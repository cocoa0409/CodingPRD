"""Cross-cutting layers: version pinning, per-row version counters, filtered pagination and the
derived-field chain a single price post has to rebuild."""

from test_helpers import fixtures, get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DEFAULT_CLOCK_UTC, clock_stamp
from test_helpers.factories import (
    create_mtm_run_payload,
    create_pledge_allocation_payload,
    create_runoff_forecast_payload,
    price_payload,
    projected_window,
)
from test_helpers.fixtures import COMPLIANCE, OFFICER, OPERATOR, REGULATOR
from test_helpers.test_users import make_public_unit_treasurer_headers

FIVE_AM = "2026-08-01T05:00:00Z"
HORIZON_END = "2026-08-31T00:00:00Z"


def test_a_second_pledge_needs_a_freshly_read_agreement_version(client):
    """The first allocation consumes the version the client was holding, so replaying it on the next
    asset is a 412 that writes nothing at all; re-reading the agreement makes the identical payload
    succeed, and the agreement never left EXECUTED throughout.

    PRD: "- `POST /pledge-allocations` requires `expected_pledge_agreement_version`. If it does not
    equal the referenced `PledgeAgreement`'s current `version`, the request is rejected with
    `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). An agreement legitimately carries many allocations, so
    this check exists purely to stop a writer from pledging against a stale view of the agreement's
    allocation set, custodian or beneficiary."
    PRD: "Each of these three requests must carry a non-optional integer field holding the `version`
    of the parent as the client last observed it, and the service compares that value to the
    parent's current stored `version` before doing anything else that could mutate state."
    PRD: "Concretely: an agreement's `total_collateral_value_cents` is the sum of
    `allocated_collateral_value_cents` over its allocations that are `ACTIVE` and whose asset is
    `ELIGIBLE`; its `total_pledged_par_cents` is the sum of `allocated_par_cents` over all of its
    `ACTIVE` allocations, whether or not the underlying asset is still eligible; and its
    `active_allocation_count` is the number of its allocations in `ACTIVE` status."
    PRD: "Coverage is measured by `coverage_ratio_bps`. When `required_collateral_cents` is zero the
    ratio is defined as 10000; otherwise it is `assigned_collateral_value_cents` multiplied by
    10000, divided by `required_collateral_cents`, floored to whole basis points."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_agreement_version_rejected_on_second_allocation
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    assets = [
        fixtures.create_collateral_asset(
            client, perimeter["depository_id"], perimeter["custodian_id"], cusip=f"CU-{n}"
        )
        for n in (1, 2, 3)
    ]
    first_version = fixtures.agreement_version(client, perimeter["agreement_id"])

    def allocation_payload(asset_id, pinned):
        return create_pledge_allocation_payload(
            perimeter["agreement_id"], asset_id, 10_000_000, pinned
        )

    first = get_success_data(
        client.create_pledge_allocation(
            allocation_payload(assets[0]["id"], first_version), OFFICER
        ),
        201,
    )
    assert first["allocated_collateral_value_cents"] == 9_800_000

    after_first = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert after_first["version"] == first_version + 1
    assert after_first["active_allocation_count"] == 1
    assert after_first["total_pledged_par_cents"] == 10_000_000
    assert after_first["total_collateral_value_cents"] == 9_800_000

    stale = client.create_pledge_allocation(
        allocation_payload(assets[1]["id"], first_version), OFFICER
    )
    validate_error(stale, ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value, 412)

    unchanged = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert unchanged["version"] == first_version + 1
    assert unchanged["active_allocation_count"] == 1
    assert unchanged["status"] == "EXECUTED"
    untouched_asset = get_success_data(
        client.get_collateral_asset(assets[1]["id"], OFFICER), 200
    )
    assert untouched_asset["pledge_status"] == "UNPLEDGED"

    second_version = fixtures.agreement_version(client, perimeter["agreement_id"])
    assert second_version == first_version + 1
    replayed = get_success_data(
        client.create_pledge_allocation(
            allocation_payload(assets[1]["id"], second_version), OFFICER
        ),
        201,
    )
    assert replayed["allocated_collateral_value_cents"] == 9_800_000

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["active_allocation_count"] == 2
    assert agreement["total_pledged_par_cents"] == 20_000_000
    assert agreement["total_collateral_value_cents"] == 19_600_000

    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert account["assigned_collateral_value_cents"] == 19_600_000
    assert account["coverage_ratio_bps"] == 19_600_000 * 10000 // 78_750_000
    assert account["coverage_ratio_bps"] == 2488


def test_a_second_mark_to_market_run_needs_a_freshly_read_depository_version(client):
    """The first run bumps the depository itself, so a regulator replaying the officer's pre-run
    version is refused on freshness even though its window is perfectly legal — no run row, no
    margin call, no counter movement — and the same payload lands once the version is re-read.

    PRD: "- `POST /depositories/{id}/mtm-runs` requires `expected_depository_version`. If it does not
    equal that `Depository`'s current `version`, the request is rejected with
    `ERR_STALE_DEPOSITORY_VERSION` (HTTP 412). Periodic runs over non-overlapping windows are
    legitimately repeatable, so without this check a stale request would value collateral against a
    superseded view of the depository's capital tier, deficiency counter or approval status."
    PRD: "Either way the depository's `mtm_run_index` is set to the run's `run_index`, its
    `last_mtm_window_end` is set to the run's `window_end`, and its `collateral_posture` is
    re-derived: `FROZEN` when `consecutive_deficiency_runs` has reached 3 or more, otherwise
    `MARGIN_DEFICIENT` when `open_margin_call_count` is 1 or more, otherwise `COMPLIANT`."
    PRD: "The depository's `version` is incremented by 1, which is why a client running two
    consecutive runs must re-read the depository between them."
    PRD: "`window_start` must be at or before `window_end`, so a single-instant window is
    permissible but an inverted one is not; `window_end` may not lie in the future relative to the
    logical clock; the closed window from `window_start` to `window_end` inclusive must not intersect
    the closed window of any prior run of the same depository; and `window_start` must fall at least
    4 hours after the previous run's `window_end`, giving a mandatory buffer between consecutive
    windows."
    PRD: "`MarkToMarketRun` records are the sole exception: a mark-to-market run is an immutable
    historical record, so it carries only `id` and `created_at` — it has no `updated_at` field and no
    `version` field, and nothing in the service ever updates a run after it is written."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_depository_version_rejected_on_second_mtm_run
    """
    fixtures.set_clock(client, FIVE_AM)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    depository = fixtures.create_approved_depository(client, capital_ratio_bps=1200)
    fixtures.create_funded_account(
        client, depository["id"], public_unit["id"], 100_000_000
    )
    first_version = fixtures.depository_version(client, depository["id"])

    first_run = get_success_data(
        client.create_mtm_run(
            depository["id"],
            create_mtm_run_payload(
                "2026-07-31T00:00:00Z", DEFAULT_CLOCK_UTC, first_version
            ),
            OFFICER,
        ),
        201,
    )
    assert first_run["run_index"] == 1
    assert first_run["deficiency_cents"] == 78_750_000
    assert first_run["outcome"] == "DEFICIENT"
    assert "version" not in first_run
    assert "updated_at" not in first_run

    after_first = get_success_data(client.get_depository(depository["id"], OFFICER), 200)
    assert after_first["mtm_run_index"] == 1
    assert after_first["consecutive_deficiency_runs"] == 1
    assert after_first["last_mtm_window_end"] == DEFAULT_CLOCK_UTC
    assert after_first["version"] == first_version + 1

    second_window = create_mtm_run_payload(
        "2026-08-01T04:00:00Z", FIVE_AM, first_version
    )
    stale = client.create_mtm_run(depository["id"], second_window, REGULATOR)
    validate_error(stale, ApiErrorId.ERR_STALE_DEPOSITORY_VERSION.value, 412)

    unchanged = get_success_data(client.get_depository(depository["id"], REGULATOR), 200)
    assert unchanged["mtm_run_index"] == 1
    assert unchanged["consecutive_deficiency_runs"] == 1
    assert unchanged["open_margin_call_count"] == 1
    _runs, meta = validate_paginated(
        client.list_depository_mtm_runs(depository["id"], REGULATOR)
    )
    assert meta["total_count"] == 1

    second_version = fixtures.depository_version(client, depository["id"], REGULATOR)
    assert second_version == first_version + 1
    second_run = get_success_data(
        client.create_mtm_run(
            depository["id"],
            create_mtm_run_payload("2026-08-01T04:00:00Z", FIVE_AM, second_version),
            REGULATOR,
        ),
        201,
    )
    assert second_run["run_index"] == 2

    after_second = get_success_data(
        client.get_depository(depository["id"], REGULATOR), 200
    )
    assert after_second["consecutive_deficiency_runs"] == 2
    assert after_second["last_mtm_window_end"] == FIVE_AM
    assert after_second["collateral_posture"] == "MARGIN_DEFICIENT"


def test_the_row_version_counts_accepted_writes_and_ignores_reads(client):
    """Every row opens at version 1 with matching creation stamps, a GET never moves it, and an
    accepted write always advances it by exactly one — even a price post that re-states the price
    already stored — while the counter belongs to the row and not to the caller who wrote it.

    PRD: "Most resources additionally carry `updated_at`, refreshed on every mutation using the same
    format, and `version`, an integer that starts at 1 when the resource is created and increments by
    exactly 1 on every mutation of that resource."
    PRD: "A `SystemOperator` or a `BankCollateralOfficer` posts a new `market_price_bps`, which must
    be strictly positive, against an asset whose `eligibility_status` is still `ELIGIBLE`; the asset
    self-loops in `ELIGIBLE`, its `priced_at` is re-stamped from the clock, and its
    `market_value_cents` and `collateral_value_cents` are recomputed."
    PRD: "For the asset as a whole, `market_value_cents` is `par_value_cents` multiplied by
    `market_price_bps`, divided by 10000, rounded half up to whole cents; then
    `collateral_value_cents` is that market value multiplied by the quantity 10000 minus
    `haircut_bps`, divided by 10000, again rounded half up to whole cents."
    PRD: "`haircut_bps` is derived at registration from the asset type and is never supplied by a
    client: a `US_TREASURY` carries 200 basis points, an `AGENCY_DEBENTURE` 300, an `AGENCY_MBS` 800,
    a `MUNI_GO` 1000, a `MUNI_REVENUE` 1500, and a `LETTER_OF_CREDIT` none at all."
    PRD: "| POST | /collateral-assets/{id}/prices | Post a new market price, revaluing the asset and every active allocation on it | SystemOperator, BankCollateralOfficer |"

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_never_on_read
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_custodian(client, name="First Custody Bank")
    assert custodian["version"] == 1
    assert custodian["approval_status"] == "PENDING_APPROVAL"
    assert custodian["created_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert custodian["updated_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    depository = fixtures.create_approved_depository(client)
    asset = fixtures.create_collateral_asset(
        client, depository["id"], custodian["id"], cusip="CU-1", market_price_bps=9900
    )
    assert asset["version"] == 1
    assert asset["created_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert asset["updated_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert asset["haircut_bps"] == 200
    assert asset["priced_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert asset["market_value_cents"] == 9_900_000
    assert asset["collateral_value_cents"] == 9_702_000

    read_custodian = get_success_data(client.get_custodian(custodian["id"], REGULATOR), 200)
    assert read_custodian["version"] == 1
    assert read_custodian["updated_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    approved = get_success_data(client.approve_custodian(custodian["id"], REGULATOR), 200)
    assert approved["version"] == 2
    assert approved["approval_status"] == "APPROVED"
    assert approved["approved_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    identical = get_success_data(
        client.post_price(asset["id"], price_payload(9900), OPERATOR), 200
    )
    assert identical["version"] == 2
    assert identical["market_price_bps"] == 9900
    assert identical["priced_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert identical["eligibility_status"] == "ELIGIBLE"
    assert identical["market_value_cents"] == 9_900_000

    repriced = get_success_data(
        client.post_price(asset["id"], price_payload(9800), OFFICER), 200
    )
    assert repriced["version"] == 3
    assert repriced["market_price_bps"] == 9800
    assert repriced["market_value_cents"] == 9_800_000
    assert repriced["collateral_value_cents"] == 9_604_000

    first_read = get_success_data(client.get_collateral_asset(asset["id"], COMPLIANCE), 200)
    assert first_read["version"] == 3
    second_read = get_success_data(client.get_collateral_asset(asset["id"], COMPLIANCE), 200)
    assert second_read["version"] == 3
    assert second_read["market_value_cents"] == 9_800_000


def test_a_filtered_page_counts_the_filtered_set_and_not_the_table(client):
    """`total_count` describes the rows matching the filters, so a type-filtered page reports four of
    six and never leaks a municipal row; marking one asset ineligible moves it between eligibility
    filters instead of deleting it, and a page size outside 1 through 100 is a malformed request.

    PRD: "Every list endpoint accepts two optional query parameters. `limit` controls page size: it
    defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` controls the
    zero-based starting position: it defaults to 0 and may not be negative. A `limit` outside the
    range 1 through 100 inclusive, or a negative `offset`, is a malformed request and is rejected
    with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD: "The `meta` object of a list response carries `limit` (the effective page size), `offset`
    (the effective starting position), `total_count` (the number of records matching the filters
    before pagination is applied) and `has_more` (true when `offset` plus the number of returned
    records is strictly less than `total_count`)."
    PRD: "| GET | /collateral-assets | List collateral assets, filterable by depository, custodian, asset type, eligibility status and pledge status | StateRegulator, BankCollateralOfficer, BankComplianceOfficer, Custodian, SystemOperator |"
    PRD: "A `StateRegulator` may declare an asset ineligible, supplying an `ineligible_reason`. The
    asset moves `ELIGIBLE → INELIGIBLE`, its `collateral_value_cents` collapses to zero, the reason
    is stored, and its `version` is incremented."

    Design: Corner/cross_cutting_complexity_layers/pagination_with_filtering_on_collateral_assets
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client, name="First Custody Bank")
    depository = fixtures.create_approved_depository(client)
    treasuries = [
        fixtures.create_collateral_asset(
            client, depository["id"], custodian["id"], cusip=f"CU-{n}"
        )["id"]
        for n in (1, 2, 3, 4)
    ]
    munis = [
        fixtures.create_collateral_asset(
            client,
            depository["id"],
            custodian["id"],
            cusip=f"MG-{n}",
            asset_type="MUNI_GO",
        )["id"]
        for n in (1, 2)
    ]

    rows, meta = validate_paginated(
        client.list_collateral_assets(COMPLIANCE, {"depository_id": depository["id"]})
    )
    assert meta["total_count"] == 6
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(rows) == 6

    page, page_meta = validate_paginated(
        client.list_collateral_assets(
            COMPLIANCE,
            {
                "depository_id": depository["id"],
                "asset_type": "US_TREASURY",
                "limit": 2,
                "offset": 2,
            },
        )
    )
    assert page_meta["total_count"] == 4
    assert page_meta["has_more"] is False
    assert page_meta["limit"] == 2
    assert page_meta["offset"] == 2
    assert len(page) == 2
    assert all(row["asset_type"] == "US_TREASURY" for row in page)
    assert {row["id"] for row in page} <= set(treasuries)
    assert not {row["id"] for row in page} & set(munis)

    downgraded = fixtures.mark_ineligible(
        client, munis[0], ineligible_reason="Issuer downgraded below the program floor"
    )
    assert downgraded["eligibility_status"] == "INELIGIBLE"
    assert downgraded["ineligible_reason"] == "Issuer downgraded below the program floor"
    assert downgraded["collateral_value_cents"] == 0

    ineligible_rows, ineligible_meta = validate_paginated(
        client.list_collateral_assets(
            REGULATOR,
            {"depository_id": depository["id"], "eligibility_status": "INELIGIBLE"},
        )
    )
    assert ineligible_meta["total_count"] == 1
    assert [row["id"] for row in ineligible_rows] == [munis[0]]

    _eligible, eligible_meta = validate_paginated(
        client.list_collateral_assets(
            REGULATOR,
            {"depository_id": depository["id"], "eligibility_status": "ELIGIBLE"},
        )
    )
    assert eligible_meta["total_count"] == 5

    too_large = client.list_collateral_assets(
        REGULATOR, {"depository_id": depository["id"], "limit": 101}
    )
    validate_error(too_large, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    too_small = client.list_collateral_assets(
        REGULATOR, {"depository_id": depository["id"], "limit": 0}
    )
    validate_error(too_small, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    still_there, still_meta = validate_paginated(
        client.list_collateral_assets(REGULATOR, {"depository_id": depository["id"]})
    )
    assert still_meta["total_count"] == 6
    assert munis[0] in {row["id"] for row in still_there}


def test_a_superseding_forecast_needs_a_freshly_read_account_version(client):
    """Filing a forecast bumps the account, so replaying the pre-filing version is refused before the
    supersession side effect can run; the re-read version retires the first forecast, and a forecast
    on a different cycle leaves it alone because supersession is scoped to the cycle label.

    PRD: "- `POST /runoff-forecasts` requires `expected_deposit_account_version`. If it does not equal
    the referenced `DepositAccount`'s current `version`, the request is rejected with
    `ERR_STALE_DEPOSIT_ACCOUNT_VERSION` (HTTP 412). Because filing a forecast supersedes the account's
    prior forecast for the same cycle, a forecast built on a stale view of the account's balance and
    requirement must be refused on the version check rather than silently replacing a newer one."
    PRD: "A filed forecast begins at `status` `OPEN` with `requires_reforecast` false and
    `superseded_at` null. Filing is also a supersession: any prior forecast for the same account and
    the same `cycle_label` that stands in `OPEN` or `STALE` status is moved to `SUPERSEDED` with
    `superseded_at` stamped from the clock, and when the superseded forecast was `STALE`, its
    `requires_reforecast` flag is cleared back to false as it is retired."
    PRD: "Because a forecast is a claim about an account, filing one increments that
    `DepositAccount`'s `version` by 1."
    PRD: "For each window the projected uninsured amount is `projected_balance_cents` less the
    25,000,000-cent insurance coverage limit, floored at zero; the window's projected requirement is
    that uninsured figure multiplied by the frozen percentage, divided by 10000, rounded half up to
    whole cents."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_deposit_account_version_rejected_then_forecast_supersedes
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    depository = fixtures.create_approved_depository(client)
    account = fixtures.create_funded_account(
        client, depository["id"], public_unit["id"], 100_000_000
    )
    treasurer = make_public_unit_treasurer_headers(public_unit["id"])
    windows = [projected_window(DEFAULT_CLOCK_UTC, HORIZON_END, 100_000_000)]
    first_version = account["version"]

    def forecast_payload(pinned, cycle_label="TAX_COLLECTION", basis="PEAK_WINDOW"):
        return create_runoff_forecast_payload(
            account["id"],
            DEFAULT_CLOCK_UTC,
            HORIZON_END,
            windows,
            pinned,
            cycle_label=cycle_label,
            basis=basis,
        )

    first = get_success_data(
        client.create_runoff_forecast(forecast_payload(first_version), treasurer), 201
    )
    assert first["status"] == "OPEN"
    assert first["projected_required_collateral_cents"] == 78_750_000
    assert first["superseded_at"] is None
    assert first["requires_reforecast"] is False
    assert fixtures.account_version(client, account["id"], treasurer) == first_version + 1

    stale = client.create_runoff_forecast(
        forecast_payload(first_version, basis="PERIOD_END"), treasurer
    )
    validate_error(stale, ApiErrorId.ERR_STALE_DEPOSIT_ACCOUNT_VERSION.value, 412)

    survivor = get_success_data(client.get_runoff_forecast(first["id"], treasurer), 200)
    assert survivor["status"] == "OPEN"
    assert survivor["superseded_at"] is None
    _rows, meta = validate_paginated(
        client.list_account_runoff_forecasts(account["id"], treasurer)
    )
    assert meta["total_count"] == 1

    second_version = fixtures.account_version(client, account["id"], treasurer)
    assert second_version == first_version + 1
    second = get_success_data(
        client.create_runoff_forecast(
            forecast_payload(second_version, basis="PERIOD_END"), treasurer
        ),
        201,
    )
    assert second["status"] == "OPEN"
    assert second["projected_required_collateral_cents"] == 78_750_000

    superseded = get_success_data(client.get_runoff_forecast(first["id"], treasurer), 200)
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    third_version = fixtures.account_version(client, account["id"], treasurer)
    assert third_version == second_version + 1
    third = get_success_data(
        client.create_runoff_forecast(
            forecast_payload(third_version, cycle_label="DISBURSEMENT"), treasurer
        ),
        201,
    )
    assert third["status"] == "OPEN"
    assert third["cycle_label"] == "DISBURSEMENT"

    other_cycle = get_success_data(client.get_runoff_forecast(second["id"], treasurer), 200)
    assert other_cycle["status"] == "OPEN"
    assert other_cycle["superseded_at"] is None
    assert fixtures.account_version(client, account["id"], treasurer) == first_version + 3


def test_one_price_post_rebuilds_the_whole_derived_chain_without_moving_par(client):
    """A single vendor price walks the whole mirror chain — asset value, allocation value, agreement
    total, depository total, account coverage — while the pledged par stays exactly where it was, and
    it issues no margin call because valuation is not a mark-to-market run.

    PRD: "The repricing then propagates: every `ACTIVE` allocation on that asset recomputes its
    `allocated_collateral_value_cents`; every agreement touched recomputes
    `total_collateral_value_cents`; dedicated beneficiaries recompute their coverage while pooled
    agreements re-run the pool waterfall; the depository's `total_pledged_collateral_value_cents` is
    recomputed; and the asset's `version` is incremented."
    PRD: "For an individual allocation, the same two steps run against the pledged slice rather than
    the full par: the allocation's market value is `allocated_par_cents` multiplied by the asset's
    `market_price_bps`, divided by 10000, rounded half up; then `allocated_collateral_value_cents` is
    that figure multiplied by 10000 minus the asset's `haircut_bps`, divided by 10000, rounded half
    up."
    PRD: "Concretely: an agreement's `total_collateral_value_cents` is the sum of
    `allocated_collateral_value_cents` over its allocations that are `ACTIVE` and whose asset is
    `ELIGIBLE`; its `total_pledged_par_cents` is the sum of `allocated_par_cents` over all of its
    `ACTIVE` allocations, whether or not the underlying asset is still eligible; and its
    `active_allocation_count` is the number of its allocations in `ACTIVE` status."
    PRD: "A depository's `total_pledged_collateral_value_cents` is the sum of
    `total_collateral_value_cents` over its agreements in `EXECUTED` status."
    PRD: "Coverage is measured by `coverage_ratio_bps`. When `required_collateral_cents` is zero the
    ratio is defined as 10000; otherwise it is `assigned_collateral_value_cents` multiplied by 10000,
    divided by `required_collateral_cents`, floored to whole basis points."
    PRD: "Thereafter the unit's exposure is a strictly ordered read of its accounts: it is
    `ESCALATED` whenever any of its accounts has `funding_status` `RESTRICTED`; otherwise it is
    `WATCH` whenever any of its accounts has `collateral_status` `DEFICIENT`; otherwise it is
    `NORMAL`."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_after_repricing_an_allocated_asset
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        cusip="CU-1",
        par_value_cents=40_000_000,
    )
    assert asset["market_value_cents"] == 40_000_000
    assert asset["collateral_value_cents"] == 39_200_000
    allocation = fixtures.create_allocation(
        client, perimeter["agreement_id"], asset["id"], 40_000_000
    )
    assert allocation["allocated_collateral_value_cents"] == 39_200_000

    before = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert before["required_collateral_cents"] == 78_750_000
    assert before["assigned_collateral_value_cents"] == 39_200_000
    assert before["coverage_ratio_bps"] == 39_200_000 * 10000 // 78_750_000
    assert before["coverage_ratio_bps"] == 4977
    assert before["collateral_status"] == "DEFICIENT"
    unit_before = get_success_data(
        client.get_public_unit(perimeter["public_unit_id"], REGULATOR), 200
    )
    assert unit_before["exposure_status"] == "WATCH"

    repriced = get_success_data(
        client.post_price(asset["id"], price_payload(9000), OPERATOR), 200
    )
    assert repriced["market_value_cents"] == 36_000_000
    assert repriced["collateral_value_cents"] == 35_280_000
    assert repriced["priced_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert repriced["pledged_par_cents"] == 40_000_000

    reprized_allocation = get_success_data(
        client.get_pledge_allocation(allocation["id"], OFFICER), 200
    )
    assert reprized_allocation["allocated_par_cents"] == 40_000_000
    assert reprized_allocation["allocated_collateral_value_cents"] == 35_280_000
    assert reprized_allocation["status"] == "ACTIVE"

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["total_collateral_value_cents"] == 35_280_000
    assert agreement["total_pledged_par_cents"] == 40_000_000

    depository = get_success_data(
        client.get_depository(perimeter["depository_id"], OFFICER), 200
    )
    assert depository["total_pledged_collateral_value_cents"] == 35_280_000
    assert depository["total_pledged_par_cents"] == 40_000_000

    after = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert after["assigned_collateral_value_cents"] == 35_280_000
    assert after["coverage_ratio_bps"] == 4480
    assert after["collateral_status"] == "DEFICIENT"

    unit_after = get_success_data(
        client.get_public_unit(perimeter["public_unit_id"], REGULATOR), 200
    )
    assert unit_after["exposure_status"] == "WATCH"

    _calls, call_meta = validate_paginated(
        client.list_margin_calls(REGULATOR, {"depository_id": perimeter["depository_id"]})
    )
    assert call_meta["total_count"] == 0
