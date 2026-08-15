"""Access control and read models: role denials, patient ownership, list
pagination, notice reachability, the logical clock default, and pinned policy
snapshots across supersession."""
from test_helpers import (
    BILLING,
    COLLECTIONS,
    COMPLIANCE,
    COUNSELOR,
    REVIEWER,
    ApiErrorId,
    add_member,
    assert_instant_eq,
    assert_notification_record,
    build_under_review_application,
    create_account,
    create_active_policy,
    create_application,
    create_determination,
    create_patient,
    create_policy,
    get_account,
    list_account_notices,
    list_application_notices,
    make_patient_headers,
    set_clock,
    setup_account_in_notice_period,
    setup_verified_application,
    submit_application,
    upload_and_verify,
    upload_document,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRoleDenials:
    def test_collections_agent_cannot_create_policy(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "A `ComplianceOfficer` owns policies, halts collection
        actions, runs the community benefit report lifecycle, drives the
        logical clock, and shares determination-reversal and
        patient-registration rights."

        Design: Corner/rbac/collections_agent_cannot_create_policies
        """
        resp = api.create_policy(
            {
                "policy_code": "FAP-X",
                "fpl_base_cents": 1500000,
                "fpl_increment_cents": 500000,
                "full_discount_max_fpl_pct": 200,
                "partial_discount_max_fpl_pct": 300,
                "partial_discount_floor_pct": 50.0,
                "asset_limit_cents": 2500000,
                "retroactive_window_days": 240,
                "notification_period_days": 120,
                "eca_notice_days": 30,
                "doc_response_days": 30,
                "presumptive_partial_score_threshold": 70.0,
                "presumptive_full_score_threshold": 90.0,
                "effective_from": "2026-01-01T00:00:00Z",
                "effective_to": "2027-01-01T00:00:00Z",
            },
            COLLECTIONS,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_counselor_cannot_finalize_determination(self, api):
        """PRD §2.1: "A `FinancialCounselor` is intake staff — shepherding
        applications through review, requesting documents, verifying or
        rejecting uploads, running presumptive screenings, and registering
        patients — but may never create or finalize a determination."
        PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/counselor_cannot_finalize_determination
        """
        ctx = setup_verified_application(
            patient_name="RBAC Ruth", mrn="MRN-RBAC-1", ssn_last4="0050",
            reported_income=2000000, accounts=((100000, 0),),
            tax_return_amount=2000000,
        )
        det = create_determination(
            ctx["application"]["id"], "VERIFIED_APPLICATION",
            [ctx["accounts"][0]["id"]],
        )
        resp = api.finalize_determination(det["id"], COUNSELOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_reviewer_cannot_verify_document(self, api):
        """PRD §2.1: "An `AssistanceReviewer` is the determination authority —
        creating and finalizing determinations and sharing reversal authority
        with compliance — but may not touch documents or screenings."
        PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/reviewer_cannot_verify_documents
        """
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        ctx = build_under_review_application(
            patient_name="RBAC Doc", mrn="MRN-RDOC-1", ssn_last4="0051",
            reported_income=1000000,
        )
        doc = upload_document(
            ctx["application"]["id"], doc_type="TAX_RETURN",
            period_start="2025-01-01", period_end="2025-12-31",
            amount_cents=1000000, household_member_id=ctx["members"][0]["id"],
        )
        resp = api.verify_document(doc["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestPatientOwnership:
    def test_patient_reading_other_patients_applications_rejected(self, api):
        """PRD §2.1: "When `X-User-Role` is `Patient`, `X-User-ID` is the `id`
        of the acting `Patient`; ownership checks on any resource that
        references a `Patient` compare the resource's patient reference to
        `X-User-ID`. Specifically, on every patient-scoped endpoint the
        presented `X-User-ID` must equal the `patient_id` of the targeted
        resource — directly for accounts and applications, and transitively
        for documents (via their owning application) and determinations (via
        their owning application). A mismatch is rejected with
        `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/patient_cannot_access_other_patients_resources
        """
        patient_a = create_patient(
            full_name="Owner A", date_of_birth="1990-01-01",
            ssn_last4="0052", mrn="MRN-OWN-A",
        )
        patient_b = create_patient(
            full_name="Owner B", date_of_birth="1990-01-01",
            ssn_last4="0053", mrn="MRN-OWN-B",
        )
        create_application(
            patient_b["id"], screening_source="STANDARD",
            reported_annual_income_cents=1000000, reported_liquid_assets_cents=0,
        )
        resp = api.list_patient_applications(
            patient_b["id"], make_patient_headers(patient_a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)

    def test_patient_can_submit_own_application(self, api):
        """PRD §2.1: "Role capabilities in brief: a `Patient` creates, submits,
        and withdraws their own applications, adds their own household members
        and documents, posts payments to their own accounts, and reads their
        own data."
        PRD §3.4: "It pins `policy_id` and `policy_version` to the currently
        `ACTIVE` policy — the snapshot all later math must use, immune to later
        supersession."

        Design: Corner/rbac/patient_can_submit_own_application
        """
        set_clock("2026-02-01T00:00:00Z")
        policy = create_active_policy()
        patient = create_patient(
            full_name="Self Serve", date_of_birth="1990-01-01",
            ssn_last4="0054", mrn="MRN-SELF-1",
        )
        own = make_patient_headers(patient["id"])
        app = validate_success(
            api.create_application(
                {
                    "patient_id": patient["id"],
                    "screening_source": "STANDARD",
                    "reported_annual_income_cents": 1500000,
                    "reported_liquid_assets_cents": 0,
                },
                own,
            ),
            201,
        )
        validate_success(
            api.add_member(
                app["id"],
                {"full_name": "Self Serve", "relationship": "SELF", "age": 40},
                own,
            ),
            201,
        )
        submitted = validate_success(api.submit_application(app["id"], own))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["policy_id"] == policy["id"], (
            "submit pins the currently ACTIVE policy"
        )


class TestListingsAndNotices:
    def test_applications_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; when omitted it defaults to 10, and it accepts a minimum of 1
        and a maximum of 100. The `offset` parameter sets how many items are
        skipped and defaults to 0. Unless otherwise specified, every list
        endpoint returns resources sorted by `created_at` in ascending order.
        List responses carry `limit`, `offset`, `total_count`, and `has_more`
        in the `meta` object of the envelope."

        Design: Corner/endpoints/applications_list_pagination_and_filters
        """
        patient_a = create_patient(
            full_name="List A", date_of_birth="1990-01-01",
            ssn_last4="0043", mrn="MRN-LIST-A",
        )
        patient_b = create_patient(
            full_name="List B", date_of_birth="1990-01-01",
            ssn_last4="0044", mrn="MRN-LIST-B",
        )
        create_application(
            patient_a["id"], screening_source="STANDARD",
            reported_annual_income_cents=1000000, reported_liquid_assets_cents=0,
        )
        # one-open rule: a second application for patient A is refused
        resp = api.create_application(
            {
                "patient_id": patient_a["id"],
                "screening_source": "STANDARD",
                "reported_annual_income_cents": 1000000,
                "reported_liquid_assets_cents": 0,
            },
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_APPLICATION)
        create_application(
            patient_b["id"], screening_source="PRESUMPTIVE",
            reported_annual_income_cents=2000000, reported_liquid_assets_cents=0,
        )
        data, meta = validate_paginated(api.list_applications(COUNSELOR))
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "default limit"
        assert meta["offset"] == 0
        assert len(data) == 2
        # per-patient narrowing via the patient-scoped list endpoint (PRD §4)
        own = validate_success(
            api.list_patient_applications(patient_a["id"], COUNSELOR)
        )
        assert len(own) == 1
        assert own[0]["patient_id"] == patient_a["id"]

    def test_notices_reachable_from_account_and_application(self, api):
        """PRD §3.2: "The `FIRST_STATEMENT`, `DETERMINATION_LETTER`, and
        `DOC_REQUEST` notice types are system-created; staff-issued notices are
        limited to `PLAIN_LANGUAGE_SUMMARY` and `ECA_WARNING`, which a
        `BillingAdministrator` issues against an account by supplying
        `notice_type` and an optional `delivery_channel` (one of `MAIL`,
        `PORTAL`, `EMAIL`), producing a `NotificationRecord` whose `issued_at`
        stamps the logical clock."
        PRD §3.4: "It creates a `PLAIN_LANGUAGE_SUMMARY` `NotificationRecord`
        with `application_id` set and `is_plain_language` true. And it freezes
        collections: every account of this patient whose posture is
        `NOTICE_PERIOD`, `ECA_ELIGIBLE`, or `ECA_ACTIVE` transitions to
        `ASSISTANCE_HOLD`."

        Design: Corner/endpoints/notices_reverse_reachability_on_both_parents
        """
        ctx = setup_account_in_notice_period(
            patient_name="Notice Ned", mrn="MRN-NOT-1", ssn_last4="0045",
            statement_at="2026-01-01T00:00:00Z",
        )
        account_id = ctx["account"]["id"]
        app = create_application(
            ctx["patient"]["id"], screening_source="STANDARD",
            reported_annual_income_cents=1000000, reported_liquid_assets_cents=0,
        )
        add_member(app["id"], full_name="Notice Ned", relationship="SELF", age=40)
        submit_application(app["id"])
        account_notices = list_account_notices(account_id)
        first_statements = [
            n for n in account_notices if n["notice_type"] == "FIRST_STATEMENT"
        ]
        assert len(first_statements) == 1
        assert_notification_record(first_statements[0])
        assert first_statements[0]["account_id"] == account_id
        assert first_statements[0]["is_plain_language"] is True
        app_notices = list_application_notices(app["id"])
        summaries = [
            n for n in app_notices if n["notice_type"] == "PLAIN_LANGUAGE_SUMMARY"
        ]
        assert len(summaries) == 1
        assert summaries[0]["application_id"] == app["id"]
        assert summaries[0]["is_plain_language"] is True
        account = get_account(account_id)
        assert account["collection_posture"] == "ASSISTANCE_HOLD", (
            "the account was in NOTICE_PERIOD at submit, so the freeze applies"
        )


class TestLogicalClockDefault:
    def test_unset_clock_stamps_startup_instant(self, api):
        """PRD §2.4: "All temporal reasoning in the system — statement windows,
        document deadlines, notification gates, reporting-year membership, and
        every recorded timestamp described as "now" — reads a server-side
        logical clock, never wall-clock time. Before any operator interaction
        the logical clock stands at exactly `2026-08-01T00:00:00Z`, and it
        never falls back to wall-clock time thereafter."

        Design: Corner/cross_cutting_layers/clock_default_is_fixed_startup_time
        """
        # NOTE: the clock is deliberately never set in this test.
        patient = create_patient(
            full_name="Clock Clara", date_of_birth="1990-01-01",
            ssn_last4="0055", mrn="MRN-CLK-1",
        )
        account = create_account(
            patient["id"], total_charges_cents=100000, insurance_paid_cents=0
        )
        notice = validate_success(api.issue_statement(account["id"], BILLING), 201)
        assert_notification_record(notice)
        assert_instant_eq(notice["issued_at"], "2026-08-01T00:00:00Z")
        refreshed = get_account(account["id"])
        assert_instant_eq(refreshed["first_statement_at"], "2026-08-01T00:00:00Z")


class TestPinnedPolicySnapshot:
    def test_superseded_policy_snapshot_still_governs(self, api):
        """PRD §2.7: "Exactly one policy is `ACTIVE` at a time. Applications
        pin the active policy's identity and version integer at submit
        (`policy_id` and `policy_version`), and every calculation for that
        application — FPL percentage, tier thresholds, deadlines, retroactive
        windows — must use that pinned snapshot even if the policy is later
        superseded. Supersession never rewrites a pinned snapshot."
        PRD §3.1: "On success the policy moves `DRAFT → ACTIVE`, and any other
        policy that was `ACTIVE` is transitioned to `SUPERSEDED` by the same
        operation; both the activated policy's `version` and the superseded
        policy's `version` increment by 1, and both records refresh
        `updated_at`."

        Design: Corner/cross_cutting_layers/superseded_policy_snapshot_still_governs_pinned_application
        """
        set_clock("2026-02-01T00:00:00Z")
        p1 = create_active_policy()  # base 1500000; version 2 after activation
        ctx = build_under_review_application(
            patient_name="Pin Pam", mrn="MRN-PIN-1", ssn_last4="0058",
            reported_income=3150000, members=(("SELF", 40),),
            accounts=((100000, 0),),
        )
        app_id = ctx["application"]["id"]
        # successor policy supersedes P1 before the determination is created
        p2 = create_policy(
            policy_code="FAP-2027",
            fpl_base_cents=1600000,
            fpl_increment_cents=550000,
            effective_from="2027-01-01T00:00:00Z",
            effective_to="2028-01-01T00:00:00Z",
        )
        validate_success(api.activate_policy(p2["id"], COMPLIANCE))
        upload_and_verify(
            app_id, ctx["members"][0]["id"], doc_type="TAX_RETURN",
            amount_cents=3150000,
        )
        upload_and_verify(
            app_id, ctx["members"][0]["id"], doc_type="IDENTITY", amount_cents=0,
            period_start="2026-01-01", period_end="2026-01-01",
        )
        det = create_determination(
            app_id, "VERIFIED_APPLICATION", [ctx["accounts"][0]["id"]]
        )
        assert det["policy_id"] == p1["id"], "the pinned snapshot is P1, not P2"
        assert det["policy_version"] == 2, "P1 was version 2 after its activation"
        # pinned base 1500000: 3150000*100/1500000 = 210.0000%
        # (the superseding base 1600000 would give 196.8750% and TIER_FULL)
        assert abs(float(det["fpl_pct_snapshot"]) - 210.0000) < 1e-6
        assert det["tier"] == "TIER_PARTIAL"
        # 50 + (300-210)*(100-50)/(300-200) = 50 + 90*50/100 = 95.00
        assert abs(float(det["discount_pct"]) - 95.00) < 1e-6
