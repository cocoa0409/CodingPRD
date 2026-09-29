"""Findings, evidence packages and the logical-clock test surface."""

from flask import Blueprint, g

from constants import (
    EVIDENCE_ACTIONS,
    EVIDENCE_STATES,
    FINDING_ACTIONS,
    FINDING_STATES,
    READ_ROLES,
    RETEST_RESULTS,
    ROLE_AUDIT_LIAISON,
    ROLE_COORDINATOR,
    ROLE_IT_OPERATOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_RISK_APPROVER,
    SEVERITIES,
)
from db import db, iso, new_row, now, parse_dt, touch
from errors import ApiError, bad_request
from middleware import actor_id, endpoint
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
    v_str,
)

bp = Blueprint("audit", __name__)


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #

@bp.post("/findings")
@endpoint([ROLE_COORDINATOR, ROLE_IT_OPERATOR, ROLE_AUDIT_LIAISON])
def create_finding():
    payload = body()
    check_fk(payload, "exercise_id", "exercises")
    check_fk(payload, "recovery_group_id", "recovery_groups")

    exercise_id = v_str(payload, "exercise_id")
    group_id = v_str(payload, "recovery_group_id")
    severity = v_enum(payload, "severity", SEVERITIES)
    title = v_str(payload, "title")
    description = v_str(payload, "description")
    due_at = v_dt(payload, "due_at", required=False)

    row = new_row()
    row.update({
        "exercise_id": exercise_id,
        "recovery_group_id": group_id,
        "severity": severity,
        "title": title,
        "description": description,
        "owner_id": None,
        "state": "OPEN",
        "retest_exercise_id": None,
        "retest_failure_count": 0,
        "escalated": False,
        "due_at": due_at,
    })
    db.findings[row["id"]] = row

    group = db.recovery_groups[group_id]
    services.refresh_open_finding_count(group)
    return created(row)


@bp.get("/findings/<row_id>")
@endpoint(READ_ROLES)
def get_finding(row_id):
    return ok(lookup_path("findings", row_id))


@bp.get("/findings")
@endpoint(READ_ROLES)
def list_findings():
    exercise = filter_value("exercise_id")
    group = filter_value("recovery_group_id")
    owner = filter_value("owner_id")
    retest = filter_value("retest_exercise_id")
    state = filter_value("state", FINDING_STATES)
    severity = filter_value("severity", SEVERITIES)
    rows = []
    for row in db.findings.values():
        if exercise is not None and row["exercise_id"] != exercise:
            continue
        if group is not None and row["recovery_group_id"] != group:
            continue
        if owner is not None and row["owner_id"] != owner:
            continue
        if retest is not None and row["retest_exercise_id"] != retest:
            continue
        if state is not None and row["state"] != state:
            continue
        if severity is not None and row["severity"] != severity:
            continue
        rows.append(row)
    page, meta = paginate(rows)
    return ok_list(page, meta)


# CLOSE is reachable only through RECORD_RETEST_RESULT/PASSED, so the action has
# no declared from-state of its own and always reports the state error.
_FINDING_FROM_STATES = {
    "ASSIGN": ("OPEN", "RETEST_FAILED"),
    "REMEDIATE": ("REMEDIATION_ASSIGNED",),
    "SCHEDULE_RETEST": ("REMEDIATED",),
    "RECORD_RETEST_RESULT": ("RETEST_SCHEDULED",),
    "CLOSE": (),
    "WITHDRAW": ("OPEN", "REMEDIATION_ASSIGNED", "RETEST_FAILED"),
}


@bp.post("/findings/<row_id>/transitions")
@endpoint([ROLE_COORDINATOR])
def transition_finding(row_id):
    finding = lookup_path("findings", row_id)
    payload = body()
    # rank 5 -- body foreign keys are checked whenever they are supplied at all.
    check_fk(payload, "owner_id", "stakeholders")
    check_fk(payload, "retest_exercise_id", "exercises")

    action = v_enum(payload, "action", FINDING_ACTIONS)
    v_str(payload, "note", required=False)

    state = finding["state"]
    # rank 14 -- the from-state dominates the action-conditional payload fields.
    if state not in _FINDING_FROM_STATES[action]:
        raise ApiError("ERR_INVALID_FINDING_STATE",
                       "Action %s is not declared from state %s." % (action, state))

    if action == "ASSIGN":
        owner_id = v_str(payload, "owner_id")
        owner = db.stakeholders[owner_id]
        if owner["status"] != "ACTIVE":
            raise bad_request("owner_id must reference an ACTIVE stakeholder.")
        finding["owner_id"] = owner_id
        finding["state"] = "REMEDIATION_ASSIGNED"

    elif action == "REMEDIATE":
        if not finding["owner_id"]:
            raise bad_request("The finding has no remediation owner.")
        finding["state"] = "REMEDIATED"

    elif action == "SCHEDULE_RETEST":
        retest_id = v_str(payload, "retest_exercise_id")
        retest = db.exercises[retest_id]
        if retest["execution_state"] in ("CLOSED", "CANCELLED", "ABORTED"):
            raise ApiError("ERR_INVALID_EXERCISE_STATE",
                           "The nominated retest exercise is already finished.")
        # rank 32
        in_scope = any(item["recovery_group_id"] == finding["recovery_group_id"]
                       for item in services.scope_items_of(retest_id))
        if not in_scope:
            raise ApiError("ERR_RETEST_SCOPE_MISMATCH",
                           "The nominated retest exercise does not scope the "
                           "finding's recovery group.")
        finding["retest_exercise_id"] = retest_id
        finding["state"] = "RETEST_SCHEDULED"

    elif action == "RECORD_RETEST_RESULT":
        result = v_enum(payload, "retest_result", RETEST_RESULTS)
        if not finding["retest_exercise_id"]:
            raise bad_request("The finding has no nominated retest exercise.")
        if result == "PASSED":
            finding["state"] = "CLOSED"
        else:
            finding["state"] = "RETEST_FAILED"
            # CASCADE B hops 1 and 2.
            services.apply_retest_failure(finding)

    else:  # WITHDRAW
        finding["state"] = "WITHDRAWN"

    touch(finding)

    group = db.recovery_groups.get(finding["recovery_group_id"])
    if group is not None:
        services.refresh_open_finding_count(group)
        # CASCADE B hop 3 onwards, and the thaw when the last escalated
        # CRITICAL finding leaves the board.
        services.apply_posture(group)
    return created(finding)


# --------------------------------------------------------------------------- #
# Evidence packages
# --------------------------------------------------------------------------- #

@bp.post("/evidence-packages")
@endpoint([ROLE_AUDIT_LIAISON])
def create_evidence_package():
    payload = body()
    check_fk(payload, "exercise_id", "exercises")
    check_fk(payload, "prepared_by_id", "stakeholders")

    exercise_id = v_str(payload, "exercise_id")
    prepared_by_id = v_str(payload, "prepared_by_id")

    row = new_row()
    row.update({
        "exercise_id": exercise_id,
        "prepared_by_id": prepared_by_id,
        "signed_off_by_id": None,
        "state": "DRAFT",
        "manifest_line_count": 0,
        "return_reason": "NONE",
        "sealed_at": None,
    })
    db.evidence_packages[row["id"]] = row
    return created(row)


@bp.get("/evidence-packages/<row_id>")
@endpoint(READ_ROLES)
def get_evidence_package(row_id):
    return ok(lookup_path("evidence_packages", row_id))


@bp.get("/evidence-packages")
@endpoint(READ_ROLES)
def list_evidence_packages():
    exercise = filter_value("exercise_id")
    preparer = filter_value("prepared_by_id")
    signer = filter_value("signed_off_by_id")
    state = filter_value("state", EVIDENCE_STATES)
    rows = []
    for row in db.evidence_packages.values():
        if exercise is not None and row["exercise_id"] != exercise:
            continue
        if preparer is not None and row["prepared_by_id"] != preparer:
            continue
        if signer is not None and row["signed_off_by_id"] != signer:
            continue
        if state is not None and row["state"] != state:
            continue
        rows.append(row)
    page, meta = paginate(rows)
    return ok_list(page, meta)


_EVIDENCE_FROM_STATES = {
    "SUBMIT": ("DRAFT", "RETURNED"),
    "RETURN": ("SUBMITTED",),
    "SIGN_OFF": ("SUBMITTED",),
    "SEAL": ("SIGNED_OFF",),
}

# The endpoint is shared by two roles but each action has exactly one actor.
_EVIDENCE_ACTORS = {
    "SUBMIT": ROLE_AUDIT_LIAISON,
    "RETURN": ROLE_AUDIT_LIAISON,
    "SEAL": ROLE_AUDIT_LIAISON,
    "SIGN_OFF": ROLE_RISK_APPROVER,
}


@bp.post("/evidence-packages/<row_id>/transitions")
@endpoint([ROLE_AUDIT_LIAISON, ROLE_RISK_APPROVER])
def transition_evidence_package(row_id):
    package = lookup_path("evidence_packages", row_id)
    payload = body()
    action = v_enum(payload, "action", EVIDENCE_ACTIONS)
    v_str(payload, "note", required=False)

    # The action's declared actor (rank 2 in spirit: the role is not authorised
    # for THIS action even though it may call the endpoint).
    if g.role != _EVIDENCE_ACTORS[action]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Action %s is driven by %s, not %s."
                       % (action, _EVIDENCE_ACTORS[action], g.role))

    # rank 16 is checked before rank 15: a SEALED package has no declared
    # from-state at all, so the seal error would otherwise be unreachable.
    if package["state"] == "SEALED":
        raise ApiError("ERR_EVIDENCE_SEALED",
                       "A SEALED evidence package accepts no further transition.")
    # rank 15
    if package["state"] not in _EVIDENCE_FROM_STATES[action]:
        raise ApiError("ERR_INVALID_EVIDENCE_STATE",
                       "Action %s is not declared from state %s."
                       % (action, package["state"]))

    if action == "SIGN_OFF":
        # rank 20
        if package["prepared_by_id"] == actor_id():
            raise ApiError("ERR_SOD_EVIDENCE_SIGNER",
                           "The preparer of a package may not sign it off.")
        package["signed_off_by_id"] = actor_id()
        package["state"] = "SIGNED_OFF"

    elif action == "SUBMIT":
        # rank 40
        exercise = db.exercises.get(package["exercise_id"])
        if exercise is None or exercise["execution_state"] != "CLOSED":
            raise ApiError("ERR_EXERCISE_NOT_CLOSED",
                           "The evidenced exercise is not CLOSED.")
        package["manifest_line_count"] = services.compute_manifest_line_count(package)
        package["return_reason"] = "NONE"
        package["state"] = "SUBMITTED"

    elif action == "RETURN":
        package["return_reason"] = "INCOMPLETE_MANIFEST"
        package["state"] = "RETURNED"

    else:  # SEAL
        package["sealed_at"] = now()
        package["state"] = "SEALED"

    touch(package)
    return created(package)


# --------------------------------------------------------------------------- #
# Test-driving surface: the logical clock
# --------------------------------------------------------------------------- #

@bp.post("/_clock/set_current_utc")
@endpoint([ROLE_PLATFORM_ADMIN], skip_identity=True)
def set_clock():
    payload = body()
    raw = payload.get("to_iso8601")
    if raw is None:
        raise bad_request("Field 'to_iso8601' is required.")
    parsed = parse_dt(raw)
    if parsed is None:
        raise bad_request("Field 'to_iso8601' must be an ISO 8601 UTC datetime.")
    db.clock = parsed
    # No entity is mutated: only the clock the server reads from now on.
    return ok({"current_utc": iso(parsed)})
