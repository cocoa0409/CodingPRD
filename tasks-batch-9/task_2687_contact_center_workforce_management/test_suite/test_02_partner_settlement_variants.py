"""Partner settlement: both billing variants, and per-line invoice rounding."""

from test_helpers.assertions import assert_settlement_amounts
from test_helpers.constants import (
    BILLING_COMMITMENT_FLOOR,
    BILLING_DELIVERED_ONLY,
)
from test_helpers.fixtures import (
    commit_allocation,
    make_outsource_partner,
    propose_allocation,
    read_allocation,
    read_partner,
    settle_allocation,
)


def _partner_pair(api):
    """Two identically priced partners differing only in billing basis."""
    floor_partner = make_outsource_partner(
        api,
        legal_name="Floor Partners BV",
        rate_per_contact_millicents=12500,
        interval_max_volume=50,
        commitment_floor_volume=20,
        billing_basis=BILLING_COMMITMENT_FLOOR,
    )
    delivered_partner = make_outsource_partner(
        api,
        legal_name="Delivered Partners BV",
        rate_per_contact_millicents=12500,
        interval_max_volume=50,
        commitment_floor_volume=20,
        billing_basis=BILLING_DELIVERED_ONLY,
    )
    return floor_partner, delivered_partner


def _committed_line(api, partner, interval_plan_id, allocated_volume=41):
    """One allocation proposed by one operator and committed by another."""
    allocation = propose_allocation(
        api, partner["id"], interval_plan_id, allocated_volume
    )
    fresh = read_partner(api, partner["id"])
    commit_allocation(api, allocation["id"], fresh["version"])
    return allocation


class TestBillingBasisDivergence:
    """The same delivery data settles to two different payables."""

    def test_commitment_floor_partner_is_billed_the_committed_volume(
        self, api, partner_week
    ):
        """Under-delivery on a commitment-floor line is billed at the committed volume.

        "under `COMMITMENT_FLOOR` it is `settlement_floor_cents`, so the
        committed volume is billed regardless of delivery and under-delivery
        costs the buyer full price with no penalty credited"

        Design: Difficulty/dual_variant_calc/partner_settlement_floor_vs_delivered_divergence
        """
        floor_partner, _ = _partner_pair(api)
        line = _committed_line(api, floor_partner, partner_week["intervals"][0]["id"])

        settle_allocation(api, line["id"], 30)

        settled = read_allocation(api, line["id"])
        assert_settlement_amounts(
            settled,
            settlement_floor_cents=513,
            settlement_delivered_cents=375,
            shortfall_penalty_cents=34,
            settlement_amount_cents=513,
        )

    def test_delivered_only_partner_is_billed_delivery_less_the_penalty(
        self, api, partner_week
    ):
        """Under-delivery on a delivered-only line bills 375 less the 34-cent penalty.

        "under `DELIVERED_ONLY` it is `settlement_delivered_cents` minus
        `shortfall_penalty_cents`, so only handled contacts are billed and the
        buyer is further credited a twenty-five-percent shortfall penalty."

        Design: Difficulty/dual_variant_calc/partner_settlement_floor_vs_delivered_divergence
        """
        _, delivered_partner = _partner_pair(api)
        line = _committed_line(
            api, delivered_partner, partner_week["intervals"][1]["id"]
        )

        settle_allocation(api, line["id"], 30)

        settled = read_allocation(api, line["id"])
        assert_settlement_amounts(
            settled,
            settlement_floor_cents=513,
            settlement_delivered_cents=375,
            shortfall_penalty_cents=34,
            settlement_amount_cents=341,
        )

    def test_all_three_amounts_are_stored_on_both_settled_rows(self, api, partner_week):
        """Both variant columns are stored on both rows and the payables diverge by 172 cents.

        "Three amounts are always computed and always stored, regardless of
        which one is authoritative."

        Design: Difficulty/dual_variant_calc/partner_settlement_floor_vs_delivered_divergence
        """
        floor_partner, delivered_partner = _partner_pair(api)
        floor_line = _committed_line(
            api, floor_partner, partner_week["intervals"][0]["id"]
        )
        delivered_line = _committed_line(
            api, delivered_partner, partner_week["intervals"][1]["id"]
        )

        settle_allocation(api, floor_line["id"], 30)
        settle_allocation(api, delivered_line["id"], 30)

        floor_row = read_allocation(api, floor_line["id"])
        delivered_row = read_allocation(api, delivered_line["id"])
        for row in (floor_row, delivered_row):
            assert row["settlement_floor_cents"] == 513
            assert row["settlement_delivered_cents"] == 375
            assert row["shortfall_penalty_cents"] == 34
        divergence = (
            floor_row["settlement_amount_cents"]
            - delivered_row["settlement_amount_cents"]
        )
        assert divergence == 172

    def test_each_partner_invoices_its_own_authoritative_payable(
        self, api, partner_week
    ):
        """Settlement adds the authoritative payable to the invoice and clears the outstanding.

        "Settlement then subtracts `allocated_volume` from the partner's
        `committed_volume_outstanding` and adds `settlement_amount_cents` to the
        partner's `invoice_total_cents`."

        Design: Difficulty/dual_variant_calc/partner_settlement_floor_vs_delivered_divergence
        """
        floor_partner, delivered_partner = _partner_pair(api)
        floor_line = _committed_line(
            api, floor_partner, partner_week["intervals"][0]["id"]
        )
        delivered_line = _committed_line(
            api, delivered_partner, partner_week["intervals"][1]["id"]
        )

        settle_allocation(api, floor_line["id"], 30)
        settle_allocation(api, delivered_line["id"], 30)

        assert read_partner(api, floor_partner["id"])["invoice_total_cents"] == 513
        assert read_partner(api, delivered_partner["id"])["invoice_total_cents"] == 341
        assert read_partner(api, floor_partner["id"])["committed_volume_outstanding"] == 0
        assert (
            read_partner(api, delivered_partner["id"])["committed_volume_outstanding"]
            == 0
        )


class TestInvoiceRoundingOrder:
    """Two settlement lines of 41 contacts each accumulate to 1026, not 1025."""

    def test_two_lines_are_rounded_individually_then_summed(self, api, partner_week):
        """Each 41-contact line rounds to 513 cents and the invoice totals 1026.

        "Each settlement line is rounded to whole cents on its own, and
        `invoice_total_cents` is the integer sum of those already-rounded lines
        — never the result of summing millicents across lines and rounding once
        at the end."

        Design: Difficulty/combinatorial_formula/partner_invoice_per_line_rounding_order
        """
        partner = make_outsource_partner(
            api,
            legal_name="Roundwise Contact BV",
            rate_per_contact_millicents=12500,
            interval_max_volume=50,
            commitment_floor_volume=20,
            billing_basis=BILLING_COMMITMENT_FLOOR,
        )
        first = _committed_line(api, partner, partner_week["intervals"][0]["id"])
        second = _committed_line(api, partner, partner_week["intervals"][1]["id"])

        settle_allocation(api, first["id"], 41)
        settle_allocation(api, second["id"], 41)

        assert read_allocation(api, first["id"])["settlement_delivered_cents"] == 513
        assert read_allocation(api, second["id"])["settlement_delivered_cents"] == 513
        assert read_partner(api, partner["id"])["invoice_total_cents"] == 1026

    def test_delivery_that_meets_the_commitment_carries_no_penalty(
        self, api, partner_week
    ):
        """Delivering the full committed volume leaves the shortfall penalty at zero.

        "it is zero whenever delivery met or exceeded the commitment."

        Design: Difficulty/combinatorial_formula/partner_invoice_per_line_rounding_order
        """
        partner = make_outsource_partner(
            api,
            legal_name="Roundwise Contact BV",
            rate_per_contact_millicents=12500,
            interval_max_volume=50,
            commitment_floor_volume=20,
            billing_basis=BILLING_COMMITMENT_FLOOR,
        )
        line = _committed_line(api, partner, partner_week["intervals"][0]["id"])

        settle_allocation(api, line["id"], 41)

        settled = read_allocation(api, line["id"])
        assert_settlement_amounts(
            settled,
            shortfall_penalty_cents=0,
            settlement_amount_cents=513,
        )
        assert read_partner(api, partner["id"])["committed_volume_outstanding"] == 0
