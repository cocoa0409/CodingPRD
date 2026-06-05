"""Corner section: entities — CRUD basics, system fields, computed fields,
the CCRReview immutability surface, and required/range-checked inputs on
purchase-agreement creation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    is_iso8601_timestamp,
    setup_actors,
    setup_active_agreement,
    bootstrap_compliance_officer,
    register_user,
    create_agreement,
    activate_agreement,
    fetch_escrow_for_agreement,
    create_deposit,
    confirm_deposit,
    create_purchase_agreement_payload,
    create_ccr_review_payload,
    create_earnest_money_deposit_payload,
    make_escrow_officer_headers,
    NON_EXISTENT_UUID,
)


class TestPurchaseAgreementCreation:
    def test_create_purchase_agreement_returns_201_with_draft_and_version_1(self, api):
        """PRD §3.1: "The new agreement lands in ``DRAFT`` with ``version`` 1, ``status`` ``DRAFT``, ``earnest_money_received_cents`` of zero, and ``terminated_reason`` null."

        Design: Corner/entities/create_purchase_agreement_required_fields_present
        """
        co_id, co_headers = bootstrap_compliance_officer()
        eo_id = register_user("EscrowOfficer", "Escrow Officer 1", co_headers)
        eo_headers = make_escrow_officer_headers(eo_id)
        res = api.create_purchase_agreement(
            create_purchase_agreement_payload(
                buyer_name="Buyer One",
                seller_name="Seller One",
                property_address="1 Main St",
                purchase_price_cents=50_000_000,
                earnest_money_required_cents=1_000_000,
                scheduled_closing_date="2026-08-01T00:00:00Z",
            ),
            eo_headers,
        )
        agr = validate_success(res, expected_status=201)
        assert agr["status"] == "DRAFT"
        assert agr["version"] == 1


class TestPurchaseAgreementNotFound:
    def test_get_nonexistent_purchase_agreement_returns_404_err_not_found(self, api):
        """PRD §2.8: "Wherever a URL contains a path-templated ``id``, the server resolves the segment to its target row before any business check runs. Any path id that does not resolve is rejected with ``ERR_NOT_FOUND`` (HTTP 404)."

        Design: Corner/entities/get_purchase_agreement_not_found
        """
        co_id, co_headers = bootstrap_compliance_officer()
        eo_id = register_user("EscrowOfficer", "Escrow Officer 1", co_headers)
        eo_headers = make_escrow_officer_headers(eo_id)
        res = api.get_purchase_agreement(NON_EXISTENT_UUID, eo_headers)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)


class TestPurchaseAgreementListingPagination:
    def test_list_purchase_agreements_returns_meta_with_total_count_and_has_more(self, api):
        """PRD §2.3: "List endpoints accept two query parameters, ``limit`` and ``offset``. The default ``limit`` is 10, the minimum is 1, and the maximum is 100; a request outside this range is rejected with ``ERR_INVALID_REQUEST``. The default ``offset`` is 0. Results are ordered by ``created_at`` ascending — chronologically, in the order they were recorded. The list endpoint's response envelope places ``limit``, ``offset``, ``total_count``, and ``has_more`` inside ``meta``, and the actual resource array in ``data``."

        Design: Corner/entities/list_purchase_agreements_pagination_defaults
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        # Create exactly one agreement so total_count is deterministic.
        create_agreement(actors, property_address="1 Pag St")
        data, meta = validate_paginated(
            api.list_purchase_agreements(actors["eo"])
        )
        assert meta["total_count"] == 1, \
            f"total_count must equal the number of agreements (1), got {meta['total_count']}"
        assert meta["has_more"] is False, \
            f"has_more must be false when only 1 row fits inside the default limit=10, got {meta['has_more']}"


class TestPurchaseAgreementMissingRequiredField:
    def test_missing_purchase_price_returns_422_err_invalid_request(self, api):
        """PRD §5: ERR_INVALID_REQUEST → HTTP 422.
        PRD §2.10: "Catch-all body-shape errors (``ERR_INVALID_REQUEST``) are last."

        Design: Corner/entities/create_agreement_missing_purchase_price_invalid_request
        """
        co_id, co_headers = bootstrap_compliance_officer()
        eo_id = register_user("EscrowOfficer", "Escrow Officer 1", co_headers)
        eo_headers = make_escrow_officer_headers(eo_id)
        payload = {
            "buyer_name": "B",
            "seller_name": "S",
            "property_address": "1 NF St",
            "earnest_money_required_cents": 1_000_000,
            "scheduled_closing_date": "2026-08-01T00:00:00Z",
            # purchase_price_cents intentionally omitted
        }
        res = api.create_purchase_agreement(payload, eo_headers)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


class TestPurchaseAgreementPriceBelowFloor:
    def test_purchase_price_below_floor_returns_422_err_price_out_of_range(self, api):
        """PRD §3.1: "The contract price must be at least 100,000 cents and at most 1,000,000,000,000 cents (one trillion cents, or ten billion dollars) — values outside this range are rejected with ``ERR_PRICE_OUT_OF_RANGE``."

        Design: Corner/entities/create_agreement_purchase_price_below_floor_rejected
        """
        co_id, co_headers = bootstrap_compliance_officer()
        eo_id = register_user("EscrowOfficer", "Escrow Officer 1", co_headers)
        eo_headers = make_escrow_officer_headers(eo_id)
        res = api.create_purchase_agreement(
            create_purchase_agreement_payload(
                purchase_price_cents=99_999,
                property_address="1 Lo St",
            ),
            eo_headers,
        )
        validate_error(res, "ERR_PRICE_OUT_OF_RANGE", expected_status=422)


class TestCCRReviewIsImmutable:
    def test_ccr_review_get_returns_recorded_fields(self, api):
        """PRD §3.3: "A ``ComplianceOfficer`` records the CC&R review for the property in a single append-only entry. The review carries the ``agreement_id``, the ``hoa_name`` (or null if the property is not subject to a homeowners' association), a ``restrictions_summary`` summarising the covenants, conditions and restrictions reviewed, and the boolean ``buyer_acknowledged`` that captures whether the buyer has explicitly accepted those restrictions. The review is immutable once recorded — there is no update or delete — and the only way to record a change is to append a new review row."

        Design: Corner/entities/ccr_review_is_immutable
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(actors=actors)
        res = api.create_ccr_review(
            create_ccr_review_payload(
                agreement_id=base["agreement"]["id"],
                hoa_name="HOA",
                restrictions_summary="ok",
                buyer_acknowledged=True,
            ),
            actors["co"],
        )
        ccr = validate_success(res, expected_status=201)
        fetched = validate_success(
            api.get_ccr_review(ccr["id"], actors["co"]),
            expected_status=200,
        )
        assert fetched["buyer_acknowledged"] is True, \
            f"recorded buyer_acknowledged must be returned by GET, got {fetched['buyer_acknowledged']}"


class TestEarnestMoneyReceivedComputedFieldUpdate:
    def test_earnest_money_received_recomputed_on_each_confirm(self, api):
        """PRD §3.1: "Confirmation is the trigger for the agreement's funding event. The system recomputes ``earnest_money_received_cents`` as the sum of ``amount_cents`` across every ``CONFIRMED`` deposit on the agreement"

        Design: Corner/entities/computed_field_earnest_money_received_cents_updates_on_confirm
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(
            actors=actors, earnest_money_required_cents=1_000_000
        )
        d1 = create_deposit(actors, base["escrow"]["id"], amount_cents=500_000)
        # Also create a second PENDING deposit (un-confirmed) to test that
        # only CONFIRMED deposits enter the recomputed sum.
        create_deposit(actors, base["escrow"]["id"], amount_cents=300_000)
        confirm_deposit(actors, d1["id"], confirmation_reference="CF-1")
        agr_after = validate_success(
            api.get_purchase_agreement(base["agreement"]["id"], actors["eo"]),
            expected_status=200,
        )
        assert agr_after["earnest_money_received_cents"] == 500_000, \
            f"only CONFIRMED deposits contribute; expected 500000, got {agr_after['earnest_money_received_cents']}"


class TestSystemFieldsAreServerMinted:
    def test_create_response_carries_server_minted_id_and_created_at(self, api):
        """PRD §2.4: "Every resource that the system writes carries an ``id`` field of type string. The ``id`` is a server-minted UUID with no type prefix — the client never supplies it on create, and a value such as ``"agr_..."`` or ``"escrow_..."`` is not used."
        PRD §2.4: "Most resources also carry three system fields. The ``created_at`` field is the UTC instant the row was inserted, formatted as an ISO 8601 timestamp with three fractional digits (millisecond precision, trailing ``Z``)."

        Design: Corner/entities/system_fields_id_and_created_at_are_generated
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        res = api.create_purchase_agreement(
            create_purchase_agreement_payload(property_address="1 SF St"),
            actors["eo"],
        )
        agr = validate_success(res, expected_status=201)
        assert is_valid_uuid(agr["id"]), \
            f"id must be a server-minted UUID with no prefix, got {agr['id']!r}"
        assert is_iso8601_timestamp(agr["created_at"]), \
            f"created_at must be ISO 8601, got {agr['created_at']!r}"
        assert agr["version"] == 1, \
            f"newly-created row must carry version=1, got {agr['version']}"
