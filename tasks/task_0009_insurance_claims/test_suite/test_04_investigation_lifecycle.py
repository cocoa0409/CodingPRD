"""Investigation lifecycle: open, update, estimates, and reject.

Pinned to PRD §3.2 (investigation, estimates, reject), §2.11 (blacklist).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    create_investigation_payload, create_estimate_line_item_payload,
    patch_investigation_payload,
    setup_basic_world, file_claim, open_investigation, update_investigation,
    add_estimate_line_item, create_adjuster, create_repair_shop, get_claim,
    make_adjuster_headers, TEST_USERS,
    assert_investigation, assert_estimate_line_item,
)


# ─── §3.2 happy-path open investigation ───────────────────────────
def test_open_investigation_transitions_claim(api):
    """PRD §3.2: "Once a claim is in `INTAKE`, an `Adjuster` opens an
    investigation by providing the `adjuster_id` of the assigned investigator.
    Opening an investigation transitions the claim from `INTAKE` to
    `UNDER_INVESTIGATION` and creates an `Investigation` row in `OPEN`
    status whose `claim_id` references the parent claim."

    Claim: open investigation -> Investigation in OPEN, Claim in
    UNDER_INVESTIGATION.
    """
    world = setup_basic_world()
    claim = file_claim(world)
    inv = open_investigation(world, claim)
    assert_investigation(inv)
    assert inv["status"] == "OPEN"
    assert inv["claim_id"] == claim["id"]
    refreshed = get_claim(claim["id"])
    assert refreshed["status"] == "UNDER_INVESTIGATION"


def test_open_investigation_specialty_mismatch_rejected(api):
    """PRD §3.2: "Two operational guards apply at this point: the underlying
    policy's `status` must be `ACTIVE` and the assigned `Adjuster.specialty`
    must equal the policy's `coverage_type` (`AUTO`, `PROPERTY`, or
    `LIABILITY`); a specialty mismatch is rejected with
    `ERR_ADJUSTER_SPECIALTY_MISMATCH`."

    Claim: AUTO policy + PROPERTY adjuster -> ERR_ADJUSTER_SPECIALTY_MISMATCH.
    """
    world = setup_basic_world(coverage_type="AUTO", adjuster_specialty="AUTO")
    claim = file_claim(world)
    foreign_adj = create_adjuster(full_name="Property Adj", specialty="PROPERTY")
    res = api.create_investigation(
        claim["id"],
        create_investigation_payload(adjuster_id=foreign_adj["id"]),
        make_adjuster_headers(foreign_adj["id"]),
    )
    validate_error(res, "ERR_ADJUSTER_SPECIALTY_MISMATCH")


def test_open_investigation_when_claim_not_in_intake_rejected(api):
    """PRD §2 priority order (§2.6): "the requirement that the `Claim` (or
    other action target) be in the correct state for the requested action"
    PRD §3.2: open-investigation requires Claim.status == INTAKE.

    Claim: opening a second investigation on a claim already in
    UNDER_INVESTIGATION -> ERR_INVESTIGATION_ALREADY_OPEN (per §3.2:
    "Two simultaneous attempts to open an investigation against the same
    claim serialise on the claim's transition out of `INTAKE`; the loser
    is rejected with `ERR_INVESTIGATION_ALREADY_OPEN`.").
    """
    world = setup_basic_world()
    claim = file_claim(world)
    open_investigation(world, claim)
    res = api.create_investigation(
        claim["id"],
        create_investigation_payload(adjuster_id=world["adjuster"]["id"]),
        make_adjuster_headers(world["adjuster"]["id"]),
    )
    validate_error(res, "ERR_INVESTIGATION_ALREADY_OPEN")


# ─── §3.2 update investigation ────────────────────────────────────
def test_patch_investigation_updates_photo_and_doc_auth(api):
    """PRD §3.2: "While the investigation is open, the same adjuster updates
    the case file. Damage photographs are recorded on `photo_urls` (a
    non-empty list of valid http or https URLs); the adjuster's confirmation
    that supporting documents are genuine is recorded on
    `document_authenticity_passed`, which defaults to false on creation;
    and the adjuster's final loss assessment is recorded on
    `assessed_loss_cents`."

    Claim: PATCH /investigations/{inv_id} updates these fields and bumps
    Investigation.version.
    """
    world = setup_basic_world()
    claim = file_claim(world)
    inv = open_investigation(world, claim)
    assert inv["document_authenticity_passed"] is False  # default
    updated = update_investigation(
        claim, inv, world["adjuster"],
        photo_urls=["https://example.com/p1.jpg"],
        document_authenticity_passed=True,
        assessed_loss_cents=400_000,
    )
    assert updated["photo_urls"] == ["https://example.com/p1.jpg"]
    assert updated["document_authenticity_passed"] is True
    assert updated["assessed_loss_cents"] == 400_000
    assert updated["version"] > inv["version"]


# ─── §3.2 estimate line items ─────────────────────────────────────
def test_add_estimate_line_item_succeeds(api):
    """PRD §3.2: "The adjuster also appends repair-shop quotes as estimate
    line items, each carrying its parent `investigation_id`, a
    `repair_shop_id`, a free-text `description`, and a positive
    `amount_cents`."

    Claim: POST /estimates returns 201 and an EstimateLineItem with the
    given fields.
    """
    world = setup_basic_world()
    claim = file_claim(world)
    inv = open_investigation(world, claim)
    line = add_estimate_line_item(
        claim, inv, world["adjuster"], world["repair_shop"],
        description="Repair bumper", amount_cents=350_000,
    )
    assert_estimate_line_item(line)
    assert line["investigation_id"] == inv["id"]
    assert line["repair_shop_id"] == world["repair_shop"]["id"]
    assert line["amount_cents"] == 350_000


def test_add_estimate_line_item_zero_amount_rejected(api):
    """PRD §3.2 / §1.1 EstimateLineItem.amount_cents constraint "> 0".

    Claim: amount_cents = 0 -> ERR_VALIDATION_FAILED.
    """
    world = setup_basic_world()
    claim = file_claim(world)
    inv = open_investigation(world, claim)
    res = api.create_estimate_line_item(
        claim["id"], inv["id"],
        create_estimate_line_item_payload(
            repair_shop_id=world["repair_shop"]["id"],
            amount_cents=0,
        ),
        make_adjuster_headers(world["adjuster"]["id"]),
    )
    validate_error(res, "ERR_VALIDATION_FAILED")


def test_add_estimate_against_blacklisted_shop_rejected(api):
    """PRD §2.11: "Any new estimate line referencing a `BLACKLISTED` shop
    is rejected with `ERR_REPAIR_SHOP_BLACKLISTED`."

    Claim: estimate against a BLACKLISTED shop -> ERR_REPAIR_SHOP_BLACKLISTED.
    """
    world = setup_basic_world()
    claim = file_claim(world)
    inv = open_investigation(world, claim)
    # Admin manually flips shop to BLACKLISTED via PATCH (admin override; PRD §3.9 says
    # "the admin update endpoint can lower or freeze status but cannot raise `trust_score`").
    blacklisted = world["repair_shop"]
    res_patch = api.patch_repair_shop(
        blacklisted["id"], {"status": "BLACKLISTED", "version": blacklisted["version"]},
        TEST_USERS["admin_headers"],
    )
    validate_success(res_patch)
    # Attempt estimate.
    res = api.create_estimate_line_item(
        claim["id"], inv["id"],
        create_estimate_line_item_payload(
            repair_shop_id=blacklisted["id"], amount_cents=100_000,
        ),
        make_adjuster_headers(world["adjuster"]["id"]),
    )
    validate_error(res, "ERR_REPAIR_SHOP_BLACKLISTED")


# ─── §3.2 reject investigation ────────────────────────────────────
def test_reject_investigation_reverts_claim_to_intake(api):
    """PRD §3.2: "If the investigation needs to be unwound, the assigning
    adjuster — and only that adjuster — may reject it. Rejection moves
    the `Investigation.status` to `REJECTED` and reverts the parent claim
    from `UNDER_INVESTIGATION` back to `INTAKE`, clearing
    `Claim.review_path` so that a fresh investigation can be reopened
    later."

    Claim: reject -> Investigation REJECTED, Claim back to INTAKE.
    """
    world = setup_basic_world()
    claim = file_claim(world)
    inv = open_investigation(world, claim)
    res = api.reject_investigation(
        claim["id"], inv["id"],
        make_adjuster_headers(world["adjuster"]["id"]),
    )
    rejected_inv = validate_success(res)
    assert rejected_inv["status"] == "REJECTED"
    refreshed = get_claim(claim["id"])
    assert refreshed["status"] == "INTAKE"


def test_reject_investigation_only_by_assigning_adjuster(api):
    """PRD §3.2: "If the investigation needs to be unwound, the assigning
    adjuster — and only that adjuster — may reject it."

    Claim: a different adjuster cannot reject the investigation.
    """
    world = setup_basic_world()
    claim = file_claim(world)
    inv = open_investigation(world, claim)
    other_adj = create_adjuster(full_name="Other Adjuster", specialty="AUTO")
    res = api.reject_investigation(
        claim["id"], inv["id"],
        make_adjuster_headers(other_adj["id"]),
    )
    body = res.json()
    assert res.status_code >= 400, f"Other adjuster must not reject: {body}"


# ─── RBAC on investigation endpoints ──────────────────────────────
def test_open_investigation_requires_adjuster(api, customer_headers):
    """PRD §4 endpoints table: POST /claims/{id}/investigations is Adjuster-only.

    Claim: Customer calling POST /investigations -> ERR_FORBIDDEN.
    """
    world = setup_basic_world()
    claim = file_claim(world)
    res = api.create_investigation(
        claim["id"],
        create_investigation_payload(adjuster_id=world["adjuster"]["id"]),
        customer_headers,
    )
    validate_error(res, "ERR_FORBIDDEN")
