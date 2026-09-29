"""Computed reads and projections: assurance summary, filtered unit inventory,
permit renewal filing and clock-driven recomputation.

Every precondition is built through the documented endpoints against an empty
database whose logical clock reads 2026-08-01T00:00:00Z.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    TEST_USERS,
    assert_assurance,
    assert_cents,
    assert_mass,
    assert_mass_ledger_balances,
    assert_unit_state,
    fixtures,
)
from test_helpers.factories import (
    manifest_line_payload,
    permit_renewal_payload,
    receipt_line,
    receive_payload,
)


class TestFinancialAssuranceSummary:
    def test_summary_prices_the_whole_requirement_from_held_mass(self, api):
        """One 200 kg drum in storage raises the closure price and the summary shows every step.

        A dedicated computed read — the facility's financial assurance summary — returns the facility projection with `closure_base_cost_cents`, `assurance_tier`, `closure_cost_estimate_cents`, `corrective_action_reserve_cents`, `active_treatment_liability_cents`, `required_assurance_cents`, `posted_assurance_cents` and `assurance_shortfall_cents` all recomputed at the current clock instant.
        `closure_base_cost_cents` is 25,000,000 cents of fixed closure overhead plus 1,800 cents for every kilogram of `held_mass_kg`, that per-kilogram product being rounded half up to whole cents before it is added to the fixed component.
        `assurance_tier` is `TIER_1` when `closure_base_cost_cents` is below 30,000,000 cents, `TIER_2` when it is below 60,000,000 cents but not below 30,000,000, and `TIER_3` otherwise.
        The rate is 5 percent for `TIER_1`, 10 percent for `TIER_2` and 18 percent for `TIER_3`.
        `required_assurance_cents` is the sum of `closure_cost_estimate_cents`, the facility's input `post_closure_cost_cents`, `corrective_action_reserve_cents`, and `active_treatment_liability_cents` — the last being the sum of `estimated_treatment_liability_cents` across the facility's batches that are `PLANNED` or `IN_TREATMENT`.
        `posted_assurance_cents` is the sum of `face_amount_cents` over the facility's instruments whose `status` is `ACTIVE`, and `assurance_shortfall_cents` is the amount by which the required total exceeds the posted total, or zero when the posted total is at least the required total.
        `mass_ledger_kg` is the sum of those five destinations, and it must equal `received_mass_kg` after every operation, with no rounding drift.

        Design: Corner/endpoints/financial_assurance_summary_recomputes_the_whole_requirement
        """
        scenario = fixtures.setup_container_in_storage(net_weight_kg=200.0)

        summary = validate_success(
            api.get_financial_assurance_summary(
                scenario.facility["id"], TEST_USERS["inspector"]
            )
        )

        # 25,000,000 + 200 kg x 1,800, still under the TIER_1 ceiling, so the
        # 5 percent surcharge applies and the 8,000,000 post-closure estimate is added.
        assert_assurance(
            summary,
            base_cents=25_360_000,
            tier="TIER_1",
            estimate_cents=26_628_000,
            reserve_cents=0,
            liability_cents=0,
            required_cents=34_628_000,
            posted_cents=90_000_000,
            shortfall_cents=0,
        )

        facility = fixtures.read_facility(scenario.facility["id"])
        assert_mass(facility["held_mass_kg"], 200.0, "held_mass_kg")
        assert_mass(facility["unallocated_receipt_kg"], 800.0, "unallocated_receipt_kg")
        assert_mass(facility["received_mass_kg"], 1000.0, "received_mass_kg")
        assert_mass(facility["mass_ledger_kg"], 1000.0, "mass_ledger_kg")
        assert_mass_ledger_balances(facility)

        # The plain facility read and the summary are computed at the same instant.
        assert_assurance(
            facility,
            base_cents=summary["closure_base_cost_cents"],
            tier=summary["assurance_tier"],
            estimate_cents=summary["closure_cost_estimate_cents"],
            required_cents=summary["required_assurance_cents"],
            posted_cents=summary["posted_assurance_cents"],
            shortfall_cents=summary["assurance_shortfall_cents"],
        )


class TestUnitInventoryListing:
    def test_unit_inventory_can_be_narrowed_to_a_single_custody_state(self, api):
        """A voided drum stays listable in the unit while leaving the unit's stored mass.

        Containers may be filtered by `manifest_line_id`, `waste_profile_id`, `storage_unit_id`, `treatment_batch_id`, `custody_state` and `compliance_state`; the containers of a single storage unit may be filtered by `custody_state` and `compliance_state`.
        Voiding from either source has identical effects: the container's mass leaves its unit's `stored_kg` and leaves its line's `allocated_container_mass_kg`, so the mass returns to the facility's `unallocated_receipt_kg` and `mass_ledger_kg` does not move, while the facility's `closure_cost_estimate_cents` and `required_assurance_cents` are recomputed downward.
        `container_count` is the number of containers in the unit whose custody is `FILLING`, `SEALED` or `STAGED`.
        `stored_kg` is the sum of `net_weight_kg` over those same containers, to 3 decimals.
        List responses include `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the current page.

        Design: Corner/endpoints/unit_container_listing_filters_by_custody_state
        """
        scenario = fixtures.setup_container_in_storage(net_weight_kg=200.0)
        standing = scenario.container
        scrapped = fixtures.place_container(
            scenario.line["id"], scenario.unit["id"], net_weight_kg=150.0
        )
        fixtures.void_container(scrapped["id"], reason_code="DAMAGED_ON_ARRIVAL")

        voided_rows, voided_meta = validate_paginated(
            api.list_unit_containers(
                scenario.unit["id"],
                TEST_USERS["compliance_manager"],
                params={"custody_state": "VOIDED"},
            )
        )
        assert voided_meta["total_count"] == 1
        assert voided_meta["has_more"] is False
        assert [row["id"] for row in voided_rows] == [scrapped["id"]]
        assert voided_rows[0]["custody_state"] == "VOIDED"

        filling_rows, filling_meta = validate_paginated(
            api.list_unit_containers(
                scenario.unit["id"],
                TEST_USERS["compliance_manager"],
                params={"custody_state": "FILLING"},
            )
        )
        assert filling_meta["total_count"] == 1
        assert [row["id"] for row in filling_rows] == [standing["id"]]

        # Unfiltered, the unit still lists both drums it has ever held.
        all_rows, all_meta = validate_paginated(
            api.list_unit_containers(scenario.unit["id"], TEST_USERS["compliance_manager"])
        )
        assert all_meta["total_count"] == 2
        assert {row["id"] for row in all_rows} == {standing["id"], scrapped["id"]}

        # Only the standing drum counts towards the unit's occupancy and mass.
        assert_unit_state(
            fixtures.read_unit(scenario.unit["id"]), container_count=1, stored_kg=200.0
        )

        line = fixtures.read_line(scenario.manifest["id"], 1)
        assert_mass(line["allocated_container_mass_kg"], 200.0, "allocated_container_mass_kg")

        facility = fixtures.read_facility(scenario.facility["id"])
        assert_mass(facility["held_mass_kg"], 200.0, "held_mass_kg")
        assert_mass(facility["unallocated_receipt_kg"], 800.0, "unallocated_receipt_kg")
        assert_mass(facility["mass_ledger_kg"], 1000.0, "mass_ledger_kg")
        assert_mass_ledger_balances(facility)


class TestPermitRenewalFiling:
    def test_filing_early_keeps_the_dock_open(self, api):
        """A facility that files for renewal keeps receiving and pricing shipments.

        Filing moves the facility from `ACTIVE` to `RENEWAL_PENDING`, or from `EXPIRED` to `RENEWAL_PENDING`, and stamps `renewal_requested_at` with the current clock instant while storing the requested expiry.
        A facility in `RENEWAL_PENDING` continues to accept waste and to run treatment exactly as an `ACTIVE` one does — that is the point of filing early.
        For each included line, taken in `line_number` ascending order, a per-kilogram rate is formed from the line's waste profile: a base rate of 40 cents per kilogram for `BULK_LIQUID`, 55 for `SLUDGE`, 30 for `SOLID` and 120 for `LAB_PACK`, multiplied by a hazard multiplier of 1.10 for `ACID`, 1.10 for `ALKALINE`, 1.35 for `OXIDIZER`, 1.50 for `CYANIDE_BEARING`, 1.45 for `WATER_REACTIVE` and 1.20 for `ORGANIC_SOLVENT`, and then increased by a flat land-disposal-restriction surcharge of 12 cents per kilogram whenever the profile's `ldr_subcategory` is anything other than `NONE`.
        The line's charge is the priced quantity multiplied by that rate, rounded half up to whole cents, plus a container handling fee of 750 cents for each container in the line's `received_container_count`.
        The **provisional** variant runs at receipt, includes every line whose `line_status` is `RECEIVED`, and prices each line's `received_quantity_kg`.
        When `discrepancy_type` computes to `NONE`, the manifest moves from `EN_ROUTE` to `VERIFIED`.

        Design: Corner/endpoints/permit_renewal_request_moves_permit_to_renewal_pending_and_receipt_continues
        """
        fixtures.set_clock()
        facility, _instrument = fixtures.create_funded_facility(
            permitted_methods=["INCINERATION"]
        )
        generator = fixtures.create_generator()
        profile = fixtures.create_approved_profile(generator["id"], facility["id"])
        manifest = fixtures.create_manifest(
            generator["id"],
            facility["id"],
            lines=[manifest_line_payload(profile["id"], 1000.0, 4, False)],
        )

        renewed = validate_success(
            api.request_permit_renewal(
                facility["id"],
                permit_renewal_payload("2029-06-30T00:00:00Z"),
                TEST_USERS["compliance_manager"],
            )
        )
        assert renewed["permit_status"] == "RENEWAL_PENDING"
        assert renewed["renewal_requested_at"].startswith("2026-08-01T00:00:00")
        assert renewed["requested_permit_expires_at"].startswith("2029-06-30T00:00:00")
        # The standing permit expiry is untouched until the renewal is decided.
        assert renewed["permit_expires_at"].startswith("2027-06-30T00:00:00")

        received = validate_success(
            api.receive_manifest(
                manifest["id"],
                receive_payload([receipt_line(1, 1000.0, 4)]),
                TEST_USERS["clerk"],
            )
        )
        assert received["status"] == "VERIFIED"
        # A SOLID organic-solvent stream at 30 x 1.20 cents per kilogram over
        # 1,000 kg, plus 750 cents of handling for each of the four drums.
        assert_cents(received["provisional_charge_cents"], 39_000, "provisional_charge_cents")

        facility_after = fixtures.read_facility(facility["id"])
        assert facility_after["permit_status"] == "RENEWAL_PENDING"
        assert_mass(facility_after["received_mass_kg"], 1000.0, "received_mass_kg")
        assert_mass(facility_after["unallocated_receipt_kg"], 1000.0, "unallocated_receipt_kg")


class TestClockDrivenRecomputation:
    def test_moving_the_clock_ages_the_inventory_without_touching_the_rows(self, api):
        """Eight days pass and both the drum's age and the unit's inspection status move on their own.

        The call mutates no stored row; it merely changes the instant against which derived values are computed on the next read.
        `accumulation_days` is the number of whole 86,400-second days that have elapsed from `accumulation_start_date` to the current clock instant, taking the floor, and it is recomputed on every read.
        `ten_day_overdue` is true when the container sits in a unit whose `unit_type` is `TEN_DAY_TRANSFER` and its `accumulation_days` is strictly greater than 10.
        `inspection_overdue` is true when the current clock instant is **strictly** later than `last_inspection_at` advanced by `inspection_frequency_days` days.
        A new unit opens with `status` of `ACTIVE`, `closure_plan_ref` null, `last_inspection_at` initialised to the unit's own `created_at`, and `posture` of `OPEN`.
        One thing deliberately does **not** enter posture: `inspection_overdue`.

        Design: Corner/endpoints/clock_endpoint_recomputes_time_derived_fields_without_mutating_rows
        """
        scenario = fixtures.setup_container_in_storage(
            net_weight_kg=200.0,
            container_overrides={"accumulation_start_date": "2026-07-25T00:00:00Z"},
        )

        before_container = fixtures.read_container(scenario.container["id"])
        assert before_container["accumulation_days"] == 7
        before_unit = fixtures.read_unit(scenario.unit["id"])
        assert_unit_state(before_unit, inspection_overdue=False, posture="OPEN", status="ACTIVE")
        assert before_unit["last_inspection_at"].startswith("2026-08-01T00:00:00")

        fixtures.set_clock("2026-08-09T00:00:00Z")

        after_container = fixtures.read_container(scenario.container["id"])
        assert after_container["accumulation_days"] == 15
        # A container area is not a ten-day transfer facility, so age alone is no breach.
        assert after_container["ten_day_overdue"] is False
        assert_mass(after_container["net_weight_kg"], 200.0, "net_weight_kg")
        assert after_container["custody_state"] == "FILLING"
        assert after_container["version"] == before_container["version"]

        after_unit = fixtures.read_unit(scenario.unit["id"])
        # Seven-day inspection frequency from 1 August, so 9 August is past due,
        # yet an overdue inspection never closes the unit to placement.
        assert_unit_state(
            after_unit,
            inspection_overdue=True,
            posture="OPEN",
            status="ACTIVE",
            container_count=1,
            stored_kg=200.0,
        )
        assert after_unit["last_inspection_at"] == before_unit["last_inspection_at"]
        assert after_unit["version"] == before_unit["version"]
