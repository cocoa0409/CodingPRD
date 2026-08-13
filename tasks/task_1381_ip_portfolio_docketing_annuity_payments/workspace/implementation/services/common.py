"""Shared record helpers: IDs, timestamps, field validation, lookups, state guards."""

import re
import uuid
from datetime import date

import db as dbmod
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
)

JURISDICTIONS = {"US", "EP", "JP", "CN", "KR", "PCT"}
APPLICATION_TYPES = {
    "ORIGINAL",
    "PARIS_CONVENTION",
    "PCT_INTERNATIONAL",
    "PCT_NATIONAL_PHASE",
    "CONTINUATION",
    "DIVISIONAL",
}
ENTITY_SIZES = {"LARGE", "SMALL"}
ENTRY_TYPES = {
    "OFFICE_ACTION_RESPONSE",
    "STATUTORY",
    "PARIS_PRIORITY",
    "PCT_PHASE",
    "ANNUITY",
    "RECORDATION",
}
ACTION_TYPES = {
    "NON_FINAL_REJECTION",
    "FINAL_REJECTION",
    "NOTICE_OF_ALLOWANCE",
    "INFORMATIONAL",
}
INSTRUCTION_TYPES = {"FILING", "OA_RESPONSE", "ANNUITY_PAYMENT", "RECORDATION"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id():
    return str(uuid.uuid4())


def stamp_new(record):
    ts = dbmod.logical_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    record["updated_at"] = dbmod.logical_iso()


def bump(record):
    """Every modification refreshes updated_at and increments version (PRD §2.6)."""
    record["version"] = record.get("version", 1) + 1
    touch(record)


# --- body shape validation (priority 6) --------------------------------------

def check_allowed_fields(body, allowed):
    extra = [k for k in body.keys() if k not in allowed]
    if extra:
        raise_err(ERR_INVALID_REQUEST, f"Undeclared field(s): {', '.join(sorted(extra))}")


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, f"{field} is required and must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"{field} must be a string")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"{field} is required and must be an integer")
    return v


def opt_int(body, field):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return v


def req_date(body, field):
    """Strict ISO YYYY-MM-DD date field -> datetime.date."""
    v = body.get(field)
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise_err(ERR_INVALID_REQUEST, f"{field} must be an ISO YYYY-MM-DD date string")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"{field} is not a valid calendar date")


def req_str_array(body, field):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise_err(ERR_INVALID_REQUEST, f"{field} must be an array of strings")
    return v


# --- existence (priority 4) ----------------------------------------------------

def get_record(collection, rid, label):
    rec = dbmod.DB[collection].get(rid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, f"{label} not found: {rid}")
    return rec


def get_client(rid):
    return get_record("clients", rid, "Client")


def get_contact(rid):
    return get_record("contacts", rid, "ClientContact")


def get_firm(rid):
    return get_record("counsel_firms", rid, "CounselFirm")


def get_inventor(rid):
    return get_record("inventors", rid, "Inventor")


def get_family(rid):
    return get_record("families", rid, "PatentFamily")


def get_application(rid):
    return get_record("applications", rid, "Application")


def get_entry(rid):
    return get_record("docket_entries", rid, "DocketEntry")


def get_office_action(rid):
    return get_record("office_actions", rid, "OfficeAction")


def get_obligation(rid):
    return get_record("obligations", rid, "AnnuityObligation")


def get_authorization(rid):
    return get_record("authorizations", rid, "PaymentAuthorization")


def get_instruction(rid):
    return get_record("instructions", rid, "OutsideCounselInstruction")


def get_review(rid):
    return get_record("reviews", rid, "AbandonmentReview")


def get_assignment(rid):
    return get_record("assignments", rid, "AssignmentRecord")


def get_audit(rid):
    return get_record("audits", rid, "DocketAudit")


def get_rule(rid):
    return get_record("jurisdiction_rules", rid, "JurisdictionRule")


def rule_for_jurisdiction(code):
    rid = dbmod.DB["jurisdiction_index"].get(code)
    if rid is None:
        return None
    return dbmod.DB["jurisdiction_rules"][rid]


# --- hierarchy walkers ---------------------------------------------------------

def family_of_application(app):
    return dbmod.DB["families"][app["family_id"]]


def client_of_family(family):
    return dbmod.DB["clients"][family["client_id"]]


def client_of_application(app):
    return client_of_family(family_of_application(app))


def application_of_obligation(ob):
    return dbmod.DB["applications"][ob["application_id"]]


def family_of_obligation(ob):
    return family_of_application(application_of_obligation(ob))


def application_of_entry(entry):
    return dbmod.DB["applications"][entry["application_id"]]


# --- state guards (priority 7) --------------------------------------------------

TERMINAL_STATES = {
    "clients": set(),
    "families": {"CLOSED"},
    "applications": {"ABANDONED", "LAPSED", "WITHDRAWN"},
    "docket_entries": {"COMPLETED", "CANCELLED", "LAPSED"},
    "office_actions": {"CLOSED"},
    "obligations": {"PAID_CONFIRMED", "LAPSED", "CANCELLED"},
    "authorizations": {"RELEASED", "REJECTED", "SUPERSEDED"},
    "instructions": {"COMPLETED", "DECLINED", "CANCELLED"},
    "reviews": {"REJECTED", "EXECUTED"},
    "assignments": {"RECORDED"},
    "audits": {"RESOLVED", "CLOSED_CLEAN"},
}


def ensure_transition(rec, allowed_from, collection, label):
    """Terminal resources reject every transition; a non-listed from-state is invalid."""
    status = rec["status"]
    if status in TERMINAL_STATES[collection]:
        raise_err(ERR_ALREADY_TERMINAL, f"{label} is in terminal state {status}")
    if status not in allowed_from:
        raise_err(
            ERR_INVALID_STATE,
            f"{label} in state {status} does not define this transition",
        )
