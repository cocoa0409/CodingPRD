"""Payload factories — one per write endpoint, client-supplied fields only.

Monetary values are integer numbers of cents and are emitted as Python ints,
never as strings.
"""

from .constants import TEST_DEFAULTS


# --- Installation -----------------------------------------------------------


def create_installation_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["INSTALLATION_NAME"],
        "branch": TEST_DEFAULTS["BRANCH"],
        "mha_code": TEST_DEFAULTS["MHA_CODE"],
        "bill_of_rights_version": TEST_DEFAULTS["BILL_OF_RIGHTS_VERSION"],
    }
    payload.update(overrides)
    return payload


# --- BahRate ----------------------------------------------------------------


def create_bah_rate_payload(installation_id: str, **overrides) -> dict:
    payload = {
        "installation_id": installation_id,
        "pay_grade": "E5",
        "with_dependents": True,
        "effective_year": 2026,
        "monthly_rate_cents": TEST_DEFAULTS["E5_MONTHLY_RATE_CENTS"],
        "utility_allowance_cents": TEST_DEFAULTS["E5_UTILITY_ALLOWANCE_CENTS"],
    }
    payload.update(overrides)
    return payload


# --- HousingUnit ------------------------------------------------------------


def create_housing_unit_payload(installation_id: str, **overrides) -> dict:
    payload = {
        "installation_id": installation_id,
        "unit_code": "A-101",
        "bedroom_count": 2,
        "unit_type": "TOWNHOME",
        "designated_rank_category": "JUNIOR_ENLISTED",
        "historic_flag": False,
    }
    payload.update(overrides)
    return payload


def housing_unit_status_payload(status: str, **overrides) -> dict:
    payload = {"status": status}
    payload.update(overrides)
    return payload


# --- ServiceMember / Dependent / orders -------------------------------------


def create_service_member_payload(**overrides) -> dict:
    payload = {
        "dodid": "1000000001",
        "last_name": "Reyes",
        "first_name": "Ana",
        "branch": "ARMY",
        "pay_grade": "E5",
    }
    payload.update(overrides)
    return payload


def create_dependent_payload(service_member_id: str, **overrides) -> dict:
    payload = {
        "service_member_id": service_member_id,
        "relationship": "CHILD",
        "date_of_birth": "2018-04-10",
        "gender": "MALE",
    }
    payload.update(overrides)
    return payload


def record_orders_payload(**overrides) -> dict:
    """Every field on the orders recording call is optional."""
    payload: dict = {}
    payload.update(overrides)
    return payload


# --- WaitlistApplication ----------------------------------------------------


def create_waitlist_application_payload(
    installation_id: str, service_member_id: str, **overrides
) -> dict:
    payload = {
        "installation_id": installation_id,
        "service_member_id": service_member_id,
        "pcs_orders_date": "2026-08-25",
        "expected_arrival_date": "2026-09-01",
    }
    payload.update(overrides)
    return payload


def recertify_payload(expected_application_version: int, **overrides) -> dict:
    payload = {"expected_application_version": expected_application_version}
    payload.update(overrides)
    return payload


# --- Lease ------------------------------------------------------------------


def create_lease_payload(
    application_id: str, housing_unit_id: str, **overrides
) -> dict:
    payload = {
        "application_id": application_id,
        "housing_unit_id": housing_unit_id,
        "start_date": "2026-09-01",
        "term_months": 12,
    }
    payload.update(overrides)
    return payload


def rent_redetermination_payload(
    expected_lease_version: int, effective_date: str, **overrides
) -> dict:
    payload = {
        "expected_lease_version": expected_lease_version,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def termination_notice_payload(
    termination_reason: str,
    termination_notice_date: str,
    termination_effective_date: str,
    **overrides,
) -> dict:
    payload = {
        "termination_reason": termination_reason,
        "termination_notice_date": termination_notice_date,
        "termination_effective_date": termination_effective_date,
    }
    payload.update(overrides)
    return payload


# --- MoveInInspection -------------------------------------------------------


def create_move_in_inspection_payload(lease_id: str, **overrides) -> dict:
    payload = {"lease_id": lease_id, "scheduled_date": "2026-08-31"}
    payload.update(overrides)
    return payload


def deficiency_entry(
    deficiency_code: str, room: str, severity: str, **overrides
) -> dict:
    entry = {
        "deficiency_code": deficiency_code,
        "room": room,
        "severity": severity,
    }
    entry.update(overrides)
    return entry


def log_deficiencies_payload(entries: list) -> dict:
    return {"deficiencies": entries}


def tenant_acknowledge_payload(
    tenant_signature_name: str, bill_of_rights_version_ack: str
) -> dict:
    return {
        "tenant_signature_name": tenant_signature_name,
        "bill_of_rights_version_ack": bill_of_rights_version_ack,
    }


# --- WorkOrder --------------------------------------------------------------


def create_work_order_payload(housing_unit_id: str, **overrides) -> dict:
    payload = {
        "housing_unit_id": housing_unit_id,
        "category": "COSMETIC",
        "description": "Scuffed baseboard in the hallway",
    }
    payload.update(overrides)
    return payload


def assign_work_order_payload(assigned_tech_user_id: str, **overrides) -> dict:
    payload = {"assigned_tech_user_id": assigned_tech_user_id}
    payload.update(overrides)
    return payload


def reopen_work_order_payload(reopen_reason: str, **overrides) -> dict:
    payload = {"reopen_reason": reopen_reason}
    payload.update(overrides)
    return payload


# --- HazardCase -------------------------------------------------------------


def create_hazard_case_payload(housing_unit_id: str, **overrides) -> dict:
    payload = {
        "housing_unit_id": housing_unit_id,
        "hazard_type": "MOLD",
        "reported_symptoms": "Musty smell and staining behind the bathroom wall",
    }
    payload.update(overrides)
    return payload


def assess_hazard_case_payload(**overrides) -> dict:
    payload = {"child_under_six_present": False}
    payload.update(overrides)
    return payload


def clearance_payload(clearance_test_passed: bool, **overrides) -> dict:
    payload = {"clearance_test_passed": clearance_test_passed}
    payload.update(overrides)
    return payload


def void_hazard_case_payload(void_reason: str = "Case opened in error") -> dict:
    return {"void_reason": void_reason}


# --- DisplacementLodging ----------------------------------------------------


def create_displacement_lodging_payload(
    hazard_case_id: str, lease_id: str, **overrides
) -> dict:
    payload = {
        "hazard_case_id": hazard_case_id,
        "lease_id": lease_id,
        "start_date": "2026-09-20",
        "end_date": "2026-09-30",
        "nightly_rate_cents": 21000,
        "occupants_count": 4,
    }
    payload.update(overrides)
    return payload


def close_lodging_payload(actual_end_date: str) -> dict:
    return {"actual_end_date": actual_end_date}


# --- DisputeCase ------------------------------------------------------------


def create_dispute_case_payload(
    lease_id: str, service_member_id: str, **overrides
) -> dict:
    payload = {
        "lease_id": lease_id,
        "service_member_id": service_member_id,
        "category": "RENT_CHARGE",
        "description": "September rent was charged at the pre-move-in figure",
    }
    payload.update(overrides)
    return payload


def propose_resolution_payload(
    proposed_remedy: str, credit_offer_cents: int, **overrides
) -> dict:
    payload = {
        "proposed_remedy": proposed_remedy,
        "credit_offer_cents": credit_offer_cents,
    }
    payload.update(overrides)
    return payload


def respond_payload(accepted: bool) -> dict:
    return {"accepted": accepted}


def installation_decision_payload(credit_award_cents: int, **overrides) -> dict:
    payload = {"credit_award_cents": credit_award_cents}
    payload.update(overrides)
    return payload


# --- ReinvestmentAccount ----------------------------------------------------


def create_reinvestment_account_payload(installation_id: str, **overrides) -> dict:
    payload = {
        "installation_id": installation_id,
        "fiscal_year": 2026,
        "opening_balance_cents": TEST_DEFAULTS["OPENING_BALANCE_CENTS"],
        "occupancy_basis": "UNIT_DAY_WEIGHTED",
    }
    payload.update(overrides)
    return payload


def expenditure_payload(
    expected_account_version: int, amount_cents: int, **overrides
) -> dict:
    payload = {
        "expected_account_version": expected_account_version,
        "amount_cents": amount_cents,
        "purpose": "Roof replacement on the 400 block",
    }
    payload.update(overrides)
    return payload


def metrics_run_payload(period_month: str, **overrides) -> dict:
    payload = {"period_month": period_month}
    payload.update(overrides)
    return payload


def allotment_run_payload(period_month: str, **overrides) -> dict:
    payload = {"period_month": period_month}
    payload.update(overrides)
    return payload
