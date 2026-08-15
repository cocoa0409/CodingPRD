"""Tests for invoice creation, OCC, supersede, tiered pricing, and voiding."""
import pytest

from test_helpers import (

    ApiErrorId,
    TEST_USERS,
    create_invoice_payload,
    create_pad,
    create_reserved_request,
    setup_invoice_for_cleared_operation,
    setup_invoice_issued,
    setup_operation_cleared,
    validate_error,
    validate_success,
)


class TestInvoiceOcc:
    def test_occ_invoice_create_stale_airline_version_rejected(self, api):
        """PRD §2.6: "Creating an invoice requires the request to carry
        `expected_airline_version`, the client-observed `version` of the billed
        airline. If the airline's current `version` has advanced since the
        client last read it, creation is rejected with `ERR_STALE_VERSION`
        (HTTP 412). This guard exists because invoice creation legitimately
        supersedes any existing `DRAFT` invoice for the same operation and
        itself advances the airline's version, so a writer holding a stale
        airline view must be refused rather than allowed to supersede on data
        it never observed."

        Design: Corner/cross_cutting_layers/occ_invoice_create_stale_airline_version_rejected
        """
        station, permit, tank, pad, airline, request, operation = (
            setup_operation_cleared(actual_liters=300, collected_liters=200)
        )

        # Read airline version (v1).
        resp = api.get_airline(
            airline["id"], TEST_USERS["billing_clerk_headers"]
        )
        airline_v1 = validate_success(resp)
        av1 = airline_v1["version"]

        # First invoice creation advances the airline version.
        payload = create_invoice_payload(
            operation["id"], expected_airline_version=av1
        )
        resp = api.create_invoice(
            payload, TEST_USERS["billing_clerk_headers"]
        )
        validate_success(resp, expected_status=201)

        # Second create with the stale version is rejected.
        payload = create_invoice_payload(
            operation["id"], expected_airline_version=av1
        )
        resp = api.create_invoice(
            payload, TEST_USERS["billing_clerk_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_invoice_supersede_replaces_prior_draft(self, api):
        """PRD §3.9: "If an invoice for the same operation already exists in
        `ISSUED` status, creation is rejected with `ERR_INVALID_STATE`; if one
        exists in `DRAFT` status, the existing draft is moved to `SUPERSEDED`
        and the new invoice records it as `supersedes_invoice_id`."

        Design: Corner/cross_cutting_layers/invoice_supersede_replaces_prior_draft
        """
        station, permit, tank, pad, airline, request, operation = (
            setup_operation_cleared(actual_liters=300, collected_liters=200)
        )

        # Create first invoice (DRAFT).
        resp = api.get_airline(
            airline["id"], TEST_USERS["billing_clerk_headers"]
        )
        av1 = validate_success(resp)["version"]
        payload = create_invoice_payload(
            operation["id"], expected_airline_version=av1
        )
        resp = api.create_invoice(
            payload, TEST_USERS["billing_clerk_headers"]
        )
        inv1 = validate_success(resp, expected_status=201)
        assert inv1["status"] == "DRAFT"

        # Re-read airline version and create second invoice.
        resp = api.get_airline(
            airline["id"], TEST_USERS["billing_clerk_headers"]
        )
        av2 = validate_success(resp)["version"]
        payload = create_invoice_payload(
            operation["id"], expected_airline_version=av2
        )
        resp = api.create_invoice(
            payload, TEST_USERS["billing_clerk_headers"]
        )
        inv2 = validate_success(resp, expected_status=201)
        assert inv2["supersedes_invoice_id"] == inv1["id"]

        # Prior draft is SUPERSEDED.
        resp = api.get_invoice(
            inv1["id"], TEST_USERS["billing_clerk_headers"]
        )
        assert validate_success(resp)["status"] == "SUPERSEDED"

        # Exactly one non-superseded DRAFT remains for this operation.
        resp = api.list_invoices(
            TEST_USERS["billing_clerk_headers"],
            params={"operation_id": operation["id"], "status": "DRAFT"},
        )
        drafts = validate_success(resp)
        assert len(drafts) == 1
        assert drafts[0]["id"] == inv2["id"]


class TestInvoicePricing:
    def test_invoice_marginal_vs_flat_tier(self, api):
        """PRD §3.9: "For illustration, an airline with a month-to-date base of
        4,900 billed liters receiving a 300-liter `TYPE_I` operation pays for
        its first 100 liters at 90 cents flat — 9,000 cents — and the remaining
        200 liters at 90 cents times 0.92 — 16,560 cents — for a fluid charge
        of 25,560 cents. Pricing every liter at the highest tier touched —
        which would yield 24,840 cents here — is the documented `FLAT_TIER`
        interpretation and is never applied."

        Design: Difficulty/dual_variant_calc/invoice_marginal_vs_flat_tier
        """
        # Op1: 4900 L on MEDIUM pad, issued so monthly_billed_liters == 4900.
        station, permit, tank, pad_m, airline, request1, op1, inv1 = (
            setup_invoice_issued(
                actual_liters=4900,
                collected_liters=2500,
                size_class="MEDIUM",
                tank_overrides={
                    "fluid_type": "TYPE_I",
                    "capacity_liters": 50000,
                    "on_hand_liters": 50000,
                    "reorder_threshold_liters": 300,
                },
            )
        )

        # Op2: 300 L on SMALL pad, no weather event.
        pad_s = create_pad(station["id"], code="PS", max_size_class="SMALL")
        r2 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA2", scheduled_departure="2026-05-01T13:00:00Z"
        )
        from test_helpers import assign_request_payload, get_operation_for_request
        payload = assign_request_payload(
            pad_s["id"],
            window_start="2026-05-01T11:00:00Z",
            window_end="2026-05-01T11:30:00Z",
        )
        api.assign_deice_request(
            r2["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        op2 = get_operation_for_request(r2["id"])
        from test_helpers import (
            record_acceptance_inspection,
            record_post_treatment_inspection,
            start_operation,
            complete_operation,
        )
        record_acceptance_inspection(op2["id"], inspector_id="insp-1")
        start_operation(op2["id"], oat_celsius=0)
        complete_operation(op2["id"], actual_liters=300, collected_liters=200)
        record_post_treatment_inspection(op2["id"], result="PASS", inspector_id="insp-2")

        # Create invoice for op2.
        resp = api.get_airline(
            airline["id"], TEST_USERS["billing_clerk_headers"]
        )
        av2 = validate_success(resp)["version"]
        payload = create_invoice_payload(
            op2["id"], expected_airline_version=av2
        )
        resp = api.create_invoice(
            payload, TEST_USERS["billing_clerk_headers"]
        )
        invoice = validate_success(resp, expected_status=201)

        assert invoice["fluid_charge_cents"] == 25560
        assert invoice["pad_fee_cents"] == 20000
        assert invoice["storm_surcharge_cents"] == 0
        assert invoice["total_cents"] == 45560
        assert invoice["total_cents"] != 44840
        assert invoice["pricing_variant"] == "MARGINAL_TIER"

    def test_invoice_per_line_rounding_then_sum(self, api):
        """PRD §2.5: "Invoice line items are each rounded half-up to integer
        cents first, and the invoice total is the sum of those already-rounded
        lines; computing raw amounts, summing, and rounding once at the end
        yields a different, non-conformant result."
        PRD §3.9: "the `storm_surcharge_cents` applies when significant weather
        accompanied the work: when an `ACTIVE` weather event of severity
        `LEVEL_2` or `LEVEL_3` existed at the station at the moment the
        operation transitioned to `AWAITING_INSPECTION`, the surcharge is the
        sum of the pad fee and fluid charge multiplied by the station's
        `storm_surcharge_pct` and divided by one hundred, rounded half-up to
        integer cents; otherwise it is zero."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        # Op1: 5000 L on MEDIUM pad, issued so monthly_billed_liters == 5000.
        station, permit, tank, pad_m, airline, request1, op1, inv1 = (
            setup_invoice_issued(
                actual_liters=5000,
                collected_liters=2600,
                size_class="MEDIUM",
                tank_overrides={
                    "fluid_type": "TYPE_I",
                    "capacity_liters": 50000,
                    "on_hand_liters": 50000,
                    "reorder_threshold_liters": 300,
                },
            )
        )

        # Activate a LEVEL_2 event after op1 completion, before op2 completion.
        from test_helpers import create_and_activate_weather_event
        create_and_activate_weather_event(
            station["id"],
            precip_type="SNOW",
            precip_rate="LIGHT",
            severity="LEVEL_2",
            started_at="2026-05-01T05:00:00Z",
        )

        # Op2: 3 L on SMALL pad while LEVEL_2 event is ACTIVE.
        pad_s = create_pad(station["id"], code="PS", max_size_class="SMALL")
        r2 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA2", scheduled_departure="2026-05-01T13:00:00Z"
        )
        from test_helpers import assign_request_payload, get_operation_for_request
        payload = assign_request_payload(
            pad_s["id"],
            window_start="2026-05-01T11:00:00Z",
            window_end="2026-05-01T11:30:00Z",
        )
        api.assign_deice_request(
            r2["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        op2 = get_operation_for_request(r2["id"])
        from test_helpers import (
            record_acceptance_inspection,
            record_post_treatment_inspection,
            start_operation,
            complete_operation,
        )
        record_acceptance_inspection(op2["id"], inspector_id="insp-1")
        start_operation(op2["id"], oat_celsius=0)
        complete_operation(op2["id"], actual_liters=3, collected_liters=2)
        record_post_treatment_inspection(op2["id"], result="PASS", inspector_id="insp-2")

        # Create invoice for op2.
        resp = api.get_airline(
            airline["id"], TEST_USERS["billing_clerk_headers"]
        )
        av2 = validate_success(resp)["version"]
        payload = create_invoice_payload(
            op2["id"], expected_airline_version=av2
        )
        resp = api.create_invoice(
            payload, TEST_USERS["billing_clerk_headers"]
        )
        invoice = validate_success(resp, expected_status=201)

        assert invoice["fluid_charge_cents"] == 248
        assert invoice["storm_surcharge_cents"] == 5062
        assert invoice["total_cents"] == 25310
        assert invoice["pad_fee_cents"] == 20000

    def test_tier_boundary_straddle_at_5000(self, api):
        """PRD §3.9: "The first tier covers cumulative monthly liter positions
        from zero up to but not including 5,000; the second covers 5,000 up to
        but not including 20,000; the third covers 20,000 onward. Each liter is
        priced at the base rate for the operation's fluid type — 90 cents for
        `TYPE_I`, 140 for `TYPE_IV` — multiplied by the multiplier of the tier
        that liter's cumulative position lands in: 1.0 in the first tier, 0.92
        in the second, 0.85 in the third. Where an operation straddles a tier
        boundary, each segment is computed separately and rounded half-up to
        integer cents, and the fluid charge is the sum of those rounded
        segments."

        Design: Corner/calculations/tier_boundary_straddle_at_5000
        """
        # Op1: 4999 L on MEDIUM pad, issued so monthly_billed_liters == 4999.
        station, permit, tank, pad_m, airline, request1, op1, inv1 = (
            setup_invoice_issued(
                actual_liters=4999,
                collected_liters=2600,
                size_class="MEDIUM",
                tank_overrides={
                    "fluid_type": "TYPE_I",
                    "capacity_liters": 50000,
                    "on_hand_liters": 50000,
                    "reorder_threshold_liters": 300,
                },
            )
        )

        # Op2: 2 L on SMALL pad, no weather event.
        pad_s = create_pad(station["id"], code="PS", max_size_class="SMALL")
        r2 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA2", scheduled_departure="2026-05-01T13:00:00Z"
        )
        from test_helpers import assign_request_payload, get_operation_for_request
        payload = assign_request_payload(
            pad_s["id"],
            window_start="2026-05-01T11:00:00Z",
            window_end="2026-05-01T11:30:00Z",
        )
        api.assign_deice_request(
            r2["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        op2 = get_operation_for_request(r2["id"])
        from test_helpers import (
            record_acceptance_inspection,
            record_post_treatment_inspection,
            start_operation,
            complete_operation,
        )
        record_acceptance_inspection(op2["id"], inspector_id="insp-1")
        start_operation(op2["id"], oat_celsius=0)
        complete_operation(op2["id"], actual_liters=2, collected_liters=2)
        record_post_treatment_inspection(op2["id"], result="PASS", inspector_id="insp-2")

        # Create invoice for op2.
        resp = api.get_airline(
            airline["id"], TEST_USERS["billing_clerk_headers"]
        )
        av2 = validate_success(resp)["version"]
        payload = create_invoice_payload(
            op2["id"], expected_airline_version=av2
        )
        resp = api.create_invoice(
            payload, TEST_USERS["billing_clerk_headers"]
        )
        invoice = validate_success(resp, expected_status=201)

        assert invoice["fluid_charge_cents"] == 173
        assert invoice["total_cents"] == 20173


class TestInvoiceVoidInvariant:
    def test_invoice_issue_debits_airline_balance(self, api):
        """PRD §3.9: "Issuing a `DRAFT` invoice moves it to `ISSUED` and debits
        the airline: `outstanding_balance_cents` increases by the invoice's
        `total_cents`, and `monthly_billed_liters` increases by the billed
        operation's `actual_liters`. Both the invoice's and the airline's
        `version` increment."

        Design: Difficulty/compensating_invariant/invoice_issue_then_void_restores_balance
        """
        station, permit, tank, pad, airline, request, operation, invoice = (
            setup_invoice_for_cleared_operation(
                actual_liters=300, collected_liters=200, size_class="MEDIUM",
                pad_overrides={"max_size_class": "MEDIUM"},
            )
        )
        assert invoice["status"] == "DRAFT"
        assert invoice["total_cents"] == 62000

        # Issue.
        resp = api.issue_invoice(
            invoice["id"], TEST_USERS["billing_clerk_headers"]
        )
        issued = validate_success(resp)
        assert issued["status"] == "ISSUED"

        resp = api.get_airline(
            airline["id"], TEST_USERS["billing_clerk_headers"]
        )
        airline_after = validate_success(resp)
        assert airline_after["outstanding_balance_cents"] == 62000
        assert airline_after["monthly_billed_liters"] == 300

    def test_invoice_issue_then_void_restores_balance(self, api):
        """PRD §3.9: "Issuing a `DRAFT` invoice moves it to `ISSUED` and debits
        the airline: `outstanding_balance_cents` increases by the invoice's
        `total_cents`, and `monthly_billed_liters` increases by the billed
        operation's `actual_liters`." And: "Voiding an `ISSUED` invoice is the
        exact compensation: the airline's `outstanding_balance_cents` decreases
        by `total_cents`, restoring the pre-issue balance precisely, and
        `monthly_billed_liters` decreases by the same `actual_liters`, with
        both versions incrementing again."

        Design: Difficulty/compensating_invariant/invoice_issue_then_void_restores_balance
        """
        station, permit, tank, pad, airline, request, operation, invoice = (
            setup_invoice_for_cleared_operation(
                actual_liters=300, collected_liters=200, size_class="MEDIUM",
                pad_overrides={"max_size_class": "MEDIUM"},
            )
        )
        assert invoice["total_cents"] == 62000

        # Issue.
        resp = api.issue_invoice(
            invoice["id"], TEST_USERS["billing_clerk_headers"]
        )
        validate_success(resp)

        resp = api.get_airline(
            airline["id"], TEST_USERS["billing_clerk_headers"]
        )
        airline_after_issue = validate_success(resp)
        assert airline_after_issue["outstanding_balance_cents"] == 62000
        assert airline_after_issue["monthly_billed_liters"] == 300

        # Void.
        resp = api.void_invoice(
            invoice["id"], TEST_USERS["billing_clerk_headers"]
        )
        assert validate_success(resp)["status"] == "VOID"

        resp = api.get_airline(
            airline["id"], TEST_USERS["billing_clerk_headers"]
        )
        airline_after_void = validate_success(resp)
        assert airline_after_void["outstanding_balance_cents"] == 0
        assert airline_after_void["monthly_billed_liters"] == 0


class TestInvoicePricingEdgeCases:
    def test_invoice_marginal_tier_applied_not_flat(self, api):
        """PRD §3.9: "Each liter is priced at the base rate for the operation's
        fluid type — 90 cents for `TYPE_I`, 140 for `TYPE_IV` — multiplied by
        the multiplier of the tier that liter's cumulative position lands in:
        1.0 in the first tier, 0.92 in the second, 0.85 in the third." And:
        "Pricing every liter at the highest tier touched — which would yield
        24,840 cents here — is the documented `FLAT_TIER` interpretation and is
        never applied."

        Design: Difficulty/dual_variant_calc/invoice_marginal_vs_flat_tier
        """
        # Op1: 4900 L issued so monthly base is 4900.
        station, permit, tank, pad_m, airline, request1, op1, inv1 = (
            setup_invoice_issued(
                actual_liters=4900,
                collected_liters=2500,
                size_class="MEDIUM",
                tank_overrides={
                    "fluid_type": "TYPE_I",
                    "capacity_liters": 50000,
                    "on_hand_liters": 50000,
                    "reorder_threshold_liters": 300,
                },
            )
        )

        # Op2: 300 L on SMALL pad.
        pad_s = create_pad(station["id"], code="PS", max_size_class="SMALL")
        r2 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA2", scheduled_departure="2026-05-01T13:00:00Z"
        )
        from test_helpers import assign_request_payload, get_operation_for_request
        payload = assign_request_payload(
            pad_s["id"],
            window_start="2026-05-01T11:00:00Z",
            window_end="2026-05-01T11:30:00Z",
        )
        api.assign_deice_request(
            r2["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        op2 = get_operation_for_request(r2["id"])
        from test_helpers import (
            record_acceptance_inspection,
            record_post_treatment_inspection,
            start_operation,
            complete_operation,
        )
        record_acceptance_inspection(op2["id"], inspector_id="insp-1")
        start_operation(op2["id"], oat_celsius=0)
        complete_operation(op2["id"], actual_liters=300, collected_liters=200)
        record_post_treatment_inspection(op2["id"], result="PASS", inspector_id="insp-2")

        resp = api.get_airline(
            airline["id"], TEST_USERS["billing_clerk_headers"]
        )
        av2 = validate_success(resp)["version"]
        payload = create_invoice_payload(
            op2["id"], expected_airline_version=av2
        )
        resp = api.create_invoice(
            payload, TEST_USERS["billing_clerk_headers"]
        )
        invoice = validate_success(resp, expected_status=201)

        # MARGINAL_TIER: 100 L @ 90 + 200 L @ 82.8 = 9000 + 16560 = 25560.
        assert invoice["fluid_charge_cents"] == 25560
        # FLAT_TIER would be 300 * 82.8 = 24840.
        assert invoice["fluid_charge_cents"] != 24840
        assert invoice["pricing_variant"] == "MARGINAL_TIER"

    def test_invoice_rounding_per_line_not_sum_then_round(self, api):
        """PRD §2.5: "Invoice line items are each rounded half-up to integer
        cents first, and the invoice total is the sum of those already-rounded
        lines; computing raw amounts, summing, and rounding once at the end
        yields a different, non-conformant result."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        # Op1: 5000 L issued so monthly base is 5000 (tier 2 for op2).
        station, permit, tank, pad_m, airline, request1, op1, inv1 = (
            setup_invoice_issued(
                actual_liters=5000,
                collected_liters=2600,
                size_class="MEDIUM",
                tank_overrides={
                    "fluid_type": "TYPE_I",
                    "capacity_liters": 50000,
                    "on_hand_liters": 50000,
                    "reorder_threshold_liters": 300,
                },
            )
        )

        from test_helpers import create_and_activate_weather_event
        create_and_activate_weather_event(
            station["id"],
            precip_type="SNOW",
            precip_rate="LIGHT",
            severity="LEVEL_2",
            started_at="2026-05-01T05:00:00Z",
        )

        pad_s = create_pad(station["id"], code="PS", max_size_class="SMALL")
        r2 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA2", scheduled_departure="2026-05-01T13:00:00Z"
        )
        from test_helpers import assign_request_payload, get_operation_for_request
        payload = assign_request_payload(
            pad_s["id"],
            window_start="2026-05-01T11:00:00Z",
            window_end="2026-05-01T11:30:00Z",
        )
        api.assign_deice_request(
            r2["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        op2 = get_operation_for_request(r2["id"])
        from test_helpers import (
            record_acceptance_inspection,
            record_post_treatment_inspection,
            start_operation,
            complete_operation,
        )
        record_acceptance_inspection(op2["id"], inspector_id="insp-1")
        start_operation(op2["id"], oat_celsius=0)
        complete_operation(op2["id"], actual_liters=3, collected_liters=2)
        record_post_treatment_inspection(op2["id"], result="PASS", inspector_id="insp-2")

        resp = api.get_airline(
            airline["id"], TEST_USERS["billing_clerk_headers"]
        )
        av2 = validate_success(resp)["version"]
        payload = create_invoice_payload(
            op2["id"], expected_airline_version=av2
        )
        resp = api.create_invoice(
            payload, TEST_USERS["billing_clerk_headers"]
        )
        invoice = validate_success(resp, expected_status=201)

        # Per-line rounding: fluid 248 + surcharge 5062 = 5310; sum-then-round
        # would give 25311.
        assert invoice["fluid_charge_cents"] == 248
        assert invoice["storm_surcharge_cents"] == 5062
        assert invoice["total_cents"] == 25310
        assert invoice["total_cents"] != 25311


class TestOperationVoidGuard:
    def test_operation_void_blocked_by_open_invoice(self, api):
        """PRD §3.6: "Voiding is available only on a `CLEARED` operation, and
        only while no invoice for that operation exists in `DRAFT` or `ISSUED`
        status — the presence of either rejects the void with
        `ERR_OPERATION_INVOICED`."

        Design: Corner/errors/operation_void_blocked_by_open_invoice
        """
        station, permit, tank, pad, airline, request, operation, invoice = (
            setup_invoice_for_cleared_operation(
                actual_liters=300, collected_liters=200
            )
        )

        resp = api.void_deice_operation(
            operation["id"], TEST_USERS["pad_operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_OPERATION_INVOICED)

        resp = api.get_deice_operation(
            operation["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "CLEARED"
