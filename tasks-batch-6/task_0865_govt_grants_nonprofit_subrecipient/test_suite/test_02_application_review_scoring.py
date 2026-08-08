"""Application submission, the revision loop, panel review, and automatic scoring."""
from test_helpers import (
    validate_success,
    validate_error,
    create_application_payload,
    create_review_payload,
    create_nonprofit,
    create_nofo,
    create_draft_application,
    create_scored_application,
    make_program_officer_headers,
    make_panelist_headers,
    make_subrecipient_headers,
)


def _application_under_review(api, scores_done=()):
    """Build an application in UNDER_REVIEW, optionally with some reviews already stored."""
    np = create_nonprofit()
    nofo = create_nofo()
    app = create_draft_application(nofo["id"], np["id"])
    sub_headers = make_subrecipient_headers(np["id"])
    validate_success(api.submit_application(app["id"], sub_headers), 200)
    validate_success(api.start_review(app["id"], make_program_officer_headers()), 200)
    for i, score in enumerate(scores_done):
        validate_success(
            api.create_review(app["id"], create_review_payload(score),
                              make_panelist_headers(f"pan-{i + 1}")),
            201,
        )
    return np, nofo, app


def test_revision_request_moves_application_to_revision_requested(api):
    """PRD §3.2: "A ProgramOfficer then starts review, moving the application from SUBMITTED
    to UNDER_REVIEW, and may send it back with an optional revision_note, transitioning it from
    UNDER_REVIEW to REVISION_REQUESTED."

    Design: Difficulty/non_linear_state_machine/application_revision_request_resubmit_cycle
    """
    np, nofo, app = _application_under_review(api)
    res = api.request_revision(app["id"], {"revision_note": "add budget detail"},
                               make_program_officer_headers())
    updated = validate_success(res, 200)
    assert updated["status"] == "REVISION_REQUESTED"


def test_resubmit_after_revision_returns_to_submitted(api):
    """PRD §3.2: "From REVISION_REQUESTED the owning Subrecipient resubmits, returning it to
    SUBMITTED; this resubmission of an already-existing application does not re-check
    intake_status, so a revision loop may complete even after intake has closed."

    Design: Difficulty/non_linear_state_machine/application_revision_request_resubmit_cycle
    """
    np, nofo, app = _application_under_review(api)
    validate_success(
        api.request_revision(app["id"], {"revision_note": "add budget detail"},
                             make_program_officer_headers()),
        200,
    )
    res = api.submit_application(app["id"], make_subrecipient_headers(np["id"]))
    updated = validate_success(res, 200)
    assert updated["status"] == "SUBMITTED"


def test_third_review_computes_average_and_scores_application(api):
    """PRD §3.3: "When the review just stored brings review_count to three, the application
    transitions from UNDER_REVIEW to SCORED as a side effect of that third review, with
    average_score recomputed to reflect all three."
    PRD §3.3: "which is the mean of the attached reviews' score values rounded half up to two
    decimals and is null while review_count is 0."

    Design: Corner/calculations/application_average_score_after_three_reviews
    """
    np = create_nonprofit()
    nofo = create_nofo()
    app = create_scored_application(nofo["id"], np["id"], scores=(80, 85, 90))
    assert app["review_count"] == 3
    assert app["average_score"] == 85.0
    assert app["status"] == "SCORED"


def test_duplicate_review_by_same_panelist_rejected(api):
    """PRD §3.3: "A panelist who has already reviewed a given application cannot review it
    again; the duplicate is rejected with ERR_DUPLICATE_REVIEW."

    Design: Corner/validations/duplicate_review_by_same_panelist_rejected
    """
    np, nofo, app = _application_under_review(api, scores_done=(80,))
    res = api.create_review(app["id"], create_review_payload(60), make_panelist_headers("pan-1"))
    validate_error(res, "ERR_DUPLICATE_REVIEW")


def test_negotiated_rate_over_cap_rejected(api):
    """PRD §3.2: "when a negotiated_indirect_rate is supplied it must not exceed the
    opportunity's indirect_cost_cap_pct (otherwise ERR_INDIRECT_RATE_OVER_CAP); the rate is
    ignored for a DE_MINIMIS election."

    Design: Corner/validations/negotiated_rate_over_cap_rejected_on_submit
    """
    np = create_nonprofit()
    nofo = create_nofo(indirect_cost_cap_pct=0.30)
    payload = create_application_payload(
        np["id"], indirect_method="NEGOTIATED", negotiated_indirect_rate=0.40
    )
    res = api.create_application(nofo["id"], payload, make_subrecipient_headers(np["id"]))
    validate_error(res, "ERR_INDIRECT_RATE_OVER_CAP")
