"""Refused triggers, and the cascades a pulled date sends down the tree.

Every test here either fires a trigger the contract declares no edge for and
checks that nothing moved, or walks one of the two cancellation forks and
checks each declared side effect.
"""

import pytest

from test_helpers import api_errors as E
from test_helpers import (
    assert_market_exposure,
    assert_timestamp_equals,
    assert_unchanged,
    get_success_data,
    make_risk_officer_headers,
    make_tour_accountant_headers,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

ZERO_FEE_WORLD = {
    "guarantee_exposure_limit_cents": 5_000_000,
    "gross_capacity": 1_000,
    "facility_fee_cents_per_ticket": 0,
    "ticket_tax_pct": 0,
}

ROW_IDENTITY = ("status", "version")


def zero_fee(**overrides):
    """A market, act and venue whose ticket tax and facility fee are both 0."""
    kwargs = dict(ZERO_FEE_WORLD)
    kwargs.update(overrides)
    return kwargs


def rental_terms(rental_fee_cents=150_000, **overrides):
    """RENTAL show terms with every co-promote percentage explicitly 0."""
    terms = {
        "venue_arrangement": "RENTAL",
        "rental_fee_cents": rental_fee_cents,
        "copromote_venue_share_pct": 0,
        "venue_expense_pct_production": 0,
        "venue_expense_pct_marketing": 0,
        "venue_expense_pct_staffing": 0,
        "venue_expense_pct_hospitality": 0,
    }
    terms.update(overrides)
    return terms


def planned_show_with_open_children(build):
    """A PLANNED show carrying a DRAFT offer, a DRAFT tier and a COMP hold."""
    ctx = build.planned_show(show=rental_terms(), **zero_fee(gross_capacity=800))
    ctx["offer"] = build.offer(
        ctx["show"]["id"],
        guarantee_cents=700_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    ctx["tier"] = build.tier(
        ctx["show"]["id"], tier_name="GA", price_cents=4_000, allocation_qty=400
    )
    ctx["hold"] = build.hold(
        ctx["tier"]["id"], kind="COMP", qty=5, holder="local radio winners"
    )
    ctx["show"] = build.read_show(ctx["show"]["id"])
    return ctx


def confirmed_show_with_a_submitted_invoice(build):
    """A CONFIRMED show, one STAFFING line and one SUBMITTED invoice on it."""
    ctx = build.confirmed_show(
        guarantee_cents=700_000,
        expense_cap_cents=1_000_000,
        show=rental_terms(),
        **zero_fee(),
    )
    ctx["line"] = build.budget_line(
        ctx["show"]["id"],
        category="STAFFING",
        description="stagehand call",
        budgeted_cents=150_000,
    )
    ctx["invoice"] = build.submitted_invoice(
        ctx["show"]["id"], ctx["line"]["id"], 150_000, vendor_name="Local One"
    )
    return ctx


def performed_show_with_a_draft_settlement(build):
    """A PERFORMED show whose settlement book has only just been opened."""
    ctx = build.performed_show(
        guarantee_cents=700_000,
        expense_cap_cents=1_000_000,
        tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 400}],
        announce_at="2026-08-01T00:00:00.000Z",
        show=rental_terms(),
        **zero_fee(),
    )
    ctx["settlement"] = build.settlement(ctx["show"]["id"])
    return ctx


def opened_cancellation_event(build):
    """A pulled PLANNED date whose cancellation event is still OPENED."""
    ctx = build.planned_show(show=rental_terms(), **zero_fee())
    ctx["event"] = build.cancellation_event(
        ctx["show"]["id"],
        kind="CANCELLED",
        reason="the act pulled the date before the deal closed",
    )
    return ctx


class TestTriggersWithNoDeclaredEdge:
    """A trigger the current state declares no edge for is refused outright."""

    @pytest.mark.parametrize(
        "trigger",
        [
            pytest.param(
                lambda api, build, ctx: api.perform_show(
                    ctx["show"]["id"], build.accountant
                ),
                id="perform",
            ),
            pytest.param(
                lambda api, build, ctx: api.pause_sales(
                    ctx["show"]["id"], "a winter storm warning", build.risk
                ),
                id="pause-sales",
            ),
            pytest.param(
                lambda api, build, ctx: api.resume_sales(
                    ctx["show"]["id"], build.buyer
                ),
                id="resume-sales",
            ),
        ],
    )
    def test_show_triggers_with_no_edge_from_planned_are_rejected(
        self, api, build, trigger
    ):
        """PRD 2.9: "State legality — `ERR_INVALID_STATE` when the target sits in a non-terminal state from which the requested trigger has no declared transition, including sub-resource guards such as a show's ticketing state or a budget line's own lifecycle state."

        Design: Corner/state_machines/triggers_with_no_declared_edge_from_the_current_state_are_rejected
        """
        ctx = planned_show_with_open_children(build)
        validate_error(trigger(api, build, ctx), E.ERR_INVALID_STATE)
        show = build.read_show(ctx["show"]["id"])
        assert show["show_status"] == "PLANNED"
        assert show["sales_status"] == "PRE_SALE"
        # A Show carries two status dimensions rather than a single `status`.
        assert_unchanged(
            show, ctx["show"], ("show_status", "sales_status", "version", "updated_at")
        )

    @pytest.mark.parametrize(
        "trigger",
        [
            pytest.param(
                lambda api, build, ctx: api.accept_offer(
                    ctx["offer"]["id"], build.artist_rep(ctx["artist"]["id"])
                ),
                id="accept",
            ),
            pytest.param(
                lambda api, build, ctx: api.counter_offer(
                    ctx["offer"]["id"],
                    build.artist_rep(ctx["artist"]["id"]),
                    counter_guarantee_cents=750_000,
                    counter_note="the act needs a higher floor for this routing",
                ),
                id="counter",
            ),
        ],
    )
    def test_offer_triggers_with_no_edge_from_draft_are_rejected(
        self, api, build, trigger
    ):
        """PRD 3.3: "An `ArtistRep` whose `X-User-ID` equals the show's `artist_id` accepts a `SUBMITTED` offer on a show that is still `PLANNED`; the offer moves `SUBMITTED → ACCEPTED` and, in the same request, the show moves `PLANNED → CONFIRMED`."

        Design: Corner/state_machines/triggers_with_no_declared_edge_from_the_current_state_are_rejected
        """
        ctx = planned_show_with_open_children(build)
        validate_error(trigger(api, build, ctx), E.ERR_INVALID_STATE)
        offer = build.read_offer(ctx["offer"]["id"])
        assert offer["status"] == "DRAFT"
        assert offer["round_index"] == 1
        assert build.read_show(ctx["show"]["id"])["show_status"] == "PLANNED"

    @pytest.mark.parametrize(
        "trigger",
        [
            pytest.param(
                lambda api, build, ctx: api.approve_vendor_invoice(
                    ctx["invoice"]["id"], build.accountant_two
                ),
                id="approve",
            ),
            pytest.param(
                lambda api, build, ctx: api.resolve_vendor_invoice_dispute(
                    ctx["invoice"]["id"],
                    build.accountant,
                    outcome="RESUBMIT",
                    amount_cents=150_000,
                    documentation_ref="INV-REDO-1",
                ),
                id="dispute-resolution",
            ),
        ],
    )
    def test_invoice_triggers_with_no_edge_from_submitted_are_rejected(
        self, api, build, trigger
    ):
        """PRD 3.6: "Approval — available to a `TourAccountant` or a `RiskOfficer` — moves it `VERIFIED → APPROVED` and records `approved_by_user_id`"

        Design: Corner/state_machines/triggers_with_no_declared_edge_from_the_current_state_are_rejected
        """
        ctx = confirmed_show_with_a_submitted_invoice(build)
        validate_error(trigger(api, build, ctx), E.ERR_INVALID_STATE)
        invoice = build.read_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "SUBMITTED"
        assert invoice["approved_by_user_id"] is None
        assert invoice["resubmit_count"] == 0
        assert build.read_budget_line(ctx["line"]["id"])["actual_cents"] == 0

    @pytest.mark.parametrize(
        "trigger",
        [
            pytest.param(
                lambda api, build, ctx: api.respond_to_settlement(
                    ctx["settlement"]["id"],
                    build.artist_rep(ctx["artist"]["id"]),
                    response="SIGN",
                ),
                id="artist-response",
            ),
            pytest.param(
                lambda api, build, ctx: api.pay_settlement(
                    ctx["settlement"]["id"],
                    build.accountant,
                    payment_method="WIRE",
                    payment_reference="WIRE-40001",
                ),
                id="pay",
            ),
            pytest.param(
                lambda api, build, ctx: api.reopen_settlement(
                    ctx["settlement"]["id"],
                    build.risk,
                    reopen_reason="the box office count arrived after the walkout",
                ),
                id="reopen",
            ),
        ],
    )
    def test_settlement_triggers_with_no_edge_from_draft_are_rejected(
        self, api, build, trigger
    ):
        """PRD 3.8: "Once the settlement is `CALCULATED`, the artist side answers it."

        Design: Corner/state_machines/triggers_with_no_declared_edge_from_the_current_state_are_rejected
        """
        ctx = performed_show_with_a_draft_settlement(build)
        validate_error(trigger(api, build, ctx), E.ERR_INVALID_STATE)
        settlement = build.read_settlement(ctx["settlement"]["id"])
        assert settlement["status"] == "DRAFT"
        assert settlement["signed_by_user_id"] is None
        assert settlement["paid_at"] is None
        assert settlement["reopen_count"] == 0
        assert build.read_show(ctx["show"]["id"])["show_status"] == "PERFORMED"

    @pytest.mark.parametrize(
        "trigger",
        [
            pytest.param(
                lambda api, build, ctx: api.file_claim(
                    ctx["event"]["id"],
                    build.risk,
                    claim_amount_cents=100_000,
                    claim_documentation_ref="CLAIM-40001",
                ),
                id="file-claim",
            ),
            pytest.param(
                lambda api, build, ctx: api.settle_claim(
                    ctx["event"]["id"],
                    build.risk_two,
                    outcome="SETTLE",
                    insurer_reference="INS-40001",
                ),
                id="settle-claim",
            ),
        ],
    )
    def test_cancellation_event_triggers_with_no_edge_from_opened_are_rejected(
        self, api, build, trigger
    ):
        """PRD 3.9: "A `RiskOfficer` then files an insurance claim, moving the event `REFUNDS_PROCESSED → CLAIM_FILED`"

        Design: Corner/state_machines/triggers_with_no_declared_edge_from_the_current_state_are_rejected
        """
        ctx = opened_cancellation_event(build)
        validate_error(trigger(api, build, ctx), E.ERR_INVALID_STATE)
        event = build.read_event(ctx["event"]["id"])
        assert event["status"] == "OPENED"
        assert event["filed_by_user_id"] is None
        assert event["covered_loss_cents"] == 0
        assert event["insurance_recovery_cents"] == 0

    def test_convert_to_comp_has_no_declared_edge_from_a_comp_hold(self, api, build):
        """PRD 3.5: "The hold must be in `HELD`, its `kind` must be something other than `COMP`, and the show's `sales_status` must be `PRE_SALE`, `SELLING` or `PAUSED`."

        Design: Corner/state_machines/triggers_with_no_declared_edge_from_the_current_state_are_rejected
        """
        ctx = planned_show_with_open_children(build)
        before = build.read_tier(ctx["tier"]["id"])
        validate_error_is_one_of(
            api.convert_hold_to_comp(ctx["hold"]["id"], build.buyer),
            [E.ERR_INVALID_STATE, E.ERR_INVALID_REQUEST],
        )
        hold = build.read_hold(ctx["hold"]["id"])
        assert hold["status"] == "HELD"
        assert hold["kind"] == "COMP"
        assert hold["released_by_user_id"] is None
        assert_unchanged(
            build.read_tier(ctx["tier"]["id"]),
            before,
            ("comp_qty", "held_qty", "available_qty", "version"),
        )

    def test_releasing_a_hold_once_ticketing_has_closed_is_rejected(self, api, build):
        """PRD 3.5: "Releasing a hold puts the seats back. The hold must be in `HELD`, and the show's `sales_status` must not yet be `CLOSED`."

        Design: Corner/state_machines/triggers_with_no_declared_edge_from_the_current_state_are_rejected
        """
        ctx = build.on_sale_show(
            guarantee_cents=700_000,
            expense_cap_cents=1_000_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 400}],
            announce_at="2026-08-01T00:00:00.000Z",
            show=rental_terms(),
            **zero_fee(),
        )
        hold = build.hold(
            ctx["tiers"][0]["id"],
            kind="PROMOTER_HOLD",
            qty=10,
            holder="production office",
        )
        build.set_clock("2026-10-10T06:00:00.000Z")
        performed = validate_success(
            api.perform_show(ctx["show"]["id"], build.accountant)
        )
        assert performed["sales_status"] == "CLOSED"

        validate_error(
            api.release_ticket_hold(hold["id"], build.buyer), E.ERR_INVALID_STATE
        )
        after = build.read_hold(hold["id"])
        assert after["status"] == "HELD"
        assert after["released_by_user_id"] is None

    def test_a_refused_trigger_writes_nothing_anywhere(self, api, build):
        """PRD 2.9: "State legality — `ERR_INVALID_STATE` when the target sits in a non-terminal state from which the requested trigger has no declared transition, including sub-resource guards such as a show's ticketing state or a budget line's own lifecycle state."

        Design: Corner/state_machines/triggers_with_no_declared_edge_from_the_current_state_are_rejected
        """
        ctx = planned_show_with_open_children(build)
        market_before = build.read_market(ctx["market"]["id"])
        artist_before = build.read_artist(ctx["artist"]["id"])
        tier_before = build.read_tier(ctx["tier"]["id"])
        offer_before = build.read_offer(ctx["offer"]["id"])

        validate_error(
            api.perform_show(ctx["show"]["id"], build.accountant), E.ERR_INVALID_STATE
        )
        validate_error(
            api.pause_sales(ctx["show"]["id"], "a winter storm warning", build.risk),
            E.ERR_INVALID_STATE,
        )
        validate_error(
            api.resume_sales(ctx["show"]["id"], build.buyer), E.ERR_INVALID_STATE
        )
        validate_error(
            api.accept_offer(
                ctx["offer"]["id"], build.artist_rep(ctx["artist"]["id"])
            ),
            E.ERR_INVALID_STATE,
        )

        assert_unchanged(
            build.read_show(ctx["show"]["id"]),
            ctx["show"],
            ("show_status", "sales_status", "committed_guarantee_cents", "version"),
        )
        assert_unchanged(build.read_offer(ctx["offer"]["id"]), offer_before, ROW_IDENTITY)
        assert_unchanged(build.read_tier(ctx["tier"]["id"]), tier_before, ROW_IDENTITY)
        assert_unchanged(
            build.read_artist(ctx["artist"]["id"]),
            artist_before,
            ("confirmed_show_count", "version"),
        )
        assert_unchanged(
            build.read_market(ctx["market"]["id"]),
            market_before,
            ("committed_guarantee_cents", "exposure_utilization_pct", "risk_posture", "version"),
        )


def cancelled_show_with_terminal_children(build):
    """A CANCELLED show carrying a withdrawn offer, an accepted offer and a released hold."""
    ctx = build.planned_show(show=rental_terms(), **zero_fee(gross_capacity=800))
    ctx["withdrawn_offer"] = build.offer(
        ctx["show"]["id"],
        guarantee_cents=600_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    get_success_data(
        build.api.withdraw_offer(
            ctx["withdrawn_offer"]["id"],
            "the agent moved the routing to another market",
            build.buyer,
        )
    )
    ctx["accepted_offer"] = build.accepted_offer(
        ctx["show"]["id"],
        ctx["artist"]["id"],
        guarantee_cents=700_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    ctx["tier"] = build.tier(
        ctx["show"]["id"], tier_name="GA", price_cents=4_000, allocation_qty=400
    )
    held = build.hold(
        ctx["tier"]["id"], kind="ARTIST_HOLD", qty=10, holder="the act's guest list"
    )
    ctx["hold"] = get_success_data(
        build.api.release_ticket_hold(held["id"], build.buyer)
    )
    ctx["event"] = build.cancellation_event(
        ctx["show"]["id"],
        kind="CANCELLED",
        reason="the tour bus was written off outside town",
    )
    ctx["show"] = build.read_show(ctx["show"]["id"])
    return ctx


def denied_claim_event(build):
    """A pulled date whose insurance claim came back denied, a terminal event state."""
    ctx = build.planned_show(show=rental_terms(), **zero_fee())
    event = build.cancellation_event(
        ctx["show"]["id"],
        kind="CANCELLED",
        reason="the building failed its roof inspection",
    )
    event = get_success_data(
        build.api.process_refunds(event["id"], build.accountant)
    )
    event = get_success_data(
        build.api.file_claim(
            event["id"],
            make_risk_officer_headers("u-risk-filer"),
            claim_amount_cents=100_000,
            claim_documentation_ref="CLAIM-88001",
        )
    )
    ctx["event"] = get_success_data(
        build.api.settle_claim(
            event["id"],
            make_risk_officer_headers("u-risk-adjuster"),
            outcome="DENY",
            reason="the policy excluded this peril",
        )
    )
    return ctx


class TestTerminalStatesRejectEveryFurtherTrigger:
    """A row in one of its own terminal states is never moved again."""

    @pytest.mark.parametrize(
        "trigger",
        [
            pytest.param(
                lambda api, build, ctx: api.submit_offer(
                    ctx["withdrawn_offer"]["id"], build.buyer
                ),
                id="submit",
            ),
            pytest.param(
                lambda api, build, ctx: api.withdraw_offer(
                    ctx["withdrawn_offer"]["id"], "one more try at the same row", build.buyer
                ),
                id="withdraw",
            ),
        ],
    )
    def test_a_withdrawn_offer_rejects_every_further_trigger(self, api, build, trigger):
        """PRD 3.2: "`ACCEPTED`, `WITHDRAWN`, `SUPERSEDED` and `EXPIRED` are all terminal — an offer in any of them is never moved again, and is untouched even by the cancellation cascade that withdraws open paper."

        Design: Corner/state_machines/terminal_states_reject_every_further_trigger
        """
        ctx = cancelled_show_with_terminal_children(build)
        before = build.read_offer(ctx["withdrawn_offer"]["id"])
        assert before["status"] == "WITHDRAWN"
        validate_error(trigger(api, build, ctx), E.ERR_ALREADY_TERMINAL)
        assert_unchanged(
            build.read_offer(ctx["withdrawn_offer"]["id"]), before, ROW_IDENTITY
        )

    @pytest.mark.parametrize(
        "trigger",
        [
            pytest.param(
                lambda api, build, ctx: api.accept_offer(
                    ctx["accepted_offer"]["id"], build.artist_rep(ctx["artist"]["id"])
                ),
                id="accept",
            ),
            pytest.param(
                lambda api, build, ctx: api.counter_offer(
                    ctx["accepted_offer"]["id"],
                    build.artist_rep(ctx["artist"]["id"]),
                    counter_guarantee_cents=800_000,
                    counter_note="the act wants to renegotiate after the fact",
                ),
                id="counter",
            ),
            pytest.param(
                lambda api, build, ctx: api.withdraw_offer(
                    ctx["accepted_offer"]["id"],
                    "the promoter tried to pull signed paper",
                    build.buyer,
                ),
                id="withdraw",
            ),
        ],
    )
    def test_an_accepted_offer_rejects_every_further_trigger(self, api, build, trigger):
        """PRD 3.2: "`ACCEPTED`, `WITHDRAWN`, `SUPERSEDED` and `EXPIRED` are all terminal — an offer in any of them is never moved again"

        Design: Corner/state_machines/terminal_states_reject_every_further_trigger
        """
        ctx = cancelled_show_with_terminal_children(build)
        before = build.read_offer(ctx["accepted_offer"]["id"])
        assert before["status"] == "ACCEPTED"
        validate_error(trigger(api, build, ctx), E.ERR_ALREADY_TERMINAL)
        after = build.read_offer(ctx["accepted_offer"]["id"])
        assert_unchanged(after, before, ROW_IDENTITY + ("guarantee_cents", "round_index"))

    @pytest.mark.parametrize(
        "trigger",
        [
            pytest.param(
                lambda api, build, ctx: api.put_show_on_sale(
                    ctx["show"]["id"], build.buyer
                ),
                id="on-sale",
            ),
            pytest.param(
                lambda api, build, ctx: api.perform_show(
                    ctx["show"]["id"], build.accountant
                ),
                id="perform",
            ),
        ],
    )
    def test_a_cancelled_show_rejects_every_further_trigger(self, api, build, trigger):
        """PRD 3.9: "Under `CANCELLED` the show's `show_status` moves to `CANCELLED` (terminal), every budget line whose lifecycle `status` is `ACTIVE` moves to `VOID`"

        Design: Corner/state_machines/terminal_states_reject_every_further_trigger
        """
        ctx = cancelled_show_with_terminal_children(build)
        assert ctx["show"]["show_status"] == "CANCELLED"
        validate_error(trigger(api, build, ctx), E.ERR_ALREADY_TERMINAL)
        after = build.read_show(ctx["show"]["id"])
        assert after["show_status"] == "CANCELLED"
        assert after["sales_status"] == "CLOSED"
        assert_unchanged(after, ctx["show"], ("version", "updated_at"))

    @pytest.mark.parametrize(
        "trigger",
        [
            pytest.param(
                lambda api, build, ctx: api.release_ticket_hold(
                    ctx["hold"]["id"], build.buyer
                ),
                id="release",
            ),
            pytest.param(
                lambda api, build, ctx: api.convert_hold_to_comp(
                    ctx["hold"]["id"], build.buyer
                ),
                id="convert-to-comp",
            ),
        ],
    )
    def test_a_released_hold_rejects_every_further_trigger(self, api, build, trigger):
        """PRD 3.5: "`RELEASED`, `CONVERTED` and `EXPIRED` are all terminal for a hold."

        Design: Corner/state_machines/terminal_states_reject_every_further_trigger
        """
        ctx = cancelled_show_with_terminal_children(build)
        before = build.read_hold(ctx["hold"]["id"])
        assert before["status"] == "RELEASED"
        validate_error(trigger(api, build, ctx), E.ERR_ALREADY_TERMINAL)
        after = build.read_hold(ctx["hold"]["id"])
        assert_unchanged(after, before, ROW_IDENTITY + ("kind",))

    @pytest.mark.parametrize(
        "trigger",
        [
            pytest.param(
                lambda api, build, ctx: api.settle_claim(
                    ctx["event"]["id"],
                    make_risk_officer_headers("u-risk-adjuster"),
                    outcome="SETTLE",
                    insurer_reference="INS-88002",
                ),
                id="settle-claim",
            ),
            pytest.param(
                lambda api, build, ctx: api.process_refunds(
                    ctx["event"]["id"], build.accountant
                ),
                id="process-refunds",
            ),
        ],
    )
    def test_a_denied_claim_event_rejects_every_further_trigger(
        self, api, build, trigger
    ):
        """PRD 3.9: "`CLAIM_SETTLED`, `CLAIM_DENIED` and `RESCHEDULED` are the event's three terminal states."

        Design: Corner/state_machines/terminal_states_reject_every_further_trigger
        """
        ctx = denied_claim_event(build)
        before = build.read_event(ctx["event"]["id"])
        assert before["status"] == "CLAIM_DENIED"
        validate_error(trigger(api, build, ctx), E.ERR_ALREADY_TERMINAL)
        after = build.read_event(ctx["event"]["id"])
        assert_unchanged(
            after,
            before,
            ROW_IDENTITY
            + ("covered_loss_cents", "insurance_recovery_cents", "unrecovered_cost_cents"),
        )

    def test_refusing_a_terminal_trigger_leaves_the_portfolio_flat(self, api, build):
        """PRD 2.9: "Terminality — `ERR_ALREADY_TERMINAL` when the target already sits in one of its own terminal states. Because a target already in a terminal state is reported here and a target in a non-terminal but wrong state is reported by the preceding rule, the two state errors never compete for the same call."

        Design: Corner/state_machines/terminal_states_reject_every_further_trigger
        """
        ctx = cancelled_show_with_terminal_children(build)
        market_before = build.read_market(ctx["market"]["id"])
        artist_before = build.read_artist(ctx["artist"]["id"])
        tier_before = build.read_tier(ctx["tier"]["id"])

        validate_error(
            api.put_show_on_sale(ctx["show"]["id"], build.buyer), E.ERR_ALREADY_TERMINAL
        )
        validate_error(
            api.accept_offer(
                ctx["accepted_offer"]["id"], build.artist_rep(ctx["artist"]["id"])
            ),
            E.ERR_ALREADY_TERMINAL,
        )
        validate_error(
            api.release_ticket_hold(ctx["hold"]["id"], build.buyer),
            E.ERR_ALREADY_TERMINAL,
        )

        assert_market_exposure(build.read_market(ctx["market"]["id"]), 0, 0, "OPEN")
        assert_unchanged(
            build.read_market(ctx["market"]["id"]), market_before, ("version",)
        )
        assert_unchanged(
            build.read_artist(ctx["artist"]["id"]),
            artist_before,
            ("confirmed_show_count", "version"),
        )
        assert_unchanged(
            build.read_tier(ctx["tier"]["id"]),
            tier_before,
            ROW_IDENTITY + ("held_qty", "comp_qty", "available_qty"),
        )


def on_sale_rental_show(build):
    """An ON_SALE / SELLING show with one 400-seat GA tier and a 600,000 guarantee."""
    return build.on_sale_show(
        tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 400}],
        announce_at="2026-08-01T00:00:00.000Z",
        guarantee_cents=600_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
        show=rental_terms(),
        **zero_fee(gross_capacity=800),
    )


class TestRepeatingASucceededTrigger:
    """Firing the same trigger a second time is refused and no side effect repeats."""

    def test_re_submitting_a_submitted_offer_does_not_restart_the_expiry_clock(
        self, api, build
    ):
        """PRD 3.2: "Sending the paper to the artist side moves the offer `DRAFT → SUBMITTED`, and may only be done while the show is still `PLANNED`. The submission stamps `submitted_at` with the current logical clock and sets `expires_at` to exactly 72 hours — three days — after that instant."

        Design: Corner/state_machines/repeating_a_trigger_after_it_succeeded_is_rejected_without_double_side_effects
        """
        build.set_clock("2026-08-01T00:00:00.000Z")
        ctx = build.planned_show(show=rental_terms(), **zero_fee())
        offer = build.offer(
            ctx["show"]["id"],
            guarantee_cents=700_000,
            deposit_cents=0,
            expense_cap_cents=1_000_000,
        )
        submitted = get_success_data(api.submit_offer(offer["id"], build.buyer))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["round_index"] == 1
        assert_timestamp_equals(submitted["submitted_at"], "2026-08-01T00:00:00.000Z")
        assert_timestamp_equals(submitted["expires_at"], "2026-08-04T00:00:00.000Z")

        build.set_clock("2026-08-01T06:00:00.000Z")
        validate_error(api.submit_offer(offer["id"], build.buyer), E.ERR_INVALID_STATE)

        after = build.read_offer(offer["id"])
        assert after["round_index"] == 1
        assert_timestamp_equals(after["submitted_at"], "2026-08-01T00:00:00.000Z")
        assert_timestamp_equals(after["expires_at"], "2026-08-04T00:00:00.000Z")
        assert_unchanged(after, submitted, ROW_IDENTITY)

    def test_verifying_a_verified_invoice_again_keeps_the_first_verifier(self, api, build):
        """PRD 3.6: "A `TourAccountant` verifies it against the settlement book, moving it `SUBMITTED → VERIFIED` and recording `verified_by_user_id`"

        Design: Corner/state_machines/repeating_a_trigger_after_it_succeeded_is_rejected_without_double_side_effects
        """
        ctx = confirmed_show_with_a_submitted_invoice(build)
        first_verifier = make_tour_accountant_headers("u-acct-first-verifier")
        verified = get_success_data(
            api.verify_vendor_invoice(ctx["invoice"]["id"], first_verifier)
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == first_verifier["X-User-ID"]

        second_verifier = make_tour_accountant_headers("u-acct-second-verifier")
        validate_error(
            api.verify_vendor_invoice(ctx["invoice"]["id"], second_verifier),
            E.ERR_INVALID_STATE,
        )

        after = build.read_invoice(ctx["invoice"]["id"])
        assert after["verified_by_user_id"] == first_verifier["X-User-ID"]
        assert_unchanged(after, verified, ROW_IDENTITY)
        line = build.read_budget_line(ctx["line"]["id"])
        assert line["actual_cents"] == 0
        assert line["variance_cents"] == 0

    def test_pausing_an_already_paused_show_does_not_touch_the_tiers_twice(
        self, api, build
    ):
        """PRD 3.4: "Pausing — available to a `TalentBuyer` or a `RiskOfficer`, and requiring a `reason` — moves `sales_status` `SELLING → PAUSED` and cascades every tier in `ON_SALE` to `PAUSED`, while leaving `show_status` completely untouched at `ON_SALE`."

        Design: Corner/state_machines/repeating_a_trigger_after_it_succeeded_is_rejected_without_double_side_effects
        """
        ctx = on_sale_rental_show(build)
        paused_show = get_success_data(
            api.pause_sales(ctx["show"]["id"], "a severe weather warning", build.risk)
        )
        assert paused_show["sales_status"] == "PAUSED"
        assert paused_show["show_status"] == "ON_SALE"
        paused_tier = build.read_tier(ctx["tiers"][0]["id"])
        assert paused_tier["status"] == "PAUSED"

        validate_error(
            api.pause_sales(ctx["show"]["id"], "the warning was extended", build.risk),
            E.ERR_INVALID_STATE,
        )

        show_after = build.read_show(ctx["show"]["id"])
        assert show_after["sales_status"] == "PAUSED"
        assert show_after["show_status"] == "ON_SALE"
        assert show_after["version"] == paused_show["version"]
        assert_unchanged(build.read_tier(ctx["tiers"][0]["id"]), paused_tier, ROW_IDENTITY)

    def test_putting_an_on_sale_show_on_sale_again_charges_the_guarantee_once(
        self, api, build
    ):
        """PRD 3.4: "Going on sale is a single call by a `TalentBuyer` that advances **both** of a show's status dimensions at once: `show_status` moves `CONFIRMED → ON_SALE` and, in the same request, `sales_status` moves `PRE_SALE → SELLING`."

        Design: Corner/state_machines/repeating_a_trigger_after_it_succeeded_is_rejected_without_double_side_effects
        """
        ctx = on_sale_rental_show(build)
        assert ctx["show"]["show_status"] == "ON_SALE"
        assert ctx["show"]["sales_status"] == "SELLING"
        market_before = build.read_market(ctx["market"]["id"])
        assert_market_exposure(market_before, 600_000, 12.00, "OPEN")

        validate_error(
            api.put_show_on_sale(ctx["show"]["id"], build.buyer), E.ERR_INVALID_STATE
        )

        show_after = build.read_show(ctx["show"]["id"])
        assert show_after["show_status"] == "ON_SALE"
        assert show_after["sales_status"] == "SELLING"
        assert show_after["version"] == ctx["show"]["version"]
        market_after = build.read_market(ctx["market"]["id"])
        assert_market_exposure(market_after, 600_000, 12.00, "OPEN")
        assert_unchanged(market_after, market_before, ("version",))


def both_cancellation_forks(build):
    """One market carrying a POSTPONED date, a CANCELLED date and a PLANNED replacement.

    Both cancellation events are opened and left in `OPENED` so each test can
    walk the fork it cares about.
    """
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(guarantee_exposure_limit_cents=10_000_000)
    artist = build.artist()
    venue = build.venue(
        market["id"],
        gross_capacity=800,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )

    postponed = build.show(
        artist["id"],
        venue["id"],
        **rental_terms(
            150_000,
            event_at="2026-10-10T02:00:00.000Z",
            load_in_at="2026-10-09T14:00:00.000Z",
            load_out_at="2026-10-10T08:00:00.000Z",
            announce_at="2026-08-01T00:00:00.000Z",
        ),
    )
    postponed_offer = build.offer(
        postponed["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=1_000_000,
        deposit_cents=0,
        expense_cap_cents=2_000_000,
    )
    get_success_data(build.api.submit_offer(postponed_offer["id"], build.buyer))
    get_success_data(
        build.api.accept_offer(postponed_offer["id"], build.artist_rep(artist["id"]))
    )
    postponed_tier = build.tier(
        postponed["id"], tier_name="GA", price_cents=5_000, allocation_qty=400
    )
    get_success_data(build.api.put_show_on_sale(postponed["id"], build.buyer))
    build.sell(postponed_tier["id"], 200)

    cancelled = build.show(
        artist["id"],
        venue["id"],
        **rental_terms(
            100_000,
            event_at="2026-10-12T02:00:00.000Z",
            load_in_at="2026-10-11T14:00:00.000Z",
            load_out_at="2026-10-12T08:00:00.000Z",
            announce_at="2026-08-01T00:00:00.000Z",
        ),
    )
    cancelled_offer = build.offer(
        cancelled["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=1_000_000,
        deposit_cents=100_000,
        expense_cap_cents=2_000_000,
    )
    get_success_data(build.api.submit_offer(cancelled_offer["id"], build.buyer))
    get_success_data(
        build.api.accept_offer(cancelled_offer["id"], build.artist_rep(artist["id"]))
    )
    cancelled_line = build.budget_line(
        cancelled["id"],
        category="PRODUCTION",
        description="staging and rigging package",
        budgeted_cents=1_000_000,
        is_artist_deductible=False,
    )
    build.approved_invoice(
        cancelled["id"], cancelled_line["id"], 1_000_000, vendor_name="Cascade Staging"
    )
    cancelled_tier = build.tier(
        cancelled["id"], tier_name="GA", price_cents=5_000, allocation_qty=400
    )
    get_success_data(build.api.put_show_on_sale(cancelled["id"], build.buyer))
    build.sell(cancelled_tier["id"], 100)

    postponed_event = build.cancellation_event(
        postponed["id"],
        kind="POSTPONED",
        reason="the singer needed vocal-cord surgery",
    )
    replacement = build.show(
        artist["id"],
        venue["id"],
        **rental_terms(
            150_000,
            event_at="2026-11-14T02:00:00.000Z",
            load_in_at="2026-11-13T14:00:00.000Z",
            load_out_at="2026-11-14T08:00:00.000Z",
            announce_at="2026-08-01T00:00:00.000Z",
            rescheduled_from_show_id=postponed["id"],
        ),
    )
    cancelled_event = build.cancellation_event(
        cancelled["id"],
        kind="CANCELLED",
        reason="the promoter lost the building for that night",
    )

    return {
        "market": market,
        "artist": artist,
        "venue": venue,
        "postponed_show": build.read_show(postponed["id"]),
        "postponed_tier": build.read_tier(postponed_tier["id"]),
        "postponed_event": postponed_event,
        "cancelled_show": build.read_show(cancelled["id"]),
        "cancelled_tier": build.read_tier(cancelled_tier["id"]),
        "cancelled_line": build.read_budget_line(cancelled_line["id"]),
        "cancelled_event": cancelled_event,
        "replacement_show": replacement,
    }


class TestCancellationEventForks:
    """From OPENED an event takes either the refund path or the reschedule path."""

    def test_processing_refunds_writes_the_three_declared_figures(self, api, build):
        """PRD 3.9: "`refunded_ticket_count` is the show's `paid_tickets_sold` plus its `transferred_in_paid_tickets`. And `unrecovered_cost_cents` — the insurable base — is the sum of `settlement_expense_cents` across the show's budget lines whose lifecycle `status` is `ACTIVE` or `VOID`, plus the accepted offer's `deposit_cents`."

        Design: Corner/state_machines/cancellation_event_forks_into_the_reschedule_path_and_the_refund_insurance_path
        """
        ctx = both_cancellation_forks(build)
        assert ctx["cancelled_event"]["status"] == "OPENED"
        assert ctx["cancelled_show"]["refund_liability_cents"] == 500_000
        assert ctx["cancelled_line"]["status"] == "VOID"
        assert ctx["cancelled_line"]["settlement_expense_cents"] == 1_000_000

        event = get_success_data(
            api.process_refunds(ctx["cancelled_event"]["id"], build.accountant)
        )
        assert event["status"] == "REFUNDS_PROCESSED"
        assert event["refund_liability_cents"] == 500_000
        assert event["refunded_ticket_count"] == 100
        assert event["unrecovered_cost_cents"] == 1_100_000

    def test_processing_refunds_zeroes_the_gross_but_keeps_the_ticket_history(
        self, api, build
    ):
        """PRD 3.9: "Processing refunds also zeroes the show's `gross_sold_cents` and `adjusted_gross_cents`, while each tier's `sold_qty` stays put as the historical record."

        Design: Corner/state_machines/cancellation_event_forks_into_the_reschedule_path_and_the_refund_insurance_path
        """
        ctx = both_cancellation_forks(build)
        assert ctx["cancelled_show"]["gross_sold_cents"] == 500_000

        get_success_data(
            api.process_refunds(ctx["cancelled_event"]["id"], build.accountant)
        )

        show = build.read_show(ctx["cancelled_show"]["id"])
        assert show["gross_sold_cents"] == 0
        assert show["adjusted_gross_cents"] == 0
        tier = build.read_tier(ctx["cancelled_tier"]["id"])
        assert tier["sold_qty"] == 100
        assert tier["status"] == "CLOSED"
        assert tier["available_qty"] == 0

    def test_settling_the_claim_covers_the_least_of_three_amounts(self, api, build):
        """PRD 3.9: "`covered_loss_cents` becomes the **smallest** of three amounts: the event's `claim_amount_cents`, its `unrecovered_cost_cents`, and the policy cap of 25,000,000 cents."

        Design: Corner/state_machines/cancellation_event_forks_into_the_reschedule_path_and_the_refund_insurance_path
        """
        ctx = both_cancellation_forks(build)
        event = get_success_data(
            api.process_refunds(ctx["cancelled_event"]["id"], build.accountant)
        )
        event = get_success_data(
            api.file_claim(
                event["id"],
                build.risk,
                claim_amount_cents=1_200_000,
                claim_documentation_ref="CLAIM-70401",
            )
        )
        assert event["status"] == "CLAIM_FILED"
        assert event["filed_by_user_id"] == build.risk["X-User-ID"]

        event = get_success_data(
            api.settle_claim(
                event["id"], build.risk_two, outcome="SETTLE", insurer_reference="INS-70401"
            )
        )
        assert event["status"] == "CLAIM_SETTLED"
        assert event["covered_loss_cents"] == 1_100_000
        assert event["insurance_recovery_cents"] == 600_000
        assert event["unrecovered_cost_cents"] == 1_100_000

    def test_the_reschedule_path_moves_the_money_to_the_replacement_date(
        self, api, build
    ):
        """PRD 3.9: "On success the event records `replacement_show_id`, the original show moves `POSTPONED → RESCHEDULED` (terminal), and the money moves rather than being refunded: the replacement show's `transferred_in_gross_cents` increases by the original's `gross_sold_cents` and its `transferred_in_paid_tickets` increases by the original's `paid_tickets_sold`"

        Design: Corner/state_machines/cancellation_event_forks_into_the_reschedule_path_and_the_refund_insurance_path
        """
        ctx = both_cancellation_forks(build)
        assert ctx["postponed_show"]["show_status"] == "POSTPONED"
        assert ctx["postponed_show"]["gross_sold_cents"] == 1_000_000
        assert ctx["postponed_show"]["refund_liability_cents"] == 1_000_000

        event = get_success_data(
            api.reschedule_cancellation_event(
                ctx["postponed_event"]["id"],
                build.buyer,
                replacement_show_id=ctx["replacement_show"]["id"],
            )
        )
        assert event["status"] == "RESCHEDULED"
        assert event["replacement_show_id"] == ctx["replacement_show"]["id"]
        assert event["refund_liability_cents"] == 0

        original = build.read_show(ctx["postponed_show"]["id"])
        assert original["show_status"] == "RESCHEDULED"
        assert original["refund_liability_cents"] == 0

        replacement = build.read_show(ctx["replacement_show"]["id"])
        assert replacement["transferred_in_gross_cents"] == 1_000_000
        assert replacement["transferred_in_paid_tickets"] == 200
        assert replacement["gross_sold_cents"] == 0
        assert replacement["adjusted_gross_cents"] == 975_000

    def test_the_two_forks_never_rejoin(self, api, build):
        """PRD 3.9: "The **reschedule path** is the alternative fork and skips refunds entirely, which is why `REFUNDS_PROCESSED` and `RESCHEDULED` are mutually unreachable from one another."

        Design: Corner/state_machines/cancellation_event_forks_into_the_reschedule_path_and_the_refund_insurance_path
        """
        ctx = both_cancellation_forks(build)
        rescheduled = get_success_data(
            api.reschedule_cancellation_event(
                ctx["postponed_event"]["id"],
                build.buyer,
                replacement_show_id=ctx["replacement_show"]["id"],
            )
        )
        settled = get_success_data(
            api.process_refunds(ctx["cancelled_event"]["id"], build.accountant)
        )
        settled = get_success_data(
            api.file_claim(
                settled["id"],
                build.risk,
                claim_amount_cents=1_200_000,
                claim_documentation_ref="CLAIM-70402",
            )
        )
        settled = get_success_data(
            api.settle_claim(
                settled["id"], build.risk_two, outcome="SETTLE", insurer_reference="INS-70402"
            )
        )

        validate_error(
            api.process_refunds(rescheduled["id"], build.accountant),
            E.ERR_ALREADY_TERMINAL,
        )
        validate_error(
            api.reschedule_cancellation_event(
                settled["id"],
                build.buyer,
                replacement_show_id=ctx["replacement_show"]["id"],
            ),
            E.ERR_ALREADY_TERMINAL,
        )

        assert_unchanged(
            build.read_event(rescheduled["id"]),
            rescheduled,
            ROW_IDENTITY + ("refunded_ticket_count", "unrecovered_cost_cents"),
        )
        assert_unchanged(
            build.read_event(settled["id"]),
            settled,
            ROW_IDENTITY + ("replacement_show_id", "insurance_recovery_cents"),
        )

    def test_neither_fork_leaves_a_guarantee_on_the_market_book(self, api, build):
        """PRD 3.9: "The show leaves the market's in-scope exposure set either way, so the market's `committed_guarantee_cents` decreases by exactly the show's `committed_guarantee_cents`"

        Design: Corner/state_machines/cancellation_event_forks_into_the_reschedule_path_and_the_refund_insurance_path
        """
        ctx = both_cancellation_forks(build)
        get_success_data(
            api.reschedule_cancellation_event(
                ctx["postponed_event"]["id"],
                build.buyer,
                replacement_show_id=ctx["replacement_show"]["id"],
            )
        )
        event = get_success_data(
            api.process_refunds(ctx["cancelled_event"]["id"], build.accountant)
        )
        event = get_success_data(
            api.file_claim(
                event["id"],
                build.risk,
                claim_amount_cents=1_200_000,
                claim_documentation_ref="CLAIM-70403",
            )
        )
        get_success_data(
            api.settle_claim(
                event["id"], build.risk_two, outcome="SETTLE", insurer_reference="INS-70403"
            )
        )

        market = build.read_market(ctx["market"]["id"])
        assert_market_exposure(market, 0, 0.00, "OPEN")
        assert market["at_risk_guarantee_cents"] == 0
        assert market["settled_show_count"] == 0
        artist = build.read_artist(ctx["artist"]["id"])
        assert artist["confirmed_show_count"] == 0


def cancelled_show_with_mixed_children(build):
    """A CANCELLED show whose children sit in a deliberate mix of states.

    Offers: one already WITHDRAWN, one still DRAFT, one ACCEPTED. Lines: one
    artist-deductible, one not. Tiers: one ON_SALE with sales on it, one added
    afterwards and still DRAFT.
    """
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(guarantee_exposure_limit_cents=10_000_000)
    artist = build.artist()
    venue = build.venue(
        market["id"],
        gross_capacity=800,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        **rental_terms(
            100_000,
            event_at="2026-10-16T02:00:00.000Z",
            load_in_at="2026-10-15T14:00:00.000Z",
            load_out_at="2026-10-16T08:00:00.000Z",
            announce_at="2026-08-01T00:00:00.000Z",
        ),
    )

    withdrawn_offer = build.offer(
        show["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=600_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    withdrawn_offer = get_success_data(
        build.api.withdraw_offer(
            withdrawn_offer["id"], "the agency withdrew the hold", build.buyer
        )
    )
    draft_offer = build.offer(
        show["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=750_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    accepted_offer = build.offer(
        show["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=800_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    get_success_data(build.api.submit_offer(accepted_offer["id"], build.buyer))
    accepted_offer = get_success_data(
        build.api.accept_offer(accepted_offer["id"], build.artist_rep(artist["id"]))
    )

    production_line = build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="staging package",
        budgeted_cents=200_000,
        is_artist_deductible=False,
    )
    marketing_line = build.budget_line(
        show["id"],
        category="MARKETING",
        description="radio buy",
        budgeted_cents=100_000,
        is_artist_deductible=True,
    )

    selling_tier = build.tier(
        show["id"], tier_name="GA", price_cents=5_000, allocation_qty=300
    )
    get_success_data(build.api.put_show_on_sale(show["id"], build.buyer))
    build.sell(selling_tier["id"], 50)
    draft_tier = build.tier(
        show["id"], tier_name="BALCONY", price_cents=3_000, allocation_qty=200
    )

    event = build.cancellation_event(
        show["id"], kind="CANCELLED", reason="the act cancelled the whole leg"
    )

    return {
        "market": market,
        "artist": artist,
        "venue": venue,
        "show": build.read_show(show["id"]),
        "event": event,
        "withdrawn_offer": withdrawn_offer,
        "draft_offer": draft_offer,
        "accepted_offer": accepted_offer,
        "production_line": production_line,
        "marketing_line": marketing_line,
        "selling_tier": selling_tier,
        "draft_tier": draft_tier,
    }


class TestCancellationCascadesToNonTerminalChildrenOnly:
    """The cascade reaches open children and steps over the ones already closed."""

    def test_every_tier_closes_and_keeps_its_sold_history(self, api, build):
        """PRD 3.9: "The show's `sales_status` moves to `CLOSED` and every tier of the show moves to `CLOSED` with `available_qty` 0; no further sale, hold, conversion or price adjustment is accepted afterwards."

        Design: Corner/state_machines/cancellation_cascades_down_to_non_terminal_children_only
        """
        ctx = cancelled_show_with_mixed_children(build)
        assert ctx["show"]["sales_status"] == "CLOSED"
        assert ctx["show"]["refund_liability_cents"] == 250_000

        sold_tier = build.read_tier(ctx["selling_tier"]["id"])
        assert sold_tier["status"] == "CLOSED"
        assert sold_tier["available_qty"] == 0
        assert sold_tier["sold_qty"] == 50
        assert sold_tier["gross_sold_cents"] == 250_000

        late_tier = build.read_tier(ctx["draft_tier"]["id"])
        assert late_tier["status"] == "CLOSED"
        assert late_tier["available_qty"] == 0
        assert late_tier["sold_qty"] == 0

        validate_error_is_one_of(
            api.record_sales(ctx["selling_tier"]["id"], build.buyer, qty=1),
            [E.ERR_INVALID_STATE, E.ERR_ALREADY_TERMINAL],
        )

    def test_every_active_budget_line_is_voided_and_leaves_the_rollups(self, api, build):
        """PRD 3.9: "every budget line whose lifecycle `status` is `ACTIVE` moves to `VOID`"

        Design: Corner/state_machines/cancellation_cascades_down_to_non_terminal_children_only
        """
        ctx = cancelled_show_with_mixed_children(build)
        for line_key in ("production_line", "marketing_line"):
            line = build.read_budget_line(ctx[line_key]["id"])
            assert line["status"] == "VOID", line_key

        show = build.read_show(ctx["show"]["id"])
        assert show["total_budgeted_expense_cents"] == 0
        assert show["total_actual_expense_cents"] == 0

    def test_open_paper_is_withdrawn_and_closed_paper_is_left_alone(self, api, build):
        """PRD 3.2: "`ACCEPTED`, `WITHDRAWN`, `SUPERSEDED` and `EXPIRED` are all terminal — an offer in any of them is never moved again, and is untouched even by the cancellation cascade that withdraws open paper."

        Design: Corner/state_machines/cancellation_cascades_down_to_non_terminal_children_only
        """
        ctx = cancelled_show_with_mixed_children(build)

        draft_after = build.read_offer(ctx["draft_offer"]["id"])
        assert ctx["draft_offer"]["status"] == "DRAFT"
        assert draft_after["status"] == "WITHDRAWN"

        assert_unchanged(
            build.read_offer(ctx["withdrawn_offer"]["id"]),
            ctx["withdrawn_offer"],
            ROW_IDENTITY,
        )
        assert_unchanged(
            build.read_offer(ctx["accepted_offer"]["id"]),
            ctx["accepted_offer"],
            ROW_IDENTITY + ("guarantee_cents",),
        )

    def test_the_cancelled_show_stops_counting_against_the_market_and_the_act(
        self, api, build
    ):
        """PRD 3.9: "The act's `confirmed_show_count` decreases by 1 under both kinds."

        Design: Corner/state_machines/cancellation_cascades_down_to_non_terminal_children_only
        """
        ctx = cancelled_show_with_mixed_children(build)
        assert_market_exposure(build.read_market(ctx["market"]["id"]), 0, 0.00, "OPEN")
        assert build.read_artist(ctx["artist"]["id"])["confirmed_show_count"] == 0


def postponed_and_cancelled_twins(build):
    """Two identically built ON_SALE dates, one then postponed and one cancelled."""
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(guarantee_exposure_limit_cents=10_000_000)
    artist = build.artist()
    venue = build.venue(
        market["id"],
        gross_capacity=800,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    specs = [
        (
            "postponed",
            "POSTPONED",
            "2026-10-10T02:00:00.000Z",
            "2026-10-09T14:00:00.000Z",
            "2026-10-10T08:00:00.000Z",
        ),
        (
            "cancelled",
            "CANCELLED",
            "2026-10-12T02:00:00.000Z",
            "2026-10-11T14:00:00.000Z",
            "2026-10-12T08:00:00.000Z",
        ),
    ]
    twins = {"market": market, "artist": artist, "venue": venue}
    for key, kind, event_at, load_in_at, load_out_at in specs:
        show = build.show(
            artist["id"],
            venue["id"],
            **rental_terms(
                50_000,
                event_at=event_at,
                load_in_at=load_in_at,
                load_out_at=load_out_at,
                announce_at="2026-08-01T00:00:00.000Z",
            ),
        )
        offer = build.offer(
            show["id"],
            deal_structure="FLAT_GUARANTEE",
            guarantee_cents=500_000,
            deposit_cents=0,
            expense_cap_cents=2_000_000,
        )
        get_success_data(build.api.submit_offer(offer["id"], build.buyer))
        get_success_data(
            build.api.accept_offer(offer["id"], build.artist_rep(artist["id"]))
        )
        line = build.budget_line(
            show["id"],
            category="PRODUCTION",
            description="staging package",
            budgeted_cents=200_000,
            is_artist_deductible=False,
        )
        build.approved_invoice(
            show["id"], line["id"], 200_000, vendor_name="Cascade Staging"
        )
        tier = build.tier(
            show["id"], tier_name="GA", price_cents=5_000, allocation_qty=200
        )
        get_success_data(build.api.put_show_on_sale(show["id"], build.buyer))
        build.sell(tier["id"], 20)
        event = build.cancellation_event(
            show["id"], kind=kind, reason="the tour came off the road unexpectedly"
        )
        twins[key] = {
            "show": build.read_show(show["id"]),
            "line": build.read_budget_line(line["id"]),
            "tier": build.read_tier(tier["id"]),
            "event": event,
        }
    return twins


class TestPostponementSparesTheBudgetLines:
    """The two kinds part company on expense: postponement keeps the lines alive."""

    def test_a_postponed_date_keeps_its_lines_active_where_cancellation_voids_them(
        self, api, build
    ):
        """PRD 3.9: "Under `POSTPONED` the show's `show_status` moves to `POSTPONED` and budget lines are explicitly **not** voided, because they carry across to the replacement date."

        Design: Corner/state_machines/postponement_spares_the_budget_lines_that_cancellation_voids
        """
        twins = postponed_and_cancelled_twins(build)
        assert twins["postponed"]["show"]["show_status"] == "POSTPONED"
        assert twins["cancelled"]["show"]["show_status"] == "CANCELLED"

        spared = build.read_budget_line(twins["postponed"]["line"]["id"])
        voided = build.read_budget_line(twins["cancelled"]["line"]["id"])
        assert spared["status"] == "ACTIVE"
        assert voided["status"] == "VOID"
        assert spared["settlement_expense_cents"] == 200_000
        assert voided["settlement_expense_cents"] == 200_000

    def test_only_the_surviving_line_still_counts_in_the_show_rollups(self, api, build):
        """PRD 3.6: "A show's `total_budgeted_expense_cents` is the sum of `budgeted_cents` over its lines whose `status` is not `VOID`, and its `total_actual_expense_cents` is the sum of `actual_cents` over the same set — the invoiced reality."

        Design: Corner/state_machines/postponement_spares_the_budget_lines_that_cancellation_voids
        """
        twins = postponed_and_cancelled_twins(build)
        postponed_show = build.read_show(twins["postponed"]["show"]["id"])
        assert postponed_show["total_budgeted_expense_cents"] == 200_000
        assert postponed_show["total_actual_expense_cents"] == 200_000

        cancelled_show = build.read_show(twins["cancelled"]["show"]["id"])
        assert cancelled_show["total_budgeted_expense_cents"] == 0
        assert cancelled_show["total_actual_expense_cents"] == 0

    def test_both_kinds_close_ticketing_and_owe_the_same_face_value_refund(
        self, api, build
    ):
        """PRD 3.9: "The show's `refund_liability_cents` becomes its `gross_sold_cents` plus its `transferred_in_gross_cents` — every paid ticket is refunded at **face value**, because the ticket tax, the facility fee and the card fees are the promoter's sunk loss and not the buyer's problem — and the event's own `refund_liability_cents` mirrors that figure."

        Design: Corner/state_machines/postponement_spares_the_budget_lines_that_cancellation_voids
        """
        twins = postponed_and_cancelled_twins(build)
        for key in ("postponed", "cancelled"):
            show = build.read_show(twins[key]["show"]["id"])
            assert show["sales_status"] == "CLOSED", key
            assert show["refund_liability_cents"] == 100_000, key
            tier = build.read_tier(twins[key]["tier"]["id"])
            assert tier["status"] == "CLOSED", key
            assert tier["available_qty"] == 0, key
            assert tier["sold_qty"] == 20, key
            assert twins[key]["event"]["refund_liability_cents"] == 100_000, key

    def test_both_kinds_expose_the_same_unrecovered_cost_to_the_insurer(
        self, api, build
    ):
        """PRD 3.9: "Lines already voided by the cancellation still count, because the money was spent before the show died; rejected vendor invoices never reach `settlement_expense_cents` and are therefore never recoverable."

        Design: Corner/state_machines/postponement_spares_the_budget_lines_that_cancellation_voids
        """
        twins = postponed_and_cancelled_twins(build)
        for key in ("postponed", "cancelled"):
            event = get_success_data(
                api.process_refunds(twins[key]["event"]["id"], build.accountant)
            )
            assert event["status"] == "REFUNDS_PROCESSED", key
            assert event["refund_liability_cents"] == 100_000, key
            assert event["refunded_ticket_count"] == 20, key
            assert event["unrecovered_cost_cents"] == 200_000, key
