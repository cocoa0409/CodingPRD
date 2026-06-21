"""Certification campaigns: launch enrollment, the projected/realized revocation
pair, divide-then-round completion percentage, the empty-campaign boundary, and
the campaign-state gate on item decisions.

Derived from PRD §3.7 (Certification Campaigns and Their Items) and §3.8
(Campaign Posture, Completion, and Revocation Impact).
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    create_campaign_payload,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

CAMPAIGN = TEST_USERS["campaign_admin_headers"]
CERTIFIER = TEST_USERS["certifier_headers"]
MANAGER = TEST_USERS["access_manager_headers"]


def test_campaign_launch_enrolls_active_grants_and_bubbles_review(api):
    """PRD §3.7: "the system enrolls every ACTIVE grant of an entitlement bundled
    by the scope role: each such grant moves its review dimension NOT_DUE ->
    UNDER_REVIEW, and a certification item is created for it in PENDING decision
    status. The campaign's item_count is set to the number of items created".

    Launching a campaign over one ACTIVE in-scope grant sets item_count==1 and the
    grant's review_status to UNDER_REVIEW.

    Design: Corner/state_machines/campaign_launch_enrolls_active_grants_bubble
    """
    campaign, role, ent, grants = fixtures.setup_campaign_over_n_identical_grants(1)
    grant = grants[0]
    assert campaign["item_count"] == 1, campaign["item_count"]
    got = validate_success(api.get_grant(grant["id"], CAMPAIGN), 200)
    assert got["review_status"] == "UNDER_REVIEW", got["review_status"]


def test_projected_and_realized_revocation_counts_diverge(api):
    """PRD §3.8: "The projected_revocation_count is a what-if read available while
    the campaign is ACTIVE: it is the count of items whose decision_status is still
    PENDING or UNDER_REVIEW".
    PRD §3.8: "The realized_revocation_count is the after-the-fact figure available
    once the campaign is CLOSED: it is the count of items whose decision_status is
    REVOKED, which equals the items auto-revoked at close plus any explicitly
    revoked during the campaign."

    Two in-scope grants -> 2 items. One item certified mid-flight; the other left
    PENDING. While ACTIVE projected==1; after close realized==1.

    Design: Difficulty/dual_variant_calc/campaign_projected_vs_realized_revocation_diverge
    """
    campaign, role, ent, grants = fixtures.setup_campaign_over_n_identical_grants(2)
    item1 = fixtures.item_for_grant(grants[0]["id"])
    validate_success(api.certify_item(item1["id"], CERTIFIER), 200)

    before = validate_success(api.get_campaign(campaign["id"], CAMPAIGN), 200)
    assert before["projected_revocation_count"] == 1, before["projected_revocation_count"]

    closed = validate_success(api.close_campaign(campaign["id"], CAMPAIGN), 200)
    assert closed["realized_revocation_count"] == 1, closed["realized_revocation_count"]
    assert closed["completion_pct"] == 100.00, closed["completion_pct"]


def test_realized_revocation_counts_close_auto_revokes(api):
    """PRD §3.8: "The realized_revocation_count ... is the count of items whose
    decision_status is REVOKED, which equals the items auto-revoked at close plus
    any explicitly revoked during the campaign."
    PRD §3.7: "every certification item still in PENDING or UNDER_REVIEW at close is
    auto-decided to REVOKED".

    Realized side of the projected/realized pair: 3 in-scope grants, none decided
    before close. While ACTIVE projected==3; closing auto-revokes all three, so
    realized==3 and completion_pct==100.00.

    Design: Difficulty/dual_variant_calc/campaign_projected_vs_realized_revocation_diverge
    """
    campaign, role, ent, grants = fixtures.setup_campaign_over_n_identical_grants(3)
    before = validate_success(api.get_campaign(campaign["id"], CAMPAIGN), 200)
    assert before["projected_revocation_count"] == 3, before["projected_revocation_count"]

    closed = validate_success(api.close_campaign(campaign["id"], CAMPAIGN), 200)
    assert closed["realized_revocation_count"] == 3, closed["realized_revocation_count"]
    assert closed["completion_pct"] == 100.00, closed["completion_pct"]


def test_campaign_completion_pct_divide_then_round(api):
    """PRD §3.8: "the percentage is computed by dividing the decided count by the
    total in full precision, multiplying that ratio by 100, and rounding the single
    resulting figure half-up to two decimal places. The division is performed
    before the rounding".

    7 items, 5 certified: (5/7)*100 rounded half-up once = 71.43 (round-per-item
    would yield 71.45).

    Design: Difficulty/combinatorial_formula/campaign_completion_divide_then_round
    """
    campaign, role, ent, grants = fixtures.setup_campaign_over_n_identical_grants(7)
    assert campaign["item_count"] == 7, campaign["item_count"]
    for g in grants[:5]:
        item = fixtures.item_for_grant(g["id"])
        validate_success(api.certify_item(item["id"], CERTIFIER), 200)

    got = validate_success(api.get_campaign(campaign["id"], CAMPAIGN), 200)
    assert got["completion_pct"] == 71.43, got["completion_pct"]


def test_campaign_completion_pct_two_thirds_divide_then_round(api):
    """PRD §3.8: "the percentage is computed by dividing the decided count by the
    total in full precision, multiplying that ratio by 100, and rounding the single
    resulting figure half-up to two decimal places ... never by rounding each
    item's contribution separately."

    A second distinguishing ratio: 3 items, 2 certified. Divide-then-round gives
    round((2/3)*100, 2) == 66.67, whereas round-per-item (2*round(100/3,2)=66.66)
    would differ. The PRD pins 66.67.

    Design: Difficulty/combinatorial_formula/campaign_completion_divide_then_round
    """
    campaign, role, ent, grants = fixtures.setup_campaign_over_n_identical_grants(3)
    assert campaign["item_count"] == 3, campaign["item_count"]
    for g in grants[:2]:
        item = fixtures.item_for_grant(g["id"])
        validate_success(api.certify_item(item["id"], CERTIFIER), 200)

    got = validate_success(api.get_campaign(campaign["id"], CAMPAIGN), 200)
    assert got["completion_pct"] == 66.67, got["completion_pct"]


def test_empty_campaign_closes_cleanly_at_100pct(api):
    """PRD §3.8: "If the total is zero, the completion percentage is 100.00, since
    an empty campaign is trivially complete."
    PRD §3.7: "every certification item still in PENDING or UNDER_REVIEW at close
    is auto-decided to REVOKED ... realized_revocation_count is set to the number
    of items auto-revoked at close plus the number of items that were explicitly
    revoked earlier".

    A campaign scoped to a role nobody currently holds launches with item_count==0
    and closes cleanly: completion_pct 100.00, realized_revocation_count 0.

    Design: Difficulty/boundary_precision_check/campaign_close_with_zero_items_empty_set
    """
    ent = fixtures.create_entitlement(risk_weight=10)
    role = fixtures.create_role([ent["id"]])
    campaign = fixtures.setup_launched_campaign(role["id"])
    assert campaign["item_count"] == 0, campaign["item_count"]

    closed = validate_success(api.close_campaign(campaign["id"], CAMPAIGN), 200)
    assert closed["completion_pct"] == 100.00, closed["completion_pct"]
    assert closed["realized_revocation_count"] == 0, closed["realized_revocation_count"]


def test_empty_campaign_posture_complete_at_launch(api):
    """PRD §3.8: "The posture is OPEN while the campaign is in DRAFT; it is
    COMPLETE when every item's decision_status is either CERTIFIED or REVOKED (and
    likewise COMPLETE for a campaign that launched with zero items)".

    The empty-set boundary observed on the posture field: a campaign that launches
    with item_count==0 immediately reports posture COMPLETE (the vacuous-truth
    branch), with no divide-by-zero in completion_pct (100.00).

    Design: Difficulty/boundary_precision_check/campaign_close_with_zero_items_empty_set
    """
    ent = fixtures.create_entitlement(risk_weight=10)
    role = fixtures.create_role([ent["id"]])
    campaign = fixtures.setup_launched_campaign(role["id"])
    assert campaign["item_count"] == 0, campaign["item_count"]
    assert campaign["posture"] == "COMPLETE", campaign["posture"]
    assert campaign["completion_pct"] == 100.00, campaign["completion_pct"]


def test_certify_blocked_once_campaign_closed(api):
    """PRD §3.7: "Both certify and revoke require the owning campaign to be in
    ACTIVE status; a decision attempted while the campaign is not ACTIVE is
    rejected with ERR_CAMPAIGN_NOT_ACTIVE."
    PRD §3.7: "every certification item still in PENDING or UNDER_REVIEW at close
    is auto-decided to REVOKED".

    A campaign with one item is launched then closed (the item auto-revokes);
    certifying that item post-close is rejected — ERR_CAMPAIGN_NOT_ACTIVE (the
    campaign gate) or ERR_INVALID_STATE (the item is already REVOKED). The block
    is governed by the linked campaign's state, a different entity pair than the
    identity case.

    Design: Difficulty/cross_entity_state_dependency/certify_blocked_when_campaign_not_active
    """
    campaign, role, ent, grants = fixtures.setup_campaign_over_n_identical_grants(1)
    item = fixtures.item_for_grant(grants[0]["id"])
    validate_success(api.close_campaign(campaign["id"], CAMPAIGN), 200)

    resp = api.certify_item(item["id"], CERTIFIER)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    ])


def test_revoke_item_blocked_once_campaign_closed(api):
    """PRD §3.7: "Both certify and revoke require the owning campaign to be in
    ACTIVE status; a decision attempted while the campaign is not ACTIVE is rejected
    with ERR_CAMPAIGN_NOT_ACTIVE."
    PRD §3.7: "every certification item still in PENDING or UNDER_REVIEW at close is
    auto-decided to REVOKED".

    The other decision verb against the same campaign-state gate: revoking an item
    after the owning campaign is CLOSED is rejected — ERR_CAMPAIGN_NOT_ACTIVE (the
    campaign gate) or ERR_INVALID_STATE (the item is already REVOKED by close).

    Design: Difficulty/cross_entity_state_dependency/certify_blocked_when_campaign_not_active
    """
    campaign, role, ent, grants = fixtures.setup_campaign_over_n_identical_grants(1)
    item = fixtures.item_for_grant(grants[0]["id"])
    validate_success(api.close_campaign(campaign["id"], CAMPAIGN), 200)

    resp = api.revoke_item(item["id"], CERTIFIER)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    ])
