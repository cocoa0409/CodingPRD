"""Input validation helpers — pre-state-machine checks."""
from __future__ import annotations

import re

import db
import errors
from services import calculations


_LEGAL_NAME_RE = re.compile(r"^[A-Z0-9 \-\.,&]+$")

ENTITY_TYPES = {"LLC", "CORP", "LP"}
REVENUE_BANDS = {"ZERO", "MICRO", "SMALL", "MEDIUM", "LARGE"}
TEMPLATE_TYPES = {"MEMBER_MANAGED", "MANAGER_MANAGED", "LP_GENERAL_LIMITED"}
AGENT_TYPES = {"INDIVIDUAL", "COMMERCIAL"}
TRIGGER_EVENTS = {"FORMATION", "AMENDMENT", "ANNUAL_REFRESH"}
CONTROL_ROLES = {"OWNER", "CONTROLLER", "BOTH"}
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def require_dict(body) -> dict:
    if body is None:
        raise errors.err_invalid_request("Request body must be a JSON object.")
    if not isinstance(body, dict):
        raise errors.err_invalid_request("Request body must be a JSON object.")
    return body


def require_str(body: dict, key: str, *, min_len: int = 1, max_len: int = 1_000_000) -> str:
    if key not in body:
        raise errors.err_invalid_request(f"Missing required field: {key}.")
    v = body[key]
    if not isinstance(v, str):
        raise errors.err_invalid_request(f"Field {key} must be a string.")
    if len(v) < min_len or len(v) > max_len:
        raise errors.err_invalid_request(f"Field {key} length out of range.")
    return v


def require_int(body: dict, key: str) -> int:
    if key not in body:
        raise errors.err_invalid_request(f"Missing required field: {key}.")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err_invalid_request(f"Field {key} must be an integer.")
    return v


def optional_str(body: dict, key: str) -> str:
    v = body.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise errors.err_invalid_request(f"Field {key} must be a string.")
    return v


# ---------- Business-entity-specific input checks ----------

def validate_legal_name(name: str) -> None:
    if not isinstance(name, str):
        raise errors.err_invalid_request("legal_name must be a string.")
    if len(name) < 1 or len(name) > 200:
        raise errors.err_invalid_request("legal_name length must be 1..200.")
    if not _LEGAL_NAME_RE.match(name):
        raise errors.err_invalid_request("legal_name has invalid characters.")


def validate_entity_type(et: str) -> None:
    if et not in ENTITY_TYPES:
        raise errors.err_invalid_request("entity_type must be one of LLC, CORP, LP.")


def validate_state_code(code: str, field_name: str = "state_code") -> None:
    if not isinstance(code, str) or not STATE_CODE_RE.match(code):
        raise errors.err_invalid_request(f"{field_name} must be two uppercase letters.")
    if code not in calculations.SUPPORTED_STATES:
        raise errors.err_invalid_request(f"{field_name} {code} not in supported state set.")


def validate_revenue_band(b: str) -> None:
    if b not in REVENUE_BANDS:
        raise errors.err_invalid_request("revenue_band must be one of ZERO, MICRO, SMALL, MEDIUM, LARGE.")


def validate_legal_name_unique(legal_name: str, formation_state_code: str) -> None:
    for be in db.business_entities.values():
        if be["status"] == "DISSOLVED":
            continue
        if be["formation_state_code"] == formation_state_code and be["legal_name"] == legal_name:
            raise errors.err_invalid_request("legal_name not unique within formation_state_code.")


# ---------- members_json & beneficial_owners_json ----------

def validate_members_json(members) -> None:
    if not isinstance(members, list):
        raise errors.err_operating_agreement_invalid("members_json must be a list.")
    if len(members) < 1 or len(members) > 50:
        raise errors.err_operating_agreement_invalid("members_json must have 1..50 entries.")
    total = 0
    for m in members:
        if not isinstance(m, dict):
            raise errors.err_operating_agreement_invalid("each member must be an object.")
        name = m.get("name")
        if not isinstance(name, str) or len(name) < 1 or len(name) > 120:
            raise errors.err_operating_agreement_invalid("member name must be 1..120 chars.")
        op = m.get("ownership_pct")
        if isinstance(op, bool) or not isinstance(op, int):
            raise errors.err_operating_agreement_invalid("ownership_pct must be an integer.")
        if op < 1 or op > 100:
            raise errors.err_operating_agreement_invalid("ownership_pct must be in 1..100.")
        total += op
    if total != 100:
        raise errors.err_operating_agreement_invalid("members_json ownership_pct must sum to 100.")


def validate_beneficial_owners_json(owners) -> None:
    if not isinstance(owners, list):
        raise errors.err_boi_invalid("beneficial_owners_json must be a list.")
    if len(owners) < 1 or len(owners) > 25:
        raise errors.err_boi_invalid("beneficial_owners_json must have 1..25 entries.")
    total = 0
    for o in owners:
        if not isinstance(o, dict):
            raise errors.err_boi_invalid("each beneficial owner must be an object.")
        op = o.get("ownership_pct")
        if isinstance(op, bool) or not isinstance(op, int):
            raise errors.err_boi_invalid("ownership_pct must be an integer.")
        if op < 1 or op > 100:
            raise errors.err_boi_invalid("ownership_pct must be in 1..100.")
        cr = o.get("control_role")
        if cr not in CONTROL_ROLES:
            raise errors.err_boi_invalid("control_role must be OWNER, CONTROLLER, or BOTH.")
        total += op
    if total != 100:
        raise errors.err_boi_invalid("beneficial_owners_json ownership_pct must sum to 100.")
