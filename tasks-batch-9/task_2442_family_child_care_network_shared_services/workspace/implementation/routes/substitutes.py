"""PRD 3.6 substitute pool coordination, selection and coverage billing."""
from flask import Blueprint

import auth
import calculations as calc
import clock
import db
import response
import services
import validators as v
from errors import ApiError

bp = Blueprint("substitutes", __name__)

CREDENTIAL_LEVELS = ("NONE", "CDA", "CHILD_DEV_TEACHER")
COUNTY_TIERS = ("HIGH_NEED", "STANDARD")
POOL_STATUSES = ("AVAILABLE", "SUSPENDED")
REASONS = ("ILLNESS", "VACATION", "TRAINING")


def _assignment(assignment_id):
    return services.find_or_404(
        db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND", "substitute assignment"
    )


# --- pool membership -------------------------------------------------------

@bp.post("/fccn/substitutes")
def add_substitute():
    auth.require_auth(("NetworkAdmin",))
    body = v.get_body()
    v.reject_unversioned(body)
    full_name = v.req_str(body, "full_name")
    credential_level = v.req_enum(body, "credential_level", CREDENTIAL_LEVELS)
    clearance_expires_on = v.req_instant(body, "clearance_expires_on")
    hourly_rate_cents = v.req_int(body, "hourly_rate_cents", 1)
    service_county_tiers = v.req_enum_array(body, "service_county_tiers", COUNTY_TIERS)

    row = db.make_row(
        full_name=full_name,
        credential_level=credential_level,
        clearance_expires_on=clearance_expires_on,
        hourly_rate_cents=hourly_rate_cents,
        service_county_tiers=service_county_tiers,
        pool_status="AVAILABLE",
        assignment_count_completed=0,
    )
    services.register_new(row)
    db.substitutes[row["id"]] = row
    return response.created(row)


@bp.post("/fccn/substitutes/<substitute_id>/clearance")
def record_clearance(substitute_id):
    auth.require_auth(("NetworkAdmin",))
    substitute = services.substitute_or_404(substitute_id)
    body = v.get_body()
    v.reject_unversioned(body)
    clearance_expires_on = v.opt_instant(body, "clearance_expires_on")
    pool_status = v.opt_enum(body, "pool_status", POOL_STATUSES)

    if clearance_expires_on is not None:
        substitute["clearance_expires_on"] = clearance_expires_on
    if pool_status is not None:
        substitute["pool_status"] = pool_status
    services.touch(substitute)
    return response.ok(substitute)


# --- coverage requests and selection ---------------------------------------

def _offer(assignment, substitute):
    assignment["substitute_id"] = substitute["id"]
    assignment["staffing_status"] = "OFFERED"


def _run_selector(assignment, provider):
    """REQUESTED -> OFFERED with the winning candidate, or -> UNFILLED."""
    winner = calc.select_substitute(assignment, provider)
    if winner is None:
        assignment["substitute_id"] = None
        assignment["staffing_status"] = "UNFILLED"
    else:
        _offer(assignment, winner)


@bp.post("/fccn/substitute-assignments")
def request_coverage():
    actor = auth.require_auth(("Provider",))
    body = v.get_body()
    provider_id = v.req_str(body, "provider_id")
    auth.scope_provider(actor, provider_id)
    provider = services.provider_or_404(provider_id)

    requested_substitute = None
    if v.present(body, "requested_substitute_id"):
        requested_substitute = services.substitute_or_404(
            v.req_str(body, "requested_substitute_id")
        )

    start_at = v.req_instant(body, "start_at")
    end_at = v.req_instant(body, "end_at")
    reason = v.req_enum(body, "reason", REASONS)
    min_credential_level = v.opt_enum(body, "min_credential_level", CREDENTIAL_LEVELS, "NONE")
    v.reject_unversioned(body)
    if clock.parse_instant(end_at) <= clock.parse_instant(start_at):
        v.bad("'end_at' must be strictly later than 'start_at'.")

    services.check_posture(provider, restricted_blocks=False)

    row = db.make_row(
        provider_id=provider["id"],
        substitute_id=None,
        start_at=start_at,
        end_at=end_at,
        reason=reason,
        min_credential_level=min_credential_level,
        staffing_status="REQUESTED",
        billing_status="UNBILLED",
        declined_substitute_ids=[],
        billable_hours=0,
        pre_fee_subtotal_cents=0,
        network_admin_fee_cents=0,
        total_cost_cents=0,
    )
    services.register_new(row)

    if requested_substitute is not None:
        # ladder 12 then 13: clearance, then the buffered interval conflict.
        if not calc.clearance_ok(requested_substitute, row):
            raise ApiError(
                "ERR_SUBSTITUTE_CLEARANCE_EXPIRED",
                "The requested substitute's clearance does not outlast the coverage window.",
            )
        if calc.has_interval_conflict(row, requested_substitute["id"]):
            raise ApiError(
                "ERR_SUBSTITUTE_INTERVAL_CONFLICT",
                "The requested substitute already covers an overlapping window.",
            )
        if calc.eligible(requested_substitute, row, provider):
            _offer(row, requested_substitute)
        else:
            row["staffing_status"] = "UNFILLED"
    else:
        _run_selector(row, provider)

    db.assignments[row["id"]] = row
    return response.created(row)


@bp.post("/fccn/substitute-assignments/<assignment_id>/accept")
def accept_assignment(assignment_id):
    actor = auth.require_auth(("Substitute",))
    assignment = _assignment(assignment_id)
    auth.scope_substitute(actor, assignment["substitute_id"])

    if assignment["staffing_status"] != "OFFERED":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE", "Only an OFFERED assignment may be accepted.")
    substitute = db.substitutes[assignment["substitute_id"]]
    if substitute["pool_status"] != "AVAILABLE":
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "The substitute is no longer AVAILABLE in the pool.",
        )
    if not calc.clearance_ok(substitute, assignment):
        raise ApiError(
            "ERR_SUBSTITUTE_CLEARANCE_EXPIRED",
            "The substitute's clearance no longer outlasts the coverage window.",
        )

    assignment["staffing_status"] = "CONFIRMED"
    services.touch(assignment)
    return response.ok(assignment)


@bp.post("/fccn/substitute-assignments/<assignment_id>/decline")
def decline_assignment(assignment_id):
    actor = auth.require_auth(("Substitute",))
    assignment = _assignment(assignment_id)
    auth.scope_substitute(actor, assignment["substitute_id"])

    if assignment["staffing_status"] != "OFFERED":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE", "Only an OFFERED assignment may be declined.")

    declining_id = assignment["substitute_id"]
    if declining_id not in assignment["declined_substitute_ids"]:
        assignment["declined_substitute_ids"].append(declining_id)
    assignment["substitute_id"] = None
    assignment["staffing_status"] = "REQUESTED"
    _run_selector(assignment, db.providers[assignment["provider_id"]])
    services.touch(assignment)
    return response.ok(assignment)


@bp.post("/fccn/substitute-assignments/<assignment_id>/complete")
def complete_assignment(assignment_id):
    actor = auth.require_auth(("Provider",))
    assignment = _assignment(assignment_id)
    auth.scope_provider(actor, assignment["provider_id"])

    if assignment["staffing_status"] != "CONFIRMED":
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE", "Only a CONFIRMED assignment may be completed."
        )
    if clock.parse_instant(assignment["end_at"]) > clock.now():
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "Coverage cannot be billed before the window has finished.",
        )

    substitute = db.substitutes[assignment["substitute_id"]]
    cost = calc.assignment_cost(assignment, substitute)
    assignment.update(cost)
    assignment["staffing_status"] = "COMPLETED"
    assignment["billing_status"] = "ACCRUED"
    services.touch(assignment)

    substitute["assignment_count_completed"] += 1
    services.touch(substitute)
    services.recompute_revenue(db.providers[assignment["provider_id"]])
    return response.ok(assignment)


@bp.post("/fccn/substitute-assignments/<assignment_id>/invoice")
def invoice_assignment(assignment_id):
    auth.require_auth(("FiscalOfficer",))
    assignment = _assignment(assignment_id)
    if assignment["billing_status"] != "ACCRUED":
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE", "Only ACCRUED coverage may be invoiced."
        )
    assignment["billing_status"] = "INVOICED"
    services.touch(assignment)
    return response.ok(assignment)


# --- reads -----------------------------------------------------------------

@bp.get("/fccn/substitutes/<substitute_id>")
def read_substitute(substitute_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Substitute"))
    auth.scope_substitute(actor, substitute_id)
    return response.ok(services.substitute_or_404(substitute_id))


@bp.get("/fccn/substitutes/<substitute_id>/assignments")
def list_substitute_assignments(substitute_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Substitute"))
    auth.scope_substitute(actor, substitute_id)
    substitute = services.substitute_or_404(substitute_id)
    limit, offset = v.pagination()
    rows = v.filtered(
        [a for a in db.assignments.values() if a["substitute_id"] == substitute["id"]],
        staffing_status="staffing_status",
        billing_status="billing_status",
    )
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/fccn/substitute-assignments/<assignment_id>")
def read_assignment(assignment_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider", "Substitute"))
    assignment = _assignment(assignment_id)
    auth.scope_provider(actor, assignment["provider_id"])
    auth.scope_substitute(actor, assignment["substitute_id"])
    return response.ok(assignment)
