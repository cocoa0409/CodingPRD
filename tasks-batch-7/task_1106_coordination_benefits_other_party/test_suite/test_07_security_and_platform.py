"""RBAC segregation of duties, optimistic concurrency, the logical clock, and
savings-period closure (PRD §2.1, §2.6, §2.7, §3.8)."""
from test_helpers import (
    TEST_USERS,
    assert_savings_period,
    create_config,
    create_member,
    create_savings_period_payload,
    create_verified_coverage,
    draft_determination,
    get_success_data,
    make_member_self_headers,
    set_clock,
    setup_repaid_claim_with_overpayment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ELIG = TEST_USERS["eligibility_analyst_headers"]
COB = TEST_USERS["cob_analyst_headers"]
EXAMINER = TEST_USERS["claims_examiner_headers"]
AUDITOR = TEST_USERS["cob_auditor_headers"]


class TestRBACSegregation:
    def test_member_self_cannot_verify_coverage(self, api):
        """PRD §2.1: "Once the headers are accepted, the role must also be
        permitted to invoke the specific endpoint; an attempt outside the role's
        grant is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." §4 grants
        coverage verification to COBAnalyst only; MemberSelf is limited to
        "responds to own surveys and reads own member record, coverages,
        surveys, and determinations" (§2.1).

        Design: Corner/validations/member_self_cannot_verify_coverage
        """
        create_config()
        member = create_member()
        coverage = create_verified_coverage(member["id"], verify=False)
        res = api.verify_coverage(
            member["id"], coverage["id"], make_member_self_headers(member["id"])
        )
        validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)

    def test_claim_examiner_cannot_close_claim(self, api):
        """PRD §2.1: "Once the headers are accepted, the role must also be
        permitted to invoke the specific endpoint; an attempt outside the role's
        grant is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." §4 grants claim
        closure to RecoverySpecialist ("Close a claim (terminal)"); §2.1 gives
        ClaimsExaminer no close grant.

        Design: Corner/validations/claim_examiner_cannot_close_claim
        """
        ctx = setup_repaid_claim_with_overpayment()
        assert ctx["claim"]["status"] == "REPAID"
        res = api.close_claim(ctx["claim"]["id"], EXAMINER)
        validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


class TestLogicalClock:
    def test_clock_default_is_2026_05_01(self, api):
        """PRD §2.6: "At server startup the logical clock reads
        2026-05-01T00:00:00Z, and the server must not fall back to wall-clock
        time under any circumstance." And §3.3: "the system records `sent_at` as
        the current logical clock and computes `due_at` as thirty days after
        `sent_at`."

        Design: Corner/endpoints/clock_default_is_2026_05_01
        """
        create_config()
        member = create_member()
        survey = get_success_data(api.create_survey(member["id"], COB))
        assert survey["sent_at"][:19] == "2026-05-01T00:00:00"
        assert survey["due_at"][:19] == "2026-05-31T00:00:00"


class TestSavingsPeriodClosure:
    def test_savings_period_close_snapshots_totals(self, api):
        """PRD §3.8: "Closing a period requires the current logical clock to be
        later than `period_end_date`; an attempt before the period has ended is
        rejected with `ERR_PERIOD_NOT_ENDED` (HTTP 409). At close, the period's
        three totals are snapshotted." With no activity inside the window the
        adjusted-claim tally is zero: "`total_claims_adjusted` counts the
        adjustments in `APPLIED` status whose `updated_at` falls inside the
        period."

        Design: Corner/endpoints/savings_period_close_snapshots_totals
        """
        create_config()
        set_clock("2026-01-01T00:00:00Z")
        period = get_success_data(api.create_savings_period(
            create_savings_period_payload(
                period_start_date="2026-01-01", period_end_date="2026-01-31"
            ),
            AUDITOR,
        ))
        assert period["posture"] == "OPEN"

        set_clock("2026-02-15T00:00:00Z")
        closed = validate_success(api.close_savings_period(period["id"], AUDITOR), 200)
        assert_savings_period(closed)
        assert closed["posture"] == "CLOSED"
        assert closed["total_claims_adjusted"] == 0
