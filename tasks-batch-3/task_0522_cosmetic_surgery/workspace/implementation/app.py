"""Cosmetic Surgery API — entry point + all routes.

In-memory only. No seeding at startup. Every rule traces to PRD prose.
"""
import os

from flask import Flask

from db import DB, stamp_create, touch
from errors import ApiError, err
from middleware import require, get_identity
from response import success, error_response
import serialize as S
import services as SVC

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    resp = error_response(e.error_id, e.message)
    resp.status_code = e.http_status
    return resp


@app.errorhandler(404)
def handle_404(e):
    resp = error_response("ERR_VALIDATION", "Not found")
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(e):
    resp = error_response("ERR_VALIDATION", "Method not allowed")
    resp.status_code = 405
    return resp


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    resp = error_response("ERR_VALIDATION", str(e))
    resp.status_code = 400
    return resp


# ---------------------------------------------------------------------------
# Lookup helpers (existence checks — priority 3)
# ---------------------------------------------------------------------------
def get_or_404(coll, id_, error_id):
    e = coll.get(id_)
    if e is None:
        raise err(error_id, f"{error_id}")
    return e


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
@require("PracticeAdmin")
def set_clock(user_id, role):
    body = SVC.get_body()
    target = SVC.require_field(body, "to_iso8601", "str")
    dt = SVC.parse_iso(target)  # validates
    DB.clock = target
    return success({"current_utc": target}, status=200)


# ===========================================================================
# Procedure catalog
# ===========================================================================
@app.route("/procedures", methods=["POST"])
@require("PracticeAdmin")
def create_procedure(user_id, role):
    body = SVC.get_body()
    code = SVC.require_field(body, "code", "str")
    name = SVC.require_field(body, "name", "str")
    surgical = SVC.require_field(body, "surgical_fee_cents", "int")
    facility = SVC.require_field(body, "facility_fee_cents", "int")
    anesthesia = SVC.require_field(body, "anesthesia_fee_cents", "int")
    revision_window = SVC.optional_field(body, "revision_window_days", "int", 90)

    if surgical <= 0:
        raise err("ERR_VALIDATION", "surgical_fee_cents must be > 0")
    if facility < 0:
        raise err("ERR_VALIDATION", "facility_fee_cents must be >= 0")
    if anesthesia < 0:
        raise err("ERR_VALIDATION", "anesthesia_fee_cents must be >= 0")
    if revision_window < 0:
        raise err("ERR_VALIDATION", "revision_window_days must be >= 0")

    e = {
        "code": code, "name": name,
        "surgical_fee_cents": surgical,
        "facility_fee_cents": facility,
        "anesthesia_fee_cents": anesthesia,
        "revision_window_days": revision_window,
        "active": True, "status": "ACTIVE",
    }
    stamp_create(e)
    DB.procedures[e["id"]] = e
    return success(S.procedure(e), status=201)


@app.route("/procedures", methods=["GET"])
@require("PracticeAdmin", "FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_procedures(user_id, role):
    page, meta = SVC.paginate(list(DB.procedures.values()))
    return success([S.procedure(e) for e in page], response_type="array", pagination=meta)


@app.route("/procedures/<pid>", methods=["GET"])
@require("PracticeAdmin", "FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def get_procedure(pid, user_id, role):
    e = get_or_404(DB.procedures, pid, "ERR_PROCEDURE_NOT_FOUND")
    return success(S.procedure(e))


@app.route("/procedures/<pid>/retire", methods=["POST"])
@require("PracticeAdmin")
def retire_procedure(pid, user_id, role):
    e = get_or_404(DB.procedures, pid, "ERR_PROCEDURE_NOT_FOUND")
    e["active"] = False
    e["status"] = "RETIRED"
    touch(e)
    return success(S.procedure(e))


@app.route("/procedures/<pid>/line-items", methods=["GET"])
@require("PracticeAdmin", "FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_procedure_line_items(pid, user_id, role):
    get_or_404(DB.procedures, pid, "ERR_PROCEDURE_NOT_FOUND")
    items = [li for li in DB.line_items.values() if li["procedure_id"] == pid]
    page, meta = SVC.paginate(items)
    return success([S.line_item(e) for e in page], response_type="array", pagination=meta)


# ===========================================================================
# Patient
# ===========================================================================
@app.route("/patients", methods=["POST"])
@require("FrontDeskCoordinator", "Surgeon")
def create_patient(user_id, role):
    body = SVC.get_body()
    full_name = SVC.require_field(body, "full_name", "str")
    dob = SVC.require_field(body, "date_of_birth", "str")
    age = SVC.require_field(body, "age_years", "int")
    bmi = SVC.require_field(body, "bmi", "number")
    asa = SVC.optional_field(body, "asa_class", "int", 1)
    smoker = SVC.optional_field(body, "smoker", "bool", False)
    prior = SVC.optional_field(body, "prior_complication_count", "int", 0)

    if age < 18:
        raise err("ERR_VALIDATION", "age_years must be >= 18")
    if not (bmi > 0):
        raise err("ERR_VALIDATION", "bmi must be > 0")
    if asa < 1 or asa > 4:
        raise err("ERR_VALIDATION", "asa_class must be 1..4")
    if prior < 0:
        raise err("ERR_VALIDATION", "prior_complication_count must be >= 0")

    e = {
        "full_name": full_name, "date_of_birth": dob,
        "age_years": age, "asa_class": asa, "bmi": bmi,
        "smoker": smoker, "prior_complication_count": prior,
    }
    SVC.compute_risk(e)
    stamp_create(e)
    DB.patients[e["id"]] = e
    return success(S.patient(e), status=201)


@app.route("/patients/<pid>", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def get_patient(pid, user_id, role):
    e = get_or_404(DB.patients, pid, "ERR_PATIENT_NOT_FOUND")
    return success(S.patient(e))


@app.route("/patients/<pid>", methods=["PATCH"])
@require("Surgeon")
def update_patient(pid, user_id, role):
    e = get_or_404(DB.patients, pid, "ERR_PATIENT_NOT_FOUND")
    body = SVC.get_body()
    asa = SVC.optional_field(body, "asa_class", "int", None)
    bmi = SVC.optional_field(body, "bmi", "number", None)
    smoker = SVC.optional_field(body, "smoker", "bool", None)
    age = SVC.optional_field(body, "age_years", "int", None)
    prior = SVC.optional_field(body, "prior_complication_count", "int", None)

    if asa is not None:
        if asa < 1 or asa > 4:
            raise err("ERR_VALIDATION", "asa_class must be 1..4")
        e["asa_class"] = asa
    if bmi is not None:
        if not (bmi > 0):
            raise err("ERR_VALIDATION", "bmi must be > 0")
        e["bmi"] = bmi
    if smoker is not None:
        e["smoker"] = smoker
    if age is not None:
        if age < 18:
            raise err("ERR_VALIDATION", "age_years must be >= 18")
        e["age_years"] = age
    if prior is not None:
        if prior < 0:
            raise err("ERR_VALIDATION", "prior_complication_count must be >= 0")
        e["prior_complication_count"] = prior

    SVC.compute_risk(e)
    touch(e)
    return success(S.patient(e))


@app.route("/patients/<pid>/clearances", methods=["POST"])
@require("Surgeon")
def issue_clearance(pid, user_id, role):
    patient = get_or_404(DB.patients, pid, "ERR_PATIENT_NOT_FOUND")
    body = SVC.get_body()
    tier_provided = SVC.require_field(body, "tier_provided", "str")
    if tier_provided not in ("STANDARD", "MEDICAL"):
        raise err("ERR_VALIDATION", "tier_provided must be STANDARD or MEDICAL")
    tier_required = patient["clearance_tier"]
    cleared = SVC.tier_satisfies(tier_provided, tier_required)
    e = {
        "patient_id": pid,
        "tier_required": tier_required,
        "tier_provided": tier_provided,
        "cleared": cleared,
        "status": "ISSUED",
    }
    stamp_create(e)
    DB.clearances[e["id"]] = e
    return success(S.clearance(e), status=201)


@app.route("/patients/<pid>/clearances", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_clearances(pid, user_id, role):
    get_or_404(DB.patients, pid, "ERR_PATIENT_NOT_FOUND")
    items = [c for c in DB.clearances.values() if c["patient_id"] == pid]
    page, meta = SVC.paginate(items)
    return success([S.clearance(e) for e in page], response_type="array", pagination=meta)


@app.route("/patients/<pid>/consultations", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_patient_consultations(pid, user_id, role):
    get_or_404(DB.patients, pid, "ERR_PATIENT_NOT_FOUND")
    items = [c for c in DB.consultations.values() if c["patient_id"] == pid]
    page, meta = SVC.paginate(items)
    return success([S.consultation(e) for e in page], response_type="array", pagination=meta)


@app.route("/patients/<pid>/quote-packages", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_patient_quotes(pid, user_id, role):
    get_or_404(DB.patients, pid, "ERR_PATIENT_NOT_FOUND")
    items = [q for q in DB.quote_packages.values() if q["patient_id"] == pid]
    page, meta = SVC.paginate(items)
    return success([S.quote_package(e) for e in page], response_type="array", pagination=meta)


@app.route("/patients/<pid>/surgery-bookings", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_patient_bookings(pid, user_id, role):
    get_or_404(DB.patients, pid, "ERR_PATIENT_NOT_FOUND")
    items = [b for b in DB.bookings.values() if b["patient_id"] == pid]
    page, meta = SVC.paginate(items)
    return success([S.booking(e) for e in page], response_type="array", pagination=meta)


# ===========================================================================
# Consultation
# ===========================================================================
@app.route("/consultations", methods=["POST"])
@require("FrontDeskCoordinator")
def create_consultation(user_id, role):
    body = SVC.get_body()
    patient_id = SVC.require_field(body, "patient_id", "str")
    surgeon_user_id = SVC.require_field(body, "surgeon_user_id", "str")
    chief = SVC.require_field(body, "chief_complaint", "str")
    get_or_404(DB.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    e = {
        "patient_id": patient_id,
        "surgeon_user_id": surgeon_user_id,
        "chief_complaint": chief,
        "status": "SCHEDULED",
    }
    stamp_create(e)
    DB.consultations[e["id"]] = e
    return success(S.consultation(e), status=201)


@app.route("/consultations/<cid>", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def get_consultation(cid, user_id, role):
    e = get_or_404(DB.consultations, cid, "ERR_CONSULTATION_NOT_FOUND")
    return success(S.consultation(e))


@app.route("/consultations/<cid>/complete", methods=["POST"])
@require("Surgeon")
def complete_consultation(cid, user_id, role):
    e = get_or_404(DB.consultations, cid, "ERR_CONSULTATION_NOT_FOUND")
    if e["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Consultation is not SCHEDULED")
    if user_id != e["surgeon_user_id"]:
        raise err("ERR_NOT_OWNER", "Acting surgeon does not own this consultation")
    e["status"] = "COMPLETED"
    touch(e)
    return success(S.consultation(e))


@app.route("/consultations/<cid>/close", methods=["POST"])
@require("FrontDeskCoordinator")
def close_consultation(cid, user_id, role):
    e = get_or_404(DB.consultations, cid, "ERR_CONSULTATION_NOT_FOUND")
    if e["status"] not in ("SCHEDULED", "COMPLETED", "CONVERTED"):
        raise err("ERR_INVALID_STATE", "Consultation cannot be closed from this state")
    # Blocked if any QuotePackage on this consultation is still PRESENTED.
    for q in DB.quote_packages.values():
        if q["consultation_id"] == cid and q["status"] == "PRESENTED":
            raise err("ERR_OPEN_QUOTE_EXISTS", "A presented quote remains open")
    e["status"] = "CLOSED"
    touch(e)
    return success(S.consultation(e))


@app.route("/consultations/<cid>/quote-packages", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_consultation_quotes(cid, user_id, role):
    get_or_404(DB.consultations, cid, "ERR_CONSULTATION_NOT_FOUND")
    items = [q for q in DB.quote_packages.values() if q["consultation_id"] == cid]
    page, meta = SVC.paginate(items)
    return success([S.quote_package(e) for e in page], response_type="array", pagination=meta)


# ===========================================================================
# QuotePackage & line items
# ===========================================================================
@app.route("/quote-packages", methods=["POST"])
@require("FrontDeskCoordinator")
def create_quote(user_id, role):
    body = SVC.get_body()
    consultation_id = SVC.require_field(body, "consultation_id", "str")
    consult = get_or_404(DB.consultations, consultation_id, "ERR_CONSULTATION_NOT_FOUND")
    e = {
        "consultation_id": consultation_id,
        "patient_id": consult["patient_id"],
        "subtotal_cents": 0,
        "discount_pct": 0.00,
        "total_cents": 0,
        "required_deposit_cents": 0,
        "deposit_paid_cents": 0,
        "financed_cents": 0,
        "balance_due_cents": 0,
        "status": "DRAFT",
    }
    stamp_create(e)
    DB.quote_packages[e["id"]] = e
    return success(S.quote_package(e), status=201)


@app.route("/quote-packages/<qid>", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def get_quote(qid, user_id, role):
    e = get_or_404(DB.quote_packages, qid, "ERR_QUOTE_NOT_FOUND")
    return success(S.quote_package(e))


@app.route("/quote-packages/<qid>/line-items", methods=["POST"])
@require("FrontDeskCoordinator")
def add_line_item(qid, user_id, role):
    quote = get_or_404(DB.quote_packages, qid, "ERR_QUOTE_NOT_FOUND")
    body = SVC.get_body()
    procedure_id = SVC.require_field(body, "procedure_id", "str")
    procedure = get_or_404(DB.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    # State: only DRAFT quotes accept line items.
    if quote["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Quote is not DRAFT")
    if procedure["status"] != "ACTIVE":
        raise err("ERR_PROCEDURE_RETIRED", "Procedure is retired")

    surg = procedure["surgical_fee_cents"]
    fac = procedure["facility_fee_cents"]
    anes = procedure["anesthesia_fee_cents"]
    li = {
        "quote_package_id": qid,
        "procedure_id": procedure_id,
        "surgical_fee_cents": surg,
        "facility_fee_cents": fac,
        "anesthesia_fee_cents": anes,
        "bundle_total_cents": surg + fac + anes,
    }
    stamp_create(li, common=False)
    DB.line_items[li["id"]] = li

    SVC.recompute_quote_pricing(quote, DB.line_items.values())
    SVC.recompute_balance(quote)
    touch(quote)
    return success(S.line_item(li), status=201)


@app.route("/quote-packages/<qid>/line-items", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_line_items(qid, user_id, role):
    get_or_404(DB.quote_packages, qid, "ERR_QUOTE_NOT_FOUND")
    items = [li for li in DB.line_items.values() if li["quote_package_id"] == qid]
    page, meta = SVC.paginate(items)
    return success([S.line_item(e) for e in page], response_type="array", pagination=meta)


@app.route("/quote-packages/<qid>/deposits", methods=["POST"])
@require("BillingSpecialist")
def record_deposit(qid, user_id, role):
    quote = get_or_404(DB.quote_packages, qid, "ERR_QUOTE_NOT_FOUND")
    body = SVC.get_body()
    amount = SVC.require_field(body, "amount_cents", "int")
    if amount <= 0:
        raise err("ERR_VALIDATION", "amount_cents must be > 0")
    quote["deposit_paid_cents"] += amount
    SVC.recompute_balance(quote)
    touch(quote)
    return success(S.quote_package(quote), status=201)


@app.route("/quote-packages/<qid>/present", methods=["POST"])
@require("FrontDeskCoordinator")
def present_quote(qid, user_id, role):
    quote = get_or_404(DB.quote_packages, qid, "ERR_QUOTE_NOT_FOUND")
    if quote["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Quote is not DRAFT")
    lines = [li for li in DB.line_items.values() if li["quote_package_id"] == qid]
    if not lines:
        raise err("ERR_EMPTY_QUOTE", "Quote has no line items")
    # Pricing already reconciled on each add; presenting simply freezes it.
    quote["status"] = "PRESENTED"
    touch(quote)
    return success(S.quote_package(quote))


@app.route("/quote-packages/<qid>/accept", methods=["POST"])
@require("FrontDeskCoordinator")
def accept_quote(qid, user_id, role):
    quote = get_or_404(DB.quote_packages, qid, "ERR_QUOTE_NOT_FOUND")
    if quote["status"] != "PRESENTED":
        raise err("ERR_INVALID_STATE", "Quote is not PRESENTED")
    # Consent (priority 9) then deposit (priority 13).
    has_consent = any(
        c["quote_package_id"] == qid
        and c["status"] == "SIGNED"
        and c["surgical_consent_signed"] is True
        for c in DB.consents.values()
    )
    if not has_consent:
        raise err("ERR_CONSENT_MISSING", "No signed surgical consent")
    if quote["deposit_paid_cents"] < quote["required_deposit_cents"]:
        raise err("ERR_DEPOSIT_UNPAID", "Deposit does not cover required amount")

    quote["status"] = "ACCEPTED"
    # Cascade: parent Consultation COMPLETED -> CONVERTED.
    consult = DB.consultations.get(quote["consultation_id"])
    if consult is not None and consult["status"] == "COMPLETED":
        consult["status"] = "CONVERTED"
        touch(consult)
    SVC.recompute_balance(quote)
    touch(quote)
    return success(S.quote_package(quote))


def _void_submitted_financings(qid):
    """Cascade for reject/expire: any SUBMITTED financing -> VOIDED."""
    for f in DB.financings.values():
        if f["quote_package_id"] == qid and f["status"] == "SUBMITTED":
            f["status"] = "VOIDED"
            touch(f)


@app.route("/quote-packages/<qid>/reject", methods=["POST"])
@require("FrontDeskCoordinator")
def reject_quote(qid, user_id, role):
    quote = get_or_404(DB.quote_packages, qid, "ERR_QUOTE_NOT_FOUND")
    if quote["status"] != "PRESENTED":
        raise err("ERR_INVALID_STATE", "Quote is not PRESENTED")
    quote["status"] = "REJECTED"
    _void_submitted_financings(qid)
    touch(quote)
    return success(S.quote_package(quote))


@app.route("/quote-packages/<qid>/expire", methods=["POST"])
@require("FrontDeskCoordinator")
def expire_quote(qid, user_id, role):
    quote = get_or_404(DB.quote_packages, qid, "ERR_QUOTE_NOT_FOUND")
    if quote["status"] not in ("DRAFT", "PRESENTED"):
        raise err("ERR_INVALID_STATE", "Quote is not DRAFT or PRESENTED")
    quote["status"] = "EXPIRED"
    _void_submitted_financings(qid)
    touch(quote)
    return success(S.quote_package(quote))


# ===========================================================================
# Consent
# ===========================================================================
@app.route("/quote-packages/<qid>/consents", methods=["POST"])
@require("FrontDeskCoordinator", "Surgeon")
def create_consent(qid, user_id, role):
    get_or_404(DB.quote_packages, qid, "ERR_QUOTE_NOT_FOUND")
    body = SVC.get_body()
    before_photo = SVC.require_field(body, "before_photo_ref", "str")
    photo_signed = SVC.require_field(body, "photo_consent_signed", "bool")
    surgical_signed = SVC.require_field(body, "surgical_consent_signed", "bool")
    e = {
        "quote_package_id": qid,
        "before_photo_ref": before_photo,
        "photo_consent_signed": photo_signed,
        "surgical_consent_signed": surgical_signed,
        "status": "SIGNED" if surgical_signed else "PENDING",
    }
    stamp_create(e)
    DB.consents[e["id"]] = e
    return success(S.consent(e), status=201)


@app.route("/quote-packages/<qid>/consents", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_consents(qid, user_id, role):
    get_or_404(DB.quote_packages, qid, "ERR_QUOTE_NOT_FOUND")
    items = [c for c in DB.consents.values() if c["quote_package_id"] == qid]
    page, meta = SVC.paginate(items)
    return success([S.consent(e) for e in page], response_type="array", pagination=meta)


@app.route("/consents/<cid>/revoke", methods=["POST"])
@require("Surgeon")
def revoke_consent(cid, user_id, role):
    e = get_or_404(DB.consents, cid, "ERR_CONSENT_NOT_FOUND")
    e["status"] = "REVOKED"
    touch(e)
    return success(S.consent(e))


# ===========================================================================
# SurgeryBooking
# ===========================================================================
def _intervals_overlap_open(a_start, a_end, b_start, b_end):
    # Half-open: conflict iff a.start < b.end AND b.start < a.end.
    return a_start < b_end and b_start < a_end


def _intervals_overlap_buffered(a_start, a_end, b_start, b_end, buffer_s):
    # Buffered-closed: conflict iff a.start < b.end+buf AND b.start < a.end+buf.
    return a_start < (b_end + buffer_s) and b_start < (a_end + buffer_s)


@app.route("/surgery-bookings", methods=["POST"])
@require("FrontDeskCoordinator")
def create_booking(user_id, role):
    body = SVC.get_body()
    quote_id = SVC.require_field(body, "quote_package_id", "str")
    surgeon_user_id = SVC.require_field(body, "surgeon_user_id", "str")
    or_room = SVC.require_field(body, "or_room", "str")
    scheduled_start = SVC.require_field(body, "scheduled_start", "str")
    scheduled_end = SVC.require_field(body, "scheduled_end", "str")
    expected_version = SVC.require_field(body, "expected_quote_package_version", "int")

    # Existence (priority 3).
    quote = get_or_404(DB.quote_packages, quote_id, "ERR_QUOTE_NOT_FOUND")
    # State (priority 4): quote must be ACCEPTED.
    if quote["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Quote is not ACCEPTED")

    start_dt = SVC.parse_iso(scheduled_start)
    end_dt = SVC.parse_iso(scheduled_end)
    clock = SVC.clock_dt(DB)
    start_s = SVC.epoch_seconds(start_dt)
    end_s = SVC.epoch_seconds(end_dt)
    clock_s = SVC.epoch_seconds(clock)

    # Priority 8: clearance present (ISSUED, cleared == true) for the patient.
    patient_id = quote["patient_id"]
    has_clearance = any(
        c["patient_id"] == patient_id and c["status"] == "ISSUED" and c["cleared"] is True
        for c in DB.clearances.values()
    )
    if not has_clearance:
        raise err("ERR_CLEARANCE_MISSING", "Patient has no valid clearance")

    # Priority 10: OR overlap (half-open) with existing SCHEDULED bookings.
    for b in DB.bookings.values():
        if b["status"] != "SCHEDULED" or b["or_room"] != or_room:
            continue
        b_start = SVC.epoch_seconds(SVC.parse_iso(b["scheduled_start"]))
        b_end = SVC.epoch_seconds(SVC.parse_iso(b["scheduled_end"]))
        if _intervals_overlap_open(start_s, end_s, b_start, b_end):
            raise err("ERR_OR_DOUBLE_BOOKED", "OR interval overlaps existing booking")

    # Priority 11: surgeon 60-minute turnaround buffer.
    BUFFER = 60 * 60
    for b in DB.bookings.values():
        if b["status"] != "SCHEDULED" or b["surgeon_user_id"] != surgeon_user_id:
            continue
        b_start = SVC.epoch_seconds(SVC.parse_iso(b["scheduled_start"]))
        b_end = SVC.epoch_seconds(SVC.parse_iso(b["scheduled_end"]))
        if _intervals_overlap_buffered(start_s, end_s, b_start, b_end, BUFFER):
            raise err("ERR_SURGEON_BUFFER_CONFLICT", "Surgeon buffer conflict")

    # Priority 12: scheduled_start strictly in the future.
    if not (start_s > clock_s):
        raise err("ERR_SURGERY_IN_PAST", "scheduled_start must be in the future")

    # Priority 15: OCC on quote version.
    if expected_version != quote["version"]:
        raise err("ERR_STALE_VERSION", "expected_quote_package_version is stale")

    # Priority 16: time range end strictly after start.
    if not (end_s > start_s):
        raise err("ERR_INVALID_TIME_RANGE", "scheduled_end must be after scheduled_start")

    e = {
        "quote_package_id": quote_id,
        "patient_id": patient_id,
        "surgeon_user_id": surgeon_user_id,
        "or_room": or_room,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "deposit_forfeited_cents": 0,
        "deposit_refunded_cents": 0,
        "status": "SCHEDULED",
    }
    stamp_create(e)
    DB.bookings[e["id"]] = e
    # Booking creation increments the quote version.
    touch(quote)
    return success(S.booking(e), status=201)


@app.route("/surgery-bookings/<bid>", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def get_booking(bid, user_id, role):
    e = get_or_404(DB.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    return success(S.booking(e))


@app.route("/surgery-bookings", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_bookings(user_id, role):
    from flask import request as _rq
    items = list(DB.bookings.values())
    quote_id = _rq.args.get("quote_package_id")
    patient_id = _rq.args.get("patient_id")
    if quote_id is not None:
        items = [b for b in items if b["quote_package_id"] == quote_id]
    if patient_id is not None:
        items = [b for b in items if b["patient_id"] == patient_id]
    page, meta = SVC.paginate(items)
    return success([S.booking(e) for e in page], response_type="array", pagination=meta)


@app.route("/surgery-bookings/<bid>/complete", methods=["POST"])
@require("Surgeon")
def complete_booking(bid, user_id, role):
    booking = get_or_404(DB.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Booking is not SCHEDULED")
    # Owner surgeon only.
    if user_id != booking["surgeon_user_id"]:
        raise err("ERR_NOT_OWNER", "Acting surgeon does not own this booking")
    # Clock must have reached scheduled_start.
    clock_s = SVC.epoch_seconds(SVC.clock_dt(DB))
    start_s = SVC.epoch_seconds(SVC.parse_iso(booking["scheduled_start"]))
    if clock_s < start_s:
        raise err("ERR_SURGERY_NOT_STARTED", "Surgery has not started")
    booking["status"] = "COMPLETED"
    # Quote deposit and financing are consumed; balance recomputed.
    quote = DB.quote_packages.get(booking["quote_package_id"])
    if quote is not None:
        SVC.recompute_balance(quote)
        touch(quote)
    touch(booking)
    return success(S.booking(booking))


@app.route("/surgery-bookings/<bid>/cancel", methods=["POST"])
@require("BillingSpecialist")
def cancel_booking(bid, user_id, role):
    booking = get_or_404(DB.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Booking is not SCHEDULED")
    quote = DB.quote_packages.get(booking["quote_package_id"])

    # Settlement.
    start_dt = SVC.parse_iso(booking["scheduled_start"])
    clock = SVC.clock_dt(DB)
    deposit_paid = quote["deposit_paid_cents"] if quote else 0
    refunded, forfeited = SVC.cancellation_settlement(deposit_paid, start_dt, clock)
    booking["deposit_refunded_cents"] = refunded
    booking["deposit_forfeited_cents"] = forfeited
    booking["status"] = "CANCELLED"

    if quote is not None:
        # Hop 1: refunded portion leaves the quote ledger.
        quote["deposit_paid_cents"] -= refunded
        # Hop 2: void APPROVED/SUBMITTED financings; reverse approved amounts.
        for f in DB.financings.values():
            if f["quote_package_id"] == quote["id"] and f["status"] in ("APPROVED", "SUBMITTED"):
                was_approved = f["status"] == "APPROVED"
                f["status"] = "VOIDED"
                if was_approved:
                    quote["financed_cents"] -= f["approved_amount_cents"]
                touch(f)
        # Hop 3: recompute balance.
        SVC.recompute_balance(quote)
        touch(quote)

    touch(booking)
    return success(S.booking(booking))


# ===========================================================================
# FinancingApplication
# ===========================================================================
@app.route("/financing-applications", methods=["POST"])
@require("BillingSpecialist")
def create_financing(user_id, role):
    body = SVC.get_body()
    quote_id = SVC.require_field(body, "quote_package_id", "str")
    lender = SVC.require_field(body, "lender", "str")
    requested = SVC.require_field(body, "requested_amount_cents", "int")
    get_or_404(DB.quote_packages, quote_id, "ERR_QUOTE_NOT_FOUND")
    if lender not in ("CARECREDIT", "CHERRY"):
        raise err("ERR_VALIDATION", "lender must be CARECREDIT or CHERRY")
    if requested <= 0:
        raise err("ERR_VALIDATION", "requested_amount_cents must be > 0")
    e = {
        "quote_package_id": quote_id,
        "lender": lender,
        "requested_amount_cents": requested,
        "approved_amount_cents": 0,
        "merchant_fee_cents": 0,
        "practice_net_cents": 0,
        "status": "SUBMITTED",
    }
    stamp_create(e)
    DB.financings[e["id"]] = e
    return success(S.financing(e), status=201)


@app.route("/financing-applications/<fid>", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def get_financing(fid, user_id, role):
    e = get_or_404(DB.financings, fid, "ERR_FINANCING_NOT_FOUND")
    return success(S.financing(e))


@app.route("/financing-applications", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_financings(user_id, role):
    from flask import request as _rq
    items = list(DB.financings.values())
    quote_id = _rq.args.get("quote_package_id")
    if quote_id is not None:
        items = [f for f in items if f["quote_package_id"] == quote_id]
    page, meta = SVC.paginate(items)
    return success([S.financing(e) for e in page], response_type="array", pagination=meta)


@app.route("/financing-applications/<fid>/approve", methods=["POST"])
@require("BillingSpecialist")
def approve_financing(fid, user_id, role):
    f = get_or_404(DB.financings, fid, "ERR_FINANCING_NOT_FOUND")
    if f["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Financing is not SUBMITTED")
    quote = DB.quote_packages.get(f["quote_package_id"])
    if quote is None or quote["status"] != "ACCEPTED":
        raise err("ERR_QUOTE_NOT_ACCEPTED", "Parent quote is not ACCEPTED")
    approved = f["requested_amount_cents"]
    if approved > quote["balance_due_cents"]:
        raise err("ERR_FINANCING_EXCEEDS_BALANCE", "Approved amount exceeds balance")

    f["approved_amount_cents"] = approved
    fee, net = SVC.practice_net(approved, f["lender"])
    f["merchant_fee_cents"] = fee
    f["practice_net_cents"] = net
    f["status"] = "APPROVED"
    # Cascade onto quote.
    quote["financed_cents"] += approved
    SVC.recompute_balance(quote)
    touch(quote)
    touch(f)
    return success(S.financing(f))


@app.route("/financing-applications/<fid>/decline", methods=["POST"])
@require("BillingSpecialist")
def decline_financing(fid, user_id, role):
    f = get_or_404(DB.financings, fid, "ERR_FINANCING_NOT_FOUND")
    if f["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Financing is not SUBMITTED")
    f["status"] = "DECLINED"
    touch(f)
    return success(S.financing(f))


# ===========================================================================
# ComplicationCase
# ===========================================================================
@app.route("/complication-cases", methods=["POST"])
@require("Surgeon")
def create_case(user_id, role):
    body = SVC.get_body()
    booking_id = SVC.require_field(body, "surgery_booking_id", "str")
    line_item_id = SVC.require_field(body, "line_item_id", "str")
    attribution = SVC.require_field(body, "attribution", "str")
    get_or_404(DB.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    get_or_404(DB.line_items, line_item_id, "ERR_LINE_ITEM_NOT_FOUND")
    if attribution not in ("SURGICAL_ORIGIN", "PATIENT_FACTOR", "UNRELATED"):
        raise err("ERR_VALIDATION", "invalid attribution")
    e = {
        "surgery_booking_id": booking_id,
        "line_item_id": line_item_id,
        "reported_at": DB.clock,
        "attribution": attribution,
        "within_revision_window": None,
        "revision_charge_cents": None,
        "status": "OPEN",
    }
    stamp_create(e)
    DB.cases[e["id"]] = e
    return success(S.case(e), status=201)


@app.route("/complication-cases/<cid>", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def get_case(cid, user_id, role):
    e = get_or_404(DB.cases, cid, "ERR_CASE_NOT_FOUND")
    return success(S.case(e))


@app.route("/complication-cases", methods=["GET"])
@require("FrontDeskCoordinator", "Surgeon", "BillingSpecialist")
def list_cases(user_id, role):
    from flask import request as _rq
    items = list(DB.cases.values())
    booking_id = _rq.args.get("surgery_booking_id")
    line_item_id = _rq.args.get("line_item_id")
    if booking_id is not None:
        items = [c for c in items if c["surgery_booking_id"] == booking_id]
    if line_item_id is not None:
        items = [c for c in items if c["line_item_id"] == line_item_id]
    page, meta = SVC.paginate(items)
    return success([S.case(e) for e in page], response_type="array", pagination=meta)


@app.route("/complication-cases/<cid>/review", methods=["POST"])
@require("Surgeon")
def review_case(cid, user_id, role):
    e = get_or_404(DB.cases, cid, "ERR_CASE_NOT_FOUND")
    if e["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Case is not OPEN")
    booking = DB.bookings.get(e["surgery_booking_id"])
    if booking is None or booking["status"] != "COMPLETED":
        raise err("ERR_BOOKING_NOT_COMPLETED", "Parent booking is not COMPLETED")
    e["status"] = "UNDER_REVIEW"
    touch(e)
    return success(S.case(e))


@app.route("/complication-cases/<cid>/reopen", methods=["POST"])
@require("Surgeon")
def reopen_case(cid, user_id, role):
    e = get_or_404(DB.cases, cid, "ERR_CASE_NOT_FOUND")
    if e["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Case is not UNDER_REVIEW")
    # Clear provisional attribution decision (revision charge fields).
    e["within_revision_window"] = None
    e["revision_charge_cents"] = None
    e["status"] = "OPEN"
    touch(e)
    return success(S.case(e))


@app.route("/complication-cases/<cid>/approve-revision", methods=["POST"])
@require("Surgeon")
def approve_revision(cid, user_id, role):
    e = get_or_404(DB.cases, cid, "ERR_CASE_NOT_FOUND")
    if e["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Case is not UNDER_REVIEW")
    booking = DB.bookings.get(e["surgery_booking_id"])
    line_item = DB.line_items.get(e["line_item_id"])
    procedure = DB.procedures.get(line_item["procedure_id"]) if line_item else None
    within, charge = SVC.revision_charge(e, booking, procedure, line_item)
    e["within_revision_window"] = within
    e["revision_charge_cents"] = charge
    e["status"] = "REVISION_APPROVED"
    touch(e)
    return success(S.case(e))


@app.route("/complication-cases/<cid>/resolve", methods=["POST"])
@require("Surgeon")
def resolve_case(cid, user_id, role):
    e = get_or_404(DB.cases, cid, "ERR_CASE_NOT_FOUND")
    if e["status"] not in ("OPEN", "UNDER_REVIEW", "REVISION_APPROVED"):
        raise err("ERR_INVALID_STATE", "Case cannot be resolved from this state")
    e["status"] = "RESOLVED"
    touch(e)
    return success(S.case(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
