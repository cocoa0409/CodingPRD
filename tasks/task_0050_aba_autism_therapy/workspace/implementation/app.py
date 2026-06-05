import os
from flask import Flask, request

import errors
from errors import ApiError, err
from response import success, error_response
from db import db, new_common, touch
from middleware import authenticate, require_role
from pagination import parse_pagination, paginate
import util
from util import parse_iso, parse_date
import serialize
import services
import calculations as calc

app = Flask(__name__)


# ===========================================================================
# Error handling
# ===========================================================================

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_VALIDATION", f"Unexpected error: {e}", 422)


def get_json():
    """Parse the request JSON body, defaulting to {} for empty bodies on action
    endpoints. Malformed JSON -> ERR_VALIDATION (PRD §2.4)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err(errors.ERR_VALIDATION, "Malformed JSON body.")
    if body is None:
        return {}
    return body


# ===========================================================================
# Existence helpers (ERR_NOT_FOUND), clock helper
# ===========================================================================

def fetch_or_404(collection, rid, label="Resource"):
    rec = collection.get(rid)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, f"{label} not found.")
    return rec


def fetch_body_fk(collection, value, label):
    rec = collection.get(value)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, f"Referenced {label} does not exist.")
    return rec


def server_now():
    """The server's current instant for time-gated checks (PRD §3.4). When the
    test clock has been set, use it; otherwise fall back to wall-clock UTC."""
    if db.current_clock is not None:
        return parse_iso(db.current_clock)
    from response import now_dt
    return now_dt()


def server_today():
    return server_now().date()


# ===========================================================================
# Generic list helper
# ===========================================================================

def do_list(collection, serializer, filters=None):
    limit, offset = parse_pagination()
    items = list(collection.values())
    if filters:
        for field, value in filters.items():
            if value is not None:
                items = [r for r in items if r.get(field) == value]
    page, meta = paginate(items, limit, offset)
    return success([serializer(r) for r in page], status=200, pagination=meta)


# ===========================================================================
# Test clock
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    body = util.require_body(get_json())
    to_iso = util.req_datetime(body, "to_iso8601")
    require_role(role, {"BillingSpecialist", "IntakeCoordinator"})
    db.current_clock = to_iso
    return success({}, status=200)


# ===========================================================================
# Payer
# ===========================================================================

@app.route("/payers", methods=["POST"])
def create_payer():
    _, role = authenticate()
    body = util.require_body(get_json())
    name = util.req_str(body, "name", 1, 500)
    allowed_rate = util.req_int(body, "allowed_rate_cents", 0)
    coinsurance = util.req_number(body, "coinsurance_pct", 0, 1)
    supervision_ratio = util.req_number(body, "supervision_ratio_pct", 0, 1, strict_min=True)
    require_role(role, {"IntakeCoordinator", "BillingSpecialist"})

    rec = new_common()
    rec.update({
        "name": name,
        "allowed_rate_cents": allowed_rate,
        "coinsurance_pct": coinsurance,
        "supervision_ratio_pct": supervision_ratio,
    })
    db.payers[rec["id"]] = rec
    return success(serialize.payer_out(rec), status=201)


@app.route("/payers/<pid>", methods=["GET"])
def get_payer(pid):
    _, role = authenticate()
    require_role(role, {"IntakeCoordinator", "BillingSpecialist", "BCBA"})
    rec = fetch_or_404(db.payers, pid, "Payer")
    return success(serialize.payer_out(rec), status=200)


# ===========================================================================
# Client
# ===========================================================================

@app.route("/clients", methods=["POST"])
def create_client():
    _, role = authenticate()
    body = util.require_body(get_json())
    full_name = util.req_str(body, "full_name", 1, 500)
    dob = util.req_iso_date(body, "date_of_birth")
    caregiver_user_id = util.req_str(body, "caregiver_user_id", 1, 500)
    insurance_payer_id = util.req_fk(body, "insurance_payer_id")
    require_role(role, {"IntakeCoordinator"})
    fetch_body_fk(db.payers, insurance_payer_id, "payer")

    rec = new_common()
    rec.update({
        "full_name": full_name,
        "date_of_birth": dob,
        "caregiver_user_id": caregiver_user_id,
        "insurance_payer_id": insurance_payer_id,
        "status": "INTAKE",
    })
    db.clients[rec["id"]] = rec
    return success(serialize.client_out(rec), status=201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    _, role = authenticate()
    require_role(role, {"IntakeCoordinator", "BCBA", "BillingSpecialist", "Caregiver"})
    rec = fetch_or_404(db.clients, cid, "Client")
    return success(serialize.client_out(rec), status=200)


@app.route("/clients", methods=["GET"])
def list_clients():
    _, role = authenticate()
    require_role(role, {"IntakeCoordinator", "BCBA", "BillingSpecialist"})
    return do_list(db.clients, serialize.client_out, {
        "insurance_payer_id": request.args.get("insurance_payer_id"),
    })


@app.route("/clients/<cid>/discharge", methods=["POST"])
def discharge_client(cid):
    _, role = authenticate()
    require_role(role, {"IntakeCoordinator"})
    rec = fetch_or_404(db.clients, cid, "Client")
    rec["status"] = "DISCHARGED"
    touch(rec)
    return success(serialize.client_out(rec), status=200)


# ===========================================================================
# Provider
# ===========================================================================

@app.route("/providers", methods=["POST"])
def create_provider():
    _, role = authenticate()
    body = util.require_body(get_json())
    full_name = util.req_str(body, "full_name", 1, 500)
    credential = util.req_enum(body, "credential", {"BCBA", "RBT"})
    npi = util.req_str(body, "npi", 1, 500)
    supervising_bcba_id = None
    if body.get("supervising_bcba_id") is not None:
        supervising_bcba_id = util.req_fk(body, "supervising_bcba_id")
    require_role(role, {"IntakeCoordinator"})
    if supervising_bcba_id is not None:
        fetch_body_fk(db.providers, supervising_bcba_id, "supervising BCBA")

    rec = new_common()
    rec.update({
        "full_name": full_name,
        "credential": credential,
        "npi": npi,
        "supervising_bcba_id": supervising_bcba_id,
        "status": "ACTIVE",
    })
    db.providers[rec["id"]] = rec
    return success(serialize.provider_out(rec), status=201)


@app.route("/providers/<pid>", methods=["GET"])
def get_provider(pid):
    _, role = authenticate()
    require_role(role, {"IntakeCoordinator", "BCBA", "RBT", "BillingSpecialist"})
    rec = fetch_or_404(db.providers, pid, "Provider")
    return success(serialize.provider_out(rec), status=200)


@app.route("/providers/<pid>/deactivate", methods=["POST"])
def deactivate_provider(pid):
    _, role = authenticate()
    require_role(role, {"IntakeCoordinator"})
    rec = fetch_or_404(db.providers, pid, "Provider")
    rec["status"] = "INACTIVE"
    touch(rec)
    return success(serialize.provider_out(rec), status=200)


@app.route("/providers", methods=["GET"])
def list_providers():
    _, role = authenticate()
    require_role(role, {"IntakeCoordinator", "BCBA", "BillingSpecialist"})
    return do_list(db.providers, serialize.provider_out, {
        "supervising_bcba_id": request.args.get("supervising_bcba_id"),
    })


# ===========================================================================
# DiagnosticEvaluation
# ===========================================================================

@app.route("/diagnostic-evaluations", methods=["POST"])
def create_evaluation():
    _, role = authenticate()
    body = util.require_body(get_json())
    client_id = util.req_fk(body, "client_id")
    evaluator_bcba_id = util.req_fk(body, "evaluator_bcba_id")
    assessment_score = util.req_int(body, "assessment_score", 0, 180)
    require_role(role, {"BCBA"})
    # existence left-to-right: client_id then evaluator_bcba_id.
    fetch_body_fk(db.clients, client_id, "client")
    fetch_body_fk(db.providers, evaluator_bcba_id, "provider")

    rec = new_common()
    rec.update({
        "client_id": client_id,
        "evaluator_bcba_id": evaluator_bcba_id,
        "assessment_score": assessment_score,
        "severity_level": None,
        "recommended_weekly_units": None,
        "status": "DRAFT",
    })
    db.diagnostic_evaluations[rec["id"]] = rec
    return success(serialize.evaluation_out(rec), status=201)


@app.route("/diagnostic-evaluations/<eid>", methods=["GET"])
def get_evaluation(eid):
    _, role = authenticate()
    require_role(role, {"BCBA", "IntakeCoordinator"})
    rec = fetch_or_404(db.diagnostic_evaluations, eid, "DiagnosticEvaluation")
    return success(serialize.evaluation_out(rec), status=200)


@app.route("/diagnostic-evaluations", methods=["GET"])
def list_evaluations():
    _, role = authenticate()
    require_role(role, {"BCBA", "IntakeCoordinator"})
    return do_list(db.diagnostic_evaluations, serialize.evaluation_out, {
        "client_id": request.args.get("client_id"),
        "evaluator_bcba_id": request.args.get("evaluator_bcba_id"),
    })


@app.route("/diagnostic-evaluations/<eid>/submit", methods=["POST"])
def submit_evaluation(eid):
    user_id, role = authenticate()
    require_role(role, {"BCBA"})
    rec = fetch_or_404(db.diagnostic_evaluations, eid, "DiagnosticEvaluation")
    # resource owner (priority 4): acting provider must be the evaluator.
    if user_id != rec["evaluator_bcba_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Acting provider is not the evaluator.")
    # state (priority 5)
    if rec["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Evaluation is not in DRAFT.")
    # side effect: compute severity_level + recommended_weekly_units.
    severity, weekly = calc.diagnostic_severity(rec["assessment_score"])
    rec["severity_level"] = severity
    rec["recommended_weekly_units"] = weekly
    rec["status"] = "SUBMITTED"
    touch(rec)
    return success(serialize.evaluation_out(rec), status=200)


@app.route("/diagnostic-evaluations/<eid>/review", methods=["POST"])
def review_evaluation(eid):
    _, role = authenticate()
    body = util.require_body(get_json())
    decision = util.req_enum(body, "decision", {"FINALIZE", "REJECT"})
    require_role(role, {"IntakeCoordinator"})
    rec = fetch_or_404(db.diagnostic_evaluations, eid, "DiagnosticEvaluation")
    # state (priority 5)
    if rec["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "Evaluation is not SUBMITTED.")
    rec["status"] = "FINALIZED" if decision == "FINALIZE" else "REJECTED"
    touch(rec)
    return success(serialize.evaluation_out(rec), status=200)


# ===========================================================================
# TreatmentPlan
# ===========================================================================

@app.route("/treatment-plans", methods=["POST"])
def create_plan():
    _, role = authenticate()
    body = util.require_body(get_json())
    client_id = util.req_fk(body, "client_id")
    evaluation_id = util.req_fk(body, "evaluation_id")
    author_bcba_id = util.req_fk(body, "author_bcba_id")
    requested_direct = util.req_int(body, "requested_direct_units", 1)
    requested_supervision = util.req_int(body, "requested_supervision_units", 0)
    requested_parent = util.req_int(body, "requested_parent_training_units", 0)
    require_role(role, {"BCBA"})
    # existence left-to-right.
    fetch_body_fk(db.clients, client_id, "client")
    fetch_body_fk(db.diagnostic_evaluations, evaluation_id, "evaluation")
    fetch_body_fk(db.providers, author_bcba_id, "provider")

    rec = new_common()
    rec.update({
        "client_id": client_id,
        "evaluation_id": evaluation_id,
        "author_bcba_id": author_bcba_id,
        "requested_direct_units": requested_direct,
        "requested_supervision_units": requested_supervision,
        "requested_parent_training_units": requested_parent,
        "status": "DRAFT",
    })
    db.treatment_plans[rec["id"]] = rec
    return success(serialize.plan_out(rec), status=201)


@app.route("/treatment-plans/<pid>", methods=["GET"])
def get_plan(pid):
    _, role = authenticate()
    require_role(role, {"BCBA", "IntakeCoordinator", "BillingSpecialist"})
    rec = fetch_or_404(db.treatment_plans, pid, "TreatmentPlan")
    return success(serialize.plan_out(rec), status=200)


@app.route("/treatment-plans", methods=["GET"])
def list_plans():
    _, role = authenticate()
    require_role(role, {"BCBA", "IntakeCoordinator", "BillingSpecialist"})
    return do_list(db.treatment_plans, serialize.plan_out, {
        "client_id": request.args.get("client_id"),
        "evaluation_id": request.args.get("evaluation_id"),
        "author_bcba_id": request.args.get("author_bcba_id"),
    })


@app.route("/treatment-plans/<pid>/submit", methods=["POST"])
def submit_plan(pid):
    user_id, role = authenticate()
    require_role(role, {"BCBA"})
    rec = fetch_or_404(db.treatment_plans, pid, "TreatmentPlan")
    # resource owner (priority 4): acting provider must be the author.
    if user_id != rec["author_bcba_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Acting provider is not the author.")
    # state (priority 5): submit allowed from DRAFT or REVISION_REQUESTED.
    if rec["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise err(errors.ERR_INVALID_STATE, "Plan is not DRAFT or REVISION_REQUESTED.")
    # business referential (priority 6): backing evaluation must be FINALIZED.
    evaluation = db.diagnostic_evaluations.get(rec["evaluation_id"])
    if evaluation is None or evaluation["status"] != "FINALIZED":
        raise err(errors.ERR_EVALUATION_NOT_FINALIZED, "Backing evaluation is not FINALIZED.")
    rec["status"] = "SUBMITTED"
    touch(rec)
    return success(serialize.plan_out(rec), status=200)


@app.route("/treatment-plans/<pid>/review", methods=["POST"])
def review_plan(pid):
    _, role = authenticate()
    body = util.require_body(get_json())
    decision = util.req_enum(body, "decision", {"APPROVE", "REQUEST_REVISION"})
    require_role(role, {"IntakeCoordinator"})
    rec = fetch_or_404(db.treatment_plans, pid, "TreatmentPlan")
    # state (priority 5)
    if rec["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "Plan is not SUBMITTED.")

    if decision == "REQUEST_REVISION":
        rec["status"] = "REVISION_REQUESTED"
        touch(rec)
        return success(serialize.plan_out(rec), status=200)

    # APPROVE side effects (PRD §3.3):
    #  - retire any prior APPROVED plan for the same client (this new one
    #    supersedes it)
    #  - bubble the client INTAKE -> ACTIVE
    for other in db.treatment_plans.values():
        if other["id"] == rec["id"]:
            continue
        if other["client_id"] == rec["client_id"] and other["status"] == "APPROVED":
            other["status"] = "RETIRED"
            touch(other)
    rec["status"] = "APPROVED"
    touch(rec)
    client = db.clients.get(rec["client_id"])
    if client is not None and client["status"] == "INTAKE":
        client["status"] = "ACTIVE"
        touch(client)
    return success(serialize.plan_out(rec), status=200)


# ===========================================================================
# Authorization
# ===========================================================================

@app.route("/authorizations", methods=["POST"])
def create_authorization():
    _, role = authenticate()
    body = util.require_body(get_json())
    treatment_plan_id = util.req_fk(body, "treatment_plan_id")
    payer_id = util.req_fk(body, "payer_id")
    authorized_direct = util.req_int(body, "authorized_direct_units", 0)
    authorized_supervision = util.req_int(body, "authorized_supervision_units", 0)
    authorized_parent = util.req_int(body, "authorized_parent_training_units", 0)
    period_start = util.req_iso_date(body, "period_start")
    period_end = util.req_iso_date(body, "period_end")
    require_role(role, {"BillingSpecialist"})
    # existence left-to-right.
    fetch_body_fk(db.treatment_plans, treatment_plan_id, "treatment plan")
    fetch_body_fk(db.payers, payer_id, "payer")

    rec = new_common()
    rec.update({
        "treatment_plan_id": treatment_plan_id,
        "payer_id": payer_id,
        "authorized_direct_units": authorized_direct,
        "authorized_supervision_units": authorized_supervision,
        "authorized_parent_training_units": authorized_parent,
        "period_start": period_start,
        "period_end": period_end,
        "reserved_direct_units": 0,
        "delivered_direct_units": 0,
        "reserved_supervision_units": 0,
        "delivered_supervision_units": 0,
        "reserved_parent_training_units": 0,
        "delivered_parent_training_units": 0,
        "remaining_direct_units": authorized_direct,
        "supervision_status": "COMPLIANT",
        "status": "ACTIVE",
        "superseded_by_id": None,
    })
    db.authorizations[rec["id"]] = rec
    return success(serialize.authorization_out(rec), status=201)


@app.route("/authorizations/<aid>", methods=["GET"])
def get_authorization(aid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist", "BCBA", "IntakeCoordinator"})
    rec = fetch_or_404(db.authorizations, aid, "Authorization")
    return success(serialize.authorization_out(rec), status=200)


@app.route("/authorizations", methods=["GET"])
def list_authorizations():
    _, role = authenticate()
    require_role(role, {"BillingSpecialist", "BCBA", "IntakeCoordinator"})
    return do_list(db.authorizations, serialize.authorization_out, {
        "treatment_plan_id": request.args.get("treatment_plan_id"),
        "payer_id": request.args.get("payer_id"),
        "superseded_by_id": request.args.get("superseded_by_id"),
    })


@app.route("/authorizations/<aid>/renew", methods=["POST"])
def renew_authorization(aid):
    _, role = authenticate()
    body = util.require_body(get_json())
    expected_version = util.req_int(body, "expected_authorization_version")
    authorized_direct = util.req_int(body, "authorized_direct_units", 0)
    authorized_supervision = util.req_int(body, "authorized_supervision_units", 0)
    authorized_parent = util.req_int(body, "authorized_parent_training_units", 0)
    period_start = util.req_iso_date(body, "period_start")
    period_end = util.req_iso_date(body, "period_end")
    require_role(role, {"BillingSpecialist"})
    rec = fetch_or_404(db.authorizations, aid, "Authorization")
    # state (priority 5): renew defined only from ACTIVE.
    if rec["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Authorization is not ACTIVE.")
    # OCC (ERR_STALE_VERSION / 412)
    if expected_version != rec["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale authorization version.")

    # Create the successor. Direct pool carries forward the predecessor's
    # remaining direct units; supervision/parent pools come from the body
    # verbatim (PRD §3.5).
    successor = new_common()
    successor.update({
        "treatment_plan_id": rec["treatment_plan_id"],
        "payer_id": rec["payer_id"],
        "authorized_direct_units": authorized_direct + rec["remaining_direct_units"],
        "authorized_supervision_units": authorized_supervision,
        "authorized_parent_training_units": authorized_parent,
        "period_start": period_start,
        "period_end": period_end,
        "reserved_direct_units": 0,
        "delivered_direct_units": 0,
        "reserved_supervision_units": 0,
        "delivered_supervision_units": 0,
        "reserved_parent_training_units": 0,
        "delivered_parent_training_units": 0,
        "remaining_direct_units": authorized_direct + rec["remaining_direct_units"],
        "supervision_status": "COMPLIANT",
        "status": "ACTIVE",
        "superseded_by_id": None,
    })
    db.authorizations[successor["id"]] = successor

    rec["superseded_by_id"] = successor["id"]
    rec["status"] = "RENEWED"
    touch(rec)  # increments predecessor.version by 1
    return success(serialize.authorization_out(successor), status=201)


@app.route("/authorizations/<aid>/close", methods=["POST"])
def close_authorization(aid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    rec = fetch_or_404(db.authorizations, aid, "Authorization")
    # state (priority 5): close defined only from ACTIVE.
    if rec["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Authorization is not ACTIVE.")
    # business temporal (priority 16): clock date strictly after period_end.
    if not (server_today() > parse_date(rec["period_end"])):
        raise err(errors.ERR_AUTHORIZATION_NOT_EXPIRABLE,
                  "Authorization period has not yet elapsed.")
    # cascade: cancel still-SCHEDULED sessions, freeing their reservations.
    for s in services.sessions_for_authorization(rec["id"]):
        if s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)
    rec["status"] = "EXPIRED"
    # recompute pools/supervision after cascade (does NOT re-flip EXPIRED).
    services._recompute_pools(rec)
    services._recompute_supervision_status(rec)
    touch(rec)
    return success(serialize.authorization_out(rec), status=200)


# ===========================================================================
# TherapySession
# ===========================================================================

def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open intervals [start, end) overlap iff a_start < b_end and
    b_start < a_end (touching endpoints do not overlap) (PRD §3.6)."""
    return a_start < b_end and b_start < a_end


@app.route("/therapy-sessions", methods=["POST"])
def create_session():
    from datetime import timedelta
    _, role = authenticate()
    body = util.require_body(get_json())
    authorization_id = util.req_fk(body, "authorization_id")
    provider_id = util.req_fk(body, "provider_id")
    service_line = util.req_enum(
        body, "service_line",
        {"DIRECT_THERAPY", "SUPERVISION", "PARENT_TRAINING"})
    scheduled_start = util.req_datetime(body, "scheduled_start")
    scheduled_end = util.req_datetime(body, "scheduled_end")
    scheduled_units = util.req_int(body, "scheduled_units", 1)
    require_role(role, {"RBT", "BCBA"})
    # existence left-to-right: authorization then provider.
    auth = fetch_body_fk(db.authorizations, authorization_id, "authorization")
    provider = fetch_body_fk(db.providers, provider_id, "provider")

    # credential mismatch (priority 7): DIRECT_THERAPY->RBT, SUP/PARENT->BCBA.
    required_credential = "RBT" if service_line == "DIRECT_THERAPY" else "BCBA"
    if provider["credential"] != required_credential:
        raise err(errors.ERR_CREDENTIAL_MISMATCH,
                  "Provider credential does not match service_line.")

    start_dt = parse_iso(scheduled_start)
    end_dt = parse_iso(scheduled_end)

    # outside auth window (priority 8): date(scheduled_start) within [start,end].
    sess_date = start_dt.date()
    if not (parse_date(auth["period_start"]) <= sess_date <= parse_date(auth["period_end"])):
        raise err(errors.ERR_OUTSIDE_AUTH_WINDOW,
                  "Session date is outside the authorization window.")

    # provider double-booked (priority 9): overlap with provider's
    # SCHEDULED/DELIVERED session interval (half-open).
    for s in db.therapy_sessions.values():
        if s["provider_id"] != provider_id:
            continue
        if s["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        if _intervals_overlap(start_dt, end_dt,
                              parse_iso(s["scheduled_start"]),
                              parse_iso(s["scheduled_end"])):
            raise err(errors.ERR_PROVIDER_DOUBLE_BOOKED,
                      "Provider already has an overlapping session.")

    # client buffer conflict (priority 10): same client (via authorization's
    # treatment plan) within 15 minutes of the new interval.
    plan = db.treatment_plans.get(auth["treatment_plan_id"])
    client_id = plan["client_id"] if plan else None
    buffer = timedelta(minutes=15)
    if client_id is not None:
        for s in db.therapy_sessions.values():
            if s["status"] not in ("SCHEDULED", "DELIVERED"):
                continue
            s_auth = db.authorizations.get(s["authorization_id"])
            s_plan = db.treatment_plans.get(s_auth["treatment_plan_id"]) if s_auth else None
            s_client = s_plan["client_id"] if s_plan else None
            if s_client != client_id:
                continue
            if _intervals_overlap(start_dt - buffer, end_dt + buffer,
                                  parse_iso(s["scheduled_start"]),
                                  parse_iso(s["scheduled_end"])):
                raise err(errors.ERR_CLIENT_BUFFER_CONFLICT,
                          "Client has a session within the 15-minute buffer.")

    # units exceeded (priority 12): reserved+delivered+new must not exceed the
    # authorized pool for this service line.
    key = services.SERVICE_LINE_TO_KEY[service_line]
    authorized = auth[f"authorized_{key}_units"]
    reserved = auth[f"reserved_{key}_units"]
    delivered = auth[f"delivered_{key}_units"]
    if reserved + delivered + scheduled_units > authorized:
        raise err(errors.ERR_UNITS_EXCEEDED,
                  "Scheduling would exceed the authorized unit pool.")

    rec = new_common()
    rec.update({
        "authorization_id": authorization_id,
        "provider_id": provider_id,
        "service_line": service_line,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "scheduled_units": scheduled_units,
        "delivered_units": 0,
        "status": "SCHEDULED",
    })
    db.therapy_sessions[rec["id"]] = rec
    services.recompute_authorization(auth)
    return success(serialize.session_out(rec), status=201)


@app.route("/therapy-sessions/<sid>", methods=["GET"])
def get_session(sid):
    _, role = authenticate()
    require_role(role, {"RBT", "BCBA", "BillingSpecialist"})
    rec = fetch_or_404(db.therapy_sessions, sid, "TherapySession")
    return success(serialize.session_out(rec), status=200)


@app.route("/therapy-sessions", methods=["GET"])
def list_sessions():
    _, role = authenticate()
    require_role(role, {"RBT", "BCBA", "BillingSpecialist"})
    return do_list(db.therapy_sessions, serialize.session_out, {
        "authorization_id": request.args.get("authorization_id"),
        "provider_id": request.args.get("provider_id"),
    })


@app.route("/therapy-sessions/<sid>/deliver", methods=["POST"])
def deliver_session(sid):
    user_id, role = authenticate()
    body = util.require_body(get_json())
    delivered_units = util.req_int(body, "delivered_units")
    require_role(role, {"BCBA", "RBT"})
    rec = fetch_or_404(db.therapy_sessions, sid, "TherapySession")
    # state (priority 5)
    if rec["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Session is not SCHEDULED.")
    auth = db.authorizations.get(rec["authorization_id"])
    # active-authorization (priority 10.5): owning auth must be ACTIVE/EXHAUSTED.
    if auth is None or auth["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise err(errors.ERR_AUTHORIZATION_NOT_ACTIVE,
                  "Owning authorization is not ACTIVE or EXHAUSTED.")
    # delivered-units validity (priority 11): 0 < delivered <= scheduled.
    if not (0 < delivered_units <= rec["scheduled_units"]):
        raise err(errors.ERR_DELIVERED_UNITS_INVALID,
                  "delivered_units must be in (0, scheduled_units].")
    # supervision-line credential (priority 7): acting provider must be BCBA.
    if rec["service_line"] == "SUPERVISION":
        provider = db.providers.get(rec["provider_id"])
        if provider is None or provider["credential"] != "BCBA":
            raise err(errors.ERR_CREDENTIAL_MISMATCH,
                      "Supervision must be delivered by a BCBA.")

    rec["delivered_units"] = delivered_units
    rec["status"] = "DELIVERED"
    touch(rec)
    services.recompute_authorization(auth)
    return success(serialize.session_out(rec), status=200)


@app.route("/therapy-sessions/<sid>/no-show", methods=["POST"])
def no_show_session(sid):
    _, role = authenticate()
    require_role(role, {"RBT", "BCBA"})
    rec = fetch_or_404(db.therapy_sessions, sid, "TherapySession")
    if rec["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Session is not SCHEDULED.")
    rec["status"] = "NO_SHOW"
    touch(rec)
    auth = db.authorizations.get(rec["authorization_id"])
    if auth is not None:
        services.recompute_authorization(auth)
    return success(serialize.session_out(rec), status=200)


@app.route("/therapy-sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    _, role = authenticate()
    require_role(role, {"RBT", "BCBA"})
    rec = fetch_or_404(db.therapy_sessions, sid, "TherapySession")
    if rec["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Session is not SCHEDULED.")
    rec["status"] = "CANCELLED"
    touch(rec)
    auth = db.authorizations.get(rec["authorization_id"])
    if auth is not None:
        services.recompute_authorization(auth)
    return success(serialize.session_out(rec), status=200)


# ===========================================================================
# Claim
# ===========================================================================

def _live_claim_exists(session_id, exclude_id=None):
    """True if any SUBMITTED or PAID claim exists for the session (PRD §3.9)."""
    for c in db.claims.values():
        if c["id"] == exclude_id:
            continue
        if c["session_id"] == session_id and c["status"] in ("SUBMITTED", "PAID"):
            return True
    return False


@app.route("/claims", methods=["POST"])
def create_claim():
    _, role = authenticate()
    body = util.require_body(get_json())
    session_id = util.req_fk(body, "session_id")
    require_role(role, {"BillingSpecialist"})
    session = fetch_body_fk(db.therapy_sessions, session_id, "session")

    # session must be DELIVERED (priority 15).
    if session["status"] != "DELIVERED":
        raise err(errors.ERR_SESSION_NOT_DELIVERED,
                  "Claim can only be created for a DELIVERED session.")
    # duplicate claim (priority 14): no live SUBMITTED/PAID claim for session.
    if _live_claim_exists(session_id):
        raise err(errors.ERR_DUPLICATE_CLAIM,
                  "A live claim already exists for this session.")

    auth = db.authorizations.get(session["authorization_id"])
    payer_id = auth["payer_id"] if auth else None
    provisional = calc.provisional_billed_cents(
        session["service_line"], session["scheduled_units"])

    rec = new_common()
    rec.update({
        "session_id": session_id,
        "payer_id": payer_id,
        "billed_cents": provisional,
        "allowed_cents": 0,
        "patient_responsibility_cents": 0,
        "payer_paid_cents": 0,
        "denial_reason": "NONE",
        "status": "DRAFT",
    })
    db.claims[rec["id"]] = rec
    return success(serialize.claim_out(rec), status=201)


@app.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist", "BCBA"})
    rec = fetch_or_404(db.claims, cid, "Claim")
    return success(serialize.claim_out(rec), status=200)


@app.route("/claims", methods=["GET"])
def list_claims():
    _, role = authenticate()
    require_role(role, {"BillingSpecialist", "BCBA"})
    return do_list(db.claims, serialize.claim_out, {
        "session_id": request.args.get("session_id"),
        "payer_id": request.args.get("payer_id"),
    })


@app.route("/claims/<cid>/submit", methods=["POST"])
def submit_claim(cid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    rec = fetch_or_404(db.claims, cid, "Claim")
    # state (priority 5)
    if rec["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Claim is not DRAFT.")
    # duplicate claim (priority 14): no OTHER live SUBMITTED/PAID claim.
    if _live_claim_exists(rec["session_id"], exclude_id=rec["id"]):
        raise err(errors.ERR_DUPLICATE_CLAIM,
                  "Another live claim already exists for this session.")
    # finalize billed_cents to delivered-unit basis.
    session = db.therapy_sessions.get(rec["session_id"])
    rec["billed_cents"] = calc.final_billed_cents(
        session["service_line"], session["delivered_units"])
    rec["status"] = "SUBMITTED"
    touch(rec)
    return success(serialize.claim_out(rec), status=200)


@app.route("/claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    _, role = authenticate()
    body = util.require_body(get_json())
    decision = util.req_enum(body, "decision", {"PAY", "DENY"})
    denial_reason = None
    if decision == "DENY":
        denial_reason = util.opt_enum(
            body, "denial_reason",
            {"NONE", "NOT_AUTHORIZED", "SUPERVISION_DEFICIENT", "DUPLICATE"},
            "NONE")
    require_role(role, {"BillingSpecialist"})
    rec = fetch_or_404(db.claims, cid, "Claim")
    # state (priority 5)
    if rec["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "Claim is not SUBMITTED.")

    session = db.therapy_sessions.get(rec["session_id"])
    auth = db.authorizations.get(session["authorization_id"]) if session else None

    if decision == "PAY":
        # supervision gate (priority 13): owning auth must be COMPLIANT.
        if auth is None or auth["supervision_status"] != "COMPLIANT":
            raise err(errors.ERR_SUPERVISION_DEFICIENT,
                      "Owning authorization supervision is DEFICIENT.")
        payer = db.payers.get(rec["payer_id"])
        allowed, patient, payer_paid = calc.remittance(
            session["delivered_units"],
            payer["allowed_rate_cents"],
            payer["coinsurance_pct"],
        )
        rec["allowed_cents"] = allowed
        rec["patient_responsibility_cents"] = patient
        rec["payer_paid_cents"] = payer_paid
        rec["status"] = "PAID"
        touch(rec)
        return success(serialize.claim_out(rec), status=200)

    # DENY: zero money, set denial_reason.
    rec["denial_reason"] = denial_reason
    rec["allowed_cents"] = 0
    rec["patient_responsibility_cents"] = 0
    rec["payer_paid_cents"] = 0
    rec["status"] = "DENIED"
    touch(rec)
    return success(serialize.claim_out(rec), status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    # Avoid a startup-blocking DNS timeout. Both Flask's app.run() banner
    # (get_interface_ip) and the stdlib HTTPServer.server_bind() (socket.getfqdn)
    # try to resolve this host's .local name when binding to 0.0.0.0. On a
    # machine whose hostname does not resolve, that lookup blocks ~5s on a DNS
    # timeout BEFORE the listener serves. socket.getfqdn is only used to populate
    # a cosmetic server_name, so short-circuit it to keep bind instant.
    import socket as _socket

    _socket.getfqdn = lambda name="": (name or "localhost")

    from werkzeug.serving import make_server

    httpd = make_server("0.0.0.0", port, app, threaded=True)
    httpd.serve_forever()
