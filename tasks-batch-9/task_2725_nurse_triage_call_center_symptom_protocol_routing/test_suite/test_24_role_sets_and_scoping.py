"""Role sets, liaison practice scoping, assigned-nurse scoping, shared reads."""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_version_is
from test_helpers.test_users import (
    UNBOUND_CHARGE_NURSE,
    UNBOUND_PRACTICE_LIAISON,
    UNBOUND_TRIAGE_NURSE,
)

INTAKE_HAS_NO_CLINICAL_STANDING = (
    "An intake agent has no clinical standing to verify a callback outcome at all."
)


class TestWriteEndpointsOutsideTheirRoleSet:
    def test_reference_data_writes_reject_the_liaison_and_the_charge_nurse(self, world):
        """PRD §2.1: "When both headers are present but the named role is not among the
        roles authorised for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/write_endpoints_outside_their_declared_role_set_are_rejected
        """
        liaison_creates_practice = world.api.create_practice(
            f.practice_payload(name="Liaison Health"), UNBOUND_PRACTICE_LIAISON
        )
        charge_publishes_protocol = world.api.create_protocol(
            f.protocol_payload(), UNBOUND_CHARGE_NURSE
        )
        charge_suspends_practice = world.api.patch_practice_status(
            NON_EXISTENT_UUID, f.practice_status_payload("SUSPENDED"), UNBOUND_CHARGE_NURSE
        )

        validate_error(liaison_creates_practice, ApiErrorId.ERR_UNAUTHORIZED, 403)
        validate_error(charge_publishes_protocol, ApiErrorId.ERR_UNAUTHORIZED, 403)
        validate_error(charge_suspends_practice, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_the_role_check_fires_before_the_existence_check(self, world):
        """PRD §2.12: "2. `ERR_UNAUTHORIZED` — the presented role is not among the
        endpoint's authorised roles. Guards every endpoint that has a role list."

        Design: Corner/rbac/write_endpoints_outside_their_declared_role_set_are_rejected
        """
        intake_scores_protocol = world.api.create_assessment(
            NON_EXISTENT_UUID,
            f.assessment_payload(NON_EXISTENT_UUID, red_flag_count=0),
            world.intake,
        )
        intake_verifies_callback = world.api.verify_callback(
            NON_EXISTENT_UUID,
            f.verify_payload(
                "IMPROVED", True, verifier_attestation=INTAKE_HAS_NO_CLINICAL_STANDING
            ),
            world.intake,
        )

        validate_error(intake_scores_protocol, ApiErrorId.ERR_UNAUTHORIZED, 403)
        validate_error(intake_verifies_callback, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_the_two_supervisory_writes_and_the_audit_write_are_role_exclusive(
        self, world
    ):
        """PRD §2.1: "`ChargeNurse` is a shift supervisor who is also a licensed nurse;
        it owns the two supervisory compensating operations — overriding a determined
        disposition and reopening a closed call — and it may not perform any operation
        reserved for `TriageNurse`".

        Design: Corner/rbac/write_endpoints_outside_their_declared_role_set_are_rejected
        """
        nurse_overrides = world.api.override_disposition(
            NON_EXISTENT_UUID,
            f.override_payload(
                "URGENT_CARE_24H",
                override_reason_code="CLINICIAN_DIRECTED",
                override_narrative=(
                    "A triage nurse may never perform the supervisory override "
                    "operation."
                ),
            ),
            UNBOUND_TRIAGE_NURSE,
        )
        nurse_reopens = world.api.reopen_call(
            NON_EXISTENT_UUID,
            f.reopen_payload(
                reopen_reason="A triage nurse may not reopen a closed call either."
            ),
            UNBOUND_TRIAGE_NURSE,
        )
        charge_files_outcome = world.api.create_audit_record(
            NON_EXISTENT_UUID,
            f.audit_record_payload(
                reported_outcome="ED_ADMITTED",
                outcome_source="EHR_CLAIM",
                outcome_observed_at="2026-08-03T20:00:00Z",
            ),
            UNBOUND_CHARGE_NURSE,
        )

        validate_error(nurse_overrides, ApiErrorId.ERR_UNAUTHORIZED, 403)
        validate_error(nurse_reopens, ApiErrorId.ERR_UNAUTHORIZED, 403)
        validate_error(charge_files_outcome, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_none_of_the_refused_writes_persisted_anything(self, world):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format".

        Design: Corner/rbac/write_endpoints_outside_their_declared_role_set_are_rejected
        """
        world.api.create_practice(
            f.practice_payload(name="Liaison Health"), UNBOUND_PRACTICE_LIAISON
        )
        world.api.create_protocol(f.protocol_payload(), UNBOUND_CHARGE_NURSE)
        world.api.create_assessment(
            NON_EXISTENT_UUID,
            f.assessment_payload(NON_EXISTENT_UUID, red_flag_count=0),
            world.intake,
        )
        world.api.create_audit_record(
            NON_EXISTENT_UUID,
            f.audit_record_payload(outcome_source="EHR_CLAIM"),
            UNBOUND_CHARGE_NURSE,
        )

        _, protocol_meta = validate_paginated(world.api.list_protocols(world.admin, None))
        _, assessment_meta = validate_paginated(
            world.api.list_assessments(world.admin, None)
        )

        assert protocol_meta["total_count"] == 0
        assert assessment_meta["total_count"] == 0


@pytest.fixture
def two_practices_each_with_a_draft_window(world):
    """practice_1 is the liaison's own practice; practice_2 belongs to someone else."""
    world.set_clock("2026-08-03T14:30:00Z")
    practice_1 = world.create_practice(
        name="Northside Family Health",
        audit_period_start_utc="2026-08-01T00:00:00Z",
    )
    practice_2 = get_success_data(
        world.api.create_practice(
            f.practice_payload(
                name="Lakeside Pediatrics",
                per_minute_rate_millicents=3900,
                audit_period_start_utc="2026-08-01T00:00:00Z",
            ),
            world.admin,
        )
    )
    nights = {
        "start_utc": "2026-08-10T02:00:00Z",
        "end_utc": "2026-08-10T13:00:00Z",
        "coverage_kind": "NIGHTS",
    }
    window_2 = get_success_data(
        world.api.create_coverage_window(
            f.coverage_window_payload(practice_2["id"], **nights), world.admin
        )
    )
    window_1 = get_success_data(
        world.api.create_coverage_window(
            f.coverage_window_payload(practice_1["id"], **nights), world.admin
        )
    )
    return practice_1, practice_2, window_1, window_2


class TestPracticeLiaisonIsScopedToItsOwnPractice:
    def test_the_three_scoped_reads_of_another_practice_are_refused(
        self, world, two_practices_each_with_a_draft_window
    ):
        """PRD §2.1: "When `X-User-Role` is `PracticeLiaison`, `X-User-ID` is the `id` of
        the acting `Practice`; any practice-scoped path whose practice identifier is not
        equal to `X-User-ID` is rejected with `ERR_PRACTICE_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/practice_liaison_cannot_read_another_practices_compliance_summary
        """
        practice_1, practice_2, _, _ = two_practices_each_with_a_draft_window
        as_liaison_1 = world.liaison_headers(practice_1["id"])

        summary = world.api.get_compliance_summary(practice_2["id"], as_liaison_1)
        invoice = world.api.get_after_hours_invoice(practice_2["id"], as_liaison_1)
        panel = world.api.list_patients(practice_2["id"], as_liaison_1, None)

        validate_error(summary, ApiErrorId.ERR_PRACTICE_SCOPE_VIOLATION, 403)
        validate_error(invoice, ApiErrorId.ERR_PRACTICE_SCOPE_VIOLATION, 403)
        validate_error(panel, ApiErrorId.ERR_PRACTICE_SCOPE_VIOLATION, 403)

    def test_the_liaison_cannot_activate_the_other_practices_window(
        self, world, two_practices_each_with_a_draft_window
    ):
        """PRD §2.12: "15. `ERR_PRACTICE_SCOPE_VIOLATION` — the acting role is
        `PracticeLiaison` and `X-User-ID` is not the identifier of the practice named in
        the path."

        Design: Corner/rbac/practice_liaison_cannot_read_another_practices_compliance_summary
        """
        practice_1, _, _, window_2 = two_practices_each_with_a_draft_window
        assert window_2["status"] == "DRAFT"

        response = world.api.activate_coverage_window(
            window_2["id"], {}, world.liaison_headers(practice_1["id"])
        )

        validate_error(response, ApiErrorId.ERR_PRACTICE_SCOPE_VIOLATION, 403)
        after = world.coverage_window(window_2["id"])
        assert after["status"] == "DRAFT"
        assert_version_is(after, 1, "the scope refusal wrote nothing")

    def test_the_identical_requests_against_its_own_practice_succeed(
        self, world, two_practices_each_with_a_draft_window
    ):
        """PRD §2.1: "`PracticeLiaison` is a contracted practice's own representative,
        whose reads are narrowed to that practice's own data."

        Design: Corner/rbac/practice_liaison_cannot_read_another_practices_compliance_summary
        """
        practice_1, _, window_1, _ = two_practices_each_with_a_draft_window
        as_liaison_1 = world.liaison_headers(practice_1["id"])

        own_summary = get_success_data(
            world.api.get_compliance_summary(practice_1["id"], as_liaison_1)
        )
        own_window = get_success_data(
            world.api.activate_coverage_window(window_1["id"], {}, as_liaison_1)
        )

        assert own_summary["audited_count"] == 0
        assert own_summary["compliance_posture"] == "NORMAL"
        assert own_window["status"] == "ACTIVE"

    def test_the_platform_admin_reads_both_practices(
        self, world, two_practices_each_with_a_draft_window
    ):
        """PRD §2.1: "When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque
        operator identifier not tied to any persisted entity."

        Design: Corner/rbac/practice_liaison_cannot_read_another_practices_compliance_summary
        """
        _, practice_2, _, _ = two_practices_each_with_a_draft_window

        seen_by_admin = get_success_data(
            world.api.get_compliance_summary(practice_2["id"], world.admin)
        )

        assert seen_by_admin["audited_count"] == 0
        assert seen_by_admin["compliance_posture"] == "NORMAL"


@pytest.fixture
def assigned_call_with_an_equally_licensed_bystander(world):
    """nurse_a holds the call; nurse_c has the same CA licence and shift."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_c"),
        protocol={"base_severity": 62},
    )
    call = world.call_through_assignment("nurse_a", reason_text="chest discomfort")
    assert call["assigned_nurse_id"] == world.nurse_id("nurse_a")
    return call


class TestOnlyTheAssignedNurseMayWorkTheCall:
    def test_the_bystander_nurse_cannot_score_the_protocol(
        self, world, assigned_call_with_an_equally_licensed_bystander
    ):
        """PRD §3.5: "Only the nurse recorded as the call's assigned nurse may score it;
        anyone else receives `ERR_NOT_ASSIGNED_NURSE`."

        Design: Corner/rbac/a_nurse_who_is_not_the_assigned_nurse_cannot_assess_or_complete_the_call
        """
        call = assigned_call_with_an_equally_licensed_bystander

        response = world.api.create_assessment(
            call["id"],
            f.assessment_payload(world.protocols["protocol"]["id"]),
            world.nurse_headers("nurse_c"),
        )

        validate_error(response, ApiErrorId.ERR_NOT_ASSIGNED_NURSE, 403)
        _, meta = validate_paginated(
            world.api.list_assessments(world.admin, {"call_id": call["id"]})
        )
        assert meta["total_count"] == 0
        assert world.call(call["id"])["status"] == "ASSIGNED"

    def test_the_assigned_nurse_scores_it_and_the_bystander_cannot_advise_on_it(
        self, world, assigned_call_with_an_equally_licensed_bystander
    ):
        """PRD §2.1: "A `TriageNurse` may only act on a call whose assigned nurse is that
        nurse, and on a callback task whose assigned nurse is that nurse; otherwise the
        request is rejected with `ERR_NOT_ASSIGNED_NURSE` (HTTP 403)."

        Design: Corner/rbac/a_nurse_who_is_not_the_assigned_nurse_cannot_assess_or_complete_the_call
        """
        call = assigned_call_with_an_equally_licensed_bystander
        assessment = world.create_assessment(call["id"], "nurse_a", "protocol")
        version = world.call_version(call["id"])

        response = world.api.create_disposition(
            f.disposition_payload(call["id"], assessment["id"], "ED_NOW", version),
            world.nurse_headers("nurse_c"),
        )

        validate_error(response, ApiErrorId.ERR_NOT_ASSIGNED_NURSE, 403)
        _, meta = validate_paginated(
            world.api.list_assessments(world.admin, {"call_id": call["id"]})
        )
        assert meta["total_count"] == 1
        assert world.assessment(assessment["id"])["status"] == "ACTIVE"

    def test_the_bystander_cannot_log_an_attempt_on_the_resulting_callback(
        self, world, assigned_call_with_an_equally_licensed_bystander
    ):
        """PRD §3.8: "Recording an attempt is reserved to the task's `assigned_nurse_id`;
        any other nurse receives `ERR_NOT_ASSIGNED_NURSE`."

        Design: Corner/rbac/a_nurse_who_is_not_the_assigned_nurse_cannot_assess_or_complete_the_call
        """
        call = assigned_call_with_an_equally_licensed_bystander
        assessment = world.create_assessment(call["id"], "nurse_a", "protocol")
        disposition = world.create_disposition(
            call["id"], assessment["id"], "ED_NOW", "nurse_a"
        )
        task = world.callback_for(disposition["id"])

        response = world.api.create_callback_attempt(
            task["id"], f.attempt_payload("NO_ANSWER"), world.nurse_headers("nurse_c")
        )

        validate_error(response, ApiErrorId.ERR_NOT_ASSIGNED_NURSE, 403)
        after = world.callback(task["id"])
        assert after["attempt_count"] == 0
        assert after["assigned_nurse_id"] == world.nurse_id("nurse_a")

    def test_the_bystander_cannot_close_the_call_but_the_assigned_nurse_can(
        self, world, assigned_call_with_an_equally_licensed_bystander
    ):
        """PRD §3.9: "Only the assigned nurse closes a call, and only from
        `DISPOSITIONED`, moving it to `CLOSED`."

        Design: Corner/rbac/a_nurse_who_is_not_the_assigned_nurse_cannot_assess_or_complete_the_call
        """
        call = assigned_call_with_an_equally_licensed_bystander
        assessment = world.create_assessment(call["id"], "nurse_a", "protocol")
        world.create_disposition(call["id"], assessment["id"], "ED_NOW", "nurse_a")

        refused = world.api.complete_call(
            call["id"], f.complete_payload(12), world.nurse_headers("nurse_c")
        )
        closed = world.complete_call(call["id"], "nurse_a", handle_minutes=12)

        validate_error(refused, ApiErrorId.ERR_NOT_ASSIGNED_NURSE, 403)
        assert closed["status"] == "CLOSED"
        assert world.nurse("nurse_a")["active_call_load"] == 0
        assert world.nurse("nurse_c")["active_call_load"] == 0


@pytest.fixture
def one_call_and_one_protocol_for_every_role_to_read(world):
    """A practice, an ACTIVE protocol and one INTAKE call."""
    world.set_clock("2026-08-03T14:30:00Z")
    practice = world.create_practice(name="Northside Family Health")
    world.create_protocol("protocol")
    call = world.open_call(
        caller_name="Dana Reyes",
        caller_phone="+14155550100",
        reason_text="chest discomfort",
    )
    return practice, call


class TestSharedLookupReadsAreOpenToEveryRole:
    def test_all_six_roles_read_the_identical_call_body(
        self, world, one_call_and_one_protocol_for_every_role_to_read
    ):
        """PRD §4: "| GET | `/triage-calls/{id}` | Reads one call, including the version
        used for the disposition version handshake. | All roles |"

        Design: Corner/rbac/every_role_can_read_the_shared_lookup_endpoints
        """
        practice, call = one_call_and_one_protocol_for_every_role_to_read
        every_role = (
            world.admin,
            world.intake,
            UNBOUND_TRIAGE_NURSE,
            UNBOUND_CHARGE_NURSE,
            world.auditor,
            world.liaison_headers(practice["id"]),
        )

        bodies = [
            get_success_data(world.api.get_triage_call(call["id"], headers))
            for headers in every_role
        ]

        assert [body["id"] for body in bodies] == [call["id"]] * 6
        assert bodies[0]["status"] == "INTAKE"
        assert bodies[5]["caller_phone"] == "+14155550100"
        assert all(body == bodies[0] for body in bodies), "no role-dependent redaction"

    def test_the_liaison_reads_the_shared_protocol_listing(
        self, world, one_call_and_one_protocol_for_every_role_to_read
    ):
        """PRD §4: "| GET | `/symptom-protocols` | Lists symptom protocols. | All roles |"

        Design: Corner/rbac/every_role_can_read_the_shared_lookup_endpoints
        """
        practice, _ = one_call_and_one_protocol_for_every_role_to_read

        rows, meta = validate_paginated(
            world.api.list_protocols(
                world.liaison_headers(practice["id"]), {"status": "ACTIVE"}
            )
        )

        assert meta["total_count"] == 1
        assert rows[0]["code"] == "CHEST_PAIN"
