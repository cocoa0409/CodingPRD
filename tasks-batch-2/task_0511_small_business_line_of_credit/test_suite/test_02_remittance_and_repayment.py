"""Remittance settlement: waterfall allocation, cadence variants, FIFO ordering, NSF retry
cycle, due-timing boundary, and the delinquency cure loop.

Covers difficulty instances (dual_variant_calc, non_linear_state_machine, boundary_precision)
and corner instances (calculations, state_machines, errors).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    create_active_credit_line,
    create_active_line_with_draw,
    take_draw,
    schedule_remittance,
    settle_remittance,
    set_clock,
    setup_delinquent_line,
    get_line,
    SV1,
)


class TestRemittanceCadenceVariants:
    def test_daily_cadence_target_is_two_percent_of_outstanding(self, api):
        """A DAILY line settles 2% of the outstanding total; fee is repaid before principal.

        PRD §3.5: "where a DAILY line uses 2 percent and a WEEKLY line uses 10 percent; the
        target is rounded half up to a whole cent before being capped."
        PRD §3.5: "Within each draw, fee is repaid before principal"

        Design: Difficulty/dual_variant_calc/remittance_amount_daily_vs_weekly_cadence
        """
        set_clock("2026-05-10T00:00:00Z")
        _, _, _, line = create_active_credit_line(
            cadence="DAILY", feed_overrides={"pulled_at": "2026-05-09T00:00:00Z"}
        )
        take_draw(line["id"], 500_000)  # fee 40000
        take_draw(line["id"], 300_000)  # fee 24000 -> outstanding_total 864000
        remit = schedule_remittance(line["id"], "2026-05-12T00:00:00Z")
        set_clock("2026-05-12T00:00:00Z")
        settled = settle_remittance(remit["id"], "SUCCESS")
        assert settled["status"] == "SETTLED"
        assert settled["amount_cents"] == 17280
        assert settled["fee_applied_cents"] == 17280
        assert settled["principal_applied_cents"] == 0

    def test_weekly_cadence_target_is_ten_percent_and_repays_fee_then_principal(self, api):
        """A WEEKLY line settles 10% of outstanding, repaying fee fully then principal.

        PRD §3.5: "where a DAILY line uses 2 percent and a WEEKLY line uses 10 percent"
        PRD §3.5: "The portion applied to principal across all draws becomes
        principal_applied_cents and the portion applied to fee becomes fee_applied_cents, and
        the debited amount_cents is their sum"

        Design: Difficulty/compensating_invariant/credit_capacity_conserved_through_draw_and_remittance
        """
        set_clock("2026-05-18T00:00:00Z")
        _, _, _, line = create_active_credit_line(
            cadence="WEEKLY", feed_overrides={"pulled_at": "2026-05-17T00:00:00Z"}
        )
        take_draw(line["id"], 400_000)  # fee 32000 -> outstanding_total 432000
        remit = schedule_remittance(line["id"], "2026-05-25T00:00:00Z")
        set_clock("2026-05-25T00:00:00Z")
        settled = settle_remittance(remit["id"], "SUCCESS")
        assert settled["amount_cents"] == 43200
        assert settled["fee_applied_cents"] == 32000
        assert settled["principal_applied_cents"] == 11200
        line_after = get_line(line["id"])
        assert line_after["outstanding_principal_cents"] == 388800
        assert line_after["available_credit_cents"] == 611200

    def test_credit_capacity_invariant_holds_after_remittance(self, api):
        """available_credit_cents + outstanding_principal_cents stays equal to credit_limit_cents.

        PRD §3.3: "its available_credit_cents is the credit limit minus outstanding principal,
        floored at zero"

        Design: Difficulty/compensating_invariant/credit_capacity_conserved_through_draw_and_remittance
        """
        set_clock("2026-05-18T00:00:00Z")
        _, _, _, line = create_active_credit_line(
            cadence="WEEKLY", feed_overrides={"pulled_at": "2026-05-17T00:00:00Z"}
        )
        take_draw(line["id"], 400_000)
        remit = schedule_remittance(line["id"], "2026-05-25T00:00:00Z")
        set_clock("2026-05-25T00:00:00Z")
        settle_remittance(remit["id"], "SUCCESS")
        line_after = get_line(line["id"])
        assert (
            line_after["available_credit_cents"] + line_after["outstanding_principal_cents"]
            == line_after["credit_limit_cents"]
        )


class TestFifoAllocation:
    def test_fifo_repays_oldest_draw_first(self, api):
        """A remittance allocates oldest-drawn first; the oldest draw is REPAID before the newest
        receives any allocation.

        PRD §3.5: "The amount is then allocated across the line's OUTSTANDING draws in FIFO
        order — oldest drawn_at first, breaking ties by drawn_at and then by created_at
        ascending, never by id."

        Design: Corner/calculations/remittance_fifo_oldest_draw_first
        """
        set_clock("2026-05-10T00:00:00Z")
        _, _, _, line = create_active_credit_line(
            cadence="WEEKLY", feed_overrides={"pulled_at": "2026-05-09T00:00:00Z"}
        )
        d1 = take_draw(line["id"], 1_000)  # fee 80, oldest
        set_clock("2026-05-11T00:00:00Z")
        d2 = take_draw(line["id"], 100_000)  # fee 8000, newest
        remit = schedule_remittance(line["id"], "2026-05-18T00:00:00Z")
        set_clock("2026-05-18T00:00:00Z")
        settled = settle_remittance(remit["id"], "SUCCESS")
        assert settled["amount_cents"] == 10908
        assert settled["principal_applied_cents"] == 2828
        assert settled["fee_applied_cents"] == 8080
        draw1 = validate_success(api.get_draw(d1["id"], SV1), 200)
        draw2 = validate_success(api.get_draw(d2["id"], SV1), 200)
        assert draw1["status"] == "REPAID"
        assert draw2["status"] == "OUTSTANDING"
        assert draw2["principal_repaid_cents"] == 1828


class TestNsfRetryCycle:
    def test_nsf_settle_spawns_scheduled_retry_two_days_later(self, api):
        """An NSF settle fails the remittance and spawns a fresh SCHEDULED retry +2 days out.

        PRD §3.5: "the system spawns exactly one retry remittance — a fresh SCHEDULED
        remittance whose scheduled_for is this remittance's scheduled_for plus a 2-day retry
        gap, with its attempt_count initialized to this remittance's post-increment
        attempt_count — and sets this remittance's next_retry_remittance_id to the spawned id."

        Design: Difficulty/non_linear_state_machine/remittance_nsf_retry_cycle
        """
        set_clock("2026-05-13T00:00:00Z")
        line, _ = create_active_line_with_draw(
            200_000, cadence="DAILY", feed_overrides={"pulled_at": "2026-05-12T00:00:00Z"}
        )
        remit = schedule_remittance(line["id"], "2026-05-15T00:00:00Z")
        set_clock("2026-05-15T00:00:00Z")
        failed = settle_remittance(remit["id"], "NSF")
        assert failed["status"] == "FAILED"
        assert failed["attempt_count"] == 1
        assert failed["failure_reason"] == "NSF"
        data, meta = api_scheduled_remittances(api, line["id"])
        assert meta["total_count"] == 1, "exactly one new SCHEDULED retry exists"
        assert data[0]["scheduled_for"][:10] == "2026-05-17"
        line_after = get_line(line["id"])
        assert line_after["nsf_strike_count"] == 1


class TestDueTimingBoundary:
    def test_settle_at_exact_scheduled_instant_succeeds(self, api):
        """Settling at now == scheduled_for is allowed (>= boundary).

        PRD §3.5: "the logical clock has reached or passed its scheduled_for; settling before
        the scheduled instant is rejected with ERR_REMITTANCE_NOT_DUE."

        Design: Difficulty/boundary_precision_check/settle_at_exact_scheduled_for_instant_succeeds
        """
        set_clock("2026-05-18T00:00:00Z")
        line, _ = create_active_line_with_draw(
            500_000, cadence="DAILY", feed_overrides={"pulled_at": "2026-05-17T00:00:00Z"}
        )
        remit = schedule_remittance(line["id"], "2026-05-20T00:00:00Z")
        set_clock("2026-05-20T00:00:00Z")
        settled = settle_remittance(remit["id"], "SUCCESS")
        assert settled["status"] == "SETTLED"
        assert settled["amount_cents"] == 10800
        assert settled["fee_applied_cents"] == 10800

    def test_settle_one_second_before_due_is_rejected(self, api):
        """Settling one second before scheduled_for returns ERR_REMITTANCE_NOT_DUE.

        PRD §3.5: "the logical clock has reached or passed its scheduled_for; settling before
        the scheduled instant is rejected with ERR_REMITTANCE_NOT_DUE."

        Design: Corner/validations/settle_before_due_returns_not_due
        """
        set_clock("2026-05-18T00:00:00Z")
        line, _ = create_active_line_with_draw(
            500_000, cadence="DAILY", feed_overrides={"pulled_at": "2026-05-17T00:00:00Z"}
        )
        remit = schedule_remittance(line["id"], "2026-05-20T00:00:00Z")
        set_clock("2026-05-19T23:59:59Z")
        from test_helpers import validate_error, settle_remittance_payload
        res = api.settle_remittance(remit["id"], settle_remittance_payload("SUCCESS"), SV1)
        validate_error(res, "ERR_REMITTANCE_NOT_DUE")
        after = validate_success(api.get_remittance(remit["id"], SV1), 200)
        assert after["status"] == "SCHEDULED"


class TestDelinquencyCure:
    def test_success_settle_cures_delinquent_to_active(self, api):
        """A SUCCESS settle on a DELINQUENT line resets nsf_strike_count and cures to ACTIVE.

        PRD §3.6: "any settlement that succeeds resets nsf_strike_count to zero and, if the
        line was DELINQUENT, moves it back to ACTIVE."

        Design: Corner/state_machines/remittance_success_cures_delinquent_to_active
        """
        line, _, last = setup_delinquent_line(principal_cents=200_000)
        delinquent = get_line(line["id"])
        assert delinquent["status"] == "DELINQUENT"
        assert delinquent["nsf_strike_count"] == 3
        retry_id = last["next_retry_remittance_id"]
        assert retry_id, "a SCHEDULED retry should exist to settle"
        retry = validate_success(api.get_remittance(retry_id, SV1), 200)
        set_clock(retry["scheduled_for"])
        settled = settle_remittance(retry_id, "SUCCESS")
        assert settled["status"] == "SETTLED"
        cured = get_line(line["id"])
        assert cured["status"] == "ACTIVE"
        assert cured["nsf_strike_count"] == 0


# ─── helper ────────────────────────────────────────────────────────────
def api_scheduled_remittances(api, line_id):
    """Return (data, meta) for SCHEDULED remittances on a line."""
    from test_helpers import validate_paginated
    return validate_paginated(api.list_remittances(line_id, SV1, params={"status": "SCHEDULED"}))
