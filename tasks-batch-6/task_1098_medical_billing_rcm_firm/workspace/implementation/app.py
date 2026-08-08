"""Medical Billing RCM Firm API — Flask entry point and all routes.

Storage is in-memory only (store.py dicts). Nothing is seeded at startup:
every entity is created through the declared API surface.
"""
import os

from flask import Flask, request, g

import store
import logic
from serializers import serialize
from helpers import (
    ApiError, success, error_response, authenticate, require_roles,
    practice_user_can_read, get_body, require_string, require_int,
    require_number, require_enum, require_datetime, paginate,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Common mutation helpers
# ---------------------------------------------------------------------------
def touch(rec, bump_version=True):
    rec["updated_at"] = store.clock_now()
    if bump_version and "version" in rec:
        rec["version"] += 1


def base_common(rec):
    now = store.clock_now()
    rec["id"] = store.new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    return rec


def base_line(rec):
    rec["id"] = store.new_id()
    rec["created_at"] = store.clock_now()
    return rec


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------
def get_practice(pid):
    r = store.practices.get(pid)
    if r is None:
        raise ApiError("ERR_PRACTICE_NOT_FOUND", 404, "Practice not found")
    return r


def get_payer(pid):
    r = store.payers.get(pid)
    if r is None:
        raise ApiError("ERR_PAYER_NOT_FOUND", 404, "Payer not found")
    return r


def get_provider(pid):
    r = store.providers.get(pid)
    if r is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "Provider not found")
    return r


def get_enrollment(eid):
    r = store.payer_enrollments.get(eid)
    if r is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    return r


def get_fee_schedule(fid):
    r = store.fee_schedules.get(fid)
    if r is None:
        raise ApiError("ERR_FEE_SCHEDULE_NOT_FOUND", 404, "Fee schedule not found")
    return r


def get_claim(cid):
    r = store.claims.get(cid)
    if r is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "Claim not found")
    return r


def get_denial(did):
    r = store.denials.get(did)
    if r is None:
        raise ApiError("ERR_DENIAL_NOT_FOUND", 404, "Denial not found")
    return r


def get_appeal(aid):
    r = store.appeals.get(aid)
    if r is None:
        raise ApiError("ERR_APPEAL_NOT_FOUND", 404, "Appeal not found")
    return r


def get_remittance(rid):
    r = store.remittances.get(rid)
    if r is None:
        raise ApiError("ERR_REMITTANCE_NOT_FOUND", 404, "Remittance not found")
    return r


def get_posting(pid):
    r = store.payment_postings.get(pid)
    if r is None:
        raise ApiError("ERR_POSTING_NOT_FOUND", 404, "Payment posting not found")
    return r


def get_statement(sid):
    r = store.patient_statements.get(sid)
    if r is None:
        raise ApiError("ERR_STATEMENT_NOT_FOUND", 404, "Statement not found")
    return r


def invalid_state():
    raise ApiError("ERR_INVALID_STATE", 409, "Requested transition is not defined from the current state")


# ---------------------------------------------------------------------------
# Interval helpers
# ---------------------------------------------------------------------------
def fs_covers(fs, service_date):
    if fs["effective_date"] > service_date:
        return False
    if fs["end_date"] is not None and service_date > fs["end_date"]:
        return False
    return True


def fs_intervals_overlap(a, b):
    # closed-closed [eff, end] (end None => +inf)
    a_end = a["end_date"]
    b_end = b["end_date"]
    if a_end is not None and b["effective_date"] > a_end:
        return False
    if b_end is not None and a["effective_date"] > b_end:
        return False
    return True


def enrollment_covers(enr, service_date):
    # half-open [effective, termination)
    if enr["effective_date"] > service_date:
        return False
    if enr["termination_date"] is not None and service_date >= enr["termination_date"]:
        return False
    return True


def enrollment_periods_overlap(a_eff, a_term, b_eff, b_term):
    # half-open [eff, term); term None => +inf
    if a_term is not None and b_eff >= a_term:
        return False
    if b_term is not None and a_eff >= b_term:
        return False
    return True


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(err):
    return error_response(ApiError("ERR_VALIDATION", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(err):
    return error_response(ApiError("ERR_VALIDATION", 405, "Method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_VALIDATION", 500, "Internal error: %s" % err))


@app.after_request
def _no_keepalive(resp):
    # Avoid werkzeug keep-alive RemoteDisconnected flakiness under per-test reboot.
    resp.headers["Connection"] = "close"
    return resp


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock_route():
    authenticate()
    require_roles("AccountManager")
    body = get_body()
    dt = require_datetime(body, "to_iso8601")
    store.set_clock(dt)
    return success({"current_utc": store.render_dt(store.clock_now())}, 200)


# ===========================================================================
# Practices
# ===========================================================================
@app.route("/rcm/practices", methods=["POST"])
def create_practice():
    authenticate()
    require_roles("AccountManager")
    body = get_body()
    name = require_string(body, "name")
    npi = require_string(body, "npi")
    tax_id = require_string(body, "tax_id")
    fee_pct = require_number(body, "billing_fee_pct", lo=0, hi=1, lo_strict=True, hi_strict=True)
    rec = base_common({
        "name": name, "npi": npi, "tax_id": tax_id, "billing_fee_pct": fee_pct,
        "status": "PROSPECT", "ar_balance_cents": 0, "collected_ytd_cents": 0,
    })
    store.practices[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/rcm/practices/<pid>", methods=["GET"])
def get_practice_route(pid):
    authenticate()
    require_roles("AccountManager", "PracticeUser")
    rec = get_practice(pid)
    practice_user_can_read(pid)
    return success(serialize(rec), 200)


@app.route("/rcm/practices", methods=["GET"])
def list_practices():
    authenticate()
    require_roles("AccountManager")
    return paginate(list(store.practices.values()), serialize)


@app.route("/rcm/practices/<pid>/activate", methods=["POST"])
def activate_practice(pid):
    authenticate()
    require_roles("AccountManager")
    rec = get_practice(pid)
    body = get_body()
    target = require_enum(body, "target_status",
                          {"PROSPECT", "ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED"},
                          required=False)
    current = rec["status"]
    # Defined activate transitions and their inferred targets.
    inferred = {"ONBOARDING": "ACTIVE", "ACTIVE": "SUSPENDED", "SUSPENDED": "ACTIVE"}
    if current not in inferred:
        invalid_state()
    dest = target if target is not None else inferred[current]
    if dest != inferred[current]:
        invalid_state()
    if current == "ONBOARDING":
        has_active_fs = any(fs["practice_id"] == pid and fs["status"] == "ACTIVE"
                            for fs in store.fee_schedules.values())
        if not has_active_fs:
            invalid_state()
    rec["status"] = dest
    touch(rec, bump_version=True)
    return success(serialize(rec), 200)


@app.route("/rcm/practices/<pid>/kpi", methods=["GET"])
def practice_kpi_route(pid):
    authenticate()
    require_roles("AccountManager", "PracticeUser")
    rec = get_practice(pid)
    practice_user_can_read(pid)
    return success(logic.practice_kpi(rec), 200)


@app.route("/rcm/practices/<pid>/billing-fee", methods=["GET"])
def practice_billing_fee_route(pid):
    authenticate()
    require_roles("AccountManager", "PracticeUser")
    rec = get_practice(pid)
    practice_user_can_read(pid)
    return success(logic.practice_billing_fee(rec), 200)


@app.route("/rcm/practices/<pid>/providers", methods=["GET"])
def list_practice_providers(pid):
    authenticate()
    require_roles("AccountManager", "CredentialingSpecialist", "PracticeUser")
    get_practice(pid)
    practice_user_can_read(pid)
    items = [p for p in store.providers.values() if p["practice_id"] == pid]
    return paginate(items, serialize)


@app.route("/rcm/practices/<pid>/fee-schedules", methods=["GET"])
def list_practice_fee_schedules(pid):
    authenticate()
    require_roles("AccountManager", "PracticeUser")
    get_practice(pid)
    practice_user_can_read(pid)
    items = [f for f in store.fee_schedules.values() if f["practice_id"] == pid]
    return paginate(items, serialize)


@app.route("/rcm/practices/<pid>/claims", methods=["GET"])
def list_practice_claims(pid):
    authenticate()
    require_roles("AccountManager", "Coder", "Biller", "PracticeUser")
    get_practice(pid)
    practice_user_can_read(pid)
    items = [c for c in store.claims.values() if c["practice_id"] == pid]
    return paginate(items, serialize)


@app.route("/rcm/practices/<pid>/statements", methods=["GET"])
def list_practice_statements(pid):
    authenticate()
    require_roles("AccountManager", "PaymentPoster", "PracticeUser")
    get_practice(pid)
    practice_user_can_read(pid)
    items = [s for s in store.patient_statements.values() if s["practice_id"] == pid]
    return paginate(items, serialize)


# ===========================================================================
# Payers
# ===========================================================================
@app.route("/rcm/payers", methods=["POST"])
def create_payer():
    authenticate()
    require_roles("AccountManager")
    body = get_body()
    name = require_string(body, "name")
    payer_type = require_enum(body, "payer_type", {"COMMERCIAL", "MEDICARE", "MEDICAID"})
    timely = require_int(body, "timely_filing_days", min_value=1)
    appeal = require_int(body, "appeal_window_days", min_value=1)
    rec = base_common({
        "name": name, "payer_type": payer_type,
        "timely_filing_days": timely, "appeal_window_days": appeal,
    })
    store.payers[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/rcm/payers/<pid>", methods=["GET"])
def get_payer_route(pid):
    authenticate()
    require_roles("AccountManager", "Biller", "CredentialingSpecialist")
    return success(serialize(get_payer(pid)), 200)


@app.route("/rcm/payers/<pid>/enrollments", methods=["GET"])
def list_payer_enrollments(pid):
    authenticate()
    require_roles("AccountManager", "CredentialingSpecialist")
    get_payer(pid)
    items = [e for e in store.payer_enrollments.values() if e["payer_id"] == pid]
    return paginate(items, serialize)


@app.route("/rcm/payers/<pid>/remittances", methods=["GET"])
def list_payer_remittances(pid):
    authenticate()
    require_roles("AccountManager", "PaymentPoster")
    get_payer(pid)
    items = [r for r in store.remittances.values() if r["payer_id"] == pid]
    return paginate(items, serialize)


@app.route("/rcm/payers/<pid>/claims", methods=["GET"])
def list_payer_claims(pid):
    authenticate()
    require_roles("AccountManager", "Biller", "DenialSpecialist")
    get_payer(pid)
    items = [c for c in store.claims.values() if c["payer_id"] == pid]
    return paginate(items, serialize)


# ===========================================================================
# Providers / credentialing
# ===========================================================================
@app.route("/rcm/providers", methods=["POST"])
def create_provider():
    authenticate()
    require_roles("CredentialingSpecialist")
    body = get_body()
    practice_id = require_string(body, "practice_id")
    get_practice(practice_id)
    npi = require_string(body, "npi")
    first_name = require_string(body, "first_name")
    last_name = require_string(body, "last_name")
    specialty = require_string(body, "specialty")
    rec = base_common({
        "practice_id": practice_id, "npi": npi, "first_name": first_name,
        "last_name": last_name, "specialty": specialty,
        "credentialing_status": "PENDING", "credentialing_expiration_date": None,
    })
    store.providers[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/rcm/providers/<pid>", methods=["GET"])
def get_provider_route(pid):
    authenticate()
    require_roles("AccountManager", "CredentialingSpecialist", "Biller")
    return success(serialize(get_provider(pid)), 200)


@app.route("/rcm/providers/<pid>/enrollments", methods=["GET"])
def list_provider_enrollments(pid):
    authenticate()
    require_roles("AccountManager", "CredentialingSpecialist")
    get_provider(pid)
    items = [e for e in store.payer_enrollments.values() if e["provider_id"] == pid]
    return paginate(items, serialize)


@app.route("/rcm/providers/<pid>/claims", methods=["GET"])
def list_provider_claims(pid):
    authenticate()
    require_roles("AccountManager", "Biller", "Coder")
    get_provider(pid)
    items = [c for c in store.claims.values() if c["provider_id"] == pid]
    return paginate(items, serialize)


@app.route("/rcm/providers/<pid>/credentialing/submit", methods=["POST"])
def credentialing_submit(pid):
    authenticate()
    require_roles("CredentialingSpecialist")
    rec = get_provider(pid)
    if rec["credentialing_status"] not in ("PENDING", "EXPIRED"):
        invalid_state()
    rec["credentialing_status"] = "SUBMITTED"
    touch(rec, bump_version=True)
    return success(serialize(rec), 200)


@app.route("/rcm/providers/<pid>/credentialing/decision", methods=["POST"])
def credentialing_decision(pid):
    authenticate()
    require_roles("CredentialingSpecialist")
    rec = get_provider(pid)
    body = get_body()
    decision = require_enum(body, "decision", {"APPROVE", "REJECT"})
    if rec["credentialing_status"] != "SUBMITTED":
        invalid_state()
    if decision == "APPROVE":
        expiration = require_datetime(body, "expiration_date")
        if not (expiration > store.clock_now()):
            raise ApiError("ERR_VALIDATION", 422, "expiration_date must be strictly after the current clock")
        rec["credentialing_status"] = "APPROVED"
        rec["credentialing_expiration_date"] = expiration
    else:
        rec["credentialing_status"] = "REJECTED"
    touch(rec, bump_version=True)
    return success(serialize(rec), 200)


# ===========================================================================
# PayerEnrollment
# ===========================================================================
@app.route("/rcm/payer-enrollments", methods=["POST"])
def create_enrollment():
    authenticate()
    require_roles("CredentialingSpecialist")
    body = get_body()
    provider_id = require_string(body, "provider_id")
    get_provider(provider_id)
    payer_id = require_string(body, "payer_id")
    get_payer(payer_id)
    effective = require_datetime(body, "effective_date")
    termination = require_datetime(body, "termination_date", required=False)
    # Overlap against existing non-TERMINATED enrollments for same (provider,payer).
    for e in store.payer_enrollments.values():
        if e["provider_id"] == provider_id and e["payer_id"] == payer_id and e["status"] != "TERMINATED":
            if enrollment_periods_overlap(effective, termination,
                                          e["effective_date"], e["termination_date"]):
                raise ApiError("ERR_ENROLLMENT_PERIOD_OVERLAP", 409,
                               "Enrollment period overlaps an existing enrollment")
    rec = base_common({
        "provider_id": provider_id, "payer_id": payer_id,
        "effective_date": effective, "termination_date": termination,
        "status": "PENDING",
    })
    store.payer_enrollments[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/rcm/payer-enrollments/<eid>", methods=["GET"])
def get_enrollment_route(eid):
    authenticate()
    require_roles("AccountManager", "CredentialingSpecialist")
    return success(serialize(get_enrollment(eid)), 200)


@app.route("/rcm/payer-enrollments", methods=["GET"])
def list_enrollments():
    authenticate()
    require_roles("AccountManager", "CredentialingSpecialist")
    provider_id = request.args.get("provider_id")
    payer_id = request.args.get("payer_id")
    items = list(store.payer_enrollments.values())
    if provider_id is not None:
        items = [e for e in items if e["provider_id"] == provider_id]
    if payer_id is not None:
        items = [e for e in items if e["payer_id"] == payer_id]
    return paginate(items, serialize)


@app.route("/rcm/payer-enrollments/<eid>/activate", methods=["POST"])
def activate_enrollment(eid):
    authenticate()
    require_roles("CredentialingSpecialist")
    rec = get_enrollment(eid)
    if rec["status"] != "PENDING":
        invalid_state()
    provider = store.providers.get(rec["provider_id"])
    if provider is None or provider["credentialing_status"] != "APPROVED":
        invalid_state()
    rec["status"] = "ACTIVE"
    touch(rec, bump_version=True)
    return success(serialize(rec), 200)


@app.route("/rcm/payer-enrollments/<eid>/terminate", methods=["POST"])
def terminate_enrollment(eid):
    authenticate()
    require_roles("CredentialingSpecialist")
    rec = get_enrollment(eid)
    body = get_body()
    termination = require_datetime(body, "termination_date")
    if rec["status"] != "ACTIVE":
        invalid_state()
    rec["status"] = "TERMINATED"
    rec["termination_date"] = termination
    touch(rec, bump_version=True)
    return success(serialize(rec), 200)


# ===========================================================================
# FeeSchedule
# ===========================================================================
@app.route("/rcm/fee-schedules", methods=["POST"])
def create_fee_schedule():
    authenticate()
    require_roles("AccountManager")
    body = get_body()
    practice_id = require_string(body, "practice_id")
    get_practice(practice_id)
    effective = require_datetime(body, "effective_date")
    end_date = require_datetime(body, "end_date", required=False)
    rec = base_common({
        "practice_id": practice_id, "effective_date": effective,
        "end_date": end_date, "status": "DRAFT",
    })
    store.fee_schedules[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/rcm/fee-schedules/<fid>", methods=["GET"])
def get_fee_schedule_route(fid):
    authenticate()
    require_roles("AccountManager", "Coder", "PracticeUser")
    rec = get_fee_schedule(fid)
    practice_user_can_read(rec["practice_id"])
    return success(serialize(rec), 200)


@app.route("/rcm/fee-schedules/<fid>/lines", methods=["POST"])
def add_fee_schedule_line(fid):
    authenticate()
    require_roles("AccountManager")
    fs = get_fee_schedule(fid)
    body = get_body()
    cpt_code = require_string(body, "cpt_code")
    allowed = require_int(body, "allowed_amount_cents", money=True)
    rec = base_line({
        "fee_schedule_id": fid, "cpt_code": cpt_code, "allowed_amount_cents": allowed,
    })
    store.fee_schedule_lines[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/rcm/fee-schedules/<fid>/lines", methods=["GET"])
def list_fee_schedule_lines(fid):
    authenticate()
    require_roles("AccountManager", "Coder", "PracticeUser")
    fs = get_fee_schedule(fid)
    practice_user_can_read(fs["practice_id"])
    items = [l for l in store.fee_schedule_lines.values() if l["fee_schedule_id"] == fid]
    return paginate(items, serialize)


@app.route("/rcm/fee-schedules/<fid>/activate", methods=["POST"])
def activate_fee_schedule(fid):
    authenticate()
    require_roles("AccountManager")
    fs = get_fee_schedule(fid)
    body = get_body()
    expected_version = require_int(body, "expected_practice_version")
    if fs["status"] != "DRAFT":
        invalid_state()
    lines = [l for l in store.fee_schedule_lines.values() if l["fee_schedule_id"] == fid]
    if len(lines) < 1:
        raise ApiError("ERR_VALIDATION", 422, "Fee schedule must have at least one line to activate")
    practice = get_practice(fs["practice_id"])
    # Overlap (priority 9) before OCC (priority 11).
    for other in store.fee_schedules.values():
        if other["id"] == fid:
            continue
        if other["practice_id"] == fs["practice_id"] and other["status"] == "ACTIVE":
            if fs_intervals_overlap(fs, other):
                raise ApiError("ERR_FEE_SCHEDULE_OVERLAP", 409,
                               "Fee schedule interval overlaps an active schedule")
    if expected_version != practice["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale practice version")
    # Success.
    fs["status"] = "ACTIVE"
    touch(fs, bump_version=True)
    for other in store.fee_schedules.values():
        if other["id"] == fid:
            continue
        if (other["practice_id"] == fs["practice_id"] and other["status"] == "ACTIVE"
                and other["end_date"] is not None and other["end_date"] < fs["effective_date"]):
            other["status"] = "SUPERSEDED"
            touch(other, bump_version=True)
    practice["version"] += 1
    if practice["status"] == "PROSPECT":
        practice["status"] = "ONBOARDING"
    practice["updated_at"] = store.clock_now()
    return success(serialize(fs), 200)


# ===========================================================================
# Claims — charge entry, scrub, submission, closure
# ===========================================================================
@app.route("/rcm/claims", methods=["POST"])
def create_claim():
    authenticate()
    require_roles("Coder")
    body = get_body()
    practice_id = require_string(body, "practice_id")
    get_practice(practice_id)
    provider_id = require_string(body, "provider_id")
    get_provider(provider_id)
    payer_id = require_string(body, "payer_id")
    get_payer(payer_id)
    service_date = require_datetime(body, "service_date")
    deductible = require_int(body, "deductible_remaining_cents", money=True)
    coinsurance = require_number(body, "coinsurance_pct", lo=0, hi=1)
    copay = require_int(body, "copay_cents", money=True)
    rec = base_common({
        "practice_id": practice_id, "provider_id": provider_id, "payer_id": payer_id,
        "service_date": service_date, "deductible_remaining_cents": deductible,
        "coinsurance_pct": coinsurance, "copay_cents": copay, "status": "DRAFT",
        "billed_amount_cents": 0, "allowed_amount_cents": 0,
        "contractual_adjustment_cents": 0, "patient_responsibility_cents": 0,
        "expected_reimbursement_cents": 0, "insurance_paid_cents": 0,
        "write_off_cents": 0, "outstanding_balance_cents": 0,
        "scrubbed_by_user_id": None, "submitted_by_user_id": None,
        "submission_date": None, "appeal_round": 0,
        "_provisional_pr": 0, "_ever_accepted": False,
    })
    store.claims[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/rcm/claims/<cid>", methods=["GET"])
def get_claim_route(cid):
    authenticate()
    require_roles("AccountManager", "Coder", "Biller", "DenialSpecialist",
                  "PaymentPoster", "PracticeUser")
    rec = get_claim(cid)
    practice_user_can_read(rec["practice_id"])
    return success(serialize(rec), 200)


@app.route("/rcm/claims/<cid>/lines", methods=["POST"])
def add_claim_line(cid):
    authenticate()
    require_roles("Coder")
    claim = get_claim(cid)
    body = get_body()
    cpt_code = require_string(body, "cpt_code")
    units = require_int(body, "units", min_value=1)
    charge = require_int(body, "charge_amount_cents", money=True)
    rec = base_line({
        "claim_id": cid, "cpt_code": cpt_code, "units": units,
        "charge_amount_cents": charge, "allowed_amount_cents": 0,
    })
    store.claim_lines[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/rcm/claims/<cid>/lines", methods=["GET"])
def list_claim_lines(cid):
    authenticate()
    require_roles("AccountManager", "Coder", "Biller", "PracticeUser")
    claim = get_claim(cid)
    practice_user_can_read(claim["practice_id"])
    items = [l for l in store.claim_lines.values() if l["claim_id"] == cid]
    return paginate(items, serialize)


@app.route("/rcm/claims/<cid>/denials", methods=["GET"])
def list_claim_denials(cid):
    authenticate()
    require_roles("AccountManager", "DenialSpecialist", "Biller", "PracticeUser")
    claim = get_claim(cid)
    practice_user_can_read(claim["practice_id"])
    items = [d for d in store.denials.values() if d["claim_id"] == cid]
    return paginate(items, serialize)


@app.route("/rcm/claims/<cid>/postings", methods=["GET"])
def list_claim_postings(cid):
    authenticate()
    require_roles("AccountManager", "PaymentPoster", "Biller", "PracticeUser")
    claim = get_claim(cid)
    practice_user_can_read(claim["practice_id"])
    items = [p for p in store.payment_postings.values() if p["claim_id"] == cid]
    return paginate(items, serialize)


@app.route("/rcm/claims/<cid>/statements", methods=["GET"])
def list_claim_statements(cid):
    authenticate()
    require_roles("AccountManager", "PaymentPoster", "PracticeUser")
    claim = get_claim(cid)
    practice_user_can_read(claim["practice_id"])
    items = [s for s in store.patient_statements.values() if s["claim_id"] == cid]
    return paginate(items, serialize)


@app.route("/rcm/claims/<cid>/scrub", methods=["POST"])
def scrub_claim(cid):
    authenticate()
    require_roles("Coder")
    claim = get_claim(cid)
    if claim["status"] != "DRAFT":
        invalid_state()
    lines = logic.claim_lines_of(cid)
    if len(lines) < 1:
        raise ApiError("ERR_NO_CLAIM_LINES", 422, "Claim has no charge lines")
    # Covering ACTIVE fee schedule for the practice at service_date.
    covering = None
    for fs in store.fee_schedules.values():
        if (fs["practice_id"] == claim["practice_id"] and fs["status"] == "ACTIVE"
                and fs_covers(fs, claim["service_date"])):
            covering = fs
            break
    if covering is None:
        raise ApiError("ERR_NO_ACTIVE_FEE_SCHEDULE", 422,
                       "No active fee schedule covers the service date")
    price = {}
    for l in store.fee_schedule_lines.values():
        if l["fee_schedule_id"] == covering["id"]:
            price[l["cpt_code"]] = l["allowed_amount_cents"]
    for l in lines:
        if l["cpt_code"] not in price:
            raise ApiError("ERR_CPT_NOT_IN_FEE_SCHEDULE", 422,
                           "A claim line CPT is not priced by the covering fee schedule")
    # Resolve line allowed amounts.
    for l in lines:
        l["allowed_amount_cents"] = l["units"] * price[l["cpt_code"]]
    provisional = logic.provisional_patient_responsibility(claim)
    claim["_provisional_pr"] = provisional
    logic.recompute_claim_ledger(claim)
    claim["expected_reimbursement_cents"] = claim["allowed_amount_cents"] - claim["patient_responsibility_cents"]
    claim["scrubbed_by_user_id"] = g.user_id
    claim["status"] = "SCRUBBED"
    touch(claim, bump_version=True)
    logic.recompute_practice_totals(get_practice(claim["practice_id"]), touch)
    return success(serialize(claim), 200)


@app.route("/rcm/claims/<cid>/submit", methods=["POST"])
def submit_claim(cid):
    authenticate()
    require_roles("Biller")
    claim = get_claim(cid)
    if claim["status"] != "SCRUBBED":
        invalid_state()
    provider = store.providers.get(claim["provider_id"])
    payer = store.payers.get(claim["payer_id"])
    # 1) Credentialing (auto-expire if past expiration).
    if provider is not None and provider["credentialing_status"] == "APPROVED":
        exp = provider["credentialing_expiration_date"]
        if exp is not None and store.clock_now() >= exp:
            provider["credentialing_status"] = "EXPIRED"
            touch(provider, bump_version=True)
    if provider is None or provider["credentialing_status"] != "APPROVED":
        raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED", 422, "Rendering provider is not credentialed")
    # 2) Segregation of duties.
    if g.user_id == claim["scrubbed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Submitting user must differ from the scrubbing user")
    # 3) Active enrollment covering service_date.
    has_enrollment = any(
        e["provider_id"] == claim["provider_id"] and e["payer_id"] == claim["payer_id"]
        and e["status"] == "ACTIVE" and enrollment_covers(e, claim["service_date"])
        for e in store.payer_enrollments.values())
    if not has_enrollment:
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 422,
                       "No active payer enrollment covers the service date")
    # 4) Timely filing.
    days = store.day_diff(store.clock_now(), claim["service_date"])
    if days > payer["timely_filing_days"]:
        raise ApiError("ERR_TIMELY_FILING_EXCEEDED", 422, "Timely filing window exceeded")
    claim["submission_date"] = store.clock_now()
    claim["submitted_by_user_id"] = g.user_id
    claim["status"] = "SUBMITTED"
    touch(claim, bump_version=True)
    return success(serialize(claim), 200)


@app.route("/rcm/claims/<cid>/accept", methods=["POST"])
def accept_claim(cid):
    authenticate()
    require_roles("Biller")
    claim = get_claim(cid)
    get_body()  # clearinghouse_ref optional, not persisted
    if claim["status"] != "SUBMITTED":
        invalid_state()
    claim["status"] = "ACCEPTED"
    claim["_ever_accepted"] = True
    touch(claim, bump_version=True)
    return success(serialize(claim), 200)


@app.route("/rcm/claims/<cid>/close", methods=["POST"])
def close_claim(cid):
    authenticate()
    require_roles("Biller", "Coder")
    claim = get_claim(cid)
    status = claim["status"]
    if status == "DRAFT":
        claim["status"] = "VOID"
        touch(claim, bump_version=True)
    elif status == "PAID":
        claim["status"] = "CLOSED"
        touch(claim, bump_version=True)
        logic.recompute_practice_totals(get_practice(claim["practice_id"]), touch)
    elif status == "DENIED":
        claim["write_off_cents"] = claim["outstanding_balance_cents"]
        claim["outstanding_balance_cents"] = 0
        for d in store.denials.values():
            if d["claim_id"] == cid and d["status"] in ("OPEN", "UPHELD"):
                d["status"] = "WRITTEN_OFF"
                touch(d, bump_version=True)
        claim["status"] = "CLOSED"
        touch(claim, bump_version=True)
        logic.recompute_practice_totals(get_practice(claim["practice_id"]), touch)
    else:
        invalid_state()
    return success(serialize(claim), 200)


# ===========================================================================
# Denials
# ===========================================================================
@app.route("/rcm/claims/<cid>/denials", methods=["POST"])
def create_denial(cid):
    authenticate()
    require_roles("DenialSpecialist")
    claim = get_claim(cid)
    body = get_body()
    denial_code = require_string(body, "denial_code")
    denied_amount = require_int(body, "denied_amount_cents", money=True)
    denial_date = require_datetime(body, "denial_date")
    if claim["status"] not in ("SUBMITTED", "ACCEPTED"):
        invalid_state()
    rec = base_common({
        "claim_id": cid, "denial_code": denial_code,
        "denied_amount_cents": denied_amount, "denial_date": denial_date,
        "status": "OPEN",
    })
    store.denials[rec["id"]] = rec
    claim["status"] = "DENIED"
    touch(claim, bump_version=True)
    return success(serialize(rec), 201)


@app.route("/rcm/denials/<did>", methods=["GET"])
def get_denial_route(did):
    authenticate()
    require_roles("AccountManager", "DenialSpecialist", "Biller")
    return success(serialize(get_denial(did)), 200)


@app.route("/rcm/denials/<did>/appeals", methods=["GET"])
def list_denial_appeals(did):
    authenticate()
    require_roles("AccountManager", "DenialSpecialist")
    get_denial(did)
    items = [a for a in store.appeals.values() if a["denial_id"] == did]
    return paginate(items, serialize)


@app.route("/rcm/denials/<did>/appeals", methods=["POST"])
def create_appeal(did):
    authenticate()
    require_roles("DenialSpecialist")
    denial = get_denial(did)
    body = get_body()
    level = require_int(body, "level", required=False, min_value=1)
    if level is None:
        level = 1
    if level > 2:
        raise ApiError("ERR_VALIDATION", 422, "level must be 1 or 2")
    narrative = require_string(body, "narrative")
    claim = store.claims.get(denial["claim_id"])
    if claim is not None and claim["appeal_round"] >= 2:
        raise ApiError("ERR_APPEAL_LIMIT_EXCEEDED", 422,
                       "Appeal would exceed the maximum of two rounds")
    rec = base_common({
        "denial_id": did, "level": level, "narrative": narrative,
        "status": "DRAFT", "recovered_amount_cents": 0, "submitted_date": None,
    })
    store.appeals[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/rcm/appeals/<aid>", methods=["GET"])
def get_appeal_route(aid):
    authenticate()
    require_roles("AccountManager", "DenialSpecialist")
    return success(serialize(get_appeal(aid)), 200)


@app.route("/rcm/appeals/<aid>/submit", methods=["POST"])
def submit_appeal(aid):
    authenticate()
    require_roles("DenialSpecialist")
    appeal = get_appeal(aid)
    denial = store.denials.get(appeal["denial_id"])
    claim = store.claims.get(denial["claim_id"]) if denial else None
    payer = store.payers.get(claim["payer_id"]) if claim else None
    if appeal["status"] != "DRAFT":
        invalid_state()
    if denial is None or denial["status"] != "OPEN":
        invalid_state()
    days = store.day_diff(store.clock_now(), denial["denial_date"])
    if payer is not None and days > payer["appeal_window_days"]:
        raise ApiError("ERR_APPEAL_WINDOW_EXCEEDED", 422, "Appeal window exceeded")
    appeal["status"] = "SUBMITTED"
    appeal["submitted_date"] = store.clock_now()
    touch(appeal, bump_version=True)
    denial["status"] = "APPEALED"
    touch(denial, bump_version=True)
    if claim is not None:
        if claim["status"] != "DENIED":
            invalid_state()
        claim["status"] = "APPEALED"
        claim["appeal_round"] += 1
        touch(claim, bump_version=True)
    return success(serialize(appeal), 200)


@app.route("/rcm/appeals/<aid>/decision", methods=["POST"])
def decide_appeal(aid):
    authenticate()
    require_roles("DenialSpecialist")
    appeal = get_appeal(aid)
    body = get_body()
    outcome = require_enum(body, "outcome", {"OVERTURN", "UPHOLD", "WITHDRAW"})
    denial = store.denials.get(appeal["denial_id"])
    claim = store.claims.get(denial["claim_id"]) if denial else None
    if outcome == "WITHDRAW":
        if appeal["status"] != "DRAFT":
            invalid_state()
        appeal["status"] = "WITHDRAWN"
        touch(appeal, bump_version=True)
        return success(serialize(appeal), 200)
    # OVERTURN / UPHOLD require a SUBMITTED appeal.
    if appeal["status"] != "SUBMITTED":
        invalid_state()
    if outcome == "OVERTURN":
        recovered = require_int(body, "recovered_amount_cents", required=False, money=True)
        if recovered is None:
            recovered = 0
        appeal["status"] = "OVERTURNED"
        appeal["recovered_amount_cents"] = recovered
        touch(appeal, bump_version=True)
        if denial is not None:
            denial["status"] = "OVERTURNED"
            touch(denial, bump_version=True)
        if claim is not None:
            claim["write_off_cents"] = max(0, claim["write_off_cents"] - recovered)
            claim["status"] = "ACCEPTED"
            claim["_ever_accepted"] = True
            logic.recompute_claim_ledger(claim)
            touch(claim, bump_version=True)
            logic.recompute_practice_totals(get_practice(claim["practice_id"]), touch)
    else:  # UPHOLD
        appeal["status"] = "UPHELD"
        touch(appeal, bump_version=True)
        if denial is not None:
            denial["status"] = "UPHELD"
            touch(denial, bump_version=True)
        if claim is not None:
            claim["status"] = "DENIED"
            touch(claim, bump_version=True)
    return success(serialize(appeal), 200)


# ===========================================================================
# Remittance / payment posting
# ===========================================================================
@app.route("/rcm/remittances", methods=["POST"])
def create_remittance():
    authenticate()
    require_roles("PaymentPoster")
    body = get_body()
    payer_id = require_string(body, "payer_id")
    get_payer(payer_id)
    remittance_ref = require_string(body, "remittance_ref")
    total = require_int(body, "total_amount_cents", money=True)
    rec = base_common({
        "payer_id": payer_id, "remittance_ref": remittance_ref,
        "total_amount_cents": total, "allocated_amount_cents": 0,
        "unallocated_amount_cents": total, "status": "RECEIVED",
    })
    store.remittances[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/rcm/remittances/<rid>", methods=["GET"])
def get_remittance_route(rid):
    authenticate()
    require_roles("AccountManager", "PaymentPoster")
    return success(serialize(get_remittance(rid)), 200)


@app.route("/rcm/remittances/<rid>/postings", methods=["POST"])
def create_posting(rid):
    authenticate()
    require_roles("PaymentPoster")
    remittance = get_remittance(rid)
    body = get_body()
    claim_id = require_string(body, "claim_id")
    claim = get_claim(claim_id)
    insurance_paid = require_int(body, "insurance_paid_cents", money=True)
    patient_resp = require_int(body, "patient_responsibility_cents", money=True)
    adjustment = require_int(body, "adjustment_cents", money=True)
    expected_version = require_int(body, "expected_claim_version")
    if remittance["status"] not in ("RECEIVED", "POSTING"):
        invalid_state()
    # Overallocation (priority 10) before OCC (priority 11).
    if remittance["allocated_amount_cents"] + insurance_paid > remittance["total_amount_cents"]:
        raise ApiError("ERR_OVERALLOCATION", 422,
                       "Posting would over-allocate the remittance")
    if expected_version != claim["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale claim version")
    rec = base_common({
        "remittance_id": rid, "claim_id": claim_id,
        "insurance_paid_cents": insurance_paid,
        "patient_responsibility_cents": patient_resp,
        "adjustment_cents": adjustment, "status": "POSTED",
    })
    store.payment_postings[rec["id"]] = rec
    if remittance["status"] == "RECEIVED":
        remittance["status"] = "POSTING"
    logic.recompute_remittance_allocation(remittance)
    touch(remittance, bump_version=True)
    logic.recompute_claim_ledger(claim)
    if claim["status"] == "ACCEPTED" and claim["outstanding_balance_cents"] <= 0:
        claim["status"] = "PAID"
    touch(claim, bump_version=True)
    logic.recompute_practice_totals(get_practice(claim["practice_id"]), touch)
    return success(serialize(rec), 201)


@app.route("/rcm/remittances/<rid>/postings", methods=["GET"])
def list_remittance_postings(rid):
    authenticate()
    require_roles("AccountManager", "PaymentPoster")
    get_remittance(rid)
    items = [p for p in store.payment_postings.values() if p["remittance_id"] == rid]
    return paginate(items, serialize)


@app.route("/rcm/remittances/<rid>/finalize", methods=["POST"])
def finalize_remittance(rid):
    authenticate()
    require_roles("PaymentPoster")
    remittance = get_remittance(rid)
    if remittance["status"] != "POSTING":
        invalid_state()
    if remittance["allocated_amount_cents"] != remittance["total_amount_cents"]:
        raise ApiError("ERR_REMITTANCE_NOT_BALANCED", 422, "Remittance is not fully reconciled")
    remittance["status"] = "POSTED"
    touch(remittance, bump_version=True)
    return success(serialize(remittance), 200)


@app.route("/rcm/payment-postings/<pid>", methods=["GET"])
def get_posting_route(pid):
    authenticate()
    require_roles("AccountManager", "PaymentPoster")
    return success(serialize(get_posting(pid)), 200)


@app.route("/rcm/payment-postings/<pid>/reverse", methods=["POST"])
def reverse_posting(pid):
    authenticate()
    require_roles("PaymentPoster")
    posting = get_posting(pid)
    body = get_body()
    require_string(body, "reason")
    if posting["status"] != "POSTED":
        invalid_state()
    posting["status"] = "REVERSED"
    touch(posting, bump_version=True)
    claim = store.claims.get(posting["claim_id"])
    remittance = store.remittances.get(posting["remittance_id"])
    if claim is not None:
        logic.recompute_claim_ledger(claim)
        if claim["status"] == "PAID" and claim["outstanding_balance_cents"] > 0:
            claim["status"] = "ACCEPTED"
        touch(claim, bump_version=True)
        logic.recompute_practice_totals(get_practice(claim["practice_id"]), touch)
    if remittance is not None:
        logic.recompute_remittance_allocation(remittance)
        siblings = [p for p in store.payment_postings.values()
                    if p["remittance_id"] == remittance["id"]]
        if remittance["status"] == "POSTING" and siblings and all(p["status"] == "REVERSED" for p in siblings):
            remittance["status"] = "REVERSED"
        touch(remittance, bump_version=True)
    return success(serialize(posting), 200)


# ===========================================================================
# Patient statements
# ===========================================================================
@app.route("/rcm/patient-statements", methods=["POST"])
def create_statement():
    authenticate()
    require_roles("PaymentPoster", "AccountManager")
    body = get_body()
    claim_id = require_string(body, "claim_id")
    claim = get_claim(claim_id)
    rec = base_common({
        "claim_id": claim_id, "practice_id": claim["practice_id"],
        "statement_amount_cents": claim["patient_responsibility_cents"],
        "amount_paid_cents": 0, "first_sent_date": None,
        "aging_bucket": "CURRENT", "status": "DRAFT",
    })
    store.patient_statements[rec["id"]] = rec
    return success(serialize(rec), 201)


@app.route("/rcm/patient-statements/<sid>", methods=["GET"])
def get_statement_route(sid):
    authenticate()
    require_roles("AccountManager", "PaymentPoster", "PracticeUser")
    rec = get_statement(sid)
    practice_user_can_read(rec["practice_id"])
    rec["aging_bucket"] = logic.aging_bucket_for(rec)
    return success(serialize(rec), 200)


@app.route("/rcm/patient-statements/<sid>/send", methods=["POST"])
def send_statement(sid):
    authenticate()
    require_roles("PaymentPoster")
    rec = get_statement(sid)
    if rec["status"] != "DRAFT":
        invalid_state()
    if rec["statement_amount_cents"] <= 0:
        invalid_state()
    rec["first_sent_date"] = store.clock_now()
    rec["aging_bucket"] = "CURRENT"
    rec["status"] = "SENT"
    touch(rec, bump_version=True)
    return success(serialize(rec), 200)


@app.route("/rcm/patient-statements/<sid>/record-payment", methods=["POST"])
def record_statement_payment(sid):
    authenticate()
    require_roles("PaymentPoster")
    rec = get_statement(sid)
    body = get_body()
    amount = require_int(body, "amount_cents", money=True)
    if rec["status"] not in ("SENT", "PARTIAL", "COLLECTIONS"):
        invalid_state()
    rec["amount_paid_cents"] += amount
    claim = store.claims.get(rec["claim_id"])
    if claim is not None:
        logic.recompute_claim_ledger(claim)
        touch(claim, bump_version=False)
    if rec["amount_paid_cents"] >= rec["statement_amount_cents"]:
        rec["status"] = "PAID"
        if claim is not None:
            logic.recompute_practice_totals(get_practice(claim["practice_id"]), touch)
    else:
        rec["status"] = "PARTIAL"
    touch(rec, bump_version=True)
    return success(serialize(rec), 200)


@app.route("/rcm/patient-statements/<sid>/collections", methods=["POST"])
def statement_collections(sid):
    authenticate()
    require_roles("PaymentPoster")
    rec = get_statement(sid)
    rec["aging_bucket"] = logic.aging_bucket_for(rec)
    if rec["status"] not in ("SENT", "PARTIAL"):
        invalid_state()
    if rec["aging_bucket"] != "OVER_90":
        invalid_state()
    rec["status"] = "COLLECTIONS"
    touch(rec, bump_version=True)
    return success(serialize(rec), 200)


@app.route("/rcm/patient-statements/<sid>/write-off", methods=["POST"])
def statement_write_off(sid):
    authenticate()
    require_roles("AccountManager")
    rec = get_statement(sid)
    if rec["status"] != "COLLECTIONS":
        invalid_state()
    remaining = rec["statement_amount_cents"] - rec["amount_paid_cents"]
    if remaining < 0:
        remaining = 0
    claim = store.claims.get(rec["claim_id"])
    if claim is not None:
        claim["write_off_cents"] += remaining
        logic.recompute_claim_ledger(claim)
        touch(claim, bump_version=True)
        logic.recompute_practice_totals(get_practice(claim["practice_id"]), touch)
    rec["status"] = "WRITTEN_OFF"
    touch(rec, bump_version=True)
    return success(serialize(rec), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
