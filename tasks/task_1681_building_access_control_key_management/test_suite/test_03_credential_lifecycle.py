"""Credential lifecycle: issue/return cycle, invalid transitions, per-node count
reconciliation, and the physical-pool conservation invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_node_counts,
    create_credential,
    create_person,
    get_credential,
    get_key_node,
    get_success_data,
    issue_credential,
    set_clock,
    setup_building_with_chain,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["security_admin_headers"]
DESK = TEST_USERS["front_desk_headers"]
OFFICER = TEST_USERS["security_officer_headers"]


# ---------------------------------------------------------------------------
# Corner: invalid transitions
# ---------------------------------------------------------------------------

def test_credential_issue_from_issued_rejected(api):
    """PRD §3.2: "The credential must currently be `IN_STOCK`, else
    `ERR_CREDENTIAL_NOT_ISSUABLE`."

    Design: Corner/state_machines/credential_issue_from_issued_rejected
    """
    ctx = setup_building_with_chain("SM House")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    r2 = create_person(building["id"], "Res Two", "RESIDENT", unit_label="U-2")
    cred = create_credential(building["id"], change["id"], "F-1", "FOB")
    issue_credential(cred["id"], r1["id"])

    resp = api.issue_credential(cred["id"], {"person_id": r2["id"]}, DESK)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_ISSUABLE)
    assert get_credential(cred["id"])["holder_person_id"] == r1["id"]


def test_credential_return_from_stock_rejected(api):
    """PRD §3.2: "The credential lifecycle is cyclic around stock: returning an
    `ISSUED` credential — again `ERR_CREDENTIAL_NOT_ISSUED` guards the
    precondition — clears `holder_person_id`, `issued_at`, and `expires_at`,
    putting it back to `IN_STOCK` where it may be issued again."

    Design: Corner/state_machines/credential_return_from_stock_rejected
    """
    ctx = setup_building_with_chain("SM House 2")
    cred = create_credential(ctx["building"]["id"], ctx["change"]["id"], "F-1", "FOB")
    resp = api.return_credential(cred["id"], DESK)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_ISSUED)
    assert get_credential(cred["id"])["status"] == "IN_STOCK"


def test_error_credential_not_issued_on_lost_report(api):
    """PRD §3.2: "Reporting a credential lost requires it to be `ISSUED` (same
    `ERR_CREDENTIAL_NOT_ISSUED` guard); a `Resident` or `Vendor` caller may
    report only a credential whose `holder_person_id` matches their `X-User-ID`,
    else `ERR_FORBIDDEN`."

    Design: Corner/errors/error_credential_not_issued_on_lost_report
    """
    ctx = setup_building_with_chain("NotIssued House")
    building, change = ctx["building"], ctx["change"]
    cred = create_credential(building["id"], change["id"], "K-1", "METAL_KEY")
    resp = api.report_lost_credential(cred["id"], DESK)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_ISSUED)
    assert get_key_node(change["id"])["status"] == "ACTIVE"
    incidents = get_success_data(
        api.list_incidents(OFFICER, params={"credential_id": cred["id"]})
    )
    assert incidents == []


# ---------------------------------------------------------------------------
# Corner: per-node counts
# ---------------------------------------------------------------------------

def test_key_node_counts_are_node_local_not_subtree(api):
    """PRD §3.1: "Three computed counters describe a node's inventory at any
    moment, counting only credentials pinned to that exact node (never the
    subtree): `stock_credential_count` is the number with `status` `IN_STOCK`,
    `issued_credential_count` the number `ISSUED`, and `lost_credential_count`
    the number `LOST`."

    Design: Corner/calculations/key_node_counts_are_node_local_not_subtree
    """
    ctx = setup_building_with_chain("Counts House")
    building, master, change = ctx["building"], ctx["master"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    cred = create_credential(building["id"], change["id"], "F-1", "FOB")
    issue_credential(cred["id"], r1["id"])

    assert get_key_node(change["id"])["issued_credential_count"] == 1
    assert get_key_node(master["id"])["issued_credential_count"] == 0


def test_node_counts_reconcile_after_moveout_deactivation(api):
    """PRD §3.6: "The transition stamps `moved_out_at` to now, deactivates
    every credential currently `ISSUED` to that person with
    `deactivated_reason` `MOVE_OUT`, removes the person's id from the
    `person_ids` of every access group in the building, and creates the
    settlement charge in `DRAFT`: `kind` `MOVE_OUT_SETTLEMENT`, `person_id`
    set, `deposit_cents` snapshotted from the person's `key_deposit_cents`,
    `moved_out_at` recorded, `line_items` holding the forfeiture lines for
    the credentials `ISSUED` at move-out, `provisional_refund_cents`
    computed, and `amount_cents` 0 while in draft."
    PRD §3.2: "Deactivation is always system-driven: a credential leaves
    `IN_STOCK`, `ISSUED`, or `LOST` for `DEACTIVATED` with `deactivated_reason`
    one of `MOVE_OUT`, `TERMINATION`, `EXPIRED`, `REKEY`, or `INCIDENT`,
    retaining `holder_person_id` and (when present) `lost_at` for the record."

    Design: Corner/cross_cutting_layers/node_counts_reconcile_after_moveout_deactivation
    """
    ctx = setup_building_with_chain("Reconcile House")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    f1 = create_credential(building["id"], change["id"], "F-1", "FOB")
    f2 = create_credential(building["id"], change["id"], "F-2", "FOB")
    create_credential(building["id"], change["id"], "F-3", "FOB")
    issue_credential(f1["id"], r1["id"])
    issue_credential(f2["id"], r1["id"])

    resp = api.move_out_person(r1["id"], DESK)
    get_success_data(resp)

    node = get_key_node(change["id"])
    assert_node_counts(node, stock=1, issued=0, lost=0)
    f1_after = get_credential(f1["id"])
    assert f1_after["status"] == "DEACTIVATED"
    assert f1_after["deactivated_reason"] == "MOVE_OUT"
    assert f1_after["holder_person_id"] == r1["id"]


# ---------------------------------------------------------------------------
# Difficulty: cyclic issue/return reissue loop
# ---------------------------------------------------------------------------

def _setup_three_fob_node():
    ctx = setup_building_with_chain("Cycle House")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    r2 = create_person(building["id"], "Res Two", "RESIDENT", unit_label="U-2")
    f1 = create_credential(building["id"], change["id"], "S-1", "FOB")
    create_credential(building["id"], change["id"], "S-2", "FOB")
    create_credential(building["id"], change["id"], "S-3", "FOB")
    return ctx, r1, r2, f1


def test_credential_issue_return_reissue_cycle_counts(api):
    """PRD §3.2: "The credential lifecycle is cyclic around stock: returning an
    `ISSUED` credential — again `ERR_CREDENTIAL_NOT_ISSUED` guards the
    precondition — clears `holder_person_id`, `issued_at`, and `expires_at`,
    putting it back to `IN_STOCK` where it may be issued again."
    PRD §3.1: "Three computed counters describe a node's inventory at any
    moment, counting only credentials pinned to that exact node (never the
    subtree): `stock_credential_count` is the number with `status` `IN_STOCK`,
    `issued_credential_count` the number `ISSUED`, and `lost_credential_count`
    the number `LOST`."

    Design: Difficulty/non_linear_state_machine/credential_issue_return_reissue_cycle
    """
    ctx, r1, r2, f1 = _setup_three_fob_node()
    change = ctx["change"]

    issue_credential(f1["id"], r1["id"])
    node = get_key_node(change["id"])
    assert_node_counts(node, stock=2, issued=1, lost=0)

    resp = api.return_credential(f1["id"], DESK)
    returned = validate_success(resp)
    assert returned["status"] == "IN_STOCK"
    assert returned["holder_person_id"] is None
    assert returned["issued_at"] is None
    assert returned["expires_at"] is None
    node = get_key_node(change["id"])
    assert_node_counts(node, stock=3, issued=0, lost=0)


def test_credential_issue_return_reissue_cycle_new_holder(api):
    """PRD §3.2: "The credential lifecycle is cyclic around stock: returning an
    `ISSUED` credential — again `ERR_CREDENTIAL_NOT_ISSUED` guards the
    precondition — clears `holder_person_id`, `issued_at`, and `expires_at`,
    putting it back to `IN_STOCK` where it may be issued again."
    PRD §3.2: "On success the credential's `holder_person_id` is set to the
    person, `issued_at` to the current logical instant, and `expires_at` exactly
    as supplied for a vendor."

    Design: Difficulty/non_linear_state_machine/credential_issue_return_reissue_cycle
    """
    ctx, r1, r2, f1 = _setup_three_fob_node()

    issue_credential(f1["id"], r1["id"])
    assert get_credential(f1["id"])["status"] == "ISSUED"
    resp = api.return_credential(f1["id"], DESK)
    assert validate_success(resp)["status"] == "IN_STOCK"

    reissued = validate_success(
        api.issue_credential(f1["id"], {"person_id": r2["id"]}, DESK)
    )
    assert reissued["status"] == "ISSUED"
    assert reissued["holder_person_id"] == r2["id"]
    node = get_key_node(ctx["change"]["id"])
    assert_node_counts(node, stock=2, issued=1, lost=0)


# ---------------------------------------------------------------------------
# Difficulty: physical credential pool conservation
# ---------------------------------------------------------------------------

def test_credential_pool_conservation_forward_action(api):
    """PRD §3.1: "Three computed counters describe a node's inventory at any
    moment, counting only credentials pinned to that exact node (never the
    subtree): `stock_credential_count` is the number with `status` `IN_STOCK`,
    `issued_credential_count` the number `ISSUED`, and `lost_credential_count`
    the number `LOST`."

    Design: Difficulty/compensating_invariant/credential_pool_conservation_across_issue_return
    """
    ctx = setup_building_with_chain("Ledger House")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    f1 = create_credential(building["id"], change["id"], "S-1", "FOB")
    create_credential(building["id"], change["id"], "S-2", "FOB")
    create_credential(building["id"], change["id"], "S-3", "FOB")

    node = get_key_node(change["id"])
    assert_node_counts(node, stock=3, issued=0, lost=0)

    issue_credential(f1["id"], r1["id"])
    node = get_key_node(change["id"])
    assert_node_counts(node, stock=2, issued=1, lost=0)
    total = (node["stock_credential_count"] + node["issued_credential_count"]
             + node["lost_credential_count"])
    assert total == 3


def test_credential_pool_conservation_compensating_action_restores_baseline(api):
    """PRD §3.2: "The credential lifecycle is cyclic around stock: returning an
    `ISSUED` credential — again `ERR_CREDENTIAL_NOT_ISSUED` guards the
    precondition — clears `holder_person_id`, `issued_at`, and `expires_at`,
    putting it back to `IN_STOCK` where it may be issued again."
    PRD §3.1: "Three computed counters describe a node's inventory at any
    moment, counting only credentials pinned to that exact node (never the
    subtree): `stock_credential_count` is the number with `status` `IN_STOCK`,
    `issued_credential_count` the number `ISSUED`, and `lost_credential_count`
    the number `LOST`."

    Design: Difficulty/compensating_invariant/credential_pool_conservation_across_issue_return
    """
    ctx = setup_building_with_chain("Ledger House")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    f1 = create_credential(building["id"], change["id"], "S-1", "FOB")
    create_credential(building["id"], change["id"], "S-2", "FOB")
    create_credential(building["id"], change["id"], "S-3", "FOB")

    issue_credential(f1["id"], r1["id"])
    resp = api.return_credential(f1["id"], DESK)
    validate_success(resp)

    node = get_key_node(change["id"])
    assert_node_counts(node, stock=3, issued=0, lost=0)
    total = (node["stock_credential_count"] + node["issued_credential_count"]
             + node["lost_credential_count"])
    assert total == 3
