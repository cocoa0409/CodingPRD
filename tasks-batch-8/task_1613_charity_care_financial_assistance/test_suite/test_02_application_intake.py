"""Application intake: creation state, household composition, submit gates,
withdrawal terminal lockdown."""
from test_helpers import (
    COUNSELOR,
    ApiErrorId,
    add_member,
    assert_assistance_application,
    assert_household_member,
    create_active_policy,
    create_application,
    create_patient,
    create_policy,
    finalize_determination,
    get_application,
    set_clock,
    setup_verified_application,
    create_determination,
    submit_application,
    validate_error,
    validate_success,
)


class TestApplicationCreation:
    def test_application_initial_state_is_draft(self, api):
        """PRD §3.3: "A `Patient` (for themselves) or a `FinancialCounselor` (on
        their behalf) opens an assistance application in `DRAFT` by naming the
        `patient_id`, the `screening_source` (`STANDARD` for a
        patient-initiated, document-verified path, or `PRESUMPTIVE` for a
        hospital-initiated non-responder path), and the self-reported figures
        `reported_annual_income_cents` and `reported_liquid_assets_cents` (both
        integer cents, at least zero)."
        PRD §3.3: "The application exposes `household_size` as the count of its
        member rows, recomputed as members are added."

        Design: Corner/state_machines/application_initial_state_is_draft
        """
        patient = create_patient(
            full_name="Init Iris", date_of_birth="1994-01-01",
            ssn_last4="0017", mrn="MRN-INIT-1",
        )
        resp = api.create_application(
            {
                "patient_id": patient["id"],
                "screening_source": "STANDARD",
                "reported_annual_income_cents": 1000000,
                "reported_liquid_assets_cents": 0,
            },
            COUNSELOR,
        )
        app = validate_success(resp, 201)
        assert_assistance_application(app)
        assert app["status"] == "DRAFT"
        assert app["household_size"] == 0
        assert app.get("submitted_at") is None, "submitted_at stamps only at submit (PRD §3.4)"
        assert app.get("policy_id") is None, "policy pins only at submit (PRD §3.4)"
        assert app["version"] == 1

    def test_duplicate_open_application_rejected(self, api):
        """PRD §3.3: "A patient may have at most one open application — that
        is, one application in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or
        `PENDING_DOCUMENTS` — and a second attempt is rejected with
        `ERR_DUPLICATE_OPEN_APPLICATION` (HTTP 409)."

        Design: Corner/entities/application_create_duplicate_open_application_rejected
        """
        patient = create_patient(
            full_name="Dup Dana", date_of_birth="1991-01-01",
            ssn_last4="0004", mrn="MRN-DUP-1",
        )
        create_application(
            patient["id"], screening_source="STANDARD",
            reported_annual_income_cents=1000000, reported_liquid_assets_cents=0,
        )
        resp = api.create_application(
            {
                "patient_id": patient["id"],
                "screening_source": "STANDARD",
                "reported_annual_income_cents": 1000000,
                "reported_liquid_assets_cents": 0,
            },
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_APPLICATION)


class TestHouseholdComposition:
    def test_household_members_counted(self, api):
        """PRD §3.3: "The application exposes `household_size` as the count of
        its member rows, recomputed as members are added. Exactly one `SELF`
        row is required before the application can be submitted."

        Design: Corner/entities/household_member_added_and_counted
        """
        patient = create_patient(
            full_name="House Helen", date_of_birth="1985-01-01",
            ssn_last4="0006", mrn="MRN-HH-1",
        )
        app = create_application(
            patient["id"], screening_source="STANDARD",
            reported_annual_income_cents=4000000, reported_liquid_assets_cents=0,
        )
        add_member(app["id"], full_name="House Helen", relationship="SELF", age=41)
        add_member(app["id"], full_name="Spouse Hank", relationship="SPOUSE", age=43)
        add_member(app["id"], full_name="Child Hope", relationship="CHILD", age=9)
        app = get_application(app["id"])
        assert app["household_size"] == 3, (
            "SELF + SPOUSE + CHILD member rows count to household_size 3"
        )

    def test_household_member_carries_no_version(self, api):
        """PRD §2.5: "Three resources are intentionally lighter.
        `HouseholdMember`, `PresumptiveScreening`, and `NotificationRecord`
        carry only `id` and `created_at`; both `updated_at` and `version` are
        absent from them, and nothing in the API reads or writes a version for
        these types."

        Design: Corner/entities/immutable_household_member_has_no_update_endpoint
        """
        patient = create_patient(
            full_name="Immute Ivan", date_of_birth="1985-02-01",
            ssn_last4="0007", mrn="MRN-IMM-1",
        )
        app = create_application(
            patient["id"], screening_source="STANDARD",
            reported_annual_income_cents=1000000, reported_liquid_assets_cents=0,
        )
        resp = api.add_member(
            app["id"],
            {"full_name": "Immute Ivan", "relationship": "SELF", "age": 41},
            COUNSELOR,
        )
        member = validate_success(resp, 201)
        assert_household_member(member)
        members = validate_success(api.list_members(app["id"], COUNSELOR))
        assert isinstance(members, list) and len(members) == 1
        assert members[0]["id"] == member["id"]


class TestSubmitGates:
    def test_submit_without_self_member_rejected(self, api):
        """PRD §3.4: "Submission — by the `Patient` themselves or a
        `FinancialCounselor` — enforces three checks: the application must be
        in `DRAFT` (`ERR_APPLICATION_NOT_DRAFT`, HTTP 409), at least one
        household member with `relationship` `SELF` must exist
        (`ERR_HOUSEHOLD_SELF_REQUIRED`, HTTP 422), and a policy with status
        `ACTIVE` must exist (`ERR_NO_ACTIVE_POLICY`, HTTP 409)."

        Design: Corner/validations/submit_without_self_member_rejected
        """
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        patient = create_patient(
            full_name="No Self", date_of_birth="1990-01-01",
            ssn_last4="0030", mrn="MRN-NSELF-1",
        )
        app = create_application(
            patient["id"], screening_source="STANDARD",
            reported_annual_income_cents=1000000, reported_liquid_assets_cents=0,
        )
        add_member(app["id"], full_name="Only Spouse", relationship="SPOUSE", age=40)
        resp = api.submit_application(app["id"], COUNSELOR)
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_SELF_REQUIRED)

    def test_submit_without_active_policy_rejected(self, api):
        """PRD §3.4: "Submission — by the `Patient` themselves or a
        `FinancialCounselor` — enforces three checks: the application must be
        in `DRAFT` (`ERR_APPLICATION_NOT_DRAFT`, HTTP 409), at least one
        household member with `relationship` `SELF` must exist
        (`ERR_HOUSEHOLD_SELF_REQUIRED`, HTTP 422), and a policy with status
        `ACTIVE` must exist (`ERR_NO_ACTIVE_POLICY`, HTTP 409)."

        Design: Corner/validations/submit_without_active_policy_rejected
        """
        create_policy(policy_code="FAP-DRAFT")  # never activated
        patient = create_patient(
            full_name="No Pol", date_of_birth="1990-01-01",
            ssn_last4="0031", mrn="MRN-NPOL-1",
        )
        app = create_application(
            patient["id"], screening_source="STANDARD",
            reported_annual_income_cents=1000000, reported_liquid_assets_cents=0,
        )
        add_member(app["id"], full_name="No Pol", relationship="SELF", age=40)
        resp = api.submit_application(app["id"], COUNSELOR)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_POLICY)

    def test_submit_from_submitted_rejected(self, api):
        """PRD §3.4: "Submission — by the `Patient` themselves or a
        `FinancialCounselor` — enforces three checks: the application must be
        in `DRAFT` (`ERR_APPLICATION_NOT_DRAFT`, HTTP 409), at least one
        household member with `relationship` `SELF` must exist
        (`ERR_HOUSEHOLD_SELF_REQUIRED`, HTTP 422), and a policy with status
        `ACTIVE` must exist (`ERR_NO_ACTIVE_POLICY`, HTTP 409)."

        Design: Corner/state_machines/submit_from_non_draft_rejected
        """
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        patient = create_patient(
            full_name="State Stan", date_of_birth="1986-01-01",
            ssn_last4="0008", mrn="MRN-ST-1",
        )
        app = create_application(
            patient["id"], screening_source="STANDARD",
            reported_annual_income_cents=1000000, reported_liquid_assets_cents=0,
        )
        add_member(app["id"], full_name="State Stan", relationship="SELF", age=40)
        submit_application(app["id"])
        resp = api.submit_application(app["id"], COUNSELOR)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DRAFT)


class TestReviewEntryAndWithdrawal:
    def test_begin_review_from_draft_rejected(self, api):
        """PRD §3.5: "A `FinancialCounselor` begins review of a `SUBMITTED`
        application, moving it to `UNDER_REVIEW` (a begin-review on anything
        else is `ERR_APPLICATION_NOT_SUBMITTED`)."

        Design: Corner/state_machines/begin_review_from_draft_rejected
        """
        patient = create_patient(
            full_name="Skip Sylvia", date_of_birth="1986-02-01",
            ssn_last4="0009", mrn="MRN-SKIP-1",
        )
        app = create_application(
            patient["id"], screening_source="STANDARD",
            reported_annual_income_cents=1000000, reported_liquid_assets_cents=0,
        )
        resp = api.begin_review(app["id"], COUNSELOR)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTED)

    def test_withdraw_from_denied_rejected(self, api):
        """PRD §3.4: "Withdrawal is available to the `Patient` (own) or a
        `FinancialCounselor` from any non-terminal state — `DRAFT`,
        `SUBMITTED`, `UNDER_REVIEW`, or `PENDING_DOCUMENTS` — optionally
        carrying a `reason`; attempting it on a terminal application is
        rejected with `ERR_APPLICATION_TERMINAL` (HTTP 409)."
        PRD §3.8: "with any tier other than `INELIGIBLE` the application moves
        `UNDER_REVIEW → APPROVED`, while an `INELIGIBLE` tier moves it
        `UNDER_REVIEW → DENIED` and releases every account of the patient from
        `ASSISTANCE_HOLD` back to `NOTICE_PERIOD`."

        Design: Corner/state_machines/withdraw_from_terminal_denied_rejected
        """
        ctx = setup_verified_application(
            patient_name="Term Tina", mrn="MRN-TERM-1", ssn_last4="0010",
            reported_income=6000000, tax_return_amount=6000000,
            accounts=((100000, 0),),
        )
        det = create_determination(
            ctx["application"]["id"], "VERIFIED_APPLICATION",
            [ctx["accounts"][0]["id"]],
        )
        assert det["tier"] == "INELIGIBLE", (
            "income 6000000 is 400.0000% of the size-1 guideline, above the 300 ceiling"
        )
        finalize_determination(det["id"])
        app = get_application(ctx["application"]["id"])
        assert app["status"] == "DENIED"
        resp = api.withdraw_application(app["id"], COUNSELOR, {})
        validate_error(resp, ApiErrorId.ERR_APPLICATION_TERMINAL)
