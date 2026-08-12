"""Rate card authoring, half-open window rule, and OCC revision."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_rate_card,
    create_active_rate_card,
    create_rate_card_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_rate_card_creation_defaults_and_system_fields(api):
    """PRD: "A new card is born in `DRAFT` status and prices nothing until
    activated."
    PRD: "Every resource is identified by an `id` that is a server-minted UUID
    with no type prefix."
    PRD: "The new card's `supersedes_id` points back at the source card's `id`
    (it is null on original cards)"
    PRD: "Computed or system-owned fields supplied in a request body are
    ignored silently — they are not an error."

    Design: Corner/entities/rate_card_creation_defaults_and_system_fields
    """
    payload = create_rate_card_payload(status="ACTIVE", version=99)
    resp = api.create_rate_card(payload, ADMIN)
    card = validate_success(resp, expected_status=201)
    assert_rate_card(card)
    assert card["status"] == "DRAFT", "client-supplied status must be ignored"
    assert card["supersedes_id"] is None, "original card's supersedes_id is null"
    assert is_valid_uuid(card["id"])
    assert is_iso8601_timestamp(card["created_at"])
    assert is_iso8601_timestamp(card["updated_at"])
    assert isinstance(card["version"], int)

    fetched = validate_success(api.get_rate_card(card["id"], ADMIN))
    assert fetched["status"] == "DRAFT"
    assert fetched["supersedes_id"] is None


class TestHalfOpenWindowOverlap:
    def test_rate_card_overlapping_window_rejected(self, api):
        """PRD: "What is forbidden is two `ACTIVE` cards with the same key
        whose half-open windows share even a single day."
        PRD: "if any other `ACTIVE` card with the identical key has a half-open
        window overlapping this card's window by even one day, activation is
        rejected with `ERR_RATE_CARD_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/rate_card_half_open_window_overlap
        """
        card_a = create_active_rate_card(
            effective_from="2026-05-01", effective_to="2026-08-01"
        )
        assert card_a["status"] == "ACTIVE"
        card_b = validate_success(
            api.create_rate_card(
                create_rate_card_payload(
                    bill_rate_ceiling_cents=12500,
                    effective_from="2026-06-01",
                    effective_to="2026-09-01",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        resp = api.activate_rate_card(card_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RATE_CARD_WINDOW_OVERLAP)
        after = validate_success(api.get_rate_card(card_b["id"], ADMIN))
        assert after["status"] == "DRAFT", "rejected activation must leave the card DRAFT"

    def test_rate_card_adjacent_window_allowed(self, api):
        """PRD: "Two cards with the same key may touch — one card's
        `effective_from` equal to another's `effective_to` — without
        conflicting; adjacency with a gap of zero days is explicitly allowed."

        Design: Difficulty/resource_temporal_overlap/rate_card_half_open_window_overlap
        """
        card_a = create_active_rate_card(
            effective_from="2026-05-01", effective_to="2026-08-01"
        )
        assert card_a["status"] == "ACTIVE"
        card_c = validate_success(
            api.create_rate_card(
                create_rate_card_payload(
                    bill_rate_ceiling_cents=13000,
                    effective_from="2026-08-01",
                    effective_to="2026-11-01",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        activated = validate_success(api.activate_rate_card(card_c["id"], ADMIN))
        assert activated["status"] == "ACTIVE", (
            "half-open adjacency ([.., 2026-08-01) then [2026-08-01, ..)) is not overlap"
        )

    def test_rate_card_same_window_different_key_allowed(self, api):
        """PRD: "A rate card prices one key — the triple of `role_code`,
        `skill_code` and `geo_code` — over a half-open effective window that
        runs from `effective_from` up to but not including `effective_to`."
        PRD: "What is forbidden is two `ACTIVE` cards with the same key whose
        half-open windows share even a single day."

        Design: Difficulty/resource_temporal_overlap/rate_card_half_open_window_overlap
        """
        card_a = create_active_rate_card(
            effective_from="2026-06-01", effective_to="2026-09-01"
        )
        assert card_a["status"] == "ACTIVE"
        card_d = validate_success(
            api.create_rate_card(
                create_rate_card_payload(
                    skill_code="PYTHON",
                    bill_rate_ceiling_cents=12500,
                    effective_from="2026-06-01",
                    effective_to="2026-09-01",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        activated = validate_success(api.activate_rate_card(card_d["id"], ADMIN))
        assert activated["status"] == "ACTIVE", (
            "identical window under a different skill_code is a different key"
        )


class TestRateCardRevisionOcc:
    def test_revision_creates_draft_supersede_and_bumps_source(self, api):
        """PRD: "Creating a revision of a source card — allowed while the
        source is `ACTIVE` or `DRAFT` — produces a brand-new card in `DRAFT`
        whose fields are copied from the source, with any of
        `pay_rate_floor_cents`, `bill_rate_ceiling_cents`, `max_markup_pct`,
        `effective_from` and `effective_to` overridden by values supplied in
        the request."
        PRD: "The new card's `supersedes_id` points back at the source card's
        `id` (it is null on original cards), and the act of revising increments
        the source card's `version` by one"

        Design: Corner/cross_cutting/rate_card_revision_occ_stale
        """
        card = validate_success(
            api.create_rate_card(create_rate_card_payload(), ADMIN), expected_status=201
        )
        revision = validate_success(
            api.create_rate_card_revision(
                card["id"],
                {
                    "expected_rate_card_version": card["version"],
                    "bill_rate_ceiling_cents": 11500,
                },
                ADMIN,
            ),
            expected_status=201,
        )
        assert_rate_card(revision)
        assert revision["id"] != card["id"]
        assert revision["status"] == "DRAFT"
        assert revision["supersedes_id"] == card["id"]
        assert revision["bill_rate_ceiling_cents"] == 11500, "override applied"
        assert revision["pay_rate_floor_cents"] == card["pay_rate_floor_cents"], (
            "non-overridden fields copy from the source"
        )
        source_after = validate_success(api.get_rate_card(card["id"], ADMIN))
        assert source_after["version"] == card["version"] + 1, (
            "revising increments the source card's version by one"
        )

    def test_revision_stale_version_rejected(self, api):
        """PRD: "Creating a revision of a rate card works the same way: the
        request must carry `expected_rate_card_version` matching the source
        card's current `version`. A mismatch is rejected with
        `ERR_STALE_RATE_CARD_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/rate_card_revision_occ_stale
        """
        card = validate_success(
            api.create_rate_card(create_rate_card_payload(), ADMIN), expected_status=201
        )
        observed_version = card["version"]
        validate_success(
            api.create_rate_card_revision(
                card["id"],
                {
                    "expected_rate_card_version": observed_version,
                    "bill_rate_ceiling_cents": 11500,
                },
                ADMIN,
            ),
            expected_status=201,
        )
        resp = api.create_rate_card_revision(
            card["id"],
            {
                "expected_rate_card_version": observed_version,
                "bill_rate_ceiling_cents": 11000,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_RATE_CARD_VERSION)
        lines, meta = validate_paginated(
            api.list_rate_cards(ADMIN, params={"supersedes_id": card["id"]})
        )
        assert meta["total_count"] == 1, (
            "the stale replay must not create a third card"
        )
