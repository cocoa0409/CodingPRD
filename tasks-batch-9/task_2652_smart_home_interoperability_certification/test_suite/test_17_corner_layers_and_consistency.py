"""Optimistic concurrency, version pinning and immediate read-after-write.

The two version-guarded writes of the service are driven against the counters
they guard, so that a replayed version is refused while writes to neighbouring
rows leave the guard fresh. The pinned certification fee and the frozen test-plan
snapshot are then held against every later event that would move an unpinned
value, and finally every cascaded and derived value is read back on the request
cycle that produced it.
"""

from test_helpers import (
    DAC_ISSUED,
    PLAN_DRAFT,
    PLAN_VOIDED,
    PUB_PUBLISHED,
    RECERT_DELTA,
    RECERT_NONE,
    RECERT_REASON_FEATURE_DELTA,
    REVIEW_RETURNED,
    SESSION_CANCELLED,
    SESSION_IN_PROGRESS,
    SUB_IN_REVIEW,
    SUB_RETURNED_FOR_INFO,
    SUB_WITHDRAWN,
    SYSTEM_USER_ID,
    VOIDED_SPEC_DEPRECATED,
    VOIDED_SUPERSEDED,
    append_results,
    assert_cents,
    assert_reserved_bench_minutes,
    assert_score,
    assert_states,
    assert_version,
    assert_version_incremented,
    build_program,
    deprecate_specification,
    feature,
    issue_test_plan,
    new_feature_set,
    new_session,
    new_specification,
    publish_listing,
    purchase_credits,
    ratify_specification,
    read_laboratory,
    read_ledger,
    read_listing,
    read_readiness,
    read_session,
    read_submission,
    read_test_plan,
    result_line,
    same_instant,
    set_clock,
    start_review,
    start_session,
    submit_submission,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_INVALID_SPECIFICATION_STATE,
    ERR_STALE_LISTING_VERSION,
    ERR_STALE_SUBMISSION_VERSION,
)
from test_helpers.factories import firmware_revision_payload, test_plan_payload
from test_helpers.fixtures import new_test_plan
from test_helpers.test_users import ADMIN_HEADERS, make_member_headers

#: One mandatory lighting feature set worth twenty test cases.
ONE_MANDATORY_FEATURE = [feature("CORE_ONOFF", "MANDATORY", 20)]

#: A mandatory feature set plus an optional one the device may or may not declare.
MANDATORY_PLUS_OPTIONAL = [
    feature("CORE_ONOFF", "MANDATORY", 20),
    feature("CORE_DIM", "OPTIONAL", 10),
]


def _submission_version_ladder():
    """An IN_REVIEW submission carrying the version it reached at every write."""
    ctx = build_program(stage="draft", features=ONE_MANDATORY_FEATURE)
    ctx.version_at_creation = ctx.submission["version"]
    ctx.version_after_submit = submit_submission(ctx.submission_id, ctx.member_id)[
        "version"
    ]
    ctx.version_in_review = start_review(ctx.submission_id)["version"]
    return ctx


def _create_plan_response(submission_id, expected_submission_version):
    """POST /test-plans with a caller-chosen expected_submission_version."""
    return api_client.create_test_plan(
        test_plan_payload(submission_id, expected_submission_version), ADMIN_HEADERS
    )


class TestStaleSubmissionVersionGuardsPlanCreation:
    """The plan-create guard reads the submission's own version counter."""

    def test_01_the_submission_version_increments_on_every_accepted_write(self):
        """Creation, submit, review pick-up and plan creation are four accepted
        writes to the same submission row, so its version walks 1, 2, 3, 4.

        PRD (§2.4): "`version` — an integer that starts at 1 when the row is created
        and increments by one on every mutation of that row."

        Design: Corner/cross_cutting_complexity_layers/a_stale_submission_version_blocks_plan_creation_while_unrelated_writes_do_not
        """
        ctx = _submission_version_ladder()

        assert ctx.version_at_creation == 1, (
            "a freshly created submission starts at version 1, got {}".format(
                ctx.version_at_creation
            )
        )
        assert ctx.version_after_submit == 2, (
            "the submit is one mutation of the submission, expected version 2, "
            "got {}".format(ctx.version_after_submit)
        )
        assert ctx.version_in_review == 3, (
            "the review pick-up is one mutation of the submission, expected version "
            "3, got {}".format(ctx.version_in_review)
        )

        plan = validate_success(
            _create_plan_response(ctx.submission_id, ctx.version_in_review), 201
        )
        after_create = read_submission(ctx.submission_id)

        assert_states(plan, state=PLAN_DRAFT)
        assert_version(after_create, 4, "submission after the plan create")
        assert_version_incremented(after_create["version"], ctx.version_in_review)

    def test_02_replaying_a_consumed_version_is_refused_and_writes_nothing(self):
        """The version the first plan create consumed is refused with 412 on the
        second create, and the refusal leaves the single DRAFT plan and the
        submission's version exactly as they were.

        PRD (§2.8): "**Submission stale-view check.** `expected_submission_version`
        equals the parent submission's current `version` — otherwise
        `ERR_STALE_SUBMISSION_VERSION` (412). Applies to test-plan creation."

        Design: Corner/cross_cutting_complexity_layers/a_stale_submission_version_blocks_plan_creation_while_unrelated_writes_do_not
        """
        ctx = _submission_version_ladder()
        first_plan = validate_success(
            _create_plan_response(ctx.submission_id, ctx.version_in_review), 201
        )

        validate_error(
            _create_plan_response(ctx.submission_id, ctx.version_in_review),
            ERR_STALE_SUBMISSION_VERSION,
        )

        plans, meta = validate_paginated(
            api_client.list_test_plans(
                ADMIN_HEADERS, submission_id=ctx.submission_id, limit=10, offset=0
            )
        )
        assert meta["total_count"] == 1, (
            "the refused create stored no plan, expected total_count 1, got {}".format(
                meta["total_count"]
            )
        )
        assert len(plans) == 1, (
            "exactly one plan exists for the submission, got {}".format(len(plans))
        )
        surviving = read_test_plan(first_plan["id"])
        assert_states(surviving, state=PLAN_DRAFT, voided_reason=None)
        after_refusal = read_submission(ctx.submission_id)
        assert_version(after_refusal, 4, "submission after the refused create")
        assert_states(after_refusal, state=SUB_IN_REVIEW)

    def test_03_writes_to_neighbouring_rows_leave_the_guard_fresh(self):
        """Issuing the plan and booking a bench window write TestPlan, TestSession
        and TestLaboratory rows without bumping the submission, so the version read
        before those writes is still accepted and deliberately supersedes.

        PRD (§3.5): "Creating a plan for a submission that already has a live one is
        therefore not an error but a deliberate supersede: the prior plan is set to
        `VOIDED` with `voided_reason` `SUPERSEDED_BY_NEW_PLAN`, every session of that
        prior plan whose `state` is `SCHEDULED` or `IN_PROGRESS` is set to
        `CANCELLED`, and each such cancellation decrements the owning laboratory's
        `reserved_bench_minutes` by exactly that session's `reserved_minutes`."

        Design: Corner/cross_cutting_complexity_layers/a_stale_submission_version_blocks_plan_creation_while_unrelated_writes_do_not
        """
        ctx = _submission_version_ladder()
        first_plan = new_test_plan(ctx.submission_id, ctx.version_in_review)
        version_before_neighbour_writes = read_submission(ctx.submission_id)["version"]

        issue_test_plan(first_plan["id"])
        session = new_session(first_plan["id"], ctx.laboratory_id)
        after_booking = read_submission(ctx.submission_id)

        assert after_booking["version"] == version_before_neighbour_writes, (
            "issuing a plan and booking a bench window never bump the submission, "
            "expected version {}, got {}".format(
                version_before_neighbour_writes, after_booking["version"]
            )
        )
        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory_id), 240)

        second_plan = validate_success(
            _create_plan_response(
                ctx.submission_id, version_before_neighbour_writes
            ),
            201,
        )

        assert second_plan["id"] != first_plan["id"], (
            "the accepted create stores a new plan, got the same id {}".format(
                second_plan["id"]
            )
        )
        superseded = read_test_plan(first_plan["id"])
        assert_states(
            superseded, state=PLAN_VOIDED, voided_reason=VOIDED_SUPERSEDED
        )
        assert_states(read_session(session["id"]), state=SESSION_CANCELLED)
        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory_id), 0)
        assert_version(
            read_submission(ctx.submission_id), 5, "submission after the supersede"
        )


def _published_listing_program():
    """A published listing whose declared_features hold CORE_ONOFF only, carrying
    the listing version observed before and after publication."""
    ctx = build_program(
        stage="listed",
        features=MANDATORY_PLUS_OPTIONAL,
        declared_codes=["CORE_ONOFF"],
    )
    ctx.version_at_creation = ctx.listing["version"]
    ctx.listing = publish_listing(ctx.listing_id)
    ctx.version_at_publication = ctx.listing["version"]
    return ctx


def _firmware_report_response(listing_id, expected_listing_version, **overrides):
    """POST /listings/{id}/firmware-revisions with a caller-chosen version."""
    return api_client.report_firmware_revision(
        listing_id,
        firmware_revision_payload(expected_listing_version, **overrides),
        ADMIN_HEADERS,
    )


class TestStaleListingVersionBlocksReclassification:
    """The firmware-report guard on a listing whose version publication moved."""

    def test_04_the_version_publication_consumed_no_longer_reports_firmware(self):
        """Publication is itself a write to the listing row, so the version a client
        read at creation is already stale and its firmware report is refused with
        412 without touching a single classification field.

        PRD (§2.9): "A member who reads a listing, then has that listing's
        `declared_features` refreshed by an operator's publication, must re-read the
        listing before reporting a firmware revision."

        Design: Corner/cross_cutting_complexity_layers/a_stale_listing_version_blocks_a_firmware_report_that_would_otherwise_reclassify
        """
        ctx = _published_listing_program()

        assert ctx.version_at_creation == 1, (
            "a freshly created listing starts at version 1, got {}".format(
                ctx.version_at_creation
            )
        )
        assert ctx.version_at_publication == 2, (
            "publication is one mutation of the listing, expected version 2, "
            "got {}".format(ctx.version_at_publication)
        )

        validate_error(
            _firmware_report_response(
                ctx.listing_id,
                ctx.version_at_creation,
                firmware_version="1.1.0",
                changed_feature_codes=["CORE_DIM"],
                security_change=True,
            ),
            ERR_STALE_LISTING_VERSION,
        )

        listing = read_listing(ctx.listing_id)
        assert listing["recert_classification"] is None, (
            "the refused report classified nothing, expected recert_classification "
            "None, got {!r}".format(listing["recert_classification"])
        )
        assert listing["firmware_revision_count"] == 0, (
            "the refused report is not counted, expected firmware_revision_count 0, "
            "got {}".format(listing["firmware_revision_count"])
        )
        assert listing["latest_firmware_version"] is None, (
            "the refused report stored no firmware version, got {!r}".format(
                listing["latest_firmware_version"]
            )
        )
        assert_version(listing, 2, "listing after the refused report")

    def test_05_the_same_body_replayed_at_the_fresh_version_classifies_none(self):
        """The identical body, resent with the version publication produced, is
        accepted: a security-flagged change to a code outside declared_features on
        an SB1 baseline lands on rule five, so nothing is reclassified but the two
        unconditional writes still happen.

        PRD (§3.9): "Rule five classifies `NONE` and leaves `recert_trigger_reason`
        unchanged, and it is where a `security_change` of true lands when the
        specification's baseline is `SB1` and nothing in the overlap is
        security-relevant — a security-flagged revision that nevertheless triggers no
        recertification."

        Design: Corner/cross_cutting_complexity_layers/a_stale_listing_version_blocks_a_firmware_report_that_would_otherwise_reclassify
        """
        ctx = _published_listing_program()
        validate_error(
            _firmware_report_response(
                ctx.listing_id,
                ctx.version_at_creation,
                firmware_version="1.1.0",
                changed_feature_codes=["CORE_DIM"],
                security_change=True,
            ),
            ERR_STALE_LISTING_VERSION,
        )

        accepted = validate_success(
            _firmware_report_response(
                ctx.listing_id,
                ctx.version_at_publication,
                firmware_version="1.1.0",
                changed_feature_codes=["CORE_DIM"],
                security_change=True,
            )
        )

        assert_states(
            accepted,
            recert_classification=RECERT_NONE,
            recert_trigger_reason=None,
            latest_firmware_version="1.1.0",
        )
        assert accepted["recertification_due_at"] is None, (
            "a NONE classification leaves recertification_due_at exactly as it was, "
            "expected None, got {!r}".format(accepted["recertification_due_at"])
        )
        assert accepted["firmware_revision_count"] == 1, (
            "the accepted report raises firmware_revision_count to 1, got {}".format(
                accepted["firmware_revision_count"]
            )
        )
        assert_version(accepted, 3, "listing after the accepted report")

    def test_06_a_consumed_version_cannot_overwrite_the_classification_it_produced(
        self,
    ):
        """Once a report has been accepted the version it was sent with is consumed,
        so a second report quoting it is refused and the stored classification the
        client never re-read survives untouched.

        PRD (§2.9): "Again the operation is legitimate on its face — the listing is
        still `PUBLISHED` and each report is entitled to replace the previous
        report's `recert_classification`, `recert_trigger_reason` and
        `recertification_due_at` — so only the version check prevents a client from
        overwriting a classification it never observed."

        Design: Corner/cross_cutting_complexity_layers/a_stale_listing_version_blocks_a_firmware_report_that_would_otherwise_reclassify
        """
        ctx = _published_listing_program()
        validate_success(
            _firmware_report_response(
                ctx.listing_id,
                ctx.version_at_publication,
                firmware_version="1.1.0",
                changed_feature_codes=["CORE_DIM"],
                security_change=True,
            )
        )

        validate_error(
            _firmware_report_response(
                ctx.listing_id,
                ctx.version_at_publication,
                firmware_version="1.2.0",
                changed_feature_codes=["CORE_ONOFF"],
                security_change=False,
            ),
            ERR_STALE_LISTING_VERSION,
        )

        listing = read_listing(ctx.listing_id)
        assert_states(
            listing,
            recert_classification=RECERT_NONE,
            recert_trigger_reason=None,
            latest_firmware_version="1.1.0",
            publication_status=PUB_PUBLISHED,
        )
        assert listing["firmware_revision_count"] == 1, (
            "the refused second report is not counted, expected "
            "firmware_revision_count 1, got {}".format(
                listing["firmware_revision_count"]
            )
        )
        assert_version(listing, 3, "listing after the refused second report")

    def test_07_the_refused_reclassification_lands_once_the_client_re_reads(self):
        """Sent again with the version the first report left behind, the same body
        reclassifies the listing to DELTA and dates the deadline ninety days out from
        the logical clock, while the publication and the credential stand.

        PRD (§3.9): "The deadline follows the classification: `FULL` sets
        `recertification_due_at` to the logical clock's current instant advanced by 30
        days, `DELTA` advances it by 90 days, and `NONE` leaves
        `recertification_due_at` exactly as it was, including null."

        Design: Corner/cross_cutting_complexity_layers/a_stale_listing_version_blocks_a_firmware_report_that_would_otherwise_reclassify
        """
        ctx = _published_listing_program()
        first = validate_success(
            _firmware_report_response(
                ctx.listing_id,
                ctx.version_at_publication,
                firmware_version="1.1.0",
                changed_feature_codes=["CORE_DIM"],
                security_change=True,
            )
        )

        # The overlap is the single non-security-relevant CORE_ONOFF, so rule four
        # applies and the clock still stands at 2026-09-02T12:00:00Z.
        reclassified = validate_success(
            _firmware_report_response(
                ctx.listing_id,
                first["version"],
                firmware_version="1.2.0",
                changed_feature_codes=["CORE_ONOFF"],
                security_change=False,
            )
        )

        assert_states(
            reclassified,
            recert_classification=RECERT_DELTA,
            recert_trigger_reason=RECERT_REASON_FEATURE_DELTA,
            latest_firmware_version="1.2.0",
            publication_status=PUB_PUBLISHED,
        )
        due_at = reclassified["recertification_due_at"]
        assert due_at is not None and same_instant(due_at, "2026-12-01T12:00:00Z"), (
            "DELTA dates the deadline 90 days after 2026-09-02T12:00:00Z, expected "
            "2026-12-01T12:00:00Z, got {!r}".format(due_at)
        )
        assert reclassified["firmware_revision_count"] == 2, (
            "the second accepted report raises firmware_revision_count to 2, "
            "got {}".format(reclassified["firmware_revision_count"])
        )
        assert_version(reclassified, 4, "listing after the reclassification")
        assert_states(read_submission(ctx.submission_id), dac_state=DAC_ISSUED)


def _pinned_program():
    """An IN_REVIEW submission on a two-feature specification whose fee and plan
    snapshot were both fixed at creation time."""
    ctx = build_program(
        stage="plan",
        features=MANDATORY_PLUS_OPTIONAL,
        declared_codes=["CORE_ONOFF", "CORE_DIM"],
    )
    ctx.required_at_creation = ctx.plan["required_case_count"]
    ctx.mandatory_at_creation = ctx.plan["mandatory_case_count"]
    ctx.optional_at_creation = ctx.plan["optional_case_count"]
    ctx.included_at_creation = list(ctx.plan["included_feature_set_ids"])
    ctx.plan = issue_test_plan(ctx.plan_id)
    return ctx


def _ratify_successor_specification(ctx):
    """A stricter successor baseline that supersedes the pinned specification."""
    successor = new_specification(
        security_baseline_level="SB3",
        effective_date="2026-09-05T00:00:00Z",
        supersedes_specification_id=ctx.specification_id,
    )
    new_feature_set(
        successor["id"],
        device_type="LIGHTING",
        feature_code="CORE_ONOFF",
        obligation="MANDATORY",
        test_case_count=40,
        security_relevant=True,
    )
    ratify_specification(successor["id"])
    return successor["id"]


class TestPinnedFeeAndPlanSnapshotSurviveLaterEvents:
    """Everything that happens after creation leaves the pinned values alone."""

    def test_08_a_stricter_successor_and_fresh_credit_do_not_move_the_fee(self):
        """The fee pinned from LIGHTING, two declared features, SB1 and an ADOPTER
        tier stays at 150000 cents once a stricter SB3 successor has been ratified
        and the member has bought half a million cents of extra credit.

        PRD (§3.4): "The **certification fee** is computed once, at creation, and
        pinned onto `certification_fee_cents`; it is never recomputed, so a member
        that later climbs from `PARTICIPANT` to `PROMOTER`, or a specification that is
        later amended, does not move an already-pinned fee."

        Design: Corner/cross_cutting_complexity_layers/the_fee_and_the_plan_snapshot_survive_everything_that_happens_afterwards
        """
        ctx = _pinned_program()

        assert_cents(ctx.certification_fee_cents, 150000, "fee pinned at creation")
        assert ctx.required_at_creation == 30, (
            "the closure over CORE_ONOFF plus CORE_DIM is 30 cases at creation, "
            "got {}".format(ctx.required_at_creation)
        )

        _ratify_successor_specification(ctx)
        purchase_credits(ctx.member_id, 500000)

        submission = read_submission(ctx.submission_id)
        assert_cents(
            submission["certification_fee_cents"], 150000, "certification_fee_cents"
        )
        assert_cents(submission["fee_escrowed_cents"], 150000, "fee_escrowed_cents")
        assert submission["specification_id"] == ctx.specification_id, (
            "the submission stays pinned to the specification it was created "
            "against, expected {}, got {}".format(
                ctx.specification_id, submission["specification_id"]
            )
        )

    def test_09_the_deprecation_cascade_rewrites_review_state_and_no_money(self):
        """Deprecating the pinned baseline drives the submission back to
        RETURNED_FOR_INFO under the SYSTEM reviewer with revision_round 1, and moves
        neither the pinned fee nor the escrow.

        PRD (§3.1): "**Hop one** takes every submission pinned to this version whose
        `state` is `SUBMITTED`, `IN_REVIEW` or `RETURNED_FOR_INFO` and sets
        `conformance_review_state` to `RETURNED`, `state` to `RETURNED_FOR_INFO`, and
        `conformance_reviewer_user_id` to the literal `SYSTEM`; each such submission's
        `revision_round` is raised by one but never past the ceiling of 2, so a
        submission already at 2 stays at 2 rather than overflowing."

        Design: Corner/cross_cutting_complexity_layers/the_fee_and_the_plan_snapshot_survive_everything_that_happens_afterwards
        """
        ctx = _pinned_program()
        _ratify_successor_specification(ctx)

        deprecate_specification(ctx.specification_id)

        submission = read_submission(ctx.submission_id)
        assert_states(
            submission,
            state=SUB_RETURNED_FOR_INFO,
            conformance_review_state=REVIEW_RETURNED,
            conformance_reviewer_user_id=SYSTEM_USER_ID,
            revision_round=1,
        )
        assert_cents(
            submission["certification_fee_cents"], 150000, "certification_fee_cents"
        )
        assert_cents(submission["fee_escrowed_cents"], 150000, "fee_escrowed_cents")

    def test_10_a_voided_plan_still_carries_the_closure_it_froze_at_creation(self):
        """The cascade voids the plan, and the voided plan still reports the exact
        feature sets and case counts its creation-time closure produced.

        PRD (§3.5): "The plan's scope is resolved once, at creation, by a **closure
        computation** over the specification's feature graph, and it is never
        recomputed."

        Design: Corner/cross_cutting_complexity_layers/the_fee_and_the_plan_snapshot_survive_everything_that_happens_afterwards
        """
        ctx = _pinned_program()
        _ratify_successor_specification(ctx)
        deprecate_specification(ctx.specification_id)

        plan = read_test_plan(ctx.plan_id)

        assert_states(
            plan, state=PLAN_VOIDED, voided_reason=VOIDED_SPEC_DEPRECATED
        )
        expected_ids = [
            ctx.feature_set_ids["CORE_DIM"],
            ctx.feature_set_ids["CORE_ONOFF"],
        ]
        assert plan["included_feature_set_ids"] == expected_ids, (
            "the frozen closure holds both feature sets ordered by feature_code "
            "ascending, expected {}, got {}".format(
                expected_ids, plan["included_feature_set_ids"]
            )
        )
        assert plan["required_case_count"] == ctx.required_at_creation == 30, (
            "the voided plan keeps its creation-time required_case_count of 30, "
            "got {}".format(plan["required_case_count"])
        )
        assert plan["mandatory_case_count"] == ctx.mandatory_at_creation == 20, (
            "the voided plan keeps its creation-time mandatory_case_count of 20, "
            "got {}".format(plan["mandatory_case_count"])
        )
        assert plan["optional_case_count"] == ctx.optional_at_creation == 10, (
            "the voided plan keeps its creation-time optional_case_count of 10, "
            "got {}".format(plan["optional_case_count"])
        )

    def test_11_the_pin_that_survived_is_the_pin_that_blocks_the_resubmit(self):
        """Because the submission still points at the deprecated baseline, the
        resubmit RETURNED_FOR_INFO would otherwise allow is refused, and no second
        escrow is taken against the enlarged balance.

        PRD (§3.4): "It requires `RATIFIED` status on the pinned specification,
        `good_standing` on the member, and the same `SB2`/`SB3` declaration pair."

        Design: Corner/cross_cutting_complexity_layers/the_fee_and_the_plan_snapshot_survive_everything_that_happens_afterwards
        """
        ctx = _pinned_program()
        _ratify_successor_specification(ctx)
        purchase_credits(ctx.member_id, 500000)
        deprecate_specification(ctx.specification_id)

        validate_error(
            api_client.submit_submission(
                ctx.submission_id, headers=make_member_headers(ctx.member_id)
            ),
            ERR_INVALID_SPECIFICATION_STATE,
        )

        assert_states(read_submission(ctx.submission_id), state=SUB_RETURNED_FOR_INFO)
        ledger = read_ledger(ctx.member_id, variant="AVAILABLE")
        assert_cents(ledger["credits_purchased_cents"], 1500000, "credits_purchased_cents")
        assert_cents(ledger["escrowed_credit_cents"], 150000, "escrowed_credit_cents")
        assert_cents(ledger["balance_cents"], 1350000, "AVAILABLE balance_cents")


def _immediate_consistency_program():
    """An IN_PROGRESS session on a freshly booked bench, keeping the response body
    of each write that produced a derived value."""
    ctx = build_program(stage="submitted", features=ONE_MANDATORY_FEATURE)
    ctx.escrowed_at_submit = ctx.submission["fee_escrowed_cents"]
    ctx.submission = start_review(ctx.submission_id)
    plan = new_test_plan(ctx.submission_id, ctx.submission["version"])
    ctx.plan_id = plan["id"]
    ctx.plan = issue_test_plan(ctx.plan_id)
    ctx.booked_session = new_session(ctx.plan_id, ctx.laboratory_id)
    ctx.session_id = ctx.booked_session["id"]
    ctx.laboratory_after_booking = read_laboratory(ctx.laboratory_id)
    set_clock("2026-09-02T09:00:00Z")
    ctx.session = start_session(ctx.session_id, ctx.laboratory_id)
    return ctx


class TestEveryDerivedValueIsReadableImmediately:
    """No derived or cascaded value waits for a later request to become true."""

    def test_12_booking_answers_with_the_reserved_minutes_it_has_already_charged(self):
        """The booking response carries the 240 minutes computed from its window, and
        the owning laboratory's occupancy figure already holds those minutes on the
        very next read.

        PRD (§3.6): "An accepted booking stores the session in `state` `SCHEDULED`
        with `started_at` and `completed_at` null, `completed_late` false,
        `result_lines` an empty array, `disputed_line_count` 0, and `reserved_minutes`
        computed from the window; the laboratory's `reserved_bench_minutes` rises by
        that figure immediately."

        Design: Corner/consistency_model/every_cascaded_and_derived_value_is_readable_in_the_same_request
        """
        ctx = _immediate_consistency_program()

        assert ctx.booked_session["reserved_minutes"] == 240, (
            "the 09:00-13:00 window is 240 minutes and the create response says so, "
            "got {}".format(ctx.booked_session["reserved_minutes"])
        )
        assert_reserved_bench_minutes(ctx.laboratory_after_booking, 240)
        assert_cents(ctx.escrowed_at_submit, 135000, "fee_escrowed_cents at submit")
        # Starting the session moves no minutes: they were charged at booking.
        assert_states(ctx.session, state=SESSION_IN_PROGRESS)
        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory_id), 240)

    def test_13_the_provisional_score_is_stored_by_the_write_that_caused_it(self):
        """The result-line submission answers with a session, yet the derived
        readiness figure it recomputed is already on the submission and already
        agrees with the computed readiness read.

        PRD (§3.8): "The `PROVISIONAL` figure is recomputed and written to
        `provisional_readiness_score` after every result-line submission and after
        every plugfest outcome recording; it is null until the first result line
        exists."

        Design: Corner/consistency_model/every_cascaded_and_derived_value_is_readable_in_the_same_request
        """
        ctx = _immediate_consistency_program()

        appended = append_results(
            ctx.session_id,
            ctx.laboratory_id,
            [result_line(ctx.feature_set_ids["CORE_ONOFF"], "PASS")],
        )

        assert len(appended["result_lines"]) == 1, (
            "the append response carries the stored line, expected 1, got {}".format(
                len(appended["result_lines"])
            )
        )
        submission = read_submission(ctx.submission_id)
        assert_score(
            submission["provisional_readiness_score"],
            "85.00",
            "provisional_readiness_score",
        )
        readiness = read_readiness(ctx.submission_id, variant="PROVISIONAL")
        assert_score(readiness["score"], "85.00", "PROVISIONAL readiness score")
        assert readiness["mandatory_case_count"] == 20, (
            "the plan's mandatory closure is 20 cases, got {}".format(
                readiness["mandatory_case_count"]
            )
        )
        assert readiness["mandatory_passed_cases"] == 20, (
            "the single PASS covers all 20 mandatory cases, got {}".format(
                readiness["mandatory_passed_cases"]
            )
        )
        assert readiness["optional_case_count"] == 0, (
            "no optional feature set is in scope, expected 0, got {}".format(
                readiness["optional_case_count"]
            )
        )
        assert readiness["counted_session_count"] == 1, (
            "PROVISIONAL counts the IN_PROGRESS session, expected 1, got {}".format(
                readiness["counted_session_count"]
            )
        )
        assert readiness["late_session_count"] == 0, (
            "nothing is late before it is complete, expected 0, got {}".format(
                readiness["late_session_count"]
            )
        )
        assert readiness["plugfest_credit_count"] == 0, (
            "no plugfest was attended, expected 0, got {}".format(
                readiness["plugfest_credit_count"]
            )
        )

    def test_14_the_withdrawal_body_carries_its_whole_cascade_at_once(self):
        """One withdrawal releases the escrow, voids the plan, cancels the live
        session and gives the laboratory its bench back; the response body already
        shows the released escrow and every touched row reads correctly on the first
        request after it.

        PRD (§3.8): "It sets `state` to `WITHDRAWN`, releases any escrow back to
        `credit_balance_cents` and zeroes `fee_escrowed_cents` — a no-op from `DRAFT`,
        where `fee_escrowed_cents` is already 0, and observable from the other three,
        where it equals `certification_fee_cents` — voids the submission's
        non-`VOIDED` test plan with `voided_reason` `SUPERSEDED_BY_NEW_PLAN`, and
        cancels every `SCHEDULED` or `IN_PROGRESS` session of that plan, each
        cancellation decrementing the owning laboratory's `reserved_bench_minutes` by
        exactly that session's `reserved_minutes`."

        Design: Corner/consistency_model/every_cascaded_and_derived_value_is_readable_in_the_same_request
        """
        ctx = _immediate_consistency_program()
        append_results(
            ctx.session_id,
            ctx.laboratory_id,
            [result_line(ctx.feature_set_ids["CORE_ONOFF"], "PASS")],
        )

        withdrawn = validate_success(
            api_client.withdraw_submission(
                ctx.submission_id, headers=make_member_headers(ctx.member_id)
            )
        )

        assert_states(withdrawn, state=SUB_WITHDRAWN)
        assert_cents(
            withdrawn["fee_escrowed_cents"], 0, "fee_escrowed_cents in the response"
        )
        assert_cents(
            withdrawn["certification_fee_cents"], 135000, "certification_fee_cents"
        )
        assert_states(
            read_test_plan(ctx.plan_id),
            state=PLAN_VOIDED,
            voided_reason=VOIDED_SUPERSEDED,
        )
        assert_states(read_session(ctx.session_id), state=SESSION_CANCELLED)
        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory_id), 0)
        ledger = read_ledger(ctx.member_id, variant="AVAILABLE")
        assert_cents(ledger["escrowed_credit_cents"], 0, "escrowed_credit_cents")
        assert_cents(ledger["balance_cents"], 1000000, "AVAILABLE balance_cents")
