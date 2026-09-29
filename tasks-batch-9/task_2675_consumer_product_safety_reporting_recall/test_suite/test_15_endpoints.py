"""The endpoint surface: action verbs, computed reads and filtered collections."""

from datetime import datetime

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_field_values,
    assert_fields_null,
    assert_ids_equal,
    assert_integer_cents,
    assert_millisecond_timestamp,
    assert_pagination_meta,
    assert_reserve_conserved,
    assert_unchanged,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    COUNSEL_HEADERS,
    DIRECTOR_HEADERS,
    OFFICER_HEADERS,
    make_retailer_rep_headers,
)

# The canonical docket puts the stop-sale in force at this instant, so the 72h
# acknowledgement deadline lands three days later.
STOP_SALE_CLOCK = "2026-03-13T00:00:00Z"
ACK_WINDOW_CLOCK = "2026-03-14T00:00:00Z"
ACK_DEADLINE = "2026-03-16T00:00:00Z"
PAST_ACK_DEADLINE_CLOCK = "2026-03-17T00:00:00Z"

# Two inspection windows at the same store, three days apart, so neither falls
# inside the other's 24h travel buffer.
FIRST_WINDOW = {
    "window_start": "2026-03-17T09:00:00Z",
    "window_end": "2026-03-17T17:00:00Z",
}
SECOND_WINDOW = {
    "window_start": "2026-03-20T09:00:00Z",
    "window_end": "2026-03-20T17:00:00Z",
}

# A second storefront chain enrolled alongside MegaMart, so a sweep has two rows
# to discriminate between.
SECOND_RETAILER = {
    "name": "CornerHome Hardware",
    "channel_type": "SPECIALTY",
    "store_count": 4,
}


def _instant(value):
    """One ISO 8601 UTC instant, whatever fractional precision it carries."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _assert_same_instant(actual, expected):
    """A stored instant denotes exactly the expected moment."""
    assert _instant(actual) == _instant(expected), (
        f"expected the instant {expected}, got {actual}"
    )


def _two_visits_one_completed(api):
    """A monitoring recall carrying two shelf audits, the earlier one passed."""
    env = fx.monitoring_recall_env(api)
    fx.acknowledge_notification(api, env["notification_id"], units_on_shelf_reported=0)
    first = fx.create_audit_visit(api, env["notification_id"], **FIRST_WINDOW)
    second = fx.create_audit_visit(api, env["notification_id"], **SECOND_WINDOW)
    env["first_visit"] = first
    env["second_visit"] = second
    return env


class TestAuditVisitRoundTrip:
    """One shelf audit written, mutated, read back and listed four ways."""

    def test_the_scheduled_visit_reads_back_as_completed_once_the_verdict_lands(
        self, api
    ):
        """A visit starts SCHEDULED and PENDING, then reads back COMPLETED.

        The contract states: "A new visit is created with `status` `SCHEDULED`,
        `verdict` `PENDING`, and `shelf_units_found` and `completed_at` both null;
        `status` runs `SCHEDULED -> COMPLETED` and `verdict` is one of `PENDING`,
        `PASS` and `FAIL`." And of the completion itself: "On success the visit
        advances `SCHEDULED -> COMPLETED`, its `verdict` moves from `PENDING` to
        the recorded value, and `completed_at` is stamped with the logical clock."

        Design: Corner/endpoints/audit_visit_create_read_and_filtered_list_round_trip
        """
        env = _two_visits_one_completed(api)
        first = env["first_visit"]

        assert_field_values(first, status="SCHEDULED", verdict="PENDING")
        assert_fields_null(first, "shelf_units_found", "completed_at")
        _assert_same_instant(first["window_start"], FIRST_WINDOW["window_start"])
        _assert_same_instant(first["window_end"], FIRST_WINDOW["window_end"])

        completed = fx.complete_audit_visit(
            api, first["id"], verdict="PASS", shelf_units_found=0
        )
        assert_field_values(
            completed, status="COMPLETED", verdict="PASS", shelf_units_found=0
        )
        assert_millisecond_timestamp(completed["completed_at"])
        _assert_same_instant(completed["completed_at"], ACK_WINDOW_CLOCK)

        read_back = validate_success(
            api.get_audit_visit(first["id"], headers=AUDITOR_HEADERS)
        )
        assert_field_values(
            read_back,
            id=first["id"],
            retailer_notification_id=env["notification_id"],
            status="COMPLETED",
            verdict="PASS",
            shelf_units_found=0,
        )

    def test_the_filtered_collection_reflects_the_mutation_on_every_filter(self, api):
        """Filtering by parent, by status, by verdict and by page all agree.

        The contract states: "The audit-visit collection filters on
        `retailer_notification_id`, `status` and `verdict`." And of ordering and
        page metadata: "Collection results are always ordered by `created_at`
        ascending — never by `id` — so that pagination is stable and so that a
        caller walking pages sees rows in the order the office recorded them."

        Design: Corner/endpoints/audit_visit_create_read_and_filtered_list_round_trip
        """
        env = _two_visits_one_completed(api)
        first_id = env["first_visit"]["id"]
        second_id = env["second_visit"]["id"]
        fx.complete_audit_visit(api, first_id, verdict="PASS", shelf_units_found=0)

        rows, meta = validate_paginated(
            api.list_audit_visits(
                {"retailer_notification_id": env["notification_id"]},
                headers=DIRECTOR_HEADERS,
            )
        )
        assert_ids_equal(rows, [first_id, second_id])
        assert_created_at_ascending(rows)
        assert_pagination_meta(meta, limit=10, offset=0, total_count=2, has_more=False)

        scheduled, scheduled_meta = validate_paginated(
            api.list_audit_visits(
                {
                    "retailer_notification_id": env["notification_id"],
                    "status": "SCHEDULED",
                },
                headers=DIRECTOR_HEADERS,
            )
        )
        assert_ids_equal(scheduled, [second_id])
        assert_pagination_meta(scheduled_meta, total_count=1, has_more=False)

        passing, passing_meta = validate_paginated(
            api.list_audit_visits(
                {
                    "retailer_notification_id": env["notification_id"],
                    "verdict": "PASS",
                },
                headers=DIRECTOR_HEADERS,
            )
        )
        assert_ids_equal(passing, [first_id])
        assert_pagination_meta(passing_meta, total_count=1, has_more=False)

        windowed, windowed_meta = validate_paginated(
            api.list_audit_visits(
                {
                    "retailer_notification_id": env["notification_id"],
                    "limit": 1,
                    "offset": 1,
                },
                headers=DIRECTOR_HEADERS,
            )
        )
        assert_ids_equal(windowed, [second_id])
        assert_pagination_meta(
            windowed_meta, limit=1, offset=1, total_count=2, has_more=False
        )


def _issued_notification_inside_the_window(api):
    """An approved recall whose only notification is ISSUED, clock inside 72h."""
    env = fx.approved_recall_env(api)
    fx.set_clock(api, ACK_WINDOW_CLOCK)
    return env


class TestAcknowledgementIsPaperworkNotClearance:
    """Acknowledging a stop-sale stamps the notice and moves nothing else."""

    def test_acknowledgement_records_the_shelf_count_and_leaves_the_stop_sale_standing(
        self, api
    ):
        """The retailer's own counters and the recall's axis do not move.

        The contract states: "It stamps `acknowledged_at` with the logical clock
        and records `units_on_shelf_reported`." Only verification unwinds the
        stop-sale: "On the retailer, `open_stop_sale_count` is decremented by 1 and
        `verified_removal_count` is incremented by 1, and `compliance_posture` is
        set to `CLEAR` when `open_stop_sale_count` reaches 0." And of the
        delinquency counter: "Acknowledgement does *not* reduce `delinquent_count`
        — that counter is monotonic, recording how many times this retailer has
        ever been swept into delinquency, and it is never decremented."

        Design: Corner/endpoints/acknowledge_action_stamps_the_notification_without_clearing_the_stop_sale
        """
        env = _issued_notification_inside_the_window(api)
        issued = env["notification"]
        assert_field_values(issued, status="ISSUED", stop_sale_required=True)
        _assert_same_instant(issued["issued_at"], STOP_SALE_CLOCK)
        _assert_same_instant(issued["ack_due_at"], ACK_DEADLINE)

        acknowledged = fx.acknowledge_as_retailer(
            api,
            env["notification_id"],
            env["retailer_id"],
            units_on_shelf_reported=4,
        )
        assert_field_values(
            acknowledged, status="ACKNOWLEDGED", units_on_shelf_reported=4
        )
        assert_millisecond_timestamp(acknowledged["acknowledged_at"])
        _assert_same_instant(acknowledged["acknowledged_at"], ACK_WINDOW_CLOCK)
        assert_unchanged(issued, acknowledged, "issued_at", "ack_due_at")
        assert_fields_null(acknowledged, "verified_at")

        retailer = fx.get_retailer(api, env["retailer_id"])
        assert_field_values(
            retailer,
            open_stop_sale_count=1,
            verified_removal_count=0,
            delinquent_count=0,
            compliance_posture="STOP_SALE_ACTIVE",
        )

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall, plan_status="APPROVED", notification_status="IN_PROGRESS"
        )

    def test_replaying_the_acknowledgement_is_refused_and_keeps_the_first_count(
        self, api
    ):
        """A second acknowledgement cannot overwrite the reported shelf count.

        The contract states: "Acknowledgement is legal from `ISSUED` (on time) and
        from `DELINQUENT` (a late acknowledgement); from any other status it draws
        `ERR_NOTIFICATION_STATE_INVALID`." And of every action in the system:
        "Every action operation in this system is a state transition and none of
        them are idempotent: re-firing the same trigger on a row that has already
        advanced returns that entity's state error at step 9 rather than succeeding
        silently."

        Design: Corner/endpoints/acknowledge_action_stamps_the_notification_without_clearing_the_stop_sale
        """
        env = _issued_notification_inside_the_window(api)
        acknowledged = fx.acknowledge_as_retailer(
            api,
            env["notification_id"],
            env["retailer_id"],
            units_on_shelf_reported=4,
        )

        response = api.acknowledge_notification(
            env["notification_id"],
            f.acknowledge_payload(units_on_shelf_reported=0),
            headers=make_retailer_rep_headers(env["retailer_id"]),
        )
        validate_error(response, "ERR_NOTIFICATION_STATE_INVALID", 409)

        replayed = fx.get_notification(api, env["notification_id"])
        assert_field_values(
            replayed, status="ACKNOWLEDGED", units_on_shelf_reported=4
        )
        assert_unchanged(
            acknowledged, replayed, "acknowledged_at", "version", "updated_at"
        )


def _two_enrolled_retailers_under_stop_sale(api):
    """An approved recall whose two retailers each hold one ISSUED notification."""
    env = fx.draft_recall_env(api)
    second_retailer = fx.create_retailer(api, **SECOND_RETAILER)
    second_notification = fx.create_notification(
        api, env["recall_id"], second_retailer["id"]
    )
    fx.submit_plan(api, env["recall_id"])
    env["recall"] = fx.approve_plan(api, env["recall_id"])
    env["second_retailer"] = second_retailer
    env["second_retailer_id"] = second_retailer["id"]
    env["second_notification_id"] = second_notification["id"]
    env["notification"] = fx.get_notification(api, env["notification_id"])
    return env


class TestComplianceSweepDiscriminatesPerRow:
    """A batch scan that flips only the rows the clock has strictly passed."""

    def test_the_sweep_flags_the_overdue_notification_and_spares_the_acknowledged_one(
        self, api
    ):
        """One of two notifications flips; the acknowledged retailer is untouched.

        The contract states: "Every notification on the recall that is still
        `ISSUED` and whose `ack_due_at` the logical clock has **strictly** passed is
        flipped `ISSUED -> DELINQUENT`, processed in `created_at` ascending order; a
        notification whose `ack_due_at` exactly equals the current clock reading is
        not yet overdue and is left alone." And of the cascade: "For each
        notification flipped, the owning retailer's `delinquent_count` is
        incremented by 1 and its `compliance_posture` is set to `DELINQUENT`. When
        at least one notification was flipped, the recall's `notification_status`
        moves `IN_PROGRESS -> DEFICIENT`."

        Design: Corner/endpoints/compliance_sweep_flags_only_the_overdue_notification_and_is_a_no_op_when_rerun
        """
        env = _two_enrolled_retailers_under_stop_sale(api)
        assert_field_values(env["recall"], notification_status="IN_PROGRESS")
        _assert_same_instant(env["recall"]["stop_sale_effective_at"], STOP_SALE_CLOCK)
        _assert_same_instant(env["notification"]["ack_due_at"], ACK_DEADLINE)

        fx.set_clock(api, ACK_WINDOW_CLOCK)
        fx.acknowledge_notification(
            api, env["notification_id"], units_on_shelf_reported=0
        )
        fx.set_clock(api, PAST_ACK_DEADLINE_CLOCK)

        swept = fx.compliance_sweep(api, env["recall_id"])
        assert_field_values(swept, notification_status="DEFICIENT")

        assert_field_values(
            fx.get_notification(api, env["second_notification_id"]),
            status="DELINQUENT",
        )
        assert_field_values(
            fx.get_notification(api, env["notification_id"]), status="ACKNOWLEDGED"
        )

        assert_field_values(
            fx.get_retailer(api, env["second_retailer_id"]),
            delinquent_count=1,
            compliance_posture="DELINQUENT",
            open_stop_sale_count=1,
            verified_removal_count=0,
        )
        assert_field_values(
            fx.get_retailer(api, env["retailer_id"]),
            delinquent_count=0,
            compliance_posture="STOP_SALE_ACTIVE",
            open_stop_sale_count=1,
        )

    def test_rerunning_the_sweep_answers_with_the_recall_and_changes_nothing(
        self, api
    ):
        """A second sweep finds nothing newly overdue and moves no counter.

        The contract states: "A sweep that finds nothing newly overdue changes
        nothing and is still answered successfully — it is a scan, not a state
        transition on the recall itself, and it always answers with the recall
        record."

        Design: Corner/endpoints/compliance_sweep_flags_only_the_overdue_notification_and_is_a_no_op_when_rerun
        """
        env = _two_enrolled_retailers_under_stop_sale(api)
        fx.set_clock(api, ACK_WINDOW_CLOCK)
        fx.acknowledge_notification(
            api, env["notification_id"], units_on_shelf_reported=0
        )
        fx.set_clock(api, PAST_ACK_DEADLINE_CLOCK)

        first_sweep = fx.compliance_sweep(api, env["recall_id"])
        delinquent_before = fx.get_notification(api, env["second_notification_id"])

        second_sweep = validate_success(
            api.compliance_sweep(env["recall_id"], headers=OFFICER_HEADERS), 200
        )
        assert_field_values(
            second_sweep, id=env["recall_id"], notification_status="DEFICIENT"
        )
        assert_unchanged(
            first_sweep, second_sweep, "version", "updated_at", "notification_status"
        )

        assert_unchanged(
            delinquent_before,
            fx.get_notification(api, env["second_notification_id"]),
            "status",
            "version",
        )
        assert_field_values(
            fx.get_retailer(api, env["second_retailer_id"]),
            delinquent_count=1,
            compliance_posture="DELINQUENT",
        )
        assert_field_values(
            fx.get_retailer(api, env["retailer_id"]), delinquent_count=0
        )

    def test_a_deadline_falling_exactly_on_the_clock_is_not_yet_overdue(self, api):
        """At exactly ack_due_at neither notification is swept into delinquency.

        The contract states: "a notification whose `ack_due_at` exactly equals the
        current clock reading is not yet overdue and is left alone." And of the
        scan's own effect: "A sweep that finds nothing newly overdue changes
        nothing and is still answered successfully."

        Design: Corner/endpoints/compliance_sweep_flags_only_the_overdue_notification_and_is_a_no_op_when_rerun
        """
        env = _two_enrolled_retailers_under_stop_sale(api)
        before = fx.get_recall(api, env["recall_id"])
        fx.set_clock(api, ACK_DEADLINE)

        swept = validate_success(
            api.compliance_sweep(env["recall_id"], headers=DIRECTOR_HEADERS), 200
        )
        assert_field_values(swept, notification_status="IN_PROGRESS")
        assert_unchanged(before, swept, "version", "updated_at")

        for notification_id in (
            env["notification_id"],
            env["second_notification_id"],
        ):
            assert_field_values(
                fx.get_notification(api, notification_id), status="ISSUED"
            )
        for retailer_id in (env["retailer_id"], env["second_retailer_id"]):
            assert_field_values(
                fx.get_retailer(api, retailer_id),
                delinquent_count=0,
                compliance_posture="STOP_SALE_ACTIVE",
            )


def _draft_recall_and_an_unenrolled_retailer(api):
    """A drafted recall and a registered retailer with no link between them."""
    env = fx.draft_recall_env(api, enroll_retailer=False)
    retailer = fx.create_retailer(api)
    env["retailer"] = retailer
    env["retailer_id"] = retailer["id"]
    return env


class TestRetailerNotificationLinksTwoParents:
    """The one row with two parents, reachable through either of them."""

    def test_both_body_foreign_keys_must_resolve_before_the_link_exists(self, api):
        """A bogus retailer reports the retailer's code, a bogus recall the recall's.

        The contract states: "The same catalogue serves foreign keys supplied in a
        request body, but body foreign keys are only resolved *after* the body has
        passed its shape check, so a malformed payload never leaks the existence of
        a referenced row." The ordering names the family: "**Body foreign-key
        existence** — every foreign-key identifier in the body resolves to a live
        row, else that entity's not-found error."

        Design: Corner/endpoints/retailer_notification_links_two_parents_and_is_reachable_from_both
        """
        env = _draft_recall_and_an_unenrolled_retailer(api)

        validate_error(
            api.create_retailer_notification(
                f.retailer_notification_payload(env["recall_id"], NON_EXISTENT_UUID),
                headers=OFFICER_HEADERS,
            ),
            "ERR_RETAILER_NOT_FOUND",
            404,
        )
        validate_error(
            api.create_retailer_notification(
                f.retailer_notification_payload(NON_EXISTENT_UUID, env["retailer_id"]),
                headers=OFFICER_HEADERS,
            ),
            "ERR_RECALL_NOT_FOUND",
            404,
        )

        rows, meta = validate_paginated(
            fx.list_notifications(api, recall_id=env["recall_id"])
        )
        assert rows == [], f"a refused enrollment left a row behind: {rows}"
        assert_pagination_meta(meta, total_count=0, has_more=False)

    def test_the_new_link_is_reachable_from_the_recall_and_from_the_retailer(
        self, api
    ):
        """The same notification comes back under either parent's filter.

        The contract states: "The retailer-notification collection filters on
        `recall_id`, `retailer_id`, `status` and `stop_sale_required`, and is the
        only channel through which the stop-sale issuance cascade and the
        delinquency sweep become visible." And of the row's own defaults: "a new
        notification is always created in `PENDING` with `stop_sale_required` false
        and with `issued_at`, `ack_due_at`, `acknowledged_at`, `verified_at` and
        `units_on_shelf_reported` all null."

        Design: Corner/endpoints/retailer_notification_links_two_parents_and_is_reachable_from_both
        """
        env = _draft_recall_and_an_unenrolled_retailer(api)

        created = validate_success(
            api.create_retailer_notification(
                f.retailer_notification_payload(env["recall_id"], env["retailer_id"]),
                headers=OFFICER_HEADERS,
            ),
            201,
        )
        assert_field_values(
            created,
            recall_id=env["recall_id"],
            retailer_id=env["retailer_id"],
            status="PENDING",
            stop_sale_required=False,
        )
        assert_fields_null(
            created,
            "issued_at",
            "ack_due_at",
            "acknowledged_at",
            "verified_at",
            "units_on_shelf_reported",
        )

        by_recall, recall_meta = validate_paginated(
            fx.list_notifications(api, recall_id=env["recall_id"])
        )
        assert_ids_equal(by_recall, [created["id"]])
        assert_pagination_meta(recall_meta, total_count=1, has_more=False)

        by_retailer, retailer_meta = validate_paginated(
            fx.list_notifications(api, retailer_id=env["retailer_id"])
        )
        assert_ids_equal(by_retailer, [created["id"]])
        assert_pagination_meta(retailer_meta, total_count=1, has_more=False)

        assert_field_values(
            fx.get_retailer(api, env["retailer_id"]),
            open_stop_sale_count=0,
            verified_removal_count=0,
            delinquent_count=0,
            compliance_posture="CLEAR",
        )


class TestPenaltyCaseComputedRead:
    """One GET carrying the frozen assessment and the non-binding preview."""

    def test_the_case_read_carries_the_frozen_assessment_and_its_conserved_reserve(
        self, api
    ):
        """Four violations, a hospitalisation and two late days assess 5,500,000.

        The contract states: "The computation starts from a base of 1,000,000 cents
        per alleged violation, that is 1,000,000 multiplied by `violation_count`."
        And: "when it is `HOSPITALIZATION` the multiplier is 1.25". And: "The base
        is then scaled a second time by a lateness multiplier of 1.00 plus the
        smaller of 0.50 and the product of 0.05 and the report's stored
        `days_late`, so each full day of delay adds five percent up to a hard
        ceiling of fifty percent." The reserve then opens conserved: "A new case is
        created in `status` `ASSESSMENT_OPEN`, with `reserved_cents` at 0 and
        `available_cents` equal to `assessed_penalty_cents`, so the conserved
        reserve identity holds from the first instant."

        Design: Corner/endpoints/penalty_case_read_exposes_the_frozen_assessment_and_its_non_binding_preview
        """
        env = fx.penalty_case_on_report_env(api, violation_count=4)
        assert_field_values(
            env["report"], days_late=2, late_surcharge_cents=500000, status="SUBMITTED"
        )

        case = validate_success(
            api.get_penalty_case(env["case_id"], headers=COUNSEL_HEADERS)
        )
        assert_field_values(
            case,
            section_report_id=env["report_id"],
            violation_count=4,
            status="ASSESSMENT_OPEN",
            assessed_penalty_cents=5500000,
            reserved_cents=0,
            available_cents=5500000,
            current_offer_round=0,
            cooperation_bonus_applied=False,
        )
        assert_fields_null(case, "current_offer_cents", "current_offer_by")
        assert_integer_cents(
            case, "assessed_penalty_cents", "reserved_cents", "available_cents"
        )
        assert_reserve_conserved(case)

        rows, meta = validate_paginated(
            api.list_penalty_cases(
                {"section_report_id": env["report_id"]}, headers=COUNSEL_HEADERS
            )
        )
        assert_ids_equal(rows, [env["case_id"]])
        assert_pagination_meta(meta, total_count=1, has_more=False)

    def test_the_preview_is_keyed_on_the_assessment_while_the_binding_fields_stay_empty(
        self, api
    ):
        """With no offer standing the preview discounts the assessment itself.

        The contract states: "In the **preview** variant the base is
        `current_offer_cents` when a standing offer exists and
        `assessed_penalty_cents` when none does." The tier follows: "when the base
        is at least 5,000,000 and at most 12,000,000 cents the tier is `TIER_2` at
        fifteen percent". And nothing binding is written: "In the **preview**
        variant only `consent_agreement_preview_cents` is written and
        `cooperation_credit_tier`, `cooperation_credit_cents`,
        `consent_agreement_total_cents`, `compliance_program_required` and
        `reporting_obligation_months` are all left untouched at their null and zero
        values."

        Design: Corner/endpoints/penalty_case_read_exposes_the_frozen_assessment_and_its_non_binding_preview
        """
        env = fx.penalty_case_on_report_env(api, violation_count=4)

        case = validate_success(
            api.get_penalty_case(env["case_id"], headers=COUNSEL_HEADERS)
        )
        assert_field_values(
            case,
            assessed_penalty_cents=5500000,
            consent_agreement_preview_cents=4675000,
            compliance_program_required=False,
            reporting_obligation_months=0,
        )
        assert_integer_cents(case, "consent_agreement_preview_cents")
        assert_fields_null(
            case,
            "cooperation_credit_tier",
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
        )
        assert (
            case["consent_agreement_preview_cents"] < case["assessed_penalty_cents"]
        ), "the preview must discount the assessment, not restate it"
