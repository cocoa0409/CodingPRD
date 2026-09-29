"""Who may act: peer roles, header-borne identity, record ownership and the two-person rules."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import UNKNOWN_POSTING_ID_ALT
from test_helpers.test_users import (
    COMPLIANCE_REVIEWER_ALT_USER_ID,
    COMPLIANCE_REVIEWER_USER_ID,
    brand_lead_headers,
    candidate_headers,
    community_manager_headers,
    compliance_reviewer_headers,
    headers_for_role,
    media_buyer_headers,
    no_identity_headers,
    persona_researcher_headers,
)


def test_the_staff_roles_are_peers_and_the_role_check_precedes_the_path_lookup(api):
    """PRD §2.9: "3. The acting role must appear in the called endpoint's authorized-role list, else
    `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD §2.2: "A request whose headers are well formed but whose role is not among the endpoint's
    authorized roles is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.9: "6. Every path identifier must resolve, left to right, with the per-kind codes of §2.8
    (404)."

    Design: Corner/rbac/persona_researcher_cannot_publish_a_posting_or_clear_compliance
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    posting = fx.create_posting(api, family["id"])
    optimized = fx.optimize_posting(api, posting["id"], posting["version"])

    researcher_publishes = api.publish_job_posting(posting["id"], persona_researcher_headers())
    buyer_clears = api.compliance_review_job_posting(
        posting["id"], f.compliance_review_payload("CLEAR", "not my job"), media_buyer_headers()
    )
    researcher_publishes_a_ghost = api.publish_job_posting(
        UNKNOWN_POSTING_ID_ALT, persona_researcher_headers()
    )
    researcher_reads = api.get_job_posting(posting["id"], persona_researcher_headers())

    for response in (researcher_publishes, buyer_clears, researcher_publishes_a_ghost):
        validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED, 403)
    read_back = validate_success(researcher_reads, 200)
    assert read_back["content_status"] == "OPTIMIZED", read_back
    assert read_back["compliance_status"] == "UNREVIEWED", read_back
    assert read_back["version"] == 2, read_back
    assert read_back["version"] == optimized["version"], read_back


def test_a_candidate_may_only_move_her_own_consent_while_a_manager_may_move_anyones(api):
    """PRD §2.9: "8. A `Candidate` may act only on the `TalentCommunityMember` whose `id` equals the
    acting `X-User-ID`, on the consent-change operation, else `ERR_NOT_RESOURCE_OWNER` (403)."
    PRD §3.7: "This operation is available to a `Candidate` and to a `CommunityManager`, but a
    `Candidate` may only act on the member record whose `id` equals their own `X-User-ID`; acting on
    anyone else's record is refused with `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.7: "`PAUSE` requires `SUBSCRIBED` and moves the member `SUBSCRIBED → PAUSED`."

    Design: Corner/rbac/candidate_cannot_change_another_members_consent
    """
    program = fx.create_program(api)
    first = fx.subscribed_member(api, program["id"], "m1@example.com")
    second = fx.subscribed_member(api, program["id"], "m2@example.com")

    acting_on_a_stranger = api.change_consent(
        second["id"], f.consent_change_payload("UNSUBSCRIBE"), candidate_headers(first["id"])
    )
    acting_on_herself = api.change_consent(
        first["id"], f.consent_change_payload("PAUSE"), candidate_headers(first["id"])
    )
    manager_acts_for_her = api.change_consent(
        second["id"], f.consent_change_payload("PAUSE"), community_manager_headers()
    )

    validate_error(acting_on_a_stranger, ApiErrorId.NOT_RESOURCE_OWNER, 403)
    own_pause = validate_success(acting_on_herself, 200)
    assert own_pause["consent_status"] == "PAUSED", own_pause
    assert own_pause["version"] == first["version"] + 1, own_pause
    managed_pause = validate_success(manager_acts_for_her, 200)
    assert managed_pause["consent_status"] == "PAUSED", managed_pause
    assert managed_pause["id"] == second["id"], managed_pause


def test_identity_headers_are_required_except_where_anonymous_is_authorized(api):
    """PRD §2.2: "A request that is missing `X-User-ID` or `X-User-Role`, that supplies either header
    empty, or that names a role outside the eight above, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401) — but only on endpoints whose authorized-role list does not include `Anonymous`."
    PRD §2.2: "Endpoints that do list `Anonymous` accept header-less requests."
    PRD §2.9: "2. `X-User-Role` must name one of the eight roles in the access matrix, else
    `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/request_with_missing_x_user_role_header_returns_unauthenticated
    """
    program = fx.create_program(api)

    without_headers = api.get_program(program["id"], no_identity_headers())
    with_an_invented_role = api.get_program(
        program["id"], headers_for_role("TalentMarketingIntern")
    )
    anonymous_browse = api.list_job_postings(no_identity_headers())

    validate_error(without_headers, ApiErrorId.UNAUTHENTICATED, 401)
    validate_error(with_an_invented_role, ApiErrorId.UNAUTHENTICATED, 401)
    postings, meta = validate_paginated(anonymous_browse)
    assert postings == [], postings
    assert meta["total_count"] == 0, meta
    settled = fx.read_program(api, program["id"])
    assert settled["version"] == program["version"], settled
    assert settled["updated_at"] == program["updated_at"], settled


def test_the_author_of_the_copy_cannot_be_the_reviewer_who_clears_it(api):
    """PRD §2.11: "A posting compliance decision — `CLEAR` or `FLAG` alike — is refused when the
    acting identifier equals the posting's `optimized_by_user_id`."
    PRD §2.11: "All three refusals carry `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and all three are
    evaluated before any state-machine or business rule on the same request."
    PRD §3.4: "Neither decision is permitted on an `ARCHIVED` posting, which is refused with
    `ERR_POSTING_ALREADY_ARCHIVED`, and neither is permitted when the acting `X-User-ID` equals the
    posting's `optimized_by_user_id`, which is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_same_user_cannot_optimize_a_posting_and_then_clear_its_compliance
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    posting = fx.create_posting(api, family["id"])
    optimized = validate_success(
        api.optimize_job_posting(
            posting["id"],
            f.optimize_payload(posting["version"]),
            brand_lead_headers(COMPLIANCE_REVIEWER_USER_ID),
        ),
        200,
    )

    self_review = api.compliance_review_job_posting(
        posting["id"],
        f.compliance_review_payload("CLEAR", "reviewing my own copy"),
        compliance_reviewer_headers(COMPLIANCE_REVIEWER_USER_ID),
    )
    after_the_refusal = fx.read_posting(api, posting["id"])
    independent_review = api.compliance_review_job_posting(
        posting["id"],
        f.compliance_review_payload("CLEAR", "independent review"),
        compliance_reviewer_headers(COMPLIANCE_REVIEWER_ALT_USER_ID),
    )

    assert optimized["optimized_by_user_id"] == COMPLIANCE_REVIEWER_USER_ID, optimized
    validate_error(self_review, ApiErrorId.SEGREGATION_OF_DUTIES, 403)
    assert after_the_refusal["compliance_status"] == "UNREVIEWED", after_the_refusal
    assert after_the_refusal["cleared_by_user_id"] is None, after_the_refusal
    assert after_the_refusal["version"] == optimized["version"], after_the_refusal
    cleared = validate_success(independent_review, 200)
    assert cleared["compliance_status"] == "CLEARED", cleared
    assert cleared["cleared_by_user_id"] == COMPLIANCE_REVIEWER_ALT_USER_ID, cleared
    assert cleared["optimized_by_user_id"] == COMPLIANCE_REVIEWER_USER_ID, cleared
