"""Authentication and authorization: the unauthenticated gate, role denials,
grower ownership scoping, and the ladder's existence-before-shape ordering."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_grower,
    set_clock,
    setup_issued_invoice,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS, make_grower_headers

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestAuthentication:
    @pytest.mark.parametrize("headers", [
        {},  # neither header present
        {"X-User-ID": "someone", "Content-Type": "application/json"},  # no role
        build_user_headers("someone", "Wizard"),  # undeclared role
    ])
    def test_unauthenticated_request_rejected(self, api, headers):
        """PRD §2.1: "A request missing either header, or presenting an
        `X-User-Role` that names no declared role, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)." PRD §2.6: authentication is tier 1
        — "a failure higher on the ladder is never masked by one lower down",
        so even a nonexistent resource id surfaces the auth error first.

        Design: Corner/validations/unauthenticated_request_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.get_grower(NON_EXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestExistenceBeforeShape:
    def test_existence_checked_before_request_shape(self, api):
        """PRD §2.6: "a request that would fail checks in two different tiers
        is rejected with the error from the earlier tier" — tier 4
        ("**Existence** — every resource referenced in the path exists,
        validated left to right (§2.11); otherwise `ERR_NOT_FOUND`
        (HTTP 404)") precedes tier 5 ("**Request well-formedness** — required
        fields are present, types are valid, enum members are valid, and
        numeric ranges are respected; otherwise `ERR_INVALID_REQUEST`
        (HTTP 400)").

        Design: Corner/validations/existence_checked_before_request_shape
        """
        set_clock("2026-08-01T00:00:00Z")
        # A POST under a nonexistent grove with an empty (invalid) body.
        resp = api_client.create_maturity_test(
            NON_EXISTENT_UUID, {}, TEST_USERS["inspector_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRoleDenials:
    def test_field_supervisor_cannot_manage_pools(self, api):
        """PRD §2.1: "A caller whose role does not appear in the endpoint's
        authorized set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD
        §4: `POST /packinghouse/pools` authorizes only `PoolAccountant`.

        Design: Corner/rbac/field_supervisor_cannot_manage_pools
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.create_pool(
            {"variety": "HAMLIN", "week_start": "2026-07-27"}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        _rows, meta = validate_paginated(api_client.list_pools(ACCOUNTANT))
        assert meta["total_count"] == 0, "the denied call persists no pool"

    def test_non_admin_cannot_set_clock(self, api):
        """PRD §2.5: "A `PackinghouseAdmin`-only test-driving capability
        advances the clock by supplying a `to_iso8601` instant". PRD §2.1:
        "A caller whose role does not appear in the endpoint's authorized set
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/non_admin_cannot_set_clock
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.set_clock("2026-08-02T00:00:00Z",
                                    TEST_USERS["officer_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        # The clock was not advanced: a resource created now still stamps the
        # original instant (PRD §2.5: the clock "never falls back to
        # wall-clock time" and only the authorized call moves it).
        grower = create_grower("GR-RB4", "Clock Witness")
        assert grower["created_at"].startswith("2026-08-01T00:00:00")


class TestGrowerOwnership:
    def test_grower_cannot_touch_other_growers_invoice(self, api):
        """PRD §2.1: "When `X-User-Role` is `Grower`, `X-User-ID` is the `id`
        of the acting Grower record; ownership checks on any resource that
        references a grower compare the resource's grower reference — directly
        on advances and invoices, or through the owning grower of the target
        grove — to `X-User-ID`. A mismatch is rejected with
        `ERR_GROWER_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/grower_cannot_touch_other_growers_invoice
        """
        scenario = setup_issued_invoice("RB2")
        owner_headers = make_grower_headers(scenario["grower"]["id"])
        other = create_grower("GR-RB2B", "Owner B")
        invoice_id = scenario["invoice"]["id"]
        # Grower B paying grower A's invoice: the role is allowed, the
        # identity is wrong.
        resp = api_client.pay_caretaking_invoice(
            invoice_id, {"amount_cents": 1000}, make_grower_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_GROWER_OWNERSHIP_MISMATCH)
        # The owning grower pays its own invoice.
        paid = validate_success(api_client.pay_caretaking_invoice(
            invoice_id, {"amount_cents": 1000}, owner_headers),
            expected_status=201)
        assert paid["paid_cents"] == 1000
        assert paid["status"] == "PARTIALLY_PAID"
