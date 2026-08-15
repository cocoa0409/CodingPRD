"""Shared helpers for route handlers: nested path resolution, pagination,
request body validation (PRD §2.6 validation order, §2.3 pagination)."""

from flask import request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_PROGRAM_NOT_FOUND,
    ERR_INDEX_NOT_FOUND,
    ERR_STATION_NOT_FOUND,
    ERR_HOLDER_NOT_FOUND,
    ERR_POLICY_NOT_FOUND,
    ERR_INVOICE_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_DISPUTE_NOT_FOUND,
    ERR_TREATY_NOT_FOUND,
)
from services import domain


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------

def body() -> dict:
    """Return the JSON request body as a dict, or raise ERR_INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, 400, "Malformed request body")
    return data


def require_fields(data: dict, fields) -> None:
    for f in fields:
        if f not in data or data[f] is None:
            raise err(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def require_enum(data: dict, field: str, allowed) -> None:
    if data.get(field) not in allowed:
        raise err(ERR_INVALID_REQUEST, 400, f"Invalid value for {field}")


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err(ERR_INVALID_REQUEST, 400, "Invalid limit")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err(ERR_INVALID_REQUEST, 400, "Invalid offset")
    if limit < 1 or limit > 100 or offset < 0:
        raise err(ERR_INVALID_REQUEST, 400, "Pagination out of range")
    return limit, offset


def paginate(items, limit, offset):
    """items: full sorted list. Return (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["id"]))


# ---------------------------------------------------------------------------
# Left-to-right nested path resolution (PRD §2.6)
# Each function raises the specific 404 for the first unresolvable segment.
# ---------------------------------------------------------------------------

def get_program(program_id: str) -> dict:
    p = db.programs.get(program_id)
    if not p:
        raise err(ERR_PROGRAM_NOT_FOUND, 404, "Program id does not exist")
    return p


def get_index_in_program(program: dict, index_id: str) -> dict:
    idx = db.index_definitions.get(index_id)
    if not idx or idx["program_id"] != program["id"]:
        raise err(ERR_INDEX_NOT_FOUND, 404, "Index definition id does not exist within the program")
    return idx


def get_station_in_program(program: dict, station_id: str) -> dict:
    s = db.stations.get(station_id)
    if not s or s["program_id"] != program["id"]:
        raise err(ERR_STATION_NOT_FOUND, 404, "Station id does not exist within the program")
    return s


def get_holder_in_program(program: dict, holder_id: str) -> dict:
    h = db.policyholders.get(holder_id)
    if not h or h["program_id"] != program["id"]:
        raise err(ERR_HOLDER_NOT_FOUND, 404, "Policyholder id does not exist within the program")
    return h


def get_policy_of_holder(holder: dict, policy_id: str) -> dict:
    p = db.policies.get(policy_id)
    if not p or p["policyholder_id"] != holder["id"]:
        raise err(ERR_POLICY_NOT_FOUND, 404, "Policy id does not exist within the policyholder")
    return p


def get_invoice_in_program(program: dict, invoice_id: str) -> dict:
    inv = db.invoices.get(invoice_id)
    if not inv:
        raise err(ERR_INVOICE_NOT_FOUND, 404, "Invoice id does not exist within the program")
    pol = db.policies.get(inv["policy_id"])
    if not pol or pol["program_id"] != program["id"]:
        raise err(ERR_INVOICE_NOT_FOUND, 404, "Invoice id does not exist within the program")
    return inv


def get_event_in_index(index: dict, event_id: str) -> dict:
    ev = db.trigger_events.get(event_id)
    if not ev or ev["index_definition_id"] != index["id"]:
        raise err(ERR_EVENT_NOT_FOUND, 404, "Trigger event id does not exist within the index")
    return ev


def get_claim_in_program(program: dict, claim_id: str) -> dict:
    c = db.claims.get(claim_id)
    if not c:
        raise err(ERR_CLAIM_NOT_FOUND, 404, "Claim id does not exist within the program")
    pol = db.policies.get(c["policy_id"])
    if not pol or pol["program_id"] != program["id"]:
        raise err(ERR_CLAIM_NOT_FOUND, 404, "Claim id does not exist within the program")
    return c


def get_dispute_in_claim(claim: dict, dispute_id: str) -> dict:
    d = db.disputes.get(dispute_id)
    if not d or d["claim_id"] != claim["id"]:
        raise err(ERR_DISPUTE_NOT_FOUND, 404, "Dispute id does not exist within the claim")
    return d


def get_treaty_in_program(program: dict, treaty_id: str) -> dict:
    t = db.treaties.get(treaty_id)
    if not t or t["program_id"] != program["id"]:
        raise err(ERR_TREATY_NOT_FOUND, 404, "Treaty id does not exist within the program")
    return t
