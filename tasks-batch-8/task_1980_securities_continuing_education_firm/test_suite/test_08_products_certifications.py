"""Product offerings & certifications: launch guards, fan-out eligibility,
duplicate codes, withdraw/reinstate state guards."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_approved_content,
    create_draft_content,
    create_product_payload,
    create_rep,
    get_certification_for,
    get_success_data,
    setup_launched_product,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLaunchGuards:
    def test_launch_with_unapproved_content_rejected(self, api, officer_headers):
        """PRD §3.7: "A `ComplianceOfficer` may launch a product in `PROPOSED`
        — launching from any other status is rejected with
        `ERR_PRODUCT_NOT_PROPOSED` — and only while the content named by
        `required_training_content_id` is `APPROVED`, otherwise
        `ERR_PRODUCT_TRAINING_CONTENT_NOT_APPROVED`."

        Design: Corner/errors/c_launch_with_unapproved_content_returns_409
        """
        # Content submitted but never approved (PENDING_APPROVAL).
        from test_helpers import TEST_USERS, create_content_payload
        content = get_success_data(api.create_content(
            create_content_payload(code="PR-UNAPPR", ce_category="PRODUCT"),
            TEST_USERS["admin_headers"]))
        get_success_data(api.submit_content(
            content["id"], TEST_USERS["admin_headers"]))
        product = get_success_data(api.create_product(
            create_product_payload(content["id"], product_code="PUNAPPR"),
            officer_headers))

        resp = api.launch_product(product["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_TRAINING_CONTENT_NOT_APPROVED)

        data = validate_success(api.get_product(product["id"], officer_headers))
        assert data["product_status"] == "PROPOSED", (
            f"rejected launch must leave the product PROPOSED, "
            f"got {data['product_status']}")

    def test_second_launch_rejected(self, api, officer_headers):
        """PRD §3.7: "A `ComplianceOfficer` may launch a product in `PROPOSED`
        — launching from any other status is rejected with
        `ERR_PRODUCT_NOT_PROPOSED`."

        Design: Corner/errors/c_launch_twice_returns_409
        """
        _content, product = setup_launched_product(
            content_overrides={"code": "PR-LT"},
            product_overrides={"product_code": "PLT"})
        resp = api.launch_product(product["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_PROPOSED)

    def test_withdraw_proposed_product_rejected(self, api, officer_headers):
        """PRD §3.7: "Withdrawal itself is a `ComplianceOfficer` action on a
        `LAUNCHED` product — withdrawing from any other status is rejected with
        `ERR_PRODUCT_NOT_LAUNCHED` — and leaves the product in `WITHDRAWN`,
        which is terminal."

        Design: Corner/errors/c_withdraw_proposed_product_returns_409
        """
        content = create_draft_content(code="PR-WP", ce_category="PRODUCT")
        product = get_success_data(api.create_product(
            create_product_payload(content["id"], product_code="PWP"),
            officer_headers))
        resp = api.withdraw_product(product["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_LAUNCHED)


class TestLaunchFanout:
    def test_fanout_excludes_terminated_rep(self, api, officer_headers):
        """PRD §3.7: "Launching stamps `launched_at`, writes a
        `PRODUCT_LAUNCHED` event, and fans out: one product certification in
        `PENDING_TRAINING` is created for every representative whose
        `registration_status` is `ACTIVE` at that moment, processed in
        `created_at` ascending order with `crd_number` ascending as the
        tie-break. Representatives in `INACTIVE_CE` or `TERMINATED` receive no
        certification."

        Design: Corner/calculations/c_launch_fanout_excludes_terminated_rep
        """
        rep_active = create_rep(crd_number="CRD-C19A")
        rep_term = create_rep(crd_number="CRD-C19B")
        get_success_data(api.terminate_representative(rep_term["id"], officer_headers))

        content = create_approved_content(code="PR-FAN", ce_category="PRODUCT")
        product = get_success_data(api.create_product(
            create_product_payload(content["id"], product_code="PFAN"),
            officer_headers))
        get_success_data(api.launch_product(product["id"], officer_headers))

        data, meta = validate_paginated(
            api.list_product_certifications(
                officer_headers, params={"product_id": product["id"]}))
        assert len(data) == 1, (
            f"fan-out must create exactly one certification (ACTIVE rep only), "
            f"got {len(data)}")
        assert data[0]["rep_id"] == rep_active["id"]
        assert data[0]["cert_status"] == "PENDING_TRAINING"


class TestDuplicateProductCode:
    def test_duplicate_product_code_rejected(self, api, officer_headers):
        """PRD §3.7: "A `ComplianceOfficer` registers a product by supplying a
        unique `product_code` — a duplicate is rejected with
        `ERR_DUPLICATE_PRODUCT_CODE` — a `name`, and the
        `required_training_content_id` of the product-specific course that
        gates selling."

        Design: Corner/errors/c_duplicate_product_code_returns_409
        """
        content = create_draft_content(code="PR-DUP", ce_category="PRODUCT")
        get_success_data(api.create_product(
            create_product_payload(content["id"], product_code="DUP-P"),
            officer_headers))
        resp = api.create_product(
            create_product_payload(content["id"], product_code="DUP-P",
                                   name="Second Product"),
            officer_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PRODUCT_CODE)


class TestReinstateStateGuard:
    def test_reinstate_pending_certification_rejected(self, api, officer_headers):
        """PRD §3.7: "A `ComplianceOfficer` may reinstate a certification that
        is `SUSPENDED` — otherwise `ERR_CERTIFICATION_NOT_SUSPENDED`."

        Design: Corner/errors/c_reinstate_pending_certification_returns_409
        """
        rep = create_rep(crd_number="CRD-RPC")
        content, product = setup_launched_product(
            content_overrides={"code": "PR-RPC"},
            product_overrides={"product_code": "PRPC"})
        cert = get_certification_for(rep["id"], product["id"])
        assert cert["cert_status"] == "PENDING_TRAINING"

        resp = api.reinstate_certification(cert["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_SUSPENDED)
