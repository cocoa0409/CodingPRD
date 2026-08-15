"""Permit cases and emissions certificates: cycles, fees, expiry, tier gates (PRD §3.4, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_certificate,
    get_success_data,
    set_clock,
    setup_approved_permit,
    setup_authorized_order,
    setup_locked_configuration,
    setup_submitted_permit,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_permit_case_payload

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
APP_ENG = TEST_USERS["application_engineer_headers"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/permit_case_correction_cycle
# ---------------------------------------------------------------------------

def test_permit_correction_cycle_increments_revision_and_fees(api):
    """PRD §3.4: "A correction cycle is resubmitted by the `ComplianceOfficer`:
    resubmission from `CORRECTION_REQUESTED` is allowed only while the current
    logical-clock date is on or before `expires_on` — after that it is rejected
    with `ERR_PERMIT_EXPIRED` — and each such cycle increments `revision_count`
    by 1, restamps `submitted_on` and `expires_on` from the current clock, and
    adds the `resubmission_fee_cents` into `total_fees_paid_cents`."

    US_TX: base 100000 + resubmission 50000 = 150000 after one cycle; the
    resubmission at default clock 2026-08-01 re-derives expires_on 2026-09-15
    (45 days).

    Design: Difficulty/non_linear_state_machine/permit_case_correction_cycle
    """
    ctx = setup_submitted_permit()
    permit = ctx["permit"]
    assert permit["status"] == "SUBMITTED"
    assert permit["submitted_on"] == "2026-08-01"
    assert permit["expires_on"] == "2026-09-15"

    corrected = get_success_data(api_client.request_permit_correction(permit["id"], ADMIN))
    assert corrected["status"] == "CORRECTION_REQUESTED"

    resubmitted = get_success_data(api_client.submit_permit_case(permit["id"], COMPLIANCE))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1
    assert resubmitted["total_fees_paid_cents"] == 150000
    assert resubmitted["expires_on"] == "2026-09-15"


def test_permit_correction_cycle_is_repeatable(api):
    """PRD §3.4: "The authority side of the desk is played by `PlatformAdmin`.
    From `SUBMITTED`, the authority may request corrections — the `SUBMITTED` →
    `CORRECTION_REQUESTED` move..." and each cycle "increments `revision_count`
    by 1... and adds the `resubmission_fee_cents` into `total_fees_paid_cents`."

    A second correction cycle takes revision_count to 2 and total fees to
    100000 + 2*50000 = 200000.

    Design: Difficulty/non_linear_state_machine/permit_case_correction_cycle
    """
    ctx = setup_submitted_permit()
    permit = ctx["permit"]
    get_success_data(api_client.request_permit_correction(permit["id"], ADMIN))
    get_success_data(api_client.submit_permit_case(permit["id"], COMPLIANCE))
    get_success_data(api_client.request_permit_correction(permit["id"], ADMIN))
    resubmitted = get_success_data(api_client.submit_permit_case(permit["id"], COMPLIANCE))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 2
    assert resubmitted["total_fees_paid_cents"] == 200000


# ---------------------------------------------------------------------------
# Corner/state_machines/permit_expire_check_before_expiry_rejected
# ---------------------------------------------------------------------------

def test_permit_expire_check_at_expiry_date_rejected(api):
    """PRD §3.4: "The authority may also expire a `SUBMITTED` case via an expiry
    check, which succeeds only when the logical-clock date is strictly greater
    than `expires_on` — a date equal to `expires_on` does not expire, and the
    check then fails with `ERR_PERMIT_NOT_EXPIRED`; a successful check moves the
    case to `EXPIRED`."

    Design: Corner/state_machines/permit_expire_check_before_expiry_rejected
    """
    ctx = setup_submitted_permit()
    permit = ctx["permit"]
    assert permit["expires_on"] == "2026-09-15"
    set_clock("2026-09-15T00:00:00Z")
    resp = api_client.expire_check_permit(permit["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_EXPIRED)
    current = get_success_data(api_client.get_permit_case(permit["id"], ADMIN))
    assert current["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Corner/state_machines/permit_expire_check_after_expiry_succeeds
# ---------------------------------------------------------------------------

def test_permit_expire_check_after_expiry_succeeds(api):
    """PRD §3.4: "The authority may also expire a `SUBMITTED` case via an expiry
    check, which succeeds only when the logical-clock date is strictly greater
    than `expires_on` — a date equal to `expires_on` does not expire, and the
    check then fails with `ERR_PERMIT_NOT_EXPIRED`; a successful check moves the
    case to `EXPIRED`."

    At 2026-09-16 (one day past the 2026-09-15 expiry), the check succeeds and
    the permit lands in EXPIRED.

    Design: Corner/state_machines/permit_expire_check_after_expiry_succeeds
    """
    ctx = setup_submitted_permit()
    permit = ctx["permit"]
    set_clock("2026-09-16T00:00:00Z")
    expired = validate_success(api_client.expire_check_permit(permit["id"], ADMIN))
    assert expired["status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Corner/state_machines/resubmit_after_expiry_rejected
# ---------------------------------------------------------------------------

def test_resubmit_after_expiry_rejected(api):
    """PRD §3.4: "resubmission from `CORRECTION_REQUESTED` is allowed only while
    the current logical-clock date is on or before `expires_on` — after that it
    is rejected with `ERR_PERMIT_EXPIRED`..."

    Design: Corner/state_machines/resubmit_after_expiry_rejected
    """
    ctx = setup_submitted_permit()
    permit = ctx["permit"]
    get_success_data(api_client.request_permit_correction(permit["id"], ADMIN))
    set_clock("2026-09-20T00:00:00Z")
    resp = api_client.submit_permit_case(permit["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_PERMIT_EXPIRED)
    current = get_success_data(api_client.get_permit_case(permit["id"], COMPLIANCE))
    assert current["status"] == "CORRECTION_REQUESTED"


# ---------------------------------------------------------------------------
# Corner/calculations/permit_fee_locale_constants
# ---------------------------------------------------------------------------

def test_permit_fee_locale_constants_us_ca(api):
    """PRD §3.4: "the fee schedule is derived from that jurisdiction: the
    `base_fee_cents` is 250000 for `US_CA`, 175000 for `DE`, and 100000
    otherwise, and the `resubmission_fee_cents` is half the base fee rounded
    half-up to whole cents."

    A US_CA permit accrues base 250000 on first submission plus resubmission
    125000 on the correction cycle: 375000 total.

    Design: Corner/calculations/permit_fee_locale_constants
    """
    ctx = setup_locked_configuration(
        customer_overrides={"primary_locale": "US_CA"},
        order_overrides={"site_locale": "US_CA"},
        engine_overrides={"emissions_tier_capability": "TIER_4_FINAL_CARB"},
        configuration_overrides={"fuel_tank_gallons": 500},
    )
    permit = get_success_data(api_client.create_permit_case(
        create_permit_case_payload(
            order_id=ctx["order"]["id"], configuration_id=ctx["configuration"]["id"]
        ),
        COMPLIANCE,
    ))
    assert permit["base_fee_cents"] == 250000
    assert permit["resubmission_fee_cents"] == 125000

    get_success_data(api_client.submit_permit_case(permit["id"], COMPLIANCE))
    get_success_data(api_client.request_permit_correction(permit["id"], ADMIN))
    resubmitted = get_success_data(api_client.submit_permit_case(permit["id"], COMPLIANCE))
    assert resubmitted["total_fees_paid_cents"] == 375000


# ---------------------------------------------------------------------------
# Corner/calculations/emissions_tier_locale_branching_constants
# ---------------------------------------------------------------------------

def _cert_for_locale(site_locale, application, engine_tier):
    ctx = setup_locked_configuration(
        customer_overrides={"primary_locale": site_locale},
        order_overrides={"site_locale": site_locale, "application": application},
        engine_overrides={"emissions_tier_capability": engine_tier},
        configuration_overrides={"fuel_tank_gallons": 500},
    )
    cert = create_certificate(ctx["order"]["id"], ctx["configuration"]["id"])
    return cert


def test_emissions_required_tier_by_locale(api):
    """PRD §3.5: "The `required_tier` follows the order's `site_locale`: `US_CA`
    demands `TIER_4_FINAL_CARB`, `DE` demands `STAGE_V`, and anything else
    demands `EPA_TIER_4`."

    Design: Corner/calculations/emissions_tier_locale_branching_constants
    """
    cert_ca = _cert_for_locale("US_CA", "STANDBY", "STAGE_V")
    cert_de = _cert_for_locale("DE", "STANDBY", "STAGE_V")
    cert_tx = _cert_for_locale("US_TX", "STANDBY", "STAGE_V")
    assert cert_ca["required_tier"] == "TIER_4_FINAL_CARB"
    assert cert_de["required_tier"] == "STAGE_V"
    assert cert_tx["required_tier"] == "EPA_TIER_4"


def test_emissions_requires_hour_log_when_prime(api):
    """PRD §3.5: "The boolean `requires_hour_log` is true exactly when the
    order's `application` is `PRIME`."

    Design: Corner/calculations/emissions_tier_locale_branching_constants
    """
    cert_prime = _cert_for_locale("DE", "PRIME", "STAGE_V")
    cert_standby = _cert_for_locale("DE", "STANDBY", "STAGE_V")
    assert cert_prime["requires_hour_log"] is True
    assert cert_standby["requires_hour_log"] is False


# ---------------------------------------------------------------------------
# Corner/calculations/hour_log_required_prime_submit_rejected
# ---------------------------------------------------------------------------

def test_hour_log_required_prime_submit_rejected(api):
    """PRD §3.5: "Submission — by the `ComplianceOfficer`, from `APP_DRAFT`, and
    again from `REJECTED` after an authority rejection — requires the
    configuration to be `LOCKED` or `RELEASED` (otherwise
    `ERR_CONFIG_STATE_INVALID`), and when `requires_hour_log` is true the
    submission must carry `hour_log_attached` as true, else it is rejected with
    `ERR_HOUR_LOG_REQUIRED`; the submit call accepts an `hour_log_attached`
    value so the log can be attached at submit time."

    Design: Corner/calculations/hour_log_required_prime_submit_rejected
    """
    ctx = setup_locked_configuration(
        customer_overrides={"primary_locale": "DE"},
        order_overrides={"site_locale": "DE", "application": "PRIME"},
        engine_overrides={"emissions_tier_capability": "STAGE_V"},
        configuration_overrides={"fuel_tank_gallons": 500},
    )
    cert = create_certificate(ctx["order"]["id"], ctx["configuration"]["id"])
    assert cert["requires_hour_log"] is True

    resp = api_client.submit_emissions_certificate(cert["id"], {}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_HOUR_LOG_REQUIRED)

    submitted = validate_success(api_client.submit_emissions_certificate(
        cert["id"], {"hour_log_attached": True}, COMPLIANCE
    ))
    assert submitted["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Corner/validations/emissions_tier_insufficient_on_submitted_cert
# ---------------------------------------------------------------------------

def test_emissions_tier_insufficient_on_submitted_cert(api):
    """PRD §3.5: "Issuance applies the tier ladder — `TIER_2` ranks 1,
    `EPA_TIER_4` ranks 2, `STAGE_V` ranks 3, `TIER_4_FINAL_CARB` ranks 4 — and
    the engine's tier rank must be at least the required tier's rank, or
    issuance fails with `ERR_EMISSIONS_TIER_INSUFFICIENT`."

    A SUBMITTED US_CA certificate (required rank 4) on an EPA_TIER_4 engine
    (rank 2) fails issuance.

    Design: Corner/validations/emissions_tier_insufficient_on_submitted_cert
    """
    ctx = setup_locked_configuration(
        customer_overrides={"primary_locale": "US_CA"},
        order_overrides={"site_locale": "US_CA"},
        engine_overrides={"emissions_tier_capability": "EPA_TIER_4"},
        configuration_overrides={"fuel_tank_gallons": 500},
    )
    cert = create_certificate(ctx["order"]["id"], ctx["configuration"]["id"])
    assert cert["required_tier"] == "TIER_4_FINAL_CARB"
    assert cert["engine_tier"] == "EPA_TIER_4"
    cert = get_success_data(api_client.submit_emissions_certificate(cert["id"], {}, COMPLIANCE))
    resp = api_client.issue_emissions_certificate(cert["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMISSIONS_TIER_INSUFFICIENT)
    current = get_success_data(api_client.get_emissions_certificate(cert["id"], COMPLIANCE))
    assert current["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/state_vs_safety_on_cert_issue
# ---------------------------------------------------------------------------

def test_cert_issue_state_check_precedes_tier_safety(api):
    """PRD §2.8: "...then state-machine from-state checks, then business rules
    in the order: emissions and locale safety, segregation of duties, capacity
    and overlap constraints, clock-relative temporal windows, cross-entity
    referential requirements, and finally fiscal gates such as the credit check."

    Issuing a certificate still in APP_DRAFT (state violation) on a US_CA order
    whose EPA_TIER_4 engine cannot satisfy TIER_4_FINAL_CARB (safety violation)
    returns ERR_CERT_STATE_INVALID — the from-state check runs before the
    emissions-safety rule.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_cert_issue
    """
    ctx = setup_locked_configuration(
        customer_overrides={"primary_locale": "US_CA"},
        order_overrides={"site_locale": "US_CA"},
        engine_overrides={"emissions_tier_capability": "EPA_TIER_4"},
        configuration_overrides={"fuel_tank_gallons": 500},
    )
    cert = create_certificate(ctx["order"]["id"], ctx["configuration"]["id"])
    assert cert["required_tier"] == "TIER_4_FINAL_CARB"
    assert cert["status"] == "APP_DRAFT"
    resp = api_client.issue_emissions_certificate(cert["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CERT_STATE_INVALID)


def test_cert_issue_draft_certificate_rejected_regardless_of_tier(api):
    """PRD §2.8: "...then state-machine from-state checks, then business rules
    in the order: emissions and locale safety..." — the from-state check gates
    even when the engine tier would satisfy the requirement.

    An APP_DRAFT certificate on a fully capable TIER_4_FINAL_CARB engine is
    still rejected with ERR_CERT_STATE_INVALID.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_cert_issue
    """
    ctx = setup_locked_configuration(
        customer_overrides={"primary_locale": "US_CA"},
        order_overrides={"site_locale": "US_CA"},
        engine_overrides={"emissions_tier_capability": "TIER_4_FINAL_CARB"},
        configuration_overrides={"fuel_tank_gallons": 500},
    )
    cert = create_certificate(ctx["order"]["id"], ctx["configuration"]["id"])
    assert cert["engine_tier"] == "TIER_4_FINAL_CARB"
    assert cert["status"] == "APP_DRAFT"
    resp = api_client.issue_emissions_certificate(cert["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CERT_STATE_INVALID)
    current = get_success_data(api_client.get_emissions_certificate(cert["id"], COMPLIANCE))
    assert current["status"] == "APP_DRAFT"
