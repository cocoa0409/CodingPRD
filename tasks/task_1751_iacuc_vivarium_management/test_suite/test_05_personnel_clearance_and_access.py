"""Personnel clearance gates (training + occupational health), enrollment
expiry, authentication and role-permission denials, and investigator
ownership on submission (PRD §2.1, §2.8, §3.2, §3.3).
"""
from datetime import timedelta

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    STAFF,
    TRAINING,
    VET,
    ApiErrorId,
    api_client,
    assert_personnel,
    create_approved_protocol,
    create_cleared_personnel,
    create_draft_protocol,
    create_inspection,
    create_investigator,
    create_personnel_record,
    get_success_data,
    make_investigator_headers,
    parse_instant,
    set_clock,
    validate_error,
)
from test_helpers.factories import create_cage_payload
from test_helpers.fixtures import (
    clear_occ_health,
    create_billing_run,
    enroll_and_complete_course,
)


def _create_partially_trained_personnel():
    """Personnel with 3 of 4 required courses COMPLETED (SPECIES_SPECIFIC
    missing) and occupational health CLEARED."""
    person = create_personnel_record(role_on_protocols="STUDENT")
    for course in ("ANIMAL_HANDLING", "ASEPTIC_TECHNIQUE", "EUTHANASIA"):
        enroll_and_complete_course(person["id"], course)
    clear_occ_health(person["id"])
    return person


class TestClearanceGateExpiry:
    def test_gates_true_while_enrollments_current(self, api):
        """PRD §3.2: "A personnel member's `training_completed` flag is
        recomputed on every completion and every expiry: it is true exactly
        when, for each of the four required course codes, the member holds an
        enrollment in `COMPLETED` whose `expires_at` is either unset or still
        in the future." and "The member's `occ_health_cleared` flag is true
        exactly when at least one of their occupational-health enrollments
        stands `CLEARED` with an `expires_at` that is unset or still in the
        future".

        Design: Difficulty/dual_variant_calc/training_gate_completed_vs_expired_on_personnel
        """
        person = create_cleared_personnel()
        assert_personnel(person)
        assert person["training_completed"] is True
        assert person["occ_health_cleared"] is True

        enrollments = get_success_data(
            api_client.list_personnel_training_enrollments(person["id"], TRAINING)
        )
        assert len(enrollments) == 4
        for row in enrollments:
            assert row["state"] == "COMPLETED"
            completed = parse_instant(row["completed_at"])
            expires = parse_instant(row["expires_at"])
            assert expires - completed == timedelta(days=365), (
                "expires_at becomes exactly 365 days after completed_at"
            )

    def test_gates_flip_false_after_clock_crosses_expiry(self, api):
        """PRD §3.2: "When the logical clock reaches `expires_at`, the
        enrollment moves from `COMPLETED` to `EXPIRED`, a terminal state." and
        the gates are "recomputed on every completion and every expiry", so
        the same rows evaluate differently once the logical clock passes
        2027-08-01 (completed 2026-08-01 plus 365 days).

        Design: Difficulty/dual_variant_calc/training_gate_completed_vs_expired_on_personnel
        """
        person = create_cleared_personnel()
        set_clock("2027-08-02T00:00:00Z")

        after = get_success_data(api_client.get_personnel(person["id"], ADMIN))
        assert after["training_completed"] is False, (
            "all four enrollments EXPIRED -> training_completed false"
        )
        assert after["occ_health_cleared"] is False, (
            "the occ-health enrollment also expired -> occ_health_cleared false"
        )

        enrollments = get_success_data(
            api_client.list_personnel_training_enrollments(person["id"], TRAINING)
        )
        assert all(row["state"] == "EXPIRED" for row in enrollments)


class TestTrainingGateOnPersonnelAttach:
    def test_personnel_add_blocked_when_course_missing(self, api):
        """PRD §3.2: "Attaching personnel to a protocol checks the member
        being attached ... In all three cases the member must hold both
        `training_completed` and `occ_health_cleared`, and failure is rejected
        with `ERR_TRAINING_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/personnel_add_blocked_by_training_gate
        """
        scenario = create_approved_protocol()
        person = _create_partially_trained_personnel()

        resp = api_client.attach_protocol_personnel(
            scenario["protocol"]["id"], {"personnel_id": person["id"]},
            scenario["investigator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TRAINING_INCOMPLETE)


class TestEnrollmentTerminalLockdown:
    def test_expired_enrollment_cannot_be_completed(self, api):
        """PRD §3.2: "When the logical clock reaches `expires_at`, the
        enrollment moves from `COMPLETED` to `EXPIRED`, a terminal state."
        PRD §2.8: "State legality — the target resource is in a state from
        which the requested transition exists (`ERR_INVALID_STATE`, 409)."

        Design: Corner/state_machines/training_enrollment_terminal_expired_lockdown
        """
        person = create_personnel_record()
        enrollment = enroll_and_complete_course(person["id"], "EUTHANASIA")
        assert enrollment["state"] == "COMPLETED"

        set_clock("2027-08-02T00:00:00Z")
        enrollments = get_success_data(
            api_client.list_personnel_training_enrollments(person["id"], TRAINING)
        )
        assert enrollments[0]["state"] == "EXPIRED", (
            "the clock crossing expires_at flips COMPLETED to EXPIRED"
        )

        resp = api_client.complete_training_enrollment(enrollment["id"], TRAINING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the operational
        capacity in which they act. A request missing either header, or
        presenting a role the system does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/request_missing_auth_headers_unauthenticated
        """
        resp = api_client.get_investigator(
            NON_EXISTENT_UUID, headers={"Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRolePermissionDenials:
    def test_investigator_cannot_complete_inspection(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD
        §4: `POST /iacuc/inspections/{id}/complete` is authorized for
        "IacucAdministrator" only.

        Design: Corner/roles/investigator_cannot_complete_inspection
        """
        investigator = create_investigator()
        inspection = create_inspection(
            inspection_kind="PROGRAM_REVIEW", scheduled_for="2026-08-15T00:00:00Z",
        )

        resp = api_client.complete_inspection(
            inspection["id"],
            {"completed_at": "2026-08-15T10:00:00Z", "deficiency_count": 0},
            make_investigator_headers(investigator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_animal_care_staff_cannot_finalize_billing(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD
        §4: `POST /iacuc/billing-runs/{id}/finalize` is authorized for
        "BillingCoordinator" only.

        Design: Corner/roles/animal_care_staff_cannot_finalize_billing
        """
        run = create_billing_run("2026-08-01T00:00:00Z", "2026-08-22T00:00:00Z")

        resp = api_client.finalize_billing_run(
            run["id"], {"expected_billing_run_version": run["version"]}, STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_veterinarian_cannot_create_cages(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD
        §4: `POST /iacuc/cages` is authorized for "FacilityManager" only.

        Design: Corner/roles/veterinarian_cannot_create_cages
        """
        scenario = create_draft_protocol()

        resp = api_client.create_cage(
            create_cage_payload(scenario["protocol"]["id"]), VET,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestInvestigatorOwnership:
    def test_submitting_another_investigators_protocol_rejected(self, api):
        """PRD §3.3: "Submission is the investigator's own act: the
        `X-User-ID` must equal the protocol's `investigator_id` (else
        `ERR_NOT_OWNER`)". PRD §2.1: "a mismatch is rejected with
        `ERR_NOT_OWNER` (HTTP 403)."

        Design: Corner/roles/investigator_ownership_enforced_on_submit
        """
        scenario = create_draft_protocol()
        other = create_investigator()

        resp = api_client.submit_protocol(
            scenario["protocol"]["id"], make_investigator_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER)

