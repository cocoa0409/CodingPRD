"""Role exclusivity, ownership, the three segregations, and the auth precondition."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_application,
    create_evidence_payload,
    create_location_claim_payload,
    create_score_sheet_payload,
    current_application_version,
    make_scoring_officer_headers,
    make_subgrantee_headers,
    read_application,
    read_challenge,
    read_location,
    read_program,
    read_subgrantee,
    register_subgrantee,
    setup_challenge_open_program,
    setup_community_challenge_meeting_standard,
    setup_qualified_subgrantee,
    setup_submitted_application,
    setup_under_review_challenge,
    triage_challenge,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.fixtures import (
    ADMIN,
    ANALYST,
    ANALYST_OTHER,
    AUDITOR,
    REVIEWER,
    SCORER,
    advance_program_to_scoring,
)
from test_helpers.test_users import NO_USER_HEADERS, TEST_USERS

STRANGER_PROVIDER = TEST_USERS["provider_stranger_headers"]


def test_no_role_reaches_outside_its_own_exclusive_operations():
    """The role model separates duties rather than nesting them, so the program
    administrator cannot triage, open a capability review or score, and each other
    role is refused on the operations reserved to somebody else — with no referenced
    row left altered.

    PRD 2.1: "A request whose `X-User-Role` is missing, is not one of the nine
    declared role names, or is not listed among the roles authorised for the
    endpoint being called is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.12: "2. **Priority 12 — role authorisation.** `X-User-Role` present, one
    of the nine declared roles, and listed for the endpoint →
    `ERR_UNAUTHORIZED`."
    PRD 3.3: "Triage sets `rebuttal_round` to 1, stamps `rebuttal_deadline` at
    thirty days after the current logical instant, records the acting analyst as
    `triaged_by_user_id`, and on the eligibility axis moves the contested location
    `MAPPED → CHALLENGED` while re-deriving that location's `challenge_count`."

    Design: Corner/rbac/rbac_exclusive_operation_denials_rejected
    """
    ctx = setup_challenge_open_program(("L3",))
    contested = ctx["location_ids"]["L3"]
    applicant = register_subgrantee(ctx["program_id"])
    application = create_application(ctx["program_id"], applicant["id"])
    challenge = setup_community_challenge_meeting_standard(ctx["program_id"], contested)
    application_version = current_application_version(application["id"])

    denials = [
        api_client.triage_challenge(challenge["id"], ADMIN),
        api_client.begin_capability_review(applicant["id"], ADMIN),
        api_client.create_score_sheet(
            create_score_sheet_payload(application["id"], application_version), ADMIN
        ),
        api_client.close_challenge_window(ctx["program_id"], ANALYST),
        api_client.select_application(application["id"], SCORER),
        api_client.create_location_claim(
            create_location_claim_payload(application["id"], contested), REVIEWER
        ),
        api_client.close_rebuttal(challenge["id"], AUDITOR),
        api_client.set_clock(
            "2026-08-11T00:00:00Z", make_subgrantee_headers(applicant["id"])
        ),
    ]
    for refused in denials:
        validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, 403)

    untriaged = read_challenge(challenge["id"])
    assert untriaged["challenge_state"] == "SUBMITTED"
    assert untriaged["triaged_by_user_id"] is None
    assert read_subgrantee(applicant["id"])["capability_state"] == "REGISTERED"
    held = read_application(application["id"])
    assert held["application_state"] == "DRAFT"
    assert held["claim_count"] == 0
    assert read_program(ctx["program_id"])["program_state"] == "CHALLENGE_OPEN"
    assert read_location(contested)["eligibility_state"] == "MAPPED"

    triaged = triage_challenge(challenge["id"])
    assert triaged["rebuttal_deadline"].startswith("2026-09-09T00:00:00"), (
        "Thirty days after 2026-08-10, so the refused clock call never moved the clock"
    )


def test_a_subgrantee_cannot_act_on_another_applicants_records():
    """The applicant role is the one identity-backed role, so a second registered
    applicant — holding a permitted role and a real identity — is refused on both
    writes against the first applicant's draft, and a provider who reported nothing
    about the contested location is refused on the evidence append.

    PRD 2.1: "An ownership failure by a caller who does hold an allowed role is
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This covers three situations: a
    `Subgrantee` acting on an application, location claim or milestone whose owning
    application's `subgrantee_id` is not its own `X-User-ID`; an evidence append by
    a caller who is neither the challenge's `submitter_user_id` nor the challenged
    location's `reporting_provider_user_id`; and a challenge resubmission by a
    caller other than the challenge's `submitter_user_id`."
    PRD 3.5: "Submission is the applicant's own act and moves the application
    `DRAFT → SUBMITTED`. It requires the caller's `X-User-ID` to equal
    `subgrantee_id`, the program to be `CHALLENGE_OPEN` or `CHALLENGE_CLOSED`, the
    logical clock to sit inside the half-open application window at or after
    `application_window_start` and strictly before `application_window_end`,
    `claim_count` to be at least 1, `match_offer_pct` to be at least the program's
    `min_match_pct`, and `committed_down_mbps` and `committed_up_mbps` to be at
    least the program's `served_down_mbps_threshold` and
    `served_up_mbps_threshold` respectively — with the floor stated absolutely as at
    least 100 megabits per second down and at least 20 up."

    Design: Corner/rbac/rbac_subgrantee_cannot_touch_another_subgrantees_application_rejected
    """
    ctx = setup_challenge_open_program(("L3",))
    contested = ctx["location_ids"]["L3"]
    assert ctx["locations"]["L3"]["reporting_provider_user_id"] == "prov-2"

    owner = register_subgrantee(ctx["program_id"])
    intruder = register_subgrantee(ctx["program_id"], legal_name="Southline Broadband")
    application = create_application(ctx["program_id"], owner["id"])
    intruder_headers = make_subgrantee_headers(intruder["id"])

    refused_claim = api_client.create_location_claim(
        create_location_claim_payload(application["id"], contested), intruder_headers
    )
    validate_error(refused_claim, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    refused_submit = api_client.submit_application(application["id"], intruder_headers)
    validate_error(refused_submit, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    guarded = read_application(application["id"])
    assert guarded["application_state"] == "DRAFT"
    assert guarded["claim_count"] == 0
    claims, claim_meta = validate_paginated(
        api_client.list_application_location_claims(application["id"], ADMIN)
    )
    assert claims == []
    assert claim_meta["total_count"] == 0

    challenge = setup_community_challenge_meeting_standard(ctx["program_id"], contested)
    before_count = validate_paginated(
        api_client.list_challenge_evidence(challenge["id"], ADMIN)
    )[1]["total_count"]

    refused_append = api_client.append_challenge_evidence(
        challenge["id"],
        create_evidence_payload(
            "FIELD_SURVEY", "2026-07-01T00:00:00Z", challenge["version"]
        ),
        STRANGER_PROVIDER,
    )
    validate_error(refused_append, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    _, after_meta = validate_paginated(
        api_client.list_challenge_evidence(challenge["id"], ADMIN)
    )
    assert after_meta["total_count"] == before_count


def test_the_analyst_who_triaged_a_challenge_may_not_determine_it():
    """Determination is open to the analyst role, but not to the very analyst
    recorded as having triaged this record; a second analyst decides it and the
    rejection affirms the contested location.

    PRD 2.6: "Three separations are enforced on `X-User-ID`, and all three surface
    as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 2.6: "First, the analyst recorded in a challenge's `triaged_by_user_id` may
    not record that challenge's determination."
    PRD 3.3: "Whatever the outcome, the acting caller may not be the one recorded in
    `triaged_by_user_id`, and the recorded outcome is stamped into `outcome` while
    the caller is stamped into `determined_by_user_id`."
    PRD 3.3: "A `REJECTED` determination moves the challenge
    `UNDER_REVIEW → REJECTED` and, on the eligibility axis, moves the location
    `CHALLENGED → AFFIRMED` with `classification_status` and `classification_source`
    left exactly as they were."

    Design: Corner/rbac/rbac_segregation_triager_cannot_determine_rejected
    """
    ctx = setup_challenge_open_program(("L3",))
    contested = ctx["location_ids"]["L3"]
    challenge = setup_under_review_challenge(ctx["program_id"], contested)
    assert challenge["triaged_by_user_id"] == "analyst-1"

    refused = api_client.determine_challenge(
        challenge["id"], {"outcome": "REJECTED"}, ANALYST
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    held = read_challenge(challenge["id"])
    assert held["challenge_state"] == "UNDER_REVIEW"
    assert held["outcome"] is None
    assert held["determined_by_user_id"] is None
    assert read_location(contested)["eligibility_state"] == "CHALLENGED"

    determined = validate_success(
        api_client.determine_challenge(
            challenge["id"], {"outcome": "REJECTED"}, ANALYST_OTHER
        )
    )
    assert determined["challenge_state"] == "REJECTED"
    assert determined["outcome"] == "REJECTED"
    assert determined["determined_by_user_id"] == "analyst-2"

    affirmed = read_location(contested)
    assert affirmed["eligibility_state"] == "AFFIRMED"
    assert affirmed["classification_status"] == "UNSERVED"
    assert affirmed["classification_source"] == "NATIONAL_MAP"


def test_the_reviewer_who_qualified_an_applicant_may_not_score_its_application():
    """The separation is keyed on identity rather than role: the same person who was
    recorded as the applicant's capability reviewer is refused when acting as a
    scoring officer over that applicant's application, while a different officer
    scores it.

    PRD 2.6: "Three separations are enforced on `X-User-ID`, and all three surface
    as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 2.6: "Second, the reviewer recorded in a subgrantee's
    `capability_reviewer_user_id` may not create a score sheet for any application
    of that subgrantee."
    PRD 3.6: "Beyond the version check it requires the application to be in
    `SUBMITTED` or `RESCORE_REQUIRED`, the application's applicant to be
    `QUALIFIED` — otherwise `ERR_SUBGRANTEE_NOT_QUALIFIED` — at least one location
    claim in `CLAIMED_ELIGIBLE`, so that `confirmed_location_count` — the final cost
    denominator — is at least 1, otherwise `ERR_NO_ELIGIBLE_LOCATIONS` — and the
    acting officer not to be the applicant's `capability_reviewer_user_id`."

    Design: Corner/rbac/rbac_segregation_capability_reviewer_cannot_score_rejected
    """
    ctx = setup_challenge_open_program(("L2", "L3", "L5"))
    applicant = setup_qualified_subgrantee(ctx["program_id"])
    assert applicant["capability_reviewer_user_id"] == "reviewer-1"
    application, _ = setup_submitted_application(
        ctx["program_id"],
        applicant["id"],
        [(ctx["location_ids"][key], 900002) for key in ("L2", "L3", "L5")],
    )
    advance_program_to_scoring(ctx["program_id"])

    version = current_application_version(application["id"])
    conflicted = api_client.create_score_sheet(
        create_score_sheet_payload(application["id"], version),
        make_scoring_officer_headers("reviewer-1"),
    )
    validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    sheets, meta = validate_paginated(
        api_client.list_application_score_sheets(application["id"], ADMIN)
    )
    assert sheets == []
    assert meta["total_count"] == 0
    assert read_application(application["id"])["application_state"] == "SUBMITTED"

    sheet = validate_success(
        api_client.create_score_sheet(
            create_score_sheet_payload(application["id"], version), SCORER
        ),
        201,
    )
    assert sheet["scored_by_user_id"] == "scorer-1"
    assert sheet["score_state"] == "FINAL"
    assert read_application(application["id"])["application_state"] == "SCORED"


def test_only_the_clock_endpoint_runs_without_an_acting_user():
    """The clock setter is the one endpoint that needs no acting user, so it accepts
    a request carrying only a role; every other endpoint refuses a missing or empty
    identity ahead of the pagination and existence checks in the same request.

    PRD 2.1: "A request with a missing or empty `X-User-ID` is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401); the sole exception is the logical-clock
    endpoint, which is a test-driving facility and requires no acting user."
    PRD 2.12: "1. **Priority 10 — authentication.** `X-User-ID` present and
    non-empty on every endpoint except the logical-clock setter →
    `ERR_UNAUTHENTICATED`."
    PRD 2.12: "When more than one rule could reject a request, the rule with the
    lowest priority number wins and its error is the one returned; evaluation stops
    at the first violation."

    Design: Corner/validations/missing_user_id_header_rejected
    """
    anonymous_clock = api_client.set_clock("2026-08-10T00:00:00Z", NO_USER_HEADERS)
    assert anonymous_clock.status_code == 200, (
        "The clock endpoint is the sole exception to the identity requirement"
    )

    ctx = setup_challenge_open_program(("L3",))

    everything_broken = api_client.list_locations(
        NO_USER_HEADERS, params={"program_id": NON_EXISTENT_UUID, "limit": 0}
    )
    validate_error(everything_broken, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    empty_identity = dict(NO_USER_HEADERS)
    empty_identity["X-User-ID"] = ""
    validate_error(
        api_client.get_program(ctx["program_id"], empty_identity),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api_client.list_programs(empty_identity),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    assert read_program(ctx["program_id"])["program_state"] == "CHALLENGE_OPEN"
    assert DEFAULT_CLOCK == "2026-08-01T00:00:00Z"
