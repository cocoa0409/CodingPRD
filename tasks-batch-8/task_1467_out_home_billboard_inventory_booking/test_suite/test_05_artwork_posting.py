"""Artwork production pipeline, posting verification, and photo-proof lists."""
from test_helpers import (
    OA,
    PC,
    SP,
    ApiErrorId,
    api_client,
    confirm_flight,
    create_artwork_order_payload,
    create_posting_record_payload,
    deliver_artwork,
    get_success_data,
    make_field_installer_headers,
    make_operations_auditor_headers,
    report_posting,
    set_clock,
    setup_art_cleared_flight,
    setup_booked_flight,
    setup_held_flight,
    setup_live_flight,
    submit_and_approve_campaign,
    validate_error,
    validate_paginated,
    validate_success,
    verify_posting,
)


class TestArtworkRevisionLoop:

    def test_revision_loop_accumulates_count_across_cycles(self):
        """PRD section 3.6: "Production flows `SUBMITTED` → `IN_PRODUCTION` →
        `PRINTED` → `SHIPPED` → `DELIVERED`. From `IN_PRODUCTION`, the
        coordinator may send the order into `REVISION_REQUESTED`, which
        increments `revision_count` by 1, and a revised order loops back from
        `REVISION_REQUESTED` to `SUBMITTED` to run the pipeline again."

        Design: Difficulty/non_linear_state_machine/artwork_revision_loop_cycle
        """
        bundle = setup_booked_flight()
        order = get_success_data(api_client.create_artwork_order(
            create_artwork_order_payload(bundle["flight"]["id"]), PC))

        for _ in range(3):
            order = get_success_data(api_client.update_artwork_order(
                order["id"], {"status": "IN_PRODUCTION"}, PC))
            order = get_success_data(api_client.update_artwork_order(
                order["id"], {"status": "REVISION_REQUESTED"}, PC))
            order = get_success_data(api_client.update_artwork_order(
                order["id"], {"status": "SUBMITTED"}, PC))
        assert order["revision_count"] == 3, (
            f"the IN_PRODUCTION -> REVISION_REQUESTED -> SUBMITTED cycle ran "
            f"three times: expected revision_count 3, "
            f"got {order['revision_count']}"
        )

    def test_delivery_posts_surcharge_beyond_two_free_revisions(self):
        """PRD section 3.6: "At the `SHIPPED` → `DELIVERED` transition, the
        order's `production_charge_cents` is set to the excess of
        `revision_count` over two — zero when two or fewer revisions occurred
        — multiplied by 35,000 cents ($350 per revision beyond the second, two
        being free), and that amount is posted onto the campaign's
        `production_charges_cents` accumulator. The flight moves `BOOKED` →
        `ART_CLEARED`; when the flight has already advanced to `MISSED` or
        beyond, that flight transition is a no-op."

        Design: Difficulty/non_linear_state_machine/artwork_revision_loop_cycle
        """
        bundle = setup_booked_flight()
        order = get_success_data(api_client.create_artwork_order(
            create_artwork_order_payload(bundle["flight"]["id"]), PC))

        for _ in range(3):
            for status in ("IN_PRODUCTION", "REVISION_REQUESTED", "SUBMITTED"):
                order = get_success_data(api_client.update_artwork_order(
                    order["id"], {"status": status}, PC))
        for status in ("IN_PRODUCTION", "PRINTED", "SHIPPED", "DELIVERED"):
            order = get_success_data(api_client.update_artwork_order(
                order["id"], {"status": status}, PC))

        assert order["status"] == "DELIVERED"
        assert order["revision_count"] == 3
        assert order["production_charge_cents"] == 35_000, (
            f"only the third revision bills: (3 - 2) x 35000; "
            f"got {order['production_charge_cents']}"
        )

        flight = validate_success(
            api_client.get_flight(bundle["flight"]["id"], SP), 200)
        assert flight["status"] == "ART_CLEARED"

        campaign = validate_success(
            api_client.get_campaign(bundle["campaign"]["id"], SP), 200)
        assert campaign["production_charges_cents"] == 35_000, (
            f"the surcharge posts to the campaign accumulator: expected "
            f"35000, got {campaign['production_charges_cents']}"
        )


class TestArtworkCreationGates:

    def test_artwork_requires_booked_flight_rejected(self):
        """PRD section 3.6: "The flight must be `BOOKED` — submitting against
        any other flight state is `ERR_INVALID_STATE` — and at most one
        non-terminal artwork order may exist per flight, otherwise
        `ERR_ACTIVE_ARTWORK_ORDER_EXISTS`."

        Design: Corner/state_machines/artwork_requires_booked_flight_rejected
        """
        bundle = setup_held_flight()
        resp = api_client.create_artwork_order(
            create_artwork_order_payload(bundle["flight"]["id"]), PC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_artwork_dimension_mismatch_rejected(self):
        """PRD section 3.6: "The dimensions must equal the face's
        `width_inches` and `height_inches` exactly, otherwise
        `ERR_ARTWORK_DIMENSION_MISMATCH`."

        Design: Corner/validations/artwork_dimension_mismatch_rejected
        """
        bundle = setup_booked_flight()
        resp = api_client.create_artwork_order(
            create_artwork_order_payload(bundle["flight"]["id"],
                                         width_inches=168, height_inches=575),
            PC,
        )
        validate_error(resp, ApiErrorId.ERR_ARTWORK_DIMENSION_MISMATCH)

    def test_material_face_mismatch_rejected(self):
        """PRD section 3.6: "Material must suit the display type: a `DIGITAL`
        face requires `DIGITAL_FILE`, while a `STATIC` face requires `VINYL`
        or `POLYETHYLENE`; a mismatch is `ERR_MATERIAL_FACE_MISMATCH`."

        Design: Corner/validations/material_face_mismatch_rejected
        """
        bundle = setup_booked_flight()
        resp = api_client.create_artwork_order(
            create_artwork_order_payload(bundle["flight"]["id"],
                                         material="DIGITAL_FILE"),
            PC,
        )
        validate_error(resp, ApiErrorId.ERR_MATERIAL_FACE_MISMATCH)

    def test_active_artwork_order_uniqueness_rejected(self):
        """PRD section 3.6: "The flight must be `BOOKED` — submitting against
        any other flight state is `ERR_INVALID_STATE` — and at most one
        non-terminal artwork order may exist per flight, otherwise
        `ERR_ACTIVE_ARTWORK_ORDER_EXISTS`."
        PRD section 3.6: "Cancellation into `CANCELLED` is allowed from
        `SUBMITTED`, `IN_PRODUCTION`, or `REVISION_REQUESTED`."

        Design: Corner/validations/active_artwork_order_uniqueness_rejected
        """
        bundle = setup_booked_flight()
        first = get_success_data(api_client.create_artwork_order(
            create_artwork_order_payload(bundle["flight"]["id"]), PC))
        assert first["status"] == "SUBMITTED"

        dup = api_client.create_artwork_order(
            create_artwork_order_payload(bundle["flight"]["id"],
                                         creative_code="CR-2"),
            PC,
        )
        validate_error(dup, ApiErrorId.ERR_ACTIVE_ARTWORK_ORDER_EXISTS)

        get_success_data(api_client.update_artwork_order(
            first["id"], {"status": "CANCELLED"}, PC))
        second = validate_success(api_client.create_artwork_order(
            create_artwork_order_payload(bundle["flight"]["id"],
                                         creative_code="CR-2"),
            PC,
        ), 201)
        assert second["status"] == "SUBMITTED"


class TestPostingVerification:

    def test_verification_stamps_auditor_and_clears_flight_live(self):
        """PRD section 3.6: "On verification, `verified_by_user_id` is stamped
        with the verifier's identity, and timing decides what the flight does
        next. When `posted_on` is no later than two days after `start_date`,
        the flight moves `ART_CLEARED` → `LIVE` on time."

        Design: Difficulty/transitive_cascade/posting_verify_cascade_to_campaign_activation
        """
        bundle = setup_art_cleared_flight()
        set_clock("2026-08-10T00:00:00Z")
        posting = report_posting(bundle["flight"]["id"], posted_on="2026-08-10",
                                 installer_id="installer-1")

        verified = verify_posting(posting["id"], auditor_id="auditor-1")
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "auditor-1"

        flight = validate_success(
            api_client.get_flight(bundle["flight"]["id"], SP), 200)
        assert flight["status"] == "LIVE", (
            f"posted_on 2026-08-10 is within two days of start_date "
            f"2026-08-10: expected LIVE, got {flight['status']}"
        )

    def test_first_live_flight_activates_campaign(self):
        """PRD section 3.4: "Activation is automatic: the campaign moves
        `APPROVED` → `ACTIVE` the moment its first flight enters `LIVE`."
        PRD section 3.6: "If this flight is its campaign's first to reach
        `LIVE`, the campaign moves `APPROVED` → `ACTIVE`; affected delivery
        postures recompute."

        Design: Difficulty/transitive_cascade/posting_verify_cascade_to_campaign_activation
        """
        bundle = setup_art_cleared_flight()
        pre = validate_success(
            api_client.get_campaign(bundle["campaign"]["id"], SP), 200)
        assert pre["status"] == "APPROVED"

        set_clock("2026-08-10T00:00:00Z")
        posting = report_posting(bundle["flight"]["id"], posted_on="2026-08-10")
        verify_posting(posting["id"])

        campaign = validate_success(
            api_client.get_campaign(bundle["campaign"]["id"], SP), 200)
        assert campaign["status"] == "ACTIVE", (
            f"the campaign's first LIVE flight activates it: "
            f"got {campaign['status']}"
        )

    def test_verifier_equals_installer_rejected(self):
        """PRD section 3.6: "Verification enforces segregation of duties —
        the verifier's `X-User-ID` must differ from `installer_user_id`,
        otherwise `ERR_SEGREGATION_OF_DUTIES` — and at most one record per
        flight may ever reach `VERIFIED`; a second verification is
        `ERR_INVALID_STATE`."
        PRD section 2.11: "A posting record may only be verified or rejected
        by an `OperationsAuditor` whose `X-User-ID` differs from the record's
        `installer_user_id` — an installer can never audit their own work."

        Design: Corner/validations/verifier_equals_installer_rejected
        """
        bundle = setup_art_cleared_flight()
        set_clock("2026-08-10T00:00:00Z")
        posting = report_posting(bundle["flight"]["id"], posted_on="2026-08-10",
                                 installer_id="installer-1")

        same_user = api_client.update_posting_record(
            posting["id"], {"status": "VERIFIED"},
            make_operations_auditor_headers("installer-1"),
        )
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        ok = validate_success(api_client.update_posting_record(
            posting["id"], {"status": "VERIFIED"},
            make_operations_auditor_headers("auditor-9"),
        ), 200)
        assert ok["status"] == "VERIFIED"

    def test_posting_before_artwork_cleared_rejected(self):
        """PRD section 3.6: "The flight must be `ART_CLEARED` or `MISSED`,
        otherwise `ERR_FLIGHT_NOT_POSTABLE`, and `posted_on` must fall no
        earlier than seven days before the flight's `start_date` and no later
        than the clock's current date, otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/errors/posting_before_artwork_cleared_rejected
        """
        bundle = setup_booked_flight()
        set_clock("2026-08-10T00:00:00Z")
        resp = api_client.create_posting_record(
            create_posting_record_payload(bundle["flight"]["id"],
                                          posted_on="2026-08-10",
                                          photo_proof_url="https://proof.example/e.jpg"),
            make_field_installer_headers("installer-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_POSTABLE)

        records, meta = validate_paginated(
            api_client.list_flight_posting_records(
                bundle["flight"]["id"], OA))
        assert records == [] and meta["total_count"] == 0


class TestPostingRecordListPagination:

    def test_posting_records_list_pagination_envelope(self):
        """PRD section 2.3: "Paginated list responses include `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        envelope."
        PRD section 2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/endpoints/posting_records_list_pagination_envelope
        """
        bundle = setup_art_cleared_flight()
        set_clock("2026-08-10T00:00:00Z")
        for i in range(3):
            report_posting(bundle["flight"]["id"], posted_on="2026-08-10",
                           installer_id="installer-1",
                           photo_proof_url=f"https://proof.example/{i}.jpg")

        resp = api_client.list_flight_posting_records(
            bundle["flight"]["id"], OA, params={"limit": 2, "offset": 0})
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
