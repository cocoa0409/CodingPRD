"""The five-step settlement and the release cascade termination sets off."""

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import fixtures as fx

DISPUTE_CLOCK = "2026-09-30T12:00:00Z"
NOTICE_CLOCK = "2026-10-01T00:00:00Z"
NOTICE_DATE = "2026-10-01"
EFFECTIVE_DATE = "2026-11-19"
TERMINATION_CLOCK = "2026-11-19T10:00:00Z"

# Nineteen whole days of November, both endpoints included, at 7172 a day.
PRORATED_FINAL_MONTH_CENTS = 136268
# Ten days of the same daily rent, credited back through a resolved dispute.
AWARDED_CREDIT_CENTS = 71720
CREDIT_REDUCED_BASE_CENTS = 64548
LOW_TIER_FEE_CENTS = 3227
CREDITED_SETTLEMENT_TOTAL_CENTS = 67775
# What the fee would be if the tier were chosen on the uncredited base, or if
# the high rate were applied to the reduced one.
HIGH_RATE_ON_REDUCED_BASE_CENTS = 5164
HIGH_RATE_TOTAL_CENTS = 69712
UNCREDITED_TIER_TOTAL_CENTS = 75449
CREDITED_BALANCE_CENTS = 285925

# With no dispute credit the base clears one thousand dollars, so the high
# tier rate applies to the whole prorated month.
HIGH_TIER_FEE_CENTS = 10901
UNCREDITED_SETTLEMENT_TOTAL_CENTS = 147169
UNCREDITED_BALANCE_CENTS = 147169

CREDIT_REMEDY = "Rent credit for ten days of degraded service"


def _credited_tenancy_under_notice(api):
    """September charged, ten days of it credited, notice given for November."""
    state = fx.setup_charged_lease(api)
    fx.setup_resolved_dispute(
        api,
        occupied_state=state,
        dispute_clock=DISPUTE_CLOCK,
        credit_offer_cents=AWARDED_CREDIT_CENTS,
        remedy=CREDIT_REMEDY,
    )
    fx.setup_lease_under_notice(
        api,
        occupied_state=state,
        reason="CONVENIENCE",
        notice_date=NOTICE_DATE,
        effective_date=EFFECTIVE_DATE,
        notice_clock=NOTICE_CLOCK,
    )
    return state


def _terminate_on_the_effective_date(api, state):
    fx.set_clock(api, TERMINATION_CLOCK)
    return fx.terminate_lease(api, state["lease"]["id"])


def test_the_awarded_credit_reduces_the_fee_base_before_the_tier_is_chosen(api):
    """Ten days of credit drop the base under one thousand dollars.

    PRD: "Step three computes the fee base as the prorated rent less those awarded credits, floored at 0 — credits reduce the base **before** the tier is chosen."

    Design: Difficulty/combinatorial_formula/early_termination_fee_tier_keyed_on_credit_reduced_base
    """
    state = _credited_tenancy_under_notice(api)
    assert state["dispute"]["status"] == "CLOSED_RESOLVED"
    assert state["dispute"]["credit_award_cents"] == AWARDED_CREDIT_CENTS
    assert state["lease"]["daily_rent_cents"] == const.BASE_DAILY_RENT_CENTS

    terminated = _terminate_on_the_effective_date(api, state)

    assert terminated["early_termination_fee_cents"] == LOW_TIER_FEE_CENTS
    assert terminated["settlement_total_cents"] == CREDITED_SETTLEMENT_TOTAL_CENTS
    # The base is what the tier was read from, and it is the reduced figure.
    assert (
        terminated["settlement_total_cents"] - terminated["early_termination_fee_cents"]
        == CREDIT_REDUCED_BASE_CENTS
    )
    assert terminated["early_termination_fee_cents"] != HIGH_RATE_ON_REDUCED_BASE_CENTS
    assert terminated["settlement_total_cents"] != UNCREDITED_TIER_TOTAL_CENTS


def test_the_low_tier_rate_is_selected_on_that_reduced_base(api):
    """Below one thousand dollars the fee is five percent, not eight.

    PRD: "Step four selects the tier rate on that reduced base: a fee base below 100000 cents, that is below one thousand dollars, takes the low rate of five percent, and a fee base of 100000 cents or more takes the high rate of eight percent."

    Design: Difficulty/combinatorial_formula/early_termination_fee_tier_keyed_on_credit_reduced_base
    """
    state = _credited_tenancy_under_notice(api)

    terminated = _terminate_on_the_effective_date(api, state)

    assert CREDIT_REDUCED_BASE_CENTS < 100000
    assert terminated["early_termination_fee_cents"] == LOW_TIER_FEE_CENTS
    assert terminated["settlement_total_cents"] == CREDITED_SETTLEMENT_TOTAL_CENTS
    assert terminated["settlement_total_cents"] != HIGH_RATE_TOTAL_CENTS
    assert terminated["occupancy_status"] == "TERMINATED"
    assert terminated["allotment_status"] == "CLOSED"
    assert terminated["termination_reason"] == "CONVENIENCE"
    assert terminated["termination_effective_date"] == EFFECTIVE_DATE


def test_the_settlement_posts_one_prorated_charge_and_one_fee_row(api):
    """The closing ledger carries the prorated month and the fee, nothing else.

    PRD: "As a second hop, because the allotment dimension became `CLOSED`, settlement rows are posted: a `CHARGE` row for the prorated final period, whose amount is the prorated rent from step one, and — only when `early_termination_fee_cents` is greater than 0 — an `EARLY_TERMINATION_FEE` row for the fee amount."

    Design: Difficulty/combinatorial_formula/early_termination_fee_tier_keyed_on_credit_reduced_base
    """
    state = _credited_tenancy_under_notice(api)
    lease_id = state["lease"]["id"]

    terminated = _terminate_on_the_effective_date(api, state)

    ledger = fx.read_ledger(api, lease_id)
    for row in ledger:
        asserts.assert_allotment_transaction(row)
    asserts.assert_created_at_ascending(ledger)
    assert [row["type"] for row in ledger] == [
        "CHARGE",
        "REFUND",
        "CHARGE",
        "EARLY_TERMINATION_FEE",
    ]
    assert [row["amount_cents"] for row in ledger] == [
        const.BASE_NET_RENT_CENTS,
        -AWARDED_CREDIT_CENTS,
        PRORATED_FINAL_MONTH_CENTS,
        LOW_TIER_FEE_CENTS,
    ]
    settlement_ref = f"TERMINATION_SETTLEMENT:{lease_id}"
    assert ledger[2]["source_ref"] == settlement_ref
    assert ledger[3]["source_ref"] == settlement_ref
    assert terminated["allotment_balance_cents"] == CREDITED_BALANCE_CENTS
    asserts.assert_ledger_conservation(ledger, terminated)


def _tenancy_under_notice_with_no_credits(api):
    """The canonical tenancy under a convenience notice, ledger untouched."""
    state = fx.setup_occupied_lease(api)
    fx.setup_lease_under_notice(
        api,
        occupied_state=state,
        reason="CONVENIENCE",
        notice_date=NOTICE_DATE,
        effective_date=EFFECTIVE_DATE,
        notice_clock=NOTICE_CLOCK,
    )
    assert state["lease"]["occupancy_status"] == "NOTICE_GIVEN"
    assert state["lease"]["allotment_status"] == "ACTIVE"
    return state


def test_termination_closes_both_dimensions_and_settles_the_final_month(api):
    """Hop one: the tenancy ends, the ledger closes, the settlement lands.

    PRD: "It advances the occupancy dimension `NOTICE_GIVEN → TERMINATED`, which is terminal, and advances the allotment dimension from `ACTIVE` or from `SUSPENDED` to `CLOSED` — both source states are permitted and both run the identical settlement and reinvestment cascade, the only difference being that abatement rows already sitting on a suspended lease's ledger reduce the settlement base."

    Design: Difficulty/transitive_cascade/lease_termination_cascades_unit_release_to_installation_counters
    """
    state = _tenancy_under_notice_with_no_credits(api)

    terminated = _terminate_on_the_effective_date(api, state)

    asserts.assert_lease(terminated)
    assert terminated["occupancy_status"] == "TERMINATED"
    assert terminated["allotment_status"] == "CLOSED"
    assert terminated["early_termination_fee_cents"] == HIGH_TIER_FEE_CENTS
    assert terminated["settlement_total_cents"] == UNCREDITED_SETTLEMENT_TOTAL_CENTS
    ledger = fx.read_ledger(api, state["lease"]["id"])
    assert [row["type"] for row in ledger] == ["CHARGE", "EARLY_TERMINATION_FEE"]
    assert [row["amount_cents"] for row in ledger] == [
        PRORATED_FINAL_MONTH_CENTS,
        HIGH_TIER_FEE_CENTS,
    ]
    assert terminated["allotment_balance_cents"] == UNCREDITED_BALANCE_CENTS
    asserts.assert_ledger_conservation(ledger, terminated)


def test_the_released_unit_is_stamped_with_the_effective_date(api):
    """Hop two: the unit comes free and remembers when it came free.

    PRD: "The unit advances `OCCUPIED → AVAILABLE` with `last_lease_end_date` set to `termination_effective_date`, which arms the turn-buffer rule for whoever leases the unit next, and the installation's `occupied_unit_count` and `available_unit_count` are recomputed with the unit's `version` incremented by 1."

    Design: Difficulty/transitive_cascade/lease_termination_cascades_unit_release_to_installation_counters
    """
    state = _tenancy_under_notice_with_no_credits(api)
    occupied_version = fx.read_housing_unit(api, state["unit"]["id"])["version"]

    _terminate_on_the_effective_date(api, state)

    unit = fx.read_housing_unit(api, state["unit"]["id"])
    asserts.assert_housing_unit(unit)
    assert unit["status"] == "AVAILABLE"
    assert unit["last_lease_end_date"] == EFFECTIVE_DATE
    assert unit["version"] == occupied_version + 1


def test_the_release_moves_the_unit_between_the_installation_counters(api):
    """Hop two again: the counters follow the unit without inventing inventory.

    PRD: "`available_unit_count`, `assigned_unit_count`, `occupied_unit_count`, `offline_unit_count` and `hazard_hold_unit_count` are the counts of those rows whose `status` is `AVAILABLE`, `ASSIGNED`, `OCCUPIED`, `OFFLINE_MAINTENANCE` and `HAZARD_HOLD` respectively."

    Design: Difficulty/transitive_cascade/lease_termination_cascades_unit_release_to_installation_counters
    """
    state = _tenancy_under_notice_with_no_credits(api)
    before = fx.read_installation(api, state["installation"]["id"])
    assert before["occupied_unit_count"] == 1
    assert before["available_unit_count"] == 0

    _terminate_on_the_effective_date(api, state)

    installation = fx.read_installation(api, state["installation"]["id"])
    asserts.assert_installation(installation)
    assert installation["occupied_unit_count"] == 0
    assert installation["available_unit_count"] == 1
    assert installation["assigned_unit_count"] == 0
    assert installation["hazard_hold_unit_count"] == 0
    assert installation["offline_unit_count"] == 0
    assert installation["total_unit_count"] == before["total_unit_count"] == 1
    asserts.assert_installation_counter_conservation(installation)
