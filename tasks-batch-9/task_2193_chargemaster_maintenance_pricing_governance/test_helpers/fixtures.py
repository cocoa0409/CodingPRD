"""Composite setup helpers. Every helper builds its state through declared endpoints only."""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from . import factories as f
from .test_users import (
    TEST_USERS, MANAGER_USER_ID, MANAGER2_USER_ID, ANALYST_USER_ID, ANALYST2_USER_ID,
    APPROVER_USER_ID, APPROVER2_USER_ID, COMPLIANCE_USER_ID, CONTRACT_USER_ID,
    make_manager_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ANALYST2 = TEST_USERS["analyst2_headers"]
APPROVER = TEST_USERS["approver_headers"]
APPROVER2 = TEST_USERS["approver2_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
CONTRACT = TEST_USERS["contract_headers"]


# ---------------------------------------------------------------- clock

def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------- tier 0: roots

def create_facility(**overrides) -> dict:
    return get_success_data(
        api_client.create_facility(f.create_facility_payload(**overrides), ADMIN)
    )


def read_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, ADMIN))


def patch_facility(facility_id: str, **fields) -> dict:
    """PATCH the facility carrying its live version as expected_facility_version."""
    live = read_facility(facility_id)
    payload = {"expected_facility_version": live["version"]}
    payload.update(fields)
    return get_success_data(api_client.update_facility(facility_id, payload, ADMIN))


def create_revenue_code(**overrides) -> dict:
    return get_success_data(
        api_client.create_revenue_code(f.create_revenue_code_payload(**overrides), ADMIN)
    )


def create_department(facility_id: str, manager_user_id: str = MANAGER_USER_ID,
                      **overrides) -> dict:
    return get_success_data(
        api_client.create_department(
            f.create_department_payload(facility_id, manager_user_id, **overrides), ADMIN
        )
    )


def create_price_rule(facility_id: str, revenue_code_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_price_rule(
            f.create_price_rule_payload(facility_id, revenue_code_id, **overrides), ANALYST
        )
    )


def setup_base(facility_overrides=None, revenue_code_overrides=None,
               department_overrides=None, price_rule_overrides=None,
               manager_user_id: str = MANAGER_USER_ID) -> dict:
    """Facility + revenue code + department + one open-ended ACTIVE cost-plus price rule.

    Returns a dict with keys: facility, revenue_code, department, price_rule,
    manager_headers.
    """
    facility = create_facility(**(facility_overrides or {}))
    revenue_code = create_revenue_code(**(revenue_code_overrides or {}))
    department = create_department(
        facility["id"], manager_user_id, **(department_overrides or {})
    )
    price_rule = create_price_rule(
        facility["id"], revenue_code["id"], **(price_rule_overrides or {})
    )
    return {
        "facility": facility,
        "revenue_code": revenue_code,
        "department": department,
        "price_rule": price_rule,
        "manager_headers": make_manager_headers(manager_user_id),
        "manager_user_id": manager_user_id,
    }


# ---------------------------------------------------------------- tier 1: items

def create_item(base: dict, **overrides) -> dict:
    """A DRAFT / PRICE_STALE charge item under the base scenario."""
    payload = f.create_charge_item_payload(
        base["facility"]["id"], base["department"]["id"], base["revenue_code"]["id"], **overrides
    )
    return get_success_data(api_client.create_charge_item(payload, ANALYST))


def read_item(item_id: str) -> dict:
    return get_success_data(api_client.get_charge_item(item_id, ANALYST))


def reprice_item(item_id: str) -> dict:
    return get_success_data(api_client.reprice_charge_item(item_id, ANALYST))


def item_lifecycle(item_id: str, action: str, headers=None, **payload_extras) -> dict:
    payload = {"action": action}
    payload.update(payload_extras)
    if headers is None:
        headers = APPROVER if action in ("APPROVE", "ACTIVATE", "REACTIVATE") else ANALYST
    return get_success_data(api_client.charge_item_lifecycle(item_id, payload, headers))


def create_priced_item(base: dict, **overrides) -> dict:
    """DRAFT item repriced once, so price_status is PRICED_CURRENT."""
    item = create_item(base, **overrides)
    return reprice_item(item["id"])


def create_active_item(base: dict, **overrides) -> dict:
    """Walk a fresh item all the way to ACTIVE / PRICED_CURRENT."""
    item = create_priced_item(base, **overrides)
    item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    item_lifecycle(item["id"], "APPROVE", APPROVER)
    return item_lifecycle(item["id"], "ACTIVATE", APPROVER)


def create_inactive_item(base: dict, **overrides) -> dict:
    """ACTIVE item deactivated back to INACTIVE."""
    item = create_active_item(base, **overrides)
    return item_lifecycle(item["id"], "DEACTIVATE", ANALYST)


def create_archived_item(base: dict, **overrides) -> dict:
    """INACTIVE item archived; ARCHIVED is the only terminal lifecycle state."""
    item = create_inactive_item(base, **overrides)
    return item_lifecycle(item["id"], "ARCHIVE", ANALYST)


def create_pending_review_item(base: dict, **overrides) -> dict:
    item = create_item(base, **overrides)
    return item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST)


def create_approved_item(base: dict, **overrides) -> dict:
    item = create_priced_item(base, **overrides)
    item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    return item_lifecycle(item["id"], "APPROVE", APPROVER)


# ---------------------------------------------------------------- tier 2: change requests

def create_change_request(base: dict, item_id: str, request_type: str = "PRICE_CHANGE",
                          headers=None, **overrides) -> dict:
    payload = f.create_change_request_payload(
        base["department"]["id"], item_id, request_type, **overrides
    )
    return get_success_data(
        api_client.create_change_request(payload, headers or base["manager_headers"])
    )


def read_change_request(request_id: str) -> dict:
    return get_success_data(api_client.get_change_request(request_id, ANALYST))


def decide_change_request(request_id: str, decision: str, headers=None, **extras) -> dict:
    payload = {"decision": decision}
    payload.update(extras)
    return get_success_data(
        api_client.change_request_decision(request_id, payload, headers or ANALYST)
    )


def review_change_request(request_id: str, headers=None, **extras) -> dict:
    return decide_change_request(request_id, "REVIEW", headers or ANALYST, **extras)


def create_reviewed_change_request(base: dict, item_id: str, request_type: str = "PRICE_CHANGE",
                                   **overrides) -> dict:
    """Change request walked SUBMITTED -> UNDER_REVIEW by an analyst who is not the submitter."""
    request = create_change_request(base, item_id, request_type, **overrides)
    return review_change_request(request["id"], ANALYST)


def approve_change_request(request_id: str, expected_charge_item_version: int,
                           headers=None, **extras) -> dict:
    payload = {"expected_charge_item_version": expected_charge_item_version}
    payload.update(extras)
    return get_success_data(
        api_client.approve_change_request(request_id, payload, headers or APPROVER)
    )


def create_approved_change_request(base: dict, item_id: str,
                                    request_type: str = "PRICE_CHANGE", **overrides) -> dict:
    """Change request walked all the way to APPROVED with a fresh item version."""
    request = create_reviewed_change_request(base, item_id, request_type, **overrides)
    live = read_item(item_id)
    return approve_change_request(request["id"], live["version"], APPROVER)


def create_changes_requested_change_request(base: dict, item_id: str,
                                            request_type: str = "PRICE_CHANGE",
                                            **overrides) -> dict:
    request = create_reviewed_change_request(base, item_id, request_type, **overrides)
    return decide_change_request(
        request["id"], "REQUEST_CHANGES", ANALYST, decision_note="Needs more detail."
    )


def resubmit_change_request(request_id: str, headers, **extras) -> dict:
    payload = dict(extras)
    return get_success_data(
        api_client.resubmit_change_request(request_id, payload, headers)
    )


def implement_change_request(request_id: str, **extras) -> dict:
    return get_success_data(
        api_client.implement_change_request(request_id, ANALYST, extras or None)
    )


# ---------------------------------------------------------------- tier 3: payer contracts

def create_payer_contract(facility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_payer_contract(
            f.create_payer_contract_payload(facility_id, **overrides), CONTRACT
        )
    )


def create_analysis(change_request_id: str, variant: str = "FORWARD_PROJECTED",
                    headers=None) -> dict:
    return get_success_data(
        api_client.create_price_change_analysis(
            f.create_price_change_analysis_payload(change_request_id, variant),
            headers or CONTRACT,
        )
    )


# ---------------------------------------------------------------- tier 4: code update cycles

def create_cycle(facility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_code_update_cycle(
            f.create_code_update_cycle_payload(facility_id, **overrides), ANALYST
        )
    )


def create_entry(cycle_id: str, action: str = "CROSSWALK", **overrides) -> dict:
    return get_success_data(
        api_client.create_code_update_entry(
            cycle_id, f.create_code_update_entry_payload(action, **overrides), ANALYST
        )
    )


def cycle_lifecycle(cycle_id: str, action: str, headers=None, **extras) -> dict:
    payload = {"action": action}
    payload.update(extras)
    if headers is None:
        headers = {
            "START_MAPPING": ANALYST,
            "APPROVE_CROSSWALK": APPROVER,
            "ACTIVATE": COMPLIANCE,
            "ROLL_BACK": COMPLIANCE,
            "CANCEL": COMPLIANCE,
        }[action]
    return get_success_data(api_client.code_update_cycle_lifecycle(cycle_id, payload, headers))


def disposition_entry(entry_id: str, action: str, headers=None, **extras) -> dict:
    payload = {"action": action}
    payload.update(extras)
    return get_success_data(
        api_client.disposition_code_update_entry(entry_id, payload, headers or ANALYST)
    )


def read_entry(entry_id: str) -> dict:
    return get_success_data(api_client.get_code_update_entry(entry_id, ANALYST))


def read_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_code_update_cycle(cycle_id, ANALYST))


# ---------------------------------------------------------------- tier 5: charge capture

def create_batch(base: dict, headers=None, **overrides) -> dict:
    facility_id = overrides.pop("facility_id", base["facility"]["id"])
    department_id = overrides.pop("department_id", base["department"]["id"])
    payload = f.create_charge_capture_batch_payload(
        facility_id, department_id, **overrides
    )
    return get_success_data(
        api_client.create_charge_capture_batch(payload, headers or base["manager_headers"])
    )


def append_line(batch_id: str, cdm_number: str, headers, **overrides) -> dict:
    payload = f.create_captured_charge_payload(cdm_number, **overrides)
    return get_success_data(api_client.create_captured_charge(batch_id, payload, headers))


def reconcile_batch(batch_id: str) -> dict:
    return get_success_data(api_client.reconcile_batch(batch_id, ANALYST))


def batch_lifecycle(batch_id: str, action: str, headers=None, **extras) -> dict:
    payload = {"action": action}
    payload.update(extras)
    if headers is None:
        headers = ANALYST
    return get_success_data(api_client.batch_lifecycle(batch_id, payload, headers))


def read_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_charge_capture_batch(batch_id, ANALYST))


def read_department(department_id: str) -> dict:
    return get_success_data(api_client.get_department(department_id, ADMIN))


def list_findings(**params) -> list:
    resp = api_client.list_missing_charge_findings(ANALYST, params=params or None)
    return get_success_data(resp)


def list_captured_charges(**params) -> list:
    resp = api_client.list_captured_charges(ANALYST, params=params or None)
    return get_success_data(resp)


def disposition_finding(finding_id: str, action: str, **extras) -> dict:
    payload = {"action": action}
    payload.update(extras)
    return get_success_data(api_client.disposition_finding(finding_id, payload, ANALYST))


# ---------------------------------------------------------------- tier 6: transparency files

def build_transparency_file(facility_id: str, expected_facility_version: int, **overrides) -> dict:
    payload = f.create_transparency_file_payload(
        facility_id, expected_facility_version, **overrides
    )
    return get_success_data(api_client.create_transparency_file(payload, COMPLIANCE))


def file_lifecycle(file_id: str, action: str, **extras) -> dict:
    payload = {"action": action}
    payload.update(extras)
    return get_success_data(api_client.transparency_file_lifecycle(file_id, payload, COMPLIANCE))


def read_file(file_id: str) -> dict:
    return get_success_data(api_client.get_transparency_file(file_id, COMPLIANCE))


def setup_publishable_facility(**base_overrides) -> dict:
    """Base scenario + one ACTIVE / PRICED_CURRENT item + one ACTIVE payer contract
    whose closed term contains the default logical now, so a build can validate."""
    base = setup_base(**base_overrides)
    item = create_active_item(base)
    contract = create_payer_contract(
        base["facility"]["id"],
        term_start_date="2026-01-01T00:00:00Z",
        term_end_date="2026-12-31T00:00:00Z",
    )
    base["item"] = item
    base["contract"] = contract
    base["facility"] = read_facility(base["facility"]["id"])
    return base


def setup_frozen_facility(**base_overrides) -> dict:
    """Base scenario driven to chargemaster_posture FROZEN by an in-flight build."""
    base = setup_publishable_facility(**base_overrides)
    facility = read_facility(base["facility"]["id"])
    tfile = build_transparency_file(facility["id"], facility["version"])
    base["transparency_file"] = tfile
    base["facility"] = read_facility(facility["id"])
    return base


def setup_validated_file(**base_overrides) -> dict:
    """Base scenario with a VALIDATED transparency file (items frozen)."""
    base = setup_frozen_facility(**base_overrides)
    base["transparency_file"] = file_lifecycle(base["transparency_file"]["id"], "VALIDATE")
    base["facility"] = read_facility(base["facility"]["id"])
    return base


def setup_published_file(**base_overrides) -> dict:
    """Base scenario with a PUBLISHED transparency file and a CURRENT facility."""
    base = setup_validated_file(**base_overrides)
    base["transparency_file"] = file_lifecycle(base["transparency_file"]["id"], "PUBLISH")
    base["facility"] = read_facility(base["facility"]["id"])
    return base


def setup_restricted_by_cycle(**base_overrides) -> dict:
    """Base scenario whose posture is RESTRICTED because a cycle is MAPPING."""
    base = setup_base(**base_overrides)
    item = create_active_item(base, code_type="CPT", code_value="99213")
    cycle = create_cycle(base["facility"]["id"])
    entry = create_entry(cycle["id"], "CROSSWALK", old_code_value="99213",
                         new_code_value="99215")
    cycle_lifecycle(cycle["id"], "START_MAPPING")
    base["item"] = item
    base["cycle"] = cycle
    base["entry"] = entry
    base["facility"] = read_facility(base["facility"]["id"])
    return base
