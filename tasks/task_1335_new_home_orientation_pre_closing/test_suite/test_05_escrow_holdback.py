"""Escrow holdback: rounding order, clamps, compensating decide symmetry,
provisional vs final amounts at closing, funding gates, and release OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_buyer_headers,
    make_rep_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


class TestEscrowRoundingOrder:
    def _completed_home_with_two_items(self, api):
        """Default-policy community; orientation completed after two
        WARRANTABLE 33333-cent items were decided COMPLETE_AFTER_CLOSING."""
        community, buyer, rep = fx.setup_base()  # multiplier 1.5
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T14:00:00Z")
        fx.start_appointment(appt["id"], rep["id"])
        for title in ("Tile hairline crack A", "Tile hairline crack B"):
            item = fx.create_deficiency(home["id"], appt["id"], rep["id"], title=title)
            fx.classify_deficiency(item["id"], rep["id"],
                                   estimated_repair_cost_cents=33_333)
            fx.decide_deficiency(item["id"], "COMPLETE_AFTER_CLOSING")
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        fx.mark_checklist(appt["id"], rep["id"])
        fx.complete_appointment(appt["id"], rep["id"])
        return home

    def test_per_line_rounding_before_summation(self, api):
        """PRD §3.7: "For each included deficiency item,
        `estimated_repair_cost_cents` is multiplied by the community's
        `holdback_cost_multiplier` and the product is rounded half up to a
        whole cent; only then are the per-item contributions summed."
        PRD §3.7: "Rounding per item before summation — never once at the end —
        and clamping after summation is the contract; the alternate order
        yields different cents and is not."

        Design: Difficulty/combinatorial_formula/escrow_per_line_rounding_order_pinned
        """
        home = self._completed_home_with_two_items(api)
        escrow = fx.get_escrow_for_home(home["id"])
        # round_half_up(33333 * 1.5) = 50000 per line; two lines sum to 100000.
        assert escrow["holdback_amount_cents"] == 100_000, (
            f"per-line rounding must yield 100000 (aggregate order would give 99999), "
            f"got {escrow['holdback_amount_cents']}"
        )

    def test_escrow_activated_by_nonzero_amount(self, api):
        """PRD §3.7: "Provisioning immediately runs the amount recompute, and
        if the computed amount exceeds zero the fresh escrow flips `DRAFT` →
        `ACTIVE` inside the same request."

        Design: Difficulty/combinatorial_formula/escrow_per_line_rounding_order_pinned
        """
        home = self._completed_home_with_two_items(api)
        escrow = fx.get_escrow_for_home(home["id"])
        assert escrow["status"] == "ACTIVE", (
            f"positive provisional amount must activate the escrow, got {escrow['status']}"
        )


class TestEscrowClamps:
    def _completed_home_with_single_item(self, api, cost_cents):
        community, buyer, rep = fx.setup_base()  # default min 50000 / max 1000000
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T14:00:00Z")
        fx.start_appointment(appt["id"], rep["id"])
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"], title="Caulk gap")
        fx.classify_deficiency(item["id"], rep["id"],
                               estimated_repair_cost_cents=cost_cents)
        fx.decide_deficiency(item["id"], "COMPLETE_AFTER_CLOSING")
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        fx.mark_checklist(appt["id"], rep["id"])
        fx.complete_appointment(appt["id"], rep["id"])
        return home

    def test_min_clamp_floor_applied(self, api):
        """PRD §3.7: "Otherwise the amount is clamped: a sum below
        `holdback_min_cents` is raised to that floor, and a sum above
        `holdback_max_cents` is capped at that ceiling."

        Design: Corner/calculations/holdback_min_clamp_floor_applied
        """
        home = self._completed_home_with_single_item(api, 10_000)  # raw 15000
        escrow = fx.get_escrow_for_home(home["id"])
        assert escrow["holdback_amount_cents"] == 50_000, (
            f"raw 15000 must clamp up to the 50000 floor, got {escrow['holdback_amount_cents']}"
        )
        assert escrow["status"] == "ACTIVE"

    def test_max_clamp_ceiling_applied(self, api):
        """PRD §3.7: "Otherwise the amount is clamped: a sum below
        `holdback_min_cents` is raised to that floor, and a sum above
        `holdback_max_cents` is capped at that ceiling."

        Design: Corner/calculations/holdback_max_clamp_ceiling_applied
        """
        home = self._completed_home_with_single_item(api, 1_000_000)  # raw 1500000
        escrow = fx.get_escrow_for_home(home["id"])
        assert escrow["holdback_amount_cents"] == 1_000_000, (
            f"raw 1500000 must clamp down to the 1000000 ceiling, "
            f"got {escrow['holdback_amount_cents']}"
        )


class TestDecideCompensation:
    def test_decide_redecide_amount_conservation(self, api, manager_headers):
        """PRD §3.4: "Both forms recompute the home's open-item counts and
        re-evaluate its readiness, and both drive the escrow recompute of §3.7
        whenever a non-`VOIDED` holdback exists: the escrow flips `DRAFT` →
        `ACTIVE` when the recomputed amount rises above zero and `ACTIVE` →
        `VOIDED` when it returns to zero pre-close. The reversal is
        compensating with exact symmetry — changing an item from after-closing
        to before-closing removes precisely the contribution that the opposite
        change added."

        Design: Difficulty/compensating_invariant/escrow_decide_redecide_amount_conservation
        """
        community, buyer, rep = fx.setup_base(
            community_overrides={"holdback_cost_multiplier": 2.0,
                                 "holdback_min_cents": 1_000,
                                 "holdback_max_cents": 10_000_000}
        )
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T14:00:00Z")
        fx.start_appointment(appt["id"], rep["id"])
        d1 = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                  title="Furnace ignition fault")
        fx.classify_deficiency(d1["id"], rep["id"], estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(d1["id"], "COMPLETE_AFTER_CLOSING")
        d2 = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                  title="Gate latch misaligned")
        fx.classify_deficiency(d2["id"], rep["id"], estimated_repair_cost_cents=10_000)
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        fx.mark_checklist(appt["id"], rep["id"])
        fx.complete_appointment(appt["id"], rep["id"])

        escrow = fx.get_escrow_for_home(home["id"])
        assert escrow["holdback_amount_cents"] == 40_000, (
            f"pre-pair baseline must be 40000, got {escrow['holdback_amount_cents']}"
        )
        fx.decide_deficiency(d2["id"], "COMPLETE_AFTER_CLOSING")
        escrow = get_success_data(api.get_escrow_holdback(escrow["id"], manager_headers))
        assert escrow["holdback_amount_cents"] == 60_000, (
            f"forward decide must add exactly 20000, got {escrow['holdback_amount_cents']}"
        )
        fx.decide_deficiency(d2["id"], "COMPLETE_BEFORE_CLOSING")
        escrow = get_success_data(api.get_escrow_holdback(escrow["id"], manager_headers))
        assert escrow["holdback_amount_cents"] == 40_000, (
            f"compensating decide must restore exactly 40000, got {escrow['holdback_amount_cents']}"
        )
        assert escrow["status"] == "ACTIVE"
        home = get_success_data(api.get_home(home["id"], manager_headers))
        assert home["open_before_closing_count"] == 1, (
            f"d2 must count as open-before, got {home['open_before_closing_count']}"
        )
        assert home["open_after_closing_count"] == 1, (
            f"d1 must count as open-after, got {home['open_after_closing_count']}"
        )

    def test_home_counters_mirror_the_decide_pair(self, api, manager_headers):
        """PRD §3.4: "`open_before_closing_count` tallies the home's items
        whose `resolution` is `COMPLETE_BEFORE_CLOSING` and whose status is one
        of `DECIDED`, `IN_REPAIR`, `READY_FOR_REINSPECTION`, or `VERIFIED`;
        `open_after_closing_count` tallies the same four statuses for
        `COMPLETE_AFTER_CLOSING` items, excluding anything already
        `SIGNED_OFF`."
        PRD §3.4: "Both forms recompute the home's open-item counts and
        re-evaluate its readiness"

        Design: Difficulty/compensating_invariant/escrow_decide_redecide_amount_conservation
        """
        community, buyer, rep = fx.setup_base(
            community_overrides={"holdback_cost_multiplier": 2.0,
                                 "holdback_min_cents": 1_000,
                                 "holdback_max_cents": 10_000_000}
        )
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T14:00:00Z")
        fx.start_appointment(appt["id"], rep["id"])
        d1 = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                  title="Furnace ignition fault")
        fx.classify_deficiency(d1["id"], rep["id"], estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(d1["id"], "COMPLETE_AFTER_CLOSING")
        d2 = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                  title="Gate latch misaligned")
        fx.classify_deficiency(d2["id"], rep["id"], estimated_repair_cost_cents=10_000)
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        fx.mark_checklist(appt["id"], rep["id"])
        fx.complete_appointment(appt["id"], rep["id"])

        home = get_success_data(api.get_home(home["id"], manager_headers))
        assert (home["open_before_closing_count"],
                home["open_after_closing_count"]) == (0, 1), (
            f"baseline counters must be 0/1, got {home['open_before_closing_count']}/"
            f"{home['open_after_closing_count']}"
        )
        fx.decide_deficiency(d2["id"], "COMPLETE_AFTER_CLOSING")
        home = get_success_data(api.get_home(home["id"], manager_headers))
        assert (home["open_before_closing_count"],
                home["open_after_closing_count"]) == (0, 2), (
            f"the forward decide must move counters to 0/2, got "
            f"{home['open_before_closing_count']}/{home['open_after_closing_count']}"
        )
        fx.decide_deficiency(d2["id"], "COMPLETE_BEFORE_CLOSING")
        home = get_success_data(api.get_home(home["id"], manager_headers))
        assert (home["open_before_closing_count"],
                home["open_after_closing_count"]) == (1, 1), (
            f"the compensating decide must restore the conserved split, got "
            f"{home['open_before_closing_count']}/{home['open_after_closing_count']}"
        )


class TestProvisionalVsFinalAtClose:
    def test_final_excludes_signed_off_items(self, api, manager_headers):
        """PRD §3.7: "The **provisional** amount, stored in
        `holdback_amount_cents` and refreshed on every recompute, includes the
        home's after-closing items in `DECIDED`, `IN_REPAIR`,
        `READY_FOR_REINSPECTION`, `VERIFIED`, and `SIGNED_OFF` — signed-off
        items still count. The **final** amount, computed at closing and frozen
        into `final_holdback_cents`, uses the identical formula but excludes
        `SIGNED_OFF` items, so whenever any after-closing item was signed off
        before closing the two amounts diverge."

        Design: Difficulty/dual_variant_calc/escrow_holdback_provisional_vs_final_at_close
        """
        community, buyer, rep = fx.setup_base(
            community_overrides={"holdback_cost_multiplier": 2.0,
                                 "holdback_min_cents": 1_000,
                                 "holdback_max_cents": 10_000_000}
        )
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T14:00:00Z")
        fx.start_appointment(appt["id"], rep["id"])
        d1 = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                  system_key="HVAC", title="Furnace ignition fault")
        fx.classify_deficiency(d1["id"], rep["id"], estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(d1["id"], "COMPLETE_AFTER_CLOSING")
        d2 = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                  system_key="EXTERIOR", title="Gate latch misaligned")
        fx.classify_deficiency(d2["id"], rep["id"], estimated_repair_cost_cents=10_000)
        fx.decide_deficiency(d2["id"], "COMPLETE_AFTER_CLOSING")
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        fx.mark_checklist(appt["id"], rep["id"])
        fx.complete_appointment(appt["id"], rep["id"])

        # d2 repaired, reinspected PASS and signed off by the buyer pre-close.
        fx.move_item_to_ready_for_reinspection(d2["id"], rep["id"])
        fx.verify_item_via_reinspection(d2["id"], home["id"], rep["id"],
                                        "2026-08-26T10:00:00Z")
        fx.sign_off_item(d2["id"], buyer["id"])
        fx.sign_acknowledgment(home["id"], buyer["id"])
        escrow = fx.get_escrow_for_home(home["id"])
        assert escrow["status"] == "ACTIVE"
        assert escrow["holdback_amount_cents"] == 60_000, (
            f"provisional includes the signed-off item: 2.0*(20000+10000)=60000, "
            f"got {escrow['holdback_amount_cents']}"
        )

        closed = fx.close_home(home["id"], funded_holdback_cents=40_000)
        assert closed["status"] == "CLOSED"
        escrow = get_success_data(api.get_escrow_holdback(escrow["id"], manager_headers))
        assert escrow["final_holdback_cents"] == 40_000, (
            f"final excludes SIGNED_OFF d2: 2.0*20000=40000, got {escrow['final_holdback_cents']}"
        )
        assert escrow["holdback_amount_cents"] == 60_000, (
            f"provisional must keep counting the signed-off item, "
            f"got {escrow['holdback_amount_cents']}"
        )
        assert escrow["funded_amount_cents"] == 40_000
        assert escrow["remaining_amount_cents"] == 40_000
        assert escrow["holdback_amount_cents"] != escrow["final_holdback_cents"], (
            "the two variants must diverge for identical underlying item data"
        )

    def test_close_freezes_funding_and_remaining(self, api, manager_headers):
        """PRD §3.7: "Closing freezes `final_holdback_cents`, records
        `funded_amount_cents`, sets `remaining_amount_cents` to the funded
        amount, voids an escrow still in `DRAFT` whose final amount is zero,
        moves the home `READY_TO_CLOSE` → `CLOSED`, and increments the home's
        `version`."

        Design: Difficulty/dual_variant_calc/escrow_holdback_provisional_vs_final_at_close
        """
        ctx = fx.setup_closed_home_with_escrow()  # final 40000, funded 40000
        assert ctx["home"]["status"] == "CLOSED"
        escrow = ctx["escrow"]
        assert escrow["final_holdback_cents"] == 40_000, (
            f"final must freeze at 2.0*20000=40000, got {escrow['final_holdback_cents']}"
        )
        assert escrow["funded_amount_cents"] == 40_000
        assert escrow["remaining_amount_cents"] == 40_000, (
            f"remaining must equal the funded amount at close, "
            f"got {escrow['remaining_amount_cents']}"
        )
        assert escrow["released_amount_cents"] == 0


class TestClosingFundingGates:
    def test_funding_mismatch_rejected(self, api, manager_headers):
        """PRD §3.7: "When a non-`VOIDED` escrow exists whose final amount
        exceeds zero, the request must carry `funded_holdback_cents` equal to
        that computed final amount, with a mismatch rejected as
        `ERR_HOLDBACK_FUNDING_MISMATCH`"

        Design: Corner/errors/funding_mismatch_at_close_rejected
        """
        community, buyer, rep = fx.setup_base(
            community_overrides={"holdback_cost_multiplier": 2.0,
                                 "holdback_min_cents": 1_000,
                                 "holdback_max_cents": 10_000_000}
        )
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T14:00:00Z")
        fx.start_appointment(appt["id"], rep["id"])
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Furnace fault")
        fx.classify_deficiency(item["id"], rep["id"], estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(item["id"], "COMPLETE_AFTER_CLOSING")
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        fx.mark_checklist(appt["id"], rep["id"])
        fx.complete_appointment(appt["id"], rep["id"])
        fx.sign_acknowledgment(home["id"], buyer["id"])

        resp = api.close_home(home["id"], {"funded_holdback_cents": 99_999},
                              manager_headers)
        validate_error(resp, ApiErrorId.ERR_HOLDBACK_FUNDING_MISMATCH)
        home = get_success_data(api.get_home(home["id"], manager_headers))
        assert home["status"] == "READY_TO_CLOSE", (
            f"failed close must leave the home READY_TO_CLOSE, got {home['status']}"
        )


class TestEscrowRelease:
    def test_flush_drains_remaining_to_full_release(self, api, manager_headers):
        """PRD §3.7: "A flush rule overrides the arithmetic: if after the
        release no after-closing item remains in `DECIDED`, `IN_REPAIR`,
        `READY_FOR_REINSPECTION`, or `VERIFIED`, the entire remaining balance
        is released instead."
        PRD §3.7: "While the remaining balance stays above zero the escrow sits
        in `PARTIALLY_RELEASED`; a release that drains it to zero, including a
        flush, moves it to the terminal `FULLY_RELEASED`."
        PRD §3.7: "Throughout, `remaining_amount_cents` is simply
        `funded_amount_cents` minus `released_amount_cents`."

        Design: Difficulty/boundary_precision_check/escrow_release_zero_remaining_full_release_boundary
        """
        ctx = fx.setup_closed_home_with_escrow()  # escrow funded 40000
        # The sole after-closing item is repaired and signed off post-close.
        fx.move_item_to_ready_for_reinspection(ctx["item"]["id"], ctx["rep"]["id"])
        fx.verify_item_via_reinspection(
            ctx["item"]["id"], ctx["home"]["id"], ctx["rep"]["id"],
            "2026-09-02T10:00:00Z",
        )
        fx.sign_off_item(ctx["item"]["id"], ctx["buyer"]["id"])
        escrow = fx.get_escrow_for_home(ctx["home"]["id"])

        released = validate_success(api.release_escrow_holdback(
            escrow["id"], {"expected_escrow_version": escrow["version"]},
            manager_headers,
        ))
        # Flush: no open after-closing items remain -> entire remaining 40000.
        assert released["remaining_amount_cents"] == 0, (
            f"flush must drain remaining to exactly 0, got {released['remaining_amount_cents']}"
        )
        assert released["status"] == "FULLY_RELEASED"
        assert released["released_amount_cents"] == 40_000
        assert released["funded_amount_cents"] == (
            released["released_amount_cents"] + released["remaining_amount_cents"]
        ), "funded must equal released plus remaining"

    def test_release_marks_consumed_items_holdback_released(self, api, manager_headers):
        """PRD §3.7: "The releasable amount is computed from the home's
        after-closing items that are `SIGNED_OFF` and not yet released, each
        contributing its holdback contribution, consumed oldest sign-off first
        — `signed_off_at` ascending, ties broken by `created_at` ascending —
        with every consumed item flipping `holdback_released` to true and the
        total credited to `released_amount_cents`."

        Design: Difficulty/boundary_precision_check/escrow_release_zero_remaining_full_release_boundary
        """
        ctx = fx.setup_closed_home_with_escrow()  # escrow funded 40000
        fx.move_item_to_ready_for_reinspection(ctx["item"]["id"], ctx["rep"]["id"])
        fx.verify_item_via_reinspection(
            ctx["item"]["id"], ctx["home"]["id"], ctx["rep"]["id"],
            "2026-09-02T10:00:00Z",
        )
        fx.sign_off_item(ctx["item"]["id"], ctx["buyer"]["id"])
        escrow = fx.get_escrow_for_home(ctx["home"]["id"])
        released = validate_success(api.release_escrow_holdback(
            escrow["id"], {"expected_escrow_version": escrow["version"]},
            manager_headers,
        ))
        assert released["remaining_amount_cents"] == 0
        item = get_success_data(
            api.get_deficiency_item(ctx["item"]["id"], manager_headers)
        )
        assert item["holdback_released"] is True, (
            f"the consumed item must flip holdback_released, "
            f"got {item['holdback_released']}"
        )

    def test_second_release_on_terminal_escrow_reports_state_error(self, api, manager_headers):
        """PRD §3.7: "Releasing against a home that has not reached `CLOSED` is
        rejected with `ERR_INVALID_STATE`, as is any attempt on a
        `FULLY_RELEASED` or `VOIDED` escrow."
        PRD §2.8: "When a request would violate several rules at once, the
        server evaluates its gates in a fixed order and reports only the
        earliest failure. ... 7. State — the target entity is in a valid
        from-state for the requested transition; otherwise `ERR_INVALID_STATE`
        (HTTP 409). ... 11. Fiscal gates — the escrow release must have a
        positive releasable amount and closing funding must match the final
        holdback; otherwise `ERR_NO_RELEASABLE_AMOUNT` (HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/release_state_priority_over_fiscal_on_terminal_escrow
        """
        ctx = fx.setup_closed_home_with_escrow()  # escrow funded 40000
        fx.move_item_to_ready_for_reinspection(ctx["item"]["id"], ctx["rep"]["id"])
        fx.verify_item_via_reinspection(
            ctx["item"]["id"], ctx["home"]["id"], ctx["rep"]["id"],
            "2026-09-02T10:00:00Z",
        )
        fx.sign_off_item(ctx["item"]["id"], ctx["buyer"]["id"])
        escrow = fx.get_escrow_for_home(ctx["home"]["id"])

        first = validate_success(api.release_escrow_holdback(
            escrow["id"], {"expected_escrow_version": escrow["version"]},
            manager_headers,
        ))
        assert first["status"] == "FULLY_RELEASED", (
            f"first release must flush to FULLY_RELEASED, got {first['status']}"
        )
        # Second release with the CURRENT version: both the state gate and the
        # fiscal gate fail; the earlier state gate must be reported.
        resp = api.release_escrow_holdback(
            escrow["id"], {"expected_escrow_version": first["version"]},
            manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_release_on_terminal_escrow_changes_nothing(self, api, manager_headers):
        """PRD §3.7: "Releasing against a home that has not reached `CLOSED` is
        rejected with `ERR_INVALID_STATE`, as is any attempt on a
        `FULLY_RELEASED` or `VOIDED` escrow."

        Design: Difficulty/priority_pair_validation_conflict/release_state_priority_over_fiscal_on_terminal_escrow
        """
        ctx = fx.setup_closed_home_with_escrow()  # escrow funded 40000
        fx.move_item_to_ready_for_reinspection(ctx["item"]["id"], ctx["rep"]["id"])
        fx.verify_item_via_reinspection(
            ctx["item"]["id"], ctx["home"]["id"], ctx["rep"]["id"],
            "2026-09-02T10:00:00Z",
        )
        fx.sign_off_item(ctx["item"]["id"], ctx["buyer"]["id"])
        escrow = fx.get_escrow_for_home(ctx["home"]["id"])
        first = validate_success(api.release_escrow_holdback(
            escrow["id"], {"expected_escrow_version": escrow["version"]},
            manager_headers,
        ))
        assert first["status"] == "FULLY_RELEASED"
        assert first["released_amount_cents"] == 40_000

        validate_error(api.release_escrow_holdback(
            escrow["id"], {"expected_escrow_version": first["version"]},
            manager_headers,
        ), ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_escrow_holdback(escrow["id"], manager_headers))
        assert after["status"] == "FULLY_RELEASED"
        assert after["released_amount_cents"] == 40_000, (
            f"the rejected release must not move released_amount_cents, "
            f"got {after['released_amount_cents']}"
        )
        assert after["remaining_amount_cents"] == 0

    def test_stale_escrow_version_rejected_after_partial_release(self, api, manager_headers):
        """PRD §2.7: "Releasing escrow funds — `POST /api/escrow-holdbacks/{id}/release`
        — requires `expected_escrow_version` matching the escrow's current
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412),
        because any decide-driven recompute or prior release advances the
        escrow version and invalidates the amount basis the client saw."
        PRD §3.7: "The releasable amount is computed from the home's
        after-closing items that are `SIGNED_OFF` and not yet released, each
        contributing its holdback contribution, consumed oldest sign-off first"

        Design: Corner/errors/escrow_release_stale_version_rejected
        """
        community, buyer, rep = fx.setup_base(
            community_overrides={"holdback_cost_multiplier": 2.0,
                                 "holdback_min_cents": 1_000,
                                 "holdback_max_cents": 10_000_000}
        )
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T14:00:00Z")
        fx.start_appointment(appt["id"], rep["id"])
        d1 = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                  title="Furnace fault")
        fx.classify_deficiency(d1["id"], rep["id"], estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(d1["id"], "COMPLETE_AFTER_CLOSING")
        d2 = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                  title="Gate latch")
        fx.classify_deficiency(d2["id"], rep["id"], estimated_repair_cost_cents=10_000)
        fx.decide_deficiency(d2["id"], "COMPLETE_AFTER_CLOSING")
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        fx.mark_checklist(appt["id"], rep["id"])
        fx.complete_appointment(appt["id"], rep["id"])
        fx.sign_acknowledgment(home["id"], buyer["id"])
        fx.close_home(home["id"], funded_holdback_cents=60_000)

        # d1 signed off post-close; d2 stays open so the first release is a
        # partial (no flush).
        fx.move_item_to_ready_for_reinspection(d1["id"], rep["id"])
        fx.verify_item_via_reinspection(d1["id"], home["id"], rep["id"],
                                        "2026-09-02T10:00:00Z")
        fx.sign_off_item(d1["id"], buyer["id"])
        escrow = fx.get_escrow_for_home(home["id"])
        stale_version = escrow["version"]

        first = validate_success(api.release_escrow_holdback(
            escrow["id"], {"expected_escrow_version": stale_version}, manager_headers,
        ))
        assert first["status"] == "PARTIALLY_RELEASED", (
            f"one open after-item must keep the escrow partial, got {first['status']}"
        )
        assert first["released_amount_cents"] == 40_000, (
            f"d1 contributes 2.0*20000=40000, got {first['released_amount_cents']}"
        )
        assert first["remaining_amount_cents"] == 20_000

        resp = api.release_escrow_holdback(
            escrow["id"], {"expected_escrow_version": stale_version}, manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        escrow = get_success_data(api.get_escrow_holdback(escrow["id"], manager_headers))
        assert escrow["released_amount_cents"] == 40_000, (
            f"the stale attempt must change nothing, got {escrow['released_amount_cents']}"
        )

    def test_release_with_no_releasable_amount_rejected(self, api, manager_headers):
        """PRD §3.7: "When nothing is releasable — no unreleased signed-off
        items and no flush — the request is rejected with
        `ERR_NO_RELEASABLE_AMOUNT`."

        Design: Corner/errors/release_with_no_releasable_amount_rejected
        """
        ctx = fx.setup_closed_home_with_escrow()  # sole after-item still DECIDED
        escrow = ctx["escrow"]
        resp = api.release_escrow_holdback(
            escrow["id"], {"expected_escrow_version": escrow["version"]},
            manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_RELEASABLE_AMOUNT)
