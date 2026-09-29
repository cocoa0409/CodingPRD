"""Director compensation awards: the pinned waterfall and the offset tier key."""
from test_helpers import fixtures as X
from test_helpers.assertions import assert_fields_equal
from test_helpers.constants import (
    ANNUAL_CASH_RETAINER_CENTS,
    COMMITTEE_CHAIR_PREMIUM_CENTS,
    COMMITTEE_MEMBER_FEE_CENTS,
)

EQUITY_GRANT = 23500000
SHARE_PRICE = 90000
SHARES = 900

COMMITTEE_FEES = 2 * COMMITTEE_MEMBER_FEE_CENTS + COMMITTEE_CHAIR_PREMIUM_CENTS  # 5500000
PRE_OFFSET_TOTAL = ANNUAL_CASH_RETAINER_CENTS + COMMITTEE_FEES + EQUITY_GRANT  # 41000000
OFFSET = 2050000
TOTAL = PRE_OFFSET_TOTAL - OFFSET  # 38950000
TOTAL_IF_TIER_KEYED_ON_NET = 39975000
OWNERSHIP_REQUIREMENT = 87500000
OWNERSHIP_ACTUAL = SHARES * SHARE_PRICE  # 81000000


def _director_with_three_active_seats(client):
    """One seated director chairing AUDIT and sitting on two other committees."""
    X.adopt_policy(client, equity_grant_value_cents=EQUITY_GRANT)
    director = X.new_seated_director(
        client,
        full_name="Cora Compensated",
        email="cora@issuer.example",
        birth_date="1970-02-02",
        appointed_on="2026-01-01",
        shares_held=SHARES,
    )
    for code, name, seat_role in [
        ("AUDIT", "Audit Committee", "CHAIR"),
        ("COMPENSATION", "Compensation Committee", "MEMBER"),
        ("NOMINATING_GOVERNANCE", "Nominating and Governance Committee", "MEMBER"),
    ]:
        committee = X.new_committee(
            client, code=code, name=name, authorized_seats=5, min_seats=1
        )
        X.seat_assignment(
            client,
            committee["id"],
            director["id"],
            seat_role=seat_role,
            term_start_on="2026-01-01",
            term_end_on="2026-12-31",
        )
    return director


def _award_for(client, director):
    return X.new_comp_award(
        client,
        director["id"],
        cycle_year=2026,
        service_start_on="2026-01-01",
        service_end_on="2026-12-31",
        share_price_cents=SHARE_PRICE,
        shares_held=SHARES,
    )


def test_the_offset_tier_is_keyed_on_the_pre_offset_total_not_the_net_total(client):
    """A pre-offset total of 41000000 sits in the 5.0 percent band, so the award nets
    38950000 rather than the 39975000 a net-derived 2.5 percent tier would give.

    PRD: "A `pre_offset_total_cents` above 40000000 attracts the 5.0 percent tier even when subtracting that offset leaves a `total_cents` back below 40000000 cents; re-deriving the tier from the net figure would select 2.5 percent and produce a different, wrong award."

    Design: Difficulty/combinatorial_formula/comp_award_offset_tier_keyed_on_pre_offset_total_not_net_total
    """
    director = _director_with_three_active_seats(client)

    award = _award_for(client, director)

    assert_fields_equal(
        award,
        {
            "pre_offset_total_cents": PRE_OFFSET_TOTAL,
            "excess_offset_pct": 5.0,
            "excess_offset_cents": OFFSET,
            "total_cents": TOTAL,
        },
    )
    assert award["total_cents"] != TOTAL_IF_TIER_KEYED_ON_NET


def test_the_offset_band_boundaries_are_read_off_the_pre_offset_total(client):
    """The tier boundary at 40000000 is what puts this award on 5.0 percent; the resulting
    net total falls back under the same boundary without changing the tier.

    PRD: "it is 0.0 when the `pre_offset_total_cents` is at or below 30000000 cents, 2.5 when it is above that and at or below 40000000 cents, and 5.0 when it is above 40000000 cents."

    Design: Difficulty/combinatorial_formula/comp_award_offset_tier_keyed_on_pre_offset_total_not_net_total
    """
    director = _director_with_three_active_seats(client)

    award = _award_for(client, director)

    assert award["pre_offset_total_cents"] > 40000000
    assert award["excess_offset_pct"] == 5.0
    assert award["total_cents"] < 40000000


def test_the_award_waterfall_snapshots_service_days_seat_counts_and_the_equity_grant(client):
    """A full calendar year pays 365 service days, the three active seats snapshot as one
    chair plus two members, and the equity leg is a frozen copy of the policy grant.

    PRD: "The `service_days` is the inclusive day span of the service window: the number of days from `service_start_on` to `service_end_on`, plus one, so that both endpoint dates are paid."

    Design: Difficulty/combinatorial_formula/comp_award_offset_tier_keyed_on_pre_offset_total_not_net_total
    """
    director = _director_with_three_active_seats(client)

    award = _award_for(client, director)

    assert_fields_equal(
        award,
        {
            "service_days": 365,
            "committee_member_seat_count": 2,
            "committee_chair_seat_count": 1,
            "prorated_cash_retainer_cents": ANNUAL_CASH_RETAINER_CENTS,
            "committee_fees_cents": COMMITTEE_FEES,
            "equity_value_cents": EQUITY_GRANT,
        },
    )


def test_a_chair_seat_pays_the_premium_instead_of_the_member_fee(client):
    """Committee fees are 5500000, which is two member fees plus one chair premium and not
    two member fees plus a member fee and a premium for the chaired seat.

    PRD: "A chair seat therefore pays the chair premium in place of the member fee, not in addition to it."

    Design: Difficulty/combinatorial_formula/comp_award_offset_tier_keyed_on_pre_offset_total_not_net_total
    """
    director = _director_with_three_active_seats(client)

    award = _award_for(client, director)

    assert award["committee_fees_cents"] == COMMITTEE_FEES
    assert award["committee_fees_cents"] != 3 * COMMITTEE_MEMBER_FEE_CENTS + COMMITTEE_CHAIR_PREMIUM_CENTS


def test_the_ownership_requirement_is_taken_from_cash_compensation_only(client):
    """The requirement is 5.0 times the cash retainer plus committee fees, so 87500000 -
    the equity leg and the offset are both outside the base.

    PRD: "The `ownership_requirement_cents` is the policy's `ownership_multiple` applied to the sum of the `prorated_cash_retainer_cents` and the `committee_fees_cents`, rounded half up to whole cents"

    Design: Difficulty/combinatorial_formula/comp_award_offset_tier_keyed_on_pre_offset_total_not_net_total
    """
    director = _director_with_three_active_seats(client)

    award = _award_for(client, director)

    assert_fields_equal(
        award,
        {
            "ownership_requirement_cents": OWNERSHIP_REQUIREMENT,
            "ownership_actual_cents": OWNERSHIP_ACTUAL,
            "ownership_compliant": False,
        },
    )


def test_finalizing_inside_the_grace_window_records_the_shortfall_without_moving_posture(client):
    """The award finalizes with its shortfall on the record, but the clock has not reached
    appointed_on plus the grace years, so the director stays COMPLIANT.

    PRD: "Inside the grace window a shortfall is recorded on the award but does not move the director's posture."

    Design: Difficulty/combinatorial_formula/comp_award_offset_tier_keyed_on_pre_offset_total_not_net_total
    """
    director = _director_with_three_active_seats(client)
    award = _award_for(client, director)

    finalized = X.finalize_award(client, award["id"])

    assert_fields_equal(
        finalized, {"status": "FINALIZED", "ownership_compliant": False, "total_cents": TOTAL}
    )
    assert X.get_director(client, director["id"])["compliance_status"] == "COMPLIANT"
