"""Do-not-sell request processing and vendor propagation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_propagation_counter_invariants,
    create_property, create_approved_vendor, create_visitor,
    create_do_not_sell_request_payload,
    make_visitor_headers,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
VM = TEST_USERS["vendor_manager_headers"]
ANY = TEST_USERS["any_headers"]


def _dns_site(api):
    prop = create_property(name="DNS Site", sale_share_designation="SELLS_AND_SHARES")
    vend = create_approved_vendor(
        prop["id"], legal_name="SellCo", declared_purposes=["SALE_SHARE"],
        tracker_signatures=["sell-1.com"],
    )
    vis = create_visitor(prop["id"], external_ref="dns@x.com", jurisdiction_code="US-CA")
    req = get_success_data(
        api.create_do_not_sell_request(
            vis["id"], create_do_not_sell_request_payload(), make_visitor_headers(vis["id"])
        )
    )
    return prop, vend, vis, req


def test_dns_propagate_requires_verified(api):
    """PRD section 3.6: "Propagation is launched by a `PrivacyAdmin` and
    requires `VERIFIED` with propagation in `NOT_STARTED` or `PARTIAL_FAILURE`
    (anything else is `ERR_DNS_INVALID_STATE`)."

    Design: Difficulty/non_linear_state_machine/dns_parallel_dimensions_with_retry_cycle
    """
    prop, vend, vis, req = _dns_site(api)
    assert req["verification_status"] == "UNVERIFIED"
    assert req["propagation_status"] == "NOT_STARTED"
    res = api.propagate_do_not_sell_request(req["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_DNS_INVALID_STATE)


def test_dns_retry_cycle_and_dimension_independence(api):
    """PRD section 3.6: "a failed delivery is retried via `FAILED → PENDING`,
    which increments `attempts` and re-stamps `last_attempt_at`."
    PRD section 3.6: "While any child is `PENDING` the request remains
    `PROPAGATING`; when none is pending it settles to `ALL_CONFIRMED` if there
    are no failures and `PARTIAL_FAILURE` otherwise."

    Design: Difficulty/non_linear_state_machine/dns_parallel_dimensions_with_retry_cycle
    """
    prop, vend, vis, req = _dns_site(api)
    get_success_data(
        api.update_do_not_sell_request(req["id"], {"verification_status": "VERIFIED"}, ADMIN)
    )
    get_success_data(api.propagate_do_not_sell_request(req["id"], ADMIN))
    props, _m = validate_paginated(api.list_request_propagations(req["id"], ANY))
    assert len(props) == 1
    g1 = props[0]["id"]

    failed = validate_success(api.update_vendor_propagation(g1, {"status": "FAILED"}, VM), 200)
    assert failed["status"] == "FAILED"
    req_mid = get_success_data(api.get_do_not_sell_request(req["id"], ANY))
    assert req_mid["propagation_status"] == "PARTIAL_FAILURE", "pending 0, failed 1"

    retried = validate_success(api.update_vendor_propagation(g1, {"status": "PENDING"}, VM), 200)
    assert retried["attempts"] == 2, "FAILED -> PENDING retry increments attempts"
    req_back = get_success_data(api.get_do_not_sell_request(req["id"], ANY))
    assert req_back["propagation_status"] == "PROPAGATING", "FAILED -> PENDING cycle"

    validate_success(api.update_vendor_propagation(g1, {"status": "CONFIRMED"}, VM), 200)
    req_done = get_success_data(api.get_do_not_sell_request(req["id"], ANY))
    assert req_done["propagation_status"] == "ALL_CONFIRMED"
    assert req_done["verification_status"] == "VERIFIED", "dimensions are independent"


def test_dns_on_no_sale_property_rejected(api):
    """PRD section 3.1: "a property designated `NO_SALE_NO_SHARE` categorically
    rejects do-not-sell requests with `ERR_DNS_NOT_APPLICABLE`, because there is
    nothing to opt out of."

    Design: Corner/validations/dns_on_no_sale_property_rejected
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    vis = create_visitor(prop["id"], external_ref="n@x.com", jurisdiction_code="US-CA")
    res = api.create_do_not_sell_request(
        vis["id"], create_do_not_sell_request_payload(), make_visitor_headers(vis["id"])
    )
    validate_error(res, ApiErrorId.ERR_DNS_NOT_APPLICABLE)


def test_dns_verify_twice_rejected(api):
    """PRD section 3.6: "The verification dimension (`verification_status`) is
    settled by a `PrivacyAdmin`: `UNVERIFIED → VERIFIED` or `UNVERIFIED →
    REJECTED`, and any attempt to re-settle a settled request fails with
    `ERR_DNS_INVALID_STATE`."

    Design: Corner/state_machines/dns_verify_twice_rejected
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    vis = create_visitor(prop["id"], external_ref="v@x.com", jurisdiction_code="US-CA")
    req = get_success_data(
        api.create_do_not_sell_request(
            vis["id"], create_do_not_sell_request_payload(), make_visitor_headers(vis["id"])
        )
    )
    get_success_data(
        api.update_do_not_sell_request(req["id"], {"verification_status": "VERIFIED"}, ADMIN)
    )
    res = api.update_do_not_sell_request(req["id"], {"verification_status": "VERIFIED"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_DNS_INVALID_STATE)


def test_propagation_confirm_twice_rejected(api):
    """PRD section 3.6: "Settling a `CONFIRMED` propagation again, or retrying a
    `PENDING` one, is `ERR_PROPAGATION_INVALID_STATE`."

    Design: Corner/state_machines/propagation_confirm_twice_rejected
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    create_approved_vendor(prop["id"], legal_name="V", declared_purposes=["SALE_SHARE"],
                           tracker_signatures=["v.com"])
    vis = create_visitor(prop["id"], external_ref="p@x.com", jurisdiction_code="US-CA")
    req = get_success_data(
        api.create_do_not_sell_request(
            vis["id"], create_do_not_sell_request_payload(), make_visitor_headers(vis["id"])
        )
    )
    get_success_data(
        api.update_do_not_sell_request(req["id"], {"verification_status": "VERIFIED"}, ADMIN)
    )
    get_success_data(api.propagate_do_not_sell_request(req["id"], ADMIN))
    props, _m = validate_paginated(api.list_request_propagations(req["id"], ANY))
    g1 = props[0]["id"]
    get_success_data(api.update_vendor_propagation(g1, {"status": "CONFIRMED"}, VM))
    res = api.update_vendor_propagation(g1, {"status": "CONFIRMED"}, VM)
    validate_error(res, ApiErrorId.ERR_PROPAGATION_INVALID_STATE)


def test_propagate_empty_vendor_pool_all_confirmed(api):
    """PRD section 3.6: "If no vendor is in scope, the request jumps straight to
    `ALL_CONFIRMED` with `total_propagations` zero."

    Design: Corner/calculations/propagate_empty_vendor_pool_all_confirmed
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    # The only APPROVED vendor is out of the default SALE_SHARE scope.
    create_approved_vendor(prop["id"], legal_name="AdsOnly", declared_purposes=["ADVERTISING"],
                           tracker_signatures=["ao.com"])
    vis = create_visitor(prop["id"], external_ref="e@x.com", jurisdiction_code="US-CA")
    req = get_success_data(
        api.create_do_not_sell_request(
            vis["id"], create_do_not_sell_request_payload(), make_visitor_headers(vis["id"])
        )
    )
    get_success_data(
        api.update_do_not_sell_request(req["id"], {"verification_status": "VERIFIED"}, ADMIN)
    )
    after = validate_success(api.propagate_do_not_sell_request(req["id"], ADMIN), 200)
    assert after["propagation_status"] == "ALL_CONFIRMED"
    assert after["total_propagations"] == 0, "empty in-scope pool"


def test_propagation_partition_counter_conservation(api):
    """PRD section 3.6: "The request maintains four counters —
    `total_propagations`, `pending_count`, `confirmed_count`, `failed_count` —
    and an iron invariant: the three status counters always sum to
    `total_propagations`, which always equals the number of propagation
    children."

    Design: Difficulty/compensating_invariant/propagation_partition_counter_conservation
    """
    prop = create_property(name="Partition Site", sale_share_designation="SELLS_AND_SHARES")
    for name in ("W1", "W2", "W3"):
        create_approved_vendor(
            prop["id"], legal_name=name, declared_purposes=["SALE_SHARE"],
            tracker_signatures=[f"{name.lower()}.com"],
        )
    vis = create_visitor(prop["id"], external_ref="pp@x.com", jurisdiction_code="US-CA")
    req = get_success_data(
        api.create_do_not_sell_request(
            vis["id"], create_do_not_sell_request_payload(), make_visitor_headers(vis["id"])
        )
    )
    get_success_data(
        api.update_do_not_sell_request(req["id"], {"verification_status": "VERIFIED"}, ADMIN)
    )
    get_success_data(api.propagate_do_not_sell_request(req["id"], ADMIN))
    props, _m = validate_paginated(api.list_request_propagations(req["id"], ANY))
    assert len(props) == 3, "one PENDING propagation per in-scope APPROVED vendor"
    g1, g2, g3 = props[0]["id"], props[1]["id"], props[2]["id"]

    get_success_data(api.update_vendor_propagation(g1, {"status": "CONFIRMED"}, VM))
    get_success_data(api.update_vendor_propagation(g2, {"status": "FAILED"}, VM))
    get_success_data(api.update_vendor_propagation(g2, {"status": "PENDING"}, VM))
    get_success_data(api.update_vendor_propagation(g2, {"status": "CONFIRMED"}, VM))
    get_success_data(api.update_vendor_propagation(g3, {"status": "CONFIRMED"}, VM))

    req_after = get_success_data(api.get_do_not_sell_request(req["id"], ANY))
    assert req_after["total_propagations"] == 3
    assert req_after["pending_count"] == 0
    assert req_after["confirmed_count"] == 3
    assert req_after["failed_count"] == 0
    assert req_after["propagation_status"] == "ALL_CONFIRMED"
    assert_propagation_counter_invariants(req_after)

    g2_after = get_success_data(api.get_vendor_propagation(g2, ANY))
    assert g2_after["attempts"] == 2, "retry incremented attempts"


def test_propagation_partition_holds_at_every_step(api):
    """PRD section 3.6: "an iron invariant: the three status counters always sum
    to `total_propagations`, which always equals the number of propagation
    children. While any child is `PENDING` the request remains `PROPAGATING`;
    when none is pending it settles to `ALL_CONFIRMED` if there are no failures
    and `PARTIAL_FAILURE` otherwise."

    Design: Difficulty/compensating_invariant/propagation_partition_counter_conservation
    """
    prop = create_property(name="Partition Site", sale_share_designation="SELLS_AND_SHARES")
    for name in ("W1", "W2", "W3"):
        create_approved_vendor(
            prop["id"], legal_name=name, declared_purposes=["SALE_SHARE"],
            tracker_signatures=[f"{name.lower()}.com"],
        )
    vis = create_visitor(prop["id"], external_ref="pp@x.com", jurisdiction_code="US-CA")
    req = get_success_data(
        api.create_do_not_sell_request(
            vis["id"], create_do_not_sell_request_payload(), make_visitor_headers(vis["id"])
        )
    )
    get_success_data(
        api.update_do_not_sell_request(req["id"], {"verification_status": "VERIFIED"}, ADMIN)
    )
    get_success_data(api.propagate_do_not_sell_request(req["id"], ADMIN))
    props, _m = validate_paginated(api.list_request_propagations(req["id"], ANY))
    g1, g2, g3 = props[0]["id"], props[1]["id"], props[2]["id"]

    def check(expected_pending, expected_confirmed, expected_failed):
        cur = get_success_data(api.get_do_not_sell_request(req["id"], ANY))
        assert cur["pending_count"] == expected_pending
        assert cur["confirmed_count"] == expected_confirmed
        assert cur["failed_count"] == expected_failed
        assert_propagation_counter_invariants(cur)
        return cur

    check(3, 0, 0)
    get_success_data(api.update_vendor_propagation(g1, {"status": "CONFIRMED"}, VM))
    check(2, 1, 0)
    get_success_data(api.update_vendor_propagation(g2, {"status": "FAILED"}, VM))
    mid = check(1, 1, 1)
    assert mid["propagation_status"] == "PROPAGATING", "still PENDING children"
    get_success_data(api.update_vendor_propagation(g2, {"status": "PENDING"}, VM))
    check(2, 1, 0)
    get_success_data(api.update_vendor_propagation(g2, {"status": "CONFIRMED"}, VM))
    check(1, 2, 0)
    get_success_data(api.update_vendor_propagation(g3, {"status": "CONFIRMED"}, VM))
    done = check(0, 3, 0)
    assert done["propagation_status"] == "ALL_CONFIRMED"


def test_dns_request_get_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (..., `ERR_DNS_REQUEST_NOT_FOUND`, ...)."

    Design: Corner/errors/dns_request_get_not_found_returns_404
    """
    res = api.get_do_not_sell_request(NON_EXISTENT_UUID, ANY)
    validate_error(res, ApiErrorId.ERR_DNS_REQUEST_NOT_FOUND)


def test_propagation_get_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (..., `ERR_PROPAGATION_NOT_FOUND`, ...)."

    Design: Corner/errors/propagation_get_not_found_returns_404
    """
    res = api.get_vendor_propagation(NON_EXISTENT_UUID, ANY)
    validate_error(res, ApiErrorId.ERR_PROPAGATION_NOT_FOUND)
