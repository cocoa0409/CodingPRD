"""Abatement cascade and cure tests (PRD §3.4, §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, ADMIN, INSPECTOR,
    setup_active_scenario, setup_abated_contract, cure_abatement,
    setup_failed_inspection, setup_repair_verification,
    mark_item_repaired, request_reinspection, verify_item,
    list_hap_payments,
    make_landlord_headers,
)


class TestAbatementCascade:
    def test_deadline_breach_abates_contract(self, api):
        """PRD §3.4: "As soon as the logical clock advances past the deadline of
        any `OPEN` or `FAILED_VERIFICATION` repair item on a failed inspection,
        the contract flips from `ACTIVE` to `ABATED`, the unit flips from
        `UNDER_CONTRACT` to `SUSPENDED_ABATEMENT`, and every `HAPPayment` row
        for a period after the breach that was still `SCHEDULED` flips to
        `ABATED_HELD`."

        Design: Difficulty/transitive_cascade/abatement_cascade_contract_unit_payments
        """
        ctx = setup_abated_contract(zip_code="90007", family_code="F7")
        contract = get_success_data(api.get_contract(ctx["contract"]["id"], ADMIN))
        assert contract["status"] == "ABATED", (
            f"clock advance past the repair deadline must abate the contract, got "
            f"{contract['status']}"
        )

    def test_deadline_breach_suspends_unit_and_holds_payments(self, api):
        """PRD §3.4: "As soon as the logical clock advances past the deadline of
        any `OPEN` or `FAILED_VERIFICATION` repair item on a failed inspection,
        the contract flips from `ACTIVE` to `ABATED`, the unit flips from
        `UNDER_CONTRACT` to `SUSPENDED_ABATEMENT`, and every `HAPPayment` row
        for a period after the breach that was still `SCHEDULED` flips to
        `ABATED_HELD`."

        Design: Difficulty/transitive_cascade/abatement_cascade_contract_unit_payments
        """
        ctx = setup_abated_contract(zip_code="90007", family_code="F7b")
        unit = get_success_data(api.get_unit(ctx["unit"]["id"], ADMIN))
        assert unit["status"] == "SUSPENDED_ABATEMENT", (
            f"unit must follow the contract into abatement, got {unit['status']}"
        )
        payments = list_hap_payments(ctx["contract"]["id"])
        assert payments, "Setup: at least one payment row must exist"
        for row in payments:
            assert row["disbursement_status"] in ("ABATED_HELD", "PAID", "VOID"), (
                f"rows for periods after the breach that were SCHEDULED must be "
                f"ABATED_HELD, got {row['disbursement_status']}"
            )
        assert any(r["disbursement_status"] == "ABATED_HELD" for r in payments), (
            "at least one SCHEDULED row must have flipped to ABATED_HELD"
        )


class TestUnitStatusCompoundLoop:
    def test_abatement_moves_unit_to_suspended_abatement(self, api):
        """PRD §3.4: "As soon as the logical clock advances past the deadline of
        any `OPEN` or `FAILED_VERIFICATION` repair item on a failed inspection,
        the contract flips from `ACTIVE` to `ABATED`, the unit flips from
        `UNDER_CONTRACT` to `SUSPENDED_ABATEMENT`, and every `HAPPayment` row
        for a period after the breach that was still `SCHEDULED` flips to
        `ABATED_HELD`."

        Design: Difficulty/non_linear_state_machine/unit_status_compound_with_contract_abatement
        """
        ctx = setup_abated_contract(zip_code="90006", family_code="F6")
        unit = get_success_data(api.get_unit(ctx["unit"]["id"], ADMIN))
        assert unit["status"] == "SUSPENDED_ABATEMENT", (
            f"compound loop entry: expected SUSPENDED_ABATEMENT, got {unit['status']}"
        )

    def test_cure_returns_unit_to_under_contract(self, api):
        """PRD §3.4: "When the final non-`VERIFIED` item on the inspection is
        verified `PASS`, three things happen in one cascade: the inspection
        moves from `REPAIR_VERIFICATION` to `CLOSED`; the contract, if it was
        `ABATED`, moves back to `ACTIVE`; and the unit moves from
        `SUSPENDED_ABATEMENT` back to `UNDER_CONTRACT`."

        Design: Difficulty/non_linear_state_machine/unit_status_compound_with_contract_abatement
        """
        ctx = setup_abated_contract(zip_code="90006", family_code="F6b")
        contract = cure_abatement(ctx)
        assert contract["status"] == "ACTIVE", (
            f"cure must return the contract to ACTIVE, got {contract['status']}"
        )
        unit = get_success_data(api.get_unit(ctx["unit"]["id"], ADMIN))
        assert unit["status"] == "UNDER_CONTRACT", (
            f"compound loop exit: expected UNDER_CONTRACT, got {unit['status']}"
        )
        insp = get_success_data(api.get_inspection(ctx["inspection"]["id"], ADMIN))
        assert insp["status"] == "CLOSED"


class TestAbatementHeldPaymentsRecomputed:
    def test_cure_returns_held_rows_to_scheduled(self, api):
        """PRD §3.6: "After recompute, a row whose period has not yet disbursed
        returns to `SCHEDULED` (including the zero-amount case, which is kept
        for record-keeping); a row that was already `PAID` stays `PAID` with the
        delta recorded."

        Design: Difficulty/combinatorial_formula/abatement_proration_per_row_rounding_order
        """
        ctx = setup_abated_contract(zip_code="90004", family_code="F4")
        cure_abatement(ctx)
        payments = list_hap_payments(ctx["contract"]["id"])
        held = [r for r in payments if r["disbursement_status"] == "ABATED_HELD"]
        assert not held, (
            f"after the cure recompute no row may remain ABATED_HELD, got "
            f"{[r['disbursement_status'] for r in payments]}"
        )
        assert all(r["disbursement_status"] in ("SCHEDULED", "PAID") for r in payments)

    def test_cure_recomputes_held_rows_within_full_month_bounds(self, api):
        """PRD §3.6: "For each row, count the calendar days within that row's
        `period_month` during which the contract was in `ABATED` status — the
        abatement window is start-inclusive and end-exclusive. Divide that count
        by the total calendar days in the month to get the abated fraction,
        multiply the full-month `hap_portion_cents` by that fraction, round
        half-up to whole cents, and subtract the result from `hap_portion_cents`
        to get the new `hap_amount_cents`."

        Design: Difficulty/combinatorial_formula/abatement_proration_per_row_rounding_order
        """
        ctx = setup_abated_contract(zip_code="90004", family_code="F4c")
        contract = cure_abatement(ctx)
        payments = list_hap_payments(contract["id"])
        assert payments, "at least one payment row must exist"
        for row in payments:
            assert 0 <= row["hap_amount_cents"] <= contract["hap_portion_cents"], (
                f"recomputed hap_amount_cents {row['hap_amount_cents']} must lie "
                f"between 0 and the full-month portion {contract['hap_portion_cents']}"
            )
            assert row["disbursement_status"] in ("SCHEDULED", "PAID")
