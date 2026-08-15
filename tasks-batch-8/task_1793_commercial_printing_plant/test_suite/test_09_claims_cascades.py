"""Reprint claims: provisional vs final credit, the approve cascade across
invoice -> job -> customer, the invoice monetary conservation invariant, and
claim lifecycle errors."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_claim_payload,
    create_customer,
    create_fulfilled_mail_job,
    create_fulfilled_ship_job,
    create_issued_invoice,
    create_received_stock,
    create_reviewed_claim,
    deny_claim_payload,
    file_claim,
    get_success_data,
    make_customer_headers,
    make_plant_manager_headers,
    minimal_signature,
    review_claim,
    standard_signatures,
    validate_error,
    validate_paginated,
    validate_success,
)

_PM = TEST_USERS["plant_manager_headers"]

# Standard MAIL drop profile used by the credit tests: three zip groups, each
# >= 150 pieces, so all 10502 pieces qualify at the five-digit rate (24c).
MAIL_ZIPS = [{"zip5": "90210", "pieces": 5200},
             {"zip5": "90401", "pieces": 5000},
             {"zip5": "10001", "pieces": 302}]
MAIL_POSTAGE_CENTS = 10502 * 24  # 252048
MAIL_INVOICE_BASE_CENTS = 811923
MAIL_TOTAL_DUE_CENTS = MAIL_INVOICE_BASE_CENTS + MAIL_POSTAGE_CENTS  # 1063971


def _create_invoice(job_id):
    resp = api_client.create_invoice({"job_id": job_id}, _PM)
    inv = get_success_data(resp)
    assert inv.get("id"), f"Setup failed: create invoice -> {resp.text}"
    return inv


def _fulfilled_mail_with_issued_invoice(limit=100000000):
    cust = create_customer(name="Mail Cust", credit_limit_cents=limit)
    stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=50000)
    _est, job, _drop, _press = create_fulfilled_mail_job(
        cust["id"], standard_signatures(stock["id"]), MAIL_ZIPS,
        quantity_ordered=10002, press_spoilage_pct=3, bindery_spoilage_pct=2,
        finishing_options=["PERF", "SCORE"], included_proof_rounds=2,
    )
    inv = _create_invoice(job["id"])
    inv = get_success_data(api_client.issue_invoice(inv["id"], _PM))
    assert inv["status"] == "ISSUED"
    return cust, job, inv


class TestProvisionalVsFinalCredit:
    def test_provisional_keys_off_base_final_keys_off_total(self, api):
        """PRD §3.14: "The provisional credit — stored as
        `provisional_credit_cents` — is the invoice's `base_amount_cents`
        multiplied by `liability_pct` hundredths, multiplied by the claim's
        `defect_qty`, and divided by the invoice's `delivered_quantity`,
        rounded half-up; it keys off the base amount only, excluding postage
        and proof overage. The final credit — stored as `final_credit_cents` —
        is computed identically except that it keys off the invoice's
        `total_due_cents` rather than `base_amount_cents`, and is capped at
        `total_due_cents`; whenever postage or proof overage is non-zero the
        final figure diverges from the provisional one."

        Invoice base 811923 + postage 252048 = total_due 1063971; defect 5251
        of 10502 at 100%: provisional 405962 vs final 531986.

        Design: Difficulty/dual_variant_calc/reprint_provisional_vs_final_credit
        """
        cust, job, inv = _fulfilled_mail_with_issued_invoice()
        assert inv["base_amount_cents"] == MAIL_INVOICE_BASE_CENTS
        assert inv["postage_cents"] == MAIL_POSTAGE_CENTS
        assert inv["total_due_cents"] == MAIL_TOTAL_DUE_CENTS
        claim = create_reviewed_claim(job["id"], cust["id"], 5251,
                                      claimed_defect="COLOR_SHIFT", reviewer_user_id="pm-1")
        resp = api.approve_reprint_claim(
            claim["id"], approve_claim_payload("CREDIT", 100),
            make_plant_manager_headers("pm-2"))
        data = validate_success(resp, 200)
        assert data["provisional_credit_cents"] == 405962
        assert data["final_credit_cents"] == 531986
        assert data["provisional_credit_cents"] != data["final_credit_cents"]

    def test_final_credit_applied_to_invoice(self, api):
        """PRD §3.14: "the amount applied to the invoice is the smaller of
        `final_credit_cents` and the invoice's `amount_outstanding_cents`;
        `credit_applied_cents` increases by the applied amount."

        Design: Difficulty/dual_variant_calc/reprint_provisional_vs_final_credit
        """
        cust, job, inv = _fulfilled_mail_with_issued_invoice()
        claim = create_reviewed_claim(job["id"], cust["id"], 5251,
                                      claimed_defect="COLOR_SHIFT", reviewer_user_id="pm-1")
        api.approve_reprint_claim(claim["id"], approve_claim_payload("CREDIT", 100),
                                  make_plant_manager_headers("pm-2"))
        inv_after = get_success_data(api.get_invoice(inv["id"], _PM))
        assert inv_after["credit_applied_cents"] == 531986
        assert inv_after["amount_outstanding_cents"] == 1063971 - 531986


class TestClaimCreditCascade:
    def _setup_hold_customer(self, api):
        cust = create_customer(name="Cascade Cust", credit_limit_cents=500000)
        stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=50000)
        _est, job, _drop, _press = create_fulfilled_mail_job(
            cust["id"], standard_signatures(stock["id"]), MAIL_ZIPS,
            quantity_ordered=10002, press_spoilage_pct=3, bindery_spoilage_pct=2,
            finishing_options=["PERF", "SCORE"], included_proof_rounds=2,
        )
        inv = _create_invoice(job["id"])
        api.issue_invoice(inv["id"], _PM)
        claim = create_reviewed_claim(job["id"], cust["id"], 10502,
                                      claimed_defect="MISREGISTER", reviewer_user_id="pm-1")
        return cust, job, inv, claim

    def test_precondition_credit_hold_then_invoice_paid(self, api):
        """PRD §3.14: "`credit_applied_cents` increases by the applied amount;
        if the invoice's outstanding reaches zero it moves to `PAID`." With
        final credit 1063971 == total_due, the invoice is fully covered.

        Design: Difficulty/transitive_cascade/claim_credit_to_invoice_job_customer_cascade
        """
        cust, job, inv, claim = self._setup_hold_customer(api)
        before = get_success_data(api.get_customer(cust["id"], _PM))
        assert before["posture"] == "CREDIT_HOLD", (
            f"exposure {before['exposure_cents']} must exceed limit 500000"
        )
        api.approve_reprint_claim(claim["id"], approve_claim_payload("CREDIT", 100),
                                  make_plant_manager_headers("pm-2"))
        inv_after = get_success_data(api.get_invoice(inv["id"], _PM))
        assert inv_after["credit_applied_cents"] == 1063971
        assert inv_after["status"] == "PAID"

    def test_cascade_closes_job_and_recomputes_posture(self, api):
        """PRD §3.14: "The `PAID` transition cascades as usual: the job's
        `billing_status` becomes `SETTLED`, a `FULFILLED` job closes to
        `CLOSED`, and the customer's exposure and posture are recomputed."

        Design: Difficulty/transitive_cascade/claim_credit_to_invoice_job_customer_cascade
        """
        cust, job, inv, claim = self._setup_hold_customer(api)
        api.approve_reprint_claim(claim["id"], approve_claim_payload("CREDIT", 100),
                                  make_plant_manager_headers("pm-2"))
        job_after = get_success_data(api.get_job(job["id"], _PM))
        cust_after = get_success_data(api.get_customer(cust["id"], _PM))
        assert job_after["billing_status"] == "SETTLED"
        assert job_after["production_status"] == "CLOSED"
        assert cust_after["exposure_cents"] == 0
        assert cust_after["posture"] == "ACTIVE"
        assert cust_after["reprint_credit_balance_cents"] == 0, (
            "no remainder: final credit equaled outstanding"
        )


class TestInvoiceMonetaryConservation:
    def _issued_ship_invoice(self):
        cust = create_customer(name="IC Cust")
        stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=50000)
        _est, job, inv, _press = create_issued_invoice(
            cust["id"], standard_signatures(stock["id"]),
            quantity_ordered=10002, delivered_quantity=10502,
            press_spoilage_pct=3, bindery_spoilage_pct=2,
            finishing_options=["PERF", "SCORE"], included_proof_rounds=2,
        )
        claim = create_reviewed_claim(job["id"], cust["id"], 10502,
                                      claimed_defect="TRIM_ERROR", reviewer_user_id="pm-1")
        return cust, job, inv, claim

    def test_payment_then_credit_then_payment_conserves_money(self, api):
        """PRD §3.12: "The `amount_outstanding_cents` is a monetary
        conservation invariant: `total_due_cents` minus `amount_paid_cents`
        minus `credit_applied_cents`." Across payment 300000 + credit 202981 +
        payment 308942: 608942 + 202981 + 0 == 811923.

        Design: Difficulty/compensating_invariant/invoice_monetary_conservation_across_payment_and_credit
        """
        cust, job, inv, claim = self._issued_ship_invoice()
        r = api.pay_invoice(inv["id"], {"amount_cents": 300000}, _PM)
        d = validate_success(r, 201)
        assert d["amount_paid_cents"] + d["credit_applied_cents"] + d["amount_outstanding_cents"] == 811923
        assert d["status"] == "PARTIALLY_PAID"
        api.approve_reprint_claim(claim["id"], approve_claim_payload("CREDIT", 25),
                                  make_plant_manager_headers("pm-2"))
        mid = get_success_data(api.get_invoice(inv["id"], _PM))
        assert mid["credit_applied_cents"] == 202981, (
            f"25% liability on full quantity: rhu(811923 x 0.25) = 202981, got {mid['credit_applied_cents']}"
        )
        assert mid["amount_paid_cents"] + mid["credit_applied_cents"] + mid["amount_outstanding_cents"] == 811923

    def test_final_payment_pays_invoice_and_closes_job(self, api):
        """PRD §3.12 conservation plus PRD §3.13: "A payment covering the
        exact outstanding amount moves the invoice to `PAID`, which cascades:
        the job's `billing_status` becomes `SETTLED`, and if the job's
        `production_status` is `FULFILLED`, the job closes to `CLOSED`."

        Design: Difficulty/compensating_invariant/invoice_monetary_conservation_across_payment_and_credit
        """
        cust, job, inv, claim = self._issued_ship_invoice()
        api.pay_invoice(inv["id"], {"amount_cents": 300000}, _PM)
        api.approve_reprint_claim(claim["id"], approve_claim_payload("CREDIT", 25),
                                  make_plant_manager_headers("pm-2"))
        r = api.pay_invoice(inv["id"], {"amount_cents": 308942}, _PM)
        d = validate_success(r, 201)
        assert d["status"] == "PAID"
        assert d["amount_paid_cents"] == 608942
        assert d["credit_applied_cents"] == 202981
        assert d["amount_outstanding_cents"] == 0
        job_after = get_success_data(api.get_job(job["id"], _PM))
        assert job_after["billing_status"] == "SETTLED"
        assert job_after["production_status"] == "CLOSED"


class TestReprintChildJob:
    def test_reprint_resolution_creates_child_job(self, api):
        """PRD §3.14: "Approval with resolution `REPRINT` creates a reprint
        job: `parent_job_id` set to the original job's `id`, `estimate_id`
        null, `quantity_ordered` set to the claim's `defect_qty`,
        `zero_charge` true (such jobs are never invoiced), `billing_status`
        `NOT_BILLABLE`, `production_status` `PREPRESS`..."

        Design: Corner/entities/reprint_resolution_creates_child_job
        """
        cust = create_customer(name="RP Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        _est, job, _press = create_fulfilled_ship_job(
            cust["id"], minimal_signature(stock["id"]),
            quantity_ordered=1000, delivered_quantity=1000,
        )
        claim = create_reviewed_claim(job["id"], cust["id"], 250,
                                      claimed_defect="BINDING_DEFECT", reviewer_user_id="pm-1")
        resp = api.approve_reprint_claim(claim["id"], approve_claim_payload("REPRINT", 100),
                                         make_plant_manager_headers("pm-2"))
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED"
        assert data["resolution"] == "REPRINT"
        assert data["reprint_job_id"], "reprint_job_id must be set"
        rjob = get_success_data(api.get_job(data["reprint_job_id"], _PM))
        assert rjob["parent_job_id"] == job["id"]
        assert rjob["quantity_ordered"] == 250
        assert rjob["zero_charge"] is True
        assert rjob["billing_status"] == "NOT_BILLABLE"
        assert rjob["production_status"] == "PREPRESS"
        rows, meta = validate_paginated(api.list_jobs(_PM, params={"parent_job_id": job["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == rjob["id"]


class TestClaimLifecycleErrors:
    def _fulfilled(self):
        cust = create_customer(name="CB Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        _est, job, _press = create_fulfilled_ship_job(
            cust["id"], minimal_signature(stock["id"]),
            quantity_ordered=1000, delivered_quantity=1000,
        )
        return cust, job

    def test_defect_qty_above_delivered_rejected(self, api):
        """PRD §3.14: "The defect quantity must be at least 1 and at most the
        job's `delivered_quantity`; out-of-range values are rejected with
        `ERR_DEFECT_QTY_INVALID` (HTTP 422)."

        Design: Corner/errors/claim_lifecycle_error_battery
        """
        cust, job = self._fulfilled()
        resp = api.create_reprint_claim(
            {"job_id": job["id"], "claimed_defect": "SHORTAGE", "defect_qty": 1001},
            make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_DEFECT_QTY_INVALID)

    def test_second_open_claim_rejected(self, api):
        """PRD §3.14: "Only one open claim may exist per job — filing while
        another claim for the same job is in `FILED` or `UNDER_REVIEW` is
        rejected with `ERR_CLAIM_ALREADY_OPEN`."

        Design: Corner/errors/claim_lifecycle_error_battery
        """
        cust, job = self._fulfilled()
        file_claim(job["id"], cust["id"], 100, claimed_defect="SHORTAGE")
        resp = api.create_reprint_claim(
            {"job_id": job["id"], "claimed_defect": "TRIM_ERROR", "defect_qty": 5},
            make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_OPEN)

    def test_double_review_rejected(self, api):
        """PRD §3.14: "Claim operations attempted from a state that does not
        support them — approving a claim still in `FILED`, reviewing a claim
        already `UNDER_REVIEW` — are rejected with `ERR_CLAIM_STATE`."

        Design: Corner/errors/claim_lifecycle_error_battery
        """
        cust, job = self._fulfilled()
        claim = create_reviewed_claim(job["id"], cust["id"], 100, reviewer_user_id="pm-1")
        resp = api.review_reprint_claim(claim["id"], make_plant_manager_headers("pm-9"))
        validate_error(resp, ApiErrorId.ERR_CLAIM_STATE)

    def test_approve_by_reviewer_rejected_segregation(self, api):
        """PRD §2.1: "any subsequent approve or deny attempt carrying that
        same `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP
        403)."

        Design: Corner/errors/claim_lifecycle_error_battery
        """
        cust, job = self._fulfilled()
        claim = create_reviewed_claim(job["id"], cust["id"], 100, reviewer_user_id="pm-1")
        resp = api.approve_reprint_claim(claim["id"], approve_claim_payload("REPRINT", 100),
                                         make_plant_manager_headers("pm-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_deny_by_reviewer_rejected_then_other_pm_denies(self, api):
        """PRD §2.1: "A different `PlantManager` principal must complete the
        adjudication"; PRD §3.14: "Denial moves the claim from `UNDER_REVIEW`
        to the terminal `DENIED` state."

        Design: Corner/errors/claim_lifecycle_error_battery
        """
        cust, job = self._fulfilled()
        claim = create_reviewed_claim(job["id"], cust["id"], 100, reviewer_user_id="pm-1")
        r1 = api.deny_reprint_claim(claim["id"], deny_claim_payload(),
                                    make_plant_manager_headers("pm-1"))
        validate_error(r1, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        r2 = api.deny_reprint_claim(claim["id"], deny_claim_payload(),
                                    make_plant_manager_headers("pm-2"))
        data = validate_success(r2, 200)
        assert data["status"] == "DENIED"
        after = get_success_data(api.get_reprint_claim(claim["id"], _PM))
        assert after["reviewed_by"] == "pm-1"

    def test_approve_after_denied_rejected(self, api):
        """PRD §3.14: DENIED is terminal — "Claim operations attempted from a
        state that does not support them... are rejected with
        `ERR_CLAIM_STATE`."

        Design: Corner/errors/claim_lifecycle_error_battery
        """
        cust, job = self._fulfilled()
        claim = create_reviewed_claim(job["id"], cust["id"], 100, reviewer_user_id="pm-1")
        api.deny_reprint_claim(claim["id"], deny_claim_payload(),
                               make_plant_manager_headers("pm-2"))
        resp = api.approve_reprint_claim(claim["id"], approve_claim_payload("REPRINT", 100),
                                         make_plant_manager_headers("pm-2"))
        validate_error(resp, ApiErrorId.ERR_CLAIM_STATE)


class TestClaimApproveBeforeReview:
    def test_claim_approve_before_review_rejected(self, api):
        """PRD §3.14: "Claim operations attempted from a state that does not
        support them — approving a claim still in `FILED`, reviewing a claim
        already `UNDER_REVIEW` — are rejected with `ERR_CLAIM_STATE`."

        Design: Corner/state_machines/claim_approve_before_review_rejected
        """
        cust = create_customer(name="CL Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        _est, job, _press = create_fulfilled_ship_job(
            cust["id"], minimal_signature(stock["id"]),
            quantity_ordered=1000, delivered_quantity=1000,
        )
        claim = file_claim(job["id"], cust["id"], 10, claimed_defect="SHORTAGE")
        resp = api.approve_reprint_claim(claim["id"], approve_claim_payload("REPRINT", 100),
                                         make_plant_manager_headers("pm-1"))
        validate_error(resp, ApiErrorId.ERR_CLAIM_STATE)
        after = get_success_data(api.get_reprint_claim(claim["id"], _PM))
        assert after["status"] == "FILED"


class TestClaimCreditWithoutOpenInvoice:
    def test_claim_credit_without_open_invoice_rejected(self, api):
        """PRD §3.14: "Approval with resolution `CREDIT` first requires that
        the job's production invoice exist with status `ISSUED`,
        `PARTIALLY_PAID`, or `DISPUTED` and an `amount_outstanding_cents`
        strictly greater than zero; if none exists, the approval is rejected
        with `ERR_CLAIM_NO_OPEN_INVOICE`."

        Design: Corner/errors/claim_credit_without_open_invoice_rejected
        """
        cust = create_customer(name="CN Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        _est, job, inv, _press = create_issued_invoice(
            cust["id"], minimal_signature(stock["id"]),
            quantity_ordered=1000, delivered_quantity=1000,
        )
        api.pay_invoice(inv["id"], {"amount_cents": 85000}, _PM)  # job CLOSED
        claim = create_reviewed_claim(job["id"], cust["id"], 100,
                                      claimed_defect="COLOR_SHIFT", reviewer_user_id="pm-1")
        resp = api.approve_reprint_claim(claim["id"], approve_claim_payload("CREDIT", 50),
                                         make_plant_manager_headers("pm-2"))
        validate_error(resp, ApiErrorId.ERR_CLAIM_NO_OPEN_INVOICE)
        after = get_success_data(api.get_reprint_claim(claim["id"], _PM))
        assert after["status"] == "UNDER_REVIEW"
