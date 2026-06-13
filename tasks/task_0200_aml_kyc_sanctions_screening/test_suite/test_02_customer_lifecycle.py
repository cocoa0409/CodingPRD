"""Customer CDD lifecycle: cyclic transitions, EDD routing, and account cascades."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_customer_payload, create_legal_entity_payload, create_risk_assessment_payload,
    create_account_payload,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

CO = TEST_USERS["compliance_officer_headers"]


# ==========================================================================
# Queue A — non_linear_state_machine (cyclic customer)
# ==========================================================================
def test_customer_cyclic_approved_to_edd_back_to_approved(api):
    """PRD §3.5: "Most importantly, if the owning customer is currently
    `APPROVED`, confirming a derogatory hit drives that customer from `APPROVED`
    to `EDD_REQUIRED`: this is the cyclic revision edge."
    PRD §3.1: "Completing enhanced due diligence is the transition out of
    `EDD_REQUIRED` back to `APPROVED`; it is permitted only when the customer is
    in `EDD_REQUIRED` and `open_hit_count` is zero, and it carries the same
    approval cascades."

    Design: Difficulty/non_linear_state_machine/customer_cyclic_approved_to_edd_back_to_approved
    """
    cust = fx.create_approved_customer(
        factors=dict(geography_factor=1, product_factor=1, pep_factor=1, adverse_media_factor=1),
        date_of_birth="1990-03-03")
    cid = cust["id"]
    assert cust["cdd_status"] == "APPROVED"

    hit = validate_success(api.create_screening_hit(
        cid, {"list_type": "OFAC_SDN", "matched_name": "Cycle Co", "match_score": 0.98}, CO), 201)
    validate_success(api.disposition_hit(hit["id"], {"decision": "ESCALATE"}, CO))
    confirmed = validate_success(api.disposition_hit(hit["id"], {"decision": "CONFIRM"}, CO))
    assert confirmed["disposition"] == "CONFIRMED"

    after_confirm = validate_success(api.get_customer(cid, CO))
    assert after_confirm["cdd_status"] == "EDD_REQUIRED"

    # open_hit_count is now 0 (CONFIRMED is terminal, not in PENDING/ESCALATED set),
    # so complete-edd returns the customer to APPROVED (revisited).
    completed = validate_success(api.complete_edd(cid, CO))
    assert completed["cdd_status"] == "APPROVED"


def test_complete_edd_returns_high_customer_to_approved(api):
    """PRD §3.1: "From `SCREENING_CLEARED`, approval routes the customer either to
    `APPROVED` or, when enhanced due diligence is outstanding, to `EDD_REQUIRED`."
    PRD §3.1: "Completing enhanced due diligence is the transition out of
    `EDD_REQUIRED` back to `APPROVED`; it is permitted only when the customer is
    in `EDD_REQUIRED` and `open_hit_count` is zero".

    A HIGH customer routes SCREENING_CLEARED -> EDD_REQUIRED on approve, then
    EDD_REQUIRED -> APPROVED on complete-edd.

    Design: Difficulty/non_linear_state_machine/customer_cyclic_approved_to_edd_back_to_approved
    """
    rated = fx.create_and_rate_customer(
        factors=dict(geography_factor=5, product_factor=4, pep_factor=4, adverse_media_factor=4),
        legal_entity=True)
    assert rated["risk_rating"] == "HIGH"
    cid = rated["id"]
    validate_success(api.clear_screening(cid, CO))
    after_approve = validate_success(api.approve_customer(cid, CO))
    assert after_approve["cdd_status"] == "EDD_REQUIRED"
    completed = validate_success(api.complete_edd(cid, CO))
    assert completed["cdd_status"] == "APPROVED"


# ==========================================================================
# Queue A — transitive_cascade (confirm hit -> customer -> accounts)
# ==========================================================================
def test_confirm_hit_cascade_depth3_account_repends(api):
    """PRD §3.5: "Most importantly, if the owning customer is currently
    `APPROVED`, confirming a derogatory hit drives that customer from `APPROVED`
    to `EDD_REQUIRED`: this is the cyclic revision edge. As part of that customer
    transition, `edd_required` is forced true and every account of the customer
    whose `kyc_status` is `KYC_OK` is cascaded back to `PENDING_KYC`, reopening
    account-level diligence."

    Design: Difficulty/transitive_cascade/confirm_hit_cascade_depth3_customer_then_accounts
    """
    cust = create_customer_payload(legal_name="Casc Co", date_of_birth="1985-06-06")
    customer = validate_success(api.create_customer(cust, CO), 201)
    cid = customer["id"]
    acct = validate_success(api.create_account(cid, create_account_payload(account_ref="AC-CASC-1"), CO), 201)
    ra = validate_success(api.create_risk_assessment(
        cid, create_risk_assessment_payload(variant="PROVISIONAL", geography_factor=1,
                                            product_factor=1, pep_factor=1, adverse_media_factor=1), CO), 201)
    validate_success(api.apply_rating(
        cid, {"risk_assessment_id": ra["id"], "expected_customer_version": customer["version"]}, CO))
    validate_success(api.clear_screening(cid, CO))
    approved = validate_success(api.approve_customer(cid, CO))
    assert approved["cdd_status"] == "APPROVED"
    # account cascaded PENDING_KYC -> KYC_OK on approval
    acct_after_approve = validate_success(api.get_account(acct["id"], CO))
    assert acct_after_approve["kyc_status"] == "KYC_OK"

    hit = validate_success(api.create_screening_hit(
        cid, {"list_type": "EU_SANCTIONS", "matched_name": "Casc Co", "match_score": 0.96}, CO), 201)
    validate_success(api.disposition_hit(hit["id"], {"decision": "ESCALATE"}, CO))
    confirmed = validate_success(api.disposition_hit(hit["id"], {"decision": "CONFIRM"}, CO))

    assert confirmed["disposition"] == "CONFIRMED"  # link 1
    cust_after = validate_success(api.get_customer(cid, CO))
    assert cust_after["cdd_status"] == "EDD_REQUIRED"  # link 2, caused by link 1
    acct_after = validate_success(api.get_account(acct["id"], CO))
    assert acct_after["kyc_status"] == "PENDING_KYC"  # link 3, caused by link 2


def test_confirm_hit_forces_edd_required_true(api):
    """PRD §3.5: "Confirming a hit is the most consequential disposition. It
    recomputes `open_hit_count`, sets the customer's `edd_required` to true".
    PRD §3.5: "As part of that customer transition, `edd_required` is forced true
    and every account of the customer whose `kyc_status` is `KYC_OK` is cascaded
    back to `PENDING_KYC`, reopening account-level diligence."

    The intermediate (link-2) mutation that the depth-3 chain rides on: the
    customer's edd_required is forced true by the CONFIRM, independent of the
    downstream account re-pend.

    Design: Difficulty/transitive_cascade/confirm_hit_cascade_depth3_customer_then_accounts
    """
    cust = fx.create_approved_customer(
        factors=dict(geography_factor=1, product_factor=1, pep_factor=1, adverse_media_factor=1),
        legal_entity=True, legal_name="Casc2 Co")
    cid = cust["id"]
    hit = validate_success(api.create_screening_hit(
        cid, {"list_type": "OFAC_SDN", "matched_name": "Casc2 Co", "match_score": 0.99}, CO), 201)
    validate_success(api.disposition_hit(hit["id"], {"decision": "ESCALATE"}, CO))
    validate_success(api.disposition_hit(hit["id"], {"decision": "CONFIRM"}, CO))
    after = validate_success(api.get_customer(cid, CO))
    assert after["cdd_status"] == "EDD_REQUIRED"
    assert after["edd_required"] is True


# ==========================================================================
# Queue B — state_machines & calculations on the customer machine
# ==========================================================================
def test_initial_state_customer_starts_new(api):
    """PRD §3.1: "A newly created customer begins life in `NEW` `cdd_status` with
    a null `risk_rating` and null `risk_score`."

    Design: Corner/state_machines/initial_state_customer_starts_new
    """
    cust = validate_success(api.create_customer(
        create_customer_payload(legal_name="Init Co", date_of_birth="1984-04-04"), CO), 201)
    assert cust["cdd_status"] == "NEW"


def test_clear_screening_from_new_returns_invalid_state(api):
    """PRD §3.1: "Clearing screening moves a customer from `RISK_RATED` to
    `SCREENING_CLEARED`. It is permitted only when the customer is in
    `RISK_RATED`".
    PRD §2.7: "State-machine legality of a requested transition
    (`ERR_INVALID_STATE`) is then checked for all transition endpoints".

    Design: Corner/state_machines/clear_screening_from_new_returns_invalid_state
    """
    cust = validate_success(api.create_customer(
        create_customer_payload(legal_name="Early Co", date_of_birth="1985-05-05"), CO), 201)
    validate_error(api.clear_screening(cust["id"], CO), ApiErrorId.ERR_INVALID_STATE.value)


def test_prohibited_rating_auto_rejects_and_locks(api):
    """PRD §3.1: "If the applied band is `PROHIBITED`, the customer is immediately
    driven to the terminal `REJECTED` state".
    PRD §2.7: "State-machine legality of a requested transition
    (`ERR_INVALID_STATE`) is then checked for all transition endpoints".

    A PROHIBITED-rated customer is REJECTED (terminal); a subsequent
    clear-screening is not a defined transition -> ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_state_rejected_customer_locks_transitions
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="Proh Co", date_of_birth="1960-06-06"), CO), 201)
    cid = customer["id"]
    ra = validate_success(api.create_risk_assessment(
        cid, create_risk_assessment_payload(variant="PROVISIONAL", geography_factor=5,
                                            product_factor=5, pep_factor=5, adverse_media_factor=5), CO), 201)
    rated = validate_success(api.apply_rating(
        cid, {"risk_assessment_id": ra["id"], "expected_customer_version": customer["version"]}, CO))
    assert rated["cdd_status"] == "REJECTED"
    validate_error(api.clear_screening(cid, CO), ApiErrorId.ERR_INVALID_STATE.value)


def test_prohibited_rating_cascades_account_blocked_frozen(api):
    """PRD §3.1: "If the applied band is `PROHIBITED`, the customer is immediately
    driven to the terminal `REJECTED` state and, as a cascade, every account of
    that customer whose `monitoring_status` is not already `FROZEN` has its
    `kyc_status` set to `KYC_BLOCKED` and its `monitoring_status` set to
    `FROZEN`."

    Design: Corner/state_machines/prohibited_rating_cascades_account_blocked_frozen
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="Casc Proh", date_of_birth="1961-06-06"), CO), 201)
    cid = customer["id"]
    acct = validate_success(api.create_account(cid, create_account_payload(account_ref="AC-PROH-1"), CO), 201)
    ra = validate_success(api.create_risk_assessment(
        cid, create_risk_assessment_payload(variant="PROVISIONAL", geography_factor=5,
                                            product_factor=5, pep_factor=5, adverse_media_factor=5), CO), 201)
    validate_success(api.apply_rating(
        cid, {"risk_assessment_id": ra["id"], "expected_customer_version": customer["version"]}, CO))
    acct_after = validate_success(api.get_account(acct["id"], CO))
    assert acct_after["kyc_status"] == "KYC_BLOCKED"
    assert acct_after["monitoring_status"] == "FROZEN"


def test_approve_cascades_pending_kyc_to_kyc_ok(api):
    """PRD §3.1: "On reaching `APPROVED` — whether directly from
    `SCREENING_CLEARED` or later from `EDD_REQUIRED` — the system sets
    `periodic_review_due_at` (see §3.3) and cascades each of the customer's
    accounts whose `kyc_status` is `PENDING_KYC` to `KYC_OK`."

    Design: Corner/state_machines/approve_cascades_pending_kyc_to_kyc_ok
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="Appr Co", date_of_birth="1986-06-06"), CO), 201)
    cid = customer["id"]
    acct = validate_success(api.create_account(cid, create_account_payload(account_ref="AC-APPR-1"), CO), 201)
    ra = validate_success(api.create_risk_assessment(
        cid, create_risk_assessment_payload(variant="PROVISIONAL", geography_factor=1,
                                            product_factor=1, pep_factor=1, adverse_media_factor=1), CO), 201)
    validate_success(api.apply_rating(
        cid, {"risk_assessment_id": ra["id"], "expected_customer_version": customer["version"]}, CO))
    validate_success(api.clear_screening(cid, CO))
    approved = validate_success(api.approve_customer(cid, CO))
    assert approved["cdd_status"] == "APPROVED"
    acct_after = validate_success(api.get_account(acct["id"], CO))
    assert acct_after["kyc_status"] == "KYC_OK"


def test_high_rated_customer_routes_to_edd_on_approve(api):
    """PRD §3.1: "From `SCREENING_CLEARED`, approval routes the customer either to
    `APPROVED` or, when enhanced due diligence is outstanding, to
    `EDD_REQUIRED`."
    PRD §2.12: "enhanced due diligence is required when the customer's
    `risk_rating` is `HIGH`, or when `open_hit_count` is greater than zero, or
    when the customer has any screening hit that is both `CONFIRMED` and
    derogatory."

    Design: Corner/state_machines/high_rated_customer_routes_to_edd_required_on_approve
    """
    rated = fx.create_and_rate_customer(
        factors=dict(geography_factor=5, product_factor=4, pep_factor=4, adverse_media_factor=4),
        legal_entity=True)
    cid = rated["id"]
    assert rated["risk_rating"] == "HIGH"
    assert rated["edd_required"] is True
    validate_success(api.clear_screening(cid, CO))
    after = validate_success(api.approve_customer(cid, CO))
    assert after["cdd_status"] == "EDD_REQUIRED"


def test_idempotent_double_offboard_returns_invalid_state(api):
    """PRD §3.1: "An `APPROVED` customer may be offboarded by a
    `ComplianceOfficer`, moving it to the terminal `OFFBOARDED` state".
    PRD §2.7: "State-machine legality of a requested transition
    (`ERR_INVALID_STATE`) is then checked for all transition endpoints".

    Design: Corner/state_machines/idempotent_double_offboard_returns_invalid_state
    """
    cust = fx.create_approved_customer(
        factors=dict(geography_factor=1, product_factor=1, pep_factor=1, adverse_media_factor=1),
        date_of_birth="1987-07-07")
    cid = cust["id"]
    validate_success(api.offboard_customer(cid, CO))
    validate_error(api.offboard_customer(cid, CO), ApiErrorId.ERR_INVALID_STATE.value)


def test_review_cadence_high_90_days(api):
    """PRD §3.3: "The due instant is the customer's `created_at` advanced by a
    whole number of days that depends on the customer's risk band: 90 days for a
    `HIGH`-rated customer, 180 days for a `MEDIUM`-rated customer, and 365 days
    for a `LOW`-rated customer."

    Design: Corner/calculations/review_cadence_high_90_days
    """
    rated = fx.create_and_rate_customer(
        factors=dict(geography_factor=5, product_factor=4, pep_factor=4, adverse_media_factor=4),
        legal_entity=True, legal_name="Cad Co")
    cid = rated["id"]
    created_at = rated["created_at"]
    assert rated["risk_rating"] == "HIGH"
    validate_success(api.clear_screening(cid, CO))
    after_approve = validate_success(api.approve_customer(cid, CO))
    assert after_approve["cdd_status"] == "EDD_REQUIRED"
    completed = validate_success(api.complete_edd(cid, CO))
    assert completed["cdd_status"] == "APPROVED"
    due = completed["periodic_review_due_at"]
    assert due is not None
    # created_at + 90 days, whole UTC days.
    from datetime import datetime, timedelta
    c = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    d = datetime.fromisoformat(due.replace("Z", "+00:00"))
    assert (d - c) == timedelta(days=90), f"expected +90d, got {d - c}"


def test_offboard_cascades_all_accounts_frozen_blocked(api):
    """PRD §3.1: "An `APPROVED` customer may be offboarded by a
    `ComplianceOfficer`, moving it to the terminal `OFFBOARDED` state; as a
    cascade, every account whose `monitoring_status` is not already `FROZEN` has
    its `monitoring_status` set to `FROZEN` and its `kyc_status` set to
    `KYC_BLOCKED`."

    Design: Corner/cross_cutting_complexity_layers/cascade_offboard_freezes_all_accounts
    """
    customer = validate_success(api.create_customer(
        create_legal_entity_payload(legal_name="Multi Co", incorporation_date="1982-02-02"), CO), 201)
    cid = customer["id"]
    acct1 = validate_success(api.create_account(cid, create_account_payload(account_ref="AC-MUL-1"), CO), 201)
    acct2 = validate_success(api.create_account(cid, create_account_payload(account_ref="AC-MUL-2"), CO), 201)
    ra = validate_success(api.create_risk_assessment(
        cid, create_risk_assessment_payload(variant="PROVISIONAL", geography_factor=1,
                                            product_factor=1, pep_factor=1, adverse_media_factor=1), CO), 201)
    validate_success(api.apply_rating(
        cid, {"risk_assessment_id": ra["id"], "expected_customer_version": customer["version"]}, CO))
    validate_success(api.clear_screening(cid, CO))
    validate_success(api.approve_customer(cid, CO))
    validate_success(api.offboard_customer(cid, CO))
    a1 = validate_success(api.get_account(acct1["id"], CO))
    a2 = validate_success(api.get_account(acct2["id"], CO))
    assert a1["kyc_status"] == "KYC_BLOCKED" and a1["monitoring_status"] == "FROZEN"
    assert a2["kyc_status"] == "KYC_BLOCKED" and a2["monitoring_status"] == "FROZEN"
