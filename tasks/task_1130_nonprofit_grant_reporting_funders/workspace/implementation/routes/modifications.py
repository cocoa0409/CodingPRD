"""ModificationRequest endpoints (no-cost extensions and budget reallocations)."""

from flask import request

import services as S
from db import store
from errors import (
    err_below_expended,
    err_extension_not_forward,
    err_invalid_state,
    err_modification_not_pending,
    err_not_balanced,
    err_stale_version,
    err_validation,
)
from middleware import ALL_READ_ROLES, actor, body, check_funder_scope, require_roles
from response import ok, paginate
from util import get_dt, get_enum, get_int, get_str, is_int

REQUEST_TYPES = ("NO_COST_EXTENSION", "BUDGET_REALLOCATION")


def _validate_line_deltas(raw):
    if not isinstance(raw, list):
        raise err_validation("line_deltas must be an array")
    out = []
    for d in raw:
        if not isinstance(d, dict):
            raise err_validation("line_deltas entries must be objects")
        if "budget_line_id" not in d or "delta_cents" not in d:
            raise err_validation("line_deltas entries require budget_line_id and delta_cents")
        if not isinstance(d["budget_line_id"], str):
            raise err_validation("line_deltas.budget_line_id must be a string")
        if not is_int(d["delta_cents"]):
            raise err_validation("line_deltas.delta_cents must be an integer")
        out.append({"budget_line_id": d["budget_line_id"], "delta_cents": d["delta_cents"]})
    return out


def create_mod(grant_id):
    uid, role = actor()
    require_roles(role, {"GrantsOfficer"})
    S.get_grant(grant_id)
    data = body()
    rtype = get_enum(data, "request_type", REQUEST_TYPES)
    justification = get_str(data, "justification")
    requested_end_date = None
    line_deltas = []
    if rtype == "NO_COST_EXTENSION":
        requested_end_date = get_dt(data, "requested_end_date")
    else:
        if "line_deltas" not in data:
            raise err_validation("Missing required field: line_deltas")
        line_deltas = _validate_line_deltas(data["line_deltas"])
    m = S.stamp({
        "grant_id": grant_id,
        "request_type": rtype,
        "justification": justification,
        "requested_end_date": requested_end_date,
        "line_deltas": line_deltas,
        "status": "DRAFT",
        "created_by_user_id": uid,
        "submitted_by_user_id": None,
        "decided_by_funder_id": None,
    })
    store["modification_requests"][m["id"]] = m
    return ok(S.ser_mod(m), code=201)


def list_mods(grant_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    S.get_grant(grant_id)
    items = S.grant_mods(grant_id)
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, meta = paginate(items)
    return ok([S.ser_mod(m) for m in page], pagination=meta)


def submit_mod(mod_id):
    uid, role = actor()
    require_roles(role, {"ProgramDirector"})
    m = S.get_mod(mod_id)
    grant = S.get_grant(m["grant_id"])
    S.require_grant_active(grant)
    if m["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT modification request can be submitted")
    if m["request_type"] == "NO_COST_EXTENSION":
        # Priority 8: temporal rule.
        if not m["requested_end_date"] > grant["end_date"]:
            raise err_extension_not_forward()
    else:
        # Priority 7: deltas must sum to exactly zero.
        if sum(d["delta_cents"] for d in m["line_deltas"]) != 0:
            raise err_not_balanced()
        # Priority 9: adjusted + delta >= expended per line.
        for d in m["line_deltas"]:
            line = store["budget_lines"].get(d["budget_line_id"])
            if line is None or line["grant_id"] != m["grant_id"]:
                raise err_validation("line_deltas reference a budget line of this grant")
            if line["adjusted_cents"] + d["delta_cents"] < line["expended_cents"]:
                raise err_below_expended()
    m["status"] = "SUBMITTED"
    m["submitted_by_user_id"] = uid
    S.touch(m)
    return ok(S.ser_mod(m))


def approve_mod(mod_id):
    uid, role = actor()
    require_roles(role, {"Funder"})
    m = S.get_mod(mod_id)
    grant = S.get_grant(m["grant_id"])
    check_funder_scope(uid, grant)
    if m["status"] != "SUBMITTED":
        raise err_modification_not_pending("Only a SUBMITTED request can be approved")
    data = body()
    expected = data.get("expected_grant_version")
    if expected is None:
        raise err_validation("Missing required field: expected_grant_version")
    if not is_int(expected):
        raise err_validation("expected_grant_version must be an integer")
    if expected != grant["version"]:
        raise err_stale_version()
    # Side effects apply atomically; grant version increments by exactly one.
    if m["request_type"] == "NO_COST_EXTENSION":
        old_end = grant["end_date"]
        grant["end_date"] = m["requested_end_date"]
        S.apply_nce_calendar(grant, old_end, m["requested_end_date"])
    else:
        n = len(S.grant_reports(grant["id"]))
        affected = []
        for d in m["line_deltas"]:
            line = store["budget_lines"].get(d["budget_line_id"])
            if line is None:
                continue
            line["adjusted_cents"] += d["delta_cents"]
            affected.append(line)
        for line in affected:
            S.recompute_proration(line, n)
            S.touch(line)
    m["status"] = "APPROVED"
    m["decided_by_funder_id"] = uid
    S.touch(m)
    S.touch(grant)  # net +1 on the grant version
    return ok(S.ser_mod(m))


def deny_mod(mod_id):
    uid, role = actor()
    require_roles(role, {"Funder"})
    m = S.get_mod(mod_id)
    grant = S.get_grant(m["grant_id"])
    check_funder_scope(uid, grant)
    if m["status"] != "SUBMITTED":
        raise err_modification_not_pending("Only a SUBMITTED request can be denied")
    m["status"] = "DENIED"
    m["decided_by_funder_id"] = uid
    S.touch(m)
    return ok(S.ser_mod(m))


def withdraw_mod(mod_id):
    _, role = actor()
    require_roles(role, {"GrantsOfficer"})
    m = S.get_mod(mod_id)
    if m["status"] not in ("DRAFT", "SUBMITTED"):
        raise err_modification_not_pending("Only a DRAFT or SUBMITTED request can be withdrawn")
    m["status"] = "WITHDRAWN"
    S.touch(m)
    return ok(S.ser_mod(m))


def register(app):
    app.add_url_rule("/grants/<grant_id>/modification-requests", "mods_create", create_mod, methods=["POST"])
    app.add_url_rule("/grants/<grant_id>/modification-requests", "mods_list", list_mods, methods=["GET"])
    app.add_url_rule("/modification-requests/<mod_id>/submit", "mods_submit", submit_mod, methods=["POST"])
    app.add_url_rule("/modification-requests/<mod_id>/approve", "mods_approve", approve_mod, methods=["POST"])
    app.add_url_rule("/modification-requests/<mod_id>/deny", "mods_deny", deny_mod, methods=["POST"])
    app.add_url_rule("/modification-requests/<mod_id>/withdraw", "mods_withdraw", withdraw_mod, methods=["POST"])
