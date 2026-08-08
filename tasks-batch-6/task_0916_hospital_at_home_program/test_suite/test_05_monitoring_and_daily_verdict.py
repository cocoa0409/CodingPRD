"""Telemetry gap accounting and the per-service-date compliance verdict."""

from test_helpers import (
    assert_compliance_record,
    assert_day_ledger,
    assert_monitoring_lapse,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_monitoring_lapse_payload
from test_helpers.test_users import FIELD_NURSE, PROGRAM_ADMIN


def test_touching_and_overlapping_gaps_merge_into_one_interval(api):
    """PRD §3.4: "They are then merged left to right: an interval whose effective
    start is strictly later than the end of the interval accumulated so far
    begins a new accumulated interval, while an interval whose effective start is
    at or before that end is absorbed into it by extending the accumulated end to
    the later of the two ends."
    PRD §3.4: "Adjacency with zero gap therefore merges — a gap ending at 10:30
    and another starting at 10:30 become a single sixty-minute outage rather than
    two thirty-minute ones."

    Design: Corner/calculations/monitoring_lapses_that_touch_or_overlap_merge_into_one_interval
    """
    parts = fx.setup_active_episode(mrn="MRN-MG", full_name="Mel Merge")
    episode_id = parts["episode"]["id"]

    fx.record_lapse(
        episode_id,
        "2026-06-01T09:00:00Z",
        "2026-06-01T09:30:00Z",
        cause="DEVICE_OFFLINE",
    )
    fx.record_lapse(
        episode_id,
        "2026-06-01T09:30:00Z",
        "2026-06-01T10:00:00Z",
        cause="CONNECTIVITY_LOSS",
    )
    fx.record_lapse(
        episode_id,
        "2026-06-01T09:45:00Z",
        "2026-06-01T10:15:00Z",
        cause="DEVICE_OFFLINE",
    )

    day = fx.compliance_day_for(episode_id, "2026-06-01")
    assert_compliance_record(day)
    assert day["monitoring_lapse_minutes"] == 75, (
        "09:00-09:30, 09:30-10:00 and 09:45-10:15 merge into 09:00-10:15, "
        f"got {day['monitoring_lapse_minutes']}"
    )
    assert day["monitoring_lapse_minutes"] != 105, (
        "the unmerged sum of the three gaps is not the rule"
    )

    _, meta = validate_paginated(
        api.list_episode_monitoring_lapses(episode_id, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 3


def test_forty_five_second_gap_truncates_down_to_zero_minutes(api):
    """PRD §3.4: "The merged durations are summed in seconds and converted to
    whole minutes by dividing by sixty and **truncating downward**, so partial
    minutes are dropped."
    PRD §2.7: "Daily telemetry-gap totals are expressed in **whole minutes
    truncated downward**: a merged gap of 119 seconds contributes 1 minute, not
    2."

    Design: Corner/calculations/monitoring_lapse_of_45_seconds_truncates_down_to_zero_minutes
    """
    parts = fx.setup_active_episode(mrn="MRN-TR", full_name="Tom Trunc")
    episode_id = parts["episode"]["id"]

    fx.record_lapse(episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:00:45Z")

    day = fx.compliance_day_for(episode_id, "2026-06-01")
    assert day["monitoring_lapse_minutes"] == 0, (
        "a 45-second gap is a partial minute and is dropped, got "
        f"{day['monitoring_lapse_minutes']}"
    )


def test_lapse_of_exactly_240_minutes_stays_compliant_while_241_carves_out(api):
    """PRD §3.4: "`monitoring_lapse_minutes` is at or below 240 minutes — four
    hours of telemetry silence in a day is tolerated, four hours and one minute
    is not. Failure names `MONITORING_LAPSE_EXCEEDED`."
    PRD §3.4: "If all four clauses pass the day is `COMPLIANT`; otherwise it is
    `CARVED_OUT` with `carve_out_reason` set to the first failing clause's
    reason."

    Design: Corner/calculations/lapse_of_exactly_240_minutes_stays_compliant_while_241_carves_out
    """
    at_bound = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE", mrn="MRN-240", full_name="Tia Two40"
    )
    over_bound = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE",
        set_the_clock=False,
        mrn="MRN-241",
        full_name="Ora Over41",
    )
    at_id = at_bound["episode"]["id"]
    over_id = over_bound["episode"]["id"]

    fx.perform_and_attest_visit(
        at_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z", staff_user_id="rn-1"
    )
    fx.perform_and_attest_visit(
        over_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z", staff_user_id="rn-2"
    )

    fx.record_lapse(
        at_id, "2026-06-01T10:00:00Z", "2026-06-01T14:00:00Z", cause="DEVICE_OFFLINE"
    )
    fx.record_lapse(
        over_id, "2026-06-01T10:00:00Z", "2026-06-01T14:01:00Z", cause="DEVICE_OFFLINE"
    )

    at_day = fx.finalize_day(fx.compliance_day_for(at_id, "2026-06-01")["id"])
    over_day = fx.finalize_day(fx.compliance_day_for(over_id, "2026-06-01")["id"])

    assert at_day["monitoring_lapse_minutes"] == 240
    assert at_day["status"] == "COMPLIANT", (
        "240 merged minutes sits on the at-or-below bound and stays compliant"
    )
    assert over_day["monitoring_lapse_minutes"] == 241
    assert over_day["status"] == "CARVED_OUT"
    assert over_day["carve_out_reason"] == "MONITORING_LAPSE_EXCEEDED"

    assert fx.read_episode(at_id)["billable_day_count"] == 1
    assert fx.read_episode(over_id)["billable_day_count"] == 0


def test_waiver_day_carves_out_on_a_single_in_person_visit(api):
    """PRD §3.4: "On a `CMS_WAIVER` episode the day requires **two** qualified
    in-person visits, **one** physician evaluation, and continuous kit
    deployment. On a `FEE_FOR_SERVICE` episode the day requires **one** qualified
    in-person visit, requires **no** physician evaluation at all, and skips the
    kit-deployment clause entirely."
    PRD §3.4: "`qualified_in_person_visit_count` is at least the track's required
    in-person count — two under the waiver, one under fee-for-service. Failure
    names `INSUFFICIENT_IN_PERSON_VISITS`."

    Design: Difficulty/dual_variant_calc/waiver_vs_ffs_daily_compliance_diverge_on_identical_visit_set
    """
    parts = fx.setup_active_episode(
        program_track="CMS_WAIVER",
        home_distance_km=12.5,
        mrn="MRN-W1",
        full_name="Wanda Waiver",
    )
    episode_id = parts["episode"]["id"]

    fx.perform_and_attest_visit(
        episode_id,
        "2026-06-01T09:00:00Z",
        "2026-06-01T09:45:00Z",
        visit_type="RN_IN_PERSON",
        staff_user_id="rn-1",
        distance_km=8.0,
    )

    day = fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-01")["id"])
    assert day["qualified_in_person_visit_count"] == 1
    assert day["status"] == "CARVED_OUT", (
        "one in-person visit is one short of the waiver requirement of two"
    )
    assert day["carve_out_reason"] == "INSUFFICIENT_IN_PERSON_VISITS"

    episode = fx.read_episode(episode_id)
    assert_day_ledger(episode, service=1, billable=0, carved_out=1, pending=0)


def test_fee_for_service_day_is_compliant_on_the_same_single_visit(api):
    """PRD §3.4: "On a `CMS_WAIVER` episode the day requires **two** qualified
    in-person visits, **one** physician evaluation, and continuous kit
    deployment. On a `FEE_FOR_SERVICE` episode the day requires **one** qualified
    in-person visit, requires **no** physician evaluation at all, and skips the
    kit-deployment clause entirely."
    PRD §3.4: "When the verdict is compliant, the record moves `PENDING →
    COMPLIANT`, `finalized_at` is stamped from the logical clock, the episode's
    `billable_day_count` is incremented and its `pending_day_count` decremented,
    the episode's `reimbursement_amount_usd` and `meal_credit_total_usd` are
    recomputed, and the record's `version` advances by 1."

    Design: Difficulty/dual_variant_calc/waiver_vs_ffs_daily_compliance_diverge_on_identical_visit_set
    """
    parts = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE",
        home_distance_km=12.5,
        mrn="MRN-F1",
        full_name="Frank Ffs",
    )
    episode_id = parts["episode"]["id"]

    fx.perform_and_attest_visit(
        episode_id,
        "2026-06-01T09:00:00Z",
        "2026-06-01T09:45:00Z",
        visit_type="RN_IN_PERSON",
        staff_user_id="rn-2",
        distance_km=8.0,
    )

    day = fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-01")["id"])
    assert day["qualified_in_person_visit_count"] == 1
    assert day["status"] == "COMPLIANT", (
        "one in-person visit satisfies the fee-for-service requirement"
    )
    assert day["carve_out_reason"] is None
    assert day["finalized_at"] is not None

    episode = fx.read_episode(episode_id)
    assert_day_ledger(episode, service=1, billable=1, carved_out=0, pending=0)


def test_monitoring_lapse_is_append_only_evidence(api):
    """PRD §2.4: "A `MonitoringLapse` is append-only: once written it is never
    edited, so it carries only `id` and `created_at`. It has **no** `updated_at`
    field and **no** `version` field, and neither should appear in its response
    payload."
    PRD §3.4: "an optional `cause`, which defaults to `UNKNOWN` when omitted"

    Design: Corner/entities/monitoring_lapse_is_an_immutable_event_without_version_field
    """
    parts = fx.setup_active_episode(mrn="MRN-IM", full_name="Ivy Immutable")
    episode_id = parts["episode"]["id"]

    payload = create_monitoring_lapse_payload(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z"
    )
    data = validate_success(api.create_monitoring_lapse(payload, FIELD_NURSE), 201)

    assert_monitoring_lapse(data)
    assert data["cause"] == "UNKNOWN", "an omitted cause defaults to UNKNOWN"

    rows, meta = validate_paginated(
        api.list_episode_monitoring_lapses(episode_id, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 1
    assert "version" not in rows[0]
    assert "updated_at" not in rows[0]
