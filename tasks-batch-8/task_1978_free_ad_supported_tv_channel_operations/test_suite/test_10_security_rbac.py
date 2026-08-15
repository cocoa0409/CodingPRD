"""Authentication context, role authorization, ownership scope, and
segregation of duties (PRD §2.1, §2.10, §3.5, §3.7, §3.8, §4)."""
from test_helpers import (
    api_client,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    factories,
    create_channel,
    create_available_content,
    setup_platform,
    setup_active_agreement,
    setup_provisional_report,
    advance_clock,
    make_distributor_partner_headers,
    make_reviewer_headers,
    make_controller_headers,
    make_analyst_headers,
    get_creative,
    get_report,
)

ADMIN = TEST_USERS["admin_headers"]
PROGRAMMER = TEST_USERS["programmer_headers"]
LICENSING = TEST_USERS["licensing_headers"]
ADOPS = TEST_USERS["adops_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "All interactions with the API must be authenticated through two
    mandatory HTTP headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, specifying their operational capacity. A request missing either
    header, or carrying a role the system does not recognize, is rejected with
    `ERR_MISSING_CONTEXT_HEADER`."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    get_success_data(
        api.create_distributor_platform(
            factories.create_distributor_platform_payload(name="Seed"), ADMIN
        )
    )
    resp = api.list_channels(headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_CONTEXT_HEADER)
    assert resp.status_code == 400


def test_content_licensing_cannot_create_campaign(api):
    """PRD §2.1: "A caller whose role is not in an endpoint's authorized set is
    rejected with `ERR_FORBIDDEN_ROLE`." PRD §4: "| POST | `/v1/ad-campaigns` |
    Create an ad campaign (starts `DRAFT`) | AdOps |".

    Design: Corner/validations/content_licensing_cannot_create_campaign
    """
    resp = api.create_ad_campaign(
        factories.create_ad_campaign_payload(), LICENSING
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.status_code == 403


def test_channel_programmer_cannot_create_rights_grant(api):
    """PRD §2.1: "A caller whose role is not in an endpoint's authorized set is
    rejected with `ERR_FORBIDDEN_ROLE`." PRD §4: "| POST | `/v1/rights-grants` |
    Create a rights grant (starts `PENDING`) | ContentLicensing |".

    Design: Corner/rbac/channel_programmer_cannot_create_rights_grant
    """
    channel = create_channel(name="Ch RB")
    content = create_available_content(runtime_seconds=540, title="M")
    resp = api.create_rights_grant(
        factories.create_rights_grant_payload(channel["id"], content["id"], max_plays=5),
        PROGRAMMER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_adops_cannot_approve_creative(api):
    """PRD §4: "| POST | `/v1/ad-creatives/{creative_id}/approve` | Approve a
    `PENDING_REVIEW` creative | AdQualityReviewer |" and PRD §2.1: "A caller whose
    role is not in an endpoint's authorized set is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/adops_cannot_approve_creative
    """
    campaign = get_success_data(
        api.create_ad_campaign(factories.create_ad_campaign_payload(), ADOPS)
    )
    creative = get_success_data(
        api.create_ad_creative(
            factories.create_ad_creative_payload(campaign["id"]), ADOPS
        )
    )
    resp = api.creative_approve(creative["id"], ADOPS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_creative(creative["id"])["creative_status"] == "PENDING_REVIEW"


def test_finance_analyst_cannot_finalize_report(api):
    """PRD §4: "| POST | `/v1/revenue-reports/{report_id}/finalize` | Finalize a
    `PROVISIONAL` report; computes the final variant | FinanceController |" and PRD
    §2.1: "A caller whose role is not in an endpoint's authorized set is rejected
    with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/finance_analyst_cannot_finalize_report
    """
    ctx = setup_provisional_report(channel_name="Ch FA")
    resp = api.report_finalize(ctx["report"]["id"], make_analyst_headers("fin-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_report(ctx["report"]["id"])["report_status"] == "PROVISIONAL"


def test_partner_cannot_list_viewership_events(api):
    """PRD §3.7: "Events may be listed — by internal roles only: `PlatformAdmin`,
    `ChannelProgrammer`, `AdOps`, `FinanceAnalyst`, and `FinanceController`". The
    DistributorPartner role is absent, so the call is rejected with
    `ERR_FORBIDDEN_ROLE` (PRD §2.1).

    Design: Corner/rbac/partner_cannot_list_viewership_events
    """
    channel = create_channel(name="Ch PV2")
    platform = setup_platform(name="P1", active=False)
    resp = api.list_viewership_events(make_distributor_partner_headers(platform["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.status_code == 403


def test_partner_cannot_ingest_event_for_foreign_platform(api):
    """PRD §2.1: "A partner touching another platform's resource — reading or
    disputing a report whose `platform_id` differs from the caller's id, or
    submitting a viewership event for a different platform — is rejected with
    `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/validations/partner_cannot_ingest_event_for_foreign_platform
    """
    channel = create_channel(name="Ch Own")
    p1 = setup_platform(name="P1", active=False)
    p2 = setup_platform(name="P2", active=False)
    resp = api.create_viewership_event(
        factories.create_viewership_event_payload(
            channel["id"], "SESSION_START", platform_id=p1["id"]
        ),
        make_distributor_partner_headers(p2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    assert resp.status_code == 403


def test_reviewer_cannot_approve_own_creative(api):
    """PRD §3.5: "The reviewer's identity must differ from `created_by_user_id`,
    else `ERR_SEGREGATION_OF_DUTIES`; the same segregation governs rejection."

    Design: Corner/validations/reviewer_cannot_approve_own_creative
    """
    campaign = get_success_data(
        api.create_ad_campaign(factories.create_ad_campaign_payload(), ADOPS)
    )
    creative = get_success_data(
        api.create_ad_creative(
            factories.create_ad_creative_payload(campaign["id"]), ADOPS
        )
    )
    # Same X-User-ID that trafficked the creative ("ops-1") presents as reviewer.
    resp = api.creative_approve(creative["id"], make_reviewer_headers("ops-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_creative(creative["id"])["creative_status"] == "PENDING_REVIEW"


def test_controller_cannot_finalize_own_generated_report(api):
    """PRD §3.8: "Finalizing (`PROVISIONAL` → `FINALIZED`) belongs to a
    `FinanceController` who must not be the analyst recorded in
    `generated_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`". PRD §2.1: "The
    segregation-of-duties checks in §3.5 and §3.8 are the only places these
    identifiers are compared — against each other, not against resource ids."

    Design: Corner/validations/controller_cannot_finalize_own_generated_report
    """
    ctx = setup_provisional_report(channel_name="Ch Seg", analyst_id="fin-1")
    # The generator's user id presents with the controller role.
    resp = api.report_finalize(ctx["report"]["id"], make_controller_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_report(ctx["report"]["id"])["report_status"] == "PROVISIONAL"


def test_partner_reads_only_own_reports(api):
    """PRD §3.8: "Reports may be listed filtered by `channel_id`, `platform_id`,
    `agreement_id`, `report_status`, or `period_month`, and fetched by `report_id`;
    a `DistributorPartner` sees only their own platform's reports." PRD §2.1: "A
    partner touching another platform's resource — reading or disputing a report
    whose `platform_id` differs from the caller's id, or submitting a viewership
    event for a different platform — is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/partner_reads_only_own_reports
    """
    channel = create_channel(name="Ch SC")
    p1 = setup_platform(name="P1", reporting_tier="STANDARD")
    p2 = setup_platform(name="P2", reporting_tier="PREMIUM")
    setup_active_agreement(channel["id"], p1["id"], below=3000, above=4000)
    setup_active_agreement(channel["id"], p2["id"], below=2500, above=3500)
    advance_clock("2026-10-01T00:00:00Z")
    rp1 = get_success_data(
        api.create_revenue_report(
            factories.create_revenue_report_payload(channel["id"], p1["id"]),
            make_analyst_headers("fin-1"),
        )
    )
    rp2 = get_success_data(
        api.create_revenue_report(
            factories.create_revenue_report_payload(channel["id"], p2["id"]),
            make_analyst_headers("fin-1"),
        )
    )
    partner2 = make_distributor_partner_headers(p2["id"])
    data, _ = validate_paginated(api.list_revenue_reports(partner2))
    assert [row["id"] for row in data] == [rp2["id"]], (
        "partner list contains only their own platform's reports"
    )
    resp = api.get_revenue_report(rp1["id"], partner2)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
