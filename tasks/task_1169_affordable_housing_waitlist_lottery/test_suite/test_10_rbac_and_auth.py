"""Role-based access control: authentication, exclusive operations,
action-level role mapping, and applicant ownership."""
from test_helpers import (
    ApiErrorId, build_user_headers, fixtures, get_success_data,
    make_applicant_headers, validate_error, validate_paginated,
    validate_success,
)

DEVELOPER = fixtures.DEVELOPER
MARKETING = fixtures.MARKETING
CLERK = fixtures.CLERK
OFFICER = fixtures.OFFICER
AUDITOR = fixtures.AUDITOR

Q2_START = "2026-04-01T00:00:00Z"
Q2_END = "2026-06-30T00:00:00Z"


def test_unrecognized_role_returns_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or does not
    name one of these roles, or whose `X-User-ID` is missing where one is
    required (that is, for any role other than `Anonymous`), is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unrecognized_role_returns_unauthenticated
    """
    fixtures.new_property(api)
    resp = api.create_property(
        fixtures.create_property_payload(),
        build_user_headers("wiz-1", "Wizard"))
    # "Wizard" names no declared role: an authentication failure (401), not
    # an authorization failure.
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_applicant_cannot_create_unit_returns_unauthorized(api):
    """PRD §2.1: "A request whose role is not on the endpoint's authorized
    list, that violates an action-level role mapping, or — for an `Applicant`
    caller — whose `X-User-ID` does not own the addressed resource is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/applicant_cannot_create_unit_returns_unauthorized
    """
    prop = fixtures.new_property(api)
    applicant = fixtures.new_applicant(api, full_name="Cal C",
                                       email="c11@x.com")
    resp = api.create_unit(
        fixtures.create_unit_payload(prop["id"]),
        make_applicant_headers(applicant["id"]))
    # POST /units is HousingDeveloper-exclusive (PRD §4).
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    _, meta = validate_paginated(
        api.list_units(DEVELOPER, params={"property_id": prop["id"]}))
    assert meta["total_count"] == 0, "the unit is not created"


def test_marketing_coordinator_cannot_open_campaign(api):
    """PRD §2.1: "A campaign announcement may only be performed by a
    `MarketingCoordinator`; opening, closing, and reopening a campaign only
    by a `HousingDeveloper`".

    Design: Corner/rbac/marketing_coordinator_cannot_open_campaign
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_campaign(api, prop["id"])
    fixtures.set_clock("2026-06-10T00:00:00Z", api)

    resp = api.transition_campaign(campaign["id"], {"action": "OPEN"},
                                   MARKETING)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    resp2 = api.transition_campaign(campaign["id"], {"action": "ANNOUNCE"},
                                    DEVELOPER)
    validate_error(resp2, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    announced = validate_success(api.transition_campaign(
        campaign["id"], {"action": "ANNOUNCE"}, MARKETING))
    assert announced["status"] == "ANNOUNCED"
    opened = validate_success(api.transition_campaign(
        campaign["id"], {"action": "OPEN"}, DEVELOPER))
    assert opened["status"] == "OPEN"


def test_applicant_cannot_verify_own_claim(api):
    """PRD §2.1: "verifying or denying a preference claim only by an
    `ApplicationClerk`, while appealing a denied claim only by the owning
    `Applicant`".

    Design: Corner/rbac/applicant_cannot_verify_own_claim
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    applicant = fixtures.new_applicant(api, full_name="Dot D",
                                       email="d11@x.com")
    application = fixtures.submit_application(api, campaign["id"],
                                              applicant["id"])
    claim = fixtures.file_claim(api, application["id"], applicant["id"],
                                "LOCAL_RESIDENT", "lease")

    resp = api.transition_preference_claim(
        claim["id"], {"action": "VERIFY"},
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    verified = validate_success(api.transition_preference_claim(
        claim["id"], {"action": "VERIFY"}, CLERK))
    assert verified["status"] == "VERIFIED"


def test_cross_applicant_withdraw_forbidden(api):
    """PRD §2.1: "The `Applicant` role is entity-backed: when `X-User-Role`
    is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` record,
    and every ownership check on a resource that traces back to an applicant
    — an application, a preference claim, an income certification's
    applicant-facing step, a waitlist entry, an offer — compares the
    resource's owning applicant reference to `X-User-ID`."

    Design: Corner/rbac/cross_applicant_withdraw_forbidden
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    applicant_a = fixtures.new_applicant(api, full_name="Eve A",
                                         email="ea@x.com")
    application = fixtures.submit_application(api, campaign["id"],
                                              applicant_a["id"])
    applicant_b = fixtures.new_applicant(api, full_name="Mallory B",
                                         email="mb@x.com")

    resp = api.withdraw_application(
        application["id"], make_applicant_headers(applicant_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    fetched = get_success_data(api.get_application(application["id"], CLERK))
    assert fetched["status"] == "SUBMITTED"


def test_report_role_split_submit_acknowledge(api):
    """PRD §2.1: "submitting a compliance report only by a
    `ComplianceOfficer`, while acknowledging or returning one only by a
    `FundingAgencyAuditor`."

    Design: Corner/rbac/report_role_split_submit_acknowledge
    """
    world = fixtures.setup_leasing_pipeline(api, seed="SEED-RS", num_units=0,
                                            certify=False)
    report = fixtures.new_report(api, world["campaign"]["id"],
                                 period_start=Q2_START, period_end=Q2_END,
                                 period_mode="CALENDAR_QUARTER")

    resp = api.transition_compliance_report(report["id"],
                                            {"action": "SUBMIT"}, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    submitted = validate_success(api.transition_compliance_report(
        report["id"], {"action": "SUBMIT"}, OFFICER))
    assert submitted["status"] == "SUBMITTED"

    resp2 = api.transition_compliance_report(report["id"],
                                             {"action": "ACKNOWLEDGE"},
                                             OFFICER)
    validate_error(resp2, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    acknowledged = validate_success(api.transition_compliance_report(
        report["id"], {"action": "ACKNOWLEDGE"}, AUDITOR))
    assert acknowledged["status"] == "ACKNOWLEDGED"
