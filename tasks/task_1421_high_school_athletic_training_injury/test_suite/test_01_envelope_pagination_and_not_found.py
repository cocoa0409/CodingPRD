"""Response envelope, pagination, list filtering, and not-found behavior."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_athlete_as_trainer,
    create_injury_for,
    begin_care,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_trainer,
    trainer_headers,
    validate_error,
    validate_paginated,
)


class TestEnvelopeShape:

    def test_success_envelope_wraps_object_with_meta(self):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/endpoints/envelope_shape_on_success_and_error
        """
        tr1 = make_trainer()
        athlete = create_athlete_as_trainer(tr1, primary_sport="GOLF",
                                            team_level="JV")
        resp = api_client.get_athlete(athlete["id"], trainer_headers(tr1))
        body = resp.json()
        assert resp.status_code == 200
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"], \
            "success envelope carries meta.api_request_id"
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["id"] == athlete["id"]
        assert is_valid_uuid(body["data"]["id"])

    def test_error_envelope_and_unparseable_id_generic_404(self):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.8: "An identifier that cannot be parsed at all, or that
        addresses a resource family with no more specific error, draws the
        generic `ERR_NOT_FOUND`."

        Design: Corner/endpoints/envelope_shape_on_success_and_error
        """
        tr1 = make_trainer()
        resp = api_client.get_athlete("not-a-uuid", trainer_headers(tr1))
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err.get("message"), "error envelope carries a human message"
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"]


class TestPaginationAndFilters:

    def test_athlete_list_limit_offset_windows(self):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; if not provided, it defaults to 10, with a minimum
        of 1 and a maximum of 100."
        PRD §2.3: "Paginated list-based responses include the following
        fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_limit_offset_interaction
        """
        tr1 = make_trainer()
        for i in range(3):
            create_athlete_as_trainer(tr1, full_name=f"A{i}",
                                      guardian_email=None)
        page1, meta1 = validate_paginated(api_client.list_athletes(
            trainer_headers(tr1), params={"limit": 2, "offset": 0}))
        assert len(page1) == 2, f"page 1 must hold 2 rows, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0
        page2, meta2 = validate_paginated(api_client.list_athletes(
            trainer_headers(tr1), params={"limit": 2, "offset": 2}))
        assert len(page2) == 1, f"page 2 must hold 1 row, got {len(page2)}"
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"], "windows must be disjoint"

    def test_injury_list_combined_filters(self):
        """PRD §3.5: "The injury register filters by `athlete_id`,
        `event_id`, `evaluated_by_staff_id`, `reopen_of_id`, `status`, and
        `injury_type`."

        Design: Corner/endpoints/filtered_list_combination
        """
        tr1 = make_trainer()
        athlete_a = create_athlete_as_trainer(tr1, guardian_email=None)
        athlete_b = create_athlete_as_trainer(tr1, guardian_email=None)
        i1 = create_injury_for(athlete_a["id"], tr1, body_region="KNEE",
                               injury_type="SPRAIN",
                               evaluated_at="2026-07-31T10:00:00Z")
        i2 = create_injury_for(athlete_a["id"], tr1,
                               body_region="ANKLE_FOOT", injury_type="STRAIN",
                               evaluated_at="2026-07-31T11:00:00Z")
        begin_care(i2["id"], tr1)
        i3 = create_injury_for(athlete_b["id"], tr1, body_region="SHOULDER",
                               injury_type="SPRAIN", severity="MODERATE",
                               evaluated_at="2026-07-31T12:00:00Z")

        rows, meta = validate_paginated(api_client.list_injuries(
            trainer_headers(tr1),
            params={"athlete_id": athlete_a["id"], "status": "OPEN"}))
        assert len(rows) == 1 and rows[0]["id"] == i1["id"], (
            f"athlete_id+status must narrow to the one OPEN injury of A, "
            f"got {[r['id'] for r in rows]}")
        assert meta["total_count"] == 1

        sprains, meta2 = validate_paginated(api_client.list_injuries(
            trainer_headers(tr1), params={"injury_type": "SPRAIN"}))
        assert meta2["total_count"] == 2
        assert {r["id"] for r in sprains} == {i1["id"], i3["id"]}


class TestNotFoundCatalog:

    def test_athlete_not_found_returns_specific_404(self):
        """PRD §2.8: "Each resource family has its own not-found error so
        the caller learns exactly what was missing: `ERR_ATHLETE_NOT_FOUND`".

        Design: Corner/entities/athlete_not_found_returns_404
        """
        tr1 = make_trainer()
        resp = api_client.get_athlete(NON_EXISTENT_UUID,
                                      trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_ATHLETE_NOT_FOUND)

    def test_every_resource_family_not_found_code(self):
        """Note: the instance's final facet (ERR_BUDGET_NOT_FOUND at
        restock-order creation) is not translated — the PRD names that
        trigger only inside the approval narrative, so creation-time
        rejection is not PRD-covered.

        PRD §2.8: "Each resource family has its own not-found error so the
        caller learns exactly what was missing: `ERR_ATHLETE_NOT_FOUND`,
        `ERR_STAFF_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
        `ERR_INJURY_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
        `ERR_PROTOCOL_NOT_FOUND`, `ERR_EAP_NOT_FOUND`,
        `ERR_PHYSICAL_NOT_FOUND`, `ERR_BASELINE_NOT_FOUND`,
        `ERR_NOTIFICATION_NOT_FOUND`, `ERR_SUPPLY_ITEM_NOT_FOUND`, and
        `ERR_RESTOCK_ORDER_NOT_FOUND`."

        Design: Corner/entities/referenced_resources_not_found_return_404
        """
        def expect(path, error_id, headers=ADMIN):
            resp = api_client.get(path, headers=headers)
            validate_error(resp, error_id)

        expect(f"/staff/{NON_EXISTENT_UUID}", ApiErrorId.ERR_STAFF_NOT_FOUND)
        expect(f"/venues/{NON_EXISTENT_UUID}", ApiErrorId.ERR_VENUE_NOT_FOUND)
        expect(f"/events/{NON_EXISTENT_UUID}", ApiErrorId.ERR_EVENT_NOT_FOUND)
        expect(f"/injuries/{NON_EXISTENT_UUID}",
               ApiErrorId.ERR_INJURY_NOT_FOUND)
        expect(f"/referrals/{NON_EXISTENT_UUID}",
               ApiErrorId.ERR_REFERRAL_NOT_FOUND)
        expect(f"/rtp-protocols/{NON_EXISTENT_UUID}",
               ApiErrorId.ERR_PROTOCOL_NOT_FOUND)
        expect(f"/emergency-action-plans/{NON_EXISTENT_UUID}",
               ApiErrorId.ERR_EAP_NOT_FOUND)
        expect(f"/physicals/{NON_EXISTENT_UUID}",
               ApiErrorId.ERR_PHYSICAL_NOT_FOUND)
        expect(f"/baseline-tests/{NON_EXISTENT_UUID}",
               ApiErrorId.ERR_BASELINE_NOT_FOUND)
        expect(f"/guardian-notifications/{NON_EXISTENT_UUID}",
               ApiErrorId.ERR_NOTIFICATION_NOT_FOUND)
        expect(f"/supply-items/{NON_EXISTENT_UUID}",
               ApiErrorId.ERR_SUPPLY_ITEM_NOT_FOUND)
        expect(f"/restock-orders/{NON_EXISTENT_UUID}",
               ApiErrorId.ERR_RESTOCK_ORDER_NOT_FOUND)
        # Families with no dedicated code draw the generic one (PRD §2.8).
        expect(f"/coverage-assignments/{NON_EXISTENT_UUID}",
               ApiErrorId.ERR_NOT_FOUND)
        expect(f"/inventory-transactions/{NON_EXISTENT_UUID}",
               ApiErrorId.ERR_NOT_FOUND)


class TestUnauthenticated:

    def test_request_without_user_context_headers_rejected(self):
        """PRD §2.1: "A request missing either header, or presenting a role
        string outside that set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/request_missing_auth_headers_unauthenticated
        """
        resp = api_client.list_athletes(headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
