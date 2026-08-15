"""NoContactDirective and DirectiveViolation endpoints (PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_CASE_ALREADY_TERMINAL,
    ERR_DIRECTIVE_WINDOW_OVERLAP, ERR_STALE_CASE_VERSION, ERR_INVALID_REQUEST,
)
from middleware import authorized, check_case_read_access, STAFF_READ_ROLES
from response import success_list, success_object
from services.core import (
    new_record, touch, public, bump_case, append_event, get_case,
    check_case_not_terminal, get_pagination, sort_items, apply_filters,
    recompute_exposure, DIRECTIVE_SIDES, RESTRICTIONS, REPORTED_BY_SIDES,
    TERMINAL_CASE_STATES,
)
from util import clock_iso, parse_datetime
from validate import (
    get_body, req_str, req_enum, req_enum_list, req_datetime, req_int,
    opt_datetime, opt_bool, require_path, as_enum, as_datetime, as_bool, as_int,
)

bp = Blueprint("directives", __name__)

READ_ROLES = STAFF_READ_ROLES + ["Party"]


def _scopes_share(a, b):
    return a == b or a == "MUTUAL" or b == "MUTUAL"


def _windows_overlap(f1, t1, f2, t2):
    """Half-open [from, to) overlap; None `to` is open-ended; adjacency allowed."""
    fs, ts = parse_datetime(f1), parse_datetime(t1) if t1 else None
    fe, te = parse_datetime(f2), parse_datetime(t2) if t2 else None
    if te is not None and fs >= te:
        return False
    if ts is not None and fe >= ts:
        return False
    return True


@bp.post("/cases/<cid>/no-contact-directives")
def create_directive(cid):
    caller = authorized(["TitleIXCoordinator"])
    case = get_case(cid)
    check_case_not_terminal(case)
    body = get_body()

    # Tier 6: window overlap vs ACTIVE directives on a shared scope.
    party_side = as_enum(body, "party_side", DIRECTIVE_SIDES)
    eff_from = as_datetime(body, "effective_from")
    eff_to = as_datetime(body, "effective_to")
    supersede = as_bool(body, "supersede_existing") or False
    overlapping = []
    if party_side and eff_from:
        for d in db["no_contact_directives"].values():
            if d["case_id"] != cid or d["status"] != "ACTIVE":
                continue
            if not _scopes_share(party_side, d["party_side"]):
                continue
            if _windows_overlap(eff_from, eff_to, d["effective_from"], d.get("effective_to")):
                overlapping.append(d)
        if overlapping and not supersede:
            raise_error(ERR_DIRECTIVE_WINDOW_OVERLAP,
                        "directive window overlaps an ACTIVE directive on a shared party scope")

    # Tier 10: OCC on the parent case version (guarded create-with-supersede).
    expected = as_int(body, "expected_case_version")
    if expected is not None and expected != case["version"]:
        raise_error(ERR_STALE_CASE_VERSION,
                    "expected_case_version does not match the case's current version")

    # Tier 11: schema.
    party_side = req_enum(body, "party_side", DIRECTIVE_SIDES)
    restrictions = req_enum_list(body, "restrictions", RESTRICTIONS)
    effective_from = req_datetime(body, "effective_from")
    effective_to = opt_datetime(body, "effective_to")
    supersede_existing = opt_bool(body, "supersede_existing", False)
    if "PROXIMITY" in restrictions:
        proximity_feet = req_int(body, "proximity_feet")
    elif "proximity_feet" in body and body["proximity_feet"] is not None:
        proximity_feet = req_int(body, "proximity_feet")
    else:
        proximity_feet = None
    if body.get("expected_case_version") is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: expected_case_version")
    if not isinstance(body.get("expected_case_version"), int) \
            or isinstance(body.get("expected_case_version"), bool):
        raise_error(ERR_INVALID_REQUEST, "expected_case_version must be an integer")

    rec = new_record("no_contact_directives", {
        "case_id": cid,
        "party_side": party_side,
        "restrictions": restrictions,
        "proximity_feet": proximity_feet,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
        "superseded_by_directive_id": None,
        "substantiated_violation_count": 0,
    })
    append_event(cid, "DIRECTIVE_CREATED", caller,
                 {"directive_id": rec["id"], "party_side": party_side, "status": "ACTIVE"})
    if supersede_existing:
        for d in overlapping:
            d["effective_to"] = effective_from
            d["superseded_by_directive_id"] = rec["id"]
            d["status"] = "SUPERSEDED"
            touch(d)
            append_event(cid, "DIRECTIVE_SUPERSEDED", caller,
                         {"directive_id": d["id"], "superseded_by_directive_id": rec["id"],
                          "status": "SUPERSEDED"}, system=True)
    recompute_exposure(case)
    bump_case(case)
    return success_object(public(rec), 201)


@bp.get("/cases/<cid>/no-contact-directives")
def list_directives(cid):
    caller = authorized(READ_ROLES)
    case = get_case(cid)
    check_case_read_access(caller, case)
    items = [d for d in db["no_contact_directives"].values() if d["case_id"] == cid]
    items = apply_filters(items, {
        "status": request.args.get("status"),
        "party_side": request.args.get("party_side"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/no-contact-directives/<did>")
def get_directive(did):
    caller = authorized(READ_ROLES)
    directive = require_path("no_contact_directives", did)
    case = get_case(directive["case_id"])
    check_case_read_access(caller, case)
    return success_object(public(directive))


@bp.get("/no-contact-directives")
def list_directives_filtered():
    authorized(["TitleIXCoordinator", "CaseAdministrator"])
    items = list(db["no_contact_directives"].values())
    items = apply_filters(items, {
        "superseded_by_directive_id": request.args.get("superseded_by_directive_id"),
        "status": request.args.get("status"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.post("/no-contact-directives/<did>/lift")
def lift_directive(did):
    caller = authorized(["TitleIXCoordinator"])
    directive = require_path("no_contact_directives", did)
    if directive["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"directive is {directive['status']}, not ACTIVE")
    case = get_case(directive["case_id"])
    directive["status"] = "LIFTED"
    touch(directive)
    append_event(directive["case_id"], "DIRECTIVE_LIFTED", caller,
                 {"directive_id": did, "status": "LIFTED"})
    recompute_exposure(case)
    bump_case(case)
    return success_object(public(directive))


# ---------------------------------------------------------------------------
# DirectiveViolation
# ---------------------------------------------------------------------------

@bp.post("/no-contact-directives/<did>/violations")
def report_violation(did):
    caller = authorized(["TitleIXCoordinator", "Party"])
    directive = require_path("no_contact_directives", did)
    body = get_body()
    reported_by_side = req_enum(body, "reported_by_side", REPORTED_BY_SIDES)
    occurred_at = req_datetime(body, "occurred_at")
    description = req_str(body, "description")
    rec = new_record("directive_violations", {
        "directive_id": did,
        "reported_by_side": reported_by_side,
        "occurred_at": occurred_at,
        "description": description,
        "status": "PENDING",
        "substantiated_at": None,
    })
    append_event(directive["case_id"], "VIOLATION_REPORTED", caller,
                 {"violation_id": rec["id"], "directive_id": did, "status": "PENDING"})
    return success_object(public(rec), 201)


@bp.get("/no-contact-directives/<did>/violations")
def list_violations(did):
    caller = authorized(READ_ROLES)
    directive = require_path("no_contact_directives", did)
    case = get_case(directive["case_id"])
    check_case_read_access(caller, case)
    items = [v for v in db["directive_violations"].values() if v["directive_id"] == did]
    items = apply_filters(items, {"status": request.args.get("status")})
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/directive-violations/<vid>")
def get_violation(vid):
    caller = authorized(READ_ROLES)
    violation = require_path("directive_violations", vid)
    directive = require_path("no_contact_directives", violation["directive_id"])
    case = get_case(directive["case_id"])
    check_case_read_access(caller, case)
    return success_object(public(violation))


def _violation_case(violation):
    directive = db["no_contact_directives"].get(violation["directive_id"])
    return get_case(directive["case_id"]) if directive else None


@bp.post("/directive-violations/<vid>/substantiate")
def substantiate_violation(vid):
    caller = authorized(["TitleIXCoordinator"])
    violation = require_path("directive_violations", vid)
    if violation["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"violation is {violation['status']}, not PENDING")
    case = _violation_case(violation)
    if case["status"] in TERMINAL_CASE_STATES:
        raise_error(ERR_CASE_ALREADY_TERMINAL,
                    f"case is in terminal state {case['status']}")
    directive = db["no_contact_directives"].get(violation["directive_id"])
    violation["status"] = "SUBSTANTIATED"
    violation["substantiated_at"] = clock_iso()
    touch(violation)
    if directive is not None:
        directive["substantiated_violation_count"] += 1
        touch(directive)
    recompute_exposure(case)
    bump_case(case)
    append_event(case["id"], "VIOLATION_SUBSTANTIATED", caller,
                 {"violation_id": vid, "status": "SUBSTANTIATED"})
    return success_object(public(violation))


@bp.post("/directive-violations/<vid>/mark-unsubstantiated")
def mark_unsubstantiated(vid):
    caller = authorized(["TitleIXCoordinator"])
    violation = require_path("directive_violations", vid)
    if violation["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"violation is {violation['status']}, not PENDING")
    case = _violation_case(violation)
    if case["status"] in TERMINAL_CASE_STATES:
        raise_error(ERR_CASE_ALREADY_TERMINAL,
                    f"case is in terminal state {case['status']}")
    violation["status"] = "UNSUBSTANTIATED"
    touch(violation)
    bump_case(case)
    append_event(case["id"], "VIOLATION_UNSUBSTANTIATED", caller,
                 {"violation_id": vid, "status": "UNSUBSTANTIATED"})
    return success_object(public(violation))
