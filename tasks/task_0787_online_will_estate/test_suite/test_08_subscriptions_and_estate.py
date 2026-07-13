"""Subscription creation surface, FK-reverse listings, OCC on plan change, derived
estate reconciliation, and immediate renewal-settlement visibility.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_plan, set_clock, register_member, create_pending_subscription, activate,
    make_member_headers, make_active_subscription, add_beneficiary, add_asset,
    create_questionnaire_payload, partial_answers, NON_EXISTENT_UUID, ADMIN,
)


# ─── Corner: entities / subscription_creation_returns_fields ─────────────
def test_create_subscription_returns_pending_with_computed_price(api):
    """PRD §3.2: "A new subscription is created in `PENDING_PAYMENT` status." "At
    creation the subscription's signup price is computed and stored in `price_cents`".

    Design: Corner/entities/subscription_creation_returns_fields
    """
    setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=["WILL"])
    member = register_member(email="create@example.com")
    hdr = make_member_headers(member["id"])
    sub = validate_success(api.create_subscription(
        {"member_id": member["id"], "plan_tier": "PLUS", "bundle_type": "INDIVIDUAL"}, hdr), 201)
    assert sub["status"] == "PENDING_PAYMENT"
    assert sub["price_cents"] == 20000


# ─── Corner: entities / bundle_type_default_individual ───────────────────
def test_bundle_type_defaults_to_individual(api):
    """PRD §3.2: "The member may also choose a `bundle_type` of `INDIVIDUAL` (the
    default, covering the member alone) or `COUPLE` (bundling a spouse)".

    Design: Corner/entities/bundle_type_default_individual
    """
    setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=["WILL"])
    member = register_member(email="default@example.com")
    hdr = make_member_headers(member["id"])
    sub = validate_success(api.create_subscription(
        {"member_id": member["id"], "plan_tier": "PLUS"}, hdr), 201)
    assert sub["bundle_type"] == "INDIVIDUAL"
    assert sub["price_cents"] == 20000  # individual multiplier 1.0


# ─── Corner: entities / get_subscription_not_found_returns_404 ───────────
def test_get_unknown_subscription_returns_not_found(api):
    """PRD §2.9: "the system validates the existence of each path identifier from left
    to right and rejects the request at the first identifier that does not resolve,
    returning the not-found error appropriate to that resource type
    (`ERR_MEMBER_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, ...".

    Design: Corner/entities/get_subscription_not_found_returns_404
    """
    member = register_member(email="ghost@example.com")
    hdr = make_member_headers(member["id"])
    res = api.get_subscription(NON_EXISTENT_UUID, hdr)
    validate_error(res, "ERR_SUBSCRIPTION_NOT_FOUND")


# ─── Corner: entities / create_subscription_missing_member_id_returns_invalid_request ─
def test_create_subscription_missing_member_id_returns_validation(api):
    """PRD §2.10: "Field-shape problems — a missing required field, a malformed value,
    or an invalid enum member — surface as `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_subscription_missing_member_id_returns_invalid_request
    """
    setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=["WILL"])
    member = register_member(email="missing@example.com")
    hdr = make_member_headers(member["id"])
    res = api.create_subscription({"plan_tier": "PLUS", "bundle_type": "INDIVIDUAL"}, hdr)
    validate_error(res, "ERR_VALIDATION")


# ─── Corner: entities / questionnaire_completeness_computed_partial ──────
def test_questionnaire_completeness_partial(api):
    """PRD §3.5: "`answered_field_count` is the count of distinct required keys present
    in the merged answers, capped at `required_field_count`, and `completeness_pct` is
    that answered count divided by the required count times 100, rounded half-up to two
    decimals. While the recomputed completeness is below 100, the intake remains
    `IN_PROGRESS`."

    Design: Corner/entities/questionnaire_completeness_computed_partial
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    q = get_success_data(api.create_questionnaire(
        create_questionnaire_payload(sub["id"], document_type="WILL", state_code="CA"), hdr))
    updated = validate_success(
        api.submit_answers(q["id"], {"answers": partial_answers(3)}, hdr), 200)
    assert updated["completeness_pct"] == 60.00  # 3 of 5 required
    assert updated["status"] == "IN_PROGRESS"


# ─── Corner: endpoints / list_member_subscriptions_reverse_reachability ──
def test_list_member_subscriptions(api):
    """PRD §3.1: "A registered member and a `PlatformAdmin` may fetch a member record,
    and both may list that member's subscriptions."

    Design: Corner/endpoints/list_member_subscriptions_reverse_reachability
    """
    setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=["WILL"])
    member = register_member(email="listsubs@example.com")
    hdr = make_member_headers(member["id"])
    sub = create_pending_subscription(member["id"], plan_tier="PLUS")
    data, _meta = validate_paginated(api.list_member_subscriptions(member["id"], hdr))
    assert len(data) == 1
    assert data[0]["id"] == sub["id"]


# ─── Corner: endpoints / list_beneficiary_assets_reverse_reachability ────
def test_list_beneficiary_assets(api):
    """PRD §2.9: "Many resources are reachable through sub-resource list endpoints that
    reverse a foreign key — for example, listing a subscription's documents, a
    document's share grants, or a beneficiary's earmarked assets."

    Design: Corner/endpoints/list_beneficiary_assets_reverse_reachability
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    ben = add_beneficiary(sub["id"], hdr, full_name="Ben", allocation_pct=100)
    asset = add_asset(sub["id"], hdr, asset_type="BANK", description="Acct",
                      estimated_value_cents=50000, funding_status="UNFUNDED",
                      assigned_beneficiary_id=ben["id"])
    data, _meta = validate_paginated(api.list_beneficiary_assets(ben["id"], hdr))
    assert len(data) == 1
    assert data[0]["id"] == asset["id"]


# ─── Corner: cross_cutting_layers / change_plan_stale_version_returns_conflict ─
def test_change_plan_with_stale_version_rejected(api):
    """PRD §2.7: "If `expected_subscription_version` does not equal the subscription's
    current `version` — that is, if any other writer has advanced the subscription since
    the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP
    412), and no plan change or price recomputation occurs."

    Design: Corner/cross_cutting_layers/change_plan_stale_version_returns_conflict
    """
    setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=["WILL"])
    setup_plan(plan_tier="PREMIER", base_price_cents=35000,
               included_document_types=["WILL", "TRUST", "POA", "HEALTHCARE_DIRECTIVE"],
               max_documents=20, allows_trust=True)
    set_clock("2026-06-01T00:00:00Z")
    member = register_member(email="occ@example.com")
    hdr = make_member_headers(member["id"])
    sub = create_pending_subscription(member["id"], plan_tier="PLUS")
    sub = activate(sub["id"])
    stale_version = sub["version"]
    validate_success(api.change_plan(
        sub["id"], {"new_plan_tier": "PREMIER", "expected_subscription_version": stale_version}, hdr), 200)
    res = api.change_plan(
        sub["id"], {"new_plan_tier": "PLUS", "expected_subscription_version": stale_version}, hdr)
    validate_error(res, "ERR_STALE_VERSION")
    after = validate_success(api.get_subscription(sub["id"], hdr), 200)
    assert after["plan_tier"] == "PREMIER"  # the stale second change did not apply


# ─── Corner: cross_cutting_layers / derived_gross_estate_reconciles_after_asset_add ─
def test_gross_estate_reconciles_after_asset_add(api):
    """PRD §3.9: "It reports `gross_estate_value_cents`, the sum of `estimated_value_cents`
    across all of the subscription's assets, and `net_probate_estate_cents`, the sum of
    `estimated_value_cents` over only those assets that are not `FUNDED` and have no
    `assigned_beneficiary_id`".

    Design: Corner/cross_cutting_layers/derived_gross_estate_reconciles_after_asset_add
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    add_asset(sub["id"], hdr, asset_type="VEHICLE", description="Car",
              estimated_value_cents=40000, funding_status="UNFUNDED")
    summary = validate_success(api.get_estate_summary(sub["id"], hdr), 200)
    assert summary["gross_estate_value_cents"] == 40000
    assert summary["net_probate_estate_cents"] == 40000


# ─── Corner: consistency_model / renewal_settlement_immediate_visibility ─
def test_renewal_settlement_immediately_visible(api):
    """PRD §3.3: "On a `SUCCEEDED` outcome the renewal settles: `renewal_count` is
    incremented by one, and the amount actually charged — the final charge — is the
    provisional quote reduced by the loyalty discount".

    Design: Corner/consistency_model/renewal_settlement_immediate_visibility
    """
    member, sub, hdr = make_active_subscription(
        plan_tier="PLUS", base_price_cents=20000, clock="2026-06-01T00:00:00Z")
    set_clock("2027-05-15T00:00:00Z")
    get_success_data(api.renew_subscription(sub["id"], hdr))
    settled = validate_success(
        api.simulate_payment({"subscription_id": sub["id"], "outcome": "SUCCEEDED"}, ADMIN), 200)
    assert settled["renewal_count"] == 1
    assert settled["status"] == "ACTIVE"
