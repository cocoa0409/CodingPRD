"""IPRight + JurisdictionFiling + ApplicationOfficeAction state machine logic."""
from datetime import timedelta

import db
from errors import (APIError, ERR_REFERENCED_ENTITY_NOT_FOUND, ERR_AGENT_QUALIFICATION_UNVERIFIED,
                    ERR_AGENT_JURISDICTION_MISMATCH, ERR_INVALID_STATE, ERR_BAD_REQUEST,
                    ERR_OFFICE_ACTION_ALREADY_ASSIGNED, ERR_FEE_DATES_INVALID)
from services import audit, serializers
from services.common import make_versioned, touch


# ---------------- IPRight creation -----------------

def create_ip_right(body, actor_role, actor_id):
    from utils import get_str, get_enum
    ip_type = get_enum(body, "ip_type", ("PATENT", "TRADEMARK", "COPYRIGHT"))
    title = get_str(body, "title")
    if not title.strip():
        raise APIError(ERR_BAD_REQUEST, 422, "title must be non-empty")
    handling_mode = get_enum(body, "handling_mode", ("AGENCY", "SELF"))
    business_unit_id = get_str(body, "business_unit_id")
    primary_jurisdiction = get_str(body, "primary_jurisdiction")
    if not primary_jurisdiction.strip():
        raise APIError(ERR_BAD_REQUEST, 422, "primary_jurisdiction must be non-empty")
    assigned_agent_id = body.get("assigned_agent_id")

    # Validate FK references
    if business_unit_id not in db.business_units:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "business_unit_id does not resolve")
    if handling_mode == "AGENCY":
        if not assigned_agent_id:
            raise APIError(ERR_BAD_REQUEST, 422, "assigned_agent_id required for AGENCY handling_mode")
        if assigned_agent_id not in db.agents:
            raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "assigned_agent_id does not resolve")
        agent = db.agents[assigned_agent_id]
        if not agent.get("qualification_verified"):
            raise APIError(ERR_AGENT_QUALIFICATION_UNVERIFIED, 422,
                           "Agent qualification not verified")
        if primary_jurisdiction not in agent.get("jurisdictions", []):
            raise APIError(ERR_AGENT_JURISDICTION_MISMATCH, 422,
                           "Agent does not cover the primary_jurisdiction")
    else:
        # SELF
        if assigned_agent_id is not None:
            raise APIError(ERR_BAD_REQUEST, 422,
                           "assigned_agent_id must be null when handling_mode == SELF")

    right = make_versioned({
        "ip_type": ip_type,
        "title": title,
        "handling_mode": handling_mode,
        "assigned_agent_id": assigned_agent_id,
        "business_unit_id": business_unit_id,
        "status": "DRAFT",
        "primary_jurisdiction": primary_jurisdiction,
        "certificate_archive_url": None,
        "registered_at": None,
    })
    db.ip_rights[right["id"]] = right
    audit.emit("IPRight", right["id"], actor_role, actor_id,
               "STATUS_CHANGE", from_state=None, to_state="DRAFT")
    return right


# ---------------- Transitions -----------------

def materials_ready(right, actor_role, actor_id):
    if right["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "IPRight is not in DRAFT")
    # check title + primary_jurisdiction non-empty (priority 5 already satisfied; this is a sanity check)
    if not right.get("title") or not right.get("primary_jurisdiction"):
        raise APIError(ERR_INVALID_STATE, 409, "Missing required material fields")
    if right["handling_mode"] == "AGENCY":
        agent_id = right.get("assigned_agent_id")
        if not agent_id or agent_id not in db.agents:
            raise APIError(ERR_AGENT_QUALIFICATION_UNVERIFIED, 422, "Agent not present")
        agent = db.agents[agent_id]
        if not agent.get("qualification_verified"):
            raise APIError(ERR_AGENT_QUALIFICATION_UNVERIFIED, 422, "Agent qualification not verified")
    else:
        if right.get("assigned_agent_id") is not None:
            raise APIError(ERR_INVALID_STATE, 409,
                           "assigned_agent_id must be null for SELF handling_mode")
    prior = right["status"]
    right["status"] = "MATERIALS_READY"
    touch(right)
    audit.emit("IPRight", right["id"], actor_role, actor_id,
               "STATUS_CHANGE", from_state=prior, to_state="MATERIALS_READY")
    return right


def create_jurisdiction_filing(right, body, actor_role, actor_id):
    from utils import get_str
    if right["status"] not in ("MATERIALS_READY", "FILED", "OFFICE_ACTION", "REGISTERED"):
        raise APIError(ERR_INVALID_STATE, 409, "Cannot file under current IPRight status")
    jurisdiction = get_str(body, "jurisdiction")
    filing_number = get_str(body, "filing_number")
    filed_at = get_str(body, "filed_at")

    filing = make_versioned({
        "ip_right_id": right["id"],
        "jurisdiction": jurisdiction,
        "filing_number": filing_number,
        "filed_at": filed_at,
        "status": "FILED",
    })
    db.jurisdiction_filings[filing["id"]] = filing
    # If parent is MATERIALS_READY, transition to FILED on first filing
    if right["status"] == "MATERIALS_READY":
        prior = right["status"]
        right["status"] = "FILED"
        touch(right)
        audit.emit("IPRight", right["id"], actor_role, actor_id,
                   "STATUS_CHANGE", from_state=prior, to_state="FILED")
    return filing


def open_office_action(right, body, actor_role, actor_id):
    from utils import get_str
    if right["status"] not in ("FILED", "OFFICE_ACTION"):
        raise APIError(ERR_INVALID_STATE, 409, "Cannot open office action in current IPRight status")
    jurisdiction_filing_id = get_str(body, "jurisdiction_filing_id")
    assigned_agent_id = get_str(body, "assigned_agent_id")
    response_due_at = get_str(body, "response_due_at")
    # FK resolution
    if jurisdiction_filing_id not in db.jurisdiction_filings:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "jurisdiction_filing_id does not resolve")
    if assigned_agent_id not in db.agents:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "assigned_agent_id does not resolve")

    filing = db.jurisdiction_filings[jurisdiction_filing_id]
    if filing["ip_right_id"] != right["id"]:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422,
                       "jurisdiction_filing does not belong to this IPRight")
    if filing["status"] != "FILED":
        raise APIError(ERR_INVALID_STATE, 409, "JurisdictionFiling not in FILED status")

    # Agent qualification check (business safety)
    agent = db.agents[assigned_agent_id]
    if not agent.get("qualification_verified"):
        raise APIError(ERR_AGENT_QUALIFICATION_UNVERIFIED, 422, "Agent qualification not verified")

    oa = make_versioned({
        "ip_right_id": right["id"],
        "jurisdiction_filing_id": jurisdiction_filing_id,
        "assigned_agent_id": assigned_agent_id,
        "response_due_at": response_due_at,
        "responded_at": None,
        "status": "PENDING",
    })
    db.office_actions[oa["id"]] = oa
    # Filing -> OFFICE_ACTION
    prior_filing = filing["status"]
    filing["status"] = "OFFICE_ACTION"
    touch(filing)
    audit.emit("JurisdictionFiling", filing["id"], actor_role, actor_id,
               "STATUS_CHANGE", from_state=prior_filing, to_state="OFFICE_ACTION")

    # IPRight -> OFFICE_ACTION
    if right["status"] != "OFFICE_ACTION":
        prior_right = right["status"]
        right["status"] = "OFFICE_ACTION"
        touch(right)
        audit.emit("IPRight", right["id"], actor_role, actor_id,
                   "STATUS_CHANGE", from_state=prior_right, to_state="OFFICE_ACTION")
    return oa


def respond_office_action(oa, actor_role, actor_id):
    """Agent files response."""
    if oa["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Office action not PENDING")
    if db.now() >= db.parse_iso(oa["response_due_at"]):
        raise APIError(ERR_INVALID_STATE, 409, "Response deadline has elapsed")
    # actor identity check: actor_id must equal oa.assigned_agent_id
    from errors import ERR_FORBIDDEN
    if oa["assigned_agent_id"] != actor_id:
        raise APIError(ERR_FORBIDDEN, 403, "Caller is not the assigned agent")

    prior = oa["status"]
    oa["status"] = "RESPONDED"
    oa["responded_at"] = db.now_iso()
    touch(oa)
    audit.emit("ApplicationOfficeAction", oa["id"], actor_role, actor_id,
               "STATUS_CHANGE", from_state=prior, to_state="RESPONDED")

    # Filing returns to FILED
    filing = db.jurisdiction_filings.get(oa["jurisdiction_filing_id"])
    if filing and filing["status"] == "OFFICE_ACTION":
        p = filing["status"]
        filing["status"] = "FILED"
        touch(filing)
        audit.emit("JurisdictionFiling", filing["id"], actor_role, actor_id,
                   "STATUS_CHANGE", from_state=p, to_state="FILED")

    # Bubble up IPRight if no other pending office actions
    right = db.ip_rights.get(oa["ip_right_id"])
    if right:
        has_pending = any(o for o in db.office_actions.values()
                          if o["ip_right_id"] == right["id"]
                          and o["status"] == "PENDING")
        if not has_pending and right["status"] == "OFFICE_ACTION":
            p = right["status"]
            right["status"] = "FILED"
            touch(right)
            audit.emit("IPRight", right["id"], actor_role, actor_id,
                       "STATUS_CHANGE", from_state=p, to_state="FILED")
    return oa


def abandon_office_action(oa, actor_role, actor_id):
    if oa["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Office action not PENDING")
    due = db.parse_iso(oa["response_due_at"])
    if db.now() < due:
        raise APIError(ERR_INVALID_STATE, 409, "Response deadline has not elapsed")
    prior = oa["status"]
    oa["status"] = "CLOSED_ABANDONED"
    touch(oa)
    audit.emit("ApplicationOfficeAction", oa["id"], actor_role, actor_id,
               "STATUS_CHANGE", from_state=prior, to_state="CLOSED_ABANDONED")

    # filing -> ABANDONED
    filing = db.jurisdiction_filings.get(oa["jurisdiction_filing_id"])
    if filing and filing["status"] != "ABANDONED":
        p = filing["status"]
        filing["status"] = "ABANDONED"
        touch(filing)
        audit.emit("JurisdictionFiling", filing["id"], actor_role, actor_id,
                   "STATUS_CHANGE", from_state=p, to_state="ABANDONED")

    # If IPRight has no remaining FILED or OFFICE_ACTION filings, bubble to ABANDONED
    right = db.ip_rights.get(oa["ip_right_id"])
    if right:
        siblings = [f for f in db.jurisdiction_filings.values() if f["ip_right_id"] == right["id"]]
        if siblings and all(f["status"] not in ("FILED", "OFFICE_ACTION") for f in siblings):
            if right["status"] != "ABANDONED":
                p = right["status"]
                right["status"] = "ABANDONED"
                touch(right)
                audit.emit("IPRight", right["id"], actor_role, actor_id,
                           "STATUS_CHANGE", from_state=p, to_state="ABANDONED")
    return oa


def register_filing(filing, body, actor_role, actor_id):
    from utils import get_str
    if filing["status"] != "FILED":
        raise APIError(ERR_INVALID_STATE, 409, "Filing not in FILED status")
    archive_url = get_str(body, "archive_url")

    prior = filing["status"]
    filing["status"] = "REGISTERED"
    touch(filing)
    audit.emit("JurisdictionFiling", filing["id"], actor_role, actor_id,
               "STATUS_CHANGE", from_state=prior, to_state="REGISTERED")

    # Update linked office actions in RESPONDED -> CLOSED_GRANTED
    for oa in db.office_actions.values():
        if oa["jurisdiction_filing_id"] == filing["id"] and oa["status"] == "RESPONDED":
            p = oa["status"]
            oa["status"] = "CLOSED_GRANTED"
            touch(oa)
            audit.emit("ApplicationOfficeAction", oa["id"], actor_role, actor_id,
                       "STATUS_CHANGE", from_state=p, to_state="CLOSED_GRANTED")

    right = db.ip_rights.get(filing["ip_right_id"])
    if right:
        siblings = [f for f in db.jurisdiction_filings.values() if f["ip_right_id"] == right["id"]]
        if siblings and all(f["status"] in ("REGISTERED", "ABANDONED") for f in siblings):
            if right["status"] != "REGISTERED":
                p = right["status"]
                right["status"] = "REGISTERED"
                right["registered_at"] = db.now_iso()
                right["certificate_archive_url"] = archive_url
                touch(right)
                audit.emit("IPRight", right["id"], actor_role, actor_id,
                           "STATUS_CHANGE", from_state=p, to_state="REGISTERED")

                # Auto-create AnnualFeeSchedule fee_year=1 rows for each (jurisdiction, ip_type) pair
                # of REGISTERED filings of this right.
                created_juris = set()
                for f in siblings:
                    if f["status"] == "REGISTERED" and f["jurisdiction"] not in created_juris:
                        created_juris.add(f["jurisdiction"])
                        fee = make_versioned({
                            "ip_right_id": right["id"],
                            "jurisdiction": f["jurisdiction"],
                            "fee_year": 1,
                            "base_fee_cents": 0,
                            "due_date": db.now_iso(),
                            "grace_end_date": db.to_iso(db.now() + timedelta(days=180)),
                            "paid_at": None,
                            "total_paid_cents": 0,
                            "surcharge_cents": 0,
                            "auto_pay_authorized": False,
                            "assigned_agent_id": None,
                            "status": "PENDING",
                        })
                        db.annual_fees[fee["id"]] = fee
    return right or db.ip_rights[filing["ip_right_id"]]
