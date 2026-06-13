"""Placement-creation preconditions: boundaries, precedence, cross-entity state,
temporal overlap, and optimistic concurrency.

Translates Difficulty/boundary_precision_check, Difficulty/priority_pair_validation_conflict,
Difficulty/cross_entity_state_dependency, Difficulty/resource_temporal_overlap, and the
OCC corner.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_active_placement, setup_offer_extended_scenario,
    drive_submission_to_offer_extended, create_placement, start_placement,
    create_skill, create_client, create_open_job_order, create_candidate,
    create_timesheet, submit_timesheet, reject_timesheet,
    make_account_manager_headers, make_recruiter_headers,
    make_client_headers, make_candidate_headers,
)

AM = make_account_manager_headers()
RECRUITER = make_recruiter_headers()


# --- boundary_precision_check ------------------------------------------------

def test_overtime_threshold_exactly_40_yields_no_overtime(api):
    """PRD 3.6: "Overtime applies strictly above the threshold, so a week of exactly 40.0
    hours yields zero overtime hours."
    PRD 3.6: "the placement's `bill_rate_cents` applies to the regular portion."

    40.0h (bill 12000): bill_cents == 40*12000 == 480000, no overtime.

    Design: Difficulty/boundary_precision_check/overtime_threshold_exactly_40
    """
    scen = setup_active_placement()
    ts = create_timesheet(
        scen["placement"]["id"], scen["candidate"]["id"],
        "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 40)
    assert ts["bill_cents"] == 480000, f"40h bill should be 480000, got {ts['bill_cents']}"


def test_overtime_threshold_just_above_40_bills_overtime(api):
    """PRD 3.6: "the overtime portion is whatever exceeds 40, or zero if the worked hours do
    not exceed 40."
    PRD 3.6: "one and one-half times that bill rate applies to the overtime portion; again the
    two components are summed first and the total is then rounded half-up to whole cents."

    40.5h (bill 12000): bill = round_half_up(40*12000 + 0.5*12000*1.5) = 480000 + 9000 = 489000.

    Design: Difficulty/boundary_precision_check/overtime_threshold_exactly_40
    """
    scen = setup_active_placement()
    ts = create_timesheet(
        scen["placement"]["id"], scen["candidate"]["id"],
        "2026-06-22T00:00:00Z", "2026-06-29T00:00:00Z", 40.5)
    assert ts["bill_cents"] == 489000, f"40.5h bill should be 489000, got {ts['bill_cents']}"


def test_credit_limit_equality_is_allowed(api):
    """PRD 3.4: "the create is permitted only when that sum is at most the client's
    `credit_limit_cents`. Equality is allowed: a sum exactly equal to the limit passes."

    One ACTIVE placement (open_exposure 480000) plus a second placement (projected 480000) on a
    client whose credit_limit_cents == 960000: the sum equals the limit exactly, so the second
    placement is created (PENDING_START).

    Design: Difficulty/boundary_precision_check/credit_limit_equality_allowed
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Edge", credit_limit_cents=960000)
    cand_a = create_candidate(full_name="Cand A", skill_codes=["JAVA"])
    cand_b = create_candidate(full_name="Cand B", skill_codes=["JAVA"])
    jo_a, jo_a_v = create_open_job_order(cl["id"], title="Dev A", openings=1)
    sub_a, _ = drive_submission_to_offer_extended(jo_a, cand_a, cl)
    pl_a = create_placement(sub_a["id"], jo_a_v, start_date="2026-06-15T00:00:00Z",
                            end_date="2026-12-15T00:00:00Z", standard_weekly_hours=40)
    start_placement(pl_a["id"])

    jo_b, jo_b_v = create_open_job_order(cl["id"], title="Dev B", openings=1)
    sub_b, _ = drive_submission_to_offer_extended(jo_b, cand_b, cl)
    placement_b = get_success_data(api.create_placement(
        {"submission_id": sub_b["id"], "start_date": "2026-06-15T00:00:00Z",
         "end_date": "2026-12-15T00:00:00Z", "expected_job_order_version": jo_b_v,
         "standard_weekly_hours": 40}, RECRUITER))
    assert placement_b["assignment_status"] == "PENDING_START", (
        f"placement B should be created PENDING_START, got {placement_b['assignment_status']}"
    )


def test_credit_limit_just_below_required_is_rejected(api):
    """PRD 3.4: "the create is permitted only when that sum is at most the client's
    `credit_limit_cents`."
    PRD 3.4: "A sum strictly above the limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    One ACTIVE placement (open_exposure 480000) plus a second placement (projected 480000) on a
    client whose credit_limit_cents == 959999: the sum 960000 strictly exceeds the limit, so the
    second placement is rejected with ERR_CREDIT_LIMIT_EXCEEDED (the X+1 boundary partner of the
    equality case).

    Design: Difficulty/boundary_precision_check/credit_limit_equality_allowed
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="JustUnder", credit_limit_cents=959999)
    cand_a = create_candidate(full_name="Cand A", skill_codes=["JAVA"])
    cand_b = create_candidate(full_name="Cand B", skill_codes=["JAVA"])
    jo_a, jo_a_v = create_open_job_order(cl["id"], title="Dev A", openings=1)
    sub_a, _ = drive_submission_to_offer_extended(jo_a, cand_a, cl)
    pl_a = create_placement(sub_a["id"], jo_a_v, start_date="2026-06-15T00:00:00Z",
                            end_date="2026-12-15T00:00:00Z", standard_weekly_hours=40)
    start_placement(pl_a["id"])

    jo_b, jo_b_v = create_open_job_order(cl["id"], title="Dev B", openings=1)
    sub_b, _ = drive_submission_to_offer_extended(jo_b, cand_b, cl)
    resp = api.create_placement(
        {"submission_id": sub_b["id"], "start_date": "2026-06-15T00:00:00Z",
         "end_date": "2026-12-15T00:00:00Z", "expected_job_order_version": jo_b_v,
         "standard_weekly_hours": 40}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


# --- priority_pair_validation_conflict ---------------------------------------

def test_submission_state_check_precedes_credit_gate(api):
    """PRD 3.4: "First, the submission must be `OFFER_EXTENDED`; otherwise
    `ERR_SUBMISSION_NOT_OFFER_EXTENDED`."
    PRD 3.4: "Finally the credit gate applies, as described below; a breach yields
    `ERR_CREDIT_LIMIT_EXCEEDED`."

    A placement create where the submission is still SUBMITTED (not OFFER_EXTENDED) AND the
    client credit (limit 1) would be exceeded must report the earlier-evaluated
    ERR_SUBMISSION_NOT_OFFER_EXTENDED (409), not ERR_CREDIT_LIMIT_EXCEEDED (402).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_placement
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Tight", credit_limit_cents=1)
    jo, jo_v = create_open_job_order(cl["id"], openings=1)
    cand = create_candidate(full_name="Cara Dev", skill_codes=["JAVA"])
    sub = get_success_data(api.create_submission(
        {"job_order_id": jo["id"], "candidate_id": cand["id"], "submitted_pay_rate_cents": 8000},
        RECRUITER))
    resp = api.create_placement(
        {"submission_id": sub["id"], "start_date": "2026-06-15T00:00:00Z",
         "end_date": "2026-12-15T00:00:00Z", "expected_job_order_version": jo_v,
         "standard_weekly_hours": 40}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_NOT_OFFER_EXTENDED)


def test_credit_gate_fires_in_isolation_when_only_failure(api):
    """PRD 3.4: "Finally the credit gate applies, as described below; a breach yields
    `ERR_CREDIT_LIMIT_EXCEEDED`."
    PRD 3.4: "A sum strictly above the limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    A fully-valid placement request (submission OFFER_EXTENDED, order OPEN, candidate AVAILABLE, no
    overlap, opening free, fresh version) whose only failing precondition is the credit gate
    (projected 480000 against a client limit of 1) returns ERR_CREDIT_LIMIT_EXCEEDED in isolation.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_placement
    """
    scen = setup_offer_extended_scenario(client_overrides={"name": "Tight", "credit_limit_cents": 1})
    resp = api.create_placement(
        {"submission_id": scen["submission"]["id"], "start_date": "2026-06-15T00:00:00Z",
         "end_date": "2026-12-15T00:00:00Z", "expected_job_order_version": scen["jo_version"],
         "standard_weekly_hours": 40}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


def test_skill_mismatch_fires_in_isolation_with_well_formed_body(api):
    """PRD 3.3: "the candidate must hold the job order's `required_skill_code` among their
    `skill_codes`, and a candidate who does not is rejected with `ERR_SKILL_MISMATCH`."

    A submission with a well-formed body (positive submitted_pay_rate_cents) whose only failure is
    the skill mismatch (candidate holds FORKLIFT, order requires JAVA) returns ERR_SKILL_MISMATCH in
    isolation — the business referential check fires once body validation passes.

    Design: Difficulty/priority_pair_validation_conflict/skill_referential_beats_temporal_on_submission_vs_placement
    """
    create_skill(code="JAVA", category="TECH")
    create_skill(code="FORKLIFT", category="INDUSTRIAL")
    cl = create_client(name="Acme")
    jo, _jo_v = create_open_job_order(cl["id"], required_skill_code="JAVA", openings=1)
    cand = create_candidate(full_name="Wrong Skill", skill_codes=["FORKLIFT"])
    resp = api.create_submission(
        {"job_order_id": jo["id"], "candidate_id": cand["id"], "submitted_pay_rate_cents": 8000},
        RECRUITER)
    validate_error(resp, ApiErrorId.ERR_SKILL_MISMATCH)


# --- cross_entity_state_dependency -------------------------------------------

def test_submission_advance_blocked_when_job_order_on_hold(api):
    """PRD 3.3: "From `SUBMITTED`, the `Recruiter` hands the candidate to the employer by advancing
    the submission to `CLIENT_REVIEW`; this requires the submission to currently be `SUBMITTED`
    (otherwise `ERR_SUBMISSION_BAD_STATE`) and the job order to be `OPEN` (otherwise
    `ERR_JOB_ORDER_NOT_OPEN`)."

    A submission in a valid from-state (SUBMITTED) cannot advance to CLIENT_REVIEW when its parent
    job order is ON_HOLD -> ERR_JOB_ORDER_NOT_OPEN; the submission stays SUBMITTED.

    Design: Difficulty/cross_entity_state_dependency/submission_advance_requires_open_job_order
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    jo, _jo_v = create_open_job_order(cl["id"], openings=1)
    cand = create_candidate(full_name="Cara Dev", skill_codes=["JAVA"])
    sub = get_success_data(api.create_submission(
        {"job_order_id": jo["id"], "candidate_id": cand["id"], "submitted_pay_rate_cents": 8000},
        RECRUITER))
    get_success_data(api.patch_job_order(jo["id"], {"target_status": "ON_HOLD"}, AM))
    resp = api.patch_submission(sub["id"], {"target_status": "CLIENT_REVIEW"}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_JOB_ORDER_NOT_OPEN)
    unchanged = validate_success(api.get_submission(sub["id"], RECRUITER))
    assert unchanged["status"] == "SUBMITTED", f"submission should stay SUBMITTED, got {unchanged['status']}"


def test_submission_advance_succeeds_when_job_order_open(api):
    """PRD 3.3: "From `SUBMITTED`, the `Recruiter` hands the candidate to the employer by advancing
    the submission to `CLIENT_REVIEW`; this requires the submission to currently be `SUBMITTED`
    (otherwise `ERR_SUBMISSION_BAD_STATE`) and the job order to be `OPEN` (otherwise
    `ERR_JOB_ORDER_NOT_OPEN`)."

    The same cross-entity dependency in the satisfied direction: with the parent order OPEN, the
    SUBMITTED -> CLIENT_REVIEW transition succeeds and the submission becomes CLIENT_REVIEW.

    Design: Difficulty/cross_entity_state_dependency/submission_advance_requires_open_job_order
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    jo, _jo_v = create_open_job_order(cl["id"], openings=1)
    cand = create_candidate(full_name="Cara Dev", skill_codes=["JAVA"])
    sub = get_success_data(api.create_submission(
        {"job_order_id": jo["id"], "candidate_id": cand["id"], "submitted_pay_rate_cents": 8000},
        RECRUITER))
    advanced = validate_success(api.patch_submission(sub["id"], {"target_status": "CLIENT_REVIEW"}, RECRUITER))
    assert advanced["status"] == "CLIENT_REVIEW", f"submission status {advanced['status']}"


def test_timesheet_create_blocked_when_placement_pending_start(api):
    """PRD 3.6: "the placement must be `ACTIVE` (otherwise `ERR_PLACEMENT_NOT_ACTIVE`)."

    Creating a timesheet against a placement still PENDING_START (never started) ->
    ERR_PLACEMENT_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/timesheet_create_requires_active_placement
    """
    scen = setup_offer_extended_scenario()
    placement = create_placement(scen["submission"]["id"], scen["jo_version"])  # PENDING_START
    cand_headers = make_candidate_headers_for(scen)
    resp = api.create_timesheet(
        {"placement_id": placement["id"], "week_start": "2026-06-15T00:00:00Z",
         "week_end": "2026-06-22T00:00:00Z", "hours": 40}, cand_headers)
    validate_error(resp, ApiErrorId.ERR_PLACEMENT_NOT_ACTIVE)


def test_timesheet_create_succeeds_when_placement_active(api):
    """PRD 3.6: "Once a placement is `ACTIVE`, weekly **Timesheets** capture the hours worked."
    PRD 3.6: "the placement must be `ACTIVE` (otherwise `ERR_PLACEMENT_NOT_ACTIVE`). ... A timesheet
    is created in `status` `DRAFT`."

    The same Timesheet->Placement dependency satisfied: against an ACTIVE placement, creating a
    timesheet succeeds (201) and the timesheet is DRAFT.

    Design: Difficulty/cross_entity_state_dependency/timesheet_create_requires_active_placement
    """
    scen = setup_active_placement()
    cand_headers = make_candidate_headers(scen["candidate"]["id"])
    resp = api.create_timesheet(
        {"placement_id": scen["placement"]["id"], "week_start": "2026-06-15T00:00:00Z",
         "week_end": "2026-06-22T00:00:00Z", "hours": 40}, cand_headers)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT", f"timesheet status {data['status']}"


# --- resource_temporal_overlap -----------------------------------------------

def test_placement_date_overlap_closed_interval_shared_endpoint_conflicts(api):
    """PRD 3.4: "the new placement's date range must not overlap any existing placement of the
    same candidate that is `ACTIVE` or `PENDING_START`; otherwise `ERR_PLACEMENT_DATE_OVERLAP`.
    This overlap test treats each date range as a closed interval, so two ranges that merely share
    an endpoint do conflict."

    Candidate has an ACTIVE placement [2026-06-15, 2026-09-15]; a second placement
    [2026-09-15, 2026-12-15] shares the boundary 2026-09-15 -> closed-interval conflict ->
    ERR_PLACEMENT_DATE_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/candidate_placement_date_overlap_closed
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    cand = create_candidate(full_name="Busy Dev", skill_codes=["JAVA"])
    jo_a, jo_a_v = create_open_job_order(cl["id"], title="Dev A", openings=1)
    sub_a, _ = drive_submission_to_offer_extended(jo_a, cand, cl)
    pl_a = create_placement(sub_a["id"], jo_a_v, start_date="2026-06-15T00:00:00Z",
                            end_date="2026-09-15T00:00:00Z", standard_weekly_hours=40)
    start_placement(pl_a["id"])

    jo_b, jo_b_v = create_open_job_order(cl["id"], title="Dev B", openings=1)
    sub_b, _ = drive_submission_to_offer_extended(jo_b, cand, cl)
    resp = api.create_placement(
        {"submission_id": sub_b["id"], "start_date": "2026-09-15T00:00:00Z",
         "end_date": "2026-12-15T00:00:00Z", "expected_job_order_version": jo_b_v,
         "standard_weekly_hours": 40}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_PLACEMENT_DATE_OVERLAP)


def test_timesheet_week_overlap_halfopen_adjacency_allowed_interior_rejected(api):
    """PRD 3.6: "A new timesheet's half-open week must not overlap the half-open week of any
    non-`REJECTED` timesheet on the same placement; because the weeks are half-open, two weeks that
    meet exactly at a shared boundary are adjacent rather than overlapping and are allowed, while any
    interior overlap is rejected with `ERR_TIMESHEET_WEEK_OVERLAP`."

    Existing [2026-06-15, 2026-06-22): an adjacent [2026-06-22, 2026-06-29) is accepted (201);
    an interior-overlapping [2026-06-20, 2026-06-27) is rejected (ERR_TIMESHEET_WEEK_OVERLAP).

    Design: Difficulty/resource_temporal_overlap/timesheet_week_overlap_halfopen_adjacency_ok
    """
    scen = setup_active_placement()
    pl, cand = scen["placement"], scen["candidate"]
    cand_headers = make_candidate_headers(cand["id"])
    create_timesheet(pl["id"], cand["id"], "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 40)
    adj = api.create_timesheet(
        {"placement_id": pl["id"], "week_start": "2026-06-22T00:00:00Z",
         "week_end": "2026-06-29T00:00:00Z", "hours": 40}, cand_headers)
    validate_success(adj, expected_status=201)
    interior = api.create_timesheet(
        {"placement_id": pl["id"], "week_start": "2026-06-20T00:00:00Z",
         "week_end": "2026-06-27T00:00:00Z", "hours": 40}, cand_headers)
    validate_error(interior, ApiErrorId.ERR_TIMESHEET_WEEK_OVERLAP)


def test_placement_disjoint_dates_for_same_candidate_allowed(api):
    """PRD 3.4: "the new placement's date range must not overlap any existing placement of the same
    candidate that is `ACTIVE` or `PENDING_START`; otherwise `ERR_PLACEMENT_DATE_OVERLAP`."
    PRD 3.4: "Note that a candidate already `ON_ASSIGNMENT` from a non-overlapping placement may
    still take a concurrent placement — only an `INACTIVE` candidate is barred."

    A candidate with an ACTIVE placement [2026-06-15, 2026-09-14] takes a second, strictly disjoint
    placement [2026-09-15, 2026-12-15] (no shared endpoint): the create succeeds (no overlap).

    Design: Difficulty/resource_temporal_overlap/candidate_placement_date_overlap_closed
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    cand = create_candidate(full_name="Busy Dev", skill_codes=["JAVA"])
    jo_a, jo_a_v = create_open_job_order(cl["id"], title="Dev A", openings=1)
    sub_a, _ = drive_submission_to_offer_extended(jo_a, cand, cl)
    pl_a = create_placement(sub_a["id"], jo_a_v, start_date="2026-06-15T00:00:00Z",
                            end_date="2026-09-14T00:00:00Z", standard_weekly_hours=40)
    start_placement(pl_a["id"])

    jo_b, jo_b_v = create_open_job_order(cl["id"], title="Dev B", openings=1)
    sub_b, _ = drive_submission_to_offer_extended(jo_b, cand, cl)
    resp = api.create_placement(
        {"submission_id": sub_b["id"], "start_date": "2026-09-15T00:00:00Z",
         "end_date": "2026-12-15T00:00:00Z", "expected_job_order_version": jo_b_v,
         "standard_weekly_hours": 40}, RECRUITER)
    data = validate_success(resp, expected_status=201)
    assert data["assignment_status"] == "PENDING_START", f"assignment {data['assignment_status']}"


def test_timesheet_week_overlap_against_rejected_timesheet_allowed(api):
    """PRD 3.6: "A new timesheet's half-open week must not overlap the half-open week of any
    non-`REJECTED` timesheet on the same placement."

    The overlap guard ignores REJECTED timesheets: after one timesheet [2026-06-15, 2026-06-22) is
    SUBMITTED then REJECTED, a new timesheet on the exact same week [2026-06-15, 2026-06-22) is
    accepted because the conflicting timesheet is REJECTED.

    Design: Difficulty/resource_temporal_overlap/timesheet_week_overlap_halfopen_adjacency_ok
    """
    scen = setup_active_placement()
    pl, cand, cl = scen["placement"], scen["candidate"], scen["client"]
    cand_headers = make_candidate_headers(cand["id"])
    ts = create_timesheet(pl["id"], cand["id"], "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 40)
    submit_timesheet(ts["id"], cand["id"])
    reject_timesheet(ts["id"], cl["id"])
    resp = api.create_timesheet(
        {"placement_id": pl["id"], "week_start": "2026-06-15T00:00:00Z",
         "week_end": "2026-06-22T00:00:00Z", "hours": 40}, cand_headers)
    validate_success(resp, expected_status=201)


# --- OCC corner --------------------------------------------------------------

def test_stale_job_order_version_rejected_on_second_placement(api):
    """PRD 2.8: "The server compares this value to the job order's current `version`. If they
    differ ... the create is rejected with `ERR_STALE_JOB_ORDER_VERSION` (HTTP 412)."
    PRD 3.4: "The order's `filled_count` is increased by one and its `version` is incremented by one."

    On a 2-opening order, placing candidate A bumps the order's version. A second placement for
    candidate B that carries the pre-bump expected_job_order_version is rejected with
    ERR_STALE_JOB_ORDER_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_placement_create
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    jo, jo_v = create_open_job_order(cl["id"], openings=2)
    cand_a = create_candidate(full_name="Cand A", skill_codes=["JAVA"])
    cand_b = create_candidate(full_name="Cand B", skill_codes=["JAVA"])
    sub_a, _ = drive_submission_to_offer_extended(jo, cand_a, cl)
    sub_b, _ = drive_submission_to_offer_extended(jo, cand_b, cl)
    # Place A with the observed version (bumps the order's version).
    create_placement(sub_a["id"], jo_v, start_date="2026-06-15T00:00:00Z",
                     end_date="2026-09-15T00:00:00Z", standard_weekly_hours=40)
    # B carries the now-stale version.
    resp = api.create_placement(
        {"submission_id": sub_b["id"], "start_date": "2026-06-15T00:00:00Z",
         "end_date": "2026-09-15T00:00:00Z", "expected_job_order_version": jo_v,
         "standard_weekly_hours": 40}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_STALE_JOB_ORDER_VERSION)


def make_candidate_headers_for(scen):
    return make_candidate_headers(scen["candidate"]["id"])
