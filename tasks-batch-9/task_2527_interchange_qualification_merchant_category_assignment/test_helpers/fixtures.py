"""Composite setup builders.

The harness restarts the service before every test, so each test starts against
an empty store and must lay down its own reference layer through the PRD's own
endpoints. These builders do exactly that — every one of them is a sequence of
ordinary API calls whose success is validated, so a failure inside setup fails
loudly instead of surfacing later as a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_acquirer_ops_headers,
    make_category_analyst_headers,
    make_compliance_auditor_headers,
)

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]


# --- The logical clock -----------------------------------------------------

def set_clock(to_iso8601: str, headers: dict = None) -> dict:
    """PRD 4: `POST /_clock/set_current_utc` sets the logical UTC clock and runs
    its three-step sweep. NetworkAdmin only."""
    response = api_client.set_clock(to_iso8601, headers or NETWORK_ADMIN)
    return validate_success(response)


# --- Section 3.1 reference data -------------------------------------------

def create_platform(headers: dict = None, **overrides) -> dict:
    response = api_client.create_processing_platform(
        f.make_processing_platform_payload(**overrides), headers or NETWORK_ADMIN
    )
    return get_success_data(response, 201)


def create_acquirer(platform_id: str, headers: dict = None, **overrides) -> dict:
    response = api_client.create_acquirer(
        f.make_acquirer_payload(platform_id, **overrides), headers or NETWORK_ADMIN
    )
    return get_success_data(response, 201)


def create_mcc(
    mcc_code: str = "5411",
    business_type_key: str = TEST_DEFAULTS["BUSINESS_TYPE_KEY"],
    headers: dict = None,
    **overrides,
) -> dict:
    response = api_client.create_mcc_definition(
        f.make_mcc_definition_payload(mcc_code, business_type_key, **overrides),
        headers or NETWORK_ADMIN,
    )
    return get_success_data(response, 201)


def create_fx_rate(
    base_currency: str,
    quote_currency: str,
    effective_from: str,
    headers: dict = None,
    **overrides,
) -> dict:
    response = api_client.create_fx_rate(
        f.make_fx_rate_payload(base_currency, quote_currency, effective_from, **overrides),
        headers or NETWORK_ADMIN,
    )
    return get_success_data(response, 201)


# --- Section 3.2 rate programs and quarterly versions ---------------------

def create_rate_program(
    program_code: str,
    category: str,
    eligible_mcc_codes=None,
    headers: dict = None,
    **overrides,
) -> dict:
    response = api_client.create_rate_program(
        f.make_rate_program_payload(
            program_code, category, eligible_mcc_codes, **overrides
        ),
        headers or NETWORK_ADMIN,
    )
    return get_success_data(response, 201)


def create_standard_program(
    eligible_mcc_codes=None, headers: dict = None, **overrides
) -> dict:
    """The mandatory `STANDARD` fallback tier. Without it the definitive pass
    has nowhere to route a record and every intake is refused."""
    response = api_client.create_rate_program(
        f.make_standard_program_payload(eligible_mcc_codes, **overrides),
        headers or NETWORK_ADMIN,
    )
    return get_success_data(response, 201)


def draft_rate_version(
    rate_program_id: str,
    publication_quarter: str,
    effective_from: str,
    effective_to: str,
    implementation_deadline: str,
    headers: dict = None,
    **overrides,
) -> dict:
    response = api_client.create_rate_program_version(
        rate_program_id,
        f.make_rate_program_version_payload(
            publication_quarter,
            effective_from,
            effective_to,
            implementation_deadline,
            **overrides,
        ),
        headers or NETWORK_ADMIN,
    )
    return get_success_data(response, 201)


def publish_rate_version(version_id: str, headers: dict = None) -> dict:
    response = api_client.publish_rate_program_version(
        version_id, headers or NETWORK_ADMIN
    )
    return validate_success(response)


def schedule_window(
    acquirer_id: str,
    rate_program_version_id: str,
    platform_id: str,
    window_start: str,
    window_end: str,
    headers: dict = None,
    **overrides,
) -> dict:
    response = api_client.create_implementation_window(
        f.make_implementation_window_payload(
            acquirer_id,
            rate_program_version_id,
            platform_id,
            window_start,
            window_end,
            **overrides,
        ),
        headers if headers is not None else make_acquirer_ops_headers(acquirer_id),
    )
    return get_success_data(response, 201)


def start_window(window_id: str, headers: dict = None) -> dict:
    response = api_client.start_implementation_window(
        window_id, headers or NETWORK_ADMIN
    )
    return validate_success(response)


def complete_window(window_id: str, headers: dict = None, **overrides) -> dict:
    response = api_client.complete_implementation_window(
        window_id, f.make_window_completion_payload(**overrides), headers or NETWORK_ADMIN
    )
    return validate_success(response)


# --- Section 3.3 boarding and verification --------------------------------

def board_merchant(
    acquirer_id: str,
    business_type_key: str = TEST_DEFAULTS["BUSINESS_TYPE_KEY"],
    headers: dict = None,
    **overrides,
) -> dict:
    response = api_client.create_merchant(
        f.make_merchant_payload(acquirer_id, business_type_key, **overrides),
        headers if headers is not None else make_acquirer_ops_headers(acquirer_id),
    )
    return get_success_data(response, 201)


def verify_merchant(
    merchant_id: str,
    documentation_ref: str = "DOC-2026-0001",
    analyst_user_id: str = None,
    headers: dict = None,
) -> dict:
    """PRD 3.3: verification is a `CategoryAnalyst` action carrying
    `documentation_ref`."""
    if headers is None:
        headers = (
            make_category_analyst_headers(analyst_user_id)
            if analyst_user_id
            else TEST_USERS["category_analyst_headers"]
        )
    response = api_client.verify_merchant_category(
        merchant_id, f.make_verify_category_payload(documentation_ref), headers
    )
    return validate_success(response)


# --- Section 3.4 the reclassification review cycle ------------------------

def file_reclassification(
    merchant_id: str,
    requested_mcc: str,
    acquirer_id: str,
    expected_merchant_version: int = None,
    headers: dict = None,
    **overrides,
) -> dict:
    """Filing advances `Merchant.version`, so the caller must pass the version it
    last observed; when omitted the merchant is re-read first."""
    if expected_merchant_version is None:
        merchant = validate_success(
            api_client.get_merchant(merchant_id, NETWORK_ADMIN)
        )
        expected_merchant_version = merchant["version"]
    response = api_client.create_reclassification_request(
        f.make_reclassification_request_payload(
            merchant_id, requested_mcc, expected_merchant_version, **overrides
        ),
        headers if headers is not None else make_acquirer_ops_headers(acquirer_id),
    )
    return get_success_data(response, 201)


def review_reclassification(
    request_id: str, analyst_user_id: str = None, headers: dict = None
) -> dict:
    if headers is None:
        headers = (
            make_category_analyst_headers(analyst_user_id)
            if analyst_user_id
            else TEST_USERS["category_analyst_headers"]
        )
    return validate_success(
        api_client.review_reclassification_request(request_id, headers)
    )


def request_info(
    request_id: str, analyst_user_id: str = None, headers: dict = None, **overrides
) -> dict:
    if headers is None:
        headers = (
            make_category_analyst_headers(analyst_user_id)
            if analyst_user_id
            else TEST_USERS["category_analyst_headers"]
        )
    return validate_success(
        api_client.request_info_reclassification_request(
            request_id, f.make_request_info_payload(**overrides), headers
        )
    )


def resubmit_reclassification(
    request_id: str,
    acquirer_id: str,
    supporting_doc_ref: str = "DOC-LEASE-1",
    headers: dict = None,
) -> dict:
    return validate_success(
        api_client.resubmit_reclassification_request(
            request_id,
            f.make_resubmit_payload(supporting_doc_ref),
            headers if headers is not None else make_acquirer_ops_headers(acquirer_id),
        )
    )


def decide_reclassification(
    request_id: str,
    decision: str = "APPROVE",
    approver_user_id: str = None,
    headers: dict = None,
    **overrides,
) -> dict:
    from .test_users import make_category_approver_headers

    if headers is None:
        headers = (
            make_category_approver_headers(approver_user_id)
            if approver_user_id
            else TEST_USERS["category_approver_headers"]
        )
    return validate_success(
        api_client.decide_reclassification_request(
            request_id, f.make_decision_payload(decision, **overrides), headers
        )
    )


# --- Sections 3.5 to 3.7 clearing -----------------------------------------

def open_batch(
    acquirer_id: str,
    batch_date: str = "2026-08-01",
    currency_code: str = TEST_DEFAULTS["SETTLEMENT_CURRENCY"],
    headers: dict = None,
    **overrides,
) -> dict:
    response = api_client.create_settlement_batch(
        f.make_settlement_batch_payload(
            acquirer_id, batch_date, currency_code, **overrides
        ),
        headers if headers is not None else make_acquirer_ops_headers(acquirer_id),
    )
    return get_success_data(response, 201)


def read_batch(batch_id: str, headers: dict = None) -> dict:
    return validate_success(
        api_client.get_settlement_batch(batch_id, headers or NETWORK_ADMIN)
    )


def add_record(
    batch_id: str,
    merchant_id: str,
    amount_cents: int,
    acquirer_id: str,
    expected_batch_version: int = None,
    headers: dict = None,
    **overrides,
) -> dict:
    """PRD 3.5: accepting a record advances `SettlementBatch.version`, and the
    response body is the record rather than the batch, so a client adding a
    second record must re-read the batch. When `expected_batch_version` is not
    supplied that re-read is done here."""
    if expected_batch_version is None:
        expected_batch_version = read_batch(batch_id)["version"]
    response = api_client.add_transaction_record(
        batch_id,
        f.make_transaction_record_payload(
            merchant_id, amount_cents, expected_batch_version, **overrides
        ),
        headers if headers is not None else make_acquirer_ops_headers(acquirer_id),
    )
    return get_success_data(response, 201)


def submit_batch(batch_id: str, acquirer_id: str = None, headers: dict = None) -> dict:
    if headers is None:
        headers = (
            make_acquirer_ops_headers(acquirer_id) if acquirer_id else NETWORK_ADMIN
        )
    return validate_success(api_client.submit_settlement_batch(batch_id, headers))


def finalize_batch(batch_id: str, headers: dict = None) -> dict:
    """PRD 3.6: finalization is a `NetworkAdmin` operation."""
    return validate_success(
        api_client.finalize_settlement_batch(batch_id, headers or NETWORK_ADMIN)
    )


def reverse_record(
    record_id: str, reversal_type: str, headers: dict = None, **overrides
) -> dict:
    return validate_success(
        api_client.reverse_transaction_record(
            record_id,
            f.make_reversal_payload(reversal_type, **overrides),
            headers or NETWORK_ADMIN,
        )
    )


def read_record(record_id: str, headers: dict = None) -> dict:
    return validate_success(
        api_client.get_transaction_record(record_id, headers or NETWORK_ADMIN)
    )


def read_merchant(merchant_id: str, headers: dict = None) -> dict:
    return validate_success(
        api_client.get_merchant(merchant_id, headers or NETWORK_ADMIN)
    )


# --- Section 3.8 incentive programs ---------------------------------------

def create_incentive_program(headers: dict = None, **overrides) -> dict:
    response = api_client.create_incentive_program(
        f.make_incentive_program_payload(**overrides), headers or NETWORK_ADMIN
    )
    return get_success_data(response, 201)


def read_incentive_program(program_id: str, headers: dict = None) -> dict:
    return validate_success(
        api_client.get_incentive_program(program_id, headers or NETWORK_ADMIN)
    )


def enrol_merchant(
    incentive_program_id: str,
    merchant_id: str,
    committed_volume_cents: int,
    acquirer_id: str,
    expected_incentive_program_version: int = None,
    headers: dict = None,
    **overrides,
) -> dict:
    """Enrolling is an `AcquirerOps` action; every enrollment write advances
    `IncentiveProgram.version`, so the program is re-read when the caller does
    not pin a version explicitly."""
    if expected_incentive_program_version is None:
        expected_incentive_program_version = read_incentive_program(
            incentive_program_id
        )["version"]
    response = api_client.create_incentive_enrollment(
        f.make_incentive_enrollment_payload(
            incentive_program_id,
            merchant_id,
            committed_volume_cents,
            expected_incentive_program_version,
            **overrides,
        ),
        headers if headers is not None else make_acquirer_ops_headers(acquirer_id),
    )
    return get_success_data(response, 201)


def evaluate_enrollment(
    enrollment_id: str, basis: str = "TRAILING", headers: dict = None
) -> dict:
    return validate_success(
        api_client.evaluate_enrollment_performance(
            enrollment_id,
            f.make_evaluate_performance_payload(basis),
            headers or NETWORK_ADMIN,
        )
    )


def withdraw_enrollment(enrollment_id: str, headers: dict = None, **overrides) -> dict:
    return validate_success(
        api_client.withdraw_incentive_enrollment(
            enrollment_id, f.make_withdrawal_payload(**overrides), headers or NETWORK_ADMIN
        )
    )


def read_enrollment(enrollment_id: str, headers: dict = None) -> dict:
    return validate_success(
        api_client.get_incentive_enrollment(enrollment_id, headers or NETWORK_ADMIN)
    )


# --- Section 3.9 merchant category audits ---------------------------------

def open_audit(
    merchant_id: str,
    trigger_reason: str = "COMPLAINT",
    auditor_user_id: str = None,
    headers: dict = None,
) -> dict:
    if headers is None:
        headers = (
            make_compliance_auditor_headers(auditor_user_id)
            if auditor_user_id
            else TEST_USERS["compliance_auditor_headers"]
        )
    response = api_client.create_merchant_category_audit(
        f.make_audit_payload(merchant_id, trigger_reason), headers
    )
    return get_success_data(response, 201)


def start_fieldwork(
    audit_id: str,
    fieldwork_start: str,
    fieldwork_end: str,
    auditor_user_id: str = None,
    headers: dict = None,
) -> dict:
    if headers is None:
        headers = (
            make_compliance_auditor_headers(auditor_user_id)
            if auditor_user_id
            else TEST_USERS["compliance_auditor_headers"]
        )
    return validate_success(
        api_client.start_audit_fieldwork(
            audit_id, f.make_fieldwork_payload(fieldwork_start, fieldwork_end), headers
        )
    )


def sustain_findings(
    audit_id: str,
    correct_mcc: str,
    auditor_user_id: str = None,
    headers: dict = None,
    **overrides,
) -> dict:
    if headers is None:
        headers = (
            make_compliance_auditor_headers(auditor_user_id)
            if auditor_user_id
            else TEST_USERS["compliance_auditor_headers"]
        )
    return validate_success(
        api_client.sustain_audit_findings(
            audit_id, f.make_sustain_findings_payload(correct_mcc, **overrides), headers
        )
    )


def clear_findings(
    audit_id: str, auditor_user_id: str = None, headers: dict = None, **overrides
) -> dict:
    if headers is None:
        headers = (
            make_compliance_auditor_headers(auditor_user_id)
            if auditor_user_id
            else TEST_USERS["compliance_auditor_headers"]
        )
    return validate_success(
        api_client.clear_audit_findings(
            audit_id, f.make_clear_findings_payload(**overrides), headers
        )
    )


def close_audit(audit_id: str, closer_user_id: str, headers: dict = None) -> dict:
    """PRD 3.9: the closer's `X-User-ID` must differ from the recorded
    `auditor_user_id`."""
    return validate_success(
        api_client.close_merchant_category_audit(
            audit_id, headers or make_compliance_auditor_headers(closer_user_id)
        )
    )


def read_audit(audit_id: str, headers: dict = None) -> dict:
    return validate_success(
        api_client.get_merchant_category_audit(audit_id, headers or NETWORK_ADMIN)
    )


# --- Composite scenario builders ------------------------------------------

def reference_layer(
    clock: str = DEFAULT_CLOCK_UTC,
    mcc_code: str = "5411",
    business_type_key: str = TEST_DEFAULTS["BUSINESS_TYPE_KEY"],
    program_eligibility=None,
    requires_documentation: bool = False,
    high_risk: bool = False,
    country_code: str = TEST_DEFAULTS["COUNTRY_CODE"],
    settlement_currency: str = TEST_DEFAULTS["SETTLEMENT_CURRENCY"],
    max_concurrent_windows: int = TEST_DEFAULTS["MAX_CONCURRENT_WINDOWS"],
    blackout_buffer_days: int = TEST_DEFAULTS["BLACKOUT_BUFFER_DAYS"],
) -> dict:
    """Platform, acquirer and one category definition — the minimum reference
    layer PRD Section 3.1 requires before anything can be boarded or priced."""
    if clock is not None:
        set_clock(clock)
    platform = create_platform(
        max_concurrent_windows=max_concurrent_windows,
        blackout_buffer_days=blackout_buffer_days,
    )
    acquirer = create_acquirer(
        platform["id"],
        country_code=country_code,
        settlement_currency=settlement_currency,
    )
    mcc = create_mcc(
        mcc_code,
        business_type_key,
        program_eligibility=[] if program_eligibility is None else program_eligibility,
        requires_documentation=requires_documentation,
        high_risk=high_risk,
    )
    return {
        "platform": platform,
        "acquirer": acquirer,
        "mcc": mcc,
        "acquirer_headers": make_acquirer_ops_headers(acquirer["id"]),
    }


def second_acquirer(platform_id: str, **overrides) -> dict:
    """A peer acquirer on the same platform, for the scope and shared-capacity
    scenarios."""
    payload = {
        "name": TEST_DEFAULTS["SECOND_ACQUIRER_NAME"],
        "bin_prefix": TEST_DEFAULTS["SECOND_BIN_PREFIX"],
    }
    payload.update(overrides)
    return create_acquirer(platform_id, **payload)


def priced_environment(
    clock: str = DEFAULT_CLOCK_UTC,
    mcc_code: str = "5411",
    business_type_key: str = TEST_DEFAULTS["BUSINESS_TYPE_KEY"],
    program_eligibility=None,
    requires_documentation: bool = False,
    country_code: str = TEST_DEFAULTS["COUNTRY_CODE"],
    settlement_currency: str = TEST_DEFAULTS["SETTLEMENT_CURRENCY"],
    retail_base_rate_bps: int = 165,
    retail_per_item_fee_cents: int = 4,
    retail_max_clearing_delay_hours: int = 48,
    retail_requires_data_elements=None,
    standard_base_rate_bps: int = 200,
    standard_per_item_fee_cents: int = 0,
) -> dict:
    """The reference layer plus the two rate programs every clearing scenario
    needs: one preferential `CPS_RETAIL` tier and the mandatory `STANDARD`
    fallback, both covering the boarded category."""
    env = reference_layer(
        clock=clock,
        mcc_code=mcc_code,
        business_type_key=business_type_key,
        program_eligibility=program_eligibility,
        requires_documentation=requires_documentation,
        country_code=country_code,
        settlement_currency=settlement_currency,
    )
    env["retail_program"] = create_rate_program(
        "CPS_RETAIL_STD",
        "CPS_RETAIL",
        [mcc_code],
        base_rate_bps=retail_base_rate_bps,
        per_item_fee_cents=retail_per_item_fee_cents,
        max_clearing_delay_hours=retail_max_clearing_delay_hours,
        requires_data_elements=(
            [] if retail_requires_data_elements is None else retail_requires_data_elements
        ),
    )
    env["standard_program"] = create_standard_program(
        [mcc_code],
        base_rate_bps=standard_base_rate_bps,
        per_item_fee_cents=standard_per_item_fee_cents,
    )
    return env


def boarded_merchant_environment(**kwargs) -> dict:
    """`priced_environment` with a merchant already boarded under the acquirer."""
    business_type_key = kwargs.get("business_type_key", TEST_DEFAULTS["BUSINESS_TYPE_KEY"])
    env = priced_environment(**kwargs)
    env["merchant"] = board_merchant(
        env["acquirer"]["id"], business_type_key, headers=env["acquirer_headers"]
    )
    return env


def open_batch_environment(
    batch_date: str = "2026-08-01", currency_code: str = None, **kwargs
) -> dict:
    """A boarded merchant plus an `OPEN` settlement batch on its acquirer."""
    env = boarded_merchant_environment(**kwargs)
    env["batch"] = open_batch(
        env["acquirer"]["id"],
        batch_date,
        currency_code or kwargs.get("settlement_currency", TEST_DEFAULTS["SETTLEMENT_CURRENCY"]),
        headers=env["acquirer_headers"],
    )
    return env


# --- The canonical reference layer used by most clearing scenarios ---------
#
# The literals here are the ones the arithmetic of PRD Sections 3.5 to 3.7 is
# exercised against, so they are spelled out rather than hidden behind defaults.

CANONICAL_MCCS = {
    "5411": {
        "description": "Grocery Stores",
        "business_type_key": "GROCERY",
        "program_eligibility": ["SMALL_TICKET"],
        "requires_documentation": False,
        "high_risk": False,
    },
    "4900": {
        "description": "Utilities",
        "business_type_key": "UTILITY_SERVICE",
        "program_eligibility": ["UTILITY"],
        "requires_documentation": True,
        "high_risk": False,
    },
    "7995": {
        "description": "Betting and Wagering",
        "business_type_key": "GAMBLING",
        "program_eligibility": [],
        "requires_documentation": True,
        "high_risk": True,
    },
    "8398": {
        "description": "Charitable Organizations",
        "business_type_key": "CHARITABLE",
        "program_eligibility": ["CHARITY"],
        "requires_documentation": True,
        "high_risk": False,
    },
    "9399": {
        "description": "Government Services",
        "business_type_key": "GOVERNMENT",
        "program_eligibility": ["GOVERNMENT"],
        "requires_documentation": False,
        "high_risk": False,
    },
}

CANONICAL_PROGRAMS = {
    "CPS_RETAIL": {
        "program_code": "CPS_RETAIL_STD",
        "name": "CPS Retail",
        "category": "CPS_RETAIL",
        "base_rate_bps": 145,
        "per_item_fee_cents": 10,
        "requires_data_elements": [
            "AUTH_CODE",
            "TERMINAL_ID",
            "TRANSACTION_DATE",
            "CARDHOLDER_ZIP",
        ],
        "max_clearing_delay_hours": 24,
    },
    "SMALL_TICKET": {
        "program_code": "SMALL_TICKET_STD",
        "name": "Small Ticket",
        "category": "SMALL_TICKET",
        "base_rate_bps": 165,
        "per_item_fee_cents": 4,
        "requires_data_elements": ["AUTH_CODE", "TERMINAL_ID"],
        "max_clearing_delay_hours": 48,
    },
    "STANDARD": {
        "program_code": "STANDARD_FALLBACK",
        "name": "Standard",
        "category": "STANDARD",
        "base_rate_bps": 254,
        "per_item_fee_cents": 10,
        "requires_data_elements": [],
        "max_clearing_delay_hours": 720,
    },
}

ALL_CANONICAL_MCC_CODES = ["5411", "4900", "7995", "8398", "9399"]


def define_mccs(codes) -> dict:
    """Publish the named canonical category definitions; returns code -> row."""
    return {code: create_mcc(code, **CANONICAL_MCCS[code]) for code in codes}


def define_programs(keys, eligible_mcc_codes=None, **per_key_overrides) -> dict:
    """Publish the named canonical rate programs; returns key -> row.

    `eligible_mcc_codes` applies to every program created here unless a
    `<key>_eligible_mcc_codes` override is supplied.
    """
    programs = {}
    for key in keys:
        spec = dict(CANONICAL_PROGRAMS[key])
        program_code = spec.pop("program_code")
        category = spec.pop("category")
        spec.update(per_key_overrides.get(key, {}))
        codes = (
            per_key_overrides.get(f"{key}_eligible_mcc_codes")
            or eligible_mcc_codes
            or ["5411"]
        )
        programs[key] = create_rate_program(program_code, category, codes, **spec)
    return programs


def canonical_environment(
    clock: str,
    mcc_codes=("5411",),
    program_keys=("CPS_RETAIL", "SMALL_TICKET", "STANDARD"),
    eligible_mcc_codes=None,
    standard_eligible_mcc_codes=None,
    **program_overrides,
) -> dict:
    """Clock, platform, US/USD acquirer, the named category definitions and the
    named rate programs — the preamble almost every clearing chain shares."""
    if clock is not None:
        set_clock(clock)
    platform = create_platform()
    acquirer = create_acquirer(platform["id"])
    mccs = define_mccs(mcc_codes)
    overrides = dict(program_overrides)
    if standard_eligible_mcc_codes is not None:
        overrides["STANDARD_eligible_mcc_codes"] = standard_eligible_mcc_codes
    programs = define_programs(
        program_keys,
        eligible_mcc_codes=list(eligible_mcc_codes or mcc_codes),
        **overrides,
    )
    return {
        "platform": platform,
        "acquirer": acquirer,
        "acquirer_headers": make_acquirer_ops_headers(acquirer["id"]),
        "mccs": mccs,
        "programs": programs,
    }
