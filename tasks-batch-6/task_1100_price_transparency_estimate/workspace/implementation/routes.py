"""All API route handlers."""
from decimal import Decimal
from datetime import timedelta

from flask import Blueprint, request

import core
from core import db, err, bump, stamp_new, serialize, render_dt, parse_iso, round_half_up
import web
from web import (authenticate, require_owner, get_body, created, ok, paginate,
                 req_str, req_int, req_number, req_enum, req_bool, opt_bool, req_datetime)

bp = Blueprint("api", __name__)

ALL_ROLES = ["PatientUser", "ProviderStaff", "PayerAnalyst", "Admin"]


# ----------------------------------------------------------------------------
# Existence helpers
# ----------------------------------------------------------------------------
def get_or_404(table, rid, error_id):
    rec = table.get(rid)
    if rec is None:
        err(error_id, f"{error_id}: {rid}")
    return rec


def filter_val(records, field, value):
    if value is None:
        return records
    return [r for r in records if str(r.get(field)) == str(value)]


def filter_bool(records, field, raw):
    if raw is None:
        return records
    want = str(raw).lower() in ("true", "1", "yes")
    return [r for r in records if bool(r.get(field)) == want]


# ============================================================================
# Procedure
# ============================================================================
@bp.route("/procedures", methods=["POST"])
def create_procedure():
    authenticate(["ProviderStaff"])
    body = get_body()
    rec = {
        "code_system": req_enum(body, "code_system", {"CPT", "HCPCS", "DRG"}),
        "code": req_str(body, "code"),
        "description": req_str(body, "description"),
        "setting": req_enum(body, "setting", {"INPATIENT", "OUTPATIENT"}),
        "is_shoppable": opt_bool(body, "is_shoppable", True),
        "requires_prior_auth": opt_bool(body, "requires_prior_auth", False),
        "gross_charge_cents": req_int(body, "gross_charge_cents", minimum=0),
    }
    stamp_new(rec)
    db.procedures[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/procedures/<pid>", methods=["GET"])
def get_procedure(pid):
    authenticate(ALL_ROLES)
    return ok(serialize(get_or_404(db.procedures, pid, "ERR_PROCEDURE_NOT_FOUND")))


@bp.route("/procedures", methods=["GET"])
def list_procedures():
    authenticate(ALL_ROLES)
    recs = list(db.procedures.values())
    recs = filter_val(recs, "code_system", request.args.get("code_system"))
    recs = filter_bool(recs, "is_shoppable", request.args.get("is_shoppable"))
    return paginate(recs, serialize)


@bp.route("/procedures/<pid>/comparison", methods=["GET"])
def procedure_comparison(pid):
    authenticate(ALL_ROLES)
    procedure = get_or_404(db.procedures, pid, "ERR_PROCEDURE_NOT_FOUND")
    payer_type = request.args.get("payer_type")

    candidates = []
    for r in db.rates.values():
        if r["procedure_id"] != pid or r["superseded"]:
            continue
        contract = db.contracts.get(r["contract_id"])
        if not contract or contract["status"] != "ACTIVE":
            continue
        if payer_type is not None and contract["payer_type"] != payer_type:
            continue
        candidates.append(core.rate_allowed(r, procedure))

    n = len(candidates)
    if n == 0:
        median = None
        minimum = None
    else:
        candidates.sort()
        minimum = candidates[0]
        if n % 2 == 1:
            median = candidates[n // 2]
        else:
            median = round_half_up(Decimal(candidates[n // 2 - 1] + candidates[n // 2]) / Decimal(2))
    data = {
        "procedure_id": pid,
        "sample_count": n,
        "median_allowed_cents": median,
        "min_allowed_cents": minimum,
        "gross_charge_cents": procedure["gross_charge_cents"],
        "self_pay_price_cents": core.self_pay_price(procedure["gross_charge_cents"]),
    }
    return ok(data)


# ============================================================================
# PayerContract
# ============================================================================
@bp.route("/payer-contracts", methods=["POST"])
def create_contract():
    authenticate(["PayerAnalyst"])
    body = get_body()
    rec = {
        "payer_name": req_str(body, "payer_name"),
        "payer_type": req_enum(body, "payer_type", {"COMMERCIAL", "MEDICARE", "MEDICAID"}),
        "methodology": req_enum(body, "methodology", {"FEE_SCHEDULE", "PERCENT_OF_CHARGE", "CASE_RATE"}),
        "effective_date": req_datetime(body, "effective_date"),
        "expiration_date": req_datetime(body, "expiration_date"),
        "status": "DRAFT",
    }
    stamp_new(rec)
    db.contracts[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/payer-contracts/<cid>", methods=["GET"])
def get_contract(cid):
    authenticate(ALL_ROLES)
    return ok(serialize(get_or_404(db.contracts, cid, "ERR_CONTRACT_NOT_FOUND")))


@bp.route("/payer-contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    authenticate(["PayerAnalyst"])
    contract = get_or_404(db.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    if contract["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "contract is not in DRAFT")
    contract["status"] = "ACTIVE"
    bump(contract)
    return ok(serialize(contract))


# ============================================================================
# NegotiatedRate
# ============================================================================
@bp.route("/negotiated-rates", methods=["POST"])
def create_rate():
    authenticate(["PayerAnalyst"])
    body = get_body()
    contract_id = req_str(body, "contract_id")
    procedure_id = req_str(body, "procedure_id")
    rate_type = req_enum(body, "rate_type", {"FLAT", "PERCENT"})
    flat_amount = None
    percent = None
    if rate_type == "FLAT":
        flat_amount = req_int(body, "flat_amount_cents", minimum=0)
    else:
        percent = req_number(body, "percent_of_charge", minimum=0, maximum=1, min_exclusive=True)
    expected_version = req_int(body, "expected_contract_version")

    # existence (left-to-right: contract_id then procedure_id)
    contract = get_or_404(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    get_or_404(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")

    # OCC on contract
    if expected_version != contract["version"]:
        err("ERR_STALE_CONTRACT_VERSION", "expected_contract_version mismatch")

    # supersede prior live rate for same (contract, procedure)
    prior = core.find_live_rate(contract_id, procedure_id)
    if prior is not None:
        prior["superseded"] = True
        bump(prior)

    rec = {
        "contract_id": contract_id,
        "procedure_id": procedure_id,
        "rate_type": rate_type,
        "flat_amount_cents": flat_amount,
        "percent_of_charge": percent,
        "superseded": False,
    }
    stamp_new(rec)
    db.rates[rec["id"]] = rec
    bump(contract)
    return created(serialize(rec))


@bp.route("/negotiated-rates/<rid>", methods=["GET"])
def get_rate(rid):
    authenticate(ALL_ROLES)
    return ok(serialize(get_or_404(db.rates, rid, "ERR_RATE_NOT_FOUND")))


@bp.route("/negotiated-rates", methods=["GET"])
def list_rates():
    authenticate(ALL_ROLES)
    recs = list(db.rates.values())
    recs = filter_val(recs, "contract_id", request.args.get("contract_id"))
    recs = filter_val(recs, "procedure_id", request.args.get("procedure_id"))
    recs = filter_bool(recs, "superseded", request.args.get("superseded"))
    return paginate(recs, serialize)


# ============================================================================
# BenefitPlan
# ============================================================================
@bp.route("/benefit-plans", methods=["POST"])
def create_plan():
    authenticate(["PayerAnalyst"])
    body = get_body()
    deductible = req_int(body, "individual_deductible_cents", minimum=0)
    oop_max = req_int(body, "individual_oop_max_cents", minimum=0)
    if oop_max < deductible:
        err("ERR_VALIDATION", "individual_oop_max_cents must be >= individual_deductible_cents")
    rec = {
        "payer_name": req_str(body, "payer_name"),
        "plan_year": req_int(body, "plan_year"),
        "individual_deductible_cents": deductible,
        "individual_oop_max_cents": oop_max,
        "coinsurance_rate": req_number(body, "coinsurance_rate", minimum=0, maximum=1),
        "copay_cents": req_int(body, "copay_cents", minimum=0),
        "in_network": opt_bool(body, "in_network", True),
    }
    stamp_new(rec)
    db.plans[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/benefit-plans/<bid>", methods=["GET"])
def get_plan(bid):
    authenticate(ALL_ROLES)
    return ok(serialize(get_or_404(db.plans, bid, "ERR_BENEFIT_PLAN_NOT_FOUND")))


# ============================================================================
# Patient
# ============================================================================
@bp.route("/patients", methods=["POST"])
def create_patient():
    authenticate(["ProviderStaff"])
    body = get_body()
    name = req_str(body, "name")
    member_id = req_str(body, "member_id")
    benefit_plan_id = req_str(body, "benefit_plan_id")
    get_or_404(db.plans, benefit_plan_id, "ERR_BENEFIT_PLAN_NOT_FOUND")
    rec = {
        "name": name,
        "member_id": member_id,
        "benefit_plan_id": benefit_plan_id,
        "deductible_met_cents": 0,
        "oop_met_cents": 0,
    }
    stamp_new(rec)
    db.patients[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    authenticate(ALL_ROLES)
    return ok(serialize(get_or_404(db.patients, pid, "ERR_PATIENT_NOT_FOUND")))


@bp.route("/patients", methods=["GET"])
def list_patients():
    authenticate(["ProviderStaff", "PayerAnalyst", "Admin"])
    recs = list(db.patients.values())
    recs = filter_val(recs, "benefit_plan_id", request.args.get("benefit_plan_id"))
    return paginate(recs, serialize)


@bp.route("/patients/<pid>/accumulation-adjustments", methods=["POST"])
def accumulation_adjustment(pid):
    authenticate(["PayerAnalyst"])
    body = get_body()
    ded_delta = req_int(body, "deductible_delta_cents")
    oop_delta = req_int(body, "oop_delta_cents")
    req_str(body, "source")
    patient = get_or_404(db.patients, pid, "ERR_PATIENT_NOT_FOUND")
    patient["deductible_met_cents"] += ded_delta
    patient["oop_met_cents"] += oop_delta
    bump(patient)
    core.cascade_recompute(pid)
    return ok(serialize(patient))


# ============================================================================
# Provider
# ============================================================================
@bp.route("/providers", methods=["POST"])
def create_provider():
    authenticate(["ProviderStaff"])
    body = get_body()
    rec = {
        "name": req_str(body, "name"),
        "npi": req_str(body, "npi"),
        "specialty": req_str(body, "specialty"),
    }
    stamp_new(rec)
    db.providers[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/providers/<pid>", methods=["GET"])
def get_provider(pid):
    authenticate(ALL_ROLES)
    return ok(serialize(get_or_404(db.providers, pid, "ERR_PROVIDER_NOT_FOUND")))


# ============================================================================
# Room
# ============================================================================
@bp.route("/rooms", methods=["POST"])
def create_room():
    authenticate(["ProviderStaff"])
    body = get_body()
    rec = {
        "name": req_str(body, "name"),
        "room_type": req_enum(body, "room_type", {"EXAM", "PROCEDURE", "IMAGING"}),
    }
    stamp_new(rec)
    db.rooms[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/rooms/<rid>", methods=["GET"])
def get_room(rid):
    authenticate(ALL_ROLES)
    return ok(serialize(get_or_404(db.rooms, rid, "ERR_ROOM_NOT_FOUND")))


# ============================================================================
# Estimate
# ============================================================================
def _new_estimate_record(patient_id, estimate_type, contract_id):
    rec = {
        "patient_id": patient_id,
        "contract_id": contract_id,
        "estimate_type": estimate_type,
        "status": "DRAFT",
        "allowed_amount_cents": None,
        "deductible_applied_cents": None,
        "coinsurance_cents": None,
        "copay_cents": None,
        "patient_responsibility_cents": None,
        "plan_paid_cents": None,
        "responsibility_basis": None,
        "recompute_required": False,
        "issued_at": None,
        "settled_at": None,
    }
    stamp_new(rec)
    return rec


@bp.route("/estimates", methods=["POST"])
def create_estimate():
    user_id, role = authenticate(["PatientUser", "ProviderStaff"])
    body = get_body()
    # ownership (priority 2): PatientUser must target its own patient
    if role == "PatientUser":
        pid_in = body.get("patient_id")
        if isinstance(pid_in, str) and pid_in != user_id:
            err("ERR_UNAUTHORIZED", "PatientUser does not own the target patient")
    # validation (priority 3)
    patient_id = req_str(body, "patient_id")
    estimate_type = req_enum(body, "estimate_type", {"GFE_INSURED", "GFE_SELFPAY"})
    expected_version = req_int(body, "expected_patient_version")
    contract_id = body.get("contract_id")
    if contract_id is not None and not isinstance(contract_id, str):
        err("ERR_VALIDATION", "contract_id must be a string")
    # existence (priority 4): patient then contract (declaration order)
    patient = get_or_404(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    if role == "PatientUser":
        require_owner(role, user_id, patient_id)
    if contract_id is not None:
        get_or_404(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    # OCC (priority 5)
    if expected_version != patient["version"]:
        err("ERR_STALE_PATIENT_VERSION", "expected_patient_version mismatch")
    # type/contract consistency (priority 8)
    if estimate_type == "GFE_INSURED" and contract_id is None:
        err("ERR_ESTIMATE_TYPE_CONTRACT_MISMATCH", "GFE_INSURED requires contract_id")
    if estimate_type == "GFE_SELFPAY" and contract_id is not None:
        err("ERR_ESTIMATE_TYPE_CONTRACT_MISMATCH", "GFE_SELFPAY forbids contract_id")

    rec = _new_estimate_record(patient_id, estimate_type, contract_id)
    db.estimates[rec["id"]] = rec
    bump(patient)  # each create advances patient.version
    return created(serialize(rec))


@bp.route("/estimates/<eid>", methods=["GET"])
def get_estimate(eid):
    user_id, role = authenticate(ALL_ROLES)
    est = get_or_404(db.estimates, eid, "ERR_ESTIMATE_NOT_FOUND")
    require_owner(role, user_id, est["patient_id"])
    return ok(serialize(est))


@bp.route("/estimates", methods=["GET"])
def list_estimates():
    authenticate(ALL_ROLES)
    recs = list(db.estimates.values())
    recs = filter_val(recs, "patient_id", request.args.get("patient_id"))
    recs = filter_val(recs, "contract_id", request.args.get("contract_id"))
    recs = filter_val(recs, "status", request.args.get("status"))
    return paginate(recs, serialize)


@bp.route("/estimates/<eid>/lines", methods=["POST"])
def add_line(eid):
    user_id, role = authenticate(["PatientUser", "ProviderStaff"])
    body = get_body()
    procedure_id = req_str(body, "procedure_id")
    est = get_or_404(db.estimates, eid, "ERR_ESTIMATE_NOT_FOUND")
    require_owner(role, user_id, est["patient_id"])
    get_or_404(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    if est["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "lines may only be added to a DRAFT estimate")
    existing = core.lines_of(eid)
    line_number = len(existing) + 1
    rec = {
        "estimate_id": eid,
        "procedure_id": procedure_id,
        "line_number": line_number,
        "allowed_amount_cents": None,
        "deductible_applied_cents": None,
        "coinsurance_cents": None,
        "line_patient_responsibility_cents": None,
        "pinned_rate_id": None,
        "pinned_rate_version": None,
    }
    stamp_new(rec)
    db.lines[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/estimates/<eid>/issue", methods=["POST"])
def issue_estimate(eid):
    authenticate(["ProviderStaff"])
    est = get_or_404(db.estimates, eid, "ERR_ESTIMATE_NOT_FOUND")
    # own-state (priority 6)
    if est["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "estimate is not in DRAFT")
    insured = est["estimate_type"] == "GFE_INSURED"
    # cross-entity state (priority 7): contract ACTIVE for insured
    if insured:
        contract = db.contracts.get(est["contract_id"])
        if contract is None:
            err("ERR_CONTRACT_NOT_FOUND", "contract missing")
        if contract["status"] != "ACTIVE":
            err("ERR_CONTRACT_NOT_ACTIVE", "referenced contract is not ACTIVE")
    # at least one line (priority 8)
    lines = core.lines_of(eid)
    if not lines:
        err("ERR_ESTIMATE_NO_LINES", "estimate has no lines")
    # every line has a live negotiated rate (priority 10)
    if insured:
        for line in lines:
            if core.find_live_rate(est["contract_id"], line["procedure_id"]) is None:
                err("ERR_NO_NEGOTIATED_RATE", "line procedure has no non-superseded rate")

    core.price_lines_at_issue(est)
    core.aggregate_and_responsibility(est, "ESTIMATE")
    est["status"] = "ISSUED"
    est["issued_at"] = render_dt(db.clock)
    bump(est)
    return ok(serialize(est))


@bp.route("/estimates/<eid>/accept", methods=["POST"])
def accept_estimate(eid):
    user_id, role = authenticate(["PatientUser"])
    est = get_or_404(db.estimates, eid, "ERR_ESTIMATE_NOT_FOUND")
    require_owner(role, user_id, est["patient_id"])
    if est["status"] != "ISSUED":
        err("ERR_INVALID_STATE", "estimate is not ISSUED")
    est["status"] = "ACCEPTED"
    bump(est)
    return ok(serialize(est))


@bp.route("/estimates/<eid>/void", methods=["POST"])
def void_estimate(eid):
    authenticate(["ProviderStaff"])
    est = get_or_404(db.estimates, eid, "ERR_ESTIMATE_NOT_FOUND")
    if est["status"] not in ("ISSUED", "ACCEPTED", "SETTLED"):
        err("ERR_INVALID_STATE", "estimate cannot be voided from its current state")
    was_settled = est["status"] == "SETTLED"
    est["status"] = "VOID"
    bump(est)
    if was_settled:
        patient = db.patients[est["patient_id"]]
        patient["deductible_met_cents"] -= est["deductible_applied_cents"]
        patient["oop_met_cents"] -= est["patient_responsibility_cents"]
        bump(patient)
        core.cascade_recompute(patient["id"], exclude_id=est["id"])
    return ok(serialize(est))


# ============================================================================
# EstimateLine
# ============================================================================
@bp.route("/estimate-lines/<lid>", methods=["GET"])
def get_line(lid):
    authenticate(ALL_ROLES)
    return ok(serialize(get_or_404(db.lines, lid, "ERR_LINE_NOT_FOUND")))


@bp.route("/estimate-lines", methods=["GET"])
def list_lines():
    authenticate(ALL_ROLES)
    recs = list(db.lines.values())
    recs = filter_val(recs, "estimate_id", request.args.get("estimate_id"))
    recs = filter_val(recs, "procedure_id", request.args.get("procedure_id"))
    return paginate(recs, serialize)


# ============================================================================
# PriorAuthorization
# ============================================================================
@bp.route("/prior-authorizations", methods=["POST"])
def create_prior_auth():
    authenticate(["ProviderStaff"])
    body = get_body()
    estimate_id = req_str(body, "estimate_id")
    procedure_code = req_str(body, "procedure_code")
    requested_units = req_int(body, "requested_units", minimum=1)
    get_or_404(db.estimates, estimate_id, "ERR_ESTIMATE_NOT_FOUND")
    rec = {
        "estimate_id": estimate_id,
        "procedure_code": procedure_code,
        "requested_units": requested_units,
        "status": "REQUESTED",
        "auth_number": None,
        "approved_units": None,
        "expiration_date": None,
        "denial_reason": None,
    }
    stamp_new(rec)
    db.prior_auths[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/prior-authorizations/<aid>", methods=["GET"])
def get_prior_auth(aid):
    authenticate(ALL_ROLES)
    return ok(serialize(get_or_404(db.prior_auths, aid, "ERR_PRIOR_AUTH_NOT_FOUND")))


@bp.route("/prior-authorizations", methods=["GET"])
def list_prior_auths():
    authenticate(ALL_ROLES)
    recs = list(db.prior_auths.values())
    recs = filter_val(recs, "estimate_id", request.args.get("estimate_id"))
    recs = filter_val(recs, "status", request.args.get("status"))
    return paginate(recs, serialize)


@bp.route("/prior-authorizations/<aid>/approve", methods=["POST"])
def approve_prior_auth(aid):
    authenticate(["PayerAnalyst"])
    body = get_body()
    auth_number = req_str(body, "auth_number")
    approved_units = req_int(body, "approved_units", minimum=1)
    expiration_date = req_datetime(body, "expiration_date")
    pa = get_or_404(db.prior_auths, aid, "ERR_PRIOR_AUTH_NOT_FOUND")
    if pa["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", "prior authorization is not REQUESTED")
    pa["status"] = "APPROVED"
    pa["auth_number"] = auth_number
    pa["approved_units"] = approved_units
    pa["expiration_date"] = expiration_date
    bump(pa)
    return ok(serialize(pa))


@bp.route("/prior-authorizations/<aid>/deny", methods=["POST"])
def deny_prior_auth(aid):
    authenticate(["PayerAnalyst"])
    body = get_body()
    denial_reason = req_str(body, "denial_reason")
    pa = get_or_404(db.prior_auths, aid, "ERR_PRIOR_AUTH_NOT_FOUND")
    if pa["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", "prior authorization is not REQUESTED")
    pa["status"] = "DENIED"
    pa["denial_reason"] = denial_reason
    bump(pa)
    return ok(serialize(pa))


# ============================================================================
# Appointment
# ============================================================================
def _intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and a_end > b_start


@bp.route("/appointments", methods=["POST"])
def create_appointment():
    authenticate(["ProviderStaff"])
    body = get_body()
    patient_id = req_str(body, "patient_id")
    estimate_id = req_str(body, "estimate_id")
    provider_id = req_str(body, "provider_id")
    room_id = req_str(body, "room_id")
    prior_auth_id = body.get("prior_auth_id")
    if prior_auth_id is not None and not isinstance(prior_auth_id, str):
        err("ERR_VALIDATION", "prior_auth_id must be a string")
    scheduled_start = req_datetime(body, "scheduled_start")
    scheduled_end = req_datetime(body, "scheduled_end")

    # existence, declaration order: patient, estimate, provider, room, prior_auth
    get_or_404(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    est = get_or_404(db.estimates, estimate_id, "ERR_ESTIMATE_NOT_FOUND")
    get_or_404(db.providers, provider_id, "ERR_PROVIDER_NOT_FOUND")
    get_or_404(db.rooms, room_id, "ERR_ROOM_NOT_FOUND")
    if prior_auth_id is not None:
        get_or_404(db.prior_auths, prior_auth_id, "ERR_PRIOR_AUTH_NOT_FOUND")

    # cross-entity state (priority 7): estimate ACCEPTED
    if est["status"] != "ACCEPTED":
        err("ERR_ESTIMATE_NOT_ACCEPTED", "estimate is not ACCEPTED")

    start_dt = parse_iso(scheduled_start)
    end_dt = parse_iso(scheduled_end)

    # prior-auth gating (priority 9)
    requires_pa = any(
        db.procedures[l["procedure_id"]]["requires_prior_auth"]
        for l in core.lines_of(estimate_id)
    )
    if requires_pa:
        if prior_auth_id is None:
            err("ERR_PRIOR_AUTH_NOT_APPROVED", "prior authorization required")
        pa = db.prior_auths[prior_auth_id]
        if pa["status"] != "APPROVED":
            err("ERR_PRIOR_AUTH_NOT_APPROVED", "prior authorization is not APPROVED")
        if pa["expiration_date"] is not None and parse_iso(pa["expiration_date"]) < start_dt:
            err("ERR_PRIOR_AUTH_EXPIRED", "prior authorization expired before appointment start")

    # provider availability (priority 11): buffered by CLEANUP_BUFFER_MINUTES
    buffer = timedelta(minutes=core.CLEANUP_BUFFER_MINUTES)
    for ap in db.appointments.values():
        if ap["provider_id"] != provider_id or ap["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        e_start = parse_iso(ap["scheduled_start"])
        e_end = parse_iso(ap["scheduled_end"])
        if _intervals_overlap(start_dt, end_dt, e_start - buffer, e_end + buffer):
            err("ERR_PROVIDER_UNAVAILABLE", "provider is not available")

    # room availability (priority 12): strict half-open, no buffer
    for ap in db.appointments.values():
        if ap["room_id"] != room_id or ap["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        e_start = parse_iso(ap["scheduled_start"])
        e_end = parse_iso(ap["scheduled_end"])
        if _intervals_overlap(start_dt, end_dt, e_start, e_end):
            err("ERR_ROOM_UNAVAILABLE", "room is not available")

    rec = {
        "patient_id": patient_id,
        "estimate_id": estimate_id,
        "provider_id": provider_id,
        "room_id": room_id,
        "prior_auth_id": prior_auth_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
    }
    stamp_new(rec)
    db.appointments[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    user_id, role = authenticate(ALL_ROLES)
    ap = get_or_404(db.appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
    require_owner(role, user_id, ap["patient_id"])
    return ok(serialize(ap))


@bp.route("/appointments", methods=["GET"])
def list_appointments():
    authenticate(ALL_ROLES)
    recs = list(db.appointments.values())
    for f in ("patient_id", "estimate_id", "provider_id", "room_id", "prior_auth_id", "status"):
        recs = filter_val(recs, f, request.args.get(f))
    return paginate(recs, serialize)


@bp.route("/appointments/<aid>/complete", methods=["POST"])
def complete_appointment(aid):
    authenticate(["ProviderStaff"])
    ap = get_or_404(db.appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
    if ap["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "appointment is not SCHEDULED")
    ap["status"] = "COMPLETED"
    bump(ap)

    # cascade: settle linked estimate
    est = db.estimates.get(ap["estimate_id"])
    if est is not None and est["status"] == "ACCEPTED":
        patient = db.patients[est["patient_id"]]
        core.aggregate_and_responsibility(est, "FINAL")
        est["settled_at"] = render_dt(db.clock)
        est["status"] = "SETTLED"
        bump(est)
        patient["deductible_met_cents"] += est["deductible_applied_cents"]
        patient["oop_met_cents"] += est["patient_responsibility_cents"]
        bump(patient)
        core.cascade_recompute(patient["id"], exclude_id=est["id"])

    # cascade: consume linked approved prior auth
    if ap["prior_auth_id"] is not None:
        pa = db.prior_auths.get(ap["prior_auth_id"])
        if pa is not None and pa["status"] == "APPROVED":
            pa["status"] = "CONSUMED"
            bump(pa)

    return ok(serialize(ap))


@bp.route("/appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    user_id, role = authenticate(["ProviderStaff", "PatientUser"])
    ap = get_or_404(db.appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
    require_owner(role, user_id, ap["patient_id"])
    if ap["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "appointment is not SCHEDULED")
    ap["status"] = "CANCELLED"
    bump(ap)
    return ok(serialize(ap))


# ============================================================================
# Dispute
# ============================================================================
@bp.route("/disputes", methods=["POST"])
def create_dispute():
    user_id, role = authenticate(["PatientUser"])
    body = get_body()
    estimate_id = req_str(body, "estimate_id")
    reason = req_str(body, "reason")
    disputed_amount = req_int(body, "disputed_amount_cents", minimum=0)
    est = get_or_404(db.estimates, estimate_id, "ERR_ESTIMATE_NOT_FOUND")
    require_owner(role, user_id, est["patient_id"])
    if est["status"] != "ISSUED":
        err("ERR_INVALID_STATE", "estimate is not ISSUED")
    rec = {
        "estimate_id": estimate_id,
        "reason": reason,
        "disputed_amount_cents": disputed_amount,
        "status": "OPEN",
        "resolution_note": None,
        "adjusted_patient_responsibility_cents": None,
    }
    stamp_new(rec)
    db.disputes[rec["id"]] = rec
    est["status"] = "DISPUTED"
    bump(est)
    return created(serialize(rec))


@bp.route("/disputes/<did>", methods=["GET"])
def get_dispute(did):
    user_id, role = authenticate(ALL_ROLES)
    d = get_or_404(db.disputes, did, "ERR_DISPUTE_NOT_FOUND")
    est = db.estimates.get(d["estimate_id"])
    if est is not None:
        require_owner(role, user_id, est["patient_id"])
    return ok(serialize(d))


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    authenticate(ALL_ROLES)
    recs = list(db.disputes.values())
    recs = filter_val(recs, "estimate_id", request.args.get("estimate_id"))
    recs = filter_val(recs, "status", request.args.get("status"))
    return paginate(recs, serialize)


@bp.route("/disputes/<did>/assign", methods=["POST"])
def assign_dispute(did):
    authenticate(["ProviderStaff"])
    d = get_or_404(db.disputes, did, "ERR_DISPUTE_NOT_FOUND")
    if d["status"] != "OPEN":
        err("ERR_INVALID_STATE", "dispute is not OPEN")
    d["status"] = "UNDER_REVIEW"
    bump(d)
    return ok(serialize(d))


@bp.route("/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    authenticate(["ProviderStaff"])
    body = get_body()
    resolution = req_enum(body, "resolution", {"UPHELD", "ADJUSTED"})
    note = body.get("resolution_note")
    if note is not None and not isinstance(note, str):
        err("ERR_VALIDATION", "resolution_note must be a string")
    d = get_or_404(db.disputes, did, "ERR_DISPUTE_NOT_FOUND")
    if d["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", "dispute is not UNDER_REVIEW")
    est = db.estimates.get(d["estimate_id"])

    if resolution == "ADJUSTED":
        adjusted = body.get("adjusted_patient_responsibility_cents")
        if not (isinstance(adjusted, int) and not isinstance(adjusted, bool)):
            err("ERR_INVALID_ADJUSTMENT", "adjusted_patient_responsibility_cents required for ADJUSTED")
        cap = est["patient_responsibility_cents"] if est is not None else 0
        if adjusted < 0 or (cap is not None and adjusted > cap):
            err("ERR_INVALID_ADJUSTMENT", "adjusted value out of range")
        d["status"] = "RESOLVED_ADJUSTED"
        d["adjusted_patient_responsibility_cents"] = adjusted
        if note is not None:
            d["resolution_note"] = note
        bump(d)
        if est is not None:
            est["status"] = "ISSUED"
            est["patient_responsibility_cents"] = adjusted
            est["plan_paid_cents"] = est["allowed_amount_cents"] - adjusted
            bump(est)
    else:  # UPHELD
        d["status"] = "RESOLVED_UPHELD"
        if note is not None:
            d["resolution_note"] = note
        bump(d)
        if est is not None:
            est["status"] = "ISSUED"
            bump(est)

    return ok(serialize(d))


# ============================================================================
# Reporting + logical clock
# ============================================================================
@bp.route("/reports/price-transparency", methods=["GET"])
def price_transparency_report():
    authenticate(["Admin"])
    code_system = request.args.get("code_system")
    payer_type = request.args.get("payer_type")

    procedures = list(db.procedures.values())
    if code_system is not None:
        procedures = [p for p in procedures if p["code_system"] == code_system]
    procedure_count = len(procedures)

    rate_count = 0
    sums = {}
    counts = {}
    for r in db.rates.values():
        if r["superseded"]:
            continue
        procedure = db.procedures.get(r["procedure_id"])
        contract = db.contracts.get(r["contract_id"])
        if procedure is None or contract is None:
            continue
        if code_system is not None and procedure["code_system"] != code_system:
            continue
        if payer_type is not None and contract["payer_type"] != payer_type:
            continue
        rate_count += 1
        allowed = core.rate_allowed(r, procedure)
        cs = procedure["code_system"]
        sums[cs] = sums.get(cs, 0) + allowed
        counts[cs] = counts.get(cs, 0) + 1

    avg_by_cs = {cs: round_half_up(Decimal(sums[cs]) / Decimal(counts[cs])) for cs in sums}
    issued_estimate_count = sum(1 for e in db.estimates.values() if e["status"] == "ISSUED")

    data = {
        "procedure_count": procedure_count,
        "rate_count": rate_count,
        "avg_allowed_cents_by_code_system": avg_by_cs,
        "issued_estimate_count": issued_estimate_count,
    }
    return ok(data)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["Admin"])
    body = get_body()
    to_iso = req_datetime(body, "to_iso8601")
    db.clock = parse_iso(to_iso)
    return ok({"now": render_dt(db.clock)})
