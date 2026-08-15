"""Vendor registration, duplicate detection, envelope, auth and read-access tests."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    assert_vendor,
    create_vendor_payload,
    create_vendor,
)

VS1 = TEST_USERS["vendor_specialist_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]
AUD = TEST_USERS["auditor_headers"]
CLERK = TEST_USERS["ap_clerk_headers"]


class TestVendorCreationDefaultsAndShape:
    def test_vendor_create_applies_system_defaults(self, api):
        """A minimal vendor create persists inputs and applies system defaults.

        PRD §3.1: "The payment configuration consists of `payment_terms_days` (net terms in days, defaulting to 30), `early_pay_discount_pct` (a discount fraction such as 0.02, defaulting to 0, where 0 disables early-pay discounting entirely), and `discount_window_days` (the number of days from an invoice's `received_date` during which the discount applies, defaulting to 0, with the window's end day inclusive)."
        PRD §3.1: "The new vendor is born in `DRAFT` status, the caller is recorded as `created_by_user_id` (the SoD-1 anchor), and a `CREATE` audit event is appended."
        PRD §3.1: "Below 0.7500 the vendor is created with `duplicate_review_required` false."

        Design: Corner/entities/vendor_create_applies_defaults
        """
        resp = api.create_vendor(create_vendor_payload(
            legal_name="Default Depot", tax_id="20-0000001",
            remit_email="ap@dd.com", phone="+1-555-2000",
            address_line1="30 Fir St", city="Springfield", country="US"), VS1)
        vendor = validate_success(resp, expected_status=201)
        assert_vendor(vendor)
        assert vendor["status"] == "DRAFT"
        assert vendor["legal_name"] == "Default Depot"
        assert vendor["tax_id"] == "20-0000001"
        assert vendor["payment_terms_days"] == 30
        assert vendor["early_pay_discount_pct"] == 0
        assert vendor["discount_window_days"] == 0
        assert vendor["duplicate_review_required"] is False
        assert vendor["created_by_user_id"] == "u-vs-01"

    def test_vendor_create_missing_tax_id_returns_invalid_request(self, api):
        """Omitting required tax_id fails shape validation before screening.

        PRD §2.11: "Request-shape validity comes next — an unparsable body, a missing required field, an invalid enum value, a non-positive `amount_cents`, a negative `min_amount_cents`, a `tax_id` supplied in a vendor edit, or a document window whose `valid_from` falls after its `valid_until` are all rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/vendor_create_missing_tax_id_returns_invalid_request
        """
        payload = create_vendor_payload(legal_name="No Taxid", tax_id="x")
        payload.pop("tax_id")
        resp = api.create_vendor(payload, VS1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_vendor_get_unknown_id_returns_not_found(self, api):
        """GET on a well-formed but unknown vendor id returns 404.

        PRD §2.11: "Only then are path identifiers resolved: endpoints that address nested resources validate the path strictly left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) for the first identifier that does not correspond to an existing resource — a request targeting a bank account under a non-existent vendor fails on the vendor before the account is ever sought."

        Design: Corner/entities/vendor_get_not_found_returns_404
        """
        resp = api.get_vendor(NON_EXISTENT_UUID, AUD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_vendor_list_pagination_envelope(self, api):
        """Pagination meta fields and limit/offset slicing over three vendors.

        PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/vendor_list_pagination_envelope
        """
        ids = set()
        for name in ("Page One", "Page Two", "Page Three"):
            vendor = create_vendor(legal_name=name)
            ids.add(vendor["id"])

        page1, meta1 = validate_paginated(api.list_vendors(AUD, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_vendors(AUD, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        paged_ids = {v["id"] for v in page1} | {v["id"] for v in page2}
        assert paged_ids == ids, "the two pages must partition the created vendors"


class TestEnvelopeAuthAndAccess:
    def test_response_envelope_shape_on_success_and_error(self, api):
        """Success and error bodies follow the standard envelopes.

        PRD §2.2: "All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:"
        PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format:"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        ok_resp = api.create_vendor(create_vendor_payload(
            legal_name="Envelope Elm", tax_id="88-8888888"), VS1)
        assert ok_resp.status_code == 201
        ok_body = ok_resp.json()
        assert isinstance(ok_body["meta"].get("api_request_id"), str)
        assert ok_body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(ok_body["meta"].get("api_request_timestamp"), str)
        assert ok_body["response_type"] == "object"
        assert is_valid_uuid(ok_body["data"]["id"])

        err_resp = api.create_vendor(create_vendor_payload(
            legal_name="Envelope Elm", tax_id="88-8888888"), VS1)
        assert err_resp.status_code == 409
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == ApiErrorId.ERR_DUPLICATE_TAX_ID.value
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]

    def test_create_vendor_missing_auth_header_returns_400(self, api):
        """A call without the user context headers fails credential screening.

        PRD §2.1: "A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/create_vendor_missing_auth_header_returns_400
        """
        resp = api.create_vendor(create_vendor_payload(
            legal_name="No Auth", tax_id="20-0000050"), headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_apclerk_cannot_create_vendor_forbidden(self, api):
        """APClerk is not authorized on POST /vendors.

        PRD §2.1: "A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/vendors` | Create a vendor in DRAFT with duplicate detection | VendorSpecialist, VendorManager |"

        Design: Corner/rbac/apclerk_cannot_create_vendor_forbidden
        """
        resp = api.create_vendor(create_vendor_payload(
            legal_name="Clerk Made", tax_id="20-0000054"), CLERK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
        data, meta = validate_paginated(api.list_vendors(AUD))
        assert meta["total_count"] == 0, "no vendor may be persisted by the forbidden call"

    def test_auditor_read_only_with_audit_access(self, api):
        """Auditor can query the audit trail and read vendors but cannot write.

        PRD §2.7: "Access to the audit trail is restricted to assurance and control roles: `VendorManager`, `ComplianceOfficer`, `Controller`, and `Auditor`."
        PRD §2.1: "A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/auditor_read_only_with_audit_access
        """
        vendor = create_vendor(legal_name="Watched Wren", tax_id="20-0000055")
        events, meta = validate_paginated(api.list_audit_events(
            AUD, params={"entity_type": "Vendor", "entity_id": vendor["id"]}))
        assert meta["total_count"] >= 1
        assert any(e["event_type"] == "CREATE" and e["entity_id"] == vendor["id"]
                   for e in events)

        resp = api.create_vendor(create_vendor_payload(
            legal_name="Auditor Made", tax_id="20-0000056"), AUD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


class TestDuplicateDetection:
    def test_duplicate_tax_id_rejected(self, api):
        """tax_id equality on a non-terminal vendor is the strict leg collision.

        PRD §3.1: "The strict leg flags only exact collisions: if any candidate's `tax_id` equals the new vendor's `tax_id`, creation is rejected with `ERR_DUPLICATE_TAX_ID`."
        PRD §3.1: "Both thresholds compare against the four-decimal-place rounded score with at-least semantics, and the create-time checks fire in this order: request validity first, then the tax-identifier collision, then the hard block, then the review band."

        Design: Corner/validations/duplicate_tax_id_rejected
        """
        create_vendor(legal_name="Alpha One", tax_id="77-7777777")
        resp = api.create_vendor(create_vendor_payload(
            legal_name="Zzz Completely Different", tax_id="77-7777777"), VS1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAX_ID.value)

    def test_duplicate_detection_relaxed_hard_block_on_typo_name(self, api):
        """A one-character typo with a different tax_id passes the strict leg but
        the relaxed trigram leg hard-blocks at 0.9630 >= 0.9000.

        PRD §3.1: "The relaxed leg computes the §2.10 similarity score of the new `legal_name` against each candidate's `legal_name` and, when the candidate carries one, its `dba_name`, taking the best score over all comparisons; because the score is a trigram measure, a one-character typo in the name with a different `tax_id` passes the strict leg cleanly but is caught here."
        PRD §3.1: "If the best score is at least 0.9000, creation is rejected with `ERR_DUPLICATE_VENDOR_HARD_BLOCK` — identical input that produced no strict match produces a hard block here."

        Design: Difficulty/dual_variant_calc/duplicate_detection_strict_passes_relaxed_blocks
        """
        create_vendor(legal_name="Northwind Traders", tax_id="11-1111111")
        resp = api.create_vendor(create_vendor_payload(
            legal_name="Northwind Trader", tax_id="22-2222222"), VS1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VENDOR_HARD_BLOCK.value)

    def test_duplicate_hard_block_leaves_no_second_vendor(self, api):
        """The hard-blocked registration persists nothing: the name filter still
        finds exactly the original vendor.

        PRD §3.1: "If the best score is at least 0.9000, creation is rejected with `ERR_DUPLICATE_VENDOR_HARD_BLOCK` — identical input that produced no strict match produces a hard block here."
        PRD §3.1: "Accounts payable staff can browse the vendor register with optional filters: `status` isolates a lifecycle stage, `name_contains` matches against vendor names, `merged_into_vendor_id` finds everything absorbed into a given survivor, and `primary_bank_account_id` locates the vendor currently paying through a given account."

        Design: Difficulty/dual_variant_calc/duplicate_detection_strict_passes_relaxed_blocks
        """
        create_vendor(legal_name="Northwind Traders", tax_id="11-1111111")
        resp = api.create_vendor(create_vendor_payload(
            legal_name="Northwind Trader", tax_id="22-2222222"), VS1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VENDOR_HARD_BLOCK.value)
        data, meta = validate_paginated(api.list_vendors(
            AUD, params={"name_contains": "Northwind"}))
        assert meta["total_count"] == 1
        assert data[0]["legal_name"] == "Northwind Traders"

    def test_duplicate_score_exactly_hard_block_threshold(self, api):
        """Dice score of exactly 0.9000 hard-blocks: the >= boundary is inclusive;
        0.8966 lands in the review band instead.

        PRD §3.1: "If the best score is at least 0.9000, creation is rejected with `ERR_DUPLICATE_VENDOR_HARD_BLOCK` — identical input that produced no strict match produces a hard block here."
        PRD §3.1: "Both thresholds compare against the four-decimal-place rounded score with at-least semantics, and the create-time checks fire in this order: request validity first, then the tax-identifier collision, then the hard block, then the review band."

        Design: Difficulty/boundary_precision_check/duplicate_score_exactly_hard_block_threshold
        """
        create_vendor(legal_name="Red Barn Feeds", tax_id="33-3333333")
        create_vendor(legal_name="Stonebridge Supply", tax_id="44-4444444")

        # 'Red Barn Feeda' vs 'Red Barn Feeds': Dice == 0.9000 exactly.
        resp = api.create_vendor(create_vendor_payload(
            legal_name="Red Barn Feeda", tax_id="55-5555555"), VS1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VENDOR_HARD_BLOCK.value)

        # 'Sonebridge Supply' vs 'Stonebridge Supply': Dice == 0.8966 (review band).
        resp = api.create_vendor(create_vendor_payload(
            legal_name="Sonebridge Supply", tax_id="66-6666666"), VS1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VENDOR_REVIEW_REQUIRED.value)

    def test_duplicate_review_band_acknowledged_creates_flagged_vendor(self, api):
        """A review-band score with duplicate_acknowledged=true creates the vendor
        with duplicate_review_required set.

        PRD §3.1: "If the best score is at least 0.7500 but below 0.9000, creation is rejected with `ERR_DUPLICATE_VENDOR_REVIEW_REQUIRED` unless the caller asserted `duplicate_acknowledged` as true, in which case the vendor is created with its `duplicate_review_required` flag set to true."

        Design: Difficulty/boundary_precision_check/duplicate_score_exactly_hard_block_threshold
        """
        create_vendor(legal_name="Stonebridge Supply", tax_id="44-4444444")
        resp = api.create_vendor(create_vendor_payload(
            legal_name="Sonebridge Supply", tax_id="66-6666666"), VS1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VENDOR_REVIEW_REQUIRED.value)

        created = validate_success(api.create_vendor(create_vendor_payload(
            legal_name="Sonebridge Supply", tax_id="66-6666666",
            duplicate_acknowledged=True), VS1), expected_status=201)
        assert_vendor(created)
        assert created["duplicate_review_required"] is True
        assert created["status"] == "DRAFT"
