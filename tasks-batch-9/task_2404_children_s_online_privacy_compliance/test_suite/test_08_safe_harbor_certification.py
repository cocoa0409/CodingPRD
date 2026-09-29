"""Safe harbor: the bounded remediation loop and the program's own approval flag."""

from test_helpers import (
    STARTUP_CLOCK,
    api_client,
    assert_instant,
    create_assessment,
    create_program,
    create_service,
    certify_assessment,
    make_assessor_headers,
    make_certifier_headers,
    mixed_audience_service,
    read_assessment,
    read_service,
    set_assessment_status,
    submit_assessment,
    validate_error,
)

ASSESSOR = make_assessor_headers("assessor-1")
CERTIFIER = make_certifier_headers("certifier-1")


def _program_and_assessment(regulator_approved: bool = True, service=None) -> dict:
    """A program, a service and one `DRAFT` assessment for 2026 opened by assessor-1."""
    service = service or create_service(name="Rocket Readers")
    program = create_program(
        program_name="KidTrust Seal",
        regulator_approved=regulator_approved,
        annual_assessment_required=True,
        assessment_validity_days=365,
        assessment_grace_days=30,
    )
    assessment = create_assessment(service["id"], program["id"], 2026, ASSESSOR)
    return {
        "service_id": service["id"],
        "program_id": program["id"],
        "assessment_id": assessment["id"],
        "assessment": assessment,
    }


class TestRemediationLoopBoundedThenCertified:
    """Two rounds are allowed, the third is refused, and the row still certifies."""

    def test_01_the_first_two_remediation_rounds_are_accepted(self):
        """Each send-back advances the round counter by one.

        "It may send the assessment back by moving it `SUBMITTED → REMEDIATION_REQUIRED`,
        optionally recording a `remediation_note`; this transition is certifier-only ... and
        advances `remediation_round` by one." Resubmission "overwrites the stored count with
        the new value."

        Design: Difficulty/non_linear_state_machine/assessment_remediation_cycle_bounded_then_certified
        """
        fixture = _program_and_assessment()
        assert fixture["assessment"]["preparer_user_id"] == "assessor-1", (
            "the opening assessor is recorded as the preparer, got "
            f"{fixture['assessment']['preparer_user_id']}"
        )
        assert fixture["assessment"]["remediation_round"] == 0

        submit_assessment(fixture["assessment_id"], 2, ASSESSOR)
        first = set_assessment_status(
            fixture["assessment_id"],
            "REMEDIATION_REQUIRED",
            CERTIFIER,
            remediation_note="round 1: notice missing retention language",
        )
        assert first["remediation_round"] == 1, (
            f"the first send-back is round 1, got {first['remediation_round']}"
        )

        resubmitted = set_assessment_status(
            fixture["assessment_id"], "SUBMITTED", ASSESSOR, findings_open_count=1
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["findings_open_count"] == 1, (
            f"the resubmission overwrites the stored count, got {resubmitted['findings_open_count']}"
        )

        second = set_assessment_status(
            fixture["assessment_id"],
            "REMEDIATION_REQUIRED",
            CERTIFIER,
            remediation_note="round 2: age screen still prefilled",
        )
        assert second["remediation_round"] == 2, (
            f"the second send-back is round 2, got {second['remediation_round']}"
        )

    def test_02_a_third_remediation_attempt_is_refused_and_the_row_stays_submitted(self):
        """The cap closes the loop without moving the assessment.

        The send-back "is permitted only while `remediation_round` is strictly below 2, else
        `ERR_REMEDIATION_ROUNDS_EXHAUSTED` (HTTP 409)", and each cap is "compared against the
        counter the corresponding entity carries, with re-entry permitted only while the
        counter is strictly below the cap."

        Design: Difficulty/non_linear_state_machine/assessment_remediation_cycle_bounded_then_certified
        """
        fixture = _program_and_assessment()
        assessment_id = fixture["assessment_id"]
        submit_assessment(assessment_id, 2, ASSESSOR)
        set_assessment_status(assessment_id, "REMEDIATION_REQUIRED", CERTIFIER)
        set_assessment_status(assessment_id, "SUBMITTED", ASSESSOR, findings_open_count=1)
        set_assessment_status(assessment_id, "REMEDIATION_REQUIRED", CERTIFIER)
        set_assessment_status(assessment_id, "SUBMITTED", ASSESSOR, findings_open_count=0)

        validate_error(
            api_client.set_safe_harbor_assessment_status(
                assessment_id,
                {"to_status": "REMEDIATION_REQUIRED", "remediation_note": "round 3 attempt"},
                CERTIFIER,
            ),
            "ERR_REMEDIATION_ROUNDS_EXHAUSTED",
        )

        stored = read_assessment(assessment_id)
        assert stored["status"] == "SUBMITTED", (
            f"the refused send-back left the row where it was, got {stored['status']}"
        )
        assert stored["remediation_round"] == 2, (
            f"the refused attempt incremented nothing, got {stored['remediation_round']}"
        )

    def test_03_an_assessment_with_the_loop_exhausted_still_certifies(self):
        """Exhausting the loop does not force failure.

        "A successful certification records `certifier_user_id` as the acting `X-User-ID`,
        stamps `certified_at` with the current logical-clock instant, sets `expires_at` to
        `certified_at` plus the program's `assessment_validity_days` days, recomputes the
        service's `safe_harbor_status` and `safe_harbor_expires_at`, re-derives
        `compliance_posture`".

        Design: Difficulty/non_linear_state_machine/assessment_remediation_cycle_bounded_then_certified
        """
        fixture = _program_and_assessment()
        assessment_id = fixture["assessment_id"]
        submit_assessment(assessment_id, 2, ASSESSOR)
        set_assessment_status(assessment_id, "REMEDIATION_REQUIRED", CERTIFIER)
        set_assessment_status(assessment_id, "SUBMITTED", ASSESSOR, findings_open_count=1)
        set_assessment_status(assessment_id, "REMEDIATION_REQUIRED", CERTIFIER)
        set_assessment_status(assessment_id, "SUBMITTED", ASSESSOR, findings_open_count=0)
        validate_error(
            api_client.set_safe_harbor_assessment_status(
                assessment_id, {"to_status": "REMEDIATION_REQUIRED"}, CERTIFIER
            ),
            "ERR_REMEDIATION_ROUNDS_EXHAUSTED",
        )

        certified = certify_assessment(assessment_id, "certifier-1")

        assert certified["status"] == "CERTIFIED", (
            f"the exhausted loop does not block certification, got {certified['status']}"
        )
        assert certified["certifier_user_id"] == "certifier-1"
        assert certified["findings_open_count"] == 0
        assert certified["remediation_round"] == 2
        assert_instant(certified["certified_at"], STARTUP_CLOCK, "certified_at")
        assert_instant(certified["expires_at"], "2027-08-01T00:00:00Z", "expires_at")

        service = read_service(fixture["service_id"])
        assert service["safe_harbor_status"] == "CERTIFIED", (
            "the clock is strictly before the expiry, got "
            f"{service['safe_harbor_status']}"
        )
        assert_instant(
            service["safe_harbor_expires_at"], "2027-08-01T00:00:00Z", "safe_harbor_expires_at"
        )
        assert service["compliance_posture"] == "OPEN"


class TestCertificationGatedByProgramRegulatorApproval:
    """A flawless assessment still fails if its program is not regulator approved."""

    def test_04_opening_an_assessment_moves_the_service_off_not_enrolled(self):
        """A draft row is enough to leave `NOT_ENROLLED`, and not enough to be certified.

        "If the service has no assessment at all, its `safe_harbor_status` is
        `NOT_ENROLLED`. If it has assessments but none certified, the status is
        `ASSESSMENT_DUE`." "The service's `safe_harbor_expires_at` mirrors the governing
        assessment's `expires_at`, and is null when no certified assessment exists."

        Design: Difficulty/cross_entity_state_dependency/certification_gated_by_program_regulator_approval_state
        """
        service = mixed_audience_service(name="Harbor Gate Kids")
        assert service["safe_harbor_status"] == "NOT_ENROLLED", (
            f"no assessment exists yet, got {service['safe_harbor_status']}"
        )

        fixture = _program_and_assessment(regulator_approved=False, service=service)
        assert fixture["assessment"]["status"] == "DRAFT"
        assert fixture["assessment"]["certified_at"] is None
        assert fixture["assessment"]["expires_at"] is None

        enrolled = read_service(service["id"])
        assert enrolled["safe_harbor_status"] == "ASSESSMENT_DUE", (
            "an uncertified assessment leaves the service merely due, got "
            f"{enrolled['safe_harbor_status']}"
        )
        assert enrolled["safe_harbor_expires_at"] is None

    def test_05_an_unapproved_program_refuses_a_flawless_certification(self):
        """Zero findings and a distinct certifier are not enough.

        Certification "requires, in this clause order: `findings_open_count` equal to 0 ...
        the referenced program's `regulator_approved` to be true, otherwise
        `ERR_PROGRAM_NOT_REGULATOR_APPROVED` (HTTP 409); and the acting `X-User-ID` to differ
        from the assessment's `preparer_user_id`". Submission itself is allowed, since only "a
        program whose `annual_assessment_required` is false refuses the submission".

        Design: Difficulty/cross_entity_state_dependency/certification_gated_by_program_regulator_approval_state
        """
        service = mixed_audience_service(name="Harbor Gate Kids")
        fixture = _program_and_assessment(regulator_approved=False, service=service)
        submitted = submit_assessment(fixture["assessment_id"], 0, ASSESSOR)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["findings_open_count"] == 0

        validate_error(
            api_client.certify_safe_harbor_assessment(fixture["assessment_id"], CERTIFIER),
            "ERR_PROGRAM_NOT_REGULATOR_APPROVED",
        )

        stored = read_assessment(fixture["assessment_id"])
        assert stored["status"] == "SUBMITTED", (
            f"the refused certification left the row submitted, got {stored['status']}"
        )
        assert stored["certified_at"] is None
        assert stored["expires_at"] is None
        assert stored["certifier_user_id"] is None
        service_after = read_service(service["id"])
        assert service_after["safe_harbor_status"] == "ASSESSMENT_DUE"
        assert service_after["safe_harbor_expires_at"] is None

    def test_06_a_second_assessment_under_an_approved_program_certifies(self):
        """The approved program's row certifies while the refused row is left alone.

        "The governing assessment is the one for this service whose `status` is `CERTIFIED`
        with the greatest `assessment_year`", and at most one assessment may exist for a
        combination of "a `service_id` and a `program_id` for a given `assessment_year`", so
        a second program admits a second row for the same year.

        Design: Difficulty/cross_entity_state_dependency/certification_gated_by_program_regulator_approval_state
        """
        service = mixed_audience_service(name="Harbor Gate Kids")
        refused = _program_and_assessment(regulator_approved=False, service=service)
        submit_assessment(refused["assessment_id"], 0, ASSESSOR)
        validate_error(
            api_client.certify_safe_harbor_assessment(refused["assessment_id"], CERTIFIER),
            "ERR_PROGRAM_NOT_REGULATOR_APPROVED",
        )

        good_program = create_program(
            program_name="Recognised Kids Seal",
            regulator_approved=True,
            annual_assessment_required=True,
            assessment_validity_days=365,
            assessment_grace_days=30,
        )
        good = create_assessment(service["id"], good_program["id"], 2026, ASSESSOR)
        submit_assessment(good["id"], 0, ASSESSOR)

        certified = certify_assessment(good["id"], "certifier-1")

        assert certified["status"] == "CERTIFIED"
        assert certified["certifier_user_id"] == "certifier-1"
        assert_instant(certified["certified_at"], STARTUP_CLOCK, "certified_at")
        assert_instant(certified["expires_at"], "2027-08-01T00:00:00Z", "expires_at")

        service_after = read_service(service["id"])
        assert service_after["safe_harbor_status"] == "CERTIFIED", (
            "the certified row governs, got " f"{service_after['safe_harbor_status']}"
        )
        assert_instant(
            service_after["safe_harbor_expires_at"],
            "2027-08-01T00:00:00Z",
            "safe_harbor_expires_at",
        )
        assert service_after["compliance_posture"] == "OPEN", (
            "safe harbor reaches the posture ladder only through LAPSED, got "
            f"{service_after['compliance_posture']}"
        )
        assert read_assessment(refused["assessment_id"])["status"] == "SUBMITTED", (
            "the second assessment did not repair the first"
        )
