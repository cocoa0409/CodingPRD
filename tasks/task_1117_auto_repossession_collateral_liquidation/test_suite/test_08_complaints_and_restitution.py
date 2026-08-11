"""Complaint resolution: the four-link restitution cascade on UPHELD, the
paid_to_date conservation invariant, and complaint lifecycle rejections."""
from test_helpers import (
    ApiErrorId,
    assign_agent,
    create_agent,
    file_complaint,
    get_loan,
    list_deficiency_notices,
    list_ledger_entries,
    list_sale_records,
    make_borrower_headers,
    make_compliance_officer_headers,
    record_deficiency_payment_payload,
    resolve_complaint,
    rm_headers,
    setup_case_cure_expired,
    setup_case_deficiency_noticed,
    validate_error,
    validate_success,
)

CO = make_compliance_officer_headers("co_1")


def _deficiency_case_with_payment(api, borrower_name, email, vin, payment=200_000):
    """DEFICIENCY_NOTICED case whose borrower has paid `payment` toward the
    1,009,530c SENT notice (notice stays SENT), then filed a complaint."""
    ctx = setup_case_deficiency_noticed(
        borrower_overrides={"full_name": borrower_name, "email": email},
        loan_overrides={"vin": vin})
    notice = ctx["notice"]
    paid = validate_success(api.record_deficiency_payment(
        notice["id"], record_deficiency_payment_payload(payment),
        make_borrower_headers(ctx["borrower"]["id"])))
    assert paid["status"] == "SENT"
    assert paid["paid_cents"] == payment
    complaint = file_complaint(ctx["case"]["id"], ctx["borrower"]["id"],
                               category="WRONGFUL_REPOSSESSION",
                               description="payments were current")
    ctx["complaint"] = complaint
    return ctx


class TestRestitutionCascade:
    def test_upheld_complaint_voids_notice_and_sale(self, api):
        """PRD §3.8: "An `UPHELD` outcome fires the four-link restitution
        cascade, applied atomically: first, the complaint itself moves to
        `UPHELD`; second, every deficiency notice of the case in `DRAFT`,
        `SENT`, or `DISPUTED` is voided, every sale record of the case in
        `PENDING_CERTIFICATION` or `CERTIFIED` is voided, and every consignment
        of the case in `DRAFT`, `LISTED`, or `UNSOLD` is withdrawn"

        Design: Difficulty/transitive_cascade/complaint_upheld_restitution_cascade
        """
        ctx = _deficiency_case_with_payment(api, "CU", "cu@x.com", "VIN00000000000015")
        resolved = resolve_complaint(ctx["complaint"]["id"], "UPHELD")
        assert resolved["status"] == "UPHELD"

        notices = list_deficiency_notices(ctx["case"]["id"])
        assert notices[0]["status"] == "VOID", "link 2: the SENT notice is voided"
        sales = list_sale_records(ctx["consignment"]["id"])
        assert sales[0]["status"] == "VOID", "link 2: the CERTIFIED sale is voided"
        consignment = validate_success(api.get_consignment(ctx["consignment"]["id"], rm_headers()))
        assert consignment["status"] == "SOLD", (
            "a SOLD consignment is terminal and not in the withdrawn set")

    def test_upheld_complaint_reverses_payments_and_restores_loan(self, api):
        """PRD §3.8: "third, for every `PAYMENT` ledger entry of the case, a
        `REVERSAL` entry is created with its `reverses_entry_id` pointing at
        the payment it undoes; fourth, the loan's `paid_to_date_cents` is
        decremented by the reversed amounts — the loan is restored as if the
        case's payments never happened — the loan moves back to `CURRENT`, and
        the case settles into `RESTITUTION`."

        Design: Difficulty/transitive_cascade/complaint_upheld_restitution_cascade
        """
        ctx = _deficiency_case_with_payment(api, "CU", "cu@x.com", "VIN00000000000015")
        payments_before = [e for e in list_ledger_entries(ctx["case"]["id"])
                           if e["kind"] == "PAYMENT"]
        assert len(payments_before) == 1

        resolve_complaint(ctx["complaint"]["id"], "UPHELD")

        entries = list_ledger_entries(ctx["case"]["id"])
        reversals = [e for e in entries if e["kind"] == "REVERSAL"]
        assert len(reversals) == 1, "link 3: one REVERSAL per PAYMENT"
        assert reversals[0]["reverses_entry_id"] == payments_before[0]["id"]
        assert reversals[0]["amount_cents"] == payments_before[0]["amount_cents"]

        loan = get_loan(ctx["loan"]["id"])
        assert loan["paid_to_date_cents"] == 0, "link 4: the 200,000c payment is fully reversed"
        assert loan["status"] == "CURRENT"
        case_after = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_after["status"] == "RESTITUTION", "link 1: the case settles into RESTITUTION"


class TestPaymentReversalConservation:
    """Conserved quantity: net borrower-paid money equals
    sum(PAYMENT) - sum(REVERSAL) at every observable point."""

    def test_forward_payment_moves_paid_to_date(self, api):
        """PRD §2.10: "The ledger also drives the loan's running payment total:
        every `PAYMENT` entry increments the loan's `paid_to_date_cents` by its
        amount, and every `REVERSAL` decrements it correspondingly."
        PRD §3.7: "each payment accumulates into the notice's `paid_cents`,
        writes a `PAYMENT` ledger entry, and increments the loan's
        `paid_to_date_cents` by the same amount"

        Design: Difficulty/compensating_invariant/payment_reversal_conserves_paid_to_date
        """
        ctx = setup_case_deficiency_noticed(
            borrower_overrides={"full_name": "PI", "email": "pi@x.com"},
            loan_overrides={"vin": "VIN00000000000036"})
        loan_before = get_loan(ctx["loan"]["id"])
        assert loan_before["paid_to_date_cents"] == 0

        validate_success(api.record_deficiency_payment(
            ctx["notice"]["id"], record_deficiency_payment_payload(200_000),
            make_borrower_headers(ctx["borrower"]["id"])))
        loan_after = get_loan(ctx["loan"]["id"])
        assert loan_after["paid_to_date_cents"] == 200_000

    def test_compensating_reversal_restores_paid_to_date_exactly(self, api):
        """PRD §3.8: "the loan's `paid_to_date_cents` is decremented by the
        reversed amounts — the loan is restored as if the case's payments never
        happened — the loan moves back to `CURRENT`, and the case settles into
        `RESTITUTION`."
        PRD §2.10: "every `PAYMENT` entry increments the loan's
        `paid_to_date_cents` by its amount, and every `REVERSAL` decrements it
        correspondingly."

        Design: Difficulty/compensating_invariant/payment_reversal_conserves_paid_to_date
        """
        ctx = _deficiency_case_with_payment(api, "PI", "pi@x.com", "VIN00000000000036")
        loan_mid = get_loan(ctx["loan"]["id"])
        assert loan_mid["paid_to_date_cents"] == 200_000

        resolve_complaint(ctx["complaint"]["id"], "UPHELD")

        loan_final = get_loan(ctx["loan"]["id"])
        assert loan_final["paid_to_date_cents"] == 0, "no drift after the compensating action"
        assert loan_final["status"] == "CURRENT"
        entries = list_ledger_entries(ctx["case"]["id"])
        paid_sum = sum(e["amount_cents"] for e in entries if e["kind"] == "PAYMENT")
        reversed_sum = sum(e["amount_cents"] for e in entries if e["kind"] == "REVERSAL")
        assert paid_sum - reversed_sum == 0


class TestComplaintResolutionRejections:
    def test_double_resolve_rejected_invalid_complaint_state(self, api):
        """PRD §3.8: "The complaint must still be `UNDER_REVIEW`
        (`ERR_INVALID_COMPLAINT_STATE`), and the resolver must not be the
        manager who opened the case (`ERR_SEGREGATION_OF_DUTIES`)"
        PRD §3.8: "A `DISMISSED` outcome closes the complaint and restores the
        case verbatim to its `pre_complaint_state`"

        Design: Corner/state_machines/double_resolve_rejected_invalid_complaint_state
        """
        ctx = setup_case_cure_expired(
            borrower_overrides={"full_name": "DR", "email": "dr@x.com"},
            loan_overrides={"vin": "VIN00000000000084",
                            "principal_balance_cents": 500_000, "apr_bps": 900,
                            "monthly_payment_cents": 20_000, "missed_installments": 2,
                            "accrued_interest_cents": 8_000, "late_fees_cents": 3_000})
        # Case stands REPO_ACTIVE after an assignment is created.
        agent = create_agent(name="Agent DR", license_number="LIC-DR")
        assign_agent(ctx["case"]["id"], agent["id"])
        case_mid = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_mid["status"] == "REPO_ACTIVE"

        complaint = file_complaint(ctx["case"]["id"], ctx["borrower"]["id"],
                                   category="PROPERTY_LOSS", description="missing items")
        resolved = resolve_complaint(complaint["id"], "DISMISSED")
        assert resolved["status"] == "DISMISSED"
        case_restored = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_restored["status"] == "REPO_ACTIVE"

        resp = api.resolve_complaint(
            complaint["id"], {"outcome": "UPHELD"},
            make_compliance_officer_headers("co_2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_COMPLAINT_STATE)
        case_after = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_after["status"] == "REPO_ACTIVE", "a rejected resolve does not move the case"
