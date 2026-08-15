"""Reference data: retention policies, data elements, data systems, state law
rules."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import STAFF_ROLES, get_body, require_roles
from response import list_response, success
from serialize import (ser_data_element, ser_data_system,
                       ser_retention_policy, ser_state_law_rule)
from services.core import base_entity, created_asc, reclassification_cascade, touch
from services.risk import (CLASSIFICATIONS, DATA_CATEGORIES, DISPOSAL_ACTIONS,
                           REGIONS)
from utils import is_int, is_num

bp = Blueprint("reference", __name__)


# --- RetentionPolicy -----------------------------------------------------------

@bp.post("/privacy/retention-policies")
def create_retention_policy():
    require_roles("PrivacyAdmin")
    body = get_body()
    policy_code = body.get("policy_code")
    if isinstance(policy_code, str) and any(
            p["policy_code"] == policy_code for p in db.retention_policies.values()):
        raise ApiError("ERR_DUPLICATE_KEY", "policy_code already exists")
    duration_days = body.get("duration_days")
    disposal_action = body.get("disposal_action")
    if not isinstance(policy_code, str) or not policy_code:
        raise ApiError("ERR_INVALID_REQUEST", "policy_code is required")
    if not is_int(duration_days) or duration_days <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "duration_days must be an integer > 0")
    if disposal_action not in DISPOSAL_ACTIONS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid disposal_action")
    policy = base_entity()
    policy.update({
        "policy_code": policy_code,
        "duration_days": duration_days,
        "disposal_action": disposal_action,
    })
    db.retention_policies[policy["id"]] = policy
    return success(ser_retention_policy(policy), 201)


# --- DataElement ---------------------------------------------------------------

@bp.post("/privacy/data-elements")
def create_data_element():
    require_roles("DataSteward")
    body = get_body()
    element_key = body.get("element_key")
    if isinstance(element_key, str) and any(
            e["element_key"] == element_key for e in db.data_elements.values()):
        raise ApiError("ERR_DUPLICATE_KEY", "element_key already exists")
    category = body.get("category")
    classification = body.get("classification")
    if not isinstance(element_key, str) or not element_key:
        raise ApiError("ERR_INVALID_REQUEST", "element_key is required")
    if category not in DATA_CATEGORIES:
        raise ApiError("ERR_INVALID_REQUEST", "invalid category")
    if classification not in CLASSIFICATIONS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid classification")
    element = base_entity()
    element.update({
        "element_key": element_key,
        "category": category,
        "classification": classification,
        "status": "ACTIVE",
    })
    db.data_elements[element["id"]] = element
    return success(ser_data_element(element), 201)


@bp.get("/privacy/data-elements/<element_id>")
def get_data_element(element_id):
    require_roles(*STAFF_ROLES)
    element = db.data_elements.get(element_id)
    if element is None:
        raise ApiError("ERR_NOT_FOUND", "data element not found")
    return success(ser_data_element(element), 200)


@bp.post("/privacy/data-elements/<element_id>/reclassify")
def reclassify_data_element(element_id):
    require_roles("DataSteward")
    element = db.data_elements.get(element_id)
    if element is None:
        raise ApiError("ERR_NOT_FOUND", "data element not found")
    body = get_body()
    if "expected_element_version" in body:
        if body["expected_element_version"] != element["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_element_version does not match the current version")
    if element["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only an ACTIVE element can be reclassified")
    category = body.get("category")
    classification = body.get("classification")
    if "expected_element_version" not in body:
        raise ApiError("ERR_INVALID_REQUEST", "expected_element_version is required")
    if category not in DATA_CATEGORIES:
        raise ApiError("ERR_INVALID_REQUEST", "invalid category")
    if classification not in CLASSIFICATIONS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid classification")
    element["category"] = category
    element["classification"] = classification
    touch(element)
    reclassification_cascade(element)
    return success(ser_data_element(element), 200)


@bp.post("/privacy/data-elements/<element_id>/retire")
def retire_data_element(element_id):
    require_roles("DataSteward")
    element = db.data_elements.get(element_id)
    if element is None:
        raise ApiError("ERR_NOT_FOUND", "data element not found")
    if element["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only an ACTIVE element can be retired")
    element["status"] = "RETIRED"
    touch(element)
    return success(ser_data_element(element), 200)


# --- DataSystem ----------------------------------------------------------------

@bp.post("/privacy/data-systems")
def create_data_system():
    require_roles("PrivacyAdmin")
    body = get_body()
    system_key = body.get("system_key")
    if isinstance(system_key, str) and any(
            s["system_key"] == system_key for s in db.data_systems.values()):
        raise ApiError("ERR_DUPLICATE_KEY", "system_key already exists")
    hosting_region = body.get("hosting_region")
    stores_categories = body.get("stores_categories")
    if not isinstance(system_key, str) or not system_key:
        raise ApiError("ERR_INVALID_REQUEST", "system_key is required")
    if hosting_region not in REGIONS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid hosting_region")
    if (not isinstance(stores_categories, list)
            or any(c not in DATA_CATEGORIES for c in stores_categories)):
        raise ApiError("ERR_INVALID_REQUEST",
                       "stores_categories must be a list of data categories")
    system = base_entity()
    system.update({
        "system_key": system_key,
        "hosting_region": hosting_region,
        "stores_categories": list(stores_categories),
        "status": "ACTIVE",
    })
    db.data_systems[system["id"]] = system
    return success(ser_data_system(system), 201)


@bp.get("/privacy/data-systems")
def list_data_systems():
    require_roles(*STAFF_ROLES)
    items = created_asc(list(db.data_systems.values()))
    return list_response(items, ser_data_system)


@bp.post("/privacy/data-systems/<system_id>/decommission")
def decommission_data_system(system_id):
    require_roles("PrivacyAdmin")
    system = db.data_systems.get(system_id)
    if system is None:
        raise ApiError("ERR_NOT_FOUND", "data system not found")
    if system["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only an ACTIVE system can be decommissioned")
    system["status"] = "DECOMMISSIONED"
    touch(system)
    return success(ser_data_system(system), 200)


# --- StateLawRule --------------------------------------------------------------

@bp.post("/privacy/state-law-rules")
def create_state_law_rule():
    require_roles("PrivacyAdmin")
    body = get_body()
    state_code = body.get("state_code")
    if isinstance(state_code, str) and any(
            r["state_code"] == state_code for r in db.state_law_rules.values()):
        raise ApiError("ERR_DUPLICATE_KEY", "state_code already exists")
    law_name = body.get("law_name")
    resident_records_threshold = body.get("resident_records_threshold")
    revenue_share_threshold_pct = body.get("revenue_share_threshold_pct")
    request_deadline_days = body.get("request_deadline_days")
    extension_days = body.get("extension_days")
    if (not isinstance(state_code, str) or len(state_code) != 2
            or not state_code.isalpha()):
        raise ApiError("ERR_INVALID_REQUEST", "state_code must be a 2-letter code")
    if not isinstance(law_name, str) or not law_name:
        raise ApiError("ERR_INVALID_REQUEST", "law_name is required")
    if not is_int(resident_records_threshold) or resident_records_threshold <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "resident_records_threshold must be an integer > 0")
    if (not is_num(revenue_share_threshold_pct)
            or not (0 < revenue_share_threshold_pct <= 100)):
        raise ApiError("ERR_INVALID_REQUEST",
                       "revenue_share_threshold_pct must be in (0, 100]")
    if not is_int(request_deadline_days) or request_deadline_days <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "request_deadline_days must be an integer > 0")
    if not is_int(extension_days) or extension_days < 0:
        raise ApiError("ERR_INVALID_REQUEST", "extension_days must be an integer >= 0")
    rule = base_entity()
    rule.update({
        "state_code": state_code,
        "law_name": law_name,
        "resident_records_threshold": resident_records_threshold,
        "revenue_share_threshold_pct": revenue_share_threshold_pct,
        "request_deadline_days": request_deadline_days,
        "extension_days": extension_days,
    })
    db.state_law_rules[rule["id"]] = rule
    return success(ser_state_law_rule(rule), 201)
