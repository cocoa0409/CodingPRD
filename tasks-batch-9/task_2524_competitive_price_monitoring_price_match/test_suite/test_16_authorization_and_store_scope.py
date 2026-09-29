"""Authentication, endpoint authorisation, store scoping, segregation of duties and the error families.

Every test in this file translates exactly one rbac-section or errors-section
design instance. The service is restarted with an empty database before each
individual test, so all preconditions are built here through PRD endpoints.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    COLLECTOR,
    COMPLIANCE,
    MANAGER,
    ApiErrorId,
    api_client,
    build_user_headers,
    confirm_match,
    decide_claim,
    get_success_data,
    make_pricing_manager_headers,
    make_store_associate_headers,
    make_store_manager_headers,
    new_change_order,
    new_claim,
    new_competitor,
    new_market,
    new_match,
    new_match_policy,
    new_product,
    new_store,
    read_claim,
    read_match,
    read_order,
    read_product,
    read_store,
    set_clock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    verify_claim,
)

CLOCK = "2026-08-01T00:00:00Z"
MISSING_ID = "00000000-0000-4000-8000-000000000000"

NO_ROLE_HEADERS = {"X-User-ID": "analyst-1", "Content-Type": "application/json"}
NO_USER_HEADERS = {"X-User-Role": "PricingAnalyst", "Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS = build_user_headers("analyst-1", "PricingWizard")


def _new_west_market():
    return new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )


def test_missing_or_unknown_role_header_is_rejected_before_anything_else():
    """An absent header or an unrecognised role name is 401, even when the rest of the request is nonsense.

    PRD: "A request that omits either header, presents either as empty, or names a role the service does not recognise is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing takes place."
    Design: Corner/rbac/corner_missing_or_unknown_role_header_returns_401_first
    """
    validate_error(api_client.list_markets(NO_ROLE_HEADERS), ApiErrorId.ERR_UNAUTHENTICATED)
    validate_error(api_client.list_markets(NO_USER_HEADERS), ApiErrorId.ERR_UNAUTHENTICATED)

    missing_row = api_client.get_product(MISSING_ID, UNKNOWN_ROLE_HEADERS)
    validate_error(missing_row, ApiErrorId.ERR_UNAUTHENTICATED)
    assert missing_row.status_code == 401, "authentication outranks path existence"

    write_attempt = api_client.create_market(
        {
            "market_code": "US-WEST",
            "name": "US West",
            "strategic_positioning": "AT_PARITY",
            "strategic_index_target_bp": 9800,
        },
        UNKNOWN_ROLE_HEADERS,
    )
    validate_error(write_attempt, ApiErrorId.ERR_UNAUTHENTICATED)

    _, meta = validate_paginated(api_client.list_markets(ADMIN))
    assert meta["total_count"] == 0, "the rejected write created nothing"


def test_each_role_is_refused_the_other_roles_exclusive_operations():
    """Unauthorised roles are refused at the authorisation step, which outranks path existence and store scoping.

    PRD: "Once the caller is authenticated, the acting role must appear in the authorised-role list for the requested endpoint as given in §4; otherwise the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."
    Design: Corner/rbac/corner_role_forbidden_across_exclusive_operations
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-RB-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )

    collector_proposing_a_match = api_client.create_match(
        {
            "product_id": product["id"],
            "competitor_id": competitor["id"],
            "match_method": "ATTRIBUTE",
            "identifier_score": 70,
            "attribute_score": 70,
            "image_score": 70,
        },
        build_user_headers("collector-5", "DataCollector"),
    )
    validate_error(collector_proposing_a_match, ApiErrorId.ERR_ROLE_FORBIDDEN)

    analyst_reviewing = api_client.review_match(link["id"], {"decision": "CONFIRM"}, ANALYST)
    validate_error(analyst_reviewing, ApiErrorId.ERR_ROLE_FORBIDDEN)

    compliance_writing_a_rule = api_client.create_repricing_rule(
        {
            "market_id": market["id"],
            "category_code": "APPLIANCE",
            "target_position_bp": 9700,
            "max_change_pct": 0.10,
            "change_frequency_limit_days": 7,
            "priority": 10,
        },
        COMPLIANCE,
    )
    validate_error(compliance_writing_a_rule, ApiErrorId.ERR_ROLE_FORBIDDEN)

    admin_authoring_an_order = api_client.create_change_order(
        {
            "product_id": product["id"],
            "origin": "MANUAL",
            "requested_price_cents": 19000,
            "effective_from": CLOCK,
            "expected_product_version": product["version"],
        },
        ADMIN,
    )
    validate_error(admin_authoring_an_order, ApiErrorId.ERR_ROLE_FORBIDDEN)

    associate_submitting_an_observation = api_client.create_observation(
        {
            "link_id": link["id"],
            "observed_price_cents": 19000,
            "collection_method": "ONLINE",
            "observed_at": "2026-07-31T18:00:00Z",
            "in_stock": True,
        },
        build_user_headers("store-unknown", "StoreAssociate"),
    )
    validate_error(associate_submitting_an_observation, ApiErrorId.ERR_ROLE_FORBIDDEN)
    assert associate_submitting_an_observation.status_code == 403, (
        "endpoint authorisation is reached before store scoping"
    )

    forbidden_over_missing = api_client.review_match(MISSING_ID, {"decision": "CONFIRM"}, ANALYST)
    validate_error(forbidden_over_missing, ApiErrorId.ERR_ROLE_FORBIDDEN)
    assert forbidden_over_missing.status_code == 403, "authorisation outranks path existence"

    assert read_match(link["id"])["status"] == "PROPOSED"
    assert read_product(product["id"])["version"] == 1
    _, meta = validate_paginated(api_client.list_repricing_rules(ADMIN))
    assert meta["total_count"] == 0


def test_store_backed_identity_is_checked_against_the_targeted_row():
    """The same claim and label-batch calls are refused from store B and accepted from store A.

    PRD: "Concretely, a `StoreAssociate` or `StoreManager` acting on a price-match claim, on a shelf-label batch, or on a store itself must present an `X-User-ID` equal to the `store_id` recorded on the targeted claim or batch (or the `id` of the targeted store); a mismatch is rejected with `ERR_STORE_SCOPE_VIOLATION` (HTTP 403)."
    Design: Corner/rbac/corner_store_scope_violation_on_another_stores_rows
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-SC-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=12999,
        unit_cost_cents=7000,
        margin_floor_pct=0.20,
    )
    store_a = new_store(
        market["id"],
        store_code="STORE-A",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    store_b = new_store(
        market["id"],
        store_code="STORE-B",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
        price_match_eligible=True,
    )
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )
    confirm_match(link["id"])
    policy = new_match_policy(
        market["id"],
        eligible_competitor_tiers=["PRIMARY"],
        daily_override_budget_cents=100000,
        max_match_discount_pct=0.30,
    )
    claim = new_claim(
        policy["id"],
        product["id"],
        competitor["id"],
        store_a["id"],
        claimed_price_cents=10400,
        claimed_observed_at="2026-07-31T18:00:00Z",
        competitor_evidence_ref="receipt-a",
    )

    cross_store_filing = api_client.create_claim(
        {
            "policy_id": policy["id"],
            "product_id": product["id"],
            "competitor_id": competitor["id"],
            "store_id": store_a["id"],
            "claimed_price_cents": 10400,
            "claimed_observed_at": "2026-07-31T18:00:00Z",
            "competitor_evidence_ref": "receipt-b",
        },
        make_store_associate_headers(store_b["id"]),
    )
    validate_error(cross_store_filing, ApiErrorId.ERR_STORE_SCOPE_VIOLATION)

    cross_store_verify = api_client.verify_claim(
        claim["id"], {}, make_store_manager_headers(store_b["id"])
    )
    validate_error(cross_store_verify, ApiErrorId.ERR_STORE_SCOPE_VIOLATION)

    cross_store_batch = api_client.create_label_batch(
        {
            "store_id": store_a["id"],
            "window_start": "2026-08-01T02:00:00Z",
            "window_end": "2026-08-01T04:00:00Z",
            "reserved_item_count": 1,
        },
        make_store_manager_headers(store_b["id"]),
    )
    validate_error(cross_store_batch, ApiErrorId.ERR_STORE_SCOPE_VIOLATION)

    own_store_verify = api_client.verify_claim(
        claim["id"], {}, make_store_manager_headers(store_a["id"])
    )
    verified = validate_success(own_store_verify)
    assert verified["status"] == "VERIFYING"
    assert read_claim(claim["id"])["status"] == "VERIFYING"

    _, meta_a = validate_paginated(
        api_client.list_claims(MANAGER, params={"store_id": store_a["id"]})
    )
    assert meta_a["total_count"] == 1
    _, meta_b = validate_paginated(
        api_client.list_claims(MANAGER, params={"store_id": store_b["id"]})
    )
    assert meta_b["total_count"] == 0

    assert read_store(store_a["id"])["label_slots_used_today"] == 0, (
        "the refused batch reserved no printer slots"
    )


def test_the_manager_who_authored_an_order_cannot_decide_it():
    """Segregation of duties bars the authoring user id, not the role: another manager may decide the same order.

    PRD: "The first governs price authority: the `X-User-ID` that decides a price change order must differ from the `authored_by_user_id` recorded on that order when it was created."
    Design: Corner/rbac/corner_segregation_of_duties_blocks_self_approval
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product_one = new_product(
        market["id"],
        sku="SKU-SOD-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    product_two = new_product(
        market["id"],
        sku="SKU-SOD-2",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    order_a = new_change_order(
        product_one["id"],
        origin="MANUAL",
        requested_price_cents=19000,
        effective_from=CLOCK,
        expected_product_version=product_one["version"],
        headers=MANAGER,
    )
    submit_order(order_a["id"], MANAGER)
    order_b = new_change_order(
        product_two["id"],
        origin="MANUAL",
        requested_price_cents=19000,
        effective_from=CLOCK,
        expected_product_version=product_two["version"],
        headers=ANALYST,
    )
    submit_order(order_b["id"], ANALYST)

    assert read_order(order_a["id"])["authored_by_user_id"] == "manager-9"
    assert read_order(order_b["id"])["authored_by_user_id"] == "analyst-1"

    self_decision = api_client.decide_change_order(
        order_a["id"], {"decision": "APPROVE"}, MANAGER
    )
    validate_error(self_decision, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert read_order(order_a["id"])["status"] == "PENDING_APPROVAL"

    other_manager = make_pricing_manager_headers("manager-7")
    decided_a = validate_success(
        api_client.decide_change_order(order_a["id"], {"decision": "APPROVE"}, other_manager)
    )
    assert decided_a["status"] == "APPROVED"
    assert decided_a["decided_by_user_id"] == "manager-7"

    decided_b = validate_success(
        api_client.decide_change_order(order_b["id"], {"decision": "APPROVE"}, MANAGER)
    )
    assert decided_b["status"] == "APPROVED"
    assert decided_b["decided_by_user_id"] == "manager-9", (
        "the same manager is only barred from deciding its own authorship"
    )

    assert read_order(order_a["id"])["signage_status"] == "NOT_REQUIRED"
    assert read_order(order_b["id"])["signage_status"] == "NOT_REQUIRED"


def test_the_store_manager_can_do_everything_the_associate_can_and_four_things_more():
    """Verification, batch scheduling and reversal are manager-only, while claim filing and honouring are shared.

    PRD: "`StoreManager` — the manager of one store. Adds `MANAGER`-tier honour authority, claim verification, claim reversal and shelf-label batch scheduling on top of everything a `StoreAssociate` may do."
    Design: Corner/rbac/corner_store_manager_is_a_strict_superset_of_store_associate
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-SUP-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=12999,
        unit_cost_cents=7000,
        margin_floor_pct=0.20,
    )
    store = new_store(
        market["id"],
        store_code="STORE-A",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
        price_match_eligible=True,
    )
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )
    confirm_match(link["id"])
    policy = new_match_policy(
        market["id"],
        eligible_competitor_tiers=["PRIMARY"],
        daily_override_budget_cents=100000,
        max_match_discount_pct=0.30,
    )
    associate = make_store_associate_headers(store["id"])
    manager = make_store_manager_headers(store["id"])

    claim = new_claim(
        policy["id"],
        product["id"],
        competitor["id"],
        store["id"],
        claimed_price_cents=10400,
        claimed_observed_at="2026-07-31T18:00:00Z",
        competitor_evidence_ref="receipt-mgr",
        headers=manager,
    )
    assert claim["required_approval_tier"] == "ASSOCIATE"

    associate_verifying = api_client.verify_claim(claim["id"], {}, associate)
    validate_error(associate_verifying, ApiErrorId.ERR_ROLE_FORBIDDEN)

    associate_scheduling_labels = api_client.create_label_batch(
        {
            "store_id": store["id"],
            "window_start": "2026-08-01T02:00:00Z",
            "window_end": "2026-08-01T04:00:00Z",
            "reserved_item_count": 1,
        },
        associate,
    )
    validate_error(associate_scheduling_labels, ApiErrorId.ERR_ROLE_FORBIDDEN)

    verify_claim(claim["id"], store["id"])
    decide_claim(claim["id"], store["id"], "VERIFIED")
    honored = validate_success(api_client.honor_claim(claim["id"], {}, associate))
    assert honored["status"] == "HONORED", "honouring an ASSOCIATE-tier claim is shared"

    associate_reversing = api_client.reverse_claim(
        claim["id"], {"reversal_reason": "shopper walked"}, associate
    )
    validate_error(associate_reversing, ApiErrorId.ERR_ROLE_FORBIDDEN)

    assert read_claim(claim["id"])["status"] == "HONORED"
    rows, meta = validate_paginated(api_client.list_claim_override_logs(claim["id"], COMPLIANCE))
    assert meta["total_count"] == 1
    assert [row["direction"] for row in rows] == ["DEBIT"], (
        "the refused reversal wrote no credit"
    )


def test_each_resource_family_reports_its_own_path_not_found_code():
    """One unknown UUID walked across the twelve read-by-id routes produces twelve distinct 404 codes.

    PRD: "The resolution errors are `ERR_MARKET_NOT_FOUND`, `ERR_COMPETITOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_RULE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and `ERR_BATCH_NOT_FOUND`, each carrying HTTP 404."
    Design: Corner/errors/corner_every_path_id_not_found_code_is_reachable
    """
    probes = [
        (api_client.get_market(MISSING_ID, ANALYST), ApiErrorId.ERR_MARKET_NOT_FOUND),
        (api_client.get_competitor(MISSING_ID, ANALYST), ApiErrorId.ERR_COMPETITOR_NOT_FOUND),
        (api_client.get_product(MISSING_ID, ANALYST), ApiErrorId.ERR_PRODUCT_NOT_FOUND),
        (api_client.get_store(MISSING_ID, ANALYST), ApiErrorId.ERR_STORE_NOT_FOUND),
        (api_client.get_match(MISSING_ID, ANALYST), ApiErrorId.ERR_MATCH_NOT_FOUND),
        (api_client.get_observation(MISSING_ID, ANALYST), ApiErrorId.ERR_OBSERVATION_NOT_FOUND),
        (api_client.get_index_report(MISSING_ID, ANALYST), ApiErrorId.ERR_REPORT_NOT_FOUND),
        (api_client.get_repricing_rule(MISSING_ID, ANALYST), ApiErrorId.ERR_RULE_NOT_FOUND),
        (api_client.get_change_order(MISSING_ID, ANALYST), ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api_client.get_match_policy(MISSING_ID, ANALYST), ApiErrorId.ERR_POLICY_NOT_FOUND),
        (api_client.get_claim(MISSING_ID, ANALYST), ApiErrorId.ERR_CLAIM_NOT_FOUND),
        (api_client.get_label_batch(MISSING_ID, ANALYST), ApiErrorId.ERR_BATCH_NOT_FOUND),
    ]
    for response, expected_error in probes:
        assert response.status_code == 404, (
            f"expected 404 for {expected_error}, got {response.status_code}"
        )
        validate_error(response, expected_error)

    seen = [response.json()["data"]["error_id"] for response, _ in probes]
    assert len(set(seen)) == 12, f"each family must report its own code, saw {sorted(set(seen))}"

    override_logs_of_missing_claim = api_client.list_claim_override_logs(MISSING_ID, COMPLIANCE)
    validate_error(override_logs_of_missing_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND)
    assert override_logs_of_missing_claim.status_code == 404, (
        "an unknown claim is a 404, not an empty ledger"
    )


def test_a_dangling_body_reference_reports_the_missing_familys_own_code():
    """A bad foreign key inside the request body is reported against the referenced family, not the endpoint's own resource.

    PRD: "Identifiers supplied in a request body are resolved after the path and in a fixed declaration order — `policy_id`, then `product_id`, then `competitor_id`, then `store_id`, then `link_id`, then `market_id`, then `supersedes_order_id` — and the first that fails to resolve determines which of `ERR_MARKET_NOT_FOUND`, `ERR_COMPETITOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_POLICY_NOT_FOUND` or `ERR_ORDER_NOT_FOUND` is returned, again with HTTP 404."
    Design: Corner/errors/corner_body_reference_not_found_uses_the_referenced_family_code
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-REF-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
        price_match_eligible=True,
    )

    unknown_product = api_client.create_match(
        {
            "product_id": MISSING_ID,
            "competitor_id": competitor["id"],
            "match_method": "ATTRIBUTE",
            "identifier_score": 70,
            "attribute_score": 70,
            "image_score": 70,
        },
        ANALYST,
    )
    validate_error(unknown_product, ApiErrorId.ERR_PRODUCT_NOT_FOUND)

    unknown_competitor = api_client.create_match(
        {
            "product_id": product["id"],
            "competitor_id": MISSING_ID,
            "match_method": "ATTRIBUTE",
            "identifier_score": 70,
            "attribute_score": 70,
            "image_score": 70,
        },
        ANALYST,
    )
    validate_error(unknown_competitor, ApiErrorId.ERR_COMPETITOR_NOT_FOUND)

    unknown_link = api_client.create_observation(
        {
            "link_id": MISSING_ID,
            "observed_price_cents": 19000,
            "collection_method": "ONLINE",
            "observed_at": "2026-07-31T18:00:00Z",
            "in_stock": True,
        },
        COLLECTOR,
    )
    validate_error(unknown_link, ApiErrorId.ERR_MATCH_NOT_FOUND)

    unknown_signage_store = api_client.create_change_order(
        {
            "product_id": product["id"],
            "origin": "MANUAL",
            "requested_price_cents": 19000,
            "effective_from": CLOCK,
            "expected_product_version": product["version"],
            "signage_store_id": MISSING_ID,
        },
        ANALYST,
    )
    validate_error(unknown_signage_store, ApiErrorId.ERR_STORE_NOT_FOUND)

    unknown_batch_store = api_client.create_label_batch(
        {
            "store_id": MISSING_ID,
            "window_start": "2026-08-01T02:00:00Z",
            "window_end": "2026-08-01T04:00:00Z",
            "reserved_item_count": 1,
        },
        MANAGER,
    )
    validate_error(unknown_batch_store, ApiErrorId.ERR_STORE_NOT_FOUND)

    for listing in (
        api_client.list_matches(ANALYST),
        api_client.list_observations(ANALYST),
        api_client.list_change_orders(MANAGER),
        api_client.list_label_batches(MANAGER),
    ):
        _, meta = validate_paginated(listing)
        assert meta["total_count"] == 0, "a rejected create leaves no row behind"

    assert read_product(product["id"])["version"] == 1, (
        "the rejected order create did not consume the concurrency token"
    )


def test_the_error_envelope_is_identical_across_the_status_classes():
    """A 404, a 409, a 412 and a 422 all carry the same two-key meta and two-key data error envelope.

    PRD: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    Design: Corner/errors/corner_error_envelope_is_uniform_across_status_classes
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-ENV-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    stale_version = product["version"]
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="ATTRIBUTE",
        identifier_score=70,
        attribute_score=70,
        image_score=70,
    )
    first_order = validate_success(
        api_client.create_change_order(
            {
                "product_id": product["id"],
                "origin": "MANUAL",
                "requested_price_cents": 19500,
                "effective_from": CLOCK,
                "effective_until": "2026-08-02T00:00:00Z",
                "expected_product_version": stale_version,
            },
            ANALYST,
        ),
        201,
    )

    not_found = api_client.get_product(MISSING_ID, ANALYST)
    validate_error(not_found, ApiErrorId.ERR_PRODUCT_NOT_FOUND)

    duplicate = api_client.create_product(
        {
            "market_id": market["id"],
            "sku": "SKU-ENV-1",
            "category_code": "APPLIANCE",
            "brand": "Nordis",
            "own_price_cents": 21000,
            "unit_cost_cents": 9000,
        },
        ADMIN,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    stale = api_client.create_change_order(
        {
            "product_id": product["id"],
            "origin": "MANUAL",
            "requested_price_cents": 19000,
            "effective_from": "2026-08-02T00:00:00Z",
            "expected_product_version": stale_version,
        },
        ANALYST,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PRODUCT_VERSION)

    weak_confirm = api_client.review_match(link["id"], {"decision": "CONFIRM"}, MANAGER)
    validate_error(weak_confirm, ApiErrorId.ERR_CONFIDENCE_BELOW_CONFIRM_THRESHOLD)

    for response, expected_status in (
        (not_found, 404),
        (duplicate, 409),
        (stale, 412),
        (weak_confirm, 422),
    ):
        assert response.status_code == expected_status
        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
            f"unexpected meta keys on {expected_status}: {sorted(body['meta'].keys())}"
        )
        assert set(body["data"].keys()) == {"error_id", "message"}, (
            f"unexpected data keys on {expected_status}: {sorted(body['data'].keys())}"
        )
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
            "message must be a non-empty string"
        )

    assert read_match(link["id"])["status"] == "PROPOSED"
    assert read_product(product["id"])["version"] == 2, (
        "the stale-version rejection did not bump the product again"
    )
    orders, meta = validate_paginated(
        api_client.list_change_orders(MANAGER, params={"product_id": product["id"]})
    )
    assert meta["total_count"] == 1
    assert [order["id"] for order in orders] == [first_order["id"]]
