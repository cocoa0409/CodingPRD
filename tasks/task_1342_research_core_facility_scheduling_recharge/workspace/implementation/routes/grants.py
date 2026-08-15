"""Grants (PRD §3.4)."""

from flask import Blueprint, request

from auth import authenticate, require_roles, auth_role, auth_id
from errors import fail
from helpers import (
    Body, validate_body, non_empty_str, is_int, date_ok, parse_date,
    grant_status, grant_ledger, grant_authorized, ser_grant,
)
from store import store
from util import new_entity, ok_object, parse_pagination, paginate, sort_default, touch

bp = Blueprint("grants", __name__)


def get_grant_or_404(gid):
    g = store.grants.get(gid)
    if g is None:
        fail("ERR_NOT_FOUND", "Grant not found")
    return g


def _researcher_can_see(grant, uid):
    return grant["pi_user_id"] == uid or uid in (grant.get("authorized_user_ids") or [])


@bp.route("/grants", methods=["POST"])
def create_grant():
    authenticate()
    require_roles("FinanceOfficer")
    body = Body(request.get_json(silent=True))
    # Priority 4 — body FK existence
    pi = body.get("pi_user_id")
    if pi is not None and pi not in store.users:
        fail("ERR_NOT_FOUND", "pi_user_id does not reference an existing user")
    aus = body.get("authorized_user_ids")
    if isinstance(aus, list):
        for u in aus:
            if u not in store.users:
                fail("ERR_NOT_FOUND", "authorized_user_ids references a missing user")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"grant_code", "pi_user_id", "title", "budget_total_cents",
                 "start_date", "end_date", "authorized_user_ids"},
        required={"grant_code", "pi_user_id", "title", "budget_total_cents", "start_date", "end_date"},
        checkers={
            "grant_code": non_empty_str,
            "pi_user_id": lambda v: isinstance(v, str),
            "title": lambda v: isinstance(v, str),
            "budget_total_cents": lambda v: is_int(v) and v > 0,
            "start_date": date_ok,
            "end_date": date_ok,
            "authorized_user_ids": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
        },
    )
    sd = parse_date(body.get("start_date"))
    ed = parse_date(body.get("end_date"))
    if ed < sd:
        fail("ERR_INVALID_REQUEST", "end_date must be on or after start_date")
    # Priority 22 — unique grant_code
    for g in store.grants.values():
        if g["grant_code"] == body.get("grant_code"):
            fail("ERR_UNIQUE_CONSTRAINT", "A grant with this grant_code already exists")
    grant = new_entity({
        "grant_code": body.get("grant_code"),
        "pi_user_id": pi,
        "title": body.get("title"),
        "budget_total_cents": body.get("budget_total_cents"),
        "authorized_user_ids": list(aus) if isinstance(aus, list) else [],
        "start_date": body.get("start_date"),
        "end_date": body.get("end_date"),
        "_start_date": sd,
        "_end_date": ed,
        "_closed": False,
    })
    store.grants[grant["id"]] = grant
    return ok_object(ser_grant(grant), status=201)


@bp.route("/grants", methods=["GET"])
def list_grants():
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher")
    limit, offset = parse_pagination(request.args)
    items = list(store.grants.values())
    if auth_role() == "Researcher":
        items = [g for g in items if _researcher_can_see(g, auth_id())]
    else:
        pi = request.args.get("pi_user_id")
        if pi is not None:
            items = [g for g in items if g["pi_user_id"] == pi]
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if grant_status(g) == status]
    return paginate(sort_default(items), limit, offset, ser_grant)


@bp.route("/grants/<gid>", methods=["GET"])
def get_grant(gid):
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher")
    grant = get_grant_or_404(gid)
    if auth_role() == "Researcher" and not _researcher_can_see(grant, auth_id()):
        fail("ERR_FORBIDDEN", "Researchers may only read grants they own or are authorized on")
    return ok_object(ser_grant(grant))


@bp.route("/grants/<gid>", methods=["PUT"])
def amend_grant(gid):
    authenticate()
    require_roles("FinanceOfficer")
    grant = get_grant_or_404(gid)
    body = Body(request.get_json(silent=True))
    # Priority 5 — OCC on expected_grant_version
    expected = body.get("expected_grant_version")
    if expected is not None and is_int(expected) and expected != grant["version"]:
        fail("ERR_STALE_VERSION", "expected_grant_version does not match the grant's current version")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"expected_grant_version", "budget_total_cents", "start_date", "end_date",
                 "authorized_user_ids"},
        required={"expected_grant_version"},
        checkers={
            "expected_grant_version": is_int,
            "budget_total_cents": lambda v: is_int(v) and v > 0,
            "start_date": date_ok,
            "end_date": date_ok,
            "authorized_user_ids": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
        },
    )
    # FK existence for any new authorized_user_ids
    if body.has("authorized_user_ids"):
        for u in body.get("authorized_user_ids"):
            if u not in store.users:
                fail("ERR_NOT_FOUND", "authorized_user_ids references a missing user")
    # Apply window changes tentatively for the range check
    sd = parse_date(body.get("start_date")) if body.has("start_date") else grant["_start_date"]
    ed = parse_date(body.get("end_date")) if body.has("end_date") else grant["_end_date"]
    if ed < sd:
        fail("ERR_INVALID_REQUEST", "end_date must be on or after start_date")
    # Priority 35 — budget may not drop below encumbered + used
    if body.has("budget_total_cents"):
        enc, used, _ = grant_ledger(grant)
        if body.get("budget_total_cents") < enc + used:
            fail("ERR_GRANT_BUDGET_EXCEEDED",
                 "budget_total_cents may not be lowered below encumbered + used")
    if body.has("budget_total_cents"):
        grant["budget_total_cents"] = body.get("budget_total_cents")
    if body.has("start_date"):
        grant["start_date"] = body.get("start_date")
        grant["_start_date"] = sd
    if body.has("end_date"):
        grant["end_date"] = body.get("end_date")
        grant["_end_date"] = ed
    if body.has("authorized_user_ids"):
        grant["authorized_user_ids"] = list(body.get("authorized_user_ids"))
    touch(grant)
    return ok_object(ser_grant(grant))


@bp.route("/grants/<gid>/close", methods=["POST"])
def close_grant(gid):
    authenticate()
    require_roles("FinanceOfficer")
    grant = get_grant_or_404(gid)
    # Priority 6 — state legality: CLOSED is terminal
    if grant.get("_closed"):
        fail("ERR_INVALID_STATE", "Grant is already CLOSED")
    # Priority 9 — no PENDING/BILLED/DISPUTED entries on the grant
    for e in store.entries.values():
        if e.get("grant_id") == gid and e["status"] in ("PENDING", "BILLED", "DISPUTED"):
            fail("ERR_GRANT_HAS_OPEN_ENTRIES", "Grant has entries in PENDING/BILLED/DISPUTED")
    grant["_closed"] = True
    touch(grant)
    return ok_object(ser_grant(grant))
