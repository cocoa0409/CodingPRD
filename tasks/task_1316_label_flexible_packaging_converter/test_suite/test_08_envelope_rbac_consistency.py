"""Response envelope shape, authentication/authorization gates, and immediate
read-after-write consistency."""
from test_helpers import (
    EST,
    NON_EXISTENT_UUID,
    PREPRESS,
    PRESS_OP,
    api_client,
    create_customer,
    current_job_version,
    get_job,
    job_chain,
    validate_error,
    validate_success,
)


class TestEnvelopes:

    def test_error_envelope_shape_on_rejection(self):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format:"
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.5: "Identifiers embedded in the URL are resolved strictly left
        to right — customer before job, job before measurement, roll or letter
        — and the first identifier that does not resolve to an existing
        resource is rejected with `ERR_NOT_FOUND`; deeper identifiers are never
        examined."

        Design: Corner/endpoints/error_envelope_shape_on_rejection
        """
        resp = api_client.get_job(NON_EXISTENT_UUID, EST)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"].startswith("req_"), \
            "error meta carries a req_-prefixed request id"
        assert body["meta"]["api_request_timestamp"]
        error_data = body["data"]
        assert error_data["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(error_data["message"], str) and \
            error_data["message"].strip(), "message must be non-empty"


class TestAuthGates:

    def test_missing_auth_header_rejected(self):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, declaring the
        capacity in which they act. A request in which either header is missing
        or malformed is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
        PRD §2.5: "**Authentication context.** The `X-User-ID` and
        `X-User-Role` headers must be present and well-formed, else the request
        fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` before anything
        else is examined."

        Design: Corner/rbac/missing_auth_header_rejected
        """
        resp = api_client.list_customers(headers=None)
        validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       expected_status=400)

    def test_rbac_press_operator_cannot_create_customer(self):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §2.1: "`Estimator` — the commercial desk: customer accounts,
        substrates, ink recipes, dies, presses, and job quoting, approval,
        release and cancellation."
        PRD §2.1: "`PressOperator` — the pressroom: starting and completing
        press runs, and recording color measurements and finished rolls."

        Design: Corner/rbac/rbac_press_operator_cannot_create_customer
        """
        resp = api_client.create_customer({"account_name": "Forbidden Co"},
                                          PRESS_OP)
        validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS",
                       expected_status=403)

    def test_rbac_prepress_cannot_ship(self):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §2.1: "`QualityManager` — quality assurance: judging color
        measurements, accepting or rejecting rolls, issuing compliance letters,
        and shipping jobs."
        PRD §2.5: "**Authorization.** The declared role must be permitted on
        the endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/rbac_prepress_cannot_ship
        """
        chain = job_chain(stop_at="REWOUND", account_name="RBAC Ship Co",
                          artwork_code="AW-RB", substrate_code="RB-1",
                          recipe_code="INK-RB", die_code="D-RB",
                          press_code="P-RB", quantity_ordered=1000)
        job_id = chain["job"]["id"]
        resp = api_client.ship_job(
            job_id, {"expected_job_version": current_job_version(job_id)},
            PREPRESS)
        validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS",
                       expected_status=403)
        assert resp.status_code == 403
        assert get_job(job_id)["status"] == "REWOUND", \
            "role rejection fires before any state change"


class TestImmediateConsistency:

    def test_immediate_visibility_after_mutation(self):
        """PRD §3.1: "Later account maintenance — most commonly placing or
        lifting a credit hold — is likewise an `Estimator` operation, and each
        update increments the customer's `version`."
        PRD §2.4: "Alongside it, resources carry `created_at` and `updated_at`
        — ISO 8601 UTC timestamps with three fractional digits (for example,
        `2025-05-24T10:30:00.123Z`) — and an integer `version` that increments
        by one on every mutation of the resource, whether the mutation is
        client-invoked or server-driven. `updated_at` refreshes on the same
        occasions."

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        customer = create_customer(account_name="Imm Co")
        assert customer["credit_hold"] is False
        created_version = customer["version"]

        patched = validate_success(api_client.patch_customer(
            customer["id"], {"credit_hold": True}, EST))
        assert patched["credit_hold"] is True
        assert patched["version"] == created_version + 1

        reread = validate_success(api_client.get_customer(customer["id"], EST))
        assert reread["credit_hold"] is True, \
            "the write is visible on the immediately following read"
        assert reread["version"] == patched["version"]
