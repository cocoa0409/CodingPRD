"""Contract setup, schedule defaults, authentication, and authorization basics."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_contract,
    create_bid_item_payload,
    create_contract_payload,
    create_draft_contract,
    create_work_package_payload,
    get_success_data,
    setup_active_contract,
    validate_error,
    validate_success,
)

PM = TEST_USERS["contractor_pm_headers"]
FOREMAN = TEST_USERS["foreman_headers"]


class TestContractDefaults:
    def test_contract_creation_applies_percentage_defaults(self, api):
        """PRD §3.1: "Three percentage parameters shape the billing behavior and
        may be omitted: `retainage_pct` defaults to 0.10 — one tenth of every
        invoice subtotal is withheld as retainage — and must always be at least 0
        and strictly less than 1; `overrun_threshold_pct` defaults to 1.10,
        meaning cumulative accepted units up to one hundred ten percent of a bid
        item's estimate bill at the base price; and `quantity_cap_pct` defaults
        to 1.25, meaning reported production may never exceed one hundred
        twenty-five percent of the estimate. A new contract stands in `DRAFT`."

        Design: Corner/entities/contract_creation_applies_defaults
        """
        resp = api.create_contract(
            create_contract_payload(contract_number="CD-1"), PM)
        contract = validate_success(resp, 201)
        assert_contract(contract)
        assert contract["retainage_pct"] == pytest.approx(0.10), (
            "retainage_pct defaults to 0.10 when omitted")
        assert contract["overrun_threshold_pct"] == pytest.approx(1.10), (
            "overrun_threshold_pct defaults to 1.10 when omitted")
        assert contract["quantity_cap_pct"] == pytest.approx(1.25), (
            "quantity_cap_pct defaults to 1.25 when omitted")
        assert contract["status"] == "DRAFT", "A new contract stands in DRAFT"


class TestContractInputValidation:
    def test_contract_missing_utility_name_rejected(self, api):
        """PRD §3.1: "Everything begins when a `CONTRACTOR_PM` registers the
        engagement as a new contract, supplying the `utility_name`, a
        `contract_number` that must be unique across all contracts, and the
        agreement's `effective_start` and `effective_end` instants, with the end
        required to fall on or after the start."
        PRD §2.9: "3. Request shape — required fields present, enum values drawn
        from their declared sets, numeric constraints satisfied (positive
        quantities and rates, percentages in range), otherwise
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/contract_missing_required_field_rejected
        """
        payload = create_contract_payload(contract_number="CD-2")
        del payload["utility_name"]
        resp = api.create_contract(payload, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_unknown_contract_returns_not_found(self, api):
        """PRD §2.9: "4. Existence — path identifiers are resolved left to right,
        then foreign-key references in the body; the first reference that does
        not exist is rejected with `ERR_NOT_FOUND`."

        Design: Corner/entities/contract_not_found_returns_404
        """
        resp = api.get_contract(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthenticationOrder:
    def test_request_without_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does not
        name one of the five declared roles is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.9: "1. Authentication — the `X-User-Role` header must be present
        and name a declared role, otherwise `ERR_UNAUTHENTICATED`."
        Authentication runs before existence, so even an unknown id yields 401.

        Design: Corner/validations/missing_role_header_unauthenticated
        """
        resp = api.get_contract(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_foreman_cannot_create_contract(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among
        the roles permitted for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/contracts` | Create a contract in `DRAFT` |
        CONTRACTOR_PM |"

        Design: Corner/validations/foreman_cannot_create_contract
        """
        resp = api.create_contract(
            create_contract_payload(contract_number="CV-1"), FOREMAN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestContractActivityGates:
    def test_work_package_create_on_draft_contract_rejected(self, api):
        """PRD §3.2: "The project manager creates one under an `ACTIVE` contract
        with a `name`, a `location` describing the feeder, address, or mileage,
        and an optional `requires_outage` flag — false by default, and true only
        when production may be reported solely under a live outage window."
        PRD §2.10: "Operational writes are only accepted while the owning
        contract is `ACTIVE`. When the contract is `SUSPENDED`, such writes are
        rejected with `ERR_CONTRACT_SUSPENDED` (HTTP 409); when it is `DRAFT` or
        `CLOSED`, they are rejected with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/validations/work_package_create_requires_active_contract
        """
        contract = create_draft_contract(contract_number="CD-4")
        get_success_data(api.create_bid_item(
            contract["id"], create_bid_item_payload(), PM))
        resp = api.create_work_package(
            contract["id"],
            create_work_package_payload(name="Too early", location="L8"),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    def test_bid_items_locked_after_activation(self, api):
        """PRD §3.1: "The moment the contract leaves `DRAFT`, the schedule locks:
        any further attempt to add a bid item is rejected with
        `ERR_BID_ITEMS_LOCKED`."

        Design: Corner/validations/bid_items_locked_after_activation
        """
        contract, _ = setup_active_contract(
            contract_overrides={"contract_number": "CD-3"})
        resp = api.create_bid_item(
            contract["id"],
            create_bid_item_payload(item_code="OH-LATE", unit_price=99.00,
                                    estimated_quantity=10),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_BID_ITEMS_LOCKED)

    def test_contract_close_blocked_by_open_work_packages(self, api):
        """PRD §3.1: "Closure is the mirror act at the end of the engagement — a
        transition with `to` set to `CLOSED` succeeds only when every work
        package of the contract has reached a terminal state, `COMPLETED` or
        `CANCELLED`; while any work package remains open the close is rejected
        with `ERR_OPEN_WORK_PACKAGES`."

        Design: Corner/validations/contract_close_blocked_by_open_work_packages
        """
        contract, _ = setup_active_contract(
            contract_overrides={"contract_number": "CV-12"})
        get_success_data(api.create_work_package(
            contract["id"],
            create_work_package_payload(name="WP open", location="L18"),
            PM))
        resp = api.transition_contract(contract["id"], {"to": "CLOSED"}, PM)
        validate_error(resp, ApiErrorId.ERR_OPEN_WORK_PACKAGES)
        contract_after = validate_success(api.get_contract(contract["id"], PM))
        assert contract_after["status"] == "ACTIVE", (
            "The rejected close leaves the contract ACTIVE")
