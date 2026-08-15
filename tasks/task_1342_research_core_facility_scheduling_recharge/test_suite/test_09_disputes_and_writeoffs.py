"""The dispute loop, write-off compensation, batch immutability, and grant
conservation (PRD §2.10, §3.4, §3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, make_researcher_headers,
    setup_billed_entry, open_batch, get_grant, get_batch, find_entries,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _owner(ctx):
    return make_researcher_headers(ctx["stack"]["u1"]["id"])


def _dispute_and_reopen(api, ctx):
    """Dispute the billed entry as its owner, then open the 2026-10 batch."""
    disputed = validate_success(
        api.dispute_recharge_entry(
            ctx["entry"]["id"], {"dispute_reason": "hours look wrong"}, _owner(ctx)
        ),
        200,
    )
    assert disputed["status"] == "DISPUTED"
    bat10 = open_batch(2026, 10)
    return bat10


class TestDisputeCycle:
    def test_uphold_returns_to_billed_and_clears_reason(self, api):
        """PRD §3.9: "Once `BILLED`, an entry may be marked `PAID` by a
        `FinanceOfficer`, or disputed by its owner or a `FinanceOfficer` with a
        non-empty `dispute_reason`, moving to `DISPUTED`. Dispute resolution by
        a `FinanceOfficer` takes a `resolution` (with an optional `note`):
        `UPHOLD` returns the entry to `BILLED` and clears `dispute_reason` —
        the dispute loop may repeat".

        Design: Difficulty/non_linear_state_machine/recharge_entry_dispute_cycle
        """
        ctx = setup_billed_entry()
        entry_id = ctx["entry"]["id"]
        disputed = validate_success(
            api.dispute_recharge_entry(
                entry_id, {"dispute_reason": "hours look wrong"}, _owner(ctx)
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"
        upheld = validate_success(
            api.resolve_recharge_entry_dispute(
                entry_id, {"resolution": "UPHOLD"}, FINANCE
            ),
            200,
        )
        assert upheld["status"] == "BILLED"
        assert upheld["dispute_reason"] is None, "UPHOLD clears the reason"
        # The loop may repeat: a second dispute is accepted from BILLED.
        redispputed = validate_success(
            api.dispute_recharge_entry(
                entry_id, {"dispute_reason": "recount requested by PI"}, _owner(ctx)
            ),
            200,
        )
        assert redispputed["status"] == "DISPUTED"

    def test_write_off_credits_grant_and_posts_adjustment(self, api):
        """PRD §3.9: "`WRITE_OFF` moves the entry to `WRITTEN_OFF` and triggers
        the compensating cascade: an `ADJUSTMENT` entry is created in the
        currently open batch (`ERR_BATCH_NOT_OPEN` if none) with kind
        `ADJUSTMENT`, status `PAID`, the original's `grant_id`, `user_id`, and
        `instrument_id` copied across, `amount_cents` the negative of the
        original's amount, `subsidy_offset_cents` zero, and `net_amount_cents`
        likewise the negative of the original." PRD §2.10: "`budget_used_cents`
        is the sum of `net_amount_cents` over the grant's recharge entries of
        kind `USAGE` or `PENALTY` whose status is `PENDING`, `BILLED`, `PAID`,
        or `DISPUTED` — entries in `WRITTEN_OFF` are excluded because they have
        been reversed, and `ADJUSTMENT` entries never count."

        Design: Difficulty/non_linear_state_machine/recharge_entry_dispute_cycle
        """
        ctx = setup_billed_entry()
        bat10 = _dispute_and_reopen(api, ctx)
        resolved = validate_success(
            api.resolve_recharge_entry_dispute(
                ctx["entry"]["id"],
                {"resolution": "WRITE_OFF", "note": "goodwill"},
                FINANCE,
            ),
            200,
        )
        assert resolved["status"] == "WRITTEN_OFF"
        grant = get_grant(ctx["stack"]["g1"]["id"])
        assert grant["budget_used_cents"] == 0, "the write-off fully credits the grant"
        assert grant["budget_available_cents"] == 100000
        adjustments = find_entries(batch_id=bat10["id"], kind="ADJUSTMENT")
        assert len(adjustments) == 1
        assert adjustments[0]["amount_cents"] == -15000
        assert adjustments[0]["net_amount_cents"] == -15000
        bat9_after = get_batch(ctx["batch"]["id"])
        assert bat9_after["gross_amount_cents"] == 15000, "finalized totals frozen"


class TestEntryTerminalLockdown:
    def test_entry_paid_terminal_lockdown(self, api):
        """PRD §3.9: "Once `BILLED`, an entry may be marked `PAID` by a
        `FinanceOfficer`, or disputed by its owner or a `FinanceOfficer` with a
        non-empty `dispute_reason`, moving to `DISPUTED`." and "`PAID` and
        `WRITTEN_OFF` are terminal." PRD §2.9: "State-machine legality
        (`ERR_INVALID_STATE`): the target resource's current state must permit
        the requested transition".

        Design: Corner/state_machines/entry_paid_terminal_lockdown
        """
        ctx = setup_billed_entry()
        paid = validate_success(
            api.mark_recharge_entry_paid(ctx["entry"]["id"], FINANCE), 200
        )
        assert paid["status"] == "PAID"
        res = api.dispute_recharge_entry(
            ctx["entry"]["id"], {"dispute_reason": "too late"}, _owner(ctx)
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        after = validate_success(
            api.get_recharge_entry(ctx["entry"]["id"], FINANCE), 200
        )
        assert after["status"] == "PAID"


class TestFinalizedBatchImmutability:
    def test_finalized_totals_survive_entry_writeoff(self, api):
        """PRD §3.9: "Finalization by a `FinanceOfficer` flips every `PENDING`
        entry in the batch to `BILLED`, freezes the four totals by recomputing
        them once — they are immutable thereafter". and "Corrections after
        finalization never touch the frozen batch — they post as `ADJUSTMENT`
        entries into the *next* open batch."

        Design: Difficulty/compensating_invariant/finalized_batch_total_immutability
        """
        ctx = setup_billed_entry()
        at_close = ctx["batch"]
        assert at_close["gross_amount_cents"] == 15000
        assert at_close["net_amount_cents"] == 15000
        assert at_close["entry_count"] == 1

        _dispute_and_reopen(api, ctx)
        validate_success(
            api.resolve_recharge_entry_dispute(
                ctx["entry"]["id"], {"resolution": "WRITE_OFF"}, FINANCE
            ),
            200,
        )
        frozen = get_batch(ctx["batch"]["id"])
        assert frozen["gross_amount_cents"] == 15000, "frozen gross must not move"
        assert frozen["net_amount_cents"] == 15000
        assert frozen["entry_count"] == 1

    def test_adjustment_lands_in_next_open_batch(self, api):
        """PRD §3.9: "Corrections after finalization never touch the frozen
        batch — they post as `ADJUSTMENT` entries into the *next* open batch."
        and "`WRITE_OFF` moves the entry to `WRITTEN_OFF` and triggers the
        compensating cascade: an `ADJUSTMENT` entry is created in the currently
        open batch (`ERR_BATCH_NOT_OPEN` if none) with kind `ADJUSTMENT`,
        status `PAID`".

        Design: Difficulty/compensating_invariant/finalized_batch_total_immutability
        """
        ctx = setup_billed_entry()
        bat10 = _dispute_and_reopen(api, ctx)
        validate_success(
            api.resolve_recharge_entry_dispute(
                ctx["entry"]["id"], {"resolution": "WRITE_OFF"}, FINANCE
            ),
            200,
        )
        entry_after = validate_success(
            api.get_recharge_entry(ctx["entry"]["id"], FINANCE), 200
        )
        assert entry_after["status"] == "WRITTEN_OFF"
        bat10_after = get_batch(bat10["id"])
        assert bat10_after["entry_count"] == 1, "the ADJUSTMENT posts to 2026-10"
        assert bat10_after["gross_amount_cents"] == -15000


class TestGrantCloseAndConservation:
    def test_grant_close_blocked_by_open_entries(self, api):
        """PRD §3.4: "Closing a grant is a `FinanceOfficer` action permitted
        from `ACTIVE`, `EXHAUSTED`, or `EXPIRED`, but only while no recharge
        entries on the grant sit in `PENDING`, `BILLED`, or `DISPUTED` status;
        otherwise the close is rejected with `ERR_GRANT_HAS_OPEN_ENTRIES`."

        Design: Corner/validations/grant_close_blocked_by_open_entries
        """
        ctx = setup_billed_entry()
        bat10 = _dispute_and_reopen(api, ctx)  # entry now DISPUTED
        blocked = api.close_grant(ctx["stack"]["g1"]["id"], FINANCE)
        validate_error(blocked, "ERR_GRANT_HAS_OPEN_ENTRIES", expected_status=409)
        validate_success(
            api.resolve_recharge_entry_dispute(
                ctx["entry"]["id"], {"resolution": "WRITE_OFF"}, FINANCE
            ),
            200,
        )
        closed = validate_success(
            api.close_grant(ctx["stack"]["g1"]["id"], FINANCE), 200
        )
        assert closed["status"] == "CLOSED", (
            "WRITTEN_OFF is not an open status, so the close succeeds"
        )

    def test_bill_then_writeoff_restores_grant_exactly(self, api):
        """PRD §2.10: "`budget_used_cents` is the sum of `net_amount_cents`
        over the grant's recharge entries of kind `USAGE` or `PENALTY` whose
        status is `PENDING`, `BILLED`, `PAID`, or `DISPUTED` — entries in
        `WRITTEN_OFF` are excluded because they have been reversed, and
        `ADJUSTMENT` entries never count." PRD §3.9: "The written-off original
        leaves the grant's counted set while the adjustment never counts, so
        the grant's `budget_used_cents` recomputes to fully credit the original
        charge and the grant's status is recomputed".

        Design: Difficulty/compensating_invariant/grant_budget_bill_writeoff_conservation
        """
        ctx = setup_billed_entry()
        mid = get_grant(ctx["stack"]["g1"]["id"])
        assert mid["budget_used_cents"] == 15000, "BILLED entry counts as used"

        _dispute_and_reopen(api, ctx)
        validate_success(
            api.resolve_recharge_entry_dispute(
                ctx["entry"]["id"],
                {"resolution": "WRITE_OFF", "note": "billing error confirmed"},
                FINANCE,
            ),
            200,
        )
        post = get_grant(ctx["stack"]["g1"]["id"])
        assert post["budget_used_cents"] == 0, "identical to before the pair"
        assert post["budget_available_cents"] == 100000

    def test_counted_set_invariant_holds_at_each_step(self, api):
        """PRD §2.10: "`budget_used_cents` is the sum of `net_amount_cents`
        over the grant's recharge entries of kind `USAGE` or `PENALTY` whose
        status is `PENDING`, `BILLED`, `PAID`, or `DISPUTED` — entries in
        `WRITTEN_OFF` are excluded because they have been reversed, and
        `ADJUSTMENT` entries never count."

        Design: Difficulty/compensating_invariant/grant_budget_bill_writeoff_conservation
        """
        ctx = setup_billed_entry()
        bat10 = _dispute_and_reopen(api, ctx)
        validate_success(
            api.resolve_recharge_entry_dispute(
                ctx["entry"]["id"], {"resolution": "WRITE_OFF"}, FINANCE
            ),
            200,
        )
        entries = find_entries(grant_id=ctx["stack"]["g1"]["id"])
        counted = [
            e for e in entries
            if e["kind"] in ("USAGE", "PENALTY")
            and e["status"] in ("PENDING", "BILLED", "PAID", "DISPUTED")
        ]
        recomputed = sum(e["net_amount_cents"] for e in counted)
        grant = get_grant(ctx["stack"]["g1"]["id"])
        assert grant["budget_used_cents"] == recomputed == 0
        adjustments = find_entries(grant_id=ctx["stack"]["g1"]["id"],
                                   kind="ADJUSTMENT")
        assert len(adjustments) == 1
        assert adjustments[0]["amount_cents"] == -15000
        assert adjustments[0]["batch_id"] == bat10["id"]
