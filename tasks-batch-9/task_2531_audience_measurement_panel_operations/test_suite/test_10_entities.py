"""Entity creation, retrieval and listing contracts (PRD 2.3, 2.5, 3.1-3.9).

Every test in this file pins what the server itself owns on a freshly written row:
the computed defaults, the roll-ups the write moves on its parent, the fields a
client may not supply, and the ordering and pagination of the collection reads.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_common_properties,
    assert_freshly_created,
    assert_ordered_by,
    expected_boost_reservation,
    expected_fill_rate,
    ids_of,
)
from test_helpers.constants import (
    BOOSTED_MULTIPLIER,
    STANDARD_BASE_FEE_CENTS,
    STANDARD_SLA_HOURS,
)
from test_helpers.factories import (
    cell_population,
    processing_run_payload,
    tuning_interval_payload,
    universe_estimate_payload,
)
from test_helpers.fixtures import CLOCK_T0, VINTAGE_FROM, VINTAGE_TO, PanelHarness
from test_helpers.test_users import (
    make_auditor_headers,
    make_director_headers,
    make_statistician_headers,
)


# ----------------------------------------------------------------------
# PRD 2.5 renders `created_at` and every business-event stamp as "an ISO 8601
# UTC timestamp with three fractional digits", while the design index writes the
# same instants without the fractional part. `test_helpers/assertions.py` has no
# instant-comparison helper, so the two forms are reconciled here.
# ----------------------------------------------------------------------

def _instant_seconds(value: str) -> int:
    """Whole seconds since the epoch for an ISO 8601 UTC instant."""
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC instant: {value!r}"
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _assert_instant(got: str, want: str, label: str = "timestamp") -> None:
    """Assert two ISO 8601 UTC instants name the same moment, to the second."""
    assert _instant_seconds(got) == _instant_seconds(want), (
        f"{label}: expected {want!r}, got {got!r}"
    )


class TestMarketEntity:
    """Market registration and single-row retrieval (PRD 3.1)."""

    def test_market_creation_echoes_inputs_and_lands_restricted(self, panel: PanelHarness):
        """A market with no cells is RESTRICTED, not OPEN, at registration.

        PRD 3.1: "Note the consequence for a brand-new market: it has no quota
        cells at all, so `under_target_cell_count` is 0, clause 3 fires before
        clause 4, and the initial posture is `RESTRICTED` rather than `OPEN`."

        Design: Corner/entities/market_creation_returns_computed_defaults_and_restricted_posture
        """
        response = panel.client.create_market(
            panel.ops,
            name="Metro Alpha",
            market_code="DMA-601",
            dma_rank=101,
            incentive_budget_cents=500000,
        )
        body = response.json()
        assert body["response_type"] == "object"
        market = validate_success(response, 201)

        assert isinstance(market["id"], str) and market["id"] != ""
        assert is_valid_uuid(market["id"])
        assert market["market_code"] == "DMA-601"
        assert market["name"] == "Metro Alpha"
        assert market["dma_rank"] == 101
        assert market["incentive_budget_cents"] == 500000
        assert market["recruitment_posture"] == "RESTRICTED"
        # PRD 3.1: "`posture_changed_at` is stamped from the logical clock at
        # registration".
        _assert_instant(market["posture_changed_at"], CLOCK_T0, "posture_changed_at")
        # PRD 2.5: "`version` -- an integer that starts at 1 on creation".
        assert_common_properties(market, expected_version=1)

    def test_market_creation_starts_every_rollup_at_zero(self, panel: PanelHarness):
        """Registration leaves every server-maintained roll-up at its floor.

        PRD 3.1: "`accreditation_status` starts at `UNAUDITED` and thereafter
        holds the outcome of the most recently finalized audit -- `ACCREDITED`,
        `QUALIFIED` or `DENIED`. `publication_blocked` starts false.
        `limitation_disclosures` starts as an empty array and only ever grows."

        Design: Corner/entities/market_creation_returns_computed_defaults_and_restricted_posture
        """
        market = validate_success(
            panel.client.create_market(
                panel.ops,
                name="Metro Alpha",
                market_code="DMA-601",
                dma_rank=101,
                incentive_budget_cents=500000,
            ),
            201,
        )

        assert market["accreditation_status"] == "UNAUDITED"
        assert market["publication_blocked"] is False
        assert market["limitation_disclosures"] == []
        assert market["incentive_budget_committed_cents"] == 0
        assert market["incentive_budget_reserved_cents"] == 0
        assert market["quota_cell_count"] == 0
        assert market["filled_cell_count"] == 0
        assert market["under_target_cell_count"] == 0
        assert market["open_audit_count"] == 0

    def test_market_retrieval_returns_the_stored_row(self, panel: PanelHarness):
        """GET returns the roll-ups the quota-cell write already moved.

        PRD 3.1: "That armed boost immediately reserves budget on the parent
        market, the market's `quota_cell_count` and `under_target_cell_count`
        each rise by one, the posture is re-evaluated -- which moves a market
        holding its first cell from `RESTRICTED` to `OPEN`, because clause 3 no
        longer matches -- and the market's `version` advances by one."

        Design: Corner/entities/market_retrieval_returns_the_stored_row
        """
        market = panel.create_market(
            name="Metro Beta",
            market_code="DMA-602",
            dma_rank=102,
            incentive_budget_cents=500000,
        )
        panel.create_quota_cell(
            market["id"],
            age_band="P18_34",
            income_band="MID",
            geo_zone="URBAN",
            target_households=2,
            base_incentive_cents=1000,
        )

        stored = validate_success(
            panel.client.get_market(panel.statistician, market["id"]), 200
        )

        assert stored["id"] == market["id"]
        assert stored["market_code"] == "DMA-602"
        assert stored["quota_cell_count"] == 1
        assert stored["under_target_cell_count"] == 1
        assert stored["filled_cell_count"] == 0
        # PRD 3.1: "the market's `incentive_budget_reserved_cents` rises by the
        # cell's `base_incentive_cents` multiplied by one quarter and by
        # `target_households`, rounded half up to a whole cent."
        assert stored["incentive_budget_reserved_cents"] == expected_boost_reservation(1000, 2)
        assert stored["incentive_budget_reserved_cents"] == 500
        assert stored["incentive_budget_committed_cents"] == 0
        assert stored["recruitment_posture"] == "OPEN"
        assert stored["version"] == 2


class TestMarketListing:
    """The markets collection: posture filter, pagination and ordering (PRD 2.3)."""

    @staticmethod
    def _three_markets(panel: PanelHarness):
        """DMA-603 and DMA-604 stay cell-less (RESTRICTED); DMA-605 gets a cell (OPEN)."""
        third = panel.create_market(
            name="Metro Gamma",
            market_code="DMA-603",
            dma_rank=103,
            incentive_budget_cents=200000,
        )
        fourth = panel.create_market(
            name="Metro Delta",
            market_code="DMA-604",
            dma_rank=104,
            incentive_budget_cents=200000,
        )
        fifth = panel.create_market(
            name="Metro Epsilon",
            market_code="DMA-605",
            dma_rank=105,
            incentive_budget_cents=200000,
        )
        panel.create_quota_cell(
            fifth["id"],
            age_band="P35_54",
            income_band="LOW",
            geo_zone="RURAL",
            target_households=1,
            base_incentive_cents=1000,
        )
        return third, fourth, fifth

    def test_restricted_filter_paginates_across_two_pages(self, panel: PanelHarness):
        """The posture filter reports the pre-pagination count on both pages.

        PRD 2.3: "`total_count` (the number of rows the filter matched before
        pagination) and `has_more` (true when rows remain beyond this page)".

        Design: Corner/entities/market_listing_filters_by_posture_and_paginates
        """
        third, fourth, fifth = self._three_markets(panel)

        first_response = panel.client.list_markets(
            panel.rep, recruitment_posture="RESTRICTED", limit=1, offset=0
        )
        assert first_response.json()["response_type"] == "array"
        page_one, meta_one = validate_paginated(first_response)
        assert meta_one["total_count"] == 2
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 1
        assert meta_one["offset"] == 0
        assert len(page_one) == 1

        page_two, meta_two = validate_paginated(
            panel.client.list_markets(
                panel.rep, recruitment_posture="RESTRICTED", limit=1, offset=1
            )
        )
        assert meta_two["total_count"] == 2
        assert meta_two["has_more"] is False
        assert len(page_two) == 1

        together = ids_of(page_one) + ids_of(page_two)
        assert sorted(together) == sorted([third["id"], fourth["id"]])
        assert fifth["id"] not in together

    def test_restricted_pages_are_ordered_newest_first_then_by_code(
        self, panel: PanelHarness
    ):
        """Both markets share one logical-clock `created_at`, so the code breaks the tie.

        PRD 2.3: "Markets are ordered newest first - by `created_at` descending,
        and ties broken by `market_code` ascending."

        Design: Corner/entities/market_listing_filters_by_posture_and_paginates
        """
        self._three_markets(panel)

        page_one, _ = validate_paginated(
            panel.client.list_markets(
                panel.rep, recruitment_posture="RESTRICTED", limit=1, offset=0
            )
        )
        page_two, _ = validate_paginated(
            panel.client.list_markets(
                panel.rep, recruitment_posture="RESTRICTED", limit=1, offset=1
            )
        )
        rows = page_one + page_two

        # PRD 2.5: `created_at` is "taken from the logical clock", which never
        # moved between the two registrations, so both rows carry the same
        # instant and the `market_code` tie-break decides the order.
        assert rows[0]["created_at"] == rows[1]["created_at"]
        assert_ordered_by(rows, [("created_at", "desc"), ("market_code", "asc")])
        assert [row["market_code"] for row in rows] == ["DMA-603", "DMA-604"]

    def test_open_filter_isolates_the_market_holding_a_cell(self, panel: PanelHarness):
        """The OPEN filter returns only the market with a cell, at the default page size.

        PRD 2.3: "`limit` caps the number of rows returned; when omitted it
        defaults to 10 ... `offset` is the number of rows to skip before the page
        begins and defaults to 0."

        Design: Corner/entities/market_listing_filters_by_posture_and_paginates
        """
        _, _, fifth = self._three_markets(panel)

        rows, meta = validate_paginated(
            panel.client.list_markets(panel.rep, recruitment_posture="OPEN")
        )

        assert meta["total_count"] == 1
        assert ids_of(rows) == [fifth["id"]]
        assert meta["limit"] == 10
        assert meta["offset"] == 0


class TestQuotaCellEntity:
    """Quota-cell creation, its armed boost and the parent roll-ups (PRD 3.1)."""

    def test_new_cell_is_under_target_with_its_boost_armed(self, panel: PanelHarness):
        """An empty cell is graded UNDER_TARGET and arms the boost in the same write.

        PRD 3.1: "A newly created cell is empty, and the fill calculation
        therefore lands it in its most aggressive recruitment stance:
        `intab_count` 0, `fill_rate` 0.0000, `quota_status` `UNDER_TARGET`,
        `incentive_boost_active` true and `effective_incentive_multiplier` 1.25."

        Design: Corner/entities/quota_cell_creation_arms_boost_and_moves_market_rollups
        """
        market = panel.create_market(
            name="Metro Zeta",
            market_code="DMA-606",
            dma_rank=106,
            incentive_budget_cents=500000,
        )
        assert market["recruitment_posture"] == "RESTRICTED"

        cell = validate_success(
            panel.client.create_quota_cell(
                panel.ops,
                market["id"],
                age_band="P55_PLUS",
                income_band="HIGH",
                geo_zone="SUBURBAN",
                target_households=3,
                base_incentive_cents=4000,
            ),
            201,
        )

        assert cell["intab_count"] == 0
        assert cell["fill_rate"] == expected_fill_rate(0, 3)
        assert cell["fill_rate"] == 0.0
        assert cell["quota_status"] == "UNDER_TARGET"
        assert cell["incentive_boost_active"] is True
        assert cell["effective_incentive_multiplier"] == BOOSTED_MULTIPLIER

    def test_cell_write_moves_market_rollups_and_flips_the_posture(
        self, panel: PanelHarness
    ):
        """The reserve, the counts and the posture are all current on the next read.

        PRD 3.1: "That armed boost immediately reserves budget on the parent
        market, the market's `quota_cell_count` and `under_target_cell_count`
        each rise by one, the posture is re-evaluated - which moves a market
        holding its first cell from `RESTRICTED` to `OPEN`, because clause 3 no
        longer matches - and the market's `version` advances by one."

        Design: Corner/entities/quota_cell_creation_arms_boost_and_moves_market_rollups
        """
        market = panel.create_market(
            name="Metro Zeta",
            market_code="DMA-606",
            dma_rank=106,
            incentive_budget_cents=500000,
        )
        panel.create_quota_cell(
            market["id"],
            age_band="P55_PLUS",
            income_band="HIGH",
            geo_zone="SUBURBAN",
            target_households=3,
            base_incentive_cents=4000,
        )

        after = validate_success(panel.client.get_market(panel.ops, market["id"]), 200)

        assert after["incentive_budget_reserved_cents"] == expected_boost_reservation(4000, 3)
        assert after["incentive_budget_reserved_cents"] == 3000
        assert after["quota_cell_count"] == 1
        assert after["under_target_cell_count"] == 1
        assert after["recruitment_posture"] == "OPEN"
        _assert_instant(after["posture_changed_at"], CLOCK_T0, "posture_changed_at")


class TestHouseholdEntity:
    """Recruitment defaults and the server-owned fields of a household (PRD 3.2)."""

    RECRUITED_CLOCK = "2026-09-15T08:30:00Z"

    def _market_and_cell(self, panel: PanelHarness, code: str, rank: int):
        """One market with a single cell of target 2 and a 1000-cent base incentive."""
        market = panel.create_market(
            name=f"Metro {code}",
            market_code=code,
            dma_rank=rank,
            incentive_budget_cents=500000,
        )
        cell = panel.create_quota_cell(
            market["id"],
            age_band="P18_34",
            income_band="MID",
            geo_zone="URBAN",
            target_households=2,
            base_incentive_cents=1000,
        )
        return market, cell

    def test_recruitment_stamps_recruited_at_from_the_logical_clock(
        self, panel: PanelHarness
    ):
        """`recruited_at` reads the logical clock, not wall-clock time.

        PRD 3.2: "A recruited household begins at `status` `RECRUITED` with
        `recruited_at` stamped from the logical clock - this, and not
        `created_at`, is what the tenure multiplier and the first-enumeration
        deadline later measure from. `enumeration_verdict` starts at `PENDING`".

        Design: Corner/entities/household_creation_stamps_recruited_at_and_defaults
        """
        market, cell = self._market_and_cell(panel, "DMA-607", 107)
        panel.set_clock(self.RECRUITED_CLOCK)

        household = validate_success(
            panel.client.create_household(
                panel.ops,
                market_id=market["id"],
                quota_cell_id=cell["id"],
                recruitment_source="ONLINE_PANEL_TRANSFER",
                persons_count=3,
            ),
            201,
        )

        assert household["status"] == "RECRUITED"
        assert household["enumeration_verdict"] == "PENDING"
        _assert_instant(household["recruited_at"], self.RECRUITED_CLOCK, "recruited_at")

    def test_recruitment_defaults_leave_the_cell_out_of_tab(self, panel: PanelHarness):
        """Every computed household field starts at its declared floor and no cell moves.

        PRD 3.2: "`enumeration_count` at 0, `compliance_rate_rolling_30` at
        0.0000, `incentive_accrued_cents` at 0 with an empty `accrual_periods`
        array, and `roster_persons_count`, `tv_sets_count`,
        `last_enumeration_at` and `retired_reason` all null. Recruitment alone
        does not put a household in tab: the cell's `intab_count` does not move."

        Design: Corner/entities/household_creation_stamps_recruited_at_and_defaults
        """
        market, cell = self._market_and_cell(panel, "DMA-607", 107)
        panel.set_clock(self.RECRUITED_CLOCK)

        household = validate_success(
            panel.client.create_household(
                panel.ops,
                market_id=market["id"],
                quota_cell_id=cell["id"],
                recruitment_source="ONLINE_PANEL_TRANSFER",
                persons_count=3,
            ),
            201,
        )

        assert household["compliance_rate_rolling_30"] == 0.0
        assert household["incentive_accrued_cents"] == 0
        assert household["accrual_periods"] == []
        assert household["enumeration_count"] == 0
        assert household["roster_persons_count"] is None
        assert household["tv_sets_count"] is None
        assert household["last_enumeration_at"] is None
        assert household["retired_reason"] is None

        assert panel.read_quota_cell(cell["id"])["intab_count"] == 0

    def test_supplied_system_fields_are_discarded(self, panel: PanelHarness):
        """id, version, status, recruited_at and the ledger are all server-owned.

        PRD 2.5: "`id` - a server-minted UUID." and "`version` - an integer that
        starts at 1 on creation and increments by exactly 1 on every mutation of
        the row."

        Design: Corner/entities/household_system_fields_supplied_input_ignored
        """
        market, cell = self._market_and_cell(panel, "DMA-608", 108)

        household = validate_success(
            panel.client.create_household(
                panel.ops,
                market_id=market["id"],
                quota_cell_id=cell["id"],
                recruitment_source="ADDRESS_SAMPLE",
                persons_count=2,
                id="hh-supplied-by-client",
                status="ACTIVE",
                recruited_at="2020-01-01T00:00:00Z",
                incentive_accrued_cents=9999,
                version=77,
            ),
            201,
        )

        assert household["id"] != "hh-supplied-by-client"
        assert is_valid_uuid(household["id"])
        # PRD 3.2: "A recruited household begins at `status` `RECRUITED` with
        # `recruited_at` stamped from the logical clock".
        assert household["status"] == "RECRUITED"
        _assert_instant(household["recruited_at"], CLOCK_T0, "recruited_at")
        assert household["incentive_accrued_cents"] == 0
        assert household["version"] == 1
        # PRD 2.5: `created_at` is "taken from the logical clock" and `updated_at`
        # is "refreshed on every mutation of the row", so both read the startup
        # clock on a row that has not been mutated since.
        assert_freshly_created(household)
        _assert_instant(household["created_at"], CLOCK_T0, "created_at")
        _assert_instant(household["updated_at"], CLOCK_T0, "updated_at")


class TestHouseholdListing:
    """The households collection: status and verdict filters (PRD 2.3, 3.2)."""

    SECOND_CLOCK = "2026-08-01T01:00:00Z"

    def _diverging_pair(self, panel: PanelHarness):
        """Two homes of one cell: A enumerated COMPLIANT, B enumerated NONCOMPLIANT."""
        market = panel.create_market(
            name="Metro Iota",
            market_code="DMA-609",
            dma_rank=109,
            incentive_budget_cents=500000,
        )
        cell = panel.create_quota_cell(
            market["id"],
            age_band="P18_34",
            income_band="MID",
            geo_zone="URBAN",
            target_households=4,
            base_incentive_cents=1000,
        )
        first = panel.recruit_household(
            market["id"], cell["id"], recruitment_source="ADDRESS_SAMPLE", persons_count=2
        )
        panel.installed_meter(first["id"], meter_type="TV_TUNER", serial_no="MT-002001")
        panel.enumerate_household(first["id"], roster_persons_count=2, tv_sets_count=1)

        # The clock moves before the second recruitment so that `created_at`
        # ascending is an observable order rather than a tie.
        panel.set_clock(self.SECOND_CLOCK)

        second = panel.recruit_household(
            market["id"], cell["id"], recruitment_source="RDD_PHONE", persons_count=2
        )
        panel.installed_meter(second["id"], meter_type="TV_TUNER", serial_no="MT-002002")
        panel.enumerate_household(second["id"], roster_persons_count=5, tv_sets_count=1)
        return market, cell, first, second

    def test_status_filter_isolates_the_active_household(self, panel: PanelHarness):
        """Only the COMPLIANT home reached ACTIVE, so the status filter returns one row.

        PRD 3.2: "`ENUM_PENDING` with a `COMPLIANT` verdict moves the household
        to `ACTIVE`."

        Design: Corner/entities/household_listing_filters_by_status_and_verdict
        """
        _, cell, first, _ = self._diverging_pair(panel)

        rows, meta = validate_paginated(
            panel.client.list_households(
                panel.statistician, quota_cell_id=cell["id"], status="ACTIVE"
            )
        )

        assert meta["total_count"] == 1
        assert ids_of(rows) == [first["id"]]
        assert rows[0]["status"] == "ACTIVE"

    def test_verdict_filter_isolates_the_noncompliant_household(self, panel: PanelHarness):
        """The failing roster produced NONCOMPLIANT and a hold, and the filter finds it.

        PRD 3.2: "`ENUM_PENDING` with a `NONCOMPLIANT` verdict moves the
        household to `NONCOMPLIANT_HOLD` and changes no in-tab count, because
        the household was never in tab."

        Design: Corner/entities/household_listing_filters_by_status_and_verdict
        """
        market, _, _, second = self._diverging_pair(panel)

        rows, meta = validate_paginated(
            panel.client.list_households(
                panel.statistician,
                market_id=market["id"],
                enumeration_verdict="NONCOMPLIANT",
            )
        )

        assert meta["total_count"] == 1
        assert ids_of(rows) == [second["id"]]
        assert rows[0]["status"] == "NONCOMPLIANT_HOLD"
        assert rows[0]["enumeration_verdict"] == "NONCOMPLIANT"

    def test_unfiltered_listing_orders_by_created_at_and_counts_one_in_tab(
        self, panel: PanelHarness
    ):
        """Both homes list oldest first, and only the ACTIVE one is in tab.

        PRD 2.3: "Unless a collection states otherwise below, list results are
        ordered by `created_at` ascending."

        Design: Corner/entities/household_listing_filters_by_status_and_verdict
        """
        market, cell, first, second = self._diverging_pair(panel)

        rows, meta = validate_paginated(
            panel.client.list_households(panel.statistician, market_id=market["id"])
        )

        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert_ordered_by(rows, [("created_at", "asc")])
        assert ids_of(rows) == [first["id"], second["id"]]

        # PRD 3.1: "`intab_count` is recounted as the number of households of
        # that cell whose `status` is exactly `ACTIVE`".
        graded = panel.read_quota_cell(cell["id"])
        assert graded["intab_count"] == 1
        assert graded["fill_rate"] == expected_fill_rate(1, 4)
        assert graded["fill_rate"] == 0.25


class TestMeterEntity:
    """Meter shipment defaults and the parent household advance (PRD 3.3)."""

    def _recruited_household(self, panel: PanelHarness):
        """Market DMA-610 with one cell and one household still at RECRUITED."""
        market = panel.create_market(
            name="Metro Kappa",
            market_code="DMA-610",
            dma_rank=110,
            incentive_budget_cents=500000,
        )
        cell = panel.create_quota_cell(
            market["id"],
            age_band="P18_34",
            income_band="MID",
            geo_zone="URBAN",
            target_households=2,
            base_incentive_cents=1000,
        )
        household = panel.recruit_household(
            market["id"], cell["id"], recruitment_source="ADDRESS_SAMPLE", persons_count=2
        )
        return market, cell, household

    def test_shipped_meter_defaults_and_the_first_shipment_schedules_the_install(
        self, panel: PanelHarness
    ):
        """A shipped device starts SHIPPED and HEALTHY, and moves its home forward.

        PRD 3.3: "A shipped meter starts at `install_status` `SHIPPED`,
        `health_status` `HEALTHY`, `fault_count` 0, `missing_minutes_last_scan` 0
        and `installed_at` null. Shipping is also the *only* thing that schedules
        an installation: when the household was `RECRUITED`, creating its first
        meter row moves the household to `INSTALL_SCHEDULED`."

        Design: Corner/entities/meter_creation_defaults_and_parent_household_advance
        """
        _, _, household = self._recruited_household(panel)

        meter = validate_success(
            panel.client.create_meter(
                panel.tech,
                household_id=household["id"],
                meter_type="TV_TUNER",
                serial_no="MT-002003",
            ),
            201,
        )

        assert meter["install_status"] == "SHIPPED"
        assert meter["health_status"] == "HEALTHY"
        assert meter["fault_count"] == 0
        assert meter["missing_minutes_last_scan"] == 0
        assert meter["installed_at"] is None
        # PRD 3.3: a repair "clears `last_fault_code` back to null", which is the
        # value a device that has never reported a fault carries.
        assert meter["last_fault_code"] is None

        parent = validate_success(
            panel.client.get_household(panel.tech, household["id"]), 200
        )
        assert parent["status"] == "INSTALL_SCHEDULED"

    def test_second_meter_of_another_type_does_not_re_advance_the_household(
        self, panel: PanelHarness
    ):
        """A second shipment of a different type is accepted and the status holds.

        PRD 3.3: "A second or third meter shipped to a household that has
        already moved on leaves the household `status` untouched."

        Design: Corner/entities/meter_creation_defaults_and_parent_household_advance
        """
        _, _, household = self._recruited_household(panel)
        panel.ship_meter(household["id"], meter_type="TV_TUNER", serial_no="MT-002003")

        second = validate_success(
            panel.client.create_meter(
                panel.tech,
                household_id=household["id"],
                meter_type="STREAMING_ROUTER",
                serial_no="MT-002004",
            ),
            201,
        )
        assert second["install_status"] == "SHIPPED"

        parent = validate_success(
            panel.client.get_household(panel.tech, household["id"]), 200
        )
        assert parent["status"] == "INSTALL_SCHEDULED"

        rows, meta = validate_paginated(
            panel.client.list_meters(panel.tech, household_id=household["id"])
        )
        assert meta["total_count"] == 2
        assert [row["install_status"] for row in rows] == ["SHIPPED", "SHIPPED"]


class TestTuningIntervalEntity:
    """Interval ingest defaults and the rolling compliance refresh (PRD 3.6)."""

    START_ISO = "2026-07-31T18:00:00Z"
    END_ISO = "2026-07-31T23:50:00Z"
    TUNING_MINUTES = 350

    def _active_metered_household(self, panel: PanelHarness):
        """Market DMA-611, one cell, one ACTIVE household with an INSTALLED tuner."""
        market = panel.create_market(
            name="Metro Lambda",
            market_code="DMA-611",
            dma_rank=111,
            incentive_budget_cents=500000,
        )
        cell = panel.create_quota_cell(
            market["id"],
            age_band="P18_34",
            income_band="MID",
            geo_zone="URBAN",
            target_households=2,
            base_incentive_cents=1000,
        )
        household = panel.recruit_household(
            market["id"], cell["id"], recruitment_source="ADDRESS_SAMPLE", persons_count=2
        )
        meter = panel.installed_meter(
            household["id"], meter_type="TV_TUNER", serial_no="MT-002005"
        )
        panel.enumerate_household(household["id"], roster_persons_count=2, tv_sets_count=1)
        return household, meter

    def test_ingested_interval_starts_raw_and_names_the_meters_household(
        self, panel: PanelHarness
    ):
        """A freshly ingested block is RAW with nothing credited yet.

        PRD 3.6: "An ingested record starts at `state` `RAW` with
        `usable_minutes` 0, `ascribed` false, and `processing_run_id` and
        `invalidation_reason` both null."

        Design: Corner/entities/tuning_interval_creation_derives_household_and_starts_raw
        """
        household, meter = self._active_metered_household(panel)

        interval = validate_success(
            panel.client.create_tuning_interval(
                panel.statistician,
                **tuning_interval_payload(
                    meter["id"],
                    household["id"],
                    self.START_ISO,
                    self.END_ISO,
                    self.TUNING_MINUTES,
                    source_methodology="INHOME_TUNER",
                    station_code="WXYZ",
                ),
            ),
            201,
        )

        assert interval["state"] == "RAW"
        assert interval["usable_minutes"] == 0
        assert interval["ascribed"] is False
        assert interval["processing_run_id"] is None
        assert interval["invalidation_reason"] is None
        # PRD 3.6: "the submitted `household_id` must equal the meter's own
        # `household_id`", so the stored row names the metered home.
        assert interval["household_id"] == household["id"]
        assert interval["household_id"] == meter["household_id"]
        assert interval["meter_id"] == meter["id"]

    def test_ingest_refreshes_the_rolling_compliance_rate(self, panel: PanelHarness):
        """One reported day of 350 minutes scores 1/1, stored at ingest time.

        PRD 3.6: "The rate is the compliant days divided by the evaluated days,
        rounded half up to 4 decimal places ... The figure is stored, not derived
        at read time: it is recomputed on interval ingest and on a
        fault-detection scan".

        Design: Corner/entities/tuning_interval_creation_derives_household_and_starts_raw
        """
        household, meter = self._active_metered_household(panel)

        interval = validate_success(
            panel.client.create_tuning_interval(
                panel.statistician,
                **tuning_interval_payload(
                    meter["id"],
                    household["id"],
                    self.START_ISO,
                    self.END_ISO,
                    self.TUNING_MINUTES,
                    source_methodology="INHOME_TUNER",
                    station_code="WXYZ",
                ),
            ),
            201,
        )

        refreshed = validate_success(
            panel.client.get_household(panel.statistician, household["id"]), 200
        )
        assert refreshed["compliance_rate_rolling_30"] == 1.0

        rows, meta = validate_paginated(
            panel.client.list_tuning_intervals(
                panel.statistician, meter_id=meter["id"], state="RAW"
            )
        )
        assert meta["total_count"] == 1
        assert ids_of(rows) == [interval["id"]]


class TestUniverseEstimateEntity:
    """Drafted vintage totals and the parent market version bump (PRD 3.5)."""

    def _market_with_two_cells(self, panel: PanelHarness):
        """Market DMA-612 with exactly two cells, so `cell_populations` names both."""
        market = panel.create_market(
            name="Metro Mu",
            market_code="DMA-612",
            dma_rank=112,
            incentive_budget_cents=500000,
        )
        first = panel.create_quota_cell(
            market["id"],
            age_band="P18_34",
            income_band="LOW",
            geo_zone="URBAN",
            target_households=1,
            base_incentive_cents=1000,
        )
        second = panel.create_quota_cell(
            market["id"],
            age_band="P35_54",
            income_band="MID",
            geo_zone="RURAL",
            target_households=1,
            base_incentive_cents=1000,
        )
        return market, first, second

    def _draft(self, panel: PanelHarness, market, first, second, version: int):
        """Draft the 2026Q3 vintage over both cells at the given market version."""
        return validate_success(
            panel.client.create_universe_estimate(
                panel.statistician,
                **universe_estimate_payload(
                    market["id"],
                    version,
                    [
                        cell_population(first["id"], 100000, 250000),
                        cell_population(second["id"], 30000, 70000),
                    ],
                    vintage_label="2026Q3",
                    effective_from=VINTAGE_FROM,
                    effective_to=VINTAGE_TO,
                ),
            ),
            201,
        )

    def test_totals_are_summed_from_the_cell_populations(self, panel: PanelHarness):
        """The two totals are sums over the array, and the vintage starts DRAFT.

        PRD 3.5: "The draft is created with `status` `DRAFT`, `published_at` and
        `superseded_at` null, and `total_population_households` and
        `total_population_persons` summed from the array entries."

        Design: Corner/entities/universe_estimate_totals_are_summed_not_supplied
        """
        market, first, second = self._market_with_two_cells(panel)
        version = panel.market_version(market["id"])

        universe = self._draft(panel, market, first, second, version)

        assert universe["total_population_households"] == 100000 + 30000
        assert universe["total_population_households"] == 130000
        assert universe["total_population_persons"] == 250000 + 70000
        assert universe["total_population_persons"] == 320000
        assert universe["status"] == "DRAFT"
        assert universe["published_at"] is None
        assert universe["superseded_at"] is None

    def test_drafting_advances_the_parent_market_version(self, panel: PanelHarness):
        """The draft is what bumps the market, making concurrent drafts exclusive.

        PRD 3.5: "Drafting also advances the parent market's `version` by one,
        which is what makes two concurrent draft attempts against the same
        market mutually exclusive."

        Design: Corner/entities/universe_estimate_totals_are_summed_not_supplied
        """
        market, first, second = self._market_with_two_cells(panel)
        before = panel.market_version(market["id"])

        self._draft(panel, market, first, second, before)

        after = validate_success(
            panel.client.get_market(panel.statistician, market["id"]), 200
        )
        assert after["version"] == before + 1


class TestProcessingRunEntity:
    """Opening a run: the derived window and the empty counters (PRD 3.6)."""

    WINDOW_START_ISO = "2026-08-10T00:00:00Z"
    WINDOW_END_ISO = "2026-08-11T12:00:00Z"
    RUN_CLOCK = "2026-08-12T00:00:00Z"
    OPENER_USER_ID = "stat-opener-c13"

    def _open_run(self, panel: PanelHarness):
        """Market DMA-613 with a published vintage and rule set, run opened at 2026-08-12."""
        market = panel.create_market(
            name="Metro Nu",
            market_code="DMA-613",
            dma_rank=113,
            incentive_budget_cents=500000,
        )
        cell = panel.create_quota_cell(
            market["id"],
            age_band="P18_34",
            income_band="MID",
            geo_zone="URBAN",
            target_households=1,
            base_incentive_cents=2000,
        )
        rule_set = panel.published_rule_set(
            label="RS-C01",
            missing_interval_ascription_minutes=60,
            invalid_tuning_max_minutes=900,
            outlier_household_minutes_cap=1200,
            outlier_weight_ratio_cap=2.5,
            fault_missing_minutes_threshold=1440,
        )
        universe = panel.published_universe(
            market["id"],
            [cell["id"]],
            vintage_label="2026Q3",
            cell_populations=[cell_population(cell["id"], 100000, 250000)],
        )
        panel.set_clock(self.RUN_CLOCK)

        opener = make_statistician_headers(self.OPENER_USER_ID)
        return validate_success(
            panel.client.create_processing_run(
                opener,
                **processing_run_payload(
                    market["id"],
                    universe["id"],
                    rule_set["id"],
                    panel.market_version(market["id"]),
                    window_start_iso=self.WINDOW_START_ISO,
                    window_end_iso=self.WINDOW_END_ISO,
                ),
            ),
            201,
        )

    def test_window_minutes_is_derived_from_the_two_bounds(self, panel: PanelHarness):
        """A 36-hour window is 2160 minutes and the opener is recorded from the header.

        PRD 3.6: "An opened run starts at `state` `OPEN` with `opened_by_user_id`
        recording the caller, `window_minutes` computed as the elapsed time from
        `window_start_iso` to `window_end_iso` divided by 60 seconds".

        Design: Corner/entities/processing_run_creation_computes_window_minutes
        """
        run = self._open_run(panel)

        assert run["window_minutes"] == 36 * 60
        assert run["window_minutes"] == 2160
        assert run["state"] == "OPEN"
        assert run["opened_by_user_id"] == self.OPENER_USER_ID
        assert run["weight_variant"] is None
        assert run["published_by_user_id"] is None

    def test_opened_run_counters_and_outputs_start_empty(self, panel: PanelHarness):
        """Every count starts at 0 and every output field starts null or empty.

        PRD 3.6: "`contributing_household_count`, `ascribed_interval_count`,
        `invalidated_interval_count`, `outlier_household_count`,
        `excluded_cell_count` and `total_weight_mass` all start at 0;
        `weight_variant`, `projected_average_audience`, `published_at`,
        `published_by_user_id`, `repin_required_reason` and `superseded_by_run_id`
        all start null; and `limitation_disclosures` starts empty."

        Design: Corner/entities/processing_run_creation_computes_window_minutes
        """
        run = self._open_run(panel)

        # PRD 3.6: `intab_snapshot_count` is "frozen at the number of `ACTIVE`
        # households of the market at the moment of opening" - there are none.
        assert run["intab_snapshot_count"] == 0
        assert run["contributing_household_count"] == 0
        assert run["ascribed_interval_count"] == 0
        assert run["invalidated_interval_count"] == 0
        assert run["outlier_household_count"] == 0
        assert run["excluded_cell_count"] == 0
        assert run["total_weight_mass"] == 0
        assert run["projected_average_audience"] is None
        assert run["published_at"] is None
        assert run["repin_required_reason"] is None
        assert run["superseded_by_run_id"] is None
        assert run["limitation_disclosures"] == []


class TestClientEntity:
    """Client registration and the fixed tier table (PRD 3.8)."""

    def _client_with_supplied_commercials(self, panel: PanelHarness, market_id: str):
        """Register a STANDARD client whose body also tries to set the tier fields."""
        return validate_success(
            panel.client.create_client(
                panel.rep,
                name="Northstar Media",
                tier="STANDARD",
                contract_market_ids=[market_id],
                tier_base_fee_cents=1,
                delivery_sla_hours=999,
                custom_analysis_quota=500,
            ),
            201,
        )

    def test_standard_tier_table_overrides_the_supplied_commercials(
        self, panel: PanelHarness
    ):
        """The tier table wins: 65000 / 72 / 3, and 1 / 999 / 500 are discarded.

        PRD 3.8: "The tier is the only commercial input; the three derived
        commercial fields come from a fixed tier table and any values supplied
        for them in the body are ignored" and "`STANDARD` sets
        `tier_base_fee_cents` to 65000, `delivery_sla_hours` to 72 and
        `custom_analysis_quota` to 3."

        Design: Corner/entities/client_tier_derived_fields_supplied_input_ignored
        """
        market = panel.create_market(
            name="Metro Xi",
            market_code="DMA-614",
            dma_rank=114,
            incentive_budget_cents=500000,
        )

        subscriber = self._client_with_supplied_commercials(panel, market["id"])

        assert subscriber["tier"] == "STANDARD"
        assert subscriber["tier_base_fee_cents"] == STANDARD_BASE_FEE_CENTS
        assert subscriber["tier_base_fee_cents"] == 65000
        assert subscriber["delivery_sla_hours"] == STANDARD_SLA_HOURS
        assert subscriber["delivery_sla_hours"] == 72
        assert subscriber["custom_analysis_quota"] == 3

    def test_new_client_starts_active_with_zero_counters(self, panel: PanelHarness):
        """A registered subscriber starts ACTIVE with an empty commercial ledger.

        PRD 3.8: "A new client is `ACTIVE` with `custom_analysis_used`,
        `held_deliverable_count` and `delivery_sla_credit_cents` all 0 and
        `suspended_reason` null."

        Design: Corner/entities/client_tier_derived_fields_supplied_input_ignored
        """
        market = panel.create_market(
            name="Metro Xi",
            market_code="DMA-614",
            dma_rank=114,
            incentive_budget_cents=500000,
        )

        subscriber = self._client_with_supplied_commercials(panel, market["id"])

        assert subscriber["status"] == "ACTIVE"
        assert subscriber["custom_analysis_used"] == 0
        assert subscriber["held_deliverable_count"] == 0
        assert subscriber["delivery_sla_credit_cents"] == 0
        assert subscriber["suspended_reason"] is None
        assert subscriber["contract_market_ids"] == [market["id"]]


class TestMethodologyChangeEntity:
    """Drafting a change and the self-referential supersession link (PRD 3.9)."""

    FIRST_DRAFTER = "gov-drafter-a"
    SECOND_DRAFTER = "gov-drafter-b"

    def _two_changes(self, panel: PanelHarness):
        """A published target rule set, two proposals, and two chained changes."""
        market = panel.create_market(
            name="Metro Omicron",
            market_code="DMA-615",
            dma_rank=115,
            incentive_budget_cents=500000,
        )
        target = panel.published_rule_set(
            label="RS-C02",
            missing_interval_ascription_minutes=60,
            invalid_tuning_max_minutes=900,
            outlier_household_minutes_cap=1200,
            outlier_weight_ratio_cap=2.5,
            fault_missing_minutes_threshold=1440,
        )
        first_proposal = panel.draft_rule_set(
            label="RS-C03",
            missing_interval_ascription_minutes=72,
            invalid_tuning_max_minutes=960,
            outlier_household_minutes_cap=1200,
            outlier_weight_ratio_cap=2.6,
            fault_missing_minutes_threshold=1440,
        )
        second_proposal = panel.draft_rule_set(
            label="RS-C04",
            missing_interval_ascription_minutes=75,
            invalid_tuning_max_minutes=970,
            outlier_household_minutes_cap=1200,
            outlier_weight_ratio_cap=2.7,
            fault_missing_minutes_threshold=1440,
        )
        first_change = validate_success(
            panel.client.create_methodology_change(
                make_director_headers(self.FIRST_DRAFTER),
                title="Widen ascription window",
                target_edit_rule_set_id=target["id"],
                proposed_edit_rule_set_id=first_proposal["id"],
                affected_market_ids=[market["id"]],
            ),
            201,
        )
        second_change = validate_success(
            panel.client.create_methodology_change(
                make_director_headers(self.SECOND_DRAFTER),
                title="Widen ascription window, second attempt",
                target_edit_rule_set_id=target["id"],
                proposed_edit_rule_set_id=second_proposal["id"],
                affected_market_ids=[market["id"]],
                supersedes_change_id=first_change["id"],
            ),
            201,
        )
        return first_change, second_change

    def test_draft_starts_with_zero_impact_and_the_drafter_stamped(
        self, panel: PanelHarness
    ):
        """A drafted change carries no analysis yet and records its author.

        PRD 3.9: "The change starts in `DRAFT` with `created_by_user_id` stamped
        from `X-User-ID`, `impact_delta_pct` at 0.0000, `impact_tier` null and
        `revision_count` 0."

        Design: Corner/entities/methodology_change_creation_defaults_and_self_reference
        """
        _, second_change = self._two_changes(panel)

        assert second_change["state"] == "DRAFT"
        assert second_change["impact_delta_pct"] == 0.0
        assert second_change["impact_tier"] is None
        assert second_change["revision_count"] == 0
        assert second_change["created_by_user_id"] == self.SECOND_DRAFTER
        # PRD 3.9 names these six fields as the ones a revision "cleared", so null
        # and 0 are their pre-analysis, pre-notification values.
        assert second_change["notification_lead_hours"] is None
        assert second_change["notification_deadline_at"] is None
        assert second_change["baseline_processing_run_id"] is None
        assert second_change["baseline_projected_average_audience"] is None
        assert second_change["notified_client_count"] == 0
        assert second_change["acknowledged_client_count"] == 0
        assert second_change["activated_at"] is None

    def test_supersedes_link_resolves_and_leaves_the_named_change_alone(
        self, panel: PanelHarness
    ):
        """The chain is stored on the new row and the older row keeps its own state.

        PRD 3.9: "A supplied `supersedes_change_id` must name a change standing
        in `DRAFT`, `IMPACT_ASSESSED` or `NOTIFIED`".

        Design: Corner/entities/methodology_change_creation_defaults_and_self_reference
        """
        first_change, second_change = self._two_changes(panel)

        assert second_change["supersedes_change_id"] == first_change["id"]

        # PRD 3.9: "A change named by another change's `supersedes_change_id`
        # keeps its own `state` throughout: activation never rewrites history."
        older = validate_success(
            panel.client.get_methodology_change(panel.director, first_change["id"]), 200
        )
        assert older["state"] == "DRAFT"

        rows, meta = validate_paginated(
            panel.client.list_methodology_changes(
                panel.director, supersedes_change_id=first_change["id"]
            )
        )
        assert meta["total_count"] == 1
        assert ids_of(rows) == [second_change["id"]]


class TestAccreditationAuditEntity:
    """Opening an audit and the freeze it puts on the market (PRD 3.9, 3.1)."""

    OPENER_USER_ID = "auditor-opener-16"

    def _market_under_audit(self, panel: PanelHarness):
        """Market DMA-616 with one UNDER_TARGET cell and an audit just opened."""
        market = panel.create_market(
            name="Metro Pi",
            market_code="DMA-616",
            dma_rank=116,
            incentive_budget_cents=500000,
        )
        cell = panel.create_quota_cell(
            market["id"],
            age_band="P18_34",
            income_band="MID",
            geo_zone="URBAN",
            target_households=2,
            base_incentive_cents=1000,
        )
        rule_set = panel.published_rule_set(
            label="RS-C05",
            missing_interval_ascription_minutes=60,
            invalid_tuning_max_minutes=900,
            outlier_household_minutes_cap=1200,
            outlier_weight_ratio_cap=2.5,
            fault_missing_minutes_threshold=1440,
        )
        audit = validate_success(
            panel.client.create_accreditation_audit(
                make_auditor_headers(self.OPENER_USER_ID),
                market_id=market["id"],
                scope_edit_rule_set_id=rule_set["id"],
                auditor_note="Annual methodology review of DMA-616",
            ),
            201,
        )
        return market, cell, audit

    def test_opened_audit_records_its_opener_and_nothing_else(self, panel: PanelHarness):
        """A new audit is OPEN with no outcome and no finalization yet.

        PRD 3.9: "The audit starts in `OPEN` with `opened_by_user_id` stamped
        from `X-User-ID`, `outcome`, `finalized_by_user_id` and `finalized_at`
        null, and `limitation_disclosures` empty."

        Design: Corner/entities/accreditation_audit_creation_freezes_the_market
        """
        _, _, audit = self._market_under_audit(panel)

        assert audit["state"] == "OPEN"
        assert audit["outcome"] is None
        assert audit["limitation_disclosures"] == []
        assert audit["opened_by_user_id"] == self.OPENER_USER_ID
        assert audit["finalized_by_user_id"] is None
        assert audit["finalized_at"] is None

    def test_opening_an_audit_freezes_the_market_over_the_cell_verdict(
        self, panel: PanelHarness
    ):
        """Clause 1 outranks the UNDER_TARGET cell that would otherwise mean OPEN.

        PRD 3.9: "Opening it raises the market's `open_audit_count` by one, which
        fires the first clause of the posture calculation and drives
        `recruitment_posture` to `FROZEN` with `posture_changed_at` updated -
        overriding every cell-level consideration."

        Design: Corner/entities/accreditation_audit_creation_freezes_the_market
        """
        market, _, _ = self._market_under_audit(panel)

        frozen = validate_success(
            panel.client.get_market(panel.auditor, market["id"]), 200
        )

        assert frozen["open_audit_count"] == 1
        assert frozen["recruitment_posture"] == "FROZEN"
        _assert_instant(frozen["posture_changed_at"], CLOCK_T0, "posture_changed_at")
        # PRD 3.1 clause 3 still counts the cell: only the posture flipped.
        assert frozen["under_target_cell_count"] == 1
        assert frozen["quota_cell_count"] == 1
