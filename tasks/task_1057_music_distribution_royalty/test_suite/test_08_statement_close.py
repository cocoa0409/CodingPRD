"""Closing a statement: the provisional/final commission split, the Content-ID bonus,
the two-level allocation waterfall and the payout cascade."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_statement_summary, assert_payout_totals_match_statement_net,
    setup_world, lock_sheets_for_world, setup_reconciled_statement, setup_closed_statement,
    open_statement, ingest_batch, reconcile_statement, close_statement,
    royalty_line_payload, read_statement, read_artist, read_collaborator, list_payouts_for,
    set_clock, create_plan, create_artist, create_active_subscription,
    PERIOD_MAY, PERIOD_JAN, PERIOD_FEB, make_finance_headers, make_artist_headers,
    FIN_RECONCILER, FIN_CLOSER, FIN_APPROVER,
)


def _payout_by_payee(payouts, collaborator_id):
    matches = [p for p in payouts if p["collaborator_id"] == collaborator_id]
    assert len(matches) == 1, f"expected exactly 1 payout for {collaborator_id}, got {len(matches)}"
    return matches[0]


def _content_id_world(email, plan_overrides, payees, tracks=None):
    return setup_world(
        plan_overrides=plan_overrides,
        store_overrides={"code": "SPOTIFY", "name": "Spotify", "delivery_lead_days": 5,
                         "surcharge_bps": 0},
        extra_stores=[{"code": "YOUTUBE", "name": "YouTube", "delivery_lead_days": 5,
                       "surcharge_bps": 0}],
        artist_overrides={"email": email},
        payees=payees,
        tracks=tracks,
    )


def test_close_recommissions_content_id_revenue_at_the_flat_rate(api):
    """PRD §3.8: "Step four, however, splits the basis in two. The non-Content-ID gross — the
    statement's `gross_cents` less its `content_id_gross_cents` — is multiplied by the effective
    rate, divided by 10000 and rounded half up to whole cents. Separately, the statement's
    `content_id_gross_cents` is multiplied by 3000 basis points, divided by 10000 and rounded half
    up to whole cents; Content-ID revenue is commissioned at that flat 3000-basis-point rate
    rather than at the artist's plan rate. The two rounded amounts are then added together to give
    the raw final figure."
    PRD §3.7: "variant used at reconciliation, the whole of the statement's `gross_cents` is
    commissioned at the effective rate: multiply `gross_cents` by the effective rate, divide by
    10000, and round half up to whole cents."
    PRD §3.8: "any bonus exists: if that figure is at least 200000 cents the bonus rate is 500
    basis points, otherwise if it is at least 50000 cents the bonus rate is 200 basis points,
    otherwise it is 0."
    PRD §3.8: "With those two figures in hand, `net_cents` becomes the statement's `gross_cents`,
    less the final commission, plus the Content-ID bonus."

    Design: Difficulty/dual_variant_calc/statement_provisional_vs_final_commission_divergence
    """
    world = _content_id_world(
        "nova@example.com",
        {"code": "PRO", "name": "Pro", "commission_bps": 1500, "allows_content_id": True},
        payees=[{"name": "Rae", "email": "rae@example.com", "country_code": "US",
                 "tax_form_status": "VERIFIED"},
                {"name": "Milo", "email": "milo@example.com", "country_code": "GB",
                 "tax_form_status": "VERIFIED"}],
        tracks=[{"title": "Dawn", "duration_seconds": 210},
                {"title": "Dusk", "duration_seconds": 195}],
    )
    c1, c2 = world["payees"]
    track_a, track_b = world["tracks"]
    store_spot, store_yt = world["stores"]
    lock_sheets_for_world(world, [[(c1["id"], 6667), (c2["id"], 3333)], [(c1["id"], 10000)]])

    setup_reconciled_statement(world, [
        royalty_line_payload(track_a["id"], store_spot["id"], 400000, "2026-05-10T00:00:00Z",
                             units=1200000),
        royalty_line_payload(track_b["id"], store_yt["id"], 100000, "2026-05-11T00:00:00Z",
                             source="CONTENT_ID", units=300000),
    ])
    provisional = read_statement(world["statement_id"])
    assert provisional["gross_cents"] == 500000
    assert provisional["content_id_gross_cents"] == 100000
    assert provisional["provisional_net_cents"] == 425000

    closed = validate_success(
        api.close_statement(world["statement_id"], make_finance_headers(FIN_CLOSER))
    )

    assert closed["status"] == "CLOSED"
    assert closed["commission_cents"] == 90000, (
        "60000 on the non-Content-ID gross plus 30000 on the Content-ID gross at 3000 bps"
    )
    assert closed["content_id_bonus_cents"] == 2000
    assert closed["net_cents"] == 412000


def test_close_preserves_the_provisional_net_and_reports_the_divergence(api):
    """PRD §3.8: "The value of `provisional_net_cents` recorded at reconciliation is deliberately
    left untouched, so that the divergence between the provisional and final views remains
    reportable after the fact."
    PRD §3.9: "It reports `statement_id`, the statement's `gross_cents` and
    `content_id_gross_cents`, its `commission_cents` and `content_id_bonus_cents`, both
    `provisional_net_cents` and `net_cents`, a `variant_delta_cents` giving the divergence between
    the final net and the provisional net — the final `net_cents` less `provisional_net_cents` —
    and two payout roll-ups: `payout_count`, the number of payouts attached to the statement, and
    `payout_gross_total_cents`, the sum of their `gross_cents`."

    Design: Difficulty/dual_variant_calc/statement_provisional_vs_final_commission_divergence
    """
    world = _content_id_world(
        "nova2@example.com",
        {"code": "PRO", "name": "Pro", "commission_bps": 1500, "allows_content_id": True},
        payees=[{"name": "Rae", "email": "rae@example.com", "country_code": "US",
                 "tax_form_status": "VERIFIED"},
                {"name": "Milo", "email": "milo@example.com", "country_code": "GB",
                 "tax_form_status": "VERIFIED"}],
        tracks=[{"title": "Dawn", "duration_seconds": 210},
                {"title": "Dusk", "duration_seconds": 195}],
    )
    c1, c2 = world["payees"]
    track_a, track_b = world["tracks"]
    store_spot, store_yt = world["stores"]
    lock_sheets_for_world(world, [[(c1["id"], 6667), (c2["id"], 3333)], [(c1["id"], 10000)]])

    setup_closed_statement(world, [
        royalty_line_payload(track_a["id"], store_spot["id"], 400000, "2026-05-10T00:00:00Z",
                             units=1200000),
        royalty_line_payload(track_b["id"], store_yt["id"], 100000, "2026-05-11T00:00:00Z",
                             source="CONTENT_ID", units=300000),
    ])

    stored = read_statement(world["statement_id"])
    assert stored["provisional_net_cents"] == 425000, "the provisional view survives the close"
    assert stored["net_cents"] == 412000

    summary = validate_success(
        api.get_statement_summary(world["statement_id"], make_finance_headers(FIN_CLOSER))
    )
    assert_statement_summary(summary)
    assert summary["variant_delta_cents"] == 412000 - 425000
    assert summary["gross_cents"] == 500000
    assert summary["content_id_gross_cents"] == 100000


def test_two_level_allocation_uses_floor_then_largest_remainder(api):
    """PRD §3.8: "For each share on that sheet, compute the exact rational entitlement as the
    track's allocated cents multiplied by that share's `share_bps` and divided by 10000; take the
    floor as the share's provisional cents; sum those floors and subtract from the track's
    allocation to obtain that track's leftover cents. Order the shares by the fractional part of
    their exact entitlement, largest first, breaking ties first by `share_bps` largest first and
    then by the share's `created_at` earliest first, and hand one additional cent to each of the
    first shares in that order until that track's leftover is exhausted."
    PRD §3.8: "Finally the per-share cents are folded by payee: one payout is created for each
    collaborator holding at least one share in the locked sheets of the statement's participating
    tracks, and its `gross_cents` is the sum of every share amount awarded to that collaborator
    across every track."

    Design: Difficulty/combinatorial_formula/payout_two_level_floor_largest_remainder_rounding_order
    """
    world = setup_world(
        plan_overrides={"code": "MICRO", "name": "Micro", "commission_bps": 1500,
                        "allows_content_id": False, "included_release_slots": 2},
        artist_overrides={"email": "orion@example.com"},
        payees=[{"name": "Ann", "email": "ann@example.com"},
                {"name": "Ben", "email": "ben@example.com"},
                {"name": "Cal", "email": "cal@example.com"}],
    )
    cx, cy, cz = world["payees"]
    lock_sheets_for_world(world, [[(cx["id"], 3333), (cy["id"], 3333), (cz["id"], 3334)]])

    setup_closed_statement(world, [
        royalty_line_payload(world["track"]["id"], world["store"]["id"], 1000,
                             "2026-05-14T00:00:00Z", units=4000),
    ])

    statement = read_statement(world["statement_id"])
    assert statement["commission_cents"] == 150
    assert statement["net_cents"] == 850

    payouts = list_payouts_for(statement_id=world["statement_id"])
    assert _payout_by_payee(payouts, cx["id"])["gross_cents"] == 283
    assert _payout_by_payee(payouts, cy["id"])["gross_cents"] == 283
    assert _payout_by_payee(payouts, cz["id"])["gross_cents"] == 284, (
        "the largest fractional remainder takes the single leftover cent"
    )


def test_allocation_conserves_every_cent_of_the_statement_net(api):
    """PRD §3.8: "The invariant this procedure guarantees is exact: the sum of `gross_cents`
    across all payouts created by a close equals the statement's `net_cents` to the cent, with
    nothing lost and nothing invented."
    PRD §3.9: "It reports `statement_id`, the statement's `gross_cents` and
    `content_id_gross_cents`, its `commission_cents` and `content_id_bonus_cents`, both
    `provisional_net_cents` and `net_cents`, a `variant_delta_cents` giving the divergence between
    the final net and the provisional net — the final `net_cents` less `provisional_net_cents` —
    and two payout roll-ups: `payout_count`, the number of payouts attached to the statement, and
    `payout_gross_total_cents`, the sum of their `gross_cents`."

    Design: Difficulty/combinatorial_formula/payout_two_level_floor_largest_remainder_rounding_order
    """
    world = setup_world(
        plan_overrides={"code": "MICRO", "name": "Micro", "commission_bps": 1500,
                        "allows_content_id": False, "included_release_slots": 2},
        artist_overrides={"email": "orion2@example.com"},
        payees=[{"name": "Ann", "email": "ann@example.com"},
                {"name": "Ben", "email": "ben@example.com"},
                {"name": "Cal", "email": "cal@example.com"}],
    )
    cx, cy, cz = world["payees"]
    lock_sheets_for_world(world, [[(cx["id"], 3333), (cy["id"], 3333), (cz["id"], 3334)]])

    setup_closed_statement(world, [
        royalty_line_payload(world["track"]["id"], world["store"]["id"], 1000,
                             "2026-05-14T00:00:00Z", units=4000),
    ])

    payouts = list_payouts_for(statement_id=world["statement_id"])
    assert_payout_totals_match_statement_net(payouts, 850)

    summary = validate_success(
        api.get_statement_summary(world["statement_id"], make_finance_headers(FIN_CLOSER))
    )
    assert summary["payout_count"] == 3
    assert summary["payout_gross_total_cents"] == 850


def test_commission_cap_limits_the_raw_figure_on_the_first_statement(api):
    """PRD §3.7: "Compute the cap as the statement's `gross_cents` multiplied by 2000 basis points
    and divided by 10000, rounded half up to whole cents — the platform never takes more than a
    fifth of an artist's gross."
    PRD §3.7: "Otherwise the commission is the raw figure from step four, first limited downward
    to the cap by taking the smaller of the two, and then lifted to the floor of 50 cents by
    taking the larger of that result and 50."
    PRD §3.8: "Closing also raises the artist's `lifetime_gross_cents` by the statement's
    `gross_cents`, which is why the loyalty tier of the"

    Design: Difficulty/combinatorial_formula/commission_effective_rate_nested_min_max_with_loyalty_and_surcharge
    """
    world = _content_id_world(
        "lyra@example.com",
        {"code": "HEAVY", "name": "Heavy", "commission_bps": 2500, "allows_content_id": True,
         "included_release_slots": 4},
        payees=[{"name": "Sol", "email": "sol@example.com"}],
    )
    lock_sheets_for_world(world)
    store_spot = world["stores"][0]

    setup_closed_statement(world, [
        royalty_line_payload(world["track"]["id"], store_spot["id"], 120000,
                             "2026-01-10T00:00:00Z", units=400000),
    ], period=PERIOD_JAN)

    statement = read_statement(world["statement_id"])
    assert statement["commission_cents"] == 24000, (
        "the raw 30000 at 2500 bps is limited downward to the 2000-bps cap"
    )
    assert statement["net_cents"] == 96000
    assert read_artist(world["artist_id"])["lifetime_gross_cents"] == 120000


def test_effective_rate_combines_loyalty_discount_and_weighted_store_surcharge(api):
    """PRD §3.7: "Read the artist's `lifetime_gross_cents`, which reflects only statements that
    have already reached `CLOSED` and therefore excludes the statement being worked on. If that
    figure is at least 500000 cents, the loyalty discount is 250 basis points; otherwise if it is
    at least 100000 cents, the discount is 100 basis points; otherwise there is no discount and
    the figure is 0 basis points."
    PRD §3.7: "Otherwise, for every line of the statement, multiply that line's `gross_cents` by
    the `surcharge_bps` of the store that reported it; sum those products across all lines; divide
    the sum by the statement's `gross_cents`; and round the quotient half up to a whole number of
    basis points."
    PRD §3.7: "Take the `commission_bps` of the plan behind the artist's subscription, subtract
    the loyalty discount from step one, and add the weighted surcharge from step two. Clamp the
    outcome to the range 0 to 10000 inclusive: anything below 0 becomes 0, anything above 10000
    becomes 10000."

    Design: Difficulty/combinatorial_formula/commission_effective_rate_nested_min_max_with_loyalty_and_surcharge
    """
    world = setup_world(
        plan_overrides={"code": "HEAVY", "name": "Heavy", "commission_bps": 2500,
                        "allows_content_id": True, "included_release_slots": 4},
        store_overrides={"code": "SPOTIFY", "name": "Spotify", "delivery_lead_days": 5,
                         "surcharge_bps": 0},
        extra_stores=[{"code": "YOUTUBE", "name": "YouTube", "delivery_lead_days": 5,
                       "surcharge_bps": 500}],
        artist_overrides={"email": "lyra2@example.com"},
        payees=[{"name": "Sol", "email": "sol@example.com"}],
    )
    lock_sheets_for_world(world)
    track_id = world["track"]["id"]
    store_spot, store_yt = world["stores"]

    setup_closed_statement(world, [
        royalty_line_payload(track_id, store_spot["id"], 120000, "2026-01-10T00:00:00Z",
                             units=400000),
    ], period=PERIOD_JAN)
    assert read_artist(world["artist_id"])["lifetime_gross_cents"] == 120000

    setup_closed_statement(world, [
        royalty_line_payload(track_id, store_spot["id"], 300000, "2026-02-10T00:00:00Z",
                             units=900000),
        royalty_line_payload(track_id, store_yt["id"], 100000, "2026-02-11T00:00:00Z",
                             source="CONTENT_ID", units=250000),
    ], period=PERIOD_FEB)

    second = read_statement(world["statement_id"])
    assert second["gross_cents"] == 400000
    assert second["provisional_net_cents"] == 320000, (
        "effective rate 2525 bps raises a raw 101000 that the 80000 cap limits"
    )
    assert second["commission_cents"] == 80000
    assert second["content_id_bonus_cents"] == 2000
    assert second["net_cents"] == 322000
    assert read_artist(world["artist_id"])["lifetime_gross_cents"] == 520000


def test_close_materialises_one_payout_per_entitled_payee(api):
    """PRD §3.8: "Finally the per-share cents are folded by payee: one payout is created for each
    collaborator holding at least one share in the locked sheets of the statement's participating
    tracks, and its `gross_cents` is the sum of every share amount awarded to that collaborator
    across every track."
    PRD §3.7: "Otherwise the commission is the raw figure from step four, first limited downward
    to the cap by taking the smaller of the two, and then lifted to the floor of 50 cents by
    taking the larger of that result and 50."

    Design: Difficulty/transitive_cascade/statement_close_depth_three_payout_autoapproval_cascade
    """
    world = setup_world(
        plan_overrides={"code": "FLAT", "name": "Flat", "commission_bps": 0,
                        "allows_content_id": False, "included_release_slots": 3},
        artist_overrides={"email": "sirius@example.com"},
        payees=[{"name": "Big", "email": "big@example.com"},
                {"name": "Small", "email": "small@example.com"}],
    )
    c_big, c_small = world["payees"]
    lock_sheets_for_world(world, [[(c_big["id"], 8000), (c_small["id"], 2000)]])

    setup_closed_statement(world, [
        royalty_line_payload(world["track"]["id"], world["store"]["id"], 4050,
                             "2026-05-15T00:00:00Z", units=20000),
    ])

    statement = read_statement(world["statement_id"])
    assert statement["commission_cents"] == 50, "a zero plan rate is lifted to the 50-cent floor"
    assert statement["net_cents"] == 4000

    payouts = list_payouts_for(statement_id=world["statement_id"])
    assert len(payouts) == 2
    assert _payout_by_payee(payouts, c_big["id"])["gross_cents"] == 3200
    assert _payout_by_payee(payouts, c_small["id"])["gross_cents"] == 800
    assert read_artist(world["artist_id"])["lifetime_gross_cents"] == 4050


def test_close_auto_approves_only_payouts_at_or_above_the_threshold(api):
    """PRD §3.8: "As the last hop of the cascade, every payout the close just created whose
    `net_cents` is at least 2000 cents moves straight from `PENDING` to `APPROVED` with
    `auto_approved` set true, `approved_by_user_id` deliberately left null, and its `version`
    advanced by 1. Payouts below that threshold remain in `PENDING` awaiting a human."
    PRD §3.8: "Each created payout starts in `PENDING` with `auto_approved` false,
    `approved_by_user_id`, `paid_by_user_id`, `paid_at` and `reversal_reason_code` all null, and
    each raises its collaborator's `pending_payout_cents` by that payout's `net_cents`."

    Design: Difficulty/transitive_cascade/statement_close_depth_three_payout_autoapproval_cascade
    """
    world = setup_world(
        plan_overrides={"code": "FLAT", "name": "Flat", "commission_bps": 0,
                        "allows_content_id": False, "included_release_slots": 3},
        artist_overrides={"email": "sirius2@example.com"},
        payees=[{"name": "Big", "email": "big@example.com"},
                {"name": "Small", "email": "small@example.com"}],
    )
    c_big, c_small = world["payees"]
    lock_sheets_for_world(world, [[(c_big["id"], 8000), (c_small["id"], 2000)]])

    setup_closed_statement(world, [
        royalty_line_payload(world["track"]["id"], world["store"]["id"], 4050,
                             "2026-05-15T00:00:00Z", units=20000),
    ])

    payouts = list_payouts_for(statement_id=world["statement_id"])
    big = _payout_by_payee(payouts, c_big["id"])
    small = _payout_by_payee(payouts, c_small["id"])

    assert big["net_cents"] == 3200
    assert big["status"] == "APPROVED"
    assert big["auto_approved"] is True
    assert big["approved_by_user_id"] is None

    assert small["net_cents"] == 800
    assert small["status"] == "PENDING", "800 cents is below the 2000-cent auto-approval threshold"
    assert small["auto_approved"] is False

    assert read_collaborator(c_big["id"])["pending_payout_cents"] == 3200
    assert read_collaborator(c_small["id"])["pending_payout_cents"] == 800


def test_content_id_bonus_tier_is_selected_at_exactly_fifty_thousand_cents(api):
    """PRD §3.8: "any bonus exists: if that figure is at least 200000 cents the bonus rate is 500
    basis points, otherwise if it is at least 50000 cents the bonus rate is 200 basis points,
    otherwise it is 0."
    PRD §3.8: "The bonus is then that Content-ID gross multiplied by the selected rate, divided by
    10000 and rounded half up to whole cents, and it is stored in `content_id_bonus_cents`."

    Design: Corner/calculations/content_id_bonus_tier_boundary_at_exactly_50000_cents
    """
    world = setup_world(
        plan_overrides={"code": "CIDPLAN", "name": "Cid Plan", "commission_bps": 1000,
                        "allows_content_id": True},
        store_overrides={"code": "YOUTUBE", "name": "YouTube", "delivery_lead_days": 3,
                         "surcharge_bps": 0},
        artist_overrides={"email": "cent@example.com"},
        payees=[{"name": "Cee", "email": "cee@example.com"}],
    )
    lock_sheets_for_world(world)
    track_id, store_yt = world["track"]["id"], world["store"]

    setup_closed_statement(world, [
        royalty_line_payload(track_id, store_yt["id"], 50000, "2026-01-15T00:00:00Z",
                             source="CONTENT_ID", units=200000),
    ], period=PERIOD_JAN)
    at_tier = read_statement(world["statement_id"])
    assert at_tier["content_id_gross_cents"] == 50000
    assert at_tier["commission_cents"] == 10000
    assert at_tier["content_id_bonus_cents"] == 1000
    assert at_tier["net_cents"] == 41000

    setup_closed_statement(world, [
        royalty_line_payload(track_id, store_yt["id"], 49999, "2026-02-15T00:00:00Z",
                             source="CONTENT_ID", units=199990),
    ], period=PERIOD_FEB)
    below_tier = read_statement(world["statement_id"])
    assert below_tier["content_id_gross_cents"] == 49999
    assert below_tier["commission_cents"] == 10000
    assert below_tier["content_id_bonus_cents"] == 0, "one cent short of the tier earns nothing"
    assert below_tier["net_cents"] == 39999


def test_statement_summary_reports_the_variant_delta_and_payout_rollup(api):
    """PRD §3.9: "It reports `statement_id`, the statement's `gross_cents` and
    `content_id_gross_cents`, its `commission_cents` and `content_id_bonus_cents`, both
    `provisional_net_cents` and `net_cents`, a `variant_delta_cents` giving the divergence between
    the final net and the provisional net — the final `net_cents` less `provisional_net_cents` —
    and two payout roll-ups: `payout_count`, the number of payouts attached to the statement, and
    `payout_gross_total_cents`, the sum of their `gross_cents`."
    PRD §3.9: "The roll-up mutates nothing."

    Design: Corner/endpoints/statement_summary_computed_read_reports_variant_delta_and_payout_rollup
    """
    world = _content_id_world(
        "norma3@example.com",
        {"code": "CIDSUM", "name": "Cid Sum", "commission_bps": 1000, "allows_content_id": True},
        payees=[{"name": "Rep", "email": "rep@example.com"}],
    )
    lock_sheets_for_world(world)
    track_id = world["track"]["id"]
    store_spot, store_yt = world["stores"]

    setup_closed_statement(world, [
        royalty_line_payload(track_id, store_spot["id"], 9000, "2026-05-10T00:00:00Z",
                             units=40000),
        royalty_line_payload(track_id, store_yt["id"], 1000, "2026-05-11T00:00:00Z",
                             source="CONTENT_ID", units=5000),
    ])

    summary = validate_success(
        api.get_statement_summary(world["statement_id"], make_artist_headers(world["artist_id"]))
    )

    assert_statement_summary(summary)
    assert summary["gross_cents"] == 10000
    assert summary["content_id_gross_cents"] == 1000
    assert summary["commission_cents"] == 1200
    assert summary["content_id_bonus_cents"] == 0
    assert summary["provisional_net_cents"] == 9000
    assert summary["net_cents"] == 8800
    assert summary["variant_delta_cents"] == 8800 - 9000
    assert summary["payout_count"] == 1
    assert summary["payout_gross_total_cents"] == 8800


def test_the_reconciling_operator_may_not_also_close_the_statement(api):
    """PRD §2.10: "Closing a statement requires that the acting `X-User-ID` differ from the
    `reconciled_by_user_id` recorded when the statement was reconciled."
    PRD §3.8: "It may be performed only on a statement in `RECONCILED` — any other state is
    refused with `ERR_INVALID_STATE` — and only by a `FinanceOps` operator whose `X-User-ID`
    differs from the `reconciled_by_user_id` already recorded on that statement, on pain of
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.8: "The operator who closes is recorded in `closed_by_user_id`, and the statement's
    `version` advances by 1."

    Design: Corner/rbac/same_finance_user_cannot_reconcile_and_close_a_statement
    """
    set_clock("2026-07-01T00:00:00Z")
    plan = create_plan()
    artist = create_artist(email="caelum2@example.com")
    create_active_subscription(artist["id"], plan["id"])
    statement = open_statement(artist["id"], PERIOD_MAY, FIN_RECONCILER)
    reconcile_statement(statement["id"], FIN_RECONCILER)

    same_operator = api.close_statement(statement["id"], make_finance_headers(FIN_RECONCILER))
    validate_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert read_statement(statement["id"])["reconciled_by_user_id"] == FIN_RECONCILER

    closed = validate_success(
        api.close_statement(statement["id"], make_finance_headers(FIN_CLOSER))
    )
    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == FIN_CLOSER


def test_close_response_already_reflects_the_whole_cascade(api):
    """PRD §3.8: "Each created payout starts in `PENDING` with `auto_approved` false,
    `approved_by_user_id`, `paid_by_user_id`, `paid_at` and `reversal_reason_code` all null, and
    each raises its collaborator's `pending_payout_cents` by that payout's `net_cents`."
    PRD §3.8: "As the last hop of the cascade, every payout the close just created whose
    `net_cents` is at least 2000 cents moves straight from `PENDING` to `APPROVED` with
    `auto_approved` set true, `approved_by_user_id` deliberately left null, and its `version`
    advanced by 1."

    Design: Corner/consistency_model/close_response_body_already_reflects_all_cascaded_state
    """
    world = setup_world(
        plan_overrides={"code": "FLAT", "name": "Flat", "commission_bps": 0,
                        "allows_content_id": False, "included_release_slots": 3},
        artist_overrides={"email": "norma4@example.com"},
        payees=[{"name": "Imm", "email": "imm@example.com"}],
    )
    lock_sheets_for_world(world)
    setup_reconciled_statement(world, [
        royalty_line_payload(world["track"]["id"], world["store"]["id"], 4050,
                             "2026-05-20T00:00:00Z", units=20000),
    ])

    closed = validate_success(
        api.close_statement(world["statement_id"], make_finance_headers(FIN_CLOSER))
    )
    assert closed["status"] == "CLOSED"
    assert closed["net_cents"] == 4000

    payee = validate_success(
        api.get_collaborator(world["payee"]["id"], make_finance_headers(FIN_CLOSER))
    )
    assert payee["pending_payout_cents"] == 4000, (
        "the cascade is visible on the very next read"
    )

    payouts = list_payouts_for(statement_id=world["statement_id"])
    assert len(payouts) == 1
    assert payouts[0]["net_cents"] == 4000
    assert payouts[0]["status"] == "APPROVED"
    assert read_artist(world["artist_id"])["lifetime_gross_cents"] == 4050
