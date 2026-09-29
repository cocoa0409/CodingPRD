"""Recovery groups, runbook revisions and runbook steps."""

from decimal import Decimal

from flask import Blueprint

from constants import (
    POSTURES,
    READ_ROLES,
    ROLE_AUDIT_LIAISON,
    ROLE_COORDINATOR,
    ROLE_IT_OPERATOR,
    RUNBOOK_ACTIONS,
    RUNBOOK_STATUSES,
    STEP_VALIDATION_STATUSES,
)
from db import db, new_row, now, touch
from errors import ApiError
from middleware import endpoint
from response import created, ok, ok_list
import services
from validation import (
    body,
    check_fk,
    filter_value,
    lookup_path,
    paginate,
    v_dt,
    v_enum,
    v_int,
    v_str,
)

bp = Blueprint("groups", __name__)


# --------------------------------------------------------------------------- #
# Recovery groups
# --------------------------------------------------------------------------- #

@bp.post("/recovery-groups")
@endpoint([ROLE_COORDINATOR])
def create_recovery_group():
    payload = body()
    check_fk(payload, "recovery_site_id", "sites")
    check_fk(payload, "lead_coordinator_id", "stakeholders")

    name = v_str(payload, "name")
    group_code = v_str(payload, "group_code")
    site_id = v_str(payload, "recovery_site_id")
    lead_id = v_str(payload, "lead_coordinator_id")
    recovery_order = v_int(payload, "recovery_order", minimum=1)

    for existing in db.recovery_groups.values():
        if existing["group_code"] == group_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "group_code '%s' is already in use." % group_code)

    row = new_row()
    row.update({
        "name": name,
        "group_code": group_code,
        "recovery_site_id": site_id,
        "lead_coordinator_id": lead_id,
        "recovery_order": recovery_order,
        "posture": "RESTRICTED",
        "posture_reason": "NO_VALIDATED_RUNBOOK",
        "current_runbook_id": None,
        "projected_recovery_minutes": 0,
        "recovery_sequence": [],
        "open_finding_count": 0,
        "change_freeze_start_at": None,
        "change_freeze_end_at": None,
    })
    db.recovery_groups[row["id"]] = row
    return created(row)


@bp.get("/recovery-groups/<row_id>")
@endpoint(READ_ROLES)
def get_recovery_group(row_id):
    return ok(lookup_path("recovery_groups", row_id))


@bp.get("/recovery-groups")
@endpoint(READ_ROLES)
def list_recovery_groups():
    site = filter_value("recovery_site_id")
    lead = filter_value("lead_coordinator_id")
    runbook = filter_value("current_runbook_id")
    posture = filter_value("posture", POSTURES)
    rows = []
    for row in db.recovery_groups.values():
        if site is not None and row["recovery_site_id"] != site:
            continue
        if lead is not None and row["lead_coordinator_id"] != lead:
            continue
        if runbook is not None and row["current_runbook_id"] != runbook:
            continue
        if posture is not None and row["posture"] != posture:
            continue
        rows.append(row)
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/recovery-groups/<row_id>/change-freeze")
@endpoint([ROLE_COORDINATOR])
def set_change_freeze(row_id):
    group = lookup_path("recovery_groups", row_id)
    payload = body()
    start = v_dt(payload, "change_freeze_start_at")
    end = v_dt(payload, "change_freeze_end_at")

    # rank 44 -- the freeze interval is closed, so equal endpoints are legal.
    if end < start:
        raise ApiError("ERR_INVALID_WINDOW",
                       "change_freeze_end_at must be at or after change_freeze_start_at.")

    group["change_freeze_start_at"] = start
    group["change_freeze_end_at"] = end
    touch(group)                        # declared: increments the group's version by 1
    return created(group)


@bp.post("/recovery-groups/<row_id>/posture-refresh")
@endpoint([ROLE_COORDINATOR, ROLE_AUDIT_LIAISON])
def refresh_posture(row_id):
    group = lookup_path("recovery_groups", row_id)
    services.refresh_readiness_score(db.runbooks.get(group["current_runbook_id"]))
    services.refresh_projection(group)
    services.refresh_open_finding_count(group)
    services.apply_posture(group)
    return ok(group)


# --------------------------------------------------------------------------- #
# Runbooks
# --------------------------------------------------------------------------- #

@bp.post("/runbooks")
@endpoint([ROLE_COORDINATOR])
def create_runbook():
    payload = body()
    check_fk(payload, "recovery_group_id", "recovery_groups")
    check_fk(payload, "author_id", "stakeholders")

    group_id = v_str(payload, "recovery_group_id")
    title = v_str(payload, "title")
    author_id = v_str(payload, "author_id")
    expected_version = v_int(payload, "expected_recovery_group_version")
    validity_days = v_int(payload, "validity_days", required=False, default=180,
                          minimum=1, maximum=3650)

    group = db.recovery_groups[group_id]
    # rank 7 -- optimistic concurrency on the recovery group.
    if expected_version != group["version"]:
        raise ApiError(
            "ERR_STALE_RECOVERY_GROUP_VERSION",
            "expected_recovery_group_version %s does not match the group's current "
            "version %s." % (expected_version, group["version"]),
        )

    revision = 1 + len(services.runbooks_of(group_id))
    row = new_row()
    row.update({
        "recovery_group_id": group_id,
        "title": title,
        "author_id": author_id,
        "revision": revision,
        "status": "DRAFT",
        "validity_days": validity_days,
        "validated_at": None,
        "readiness_score": Decimal("0.00"),
        "stale_reason": "NONE",
    })
    db.runbooks[row["id"]] = row
    touch(group)                        # declared: increments the group's version by 1
    return created(row)


@bp.get("/runbooks/<row_id>")
@endpoint(READ_ROLES)
def get_runbook(row_id):
    return ok(lookup_path("runbooks", row_id))


@bp.get("/runbooks")
@endpoint(READ_ROLES)
def list_runbooks():
    group = filter_value("recovery_group_id")
    author = filter_value("author_id")
    status = filter_value("status", RUNBOOK_STATUSES)
    rows = []
    for row in db.runbooks.values():
        if group is not None and row["recovery_group_id"] != group:
            continue
        if author is not None and row["author_id"] != author:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, meta = paginate(rows)
    return ok_list(page, meta)


_RUNBOOK_FROM_STATES = {
    "SUBMIT_FOR_REVIEW": ("DRAFT", "STALE"),
    "RETURN_TO_DRAFT": ("IN_REVIEW",),
    "VALIDATE": ("IN_REVIEW",),
}


@bp.post("/runbooks/<row_id>/transitions")
@endpoint([ROLE_COORDINATOR])
def transition_runbook(row_id):
    runbook = lookup_path("runbooks", row_id)
    payload = body()
    action = v_enum(payload, "action", RUNBOOK_ACTIONS)
    v_str(payload, "note", required=False)

    status = runbook["status"]
    # rank 11 -- from-state plus the action's own precondition, one error id.
    if status not in _RUNBOOK_FROM_STATES[action]:
        raise ApiError("ERR_INVALID_RUNBOOK_STATE",
                       "Action %s is not declared from status %s." % (action, status))

    steps = services.steps_of(runbook["id"])
    if action == "SUBMIT_FOR_REVIEW":
        if status == "DRAFT" and not steps:
            raise ApiError("ERR_INVALID_RUNBOOK_STATE",
                           "SUBMIT_FOR_REVIEW requires at least one step.")
        if status == "STALE" and any(s["validation_status"] == "INVALIDATED" for s in steps):
            raise ApiError(
                "ERR_INVALID_RUNBOOK_STATE",
                "SUBMIT_FOR_REVIEW from STALE requires no INVALIDATED step.",
            )
        runbook["status"] = "IN_REVIEW"
    elif action == "RETURN_TO_DRAFT":
        runbook["status"] = "DRAFT"
    else:  # VALIDATE
        if any(s["validation_status"] != "VALIDATED" for s in steps):
            raise ApiError("ERR_INVALID_RUNBOOK_STATE",
                           "VALIDATE requires every step to be VALIDATED.")
        runbook["status"] = "VALIDATED"
        runbook["validated_at"] = now()
        runbook["stale_reason"] = "NONE"

    touch(runbook)
    services.refresh_readiness_score(runbook)   # every action recomputes readiness

    if action == "VALIDATE":
        group = db.recovery_groups.get(runbook["recovery_group_id"])
        if group is not None:
            group["current_runbook_id"] = runbook["id"]
            touch(group)
            # Supersede every earlier revision of the same group that held
            # VALIDATED or STALE standing.
            for other in services.runbooks_of(group["id"]):
                if (other["id"] != runbook["id"]
                        and other["revision"] < runbook["revision"]
                        and other["status"] in ("VALIDATED", "STALE")):
                    other["status"] = "SUPERSEDED"
                    other["stale_reason"] = "SUPERSEDED_BY_REVISION"
                    touch(other)
            services.apply_posture(group)
    return created(runbook)


# --------------------------------------------------------------------------- #
# Runbook steps
# --------------------------------------------------------------------------- #

@bp.post("/runbook-steps")
@endpoint([ROLE_COORDINATOR, ROLE_IT_OPERATOR])
def create_runbook_step():
    payload = body()
    check_fk(payload, "runbook_id", "runbooks")
    check_fk(payload, "owner_id", "stakeholders")
    check_fk(payload, "covers_application_id", "applications")
    check_fk(payload, "covers_asset_id", "assets")

    runbook_id = v_str(payload, "runbook_id")
    step_number = v_int(payload, "step_number", minimum=1)
    description = v_str(payload, "description")
    owner_id = v_str(payload, "owner_id")
    expected_minutes = v_int(payload, "expected_minutes", minimum=0)
    weight = v_int(payload, "weight", minimum=1, maximum=20)
    covers_application_id = v_str(payload, "covers_application_id", required=False)
    covers_asset_id = v_str(payload, "covers_asset_id", required=False)

    runbook = db.runbooks[runbook_id]
    # rank 12
    if runbook["status"] == "SUPERSEDED":
        raise ApiError("ERR_INVALID_STEP_STATE",
                       "Steps may not be added to a SUPERSEDED runbook.")
    # rank 36
    for existing in services.steps_of(runbook_id):
        if existing["step_number"] == step_number:
            raise ApiError("ERR_DUPLICATE_STEP_NUMBER",
                           "step_number %s already exists in this runbook." % step_number)

    row = new_row()
    row.update({
        "runbook_id": runbook_id,
        "step_number": step_number,
        "description": description,
        "owner_id": owner_id,
        "expected_minutes": expected_minutes,
        "weight": weight,
        "validation_status": "PENDING",
        "last_validated_at": None,
        "covers_application_id": covers_application_id,
        "covers_asset_id": covers_asset_id,
    })
    db.runbook_steps[row["id"]] = row
    return created(row)


@bp.get("/runbook-steps/<row_id>")
@endpoint(READ_ROLES)
def get_runbook_step(row_id):
    return ok(lookup_path("runbook_steps", row_id))


@bp.get("/runbook-steps")
@endpoint(READ_ROLES)
def list_runbook_steps():
    runbook = filter_value("runbook_id")
    owner = filter_value("owner_id")
    covers_app = filter_value("covers_application_id")
    covers_asset = filter_value("covers_asset_id")
    status = filter_value("validation_status", STEP_VALIDATION_STATUSES)
    rows = []
    for row in db.runbook_steps.values():
        if runbook is not None and row["runbook_id"] != runbook:
            continue
        if owner is not None and row["owner_id"] != owner:
            continue
        if covers_app is not None and row["covers_application_id"] != covers_app:
            continue
        if covers_asset is not None and row["covers_asset_id"] != covers_asset:
            continue
        if status is not None and row["validation_status"] != status:
            continue
        rows.append(row)
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/runbook-steps/<row_id>/validations")
@endpoint([ROLE_IT_OPERATOR])
def validate_runbook_step(row_id):
    step = lookup_path("runbook_steps", row_id)
    payload = body()
    v_str(payload, "validation_note", required=False)

    runbook = db.runbooks.get(step["runbook_id"])
    # rank 12
    if runbook is None or runbook["status"] == "SUPERSEDED":
        raise ApiError("ERR_INVALID_STEP_STATE",
                       "A step of a SUPERSEDED runbook may not be validated.")
    # rank 25
    if step["covers_application_id"]:
        covered = db.applications.get(step["covers_application_id"])
        if covered is None or covered["tier_agreement_status"] != "AGREED":
            raise ApiError(
                "ERR_STEP_COVERS_UNAGREED_APPLICATION",
                "The covered application's tier agreement is not AGREED.",
            )

    step["validation_status"] = "VALIDATED"
    step["last_validated_at"] = now()
    touch(step)

    services.refresh_readiness_score(runbook)
    group = db.recovery_groups.get(runbook["recovery_group_id"])
    if group is not None:
        services.apply_posture(group)
    return created(step)
