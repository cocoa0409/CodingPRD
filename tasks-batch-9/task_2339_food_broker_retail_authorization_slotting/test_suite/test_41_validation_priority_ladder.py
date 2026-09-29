"""One five-way-invalid item setup, repaired one rung at a time: 401, 403, 400, 400, 404, 201."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    CatalogState,
    PRIMARY_CATEGORY,
    UPC_1,
    UPC_BAD_CHECK_DIGIT,
    fixtures,
    get_success_data,
    headers_for_role,
    make_retailer_buyer_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F

UNDECLARED_ROLE = "ChainManager"


@pytest.fixture
def one_chain_and_one_principal(api):
    """A real chain and a real principal, so only the defects under test remain."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    principal = fixtures.create_principal(api, slotting_budget_cents=20000000)
    return {"retailer": retailer, "principal": principal}


def five_way_invalid_payload():
    """Unknown principal, bad check digit and a missing required `description`."""
    payload = F.item_payload(NON_EXISTENT_UUID, upc=UPC_BAD_CHECK_DIGIT)
    del payload["description"]
    return payload


def payload_with_description():
    """Repairs only the shape defect: unknown principal and bad check digit remain."""
    return F.item_payload(NON_EXISTENT_UUID, upc=UPC_BAD_CHECK_DIGIT)


def payload_with_valid_upc():
    """Repairs the check digit too: only the unknown principal remains."""
    return F.item_payload(NON_EXISTENT_UUID, upc=UPC_1)


class TestValidationPriorityLadder:
    def test_an_undeclared_role_header_masks_every_other_defect(
        self, api, one_chain_and_one_principal
    ):
        """Four defects sit in the request and the caller never learns about any of them.

        PRD: "Validations are evaluated in ascending priority bands, and the **first** violated rule
        determines the response."

        PRD: "**Authentication.** `X-User-Role` and `X-User-ID` present, and the role one of the
        five declared names — otherwise `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/validations/priority_ladder_runs_auth_then_role_then_shape_then_lookup_then_scope
        """
        response = api.create_item(
            five_way_invalid_payload(), headers_for_role(UNDECLARED_ROLE, "u_ghost")
        )

        validate_error(response, ApiErrorId.UNAUTHENTICATED, 401)

    def test_the_role_gate_outranks_the_body_and_the_lookup(
        self, api, one_chain_and_one_principal
    ):
        """A declared but unauthorized role gets 403 while the body is still broken.

        PRD: "**Role permission.** The acting role appears in the endpoint's authorized list —
        otherwise `ERR_ROLE_FORBIDDEN` (403)."

        PRD: "| POST | `/items` | New item setup for a principal | BrokerAccountManager |"

        Design: Corner/validations/priority_ladder_runs_auth_then_role_then_shape_then_lookup_then_scope
        """
        response = api.create_item(five_way_invalid_payload(), BROKER_ADMIN_HEADERS)

        validate_error(response, ApiErrorId.ROLE_FORBIDDEN, 403)

    def test_a_missing_required_field_outranks_the_check_digit_and_the_lookup(
        self, api, one_chain_and_one_principal
    ):
        """With the role fixed, the absent `description` is reported before anything else.

        PRD: "**Request shape.** Required body fields present; types, enum membership and numeric
        ranges valid — for example `amortization_periods` between 1 and 12, `item_ids` holding 1 to 5
        elements, every basis-point field within 0 through 10,000, `upc` exactly twelve digits, dates
        well-formed."

        Design: Corner/validations/priority_ladder_runs_auth_then_role_then_shape_then_lookup_then_scope
        """
        response = api.create_item(five_way_invalid_payload(), ACCOUNT_MANAGER_HEADERS)

        validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

    def test_the_check_digit_is_the_last_shape_defect_before_lookups(
        self, api, one_chain_and_one_principal
    ):
        """Twelve digits that fail the checksum still answer 400, not the unknown principal's 404.

        PRD: "A `upc` that is twelve digits but fails its check digit returns
        `ERR_UPC_CHECK_DIGIT_INVALID` (400) in this same band."

        Design: Corner/validations/priority_ladder_runs_auth_then_role_then_shape_then_lookup_then_scope
        """
        response = api.create_item(payload_with_description(), ACCOUNT_MANAGER_HEADERS)

        validate_error(response, ApiErrorId.UPC_CHECK_DIGIT_INVALID, 400)

    def test_the_unknown_principal_surfaces_only_once_the_shape_is_clean(
        self, api, one_chain_and_one_principal
    ):
        """The body foreign key is the last remaining defect, so now it is the reported one.

        PRD: "**Existence.** Path identifiers are resolved left to right, then body foreign keys,
        yielding the 404 family described in §2.10."

        Design: Corner/validations/priority_ladder_runs_auth_then_role_then_shape_then_lookup_then_scope
        """
        response = api.create_item(payload_with_valid_upc(), ACCOUNT_MANAGER_HEADERS)

        validate_error(response, ApiErrorId.PRINCIPAL_NOT_FOUND, 404)

    def test_the_fully_repaired_request_creates_an_incomplete_item(
        self, api, one_chain_and_one_principal
    ):
        """Every rung of the ladder is satisfied, and the new item starts with no catalog data.

        PRD: "A new item begins with `catalog_state` at `INCOMPLETE` and `catalog_submission_round`
        at 0, and its five catalog attributes — `gtin14`, `dimensions_cm`, `gross_weight_g`,
        `nutrition_panel_url` and `shelf_life_days` — are all null until the first catalog
        submission."

        Design: Corner/validations/priority_ladder_runs_auth_then_role_then_shape_then_lookup_then_scope
        """
        scope = one_chain_and_one_principal

        item = get_success_data(
            api.create_item(
                F.item_payload(scope["principal"]["id"], upc=UPC_1), ACCOUNT_MANAGER_HEADERS
            ),
            201,
        )

        assert item["upc"] == UPC_1
        assert item["catalog_state"] == CatalogState.INCOMPLETE
        assert item["catalog_submission_round"] == 0
        assert item["gtin14"] is None
        assert item["shelf_life_days"] is None

    def test_a_missing_chain_is_reported_as_absent_rather_than_out_of_scope(
        self, api, one_chain_and_one_principal
    ):
        """A buyer can never own a chain that does not exist, and existence still answers first.

        PRD: "**Existence.** Path identifiers are resolved left to right, then body foreign keys,
        yielding the 404 family described in §2.10."

        PRD: "**Ownership scope.** A `RetailerBuyer` acting outside its own chain returns
        `ERR_RETAILER_SCOPE_FORBIDDEN` (403); a `PrincipalPortalUser` reading another principal's
        resource returns `ERR_PRINCIPAL_SCOPE_FORBIDDEN` (403)."

        Design: Corner/validations/priority_ladder_runs_auth_then_role_then_shape_then_lookup_then_scope
        """
        scope = one_chain_and_one_principal

        response = api.create_review(
            F.review_payload(NON_EXISTENT_UUID, category_code=PRIMARY_CATEGORY),
            make_retailer_buyer_headers(scope["retailer"]["id"]),
        )

        validate_error(response, ApiErrorId.RETAILER_NOT_FOUND, 404)
        _, meta = validate_paginated(api.list_reviews(BROKER_ADMIN_HEADERS))
        assert meta["total_count"] == 0
