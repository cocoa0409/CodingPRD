"""Write-off approval guards: aging, statement cycle, active plan, partial
amounts, cost report year, segregation of duties, screening currency, and
re-approval of a posted write-off."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_write_off_payload,
    create_account,
    create_evaluated_screening,
    create_pending_screening,
    create_pending_write_off,
    create_plan,
    issue_statements,
    make_officer_headers,
    read_account,
    setup_posted_bad_debt_writeoff,
    validate_error,
    validate_success,
)

COLLECTOR = TEST_USERS["collector_headers"]
OFFICER = TEST_USERS["officer_headers"]


class TestBadDebtApprovalGuards:
    def test_bad_debt_approval_before_120_days_rejected(self, api):
        """PRD §3.9: "For `BAD_DEBT`, the account must be in `BUCKET_120_PLUS`
        at approval time (else `ERR_WRITE_OFF_BEFORE_120_DAYS`)"

        Liability date 2026-06-15 is 47 days before the boot clock, so the
        account is in BUCKET_30 with the statement-cycle minimum already met.

        Design: Corner/validations/bad_debt_writeoff_before_120_days_rejected
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-06-15",
            patient_mrn="MRN-N4", patient_name="N4")
        issue_statements(account["id"], count=3)
        write_off = create_pending_write_off(
            account["id"], write_off_kind="BAD_DEBT",
            medicare_cost_report_year=2026)

        resp = api.approve_write_off(
            write_off["id"],
            approve_write_off_payload(read_account(account["id"])["version"]),
            make_officer_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_WRITE_OFF_BEFORE_120_DAYS)

    def test_active_payment_plan_blocks_writeoff(self, api):
        """PRD §3.9: "a bad-debt write-off taken directly from `OPEN`
        additionally requires that no `ACTIVE` payment plan exist for the
        account (else `ERR_ACTIVE_PAYMENT_PLAN_BLOCKS_WRITE_OFF`)"

        Design: Corner/validations/active_payment_plan_blocks_bad_debt_writeoff
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-N5", patient_name="N5")
        issue_statements(account["id"], count=3)
        create_plan(account["id"], installment_amount_cents=25000,
                    installment_count=4, first_installment_due="2026-02-01")
        write_off = create_pending_write_off(
            account["id"], write_off_kind="BAD_DEBT",
            medicare_cost_report_year=2026)

        resp = api.approve_write_off(
            write_off["id"],
            approve_write_off_payload(read_account(account["id"])["version"]),
            make_officer_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_ACTIVE_PAYMENT_PLAN_BLOCKS_WRITE_OFF)

    def test_explicit_partial_amount_writeoff_rejected(self, api):
        """PRD §3.9: "Only full-balance write-offs exist: the written-off
        `amount_cents` is always a snapshot of the account's entire
        `current_balance_cents` at the moment of approval, and a request
        carrying an explicit partial amount is rejected with
        `ERR_PARTIAL_WRITE_OFF_NOT_SUPPORTED`."

        Design: Corner/validations/partial_writeoff_attempt_rejected
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-N6", patient_name="N6")
        resp = api.create_write_off(
            {"account_id": account["id"], "write_off_kind": "BAD_DEBT",
             "medicare_cost_report_year": 2026, "amount_cents": 10000},
            COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_PARTIAL_WRITE_OFF_NOT_SUPPORTED)

    def test_cost_report_year_in_future_rejected(self, api):
        """PRD §3.9: "For a `BAD_DEBT` write-off, the cost report year must be
        no earlier than the calendar year of the `guarantor_liability_date` and
        no later than the calendar year of the logical clock at approval time,
        else `ERR_INVALID_COST_REPORT_YEAR`."

        The boot clock sits in calendar year 2026, so a 2027 cost report year is
        out of window.

        Design: Corner/validations/invalid_cost_report_year_in_future
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-N7", patient_name="N7")
        resp = api.create_write_off(
            {"account_id": account["id"], "write_off_kind": "BAD_DEBT",
             "medicare_cost_report_year": 2027},
            COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_COST_REPORT_YEAR)


class TestSegregationOfDutiesOnApproval:
    def test_writeoff_creator_cannot_approve(self, api):
        """PRD §3.9: "The approving officer's `X-User-ID` must differ from the
        creator's — the same principal may not both request and approve a
        write-off, and a violation is `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

        Design: Corner/validations/segregation_of_duties_creator_cannot_approve
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-N2", patient_name="N2",
            headers=make_officer_headers("officer-1"))
        issue_statements(account["id"], count=3)
        write_off = create_pending_write_off(
            account["id"], creator_headers=make_officer_headers("officer-1"),
            write_off_kind="BAD_DEBT", medicare_cost_report_year=2026)

        resp = api.approve_write_off(
            write_off["id"],
            approve_write_off_payload(read_account(account["id"])["version"]),
            make_officer_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        unchanged = validate_success(api.get_write_off(write_off["id"], OFFICER), 200)
        assert unchanged["status"] == "PENDING_APPROVAL"


class TestScreeningCurrency:
    def test_superseded_screening_blocks_charity_writeoff(self, api):
        """PRD §3.9: "For `CHARITY_CARE`, the referenced screening must still be
        `EVALUATED` with an outcome of `FULL_CHARITY` or `PARTIAL_CHARITY` at
        approval time; a screening that has been superseded, already applied, or
        evaluated ineligible fails with `ERR_SCREENING_NOT_CURRENT`."
        PRD §3.3: "any earlier screening for the same account that is still
        `PENDING` or `EVALUATED` is automatically transitioned to `SUPERSEDED`."

        The write-off references the first screening; a second screening then
        supersedes it before approval.

        Design: Difficulty/cross_entity_state_dependency/writeoff_approval_depends_on_screening_state
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date="2026-06-01",
            patient_mrn="MRN-H1", patient_name="H1")
        screening_v1 = create_evaluated_screening(
            account["id"], household_size=1, household_income_cents=1500000)
        assert screening_v1["eligibility_outcome"] == "FULL_CHARITY"
        write_off = create_pending_write_off(
            account["id"], write_off_kind="CHARITY_CARE",
            screening_id=screening_v1["id"])

        # A newer screening on the same account supersedes v1.
        create_pending_screening(
            account["id"], screening_model="SCORE_BASED", third_party_score=800,
            household_size=None, household_income_cents=None)
        superseded = validate_success(
            api.get_screening(screening_v1["id"], COLLECTOR), 200)
        assert superseded["status"] == "SUPERSEDED"

        resp = api.approve_write_off(
            write_off["id"],
            approve_write_off_payload(read_account(account["id"])["version"]),
            make_officer_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CURRENT)
        unchanged = validate_success(api.get_write_off(write_off["id"], OFFICER), 200)
        assert unchanged["status"] == "PENDING_APPROVAL"

    def test_ineligible_screening_blocks_charity_writeoff(self, api):
        """PRD §3.9: "For `CHARITY_CARE`, the referenced screening must still be
        `EVALUATED` with an outcome of `FULL_CHARITY` or `PARTIAL_CHARITY` at
        approval time; a screening that has been superseded, already applied, or
        evaluated ineligible fails with `ERR_SCREENING_NOT_CURRENT`."

        A score of 500 is below 550, so the referenced screening evaluates
        NOT_ELIGIBLE and the charity-care approval is rejected.

        Design: Difficulty/cross_entity_state_dependency/writeoff_approval_depends_on_screening_state
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date="2026-06-01",
            patient_mrn="MRN-H3", patient_name="H3 Ineligible")
        screening = create_evaluated_screening(
            account["id"], screening_model="SCORE_BASED", third_party_score=500,
            household_size=None, household_income_cents=None)
        assert screening["eligibility_outcome"] == "NOT_ELIGIBLE"
        write_off = create_pending_write_off(
            account["id"], write_off_kind="CHARITY_CARE",
            screening_id=screening["id"])

        resp = api.approve_write_off(
            write_off["id"],
            approve_write_off_payload(read_account(account["id"])["version"]),
            make_officer_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CURRENT)


class TestReapprovalRejected:
    def test_approve_posted_writeoff_invalid_state(self, api):
        """PRD §3.9: "The write-off must still be `PENDING_APPROVAL`, else
        `ERR_INVALID_STATE`."

        The second approval carries a fresh expected_account_version and a
        different approver, so only the state precondition can fail.

        Design: Corner/state_machines/writeoff_approve_from_posted_returns_invalid_state
        """
        account, write_off = setup_posted_bad_debt_writeoff(
            balance_cents=50000, guarantor_liability_date="2026-01-01")
        assert write_off["status"] == "POSTED"

        resp = api.approve_write_off(
            write_off["id"],
            approve_write_off_payload(read_account(account["id"])["version"]),
            make_officer_headers("officer-2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
