"""Two administrative round trips on the paperwork side of the system. A renewal moves three
things at once — the term, optionally the price, and both ends of the next window, which are
re-derived from the new final vintage rather than nudged along by the number of years bought. And
a producer's standing is a gate rather than a state machine: the only way to see it is that
operations reachable through the producer stop working while it is withdrawn and start again the
moment it is restored.
"""
from test_helpers import (
    MANAGER,
    ApiErrorId,
    move_clock,
    read_contract,
    read_grower,
    reinstate_grower,
    setup_active_contract,
    setup_drafted_contract,
    suspend_grower,
    validate_error,
    validate_paginated,
    validate_success,
)

ACCEPTED_AT = "2026-08-01T00:00:00Z"

# The term ends with the 2026 vintage, so the first window closes at midnight on the first of
# November 2026 and opens the contract's 90 notice days earlier.
FIRST_WINDOW_OPENS_AT = "2026-08-03T00:00:00Z"
FIRST_WINDOW_CLOSES_AT = "2026-11-01T00:00:00Z"

# Two years bought on a 2026 term lands the new final vintage on 2028 — an implementation that
# rolls the window forward by a single year would say 2027.
RENEWED_TERM_END_VINTAGE = 2028
SECOND_WINDOW_OPENS_AT = "2028-08-03T00:00:00Z"
SECOND_WINDOW_CLOSES_AT = "2028-11-01T00:00:00Z"

THIRD_TERM_END_VINTAGE = 2030
THIRD_WINDOW_CLOSES_AT = "2030-11-01T00:00:00Z"

ORIGINAL_PRICE_PER_TON_CENTS = 450000
RENEWED_PRICE_PER_TON_CENTS = 480000

A_TWO_YEAR_EXTENSION_AT_A_NEW_PRICE = {
    "renewal_term_years": 2,
    "renewed_base_price_per_ton_cents": RENEWED_PRICE_PER_TON_CENTS,
}
A_TWO_YEAR_EXTENSION_AT_THE_SAME_PRICE = {"renewal_term_years": 2}


# --- Renewing inside the open window -----------------------------------------------------


def _a_spotless_producer_on_a_single_vintage_term() -> dict:
    """An ACTIVE contract whose term ends with the vintage it began in, on a producer whose
    standing has never been dented — so only the window can stand in a renewal's way."""
    move_clock(ACCEPTED_AT)
    ctx = setup_active_contract({"contract_code": "GC-RENEW", "term_end_vintage": 2026})
    return ctx


def _renew(api, contract_id: str, terms: dict):
    return api.renew_contract(contract_id, dict(terms), MANAGER)


def test_the_clock_alone_opens_the_window(api):
    """Nobody asks for the window to open: the contract sits at `NOT_DUE` until the clock reaches
    the opening instant, and the transition bumps the row's version on its own.

    PRD: "All three of those edges are fired by the logical clock, not by a client: they require
    the lifecycle to be `ACTIVE` and the clock to have moved into the half-open interval that
    begins at `renewal_window_opens_at` and ends strictly before `renewal_window_closes_at`. Each
    fires a contract version increment."

    Design: Corner/endpoints/renew_extends_the_term_and_recomputes_the_renewal_window
    """
    ctx = _a_spotless_producer_on_a_single_vintage_term()
    assert ctx["contract"]["renewal_status"] == "NOT_DUE"
    assert ctx["contract"]["renewal_window_opens_at"] == FIRST_WINDOW_OPENS_AT
    assert ctx["contract"]["renewal_window_closes_at"] == FIRST_WINDOW_CLOSES_AT
    version_before = ctx["contract"]["version"]

    move_clock(FIRST_WINDOW_OPENS_AT)
    opened = read_contract(ctx["contract"]["id"])
    assert opened["renewal_status"] == "RENEWAL_WINDOW_OPEN"
    assert opened["version"] == version_before + 1


def test_a_renewal_buys_years_and_replaces_the_price(api):
    """The producer's lifetime standing is untouched at 100.0 and the window is open, so both the
    term extension and the supplied price take effect.

    PRD: "A successful renewal increases `term_end_vintage` by `renewal_term_years`, replaces
    `base_price_per_ton_cents` with `renewed_base_price_per_ton_cents` when that optional input
    was supplied and leaves it untouched otherwise"

    Design: Corner/endpoints/renew_extends_the_term_and_recomputes_the_renewal_window
    """
    ctx = _a_spotless_producer_on_a_single_vintage_term()
    assert float(read_grower(ctx["grower"]["id"])["reliability_score_lifetime"]) == 100.0
    move_clock(FIRST_WINDOW_OPENS_AT)

    renewed = validate_success(
        _renew(api, ctx["contract"]["id"], A_TWO_YEAR_EXTENSION_AT_A_NEW_PRICE)
    )
    assert renewed["renewal_status"] == "RENEWED"
    assert renewed["term_end_vintage"] == RENEWED_TERM_END_VINTAGE
    assert renewed["base_price_per_ton_cents"] == RENEWED_PRICE_PER_TON_CENTS


def test_the_new_window_is_derived_from_the_new_final_vintage(api):
    """Both edges are recomputed from the vintage the term now ends in, not shifted by the two
    years that were bought — the opening edge still sits the contract's notice period before the
    first of November.

    PRD: "and recomputes the renewal window from the new `term_end_vintage` —
    `renewal_window_closes_at` becomes midnight UTC on the first of November of that year and
    `renewal_window_opens_at` becomes that instant less `termination_notice_days` days."

    Design: Corner/endpoints/renew_extends_the_term_and_recomputes_the_renewal_window
    """
    ctx = _a_spotless_producer_on_a_single_vintage_term()
    move_clock(FIRST_WINDOW_OPENS_AT)

    renewed = validate_success(
        _renew(api, ctx["contract"]["id"], A_TWO_YEAR_EXTENSION_AT_A_NEW_PRICE)
    )
    assert renewed["renewal_window_closes_at"] == SECOND_WINDOW_CLOSES_AT
    assert renewed["renewal_window_opens_at"] == SECOND_WINDOW_OPENS_AT


def test_the_renewal_left_the_lifecycle_and_the_money_alone(api):
    """The renewal dimension moves independently: the agreement is still running, still open on
    tonnage, and still without a settlement.

    PRD: "A contract's renewal dimension moves independently of its lifecycle."

    Design: Corner/endpoints/renew_extends_the_term_and_recomputes_the_renewal_window
    """
    ctx = _a_spotless_producer_on_a_single_vintage_term()
    move_clock(FIRST_WINDOW_OPENS_AT)
    _renew(api, ctx["contract"]["id"], A_TWO_YEAR_EXTENSION_AT_A_NEW_PRICE)

    contract = read_contract(ctx["contract"]["id"])
    assert contract["lifecycle_status"] == "ACTIVE"
    assert contract["tonnage_status"] == "OPEN"
    assert float(contract["delivered_contract_tons"]) == 0.000
    assert contract["settlement_closed_at"] is None
    assert contract["final_settlement_cents"] == 0


def test_the_renewed_contract_is_discoverable_by_its_renewal_state(api):
    """The renewal dimension is a working query filter and not merely a field on the row.

    PRD: "Contracts are read individually and listed with the optional filters `grower_id`,
    `quality_spec_id`, `lifecycle_status`, `renewal_status` and `tonnage_status`, newest first by
    `created_at` descending."

    Design: Corner/endpoints/renew_extends_the_term_and_recomputes_the_renewal_window
    """
    ctx = _a_spotless_producer_on_a_single_vintage_term()
    move_clock(FIRST_WINDOW_OPENS_AT)
    _renew(api, ctx["contract"]["id"], A_TWO_YEAR_EXTENSION_AT_A_NEW_PRICE)

    rows, meta = validate_paginated(
        api.list_grape_contracts(MANAGER, params={"renewal_status": "RENEWED"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["contract"]["id"]


def test_the_recomputed_window_lets_the_cycle_run_a_second_time(api):
    """Because the window was re-derived rather than left behind, the clock can enter it again and
    a second renewal is possible — and this one omits the price, so the price it was renewed at
    last time stands.

    PRD: "and equally `RENEWED → RENEWAL_WINDOW_OPEN` and `EVERGREEN_ROLLED →
    RENEWAL_WINDOW_OPEN` once the window has been recomputed for the new term."

    Design: Corner/endpoints/renew_extends_the_term_and_recomputes_the_renewal_window
    """
    ctx = _a_spotless_producer_on_a_single_vintage_term()
    move_clock(FIRST_WINDOW_OPENS_AT)
    _renew(api, ctx["contract"]["id"], A_TWO_YEAR_EXTENSION_AT_A_NEW_PRICE)

    move_clock(SECOND_WINDOW_OPENS_AT)
    assert read_contract(ctx["contract"]["id"])["renewal_status"] == "RENEWAL_WINDOW_OPEN"

    renewed_again = validate_success(
        _renew(api, ctx["contract"]["id"], A_TWO_YEAR_EXTENSION_AT_THE_SAME_PRICE)
    )
    assert renewed_again["term_end_vintage"] == THIRD_TERM_END_VINTAGE
    assert renewed_again["base_price_per_ton_cents"] == RENEWED_PRICE_PER_TON_CENTS
    assert renewed_again["renewal_window_closes_at"] == THIRD_WINDOW_CLOSES_AT


# --- Withdrawing and restoring a producer's standing -------------------------------------


def _a_producer_with_a_contract_waiting_to_go_out() -> dict:
    """One producer with one block, one specification and one DRAFT contract that already has its
    allocation, so the only thing between it and the table is the producer's standing."""
    move_clock(ACCEPTED_AT)
    return setup_drafted_contract({"contract_code": "GC-STANDING"})


def test_suspension_is_a_mutation_of_the_producer_row(api):
    """Withdrawing standing is an edit of an existing row rather than the creation of anything, so
    the version counter moves off its initial value.

    PRD: "Suspension moves `status` to `SUSPENDED` and accepts an optional free-text `reason` that
    the server does not interpret; reinstatement moves `status` back to `ACTIVE` and takes no body
    at all. Both are `GrowerRelationsManager`-only, and both are modifications of an existing row
    rather than creations."

    Design: Corner/endpoints/suspend_and_reinstate_round_trip_the_producers_standing
    """
    ctx = _a_producer_with_a_contract_waiting_to_go_out()
    assert ctx["grower"]["version"] == 1

    suspended = suspend_grower(ctx["grower"]["id"], reason="Licence under review")
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 2


def test_a_suspended_producer_cannot_be_put_on_the_table(api):
    """The refusal is a 403 the business rules produce, not one the role table produces — the
    manager is entirely entitled to make this call — and the contract does not move.

    PRD: "A `SUSPENDED` producer is frozen out of six operations, and the refusal is always
    `ERR_GROWER_SUSPENDED` with HTTP 403: putting a contract on the table, accepting a contract,
    issuing a pick call, booking a delivery appointment, capturing a weigh tag, and paying an
    installment."

    Design: Corner/endpoints/suspend_and_reinstate_round_trip_the_producers_standing
    """
    ctx = _a_producer_with_a_contract_waiting_to_go_out()
    suspend_grower(ctx["grower"]["id"], reason="Licence under review")

    validate_error(
        api.offer_contract(ctx["contract"]["id"], MANAGER),
        ApiErrorId.ERR_GROWER_SUSPENDED.value,
        403,
    )
    assert read_contract(ctx["contract"]["id"])["lifecycle_status"] == "DRAFT"


def test_reinstatement_restores_the_standing_and_advances_the_counter_again(api):
    """A pure standing change is still a write, so the second leg of the round trip advances the
    version once more.

    PRD: "Almost every resource additionally carries `updated_at` — an ISO 8601 UTC timestamp,
    same format, refreshed on every mutation — and `version`, an integer that starts at 1 on
    creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/suspend_and_reinstate_round_trip_the_producers_standing
    """
    ctx = _a_producer_with_a_contract_waiting_to_go_out()
    suspend_grower(ctx["grower"]["id"], reason="Licence under review")

    restored = reinstate_grower(ctx["grower"]["id"])
    assert restored["status"] == "ACTIVE"
    assert restored["version"] == 3


def test_the_gate_is_read_afresh_on_every_request(api):
    """The very request that was refused a moment ago now succeeds, unchanged — so the standing is
    consulted per request rather than latched when the contract was drafted.

    PRD: "Putting a contract on the table is a `GrowerRelationsManager` action that drives
    `DRAFT → OFFERED`"

    Design: Corner/endpoints/suspend_and_reinstate_round_trip_the_producers_standing
    """
    ctx = _a_producer_with_a_contract_waiting_to_go_out()
    suspend_grower(ctx["grower"]["id"], reason="Licence under review")
    api.offer_contract(ctx["contract"]["id"], MANAGER)
    reinstate_grower(ctx["grower"]["id"])

    offered = validate_success(api.offer_contract(ctx["contract"]["id"], MANAGER))
    assert offered["lifecycle_status"] == "OFFERED"


def test_the_producer_listing_follows_the_standing_both_ways(api):
    """The standing filter is a live query over the current value: the producer appears under
    `SUSPENDED` while the hold is on and has left that collection once it is lifted.

    PRD: "Producers can be browsed as a collection with the optional filters `region_code` and
    `status`, and a single producer read returns both reliability scores and the outstanding lien
    balance."

    Design: Corner/endpoints/suspend_and_reinstate_round_trip_the_producers_standing
    """
    ctx = _a_producer_with_a_contract_waiting_to_go_out()
    suspend_grower(ctx["grower"]["id"], reason="Licence under review")

    rows, meta = validate_paginated(api.list_growers(MANAGER, params={"status": "SUSPENDED"}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["grower"]["id"]

    reinstate_grower(ctx["grower"]["id"])
    _, after = validate_paginated(api.list_growers(MANAGER, params={"status": "SUSPENDED"}))
    assert after["total_count"] == 0
