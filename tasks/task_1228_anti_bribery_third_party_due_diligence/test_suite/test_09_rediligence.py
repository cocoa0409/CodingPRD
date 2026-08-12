"""Re-diligence cycles: tier-interval scheduling, sweep/grace, outcomes."""
import pytest

from test_helpers import (
    ApiErrorId,
    admin_headers,
    advance_to_dd_review,
    create_active_policy,
    create_country,
    create_draft_third_party,
    get_third_party,
    officer_headers,
    set_clock,
    setup_third_party_in_state,
    validate_error,
    validate_success,
    walk_to_approved,
)


class TestAutoCycleScheduling:
    def test_rediligence_auto_cycle_due_date_by_tier(self, api, officer_headers):
        """PRD §3.5: "Approval stamps `approval_tier_snapshot` with the current
        `risk_tier` and `approved_policy_id` with the active policy's id — from
        then on, contract clause requirements key off this snapshot rather than
        the live tier — sets `diligence_expires_at` to the current date plus the
        tier's re-diligence interval (365 days for `LOW` or `MEDIUM`, 180 days
        for `HIGH`, 90 days for `CRITICAL`), auto-creates the first re-diligence
        cycle with `trigger_source` `SCHEDULED`, status `SCHEDULED`, and
        `due_date` equal to `diligence_expires_at`, and increments the party's
        `version` by one."

        Design: Corner/calculations/rediligence_auto_cycle_due_date_by_tier
        """
        set_clock("2026-05-01T00:00:00Z")
        create_country("CH", 80)
        create_country("CU", 36)
        create_active_policy()

        # LOW: CH/TECHNOLOGY/NONE -> 16; HIGH: CU/CONSULTING/DIRECT -> 70.
        tp_low = create_draft_third_party("CH", "TECHNOLOGY", "NONE", legal_name="TP Low")
        advance_to_dd_review(tp_low["id"])
        walk_to_approved(tp_low["id"])

        tp_high = create_draft_third_party("CU", "CONSULTING", "DIRECT", legal_name="TP High")
        advance_to_dd_review(tp_high["id"])
        walk_to_approved(tp_high["id"])

        low_cycles = validate_success(
            api.list_rediligence_cycles(tp_low["id"], officer_headers), 200)
        assert len(low_cycles) == 1, "exactly one auto cycle is created at approval"
        assert low_cycles[0]["cycle_status"] == "SCHEDULED"
        assert low_cycles[0]["trigger_source"] == "SCHEDULED"
        assert str(low_cycles[0]["due_date"]).startswith("2027-05-01"), (
            "LOW interval is 365 days from 2026-05-01"
        )

        high_cycles = validate_success(
            api.list_rediligence_cycles(tp_high["id"], officer_headers), 200)
        assert len(high_cycles) == 1
        assert str(high_cycles[0]["due_date"]).startswith("2026-10-28"), (
            "HIGH interval is 180 days from 2026-05-01"
        )


class TestOverdueSweepAndGrace:
    def test_rediligence_overdue_sweep_and_auto_suspend_grace(self, api, officer_headers,
                                                              admin_headers):
        """PRD §3.9: "The clock sweep moves a `SCHEDULED` or `IN_PROGRESS` cycle
        to `OVERDUE` once the current date passes its `due_date`, and while any
        cycle is `OVERDUE` two consequences follow: contract activation for the
        party is refused (`ERR_REDILIGENCE_OVERDUE`), and once the current date
        is more than 30 days past the `due_date` the sweep suspends the party
        automatically — `APPROVED` to `SUSPENDED`."
        PRD §2.5: "All of these comparisons are strictly-greater comparisons on
        whole ISO dates: a certification lapses only when the current date is
        later than its `valid_until`, a contract expires only when the current
        date is later than its `end_date`, a training assignment or re-diligence
        cycle becomes overdue only when the current date is later than its
        `due_date`, and the due date itself is not yet overdue."

        Design: Corner/calculations/rediligence_overdue_sweep_and_auto_suspend_grace
        """
        # LOW third party approved 2026-05-01: auto cycle due 2027-05-01.
        ctx = setup_third_party_in_state("APPROVED", "CH", 80)
        tp_id = ctx["third_party"]["id"]

        # due+1: cycle OVERDUE.
        set_clock("2027-05-02T00:00:00Z")
        cycles = validate_success(api.list_rediligence_cycles(tp_id, officer_headers), 200)
        assert cycles[0]["cycle_status"] == "OVERDUE"

        # due+30 (2027-05-31): NOT strictly greater — the grace period holds.
        set_clock("2027-05-31T00:00:00Z")
        assert get_third_party(tp_id)["onboarding_status"] == "APPROVED"

        # due+31 (2027-06-01): more than 30 days past due — auto-suspend fires.
        set_clock("2027-06-01T00:00:00Z")
        assert get_third_party(tp_id)["onboarding_status"] == "SUSPENDED"


class TestCompletionOutcomes:
    def test_rediligence_downgrade_steps_tier_and_successor(self, api, officer_headers):
        """PRD §3.9: "`DOWNGRADE` escalates the party's `risk_tier` one step —
        `LOW` to `MEDIUM`, `MEDIUM` to `HIGH`, `HIGH` to `CRITICAL`, with
        `CRITICAL` staying put — resets `diligence_expires_at` to the current
        date plus the interval of the new tier, and schedules the successor cycle
        just 30 days out."
        PRD §3.5: "Approval stamps `approval_tier_snapshot` with the current
        `risk_tier` and `approved_policy_id` with the active policy's id — from
        then on, contract clause requirements key off this snapshot rather than
        the live tier"

        Design: Corner/calculations/rediligence_downgrade_steps_tier_and_successor
        """
        # NG cpi 25 -> norm 75; TECHNOLOGY/NONE -> round_half_up(43.5) = 44 -> MEDIUM.
        ctx = setup_third_party_in_state("APPROVED", "NG", 25, "TECHNOLOGY", "NONE")
        tp_id = ctx["third_party"]["id"]

        cycles = validate_success(api.list_rediligence_cycles(tp_id, officer_headers), 200)
        cycle_id = cycles[0]["id"]
        validate_success(api.start_rediligence_cycle(cycle_id, officer_headers), 200)

        completed = validate_success(
            api.complete_rediligence_cycle(cycle_id, {"outcome": "DOWNGRADE"},
                                           officer_headers), 200)
        assert completed["cycle_status"] == "COMPLETED"
        assert completed["outcome"] == "DOWNGRADE"

        tp = get_third_party(tp_id)
        assert tp["risk_tier"] == "HIGH", "MEDIUM escalates exactly one step to HIGH"
        assert tp["approval_tier_snapshot"] == "MEDIUM", "the snapshot is not rewritten"
        assert str(tp["diligence_expires_at"]).startswith("2026-10-28"), (
            "current 2026-05-01 + 180-day HIGH interval"
        )

        cycles_after = validate_success(
            api.list_rediligence_cycles(tp_id, officer_headers), 200)
        assert len(cycles_after) == 2
        successor = cycles_after[1]
        assert successor["cycle_status"] == "SCHEDULED"
        assert str(successor["due_date"]).startswith("2026-05-31"), (
            "the DOWNGRADE successor is scheduled just 30 days out"
        )

    def test_manual_rediligence_cycle_while_open_rejected(self, api, officer_headers):
        """PRD §3.9: "An officer may also open a manual cycle — `trigger_source`
        `MANUAL`, `due_date` set to the current date plus 30 days — but only when
        no other cycle of the party is `SCHEDULED`, `IN_PROGRESS`, or `OVERDUE`;
        otherwise the create fails with `ERR_DUPLICATE_ACTIVE_CYCLE`."
        PRD §3.9: "`REAFFIRM` extends `diligence_expires_at` to the current date
        plus the interval of the party's current tier and auto-creates the
        successor cycle in `SCHEDULED` at that date."

        Design: Corner/validations/manual_rediligence_cycle_while_open_rejected
        """
        ctx = setup_third_party_in_state("APPROVED", "CH", 80)
        tp_id = ctx["third_party"]["id"]

        # The approval-created SCHEDULED cycle occupies the single open slot.
        first = api.create_rediligence_cycle(tp_id, officer_headers)
        validate_error(first, ApiErrorId.ERR_DUPLICATE_ACTIVE_CYCLE)

        cycles = validate_success(api.list_rediligence_cycles(tp_id, officer_headers), 200)
        cycle_id = cycles[0]["id"]
        validate_success(api.start_rediligence_cycle(cycle_id, officer_headers), 200)
        completed = validate_success(
            api.complete_rediligence_cycle(cycle_id, {"outcome": "REAFFIRM"},
                                           officer_headers), 200)
        assert completed["cycle_status"] == "COMPLETED"

        # The REAFFIRM successor is itself SCHEDULED, so the rule still blocks.
        second = api.create_rediligence_cycle(tp_id, officer_headers)
        validate_error(second, ApiErrorId.ERR_DUPLICATE_ACTIVE_CYCLE)

        cycles_after = validate_success(
            api.list_rediligence_cycles(tp_id, officer_headers), 200)
        successor = cycles_after[1]
        assert successor["cycle_status"] == "SCHEDULED"
        assert successor["trigger_source"] == "SCHEDULED"
        assert str(successor["due_date"]).startswith("2027-05-01"), (
            "reaffirmed expiry = current 2026-05-01 + 365-day LOW interval"
        )
