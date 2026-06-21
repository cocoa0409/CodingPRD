"""Ledger cascades and billing posture: declare-loss / reconcile cascades into
the account ledger, conserved-quantity invariants, the PAST_DUE threshold edge,
settlement clearing PAST_DUE, and OCC version increments on visit writes.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    setup_assigned_garment,
    setup_provisional_finalized_visit,
    setup_account_with_loss_charge,
    make_account,
    make_garment_type,
    make_wearer,
    make_garment,
    make_assignment,
    get_account,
    get_garment,
    get_wearer,
    list_account_charges,
    reconcile_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]


# ─── Queue A: transitive_cascade ──────────────────────────────────────────

def test_declare_loss_cascades_charge_ledger_then_past_due(api):
    """PRD §3.4: "Declaring a loss moves the assignment `ASSIGNED → LOST`, stamps
    `closed_at_iso`, drives the garment's `lifecycle_status` to `LOST`, creates a `LOSS`
    `ServiceCharge` against the visit's account computed by the loss-and-damage fee rule
    (cascade hop one), then recomputes the account's `outstanding_cents` and
    `billing_status` (cascade hop two)."
    PRD §3.1: "an account moves from `CURRENT` to `PAST_DUE` only when its
    `outstanding_cents` rises strictly above 500 dollars (that is, above 50,000 cents
    — equality at exactly that figure does not trip the threshold)."

    Design: Difficulty/transitive_cascade/declare_loss_to_charge_to_ledger_to_past_due
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(
        grace=0, replacement_cost_cents=60000, weekly_rate_cents=1000, category="COVERALL"
    )
    validate_success(api.declare_loss(asg["id"], MANAGER), 200)
    garment = get_garment(g["id"])
    assert garment["lifecycle_status"] == "LOST", (
        f"garment lifecycle should be LOST, got {garment['lifecycle_status']}"
    )
    account = get_account(acct["id"])
    assert account["outstanding_cents"] == 60000, (
        f"ledger should hold the 60000 LOSS charge, got {account['outstanding_cents']}"
    )
    assert account["billing_status"] == "PAST_DUE", (
        f"60000 > 50000 must flip billing to PAST_DUE, got {account['billing_status']}"
    )


def test_declare_loss_closes_assignment_and_decrements_count(api):
    """PRD §3.4: "Declaring a loss moves the assignment `ASSIGNED → LOST`, stamps
    `closed_at_iso`, drives the garment's `lifecycle_status` to `LOST`, creates a `LOSS`
    `ServiceCharge` against the visit's account computed by the loss-and-damage fee rule
    (cascade hop one), then recomputes the account's `outstanding_cents` and
    `billing_status` (cascade hop two), decrements the wearer's `assigned_garment_count`
    by one, and increments the assignment's `version`."

    Design: Difficulty/transitive_cascade/declare_loss_to_charge_to_ledger_to_past_due
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(
        grace=0, replacement_cost_cents=60000, weekly_rate_cents=1000, category="COVERALL"
    )
    lost = validate_success(api.declare_loss(asg["id"], MANAGER), 200)
    assert lost["status"] == "LOST", f"assignment must move to LOST, got {lost['status']}"
    wearer_after = get_wearer(wearer["id"])
    assert wearer_after["assigned_garment_count"] == 0, (
        f"the wearer's count must decrement to 0 on loss, got "
        f"{wearer_after['assigned_garment_count']}"
    )


def test_reconcile_supersedes_provisional_in_ledger(api):
    """PRD §3.10: "Reconciliation computes the **finalized** charge into
    `finalized_charge_cents` and supersedes the provisional charges: it deletes the
    provisional `RENTAL` and `SHORTAGE` charge rows for the visit and replaces them with
    finalized `RENTAL` and `SHORTAGE` rows (with `paid` false), then recomputes the
    account's `outstanding_cents` and `billing_status`, and increments the visit's
    `version`."

    Design: Difficulty/transitive_cascade/reconcile_supersede_charges_to_ledger_recompute
    """
    ctx = setup_provisional_finalized_visit(grace=2, weekly_rate_cents=1200,
                                            num_garments=3, num_washed=1, actual_soil_count=1)
    visit = ctx["visit"]
    reconciled = get_success_data(
        api.reconcile_visit(visit["id"], reconcile_payload(ctx["delivered_version"]), ADMIN)
    )
    account = get_account(ctx["account"]["id"])
    assert reconciled["finalized_charge_cents"] == 1200, (
        f"finalized charge should be 1200, got {reconciled['finalized_charge_cents']}"
    )
    assert account["outstanding_cents"] == 1200, (
        f"ledger should drop from provisional 3600 to finalized 1200, got "
        f"{account['outstanding_cents']}"
    )


def test_reconcile_replaces_charge_rows_summing_to_finalized(api):
    """PRD §3.10: "it deletes the provisional `RENTAL` and `SHORTAGE` charge rows for the
    visit and replaces them with finalized `RENTAL` and `SHORTAGE` rows (with `paid`
    false), then recomputes the account's `outstanding_cents` and `billing_status`, and
    increments the visit's `version`."

    Design: Difficulty/transitive_cascade/reconcile_supersede_charges_to_ledger_recompute
    """
    ctx = setup_provisional_finalized_visit(grace=2, weekly_rate_cents=1200,
                                            num_garments=3, num_washed=1, actual_soil_count=1)
    visit = ctx["visit"]
    get_success_data(
        api.reconcile_visit(visit["id"], reconcile_payload(ctx["delivered_version"]), ADMIN)
    )
    # After reconciliation the surviving charge rows must sum to the finalized total (1200),
    # not to the superseded provisional total (3600).
    charges = list_account_charges(ctx["account"]["id"])
    unpaid_total = sum(c["amount_cents"] for c in charges if not c["paid"])
    assert unpaid_total == 1200, (
        f"surviving charge rows must sum to the finalized 1200, not the provisional 3600; "
        f"got {unpaid_total}"
    )


# ─── Queue A: compensating_invariant ──────────────────────────────────────

def test_reconcile_conserves_ledger_to_finalized_total(api):
    """PRD §3.10: "The net account ledger after reconciliation must equal the finalized
    total — the provisional figures are fully compensated out."

    Design: Difficulty/compensating_invariant/reconcile_ledger_conserved_to_finalized_total
    """
    ctx = setup_provisional_finalized_visit(grace=2, weekly_rate_cents=1200,
                                            num_garments=3, num_washed=1, actual_soil_count=1)
    visit = ctx["visit"]
    reconciled = get_success_data(
        api.reconcile_visit(visit["id"], reconcile_payload(ctx["delivered_version"]), ADMIN)
    )
    account = get_account(ctx["account"]["id"])
    assert account["outstanding_cents"] == 1200, (
        f"outstanding should equal finalized total, got {account['outstanding_cents']}"
    )
    assert account["outstanding_cents"] == reconciled["finalized_charge_cents"], (
        "outstanding_cents must equal the visit's finalized_charge_cents with no "
        "provisional residue"
    )


def test_reconcile_leaves_no_provisional_residue_in_ledger(api):
    """PRD §3.10: "The net account ledger after reconciliation must equal the finalized
    total — the provisional figures are fully compensated out."

    Design: Difficulty/compensating_invariant/reconcile_ledger_conserved_to_finalized_total
    """
    ctx = setup_provisional_finalized_visit(grace=2, weekly_rate_cents=1200,
                                            num_garments=3, num_washed=1, actual_soil_count=1)
    visit = ctx["visit"]
    # Confirm the provisional total was on the ledger before the compensating action.
    before = get_account(ctx["account"]["id"])
    assert before["outstanding_cents"] == 3600, (
        f"the provisional 3600 should be on the ledger pre-reconcile, got "
        f"{before['outstanding_cents']}"
    )
    get_success_data(
        api.reconcile_visit(visit["id"], reconcile_payload(ctx["delivered_version"]), ADMIN)
    )
    after = get_account(ctx["account"]["id"])
    # The provisional 3600 is fully compensated out, leaving exactly the finalized 1200.
    assert after["outstanding_cents"] == 1200, (
        f"the provisional figure must be fully compensated out, leaving 1200, got "
        f"{after['outstanding_cents']}"
    )


def test_return_conserves_assigned_garment_count(api):
    """PRD §3.4: "Returning a garment moves the assignment `ASSIGNED → RETURNED`, stamps
    `closed_at_iso`, drives the garment back `ASSIGNED → IN_STOCK` (and its `wash_location`
    back to `AT_PLANT`), decrements the wearer's `assigned_garment_count` by one, and
    increments the assignment's `version`."

    Design: Difficulty/compensating_invariant/return_conserves_garment_assigned_count
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(grace=0)
    # Forward action set assigned_garment_count to 1 and garment ASSIGNED.
    before = get_wearer(wearer["id"])
    assert before["assigned_garment_count"] == 1, (
        f"assignment should have raised count to 1, got {before['assigned_garment_count']}"
    )
    returned = validate_success(api.return_assignment(asg["id"], MANAGER), 200)
    assert returned["status"] == "RETURNED", f"assignment should be RETURNED, got {returned['status']}"
    after_wearer = get_wearer(wearer["id"])
    after_garment = get_garment(g["id"])
    assert after_wearer["assigned_garment_count"] == 0, (
        f"return must decrement count back to 0, got {after_wearer['assigned_garment_count']}"
    )
    assert after_garment["lifecycle_status"] == "IN_STOCK", (
        f"return must restore garment to IN_STOCK, got {after_garment['lifecycle_status']}"
    )


def test_return_restores_garment_wash_location_to_plant(api):
    """PRD §3.4: "Returning a garment moves the assignment `ASSIGNED → RETURNED`, stamps
    `closed_at_iso`, drives the garment back `ASSIGNED → IN_STOCK` (and its `wash_location`
    back to `AT_PLANT`), decrements the wearer's `assigned_garment_count` by one, and
    increments the assignment's `version`."

    Design: Difficulty/compensating_invariant/return_conserves_garment_assigned_count
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(grace=0)
    # After assignment the garment is AT_CUSTOMER; return must drive it back to AT_PLANT.
    validate_success(api.return_assignment(asg["id"], MANAGER), 200)
    garment = get_garment(g["id"])
    assert garment["wash_location"] == "AT_PLANT", (
        f"return must reset wash_location to AT_PLANT, got {garment['wash_location']}"
    )


# ─── Queue A: boundary_precision_check ────────────────────────────────────

def test_outstanding_exactly_at_threshold_stays_current(api):
    """PRD §3.1: "an account moves from `CURRENT` to `PAST_DUE` only when its
    `outstanding_cents` rises strictly above 500 dollars (that is, above 50,000 cents
    — equality at exactly that figure does not trip the threshold)."

    Design: Difficulty/boundary_precision_check/past_due_threshold_strictly_greater_than
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(
        grace=0, replacement_cost_cents=50000, weekly_rate_cents=1000, category="COVERALL"
    )
    validate_success(api.declare_loss(asg["id"], MANAGER), 200)
    account = get_account(acct["id"])
    assert account["outstanding_cents"] == 50000, (
        f"a single 50000 LOSS should leave outstanding at exactly 50000, got "
        f"{account['outstanding_cents']}"
    )
    assert account["billing_status"] == "CURRENT", (
        f"outstanding == 50000 is not strictly above the threshold, must stay CURRENT, "
        f"got {account['billing_status']}"
    )


def test_outstanding_one_cent_above_threshold_flips_past_due(api):
    """PRD §3.1: "an account moves from `CURRENT` to `PAST_DUE` only when its
    `outstanding_cents` rises strictly above 500 dollars (that is, above 50,000 cents
    — equality at exactly that figure does not trip the threshold)."

    Design: Difficulty/boundary_precision_check/past_due_threshold_strictly_greater_than
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(
        grace=0, replacement_cost_cents=50001, weekly_rate_cents=1000, category="COVERALL"
    )
    validate_success(api.declare_loss(asg["id"], MANAGER), 200)
    account = get_account(acct["id"])
    assert account["outstanding_cents"] == 50001, (
        f"a single 50001 LOSS should leave outstanding at 50001, got "
        f"{account['outstanding_cents']}"
    )
    assert account["billing_status"] == "PAST_DUE", (
        f"50001 is strictly above the 50000 threshold, must flip to PAST_DUE, got "
        f"{account['billing_status']}"
    )


# ─── Queue B: settlement clears PAST_DUE ──────────────────────────────────

def test_settle_charge_clears_past_due(api):
    """PRD §3.11: "A settlement that clears enough debt to bring `outstanding_cents` to
    or below 50,000 cents drives the account's `billing_status` from `PAST_DUE` back to
    `CURRENT` and increments the account's `version`."

    Design: Corner/endpoints/settle_charge_clears_past_due
    """
    acct, wearer, gt, g, asg = setup_account_with_loss_charge(replacement_cost_cents=60000)
    charges = list_account_charges(acct["id"])
    assert len(charges) == 1, f"expected the sole LOSS charge, got {len(charges)}"
    charge = charges[0]
    settled = validate_success(api.settle_charge(charge["id"], ADMIN), 200)
    assert settled["paid"] is True, "settled charge must have paid == true"
    account = get_account(acct["id"])
    assert account["outstanding_cents"] == 0, (
        f"settling the only charge must zero outstanding, got {account['outstanding_cents']}"
    )
    assert account["billing_status"] == "CURRENT", (
        f"clearing debt below threshold must restore CURRENT, got {account['billing_status']}"
    )


def test_settle_already_paid_charge_rejected(api):
    """PRD §3.11: "An administrator settles a charge to mark it paid; settling a charge
    that is already paid is rejected with `ERR_CHARGE_ALREADY_SETTLED`."

    Design: Corner/errors/charge_already_settled_rejected
    """
    acct, wearer, gt, g, asg = setup_account_with_loss_charge(replacement_cost_cents=8000)
    charge = list_account_charges(acct["id"])[0]
    validate_success(api.settle_charge(charge["id"], ADMIN), 200)
    res = api.settle_charge(charge["id"], ADMIN)
    validate_error(res, "ERR_CHARGE_ALREADY_SETTLED")


# ─── Queue B: consistency_model ───────────────────────────────────────────

def test_assignment_side_effects_visible_immediately(api):
    """PRD §3.4: "the assignment is created in `ASSIGNED` status, the garment's
    `lifecycle_status` advances `IN_STOCK → ASSIGNED` while its `wash_location`
    simultaneously advances `AT_PLANT → AT_CUSTOMER`, the wearer's
    `assigned_garment_count` increments by one, and the garment's `version` increments
    by one."

    Design: Corner/consistency_model/assignment_side_effects_visible_same_request
    """
    acct = make_account()
    gt = make_garment_type()
    wearer = make_wearer(acct["id"])
    g = make_garment(acct["id"], gt["id"])
    make_assignment(g["id"], wearer["id"])
    # A read immediately afterward must reflect both side effects with no lag.
    fetched_wearer = get_wearer(wearer["id"])
    fetched_garment = get_garment(g["id"])
    assert fetched_wearer["assigned_garment_count"] == 1, (
        f"wearer count should be 1 immediately, got {fetched_wearer['assigned_garment_count']}"
    )
    assert fetched_garment["lifecycle_status"] == "ASSIGNED", (
        f"garment should be ASSIGNED immediately, got {fetched_garment['lifecycle_status']}"
    )


# ─── Queue B: OCC version increments ──────────────────────────────────────

def test_visit_version_advances_make_create_time_version_stale(api):
    """PRD §2.7: "The server compares that value to the visit's current `version`. If
    they differ — that is, if another writer has advanced the visit's `version` since the
    client read it — the reconciliation is rejected with `ERR_STALE_VISIT_VERSION` and
    HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_visit_write
    """
    ctx = setup_provisional_finalized_visit(grace=5, weekly_rate_cents=1000,
                                            num_garments=1, num_washed=1, actual_soil_count=1)
    visit = ctx["visit"]
    # The visit's version was 1 at creation; pickup and deliver each advanced it, so a
    # reconcile against version 1 is stale.
    res = api.reconcile_visit(visit["id"], reconcile_payload(1), ADMIN)
    validate_error(res, "ERR_STALE_VISIT_VERSION", expected_status=412)
