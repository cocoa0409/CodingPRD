"""Global specifications: response envelope, authentication, RBAC denials,
customer-scope ownership, and existence-vs-state ordering (PRD §2)."""
from test_helpers import (
    assert_customer,
    create_customer,
    create_customer_payload,
    create_lot_payload,
    create_released_program,
    create_test_program_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_customer_rep_headers,
    setup_awaiting_disposition_lot,
    setup_in_test_lot,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ENG1, OPS, QE, get_pending_review_id
from test_helpers.factories import create_esd_audit_payload

# A well-formed but absent lot id used by the not-found recipes.
ABSENT_LOT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestSuccessEnvelope:
    def test_create_customer_success_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`." and "The `response_type` is either
        "object" for a single resource or "array" for a list of resources."
        PRD §2.4: "`id` (string): a unique, server-minted identifier formatted as a
        UUID, with no type prefix."
        PRD §4: "Operations that create new resources — registering a customer,
        program, fixture, chamber, reservation, lot, unit, result, authorization,
        equipment record, maintenance order, audit, RMA case, disposition review, or
        minting a program revision — return a `201 Created` status code."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        res = api.create_customer(
            create_customer_payload(name="EnvCo", tier="STANDARD"), OPS
        )
        assert res.status_code == 201, f"create must return 201, got {res.status_code}"
        body = res.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with req_"
        )
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        cust_id = body["data"]["id"]
        assert is_valid_uuid(cust_id), "data.id must be a server-minted UUID"
        assert_customer(body["data"])


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request that arrives without both headers, or whose role
        header does not name one of these four roles, is rejected with
        `ERR_UNAUTHENTICATED`."
        PRD §2.11: "Incoming requests are validated against a fixed priority ladder,
        and the first failing rung determines the error returned — a request that
        would fail several checks surfaces only the earliest rung's error."
        (Authentication is rung 1, existence rung 3, so no 404 leaks for this
        absent lot id.)

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        res = api.get_lot(ABSENT_LOT_ID, headers={})
        validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)

    def test_get_nonexistent_lot_returns_not_found(self, api):
        """PRD §2.11: "every identifier referenced in the path and body exists, validated
        left-to-right — path identifiers first, then body fields in their declared
        order — otherwise `ERR_NOT_FOUND`."

        Design: Corner/validations/get_nonexistent_lot_returns_not_found
        """
        res = api.get_lot(ABSENT_LOT_ID, OPS)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    def test_existence_checked_before_state(self, api):
        """PRD §2.11: "Incoming requests are validated against a fixed priority
        ladder, and the first failing rung determines the error returned — a request
        that would fail several checks surfaces only the earliest rung's error."
        PRD §2.11: "every identifier referenced in the path and body exists, validated
        left-to-right — path identifiers first, then body fields in their declared
        order — otherwise `ERR_NOT_FOUND`." (Existence is rung 3, lifecycle state
        rung 4, so enqueue on an absent lot never reaches the state machine.)

        Design: Corner/validations/existence_checked_before_state
        """
        res = api.enqueue_lot(ABSENT_LOT_ID, OPS)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)


class TestRbacDenials:
    def test_customer_rep_cannot_create_test_program(self, api):
        """PRD §2.1: "A `CustomerRep` owns lot creation and RMA intake for their own
        customer and may declare serial numbers on their own lots; they share read
        access to every resource. A `TestEngineer` develops test programs and
        fixtures, validates and releases programs, mints revisions, records test
        insertions, and issues or revokes retest authorizations."
        PRD §2.1: "A request whose role is well-formed but not listed among the
        endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/customer_rep_cannot_create_test_program_unauthorized
        """
        customer = create_customer(name="RbacCo")
        rep = make_customer_rep_headers(customer["id"])
        res = api.create_test_program(
            create_test_program_payload(customer["id"], part_number="PN-235"), rep
        )
        validate_error(res, "ERR_UNAUTHORIZED_ROLE", expected_status=403)

    def test_quality_engineer_cannot_record_results(self, api):
        """PRD §2.1: "A `TestEngineer` develops test programs and fixtures, validates
        and releases programs, mints revisions, records test insertions, and issues
        or revokes retest authorizations."
        PRD §2.1: "A `QualityEngineer` voids test results, opens and closes ESD
        audits, opens and decides lot disposition reviews, and runs the
        failure-analysis stages of an RMA case."
        PRD §2.1: "A request whose role is well-formed but not listed among the
        endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/quality_engineer_cannot_record_results_unauthorized
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-236")
        res = api.create_test_result(
            {
                "unit_id": ctx["units"][0]["id"],
                "fixture_id": ctx["fixture"]["id"],
                "bin_code": 1,
            },
            QE,
        )
        validate_error(res, "ERR_UNAUTHORIZED_ROLE", expected_status=403)
        unit = validate_success(api.get_unit(ctx["units"][0]["id"], QE), 200)
        assert unit["test_status"] == "UNTESTED", "rejected insert must persist nothing"

    def test_test_engineer_cannot_decide_review(self, api):
        """PRD §2.1: "A `QualityEngineer` voids test results, opens and closes ESD
        audits, opens and decides lot disposition reviews, and runs the
        failure-analysis stages of an RMA case."
        PRD §2.1: "A request whose role is well-formed but not listed among the
        endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/test_engineer_cannot_decide_review_unauthorized
        """
        # FPY 0.5 -> MRB_REVIEW -> auto PENDING review exists.
        ctx = setup_awaiting_disposition_lot(
            [1, 9], part_number="PN-237", max_retests_per_unit=1
        )
        review_id = get_pending_review_id(ctx["lot"]["id"])
        assert review_id, "expected an auto-created PENDING review"
        res = api.decide_lot_disposition_review(
            review_id, {"decision": "SCRAP", "rationale": "engineer overreach"}, ENG1
        )
        validate_error(res, "ERR_UNAUTHORIZED_ROLE", expected_status=403)
        review = validate_success(api.get_lot_disposition_review(review_id, QE), 200)
        assert review["status"] == "PENDING", "rejected decide must change nothing"

    def test_operations_manager_cannot_close_audit(self, api):
        """PRD §2.1: "A `QualityEngineer` voids test results, opens and closes ESD
        audits, opens and decides lot disposition reviews, and runs the
        failure-analysis stages of an RMA case."
        PRD §2.1: "A request whose role is well-formed but not listed among the
        endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/operations_manager_cannot_close_audit_unauthorized
        """
        audit = validate_success(
            api.create_esd_audit(
                create_esd_audit_payload(area_code="AREA-RB", findings=[]), QE
            ),
            201,
        )
        res = api.close_esd_audit(audit["id"], {"corrective_actions": []}, OPS)
        validate_error(res, "ERR_UNAUTHORIZED_ROLE", expected_status=403)
        audit_after = validate_success(api.get_esd_audit(audit["id"], QE), 200)
        assert audit_after["status"] == "OPEN", "rejected close must change nothing"


class TestCustomerScope:
    def test_foreign_customer_scope_forbidden(self, api):
        """PRD §2.1: "Consequently, a `CustomerRep` may create lots, register
        serialized units, and open RMA cases only within their own customer scope —
        lot creation must carry a `customer_id` equal to `X-User-ID`, unit
        registration must target a lot belonging to that customer, and RMA creation
        must reference a lot and unit belonging to that customer — and any scope
        mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/validations/foreign_customer_scope_forbidden
        """
        cust_a = create_customer(name="CustA")
        cust_b = create_customer(name="CustB")
        # Build a RELEASED program owned by customer B.
        ctx_b = create_released_program(cust_b["id"], part_number="PN-214")
        rep_a = make_customer_rep_headers(cust_a["id"])
        res = api.create_lot(
            create_lot_payload(
                cust_b["id"], ctx_b["program"]["id"],
                part_number="PN-214", quantity=1,
            ),
            rep_a,
        )
        validate_error(res, "ERR_FORBIDDEN_OWNERSHIP", expected_status=403)
