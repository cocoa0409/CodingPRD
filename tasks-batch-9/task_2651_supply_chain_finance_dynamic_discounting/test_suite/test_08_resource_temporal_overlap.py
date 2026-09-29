"""Depth tests for the ``resource_temporal_overlap`` rule.

Two resources in this contract are booked over intervals, and they take
deliberately opposite views of what an overlap means. A buyer programme is
occupied *exclusively* by its auction windows: the half-open window
``[opens_at, closes_at)`` is inflated by a sixty-minute cooldown on both sides
before the conflict test runs, so an abutting window still collides and only a
gap of exactly the cooldown gets through — and the occupancy filter is
status-scoped, so a `CANCELLED` window stops occupying the programme and hands
its slot back to a fully overlapping replacement.

A funder is booked over *closed* intervals ``[effective_from, effective_to]``
and overlap there is entirely legal; only the summed exposure at a candidate
instant can fail. Two tranches that meet the ceiling exactly coexist, one cent
more is refused, and the same-sized tranche that starts one day past the closed
upper bound sails through — which is what proves overlap was never the thing
being tested. The closed upper bound also means a tranche still counts on its
`effective_to` date and only leaves the pool on the next clock sweep.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_FUNDER_CAPITAL_OVERCOMMITTED,
    ERR_SESSION_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_funder_capital_conserved,
    assert_pagination_meta,
    ids_of,
)
from test_helpers.test_users import (
    PLATFORM_OPS_HEADERS,
    make_buyer_admin_headers,
    make_funder_headers,
)

# ─── Instance 1: exclusive session occupancy ──────────
COOLDOWN_PROGRAM = {
    "name": "Cooldown Programme",
    "program_type": "SUPPLIER_NAMED",
    "max_acceptable_apr_bps": 1200,
    "min_days_early": 5,
    "concentration_cap_pct": 100.00,
    "funding_policy": "SELF_ONLY",
}

COOLDOWN_BUYER = {
    "legal_name": "Cooldown Buyer",
    "credit_limit_cents": 100_000_000,
    "self_funding_enabled": True,
}

# Session A holds 09:00..12:00 on 2026-08-10. The cooldown is sixty minutes, so
# A's inflated occupancy on the right-hand side runs up to but not including
# 12:00 + 60min = 13:00, and on the left-hand side any candidate window whose
# closes_at + 60min is at or before 09:00 — i.e. closing at or before 08:00 —
# is clear of it.
A_OPENS = "2026-08-10T09:00:00Z"
A_CLOSES = "2026-08-10T12:00:00Z"
COOLDOWN_MINUTES = 60

# ─── Instance 2: aggregate funder capacity ────────────
CAPITAL_LIMIT_CENTS = 1_000_000
T1_CENTS = 600_000
# 1000000 - 600000 = 400000 is exactly the headroom T1 leaves, so a second
# tranche of 400000 is admissible at equality and 400001 is one cent too many.
T2_CENTS = CAPITAL_LIMIT_CENTS - T1_CENTS
T2_OVER_CENTS = T2_CENTS + 1
T5_CENTS = 700_000

T1_FROM = "2026-08-01T00:00:00Z"
T1_TO = "2026-08-31T00:00:00Z"
T2_FROM = "2026-08-15T00:00:00Z"
T2_TO = "2026-09-15T00:00:00Z"
# One day past T2's closed upper bound, so T2 no longer covers T5's opening
# instant and the summed exposure there is 0 + 700000 = 700000.
T5_FROM = "2026-09-16T00:00:00Z"
T5_TO = "2026-09-30T00:00:00Z"

STACKING_FUNDER = {
    "legal_name": "Tranche Stacking Fund",
    "capital_limit_cents": CAPITAL_LIMIT_CENTS,
    "min_apr_bps": 500,
    "fee_spread_bps": 0,
    "max_single_invoice_cents": 900_000,
}


def _cooldown_ctx(clock="2026-08-01T00:00:00Z"):
    """One buyer and one OPEN SELF_ONLY programme with no session on it yet, so
    every window in the test is scheduled explicitly."""
    return fx.build_base(
        clock=clock,
        buyer_overrides=dict(COOLDOWN_BUYER),
        program_overrides=dict(COOLDOWN_PROGRAM),
        onboard=False,
        session_window=None,
    )


def _schedule(ctx, opens_at, closes_at):
    """POST /auction-sessions as the programme owner, returning the raw response
    so a conflict can be inspected."""
    return api_client.create_session(
        f.session_payload(ctx.program_id, opens_at, closes_at),
        make_buyer_admin_headers(ctx.buyer_id),
    )


def _sessions_of(ctx, status=None):
    return validate_paginated(
        api_client.list_program_sessions(
            ctx.program_id, make_buyer_admin_headers(ctx.buyer_id), status=status
        )
    )


def _funder_with_t1():
    """The stacking funder registered with a 1000000-cent ceiling and tranche T1
    of 600000 cents already committed over the closed interval
    2026-08-01..2026-08-31."""
    funder = fx.new_funder(**STACKING_FUNDER)
    t1 = fx.add_commitment(
        funder["id"],
        committed_amount_cents=T1_CENTS,
        effective_from=T1_FROM,
        effective_to=T1_TO,
    )
    return funder, t1


def _commit(funder_id, cents, effective_from, effective_to):
    """POST /funders/{id}/commitments as the funder itself, returning the raw
    response so a refusal can be inspected."""
    return api_client.create_commitment(
        funder_id,
        f.commitment_payload(
            committed_amount_cents=cents,
            effective_from=effective_from,
            effective_to=effective_to,
        ),
        make_funder_headers(funder_id),
    )


def _tranches_of(funder_id, status=None):
    return validate_paginated(
        api_client.list_commitments(funder_id, PLATFORM_OPS_HEADERS, status=status)
    )


def _read_funder(funder_id):
    return validate_success(api_client.get_funder(funder_id, PLATFORM_OPS_HEADERS))


def test_session_cooldown_refuses_abutting_and_thirty_minute_gaps_not_sixty():
    """Against session A holding 09:00..12:00, a window opening at exactly 12:00
    conflicts, one opening at 12:30 conflicts, one opening at exactly 13:00 is
    scheduled, and the mirror-image window closing at exactly 08:00 is scheduled
    too — so the cooldown is inflated on both sides and both edges are strict.

    PRD §3.5: "Windows on one programme occupy the timeline exclusively, and they
    must be separated by a cooldown of **one hour**."

    PRD §3.5: "Concretely, a requested window conflicts with an existing
    `SCHEDULED` or `LIVE` session on the same programme when the requested
    `opens_at` falls before the existing window's `closes_at` advanced by sixty
    minutes and, at the same time, the existing window's `opens_at` falls before
    the requested `closes_at` advanced by sixty minutes."

    PRD §3.5: "Two consequences follow from that formulation and both are
    intended: windows that merely abut, where the new `opens_at` equals the
    existing `closes_at`, still conflict; and a gap of exactly sixty minutes
    between the end of one window and the start of the next does not conflict."

    PRD §2.7 check 17: "**Session window exclusivity** — the requested window
    neither overlaps nor falls within 60 minutes of any auction session on the
    same programme whose `status` is `SCHEDULED` or `LIVE`. Otherwise
    `ERR_SESSION_WINDOW_CONFLICT` (409). Applies to `POST /auction-sessions`."

    PRD §3.5: "A new session is persisted in `status` `SCHEDULED` with
    `named_offer_count` at 0 and `clearing_apr_bps` at 0."

    Design: Difficulty/resource_temporal_overlap/session_exclusive_occupancy_with_sixty_minute_cooldown
    """
    ctx = _cooldown_ctx()
    session_a = validate_success(_schedule(ctx, A_OPENS, A_CLOSES), 201)
    assert session_a["status"] == "SCHEDULED", (
        "a fresh window opens in SCHEDULED, got {}".format(session_a["status"])
    )
    assert session_a["named_offer_count"] == 0
    assert session_a["clearing_apr_bps"] == 0, (
        "clearing_apr_bps starts at 0, not null, got {!r}".format(
            session_a["clearing_apr_bps"]
        )
    )
    assert session_a["version"] == 1

    # Abutting: 12:00 < 12:00 + 60min = 13:00 is true, and A's 09:00 < 15:00 +
    # 60min = 16:00 is true, so both halves of the conjunction hold.
    validate_error(
        _schedule(ctx, "2026-08-10T12:00:00Z", "2026-08-10T15:00:00Z"),
        ERR_SESSION_WINDOW_CONFLICT,
        409,
    )

    # A 30-minute gap sits strictly inside the cooldown: 12:30 < 13:00.
    validate_error(
        _schedule(ctx, "2026-08-10T12:30:00Z", "2026-08-10T15:00:00Z"),
        ERR_SESSION_WINDOW_CONFLICT,
        409,
    )

    surviving, surviving_meta = _sessions_of(ctx)
    assert ids_of(surviving) == [session_a["id"]], (
        "a refused schedule must not persist a row, got {}".format(
            ids_of(surviving)
        )
    )
    assert surviving_meta["total_count"] != 3, (
        "both refusals must have left the programme holding A alone"
    )

    # A gap of exactly the cooldown clears it, because 13:00 < 13:00 is false.
    session_d = validate_success(_schedule(ctx, "2026-08-10T13:00:00Z",
                                           "2026-08-10T15:00:00Z"), 201)
    assert session_d["status"] == "SCHEDULED", (
        "a gap of exactly {} minutes must not conflict, got {}".format(
            COOLDOWN_MINUTES, session_d["status"]
        )
    )

    # The mirror image on the earlier side: E closes at 08:00 and A's 09:00 <
    # 08:00 + 60min = 09:00 is false, so the second half of the conjunction
    # fails and there is no conflict with A; nor with D, whose 13:00 is not
    # before 09:00 either.
    session_e = validate_success(_schedule(ctx, "2026-08-10T06:00:00Z",
                                          "2026-08-10T08:00:00Z"), 201)
    assert session_e["status"] == "SCHEDULED"

    rows, meta = _sessions_of(ctx)
    assert ids_of(rows) == [session_a["id"], session_d["id"], session_e["id"]], (
        "exactly the three accepted windows survive, in created_at order, got "
        "{}".format(ids_of(rows))
    )
    assert_created_at_ascending(rows)
    assert_pagination_meta(meta, 10, 0, expected_total=3, expected_has_more=False)
    assert meta["total_count"] != 5, (
        "the two refused requests must not have persisted a session row"
    )
    assert {row["status"] for row in rows} == {"SCHEDULED"}


def test_a_cancelled_window_stops_occupying_the_programme_timeline():
    """The occupancy filter is status-scoped. While window G is `LIVE` a strictly
    interior replacement is refused, but once G is `CANCELLED` the very same
    request is scheduled, because a cancelled window no longer occupies the
    programme's timeline at all.

    PRD §2.7 check 17: "**Session window exclusivity** — the requested window
    neither overlaps nor falls within 60 minutes of any auction session on the
    same programme whose `status` is `SCHEDULED` or `LIVE`. Otherwise
    `ERR_SESSION_WINDOW_CONFLICT` (409). Applies to `POST /auction-sessions`."

    PRD §3.5: "The four session states are `SCHEDULED`, `LIVE`, `CLOSED` and
    `CANCELLED`, of which `CLOSED` and `CANCELLED` are terminal."

    PRD §3.5: "A session becomes `LIVE` only when the new clock instant is at or
    after its `opens_at` and strictly before its `closes_at`, and only while the
    governing programme is `OPEN` or `PAUSED`."

    PRD §3.5: "With `mode` set to `CANCEL`, the session may be `SCHEDULED` or
    `LIVE` and it moves to `CANCELLED`, expiring outstanding offers in ascending
    `created_at` order but writing no clearing rate."

    PRD §2.4: "`version`, an integer that starts at 1 on creation and increases
    by exactly 1 on every mutation of that row."

    Design: Difficulty/resource_temporal_overlap/session_exclusive_occupancy_with_sixty_minute_cooldown
    """
    ctx = _cooldown_ctx()
    session_g = validate_success(
        _schedule(ctx, "2026-08-20T09:00:00Z", "2026-08-20T17:00:00Z"), 201
    )
    assert session_g["status"] == "SCHEDULED"

    # The clock lands exactly on G's opens_at, which is inside the half-open
    # window, so step two of the sweep drives SCHEDULED -> LIVE.
    fx.set_clock("2026-08-20T09:00:00Z")
    live_rows, live_meta = _sessions_of(ctx, status="LIVE")
    assert ids_of(live_rows) == [session_g["id"]], (
        "the clock landing on opens_at must make G LIVE, got {}".format(
            ids_of(live_rows)
        )
    )
    assert live_meta["total_count"] == 1
    live_g = live_rows[0]
    assert live_g["version"] == session_g["version"] + 1, (
        "the sweep transition is a mutation and bumps version by exactly one"
    )

    # Control: while G occupies the programme, the interior replacement is
    # refused — 09:30 < 17:00 + 60min and 09:00 < 16:00 + 60min both hold.
    validate_error(
        _schedule(ctx, "2026-08-20T09:30:00Z", "2026-08-20T16:00:00Z"),
        ERR_SESSION_WINDOW_CONFLICT,
        409,
    )

    cancelled = fx.close_session(session_g["id"], ctx.buyer_id, mode="CANCEL")
    assert cancelled["status"] == "CANCELLED", (
        "CANCEL from LIVE lands on CANCELLED, got {}".format(cancelled["status"])
    )
    assert cancelled["status"] != "CLOSED", (
        "cancellation is not settlement; CLOSED would be the wrong terminal"
    )
    assert cancelled["clearing_apr_bps"] == 0, (
        "cancellation writes no clearing rate, got {!r}".format(
            cancelled["clearing_apr_bps"]
        )
    )
    assert cancelled["version"] == live_g["version"] + 1

    # Same window, same programme, same clock — only G's status changed.
    session_h = validate_success(
        _schedule(ctx, "2026-08-20T09:30:00Z", "2026-08-20T16:00:00Z"), 201
    )
    assert session_h["status"] == "SCHEDULED", (
        "a window strictly inside a CANCELLED window is legal, got {}".format(
            session_h["status"]
        )
    )
    assert session_h["named_offer_count"] == 0
    assert session_h["version"] == 1, (
        "the replacement is a brand-new row, not a revival of G"
    )
    assert session_h["id"] != session_g["id"]

    rows, meta = _sessions_of(ctx)
    assert ids_of(rows) == [session_g["id"], session_h["id"]], (
        "only G and H persist, in created_at order, got {}".format(ids_of(rows))
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[session_g["id"]]["status"] == "CANCELLED"
    assert by_id[session_h["id"]]["status"] == "SCHEDULED"
    assert_pagination_meta(meta, 10, 0, expected_total=2, expected_has_more=False)
    assert meta["total_count"] != 3, (
        "the refused interior request must not have persisted a session row"
    )
    assert ids_of(_sessions_of(ctx, status="CANCELLED")[0]) == [session_g["id"]]
    assert ids_of(_sessions_of(ctx, status="SCHEDULED")[0]) == [session_h["id"]]


def test_overlapping_tranches_stack_to_the_ceiling_and_one_cent_more_fails():
    """Tranches on one funder may overlap freely; what is tested is the summed
    exposure at each candidate instant. 600000 + 400001 breaches the 1000000
    ceiling at 2026-08-15 and is refused, 600000 + 400000 meets it exactly and is
    persisted, a third 700000 tranche overlapping T2 at 2026-09-01 is refused,
    and the identical 700000 tranche starting one day past T2's closed upper
    bound is persisted — so overlap was never the thing being tested.

    PRD §3.7: "Tranches on one funder are explicitly permitted to overlap in time
    — the funder's exposure at an instant is the sum of the tranches covering it,
    which is the aggregate-capacity semantics this platform assumes."

    PRD §3.7: "When a new tranche is submitted, the platform tests a set of
    candidate instants consisting of the new tranche's `effective_from` together
    with every boundary point of existing tranches that falls inside the new
    interval. At each candidate instant, the already-committed capital of that
    funder at that instant, plus the new `committed_amount_cents`, must be at
    most the funder's `capital_limit_cents`. If any candidate instant would
    breach the ceiling, the tranche is refused with
    `ERR_FUNDER_CAPITAL_OVERCOMMITTED`. Overlap alone never fails; only summed
    exposure does."

    PRD §3.7: "The interval is closed on both ends: a tranche whose `effective_to`
    falls on a given date still covers that date."

    PRD §3.7: "Tranches are persisted in `status` `ACTIVE`, and the only other
    tranche state is the terminal `EXPIRED`."

    PRD §2.7 check 26: "**Funder capital ceiling** — the new tranche does not push
    the funder's summed committed capital above its `capital_limit_cents` at any
    instant inside the tranche's interval. Otherwise
    `ERR_FUNDER_CAPITAL_OVERCOMMITTED` (409). Applies to
    `POST /funders/{id}/commitments`."

    Design: Difficulty/resource_temporal_overlap/funder_tranche_aggregate_capacity_over_closed_intervals
    """
    funder, t1 = _funder_with_t1()
    assert t1["status"] == "ACTIVE"
    assert t1["committed_amount_cents"] == T1_CENTS
    assert t1["version"] == 1

    # Clock is at 2026-08-01, which T1's closed interval covers, so committed
    # capital there is 600000 and nothing is encumbered yet.
    after_t1 = _read_funder(funder["id"])
    assert after_t1["available_capital_cents"] == T1_CENTS, (
        "committed 600000 at the clock date minus 0 encumbered, got {}".format(
            after_t1["available_capital_cents"]
        )
    )
    assert after_t1["encumbered_capital_cents"] == 0
    assert_funder_capital_conserved(after_t1, T1_CENTS)

    # Candidate instant 2026-08-15 is the new effective_from; T1's closed
    # interval covers it, so 600000 + 400001 = 1000001 > 1000000.
    validate_error(
        _commit(funder["id"], T2_OVER_CENTS, T2_FROM, T2_TO),
        ERR_FUNDER_CAPITAL_OVERCOMMITTED,
        409,
    )
    _, refused_meta = _tranches_of(funder["id"])
    assert refused_meta["total_count"] != 2, (
        "the one-cent overshoot must not persist a tranche row"
    )
    assert refused_meta["total_count"] == 1

    # The same overlapping window at 400000 sums to exactly 1000000 at both
    # candidate instants (2026-08-15 and T1's boundary 2026-08-31), and equality
    # is permitted.
    t2 = validate_success(_commit(funder["id"], T2_CENTS, T2_FROM, T2_TO), 201)
    assert t2["status"] == "ACTIVE", (
        "summed exposure of exactly the ceiling is allowed, got {}".format(
            t2["status"]
        )
    )
    assert t2["committed_amount_cents"] == T2_CENTS
    assert t2["version"] == 1

    # T2 overlaps T1 for the whole of 2026-08-15..2026-08-31, yet the clock is
    # still at 2026-08-01, which only T1 covers.
    after_t2 = _read_funder(funder["id"])
    assert after_t2["available_capital_cents"] == T1_CENTS, (
        "only T1 covers 2026-08-01, got {}".format(
            after_t2["available_capital_cents"]
        )
    )
    assert after_t2["available_capital_cents"] != CAPITAL_LIMIT_CENTS, (
        "committed capital is measured at the clock date, not summed over all "
        "tranches regardless of interval"
    )

    # Candidate instant 2026-09-01 lies inside T2's closed interval, which still
    # contributes 400000 there even though T1 has ended: 400000 + 700000 =
    # 1100000 > 1000000.
    validate_error(
        _commit(funder["id"], T5_CENTS, "2026-09-01T00:00:00Z", T5_TO),
        ERR_FUNDER_CAPITAL_OVERCOMMITTED,
        409,
    )

    # One day past T2's closed upper bound nothing covers 2026-09-16, so the
    # identical 700000 tranche sums to 700000 and is admitted.
    t5 = validate_success(_commit(funder["id"], T5_CENTS, T5_FROM, T5_TO), 201)
    assert t5["status"] == "ACTIVE"
    assert t5["committed_amount_cents"] == T5_CENTS, (
        "the admitted tranche is the same size as the refused one"
    )

    active_rows, active_meta = _tranches_of(funder["id"], status="ACTIVE")
    assert ids_of(active_rows) == [t1["id"], t2["id"], t5["id"]], (
        "exactly the three admitted tranches persist, got {}".format(
            ids_of(active_rows)
        )
    )
    assert_created_at_ascending(active_rows)
    assert_pagination_meta(active_meta, 10, 0, expected_total=3,
                           expected_has_more=False)
    assert active_meta["total_count"] != 5, (
        "neither refused tranche may leave a row behind"
    )
    expired_rows, expired_meta = _tranches_of(funder["id"], status="EXPIRED")
    assert expired_rows == []
    assert expired_meta["total_count"] == 0


def test_a_tranche_counts_on_its_effective_to_date_and_expires_next_sweep():
    """The closed upper bound is load-bearing in two directions. At clock
    2026-08-31, T1's own `effective_to`, T1 still covers the date and the funder
    reads 600000 + 400000 = 1000000 of available capital. One day later step five
    of the sweep has expired T1, only T2 covers 2026-09-01, and available capital
    drops to exactly 400000.

    PRD §3.7: "Committed capital at a date is the sum of `committed_amount_cents`
    over that funder's tranches whose `status` is `ACTIVE` and whose closed
    interval contains that date; expired tranches contribute nothing.
    `available_capital_cents` is then that committed figure at the logical clock's
    current date minus the funder's `encumbered_capital_cents`, floored at zero so
    it never goes negative."

    PRD §3.5: "Step five expires capital: every `ACTIVE` funder commitment whose
    `effective_to` has passed becomes `EXPIRED`, and each affected funder's
    available capital is recomputed."

    PRD §3.7: "Tranches also expire on their own through the clock sweep of §3.5,
    when the clock's date passes a tranche's `effective_to`; that path increments
    both the tranche's `version` and the funder's `version` by one and recomputes
    available capital identically."

    PRD §2.10: "For every funder, the capital committed at the logical clock date
    must always equal `available_capital_cents` plus `encumbered_capital_cents`"

    PRD §2.3: "List results are ordered by `created_at` ascending."

    Design: Difficulty/resource_temporal_overlap/funder_tranche_aggregate_capacity_over_closed_intervals
    """
    funder, t1 = _funder_with_t1()
    t2 = fx.add_commitment(
        funder["id"],
        committed_amount_cents=T2_CENTS,
        effective_from=T2_FROM,
        effective_to=T2_TO,
    )
    t5 = fx.add_commitment(
        funder["id"],
        committed_amount_cents=T5_CENTS,
        effective_from=T5_FROM,
        effective_to=T5_TO,
    )

    # 2026-08-31 is T1's effective_to, so T1 has not "passed" and stays ACTIVE.
    # T1 600000 + T2 400000 = 1000000 cover the date; T5 starts 2026-09-16.
    fx.set_clock("2026-08-31T00:00:00Z")
    on_edge = _read_funder(funder["id"])
    assert on_edge["available_capital_cents"] == CAPITAL_LIMIT_CENTS, (
        "600000 + 400000 both cover the closed upper bound, got {}".format(
            on_edge["available_capital_cents"]
        )
    )
    assert on_edge["available_capital_cents"] != T2_CENTS, (
        "a half-open reading of [effective_from, effective_to] would drop T1 a "
        "day early and report 400000"
    )
    assert on_edge["available_capital_cents"] != T1_CENTS + T2_CENTS + T5_CENTS, (
        "T5 does not cover 2026-08-31 and must not be summed in"
    )
    assert on_edge["encumbered_capital_cents"] == 0
    assert_funder_capital_conserved(on_edge, CAPITAL_LIMIT_CENTS)

    edge_rows, edge_meta = _tranches_of(funder["id"], status="ACTIVE")
    assert ids_of(edge_rows) == [t1["id"], t2["id"], t5["id"]], (
        "nothing has expired yet at 2026-08-31, got {}".format(ids_of(edge_rows))
    )
    assert edge_meta["total_count"] == 3
    version_before = on_edge["version"]

    # One day on, T1's effective_to has passed and step five expires it.
    fx.set_clock("2026-09-01T00:00:00Z")
    after = _read_funder(funder["id"])
    assert after["available_capital_cents"] == T2_CENTS, (
        "only T2's closed interval contains 2026-09-01, got {}".format(
            after["available_capital_cents"]
        )
    )
    assert after["available_capital_cents"] != CAPITAL_LIMIT_CENTS, (
        "T1 must have left the pool once the clock passed its effective_to"
    )
    assert after["available_capital_cents"] != T2_CENTS + T5_CENTS, (
        "T5 has not started on 2026-09-01 and must not be counted early"
    )
    assert_funder_capital_conserved(after, T2_CENTS)
    assert after["version"] == version_before + 1, (
        "the expiry sweep bumps the funder's version by exactly one, got {} "
        "from {}".format(after["version"], version_before)
    )

    expired_rows, expired_meta = _tranches_of(funder["id"], status="EXPIRED")
    assert ids_of(expired_rows) == [t1["id"]], (
        "T1 is the only tranche whose effective_to has passed, got {}".format(
            ids_of(expired_rows)
        )
    )
    assert expired_meta["total_count"] == 1
    assert expired_rows[0]["status"] == "EXPIRED"
    assert expired_rows[0]["version"] == t1["version"] + 1, (
        "the expiry sweep bumps the tranche's version by exactly one"
    )
    assert expired_rows[0]["committed_amount_cents"] == T1_CENTS, (
        "expiry changes status, not the pledged amount"
    )

    still_active, active_meta = _tranches_of(funder["id"], status="ACTIVE")
    assert ids_of(still_active) == [t2["id"], t5["id"]], (
        "T2 and T5 only, in created_at order, got {}".format(ids_of(still_active))
    )
    assert_created_at_ascending(still_active)
    assert_pagination_meta(active_meta, 10, 0, expected_total=2,
                           expected_has_more=False)
    assert t1["id"] not in ids_of(still_active), (
        "an expired tranche must leave the ACTIVE collection, not merely stop "
        "contributing capital"
    )
