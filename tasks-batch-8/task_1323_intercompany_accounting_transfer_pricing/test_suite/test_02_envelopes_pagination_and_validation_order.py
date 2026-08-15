"""Response envelopes, list pagination/filtering, and validation precedence."""
from test_helpers import (
    ADMIN,
    ANALYST,
    MANAGER,
    NON_EXISTENT_UUID,
    TP_LEAD,
    ApiErrorId,
    book_transaction,
    create_active_agreement,
    create_audit_case,
    create_doc,
    create_fiscal_year,
    create_legal_entity,
    setup_active_agreement,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestErrorEnvelope:

    def test_error_envelope_shape_on_not_found(self):
        """PRD section 2.2: "All error API responses (4xx status codes)
        follow this standard envelope format" with "response_type": "error".
        PRD section 2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error. The `message` provides a
        human-readable explanation of what went wrong."
        PRD section 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/error_envelope_shape_on_failure
        """
        resp = api_client.get_fiscal_year(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) \
            and len(body["data"]["message"]) > 0
        assert body["meta"]["api_request_id"].startswith("req_"), \
            "api_request_id must be present and start with req_"
        assert "api_request_timestamp" in body["meta"]


class TestExistenceBeforeState:

    def test_agreement_get_unknown_id_not_found(self):
        """PRD section 2.9: "Wherever an identifier appears — in a path
        variable or in a request-body foreign key such as an `agreement_id`
        or `fiscal_year_id` — the server must resolve it, in the order given
        by step 3 of §2.8, and reject the request with `ERR_NOT_FOUND` on the
        first identifier that does not correspond to an existing resource."

        Design: Corner/entities/agreement_get_unknown_id_returns_not_found
        """
        resp = api_client.get_agreement(NON_EXISTENT_UUID, MANAGER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_match_unknown_transaction_returns_not_found(self):
        """PRD section 2.8: "3. **Existence** — every identifier must
        resolve: path identifiers first, validated left to right, then
        body-supplied foreign keys in their declared order; the first
        unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404)."
        PRD section 2.8: "4. **State legality** — the target resource must be
        in a state from which the requested transition or operation is
        defined, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/validations/match_unknown_transaction_returns_not_found
        """
        resp = api_client.match_transaction(NON_EXISTENT_UUID, ANALYST)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthContext:

    def test_missing_role_header_rejected(self):
        """PRD section 2.1: "Every request must carry two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`,
        declaring the capacity in which they act. A request in which either
        header is missing or empty is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        headers_without_role = {
            "X-User-ID": "admin-1",
            "Content-Type": "application/json",
        }
        resp = api_client.create_fiscal_year(
            {"year_index": 2026, "group_revenue_eur": 100_000_000},
            headers_without_role,
        )
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestTransactionListing:

    def _setup_two_agreements_with_transactions(self):
        ctx = setup_active_agreement(transaction_type="SERVICES")
        tx_a = book_transaction(ctx["agreement"]["id"],
                                ctx["fiscal_year"]["id"])
        # Second agreement on a different transaction_type to avoid overlap.
        agreement_b = create_active_agreement(
            ctx["provider"]["id"], ctx["recipient"]["id"],
            ctx["study"]["id"], transaction_type="FINANCING")
        tx_b = book_transaction(agreement_b["id"], ctx["fiscal_year"]["id"])
        return ctx, tx_a, agreement_b, tx_b

    def test_transactions_list_filters_by_agreement(self):
        """PRD section 3.4: "The transactions listing accepts optional
        filters `agreement_id`, `fiscal_year_id`, `origin_run_id`,
        `elimination_status`, and `settlement_status`."
        PRD section 2.3: "List responses carry the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` inside the `meta` object of
        the response envelope."

        Design: Corner/endpoints/transactions_list_filters_by_agreement
        """
        ctx, tx_a, agreement_b, tx_b = \
            self._setup_two_agreements_with_transactions()
        resp = api_client.list_transactions(
            MANAGER, params={"agreement_id": ctx["agreement"]["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(data) == 1
        assert data[0]["id"] == tx_a["id"]
        assert data[0]["agreement_id"] == ctx["agreement"]["id"]
        assert all(item["id"] != tx_b["id"] for item in data)

    def test_pagination_limit_offset_window(self):
        """PRD section 2.3: "`limit` sets the maximum number of items
        returned; it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100. `offset` sets the number of items skipped and
        defaults to 0."
        PRD section 2.3: "List responses carry the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` inside the `meta` object of
        the response envelope."

        Design: Corner/endpoints/pagination_limit_offset_window
        """
        ctx = setup_active_agreement()
        for _ in range(3):
            book_transaction(ctx["agreement"]["id"],
                             ctx["fiscal_year"]["id"])

        window_resp = api_client.list_transactions(
            MANAGER, params={"agreement_id": ctx["agreement"]["id"],
                             "limit": 2, "offset": 2})
        window, window_meta = validate_paginated(window_resp)
        assert len(window) == 1
        assert window_meta["total_count"] == 3
        assert window_meta["has_more"] is False
        assert window_meta["limit"] == 2
        assert window_meta["offset"] == 2

        default_resp = api_client.list_transactions(
            MANAGER, params={"agreement_id": ctx["agreement"]["id"]})
        default, default_meta = validate_paginated(default_resp)
        assert len(default) == 3
        assert default_meta["total_count"] == 3
        assert default_meta["has_more"] is False
        assert default_meta["limit"] == 10
        assert default_meta["offset"] == 0


class TestValidationPrecedencePairs:

    def test_doc_file_state_error_beats_cbc_fiscal_error(self):
        """PRD section 2.8: "Every request is validated against a fixed
        sequence of check categories, and the first failing check determines
        the error returned — a caller always sees the earliest applicable
        failure, not a later one."
        PRD section 2.8: "4. **State legality** — the target resource must be
        in a state from which the requested transition or operation is
        defined, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
        PRD section 2.8: "9. **Fiscal-calendar obligations** — the year must
        be `CLOSING` for true-up approval and posting, must not be `CLOSED`
        for booking or filing, and country-by-country filing presence and
        obligation are enforced at close and at filing."

        Design: Difficulty/priority_pair_validation_conflict/doc_file_state_error_beats_cbc_fiscal_error
        """
        fy = create_fiscal_year(year_index=2026, group_revenue_eur=600_000_000)
        assert fy["cbc_required"] is False
        doc = create_doc(fy["id"], "CBC_REPORT")

        resp = api_client.file_doc_package(doc["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_doc_file_rejection_leaves_package_unchanged(self):
        """PRD section 2.8: "Every request is validated against a fixed
        sequence of check categories, and the first failing check determines
        the error returned — a caller always sees the earliest applicable
        failure, not a later one."
        PRD section 3.6: "Filing by a `TaxManager` (`APPROVED → FILED`)
        enforces three obligations: the fiscal year must not be `CLOSED`
        (`ERR_BOOKS_CLOSED`); a `CBC_REPORT` may only be filed for a year
        whose `cbc_required` is true (`ERR_CBC_NOT_REQUIRED`)"

        Design: Difficulty/priority_pair_validation_conflict/doc_file_state_error_beats_cbc_fiscal_error
        """
        fy = create_fiscal_year(year_index=2026, group_revenue_eur=600_000_000)
        doc = create_doc(fy["id"], "CBC_REPORT")

        resp = api_client.file_doc_package(doc["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api_client.get_doc_package(doc["id"], MANAGER),
                                 expected_status=200)
        assert after["status"] == "DRAFT", \
            "a rejected filing must not mutate the package"
        assert after["version"] == doc["version"]

    def test_audit_case_referential_error_beats_year_overlap(self):
        """PRD section 2.8: "Every request is validated against a fixed
        sequence of check categories, and the first failing check determines
        the error returned — a caller always sees the earliest applicable
        failure, not a later one."
        PRD section 2.8: "6. **Entity referential integrity** — referenced
        legal entities must be `ACTIVE` where required, and an agreement's
        provider and recipient must be distinct, else `ERR_ENTITY_INACTIVE`
        or `ERR_SAME_LEGAL_ENTITY`."
        PRD section 2.8: "7. **Temporal rules** — agreement effective-period
        overlap, APA covered-year disjointness, and the in-effect window at
        activation, surfacing `ERR_AGREEMENT_PERIOD_OVERLAP`,
        `ERR_APA_YEAR_OVERLAP`, or `ERR_AGREEMENT_NOT_IN_EFFECT`."

        Design: Difficulty/priority_pair_validation_conflict/audit_case_referential_beats_apa_year_overlap
        """
        entity = create_legal_entity()
        create_audit_case(entity["id"], case_type="APA",
                          covered_year_indexes=[2024, 2025])
        api_client.deactivate_legal_entity(entity["id"], ADMIN)

        resp = api_client.create_audit_case(
            {"entity_id": entity["id"], "case_type": "APA",
             "authority_country": "US", "covered_year_indexes": [2025, 2026]},
            TP_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_ENTITY_INACTIVE)

    def test_audit_case_inactive_entity_rejected_regardless_of_years(self):
        """PRD section 3.7: "a `TransferPricingLead` opens an **AuditCase**
        naming the audited `entity_id` (which must be `ACTIVE`)"
        PRD section 2.8: "6. **Entity referential integrity** — referenced
        legal entities must be `ACTIVE` where required, and an agreement's
        provider and recipient must be distinct, else `ERR_ENTITY_INACTIVE`
        or `ERR_SAME_LEGAL_ENTITY`."

        Design: Difficulty/priority_pair_validation_conflict/audit_case_referential_beats_apa_year_overlap
        """
        entity = create_legal_entity()
        create_audit_case(entity["id"], case_type="APA",
                          covered_year_indexes=[2024, 2025])
        api_client.deactivate_legal_entity(entity["id"], ADMIN)

        # Disjoint years: only the referential rule can fire.
        resp = api_client.create_audit_case(
            {"entity_id": entity["id"], "case_type": "APA",
             "authority_country": "US", "covered_year_indexes": [2027]},
            TP_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_ENTITY_INACTIVE)
