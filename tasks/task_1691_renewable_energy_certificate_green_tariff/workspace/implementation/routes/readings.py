"""Meter reading endpoints: submission, attestation, acceptance, void."""

from datetime import timedelta

from flask import Blueprint, request

from errors import raise_err, ERR_VALIDATION, ERR_GENERATOR_NOT_ACTIVE, \
    ERR_INVALID_READING_STATE, ERR_SELF_ATTESTATION, ERR_PERIOD_INVERTED, \
    ERR_FUTURE_PERIOD, ERR_READING_PERIOD_OVERLAP, \
    ERR_ATTESTATION_WINDOW_EXPIRED, ERR_QUANTITY_INVALID, \
    ERR_READING_ALREADY_MINTED
from store import STORE, new_id, next_seq, now_ts, clock_now
from util import auth, require_role, forbidden, ok_object, body_json, \
    req_str, req_int, opt_str, parse_iso, get_or_404
from services import touch
from routes.generators import list_with_serializer

bp = Blueprint("readings", __name__)

ATTESTATION_WINDOW_DAYS = 30
LIVE_OVERLAP_STATUSES = ("SUBMITTED", "ATTESTED", "ACCEPTED")


def serialize_reading(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


@bp.post("/greenpower/meter-readings")
def create_reading():
    uid, role = auth()
    require_role(role, "GeneratorOperator")
    body = body_json()
    # Ownership (raw-value match): caller operates the named generator.
    generator_id = body.get("generator_id")
    if isinstance(generator_id, str) and uid != generator_id:
        forbidden("A GeneratorOperator may only submit readings for their own generator")
    generator_id = req_str(body, "generator_id")
    period_start_raw = req_str(body, "period_start")
    period_end_raw = req_str(body, "period_end")
    period_start = parse_iso(period_start_raw, "period_start")
    period_end = parse_iso(period_end_raw, "period_end")
    metered_kwh = req_int(body, "metered_kwh")

    gen = get_or_404(STORE["generators"], generator_id, "Generator")

    if gen["status"] != "ACTIVE":
        raise_err(ERR_GENERATOR_NOT_ACTIVE,
                  "Meter readings may only be submitted for an ACTIVE generator")
    if period_end <= period_start:
        raise_err(ERR_PERIOD_INVERTED, "period_end must be strictly after period_start")
    if period_end > clock_now():
        raise_err(ERR_FUTURE_PERIOD, "period_end may not be later than the logical clock")
    for existing in STORE["readings"].values():
        if existing["generator_id"] != generator_id:
            continue
        if existing["status"] not in LIVE_OVERLAP_STATUSES:
            continue
        if period_start < existing["_period_end_dt"] and existing["_period_start_dt"] < period_end:
            raise_err(ERR_READING_PERIOD_OVERLAP,
                      "Reading period overlaps an existing non-terminal reading")
    if metered_kwh <= 0:
        raise_err(ERR_QUANTITY_INVALID, "metered_kwh must be a positive integer")

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "generator_id": generator_id,
        "period_start": period_start_raw,
        "period_end": period_end_raw,
        "metered_kwh": metered_kwh,
        "status": "SUBMITTED",
        "submitted_by_user_id": uid,
        "attested_by_user_id": None,
        "rejection_reason": None,
        "minted": False,
        "minted_vintage_month": None,
        "_period_start_dt": period_start,
        "_period_end_dt": period_end,
        "_seq": next_seq(),
    }
    STORE["readings"][rec["id"]] = rec
    return ok_object(serialize_reading(rec), 201)


@bp.get("/greenpower/meter-readings")
def list_readings():
    auth()
    filters = {
        "generator_id": request.args.get("generator_id"),
        "status": request.args.get("status"),
    }
    return list_with_serializer(list(STORE["readings"].values()), filters,
                                serialize_reading)


@bp.get("/greenpower/meter-readings/<rid>")
def get_reading(rid):
    auth()
    rec = get_or_404(STORE["readings"], rid, "MeterReading")
    return ok_object(serialize_reading(rec))


@bp.post("/greenpower/meter-readings/<rid>/attest")
def attest_reading(rid):
    uid, role = auth()
    require_role(role, "MeterAttester")
    rec = get_or_404(STORE["readings"], rid, "MeterReading")
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_READING_STATE, "Attestation requires a SUBMITTED reading")
    if uid == rec["submitted_by_user_id"]:
        raise_err(ERR_SELF_ATTESTATION,
                  "An attester may not attest a reading they submitted")
    if clock_now() > rec["_period_end_dt"] + timedelta(days=ATTESTATION_WINDOW_DAYS):
        raise_err(ERR_ATTESTATION_WINDOW_EXPIRED,
                  "Attestation window closed 30 days after period_end")
    rec["status"] = "ATTESTED"
    rec["attested_by_user_id"] = uid
    touch(rec)
    return ok_object(serialize_reading(rec))


@bp.post("/greenpower/meter-readings/<rid>/reject")
def reject_reading(rid):
    uid, role = auth()
    require_role(role, "MeterAttester")
    rec = get_or_404(STORE["readings"], rid, "MeterReading")
    if rec["status"] not in ("SUBMITTED", "ATTESTED"):
        raise_err(ERR_INVALID_READING_STATE,
                  "Rejection requires a SUBMITTED or ATTESTED reading")
    if uid == rec["submitted_by_user_id"]:
        raise_err(ERR_SELF_ATTESTATION,
                  "An attester may not reject a reading they submitted")
    body = body_json()
    rec["rejection_reason"] = opt_str(body, "reason")
    if rec["status"] == "ATTESTED":
        rec["attested_by_user_id"] = None
    rec["status"] = "REJECTED"
    touch(rec)
    return ok_object(serialize_reading(rec))


@bp.post("/greenpower/meter-readings/<rid>/resubmit")
def resubmit_reading(rid):
    uid, role = auth()
    require_role(role, "GeneratorOperator")
    rec = get_or_404(STORE["readings"], rid, "MeterReading")
    if uid != rec["submitted_by_user_id"]:
        forbidden("Only the submitting operator may resubmit this reading")
    if rec["status"] != "REJECTED":
        raise_err(ERR_INVALID_READING_STATE, "Resubmission requires a REJECTED reading")
    rec["status"] = "SUBMITTED"
    rec["rejection_reason"] = None
    touch(rec)
    return ok_object(serialize_reading(rec))


@bp.post("/greenpower/meter-readings/<rid>/accept")
def accept_reading(rid):
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    rec = get_or_404(STORE["readings"], rid, "MeterReading")
    if rec["status"] != "ATTESTED":
        raise_err(ERR_INVALID_READING_STATE, "Acceptance requires an ATTESTED reading")
    gen = get_or_404(STORE["generators"], rec["generator_id"], "Generator")
    if gen["status"] != "ACTIVE":
        raise_err(ERR_GENERATOR_NOT_ACTIVE,
                  "Readings of a non-ACTIVE generator cannot be accepted")
    rec["status"] = "ACCEPTED"
    touch(rec)
    touch(gen)
    return ok_object(serialize_reading(rec))


@bp.post("/greenpower/meter-readings/<rid>/void")
def void_reading(rid):
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    rec = get_or_404(STORE["readings"], rid, "MeterReading")
    if rec["status"] != "ACCEPTED":
        raise_err(ERR_INVALID_READING_STATE, "Voiding requires an ACCEPTED reading")
    if rec["minted"]:
        raise_err(ERR_READING_ALREADY_MINTED,
                  "A reading consumed by a mint run cannot be voided")
    body = body_json()
    reason = opt_str(body, "reason")
    if reason is not None:
        rec["rejection_reason"] = reason
    rec["status"] = "VOIDED"
    touch(rec)
    gen = STORE["generators"].get(rec["generator_id"])
    if gen is not None:
        touch(gen)
    return ok_object(serialize_reading(rec))
