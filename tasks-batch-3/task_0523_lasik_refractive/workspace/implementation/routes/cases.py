from datetime import timedelta

from flask import Blueprint, request, g

from db import db, parse_dt, HEAL_SETTLE_DAYS
from middleware import require_auth
from response import success
from helpers import (
    stamp_create, touch, serialize, get_json_body, get_or_404,
    as_int, as_number, as_str, as_bool, paginate, sorted_by_created,
)
from errors import err
from services.calc import amortized_installment_cents

bp = Blueprint("cases", __name__)


# ---------------- Create / read cases ----------------
@bp.post("/refractive/cases")
@require_auth(["Coordinator"])
def create_case():
    body = get_json_body()
    patient_id = as_str(body, "patient_id")
    screening_id = as_str(body, "screening_id")
    package_id = as_str(body, "package_id")

    # existence left-to-right
    patient = get_or_404(db.patients, patient_id)
    screening = get_or_404(db.screenings, screening_id)
    get_or_404(db.packages, package_id)

    # referential business rule: screening APPROVED and belongs to patient
    if screening["status"] != "APPROVED" or screening["patient_id"] != patient_id:
        raise err("ERR_SCREENING_NOT_APPROVED",
                  "screening_id must reference an APPROVED screening for the patient")

    rec = {
        "patient_id": patient_id,
        "screening_id": screening_id,
        "package_id": package_id,
        "clinical_status": "PLANNED",
        "financial_status": "UNFUNDED",
        "surgery_completed_at": None,
        "final_uncorrected_va": None,
    }
    stamp_create(rec)
    db.cases[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/refractive/cases/<cid>")
@require_auth(["Coordinator", "Surgeon", "Optometrist", "Patient"])
def get_case(cid):
    return success(serialize(get_or_404(db.cases, cid)), 200)


@bp.get("/refractive/cases")
@require_auth(["Coordinator", "Surgeon", "Optometrist", "Patient"])
def list_cases():
    items = list(db.cases.values())
    for field in ("patient_id", "screening_id", "package_id",
                  "clinical_status", "financial_status"):
        v = request.args.get(field)
        if v is not None:
            items = [x for x in items if x[field] == v]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)


# ---------------- Financing (financial axis) ----------------
@bp.post("/refractive/cases/<cid>/financing")
@require_auth(["Coordinator"])
def create_financing(cid):
    case = get_or_404(db.cases, cid)
    body = get_json_body()
    down = as_int(body, "down_payment_cents")
    term = as_int(body, "term_months")
    apr = as_int(body, "apr_bps")

    if down < 0:
        raise err("ERR_INVALID_REQUEST", "down_payment_cents must be >= 0")
    if term < 1 or term > 60:
        raise err("ERR_INVALID_REQUEST", "term_months must be 1..60")
    if apr < 0:
        raise err("ERR_INVALID_REQUEST", "apr_bps must be >= 0")

    # state gate: financial axis must be UNFUNDED
    if case["financial_status"] != "UNFUNDED":
        raise err("ERR_INVALID_STATE", "financial_status must be UNFUNDED")

    package = db.packages[case["package_id"]]

    # fiscal: deposit floor
    if down < package["deposit_cents"]:
        raise err("ERR_DEPOSIT_TOO_LOW", "down_payment_cents below package deposit")

    base = package["base_price_cents"]

    if down == base:
        # paid outright
        plan = {
            "case_id": cid,
            "down_payment_cents": down,
            "term_months": 1,
            "apr_bps": apr,
            "monthly_installment_cents": 0,
            "amount_settled_cents": base,
            "status": "SETTLED",
        }
        stamp_create(plan)
        db.financing[plan["id"]] = plan
        case["financial_status"] = "PAID_IN_FULL"
        touch(case)
        return success(serialize(plan), 201)

    # down < base -> OPEN plan (down >= deposit already checked; deposit <= base by pkg constraint)
    installment = amortized_installment_cents(base, down, term, apr)
    plan = {
        "case_id": cid,
        "down_payment_cents": down,
        "term_months": term,
        "apr_bps": apr,
        "monthly_installment_cents": installment,
        "amount_settled_cents": down,
        "status": "OPEN",
    }
    stamp_create(plan)
    db.financing[plan["id"]] = plan
    case["financial_status"] = "DEPOSIT_PAID"
    touch(case)
    return success(serialize(plan), 201)


@bp.get("/refractive/cases/<cid>/financing")
@require_auth(["Coordinator", "Patient"])
def list_case_financing(cid):
    get_or_404(db.cases, cid)
    items = [f for f in db.financing.values() if f["case_id"] == cid]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)


# ---------------- Bookings (clinical axis PLANNED->SCHEDULED, OCC guarded) ----------------
def _day(dt):
    return dt.date()


def _overlap(a_start, a_end, b_start, b_end):
    # half-open intervals [start, end) overlap iff a_start < b_end and b_start < a_end
    return a_start < b_end and b_start < a_end


@bp.post("/refractive/cases/<cid>/bookings")
@require_auth(["Coordinator"])
def create_booking(cid):
    case = get_or_404(db.cases, cid)
    body = get_json_body()
    suite_id = as_str(body, "suite_id")
    surgeon_id = as_str(body, "surgeon_id")
    slot_start_raw = as_str(body, "slot_start")
    slot_end_raw = as_str(body, "slot_end")
    expected_version = as_int(body, "expected_case_version")

    # existence of referenced resources (left-to-right)
    suite = get_or_404(db.suites, suite_id)
    surgeon = get_or_404(db.surgeons, surgeon_id)

    try:
        slot_start = parse_dt(slot_start_raw)
        slot_end = parse_dt(slot_end_raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "slot_start/slot_end must be ISO 8601 datetimes")

    # state gate: PLANNED
    if case["clinical_status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "case must be PLANNED to schedule")

    # OCC (part of state layer)
    if expected_version != case["version"]:
        raise err("ERR_STALE_CASE_VERSION", "expected_case_version does not match")

    # referential: must be funded
    if case["financial_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        raise err("ERR_CASE_NOT_FUNDED", "case must be funded before booking")

    # no ACTIVE booking already for this case (invalid state)
    if any(b["case_id"] == cid and b["status"] == "ACTIVE" for b in db.bookings.values()):
        raise err("ERR_INVALID_STATE", "case already has an active booking")

    # temporal: slot well-formed
    if not (slot_end > slot_start):
        raise err("ERR_INVALID_SLOT", "slot_end must be strictly after slot_start")

    # temporal: suite conflict (interval + suite buffer after end)
    buffer = timedelta(minutes=suite["turnaround_buffer_minutes"])
    for b in db.bookings.values():
        if b["status"] != "ACTIVE" or b["suite_id"] != suite_id:
            continue
        # new interval extended by buffer after its end vs existing extended by its buffer
        if _overlap(slot_start, slot_end + buffer, b["slot_start"], b["slot_end"] + buffer):
            raise err("ERR_SUITE_TIME_CONFLICT", "suite time conflict")

    # temporal: surgeon conflict (bare overlap, no buffer)
    for b in db.bookings.values():
        if b["status"] != "ACTIVE" or b["surgeon_id"] != surgeon_id:
            continue
        if _overlap(slot_start, slot_end, b["slot_start"], b["slot_end"]):
            raise err("ERR_SURGEON_TIME_CONFLICT", "surgeon time conflict")

    # constraint: suite daily cap (ACTIVE bookings on suite for UTC day of slot_start)
    day = _day(slot_start)
    suite_day_count = sum(
        1 for b in db.bookings.values()
        if b["status"] == "ACTIVE" and b["suite_id"] == suite_id
        and _day(b["slot_start"]) == day
    )
    if suite_day_count + 1 > suite["daily_case_cap"]:
        raise err("ERR_SUITE_DAILY_CAP", "suite daily cap exceeded")

    # constraint: surgeon daily cap
    surgeon_day_count = sum(
        1 for b in db.bookings.values()
        if b["status"] == "ACTIVE" and b["surgeon_id"] == surgeon_id
        and _day(b["slot_start"]) == day
    )
    if surgeon_day_count + 1 > surgeon["max_daily_cases"]:
        raise err("ERR_SURGEON_DAILY_CAP", "surgeon daily cap exceeded")

    # constraint: availability
    if suite["status"] != "OPEN" or not surgeon["accepting"]:
        raise err("ERR_RESOURCE_UNAVAILABLE", "suite not OPEN or surgeon not accepting")

    booking = {
        "case_id": cid,
        "suite_id": suite_id,
        "surgeon_id": surgeon_id,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "expected_case_version": expected_version,
        "status": "ACTIVE",
    }
    stamp_create(booking)
    db.bookings[booking["id"]] = booking

    case["clinical_status"] = "SCHEDULED"
    touch(case)  # increments version by 1
    return success(serialize(booking), 201)


@bp.get("/refractive/cases/<cid>/bookings")
@require_auth(["Coordinator", "Surgeon", "Patient"])
def list_case_bookings(cid):
    get_or_404(db.cases, cid)
    items = [b for b in db.bookings.values() if b["case_id"] == cid]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)


# ---------------- Consent (clinical axis SCHEDULED->CONSENTED) ----------------
@bp.post("/refractive/cases/<cid>/consent")
@require_auth(["Patient"])
def sign_consent(cid):
    case = get_or_404(db.cases, cid)
    body = get_json_body()
    drops = as_bool(body, "drops_regimen_started")
    signer = as_str(body, "signed_by_patient_id")

    if case["clinical_status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "case must be SCHEDULED to sign consent")

    if drops is not True:
        raise err("ERR_DROPS_NOT_STARTED", "drops_regimen_started must be true")
    if signer != case["patient_id"]:
        raise err("ERR_CONSENT_PATIENT_MISMATCH", "signer must be the case patient")

    consent = {
        "case_id": cid,
        "drops_regimen_started": drops,
        "signed_by_patient_id": signer,
        "signed_at": db.now(),
        "status": "SIGNED",
    }
    stamp_create(consent)
    db.consents[consent["id"]] = consent

    case["clinical_status"] = "CONSENTED"
    touch(case)
    return success(serialize(consent), 201)


@bp.get("/refractive/cases/<cid>/consent")
@require_auth(["Coordinator", "Surgeon", "Patient"])
def list_case_consent(cid):
    get_or_404(db.cases, cid)
    items = [c for c in db.consents.values() if c["case_id"] == cid]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)


# ---------------- Operate (CONSENTED->OPERATED) ----------------
@bp.post("/refractive/cases/<cid>/operate")
@require_auth(["Surgeon"])
def operate_case(cid):
    case = get_or_404(db.cases, cid)
    if case["clinical_status"] != "CONSENTED":
        raise err("ERR_INVALID_STATE", "case must be CONSENTED to operate")

    now = db.now()
    has_active_ready = any(
        b["case_id"] == cid and b["status"] == "ACTIVE" and b["slot_start"] <= now
        for b in db.bookings.values()
    )
    if not has_active_ready:
        raise err("ERR_INVALID_STATE", "no active booking with slot_start <= now")

    has_signed = any(
        c["case_id"] == cid and c["status"] == "SIGNED" for c in db.consents.values()
    )
    if not has_signed:
        raise err("ERR_INVALID_STATE", "no signed consent form")

    case["clinical_status"] = "OPERATED"
    case["surgery_completed_at"] = now
    touch(case)

    patient = db.patients.get(case["patient_id"])
    if patient is not None:
        patient["status"] = "OPERATED"
        touch(patient)
    return success(serialize(case), 200)


# ---------------- Heal (OPERATED->HEALED) ----------------
@bp.post("/refractive/cases/<cid>/heal")
@require_auth(["Surgeon"])
def heal_case(cid):
    case = get_or_404(db.cases, cid)
    body = get_json_body()
    final_va = as_number(body, "final_uncorrected_va")

    if case["clinical_status"] != "OPERATED":
        raise err("ERR_INVALID_STATE", "case must be OPERATED to heal")

    deadline = case["surgery_completed_at"] + timedelta(days=HEAL_SETTLE_DAYS)
    if db.now() < deadline:
        raise err("ERR_HEAL_TOO_EARLY", "heal attempted before settling period")

    case["final_uncorrected_va"] = final_va
    case["clinical_status"] = "HEALED"
    touch(case)
    return success(serialize(case), 200)


# ---------------- Cancel (cascade, OCC guarded) ----------------
@bp.post("/refractive/cases/<cid>/cancel")
@require_auth(["Coordinator"])
def cancel_case(cid):
    case = get_or_404(db.cases, cid)
    body = get_json_body()
    expected_version = as_int(body, "expected_case_version")

    if case["clinical_status"] not in ("PLANNED", "SCHEDULED", "CONSENTED"):
        raise err("ERR_INVALID_STATE", "case not cancellable from current state")

    if expected_version != case["version"]:
        raise err("ERR_STALE_CASE_VERSION", "expected_case_version does not match")

    case["clinical_status"] = "CANCELLED"

    # cascade: release active bookings
    for b in db.bookings.values():
        if b["case_id"] == cid and b["status"] == "ACTIVE":
            b["status"] = "RELEASED"
            touch(b)

    # cascade: revoke signed consents
    for c in db.consents.values():
        if c["case_id"] == cid and c["status"] == "SIGNED":
            c["status"] = "REVOKED"
            touch(c)

    # cascade: cancel open financing; flip financial axis only if PAID_IN_FULL
    for f in db.financing.values():
        if f["case_id"] == cid and f["status"] == "OPEN":
            f["status"] = "CANCELLED"
            touch(f)
    if case["financial_status"] == "PAID_IN_FULL":
        case["financial_status"] = "REFUNDED"

    touch(case)  # increments version by 1
    return success(serialize(case), 200)
