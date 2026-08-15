"""Corner queue B tests: missing auth headers, role-permission denials, OCC happy path,
and immediate consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_same_instant,
    consent_application,
    create_applicant,
    create_application,
    create_criteria_payload,
    create_landlord,
    create_landlord_payload,
    get_application,
    get_criteria,
    get_landlord,
    make_applicant_headers,
    make_landlord_headers,
    run_record_searches,
    set_clock,
    setup_landlord_with_criteria,
    submit_application,
    validate_error,
    validate_success,
    verify_identity,
)

ADMIN = TEST_USERS["admin_headers"]
SCREENER = TEST_USERS["screener_headers"]


def test_missing_auth_header_returns_400():
    """PRD §2.1: "All interactions with the API must be authenticated through
    two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, declaring their operational capacity. A request missing
    either header, or presenting a malformed one, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/errors/missing_auth_header_returns_400
    """
    api_client.create_landlord(create_landlord_payload(name="L Auth", contact_email="lauth@x.com"), ADMIN)
    resp = api_client.list_applications({})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_screener_cannot_publish_criteria():
    """PRD §2.6: "2. **Role admission.** The role in `X-User-Role` must be
    admitted on the endpoint per §4, failing with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §4: the criteria publish row admits Landlord only.

    Design: Corner/rbac/screener_cannot_publish_criteria
    """
    landlord = create_landlord(name="L Rbac", contact_email="lrbac@x.com")
    criteria = api_client.create_criteria(
        create_criteria_payload(), make_landlord_headers(landlord["id"])
    ).json()["data"]
    resp = api_client.publish_criteria(
        criteria["id"], {"expected_landlord_version": landlord["version"]}, SCREENER
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert get_criteria(criteria["id"])["status"] == "DRAFT"
    assert get_landlord(landlord["id"])["version"] == 1


def test_applicant_cannot_score_application():
    """PRD §2.6: "2. **Role admission.** The role in `X-User-Role` must be
    admitted on the endpoint per §4, failing with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §4: the score row admits Screener only.

    Design: Corner/rbac/applicant_cannot_score_application
    """
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    consent_application(app, applicant)
    verify_identity(app)
    app = submit_application(app, landlord)
    run_record_searches(app, credit_score=700)
    resp = api_client.score_application(app["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    app_after = get_application(app["id"])
    assert app_after["status"] == "SCREENING"
    assert app_after["recommendation"] is None


def test_publish_increments_landlord_version_and_visible_immediately():
    """PRD §2.8: "because every successful publish advances the landlord's `version` by one,"
    PRD §2.5: "All mutations in the system are atomic and immediately visible: when an operation cascades across several resources — a dispute flips records and its parent report, a suspension cancels a portfolio of applications — every affected resource reflects its new state in the same response cycle,"

    Design: Corner/cross_cutting_complexity_layers/publish_increments_landlord_version_and_visible_immediately
    """
    set_clock()
    landlord = create_landlord(name="L Occ2", contact_email="locc2@x.com")
    criteria = api_client.create_criteria(
        create_criteria_payload(), make_landlord_headers(landlord["id"])
    ).json()["data"]
    resp = api_client.publish_criteria(
        criteria["id"], {"expected_landlord_version": landlord["version"]},
        make_landlord_headers(landlord["id"]),
    )
    data = validate_success(resp)
    assert data["status"] == "PUBLISHED", "visible in the same response, no re-read"
    assert_same_instant(data["published_at"], "2026-08-01T00:00:00Z", "published_at")
    assert get_landlord(landlord["id"])["version"] == 2, "exactly one increment: 1 -> 2"


def test_state_change_visible_in_same_response():
    """PRD §2.5: "All mutations in the system are atomic and immediately
    visible: when an operation cascades across several resources — a dispute
    flips records and its parent report, a suspension cancels a portfolio of
    applications — every affected resource reflects its new state in the same
    response cycle, with each mutated resource refreshing `updated_at` and
    incrementing `version` as described above."

    Design: Corner/consistency_model/state_change_visible_in_same_response
    """
    landlord = create_landlord(name="L Imm", contact_email="limm@x.com")
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    resp = api_client.withdraw_application(app["id"], make_landlord_headers(landlord["id"]))
    data = validate_success(resp)
    assert data["status"] == "WITHDRAWN", "mutation visible in the same response"
    assert data["version"] == 2, "created at 1, withdraw incremented it exactly once"
    assert get_application(app["id"])["status"] == "WITHDRAWN", "subsequent read agrees"
