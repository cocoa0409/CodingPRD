"""Gala event creation, common resource fields, authentication and role
gates, bidder registration rules, initial states, and list pagination."""
from test_helpers import (
    ADMIN,
    CM,
    NON_EXISTENT_UUID,
    PO,
    ApiErrorId,
    api_client,
    assert_bidder,
    assert_bundle,
    assert_gala_event,
    assert_solicitation,
    create_bidder,
    create_bidder_payload,
    create_donor,
    create_donor_payload,
    create_event,
    create_gala_event_payload,
    create_pledged_solicitation,
    create_solicitation_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_bidder_headers,
    receive_item,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestGalaEventCreation:

    def test_create_gala_event_returns_draft_with_system_fields(self):
        """PRD section 3.1: "A new event starts in `DRAFT` status."
        PRD section 2.4: "Every resource served by this API — gala events,
        donors, bidders, solicitations, items, valuations, bundles, bids,
        invoices, payments, certificates, blackout windows, dispositions,
        and donor acknowledgments alike — carries a standard set of
        system-managed fields"

        Design: Corner/entities/gala_event_creation_defaults
        """
        resp = api_client.create_gala_event(create_gala_event_payload(), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_gala_event(data)
        assert data["status"] == "DRAFT", \
            f"new event must start DRAFT, got {data['status']}"
        assert data["version"] == 1, \
            f"version must start at 1, got {data['version']}"
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        # Config round-trips verbatim.
        assert data["min_bid_pct_bps"] == 3000
        assert data["min_bid_increment_cents"] == 500
        assert data["min_bid_floor_cents"] == 1000
        assert data["ack_threshold_cents"] == 25000
        assert data["solicitation_cooldown_days"] == 30
        assert data["cert_validity_months"] == 12
        assert data["cert_grace_days"] == 30
        assert len(data["bid_increment_tiers"]) == 3
        assert data["bid_increment_tiers"][-1]["up_to_cents"] is None

    def test_get_gala_event_not_found_returns_404(self):
        """PRD section 2.8: "path identifiers and body foreign-key
        references all exist, validated left to right; otherwise
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/gala_event_get_not_found_returns_404
        """
        resp = api_client.get_gala_event(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthenticationAndRoleGates:

    def test_missing_role_header_unauthenticated(self):
        """PRD section 2.1: "A request with missing or invalid headers, or
        one naming a role outside this list, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_role_header_unauthenticated
        """
        headers_without_role = {
            "X-User-ID": "some-user",
            "Content-Type": "application/json",
        }
        resp = api_client.create_gala_event(create_gala_event_payload(),
                                            headers_without_role)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_bidder_cannot_create_gala_event(self):
        """PRD section 2.1: "A request whose role is not permitted for the
        targeted operation is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)." PRD section 4: POST /gala-events is authorized for
        GalaAdmin only.

        Design: Corner/rbac/bidder_cannot_create_gala_event
        """
        resp = api_client.create_gala_event(
            create_gala_event_payload(),
            make_bidder_headers("00000000-0000-0000-0000-000000000001"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestDonorAndBidderRegistration:

    def test_create_donor_missing_email_rejected(self):
        """PRD section 2.8: "required fields are present, types and enum
        values are valid, and datetime ordering is valid" PRD section 3.2:
        "A `ProcurementOfficer` creates each donor with a `full_name`, a
        contact `email`, a `donor_type` of either `INDIVIDUAL` or
        `BUSINESS`, and an optional `tax_id`."

        Design: Corner/entities/donor_create_missing_required_field_rejected
        """
        payload = create_donor_payload()
        del payload["email"]
        resp = api_client.create_donor(payload, PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_paddle_number_unique_within_event(self):
        """PRD section 3.5: "Paddle numbers are unique within their event:
        a registration reusing a `paddle_no` already taken under the same
        `gala_event_id` is rejected with `ERR_PADDLE_TAKEN`."

        Design: Corner/entities/bidder_paddle_unique_per_event
        """
        ev1 = create_event()
        ev2 = create_event()
        first = create_bidder(ev1["id"], paddle_no=7, full_name="Bidder A")
        assert first["paddle_no"] == 7

        dup = api_client.create_bidder(
            create_bidder_payload(ev1["id"], paddle_no=7,
                                  full_name="Bidder B"),
            ADMIN,
        )
        validate_error(dup, ApiErrorId.ERR_PADDLE_TAKEN)

        other_event = api_client.create_bidder(
            create_bidder_payload(ev2["id"], paddle_no=7,
                                  full_name="Bidder C"),
            ADMIN,
        )
        data = validate_success(other_event, expected_status=201)
        assert_bidder(data)
        assert data["paddle_no"] == 7
        assert data["gala_event_id"] == ev2["id"]


class TestInitialStates:

    def test_initial_states_on_create(self):
        """PRD section 3.2: "A new solicitation starts in `DRAFT`."
        PRD section 3.4: "the bundle starts in `DRAFT` with
        `bundle_fmv_cents` at zero, `min_bid_cents` null,
        `min_bid_overridden` false, `current_high_bid_cents` null, and
        `published_at` null."
        PRD section 3.5: "New bidders start `REGISTERED`"

        Design: Corner/state_machines/initial_states_on_create
        """
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)
        api_client.advance_gala_event(event["id"], ADMIN)  # CATALOGING
        donor = create_donor()

        sol_resp = api_client.create_solicitation(
            create_solicitation_payload(donor["id"], event["id"]), PO)
        sol = validate_success(sol_resp, expected_status=201)
        assert_solicitation(sol)
        assert sol["status"] == "DRAFT"

        bundle_resp = api_client.create_bundle(
            {"gala_event_id": event["id"], "title": "Empty"}, CM)
        bundle = validate_success(bundle_resp, expected_status=201)
        assert_bundle(bundle)
        assert bundle["status"] == "DRAFT"
        assert bundle["bundle_fmv_cents"] == 0
        assert bundle["min_bid_cents"] is None
        assert bundle["min_bid_overridden"] is False
        assert bundle["current_high_bid_cents"] is None
        assert bundle["published_at"] is None

        bidder_resp = api_client.create_bidder(
            create_bidder_payload(event["id"], paddle_no=3), ADMIN)
        bidder = validate_success(bidder_resp, expected_status=201)
        assert_bidder(bidder)
        assert bidder["status"] == "REGISTERED"


class TestItemListingPagination:

    def test_items_list_pagination_and_filter(self):
        """PRD section 3.3: "Items can be listed with filters on
        `solicitation_id`, `donor_id`, `gala_event_id`, `bundle_id`, and
        `status`, with pagination."
        PRD section 2.3: "Paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/items_list_pagination_and_filter
        """
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        for i in range(3):
            donor = create_donor()
            sol = create_pledged_solicitation(donor["id"], event["id"])
            receive_item(sol["id"], title=f"I{i + 1}")

        page1, meta1 = validate_paginated(api_client.list_items(
            ADMIN, params={"gala_event_id": event["id"],
                           "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api_client.list_items(
            ADMIN, params={"gala_event_id": event["id"],
                           "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2

        ids = {item["id"] for item in page1} | {item["id"]
                                                for item in page2}
        assert len(ids) == 3, "pages must not overlap"


class TestGalaSettingsOcc:

    def test_gala_settings_patch_stale_version_rejected(self):
        """PRD section 2.7: "`PATCH /gala-events/{id}` requires
        `expected_gala_event_version`, matched against the gala event's
        current `version`." and "If the supplied value does not match the
        resource's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) — the client's view is stale and the
        write must not proceed on top of changes the client has not
        observed."

        Design: Corner/cross_cutting_complexity_layers/occ_gala_settings_stale_version
        """
        event = create_event()
        ev_id, ev_v = event["id"], event["version"]
        assert ev_v == 1

        first = validate_success(api_client.update_gala_event(
            ev_id, {"min_bid_pct_bps": 3500,
                    "expected_gala_event_version": ev_v}, ADMIN))
        assert first["version"] == 2
        assert first["min_bid_pct_bps"] == 3500

        stale = api_client.update_gala_event(
            ev_id, {"min_bid_pct_bps": 4000,
                    "expected_gala_event_version": ev_v}, ADMIN)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        after = get_success_data(api_client.get_gala_event(ev_id, ADMIN))
        assert after["min_bid_pct_bps"] == 3500, \
            "rejected replay must not modify the event"
        assert after["version"] == 2
