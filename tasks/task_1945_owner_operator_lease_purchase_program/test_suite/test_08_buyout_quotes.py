"""Buyout quotes: scheduled vs early pricing, pinned evaluation order, OCC on
the lease version, supersede, expiry, eligibility, and acceptance cascades."""
from test_helpers import (
    validate_success, validate_error, api_client,
    ApiErrorId, TEST_USERS, make_driver_headers,
    create_active_lease, set_clock, create_buyout_quote, read_lease_version,
    finalize_healthy_week, finalize_short_week, offer_and_accept_lane,
    create_buyout_quote_payload,
)

ADMIN = TEST_USERS["lease_admin_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


# ─── Queue A: difficulty/dual_variant_calc ───────────

def _scenario_early_and_scheduled_quotes():
    """ACTIVE lease (base price 4500000, weekly 65000, start 2026-08-03, term
    52): an EARLY quote at clock 2026-08-12, then a SCHEDULED quote at clock
    2027-08-03 (past the 2027-08-02 term end)."""
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    set_clock("2026-08-12T00:00:00Z")
    q1 = create_buyout_quote(lease_id, "EARLY")
    set_clock("2027-08-03T00:00:00Z")
    q2 = create_buyout_quote(lease_id, "SCHEDULED")
    scenario["q1"] = q1
    scenario["q2"] = q2
    return scenario


def test_buyout_price_early_variant_adds_fee(api):
    """PRD section 3.8: "Step one computes `quoted_price_cents`: a `SCHEDULED`
    quote takes exactly the lease's `buyout_base_price_cents`; an `EARLY` quote
    adds an early fee — the remaining whole weeks of the term (the term in weeks
    minus the whole weeks elapsed from `start_date` to the current logical clock,
    floored at zero) multiplied by `weekly_payment_cents` multiplied by
    one-tenth, with the product rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/buyout_price_scheduled_vs_early
    """
    scenario = _scenario_early_and_scheduled_quotes()
    q1 = validate_success(api.get_buyout_quote(scenario["q1"]["id"], ADMIN), 200)
    assert q1["quoted_price_cents"] == 4831500, (
        "EARLY at weeks_elapsed 1: 4500000 + round_half_up(51*65000*0.10) = 331500 fee")
    assert q1["quote_kind"] == "EARLY"


def test_buyout_price_scheduled_variant_and_supersede(api):
    """PRD section 3.8: "a `SCHEDULED` quote takes exactly the lease's
    `buyout_base_price_cents`". PRD section 3.8: "Creating a quote supersedes any
    prior `GENERATED` quote of the same lease (which moves to `SUPERSEDED`,
    terminal) and increments the lease's `version` by one".

    Design: Difficulty/dual_variant_calc/buyout_price_scheduled_vs_early
    """
    scenario = _scenario_early_and_scheduled_quotes()
    q2 = validate_success(api.get_buyout_quote(scenario["q2"]["id"], ADMIN), 200)
    assert q2["quoted_price_cents"] == 4500000, "SCHEDULED: base price, no fee"
    assert q2["status"] == "GENERATED"

    q1 = validate_success(api.get_buyout_quote(scenario["q1"]["id"], ADMIN), 200)
    assert q1["status"] == "SUPERSEDED", "the newer quote supersedes the prior GENERATED one"
    assert q1["quoted_price_cents"] != q2["quoted_price_cents"], (
        "the same lease prices differently under the two variants")


# ─── Queue A: difficulty/combinatorial_formula (buyout order) ──

def _scenario_with_arrears_and_escrow_for_quote():
    """ACTIVE lease with lane ACCEPTED: W1 finalized healthy (escrow +20000),
    W2 and W3 finalized as all-zero declined short payments (missed 2, arrears
    130000). Clock left at 2026-08-28 (weeks_elapsed 3, remaining_weeks 49)."""
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    offer_and_accept_lane(lease_id, scenario["operator"]["id"])
    finalize_healthy_week(lease_id, "2026-08-03", "2026-08-12T00:00:00Z")
    finalize_short_week(lease_id, "2026-08-10", "2026-08-19T00:00:00Z")
    finalize_short_week(lease_id, "2026-08-17", "2026-08-26T00:00:00Z")
    set_clock("2026-08-28T00:00:00Z")
    scenario["lease"] = validate_success(api_client.get_lease_agreement(lease_id, ADMIN), 200)
    return scenario


def test_buyout_evaluation_order_price_and_arrears(api):
    """PRD section 3.8: "Step two snapshots the lease's current `arrears_cents`
    into `arrears_carried_cents`." PRD section 3.4: "a short payment increments
    `missed_payment_count` by one and adds the shortfall (the scheduled weekly
    payment minus the applied amount) to `arrears_cents`".

    Design: Difficulty/combinatorial_formula/buyout_evaluation_order_pinned
    """
    scenario = _scenario_with_arrears_and_escrow_for_quote()
    lease = scenario["lease"]
    assert lease["arrears_cents"] == 130000, "two short finalizations of 65000 each"
    assert lease["missed_payment_count"] == 2

    quote = create_buyout_quote(lease["id"], "EARLY")
    assert quote["quoted_price_cents"] == 4818500, (
        "4500000 + round_half_up(49*65000*0.10) = 318500 fee at weeks_elapsed 3")
    assert quote["arrears_carried_cents"] == 130000


def test_buyout_evaluation_order_credit_and_amount_due(api):
    """PRD section 3.8: "Step three computes `escrow_credit_cents` as the lesser
    of the escrow account's current balance and the quoted price plus the carried
    arrears. Step four sets `amount_due_cents` to the quoted price plus carried
    arrears minus the escrow credit, floored at zero. The escrow balance is read
    at step three and is not refunded separately on acceptance — acceptance
    applies it."

    Design: Difficulty/combinatorial_formula/buyout_evaluation_order_pinned
    """
    scenario = _scenario_with_arrears_and_escrow_for_quote()
    quote = create_buyout_quote(scenario["lease"]["id"], "EARLY")
    assert quote["escrow_credit_cents"] == 20000, "min(balance 20000, 4818500+130000)"
    assert quote["amount_due_cents"] == 4928500, "max(0, 4818500 + 130000 - 20000)"


# ─── Queue B: corner/state_machines + corner/validations + cross-cutting ──

def test_buyout_accept_side_effects_and_double_accept_rejected(api):
    """PRD section 3.8: "Acceptance is the second route to `COMPLETED`: the lease
    moves `ACTIVE` (or `DEFAULTED`) → `COMPLETED`, the truck `LEASED` → `SOLD`,
    and the escrow is applied to the purchase — the applied amount is the lesser
    of the balance and the quoted price plus arrears, the balance falls by it,
    `total_applied_cents` grows by it, and the account closes regardless of
    remainder, since the credit was priced into the amount due." PRD section 3.8:
    "Accepting requires the quote to be `GENERATED` (otherwise
    `ERR_QUOTE_NOT_GENERATED`)".

    Design: Corner/state_machines/buyout_accept_side_effects_and_double_accept_rejected
    """
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    driver = make_driver_headers(scenario["operator"]["id"])
    set_clock("2026-08-12T00:00:00Z")
    quote = create_buyout_quote(lease_id, "EARLY")

    accepted = validate_success(api.accept_buyout_quote(quote["id"], driver), 200)
    assert accepted["status"] == "ACCEPTED"

    lease = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert lease["status"] == "COMPLETED"
    truck = validate_success(api.get_truck(scenario["truck"]["id"], ADMIN), 200)
    assert truck["status"] == "SOLD"
    escrow = validate_success(api.get_escrow_account(scenario["escrow"]["id"], ADMIN), 200)
    assert escrow["status"] == "CLOSED"
    assert escrow["balance_cents"] == 0
    assert escrow["total_applied_cents"] == 0

    res = api.accept_buyout_quote(quote["id"], driver)
    validate_error(res, ApiErrorId.ERR_QUOTE_NOT_GENERATED.value)


def test_quote_accept_after_expiry_rejected(api):
    """PRD section 3.8: "The quote's `expires_on` is stamped seven days after its
    creation." PRD section 3.8: "Accepting requires the quote to be `GENERATED`
    (otherwise `ERR_QUOTE_NOT_GENERATED`), unexpired against the logical clock
    (`ERR_QUOTE_EXPIRED`, HTTP 409, once `expires_on` has been reached)".

    Design: Corner/state_machines/quote_accept_after_expiry_rejected
    """
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    driver = make_driver_headers(scenario["operator"]["id"])
    set_clock("2026-08-12T00:00:00Z")
    quote = create_buyout_quote(lease_id, "EARLY")

    # Created 2026-08-12 -> expires_on 2026-08-19; clock moves past it.
    set_clock("2026-08-20T00:00:00Z")
    res = api.accept_buyout_quote(quote["id"], driver)
    validate_error(res, ApiErrorId.ERR_QUOTE_EXPIRED.value)

    after = validate_success(api.get_buyout_quote(quote["id"], ADMIN), 200)
    assert after["status"] == "GENERATED", "rejected acceptance leaves the quote GENERATED"
    lease = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert lease["status"] == "ACTIVE"


def test_scheduled_buyout_before_term_returns_422(api):
    """PRD section 3.8: "Two eligibility rules gate generation: a `SCHEDULED`
    quote requires the logical clock to have reached the term end, and any quote
    requires the lease to be `ACTIVE` or `DEFAULTED` — violations draw
    `ERR_BUYOUT_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/scheduled_buyout_before_term_returns_422
    """
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    set_clock("2026-08-12T00:00:00Z")

    res = api.create_buyout_quote(
        create_buyout_quote_payload(lease_id, "SCHEDULED", read_lease_version(lease_id)),
        ADMIN)
    validate_error(res, ApiErrorId.ERR_BUYOUT_NOT_ELIGIBLE.value)


def test_buyout_create_stale_version_returns_412(api):
    """PRD section 2.7: "If the lease's current `version` differs from
    `expected_lease_version` — because any write, including a prior quote
    creation, has advanced it — the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/buyout_create_stale_version_returns_412
    """
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    stale_version = read_lease_version(lease_id)
    q1 = create_buyout_quote(lease_id, "EARLY", expected_lease_version=stale_version)
    assert q1["status"] == "GENERATED"

    # The first create bumped the lease version: the same expectation is stale.
    res = api.create_buyout_quote(
        create_buyout_quote_payload(lease_id, "EARLY", stale_version), ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)

    quotes = validate_success(api.list_buyout_quotes(ADMIN, params={"lease_id": lease_id}), 200)
    generated = [q for q in quotes if q["status"] == "GENERATED"]
    assert len(generated) == 1 and generated[0]["id"] == q1["id"], (
        "exactly one GENERATED quote survives")


def test_buyout_create_fresh_version_supersedes_prior(api):
    """PRD section 3.8: "Creating a quote supersedes any prior `GENERATED` quote
    of the same lease (which moves to `SUPERSEDED`, terminal) and increments the
    lease's `version` by one — the very mutation the OCC field guards against on
    a subsequent create."

    Design: Corner/cross_cutting_layers/buyout_create_fresh_version_supersedes_prior
    """
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    lv1 = read_lease_version(lease_id)
    q1 = create_buyout_quote(lease_id, "EARLY", expected_lease_version=lv1)

    lv2 = read_lease_version(lease_id)
    assert lv2 == lv1 + 1, "first quote create bumped the lease version by exactly 1"

    q2 = create_buyout_quote(lease_id, "EARLY", expected_lease_version=lv2)
    lv3 = read_lease_version(lease_id)
    assert lv3 == lv2 + 1, "second quote create bumped it again by exactly 1"

    q1_after = validate_success(api.get_buyout_quote(q1["id"], ADMIN), 200)
    assert q1_after["status"] == "SUPERSEDED"
    q2_after = validate_success(api.get_buyout_quote(q2["id"], ADMIN), 200)
    assert q2_after["status"] == "GENERATED"
