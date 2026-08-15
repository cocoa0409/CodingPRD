"""Trust ledger shape, reconciliation invariants, and conserved quantities."""
from test_helpers import (
    TEST_USERS,
    approve_draw,
    assert_ledger_entry,
    assert_ledger_invariants,
    close_holdback,
    create_approved_draw,
    create_draft_holdback,
    create_verified_draw,
    get_holdback,
    list_draws,
    list_ledger,
    pay_draw,
    set_logical_clock,
    setup_engagement,
    setup_escrow_file,
    verify_work_order,
)

OFFICER = TEST_USERS["officer_headers"]


class TestLedgerShape:
    def test_ledger_entry_immutable_shape(self, api):
        """PRD §2.5: "The trust ledger entry is the single exception to this convention: because entries are immutable once appended, a ledger entry carries only `id` and `created_at`; both `updated_at` and `version` are absent from it."
        PRD §2.7: "The `seq` field is a per-holdback monotonic sequence starting at 1 and assigned in append order"

        Entries expose exactly the ledger field set — no version, no
        updated_at — ordered by seq ascending.

        Design: Corner/entities/ledger_entry_immutable_shape
        """
        set_logical_clock()
        file = setup_escrow_file()
        hb = create_draft_holdback(file["id"])

        entries = list_ledger(hb["id"])
        assert len(entries) == 1
        entry = entries[0]
        assert_ledger_entry(entry)
        assert set(entry.keys()) <= {
            "id", "created_at", "holdback_id", "seq", "entry_type",
            "amount_cents", "running_balance_cents", "memo",
        }
        assert entry["seq"] == 1
        assert [e["seq"] for e in entries] == sorted(e["seq"] for e in entries)


class TestTrustCashConservation:
    def _setup_paid_draw_and_close(self, api):
        """230000 funded; draw 80000 approved AND paid via the pay endpoint;
        work verified; then closed (remainder 150000 to seller)."""
        ctx = setup_engagement()
        pair = create_approved_draw(ctx, 80000, description="Stage 1",
                                    scheduled_start="2026-08-20T10:00:00Z",
                                    scheduled_end="2026-08-20T11:00:00Z")
        pay_draw(pair["draw"]["id"])
        verify_work_order(ctx)
        close_holdback(ctx["holdback"]["id"])
        return ctx

    def test_trust_cash_conserved_over_lifecycle_amounts(self, api):
        """PRD §2.7: "First, the holdback's `trust_balance_cents` always equals the sum of the signed `amount_cents` over all of its entries, which always equals the last entry's `running_balance_cents`."
        PRD §3.8: "When the waterfall finishes, the trust balance is exactly zero — that is the closing invariant"

        Funding (+230000) is compensated by the draw pay (-80000) plus the
        close remainder (-150000); the signed sum nets to exactly zero.

        Design: Difficulty/compensating_invariant/trust_cash_conserved_over_lifecycle
        """
        ctx = self._setup_paid_draw_and_close(api)
        hb = get_holdback(ctx["holdback"]["id"])
        entries = list_ledger(ctx["holdback"]["id"])

        amounts = [e["amount_cents"] for e in entries]
        assert amounts == [230000, -80000, -150000]
        assert [e["entry_type"] for e in entries] == [
            "FUNDING", "DRAW_DEBIT", "RETURN_TO_SELLER"]
        assert sum(amounts) == 0 == hb["trust_balance_cents"], (
            "the escrow trust returns to neutral with zero drift"
        )
        assert_ledger_invariants(entries, hb["trust_balance_cents"])

    def test_trust_cash_running_balance_and_disbursed_totals(self, api):
        """PRD §2.7: "Two further aggregates derive from the ledger: `total_disbursed_cents` is the sum of the magnitudes of all `DRAW_DEBIT` entries"
        PRD §2.7: "Each entry's `running_balance_cents` is the previous entry's `running_balance_cents` plus this entry's signed amount; the first entry's running balance equals its own amount."

        Running balances walk 230000 -> 150000 -> 0, and the disbursed total
        is exactly the paid draw.

        Design: Difficulty/compensating_invariant/trust_cash_conserved_over_lifecycle
        """
        ctx = self._setup_paid_draw_and_close(api)
        hb = get_holdback(ctx["holdback"]["id"])
        entries = list_ledger(ctx["holdback"]["id"])

        assert [e["running_balance_cents"] for e in entries] == [230000, 150000, 0]
        assert hb["total_disbursed_cents"] == 80000
        assert hb["status"] == "CLOSED_COMPLETED"


class TestReservedCommitmentInvariant:
    def _setup_two_approved_then_pay_first(self, api):
        """draw1 80000 APPROVED, draw2 50000 APPROVED (reserved 130000);
        then draw1 paid."""
        ctx = setup_engagement()
        pair1 = create_approved_draw(ctx, 80000, description="Stage 1",
                                     scheduled_start="2026-08-20T10:00:00Z",
                                     scheduled_end="2026-08-20T11:00:00Z")
        pair2 = create_approved_draw(ctx, 50000, description="Stage 2",
                                     scheduled_start="2026-08-21T10:00:00Z",
                                     scheduled_end="2026-08-21T11:00:00Z")
        pay_draw(pair1["draw"]["id"])
        return ctx, pair1, pair2

    def test_reserved_nets_to_surviving_commitment(self, api):
        """PRD §3.5: "Payment appends a `DRAW_DEBIT` entry for the negative amount, reduces `trust_balance_cents` by the amount, grows `total_disbursed_cents` by the amount, releases the reservation by reducing `reserved_cents` by the amount, stamps `paid_at`, and moves the draw to `PAID`."
        PRD §2.7: "Second, the holdback's `reserved_cents` always equals the sum of the `amount_cents` of its draw requests currently in `APPROVED` (approved-but-unpaid) state."

        approve 80000 + approve 50000 - pay 80000 leaves reserved at exactly
        the surviving 50000 commitment — no drift after the round trip.

        Design: Difficulty/compensating_invariant/reserved_commitment_approve_pay_neutral
        """
        ctx, pair1, pair2 = self._setup_two_approved_then_pay_first(api)
        hb = get_holdback(ctx["holdback"]["id"])
        assert hb["reserved_cents"] == 50000

        draws = list_draws(ctx["holdback"]["id"])
        approved_sum = sum(d["amount_cents"] for d in draws if d["status"] == "APPROVED")
        assert approved_sum == 50000 == hb["reserved_cents"]
        statuses = {d["id"]: d["status"] for d in draws}
        assert statuses[pair1["draw"]["id"]] == "PAID"
        assert statuses[pair2["draw"]["id"]] == "APPROVED"

    def test_pay_moves_cash_while_approve_never_does(self, api):
        """PRD §3.5: "Payment appends a `DRAW_DEBIT` entry for the negative amount, reduces `trust_balance_cents` by the amount, grows `total_disbursed_cents` by the amount, releases the reservation by reducing `reserved_cents` by the amount, stamps `paid_at`, and moves the draw to `PAID`."

        After the approve/approve/pay round trip: trust 150000 (only the pay
        moved cash), disbursed 80000.

        Design: Difficulty/compensating_invariant/reserved_commitment_approve_pay_neutral
        """
        ctx, pair1, pair2 = self._setup_two_approved_then_pay_first(api)
        hb = get_holdback(ctx["holdback"]["id"])
        assert hb["trust_balance_cents"] == 150000, "230000 funded - 80000 paid"
        assert hb["total_disbursed_cents"] == 80000

        entries = list_ledger(ctx["holdback"]["id"])
        assert [e["entry_type"] for e in entries] == ["FUNDING", "DRAW_DEBIT"]
        assert entries[1]["running_balance_cents"] == 150000
