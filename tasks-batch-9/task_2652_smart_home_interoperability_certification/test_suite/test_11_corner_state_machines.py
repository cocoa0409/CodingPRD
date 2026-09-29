"""The programme's state machines: their guards, their cycles and their locks.

Every transition in this service is a guarded move on one named axis, and the
interesting behaviour sits at the edges — a trigger that is legal exactly once, a
pair of states that cycles without bound, a terminal state no trigger leaves, and
the cascades and fan-outs a single accepted move drags behind it.
"""

from test_helpers import (
    CASE_CLOSED,
    CASE_EVIDENCE_REVIEW,
    CASE_OPEN,
    CASE_REMEDIATED,
    CASE_REMEDIATION_ORDERED,
    CASE_WITHDRAWAL_ORDERED,
    CLOCK_PROGRAMME_START,
    COMPLIANCE_NONCOMPLIANT,
    COMPLIANCE_REMEDIATED,
    COMPLIANCE_UNDER_INVESTIGATION,
    DAC_ISSUED,
    DAC_NOT_ISSUED,
    DAC_REVOKED,
    LAB_REVOKED,
    MEMBER_IP_EXECUTED,
    MEMBER_REGISTERED,
    MEMBER_TOOLS_GRANTED,
    MEMBER_TOOLS_REVOKED,
    PARTICIPATION_NO_SHOW,
    PARTICIPATION_PASSED,
    PARTICIPATION_REGISTERED,
    PLAN_COMPLETE,
    PLAN_IN_EXECUTION,
    PLAN_ISSUED,
    PLAN_VOIDED,
    PLUGFEST_CANCELLED,
    PLUGFEST_CLOSED,
    PLUGFEST_LOCKED,
    PLUGFEST_REGISTRATION_OPEN,
    PUB_PUBLISHED,
    PUB_SUPPRESSED,
    PUB_WITHDRAWN,
    REVIEW_APPROVED,
    REVIEW_PENDING,
    SESSION_CANCELLED,
    SESSION_COMPLETE,
    SESSION_IN_PROGRESS,
    SESSION_SCHEDULED,
    SPEC_DEPRECATED,
    SPEC_DRAFT,
    SPEC_RATIFIED,
    SPEC_RETIRED,
    SUB_CERTIFIED,
    SUB_IN_REVIEW,
    SUB_REVIEW_COMPLETE,
    SUB_WITHDRAWN,
    VOIDED_SPEC_DEPRECATED,
    accreditation_decision,
    advance_case,
    append_results,
    build_member,
    build_program,
    build_specification,
    close_plugfest,
    complete_session,
    deprecate_specification,
    execute_ip_commitment,
    feature,
    grant_tool_access,
    lock_plugfest,
    new_case,
    new_feature_set,
    new_member,
    new_participation,
    new_plugfest,
    new_session,
    new_specification,
    new_submission,
    read_case,
    read_laboratory,
    read_listing,
    read_member,
    read_participation,
    read_plugfest,
    read_session,
    read_specification,
    read_submission,
    read_test_plan,
    record_outcome,
    result_line,
    revoke_tool_access,
    same_instant,
    security_decision,
    set_clock,
    start_session,
    validate_error,
    validate_success,
    withdraw_submission,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_LABORATORY_STATE,
    ERR_INVALID_LISTING_STATE,
    ERR_INVALID_MEMBER_STATE,
    ERR_INVALID_PARTICIPATION_STATE,
    ERR_INVALID_PLUGFEST_STATE,
    ERR_INVALID_SESSION_STATE,
    ERR_INVALID_SPECIFICATION_STATE,
    ERR_INVALID_SUBMISSION_STATE,
    ERR_MANDATORY_COVERAGE_INCOMPLETE,
    ERR_REVIEW_ALREADY_DECIDED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import assert_cents, assert_score, assert_states
from test_helpers.factories import (
    accreditation_payload,
    case_advance_payload,
    competency_review_payload,
    conformance_decision_payload,
    ip_commitment_payload,
    noncompliance_case_payload,
    participation_payload,
    record_outcome_payload,
    results_payload,
    security_decision_payload,
    test_session_payload,
    tool_access_payload,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CONFORMANCE_REVIEWER_1,
    SECURITY_REVIEWER_1,
    SECURITY_REVIEWER_2,
    make_compliance_headers,
    make_conformance_headers,
    make_laboratory_headers,
    make_member_headers,
    make_security_headers,
)

#: One MANDATORY lighting feature set, the smallest ratifiable lighting graph.
SINGLE_LIGHTING_FEATURE = [feature("CORE_ONOFF", "MANDATORY", 20)]

#: The officers of the two segregation-of-duties halves of an investigation.
OFFICER_ONE = "OFFICER1"
OFFICER_TWO = "OFFICER2"


class TestSpecificationRatificationGuards:
    """DRAFT to RATIFIED: two coverage guards, then a one-shot trigger."""

    def test_01_ratification_needs_a_feature_set_and_a_mandatory_baseline(self):
        """A version with no feature sets at all and a version whose only device
        class carries nothing but an OPTIONAL set are both refused for the same
        reason, and both stay DRAFT with no ratification stamp.

        PRD (§3.1): "A version moves `DRAFT → RATIFIED` when it has at least one
        feature set and when, for every device class that appears at all among its
        feature sets, at least one of that class's feature sets carries `obligation`
        `MANDATORY` — a version that describes only optional lighting behaviour has
        no baseline and cannot be ratified, and either shortfall is reported as
        `ERR_MANDATORY_COVERAGE_INCOMPLETE`."

        Design: Corner/state_machines/specification_ratify_demands_coverage_and_refuses_a_second_call
        """
        set_clock(CLOCK_PROGRAMME_START)
        empty = new_specification(version_label="SHIC-EMPTY")
        optional_only = new_specification(version_label="SHIC-OPTONLY")
        new_feature_set(
            optional_only["id"],
            device_type="THERMOSTAT",
            feature_code="ECO_MODE",
            obligation="OPTIONAL",
            test_case_count=8,
        )

        validate_error(
            api_client.ratify_specification(empty["id"], headers=ADMIN_HEADERS),
            ERR_MANDATORY_COVERAGE_INCOMPLETE,
        )
        validate_error(
            api_client.ratify_specification(optional_only["id"], headers=ADMIN_HEADERS),
            ERR_MANDATORY_COVERAGE_INCOMPLETE,
        )

        stored_empty = read_specification(empty["id"])
        assert_states(stored_empty, status=SPEC_DRAFT, feature_set_count=0)
        assert stored_empty["ratified_at"] is None, (
            "a refused ratification stamps nothing, expected ratified_at null, "
            "got {!r}".format(stored_empty["ratified_at"])
        )
        stored_optional = read_specification(optional_only["id"])
        assert_states(stored_optional, status=SPEC_DRAFT, feature_set_count=1)
        assert stored_optional["ratified_at"] is None, (
            "the optional-only version is still a draft, expected ratified_at null, "
            "got {!r}".format(stored_optional["ratified_at"])
        )

    def test_02_the_mandatory_set_unlocks_ratification_which_then_runs_once(self):
        """Adding the THERMOSTAT MANDATORY set lets the very same call through,
        stamping `ratified_at` at the clock; repeating that call is refused as a
        specification-state error and changes nothing.

        PRD (§3.1): "Attempting to ratify a version that is not `DRAFT` draws the
        same specification-state error."

        Design: Corner/state_machines/specification_ratify_demands_coverage_and_refuses_a_second_call
        """
        set_clock(CLOCK_PROGRAMME_START)
        specification = new_specification(version_label="SHIC-OPTONLY")
        new_feature_set(
            specification["id"],
            device_type="THERMOSTAT",
            feature_code="ECO_MODE",
            obligation="OPTIONAL",
            test_case_count=8,
        )
        validate_error(
            api_client.ratify_specification(specification["id"], headers=ADMIN_HEADERS),
            ERR_MANDATORY_COVERAGE_INCOMPLETE,
        )
        new_feature_set(
            specification["id"],
            device_type="THERMOSTAT",
            feature_code="SETPOINT",
            obligation="MANDATORY",
            test_case_count=12,
        )

        ratified = validate_success(
            api_client.ratify_specification(specification["id"], headers=ADMIN_HEADERS)
        )

        assert_states(ratified, status=SPEC_RATIFIED, feature_set_count=2)
        assert same_instant(ratified["ratified_at"], CLOCK_PROGRAMME_START), (
            "ratification stamps the clock's current instant, expected {}, got {}".format(
                CLOCK_PROGRAMME_START, ratified["ratified_at"]
            )
        )
        version_after_ratify = ratified["version"]

        validate_error(
            api_client.ratify_specification(specification["id"], headers=ADMIN_HEADERS),
            ERR_INVALID_SPECIFICATION_STATE,
        )

        stored = read_specification(specification["id"])
        assert_states(
            stored,
            status=SPEC_RATIFIED,
            feature_set_count=2,
            version=version_after_ratify,
        )


class TestSpecificationRetirementAndItsLock:
    """One demotion endpoint, two steps, and a terminal state nothing leaves."""

    def test_03_a_live_submission_blocks_retirement_until_it_is_withdrawn(self):
        """The first demotion always lands on DEPRECATED, but the step to RETIRED
        waits for the last live submission: withdrawing the DRAFT submission is what
        lets the identical call through.

        PRD (§3.1): "From `DEPRECATED` it moves to `RETIRED`, which is terminal, and
        only when no submission pinned to the version sits in any of the live states
        `DRAFT`, `SUBMITTED`, `IN_REVIEW`, `RETURNED_FOR_INFO` or `REVIEW_COMPLETE`;
        a still-live submission blocks retirement with
        `ERR_INVALID_SPECIFICATION_STATE`."

        Design: Corner/state_machines/specification_retires_only_without_live_submissions_and_then_locks
        """
        ctx = build_program(stage="draft", features=SINGLE_LIGHTING_FEATURE)

        deprecated = deprecate_specification(ctx.specification_id)

        assert_states(deprecated, status=SPEC_DEPRECATED)
        assert same_instant(deprecated["deprecated_at"], CLOCK_PROGRAMME_START), (
            "demotion stamps deprecated_at at the clock, expected {}, got {}".format(
                CLOCK_PROGRAMME_START, deprecated["deprecated_at"]
            )
        )

        validate_error(
            api_client.deprecate_specification(
                ctx.specification_id, headers=ADMIN_HEADERS
            ),
            ERR_INVALID_SPECIFICATION_STATE,
        )
        assert_states(read_specification(ctx.specification_id), status=SPEC_DEPRECATED)

        withdrawn = withdraw_submission(ctx.submission_id, ctx.member_id)
        assert_states(withdrawn, state=SUB_WITHDRAWN)

        retired = validate_success(
            api_client.deprecate_specification(
                ctx.specification_id, headers=ADMIN_HEADERS
            )
        )
        assert_states(retired, status=SPEC_RETIRED)

    def test_04_retired_is_terminal_and_no_longer_a_legal_commitment_scope(self):
        """Nothing leaves RETIRED: a further demotion is refused, and a member trying
        to execute its commitment against that version is refused too and stays
        REGISTERED with no scope recorded.

        PRD (§2.8): "`ERR_INVALID_SPECIFICATION_STATE` (409) when the target
        specification's `status` does not permit the operation: ratifying or adding a
        feature set requires `DRAFT`; submitting a certification submission requires
        `RATIFIED`; executing an IP commitment and creating a plugfest require
        `RATIFIED` or `DEPRECATED`; naming a non-null `supersedes_specification_id` at
        creation requires the named version's `status` to be `RATIFIED` or
        `DEPRECATED`; and the demotion step from `DEPRECATED` to `RETIRED`
        additionally requires that no submission pinned to the version sits in a live
        state."

        Design: Corner/state_machines/specification_retires_only_without_live_submissions_and_then_locks
        """
        set_clock(CLOCK_PROGRAMME_START)
        spec_ctx = build_specification(features=SINGLE_LIGHTING_FEATURE)
        deprecate_specification(spec_ctx.specification_id)
        retired = deprecate_specification(spec_ctx.specification_id)
        assert_states(retired, status=SPEC_RETIRED)
        latecomer = new_member(legal_name="Borea Labs", tier="PARTICIPANT")

        validate_error(
            api_client.deprecate_specification(
                spec_ctx.specification_id, headers=ADMIN_HEADERS
            ),
            ERR_INVALID_SPECIFICATION_STATE,
        )
        validate_error(
            api_client.execute_ip_commitment(
                latecomer["id"],
                ip_commitment_payload(spec_ctx.specification_id, essential_patent_count=1),
                make_member_headers(latecomer["id"]),
            ),
            ERR_INVALID_SPECIFICATION_STATE,
        )

        assert_states(read_specification(spec_ctx.specification_id), status=SPEC_RETIRED)
        stored_member = read_member(latecomer["id"])
        assert_states(stored_member, onboarding_state=MEMBER_REGISTERED)
        assert stored_member["ip_scope_specification_id"] is None, (
            "the refused commitment records no scope, expected null, got {!r}".format(
                stored_member["ip_scope_specification_id"]
            )
        )


def _registered_member_against_a_ratified_version():
    """A ratified single-feature version plus one member still only REGISTERED."""
    set_clock(CLOCK_PROGRAMME_START)
    spec_ctx = build_specification(features=SINGLE_LIGHTING_FEATURE)
    member = new_member(legal_name="Acme Devices", tier="PROMOTER")
    return spec_ctx.specification_id, member["id"]


class TestToolAccessCycle:
    """The cyclic half of onboarding, and every out-of-order trigger around it."""

    def test_05_tool_access_presupposes_a_commitment_that_executes_only_once(self):
        """A grant aimed at a merely REGISTERED member is refused; the commitment
        itself then lands with good standing still false, and a second commitment is
        refused without overwriting the first one's disclosure.

        PRD (§3.2): "A member that has already executed a commitment cannot execute a
        second one; the attempt is rejected with `ERR_INVALID_MEMBER_STATE`."

        Design: Corner/state_machines/tool_access_cycles_grant_revoke_grant_with_good_standing_tracking
        """
        specification_id, member_id = _registered_member_against_a_ratified_version()

        validate_error(
            api_client.set_tool_access(member_id, tool_access_payload("GRANT"), ADMIN_HEADERS),
            ERR_INVALID_MEMBER_STATE,
        )
        assert_states(read_member(member_id), onboarding_state=MEMBER_REGISTERED)

        executed = execute_ip_commitment(
            member_id,
            specification_id,
            ip_commitment_type="RAND_ROYALTY_BEARING",
            essential_patent_count=7,
        )

        assert_states(
            executed,
            onboarding_state=MEMBER_IP_EXECUTED,
            ip_commitment_type="RAND_ROYALTY_BEARING",
            essential_patent_count=7,
            ip_scope_specification_id=specification_id,
            good_standing=False,
        )
        assert same_instant(executed["ip_executed_at"], CLOCK_PROGRAMME_START), (
            "the commitment stamps ip_executed_at at the clock, expected {}, "
            "got {}".format(CLOCK_PROGRAMME_START, executed["ip_executed_at"])
        )

        validate_error(
            api_client.execute_ip_commitment(
                member_id,
                ip_commitment_payload(
                    specification_id,
                    ip_commitment_type="RAND_ROYALTY_FREE",
                    essential_patent_count=1,
                ),
                make_member_headers(member_id),
            ),
            ERR_INVALID_MEMBER_STATE,
        )

        assert_states(
            read_member(member_id),
            onboarding_state=MEMBER_IP_EXECUTED,
            ip_commitment_type="RAND_ROYALTY_BEARING",
            essential_patent_count=7,
        )

    def test_06_grant_revoke_grant_cycles_and_good_standing_tracks_it(self):
        """Entitlement cycles without bound, good standing following it true, false,
        true, while a repeated grant and a repeated revoke are each refused and leave
        the member where it stood.

        PRD (§3.2): "A further grant moves `TOOLS_REVOKED → TOOLS_GRANTED` and
        restores good standing — this pair is cyclic and may repeat without bound,
        since a member whose tooling was pulled for a paperwork lapse can be
        reinstated as often as necessary."

        Design: Corner/state_machines/tool_access_cycles_grant_revoke_grant_with_good_standing_tracking
        """
        specification_id, member_id = _registered_member_against_a_ratified_version()
        execute_ip_commitment(
            member_id,
            specification_id,
            ip_commitment_type="RAND_ROYALTY_BEARING",
            essential_patent_count=7,
        )

        granted = grant_tool_access(member_id)
        assert_states(
            granted, onboarding_state=MEMBER_TOOLS_GRANTED, good_standing=True
        )
        version_after_first_grant = granted["version"]

        validate_error(
            api_client.set_tool_access(member_id, tool_access_payload("GRANT"), ADMIN_HEADERS),
            ERR_INVALID_MEMBER_STATE,
        )
        assert_states(
            read_member(member_id),
            onboarding_state=MEMBER_TOOLS_GRANTED,
            good_standing=True,
            version=version_after_first_grant,
        )

        revoked = revoke_tool_access(member_id)
        assert_states(
            revoked, onboarding_state=MEMBER_TOOLS_REVOKED, good_standing=False
        )

        validate_error(
            api_client.set_tool_access(member_id, tool_access_payload("REVOKE"), ADMIN_HEADERS),
            ERR_INVALID_MEMBER_STATE,
        )
        assert_states(
            read_member(member_id),
            onboarding_state=MEMBER_TOOLS_REVOKED,
            good_standing=False,
        )

        regranted = grant_tool_access(member_id)

        assert_states(
            regranted,
            onboarding_state=MEMBER_TOOLS_GRANTED,
            good_standing=True,
            open_case_count=0,
        )
        assert regranted["ip_withdrawn_at"] is None, (
            "the commitment was never withdrawn, expected ip_withdrawn_at null, "
            "got {!r}".format(regranted["ip_withdrawn_at"])
        )
        assert regranted["version"] == version_after_first_grant + 2, (
            "only the revoke and the re-grant wrote after the first grant, expected "
            "version {}, got {}".format(
                version_after_first_grant + 2, regranted["version"]
            )
        )


def _plugfest_with_two_vendors():
    """One event at quorum: two members, one submission each, both registered."""
    ctx = build_program(stage="draft", features=SINGLE_LIGHTING_FEATURE)
    co_vendor = build_member(
        scope_specification_id=ctx.specification_id, legal_name="Borea Labs"
    )
    ctx.co_member_id = co_vendor.member_id
    ctx.co_submission = new_submission(
        ctx.co_member_id,
        ctx.specification_id,
        ["CORE_ONOFF"],
        device_model="BL-200",
    )
    ctx.plugfest = new_plugfest(
        ctx.laboratory_id,
        ctx.specification_id,
        window_start="2026-10-05T09:00:00Z",
        window_end="2026-10-05T17:00:00Z",
        registration_deadline="2026-10-01T00:00:00Z",
        min_distinct_vendors=2,
    )
    ctx.plugfest_id = ctx.plugfest["id"]
    ctx.participation_one = new_participation(
        ctx.plugfest_id, ctx.member_id, ctx.submission_id, device_model="AL-100"
    )
    ctx.participation_two = new_participation(
        ctx.plugfest_id, ctx.co_member_id, ctx.co_submission["id"], device_model="BL-200"
    )
    return ctx


class TestPlugfestLockAndClose:
    """Locking freezes the roster; closing marks no-shows and drops the count."""

    def test_07_the_lock_stamps_the_roster_shut_at_exactly_the_quorum(self):
        """Two distinct vendors meet a `min_distinct_vendors` of 2 exactly, so the
        lock is accepted and stamped, and every later registration for the event is
        turned away.

        PRD (§3.7): "The lock stamps `locked_at` and refuses all further
        registrations for the event."

        Design: Corner/state_machines/plugfest_close_marks_no_shows_and_drops_the_distinct_vendor_count
        """
        ctx = _plugfest_with_two_vendors()

        before = read_plugfest(ctx.plugfest_id)
        assert_states(
            before, state=PLUGFEST_REGISTRATION_OPEN, distinct_vendor_count=2
        )

        locked = lock_plugfest(ctx.plugfest_id)

        assert_states(locked, state=PLUGFEST_LOCKED, distinct_vendor_count=2)
        assert same_instant(locked["locked_at"], CLOCK_PROGRAMME_START), (
            "the lock stamps locked_at at the clock, expected {}, got {}".format(
                CLOCK_PROGRAMME_START, locked["locked_at"]
            )
        )

        validate_error(
            api_client.create_participation(
                participation_payload(
                    ctx.plugfest_id,
                    ctx.member_id,
                    ctx.submission_id,
                    device_model="AL-100",
                ),
                make_member_headers(ctx.member_id),
            ),
            ERR_INVALID_PLUGFEST_STATE,
        )
        assert_states(read_plugfest(ctx.plugfest_id), distinct_vendor_count=2)

    def test_08_the_close_no_shows_the_silent_vendor_and_the_count_falls(self):
        """The vendor who was scored keeps its participation and its single credit,
        while the vendor who never appeared is recorded NO_SHOW with no credit — and
        because no-shows leave the counted set the vendor count falls from 2 to 1.

        PRD (§3.7): "A `ProgramAdmin` moves it `LOCKED → CLOSED`, and every
        participation still in `state` `REGISTERED` is set to `NO_SHOW` — a vendor who
        registered and never appeared is recorded as such rather than quietly
        forgotten — leaving `plugfest_credit_count` unchanged."

        Design: Corner/state_machines/plugfest_close_marks_no_shows_and_drops_the_distinct_vendor_count
        """
        ctx = _plugfest_with_two_vendors()
        lock_plugfest(ctx.plugfest_id)

        passed = record_outcome(
            ctx.participation_one["id"],
            ctx.laboratory_id,
            outcome="PASS",
            interop_pass_count=3,
        )
        assert_states(
            passed, state=PARTICIPATION_PASSED, interop_pass_count=3
        )
        assert same_instant(passed["outcome_recorded_at"], CLOCK_PROGRAMME_START), (
            "the outcome is stamped at the clock, expected {}, got {}".format(
                CLOCK_PROGRAMME_START, passed["outcome_recorded_at"]
            )
        )
        assert_states(read_submission(ctx.submission_id), plugfest_credit_count=1)

        validate_error(
            api_client.record_outcome(
                ctx.participation_one["id"],
                record_outcome_payload("FAIL", 0),
                make_laboratory_headers(ctx.laboratory_id),
            ),
            ERR_INVALID_PARTICIPATION_STATE,
        )
        assert_states(
            read_participation(ctx.participation_one["id"]),
            state=PARTICIPATION_PASSED,
            interop_pass_count=3,
        )

        closed = close_plugfest(ctx.plugfest_id)

        assert_states(closed, state=PLUGFEST_CLOSED, distinct_vendor_count=1)
        no_show = read_participation(ctx.participation_two["id"])
        assert_states(no_show, state=PARTICIPATION_NO_SHOW)
        assert no_show["outcome_recorded_at"] is None, (
            "a no-show was never scored, expected outcome_recorded_at null, "
            "got {!r}".format(no_show["outcome_recorded_at"])
        )
        assert_states(
            read_submission(ctx.co_submission["id"]), plugfest_credit_count=0
        )
        assert_states(read_submission(ctx.submission_id), plugfest_credit_count=1)

        validate_error(
            api_client.close_plugfest(ctx.plugfest_id, headers=ADMIN_HEADERS),
            ERR_INVALID_PLUGFEST_STATE,
        )


class TestReviewCompleteBubblesUpOnTheSecondAxis:
    """Two independent review axes resolving one primary state."""

    def test_09_an_approved_security_axis_alone_leaves_the_row_in_review(self):
        """The security APPROVE lands first, is recorded with its reviewer and its
        findings, and leaves the primary state IN_REVIEW; a second verdict on that
        same axis is refused and overwrites nothing.

        PRD (§3.8): "At the end of *either* decision the system evaluates a compound
        bubble-up: when the submission is `IN_REVIEW` and both
        `conformance_review_state` and `security_review_state` are `APPROVED`, the
        submission moves `IN_REVIEW → REVIEW_COMPLETE`."

        Design: Corner/state_machines/review_complete_bubbles_up_when_the_second_axis_approves
        """
        ctx = build_program(stage="plan_complete", features=SINGLE_LIGHTING_FEATURE)

        approved = validate_success(
            api_client.security_decision(
                ctx.submission_id,
                security_decision_payload("APPROVE"),
                make_security_headers(SECURITY_REVIEWER_1),
            )
        )

        assert_states(
            approved,
            state=SUB_IN_REVIEW,
            security_review_state=REVIEW_APPROVED,
            security_reviewer_user_id=SECURITY_REVIEWER_1,
            secure_boot_verified=True,
            verified_firmware_update_capability="OTA_SIGNED",
            conformance_review_state=REVIEW_PENDING,
        )

        validate_error(
            api_client.security_decision(
                ctx.submission_id,
                security_decision_payload(
                    "REJECT",
                    secure_boot_verified=False,
                    verified_firmware_update_capability="NONE",
                ),
                make_security_headers(SECURITY_REVIEWER_2),
            ),
            ERR_REVIEW_ALREADY_DECIDED,
        )

        assert_states(
            read_submission(ctx.submission_id),
            state=SUB_IN_REVIEW,
            security_review_state=REVIEW_APPROVED,
            security_reviewer_user_id=SECURITY_REVIEWER_1,
            secure_boot_verified=True,
        )

    def test_10_the_conformance_approve_landing_second_completes_the_review(self):
        """With security already approved the conformance APPROVE is the trigger: it
        pins the 85.00 final score and moves the row to REVIEW_COMPLETE, which is not
        certification — no credential, no stamp — and the escrow stays held.

        PRD (§3.8): "Whichever decision lands second is the one that triggers it."

        Design: Corner/state_machines/review_complete_bubbles_up_when_the_second_axis_approves
        """
        ctx = build_program(stage="plan_complete", features=SINGLE_LIGHTING_FEATURE)
        security_decision(ctx.submission_id, "APPROVE", SECURITY_REVIEWER_1)

        completed = validate_success(
            api_client.conformance_decision(
                ctx.submission_id,
                conformance_decision_payload("APPROVE", note="All mandatory cases pass."),
                make_conformance_headers(CONFORMANCE_REVIEWER_1),
            )
        )

        assert_states(
            completed,
            state=SUB_REVIEW_COMPLETE,
            conformance_review_state=REVIEW_APPROVED,
            conformance_reviewer_user_id=CONFORMANCE_REVIEWER_1,
            dac_state=DAC_NOT_ISSUED,
        )
        assert_score(completed["final_readiness_score"], "85.00", "final_readiness_score")
        assert completed["certified_at"] is None, (
            "REVIEW_COMPLETE is not certification, expected certified_at null, "
            "got {!r}".format(completed["certified_at"])
        )

        validate_error(
            api_client.start_review(
                ctx.submission_id, headers=make_conformance_headers(CONFORMANCE_REVIEWER_1)
            ),
            ERR_INVALID_SUBMISSION_STATE,
        )

        member = read_member(ctx.member_id)
        assert_cents(member["escrowed_credit_cents"], 135000, "escrowed_credit_cents")
        assert_cents(member["credit_balance_cents"], 865000, "credit_balance_cents")


def _issued_plan_with_two_bench_sessions():
    """An ISSUED two-mandatory-set plan with one session booked on each bench."""
    ctx = build_program(stage="issued")
    ctx.session_one = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T11:00:00Z",
    )
    ctx.session_two = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=2,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T11:00:00Z",
    )
    return ctx


class TestPlanCompletionNeedsFullMandatoryCoverage:
    """A plan's COMPLETE state is a function of its sessions and of coverage."""

    def test_11_one_finished_session_out_of_two_leaves_the_plan_in_execution(self):
        """Results are refused against a session that has not started; the first
        start bubbles the plan into execution; and finishing that session leaves the
        plan IN_EXECUTION, because a session is still live and CORE_DIM has no line.

        PRD (§3.5): "And it moves it `IN_EXECUTION → COMPLETE` when a session
        completes and, at that instant, all four of the following hold: no session of
        the plan remains in `SCHEDULED` or `IN_PROGRESS`; at least one session of the
        plan is `COMPLETE`; and every feature set of `included_feature_set_ids` whose
        `obligation` is `MANDATORY` or `CONDITIONAL` appears as the `feature_set_id`
        of at least one result line across the plan's completed sessions."

        Design: Corner/state_machines/plan_reaches_complete_only_when_every_mandatory_set_is_covered
        """
        ctx = _issued_plan_with_two_bench_sessions()

        validate_error(
            api_client.append_results(
                ctx.session_two["id"],
                results_payload([result_line(ctx.feature_set_ids["CORE_DIM"], "PASS")]),
                make_laboratory_headers(ctx.laboratory_id),
            ),
            ERR_INVALID_SESSION_STATE,
        )
        assert_states(read_session(ctx.session_two["id"]), state=SESSION_SCHEDULED)
        assert_states(read_test_plan(ctx.plan_id), state=PLAN_ISSUED)

        set_clock("2026-09-02T09:00:00Z")
        started = start_session(ctx.session_one["id"], ctx.laboratory_id)
        assert_states(started, state=SESSION_IN_PROGRESS)
        assert_states(read_test_plan(ctx.plan_id), state=PLAN_IN_EXECUTION)

        append_results(
            ctx.session_one["id"],
            ctx.laboratory_id,
            [result_line(ctx.feature_set_ids["CORE_ONOFF"], "PASS")],
        )
        set_clock("2026-09-02T10:00:00Z")
        completed = complete_session(ctx.session_one["id"], ctx.laboratory_id)

        assert_states(completed, state=SESSION_COMPLETE, completed_late=False)
        assert same_instant(completed["completed_at"], "2026-09-02T10:00:00Z"), (
            "completion stamps the clock, expected 2026-09-02T10:00:00Z, got {}".format(
                completed["completed_at"]
            )
        )
        assert_states(read_test_plan(ctx.plan_id), state=PLAN_IN_EXECUTION)

    def test_12_the_second_mandatory_set_closes_the_plan_and_frees_the_benches(self):
        """A completion that captured nothing is refused and leaves the session live;
        once CORE_DIM is recorded the same completion carries the plan to COMPLETE and
        both bench reservations are released.

        PRD (§3.6): "Completing a session requires `state` `IN_PROGRESS`, laboratory
        ownership, and a `result_lines` array that is not empty — completing a session
        that captured nothing is refused with `ERR_MANDATORY_COVERAGE_INCOMPLETE`."

        Design: Corner/state_machines/plan_reaches_complete_only_when_every_mandatory_set_is_covered
        """
        ctx = _issued_plan_with_two_bench_sessions()
        set_clock("2026-09-02T09:00:00Z")
        start_session(ctx.session_one["id"], ctx.laboratory_id)
        append_results(
            ctx.session_one["id"],
            ctx.laboratory_id,
            [result_line(ctx.feature_set_ids["CORE_ONOFF"], "PASS")],
        )
        set_clock("2026-09-02T10:00:00Z")
        complete_session(ctx.session_one["id"], ctx.laboratory_id)
        start_session(ctx.session_two["id"], ctx.laboratory_id)

        validate_error(
            api_client.complete_test_session(
                ctx.session_two["id"],
                headers=make_laboratory_headers(ctx.laboratory_id),
            ),
            ERR_MANDATORY_COVERAGE_INCOMPLETE,
        )
        assert_states(read_session(ctx.session_two["id"]), state=SESSION_IN_PROGRESS)
        assert_states(read_test_plan(ctx.plan_id), state=PLAN_IN_EXECUTION)

        append_results(
            ctx.session_two["id"],
            ctx.laboratory_id,
            [result_line(ctx.feature_set_ids["CORE_DIM"], "PASS")],
        )
        second = complete_session(ctx.session_two["id"], ctx.laboratory_id)
        assert_states(second, state=SESSION_COMPLETE)

        plan = read_test_plan(ctx.plan_id)
        assert_states(
            plan,
            state=PLAN_COMPLETE,
            required_case_count=30,
            mandatory_case_count=30,
            optional_case_count=0,
        )
        expected_ids = [
            ctx.feature_set_ids["CORE_DIM"],
            ctx.feature_set_ids["CORE_ONOFF"],
        ]
        assert plan["included_feature_set_ids"] == expected_ids, (
            "the closure is ordered by feature_code ascending, expected {}, "
            "got {}".format(expected_ids, plan["included_feature_set_ids"])
        )
        laboratory = read_laboratory(ctx.laboratory_id)
        assert laboratory["reserved_bench_minutes"] == 0, (
            "both completions released their 120 reserved minutes, expected 0, "
            "got {}".format(laboratory["reserved_bench_minutes"])
        )


def _laboratory_with_live_work_and_a_hosted_event():
    """One laboratory carrying two booked sessions, an in-execution plan and one
    open plugfest with a single registered vendor."""
    ctx = build_program(stage="issued", features=SINGLE_LIGHTING_FEATURE)
    ctx.session_one = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T11:00:00Z",
        session_type="INTEROP",
    )
    ctx.session_two = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=2,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T11:00:00Z",
        session_type="SECURITY",
    )
    start_session(ctx.session_one["id"], ctx.laboratory_id)
    ctx.plugfest = new_plugfest(
        ctx.laboratory_id,
        ctx.specification_id,
        window_start="2026-10-05T09:00:00Z",
        window_end="2026-10-05T17:00:00Z",
        registration_deadline="2026-10-01T00:00:00Z",
        min_distinct_vendors=2,
    )
    ctx.plugfest_id = ctx.plugfest["id"]
    ctx.participation = new_participation(
        ctx.plugfest_id, ctx.member_id, ctx.submission_id, device_model="AL-100"
    )
    return ctx


class TestAccreditationRevocationCascade:
    """One revocation, one two-hop cascade, one independent fan-out."""

    def test_13_revocation_cancels_the_live_sessions_and_voids_the_orphaned_plan(self):
        """Both booked sessions are cancelled and the occupancy figure is zeroed
        outright, which orphans the in-execution plan and voids it, while the
        submission behind it is deliberately left alone.

        PRD (§3.3): "Its **hop one** takes every session of this laboratory whose
        `state` is `SCHEDULED` or `IN_PROGRESS` and sets `state` to `CANCELLED`, and
        then sets the laboratory's `reserved_bench_minutes` to 0 outright, since
        nothing remains booked."

        Design: Corner/state_machines/laboratory_revoke_cascades_sessions_plan_and_hosted_plugfest
        """
        ctx = _laboratory_with_live_work_and_a_hosted_event()

        before = read_laboratory(ctx.laboratory_id)
        assert before["reserved_bench_minutes"] == 240, (
            "two 120-minute bookings are held, expected reserved_bench_minutes 240, "
            "got {}".format(before["reserved_bench_minutes"])
        )

        revoked = accreditation_decision(ctx.laboratory_id, "REVOKE")

        assert_states(
            revoked, accreditation_status=LAB_REVOKED, reserved_bench_minutes=0
        )
        assert_states(read_session(ctx.session_one["id"]), state=SESSION_CANCELLED)
        assert_states(read_session(ctx.session_two["id"]), state=SESSION_CANCELLED)
        assert_states(
            read_test_plan(ctx.plan_id),
            state=PLAN_VOIDED,
            voided_reason=VOIDED_SPEC_DEPRECATED,
        )
        assert_states(read_submission(ctx.submission_id), state=SUB_IN_REVIEW)

    def test_14_the_hosted_event_fans_out_and_revoked_accepts_nothing_further(self):
        """Independently of the session chain the hosted event is cancelled and its
        registered vendor becomes a no-show, dropping the vendor count to zero; the
        revoked laboratory then refuses reinstatement, review and new bookings alike.

        PRD (§3.3): "Separately, and independently of that chain, a **fan-out** takes
        every plugfest this laboratory hosts whose `state` is `REGISTRATION_OPEN` or
        `LOCKED` and sets `state` to `CANCELLED`, and then takes every participation
        of those cancelled events whose `state` is `REGISTERED` and sets `state` to
        `NO_SHOW`."

        Design: Corner/state_machines/laboratory_revoke_cascades_sessions_plan_and_hosted_plugfest
        """
        ctx = _laboratory_with_live_work_and_a_hosted_event()
        assert_states(
            read_participation(ctx.participation["id"]), state=PARTICIPATION_REGISTERED
        )

        accreditation_decision(ctx.laboratory_id, "REVOKE")

        assert_states(
            read_plugfest(ctx.plugfest_id),
            state=PLUGFEST_CANCELLED,
            distinct_vendor_count=0,
        )
        assert_states(
            read_participation(ctx.participation["id"]), state=PARTICIPATION_NO_SHOW
        )

        validate_error(
            api_client.accreditation_decision(
                ctx.laboratory_id, accreditation_payload("REINSTATE"), ADMIN_HEADERS
            ),
            ERR_INVALID_LABORATORY_STATE,
        )
        validate_error(
            api_client.competency_review(
                ctx.laboratory_id, competency_review_payload("LIFETIME"), ADMIN_HEADERS
            ),
            ERR_INVALID_LABORATORY_STATE,
        )
        validate_error(
            api_client.create_test_session(
                test_session_payload(
                    ctx.plan_id,
                    ctx.laboratory_id,
                    bench_index=1,
                    window_start="2026-09-03T09:00:00Z",
                    window_end="2026-09-03T10:00:00Z",
                ),
                ADMIN_HEADERS,
            ),
            ERR_INVALID_LABORATORY_STATE,
        )
        assert_states(
            read_laboratory(ctx.laboratory_id),
            accreditation_status=LAB_REVOKED,
            reserved_bench_minutes=0,
        )


def _published_certified_listing():
    """One device certified end to end with credential DAC-000001 and published."""
    return build_program(
        stage="published",
        features=SINGLE_LIGHTING_FEATURE,
        dac_serial="DAC-000001",
    )


class TestCaseWithdrawalOrder:
    """An investigation that ends in a withdrawal order, and its closure gate."""

    def test_15_opening_a_case_prices_it_and_moves_only_the_compliance_axis(self):
        """The interop case is priced at 50000 plus a 5000 surcharge, records the
        officer who filed it, and marks the listing UNDER_INVESTIGATION while the
        device stays visible to consumers as PUBLISHED.

        PRD (§3.9): "Acceptance opens the case in `state` `OPEN`, records
        `opened_by_user_id` as the acting `X-User-ID`, leaves `auto_opened` false,
        `closed_by_user_id` and `remediation_deadline_at` null, prices the assessment,
        moves the listing's `compliance_status` to `UNDER_INVESTIGATION` while leaving
        `publication_status` untouched, and recomputes the member's
        `open_case_count`."

        Design: Corner/state_machines/case_withdrawal_order_withdraws_the_listing_and_revokes_the_credential
        """
        ctx = _published_certified_listing()

        opened = validate_success(
            api_client.create_noncompliance_case(
                noncompliance_case_payload(
                    ctx.listing_id,
                    category="INTEROP_DEFECT",
                    claimed_impact_units=100,
                    evidence_summary="Field reports of pairing failures with three hub vendors.",
                ),
                make_compliance_headers(OFFICER_ONE),
            ),
            201,
        )

        assert_states(
            opened,
            state=CASE_OPEN,
            auto_opened=False,
            opened_by_user_id=OFFICER_ONE,
        )
        assert opened["closed_by_user_id"] is None, (
            "a fresh case has no closer, expected closed_by_user_id null, "
            "got {!r}".format(opened["closed_by_user_id"])
        )
        assert opened["remediation_deadline_at"] is None, (
            "no remediation has been ordered, expected remediation_deadline_at null, "
            "got {!r}".format(opened["remediation_deadline_at"])
        )
        assert_cents(
            opened["assessment_subtotal_cents"], 50000, "assessment_subtotal_cents"
        )
        assert_cents(opened["surcharge_cents"], 5000, "surcharge_cents")
        assert_cents(opened["penalty_total_cents"], 55000, "penalty_total_cents")

        assert_states(
            read_listing(ctx.listing_id),
            compliance_status=COMPLIANCE_UNDER_INVESTIGATION,
            publication_status=PUB_PUBLISHED,
        )
        assert_states(read_member(ctx.member_id), open_case_count=1)

    def test_16_the_withdrawal_order_writes_three_rows_and_only_a_second_officer_closes(self):
        """One disposition withdraws the listing, marks it noncompliant and revokes
        the credential without erasing it; the officer who opened the case cannot
        close it, the second officer can, and the withdrawn listing never publishes
        again.

        PRD (§3.9): "`ORDER_WITHDRAWAL` moves it `EVIDENCE_REVIEW →
        WITHDRAWAL_ORDERED` and drives the listing to `publication_status` `WITHDRAWN`
        and `compliance_status` `NONCOMPLIANT`, revoking the linked submission's
        `dac_state` where it is `ISSUED` — the same enforcement package as an
        operator-filed listing withdrawal, reached down the case path instead."

        Design: Corner/state_machines/case_withdrawal_order_withdraws_the_listing_and_revokes_the_credential
        """
        ctx = _published_certified_listing()
        case = new_case(
            ctx.listing_id,
            officer_user_id=OFFICER_ONE,
            category="INTEROP_DEFECT",
            claimed_impact_units=100,
        )
        escalated = advance_case(case["id"], "ESCALATE", officer_user_id=OFFICER_ONE)
        assert_states(escalated, state=CASE_EVIDENCE_REVIEW)

        ordered = validate_success(
            api_client.advance_case(
                case["id"],
                case_advance_payload("ORDER_WITHDRAWAL"),
                make_compliance_headers(OFFICER_ONE),
            )
        )

        assert_states(ordered, state=CASE_WITHDRAWAL_ORDERED)
        assert_states(
            read_listing(ctx.listing_id),
            publication_status=PUB_WITHDRAWN,
            compliance_status=COMPLIANCE_NONCOMPLIANT,
        )
        assert_states(
            read_submission(ctx.submission_id),
            state=SUB_CERTIFIED,
            dac_state=DAC_REVOKED,
            dac_serial="DAC-000001",
        )

        validate_error(
            api_client.close_case(
                case["id"], headers=make_compliance_headers(OFFICER_ONE)
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )
        still_open = read_case(case["id"])
        assert_states(still_open, state=CASE_WITHDRAWAL_ORDERED)
        assert still_open["closed_by_user_id"] is None, (
            "the refused close records nobody, expected closed_by_user_id null, "
            "got {!r}".format(still_open["closed_by_user_id"])
        )

        closed = validate_success(
            api_client.close_case(
                case["id"], headers=make_compliance_headers(OFFICER_TWO)
            )
        )
        assert_states(closed, state=CASE_CLOSED, closed_by_user_id=OFFICER_TWO)

        validate_error(
            api_client.advance_case(
                case["id"],
                case_advance_payload("ESCALATE"),
                make_compliance_headers(OFFICER_TWO),
            ),
            ERR_INVALID_CASE_STATE,
        )
        # ORDER_WITHDRAWAL revoked the credential as well as withdrawing the
        # listing, so rung 16 (publication requires dac_state ISSUED) is violated
        # before rung 22 (a WITHDRAWN listing cannot publish); §2.8 gives the
        # earlier rung, so the ladder-correct answer is the submission-state error.
        validate_error(
            api_client.publish_listing(ctx.listing_id, headers=ADMIN_HEADERS),
            ERR_INVALID_SUBMISSION_STATE,
        )
        assert_states(read_member(ctx.member_id), open_case_count=0)


def _listing_under_security_investigation():
    """A published listing with an OPEN SECURITY_DEFECT case over 40 units."""
    ctx = _published_certified_listing()
    ctx.case = new_case(
        ctx.listing_id,
        officer_user_id=OFFICER_ONE,
        category="SECURITY_DEFECT",
        claimed_impact_units=40,
        evidence_summary="Attestation key reuse across two production batches.",
    )
    ctx.case_id = ctx.case["id"]
    return ctx


class TestCaseRemediationPath:
    """Remediation suppresses visibility and restores only the compliance axis."""

    def test_17_ordering_remediation_suppresses_the_listing_for_a_bounded_window(self):
        """A security case is priced at 20000 plus a 7000 surcharge and blocks
        publication outright; a remediation window beyond 365 days is refused, and the
        accepted 30-day order suppresses the listing and dates the deadline exactly 30
        days out.

        PRD (§3.9): "`ORDER_REMEDIATION` moves it `EVIDENCE_REVIEW →
        REMEDIATION_ORDERED`, requires `remediation_days` to be present and between 1
        and 365 — an absent or out-of-range value being refused with
        `ERR_INVALID_DATE_RANGE` — sets `remediation_deadline_at` to the logical
        clock's current instant advanced by that many days, and, where the listing's
        `publication_status` is `PUBLISHED`, suppresses it."

        Design: Corner/state_machines/case_remediation_suppresses_then_remediates_and_needs_a_republish
        """
        ctx = _listing_under_security_investigation()

        assert_cents(
            ctx.case["assessment_subtotal_cents"], 20000, "assessment_subtotal_cents"
        )
        assert_cents(ctx.case["surcharge_cents"], 7000, "surcharge_cents")
        assert_cents(ctx.case["penalty_total_cents"], 27000, "penalty_total_cents")

        validate_error(
            api_client.publish_listing(ctx.listing_id, headers=ADMIN_HEADERS),
            ERR_INVALID_LISTING_STATE,
        )

        advance_case(ctx.case_id, "ESCALATE", officer_user_id=OFFICER_ONE)
        validate_error(
            api_client.advance_case(
                ctx.case_id,
                case_advance_payload("ORDER_REMEDIATION", remediation_days=400),
                make_compliance_headers(OFFICER_ONE),
            ),
            ERR_INVALID_DATE_RANGE,
        )
        assert_states(read_case(ctx.case_id), state=CASE_EVIDENCE_REVIEW)

        ordered = validate_success(
            api_client.advance_case(
                ctx.case_id,
                case_advance_payload("ORDER_REMEDIATION", remediation_days=30),
                make_compliance_headers(OFFICER_ONE),
            )
        )

        # `remediation_days` is an input the PRD consumes to derive
        # `remediation_deadline_at`; it is never named as a stored attribute of a
        # NoncomplianceCase, so it is not asserted on the response body. The
        # 30-day deadline below is what the PRD does uniquely determine.
        assert_states(ordered, state=CASE_REMEDIATION_ORDERED)
        assert same_instant(ordered["remediation_deadline_at"], "2026-10-02T12:00:00Z"), (
            "30 days from 2026-09-02T12:00:00Z is 2026-10-02T12:00:00Z, got {}".format(
                ordered["remediation_deadline_at"]
            )
        )
        assert_states(
            read_listing(ctx.listing_id),
            publication_status=PUB_SUPPRESSED,
            compliance_status=COMPLIANCE_UNDER_INVESTIGATION,
        )

    def test_18_confirming_on_the_deadline_restores_compliance_but_not_visibility(self):
        """Confirmation is accepted at exactly the deadline instant and lifts the
        compliance axis to REMEDIATED, yet the listing stays SUPPRESSED until it is
        published again — and the credential was never touched.

        PRD (§3.9): "`CONFIRM_REMEDIATION` moves it `REMEDIATION_ORDERED →
        REMEDIATED`, requires the logical clock's current instant to be at or before
        `remediation_deadline_at` — an expired deadline being refused with
        `ERR_REMEDIATION_DEADLINE_PASSED`, with an instant exactly equal to the
        deadline accepted — and sets the listing's `compliance_status` to `REMEDIATED`
        while leaving `publication_status` at `SUPPRESSED`."

        Design: Corner/state_machines/case_remediation_suppresses_then_remediates_and_needs_a_republish
        """
        ctx = _listing_under_security_investigation()
        advance_case(ctx.case_id, "ESCALATE", officer_user_id=OFFICER_ONE)
        advance_case(
            ctx.case_id,
            "ORDER_REMEDIATION",
            officer_user_id=OFFICER_ONE,
            remediation_days=30,
        )
        set_clock("2026-10-02T12:00:00Z")

        remediated = validate_success(
            api_client.advance_case(
                ctx.case_id,
                case_advance_payload("CONFIRM_REMEDIATION"),
                make_compliance_headers(OFFICER_ONE),
            )
        )

        assert_states(remediated, state=CASE_REMEDIATED)
        assert_states(
            read_listing(ctx.listing_id),
            compliance_status=COMPLIANCE_REMEDIATED,
            publication_status=PUB_SUPPRESSED,
        )

        republished = validate_success(
            api_client.publish_listing(ctx.listing_id, headers=ADMIN_HEADERS)
        )

        assert_states(republished, publication_status=PUB_PUBLISHED)
        assert same_instant(republished["published_at"], "2026-10-02T12:00:00Z"), (
            "publication stamps the clock, expected 2026-10-02T12:00:00Z, got {}".format(
                republished["published_at"]
            )
        )
        assert republished["declared_features"] == ["CORE_ONOFF"], (
            "the declaration is recomputed from the plan, expected ['CORE_ONOFF'], "
            "got {}".format(republished["declared_features"])
        )

        closed = validate_success(
            api_client.close_case(
                ctx.case_id, headers=make_compliance_headers(OFFICER_TWO)
            )
        )
        assert_states(closed, state=CASE_CLOSED, closed_by_user_id=OFFICER_TWO)
        assert_states(read_submission(ctx.submission_id), dac_state=DAC_ISSUED)
