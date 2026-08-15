"""Invoicing, reconciliation against agency records, and the season ledger."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_aircraft,
    assert_invoice,
    create_active_contract,
    create_availability_period_payload,
    create_draft_invoice,
    get_contract,
    get_invoice,
    import_agency_record,
    list_line_items,
    log_sortie,
    make_agency_finance_headers,
    make_carrier_finance_headers,
    set_clock,
    setup_carded_pair,
    setup_on_incident,
    setup_submitted_invoice,
    submit_invoice,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["carrier_ops_headers"]


class TestReconciliationBasisSwitch:
    def test_reconcile_switches_flight_lines_to_agency_basis(self, api):
        """PRD §3.8: "Otherwise the invoice moves to `RECONCILED`:
        `billing_basis` becomes `RECONCILED`, `reconciled_by` records the
        operator, every flight line's `billed_amount_cents` switches to its
        agency amount, the flight subtotal and net recompute under the pinned
        sequence, the season ledger shifts by the difference between new and
        old net, and both the invoice's and the contract's versions increment."
        PRD §3.8: "`mismatch_flag` is set when carrier and agency quantities
        differ by more than one tenth of an hour — a difference of exactly one
        tenth is within tolerance."

        Design: Difficulty/dual_variant_calc/invoice_reconciliation_carrier_vs_agency_basis
        """
        ws = setup_submitted_invoice()  # 50 carrier tenths, 1,500,000 cents
        invoice = ws["invoice"]
        assert invoice["status"] == "SUBMITTED"

        import_agency_record(ws["contract"]["id"], ws["assignment"]["id"],
                             "2026-08-02", 49)

        reconciled = validate_success(api.reconcile_invoice(
            invoice["id"], make_agency_finance_headers("af_1")), 200)
        assert reconciled["status"] == "RECONCILED", "|50 - 49| == 1 is within tolerance"
        assert reconciled["billing_basis"] == "RECONCILED"
        assert reconciled["reconciled_by"] == "af_1"
        assert reconciled["flight_subtotal_cents"] == 1470000, \
            "agency basis: 49 tenths at 300,000 cents/h"
        assert reconciled["net_cents"] == 1470000

        lines = list_line_items(invoice["id"])
        flight_lines = [l for l in lines if l["line_type"] == "FLIGHT_DAY"]
        assert len(flight_lines) == 1
        line = flight_lines[0]
        assert line["agency_qty"] == 49
        assert line["agency_amount_cents"] == 1470000
        assert line["billed_amount_cents"] == 1470000
        assert line["mismatch_flag"] is False

    def test_provisional_bills_carrier_basis_before_reconcile(self, api):
        """PRD §3.8: "Identical carrier data can therefore legitimately bill
        differently across bases: 50 carrier tenths versus 49 agency tenths
        at 300,000 cents per hour bills 1,500,000 cents provisionally but
        1,470,000 reconciled."
        PRD §3.8: "A new invoice is `DRAFT` on the `PROVISIONAL` billing basis
        — carrier logs".

        Design: Difficulty/dual_variant_calc/invoice_reconciliation_carrier_vs_agency_basis
        """
        ws = setup_on_incident()
        log = log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                         "2026-08-02", 0.0, 5.0)
        assert log["flight_hours_tenths"] == 50
        assert log["billable_cents"] == 1500000, "per-sortie rounding"

        invoice = create_draft_invoice(ws["contract"]["id"],
                                       "2026-08-02", "2026-08-02")
        assert invoice["billing_basis"] == "PROVISIONAL"
        assert invoice["flight_subtotal_cents"] == 1500000
        assert invoice["net_cents"] == 1500000

        invoice = submit_invoice(invoice["id"], submitted_by="cf_1",
                                 advance_clock_to="2026-08-09T00:00:00Z")
        contract = get_contract(ws["contract"]["id"])
        assert contract["season_billed_cents"] == 1500000, \
            "submit debits the season ledger by the provisional net"

        import_agency_record(ws["contract"]["id"], ws["assignment"]["id"],
                             "2026-08-02", 49)
        validate_success(api.reconcile_invoice(
            invoice["id"], make_agency_finance_headers("af_1")), 200)
        contract = get_contract(ws["contract"]["id"])
        assert contract["season_billed_cents"] == 1470000, \
            "the ledger shifts by exactly the -30000 basis delta"


class TestDisputeResubmitCycle:
    def _setup_single_day_invoice(self, api):
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(aircraft["id"],
                                               service_date="2026-08-03"),
            OPS), 201)
        invoice = create_draft_invoice(contract["id"], "2026-08-03", "2026-08-03")
        set_clock("2026-08-09T00:00:00Z")
        return contract, invoice

    def test_dispute_resubmit_loop_status_and_restamping(self, api):
        """PRD §3.8: "An `AgencyFinance` operator may dispute a `SUBMITTED`
        invoice, recording a `dispute_reason`; the invoice stays on the
        `PROVISIONAL` basis and the season ledger does not move, because
        `DISPUTED` remains inside the invariant set. `CarrierFinance` may then
        resubmit, clearing `dispute_reason` and restamping `submitted_by` and
        `submitted_at`, again without ledger movement — the `SUBMITTED` →
        `DISPUTED` → `SUBMITTED` loop is the carrier/agency negotiation path."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resubmit_cycle
        """
        _contract, invoice = self._setup_single_day_invoice(api)
        v0 = invoice["version"]
        assert invoice["status"] == "DRAFT"

        submitted = validate_success(api.submit_invoice(
            invoice["id"], make_carrier_finance_headers("cf_1")), 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by"] == "cf_1"
        assert submitted["submitted_at"] is not None
        assert submitted["version"] == v0 + 1

        disputed = validate_success(api.dispute_invoice(
            invoice["id"], {"dispute_reason": "agency hours mismatch"},
            make_agency_finance_headers("af_1")), 200)
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "agency hours mismatch"
        assert disputed["billing_basis"] == "PROVISIONAL"
        assert disputed["version"] == v0 + 2

        resubmitted = validate_success(api.resubmit_invoice(
            invoice["id"], make_carrier_finance_headers("cf_1")), 200)
        assert resubmitted["status"] == "SUBMITTED", "loop re-entry is legal"
        assert resubmitted["dispute_reason"] is None, "resubmit clears the reason"
        assert resubmitted["submitted_by"] == "cf_1", "restamped submitter"
        assert resubmitted["version"] == v0 + 3

    def test_season_billed_stable_through_negotiation_loop(self, api):
        """PRD §3.8: "That ledger obeys a standing invariant — it always
        equals the sum of `net_cents` over the contract's invoices in
        `SUBMITTED`, `DISPUTED`, `RECONCILED`, or `PAID`".

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resubmit_cycle
        """
        contract, invoice = self._setup_single_day_invoice(api)
        assert invoice["net_cents"] == 500000

        validate_success(api.submit_invoice(
            invoice["id"], make_carrier_finance_headers("cf_1")), 200)
        assert get_contract(contract["id"])["season_billed_cents"] == 500000

        validate_success(api.dispute_invoice(
            invoice["id"], {"dispute_reason": "agency hours mismatch"},
            make_agency_finance_headers("af_1")), 200)
        assert get_contract(contract["id"])["season_billed_cents"] == 500000, \
            "DISPUTED remains inside the invariant set"

        validate_success(api.resubmit_invoice(
            invoice["id"], make_carrier_finance_headers("cf_1")), 200)
        assert get_contract(contract["id"])["season_billed_cents"] == 500000, \
            "the loop never double-debits"

        current = get_invoice(invoice["id"])
        assert current["net_cents"] == 500000, "net is stable through the loop"


class TestSubmitVoidConservation:
    def test_submit_then_void_restores_season_billed(self, api):
        """PRD §3.8: "Submitting stamps `submitted_by` with the operator's
        `X-User-ID` and `submitted_at` with the clock, and debits the
        contract: `season_billed_cents` increases by the invoice's `net_cents`";
        "voiding from `SUBMITTED` or `DISPUTED` subtracts the invoice's
        `net_cents` from `season_billed_cents`, the exact compensation of the
        submit side effect"; "a submission followed later by a void of the
        same invoice leaves the ledger exactly at its pre-submit value."

        Design: Difficulty/compensating_invariant/invoice_submit_void_conserve_season_billed
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(aircraft["id"],
                                               service_date="2026-08-03"),
            OPS), 201)
        invoice = create_draft_invoice(contract["id"], "2026-08-03", "2026-08-03")
        assert invoice["net_cents"] == 500000
        set_clock("2026-08-09T00:00:00Z")
        assert get_contract(contract["id"])["season_billed_cents"] == 0

        validate_success(api.submit_invoice(
            invoice["id"], make_carrier_finance_headers("cf_1")), 200)
        assert get_contract(contract["id"])["season_billed_cents"] == 500000, \
            "submit adds the invoice to the invariant set"

        voided = validate_success(api.void_invoice(
            invoice["id"], make_carrier_finance_headers("cf_1")), 200)
        assert voided["status"] == "VOID"
        assert get_contract(contract["id"])["season_billed_cents"] == 0, \
            "the forward+compensating pair conserves the ledger exactly"

    def test_void_from_submitted_compensates_versions_and_net(self, api):
        """PRD §3.8: "voiding from `DRAFT` touches no ledger — a draft was
        never counted — while voiding from `SUBMITTED` or `DISPUTED` subtracts
        the invoice's `net_cents` from `season_billed_cents`, the exact
        compensation of the submit side effect, bumping both the invoice's and
        the contract's versions."

        Design: Difficulty/compensating_invariant/invoice_submit_void_conserve_season_billed
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(aircraft["id"],
                                               service_date="2026-08-03"),
            OPS), 201)
        invoice = create_draft_invoice(contract["id"], "2026-08-03", "2026-08-03")
        set_clock("2026-08-09T00:00:00Z")

        submitted = validate_success(api.submit_invoice(
            invoice["id"], make_carrier_finance_headers("cf_1")), 200)
        contract_mid = get_contract(contract["id"])
        assert contract_mid["season_billed_cents"] == submitted["net_cents"]

        voided = validate_success(api.void_invoice(
            invoice["id"], make_carrier_finance_headers("cf_1")), 200)
        assert voided["version"] == submitted["version"] + 1
        contract_after = get_contract(contract["id"])
        assert contract_after["version"] == contract_mid["version"] + 1
        assert contract_after["season_billed_cents"] == 0


class TestInvoiceComposition:
    def test_invoice_penalty_evaluation_order(self, api):
        """PRD §3.8: "First, `availability_subtotal_cents` sums the carrier
        amounts of the availability lines."
        PRD §3.8: "Second, `flight_subtotal_cents` sums `billed_amount_cents`
        over the flight lines under the current basis."
        PRD §3.8: "Fifth, `penalty_cents` is five percent of
        `availability_subtotal_cents`, rounded half up to whole cents — but
        only when at least one availability day exists and the ratio of
        compliant to expected days falls below 0.98, compared as an exact
        rational: compliant days times one hundred strictly less than expected
        days times ninety-eight."
        PRD §3.8: "Sixth, `net_cents` is the availability subtotal plus the
        flight subtotal minus the penalty."
        PRD §3.8: "Lines are emitted in a pinned order: availability days by
        `service_date` ascending, then flight days by `reference_date`
        ascending with ties broken by the assignment's `created_at` ascending,
        then the penalty line last."

        Design: Corner/calculations/invoice_penalty_evaluation_order
        """
        ws = setup_on_incident()
        # Two EU days: 570 min compliant (500000) and 285 min short (250000).
        validate_success(api.create_availability_period(
            ws["contract"]["id"],
            create_availability_period_payload(
                ws["aircraft"]["id"], service_date="2026-08-03",
                available_start="2026-08-03T07:00:00Z",
                available_end="2026-08-03T16:30:00Z"),
            OPS), 201)
        validate_success(api.create_availability_period(
            ws["contract"]["id"],
            create_availability_period_payload(
                ws["aircraft"]["id"], service_date="2026-08-04",
                available_start="2026-08-04T07:00:00Z",
                available_end="2026-08-04T11:45:00Z"),
            OPS), 201)
        log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                   "2026-08-02", 100.0, 101.05)
        log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                   "2026-08-02", 200.0, 200.65)

        invoice = create_draft_invoice(ws["contract"]["id"],
                                       "2026-08-01", "2026-08-31")
        assert invoice["availability_subtotal_cents"] == 750000
        assert invoice["flight_subtotal_cents"] == 540000
        assert invoice["penalty_cents"] == 37500, \
            "compliance 1/2 < 0.98: round_half_up(750000 * 0.05)"
        assert invoice["net_cents"] == 1252500, \
            "750000 + 540000 - 37500, penalty evaluated before net"

        lines = list_line_items(invoice["id"])
        assert len(lines) == 4
        assert lines[0]["line_type"] == "AVAILABILITY_DAY"
        assert lines[0]["reference_date"] == "2026-08-03"
        assert lines[0]["carrier_amount_cents"] == 500000
        assert lines[1]["line_type"] == "AVAILABILITY_DAY"
        assert lines[1]["reference_date"] == "2026-08-04"
        assert lines[1]["carrier_amount_cents"] == 250000
        assert lines[2]["line_type"] == "FLIGHT_DAY"
        assert lines[2]["carrier_qty"] == 18
        assert lines[2]["carrier_amount_cents"] == 540000
        assert lines[3]["line_type"] == "PENALTY", "penalty line is last"
        assert lines[3]["carrier_qty"] == 0
        assert lines[3]["carrier_amount_cents"] == -37500

    def test_invoice_empty_period_zero_penalty(self, api):
        """PRD §3.8: "With no availability days at all, the penalty is zero."
        PRD §3.8: "A new invoice is `DRAFT` on the `PROVISIONAL` billing basis
        — carrier logs — with `availability_subtotal_cents`,
        `flight_subtotal_cents`, `penalty_cents`, and `net_cents` all zero".

        Design: Corner/calculations/invoice_empty_period_zero_penalty
        """
        contract = create_active_contract()
        invoice = create_draft_invoice(contract["id"], "2026-08-02", "2026-08-02")
        assert_invoice(invoice)
        assert invoice["availability_subtotal_cents"] == 0
        assert invoice["flight_subtotal_cents"] == 0
        assert invoice["penalty_cents"] == 0, \
            "expected_days == 0: the compliance ratio never divides by zero"
        assert invoice["net_cents"] == 0


class TestReconciliationMismatch:
    def test_reconciliation_tolerance_boundary_dispute(self, api):
        """PRD §3.8: "On a match, `agency_qty` takes the record's
        `agency_flight_hours_tenths`, `agency_amount_cents` is computed from
        those tenths at the contract's flight-hour rate with round-half-up to
        whole cents, and `mismatch_flag` is set when carrier and agency
        quantities differ by more than one tenth of an hour — a difference of
        exactly one tenth is within tolerance."
        PRD §3.8: "If any flight line mismatches, the invoice drops to
        `DISPUTED` with `dispute_reason` set to `RECONCILIATION_MISMATCH`,
        basis unchanged, net unchanged."

        Design: Corner/calculations/reconciliation_tolerance_boundary_dispute
        """
        ws = setup_submitted_invoice()  # 50 carrier tenths, net 1,500,000
        import_agency_record(ws["contract"]["id"], ws["assignment"]["id"],
                             "2026-08-02", 48)

        disputed = validate_success(api.reconcile_invoice(
            ws["invoice"]["id"], make_agency_finance_headers("af_1")), 200)
        assert disputed["status"] == "DISPUTED", "|50 - 48| == 2 > tolerance 1"
        assert disputed["billing_basis"] == "PROVISIONAL", "basis unchanged"
        assert disputed["net_cents"] == 1500000, "net unchanged on mismatch"
        assert disputed["dispute_reason"] == "RECONCILIATION_MISMATCH"

        lines = list_line_items(ws["invoice"]["id"])
        flight_lines = [l for l in lines if l["line_type"] == "FLIGHT_DAY"]
        assert len(flight_lines) == 1
        assert flight_lines[0]["mismatch_flag"] is True
        assert flight_lines[0]["agency_qty"] == 48, \
            "agency quantity recorded for the dispute trail"


class TestSubmitWindowAndOverlap:
    def test_invoice_submit_period_close_boundary(self, api):
        """PRD §3.8: "Submission moves the invoice `DRAFT` → `SUBMITTED` and
        is allowed only once the billing period has fully closed —
        `period_end` strictly before the current clock date, otherwise
        `ERR_BILLING_PERIOD_NOT_CLOSED`."

        Design: Corner/validations/invoice_submit_period_close_boundary
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(aircraft["id"],
                                               service_date="2026-08-03"),
            OPS), 201)
        invoice = create_draft_invoice(contract["id"], "2026-08-03", "2026-08-03")

        # Clock date equal to period_end: the period is not yet closed.
        set_clock("2026-08-03T23:59:00Z")
        resp = api.submit_invoice(
            invoice["id"], make_carrier_finance_headers("cf_1"))
        validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_NOT_CLOSED,
                       expected_status=422)

        set_clock("2026-08-04T00:00:00Z")
        submitted = validate_success(api.submit_invoice(
            invoice["id"], make_carrier_finance_headers("cf_1")), 200)
        assert submitted["status"] == "SUBMITTED"

    def test_invoice_period_overlap_rejected(self, api):
        """PRD §3.8: "At most one non-`VOID` invoice may exist per contract
        and `period_start` pair; a repeat period start is
        `ERR_INVOICE_PERIOD_OVERLAP`."

        Design: Corner/validations/invoice_period_overlap_rejected
        """
        contract = create_active_contract()
        create_draft_invoice(contract["id"], "2026-08-03", "2026-08-07")

        # Fresh OCC version: the rejection is the uniqueness constraint.
        version = get_contract(contract["id"])["version"]
        resp = api.create_invoice(contract["id"], {
            "period_start": "2026-08-03", "period_end": "2026-08-10",
            "expected_contract_version": version,
        }, make_carrier_finance_headers("cf_1"))
        validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP,
                       expected_status=409)


class TestSegregationAndClosure:
    def test_reconcile_same_operator_segregation_of_duties(self, api):
        """PRD §2.1: "One segregation-of-duties rule does compare opaque
        identifiers: the operator who reconciles an invoice must not be the
        operator who submitted it, and a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.8: "Without a match, the line's agency fields simply mirror the
        carrier values and no mismatch is flagged".

        Design: Corner/validations/reconcile_same_operator_segregation_of_duties
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(aircraft["id"],
                                               service_date="2026-08-03"),
            OPS), 201)
        invoice = create_draft_invoice(contract["id"], "2026-08-03", "2026-08-03")
        submit_invoice(invoice["id"], submitted_by="cf_1",
                       advance_clock_to="2026-08-09T00:00:00Z")

        # Same operator id as the submitter, even under the AgencyFinance role.
        resp = api.reconcile_invoice(
            invoice["id"], make_agency_finance_headers("cf_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)

        reconciled = validate_success(api.reconcile_invoice(
            invoice["id"], make_agency_finance_headers("af_1")), 200)
        assert reconciled["status"] == "RECONCILED", \
            "no agency records: all lines mirror carrier basis, no mismatch"

    def test_invoice_paid_terminal_lockdown(self, api):
        """PRD §3.8: "A reconciled invoice is marked paid by `AgencyFinance`,
        landing in terminal `PAID` with the season ledger unmoved, since
        `PAID` stays in the invariant set."
        PRD §2.9: "terminal states reject every further action
        (`ERR_ALREADY_TERMINAL`, HTTP 409) — terminal means a `CLOSED`
        contract, incident, or dispatch order, a `DECLINED` or `CANCELLED`
        order, a `DECARDED` aircraft, a `PAID` or `VOID` invoice, a
        `DEMOBILIZED` assignment, a `DROPPED` load, and an `EXCUSED` or
        `UNAVAILABLE` availability period".

        Design: Corner/state_machines/invoice_paid_terminal_lockdown
        """
        ws = setup_submitted_invoice()  # 50 carrier tenths
        import_agency_record(ws["contract"]["id"], ws["assignment"]["id"],
                             "2026-08-02", 50)  # exact match, diff 0 <= 1

        reconciled = validate_success(api.reconcile_invoice(
            ws["invoice"]["id"], make_agency_finance_headers("af_1")), 200)
        assert reconciled["status"] == "RECONCILED"

        paid = validate_success(api.mark_invoice_paid(
            ws["invoice"]["id"], make_agency_finance_headers("af_1")), 200)
        assert paid["status"] == "PAID"

        resp = api.dispute_invoice(
            ws["invoice"]["id"], {"dispute_reason": "late objection"},
            make_agency_finance_headers("af_1"))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL,
                       expected_status=409)


class TestInvoiceOcc:
    def test_occ_invoice_create_stale_version(self, api):
        """PRD §2.8: "Creating an invoice under a contract requires the
        request to carry `expected_contract_version`, the contract `version`
        the client last observed. If another accepted write — an invoice
        creation, an availability cascade, a submit or void adjustment — has
        advanced the contract's version since that read, the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §3.8: "the creation itself bumps the contract's version".

        Design: Corner/complexity_layers/occ_invoice_create_stale_version
        """
        contract = create_active_contract()
        stale_version = get_contract(contract["id"])["version"]

        first = validate_success(api.create_invoice(contract["id"], {
            "period_start": "2026-08-03", "period_end": "2026-08-07",
            "expected_contract_version": stale_version,
        }, make_carrier_finance_headers("cf_1")), 201)
        assert first["status"] == "DRAFT"

        mid_version = get_contract(contract["id"])["version"]
        assert mid_version == stale_version + 1, \
            "each successful invoice create increments the contract version by 1"

        resp = api.create_invoice(contract["id"], {
            "period_start": "2026-08-10", "period_end": "2026-08-14",
            "expected_contract_version": stale_version,
        }, make_carrier_finance_headers("cf_1"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        second = validate_success(api.create_invoice(contract["id"], {
            "period_start": "2026-08-10", "period_end": "2026-08-14",
            "expected_contract_version": mid_version,
        }, make_carrier_finance_headers("cf_1")), 201)
        assert second["status"] == "DRAFT"
        assert get_contract(contract["id"])["version"] == mid_version + 1
