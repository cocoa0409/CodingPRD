"""Inventory stand-up: faces, rate cards, and permit renewal chains."""
from test_helpers import (
    ApiErrorId,
    CO,
    IM,
    NON_EXISTENT_UUID,
    SP,
    api_client,
    assert_face,
    assert_face_posture_consistency,
    create_face_payload,
    create_face_with_permit,
    create_permit_payload,
    create_published_rate_card,
    create_rate_card_payload,
    get_success_data,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFaceCreation:

    def test_face_creation_applies_defaults_and_computed_posture(self):
        """PRD section 3.1: "A new face is born `AVAILABLE` with
        `booking_posture` `OPEN` and a null `current_permit_id`."
        PRD section 2.7: "The `booking_posture` field is `OPEN` when the face
        is `AVAILABLE`, `RESTRICTED` while it is `UNDER_MAINTENANCE`, and
        `BLOCKED` when it is `PERMIT_SUSPENDED` or `DECOMMISSIONED`."

        Design: Corner/entities/face_creation_applies_defaults_and_computed_posture
        """
        resp = api_client.create_face(
            create_face_payload(face_code="F-NYC-100", structure_code="ST-100",
                                illuminated=False, daily_traffic_count=50_000),
            IM,
        )
        face = validate_success(resp, 201)
        assert_face(face)
        assert face["status"] == "AVAILABLE"
        assert face["booking_posture"] == "OPEN"
        assert face["current_permit_id"] is None
        assert is_valid_uuid(face["id"])
        assert_face_posture_consistency(face)

        reread = validate_success(api_client.get_face(face["id"], IM), 200)
        assert reread["status"] == "AVAILABLE"
        assert reread["booking_posture"] == "OPEN"

    def test_static_face_with_loop_slots_rejected(self):
        """PRD section 3.1: "A `DIGITAL` face additionally requires
        `loop_slots_total` — the number of advertising slots in its 64-second
        loop, between 1 and 16 inclusive — while a `STATIC` face must omit
        `loop_slots_total` entirely; either violation is rejected with
        `ERR_DIGITAL_SLOTS_REQUIRED`."

        Design: Corner/entities/static_face_with_loop_slots_rejected
        """
        resp = api_client.create_face(
            create_face_payload(face_code="F-BAD", structure_code="ST-BAD",
                                display_type="STATIC", illuminated=False,
                                daily_traffic_count=50_000, loop_slots_total=8),
            IM,
        )
        validate_error(resp, ApiErrorId.ERR_DIGITAL_SLOTS_REQUIRED)

    def test_digital_face_without_loop_slots_rejected(self):
        """PRD section 3.1: "A `DIGITAL` face additionally requires
        `loop_slots_total` — the number of advertising slots in its 64-second
        loop, between 1 and 16 inclusive — while a `STATIC` face must omit
        `loop_slots_total` entirely; either violation is rejected with
        `ERR_DIGITAL_SLOTS_REQUIRED`."

        Design: Corner/entities/digital_face_without_loop_slots_rejected
        """
        payload = create_face_payload(face_code="F-BAD2", structure_code="ST-BAD2",
                                      display_type="DIGITAL", illuminated=True,
                                      daily_traffic_count=300_000)
        assert "loop_slots_total" not in payload
        resp = api_client.create_face(payload, IM)
        validate_error(resp, ApiErrorId.ERR_DIGITAL_SLOTS_REQUIRED)

    def test_face_not_found_returns_404(self):
        """PRD section 2.8: "When an endpoint path contains resource
        identifiers, the system validates their existence strictly
        left-to-right and rejects the request at the first identifier that
        does not resolve, returning the not-found error that corresponds to
        that resource type: `ERR_RATE_CARD_NOT_FOUND`, `ERR_FACE_NOT_FOUND`,
        ..."

        Design: Corner/entities/face_not_found_returns_404
        """
        resp = api_client.get_face(NON_EXISTENT_UUID, IM)
        validate_error(resp, ApiErrorId.ERR_FACE_NOT_FOUND)

    def test_face_computed_field_input_ignored(self):
        """PRD section 2.7: "A face's sellability is exposed through two
        read-only derived fields, recomputed whenever the underlying state
        changes."
        PRD section 3.1: "A new face is born `AVAILABLE` with
        `booking_posture` `OPEN` and a null `current_permit_id`."

        Design: Corner/entities/face_computed_field_input_ignored
        """
        resp = api_client.create_face(
            create_face_payload(face_code="F-NYC-101", structure_code="ST-101",
                                illuminated=False, daily_traffic_count=50_000,
                                booking_posture="BLOCKED"),
            IM,
        )
        face = validate_success(resp, 201)
        assert face["booking_posture"] == "OPEN", (
            f"client-supplied booking_posture must be ignored; "
            f"a new face is born OPEN, got {face['booking_posture']}"
        )


class TestRateCardPublishGates:

    def test_rate_card_publish_tier_config_rejected(self):
        """PRD section 3.1: "Publishing a card (the `DRAFT` → `PUBLISHED`
        transition) enforces two checks: the tier-2 threshold must be strictly
        greater than the tier-1 threshold, otherwise `ERR_INVALID_REQUEST`;
        and no other card for the same `market_code` and `display_type` pair
        may already be `PUBLISHED`, otherwise
        `ERR_RATE_CARD_DUPLICATE_PUBLISHED`."

        Design: Corner/validations/rate_card_publish_tier_config_rejected
        """
        card = validate_success(api_client.create_rate_card(
            create_rate_card_payload(traffic_tier_1_threshold=250_000,
                                     traffic_tier_2_threshold=100_000),
            IM,
        ), 201)
        resp = api_client.update_rate_card(
            card["id"],
            {"status": "PUBLISHED", "expected_rate_card_version": card["version"]},
            IM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        reread = validate_success(api_client.get_rate_card(card["id"], IM), 200)
        assert reread["status"] == "DRAFT"

    def test_rate_card_duplicate_published_rejected(self):
        """PRD section 3.1: "Publishing a card (the `DRAFT` → `PUBLISHED`
        transition) enforces two checks: the tier-2 threshold must be strictly
        greater than the tier-1 threshold, otherwise `ERR_INVALID_REQUEST`;
        and no other card for the same `market_code` and `display_type` pair
        may already be `PUBLISHED`, otherwise
        `ERR_RATE_CARD_DUPLICATE_PUBLISHED`."

        Design: Corner/validations/rate_card_duplicate_published_rejected
        """
        create_published_rate_card()  # card A: (NYC, STATIC) PUBLISHED
        card_b = validate_success(api_client.create_rate_card(
            create_rate_card_payload(base_weekly_cents=300_000), IM,
        ), 201)
        resp = api_client.update_rate_card(
            card_b["id"],
            {"status": "PUBLISHED",
             "expected_rate_card_version": card_b["version"]},
            IM,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_CARD_DUPLICATE_PUBLISHED)
        reread = validate_success(api_client.get_rate_card(card_b["id"], IM), 200)
        assert reread["status"] == "DRAFT"


class TestPermitRenewalChain:

    def test_permit_self_reference_chain_links(self):
        """PRD section 3.2: "When the filing carries a `supersedes_permit_id`,
        the referenced permit must currently be `ACTIVE` or `RENEWAL_PENDING`;
        filing succeeds by moving that predecessor to `SUPERSEDED` and pointing
        the face's `current_permit_id` at the new permit."
        PRD section 3.2: "A permit's renewal chain is inspectable through the
        successor inquiry, which lists the permits whose `supersedes_permit_id`
        points at a given permit."
        PRD section 3.2: "When the clock stands anywhere from thirty days
        before `expires_on` up to but not including `expires_on`, the sweep
        moves an `ACTIVE` permit to `RENEWAL_PENDING`."

        Design: Corner/entities/permit_self_reference_chain_links
        """
        face, permit = create_face_with_permit(
            face_code="F-NYC-102", permit_number="P-OLD",
            permit_expires="2026-09-15T00:00:00Z",
        )
        set_clock("2026-08-16T00:00:00Z")
        p1_mid = validate_success(api_client.get_permit(permit["id"], CO), 200)
        assert p1_mid["status"] == "RENEWAL_PENDING", (
            f"permit expiring 2026-09-15 must be RENEWAL_PENDING once the "
            f"clock enters the 30-day renewal window, got {p1_mid['status']}"
        )

        p2 = validate_success(api_client.create_permit(
            create_permit_payload(
                face["id"], permit_number="P-NEW",
                issued_on="2026-08-16T00:00:00Z",
                expires_on="2027-09-15T00:00:00Z",
                supersedes_permit_id=permit["id"],
            ),
            CO,
        ), 201)
        assert p2["status"] == "ACTIVE"

        p1_after = validate_success(api_client.get_permit(permit["id"], CO), 200)
        assert p1_after["status"] == "SUPERSEDED"

        successors, _meta = validate_paginated(
            api_client.list_permit_successors(permit["id"], CO))
        assert [s["id"] for s in successors] == [p2["id"]]

        face_after = validate_success(api_client.get_face(face["id"], CO), 200)
        assert face_after["current_permit_id"] == p2["id"]
