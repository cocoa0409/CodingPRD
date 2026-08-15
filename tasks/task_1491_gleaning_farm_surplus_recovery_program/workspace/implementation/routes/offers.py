"""Surplus offers: publish, cancel, close (OCC-guarded), receipts."""
from decimal import Decimal, ROUND_HALF_UP
from flask import request

import errors as E
import services as svc
from db import store, stamp_new, touch, now
from errors import ApiError
from middleware import require_roles
from response import ok_obj, ok_list
from util import serialize, dec1, dec4, intervals_overlap

PC = "ProgramCoordinator"
CL = "CrewLeader"
FSO = "FoodSafetyOfficer"
GR = "GrantReviewer"

TERMINAL_OFFER = ("CLOSED", "CANCELLED", "EXPIRED")

# calculations.donation_valuation pricing table (cents per pound)
PRICE_PER_LB_CENTS = {
    "SWEET_CORN": 33,
    "APPLES": 41,
    "LEAFY_GREENS": 74,
    "TOMATOES": 58,
    "ROOT_VEG": 29,
    "WINTER_SQUASH": 36,
}
DEFAULT_PRICE_CENTS = 40


def register(app):

    @app.route("/glean/offers", methods=["POST"])
    def create_offer():
        require_roles(PC)
        fs = svc.FieldSet()
        farm_id = fs.req_str("farm_id")
        crop_code = fs.req_str("crop_code")
        estimated_lbs = fs.req_num("estimated_lbs")
        window_start = fs.req_dt("window_start")
        window_end = fs.req_dt("window_end")
        perishability_class = fs.req_enum("perishability_class", ("HIGH", "MEDIUM", "LOW"))
        requires_refrigeration = fs.req_bool("requires_refrigeration")
        # Gate 3: body FK existence
        farm = svc.fk_or_404(store.farms, farm_id, "Farm")
        # Gate 8: per-farm per-crop window overlap (non-terminal offers; adjacency ok)
        if farm is not None and window_start is not None and window_end is not None \
                and crop_code is not None:
            for o in store.offers.values():
                if o["farm_id"] != farm_id or o["crop_code"] != crop_code:
                    continue
                if o["status"] in TERMINAL_OFFER:
                    continue
                if intervals_overlap(window_start, window_end,
                                     o["window_start"], o["window_end"]):
                    raise ApiError(E.ERR_OFFER_WINDOW_OVERLAP, 422,
                                   "Farm already holds a non-terminal offer for this "
                                   "crop with an overlapping harvest window")
        # Gate 23: farm active gate
        if farm is not None and not farm["active_flag"]:
            raise ApiError(E.ERR_FARM_INACTIVE, 422,
                           "Farm active_flag is false; it may not publish new offers")
        # Gate 26: request shape
        if estimated_lbs is not None and estimated_lbs <= 0:
            fs.bad = True
        if window_start is not None and window_end is not None and window_end <= window_start:
            fs.bad = True
        fs.raise_if_bad()
        rec = {
            "farm_id": farm_id,
            "crop_code": crop_code,
            "estimated_lbs": dec1(estimated_lbs),
            "window_start": window_start,
            "window_end": window_end,
            "perishability_class": perishability_class,
            "requires_refrigeration": requires_refrigeration,
            "status": "OFFERED",
            "actual_lbs": Decimal("0.0"),
            "salvage_ratio": None,
        }
        stamp_new(rec)
        store.offers[rec["id"]] = rec
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/offers", methods=["GET"])
    def list_offers():
        require_roles(PC, GR, FSO, CL)
        page, limit, offset, total = svc.paginate(
            store.offers.values(),
            {"farm_id": request.args.get("farm_id"),
             "status": request.args.get("status")})
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/offers/<rid>", methods=["GET"])
    def get_offer(rid):
        require_roles(PC, GR, FSO, CL)
        offer = svc.get_or_404(store.offers, rid, "SurplusOffer")
        return ok_obj(serialize(offer))

    @app.route("/glean/offers/<rid>/cancel", methods=["POST"])
    def cancel_offer(rid):
        require_roles(PC)
        offer = svc.get_or_404(store.offers, rid, "SurplusOffer")
        status = offer["status"]
        if status in TERMINAL_OFFER:
            # Gate 20: terminal-state lockdown
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Offer is in terminal state %s" % status)
        if status == "GLEANED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "A GLEANED offer cannot be cancelled")
        if status == "OFFERED":
            bad = [e for e in svc.events_of_offer(rid)
                   if e["status"] in ("FULL", "IN_PROGRESS", "HARVESTED", "RECONCILED")]
            if bad:
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "An event of this offer has progressed past OPEN")
        else:  # SCHEDULED
            bad = [e for e in svc.events_of_offer(rid)
                   if e["status"] not in ("DRAFT", "OPEN", "CANCELLED")]
            if bad:
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "Every event must be DRAFT, OPEN, or CANCELLED to cancel")
        # Cascade: DRAFT/OPEN events -> CANCELLED, their PENDING/CONFIRMED
        # assignments -> DECLINED, containers and vehicles released.
        for e in svc.events_of_offer(rid):
            if e["status"] in ("DRAFT", "OPEN"):
                svc.cascade_event_cancel(e)
        offer["status"] = "CANCELLED"
        touch(offer)
        return ok_obj(serialize(offer))

    @app.route("/glean/offers/<rid>/close", methods=["POST"])
    def close_offer(rid):
        require_roles(PC)
        offer = svc.get_or_404(store.offers, rid, "SurplusOffer")
        fs = svc.FieldSet()
        expected_offer_version = fs.req_int("expected_offer_version")
        # Gate 4: state compatibility (terminal targets defer to gate 20)
        status = offer["status"]
        terminal = status in TERMINAL_OFFER
        if not terminal and status != "GLEANED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a GLEANED offer can be closed")
        if status == "GLEANED":
            bad = [e for e in svc.events_of_offer(rid)
                   if e["status"] not in ("RECONCILED", "CANCELLED")]
            if bad:
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "Every glean event must be RECONCILED or CANCELLED")
        # Gate 18: one DonationReceipt per SurplusOffer
        for r in store.receipts.values():
            if r["surplus_offer_id"] == rid:
                raise ApiError(E.ERR_DUPLICATE, 409,
                               "A DonationReceipt has already been issued for this offer")
        # Gate 19: optimistic concurrency
        if expected_offer_version is not None \
                and expected_offer_version != offer["version"]:
            raise ApiError(E.ERR_STALE_OFFER_VERSION, 412,
                           "expected_offer_version does not match the offer's version")
        # Gate 20: terminal lockdown
        if terminal:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Offer is in terminal state %s" % status)
        # Gate 25: open-incident gate
        for e in svc.events_of_offer(rid):
            for i in svc.incidents_of_event(e["id"]):
                if i["disposition"] == "OPEN":
                    raise ApiError(E.ERR_INCIDENT_OPEN, 422,
                                   "An OPEN food-safety incident blocks closing")
        fs.raise_if_bad()
        # --- final accounting ---
        svc.recompute_offer_actual(offer)
        actual = offer["actual_lbs"]
        offer["salvage_ratio"] = dec4(actual / offer["estimated_lbs"])
        resolved_condemned = Decimal("0.0")
        any_resolved = False
        for e in svc.events_of_offer(rid):
            for i in svc.incidents_of_event(e["id"]):
                if i["disposition"].startswith("RESOLVED_"):
                    any_resolved = True
                    resolved_condemned += i["condemned_lbs"]
        if any_resolved:
            receipt_lbs = (actual - resolved_condemned).quantize(Decimal("0.1"))
            if receipt_lbs < 0:
                receipt_lbs = Decimal("0.0")
        else:
            receipt_lbs = actual
        price = PRICE_PER_LB_CENTS.get(offer["crop_code"], DEFAULT_PRICE_CENTS)
        fmv = int((receipt_lbs * price).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        receipt = {
            "surplus_offer_id": rid,
            "farm_id": offer["farm_id"],
            "receipt_lbs": receipt_lbs,
            "fair_market_value_cents": fmv,
            "issued_at": now(),
        }
        stamp_new(receipt, mutable=False)
        store.receipts[receipt["id"]] = receipt
        farm = store.farms.get(offer["farm_id"])
        if farm is not None:
            farm["lifetime_donated_lbs"] = (farm["lifetime_donated_lbs"]
                                            + receipt_lbs).quantize(Decimal("0.1"))
            touch(farm)
        offer["status"] = "CLOSED"
        offer["_closed_at"] = now()
        touch(offer)
        return ok_obj(serialize(offer))

    @app.route("/glean/offers/<rid>/receipt", methods=["GET"])
    def get_offer_receipt(rid):
        require_roles(PC, GR)
        svc.get_or_404(store.offers, rid, "SurplusOffer")
        receipts = [r for r in store.receipts.values() if r["surplus_offer_id"] == rid]
        page, limit, offset, total = svc.paginate(receipts)
        return ok_list([serialize(r) for r in page], limit, offset, total)
