"""Authentication, role admission, tenant exemption, and the send-credit conservation invariant."""
from test_helpers import (
    ANONYMOUS,
    NON_EXISTENT_UUID,
    NO_AUTH,
    PLATFORM,
    ApiErrorId,
    add_confirmed_subscribers,
    assert_credit_conservation,
    create_account_payload,
    create_approved_campaign,
    create_audience,
    create_audience_payload,
    create_published_template,
    deliver,
    provision_tenant,
    read_campaign,
    schedule_ok,
    setup_dispatched_campaign,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_a_request_with_no_role_header_is_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` is missing or names something other than one of
        the four declared roles, or whose `X-User-ID` is missing for any role other than `Anonymous`,
        is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_role_header_returns_unauthenticated
        """
        resp = api.create_account(create_account_payload(name="Acme"), NO_AUTH)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_listing_users_of_an_unknown_account_is_a_not_found(self, api):
        """PRD §2.5: "Path identifiers resolve, left to right, the leftmost miss winning —
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_AUDIENCE_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`,
        `ERR_TEMPLATE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_JOURNEY_NOT_FOUND`,
        `ERR_IMPORT_JOB_NOT_FOUND` or `ERR_SEND_NOT_FOUND` as appropriate."

        Design: Corner/errors/err_account_not_found_on_users_list
        """
        resp = api.list_account_users(NON_EXISTENT_UUID, PLATFORM)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)


class TestRoleAdmission:
    def test_anonymous_may_not_list_contacts(self, api):
        """PRD §2.1: "A request whose claimed role is well-formed but is not among the roles the
        target operation admits is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "When `X-User-Role` is `Anonymous`, no `X-User-ID` is sent at all. `Anonymous` is
        the unauthenticated visitor filling in a public signup form or clicking a link inside a
        delivered email; it has no persisted identity and the server never resolves it to an entity."
        PRD §4: "| GET | `/subscribers` | List contacts, filterable by audience and state |
        PlatformAdmin, CampaignAuthor, ComplianceApprover |"

        Design: Corner/rbac/anonymous_cannot_list_subscribers
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)
        add_confirmed_subscribers(audience["id"], 1, PLATFORM)

        resp = api.list_subscribers(ANONYMOUS, {"audience_id": audience["id"]})
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_platform_admin_is_exempt_from_the_tenant_isolation_check(self, api):
        """PRD §2.1: "Tenant isolation is absolute for the two entity-backed roles: a
        `CampaignAuthor` or `ComplianceApprover` whose own `AccountUser.account_id` differs from the
        owning account of any resource they touch — the account behind a path identifier, an
        `account_id` in the body, the account owning a referenced template, or the account owning the
        audience behind an audience identifier — is rejected with `ERR_CROSS_ACCOUNT_ACCESS` (HTTP
        403). `PlatformAdmin` is exempt from this check."
        PRD §2.1: "When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator
        identifier not tied to any persisted entity."

        Design: Corner/rbac/platform_admin_exempt_from_cross_account_check
        """
        account_a = validate_success(api.create_account(create_account_payload(name="A"), PLATFORM), 201)
        account_b = validate_success(api.create_account(create_account_payload(name="B"), PLATFORM), 201)

        list_a = validate_success(
            api.create_audience(
                create_audience_payload(account_a["id"], name="LA", default_from_email="a@x.com"),
                PLATFORM,
            ),
            201,
        )
        list_b = validate_success(
            api.create_audience(
                create_audience_payload(account_b["id"], name="LB", default_from_email="b@x.com"),
                PLATFORM,
            ),
            201,
        )

        assert list_a["account_id"] == account_a["id"]
        assert list_b["account_id"] == account_b["id"]


class TestSendCreditConservation:
    def test_the_grant_reconciles_after_a_schedule_is_undone_by_a_cancel(self, api):
        """PRD §2.7: "Send credits are granted exactly once, when the tenant is provisioned, and
        never again. `granted_send_credits` records that immutable grant. From it, three buckets are
        derived and must always reconcile: `send_credit_balance` holds credits that are neither
        reserved nor spent; `reserved_send_credits` is the sum of `reserved_credit_count` across the
        account's campaigns whose `status` is `SCHEDULED` or `SENDING`; and `consumed_send_credits` is
        the sum of `reserved_credit_count` across the account's campaigns whose `status` is `SENT`. At
        every observable instant, `granted_send_credits` equals the balance plus the reservations plus
        the consumption."

        Design: Difficulty/compensating_invariant/send_credit_conservation_across_schedule_and_cancel
        """
        tenant = provision_tenant(initial_send_credits=100)
        audience = create_audience(tenant, double_optin_required=False)
        add_confirmed_subscribers(audience["id"], 4, tenant.author_headers)
        template = create_published_template(tenant)
        campaign = create_approved_campaign(tenant, audience["id"], template["id"])

        assert tenant.refresh()["granted_send_credits"] == 100

        schedule_ok(tenant, campaign["id"], "2026-05-02T10:00:00Z", 60)
        after_schedule = tenant.refresh()
        assert after_schedule["send_credit_balance"] == 96
        assert after_schedule["reserved_send_credits"] == 4
        assert_credit_conservation(after_schedule, 100)

        validate_success(api.cancel_campaign(campaign["id"], tenant.author_headers))

        after_cancel = tenant.refresh()
        assert after_cancel["send_credit_balance"] == 100
        assert after_cancel["reserved_send_credits"] == 0
        assert after_cancel["consumed_send_credits"] == 0
        assert_credit_conservation(after_cancel, 100)

    def test_cancel_returns_the_full_reservation_even_when_sends_were_delivered(self, api):
        """PRD §3.6: "Sends that had already reached a terminal `delivery_status` — `DELIVERED`,
        `HARD_BOUNCED`, `SUPPRESSED` or `COMPLAINED` — are left exactly as they are, but the full
        original reservation is still returned. That is the stated compensation policy, and it is
        what keeps the grant reconciling against the three buckets."
        PRD §2.7: "At every observable instant, `granted_send_credits` equals the balance plus the
        reservations plus the consumption."

        Design: Difficulty/compensating_invariant/send_credit_conservation_across_schedule_and_cancel
        """
        env = setup_dispatched_campaign(num_subscribers=4, initial_send_credits=100)
        deliver(env.send_ids[0])
        deliver(env.send_ids[1])

        validate_success(api.cancel_campaign(env.campaign_id, env.tenant.author_headers))

        assert read_campaign(env.campaign_id)["reserved_credit_count"] == 0
        account = env.tenant.refresh()
        assert account["granted_send_credits"] == 100
        assert account["send_credit_balance"] == 100, "the whole original reservation came back"
        assert account["reserved_send_credits"] == 0
        assert account["consumed_send_credits"] == 0
        assert_credit_conservation(account, 100)
