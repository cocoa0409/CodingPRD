"""Multi-link cascades: finalization, posting and manifest rejection."""
from test_helpers import (
    assert_intake,
    assert_intake_mass_conservation,
    assert_recovery_lot,
    assert_settlement,
    fixtures as fx,
    validate_paginated,
    validate_success,
)

_TWO_TRIAGEABLE_MODULES = (
    {
        "serial_code": "M-S",
        "mass_kg": 100.0,
        "min_cell_capacity_pct": 76.0,
        "mean_cell_capacity_pct": 78.0,
        "cycle_count": 400,
    },
    {
        "serial_code": "M-V",
        "mass_kg": 100.0,
        "min_cell_capacity_pct": 58.0,
        "mean_cell_capacity_pct": 62.0,
        "cycle_count": 1200,
    },
)


# --------------------------------------------------------------------------
# Finalization: lot -> module -> settlement -> supplier, plus the bubble-up
# --------------------------------------------------------------------------

def test_finalization_writes_the_reconciliation_and_consumes_the_charged_module(api):
    """The first two links of the finalization cascade reconcile the lot's mass and
    move every charged module to CONSUMED.

    PRD §3.7: "The second link fires because the lot became `FINALIZED`: every module
    whose `lot_id` is this lot and whose `status` is `CHARGED` moves
    `CHARGED → CONSUMED`."

    Design: Difficulty/transitive_cascade/finalize_lot_four_link_cascade_to_supplier_quality_strike
    """
    ctx = fx.finalized_lot(api)
    lot = ctx["lot"]

    assert_recovery_lot(lot)
    assert lot["status"] == "FINALIZED"
    assert float(lot["charged_mass_kg"]) == 100.000
    assert float(lot["recovered_mass_kg"]) == 30.000
    assert float(lot["residue_mass_kg"]) == 67.0
    assert float(lot["accounted_mass_kg"]) == 97.000
    assert float(lot["unaccounted_mass_kg"]) == 3.000
    assert float(lot["mass_balance_pct"]) == 97.00
    assert float(lot["recycled_content_pct"]) == 30.00

    module = validate_success(api.get_module(ctx["modules"][0]["id"], fx.OPERATOR))
    assert module["status"] == "CONSUMED"


def test_finalization_reprices_the_settlement_and_strikes_the_counterparty(api):
    """The third link re-prices the contributing settlement and the fourth adds a
    quality strike because the assay variance exceeds two percentage points; the
    campaign then closes itself.

    PRD §3.7: "for any settlement that lands in `FINAL` with a `max_variance_pp`
    strictly greater than 2.00 percentage points, that supplier's
    `quality_strike_count` increases by 1"

    Design: Difficulty/transitive_cascade/finalize_lot_four_link_cascade_to_supplier_quality_strike
    """
    ctx = fx.finalized_lot(api)
    settlement = fx.read_settlement(api, ctx["settlement"]["id"])

    assert_settlement(settlement)
    assert settlement["variant"] == "FINAL"
    assert settlement["state"] == "DRAFT"
    assert settlement["gross_cents"] == 36750
    assert settlement["processing_fee_cents"] == 4410
    assert settlement["pre_surcharge_net_cents"] == 32340
    assert settlement["hazmat_surcharge_cents"] == 1617
    assert settlement["net_payable_cents"] == 30723
    assert float(settlement["max_variance_pp"]) == 18.00

    supplier = fx.read_supplier(api, ctx["supplier"]["id"])
    assert supplier["quality_strike_count"] == 1

    campaign = validate_success(
        api.get_campaign(ctx["campaign"]["id"], fx.OPERATOR)
    )
    assert campaign["status"] == "CLOSED", (
        "the campaign bubbles up to CLOSED once its last non-terminal lot is terminal"
    )
    assert float(campaign["committed_input_kg"]) == 100.000

    intake = fx.read_intake(api, ctx["intake"]["id"])
    assert float(intake["assigned_mass_kg"]) == 100.0
    assert float(intake["unassigned_mass_kg"]) == 0.0


def test_provisional_payable_is_replaced_rather_than_added_to(api):
    """The shipment carries exactly one settlement, whose provisional figure is
    superseded by the final re-pricing.

    PRD §3.5: "Release also **cuts a settlement**, as a cascade-created child that
    never appears in the release response."

    Design: Difficulty/transitive_cascade/finalize_lot_four_link_cascade_to_supplier_quality_strike
    """
    ctx = fx.released_intake(api)
    provisional = fx.read_settlement(api, ctx["settlement"]["id"])
    assert provisional["variant"] == "PROVISIONAL"
    assert provisional["net_payable_cents"] == 10674

    fx.advance_processing(ctx)
    settlements, meta = validate_paginated(
        api.list_settlements(fx.ACCOUNTANT, params={"intake_id": ctx["intake"]["id"]})
    )
    assert meta["total_count"] == 1
    assert settlements[0]["id"] == provisional["id"]
    assert settlements[0]["variant"] == "FINAL"
    assert settlements[0]["net_payable_cents"] == 30723


# --------------------------------------------------------------------------
# Posting: settlement -> supplier balance -> credit hold -> quarantine
# --------------------------------------------------------------------------

def test_posting_freezes_the_amount_and_raises_the_credit_hold(api):
    """Posting freezes the payable figure on the settlement and pushes the
    counterparty's balance past its credit limit.

    PRD §3.9: "The first link freezes `posted_amount_cents` at the current
    `net_payable_cents` — from this point on, the payable ledger is driven by the
    frozen figure, not by the live calculation."

    Design: Difficulty/transitive_cascade/post_settlement_four_link_cascade_to_intake_quarantine
    """
    ctx = fx.credit_hold_world(api)

    settlement = ctx["settlement"]
    assert settlement["state"] == "POSTED"
    assert settlement["posted_amount_cents"] == 30723
    assert settlement["net_payable_cents"] == 30723

    supplier = ctx["supplier"]
    assert supplier["payable_balance_cents"] == 30723
    assert supplier["credit_limit_cents"] == 20_000
    assert supplier["credit_hold"] is True
    assert supplier["paid_to_date_cents"] == 0


def test_credit_hold_quarantines_only_shipments_still_in_received(api):
    """The fourth link catches the shipment that has not passed the identification
    bench and leaves the released one alone.

    PRD §3.9: "every shipment of that supplier whose `custody_state` is `RECEIVED`
    moves to `QUARANTINED` with `hold_reason` set to `SUPPLIER_CREDIT_HOLD`. Only
    shipments still sitting in `RECEIVED` are caught"

    Design: Difficulty/transitive_cascade/post_settlement_four_link_cascade_to_intake_quarantine
    """
    ctx = fx.credit_hold_world(api)

    second = ctx["second_intake"]
    assert_intake(second)
    assert second["custody_state"] == "QUARANTINED"
    assert second["hold_reason"] == "SUPPLIER_CREDIT_HOLD"
    assert second["identified_chemistry"] is None

    first = ctx["first_intake"]
    assert first["custody_state"] == "RELEASED"
    assert first["hold_reason"] is None


# --------------------------------------------------------------------------
# Manifest rejection: manifest -> compliance -> custody -> decisions/modules
# --------------------------------------------------------------------------

def _rejected_manifest_world(api):
    """A packaged shipment with a submitted manifest and two graded modules, whose
    manifest the inspector then rejects."""
    ctx = fx.build_world(
        api,
        stop_after="manifest",
        intake={
            "intake": {"gross_mass_kg": 250.0, "packaging_tare_kg": 50.0},
            "modules": _TWO_TRIAGEABLE_MODULES,
            "manifest": {"un_number": "UN3481"},
        },
    )
    ctx["decisions"] = [
        fx.triage_module(api, module["id"]) for module in ctx["modules"]
    ]
    ctx["rejected"] = fx.reject_manifest(
        api,
        ctx["intake"]["id"],
        ctx["manifest"]["id"],
        "Packing group inconsistent with UN3481 declaration",
    )
    return ctx


def test_manifest_rejection_quarantines_the_shipment_on_both_dimensions(api):
    """The first two links flip the manifest to REJECTED and drive the shipment's
    custody dimension into quarantine with a paperwork hold reason.

    PRD §3.3: "The second link fires *because* the compliance dimension changed: the
    shipment's `custody_state`, which at this point is `IDENTIFIED`, `DISCHARGED` or
    `PACKAGED`, moves to `QUARANTINED` and its `hold_reason` is set to
    `MANIFEST_REJECTED`."

    Design: Difficulty/transitive_cascade/manifest_reject_three_link_cascade_voids_triage_decisions
    """
    ctx = _rejected_manifest_world(api)

    manifest = ctx["rejected"]
    assert manifest["status"] == "REJECTED"
    assert manifest["rejection_reason"] == "Packing group inconsistent with UN3481 declaration"
    assert manifest["revision"] == 1

    intake = fx.read_intake(api, ctx["intake"]["id"])
    assert intake["compliance_state"] == "MANIFEST_REJECTED"
    assert intake["custody_state"] == "QUARANTINED"
    assert intake["hold_reason"] == "MANIFEST_REJECTED"


def test_manifest_rejection_voids_the_triage_decisions_it_reaches(api):
    """The third link voids every active decision on the shipment's modules and
    returns those modules to the pending-triage queue with their scores cleared.

    PRD §3.3: "every triage decision on that shipment's modules whose `status` is
    `ACTIVE` becomes `VOIDED`, and each module so affected reverts to
    `PENDING_TRIAGE` with its `second_life_score` and `grade` reset to null"

    Design: Difficulty/transitive_cascade/manifest_reject_three_link_cascade_voids_triage_decisions
    """
    ctx = _rejected_manifest_world(api)

    for module in ctx["modules"]:
        stored = validate_success(api.get_module(module["id"], fx.ENGINEER))
        assert stored["status"] == "PENDING_TRIAGE"
        assert stored["second_life_score"] is None
        assert stored["grade"] is None

        decisions, meta = validate_paginated(
            api.list_triage_decisions(module["id"], fx.ENGINEER)
        )
        assert meta["total_count"] == 1
        assert decisions[0]["status"] == "VOIDED"

    intake = fx.read_intake(api, ctx["intake"]["id"])
    assert float(intake["module_mass_total_kg"]) == 200.0
    assert float(intake["assigned_mass_kg"]) == 0.0
    assert_intake_mass_conservation(intake)
