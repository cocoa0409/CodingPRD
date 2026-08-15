"""Earnest-money deadlines and buyer qualification timing (PRD §3.1, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_deposit,
    assert_instant_equal,
    assert_money,
    get_success_data,
    make_agent_headers,
    make_buyer_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_earnest_money_floor_and_due_timestamp(api):
    """PRD §3.7: "The `amount_due` is three percent of the winning bid's amount,
    rounded half-up to 2 decimal places, but never less than a $10,000 floor;
    the `due_at` deadline is exactly forty-eight hours after the award
    timestamp; and `amount_received`, `amount_refunded`, `amount_forfeited`, and
    `amount_applied` all start at zero on a `PENDING` deposit."

    Design: Corner/calculations/earnest_money_floor_and_due_timestamp
    """
    # Sole NE comp values the 80ac/SPI60 tract at 180000 provisionally, so the
    # reserve floor (153000) passes against reserve 200000.
    fx.post_comparable(
        county="Lancaster", state_code="NE", sale_date="2026-01-15T00:00:00Z",
        sale_price_total=300000,
    )
    env = fx.setup_awarded_whole(
        bid_amount=250000,
        method="LIVE",
        county="Lancaster",
        state_code="NE",
        total_gross_acres=80,
        reserve_price_total=200000,
        tract_specs=[{
            "tract_number": 1, "gross_acres": 80, "tillable_acres": 60,
            "soil_productivity_index": 60, "min_price": 150000,
        }],
        comparables="none",
    )
    deposit = env["deposit"]
    assert_deposit(deposit)
    # 3% of 250000 is 7500, below the 10000 floor: the floor binds.
    assert_money(deposit["amount_due"], 10000.00, "amount_due")
    # Award ran at 2026-08-10T19:00:00Z; due_at is exactly +48h.
    assert_instant_equal(deposit["due_at"], "2026-08-12T19:00:00Z", "due_at")
    assert deposit["status"] == "PENDING"
    assert_money(deposit["amount_received"], 0, "amount_received")


def test_verify_deposit_before_payment_rejected(api):
    """PRD §3.7: "Verification moves a deposit from `RECEIVED` to `VERIFIED`, or
    from `LATE` to `VERIFIED` when late funds are accepted; from any other state
    it is `ERR_INVALID_DEPOSIT_STATE`."

    Design: Corner/state_machines/verify_deposit_before_payment_rejected
    """
    env = fx.setup_awarded_whole(bid_amount=770000, method="LIVE")
    deposit = env["deposit"]
    assert deposit["status"] == "PENDING"
    assert_money(deposit["amount_due"], 23100.00, "amount_due")  # 3% of 770000
    res = api.verify_deposit(deposit["id"], fx.ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_DEPOSIT_STATE)


def test_emd_grace_boundary_not_yet_forfeited(api):
    """PRD §3.7: "When the logical clock passes the deposit's `due_at` by more
    than a further twenty-four hours of grace while the deposit is still
    `PENDING`, the sweep moves it to `FORFEITED`; the same sweep moves a `LATE`
    deposit to `FORFEITED` on the identical condition."
    PRD §3.7: "The clock sweep independently moves a still-underpaid deposit
    from `PENDING` to `LATE` once the clock passes `due_at`."

    Design: Corner/cross_cutting/emd_forfeit_grace_boundary_not_yet_forfeited
    """
    env = fx.setup_awarded_whole(bid_amount=770000, method="LIVE")
    # due_at is 2026-08-12T19:00:00Z; at exactly due_at + 24h the strict "more
    # than" forfeiture condition is not yet met, but the deposit is late.
    fx.set_clock("2026-08-13T19:00:00Z")
    deposit = get_success_data(
        api.get_deposit(env["deposit"]["id"], make_agent_headers(env["agent"]["id"]))
    )
    assert deposit["status"] == "LATE", (
        "at clock == due_at + 24h the deposit is LATE, not yet FORFEITED"
    )


def test_qualification_expiry_and_requalification_cycle(api):
    """PRD §3.1: "when the logical clock reaches or passes a qualified buyer's
    `qualification_expires_at`, the buyer moves from `QUALIFIED` to `EXPIRED`"
    PRD §3.1: "Re-qualification is permitted from `EXPIRED` — the admin supplies
    a fresh `qualification_expires_at`, which must be strictly after the logical
    clock, and a value not in the future is rejected with `ERR_VALIDATION` — but
    `DISQUALIFIED` is terminal and may never be qualified again."
    PRD §3.6: "the bidder's `qualification_status` must be `QUALIFIED` with the
    logical clock strictly before `qualification_expires_at`, else
    `ERR_BUYER_NOT_QUALIFIED`"

    Design: Corner/cross_cutting/qualification_expiry_and_requalification_cycle
    """
    env = fx.setup_marketed_listing()
    auction = fx.schedule_auction(
        env["agent"], env["listing"]["id"], method="ONLINE",
        scheduled_start="2026-08-19T10:00:00Z",
        scheduled_end="2026-08-21T10:00:00Z",
    )
    buyer = fx.create_qualified_buyer(expires_at="2026-08-20T00:00:00Z")
    # Land exactly on the expiry instant; "reaches or passes" expires the buyer.
    auction = fx.open_auction_at(env["agent"], auction["id"], "2026-08-20T00:00:00Z")
    buyer_after = validate_success(api.get_buyer(buyer["id"], fx.ADMIN), 200)
    assert buyer_after["qualification_status"] == "EXPIRED"

    res = fx.place_bid_fresh(buyer, auction["id"], 700000, [env["tracts"][0]["id"]])
    validate_error(res, ApiErrorId.ERR_BUYER_NOT_QUALIFIED)

    requalified = fx.qualify_buyer(buyer["id"], "2026-09-01T00:00:00Z")
    assert requalified["qualification_status"] == "QUALIFIED"
    bid = get_success_data(
        fx.place_bid_fresh(buyer, auction["id"], 700000, [env["tracts"][0]["id"]])
    )
    assert bid["status"] == "PLACED"


def test_agent_who_recorded_cannot_verify(api):
    """PRD §3.7: "Verification is the back office's exclusive act, and the
    segregation of duties is deliberate: payments are recorded by a
    `BrokerAgent`, but verification is `PlatformAdmin`-only, so the agent who
    recorded funds can never clear them."

    Design: Corner/rbac/rbac_agent_cannot_verify_deposit
    """
    env = fx.setup_awarded_whole(bid_amount=770000, method="LIVE")
    deposit = fx.record_payment(env["agent"], env["deposit"]["id"], 23100)
    assert deposit["status"] == "RECEIVED"
    res = api.verify_deposit(deposit["id"], make_agent_headers(env["agent"]["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
