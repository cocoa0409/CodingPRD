"""Expiration, the closing waterfall, remainder disposition, and lockdown."""
from test_helpers import (
    ApiErrorId,
    PARTIES,
    TEST_USERS,
    approve_draw,
    close_holdback,
    create_approved_draw,
    create_draft_holdback,
    create_draw,
    create_extension,
    create_verified_draw,
    expire_holdback,
    get_holdback,
    get_work_order,
    list_draws,
    list_extensions,
    list_inspections,
    list_ledger,
    schedule_and_report_inspection,
    schedule_inspection,
    set_logical_clock,
    setup_active_holdback,
    setup_engagement,
    setup_escrow_file,
    setup_verified_engagement,
    submit_completion,
    validate_error,
    validate_success,
    verify_work_order,
)

OFFICER = TEST_USERS["officer_headers"]
BUYER = TEST_USERS["buyer_1_headers"]


class TestExpireBoundary:
    def test_expire_on_deadline_date_rejected(self, api):
        """PRD §3.8: "The clock date must be strictly after the `effective_deadline_date` — expiring on the deadline date itself, or any earlier day, fails with `ERR_NOT_EXPIRED`, because equality on the deadline date does not expire."

        Design: Difficulty/boundary_precision_check/expire_deadline_date_boundary
        """
        ctx = setup_active_holdback()
        hb_id = ctx["holdback"]["id"]
        set_logical_clock("2026-09-15T12:00:00Z")

        resp = api.expire_holdback(hb_id, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_EXPIRED)
        assert get_holdback(hb_id)["status"] == "ACTIVE"

    def test_expire_one_day_after_deadline_succeeds(self, api):
        """PRD §3.8: "The clock date must be strictly after the `effective_deadline_date` — expiring on the deadline date itself, or any earlier day, fails with `ERR_NOT_EXPIRED`, because equality on the deadline date does not expire."
        PRD §3.8: "Expiration moves the holdback from `ACTIVE` to `EXPIRED`"

        One day past the deadline the same call succeeds; with no extensions
        the effective deadline still equals the work deadline.

        Design: Difficulty/boundary_precision_check/expire_deadline_date_boundary
        """
        ctx = setup_active_holdback()
        hb_id = ctx["holdback"]["id"]
        set_logical_clock("2026-09-15T12:00:00Z")
        early = api.expire_holdback(hb_id, OFFICER)
        validate_error(early, ApiErrorId.ERR_NOT_EXPIRED)

        set_logical_clock("2026-09-16T00:00:00Z")
        expired = validate_success(api.expire_holdback(hb_id, OFFICER), 200)
        assert expired["status"] == "EXPIRED"
        assert expired["effective_deadline_date"] == "2026-09-15"


class TestExpireCascade:
    def test_expire_cancels_open_work_items(self, api):
        """PRD §3.8: "Expiration moves the holdback from `ACTIVE` to `EXPIRED` and cancels everything still open beneath it in one sweep: every `SUBMITTED` draw request becomes `CANCELLED`, every `PLANNED` inspection becomes `CANCELLED`, and every `PENDING` extension request becomes `CANCELLED`."
        PRD §2.7: "Second, the holdback's `reserved_cents` always equals the sum of the `amount_cents` of its draw requests currently in `APPROVED` (approved-but-unpaid) state."

        The APPROVED draw and the PASSED inspection survive; the SUBMITTED
        draw, the PLANNED inspection, and the PENDING extension are cancelled.

        Design: Corner/complexity_layers/expire_cancels_open_work_items
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]
        pair1 = create_approved_draw(ctx, 50000, description="Stage 1",
                                     scheduled_start="2026-08-20T10:00:00Z",
                                     scheduled_end="2026-08-20T11:00:00Z")
        draw2 = create_draw(hb_id, 40000, description="Stage 2")
        ins2 = schedule_inspection(hb_id, purpose="DRAW_VERIFICATION",
                                   scheduled_start="2026-08-25T10:00:00Z",
                                   scheduled_end="2026-08-25T11:00:00Z")
        ext = create_extension(hb_id, BUYER, reason="WEATHER_EXTERIOR",
                               requested_days=5, evidence_ref="NOAA log")

        set_logical_clock("2026-09-16T00:00:00Z")
        expired = expire_holdback(hb_id)
        assert expired["status"] == "EXPIRED"

        draws = {d["id"]: d for d in list_draws(hb_id)}
        assert draws[pair1["draw"]["id"]]["status"] == "APPROVED"
        assert draws[draw2["id"]]["status"] == "CANCELLED"

        ins = {i["id"]: i for i in list_inspections(hb_id)}
        assert ins[pair1["inspection"]["id"]]["status"] == "PASSED"
        assert ins[ins2["id"]]["status"] == "CANCELLED"

        exts = {e["id"]: e for e in list_extensions(hb_id)}
        assert exts[ext["id"]]["status"] == "CANCELLED"

        hb = get_holdback(hb_id)
        assert hb["reserved_cents"] == 50000, (
            "only the surviving APPROVED draw still reserves"
        )


class TestClosingReadiness:
    def test_expire_from_draft_rejected(self, api):
        """PRD §3.8: "Expiration is an explicit officer action on an `ACTIVE` holdback, never an automatic system transition."
        PRD §2.9: "Generic state preconditions on action endpoints: the attempted transition's from-state must hold (no wrong-from-state transitions, no actions on terminal resources, no duplicate decide/report/resolve/deposit, no reinspection without a prior failed final inspection) — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Even with the clock beyond the deadline, a DRAFT holdback cannot be
        expired — the state gate fires, not the temporal gate.

        Design: Corner/state_machines/expire_from_draft_rejected
        """
        set_logical_clock()
        file = setup_escrow_file()
        hb = create_draft_holdback(file["id"])
        set_logical_clock("2026-09-20T00:00:00Z")

        resp = api.expire_holdback(hb["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_from_draft_rejected(self, api):
        """PRD §3.8: "Closing is the terminal act, from either of two from-states with distinct readiness tests."
        PRD §2.9: "Generic state preconditions on action endpoints: the attempted transition's from-state must hold (no wrong-from-state transitions, no actions on terminal resources, no duplicate decide/report/resolve/deposit, no reinspection without a prior failed final inspection) — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Close is defined only from ACTIVE/EXPIRED; from DRAFT it fails with the
        generic state error rather than ERR_CLOSE_NOT_READY.

        Design: Corner/state_machines/close_from_draft_rejected
        """
        set_logical_clock()
        file = setup_escrow_file()
        hb = create_draft_holdback(file["id"])

        resp = api.close_holdback(hb["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_with_unverified_work_rejected(self, api):
        """PRD §3.8: "From `ACTIVE`, closing requires the holdback's `closeout_status` to be `READY_TO_CLOSE` — which it is exactly when the holdback is `ACTIVE`, `work_verified` is true, no dispute is `OPEN`, and no shortfall pledge is `PLEDGED`; in every other configuration `closeout_status` reads `NOT_READY` and the close fails with `ERR_CLOSE_NOT_READY`."

        Completion submitted but never verified leaves closeout NOT_READY.

        Design: Corner/validations/close_with_unverified_work_rejected
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]
        submit_completion(ctx["work_order"]["id"])

        resp = api.close_holdback(hb_id, OFFICER)
        validate_error(resp, ApiErrorId.ERR_CLOSE_NOT_READY)

        hb = get_holdback(hb_id)
        assert hb["status"] == "ACTIVE"
        assert hb["work_verified"] is False
        entries = list_ledger(hb_id)
        assert len(entries) == 1 and entries[0]["entry_type"] == "FUNDING"

    def test_closed_holdback_terminal_lockdown(self, api):
        """PRD §3.8: "the holdback settles into `CLOSED_COMPLETED` or `CLOSED_EXPIRED` (both terminal)"
        PRD §2.9: "Generic state preconditions on action endpoints: the attempted transition's from-state must hold (no wrong-from-state transitions, no actions on terminal resources, no duplicate decide/report/resolve/deposit, no reinspection without a prior failed final inspection) — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        From CLOSED_COMPLETED every further transition — close, expire, submit —
        is rejected.

        Design: Corner/state_machines/closed_holdback_terminal_lockdown
        """
        ctx = setup_verified_engagement()
        hb_id = ctx["holdback"]["id"]
        closed = close_holdback(hb_id)
        assert closed["status"] == "CLOSED_COMPLETED"

        set_logical_clock("2026-09-20T00:00:00Z")
        for attempt in (
            api.close_holdback(hb_id, OFFICER),
            api.expire_holdback(hb_id, OFFICER),
            api.submit_holdback(hb_id, OFFICER),
        ):
            validate_error(attempt, ApiErrorId.ERR_INVALID_STATE)

        assert get_holdback(hb_id)["status"] == "CLOSED_COMPLETED"


class TestCloseWaterfall:
    def test_close_split_rounding_order(self, api):
        """PRD §2.6: "In the closing-waterfall split, the seller's share is the half rounded half-up first, and the buyer's share is the residual."
        PRD §3.8: "The split is pinned: the seller's share is half the remainder rounded half-up to whole cents — the seller's side is rounded first — and the buyer's share is the residual, the remainder minus the seller's share; the `RETURN_TO_SELLER` entry is appended before the `RELEASE_TO_BUYER` entry."

        On an odd 10503-cent remainder (estimate 9548 @ 10%) the seller share
        rounds half-up to 5252 first and the buyer takes the 5251 residual.

        Design: Difficulty/combinatorial_formula/close_split_rounding_order
        """
        ctx = setup_verified_engagement(
            file_overrides={"property_address": "2 Cedar Ln"},
            repair_scope="Fence rebuild", repair_estimate_cents=9548,
            contingency_pct=10, funding_source="SPLIT_EQUAL",
            overrun_responsibility="SPLIT_EQUAL",
            exterior_work_flag=False, bid_amount_cents=9000,
        )
        hb_id = ctx["holdback"]["id"]
        assert ctx["holdback"]["holdback_amount_cents"] == 10503

        close_holdback(hb_id)
        entries = list_ledger(hb_id)
        assert [e["entry_type"] for e in entries] == [
            "FUNDING", "RETURN_TO_SELLER", "RELEASE_TO_BUYER"]
        assert entries[1]["amount_cents"] == -5252, "seller share rounded half-up first"
        assert entries[2]["amount_cents"] == -5251, "buyer takes the residual"

    def test_close_split_running_balances_conserve_to_zero(self, api):
        """PRD §3.8: "When the waterfall finishes, the trust balance is exactly zero — that is the closing invariant"
        PRD §2.6: "Rounding both shares independently is forbidden: on odd cent amounts the two independently rounded halves drift apart from the total by a cent, and the residual rule is what keeps the trust account exactly balanced."

        Running balances 10503 -> 5251 -> 0 show no cent drift; the holdback
        settles CLOSED_COMPLETED with trust balance zero.

        Design: Difficulty/combinatorial_formula/close_split_rounding_order
        """
        ctx = setup_verified_engagement(
            file_overrides={"property_address": "2 Cedar Ln"},
            repair_scope="Fence rebuild", repair_estimate_cents=9548,
            contingency_pct=10, funding_source="SPLIT_EQUAL",
            overrun_responsibility="SPLIT_EQUAL",
            exterior_work_flag=False, bid_amount_cents=9000,
        )
        hb_id = ctx["holdback"]["id"]

        closed = close_holdback(hb_id)
        assert closed["status"] == "CLOSED_COMPLETED"
        assert closed["trust_balance_cents"] == 0

        entries = list_ledger(hb_id)
        assert [e["running_balance_cents"] for e in entries] == [10503, 5251, 0]
        assert sum(e["amount_cents"] for e in entries) == 0

    def test_close_waterfall_pays_approved_draw_then_remainder(self, api):
        """PRD §3.8: "Step one pays every still-`APPROVED` draw in `approved_at` ascending order, ties broken by `created_at` ascending: each draw gets its `DRAW_DEBIT` entry for the negative amount, is stamped `paid_at`, and moves to `PAID`."
        PRD §3.8: "On the completed path the disposition basis is the holdback's `funding_source`: `SELLER_PROCEEDS` returns the entire remainder to the seller through a single `RETURN_TO_SELLER` entry"

        Close on a verified holdback with one unpaid APPROVED draw appends
        DRAW_DEBIT -80000 (running 150000) then RETURN_TO_SELLER -150000
        (running 0).

        Design: Difficulty/transitive_cascade/close_cascade_ledger_file_bubbleup
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]
        pair = create_approved_draw(ctx, 80000, description="Stage 1",
                                    scheduled_start="2026-08-20T10:00:00Z",
                                    scheduled_end="2026-08-20T11:00:00Z")
        verify_work_order(ctx)

        closed = close_holdback(hb_id)
        assert closed["status"] == "CLOSED_COMPLETED"

        entries = list_ledger(hb_id)
        assert [e["entry_type"] for e in entries] == [
            "FUNDING", "DRAW_DEBIT", "RETURN_TO_SELLER"]
        assert entries[1]["amount_cents"] == -80000
        assert entries[1]["running_balance_cents"] == 150000
        assert entries[2]["amount_cents"] == -150000
        assert entries[2]["running_balance_cents"] == 0

    def test_close_bubbles_up_file_status_and_pays_draw(self, api):
        """PRD §3.8: "the holdback settles into `CLOSED_COMPLETED` or `CLOSED_EXPIRED` (both terminal), and the escrow file's `status` recomputes to `CLOSED` in the same breath."
        PRD §3.1: "it reads `CLOSED` once the holdback reaches `CLOSED_COMPLETED` or `CLOSED_EXPIRED`."
        PRD §3.8: "Step one pays every still-`APPROVED` draw in `approved_at` ascending order, ties broken by `created_at` ascending: each draw gets its `DRAW_DEBIT` entry for the negative amount, is stamped `paid_at`, and moves to `PAID`."

        The waterfall pays the approved draw without any pay call, and the
        escrow file flips to CLOSED.

        Design: Difficulty/transitive_cascade/close_cascade_ledger_file_bubbleup
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]
        pair = create_approved_draw(ctx, 80000, description="Stage 1",
                                    scheduled_start="2026-08-20T10:00:00Z",
                                    scheduled_end="2026-08-20T11:00:00Z")
        verify_work_order(ctx)

        close_holdback(hb_id)

        draws = {d["id"]: d for d in list_draws(hb_id)}
        assert draws[pair["draw"]["id"]]["status"] == "PAID"
        assert draws[pair["draw"]["id"]]["paid_at"] is not None

        file_after = validate_success(api.get_file(ctx["file"]["id"], OFFICER), 200)
        assert file_after["status"] == "CLOSED"

        hb = get_holdback(hb_id)
        assert hb["trust_balance_cents"] == 0
        assert hb["total_disbursed_cents"] == 80000
