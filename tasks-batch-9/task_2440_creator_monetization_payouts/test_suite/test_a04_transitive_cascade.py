"""One transition must propagate along a chain of strictly caused hops."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import (
    assert_balances,
    assert_dimensions,
    assert_instant,
    assert_ledger_sequence,
    assert_no_zero_amount_entries,
    assert_total_count,
)
from test_helpers.constants import (
    APPEAL_UPHELD,
    DEMONETIZED,
    ELIGIBILITY_SUSPENDED,
    ENTRY_ACCRUAL,
    ENTRY_ACCRUAL_RESTORE,
    ENTRY_ACCRUAL_REVERSAL,
    ENTRY_CLAWBACK,
    ENTRY_PAYOUT_DEBIT,
    ENTRY_PAYOUT_FEE,
    ENTRY_PAYOUT_REVERSAL,
    EVENT_ACCRUED,
    EVENT_BELOW_MINIMUM,
    EVENT_CLAWED_BACK,
    EVENT_REVERSED,
    FAILED_CRITERION_POLICY,
    INVESTIGATION_SUBSTANTIATED,
    MONETIZED,
    PAYOUT_STATE_ARREARS,
    PAYOUT_STATE_HOLD,
    PAYOUT_VOIDED,
    RATING_GREEN,
    RATING_RED,
    RATING_SOURCE_APPEAL,
    SOURCE_INVESTIGATION,
    SOURCE_PAYOUT,
    STATEMENT_ADJUSTED,
    STATEMENT_FINALIZED,
    TAX_DRAFT,
)
from test_helpers.fixtures import (
    ads_product,
    august_period,
    close,
    content_item,
    eligible_creator,
    finalize,
    july_period,
    payable_creator,
    post_event,
    refresh_creator,
    statement_for,
    tips_product,
)
from test_helpers.test_users import (
    ADMIN,
    FINANCE,
    REVIEWER,
    REVIEWER_ALT,
    make_creator_headers,
)


def _ready_for_substantiation(api):
    """Two closed periods, one attached payout and one absorbing statement."""
    creator, _profile = payable_creator(api)
    product = tips_product(api)
    july = july_period(api)
    august = august_period(api)
    event_one = post_event(
        api, creator["id"], product["id"], gross_amount_cents=40000,
        occurred_at="2026-07-05T00:00:00Z",
    )
    event_two = post_event(
        api, creator["id"], product["id"], gross_amount_cents=20000,
        occurred_at="2026-07-20T00:00:00Z",
    )
    close(api, july["id"])
    statement_one = finalize(
        api, statement_for(api, creator["id"], july["id"])["id"]
    )
    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    get_success_data(api.set_clock(fac.clock_payload("2026-09-01T00:00:00Z"), ADMIN))
    event_three = post_event(
        api, creator["id"], product["id"], gross_amount_cents=30000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    close(api, august["id"])
    statement_two = finalize(
        api, statement_for(api, creator["id"], august["id"])["id"]
    )
    investigation = get_success_data(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Suspected incentivised-view farm during July.",
                violation_window_start="2026-07-01T00:00:00Z",
                violation_window_end="2026-07-31T23:59:59Z",
                hold_payouts=True,
            ),
            REVIEWER,
        )
    )
    return {
        "creator": creator,
        "payout": payout,
        "statement_one": statement_one,
        "statement_two": statement_two,
        "events": (event_one, event_two, event_three),
        "investigation": investigation,
    }


def _substantiate(api, investigation_id):
    return get_success_data(
        api.substantiate_investigation(
            investigation_id,
            fac.substantiate_payload(
                finding="Confirmed: the July watch time came from a paid view farm."
            ),
            REVIEWER_ALT,
        )
    )


def test_substantiation_claws_back_in_window_events_and_strikes_the_channel(api):
    """Confirming a violation sweeps only the events inside the window.

    The two July events become clawed back and fix a 30000-cent base while the
    August event stays accrued, and the same request records the strike that
    drives eligibility to suspended.

    Design: Difficulty/transitive_cascade/substantiate_investigation_five_hop_clawback_waterfall_cascade
    """
    ctx = _ready_for_substantiation(api)
    assert ctx["statement_one"]["net_payable_cents"] == 30000
    assert ctx["statement_two"]["net_payable_cents"] == 15000
    assert ctx["payout"]["fee_cents"] == 200
    assert ctx["payout"]["amount_cents"] == 29800
    assert ctx["investigation"]["hold_amount_cents"] == 15000
    before = refresh_creator(api, ctx["creator"]["id"])
    assert_dimensions(before, payout_state=PAYOUT_STATE_HOLD)
    assert before["ledger_balance_cents"] == 15000

    resolved = _substantiate(api, ctx["investigation"]["id"])
    assert resolved["state"] == INVESTIGATION_SUBSTANTIATED
    assert resolved["resolved_by_user_id"] == "reviewer-r2"
    assert_instant(resolved["resolved_at"], "2026-09-01T00:00:00Z")
    assert resolved["clawback_base_cents"] == 30000

    one, two, three = ctx["events"]
    for event_id, expected in (
        (one["id"], EVENT_CLAWED_BACK),
        (two["id"], EVENT_CLAWED_BACK),
        (three["id"], EVENT_ACCRUED),
    ):
        rows = validate_success(
            api.list_revenue_events(FINANCE, {"creator_id": ctx["creator"]["id"]})
        )
        match = [r for r in rows if r["id"] == event_id][0]
        assert match["status"] == expected

    creator = refresh_creator(api, ctx["creator"]["id"])
    assert creator["active_strike_count"] == 1
    assert creator["eligibility_status"] == ELIGIBILITY_SUSPENDED
    assert creator["last_evaluation_failed_criteria"] == [FAILED_CRITERION_POLICY]


def test_the_waterfall_absorbs_only_statements_no_payout_has_claimed(api):
    """The attached statement is not a bucket, so half the base is unrecovered.

    Only the unattached August statement absorbs, taking 15000 and turning
    adjusted without its net payable moving, and the 15000-cent shortfall is
    booked as one clawback entry plus stored arrears.

    Design: Difficulty/transitive_cascade/substantiate_investigation_five_hop_clawback_waterfall_cascade
    """
    ctx = _ready_for_substantiation(api)
    resolved = _substantiate(api, ctx["investigation"]["id"])

    assert resolved["clawback_recovered_cents"] == 15000
    assert resolved["clawback_unrecovered_cents"] == 15000

    absorbing = validate_success(
        api.get_statement(ctx["statement_two"]["id"], FINANCE)
    )
    assert absorbing["status"] == STATEMENT_ADJUSTED
    assert absorbing["clawback_applied_cents"] == 15000
    assert absorbing["net_payable_cents"] == 15000

    clawbacks = assert_total_count(
        api.list_ledger_entries(
            ctx["creator"]["id"], FINANCE, {"entry_type": ENTRY_CLAWBACK}
        ),
        1,
    )
    assert clawbacks[0]["amount_cents"] == -15000
    assert clawbacks[0]["source_entity"] == SOURCE_INVESTIGATION
    assert clawbacks[0]["source_id"] == ctx["investigation"]["id"]
    assert refresh_creator(api, ctx["creator"]["id"])[
        "outstanding_clawback_cents"
    ] == 15000


def test_arrears_outranks_the_hold_and_voids_the_pending_payout(api):
    """Stored arrears push the channel past the hold the same case imposed.

    The pending payout is voided with a reversal of the full 30000 it had
    reserved, its statement is freed without being re-swept, no payment failure
    is recorded, and the seven ledger rows leave the balance at 30000.

    Design: Difficulty/transitive_cascade/substantiate_investigation_five_hop_clawback_waterfall_cascade
    """
    ctx = _ready_for_substantiation(api)
    _substantiate(api, ctx["investigation"]["id"])

    creator = refresh_creator(api, ctx["creator"]["id"])
    assert_dimensions(creator, payout_state=PAYOUT_STATE_ARREARS)

    payout = validate_success(api.get_payout(ctx["payout"]["id"], FINANCE))
    assert payout["state"] == PAYOUT_VOIDED
    assert payout["settled_at"] is None

    reversals = assert_total_count(
        api.list_ledger_entries(
            ctx["creator"]["id"], FINANCE, {"entry_type": ENTRY_PAYOUT_REVERSAL}
        ),
        1,
    )
    assert reversals[0]["amount_cents"] == 30000
    assert reversals[0]["source_entity"] == SOURCE_PAYOUT
    assert reversals[0]["source_id"] == ctx["payout"]["id"]

    freed = validate_success(api.get_statement(ctx["statement_one"]["id"], FINANCE))
    assert freed["payout_id"] is None
    assert freed["status"] == STATEMENT_FINALIZED
    assert freed["clawback_applied_cents"] == 0

    assert creator["consecutive_payment_failures"] == 0
    assert_balances(
        creator,
        ledger_balance_cents=30000,
        held_cents=0,
        available_balance_cents=30000,
    )
    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 7)
    assert_ledger_sequence(
        rows,
        [
            (ENTRY_ACCRUAL, 20000),
            (ENTRY_ACCRUAL, 10000),
            (ENTRY_PAYOUT_DEBIT, -29800),
            (ENTRY_PAYOUT_FEE, -200),
            (ENTRY_ACCRUAL, 15000),
            (ENTRY_CLAWBACK, -15000),
            (ENTRY_PAYOUT_REVERSAL, 30000),
        ],
    )
    assert_no_zero_amount_entries(rows)


def _two_accruals_on_one_item(api):
    """One rated item carrying two accrued advertising events."""
    creator = eligible_creator(api, country_code="GB")
    product = ads_product(api)
    july_period(api)
    item = content_item(api, creator["id"])
    first = post_event(
        api, creator["id"], product["id"], gross_amount_cents=10000,
        content_item_id=item["id"], occurred_at="2026-07-05T00:00:00Z",
    )
    second = post_event(
        api, creator["id"], product["id"], gross_amount_cents=5000,
        content_item_id=item["id"], occurred_at="2026-07-06T00:00:00Z",
    )
    assert first["creator_share_cents"] == 8000
    assert second["creator_share_cents"] == 4000
    return creator, item, first, second


def _rate_red(api, item_id):
    return get_success_data(
        api.rate_content_item(
            item_id,
            fac.rate_payload(
                RATING_RED, note="Unlicensed music bed throughout the clip."
            ),
            REVIEWER,
        )
    )


def test_a_red_rating_zeroes_every_accrual_that_item_had_earned(api):
    """Demonetising an item rewrites its events rather than leaving them.

    Both events drop to a zero effective share and a zero creator share and
    become reversed rather than below-minimum, with the punitive rating frozen
    onto each of them.

    Design: Difficulty/transitive_cascade/rate_content_red_three_hop_accrual_reversal_cascade
    """
    creator, item, first, second = _two_accruals_on_one_item(api)

    rated = _rate_red(api, item["id"])
    assert rated["suitability_rating"] == RATING_RED
    assert rated["monetization_state"] == DEMONETIZED
    assert rated["last_rated_by_user_id"] == "reviewer-r1"
    assert_instant(rated["last_rated_at"], "2026-08-01T00:00:00Z")
    assert rated["open_appeal_count"] == 0

    events = validate_success(
        api.list_revenue_events(FINANCE, {"creator_id": creator["id"]})
    )
    by_id = {row["id"]: row for row in events}
    for event_id in (first["id"], second["id"]):
        row = by_id[event_id]
        assert row["status"] == EVENT_REVERSED
        assert row["status"] != EVENT_BELOW_MINIMUM
        assert row["effective_share_bps"] == 0
        assert row["creator_share_cents"] == 0
        assert row["suitability_rating_at_accrual"] == RATING_RED


def test_the_reversal_entries_unwind_the_ledger_in_accrual_order(api):
    """Each zeroed event contributes its own negative entry, oldest first.

    The 8000-cent accrual is reversed down to a running balance of 4000 and the
    4000-cent accrual down to zero, leaving four entries and no empty rows.

    Design: Difficulty/transitive_cascade/rate_content_red_three_hop_accrual_reversal_cascade
    """
    creator, item, _first, _second = _two_accruals_on_one_item(api)
    _rate_red(api, item["id"])

    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 4)
    assert_ledger_sequence(
        rows,
        [
            (ENTRY_ACCRUAL, 8000),
            (ENTRY_ACCRUAL, 4000),
            (ENTRY_ACCRUAL_REVERSAL, -8000),
            (ENTRY_ACCRUAL_REVERSAL, -4000),
        ],
    )
    reversals = [r for r in rows if r["entry_type"] == ENTRY_ACCRUAL_REVERSAL]
    assert [r["balance_after_cents"] for r in reversals] == [4000, 0]
    assert_no_zero_amount_entries(rows)
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 0


def _upheld_appeal(api):
    creator, item, first, second = _two_accruals_on_one_item(api)
    _rate_red(api, item["id"])
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 0
    creator_headers = make_creator_headers(creator["id"])
    appeal = validate_success(
        api.create_appeal(fac.appeal_payload(item["id"]), creator_headers), 201
    )
    get_success_data(api.start_appeal_review(appeal["id"], REVIEWER_ALT))
    decided = get_success_data(
        api.decide_appeal(
            appeal["id"],
            fac.decide_appeal_payload(
                "UPHELD", rationale="The licence covers the music bed."
            ),
            REVIEWER_ALT,
        )
    )
    return creator, item, appeal, decided, first, second


def test_upholding_an_appeal_returns_the_item_to_the_requested_rating(api):
    """A successful appeal writes the rating itself, not a manual override.

    The appeal is upheld by the deciding reviewer at the current instant while
    still at revision round zero, and the item comes back green and monetized
    with the appeal recorded as the source and no manual rater attached.

    Design: Difficulty/transitive_cascade/uphold_appeal_four_hop_accrual_restore_cascade
    """
    _creator, item, _appeal, decided, _first, _second = _upheld_appeal(api)

    assert decided["state"] == APPEAL_UPHELD
    assert decided["decided_by_user_id"] == "reviewer-r2"
    assert_instant(decided["decided_at"], "2026-08-01T00:00:00Z")
    assert decided["revision_round"] == 0

    reloaded = validate_success(api.get_content_item(item["id"], FINANCE))
    assert reloaded["suitability_rating"] == RATING_GREEN
    assert reloaded["monetization_state"] == MONETIZED
    assert reloaded["rating_source"] == RATING_SOURCE_APPEAL
    assert reloaded["last_rated_by_user_id"] is None
    assert reloaded["open_appeal_count"] == 0


def test_the_restored_accruals_are_recomputed_not_merely_re_flagged(api):
    """Every reversed event earns its original share back in ledger order.

    Both events return to accrued at 8000 basis points with their 8000-cent and
    4000-cent shares, two restore entries climb the balance to 12000, and the
    item can no longer be appealed.

    Design: Difficulty/transitive_cascade/uphold_appeal_four_hop_accrual_restore_cascade
    """
    creator, item, _appeal, _decided, first, second = _upheld_appeal(api)

    events = validate_success(
        api.list_revenue_events(FINANCE, {"creator_id": creator["id"]})
    )
    by_id = {row["id"]: row for row in events}
    for event_id, share in ((first["id"], 8000), (second["id"], 4000)):
        row = by_id[event_id]
        assert row["status"] == EVENT_ACCRUED
        assert row["effective_share_bps"] == 8000
        assert row["creator_share_cents"] == share
        assert row["suitability_rating_at_accrual"] == RATING_GREEN

    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 6)
    restores = [r for r in rows if r["entry_type"] == ENTRY_ACCRUAL_RESTORE]
    assert [r["amount_cents"] for r in restores] == [8000, 4000]
    assert [r["balance_after_cents"] for r in restores] == [8000, 12000]
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 12000

    validate_error(
        api.create_appeal(
            fac.appeal_payload(item["id"]), make_creator_headers(creator["id"])
        ),
        err.ERR_CONTENT_NOT_APPEALABLE,
        409,
    )


def test_a_policy_strike_bumps_the_version_a_stale_writer_still_holds(api):
    """Recording a strike is itself a write against the channel record.

    The strike suspends the channel on the policy criterion and increments the
    channel version by exactly one, which is what later invalidates a caller
    holding the pre-strike number.

    Design: Difficulty/transitive_cascade/policy_strike_two_hop_cascade_invalidates_creator_version_for_occ
    """
    creator = eligible_creator(api, country_code="US")
    first_version = creator["version"]

    struck = get_success_data(
        api.create_policy_strike(
            creator["id"], fac.policy_strike_payload(), REVIEWER
        )
    )
    assert struck["active_strike_count"] == 1
    assert_instant(struck["last_strike_at"], "2026-08-01T00:00:00Z")
    assert struck["eligibility_status"] == ELIGIBILITY_SUSPENDED
    assert struck["last_evaluation_failed_criteria"] == [FAILED_CRITERION_POLICY]
    # One on-demand evaluation made the channel eligible; the strike's second
    # hop re-runs the evaluation and "increments `evaluation_count`" (PRD 3.1).
    assert struck["evaluation_count"] == 2
    assert struck["version"] == first_version + 1


def test_the_stale_version_is_refused_and_the_fresh_one_accepted(api):
    """The optimistic check rejects the pre-strike version with no side effect.

    A tax profile submitted against the stale number is refused and nothing is
    stored, while the post-strike number is accepted and creates a draft at the
    backup rate without disturbing the suspension the strike caused.

    Design: Difficulty/transitive_cascade/policy_strike_two_hop_cascade_invalidates_creator_version_for_occ
    """
    creator = eligible_creator(api, country_code="US")
    first_version = creator["version"]
    struck = get_success_data(
        api.create_policy_strike(
            creator["id"], fac.policy_strike_payload(), REVIEWER
        )
    )
    second_version = struck["version"]

    validate_error(
        api.create_tax_profile(
            fac.tax_profile_payload(creator["id"], first_version), FINANCE
        ),
        err.ERR_STALE_CREATOR_VERSION,
        412,
    )
    assert_total_count(
        api.list_tax_profiles(FINANCE, {"creator_id": creator["id"]}), 0
    )
    assert refresh_creator(api, creator["id"])["version"] == second_version

    profile = validate_success(
        api.create_tax_profile(
            fac.tax_profile_payload(creator["id"], second_version), FINANCE
        ),
        201,
    )
    assert profile["status"] == TAX_DRAFT
    assert profile["withholding_rate_bps"] == 2400

    after = refresh_creator(api, creator["id"])
    assert after["version"] == second_version + 1
    assert after["eligibility_status"] == ELIGIBILITY_SUSPENDED
    assert after["active_strike_count"] == 1
