"""Auction lifecycle: soft-close cycle, close sweeps, sealed reveal, award and
no-sale exits (PRD §3.5, §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    assert_money,
    get_success_data,
    make_agent_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


# ────────────────────────── soft-close cycle ─────────────────────────

def _soft_close_env():
    """ONLINE auction 17:00-19:00Z with 5/5-minute soft close, opened at 18:57."""
    env = fx.setup_open_auction(
        method="ONLINE",
        open_at="2026-08-10T18:57:00Z",
        soft_close_window_minutes=5,
        extension_minutes=5,
    )
    return env


def test_soft_close_first_in_window_bid_extends(api):
    """PRD §3.5: "A bid accepted while the logical clock sits within
    `soft_close_window_minutes` before `effective_end` — that is, inside the
    final stretch of the window — extends the auction: `effective_end` gains
    `extension_minutes`, `extension_count` increases by one, and the auction
    moves from `OPEN` to `EXTENDED`, or from `EXTENDED` to `EXTENDED` again when
    a further bid lands inside the current soft-close window."

    Design: Difficulty/non_linear_state_machine/auction_open_extended_soft_close_cycle
    """
    env = _soft_close_env()
    b1 = fx.create_qualified_buyer()
    get_success_data(
        fx.place_bid_fresh(b1, env["auction"]["id"], 700000, [env["tracts"][0]["id"]])
    )
    auction = fx.read_auction(env["auction"]["id"], make_agent_headers(env["agent"]["id"]))
    # Bid at 18:57 lands inside [18:55, 19:00): one extension fires.
    assert auction["status"] == "EXTENDED"
    assert_instant_equal(auction["effective_end"], "2026-08-10T19:05:00Z", "effective_end")
    assert auction["extension_count"] == 1


def test_soft_close_second_in_window_bid_reextends_and_outbids(api):
    """PRD §3.5: "A bid accepted while the logical clock sits within
    `soft_close_window_minutes` before `effective_end` — that is, inside the
    final stretch of the window — extends the auction: `effective_end` gains
    `extension_minutes`, `extension_count` increases by one, and the auction
    moves from `OPEN` to `EXTENDED`, or from `EXTENDED` to `EXTENDED` again when
    a further bid lands inside the current soft-close window."
    PRD §3.6: "On `LIVE` and `ONLINE` auctions, when a later bid with an
    identical single-tract scope and a higher amount is accepted, the previous
    `PLACED` high bid for that scope moves to `OUTBID`."

    Design: Difficulty/non_linear_state_machine/auction_open_extended_soft_close_cycle
    """
    env = _soft_close_env()
    agent_headers = make_agent_headers(env["agent"]["id"])
    t = [env["tracts"][0]["id"]]
    b1 = fx.create_qualified_buyer()
    b2 = fx.create_qualified_buyer(full_name="Buyer Two", email="b2@x.com")
    bid1 = get_success_data(fx.place_bid_fresh(b1, env["auction"]["id"], 700000, t))
    fx.set_clock("2026-08-10T19:03:00Z")  # inside the [19:00, 19:05) window
    # 705000 == 700000 + 5000 exactly: accepted, and the cycle re-extends.
    get_success_data(fx.place_bid_fresh(b2, env["auction"]["id"], 705000, t))
    auction = fx.read_auction(env["auction"]["id"], agent_headers)
    assert auction["status"] == "EXTENDED"
    assert_instant_equal(auction["effective_end"], "2026-08-10T19:10:00Z", "effective_end")
    assert auction["extension_count"] == 2
    bid1_after = validate_success(api.get_bid(bid1["id"], agent_headers), 200)
    assert bid1_after["status"] == "OUTBID"


# ────────────────────────── zero-bid close sweep ─────────────────────

def _sealed_env_no_bids():
    return fx.setup_open_auction(
        method="SEALED_BID",
        reserve_price_total=770000,
        scheduled_start="2026-08-11T10:00:00Z",
        scheduled_end="2026-08-11T12:00:00Z",
        open_at="2026-08-11T10:00:00Z",
    )


def test_zero_bid_auction_closes_no_sale(api):
    """PRD §3.5: "With zero bids standing, the auction — again from either
    `OPEN` or `EXTENDED` — moves to `NO_SALE`, and when no other auction of the
    listing remains in `SCHEDULED`, `OPEN`, `EXTENDED`, or
    `CLOSED_PENDING_AWARD`, the listing falls back from `AUCTION_SCHEDULED` to
    `MARKETED` with its `version` incremented, ready for a fresh scheduling
    round; the listing's auctions remain listable per listing throughout."

    Design: Difficulty/boundary_precision_check/zero_bid_sealed_auction_auto_no_sale
    """
    env = _sealed_env_no_bids()
    fx.set_clock("2026-08-11T12:00:00Z")
    auction = fx.read_auction(env["auction"]["id"], make_agent_headers(env["agent"]["id"]))
    assert auction["status"] == "NO_SALE", (
        "zero PLACED/SEALED bids at close: NO_SALE, not CLOSED_PENDING_AWARD"
    )


def test_zero_bid_no_sale_returns_listing_to_marketed(api):
    """PRD §3.5: "With zero bids standing, the auction — again from either
    `OPEN` or `EXTENDED` — moves to `NO_SALE`, and when no other auction of the
    listing remains in `SCHEDULED`, `OPEN`, `EXTENDED`, or
    `CLOSED_PENDING_AWARD`, the listing falls back from `AUCTION_SCHEDULED` to
    `MARKETED` with its `version` incremented, ready for a fresh scheduling
    round; the listing's auctions remain listable per listing throughout."

    Design: Difficulty/boundary_precision_check/zero_bid_sealed_auction_auto_no_sale
    """
    env = _sealed_env_no_bids()
    fx.set_clock("2026-08-11T12:00:00Z")
    agent_headers = make_agent_headers(env["agent"]["id"])
    listing = fx.read_listing(env["listing"]["id"], agent_headers)
    tract = get_success_data(api.get_tract(env["tracts"][0]["id"], agent_headers))
    assert listing["status"] == "MARKETED"
    assert tract["status"] == "OFFERED", "tract survives for a future auction"


# ────────────────────────── sealed reveal at close ───────────────────

def test_sealed_bids_hidden_then_revealed_at_close(api):
    """PRD §3.6: "a `SEALED` bid's `amount` is hidden — returned as null on both
    individual bid reads and bid listings — until the close sweep reveals it as
    `REVEALED`."
    PRD §3.5: "With at least one bid standing in `PLACED` or `SEALED`, the
    auction — whether `OPEN` or `EXTENDED` — moves to `CLOSED_PENDING_AWARD`,
    and for a `SEALED_BID` auction every `SEALED` bid is revealed, moving to
    `REVEALED` with amounts becoming visible."

    Design: Corner/state_machines/sealed_bids_hidden_then_revealed_at_close
    """
    env = _sealed_env_no_bids()
    agent_headers = make_agent_headers(env["agent"]["id"])
    t = [env["tracts"][0]["id"]]
    b1 = fx.create_qualified_buyer()
    b2 = fx.create_qualified_buyer(full_name="Buyer Two", email="b2@x.com")
    get_success_data(fx.place_bid_fresh(b1, env["auction"]["id"], 700000, t))
    bid2 = get_success_data(fx.place_bid_fresh(b2, env["auction"]["id"], 710000, t))

    pre = validate_success(api.get_bid(bid2["id"], agent_headers), 200)
    assert pre["status"] == "SEALED"
    assert pre["amount"] is None, "sealed amount hidden before the close sweep"

    fx.set_clock("2026-08-11T12:00:00Z")
    post = validate_success(api.get_bid(bid2["id"], agent_headers), 200)
    assert post["status"] == "REVEALED"
    assert_money(post["amount"], 710000, "revealed amount")
    auction = fx.read_auction(env["auction"]["id"], agent_headers)
    assert auction["status"] == "CLOSED_PENDING_AWARD"


# ────────────────────────── invalid auction transitions ──────────────

def test_award_while_open_and_open_twice_rejected(api):
    """PRD §3.7: "An auction in `CLOSED_PENDING_AWARD` has two exits, both
    reserved to the listing's agent."
    PRD §3.5: "The caller must be the listing's agent, and the logical clock
    must have reached `scheduled_start` without yet reaching `scheduled_end` —
    opening outside the window is `ERR_AUCTION_WINDOW_INVALID`, and opening from
    any state other than `SCHEDULED` is `ERR_INVALID_AUCTION_STATE`."

    Design: Corner/state_machines/award_while_open_and_open_twice_rejected
    """
    env = fx.setup_marketed_listing()
    agent_headers = make_agent_headers(env["agent"]["id"])
    auction = fx.schedule_auction(env["agent"], env["listing"]["id"], method="ONLINE")
    fx.set_clock(fx.AUCTION_START)
    # Award requires CLOSED_PENDING_AWARD; the auction is still SCHEDULED.
    early_award = api.award_auction(auction["id"], agent_headers)
    validate_error(early_award, ApiErrorId.ERR_INVALID_AUCTION_STATE)
    opened = validate_success(api.open_auction(auction["id"], agent_headers), 200)
    assert opened["status"] == "OPEN"
    # Open requires SCHEDULED; the auction is already OPEN.
    reopened = api.open_auction(auction["id"], agent_headers)
    validate_error(reopened, ApiErrorId.ERR_INVALID_AUCTION_STATE)


# ────────────────────────── reserve gate at award ────────────────────

def test_award_below_reserve_rejected_then_no_sale(api):
    """PRD §3.7: "The `awarded_total` is the sum of the winning bids' amounts,
    and the award stands only if it meets the listing's `reserve_price_total` —
    a shortfall rejects the whole award with `ERR_RESERVE_NOT_MET`."
    PRD §3.7: "The no-sale exit moves the auction to `NO_SALE`: every bid still
    `PLACED` or `REVEALED` is voided to `VOIDED`; the listing falls back from
    `AUCTION_SCHEDULED` to `MARKETED` when no other auction of the listing
    remains in `SCHEDULED`, `OPEN`, `EXTENDED`, or `CLOSED_PENDING_AWARD`; rights
    dispositions unlock from `LOCKED` to `DECLARED` under that same
    no-active-auction condition; and the auction's `version` increments."

    Design: Corner/validations/award_below_reserve_rejected_then_no_sale
    """
    env = fx.setup_open_auction(method="LIVE")  # reserve 770000, min 700000
    agent_headers = make_agent_headers(env["agent"]["id"])
    b1 = fx.create_qualified_buyer()
    bid = get_success_data(
        fx.place_bid_fresh(b1, env["auction"]["id"], 700000, [env["tracts"][0]["id"]])
    )
    fx.set_clock(fx.AUCTION_END)
    short = api.award_auction(env["auction"]["id"], agent_headers)
    # awarded_total 700000 < reserve 770000: the whole award is rejected.
    validate_error(short, ApiErrorId.ERR_RESERVE_NOT_MET)
    auction = fx.read_auction(env["auction"]["id"], agent_headers)
    assert auction["status"] == "CLOSED_PENDING_AWARD", "rejected award leaves state"

    no_sale = validate_success(api.no_sale_auction(env["auction"]["id"], agent_headers), 200)
    assert no_sale["status"] == "NO_SALE"
    bid_after = validate_success(api.get_bid(bid["id"], agent_headers), 200)
    assert bid_after["status"] == "VOIDED"
    listing = fx.read_listing(env["listing"]["id"], agent_headers)
    assert listing["status"] == "MARKETED"
