"""Shipments: booking, dispatch, delivery, acceptance, rejection, unwinds."""
from decimal import Decimal

from flask import Blueprint, request

from common import (ApiError, actor, as_date, as_dec, as_int, as_str,
                    bad_request, body_dict, created, fk_not_found,
                    invalid_state, not_found, ok, ok_list, ownership_err,
                    paginate, raw_body, ser)
from logic import (D0, MOISTURE_TOLERANCE_PCT, REJECTION_TOLERANCE_PCT,
                   STANDARD_CREDIT_PER_TON, current_date, current_month,
                   freight_shares, freight_total_cents, fulfillment_for,
                   lazy_expire_determination, lazy_expire_permit,
                   new_ledger_record, new_record, recompute_generator, rhu,
                   rollover_agreement, rollover_commitment, select_price,
                   sorted_items, touch)
from store import db

bp = Blueprint("shipments", __name__)


def _owner_generator_id(sh):
    ag = db.agreements.get(sh["supply_agreement_id"])
    return ag["generator_id"] if ag else None


def _owner_offtaker_id(sh):
    cm = db.commitments.get(sh["offtake_commitment_id"])
    return cm["offtaker_id"] if cm else None


def _load_shipment(sid):
    sh = db.shipments.get(sid)
    if sh is None:
        not_found("Shipment not found")
    return sh


def _check_generator_ownership(sh, uid):
    gid = _owner_generator_id(sh)
    if gid is not None and gid != uid:
        ownership_err()


def _check_offtaker_ownership(sh, uid):
    oid = _owner_offtaker_id(sh)
    if oid is not None and oid != uid:
        ownership_err()


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------

@bp.post("/api/shipments")
def book_shipment():
    uid, _ = actor({"Generator"})
    raw = raw_body()
    # stage 3 ownership: the agreement must belong to the acting Generator
    if isinstance(raw, dict):
        agid = raw.get("supply_agreement_id")
        if isinstance(agid, str):
            ag = db.agreements.get(agid)
            if ag is not None and ag["generator_id"] != uid:
                ownership_err()
    # stage 4 body well-formedness
    body = body_dict()
    ag_id = as_str(body, "supply_agreement_id")
    cm_id = as_str(body, "offtake_commitment_id")
    pickup_date = as_date(body, "pickup_date")
    distance = as_int(body, "distance_miles")
    if distance < 0:
        bad_request("distance_miles must be >= 0")
    gross = as_dec(body, "gross_tons")
    if gross <= D0:
        bad_request("gross_tons must be > 0")
    loading_moisture = as_dec(body, "loading_moisture_pct")
    expected_version = as_int(body, "expected_supply_agreement_version")
    # stage 6 foreign keys
    ag = db.agreements.get(ag_id)
    if ag is None:
        fk_not_found("supply_agreement_id does not resolve")
    cm = db.commitments.get(cm_id)
    if cm is None:
        fk_not_found("offtake_commitment_id does not resolve")
    # stage 7 optimistic concurrency
    if expected_version != ag["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION", 412,
                       "expected_supply_agreement_version is stale")
    rollover_agreement(ag)
    rollover_commitment(cm)
    # stage 8 state
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409,
                       "Agreement is not ACTIVE")
    if cm["status"] != "ACTIVE":
        raise ApiError("ERR_COMMITMENT_NOT_ACTIVE", 409,
                       "Commitment is not ACTIVE")
    # stage 10 temporal: pickup_date within inclusive term
    if not (ag["term_start"] <= pickup_date <= ag["term_end"]):
        raise ApiError("ERR_OUTSIDE_AGREEMENT_TERM", 422,
                       "pickup_date outside agreement term")
    # stage 12 referential
    if ag["stream_id"] != cm["stream_id"]:
        raise ApiError("ERR_STREAM_MISMATCH", 422,
                       "Agreement and commitment cover different streams")
    # stage 13 fiscal: quotas then price
    if (ag["booked_month_to_date_tons"] + gross > ag["committed_monthly_tons"]
            or cm["accepted_month_to_date_tons"] + gross
            > cm["committed_monthly_tons"]):
        raise ApiError("ERR_COMMITMENT_EXCEEDED", 422,
                       "Booking would exceed a monthly commitment")
    stream = db.streams.get(ag["stream_id"])
    price_entry = select_price(stream["material_type"],
                               cm["destination_state_code"], pickup_date)
    if price_entry is None:
        raise ApiError("ERR_PRICE_INDEX_GAP", 422,
                       "No market price index entry effective on pickup_date")
    # economics (computed before quota side effects)
    price_at_pickup = price_entry["price_cents_per_ton"]
    freight_total = freight_total_cents(distance)
    gen_share, broker_share = freight_shares(
        freight_total, ag["freight_share_pct_to_generator"])
    provisional = int(rhu(gross * Decimal(price_at_pickup), 0))

    rec = new_record()
    rec.update(supply_agreement_id=ag_id, offtake_commitment_id=cm_id,
               pickup_date=pickup_date, distance_miles=distance,
               gross_tons=gross, loading_moisture_pct=loading_moisture,
               destination_moisture_pct=None, destination_arsenic_ppm=None,
               price_at_pickup_cents_per_ton=price_at_pickup,
               price_at_acceptance_cents_per_ton=None,
               freight_total_cents=freight_total,
               generator_freight_share_cents=gen_share,
               broker_freight_share_cents=broker_share,
               provisional_settlement_cents=provisional,
               moisture_deduction_pct=None, net_billable_tons=None,
               final_gross_revenue_cents=None, final_generator_share_cents=None,
               final_broker_share_cents=None, generator_net_payout_cents=None,
               status="BOOKED", rejection_reason=None, void_reason=None)
    db.shipments[rec["id"]] = rec
    # quota side effect
    ag["booked_month_to_date_tons"] += gross
    touch(ag)
    return created(ser(rec))


@bp.get("/api/shipments")
def list_shipments():
    actor()
    items = sorted_items(db.shipments.values())
    aid = request.args.get("supply_agreement_id")
    cid = request.args.get("offtake_commitment_id")
    st = request.args.get("status")
    if aid is not None:
        items = [r for r in items if r["supply_agreement_id"] == aid]
    if cid is not None:
        items = [r for r in items if r["offtake_commitment_id"] == cid]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, meta = paginate(items)
    return ok_list([ser(r) for r in page], meta)


@bp.get("/api/shipments/<sid>")
def get_shipment(sid):
    actor()
    return ok(ser(_load_shipment(sid)))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

@bp.post("/api/shipments/<sid>/dispatch")
def dispatch_shipment(sid):
    uid, _ = actor({"Generator"})
    sh = db.shipments.get(sid)
    if sh is not None:
        _check_generator_ownership(sh, uid)
    if sh is None:
        not_found("Shipment not found")
    if sh["status"] != "BOOKED":
        invalid_state()
    ag = db.agreements.get(sh["supply_agreement_id"])
    cm = db.commitments.get(sh["offtake_commitment_id"])
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409,
                       "Agreement is not ACTIVE")
    if cm["status"] != "ACTIVE":
        raise ApiError("ERR_COMMITMENT_NOT_ACTIVE", 409,
                       "Commitment is not ACTIVE")
    today = current_date()
    stream = db.streams.get(ag["stream_id"])
    # stage 9 safety: eligibility then permit
    eligible = False
    for d in db.determinations.values():
        if d["stream_id"] != ag["stream_id"]:
            continue
        lazy_expire_determination(d)
        if (d["state_code"] == cm["destination_state_code"]
                and d["status"] == "APPROVED"
                and d["valid_from"] <= today < d["valid_until"]):
            eligible = True
    if not eligible:
        raise ApiError("ERR_REUSE_NOT_ELIGIBLE", 422,
                       "No APPROVED eligibility determination covers the destination")
    permitted = False
    for p in db.permits.values():
        lazy_expire_permit(p)
        if (p["state_code"] == cm["destination_state_code"]
                and p["material_type"] == stream["material_type"]
                and p["status"] == "ACTIVE"
                and p["issued_on"] <= today <= p["expires_on"]):
            permitted = True
    if not permitted:
        raise ApiError("ERR_PERMIT_REQUIRED", 422,
                       "No ACTIVE state permit covers the destination and material")
    # stage 10 temporal
    if not (ag["term_start"] <= today <= ag["term_end"]):
        raise ApiError("ERR_OUTSIDE_AGREEMENT_TERM", 422,
                       "Current logical date outside agreement term")
    sh["status"] = "DISPATCHED"
    touch(sh)
    return ok(ser(sh))


# ---------------------------------------------------------------------------
# Deliver / accept / reject (Offtaker)
# ---------------------------------------------------------------------------

@bp.post("/api/shipments/<sid>/deliver")
def deliver_shipment(sid):
    uid, _ = actor({"Offtaker"})
    sh = db.shipments.get(sid)
    if sh is not None:
        _check_offtaker_ownership(sh, uid)
    body = body_dict()
    moist = as_dec(body, "destination_moisture_pct")
    ars = as_dec(body, "destination_arsenic_ppm")
    if sh is None:
        not_found("Shipment not found")
    if sh["status"] != "DISPATCHED":
        invalid_state()
    sh["destination_moisture_pct"] = moist
    sh["destination_arsenic_ppm"] = ars
    sh["status"] = "DELIVERED"
    touch(sh)
    return ok(ser(sh))


@bp.post("/api/shipments/<sid>/accept")
def accept_shipment(sid):
    uid, _ = actor({"Offtaker"})
    sh = db.shipments.get(sid)
    if sh is not None:
        _check_offtaker_ownership(sh, uid)
    if sh is None:
        not_found("Shipment not found")
    if sh["status"] != "DELIVERED":
        invalid_state()
    ag = db.agreements.get(sh["supply_agreement_id"])
    cm = db.commitments.get(sh["offtake_commitment_id"])
    stream = db.streams.get(ag["stream_id"])
    # quality gate (stage 11)
    if (sh["destination_moisture_pct"] > cm["max_moisture_pct"] + MOISTURE_TOLERANCE_PCT
            or sh["destination_arsenic_ppm"] > cm["max_arsenic_ppm"]):
        raise ApiError("ERR_QUALITY_OUT_OF_SPEC", 422,
                       "Destination measurements breach the quality spec")
    # shipment_settlement final variant — pinned evaluation order
    deduction = max(D0, sh["destination_moisture_pct"] - cm["max_moisture_pct"])
    net_billable = rhu(sh["gross_tons"] * (Decimal(1) - deduction / Decimal(100)), 3)
    price_entry = select_price(stream["material_type"],
                               cm["destination_state_code"], current_date())
    price = (price_entry["price_cents_per_ton"] if price_entry is not None
             else sh["price_at_pickup_cents_per_ton"])
    final_gross = int(rhu(net_billable * Decimal(price), 0))
    final_gen = int(rhu(Decimal(final_gross)
                        * ag["revenue_share_pct_to_generator"], 0))
    final_broker = final_gross - final_gen
    net_payout = final_gen - sh["generator_freight_share_cents"]

    sh["moisture_deduction_pct"] = deduction
    sh["net_billable_tons"] = net_billable
    sh["price_at_acceptance_cents_per_ton"] = price
    sh["final_gross_revenue_cents"] = final_gross
    sh["final_generator_share_cents"] = final_gen
    sh["final_broker_share_cents"] = final_broker
    sh["generator_net_payout_cents"] = net_payout
    sh["status"] = "ACCEPTED"
    touch(sh)
    # cascade: counters
    rollover_agreement(ag)
    ag["delivered_month_to_date_tons"] += net_billable
    ag["fulfillment_status"] = fulfillment_for(ag)
    touch(ag)
    rollover_commitment(cm)
    cm["accepted_month_to_date_tons"] += net_billable
    touch(cm)
    # cascade: sustainability credit ACCRUAL
    entry = new_ledger_record()
    entry.update(generator_id=ag["generator_id"], shipment_id=sh["id"],
                 entry_type="ACCRUAL", period=current_month(),
                 tons_credited=net_billable,
                 credits=rhu(net_billable * STANDARD_CREDIT_PER_TON, 2))
    db.credit_entries[entry["id"]] = entry
    recompute_generator(ag["generator_id"])
    db.accepted_periods[sh["id"]] = current_month()
    return ok(ser(sh))


@bp.post("/api/shipments/<sid>/reject")
def reject_shipment(sid):
    uid, _ = actor({"Offtaker"})
    sh = db.shipments.get(sid)
    if sh is not None:
        _check_offtaker_ownership(sh, uid)
    reason = as_str(body_dict(), "reason")
    if sh is None:
        not_found("Shipment not found")
    if sh["status"] != "DELIVERED":
        invalid_state()
    sh["status"] = "REJECTED"
    sh["rejection_reason"] = reason
    touch(sh)
    cm = db.commitments.get(sh["offtake_commitment_id"])
    cm["cumulative_rejected_tons"] += sh["gross_tons"]
    touch(cm)
    # rejection_tolerance_posture: strictly-greater comparison
    tolerance = rhu(Decimal(cm["committed_monthly_tons"]) * REJECTION_TOLERANCE_PCT, 3)
    if cm["status"] == "ACTIVE" and cm["cumulative_rejected_tons"] > tolerance:
        cm["status"] = "SUSPENDED"
        touch(cm)
        # conditional cascade: cancel BOOKED siblings, release their quota
        siblings = [s for s in sorted_items(db.shipments.values())
                    if s["offtake_commitment_id"] == cm["id"]
                    and s["status"] == "BOOKED"]
        for sib in siblings:
            sib["status"] = "CANCELLED"
            touch(sib)
            sag = db.agreements.get(sib["supply_agreement_id"])
            if sag is not None:
                rollover_agreement(sag)
                sag["booked_month_to_date_tons"] -= sib["gross_tons"]
                touch(sag)
    return ok(ser(sh))


# ---------------------------------------------------------------------------
# Recondition / redeliver / dispose / cancel (Generator)
# ---------------------------------------------------------------------------

@bp.post("/api/shipments/<sid>/recondition")
def recondition_shipment(sid):
    uid, _ = actor({"Generator"})
    sh = db.shipments.get(sid)
    if sh is not None:
        _check_generator_ownership(sh, uid)
    if sh is None:
        not_found("Shipment not found")
    if sh["status"] != "REJECTED":
        invalid_state()
    sh["status"] = "RECONDITIONING"
    touch(sh)
    return ok(ser(sh))


@bp.post("/api/shipments/<sid>/redeliver")
def redeliver_shipment(sid):
    uid, _ = actor({"Generator"})
    sh = db.shipments.get(sid)
    if sh is not None:
        _check_generator_ownership(sh, uid)
    body = body_dict()
    moist = as_dec(body, "destination_moisture_pct")
    ars = as_dec(body, "destination_arsenic_ppm")
    if sh is None:
        not_found("Shipment not found")
    if sh["status"] != "RECONDITIONING":
        invalid_state()
    sh["destination_moisture_pct"] = moist
    sh["destination_arsenic_ppm"] = ars
    sh["status"] = "DELIVERED"
    touch(sh)
    return ok(ser(sh))


@bp.post("/api/shipments/<sid>/dispose")
def dispose_shipment(sid):
    uid, _ = actor({"Generator"})
    sh = db.shipments.get(sid)
    if sh is not None:
        _check_generator_ownership(sh, uid)
    if sh is None:
        not_found("Shipment not found")
    if sh["status"] != "REJECTED":
        invalid_state()
    sh["status"] = "DISPOSED"
    touch(sh)
    return ok(ser(sh))


@bp.post("/api/shipments/<sid>/cancel")
def cancel_shipment(sid):
    uid, _ = actor({"Generator"})
    sh = db.shipments.get(sid)
    if sh is not None:
        _check_generator_ownership(sh, uid)
    if sh is None:
        not_found("Shipment not found")
    if sh["status"] != "BOOKED":
        invalid_state()
    sh["status"] = "CANCELLED"
    touch(sh)
    ag = db.agreements.get(sh["supply_agreement_id"])
    if ag is not None:
        rollover_agreement(ag)
        ag["booked_month_to_date_tons"] = max(
            D0, ag["booked_month_to_date_tons"] - sh["gross_tons"])
        touch(ag)
    return ok(ser(sh))


# ---------------------------------------------------------------------------
# Void (BrokerOps)
# ---------------------------------------------------------------------------

@bp.post("/api/shipments/<sid>/void")
def void_shipment(sid):
    actor({"BrokerOps"})
    sh = db.shipments.get(sid)
    reason = as_str(body_dict(), "reason")
    if sh is None:
        not_found("Shipment not found")
    if sh["status"] != "ACCEPTED":
        invalid_state()
    sh["status"] = "VOIDED"
    sh["void_reason"] = reason
    touch(sh)
    ag = db.agreements.get(sh["supply_agreement_id"])
    cm = db.commitments.get(sh["offtake_commitment_id"])
    net = sh["net_billable_tons"]
    # credit reversal: credits equal to the original ACCRUAL of this shipment
    accrual = next((e for e in sorted_items(db.credit_entries.values())
                    if e["shipment_id"] == sh["id"]
                    and e["entry_type"] == "ACCRUAL"), None)
    reversal_credits = accrual["credits"] if accrual is not None else D0
    entry = new_ledger_record()
    entry.update(generator_id=ag["generator_id"], shipment_id=sh["id"],
                 entry_type="REVERSAL", period=current_month(),
                 tons_credited=net, credits=reversal_credits)
    db.credit_entries[entry["id"]] = entry
    recompute_generator(ag["generator_id"])
    db.accepted_periods.pop(sh["id"], None)
    rollover_agreement(ag)
    ag["delivered_month_to_date_tons"] = max(
        D0, ag["delivered_month_to_date_tons"] - net)
    ag["fulfillment_status"] = fulfillment_for(ag)
    touch(ag)
    rollover_commitment(cm)
    cm["accepted_month_to_date_tons"] = max(
        D0, cm["accepted_month_to_date_tons"] - net)
    touch(cm)
    return ok(ser(sh))


@bp.get("/api/shipments/<sid>/credit-entries")
def shipment_credit_entries(sid):
    actor()
    if sid not in db.shipments:
        not_found("Shipment not found")
    items = [e for e in sorted_items(db.credit_entries.values())
             if e["shipment_id"] == sid]
    page, meta = paginate(items)
    return ok_list([ser(r) for r in page], meta)
