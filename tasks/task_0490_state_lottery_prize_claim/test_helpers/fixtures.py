"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, since the harness restarts the server (empty DB) before every test.
All setup calls use get_success_data() so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.

Serial/tax-id uniqueness: each test runs against a fresh DB, but a single test
may build several retailers/terminals/tickets. Fixtures accept explicit unique
suffixes (or generate them) to keep tax_id / serial_number / serial distinct.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, officer_headers, admin_headers, operator_headers, clerk_headers,
)
from .factories import (
    create_game_payload, create_retailer_payload, create_terminal_payload,
    create_player_payload, create_ticket_payload, create_prize_claim_payload,
    create_drawing_payload, create_entry_payload, create_settlement_payload,
    self_exclude_payload,
)

# Monotonic counter to keep unique fields distinct within a single test process.
_uniq = itertools.count(1)


def _u() -> int:
    return next(_uniq)


LIC = TEST_USERS["licensing_admin_headers"]
OP = TEST_USERS["terminal_operator_headers"]
CLERK = TEST_USERS["claims_clerk_headers"]
OFF = TEST_USERS["lottery_officer_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers=None):
    """Set the logical clock. Uses LotteryOfficer by default."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or OFF))


# ---------------------------------------------------------------------------
# Tier 1: primitive creators
# ---------------------------------------------------------------------------
def create_game(game_type="JACKPOT", **overrides):
    """Create an ACTIVE game (status ACTIVE on creation). Returns the game dict."""
    payload = create_game_payload(
        name=overrides.pop("name", f"Game-{_u()}"),
        game_type=game_type,
        **overrides,
    )
    return get_success_data(api_client.create_game(payload, OFF))


def create_retailer(**overrides):
    """Register a retailer (PENDING). tax_id auto-uniqued unless supplied."""
    payload = create_retailer_payload(
        business_name=overrides.pop("business_name", f"Mart-{_u()}"),
        tax_id=overrides.pop("tax_id", f"TAX-{_u()}"),
        **overrides,
    )
    return get_success_data(api_client.create_retailer(payload, LIC))


def create_active_retailer(**overrides):
    """Retailer driven PENDING -> ACTIVE. Returns the activated retailer dict."""
    ret = create_retailer(**overrides)
    return get_success_data(api_client.activate_license(ret["id"], LIC))


def create_provisioned_terminal(retailer_id, **overrides):
    payload = create_terminal_payload(
        retailer_id,
        serial_number=overrides.pop("serial_number", f"SN-{_u()}"),
        **overrides,
    )
    return get_success_data(api_client.create_terminal(payload, LIC))


def create_active_terminal(retailer_id, **overrides):
    """Provision + activate a terminal on an ACTIVE retailer. Returns terminal dict."""
    term = create_provisioned_terminal(retailer_id, **overrides)
    return get_success_data(api_client.activate_terminal(term["id"], LIC))


def create_player(**overrides):
    payload = create_player_payload(
        full_name=overrides.pop("full_name", f"Player-{_u()}"),
        government_id_number=overrides.pop("government_id_number", f"GID-{_u()}"),
        **overrides,
    )
    return get_success_data(api_client.create_player(payload, CLERK))


# ---------------------------------------------------------------------------
# Tier 2: active retailer + terminal hierarchy
# ---------------------------------------------------------------------------
def setup_active_retailer_with_terminal(retailer_overrides=None, terminal_overrides=None):
    """ACTIVE retailer + one ACTIVE terminal. Returns (retailer, terminal).

    The returned retailer dict is the *activated* version; re-read with
    api_client.get_retailer for live computed ledger fields."""
    ret = create_active_retailer(**(retailer_overrides or {}))
    term = create_active_terminal(ret["id"], **(terminal_overrides or {}))
    return ret, term


def setup_game_retailer_terminal(game_type="JACKPOT", threshold_cents=600000,
                                 clock="2026-01-05T00:00:00Z", game_overrides=None,
                                 retailer_overrides=None):
    """Active game + active retailer + active terminal; clock set. The single most
    common preamble. Returns (game, retailer, terminal)."""
    g_over = dict(game_overrides or {})
    g_over.setdefault("federal_withholding_threshold_cents", threshold_cents)
    game = create_game(game_type=game_type, **g_over)
    ret, term = setup_active_retailer_with_terminal(retailer_overrides=retailer_overrides)
    if clock is not None:
        set_clock(clock)
    return game, ret, term


# ---------------------------------------------------------------------------
# Tier 3: tickets in various validation states
# ---------------------------------------------------------------------------
def sell_ticket(game_id, terminal_id, declared_tier=0, gross_prize_cents=0,
                draw_date="2026-01-10T00:00:00Z", price_cents=200, **overrides):
    """Sell a ticket via an ACTIVE terminal (UNVALIDATED). Returns ticket dict."""
    payload = create_ticket_payload(
        game_id, terminal_id,
        serial=overrides.pop("serial", f"TK-{_u()}"),
        declared_tier=declared_tier,
        gross_prize_cents=gross_prize_cents,
        draw_date=draw_date,
        price_cents=price_cents,
        **overrides,
    )
    return get_success_data(api_client.create_ticket(payload, OP))


def sell_and_validate_winner(game_id, terminal_id, gross_prize_cents=1000000,
                             draw_date="2026-01-10T00:00:00Z", **overrides):
    """Sell an over-threshold winner and validate -> VALIDATED_WINNER. Returns ticket."""
    tk = sell_ticket(game_id, terminal_id, declared_tier=1,
                     gross_prize_cents=gross_prize_cents, draw_date=draw_date, **overrides)
    return get_success_data(api_client.validate_ticket(tk["id"], OP))


def sell_and_validate_nonwinner(game_id, terminal_id,
                                draw_date="2026-01-10T00:00:00Z", **overrides):
    """Sell a non-winner (tier 0) and validate -> VALIDATED_NONWINNER (ELIGIBLE)."""
    tk = sell_ticket(game_id, terminal_id, declared_tier=0, gross_prize_cents=0,
                     draw_date=draw_date, **overrides)
    return get_success_data(api_client.validate_ticket(tk["id"], OP))


def sell_and_counter_pay(game_id, terminal_id, gross_prize_cents=50000,
                         draw_date="2026-01-10T00:00:00Z", **overrides):
    """Sell an under-threshold winner and validate -> PAID_AT_COUNTER (accrues bonus)."""
    tk = sell_ticket(game_id, terminal_id, declared_tier=2,
                     gross_prize_cents=gross_prize_cents, draw_date=draw_date, **overrides)
    return get_success_data(api_client.validate_ticket(tk["id"], OP))


# ---------------------------------------------------------------------------
# Tier 3b: prize claims in various lifecycle states
# ---------------------------------------------------------------------------
def open_claim(ticket_id, player_id, payout_option="CASH"):
    """Open a claim against a VALIDATED_WINNER ticket -> SUBMITTED."""
    payload = create_prize_claim_payload(ticket_id, player_id, payout_option)
    return get_success_data(api_client.create_prize_claim(payload, CLERK))


def setup_submitted_claim(game_type="JACKPOT", payout_option="CASH",
                          gross_prize_cents=1000000, clock="2026-01-05T00:00:00Z",
                          threshold_cents=600000):
    """Full chain to a SUBMITTED claim on a VALIDATED_WINNER ticket.
    Returns dict with game, retailer, terminal, ticket, player, claim."""
    game, ret, term = setup_game_retailer_terminal(
        game_type=game_type, threshold_cents=threshold_cents, clock=clock)
    ticket = sell_and_validate_winner(game["id"], term["id"],
                                      gross_prize_cents=gross_prize_cents)
    player = create_player()
    claim = open_claim(ticket["id"], player["id"], payout_option)
    return {"game": game, "retailer": ret, "terminal": term,
            "ticket": ticket, "player": player, "claim": claim}


def setup_adjudicating_claim(adj_user_id="u-adj", **kwargs):
    """SUBMITTED -> ADJUDICATING by adj_user_id. Returns the dict from
    setup_submitted_claim plus the adjudicating claim under 'claim' and 'adj_headers'."""
    ctx = setup_submitted_claim(**kwargs)
    adj = officer_headers(adj_user_id)
    ctx["claim"] = get_success_data(
        api_client.begin_adjudication(ctx["claim"]["id"], adj))
    ctx["adj_headers"] = adj
    ctx["adj_user_id"] = adj_user_id
    return ctx


def setup_approved_claim(adj_user_id="u-adj", **kwargs):
    """ADJUDICATING -> APPROVED_* by the adjudicating officer. Returns ctx with the
    approved claim under 'claim'."""
    ctx = setup_adjudicating_claim(adj_user_id=adj_user_id, **kwargs)
    ctx["claim"] = get_success_data(
        api_client.approve_claim(ctx["claim"]["id"], ctx["adj_headers"]))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: commission settlement setups
# ---------------------------------------------------------------------------
def fresh_retailer_version(retailer_id):
    """Re-read the retailer and return its current version (for OCC)."""
    r = get_success_data(api_client.get_retailer(retailer_id, OFF))
    return r["version"]


def create_settlement(retailer_id, period_start, period_end,
                      expected_retailer_version=None, prep_user_id="u-prep"):
    """Prepare a settlement (DRAFT). If expected_retailer_version is None, reads the
    current version first. Returns the settlement dict."""
    if expected_retailer_version is None:
        expected_retailer_version = fresh_retailer_version(retailer_id)
    payload = create_settlement_payload(
        retailer_id, period_start, period_end, expected_retailer_version)
    return get_success_data(
        api_client.create_settlement(payload, officer_headers(prep_user_id)))


def setup_window_with_sold_tickets(prices, game_type="DAILY", threshold_cents=600000,
                                   commission_rate=None, cashing_bonus_rate=None,
                                   clock="2026-05-10T00:00:00Z",
                                   draw_date="2026-05-10T00:00:00Z"):
    """Active retailer+terminal; sell one tier-0 ticket per price in `prices` inside
    the window. Returns (game, retailer, terminal, [tickets])."""
    r_over = {}
    if commission_rate is not None:
        r_over["commission_rate"] = commission_rate
    if cashing_bonus_rate is not None:
        r_over["cashing_bonus_rate"] = cashing_bonus_rate
    game = create_game(game_type=game_type,
                       federal_withholding_threshold_cents=threshold_cents)
    ret, term = setup_active_retailer_with_terminal(retailer_overrides=r_over)
    if clock is not None:
        set_clock(clock)
    tickets = []
    for p in prices:
        tickets.append(sell_ticket(game["id"], term["id"], declared_tier=0,
                                   gross_prize_cents=0, price_cents=p, draw_date=draw_date))
    return game, ret, term, tickets


# ---------------------------------------------------------------------------
# Tier 5: second-chance drawing setups
# ---------------------------------------------------------------------------
def create_open_drawing(game_id, entry_deadline="2026-02-01T00:00:00Z",
                        prize_pool_cents=500000):
    payload = create_drawing_payload(game_id, entry_deadline=entry_deadline,
                                     prize_pool_cents=prize_pool_cents)
    return get_success_data(api_client.create_drawing(payload, OFF))


def enter_ticket(drawing_id, ticket_id, headers=None):
    """File a second-chance entry. Defaults to ClaimsClerk."""
    payload = create_entry_payload(drawing_id, ticket_id)
    return get_success_data(api_client.create_entry(payload, headers or CLERK))


def drawing_version(drawing_id):
    d = get_success_data(api_client.get_drawing(drawing_id, OFF))
    return d["version"]


def setup_drawing_with_eligible_entry(entry_deadline="2026-02-01T00:00:00Z",
                                      pre_entry_clock="2026-01-10T00:00:00Z"):
    """Active game/retailer/terminal + OPEN drawing + one ELIGIBLE nonwinner entered.
    Returns dict: game, retailer, terminal, drawing, ticket, entry.
    Leaves the clock at pre_entry_clock (before entry_deadline)."""
    game = create_game(game_type="DAILY", federal_withholding_threshold_cents=600000)
    ret, term = setup_active_retailer_with_terminal()
    drawing = create_open_drawing(game["id"], entry_deadline=entry_deadline)
    set_clock(pre_entry_clock)
    ticket = sell_and_validate_nonwinner(game["id"], term["id"], draw_date=pre_entry_clock)
    entry = enter_ticket(drawing["id"], ticket["id"])
    return {"game": game, "retailer": ret, "terminal": term,
            "drawing": drawing, "ticket": ticket, "entry": entry}
