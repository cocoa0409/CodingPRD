"""Lead distribution engine: eligibility, the tiered lead charge, the
distribution cap, and OCC on distribute."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_customer_headers,
    create_category, create_customer, create_plan,
    create_verified_pro, create_subscription_pro, create_request,
    distribute_once, lead_for, reset_clock,
    setup_distributed_lead,
)

ADMIN = TEST_USERS["admin_headers"]


def _pay_vs_subscription_scenario(api):
    """Two eligible pros — P1 PAY_PER_LEAD (wallet 20000) and P2 SUBSCRIPTION
    (8 included credits) — and a request distributed twice so each pro holds
    exactly one lead. Identical gross 5000 (threshold 5 keeps demand normal)."""
    reset_clock(api)
    cat = create_category(api, base_lead_price_cents=5000, max_leads_per_request=2,
                          demand_high_threshold=5, min_rating_to_receive_leads=0.0)
    plan = create_plan(api, included_lead_credits=8, overage_price_cents=4000)
    cust = create_customer(api)
    p1 = create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["94016"],
                             billing_mode="PAY_PER_LEAD")
    p2 = create_subscription_pro(api, plan_id=plan["id"], category_ids=[cat["id"]],
                                 zip_codes=["94016"])
    req = create_request(cust["id"], cat["id"], api=api)
    r2 = distribute_once(req["id"], req["version"], api=api)
    distribute_once(req["id"], r2["version"], api=api)
    lead1 = lead_for(req["id"], p1["id"], api=api)
    lead2 = lead_for(req["id"], p2["id"], api=api)
    return {"p1": p1, "p2": p2, "lead1": lead1, "lead2": lead2}


def test_pay_per_lead_charge_debits_wallet_by_gross(api):
    """PRD 3.3: "The gross price in cents is the category's base_lead_price_cents
    multiplied by that multiplier, rounded half-up to a whole cent."
    PRD 3.3: "For a PAY_PER_LEAD pro, charge_cents is the gross price,
    credits_consumed is 0, and credit_balance_cents is debited by that amount (a
    pro qualifies for funding only when the wallet already covers the gross price)."

    Design: Difficulty/dual_variant_calc/lead_charge_pay_per_lead_vs_subscription_divergence
    """
    ctx = _pay_vs_subscription_scenario(api)
    assert ctx["lead1"]["charge_cents"] == 5000
    assert ctx["lead1"]["credits_consumed"] == 0
    pro = get_success_data(api.get_pro(ctx["p1"]["id"], ADMIN))
    assert pro["credit_balance_cents"] == 15000, "wallet 20000 debited by gross 5000"


def test_subscription_lead_consumes_credit_without_charge(api):
    """PRD 3.3: "For a SUBSCRIPTION pro, if remaining_lead_credits is at least
    one, charge_cents is 0, credits_consumed is 1, and one credit is decremented
    from remaining_lead_credits;"

    Design: Difficulty/dual_variant_calc/lead_charge_pay_per_lead_vs_subscription_divergence
    """
    ctx = _pay_vs_subscription_scenario(api)
    assert ctx["lead2"]["charge_cents"] == 0
    assert ctx["lead2"]["credits_consumed"] == 1
    pro = get_success_data(api.get_pro(ctx["p2"]["id"], ADMIN))
    assert pro["remaining_lead_credits"] == 7, "8 included credits, one consumed"


def test_subscription_overage_charges_flat_fee_to_wallet(api):
    """PRD 3.3: "otherwise the pro pays overage, where charge_cents becomes the
    plan's overage_price_cents, credits_consumed is 0, and the wallet is debited
    by that overage."

    Design: Corner/calculations/subscription_overage_charges_wallet_flat_fee
    """
    reset_clock(api)
    cat = create_category(api, base_lead_price_cents=5000, demand_high_threshold=5,
                          min_rating_to_receive_leads=0.0)
    plan = create_plan(api, included_lead_credits=0, overage_price_cents=4000)
    cust = create_customer(api)
    pro = create_subscription_pro(api, plan_id=plan["id"], wallet=5000,
                                  category_ids=[cat["id"]], zip_codes=["94016"])
    req = create_request(cust["id"], cat["id"], api=api)
    distribute_once(req["id"], req["version"], api=api)
    lead = lead_for(req["id"], pro["id"], api=api)
    assert lead["charge_cents"] == 4000
    assert lead["credits_consumed"] == 0
    pro_after = get_success_data(api.get_pro(pro["id"], ADMIN))
    assert pro_after["remaining_lead_credits"] == 0
    assert pro_after["credit_balance_cents"] == 1000, "wallet 5000 debited by overage 4000"


def test_distribute_with_unfundable_pro_returns_insufficient_credit(api):
    """PRD 3.3: "Additionally, at least one candidate must be able to fund the
    lead (per the charge rules below); if the qualifying pros exist but none can
    fund the charge, the distribution is rejected with ERR_INSUFFICIENT_CREDIT."

    Design: Corner/validations/distribute_insufficient_credit_returns_402
    """
    reset_clock(api)
    cat = create_category(api, base_lead_price_cents=5000, min_rating_to_receive_leads=0.0)
    cust = create_customer(api)
    create_verified_pro(api, wallet=1000, category_ids=[cat["id"]], zip_codes=["94016"])
    req = create_request(cust["id"], cat["id"], api=api)
    resp = api.distribute(req["id"], {"expected_service_request_version": req["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)


def test_distribute_with_no_zip_match_returns_no_eligible_pros(api):
    """PRD 3.3: "The candidate set for a request consists of every pro that is
    VERIFIED, that lists the request's category in its covered_category_ids, that
    lists the request's zip_code in its service_zip_codes, that is not already
    holding a lead for this request, and whose reputation clears the category floor."
    PRD 3.3: "If the candidate set is empty — because the cap has already been
    reached or because no pro satisfies the category, geography, reputation, and
    not-already-holding conditions — the distribution is rejected with
    ERR_NO_ELIGIBLE_PROS."

    Design: Corner/validations/distribute_no_matching_zip_returns_no_eligible_pros
    """
    reset_clock(api)
    cat = create_category(api, base_lead_price_cents=5000, min_rating_to_receive_leads=0.0)
    cust = create_customer(api)
    create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["99999"])
    req = create_request(cust["id"], cat["id"], api=api, zip_code="94016")
    resp = api.distribute(req["id"], {"expected_service_request_version": req["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_PROS)


def test_first_distribute_below_cap_succeeds(api):
    """PRD 3.3: "The first successful distribution moves the request from OPEN to
    DISTRIBUTED; subsequent distributions are a self-loop that keeps the request
    in DISTRIBUTED while adding one more lead each time."
    PRD 3.3: "The request's distributed_lead_count rises by one and its version
    is bumped."

    Design: Difficulty/boundary_precision_check/distribution_cap_empty_candidate_set_boundary
    """
    reset_clock(api)
    cat = create_category(api, max_leads_per_request=1, min_rating_to_receive_leads=0.0)
    cust = create_customer(api)
    create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["94016"])
    req = create_request(cust["id"], cat["id"], api=api)
    updated = validate_success(
        api.distribute(req["id"], {"expected_service_request_version": req["version"]}, ADMIN)
    )
    assert updated["status"] == "DISTRIBUTED"
    assert updated["distributed_lead_count"] == 1


def test_distribute_at_cap_returns_no_eligible_pros(api):
    """PRD 3.3: "A distribution is permitted only while the request is OPEN or
    DISTRIBUTED, only while distributed_lead_count is strictly below the
    category's max_leads_per_request, and only when at least one pro qualifies."
    PRD 3.3: "If the candidate set is empty — because the cap has already been
    reached or because no pro satisfies the category, geography, reputation, and
    not-already-holding conditions — the distribution is rejected with
    ERR_NO_ELIGIBLE_PROS."

    Design: Difficulty/boundary_precision_check/distribution_cap_empty_candidate_set_boundary
    """
    reset_clock(api)
    cat = create_category(api, max_leads_per_request=1, min_rating_to_receive_leads=0.0)
    cust = create_customer(api)
    create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["94016"])
    req = create_request(cust["id"], cat["id"], api=api)
    r2 = distribute_once(req["id"], req["version"], api=api)
    resp = api.distribute(req["id"], {"expected_service_request_version": r2["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_PROS)
    final = get_success_data(api.get_service_request(req["id"], ADMIN))
    assert final["distributed_lead_count"] == 1, "cap reached: count stays at 1"


def test_distribute_with_stale_version_returns_412(api):
    """PRD 2.8: "If that value does not equal the request's current version —
    because another distribution has already advanced it since the client last
    read the request — the call is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/distribute_stale_version_returns_412
    """
    reset_clock(api)
    cat = create_category(api, max_leads_per_request=2, min_rating_to_receive_leads=0.0)
    cust = create_customer(api)
    create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["94016"])
    create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["94016"])
    req = create_request(cust["id"], cat["id"], api=api)
    stale_version = req["version"]
    distribute_once(req["id"], stale_version, api=api)  # advances version
    resp = api.distribute(req["id"], {"expected_service_request_version": stale_version}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    final = get_success_data(api.get_service_request(req["id"], ADMIN))
    assert final["distributed_lead_count"] == 1


def test_leads_filterable_by_request_and_pro(api):
    """PRD 2.3: "Beyond limit and offset, list endpoints accept domain filters
    that narrow the collection by exact match on the named fields."
    PRD 3.3: "Each successful distribution creates one Lead recording its
    request_id, pro_id, a category_id snapshot from the request, the billing_mode
    snapshot, the computed charge_cents and credits_consumed, an initial
    contact_status of DISTRIBUTED, an initial billing_status of CHARGED, and a
    distributed_at stamped from the logical clock."

    Design: Corner/endpoints/leads_reverse_reachable_by_request_and_pro
    """
    ctx = setup_distributed_lead(api=api)
    data = get_success_data(
        api.list_leads(ADMIN, params={"request_id": ctx["request"]["id"], "pro_id": ctx["pro"]["id"]})
    )
    assert len(data) == 1
    assert data[0]["request_id"] == ctx["request"]["id"]
    assert data[0]["pro_id"] == ctx["pro"]["id"]


def test_list_requests_reports_pagination_metadata(api):
    """PRD 2.3: "The limit parameter caps the number of items returned; when
    omitted it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD 2.3: "Every list response carries limit, offset, total_count, and
    has_more in the meta object."

    Design: Corner/endpoints/list_service_requests_pagination_metadata
    """
    cat = create_category(api)
    cust = create_customer(api)
    create_request(cust["id"], cat["id"], api=api, description="r1")
    create_request(cust["id"], cat["id"], api=api, description="r2")
    resp = api.list_service_requests(ADMIN, params={"customer_id": cust["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_customer_cannot_distribute_returns_forbidden(api):
    """PRD 3.3: "A distribute call is available only to a PlatformAdmin and
    carries expected_service_request_version (Section 2.8)."
    PRD 2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/customer_cannot_distribute_returns_forbidden
    """
    cat = create_category(api)
    cust = create_customer(api)
    req = create_request(cust["id"], cat["id"], api=api)
    resp = api.distribute(req["id"], {"expected_service_request_version": req["version"]},
                          make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
