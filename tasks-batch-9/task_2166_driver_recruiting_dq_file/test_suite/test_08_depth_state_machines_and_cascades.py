"""Depth coverage: parallel axes, cyclic machines, and the four-hop cascades."""
from test_helpers import (
    TEST_USERS,
    activate_tuition_agreement,
    create_application,
    create_open_session,
    create_tuition_agreement,
    drive_segment_to_good_faith,
    fetch_applicant,
    fetch_carrier,
    fetch_dq_document,
    fetch_dq_file,
    grant_consent,
    open_clearinghouse_query,
    order_drug_test,
    order_screening_check,
    collect_specimen,
    record_employment_segment,
    record_lab_result,
    record_mro_verification,
    reserve_seat,
    setup_hired_applicant,
    setup_road_test_passed_application,
    setup_submitted_application,
    terminate_hire,
    validate_success,
)

RECRUITER = TEST_USERS["recruiter_headers"]
DER = TEST_USERS["der_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]
SCHOOL = TEST_USERS["school_coordinator_headers"]

GOOD_FAITH_CLOCK_STOPS = (
    "2026-08-15T00:00:00Z",
    "2026-08-29T00:00:00Z",
    "2026-09-12T00:00:00Z",
)


def _dilute_then_positive_specimen(dot_number: str):
    """A specimen that came back DILUTE, was recollected once, then read POSITIVE."""
    ctx = setup_submitted_application(carrier_overrides={"dot_number": dot_number})
    order = order_drug_test(ctx["application_id"], "PRE_EMPLOYMENT")
    collect_specimen(order["id"], "2026-08-01T09:00:00Z")
    record_lab_result(order["id"], "DILUTE")
    collect_specimen(order["id"], "2026-08-03T09:00:00Z")
    record_lab_result(order["id"], "POSITIVE")
    ctx["drug_test_order"] = order
    return ctx


def _road_test_passed_with_reserved_seat_and_consent(dot_number: str):
    """A ROAD_TEST_PASSED application holding a RESERVED seat and a consented FULL query."""
    ctx = setup_road_test_passed_application(carrier_overrides={"dot_number": dot_number})
    session = create_open_session(ctx["carrier_id"])
    ctx["session"] = session
    ctx["enrollment"] = reserve_seat(
        session["id"], ctx["application_id"], session["version"]
    )
    query = open_clearinghouse_query(ctx["application_id"], "FULL")
    grant_consent(query["id"], ctx["applicant_id"])
    ctx["clearinghouse_query"] = query
    return ctx


def _hired_with_active_tuition_and_a_second_draft(dot_number: str):
    """A hired driver carrying an ACTIVE agreement and a second DRAFT application."""
    ctx = setup_hired_applicant(carrier_overrides={"dot_number": dot_number})
    agreement = create_tuition_agreement(
        ctx["applicant_id"], tuition_total_cents=115205, commitment_months=12
    )
    ctx["tuition_agreement"] = activate_tuition_agreement(agreement["id"])
    ctx["second_application"] = create_application(
        ctx["applicant_id"], position_type="LOCAL"
    )
    return ctx


# ─── non_linear_state_machine ─────────────────────────────────────────────────

def test_the_qualification_axis_advances_while_the_screening_axis_lags(api):
    """PRD §3.2: "The application carries **two independent state axes**."
    PRD §3.2: "The axes advance independently and join in exactly one place, at
    `ORIENTATION_COMPLETE → QUALIFIED`."
    PRD §3.6: "On success the test moves `SCHEDULED → PASSED`, which is its terminal state; the
    application's `qualification_status` advances `IN_PROGRESS → ROAD_TEST_PASSED`; the
    `ROAD_TEST_CERT` document of the application's qualification file becomes `PRESENT` with
    `effective_on` at the current logical-clock date; and the file's `completeness_pct`,
    `deficiency_count` and status are recomputed with its `version` incremented by one."
    PRD §3.4: "Orders open in `ORDERED`, and the very first order placed against a `SUBMITTED`
    application advances that application's `screening_status` from `SUBMITTED` to `SCREENING`
    as a system side effect."

    Design: Difficulty/non_linear_state_machine/application_parallel_axes_advance_independently
    """
    ctx = setup_road_test_passed_application(carrier_overrides={"dot_number": "DOT-2166-G"})
    order_screening_check(ctx["application_id"], "MVR")

    application = validate_success(
        api.get_driver_application(ctx["application_id"], SAFETY_DIRECTOR)
    )

    assert application["qualification_status"] == "ROAD_TEST_PASSED"
    assert application["screening_status"] == "SCREENING", (
        "the screening axis is not a function of the qualification axis"
    )


def test_a_passed_road_test_leaves_the_ordered_report_untouched(api):
    """PRD §3.6: "Those three already-rounded section values are then added together and the sum
    is rounded half up to one decimal place, and that one-decimal figure is `composite_score`."
    PRD §3.4: "Orders open in `ORDERED`, and the very first order placed against a `SUBMITTED`
    application advances that application's `screening_status` from `SUBMITTED` to `SCREENING`
    as a system side effect."
    PRD §3.2: "The `Recruiter` closes the round by supplying a `response_note`, moving the axis
    `INFO_REQUESTED → SCREENING` and incrementing `revision_round` by one."

    Design: Difficulty/non_linear_state_machine/application_parallel_axes_advance_independently
    """
    ctx = setup_road_test_passed_application(carrier_overrides={"dot_number": "DOT-2166-G"})
    mvr = order_screening_check(ctx["application_id"], "MVR")

    check = validate_success(api.get_screening_check(mvr["id"], RECRUITER))
    road_test = validate_success(api.get_road_test(ctx["road_test"]["id"], RECRUITER))
    application = validate_success(
        api.get_driver_application(ctx["application_id"], SAFETY_DIRECTOR)
    )

    assert check["status"] == "ORDERED"
    assert float(road_test["composite_score"]) == 83.8
    assert application["revision_round"] == 0


def test_the_third_documented_request_lands_the_segment_in_good_faith(api):
    """PRD §3.3: "That single trigger branches on the round counter, and the two branches are
    exact mirrors of one another. While `request_round` is strictly less than 3, the segment
    falls back to `NO_RESPONSE`, changing nothing else, and the loop `REQUESTED → NO_RESPONSE →
    REQUESTED` may run again. Once `request_round` has reached 3, the same trigger instead lands
    the segment in the terminal `GOOD_FAITH_DOCUMENTED` state, and that transition recomputes the
    parent application's `verified_coverage_days` and `gap_days_unexplained` — which, under the
    strict accounting those two fields use, does *not* credit the good-faith segment."
    PRD §3.3: "Issuing the request moves the segment to `REQUESTED` from either `PENDING` or
    `NO_RESPONSE`, increments `request_round` by one and stamps `last_requested_at` with the
    current logical-clock instant; a segment whose parent application has already reached
    `SCREEN_FAILED` may not be chased further, and a re-request out of `NO_RESPONSE` is accepted
    only while `request_round` is strictly less than 3."

    Design: Difficulty/non_linear_state_machine/employment_verification_cycles_then_branches_to_good_faith
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-2166-H"})
    segment = record_employment_segment(
        ctx["application_id"], "Silver Spur Freight", "2022-01-01", "2024-09-01"
    )

    final = drive_segment_to_good_faith(segment["id"], GOOD_FAITH_CLOCK_STOPS)

    assert final["status"] == "GOOD_FAITH_DOCUMENTED"
    assert final["request_round"] == 3


def test_the_good_faith_branch_credits_no_strict_coverage(api):
    """PRD §3.3: "The strict accounting, named `strict_verified`, admits only segments in
    `RESPONDED_VERIFIED`; it is the default, it is the one persisted into the application's
    `verified_coverage_days` and `gap_days_unexplained`, and it is the one the hiring gate
    enforces."
    PRD §3.3: "The `verified_coverage_days` figure is the total number of days spanned by the
    merged runs, and `gap_days_unexplained` is 1,095 minus that figure."

    Design: Difficulty/non_linear_state_machine/employment_verification_cycles_then_branches_to_good_faith
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-2166-H"})
    segment = record_employment_segment(
        ctx["application_id"], "Silver Spur Freight", "2022-01-01", "2024-09-01"
    )
    drive_segment_to_good_faith(segment["id"], GOOD_FAITH_CLOCK_STOPS)

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )

    assert application["verified_coverage_days"] == 0
    assert application["gap_days_unexplained"] == 1095


def test_a_verified_negative_after_one_recollection_and_a_positive_lab(api):
    """PRD §3.5: "Recording a collection supplies the `collected_at` instant and moves the order
    to `COLLECTED` from either `ORDERED` or `LAB_DILUTE`; the second of those is a recollection
    and is accepted only while `dilute_recollect_count` is strictly below the single permitted
    recollection, meaning a count of zero, and it increments that counter by one."
    PRD §3.5: "A `VERIFIED_NEGATIVE` decision is accepted from `LAB_NEGATIVE` and, identically,
    from `LAB_POSITIVE` — the latter being the case where the officer accepts a legitimate
    medical explanation — and both branches carry exactly the same consequences: the order lands
    in `MRO_VERIFIED_NEGATIVE`, the `DRUG_TEST_RESULT` document of the application's
    qualification file becomes `PRESENT` with `effective_on` at the current logical-clock date,
    that file's `completeness_pct`, `deficiency_count` and status are recomputed, its `version`
    increments by one, and the application is re-evaluated for the `SCREENING → SCREEN_CLEARED`
    move."

    Design: Difficulty/non_linear_state_machine/drug_test_dilute_cycle_then_mro_branch_to_negative
    """
    ctx = _dilute_then_positive_specimen("DOT-2166-I")

    verified = record_mro_verification(
        ctx["drug_test_order"]["id"], "VERIFIED_NEGATIVE"
    )

    assert verified["status"] == "MRO_VERIFIED_NEGATIVE"
    assert verified["dilute_recollect_count"] == 1
    assert verified["collected_at"] == "2026-08-03T09:00:00.000Z"


def test_the_negative_branch_files_the_specimen_artifact_without_disqualifying(api):
    """PRD §3.5: "A `VERIFIED_NEGATIVE` decision is accepted from `LAB_NEGATIVE` and,
    identically, from `LAB_POSITIVE` — the latter being the case where the officer accepts a
    legitimate medical explanation — and both branches carry exactly the same consequences: the
    order lands in `MRO_VERIFIED_NEGATIVE`, the `DRUG_TEST_RESULT` document of the application's
    qualification file becomes `PRESENT` with `effective_on` at the current logical-clock date,
    that file's `completeness_pct`, `deficiency_count` and status are recomputed, its `version`
    increments by one, and the application is re-evaluated for the `SCREENING → SCREEN_CLEARED`
    move."
    PRD §3.5: "The laboratory then reports. From `COLLECTED`, a `lab_result` of `NEGATIVE`,
    `POSITIVE` or `DILUTE` moves the order to `LAB_NEGATIVE`, `LAB_POSITIVE` or `LAB_DILUTE`
    respectively; none of the three changes anything beyond the status, and in particular a
    positive laboratory result on its own triggers no cascade whatsoever — a Medical Review
    Officer must verify it first."

    Design: Difficulty/non_linear_state_machine/drug_test_dilute_cycle_then_mro_branch_to_negative
    """
    ctx = _dilute_then_positive_specimen("DOT-2166-I")

    record_mro_verification(ctx["drug_test_order"]["id"], "VERIFIED_NEGATIVE")

    document = fetch_dq_document(ctx["dq_file_id"], "DRUG_TEST_RESULT")
    assert document["status"] == "PRESENT"

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["screening_status"] == "SUBMITTED"
    assert application["qualification_status"] == "IN_PROGRESS"


# ─── transitive_cascade ───────────────────────────────────────────────────────

def test_a_prohibited_result_fails_the_screening_axis_and_disqualifies(api):
    """PRD §3.5: "A `PROHIBITED` result is accepted only on a query whose `query_type` is
    `FULL`, and it is the origin of a four-hop cascade: the parent application's
    `screening_status` becomes `SCREEN_FAILED` with the reason token `CLEARINGHOUSE_PROHIBITED`;
    that in turn drives the same application's `qualification_status` to `DISQUALIFIED`; that in
    turn moves the one-to-one qualification file to `ARCHIVED`, increments its `version` by one,
    and cancels every `RESERVED` orientation enrollment of that application; and that in turn
    recomputes the carrier's `filled_requisitions`, `deficiency_ratio` and `posture` and
    increments the carrier's `version` by one."

    Design: Difficulty/transitive_cascade/clearinghouse_prohibited_four_hop_cascade
    """
    ctx = _road_test_passed_with_reserved_seat_and_consent("DOT-2166-J")

    prohibited = validate_success(
        api.record_clearinghouse_result(
            ctx["clearinghouse_query"]["id"], {"result": "PROHIBITED"}, DER
        )
    )

    assert prohibited["status"] == "RESULT_PROHIBITED"
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["screening_status"] == "SCREEN_FAILED"
    assert application["qualification_status"] == "DISQUALIFIED"
    assert application["disqualifying_reason"] == "CLEARINGHOUSE_PROHIBITED"


def test_the_prohibited_cascade_archives_the_file_and_repays_the_seat(api):
    """PRD §3.5: "A `PROHIBITED` result is accepted only on a query whose `query_type` is
    `FULL`, and it is the origin of a four-hop cascade: the parent application's
    `screening_status` becomes `SCREEN_FAILED` with the reason token `CLEARINGHOUSE_PROHIBITED`;
    that in turn drives the same application's `qualification_status` to `DISQUALIFIED`; that in
    turn moves the one-to-one qualification file to `ARCHIVED`, increments its `version` by one,
    and cancels every `RESERVED` orientation enrollment of that application; and that in turn
    recomputes the carrier's `filled_requisitions`, `deficiency_ratio` and `posture` and
    increments the carrier's `version` by one."
    PRD §3.2: "The consequences fan out: every orientation enrollment of that application still
    in `RESERVED` becomes `CANCELLED`, and each such cancellation decrements the owning session's
    `enrolled_count` by one and increments that session's `version` by one; the one-to-one
    qualification file moves to `ARCHIVED` and its `version` increments by one; and the carrier's
    `filled_requisitions`, `deficiency_ratio` and `posture` are recomputed."

    Design: Difficulty/transitive_cascade/clearinghouse_prohibited_four_hop_cascade
    """
    ctx = _road_test_passed_with_reserved_seat_and_consent("DOT-2166-J")
    carrier_before = fetch_carrier(ctx["carrier_id"])

    validate_success(
        api.record_clearinghouse_result(
            ctx["clearinghouse_query"]["id"], {"result": "PROHIBITED"}, DER
        )
    )

    assert fetch_dq_file(ctx["dq_file_id"])["status"] == "ARCHIVED"
    enrollment = validate_success(
        api.get_orientation_enrollment(ctx["enrollment"]["id"], RECRUITER)
    )
    assert enrollment["status"] == "CANCELLED"
    session = validate_success(
        api.get_orientation_session(ctx["session"]["id"], RECRUITER)
    )
    assert session["enrolled_count"] == 0

    carrier_after = fetch_carrier(ctx["carrier_id"])
    assert carrier_after["version"] == carrier_before["version"] + 1
    assert carrier_after["posture"] == "OPEN"
    assert float(carrier_after["deficiency_ratio"]) == 0.0


def test_termination_moves_the_outstanding_balance_into_a_clawback(api):
    """PRD §3.8: "The first hop moves the record `ACTIVE → TERMINATED` and writes
    `terminated_on`, `termination_type`, `rehire_flag` and `tenure_days`, the last being the whole
    number of days from `hired_on` to `terminated_on`. The second hop, caused by the first, moves
    every tuition agreement of that applicant still in `ACTIVE` into `TERMINATED_CLAWBACK`,
    shifting each agreement's whole `outstanding_cents` balance into its `clawback_cents`."
    PRD §3.9: "As the second hop of the termination cascade of §3.8, an `ACTIVE` agreement moves
    to `TERMINATED_CLAWBACK`: its entire `outstanding_cents` balance is moved into
    `clawback_cents` and `outstanding_cents` is set to zero."

    Design: Difficulty/transitive_cascade/termination_four_hop_turnover_cascade
    """
    ctx = _hired_with_active_tuition_and_a_second_draft("DOT-2166-K")

    hire = terminate_hire(
        ctx["hire_id"],
        terminated_on="2026-08-20",
        termination_type="INVOLUNTARY_SAFETY",
        rehire_flag="NOT_ELIGIBLE",
    )

    assert hire["status"] == "TERMINATED"
    assert hire["tenure_days"] == 7
    assert hire["terminated_on"] == "2026-08-20"

    agreement = validate_success(
        api.get_tuition_agreement(ctx["tuition_agreement"]["id"], SCHOOL)
    )
    assert agreement["status"] == "TERMINATED_CLAWBACK"
    assert agreement["clawback_cents"] == 115200
    assert agreement["outstanding_cents"] == 0


def test_the_clawback_bars_rehire_and_disqualifies_the_open_application(api):
    """PRD §3.8: "The third hop, caused by the second, recomputes the applicant's
    `outstanding_clawback_cents` and `rehire_eligibility`, and any positive clawback forces that
    eligibility to `PERMANENTLY_INELIGIBLE`. The fourth hop, caused by the third, fires only when
    the eligibility has become `PERMANENTLY_INELIGIBLE`: every application of that applicant whose
    `qualification_status` is not already terminal is driven to `DISQUALIFIED` with the reason
    token `REHIRE_INELIGIBLE`, which archives each of those applications' files and cancels their
    reserved enrollments."
    PRD §3.1: "The `filled_requisitions` count is the number of hire records at that carrier whose
    status is `ACTIVE`; terminated and rescinded hires do not count."

    Design: Difficulty/transitive_cascade/termination_four_hop_turnover_cascade
    """
    ctx = _hired_with_active_tuition_and_a_second_draft("DOT-2166-K")

    terminate_hire(
        ctx["hire_id"],
        terminated_on="2026-08-20",
        termination_type="INVOLUNTARY_SAFETY",
        rehire_flag="NOT_ELIGIBLE",
    )

    applicant = fetch_applicant(ctx["applicant_id"])
    assert applicant["outstanding_clawback_cents"] == 115200
    assert applicant["rehire_eligibility"] == "PERMANENTLY_INELIGIBLE"

    second = validate_success(
        api.get_driver_application(ctx["second_application"]["id"], RECRUITER)
    )
    assert second["qualification_status"] == "DISQUALIFIED"
    assert second["disqualifying_reason"] == "REHIRE_INELIGIBLE"

    hired = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert hired["qualification_status"] == "HIRED", (
        "an already-terminal application is untouched by the fourth hop"
    )
    assert fetch_carrier(ctx["carrier_id"])["filled_requisitions"] == 0
