"""Risk scoring: effective vs projected score, the stepped privilege surcharge
and its cap, the high-risk flag boundary, and immediate counter consistency.

All values are derived from PRD §2.7 (Risk Scoring, Privilege Surcharge, and
Derived-Field Reconciliation) and §3.5 (grant activation side effects).
"""
from test_helpers import (
    validate_success,
    create_entitlement_payload, create_role_payload, create_identity_payload,
    create_grant_payload, create_access_request_payload,
    TEST_USERS, build_user_headers,
    fixtures,
)

CATALOG = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["access_manager_headers"]


def test_effective_and_projected_risk_diverge_with_submitted_request(api):
    """PRD §2.7: "The projected risk score is the active-grant base plus the
    pending base plus this projected surcharge."
    PRD §2.7: "On top of the base sits a stepped privilege surcharge: count the
    distinct privileged entitlements held through active grants, cap that count
    at three, and add 25 points for each counted privileged entitlement."

    Effective: one held non-priv grant of risk 30 -> base 30, no privileged ->
    surcharge 0 -> 30. Projected adds pending entitlements (priv 40 + non-priv
    20) and 1 distinct privileged -> 30 + 60 + 25 = 115.

    Design: Difficulty/dual_variant_calc/identity_projected_vs_effective_risk_diverge
    """
    e_held = validate_success(api.create_entitlement(
        create_entitlement_payload(name="Held", system_code="SYS_H",
                                   is_privileged=False, risk_weight=30), CATALOG), 201)
    e_p = validate_success(api.create_entitlement(
        create_entitlement_payload(name="ReqPriv", system_code="SYS_P",
                                   is_privileged=True, risk_weight=40), CATALOG), 201)
    e_n = validate_success(api.create_entitlement(
        create_entitlement_payload(name="ReqNon", system_code="SYS_N",
                                   is_privileged=False, risk_weight=20), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([e_p["id"], e_n["id"]], name="RoleR"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Ida", email="ida@x.com"), MANAGER), 201)
    # Grant the held entitlement (active-grant base = 30).
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(e_held["id"], identity["version"]), MANAGER), 201)
    # Raise + submit a request for the role (adds the pending set).
    mgr = build_user_headers("mgr-1", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)

    got = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert got["effective_risk_score"] == 30, got["effective_risk_score"]
    assert got["projected_risk_score"] == 115, got["projected_risk_score"]
    assert got["projected_risk_score"] != got["effective_risk_score"]


def test_projected_drops_back_to_effective_after_request_rejected(api):
    """PRD §3.4: "Finally the identity's projected_risk_score is recomputed: with
    the request no longer pending, its pending portion is cleared and the
    projection now equals the effective score."
    PRD §2.7: "When an identity has no submitted requests, its pending set is empty
    and its projected risk score equals its effective risk score."

    Same divergence scenario, asserted from the opposite end: while SUBMITTED the
    projection (115) exceeds effective (30); once the only pending request is
    rejected the projection collapses back to the effective score (30) — the two
    algorithms converge when the pending set empties.

    Design: Difficulty/dual_variant_calc/identity_projected_vs_effective_risk_diverge
    """
    e_held = validate_success(api.create_entitlement(
        create_entitlement_payload(name="Held", system_code="SYS_H",
                                   is_privileged=False, risk_weight=30), CATALOG), 201)
    e_p = validate_success(api.create_entitlement(
        create_entitlement_payload(name="ReqPriv", system_code="SYS_P",
                                   is_privileged=True, risk_weight=40), CATALOG), 201)
    e_n = validate_success(api.create_entitlement(
        create_entitlement_payload(name="ReqNon", system_code="SYS_N",
                                   is_privileged=False, risk_weight=20), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([e_p["id"], e_n["id"]], name="RoleR"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Idb", email="idb@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(e_held["id"], identity["version"]), MANAGER), 201)
    mgr = build_user_headers("mgr-2", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)
    diverged = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert diverged["projected_risk_score"] == 115
    assert diverged["effective_risk_score"] == 30

    apr = build_user_headers("apr-2", "AccessApprover")
    validate_success(api.reject_access_request(req["id"], apr), 200)
    after = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert after["projected_risk_score"] == 30, after["projected_risk_score"]
    assert after["projected_risk_score"] == after["effective_risk_score"]


def test_effective_risk_nonlinear_privileged_surcharge_caps_at_three(api):
    """PRD §2.7: "the surcharge is 25 points multiplied by the smaller of the
    privileged count and three — so zero privileged entitlements add nothing,
    one adds 25, two adds 50, three adds 75, and four or more still add only 75."

    Four privileged grants of risk 20: base 80, surcharge 25*min(4,3)=75 -> 155.

    Design: Difficulty/combinatorial_formula/effective_risk_nonlinear_privileged_surcharge
    """
    identity, ents, grants = fixtures.setup_identity_with_grants(
        [{"is_privileged": True, "risk_weight": 20} for _ in range(4)]
    )
    got = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert got["privileged_entitlement_count"] == 4, got["privileged_entitlement_count"]
    assert got["effective_risk_score"] == 155, got["effective_risk_score"]


def test_effective_risk_per_grant_contribution_is_raw_risk_weight(api):
    """PRD §2.7: "Each individual active grant's risk_contribution is exactly the
    risk_weight of its entitlement; the surcharge is an identity-level addition and
    is not distributed across the individual grants."

    The same 4-privileged-grant scenario, asserted on the per-grant facet: each
    grant's risk_contribution equals its entitlement risk_weight (20), proving the
    75-point surcharge lives at the identity level (155 = 80 base + 75) and is not
    spread across grants.

    Design: Difficulty/combinatorial_formula/effective_risk_nonlinear_privileged_surcharge
    """
    identity, ents, grants = fixtures.setup_identity_with_grants(
        [{"is_privileged": True, "risk_weight": 20} for _ in range(4)]
    )
    for g in grants:
        got = validate_success(api.get_grant(g["id"], MANAGER), 200)
        assert got["risk_contribution"] == 20, got["risk_contribution"]
    identity_now = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert identity_now["effective_risk_score"] == 155, identity_now["effective_risk_score"]


def test_privileged_surcharge_cap_at_three_steps(api):
    """PRD §2.7: "count the distinct privileged entitlements held through active
    grants, cap that count at three, and add 25 points for each counted
    privileged entitlement."

    Three privileged grants of risk 10: base 30 + surcharge 25*min(3,3)=75 = 105.

    Design: Corner/calculations/privileged_surcharge_cap_at_three_steps
    """
    identity, ents, grants = fixtures.setup_identity_with_grants(
        [{"is_privileged": True, "risk_weight": 10} for _ in range(3)]
    )
    got = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert got["effective_risk_score"] == 105, got["effective_risk_score"]


def test_high_risk_flag_at_exactly_100_boundary(api):
    """PRD §3.4: "If, as a result of these activations, the identity's
    effective_risk_score crosses the high-risk threshold of 100 points, the
    newest privileged grant has its review dimension set to FLAGGED."
    PRD §2.7: "A risk threshold of 100 points marks the boundary of high risk."

    A single privileged grant of risk 75: base 75 + surcharge 25 = 100, which is
    >= the boundary, so the grant is FLAGGED at exactly 100.

    Design: Difficulty/boundary_precision_check/high_risk_threshold_ge_boundary
    """
    e75 = validate_success(api.create_entitlement(
        create_entitlement_payload(name="Edge75", system_code="E75",
                                   is_privileged=True, risk_weight=75), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Edge", email="edge@x.com"), MANAGER), 201)
    grant = validate_success(api.create_grant(identity["id"],
        create_grant_payload(e75["id"], identity["version"]), MANAGER), 201)

    got = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert got["effective_risk_score"] == 100, got["effective_risk_score"]
    assert grant["review_status"] == "FLAGGED", grant["review_status"]


def test_high_risk_no_flag_just_below_100_boundary(api):
    """PRD §3.4: "If, as a result of these activations, the identity's
    effective_risk_score crosses the high-risk threshold of 100 points, the newest
    privileged grant has its review dimension set to FLAGGED."
    PRD §2.7: "A risk threshold of 100 points marks the boundary of high risk."

    Boundary X-1: a privileged grant of risk 74 lands effective at 99 (74 + 25
    surcharge), which does NOT cross 100, so the grant is NOT flagged and stays at
    its initial NOT_DUE review status.

    Design: Difficulty/boundary_precision_check/high_risk_threshold_ge_boundary
    """
    e74 = validate_success(api.create_entitlement(
        create_entitlement_payload(name="Edge74", system_code="E74",
                                   is_privileged=True, risk_weight=74), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Edge2", email="edge2@x.com"), MANAGER), 201)
    grant = validate_success(api.create_grant(identity["id"],
        create_grant_payload(e74["id"], identity["version"]), MANAGER), 201)

    got = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert got["effective_risk_score"] == 99, got["effective_risk_score"]
    assert grant["review_status"] == "NOT_DUE", grant["review_status"]


def test_projected_equals_effective_when_no_pending_requests(api):
    """PRD §2.7: "When an identity has no submitted requests, its pending set is
    empty and its projected risk score equals its effective risk score."

    One held non-priv grant of risk 30, no submitted requests: both scores 30.

    Design: Corner/calculations/projected_equals_effective_when_no_pending_requests
    """
    en = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntN", system_code="EN",
                                   is_privileged=False, risk_weight=30), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Ni", email="ni@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(en["id"], identity["version"]), MANAGER), 201)

    got = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert got["effective_risk_score"] == 30, got["effective_risk_score"]
    assert got["projected_risk_score"] == 30, got["projected_risk_score"]


def test_grant_counters_and_risk_immediately_consistent(api):
    """PRD §2.7: "they are never set by a client and are recomputed by the system
    every time a grant activates, a grant is revoked, a request changes the
    pending set, or an identity is disabled."
    PRD §3.5: "it increments the owning identity's active_grant_count by one ...
    it recomputes the identity's effective_risk_score and is_orphan".

    Right after a direct non-priv grant of risk 10, the identity read shows
    active_grant_count==1 and effective_risk_score==10.

    Design: Corner/consistency_model/counters_visible_in_same_response_immediate
    """
    imm = validate_success(api.create_entitlement(
        create_entitlement_payload(name="Imm", system_code="IM", risk_weight=10), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Immi", email="imm@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(imm["id"], identity["version"]), MANAGER), 201)

    got = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert got["active_grant_count"] == 1, got["active_grant_count"]
    assert got["effective_risk_score"] == 10, got["effective_risk_score"]
