"""Permits: application, issuance, recalculation, disturbance reporting, the
parent-scoped discovery reads and the computed bond summary (PRD 3.2, 3.4)."""

from flask import Blueprint

import calculations as calc
import constants as C
import engine
import serialization as ser
from db import D, ZERO, base_row, days, db, now
from engine import bump
from errors import ApiError
from response import created_response, object_response
from routes._shared import (
    apply_filters,
    check_decision_reason,
    collection_filtered,
    paged,
    precheck_denial_reason,
    require_permit_operator,
    require_permit_status,
)
from validation import (
    authorize,
    datetime_field,
    enum_field,
    get_body,
    int_field,
    lookup,
    number_field,
    query_enum,
    resolve,
    str_field,
)

bp = Blueprint("permits", __name__)

LIST_FILTERS = [
    ("operator_id", "operator_id", None),
    ("mine_site_id", "mine_site_id", None),
    ("status", "status", C.PERMIT_STATUSES),
    ("compliance_posture", "compliance_posture", C.COMPLIANCE_POSTURES),
    ("bond_basis", "bond_basis", C.BOND_BASES),
]


# ==========================================================================
# Creation, reads
# ==========================================================================
@bp.post("/mining/permits")
def create_permit():
    user_id, role = authorize([C.ROLE_OPERATOR])
    body = get_body()
    mine_site_id = str_field(body, "mine_site_id")
    operator_id = str_field(body, "operator_id")
    mining_plan_acres = number_field(body, "mining_plan_acres", gt=0)
    post_mining_land_use = enum_field(body, "post_mining_land_use", C.POST_MINING_LAND_USES)
    proposed_start_date = datetime_field(body, "proposed_start_date")

    # Band 5 — body reference existence, left to right as §2.5 lists them.
    resolve(db.mine_sites, mine_site_id, "ERR_MINE_SITE_NOT_FOUND")
    operator = resolve(db.operators, operator_id, "ERR_OPERATOR_NOT_FOUND")

    # Band 6 — the special form of the ownership rule for this creation.
    if user_id != operator_id:
        raise ApiError(
            "ERR_NOT_PERMIT_OPERATOR",
            "The acting user must be the operator named in the application.",
        )

    # Band 10 — a disqualified operator may not apply at all.
    if operator["registry_status"] == "DISQUALIFIED":
        raise ApiError(
            "ERR_OPERATOR_DISQUALIFIED", "A disqualified operator may not file a permit application."
        )

    row = base_row()
    row.update(
        {
            "mine_site_id": mine_site_id,
            "operator_id": operator_id,
            "mining_plan_acres": mining_plan_acres,
            "post_mining_land_use": post_mining_land_use,
            "proposed_start_date": proposed_start_date,
            "status": "APPLICATION_SUBMITTED",
            "compliance_posture": "COMPLIANT",
            "bond_basis": "FULL_PLAN",
            "bond_required_amount": ZERO,
            "bond_held_amount": ZERO,
            "bond_released_to_date": ZERO,
            "bond_deficiency_amount": ZERO,
            "disturbed_acres": ZERO,
            "reclaimed_acres_credited": ZERO,
            "phase1_released_acres": ZERO,
            "phase2_released_acres": ZERO,
            "phase3_released_acres": ZERO,
            "last_notice_end_date": None,
            "issued_at": None,
            "denial_reason": None,
        }
    )
    db.permits[row["id"]] = row
    return created_response(ser.permit_out(row))


@bp.get("/mining/permits/<permit_id>")
def get_permit(permit_id):
    authorize(C.ALL_ROLES)
    row = lookup(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
    return object_response(ser.permit_out(row))


@bp.get("/mining/permits")
def list_permits():
    authorize(C.ALL_ROLES)
    return collection_filtered(db.permits.values(), LIST_FILTERS, ser.permit_out)


# ==========================================================================
# Decisions and determinations
# ==========================================================================
@bp.post("/mining/permits/<permit_id>/decide")
def decide_permit(permit_id):
    authorize([C.ROLE_PERMIT_REVIEWER])
    body = get_body()
    decision = enum_field(body, "decision", C.DECISIONS_ISSUE)
    precheck_denial_reason(body)

    permit = lookup(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")

    # Band 9 — both branches require APPLICATION_SUBMITTED.
    require_permit_status(permit, ["APPLICATION_SUBMITTED"])

    if decision == "ISSUE":
        # Band 10.
        operator = db.operators.get(permit["operator_id"])
        if operator is None or operator["registry_status"] != "ACTIVE":
            raise ApiError(
                "ERR_OPERATOR_DISQUALIFIED",
                "A permit cannot be issued to a disqualified operator.",
            )
        # Band 11.
        if calc.accepted_estimate(permit["id"]) is None:
            raise ApiError(
                "ERR_NO_ACCEPTED_ESTIMATE",
                "A permit cannot be issued without an accepted reclamation cost estimate.",
            )

    # Band 13 — the decision / denial_reason coupling.
    denial_reason = check_decision_reason(decision, body)

    if decision == "ISSUE":
        # Band 15 — the fiscal gate.
        if D(permit["bond_held_amount"]) < D(permit["bond_required_amount"]):
            raise ApiError(
                "ERR_BOND_BELOW_REQUIRED",
                "The bond held is below the required amount for this permit.",
            )
        permit["status"] = "ISSUED"
        permit["issued_at"] = now()
        engine.recompute_posture(permit)
    else:
        permit["status"] = "DENIED"
        permit["denial_reason"] = denial_reason

    bump(permit)
    return object_response(ser.permit_out(permit))


@bp.post("/mining/permits/<permit_id>/recalculate-bond")
def recalculate_bond(permit_id):
    authorize([C.ROLE_BOND_SPECIALIST])
    body = get_body()
    basis = enum_field(body, "basis", C.BOND_BASES)
    expected_version = int_field(body, "expected_permit_version")

    permit = lookup(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")

    # Band 8 — the stale-determination guard.
    if expected_version != permit["version"]:
        raise ApiError(
            "ERR_STALE_PERMIT_VERSION",
            "The permit has moved since it was last read; re-read its version.",
        )

    # Band 9.
    require_permit_status(permit, C.PERMIT_STATUSES_RECALC)

    # Band 11.
    estimate = calc.accepted_estimate(permit["id"])
    if estimate is None:
        raise ApiError(
            "ERR_NO_ACCEPTED_ESTIMATE",
            "A recalculation requires an accepted reclamation cost estimate.",
        )

    # Band 12 — the estimate must still be within its three-year currency.
    if (now() - estimate["estimate_effective_date"]) > days(C.ESTIMATE_MAX_AGE_DAYS):
        raise ApiError(
            "ERR_ESTIMATE_EXPIRED",
            "The accepted cost estimate is more than three years old.",
        )

    permit["bond_basis"] = basis
    engine.rerun_bond_determination(permit)
    engine.recompute_posture(permit)
    bump(permit)
    return object_response(ser.permit_out(permit))


@bp.post("/mining/permits/<permit_id>/cease-mining")
def cease_mining(permit_id):
    user_id, role = authorize([C.ROLE_OPERATOR])
    get_body()
    permit = lookup(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")

    # Band 6.
    require_permit_operator(role, user_id, permit)

    # Band 9 — admitted only from ISSUED, and only with ground actually broken.
    if permit["status"] != "ISSUED" or D(permit["disturbed_acres"]) <= 0:
        raise ApiError(
            "ERR_PERMIT_STATE_INVALID",
            "Only an issued permit with disturbed acreage may enter the reclamation phase.",
        )

    permit["status"] = "RECLAMATION_PHASE"
    engine.recompute_posture(permit)
    bump(permit)
    return object_response(ser.permit_out(permit))


@bp.patch("/mining/permits/<permit_id>/disturbance")
def report_disturbance(permit_id):
    user_id, role = authorize([C.ROLE_OPERATOR])
    body = get_body()
    disturbed = number_field(body, "disturbed_acres", required=False, ge=0)
    reclaimed = number_field(body, "reclaimed_acres_credited", required=False, ge=0)

    permit = lookup(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
    require_permit_operator(role, user_id, permit)
    require_permit_status(permit, C.PERMIT_STATUSES_DISTURBANCE)

    if disturbed is not None:
        permit["disturbed_acres"] = disturbed
    if reclaimed is not None:
        permit["reclaimed_acres_credited"] = reclaimed
    # Deliberately no re-pricing: only an explicit recalculation moves the bond.
    bump(permit)
    return object_response(ser.permit_out(permit))


# ==========================================================================
# Parent-scoped discovery reads (PRD 2.11)
# ==========================================================================
def _parent(permit_id, roles):
    authorize(roles)
    return lookup(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")


@bp.get("/mining/permits/<permit_id>/reclamation-cost-estimates")
def permit_estimates(permit_id):
    _parent(permit_id, C.ROLES_OP_STAFF)
    rows = [r for r in db.estimates.values() if r["permit_id"] == permit_id]
    rows = apply_filters(rows, [("status", "status", C.ESTIMATE_STATUSES)])
    return paged(rows, ser.estimate_out)


@bp.get("/mining/permits/<permit_id>/bond-instruments")
def permit_instruments(permit_id):
    _parent(permit_id, C.ROLES_OP_STAFF)
    rows = [r for r in db.instruments.values() if r["permit_id"] == permit_id]
    rows = apply_filters(rows, [("status", "status", C.INSTRUMENT_STATUSES)])
    return paged(rows, ser.instrument_out)


@bp.get("/mining/permits/<permit_id>/bond-release-applications")
def permit_releases(permit_id):
    _parent(permit_id, C.ROLES_OP_STAFF_PUBLIC)
    rows = [r for r in db.release_apps.values() if r["permit_id"] == permit_id]
    rows = apply_filters(
        rows,
        [("status", "status", C.RELEASE_STATUSES), ("phase", "phase", C.RELEASE_PHASES)],
    )
    return paged(rows, ser.release_out)


@bp.get("/mining/permits/<permit_id>/inspections")
def permit_inspections(permit_id):
    _parent(permit_id, C.ROLES_OP_STAFF_INSPECTOR)
    rows = [r for r in db.inspections.values() if r["permit_id"] == permit_id]
    rows = apply_filters(
        rows,
        [
            ("status", "status", C.INSPECTION_STATUSES),
            ("inspection_type", "inspection_type", C.INSPECTION_TYPES),
        ],
    )
    return paged(rows, ser.inspection_out)


@bp.get("/mining/permits/<permit_id>/violation-notices")
def permit_notices(permit_id):
    _parent(permit_id, C.ALL_ROLES)
    rows = [r for r in db.notices.values() if r["permit_id"] == permit_id]
    rows = apply_filters(
        rows,
        [
            ("notice_status", "notice_status", C.NOTICE_STATUSES),
            ("penalty_status", "penalty_status", C.PENALTY_STATUSES),
        ],
    )
    return paged(rows, ser.notice_out)


@bp.get("/mining/permits/<permit_id>/permit-revisions")
def permit_revisions(permit_id):
    _parent(permit_id, C.ROLES_REVISION_READ)
    rows = [r for r in db.revisions.values() if r["permit_id"] == permit_id]
    rows = apply_filters(
        rows,
        [
            ("status", "status", C.REVISION_STATUSES),
            ("revision_type", "revision_type", C.REVISION_TYPES),
        ],
    )
    return paged(rows, ser.revision_out)


@bp.get("/mining/permits/<permit_id>/forfeiture-proceedings")
def permit_proceedings(permit_id):
    _parent(permit_id, C.ROLES_OP_STAFF_PUBLIC)
    rows = [r for r in db.proceedings.values() if r["permit_id"] == permit_id]
    rows = apply_filters(rows, [("status", "status", C.PROCEEDING_STATUSES)])
    return paged(rows, ser.proceeding_out)


@bp.get("/mining/permits/<permit_id>/bond-summary")
def bond_summary(permit_id):
    permit = _parent(permit_id, C.ROLES_OP_STAFF)
    phase = query_enum("phase", C.RELEASE_PHASES) or C.DEFAULT_BOND_SUMMARY_PHASE
    floor = calc.retention_floor(permit, phase)
    releasable = calc.available_headroom(permit, phase)
    return object_response(
        {
            "bond_required_amount": float(permit["bond_required_amount"]),
            "bond_held_amount": float(permit["bond_held_amount"]),
            "bond_released_to_date": float(permit["bond_released_to_date"]),
            "bond_deficiency_amount": float(permit["bond_deficiency_amount"]),
            "retention_floor": float(floor),
            "releasable_amount": float(releasable),
        }
    )
