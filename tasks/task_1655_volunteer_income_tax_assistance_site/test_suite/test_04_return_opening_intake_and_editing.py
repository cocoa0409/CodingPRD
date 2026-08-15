"""Opening a return and editing it at intake: initial state, compliance
gates at creation, cardinality and reuse rules, the conditional document
checklist, computed-field write rejection, optimistic concurrency, immediate
read-back, and status filtering."""
from test_helpers import (
    DAY2_END,
    DAY2_START,
    ApiErrorId,
    assert_tax_return,
    check_in_appointment,
    create_checked_in_appointment,
    create_intake_return,
    create_tax_return_payload,
    create_verified_taxpayer,
    get_return,
    patch_return,
    preparation_ready_patch,
    register_taxpayer,
    schedule_appointment,
    setup_staffed_site,
    transition_return,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import patch_tax_return_payload


class TestReturnInitialState:
    def test_return_initial_state_intake(self, api):
        """PRD §3.4: "At creation the return derives its context from the
        appointment: `taxpayer_id` and `site_id` are copied across,
        `preparer_id` is set to the acting preparer's `X-User-ID`, and the
        return begins in `INTAKE_STARTED`. Its `reviewer_id` stays null until
        the first quality review, `submission_count` and `qr_failure_count`
        start at zero, `reached_preparation` starts false, `transmitted_at`,
        `referral_reason`, `referral_destination`, `withdrawal_reason`, and
        `first_ack_outcome` all start null, and the provisional
        `estimated_refund_cents` is computed immediately — zero while all the
        money fields are at their default of zero."

        Design: Corner/state_machines/return_initial_state_intake
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(
            ctx.scr_headers, full_name="Tp Init", ssn_token="SSN-I1",
            phone="555-2007", id_document_type="PASSPORT",
        )
        appt, ret = create_intake_return(ctx, tp["id"])
        assert_tax_return(ret)
        assert ret["status"] == "INTAKE_STARTED"
        assert ret["taxpayer_id"] == tp["id"]
        assert ret["site_id"] == ctx.site_id
        assert ret["preparer_id"] == ctx.preparer["id"]
        assert ret["reviewer_id"] is None
        assert ret["submission_count"] == 0
        assert ret["qr_failure_count"] == 0
        assert ret["reached_preparation"] is False
        assert ret["first_ack_outcome"] is None
        assert ret["final_refund_cents"] is None
        assert ret["documents_complete"] is False
        assert ret["out_of_scope"] is False
        assert ret["estimated_refund_cents"] == 0


class TestReturnCreationGates:
    def test_identity_unverified_blocks_return_create(self, api):
        """PRD §3.4: "Opening is gated through the pipeline of §2.8: the
        taxpayer's `identity_status` must be `VERIFIED`
        (`ERR_IDENTITY_NOT_VERIFIED`); the acting preparer must be `ACTIVE`
        and hold `CURRENT` passed `ETHICS` and `BASIC` certifications for
        season 2026, plus `ADVANCED` when `has_advanced_scope_items` is true
        (`ERR_VOLUNTEER_NOT_CERTIFIED`)"

        Design: Corner/validations/identity_unverified_blocks_return_create
        """
        ctx = setup_staffed_site()
        tp = register_taxpayer(ctx.scr_headers, full_name="Tp UV",
                               ssn_token="SSN-UV1", phone="555-2015")
        assert tp["identity_status"] == "UNVERIFIED"
        appt = create_checked_in_appointment(ctx, tp["id"], ctx.preparer["id"])

        resp = api.create_tax_return(
            create_tax_return_payload(appt["id"]), ctx.prep_headers
        )
        validate_error(resp, ApiErrorId.ERR_IDENTITY_NOT_VERIFIED)

    def test_open_return_exists_blocks_second_return(self, api):
        """PRD §3.4: "cardinality then forbids opening a second in-flight
        return for the same taxpayer at the same site — in-flight meaning any
        status other than `COMPLETED`, `REFERRED`, or `WITHDRAWN`
        (`ERR_OPEN_RETURN_EXISTS`)"

        Design: Corner/validations/open_return_exists_blocks_second_return
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp OR",
                                      ssn_token="SSN-OR1", phone="555-2016")
        appt1, ret1 = create_intake_return(ctx, tp["id"])
        assert ret1["status"] == "INTAKE_STARTED"
        appt2 = schedule_appointment(
            ctx, tp["id"], ctx.preparer["id"],
            start_at=DAY2_START, end_at=DAY2_END, purpose="FOLLOW_UP",
        )
        check_in_appointment(appt2["id"], ctx.scr_headers)

        resp = api.create_tax_return(
            create_tax_return_payload(appt2["id"]), ctx.prep_headers
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_RETURN_EXISTS)

    def test_appointment_reuse_rejected(self, api):
        """PRD §3.4: "and forbids reusing an appointment that already
        originated a return (`ERR_APPOINTMENT_ALREADY_USED`)"

        Design: Corner/validations/appointment_reuse_rejected
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp RU",
                                      ssn_token="SSN-RU1", phone="555-2023")
        appt, ret1 = create_intake_return(ctx, tp["id"])

        resp = api.create_tax_return(
            create_tax_return_payload(appt["id"], tax_year=2024), ctx.prep_headers
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_ALREADY_USED)

    def test_advanced_scope_requires_advanced_cert(self, api):
        """PRD §3.4: "the acting preparer must be `ACTIVE` and hold `CURRENT`
        passed `ETHICS` and `BASIC` certifications for season 2026, plus
        `ADVANCED` when `has_advanced_scope_items` is true
        (`ERR_VOLUNTEER_NOT_CERTIFIED`)"

        Design: Corner/validations/advanced_scope_requires_advanced_cert
        """
        ctx = setup_staffed_site()  # preparer holds ETHICS + BASIC only
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp ADV",
                                      ssn_token="SSN-ADV", phone="555-2022")
        appt = create_checked_in_appointment(ctx, tp["id"], ctx.preparer["id"])

        resp = api.create_tax_return(
            create_tax_return_payload(appt["id"], has_advanced_scope_items=True),
            ctx.prep_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_CERTIFIED)

    def test_sponsor_cannot_create_return(self, api, sponsor_admin_headers):
        """PRD §2.1: "A `Preparer` is a certified volunteer who opens returns
        from checked-in appointments and owns the returns it creates"
        PRD §2.1: "Any action attempted outside the caller's role envelope is
        rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/sponsor_cannot_create_return
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp RB4",
                                      ssn_token="SSN-RB4", phone="555-2032",
                                      id_document_type="STATE_ID")
        appt = create_checked_in_appointment(ctx, tp["id"], ctx.preparer["id"])

        resp = api.create_tax_return(
            create_tax_return_payload(appt["id"]), sponsor_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestLifecycleOrdering:
    def test_transmit_from_intake_rejected(self, api):
        """PRD §3.6: "Transmission — `QR_PASSED` to `TRANSMITTED`, performed
        by the `SiteCoordinator` — e-files the return."
        PRD §2.8: "5. **State legality**, on every state-driving call, on
        identity verification, on rejection follow-up, on return edits, on
        allocation add and remove, and on appointment rescheduling: the
        requested transition must exist from the resource's current state —
        terminal states accept no transitions — and the editability windows
        must hold."

        Design: Corner/state_machines/transmit_from_intake_rejected
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp T1",
                                      ssn_token="SSN-T1", phone="555-2008",
                                      id_document_type="STATE_ID")
        appt, ret = create_intake_return(ctx, tp["id"])

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "TRANSMITTED"}, ctx.coord_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        ret = get_return(ret["id"], ctx.prep_headers)
        assert ret["status"] == "INTAKE_STARTED"
        assert ret["submission_count"] == 0


class TestScopeGateAndReferral:
    def test_out_of_scope_gate_and_referral_flow(self, api):
        """PRD §3.4: "`out_of_scope` is true when `out_of_scope_flags` is
        non-empty — the recognized flags are `RENTAL_INCOME`,
        `BUSINESS_WITH_LOSS`, `FOREIGN_EARNED_INCOME`, and `CASUALTY_LOSS` —
        or when the `filing_status` is `MARRIED_SEPARATE`"
        PRD §3.8: "For a return whose `out_of_scope` is true, referral or
        withdrawal are the only exits: any attempt to advance it toward
        preparation or review is rejected with `ERR_OUT_OF_SCOPE`."
        PRD §3.8: "From any of `INTAKE_STARTED`, `IN_PREPARATION`,
        `PENDING_QR`, `QR_FAILED`, `QR_PASSED`, or `REJECTED`, a `Preparer`,
        a `QualityReviewer`, or the `SiteCoordinator` may move the return to
        `REFERRED`, supplying a `referral_reason` and a
        `referral_destination` (`ERR_INVALID_REQUEST` when either is absent);
        both are recorded on the return."

        Design: Corner/validations/out_of_scope_gate_and_referral_flow
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp OOS",
                                      ssn_token="SSN-OOS", phone="555-2017",
                                      id_document_type="PASSPORT")
        appt, ret = create_intake_return(
            ctx, tp["id"], return_overrides={"out_of_scope_flags": ["RENTAL_INCOME"]}
        )
        assert ret["out_of_scope"] is True
        assert "RENTAL_INCOME" in ret["out_of_scope_reasons"]
        ret = preparation_ready_patch(ret, ctx.prep_headers)

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "IN_PREPARATION"}, ctx.prep_headers
        )
        validate_error(resp, ApiErrorId.ERR_OUT_OF_SCOPE)

        ret = validate_success(
            api.transition_tax_return(
                ret["id"],
                {"to_status": "REFERRED",
                 "referral_reason": "Rental income is out of VITA scope",
                 "referral_destination": "Commercial preparer referral list"},
                ctx.prep_headers,
            )
        )
        assert ret["status"] == "REFERRED"
        assert ret["referral_reason"] == "Rental income is out of VITA scope"
        assert ret["referral_destination"] == "Commercial preparer referral list"


class TestConditionalDocumentChecklist:
    def test_begin_preparation_without_bank_info_rejected(self, api):
        """PRD §3.4: "`documents_complete` is true exactly when `PHOTO_ID`,
        `SSN_CARD`, and `W2` are all present in `documents_received` and,
        whenever the `refund_method` is `DIRECT_DEPOSIT`, `BANK_INFO` is
        present as well."
        PRD §3.4: "It requires `documents_complete` to be true and
        `interview_confirmed` to be true (`ERR_DOCUMENTS_INCOMPLETE`), and
        the return must still be in scope (`ERR_OUT_OF_SCOPE`)."

        Design: Corner/validations/begin_preparation_without_bank_info_rejected
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp BI",
                                      ssn_token="SSN-BI1", phone="555-2024",
                                      id_document_type="PASSPORT")
        appt, ret = create_intake_return(ctx, tp["id"])
        ret = patch_return(
            ret, ctx.prep_headers,
            documents_received=["PHOTO_ID", "SSN_CARD", "W2"],
            interview_confirmed=True,
            refund_method="DIRECT_DEPOSIT",
        )
        assert ret["documents_complete"] is False, (
            "BANK_INFO missing while refund_method is DIRECT_DEPOSIT"
        )

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "IN_PREPARATION"}, ctx.prep_headers
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENTS_INCOMPLETE)


class TestPatchEditing:
    def test_patch_computed_field_rejected(self, api):
        """PRD §3.4: "The editable surface comprises `documents_received` —
        any subset of `PHOTO_ID`, `SSN_CARD`, `W2`, `FORM_1099`,
        `PRIOR_YEAR_RETURN`, and `BANK_INFO`, starting empty — the
        `interview_confirmed` flag (false until the intake and interview
        sheet has been reviewed with the taxpayer), the money fields
        `wages_cents`, `other_income_cents`, `earned_income_cents`,
        `withholding_reported_cents`, and `withholding_verified_cents` (each
        at least zero when present, with `withholding_verified_cents` null
        until documents have been verified), `qualifying_children` (from 0 to
        10, default 0), the `refund_method` (`PAPER_CHECK` by default, or
        `DIRECT_DEPOSIT`), and the scope fields `has_advanced_scope_items`
        and `out_of_scope_flags`."
        PRD §2.8: "4. **Request schema**, on all endpoints: required fields
        must be present, types correct, enum values valid, unknown fields
        rejected, and conditionally required fields supplied"

        Design: Corner/entities/patch_computed_field_rejected
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp Z",
                                      ssn_token="SSN-Z1", phone="555-2005")
        appt, ret = create_intake_return(ctx, tp["id"])

        payload = patch_tax_return_payload(ret["version"], estimated_refund_cents=1)
        resp = api.patch_tax_return(ret["id"], payload, ctx.prep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_occ_return_patch_stale(self, api):
        """PRD §2.7: "Editing a return's intake and preparation fields
        requires the request to carry `expected_return_version`, holding the
        `version` of the return the client last observed. If the return's
        current `version` has advanced beyond that value — because another
        writer has since edited the return — the edit is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the
        return before writing."

        Design: Corner/cross_cutting_complexity_layers/occ_return_patch_stale
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp OCC",
                                      ssn_token="SSN-OCC", phone="555-2034")
        appt, ret = create_intake_return(ctx, tp["id"])
        stale_version = ret["version"]

        ret = patch_return(ret, ctx.prep_headers, wages_cents=500000)
        assert ret["wages_cents"] == 500000

        payload = patch_tax_return_payload(stale_version, wages_cents=600000)
        resp = api.patch_tax_return(ret["id"], payload, ctx.prep_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        ret = get_return(ret["id"], ctx.prep_headers)
        assert ret["wages_cents"] == 500000, "the first write stands"
        assert ret["version"] != stale_version

    def test_immediate_read_after_write(self, api):
        """PRD §3.4: "Every such edit must carry `expected_return_version`
        per §2.7, recomputes the return's `documents_complete`,
        `out_of_scope`, `out_of_scope_reasons`, and `estimated_refund_cents`,
        and increments the return's `version` by one."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        Design: Corner/consistency_model/immediate_read_after_write
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp IC",
                                      ssn_token="SSN-IC1", phone="555-2036")
        appt, ret = create_intake_return(ctx, tp["id"])
        patched = patch_return(
            ret, ctx.prep_headers,
            wages_cents=1234567, earned_income_cents=1234567,
            withholding_reported_cents=50000,
        )
        # 50000 + min(round_half_up(0.15 * 1234567) = 185185, 600000)
        assert patched["wages_cents"] == 1234567
        assert patched["estimated_refund_cents"] == 235185
        assert patched["version"] == ret["version"] + 1

        fetched = get_return(ret["id"], ctx.prep_headers)
        assert fetched["wages_cents"] == patched["wages_cents"]
        assert fetched["estimated_refund_cents"] == patched["estimated_refund_cents"]
        assert fetched["version"] == patched["version"], (
            "the edit is visible on an immediate read with no lag"
        )


class TestReturnStatusFilter:
    def test_status_filter_list(self, api):
        """PRD §2.3: "The two top-level list views accept optional filters:
        the appointments list filters by `site_id`, `taxpayer_id`,
        `volunteer_id`, and `status`, and the returns list filters by
        `taxpayer_id`, `site_id`, `appointment_id`, `preparer_id`,
        `reviewer_id`, and `status`."

        Design: Corner/endpoints/status_filter_list
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp SF",
                                      ssn_token="SSN-SF1", phone="555-2027")
        appt, ret = create_intake_return(
            ctx, tp["id"],
            appt_kwargs={"purpose": "INTAKE"},
            return_overrides={"out_of_scope_flags": ["RENTAL_INCOME"]},
        )
        ret = transition_return(
            ret["id"], "REFERRED", ctx.prep_headers,
            referral_reason="Rental income out of scope",
            referral_destination="Commercial preparer list",
        )
        assert ret["status"] == "REFERRED"

        referred, meta = validate_paginated(
            api.list_tax_returns(
                ctx.coord_headers,
                params={"site_id": ctx.site_id, "status": "REFERRED"},
            )
        )
        assert meta["total_count"] == 1
        assert [r["id"] for r in referred] == [ret["id"]]

        completed, meta = validate_paginated(
            api.list_tax_returns(
                ctx.coord_headers,
                params={"site_id": ctx.site_id, "status": "COMPLETED"},
            )
        )
        assert completed == []
        assert meta["total_count"] == 0
