"""RBAC denials, ownership/scope violations, temporal validations, uniqueness
constraints, referential usability, and OCC on the subscription version."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    make_coordinator, make_agent, make_coordinator_with_seller,
    make_coordinator_with_buyer_seller, make_template, make_subscription,
    make_file, activate_file, make_active_listing_file, make_active_purchase_file,
    create_coordinator_payload, create_agent_payload, create_template_payload,
    create_subscription_payload, create_file_payload, create_document_payload,
    get_file_version, make_routed_amendment, get_signature_request_for_agent,
    ABSENT_UUID,
)


class TestAuthHeader:
    def test_request_missing_auth_header_returns_400(self):
        """PRD §2.1: "Every request carries two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing or malformed, the request is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.5: "When several checks could reject the same request, the service
        evaluates them in a fixed order so the returned error is deterministic. First,
        header presence and well-formedness
        (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."

        Design: Corner/validations/request_missing_auth_header_returns_400
        """
        resp = api_client.get_file(ABSENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_request_missing_role_header_returns_400(self):
        """PRD §2.1: "Every request carries two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing or malformed, the request is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/request_missing_auth_header_returns_400
        """
        resp = api_client.get_file(ABSENT_UUID, {"X-User-ID": "someone"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleDenials:
    def test_agent_cannot_create_file_forbidden(self):
        """PRD §2.1: "If the role is not permitted for the endpoint per the access
        matrix, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
        403)."
        PRD §2.1: "Segregation of duties is deliberate: `SystemAdmin` alone manages
        coordinators, checklist templates, and the logical clock; `Coordinator` alone
        owns files, roster, subscription, and every file-lifecycle action; `Agent`
        alone submits documents and signs or declines signature requests; `TitleRep`
        alone confirms title clearance; `LenderRep` alone confirms lender
        clear-to-close."

        Design: Corner/validations/agent_cannot_create_file_forbidden
        """
        coord, coord_h, seller, seller_h = make_coordinator_with_seller()
        payload = create_file_payload(seller_agent_id=seller["id"])
        resp = api_client.create_file(payload, seller_h)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_title_rep_cannot_confirm_lender(self):
        """PRD §2.1: "If the role is not permitted for the endpoint per the access
        matrix, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
        403)."
        PRD §2.1: "Segregation of duties is deliberate: `SystemAdmin` alone manages
        coordinators, checklist templates, and the logical clock; `Coordinator` alone
        owns files, roster, subscription, and every file-lifecycle action; `Agent`
        alone submits documents and signs or declines signature requests; `TitleRep`
        alone confirms title clearance; `LenderRep` alone confirms lender
        clear-to-close."
        PRD §2.5: "Second, role permission (`ERR_INSUFFICIENT_PERMISSIONS`). Third,
        existence of every path id and body foreign-key id, validated left-to-right as
        the ids appear in the URL and then the payload; each unresolved id produces
        its own entity-specific 404"

        Design: Corner/rbac/title_rep_cannot_confirm_lender
        """
        # The role check fires before the 404 existence check on the target id.
        resp = api_client.confirm_lender(ABSENT_UUID, TEST_USERS["title_rep_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_coordinator_cannot_confirm_title(self):
        """PRD §2.1: "If the role is not permitted for the endpoint per the access
        matrix, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
        403)."
        PRD §2.1: "Segregation of duties is deliberate: `SystemAdmin` alone manages
        coordinators, checklist templates, and the logical clock; `Coordinator` alone
        owns files, roster, subscription, and every file-lifecycle action; `Agent`
        alone submits documents and signs or declines signature requests; `TitleRep`
        alone confirms title clearance; `LenderRep` alone confirms lender
        clear-to-close."

        Design: Corner/rbac/coordinator_cannot_confirm_title
        """
        coord, coord_h = make_coordinator()
        resp = api_client.confirm_title(ABSENT_UUID, coord_h)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_coordinator_cannot_publish_template(self):
        """PRD §2.1: "If the role is not permitted for the endpoint per the access
        matrix, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
        403)."
        PRD §3.1: "Checklist templates are the platform's unit of jurisdictional
        knowledge, and only a `SystemAdmin` manages them."

        Design: Corner/rbac/coordinator_cannot_publish_template
        """
        coord, coord_h = make_coordinator()
        tmpl = make_template(publish=False)
        resp = api_client.publish_template(tmpl["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = validate_success(api_client.get_template(tmpl["id"], TEST_USERS["admin_headers"]))
        assert after["status"] == "DRAFT"

    def test_agent_cannot_accept_document(self):
        """PRD §2.1: "If the role is not permitted for the endpoint per the access
        matrix, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
        403)."
        PRD §3.5: "The coordinator then accepts (`RECEIVED → ACCEPTED`) or rejects
        (`RECEIVED → REJECTED`) it; rejection requires a `reason` (otherwise
        `ERR_INVALID_REQUEST`) which is recorded as `reject_reason`, and both accept
        and reject also reset the file's `last_audit_status` to `NONE` — any document
        status mutation after an audit invalidates that audit."

        Design: Corner/rbac/agent_cannot_accept_document
        """
        coord, coord_h, seller, seller_h = make_coordinator_with_seller()
        resp = api_client.accept_document(ABSENT_UUID, seller_h)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestOwnershipScope:
    def test_coordinator_cannot_mutate_other_coordinators_file(self):
        """PRD §2.1: "When `X-User-Role` is `Coordinator`, `X-User-ID` is the `id` of
        the acting `Coordinator`; ownership checks on any resource that references a
        `Coordinator` compare the resource's `coordinator_id` foreign-key field to
        `X-User-ID`. A coordinator who attempts to mutate a file, subscription, or
        child resource owned by another coordinator is rejected with
        `ERR_RESOURCE_NOT_OWNED` (HTTP 403)."

        Design: Corner/validations/coordinator_cannot_mutate_other_coordinators_file
        """
        scen = make_active_listing_file(coordinator_name="Casey Coord")
        coord2, coord2_h = make_coordinator("Dana Coord")
        file_id = scen["file"]["id"]
        resp = api_client.terminate_file(file_id, coord2_h, payload={"reason": "poach attempt"})
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_OWNED)
        fetched = validate_success(api_client.get_file(file_id, scen["coord_h"]))
        assert fetched["status"] == "ACTIVE"

    def test_non_party_agent_cannot_submit_document(self):
        """PRD §2.1: "An agent submitting a document must be the file's
        `buyer_agent_id` or `seller_agent_id`, otherwise `ERR_AGENT_NOT_ON_FILE`
        (HTTP 403)."
        PRD §3.5: "A party agent submits it, moving `REQUESTED → RECEIVED` or, on
        resubmission, `REJECTED → RECEIVED`; the actor must be the file's buyer or
        seller agent (`ERR_AGENT_NOT_ON_FILE`), the document must be in `REQUESTED` or
        `REJECTED` (`ERR_DOCUMENT_INVALID_STATE`), the submit stamps
        `submitted_by_agent_id` with the acting agent, a resubmission increments
        `review_round` by 1, and every submission resets the file's
        `last_audit_status` to `NONE`."

        Design: Corner/validations/non_party_agent_cannot_submit_document
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        _third, third_h = make_agent(coord_h, "Mallory Third")
        doc = get_success_data(api_client.create_document(
            create_document_payload(file_id=file_id, doc_type="EXECUTED_CONTRACT"), coord_h
        ))
        resp = api_client.submit_document(doc["id"], third_h)
        validate_error(resp, ApiErrorId.ERR_AGENT_NOT_ON_FILE)
        after = validate_success(api_client.get_document(doc["id"], coord_h))
        assert after["status"] == "REQUESTED"

    def test_wrong_agent_cannot_sign_signature_request(self):
        """PRD §2.1: "A signing agent whose `X-User-ID` does not match the signature
        request's `agent_id` is rejected with `ERR_SIGNATURE_NOT_AUTHORIZED` (HTTP
        403)."
        PRD §3.6: "Signing requires the request `PENDING`
        (`ERR_SIGNATURE_INVALID_STATE`), the acting agent's `X-User-ID` to equal the
        request's `agent_id` (`ERR_SIGNATURE_NOT_AUTHORIZED`), and the owning
        amendment to be in `ROUTED` or `PARTIALLY_SIGNED`
        (`ERR_AMENDMENT_INVALID_STATE`)."

        Design: Corner/validations/wrong_agent_cannot_sign_signature_request
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        am = make_routed_amendment(coord_h, file_id, "2026-08-10", "2026-08-15")
        sig_buyer = get_signature_request_for_agent(coord_h, am["id"], scen["buyer"]["id"])
        # The seller agent attempts to sign the buyer's request.
        resp = api_client.sign_signature_request(sig_buyer["id"], scen["seller_h"])
        validate_error(resp, ApiErrorId.ERR_SIGNATURE_NOT_AUTHORIZED)
        after = validate_success(api_client.get_signature_request(sig_buyer["id"], coord_h))
        assert after["status"] == "PENDING"


class TestExistenceAndTemporal:
    def test_document_create_for_missing_file_not_found(self):
        """PRD §2.5: "Third, existence of every path id and body foreign-key id,
        validated left-to-right as the ids appear in the URL and then the payload;
        each unresolved id produces its own entity-specific 404
        (`ERR_COORDINATOR_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`,
        `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`,
        `ERR_DEADLINE_NOT_FOUND`, `ERR_REMINDER_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_COMMUNICATION_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`,
        `ERR_SIGNATURE_REQUEST_NOT_FOUND`, `ERR_CLOSING_VERIFICATION_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`)."

        Design: Corner/validations/document_create_for_missing_file_not_found
        """
        coord, coord_h = make_coordinator()
        resp = api_client.create_document(
            create_document_payload(file_id=ABSENT_UUID, doc_type="EXECUTED_CONTRACT"), coord_h
        )
        validate_error(resp, ApiErrorId.ERR_FILE_NOT_FOUND)

    def test_file_create_closing_in_past_rejected(self):
        """PRD §3.3: "The closing date is validated against the logical clock at
        creation: a `closing_date` before the current clock date is rejected with
        `ERR_CLOSING_DATE_IN_PAST`."
        PRD §2.8: "At startup the current time is exactly 2026-08-01T00:00:00Z and
        never advances on its own."

        Design: Corner/validations/file_create_closing_in_past_rejected
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        payload = create_file_payload(
            seller_agent_id=seller["id"],
            effective_date="2026-07-01",
            closing_date="2026-07-20",
        )
        resp = api_client.create_file(payload, coord_h)
        validate_error(resp, ApiErrorId.ERR_CLOSING_DATE_IN_PAST)

    def test_communication_response_due_in_past_rejected(self):
        """PRD §3.5: "Each entry records `author_role` from the caller's
        `X-User-Role` and starts `OPEN` with `entry_kind` `LOG` (other kinds being
        `ESCALATION` and `SYSTEM`). An optional `in_reply_to_id` references another
        entry on the file; when it references an `OPEN` entry, that referenced entry
        is marked `ANSWERED`."
        PRD §3.5: "Creating one requires `file_id`, `party` (one of `BUYER_AGENT`,
        `SELLER_AGENT`, `LENDER`, `TITLE`, `COORDINATOR`, `SYSTEM`), `direction`
        (`INBOUND`, `OUTBOUND`, or `SYSTEM`), and `body`; `requires_response` defaults
        to false, and when it is true a `response_due_at` must be supplied that is
        strictly after the current clock time, otherwise `ERR_RESPONSE_DUE_IN_PAST`."

        Design: Corner/validations/communication_response_due_in_past_rejected
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        resp = api_client.create_communication(
            {
                "file_id": file_id,
                "party": "SELLER_AGENT",
                "direction": "OUTBOUND",
                "body": "late ask",
                "requires_response": True,
                "response_due_at": "2026-07-15T09:00:00Z",
            },
            coord_h,
        )
        validate_error(resp, ApiErrorId.ERR_RESPONSE_DUE_IN_PAST)


class TestUniquenessAndReferential:
    def test_second_active_template_rejected(self):
        """PRD §3.1: "Publishing moves a template from `DRAFT` to `ACTIVE`. The
        template must currently be in `DRAFT` (otherwise `ERR_TEMPLATE_INVALID_STATE`),
        its `milestone_defs` must be non-empty (otherwise `ERR_INVALID_REQUEST`), and
        — critically — at most one template may be `ACTIVE` for any given pair of
        `state_code` and `contract_type`; publishing a second one is rejected with
        `ERR_TEMPLATE_ALREADY_ACTIVE`. Every publish increments `template_version` by
        1."

        Design: Corner/validations/second_active_template_rejected
        """
        make_template(state_code="TX", contract_type="LISTING_ONLY")
        tmpl_b = make_template(
            state_code="TX", contract_type="LISTING_ONLY",
            milestone_defs=[{"name": "Photo Day", "offset_days": 2, "mandatory": False}],
            publish=False,
        )
        resp = api_client.publish_template(tmpl_b["id"], TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_ALREADY_ACTIVE)
        after = validate_success(api_client.get_template(tmpl_b["id"], TEST_USERS["admin_headers"]))
        assert after["status"] == "DRAFT"
        assert after["template_version"] == 1

    def test_second_subscription_rejected(self):
        """PRD §3.2: "The subscription starts `ACTIVE` with `included_files_used` at
        0, and a coordinator may hold at most one `ACTIVE` subscription — a second
        open attempt is rejected with `ERR_SUBSCRIPTION_ALREADY_ACTIVE`."

        Design: Corner/validations/second_subscription_rejected
        """
        coord, coord_h = make_coordinator()
        make_subscription(coord_h, included_files_quota=1, overage_fee_cents=34900)
        resp = api_client.create_subscription(
            create_subscription_payload(monthly_fee_cents=19900, included_files_quota=5,
                                        overage_fee_cents=24900),
            coord_h,
        )
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_ALREADY_ACTIVE)
        rows = get_success_data(api_client.list_subscriptions(coord_h, params={"limit": 10}))
        assert len(rows) == 1, "the rejected second subscription must not be persisted"

    def test_cancelled_subscription_reuse_rejected(self):
        """PRD §3.3: "Two fields are conditionally required: `buyer_agent_id` is
        required exactly when the contract type is `PURCHASE_SALE` and null is allowed
        otherwise (a missing buyer agent on a purchase-sale is `ERR_INVALID_REQUEST`);
        `subscription_id` is required exactly when the billing model is `SUBSCRIPTION`
        and forbidden otherwise, and it must reference a subscription that exists, is
        `ACTIVE`, and belongs to the acting coordinator, otherwise
        `ERR_SUBSCRIPTION_INACTIVE`."

        Design: Corner/validations/cancelled_subscription_reuse_rejected
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        sub = make_subscription(coord_h, included_files_quota=1, overage_fee_cents=34900)
        validate_success(api_client.cancel_subscription(sub["id"], coord_h))
        current = validate_success(api_client.get_subscription(sub["id"], coord_h))
        resp = api_client.create_file(
            create_file_payload(
                billing_model="SUBSCRIPTION",
                subscription_id=sub["id"],
                expected_subscription_version=current["version"],
                seller_agent_id=seller["id"],
            ),
            coord_h,
        )
        # The OCC version matched (412 would be wrong); the failure is purely the
        # inactive reference.
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_INACTIVE)


class TestSubscriptionOcc:
    def test_occ_stale_subscription_version_rejected(self):
        """PRD §2.6: "A request that creates a `SUBSCRIPTION`-billed transaction file
        must carry `expected_subscription_version`, a non-optional field holding the
        client's last observed `version` of the target `Subscription`. File creation
        commits an included-files slot and increments the subscription's `version`, so
        a create carrying a previously observed version is stale even when quota
        semantics would otherwise allow the commitment; it is rejected with
        `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412). Endpoints not named here do not
        take a version field."

        Design: Corner/cross_cutting_layers/occ_stale_subscription_version_rejected
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        sub = make_subscription(coord_h, included_files_quota=5, overage_fee_cents=34900)
        sub_v = sub["version"]
        payload_a = create_file_payload(
            billing_model="SUBSCRIPTION", subscription_id=sub["id"],
            expected_subscription_version=sub_v, seller_agent_id=seller["id"],
        )
        validate_success(api_client.create_file(payload_a, coord_h), expected_status=201)
        # Quota semantics would allow file B (1 < 5), but the observed version is stale.
        payload_b = create_file_payload(
            billing_model="SUBSCRIPTION", subscription_id=sub["id"],
            expected_subscription_version=sub_v, seller_agent_id=seller["id"],
            property_address="2 Oak Ave", closing_date="2026-09-02",
        )
        resp = api_client.create_file(payload_b, coord_h)
        validate_error(resp, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION)
        after = validate_success(api_client.get_subscription(sub["id"], coord_h))
        assert after["included_files_used"] == 1, "only the first file committed a slot"
