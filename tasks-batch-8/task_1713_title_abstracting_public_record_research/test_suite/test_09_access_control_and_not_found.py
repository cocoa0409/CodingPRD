"""Authentication, authorization, and per-resource not-found coverage (PRD §2.1, §2.10)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    ApiErrorId,
    create_order,
    create_order_payload,
    make_client_headers,
    make_ops_headers,
    validate_error,
)


class TestAuthentication:
    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting party, and `X-User-Role`, naming the capacity in
        which they act. A request missing either header, or presenting a role the
        system does not declare, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/unauthenticated_request_rejected
        """
        resp = api.create_abstract_order(
            create_order_payload("client_851", property_address="70 Bee St"),
            NO_AUTH_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestClientVisibility:
    def test_client_cannot_read_other_clients_order(self, api):
        """PRD §2.1: "a `Client` may place an order only when the request's
        `client_ref` equals `X-User-ID`, and may later read or cancel only orders
        whose `client_ref` matches"
        PRD §3.1: "The intake payload names the opaque client identifier
        `client_ref` — which must equal the caller's `X-User-ID`, or the placement
        is refused with `ERR_FORBIDDEN`"

        Design: Corner/rbac/client_cannot_read_other_clients_order
        """
        order = create_order("client_865a", property_address="84 Bee St")

        cross_read = api.get_abstract_order(order["id"], make_client_headers("client_865b"))
        validate_error(cross_read, ApiErrorId.ERR_FORBIDDEN)

        spoof = api.create_abstract_order(
            create_order_payload("client_865a", property_address="85 Bee St"),
            make_client_headers("client_865b"),
        )
        validate_error(spoof, ApiErrorId.ERR_FORBIDDEN)


class TestNotFound:
    """PRD §2.10: "Requests that reference resources through path or body
    identifiers are validated in a strict, left-to-right sequence. The parent
    order is resolved first — a reference to a nonexistent order yields
    `ERR_ORDER_NOT_FOUND` before any child identifier is examined — and only then
    the assignment, document, check, report, curative requirement, or retrieval
    named by the request, each surfacing its own not-found error
    (`ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_CHECK_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_CURATIVE_NOT_FOUND`, `ERR_RETRIEVAL_NOT_FOUND`)."
    """

    def test_order_get_not_found_returns_404(self, api):
        """PRD §2.10: "a reference to a nonexistent order yields
        `ERR_ORDER_NOT_FOUND` before any child identifier is examined"

        Design: Corner/entities/order_get_not_found_returns_404
        """
        resp = api.get_abstract_order(NON_EXISTENT_UUID, make_ops_headers())
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)

    def test_assignment_get_not_found_returns_404(self, api):
        """PRD §2.10: "only then the assignment, document, check, report, curative
        requirement, or retrieval named by the request, each surfacing its own
        not-found error (`ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_CHECK_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CURATIVE_NOT_FOUND`,
        `ERR_RETRIEVAL_NOT_FOUND`)."

        Design: Corner/errors/assignment_get_not_found_returns_404
        """
        resp = api.get_search_assignment(NON_EXISTENT_UUID, make_ops_headers())
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND)

    def test_document_get_not_found_returns_404(self, api):
        """PRD §2.10: "only then the assignment, document, check, report, curative
        requirement, or retrieval named by the request, each surfacing its own
        not-found error (`ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_CHECK_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CURATIVE_NOT_FOUND`,
        `ERR_RETRIEVAL_NOT_FOUND`)."

        Design: Corner/errors/document_get_not_found_returns_404
        """
        resp = api.get_record_document(NON_EXISTENT_UUID, make_ops_headers())
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_FOUND)

    def test_legal_check_get_not_found_returns_404(self, api):
        """PRD §2.10: "only then the assignment, document, check, report, curative
        requirement, or retrieval named by the request, each surfacing its own
        not-found error (`ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_CHECK_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CURATIVE_NOT_FOUND`,
        `ERR_RETRIEVAL_NOT_FOUND`)."

        Design: Corner/errors/legal_check_get_not_found_returns_404
        """
        resp = api.get_legal_description_check(NON_EXISTENT_UUID, make_ops_headers())
        validate_error(resp, ApiErrorId.ERR_CHECK_NOT_FOUND)

    def test_report_get_not_found_returns_404(self, api):
        """PRD §2.10: "only then the assignment, document, check, report, curative
        requirement, or retrieval named by the request, each surfacing its own
        not-found error (`ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_CHECK_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CURATIVE_NOT_FOUND`,
        `ERR_RETRIEVAL_NOT_FOUND`)."

        Design: Corner/errors/report_get_not_found_returns_404
        """
        resp = api.get_abstract_report(NON_EXISTENT_UUID, make_ops_headers())
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FOUND)

    def test_curative_get_not_found_returns_404(self, api):
        """PRD §2.10: "only then the assignment, document, check, report, curative
        requirement, or retrieval named by the request, each surfacing its own
        not-found error (`ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_CHECK_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CURATIVE_NOT_FOUND`,
        `ERR_RETRIEVAL_NOT_FOUND`)."

        Design: Corner/errors/curative_get_not_found_returns_404
        """
        resp = api.get_curative_requirement(NON_EXISTENT_UUID, make_ops_headers())
        validate_error(resp, ApiErrorId.ERR_CURATIVE_NOT_FOUND)

    def test_retrieval_get_not_found_returns_404(self, api):
        """PRD §2.10: "only then the assignment, document, check, report, curative
        requirement, or retrieval named by the request, each surfacing its own
        not-found error (`ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_CHECK_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CURATIVE_NOT_FOUND`,
        `ERR_RETRIEVAL_NOT_FOUND`)."

        Design: Corner/errors/retrieval_get_not_found_returns_404
        """
        resp = api.get_county_retrieval(NON_EXISTENT_UUID, make_ops_headers())
        validate_error(resp, ApiErrorId.ERR_RETRIEVAL_NOT_FOUND)
