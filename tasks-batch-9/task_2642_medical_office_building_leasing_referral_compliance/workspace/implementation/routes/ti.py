"""Tenant-improvement projects, their immutable line items and the two
independent engineering reviews (PRD Section 3.6)."""

from decimal import Decimal

from flask import Blueprint

import enums
import serializers as ser
import validators as v
from db import by_creation, db, stamp_new, touch
from errors import ApiError, bad_request
from lookups import get_lease, get_resource, get_suite, paged
from middleware import acting_user_id, endpoint, is_portal_user, require_tenant_scope
from response import object_response
from services import calc

bp = Blueprint("ti", __name__)

ZERO = Decimal("0.00")
IN_FLIGHT_STATUSES = ("DESIGN", "IN_REVIEW", "PERMITTED", "CONSTRUCTION", "ON_HOLD")
CANCELLABLE_STATUSES = ("DESIGN", "IN_REVIEW", "PERMITTED")


def _ti_state_guard(project, allowed):
    """Ladder rung 14."""
    if project["status"] not in allowed:
        raise ApiError(
            "ERR_INVALID_TI_STATE",
            "Project '%s' is in status %s; expected one of %s."
            % (project["id"], project["status"], ", ".join(allowed)),
        )


def _project_scope(project):
    if is_portal_user():
        lease = db.leases[project["lease_id"]]
        require_tenant_scope(lease["tenant_id"])


def _compensate_utility(project, suite):
    """Restores the electrical draw the utility branch took."""
    suite["power_amps_available"] += project["power_amps_drawn"]
    project["power_amps_drawn"] = 0


def _compensate_shielding(suite):
    """Reverses the shielding branch's certification of the suite."""
    suite["shielding_certified"] = False
    suite["lead_thickness_mm"] = None


# ------------------------------------------------------------------ project


@bp.post("/leases/<lease_id>/ti-projects")
@endpoint("LeasingAgent")
def create_ti_project(lease_id):
    body = v.json_body()
    suite_id = v.get_string(body, "suite_id")
    target_class = v.get_enum(body, "target_suite_class", enums.SUITE_CLASSES)
    # Optional in general — a zero is a perfectly good declaration for a
    # non-imaging build-out — and only IMAGING forces it strictly positive.
    lead_thickness = v.get_money(body, "lead_thickness_mm", required=False)
    power_requested = v.get_int(body, "power_amps_requested", minimum=0)
    medical_gas = v.get_bool(body, "medical_gas_requested", required=False, default=False)
    allowance = v.get_money(body, "authorized_allowance_total")
    share = v.get_share_pct(body, "landlord_share_pct")
    if target_class == "IMAGING" and (lead_thickness is None or lead_thickness <= 0):
        raise bad_request(
            "Field 'lead_thickness_mm' must be present and strictly positive for an "
            "IMAGING target suite class."
        )

    suite = get_suite(suite_id)
    lease = get_lease(lease_id)
    if suite["id"] != lease["suite_id"]:
        raise ApiError(
            "ERR_SUITE_NOT_FOUND",
            "Suite '%s' is not the suite demised by lease '%s'." % (suite_id, lease["id"]),
        )
    if lease["status"] in calc.CLOSED_LEASE_STATUSES:
        raise ApiError(
            "ERR_INVALID_LEASE_STATE",
            "Lease '%s' has reached %s." % (lease["id"], lease["status"]),
        )

    row = {
        "lease_id": lease["id"],
        "suite_id": suite["id"],
        "target_suite_class": target_class,
        "status": "DESIGN",
        "shielding_review_status": "NOT_SUBMITTED",
        "utility_review_status": "NOT_SUBMITTED",
        "lead_thickness_mm": lead_thickness,
        "power_amps_requested": power_requested,
        "power_amps_drawn": 0,
        "medical_gas_requested": medical_gas,
        "authorized_allowance_total": allowance,
        "landlord_share_pct": share,
        "landlord_committed_amount": ZERO,
        "tenant_committed_amount": ZERO,
        "allowance_remaining": allowance,
        "line_item_count": 0,
        "on_hold_from_status": None,
    }
    stamp_new(row)
    db.ti_projects[row["id"]] = row
    return object_response(ser.ti_project_out(row), 201)


@bp.get("/ti-projects/<project_id>")
@endpoint()
def read_ti_project(project_id):
    project = get_resource(db.ti_projects, project_id, "Tenant-improvement project")
    _project_scope(project)
    return object_response(ser.ti_project_out(project))


@bp.get("/ti-projects")
@endpoint()
def list_ti_projects():
    limit, offset = v.pagination()
    lease_id = v.query_string("lease_id")
    suite_id = v.query_string("suite_id")
    status = v.query_enum("status", enums.TI_STATUSES)

    rows = by_creation(list(db.ti_projects.values()))
    if is_portal_user():
        mine = acting_user_id()
        rows = [
            p for p in rows if db.leases[p["lease_id"]]["tenant_id"] == mine
        ]
    if lease_id is not None:
        rows = [p for p in rows if p["lease_id"] == lease_id]
    if suite_id is not None:
        rows = [p for p in rows if p["suite_id"] == suite_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return paged(rows, ser.ti_project_out, limit, offset)


# --------------------------------------------------------------- line items


@bp.post("/ti-projects/<project_id>/line-items")
@endpoint("LeasingAgent")
def append_line_item(project_id):
    body = v.json_body()
    expected = v.get_int(body, "expected_ti_project_version", minimum=0)
    description = v.get_string(body, "description")
    category = v.get_enum(body, "category", enums.TI_CATEGORIES)
    cost_amount = v.get_money(body, "cost_amount", allow_zero=False)
    override = v.get_share_pct(body, "landlord_share_pct_override", required=False)

    project = get_resource(db.ti_projects, project_id, "Tenant-improvement project")
    if expected != project["version"]:
        raise ApiError(
            "ERR_STALE_TI_PROJECT_VERSION",
            "expected_ti_project_version %d does not match the project's current version %d."
            % (expected, project["version"]),
        )
    _ti_state_guard(project, ("DESIGN",))

    share = calc.line_effective_share(project, category, override)
    landlord_amount, tenant_amount = calc.split_line(cost_amount, share)
    prospective = calc.q2(
        project["authorized_allowance_total"]
        - (project["landlord_committed_amount"] + landlord_amount)
    )
    if prospective < 0:
        raise ApiError(
            "ERR_TI_ALLOWANCE_EXCEEDED",
            "A landlord share of %s would leave allowance_remaining at %s."
            % (landlord_amount, prospective),
        )

    row = {
        "ti_project_id": project["id"],
        "sequence_no": project["line_item_count"] + 1,
        "description": description,
        "category": category,
        "cost_amount": cost_amount,
        "landlord_share_pct_override": override,
        "effective_share_pct": share,
        "landlord_share_amount": landlord_amount,
        "tenant_share_amount": tenant_amount,
    }
    stamp_new(row, versioned=False)
    db.ti_line_items[row["id"]] = row
    calc.recompute_ti_totals(project)
    touch(project)
    return object_response(ser.ti_line_item_out(row), 201)


@bp.get("/ti-projects/<project_id>/line-items")
@endpoint()
def list_line_items(project_id):
    limit, offset = v.pagination()
    category = v.query_enum("category", enums.TI_CATEGORIES)
    project = get_resource(db.ti_projects, project_id, "Tenant-improvement project")
    _project_scope(project)
    rows = calc.line_items_of_project(project["id"])
    if category is not None:
        rows = [l for l in rows if l["category"] == category]
    return paged(rows, ser.ti_line_item_out, limit, offset)


# -------------------------------------------------------------- transitions


@bp.post("/ti-projects/<project_id>/transitions")
@endpoint("LeasingAgent")
def ti_transition(project_id):
    body = v.json_body()
    action = v.get_enum(body, "action", enums.TI_ACTIONS)
    v.get_string(body, "note", required=False, allow_empty=True)

    project = get_resource(db.ti_projects, project_id, "Tenant-improvement project")
    lease = db.leases[project["lease_id"]]
    suite = db.suites[project["suite_id"]]

    if action == "SUBMIT_REVIEWS":
        _ti_state_guard(project, ("DESIGN",))
        if project["line_item_count"] < 1:
            raise ApiError(
                "ERR_INVALID_TI_STATE",
                "Project '%s' carries no line items." % project["id"],
            )
        if project["target_suite_class"] == "IMAGING" and (
            project["lead_thickness_mm"] is None or project["lead_thickness_mm"] <= 0
        ):
            raise ApiError(
                "ERR_INVALID_TI_STATE",
                "Project '%s' targets IMAGING without a positive lead_thickness_mm."
                % project["id"],
            )
        if lease["status"] in ("TERMINATED", "WITHDRAWN", "SUSPENDED_MIX_REVIEW"):
            raise ApiError(
                "ERR_INVALID_LEASE_STATE",
                "Lease '%s' is in status %s." % (lease["id"], lease["status"]),
            )
        # FORK — both dimensions open in the same transition.
        project["status"] = "IN_REVIEW"
        project["shielding_review_status"] = "PENDING"
        project["utility_review_status"] = "PENDING"
        touch(project)
        return object_response(ser.ti_project_out(project))

    if action == "START_CONSTRUCTION":
        _ti_state_guard(project, ("PERMITTED",))
        if lease["status"] not in ("EXECUTED", "ACTIVE"):
            raise ApiError(
                "ERR_TI_PROJECT_NOT_COMPLETE",
                "Lease '%s' is in status %s; construction requires EXECUTED or ACTIVE."
                % (lease["id"], lease["status"]),
            )
        if project["allowance_remaining"] < 0:
            raise ApiError(
                "ERR_TI_ALLOWANCE_EXCEEDED",
                "Project '%s' has a negative allowance_remaining." % project["id"],
            )
        project["status"] = "CONSTRUCTION"
        touch(project)
        return object_response(ser.ti_project_out(project))

    # CANCEL — identical compensation from DESIGN, IN_REVIEW or PERMITTED.
    _ti_state_guard(project, CANCELLABLE_STATUSES)
    _compensate_utility(project, suite)
    if project["shielding_review_status"] == "APPROVED":
        _compensate_shielding(suite)
    touch(suite)
    project["status"] = "CANCELLED"
    project["landlord_committed_amount"] = ZERO
    project["tenant_committed_amount"] = ZERO
    project["allowance_remaining"] = project["authorized_allowance_total"]
    touch(project)
    return object_response(ser.ti_project_out(project))


# ------------------------------------------------------- engineering reviews


@bp.post("/ti-projects/<project_id>/reviews")
@endpoint("FacilitiesEngineer")
def record_review(project_id):
    body = v.json_body()
    review_type = v.get_enum(body, "review_type", enums.TI_REVIEW_TYPES)
    decision = v.get_enum(body, "decision", enums.TI_REVIEW_DECISIONS)
    verified = v.get_money(body, "lead_thickness_verified_mm", required=False)
    v.get_string(body, "review_note", required=False, allow_empty=True)

    project = get_resource(db.ti_projects, project_id, "Tenant-improvement project")
    _ti_state_guard(project, ("IN_REVIEW",))
    addressed = "shielding_review_status" if review_type == "SHIELDING" else "utility_review_status"
    other = "utility_review_status" if review_type == "SHIELDING" else "shielding_review_status"
    if project[addressed] != "PENDING":
        raise ApiError(
            "ERR_INVALID_TI_STATE",
            "The %s review dimension of project '%s' reads %s, not PENDING."
            % (review_type, project["id"], project[addressed]),
        )
    suite = db.suites[project["suite_id"]]

    if decision == "APPROVE":
        if review_type == "SHIELDING":
            if project["target_suite_class"] == "IMAGING" and (
                verified is None or verified < project["lead_thickness_mm"]
            ):
                raise ApiError(
                    "ERR_SHIELDING_CERTIFICATION_MISSING",
                    "lead_thickness_verified_mm must be at least the designed %s."
                    % project["lead_thickness_mm"],
                )
            # BRANCH A — shielding only; never electrical capacity.
            project["shielding_review_status"] = "APPROVED"
            suite["shielding_certified"] = True
            suite["lead_thickness_mm"] = verified
        else:
            # Rung 19 (medical gas) precedes rung 20 (electrical capacity).
            if project["medical_gas_requested"] and not suite["medical_gas_available"]:
                raise ApiError(
                    "ERR_SHIELDING_CERTIFICATION_MISSING",
                    "Suite '%s' provides no piped medical gas." % suite["id"],
                )
            if suite["power_amps_available"] < project["power_amps_requested"]:
                raise ApiError(
                    "ERR_INSUFFICIENT_UTILITY_CAPACITY",
                    "Suite '%s' has %d amps available against %d requested."
                    % (suite["id"], suite["power_amps_available"], project["power_amps_requested"]),
                )
            # BRANCH B — utility only; never shielding.
            project["utility_review_status"] = "APPROVED"
            suite["power_amps_available"] -= project["power_amps_requested"]
            project["power_amps_drawn"] = project["power_amps_requested"]
        touch(suite)
        # JOIN — the same request permits the project once both are in.
        if project[other] == "APPROVED":
            project["status"] = "PERMITTED"
        touch(project)
        return object_response(ser.ti_project_out(project))

    # REJECT — cycle back to DESIGN with full compensation of the other branch.
    suite_touched = False
    if project[other] == "APPROVED":
        if other == "shielding_review_status":
            _compensate_shielding(suite)
        else:
            _compensate_utility(project, suite)
        suite_touched = True
    if suite_touched:
        touch(suite)
    project[addressed] = "REJECTED"
    project[other] = "NOT_SUBMITTED"
    project["status"] = "DESIGN"
    touch(project)
    return object_response(ser.ti_project_out(project))


@bp.post("/ti-projects/<project_id>/complete")
@endpoint("FacilitiesEngineer")
def complete_project(project_id):
    body = v.json_body()
    v.get_string(body, "completion_note", required=False, allow_empty=True)

    project = get_resource(db.ti_projects, project_id, "Tenant-improvement project")
    _ti_state_guard(project, ("CONSTRUCTION",))
    if (
        project["shielding_review_status"] != "APPROVED"
        or project["utility_review_status"] != "APPROVED"
    ):
        raise ApiError(
            "ERR_INVALID_TI_STATE",
            "Both review dimensions of project '%s' must read APPROVED." % project["id"],
        )
    if project["allowance_remaining"] < 0:
        raise ApiError(
            "ERR_TI_ALLOWANCE_EXCEEDED",
            "Project '%s' has a negative allowance_remaining." % project["id"],
        )

    suite = db.suites[project["suite_id"]]
    # The suite legally becomes what it was built to be; the class premium in
    # Section 3.4 and the turnover buffer in Section 3.5 both key off this.
    suite["suite_class"] = project["target_suite_class"]
    if project["medical_gas_requested"]:
        suite["medical_gas_available"] = True
    touch(suite)
    project["status"] = "COMPLETE"
    touch(project)
    return object_response(ser.ti_project_out(project))
