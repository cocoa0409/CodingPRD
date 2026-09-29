"""Layers that meet in one flow: the version echo, and the two repurchase legs.

Every test builds the whole of its own world against an empty database, with the
logical clock at its boot instant of 2026-08-01T00:00:00Z (PRD §2.6) unless the
test moves it.
"""

from __future__ import annotations

from test_helpers import (
    SPONSOR,
    TRANSFER_AGENT,
    ApiErrorId,
    NavRecordStatus,
    RepurchaseRequestStatus,
    assert_created,
    assert_error,
    assert_fields,
    assert_ok,
    assert_total_count,
    nav_record_payload,
)
from test_helpers.fixtures import ReitWorld


def _thornsett_class(world: ReitWorld) -> dict:
    """A freshly created zero-load class I, so its counter still reads 1."""
    offering = world.offering(name="Thornsett Income REIT")
    share_class = world.share_class(offering["id"])
    return {"offering_id": offering["id"], "share_class": share_class}


def _underbrook_quarter(world: ReitWorld, api) -> dict:
    """Three 2026-Q3 periods, each tendered for 100000000 e4 and processed at its cutoff."""
    world.set_clock("2026-07-01T00:00:00Z", SPONSOR)
    offering = world.offering(name="Underbrook Income REIT")
    share_class = world.share_class(offering["id"])
    firm = world.broker_dealer(
        firm_name="Underbrook Placement", crd_number="CRD-360001"
    )
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(
        offering["id"], firm["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement["id"])
    investor = world.investor(
        legal_name="Yara Nordstrom",
        email="yara.nordstrom@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=2000000000,
    )
    world.document_suitability(investor["id"], "SUIT-YARA-2026-07")
    subscription = world.subscription(
        offering["id"], share_class["id"], investor["id"], agreement["id"], 100000000
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(offering["id"])
    funded_class = world.read_share_class(share_class["id"])
    nav = world.published_nav(
        share_class["id"], "2026-06-01", "2026-06-30", 100000000
    )

    months = [
        ("2026-07", "2026-07-01T00:00:00Z", "2026-07-10T00:00:00Z", "2026-07-12"),
        ("2026-08", "2026-08-01T00:00:00Z", "2026-08-10T00:00:00Z", "2026-08-12"),
        ("2026-09", "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z", "2026-09-12"),
    ]
    periods, requests = [], []
    for month, opens_at, cutoff, settlement in months:
        world.set_clock(opens_at, TRANSFER_AGENT)
        period = world.repurchase_period(
            offering["id"],
            period_month=month,
            opens_at=opens_at,
            request_cutoff_at=cutoff,
            settlement_date=settlement,
        )
        tender = world.tender(
            period["id"], share_class["id"], 100000000, investor["id"]
        )
        world.set_clock(cutoff, TRANSFER_AGENT)
        periods.append(
            assert_ok(api.process_repurchase_period(period["id"], None, TRANSFER_AGENT))
        )
        requests.append(world.read_request(tender["id"]))
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "investor_id": investor["id"],
        "funded_class": funded_class,
        "nav": nav,
        "periods": periods,
        "requests": requests,
    }


class TestStaleShareClassVersion:
    """PRD §2.8: the valuation write carries a version echo of its share class."""

    def test_a_stale_echo_creates_no_valuation_row_and_moves_no_counter(
        self, world: ReitWorld, api
    ):
        """Replaying the version the June write consumed is refused, leaving one row and version 2.

        PRD §2.8: "A `POST /nav-records` request must carry `expected_share_class_version` as a mandatory field, holding the `version` of the target `ShareClass` that the client last read."
        PRD §2.8: "If that value does not equal the share class's currently stored `version`, the write is rejected with `ERR_STALE_SHARE_CLASS_VERSION` and HTTP 412, and no valuation row is created."

        Design: Corner/cross_cutting_complexity_layers/a_stale_share_class_version_creates_no_nav_row_and_the_counter_only_moves_on_writes
        """
        setup = _thornsett_class(world)
        share_class_id = setup["share_class"]["id"]
        assert setup["share_class"]["version"] == 1, (
            "a freshly created share class opens at version 1"
        )

        june = assert_created(
            api.create_nav_record(
                nav_record_payload(
                    share_class_id,
                    setup["share_class"]["version"],
                    period_start_date="2026-06-01",
                    period_end_date="2026-06-30",
                    gross_asset_value_cents=4000000,
                    other_liabilities_cents=0,
                ),
                SPONSOR,
            )
        )
        assert_fields(june, status=NavRecordStatus.DRAFT)

        current_version = world.share_class_version(share_class_id)
        assert current_version == 2, (
            "creating a valuation incremented the parent share class's version"
        )

        stale = api.create_nav_record(
            nav_record_payload(
                share_class_id,
                current_version - 1,
                period_start_date="2026-07-01",
                period_end_date="2026-07-31",
                gross_asset_value_cents=4100000,
                other_liabilities_cents=0,
            ),
            SPONSOR,
        )
        assert_error(stale, ApiErrorId.STALE_SHARE_CLASS_VERSION, 412)

        assert world.share_class_version(share_class_id) == 2, (
            "a refused write does not advance the counter"
        )
        assert_total_count(
            api.list_nav_records({"share_class_id": share_class_id}, SPONSOR), 1
        )

    def test_the_share_class_counter_advances_once_for_each_accepted_valuation(
        self, world: ReitWorld, api
    ):
        """Two valuations carry the class from version 1 to version 3 and leave June's figures alone.

        PRD §2.8: "A successful create increments the share class's `version` by 1."
        PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp recording the most recent mutation of the row, and `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

        Design: Corner/cross_cutting_complexity_layers/a_stale_share_class_version_creates_no_nav_row_and_the_counter_only_moves_on_writes
        """
        setup = _thornsett_class(world)
        share_class_id = setup["share_class"]["id"]

        june = world.nav_record(
            share_class_id, "2026-06-01", "2026-06-30", 4000000, 0, 1
        )
        assert world.share_class_version(share_class_id) == 2

        july = assert_created(
            api.create_nav_record(
                nav_record_payload(
                    share_class_id,
                    2,
                    period_start_date="2026-07-01",
                    period_end_date="2026-07-31",
                    gross_asset_value_cents=4100000,
                    other_liabilities_cents=0,
                ),
                SPONSOR,
            )
        )
        assert_fields(july, status=NavRecordStatus.DRAFT)
        assert world.share_class_version(share_class_id) == 3

        assert_fields(
            world.read_nav_record(june["id"]), gross_asset_value_cents=4000000
        )
        assert_total_count(
            api.list_nav_records({"share_class_id": share_class_id}, SPONSOR), 2
        )


class TestQuarterlyLegOvertakesTheMonthlyLeg:
    """PRD §3.8: capacity is the lesser of a monthly and a quarterly leg."""

    def test_the_quarterly_leg_binds_in_the_third_month_of_the_quarter(
        self, world: ReitWorld, api
    ):
        """Months one and two are capped monthly at 2000000 and 1960000; month three is capped quarterly at 842000.

        PRD §3.8: "`monthly_cap_cents` is two percent of it — the aggregate multiplied by 200 basis points, divided by 10,000, floored."
        PRD §3.8: "The quarterly leg is measured against a five percent ceiling: the quarter's usage is the sum of `settled_amount_cents` across the offering's *other* periods that share this period's `quarter_key` and have already reached `PROCESSED`, and `quarterly_remaining_cents` is the greater of zero and the aggregate multiplied by 500 basis points, divided by 10,000, floored, less that usage."
        PRD §3.8: "Note that the quarterly ceiling is recomputed from the *current* aggregate valuation every month rather than being fixed as a dollar budget at the start of the quarter, so a falling valuation can make the quarterly leg bind in the third month of a quarter even where the monthly leg alone would not have."

        Design: Corner/cross_cutting_complexity_layers/the_quarterly_leg_takes_over_from_the_monthly_leg_in_the_third_month
        """
        setup = _underbrook_quarter(world, api)
        assert_fields(setup["funded_class"], shares_outstanding_e4=1000000000)
        assert_fields(setup["nav"], nav_per_share_cents=1000)

        first, second, third = setup["periods"]
        for period in (first, second, third):
            assert_fields(period, quarter_key="2026-Q3")

        assert_fields(
            first,
            monthly_cap_cents=2000000,
            quarterly_remaining_cents=5000000,
            capacity_cents=2000000,
            settled_amount_cents=2000000,
            prorated=True,
        )
        assert_fields(
            second,
            monthly_cap_cents=1960000,
            quarterly_remaining_cents=2900000,
            capacity_cents=1960000,
            settled_amount_cents=1960000,
        )
        assert_fields(
            third,
            monthly_cap_cents=1920800,
            quarterly_remaining_cents=842000,
            capacity_cents=842000,
            settled_amount_cents=842000,
        )

    def test_each_settlement_deducts_two_percent_and_reconciles_on_the_statement(
        self, world: ReitWorld, api
    ):
        """Three prorated grants each bear the early-repurchase deduction and add up on the statement.

        PRD §3.8: "Otherwise each tier-two tender is granted the remainder multiplied by its own requested value, divided by the tier-two total, and floored; the flooring leaves a shortfall of a few cents against the remainder, and that leftover is distributed one cent at a time to tier-two tenders in ascending `created_at` order until it is exhausted."
        PRD §3.8: "The lot's holding period is the whole number of days from the calendar date of its `issued_date` to the period's `settlement_date`; where that count is fewer than 365 days the lot bears a deduction of two percent of its own gross proceeds — the lot gross multiplied by 200 basis points, divided by 10,000 and rounded half up — and where it is 365 days or more the lot bears no deduction at all."
        PRD §3.8: "The request records `early_repurchase_deduction_cents` as the sum of its per-lot deductions and `net_proceeds_cents` as the sum of its per-lot gross amounts each less that lot's deduction, and the deduction total is added to the stockholder's `cumulative_early_repurchase_deduction_cents`."

        Design: Corner/cross_cutting_complexity_layers/the_quarterly_leg_takes_over_from_the_monthly_leg_in_the_third_month
        """
        setup = _underbrook_quarter(world, api)
        first, second, third = setup["requests"]

        assert_fields(
            first,
            status=RepurchaseRequestStatus.PARTIALLY_FULFILLED,
            approved_value_cents=2000000,
            approved_shares_e4=20000000,
            early_repurchase_deduction_cents=40000,
            net_proceeds_cents=1960000,
        )
        assert_fields(
            second,
            approved_shares_e4=19600000,
            early_repurchase_deduction_cents=39200,
            net_proceeds_cents=1920800,
        )
        assert_fields(
            third,
            approved_value_cents=842000,
            approved_shares_e4=8420000,
            early_repurchase_deduction_cents=16840,
            net_proceeds_cents=825160,
        )

        statement = assert_ok(
            api.get_investor_statement(setup["investor_id"], TRANSFER_AGENT)
        )
        assert_fields(
            statement,
            total_shares_e4=951980000,
            cumulative_early_repurchase_deduction_cents=96040,
            estimated_value_cents=95198000,
        )
        assert_fields(
            world.read_offering(setup["offering_id"]), aggregate_nav_cents=95198000
        )
