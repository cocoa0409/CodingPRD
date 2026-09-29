"""Platform-wide conventions: per-entity 404 codes, the identity headers, the role
table, segregation of duties, the two echoed version counters and the immediate
visibility of derived fields."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PRIVACY_OFFICER_HEADERS,
    RESEARCH_LEAD_HEADERS,
    RESEARCH_OPS_ADMIN_HEADERS,
    RESEARCHER_HEADERS,
    STAKEHOLDER_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    auto_invite_payload,
    create_decision,
    create_finding,
    create_incentive_settlement_payload,
    create_participant_pool_payload,
    create_pool,
    create_readout_payload,
    create_recruitment_payload,
    create_request,
    create_research_request_payload,
    create_study_payload,
    create_theme,
    create_theme_payload,
    grant_consent,
    link_evidence,
    lock_finding,
    read_consent,
    read_finding,
    read_pool,
    read_recruitment,
    read_study,
    read_theme,
    revoke_consent_payload,
    setup_approved_request,
    setup_fielding_study,
    setup_guide_approved_study,
    setup_invited_recruitments,
    setup_study_in_analysis,
    study_guide_payload,
    triage_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# Headers that deliberately fail the identity check of PRD 2.1. `build_user_headers`
# always populates both identity headers, so these dictionaries are written out.
NO_IDENTITY_HEADERS = {"Content-Type": "application/json"}
BLANK_USER_ID_HEADERS = {
    "Content-Type": "application/json",
    "X-User-ID": "",
    "X-User-Role": "Stakeholder",
}
BLANK_ROLE_HEADERS = {
    "Content-Type": "application/json",
    "X-User-ID": "u_stake_1",
    "X-User-Role": "",
}
ROLE_ONLY_HEADERS = {
    "Content-Type": "application/json",
    "X-User-Role": "Stakeholder",
}
USER_ONLY_HEADERS = {
    "Content-Type": "application/json",
    "X-User-ID": "u_stake_1",
}


# ===========================================================================
# Each entity type answers an unknown id with its own 404 code
# ===========================================================================
NOT_FOUND_ROWS = [
    (
        "roadmap decision read",
        lambda api: api.get_roadmap_decision(NON_EXISTENT_UUID, STAKEHOLDER_HEADERS),
        "ERR_DECISION_NOT_FOUND",
    ),
    (
        "research request read",
        lambda api: api.get_research_request(NON_EXISTENT_UUID, RESEARCHER_HEADERS),
        "ERR_REQUEST_NOT_FOUND",
    ),
    (
        "participant pool read",
        lambda api: api.get_participant_pool(
            NON_EXISTENT_UUID, RESEARCH_OPS_ADMIN_HEADERS
        ),
        "ERR_POOL_NOT_FOUND",
    ),
    (
        "participant read",
        lambda api: api.get_participant(NON_EXISTENT_UUID, RESEARCHER_HEADERS),
        "ERR_PARTICIPANT_NOT_FOUND",
    ),
    (
        "study read",
        lambda api: api.get_study(NON_EXISTENT_UUID, RESEARCHER_HEADERS),
        "ERR_STUDY_NOT_FOUND",
    ),
    (
        "recruitment read",
        lambda api: api.get_recruitment(NON_EXISTENT_UUID, RESEARCHER_HEADERS),
        "ERR_RECRUITMENT_NOT_FOUND",
    ),
    (
        "consent record read",
        lambda api: api.get_consent_record(NON_EXISTENT_UUID, PRIVACY_OFFICER_HEADERS),
        "ERR_CONSENT_NOT_FOUND",
    ),
    (
        "artifact read",
        lambda api: api.get_artifact(NON_EXISTENT_UUID, RESEARCHER_HEADERS),
        "ERR_ARTIFACT_NOT_FOUND",
    ),
    (
        "theme read",
        lambda api: api.get_theme(NON_EXISTENT_UUID, RESEARCHER_HEADERS),
        "ERR_THEME_NOT_FOUND",
    ),
    (
        "finding read",
        lambda api: api.get_finding(NON_EXISTENT_UUID, RESEARCHER_HEADERS),
        "ERR_FINDING_NOT_FOUND",
    ),
    (
        "evidence link deletion",
        lambda api: api.delete_evidence_link(NON_EXISTENT_UUID, RESEARCHER_HEADERS),
        "ERR_EVIDENCE_LINK_NOT_FOUND",
    ),
    (
        "readout read",
        lambda api: api.get_readout(NON_EXISTENT_UUID, RESEARCHER_HEADERS),
        "ERR_READOUT_NOT_FOUND",
    ),
    (
        "follow-up completion",
        lambda api: api.complete_follow_up(NON_EXISTENT_UUID, STAKEHOLDER_HEADERS),
        "ERR_FOLLOW_UP_NOT_FOUND",
    ),
]


@pytest.mark.parametrize(
    "label,call,expected_error_id",
    NOT_FOUND_ROWS,
    ids=[row[0].replace(" ", "_") for row in NOT_FOUND_ROWS],
)
def test_each_entity_type_has_its_own_not_found_code(api, label, call, expected_error_id):
    """A missing row yields the code that names its own entity type, never a generic one.

    PRD 2.6: "**Existence, resolved in the order the identifiers are listed below**
    — a referenced row that does not exist yields its own 404 code before any body
    validation, state check or business rule is considered"

    Design: Corner/entities/unknown_resource_ids_return_their_own_not_found_errors
    """
    response = call(api)
    validate_error(response, expected_error_id)


def test_the_thirteen_not_found_codes_are_all_distinct(api):
    """Thirteen entity types answer with thirteen different identifiers.

    PRD 2.4: "All thirteen resource types in this system — `RoadmapDecision`,
    `ResearchRequest`, `ParticipantPool`, `Participant`, `Study`, `Recruitment`,
    `ConsentRecord`, `ResearchArtifact`, `Theme`, `Finding`, `EvidenceLink`,
    `Readout` and `FollowUp` — additionally carry `updated_at` and `version`."

    PRD 2.6: "**Existence, resolved in the order the identifiers are listed below**
    — a referenced row that does not exist yields its own 404 code before any body
    validation, state check or business rule is considered"

    Design: Corner/entities/unknown_resource_ids_return_their_own_not_found_errors
    """
    observed = []
    for label, call, expected_error_id in NOT_FOUND_ROWS:
        error = validate_error(call(api), expected_error_id)
        observed.append(error["error_id"])

    assert len(observed) == 13, (
        f"Expected one probe per resource type, got {len(observed)}"
    )
    assert len(set(observed)) == 13, (
        f"Expected thirteen distinct not-found identifiers, got {sorted(set(observed))}"
    )


# ===========================================================================
# Intake without a usable identity never reaches the funnel
# ===========================================================================
MISSING_IDENTITY_HEADERS = [
    ("both headers omitted", NO_IDENTITY_HEADERS),
    ("only the role supplied", ROLE_ONLY_HEADERS),
    ("only the user id supplied", USER_ONLY_HEADERS),
    ("an empty user id", BLANK_USER_ID_HEADERS),
    ("an empty role", BLANK_ROLE_HEADERS),
]


@pytest.mark.parametrize(
    "label,headers",
    MISSING_IDENTITY_HEADERS,
    ids=[row[0].replace(" ", "_") for row in MISSING_IDENTITY_HEADERS],
)
def test_intake_without_both_identity_headers_is_unauthenticated(api, label, headers):
    """An absent or empty `X-User-ID` or `X-User-Role` stops the request at the door.

    PRD 2.1: "Every request to every endpoint — including the two test-driving
    endpoints — must carry two headers: `X-User-ID`, identifying the acting
    operator, and `X-User-Role`, naming the role that operator is acting in."

    PRD 2.1: "If either header is absent or present but empty, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/request_creation_without_identity_headers_returns_unauthenticated
    """
    decision = create_decision(api)

    response = api.raw_post(
        "/research-requests",
        create_research_request_payload(decision["id"]),
        headers,
    )
    validate_error(response, "ERR_UNAUTHENTICATED")


def test_an_unauthenticated_intake_attempt_creates_no_request(api):
    """The rejected attempt leaves the decision's request list empty.

    PRD 2.1: "If either header is absent or present but empty, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD 2.1: "No further processing takes place; the platform never falls back on a
    default role or an anonymous identity."

    PRD 3.1: "The request lands in `status` `SUBMITTED` with `revision_round` at 0,
    its `requester_user_id` set to the acting operator's `X-User-ID`, and
    `priority_score`, `recommended_method`, `approved_method`, `triage_reason` and
    `triaged_at` all null."

    Design: Corner/errors/request_creation_without_identity_headers_returns_unauthenticated
    """
    decision = create_decision(api)
    payload = create_research_request_payload(decision["id"])

    validate_error(
        api.raw_post("/research-requests", payload, NO_IDENTITY_HEADERS),
        "ERR_UNAUTHENTICATED",
    )

    empty = api.list_decision_research_requests(decision["id"], STAKEHOLDER_HEADERS)
    empty_rows, empty_meta = validate_paginated(empty)
    assert empty_meta["total_count"] == 0, (
        f"Expected the rejected intake to have stored nothing, "
        f"got total_count {empty_meta['total_count']}"
    )
    assert empty_rows == [], f"Expected an empty list, got {len(empty_rows)} rows"

    created = validate_success(
        api.raw_post("/research-requests", payload, STAKEHOLDER_HEADERS), 201
    )
    assert created["status"] == "SUBMITTED", (
        f"Expected an identified intake to land SUBMITTED, got {created['status']}"
    )
    assert created["requester_user_id"] == "u_stake_1", (
        f"Expected requester_user_id to be taken from X-User-ID, "
        f"got {created['requester_user_id']!r}"
    )
    assert created["revision_round"] == 0, (
        f"Expected revision_round 0 at intake, got {created['revision_round']}"
    )

    after = api.list_decision_research_requests(decision["id"], STAKEHOLDER_HEADERS)
    after_rows, after_meta = validate_paginated(after)
    assert after_meta["total_count"] == 1, (
        f"Expected exactly the one accepted request, "
        f"got total_count {after_meta['total_count']}"
    )
    assert after_rows[0]["id"] == created["id"], (
        "Expected the accepted request to be the only row on the decision"
    )


def test_an_unlisted_role_is_unauthorised_rather_than_unauthenticated(api):
    """Headers that are present but name a role outside the five get 403, not 401.

    PRD 2.1: "If `X-User-Role` holds any string outside those five, or holds one of
    the five but that role is not listed as authorised for the endpoint being
    called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 2.6: "**Authentication** — both headers present and non-empty, else
    `ERR_UNAUTHENTICATED` (401)."

    PRD 2.6: "**Role authorisation** — `X-User-Role` is one of the five declared
    roles and is listed for the endpoint, else `ERR_UNAUTHORIZED` (403)."

    Design: Corner/errors/request_creation_without_identity_headers_returns_unauthenticated
    """
    decision = create_decision(api)
    payload = create_research_request_payload(decision["id"])

    unknown_role = api.raw_post("/research-requests", payload, UNKNOWN_ROLE_HEADERS)
    validate_error(unknown_role, "ERR_UNAUTHORIZED")

    missing_identity = api.raw_post("/research-requests", payload, NO_IDENTITY_HEADERS)
    validate_error(missing_identity, "ERR_UNAUTHENTICATED")

    rows, meta = validate_paginated(
        api.list_decision_research_requests(decision["id"], STAKEHOLDER_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"Expected neither rejected attempt to have stored a request, "
        f"got total_count {meta['total_count']}"
    )
    assert rows == [], f"Expected an empty list, got {len(rows)} rows"


# ===========================================================================
# Role-exclusive operations refuse every other role
# ===========================================================================
def _deny_fielding_as_stakeholder(api):
    ctx = setup_guide_approved_study(api)
    return api.field_study(ctx["study"]["id"], STAKEHOLDER_HEADERS)


def _deny_fielding_under_an_unlisted_role(api):
    ctx = setup_guide_approved_study(api)
    return api.field_study(ctx["study"]["id"], UNKNOWN_ROLE_HEADERS)


def _deny_pool_creation_as_researcher(api):
    return api.create_participant_pool(
        create_participant_pool_payload(), RESEARCHER_HEADERS
    )


def _deny_triage_as_researcher(api):
    decision = create_decision(api)
    request = create_request(decision["id"], api)
    return api.triage_research_request(
        request["id"], triage_payload("APPROVED"), RESEARCHER_HEADERS
    )


def _deny_consent_revocation_as_researcher(api):
    ctx = setup_fielding_study(api)
    consent = grant_consent(ctx["participants"][0]["id"], ctx["study"]["id"], api)
    return api.revoke_consent_record(
        consent["id"], revoke_consent_payload(), RESEARCHER_HEADERS
    )


def _deny_theme_creation_as_privacy_officer(api):
    return api.create_theme(create_theme_payload(), PRIVACY_OFFICER_HEADERS)


def _deny_decision_locking_as_research_lead(api):
    decision = create_decision(api)
    return api.lock_roadmap_decision(decision["id"], RESEARCH_LEAD_HEADERS)


def _deny_batch_invitation_as_research_lead(api):
    ctx = setup_fielding_study(api)
    return api.auto_invite(ctx["study"]["id"], auto_invite_payload(1), RESEARCH_LEAD_HEADERS)


DENIED_CALLS = [
    ("fielding a study as a Stakeholder", _deny_fielding_as_stakeholder),
    ("fielding a study under an unlisted role", _deny_fielding_under_an_unlisted_role),
    ("creating a pool as a Researcher", _deny_pool_creation_as_researcher),
    ("triaging intake as a Researcher", _deny_triage_as_researcher),
    ("revoking consent as a Researcher", _deny_consent_revocation_as_researcher),
    ("creating a theme as a PrivacyOfficer", _deny_theme_creation_as_privacy_officer),
    ("locking a decision as a ResearchLead", _deny_decision_locking_as_research_lead),
    ("batch inviting as a ResearchLead", _deny_batch_invitation_as_research_lead),
]


@pytest.mark.parametrize(
    "label,call",
    DENIED_CALLS,
    ids=[row[0].replace(" ", "_") for row in DENIED_CALLS],
)
def test_a_role_outside_the_authorised_list_is_refused(api, label, call):
    """Each role-exclusive operation refuses a caller the endpoint does not list.

    PRD 2.1: "If `X-User-Role` holds any string outside those five, or holds one of
    the five but that role is not listed as authorised for the endpoint being
    called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 2.6: "**Role authorisation** — `X-User-Role` is one of the five declared
    roles and is listed for the endpoint, else `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/roles_cannot_invoke_other_roles_exclusive_operations
    """
    validate_error(call(api), "ERR_UNAUTHORIZED")


def test_a_refused_role_check_changes_no_state(api):
    """A 403 on the role check is inert: nothing moves on any of the four targets.

    PRD 2.1: "If `X-User-Role` holds any string outside those five, or holds one of
    the five but that role is not listed as authorised for the endpoint being
    called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 2.6: "**Role authorisation** — `X-User-Role` is one of the five declared
    roles and is listed for the endpoint, else `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/roles_cannot_invoke_other_roles_exclusive_operations
    """
    ctx = setup_guide_approved_study(api)
    study_id = ctx["study"]["id"]
    decision_id = ctx["decision"]["id"]

    validate_error(api.field_study(study_id, STAKEHOLDER_HEADERS), "ERR_UNAUTHORIZED")
    validate_error(api.field_study(study_id, UNKNOWN_ROLE_HEADERS), "ERR_UNAUTHORIZED")
    validate_error(
        api.create_theme(create_theme_payload(), PRIVACY_OFFICER_HEADERS),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.lock_roadmap_decision(decision_id, RESEARCH_LEAD_HEADERS),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.create_participant_pool(
            create_participant_pool_payload(), RESEARCHER_HEADERS
        ),
        "ERR_UNAUTHORIZED",
    )

    study = read_study(study_id, api)
    assert study["execution_status"] == "GUIDE_APPROVED", (
        f"Expected the refused fielding to leave the study GUIDE_APPROVED, "
        f"got {study['execution_status']}"
    )
    assert study["fielded_at"] is None, (
        f"Expected fielded_at to stay null, got {study['fielded_at']!r}"
    )
    assert study["version"] == ctx["study"]["version"], (
        f"Expected the study version to stay {ctx['study']['version']}, "
        f"got {study['version']}"
    )

    decision = validate_success(
        api.get_roadmap_decision(decision_id, STAKEHOLDER_HEADERS), 200
    )
    assert decision["status"] == "OPEN", (
        f"Expected the refused lock to leave the decision OPEN, "
        f"got {decision['status']}"
    )
    assert decision["locked_at"] is None, (
        f"Expected locked_at to stay null, got {decision['locked_at']!r}"
    )

    themes_rows, themes_meta = validate_paginated(api.list_themes(RESEARCHER_HEADERS))
    assert themes_meta["total_count"] == 0, (
        f"Expected the refused theme creation to store nothing, "
        f"got total_count {themes_meta['total_count']}"
    )
    assert themes_rows == [], f"Expected no themes, got {len(themes_rows)} rows"


def test_a_refused_consent_revocation_leaves_the_record_granted(api):
    """The privacy cascade never starts when the role check refuses the caller.

    PRD 2.1: "`PrivacyOfficer` — owns consent and retention: grants and revokes
    consent, runs the retention sweep, and reads every artifact and evidence link."

    PRD 2.1: "If `X-User-Role` holds any string outside those five, or holds one of
    the five but that role is not listed as authorised for the endpoint being
    called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/roles_cannot_invoke_other_roles_exclusive_operations
    """
    ctx = setup_fielding_study(api)
    consent = grant_consent(ctx["participants"][0]["id"], ctx["study"]["id"], api)

    validate_error(
        api.revoke_consent_record(
            consent["id"], revoke_consent_payload(), RESEARCHER_HEADERS
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.revoke_consent_record(
            consent["id"], revoke_consent_payload(), RESEARCH_OPS_ADMIN_HEADERS
        ),
        "ERR_UNAUTHORIZED",
    )

    after = read_consent(consent["id"], api)
    assert after["status"] == "GRANTED", (
        f"Expected the consent record to stay GRANTED, got {after['status']}"
    )
    assert after["revoked_at"] is None, (
        f"Expected revoked_at to stay null, got {after['revoked_at']!r}"
    )
    assert after["version"] == consent["version"], (
        f"Expected the consent version to stay {consent['version']}, "
        f"got {after['version']}"
    )


# ===========================================================================
# Researcher and ResearchLead share the authoring surface
# ===========================================================================
def test_both_authoring_roles_can_create_and_read_each_others_themes(api):
    """Theme creation is open to both authoring roles and neither read is narrowed.

    PRD 3.7: "A `Researcher` or `ResearchLead` creates one with a `label` that must
    be non-empty and unique across every theme in the repository — a collision is
    refused with `ERR_DUPLICATE_LABEL` — and optionally a `parent_theme_id` naming
    the theme it nests under."

    PRD 2.1: "`ResearchLead` — triages intake, approves moderator guides and
    publishes findings. A `ResearchLead` may also author findings, which is exactly
    why publication carries a separate author check."

    Design: Corner/rbac/researcher_and_research_lead_share_the_authoring_surface
    """
    by_researcher = validate_success(
        api.create_theme(
            create_theme_payload(label="Navigation friction"), RESEARCHER_HEADERS
        ),
        201,
    )
    by_lead = validate_success(
        api.create_theme(
            create_theme_payload(label="Checkout drop-off"), RESEARCH_LEAD_HEADERS
        ),
        201,
    )

    for theme in (by_researcher, by_lead):
        assert theme["status"] == "EMERGING", (
            f"Expected a fresh theme to open EMERGING, got {theme['status']}"
        )
        assert theme["version"] == 1, (
            f"Expected a fresh theme at version 1, got {theme['version']}"
        )

    cross_read_by_lead = validate_success(
        api.get_theme(by_researcher["id"], RESEARCH_LEAD_HEADERS), 200
    )
    cross_read_by_researcher = validate_success(
        api.get_theme(by_lead["id"], RESEARCHER_HEADERS), 200
    )
    assert cross_read_by_lead["label"] == "Navigation friction", (
        "Expected a ResearchLead to read a theme a Researcher created"
    )
    assert cross_read_by_researcher["label"] == "Checkout drop-off", (
        "Expected a Researcher to read a theme a ResearchLead created"
    )

    rows, meta = validate_paginated(api.list_themes(RESEARCH_LEAD_HEADERS))
    assert meta["total_count"] == 2, (
        f"Expected both themes in the shared index, got {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {by_researcher["id"], by_lead["id"]}, (
        "Expected the index to hold exactly the two authored themes"
    )


def test_either_authoring_role_can_draft_and_lock_a_finding(api):
    """Both roles author findings, and either may lock a finding the other authored.

    PRD 3.7: "Locking a finding is how a `Researcher` or `ResearchLead` declares its
    evidence set final, carrying it `DRAFT → EVIDENCE_LOCKED`."

    PRD 3.7: "The finding opens in `status` `DRAFT` with `strength_variant`
    `PROVISIONAL`, `evidence_strength` 0.00, `admissible_link_count` and
    `distinct_participant_count` at 0, `retraction_reason` and `published_at` null,
    and `authored_by_user_id` set to the creating operator's `X-User-ID`."

    Design: Corner/rbac/researcher_and_research_lead_share_the_authoring_surface
    """
    ctx = setup_study_in_analysis(api)
    study_id = ctx["study"]["id"]
    artifact_ids = [artifact["id"] for artifact in ctx["artifacts"]]
    theme = create_theme(api, label="Navigation friction")

    by_researcher = create_finding(
        study_id,
        theme["id"],
        api,
        headers=RESEARCHER_HEADERS,
        statement="Power users lose their place after a filter reset",
    )
    by_lead = create_finding(
        study_id,
        theme["id"],
        api,
        headers=RESEARCH_LEAD_HEADERS,
        statement="Power users expect the filter bar to persist",
    )

    assert by_researcher["authored_by_user_id"] == "u_res_1", (
        f"Expected the Researcher's X-User-ID on the authored finding, "
        f"got {by_researcher['authored_by_user_id']!r}"
    )
    assert by_lead["authored_by_user_id"] == "u_lead_1", (
        f"Expected the ResearchLead's X-User-ID on the authored finding, "
        f"got {by_lead['authored_by_user_id']!r}"
    )
    for finding in (by_researcher, by_lead):
        assert finding["status"] == "DRAFT", (
            f"Expected a fresh finding to open DRAFT, got {finding['status']}"
        )
        assert finding["strength_variant"] == "PROVISIONAL", (
            f"Expected the provisional variant at creation, "
            f"got {finding['strength_variant']}"
        )

    for finding in (by_researcher, by_lead):
        for artifact_id in artifact_ids:
            link_evidence(
                finding["id"], artifact_id, api, weight_class="DIRECT_QUOTE"
            )

    locked_by_lead = validate_success(
        api.lock_finding(by_researcher["id"], RESEARCH_LEAD_HEADERS), 200
    )
    locked_by_researcher = validate_success(
        api.lock_finding(by_lead["id"], RESEARCHER_HEADERS), 200
    )
    assert locked_by_lead["status"] == "EVIDENCE_LOCKED", (
        f"Expected a ResearchLead to lock a Researcher's finding, "
        f"got {locked_by_lead['status']}"
    )
    assert locked_by_researcher["status"] == "EVIDENCE_LOCKED", (
        f"Expected a Researcher to lock a ResearchLead's finding, "
        f"got {locked_by_researcher['status']}"
    )


# ===========================================================================
# Publication is refused to the finding's own author
# ===========================================================================
def test_a_research_lead_cannot_publish_the_finding_they_authored(api):
    """The author is refused even though their role is entitled to publish.

    PRD 2.1: "Separately, publishing a finding requires that `X-User-ID` **differ**
    from the finding's `authored_by_user_id`; if they are equal the request is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD 3.7: "The publisher's `X-User-ID` must differ from the finding's
    `authored_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — and since a
    `ResearchLead` is entitled to author findings, this is a live constraint rather
    than a formality."

    Design: Corner/rbac/author_cannot_publish_their_own_finding
    """
    ctx = setup_study_in_analysis(api)
    theme = create_theme(api, label="Navigation friction")
    finding = create_finding(
        ctx["study"]["id"], theme["id"], api, headers=RESEARCH_LEAD_HEADERS
    )
    for artifact in ctx["artifacts"]:
        link_evidence(finding["id"], artifact["id"], api, weight_class="DIRECT_QUOTE")
    locked = lock_finding(finding["id"], api)
    assert locked["authored_by_user_id"] == "u_lead_1", (
        f"Expected the ResearchLead to be recorded as author, "
        f"got {locked['authored_by_user_id']!r}"
    )
    assert float(locked["evidence_strength"]) == pytest.approx(0.60, abs=0.01), (
        f"Expected a corroborated strength of 0.60, clear of the publish floor, "
        f"got {locked['evidence_strength']}"
    )

    refused = api.publish_finding(finding["id"], RESEARCH_LEAD_HEADERS)
    validate_error(refused, "ERR_SEGREGATION_OF_DUTIES")

    unchanged = read_finding(finding["id"], api)
    assert unchanged["status"] == "EVIDENCE_LOCKED", (
        f"Expected the finding to stay EVIDENCE_LOCKED, got {unchanged['status']}"
    )
    assert unchanged["published_at"] is None, (
        f"Expected published_at to stay null, got {unchanged['published_at']!r}"
    )
    assert unchanged["version"] == locked["version"], (
        f"Expected the refused publication to leave version at "
        f"{locked['version']}, got {unchanged['version']}"
    )

    theme_after_refusal = read_theme(theme["id"], api)
    assert float(theme_after_refusal["evidence_weight"]) == pytest.approx(
        0.00, abs=0.01
    ), (
        f"Expected no theme weight from an unpublished finding, "
        f"got {theme_after_refusal['evidence_weight']}"
    )


def test_a_second_entitled_operator_publishes_the_same_finding(api):
    """A different accepted publisher carries the very finding the author could not.

    PRD 3.7: "On success `published_at` is set to the current logical clock instant
    and the theme weights are recomputed for the finding's theme and every ancestor
    of it."

    PRD 3.7: "A theme's `own_evidence_weight` is the sum, over every `PUBLISHED`
    finding whose `theme_id` is that theme, of the finding's `evidence_strength`
    multiplied by its severity multiplier — 1.50 for `HIGH`, 1.00 for `MEDIUM`, 0.60
    for `LOW` — with each per-finding term rounded half-up to two decimals before it
    enters the sum."

    Design: Corner/rbac/author_cannot_publish_their_own_finding
    """
    ctx = setup_study_in_analysis(api)
    theme = create_theme(api, label="Navigation friction")
    finding = create_finding(
        ctx["study"]["id"], theme["id"], api, headers=RESEARCH_LEAD_HEADERS
    )
    for artifact in ctx["artifacts"]:
        link_evidence(finding["id"], artifact["id"], api, weight_class="DIRECT_QUOTE")
    locked = lock_finding(finding["id"], api)

    validate_error(
        api.publish_finding(finding["id"], RESEARCH_LEAD_HEADERS),
        "ERR_SEGREGATION_OF_DUTIES",
    )

    published = validate_success(
        api.publish_finding(finding["id"], RESEARCH_OPS_ADMIN_HEADERS), 200
    )
    assert published["status"] == "PUBLISHED", (
        f"Expected a different entitled operator to publish the finding, "
        f"got {published['status']}"
    )
    assert published["published_at"] == "2026-08-01T00:00:00.000Z", (
        f"Expected published_at to be stamped from the logical clock, "
        f"got {published['published_at']!r}"
    )
    assert published["authored_by_user_id"] == "u_lead_1", (
        "Expected publication to leave the recorded author alone"
    )
    assert published["version"] == locked["version"] + 1, (
        f"Expected publication to advance version from {locked['version']} to "
        f"{locked['version'] + 1}, got {published['version']}"
    )

    theme_after = read_theme(theme["id"], api)
    assert float(theme_after["own_evidence_weight"]) == pytest.approx(0.60, abs=0.01), (
        f"Expected 0.60 strength times the MEDIUM multiplier 1.00, "
        f"got {theme_after['own_evidence_weight']}"
    )
    assert float(theme_after["evidence_weight"]) == pytest.approx(0.60, abs=0.01), (
        f"Expected the rolled-up weight to equal the own weight, "
        f"got {theme_after['evidence_weight']}"
    )
    assert theme_after["status"] == "EMERGING", (
        f"Expected 0.60 to stay below the 1.20 established threshold, "
        f"got {theme_after['status']}"
    )


# ===========================================================================
# The echoed study version on readout drafting
# ===========================================================================
def test_a_stale_expected_study_version_rejects_the_readout_draft(api):
    """Only the study's exact current `version` is accepted; neighbours are 412s.

    PRD 2.9: "Drafting a readout against a study requires `expected_study_version`
    in the request body, carrying the client's last observed `version` of the target
    `Study`."

    PRD 2.9: "If that value does not equal the study's current `version`, the
    request is rejected with `ERR_STALE_STUDY_VERSION` (HTTP 412) and nothing is
    created."

    Design: Corner/cross_cutting_layers/stale_expected_study_version_on_readout_create_returns_conflict
    """
    ctx = setup_guide_approved_study(api)
    study_id = ctx["study"]["id"]
    theme = create_theme(api, label="Navigation friction")
    finding = create_finding(study_id, theme["id"], api)

    current = read_study(study_id, api)["version"]

    for stale in (current - 1, current + 1):
        refused = api.create_readout(
            study_id,
            create_readout_payload(ctx["decision"]["id"], [finding["id"]], stale),
            RESEARCHER_HEADERS,
        )
        validate_error(refused, "ERR_STALE_STUDY_VERSION")

    rows, meta = validate_paginated(
        api.list_readouts(RESEARCHER_HEADERS, {"study_id": study_id})
    )
    assert meta["total_count"] == 0, (
        f"Expected the two refused drafts to have created nothing, "
        f"got total_count {meta['total_count']}"
    )
    assert rows == [], f"Expected no readouts, got {len(rows)} rows"
    assert read_study(study_id, api)["version"] == current, (
        f"Expected the refused drafts to leave the study at version {current}"
    )


def test_the_matching_study_version_drafts_once_and_then_goes_stale(api):
    """The accepted draft advances the study, so replaying the same number is a 412.

    PRD 2.9: "On success the study's `version` is incremented by 1, which means a
    client that drafts two readouts in sequence must re-read the study between
    them."

    PRD 3.8: "A successful draft opens in `status` `DRAFT` with `delivered_at`,
    `responded_at`, `response_note`, `decision_confidence_before` and
    `decision_confidence_after` all null, and it increments the target study's
    `version` by 1."

    Design: Corner/cross_cutting_layers/stale_expected_study_version_on_readout_create_returns_conflict
    """
    ctx = setup_guide_approved_study(api)
    study_id = ctx["study"]["id"]
    theme = create_theme(api, label="Navigation friction")
    finding = create_finding(study_id, theme["id"], api)
    current = read_study(study_id, api)["version"]

    payload = create_readout_payload(ctx["decision"]["id"], [finding["id"]], current)
    readout = validate_success(
        api.create_readout(study_id, payload, RESEARCHER_HEADERS), 201
    )
    assert readout["status"] == "DRAFT", (
        f"Expected the draft to open DRAFT, got {readout['status']}"
    )
    assert readout["delivered_at"] is None, (
        f"Expected delivered_at null on a fresh draft, got {readout['delivered_at']!r}"
    )
    assert readout["responded_at"] is None, (
        f"Expected responded_at null on a fresh draft, got {readout['responded_at']!r}"
    )
    assert readout["response_note"] is None, (
        f"Expected response_note null on a fresh draft, "
        f"got {readout['response_note']!r}"
    )
    assert readout["decision_confidence_before"] is None, (
        f"Expected decision_confidence_before null on a fresh draft, "
        f"got {readout['decision_confidence_before']!r}"
    )
    assert readout["decision_confidence_after"] is None, (
        f"Expected decision_confidence_after null on a fresh draft, "
        f"got {readout['decision_confidence_after']!r}"
    )

    after_draft = read_study(study_id, api)["version"]
    assert after_draft == current + 1, (
        f"Expected the draft to advance the study from {current} to {current + 1}, "
        f"got {after_draft}"
    )

    replay = api.create_readout(study_id, payload, RESEARCHER_HEADERS)
    validate_error(replay, "ERR_STALE_STUDY_VERSION")

    rows, meta = validate_paginated(
        api.list_readouts(RESEARCHER_HEADERS, {"study_id": study_id})
    )
    assert meta["total_count"] == 1, (
        f"Expected exactly the one accepted readout, "
        f"got total_count {meta['total_count']}"
    )
    assert rows[0]["id"] == readout["id"], (
        "Expected the accepted readout to be the only row"
    )
    assert read_study(study_id, api)["version"] == current + 1, (
        "Expected the replayed draft to leave the study version alone"
    )


# ===========================================================================
# The echoed pool version on settlement
# ===========================================================================
def test_a_stale_expected_pool_version_moves_no_money(api):
    """A settlement quoting the wrong pool `version` is a 412 and the ledger holds.

    PRD 2.9: "Running an incentive settlement against a participant pool requires
    `expected_pool_version` in the request body, carrying the client's last observed
    `version` of the target `ParticipantPool`."

    PRD 2.9: "A mismatch with the pool's current `version` is rejected with
    `ERR_STALE_POOL_VERSION` (HTTP 412) and no money moves."

    Design: Corner/cross_cutting_layers/stale_expected_pool_version_on_settlement_returns_conflict
    """
    ctx = setup_invited_recruitments(
        api,
        participant_count=1,
        invite_count=1,
        pool_overrides={"incentive_budget_cents": 100000},
    )
    pool_id = ctx["pool"]["id"]
    study_id = ctx["study"]["id"]
    before = read_pool(pool_id, api)
    assert before["incentive_reserved_cents"] == 5000, (
        f"Expected one invitation to have reserved 5000 cents, "
        f"got {before['incentive_reserved_cents']}"
    )

    refused = api.create_incentive_settlement(
        pool_id,
        create_incentive_settlement_payload(
            study_id, "FORWARD_ESTIMATE", before["version"] - 1
        ),
        RESEARCH_OPS_ADMIN_HEADERS,
    )
    validate_error(refused, "ERR_STALE_POOL_VERSION")

    unchanged = read_pool(pool_id, api)
    assert unchanged["version"] == before["version"], (
        f"Expected the pool to stay at version {before['version']}, "
        f"got {unchanged['version']}"
    )
    assert unchanged["incentive_reserved_cents"] == 5000, (
        f"Expected reserved cents untouched at 5000, "
        f"got {unchanged['incentive_reserved_cents']}"
    )
    assert unchanged["incentive_paid_cents"] == 0, (
        f"Expected paid cents untouched at 0, got {unchanged['incentive_paid_cents']}"
    )
    assert unchanged["incentive_available_cents"] == 95000, (
        f"Expected available cents untouched at 95000, "
        f"got {unchanged['incentive_available_cents']}"
    )
    assert unchanged["last_estimate_cents"] is None, (
        f"Expected no advisory estimate to have been written, "
        f"got {unchanged['last_estimate_cents']!r}"
    )


def test_the_matching_pool_version_settles_once_and_then_goes_stale(api):
    """The accepted estimate advances the pool, so the same number replays as a 412.

    PRD 2.9: "A successful settlement increments the pool's `version` by 1."

    PRD 3.9: "The estimate is the plain sum of those rows' `reserved_cents` — the
    assumption being that every open recruitment completes at its full reserved
    amount."

    PRD 3.9: "The figure is written to the pool's `last_estimate_cents` and **no
    recruitment row is mutated**."

    Design: Corner/cross_cutting_layers/stale_expected_pool_version_on_settlement_returns_conflict
    """
    ctx = setup_invited_recruitments(
        api,
        participant_count=1,
        invite_count=1,
        pool_overrides={"incentive_budget_cents": 100000},
    )
    pool_id = ctx["pool"]["id"]
    study_id = ctx["study"]["id"]
    recruitment_id = ctx["recruitments"][0]["id"]
    pool_version = read_pool(pool_id, api)["version"]

    payload = create_incentive_settlement_payload(
        study_id, "FORWARD_ESTIMATE", pool_version
    )
    validate_success(
        api.create_incentive_settlement(pool_id, payload, RESEARCH_OPS_ADMIN_HEADERS),
        200,
    )

    settled = read_pool(pool_id, api)
    assert settled["version"] == pool_version + 1, (
        f"Expected the settlement to advance the pool from {pool_version} to "
        f"{pool_version + 1}, got {settled['version']}"
    )
    assert settled["last_estimate_cents"] == 5000, (
        f"Expected the advisory estimate to be the single reservation of 5000, "
        f"got {settled['last_estimate_cents']}"
    )
    assert settled["incentive_paid_cents"] == 0, (
        f"Expected the advisory run to move no money, "
        f"got {settled['incentive_paid_cents']}"
    )
    assert settled["incentive_reserved_cents"] == 5000, (
        f"Expected reserved cents to stay 5000, "
        f"got {settled['incentive_reserved_cents']}"
    )
    assert settled["settled_study_ids"] == [], (
        f"Expected an advisory run to leave settled_study_ids empty, "
        f"got {settled['settled_study_ids']}"
    )
    assert settled["status"] == "OPEN", (
        f"Expected a utilization of 0.05 to leave the pool OPEN, "
        f"got {settled['status']}"
    )

    recruitment = read_recruitment(recruitment_id, api)
    assert recruitment["incentive_state"] == "RESERVED", (
        f"Expected the recruitment row untouched at RESERVED, "
        f"got {recruitment['incentive_state']}"
    )
    assert recruitment["paid_cents"] == 0, (
        f"Expected paid_cents to stay 0 on the recruitment, "
        f"got {recruitment['paid_cents']}"
    )

    replay = api.create_incentive_settlement(
        pool_id, payload, RESEARCH_OPS_ADMIN_HEADERS
    )
    validate_error(replay, "ERR_STALE_POOL_VERSION")
    assert read_pool(pool_id, api)["version"] == pool_version + 1, (
        "Expected the replayed settlement to leave the pool version alone"
    )


# ===========================================================================
# Every mutation advances the row's own version counter
# ===========================================================================
def test_the_study_version_ladder_climbs_one_step_per_mutation(api):
    """Creation, guide write, approval and fielding read 1, 2, 3 and 4 in turn.

    PRD 2.4: "`version` is an integer that starts at 1 when the resource is created
    and increments by exactly 1 on every mutation."

    PRD 3.3: "On success the study is stamped with `lead_user_id` taken from the
    creating operator's `X-User-ID`, opens with `execution_status` `PLANNED` and
    `recruitment_status` `NOT_STARTED`, has `guide_status` `NONE` with
    `guide_version_label`, `guide_question_count` and `guide_version_pinned` all
    null, has `invited_count`, `screened_in_count` and `completed_count` at 0 and
    `fielded_at` and `fielding_closed_at` null — and it drags its request from
    `APPROVED` to `IN_STUDY`."

    PRD 3.3: "Every write sets `guide_status` to `DRAFT` and clears
    `guide_version_pinned` back to null — including a rewrite of a guide that had
    already been approved, which is exactly the point: a rewritten guide is an
    unapproved guide."

    Design: Corner/cross_cutting_layers/every_mutation_increments_the_entity_version
    """
    intake = setup_approved_request(api, method="INTERVIEW")
    pool = create_pool(api)

    created = validate_success(
        api.create_study(
            create_study_payload(intake["request"]["id"], pool["id"]),
            RESEARCHER_HEADERS,
        ),
        201,
    )
    assert created["version"] == 1, (
        f"Expected a freshly opened study at version 1, got {created['version']}"
    )
    assert created["execution_status"] == "PLANNED", (
        f"Expected the study to open PLANNED, got {created['execution_status']}"
    )
    assert created["recruitment_status"] == "NOT_STARTED", (
        f"Expected the recruitment dimension to open NOT_STARTED, "
        f"got {created['recruitment_status']}"
    )
    assert created["guide_status"] == "NONE", (
        f"Expected a study with no guide to read NONE, got {created['guide_status']}"
    )
    study_id = created["id"]

    read_without_mutation = validate_success(
        api.get_study(study_id, RESEARCHER_HEADERS), 200
    )
    assert read_without_mutation["version"] == 1, (
        f"Expected a read to leave the version at 1, "
        f"got {read_without_mutation['version']}"
    )

    after_guide = validate_success(
        api.write_study_guide(study_id, study_guide_payload(), RESEARCHER_HEADERS), 200
    )
    assert after_guide["version"] == 2, (
        f"Expected the guide write to advance the version to 2, "
        f"got {after_guide['version']}"
    )
    assert after_guide["guide_status"] == "DRAFT", (
        f"Expected a written guide to read DRAFT, got {after_guide['guide_status']}"
    )
    assert after_guide["guide_version_pinned"] is None, (
        f"Expected the guide write to leave the pin null, "
        f"got {after_guide['guide_version_pinned']!r}"
    )

    after_approval = validate_success(
        api.approve_study_guide(study_id, RESEARCH_LEAD_HEADERS), 200
    )
    assert after_approval["version"] == 3, (
        f"Expected approval to advance the version to 3, "
        f"got {after_approval['version']}"
    )
    assert after_approval["guide_status"] == "APPROVED", (
        f"Expected approval to set guide_status APPROVED, "
        f"got {after_approval['guide_status']}"
    )
    assert after_approval["guide_version_pinned"] == "G1", (
        f"Expected approval to pin the guide label, "
        f"got {after_approval['guide_version_pinned']!r}"
    )
    assert after_approval["execution_status"] == "GUIDE_APPROVED", (
        f"Expected approval to carry the study to GUIDE_APPROVED, "
        f"got {after_approval['execution_status']}"
    )

    after_fielding = validate_success(
        api.field_study(study_id, RESEARCHER_HEADERS), 200
    )
    assert after_fielding["version"] == 4, (
        f"Expected fielding to advance the version to 4, "
        f"got {after_fielding['version']}"
    )
    assert after_fielding["execution_status"] == "FIELDING", (
        f"Expected fielding to carry the study to FIELDING, "
        f"got {after_fielding['execution_status']}"
    )
    assert after_fielding["recruitment_status"] == "NOT_STARTED", (
        f"Expected fielding to leave the recruitment dimension NOT_STARTED, "
        f"got {after_fielding['recruitment_status']}"
    )
    assert after_fielding["fielded_at"] == "2026-08-01T00:00:00.000Z", (
        f"Expected fielded_at stamped from the logical clock, "
        f"got {after_fielding['fielded_at']!r}"
    )

    final_read = read_study(study_id, api)
    assert final_read["version"] == 4, (
        f"Expected the final read to still show version 4, got {final_read['version']}"
    )


def test_untouched_neighbours_keep_their_own_version_counters(api):
    """Four mutations of the study leave the pool's own counter exactly where it was.

    PRD 2.4: "`version` is an integer that starts at 1 when the resource is created
    and increments by exactly 1 on every mutation."

    PRD 2.4: "A mutation here means any change the platform makes to the row,
    whether the client asked for it directly or a cascade produced it: when a no-show
    forfeits a reservation and the pool's ledger fields move as a consequence, the
    pool's own `version` and `updated_at` advance too."

    Design: Corner/cross_cutting_layers/every_mutation_increments_the_entity_version
    """
    intake = setup_approved_request(api, method="INTERVIEW")
    pool = create_pool(api)
    assert pool["version"] == 1, (
        f"Expected a freshly created pool at version 1, got {pool['version']}"
    )

    study = validate_success(
        api.create_study(
            create_study_payload(intake["request"]["id"], pool["id"]),
            RESEARCHER_HEADERS,
        ),
        201,
    )
    api.write_study_guide(study["id"], study_guide_payload(), RESEARCHER_HEADERS)
    api.approve_study_guide(study["id"], RESEARCH_LEAD_HEADERS)
    api.field_study(study["id"], RESEARCHER_HEADERS)

    assert read_study(study["id"], api)["version"] == 4, (
        "Expected the four study mutations to land on version 4"
    )
    pool_after = read_pool(pool["id"], api)
    assert pool_after["version"] == 1, (
        f"Expected the pool's own version to stay 1 while no ledger field moved, "
        f"got {pool_after['version']}"
    )
    assert pool_after["incentive_reserved_cents"] == 0, (
        f"Expected no money reserved yet, "
        f"got {pool_after['incentive_reserved_cents']}"
    )


# ===========================================================================
# Derived fields are visible in the response that produced them
# ===========================================================================
def test_an_invitation_returns_its_reservation_and_the_pool_ledger_is_current(api):
    """`reserved_cents` and the pool's re-derived ledger are readable immediately.

    PRD 2.11: "Each is recomputed by a named rule at the moments §3 specifies,
    stored on the row, and returned by reads."

    PRD 3.4: "A successful invitation writes a recruitment in `status` `INVITED`
    with `incentive_state` `RESERVED` and its `reserved_cents` stored, sets
    `screen_score`, `scheduled_start`, `scheduled_end`, `moderator_user_id`,
    `actual_duration_min` and `closure_reason` to null with `reschedule_count` at 0
    and `paid_cents` at 0, and copies the study's `guide_version_pinned` onto the
    recruitment's own `guide_version_pinned` so the session is forever tied to the
    guide version that was in force."

    PRD 3.4: "Otherwise the pool's `incentive_reserved_cents` rises by exactly
    `reserved_cents` and `incentive_available_cents` is re-derived as budget minus
    reserved minus paid, keeping the ledger partition of §2.10 intact."

    Design: Corner/consistency_model/computed_fields_are_visible_in_the_same_response
    """
    ctx = setup_fielding_study(
        api,
        participant_count=1,
        pool_overrides={"incentive_budget_cents": 100000},
    )

    recruitment = validate_success(
        api.create_recruitment(
            ctx["study"]["id"],
            create_recruitment_payload(ctx["participants"][0]["id"]),
            RESEARCHER_HEADERS,
        ),
        201,
    )
    assert recruitment["status"] == "INVITED", (
        f"Expected the invitation to open INVITED, got {recruitment['status']}"
    )
    assert recruitment["incentive_state"] == "RESERVED", (
        f"Expected the money to open RESERVED, got {recruitment['incentive_state']}"
    )
    assert recruitment["reserved_cents"] == 5000, (
        f"Expected an unstressed pool to reserve the base 5000 cents, "
        f"got {recruitment['reserved_cents']}"
    )
    assert recruitment["screen_score"] is None, (
        f"Expected screen_score null before screening, "
        f"got {recruitment['screen_score']!r}"
    )
    assert recruitment["paid_cents"] == 0, (
        f"Expected paid_cents 0 at invitation, got {recruitment['paid_cents']}"
    )

    pool = read_pool(ctx["pool"]["id"], api)
    assert pool["incentive_reserved_cents"] == 5000, (
        f"Expected the pool ledger to already show 5000 reserved, "
        f"got {pool['incentive_reserved_cents']}"
    )
    assert pool["incentive_available_cents"] == 95000, (
        f"Expected available cents re-derived to 95000, "
        f"got {pool['incentive_available_cents']}"
    )
    assert pool["participant_count"] == 1, (
        f"Expected the enrolled participant counted, got {pool['participant_count']}"
    )
    assert pool["status"] == "OPEN", (
        f"Expected a utilization of 0.05 to leave the pool OPEN, "
        f"got {pool['status']}"
    )

    study = read_study(ctx["study"]["id"], api)
    assert study["invited_count"] == 1, (
        f"Expected invited_count recomputed to 1, got {study['invited_count']}"
    )
    assert study["recruitment_status"] == "RECRUITING", (
        f"Expected the first invitation to open recruiting, "
        f"got {study['recruitment_status']}"
    )


def test_screening_returns_the_score_it_just_computed(api):
    """`screen_score` and the admission verdict arrive in the screening response.

    PRD 3.5: "A submitted `segment` exactly equal to the rubric's
    `required_segment` earns 40.0 points, and nothing otherwise."

    PRD 3.5: "A submitted `locale` exactly equal to `required_locale` earns 20.0
    points, and nothing otherwise."

    PRD 3.5: "Each element of the submitted `answers` array that appears in the
    rubric's `target_answers` counts as one hit; multiply the number of hits by 15.0
    and hold the result at a ceiling of 40.0 points — so one hit earns 15.0, two earn
    30.0, and three or more all earn the capped 40.0."

    PRD 3.5: "A score of at least 60.00 carries the recruitment `INVITED →
    SCREENED_IN`; anything below — including the 0.00 produced by the
    disqualifying-answer gate — carries it `INVITED → SCREENED_OUT`, which is
    terminal."

    Design: Corner/consistency_model/computed_fields_are_visible_in_the_same_response
    """
    ctx = setup_invited_recruitments(api, participant_count=1, invite_count=1)
    recruitment_id = ctx["recruitments"][0]["id"]

    screened = validate_success(
        api.screen_recruitment(recruitment_id, RESEARCHER_HEADERS), 200
    )
    assert float(screened["screen_score"]) == pytest.approx(90.00, abs=0.01), (
        f"Expected 40.0 for segment plus 20.0 for locale plus 30.0 for two target "
        f"hits, got {screened['screen_score']}"
    )
    assert screened["status"] == "SCREENED_IN", (
        f"Expected 90.00 to clear the 60.00 threshold, got {screened['status']}"
    )
    assert screened["incentive_state"] == "RESERVED", (
        f"Expected screening to leave the money alone, "
        f"got {screened['incentive_state']}"
    )

    study = read_study(ctx["study"]["id"], api)
    assert study["screened_in_count"] == 1, (
        f"Expected screened_in_count recomputed to 1 in the same request, "
        f"got {study['screened_in_count']}"
    )


def test_a_finding_and_its_first_link_report_their_derived_counters_at_once(api):
    """Creation returns the empty rollup and the link returns its own contribution.

    PRD 3.7: "The finding opens in `status` `DRAFT` with `strength_variant`
    `PROVISIONAL`, `evidence_strength` 0.00, `admissible_link_count` and
    `distinct_participant_count` at 0, `retraction_reason` and `published_at` null,
    and `authored_by_user_id` set to the creating operator's `X-User-ID`."

    PRD 3.7: "The new link opens with `is_admissible` true and `inadmissible_reason`
    null."

    PRD 2.11: "A derived field is never left stale behind a mutation that could have
    changed it, and recomputing it counts as a mutation of its row for the purposes
    of `updated_at` and `version` in §2.4."

    Design: Corner/consistency_model/computed_fields_are_visible_in_the_same_response
    """
    ctx = setup_study_in_analysis(api, participant_count=1)
    theme = create_theme(api, label="Navigation friction")

    finding = validate_success(
        api.create_finding(
            {
                "study_id": ctx["study"]["id"],
                "theme_id": theme["id"],
                "statement": "Power users rebuild the same filters every Monday.",
                "severity": "MEDIUM",
            },
            RESEARCHER_HEADERS,
        ),
        201,
    )
    assert float(finding["evidence_strength"]) == pytest.approx(0.00, abs=0.01), (
        f"Expected a linkless finding to score 0.00, "
        f"got {finding['evidence_strength']}"
    )
    assert finding["strength_variant"] == "PROVISIONAL", (
        f"Expected the provisional variant at creation, "
        f"got {finding['strength_variant']}"
    )
    assert finding["admissible_link_count"] == 0, (
        f"Expected no admissible links yet, got {finding['admissible_link_count']}"
    )
    assert finding["distinct_participant_count"] == 0, (
        f"Expected no participants reached yet, "
        f"got {finding['distinct_participant_count']}"
    )

    link = validate_success(
        api.create_evidence_link(
            finding["id"],
            {
                "artifact_id": ctx["artifacts"][0]["id"],
                "excerpt_ref": "00:12:30",
                "weight_class": "DIRECT_QUOTE",
            },
            RESEARCHER_HEADERS,
        ),
        201,
    )
    assert float(link["contribution"]) == pytest.approx(1.00, abs=0.01), (
        f"Expected DIRECT_QUOTE 1.00 times the INTERVIEW multiplier 1.00, "
        f"got {link['contribution']}"
    )
    assert link["is_admissible"] is True, (
        "Expected a fresh link to open admissible"
    )
    assert link["inadmissible_reason"] is None, (
        f"Expected inadmissible_reason null on a fresh link, "
        f"got {link['inadmissible_reason']!r}"
    )

    rescored = read_finding(finding["id"], api)
    assert float(rescored["evidence_strength"]) == pytest.approx(0.25, abs=0.01), (
        f"Expected a raw total of 1.00 over the 4.00 provisional divisor, "
        f"got {rescored['evidence_strength']}"
    )
    assert rescored["admissible_link_count"] == 1, (
        f"Expected the link counted immediately, "
        f"got {rescored['admissible_link_count']}"
    )
    assert rescored["distinct_participant_count"] == 1, (
        f"Expected the one reachable participant counted immediately, "
        f"got {rescored['distinct_participant_count']}"
    )
    assert rescored["version"] > finding["version"], (
        f"Expected the rescore to advance the finding's version beyond "
        f"{finding['version']}, got {rescored['version']}"
    )
