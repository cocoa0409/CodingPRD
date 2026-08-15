"""Water-loss dual metrics, cycle close preconditions, and the OCC close guard."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_billing_cycle,
    bill_cycle_with_readings,
    create_boil_order_payload,
    get_cycle_invoice,
    get_district_version,
    get_success_data,
    issue_boil_order,
    open_cycle,
    post_master_reading,
    setup_billed_invoice,
    setup_member_with_installed_tap,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CLERK, FIELD, TREASURER
from test_helpers.constants import CLOCK_ORDER_ISSUED, CYCLE_1


class TestProvisionalVsFinalLoss:
    def _setup_billed_then_closed(self, api):
        """Cycle billed with sold 8000 (no master yet), then master 10000 + close."""
        ctx = setup_billed_invoice(usage_gallons=8000)
        district = ctx["district"]
        cycle = ctx["cycle"]
        billed = get_success_data(api.get_billing_cycle(district["id"], cycle["id"], CLERK))
        post_master_reading(district["id"], cycle["id"], 10_000)
        version = get_district_version(district["id"])
        closed = get_success_data(
            api.close_cycle(
                district["id"], cycle["id"], {"expected_district_version": version}, TREASURER
            )
        )
        return ctx, billed, closed

    def test_provisional_loss_is_zero_under_master_fallback(self, api):
        """PRD section 3.5: "The master side is the cycle's single `master_gallons`
        value if a master reading has been posted; if none has been posted yet, the
        master falls back to the sum of sold usage, making the provisional loss
        provisionally zero."

        Design: Difficulty/dual_variant_calc/water_loss_provisional_vs_final_on_billing_cycle
        """
        _, billed, _ = self._setup_billed_then_closed(api)
        assert billed["status"] == "BILLED"
        assert billed["provisional_loss_pct"] == pytest.approx(0.0, abs=1e-9)

    def test_final_loss_diverges_once_true_master_posts(self, api):
        """PRD section 3.5: "The `final_loss_pct` is the same
        hundred-times-difference-over-master formula, three decimals, half-up" and
        "the provisional and final percentages are a dual-variant pair on the cycle
        and need not agree." Master 10000 vs sold 8000 -> final loss 20.000 while
        the provisional figure was 0.000 for the identical sold set.

        Design: Difficulty/dual_variant_calc/water_loss_provisional_vs_final_on_billing_cycle
        """
        _, billed, closed = self._setup_billed_then_closed(api)
        assert closed["status"] == "CLOSED"
        assert closed["final_loss_pct"] == pytest.approx(20.0, abs=1e-9)
        assert closed["provisional_loss_pct"] == pytest.approx(0.0, abs=1e-9)
        assert closed["final_loss_pct"] != closed["provisional_loss_pct"]


class TestCloseMasterReadingGate:
    def test_close_without_master_reading_rejected(self, api):
        """PRD section 3.3: "Close requires the cycle to be `BILLED`
        (`ERR_CYCLE_NOT_BILLED` otherwise) and exactly one `MasterMeterReading`
        posted for the cycle — zero or two both fail with
        `ERR_MASTER_READING_REQUIRED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/master_meter_zero_loss_empty_set_edge
        """
        ctx = setup_billed_invoice(usage_gallons=0)
        district = ctx["district"]
        cycle = ctx["cycle"]
        version = get_district_version(district["id"])
        resp = api.close_cycle(
            district["id"], cycle["id"], {"expected_district_version": version}, TREASURER
        )
        validate_error(resp, ApiErrorId.ERR_MASTER_READING_REQUIRED, expected_status=409)
        after = get_success_data(api.get_billing_cycle(district["id"], cycle["id"], CLERK))
        assert after["status"] == "BILLED"

    def test_close_with_zero_master_applies_zero_loss_guard(self, api):
        """PRD section 3.5: "with the zero-master case at 0.000" — a posted master
        of 0 gallons closes cleanly with final_loss_pct exactly 0 rather than
        dividing by zero.

        Design: Difficulty/boundary_precision_check/master_meter_zero_loss_empty_set_edge
        """
        ctx = setup_billed_invoice(usage_gallons=0)
        district = ctx["district"]
        cycle = ctx["cycle"]
        post_master_reading(district["id"], cycle["id"], 0)
        version = get_district_version(district["id"])
        closed = get_success_data(
            api.close_cycle(
                district["id"], cycle["id"], {"expected_district_version": version}, TREASURER
            )
        )
        assert_billing_cycle(closed)
        assert closed["status"] == "CLOSED"
        assert closed["final_loss_pct"] == pytest.approx(0.0, abs=1e-9)


class TestBillCascadeVisibility:
    def test_bill_cascade_immediately_visible(self, api):
        """PRD section 3.3: "it creates one invoice per tapped member (see §3.4 for
        the charge arithmetic), computes the cycle's `provisional_loss_pct` (see
        §3.5), and applies delinquency aging — every still-unpaid invoice from
        prior cycles has its collection status advanced per the escalation rules of
        §3.6 against the logical clock" and "The cycle's `billed_total_cents`
        accumulates the `total_cents` of every non-`VOID` invoice in the cycle."

        Design: Corner/consistency_model/bill_cascade_atomic_visibility
        """
        ctx = setup_billed_invoice(usage_gallons=4300)
        district = ctx["district"]
        cycle = get_success_data(api.get_billing_cycle(district["id"], ctx["cycle"]["id"], CLERK))
        assert cycle["status"] == "BILLED"
        # No master reading posted at bill time: fallback master = sum of sold.
        assert cycle["provisional_loss_pct"] == pytest.approx(0.0, abs=1e-9)
        invoice = ctx["invoice"]
        assert invoice["billing_status"] == "ISSUED"
        assert invoice["total_cents"] == 4850
        assert cycle["billed_total_cents"] == 4850


class TestOptimisticConcurrencyOnClose:
    def test_stale_expected_version_rejected_then_fresh_close_succeeds(self, api):
        """PRD section 2.6: "If the district's current `version` has advanced since
        that observation — for example because another writer billed a later cycle,
        adopted a resolution, or issued a boil order — the close is rejected with
        `ERR_STALE_VERSION` (HTTP 412)." PRD section 2.8: "District-level events —
        adopting a rate schedule, billing or closing a cycle, ratifying an
        annexation, issuing or resolving a boil order, proposing or adopting a
        board resolution — each increment the district's `version` by 1".

        Design: Corner/endpoints/occ_stale_version_on_cycle_close
        """
        ctx = setup_billed_invoice(usage_gallons=500)
        district = ctx["district"]
        cycle = ctx["cycle"]
        post_master_reading(district["id"], cycle["id"], 500)

        stale_version = get_district_version(district["id"])
        issue_boil_order(district["id"], at_iso=CLOCK_ORDER_ISSUED, reason="Pressure loss")
        fresh_version = get_district_version(district["id"])
        assert fresh_version == stale_version + 1, "Issuing a boil order must bump the district version"

        resp = api.close_cycle(
            district["id"], cycle["id"], {"expected_district_version": stale_version}, TREASURER
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        closed = get_success_data(
            api.close_cycle(
                district["id"], cycle["id"], {"expected_district_version": fresh_version}, TREASURER
            )
        )
        assert closed["status"] == "CLOSED"
        assert get_district_version(district["id"]) == fresh_version + 1, (
            "A successful close increments the district version by exactly 1"
        )
