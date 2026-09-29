"""Guards that refuse a request the docket cannot honour, and the order they fire in."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_field_values,
    assert_fields_null,
    assert_millisecond_timestamp,
    assert_pagination_meta,
    assert_unchanged,
    assert_unit_ledger_conserved,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    DIRECTOR_HEADERS,
    INTAKE_HEADERS,
    OFFICER_HEADERS,
)

# The clock the docket chain stands at once the statutory report is filed and the
# plan approved; nothing in this file moves it unless a temporal gate demands it.
APPROVAL_CLOCK = "2026-03-13T00:00:00Z"

# A press release that is due a week after approval and embargoed for five days
# beyond that, so the two temporal gates on release are violated together.
PRESS_RELEASE = {
    "channel": "PRESS_RELEASE",
    "scheduled_for": "2026-03-20T00:00:00Z",
    "embargo_until": "2026-03-25T00:00:00Z",
    "reach_count": 500000,
}
SCHEDULE_INSTANT = "2026-03-20T00:00:00Z"
EMBARGO_INSTANT = "2026-03-25T00:00:00Z"

# A direct notice due the instant the stop-sale takes effect, so it can be
# released without moving the clock away from approval.
NOTICE_DUE_AT_APPROVAL = {"scheduled_for": APPROVAL_CLOCK}

DUPLICATE_INTAKE_REPORT = {
    "report_channel": "WEB_FORM",
    "incident_date": "2026-02-10T00:00:00Z",
    "narrative": "Kettle lid released a jet of steam onto the user's hand.",
}


def _frozen_model_carrying_a_fresh_analysis(api):
    """A model frozen by a reportable determination, with a new ANALYZED pattern."""
    env = fx.determined_evaluation_env(api)
    model = fx.get_product_model(api, env["model_id"])
    env["model"] = model
    second = fx.create_pattern(
        api, env["model_id"], model["version"], analysis_basis="FINAL"
    )
    env["second_pattern"] = second
    env["second_pattern_id"] = second["id"]
    return env


class TestFrozenModelPostureBlocksTheEvidenceBase:
    """A grandparent model in FROZEN posture stops both walk-backs of an analysis."""

    def test_recomputing_an_analysed_pattern_under_a_frozen_model_is_refused(self, api):
        """The recompute is stopped by the model's posture, not by the pattern's status.

        The contract states: "Recomputation requires the pattern to be in
        `ANALYZED` — any other status draws `ERR_PATTERN_STATE_INVALID` — and is
        additionally blocked with `ERR_MODEL_POSTURE_FROZEN` while the product
        model behind it is `FROZEN`, because narrowing the evidence base under an
        open escalation is not permitted." The posture got there because "a
        reportability determination of `REPORTABLE` sets `hazard_posture` to
        `FROZEN`."

        Design: Corner/validations/frozen_model_posture_blocks_both_recompute_and_dismissal
        """
        env = _frozen_model_carrying_a_fresh_analysis(api)

        assert_field_values(
            env["model"], hazard_posture="FROZEN", open_escalation_count=3
        )
        assert_field_values(env["second_pattern"], pattern_status="ANALYZED")

        escalated_before = fx.get_incident(api, env["incidents"][0]["id"])

        validate_error(
            api.recompute_hazard_pattern(
                env["second_pattern_id"],
                {"analysis_basis": "PRELIMINARY"},
                headers=OFFICER_HEADERS,
            ),
            "ERR_MODEL_POSTURE_FROZEN",
            409,
        )

        after = fx.get_pattern(api, env["second_pattern_id"])
        assert_field_values(after, pattern_status="ANALYZED")
        assert_unchanged(
            env["second_pattern"],
            after,
            "analysis_basis",
            "incident_count",
            "severity_sum",
            "risk_index",
            "analyzed_at",
            "version",
        )
        assert_unchanged(
            escalated_before,
            fx.get_incident(api, env["incidents"][0]["id"]),
            "status",
            "hazard_pattern_id",
            "version",
        )

    def test_dismissing_an_analysed_pattern_under_a_frozen_model_is_refused(self, api):
        """The dismissal is refused, so the escalated cluster is never released.

        The contract states: "This branch is gated on containment: it is refused
        with `ERR_MODEL_POSTURE_FROZEN` while the model is `FROZEN`, and like the
        confirm branch it leaves `hazard_posture` unchanged." Both blocked verbs
        answer alike because "both re-running a pattern's analysis and dismissing
        a pattern are refused with `ERR_MODEL_POSTURE_FROZEN` (HTTP 409) while the
        model behind the pattern is `FROZEN`."

        Design: Corner/validations/frozen_model_posture_blocks_both_recompute_and_dismissal
        """
        env = _frozen_model_carrying_a_fresh_analysis(api)

        assert_field_values(
            env["model"], hazard_posture="FROZEN", open_escalation_count=3
        )
        cluster_before = [
            fx.get_incident(api, row["id"]) for row in env["incidents"]
        ]

        validate_error(
            api.adjudicate_hazard_pattern(
                env["second_pattern_id"],
                f.adjudicate_payload(decision="DISMISSED"),
                headers=OFFICER_HEADERS,
            ),
            "ERR_MODEL_POSTURE_FROZEN",
            409,
        )

        assert_field_values(
            fx.get_pattern(api, env["second_pattern_id"]), pattern_status="ANALYZED"
        )
        for before in cluster_before:
            assert_unchanged(
                before,
                fx.get_incident(api, before["id"]),
                "status",
                "hazard_pattern_id",
                "escalation_deadline_at",
                "version",
            )
        assert_field_values(
            fx.get_product_model(api, env["model_id"]),
            hazard_posture="FROZEN",
            open_escalation_count=3,
        )


class TestAuditVisitBeforeTheStopSaleTakesEffect:
    """A visit booked while the retailer is still CLEAR has nothing to inspect."""

    def test_scheduling_against_a_pending_notification_reports_no_active_stop_sale(
        self, api
    ):
        """The pending notification is admitted, so the retailer's posture decides.

        The contract states: "The notification under audit must not already be
        `VERIFIED` — any of `PENDING`, `ISSUED`, `DELINQUENT` and `ACKNOWLEDGED` is
        acceptable, and the terminal state draws `ERR_NOTIFICATION_STATE_INVALID`.
        The retailer identified by that notification's `retailer_id` must actually
        be under an active stop-sale, meaning its `compliance_posture` is
        `STOP_SALE_ACTIVE` or `DELINQUENT`; a `CLEAR` retailer has nothing to
        inspect and the request is refused with `ERR_NO_ACTIVE_STOP_SALE` (HTTP
        409)." The office spells the ordering out: "Scheduling an audit visit
        against a notification that is still `PENDING` passes the cross-entity
        state check at step 10 — `PENDING` is not the terminal `VERIFIED` state —
        and is then stopped at step 12 by `ERR_NO_ACTIVE_STOP_SALE`, because the
        retailer is not yet under an active stop-sale."

        Design: Corner/validations/audit_visit_scheduled_before_the_stop_sale_takes_effect_is_refused
        """
        env = fx.draft_recall_env(api)

        assert_field_values(env["recall"], plan_status="DRAFT")
        assert_field_values(
            env["notification"], status="PENDING", stop_sale_required=False
        )
        assert_field_values(
            env["retailer"], compliance_posture="CLEAR", open_stop_sale_count=0
        )

        validate_error(
            api.create_audit_visit(
                f.audit_visit_payload(env["notification_id"]), headers=AUDITOR_HEADERS
            ),
            "ERR_NO_ACTIVE_STOP_SALE",
            409,
        )

        assert_field_values(
            fx.get_notification(api, env["notification_id"]),
            status="PENDING",
            stop_sale_required=False,
        )
        assert_field_values(
            fx.get_retailer(api, env["retailer_id"]),
            compliance_posture="CLEAR",
            open_stop_sale_count=0,
            verified_removal_count=0,
        )

        rows, meta = validate_paginated(
            api.list_audit_visits(
                {"retailer_notification_id": env["notification_id"]},
                headers=AUDITOR_HEADERS,
            )
        )
        assert rows == [], f"the refused visit was persisted anyway: {rows}"
        assert_pagination_meta(meta, total_count=0, has_more=False)


def _acknowledged_notification_with_a_scheduled_visit(api):
    """A monitoring recall whose only notification is acknowledged at zero units."""
    env = fx.monitoring_recall_env(api)
    env["notification"] = fx.acknowledge_notification(
        api, env["notification_id"], units_on_shelf_reported=0
    )
    visit = fx.create_audit_visit(api, env["notification_id"])
    env["visit"] = visit
    env["visit_id"] = visit["id"]
    return env


class TestShelfRemovalGuardsRejectUnverifiedAndContradictoryVisits:
    """Evidence must exist before verification, and a verdict may not lie."""

    def test_verifying_with_only_a_scheduled_visit_on_file_is_refused(self, api):
        """A visit that has not been walked is not evidence of shelf removal.

        The contract states: "It requires the notification to be `ACKNOWLEDGED`,
        otherwise `ERR_NOTIFICATION_STATE_INVALID`, and it requires evidence: at
        least one audit visit on this `retailer_notification_id` must be
        `COMPLETED` with `verdict` `PASS`, otherwise the request is refused with
        `ERR_SHELF_REMOVAL_UNVERIFIED` (HTTP 409)."

        Design: Corner/validations/shelf_removal_guards_reject_unverified_and_contradictory_visits
        """
        env = _acknowledged_notification_with_a_scheduled_visit(api)

        assert_field_values(env["notification"], status="ACKNOWLEDGED")
        assert_field_values(env["visit"], status="SCHEDULED", verdict="PENDING")
        assert_fields_null(env["visit"], "shelf_units_found", "completed_at")

        validate_error(
            api.verify_notification(env["notification_id"], headers=AUDITOR_HEADERS),
            "ERR_SHELF_REMOVAL_UNVERIFIED",
            409,
        )

        notification = fx.get_notification(api, env["notification_id"])
        assert_field_values(notification, status="ACKNOWLEDGED")
        assert_fields_null(notification, "verified_at")
        assert_field_values(
            fx.get_recall(api, env["recall_id"]),
            plan_status="MONITORING",
            notification_status="IN_PROGRESS",
        )
        assert_field_values(
            fx.get_retailer(api, env["retailer_id"]),
            compliance_posture="STOP_SALE_ACTIVE",
            open_stop_sale_count=1,
            verified_removal_count=0,
        )

    def test_a_passing_verdict_claimed_with_units_still_on_the_shelf_is_refused(
        self, api
    ):
        """A PASS may not be recorded while recalled units remain on shelves.

        The contract states: "The verdict may never contradict the count: a `PASS`
        requires `shelf_units_found` to be exactly 0, and a `FAIL` requires
        `shelf_units_found` to be greater than 0. One remaining unit is a `FAIL`; a
        `FAIL` claimed with a count of 0 is equally invalid. Either contradiction is
        refused with `ERR_SHELF_UNITS_PRESENT` (HTTP 422)."

        Design: Corner/validations/shelf_removal_guards_reject_unverified_and_contradictory_visits
        """
        env = _acknowledged_notification_with_a_scheduled_visit(api)

        validate_error(
            api.complete_audit_visit(
                env["visit_id"],
                f.complete_visit_payload(verdict="PASS", shelf_units_found=3),
                headers=AUDITOR_HEADERS,
            ),
            "ERR_SHELF_UNITS_PRESENT",
            422,
        )

        visit = fx.get_audit_visit(api, env["visit_id"])
        assert_field_values(visit, status="SCHEDULED", verdict="PENDING")
        assert_fields_null(visit, "shelf_units_found", "completed_at")
        assert_unchanged(env["visit"], visit, "version")

        notification = fx.get_notification(api, env["notification_id"])
        assert_field_values(notification, status="ACKNOWLEDGED")
        assert_fields_null(notification, "verified_at")

    def test_a_failing_verdict_claimed_with_an_empty_shelf_is_equally_refused(
        self, api
    ):
        """The guard is an equivalence, so a FAIL at zero units is refused too.

        The contract states: "One remaining unit is a `FAIL`; a `FAIL` claimed with
        a count of 0 is equally invalid. Either contradiction is refused with
        `ERR_SHELF_UNITS_PRESENT` (HTTP 422)."

        Design: Corner/validations/shelf_removal_guards_reject_unverified_and_contradictory_visits
        """
        env = _acknowledged_notification_with_a_scheduled_visit(api)

        validate_error(
            api.complete_audit_visit(
                env["visit_id"],
                f.complete_visit_payload(verdict="FAIL", shelf_units_found=0),
                headers=AUDITOR_HEADERS,
            ),
            "ERR_SHELF_UNITS_PRESENT",
            422,
        )

        visit = fx.get_audit_visit(api, env["visit_id"])
        assert_field_values(visit, status="SCHEDULED", verdict="PENDING")
        assert_fields_null(visit, "shelf_units_found", "completed_at")
        assert_unchanged(env["visit"], visit, "version")

        notification = fx.get_notification(api, env["notification_id"])
        assert_field_values(notification, status="ACKNOWLEDGED")
        assert_fields_null(notification, "verified_at")


def _acknowledged_notification_with_a_passing_visit(api):
    """The same acknowledged notification, with its audit visit walked and passed."""
    env = _acknowledged_notification_with_a_scheduled_visit(api)
    env["visit"] = fx.complete_audit_visit(
        api, env["visit_id"], verdict="PASS", shelf_units_found=0
    )
    return env


class TestVerificationSucceedsOnceAPassingVisitExists:
    """The positive half of the evidence gate, and the two cascades behind it."""

    def test_a_completed_passing_visit_carries_the_notification_to_verified(self, api):
        """The verify that was refused without evidence now reaches the terminal state.

        The contract states: "Verifying shelf removal — the act of a
        `SafetyDirector` or `FieldAuditor` — advances the notification
        `ACKNOWLEDGED → VERIFIED` and stamps `verified_at` with the logical clock."
        The evidence is the visit itself: "On success the visit advances `SCHEDULED
        → COMPLETED`, its `verdict` moves from `PENDING` to the recorded value, and
        `completed_at` is stamped with the logical clock."

        Design: Corner/validations/verification_succeeds_once_a_passing_visit_exists_and_satisfies_the_recall
        """
        env = _acknowledged_notification_with_a_passing_visit(api)

        assert_field_values(
            env["visit"], status="COMPLETED", verdict="PASS", shelf_units_found=0
        )
        assert env["visit"]["completed_at"].startswith("2026-03-14T00:00:00"), (
            f"completed_at is not the logical clock: {env['visit']['completed_at']}"
        )

        notification = validate_success(
            api.verify_notification(env["notification_id"], headers=AUDITOR_HEADERS)
        )

        assert_field_values(notification, status="VERIFIED")
        assert_millisecond_timestamp(notification["verified_at"])
        assert notification["verified_at"].startswith("2026-03-14T00:00:00"), (
            f"verified_at is not the logical clock: {notification['verified_at']}"
        )
        assert_field_values(
            fx.get_notification(api, env["notification_id"]), status="VERIFIED"
        )

    def test_verification_settles_the_retailer_counters_and_satisfies_the_recall(
        self, api
    ):
        """The two sibling cascades are only visible through the retailer and recall.

        The contract states: "Verification then cascades twice. On the retailer,
        `open_stop_sale_count` is decremented by 1 and `verified_removal_count` is
        incremented by 1, and `compliance_posture` is set to `CLEAR` when
        `open_stop_sale_count` reaches 0. On the recall, when this was the last
        notification of that recall not yet `VERIFIED` — that is, when every
        notification on the recall is now `VERIFIED` — the `notification_status`
        moves `IN_PROGRESS → SATISFIED`, which is the precondition closure will
        later demand."

        Design: Corner/validations/verification_succeeds_once_a_passing_visit_exists_and_satisfies_the_recall
        """
        env = _acknowledged_notification_with_a_passing_visit(api)

        assert_field_values(
            fx.get_retailer(api, env["retailer_id"]),
            compliance_posture="STOP_SALE_ACTIVE",
            open_stop_sale_count=1,
            verified_removal_count=0,
        )
        assert_field_values(
            fx.get_recall(api, env["recall_id"]),
            plan_status="MONITORING",
            notification_status="IN_PROGRESS",
        )

        fx.verify_notification(api, env["notification_id"])

        assert_field_values(
            fx.get_retailer(api, env["retailer_id"]),
            compliance_posture="CLEAR",
            open_stop_sale_count=0,
            verified_removal_count=1,
        )
        assert_field_values(
            fx.get_recall(api, env["recall_id"]),
            plan_status="MONITORING",
            notification_status="SATISFIED",
        )


def _approved_recall_with_an_embargoed_press_release(api):
    """An approved recall carrying a press release that is both early and embargoed."""
    env = fx.approved_recall_env(api)
    press = fx.create_notice(api, env["recall_id"], **PRESS_RELEASE)
    env["press"] = press
    env["press_id"] = press["id"]
    return env


class TestNoticeReleaseIsGatedByScheduleThenByEmbargo:
    """Two temporal gates on one endpoint whose relative order is observable."""

    def test_a_notice_that_is_both_early_and_embargoed_reports_the_schedule_first(
        self, api
    ):
        """Clearing the schedule gate is what makes the embargo the reported reason.

        The contract states: "The logical clock must have reached `scheduled_for`,
        with a non-strict comparison so that releasing at exactly `scheduled_for` is
        allowed; releasing earlier is refused with `ERR_NOTICE_NOT_DUE` (HTTP 409).
        And when `embargo_until` is non-null, the logical clock must also have
        reached it, again non-strictly, so releasing at exactly `embargo_until` is
        allowed and releasing earlier is refused with `ERR_EMBARGO_ACTIVE` (HTTP
        409). Because the schedule check precedes the embargo check, a notice that
        is both un-due and embargoed reports the schedule problem first."

        Design: Corner/validations/notice_release_is_gated_by_schedule_then_by_embargo_in_that_order
        """
        env = _approved_recall_with_an_embargoed_press_release(api)

        assert_field_values(env["press"], status="SCHEDULED", channel="PRESS_RELEASE")
        assert_fields_null(env["press"], "released_at")
        assert env["press"]["scheduled_for"].startswith("2026-03-20T00:00:00"), (
            f"scheduled_for was not stored as supplied: {env['press']['scheduled_for']}"
        )
        assert env["press"]["embargo_until"].startswith("2026-03-25T00:00:00"), (
            f"embargo_until was not stored as supplied: {env['press']['embargo_until']}"
        )

        validate_error(
            api.release_consumer_notice(env["press_id"], headers=OFFICER_HEADERS),
            "ERR_NOTICE_NOT_DUE",
            409,
        )
        still_scheduled = fx.get_notice(api, env["press_id"])
        assert_field_values(still_scheduled, status="SCHEDULED")
        assert_fields_null(still_scheduled, "released_at")

        fx.set_clock(api, SCHEDULE_INSTANT)

        validate_error(
            api.release_consumer_notice(env["press_id"], headers=OFFICER_HEADERS),
            "ERR_EMBARGO_ACTIVE",
            409,
        )
        after = fx.get_notice(api, env["press_id"])
        assert_field_values(after, status="SCHEDULED")
        assert_fields_null(after, "released_at")
        assert_unchanged(env["press"], after, "version", "scheduled_for", "embargo_until")

    def test_release_at_exactly_the_embargo_instant_clears_both_gates(self, api):
        """Both comparisons are non-strict, so the embargo instant itself releases.

        The contract states: "when `embargo_until` is non-null, the logical clock
        must also have reached it, again non-strictly, so releasing at exactly
        `embargo_until` is allowed and releasing earlier is refused with
        `ERR_EMBARGO_ACTIVE` (HTTP 409)." Release is per notice, because "notices on
        other channels of the same recall are untouched, so a fresh press release
        never supersedes a standing web posting."

        Design: Corner/validations/notice_release_is_gated_by_schedule_then_by_embargo_in_that_order
        """
        env = _approved_recall_with_an_embargoed_press_release(api)

        fx.set_clock(api, EMBARGO_INSTANT)
        released = validate_success(
            api.release_consumer_notice(env["press_id"], headers=OFFICER_HEADERS)
        )

        assert_field_values(released, status="RELEASED")
        assert_millisecond_timestamp(released["released_at"])
        assert released["released_at"].startswith("2026-03-25T00:00:00"), (
            f"released_at is not the logical clock: {released['released_at']}"
        )
        assert_field_values(fx.get_notice(api, env["press_id"]), status="RELEASED")

        direct = fx.get_notice(api, env["notice_id"])
        assert_field_values(direct, channel="DIRECT_NOTICE", status="SCHEDULED")
        assert_fields_null(direct, "released_at")


def _merge_as_duplicate_of(api, incident_id, target_id):
    """Attempt to fold one incident into a named surviving primary."""
    return api.dispose_incident(
        incident_id,
        f.dispose_payload(
            disposition="MERGED_DUPLICATE", duplicate_of_incident_id=target_id
        ),
        headers=INTAKE_HEADERS,
    )


def _two_models_around_one_surviving_primary(api):
    """Three intake reports on one model, one on another, and one merge already done."""
    fx.set_clock(api, "2026-03-01T00:00:00Z")
    model_a = fx.create_product_model(
        api, model_code="KETTLE-A1", units_distributed=400, units_registered=100
    )
    model_b = fx.create_product_model(
        api, model_code="KETTLE-B2", units_distributed=400, units_registered=100
    )
    primary = fx.create_incident(api, model_a["id"], **DUPLICATE_INTAKE_REPORT)
    already_merged = fx.create_incident(api, model_a["id"], **DUPLICATE_INTAKE_REPORT)
    candidate = fx.create_incident(api, model_a["id"], **DUPLICATE_INTAKE_REPORT)
    other_model_report = fx.create_incident(
        api, model_b["id"], **DUPLICATE_INTAKE_REPORT
    )
    merged = validate_success(
        _merge_as_duplicate_of(api, already_merged["id"], primary["id"])
    )
    return {
        "model_a_id": model_a["id"],
        "model_b_id": model_b["id"],
        "primary": primary,
        "already_merged": merged,
        "candidate": candidate,
        "other_model_report": other_model_report,
    }


class TestDuplicateDispositionPointerRules:
    """A merge pointer must be one hop deep, on the same model, and not itself."""

    def test_pointing_an_incident_at_itself_is_refused(self, api):
        """An incident may not be folded into itself.

        The contract states: "First, an incident may not be marked a duplicate of
        itself: a `duplicate_of_incident_id` equal to the incident's own `id` is
        refused with `ERR_SELF_DUPLICATE_REFERENCE` (HTTP 422)."

        Design: Corner/validations/duplicate_disposition_pointers_reject_self_chain_and_cross_model_targets
        """
        env = _two_models_around_one_surviving_primary(api)
        candidate = env["candidate"]

        validate_error(
            _merge_as_duplicate_of(api, candidate["id"], candidate["id"]),
            "ERR_SELF_DUPLICATE_REFERENCE",
            422,
        )

        after = fx.get_incident(api, candidate["id"])
        assert_field_values(after, status="INTAKE")
        assert_fields_null(after, "duplicate_of_incident_id")
        assert_unchanged(candidate, after, "version")

    def test_pointing_at_a_row_that_is_already_a_duplicate_is_refused(self, api):
        """A pointer at a merged row would make the chain two hops deep.

        The contract states: "Second, duplicate pointers must be exactly one hop
        deep — the target's own `duplicate_of_incident_id` must be null, the
        target's `status` must not be `MERGED_DUPLICATE`, and the target must belong
        to the same `product_model_id` — and any breach is refused with
        `ERR_DUPLICATE_CHAIN_FORBIDDEN` (HTTP 422)."

        Design: Corner/validations/duplicate_disposition_pointers_reject_self_chain_and_cross_model_targets
        """
        env = _two_models_around_one_surviving_primary(api)

        assert_field_values(
            env["already_merged"],
            status="MERGED_DUPLICATE",
            duplicate_of_incident_id=env["primary"]["id"],
        )

        validate_error(
            _merge_as_duplicate_of(
                api, env["candidate"]["id"], env["already_merged"]["id"]
            ),
            "ERR_DUPLICATE_CHAIN_FORBIDDEN",
            422,
        )

        after = fx.get_incident(api, env["candidate"]["id"])
        assert_field_values(after, status="INTAKE")
        assert_fields_null(after, "duplicate_of_incident_id")

    def test_pointing_at_a_report_under_another_product_model_is_refused(self, api):
        """A surviving primary must sit under the same product model.

        The contract states: "duplicate pointers must be exactly one hop deep — the
        target's own `duplicate_of_incident_id` must be null, the target's `status`
        must not be `MERGED_DUPLICATE`, and the target must belong to the same
        `product_model_id` — and any breach is refused with
        `ERR_DUPLICATE_CHAIN_FORBIDDEN` (HTTP 422)."

        Design: Corner/validations/duplicate_disposition_pointers_reject_self_chain_and_cross_model_targets
        """
        env = _two_models_around_one_surviving_primary(api)

        assert env["other_model_report"]["product_model_id"] != env["model_a_id"], (
            "the cross-model target must belong to the other product model"
        )

        validate_error(
            _merge_as_duplicate_of(
                api, env["candidate"]["id"], env["other_model_report"]["id"]
            ),
            "ERR_DUPLICATE_CHAIN_FORBIDDEN",
            422,
        )

        after = fx.get_incident(api, env["candidate"]["id"])
        assert_field_values(after, status="INTAKE")
        assert_fields_null(after, "duplicate_of_incident_id")
        assert_field_values(
            fx.get_incident(api, env["other_model_report"]["id"]), status="INTAKE"
        )

    def test_pointing_at_the_surviving_primary_folds_the_report_in(self, api):
        """A one-hop pointer on the same model is accepted and never rewrites the primary.

        The contract states: "A disposition of `MERGED_DUPLICATE` folds this report
        into a surviving primary and requires a `duplicate_of_incident_id` naming
        that primary." Both dispositions "are legal from `INTAKE` and from
        `CLASSIFIED`, and in the `CLASSIFIED` case only while `hazard_pattern_id` is
        null".

        Design: Corner/validations/duplicate_disposition_pointers_reject_self_chain_and_cross_model_targets
        """
        env = _two_models_around_one_surviving_primary(api)

        merged = validate_success(
            _merge_as_duplicate_of(
                api, env["candidate"]["id"], env["primary"]["id"]
            )
        )

        assert_field_values(
            merged,
            status="MERGED_DUPLICATE",
            duplicate_of_incident_id=env["primary"]["id"],
        )

        primary_after = fx.get_incident(api, env["primary"]["id"])
        assert_field_values(primary_after, status="INTAKE")
        assert_fields_null(primary_after, "duplicate_of_incident_id")
        assert_unchanged(env["primary"], primary_after, "status", "version")


class TestRecallLifecycleReferentialGates:
    """Three referential gates, each reachable only at its own stage of the plan."""

    def test_submitting_a_plan_without_a_direct_notice_component_is_refused(self, api):
        """The plan is incomplete until a direct notice exists, and then it files.

        The contract states: "It is refused unless the recall already has at least
        one consumer notice on the `DIRECT_NOTICE` channel, in either `SCHEDULED` or
        `RELEASED` status — a plan without a direct-notice component is incomplete,
        and the attempt draws `ERR_DIRECT_NOTICE_REQUIRED` (HTTP 422)."

        Design: Corner/validations/recall_lifecycle_referential_gates_fire_at_their_own_stage
        """
        env = fx.draft_recall_env(api, schedule_notice=False)

        assert_field_values(env["recall"], plan_status="DRAFT")
        assert_fields_null(env["recall"], "submitted_by_user_id")

        validate_error(
            api.submit_plan(env["recall_id"], headers=OFFICER_HEADERS),
            "ERR_DIRECT_NOTICE_REQUIRED",
            422,
        )
        blocked = fx.get_recall(api, env["recall_id"])
        assert_field_values(blocked, plan_status="DRAFT")
        assert_unchanged(env["recall"], blocked, "plan_status", "version")

        notice = fx.create_notice(api, env["recall_id"])
        assert_field_values(notice, channel="DIRECT_NOTICE", status="SCHEDULED")

        submitted = validate_success(
            api.submit_plan(env["recall_id"], headers=OFFICER_HEADERS)
        )
        assert_field_values(
            submitted, plan_status="SUBMITTED", submitted_by_user_id="co-1"
        )

    def test_beginning_monitoring_before_any_notice_is_released_is_refused(self, api):
        """A scheduled notice satisfies the submit gate but not the monitoring gate.

        The contract states: "It requires that the public has actually been told: at
        least one consumer notice on this recall must already be in `RELEASED`
        status, otherwise the request is refused with
        `ERR_CONSUMER_NOTICE_NOT_RELEASED` (HTTP 409)."

        Design: Corner/validations/recall_lifecycle_referential_gates_fire_at_their_own_stage
        """
        env = fx.approved_recall_env(api, notice=NOTICE_DUE_AT_APPROVAL)

        assert_field_values(env["recall"], plan_status="APPROVED")
        assert_field_values(env["notice"], channel="DIRECT_NOTICE", status="SCHEDULED")

        validate_error(
            api.begin_monitoring(env["recall_id"], headers=DIRECTOR_HEADERS),
            "ERR_CONSUMER_NOTICE_NOT_RELEASED",
            409,
        )
        assert_field_values(
            fx.get_recall(api, env["recall_id"]), plan_status="APPROVED"
        )

        released = fx.release_notice(api, env["notice_id"])
        assert_field_values(released, status="RELEASED")

        monitoring = validate_success(
            api.begin_monitoring(env["recall_id"], headers=DIRECTOR_HEADERS)
        )
        assert_field_values(monitoring, plan_status="MONITORING")

    def test_claiming_a_remedy_the_plan_never_offered_is_refused(self, api):
        """A consumer may not elect a remedy outside the plan's own menu.

        The contract states: "The elected `remedy_type` must be a member of the
        recall's own `remedy_options` array — a consumer cannot elect a remedy the
        firm never offered — and a non-member is refused with
        `ERR_REMEDY_OPTION_NOT_OFFERED` (HTTP 422)."

        Design: Corner/validations/recall_lifecycle_referential_gates_fire_at_their_own_stage
        """
        env = fx.monitoring_recall_env(api)

        assert_field_values(
            env["recall"],
            plan_status="MONITORING",
            units_corrected=0,
            units_outstanding=100,
        )
        assert sorted(env["recall"]["remedy_options"]) == ["REFUND", "REPAIR"], (
            f"the plan's menu is not the one authored: {env['recall']['remedy_options']}"
        )
        assert "RETROFIT_KIT" not in env["recall"]["remedy_options"], (
            "the remedy under test must be off the menu"
        )

        validate_error(
            api.create_remedy_claim(
                f.remedy_claim_payload(
                    env["recall_id"],
                    consumer_ref="C-771",
                    remedy_type="RETROFIT_KIT",
                    quantity=2,
                    unit_price_cents=8999,
                    shipping_cents_per_unit=700,
                ),
                headers=OFFICER_HEADERS,
            ),
            "ERR_REMEDY_OPTION_NOT_OFFERED",
            422,
        )

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(recall, units_corrected=0, units_outstanding=100)
        assert_unit_ledger_conserved(recall)

        rows, meta = validate_paginated(
            api.list_remedy_claims(
                {"recall_id": env["recall_id"]}, headers=OFFICER_HEADERS
            )
        )
        assert rows == [], f"the refused claim was persisted anyway: {rows}"
        assert_pagination_meta(meta, total_count=0, has_more=False)
