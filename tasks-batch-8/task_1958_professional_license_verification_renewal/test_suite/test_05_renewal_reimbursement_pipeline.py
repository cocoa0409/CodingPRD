"""Renewal reimbursement: estimates, the review diamond, caps, SoD, and OCC."""
from test_helpers import (
    ApiErrorId,
    approve_renewal_request,
    create_active_license,
    create_employee,
    create_license_type,
    create_pe_license_type,
    create_renewal_request,
    create_submitted_request,
    get_success_data,
    make_employee_headers,
    make_officer_headers,
    submit_renewal_request,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
HR = TEST_USERS["hr_headers"]

OFFICER1 = make_officer_headers("officer-1")
OFFICER2 = make_officer_headers("officer-2")


def _active_rn(email, license_number=None):
    lt = create_license_type()
    emp = create_employee(work_email=email)
    lic = create_active_license(emp["id"], lt["id"], license_number=license_number)
    return lt, emp, lic


class TestEstimateVariants:
    def test_receipt_based_estimate_tiered_math(self, api):
        """PRD §3.6: "Under `RECEIPT_BASED`, the claim is reimbursed in marginal
        bands: the band up to `reimburse_full_up_to_cents` counts in full, the
        band above it up to `reimburse_half_up_to_cents` counts at half its
        value"; "the estimate is then the smaller of the claim and that tiered
        total."

        Design: Difficulty/dual_variant_calc/reimbursement_estimate_receipt_vs_flat
        """
        lt, emp, lic_rn = _active_rn("eric@example.com", license_number="RN-4001")
        # 500000 claim: 200000 full + 0.5 * (500000 - 200000) = 350000.
        rr = create_renewal_request(lic_rn["id"], 500_000)
        assert rr["estimated_reimbursable_cents"] == 350_000

    def test_flat_schedule_estimate_differs_on_identical_claim(self, api):
        """PRD §3.6: "Under `FLAT_SCHEDULE`, the estimate is simply the smaller
        of `flat_schedule_amount_cents` and the claim, so the same receipt yields
        a different estimate under the two modes."

        Design: Difficulty/dual_variant_calc/reimbursement_estimate_receipt_vs_flat
        """
        lt_pe = create_pe_license_type()
        emp = create_employee(full_name="Eric Engineer",
                              work_email="eric.flat@example.com",
                              role_code="FIELD_ENGINEER")
        lic_pe = create_active_license(emp["id"], lt_pe["id"],
                                       license_number="PE-4001",
                                       source="MANUAL_UPLOAD")
        rr = create_renewal_request(lic_pe["id"], 500_000)
        # min(flat 100000, claim 500000) = 100000, vs 350000 under receipt mode.
        assert rr["estimated_reimbursable_cents"] == 100_000


class TestTieredEstimateWithPaidCapWaterfall:
    def _run_pipeline_to_cap(self, api, email):
        """Four claims against the same ACTIVE license, walking each to PAID.

        Returns (employee, list of (request, approved_amount)) tuples.
        """
        lt, emp, lic = _active_rn(email, license_number="RN-5001")
        results = []
        for claimed in (400_000, 500_000, 500_000):
            rr = create_submitted_request(lic["id"], claimed,
                                          submitter_headers=OFFICER1)
            approved = approve_renewal_request(rr["id"], OFFICER2)
            paid = get_success_data(api.mark_paid_renewal_request(
                approved["id"], f"PAY-{len(results) + 1}", HR), 200)
            results.append((paid, paid["approved_amount_cents"]))
        return emp, lic, results

    def test_approval_amounts_walk_the_paid_cap_waterfall(self, api):
        """PRD §3.6: "Approval fixes `approved_amount_cents` at the smaller of
        `estimated_reimbursable_cents` and the remaining paid-cap headroom — the
        employer's one-million-cent paid ceiling minus the employee's lifetime
        `reimbursement_paid_cents`".

        Design: Difficulty/combinatorial_formula/reimbursement_tiered_estimate_with_paid_cap_waterfall
        """
        emp, lic, results = self._run_pipeline_to_cap(api, "nora.tier@example.com")
        # est(400000) = min(400000, 200000 + 0.5*200000) = 300000.
        assert results[0][1] == 300_000
        # est(500000) = 350000; remainder 700000.
        assert results[1][1] == 350_000
        # est 350000; remainder 350000 — exact cap landing.
        assert results[2][1] == 350_000

    def test_fourth_request_approves_at_zero_when_cap_exhausted(self, api):
        """PRD §3.6: "whatever overflows the paid cap is dropped outright, not
        deferred to a later cycle."

        Design: Difficulty/combinatorial_formula/reimbursement_tiered_estimate_with_paid_cap_waterfall
        """
        emp, lic, results = self._run_pipeline_to_cap(api, "nora.tier4@example.com")
        rr4 = create_submitted_request(lic["id"], 500_000,
                                       submitter_headers=OFFICER1)
        assert rr4["estimated_reimbursable_cents"] == 350_000
        approved = approve_renewal_request(rr4["id"], OFFICER2)
        assert approved["approved_amount_cents"] == 0

        emp_after = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert emp_after["reimbursement_paid_cents"] == 1_000_000
        assert emp_after["reimbursement_committed_cents"] == 0


class TestRenewalRequestDiamond:
    def test_info_loop_states_and_committed_balance(self, api):
        """PRD §3.6: "Submitting moves a request from `DRAFT` to `SUBMITTED`, or
        resubmits it from `MORE_INFO` back to `SUBMITTED`"; "An officer needing
        clarification sends the request back to `MORE_INFO` with an `info_note`,
        leaving the committed counter unchanged."

        Design: Difficulty/non_linear_state_machine/renewal_request_diamond_with_info_loop
        """
        lt, emp, lic = _active_rn("nora.diamond@example.com",
                                  license_number="RN-7001")
        emp_headers = make_employee_headers(emp["id"])
        rr = create_renewal_request(lic["id"], 300_000, headers=emp_headers)
        assert rr["estimated_reimbursable_cents"] == 250_000

        s1 = submit_renewal_request(rr["id"], headers=emp_headers)
        assert s1["status"] == "SUBMITTED"
        assert get_success_data(api.get_employee(
            emp["id"], OFFICER))["reimbursement_committed_cents"] == 300_000

        s2 = validate_success(api.request_info_renewal_request(
            rr["id"], "Attach receipt page 2", OFFICER1), 200)
        assert s2["status"] == "MORE_INFO"
        assert get_success_data(api.get_employee(
            emp["id"], OFFICER))["reimbursement_committed_cents"] == 300_000

        s3 = submit_renewal_request(rr["id"], headers=emp_headers)
        assert s3["status"] == "SUBMITTED"

    def test_diamond_closes_approve_then_paid(self, api):
        """PRD §3.6: "Approval fixes `approved_amount_cents` at the smaller of
        `estimated_reimbursable_cents` and the remaining paid-cap headroom";
        "Marking an `APPROVED` request paid moves it to `PAID`, sets `paid_on` —
        which stays null until this moment — to the logical current date,
        records `paid_by_user_id` and the `payment_ref`, moves the approved
        amount out of the committed counter, and adds it to
        `reimbursement_paid_cents`."

        Design: Difficulty/non_linear_state_machine/renewal_request_diamond_with_info_loop
        """
        lt, emp, lic = _active_rn("nora.diamond2@example.com",
                                  license_number="RN-7002")
        rr = create_submitted_request(lic["id"], 300_000,
                                      submitter_headers=make_employee_headers(emp["id"]))
        approved = approve_renewal_request(rr["id"], OFFICER1)
        assert approved["status"] == "APPROVED"
        assert approved["approved_amount_cents"] == 250_000

        paid = validate_success(api.mark_paid_renewal_request(
            rr["id"], "PAY-D", HR), 200)
        assert paid["status"] == "PAID"

        emp_after = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert emp_after["reimbursement_committed_cents"] == 0
        assert emp_after["reimbursement_paid_cents"] == 250_000


class TestCompensatingInvariant:
    def test_void_releases_submitted_commitment_exactly(self, api):
        """PRD §3.6: "voiding is permitted from `DRAFT`, `SUBMITTED`, `MORE_INFO`,
        or `APPROVED` — anything else fails with `ERR_INVALID_STATE` — records a
        `void_reason`, and releases exactly what the request was still
        committing: nothing from a `DRAFT`, the full claim from `SUBMITTED` or
        `MORE_INFO`, and the approved amount from `APPROVED`."

        Design: Difficulty/compensating_invariant/committed_balance_round_trips_through_void_and_reject
        """
        lt, emp, lic = _active_rn("nora.inv@example.com", license_number="RN-8401")
        rr1 = create_submitted_request(lic["id"], 300_000, submitter_headers=OFFICER1)
        assert get_success_data(api.get_employee(
            emp["id"], OFFICER))["reimbursement_committed_cents"] == 300_000

        voided = validate_success(api.void_renewal_request(
            rr1["id"], "Duplicate entry", ADMIN), 200)
        assert voided["status"] == "VOIDED"
        assert get_success_data(api.get_employee(
            emp["id"], OFFICER))["reimbursement_committed_cents"] == 0

    def test_reject_releases_submitted_commitment_exactly(self, api):
        """PRD §3.6: "Rejection records the `decision_note`, moves the request to
        `REJECTED`, and releases the entire claim from the committed counter."

        Design: Difficulty/compensating_invariant/committed_balance_round_trips_through_void_and_reject
        """
        lt, emp, lic = _active_rn("nora.inv2@example.com", license_number="RN-8402")
        rr2 = create_submitted_request(lic["id"], 100_000, submitter_headers=OFFICER1)
        rejected = validate_success(api.reject_renewal_request(
            rr2["id"], "Insufficient documentation", OFFICER2), 200)
        assert rejected["status"] == "REJECTED"
        assert get_success_data(api.get_employee(
            emp["id"], OFFICER))["reimbursement_committed_cents"] == 0


class TestRenewalValidations:
    def test_mark_paid_on_draft_rejected(self, api):
        """PRD §3.6: "Marking an `APPROVED` request paid moves it to `PAID`, sets
        `paid_on` — which stays null until this moment — to the logical current
        date"; a `DRAFT` request is not in `APPROVED`, the only from-state, so
        the attempt fails the §2.8 state-machine from-state check
        (`ERR_INVALID_STATE`).

        Design: Corner/state_machines/mark_paid_on_draft_rejected
        """
        lt, emp, lic = _active_rn("nora.mp@example.com", license_number="RN-9109")
        rr = create_renewal_request(lic["id"], 50_000)
        resp = api.mark_paid_renewal_request(rr["id"], "PAY-X", HR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_sod_approver_is_submitter_rejected(self, api):
        """PRD §3.6: "whoever submitted a request may not decide it, and a
        deciding officer whose `X-User-ID` equals `submitted_by_user_id` is
        turned away with `ERR_SOD_SAME_USER`."

        Design: Corner/validations/sod_approver_is_submitter_rejected
        """
        lt, emp, lic = _active_rn("nora.sod@example.com", license_number="RN-9301")
        rr = create_submitted_request(lic["id"], 50_000, submitter_headers=OFFICER1)
        resp = api.approve_renewal_request(rr["id"], OFFICER1)
        validate_error(resp, ApiErrorId.ERR_SOD_SAME_USER, 403)

    def test_claim_over_hard_cap_rejected(self, api):
        """PRD §3.6: "it may not exceed the license type's
        `hard_claim_cap_cents`; a claim above that absolute ceiling is rejected
        outright with `ERR_CLAIM_EXCEEDS_HARD_CAP`."

        Design: Corner/validations/claim_over_hard_cap_rejected
        """
        lt, emp, lic = _active_rn("nora.cap@example.com", license_number="RN-9307")
        version = get_success_data(api.get_license(lic["id"], OFFICER))["version"]
        resp = api.create_renewal_request(lic["id"], {
            "claimed_amount_cents": 500_001,
            "expected_license_version": version,
        }, OFFICER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_EXCEEDS_HARD_CAP, 422)

    def test_committed_cap_exact_landing_then_exceeded(self, api):
        """PRD §3.6: "the employer caps each employee's open commitment at one
        million cents — ten thousand dollars — so a first submission whose claim
        would push `reimbursement_committed_cents` over that ceiling fails with
        `ERR_COMMITTED_CAP_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/committed_cap_boundary_exact_then_exceeded
        """
        lt_rn = create_license_type()
        lt_pe = create_pe_license_type()
        emp = create_employee(work_email="nora.comcap@example.com")
        lic1 = create_active_license(emp["id"], lt_rn["id"], license_number="RN-9308")
        lic2 = create_active_license(emp["id"], lt_pe["id"], license_number="PE-9309",
                                     source="MANUAL_UPLOAD")
        lic3 = create_active_license(emp["id"], lt_rn["id"], state_code="TX",
                                     license_number="RN-9310", source="NURSYS")

        create_submitted_request(lic1["id"], 500_000, submitter_headers=OFFICER1)
        create_submitted_request(lic2["id"], 500_000, submitter_headers=OFFICER1)
        assert get_success_data(api.get_employee(
            emp["id"], OFFICER))["reimbursement_committed_cents"] == 1_000_000

        rr3 = create_renewal_request(lic3["id"], 1)
        resp = api.submit_renewal_request(rr3["id"], OFFICER1)
        validate_error(resp, ApiErrorId.ERR_COMMITTED_CAP_EXCEEDED, 402)
        assert get_success_data(api.get_employee(
            emp["id"], OFFICER))["reimbursement_committed_cents"] == 1_000_000


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_second_create_rejected(self, api):
        """PRD §2.7: "That request body must carry `expected_license_version`, a
        non-optional field holding the `version` of the parent license as the
        client last observed it."
        PRD §2.7: "the supplied value no longer matches the license's current
        `version`, and the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity/occ_stale_version_on_second_create_rejected
        """
        lt, emp, lic = _active_rn("nora.occ@example.com", license_number="RN-9601")
        lic_v = get_success_data(api.get_license(lic["id"], OFFICER))["version"]

        rr1 = validate_success(api.create_renewal_request(lic["id"], {
            "claimed_amount_cents": 50_000, "expected_license_version": lic_v,
        }, OFFICER), 201)
        assert rr1["status"] == "DRAFT"

        resp = api.create_renewal_request(lic["id"], {
            "claimed_amount_cents": 60_000, "expected_license_version": lic_v,
        }, OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_occ_second_create_succeeds_with_fresh_version(self, api):
        """PRD §2.7: "That request body must carry `expected_license_version`, a
        non-optional field holding the `version` of the parent license as the
        client last observed it."
        PRD §3.6: "because the license now carries a dependent draft — increments
        the license's `version` by one."

        Design: Corner/cross_cutting_complexity/occ_stale_version_on_second_create_rejected
        """
        lt, emp, lic = _active_rn("nora.occ2@example.com", license_number="RN-9601b")
        lic_v = get_success_data(api.get_license(lic["id"], OFFICER))["version"]
        validate_success(api.create_renewal_request(lic["id"], {
            "claimed_amount_cents": 50_000, "expected_license_version": lic_v,
        }, OFFICER), 201)
        # Renewal creation bumped the license version by exactly one.
        fresh = get_success_data(api.get_license(lic["id"], OFFICER))
        assert fresh["version"] == lic_v + 1
        rr2 = validate_success(api.create_renewal_request(lic["id"], {
            "claimed_amount_cents": 60_000,
            "expected_license_version": fresh["version"],
        }, OFFICER), 201)
        assert rr2["status"] == "DRAFT"


class TestCrossEntityStateDependency:
    def test_renewal_submit_gated_by_license_revocation(self, api):
        """PRD §3.6: "a license outside `ACTIVE`, `EXPIRED`, or `LAPSED` fails
        with `ERR_LICENSE_NOT_RENEWABLE`."
        PRD §3.7: "a `REVOCATION` moves a license in `ACTIVE` or `SUSPENDED` to
        `REVOKED`, which is terminal".

        Design: Difficulty/cross_entity_state_dependency/renewal_submit_gated_by_license_revocation
        """
        from test_helpers import create_disciplinary_event, confirm_disciplinary_event
        lt, emp, lic = _active_rn("nora.xentity@example.com",
                                  license_number="RN-8301")
        rr = create_renewal_request(lic["id"], 50_000)
        event = create_disciplinary_event(
            lic["id"], headers=OFFICER1, board_case_number="B-17",
            event_type="REVOCATION", effective_on="2026-08-01")
        confirm_disciplinary_event(event["id"], headers=OFFICER2)

        resp = api.submit_renewal_request(rr["id"], OFFICER1)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_RENEWABLE, 409)

    def test_renewal_submit_on_revoked_still_rejected_for_other_claims(self, api):
        """PRD §3.6: "Two license-state gates then apply in this order: a
        `SUSPENDED` license blocks submission with `ERR_LICENSE_SUSPENDED`, and
        a license outside `ACTIVE`, `EXPIRED`, or `LAPSED` fails with
        `ERR_LICENSE_NOT_RENEWABLE`."

        Design: Difficulty/cross_entity_state_dependency/renewal_submit_gated_by_license_revocation
        """
        from test_helpers import create_disciplinary_event, confirm_disciplinary_event
        lt, emp, lic = _active_rn("nora.xentity2@example.com",
                                  license_number="RN-8301b")
        rr = create_renewal_request(lic["id"], 75_000)
        event = create_disciplinary_event(
            lic["id"], headers=OFFICER1, board_case_number="B-18",
            event_type="REVOCATION", effective_on="2026-08-01")
        confirm_disciplinary_event(event["id"], headers=OFFICER2)
        assert get_success_data(api.get_license(lic["id"], OFFICER))["status"] == "REVOKED"

        # Even the license-owning Employee actor cannot submit a revoked license.
        resp = api.submit_renewal_request(rr["id"], make_employee_headers(emp["id"]))
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_RENEWABLE, 409)
