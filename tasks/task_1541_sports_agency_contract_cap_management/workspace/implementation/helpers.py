"""Shared request-handling helpers: auth, body validation, pagination,
common entity fields, and scoped path resolvers (left-to-right per PRD 2.7)."""

import uuid
from datetime import datetime, timezone

import db
from errors import (
    err_unauthenticated, err_forbidden, err_not_found, err_invalid_request,
)
from response import format_ts

ROLES = {"LeagueOfficer", "AgencyManager", "Agent", "Team", "Player"}
ALL_ROLES = ["LeagueOfficer", "AgencyManager", "Agent", "Team", "Player"]


# ---------------------------------------------------------------------------
# Auth (validation priorities 1-2)
# ---------------------------------------------------------------------------

def authenticate():
    """Priority 1: X-User-Role and X-User-ID present, role declared."""
    from flask import request
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Priority 2: acting role in the endpoint's declared roles list."""
    if role not in allowed:
        raise err_forbidden()


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------

def get_json_body():
    """Parse the request JSON body.

    Rates and percentages are exact decimal fractions (PRD 2.6), so floats are
    parsed as Decimal to keep 0.075 exact instead of inheriting binary-float
    noise before it reaches the valuation math.
    """
    import json
    from decimal import Decimal
    from flask import request
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        raw = request.get_data(as_text=True)
        body = json.loads(raw, parse_float=Decimal) if raw else None
    except Exception:
        body = None
    if body is None:
        # Malformed JSON or non-JSON content with no declared input: treat as
        # empty object; required-field checks will surface any real problem.
        return {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def reject_unknown_fields(body, allowed):
    for key in body:
        if key not in allowed:
            raise err_invalid_request(f"Unknown field: {key}")


def req_string(body, field):
    if field not in body:
        raise err_invalid_request(f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str):
        raise err_invalid_request(f"Field {field} must be a string")
    return v


def opt_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err_invalid_request(f"Field {field} must be a string")
    return v


def req_enum(body, field, members):
    v = req_string(body, field)
    if v not in members:
        raise err_invalid_request(f"Field {field} must be one of {sorted(members)}")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    from decimal import Decimal
    return (isinstance(v, (int, float, Decimal)) and not isinstance(v, bool))


def req_int(body, field):
    if field not in body:
        raise err_invalid_request(f"Missing required field: {field}")
    v = body[field]
    if not _is_int(v):
        raise err_invalid_request(f"Field {field} must be an integer")
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_int(v):
        raise err_invalid_request(f"Field {field} must be an integer")
    return v


def req_number(body, field):
    if field not in body:
        raise err_invalid_request(f"Missing required field: {field}")
    v = body[field]
    if not _is_number(v):
        raise err_invalid_request(f"Field {field} must be a number")
    return v


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_number(v):
        raise err_invalid_request(f"Field {field} must be a number")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err_invalid_request(f"Field {field} must be a boolean")
    return v


def parse_datetime_iso(v, field):
    if not isinstance(v, str):
        raise err_invalid_request(f"Field {field} must be an ISO 8601 datetime string")
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_invalid_request(f"Field {field} must be an ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, field):
    v = req_string(body, field)
    return parse_datetime_iso(v, field)


# ---------------------------------------------------------------------------
# Common resource fields (id / created_at / updated_at / version) — PRD 2.4.
# All timestamps come from the logical clock (PRD 2.5).
# ---------------------------------------------------------------------------

def now_stamp():
    return format_ts(db.get_clock())


def new_entity():
    ts = now_stamp()
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts, "version": 1}


def bump(entity):
    entity["version"] += 1
    entity["updated_at"] = now_stamp()


def bump_once(entity):
    """Bump at most once per request, however many cascades touch the entity."""
    from flask import g
    reg = getattr(g, "_bumped", None)
    if reg is None:
        reg = set()
        g._bumped = reg
    if id(entity) not in reg:
        reg.add(id(entity))
        bump(entity)


# ---------------------------------------------------------------------------
# Pagination (scaffold pagination_fields / pagination_defaults)
# ---------------------------------------------------------------------------

def parse_pagination():
    from flask import request
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sorted_by_created(items):
    """Ascending created_at; Python's stable sort keeps insertion order on ties."""
    return sorted(items, key=lambda e: e["created_at"])


# ---------------------------------------------------------------------------
# Scoped path resolvers — priority 3, validated left to right (PRD 2.7).
# ---------------------------------------------------------------------------

def resolve_agency(agency_id):
    ent = db.agencies.get(agency_id)
    if ent is None:
        raise err_not_found("Agency not found")
    return ent


def resolve_agent(agency_id, agent_id):
    ent = db.agents.get(agent_id)
    if ent is None or ent["agency_id"] != agency_id:
        raise err_not_found("Agent not found")
    return ent


def resolve_client(agency_id, client_id):
    ent = db.clients.get(client_id)
    if ent is None or ent["agency_id"] != agency_id:
        raise err_not_found("Client not found")
    return ent


def resolve_team(team_id):
    ent = db.teams.get(team_id)
    if ent is None:
        raise err_not_found("Team not found")
    return ent


def resolve_cap_season(team_id, cap_season_id):
    ent = db.cap_seasons.get(cap_season_id)
    if ent is None or ent["team_id"] != team_id:
        raise err_not_found("CapSeason not found")
    return ent


def resolve_contract(client_id, contract_id):
    ent = db.contracts.get(contract_id)
    if ent is None or ent["client_id"] != client_id:
        raise err_not_found("Contract not found")
    return ent


def resolve_proposal(contract_id, proposal_id):
    ent = db.proposals.get(proposal_id)
    if ent is None or ent["contract_id"] != contract_id:
        raise err_not_found("Proposal not found")
    return ent


def resolve_endorsement(client_id, deal_id):
    ent = db.endorsements.get(deal_id)
    if ent is None or ent["client_id"] != client_id:
        raise err_not_found("EndorsementDeal not found")
    return ent


def resolve_tender_option(contract_id, tender_id):
    ent = db.tender_options.get(tender_id)
    if ent is None or ent["contract_id"] != contract_id:
        raise err_not_found("TenderOption not found")
    return ent


def resolve_grievance(contract_id, grievance_id):
    ent = db.grievances.get(grievance_id)
    if ent is None or ent["contract_id"] != contract_id:
        raise err_not_found("Grievance not found")
    return ent


def resolve_fee_entry(agency_id, entry_id):
    ent = db.fee_ledger_entries.get(entry_id)
    if ent is None or ent["agency_id"] != agency_id:
        raise err_not_found("FeeLedgerEntry not found")
    return ent


def acting_certified_agent(user_id):
    """Priority 5: the acting agent must exist and be CERTIFIED."""
    from errors import err_agent_not_certified
    agent = db.agents.get(user_id)
    if agent is None or agent["cert_status"] != "CERTIFIED":
        raise err_agent_not_certified()
    return agent
