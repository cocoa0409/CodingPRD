"""Agency, Agent, Author, Editor endpoints."""
from flask import Blueprint

from core import (DB, F, ERR_BODY, ERR_STATE, acting_agency, fail, get_ref,
                  get_scoped, guard, list_response, new_record, parse_body,
                  public, success, touch)
from domain import refresh_posture

bp = Blueprint("roster", __name__)

ALL = ("AgencyAdmin", "Agent", "ContractsManager", "RoyaltiesAccountant")


def _email_taken(coll, agency_id, email):
    return any(r for r in DB[coll].values()
               if r["agency_id"] == agency_id and r["email"] == email)


# ---------------------------------------------------------------- agencies ----
@bp.route("/agencies", methods=["POST"])
def create_agency():
    guard("AgencyAdmin")
    data = parse_body([
        F("name", "str", required=True),
        F("commission_pct", "num", required=True, lo=0),
        F("slush_capacity", "int", required=True, lo=0),
    ])
    rec = new_record()
    rec.update({
        "name": data["name"],
        "commission_pct": data["commission_pct"],
        "slush_capacity": data["slush_capacity"],
        "period_index": 0,
        "books_closed_through_period_index": None,
        "posture": "NORMAL",
    })
    DB["agencies"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/agencies/<agencyId>", methods=["GET"])
def get_agency(agencyId):
    ctx = guard(*ALL)
    return success(public(get_scoped("agencies", agencyId, ctx)))


@bp.route("/agencies/<agencyId>/close-period", methods=["POST"])
def close_period(agencyId):
    ctx = guard("AgencyAdmin", "RoyaltiesAccountant")
    parse_body([])
    agency = get_scoped("agencies", agencyId, ctx)
    agency["period_index"] += 1
    touch(agency)
    period = agency["period_index"]
    # Lapse sweep: completed period is N = period - 1; lapse queries whose
    # requested_period_index <= N - 1 while the manuscript is still early.
    for q in list(DB["query_letters"].values()):
        if (q["agency_id"] != agencyId or q["status"] != "REQUESTED"
                or q["requested_period_index"] is None
                or q["requested_period_index"] > period - 2):
            continue
        ms = next((m for m in DB["manuscripts"].values()
                   if m["query_letter_id"] == q["id"]), None)
        if ms is None or ms["status"] not in ("SUBMITTED", "READER_ASSIGNED"):
            continue
        q["status"] = "LAPSED"
        touch(q)
        ms["status"] = "DECLINED"
        touch(ms)
    # Installment due/late sweep (one transition per installment per close).
    for inst in DB["advance_installments"].values():
        if inst["agency_id"] != agencyId:
            continue
        status = inst["status"]
        if status == "SCHEDULED" and period >= inst["due_period_index"]:
            inst["status"] = "DUE"
            touch(inst)
        elif status == "DUE" and period > inst["due_period_index"]:
            inst["status"] = "LATE"
            touch(inst)
    # Deal activation backstop.
    for deal in DB["deals"].values():
        if deal["agency_id"] != agencyId or deal["status"] != "EXECUTED":
            continue
        if any(i for i in DB["advance_installments"].values()
               if i["deal_id"] == deal["id"] and i["status"] == "PAID"):
            deal["status"] = "ACTIVE"
            touch(deal)
    refresh_posture(agency)
    return success(public(agency))


@bp.route("/agencies/<agencyId>/close-books", methods=["POST"])
def close_books(agencyId):
    ctx = guard("AgencyAdmin", "RoyaltiesAccountant")
    parse_body([])
    agency = get_scoped("agencies", agencyId, ctx)
    if agency["period_index"] == 0:
        fail(ERR_STATE, 409, "no completed period to close")
    agency["books_closed_through_period_index"] = agency["period_index"] - 1
    touch(agency)
    return success(public(agency))


# ------------------------------------------------------------------ agents ----
@bp.route("/agents", methods=["POST"])
def create_agent():
    guard("AgencyAdmin")
    data = parse_body([
        F("agency_id", "str", required=True),
        F("display_name", "str", required=True),
        F("email", "str", required=True),
    ])
    get_ref("agencies", data["agency_id"], None)
    if _email_taken("agents", data["agency_id"], data["email"]):
        fail(ERR_BODY, 400, "email already exists within agency")
    rec = new_record()
    rec.update({
        "agency_id": data["agency_id"],
        "display_name": data["display_name"],
        "email": data["email"],
        "status": "ACTIVE",
        "open_query_count": 0,
    })
    DB["agents"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/agents/<agentId>", methods=["GET"])
def get_agent(agentId):
    ctx = guard(*ALL)
    return success(public(get_scoped("agents", agentId, ctx)))


@bp.route("/agents", methods=["GET"])
def list_agents():
    ctx = guard(*ALL)
    return list_response("agents", ctx, {"agency_id": "str", "status": "str"})


@bp.route("/agents/<agentId>/deactivate", methods=["POST"])
def deactivate_agent(agentId):
    ctx = guard("AgencyAdmin")
    parse_body([])
    agent = get_scoped("agents", agentId, ctx)
    if agent["status"] != "ACTIVE":
        fail(ERR_STATE, 409, "agent is not ACTIVE")
    agent["status"] = "INACTIVE"
    touch(agent)
    return success(public(agent))


@bp.route("/agents/<agentId>/activate", methods=["POST"])
def activate_agent(agentId):
    ctx = guard("AgencyAdmin")
    parse_body([])
    agent = get_scoped("agents", agentId, ctx)
    if agent["status"] != "INACTIVE":
        fail(ERR_STATE, 409, "agent is not INACTIVE")
    agent["status"] = "ACTIVE"
    touch(agent)
    return success(public(agent))


# ----------------------------------------------------------------- authors ----
@bp.route("/authors", methods=["POST"])
def create_author():
    ctx = guard("AgencyAdmin", "Agent")
    data = parse_body([
        F("agency_id", "str", required=True),
        F("display_name", "str", required=True),
        F("email", "str", required=True),
    ])
    scope = acting_agency(ctx) if ctx.role == "Agent" else None
    get_ref("agencies", data["agency_id"], scope)
    if _email_taken("authors", data["agency_id"], data["email"]):
        fail(ERR_BODY, 400, "email already exists within agency")
    rec = new_record()
    rec.update({
        "agency_id": data["agency_id"],
        "display_name": data["display_name"],
        "email": data["email"],
        "status": "PROSPECT",
    })
    DB["authors"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/authors/<authorId>", methods=["GET"])
def get_author(authorId):
    ctx = guard(*ALL)
    return success(public(get_scoped("authors", authorId, ctx)))


@bp.route("/authors", methods=["GET"])
def list_authors():
    ctx = guard(*ALL)
    return list_response("authors", ctx, {"agency_id": "str", "status": "str"})


# ----------------------------------------------------------------- editors ----
@bp.route("/editors", methods=["POST"])
def create_editor():
    ctx = guard("AgencyAdmin", "Agent")
    data = parse_body([
        F("agency_id", "str", required=True),
        F("display_name", "str", required=True),
        F("imprint", "str", required=True),
        F("email", "str", required=True),
    ])
    scope = acting_agency(ctx) if ctx.role == "Agent" else None
    get_ref("agencies", data["agency_id"], scope)
    if _email_taken("editors", data["agency_id"], data["email"]):
        fail(ERR_BODY, 400, "email already exists within agency")
    rec = new_record()
    rec.update({
        "agency_id": data["agency_id"],
        "display_name": data["display_name"],
        "imprint": data["imprint"],
        "email": data["email"],
        "status": "ACTIVE",
    })
    DB["editors"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/editors/<editorId>", methods=["GET"])
def get_editor(editorId):
    ctx = guard(*ALL)
    return success(public(get_scoped("editors", editorId, ctx)))


@bp.route("/editors", methods=["GET"])
def list_editors():
    ctx = guard(*ALL)
    return list_response("editors", ctx, {"agency_id": "str", "status": "str"})


@bp.route("/editors/<editorId>/deactivate", methods=["POST"])
def deactivate_editor(editorId):
    ctx = guard("AgencyAdmin")
    parse_body([])
    editor = get_scoped("editors", editorId, ctx)
    if editor["status"] != "ACTIVE":
        fail(ERR_STATE, 409, "editor is not ACTIVE")
    editor["status"] = "INACTIVE"
    touch(editor)
    return success(public(editor))


@bp.route("/editors/<editorId>/activate", methods=["POST"])
def activate_editor(editorId):
    ctx = guard("AgencyAdmin")
    parse_body([])
    editor = get_scoped("editors", editorId, ctx)
    if editor["status"] != "INACTIVE":
        fail(ERR_STATE, 409, "editor is not INACTIVE")
    editor["status"] = "ACTIVE"
    touch(editor)
    return success(public(editor))
