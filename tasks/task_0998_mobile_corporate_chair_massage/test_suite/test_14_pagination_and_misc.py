"""Pagination envelope, ledger-style record shape, and same-response
mutation visibility."""
from test_helpers import (
    api_client,
    assign_therapist,
    confirm_booking,
    create_event_booking,
    get_booking,
    setup_completed_booking,
    setup_region_account_therapist,
    setup_scheduling_booking,
    submit_survey,
    validate_paginated,
    validate_success,
)


class TestPagination:
    def test_list_bookings_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        when omitted it defaults to 10, and it accepts values from a minimum
        of 1 to a maximum of 100. The `offset` parameter states how many
        items to skip and defaults to 0. Unless otherwise specified, every
        list endpoint returns resources sorted by their creation timestamp in
        ascending order, and the `meta` object of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_bookings_pagination_envelope
        """
        ctx = setup_region_account_therapist()
        for i in range(12):
            create_event_booking(
                ctx, site_address=f"B{i + 1}", event_date=f"2026-06-{i + 1:02d}",
            )
        resp = api.list_bookings(ctx["organizer"])
        assert resp.status_code == 200
        body = resp.json()
        assert body["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, f"Default page limit is 10, got {meta['limit']}"
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert len(data) == 10
        data2, meta2 = validate_paginated(
            api.list_bookings(ctx["organizer"], params={"offset": 10})
        )
        assert len(data2) == 2
        assert meta2["has_more"] is False


class TestLedgerStyleRecords:
    def test_satisfaction_survey_common_fields_false_no_update(self, api):
        """PRD §2.5: "Two resources are deliberate exceptions: a satisfaction
        survey and a payout ledger entry are immutable, ledger-style records
        and carry only `id` and `created_at` — both `updated_at` and `version`
        are absent from them."

        Design: Corner/entities/satisfaction_survey_common_fields_false_no_update
        """
        ctx = setup_completed_booking(num_claims_completed=1)
        resp = api.submit_satisfaction_survey(
            ctx["claims"][0]["id"], {"rating": 5, "comment": "great"}, ctx["organizer"],
        )
        assert resp.status_code == 201
        survey = validate_success(resp, expected_status=201)
        assert survey["id"], "Survey must carry a server-minted id"
        assert survey["created_at"], "Survey must carry created_at"
        assert "version" not in survey, "Ledger-style record must not carry version"
        assert "updated_at" not in survey, "Ledger-style record must not carry updated_at"


class TestImmediateConsistency:
    def test_immediate_visibility_of_booking_mutation_in_same_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §2.9: "Derived aggregates are maintained eagerly, never lazily:
        every mutation that changes an input to a derived field recomputes
        that field immediately within the same request, and each such
        recomputation is itself a mutation of the owning resource that
        refreshes its `updated_at` and increments its `version` — even when
        the client's request targeted a different resource."

        Design: Corner/consistency_model/immediate_visibility_of_booking_mutation_in_same_response
        """
        ctx = setup_scheduling_booking(assign=True)
        booking_id = ctx["booking"]["id"]
        prior = get_booking(ctx, booking_id)
        resp = api.confirm_booking(
            booking_id, {"expected_booking_version": prior["version"]}, ctx["organizer"],
        )
        confirmed = validate_success(resp, expected_status=200)
        assert confirmed["status"] == "CONFIRMED", (
            "The confirm response itself must carry the updated resource"
        )
        assert confirmed["version"] == prior["version"] + 1
