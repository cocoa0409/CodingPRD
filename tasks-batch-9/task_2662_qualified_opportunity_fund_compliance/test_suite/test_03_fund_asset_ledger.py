"""Registering, rolling up and disposing the fund's asset ledger."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_fund_aggregates, assert_money
from test_helpers.factories import (
    OMIT,
    create_fund_asset_payload,
    create_qoz_business_payload,
    dispose_fund_asset_payload,
)
from test_helpers.fixtures import (
    certify_business_test,
    dispose_asset,
    list_fund_assets,
    make_attested_investor,
    make_business_test,
    make_deferral_election,
    make_eligible_gain,
    make_fund_asset,
    make_qoz_business,
    make_self_certified_fund,
    make_step_up_election,
    measure_business_test,
    read_fund,
    read_fund_asset,
    read_qoz_business,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CERTIFIER_HEADERS,
    MANAGER_HEADERS,
    MEASURER_HEADERS,
)


def test_a_ten_character_census_tract_code_is_refused(api):
    """
    "the `zone_tract_code` of the designated opportunity-zone census tract it operates
    in — exactly 11 characters, no more and no fewer". "Request-body and query schema on
    every write endpoint: all required fields present, no unknown fields, correct types,
    legal enum members, and each number inside its declared bounds —
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/qoz_business_zone_tract_code_wrong_length_rejected
    """
    fund = make_self_certified_fund(api, name="Tract Code Fund")

    response = api.create_qoz_business(
        create_qoz_business_payload(
            fund["id"],
            legal_name="Short Code LLC",
            zone_tract_code="1234567890",
            declared_nqfp_amount=0.00,
            total_asset_value=500000.00,
            total_tangible_property_basis=450000.00,
        ),
        MANAGER_HEADERS,
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)
    rows, meta = validate_paginated(
        api.list_qoz_businesses(ADMIN_HEADERS, {"fund_id": fund["id"], "limit": 100})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_an_equity_link_across_two_funds_is_refused_and_so_is_a_stray_link(api):
    """
    "the operating-business link is exclusive to equity: `asset_class` `QOZB_EQUITY`
    **requires** a `qoz_business_id` whose business belongs to the same `fund_id` as the
    asset, while every other asset class must omit `qoz_business_id` entirely. A missing
    link, a link supplied on the wrong class, or a link pointing at a business of a
    different fund all yield `ERR_QOZB_LINK_REQUIRED`."

    Design: Corner/entities/fund_asset_qozb_equity_cross_fund_link_rejected
    """
    fund_a = make_self_certified_fund(api, name="Link Fund A")
    fund_b = make_self_certified_fund(api, name="Link Fund B")
    business_b = make_qoz_business(
        api,
        fund_b["id"],
        legal_name="Other Fund Business LLC",
        zone_tract_code="12345678910",
        declared_nqfp_amount=0.00,
        total_asset_value=500000.00,
        total_tangible_property_basis=450000.00,
    )

    cross_fund = api.create_fund_asset(
        create_fund_asset_payload(
            fund_a["id"],
            asset_class="QOZB_EQUITY",
            qoz_business_id=business_b["id"],
            acquisition_date="2026-01-20T00:00:00Z",
            unadjusted_cost_basis=300000.00,
            afs_fair_value=300000.00,
        ),
        MANAGER_HEADERS,
    )
    stray_link = api.create_fund_asset(
        create_fund_asset_payload(
            fund_b["id"],
            asset_class="CASH",
            qoz_business_id=business_b["id"],
            acquisition_date="2026-01-20T00:00:00Z",
            unadjusted_cost_basis=100000.00,
            afs_fair_value=100000.00,
        ),
        MANAGER_HEADERS,
    )

    validate_error(cross_fund, ApiErrorId.QOZB_LINK_REQUIRED.value, 422)
    validate_error(stray_link, ApiErrorId.QOZB_LINK_REQUIRED.value, 422)
    assert_money(
        read_fund(api, fund_a["id"])["aggregate_asset_basis"],
        0.00,
        "aggregate_asset_basis",
    )
    assert_money(
        read_fund(api, fund_b["id"])["aggregate_asset_basis"],
        0.00,
        "aggregate_asset_basis",
    )
    assert list_fund_assets(api, fund_a["id"]) == []
    assert list_fund_assets(api, fund_b["id"]) == []


def _mixed_ledger_fund(api):
    """One qualified property row and one cash row under a certified fund."""
    fund = make_self_certified_fund(api, name="Rollup Fund")
    qualified = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZ_BUSINESS_PROPERTY",
        acquisition_date="2026-01-15T00:00:00Z",
        unadjusted_cost_basis=600000.00,
        afs_fair_value=700000.00,
        original_use_in_zone=True,
    )
    cash = make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-20T00:00:00Z",
        unadjusted_cost_basis=150000.00,
        afs_fair_value=150000.00,
    )
    return fund, qualified, cash


def test_two_rows_of_different_qualification_split_the_four_rollups(api):
    """
    "A new asset is created with `status` `HELD`, `adjusted_basis` equal to its
    `unadjusted_cost_basis`, `disposed_at` empty, `proceeds_amount` at 0.00, and
    `disposition_sequence_index` empty." "`QOZ_BUSINESS_PROPERTY` with
    `original_use_in_zone` true is `QUALIFIED` immediately". "and
    `NONQUALIFIED_FINANCIAL_PROPERTY` and `CASH` are always `NONQUALIFIED`. Registration
    then recomputes all four fund aggregates."

    Design: Corner/state_machines/fund_asset_creation_updates_fund_aggregates
    """
    fund, qualified, cash = _mixed_ledger_fund(api)

    assert qualified["qualification"] == "QUALIFIED"
    assert qualified["status"] == "HELD"
    assert cash["qualification"] == "NONQUALIFIED"
    assert cash["version"] == 1
    assert_money(qualified["adjusted_basis"], 600000.00, "adjusted_basis")
    assert not qualified["disposition_sequence_index"]
    assert_money(qualified["proceeds_amount"], 0.00, "proceeds_amount")
    assert_fund_aggregates(
        read_fund(api, fund["id"]),
        aggregate_asset_basis=750000.00,
        aggregate_qualified_basis=600000.00,
        aggregate_afs_value=850000.00,
        aggregate_qualified_afs_value=700000.00,
    )


def test_disposing_the_qualified_row_collapses_the_ledger_to_the_survivor(api):
    """
    "Disposal ends an asset's life." "the `HELD → DISPOSED` transition stamps
    `disposed_at` from the logical clock, records the proceeds, and recomputes
    `aggregate_asset_basis`, `aggregate_qualified_basis`, `aggregate_afs_value` and
    `aggregate_qualified_afs_value` so that the basis ledger again describes only the
    fund's remaining `HELD` and `IMPROVING` assets."

    Design: Corner/state_machines/fund_asset_disposal_reduces_fund_aggregate_ledger
    """
    fund, qualified, cash = _mixed_ledger_fund(api)
    assert_fund_aggregates(
        read_fund(api, fund["id"]),
        aggregate_asset_basis=750000.00,
        aggregate_qualified_basis=600000.00,
        aggregate_afs_value=850000.00,
        aggregate_qualified_afs_value=700000.00,
    )

    disposed = dispose_asset(api, qualified["id"], proceeds_amount=800000.00)

    assert disposed["status"] == "DISPOSED"
    assert disposed["disposed_at"].startswith("2026-08-01T00:00:00")
    assert_money(disposed["proceeds_amount"], 800000.00, "proceeds_amount")
    assert_fund_aggregates(
        read_fund(api, fund["id"]),
        aggregate_asset_basis=150000.00,
        aggregate_qualified_basis=0.00,
        aggregate_afs_value=150000.00,
        aggregate_qualified_afs_value=0.00,
    )
    survivor = read_fund_asset(api, cash["id"])
    assert survivor["status"] == "HELD"
    assert survivor["version"] == 1


def test_a_second_disposal_of_the_same_asset_cannot_rewrite_the_proceeds(api):
    """
    "The target is already in a terminal state for its machine —
    `ERR_ALREADY_TERMINAL` (409): an `EXPIRED` gain, an `INCLUDED_FULL` or `REVOKED`
    election, a `PASSED` or `FAILED` business test, a `CERTIFIED_PASS` or
    `CERTIFIED_FAIL` asset test, a `SATISFIED` or `LAPSED` project, a `COMPLETED` or
    `BLOWN` plan, a `CURED` or `UPHELD` assessment, a `DISPOSED` asset, a `DECERTIFIED`
    fund."

    Design: Corner/state_machines/fund_asset_dispose_twice_already_terminal_rejected
    """
    fund = make_self_certified_fund(api, name="Terminal Asset Fund")
    asset = make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-02-01T00:00:00Z",
        unadjusted_cost_basis=200000.00,
        afs_fair_value=200000.00,
    )
    first = dispose_asset(api, asset["id"], proceeds_amount=210000.00)
    assert first["status"] == "DISPOSED"
    assert_money(first["proceeds_amount"], 210000.00, "proceeds_amount")

    response = api.dispose_fund_asset(
        asset["id"], dispose_fund_asset_payload(proceeds_amount=5000.00), MANAGER_HEADERS
    )

    validate_error(response, ApiErrorId.ALREADY_TERMINAL.value, 409)
    after = read_fund_asset(api, asset["id"])
    assert_money(after["proceeds_amount"], 210000.00, "proceeds_amount")
    assert after["disposed_at"].startswith("2026-08-01T00:00:00")
    assert after["version"] == 2
    assert_fund_aggregates(
        read_fund(api, fund["id"]),
        aggregate_asset_basis=0.00,
        aggregate_afs_value=0.00,
    )


def test_the_related_party_bar_binds_property_only_and_lets_cash_through(api):
    """
    "Property bought from a related party can never be qualified zone business
    property, so an asset with `acquired_from_related_party` true and `asset_class`
    `QOZ_BUSINESS_PROPERTY` is rejected outright with `ERR_RELATED_PARTY_ACQUISITION`."
    "and `NONQUALIFIED_FINANCIAL_PROPERTY` and `CASH` are always `NONQUALIFIED`."

    Design: Corner/validations/related_party_cash_asset_passes_the_related_party_bar
    """
    fund = make_self_certified_fund(
        api, name="Related Party Fund", entity_type="CORPORATION"
    )

    cash = validate_success(
        api.create_fund_asset(
            create_fund_asset_payload(
                fund["id"],
                asset_class="CASH",
                acquisition_date="2026-02-01T00:00:00Z",
                unadjusted_cost_basis=250000.00,
                afs_fair_value=250000.00,
                acquired_from_related_party=True,
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    property_response = api.create_fund_asset(
        create_fund_asset_payload(
            fund["id"],
            asset_class="QOZ_BUSINESS_PROPERTY",
            acquisition_date="2026-02-01T00:00:00Z",
            unadjusted_cost_basis=250000.00,
            afs_fair_value=250000.00,
            acquired_from_related_party=True,
            original_use_in_zone=True,
        ),
        MANAGER_HEADERS,
    )

    assert cash["qualification"] == "NONQUALIFIED"
    assert cash["acquired_from_related_party"] is True
    validate_error(property_response, ApiErrorId.RELATED_PARTY_ACQUISITION.value, 422)
    assert_fund_aggregates(
        read_fund(api, fund["id"]),
        aggregate_asset_basis=250000.00,
        aggregate_qualified_basis=0.00,
    )
    rows = list_fund_assets(api, fund["id"])
    assert [row["id"] for row in rows] == [cash["id"]]


def test_the_pinned_disposition_order_refuses_the_asset_that_jumps_the_queue(api):
    """
    "When a `disposition_sequence` was supplied, position `i` of the list, counting from
    1, is written to the `disposition_sequence_index` of the asset named at that
    position. The list is authoritative: there is no server-side ranking, no tie-break,
    and no dependence on identifier ordering." "an asset carrying a non-empty
    `disposition_sequence_index` may be disposed only once every asset of the same fund
    with a strictly smaller non-empty index is already `DISPOSED`, and jumping the queue
    yields `ERR_DISPOSITION_ORDER_VIOLATION`."

    Design: Corner/errors/disposition_out_of_declared_order_rejected
    """
    investor = make_attested_investor(
        api, legal_name="Order Discipline LLC", taxpayer_type="PARTNERSHIP"
    )
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=300000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    fund = make_self_certified_fund(
        api, name="Order Discipline QOF", entity_type="PARTNERSHIP"
    )
    first = make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=100000.00,
        afs_fair_value=100000.00,
    )
    second = make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-06T00:00:00Z",
        unadjusted_cost_basis=200000.00,
        afs_fair_value=200000.00,
    )
    election = make_deferral_election(
        api, investor["id"], gain["id"], fund["id"], elected_amount=300000.00
    )
    set_clock(api, "2036-08-01T00:00:00Z")

    step_up = make_step_up_election(
        api,
        election["id"],
        investor_id=investor["id"],
        claimed_fmv=450000.00,
        disposition_sequence=[second["id"], first["id"]],
    )

    assert step_up["holding_period_days"] == 3653
    assert step_up["status"] == "GRANTED"
    assert read_fund_asset(api, second["id"])["disposition_sequence_index"] == 1
    assert read_fund_asset(api, first["id"])["disposition_sequence_index"] == 2

    jumped = api.dispose_fund_asset(
        first["id"], dispose_fund_asset_payload(proceeds_amount=120000.00), MANAGER_HEADERS
    )

    validate_error(jumped, ApiErrorId.DISPOSITION_ORDER_VIOLATION.value, 409)
    held = read_fund_asset(api, first["id"])
    assert held["status"] == "HELD"
    assert not held["disposed_at"]

    index_one = dispose_asset(api, second["id"], proceeds_amount=260000.00)
    assert index_one["status"] == "DISPOSED"
    assert_money(index_one["proceeds_amount"], 260000.00, "proceeds_amount")
    assert index_one["disposed_at"].startswith("2036-08-01T00:00:00")

    replayed = validate_success(
        api.dispose_fund_asset(
            first["id"],
            dispose_fund_asset_payload(proceeds_amount=120000.00),
            MANAGER_HEADERS,
        )
    )

    assert replayed["status"] == "DISPOSED"
    assert_fund_aggregates(read_fund(api, fund["id"]), aggregate_asset_basis=0.00)


def test_equity_registered_after_the_pass_is_born_qualified_from_the_link(api):
    """
    "`QOZB_EQUITY` tracks the linked business's `qualification_status`, so it is
    `QUALIFIED` exactly when that business is `QUALIFIED` and `NONQUALIFIED` otherwise".
    "A new asset is created with `status` `HELD`, `adjusted_basis` equal to its
    `unadjusted_cost_basis`, `disposed_at` empty, `proceeds_amount` at 0.00, and
    `disposition_sequence_index` empty." "Registration then recomputes all four fund
    aggregates."

    Design: Corner/endpoints/fund_asset_qozb_equity_link_inherits_business_qualification
    """
    fund = make_self_certified_fund(
        api, name="Link Inherit Fund", entity_type="CORPORATION"
    )
    business = make_qoz_business(
        api,
        fund["id"],
        legal_name="Link Inherit Operating LLC",
        zone_tract_code="12345678910",
        declared_nqfp_amount=20000.00,
        total_asset_value=1000000.00,
        total_tangible_property_basis=850000.00,
    )
    test = make_business_test(api, business["id"], testing_date="2026-06-30T00:00:00Z")
    measure_business_test(
        api,
        test["id"],
        MEASURER_HEADERS,
        safe_harbor_used="GROSS_INCOME_ACTUAL",
        gross_income_zone_amount=600000.00,
        gross_income_total_amount=1000000.00,
        intangibles_zone_use_amount=450000.00,
        intangibles_total_amount=1000000.00,
        total_asset_value_measured=1000000.00,
    )
    certified = certify_business_test(api, test["id"], CERTIFIER_HEADERS)
    assert certified["status"] == "PASSED"
    assert read_qoz_business(api, business["id"])["qualification_status"] == "QUALIFIED"

    asset = validate_success(
        api.create_fund_asset(
            create_fund_asset_payload(
                fund["id"],
                asset_class="QOZB_EQUITY",
                qoz_business_id=business["id"],
                acquisition_date="2026-07-15T00:00:00Z",
                unadjusted_cost_basis=450000.00,
                afs_fair_value=450000.00,
                original_use_in_zone=OMIT,
            ),
            MANAGER_HEADERS,
        ),
        201,
    )

    assert asset["qoz_business_id"] == business["id"]
    assert asset["qualification"] == "QUALIFIED"
    assert asset["status"] == "HELD"
    assert_money(asset["adjusted_basis"], 450000.00, "adjusted_basis")
    assert_money(asset["proceeds_amount"], 0.00, "proceeds_amount")
    assert not asset["disposed_at"]
    assert not asset["disposition_sequence_index"]
    assert_fund_aggregates(
        read_fund(api, fund["id"]),
        aggregate_asset_basis=450000.00,
        aggregate_qualified_basis=450000.00,
    )
