"""Registration, tagging, barcode assignment, price constraints, item listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_consignor,
    assert_item,
    book_slot,
    check_in_booking,
    create_event,
    create_item_for,
    create_slot,
    make_consignor_headers,
    register_consignor,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestConsignorRegistration:

    def test_consignor_code_assigned_by_registration_order(self, api, organizer_headers):
        """PRD §3.2: "A new consignor arrives in status `ACTIVE` and is immediately assigned a `consignor_code`: the letter "C" followed by a zero-padded four-digit sequence number, where the sequence is the consignor's one-based registration order within the event, ordered by `created_at` ascending — the first consignor of an event receives C0001."
        PRD §2.10: "A `Consignor` carries `sold_count`, `unsold_count`, `rejected_count`, and `sold_gross_cents`".

        Design: Corner/entities/consignor_creation_assigns_code_and_defaults
        """
        event = create_event()
        c1 = register_consignor(event["id"], "Ann")
        c2 = register_consignor(event["id"], "Bob")

        assert_consignor(c1)
        assert_consignor(c2)
        assert c1["consignor_code"] == "C0001", (
            f"First consignor of the event must receive C0001, got {c1['consignor_code']}"
        )
        assert c2["consignor_code"] == "C0002", (
            f"Second consignor of the event must receive C0002, got {c2['consignor_code']}"
        )
        for consignor in (c1, c2):
            assert consignor["status"] == "ACTIVE"
            assert consignor["sold_count"] == 0
            assert consignor["unsold_count"] == 0
            assert consignor["rejected_count"] == 0
            assert consignor["sold_gross_cents"] == 0


class TestItemTagging:

    def test_item_barcode_and_defaults(self, api, organizer_headers):
        """PRD §3.3: "The item's `sale_event_id` is copied from its consignor at creation, and its `barcode` is built from the consignor's `consignor_code`, a hyphen, and a zero-padded four-digit sequence reflecting the item's one-based creation order for that consignor by `created_at` ascending — so the first item tagged by consignor C0001 carries barcode C0001-0001."
        PRD §3.3: "A new item starts in status `TAGGED`".

        Design: Corner/entities/item_creation_computes_barcode_and_defaults
        """
        event = create_event()
        consignor = register_consignor(event["id"], "Ann")

        it1 = create_item_for(consignor["id"], price_cents=500, title="Blocks")
        it2 = create_item_for(consignor["id"], price_cents=700, title="Doll")

        assert_item(it1)
        assert_item(it2)
        assert it1["barcode"] == "C0001-0001", (
            f"First item of consignor C0001 must carry barcode C0001-0001, got {it1['barcode']}"
        )
        assert it2["barcode"] == "C0001-0002", (
            f"Second item of consignor C0001 must carry barcode C0001-0002, got {it2['barcode']}"
        )
        for item in (it1, it2):
            assert item["status"] == "TAGGED"
            assert item["discount_eligible"] is True, "discount_eligible defaults to true"
            assert item["donate_flag"] is False, "donate_flag defaults to false"
            assert item["sale_event_id"] == event["id"], (
                "sale_event_id must be copied from the consignor at creation"
            )

    def test_price_below_minimum_rejected(self, api, organizer_headers):
        """PRD §3.3: "The tag price must be at least 200 cents ($2.00) — a lower price is rejected with `ERR_PRICE_BELOW_MINIMUM` (HTTP 400) — and must be a whole multiple of 50 cents, or the create fails with `ERR_PRICE_INCREMENT_VIOLATION` (HTTP 400)."

        Design: Corner/entities/item_price_below_minimum_rejected
        """
        event = create_event()
        consignor = register_consignor(event["id"], "Ann")

        resp = api.create_item(
            {"consignor_id": consignor["id"], "title": "Cheap",
             "category": "TOYS", "price_cents": 199},
            make_consignor_headers(consignor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_BELOW_MINIMUM)

        data, meta = validate_paginated(
            api.list_items(organizer_headers, params={"consignor_id": consignor["id"]})
        )
        assert meta["total_count"] == 0 and data == [], (
            "A rejected create must not leave an item row behind"
        )

    def test_price_increment_violation_rejected(self, api, organizer_headers):
        """PRD §3.3: "The tag price must be at least 200 cents ($2.00) — a lower price is rejected with `ERR_PRICE_BELOW_MINIMUM` (HTTP 400) — and must be a whole multiple of 50 cents, or the create fails with `ERR_PRICE_INCREMENT_VIOLATION` (HTTP 400)."

        Design: Corner/entities/item_price_increment_violation_rejected
        """
        event = create_event()
        consignor = register_consignor(event["id"], "Ann")

        resp = api.create_item(
            {"consignor_id": consignor["id"], "title": "Odd",
             "category": "TOYS", "price_cents": 225},
            make_consignor_headers(consignor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_INCREMENT_VIOLATION)

    def test_get_missing_item_returns_404(self, api, organizer_headers):
        """PRD §2.8: "third, existence of every referenced resource, validated left-to-right along the path and then the body — a missing sale event surfaces `ERR_SALE_EVENT_NOT_FOUND`, and the same pattern yields `ERR_CONSIGNOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`".

        Design: Corner/entities/get_missing_item_not_found_returns_404
        """
        create_event()
        resp = api.get_item(NON_EXISTENT_UUID, organizer_headers)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_FOUND)


class TestItemListing:

    def test_list_items_pagination_envelope(self, api, organizer_headers):
        """PRD §2.3: "List responses sort by `created_at` ascending, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.3: "items can be listed with `sale_event_id`, `consignor_id`, `status`, and `barcode` filters".

        Design: Corner/endpoints/list_items_pagination_envelope
        """
        event = create_event()
        consignor = register_consignor(event["id"], "Ann")
        for title, price in (("I1", 500), ("I2", 600), ("I3", 700)):
            create_item_for(consignor["id"], price_cents=price, title=title)

        page1, meta1 = validate_paginated(
            api.list_items(organizer_headers,
                           params={"consignor_id": consignor["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_items(organizer_headers,
                           params={"consignor_id": consignor["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        titles = [row["title"] for row in page1 + page2]
        assert titles == ["I1", "I2", "I3"], (
            f"Rows must be ordered by created_at ascending, got {titles}"
        )
