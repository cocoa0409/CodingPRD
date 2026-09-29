"""Entity shapes, system-minted fields, defaults and collection reads.

Covers the row a create returns, the thresholds a programme falls back to, the
untouched dispatcher baseline, filtered listing counts, the entity-specific
not-found codes, request-shape rejection on ingestion, the determinant-code
decodings stored on a call record, the birth values of a review, and the
append-only score sheet.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    approx1,
    approx2,
    assert_common_fields,
    assert_envelope_meta,
    assert_instant_equals,
    assert_score_sheet_shape,
)
from test_helpers.test_users import ADMIN, REVIEWER, SUPERVISOR

# The sheet used wherever a known provisional composite is needed: 18/20, 26/30,
# 2/3 and 5/7 give 90.00, 86.67, 66.67 and 71.43, whose mean is 78.7.
SHEET_78_7 = {
    "case_entry": (18, 20),
    "key_questions": (26, 30),
    "pre_arrival": (2, 3),
    "final_coding": (5, 7),
}
PERFECT_SHEET = {
    "case_entry": (20, 20),
    "key_questions": (30, 30),
    "pre_arrival": (3, 3),
    "final_coding": (7, 7),
}


def test_create_audit_program_returns_the_whole_row_in_the_standard_envelope(api):
    """PRD §2.4: "Every resource carries an `id` that is a server-minted UUID with no
    type prefix; clients never supply one."
    PRD §3.1: "`accreditation_status` reads `SETUP` from the moment the programme is
    created and stays there until the first accreditation report is filed, after which
    it is either `ACCREDITED` or `AT_RISK`."
    PRD §3.1: "`latest_compliance_pct` is null until the first filing."
    PRD §3.1: "`submitted_report_count` starts at 0 and `sentinel_event_count` starts at 0."

    Design: Corner/entities/create_audit_program_with_all_required_fields_returns_full_row
    """
    payload = f.full_audit_program_payload(
        name="Basin EMD QA",
        accreditation_body="IAED",
        target_compliance_pct=92.0,
        watch_floor_pct=81.0,
        high_risk_target_pct=86.0,
        review_deadline_days=21,
        rebuttal_window_days=10,
        max_rebuttal_rounds=3,
        escalated_sample_floor=30,
        hours_owed_restriction_threshold=5.0,
    )
    response = api.create_audit_program(payload, ADMIN)
    data = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object", "a single resource is returned as an object"
    assert_envelope_meta(body)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert_common_fields(data, expected_version=1)

    assert data["name"] == "Basin EMD QA"
    assert data["accreditation_body"] == "IAED"
    assert data["target_compliance_pct"] == approx1(92.0)
    assert data["watch_floor_pct"] == approx1(81.0)
    assert data["high_risk_target_pct"] == approx1(86.0)
    assert data["review_deadline_days"] == 21
    assert data["rebuttal_window_days"] == 10
    assert data["max_rebuttal_rounds"] == 3
    assert data["escalated_sample_floor"] == 30
    assert data["hours_owed_restriction_threshold"] == approx1(5.0)

    assert data["accreditation_status"] == "SETUP"
    assert data["latest_compliance_pct"] is None, "no report has been filed yet"
    assert data["submitted_report_count"] == 0
    assert data["sentinel_event_count"] == 0


def test_audit_program_thresholds_fall_back_to_their_declared_defaults(api):
    """PRD §3.1: "`target_compliance_pct` is the compliance percentage the accrediting
    body demands and defaults to 90.0; `watch_floor_pct` is the floor separating a
    merely-watched dispatcher from one on probation and defaults to 80.0;
    `high_risk_target_pct` is the minimum pass rate demanded of dispatcher-assisted
    resuscitation cases and defaults to 85.0."
    PRD §3.1: "`review_deadline_days` is the number of days after a review is opened
    within which it must be finalized, defaulting to 30."
    PRD §3.1: "`rebuttal_window_days` is the number of days after a score is submitted
    within which the dispatcher may dispute it, defaulting to 14; both must be at least 1."
    PRD §3.1: "`max_rebuttal_rounds` caps how many times one case may be disputed and
    defaults to 2, with 0 through 3 the permitted range — a programme that sets it to 0
    has disabled rebuttals entirely."
    PRD §3.1: "`escalated_sample_floor` is the elevated sample size the programme insists
    on when a dispatcher under audit is in trouble, defaulting to 25 and required to be
    at least 1."
    PRD §3.1: "`hours_owed_restriction_threshold` is the number of outstanding remediation
    hours a dispatcher may carry before their dispatch privilege is curtailed, defaulting
    to 6.0 hours."

    Design: Corner/entities/audit_program_threshold_defaults_are_applied_when_omitted
    """
    created = validate_success(
        api.create_audit_program(
            {"name": "Minimal EMD QA", "accreditation_body": "STATE_OEMS"}, ADMIN
        ),
        201,
    )
    read_back = validate_success(api.get_audit_program(created["id"], ADMIN), 200)

    for row, where in ((created, "the create response"), (read_back, "the stored row")):
        assert row["target_compliance_pct"] == approx1(90.0), where
        assert row["watch_floor_pct"] == approx1(80.0), where
        assert row["high_risk_target_pct"] == approx1(85.0), where
        assert row["review_deadline_days"] == 30, where
        assert row["rebuttal_window_days"] == 14, where
        assert row["max_rebuttal_rounds"] == 2, where
        assert row["escalated_sample_floor"] == 25, where
        assert row["hours_owed_restriction_threshold"] == approx1(6.0), where


def test_get_dispatcher_returns_the_untouched_enrollment_baseline(api):
    """PRD §3.1: "A newly enrolled dispatcher starts with `certification_status` of
    `PROVISIONAL`, no `certified_protocol_version_id` and no `certified_at`,
    `dispatch_privilege` of `FULL`, `compliance_posture` of `UNRATED`, `compliance_pct`
    of null, and every counter and ledger at zero: `reviewed_case_count` 0,
    `compliance_points_total` 0.0, `remediation_hours_owed` 0.00, `sentinel_event_count` 0."

    Design: Corner/entities/get_dispatcher_returns_the_stored_row_with_ledger_defaults
    """
    program = fx.new_program(api, name="Basin EMD QA", accreditation_body="IAED")
    dispatcher = fx.new_dispatcher(
        api,
        program["id"],
        employee_code="EMD-001",
        full_name="Ada Rune",
        hire_date="2025-04-01T00:00:00Z",
    )

    data = validate_success(api.get_dispatcher(dispatcher["id"], SUPERVISOR), 200)

    assert data["id"] == dispatcher["id"]
    assert_common_fields(data, expected_version=1)
    assert data["program_id"] == program["id"]
    assert data["employee_code"] == "EMD-001"
    assert data["full_name"] == "Ada Rune"
    assert_instant_equals(data["hire_date"], "2025-04-01T00:00:00Z")

    assert data["certification_status"] == "PROVISIONAL"
    assert data["certified_protocol_version_id"] is None
    assert data["certified_at"] is None
    assert data["dispatch_privilege"] == "FULL"
    assert data["compliance_posture"] == "UNRATED"
    assert data["compliance_pct"] is None, "an unreviewed dispatcher has no percentage yet"
    assert data["reviewed_case_count"] == 0
    assert data["compliance_points_total"] == approx1(0.0)
    assert data["remediation_hours_owed"] == approx2(0.00)
    assert data["sentinel_event_count"] == 0


def test_list_dispatchers_counts_only_the_filtered_set(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the number of rows
    matching the filters before the page window is applied and `has_more` indicates
    whether rows remain beyond it."
    PRD §3.9: "Beyond single-resource reads, the list surfaces accept filters that mirror
    the fields above, all of them optional and all combinable with `limit` and `offset`:
    a programme's protocol versions may be filtered by `status` and by `protocol_family`;
    a version's rollouts by `golive_status`; dispatchers by `program_id`,
    `certified_protocol_version_id`, `compliance_posture`, `dispatch_privilege`, and
    `certification_status`"

    Design: Corner/entities/list_dispatchers_filtered_by_program_and_privilege
    """
    program_a = fx.new_program(api, name="Program A", accreditation_body="IAED")
    program_b = fx.new_program(api, name="Program B", accreditation_body="NAED_LOCAL")
    a1 = fx.new_dispatcher(api, program_a["id"], employee_code="EMD-A1", full_name="Ada Rune")
    a2 = fx.new_dispatcher(api, program_a["id"], employee_code="EMD-A2", full_name="Bo Wexler")
    b1 = fx.new_dispatcher(
        api, program_b["id"], employee_code="EMD-B1", full_name="Cai Nogueira"
    )

    response = api.list_dispatchers(
        REVIEWER,
        {
            "program_id": program_a["id"],
            "dispatch_privilege": "FULL",
            "limit": 10,
            "offset": 0,
        },
    )
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"

    ids = [row["id"] for row in rows]
    assert sorted(ids) == sorted([a1["id"], a2["id"]]), f"unexpected page: {ids}"
    assert b1["id"] not in ids, "the other programme's dispatcher must not appear"
    for row in rows:
        assert row["program_id"] == program_a["id"]
    assert meta["total_count"] == 2, "the count is scoped to the filter"
    assert meta["has_more"] is False

    unfiltered_rows, unfiltered_meta = validate_paginated(
        api.list_dispatchers(REVIEWER, {"limit": 10, "offset": 0})
    )
    assert unfiltered_meta["total_count"] == 3
    assert len(unfiltered_rows) == 3


def test_get_review_with_an_unknown_id_returns_review_not_found(api):
    """PRD §2.5: "Path identifiers are resolved strictly left to right, and the first
    identifier that does not resolve determines the error: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_PROTOCOL_VERSION_NOT_FOUND`, `ERR_ROLLOUT_NOT_FOUND`, `ERR_DISPATCHER_NOT_FOUND`,
    `ERR_SAMPLING_PERIOD_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_REBUTTAL_NOT_FOUND`,
    `ERR_HIGH_RISK_REVIEW_NOT_FOUND`, `ERR_COACHING_PLAN_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND`, each at HTTP 404."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/entities/get_review_with_unknown_id_returns_not_found
    """
    response = api.get_review(NON_EXISTENT_UUID, SUPERVISOR)
    validate_error(response, err.ERR_REVIEW_NOT_FOUND, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert_envelope_meta(body)


@pytest.mark.parametrize(
    "probe,expected_error_id",
    [
        ("dispatcher", err.ERR_DISPATCHER_NOT_FOUND),
        ("protocol_version", err.ERR_PROTOCOL_VERSION_NOT_FOUND),
        ("coaching_plan", err.ERR_COACHING_PLAN_NOT_FOUND),
        ("audit_program", err.ERR_PROGRAM_NOT_FOUND),
    ],
)
def test_unknown_id_reads_report_the_entity_specific_not_found(api, probe, expected_error_id):
    """PRD §2.5: "Path identifiers are resolved strictly left to right, and the first
    identifier that does not resolve determines the error: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_PROTOCOL_VERSION_NOT_FOUND`, `ERR_ROLLOUT_NOT_FOUND`, `ERR_DISPATCHER_NOT_FOUND`,
    `ERR_SAMPLING_PERIOD_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_REBUTTAL_NOT_FOUND`,
    `ERR_HIGH_RISK_REVIEW_NOT_FOUND`, `ERR_COACHING_PLAN_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND`, each at HTTP 404."

    Design: Corner/entities/get_review_with_unknown_id_returns_not_found
    """
    readers = {
        "dispatcher": lambda: api.get_dispatcher(NON_EXISTENT_UUID, ADMIN),
        "protocol_version": lambda: api.get_protocol_version(NON_EXISTENT_UUID, ADMIN),
        "coaching_plan": lambda: api.get_coaching_plan(NON_EXISTENT_UUID, SUPERVISOR),
        "audit_program": lambda: api.get_audit_program(NON_EXISTENT_UUID, ADMIN),
    }
    validate_error(readers[probe](), expected_error_id, 404)


@pytest.mark.parametrize(
    "omitted_field",
    ["dispatched_determinant_code", "call_reference", "call_type", "received_at"],
)
def test_call_ingestion_rejects_a_payload_missing_a_required_field(api, omitted_field):
    """PRD §2.9: "**Request shape** — the body parses, required fields are present, types
    match, enum values are declared members, and numeric fields are in range, else
    `ERR_INVALID_REQUEST`."
    PRD §3.1: "And it carries `dispatched_determinant_code`, the code the dispatcher
    actually assigned live, from which the server immediately derives the priority rank,
    response mode and resource tier described in §2.10."

    Design: Corner/entities/create_call_record_missing_required_determinant_code_is_rejected
    """
    env = fx.enrolled_dispatcher_env(api)
    payload = f.call_record_payload(**{omitted_field: f.OMIT})

    response = api.create_call_record(env["dispatcher_id"], payload, ADMIN)
    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_call_records(env["dispatcher_id"], ADMIN, {"limit": 100})
    )
    assert rows == [], "a rejected ingestion must persist nothing"
    assert meta["total_count"] == 0


def test_call_ingestion_defaults_both_outcome_flags_to_false(api):
    """PRD §3.1: "`cardiac_arrest_confirmed` records whether the patient was in fact in
    arrest and defaults to false."
    PRD §3.1: "`bystander_cpr_in_progress` records whether a bystander was already doing
    compressions when the line connected, defaults to false, and re-weights the whole
    resuscitation performance index because a dispatcher who inherits compressions in
    progress is judged more on how fast they recognised the arrest and less on how fast
    compressions began."

    Design: Corner/entities/create_call_record_missing_required_determinant_code_is_rejected
    """
    env = fx.enrolled_dispatcher_env(api)

    data = validate_success(
        api.create_call_record(
            env["dispatcher_id"],
            f.call_record_payload(
                call_reference="C-0001",
                call_type="CHEST_PAIN",
                received_at="2026-08-05T09:00:00Z",
                dispatched_determinant_code="10-C-4",
            ),
            ADMIN,
        ),
        201,
    )
    assert data["cardiac_arrest_confirmed"] is False
    assert data["bystander_cpr_in_progress"] is False


@pytest.mark.parametrize(
    "code,call_type,expected_rank,expected_mode,expected_resource",
    [
        ("9-E-1", "CARDIAC_ARREST", 6, "HOT", "ALS"),
        ("26-A-1", "TRAUMA", 2, "COLD", "BLS"),
        ("10-C-4", "CHEST_PAIN", 4, "COLD", "ALS"),
        ("6-D-2", "BREATHING_PROBLEM", 5, "HOT", "ALS"),
    ],
)
def test_call_record_decodes_its_determinant_code_into_three_fields(
    api, code, call_type, expected_rank, expected_mode, expected_resource
):
    """PRD §2.10: "The letter maps to a numeric priority rank ordering codes by clinical
    acuity: `O` is rank 1, `A` is rank 2, `B` is rank 3, `C` is rank 4, `D` is rank 5, and
    `E` — the ECHO level, the most acute — is rank 6."
    PRD §2.10: "The response mode is `HOT` when the level letter is `D` or `E`, and `COLD`
    for every other letter."
    PRD §2.10: "The resource tier is `ALS` when the level letter is `C`, `D` or `E`, and
    `BLS` for every other letter."
    PRD §2.10: "On a call record these three decodings are stored as
    `dispatched_priority_rank`, `response_mode_assigned` and `resource_assigned`; on a
    score sheet the same decoding of the reviewer's code is stored as
    `reviewer_priority_rank`, `reviewer_response_mode` and `reviewer_resource`."
    PRD §3.1: "A freshly ingested call has `status` of `INGESTED`; it becomes `SELECTED`
    once a non-voided review references it, and returns to `INGESTED` if that review is
    ever voided."

    Design: Corner/entities/call_record_computed_priority_and_response_mode_from_determinant_code
    """
    env = fx.enrolled_dispatcher_env(api)

    data = validate_success(
        api.create_call_record(
            env["dispatcher_id"],
            f.call_record_payload(
                call_reference="C-0001",
                call_type=call_type,
                received_at="2026-08-05T09:00:00Z",
                dispatched_determinant_code=code,
            ),
            ADMIN,
        ),
        201,
    )

    assert data["dispatched_determinant_code"] == code
    assert data["dispatched_priority_rank"] == expected_rank
    assert data["response_mode_assigned"] == expected_mode
    assert data["resource_assigned"] == expected_resource
    assert data["status"] == "INGESTED"


def test_targeted_selection_mints_the_reviews_status_and_derived_references(api):
    """PRD §3.4: "A successful targeted selection creates one review with `selection_mode`
    of `TARGETED`, moves the call to `SELECTED`, and increments the period's
    `selected_review_count` by one."
    PRD §3.4: "Whichever route created it, a new review is born in `status` `SELECTED` with
    `current_sheet_round` at 0, with `provisional_composite_score`,
    `pre_penalty_composite_score`, `determinant_accuracy`, `penalty_points`,
    `final_composite_score` and `compliant` all null, with `rebuttal_round_count` at 0, and
    with no `scored_at`, `finalized_at`, `voided_at` or `void_reason`."
    PRD §3.4: "The first is `dispatcher_id`, copied from the call record so that the review
    is permanently attributed to the dispatcher who handled the call even if the roster
    later changes."
    PRD §2.4: "Every resource carries an `id` that is a server-minted UUID with no type
    prefix; clients never supply one."

    Design: Corner/entities/review_status_and_identity_are_system_minted_client_input_ignored
    """
    env = fx.enrolled_dispatcher_env(api)
    call = fx.ingest_call(api, env["dispatcher_id"], call_reference="C-0001")
    period = fx.new_period(api, env["program_id"])

    response = api.target_review(
        period["id"],
        f.target_review_payload(call["id"], selection_reason="COMPLAINT"),
        SUPERVISOR,
    )
    data = validate_success(response, 201)

    assert_common_fields(data, expected_version=1)
    assert data["status"] == "SELECTED"
    assert data["selection_mode"] == "TARGETED", "the route stamps the selection mode"
    assert data["selection_reason"] == "COMPLAINT"
    assert data["current_sheet_round"] == 0
    assert data["final_composite_score"] is None
    assert data["dispatcher_id"] == env["dispatcher_id"], "copied from the call record"
    assert data["protocol_version_id"] == env["version_id"], "pinned at selection time"


@pytest.mark.parametrize(
    "overrides",
    [
        {"call_type": "STROKE"},
        {"sampling_mode": "PARTIAL"},
        {"target_sample_count": -1},
    ],
    ids=["undeclared_call_type", "undeclared_sampling_mode", "negative_sample_count"],
)
def test_sampling_period_rejects_a_payload_outside_its_declared_values(api, overrides):
    """PRD §2.9: "**Request shape** — the body parses, required fields are present, types
    match, enum values are declared members, and numeric fields are in range, else
    `ERR_INVALID_REQUEST`."
    PRD §3.4: "A `QaSupervisor` opens a period under a programme with a `call_type` from
    the five chief-complaint buckets, a `period_start` and a `period_end` bounding the
    calls it may draw on — the window is half-open, so a call answered exactly at
    `period_start` is inside it and a call answered exactly at `period_end` is not, and a
    `period_end` that is not strictly after `period_start` is rejected with
    `ERR_INVALID_TIME_WINDOW`."
    PRD §2.9: "In-range means, among others, that section points earned and possible are
    both at least 0 and that earned never exceeds possible, that `recognition_time_sec` and
    `time_to_first_compression_sec` are at least 0, that `target_sample_count`,
    `requested_count` and `target_dispatcher_count` are at least 1, that
    `required_training_hours` is greater than 0, and that hours thresholds are at least 0."

    Design: Corner/entities/sampling_period_with_an_unknown_call_type_enum_is_rejected
    """
    program = fx.new_program(api, name="Basin EMD QA", accreditation_body="IAED")

    response = api.create_sampling_period(
        program["id"], f.sampling_period_payload(**overrides), SUPERVISOR
    )
    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_sampling_periods(program["id"], SUPERVISOR, {"limit": 100})
    )
    assert rows == [], "a rejected period must not be stored"
    assert meta["total_count"] == 0


def test_sampling_period_accepts_a_declared_call_type_and_sampling_mode(api):
    """PRD §3.4: "The period's `sampling_mode` decides which of the two selection routes it
    will accept: `RANDOM` accepts only the systematic random draw, `TARGETED` accepts only
    the case-by-case targeted selection, and `MIXED` accepts both."
    PRD §3.4: "A new period has `status` of `OPEN`, no `closed_at`, no `locked_at`, and both
    counters — `selected_review_count` and `finalized_review_count` — at 0."

    Design: Corner/entities/sampling_period_with_an_unknown_call_type_enum_is_rejected
    """
    program = fx.new_program(api, name="Basin EMD QA", accreditation_body="IAED")

    data = validate_success(
        api.create_sampling_period(
            program["id"],
            f.sampling_period_payload(
                call_type="BREATHING_PROBLEM", sampling_mode="RANDOM", target_sample_count=5
            ),
            SUPERVISOR,
        ),
        201,
    )
    assert data["call_type"] == "BREATHING_PROBLEM"
    assert data["sampling_mode"] == "RANDOM"
    assert data["status"] == "OPEN"
    assert data["selected_review_count"] == 0
    assert data["finalized_review_count"] == 0


def test_a_second_submission_appends_a_round_and_leaves_the_first_sheet_untouched(api):
    """PRD §2.4: "The single exception is the score sheet: because sheets are append-only
    audit artefacts that are never edited after submission, a score sheet carries only `id`
    and `created_at`, and both `updated_at` and `version` are absent from it entirely."
    PRD §3.5: "Sheets themselves are **append-only**: each submission creates a new score
    sheet whose `sheet_round` is one greater than the review's `current_sheet_round` at the
    moment of submission, and no earlier sheet is ever mutated or deleted."
    PRD §3.5: "The sheet with the highest round is "the current sheet", and the review's
    `current_sheet_round` is set to that round on every submission."
    PRD §3.5: "The sheet's `provisional_composite_score` is then the arithmetic mean of
    those four already-rounded percentages, rounded half up to 1 decimal place — under this
    view each of the four sections contributes exactly one quarter, regardless of the
    weights on the pinned protocol version, and no determinant penalty is applied."

    Design: Corner/entities/score_sheet_carries_no_version_field_and_cannot_be_mutated
    """
    env = fx.scored_review_env(
        api, sections=SHEET_78_7, reviewer_determinant_code="10-C-2"
    )
    first = env["sheet"]
    assert_score_sheet_shape(first)
    assert first["sheet_round"] == 1
    # 90.00, 86.67, 66.67 and 71.43 average to 78.6925, which rounds half up to 78.7.
    assert first["provisional_composite_score"] == approx1(78.7)
    assert first["determinant_accuracy"] == "MINOR_MISCODE"

    current = fx.get_review(api, env["review_id"])
    second = validate_success(
        api.submit_scores(
            env["review_id"],
            f.section_score_payload(current["version"], PERFECT_SHEET, "10-C-4"),
            REVIEWER,
        ),
        201,
    )
    assert_score_sheet_shape(second)
    assert second["id"] != first["id"], "each submission creates a new sheet"
    assert second["sheet_round"] == 2
    assert second["provisional_composite_score"] == approx1(100.0)
    assert second["determinant_accuracy"] == "ACCURATE"

    sheets = fx.list_sheets(api, env["review_id"])
    assert [sheet["sheet_round"] for sheet in sheets] == [1, 2]
    stored_first = next(sheet for sheet in sheets if sheet["id"] == first["id"])
    assert_score_sheet_shape(stored_first)
    assert stored_first["provisional_composite_score"] == approx1(78.7), (
        "the superseded sheet is never mutated"
    )
    assert stored_first["determinant_accuracy"] == "MINOR_MISCODE"
    assert stored_first["case_entry_pct"] == approx2(90.00)
    assert stored_first["key_questions_pct"] == approx2(86.67)

    review = fx.get_review(api, env["review_id"])
    assert review["current_sheet_round"] == 2
    assert review["provisional_composite_score"] == approx1(100.0)


def test_creating_a_protocol_version_under_an_unknown_program_reports_the_parent(api):
    """PRD §2.5: "Path identifiers are resolved strictly left to right, and the first
    identifier that does not resolve determines the error: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_PROTOCOL_VERSION_NOT_FOUND`, `ERR_ROLLOUT_NOT_FOUND`, `ERR_DISPATCHER_NOT_FOUND`,
    `ERR_SAMPLING_PERIOD_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_REBUTTAL_NOT_FOUND`,
    `ERR_HIGH_RISK_REVIEW_NOT_FOUND`, `ERR_COACHING_PLAN_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    or `ERR_REPORT_NOT_FOUND`, each at HTTP 404."
    PRD §2.5: "A missing parent is therefore never reported as a problem with the child."

    Design: Corner/entities/create_protocol_version_under_an_unknown_program_returns_not_found
    """
    program = fx.new_program(api, name="Basin EMD QA", accreditation_body="IAED")

    response = api.create_protocol_version(
        NON_EXISTENT_UUID, f.protocol_version_payload(version_label="MPDS-13.9"), ADMIN
    )
    validate_error(response, err.ERR_PROGRAM_NOT_FOUND, 404)

    rows, meta = validate_paginated(
        api.list_protocol_versions(program["id"], ADMIN, {"limit": 100})
    )
    assert rows == [], "nothing may be written under the real programme"
    assert meta["total_count"] == 0
