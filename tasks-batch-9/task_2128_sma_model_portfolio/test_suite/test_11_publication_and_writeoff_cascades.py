"""Multi-hop cascade behaviour: the publication fan-out and the write-off chain.

Both cascades are driven by a single request and each hop fires only because the
hop before it fired. Every test here rebuilds its own world from scratch and
asserts the whole chain — the rows each hop writes and the rows it must leave
alone.
"""
from test_helpers import (
    TEST_USERS,
    create_active_distribution,
    create_approved_version,
    create_block,
    create_distribution,
    create_invoice,
    create_sponsor,
    evaluate_drift,
    fund_account,
    get_account,
    get_block,
    get_model_version,
    get_success_data,
    get_trade_order,
    issue_invoice,
    list_trade_orders,
    open_account,
    rebalance,
    setup_drifted_account_with_orders,
    suspend_account,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["portfolio_manager_headers"]
BILLING = TEST_USERS["billing_officer_headers"]

CLOCK_START_UTC = "2026-08-01T00:00:00.000Z"
DEADLINE_TWO_DAYS_UTC = "2026-08-03T00:00:00.000Z"

STANDARD_LOTS = [
    ("ALFA", 1250, 12_500_000),
    ("BETA", 1500, 7_500_000),
    ("CETA", 1000, 2_500_000),
]
STANDARD_CASH = 2_500_000


# ---------------------------------------------------------------------------
# Shared world builders
# ---------------------------------------------------------------------------
def _ceta_order(env):
    """The BUY 980 CETA order the rebalance generated for the env's account."""
    ceta_id = env["securities"]["CETA"]["id"]
    return next(o for o in env["orders"] if o["security_id"] == ceta_id)


def _second_drifted_account(env, account_number="ACC-002", with_orders=False):
    """Open a sibling account on the same sponsor and model, optionally driving
    it to DRIFTED with its own full set of PROPOSED rebalance orders."""
    account = open_account(env, account_number)
    if with_orders:
        fund_account(env, account, STANDARD_CASH, STANDARD_LOTS)
        evaluate_drift(account["id"], env["sponsor"]["id"])
        rebalance(account["id"], env["sponsor"]["id"])
    return get_account(account["id"])


def _publication_world(skipped_account=False, skipped_account_orders=False):
    """v1 published and actively distributed, one DRIFTED account holding three
    PROPOSED rebalance orders against v1, and an APPROVED successor version
    waiting to be published."""
    env = setup_drifted_account_with_orders()
    env["distribution_v1"] = create_active_distribution(
        env["sponsor"]["id"], env["model_version"]["id"]
    )
    if skipped_account:
        sibling = _second_drifted_account(env, with_orders=skipped_account_orders)
        suspend_account(sibling["id"])
        env["sibling_account"] = get_account(sibling["id"])
    env["successor"] = create_approved_version(
        env["model"]["id"], [("ALFA", 6000), ("BETA", 4000)], env["securities"]
    )
    return env


def _write_off_world(sibling_account=False, block_the_ceta_order=False):
    """The same DRIFTED account with three PROPOSED orders, carrying one ISSUED
    invoice for 2026-01-01..2026-04-01 on a 30,000,000c average daily value."""
    env = setup_drifted_account_with_orders()
    if block_the_ceta_order:
        env["block"] = create_block(
            [_ceta_order(env)["id"]], env["sponsor"]["id"]
        )
    if sibling_account:
        env["sibling_account"] = _second_drifted_account(env, with_orders=True)
    invoice = create_invoice(env["account"]["id"])
    env["invoice"] = issue_invoice(invoice["id"])
    return env


# ---------------------------------------------------------------------------
# Cascade A — publication fan-out
# ---------------------------------------------------------------------------
def test_publish_supersedes_prior_version_and_lapses_only_active_distributions(api):
    """PRD §3.3: "The **first hop** stamps `published_at` with the current logical clock instant, repoints the owning strategy's `published_model_version_id` at the newly published version, and advances both the version's `version` and the strategy's `version`."

    PRD §3.3: "The **second hop** exists only because a strategy may hold at most one published version at a time. If a sibling version of the same strategy was sitting in `PUBLISHED`, it transitions `PUBLISHED → SUPERSEDED` and has its `superseded_at` stamped with the same clock instant. When the strategy had no previously published version, this hop and everything downstream of it simply does not occur."

    PRD §3.3: "The **third hop** exists only because a distribution may not carry a superseded version. Every sponsor distribution whose `model_version_id` is the just-superseded version and whose `status` is `ACTIVE` transitions `ACTIVE → LAPSED` with `lapsed_at` stamped at the clock instant. Distributions still in `PENDING` are left alone; `LAPSED` is terminal for a distribution."

    Design: Difficulty/transitive_cascade/publish_cascade_supersede_lapse_notify_stale_depth_five
    """
    env = _publication_world()

    # A second sponsor receives the same v1, but never activates it: a PENDING
    # distribution has not been fed to anyone and must survive the fan-out.
    other_sponsor = create_sponsor(platform_code="SOUT", name="Southline Partners")
    pending_dist = create_distribution(
        other_sponsor["id"], env["model_version"]["id"]
    )

    response = api.publish_model_version(env["successor"]["id"], MANAGER)
    validate_success(response, 200)
    published = get_success_data(response)

    # Hop 1: the published version and the strategy pointer.
    assert published["status"] == "PUBLISHED"
    assert published["published_at"] == CLOCK_START_UTC
    model = get_success_data(api.get_model(env["model"]["id"], ADMIN))
    assert model["published_model_version_id"] == env["successor"]["id"]

    # Hop 2: the sibling that was PUBLISHED is superseded at the same instant.
    prior = get_model_version(env["model_version"]["id"])
    assert prior["status"] == "SUPERSEDED"
    assert prior["superseded_at"] == CLOCK_START_UTC

    # Hop 3: the ACTIVE distribution of the superseded version lapses.
    lapsed = get_success_data(
        api.get_distribution(env["distribution_v1"]["id"], ADMIN)
    )
    assert lapsed["status"] == "LAPSED"
    assert lapsed["lapsed_at"] == CLOCK_START_UTC

    # Hop 3 skips the PENDING distribution entirely — no field is written.
    untouched = get_success_data(api.get_distribution(pending_dist["id"], ADMIN))
    assert untouched["status"] == "PENDING"
    assert untouched["lapsed_at"] is None
    assert untouched["activated_at"] is None
    assert untouched["version"] == pending_dist["version"]


def test_publish_notifies_the_fed_account_and_skips_a_suspended_one(api):
    """PRD §3.3: "Consider every account whose `sponsor_id` appears among the sponsors of the distributions that just lapsed, whose `current_model_version_id` is the superseded version, and whose `implementation_status` is either `SYNCED` or `DRIFTED`. Each such account transitions to `PENDING_IMPLEMENTATION`; its `pending_model_version_id` is set to the newly published version; its `notified_at` is stamped at the clock instant; its `implementation_deadline` is set to `notified_at` advanced by the sponsor's `implementation_lag_days` in days — for a sponsor on the default two-day contract, forty-eight hours after notification; and its `implemented_late` flag is reset to false. This cascade is conditional, not blanket: an account already in `SUSPENDED` or already in `PENDING_IMPLEMENTATION` is skipped entirely and none of those fields are written. An account arriving from `DRIFTED` keeps whatever `drift_bps` its last evaluation produced — the number is retained, it simply no longer gates a rebalance, because the account is now pending implementation rather than drifted."

    Design: Difficulty/transitive_cascade/publish_cascade_supersede_lapse_notify_stale_depth_five
    """
    env = _publication_world(skipped_account=True)
    frozen_before = env["sibling_account"]

    validate_success(api.publish_model_version(env["successor"]["id"], MANAGER), 200)

    # Hop 4 on the account the lapsed distribution actually fed.
    account = get_account(env["account"]["id"])
    assert account["implementation_status"] == "PENDING_IMPLEMENTATION"
    assert account["pending_model_version_id"] == env["successor"]["id"]
    assert account["current_model_version_id"] == env["model_version"]["id"]
    assert account["notified_at"] == CLOCK_START_UTC
    assert account["implementation_deadline"] == DEADLINE_TWO_DAYS_UTC
    assert account["implemented_late"] is False
    assert account["drift_bps"] == 1000

    # Hop 4 skips the already-SUSPENDED sibling: not one of those fields moves.
    frozen = get_account(frozen_before["id"])
    assert frozen["implementation_status"] == "SUSPENDED"
    assert frozen["pending_model_version_id"] is None
    assert frozen["notified_at"] is None
    assert frozen["implementation_deadline"] is None
    assert frozen["current_model_version_id"] == env["model_version"]["id"]
    assert frozen["version"] == frozen_before["version"]


def test_publish_stales_open_orders_of_the_notified_account_only(api):
    """PRD §3.3: "Every trade order belonging to one of the accounts touched by the fourth hop, whose `model_version_id` is the superseded version and whose `status` is either `PROPOSED` or `BLOCKED`, transitions to `STALE`. A staled order that was sitting in a block also has its `block_id` cleared, and the block it leaves recomputes its `requested_shares` and its `order_count` from its remaining members. `STALE` is terminal for a trade order."

    Design: Difficulty/transitive_cascade/publish_cascade_supersede_lapse_notify_stale_depth_five
    """
    env = _publication_world(skipped_account=True, skipped_account_orders=True)
    ceta_order = _ceta_order(env)
    sibling_id = env["sibling_account"]["id"]

    validate_success(api.publish_model_version(env["successor"]["id"], MANAGER), 200)

    # Hop 5 on the notified account: every open order goes terminal.
    staled = get_trade_order(ceta_order["id"])
    assert staled["status"] == "STALE"
    assert staled["block_id"] is None
    assert len(list_trade_orders(account_id=env["account"]["id"], status="STALE")) == 3
    assert len(list_trade_orders(account_id=env["account"]["id"], status="PROPOSED")) == 0

    # The suspended sibling was skipped by hop 4, so hop 5 never reaches its
    # orders even though they name the very same superseded version.
    assert len(list_trade_orders(account_id=sibling_id, status="PROPOSED")) == 3
    assert len(list_trade_orders(account_id=sibling_id, status="STALE")) == 0


# ---------------------------------------------------------------------------
# Cascade C — the write-off chain
# ---------------------------------------------------------------------------
def test_write_off_drives_billing_then_forces_the_implementation_dimension(api):
    """PRD §3.9: "It is available only on an `ISSUED` invoice whose account is already `DELINQUENT`, and a write-off attempted against an account in any other billing state is refused with `ERR_INVALID_STATE`. Its first hop moves the invoice `ISSUED → WRITTEN_OFF`. The second hop, which fires only because the first did, moves the account's billing dimension `DELINQUENT → WRITTEN_OFF`, a terminal state. The third hop fires only because the second did, on the principle that an account whose fees have been abandoned may not keep trading: the account's `implementation_status` is forced to `SUSPENDED` regardless of whatever value it held before, and this is the single point at which the billing dimension reaches into the implementation dimension. The fourth hop fires only because the third did: every trade order of that account in status `PROPOSED` or `BLOCKED` transitions to `CANCELLED`, with any `block_id` cleared and the affected blocks recomputing their `requested_shares` and `order_count`. Throughout all of it the account's `fees_billed_ytd_cents` is **not** reduced — a written-off fee stays billed, which is precisely what distinguishes a write-off from a void."

    Design: Difficulty/transitive_cascade/write_off_cascade_billing_to_implementation_to_orders_depth_four
    """
    env = _write_off_world()
    account_id = env["account"]["id"]
    invoice_id = env["invoice"]["id"]

    # Delinquency alone touches only the billing dimension.
    validate_success(api.mark_fee_invoice_delinquent(invoice_id, BILLING), 200)
    account = get_account(account_id)
    assert account["billing_status"] == "DELINQUENT"
    assert account["implementation_status"] == "DRIFTED"

    validate_success(api.write_off_fee_invoice(invoice_id, BILLING), 200)

    # Hop 1: the invoice itself.
    invoice = get_success_data(api.get_fee_invoice(invoice_id, BILLING))
    assert invoice["status"] == "WRITTEN_OFF"

    # Hops 2 and 3: billing goes terminal and reaches into implementation.
    account = get_account(account_id)
    assert account["billing_status"] == "WRITTEN_OFF"
    assert account["implementation_status"] == "SUSPENDED"

    # A written-off fee stays billed, and the write-off never touches cash.
    assert account["fees_billed_ytd_cents"] == 65342
    assert account["cash_cents"] == 2500000


def test_write_off_cancels_the_accounts_open_orders_and_leaves_siblings_alone(api):
    """PRD §3.9: "The fourth hop fires only because the third did: every trade order of that account in status `PROPOSED` or `BLOCKED` transitions to `CANCELLED`, with any `block_id` cleared and the affected blocks recomputing their `requested_shares` and `order_count`."

    Design: Difficulty/transitive_cascade/write_off_cascade_billing_to_implementation_to_orders_depth_four
    """
    env = _write_off_world(sibling_account=True)
    account_id = env["account"]["id"]
    invoice_id = env["invoice"]["id"]
    ceta_order = _ceta_order(env)
    sibling = env["sibling_account"]

    validate_success(api.mark_fee_invoice_delinquent(invoice_id, BILLING), 200)
    validate_success(api.write_off_fee_invoice(invoice_id, BILLING), 200)

    cancelled = get_trade_order(ceta_order["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["block_id"] is None
    assert len(list_trade_orders(account_id=account_id, status="CANCELLED")) == 3
    assert len(list_trade_orders(account_id=account_id, status="PROPOSED")) == 0

    # The cascade is scoped to the written-off account: a sibling account on the
    # same sponsor keeps both its dimensions and every one of its open orders.
    untouched = get_account(sibling["id"])
    assert untouched["billing_status"] == "CURRENT"
    assert untouched["implementation_status"] == "DRIFTED"
    assert len(list_trade_orders(account_id=sibling["id"], status="PROPOSED")) == 3
    assert len(list_trade_orders(account_id=sibling["id"], status="CANCELLED")) == 0


def test_write_off_clears_block_membership_and_recomputes_the_block(api):
    """PRD §3.9: "The fourth hop fires only because the third did: every trade order of that account in status `PROPOSED` or `BLOCKED` transitions to `CANCELLED`, with any `block_id` cleared and the affected blocks recomputing their `requested_shares` and `order_count`."

    Design: Difficulty/transitive_cascade/write_off_cascade_billing_to_implementation_to_orders_depth_four
    """
    env = _write_off_world(block_the_ceta_order=True)
    account_id = env["account"]["id"]
    invoice_id = env["invoice"]["id"]
    ceta_order = _ceta_order(env)
    block = env["block"]

    # The blocked order is a member of an OPEN street block before the cascade.
    assert block["requested_shares"] == 980
    assert block["order_count"] == 1
    assert get_trade_order(ceta_order["id"])["status"] == "BLOCKED"

    validate_success(api.mark_fee_invoice_delinquent(invoice_id, BILLING), 200)
    validate_success(api.write_off_fee_invoice(invoice_id, BILLING), 200)

    cancelled = get_trade_order(ceta_order["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["block_id"] is None

    recomputed = get_block(block["id"])
    assert recomputed["requested_shares"] == 0
    assert recomputed["order_count"] == 0

    # Both the BLOCKED member and the two still-PROPOSED orders were cancelled.
    assert len(list_trade_orders(account_id=account_id, status="CANCELLED")) == 3
    assert len(list_trade_orders(account_id=account_id, status="BLOCKED")) == 0
    assert len(list_trade_orders(account_id=account_id, status="PROPOSED")) == 0
