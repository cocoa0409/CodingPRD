"""Retail-lot consignments: delivery, provisional vs final settlement,
return reporting, and the dispute renegotiation loop."""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    FM,
    OWNER,
    advance_season_to,
    bucket_of,
    create_consignment,
    get_success_data,
    set_clock,
    setup_booking_season,
    validate_error,
    api_client,
)


def _consignment_in_booking(api, height_class, count, species="GRAND_FIR",
                            **cons_overrides):
    """BOOKING season, one lot, one DRAFT consignment against its bucket."""
    ctx = setup_booking_season(species=species, **{height_class: count})
    bucket = bucket_of(ctx["lot"]["id"], height_class)
    cons = create_consignment(ctx["season"]["id"], bucket["id"], **cons_overrides)
    ctx["bucket"] = bucket
    ctx["consignment"] = cons
    return ctx


class TestProvisionalVsFinalSettlement:
    def _setup(self):
        ctx = _consignment_in_booking(
            api_client, "H_7_8", 200, species="NOBLE_FIR",
            lot_name="Lot 9 Partners", quantity=10, unit_price_cents=2995,
            max_return_pct=0.45,
        )
        set_clock(CLOCK["HARVEST_DAY"])
        advance_season_to(ctx["season"]["id"], "HARVEST")
        return ctx

    def test_provisional_assumes_worst_case_returns(self, api):
        """PRD §3.7: "At the same moment the system computes a **provisional
        settlement**: the delivered count multiplied by the per-tree price,
        multiplied by one minus the contractual maximum return fraction,
        rounded half-up to whole cents, and recorded as
        `provisional_settlement_cents`."

        Design: Difficulty/dual_variant_calc/consignment_provisional_vs_final_settlement
        """
        ctx = self._setup()
        delivered = get_success_data(
            api.deliver_consignment(ctx["consignment"]["id"], 10, FM)
        )
        assert delivered["status"] == "DELIVERED"
        assert delivered["delivered_count"] == 10
        # round_half_up(10 * 2995 * (1 - 0.45)) = round_half_up(16472.5)
        assert delivered["provisional_settlement_cents"] == 16473
        bucket = bucket_of(ctx["lot"]["id"], "H_7_8")
        assert bucket["standing_count"] == 190
        assert bucket["consigned_cumulative"] == 10

    def test_final_uses_actual_returns_and_differs(self, api):
        """PRD §3.7: "Settlement proper requires `SETTLEMENT` posture: it
        computes the **final settlement** as the delivered count minus the
        reported returns, multiplied by the per-tree price, rounded half-up to
        whole cents, and records it as `final_settlement_cents` — identical
        delivery data yields a different final amount whenever actual returns
        differ from the worst case assumed provisionally."
        PRD §3.7: "Settlement moves the consignment to terminal `SETTLED`."

        Design: Difficulty/dual_variant_calc/consignment_provisional_vs_final_settlement
        """
        ctx = self._setup()
        delivered = get_success_data(
            api.deliver_consignment(ctx["consignment"]["id"], 10, FM)
        )
        provisional = delivered["provisional_settlement_cents"]
        advance_season_to(ctx["season"]["id"], "SHIPPING")
        advance_season_to(ctx["season"]["id"], "SETTLEMENT")
        get_success_data(api.report_return(ctx["consignment"]["id"], 3, FM))
        settled = get_success_data(
            api.settle_consignment(ctx["consignment"]["id"], FM)
        )
        # round_half_up((10 - 3) * 2995) = 20965
        assert settled["final_settlement_cents"] == 20965
        assert settled["final_settlement_cents"] != provisional, (
            "same delivery data, two valid settlement figures"
        )
        assert settled["status"] == "SETTLED"


class TestDisputeRenegotiationCycle:
    def _setup_settling(self):
        ctx = _consignment_in_booking(
            api_client, "H_6_7", 100, species="GRAND_FIR",
            lot_name="Lot 7 Retail", quantity=20, unit_price_cents=2500,
            max_return_pct=0.5,
        )
        set_clock(CLOCK["HARVEST_DAY_ALT"])
        advance_season_to(ctx["season"]["id"], "HARVEST")
        get_success_data(
            api_client.deliver_consignment(ctx["consignment"]["id"], 20, FM)
        )
        advance_season_to(ctx["season"]["id"], "SHIPPING")
        advance_season_to(ctx["season"]["id"], "SETTLEMENT")
        return ctx

    def test_settling_to_disputed_back_to_settling(self, api):
        """PRD §3.7: "When the parties disagree, the farm manager may instead
        dispute a `SETTLING` consignment during `SETTLEMENT`, moving it to
        `DISPUTED`; a later re-report of returns — again bounded by zero and
        `delivered_count`, and only in `SETTLEMENT` — brings it back to
        `SETTLING`. This `SETTLING` ↔ `DISPUTED` renegotiation loop can cycle
        until the parties settle."

        Design: Corner/state_machines/consignment_dispute_renegotiation_cycle
        """
        ctx = self._setup_settling()
        cons_id = ctx["consignment"]["id"]
        settling = get_success_data(api.report_return(cons_id, 7, FM))
        assert settling["status"] == "SETTLING"
        disputed = get_success_data(api.dispute_consignment(cons_id, FM))
        assert disputed["status"] == "DISPUTED"
        resettled = get_success_data(api.report_return(cons_id, 4, FM))
        assert resettled["status"] == "SETTLING"

    def test_settle_uses_corrected_return_report(self, api):
        """PRD §3.7: "A report carries the cumulative `returned_count` — the
        running total of trees returned so far, never below zero and never
        above `delivered_count`, else `ERR_RETURN_EXCEEDS_DELIVERED` (HTTP
        422)."
        PRD §3.7: "it computes the **final settlement** as the delivered count
        minus the reported returns, multiplied by the per-tree price, rounded
        half-up to whole cents, and records it as `final_settlement_cents` —
        identical delivery data yields a different final amount whenever actual
        returns differ from the worst case assumed provisionally."

        Design: Corner/state_machines/consignment_dispute_renegotiation_cycle
        """
        ctx = self._setup_settling()
        cons_id = ctx["consignment"]["id"]
        get_success_data(api.report_return(cons_id, 7, FM))
        get_success_data(api.dispute_consignment(cons_id, FM))
        get_success_data(api.report_return(cons_id, 4, FM))
        settled = get_success_data(api.settle_consignment(cons_id, FM))
        assert settled["status"] == "SETTLED"
        assert settled["returned_count"] == 4, "re-report overwrites to the new cumulative figure"
        assert settled["final_settlement_cents"] == 40000  # (20-4)*2500


class TestSettleRequiresSettlementPosture:
    def _setup_settling_in_shipping(self):
        ctx = _consignment_in_booking(
            api_client, "H_6_7", 100, species="GRAND_FIR",
            lot_name="Lot 7 Retail", quantity=10, unit_price_cents=2500,
            max_return_pct=0.5,
        )
        set_clock(CLOCK["HARVEST_DAY_ALT"])
        advance_season_to(ctx["season"]["id"], "HARVEST")
        get_success_data(
            api_client.deliver_consignment(ctx["consignment"]["id"], 10, FM)
        )
        advance_season_to(ctx["season"]["id"], "SHIPPING")
        get_success_data(api_client.report_return(ctx["consignment"]["id"], 2, FM))
        return ctx

    def test_settle_in_shipping_forbidden(self, api):
        """PRD §2.7: "Consignment creation requires `BOOKING` or `HARVEST`;
        delivering a consignment requires `HARVEST` or `SHIPPING`; reporting
        returns requires `SHIPPING` or `SETTLEMENT`; settlement and dispute
        require `SETTLEMENT`."
        PRD §2.7: "Any operation attempted in a posture that does not permit it
        is rejected with `ERR_POSTURE_FORBIDS` (HTTP 409)."

        Design: Corner/validations/consignment_settle_requires_settlement_posture
        """
        ctx = self._setup_settling_in_shipping()
        resp = api.settle_consignment(ctx["consignment"]["id"], FM)
        validate_error(resp, ApiErrorId.ERR_POSTURE_FORBIDS)
        cons_now = get_success_data(
            api.get_consignment(ctx["consignment"]["id"], FM)
        )
        assert cons_now["status"] == "SETTLING"

    def test_settle_after_advance_to_settlement(self, api):
        """PRD §3.7: "Settlement proper requires `SETTLEMENT` posture: it
        computes the **final settlement** as the delivered count minus the
        reported returns, multiplied by the per-tree price, rounded half-up to
        whole cents, and records it as `final_settlement_cents` — identical
        delivery data yields a different final amount whenever actual returns
        differ from the worst case assumed provisionally."

        Design: Corner/validations/consignment_settle_requires_settlement_posture
        """
        ctx = self._setup_settling_in_shipping()
        advance_season_to(ctx["season"]["id"], "SETTLEMENT")
        settled = get_success_data(
            api.settle_consignment(ctx["consignment"]["id"], FM)
        )
        assert settled["status"] == "SETTLED"
        assert settled["final_settlement_cents"] == 20000  # (10-2)*2500


class TestReturnReportBounds:
    def _setup_delivered_in_shipping(self):
        ctx = _consignment_in_booking(
            api_client, "H_6_7", 100, species="GRAND_FIR",
            lot_name="Lot 7 Retail", quantity=10, unit_price_cents=2500,
            max_return_pct=0.5,
        )
        set_clock(CLOCK["HARVEST_DAY_ALT"])
        advance_season_to(ctx["season"]["id"], "HARVEST")
        get_success_data(
            api_client.deliver_consignment(ctx["consignment"]["id"], 10, FM)
        )
        advance_season_to(ctx["season"]["id"], "SHIPPING")
        return ctx

    def test_returns_above_delivered_rejected(self, api):
        """PRD §3.7: "A report carries the cumulative `returned_count` — the
        running total of trees returned so far, never below zero and never
        above `delivered_count`, else `ERR_RETURN_EXCEEDS_DELIVERED` (HTTP
        422)."

        Design: Corner/validations/return_exceeds_delivered_rejected
        """
        ctx = self._setup_delivered_in_shipping()
        resp = api.report_return(ctx["consignment"]["id"], 11, FM)
        validate_error(resp, ApiErrorId.ERR_RETURN_EXCEEDS_DELIVERED)
        cons_now = get_success_data(
            api.get_consignment(ctx["consignment"]["id"], FM)
        )
        assert cons_now["status"] == "DELIVERED", "rejected report moves nothing"

    def test_returns_exactly_delivered_accepted(self, api):
        """PRD §3.7: "The first report, permitted in `SHIPPING` or `SETTLEMENT`
        posture, moves the consignment `DELIVERED` → `SETTLING`."
        PRD §3.7: "A report carries the cumulative `returned_count` — the
        running total of trees returned so far, never below zero and never
        above `delivered_count`, else `ERR_RETURN_EXCEEDS_DELIVERED` (HTTP
        422)."

        Design: Corner/validations/return_exceeds_delivered_rejected
        """
        ctx = self._setup_delivered_in_shipping()
        settling = get_success_data(
            api.report_return(ctx["consignment"]["id"], 10, FM)
        )
        assert settling["status"] == "SETTLING"  # inclusive cap
        assert settling["returned_count"] == 10


class TestDeliverAgainstAvailability:
    def _setup(self):
        ctx = _consignment_in_booking(
            api_client, "H_6_7", 5, species="GRAND_FIR",
            lot_name="Lot 3", quantity=6, unit_price_cents=2500,
            max_return_pct=0.3,
        )
        set_clock(CLOCK["HARVEST_DAY_ALT"])
        advance_season_to(ctx["season"]["id"], "HARVEST")
        return ctx

    def test_deliver_beyond_available_rejected(self, api):
        """PRD §3.7: "Delivery draws real inventory during `HARVEST` or
        `SHIPPING`: the call carries `delivered_count`, which must be at least
        one and no more than the bucket's `available_count`, else
        `ERR_INSUFFICIENT_STANDING` (HTTP 422)."

        Design: Corner/validations/consignment_deliver_over_available_rejected
        """
        ctx = self._setup()
        resp = api.deliver_consignment(ctx["consignment"]["id"], 6, FM)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STANDING)
        cons_now = get_success_data(
            api.get_consignment(ctx["consignment"]["id"], FM)
        )
        assert cons_now["status"] == "DRAFT"

    def test_deliver_exactly_available_accepted(self, api):
        """PRD §3.7: "The bucket's `standing_count` falls by the delivered
        amount and `consigned_cumulative` accrues it. At the same moment the
        system computes a **provisional settlement**: the delivered count
        multiplied by the per-tree price, multiplied by one minus the
        contractual maximum return fraction, rounded half-up to whole cents,
        and recorded as `provisional_settlement_cents`."

        Design: Corner/validations/consignment_deliver_over_available_rejected
        """
        ctx = self._setup()
        delivered = get_success_data(
            api.deliver_consignment(ctx["consignment"]["id"], 5, FM)
        )
        assert delivered["status"] == "DELIVERED"
        # round_half_up(5 * 2500 * (1 - 0.3)) = 8750
        assert delivered["provisional_settlement_cents"] == 8750
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["standing_count"] == 0
        assert bucket["consigned_cumulative"] == 5
