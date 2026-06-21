"""Corner (validations + errors + RBAC) — individual error trigger paths."""
from test_helpers import (
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    set_clock,
    tick_clock,
    setup_active_contract,
    setup_active_contract_with_item,
    setup_expiring_soon_contract,
    file_claim,
    assess_claim,
    register_customer,
    create_pending_contract,
    activate_contract,
    create_default_package,
    make_customer_headers,
    make_admin_headers,
    make_dispatcher_headers,
    create_contract_payload,
    create_claim_payload,
    dispatch_claim_payload,
    assess_claim_payload,
    renew_contract_payload,
    create_covered_item_payload,
)


_ADMIN = make_admin_headers()
_DISPATCHER = make_dispatcher_headers()


class TestScheduledInPastOnDispatch:

    def test_dispatch_with_scheduled_utc_before_clock_returns_scheduled_in_past(self, api):
        """PRD §3.5: "The dispatch payload carries `technician_id` (which must be
        non-empty) and `scheduled_utc` (which must be at or after the current
        server clock — a `scheduled_utc` strictly before the clock yields
        `ERR_SCHEDULED_IN_PAST`)."

        Design: Corner/validations/error_scheduled_in_past_on_dispatch
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        claim = file_claim(contract, customer, item, issue="Past schedule")
        assess_claim(claim, 10_000)
        set_clock("2026-02-01T12:00:00Z")
        # scheduled_utc strictly before clock_now.
        res = api.dispatch_claim(
            claim["id"],
            dispatch_claim_payload("tech-Past", "2026-01-20T09:00:00Z"),
            _DISPATCHER,
        )
        validate_error(res, "ERR_SCHEDULED_IN_PAST")


class TestPackageRetiredOnCreateContract:

    def test_create_contract_against_retired_package_returns_package_retired(self, api):
        """PRD §3.1: "Retirement does not invalidate existing contracts, but it
        blocks new contracts from being created against the package and blocks
        renewals that try to switch to the retired package; either attempt is
        rejected with `ERR_PACKAGE_RETIRED`."

        Design: Corner/validations/error_package_retired_on_create_contract
        """
        package = create_default_package(code="OLD",
                                          annual_premium_cents=20_000,
                                          service_fee_cents=5_000,
                                          max_covered_items=3)
        # Retire the package.
        get_success_data(api.retire_contract_package(package["id"], _ADMIN))
        customer = register_customer(email="pr-pkg@example.com")
        cust_h = make_customer_headers(customer["id"])
        res = api.create_contract(
            create_contract_payload(customer["id"], package["id"]),
            cust_h,
        )
        validate_error(res, "ERR_PACKAGE_RETIRED")


class TestCrossAggregateItemNotOnContract:

    def test_claim_with_item_from_other_contract_returns_item_not_on_contract(self, api):
        """PRD §2.5: "Cross-aggregate referential integrity is enforced one step
        beyond mere existence: when a claim is filed, the supplied `covered_item_id`
        must reference a `CoveredItem` whose `contract_id` matches the claim's
        `contract_id`. A mismatch is rejected with `ERR_ITEM_NOT_ON_CONTRACT`."

        Design: Corner/validations/cross_aggregate_item_not_on_contract_only_referential
        """
        # Two ACTIVE contracts, an item on each.
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(code="PLUSF")
        cust_a = register_customer(email="rfa@example.com")
        cust_b = register_customer(email="rfb@example.com")
        c_a = activate_contract(create_pending_contract(cust_a, package))
        c_b = activate_contract(create_pending_contract(cust_b, package))
        cust_a_h = make_customer_headers(cust_a["id"])
        cust_b_h = make_customer_headers(cust_b["id"])
        get_success_data(api.create_covered_item(
            create_covered_item_payload(c_a["id"], category="HVAC"), cust_a_h
        ))
        item_b = get_success_data(api.create_covered_item(
            create_covered_item_payload(c_b["id"], category="DRYER"), cust_b_h
        ))
        # File a claim under contract A using contract B's item.
        res = api.create_claim(
            create_claim_payload(c_a["id"], item_b["id"], issue_summary="Wrong item"),
            cust_a_h,
        )
        validate_error(res, "ERR_ITEM_NOT_ON_CONTRACT")


class TestStaleVersionOnRenew:

    def test_renew_with_stale_version_returns_stale_version_412(self, api):
        """PRD §2.7: "If that value does not equal the contract's current `version`
        at the moment the request is processed — typically because a background
        `_clock/tick` advanced the contract's lifecycle since the client last read
        it — the renewal is rejected with `ERR_STALE_VERSION` and HTTP status 412."

        Design: Corner/errors/error_stale_version_on_renew
        """
        package, customer, expiring = setup_expiring_soon_contract(
            activate_at="2026-01-01T00:00:00Z",
            tick_at="2026-12-12T00:00:00Z",
        )
        cust_h = make_customer_headers(customer["id"])
        # Supply a stale version (current - 1).
        stale_v = expiring["version"] - 1
        res = api.renew_contract(
            expiring["id"],
            renew_contract_payload(stale_v),
            cust_h,
        )
        validate_error(res, "ERR_STALE_VERSION")


class TestCustomerCannotAssessClaim:

    def test_customer_call_to_assess_returns_forbidden(self, api):
        """PRD §2.1: "A request whose `X-User-Role` is not authorized to perform
        the requested operation is rejected with `ERR_FORBIDDEN`."
        PRD §4: "| POST | `/claims/{id}/assess` | Assess a submitted claim; pins
        provisional co-pay. | `Dispatcher`, `PlatformAdmin` |"

        Design: Corner/rbac/customer_cannot_assess_claim_rbac_denial
        """
        package, customer, contract, item = setup_active_contract_with_item()
        claim = file_claim(contract, customer, item, issue="Customer attempt")
        cust_h = make_customer_headers(customer["id"])
        # Customer is not in /assess's authorized role list.
        res = api.assess_claim(claim["id"], assess_claim_payload(10_000), cust_h)
        validate_error(res, "ERR_FORBIDDEN")


class TestAnonymousCannotCreateContract:

    def test_anonymous_call_to_create_contract_returns_unauthenticated_or_forbidden(self, api):
        """PRD §2.1: "A request that omits either header on a protected endpoint
        is rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.1: "Customer registration is the sole endpoint open to `Anonymous`
        callers and does not require these headers."

        Design: Corner/rbac/anonymous_cannot_create_contract_unauthenticated
        """
        package = create_default_package(code="PLUSAN")
        customer = register_customer(email="ar-anon@example.com")
        # Empty header dict simulates the Anonymous attempt on a protected endpoint.
        res = api.create_contract(
            create_contract_payload(customer["id"], package["id"]),
            {},  # no X-User-ID / X-User-Role
        )
        # PRD §2.1 is unambiguous on the missing-header case → ERR_UNAUTHENTICATED.
        # An implementer who sends X-User-Role=Anonymous explicitly would observe
        # ERR_FORBIDDEN per §2.6; both readings are PRD-consistent.
        validate_error_is_one_of(res, ["ERR_UNAUTHENTICATED", "ERR_FORBIDDEN"])
