"""Two inclusive-versus-strict boundaries, each driven to its exact edge.

A conformance approval compares the freshly computed FINAL readiness score against
an inclusive threshold of 65.00, so exactly 65.00 is approvable while the 57.50 the
same submission carried one plugfest credit earlier is not. A firmware revision
compares the overlap between the reported change and the listing's declared
features against a strict ceiling of two codes, so an overlap of exactly two
classifies DELTA while an overlap of three classifies FULL.
"""

from test_helpers import (
    COMPLIANCE_COMPLIANT,
    DAC_ISSUED,
    DAC_REVOKED,
    PUB_PUBLISHED,
    PUB_SUPPRESSED,
    RECERT_DELTA,
    RECERT_FULL,
    RECERT_NONE,
    RECERT_REASON_FEATURE_DELTA,
    REVIEW_APPROVED,
    REVIEW_PENDING,
    SUB_IN_REVIEW,
    append_results,
    build_member,
    build_program,
    complete_session,
    feature,
    lock_plugfest,
    new_participation,
    new_plugfest,
    new_session,
    new_submission,
    plus_days,
    read_listing,
    read_readiness,
    read_submission,
    record_outcome,
    report_firmware_revision,
    result_line,
    same_instant,
    set_clock,
    start_session,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_READINESS_BELOW_THRESHOLD
from test_helpers.assertions import assert_score, assert_states
from test_helpers.factories import conformance_decision_payload
from test_helpers.test_users import CONFORMANCE_HEADERS

#: Two mandatory lighting feature sets worth 30 cases together plus one optional
#: feature set the vendor declares but never has tested.
_THRESHOLD_FEATURES = [
    feature("CORE_ONOFF", "MANDATORY", 20),
    feature("CORE_DIM", "MANDATORY", 10),
    feature("OPT_SCENE", "OPTIONAL", 8),
]

#: The instant the single bench session is finally completed, well past its
#: window_end, so the session is late and FINAL timeliness collapses to zero.
_LATE_COMPLETION_CLOCK = "2026-09-08T00:00:00Z"


def _approve_conformance(submission_id):
    """POST the conformance APPROVE without asserting anything about the answer."""
    return api_client.conformance_decision(
        submission_id, conformance_decision_payload("APPROVE"), CONFORMANCE_HEADERS
    )


def _threshold_program():
    """One IN_REVIEW submission sitting at a FINAL readiness score of 57.50.

    Its plan carries 30 mandatory cases, all passed, and 8 optional cases that
    were never tested; its one session finished late; and of the two locked
    plugfests it entered only the first has had its outcome recorded, so it holds
    exactly one interoperability credit.
    """
    ctx = build_program(
        stage="issued",
        features=_THRESHOLD_FEATURES,
        declared_codes=["CORE_ONOFF", "CORE_DIM", "OPT_SCENE"],
    )

    co_vendor = build_member(scope_specification_id=ctx.specification_id)
    co_submission = new_submission(
        co_vendor.member_id, ctx.specification_id, ["CORE_ONOFF", "CORE_DIM"]
    )
    ctx.participation_ids = []
    for window_start, window_end in (
        ("2026-09-03T09:00:00Z", "2026-09-03T17:00:00Z"),
        ("2026-09-05T09:00:00Z", "2026-09-05T17:00:00Z"),
    ):
        plugfest = new_plugfest(
            ctx.laboratory_id,
            ctx.specification_id,
            window_start=window_start,
            window_end=window_end,
            registration_deadline="2026-09-02T00:00:00Z",
        )
        own = new_participation(plugfest["id"], ctx.member_id, ctx.submission_id)
        new_participation(plugfest["id"], co_vendor.member_id, co_submission["id"])
        lock_plugfest(plugfest["id"])
        ctx.participation_ids.append(own["id"])

    session = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T13:00:00Z",
    )
    ctx.session_id = session["id"]
    set_clock("2026-09-02T09:30:00Z")
    start_session(ctx.session_id, ctx.laboratory_id)
    append_results(
        ctx.session_id,
        ctx.laboratory_id,
        [
            result_line(ctx.feature_set_ids["CORE_ONOFF"], "PASS", "h-core"),
            result_line(ctx.feature_set_ids["CORE_DIM"], "PASS", "h-dim"),
        ],
    )
    set_clock("2026-09-06T00:00:00Z")
    record_outcome(ctx.participation_ids[0], ctx.laboratory_id, "PASS", 5)
    set_clock(_LATE_COMPLETION_CLOCK)
    complete_session(ctx.session_id, ctx.laboratory_id)
    return ctx


def _earn_second_credit(ctx):
    """Record the second locked plugfest's PASS, lifting the interop ratio to 1."""
    return record_outcome(ctx.participation_ids[1], ctx.laboratory_id, "PASS", 5)


class TestFinalReadinessAtTheApprovalThreshold:
    """The inclusive 65.00 approval threshold, approached from one credit below."""

    def test_01_one_interop_credit_leaves_the_final_score_at_57_50(self):
        """With a single plugfest credit the FINAL score is 50.00 mandatory plus
        0.00 optional plus 7.50 interoperability plus 0.00 timeliness, which is
        57.50 — a shade under the approval threshold.

        PRD (§3.8): "The interoperability ratio is the submission's
        `plugfest_credit_count`, capped at the target of 2, divided by 2, rounded
        half-up to four decimal places — so one credit is worth half the
        interoperability weight, two credits are worth all of it, and a third credit
        adds nothing."

        Design: Difficulty/boundary_precision_check/final_readiness_exactly_sixty_five_point_zero_zero_is_approvable
        """
        ctx = _threshold_program()

        readiness = read_readiness(ctx.submission_id, variant="FINAL")

        assert_score(readiness["score"], "57.50", "FINAL readiness score")
        assert readiness["plugfest_credit_count"] == 1, (
            "only the first plugfest outcome has been recorded, so "
            "plugfest_credit_count is 1, got {}".format(readiness["plugfest_credit_count"])
        )
        assert readiness["mandatory_passed_cases"] == 30, (
            "both mandatory feature sets passed, expected 30 mandatory cases, "
            "got {}".format(readiness["mandatory_passed_cases"])
        )
        assert readiness["optional_passed_cases"] == 0, (
            "the optional feature set was never tested, expected 0 optional cases, "
            "got {}".format(readiness["optional_passed_cases"])
        )
        assert readiness["late_session_count"] == 1, (
            "the one counted session completed after its window_end, expected 1 late "
            "session, got {}".format(readiness["late_session_count"])
        )

    def test_02_an_approve_at_57_50_is_refused_and_persists_nothing(self):
        """An APPROVE computed at 57.50 is refused with ERR_READINESS_BELOW_THRESHOLD
        and the whole call is rolled back, so `final_readiness_score` stays null and
        both axes stay where they were.

        PRD (§3.8): "The ordering here is deliberate and observable: the score is
        computed *before* the threshold is evaluated, but it is pinned to
        `final_readiness_score` only when the request as a whole is accepted, so a
        rejected `APPROVE` leaves `final_readiness_score` exactly as it was — the
        write is rolled back with the request along with every other effect of the
        failed call."

        Design: Difficulty/boundary_precision_check/final_readiness_exactly_sixty_five_point_zero_zero_is_approvable
        """
        ctx = _threshold_program()

        response = _approve_conformance(ctx.submission_id)

        validate_error(response, ERR_READINESS_BELOW_THRESHOLD)
        submission = read_submission(ctx.submission_id)
        assert submission["final_readiness_score"] is None, (
            "the refused APPROVE must leave final_readiness_score null, got "
            "{!r}".format(submission["final_readiness_score"])
        )
        assert_states(
            submission,
            conformance_review_state=REVIEW_PENDING,
            state=SUB_IN_REVIEW,
        )

    def test_03_the_second_credit_lifts_the_final_score_to_exactly_65_00(self):
        """Recording the second plugfest PASS takes `plugfest_credit_count` to 2 and
        the FINAL score from 57.50 to exactly 65.00, the full interoperability weight
        being the only component that moved.

        PRD (§3.7): "A `PASS` moves the participation `REGISTERED → PASSED`, writes
        `interop_pass_count`, stamps `outcome_recorded_at`, and increments the named
        submission's `plugfest_credit_count` by one, that field being the count of
        the submission's participations in `state` `PASSED`; it also refreshes the
        submission's provisional readiness score."

        Design: Difficulty/boundary_precision_check/final_readiness_exactly_sixty_five_point_zero_zero_is_approvable
        """
        ctx = _threshold_program()

        _earn_second_credit(ctx)

        submission = read_submission(ctx.submission_id)
        assert submission["plugfest_credit_count"] == 2, (
            "both plugfest participations have PASSED, expected "
            "plugfest_credit_count 2, got {}".format(submission["plugfest_credit_count"])
        )
        readiness = read_readiness(ctx.submission_id, variant="FINAL")
        assert_score(readiness["score"], "65.00", "FINAL readiness score")
        assert readiness["mandatory_passed_cases"] == 30, (
            "the mandatory tally is unchanged by the plugfest credit, expected 30, "
            "got {}".format(readiness["mandatory_passed_cases"])
        )
        assert readiness["optional_passed_cases"] == 0, (
            "the optional tally is unchanged by the plugfest credit, expected 0, "
            "got {}".format(readiness["optional_passed_cases"])
        )
        assert readiness["late_session_count"] == 1, (
            "the late session is still the only counted one, expected 1, got "
            "{}".format(readiness["late_session_count"])
        )

    def test_04_an_approve_at_exactly_65_00_is_accepted_and_pins_the_score(self):
        """65.00 is at the threshold rather than below it, so the APPROVE that was
        refused a moment earlier now succeeds, pinning 65.00 and moving the
        conformance axis to APPROVED.

        PRD (§3.8): "An `APPROVE` additionally demands that the freshly computed
        final score be at or above the approval threshold of 65.00 — exactly 65.00 is
        sufficient, and a shortfall is refused with `ERR_READINESS_BELOW_THRESHOLD` —
        and that `plugfest_credit_count` be at least the pinned specification's
        `min_plugfest_credits`, with a shortfall refused as
        `ERR_INSUFFICIENT_PLUGFEST_CREDITS`."

        Design: Difficulty/boundary_precision_check/final_readiness_exactly_sixty_five_point_zero_zero_is_approvable
        """
        ctx = _threshold_program()
        validate_error(_approve_conformance(ctx.submission_id), ERR_READINESS_BELOW_THRESHOLD)
        _earn_second_credit(ctx)

        response = _approve_conformance(ctx.submission_id)

        assert response.status_code == 200, (
            "an APPROVE at exactly the 65.00 threshold must be accepted, got "
            "{}".format(response.status_code)
        )
        submission = read_submission(ctx.submission_id)
        assert_score(submission["final_readiness_score"], "65.00", "final_readiness_score")
        assert_states(submission, conformance_review_state=REVIEW_APPROVED)

    def test_05_one_approved_axis_does_not_bubble_the_submission_up(self):
        """The accepted conformance APPROVE leaves the submission IN_REVIEW because
        the security axis is still PENDING, and the PROVISIONAL variant of the same
        stored evidence reads 80.00 against FINAL's 65.00.

        PRD (§3.8): "At the end of *either* decision the system evaluates a compound
        bubble-up: when the submission is `IN_REVIEW` and both
        `conformance_review_state` and `security_review_state` are `APPROVED`, the
        submission moves `IN_REVIEW → REVIEW_COMPLETE`."

        Design: Difficulty/boundary_precision_check/final_readiness_exactly_sixty_five_point_zero_zero_is_approvable
        """
        ctx = _threshold_program()
        _earn_second_credit(ctx)
        approved = _approve_conformance(ctx.submission_id)
        assert approved.status_code == 200, (
            "the APPROVE at exactly 65.00 must be accepted before the bubble-up is "
            "inspected, expected 200, got {}".format(approved.status_code)
        )

        submission = read_submission(ctx.submission_id)

        assert_states(
            submission,
            state=SUB_IN_REVIEW,
            conformance_review_state=REVIEW_APPROVED,
            security_review_state=REVIEW_PENDING,
        )
        # PROVISIONAL pins timeliness at 1.0000, so it keeps the 15 points the late
        # session cost FINAL: 50.00 + 0.00 + 15.00 + 15.00.
        assert_score(
            read_readiness(ctx.submission_id, variant="PROVISIONAL")["score"],
            "80.00",
            "PROVISIONAL readiness score",
        )
        assert_score(
            read_readiness(ctx.submission_id, variant="FINAL")["score"],
            "65.00",
            "FINAL readiness score",
        )


#: Four lighting feature sets, none of them security-relevant, so nothing in an
#: overlap can ever be security-relevant and the classification ladder is decided
#: by the size of the overlap alone.
_FOUR_LIGHTING_FEATURES = [
    feature("CORE_ONOFF", "MANDATORY", 20, security_relevant=False),
    feature("CORE_DIM", "MANDATORY", 10, security_relevant=False),
    feature("OPT_SCENE", "OPTIONAL", 8, security_relevant=False),
    feature("OPT_COLOR", "OPTIONAL", 6, security_relevant=False),
]

_ALL_FOUR_CODES = ["CORE_ONOFF", "CORE_DIM", "OPT_SCENE", "OPT_COLOR"]

#: The instant every firmware revision below is reported at, so each deadline is
#: this instant advanced by the classification's day count.
_REVISION_CLOCK = "2026-09-10T00:00:00Z"
_DELTA_DEADLINE = plus_days(_REVISION_CLOCK, 90)
_FULL_DEADLINE = plus_days(_REVISION_CLOCK, 30)


def _published_listing_program():
    """A PUBLISHED listing over a certified device declaring all four codes."""
    ctx = build_program(
        stage="published",
        features=_FOUR_LIGHTING_FEATURES,
        declared_codes=_ALL_FOUR_CODES,
    )
    set_clock(_REVISION_CLOCK)
    return ctx


def _report_overlap_of_two(ctx):
    """Revision 1.1.0 touching the two mandatory codes: an overlap of exactly 2."""
    return report_firmware_revision(
        ctx.listing_id,
        firmware_version="1.1.0",
        changed_feature_codes=["CORE_ONOFF", "CORE_DIM"],
        security_change=False,
    )


def _report_overlap_of_three(ctx):
    """Revision 1.2.0 touching one more declared code: an overlap of 3."""
    return report_firmware_revision(
        ctx.listing_id,
        firmware_version="1.2.0",
        changed_feature_codes=["CORE_ONOFF", "CORE_DIM", "OPT_SCENE"],
        security_change=False,
    )


def _report_empty_overlap(ctx):
    """Revision 1.3.0 changing no declared code while flagging security."""
    return report_firmware_revision(
        ctx.listing_id,
        firmware_version="1.3.0",
        changed_feature_codes=[],
        security_change=True,
    )


class TestFirmwareOverlapAtTheFullRecertBoundary:
    """The strict two-code overlap ceiling that separates DELTA from FULL."""

    def test_06_an_overlap_of_exactly_two_codes_classifies_delta(self):
        """The listing declares all four codes, so a revision naming two of them
        overlaps by exactly two — which is not strictly more than two, so it falls
        through to DELTA and a deadline 90 days out.

        PRD (§3.9): "Rule three classifies `FULL` with `recert_trigger_reason`
        `FIRMWARE_FEATURE_DELTA` when the overlap holds strictly more than two codes;
        the boundary is strict, so an overlap of exactly two codes falls through to
        rule four while an overlap of three classifies `FULL`."

        Design: Difficulty/boundary_precision_check/firmware_overlap_of_exactly_two_codes_classifies_delta_not_full
        """
        ctx = _published_listing_program()
        declared = read_listing(ctx.listing_id)["declared_features"]
        assert declared == ["CORE_DIM", "CORE_ONOFF", "OPT_COLOR", "OPT_SCENE"], (
            "declared_features must carry all four codes by feature_code ascending, "
            "got {}".format(declared)
        )

        _report_overlap_of_two(ctx)

        listing = read_listing(ctx.listing_id)
        assert_states(
            listing,
            recert_classification=RECERT_DELTA,
            recert_trigger_reason=RECERT_REASON_FEATURE_DELTA,
        )
        assert same_instant(listing["recertification_due_at"], _DELTA_DEADLINE), (
            "a DELTA classification sets recertification_due_at 90 days out, "
            "expected {}, got {!r}".format(
                _DELTA_DEADLINE, listing["recertification_due_at"]
            )
        )

    def test_07_a_delta_classification_leaves_visibility_and_credential_alone(self):
        """DELTA carries none of FULL's enforcement: the listing stays PUBLISHED and
        the credential stays ISSUED, while the two always-applied writes land.

        PRD (§3.9): "Whatever the classification, and including `NONE`, two writes
        always happen: `latest_firmware_version` becomes the request's
        `firmware_version`, and `firmware_revision_count` rises by one."

        Design: Difficulty/boundary_precision_check/firmware_overlap_of_exactly_two_codes_classifies_delta_not_full
        """
        ctx = _published_listing_program()

        _report_overlap_of_two(ctx)

        listing = read_listing(ctx.listing_id)
        assert_states(
            listing,
            publication_status=PUB_PUBLISHED,
            compliance_status=COMPLIANCE_COMPLIANT,
            latest_firmware_version="1.1.0",
            firmware_revision_count=1,
        )
        submission = read_submission(ctx.submission_id)
        assert submission["dac_state"] == DAC_ISSUED, (
            "only a FULL classification revokes the credential, so dac_state must "
            "still be ISSUED, got {}".format(submission["dac_state"])
        )

    def test_08_an_overlap_of_three_codes_classifies_full_at_thirty_days(self):
        """One more declared code in the same revision pushes the overlap past the
        strict ceiling, so the classification becomes FULL and the deadline shortens
        from 90 days to 30.

        PRD (§3.9): "The deadline follows the classification: `FULL` sets
        `recertification_due_at` to the logical clock's current instant advanced by 30
        days, `DELTA` advances it by 90 days, and `NONE` leaves
        `recertification_due_at` exactly as it was, including null."

        Design: Difficulty/boundary_precision_check/firmware_overlap_of_exactly_two_codes_classifies_delta_not_full
        """
        ctx = _published_listing_program()
        _report_overlap_of_two(ctx)

        _report_overlap_of_three(ctx)

        listing = read_listing(ctx.listing_id)
        assert_states(
            listing,
            recert_classification=RECERT_FULL,
            recert_trigger_reason=RECERT_REASON_FEATURE_DELTA,
            latest_firmware_version="1.2.0",
            firmware_revision_count=2,
        )
        assert same_instant(listing["recertification_due_at"], _FULL_DEADLINE), (
            "a FULL classification rewrites recertification_due_at 30 days out, "
            "expected {}, got {!r}".format(
                _FULL_DEADLINE, listing["recertification_due_at"]
            )
        )

    def test_09_the_full_classification_suppresses_and_de_credentials(self):
        """FULL pulls the device out of the directory and revokes its attestation
        credential, while the enforcement axis is untouched because no investigation
        was opened.

        PRD (§3.9): "Where the listing's `publication_status` is `PUBLISHED` it
        becomes `SUPPRESSED`, pulling the device out of the consumer directory; and
        where the linked submission's `dac_state` is `ISSUED` it becomes `REVOKED`."

        Design: Difficulty/boundary_precision_check/firmware_overlap_of_exactly_two_codes_classifies_delta_not_full
        """
        ctx = _published_listing_program()
        _report_overlap_of_two(ctx)

        _report_overlap_of_three(ctx)

        listing = read_listing(ctx.listing_id)
        assert_states(
            listing,
            publication_status=PUB_SUPPRESSED,
            compliance_status=COMPLIANCE_COMPLIANT,
        )
        submission = read_submission(ctx.submission_id)
        assert submission["dac_state"] == DAC_REVOKED, (
            "a FULL classification revokes the issued credential, expected REVOKED, "
            "got {}".format(submission["dac_state"])
        )

    def test_10_an_empty_overlap_classifies_none_and_keeps_the_deadline(self):
        """A security-flagged revision that touches no declared code on an SB1
        specification classifies NONE, which leaves both the deadline and the trigger
        reason exactly where FULL left them while still recording the revision.

        PRD (§3.9): "Rule five classifies `NONE` and leaves `recert_trigger_reason`
        unchanged, and it is where a `security_change` of true lands when the
        specification's baseline is `SB1` and nothing in the overlap is
        security-relevant — a security-flagged revision that nevertheless triggers no
        recertification."

        Design: Difficulty/boundary_precision_check/firmware_overlap_of_exactly_two_codes_classifies_delta_not_full
        """
        ctx = _published_listing_program()
        _report_overlap_of_two(ctx)
        _report_overlap_of_three(ctx)

        _report_empty_overlap(ctx)

        listing = read_listing(ctx.listing_id)
        assert_states(
            listing,
            recert_classification=RECERT_NONE,
            recert_trigger_reason=RECERT_REASON_FEATURE_DELTA,
            latest_firmware_version="1.3.0",
            firmware_revision_count=3,
        )
        assert same_instant(listing["recertification_due_at"], _FULL_DEADLINE), (
            "a NONE classification never rewrites the deadline, expected the 30-day "
            "deadline {} left by the FULL revision, got {!r}".format(
                _FULL_DEADLINE, listing["recertification_due_at"]
            )
        )
