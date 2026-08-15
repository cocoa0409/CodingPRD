"""Closing coordination, settlement statements, disbursement and the disclosure
gate (PRD §3.4, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_closing,
    assert_money,
    assert_statement,
    create_closing_payload,
    create_statement_payload,
    get_success_data,
    make_agent_headers,
    make_buyer_headers,
    track_event_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


# ────────────────────────── net sheet variants ───────────────────────

def test_net_sheet_provisional_variant_figures(api):
    """PRD §3.8: "an over-appraisal kicker of 0.5 percent of the gross is added
    when the gross is at least 110 percent of the sum of `APPRAISAL` valuations
    across the winning-scope tracts at statement creation, the exact boundary
    included, and zero otherwise; and the commission is the greater of a $7,500
    floor and the base plus kicker, with only this final figure rounded half-up
    to 2 decimal places."
    PRD §3.8: "A `PROVISIONAL` statement performs no per-tract allocation at
    all: its `tract_allocations` is null and its `allocated_seller_costs` is a
    flat estimate of 0.5 percent of the gross, rounded half-up to 2 decimal
    places — so the two variants produce different nets on identical closing
    data."

    Design: Difficulty/dual_variant_calc/net_sheet_provisional_vs_final_diverge
    """
    env = fx.setup_closing_ready(with_disclosure=True, payoff_amount=200000)
    res = api.create_statement(
        create_statement_payload(env["closing"]["id"], "PROVISIONAL"),
        make_agent_headers(env["agent"]["id"]),
    )
    prov = validate_success(res, 201)
    assert_statement(prov)
    # gross 1400000 -> tiers 15000 + 22500 + 19500 = 57000; no kicker
    # (1400000 < 1.10 x 1357673 of scope appraisals); floor not binding.
    assert_money(prov["gross_price"], 1400000, "gross_price")
    assert_money(prov["commission_amount"], 57000.00, "commission_amount")
    assert_money(prov["allocated_seller_costs"], 7000.00, "allocated_seller_costs")
    assert prov["tract_allocations"] is None
    assert_money(prov["rent_credit"], 0, "rent_credit")
    # 1400000 - 57000 - 7000 - 200000 - 0
    assert_money(prov["seller_net"], 1136000.00, "seller_net")
    assert prov["status"] == "PROVISIONAL"


def test_net_sheet_final_variant_diverges(api):
    """PRD §3.8: "Fifth, `seller_net` is the `gross_price` minus the
    `commission_amount`, minus the `allocated_seller_costs`, minus the
    `payoff_amount` — copied from the closing package at computation time —
    minus the `rent_credit`."
    PRD §3.8: "When that possession date falls after the `target_closing_date`,
    the credit counts the calendar days from the `target_closing_date` to the
    possession date — exclusive of the start, inclusive of the end; the daily
    rent is the disclosure's `annual_rent` divided by 365, rounded half-up to 2
    decimal places before any multiplication; and the tract's credit is that
    daily rent times the day count, rounded half-up to 2 decimal places."
    PRD §3.8: "so the two variants produce different nets on identical closing
    data."

    Design: Difficulty/dual_variant_calc/net_sheet_provisional_vs_final_diverge
    """
    env = fx.setup_closing_ready(with_disclosure=True, payoff_amount=200000)
    agent_headers = make_agent_headers(env["agent"]["id"])
    prov = validate_success(
        api.create_statement(
            create_statement_payload(env["closing"]["id"], "PROVISIONAL"), agent_headers
        ),
        201,
    )
    fin = validate_success(
        api.create_statement(
            create_statement_payload(env["closing"]["id"], "FINAL"), agent_headers
        ),
        201,
    )
    assert_statement(fin)
    # Actual allocated costs: 1500 + 0.002x1400000 + 1200x2 + 0.001x1400000x0.5.
    assert_money(fin["allocated_seller_costs"], 7400.00, "allocated_seller_costs")
    # Rent credit: daily 49.32 (18000/365 rounded first) x 45 days held back.
    assert_money(fin["rent_credit"], 2219.40, "rent_credit")
    assert_money(fin["commission_amount"], 57000.00, "commission_amount")
    # 1400000 - 57000 - 7400 - 200000 - 2219.40
    assert_money(fin["seller_net"], 1133380.60, "seller_net")
    assert fin["seller_net"] != prov["seller_net"], (
        "same closing data, two variants, different seller net"
    )


# ────────────────────────── per-tract cost allocation ────────────────

def test_closing_cost_allocation_per_tract_shares(api):
    """PRD §3.8: "Seller closing costs are built from a fixed recipe: a $1,500
    flat title fee, plus 0.2 percent of the gross, plus $1,200 per tract in the
    winning scope, plus the seller's half of a 0.1 percent escrow charge on the
    gross — the total rounded half-up to 2 decimal places."
    PRD §3.8: "each tract's `share` is the total multiplied by its weight,
    rounded half-up to 2 decimal places per tract first, in pinned order; and
    the residual — which may be zero, or positive or negative cents — is added
    to the tract with the highest `tract_number`, so the allocated shares sum to
    the total exactly; the allocation is never rounded as a sum."

    Design: Difficulty/combinatorial_formula/closing_cost_allocation_per_tract_rounding_order
    """
    env = fx.setup_closing_ready(with_disclosure=False, payoff_amount=200000)
    fin = validate_success(
        api.create_statement(
            create_statement_payload(env["closing"]["id"], "FINAL"),
            make_agent_headers(env["agent"]["id"]),
        ),
        201,
    )
    assert_statement(fin)
    assert_money(fin["allocated_seller_costs"], 7400.00, "allocated_seller_costs")
    shares = {entry["tract_id"]: entry["share"] for entry in fin["tract_allocations"]}
    t1, t2 = env["tracts"][0]["id"], env["tracts"][1]["id"]
    # Appraisal weights: T1 924373 / 1357673, T2 433300 / 1357673; per-tract
    # round-half-up first yields 5038.30 / 2361.70 (residual 0.00 to T2).
    assert_money(shares[t1], 5038.30, "T1 share")
    assert_money(shares[t2], 2361.70, "T2 share")


def test_closing_cost_allocations_sum_exactly_to_total(api):
    """PRD §3.8: "the residual — which may be zero, or positive or negative
    cents — is added to the tract with the highest `tract_number`, so the
    allocated shares sum to the total exactly; the allocation is never rounded
    as a sum."
    PRD §3.8: "The `FINAL` statement exposes these as `tract_allocations`, a
    list of per-tract entries each naming a `tract_id` and its `share`."

    Design: Difficulty/combinatorial_formula/closing_cost_allocation_per_tract_rounding_order
    """
    env = fx.setup_closing_ready(with_disclosure=False, payoff_amount=200000)
    fin = validate_success(
        api.create_statement(
            create_statement_payload(env["closing"]["id"], "FINAL"),
            make_agent_headers(env["agent"]["id"]),
        ),
        201,
    )
    allocs = fin["tract_allocations"]
    assert isinstance(allocs, list) and len(allocs) == 2
    tract_ids = {entry["tract_id"] for entry in allocs}
    assert tract_ids == {env["tracts"][0]["id"], env["tracts"][1]["id"]}
    total = sum(entry["share"] for entry in allocs)
    assert total == pytest.approx(7400.00, abs=0.005)
    assert total == pytest.approx(fin["allocated_seller_costs"], abs=0.005), (
        "per-tract-first rounding: shares sum to the total exactly"
    )


# ────────────────────────── closing creation gates ───────────────────

def _awarded_combo_with_disclosure_verified():
    """Awarded COMBINATION flow, deposit VERIFIED, disclosure still DISCLOSED."""
    env = fx.setup_awarded_combination(with_disclosure=True)
    fx.pay_and_verify_deposit(env["agent"], env["deposit"]["id"], 42000)
    return env


def test_closing_blocked_until_disclosure_acknowledged(api):
    """PRD §3.8: "every lease disclosure of every tract in the winning scope
    must be `ACKNOWLEDGED`, else `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`"

    Design: Difficulty/cross_entity_state_dependency/closing_gate_depends_on_disclosure_acknowledgment
    """
    env = _awarded_combo_with_disclosure_verified()
    res = api.create_closing(
        create_closing_payload(env["auction"]["id"], payoff_amount=200000),
        make_agent_headers(env["agent"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED)


def test_closing_created_after_disclosure_acknowledged(api):
    """PRD §3.4: "Acknowledgement moves it to `ACKNOWLEDGED` and records the
    caller in `acknowledged_by_buyer_id`."
    PRD §3.8: "A new closing initializes three independent parallel axes —
    `title_status` at `NOT_ORDERED`, `survey_status` at `NOT_ORDERED`,
    `funding_status` at `UNFUNDED` — with `overall_status` derived at
    `INITIATED`."

    Design: Difficulty/cross_entity_state_dependency/closing_gate_depends_on_disclosure_acknowledgment
    """
    env = _awarded_combo_with_disclosure_verified()
    ack = fx.acknowledge_disclosure(env["buyer"], env["disclosure"]["id"])
    assert ack["status"] == "ACKNOWLEDGED"
    assert ack["acknowledged_by_buyer_id"] == env["buyer"]["id"]
    closing = fx.create_closing(env["agent"], env["auction"]["id"], payoff_amount=200000)
    assert_closing(closing)
    assert closing["overall_status"] == "INITIATED"
    assert closing["title_status"] == "NOT_ORDERED"
    assert closing["survey_status"] == "NOT_ORDERED"
    assert closing["funding_status"] == "UNFUNDED"


def test_closing_safety_gate_beats_past_date(api):
    """PRD §3.8: "The gates run in a fixed order: the auction must be `AWARDED`,
    else `ERR_INVALID_AUCTION_STATE`; the earnest-money deposit behind every
    winning bid must be `VERIFIED`, else `ERR_INVALID_DEPOSIT_STATE`; every
    lease disclosure of every tract in the winning scope must be `ACKNOWLEDGED`,
    else `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`; the `target_closing_date` must fall
    strictly after the logical clock, else `ERR_CLOSING_DATE_PAST`; and an
    auction supports exactly one closing package, a second attempt failing with
    `ERR_DUPLICATE_RECORD`."

    Design: Difficulty/priority_pair_validation_conflict/closing_unacknowledged_disclosure_past_date_safety_beats_temporal
    """
    env = _awarded_combo_with_disclosure_verified()
    # Both the disclosure gate (DISCLOSED) and the date gate (2026-08-05 is
    # before the 2026-08-10 clock) are violated; the earlier gate surfaces.
    res = api.create_closing(
        create_closing_payload(
            env["auction"]["id"],
            target_closing_date="2026-08-05T00:00:00Z",
            payoff_amount=200000,
        ),
        make_agent_headers(env["agent"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED)


def test_closing_past_date_surfaces_after_acknowledgment(api):
    """PRD §3.8: "The gates run in a fixed order: the auction must be `AWARDED`,
    else `ERR_INVALID_AUCTION_STATE`; the earnest-money deposit behind every
    winning bid must be `VERIFIED`, else `ERR_INVALID_DEPOSIT_STATE`; every
    lease disclosure of every tract in the winning scope must be `ACKNOWLEDGED`,
    else `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`; the `target_closing_date` must fall
    strictly after the logical clock, else `ERR_CLOSING_DATE_PAST`; and an
    auction supports exactly one closing package, a second attempt failing with
    `ERR_DUPLICATE_RECORD`."

    Design: Difficulty/priority_pair_validation_conflict/closing_unacknowledged_disclosure_past_date_safety_beats_temporal
    """
    env = _awarded_combo_with_disclosure_verified()
    fx.acknowledge_disclosure(env["buyer"], env["disclosure"]["id"])
    # With the safety gate now satisfied, the masked temporal gate surfaces.
    res = api.create_closing(
        create_closing_payload(
            env["auction"]["id"],
            target_closing_date="2026-08-05T00:00:00Z",
            payoff_amount=200000,
        ),
        make_agent_headers(env["agent"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CLOSING_DATE_PAST)


def test_closing_date_past_rejected_when_otherwise_valid(api):
    """PRD §3.8: "the `target_closing_date` must fall strictly after the logical
    clock, else `ERR_CLOSING_DATE_PAST`"

    Design: Corner/validations/closing_date_past_rejected_when_otherwise_valid
    """
    env = _awarded_combo_with_disclosure_verified()
    fx.acknowledge_disclosure(env["buyer"], env["disclosure"]["id"])
    res = api.create_closing(
        create_closing_payload(
            env["auction"]["id"],
            target_closing_date="2026-08-05T00:00:00Z",
            payoff_amount=200000,
        ),
        make_agent_headers(env["agent"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CLOSING_DATE_PAST)


# ────────────────────────── parallel axes machine ────────────────────

def _closing_env_whole():
    """Awarded WHOLE flow with VERIFIED deposit and a fresh closing (INITIATED)."""
    env = fx.setup_awarded_whole(bid_amount=770000, method="LIVE")
    fx.pay_and_verify_deposit(env["agent"], env["deposit"]["id"], 23100)
    env["closing"] = fx.create_closing(env["agent"], env["auction"]["id"], payoff_amount=0)
    return env


def test_title_cure_loop_cycles(api):
    """PRD §3.8: "The title axis walks `NOT_ORDERED` to `ORDERED` to
    `COMMITMENT_RECEIVED` to `CLEARED`, with `EXCEPTION_RAISED` reachable from
    either `ORDERED` or `COMMITMENT_RECEIVED` and a `CURE` event returning
    `EXCEPTION_RAISED` to `COMMITMENT_RECEIVED`."
    PRD §3.8: "It leaves `INITIATED` for `COORDINATION` the moment any axis
    departs its initial value"

    Design: Difficulty/non_linear_state_machine/closing_parallel_axes_with_title_cure_loop
    """
    env = _closing_env_whole()
    closing = env["closing"]
    assert closing["overall_status"] == "INITIATED"
    agent_headers = make_agent_headers(env["agent"]["id"])

    step = fx.track_event(closing["id"], agent_headers, "TITLE", "ORDER_COMMITMENT")
    assert step["title_status"] == "ORDERED"
    assert step["overall_status"] == "COORDINATION"
    step = fx.track_event(closing["id"], agent_headers, "TITLE", "RECEIVE_COMMITMENT")
    assert step["title_status"] == "COMMITMENT_RECEIVED"
    step = fx.track_event(closing["id"], agent_headers, "TITLE", "RAISE_EXCEPTION")
    assert step["title_status"] == "EXCEPTION_RAISED"
    step = fx.track_event(closing["id"], agent_headers, "TITLE", "CURE_EXCEPTION")
    assert step["title_status"] == "COMMITMENT_RECEIVED", (
        "cure returns the title axis to COMMITMENT_RECEIVED"
    )


def test_axes_independent_until_ready(api):
    """PRD §3.8: "it reaches `READY_TO_CLOSE` when `title_status` is `CLEARED`
    and `survey_status` is either `COMPLETED` or `WAIVED`; and it settles at
    `CLOSED` when the funding axis reaches `DISBURSED`."
    PRD §3.8: "The survey axis walks `NOT_ORDERED` to `ORDERED` to `COMPLETED`,
    or directly from `NOT_ORDERED` to `WAIVED` via a `WAIVE` event that requires
    `seller_consent` to be true — a waiver without it fails as `ERR_VALIDATION`."

    Design: Difficulty/non_linear_state_machine/closing_parallel_axes_with_title_cure_loop
    """
    env = _closing_env_whole()
    agent_headers = make_agent_headers(env["agent"]["id"])
    c_id = env["closing"]["id"]
    fx.track_event(c_id, agent_headers, "TITLE", "ORDER_COMMITMENT")
    fx.track_event(c_id, agent_headers, "TITLE", "RECEIVE_COMMITMENT")
    step = fx.track_event(c_id, agent_headers, "TITLE", "CLEAR")
    # Title CLEARED while survey untouched: not ready — axes are independent.
    assert step["title_status"] == "CLEARED"
    assert step["survey_status"] == "NOT_ORDERED"
    assert step["overall_status"] == "COORDINATION"
    step = fx.track_event(c_id, agent_headers, "SURVEY", "WAIVE", seller_consent=True)
    assert step["survey_status"] == "WAIVED"
    assert step["funding_status"] == "UNFUNDED"
    assert step["overall_status"] == "READY_TO_CLOSE"


def test_track_event_invalid_and_waive_without_consent(api):
    """PRD §3.8: "An event that does not fit the axis's current state, or any
    track event on a `CLOSED` or `TERMINATED` closing, is rejected with
    `ERR_INVALID_CLOSING_STATE`."
    PRD §3.8: "The survey axis walks `NOT_ORDERED` to `ORDERED` to `COMPLETED`,
    or directly from `NOT_ORDERED` to `WAIVED` via a `WAIVE` event that requires
    `seller_consent` to be true — a waiver without it fails as `ERR_VALIDATION`."

    Design: Corner/state_machines/track_event_invalid_from_state_and_waive_without_consent
    """
    env = _closing_env_whole()
    agent_headers = make_agent_headers(env["agent"]["id"])
    c_id = env["closing"]["id"]
    # CLEAR requires COMMITMENT_RECEIVED; the title axis is still NOT_ORDERED.
    res = api.post_track_event(c_id, track_event_payload("TITLE", "CLEAR"), agent_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_CLOSING_STATE)
    res = api.post_track_event(c_id, track_event_payload("SURVEY", "WAIVE"), agent_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


# ────────────────────────── disbursement cascade ─────────────────────

def test_disburse_completes_full_close_cascade(api):
    """PRD §3.8: "It is permitted only from `READY_TO_CLOSE`, and only when a
    `FINAL` statement exists for the closing — both failures are
    `ERR_INVALID_CLOSING_STATE`. The disbursement cascade settles the whole
    chain at once: the listing moves from `UNDER_CONTRACT` to `CLOSED` with its
    `version` incremented; every `VERIFIED` deposit moves to
    `APPLIED_TO_CLOSING` with `amount_applied` set to its `amount_received`; the
    `FINAL` statement moves to `PAID`; and each in-scope `ACKNOWLEDGED`
    disclosure moves to `POSSESSION_TRANSFERRED`."

    Design: Corner/validations/disburse_completes_full_close_cascade
    """
    env = _awarded_combo_with_disclosure_verified()
    fx.acknowledge_disclosure(env["buyer"], env["disclosure"]["id"])
    agent_headers = make_agent_headers(env["agent"]["id"])
    closing = fx.create_closing(env["agent"], env["auction"]["id"], payoff_amount=200000)
    c_id = closing["id"]

    # Disbursement is gated: overall is INITIATED and no FINAL statement exists.
    early = api.post_track_event(c_id, track_event_payload("FUNDING", "DISBURSE"), fx.ADMIN)
    validate_error(early, ApiErrorId.ERR_INVALID_CLOSING_STATE)

    closing = fx.drive_to_ready_to_close(env["agent"], c_id, survey_style="WAIVE")
    assert closing["overall_status"] == "READY_TO_CLOSE"
    statement = validate_success(
        api.create_statement(create_statement_payload(c_id, "FINAL"), agent_headers),
        201,
    )
    assert statement["status"] == "FINAL"

    fx.track_event(c_id, fx.ADMIN, "FUNDING", "RECEIVE_FUNDS")
    closed = fx.track_event(c_id, fx.ADMIN, "FUNDING", "DISBURSE")
    assert closed["overall_status"] == "CLOSED"

    listing = fx.read_listing(env["listing"]["id"], agent_headers)
    assert listing["status"] == "CLOSED"
    tract = get_success_data(api.get_tract(env["tracts"][0]["id"], agent_headers))
    assert tract["status"] == "SOLD", "terminal sale persists"
    deposit = get_success_data(api.get_deposit(env["deposit"]["id"], agent_headers))
    assert deposit["status"] == "APPLIED_TO_CLOSING"
    assert_money(deposit["amount_applied"], 42000.00, "amount_applied")
    statements = get_success_data(api.list_closing_statements(c_id, agent_headers))
    assert len(statements) == 1 and statements[0]["status"] == "PAID"
    disclosures = get_success_data(
        api.list_tract_disclosures(env["tracts"][0]["id"], agent_headers)
    )
    assert disclosures[0]["status"] == "POSSESSION_TRANSFERRED"


# ────────────────────────── disclosure acknowledgement ───────────────

def test_acknowledge_twice_rejected(api):
    """PRD §3.4: "the caller must be the buyer of a `CONFIRMED_WINNER` bid whose
    scope contains the disclosure's tract, else `ERR_FORBIDDEN`, and the
    disclosure must still be `DISCLOSED`, else `ERR_INVALID_DISCLOSURE_STATE`."

    Design: Corner/validations/acknowledge_twice_rejected_invalid_disclosure_state
    """
    env = fx.setup_awarded_combination(with_disclosure=True)
    buyer_headers = make_buyer_headers(env["buyer"]["id"])
    first = validate_success(
        api.acknowledge_disclosure(env["disclosure"]["id"], buyer_headers), 200
    )
    assert first["status"] == "ACKNOWLEDGED"
    res = api.acknowledge_disclosure(env["disclosure"]["id"], buyer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_DISCLOSURE_STATE)


def test_acknowledge_by_non_winning_buyer_forbidden(api):
    """PRD §3.4: "the caller must be the buyer of a `CONFIRMED_WINNER` bid whose
    scope contains the disclosure's tract, else `ERR_FORBIDDEN`, and the
    disclosure must still be `DISCLOSED`, else `ERR_INVALID_DISCLOSURE_STATE`."

    Design: Corner/state_machines/acknowledge_by_non_winning_buyer_forbidden
    """
    env = fx.setup_open_auction(
        method="ONLINE",
        total_gross_acres=160,
        packaging_strategy="COMBINATION",
        reserve_price_total=1200000,
        tract_specs=[dict(s) for s in fx.COMBINATION_TRACT_SPECS],
        comparables="triple",
        with_disclosure=True,
    )
    t1, t2 = env["tracts"][0]["id"], env["tracts"][1]["id"]
    loser = fx.create_qualified_buyer()
    winner = fx.create_qualified_buyer(full_name="Buyer Three", email="b3@x.com")
    get_success_data(fx.place_bid_fresh(loser, env["auction"]["id"], 700000, [t1]))
    get_success_data(fx.place_bid_fresh(winner, env["auction"]["id"], 1400000, [t1, t2]))
    fx.award_auction_at(env["agent"], env["auction"]["id"], fx.AUCTION_END)
    # The loser's individual bid is LOST, not CONFIRMED_WINNER.
    res = api.acknowledge_disclosure(
        env["disclosure"]["id"], make_buyer_headers(loser["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


# ────────────────────────── track-event duty split ───────────────────

def test_agent_cannot_post_funding_track_event(api):
    """PRD §3.8: "Duty is split: `TITLE` and `SURVEY` events are
    `BrokerAgent`-only, while `FUNDING` events are `PlatformAdmin`-only — a
    broker attempting a funding event is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/rbac_agent_cannot_post_funding_track_event
    """
    env = _closing_env_whole()
    res = api.post_track_event(
        env["closing"]["id"],
        track_event_payload("FUNDING", "RECEIVE_FUNDS"),
        make_agent_headers(env["agent"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
