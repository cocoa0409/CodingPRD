"""Flight endpoints (PRD 3.5, 3.7, 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import db
import domain
from errors import ApiError, err_invalid_request, err_invalid_state, err_stale
from middleware import require_roles, require_transition_role
from response import success, paginate, sort_created
from serializers import flight_out, artwork_out, posting_out, make_good_out
from util import D, clock_now, clock_today, req_int, req_str, parse_date, \
    is_int, req_enum, rhu

bp = Blueprint("flights", __name__, url_prefix="/api")


def get_flight_or_404(fid):
    f = db.flights.get(fid)
    if f is None:
        raise ApiError("ERR_FLIGHT_NOT_FOUND", 404, "Flight not found")
    return f


@bp.route("/flights", methods=["POST"])
def create_flight():
    require_roles("SalesPlanner")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    # Family 3: body FK existence for present ids (left-to-right)
    campaign_id = body.get("campaign_id")
    if isinstance(campaign_id, str) and campaign_id not in db.campaigns:
        raise ApiError("ERR_CAMPAIGN_NOT_FOUND", 404, "Campaign not found")
    face_id = body.get("face_id")
    if isinstance(face_id, str) and face_id not in db.faces:
        raise ApiError("ERR_FACE_NOT_FOUND", 404, "Face not found")
    rate_card_id = body.get("rate_card_id")
    if isinstance(rate_card_id, str) and rate_card_id not in db.rate_cards:
        raise ApiError("ERR_RATE_CARD_NOT_FOUND", 404, "Rate card not found")
    predecessor_id = body.get("predecessor_flight_id")
    if isinstance(predecessor_id, str) and predecessor_id not in db.flights:
        raise ApiError("ERR_FLIGHT_NOT_FOUND", 404, "Flight not found")

    # Family 4: shape
    campaign_id = req_str(body, "campaign_id")
    face_id = req_str(body, "face_id")
    rate_card_id = req_str(body, "rate_card_id")
    start_date = parse_date(body.get("start_date"), "start_date")
    end_date = parse_date(body.get("end_date"), "end_date")
    if end_date < start_date:
        raise err_invalid_request("end_date must not precede start_date")
    expected_face_version = body.get("expected_face_version")
    if not is_int(expected_face_version):
        raise err_invalid_request(
            "expected_face_version is required and must be an integer")
    if predecessor_id is not None and not isinstance(predecessor_id, str):
        raise err_invalid_request("predecessor_flight_id must be a string")

    campaign = db.campaigns[campaign_id]
    face = db.faces[face_id]
    rate_card = db.rate_cards[rate_card_id]

    loop_slots = None
    if face["display_type"] == "DIGITAL":
        loop_slots = body.get("loop_slots")
        if not is_int(loop_slots) \
                or not 1 <= loop_slots <= face["loop_slots_total"]:
            raise ApiError("ERR_DIGITAL_SLOTS_REQUIRED", 400,
                           "A DIGITAL face flight requires loop_slots in "
                           "1..loop_slots_total")
    else:
        if body.get("loop_slots") is not None:
            raise ApiError("ERR_DIGITAL_SLOTS_REQUIRED", 400,
                           "A STATIC face flight forbids loop_slots")

    # Family 5: OCC on the face version (PRD 2.10)
    if expected_face_version != face["version"]:
        raise err_stale()

    # Family 7: face bookability
    if face["booking_posture"] != "OPEN" or face["current_permit_id"] is None:
        raise ApiError("ERR_FACE_NOT_BOOKABLE", 409,
                       "Face booking_posture is not OPEN or no current permit "
                       "is in force")

    # Family 8: related-entity status
    if campaign["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_CAMPAIGN_NOT_APPROVED", 409,
                       "Hold creation requires the campaign in DRAFT or "
                       "SUBMITTED")
    if rate_card["status"] != "PUBLISHED":
        raise ApiError("ERR_RATE_CARD_NOT_PUBLISHED", 409,
                       "Flight creation requires a PUBLISHED rate card")
    if predecessor_id is not None:
        predecessor = db.flights[predecessor_id]
        if predecessor["status"] not in ("LIVE", "HOLDOVER"):
            raise err_invalid_request(
                "The predecessor flight must be LIVE or HOLDOVER")
        gap = 1 if face["display_type"] == "DIGITAL" else 2
        if start_date != predecessor["end_date"] + timedelta(days=gap):
            raise err_invalid_request(
                "A renewal flight must start exactly %d day(s) after the "
                "predecessor's end_date" % gap)
    if start_date < campaign["start_date"] or end_date > campaign["end_date"]:
        raise err_invalid_request(
            "Flight dates must lie inside the campaign window")

    # Family 10: static overlap / changeover
    if domain.static_overlap_violation(face, start_date, end_date):
        raise ApiError("ERR_FACE_OVERLAP", 409,
                       "The window violates the static changeover rule against "
                       "an occupied interval")

    # Family 11: digital loop capacity
    if domain.loop_capacity_exceeded(face, start_date, end_date,
                                     loop_slots or 0):
        raise ApiError("ERR_LOOP_CAPACITY_EXCEEDED", 409,
                       "Loop slot capacity would be exceeded")

    weeks, pinned_weekly, gross = calc.flight_gross_cost(
        face, rate_card, start_date, end_date, loop_slots)
    estimated = calc.estimated_impressions(face, weeks, loop_slots)

    f = db.new_resource()
    f.update({
        "campaign_id": campaign["id"],
        "face_id": face["id"],
        "rate_card_id": rate_card["id"],
        "predecessor_flight_id": predecessor_id,
        "start_date": start_date,
        "end_date": end_date,
        "loop_slots": loop_slots,
        "held_until": clock_now() + timedelta(hours=72),
        "weeks": weeks,
        "pinned_weekly_cents": pinned_weekly,
        "gross_cents": gross,
        "discount_pct": 0,
        "net_cents": gross,
        "pinned_rate_card_version": rate_card["version"],
        "status": "HELD",
        "cancellation_fee_cents": 0,
        "missed_days": 0,
        "suspension_started_at": None,
        "suspension_days_accrued": 0,
        "holdover_weeks": 0,
        "holdover_charge_cents": 0,
        "impression_entries": [],
        "estimated_impressions": estimated,
        "delivered_impressions": 0,
        "delivery_ratio": 0,
    })
    db.flights[f["id"]] = f
    # The hold reserves occupancy: the face's occupancy basis changed.
    db.touch(face)
    return success(flight_out(f), code=201)


@bp.route("/flights/<fid>", methods=["GET"])
def get_flight(fid):
    require_roles("SalesPlanner", "SalesManager", "FinanceAnalyst",
                  "OperationsAuditor", "InventoryManager")
    f = get_flight_or_404(fid)
    return success(flight_out(f))


@bp.route("/flights/<fid>", methods=["PUT"])
def update_flight(fid):
    user_id, role = require_roles("SalesPlanner", "OperationsAuditor")
    f = get_flight_or_404(fid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    new_status = body.get("status")
    if not isinstance(new_status, str) or new_status not in (
            "HELD", "BOOKED", "ART_CLEARED", "LIVE", "MISSED", "HOLDOVER",
            "COMPLETED", "CANCELLED", "EXPIRED", "RELEASED"):
        raise err_invalid_request("status is required and must be a valid "
                                  "flight status")
    takedown_confirmed = body.get("takedown_confirmed")
    if takedown_confirmed is not None and not isinstance(takedown_confirmed,
                                                         bool):
        raise err_invalid_request("takedown_confirmed must be a boolean")

    transition = (f["status"], new_status)
    actors = {
        ("HELD", "RELEASED"): ("SalesPlanner",),
        ("BOOKED", "CANCELLED"): ("SalesPlanner",),
        ("ART_CLEARED", "CANCELLED"): ("SalesPlanner",),
        ("MISSED", "CANCELLED"): ("SalesPlanner",),
        ("HOLDOVER", "COMPLETED"): ("OperationsAuditor",),
    }
    if transition not in actors:
        raise err_invalid_state(
            "Flight cannot transition %s -> %s" % transition)
    require_transition_role(role, actors[transition])

    campaign = db.campaigns.get(f["campaign_id"])

    if transition == ("HELD", "RELEASED"):
        f["status"] = "RELEASED"
        db.touch(f)
        if campaign is not None:
            domain.check_campaign_terminal(campaign)
    elif transition in (("BOOKED", "CANCELLED"), ("ART_CLEARED", "CANCELLED")):
        days_before = (f["start_date"] - clock_today()).days
        fee = calc.cancellation_fee(f["gross_cents"], days_before)
        f["cancellation_fee_cents"] = fee
        f["status"] = "CANCELLED"
        db.touch(f)
        if campaign is not None:
            campaign["cancellation_fees_cents"] += fee
            domain.refresh_campaign(campaign)
            domain.check_campaign_terminal(campaign)
    elif transition == ("MISSED", "CANCELLED"):
        f["missed_days"] = f["weeks"] * 7
        f["status"] = "CANCELLED"
        db.touch(f)
        domain.auto_make_good(f, "MISSED_POSTING", f["gross_cents"])
        if campaign is not None:
            domain.refresh_campaign(campaign)
            domain.check_campaign_terminal(campaign)
    elif transition == ("HOLDOVER", "COMPLETED"):
        if takedown_confirmed is not True:
            raise err_invalid_request(
                "Manual completion requires takedown_confirmed=true")
        domain.complete_flight(f, with_holdover=True)

    return success(flight_out(f))


@bp.route("/flights/<fid>/confirm", methods=["POST"])
def confirm_flight(fid):
    require_roles("SalesPlanner")
    f = get_flight_or_404(fid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    expected_campaign_version = body.get("expected_campaign_version")
    if not is_int(expected_campaign_version):
        raise err_invalid_request(
            "expected_campaign_version is required and must be an integer")

    campaign = db.campaigns.get(f["campaign_id"])
    face = db.faces.get(f["face_id"])
    advertiser = db.advertisers.get(campaign["advertiser_id"]) \
        if campaign is not None else None

    # Family 5: state + OCC
    if f["status"] != "HELD":
        raise err_invalid_state("Only a HELD flight can be confirmed")
    if campaign is None or expected_campaign_version != campaign["version"]:
        raise err_stale()

    # Family 7: face bookability
    if face is None or face["booking_posture"] != "OPEN":
        raise ApiError("ERR_FACE_NOT_BOOKABLE", 409,
                       "Face booking_posture is not OPEN")

    # Family 8: related-entity status
    if campaign["status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError("ERR_CAMPAIGN_NOT_APPROVED", 409,
                       "Confirm requires the campaign in APPROVED or ACTIVE")
    if advertiser is None or advertiser["status"] != "ACTIVE":
        raise ApiError("ERR_ADVERTISER_NOT_BOOKABLE", 409,
                       "Advertiser is not ACTIVE")

    # Family 9: hold deadline
    if not clock_now() < f["held_until"]:
        raise err_invalid_request("The hold has lapsed (held_until reached)")

    # Family 10/11: re-run occupancy checks against current occupancy
    if domain.static_overlap_violation(face, f["start_date"], f["end_date"],
                                       exclude_flight_id=f["id"]):
        raise ApiError("ERR_FACE_OVERLAP", 409,
                       "The window violates the static changeover rule against "
                       "an occupied interval")
    if domain.loop_capacity_exceeded(face, f["start_date"], f["end_date"],
                                     f["loop_slots"] or 0,
                                     exclude_flight_id=f["id"]):
        raise ApiError("ERR_LOOP_CAPACITY_EXCEEDED", 409,
                       "Loop slot capacity would be exceeded")

    # Volume-discount evaluation order (PRD 3.5, pinned):
    prospective = campaign["contracted_cents"] + f["gross_cents"]
    tier = calc.volume_tier(prospective)
    net = rhu(D(f["gross_cents"] + f["holdover_charge_cents"]) * (1 - tier))

    # Family 14: credit ceiling (equality allowed)
    if advertiser["exposure_cents"] + net > advertiser["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402,
                       "Exposure after confirm would exceed the credit limit")

    f["discount_pct"] = float(tier)
    f["net_cents"] = net
    f["status"] = "BOOKED"
    db.touch(f)

    campaign["discount_pct"] = float(tier)
    domain.recompute_campaign_ledgers(campaign)
    domain.recompute_delivery_posture(campaign)
    db.touch(campaign)
    domain.recompute_exposure(advertiser)
    return success(flight_out(f))


@bp.route("/flights/<fid>/successor-flights", methods=["GET"])
def successor_flights(fid):
    require_roles("SalesPlanner", "OperationsAuditor", "InventoryManager")
    f = get_flight_or_404(fid)
    items = sort_created([x for x in db.flights.values()
                          if x["predecessor_flight_id"] == f["id"]])
    page, meta = paginate(items)
    return success([flight_out(x) for x in page], response_type="array",
                   page_meta=meta)


@bp.route("/flights/<fid>/artwork-orders", methods=["GET"])
def flight_artwork_orders(fid):
    require_roles("ProductionCoordinator", "SalesPlanner", "OperationsAuditor")
    f = get_flight_or_404(fid)
    items = sort_created([a for a in db.artwork_orders.values()
                          if a["flight_id"] == f["id"]])
    page, meta = paginate(items)
    return success([artwork_out(a) for a in page], response_type="array",
                   page_meta=meta)


@bp.route("/flights/<fid>/posting-records", methods=["GET"])
def flight_posting_records(fid):
    require_roles("FieldInstaller", "OperationsAuditor", "SalesPlanner")
    f = get_flight_or_404(fid)
    items = sort_created([p for p in db.posting_records.values()
                          if p["flight_id"] == f["id"]])
    page, meta = paginate(items)
    return success([posting_out(p) for p in page], response_type="array",
                   page_meta=meta)


@bp.route("/flights/<fid>/make-goods", methods=["GET"])
def flight_make_goods(fid):
    require_roles("OperationsAuditor", "FinanceAnalyst", "SalesPlanner")
    f = get_flight_or_404(fid)
    items = sort_created(domain.flight_make_goods(f["id"]))
    page, meta = paginate(items)
    return success([make_good_out(m) for m in page], response_type="array",
                   page_meta=meta)


@bp.route("/flights/<fid>/impression-entries", methods=["POST"])
def add_impression_entry(fid):
    require_roles("OperationsAuditor")
    f = get_flight_or_404(fid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    period_start = parse_date(body.get("period_start"), "period_start")
    period_end = parse_date(body.get("period_end"), "period_end")
    if period_end < period_start:
        raise err_invalid_request("period_end must not precede period_start")
    source = req_enum(body, "source", ("TRAFFIC_ESTIMATE", "AUDIENCE_MEASURED"))
    impressions = req_int(body, "impressions", 0)

    f["impression_entries"].append({
        "period_start": period_start,
        "period_end": period_end,
        "source": source,
        "impressions": impressions,
        "_seq": db.next_seq(),
    })
    calc.replay_delivered(f)
    db.touch(f)
    campaign = db.campaigns.get(f["campaign_id"])
    if campaign is not None:
        domain.recompute_delivery_posture(campaign)
    return success(flight_out(f), code=201)
