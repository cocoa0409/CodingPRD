"""Role authorization, entity-backed scoping, and identity headers.

Covers PRD §2.1 identity headers and role rejection, §2.8 evaluation order
(role authorization before state and segregation), §3.5 carrier-scoped
dispute responses, and §2.1 ClientViewer cross-client confinement.
"""
from test_helpers import (
    ANALYST,
    NO_AUTH_HEADERS,
    ApiErrorId,
    build_rate_mismatch_exception,
    create_active_carrier,
    create_client,
    create_payment_run,
    make_carrier_rep_headers,
    make_client_viewer_headers,
    set_clock,
    setup_standard_chain,
    validate_error,
    validate_success,
)


class TestIdentityHeaders:
    def test_request_without_auth_headers_is_rejected(self, api):
        """PRD §2.1: "All interactions with the API are authenticated through
        two mandatory HTTP headers: `X-User-ID`, identifying the acting user,
        and `X-User-Role`, declaring the capacity in which they act. A request
        missing either header, or carrying a malformed value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/request_missing_auth_headers_unauthenticated
        """
        set_clock()
        res = api.list_clients(NO_AUTH_HEADERS)
        validate_error(
            res,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )


class TestRoleDenial:
    def test_carrier_rep_cannot_capture_invoice(self, api):
        """PRD §2.1: "Any attempt to perform an operation outside the actor's
        role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." Invoice
        intake belongs to the audit operator: PRD §3.3: "The `AuditAnalyst`
        presents the invoicing `carrier_id`, the carrier's `invoice_number`,
        the `invoice_date`, the invoice `currency`, the `billed_total_minor`,
        the `lines` array".

        Design: Corner/rbac/rbac_carrier_rep_cannot_create_invoice
        """
        chain = setup_standard_chain(with_contract=False)
        res = api.create_invoice(
            chain["client"]["id"],
            {
                "carrier_id": chain["carrier"]["id"],
                "invoice_number": "INV-X",
                "invoice_date": "2026-08-03",
                "currency": "USD",
                "billed_total_minor": 100,
                "lines": [{"charge_code": "OTHER", "billed_amount_minor": 100}],
            },
            make_carrier_rep_headers(chain["carrier"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_audit_analyst_cannot_release_run(self, api):
        """PRD §3.8: "Release (`LOCKED` → `RELEASED`) belongs to
        `TreasuryApprover` and enforces segregation of duties". PRD §2.8:
        "Every request passes through a fixed evaluation pipeline, and a
        failure at any stage short-circuits the stages after it" — role
        authorization (stage 2) precedes state legality, so an `AuditAnalyst`
        is refused even on a DRAFT run.

        Design: Corner/rbac/rbac_analyst_cannot_release_run
        """
        chain = setup_standard_chain(with_contract=False)
        run = create_payment_run(chain["client"]["id"])
        res = api.release_payment_run(run["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)


class TestEntityBackedScoping:
    def test_carrier_rep_responds_only_for_own_carrier(self, api):
        """PRD §3.5: "A `CarrierRep` then answers, moving `CARRIER_NOTIFIED` →
        `CARRIER_RESPONDED`, optionally attaching a `response_note`; the acting
        carrier's identity must match the invoice's `carrier_id`
        (`ERR_FORBIDDEN_FOR_ROLE` otherwise), and the same dispute-window check
        applies with the same error."

        The representative of carrier B is refused on carrier A's dispute;
        carrier A's own representative succeeds.

        Design: Corner/rbac/carrier_rep_scoped_to_own_carrier
        """
        chain = setup_standard_chain(client_overrides={
            "audit_tolerance_minor": 500, "audit_tolerance_pct_bp": 200,
        })
        other = create_active_carrier(
            chain["client"]["id"],
            scac_code="OTH",
            legal_name="Other Carrier",
            remit_email="remit@oth.example",
        )
        invoice, exception = build_rate_mismatch_exception(chain)
        validate_success(api.notify_exception_carrier(exception["id"], ANALYST), 200)
        res = api.respond_exception_carrier(
            exception["id"], {}, make_carrier_rep_headers(other["id"])
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)
        responded = validate_success(
            api.respond_exception_carrier(
                exception["id"], {}, make_carrier_rep_headers(chain["carrier"]["id"])
            ),
            200,
        )
        assert responded["status"] == "CARRIER_RESPONDED"

    def test_client_viewer_cross_client_read_is_not_found(self, api):
        """PRD §2.1: "When `X-User-Role` is `ClientViewer`, `X-User-ID` is the
        `id` of the acting ClientAccount: reads are confined to resources whose
        `client_id` equals `X-User-ID`, and cross-client reads likewise return
        `ERR_NOT_FOUND`, so one tenant's data is never revealed to another."

        Design: Corner/rbac/client_viewer_cross_client_read_returns_not_found
        """
        set_clock()
        client_one = create_client(name="Acme")
        client_two = create_client(name="Beta")
        res = api.get_client(client_two["id"], make_client_viewer_headers(client_one["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        own = validate_success(
            api.get_client(client_one["id"], make_client_viewer_headers(client_one["id"]))
        )
        assert own["id"] == client_one["id"]
