"""Corner section: consistency_model.

Every projection in this API is immediate: derived read models are recomputed per
request, so a write's own response and the very next read must already agree.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    assert_decimal_equals,
    assert_posture,
    assert_slot_conservation,
    num,
    set_clock,
    setup_base_ios,
    validate_paginated,
    validate_success,
)


def _setup_pre_review_passed_build(api):
    """One PRE_REVIEW_PASSED build with an OPEN five-slot window covering the clock."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_base_ios(
        client=api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"}
    )


def test_queue_response_already_carries_every_derived_priority_field(api):
    """"Step six sets `effective_review_deadline_at` to `queued_at` plus those SLA hours."

    Design: Corner/consistency_model/the_queue_response_body_already_carries_every_field_the_queue_call_derived
    """
    ctx = _setup_pre_review_passed_build(api)

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert queued["queued_at"] == DEFAULT_CLOCK
    assert queued["provisional_deadline_at"] == "2026-08-03T00:00:00Z"
    assert queued["priority_band"] == "NORMAL"
    assert queued["effective_review_deadline_at"] == "2026-08-03T00:00:00Z"
    assert queued["review_window_id"] == ctx.window_id
    assert 40.00 <= num(queued["priority_score"]) < 70.00, (
        "the score in the write response must itself justify the NORMAL band"
    )

    reread = validate_success(
        api.get_submission(ctx.submission_id, ctx.release_manager), 200
    )
    for field in (
        "queued_at",
        "provisional_deadline_at",
        "priority_score",
        "priority_band",
        "effective_review_deadline_at",
        "review_window_id",
    ):
        assert reread[field] == queued[field], f"{field} settled after the write"

    rows, _meta = validate_paginated(
        api.list_review_capacity_windows(ctx.reviewer, params={"platform": "IOS"})
    )
    window = next(row for row in rows if row["id"] == ctx.window_id)
    assert window["slots_reserved"] == 1
    assert window["slots_available"] == 4
    assert_slot_conservation(window)


def test_a_waiver_shows_up_in_the_derived_summary_on_the_very_next_call(api):
    """"Derived state — a compliance posture, a weighted compliance index, two different
    standing scores, two different privacy-disclosure accuracy scores — is recomputed by the
    server from stored rows rather than supplied by clients, so that no caller can talk its way
    past a gate by asserting a number."

    Design: Corner/consistency_model/a_waiver_is_visible_in_the_derived_read_model_on_the_very_next_call
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        mapping_advance="FAIL",
        with_submission=False,
        with_window=False,
    )

    before = validate_success(
        api.get_compliance_summary(ctx.app_record_id, ctx.auditor), 200
    )
    assert_posture(before, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR"])
    assert_decimal_equals(before["feature_compliance_index"], 0.00, 2, "index")
    assert before["mapping_total"] == 1
    assert before["mapping_failed"] == 1

    waived = validate_success(
        api.waive_mapping(
            ctx.mappings["privacy"],
            {"waiver_reason": "Compensating control accepted by policy."},
            ctx.policy_admin,
        ),
        200,
    )
    assert waived["self_review_status"] == "WAIVED_BY_PLATFORM"
    assert waived["waiver_reason"] == "Compensating control accepted by policy."

    after = validate_success(
        api.get_compliance_summary(ctx.app_record_id, ctx.auditor), 200
    )
    assert_posture(after, "OPEN", [])
    assert_decimal_equals(after["feature_compliance_index"], 100.00, 2, "index")
    assert after["mapping_failed"] == 0
    assert after["mapping_total"] == 1
    assert after["open_impact_count"] == 0
    assert after["overdue_impact_count"] == 0
    assert after["critical_finding_open_count"] == 0
    assert after["active_distribution_cert_present"] is True

    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 100.00, 2, "index")
    assert app["compliance_posture"] == "OPEN"
