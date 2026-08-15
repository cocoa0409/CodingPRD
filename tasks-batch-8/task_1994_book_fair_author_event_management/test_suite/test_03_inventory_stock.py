"""Stock lines: creation, commit gate, delivery, damage, availability math."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_copy_conservation,
    create_stock_line_payload,
    make_school,
    make_publisher,
    make_fair,
    make_fair_scheduled,
    make_accepted_agreement,
    make_delivered_stock_line,
    make_fair_open,
    make_fair_stocking,
    TEST_USERS,
)


class TestStockLineListing:
    def test_stockline_filtered_list_fk_reverse(self, api):
        """PRD §2.3: "List endpoints also accept optional equality filters drawn
        from the resource's own foreign keys and enumerations (for example
        `fair_id`, `status`, `line_type`, `mode`, `kind`, `channel`,
        `venue_key`, `publisher_party_id`, `author_party_id`, `school_party_id`,
        `agreement_id`, `stock_line_id`, `booking_id`, or `session_id`, as
        applicable per resource)."

        Design: Corner/endpoints/stockline_filtered_list_fk_reverse
        """
        school = make_school()
        pub = make_publisher()
        fair_a, agr_a = make_fair_stocking(school["id"], pub["id"], title="Fair A")
        fair_b, agr_b = make_fair_stocking(school["id"], pub["id"], title="Fair B",
                                           venue_key="CAFETERIA")
        for isbn, title in (("9780000000001", "Alpha"), ("9780000000002", "Beta")):
            validate_success(api_client.create_stock_line(
                create_stock_line_payload(
                    fair_id=fair_a["id"], agreement_id=agr_a["id"],
                    isbn=isbn, title=title,
                ), ORG,
            ), expected_status=201)
        validate_success(api_client.create_stock_line(
            create_stock_line_payload(
                fair_id=fair_b["id"], agreement_id=agr_b["id"],
                isbn="9780000000003", title="Gamma", line_type="BACKLIST", qty_committed=8,
            ), ORG,
        ), expected_status=201)
        data = validate_success(api_client.list_stock_lines(
            ORG, params={"fair_id": fair_a["id"]}
        ))
        assert isinstance(data, list) and len(data) == 2
        for entry in data:
            assert entry["fair_id"] == fair_a["id"]

ORG = TEST_USERS["organizer_headers"]


class TestStockLineCreate:
    def test_stockline_computed_qty_sold_input_rejected(self, api):
        """PRD §3.3: "A new line is `QUOTED` with all quantity counters at zero
        and `qty_on_hand_counted` null."
        PRD §2.9: "Request-shape validation (priority 7, `ERR_VALIDATION`, HTTP
        400) rejects missing required fields, wrong types, invalid enum values,
        out-of-range numbers ... and any unknown field."

        Design: Corner/entities/stockline_computed_qty_sold_input_rejected
        """
        school = make_school()
        pub = make_publisher()
        fair = make_fair(school["id"])
        agr = validate_success(api.create_agreement(
            {"fair_id": fair["id"], "publisher_party_id": pub["id"],
             "discount_pct": 0.40, "return_cap_pct": 0.25, "restocking_fee_pct": 0.10,
             "markdown_allowance_pct": 0.20, "freight_responsibility": "ORGANIZER",
             "offer_expiry_hours": 72}, ORG,
        ), expected_status=201)
        payload = create_stock_line_payload(fair_id=fair["id"], agreement_id=agr["id"])
        payload["qty_sold"] = 99
        resp = api.create_stock_line(payload, ORG)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_stockline_body_fk_not_found(self, api):
        """PRD §2.9: "then resource existence, with path resources resolved left
        to right and the first missing path or body reference yielding
        `ERR_NOT_FOUND` (HTTP 404, priority 5)"

        Design: Corner/validations/stockline_body_fk_not_found
        """
        school = make_school()
        fair = make_fair(school["id"])
        payload = create_stock_line_payload(
            fair_id=fair["id"], agreement_id=NON_EXISTENT_UUID
        )
        resp = api.create_stock_line(payload, ORG)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestStockLineCommitGate:
    def test_stockline_commit_requires_agreement_accepted(self, api):
        """PRD §3.3: "Committing a line (`QUOTED` → `COMMITTED`) requires the
        line's agreement to be `ACCEPTED` — otherwise
        `ERR_AGREEMENT_NOT_ACCEPTED` (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/stockline_commit_requires_agreement_accepted
        """
        school = make_school()
        pub = make_publisher()
        fair = make_fair_scheduled(school["id"])
        # Agreement created but NEVER accepted (still PROPOSED)
        agr = validate_success(api.create_agreement(
            {"fair_id": fair["id"], "publisher_party_id": pub["id"],
             "discount_pct": 0.40, "return_cap_pct": 0.25, "restocking_fee_pct": 0.10,
             "markdown_allowance_pct": 0.20, "freight_responsibility": "ORGANIZER",
             "offer_expiry_hours": 72}, ORG,
        ), expected_status=201)
        line = validate_success(api.create_stock_line(
            create_stock_line_payload(fair_id=fair["id"], agreement_id=agr["id"]),
            ORG,
        ), expected_status=201)
        resp = api.commit_stock_line(line["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACCEPTED)
        after = validate_success(api.get_stock_line(line["id"], ORG))
        assert after["status"] == "QUOTED"

    def test_stockline_commit_requires_fair_scheduled_or_stocking(self, api):
        """PRD §3.3: "Committing a line (`QUOTED` → `COMMITTED`) requires the
        line's agreement to be `ACCEPTED` — otherwise
        `ERR_AGREEMENT_NOT_ACCEPTED` (HTTP 409) — and the fair to be `SCHEDULED`
        or `STOCKING`."

        Design: Difficulty/cross_entity_state_dependency/stockline_commit_requires_agreement_accepted
        """
        school = make_school()
        pub = make_publisher()
        # Fair stays DRAFT; agreement is ACCEPTED but the fair is not SCHEDULED.
        fair = make_fair(school["id"])
        agr = make_accepted_agreement(fair["id"], pub["id"])
        line = validate_success(api.create_stock_line(
            create_stock_line_payload(fair_id=fair["id"], agreement_id=agr["id"]),
            ORG,
        ), expected_status=201)
        resp = api.commit_stock_line(line["id"], ORG)
        # From DRAFT the commit transition's fair-state precondition fails.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDelivery:
    def test_over_delivery_rejected(self, api):
        """PRD §3.3: "Delivery (`COMMITTED` → `DELIVERED`) records a payload
        `qty_delivered` that may not exceed `qty_committed` (`ERR_OVER_DELIVERY`,
        HTTP 409)"

        Design: Corner/errors/over_delivery_rejected
        """
        school = make_school()
        pub = make_publisher()
        fair = make_fair_scheduled(school["id"])
        agr = make_accepted_agreement(fair["id"], pub["id"])
        line = validate_success(api.create_stock_line(
            create_stock_line_payload(
                fair_id=fair["id"], agreement_id=agr["id"], qty_committed=10
            ), ORG,
        ), expected_status=201)
        validate_success(api.commit_stock_line(line["id"], ORG))
        # Move the fair to STOCKING so deliver is permitted
        validate_success(api.open_stocking(fair["id"], ORG))
        resp = api.deliver_stock_line(line["id"], {"qty_delivered": 11}, ORG)
        validate_error(resp, ApiErrorId.ERR_OVER_DELIVERY)
        after = validate_success(api.get_stock_line(line["id"], ORG))
        assert after["status"] == "COMMITTED"

    def test_delivery_exact_boundary_succeeds(self, api):
        """PRD §3.3: "Delivery (`COMMITTED` → `DELIVERED`) records a payload
        `qty_delivered` that may not exceed `qty_committed` (`ERR_OVER_DELIVERY`,
        HTTP 409) and requires the fair to be `STOCKING` or `OPEN`."

        Design: Corner/errors/over_delivery_rejected
        """
        school = make_school()
        pub = make_publisher()
        fair = make_fair_scheduled(school["id"])
        agr = make_accepted_agreement(fair["id"], pub["id"])
        line = validate_success(api.create_stock_line(
            create_stock_line_payload(
                fair_id=fair["id"], agreement_id=agr["id"], qty_committed=10
            ), ORG,
        ), expected_status=201)
        validate_success(api.commit_stock_line(line["id"], ORG))
        validate_success(api.open_stocking(fair["id"], ORG))
        resp = api.deliver_stock_line(line["id"], {"qty_delivered": 10}, ORG)
        data = validate_success(resp)
        assert data["status"] == "DELIVERED"
        assert data["qty_delivered"] == 10
        assert data["qty_available_for_sale"] == 10


class TestDamage:
    def test_damage_exceeds_on_hand_boundary(self, api):
        """PRD §3.3: "Damaged stock is written off by the organizer with a
        payload `qty`, but only while the fair is `OPEN` or `RECONCILING`, and
        only up to the unsold, unheld on-hand quantity: `qty` may not exceed
        `qty_delivered` minus `qty_sold`, minus `qty_damaged`, minus
        `qty_returned_shipped`, minus `qty_held_preorder`
        (`ERR_DAMAGE_EXCEEDS_ON_HAND`, HTTP 409)."

        Design: Corner/errors/damage_exceeds_on_hand_boundary
        """
        school = make_school()
        pub = make_publisher()
        fair, agr, lines = make_fair_open(school["id"], pub["id"])
        line = lines[0]

        resp_over = api.damage_stock_line(line["id"], {"qty": 11}, ORG)
        validate_error(resp_over, ApiErrorId.ERR_DAMAGE_EXCEEDS_ON_HAND)

        resp_ok = api.damage_stock_line(line["id"], {"qty": 10}, ORG)
        data = validate_success(resp_ok)
        assert data["qty_damaged"] == 10
        assert data["qty_available_for_sale"] == 0

    def test_damage_partial_updates_availability(self, api):
        """PRD §3.3: "At all times after delivery, a line's `qty_delivered`
        equals the sum of `qty_held_preorder`, `qty_sold`, `qty_damaged`,
        `qty_returned_shipped`, and `qty_available_for_sale`; equivalently,
        `qty_available_for_sale` is what remains of the delivered copies after
        held, sold, damaged, and shipped-back copies are subtracted."

        Design: Corner/errors/damage_exceeds_on_hand_boundary
        """
        school = make_school()
        pub = make_publisher()
        fair, agr, lines = make_fair_open(school["id"], pub["id"])
        line = lines[0]
        data = validate_success(api.damage_stock_line(line["id"], {"qty": 3}, ORG))
        assert data["qty_damaged"] == 3
        assert data["qty_available_for_sale"] == 7
        assert_copy_conservation(data)
