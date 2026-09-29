"""Two nested-arithmetic traps inside the same bill.

The first is the order of rounding and summation on the member's share; the
second is which figure the pharmacy's goodwill tier is keyed on. Both are
places where a plausible reading produces a different number of cents.
"""

import pytest

from test_helpers import (
    ZONE_Z2,
    Z1_COLD_CONTROLLED_LINES,
    Z1_COLD_CONTROLLED_SUBTOTAL_CENTS,
    active_allocation,
    allocations_for,
    assert_cost_share_pct,
    assert_fee_lines,
    assert_grant_ledger,
    assert_payer_mix,
    build_network,
    build_ready_order,
    build_window,
    read_grant,
    read_window,
    reserve_delivery,
    utc_ts,
)

COLD_CII_ORDER = {
    "rx_line_count": 2,
    "cold_chain_required": True,
    "controlled_schedule": "CII",
    "total_rx_value_cents": 31000,
}


@pytest.fixture
def cold_controlled_provisional_bill(api):
    """A cold controlled bag priced at 10% on the standard Z1 fee schedule."""
    net = build_network(api)
    order = build_ready_order(api, net, **COLD_CII_ORDER)
    window = build_window(api, net.zone["id"], capacity_slots=2)
    delivery = reserve_delivery(api, net, order["id"], window["id"])
    return net, delivery


class TestPerLineRounding:
    """"Multiplying the subtotal by the fraction and rounding once is a
    different figure whenever two or more lines land on a half cent, and it is
    the wrong answer."
    """

    def test_member_share_is_rounded_per_line_then_summed(
        self, api, cold_controlled_provisional_bill
    ):
        """Three lines land on a half cent, so the two orders of operation part.

        "Each of the six lines is separately adjudicated as a benefit item, so
        the member's share is computed line by line: multiply each line by the
        applicable cost-share fraction, round each product half up to a whole
        cent, and only then add the six rounded results together to obtain
        `patient_gross_share_cents`."

        Design: Difficulty/combinatorial_formula/patient_share_rounded_per_line_then_summed_not_on_subtotal
        """
        _net, delivery = cold_controlled_provisional_bill
        rows = allocations_for(api, delivery["id"])
        assert len(rows) == 1
        allocation = rows[0]
        assert allocation["variant"] == "PROVISIONAL"
        assert allocation["status"] == "ACTIVE"

        assert_fee_lines(allocation, Z1_COLD_CONTROLLED_LINES)
        assert allocation["fee_subtotal_cents"] == Z1_COLD_CONTROLLED_SUBTOTAL_CENTS
        assert_cost_share_pct(allocation, 0.10)

        assert allocation["patient_gross_share_cents"] == 264
        assert allocation["patient_gross_share_cents"] != 263

    def test_waterfall_consumes_the_per_line_gross_share(
        self, api, cold_controlled_provisional_bill
    ):
        """The split downstream of the share reconstructs the subtotal exactly.

        "The three payer figures always add back up to `fee_subtotal_cents`
        exactly; that identity is an invariant of every allocation the system
        writes."

        Design: Difficulty/combinatorial_formula/patient_share_rounded_per_line_then_summed_not_on_subtotal
        """
        _net, delivery = cold_controlled_provisional_bill
        allocation = active_allocation(api, delivery["id"])
        assert_payer_mix(
            allocation,
            patient_gross_share_cents=264,
            plan_grant_cents=150,
            absorption_tier_cents=50,
            pharmacy_absorption_cents=50,
            patient_payable_cents=64,
            pharmacy_payable_cents=2412,
        )
        assert (
            allocation["plan_grant_cents"]
            + allocation["pharmacy_payable_cents"]
            + allocation["patient_payable_cents"]
            == Z1_COLD_CONTROLLED_SUBTOTAL_CENTS
        )


Z2_AFTER_HOURS_LINES = [2005, 1395, 0, 0, 305, 0]
Z2_AFTER_HOURS_SUBTOTAL_CENTS = 3705


@pytest.fixture
def after_hours_bill_with_a_thin_grant(api):
    """A 30% member share, a 60-cent pool, and an after-hours Z2 window.

    The grant can only shave 60 cents off a 1113-cent member share, which is
    what leaves a four-figure pre-absorption net behind.
    """
    net = build_network(
        api,
        plan={
            "name": "Cascade Choice",
            "payer_type": "COMMERCIAL",
            "member_cost_share_pct": 0.3,
        },
        grant={"grant_budget_cents": 60, "per_delivery_cap_cents": 60},
        pharmacy={
            "name": "Birch Rx",
            "state_code": "OR",
            "cold_chain_certified": False,
            "controlled_license_tier": "NONE",
            "return_window_minutes": 300,
        },
        zone=dict(ZONE_Z2),
        patient={
            "full_name": "Ellis Vance",
            "date_of_birth": "1988-11-02",
            "phone_last4": "2210",
            "address_line": "12 Ridge Way",
            "zone_code": "Z2",
        },
    )
    order = build_ready_order(
        api,
        net,
        rx_line_count=1,
        cold_chain_required=False,
        controlled_schedule="NONE",
        total_rx_value_cents=1000,
    )
    window = build_window(
        api,
        net.zone["id"],
        window_start=utc_ts(3, 21),
        window_end=utc_ts(3, 23),
        capacity_slots=1,
    )
    delivery = reserve_delivery(api, net, order["id"], window["id"])
    return net, window, delivery


class TestAbsorptionTierPinning:
    """"Fifth, the pharmacy's goodwill tier is chosen **from that
    pre-absorption net and never re-derived from anything later**"
    """

    def test_after_hours_line_and_per_line_share_set_up_a_four_figure_net(
        self, api, after_hours_bill_with_a_thin_grant
    ):
        """A 21:00Z start charges the surcharge once and the share is 1113.

        "`after_hours_line_cents` is the zone's `after_hours_fee_cents` when the
        window's `window_start` falls at or after 20:00 UTC or before 06:00 UTC,
        and 0 otherwise."

        Design: Difficulty/combinatorial_formula/absorption_tier_pinned_to_pre_absorption_patient_net
        """
        _net, window, delivery = after_hours_bill_with_a_thin_grant
        assert read_window(api, window["id"])["is_after_hours"] is True

        rows = allocations_for(api, delivery["id"])
        assert len(rows) == 1
        allocation = rows[0]
        assert_fee_lines(allocation, Z2_AFTER_HOURS_LINES)
        assert allocation["fee_subtotal_cents"] == Z2_AFTER_HOURS_SUBTOTAL_CENTS
        assert allocation["patient_gross_share_cents"] == 1113
        assert allocation["patient_gross_share_cents"] != 1112

    def test_tier_is_keyed_on_the_pre_absorption_net_not_the_post_absorption_one(
        self, api, after_hours_bill_with_a_thin_grant
    ):
        """A net of 1053 selects tier 500; re-deriving from 553 would select 200.

        "a net of 1000 cents or more selects `absorption_tier_cents` of 500, a
        net of 500 cents or more but under 1000 selects 200, any net of at least
        1 cent but under 500 selects 50, and a net of zero selects 0."

        Design: Difficulty/combinatorial_formula/absorption_tier_pinned_to_pre_absorption_patient_net
        """
        net, _window, delivery = after_hours_bill_with_a_thin_grant
        allocation = active_allocation(api, delivery["id"])
        assert allocation["plan_grant_cents"] == 60
        assert allocation["absorption_tier_cents"] == 500
        assert_payer_mix(
            allocation,
            pharmacy_absorption_cents=500,
            patient_payable_cents=553,
            pharmacy_payable_cents=3092,
        )
        assert allocation["patient_payable_cents"] != 853

        assert_grant_ledger(
            read_grant(api, net.grant["id"]),
            committed_cents=60,
            remaining_cents=0,
            status="EXHAUSTED",
        )
