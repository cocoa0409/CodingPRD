"""Registration, child profiles, the append-only ledger, pagination, and the
two developmental-age variants (calendar canonical vs rolling browse)."""

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    SUPPORT,
    ApiErrorId,
    assert_ledger_entry,
    assert_member,
    create_catalog_item_payload,
    create_child_payload,
    create_member_payload,
    create_wallet_adjustment_payload,
    list_ledger,
    make_member_headers,
    register_member,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMemberRegistration:
    def test_register_returns_member_with_system_defaults(self, api, anonymous_headers):
        """PRD §3.1: "A freshly registered member starts with `status` `ACTIVE`
        and a `wallet_credit_cents` of zero."
        PRD §4: "Operations that create a new resource — a member, a child
        profile, a plan, a catalog item, a physical copy, a wishlist entry, a
        subscription, a rotation box, a box item, a shipment, or a wallet
        ledger adjustment — return a `201 Created` status code."

        Design: Corner/entities/member_register_creation_and_defaults
        """
        resp = api.register_member(
            create_member_payload(email="m.new@x.com", full_name="New Member"),
            anonymous_headers,
        )
        member = validate_success(resp, 201)
        assert_member(member)
        assert member["status"] == "ACTIVE"
        assert member["wallet_credit_cents"] == 0
        assert member["full_name"] == "New Member"

    def test_register_duplicate_email_rejected(self, api, anonymous_headers):
        """PRD §3.1: "Email addresses are unique across all members: a
        duplicate registration is rejected with `ERR_EMAIL_TAKEN` (HTTP 409)."

        Design: Corner/entities/member_register_duplicate_email_rejected
        """
        register_member(email="dup@x.com", full_name="First")
        resp = api.register_member(
            create_member_payload(email="dup@x.com", full_name="Second"),
            anonymous_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EMAIL_TAKEN.value)


class TestChildProfiles:
    def test_create_child_missing_birthdate_rejected(self, api):
        """PRD §2.6: "request-body shape validation (`ERR_VALIDATION`,
        HTTP 400), which rejects missing required fields, unknown or
        computed/system-managed fields supplied by the client, out-of-range
        enum values, a `min_age_months` greater than `max_age_months`, a
        `birthdate` after the logical clock date, or a duplicate copy
        `barcode`."

        Design: Corner/entities/child_create_missing_required_birthdate_returns_invalid_request
        """
        member = register_member(email="m.req@x.com")
        resp = api.create_child(member["id"], {"name": "KidNoDate"},
                                make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
        data, meta = validate_paginated(api.list_children(
            member["id"], make_member_headers(member["id"])))
        assert meta["total_count"] == 0

    def test_create_child_with_computed_field_supplied_rejected(self, api):
        """PRD §2.6: "request-body shape validation (`ERR_VALIDATION`,
        HTTP 400), which rejects missing required fields, unknown or
        computed/system-managed fields supplied by the client, out-of-range
        enum values, a `min_age_months` greater than `max_age_months`, a
        `birthdate` after the logical clock date, or a duplicate copy
        `barcode`."

        Design: Corner/entities/child_create_computed_field_input_ignored
        """
        member = register_member(email="m.cmp@x.com")
        payload = create_child_payload(name="Kid", birthdate="2025-01-15")
        payload["developmental_stage"] = "EARLY_SCHOOL"
        resp = api.create_child(member["id"], payload, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_child_profile_uses_calendar_months_canonical(self, api):
        """PRD §3.1: "The `age_months` field counts whole calendar months
        between the birthdate and the logical clock date, where a month
        completes on the same day-of-month as the birthdate — clamped to the
        month end when the target month is shorter — so a child born on
        2025-05-02 reads 11 months when the clock stands at 2026-05-01."
        PRD §3.1: "The `developmental_stage` field bands that age as `INFANT`
        for 0–11 months, `TODDLER` for 12–35, `PRESCHOOLER` for 36–59, and
        `EARLY_SCHOOL` for 60 months and beyond."

        Design: Difficulty/dual_variant_calc/developmental_stage_calendar_vs_rolling_variants
        """
        member = register_member(email="m.dev@x.com", full_name="Dev Member")
        api.create_child(member["id"],
                         create_child_payload(name="Kiddo", birthdate="2025-05-02"),
                         make_member_headers(member["id"]))
        data, _ = validate_paginated(api.list_children(
            member["id"], make_member_headers(member["id"])))
        assert len(data) == 1
        child = data[0]
        # The logical clock has never been positioned, so it reads the startup
        # default 2026-05-01T00:00:00Z (PRD §2.5): the 12th month completes on
        # 2026-05-02, one day after the clock date.
        assert child["age_months"] == 11
        assert child["developmental_stage"] == "INFANT"

    def test_catalog_browse_child_id_uses_rolling_variant(self, api):
        """PRD §3.1: "Catalog browsing is deliberately more permissive: the
        optional `child_id` filter on the catalog list applies a rolling
        variant — elapsed calendar days divided by 30, rounded down — purely as
        a suggestion aid. Under that variant the same child born 2025-05-02
        reads 12 months at clock 2026-05-01, so the browse list can suggest an
        item that the hard gate still rejects."

        Design: Difficulty/dual_variant_calc/developmental_stage_calendar_vs_rolling_variants
        """
        member = register_member(email="m.dev@x.com", full_name="Dev Member")
        child = validate_success(api.create_child(
            member["id"], create_child_payload(name="Kiddo", birthdate="2025-05-02"),
            make_member_headers(member["id"])), 201)
        item = validate_success(api.create_catalog_item(
            create_catalog_item_payload(
                title="Walker Wagon", min_age_months=12, max_age_months=24,
                developmental_stages=["TODDLER"], piece_count=8,
                retail_value_cents=9000, replacement_value_cents=7000),
            ADMIN), 201)

        data, _ = validate_paginated(api.list_catalog_items(
            make_member_headers(member["id"]), params={"child_id": child["id"]}))
        listed_ids = [i["id"] for i in data]
        # Calendar age 11 (hard gate) vs rolling floor(364/30) = 12 (browse):
        # the two variants disagree on identical inputs, and the suggestion
        # list follows the rolling variant, so the [12, 24] item appears.
        assert item["id"] in listed_ids


class TestExistenceAndLedger:
    def test_get_with_nonexistent_uuid_returns_resource_404(self, api, support_headers, ops_headers):
        """PRD §2.6: "Requests that target nested resources validate path
        identifiers strictly left to right, rejecting with the 404 that
        corresponds to the first missing resource: `ERR_MEMBER_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`,
        `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_COPY_NOT_FOUND`,
        `ERR_WISHLIST_ENTRY_NOT_FOUND`, `ERR_BOX_NOT_FOUND`,
        `ERR_BOX_ITEM_NOT_FOUND`, `ERR_FEE_NOT_FOUND`, or
        `ERR_SHIPMENT_NOT_FOUND` (each HTTP 404)."

        Design: Corner/entities/entity_not_found_returns_404
        """
        resp_member = api.get_member(NON_EXISTENT_UUID, support_headers)
        validate_error(resp_member, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)
        resp_box = api.get_rotation_box(NON_EXISTENT_UUID, ops_headers)
        validate_error(resp_box, ApiErrorId.ERR_BOX_NOT_FOUND.value)

    def test_credit_ledger_entry_is_append_only_shape(self, api):
        """PRD §2.4: "The append-only `CreditLedgerEntry` is the single
        exception: it carries `id` and `created_at` only, while `updated_at`
        and `version` are absent, because ledger entries are never modified
        after being written."

        Design: Corner/entities/credit_ledger_entry_immutable_event
        """
        member = register_member(email="m.led@x.com")
        resp = api.create_wallet_adjustment(
            member["id"],
            create_wallet_adjustment_payload(300, "PROMO_CREDIT", "seed"),
            SUPPORT,
        )
        entry = validate_success(resp, 201)
        assert_ledger_entry(entry)
        assert entry["amount_cents"] == 300
        assert entry["reason"] == "PROMO_CREDIT"

        entries = list_ledger(member["id"])
        assert len(entries) == 1
        assert_ledger_entry(entries[0])
        assert entries[0]["amount_cents"] == 300

    def test_list_pagination_envelope_defaults(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips that many items from the start of the result
        set and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/list_pagination_envelope_defaults
        """
        for title in ("T1", "T2", "T3"):
            validate_success(api.create_catalog_item(
                create_catalog_item_payload(
                    title=title, min_age_months=0, max_age_months=12,
                    developmental_stages=["INFANT"], piece_count=1,
                    retail_value_cents=1000, replacement_value_cents=500),
                ADMIN), 201)
        member = register_member(email="m.pag@x.com")
        headers = make_member_headers(member["id"])

        page1, meta1 = validate_paginated(api.list_catalog_items(
            headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_catalog_items(
            headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
