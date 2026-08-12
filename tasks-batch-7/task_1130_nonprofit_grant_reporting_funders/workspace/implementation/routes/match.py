"""MatchContribution endpoints."""

from flask import request

import services as S
from db import store
from errors import err_invalid_state, err_segregation
from middleware import ALL_READ_ROLES, actor, body, require_roles
from response import ok, paginate
from util import get_enum, get_int, get_nonempty_str, get_num, get_str, round_half_up_int, to_dec

CONTRIBUTION_TYPES = ("CASH", "IN_KIND_GOODS", "IN_KIND_SERVICES", "VOLUNTEER_TIME")
VALUATION_BASES = ("FAIR_MARKET", "ACTUAL_COST", "STANDARD_RATE")


def _recognized(contribution_type, documented_value_cents, volunteer_hours):
    if contribution_type == "VOLUNTEER_TIME":
        return round_half_up_int(to_dec(volunteer_hours) * S.STANDARD_VOLUNTEER_RATE_CENTS)
    return documented_value_cents


def create_match(grant_id):
    _, role = actor()
    require_roles(role, {"GrantsOfficer"})
    grant = S.get_grant(grant_id)
    S.require_grant_active(grant)
    data = body()
    ctype = get_enum(data, "contribution_type", CONTRIBUTION_TYPES)
    doc_val = get_int(data, "documented_value_cents", required=False, default=0, min_v=0)
    hours = get_num(data, "volunteer_hours", required=False, default=0, min_v=0)
    m = S.stamp({
        "grant_id": grant_id,
        "source_name": get_str(data, "source_name"),
        "contribution_type": ctype,
        "valuation_basis": get_enum(data, "valuation_basis", VALUATION_BASES),
        "documented_value_cents": doc_val,
        "volunteer_hours": hours,
        "recognized_value_cents": _recognized(ctype, doc_val, hours),
        "status": "PLEDGED",
        "documented_by_user_id": None,
        "verified_by_user_id": None,
    })
    store["match_contributions"][m["id"]] = m
    return ok(S.ser_match(m), code=201)


def list_matches(grant_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    S.get_grant(grant_id)
    items = S.grant_matches(grant_id)
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, meta = paginate(items)
    return ok([S.ser_match(m) for m in page], pagination=meta)


def document_match(match_id):
    uid, role = actor()
    require_roles(role, {"GrantsOfficer"})
    m = S.get_match(match_id)
    grant = S.get_grant(m["grant_id"])
    S.require_grant_active(grant)
    if m["status"] != "PLEDGED":
        raise err_invalid_state("Only a PLEDGED contribution can be documented")
    data = body()
    get_nonempty_str(data, "documentation_ref")
    m["status"] = "DOCUMENTED"
    m["documented_by_user_id"] = uid
    S.touch(m)
    return ok(S.ser_match(m))


def verify_match(match_id):
    uid, role = actor()
    require_roles(role, {"FinanceManager"})
    m = S.get_match(match_id)
    # Segregation of duties (priority 4) precedes state checks (priority 5).
    if m["documented_by_user_id"] is not None and uid == m["documented_by_user_id"]:
        raise err_segregation("Match verifier must differ from match documenter")
    if m["status"] != "DOCUMENTED":
        raise err_invalid_state("Only a DOCUMENTED contribution can be verified")
    m["status"] = "VERIFIED"
    m["verified_by_user_id"] = uid
    S.touch(m)
    return ok(S.ser_match(m))


def register(app):
    app.add_url_rule("/grants/<grant_id>/match-contributions", "match_create", create_match, methods=["POST"])
    app.add_url_rule("/grants/<grant_id>/match-contributions", "match_list", list_matches, methods=["GET"])
    app.add_url_rule("/match-contributions/<match_id>/document", "match_document", document_match, methods=["POST"])
    app.add_url_rule("/match-contributions/<match_id>/verify", "match_verify", verify_match, methods=["POST"])
