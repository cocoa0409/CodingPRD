"""Pipeline scoring, recruiter selection, and site-visit scheduling conflicts."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_account_manager, create_recruiter, create_client_entity, create_opening,
    create_candidate_entity, create_application_entity, publish_opening,
    screen_application, submit_application,
    setup_open_opening, create_site_visit_payload, create_site_visit_entity,
    make_account_manager_headers, make_recruiter_headers,
)


# --------------------------------------------------------------------------
# match_score
# --------------------------------------------------------------------------
def test_match_score_full_match_scores_100(api):
    """PRD §3.3: "50 points when the candidate's specialty equals the opening's
    specialty, 30 points when the candidate's home_region equals the opening's
    region, and 20 points when the opening's region_state appears in the
    candidate's license_states. A perfectly aligned candidate therefore scores 100."

    Design: Corner/calculations/match_score_full_match_100
    """
    ctx = setup_open_opening(region="West", region_state="CA")
    cand = create_candidate_entity(
        ctx["rec_id"], specialty="CARDIOLOGY", home_region="West", license_states=["CA"]
    )
    app = create_application_entity(ctx["rec_id"], cand["id"], ctx["opening_id"])
    screened = screen_application(ctx["rec_id"], app["id"])
    assert screened["match_score"] == 100


# --------------------------------------------------------------------------
# recruiter selector
# --------------------------------------------------------------------------
def test_recruiter_selector_picks_lower_pipeline_load(api):
    """PRD §3.2: "each eligible recruiter is ranked by their open pipeline load ...
    in ascending order, so the least-loaded recruiter wins."

    Design: Corner/calculations/recruiter_selector_picks_lower_pipeline_load
    """
    am = create_account_manager()
    rec1 = create_recruiter(["CARDIOLOGY"], full_name="Rec One", email="rec1@x.com")
    rec2 = create_recruiter(["CARDIOLOGY"], full_name="Rec Two", email="rec2@x.com")
    client = create_client_entity(am["id"])
    # rec1 carries one non-terminal (SOURCED) application -> load 1.
    opening0 = create_opening(am["id"], client["id"])
    cand1 = create_candidate_entity(rec1["id"], full_name="Dr Load")
    create_application_entity(rec1["id"], cand1["id"], opening0["id"])
    # New opening; rec2 has load 0 and must be chosen.
    opening1 = create_opening(am["id"], client["id"])
    published = publish_opening(am["id"], opening1["id"])
    assert published["recruiter_id"] == rec2["id"]
    assert published["status"] == "OPEN"


def test_publish_with_empty_recruiter_pool_rejected(api):
    """PRD §3.2: "If that pool is empty, publishing is rejected with
    ERR_NO_ELIGIBLE_RECRUITER and no assignment is made."

    Design: Difficulty/boundary_precision_check/recruiter_selector_empty_pool_blocks_publish
    """
    am = create_account_manager()
    create_recruiter(["CARDIOLOGY"])  # covers CARDIOLOGY only
    client = create_client_entity(am["id"])
    opening = create_opening(am["id"], client["id"], specialty="PSYCHIATRY")
    resp = api.transition_job_opening(
        opening["id"], "PUBLISH", make_account_manager_headers(am["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_RECRUITER.value)


def test_publish_empty_pool_leaves_opening_draft(api):
    """PRD §3.2: "If that pool is empty, publishing is rejected with
    ERR_NO_ELIGIBLE_RECRUITER and no assignment is made."
    PRD §3.2: "A freshly created opening has positions_filled at 0, a null
    recruiter_id, and status DRAFT."

    Design: Difficulty/boundary_precision_check/recruiter_selector_empty_pool_blocks_publish
    """
    am = create_account_manager()
    create_recruiter(["CARDIOLOGY"])
    client = create_client_entity(am["id"])
    opening = create_opening(am["id"], client["id"], specialty="PSYCHIATRY")
    api.transition_job_opening(
        opening["id"], "PUBLISH", make_account_manager_headers(am["id"])
    )
    got = validate_success(
        api.get_job_opening(opening["id"], make_account_manager_headers(am["id"]))
    )
    assert got["status"] == "DRAFT"
    assert got["recruiter_id"] is None


# --------------------------------------------------------------------------
# submit gated by opening OPEN (cross-entity state dependency)
# --------------------------------------------------------------------------
def test_submit_while_opening_on_hold_rejected(api):
    """PRD §3.3: "the referenced opening's status must be OPEN, otherwise the
    request is rejected with ERR_OPENING_NOT_OPEN."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_opening_open
    """
    ctx = setup_open_opening()
    cand = create_candidate_entity(ctx["rec_id"])
    app = create_application_entity(ctx["rec_id"], cand["id"], ctx["opening_id"])
    screen_application(ctx["rec_id"], app["id"])
    validate_success(
        api.transition_job_opening(
            ctx["opening_id"], "HOLD", make_account_manager_headers(ctx["am_id"])
        )
    )
    resp = api.advance_application(app["id"], "SUBMIT", make_recruiter_headers(ctx["rec_id"]))
    validate_error(resp, ApiErrorId.ERR_OPENING_NOT_OPEN.value)


def test_submit_rejected_leaves_application_screened(api):
    """PRD §3.3: "A recruiter then submits a screened application to the client
    (SCREENED → SUBMITTED). Submission has two preconditions: the referenced
    opening's status must be OPEN, otherwise the request is rejected with
    ERR_OPENING_NOT_OPEN."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_opening_open
    """
    ctx = setup_open_opening()
    cand = create_candidate_entity(ctx["rec_id"])
    app = create_application_entity(ctx["rec_id"], cand["id"], ctx["opening_id"])
    screen_application(ctx["rec_id"], app["id"])
    api.transition_job_opening(
        ctx["opening_id"], "HOLD", make_account_manager_headers(ctx["am_id"])
    )
    api.advance_application(app["id"], "SUBMIT", make_recruiter_headers(ctx["rec_id"]))
    got = validate_success(
        api.get_application(app["id"], make_recruiter_headers(ctx["rec_id"]))
    )
    assert got["stage"] == "SCREENED"


# --------------------------------------------------------------------------
# site-visit scheduling: interviewer half-open + candidate buffer
# --------------------------------------------------------------------------
def _two_candidate_opening():
    """OPEN opening (2 positions) + two SOURCED applications on distinct candidates."""
    ctx = setup_open_opening(positions_total=2)
    cand_a = create_candidate_entity(ctx["rec_id"], full_name="Dr A")
    app_a = create_application_entity(ctx["rec_id"], cand_a["id"], ctx["opening_id"])
    cand_b = create_candidate_entity(ctx["rec_id"], full_name="Dr B")
    app_b = create_application_entity(ctx["rec_id"], cand_b["id"], ctx["opening_id"])
    return ctx, app_a, app_b


def test_interviewer_double_booking_overlap_rejected(api):
    """PRD §3.4: "the request is rejected with ERR_INTERVIEWER_DOUBLE_BOOKED if
    there exists any other SCHEDULED visit on the same interviewer_user_id whose
    window overlaps it — that is, the new start falls before the existing end and
    the existing start falls before the new end."

    Design: Difficulty/resource_temporal_overlap/interviewer_double_booking_half_open
    """
    ctx, app_a, app_b = _two_candidate_opening()
    create_site_visit_entity(
        ctx["rec_id"], app_a["id"], ctx["rec_id"],
        scheduled_start="2026-05-03T15:00:00Z", scheduled_end="2026-05-03T16:00:00Z",
    )
    resp = api.create_site_visit(
        create_site_visit_payload(
            app_b["id"], ctx["rec_id"],
            scheduled_start="2026-05-03T15:30:00Z", scheduled_end="2026-05-03T16:30:00Z",
        ),
        make_recruiter_headers(ctx["rec_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED.value)


def test_interviewer_identical_window_rejected(api):
    """PRD §3.4: "the request is rejected with ERR_INTERVIEWER_DOUBLE_BOOKED if
    there exists any other SCHEDULED visit on the same interviewer_user_id whose
    window overlaps it — that is, the new start falls before the existing end and
    the existing start falls before the new end."

    Design: Difficulty/resource_temporal_overlap/interviewer_double_booking_half_open
    """
    ctx, app_a, app_b = _two_candidate_opening()
    create_site_visit_entity(
        ctx["rec_id"], app_a["id"], ctx["rec_id"],
        scheduled_start="2026-05-03T15:00:00Z", scheduled_end="2026-05-03T16:00:00Z",
    )
    resp = api.create_site_visit(
        create_site_visit_payload(
            app_b["id"], ctx["rec_id"],
            scheduled_start="2026-05-03T15:00:00Z", scheduled_end="2026-05-03T16:00:00Z",
        ),
        make_recruiter_headers(ctx["rec_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED.value)


def test_interviewer_adjacent_booking_allowed(api):
    """PRD §3.4: "When the new visit begins exactly when another ends, or ends
    exactly when another begins, there is no conflict."

    Design: Corner/state_machines/interviewer_adjacency_allowed
    """
    ctx, app_a, app_b = _two_candidate_opening()
    create_site_visit_entity(
        ctx["rec_id"], app_a["id"], ctx["rec_id"],
        scheduled_start="2026-05-03T15:00:00Z", scheduled_end="2026-05-03T16:00:00Z",
    )
    resp = api.create_site_visit(
        create_site_visit_payload(
            app_b["id"], ctx["rec_id"],
            scheduled_start="2026-05-03T16:00:00Z", scheduled_end="2026-05-03T17:00:00Z",
        ),
        make_recruiter_headers(ctx["rec_id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_candidate_travel_conflict_under_buffer_rejected(api):
    """PRD §3.4: "Each such existing visit's window is expanded by a candidate
    travel buffer of 120 minutes on both sides; if that expanded window intersects
    the new visit's window, the request is rejected with ERR_CANDIDATE_TRAVEL_CONFLICT.
    Equivalently, a gap of less than 120 minutes between the two visits is rejected,
    while a gap of exactly 120 minutes is allowed."

    Design: Difficulty/resource_temporal_overlap/candidate_travel_buffer_closed
    """
    ctx = setup_open_opening()
    intv2 = create_recruiter(["CARDIOLOGY"], full_name="Ivy Two", email="intv2@x.com")
    cand = create_candidate_entity(ctx["rec_id"])
    app = create_application_entity(ctx["rec_id"], cand["id"], ctx["opening_id"])
    create_site_visit_entity(
        ctx["rec_id"], app["id"], ctx["rec_id"],
        scheduled_start="2026-05-03T15:00:00Z", scheduled_end="2026-05-03T16:00:00Z",
    )
    # Same candidate, different interviewer, only 30 minutes later -> conflict.
    resp = api.create_site_visit(
        create_site_visit_payload(
            app["id"], intv2["id"],
            scheduled_start="2026-05-03T16:30:00Z", scheduled_end="2026-05-03T17:30:00Z",
            location="Clinic",
        ),
        make_recruiter_headers(ctx["rec_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_TRAVEL_CONFLICT.value)


def test_candidate_travel_exact_buffer_allowed(api):
    """PRD §3.4: "a gap of less than 120 minutes between the two visits is rejected,
    while a gap of exactly 120 minutes is allowed."

    Design: Difficulty/resource_temporal_overlap/candidate_travel_buffer_closed
    """
    ctx = setup_open_opening()
    intv2 = create_recruiter(["CARDIOLOGY"], full_name="Ivy Two", email="intv2@x.com")
    cand = create_candidate_entity(ctx["rec_id"])
    app = create_application_entity(ctx["rec_id"], cand["id"], ctx["opening_id"])
    create_site_visit_entity(
        ctx["rec_id"], app["id"], ctx["rec_id"],
        scheduled_start="2026-05-03T15:00:00Z", scheduled_end="2026-05-03T16:00:00Z",
    )
    # Gap from 16:00 to 18:00 is exactly 120 minutes -> allowed.
    resp = api.create_site_visit(
        create_site_visit_payload(
            app["id"], intv2["id"],
            scheduled_start="2026-05-03T18:00:00Z", scheduled_end="2026-05-03T19:00:00Z",
            location="Clinic",
        ),
        make_recruiter_headers(ctx["rec_id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
