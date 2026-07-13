"""Tenant provisioning, the logical clock, audiences, and the subscriber consent lifecycle."""
import pytest

from test_helpers import (
    ANONYMOUS,
    NON_EXISTENT_UUID,
    PLATFORM,
    ApiErrorId,
    add_subscriber,
    assert_account,
    assert_audience,
    assert_subscriber,
    assert_suppression_entry,
    billing_cycles_of,
    create_account_payload,
    create_audience,
    create_audience_payload,
    create_subscriber_payload,
    confirm_payload,
    ops_run,
    provision_tenant,
    read_audience,
    read_subscriber,
    set_clock,
    suppressions_of,
    unsubscribe,
    unsubscribe_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTenantProvisioning:
    def test_create_account_applies_every_documented_default(self, api):
        """PRD §3.1: "`plan_tier` is one of `FREE`, `ESSENTIALS`, `STANDARD` or `PREMIUM` and
        defaults to `FREE`."
        PRD §3.1: "A freshly provisioned account is `ACTIVE` with a null `suspension_reason`
        and a `sender_reputation_score` of 100, and its `billable_contact_count`,
        `reserved_send_credits` and `consumed_send_credits` all start at zero."
        PRD §3.1: "`hourly_send_capacity` is the largest number of recipients the account may
        hold inside any one overlapping group of send windows; it must be at least 1 and
        defaults to 1000."
        PRD §2.4: "`version`, an integer that starts at 1 and increments by exactly one on
        every mutation of that resource."

        Design: Corner/entities/create_account_returns_defaults_and_envelope
        """
        resp = api.create_account(create_account_payload(name="Acme"), PLATFORM)
        account = validate_success(resp, 201)
        assert_account(account)

        assert account["plan_tier"] == "FREE"
        assert account["status"] == "ACTIVE"
        assert account["suspension_reason"] is None
        assert account["granted_send_credits"] == 0
        assert account["send_credit_balance"] == 0
        assert account["reserved_send_credits"] == 0
        assert account["consumed_send_credits"] == 0
        assert account["hourly_send_capacity"] == 1000
        assert account["billable_contact_count"] == 0
        assert account["sender_reputation_score"] == 100
        assert account["version"] == 1

        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]

    def test_create_account_opens_first_billing_cycle_at_the_clock(self, api):
        """PRD §3.1: "Provisioning also opens the tenant's first billing period: a cycle whose
        `period_start` is the current clock instant, whose `period_end` is exactly 30 days
        later, whose `status` is `OPEN`, and whose `peak_contact_count` starts at 0."
        PRD §2.4: "The logical clock starts at exactly `2026-05-01T00:00:00Z` and stays there
        until a platform operator moves it; it may be moved forward or backward, and the
        operation that moves it takes a single `to_iso8601` instant and answers with the new
        `current_utc`."

        Design: Corner/entities/create_account_opens_first_billing_cycle
        """
        account = validate_success(
            api.create_account(create_account_payload(plan_tier="STANDARD"), PLATFORM), 201
        )
        cycles = billing_cycles_of(account["id"])

        assert len(cycles) == 1, f"provisioning opens exactly one cycle, got {len(cycles)}"
        assert cycles[0]["status"] == "OPEN"
        assert cycles[0]["period_start"] == "2026-05-01T00:00:00.000Z"
        assert cycles[0]["period_end"] == "2026-05-31T00:00:00.000Z"
        assert cycles[0]["peak_contact_count"] == 0

    def test_logical_clock_starts_at_its_documented_instant(self, api):
        """PRD §2.4: "The logical clock starts at exactly `2026-05-01T00:00:00Z` and stays there
        until a platform operator moves it; it may be moved forward or backward, and the
        operation that moves it takes a single `to_iso8601` instant and answers with the new
        `current_utc`."
        PRD §3.2: "Where the audience does not require double opt-in, the contact is minted
        directly into `CONFIRMED` inside the very same request: `confirmation_token` stays null,
        `consent_confirmed_at` is stamped with the clock, and — because a subscriber just became
        `CONFIRMED` — the subscribe-triggered journey enrollments described in §3.10 fire
        immediately."

        Design: Corner/endpoints/clock_startup_default_is_2026_05_01
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)
        subscriber = add_subscriber(audience["id"], "s1@x.com", PLATFORM)

        assert subscriber["created_at"] == "2026-05-01T00:00:00.000Z"
        assert subscriber["consent_confirmed_at"] == "2026-05-01T00:00:00.000Z"

        moved = set_clock("2026-06-15T12:30:00Z")
        assert moved["current_utc"] == "2026-06-15T12:30:00.000Z"


class TestAudienceCreation:
    def test_create_audience_without_default_from_email_is_rejected(self, api):
        """PRD §3.2: "It belongs to an account, carries a `name` of 1 to 120 characters, a
        `default_from_email` containing an `@` character that campaigns targeting the list will
        send from, and a `double_optin_required` flag that defaults to true."
        PRD §2.5: "Body shape: required fields present, enum values legal, integers inside their
        declared ranges, `rows` between 1 and 100 elements, `variant_b_subject` supplied whenever
        `ab_test_enabled` is true, and a well-formed `steps` array of 1 to 10 elements whose
        `step_index` values run from 0 upward in ascending order — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_audience_missing_default_from_email_invalid_request
        """
        account = validate_success(api.create_account(create_account_payload(), PLATFORM), 201)

        resp = api.create_audience({"account_id": account["id"], "name": "Main"}, PLATFORM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

        listed, _ = validate_paginated(
            api.list_audiences(PLATFORM, {"account_id": account["id"]})
        )
        assert listed == [], "the rejected request must not have created an audience"

    def test_omitted_double_optin_flag_defaults_to_true(self, api):
        """PRD §3.2: "It belongs to an account, carries a `name` of 1 to 120 characters, a
        `default_from_email` containing an `@` character that campaigns targeting the list will
        send from, and a `double_optin_required` flag that defaults to true."
        PRD §3.2: "Where the audience requires double opt-in, the contact lands in `PENDING`, a
        `confirmation_token` is minted alongside, and `consent_confirmed_at` is null."
        PRD §3.2: "Its `subscriber_count` is derived, never supplied: it counts the audience's
        subscribers whose `consent_state` is `PENDING`, `CONFIRMED` or `UNSUBSCRIBED`."

        Design: Corner/entities/create_audience_omits_double_optin_defaults_true
        """
        account = validate_success(api.create_account(create_account_payload(), PLATFORM), 201)
        audience = validate_success(
            api.create_audience(create_audience_payload(account["id"]), PLATFORM), 201
        )
        assert_audience(audience)
        assert audience["double_optin_required"] is True

        subscriber = validate_success(
            api.create_subscriber(
                audience["id"],
                create_subscriber_payload(email="s1@x.com", consent_source="SIGNUP_FORM"),
                ANONYMOUS,
            ),
            201,
        )
        assert subscriber["consent_state"] == "PENDING"
        assert subscriber["confirmation_token"] is not None
        assert subscriber["consent_confirmed_at"] is None
        assert read_audience(audience["id"])["subscriber_count"] == 1

    def test_audience_list_paginates_and_filters_by_account(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
        inside the `meta` object of the envelope, where `total_count` counts the items matching
        the filter before pagination is applied and `has_more` reports whether any item remains
        beyond the returned page."
        PRD §2.3: "Unless a specific endpoint states otherwise, list results are sorted by
        `created_at` ascending."

        Design: Corner/entities/list_audiences_paginated_and_filtered_by_account
        """
        account_a = validate_success(api.create_account(create_account_payload(name="A"), PLATFORM), 201)
        account_b = validate_success(api.create_account(create_account_payload(name="B"), PLATFORM), 201)
        for name in ("L1", "L2", "L3"):
            validate_success(
                api.create_audience(
                    create_audience_payload(account_a["id"], name=name, default_from_email="a@x.com"),
                    PLATFORM,
                ),
                201,
            )
        validate_success(
            api.create_audience(
                create_audience_payload(account_b["id"], name="L9", default_from_email="b@x.com"),
                PLATFORM,
            ),
            201,
        )

        rows, meta = validate_paginated(
            api.list_audiences(PLATFORM, {"account_id": account_a["id"], "limit": 2, "offset": 1})
        )
        assert meta["total_count"] == 3
        # offset=1 + 2 returned rows == total_count 3, so no item remains beyond this page.
        assert meta["has_more"] is False
        assert meta["limit"] == 2
        assert meta["offset"] == 1
        assert [row["name"] for row in rows] == ["L2", "L3"]
        assert all(row["account_id"] == account_a["id"] for row in rows)


class TestSubscriberCreation:
    def test_illegal_consent_source_enum_is_rejected(self, api):
        """PRD §2.9: "A `Subscriber` records where consent came from in `consent_source`, one of
        `SIGNUP_FORM`, `IMPORT`, `API` or `MANUAL`, and where it currently stands in
        `consent_state`, one of `PENDING`, `CONFIRMED`, `UNSUBSCRIBED`, `CLEANED` or `ARCHIVED`."
        PRD §2.5: "Body shape: required fields present, enum values legal, integers inside their
        declared ranges, `rows` between 1 and 100 elements, `variant_b_subject` supplied whenever
        `ab_test_enabled` is true, and a well-formed `steps` array of 1 to 10 elements whose
        `step_index` values run from 0 upward in ascending order — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_subscriber_invalid_enum_consent_source
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)

        resp = api.create_subscriber(
            audience["id"],
            {"email": "s1@x.com", "consent_source": "CARRIER_PIGEON"},
            PLATFORM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_subscriber_under_unknown_audience_reports_the_parent_miss(self, api):
        """PRD §2.5: "Path identifiers resolve, left to right, the leftmost miss winning —
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_AUDIENCE_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`,
        `ERR_TEMPLATE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_JOURNEY_NOT_FOUND`,
        `ERR_IMPORT_JOB_NOT_FOUND` or `ERR_SEND_NOT_FOUND` as appropriate. A request for a nested
        resource under a parent that does not exist reports the parent's miss, not the child's."

        Design: Corner/entities/create_subscriber_under_unknown_audience_returns_not_found
        """
        resp = api.create_subscriber(
            NON_EXISTENT_UUID, create_subscriber_payload(email="s1@x.com"), PLATFORM
        )
        validate_error(resp, ApiErrorId.ERR_AUDIENCE_NOT_FOUND.value)

    def test_unknown_campaign_id_is_a_not_found_error(self, api):
        """PRD §2.5: "Path identifiers resolve, left to right, the leftmost miss winning —
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_AUDIENCE_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`,
        `ERR_TEMPLATE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_JOURNEY_NOT_FOUND`,
        `ERR_IMPORT_JOB_NOT_FOUND` or `ERR_SEND_NOT_FOUND` as appropriate."

        Design: Corner/entities/get_campaign_unknown_id_returns_not_found
        """
        resp = api.get_campaign(NON_EXISTENT_UUID, PLATFORM)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value)
        assert resp.json()["response_type"] == "error"

    def test_brand_new_contact_is_new_with_a_neutral_score(self, api):
        """PRD §3.2: "Either way, `unsubscribed_at` and `last_opened_at` are null,
        `delivered_send_count`, `opened_send_count` and `clicked_send_count` are 0,
        `engagement_state` is `NEW`, and both `engagement_score` and `engagement_score_90d`
        read 50."
        PRD §3.4: "`engagement_state` is derived from the lifetime score, with one override at
        the front: a contact whose `delivered_send_count` is 0 is `NEW` regardless of anything
        else."

        Design: Corner/calculations/new_subscriber_engagement_state_is_new_with_neutral_score
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)

        subscriber = validate_success(
            api.create_subscriber(
                audience["id"],
                create_subscriber_payload(email="s1@x.com", consent_source="MANUAL"),
                PLATFORM,
            ),
            201,
        )
        assert_subscriber(subscriber)
        assert subscriber["delivered_send_count"] == 0
        assert subscriber["engagement_score"] == 50
        assert subscriber["engagement_score_90d"] == 50
        assert subscriber["engagement_state"] == "NEW", "NEW overrides the 40..70 DORMANT band"
        assert subscriber["last_opened_at"] is None

    def test_duplicate_email_in_the_same_audience_is_rejected(self, api):
        """PRD §3.2: "Two guards run before the row is written: if the address matches a
        suppression entry of the audience's account, the request is refused with
        `ERR_EMAIL_SUPPRESSED`, and if a subscriber with that address already exists in that
        audience in *any* `consent_state` at all, it is refused with `ERR_SUBSCRIBER_EXISTS`.
        Suppression is checked first."

        Design: Corner/validations/duplicate_email_in_same_audience_rejected
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)
        add_subscriber(audience["id"], "s1@x.com", PLATFORM)

        resp = api.create_subscriber(
            audience["id"],
            create_subscriber_payload(email="s1@x.com", consent_source="SIGNUP_FORM"),
            ANONYMOUS,
        )
        validate_error(resp, ApiErrorId.ERR_SUBSCRIBER_EXISTS.value)
        assert read_audience(audience["id"])["subscriber_count"] == 1

    def test_suppressed_address_cannot_be_added_to_any_audience_of_the_account(self, api):
        """PRD §2.9: "Once an address is suppressed for an account, no further subscriber with
        that address may be created in *any* audience of that account, and the address is
        silently withheld from every future recipient snapshot of that account."
        PRD §3.2: "Two guards run before the row is written: if the address matches a suppression
        entry of the audience's account, the request is refused with `ERR_EMAIL_SUPPRESSED`, and
        if a subscriber with that address already exists in that audience in *any* `consent_state`
        at all, it is refused with `ERR_SUBSCRIBER_EXISTS`. Suppression is checked first."

        Design: Corner/validations/suppressed_email_cannot_be_resubscribed
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        list_1 = create_audience(tenant, name="L1", double_optin_required=False, headers=PLATFORM)
        list_2 = create_audience(tenant, name="L2", double_optin_required=False, headers=PLATFORM)
        subscriber = add_subscriber(list_1["id"], "s1@x.com", PLATFORM)
        unsubscribe(subscriber)

        resp = api.create_subscriber(
            list_2["id"],
            create_subscriber_payload(email="s1@x.com", consent_source="SIGNUP_FORM"),
            ANONYMOUS,
        )
        validate_error(resp, ApiErrorId.ERR_EMAIL_SUPPRESSED.value)
        assert read_audience(list_2["id"])["subscriber_count"] == 0


class TestDoubleOptIn:
    def test_confirm_with_the_matching_token_moves_pending_to_confirmed(self, api):
        """PRD §3.2: "On success `PENDING → CONFIRMED`: `consent_confirmed_at` is stamped,
        `confirmation_token` is cleared to null, subscribe-triggered journey enrollments fire,
        and `subscriber_count` does not move, because a `PENDING` contact was already being
        counted."

        Design: Corner/state_machines/confirm_moves_pending_to_confirmed_with_token
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=True, headers=PLATFORM)
        pending = validate_success(
            api.create_subscriber(
                audience["id"],
                create_subscriber_payload(email="s1@x.com", consent_source="SIGNUP_FORM"),
                ANONYMOUS,
            ),
            201,
        )

        confirmed = validate_success(
            api.confirm_subscriber(
                pending["id"], confirm_payload(pending["confirmation_token"]), ANONYMOUS
            )
        )
        assert confirmed["consent_state"] == "CONFIRMED"
        assert confirmed["consent_confirmed_at"] == "2026-05-01T00:00:00.000Z"
        assert confirmed["confirmation_token"] is None
        assert read_audience(audience["id"])["subscriber_count"] == 1

    def test_wrong_confirmation_token_is_rejected(self, api):
        """PRD §3.2: "The contact must still be in `PENDING`; the supplied token must equal the
        stored `confirmation_token`, or the request is refused with
        `ERR_INVALID_CONFIRMATION_TOKEN`; and the clock must read strictly earlier than 48 hours
        after the contact's `created_at`, or the request is refused with `ERR_CONFIRMATION_EXPIRED`
        and the contact stays exactly where it was, in `PENDING`."

        Design: Corner/errors/err_invalid_confirmation_token_rejected
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=True, headers=PLATFORM)
        pending = validate_success(
            api.create_subscriber(
                audience["id"],
                create_subscriber_payload(email="s1@x.com", consent_source="SIGNUP_FORM"),
                ANONYMOUS,
            ),
            201,
        )

        resp = api.confirm_subscriber(pending["id"], confirm_payload("totally-wrong"), ANONYMOUS)
        validate_error(resp, ApiErrorId.ERR_INVALID_CONFIRMATION_TOKEN.value)

        after = read_subscriber(pending["id"])
        assert after["consent_state"] == "PENDING"
        assert after["confirmation_token"] is not None

    def test_confirmation_exactly_48_hours_late_is_expired(self, api):
        """PRD §3.2: "The contact must still be in `PENDING`; the supplied token must equal the
        stored `confirmation_token`, or the request is refused with
        `ERR_INVALID_CONFIRMATION_TOKEN`; and the clock must read strictly earlier than 48 hours
        after the contact's `created_at`, or the request is refused with `ERR_CONFIRMATION_EXPIRED`
        and the contact stays exactly where it was, in `PENDING`."

        Design: Corner/validations/expired_confirmation_token_rejected_after_48h
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=True, headers=PLATFORM)
        pending = validate_success(
            api.create_subscriber(
                audience["id"],
                create_subscriber_payload(email="s1@x.com", consent_source="SIGNUP_FORM"),
                ANONYMOUS,
            ),
            201,
        )
        set_clock("2026-05-03T00:00:00Z")  # exactly 48h after created_at

        resp = api.confirm_subscriber(
            pending["id"], confirm_payload(pending["confirmation_token"]), ANONYMOUS
        )
        validate_error(resp, ApiErrorId.ERR_CONFIRMATION_EXPIRED.value)
        assert read_subscriber(pending["id"])["consent_state"] == "PENDING"

    def test_confirm_on_an_unknown_subscriber_is_a_not_found(self, api):
        """PRD §2.5: "Path identifiers resolve, left to right, the leftmost miss winning —
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_AUDIENCE_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`,
        `ERR_TEMPLATE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_JOURNEY_NOT_FOUND`,
        `ERR_IMPORT_JOB_NOT_FOUND` or `ERR_SEND_NOT_FOUND` as appropriate."

        Design: Corner/errors/err_subscriber_not_found_on_confirm
        """
        resp = api.confirm_subscriber(NON_EXISTENT_UUID, confirm_payload("whatever"), ANONYMOUS)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIBER_NOT_FOUND.value)

    def test_stale_pending_contact_is_archived_by_the_epoch(self, api):
        """PRD §3.2: "During the first phase of the operations epoch, every contact still in
        `PENDING` whose `created_at` is 48 hours or more behind the clock moves
        `PENDING → ARCHIVED`, its `confirmation_token` is cleared, and both `subscriber_count`
        and `billable_contact_count` fall accordingly."
        PRD §2.11: "The epoch reports what it did: `subscribers_archived`, `campaigns_dispatched`,
        `sends_created`, `enrollments_advanced` and `billing_cycles_closed`."

        Design: Corner/state_machines/pending_subscriber_archived_after_confirmation_ttl
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=True, headers=PLATFORM)
        pending = validate_success(
            api.create_subscriber(
                audience["id"],
                create_subscriber_payload(email="s1@x.com", consent_source="SIGNUP_FORM"),
                ANONYMOUS,
            ),
            201,
        )
        set_clock("2026-05-03T01:00:00Z")  # 49 hours after creation

        summary = ops_run()
        assert summary["subscribers_archived"] == 1

        after = read_subscriber(pending["id"])
        assert after["consent_state"] == "ARCHIVED"
        assert after["confirmation_token"] is None
        assert read_audience(audience["id"])["subscriber_count"] == 0
        assert tenant.refresh()["billable_contact_count"] == 0


class TestUnsubscribeAndSuppression:
    def test_wrong_unsubscribe_token_is_rejected(self, api):
        """PRD §3.2: "The contact must be in `PENDING` or `CONFIRMED` — any other `consent_state`
        is refused with `ERR_ALREADY_UNSUBSCRIBED` — and the supplied token must equal the stored
        one, or the request is refused with `ERR_INVALID_UNSUBSCRIBE_TOKEN`."

        Design: Corner/validations/wrong_unsubscribe_token_rejected
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)
        subscriber = add_subscriber(audience["id"], "s1@x.com", PLATFORM)

        resp = api.unsubscribe_subscriber(
            subscriber["id"], unsubscribe_payload("not-the-right-token"), ANONYMOUS
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_UNSUBSCRIBE_TOKEN.value)

        assert read_subscriber(subscriber["id"])["consent_state"] == "CONFIRMED"
        assert suppressions_of(tenant.id) == []

    def test_second_unsubscribe_is_rejected_and_writes_no_second_suppression(self, api):
        """PRD §3.2: "The contact must be in `PENDING` or `CONFIRMED` — any other `consent_state`
        is refused with `ERR_ALREADY_UNSUBSCRIBED` — and the supplied token must equal the stored
        one, or the request is refused with `ERR_INVALID_UNSUBSCRIBE_TOKEN`."
        PRD §2.9: "At most one suppression row exists per account-and-address pair: whenever a
        cascade would create a second, the existing row is left as it is and no duplicate is
        written."

        Design: Corner/errors/err_already_unsubscribed_on_second_unsubscribe
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)
        subscriber = add_subscriber(audience["id"], "s1@x.com", PLATFORM)
        unsubscribe(subscriber)

        resp = api.unsubscribe_subscriber(
            subscriber["id"], unsubscribe_payload(subscriber["unsubscribe_token"]), ANONYMOUS
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_UNSUBSCRIBED.value)

        assert read_subscriber(subscriber["id"])["consent_state"] == "UNSUBSCRIBED"
        assert len(suppressions_of(tenant.id)) == 1

    def test_suppression_row_is_immutable_and_carries_no_version(self, api):
        """PRD §2.4: "`SuppressionEntry` is the sole exception. Suppression records are immutable
        once written: they carry only `id` and `created_at`, and have neither `updated_at` nor
        `version`."
        PRD §3.2: "On success the contact moves to `UNSUBSCRIBED` from whichever of `PENDING` or
        `CONFIRMED` it was in, `unsubscribed_at` is stamped with the clock, and a suppression
        entry with `reason` `UNSUBSCRIBE` is written for the account and address unless one
        already exists for that pair."

        Design: Corner/entities/suppression_entry_is_immutable_no_version_field
        """
        tenant = provision_tenant(with_author=False, with_approver=False)
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)
        subscriber = add_subscriber(audience["id"], "s1@x.com", PLATFORM)

        unsubscribe(subscriber)

        entries = suppressions_of(tenant.id)
        assert len(entries) == 1
        assert_suppression_entry(entries[0])
        assert entries[0]["email"] == "s1@x.com"
        assert entries[0]["reason"] == "UNSUBSCRIBE"
        assert "version" not in entries[0]
        assert "updated_at" not in entries[0]
