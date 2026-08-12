"""Billing lifecycle: finalize gate, accept cascade, post-payment review /
rebill cycle, segregation of duties, timely filing, compensating invariant."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_diagnosis,
    get_success_data,
    make_clerk_headers,
    make_officer_headers,
    record_payment_payload,
    create_rebill_request_payload,
    setup_in_progress,
    setup_open_review,
    setup_pending_rebill,
    setup_submitted_case,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

MCC_EXPECTED = 1365000  # weight 2.1000 x 650000; charges 2000000 never trigger outlier


def _mcc_lines():
    return [
        {"icd_code": "I21.09", "poa": "Y", "sequence": 1, "is_principal": True},
        {"icd_code": "N18.6", "poa": "Y", "sequence": 2, "cc_level": "MCC"},
    ]


class TestBillFinalizeRequiresChartCoded:
    def test_finalize_with_submitted_chart_rejected(self, api, clerk_headers, manager_headers):
        """PRD §3.6: "Finalizing a `READY` bill requires the chart to be
        `CODED` — finalizing against an uncoded chart fails with
        `ERR_CHART_NOT_CODED`." For a DRAFT bill the state ladder of §2.8 also
        names "finalizing from `DRAFT`" as `ERR_INVALID_STATE`; the two are
        same-tier, so either code satisfies the chart gate.

        Design: Difficulty/cross_entity_state_dependency/bill_finalize_requires_chart_coded
        """
        ctx = setup_submitted_case("MRN-CE1", "E-CE1", acuity="MEDICAL_LOW", credential="CCS")
        bill = get_success_data(
            api.create_bill({"account_id": ctx["account"]["id"]}, clerk_headers)
        )
        assert bill["status"] == "DRAFT"
        res = api.finalize_bill(bill["id"], clerk_headers)
        validate_error_is_one_of(
            res, [ApiErrorId.ERR_CHART_NOT_CODED, ApiErrorId.ERR_INVALID_STATE]
        )
        assert res.status_code == 409

    def test_finalize_with_in_coding_chart_rejected(self, api, clerk_headers, manager_headers):
        """PRD §3.6: "finalizing against an uncoded chart fails with
        `ERR_CHART_NOT_CODED`." A chart still IN_CODING is not CODED either;
        the finalize must fail (same-tier `ERR_INVALID_STATE` for the DRAFT
        bill is equally ladder-consistent) and the bill must stay DRAFT.

        Design: Difficulty/cross_entity_state_dependency/bill_finalize_requires_chart_coded
        """
        ctx = setup_in_progress("MRN-CE1B", "E-CE1B", acuity="MEDICAL_LOW", credential="CCS")
        add_diagnosis(ctx["chart"]["id"], ctx["coder"]["id"],
                      icd_code="I21.09", poa="Y", sequence=1, is_principal=True)
        bill = get_success_data(
            api.create_bill({"account_id": ctx["account"]["id"]}, clerk_headers)
        )
        res = api.finalize_bill(bill["id"], clerk_headers)
        validate_error_is_one_of(
            res, [ApiErrorId.ERR_CHART_NOT_CODED, ApiErrorId.ERR_INVALID_STATE]
        )
        bill_after = get_success_data(api.get_bill(bill["id"], clerk_headers))
        assert bill_after["status"] == "DRAFT"


class TestAcceptCascadesChartAndBill:
    def test_accept_moves_chart_to_coded_and_bill_to_ready(self, api, clerk_headers, manager_headers):
        """PRD §3.5: "Accepting a `SUBMITTED` assignment moves it to `ACCEPTED`
        and fires a two-hop cascade: the chart moves from `SUBMITTED` to
        `CODED`, and if a bill already exists for the account in `DRAFT`, that
        bill moves to `READY` with its `expected_reimbursement_cents` set to
        the coded case's current value."

        Design: Difficulty/transitive_cascade/accept_cascades_chart_and_bill
        """
        ctx = setup_submitted_case(
            "MRN-TC2", "E-TC2",
            acuity="MEDICAL_LOW", credential="CCS",
            total_charges_cents=900000, financial_class="SELF_PAY",
        )
        bill = get_success_data(
            api.create_bill({"account_id": ctx["account"]["id"]}, clerk_headers)
        )
        assert bill["status"] == "DRAFT"

        accepted = validate_success(
            api.accept_assignment(ctx["assignment"]["id"], manager_headers), 200
        )
        assert accepted["status"] == "ACCEPTED"

        chart = get_success_data(api.get_chart(ctx["chart"]["id"], manager_headers))
        assert chart["status"] == "CODED"

        bill_after = get_success_data(api.get_bill(bill["id"], clerk_headers))
        assert bill_after["status"] == "READY"
        assert bill_after["expected_reimbursement_cents"] == 650000

    def test_accept_settles_coder_books(self, api, clerk_headers, manager_headers):
        """PRD §3.5: "The same event settles the coder's books: the coder's
        `workload_units` is credited back by the chart's acuity weight,
        `accepted_count` increases by one, `accepted_weighted_units` grows by
        the same acuity weight".

        Design: Difficulty/transitive_cascade/accept_cascades_chart_and_bill
        """
        ctx = setup_submitted_case(
            "MRN-TC2B", "E-TC2B",
            acuity="MEDICAL_LOW", credential="CCS",
            total_charges_cents=900000, financial_class="SELF_PAY",
        )
        get_success_data(api.create_bill({"account_id": ctx["account"]["id"]}, clerk_headers))
        validate_success(api.accept_assignment(ctx["assignment"]["id"], manager_headers), 200)
        coder = get_success_data(api.get_coder(ctx["coder"]["id"], manager_headers))
        assert coder["workload_units"] == 0
        assert coder["accepted_count"] == 1
        assert coder["accepted_weighted_units"] == 1


class TestBillPostPaymentRebillCycle:
    def test_rebill_cancel_returns_bill_to_paid(self, api, manager_headers):
        """PRD §3.9: "Cancelling instead moves the request to `CANCELLED`,
        returns the bill from `REBILL_REQUIRED` to `PAID`, and restores
        `net_receivable_cents` to `billed_amount_cents` minus
        `paid_amount_cents`".

        Design: Difficulty/non_linear_state_machine/bill_post_payment_rebill_cycle
        """
        ctx = setup_pending_rebill(
            "MRN-NL2", "E-NL2",
            credential="RHIA", acuity="MEDICAL_HIGH", total_charges_cents=2000000,
            dx_lines=_mcc_lines(), requested_by="clerk-nl2",
        )
        assert ctx["rebill"]["status"] == "PENDING"
        assert ctx["bill"]["status"] == "REBILL_REQUIRED"

        cancelled = validate_success(
            api.cancel_rebill_request(ctx["rebill"]["id"], make_officer_headers("officer-nl2")),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        bill = get_success_data(api.get_bill(ctx["bill"]["id"], manager_headers))
        assert bill["status"] == "PAID"
        assert bill["net_receivable_cents"] == 0

    def test_review_closes_as_rebill_on_rebill_create(self, api, manager_headers):
        """PRD §3.9: "A successful creation produces a `PENDING` rebill request
        with the clerk's `X-User-ID` recorded as `requested_by`, moves the
        review from `OPEN` to `CLOSED_REBILL`, moves the bill from
        `POST_PAYMENT_REVIEW` to `REBILL_REQUIRED`".

        Design: Difficulty/non_linear_state_machine/bill_post_payment_rebill_cycle
        """
        ctx = setup_pending_rebill(
            "MRN-NL2B", "E-NL2B",
            credential="RHIA", acuity="MEDICAL_HIGH", total_charges_cents=2000000,
            dx_lines=_mcc_lines(), requested_by="clerk-nl2b",
        )
        review = get_success_data(
            api.get_post_payment_review(ctx["review"]["id"], manager_headers)
        )
        assert review["status"] == "CLOSED_REBILL"
        assert ctx["rebill"]["requested_by"] == "clerk-nl2b"
        assert ctx["bill"]["status"] == "REBILL_REQUIRED"


class TestRebillCreateCancelConservesNetReceivable:
    def test_pending_rebill_does_not_drift_ledger(self, api, manager_headers):
        """PRD §3.9: "the invariant being that creating a rebill and then
        cancelling it leaves the bill's net receivable exactly as it was."
        While the rebill is PENDING the ledger still reads
        `billed_amount_cents` minus `paid_amount_cents`.

        Design: Difficulty/compensating_invariant/rebill_create_cancel_conserves_net_receivable
        """
        ctx = setup_pending_rebill(
            "MRN-CI1", "E-CI1",
            credential="RHIA", acuity="MEDICAL_HIGH", total_charges_cents=2000000,
            dx_lines=_mcc_lines(), requested_by="clerk-ci1",
        )
        assert ctx["bill"]["billed_amount_cents"] == MCC_EXPECTED
        assert ctx["bill"]["paid_amount_cents"] == MCC_EXPECTED
        assert ctx["bill"]["net_receivable_cents"] == 0

    def test_create_then_cancel_restores_net_receivable(self, api, manager_headers):
        """PRD §3.9: "Cancelling instead moves the request to `CANCELLED`,
        returns the bill from `REBILL_REQUIRED` to `PAID`, and restores
        `net_receivable_cents` to `billed_amount_cents` minus
        `paid_amount_cents` — the invariant being that creating a rebill and
        then cancelling it leaves the bill's net receivable exactly as it
        was."

        Design: Difficulty/compensating_invariant/rebill_create_cancel_conserves_net_receivable
        """
        ctx = setup_pending_rebill(
            "MRN-CI1B", "E-CI1B",
            credential="RHIA", acuity="MEDICAL_HIGH", total_charges_cents=2000000,
            dx_lines=_mcc_lines(), requested_by="clerk-ci1b",
        )
        cancelled = validate_success(
            api.cancel_rebill_request(ctx["rebill"]["id"], make_officer_headers("officer-ci1b")),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        bill = get_success_data(api.get_bill(ctx["bill"]["id"], manager_headers))
        assert bill["status"] == "PAID"
        assert bill["net_receivable_cents"] == 0


def test_record_payment_on_rebilled_bill_rejected(api, manager_headers, clerk_headers):
    """PRD §2.8: "This covers, for example, submitting from `RETURNED`,
    finalizing from `DRAFT`, resolving an already-`APPLIED` finding, or
    recording a payment on a `REBILLED` bill."

    Design: Corner/state_machines/record_payment_on_rebilled_bill_rejected
    """
    ctx = setup_pending_rebill(
        "MRN-SM3", "E-SM3",
        credential="RHIA", acuity="MEDICAL_HIGH", total_charges_cents=2000000,
        dx_lines=_mcc_lines(), requested_by="clerk-sm3",
    )
    approved = get_success_data(
        api.approve_rebill_request(ctx["rebill"]["id"], make_officer_headers("officer-sm3"))
    )
    assert approved["status"] == "APPROVED"
    bill = get_success_data(api.get_bill(ctx["bill"]["id"], clerk_headers))
    assert bill["status"] == "REBILLED"
    assert bill["net_receivable_cents"] == -200000

    res = api.record_payment(
        ctx["bill"]["id"],
        record_payment_payload(paid_amount_cents=100, paid_at="2026-05-02T00:00:00Z"),
        clerk_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_rebill_delta_mismatch_rejected(api, clerk_headers):
    """PRD §3.9: "a signed `delta_cents` that must equal the review's
    `claimed_delta_cents`, with any disagreement rejected as
    `ERR_REBILL_DELTA_MISMATCH`."

    Design: Corner/validations/rebill_delta_mismatch_rejected
    """
    ctx = setup_open_review(
        "MRN-VAI", "E-VAI",
        credential="RHIA", acuity="MEDICAL_HIGH", total_charges_cents=2000000,
        dx_lines=_mcc_lines(), claimed_delta_cents=-200000, payer_ref="PR-VAI",
    )
    res = api.create_rebill_request(
        create_rebill_request_payload(ctx["review"]["id"], -150000, ctx["bill_version"]),
        clerk_headers,
    )
    validate_error(res, ApiErrorId.ERR_REBILL_DELTA_MISMATCH, expected_status=422)


class TestTimelyFiling:
    def test_timely_filing_expired_rejected(self, api, clerk_headers, manager_headers):
        """PRD §3.9: "timely filing requires the logical clock to read no later
        than 120 days after the bill's `paid_at` — a request landing exactly
        on the 120-day deadline is permitted, anything later is
        `ERR_TIMELY_FILING_EXPIRED`."

        paid_at 2026-01-01 + 120 days = 2026-05-01; clock at 2026-05-02 is one
        day too late.

        Design: Corner/validations/timely_filing_expired_rejected
        """
        ctx = setup_open_review(
            "MRN-VAJ", "E-VAJ",
            credential="RHIA", acuity="MEDICAL_HIGH", total_charges_cents=2000000,
            dx_lines=_mcc_lines(),
            paid_at="2026-01-01T00:00:00Z",
            admit_at="2025-12-20T08:00:00Z",
            discharge_at="2025-12-28T10:00:00Z",
            due_at="2026-01-10T00:00:00Z",
            payer_ref="PR-VAJ",
        )
        get_success_data(
            api.set_clock({"to_iso8601": "2026-05-02T00:00:00Z"}, manager_headers)
        )
        res = api.create_rebill_request(
            create_rebill_request_payload(ctx["review"]["id"], -200000, ctx["bill_version"]),
            clerk_headers,
        )
        validate_error(res, ApiErrorId.ERR_TIMELY_FILING_EXPIRED, expected_status=422)

    def test_timely_filing_at_deadline_allowed(self, api, manager_headers):
        """PRD §3.9: "a request landing exactly on the 120-day deadline is
        permitted, anything later is `ERR_TIMELY_FILING_EXPIRED`."

        paid_at 2026-01-01; default clock 2026-05-01 is exactly the deadline.

        Design: Corner/validations/timely_filing_at_deadline_allowed
        """
        ctx = setup_open_review(
            "MRN-VAK", "E-VAK",
            credential="RHIA", acuity="MEDICAL_HIGH", total_charges_cents=2000000,
            dx_lines=_mcc_lines(),
            paid_at="2026-01-01T00:00:00Z",
            admit_at="2025-12-20T08:00:00Z",
            discharge_at="2025-12-28T10:00:00Z",
            due_at="2026-01-10T00:00:00Z",
            payer_ref="PR-VAK",
        )
        rebill = validate_success(
            api.create_rebill_request(
                create_rebill_request_payload(ctx["review"]["id"], -200000, ctx["bill_version"]),
                make_clerk_headers("clerk-vak"),
            ),
            201,
        )
        assert rebill["status"] == "PENDING"
        bill = get_success_data(api.get_bill(ctx["bill"]["id"], manager_headers))
        assert bill["status"] == "REBILL_REQUIRED"
        review = get_success_data(
            api.get_post_payment_review(ctx["review"]["id"], manager_headers)
        )
        assert review["status"] == "CLOSED_REBILL"


def test_rebill_approve_by_requester_rejected(api, manager_headers):
    """PRD §3.9: "an approver whose `X-User-ID` equals the request's
    `requested_by` is rejected with `ERR_SEGREGATION_OF_DUTIES`".

    Design: Corner/validations/rebill_approve_by_requester_rejected
    """
    ctx = setup_pending_rebill(
        "MRN-VAL", "E-VAL",
        credential="RHIA", acuity="MEDICAL_HIGH", total_charges_cents=2000000,
        dx_lines=_mcc_lines(), requested_by="clerk-sod",
    )
    res = api.approve_rebill_request(
        ctx["rebill"]["id"], make_officer_headers("clerk-sod")
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    rebill = get_success_data(api.get_rebill_request(ctx["rebill"]["id"], manager_headers))
    assert rebill["status"] == "PENDING"
    bill = get_success_data(api.get_bill(ctx["bill"]["id"], manager_headers))
    assert bill["status"] == "REBILL_REQUIRED"


class TestBillingNotFounds:
    def test_get_unknown_bill_not_found(self, api, clerk_headers):
        """PRD §2.8: "a referenced resource that does not exist yields its
        dedicated 404: ... `ERR_BILL_NOT_FOUND` for bills".

        Design: Corner/errors/get_unknown_bill_not_found
        """
        res = api.get_bill(NON_EXISTENT_UUID, clerk_headers)
        validate_error(res, ApiErrorId.ERR_BILL_NOT_FOUND, expected_status=404)

    def test_create_rebill_unknown_review_not_found(self, api, clerk_headers, manager_headers):
        """PRD §2.8: "a referenced resource that does not exist yields its
        dedicated 404: ... `ERR_REVIEW_NOT_FOUND` for post-payment reviews".

        Design: Corner/errors/create_rebill_unknown_review_not_found
        """
        account = get_success_data(
            api.create_patient_account(
                {
                    "mrn": "MRN-ER6",
                    "admit_at": "2026-04-20T08:00:00Z",
                    "patient_class": "INPATIENT",
                    "financial_class": "MEDICARE",
                    "total_charges_cents": 900000,
                },
                manager_headers,
            )
        )
        res = api.create_rebill_request(
            {
                "review_id": NON_EXISTENT_UUID,
                "delta_cents": -100,
                "expected_bill_version": account["version"],
            },
            clerk_headers,
        )
        validate_error(res, ApiErrorId.ERR_REVIEW_NOT_FOUND, expected_status=404)

    def test_approve_unknown_rebill_not_found(self, api):
        """PRD §2.8: "a referenced resource that does not exist yields its
        dedicated 404: ... `ERR_REBILL_NOT_FOUND` for rebill requests".

        Design: Corner/errors/approve_unknown_rebill_not_found
        """
        res = api.approve_rebill_request(
            NON_EXISTENT_UUID, make_officer_headers("officer-er7")
        )
        validate_error(res, ApiErrorId.ERR_REBILL_NOT_FOUND, expected_status=404)
