"""Composite setup helpers for multi-step Flood Insurance test prerequisites.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints; the test harness restarts the server before every test, so every
fixture starts against an empty database.

Identity threading (PRD §2.1): the PolicyHolder X-User-ID is the identifier
recorded as owner_id / holder_id / claimant_id. Ownership-gated calls MUST use
make_policy_holder_headers(<that id>) so the ownership check passes. The other
three roles are opaque operators; the shared constants in TEST_USERS are fine
for them.

The logical clock starts at 2026-01-01T00:00:00Z (PRD §2.9). Fixtures that
need a policy to bind/activate/claim on a chosen date set the clock explicitly
via set_clock().
"""
from typing import Optional
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_community_payload,
    create_property_payload,
    create_elevation_certificate_payload,
    create_policy_quote_payload,
    create_claim_payload,
    create_proof_of_loss_payload,
)
from .test_users import (
    TEST_USERS,
    make_policy_holder_headers,
)


# --- Tier 0: Logical clock -------------------------------------------------

def set_clock(iso8601: str) -> None:
    """Advance the server's logical clock to an absolute UTC instant (FemaAdmin)."""
    api_client.set_clock(iso8601, TEST_USERS["fema_admin_headers"])


# --- Tier 1: Single-entity creation ----------------------------------------

def create_community(crs_class: int = 10, participating: bool = True, **overrides) -> dict:
    """FemaAdmin registers an NFIP community."""
    payload = create_community_payload(
        crs_class=crs_class, participating=participating, **overrides
    )
    return get_success_data(
        api_client.create_community(payload, TEST_USERS["fema_admin_headers"])
    )


def create_property(community_id: str, owner_id: str, **overrides) -> dict:
    """Register a property. owner_id is the PolicyHolder X-User-ID owning it;
    the call is made as that holder so the ownership recording is consistent."""
    payload = create_property_payload(community_id, owner_id, **overrides)
    return get_success_data(
        api_client.create_property(payload, make_policy_holder_headers(owner_id))
    )


def create_elevation_certificate(property_id: str, owner_id: str, **overrides) -> dict:
    """File an elevation certificate against a property (as the owning holder)."""
    payload = create_elevation_certificate_payload(property_id, **overrides)
    return get_success_data(
        api_client.create_elevation_certificate(
            payload, make_policy_holder_headers(owner_id)
        )
    )


def quote_policy(property_id: str, owner_id: str, rating_method: str = "RISK_RATING_2_0",
                 **overrides) -> dict:
    """Quote a policy on a property (as the owning holder)."""
    payload = create_policy_quote_payload(rating_method, **overrides)
    return get_success_data(
        api_client.quote_policy(property_id, payload, make_policy_holder_headers(owner_id))
    )


def quote_policy_as_underwriter(property_id: str, rating_method: str = "RISK_RATING_2_0",
                                **overrides) -> dict:
    """Quote a policy on behalf of the owner (Underwriter)."""
    payload = create_policy_quote_payload(rating_method, **overrides)
    return get_success_data(
        api_client.quote_policy(property_id, payload, TEST_USERS["underwriter_headers"])
    )


# --- Tier 2: Property + certificate scaffolding ----------------------------

def setup_community_property(crs_class: int = 10, participating: bool = True,
                             owner_id: str = "holder-1", flood_zone: str = "X",
                             occupancy: str = "PRIMARY_RESIDENCE",
                             base_flood_elevation_ft: float = 10.0,
                             has_active_mortgage: bool = False,
                             with_certificate: bool = True,
                             lowest_floor_elevation_ft: float = 11.0):
    """Active-DB scaffold: a participating community + a property (+ optional
    elevation certificate). Returns (community, property, certificate-or-None)."""
    community = create_community(crs_class=crs_class, participating=participating)
    prop = create_property(
        community["id"], owner_id,
        flood_zone=flood_zone, occupancy=occupancy,
        base_flood_elevation_ft=base_flood_elevation_ft,
        has_active_mortgage=has_active_mortgage,
    )
    cert = None
    if with_certificate:
        cert = create_elevation_certificate(
            prop["id"], owner_id, lowest_floor_elevation_ft=lowest_floor_elevation_ft
        )
    return community, prop, cert


# --- Tier 3: Policy lifecycle shortcuts ------------------------------------

def setup_quoted_policy(owner_id: str = "holder-1", rating_method: str = "RISK_RATING_2_0",
                        crs_class: int = 10, participating: bool = True,
                        flood_zone: str = "X", occupancy: str = "PRIMARY_RESIDENCE",
                        base_flood_elevation_ft: float = 10.0,
                        has_active_mortgage: bool = False,
                        lowest_floor_elevation_ft: float = 11.0,
                        with_certificate: bool = True,
                        quote_as_underwriter: bool = False,
                        **quote_overrides):
    """Build through to a QUOTED policy. Returns (community, property, policy)."""
    community, prop, _ = setup_community_property(
        crs_class=crs_class, participating=participating, owner_id=owner_id,
        flood_zone=flood_zone, occupancy=occupancy,
        base_flood_elevation_ft=base_flood_elevation_ft,
        has_active_mortgage=has_active_mortgage,
        with_certificate=with_certificate,
        lowest_floor_elevation_ft=lowest_floor_elevation_ft,
    )
    if quote_as_underwriter:
        policy = quote_policy_as_underwriter(prop["id"], rating_method, **quote_overrides)
    else:
        policy = quote_policy(prop["id"], owner_id, rating_method, **quote_overrides)
    return community, prop, policy


def setup_bound_policy(bind_clock: str = "2026-03-01T00:00:00Z", **kwargs):
    """Build through to a BOUND policy. Sets the clock to bind_clock before bind.
    Returns (community, property, bound_policy)."""
    community, prop, policy = setup_quoted_policy(**kwargs)
    set_clock(bind_clock)
    bound = get_success_data(
        api_client.bind_policy(policy["id"], TEST_USERS["underwriter_headers"])
    )
    return community, prop, bound


def setup_active_policy(bind_clock: str = "2026-03-01T00:00:00Z",
                        activate_clock: Optional[str] = None,
                        is_lender_required: bool = True, **kwargs):
    """Build through to an ACTIVE policy.

    Defaults to a lender-required policy (0-day waiting period) so it can be
    activated at bind_clock. For a standard 30-day policy, pass
    is_lender_required=False and an activate_clock at/after effective_date.
    Returns (community, property, active_policy).
    """
    kwargs.setdefault("is_lender_required", is_lender_required)
    community, prop, bound = setup_bound_policy(bind_clock=bind_clock, **kwargs)
    if activate_clock is not None:
        set_clock(activate_clock)
    active = get_success_data(
        api_client.activate_policy(bound["id"], TEST_USERS["underwriter_headers"])
    )
    return community, prop, active


# --- Tier 4: Claim lifecycle shortcuts -------------------------------------

def file_claim(policy_id: str, claimant_id: str, date_of_loss: str, **overrides) -> dict:
    """File a claim under a policy (as the claimant holder)."""
    payload = create_claim_payload(policy_id, claimant_id, date_of_loss, **overrides)
    return get_success_data(
        api_client.create_claim(payload, make_policy_holder_headers(claimant_id))
    )


def open_review(claim_id: str) -> dict:
    """Adjuster opens review on a SUBMITTED claim. Returns the UNDER_REVIEW claim."""
    return get_success_data(
        api_client.open_review(claim_id, TEST_USERS["adjuster_headers"])
    )


def file_proof_of_loss(claim_id: str, claimant_id: str, **overrides) -> dict:
    """File a sworn proof-of-loss for a claim (as the claimant holder)."""
    payload = create_proof_of_loss_payload(claim_id, **overrides)
    return get_success_data(
        api_client.create_proof_of_loss(payload, make_policy_holder_headers(claimant_id))
    )


def accept_proof_of_loss(proof_id: str) -> dict:
    """Adjuster accepts a PENDING proof-of-loss. Returns the ACCEPTED proof."""
    return get_success_data(
        api_client.accept_proof_of_loss(proof_id, TEST_USERS["adjuster_headers"])
    )


def setup_claim_under_review(owner_id: str = "holder-1",
                             date_of_loss: str = "2026-04-10T00:00:00Z",
                             bind_clock: str = "2026-03-01T00:00:00Z",
                             claim_overrides: Optional[dict] = None,
                             **policy_kwargs):
    """ACTIVE lender policy + a claim moved to UNDER_REVIEW.
    Returns (community, property, policy, claim)."""
    community, prop, policy = setup_active_policy(
        owner_id=owner_id, bind_clock=bind_clock, **policy_kwargs
    )
    claim = file_claim(policy["id"], owner_id, date_of_loss, **(claim_overrides or {}))
    claim = open_review(claim["id"])
    return community, prop, policy, claim


def setup_claim_with_accepted_proof(owner_id: str = "holder-1",
                                    date_of_loss: str = "2026-04-10T00:00:00Z",
                                    bind_clock: str = "2026-03-01T00:00:00Z",
                                    accept_clock: Optional[str] = None,
                                    claim_overrides: Optional[dict] = None,
                                    proof_overrides: Optional[dict] = None,
                                    **policy_kwargs):
    """ACTIVE lender policy + a claim UNDER_REVIEW + an ACCEPTED reconciling
    proof-of-loss. The claim is then approvable.

    claim_overrides / proof_overrides default to a building_loss 5000 claim with
    a reconciling documented_building_loss 5000. Returns
    (community, property, policy, claim, proof) where `claim` is the UNDER_REVIEW
    claim captured BEFORE approval (so its `version` is the approve-ready value).
    """
    claim_ov = {"building_loss": 5000}
    if claim_overrides:
        claim_ov = claim_overrides
    proof_ov = {"documented_building_loss": 5000}
    if proof_overrides is not None:
        proof_ov = proof_overrides

    community, prop, policy, claim = setup_claim_under_review(
        owner_id=owner_id, date_of_loss=date_of_loss, bind_clock=bind_clock,
        claim_overrides=claim_ov, **policy_kwargs
    )
    proof = file_proof_of_loss(claim["id"], owner_id, **proof_ov)
    if accept_clock is not None:
        set_clock(accept_clock)
    proof = accept_proof_of_loss(proof["id"])
    return community, prop, policy, claim, proof


def approve_claim(claim_id: str, expected_claim_version: int) -> dict:
    """Adjuster approves a claim with the OCC version. Returns the APPROVED claim."""
    return get_success_data(
        api_client.approve_claim(
            claim_id, {"expected_claim_version": expected_claim_version},
            TEST_USERS["adjuster_headers"],
        )
    )


def deny_claim(claim_id: str, expected_claim_version: int) -> dict:
    """Adjuster denies a claim with the OCC version. Returns the DENIED claim."""
    return get_success_data(
        api_client.deny_claim(
            claim_id, {"expected_claim_version": expected_claim_version},
            TEST_USERS["adjuster_headers"],
        )
    )


def setup_approved_claim(owner_id: str = "holder-1",
                         date_of_loss: str = "2026-04-10T00:00:00Z",
                         bind_clock: str = "2026-03-01T00:00:00Z",
                         claim_overrides: Optional[dict] = None,
                         proof_overrides: Optional[dict] = None,
                         **policy_kwargs):
    """Full lifecycle through an APPROVED, settled claim.
    Returns (community, property, policy, approved_claim)."""
    community, prop, policy, claim, _proof = setup_claim_with_accepted_proof(
        owner_id=owner_id, date_of_loss=date_of_loss, bind_clock=bind_clock,
        claim_overrides=claim_overrides, proof_overrides=proof_overrides,
        **policy_kwargs
    )
    approved = approve_claim(claim["id"], claim["version"])
    return community, prop, policy, approved
