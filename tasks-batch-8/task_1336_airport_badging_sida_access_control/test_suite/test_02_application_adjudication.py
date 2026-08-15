"""Background adjudication, the readiness cycle, and application expiry."""
from test_helpers import (
    BO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_badge,
    create_applicant,
    create_sponsor,
    get_application,
    issue_badge,
    make_sponsor_signatory_headers,
    open_application,
    record_chrc_fail,
    record_chrc_pass,
    record_chrc_payload,
    record_sta_cleared,
    record_sta_payload,
    record_training,
    set_clock,
    validate_error,
    validate_success,
)


def _submitted_application(sponsor_code="AF", badge_class="SIDA"):
    sponsor = create_sponsor(sponsor_code=sponsor_code)
    applicant = create_applicant(sponsor["id"])
    app = open_application(applicant["id"], sponsor["id"],
                           badge_class=badge_class)
    return sponsor, applicant, app


class TestAdjudicationTransitions:

    def test_record_sta_on_submitted_application_rejected(self):
        """PRD section 3.2: "When the TSA returns the threat assessment, the
        officer records its `outcome` against an application that must be
        `STA_PENDING`."
        PRD section 2.6: "The target entity must be in the state the
        transition requires, failing with the corresponding state error such
        as ... `ERR_APPLICATION_NOT_OPEN` ...".

        Design: Corner/state_machines/record_sta_on_submitted_application_rejected
        """
        _, _, app = _submitted_application()
        resp = api_client.record_sta_result(app["id"], record_sta_payload("CLEARED"), BO)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_OPEN)
        assert get_application(app["id"])["status"] == "SUBMITTED", \
            "a rejected step must not move the application"

    def test_record_chrc_unknown_application_returns_404(self):
        """PRD section 2.6: "Path identifiers are validated left to right and
        body references must exist — each unknown resource yields its specific
        not-found error (`ERR_SPONSOR_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_BADGE_NOT_FOUND`,
        `ERR_ESCORT_PRIVILEGE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, or
        `ERR_AUDIT_CYCLE_NOT_FOUND`)".

        Design: Corner/entities/record_chrc_unknown_application_returns_404
        """
        resp = api_client.record_chrc(
            NON_EXISTENT_UUID, record_chrc_payload("PASS"), BO)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)

    def test_chrc_fail_denies_application_with_reason(self):
        """PRD section 3.2: "A `FAIL` outcome instead stamps `chrc_outcome`
        as `FAIL`, sets `denial_reason` to `CHRC_FAILED`, and terminates the
        application in `DENIED`."

        Design: Corner/state_machines/chrc_fail_denies_application_with_reason
        """
        _, _, app = _submitted_application()
        data = record_chrc_fail(app["id"])
        assert data["status"] == "DENIED"
        assert data["denial_reason"] == "CHRC_FAILED"
        assert data["chrc_outcome"] == "FAIL"

    def test_sta_denied_denies_application_with_reason(self):
        """PRD section 3.2: "A `DENIED` result stamps `sta_outcome` as
        `DENIED`, sets `denial_reason` to `STA_DENIED`, and terminates the
        application in `DENIED`."

        Design: Corner/state_machines/sta_denied_denies_application_with_reason
        """
        _, _, app = _submitted_application()
        record_chrc_pass(app["id"])
        resp = api_client.record_sta_result(app["id"], record_sta_payload("DENIED"), BO)
        data = validate_success(resp)
        assert data["status"] == "DENIED"
        assert data["denial_reason"] == "STA_DENIED"
        assert data["sta_outcome"] == "DENIED"

    def test_record_chrc_invalid_enum_rejected(self):
        """PRD section 2.6: "missing required fields, unknown enum values,
        malformed datetimes, an `escortee_count` that is negative, a
        `max_escortees` outside the permitted range, or an audit window whose
        end is not after its start are rejected here as `ERR_INVALID_REQUEST`."

        Design: Corner/validations/record_chrc_invalid_enum_rejected
        """
        _, _, app = _submitted_application()
        resp = api_client.record_chrc(
            app["id"],
            record_chrc_payload(outcome="MAYBE"),
            BO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert get_application(app["id"])["status"] == "SUBMITTED", \
            "an invalid enum must not transition the application"

    def test_withdraw_denied_application_rejected(self):
        """PRD section 3.2: "a terminal application rejects the attempt with
        `ERR_APPLICATION_NOT_OPEN`".

        Design: Corner/state_machines/withdraw_denied_application_rejected
        """
        sponsor, _, app = _submitted_application()
        record_chrc_fail(app["id"])
        resp = api_client.withdraw_application(
            app["id"], make_sponsor_signatory_headers(sponsor["id"]))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_OPEN)


class TestReadyGateOnIssuance:

    def test_issuance_blocked_while_pending_requirements(self):
        """PRD section 3.4: "The application itself must be `READY`, else
        `ERR_APPLICATION_NOT_READY`."

        Design: Difficulty/cross_entity_state_dependency/issue_blocked_until_application_ready
        """
        sponsor = create_sponsor(sponsor_code="XD", name="XpressDolly")
        applicant = create_applicant(sponsor["id"], full_name="Vera Wynn",
                                     date_of_birth="1993-08-26",
                                     government_id_number="G9401")
        app = open_application(applicant["id"], sponsor["id"],
                               badge_class="STERILE")
        record_chrc_pass(app["id"])
        sta = record_sta_cleared(app["id"])
        assert sta["status"] == "PENDING_REQUIREMENTS", \
            "no completions on file: the application rests at the waypoint"

        resp = api_client.issue_badge(app["id"], {"badge_number": "B1101"}, BO)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_READY)

    def test_issuance_succeeds_after_training_promotes_to_ready(self):
        """PRD section 3.2: "An application in `PENDING_REQUIREMENTS` is
        promoted to `READY` the moment every required course holds a strictly
        current completion".
        PRD section 3.4: "The application itself must be `READY`, else
        `ERR_APPLICATION_NOT_READY`."

        Design: Difficulty/cross_entity_state_dependency/issue_blocked_until_application_ready
        """
        sponsor = create_sponsor(sponsor_code="XD", name="XpressDolly")
        applicant = create_applicant(sponsor["id"], full_name="Vera Wynn",
                                     date_of_birth="1993-08-26",
                                     government_id_number="G9401")
        app = open_application(applicant["id"], sponsor["id"],
                               badge_class="STERILE")
        record_chrc_pass(app["id"])
        record_sta_cleared(app["id"])

        blocked = api_client.issue_badge(app["id"], {"badge_number": "B1101"}, BO)
        validate_error(blocked, ApiErrorId.ERR_APPLICATION_NOT_READY)

        record_training(applicant["id"], "STERILE_INITIAL",
                        completed_at="2026-06-01T00:00:00Z")
        assert get_application(app["id"])["status"] == "READY"

        badge = issue_badge(app["id"], "B1101")
        assert_badge(badge)
        assert badge["status"] == "ACTIVE"
        assert badge["expires_at"] == "2027-06-01T00:00:00Z", \
            "min(issued_at + 24 months, STERILE_INITIAL expiry 2027-06-01)"


class TestReadyRegressionLoop:

    def test_ready_regresses_to_pending_when_training_lapses(self):
        """PRD section 3.2: "an application already in `READY` regresses to
        `PENDING_REQUIREMENTS` the moment some required course no longer holds
        one."
        PRD section 3.3: "A completion is **strictly current** at a given
        instant when its `expires_at` lies strictly in the future — a
        completion expiring exactly now has already lapsed."

        Design: Difficulty/non_linear_state_machine/application_ready_regression_loop
        """
        sponsor = create_sponsor(sponsor_code="RG", name="RampGroup")
        applicant = create_applicant(sponsor["id"], full_name="Kara Loh",
                                     date_of_birth="1996-08-08",
                                     government_id_number="G6001")
        app = open_application(applicant["id"], sponsor["id"],
                               badge_class="STERILE")
        record_chrc_pass(app["id"])
        record_sta_cleared(app["id"])

        record_training(applicant["id"], "STERILE_INITIAL",
                        completed_at="2025-09-01T00:00:00Z")
        assert get_application(app["id"])["status"] == "READY", \
            "completion expiring 2026-09-01 is strictly current at 2026-08-01"

        set_clock("2026-09-01T00:00:00Z")
        assert get_application(app["id"])["status"] == "PENDING_REQUIREMENTS", \
            "at exactly expires_at the completion has lapsed"

    def test_pending_repromotes_to_ready_and_issues_after_fresh_completion(self):
        """PRD section 3.2: "This promotion-and-regression pair forms the
        `PENDING_REQUIREMENTS` ↔ `READY` cycle, and an applicant whose
        coursework lapses the night before issuance will find their
        application back at the waypoint after the next clock set."

        Design: Difficulty/non_linear_state_machine/application_ready_regression_loop
        """
        sponsor = create_sponsor(sponsor_code="RG", name="RampGroup")
        applicant = create_applicant(sponsor["id"], full_name="Kara Loh",
                                     date_of_birth="1996-08-08",
                                     government_id_number="G6001")
        app = open_application(applicant["id"], sponsor["id"],
                               badge_class="STERILE")
        record_chrc_pass(app["id"])
        record_sta_cleared(app["id"])
        record_training(applicant["id"], "STERILE_INITIAL",
                        completed_at="2025-09-01T00:00:00Z")
        assert get_application(app["id"])["status"] == "READY"

        set_clock("2026-09-01T00:00:00Z")
        assert get_application(app["id"])["status"] == "PENDING_REQUIREMENTS"

        record_training(applicant["id"], "STERILE_INITIAL",
                        completed_at="2026-09-01T00:00:00Z")
        assert get_application(app["id"])["status"] == "READY", \
            "a fresh completion re-promotes the application"

        badge = issue_badge(app["id"], "B502")
        assert badge["status"] == "ACTIVE"
        assert badge["expires_at"] == "2027-09-01T00:00:00Z"


class TestApplicationExpirySweep:

    def test_application_expiry_sweep_at_exact_deadline(self):
        """PRD section 3.1: "an application that has not reached a terminal
        state by that deadline is swept to `EXPIRED` the next time the clock
        is set, with the boundary inclusive."

        Design: Corner/calculations/application_expiry_sweep_at_exact_deadline
        """
        _, _, app = _submitted_application()

        set_clock("2026-10-29T00:00:00Z")
        assert get_application(app["id"])["status"] == "SUBMITTED", \
            "one day before application_expires_at the application is untouched"

        set_clock("2026-10-30T00:00:00Z")
        assert get_application(app["id"])["status"] == "EXPIRED", \
            "at exactly application_expires_at the sweep is inclusive"
