"""Role requisition endpoints (PRD 3.1, 3.2)."""

from flask import Blueprint, request

import db
from db import (
    MAX_SCOPING_ROUNDS,
    REQUISITION_STATUSES,
    ROLE_TYPES,
    SCHEDULE_PATTERNS,
    TERMINAL_REQUISITION,
    serialize,
    store,
    touch,
)
from errors import fail
from middleware import (
    AGENCY_PRINCIPAL,
    BILLING_ADMINISTRATOR,
    CANDIDATE,
    CLIENT,
    COMPLIANCE_OFFICER,
    PLACEMENT_CONSULTANT,
    VETTING_SPECIALIST,
    authenticate,
)
from response import created_response, list_response, object_response
from services import calc, domain
from validation import (
    apply_filters,
    body_of,
    check_enum,
    check_int,
    list_params,
    require_present,
    require_string,
)

bp = Blueprint("requisitions", __name__)

WITHDRAWABLE_STATUSES = ("DRAFT", "SCOPING", "SOURCING", "TRIALING")


@bp.post("/role-requisitions")
def create_requisition():
    user_id, _role = authenticate({PLACEMENT_CONSULTANT, CLIENT})
    body = body_of(request)

    require_present(body, "client_id", "role_type", "first_year_compensation_cents", "schedule_pattern")
    # scope_note carries no declared length bound.
    scope_note = require_string(body, "scope_note", 0, 100000, required=False)
    role_type = check_enum(body, "role_type", ROLE_TYPES)
    schedule_pattern = check_enum(body, "schedule_pattern", SCHEDULE_PATTERNS)
    first_year_compensation_cents = check_int(body, "first_year_compensation_cents", minimum=0)
    live_in_required = body.get("live_in_required")
    if live_in_required is None:
        live_in_required = False
    elif not isinstance(live_in_required, bool):
        fail("ERR_INVALID_REQUEST", "Field 'live_in_required' must be a boolean")

    client = domain.resolve("clients", body["client_id"])

    # The confidentiality agreement gate, then the suspension gate (PRD 2.11).
    domain.guard_nda_countersigned(client)
    domain.guard_client_not_suspended(client)

    row = {
        "client_id": client["id"],
        "role_type": role_type,
        "first_year_compensation_cents": first_year_compensation_cents,
        "live_in_required": live_in_required,
        "schedule_pattern": schedule_pattern,
        "scope_note": scope_note,
        "status": "DRAFT",
        "scoping_round": 0,
        "resolved_fee_schedule_id": None,
        "fee_percent_bps": None,
        "guarantee_window_days": None,
        "provisional_fee_cents": None,
        "active_trial_count": 0,
        "created_by_user_id": user_id,
    }
    db.stamp_new(row)
    store.requisitions[row["id"]] = row
    return created_response(serialize(row))


@bp.get("/role-requisitions/<requisition_id>")
def get_requisition(requisition_id):
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST,
        BILLING_ADMINISTRATOR, COMPLIANCE_OFFICER, CLIENT, CANDIDATE,
    })
    row = domain.resolve("requisitions", requisition_id)
    return object_response(serialize(row))


@bp.get("/role-requisitions")
def list_requisitions():
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST,
        BILLING_ADMINISTRATOR, COMPLIANCE_OFFICER, CLIENT,
    })
    limit, offset, filters = list_params(
        request,
        enum_filters={"role_type": ROLE_TYPES, "status": REQUISITION_STATUSES},
        plain_filters=("client_id", "resolved_fee_schedule_id"),
    )
    rows = apply_filters(list(store.requisitions.values()), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


@bp.post("/role-requisitions/<requisition_id>/scope")
def scope_requisition(requisition_id):
    authenticate({PLACEMENT_CONSULTANT, CLIENT})
    body = body_of(request)

    scope_note = require_string(body, "scope_note", 0, 100000)
    schedule_pattern = check_enum(body, "schedule_pattern", SCHEDULE_PATTERNS, required=False)
    first_year_compensation_cents = check_int(
        body, "first_year_compensation_cents", minimum=0, required=False
    )
    live_in_required = body.get("live_in_required")
    if live_in_required is not None and not isinstance(live_in_required, bool):
        fail("ERR_INVALID_REQUEST", "Field 'live_in_required' must be a boolean")

    requisition = domain.resolve("requisitions", requisition_id)
    domain.guard_terminal(requisition["status"], TERMINAL_REQUISITION)
    if requisition["status"] not in ("DRAFT", "SOURCING"):
        fail("ERR_INVALID_STATE_TRANSITION")
    is_rescope = requisition["status"] == "SOURCING"

    client = domain.resolve("clients", requisition["client_id"])
    domain.guard_nda_countersigned(client)
    domain.guard_client_not_suspended(client)

    if requisition["scoping_round"] >= MAX_SCOPING_ROUNDS:
        fail("ERR_SCOPING_ROUND_LIMIT")
    if is_rescope and requisition["active_trial_count"] != 0:
        fail("ERR_REQUISITION_HAS_ACTIVE_TRIALS")

    requisition["status"] = "SCOPING"
    requisition["scoping_round"] += 1
    requisition["scope_note"] = scope_note
    if first_year_compensation_cents is not None:
        requisition["first_year_compensation_cents"] = first_year_compensation_cents
    if live_in_required is not None:
        requisition["live_in_required"] = live_in_required
    if schedule_pattern is not None:
        requisition["schedule_pattern"] = schedule_pattern
    if is_rescope:
        # Re-scoping releases the commercial snapshot so the band is re-resolved.
        requisition["resolved_fee_schedule_id"] = None
        requisition["fee_percent_bps"] = None
        requisition["guarantee_window_days"] = None
        requisition["provisional_fee_cents"] = None
    touch(requisition)
    return object_response(serialize(requisition))


@bp.post("/role-requisitions/<requisition_id>/finalize-scope")
def finalize_scope(requisition_id):
    authenticate({PLACEMENT_CONSULTANT})
    body_of(request)

    requisition = domain.resolve("requisitions", requisition_id)
    domain.guard_terminal(requisition["status"], TERMINAL_REQUISITION)
    if requisition["status"] != "SCOPING":
        fail("ERR_REQUISITION_NOT_SCOPING")

    client = domain.resolve("clients", requisition["client_id"])
    domain.guard_client_not_suspended(client)

    schedule = calc.resolve_fee_schedule(
        requisition["role_type"], requisition["first_year_compensation_cents"]
    )
    if schedule is None:
        fail("ERR_NO_FEE_SCHEDULE_MATCH")

    requisition["status"] = "SOURCING"
    requisition["resolved_fee_schedule_id"] = schedule["id"]
    requisition["fee_percent_bps"] = schedule["fee_percent_bps"]
    requisition["guarantee_window_days"] = schedule["guarantee_window_days"]
    requisition["provisional_fee_cents"] = calc.provisional_fee_cents(
        requisition["first_year_compensation_cents"], schedule["fee_percent_bps"]
    )
    touch(requisition)
    return object_response(serialize(requisition))


@bp.post("/role-requisitions/<requisition_id>/withdraw")
def withdraw_requisition(requisition_id):
    authenticate({PLACEMENT_CONSULTANT, CLIENT})
    body_of(request)

    requisition = domain.resolve("requisitions", requisition_id)
    domain.guard_terminal(requisition["status"], TERMINAL_REQUISITION)
    if requisition["status"] not in WITHDRAWABLE_STATUSES:
        fail("ERR_INVALID_STATE_TRANSITION")

    requisition["status"] = "WITHDRAWN"
    touch(requisition)

    for trial in db.sort_rows(domain.children("trial_engagements", "requisition_id", requisition["id"])):
        if trial["status"] in db.ACTIVE_TRIAL_STATUSES:
            domain.cancel_trial(trial, "CLIENT_REQUEST")

    for term in db.sort_rows(domain.children("accommodation_terms", "requisition_id", requisition["id"])):
        if term["status"] in ("PROPOSED", "COUNTERED"):
            term["status"] = "REJECTED"
            touch(term)

    domain.recompute_active_trial_count(requisition)
    return object_response(serialize(requisition))
