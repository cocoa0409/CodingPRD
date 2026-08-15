"""Optimistic concurrency on the three guarded writes, validation priority
order, and immediate read-after-write consistency."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_confirmed_booking,
    create_draft_freight_invoice,
    create_issued_freight_invoice,
    create_open_consolidation,
    create_quoted_booking,
    setup_loaded_fcl_scenario,
    setup_lcl_lane,
    stuff_booking,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BC, FC, OPS


class TestOptimisticConcurrency:
    def test_occ_booking_amend_stale_version_rejected(self, api):
        """PRD §2.6: "Amending a booking's cargo particulars requires
        `expected_booking_version` in the request body, carrying the client's
        last observed `version` of the target `Booking`. If the booking's
        version has advanced since the client last read it — for example,
        because another coordinator has just amended the same booking — the
        request is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412),
        preventing the writer from overwriting state it has not observed."
        PRD §3.6: "The estimate is recomputed on every amendment of weight,
        volume, or container count; frozen at confirm; and re-frozen at
        rebook according to the rollover variant described in §3.7."

        Design: Corner/complexity_layers/occ_booking_amend_stale_version_rejected
        """
        ctx = setup_lcl_lane()
        booking = create_quoted_booking(ctx)
        observed_version = booking["version"]

        amended = validate_success(
            api.amend_booking(
                booking["id"],
                {"expected_booking_version": observed_version,
                 "gross_weight_kg": 5000, "volume_cbm": 7.0},
                BC),
            200)
        assert amended["version"] == observed_version + 1
        # RT = max(5.0, 7.0) = 7.0: base 66500 + BAF 6650 + THC 8400 + DOC 7500.
        assert amended["estimated_freight_cents"] == 89050

        res = api.amend_booking(
            booking["id"],
            {"expected_booking_version": observed_version,
             "gross_weight_kg": 6000},
            BC)
        validate_error(res, ApiErrorId.ERR_STALE_BOOKING_VERSION,
                       expected_status=412)
        after = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert after["gross_weight_kg"] == pytest.approx(5000), (
            "the stale write must not overwrite observed state"
        )

    def test_occ_consolidation_stuff_stale_version_rejected(self, api):
        """PRD §2.6: "Stuffing an LCL booking into a consolidation requires
        `expected_consolidation_version`, carrying the client's last observed
        `version` of the target `Consolidation`. Because a prior stuffing or
        unstuffing legitimately changes `used_weight_kg` / `used_volume_cbm`
        and increments the consolidation version, a writer whose capacity view
        is stale is rejected with `ERR_STALE_CONSOLIDATION_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/occ_consolidation_stuff_stale_version_rejected
        """
        ctx = setup_lcl_lane()
        b1 = create_confirmed_booking(ctx, gross_weight_kg=6000,
                                      volume_cbm=6.0)
        b2 = create_confirmed_booking(ctx, gross_weight_kg=4000,
                                      volume_cbm=6.0)
        consolidation = create_open_consolidation(
            ctx["voyage"]["id"], cfs_location="CFS-OC", max_weight_kg=20000,
            max_volume_cbm=60.0)
        stale_version = consolidation["version"]

        stuff_booking(consolidation["id"], b1["id"])

        res = api.stuff_consolidation(consolidation["id"], b2["id"],
                                      stale_version, BC)
        validate_error(res, ApiErrorId.ERR_STALE_CONSOLIDATION_VERSION,
                       expected_status=412)

        fresh = validate_success(
            api.get_consolidation(consolidation["id"], BC), 200)
        assert fresh["used_weight_kg"] == pytest.approx(6000)
        assert fresh["version"] == stale_version + 1

        retried = validate_success(
            api.stuff_consolidation(consolidation["id"], b2["id"],
                                    fresh["version"], BC),
            201)
        assert retried["booking_id"] == b2["id"], (
            "with the fresh version the second stuff succeeds — capacity was "
            "never the problem"
        )

    def test_occ_invoice_adjustment_stale_version_rejected(self, api):
        """PRD §2.6: "Appending a manual adjustment line to a draft invoice
        requires `expected_invoice_version`, carrying the client's last
        observed `version` of the target `Invoice`. A prior adjustment
        legitimately changed the line set and total, so a writer holding a
        stale invoice view is rejected with `ERR_STALE_INVOICE_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/occ_invoice_adjustment_stale_version_rejected
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        invoice = create_draft_freight_invoice(booking["id"])
        stale_version = invoice["version"]
        assert invoice["total_cents"] == 77400

        first = validate_success(
            api.add_invoice_adjustment(invoice["id"], "SURCH-A", 0.5, 2999,
                                       stale_version, FC),
            200)
        assert first["version"] == stale_version + 1
        assert first["total_cents"] == 78900

        res = api.add_invoice_adjustment(invoice["id"], "SURCH-B", 1.0, 1000,
                                         stale_version, FC)
        validate_error(res, ApiErrorId.ERR_STALE_INVOICE_VERSION,
                       expected_status=412)
        after = validate_success(api.get_invoice(invoice["id"], FC), 200)
        assert after["total_cents"] == 78900, (
            "the stale adjustment leaves the line set untouched"
        )


class TestValidationPriority:
    def test_existence_checked_before_state_on_cancel(self, api):
        """PRD §2.9: "When an endpoint path contains an identifier, existence
        is confirmed before any state, role, or business rule runs; a missing
        identifier yields the corresponding 404 (`ERR_SHIPPER_NOT_FOUND`,
        `ERR_TARIFF_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_BOND_NOT_FOUND`,
        `ERR_VOYAGE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
        `ERR_CONSOLIDATION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_BL_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`,
        `ERR_POLICY_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND`)."
        PRD §2.8: "Lower-numbered priorities run first; the first failing
        check produces the response."

        Design: Corner/validations/existence_checked_before_state_on_cancel
        """
        res = api.cancel_booking(NON_EXISTENT_UUID, BC, reason="x")
        validate_error(res, ApiErrorId.ERR_BOOKING_NOT_FOUND,
                       expected_status=404)

    def test_cancel_loaded_with_unpaid_invoice_state_beats_fiscal(self, api):
        """PRD §3.7: "Cancellation is permitted while the booking is `QUOTED`,
        `CONFIRMED`, or `DOCUMENTATION_CLEARED`; any other state rejects with
        `ERR_BOOKING_NOT_CANCELLABLE`. Cancellation is also blocked while any
        invoice of the booking is `ISSUED` or `PARTIALLY_PAID` with
        `balance_cents` greater than zero — the rejection is
        `ERR_OUTSTANDING_BALANCE`."
        PRD §2.8: "The practical consequence is that a request that fails both
        a state check and a fiscal gate is reported as the state error, and a
        request that fails both a role check and a not-found check is reported
        as the role check."

        Design: Difficulty/priority_pair_validation_conflict/cancel_loaded_with_unpaid_invoice_state_beats_fiscal
        """
        ctx = setup_loaded_fcl_scenario()
        booking = ctx["booking"]
        assert validate_success(api.get_booking(booking["id"], OPS), 200)[
            "status"] == "LOADED"
        invoice = create_issued_freight_invoice(booking["id"])
        assert invoice["status"] == "ISSUED" and invoice["balance_cents"] > 0

        res = api.cancel_booking(booking["id"], BC, reason="dual failure")
        validate_error(res, ApiErrorId.ERR_BOOKING_NOT_CANCELLABLE,
                       expected_status=409)

        after = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert after["status"] == "LOADED"
        inv_after = validate_success(api.get_invoice(invoice["id"], FC), 200)
        assert inv_after["status"] == "ISSUED"

    def test_cancel_confirmed_with_unpaid_invoice_fiscal_gate_alone(self, api):
        """PRD §3.7: "Cancellation is also blocked while any invoice of the
        booking is `ISSUED` or `PARTIALLY_PAID` with `balance_cents` greater
        than zero — the rejection is `ERR_OUTSTANDING_BALANCE`."

        Design: Difficulty/priority_pair_validation_conflict/cancel_loaded_with_unpaid_invoice_state_beats_fiscal
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        invoice = create_issued_freight_invoice(booking["id"])
        assert invoice["balance_cents"] == 77400

        # The booking is CONFIRMED, so the state check passes and the fiscal
        # gate is the one that fires.
        res = api.cancel_booking(booking["id"], BC, reason="fiscal only")
        validate_error(res, ApiErrorId.ERR_OUTSTANDING_BALANCE,
                       expected_status=402)

        after = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert after["status"] == "CONFIRMED"


class TestImmediateConsistency:
    def test_immediate_visibility_after_mutation(self, api):
        """PRD §2.10: "Computed exposures and coverages (shipper credit
        exposure variants, surety bond available coverage) are recomputed
        eagerly on every event that affects them, and are also refreshed on
        read so that a reader always sees the current value."
        PRD §2.4: "`version` (integer): a system-managed counter that starts
        at 1 on creation and increments by one on every mutation of the
        resource."
        PRD §3.6: "On success the estimate is frozen and the shipper's
        `credit_exposure_forward_cents` now includes this booking."

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        ctx = setup_lcl_lane()
        booking = create_quoted_booking(ctx)

        confirmed = validate_success(api.confirm_booking(booking["id"], BC), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["version"] == booking["version"] + 1

        read = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert read["status"] == confirmed["status"]
        assert read["version"] == confirmed["version"], (
            "the very next GET returns the identical state — no lag"
        )

        shipper = validate_success(
            api.get_shipper(ctx["shipper"]["id"], OPS), 200)
        assert shipper["credit_exposure_forward_cents"] == 77400, (
            "the derived exposure is updated in the same transaction"
        )
