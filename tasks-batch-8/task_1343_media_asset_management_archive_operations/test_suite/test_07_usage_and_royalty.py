"""Usage reporting, royalty accrual variants, statement sweep/close/reopen/post."""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_asset, create_staff_member, create_usage_event,
    create_verified_usage_event, create_royalty_statement, set_clock,
    create_usage_event_payload, create_royalty_statement_payload,
    make_requester_headers,
    TEST_USERS,
)

FINANCE = TEST_USERS["finance_officer_headers"]


def _asset_and_staff():
    staff = create_staff_member()
    asset = create_asset(rights_holder="ACME")
    return asset, staff


# ─── royalty floor/ceil interaction (Difficulty x2) ───

def test_provisional_accrual_floor_binding(api):
    """PRD §3.7: "Usage is billed in 30-second units: the event's `duration_seconds_used`
    divided by 30, rounded up to a whole unit."
    PRD §3.7: "The raw accrual is units times rate times multiplier, rounded half up to
    integer cents, and the provisional accrual is that rounded figure or the 25-cent
    per-event floor, whichever is greater."
    (ceil(10/30) = 1 unit x 100 cents SMALL x 0.25 PROMO = 25 -> floor binds at 25.)

    Design: Difficulty/combinatorial_formula/royalty_event_floor_and_ceil_interaction
    """
    asset, staff = _asset_and_staff()
    event = create_usage_event(asset["id"], staff["id"], usage_type="PROMO",
                               market_size=100, duration_seconds_used=10)
    verified = validate_success(api.verify_usage_event(event["id"], FINANCE), 200)
    assert verified["status"] == "VERIFIED"
    assert verified["provisional_accrual_cents"] == 25, (
        "ceil(10/30)=1 unit, 100c rate, 0.25 multiplier -> raw 25 -> floor max(25, 25) == 25")


def test_provisional_accrual_above_floor_uses_ceil_units(api):
    """PRD §3.7: "Usage is billed in 30-second units: the event's `duration_seconds_used`
    divided by 30, rounded up to a whole unit."
    PRD §3.7: "the provisional accrual is that rounded figure or the 25-cent per-event
    floor, whichever is greater."
    (ceil(40/30) = 2 units x 100 cents SMALL x 0.25 PROMO = 50 -> above the floor.)

    Design: Difficulty/combinatorial_formula/royalty_event_floor_and_ceil_interaction
    """
    asset, staff = _asset_and_staff()
    event = create_usage_event(asset["id"], staff["id"], usage_type="PROMO",
                               market_size=100, duration_seconds_used=40)
    verified = validate_success(api.verify_usage_event(event["id"], FINANCE), 200)
    assert verified["status"] == "VERIFIED"
    assert verified["provisional_accrual_cents"] == 50, (
        "ceil(40/30)=2 units x 100c x 0.25 = 50, above the 25-cent floor")
    fetched = validate_success(api.get_usage_event(event["id"], FINANCE), 200)
    assert fetched["provisional_accrual_cents"] == 50


# ─── dispute / resubmit cycle ─────────────────────────

def test_usage_event_dispute_resubmit_cycle(api):
    """PRD §3.7: "Verification belongs to the `FinanceOfficer` and moves `REPORTED` to
    `VERIFIED` (from any other state, `ERR_EVENT_NOT_REPORTED`, HTTP 409)."
    PRD §3.7: "Resubmission returns a `DISPUTED` event to `REPORTED` (from any other
    state, `ERR_EVENT_NOT_DISPUTED`, HTTP 409), resets `provisional_accrual_cents` to
    null so the event must be verified afresh, and may be performed only by the original
    reporter".

    Design: Corner/state_machines/usage_event_dispute_resubmit_cycle
    """
    asset, staff = _asset_and_staff()
    event = create_usage_event(asset["id"], staff["id"], usage_type="BROADCAST",
                               market_size=6_000_000, duration_seconds_used=120)

    disputed = validate_success(api.dispute_usage_event(
        event["id"], {"reason": "wrong market"}, FINANCE), 200)
    assert disputed["status"] == "DISPUTED"

    res = api.verify_usage_event(event["id"], FINANCE)
    validate_error(res, ApiErrorId.ERR_EVENT_NOT_REPORTED)

    resubmitted = validate_success(api.resubmit_usage_event(
        event["id"], make_requester_headers(staff["id"])), 200)
    assert resubmitted["status"] == "REPORTED"
    assert resubmitted["provisional_accrual_cents"] is None


# ─── dual-variant accrual (Difficulty x2) ─────────────

def _setup_two_event_statement():
    """E1 BROADCAST LARGE(6,000,000) 120s -> prov 2000; E2 STREAMING SMALL(500,000)
    3540s -> prov 8850; statement ACME [2026-07-01, 2026-08-01)."""
    set_clock("2026-07-01T00:00:00Z")
    asset, staff = _asset_and_staff()
    e1 = create_verified_usage_event(
        asset["id"], staff["id"], usage_type="BROADCAST", market_size=6_000_000,
        duration_seconds_used=120, aired_at="2026-07-10T00:00:00Z")
    e2 = create_verified_usage_event(
        asset["id"], staff["id"], usage_type="STREAMING", market_size=500_000,
        duration_seconds_used=3540, aired_at="2026-07-15T00:00:00Z")
    stmt = create_royalty_statement()
    return asset, staff, e1, e2, stmt


def test_statement_close_provisional_vs_final_totals(api):
    """PRD §3.7: "the `volume_tier` is derived from that total: fewer than 3,600 seconds
    (one hour of verified usage) is `TIER_0`; at least 3,600 but fewer than 36,000
    seconds (ten hours) is `TIER_1`; 36,000 seconds or more is `TIER_2`."
    PRD §3.7: "each swept event's `final_accrual_cents` is recomputed with the final
    variant of the accrual: ... multiplied by one minus the volume discount, where the
    discount is 0 percent for `TIER_0`, 10 percent for `TIER_1`, and 20 percent for
    `TIER_2`".
    PRD §3.7: "`provisional_total_cents` is the sum of the events' provisional accruals
    over the same swept set — no discount".

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_accrual
    """
    _, _, e1, e2, stmt = _setup_two_event_statement()
    assert e1["provisional_accrual_cents"] == 2000  # 4 units x 500 x 1.0
    assert e2["provisional_accrual_cents"] == 8850  # 118 units x 100 x 0.75

    closed = validate_success(api.close_royalty_statement(stmt["id"], FINANCE), 200)
    assert closed["status"] == "CLOSED"
    assert closed["total_verified_seconds"] == 3660
    assert closed["volume_tier"] == "TIER_1"
    assert closed["provisional_total_cents"] == 10850, "2000 + 8850, no discount"
    assert closed["total_accrual_cents"] == 9765, (
        "TIER_1 10% discount: 2000*0.9=1800 + 8850*0.9=7965")


def test_statement_close_stamps_events_and_per_event_finals(api):
    """PRD §3.7: "The close snapshots the swept ids into `event_ids` and stamps each
    swept event's `statement_id` with this statement."
    PRD §3.7: "each swept event's `final_accrual_cents` is recomputed with the final
    variant of the accrual".

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_accrual
    """
    _, _, e1, e2, stmt = _setup_two_event_statement()
    closed = validate_success(api.close_royalty_statement(stmt["id"], FINANCE), 200)
    assert sorted(closed["event_ids"]) == sorted([e1["id"], e2["id"]])

    events, meta = validate_paginated(
        api.list_usage_events(FINANCE, params={"statement_id": stmt["id"]}))
    assert len(events) == 2
    finals = {ev["id"]: ev["final_accrual_cents"] for ev in events}
    assert finals[e1["id"]] == 1800, "2000 x (1 - 0.10)"
    assert finals[e2["id"]] == 7965, "8850 x (1 - 0.10)"
    for ev in events:
        assert ev["statement_id"] == stmt["id"]


# ─── evaluation-order formula (Difficulty x2) ─────────

def _setup_tier1_boundary_statement():
    """E1 BROADCAST LARGE 1800s -> prov 30000; E2 REBROADCAST SMALL(100) 1800s ->
    prov 3000; total 3600s -> TIER_1."""
    set_clock("2026-07-01T00:00:00Z")
    asset, staff = _asset_and_staff()
    e1 = create_verified_usage_event(
        asset["id"], staff["id"], usage_type="BROADCAST", market_size=6_000_000,
        duration_seconds_used=1800, aired_at="2026-07-10T00:00:00Z")
    e2 = create_verified_usage_event(
        asset["id"], staff["id"], usage_type="REBROADCAST", market_size=100,
        duration_seconds_used=1800, aired_at="2026-07-11T00:00:00Z")
    stmt = create_royalty_statement()
    return e1, e2, stmt


def test_statement_volume_tier_evaluation_order(api):
    """PRD §3.7: "The sweep then runs in a fixed, non-recomputable order. First the
    matching events are collected. Second, `total_verified_seconds` is computed as the
    sum of `duration_seconds_used` across the swept set — this step must fully complete
    before the next. Third, the `volume_tier` is derived from that total".

    Design: Difficulty/combinatorial_formula/statement_volume_tier_evaluation_order
    """
    e1, e2, stmt = _setup_tier1_boundary_statement()
    assert e1["provisional_accrual_cents"] == 30000  # 60 units x 500 x 1.0
    assert e2["provisional_accrual_cents"] == 3000   # 60 units x 100 x 0.5

    closed = validate_success(api.close_royalty_statement(stmt["id"], FINANCE), 200)
    assert closed["total_verified_seconds"] == 3600
    assert closed["volume_tier"] == "TIER_1"
    assert closed["provisional_total_cents"] == 33000
    assert closed["total_accrual_cents"] == 29700, "30000*0.9=27000 + 3000*0.9=2700"


def test_statement_volume_tier_per_event_finals(api):
    """PRD §3.7: "Fifth, `total_accrual_cents` is the sum of those per-event finals.
    Sixth, `provisional_total_cents` is the sum of the events' provisional accruals over
    the same swept set — no discount — so the provisional view is always at least the
    final total".

    Design: Difficulty/combinatorial_formula/statement_volume_tier_evaluation_order
    """
    e1, e2, stmt = _setup_tier1_boundary_statement()
    validate_success(api.close_royalty_statement(stmt["id"], FINANCE), 200)

    f1 = validate_success(api.get_usage_event(e1["id"], FINANCE), 200)
    f2 = validate_success(api.get_usage_event(e2["id"], FINANCE), 200)
    assert f1["final_accrual_cents"] == 27000, "30000 x 0.9"
    assert f2["final_accrual_cents"] == 2700, "3000 x 0.9"
    assert f1["statement_id"] == stmt["id"]
    assert f2["statement_id"] == stmt["id"]


# ─── TIER_2 boundary (Difficulty x2) ──────────────────

def test_volume_tier_boundary_exactly_36000_seconds(api):
    """PRD §3.7: "the `volume_tier` is derived from that total: fewer than 3,600 seconds
    (one hour of verified usage) is `TIER_0`; at least 3,600 but fewer than 36,000
    seconds (ten hours) is `TIER_1`; 36,000 seconds or more is `TIER_2`."
    (E1 BROADCAST LARGE 20000s -> 667 units x 500 = 333500; E2 BROADCAST SMALL(100)
    16000s -> 534 units x 100 = 53400; total 36000s -> TIER_2 at 20% discount:
    266800 + 42720 = 309520.)

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_exactly_36000_seconds
    """
    set_clock("2026-07-01T00:00:00Z")
    asset, staff = _asset_and_staff()
    e1 = create_verified_usage_event(
        asset["id"], staff["id"], usage_type="BROADCAST", market_size=6_000_000,
        duration_seconds_used=20000, aired_at="2026-07-10T00:00:00Z")
    e2 = create_verified_usage_event(
        asset["id"], staff["id"], usage_type="BROADCAST", market_size=100,
        duration_seconds_used=16000, aired_at="2026-07-11T00:00:00Z")
    stmt = create_royalty_statement()

    closed = validate_success(api.close_royalty_statement(stmt["id"], FINANCE), 200)
    assert closed["total_verified_seconds"] == 36000
    assert closed["volume_tier"] == "TIER_2", "36000 is in TIER_2 (>= boundary inclusive)"
    assert closed["provisional_total_cents"] == 386900, "333500 + 53400"
    assert closed["total_accrual_cents"] == 309520, "333500*0.8=266800 + 53400*0.8=42720"

    f1 = validate_success(api.get_usage_event(e1["id"], FINANCE), 200)
    f2 = validate_success(api.get_usage_event(e2["id"], FINANCE), 200)
    assert f1["final_accrual_cents"] == 266800
    assert f2["final_accrual_cents"] == 42720


def test_volume_tier_just_below_36000_is_tier1(api):
    """PRD §3.7: "at least 3,600 but fewer than 36,000 seconds (ten hours) is `TIER_1`;
    36,000 seconds or more is `TIER_2`."
    (Single BROADCAST LARGE event of 35999s: ceil(35999/30) = 1200 units x 500 =
    600000 provisional; total 35999 -> TIER_1 at 10%: 540000.)

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_exactly_36000_seconds
    """
    set_clock("2026-07-01T00:00:00Z")
    asset, staff = _asset_and_staff()
    create_verified_usage_event(
        asset["id"], staff["id"], usage_type="BROADCAST", market_size=6_000_000,
        duration_seconds_used=35999, aired_at="2026-07-10T00:00:00Z")
    stmt = create_royalty_statement()

    closed = validate_success(api.close_royalty_statement(stmt["id"], FINANCE), 200)
    assert closed["total_verified_seconds"] == 35999
    assert closed["volume_tier"] == "TIER_1", "35999 is strictly below the TIER_2 boundary"
    assert closed["provisional_total_cents"] == 600000
    assert closed["total_accrual_cents"] == 540000, "600000 x 0.9"


# ─── sweep window, overlap, post gates ────────────────

def test_statement_sweep_half_open_period(api):
    """PRD §3.7: "requires at least one matching event: a `VERIFIED` usage event whose
    asset's `rights_holder` equals the statement's `rights_holder` and whose `aired_at`
    falls at or after `period_start` and strictly before `period_end` (otherwise
    `ERR_STATEMENT_EMPTY`, HTTP 409)."
    PRD §2.10: "a royalty statement sweeps usage whose `aired_at` is at or after
    `period_start` and strictly before `period_end`."

    Design: Corner/calculations/statement_sweep_half_open_period
    """
    set_clock("2026-07-01T00:00:00Z")
    asset, staff = _asset_and_staff()
    create_verified_usage_event(
        asset["id"], staff["id"], usage_type="BROADCAST", market_size=6_000_000,
        duration_seconds_used=120, aired_at="2026-07-01T00:00:00Z")  # at period_start: in July
    e_end = create_verified_usage_event(
        asset["id"], staff["id"], usage_type="BROADCAST", market_size=6_000_000,
        duration_seconds_used=120, aired_at="2026-08-01T00:00:00Z")  # at period_end: not July
    july = create_royalty_statement()
    august = create_royalty_statement(period_start="2026-08-01T00:00:00Z",
                                      period_end="2026-09-01T00:00:00Z")

    july_closed = validate_success(api.close_royalty_statement(july["id"], FINANCE), 200)
    assert july_closed["total_verified_seconds"] == 120, (
        "includes the event at period_start, excludes the event at period_end")
    assert e_end["id"] not in july_closed["event_ids"]

    august_closed = validate_success(api.close_royalty_statement(august["id"], FINANCE), 200)
    assert august_closed["total_verified_seconds"] == 120
    assert e_end["id"] in august_closed["event_ids"]


def test_overlapping_statement_period_rejected_adjacent_allowed(api):
    """PRD §3.7: "Creation is rejected with `ERR_STATEMENT_PERIOD_OVERLAP` (HTTP 422)
    when the new period intersects the period of any non-terminal statement — one in
    `OPEN` or `CLOSED` — for the same rights holder; intersection follows the half-open
    convention, so back-to-back periods that merely touch are allowed."

    Design: Corner/errors/overlapping_statement_period_rejected_adjacent_allowed
    """
    first = create_royalty_statement()
    assert first["status"] == "OPEN"

    res = api.create_royalty_statement(
        create_royalty_statement_payload(period_start="2026-07-15T00:00:00Z",
                                         period_end="2026-08-15T00:00:00Z"),
        FINANCE)
    validate_error(res, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP)

    adjacent = validate_success(api.create_royalty_statement(
        create_royalty_statement_payload(period_start="2026-08-01T00:00:00Z",
                                         period_end="2026-09-01T00:00:00Z"),
        FINANCE), 201)
    assert adjacent["status"] == "OPEN"


def _setup_closed_statement_with_25_cents():
    """One PROMO SMALL(100) 10s event -> 25 cents (floor); statement CLOSED."""
    set_clock("2026-07-01T00:00:00Z")
    asset, staff = _asset_and_staff()
    event = create_verified_usage_event(
        asset["id"], staff["id"], usage_type="PROMO", market_size=100,
        duration_seconds_used=10, aired_at="2026-07-10T00:00:00Z")
    stmt = create_royalty_statement()
    closed = validate_success(api_client.close_royalty_statement(stmt["id"], FINANCE), 200)
    assert closed["total_accrual_cents"] == 25
    return event, closed


def test_statement_post_temporal_gate_beats_fiscal_gate(api):
    """PRD §2.6: "When several checks could reject the same request, the server
    evaluates them in a fixed order and returns the first failure encountered."
    (temporal rules are step 7; fiscal gates are step 9.)
    PRD §3.7: "the logical clock must have reached `period_end` (otherwise
    `ERR_PERIOD_NOT_ENDED`, HTTP 422); `total_accrual_cents` must be at least the
    1,000-cent payout minimum (otherwise `ERR_PAYOUT_BELOW_MINIMUM`, HTTP 402)".

    Design: Corner/validations/statement_post_temporal_then_fiscal_ordering
    """
    _, stmt = _setup_closed_statement_with_25_cents()
    set_clock("2026-07-15T00:00:00Z")  # inside the period; total 25 < 1000
    res = api.post_royalty_statement(stmt["id"], FINANCE)
    validate_error(res, ApiErrorId.ERR_PERIOD_NOT_ENDED)


def test_statement_post_below_minimum_after_period_end(api):
    """PRD §3.7: "`total_accrual_cents` must be at least the 1,000-cent payout minimum
    (otherwise `ERR_PAYOUT_BELOW_MINIMUM`, HTTP 402)".
    PRD §3.7: "the logical clock must have reached `period_end` (otherwise
    `ERR_PERIOD_NOT_ENDED`, HTTP 422)".

    Design: Corner/validations/statement_post_below_minimum_after_period_end
    """
    _, stmt = _setup_closed_statement_with_25_cents()
    set_clock("2026-08-01T00:00:00Z")  # == period_end: reached
    res = api.post_royalty_statement(stmt["id"], FINANCE)
    validate_error(res, ApiErrorId.ERR_PAYOUT_BELOW_MINIMUM)

    still = validate_success(api.get_royalty_statement(stmt["id"], FINANCE), 200)
    assert still["status"] == "CLOSED"


def test_statement_post_dirty_snapshot_rejected(api):
    """PRD §3.7: "every event snapshotted in `event_ids` must still be `VERIFIED` — an
    event disputed after close trips `ERR_STATEMENT_EVENTS_DIRTY` (HTTP 409)."
    PRD §3.7: "Disputing a `VERIFIED` event has a delayed consequence: if the event has
    already been swept into a closed statement, that statement's posting will fail the
    still-verified re-validation with `ERR_STATEMENT_EVENTS_DIRTY` (HTTP 409)".

    Design: Corner/validations/statement_post_dirty_snapshot_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    asset, staff = _asset_and_staff()
    event = create_verified_usage_event(
        asset["id"], staff["id"], usage_type="BROADCAST", market_size=2_000_000,
        duration_seconds_used=120, aired_at="2026-07-10T00:00:00Z")
    stmt = create_royalty_statement()
    closed = validate_success(api.close_royalty_statement(stmt["id"], FINANCE), 200)
    assert closed["total_accrual_cents"] == 1000  # 4 units x 250, TIER_0

    set_clock("2026-08-02T00:00:00Z")  # past period_end
    validate_success(api.dispute_usage_event(event["id"], {"reason": "audit"}, FINANCE), 200)

    res = api.post_royalty_statement(stmt["id"], FINANCE)
    validate_error(res, ApiErrorId.ERR_STATEMENT_EVENTS_DIRTY)
    still = validate_success(api.get_royalty_statement(stmt["id"], FINANCE), 200)
    assert still["status"] == "CLOSED"


def test_statement_post_at_minimum_boundary_posts_events(api):
    """PRD §3.7: "`total_accrual_cents` must be at least the 1,000-cent payout minimum
    (otherwise `ERR_PAYOUT_BELOW_MINIMUM`, HTTP 402)".
    PRD §3.7: "A successful post moves the statement to the terminal `POSTED` state and
    transitions every swept event from `VERIFIED` to `ROYALTY_POSTED`, the terminal
    state of the usage-event lifecycle."
    (BROADCAST MEDIUM(2,000,000) 120s -> 4 units x 250 = 1000 exactly; TIER_0, no
    discount; 1000 >= 1000 posts.)

    Design: Corner/endpoints/statement_post_at_minimum_boundary_posts_events
    """
    set_clock("2026-07-01T00:00:00Z")
    asset, staff = _asset_and_staff()
    event = create_verified_usage_event(
        asset["id"], staff["id"], usage_type="BROADCAST", market_size=2_000_000,
        duration_seconds_used=120, aired_at="2026-07-10T00:00:00Z")
    stmt = create_royalty_statement()
    closed = validate_success(api.close_royalty_statement(stmt["id"], FINANCE), 200)
    assert closed["total_accrual_cents"] == 1000

    set_clock("2026-08-01T00:00:00Z")  # == period_end: reached
    posted = validate_success(api.post_royalty_statement(stmt["id"], FINANCE), 200)
    assert posted["status"] == "POSTED"

    swept = validate_success(api.get_usage_event(event["id"], FINANCE), 200)
    assert swept["status"] == "ROYALTY_POSTED"


def test_statement_reopen_clears_snapshot_then_reclose(api):
    """PRD §3.7: "A closed statement can be reopened — from `CLOSED` only, otherwise
    `ERR_STATEMENT_NOT_CLOSED` (HTTP 409) — which empties `event_ids`, clears every
    swept event's `statement_id` back to null, and resets the computed totals to null,
    returning the statement to `OPEN` for a fresh close."

    Design: Corner/validations/statement_reopen_clears_snapshot_then_reclose
    """
    set_clock("2026-07-01T00:00:00Z")
    asset, staff = _asset_and_staff()
    event = create_verified_usage_event(
        asset["id"], staff["id"], usage_type="BROADCAST", market_size=2_000_000,
        duration_seconds_used=120, aired_at="2026-07-10T00:00:00Z")
    stmt = create_royalty_statement()
    validate_success(api.close_royalty_statement(stmt["id"], FINANCE), 200)

    reopened = validate_success(api.reopen_royalty_statement(stmt["id"], FINANCE), 200)
    assert reopened["status"] == "OPEN"
    assert reopened["event_ids"] == []
    assert reopened["total_accrual_cents"] is None
    assert reopened["provisional_total_cents"] is None

    rows, _ = validate_paginated(
        api.list_usage_events(FINANCE, params={"statement_id": stmt["id"]}))
    assert len(rows) == 0, "reopen must reset swept events' statement_id to null"

    closed_again = validate_success(api.close_royalty_statement(stmt["id"], FINANCE), 200)
    assert closed_again["status"] == "CLOSED"
    assert closed_again["total_accrual_cents"] == 1000, "TIER_0, no discount"
    assert closed_again["event_ids"] == [event["id"]]


# ─── RBAC ─────────────────────────────────────────────

def test_requester_cannot_verify_usage_event(api):
    """PRD §2.1: "A request whose role is not permitted to perform the operation is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: POST /archive/usage-events/{id}/verify is authorized for FinanceOfficer.

    Design: Corner/rbac/requester_cannot_verify_usage_forbidden
    """
    asset, staff = _asset_and_staff()
    event = create_usage_event(asset["id"], staff["id"], market_size=100,
                               duration_seconds_used=30)
    res = api.verify_usage_event(event["id"], make_requester_headers(staff["id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
