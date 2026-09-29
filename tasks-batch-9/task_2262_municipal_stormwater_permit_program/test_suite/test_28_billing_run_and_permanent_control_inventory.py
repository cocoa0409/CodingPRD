"""Two endpoints that are more than reads: the billing run that writes back to
every account, and the permanent control whose eligibility follows the clock."""

import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_fee_chain
from test_helpers.test_users import (
    CLERK_HEADERS,
    INSPECTOR_HEADERS,
    MANAGER_HEADERS,
    make_property_owner_headers,
)


class TestAFinalBillingRunReconcilesWithEveryAccount:
    """One residential parcel at its gross, one commercial parcel with a credit."""

    @pytest.fixture
    def billed_term(self):
        """A 3000 sqft residential account and a 9020 sqft commercial one at 0.2500."""
        program = fx.setup_active_program(funding_target_cents=25000)
        term_id = program["term_id"]
        first = fx.create_account(
            term_id,
            parcel_id="P-0900",
            parcel_class="RESIDENTIAL_SINGLE",
            impervious_area_sqft=3000.0,
            owner_name="Ada Owner",
        )
        second = fx.create_account(
            term_id,
            parcel_id="P-1000",
            parcel_class="COMMERCIAL",
            impervious_area_sqft=9020.0,
            owner_name="Ben Owner",
        )
        fx.setup_approved_credit(second, requested_credit_pct=0.2500)
        return {"term_id": term_id, "first": first, "second": second}

    def test_01_the_uncredited_parcel_is_billed_at_its_gross(self, billed_term):
        """One equivalent residential unit in the first tier and no surcharge.

        PRD: "`eru_units` is `impervious_area_sqft` divided by the term's `eru_sqft`,
        rounded to 2 decimal places." And: "The first tier bills 9633 cents per unit, the
        second 8207 cents per unit and the third 6541 cents per unit." And:
        "`class_surcharge_cents` is then the already-rounded `gross_fee_cents` multiplied
        by the surcharge rate of the parcel's `parcel_class` — 0.00 for
        `RESIDENTIAL_SINGLE`, 0.05 for `RESIDENTIAL_MULTI`, 0.12 for `COMMERCIAL` and 0.08
        for `INSTITUTIONAL` — rounded to whole cents." And: "`gross_billable_cents` is
        `gross_fee_cents` plus `class_surcharge_cents`."

        Design: Corner/endpoints/a_final_billing_run_writes_back_to_every_account_and_rolls_up_to_the_term
        """
        account = fx.read_account(billed_term["first"]["id"])

        assert_fee_chain(
            account,
            eru_units=1.00,
            gross_fee_cents=9633,
            class_surcharge_cents=0,
            gross_billable_cents=9633,
            total_credit_pct=0.0000,
            current_net_fee_cents=9633,
        )

    def test_02_the_credited_parcel_straddles_two_tiers(self, billed_term):
        """3.01 units, a twelve per cent surcharge and a quarter credited.

        PRD: "Those units are then split across three tiers: the first 1.00 unit falls in
        the first tier, units above 1.00 and up to 4.00 fall in the second, and units above
        4.00 fall in the third." And: "Each tier's component is computed and **rounded to
        whole cents on its own**, and only then are the three components added together to
        give `gross_fee_cents`; summing the three unrounded components and rounding once at
        the end is wrong and diverges by a cent on parcels straddling a tier boundary."
        And: "The credit in cents is `gross_billable_cents` multiplied by that capped
        percentage, rounded to whole cents, and the net fee is `gross_billable_cents` minus
        that credit."

        Design: Corner/endpoints/a_final_billing_run_writes_back_to_every_account_and_rolls_up_to_the_term
        """
        account = fx.read_account(billed_term["second"]["id"])

        assert_fee_chain(
            account,
            eru_units=3.01,
            gross_fee_cents=26129,
            class_surcharge_cents=3135,
            gross_billable_cents=29264,
            total_credit_pct=0.2500,
            current_net_fee_cents=21948,
        )

    def test_03_the_run_answers_with_the_reconciled_aggregate(self, billed_term):
        """Two accounts, 38897 gross, 7316 credited and 31581 net.

        PRD: "The run recomputes the tiered fee for every account of the term, applies the
        credit reckoning of the requested variant, and writes `last_billed_run_type`,
        `last_billed_credit_pct`, `last_billed_net_cents` and `last_billed_at` on every
        account it bills. It answers with `run_type`, `period_start`, `period_end`,
        `billed_account_count`, `total_gross_billable_cents`, `total_credit_cents` and
        `total_net_billed_cents`."

        Design: Corner/endpoints/a_final_billing_run_writes_back_to_every_account_and_rolls_up_to_the_term
        """
        run = validate_success(
            api_client.create_billing_run(
                billed_term["term_id"],
                factories.billing_run_payload("FINAL", "2026-01-01", "2026-12-31"),
                CLERK_HEADERS,
            ),
            200,
        )

        assert run["run_type"] == "FINAL", "the requested variant is echoed"
        assert run["period_start"] == "2026-01-01", "as is the billed period start"
        assert run["period_end"] == "2026-12-31", "and its end"
        assert run["billed_account_count"] == 2, (
            f"both accounts of the term were billed, got {run['billed_account_count']}"
        )
        assert run["total_gross_billable_cents"] == 38897, (
            "9633 plus 29264 is 38897, got "
            f"{run['total_gross_billable_cents']}"
        )
        assert run["total_credit_cents"] == 7316, (
            f"a quarter of 29264 is 7316, got {run['total_credit_cents']}"
        )
        assert run["total_net_billed_cents"] == 31581, (
            f"38897 less 7316 is 31581, got {run['total_net_billed_cents']}"
        )

    def test_04_the_run_writes_back_onto_each_account(self, billed_term):
        """Each account remembers the variant, the credit and the instant.

        PRD: "The run recomputes the tiered fee for every account of the term, applies the
        credit reckoning of the requested variant, and writes `last_billed_run_type`,
        `last_billed_credit_pct`, `last_billed_net_cents` and `last_billed_at` on every
        account it bills." And: "In the `FINAL` reckoning — the one behind the account's own
        stored `total_credit_pct` and `current_net_fee_cents` — an application contributes
        its `approved_credit_pct` when its `status` is `APPROVED`, and nothing otherwise."

        Design: Corner/endpoints/a_final_billing_run_writes_back_to_every_account_and_rolls_up_to_the_term
        """
        fx.run_billing(billed_term["term_id"], "FINAL", "2026-01-01", "2026-12-31")

        credited = fx.read_account(billed_term["second"]["id"])
        assert credited["last_billed_run_type"] == "FINAL", (
            f"the variant was recorded, got {credited['last_billed_run_type']}"
        )
        assert credited["last_billed_credit_pct"] == pytest.approx(
            0.2500, abs=0.00005
        ), (
            "the approved quarter was the one applied, got "
            f"{credited['last_billed_credit_pct']}"
        )
        assert credited["last_billed_net_cents"] == 21948, (
            f"29264 less 7316 is 21948, got {credited['last_billed_net_cents']}"
        )
        assert credited["last_billed_at"] == "2026-08-01T00:00:00Z", (
            f"stamped from the logical clock, got {credited['last_billed_at']}"
        )

        plain = fx.read_account(billed_term["first"]["id"])
        assert plain["last_billed_net_cents"] == 9633, (
            "the account with no application is billed at its gross, got "
            f"{plain['last_billed_net_cents']}"
        )
        assert plain["last_billed_credit_pct"] == pytest.approx(0.0000, abs=0.00005), (
            f"with nothing credited, got {plain['last_billed_credit_pct']}"
        )

    def test_05_the_run_rolls_the_revenue_up_to_the_term(self, billed_term):
        """31581 cents against a 25000 target reads ADEQUATE.

        PRD: "It also recomputes the term's `projected_annual_revenue_cents` from the
        `FINAL` net fees and refreshes `funding_adequacy_status`, which reads `ADEQUATE`
        when `projected_annual_revenue_cents` is greater than or equal to
        `funding_target_cents` and `UNDERFUNDED` otherwise."

        Design: Corner/endpoints/a_final_billing_run_writes_back_to_every_account_and_rolls_up_to_the_term
        """
        fx.run_billing(billed_term["term_id"], "FINAL", "2026-01-01", "2026-12-31")

        term = fx.read_term(billed_term["term_id"])
        assert term["projected_annual_revenue_cents"] == 31581, (
            "the sum of the two net fees, got "
            f"{term['projected_annual_revenue_cents']}"
        )
        assert term["funding_adequacy_status"] == "ADEQUATE", (
            f"31581 clears the 25000 target, got {term['funding_adequacy_status']}"
        )


class TestPermanentControlEligibilityFollowsTheClock:
    """Ownership sets the track; the clock alone can withdraw the eligibility."""

    @pytest.fixture
    def inventory(self, active_program):
        """SITE-B of 2.50 disturbed acres with one private and one municipal control."""
        site = fx.create_site(
            active_program["term_id"],
            site_name="SITE-B",
            operator_name="Southline Build",
            disturbed_acres=2.50,
        )
        private = fx.create_facility(
            site["id"],
            "PRIVATE",
            facility_type="BIORETENTION",
            design_capacity_cf=4200.00,
            service_area_acres=1.75,
        )
        municipal = validate_success(
            api_client.create_post_construction_facility(
                factories.facility_payload(
                    site["id"],
                    "MUNICIPAL",
                    facility_type="WET_POND",
                    design_capacity_cf=9000.00,
                    service_area_acres=3.00,
                ),
                MANAGER_HEADERS,
            ),
            201,
        )
        account = fx.create_account(active_program["term_id"], parcel_id="P-0900")
        return {
            "site": site,
            "private": private,
            "municipal": municipal,
            "account": account,
        }

    def test_06_a_private_control_starts_pending_and_ineligible(self, inventory):
        """The private track begins with an agreement still to record.

        PRD: "Ownership decides the agreement track immediately: a `MUNICIPAL` facility is
        created with `agreement_status` `NOT_REQUIRED`, while a `PRIVATE` facility is
        created with `agreement_status` `PENDING` because a privately owned control must
        carry a recorded maintenance agreement. In both cases `credit_eligible` starts
        false, `inspection_interval_months`, `agreement_reference`,
        `agreement_recorded_at` and `last_inspection_finalized_at` start null, and
        `months_since_last_inspection` starts at 0." And: "On creation the server derives
        `post_construction_control_required`, setting it true exactly when
        `disturbed_acres` is 2.00 or more"

        Design: Corner/endpoints/the_permanent_control_inventory_derives_eligibility_and_overdue_from_the_clock
        """
        facility = inventory["private"]

        assert facility["agreement_status"] == "PENDING", (
            f"a private control owes an agreement, got {facility['agreement_status']}"
        )
        assert facility["credit_eligible"] is False, "so it earns no credit yet"
        assert facility["inspection_interval_months"] is None, "no interval is agreed"
        assert facility["agreement_recorded_at"] is None, "and nothing is recorded"
        assert facility["months_since_last_inspection"] == 0, "the counter starts at 0"

        site = fx.read_site(inventory["site"]["id"])
        assert site["post_construction_control_required"] is True, (
            "2.50 disturbed acres is over the two-acre line"
        )

    def test_07_a_municipal_control_needs_no_agreement_and_earns_no_credit(
        self, inventory
    ):
        """NOT_REQUIRED is not the same as satisfied for credit purposes.

        PRD: "Ownership decides the agreement track immediately: a `MUNICIPAL` facility is
        created with `agreement_status` `NOT_REQUIRED`, while a `PRIVATE` facility is
        created with `agreement_status` `PENDING` because a privately owned control must
        carry a recorded maintenance agreement." And: "`credit_eligible` is true exactly
        when `ownership` is `PRIVATE`, `agreement_status` is `RECORDED`, and
        `inspection_overdue` is false — the three conditions the utility credit programme
        leans on in §3.8."

        Design: Corner/endpoints/the_permanent_control_inventory_derives_eligibility_and_overdue_from_the_clock
        """
        facility = inventory["municipal"]

        assert facility["agreement_status"] == "NOT_REQUIRED", (
            f"the city maintains its own, got {facility['agreement_status']}"
        )
        assert facility["credit_eligible"] is False, (
            "eligibility also demands private ownership"
        )

    def test_08_recording_the_agreement_turns_the_control_eligible(self, inventory):
        """A twelve-month interval recorded at the clock leaves it current.

        PRD: "The call writes `RECORDED` into `agreement_status`, copies `recorded_at`
        into `agreement_recorded_at`, stores the interval, and recomputes the three
        currency fields described below." And: "`months_since_last_inspection` is the
        number of whole months from `last_inspection_finalized_at` — or from
        `agreement_recorded_at` when the facility has never been inspected — forward to the
        logical clock, discarding any fractional month." And: "`inspection_overdue` is true
        exactly when `agreement_status` is `RECORDED` and `months_since_last_inspection` is
        strictly greater than `inspection_interval_months`." And: "`credit_eligible` is true
        exactly when `ownership` is `PRIVATE`, `agreement_status` is `RECORDED`, and
        `inspection_overdue` is false — the three conditions the utility credit programme
        leans on in §3.8."

        Design: Corner/endpoints/the_permanent_control_inventory_derives_eligibility_and_overdue_from_the_clock
        """
        recorded = validate_success(
            api_client.record_agreement(
                inventory["private"]["id"],
                factories.record_agreement_payload(
                    "2026-08-01T00:00:00Z",
                    12,
                    agreement_reference="INST-2026-77",
                ),
                INSPECTOR_HEADERS,
            ),
            200,
        )

        assert recorded["agreement_status"] == "RECORDED", (
            f"the instrument is on file, got {recorded['agreement_status']}"
        )
        assert recorded["agreement_reference"] == "INST-2026-77", "under its reference"
        assert recorded["agreement_recorded_at"] == "2026-08-01T00:00:00Z", (
            f"at the recorded instant, got {recorded['agreement_recorded_at']}"
        )
        assert recorded["inspection_interval_months"] == 12, "with a yearly interval"
        assert recorded["months_since_last_inspection"] == 0, "no month has passed"
        assert recorded["inspection_overdue"] is False, "so nothing is overdue"
        assert recorded["credit_eligible"] is True, "and the three conditions hold"

    def test_09_the_nested_listing_is_scoped_to_the_site_and_open_to_owners(
        self, inventory
    ):
        """An ownership filter over one site's inventory, read by an owner.

        PRD: "Permanent controls under one site filter on `ownership` and
        `agreement_status`." And: "Exclusively resubmits its own returned credit
        application, may file an application jointly with the clerk, and may read its own
        account, its credit applications and the permanent-control inventory."

        Design: Corner/endpoints/the_permanent_control_inventory_derives_eligibility_and_overdue_from_the_clock
        """
        owner_headers = make_property_owner_headers(inventory["account"]["id"])

        rows, meta = validate_paginated(
            api_client.list_site_post_construction_facilities(
                inventory["site"]["id"], owner_headers, {"ownership": "PRIVATE"}
            )
        )

        assert meta["total_count"] == 1, (
            f"one of the two controls is private, got {meta['total_count']}"
        )
        assert rows[0]["id"] == inventory["private"]["id"], "and it is the private one"
        assert rows[0]["ownership"] == "PRIVATE", "as the filter demanded"

    def test_10_a_month_of_the_clock_does_not_yet_make_it_overdue(self, inventory):
        """One whole month of twelve leaves the control current.

        PRD: "`months_since_last_inspection` is the number of whole months from
        `last_inspection_finalized_at` — or from `agreement_recorded_at` when the facility
        has never been inspected — forward to the logical clock, discarding any fractional
        month." And: "`inspection_overdue` is true exactly when `agreement_status` is
        `RECORDED` and `months_since_last_inspection` is strictly greater than
        `inspection_interval_months`."

        Design: Corner/endpoints/the_permanent_control_inventory_derives_eligibility_and_overdue_from_the_clock
        """
        validate_success(
            api_client.record_agreement(
                inventory["private"]["id"],
                factories.record_agreement_payload(
                    "2026-08-01T00:00:00Z", 12, agreement_reference="INST-2026-77"
                ),
                INSPECTOR_HEADERS,
            ),
            200,
        )
        fx.set_clock("2026-09-01T00:00:00Z")

        facility = fx.read_facility(inventory["private"]["id"])
        assert facility["months_since_last_inspection"] == 1, (
            f"one whole month has passed, got {facility['months_since_last_inspection']}"
        )
        assert facility["inspection_overdue"] is False, "one is not more than twelve"
        assert facility["credit_eligible"] is True, "so the credit still holds"

    def test_11_thirteen_months_withdraws_the_eligibility_without_a_write(
        self, inventory
    ):
        """The clock alone flips both derived flags, and no version is spent.

        PRD: "`inspection_overdue` is true exactly when `agreement_status` is `RECORDED`
        and `months_since_last_inspection` is strictly greater than
        `inspection_interval_months`." And: "`credit_eligible` is true exactly when
        `ownership` is `PRIVATE`, `agreement_status` is `RECORDED`, and
        `inspection_overdue` is false — the three conditions the utility credit programme
        leans on in §3.8." And: "Inspection currency is derived, never asserted."

        Design: Corner/endpoints/the_permanent_control_inventory_derives_eligibility_and_overdue_from_the_clock
        """
        recorded = validate_success(
            api_client.record_agreement(
                inventory["private"]["id"],
                factories.record_agreement_payload(
                    "2026-08-01T00:00:00Z", 12, agreement_reference="INST-2026-77"
                ),
                INSPECTOR_HEADERS,
            ),
            200,
        )
        fx.set_clock("2027-09-01T00:00:00Z")

        facility = fx.read_facility(inventory["private"]["id"])
        assert facility["months_since_last_inspection"] == 13, (
            "thirteen whole months by the floor, got "
            f"{facility['months_since_last_inspection']}"
        )
        assert facility["inspection_overdue"] is True, "thirteen is more than twelve"
        assert facility["credit_eligible"] is False, (
            "and an overdue control earns no credit"
        )
        assert facility["version"] == recorded["version"], (
            "no write happened, so the version stands at "
            f"{recorded['version']}, got {facility['version']}"
        )
