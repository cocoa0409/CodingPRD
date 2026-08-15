"""Fee waivers: programs, applications, stacking waterfall, SoD and OCC guards."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    create_waiver_program_payload, create_offering_payload,
    create_fee_catalog_item_payload,
    setup_open_year, setup_year_with_fee, add_student_with_account,
    setup_approved_waiver_account, create_program,
    submit_and_approve_application, pay_and_settle, current_account_version,
    make_bookkeeper_headers, make_family_headers,
)


class TestWaiverReviewGuards:
    def test_waiver_self_approval_rejected(self):
        """PRD §2.10: "The reviewer's X-User-ID must differ from the application's
        submitted_by_user_id — otherwise `ERR_WAIVER_SELF_APPROVAL` (HTTP 403)."

        Design: Corner/validations/waiver_self_approval_rejected
        """
        env = setup_open_year()
        student, account = add_student_with_account(env["year"]["id"])
        program = get_success_data(api_client.create_waiver_program(
            env["year"]["id"], create_waiver_program_payload(), make_bookkeeper_headers("bk-9")))
        app = get_success_data(api_client.create_waiver_application(
            account["id"], {"waiver_program_id": program["id"]},
            make_family_headers("user-42")))
        a_v = current_account_version(account["id"])
        resp = api_client.approve_waiver_application(
            account["id"], app["id"], {"expected_account_version": a_v},
            make_bookkeeper_headers("user-42"))
        validate_error(resp, ApiErrorId.ERR_WAIVER_SELF_APPROVAL)
        app_now = get_success_data(api_client.get_waiver_application(
            account["id"], app["id"], make_bookkeeper_headers("bk-9")))
        assert app_now["status"] == "PENDING"

    def test_waiver_ineligible_grade_rejected(self):
        """PRD §2.10: "The program must be ACTIVE and the student's grade within
        the program's inclusive eligibility band — otherwise
        `ERR_WAIVER_INELIGIBLE` (HTTP 422)."

        Design: Corner/validations/waiver_ineligible_grade_rejected
        """
        env = setup_open_year()
        student, account = add_student_with_account(env["year"]["id"], grade_level=10)
        program = get_success_data(api_client.create_waiver_program(
            env["year"]["id"],
            create_waiver_program_payload(waiver_pct_bp=10000,
                                          eligibility_grade_min=11,
                                          eligibility_grade_max=12),
            make_bookkeeper_headers()))
        app = get_success_data(api_client.create_waiver_application(
            account["id"], {"waiver_program_id": program["id"]}, make_family_headers("fam-1")))
        a_v = current_account_version(account["id"])
        resp = api_client.approve_waiver_application(
            account["id"], app["id"], {"expected_account_version": a_v},
            make_bookkeeper_headers("bk-1"))
        validate_error(resp, ApiErrorId.ERR_WAIVER_INELIGIBLE)

    def test_waiver_program_suspended_blocks_approval(self):
        """PRD §3.4: "Approval requires the program to be `ACTIVE` — approving
        against a `SUSPENDED` program fails with `ERR_WAIVER_PROGRAM_SUSPENDED`
        (HTTP 409)"
        PRD §3.4: "suspending moves one to `SUSPENDED`, which blocks new approvals
        while leaving existing approvals in force."

        Design: Corner/validations/waiver_program_suspended_blocks_approval
        """
        env = setup_open_year()
        student, account = add_student_with_account(env["year"]["id"])
        bk = make_bookkeeper_headers()
        program = get_success_data(api_client.create_waiver_program(
            env["year"]["id"], create_waiver_program_payload(), bk))
        app = get_success_data(api_client.create_waiver_application(
            account["id"], {"waiver_program_id": program["id"]}, make_family_headers("fam-1")))
        suspended = get_success_data(api_client.suspend_waiver_program(
            env["year"]["id"], program["id"], bk))
        assert suspended["status"] == "SUSPENDED"
        a_v = current_account_version(account["id"])
        resp = api_client.approve_waiver_application(
            account["id"], app["id"], {"expected_account_version": a_v},
            make_bookkeeper_headers("bk-1"))
        validate_error(resp, ApiErrorId.ERR_WAIVER_PROGRAM_SUSPENDED)


class TestWaiverStacking:
    def test_waiver_stacking_provisional_vs_final_diverge(self):
        """PRD §3.4: "On assessment creation the stacking is **provisional**:
        because allocated_cents is zero at creation, the waiver computes against
        the full assessed_amount_cents, and if a payment settles before the next
        approval or revocation, the provisional base can differ from the
        post-payment base until that final recomputation."
        PRD §3.4: "On approval or revocation the stacking is **final**: every
        program's contribution is recomputed from scratch against current unpaid
        remainders, and differences land as deltas on each assessment's
        waived_amount_cents."
        PRD §3.4: "For each visited assessment, the base is the unpaid remainder:
        assessed_amount_cents minus allocated_cents."

        Design: Difficulty/dual_variant_calc/waiver_stacking_provisional_vs_final_diverge
        """
        bk = make_bookkeeper_headers("bk-1")
        env = setup_year_with_fee(fee_amount=10000, with_offering=True,
                                  year_overrides={"payment_plan_min_cents": 5000})
        student, account = add_student_with_account(env["year"]["id"], grade_level=10)
        program = create_program(env, waiver_pct_bp=5000, stacking_priority=1,
                                 max_waived_per_student_cents=10000000)
        # Approve the application BEFORE any assessment exists
        submit_and_approve_application(account["id"], program["id"],
                                       submitter_user_id="fam-1",
                                       reviewer_user_id="bk-1")
        # Enrollment auto-creates the assessment; provisional stacking computes
        # against the full 10000 (allocated_cents == 0)
        get_success_data(api_client.create_enrollment(
            account["id"], {"offering_id": env["offering"]["id"]}, bk))
        fa = get_success_data(api_client.list_fee_assessments(account["id"], bk))[0]
        assert fa["waived_amount_cents"] == 5000, (
            f"Provisional waiver must be floor(10000*5000/10000)=5000; got {fa['waived_amount_cents']}")
        # Settle 2000, then a second approval recomputes the final base
        pay_and_settle(account["id"], 2000, idempotency_key="k1")
        app2 = get_success_data(api_client.create_waiver_application(
            account["id"], {"waiver_program_id": program["id"]},
            make_family_headers("fam-1")))
        a_v = current_account_version(account["id"])
        get_success_data(api_client.approve_waiver_application(
            account["id"], app2["id"], {"expected_account_version": a_v}, bk))
        fa = get_success_data(api_client.list_fee_assessments(account["id"], bk))[0]
        assert fa["waived_amount_cents"] == 4000, (
            f"Final restack on the unpaid remainder: floor(8000*0.5)=4000; got {fa['waived_amount_cents']}")
        assert fa["outstanding_cents"] == 4000, (
            f"10000 - 4000 waived - 2000 paid = 4000; got {fa['outstanding_cents']}")

    def test_waiver_stacking_provisional_applies_at_enrollment(self):
        """PRD §3.4: "The **waiver stacking** calculation runs on approval, on
        revocation, and — provisionally — whenever a new assessment is created on
        an account holding approved applications."
        PRD §3.3: "If the account holds approved waiver applications, provisional
        waiver stacking runs against the new assessment (§3.4)."

        Design: Difficulty/dual_variant_calc/waiver_stacking_provisional_vs_final_diverge
        """
        env = setup_approved_waiver_account(fee_amount=10000, waiver_pct_bp=5000,
                                            grade_level=10, enroll=True)
        fa = env["assessment"]
        assert fa["waived_amount_cents"] == 5000, (
            f"Provisional stacking at creation: floor(10000*0.5)=5000; got {fa['waived_amount_cents']}")
        account = get_success_data(api_client.get_student_account(
            env["account"]["id"], make_bookkeeper_headers()))
        assert account["waived_cents"] == 5000
        assert account["balance_cents"] == 5000

    def test_waiver_stacking_priority_cap_waterfall(self):
        """PRD §3.4: "The approved programs for the account are sorted by
        stacking_priority ascending, ties broken by program created_at ascending."
        and "The remaining allowance is max_waived_per_student_cents minus the
        cents this program has already waived across the account's other
        assessments, where earlier-created assessments consume the cap first in
        created_at ascending order."
        and "the tentative waiver is the remaining base times the program's
        waiver_pct_bp divided by ten thousand, **rounded down to a whole cent
        first**; the result is then capped at the smaller of two limits."

        Design: Difficulty/combinatorial_formula/waiver_stacking_priority_cap_waterfall
        """
        bk = make_bookkeeper_headers("bk-1")
        env = setup_year_with_fee(fee_amount=10000)
        year_id, dept_id = env["year"]["id"], env["department"]["id"]
        f1 = env["fee_item"]
        f2 = get_success_data(api_client.create_fee_catalog_item(
            year_id, create_fee_catalog_item_payload(
                name="F2", amount_cents=8000, department_id=dept_id), bk))
        o1 = get_success_data(api_client.create_offering(year_id, create_offering_payload(
            title="Chem", department_id=dept_id, fee_item_id=f1["id"],
            start_date="2026-09-01", end_date="2026-12-15"), bk))
        o2 = get_success_data(api_client.create_offering(year_id, create_offering_payload(
            title="Bio", department_id=dept_id, fee_item_id=f2["id"],
            start_date="2027-01-05", end_date="2027-04-30"), bk))
        student, account = add_student_with_account(year_id, grade_level=11)
        get_success_data(api_client.create_enrollment(account["id"], {"offering_id": o1["id"]}, bk))
        get_success_data(api_client.create_enrollment(account["id"], {"offering_id": o2["id"]}, bk))
        pa = create_program(env, name="PA", waiver_pct_bp=5000, stacking_priority=1,
                            max_waived_per_student_cents=3000)
        pb = create_program(env, name="PB", waiver_pct_bp=2500, stacking_priority=2,
                            max_waived_per_student_cents=100000)
        submit_and_approve_application(account["id"], pa["id"],
                                       submitter_user_id="fam-1", reviewer_user_id="bk-1")
        submit_and_approve_application(account["id"], pb["id"],
                                       submitter_user_id="fam-1", reviewer_user_id="bk-1")
        assessments = get_success_data(api_client.list_fee_assessments(account["id"], bk))
        assert len(assessments) == 2
        a1, a2 = assessments[0], assessments[1]
        assert a1["assessed_amount_cents"] == 10000
        assert a1["waived_amount_cents"] == 4750, (
            f"PA min(floor(10000*0.5), cap 3000)=3000 + PB floor(7000*0.25)=1750; "
            f"got {a1['waived_amount_cents']}")
        assert a2["assessed_amount_cents"] == 8000
        assert a2["waived_amount_cents"] == 2000, (
            f"PA cap exhausted (0 remaining) + PB floor(8000*0.25)=2000; got {a2['waived_amount_cents']}")
        account = get_success_data(api_client.get_student_account(account["id"], bk))
        assert account["waived_cents"] == 6750

    def test_waiver_stacking_full_coverage_waives_assessment(self):
        """PRD §3.4: "An assessment whose waiver coverage reaches its full
        assessed_amount_cents transitions `ASSESSED` → `WAIVED` with
        waived_amount_cents set to the entire assessed amount; `WAIVED` is
        terminal."

        Design: Difficulty/combinatorial_formula/waiver_stacking_priority_cap_waterfall
        """
        bk = make_bookkeeper_headers("bk-1")
        env = setup_year_with_fee(fee_amount=5000, with_offering=True)
        student, account = add_student_with_account(env["year"]["id"], grade_level=10)
        get_success_data(api_client.create_enrollment(
            account["id"], {"offering_id": env["offering"]["id"]}, bk))
        program = create_program(env, waiver_pct_bp=10000,
                                 max_waived_per_student_cents=10000000)
        submit_and_approve_application(account["id"], program["id"],
                                       submitter_user_id="fam-1", reviewer_user_id="bk-1")
        fa = get_success_data(api_client.list_fee_assessments(account["id"], bk))[0]
        assert fa["waived_amount_cents"] == 5000
        assert fa["status"] == "WAIVED"
        account = get_success_data(api_client.get_student_account(account["id"], bk))
        assert account["waived_cents"] == 5000
        assert account["balance_cents"] == 0


class TestWaiverRevoke:
    def test_waiver_approve_revoke_roundtrip_conserves_balance(self):
        """PRD §3.4: "Revocation recomputes without the revoked program: waived
        amounts roll back, and an assessment that loses its full coverage returns
        from `WAIVED` to `ASSESSED` — or to `PARTIALLY_PAID` when payments have
        already landed — per the remaining obligation."

        Design: Difficulty/compensating_invariant/waiver_approve_revoke_roundtrip_conserves_balance
        """
        bk = make_bookkeeper_headers("bk-1")
        env = setup_year_with_fee(fee_amount=8000, with_offering=True)
        student, account = add_student_with_account(env["year"]["id"], grade_level=10)
        get_success_data(api_client.create_enrollment(
            account["id"], {"offering_id": env["offering"]["id"]}, bk))
        program = create_program(env, waiver_pct_bp=5000,
                                 max_waived_per_student_cents=10000000)
        app = get_success_data(api_client.create_waiver_application(
            account["id"], {"waiver_program_id": program["id"]},
            make_family_headers("fam-1")))
        pre = get_success_data(api_client.get_student_account(account["id"], bk))
        assert pre["balance_cents"] == 8000 and pre["waived_cents"] == 0
        get_success_data(api_client.approve_waiver_application(
            account["id"], app["id"], {"expected_account_version": pre["version"]}, bk))
        mid = get_success_data(api_client.get_student_account(account["id"], bk))
        assert mid["balance_cents"] == 4000, f"Post-approve balance 4000; got {mid['balance_cents']}"
        assert mid["waived_cents"] == 4000
        # Revoke (bk-1 differs from the fam-1 submitter)
        get_success_data(api_client.revoke_waiver_application(account["id"], app["id"], bk))
        post = get_success_data(api_client.get_student_account(account["id"], bk))
        assert post["balance_cents"] == 8000, (
            f"Revocation must restore the pre-approve balance exactly; got {post['balance_cents']}")
        assert post["waived_cents"] == 0
        fa = get_success_data(api_client.list_fee_assessments(account["id"], bk))[0]
        assert fa["status"] == "ASSESSED", (
            f"100%-waiver rollback returns the assessment to ASSESSED; got {fa['status']}")

    def test_waiver_revoke_restores_outstanding_for_payment(self):
        """PRD §3.4: "Revoking an `APPROVED` application requires the revoker's
        `X-User-ID` to differ from submitted_by_user_id (again
        `ERR_WAIVER_SELF_APPROVAL`) and rolls the program out of the stacking as
        described below, moving the application to `REVOKED`"

        Design: Difficulty/compensating_invariant/waiver_approve_revoke_roundtrip_conserves_balance
        """
        bk = make_bookkeeper_headers("bk-1")
        env = setup_approved_waiver_account(fee_amount=8000, waiver_pct_bp=5000,
                                            grade_level=10, enroll=True)
        account_id = env["account"]["id"]
        # Assessment outstanding is 8000 - 4000 waived = 4000; pay half of it so
        # the assessment is PARTIALLY_PAID at revoke time. (PRD §3.4 stacking
        # visits assessments in ASSESSED or PARTIALLY_PAID status; a fully PAID
        # row has no PRD-declared transition back, so the rollback must be
        # exercised on a still-open assessment.)
        pay_and_settle(account_id, 2000, idempotency_key="k1")
        fa = get_success_data(api_client.list_fee_assessments(account_id, bk))[0]
        assert fa["status"] == "PARTIALLY_PAID"
        # Revoke the waiver: the program rolls out of the stacking and the
        # outstanding obligation returns
        get_success_data(api_client.revoke_waiver_application(
            account_id, env["application"]["id"], bk))
        account = get_success_data(api_client.get_student_account(account_id, bk))
        assert account["waived_cents"] == 0
        assert account["balance_cents"] == 6000, (
            f"8000 assessed - 0 waived - 2000 paid = 6000; got {account['balance_cents']}")
        # The restored outstanding is payable; the roundtrip conserves balance.
        pay_and_settle(account_id, 6000, idempotency_key="k2")
        fa = get_success_data(api_client.list_fee_assessments(account_id, bk))[0]
        assert fa["status"] == "PAID"
        account = get_success_data(api_client.get_student_account(account_id, bk))
        assert account["balance_cents"] == 0
