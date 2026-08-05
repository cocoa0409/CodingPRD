"""Header authentication, episode ownership and the visit-documentation
optimistic-concurrency guard."""
from test_helpers import (
    CLINICIAN,
    HIGH_REQUIRED_ELEMENTS,
    MODERATE_REQUIRED_ELEMENTS,
    ApiErrorId,
    add_navigator,
    complete_visit,
    connect_contact,
    make_care_navigator_headers,
    read_episode,
    read_visit,
    setup_completed_medrec,
    setup_confirmed_visit,
    setup_program_with_episode,
    validate_error,
    validate_success,
)

NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def test_missing_auth_headers_are_rejected_before_body_validation(api):
    """PRD §2.1: "Every request to this API — including every read — must carry
    two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`,
    naming the role that user is acting under. If either header is absent or
    present but empty, the request is rejected with `ERR_UNAUTHENTICATED` and
    HTTP 401, before any other check runs."

    Design: Corner/rbac/missing_auth_headers_return_unauthenticated
    """
    resp = api.create_patient({}, NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_VALIDATION.value


def test_navigator_cannot_act_on_another_navigators_episode(api):
    """PRD §2.1: "When `X-User-Role` is `CareNavigator`, `X-User-ID` is the `id`
    of the acting `Navigator` row; ownership checks on any resource that hangs
    off a `CareEpisode` compare that episode's `navigator_id` to `X-User-ID`,
    and a mismatch is rejected with `ERR_NOT_EPISODE_OWNER` and HTTP 403."
    PRD §2.10: "When the acting role is `CareNavigator`, `X-User-ID` equals the
    `navigator_id` of the care episode that owns the target resource — otherwise
    `ERR_NOT_EPISODE_OWNER` (403). This rung guards exactly ten mutating
    operations: creating a risk re-assessment, logging a contact attempt,
    recording a contact-attempt disposition, booking a visit, confirming a
    visit, closing a visit encounter, rescheduling a visit, raising a barrier,
    raising a red flag, and proposing a handoff."

    Design: Corner/rbac/navigator_cannot_act_on_another_navigators_episode
    """
    ctx, ep = setup_program_with_episode()
    other_navigator, _headers = add_navigator(ctx, full_name="Owen Park")

    validate_error(
        api.log_contact_attempt(
            ep["episode_id"],
            {"modality": "PHONE"},
            make_care_navigator_headers(other_navigator["id"]),
        ),
        ApiErrorId.ERR_NOT_EPISODE_OWNER.value,
    )
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["contact_attempt_count"] == 0
    assert episode["status"] == "INTAKE"


def test_stale_visit_version_rejects_a_second_amendment(api):
    """PRD §2.6: "Amending attested visit documentation requires
    `expected_visit_version` carrying the client's last observed `version` of
    that `TcmVisit`. An amendment replaces the previously attested element set
    outright, so an amendment written from a stale view would discard an
    attestation the writer never read; a mismatch is refused."
    PRD §2.6: "In each case the version field is a **required** part of the
    request body — omitting it is a plain request-validation failure — and in
    each case a value that does not equal the parent's current `version` is
    rejected with `ERR_STALE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_visit_version_rejects_amendment
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    setup_completed_medrec(ctx, ep)
    visit = setup_confirmed_visit(ctx, ep)
    complete_visit(
        ctx, visit["id"], elements=MODERATE_REQUIRED_ELEMENTS, at="2026-05-05T16:00:00Z"
    )
    validate_success(api.attest_visit(visit["id"], CLINICIAN))

    stale_version = read_visit(ctx, visit["id"])["version"]
    validate_success(
        api.amend_visit(
            visit["id"],
            {
                "documented_elements": list(HIGH_REQUIRED_ELEMENTS),
                "expected_visit_version": stale_version,
            },
            CLINICIAN,
        )
    )

    validate_error(
        api.amend_visit(
            visit["id"],
            {
                "documented_elements": ["MED_REC_REVIEWED"],
                "expected_visit_version": stale_version,
            },
            CLINICIAN,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )

    after = read_visit(ctx, visit["id"])
    assert after["amendment_count"] == 1
    assert after["achieved_complexity"] == "HIGH_COMPLEXITY"
    assert after["documentation_status"] == "AMENDED"
    assert sorted(after["documented_elements"]) == sorted(HIGH_REQUIRED_ELEMENTS)
