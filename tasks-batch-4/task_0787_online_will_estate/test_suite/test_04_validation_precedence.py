"""Validation-precedence conflicts: which error wins when two checks could both
reject the same request, per the fixed global priority order in PRD §2.10.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_plan, set_clock, register_member, create_pending_subscription, activate,
    make_completed_questionnaire, make_member_headers, add_asset,
    make_active_subscription, NON_EXISTENT_UUID, NOTARY, ADMIN,
)


def _suspended_sub_at_quota():
    """BASIC plan (max_documents=1); subscription reaches 1 document (at quota) then
    is driven to SUSPENDED via a failed renewal. A second COMPLETED WILL questionnaire
    is ready. Returns (sub_id, hdr, q2_id)."""
    setup_plan(plan_tier="BASIC", base_price_cents=10000,
               included_document_types=["WILL"], max_documents=1)
    set_clock("2026-06-01T00:00:00Z")
    member = register_member(email="precedence@example.com")
    hdr = make_member_headers(member["id"])
    sub = create_pending_subscription(member["id"], plan_tier="BASIC")
    sub = activate(sub["id"])
    # First document — fills the quota (max_documents=1).
    q1 = make_completed_questionnaire(sub["id"], hdr, "WILL", "CA")
    get_success_data(api_client.create_document({"questionnaire_id": q1["id"]}, hdr))
    # Drive to SUSPENDED via a failed renewal settlement.
    set_clock("2027-05-15T00:00:00Z")
    get_success_data(api_client.renew_subscription(sub["id"], hdr))
    get_success_data(api_client.simulate_payment(
        {"subscription_id": sub["id"], "outcome": "FAILED"}, ADMIN))
    q2 = make_completed_questionnaire(sub["id"], hdr, "WILL", "CA")
    return sub["id"], hdr, q2["id"]


# ─── Difficulty: priority_pair_validation_conflict / generate_state_outranks_quota ─
def test_generate_state_check_outranks_quota(api):
    """PRD §2.10: "The order is: ... (6) that document generation and execution act on
    an `ACTIVE` subscription (`ERR_SUBSCRIPTION_NOT_ACTIVE`); (7) that the target is not
    already in a terminal state ...; (8) then the request-body referential checks; and
    finally the remaining domain-specific business, temporal, fiscal, and concurrency
    rules described alongside their workflows in §3."

    Design: Difficulty/priority_pair_validation_conflict/generate_state_outranks_quota
    """
    sub_id, hdr, q2_id = _suspended_sub_at_quota()
    res = api.create_document({"questionnaire_id": q2_id}, hdr)
    validate_error(res, "ERR_SUBSCRIPTION_NOT_ACTIVE")


def test_generate_state_outranks_quota_no_document_created(api):
    """PRD §3.6: "The owning subscription must be `ACTIVE`, or the request is rejected
    with `ERR_SUBSCRIPTION_NOT_ACTIVE`." "Finally, the number of non-`REVOKED` documents
    already on the subscription must be strictly less than the plan's `max_documents`
    before generation proceeds, or the request is rejected with
    `ERR_DOCUMENT_QUOTA_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/generate_state_outranks_quota
    """
    sub_id, hdr, q2_id = _suspended_sub_at_quota()
    api.create_document({"questionnaire_id": q2_id}, hdr)
    docs, _meta = validate_paginated(api.list_questionnaire_documents(q2_id, hdr))
    assert len(docs) == 0


# ─── Difficulty: priority_pair_validation_conflict / assign_referential_outranks_funded_constraint ─
def _funded_asset_no_matching_beneficiary():
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    asset = add_asset(sub["id"], hdr, asset_type="REAL_ESTATE", description="Trust House",
                      estimated_value_cents=50000, funding_status="FUNDED")
    return sub, hdr, asset


def test_assign_referential_check_outranks_funded_constraint(api):
    """PRD §2.10: "(8) then the request-body referential checks; and finally the
    remaining domain-specific business, temporal, fiscal, and concurrency rules
    described alongside their workflows in §3." PRD §3.9: assign-beneficiary "takes a
    `beneficiary_id` that must reference an existing `Beneficiary` of the same
    subscription (otherwise `ERR_BENEFICIARY_NOT_FOUND`)."

    Design: Difficulty/priority_pair_validation_conflict/assign_referential_outranks_funded_constraint
    """
    sub, hdr, asset = _funded_asset_no_matching_beneficiary()
    res = api.assign_beneficiary(asset["id"], {"beneficiary_id": NON_EXISTENT_UUID}, hdr)
    validate_error(res, "ERR_BENEFICIARY_NOT_FOUND")


def test_assign_referential_outranks_funded_asset_unchanged(api):
    """PRD §3.9: "An asset that is already `FUNDED` cannot carry a probate earmark:
    assigning a beneficiary to a funded asset is rejected with
    `ERR_ASSET_ALREADY_FUNDED`." (The referential check fires first, so no earmark is
    set.)

    Design: Difficulty/priority_pair_validation_conflict/assign_referential_outranks_funded_constraint
    """
    sub, hdr, asset = _funded_asset_no_matching_beneficiary()
    api.assign_beneficiary(asset["id"], {"beneficiary_id": NON_EXISTENT_UUID}, hdr)
    assets, _meta = validate_paginated(api.list_subscription_assets(sub["id"], hdr))
    after = [a for a in assets if a["id"] == asset["id"]][0]
    assert after["assigned_beneficiary_id"] is None
