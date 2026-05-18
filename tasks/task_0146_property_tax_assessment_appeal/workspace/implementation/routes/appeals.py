"""Appeal and Hearing endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from config import GRACE_MIN, HEARING_MAX_DURATION_MIN, OFFICER_BUFFER_MIN
from db import store
from errors import raise_error
from middleware import require_owner_of_property, require_roles
from response import success
from routes._helpers import (
    bump,
    check_version,
    get_json_body,
    parse_number,
    require_appeal,
    require_assessment,
    require_field,
    require_hearing_officer,
    require_property,
)
from services.calculations import compute_tax_bill_fields
from services.serializers import serialize_appeal, serialize_hearing
from utils import new_uuid, parse_iso_datetime, round_half_up

appeals_bp = Blueprint("appeals", __name__)

VALID_GROUNDS = {"OVER_MARKET", "EXEMPTION_DENIED", "CAP_MISAPPLIED", "CLERICAL_ERROR"}
VALID_OUTCOMES = {"UPHELD", "REDUCED", "INCREASED"}
VALID_ROOMS = {"ROOM_A", "ROOM_B", "ROOM_C"}


def _open_appeals_on_assessment(assessment_id, exclude=None):
    return [
        a for a in store.appeals.values()
        if a["assessment_id"] == assessment_id
        and a["status"] in ("FILED", "SCHEDULED", "HEARD")
        and (exclude is None or a["id"] != exclude)
    ]


def _hearing_for_appeal(appeal_id):
    """Find the live hearing for the appeal (excludes CANCELLED)."""
    for h in store.hearings.values():
        if h["appeal_id"] != appeal_id and h.get("appeal_id") != appeal_id:
            continue
        if h["appeal_id"] != appeal_id:
            continue
        if h["status"] == "CANCELLED":
            continue
        return h
    return None


def _hearing_for_appeal_any(appeal_id):
    """Find a hearing for an appeal (any status; prefer non-cancelled)."""
    live = None
    cancelled = None
    for h in store.hearings.values():
        if h["appeal_id"] != appeal_id:
            continue
        if h["status"] == "CANCELLED":
            cancelled = h
        else:
            live = h
    return live or cancelled


@appeals_bp.post("/properties/<property_id>/appeals")
def file_appeal(property_id):
    require_roles({"Owner"})
    require_property(property_id)
    require_owner_of_property(property_id)
    body = get_json_body()
    assessment_id = require_field(body, "assessment_id")
    if not isinstance(assessment_id, str):
        raise_error("ERR_VALIDATION_FAILED", "assessment_id must be a string")
    # FK existence
    assessment = store.assessments.get(assessment_id)
    if assessment is None or assessment["property_id"] != property_id:
        raise_error("ERR_NOT_FOUND", f"assessment '{assessment_id}' not found")

    grounds = require_field(body, "filed_grounds")
    if grounds not in VALID_GROUNDS:
        raise_error("ERR_VALIDATION_FAILED", "filed_grounds is invalid")

    claimed = parse_number(require_field(body, "claimed_value"), "claimed_value")
    if claimed < Decimal("0"):
        raise_error("ERR_VALIDATION_FAILED", "claimed_value must be non-negative")
    claimed = round_half_up(claimed, 2)

    # State check
    if assessment["status"] not in ("ISSUED", "UNDER_APPEAL"):
        raise_error("ERR_INVALID_STATE", "assessment is not in ISSUED/UNDER_APPEAL")

    # Appeal window
    now = store.clock.now()
    window_close = assessment.get("appeal_window_closes_at")
    if window_close is None or now >= window_close:
        raise_error("ERR_APPEAL_WINDOW_CLOSED")

    with store.lock:
        rec = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "property_id": property_id,
            "assessment_id": assessment_id,
            "assessment_version": assessment["version"],
            "owner_id": g.user_id,
            "filed_grounds": grounds,
            "claimed_value": claimed,
            "status": "FILED",
            "decision_outcome": None,
            "decided_value": None,
            "captured_capped_value": assessment["capped_value"],  # internal pin
        }
        store.appeals[rec["id"]] = rec
        # Cascade: Assessment ISSUED -> UNDER_APPEAL
        if assessment["status"] == "ISSUED":
            assessment["status"] = "UNDER_APPEAL"
            bump(assessment)
    return success(serialize_appeal(rec), status_code=201)


@appeals_bp.get("/properties/<property_id>/appeals/<appeal_id>")
def get_appeal(property_id, appeal_id):
    require_roles({"Assessor", "Treasurer", "HearingOfficer", "Owner"})
    rec = require_appeal(property_id, appeal_id)
    return success(serialize_appeal(rec))


@appeals_bp.get("/properties/<property_id>/appeals/<appeal_id>/hearing")
def get_hearing(property_id, appeal_id):
    require_roles({"Assessor", "Treasurer", "HearingOfficer", "Owner"})
    require_appeal(property_id, appeal_id)
    hearing = _hearing_for_appeal_any(appeal_id)
    if hearing is None:
        raise_error("ERR_NOT_FOUND", "hearing not found for this appeal")
    return success(serialize_hearing(hearing))


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


@appeals_bp.post("/properties/<property_id>/appeals/<appeal_id>/schedule")
def schedule_hearing(property_id, appeal_id):
    require_roles({"Treasurer"})
    rec = require_appeal(property_id, appeal_id)
    body = get_json_body()

    if rec["status"] != "FILED":
        raise_error("ERR_INVALID_STATE", "appeal is not in FILED state")

    # Officer existence
    officer_id = require_field(body, "officer_id")
    if not isinstance(officer_id, str):
        raise_error("ERR_VALIDATION_FAILED", "officer_id must be a string")
    officer = require_hearing_officer(officer_id)
    if not officer.get("active", True):
        raise_error("ERR_VALIDATION_FAILED", "officer is not active")

    start_raw = require_field(body, "scheduled_start")
    end_raw = require_field(body, "scheduled_end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise_error("ERR_VALIDATION_FAILED", "scheduled_start/scheduled_end must be ISO strings")
    try:
        start = parse_iso_datetime(start_raw)
        end = parse_iso_datetime(end_raw)
    except Exception:
        raise_error("ERR_HEARING_INTERVAL_INVALID")

    if end <= start:
        raise_error("ERR_HEARING_INTERVAL_INVALID")
    duration_min = (end - start).total_seconds() / 60.0
    if duration_min > HEARING_MAX_DURATION_MIN:
        raise_error("ERR_HEARING_INTERVAL_INVALID")

    room = require_field(body, "hearing_room")
    if room not in VALID_ROOMS:
        raise_error("ERR_VALIDATION_FAILED", "hearing_room is invalid")

    # Room overlap
    for h in store.hearings.values():
        if h["status"] != "SCHEDULED":
            continue
        if h["hearing_room"] != room:
            continue
        if _intervals_overlap(start, end, h["scheduled_start"], h["scheduled_end"]):
            raise_error("ERR_ROOM_DOUBLE_BOOKED")

    # Officer buffer
    buffer_delta = timedelta(minutes=OFFICER_BUFFER_MIN)
    for h in store.hearings.values():
        if h["status"] != "SCHEDULED":
            continue
        if h["officer_id"] != officer_id:
            continue
        # gap edge-to-edge: if intervals overlap, gap is negative
        if h["scheduled_end"] <= start:
            gap = start - h["scheduled_end"]
        elif end <= h["scheduled_start"]:
            gap = h["scheduled_start"] - end
        else:
            # Overlap
            raise_error("ERR_OFFICER_BUFFER_VIOLATED")
        if gap < buffer_delta:
            raise_error("ERR_OFFICER_BUFFER_VIOLATED")

    # Segregation of duties: officer must not equal Assessor who issued the assessment
    assessment = store.assessments.get(rec["assessment_id"])
    if assessment is None:
        raise_error("ERR_NOT_FOUND")
    issued_by = assessment.get("issued_by_user_id")
    if issued_by is not None and issued_by == officer_id:
        raise_error("ERR_BOE_OFFICER_CONFLICT")

    check_version(rec, body)

    with store.lock:
        now = store.clock.now()
        hearing = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "appeal_id": rec["id"],
            "property_id": property_id,
            "scheduled_start": start,
            "scheduled_end": end,
            "hearing_room": room,
            "officer_id": officer_id,
            "status": "SCHEDULED",
        }
        store.hearings[hearing["id"]] = hearing
        rec["status"] = "SCHEDULED"
        bump(rec)
    return success(serialize_appeal(rec))


@appeals_bp.post("/properties/<property_id>/appeals/<appeal_id>/conduct")
def conduct_hearing(property_id, appeal_id):
    require_roles({"HearingOfficer"})
    rec = require_appeal(property_id, appeal_id)
    body = get_json_body()
    if rec["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", "appeal is not SCHEDULED")
    hearing = _hearing_for_appeal(appeal_id)
    if hearing is None:
        raise_error("ERR_NOT_FOUND", "live hearing not found")

    # Officer mismatch
    if g.user_id != hearing["officer_id"]:
        raise_error("ERR_OFFICER_MISMATCH")

    now = store.clock.now()
    grace_end = hearing["scheduled_end"] + timedelta(minutes=GRACE_MIN)
    if now < hearing["scheduled_start"] or now >= grace_end:
        raise_error("ERR_INVALID_STATE", "current time is outside the hearing window")

    check_version(rec, body)

    with store.lock:
        rec["status"] = "HEARD"
        bump(rec)
        hearing["status"] = "CONDUCTED"
        bump(hearing)
    return success(serialize_appeal(rec))


def _refund_first(bill, excess: Decimal):
    """Refund oldest APPLIED payments until cumulative >= excess.

    Last refund may be partial: split a Payment into two rows.
    """
    payments = [p for p in store.payments.values() if p["tax_bill_id"] == bill["id"] and p["status"] == "APPLIED"]
    payments.sort(key=lambda p: (p["applied_at"], p["id"]))
    refunded_total = Decimal("0")
    now = store.clock.now()
    for p in payments:
        if refunded_total >= excess:
            break
        amt = Decimal(str(p["amount"]))
        remaining_needed = excess - refunded_total
        if amt <= remaining_needed:
            # Full refund of this payment
            p["status"] = "REFUNDED"
            p["refund_reason"] = "APPEAL_REDUCED"
            refunded_total += amt
        else:
            # Partial: split into APPLIED remainder + REFUNDED chunk
            refunded_chunk = remaining_needed
            remainder = amt - refunded_chunk
            # Convert this payment into REFUNDED chunk
            p["amount"] = refunded_chunk
            p["status"] = "REFUNDED"
            p["refund_reason"] = "APPEAL_REDUCED"
            # Create a new APPLIED row preserving original applied_at
            new_p = {
                "id": new_uuid(),
                "created_at": now,
                "tax_bill_id": bill["id"],
                "amount": remainder,
                "applied_at": p["applied_at"],
                "status": "APPLIED",
                "refund_reason": None,
            }
            store.payments[new_p["id"]] = new_p
            refunded_total += refunded_chunk


@appeals_bp.post("/properties/<property_id>/appeals/<appeal_id>/decide")
def decide_appeal(property_id, appeal_id):
    require_roles({"HearingOfficer"})
    rec = require_appeal(property_id, appeal_id)
    body = get_json_body()
    if rec["status"] != "HEARD":
        raise_error("ERR_INVALID_STATE", "appeal is not HEARD")
    hearing = _hearing_for_appeal_any(appeal_id)
    if hearing is None:
        raise_error("ERR_NOT_FOUND", "hearing not found")
    if g.user_id != hearing["officer_id"]:
        raise_error("ERR_OFFICER_MISMATCH")

    outcome = require_field(body, "decision_outcome")
    if outcome not in VALID_OUTCOMES:
        raise_error("ERR_VALIDATION_FAILED", "decision_outcome is invalid")
    decided_value = parse_number(require_field(body, "decided_value"), "decided_value")
    if decided_value < Decimal("0"):
        raise_error("ERR_VALIDATION_FAILED", "decided_value must be non-negative")
    decided_value = round_half_up(decided_value, 2)

    # Decision-value consistency vs captured capped_value at FILED time
    captured = rec.get("captured_capped_value")
    if captured is None:
        # Fallback: use Assessment's current capped_value
        assessment = store.assessments.get(rec["assessment_id"])
        captured = assessment["capped_value"] if assessment else Decimal("0")
    captured = Decimal(str(captured))
    if outcome == "REDUCED" and not decided_value < captured:
        raise_error("ERR_DECISION_VALUE_INCONSISTENT")
    if outcome == "INCREASED" and not decided_value > captured:
        raise_error("ERR_DECISION_VALUE_INCONSISTENT")
    if outcome == "UPHELD" and decided_value != captured:
        raise_error("ERR_DECISION_VALUE_INCONSISTENT")

    check_version(rec, body)

    with store.lock:
        now = store.clock.now()
        rec["status"] = "DECIDED"
        rec["decision_outcome"] = outcome
        rec["decided_value"] = decided_value
        bump(rec)

        # Cascade: update Assessment capped_value
        assessment = store.assessments.get(rec["assessment_id"])
        if assessment is not None:
            if outcome in ("REDUCED", "INCREASED"):
                old_capped = Decimal(str(assessment["capped_value"]))
                assessment["capped_value"] = decided_value
                bump(assessment)
                capped_changed = old_capped != decided_value
            else:
                capped_changed = False

            # Recompute TaxBill for (property, roll_year) if exists
            bill = None
            for tb in store.tax_bills.values():
                if tb["property_id"] != property_id:
                    continue
                if tb["roll_year"] != assessment["roll_year"]:
                    continue
                bill = tb
                break

            if bill is not None:
                old_payments = Decimal(str(bill.get("total_payments_applied") or 0))
                compute_tax_bill_fields(bill, recompute_stack=True)
                new_base = Decimal(str(bill["base_tax_amount"]))
                if outcome == "REDUCED" and old_payments > new_base:
                    excess = old_payments - new_base
                    _refund_first(bill, excess)
                    compute_tax_bill_fields(bill, recompute_stack=True)
                # Status adjustment after recompute
                if bill["status"] not in ("PAID", "IN_DEFERRAL", "DELINQUENT"):
                    if bill["amount_due"] == Decimal("0") and bill["total_payments_applied"] > Decimal("0"):
                        bill["status"] = "PAID"
                    elif bill["total_payments_applied"] > Decimal("0") and bill["amount_due"] > Decimal("0"):
                        bill["status"] = "PARTIALLY_PAID"
                bump(bill)

            # If no remaining open appeals on Assessment, auto-FINALIZE
            still_open = _open_appeals_on_assessment(rec["assessment_id"], exclude=rec["id"])
            if not still_open and assessment["status"] == "UNDER_APPEAL":
                assessment["status"] = "FINALIZED"
                assessment["finalized_at"] = now
                bump(assessment)

    return success(serialize_appeal(rec))


@appeals_bp.post("/properties/<property_id>/appeals/<appeal_id>/withdraw")
def withdraw_appeal(property_id, appeal_id):
    require_roles({"Owner"})
    rec = require_appeal(property_id, appeal_id)
    require_owner_of_property(property_id)
    body = get_json_body()
    if rec["status"] not in ("FILED", "SCHEDULED", "HEARD"):
        raise_error("ERR_INVALID_STATE", "appeal cannot be withdrawn in its current state")
    # Ownership: the owner who filed must equal acting user
    if rec["owner_id"] != g.user_id:
        raise_error("ERR_OWNERSHIP_MISMATCH")
    check_version(rec, body)

    with store.lock:
        now = store.clock.now()
        was_scheduled = rec["status"] == "SCHEDULED"
        rec["status"] = "WITHDRAWN"
        bump(rec)
        if was_scheduled:
            hearing = _hearing_for_appeal(appeal_id)
            if hearing is not None:
                hearing["status"] = "CANCELLED"
                bump(hearing)

        # Possibly revert Assessment UNDER_APPEAL -> ISSUED
        assessment = store.assessments.get(rec["assessment_id"])
        if assessment is not None and assessment["status"] == "UNDER_APPEAL":
            still_open = _open_appeals_on_assessment(rec["assessment_id"], exclude=rec["id"])
            if not still_open:
                assessment["status"] = "ISSUED"
                bump(assessment)
    return success(serialize_appeal(rec))
