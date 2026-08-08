"""RBAC, ownership, segregation of duties, and the referential-beats-temporal
validation precedence on scheduling."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    create_account_manager, create_recruiter, create_client_entity, create_opening,
    create_client_payload, create_candidate_entity, create_application_entity,
    create_site_visit_entity, create_site_visit_payload,
    deactivate_staff,
    setup_open_opening, setup_placement_pre_start,
    make_recruiter_headers, make_account_manager_headers,
)


def test_recruiter_cannot_create_client(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."
    PRD §3.1: "Clients are the healthcare organizations the agency recruits for, and
    each is created by an AccountManager."

    Design: Corner/validations/recruiter_forbidden_to_create_client
    """
    am = create_account_manager()
    rec = create_recruiter(["CARDIOLOGY"])
    resp = api.create_client(
        create_client_payload(am["id"], name="Nope"), make_recruiter_headers(rec["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_recruiter_cannot_source_another_recruiters_candidate(api):
    """PRD §2.1: "a Recruiter may act only on Candidate records whose recruiter_id is
    theirs and on Application records they own."
    PRD §2.1: "A resource-owning role that acts on a resource it does not own is
    rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/validations/recruiter_cannot_source_another_recruiters_candidate
    """
    am = create_account_manager()
    rec1 = create_recruiter(["CARDIOLOGY"], full_name="Rec One", email="rec1@x.com")
    rec2 = create_recruiter(["CARDIOLOGY"], full_name="Rec Two", email="rec2@x.com")
    client = create_client_entity(am["id"])
    opening = create_opening(am["id"], client["id"])
    cand = create_candidate_entity(rec1["id"], full_name="Dr One")  # owned by rec1
    resp = api.create_application(
        {"candidate_id": cand["id"], "opening_id": opening["id"]},
        make_recruiter_headers(rec2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_fee_waive_by_offer_extender_rejected(api):
    """PRD §3.8: "waiving is subject to a four-eyes control — the acting account
    manager's id must differ from the extended_by_user_id recorded on the placement's
    originating offer, and if the same person who extended that offer attempts the
    waiver it is rejected with ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/validations/fee_waive_by_offer_extender_segregation_of_duties
    """
    ctx = setup_placement_pre_start()  # offer extended by ctx["am_id"], fee PENDING
    resp = api.transition_placement(
        ctx["placement_id"], {"action": "WAIVE"},
        make_account_manager_headers(ctx["am_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# --------------------------------------------------------------------------
# referential (interviewer must be ACTIVE) beats temporal overlap
# --------------------------------------------------------------------------
def _app_with_inactive_interviewer_and_prior_visit(api):
    ctx = setup_open_opening()
    intv = create_recruiter(["CARDIOLOGY"], full_name="Ivan Intv", email="intv@x.com")
    cand = create_candidate_entity(ctx["rec_id"])
    app = create_application_entity(ctx["rec_id"], cand["id"], ctx["opening_id"])
    create_site_visit_entity(
        ctx["rec_id"], app["id"], intv["id"],
        scheduled_start="2026-05-03T15:00:00Z", scheduled_end="2026-05-03T16:00:00Z",
    )
    deactivate_staff(intv["id"])
    return ctx, app, intv


def test_inactive_interviewer_with_overlap_reports_referential_error(api):
    """PRD §3.4: "The interviewer named by interviewer_user_id must be an ACTIVE
    staff user; otherwise the request is rejected with ERR_INTERVIEWER_INVALID."
    PRD §2.10: business referential integrity (priority 9) is evaluated before
    temporal overlap on scheduling (priority 10).

    Design: Difficulty/priority_pair_validation_conflict/sitevisit_referential_beats_temporal
    """
    ctx, app, intv = _app_with_inactive_interviewer_and_prior_visit(api)
    resp = api.create_site_visit(
        create_site_visit_payload(
            app["id"], intv["id"],
            scheduled_start="2026-05-03T15:30:00Z", scheduled_end="2026-05-03T16:30:00Z",
        ),
        make_recruiter_headers(ctx["rec_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INTERVIEWER_INVALID.value)


def test_inactive_interviewer_without_overlap_still_referential_error(api):
    """PRD §3.4: "The interviewer named by interviewer_user_id must be an ACTIVE
    staff user; otherwise the request is rejected with ERR_INTERVIEWER_INVALID."

    Design: Difficulty/priority_pair_validation_conflict/sitevisit_referential_beats_temporal
    """
    ctx, app, intv = _app_with_inactive_interviewer_and_prior_visit(api)
    # Non-overlapping window (no temporal conflict) isolates the referential check.
    resp = api.create_site_visit(
        create_site_visit_payload(
            app["id"], intv["id"],
            scheduled_start="2026-05-03T20:00:00Z", scheduled_end="2026-05-03T21:00:00Z",
        ),
        make_recruiter_headers(ctx["rec_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INTERVIEWER_INVALID.value)
