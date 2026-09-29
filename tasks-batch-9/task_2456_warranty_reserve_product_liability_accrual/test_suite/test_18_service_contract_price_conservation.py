"""The contract price is conserved across recognition, cancellation and refund.

PRD §3.6: "The identity that recognized plus deferred plus refunded equals
`total_contract_price_cents` holds both before and after the cancellation — this is a
compensating action, not a write-off."
"""

from test_helpers import (
    assert_contract_price_conserved,
    cancel_service_contract,
    create_family,
    create_service_contract,
    move_clock,
    read_service_contract,
)


def _build_world(api):
    """A 480000-cent 24-month contract sold 2026-02-01, six months into its term."""
    family = create_family(
        api,
        family_code="FAM-X",
        name="Premium Dishwasher Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=19000,
        reserve_cap_cents=50000000,
    )
    contract = create_service_contract(
        api,
        family["id"],
        contract_number="ESC-X-0001",
        sold_date="2026-02-01",
        term_months=24,
        total_contract_price_cents=480000,
        recognition_method="STRAIGHT_LINE",
    )
    return {"family": family, "contract": contract}


def test_the_identity_holds_at_inception_and_after_the_clock_moves(api):
    """Elapsed time only shifts value out of deferral into recognition.

    PRD §2.5: the logical clock "before any client has set it, reads exactly
    `2026-08-01T00:00:00Z`", six whole months after the sale under PRD §3.6's count.
    PRD §3.6: "`recognized_revenue_cents` is `total_contract_price_cents` multiplied by
    `months_elapsed`, divided by `term_months`, rounded to the nearest integer", and
    "`deferred_revenue_cents` is `total_contract_price_cents` less
    `recognized_revenue_cents` less `refunded_revenue_cents`."

    Design: Difficulty/compensating_invariant/service_contract_price_is_conserved_across_recognition_and_refund
    """
    world = _build_world(api)

    at_inception = world["contract"]
    assert at_inception["months_elapsed"] == 6
    assert at_inception["recognized_revenue_cents"] == 120000
    assert at_inception["deferred_revenue_cents"] == 360000
    assert at_inception["refunded_revenue_cents"] == 0
    assert at_inception["status"] == "ACTIVE"
    assert_contract_price_conserved(at_inception)

    move_clock(api, "2027-02-01T00:00:00Z")

    after_clock = read_service_contract(api, world["contract"]["id"])
    assert after_clock["months_elapsed"] == 12
    assert after_clock["recognized_revenue_cents"] == 240000
    assert after_clock["deferred_revenue_cents"] == 240000
    assert after_clock["refunded_revenue_cents"] == 0
    assert after_clock["status"] == "ACTIVE"
    assert_contract_price_conserved(after_clock)


def test_cancelling_converts_the_whole_deferral_into_a_refund(api):
    """The unearned balance moves across intact and the identity survives.

    PRD §3.6: "`refunded_revenue_cents` is set to whatever `deferred_revenue_cents` held
    immediately before the transition, `deferred_revenue_cents` is then set to 0,
    `cancelled_at` is stamped with the current logical-clock instant, and
    `recognized_revenue_cents` is frozen at its pre-cancellation value so that it no
    longer tracks the logical clock." PRD §3.6 also says new contracts begin with "a null
    `cancelled_at`".

    Design: Difficulty/compensating_invariant/service_contract_price_is_conserved_across_recognition_and_refund
    """
    world = _build_world(api)
    assert world["contract"]["cancelled_at"] is None
    move_clock(api, "2027-02-01T00:00:00Z")

    cancelled = cancel_service_contract(api, world["contract"]["id"])

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refunded_revenue_cents"] == 240000
    assert cancelled["deferred_revenue_cents"] == 0
    assert cancelled["recognized_revenue_cents"] == 240000
    assert cancelled["cancelled_at"] is not None
    assert_contract_price_conserved(cancelled)


def test_a_cancelled_contract_stops_tracking_the_clock_entirely(api):
    """Recognition stays frozen, so the identity cannot be broken by later time.

    PRD §2.5: "Every extended service contract still in `ACTIVE` status has its
    `months_elapsed`, `recognized_revenue_cents` and `deferred_revenue_cents` recomputed
    at the new clock position, and any such contract whose recomputed `months_elapsed` has
    reached or passed its `term_months` auto-transitions from `ACTIVE` to `EXPIRED`." A
    `CANCELLED` contract is outside that set, and PRD §3.6 adds that "`recognized_revenue_cents`
    is frozen at its pre-cancellation value so that it no longer tracks the logical clock."

    Design: Difficulty/compensating_invariant/service_contract_price_is_conserved_across_recognition_and_refund
    """
    world = _build_world(api)
    move_clock(api, "2027-02-01T00:00:00Z")
    cancel_service_contract(api, world["contract"]["id"])

    move_clock(api, "2027-08-01T00:00:00Z")

    contract = read_service_contract(api, world["contract"]["id"])
    assert contract["status"] == "CANCELLED"
    assert contract["months_elapsed"] == 12
    assert contract["recognized_revenue_cents"] == 240000
    assert contract["deferred_revenue_cents"] == 0
    assert contract["refunded_revenue_cents"] == 240000
    assert_contract_price_conserved(contract)
