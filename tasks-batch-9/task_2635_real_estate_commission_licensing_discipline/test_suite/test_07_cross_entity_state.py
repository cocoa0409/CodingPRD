"""Rows whose legality lives entirely in the state of other entities."""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_ce_standing,
    assert_immutable_row,
    assert_posture,
)
from test_helpers.test_users import make_analyst_headers

CLOCK_START = "2026-08-01T00:00:00Z"


def _student_two_schools_and_one_pending_instructor(client):
    """An approved school with a still-pending teacher, and a second approved school."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name="Harbor Realty Group",
        broker_name="Dana Broker",
        trust_account_required=False,
        open_escrow=False,
    )
    student = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], "Rae Field"
    )
    coastal = fixtures.approve_provider(
        client, fixtures.register_provider(client, "Coastal RE Academy")["id"]
    )
    tia = fixtures.register_instructor(client, coastal["id"], "Tia Teach", "SUBJECT_EXPERT")
    inland = fixtures.approve_provider(
        client, fixtures.register_provider(client, "Inland CE Institute")["id"]
    )
    return {"student": student, "coastal": coastal, "instructor": tia, "inland": inland}


def _report_completion(client, world, education_provider_id):
    return client.create_course_completion(
        factories.course_completion_payload(
            world["student"]["id"],
            world["instructor"]["id"],
            education_provider_id,
            credit_hours=12,
            completed_on="2026-08-01",
            course_type="CE_CORE",
        ),
        make_analyst_headers(),
    )


class TestCompletionNeedsBothOtherEntitiesInTheRightState:
    """The completion row carries no state, so it borrows two."""

    def test_a_school_cannot_claim_another_schools_teacher(self, client):
        """The referential gate is reached before either approval gate.

        The PRD says "The supplied `education_provider_id` must equal the
        instructor's own `education_provider_id`, or the report is refused with
        `ERR_INSTRUCTOR_PROVIDER_MISMATCH`; a school cannot claim another
        school's teacher."

        Design: Difficulty/cross_entity_state_dependency/course_completion_gated_on_both_provider_and_instructor_approval_states
        """
        world = _student_two_schools_and_one_pending_instructor(client)
        assert world["instructor"]["status"] == "PENDING"

        validate_error(
            _report_completion(client, world, world["inland"]["id"]),
            "ERR_INSTRUCTOR_PROVIDER_MISMATCH",
            expected_status=422,
        )
        assert_ce_standing(
            fixtures.read_licensee(client, world["student"]["id"]), valid=0, required=12
        )

    def test_the_right_school_with_a_pending_teacher_is_still_refused(self, client):
        """With the mismatch removed the instructor's own state answers.

        The PRD says "And the instructor's `status` must be `APPROVED` at the
        moment of reporting, or the report is refused with
        `ERR_INSTRUCTOR_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/course_completion_gated_on_both_provider_and_instructor_approval_states
        """
        world = _student_two_schools_and_one_pending_instructor(client)
        assert world["coastal"]["status"] == "APPROVED"

        validate_error(
            _report_completion(client, world, world["coastal"]["id"]),
            "ERR_INSTRUCTOR_NOT_APPROVED",
            expected_status=409,
        )
        assert_ce_standing(
            fixtures.read_licensee(client, world["student"]["id"]), valid=0, required=12
        )

    def test_the_identical_body_is_accepted_once_the_teacher_is_approved(self, client):
        """Nothing in the payload changes; only another entity's state does.

        The PRD says "A recorded completion starts with `credit_status` `VALID`
        and `invalidated_at` null."

        Design: Difficulty/cross_entity_state_dependency/course_completion_gated_on_both_provider_and_instructor_approval_states
        """
        world = _student_two_schools_and_one_pending_instructor(client)
        validate_error(
            _report_completion(client, world, world["coastal"]["id"]),
            "ERR_INSTRUCTOR_NOT_APPROVED",
        )

        approved = fixtures.approve_instructor(client, world["instructor"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_at"] == CLOCK_START

        completion = validate_success(
            _report_completion(client, world, world["coastal"]["id"]), expected_status=201
        )
        assert completion["credit_status"] == "VALID"
        assert completion["invalidated_at"] is None
        assert_immutable_row(completion)

        student = fixtures.read_licensee(client, world["student"]["id"])
        assert_ce_standing(student, valid=12, required=12)
        assert student["ce_deficient"] is False

    def test_an_unapproved_school_cannot_even_enrol_the_teacher(self, client):
        """Which is why a pending school's completions can never exist at all.

        The PRD says "Enrolment requires the owning provider's `status` to be
        `APPROVED`; a `PENDING`, `PROBATION` or `SUSPENDED` provider may neither
        enrol nor approve instructors, and the attempt is refused with
        `ERR_PROVIDER_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/course_completion_gated_on_both_provider_and_instructor_approval_states
        """
        pending = fixtures.register_provider(client, "Ridgeline Realty School")
        assert pending["status"] == "PENDING"

        validate_error(
            client.create_instructor(
                pending["id"],
                factories.instructor_payload("Vic Visitor", "SUBJECT_EXPERT"),
                make_analyst_headers(),
            ),
            "ERR_PROVIDER_NOT_APPROVED",
            expected_status=409,
        )


def _approved_team_name_led_by_a_salesperson(client):
    """A team name approved while its lead was active and sponsored by this firm."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name="Harbor Realty Group",
        broker_name="Dana Broker",
        trust_account_required=False,
        open_escrow=False,
    )
    brokerage_id = firm["brokerage"]["id"]
    lead = fixtures.affiliate_new_salesperson(
        client, brokerage_id, firm["broker"]["id"], "Rae Field"
    )
    submitted = fixtures.submit_advertising_name(
        client,
        brokerage_id,
        "Rae Field Partners",
        kind="TEAM",
        team_lead_licensee_id=lead["id"],
    )
    approved = fixtures.review_advertising_name(client, submitted["id"], "APPROVE")
    return {"brokerage_id": brokerage_id, "lead": lead, "name": approved}


class TestTeamNameTracksItsLeadInBothDirections:
    """Approval needs a live lead, and losing the lead undoes the approval."""

    def test_approval_is_legal_while_the_lead_is_active_and_sponsored_here(self, client):
        """The gate is re-evaluated at review time against the lead's live state.

        The PRD says "and for a team the lead must still be `ACTIVE` and still
        sponsored by this brokerage, or `ERR_TEAM_LEAD_NOT_AFFILIATED`, and the
        name must contain none of the forbidden team words, or
        `ERR_TEAM_NAME_IMPLIES_BROKERAGE`."

        Design: Difficulty/cross_entity_state_dependency/advertising_team_name_tracks_its_team_lead_licensee_state_in_both_directions
        """
        world = _approved_team_name_led_by_a_salesperson(client)
        assert world["name"]["status"] == "APPROVED"
        assert world["name"]["normalized_name"] == "RAEFIELDPARTNERS"
        assert world["name"]["rejection_reason"] is None
        assert fixtures.read_licensee(client, world["lead"]["id"])["license_status"] == "ACTIVE"

    def test_parking_the_lead_retroactively_revokes_the_name(self, client):
        """No call touches the advertising name, yet the name changes state.

        The PRD says "When a team lead transfers away or loses `ACTIVE`
        standing, the team's `APPROVED` name is revoked by the system with
        `rejection_reason` `TEAM_LEAD_INELIGIBLE`, again with no
        `reviewed_by_user_id`."

        Design: Difficulty/cross_entity_state_dependency/advertising_team_name_tracks_its_team_lead_licensee_state_in_both_directions
        """
        world = _approved_team_name_led_by_a_salesperson(client)

        parked = fixtures.go_inactive(client, world["lead"]["id"])
        assert parked["license_status"] == "INACTIVE"
        assert parked["inactive_since"] == CLOCK_START

        name = fixtures.read_advertising_name(client, world["name"]["id"])
        assert name["status"] == "REVOKED"
        assert name["rejection_reason"] == "TEAM_LEAD_INELIGIBLE"
        assert name["reviewed_by_user_id"] is None

        brokerage = fixtures.read_brokerage(client, world["brokerage_id"])
        assert brokerage["affiliated_licensee_count"] == 1, "only the designated broker remains"

    def test_a_fresh_submission_naming_the_parked_lead_is_refused_at_intake(self, client):
        """The dependency is enforced on the way in as well as on the way out.

        The PRD says "For a `DBA` or a `BRANCH` the `team_lead_licensee_id`
        **must be null**; supplying one is refused with
        `ERR_TEAM_LEAD_NOT_AFFILIATED`, the same error that answers a team whose
        lead is missing, whose `license_status` is not `ACTIVE`, or whose
        `sponsoring_brokerage_id` is not the brokerage the name is registered
        under."

        Design: Difficulty/cross_entity_state_dependency/advertising_team_name_tracks_its_team_lead_licensee_state_in_both_directions
        """
        world = _approved_team_name_led_by_a_salesperson(client)
        fixtures.go_inactive(client, world["lead"]["id"])

        validate_error(
            client.create_advertising_name(
                factories.advertising_name_payload(
                    world["brokerage_id"],
                    "Rae Field Group",
                    kind="TEAM",
                    team_lead_licensee_id=world["lead"]["id"],
                ),
                make_analyst_headers(),
            ),
            "ERR_TEAM_LEAD_NOT_AFFILIATED",
            expected_status=422,
        )

        rows = fixtures.names_for_brokerage(client, world["brokerage_id"])
        assert len(rows) == 1, "the refused submission created no row"
        assert rows[0]["normalized_name"] == "RAEFIELDPARTNERS"


class TestActivationNeedsAnOpenEscrowAccountOfTheRightType:
    """Existence is not enough: the child's type and state are both gates."""

    def test_a_firm_with_no_trust_account_at_all_cannot_activate(self, client):
        """The declared requirement is enforced against the accounts that exist.

        The PRD says "And when `trust_account_required` is true, at least one
        trust account belonging to this brokerage with `account_type` `ESCROW`
        and `status` `OPEN` must already exist; otherwise activation is refused
        with `ERR_TRUST_ACCOUNT_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/brokerage_activation_gated_on_an_open_escrow_trust_account_of_the_right_type
        """
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", "Cal Broker")
        brokerage = fixtures.register_brokerage(client, broker["id"], "Cove Realty", True, 5)

        validate_error(
            client.activate_brokerage(brokerage["id"], make_analyst_headers()),
            "ERR_TRUST_ACCOUNT_REQUIRED",
            expected_status=409,
        )
        assert fixtures.read_brokerage(client, brokerage["id"])["status"] == "PENDING"
        assert fixtures.read_licensee(client, broker["id"])["license_status"] == "EXAM_PASSED"

    def test_an_open_security_deposit_account_does_not_satisfy_the_gate(self, client):
        """The type half of the gate fails even though the state half passes.

        The PRD says "Trust accounts may be opened against a `PENDING`
        brokerage — indeed they must be, when `trust_account_required` is true
        — by a `Broker` or a `LicensingAnalyst` who supplies the depository
        institution as `bank_name` and the `account_type`, which is `ESCROW` for
        escrow money or `SECURITY_DEPOSIT` for tenant security deposits."

        Design: Difficulty/cross_entity_state_dependency/brokerage_activation_gated_on_an_open_escrow_trust_account_of_the_right_type
        """
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", "Cal Broker")
        brokerage = fixtures.register_brokerage(client, broker["id"], "Cove Realty", True, 5)
        deposits = fixtures.open_trust_account(
            client, brokerage["id"], account_type="SECURITY_DEPOSIT"
        )
        assert deposits["status"] == "OPEN"
        assert deposits["account_type"] == "SECURITY_DEPOSIT"

        validate_error(
            client.activate_brokerage(brokerage["id"], make_analyst_headers()),
            "ERR_TRUST_ACCOUNT_REQUIRED",
        )
        assert fixtures.read_brokerage(client, brokerage["id"])["status"] == "PENDING"
        assert fixtures.read_licensee(client, broker["id"])["license_status"] == "EXAM_PASSED"

    def test_an_open_escrow_account_unlocks_activation_but_not_the_licence(self, client):
        """Activation is the firm's transition; the licence rides on affiliation.

        The PRD says "It is important to understand what activation does **not**
        do: it does not issue the designated broker's licence. An `EXAM_PASSED`
        broker becomes `ACTIVE` only by being affiliated, naming themselves as
        their own supervising broker, and that affiliation — not the activation
        — is what first raises `affiliated_licensee_count` above 0."

        Design: Difficulty/cross_entity_state_dependency/brokerage_activation_gated_on_an_open_escrow_trust_account_of_the_right_type
        """
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", "Cal Broker")
        brokerage = fixtures.register_brokerage(client, broker["id"], "Cove Realty", True, 5)
        fixtures.open_trust_account(client, brokerage["id"], account_type="SECURITY_DEPOSIT")
        validate_error(
            client.activate_brokerage(brokerage["id"], make_analyst_headers()),
            "ERR_TRUST_ACCOUNT_REQUIRED",
        )

        escrow = fixtures.open_trust_account(client, brokerage["id"], account_type="ESCROW")
        assert escrow["shortage_cents"] == 0
        assert escrow["book_available_cents"] == 0

        activated = validate_success(
            client.activate_brokerage(brokerage["id"], make_analyst_headers())
        )
        assert activated["status"] == "ACTIVE"
        assert_posture(activated, "COMPLIANT")
        assert activated["affiliated_licensee_count"] == 0
        assert fixtures.read_licensee(client, broker["id"])["license_status"] == "EXAM_PASSED"

        seated = fixtures.affiliate(client, broker["id"], brokerage["id"], broker["id"])
        assert seated["license_status"] == "ACTIVE"
        assert seated["sponsoring_brokerage_id"] == brokerage["id"]
        assert seated["supervising_broker_id"] == broker["id"]
        assert seated["license_expires_at"] == "2028-07-31T00:00:00Z"
        assert fixtures.read_brokerage(client, brokerage["id"])[
            "affiliated_licensee_count"
        ] == 1
