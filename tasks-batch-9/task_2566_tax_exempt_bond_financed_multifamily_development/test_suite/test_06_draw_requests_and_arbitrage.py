"""Construction draws: half-open periods, the arbitrage series, and its undoing.

Every draw both occupies an interval and consumes proceeds, and the two are
policed by different rules that rank differently on the refusal ladder. The
negative-arbitrage series is the domain's one genuinely order-sensitive
calculation: it is re-derived from scratch, in period order, on every funding and
every void, so stored answers must be overwritten rather than adjusted.
"""

from test_helpers import (
    TRUSTEE,
    ApiErrorId,
    assert_draw_accruals,
    assert_fields,
    assert_nulls,
    assert_page,
    assert_par_conservation,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

# Sixty-one whole days, and then sixty-two that begin at the instant the first
# period ends — the touching endpoints the half-open rule permits.
EARLY_PERIOD = {
    "period_start": "2026-09-15T00:00:00Z",
    "period_end": "2026-11-15T00:00:00Z",
}
LATE_PERIOD = {
    "period_start": "2026-11-15T00:00:00Z",
    "period_end": "2027-01-16T00:00:00Z",
}


def _fund_early_draw(api, deal, amount=120000000):
    """Draw 1 over the earlier period, funded on its own first day."""
    fixtures.submit_draw(
        api, deal, draw_number=1, requested_amount_cents=amount, **EARLY_PERIOD
    )
    fixtures.approve_draw(api, deal, 1)
    return fixtures.fund_draw(api, deal, 1)


def _fund_late_draw(api, deal, amount=80000000):
    """Draw 2 over the later period, funded on its own first day."""
    fixtures.submit_draw(
        api, deal, draw_number=2, requested_amount_cents=amount, **LATE_PERIOD
    )
    fixtures.approve_draw(api, deal, 2)
    return fixtures.fund_draw(api, deal, 2)


class TestTheNegativeArbitrageSeries:
    """The series is re-sorted and rewritten on every funding, never appended to."""

    def test_the_series_orders_by_period_start_and_overwrites_the_earlier_answer(
        self, api
    ):
        """The later period is created and funded first, so every other order disagrees.

        While the later draw is alone it accrues against the whole undrawn par for
        its sixty-two days, which is 861,111. When the earlier sixty-one-day draw of
        120,000,000 joins the series, the walk has to re-sort by `period_start`: the
        earlier period now carries the full balance at 847,222 and the later one only
        the 80,000,000 that survives it, at 344,444. Honouring funding order instead
        would give 861,111 + 508,333, and the figure already stored on the later draw
        must be overwritten rather than left standing.

        PRD: "Then the funded draws are ordered by `period_start` ascending with ties broken by `draw_number` ascending — never by `id` and never by `created_at`."
        PRD: "Walking that list with a running total of proceeds already drawn, each draw's accrual is computed from the undrawn balance *before* that draw, which is the issue's `par_amount_cents` less the running total: that undrawn balance is multiplied by the spread in basis points, divided by 10,000, multiplied by the number of whole days in the draw's half-open period from `period_start` up to but not including `period_end`, and divided by a 360-day year."
        PRD: "The whole negative-arbitrage series is re-run over the funded draws, rewriting every funded draw's `negative_arbitrage_accrual_cents` and the issue's `negative_arbitrage_cents`, and the issue's `version` increments by 1."

        Design: Corner/calculations/negative_arbitrage_orders_draws_by_period_start_not_by_the_order_they_were_funded
        """
        deal = fixtures.setup_issued_bond(api)

        late = _fund_late_draw(api, deal)
        assert_fields(
            late, "late_draw", status="FUNDED", negative_arbitrage_accrual_cents=861111
        )
        assert_fields(deal.bond_issue, "bond_issue", negative_arbitrage_cents=861111)

        early = _fund_early_draw(api, deal)
        assert_fields(
            early, "early_draw", status="FUNDED", negative_arbitrage_accrual_cents=847222
        )

        rewritten = validate_success(api.get_draw_request(deal.draw_id(2), TRUSTEE))
        assert_draw_accruals({1: early, 2: rewritten}, {1: 847222, 2: 344444})

        issue = fixtures.read_bond_issue(api, deal)
        assert_fields(
            issue,
            "bond_issue",
            negative_arbitrage_cents=1191666,
            cumulative_funded_cents=200000000,
            undrawn_cents=0,
        )
        assert_par_conservation(issue)
        assert issue["negative_arbitrage_cents"] <= issue[
            "negative_arbitrage_allowance_cents"
        ], "neither funding may be blocked: the series stays inside the allowance"

    def test_a_stale_issue_version_refuses_the_second_draw_and_the_refreshed_token_passes(
        self, api
    ):
        """A sibling draw's funding invalidates a token its owner never touched.

        The concurrency token is checked against the parent issue, not against the
        draw being created, so funding draw 1 moves the issue's version out from
        under a sponsor holding a token read before any of it happened. The refusal
        has to be the version failure alone — the second draw's 80,000,000 fits the
        real undrawn balance exactly — and it must create nothing. Re-reading the
        issue and resubmitting the identical body then succeeds, which is what
        separates a real version check from a rule against second draws.

        PRD: "Creating a construction draw — `POST /draw-requests` — must carry `expected_bond_issue_version` matching the current `version` of the target `BondIssue`. A draw is sized against the undrawn balance the sponsor observed; if another draw has since been funded or voided, the issue's `version` has advanced and the undrawn balance the new draw would consume has moved. Such a request is rejected with `ERR_STALE_BOND_ISSUE_VERSION` (HTTP 412)."
        PRD: "The draw opens in `SUBMITTED` with `approved_amount_cents`, `funding_date`, `rejection_reason` and `void_reason` all null and `negative_arbitrage_accrual_cents` at zero, and the issue's `version` increments by 1."

        Design: Corner/cross_cutting_complexity_layers/stale_bond_issue_version_on_a_second_draw_is_precondition_failed_while_the_refreshed_version_passes
        """
        deal = fixtures.setup_issued_bond(api)
        observed_version = fixtures.bond_issue_version(api, deal)

        funded = _fund_early_draw(api, deal)
        assert_fields(
            funded, "early_draw", status="FUNDED", approved_amount_cents=120000000
        )

        second_body = factories.draw_payload(
            deal.bond_issue_id,
            observed_version,
            draw_number=2,
            period_start="2026-11-15T00:00:00Z",
            period_end="2026-12-15T00:00:00Z",
            requested_amount_cents=80000000,
        )
        validate_error(
            api.create_draw_request(deal.developer_headers, **second_body),
            ApiErrorId.ERR_STALE_BOND_ISSUE_VERSION,
            412,
        )
        assert_page(
            api.list_draw_requests(TRUSTEE, bond_issue_id=deal.bond_issue_id),
            total_count=1,
        )

        refreshed = fixtures.read_bond_issue(api, deal)
        assert refreshed["version"] > observed_version, (
            "funding draw 1 must have advanced the issue version"
        )
        assert_fields(refreshed, "bond_issue", undrawn_cents=80000000)

        second_body["expected_bond_issue_version"] = refreshed["version"]
        retried = validate_success(
            api.create_draw_request(deal.developer_headers, **second_body), 201
        )
        assert_fields(
            retried, "late_draw", status="SUBMITTED", requested_amount_cents=80000000
        )

        after = fixtures.read_bond_issue(api, deal)
        assert after["version"] > refreshed["version"], (
            "the accepted create increments the version, and the refused one did not"
        )


class TestWhichRuleAnswersFirst:
    """Two different category pairs, both answered above the fiscal band."""

    def test_refunding_a_funded_draw_reports_state_not_the_undrawn_shortfall(self, api):
        """A draw funded to the last cent of par, offered for funding a second time.

        Re-funding draw 2 breaks two rules at once: `FUNDED` has no outgoing funding
        transition, and its approved 80,000,000 cannot fit an undrawn balance that is
        now zero. The state band sits above the fiscal band on the refusal ladder, so
        the answer is the 409 and never the 422 — and the replay must leave the draw's
        funding date, the issue's split and the arbitrage total exactly as they were.

        PRD: "The bands, in order, are: authentication and authorization; payload well-formedness; existence of the path entity; existence of referenced foreign keys; optimistic-concurrency version match; entity-state rules; temporal business rules; fiscal business rules; safety business rules; and finally structural constraint rules."
        PRD: "A successful funding moves the draw `APPROVED` → `FUNDED` and stamps `funding_date`."
        PRD: "The approved amount must also still fit the issue's `undrawn_cents` at funding time — several approved-but-unfunded draws can together exceed the undrawn balance precisely because approval does not consume it, and the excess is caught here as `ERR_DRAW_EXCEEDS_UNDRAWN`."

        Design: Difficulty/priority_pair_validation_conflict/refunding_a_funded_draw_reports_state_not_the_undrawn_shortfall
        """
        deal = fixtures.setup_issued_bond(api)
        _fund_early_draw(api, deal)
        _fund_late_draw(api, deal)
        assert_fields(
            deal.bond_issue,
            "bond_issue",
            cumulative_funded_cents=200000000,
            undrawn_cents=0,
            negative_arbitrage_cents=1191666,
        )

        validate_error(
            api.fund_draw_request(
                deal.draw_id(2), TRUSTEE, funding_date="2026-12-01T00:00:00Z"
            ),
            ApiErrorId.ERR_DRAW_STATE_INVALID,
            409,
        )

        unchanged = validate_success(api.get_draw_request(deal.draw_id(2), TRUSTEE))
        assert_fields(unchanged, "late_draw", status="FUNDED")
        assert unchanged["funding_date"].startswith("2026-11-15T00:00:00"), (
            "the refused replay must not restamp the funding date, got {0}".format(
                unchanged["funding_date"]
            )
        )

        issue = fixtures.read_bond_issue(api, deal)
        assert_fields(
            issue,
            "bond_issue",
            cumulative_funded_cents=200000000,
            undrawn_cents=0,
            negative_arbitrage_cents=1191666,
        )
        assert_par_conservation(issue)

    def test_an_overlapping_and_overdrawn_draw_reports_the_period_conflict(self, api):
        """One request that both straddles a funded period and overdraws the issue.

        The requested 150,000,000 is nearly twice the 80,000,000 still undrawn, and
        the period 2026-10-01 to 2026-12-01 strictly overlaps the funded draw's. The
        temporal band outranks the fiscal band, so the period conflict is the answer;
        and because the create is refused, no row appears and the issue's version does
        not move — which is what keeps the sponsor's concurrency token usable.

        PRD: "A new draw's half-open interval, running from its `period_start` inclusive to its `period_end` exclusive, must not strictly overlap the half-open interval of any existing draw of the same issue whose `status` is `SUBMITTED`, `APPROVED` or `FUNDED`; a collision is `ERR_DRAW_PERIOD_OVERLAP`."
        PRD: "The requested amount must also fit inside the issue's `undrawn_cents` at that moment, and an overshoot is `ERR_DRAW_EXCEEDS_UNDRAWN`."

        Design: Difficulty/priority_pair_validation_conflict/overlapping_and_overdrawn_draw_reports_the_period_conflict_not_the_shortfall
        """
        deal = fixtures.setup_issued_bond(api)
        _fund_early_draw(api, deal)
        observed_version = fixtures.bond_issue_version(api, deal)

        validate_error(
            api.create_draw_request(
                deal.developer_headers,
                **factories.draw_payload(
                    deal.bond_issue_id,
                    observed_version,
                    draw_number=2,
                    period_start="2026-10-01T00:00:00Z",
                    period_end="2026-12-01T00:00:00Z",
                    requested_amount_cents=150000000,
                )
            ),
            ApiErrorId.ERR_DRAW_PERIOD_OVERLAP,
            409,
        )

        items, _ = assert_page(
            api.list_draw_requests(TRUSTEE, bond_issue_id=deal.bond_issue_id),
            total_count=1,
        )
        assert [row["draw_number"] for row in items] == [1], (
            "the refused create must not leave a second draw behind"
        )

        issue = fixtures.read_bond_issue(api, deal)
        assert_fields(issue, "bond_issue", undrawn_cents=80000000)
        assert issue["version"] == observed_version, (
            "a refused create must not advance the issue version"
        )


class TestHalfOpenIntervals:
    """Touching endpoints, a straddling refusal, and a vacated interval reused."""

    def test_touching_endpoints_pass_and_a_rejected_interval_becomes_reusable(self, api):
        """Four draw attempts against one issue, none of them ever funded.

        A draw that begins at the exact instant another ends is accepted, because the
        intervals are half-open and carry no buffer. A draw that strictly straddles
        two occupied intervals is refused even though both of those draws are merely
        `SUBMITTED` — occupancy is not about money. And once one of them is rejected
        its interval is vacated, so a fresh draw over that identical interval is
        accepted. The listing then proves the domain order: by period start first,
        with the tie between the two later periods broken by draw number.

        PRD: "Touching endpoints are explicitly fine — a draw that starts exactly when another one ends is accepted — and draws that have reached `REJECTED` or `VOIDED` are ignored entirely, so their intervals become reusable."
        PRD: "rejection moves it `SUBMITTED` → `REJECTED`, which is terminal, stamps the reason and frees the draw's funding period so a later draw may occupy the interval. A rejected draw leaves the issue's `undrawn_cents` completely untouched."
        PRD: "construction draws come back ordered by `period_start` ascending with ties broken by `draw_number` ascending (the same ordering the negative-arbitrage series walks)"

        Design: Difficulty/resource_temporal_overlap/draw_periods_are_half_open_so_touching_endpoints_pass_and_rejected_intervals_are_reusable
        """
        deal = fixtures.setup_issued_bond(api)
        fixtures.submit_draw(
            api, deal, draw_number=1, requested_amount_cents=60000000, **EARLY_PERIOD
        )

        touching = fixtures.submit_draw(
            api, deal, draw_number=2, requested_amount_cents=40000000, **LATE_PERIOD
        )
        assert_fields(touching, "touching_draw", status="SUBMITTED")

        validate_error(
            api.create_draw_request(
                deal.developer_headers,
                **factories.draw_payload(
                    deal.bond_issue_id,
                    fixtures.bond_issue_version(api, deal),
                    draw_number=3,
                    period_start="2026-11-01T00:00:00Z",
                    period_end="2026-12-01T00:00:00Z",
                    requested_amount_cents=10000000,
                )
            ),
            ApiErrorId.ERR_DRAW_PERIOD_OVERLAP,
            409,
        )

        rejected = fixtures.reject_draw(
            api, deal, 2, rejection_reason="requisition package incomplete"
        )
        assert_fields(
            rejected,
            "touching_draw",
            status="REJECTED",
            rejection_reason="requisition package incomplete",
        )

        reused = fixtures.submit_draw(
            api, deal, draw_number=4, requested_amount_cents=40000000, **LATE_PERIOD
        )
        assert_fields(reused, "reusing_draw", status="SUBMITTED")

        items, _ = assert_page(
            api.list_draw_requests(TRUSTEE, bond_issue_id=deal.bond_issue_id),
            total_count=3,
        )
        assert [row["draw_number"] for row in items] == [1, 2, 4], (
            "draws come back by period start, then by draw number"
        )

        issue = fixtures.read_bond_issue(api, deal)
        assert_fields(
            issue,
            "bond_issue",
            cumulative_funded_cents=0,
            undrawn_cents=200000000,
            negative_arbitrage_cents=0,
        )
        assert_par_conservation(issue)


class TestVoidingAFundedDraw:
    """The compensating action, which restores balances the survivors accrued against."""

    def test_voiding_the_first_funded_draw_rebuilds_the_par_split_and_reprices_the_survivor(
        self, api
    ):
        """Two funded draws, then the earlier one is voided and the later gets dearer.

        The par split is the issue's own conserved quantity, and the void has to
        restore it: 200,000,000 was funded plus nothing undrawn, and afterwards it is
        80,000,000 funded plus 120,000,000 undrawn. The arbitrage compensation is not
        a subtraction, because the voided draw leaves the input set entirely — which
        hands its 120,000,000 back to the balance the surviving period accrues
        against, so that survivor's own figure has to rise from 344,444 to 861,111.
        Subtracting the voided accrual from the total would have left 344,444, and the
        surviving funded draw keeps the development under construction.

        PRD: "The void moves the draw `FUNDED` → `VOIDED`, which is terminal, stamps the reason, clears `funding_date` back to null and zeroes the draw's `negative_arbitrage_accrual_cents`. The issue's `cumulative_funded_cents` falls by the approved amount and `undrawn_cents` rises by the same amount."
        PRD: "Then the entire negative-arbitrage series is recomputed over the **surviving** funded draws only: a voided draw leaves the input set altogether rather than having its accrual subtracted, which means every later draw's accrual is recomputed against restored — and therefore larger — undrawn balances."
        PRD: "The issue's `version` increments by 1, and afterwards par must once again equal `cumulative_funded_cents` plus `undrawn_cents`."

        Design: Difficulty/compensating_invariant/voiding_the_first_funded_draw_rebuilds_the_par_split_and_reprices_the_surviving_draw
        """
        deal = fixtures.setup_issued_bond(api)
        _fund_early_draw(api, deal)
        _fund_late_draw(api, deal)
        assert_fields(
            deal.bond_issue,
            "bond_issue",
            cumulative_funded_cents=200000000,
            undrawn_cents=0,
            negative_arbitrage_cents=1191666,
        )
        assert_par_conservation(deal.bond_issue)

        voided = fixtures.void_draw(
            api,
            deal,
            1,
            void_reason="requisition disallowed on audit; proceeds returned to the trustee",
        )
        assert_fields(
            voided,
            "early_draw",
            status="VOIDED",
            negative_arbitrage_accrual_cents=0,
            void_reason="requisition disallowed on audit; proceeds returned to the trustee",
        )
        assert_nulls(voided, ("funding_date",), "early_draw")

        assert_fields(
            deal.bond_issue,
            "bond_issue",
            status="ISSUED",
            cumulative_funded_cents=80000000,
            undrawn_cents=120000000,
            negative_arbitrage_cents=861111,
            negative_arbitrage_allowance_cents=4000000,
        )
        assert_par_conservation(deal.bond_issue)

        survivor = validate_success(api.get_draw_request(deal.draw_id(2), TRUSTEE))
        assert_draw_accruals({2: survivor}, {2: 861111})
        assert_fields(
            survivor, "late_draw", status="FUNDED", approved_amount_cents=80000000
        )
        assert survivor["funding_date"].startswith("2026-11-15T00:00:00"), (
            "the surviving draw keeps its own funding date, got {0}".format(
                survivor["funding_date"]
            )
        )

        assert_fields(
            fixtures.read_project(api, deal),
            "project",
            development_status="UNDER_CONSTRUCTION",
        )
