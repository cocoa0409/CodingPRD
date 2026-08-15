"""Cascades and compensating invariants: forfeiture unwind, withdrawal,
termination refund, and conserved quantities (PRD §3.2, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_deposit,
    assert_escrow_conservation,
    assert_instant_equal,
    assert_money,
    get_success_data,
    make_agent_headers,
    make_seller_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


# ────────────────────────── forfeiture cascade (depth 5) ─────────────

def test_forfeit_deadline_and_amounts(api):
    """PRD §3.7: "The `amount_due` is three percent of the winning bid's amount,
    rounded half-up to 2 decimal places, but never less than a $10,000 floor;
    the `due_at` deadline is exactly forty-eight hours after the award
    timestamp"
    PRD §3.7: "The clock sweep independently moves a still-underpaid deposit
    from `PENDING` to `LATE` once the clock passes `due_at`."
    PRD §3.7: "In both cases `amount_forfeited` is set to whatever
    `amount_received` had accumulated, and the same five-hop unwind cascade
    fires"

    Design: Difficulty/transitive_cascade/earnest_forfeit_unwinds_award_depth5
    """
    env = fx.setup_awarded_combination()
    agent_headers = make_agent_headers(env["agent"]["id"])
    deposit = env["deposit"]
    assert_money(deposit["amount_due"], 42000.00, "amount_due")  # 3% of 1400000
    assert_instant_equal(deposit["due_at"], "2026-08-12T19:00:00Z", "due_at")

    fx.set_clock("2026-08-12T19:00:01Z")  # past due_at, inside the grace window
    mid = get_success_data(api.get_deposit(deposit["id"], agent_headers))
    assert mid["status"] == "LATE"

    fx.set_clock("2026-08-13T19:00:01Z")  # past due_at + 24h grace
    late = get_success_data(api.get_deposit(deposit["id"], agent_headers))
    assert late["status"] == "FORFEITED"
    assert_money(late["amount_received"], 0, "amount_received")
    assert_money(late["amount_forfeited"], 0, "amount_forfeited")
    assert_escrow_conservation(late)


def test_forfeit_cascade_unwinds_award_five_hops(api):
    """PRD §3.7: "the same five-hop unwind cascade fires: the buyer is
    disqualified — moving to `DISQUALIFIED` whether currently `QUALIFIED` or
    `EXPIRED`; that buyer's `CONFIRMED_WINNER` bid is voided to `VOIDED`; the
    auction hops from `AWARDED` to `NO_SALE`; the listing falls from
    `UNDER_CONTRACT` back to `MARKETED` with its `version` incremented; and its
    `SOLD` tracts return to `OFFERED`."

    Design: Difficulty/transitive_cascade/earnest_forfeit_unwinds_award_depth5
    """
    env = fx.setup_awarded_combination()
    agent_headers = make_agent_headers(env["agent"]["id"])
    fx.set_clock("2026-08-13T19:00:01Z")  # past due_at + 24h grace: sweep fires

    buyer = validate_success(api.get_buyer(env["buyer"]["id"], fx.ADMIN), 200)
    assert buyer["qualification_status"] == "DISQUALIFIED"  # hop 2
    bid = validate_success(api.get_bid(env["bid"]["id"], agent_headers), 200)
    assert bid["status"] == "VOIDED"  # hop 3
    auction = fx.read_auction(env["auction"]["id"], agent_headers)
    assert auction["status"] == "NO_SALE"  # hop 4
    listing = fx.read_listing(env["listing"]["id"], agent_headers)
    assert listing["status"] == "MARKETED"  # hop 5
    for tract in env["tracts"]:
        after = get_success_data(api.get_tract(tract["id"], agent_headers))
        assert after["status"] == "OFFERED"


# ────────────────────────── withdrawal cascade (depth 3) ─────────────

def _open_l4_with_bid():
    """MARKETED WHOLE listing L4 (80ac, min 200000) with an OPEN ONLINE auction
    (2026-08-12 10:00-12:00Z) holding one PLACED bid of 200000."""
    env = fx.setup_open_auction(
        method="ONLINE",
        title="L4",
        total_gross_acres=80,
        reserve_price_total=460000,
        tract_specs=[{
            "tract_number": 1, "gross_acres": 80, "tillable_acres": 40,
            "soil_productivity_index": 60, "min_price": 200000,
        }],
        scheduled_start="2026-08-12T10:00:00Z",
        scheduled_end="2026-08-12T12:00:00Z",
        open_at="2026-08-12T10:00:00Z",
    )
    buyer = fx.create_qualified_buyer()
    bid = get_success_data(
        fx.place_bid_fresh(buyer, env["auction"]["id"], 200000, [env["tracts"][0]["id"]])
    )
    env["buyer"] = buyer
    env["bid"] = bid
    return env


def test_withdraw_open_auction_cancels_and_voids_bids(api):
    """PRD §3.2: "The withdrawal cascade is identical from all four source
    states: every auction of the listing in `SCHEDULED`, `OPEN`, or `EXTENDED`
    moves to `CANCELLED`; every bid of those auctions in `PLACED` or `SEALED`
    moves to `VOIDED`; rights dispositions revert from `LOCKED` to `DECLARED`;
    and every tract in `REGISTERED`, `OFFERED`, or `UNSOLD` moves to
    `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/listing_withdraw_cancels_open_auction_depth3
    """
    env = _open_l4_with_bid()
    res = api.withdraw_listing(
        env["listing"]["id"], make_seller_headers(env["seller"]["id"])
    )
    listing = validate_success(res, 200)
    assert listing["status"] == "WITHDRAWN"  # hop 1
    agent_headers = make_agent_headers(env["agent"]["id"])
    auction = fx.read_auction(env["auction"]["id"], agent_headers)
    assert auction["status"] == "CANCELLED"  # hop 2
    bid = validate_success(api.get_bid(env["bid"]["id"], agent_headers), 200)
    assert bid["status"] == "VOIDED"  # hop 3


def test_withdraw_releases_tracts_and_unlocks_rights(api):
    """PRD §3.2: "The withdrawal cascade is identical from all four source
    states: every auction of the listing in `SCHEDULED`, `OPEN`, or `EXTENDED`
    moves to `CANCELLED`; every bid of those auctions in `PLACED` or `SEALED`
    moves to `VOIDED`; rights dispositions revert from `LOCKED` to `DECLARED`;
    and every tract in `REGISTERED`, `OFFERED`, or `UNSOLD` moves to
    `WITHDRAWN`."
    PRD §3.4: "Rights return from `LOCKED` to `DECLARED` when an auction ends in
    `NO_SALE` or `CANCELLED` and no active auction of the listing remains."

    Design: Difficulty/transitive_cascade/listing_withdraw_cancels_open_auction_depth3
    """
    env = _open_l4_with_bid()
    validate_success(
        api.withdraw_listing(env["listing"]["id"], make_seller_headers(env["seller"]["id"])),
        200,
    )
    agent_headers = make_agent_headers(env["agent"]["id"])
    tract = get_success_data(api.get_tract(env["tracts"][0]["id"], agent_headers))
    assert tract["status"] == "WITHDRAWN"
    rights = get_success_data(api.list_tract_rights(env["tracts"][0]["id"], agent_headers))
    assert rights[0]["status"] == "DECLARED", (
        "no active auction remains, so the disposition unlocks"
    )


def test_withdraw_under_contract_rejected(api):
    """PRD §3.2: "Withdrawal is deliberately unavailable from `UNDER_CONTRACT`
    and `CLOSED` — no transition exists from those states, and the attempt is
    rejected with `ERR_INVALID_LISTING_STATE`."

    Design: Corner/state_machines/withdraw_under_contract_rejected_invalid_state
    """
    env = fx.setup_awarded_whole(bid_amount=770000, method="LIVE")
    assert env["listing"]["status"] == "UNDER_CONTRACT"
    assert env["auction"]["status"] == "AWARDED"
    res = api.withdraw_listing(
        env["listing"]["id"], make_seller_headers(env["seller"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_INVALID_LISTING_STATE)


# ────────────────────────── conserved acreage ────────────────────────

def test_acreage_conserved_through_award(api):
    """PRD §3.2: "First, acreage: at least one tract must exist, and the tract
    acreage must reconcile to `total_gross_acres` exactly — a listing with no
    tracts, or one whose tract sum is short of or over the total, fails with
    `ERR_ACREAGE_MISMATCH`."
    PRD §3.7: "A successful award moves winning bids to `CONFIRMED_WINNER` and
    every other `PLACED` or `REVEALED` bid to `LOST`; tracts inside winning
    scopes move from `OFFERED` to `SOLD`, while `OFFERED` tracts outside every
    winning scope move to `UNSOLD`."

    Design: Difficulty/compensating_invariant/acreage_conserved_across_award_and_forfeit
    """
    env = fx.setup_awarded_combination()
    agent_headers = make_agent_headers(env["agent"]["id"])
    listing = fx.read_listing(env["listing"]["id"], agent_headers)
    total = 0
    for tract in env["tracts"]:
        after = get_success_data(api.get_tract(tract["id"], agent_headers))
        assert after["status"] == "SOLD"
        total += after["gross_acres"]
    assert total == 160 == listing["total_gross_acres"], (
        "status mutations never create or destroy acres"
    )


def test_acreage_conserved_through_forfeit(api):
    """PRD §3.7: "the listing falls from `UNDER_CONTRACT` back to `MARKETED`
    with its `version` incremented; and its `SOLD` tracts return to `OFFERED`."
    PRD §3.2: "First, acreage: at least one tract must exist, and the tract
    acreage must reconcile to `total_gross_acres` exactly — a listing with no
    tracts, or one whose tract sum is short of or over the total, fails with
    `ERR_ACREAGE_MISMATCH`."

    Design: Difficulty/compensating_invariant/acreage_conserved_across_award_and_forfeit
    """
    env = fx.setup_awarded_combination()
    agent_headers = make_agent_headers(env["agent"]["id"])
    fx.set_clock("2026-08-13T19:00:01Z")  # forfeiture cascade fires
    listing = fx.read_listing(env["listing"]["id"], agent_headers)
    total = 0
    for tract in env["tracts"]:
        after = get_success_data(api.get_tract(tract["id"], agent_headers))
        assert after["status"] == "OFFERED", "compensating action restores OFFERED"
        total += after["gross_acres"]
    assert total == 160 == listing["total_gross_acres"]


# ────────────────────────── conserved escrow dollars ─────────────────

def _terminable_env():
    """Awarded COMBINATION flow with a VERIFIED deposit, acknowledged
    disclosure, and a freshly created closing (INITIATED)."""
    env = fx.setup_awarded_combination(with_disclosure=True)
    deposit = fx.pay_and_verify_deposit(env["agent"], env["deposit"]["id"], 42000)
    env["deposit"] = deposit
    env["disclosure"] = fx.acknowledge_disclosure(env["buyer"], env["disclosure"]["id"])
    env["closing"] = fx.create_closing(
        env["agent"], env["auction"]["id"], payoff_amount=200000
    )
    return env


def test_escrow_conserved_across_payment_and_refund(api):
    """PRD §3.8: "The termination cascade is identical from all three source
    states: the `VERIFIED` deposit moves to `REFUNDED` with `amount_refunded`
    set to its `amount_received`; the winning bid moves from `CONFIRMED_WINNER`
    to `VOIDED`; the auction hops from `AWARDED` to `NO_SALE`; the listing falls
    from `UNDER_CONTRACT` to `MARKETED`; its `SOLD` tracts return to `OFFERED`;
    and both `PROVISIONAL` and `FINAL` statements of the closing move to
    `SUPERSEDED`."

    Design: Difficulty/compensating_invariant/escrow_conserved_across_payment_and_termination_refund
    """
    env = _terminable_env()
    assert env["deposit"]["status"] == "VERIFIED"
    assert_money(env["deposit"]["amount_received"], 42000.00, "amount_received")
    agent_headers = make_agent_headers(env["agent"]["id"])

    closing = validate_success(
        api.terminate_closing(env["closing"]["id"], agent_headers), 200
    )
    assert closing["overall_status"] == "TERMINATED"
    deposit = get_success_data(api.get_deposit(env["deposit"]["id"], agent_headers))
    assert deposit["status"] == "REFUNDED"
    assert_money(deposit["amount_refunded"], 42000.00, "amount_refunded")
    assert_money(deposit["amount_forfeited"], 0, "amount_forfeited")
    assert_money(deposit["amount_applied"], 0, "amount_applied")
    assert_escrow_conservation(deposit)


def test_termination_reverts_auction_listing_and_tracts(api):
    """PRD §3.8: "The termination cascade is identical from all three source
    states: the `VERIFIED` deposit moves to `REFUNDED` with `amount_refunded`
    set to its `amount_received`; the winning bid moves from `CONFIRMED_WINNER`
    to `VOIDED`; the auction hops from `AWARDED` to `NO_SALE`; the listing falls
    from `UNDER_CONTRACT` to `MARKETED`; its `SOLD` tracts return to `OFFERED`;
    and both `PROVISIONAL` and `FINAL` statements of the closing move to
    `SUPERSEDED`."

    Design: Difficulty/compensating_invariant/escrow_conserved_across_payment_and_termination_refund
    """
    env = _terminable_env()
    agent_headers = make_agent_headers(env["agent"]["id"])
    validate_success(api.terminate_closing(env["closing"]["id"], agent_headers), 200)

    bid = validate_success(api.get_bid(env["bid"]["id"], agent_headers), 200)
    assert bid["status"] == "VOIDED"
    auction = fx.read_auction(env["auction"]["id"], agent_headers)
    assert auction["status"] == "NO_SALE"
    listing = fx.read_listing(env["listing"]["id"], agent_headers)
    assert listing["status"] == "MARKETED"
    for tract in env["tracts"]:
        after = get_success_data(api.get_tract(tract["id"], agent_headers))
        assert after["status"] == "OFFERED"
