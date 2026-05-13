"""ProtectionCase + Evidence logic."""
import db
from errors import (APIError, ERR_REFERENCED_ENTITY_NOT_FOUND, ERR_AGENT_JURISDICTION_MISMATCH,
                    ERR_EVIDENCE_MISSING_FOR_LITIGATION, ERR_INVALID_STATE, ERR_CASE_ALREADY_RESOLVED,
                    ERR_BAD_REQUEST)
from services import audit
from services.common import make_versioned, make_unversioned, touch


def create_case(body, actor_role, actor_id):
    from utils import get_str
    ip_right_id = get_str(body, "ip_right_id")
    assigned_agent_id = get_str(body, "assigned_agent_id")
    business_unit_id = get_str(body, "business_unit_id")
    rights_holder_currency = body.get("rights_holder_currency", "USD") or "USD"

    if ip_right_id not in db.ip_rights:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "ip_right_id does not resolve")
    if assigned_agent_id not in db.agents:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "assigned_agent_id does not resolve")
    if business_unit_id not in db.business_units:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "business_unit_id does not resolve")

    case = make_versioned({
        "ip_right_id": ip_right_id,
        "assigned_agent_id": assigned_agent_id,
        "business_unit_id": business_unit_id,
        "route": "NONE",
        "status": "OPEN",
        "outcome": None,
        "recovered_amount_cents": 0,
        "legal_fees_cents": 0,
        "agent_fees_cents": 0,
        "punitive_cap_cents": 0,
        "distributed": None,
        "rights_holder_currency": rights_holder_currency,
    })
    db.protection_cases[case["id"]] = case
    audit.emit("ProtectionCase", case["id"], actor_role, actor_id,
               "STATUS_CHANGE", from_state=None, to_state="OPEN")
    return case


def add_evidence(case, body, actor_role, actor_id):
    from utils import get_str, get_enum
    kind = get_enum(body, "kind", ("WITNESS", "DOCUMENT", "SAMPLE", "DIGITAL"))
    collected_at = get_str(body, "collected_at")
    storage_uri = get_str(body, "storage_uri")
    chain_hash = body.get("chain_of_custody_hash")
    evidence = make_unversioned({
        "protection_case_id": case["id"],
        "kind": kind,
        "collected_at": collected_at,
        "storage_uri": storage_uri,
        "chain_of_custody_hash": chain_hash,
    })
    db.evidences[evidence["id"]] = evidence
    audit.emit("Evidence", evidence["id"], actor_role, actor_id,
               "EVIDENCE_ADDED", from_state=None, to_state=None,
               payload={"case_id": case["id"], "kind": kind})
    return evidence


def route_case(case, body, actor_role, actor_id):
    from utils import get_enum
    route = get_enum(body, "route", ("DEMAND_LETTER", "LITIGATION", "MEDIATION", "ARBITRATION"))

    if case["status"] != "OPEN" or case["route"] != "NONE":
        raise APIError(ERR_INVALID_STATE, 409, "Case is not OPEN/NONE")

    agent = db.agents.get(case["assigned_agent_id"])
    right = db.ip_rights.get(case["ip_right_id"])
    if not agent or not right:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "agent or right missing")

    # Litigation requires evidence with chain_of_custody_hash != null
    if route == "LITIGATION":
        has_chain = any(e for e in db.evidences.values()
                        if e["protection_case_id"] == case["id"]
                        and e.get("chain_of_custody_hash"))
        if not has_chain:
            raise APIError(ERR_EVIDENCE_MISSING_FOR_LITIGATION, 422,
                           "Litigation route requires at least one Evidence with chain_of_custody_hash")
    # Agent jurisdiction check
    if right["primary_jurisdiction"] not in agent.get("jurisdictions", []):
        raise APIError(ERR_AGENT_JURISDICTION_MISMATCH, 422,
                       "Agent.jurisdictions does not contain IPRight.primary_jurisdiction")

    prior = case["status"]
    case["route"] = route
    case["status"] = "IN_PROGRESS"
    touch(case)
    audit.emit("ProtectionCase", case["id"], actor_role, actor_id,
               "STATUS_CHANGE", from_state=prior, to_state="IN_PROGRESS",
               payload={"route": route})
    return case


def resolve_case(case, body, actor_role, actor_id):
    from utils import get_enum, get_int
    if case["status"] in ("RESOLVED", "CLOSED"):
        raise APIError(ERR_CASE_ALREADY_RESOLVED, 409, "Case already resolved")
    if case["status"] != "IN_PROGRESS":
        raise APIError(ERR_INVALID_STATE, 409, "Case not IN_PROGRESS")
    outcome = get_enum(body, "outcome", ("WON", "LOST", "SETTLED", "DISMISSED"))
    recovered = get_int(body, "recovered_amount_cents", required=True, min_value=0)
    legal_fees = get_int(body, "legal_fees_cents", required=True, min_value=0)
    agent_fees = get_int(body, "agent_fees_cents", required=True, min_value=0)
    punitive_cap = get_int(body, "punitive_cap_cents", required=True, min_value=0)

    if outcome == "WON" and recovered <= 0:
        raise APIError(ERR_BAD_REQUEST, 422, "WON outcome requires recovered_amount_cents > 0")
    if outcome in ("LOST", "DISMISSED") and recovered != 0:
        raise APIError(ERR_BAD_REQUEST, 422, f"{outcome} outcome requires recovered_amount_cents == 0")

    case["outcome"] = outcome
    case["recovered_amount_cents"] = recovered
    case["legal_fees_cents"] = legal_fees
    case["agent_fees_cents"] = agent_fees
    case["punitive_cap_cents"] = punitive_cap

    if outcome in ("WON", "SETTLED"):
        remaining = recovered
        legal_paid = min(remaining, legal_fees); remaining -= legal_paid
        agent_paid = min(remaining, agent_fees); remaining -= agent_paid
        punitive_paid = min(remaining, punitive_cap); remaining -= punitive_paid
        rights_holder_paid = remaining
        case["distributed"] = {
            "legal_paid": legal_paid,
            "agent_paid": agent_paid,
            "punitive_paid": punitive_paid,
            "rights_holder_paid": rights_holder_paid,
        }
    else:
        case["distributed"] = None

    prior = case["status"]
    case["status"] = "RESOLVED"
    touch(case)

    # Book LITIGATION cost row for legal_fees + agent_fees, allocated to right's BU.
    right = db.ip_rights.get(case["ip_right_id"])
    if right and right["business_unit_id"] in db.business_units:
        from services.cost_logic import book_cost_for_event
        book_cost_for_event(
            category="LITIGATION",
            amount_usd_cents=legal_fees + agent_fees,
            ip_right_id=right["id"],
            protection_case_id=case["id"],
            agent_id=None,
            business_unit_id=right["business_unit_id"],
            actor_role=actor_role,
            actor_id=actor_id,
            currency="USD",
        )

    audit.emit("ProtectionCase", case["id"], actor_role, actor_id,
               "STATUS_CHANGE", from_state=prior, to_state="RESOLVED",
               payload={"outcome": outcome, "distributed": case["distributed"]})
    return case


def close_case(case, actor_role, actor_id):
    if case["status"] != "RESOLVED":
        raise APIError(ERR_INVALID_STATE, 409, "Case not in RESOLVED")
    prior = case["status"]
    case["status"] = "CLOSED"
    touch(case)
    audit.emit("ProtectionCase", case["id"], actor_role, actor_id,
               "STATUS_CHANGE", from_state=prior, to_state="CLOSED")
    return case
