"""The dual fee-earned variant: percent-of-construction versus hourly-with-not-to-exceed."""
import pytest

from test_helpers import (
    validate_success,
    assert_contract, assert_time_entry, assert_contract_wip_identity,
    setup_executed_project,
    activate_phase, activate_and_complete_phase, create_approved_time_entry,
    create_time_entry, submit_time_entry, approve_time_entry,
    read_contract, read_project,
)

TEN_HOUR_DAY = {"start_utc": "2026-05-04T08:00:00Z", "end_utc": "2026-05-04T18:00:00Z"}
SECOND_TEN_HOUR_DAY = {"start_utc": "2026-05-05T08:00:00Z", "end_utc": "2026-05-05T18:00:00Z"}


def _percent_project(project_number="PCT-001"):
    """PERCENT_OF_CONSTRUCTION: SD COMPLETED plus one APPROVED 10-hour entry."""
    bundle = setup_executed_project(project_number=project_number, name="Percent Tower")
    activate_and_complete_phase(bundle, "SD")
    entry = create_approved_time_entry(bundle, "SD", **TEN_HOUR_DAY)
    bundle["entry"] = entry
    return bundle


def _hourly_project(project_number="HR-001"):
    """HOURLY (not_to_exceed 2_000_000): identical SD COMPLETED plus the identical entry."""
    bundle = setup_executed_project(
        project_number=project_number, name="Hourly Loft",
        hourly_not_to_exceed_cents=2_000_000,
    )
    activate_and_complete_phase(bundle, "SD")
    entry = create_approved_time_entry(bundle, "SD", **SECOND_TEN_HOUR_DAY)
    bundle["entry"] = entry
    return bundle


class TestContractFeeEarnedVariants:

    def test_percent_of_construction_earns_from_phase_completion_and_ignores_labour(self, api):
        """PRD §3.3: "On a `PERCENT_OF_CONSTRUCTION` contract, `earned_to_date_cents` is the sum,
        across **all four** phases regardless of status, of each phase's `fee_allocation_cents`
        multiplied by its `percent_complete`, divided by 100, rounded half up. Approved labour is
        irrelevant to that number — hours on a percent contract drive only the project's cost
        tracking, never its fee."
        PRD §3.2: "It freezes `base_fee_cents`: on a `PERCENT_OF_CONSTRUCTION` contract this is the
        `construction_cost_estimate_cents` multiplied by `fee_rate_bp`, divided by 10000, rounded
        half up to whole cents; on an `HOURLY` contract it is simply the `not_to_exceed_cents`
        ceiling."

        Design: Difficulty/dual_variant_calc/contract_fee_earned_percent_vs_hourly_diverges_on_identical_data
        """
        bundle = _percent_project()

        entry = bundle["entry"]
        assert_time_entry(entry)
        assert entry["hours"] == pytest.approx(10.0, abs=0.01)
        assert entry["billable_cents"] == 120_000  # 10.0 h at 12_000 cents/h

        contract = read_contract(bundle)
        assert_contract(contract)
        assert contract["base_fee_cents"] == 10_000_000
        # SD's allocation is 2_000_000 and it is complete; the 120_000 of approved billable
        # labour contributes nothing whatsoever to the fee on this basis.
        assert contract["earned_to_date_cents"] == 2_000_000
        assert_contract_wip_identity(contract)

        # The labour still drives the project's own cost tracking.
        assert read_project(bundle)["labor_cost_cents"] == 50_000  # 10.0 h at 5_000 cents/h

    def test_hourly_earns_from_approved_labour_and_diverges_from_the_percent_branch(self, api):
        """PRD §3.3: "On an `HOURLY` contract, `earned_to_date_cents` is instead the sum of
        `billable_cents` across every time entry in status `APPROVED` whose phase belongs to this
        contract's project, capped at the contract's `not_to_exceed_cents`: whichever of the two is
        smaller wins. Phase completion is irrelevant to *that* number."
        PRD §3.3: "How much fee a contract has *earned* depends entirely on its `fee_basis`, and
        the two branches share no arithmetic."

        Design: Difficulty/dual_variant_calc/contract_fee_earned_percent_vs_hourly_diverges_on_identical_data
        """
        percent = _percent_project("PCT-002")
        hourly = _hourly_project("HR-002")

        hourly_entry = hourly["entry"]
        assert hourly_entry["hours"] == pytest.approx(10.0, abs=0.01)
        assert hourly_entry["billable_cents"] == 120_000

        hourly_contract = read_contract(hourly)
        assert_contract(hourly_contract)
        assert hourly_contract["base_fee_cents"] == 2_000_000  # the not_to_exceed ceiling
        # Only the approved billable labour counts here; SD's completion is irrelevant.
        assert hourly_contract["earned_to_date_cents"] == 120_000
        assert_contract_wip_identity(hourly_contract)

        percent_contract = read_contract(percent)
        assert percent_contract["earned_to_date_cents"] == 2_000_000

        assert percent_contract["earned_to_date_cents"] != hourly_contract["earned_to_date_cents"], (
            "identical phase state and identical approved labour must yield different earned "
            "figures under the two fee bases"
        )


class TestHourlyBranchDetails:

    def test_hourly_earned_is_clamped_at_the_not_to_exceed_ceiling(self, api):
        """PRD §3.3: "On an `HOURLY` contract, `earned_to_date_cents` is instead the sum of
        `billable_cents` across every time entry in status `APPROVED` whose phase belongs to this
        contract's project, capped at the contract's `not_to_exceed_cents`: whichever of the two is
        smaller wins. Phase completion is irrelevant to *that* number."
        PRD §2.6: "The contract's `wip_balance_cents`, in particular, is never stored as an
        independent quantity — it is always the contract's `earned_to_date_cents` minus its
        `billed_fee_to_date_cents`, recomputed at every point either operand changes."

        Design: Corner/calculations/hourly_earned_is_capped_at_not_to_exceed
        """
        bundle = setup_executed_project(
            project_number="NTE-001", name="NTE Nook",
            weights=(2500, 2500, 2500, 2500), hourly_not_to_exceed_cents=200_000,
        )
        activate_phase(bundle, "SD")

        first = create_approved_time_entry(bundle, "SD", **TEN_HOUR_DAY)
        second = create_approved_time_entry(bundle, "SD", **SECOND_TEN_HOUR_DAY)
        assert first["billable_cents"] == 120_000
        assert second["billable_cents"] == 120_000  # 240_000 of raw billable labour in total

        contract = read_contract(bundle)
        assert_contract(contract)
        assert contract["base_fee_cents"] == 200_000
        assert contract["total_fee_cents"] == 200_000
        assert contract["earned_to_date_cents"] == 200_000, "min() clamps; it does not error"
        assert contract["wip_balance_cents"] == 200_000

    def test_non_billable_labour_contributes_zero_to_the_hourly_fee(self, api):
        """PRD §3.4: "and `billable_cents` is those `hours` multiplied by the staff member's
        `billing_rate_cents_per_hour`, rounded half up — except on a non-billable entry, where
        `billable_cents` is 0 outright."
        PRD §3.4: "The project's `approved_hours` and `labor_cost_cents` are recomputed as the sums
        of `hours` and of `cost_cents` respectively across every time entry in status `APPROVED`
        whose phase belongs to that project — entries in `DRAFT`, `SUBMITTED` or `REJECTED`
        contribute nothing at all."

        Design: Corner/calculations/non_billable_time_entry_contributes_zero_to_hourly_earned
        """
        bundle = setup_executed_project(
            project_number="NBL-001", name="Non Billable Barn",
            weights=(2500, 2500, 2500, 2500), hourly_not_to_exceed_cents=200_000,
        )
        activate_phase(bundle, "SD")

        entry = create_time_entry(bundle, "SD", billable=False, **TEN_HOUR_DAY)
        submit_time_entry(entry["id"], bundle)
        approved = approve_time_entry(entry["id"], bundle)

        assert_time_entry(approved)
        assert approved["hours"] == pytest.approx(10.0, abs=0.01)
        assert approved["billable_cents"] == 0
        assert approved["cost_cents"] == 50_000  # 10.0 h at 5_000 cents/h

        project = read_project(bundle)
        assert project["approved_hours"] == pytest.approx(10.0, abs=0.01)
        assert project["labor_cost_cents"] == 50_000

        contract = read_contract(bundle)
        assert contract["earned_to_date_cents"] == 0, (
            "a non-billable entry carries billable_cents 0 and therefore earns no fee"
        )
