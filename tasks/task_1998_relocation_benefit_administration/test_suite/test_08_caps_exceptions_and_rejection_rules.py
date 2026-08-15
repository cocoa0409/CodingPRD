"""Cap enforcement, exception lifecycle, validation ordering, role and ownership."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    make_vendor_headers,
    assert_case_ledger,
    create_policy,
    create_employee,
    create_vendor,
    create_policy_payload,
    create_case_in_progress,
    setup_case_with_vendor,
    create_assignment_in_state,
    create_claim,
    create_approved_claim,
    approve_claim,
    reject_claim,
    create_housing_booking,
    create_travel_booking,
    confirm_booking,
    create_booking_payload,
    create_claim_payload,
    create_exception_request,
    approve_exception,
    reject_exception,
    setup_repayment_case,
    get_case,
    get_case_version,
)

MC = TEST_USERS["coordinator_headers"]
FIN = TEST_USERS["finance_headers"]
PM = TEST_USERS["program_manager_headers"]


class TestMiscCapEnforcement:
    def test_approve_claim_over_cap_without_exception_rejected(self):
        """PRD §3.5: "Following the global evaluation order, a stale version is
        rejected with `ERR_STALE_VERSION` first, then the case-open check
        (`ERR_CASE_NOT_OPEN`), then the cap arithmetic, which re-verifies the
        amount against the remaining miscellaneous headroom and rejects overflow
        with `ERR_CAP_EXCEEDED`."
        PRD §2.7: "The **remaining headroom** is the effective cap minus the
        amounts the case is already holding against that component:
        approved-but-unpaid vendor estimates hold household-goods funds,
        confirmed-but-uncompleted bookings hold housing or travel funds by
        `kind`, and approved-but-unpaid claims hold miscellaneous funds."

        Design: Corner/validations/approve_claim_over_cap_without_exception_rejected
        """
        ctx = create_case_in_progress()  # misc cap 200000
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        # Claim B (100000) is submitted while headroom still allows it
        # (submission itself is cap-checked per PRD §3.5).
        claim_b = create_claim(case_id, emp_id, amount_cents=100000, category="MISC")
        # Claim A (150000) is then approved and holds miscellaneous headroom
        # (SUBMITTED claims hold nothing per PRD §2.7).
        create_approved_claim(case_id, emp_id, amount_cents=150000, category="MISC")

        # Approving B would push MISC to 250000 > 200000 effective cap.
        resp = api_client.approve_claim(
            claim_b["id"], {"expected_case_version": get_case_version(case_id)}, FIN)
        validate_error(resp, ApiErrorId.ERR_CAP_EXCEEDED)

        claim_b_after = validate_success(api_client.get_expense_claim(claim_b["id"], MC))
        assert claim_b_after["status"] == "SUBMITTED"
        assert_case_ledger(get_case(case_id), committed=150000, paid=0, released=0)

    def test_approved_exception_relaxes_cap(self):
        """PRD §2.7: "On any given case, the **effective cap** for a component
        is the policy cap plus the sum of `requested_cap_increase_cents` over
        that case's `APPROVED` exception requests naming that component."
        PRD §3.7: "Because the effective cap derives from the sum of approved
        increases per case and component, an approved exception immediately
        widens headroom for subsequent bookings, claims, estimate approvals, and
        loss-on-sale computations"
        PRD §3.5: "Submission also checks the claim amount against the case's
        remaining miscellaneous headroom — the effective `MISC` cap anchored on
        the policy's `misc_cap_cents` — and rejects overflow with
        `ERR_CAP_EXCEEDED`."

        Design: Corner/validations/approved_exception_relaxes_cap
        """
        ctx = create_case_in_progress()  # misc cap 200000
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]

        # Without an exception the 250000 claim fails the submission cap check.
        resp = api_client.create_expense_claim(
            create_claim_payload(case_id, 250000, "MISC", "REIMBURSEMENT"),
            make_employee_headers(emp_id))
        validate_error(resp, ApiErrorId.ERR_CAP_EXCEEDED)

        ex = create_exception_request(case_id, emp_id, component="MISC",
                                      requested_cap_increase_cents=100000,
                                      justification="high-cost destination")
        approved_ex = approve_exception(ex["id"], case_id)
        assert approved_ex["status"] == "APPROVED"

        # Effective MISC cap is now 200000 + 100000 = 300000: the same claim
        # amount submits and approves.
        claim = create_claim(case_id, emp_id, amount_cents=250000, category="MISC")
        assert claim["status"] == "SUBMITTED"
        approved_claim = approve_claim(claim["id"], case_id)
        assert approved_claim["status"] == "APPROVED"
        assert_case_ledger(get_case(case_id), committed=250000, paid=0, released=0)


class TestValidationPriorityPairs:
    def test_state_beats_fiscal_on_claim_approve(self):
        """PRD §2.10: "Every request passes through a fixed, ordered validation
        cascade, and the first failing check determines the response — later
        checks are not evaluated."
        PRD §2.10: "6. **State validity**: the target resource is in a legal
        source state for the requested transition (`ERR_INVALID_STATE`, HTTP
        409)"
        PRD §2.10: "11. **Fiscal caps**: component headroom checks
        (`ERR_CAP_EXCEEDED`) and the temporary-housing stay ceiling
        (`ERR_NIGHTS_LIMIT_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_claim_approve
        """
        ctx = create_case_in_progress()  # misc cap 200000
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        # Claim B (100000) submitted while headroom still allows it (submission
        # is cap-checked per PRD §3.5), then claim A approved: holds 150000 of
        # the 200000 MISC cap (SUBMITTED claims hold nothing per PRD §2.7).
        claim_b = create_claim(case_id, emp_id, amount_cents=100000, category="MISC")
        create_approved_claim(case_id, emp_id, amount_cents=150000, category="MISC")
        # Rejecting B leaves it both a state violation (REJECTED is not a
        # legal source for approve) and, given the held 150000, a cap
        # violation (150000 + 100000 > 200000).
        reject_claim(claim_b["id"], "over policy")

        resp = api_client.approve_claim(
            claim_b["id"], {"expected_case_version": get_case_version(case_id)}, FIN)
        # State (priority 6) fires; the cap breach (priority 11) must not surface.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        claim_b_after = validate_success(api_client.get_expense_claim(claim_b["id"], MC))
        assert claim_b_after["status"] == "REJECTED"

    def test_state_beats_stale_version_and_fiscal_on_claim_approve(self):
        """PRD §2.10: "Every request passes through a fixed, ordered validation
        cascade, and the first failing check determines the response — later
        checks are not evaluated."
        PRD §2.10: "7. **Optimistic concurrency**: on the three guarded writes
        of §2.9, `expected_case_version` must match the case's current
        `version` (`ERR_STALE_VERSION`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_claim_approve
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        # Claim B submitted while headroom allows (submission is cap-checked
        # per PRD §3.5); claim A then approved and holds 150000 of the 200000
        # MISC cap (SUBMITTED claims hold nothing per PRD §2.7).
        claim_b = create_claim(case_id, emp_id, amount_cents=100000, category="MISC")
        create_approved_claim(case_id, emp_id, amount_cents=150000, category="MISC")
        reject_claim(claim_b["id"], "over policy")

        # Capture the case version, then advance it with an interleaved write.
        stale_version = get_case_version(case_id)
        booking = create_travel_booking(case_id, emp_id, 30000)
        confirm_booking(booking["id"])

        # Simultaneously: REJECTED source state (6), stale version (7), cap
        # breach (11). The earliest check — state — determines the response.
        resp = api_client.approve_claim(
            claim_b["id"], {"expected_case_version": stale_version}, FIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        claim_b_after = validate_success(api_client.get_expense_claim(claim_b["id"], MC))
        assert claim_b_after["status"] == "REJECTED"

    def test_temporal_beats_fiscal_on_booking_create(self):
        """PRD §2.10: "Every request passes through a fixed, ordered validation
        cascade, and the first failing check determines the response — later
        checks are not evaluated."
        PRD §2.10: "9. **Temporal rules**: a supplied end date falls after the
        start date (`ERR_INVALID_DATES`, HTTP 422); a temporary-housing stay
        does not overlap another live housing booking on the same case
        (`ERR_HOUSING_OVERLAP`); and a vendor's surveys respect the two-hour
        buffer (`ERR_SURVEY_CONFLICT`)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_booking_create
        """
        ctx = create_case_in_progress()  # temp-housing cap 300000
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        # B1 [Sep 1, Sep 10) at 25000/night = 225000, confirmed (held).
        b1 = create_housing_booking(case_id, emp_id,
                                    start_date="2026-09-01T00:00:00Z",
                                    end_date="2026-09-10T00:00:00Z",
                                    nightly_cents=25000)
        confirm_booking(b1["id"])
        _, meta_before = validate_paginated(
            api_client.list_case_service_bookings(case_id, MC))

        # Overlapping [Sep 5, Sep 15) at 25000/night (250000): simultaneously an
        # overlap (9) and a cap breach (225000 + 250000 > 300000) (11).
        resp = api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-09-05T00:00:00Z",
                                   end_date="2026-09-15T00:00:00Z",
                                   amount_cents=25000),
            make_employee_headers(emp_id))
        validate_error(resp, ApiErrorId.ERR_HOUSING_OVERLAP)

        _, meta_after = validate_paginated(
            api_client.list_case_service_bookings(case_id, MC))
        assert meta_after["total_count"] == meta_before["total_count"], (
            "no new booking row may be created for the rejected request")

    def test_temporal_overlap_beats_nights_limit_on_booking_create(self):
        """PRD §2.10: "Every request passes through a fixed, ordered validation
        cascade, and the first failing check determines the response — later
        checks are not evaluated."
        PRD §2.10: "9. **Temporal rules**: a supplied end date falls after the
        start date (`ERR_INVALID_DATES`, HTTP 422); a temporary-housing stay
        does not overlap another live housing booking on the same case
        (`ERR_HOUSING_OVERLAP`); and a vendor's surveys respect the two-hour
        buffer (`ERR_SURVEY_CONFLICT`)."
        PRD §2.10: "11. **Fiscal caps**: component headroom checks
        (`ERR_CAP_EXCEEDED`) and the temporary-housing stay ceiling
        (`ERR_NIGHTS_LIMIT_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_booking_create
        """
        ctx = create_case_in_progress()  # max 30 nights
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        b1 = create_housing_booking(case_id, emp_id,
                                    start_date="2026-09-01T00:00:00Z",
                                    end_date="2026-09-10T00:00:00Z",
                                    nightly_cents=15000)
        confirm_booking(b1["id"])

        # [Sep 5, Oct 6) is 31 nights AND overlaps B1: the overlap (temporal,
        # priority 9) must surface, not the stay ceiling (fiscal, priority 11).
        resp = api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-09-05T00:00:00Z",
                                   end_date="2026-10-06T00:00:00Z",
                                   amount_cents=5000),
            make_employee_headers(emp_id))
        validate_error(resp, ApiErrorId.ERR_HOUSING_OVERLAP)


class TestUniquenessAndAppeals:
    def test_duplicate_policy_triple_rejected(self):
        """PRD §3.1: "A tier is keyed by the triple of `job_level`,
        `move_scope` (`DOMESTIC` or `INTERNATIONAL`), and `home_ownership`; the
        triple is unique, so an attempt to create a second tier with an existing
        key is rejected with `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/validations/duplicate_policy_triple_rejected
        """
        create_policy()
        resp = api_client.create_policy(
            create_policy_payload(hhg_cap_cents=600000, temp_housing_cap_cents=350000,
                                  temp_housing_max_nights=45, travel_cap_cents=120000,
                                  misc_cap_cents=250000, repayment_window_months=18,
                                  gross_up_method="MARGINAL_AGGREGATE",
                                  loss_basis="PURCHASE_PRICE"), MC)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    def test_second_appeal_rejected(self):
        """PRD §3.7: "A rejected request is not necessarily dead: the owning
        employee or a coordinator may appeal it back to `PENDING` exactly once.
        The appeal increments `appeal_count` and clears the prior
        `decision_note`; attempting a second appeal on an already-appealed
        request is rejected with `ERR_APPEAL_LIMIT_REACHED`."

        Design: Corner/validations/second_appeal_rejected
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        ex = create_exception_request(case_id, emp_id, component="HHG",
                                      requested_cap_increase_cents=50000,
                                      justification="piano")
        rejected = reject_exception(ex["id"], "no")
        assert rejected["status"] == "REJECTED"
        assert rejected["decision_note"] == "no"

        appealed = get_success_data(api_client.appeal_exception(
            ex["id"], make_employee_headers(emp_id)))
        assert appealed["status"] == "PENDING"
        assert appealed["appeal_count"] == 1
        assert appealed["decision_note"] is None

        reject_exception(ex["id"], "still no")
        resp = api_client.appeal_exception(ex["id"], make_employee_headers(emp_id))
        validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)

        after = validate_success(api_client.get_exception_request(ex["id"], MC))
        assert after["status"] == "REJECTED"
        assert after["appeal_count"] == 1


class TestRoleAndOwnershipEnforcement:
    def test_employee_cannot_approve_estimate(self):
        """PRD §2.1: "Access to every operation is restricted by role as
        enumerated in §4. An attempt to act outside one's designated role —
        including failing an entity-backed ownership check — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.3: "Estimate approval by a coordinator is a guarded write: the
        request must carry `expected_case_version` matching the case's current
        `version`, with a stale value rejected as `ERR_STALE_VERSION`"

        Design: Corner/rbac/employee_cannot_approve_estimate
        """
        ctx = setup_case_with_vendor({"name": "Role Runners"})
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        emp_id = ctx["employee"]["id"]
        ma = create_assignment_in_state(case_id, vendor_id, "ESTIMATE_SUBMITTED",
                                        estimated_cents=80000)

        resp = api_client.approve_estimate(
            ma["id"], {"expected_case_version": get_case_version(case_id)},
            make_employee_headers(emp_id))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        ma_after = validate_success(api_client.get_move_assignment(ma["id"], MC))
        assert ma_after["status"] == "ESTIMATE_SUBMITTED"

    def test_vendor_cannot_submit_estimate_on_others_assignment(self):
        """PRD §2.10: "Ownership**: an `Employee` caller may act only on
        resources whose case's `employee_id` equals their `X-User-ID`, and a
        `Vendor` caller only on assignments whose `vendor_id` equals their
        `X-User-ID` (`ERR_FORBIDDEN`)."
        PRD §3.3: "The owning vendor — the caller whose `X-User-ID` equals the
        assignment's `vendor_id` — submits `estimated_cents`, moving the
        assignment `SURVEY_SCHEDULED` → `ESTIMATE_SUBMITTED`."

        Design: Corner/rbac/vendor_cannot_submit_estimate_on_others_assignment
        """
        ctx = setup_case_with_vendor({"name": "Owner One"})
        case_id = ctx["case"]["id"]
        v1 = ctx["vendor"]["id"]
        v2 = create_vendor(name="Owner Two")["id"]
        ma = create_assignment_in_state(case_id, v1, "SURVEY_SCHEDULED")

        resp = api_client.submit_estimate(
            ma["id"], {"estimated_cents": 80000}, make_vendor_headers(v2))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        ma_after = validate_success(api_client.get_move_assignment(ma["id"], MC))
        assert ma_after["status"] == "SURVEY_SCHEDULED"
        assert ma_after["estimated_cents"] is None

    def test_program_manager_cannot_create_vendors(self):
        """PRD §2.1: "Access to every operation is restricted by role as
        enumerated in §4. An attempt to act outside one's designated role —
        including failing an entity-backed ownership check — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.3: "Household-goods vendors are registered by a
        `MobilityCoordinator` with a `name` and the list of `service_regions`
        they cover; new vendors begin `ACTIVE`."

        Design: Corner/rbac/program_manager_cannot_create_vendors
        """
        resp = api_client.create_vendor(
            {"name": "PM Vendors", "service_regions": ["IL"]}, PM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_employee_cannot_sign_others_repayment(self):
        """PRD §2.10: "Ownership**: an `Employee` caller may act only on
        resources whose case's `employee_id` equals their `X-User-ID`, and a
        `Vendor` caller only on assignments whose `vendor_id` equals their
        `X-User-ID` (`ERR_FORBIDDEN`)."
        PRD §3.8: "The agreement activates when the owning employee signs it
        (`DRAFT` → `ACTIVE`)"

        Design: Corner/rbac/employee_cannot_sign_others_repayment
        """
        ctx = setup_repayment_case(paid_amount=61000, sign=False)
        agreement = ctx["agreement"]
        assert agreement["status"] == "DRAFT"
        other = create_employee(full_name="Sign Two")

        resp = api_client.sign_agreement(
            agreement["id"], make_employee_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(
            api_client.get_repayment_agreement(agreement["id"], MC))
        assert after["status"] == "DRAFT"
