"""Security and access control: role authorization, the validation cascade
order, client/author/reviewer ownership, and segregation of duties
(PRD §2.1, §2.8, §2.9, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_client_payload,
    create_draft_report,
    create_engagement_payload,
    create_in_progress_engagement,
    create_parties,
    create_submitted_engagement,
    make_client_headers,
    make_review_appraiser_headers,
    make_staff_appraiser_headers,
    setup_report_internal_review,
    validate_error,
    validate_success,
)

EM = TEST_USERS["engagement_manager_headers"]


def test_role_beats_state_on_sign(api):
    """PRD §2.9: "When several checks apply to a single request, they are
    evaluated in one fixed order, and the first failing check produces the
    response" — "2. **Role authorization.** The caller's role must appear in
    the endpoint's authorized role list — otherwise `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)" precedes "8. **State validity.**" A StaffAppraiser calling
    the MAISigner-only sign endpoint (PRD §4) on a `DRAFTING` report sees the
    role error, not the state error.

    Design: Corner/validations/priority_role_beats_state_on_sign
    """
    bundle = create_in_progress_engagement()
    report = create_draft_report(bundle)
    res = api.sign_report(report["id"], bundle["author_headers"])
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


def test_role_beats_existence_on_submit(api):
    """PRD §2.9: role authorization (step 2, `ERR_FORBIDDEN_FOR_ROLE`)
    precedes existence (step 3, "`ERR_NOT_FOUND` (HTTP 404)") — on the same
    nonexistent engagement id, a role never allowed to submit (Client; PRD
    §4 lists submit as EngagementManager-only) is refused for its role while
    the EngagementManager reaches the existence check.

    Design: Corner/validations/priority_role_beats_existence_on_submit
    """
    parties = create_parties()
    res_role = api.submit_engagement(NON_EXISTENT_UUID, parties["client_headers"])
    validate_error(res_role, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)
    res_ex = api.submit_engagement(NON_EXISTENT_UUID, EM)
    validate_error(res_ex, "ERR_NOT_FOUND", expected_status=404)


def test_ownership_client_mismatch_returns_403(api):
    """PRD §2.1: "The client-ownership check — the caller must be the
    engagement's client, else `ERR_NOT_ENGAGEMENT_CLIENT` (HTTP 403) —
    guards five actions: accepting an engagement letter, declining an
    engagement letter, submitting property data to an engagement, creating a
    revision request on a report, and withdrawing a revision request."

    Design: Corner/validations/ownership_client_mismatch_returns_403
    """
    parties = create_parties()
    client_b = validate_success(api.create_client(
        create_client_payload(name="Beta Trust", client_type="INVESTOR"),
        EM), 201)
    eng = create_submitted_engagement(parties)
    res = api.accept_engagement(eng["id"], make_client_headers(client_b["id"]))
    validate_error(res, "ERR_NOT_ENGAGEMENT_CLIENT", expected_status=403)


def test_ownership_non_author_appraiser_returns_403(api):
    """PRD §2.1: "The author-ownership check — the `StaffAppraiser` caller
    must be the engagement's author appraiser, else
    `ERR_NOT_ASSIGNED_APPRAISER` (HTTP 403) — guards data-submission accept
    and reject; approach creation, completion, exclusion, and re-inclusion;
    comparable creation; report creation, submission to review, issuance to
    the client, reissuance, and finalization; and revision-request
    acceptance, escalation, and decline from `OPEN`." A different staff
    appraiser may not submit the report for review.

    Design: Corner/validations/ownership_non_author_appraiser_returns_403
    """
    parties = create_parties(
        extra_appraisers=[("Bob Other", "CERTIFIED_GENERAL")])
    bundle = create_in_progress_engagement(parties)
    report = create_draft_report(bundle)
    bob = parties["extras"][0]
    res = api.submit_review(
        report["id"], make_staff_appraiser_headers(bob["id"]))
    validate_error(res, "ERR_NOT_ASSIGNED_APPRAISER", expected_status=403)


def test_ownership_non_reviewer_returns_403(api):
    """PRD §2.1: "The reviewer-ownership check — the `ReviewAppraiser` caller
    must be the engagement's assigned reviewer, else
    `ERR_NOT_ASSIGNED_REVIEWER` (HTTP 403) — guards review approval, review
    return, and declining a revision request that stands `ESCALATED`."

    Design: Corner/validations/ownership_non_reviewer_returns_403
    """
    parties = create_parties(
        extra_appraisers=[("Bob Other", "CERTIFIED_GENERAL")])
    bundle = setup_report_internal_review(parties)
    bob = parties["extras"][0]
    res = api.review_approve(
        bundle["report"]["id"], make_review_appraiser_headers(bob["id"]))
    validate_error(res, "ERR_NOT_ASSIGNED_REVIEWER", expected_status=403)


def test_client_cannot_create_engagement_403(api):
    """PRD §4: `POST /engagements` authorizes only `EngagementManager`; PRD
    §2.1: "A request whose role is not on the target endpoint's authorized
    list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/client_cannot_create_engagement_403
    """
    parties = create_parties()
    payload = create_engagement_payload(
        parties["client"]["id"], NON_EXISTENT_UUID, NON_EXISTENT_UUID)
    res = api.create_engagement(payload, parties["client_headers"])
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


def test_reviewer_cannot_submit_review_403(api):
    """PRD §4: `POST /reports/{reportId}/submit_review` authorizes only
    `StaffAppraiser`; the assigned reviewer calling it is refused with
    `ERR_FORBIDDEN_FOR_ROLE` (PRD §2.1) — segregation of duties at the role
    level.

    Design: Corner/rbac/reviewer_cannot_submit_review_403
    """
    bundle = create_in_progress_engagement()
    report = create_draft_report(bundle)
    res = api.submit_review(report["id"], bundle["reviewer_headers"])
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


def test_engagement_manager_cannot_place_hold_403(api):
    """PRD §4: `POST /engagements/{engagementId}/litigation-hold` authorizes
    only `LegalCounsel`; an EngagementManager caller is refused with
    `ERR_FORBIDDEN_FOR_ROLE` (PRD §2.1).

    Design: Corner/rbac/engagement_manager_cannot_place_hold_403
    """
    bundle = create_in_progress_engagement()
    res = api.place_litigation_hold(
        bundle["engagement"]["id"], {"matter_reference": "Case 26-CV-1042"}, EM)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


def test_sod_same_author_reviewer_at_submit(api):
    """PRD §2.8: "An engagement letter cannot be submitted to the client
    while the same appraiser occupies both production seats: at submit time,
    `author_appraiser_id` must differ from `reviewer_appraiser_id`, and a
    violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/rbac/sod_same_author_reviewer_at_submit
    """
    parties = create_parties()
    eng = validate_success(api.create_engagement(
        create_engagement_payload(
            parties["client"]["id"], parties["author"]["id"],
            parties["author"]["id"]),  # reviewer seat filled by the author
        EM), 201)
    res = api.submit_engagement(eng["id"], EM)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=409)
    after = validate_success(api.get_engagement(eng["id"], EM), 200)
    assert after["status"] == "DRAFT"
