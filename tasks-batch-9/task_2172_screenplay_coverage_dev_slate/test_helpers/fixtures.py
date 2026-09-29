"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: the harness restarts the server before each test, so each
test starts against an empty database.

Setup calls use the lenient ``get_success_data`` validator so a broken
precondition surfaces as a clear setup failure rather than a confusing
assertion further down.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import TEST_DEFAULTS
from .test_users import (
    ADMIN,
    BA_APPROVER,
    BA_PAYER,
    EDITOR_APPROVE,
    EDITOR_ASSIGN,
    EXEC_ALPHA,
    SUBMITTER,
    make_committee_member_headers,
    make_reader_headers,
    make_writer_headers,
)

DEFAULT_CLOCK = TEST_DEFAULTS["CLOCK"]


# ==========================================================================
# Tier 0 — primitives
# ==========================================================================


def set_clock(to_iso8601: str = DEFAULT_CLOCK) -> dict:
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def read_clock() -> dict:
    return get_success_data(api.get_clock(ADMIN))


def create_property(
    genre: str = "DRAMA",
    title: str = "Test Property",
    material_type: str = "SPEC_SCRIPT",
    source_author_name: str = "A. Author",
    logline: str = "A test logline.",
) -> dict:
    payload = {
        "title": title,
        "material_type": material_type,
        "source_author_name": source_author_name,
        "genre": genre,
        "logline": logline,
    }
    return get_success_data(api.create_literary_property(payload, EDITOR_ASSIGN))


def file_document(
    property_id: str,
    doc_type: str,
    executed_on: str = "2026-01-15",
    verified: bool = True,
    **extra,
) -> dict:
    payload = {"doc_type": doc_type, "executed_on": executed_on, "verified": verified}
    payload.update(extra)
    return get_success_data(api.file_rights_document(property_id, payload, BA_APPROVER))


def fetch_property(property_id: str) -> dict:
    return get_success_data(api.get_literary_property(property_id, BA_APPROVER))


def property_version(property_id: str) -> int:
    return fetch_property(property_id)["version"]


def make_clear_property(
    genre: str = "DRAMA", title: str = "Clear Property", **kwargs
) -> dict:
    """Three verified documents including CHAIN_OF_TITLE and COPYRIGHT_CERT."""
    prop = create_property(genre=genre, title=title, **kwargs)
    file_document(prop["id"], "CHAIN_OF_TITLE", "2026-01-15", True)
    file_document(prop["id"], "COPYRIGHT_CERT", "2026-01-16", True)
    file_document(prop["id"], "WGA_REGISTRATION", "2026-01-17", True)
    return prop


def make_partial_property(
    genre: str = "DRAMA", title: str = "Partial Property", **kwargs
) -> dict:
    """Two verified documents — enough for PARTIAL, short of CLEAR."""
    prop = create_property(genre=genre, title=title, **kwargs)
    file_document(prop["id"], "CHAIN_OF_TITLE", "2026-01-15", True)
    file_document(prop["id"], "COPYRIGHT_CERT", "2026-01-16", True)
    return prop


def make_disputed_property(
    genre: str = "THRILLER", title: str = "Disputed Property", **kwargs
) -> dict:
    """A verified chain plus an unverified PRIOR_ASSIGNMENT, so DISPUTED."""
    prop = create_property(genre=genre, title=title, **kwargs)
    file_document(prop["id"], "CHAIN_OF_TITLE", "2026-01-15", True)
    file_document(
        prop["id"],
        "PRIOR_ASSIGNMENT",
        "2023-11-02",
        False,
        notes="Producer claim never released.",
    )
    return prop


# ---- Readers ---------------------------------------------------------------


def create_reader(
    display_name: str = "R1 Solberg",
    specialty_genre: str = "DRAMA",
    weekly_capacity: int = 3,
    employment_type: str = "STAFF",
    **extra,
) -> dict:
    payload = {
        "display_name": display_name,
        "specialty_genre": specialty_genre,
        "weekly_capacity": weekly_capacity,
        "employment_type": employment_type,
    }
    payload.update(extra)
    return get_success_data(api.create_reader(payload, ADMIN))


def fetch_reader(reader_id: str) -> dict:
    return get_success_data(api.get_reader(reader_id, ADMIN))


# ---- Submissions and release forms ----------------------------------------


def create_submission(
    property_id: str,
    submitting_agency: str = "CAA",
    submitter_contact_email: str = "desk@caa.example",
    submitted_via: str = "AGENCY",
    **extra,
) -> dict:
    payload = {
        "property_id": property_id,
        "submitting_agency": submitting_agency,
        "submitter_contact_email": submitter_contact_email,
        "submitted_via": submitted_via,
    }
    payload.update(extra)
    return get_success_data(api.create_submission(payload, SUBMITTER))


def create_unsolicited_submission(
    property_id: str,
    submitting_agency: str = "Self-submitted",
    submitter_contact_email: str = "writer@mail.example",
) -> dict:
    return create_submission(
        property_id,
        submitting_agency=submitting_agency,
        submitter_contact_email=submitter_contact_email,
        submitted_via="UNSOLICITED",
    )


def fetch_submission(submission_id: str) -> dict:
    return get_success_data(api.get_submission(submission_id, EDITOR_ASSIGN))


def clear_intake(submission_id: str, headers=EDITOR_ASSIGN) -> dict:
    return get_success_data(api.clear_intake(submission_id, headers))


def open_release_form(
    submission_id: str, expires_at: str = "2026-10-01T00:00:00Z", headers=EDITOR_ASSIGN
) -> dict:
    return get_success_data(
        api.create_release_form(submission_id, {"expires_at": expires_at}, headers)
    )


def send_release_form(release_form_id: str, headers=EDITOR_ASSIGN) -> dict:
    return get_success_data(api.send_release_form(release_form_id, headers))


def execute_release_form(release_form_id: str, signer_name: str = "The Signer") -> dict:
    return get_success_data(
        api.execute_release_form(release_form_id, {"signer_name": signer_name}, SUBMITTER)
    )


def waive_release_form(
    release_form_id: str, waiver_reason: str = "Legal waived it.", headers=EDITOR_ASSIGN
) -> dict:
    return get_success_data(
        api.waive_release_form(
            release_form_id, {"waiver_reason": waiver_reason}, headers
        )
    )


def fetch_release_form(release_form_id: str) -> dict:
    return get_success_data(api.get_release_form(release_form_id, EDITOR_ASSIGN))


# ---- Assignments and reports ----------------------------------------------


def assign_reader(
    submission_id: str,
    reader_id=None,
    window_start: str = "2026-09-01T00:00:00Z",
    window_due: str = "2026-09-04T00:00:00Z",
    headers=EDITOR_ASSIGN,
    **extra,
) -> dict:
    payload = {"window_start": window_start, "window_due": window_due}
    if reader_id is not None:
        payload["reader_id"] = reader_id
    payload.update(extra)
    return get_success_data(api.assign_reader(submission_id, payload, headers))


def fetch_assignment(assignment_id: str) -> dict:
    return get_success_data(api.get_coverage_assignment(assignment_id, EDITOR_ASSIGN))


def report_for_assignment(assignment_id: str) -> dict:
    body = get_success_data(
        api.list_coverage_reports(EDITOR_ASSIGN, {"assignment_id": assignment_id})
    )
    assert body, f"Setup failed: no coverage report for assignment {assignment_id}"
    return body[0]


def fetch_report(report_id: str) -> dict:
    return get_success_data(api.get_coverage_report(report_id, EDITOR_ASSIGN))


def fill_report(
    report_id: str,
    reader_id: str,
    logline_score: int = 8,
    structure_score: int = 7,
    character_score: int = 9,
    dialogue_score: int = 6,
    marketability_score: int = 8,
    recommendation: str = "RECOMMEND",
    synopsis_word_count: int = 400,
    **extra,
) -> dict:
    payload = {
        "logline_score": logline_score,
        "structure_score": structure_score,
        "character_score": character_score,
        "dialogue_score": dialogue_score,
        "marketability_score": marketability_score,
        "recommendation": recommendation,
        "synopsis_word_count": synopsis_word_count,
    }
    payload.update(extra)
    return get_success_data(
        api.patch_coverage_report(report_id, payload, make_reader_headers(reader_id))
    )


def submit_report(report_id: str, reader_id: str) -> dict:
    return get_success_data(
        api.submit_coverage_report(report_id, make_reader_headers(reader_id))
    )


def request_revision(
    report_id: str, revision_note: str = "Please revise.", headers=EDITOR_APPROVE
) -> dict:
    return get_success_data(
        api.request_report_revision(report_id, {"revision_note": revision_note}, headers)
    )


def approve_report(report_id: str, headers=EDITOR_APPROVE) -> dict:
    return get_success_data(api.approve_coverage_report(report_id, headers))


def reject_report(
    report_id: str, reason: str = "Analysis never improved.", headers=EDITOR_APPROVE
) -> dict:
    return get_success_data(
        api.reject_coverage_report(report_id, {"reason": reason}, headers)
    )


def recall_assignment(
    assignment_id: str, reason: str = "Reader conflict.", headers=EDITOR_ASSIGN
) -> dict:
    return get_success_data(
        api.recall_coverage_assignment(assignment_id, {"reason": reason}, headers)
    )


# ==========================================================================
# Tier 1 — coverage-pipeline composites
# ==========================================================================


def setup_cleared_submission(
    genre: str = "DRAMA",
    title: str = "Cleared Property",
    property_id=None,
    submitting_agency: str = "CAA",
    submitter_contact_email: str = "desk@caa.example",
    **submission_extra,
) -> dict:
    """A property plus an AGENCY submission that has been cleared to INTAKE_CLEARED."""
    if property_id is None:
        prop = create_property(genre=genre, title=title)
        property_id = prop["id"]
    else:
        prop = fetch_property(property_id)
    submission = create_submission(
        property_id,
        submitting_agency=submitting_agency,
        submitter_contact_email=submitter_contact_email,
        **submission_extra,
    )
    clear_intake(submission["id"])
    return {"property": prop, "submission": submission}


def setup_assigned_coverage(
    genre: str = "DRAMA",
    title: str = "Assigned Property",
    reader=None,
    reader_capacity: int = 2,
    window_start: str = "2026-09-01T00:00:00Z",
    window_due: str = "2026-09-04T00:00:00Z",
    property_id=None,
    submitting_agency: str = "CAA",
    submitter_contact_email: str = "desk@caa.example",
) -> dict:
    """Property + reader + cleared submission + assignment + its DRAFT report."""
    if reader is None:
        reader = create_reader(
            display_name="R1 Solberg",
            specialty_genre=genre,
            weekly_capacity=reader_capacity,
            employment_type="STAFF",
        )
    base = setup_cleared_submission(
        genre=genre,
        title=title,
        property_id=property_id,
        submitting_agency=submitting_agency,
        submitter_contact_email=submitter_contact_email,
    )
    assignment = assign_reader(
        base["submission"]["id"],
        reader_id=reader["id"],
        window_start=window_start,
        window_due=window_due,
    )
    report = report_for_assignment(assignment["id"])
    return {
        "property": base["property"],
        "submission": base["submission"],
        "reader": reader,
        "assignment": assignment,
        "report": report,
    }


def setup_submitted_coverage(
    genre: str = "DRAMA",
    title: str = "Submitted Coverage",
    scores=(8, 7, 9, 6, 8),
    recommendation: str = "RECOMMEND",
    synopsis_word_count: int = 400,
    revision_rounds: int = 0,
    revision_scores=None,
    **kwargs,
) -> dict:
    """Walk an assignment through to a SUBMITTED report, optionally via revisions."""
    ctx = setup_assigned_coverage(genre=genre, title=title, **kwargs)
    fill_report(
        ctx["report"]["id"],
        ctx["reader"]["id"],
        logline_score=scores[0],
        structure_score=scores[1],
        character_score=scores[2],
        dialogue_score=scores[3],
        marketability_score=scores[4],
        recommendation=recommendation,
        synopsis_word_count=synopsis_word_count,
    )
    submit_report(ctx["report"]["id"], ctx["reader"]["id"])
    for round_index in range(revision_rounds):
        request_revision(
            ctx["report"]["id"], revision_note=f"Round {round_index + 1} notes."
        )
        if revision_scores is not None:
            fill_report(
                ctx["report"]["id"],
                ctx["reader"]["id"],
                logline_score=revision_scores[0],
                structure_score=revision_scores[1],
                character_score=revision_scores[2],
                dialogue_score=revision_scores[3],
                marketability_score=revision_scores[4],
                recommendation=recommendation,
                synopsis_word_count=synopsis_word_count,
            )
        submit_report(ctx["report"]["id"], ctx["reader"]["id"])
    return ctx


def setup_approved_coverage(**kwargs) -> dict:
    """A submitted report that has then been approved by a second story editor."""
    ctx = setup_submitted_coverage(**kwargs)
    approve_report(ctx["report"]["id"])
    return ctx


def board_entries_for_property(property_id: str, **extra_params):
    params = {"property_id": property_id}
    params.update(extra_params)
    return get_success_data(api.list_tracking_board_entries(EDITOR_ASSIGN, params))


# ==========================================================================
# Tier 2 — options, projects
# ==========================================================================


def create_option(
    property_id: str,
    expected_property_version=None,
    option_fee_cents: int = TEST_DEFAULTS["OPTION_FEE_CENTS"],
    purchase_price_cents: int = TEST_DEFAULTS["PURCHASE_PRICE_CENTS"],
    initial_period_months: int = TEST_DEFAULTS["INITIAL_PERIOD_MONTHS"],
    option_start_at: str = TEST_DEFAULTS["OPTION_START_AT"],
    **extra,
) -> dict:
    if expected_property_version is None:
        expected_property_version = property_version(property_id)
    payload = {
        "property_id": property_id,
        "expected_property_version": expected_property_version,
        "option_fee_cents": option_fee_cents,
        "purchase_price_cents": purchase_price_cents,
        "initial_period_months": initial_period_months,
        "option_start_at": option_start_at,
    }
    payload.update(extra)
    return get_success_data(api.create_option_agreement(payload, BA_APPROVER))


def execute_option(option_id: str) -> dict:
    return get_success_data(api.execute_option(option_id, BA_APPROVER))


def extend_option(option_id: str) -> dict:
    return get_success_data(api.extend_option(option_id, BA_APPROVER))


def exercise_option(option_id: str) -> dict:
    return get_success_data(api.exercise_option(option_id, BA_APPROVER))


def lapse_option(option_id: str) -> dict:
    return get_success_data(api.lapse_option(option_id, BA_APPROVER))


def fetch_option(option_id: str) -> dict:
    return get_success_data(api.get_option_agreement(option_id, BA_APPROVER))


def create_project(
    property_id: str,
    option_agreement_id: str,
    budget_cents: int = TEST_DEFAULTS["BUDGET_CENTS"],
    slate_year: int = TEST_DEFAULTS["SLATE_YEAR"],
    exec_headers=EXEC_ALPHA,
) -> dict:
    payload = {
        "property_id": property_id,
        "option_agreement_id": option_agreement_id,
        "budget_cents": budget_cents,
        "slate_year": slate_year,
    }
    return get_success_data(api.create_development_project(payload, exec_headers))


def fetch_project(project_id: str) -> dict:
    return get_success_data(api.get_development_project(project_id, EXEC_ALPHA))


def project_version(project_id: str) -> int:
    return fetch_project(project_id)["version"]


def place_in_turnaround(
    project_id: str, reason: str = "Slate re-prioritised.", exec_headers=EXEC_ALPHA
) -> dict:
    return get_success_data(
        api.place_in_turnaround(project_id, {"reason": reason}, exec_headers)
    )


def setup_clear_property_with_active_option(
    genre: str = "DRAMA",
    title: str = "Optioned Property",
    option_overrides=None,
) -> dict:
    prop = make_clear_property(genre=genre, title=title)
    option = create_option(prop["id"], **(option_overrides or {}))
    execute_option(option["id"])
    return {"property": prop, "option": option}


# ==========================================================================
# Tier 3 — writers, engagements, milestones
# ==========================================================================


def create_writer(
    name: str = "W1 Ferrante",
    guild_member: bool = True,
    quote_cents: int = 10_000_000,
    **extra,
) -> dict:
    payload = {"name": name, "guild_member": guild_member, "quote_cents": quote_cents}
    payload.update(extra)
    return get_success_data(api.create_writer(payload, ADMIN))


def fetch_writer(writer_id: str) -> dict:
    return get_success_data(api.get_writer(writer_id, ADMIN))


def create_engagement(
    project_id: str,
    writer_id: str,
    engagement_type: str = "ORIGINAL_DRAFT",
    total_fee_cents: int = TEST_DEFAULTS["ORIGINAL_DRAFT_FEE_CENTS"],
    start_date: str = TEST_DEFAULTS["ENGAGEMENT_START_DATE"],
    end_date: str = TEST_DEFAULTS["ENGAGEMENT_END_DATE"],
    expected_project_version=None,
    exec_headers=EXEC_ALPHA,
) -> dict:
    if expected_project_version is None:
        expected_project_version = project_version(project_id)
    payload = {
        "project_id": project_id,
        "writer_id": writer_id,
        "engagement_type": engagement_type,
        "total_fee_cents": total_fee_cents,
        "start_date": start_date,
        "end_date": end_date,
        "expected_project_version": expected_project_version,
    }
    return get_success_data(api.create_writer_engagement(payload, exec_headers))


def attach_engagement(engagement_id: str, exec_headers=EXEC_ALPHA) -> dict:
    return get_success_data(api.attach_engagement(engagement_id, exec_headers))


def fetch_engagement(engagement_id: str) -> dict:
    return get_success_data(api.get_writer_engagement(engagement_id, EXEC_ALPHA))


def terminate_engagement(
    engagement_id: str, reason: str = "Creative differences.", exec_headers=EXEC_ALPHA
) -> dict:
    return get_success_data(
        api.terminate_engagement(engagement_id, {"reason": reason}, exec_headers)
    )


def deliver(engagement_id: str, milestone_type: str, writer_id: str) -> dict:
    return get_success_data(
        api.deliver_engagement(
            engagement_id,
            {"milestone_type": milestone_type},
            make_writer_headers(writer_id),
        )
    )


def milestones_for_engagement(engagement_id: str):
    return get_success_data(
        api.list_milestone_payments(BA_APPROVER, {"engagement_id": engagement_id})
    )


def milestone_of_type(engagement_id: str, milestone_type: str) -> dict:
    rows = get_success_data(
        api.list_milestone_payments(
            BA_APPROVER,
            {"engagement_id": engagement_id, "milestone_type": milestone_type},
        )
    )
    assert rows, (
        f"Setup failed: no {milestone_type} milestone on engagement {engagement_id}"
    )
    return rows[0]


def fetch_milestone(milestone_id: str) -> dict:
    return get_success_data(api.get_milestone_payment(milestone_id, BA_APPROVER))


def approve_milestone(milestone_id: str, headers=BA_APPROVER) -> dict:
    return get_success_data(api.approve_milestone_payment(milestone_id, headers))


def pay_milestone(milestone_id: str, headers=BA_PAYER) -> dict:
    return get_success_data(api.pay_milestone_payment(milestone_id, headers))


def setup_development_pipeline(
    genre: str = "DRAMA",
    title: str = "Pipeline Property",
    budget_cents: int = TEST_DEFAULTS["BUDGET_CENTS"],
    slate_year: int = TEST_DEFAULTS["SLATE_YEAR"],
    option_overrides=None,
    exercise: bool = False,
    with_writer: bool = True,
    writer_name: str = "W1 Ferrante",
    guild_member: bool = True,
    engagement_type: str = "ORIGINAL_DRAFT",
    total_fee_cents: int = TEST_DEFAULTS["ORIGINAL_DRAFT_FEE_CENTS"],
    start_date: str = TEST_DEFAULTS["ENGAGEMENT_START_DATE"],
    end_date: str = TEST_DEFAULTS["ENGAGEMENT_END_DATE"],
    attach: bool = True,
    pay_commencement: bool = False,
    deliver_first_draft: bool = False,
    exec_headers=EXEC_ALPHA,
) -> dict:
    """CLEAR property -> ACTIVE option -> project -> (optional) writer engagement.

    ``exercise`` exercises the option after the project exists, flipping the
    project's rights axis to OWNED. ``pay_commencement`` walks the
    sequence_index 0 milestone through approve and pay (which also takes the
    engagement ATTACHED -> ACTIVE). ``deliver_first_draft`` records the
    FIRST_DRAFT_DELIVERY, taking the development axis to DRAFT_DELIVERED.
    """
    base = setup_clear_property_with_active_option(
        genre=genre, title=title, option_overrides=option_overrides
    )
    project = create_project(
        base["property"]["id"],
        base["option"]["id"],
        budget_cents=budget_cents,
        slate_year=slate_year,
        exec_headers=exec_headers,
    )
    if exercise:
        exercise_option(base["option"]["id"])

    ctx = {
        "property": base["property"],
        "option": base["option"],
        "project": project,
        "writer": None,
        "engagement": None,
    }
    if not with_writer:
        return ctx

    writer = create_writer(name=writer_name, guild_member=guild_member)
    engagement = create_engagement(
        project["id"],
        writer["id"],
        engagement_type=engagement_type,
        total_fee_cents=total_fee_cents,
        start_date=start_date,
        end_date=end_date,
        exec_headers=exec_headers,
    )
    ctx["writer"] = writer
    ctx["engagement"] = engagement
    if not attach:
        return ctx

    attach_engagement(engagement["id"], exec_headers=exec_headers)
    if pay_commencement:
        commencement = milestone_of_type(engagement["id"], "COMMENCEMENT")
        approve_milestone(commencement["id"])
        pay_milestone(commencement["id"])
        ctx["commencement"] = commencement
    if deliver_first_draft:
        deliver(engagement["id"], "FIRST_DRAFT_DELIVERY", writer["id"])
    return ctx


def setup_owned_draft_delivered_project(
    genre: str = "DRAMA",
    title: str = "Greenlight Candidate",
    pay_commencement: bool = True,
    exercise: bool = True,
    **kwargs,
) -> dict:
    """A project at rights_status OWNED and development_status DRAFT_DELIVERED."""
    return setup_development_pipeline(
        genre=genre,
        title=title,
        exercise=exercise,
        attach=True,
        pay_commencement=pay_commencement,
        deliver_first_draft=True,
        **kwargs,
    )


# ==========================================================================
# Tier 4 — greenlight committee
# ==========================================================================


DEFAULT_COMMITTEE = (
    {"display_name": "M1 Chair", "vote_weight_bps": 3000, "veto_power": False},
    {"display_name": "M2 Marketing", "vote_weight_bps": 3000, "veto_power": False},
    {"display_name": "M3 Finance", "vote_weight_bps": 3000, "veto_power": False},
    {"display_name": "M4 Physical Production", "vote_weight_bps": 1000,
     "veto_power": False},
)


def seat_member(display_name: str, vote_weight_bps: int, **extra) -> dict:
    payload = {"display_name": display_name, "vote_weight_bps": vote_weight_bps}
    payload.update(extra)
    return get_success_data(api.create_committee_member(payload, ADMIN))


def seat_committee(specs=DEFAULT_COMMITTEE):
    return [seat_member(**dict(spec)) for spec in specs]


def fetch_member(member_id: str) -> dict:
    return get_success_data(api.get_committee_member(member_id, ADMIN))


def patch_member(member_id: str, **payload) -> dict:
    return get_success_data(api.patch_committee_member(member_id, payload, ADMIN))


def convene_review(
    project_id: str,
    session_date: str = "2026-10-01",
    expected_project_version=None,
) -> dict:
    if expected_project_version is None:
        expected_project_version = project_version(project_id)
    payload = {
        "project_id": project_id,
        "session_date": session_date,
        "expected_project_version": expected_project_version,
    }
    return get_success_data(api.create_greenlight_review(payload, ADMIN))


def open_voting(review_id: str) -> dict:
    return get_success_data(api.open_voting(review_id, ADMIN))


def cast_vote(review_id: str, member_id: str, vote_value: str, comment=None) -> dict:
    payload = {"vote_value": vote_value}
    if comment is not None:
        payload["comment"] = comment
    return get_success_data(
        api.cast_vote(review_id, payload, make_committee_member_headers(member_id))
    )


def close_review(review_id: str, decision_note=None) -> dict:
    payload = {} if decision_note is None else {"decision_note": decision_note}
    return get_success_data(api.close_review(review_id, payload, ADMIN))


def fetch_review(review_id: str) -> dict:
    return get_success_data(api.get_greenlight_review(review_id, ADMIN))


def setup_review_in_voting(
    committee_specs=DEFAULT_COMMITTEE,
    ballots=(),
    genre: str = "DRAMA",
    title: str = "Committee Property",
    pay_commencement: bool = True,
    session_date: str = "2026-10-01",
    **pipeline_kwargs,
) -> dict:
    """OWNED + DRAFT_DELIVERED project, a seated committee, and a VOTING review.

    ``ballots`` is a sequence of (member_index, vote_value) pairs cast in
    order after voting opens.
    """
    ctx = setup_owned_draft_delivered_project(
        genre=genre, title=title, pay_commencement=pay_commencement, **pipeline_kwargs
    )
    members = seat_committee(committee_specs)
    review = convene_review(ctx["project"]["id"], session_date=session_date)
    open_voting(review["id"])
    for member_index, vote_value in ballots:
        cast_vote(review["id"], members[member_index]["id"], vote_value)
    ctx["members"] = members
    ctx["review"] = review
    return ctx
