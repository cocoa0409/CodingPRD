"""Fund formation, self-certification and the two independent state dimensions."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_common_fields,
    assert_fund_aggregates,
    assert_fund_state,
    assert_money,
)
from test_helpers.factories import (
    OMIT,
    create_asset_test_payload,
    create_fund_payload,
    decertify_payload,
    self_certify_payload,
)
from test_helpers.fixtures import (
    certify_asset_test,
    make_asset_test,
    make_fund,
    make_fund_asset,
    measure_asset_test,
    read_asset_test,
    read_fund,
    self_certify_fund,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CERTIFIER_HEADERS,
    FUND_MANAGER_USER_ID,
    MANAGER_HEADERS,
    MEASURER_HEADERS,
)


def test_self_certification_leaves_the_compliance_posture_untouched(api):
    """
    "On success the `DRAFT → SELF_CERTIFIED` transition stamps
    `self_certification_date` with the logical clock's current instant, records
    `first_taxable_month_iso8601` from the request, leaves `compliance_posture`
    exactly where it was — `UNTESTED` on a fresh fund — and increments the fund's
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/fund_parallel_state_dimensions_independent
    """
    fund = make_fund(api)
    assert_fund_state(fund, certification_status="DRAFT", compliance_posture="UNTESTED")
    before_version = fund["version"]

    certified = self_certify_fund(api, fund["id"])

    assert_fund_state(
        certified, certification_status="SELF_CERTIFIED", compliance_posture="UNTESTED"
    )
    assert certified["version"] == before_version + 1
    assert certified["self_certification_date"].startswith("2026-08-01T00:00:00")
    assert certified["first_taxable_month_iso8601"].startswith("2026-01-01T00:00:00")


def test_certifying_a_passing_test_moves_only_the_compliance_dimension(api):
    """
    "Neither value constrains the other, and they advance on entirely different
    triggers." "A `PASS` produces `MEASURED → CERTIFIED_PASS`, records
    `certified_by_user_id`, drives the fund's `compliance_posture` to `COMPLIANT` —
    `UNTESTED → COMPLIANT` on a fund that has never been tested — and resets
    `consecutive_failed_tests` to 0."

    Design: Difficulty/non_linear_state_machine/fund_parallel_state_dimensions_independent
    """
    fund = make_fund(api)
    self_certify_fund(api, fund["id"])
    before = read_fund(api, fund["id"])
    assert_fund_state(
        before, certification_status="SELF_CERTIFIED", compliance_posture="UNTESTED"
    )

    make_fund_asset(
        api,
        fund["id"],
        acquisition_date="2026-01-15T00:00:00Z",
        unadjusted_cost_basis=1000000.00,
        afs_fair_value=1000000.00,
    )
    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    measure_asset_test(api, test["id"], MEASURER_HEADERS)
    certified_test = certify_asset_test(api, test["id"], CERTIFIER_HEADERS)

    assert certified_test["status"] == "CERTIFIED_PASS"
    assert certified_test["result"] == "PASS"
    after = read_fund(api, fund["id"])
    assert_fund_state(
        after, certification_status="SELF_CERTIFIED", compliance_posture="COMPLIANT"
    )
    assert after["consecutive_failed_tests"] == 0
    assert after["cumulative_penalty_months"] == 0
    assert after["last_test_measurement_date"].startswith("2026-06-30T00:00:00")
    assert_money(read_asset_test(api, test["id"])["shortfall_amount"], 0.00, "shortfall")


def test_a_fund_read_back_carries_every_stored_and_derived_field(api):
    """
    "A fund is created — by a `FundManager` or a `PlatformAdmin` — from four inputs:
    the fund's `name` (1 to 200 characters, non-blank), its `entity_type`, either
    `CORPORATION` or `PARTNERSHIP`, for the federal self-certification filing; the
    `manager_user_id` that will own it". "On success the `DRAFT → SELF_CERTIFIED`
    transition stamps `self_certification_date` with the logical clock's current
    instant, records `first_taxable_month_iso8601` from the request".

    Design: Corner/entities/fund_retrieval_returns_stored_state
    """
    fund = make_fund(
        api,
        name="Readback Fund",
        entity_type="CORPORATION",
        manager_user_id=FUND_MANAGER_USER_ID,
    )
    self_certify_fund(api, fund["id"])

    stored = validate_success(api.get_fund(fund["id"], MEASURER_HEADERS))

    assert stored["id"] == fund["id"]
    assert stored["name"] == "Readback Fund"
    assert stored["entity_type"] == "CORPORATION"
    assert stored["manager_user_id"] == FUND_MANAGER_USER_ID
    assert_fund_state(
        stored, certification_status="SELF_CERTIFIED", compliance_posture="UNTESTED"
    )
    assert stored["first_taxable_month_iso8601"].startswith("2026-01-01T00:00:00")
    assert stored["self_certification_date"].startswith("2026-08-01T00:00:00")
    assert_fund_aggregates(
        stored,
        aggregate_asset_basis=0.00,
        aggregate_qualified_basis=0.00,
        aggregate_afs_value=0.00,
        aggregate_qualified_afs_value=0.00,
    )
    assert_money(
        stored["deferred_gain_committed"], 0.00, "deferred_gain_committed"
    )
    assert stored["cumulative_penalty_months"] == 0
    assert stored["consecutive_failed_tests"] == 0
    assert not stored["last_test_measurement_date"]


def test_a_fund_without_a_manager_handle_is_refused_and_nothing_is_stored(api):
    """
    "the `manager_user_id` that will own it, a non-blank handle of 1 to 64 characters
    that is compared against `X-User-ID` on later manager calls and is deliberately
    **not** a foreign key to any entity". "Request-body and query schema on every write
    endpoint: all required fields present, no unknown fields, correct types, legal enum
    members, and each number inside its declared bounds — `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/fund_create_missing_required_manager_user_id
    """
    response = api.create_fund(
        create_fund_payload(
            name="Headless Fund", entity_type="CORPORATION", manager_user_id=OMIT
        ),
        ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)
    rows, meta = validate_paginated(api.list_funds(ADMIN_HEADERS, {"limit": 100}))
    assert rows == []
    assert meta["total_count"] == 0


def test_the_four_system_properties_are_minted_by_the_server(api):
    """
    "`id` — a server-minted UUID string with no type prefix." "`version` — an integer
    that starts at 1 on creation and increases by exactly 1 on every mutation of the
    resource, cascaded mutations included." "A new fund has `certification_status`
    `DRAFT`, `compliance_posture` `UNTESTED`".

    Design: Corner/entities/fund_system_fields_minted_by_server
    """
    response = api.create_fund(
        create_fund_payload(
            name="System Fields Fund",
            entity_type="PARTNERSHIP",
            manager_user_id=FUND_MANAGER_USER_ID,
        ),
        MANAGER_HEADERS,
    )

    fund = validate_success(response, 201)

    assert_common_fields(fund, "Fund")
    assert fund["version"] == 1
    assert_fund_state(fund, certification_status="DRAFT", compliance_posture="UNTESTED")
    assert not fund["self_certification_date"]
    assert not fund["first_taxable_month_iso8601"]


def test_a_second_self_certification_cannot_restamp_the_election_month(api):
    """
    "Self-certifying a fund that is already `SELF_CERTIFIED` is an undeclared
    transition from a non-terminal state and yields `ERR_INVALID_STATE_TRANSITION`".
    "a request that fails any check in §2.11 mutates nothing."

    Design: Corner/state_machines/fund_self_certify_twice_rejected
    """
    fund = make_fund(api, name="Once Only Fund", entity_type="CORPORATION")
    assert fund["version"] == 1
    certified = self_certify_fund(api, fund["id"])
    assert certified["version"] == 2
    assert certified["certification_status"] == "SELF_CERTIFIED"

    response = api.self_certify_fund(
        fund["id"],
        self_certify_payload(first_taxable_month_iso8601="2026-02-01T00:00:00Z"),
        MANAGER_HEADERS,
    )

    validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)
    after = read_fund(api, fund["id"])
    assert after["first_taxable_month_iso8601"].startswith("2026-01-01T00:00:00")
    assert after["self_certification_date"].startswith("2026-08-01T00:00:00")
    assert after["version"] == 2
    assert after["compliance_posture"] == "UNTESTED"


def test_a_decertified_draft_fund_locks_out_both_tests_and_certification(api):
    """
    "Fund decertification lockout: the owning fund's `certification_status` must not be
    `DECERTIFIED` — `ERR_FUND_DECERTIFIED` (409). This guards election create,
    self-certification, decertification, asset-test creation and asset record." "It is
    declared from both `DRAFT` and `SELF_CERTIFIED`, so both `DRAFT → DECERTIFIED` and
    `SELF_CERTIFIED → DECERTIFIED` are legal, and in both cases it sets
    `certification_status` to `DECERTIFIED`, sets `compliance_posture` to
    `FAILED_FINAL`, and increments the fund's `version` by 1."

    Design: Corner/errors/decertified_fund_rejects_a_new_asset_test
    """
    fund = make_fund(api, name="Lockout Fund", entity_type="CORPORATION")
    assert_fund_state(
        fund, certification_status="DRAFT", compliance_posture="UNTESTED"
    )

    decertified = validate_success(
        api.decertify_fund(
            fund["id"],
            decertify_payload(
                reason_note="Voluntary withdrawal before first taxable month"
            ),
            CERTIFIER_HEADERS,
        )
    )

    assert_fund_state(
        decertified,
        certification_status="DECERTIFIED",
        compliance_posture="FAILED_FINAL",
    )
    assert decertified["version"] == fund["version"] + 1

    test_response = api.create_asset_test(
        fund["id"],
        create_asset_test_payload(
            measurement_date="2026-06-30T00:00:00Z",
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    certify_response = api.self_certify_fund(
        fund["id"],
        self_certify_payload(first_taxable_month_iso8601="2026-01-01T00:00:00Z"),
        MANAGER_HEADERS,
    )

    validate_error(test_response, ApiErrorId.FUND_DECERTIFIED.value, 409)
    validate_error(certify_response, ApiErrorId.FUND_DECERTIFIED.value, 409)
    rows, meta = validate_paginated(
        api.list_fund_asset_tests(fund["id"], ADMIN_HEADERS, {"limit": 100})
    )
    assert rows == []
    assert meta["total_count"] == 0
    after = read_fund(api, fund["id"])
    assert_fund_state(
        after, certification_status="DECERTIFIED", compliance_posture="FAILED_FINAL"
    )
    assert after["version"] == decertified["version"]


def test_the_officer_decertification_couples_the_two_dimensions_in_one_call(api):
    """
    "There is exactly one coupling: moving `certification_status` to `DECERTIFIED` forces
    `compliance_posture` to `FAILED_FINAL` as an explicit side effect." "in both cases it
    sets `certification_status` to `DECERTIFIED`, sets `compliance_posture` to
    `FAILED_FINAL`, and increments the fund's `version` by 1." "Decertifying a `DRAFT`
    fund fires none of this, and not by omission: a `DRAFT` fund cannot hold a single
    deferral election, because election creation requires a `SELF_CERTIFIED` fund."

    Design: Corner/endpoints/fund_decertify_action_sets_terminal_certification_and_failed_final
    """
    fund = make_fund(api, name="Decertify Fund", entity_type="CORPORATION")
    self_certify_fund(api, fund["id"])
    make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZ_BUSINESS_PROPERTY",
        acquisition_date="2026-01-10T00:00:00Z",
        unadjusted_cost_basis=1000000.00,
        afs_fair_value=1000000.00,
        original_use_in_zone=True,
    )
    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    measure_asset_test(api, test["id"], MEASURER_HEADERS)
    certify_asset_test(api, test["id"], CERTIFIER_HEADERS)
    before = read_fund(api, fund["id"])
    assert_fund_state(
        before, certification_status="SELF_CERTIFIED", compliance_posture="COMPLIANT"
    )
    assert before["version"] == 5, (
        "create, self-certify, the asset registration that recomputes the four "
        "aggregates, the measurement that restamps last_test_measurement_date, "
        "then the passing certification cascade"
    )

    decertified = validate_success(
        api.decertify_fund(
            fund["id"],
            decertify_payload(reason_note="Zone designation withdrawn by the state"),
            CERTIFIER_HEADERS,
        )
    )

    assert_fund_state(
        decertified,
        certification_status="DECERTIFIED",
        compliance_posture="FAILED_FINAL",
    )
    assert decertified["version"] == 6
    settled = read_asset_test(api, test["id"])
    assert settled["status"] == "CERTIFIED_PASS"
    assert settled["result"] == "PASS"
    assert_fund_aggregates(
        read_fund(api, fund["id"]),
        aggregate_asset_basis=1000000.00,
        aggregate_qualified_basis=1000000.00,
    )
    assert_money(decertified["deferred_gain_committed"], 0.00, "deferred_gain_committed")
