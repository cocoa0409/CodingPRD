"""Combinatorial formulas: meeting priority scoring and per-holder payout rounding.

Both formulas here combine several inputs whose interaction is non-linear: the
provisional priority score caps one term, gates a penalty on two fields at once
and multiplies the whole sum by a per-type factor, while the dividend payout
rounds every holder's amount before any summation happens.
"""

from test_helpers import (
    ApiClient,
    CONTACT_INSTITUTIONAL_HOLDER,
    CONTACT_RETAIL_HOLDER,
    EVENT_CONFERENCE,
    FUNDING_DECLARED_RATE,
    INSTRUCTION_EXECUTED,
    IR_ADMIN,
    REQUEST_REQUESTED,
    THREAT_ELEVATED,
    THREAT_NONE,
    TIER_1,
    TIER_3,
    TRANSFER_AGENT,
    assertions,
    fixtures,
)

# ---------------------------------------------------------------------------
# Local composite setup for the priority-score world
# ---------------------------------------------------------------------------


def _build_priority_world(api: ApiClient):
    """An open conference plus three contacts that isolate the score's terms.

    ``H1`` is a 12% institutional holder with an NDA and no activist flag; ``H2``
    is the same position but a flagged activist at ``ELEVATED``; ``H3`` is a
    0.05% retail holder with no NDA.
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    company = fixtures.create_company(
        api,
        ticker="PRI",
        legal_name="Priority Industries Inc",
        shares_outstanding=1000000,
    )
    holder_one = fixtures.create_holder(
        api,
        company["id"],
        120000,
        display_name="Holder One",
        email="h1@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        nda_on_file=True,
    )
    holder_two = fixtures.create_holder(
        api,
        company["id"],
        120000,
        display_name="Holder Two",
        email="h2@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        nda_on_file=True,
        activist_flag=True,
    )
    holder_two = fixtures.set_threat_level(api, holder_two["id"], THREAT_ELEVATED)
    holder_three = fixtures.create_holder(
        api,
        company["id"],
        500,
        display_name="Holder Three",
        email="h3@retail.test",
        contact_type=CONTACT_RETAIL_HOLDER,
    )
    event = fixtures.open_event(
        api,
        company["id"],
        event_type=EVENT_CONFERENCE,
        venue_city="Boston",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
        capacity_slots=5,
    )
    return {
        "company": company,
        "event": event,
        "h1": holder_one,
        "h2": holder_two,
        "h3": holder_three,
    }


class TestProvisionalPriorityScoreInteraction:
    """The provisional score over three deliberately contrasted contacts."""

    def test_tier_nda_and_capped_engagement_terms_for_an_institutional_holder(
        self, api: ApiClient
    ):
        """PRD §3.8: "Start with tier points read from the contact's `target_tier`: 50 for `TIER_1`, 35 for `TIER_2`, 20 for `TIER_3` and 5 for `UNTIERED`."

        PRD §3.8: "Add 8 when the contact's `nda_on_file` is true, and nothing when it is false."

        PRD §3.8: "Add an engagement term equal to the contact's `ownership_pct` multiplied by 4, rounded half up to 2 decimal places and then capped at 20 — the rounding happening before the term is added, and the cap meaning that any holder above five percent of the register contributes exactly 20."

        PRD §3.8: "Multiply the result by a type multiplier read from the contact's `contact_type`: 1.20 for an `INSTITUTIONAL_HOLDER`, 1.00 for a `SELL_SIDE_ANALYST` and 0.60 for a `RETAIL_HOLDER`."

        PRD §3.8: "The **provisional** variant runs at intake, is written to `provisional_priority_score`, uses the contact as it stands at intake, and its lead-time bonus is always zero."

        Design: Difficulty/combinatorial_formula/meeting_priority_nonlinear_tier_type_and_penalty_interaction
        """
        world = _build_priority_world(api)
        holder = fixtures.read_contact(api, world["h1"]["id"])
        assertions.assert_contact(holder, target_tier=TIER_1, threat_level=THREAT_NONE)
        assert holder["ownership_pct"] == assertions.approx_4dp(12.0000)

        request = fixtures.create_meeting_request(
            api,
            world["event"]["id"],
            world["h1"]["id"],
            requested_slot_start="2026-09-01T13:00:00Z",
            requested_slot_end="2026-09-01T13:30:00Z",
        )
        # (50 tier + 8 NDA + min(20, 48.00) engagement + 0 lead) * 1.20 = 93.60
        assertions.assert_meeting_request(
            request,
            status=REQUEST_REQUESTED,
            final_priority_score=None,
            allocated_at=None,
            promoted_from_waitlist=False,
        )
        assert request["provisional_priority_score"] == assertions.approx_2dp(93.60)

    def test_activist_penalty_applies_only_when_flag_and_threat_level_agree(
        self, api: ApiClient
    ):
        """PRD §3.8: "From that sum subtract an activist penalty of 15, applied only when the contact's `activist_flag` is true **and** its `threat_level` is `ELEVATED` or `CRITICAL`; a flagged activist at `NONE` or `WATCH` pays nothing."

        PRD §3.8: "Multiply the result by a type multiplier read from the contact's `contact_type`: 1.20 for an `INSTITUTIONAL_HOLDER`, 1.00 for a `SELL_SIDE_ANALYST` and 0.60 for a `RETAIL_HOLDER`."

        PRD §3.8: "The evaluation order is pinned and consequential: every additive term including the lead bonus is summed first, the floor at zero is applied to the product rather than to the sum, and the single final rounding to 2 decimal places happens last of all."

        Design: Difficulty/combinatorial_formula/meeting_priority_nonlinear_tier_type_and_penalty_interaction
        """
        world = _build_priority_world(api)
        penalised = fixtures.read_contact(api, world["h2"]["id"])
        assertions.assert_contact(
            penalised,
            target_tier=TIER_1,
            activist_flag=True,
            threat_level=THREAT_ELEVATED,
        )

        unpenalised_request = fixtures.create_meeting_request(
            api,
            world["event"]["id"],
            world["h1"]["id"],
            requested_slot_start="2026-09-01T13:00:00Z",
            requested_slot_end="2026-09-01T13:30:00Z",
        )
        penalised_request = fixtures.create_meeting_request(
            api,
            world["event"]["id"],
            world["h2"]["id"],
            requested_slot_start="2026-09-01T14:00:00Z",
            requested_slot_end="2026-09-01T14:30:00Z",
        )
        # The identical 12% position scores (78 - 15) * 1.20 = 75.60 once the
        # penalty's two gates are both open.
        assert penalised_request["provisional_priority_score"] == assertions.approx_2dp(75.60)
        assert unpenalised_request["provisional_priority_score"] == assertions.approx_2dp(93.60)
        assert (
            unpenalised_request["provisional_priority_score"]
            - penalised_request["provisional_priority_score"]
        ) == assertions.approx_2dp(18.00)

    def test_retail_multiplier_and_uncapped_engagement_term_for_a_small_position(
        self, api: ApiClient
    ):
        """PRD §3.8: "Multiply the result by a type multiplier read from the contact's `contact_type`: 1.20 for an `INSTITUTIONAL_HOLDER`, 1.00 for a `SELL_SIDE_ANALYST` and 0.60 for a `RETAIL_HOLDER`."

        PRD §3.8: "Add an engagement term equal to the contact's `ownership_pct` multiplied by 4, rounded half up to 2 decimal places and then capped at 20 — the rounding happening before the term is added, and the cap meaning that any holder above five percent of the register contributes exactly 20."

        PRD §3.2: "From that rounded figure — never from the raw quotient — it derives the outreach tier stored in `target_tier`, evaluated top to bottom with the first matching clause winning: a percentage of at least 5.0 is `TIER_1`; otherwise a percentage of at least 1.0 is `TIER_2`; otherwise any percentage strictly greater than zero is `TIER_3`; and a percentage of exactly zero is `UNTIERED`."

        Design: Difficulty/combinatorial_formula/meeting_priority_nonlinear_tier_type_and_penalty_interaction
        """
        world = _build_priority_world(api)
        retail = fixtures.read_contact(api, world["h3"]["id"])
        assertions.assert_contact(
            retail, target_tier=TIER_3, nda_on_file=False, shares_held=500
        )
        assert retail["ownership_pct"] == assertions.approx_4dp(0.0500)

        request = fixtures.create_meeting_request(
            api,
            world["event"]["id"],
            world["h3"]["id"],
            requested_slot_start="2026-09-01T15:00:00Z",
            requested_slot_end="2026-09-01T15:30:00Z",
        )
        # (20 tier + 0 NDA + 0.20 engagement + 0 lead) * 0.60 = 12.12
        assert request["provisional_priority_score"] == assertions.approx_2dp(12.12)
        assert request["final_priority_score"] is None


# ---------------------------------------------------------------------------
# Local composite setup for the payout-rounding world
# ---------------------------------------------------------------------------


def _build_rounding_world(api: ApiClient):
    """An issuer of 333 / 667 / 1000 shares with an acknowledged 0.4567 dividend.

    Each holder is written one hour further along the logical clock so that the
    ledger's creation-timestamp ordering is unambiguous.
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    company = fixtures.create_company(
        api,
        ticker="RND",
        legal_name="Rounding Order Corp",
        shares_outstanding=1000000,
        dividend_reserve_cents=100000,
    )
    plan = (
        (333, CONTACT_INSTITUTIONAL_HOLDER, "Round Holder One", "r1@funds.test"),
        (667, CONTACT_INSTITUTIONAL_HOLDER, "Round Holder Two", "r2@funds.test"),
        (1000, CONTACT_RETAIL_HOLDER, "Round Holder Three", "r3@retail.test"),
    )
    holders = []
    for index, (shares, contact_type, display_name, email) in enumerate(plan):
        fixtures.set_clock(api, f"2026-08-01T{index:02d}:00:00Z")
        holders.append(
            fixtures.create_holder(
                api,
                company["id"],
                shares,
                display_name=display_name,
                email=email,
                contact_type=contact_type,
            )
        )
    instruction = fixtures.submit_dividend(
        api,
        company["id"],
        record_date="2026-08-15",
        payable_date="2026-08-25",
        declared_rate_cents_per_share=0.4567,
        funding_mode=FUNDING_DECLARED_RATE,
        headers=IR_ADMIN,
    )
    fixtures.set_clock(api, "2026-08-25T00:00:00Z")
    instruction = fixtures.acknowledge_instruction(
        api, instruction["id"], headers=TRANSFER_AGENT
    )
    return company, holders, instruction


class TestPayoutRoundingOrder:
    """Rounding every holder's amount before summing them, not after."""

    def test_per_holder_amounts_are_rounded_before_they_are_summed(self, api: ApiClient):
        """PRD §3.9: "For each payee, the amount is that payee's `shares_held` multiplied by the effective rate and rounded half up to whole cents."

        PRD §3.9: "This rounding order is pinned and it matters: every holder's amount is rounded to whole cents **first** and the rounded amounts are added afterwards."

        PRD §3.9: "Summing the share counts first and rounding the product once is explicitly not the rule and yields a different total."

        PRD §3.9: "The payees are the issuer's contacts whose `contact_type` is `INSTITUTIONAL_HOLDER` or `RETAIL_HOLDER` and whose `shares_held` is strictly greater than zero **as of execution time** — not as of the acknowledgement snapshot — and the ledger rows are written in order of the payees' creation timestamps ascending, never by identifier."

        Design: Difficulty/combinatorial_formula/dividend_per_holder_rounding_before_summation
        """
        company, holders, instruction = _build_rounding_world(api)

        executed = fixtures.execute_instruction(
            api, instruction["id"], headers=TRANSFER_AGENT
        )
        assertions.assert_instruction(
            executed, status=INSTRUCTION_EXECUTED, total_payout_cents=914
        )
        # 2000 * 0.4567 = 913.4, so the rejected sum-then-round order would
        # report 913 rather than 152 + 305 + 457.
        assert executed["total_payout_cents"] != 913
        assertions.assert_payout_ledger(
            executed,
            [
                {"contact_id": holders[0]["id"], "shares_held": 333, "amount_cents": 152},
                {"contact_id": holders[1]["id"], "shares_held": 667, "amount_cents": 305},
                {"contact_id": holders[2]["id"], "shares_held": 1000, "amount_cents": 457},
            ],
        )

    def test_holder_credits_and_issuer_cash_follow_the_rounded_ledger_rows(
        self, api: ApiClient
    ):
        """PRD §3.9: "Finally each ledger row credits that holder's `dividend_received_cents` by the row's `amount_cents` and increments that contact's `version` by 1."

        PRD §3.9: "It then moves the money: the issuer's `dividend_reserve_cents` decreases by `total_payout_cents` while its `dividend_paid_cents` increases by the same figure, with the issuer's `version` incremented by 1."

        PRD §3.9: "First, the total of `dividend_reserve_cents` plus `dividend_paid_cents` is identical before execution, after execution and after reversal — cash is only ever moved between the two accounts, never created or destroyed."

        Design: Difficulty/combinatorial_formula/dividend_per_holder_rounding_before_summation
        """
        company, holders, instruction = _build_rounding_world(api)
        before = fixtures.read_company(api, company["id"])
        assertions.assert_company(
            before, dividend_reserve_cents=100000, dividend_paid_cents=0, version=1
        )

        fixtures.execute_instruction(api, instruction["id"], headers=TRANSFER_AGENT)

        credited = [fixtures.read_contact(api, holder["id"]) for holder in holders]
        assertions.assert_contact(credited[0], dividend_received_cents=152, version=2)
        assertions.assert_contact(credited[1], dividend_received_cents=305, version=2)
        assertions.assert_contact(credited[2], dividend_received_cents=457, version=2)

        after = fixtures.read_company(api, company["id"])
        assertions.assert_company(
            after, dividend_reserve_cents=99086, dividend_paid_cents=914, version=2
        )
        assertions.assert_reserve_plus_paid_unchanged(before, after)
        assertions.assert_holder_credits_match_paid(after, credited)
