"""Case assignments: creation, lifecycle, supervision relinking and hours."""

from flask import Blueprint, request

import auth
import calc
import cascades
import response
import serialize
import store
import validation as v
from errors import ApiError

bp = Blueprint("staffing", __name__)

RELEASE_REASONS = ("CLIENT_WITHDREW", "MATTER_CLOSED", "RECOGNITION_LAPSE",
                   "CASELOAD_REBALANCE", "AUTHORIZATION_REVOKED",
                   "SUPERSEDED_BY_NEW_LEAD", "VOLUNTEER_UNAVAILABLE")
LEAD_HOLD_STATUSES = ("PROPOSED", "ACTIVE", "SUSPENDED")
UNAUTHORIZED = ("AUTHORIZATION_SUSPENDED", "UNAUTHORIZED")


def _resolve_supervision(matter, rep, link_id, client):
    """Returns (supervision_link_id, supervision_source)."""
    if not calc.supervision_required(rep):
        return None, "NOT_REQUIRED"
    if link_id is not None:
        link = store.get("assignments", link_id)
        if not calc.supervisor_link_eligible(link, matter, client):
            raise ApiError("ERR_SUPERVISION_LINK_INELIGIBLE",
                           "The named supervision link fails the selection predicate.")
        return link_id, "EXPLICIT_LINK"
    candidates = calc.supervisor_candidates(matter, client)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_SUPERVISOR",
                       "No eligible supervisor assignment is available on this matter.")
    return candidates[0][0]["id"], "AUTO_SELECTED"


@bp.post("/case-assignments")
@auth.requires("SupervisingAttorney", "ProgramDirector")
def create_assignment():
    payload = v.body()
    matter_id = v.as_id(payload, "matter_id")
    rep_id = v.as_id(payload, "representative_id")
    link_id = v.as_id(payload, "supervision_link_id", required=False, default=None)
    matter = store.get("matters", matter_id)
    if matter is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    rep = store.get("representatives", rep_id)
    if rep is None:
        raise ApiError("ERR_REPRESENTATIVE_NOT_FOUND")
    if link_id is not None and store.get("assignments", link_id) is None:
        raise ApiError("ERR_SUPERVISION_LINK_NOT_FOUND")
    if rep.get("rep_type") == "ACCREDITED_REP" and not store.db["recognitions"]:
        raise ApiError("ERR_RECOGNITION_NOT_FOUND",
                       "No organization recognition row exists.")
    role_on_case = v.as_enum(payload, "role_on_case", calc.ASSIGNMENT_ROLES)
    expected = v.as_int(payload, "expected_matter_version")
    if matter.get("representation_status") == "WITHDRAWN_FROM":
        raise ApiError("ERR_MATTER_CLOSED", "The matter is closed.")
    client = store.get("clients", matter.get("client_id"))
    if client is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND")
    resolved_link, source = _resolve_supervision(matter, rep, link_id, client)
    if role_on_case == "LEAD":
        for existing in calc.matter_assignments(matter_id):
            if (existing.get("role_on_case") == "LEAD"
                    and existing.get("status") in LEAD_HOLD_STATUSES):
                raise ApiError("ERR_LEAD_ALREADY_ASSIGNED",
                               "The matter already carries a LEAD assignment.")
    if int(matter["version"]) != expected:
        raise ApiError("ERR_STALE_MATTER_VERSION",
                       "expected_matter_version does not match the matter.")
    row = store.new_row({
        "matter_id": matter_id,
        "representative_id": rep_id,
        "supervision_link_id": resolved_link,
        "role_on_case": role_on_case,
        "status": "PROPOSED",
        "supervision_source": source,
        "direct_hours_logged": store.rhu(0, 2),
        "supervision_hours_logged": store.rhu(0, 2),
        "assigned_at_utc": store.clock_iso(),
        "activated_at_utc": None,
        "released_at_utc": None,
        "release_reason_code": None,
    })
    store.insert("assignments", row)
    store.touch(matter)
    return response.created(serialize.assignment(row))


@bp.get("/case-assignments")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney",
               "CaseRepresentative", "GrantAnalyst")
def list_assignments():
    rows = store.rows("assignments")
    args = request.args
    for key in ("matter_id", "representative_id", "supervision_link_id",
                "role_on_case", "status"):
        if args.get(key):
            rows = [r for r in rows if r.get(key) == args[key]]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.assignment(r) for r in page], meta)


@bp.get("/case-assignments/<assignment_id>")
@auth.requires("ProgramDirector", "SupervisingAttorney", "CaseRepresentative",
               scoped=True)
def read_assignment(assignment_id):
    row = store.get("assignments", assignment_id)
    auth.scope_matter(row.get("matter_id") if row else None)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The case assignment does not exist.")
    return response.ok(serialize.assignment(row))


def _touch_matter_status(matter):
    calc.recompute_representation_status(matter, bump=False)
    store.touch(matter)


def _reason(payload, required):
    reason = v.as_enum(payload, "release_reason_code", RELEASE_REASONS,
                       required=False, default=None)
    if required and reason is None:
        v.bad("release_reason_code is required for this actor.")
    return reason


def _activate(row, matter, rep, payload):
    if rep.get("status") != "ACTIVE" or calc.authorization_status(rep) in UNAUTHORIZED:
        raise ApiError("ERR_REPRESENTATIVE_INACTIVE",
                       "The representative is not active or not authorized.")
    if (row.get("role_on_case") == "LEAD"
            and matter.get("forum") in calc.ATTORNEY_FORUMS):
        if not calc.rep_authorized_for_forum(rep, matter["forum"]):
            raise ApiError("ERR_FORUM_NOT_AUTHORIZED",
                           "The representative may not lead a %s case."
                           % matter["forum"])
    supervisor = None
    if calc.supervision_required(rep):
        link = store.get("assignments", row.get("supervision_link_id"))
        client = store.get("clients", matter.get("client_id"))
        if (link is None or link.get("matter_id") != matter["id"]
                or link.get("status") != "ACTIVE"
                or link.get("role_on_case") != "SUPERVISOR"):
            raise ApiError("ERR_SUPERVISEE_CAP_EXCEEDED",
                           "No resolvable ACTIVE supervisor link for this assignment.")
        supervisor = store.get("representatives", link.get("representative_id"))
        if supervisor is None or (int(supervisor.get("supervisee_count") or 0)
                                 >= int(supervisor.get("max_supervisees") or 0)):
            raise ApiError("ERR_SUPERVISEE_CAP_EXCEEDED",
                           "The supervisor is at its supervisee ceiling.")
        if client is None:
            raise ApiError("ERR_CLIENT_NOT_FOUND")
    if row.get("role_on_case") in calc.CASELOAD_ROLES:
        if int(rep.get("active_case_load") or 0) >= int(rep.get("max_case_load") or 0):
            raise ApiError("ERR_CASELOAD_CAP_EXCEEDED",
                           "The representative is at its caseload ceiling.")
    cycle = store.get("cycles", matter.get("cycle_id"))
    if cycle is not None and calc.effective_posture(cycle) == "FROZEN":
        raise ApiError("ERR_CYCLE_CAPACITY_FROZEN",
                       "The cycle capacity posture is FROZEN.")
    row["status"] = "ACTIVE"
    row["activated_at_utc"] = store.clock_iso()
    row["release_reason_code"] = None
    store.touch(row)
    if row.get("role_on_case") == "LEAD":
        for other in calc.matter_assignments(matter["id"]):
            if other["id"] == row["id"]:
                continue
            if other.get("role_on_case") != "LEAD":
                continue
            if other.get("status") not in LEAD_HOLD_STATUSES:
                continue
            cascades.release_assignment(other, "SUPERSEDED_BY_NEW_LEAD", terminal=True)
            other_rep = store.get("representatives", other.get("representative_id"))
            if other_rep is not None and other_rep["id"] != rep["id"]:
                calc.recompute_rep_counters(other_rep)
    calc.recompute_rep_counters(rep, bump=False)
    store.touch(rep)
    if supervisor is not None and supervisor["id"] != rep["id"]:
        calc.recompute_rep_counters(supervisor)
    _touch_matter_status(matter)


@bp.post("/case-assignments/<assignment_id>/transition")
@auth.requires("SupervisingAttorney", "ProgramDirector")
def transition_assignment(assignment_id):
    row = store.get("assignments", assignment_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The case assignment does not exist.")
    payload = v.body()
    action = v.as_enum(payload, "action", ("ACTIVATE", "SUSPEND", "RELEASE"))
    matter = store.get("matters", row["matter_id"])
    if matter is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    rep = store.get("representatives", row["representative_id"])
    if rep is None:
        raise ApiError("ERR_REPRESENTATIVE_NOT_FOUND")
    status = row["status"]
    needs_reason = auth.role() == "SupervisingAttorney"

    if action == "ACTIVATE":
        if status not in ("PROPOSED", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "ACTIVATE is only legal from PROPOSED or SUSPENDED.")
        if matter.get("representation_status") == "WITHDRAWN_FROM":
            raise ApiError("ERR_MATTER_CLOSED", "The matter is closed.")
        _activate(row, matter, rep, payload)
    elif action == "SUSPEND":
        if status != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "SUSPEND is only legal from ACTIVE.")
        reason = _reason(payload, needs_reason)
        cascades.release_assignment(row, reason, terminal=False)
        calc.recompute_rep_counters(rep, bump=False)
        store.touch(rep)
        for supervisor_id in cascades.supervisor_rep_ids(row):
            supervisor = store.get("representatives", supervisor_id)
            if supervisor is not None and supervisor["id"] != rep["id"]:
                calc.recompute_rep_counters(supervisor)
        _touch_matter_status(matter)
    else:
        if status == "RELEASED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The assignment is already RELEASED.")
        reason = _reason(payload, needs_reason)
        if row.get("role_on_case") == "SUPERVISOR":
            for other in store.rows("assignments"):
                if other.get("supervision_link_id") != row["id"]:
                    continue
                if other.get("status") in ("PROPOSED", "ACTIVE"):
                    raise ApiError("ERR_INVALID_STATE_TRANSITION",
                                   "Supervisees must be relinked or released first.")
        cascades.release_assignment(row, reason, terminal=True)
        calc.recompute_rep_counters(rep, bump=False)
        store.touch(rep)
        for supervisor_id in cascades.supervisor_rep_ids(row):
            supervisor = store.get("representatives", supervisor_id)
            if supervisor is not None and supervisor["id"] != rep["id"]:
                calc.recompute_rep_counters(supervisor)
        _touch_matter_status(matter)
    return response.ok(serialize.assignment(row))


@bp.post("/case-assignments/<assignment_id>/relink-supervision")
@auth.requires("SupervisingAttorney", "ProgramDirector")
def relink_supervision(assignment_id):
    row = store.get("assignments", assignment_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The case assignment does not exist.")
    payload = v.body()
    link_id = v.as_id(payload, "supervision_link_id")
    link = store.get("assignments", link_id)
    if link is None:
        raise ApiError("ERR_SUPERVISION_LINK_NOT_FOUND")
    matter = store.get("matters", row["matter_id"])
    if matter is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    if matter.get("representation_status") == "WITHDRAWN_FROM":
        raise ApiError("ERR_MATTER_CLOSED", "The matter is closed.")
    if row.get("status") != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE",
                       "Relinking requires an ACTIVE assignment.")
    client = store.get("clients", matter.get("client_id"))
    if client is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND")
    if not calc.supervisor_link_eligible(link, matter, client):
        raise ApiError("ERR_SUPERVISION_LINK_INELIGIBLE",
                       "The named supervision link fails the selection predicate.")
    previous_ids = cascades.supervisor_rep_ids(row)
    row["supervision_link_id"] = link_id
    row["supervision_source"] = "EXPLICIT_LINK"
    store.touch(row)
    new_supervisor = store.get("representatives", link.get("representative_id"))
    for previous_id in previous_ids:
        previous = store.get("representatives", previous_id)
        if previous is not None:
            calc.recompute_rep_counters(previous, bump=False)
            store.touch(previous)
    if new_supervisor is not None and new_supervisor["id"] not in previous_ids:
        calc.recompute_rep_counters(new_supervisor, bump=False)
        store.touch(new_supervisor)
    return response.ok(serialize.assignment(row))


@bp.post("/case-assignments/<assignment_id>/log-hours")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def log_hours(assignment_id):
    row = store.get("assignments", assignment_id)
    auth.scope_matter(row.get("matter_id") if row else None)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The case assignment does not exist.")
    payload = v.body()
    hours = v.as_decimal(payload, "hours", places=2)
    kind = v.as_enum(payload, "hours_kind", ("DIRECT", "SUPERVISION"))
    v.as_date(payload, "service_date")
    matter = store.get("matters", row["matter_id"])
    if matter is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    if matter.get("representation_status") == "WITHDRAWN_FROM":
        raise ApiError("ERR_MATTER_CLOSED", "The matter is closed.")
    if row.get("status") != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE",
                       "Hours may only be logged against an ACTIVE assignment.")
    if hours <= 0 or hours > calc.MAX_HOURS_PER_ENTRY:
        raise ApiError("ERR_HOURS_OUT_OF_RANGE",
                       "hours must be greater than 0.00 and at most 12.00.")
    role_on_case = row.get("role_on_case")
    if kind == "SUPERVISION" and role_on_case != "SUPERVISOR":
        raise ApiError("ERR_HOURS_OUT_OF_RANGE",
                       "SUPERVISION hours require a SUPERVISOR assignment.")
    if kind == "DIRECT" and role_on_case not in calc.DIRECT_HOURS_ROLES:
        raise ApiError("ERR_HOURS_OUT_OF_RANGE",
                       "DIRECT hours require a LEAD, CO_COUNSEL or "
                       "INTERPRETER_COORDINATOR assignment.")
    field = "direct_hours_logged" if kind == "DIRECT" else "supervision_hours_logged"
    row[field] = store.rhu(store.dec(row.get(field) or 0) + hours, 2)
    store.touch(row)
    calc.recompute_matter_hours(matter, bump=False)
    store.touch(matter)
    return response.ok(serialize.assignment(row))
