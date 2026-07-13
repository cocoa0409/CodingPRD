"""Compensating invariants on completion (escrow/bond and structure tonnage) and
optimistic-concurrency control on permit edits.
"""
from test_helpers import (
    TEST_USERS, make_carrier_headers,
    validate_success, validate_error,
    ApiErrorId,
    new_carrier, new_permit, add_segment, issue, complete,
    drive_overweight_permit_to_issued, drive_superload_permit_to_approved,
    assert_carrier_escrow_conserved, assert_structure_conserves_tonnage,
)

ADMIN = TEST_USERS["dot_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / escrow_bond_conservation_on_complete
# ---------------------------------------------------------------------------
def test_complete_restores_escrow(api):
    """PRD §3.7: "if a bond is `ACTIVE` it moves to `RELEASED`, crediting the
    carrier's `escrow_balance_cents` by the bond `amount_cents` and debiting
    `active_bond_amount_cents` by the same amount, conserving the escrow."

    Design: Difficulty/compensating_invariant/escrow_bond_conservation_on_complete
    """
    ctx = drive_superload_permit_to_approved(api, escrow_cents=10_000_000, gross_weight_lbs=210000)
    issue(api, ctx["permit"]["id"])
    completed = complete(api, ctx["permit"]["id"], ctx["carrier"]["id"])
    assert completed["status"] == "COMPLETED"
    carrier = validate_success(api.get_carrier(ctx["carrier"]["id"], ADMIN), 200)
    assert carrier["escrow_balance_cents"] == 10000000
    assert carrier["active_bond_amount_cents"] == 0


def test_complete_conserves_escrow_ledger(api):
    """PRD §2.9: "`active_bond_amount_cents` ... is the invariant partner of the
    escrow balance — when a bond activates, the escrow balance is debited and the
    active-bond total is credited by the bond amount; when a bond releases, the
    escrow balance is credited and the active-bond total is debited by the same
    amount."

    Design: Difficulty/compensating_invariant/escrow_bond_conservation_on_complete
    """
    ctx = drive_superload_permit_to_approved(api, escrow_cents=10_000_000, gross_weight_lbs=210000)
    issue(api, ctx["permit"]["id"])
    complete(api, ctx["permit"]["id"], ctx["carrier"]["id"])
    carrier = validate_success(api.get_carrier(ctx["carrier"]["id"], ADMIN), 200)
    assert_carrier_escrow_conserved(carrier)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / structure_tonnage_conservation_on_complete
# ---------------------------------------------------------------------------
def test_complete_releases_structure_tonnage(api):
    """PRD §3.7: "each `RESERVED` route segment moves to `COMPLETED` and its
    `load_tonnage` is subtracted from the crossed structure's `committed_tonnage`
    (with `available_tonnage` and `posture` recomputed)".

    Design: Difficulty/compensating_invariant/structure_tonnage_conservation_on_complete
    """
    from test_helpers import new_structure
    structure = new_structure(api, rated_capacity_tonnage=200, dead_load_tonnage=40)
    ctx = drive_overweight_permit_to_issued(api, structure=structure, gross_weight_lbs=120000)
    completed = complete(api, ctx["permit"]["id"], ctx["carrier"]["id"])
    assert completed["status"] == "COMPLETED"
    data = validate_success(api.get_structure(structure["id"], ADMIN), 200)
    assert data["committed_tonnage"] == 0
    assert data["available_tonnage"] == 200


def test_complete_conserves_structure_tonnage(api):
    """PRD §3.1: "On creation its `committed_tonnage` is 0 and its
    `available_tonnage` equals its rated capacity."
    PRD §3.7: "each `RESERVED` route segment moves to `COMPLETED` and its
    `load_tonnage` is subtracted from the crossed structure's `committed_tonnage`
    (with `available_tonnage` and `posture` recomputed)".

    After the single reservation is released, committed returns to 0 and available
    returns to the rated capacity, so committed + available == rated holds.

    Design: Difficulty/compensating_invariant/structure_tonnage_conservation_on_complete
    """
    from test_helpers import new_structure
    structure = new_structure(api, rated_capacity_tonnage=200, dead_load_tonnage=40)
    ctx = drive_overweight_permit_to_issued(api, structure=structure, gross_weight_lbs=120000)
    complete(api, ctx["permit"]["id"], ctx["carrier"]["id"])
    data = validate_success(api.get_structure(structure["id"], ADMIN), 200)
    assert_structure_conserves_tonnage(data)


# ---------------------------------------------------------------------------
# Corner: cross_cutting — optimistic concurrency control
# ---------------------------------------------------------------------------
def test_occ_stale_version_rejected(api):
    """PRD §2.6: "Because adding a route segment, resubmitting, or any prior edit
    advances the permit's `version`, a client that read the permit before one of
    those mutations holds a stale view; its edit is therefore rejected with
    `ERR_STALE_PERMIT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_permit_version_conflict
    """
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"])  # version 1
    add_segment(api, permit["id"], carrier["id"])  # version -> 2
    resp = api.edit_permit(permit["id"], {"expected_permit_version": 1, "width_in": 110},
                           make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_PERMIT_VERSION, 412)


def test_occ_fresh_version_succeeds(api):
    """PRD §3.2: "it must carry the `expected_permit_version` described in §2.6; a
    successful edit increments the permit's `version`."
    PRD §3.2: "adding a segment increments the owning permit's `version`."

    Design: Corner/cross_cutting/occ_fresh_permit_version_succeeds
    """
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"])  # version 1
    add_segment(api, permit["id"], carrier["id"])  # version -> 2
    current = validate_success(api.get_permit(permit["id"], make_carrier_headers(carrier["id"])), 200)
    resp = api.edit_permit(permit["id"], {"expected_permit_version": current["version"], "width_in": 110},
                           make_carrier_headers(carrier["id"]))
    data = validate_success(resp, 200)
    assert data["width_in"] == 110
    assert data["version"] == 3
