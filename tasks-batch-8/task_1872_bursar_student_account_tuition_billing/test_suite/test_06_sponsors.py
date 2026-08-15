"""Sponsor agreement windows, invoice generation bases, receivable lifecycle,
and utilization conservation claims (PRD §3.5, §3.6, §2.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_agreement,
    create_draft_invoice,
    create_draft_term,
    create_open_term,
    create_posted_waiver,
    enroll,
    entries_of_type,
    find_charge_entry,
    issue_invoice,
    make_student,
    read_account,
    read_ledger,
    set_clock,
    setup_account_with_enrollment,
    setup_issued_invoice,
    setup_sponsor_scenario,
    validate_error,
    validate_success,
)

_STAFF = TEST_USERS["bursar_staff_headers"]


class TestSponsorInvoiceNetVsGross:
    """billing_basis selects the invoice-amount variant (PRD §3.6)."""

    def _build_pair(self):
        term_ctx = setup_account_with_enrollment(credit_hours=12,
                                                 external_ref="S-NET")
        # Shared term for both students so the scenarios are identical.
        term = term_ctx["term"]
        s_grs = make_student("S-GRS", "Gross Kid")
        enr_grs = enroll(s_grs["id"], term["id"], credit_hours=12)
        acc_net = term_ctx["account_id"]
        acc_grs = enr_grs["account_id"]
        create_posted_waiver(acc_net, kind="SCHOLARSHIP", awarded_cents=100000)
        create_posted_waiver(acc_grs, kind="SCHOLARSHIP", awarded_cents=100000)
        ag_net = create_agreement(
            term_ctx["student"]["id"], term["id"], sponsor_name="NetCorp",
            billing_basis="NET_OF_WAIVER",
        )
        ag_grs = create_agreement(
            s_grs["id"], term["id"], sponsor_name="GrossCorp",
            billing_basis="GROSS",
        )
        return term_ctx, acc_grs, ag_net, ag_grs

    def test_net_of_waiver_subtracts_posted_waiver_allocations(self, api):
        """PRD §3.6: "Under `NET_OF_WAIVER`, each line bills the charge amount
        minus the total waiver allocations referencing it from `POSTED`
        (non-revoked) waivers on the same account, floored at zero."

        Design: Difficulty/dual_variant_calc/sponsor_invoice_net_vs_gross
        """
        (ctx, _acc_grs, ag_net, _ag_grs) = self._build_pair()
        invoice = create_draft_invoice(ag_net["id"])
        assert invoice["status"] == "DRAFT"
        assert invoice["total_cents"] == 335000, (
            "NET: (420000 - 100000) + 15000"
        )
        ledger = read_ledger(ctx["account_id"])
        tuition_id = find_charge_entry(ledger, "TUITION")["id"]
        fee_id = find_charge_entry(ledger, "FEE")["id"]
        lines = {l["ledger_entry_id"]: l["amount_cents"] for l in invoice["lines"]}
        assert lines[tuition_id] == 320000, "TUITION line nets out the waiver"
        assert lines[fee_id] == 15000, "FEE line has no waiver allocation"

    def test_gross_bills_full_charge_amounts(self, api):
        """PRD §3.6: "Under `GROSS`, each line bills the full charge amount
        even where waivers have already posted against that charge."

        Design: Difficulty/dual_variant_calc/sponsor_invoice_net_vs_gross
        """
        (_ctx, _acc_grs, _ag_net, ag_grs) = self._build_pair()
        invoice = create_draft_invoice(ag_grs["id"])
        assert invoice["status"] == "DRAFT"
        assert invoice["total_cents"] == 435000, (
            "GROSS ignores the 100000 waiver: 420000 + 15000"
        )
        amounts = sorted(l["amount_cents"] for l in invoice["lines"])
        assert amounts == [15000, 420000]


class TestSponsorAgreementHalfOpenAdjacency:
    """Half-open coverage windows: adjacency is not overlap (PRD §3.5)."""

    def test_adjacent_windows_do_not_overlap(self, api):
        """PRD §3.5: "because the windows are half-open, strict adjacency —
        one agreement ending exactly on the day the next begins — does **not**
        count as overlap."

        Design: Difficulty/resource_temporal_overlap/sponsor_agreement_half_open_adjacency
        """
        term = create_draft_term()
        student = make_student("S-SPH", "Sponsor Hub")
        create_agreement(student["id"], term["id"], sponsor_name="Alpha",
                         cap_cents=300000, covers_fees=False,
                         start_date="2026-08-01", end_date="2026-12-31")
        adjacent = create_agreement(student["id"], term["id"], sponsor_name="Beta",
                                    cap_cents=200000, covers_fees=False,
                                    start_date="2026-12-31", end_date="2027-05-31")
        assert adjacent["status"] == "ACTIVE"

    def test_intersecting_window_with_shared_kind_rejected(self, api):
        """PRD §3.5: "Overlap between two agreements of the same student is
        policed only when their covered kinds intersect (both cover tuition, or
        both cover fees) ... A true overlap is rejected with
        `ERR_SPONSOR_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/sponsor_agreement_half_open_adjacency
        """
        term = create_draft_term()
        student = make_student("S-SPO", "Sponsor Overlap")
        create_agreement(student["id"], term["id"], sponsor_name="Alpha",
                         cap_cents=300000, covers_fees=False,
                         start_date="2026-08-01", end_date="2026-12-31")
        res = api.create_sponsor_agreement(
            {
                "sponsor_name": "Gamma",
                "student_id": student["id"],
                "term_id": term["id"],
                "cap_cents": 100000,
                "covers_tuition": True,
                "covers_fees": False,
                "billing_basis": "GROSS",
                "start_date": "2026-10-01",
                "end_date": "2027-02-01",
            },
            _STAFF,
        )
        validate_error(res, ApiErrorId.ERR_SPONSOR_WINDOW_OVERLAP,
                       expected_status=409)


def test_sponsor_cap_exhaustion_boundary(api, bursar_staff_headers):
    """PRD §3.6: "when `billed_cents` reaches `cap_cents` exactly, the
    agreement transitions itself to `EXHAUSTED`, after which no further
    invoices may be created on it", and "invoicing an `EXHAUSTED` or
    `TERMINATED` agreement is rejected with `ERR_AGREEMENT_NOT_ACTIVE`
    (HTTP 409)".

    Design: Corner/calculations/sponsor_cap_exhaustion_boundary
    """
    ctx = setup_sponsor_scenario(billing_basis="GROSS", cap_cents=435000,
                                 external_ref="S-CAP2")
    invoice = create_draft_invoice(ctx["agreement"]["id"])
    assert invoice["total_cents"] == 435000, "cap fits both lines exactly"

    issue_invoice(invoice["id"])
    agreement = validate_success(
        api.get_sponsor_agreement(ctx["agreement"]["id"], bursar_staff_headers), 200
    )
    assert agreement["status"] == "EXHAUSTED"
    assert agreement["billed_cents"] == 435000

    res = api.create_sponsor_invoice({"agreement_id": ctx["agreement"]["id"]},
                                     bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, expected_status=409)


class TestSponsorInvoiceDisputeReinstateCycle:
    """ISSUED -> PARTIALLY_PAID -> DISPUTED -> PARTIALLY_PAID (PRD §3.6)."""

    def _setup_disputed(self):
        ctx = setup_issued_invoice(external_ref="S-SPN")
        inv = ctx["invoice"]
        return ctx, inv

    def test_partial_payment_then_dispute_records_reason(
        self, api, bursar_staff_headers
    ):
        """PRD §3.6: "A remittance smaller than the remainder moves an `ISSUED`
        invoice to `PARTIALLY_PAID`" and "Disputing an `ISSUED` or
        `PARTIALLY_PAID` invoice records the supplied `dispute_reason` and
        moves the invoice to `DISPUTED`, blocking further remittances."

        Design: Difficulty/non_linear_state_machine/sponsor_invoice_dispute_reinstate_cycle
        """
        ctx, inv = self._setup_disputed()
        partial = validate_success(
            api.record_sponsor_payment(inv["id"], {"amount_cents": 200000},
                                       bursar_staff_headers),
            200,
        )
        assert partial["status"] == "PARTIALLY_PAID"
        assert partial["paid_cents"] == 200000

        disputed = validate_success(
            api.transition_sponsor_invoice(
                inv["id"],
                {"action": "DISPUTE", "dispute_reason": "Sponsor queries fee line"},
                bursar_staff_headers,
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "Sponsor queries fee line"

    def test_reinstate_returns_to_partially_paid_preserving_remittance(
        self, api, bursar_staff_headers
    ):
        """PRD §3.6: "Reinstating a `DISPUTED` invoice clears the
        `dispute_reason` and returns it to `ISSUED` — or, when partial payment
        had already been recorded before the dispute, to `PARTIALLY_PAID`."

        Design: Difficulty/non_linear_state_machine/sponsor_invoice_dispute_reinstate_cycle
        """
        ctx, inv = self._setup_disputed()
        validate_success(
            api.record_sponsor_payment(inv["id"], {"amount_cents": 200000},
                                       bursar_staff_headers),
            200,
        )
        validate_success(
            api.transition_sponsor_invoice(
                inv["id"],
                {"action": "DISPUTE", "dispute_reason": "Sponsor queries fee line"},
                bursar_staff_headers,
            ),
            200,
        )
        reinstated = validate_success(
            api.transition_sponsor_invoice(inv["id"], {"action": "REINSTATE"},
                                           bursar_staff_headers),
            200,
        )
        assert reinstated["status"] == "PARTIALLY_PAID", (
            "paid_cents > 0 must return the invoice to PARTIALLY_PAID"
        )
        assert reinstated["paid_cents"] == 200000
        assert reinstated["dispute_reason"] is None


class TestInvoiceIssueVoidCapConservation:
    """Issue+void must return cap utilization and the ledger to zero (PRD §3.6)."""

    def test_issue_moves_debt_to_sponsor(self, api, bursar_staff_headers):
        """PRD §3.6: "Issuing posts a `SPONSOR_CHARGE` ledger entry for the
        invoice total — a credit-family entry that reduces the student account
        balance — with `source_ref` equal to the invoice id, recomputes the
        account, and advances agreement utilization: the invoice total is added
        to `billed_cents`".

        Design: Difficulty/compensating_invariant/invoice_issue_void_cap_conservation
        """
        ctx = setup_sponsor_scenario(billing_basis="GROSS", cap_cents=1000000,
                                     external_ref="S-CAP")
        invoice = create_draft_invoice(ctx["agreement"]["id"])
        issue_invoice(invoice["id"])
        agreement = validate_success(
            api.get_sponsor_agreement(ctx["agreement"]["id"], bursar_staff_headers),
            200,
        )
        account = read_account(ctx["account_id"])
        assert agreement["billed_cents"] == 435000
        assert account["sponsor_total_cents"] == 435000
        assert account["balance_cents"] == 0

    def test_void_restores_cap_and_student_balance(self, api, bursar_staff_headers):
        """PRD §3.6: "voiding an `ISSUED` invoice posts a `SPONSOR_REVERSAL`
        entry for the full total, recomputes the account, and subtracts the
        total from the agreement's `billed_cents` — though an agreement that
        has already flipped to `EXHAUSTED` stays `EXHAUSTED`; voiding never
        revives it."

        Design: Difficulty/compensating_invariant/invoice_issue_void_cap_conservation
        """
        ctx = setup_sponsor_scenario(billing_basis="GROSS", cap_cents=1000000,
                                     external_ref="S-CAV")
        invoice = issue_invoice(create_draft_invoice(ctx["agreement"]["id"])["id"])
        validate_success(
            api.transition_sponsor_invoice(invoice["id"], {"action": "VOID"},
                                           bursar_staff_headers),
            200,
        )
        agreement = validate_success(
            api.get_sponsor_agreement(ctx["agreement"]["id"], bursar_staff_headers),
            200,
        )
        account = read_account(ctx["account_id"])
        assert agreement["billed_cents"] == 0, "void must release utilization"
        assert agreement["status"] == "ACTIVE", "void must not terminate the agreement"
        assert account["sponsor_total_cents"] == 0
        assert account["balance_cents"] == 435000
        ledger = read_ledger(ctx["account_id"])
        assert [e["amount_cents"] for e in entries_of_type(ledger, "SPONSOR_CHARGE")] == [435000]
        assert [e["amount_cents"] for e in entries_of_type(ledger, "SPONSOR_REVERSAL")] == [435000]


def test_invoice_remittance_overpay_and_disputed_errors(api, bursar_staff_headers):
    """PRD §3.6: "Recording a remittance against an `ISSUED` or
    `PARTIALLY_PAID` invoice requires a positive `amount_cents` that does not
    exceed the unpaid remainder; an overpayment is rejected with
    `ERR_OVERPAYMENT` (HTTP 422), and remittances attempted while the invoice
    is `DISPUTED`, `PAID`, or `VOID` are rejected with
    `ERR_INVOICE_STATE_INVALID`."

    Design: Corner/errors/invoice_remittance_overpay_and_disputed_errors
    """
    ctx = setup_issued_invoice(external_ref="S-RMT")
    inv = ctx["invoice"]

    res = api.record_sponsor_payment(inv["id"], {"amount_cents": 500000},
                                     bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_OVERPAYMENT, expected_status=422)
    current = validate_success(
        api.get_sponsor_invoice(inv["id"], bursar_staff_headers), 200
    )
    assert current["paid_cents"] == 0

    validate_success(
        api.transition_sponsor_invoice(
            inv["id"], {"action": "DISPUTE", "dispute_reason": "Audit"},
            bursar_staff_headers,
        ),
        200,
    )
    res = api.record_sponsor_payment(inv["id"], {"amount_cents": 100},
                                     bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_INVOICE_STATE_INVALID, expected_status=409)


def test_draft_invoice_exists_and_billing_window_errors(api, bursar_staff_headers):
    """PRD §3.6: "at most one `DRAFT` invoice may exist per agreement at a
    time — a second attempt is rejected with `ERR_DRAFT_INVOICE_EXISTS`
    (HTTP 409)" and "the current clock date must not have passed the billing
    cutoff, which closes thirty days after the agreement's term end date,
    otherwise `ERR_BILLING_WINDOW_CLOSED` (HTTP 422)".

    Design: Corner/errors/draft_invoice_exists_and_billing_window_errors
    """
    ctx = setup_account_with_enrollment(credit_hours=12, external_ref="S-2W")
    sid, tid = ctx["student"]["id"], ctx["term"]["id"]
    ag1 = create_agreement(sid, tid, sponsor_name="WinOne",
                           start_date="2026-08-01", end_date="2026-10-01")
    ag2 = create_agreement(sid, tid, sponsor_name="WinTwo",
                           start_date="2026-10-01", end_date="2026-12-31")

    create_draft_invoice(ag1["id"])
    res = api.create_sponsor_invoice({"agreement_id": ag1["id"]},
                                     bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_DRAFT_INVOICE_EXISTS, expected_status=409)

    # Past the billing cutoff (term end 2026-12-11 + 30 days = 2027-01-10).
    set_clock("2027-01-15T00:00:00Z")
    res = api.create_sponsor_invoice({"agreement_id": ag2["id"]},
                                     bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_BILLING_WINDOW_CLOSED, expected_status=422)


def test_no_billable_charges_returns_422(api, bursar_staff_headers):
    """PRD §3.6: "If the walk yields no lines at all — nothing eligible, or the
    first eligible line already exceeding the remaining cap — creation is
    rejected with `ERR_NO_BILLABLE_CHARGES` (HTTP 422)."

    Design: Corner/errors/no_billable_charges_returns_422
    """
    ctx = setup_account_with_enrollment(credit_hours=12, external_ref="S-NCV")
    agreement = create_agreement(
        ctx["student"]["id"], ctx["term"]["id"], sponsor_name="ZeroCover",
        cap_cents=500000, covers_tuition=False, covers_fees=False,
    )
    res = api.create_sponsor_invoice({"agreement_id": agreement["id"]},
                                     bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_NO_BILLABLE_CHARGES, expected_status=422)


class TestSponsorInvoiceReferentialBeatsTemporal:
    """Referential coherence (family 5) outranks temporal windows (family 6)."""

    def _setup_ghost_agreement(self):
        term = create_open_term()
        student = make_student("S-NOA", "NoAcct")
        agreement = create_agreement(student["id"], term["id"],
                                     sponsor_name="GhostCorp", cap_cents=500000)
        set_clock("2027-01-15T00:00:00Z")  # past end_date + 30-day cutoff
        return agreement

    def test_missing_account_wins_over_billing_cutoff(self, api,
                                                      bursar_staff_headers):
        """PRD §3.6: "a `StudentAccount` must already exist for the agreement's
        student and term — otherwise `ERR_NO_ACCOUNT_FOR_AGREEMENT` (HTTP 422)"
        and PRD §2.9: the pipeline evaluates "(5) cross-entity referential
        coherence; (6) temporal windows" in that order, and "Ordering matters
        because it determines which error surfaces when several rules are
        violated at once".

        Design: Difficulty/priority_pair_validation_conflict/sponsor_invoice_referential_beats_temporal
        """
        agreement = self._setup_ghost_agreement()
        res = api.create_sponsor_invoice({"agreement_id": agreement["id"]},
                                         bursar_staff_headers)
        validate_error(res, ApiErrorId.ERR_NO_ACCOUNT_FOR_AGREEMENT,
                       expected_status=422)

    def test_billing_cutoff_fires_when_referential_passes(self, api,
                                                          bursar_staff_headers):
        """PRD §3.6: "the current clock date must not have passed the billing
        cutoff, which closes thirty days after the agreement's term end date,
        otherwise `ERR_BILLING_WINDOW_CLOSED` (HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/sponsor_invoice_referential_beats_temporal
        """
        ctx = setup_account_with_enrollment(credit_hours=12, external_ref="S-BWC")
        agreement = create_agreement(ctx["student"]["id"], ctx["term"]["id"],
                                     sponsor_name="LateCorp", cap_cents=500000)
        set_clock("2027-01-15T00:00:00Z")
        res = api.create_sponsor_invoice({"agreement_id": agreement["id"]},
                                         bursar_staff_headers)
        validate_error(res, ApiErrorId.ERR_BILLING_WINDOW_CLOSED,
                       expected_status=422)
