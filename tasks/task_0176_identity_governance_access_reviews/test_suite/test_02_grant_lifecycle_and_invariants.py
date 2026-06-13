"""Grant lifecycle: the two parallel state dimensions, the conserved-quantity
invariants under grant+revoke, and the identity-disable revoke cascade.

Derived from PRD §3.5 (The Grant: Two Parallel State Dimensions), §3.6
(Disabling and Tearing Down an Identity), and §2.7 (conserved quantities).
"""
from test_helpers import (
    validate_success,
    create_entitlement_payload, create_role_payload, create_identity_payload,
    create_grant_payload,
    TEST_USERS,
    fixtures,
)

CATALOG = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["access_manager_headers"]
CAMPAIGN = TEST_USERS["campaign_admin_headers"]
CERTIFIER = TEST_USERS["certifier_headers"]


def test_certify_advances_review_dimension_only_lifecycle_unchanged(api):
    """PRD §3.5: "From UNDER_REVIEW, certifying the item bubbles the grant to
    CERTIFIED ... reaching CERTIFIED keeps the grant live and changes nothing on
    the lifecycle dimension".

    Certifying the item moves review_status UNDER_REVIEW->CERTIFIED while
    lifecycle_status stays ACTIVE — the two dimensions move independently.

    Design: Difficulty/non_linear_state_machine/grant_parallel_lifecycle_and_review_dimensions
    """
    campaign, role, ent, grants = fixtures.setup_campaign_over_n_identical_grants(1)
    grant = grants[0]
    item = fixtures.item_for_grant(grant["id"])
    validate_success(api.certify_item(item["id"], CERTIFIER), 200)

    got = validate_success(api.get_grant(grant["id"], CERTIFIER), 200)
    assert got["review_status"] == "CERTIFIED", got["review_status"]
    assert got["lifecycle_status"] == "ACTIVE", got["lifecycle_status"]


def test_revoke_advances_review_to_flagged_and_lifecycle_to_revoked_together(api):
    """PRD §3.5: "reaching FLAGGED by way of an item revoke additionally cascades
    the grant's lifecycle_status from ACTIVE to REVOKED together with the full
    revoke side-effect set above."

    The other UNDER_REVIEW exit (item revoke) is the parallel-dimension case where
    both dimensions move at once: review_status reaches FLAGGED AND lifecycle_status
    cascades ACTIVE->REVOKED — the contrast to certify, which moves only the review
    dimension.

    Design: Difficulty/non_linear_state_machine/grant_parallel_lifecycle_and_review_dimensions
    """
    campaign, role, ent, grants = fixtures.setup_campaign_over_n_identical_grants(1)
    grant = grants[0]
    item = fixtures.item_for_grant(grant["id"])
    validate_success(api.revoke_item(item["id"], CERTIFIER), 200)

    got = validate_success(api.get_grant(grant["id"], CERTIFIER), 200)
    assert got["review_status"] == "FLAGGED", got["review_status"]
    assert got["lifecycle_status"] == "REVOKED", got["lifecycle_status"]


def test_grant_then_revoke_conserves_active_grant_count(api):
    """PRD §3.5: "it increments the owning identity's active_grant_count by one"
    PRD §3.5: "it decrements the identity's active_grant_count by one".

    Direct-granting then revoking returns active_grant_count to its pre-grant
    baseline of 0 (0 -> 1 -> 0): the forward and compensating actions net to zero.

    Design: Difficulty/compensating_invariant/grant_then_revoke_conserves_active_grant_count
    """
    inv1 = validate_success(api.create_entitlement(
        create_entitlement_payload(name="Inv1", system_code="I1", risk_weight=10), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Inva", email="inva@x.com"), MANAGER), 201)
    grant = validate_success(api.create_grant(identity["id"],
        create_grant_payload(inv1["id"], identity["version"]), MANAGER), 201)
    before = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert before["active_grant_count"] == 1, before["active_grant_count"]

    validate_success(api.revoke_grant(grant["id"], MANAGER), 200)
    after = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert after["active_grant_count"] == 0, after["active_grant_count"]


def test_grant_then_revoke_restores_orphan_baseline_on_nonhuman(api):
    """PRD §3.5: "it decrements the identity's active_grant_count by one ... it
    recomputes the identity's effective_risk_score and is_orphan".
    PRD §3.2: "it is true exactly when the identity's status is ACTIVE, its is_human
    is false, and its active_grant_count is zero".

    The active_grant_count conservation observed through is_orphan on a non-human
    identity: orphan true at baseline (0 grants), false while the grant is active (1
    grant), and true again after revoke (back to 0) — the counter returns to its
    pre-grant value, flipping is_orphan back.

    Design: Difficulty/compensating_invariant/grant_then_revoke_conserves_active_grant_count
    """
    ent = fixtures.create_entitlement(risk_weight=10)
    identity = fixtures.create_identity(is_human=False)
    assert identity["is_orphan"] is True, "non-human with 0 grants is orphan at baseline"
    grant = fixtures.direct_grant(identity["id"], ent["id"], identity["version"])
    active = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert active["active_grant_count"] == 1 and active["is_orphan"] is False

    validate_success(api.revoke_grant(grant["id"], MANAGER), 200)
    restored = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert restored["active_grant_count"] == 0, restored["active_grant_count"]
    assert restored["is_orphan"] is True, restored["is_orphan"]


def test_grant_then_revoke_conserves_privileged_count_and_risk(api):
    """PRD §3.5: "if the grant's entitlement is privileged it increments
    privileged_entitlement_count by one (counting the distinct entitlement)"
    PRD §3.5: "if the entitlement is privileged and no other active grant of that
    same entitlement remains for the identity, it decrements
    privileged_entitlement_count by one".

    Privileged grant of risk 30: count 0->1, effective 0->55 (30 base + 25
    surcharge); after revoke both return to baseline (count 0, risk 0).

    Design: Difficulty/compensating_invariant/grant_then_revoke_conserves_privileged_count_and_risk
    """
    inv2 = validate_success(api.create_entitlement(
        create_entitlement_payload(name="Inv2", system_code="I2",
                                   is_privileged=True, risk_weight=30), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Invb", email="invb@x.com"), MANAGER), 201)
    grant = validate_success(api.create_grant(identity["id"],
        create_grant_payload(inv2["id"], identity["version"]), MANAGER), 201)
    before = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert before["privileged_entitlement_count"] == 1, before["privileged_entitlement_count"]
    assert before["effective_risk_score"] == 55, before["effective_risk_score"]

    validate_success(api.revoke_grant(grant["id"], MANAGER), 200)
    after = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert after["privileged_entitlement_count"] == 0, after["privileged_entitlement_count"]
    assert after["effective_risk_score"] == 0, after["effective_risk_score"]


def test_revoking_privileged_grant_removes_only_its_surcharge(api):
    """PRD §3.5: "if the entitlement is privileged and no other active grant of that
    same entitlement remains for the identity, it decrements
    privileged_entitlement_count by one; it recomputes the identity's
    effective_risk_score".

    Identity holds one privileged grant (risk 30) and one non-priv grant (risk 10):
    effective = (30+10) base + 25 surcharge = 65, privileged_count 1. Revoking the
    privileged grant conserves the non-priv portion: privileged_count -> 0,
    active_grant_count -> 1, effective -> 10 (the 30 weight and the 25 surcharge
    both leave; the surviving non-priv grant stays).

    Design: Difficulty/compensating_invariant/grant_then_revoke_conserves_privileged_count_and_risk
    """
    identity, ents, grants = fixtures.setup_identity_with_grants(
        [{"is_privileged": True, "risk_weight": 30}, {"is_privileged": False, "risk_weight": 10}]
    )
    before = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert before["privileged_entitlement_count"] == 1, before["privileged_entitlement_count"]
    assert before["effective_risk_score"] == 65, before["effective_risk_score"]

    validate_success(api.revoke_grant(grants[0]["id"], MANAGER), 200)
    after = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert after["privileged_entitlement_count"] == 0, after["privileged_entitlement_count"]
    assert after["active_grant_count"] == 1, after["active_grant_count"]
    assert after["effective_risk_score"] == 10, after["effective_risk_score"]


def test_disable_cascade_resets_counters_to_zero(api):
    """PRD §3.6: "every grant for this identity whose lifecycle_status is ACTIVE
    is transitioned ACTIVE -> REVOKED ... once the cascade settles the identity's
    active_grant_count is zero and its effective_risk_score is zero."

    Identity holding 2 ACTIVE grants is disabled -> status DISABLED,
    active_grant_count 0, effective_risk_score 0.

    Design: Difficulty/transitive_cascade/identity_disable_to_revoke_to_counter_reset
    """
    identity, ents, grants = fixtures.setup_identity_with_grants(
        [{"risk_weight": 10}, {"risk_weight": 10}]
    )
    fresh = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    disabled = validate_success(api.disable_identity(identity["id"],
        {"expected_identity_version": fresh["version"]}, MANAGER), 200)

    assert disabled["status"] == "DISABLED", disabled["status"]
    assert disabled["active_grant_count"] == 0, disabled["active_grant_count"]
    assert disabled["effective_risk_score"] == 0, disabled["effective_risk_score"]


def test_disable_then_enable_does_not_resurrect_grants(api):
    """PRD §3.6: "once the cascade settles the identity's active_grant_count is zero
    ... it is why re-enabling a disabled identity brings it back with no access at
    all."
    PRD §3.2: "Enabling a disabled identity moves its status from DISABLED back to
    ACTIVE ... and pointedly does not resurrect any previously revoked grants — the
    identity comes back with an active_grant_count of zero".

    The disable->revoke->counter-reset chain is permanent: after the cascade drives
    active_grant_count to 0, re-enabling the identity leaves active_grant_count at 0
    (the cascaded revokes are not undone).

    Design: Difficulty/transitive_cascade/identity_disable_to_revoke_to_counter_reset
    """
    identity, ents, grants = fixtures.setup_identity_with_grants(
        [{"risk_weight": 10}, {"risk_weight": 10}]
    )
    fresh = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    disabled = validate_success(api.disable_identity(identity["id"],
        {"expected_identity_version": fresh["version"]}, MANAGER), 200)
    assert disabled["active_grant_count"] == 0

    enabled = validate_success(api.enable_identity(identity["id"],
        {"expected_identity_version": disabled["version"]}, MANAGER), 200)
    assert enabled["status"] == "ACTIVE", enabled["status"]
    assert enabled["active_grant_count"] == 0, enabled["active_grant_count"]


def test_disable_cascade_revokes_all_grants_and_audits(api):
    """PRD §3.6: "every grant for this identity whose lifecycle_status is ACTIVE
    is transitioned ACTIVE -> REVOKED ... An audit event of type
    IDENTITY_DISABLED is appended."

    After disable, both grants read lifecycle_status==REVOKED and an
    IDENTITY_DISABLED audit event exists for the subject identity.

    Design: Corner/cross_cutting_complexity_layers/disable_cascade_revokes_all_grants_endtoend
    """
    identity, ents, grants = fixtures.setup_identity_with_grants(
        [{"risk_weight": 10}, {"risk_weight": 10}]
    )
    fresh = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    validate_success(api.disable_identity(identity["id"],
        {"expected_identity_version": fresh["version"]}, MANAGER), 200)

    g1 = validate_success(api.get_grant(grants[0]["id"], MANAGER), 200)
    g2 = validate_success(api.get_grant(grants[1]["id"], MANAGER), 200)
    assert g1["lifecycle_status"] == "REVOKED", g1["lifecycle_status"]
    assert g2["lifecycle_status"] == "REVOKED", g2["lifecycle_status"]

    events = fixtures.list_identity_audit_events(identity["id"], event_type="IDENTITY_DISABLED")
    assert len(events) >= 1, "expected at least one IDENTITY_DISABLED audit event"


def test_item_revoke_cascades_grant_to_revoked(api):
    """PRD §3.7: "Revoking an item moves it to REVOKED, drives the underlying
    grant's review dimension to FLAGGED and cascades the grant's lifecycle from
    ACTIVE to REVOKED with the full revoke side effects (which recomputes the
    affected identity's counters)".

    Revoking the certification item flips the grant lifecycle ACTIVE->REVOKED and
    review_status->FLAGGED, decrementing the owner's active_grant_count to 0.

    Design: Corner/state_machines/item_revoke_cascades_grant_to_revoked
    """
    campaign, role, ent, grants = fixtures.setup_campaign_over_n_identical_grants(1)
    grant = grants[0]
    identity_id = grant["identity_id"]
    item = fixtures.item_for_grant(grant["id"])
    validate_success(api.revoke_item(item["id"], CERTIFIER), 200)

    got = validate_success(api.get_grant(grant["id"], CERTIFIER), 200)
    assert got["lifecycle_status"] == "REVOKED", got["lifecycle_status"]
    assert got["review_status"] == "FLAGGED", got["review_status"]
    identity = validate_success(api.get_identity(identity_id, MANAGER), 200)
    assert identity["active_grant_count"] == 0, identity["active_grant_count"]
