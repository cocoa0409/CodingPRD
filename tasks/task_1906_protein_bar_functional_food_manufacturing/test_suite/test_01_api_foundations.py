"""API foundations: response envelope, pagination, not-found resolution,
authentication, and read-after-write consistency."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_ingredient,
    create_ingredient_payload,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["plant_admin_headers"]
SCI = TEST_USERS["formulation_scientist_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestEnvelopeShape:
    def test_success_and_error_envelopes(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/c_envelope_shape
        """
        created = client.create_customer(
            {"name": "C1", "contact_email": "c1@x.com"}, ADMIN
        )
        assert created.status_code == 201
        body = created.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert is_valid_uuid(body["data"]["id"])

        missing = client.get_customer(NON_EXISTENT_UUID, ADMIN)
        err = validate_error(missing, ApiErrorId.ERR_CUSTOMER_NOT_FOUND, 404)
        err_body = missing.json()
        assert err_body["response_type"] == "error"
        assert isinstance(err["message"], str) and err["message"]


class TestNotFoundSweep:
    def test_every_resource_type_answers_its_own_404(self, api):
        """PRD §2.10: "The first identifier that does not correspond to an
        existing resource fails the request with that resource type's own 404
        before any later identifier is examined: a missing brand customer
        yields `ERR_CUSTOMER_NOT_FOUND`, a missing formula
        `ERR_FORMULA_NOT_FOUND`, a missing revision `ERR_REVISION_NOT_FOUND`,
        a missing ingredient `ERR_INGREDIENT_NOT_FOUND`, a missing lot
        `ERR_LOT_NOT_FOUND`, a missing line `ERR_LINE_NOT_FOUND`, a missing
        run `ERR_RUN_NOT_FOUND`, a missing agreement `ERR_AGREEMENT_NOT_FOUND`,
        a missing slot `ERR_SLOT_NOT_FOUND`, a missing changeover
        `ERR_CHANGEOVER_NOT_FOUND`, a missing study `ERR_STUDY_NOT_FOUND`, a
        missing lot release `ERR_RELEASE_NOT_FOUND`, a missing claim review
        `ERR_CLAIM_REVIEW_NOT_FOUND`, and a missing supplier
        `ERR_SUPPLIER_NOT_FOUND`."

        Design: Corner/entities/c_not_found_sweep
        """
        checks = [
            (client.get_customer(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
            (client.get_supplier(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_SUPPLIER_NOT_FOUND),
            (client.get_formula(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_FORMULA_NOT_FOUND),
            (client.get_revision(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_REVISION_NOT_FOUND),
            (client.get_ingredient(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_INGREDIENT_NOT_FOUND),
            (client.get_ingredient_lot(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_LOT_NOT_FOUND),
            (client.get_line(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_LINE_NOT_FOUND),
            (client.get_agreement(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            (client.get_slot(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_SLOT_NOT_FOUND),
            (client.get_changeover(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_CHANGEOVER_NOT_FOUND),
            (client.get_shelf_life_study(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_STUDY_NOT_FOUND),
            (client.get_lot_release(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_RELEASE_NOT_FOUND),
            (client.get_claim_review(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_CLAIM_REVIEW_NOT_FOUND),
            (client.get_production_run(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_RUN_NOT_FOUND),
        ]
        for resp, error_id in checks:
            validate_error(resp, error_id, 404)


class TestAuthentication:
    def test_missing_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does
        not name one of these roles is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/c_missing_header_returns_unauthenticated
        """
        resp = client.list_ingredients(headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestPagination:
    def test_ingredients_limit_offset_window(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10 when omitted, accepts a minimum of 1, and
        is capped at a maximum of 100. The `offset` parameter sets how many
        items to skip and defaults to 0."
        PRD §2.3: "List responses carry four pagination fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/c_ingredients_pagination
        """
        for name, category in (("I1", "BINDER"), ("I2", "FAT"), ("I3", "FLAVOR")):
            validate_success(
                client.create_ingredient(
                    create_ingredient_payload(name=name, category=category), ADMIN
                ),
                201,
            )
        page1, meta1 = validate_paginated(
            client.list_ingredients(ADMIN, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            client.list_ingredients(ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestChildCollectionReads:
    def test_reverse_reachability_and_filtered_reads(self, api):
        """PRD §3.2: "The lot listing can be filtered by `ingredient_id`, by
        `supplier_id`, and by `status`."
        PRD §2.3: "List responses carry four pagination fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/c_fk_reverse_reachability_reads
        """
        sup = fixtures.create_supplier("S1", "APPROVED")
        whey = fixtures.create_ingredient(
            "WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8
        )
        lot = fixtures.receive_lot(whey["id"], sup["id"], "WL-1", 50,
                                   coa_protein_pct=0.8)
        cust = fixtures.create_customer("C1")
        formula = fixtures.create_formula(cust["id"], "F", bar_weight_g=60)
        r1 = fixtures.create_revision(
            formula["id"], [fixtures.line(whey["id"], 40, True)],
            target_protein=15,
        )
        fixtures.create_revision(
            formula["id"], [fixtures.line(whey["id"], 45, True)],
            target_protein=17,
        )

        revisions, rev_meta = validate_paginated(
            client.list_revisions(formula["id"], SCI)
        )
        assert len(revisions) == 2
        assert rev_meta["total_count"] == 2

        lots, lot_meta = validate_paginated(
            client.list_ingredient_lots(ADMIN, params={"ingredient_id": whey["id"]})
        )
        assert [lot_row["id"] for lot_row in lots] == [lot["id"]]
        assert lot_meta["total_count"] == 1

        reviews, review_meta = validate_paginated(
            client.list_revision_claim_reviews(r1["id"], QM)
        )
        assert reviews == []
        assert review_meta["total_count"] == 0


class TestImmediateConsistency:
    def test_read_after_write_returns_created_resource(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."

        Design: Corner/consistency_model/c_immediate_read_after_write
        """
        created = validate_success(
            client.create_ingredient(
                create_ingredient_payload(
                    name="PECTIN", category="BINDER", allergen_tags=[]
                ),
                ADMIN,
            ),
            201,
        )
        assert_ingredient(created)
        read_back = validate_success(client.get_ingredient(created["id"], ADMIN), 200)
        assert read_back["name"] == "PECTIN"
        assert read_back["category"] == "BINDER"
        assert read_back["version"] == created["version"]
