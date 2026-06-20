"""Role-based access control and authentication (PRD §2.1)."""
import pytest

from test_helpers import (
    validate_error,
    set_clock,
    create_herd,
    ApiErrorId,
    TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]
VET = TEST_USERS["veterinarian_headers"]
FEED = TEST_USERS["feedlot_operator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestRoleAuthorization:
    def test_feedlot_operator_cannot_create_animal(self, api):
        """PRD §2.1: "The `HerdManager` owns animal registration, life-status changes,
        breeding records and their transitions, movement planning and application,
        mortality recording, and the setup of herds and pastures."
        PRD §2.1: "When an authenticated user attempts an operation that their role is
        not permitted to perform, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/feedlot_operator_cannot_create_animal
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        resp = api.create_animal(
            {"herd_id": herd["id"], "ear_tag": "R010", "sex": "STEER",
             "birth_date": "2024-01-01", "birth_weight_kg": 40.0},
            FEED,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_herd_manager_cannot_create_drug_product(self, api):
        """PRD §2.1: "The `Veterinarian` owns the drug-product catalogue, health
        treatments and their voiding, and the confirmation of pregnancy on a breeding
        record."
        PRD §2.1: "When an authenticated user attempts an operation that their role is
        not permitted to perform, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/herd_manager_cannot_create_drug_product
        """
        set_clock("2026-04-01T00:00:00Z")
        resp = api.create_drug_product(
            {"name": "Vax", "category": "VACCINE",
             "route_withdrawals": {"INJECTION_SC": 0}},
            HM,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_auditor_cannot_create_sale_lot(self, api):
        """PRD §2.1: "The `SaleClerk` owns sale lots, weight tickets, and sale
        finalization or withdrawal."
        PRD §2.1: "The `Auditor` is read-only and may read every collection, herd
        summary, and trace chain, but may write nothing."

        Design: Corner/rbac/auditor_cannot_create_sale_lot
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        resp = api.create_sale_lot(
            {"herd_id": herd["id"], "channel": "AUCTION",
             "pencil_shrink_pct": 0, "commission_pct": 0.05},
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request to the API must be authenticated through two
        mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and
        the `X-User-Role` header declares the operational capacity under which they are
        acting. If either header is missing or malformed, the request is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_returns_401
        """
        set_clock("2026-04-01T00:00:00Z")
        resp = api.create_herd(
            {"name": "Anon", "species": "CATTLE", "premises_id": "PRR-9"},
            {},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
