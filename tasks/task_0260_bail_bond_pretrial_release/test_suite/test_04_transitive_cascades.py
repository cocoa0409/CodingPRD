"""Transitive cascade chains: FTA -> forfeit -> proceeding -> exposure recompute
(depth 4), and exonerate -> collateral release -> held recompute + refund ledger
(depth 3).
"""
from test_helpers import (
    validate_success, validate_paginated,
    setup_active_surety_bond, setup_forfeited_bond,
    find_ledger_entries,
    TEST_USERS,
)

OFFICER = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/fta_forfeit_proceeding_exposure_cascade_depth4
# ---------------------------------------------------------------------------
def test_fta_cascades_courtdate_bond_proceeding(api):
    """PRD 3.5: "Recording a failure to appear advances the date to
    `FAILED_TO_APPEAR`."
    PRD 3.6: "A recorded failure to appear drives the linked bond
    `ACTIVE → FORFEITED` in the same request, provided the bond is currently
    `ACTIVE`. The cascade creates a `ForfeitureProceeding` referencing the bond
    through `bond_id` and the triggering hearing through `trigger_court_date_id`."

    Design: Difficulty/transitive_cascade/fta_forfeit_proceeding_exposure_cascade_depth4
    """
    scen = setup_forfeited_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    cd = validate_success(api.get_court_date(scen["court_date_id"], OFFICER))
    assert cd["status"] == "FAILED_TO_APPEAR", cd["status"]
    bond = validate_success(api.get_bond(scen["bond_id"], OFFICER))
    assert bond["coverage_status"] == "FORFEITED", bond["coverage_status"]
    procs, _ = validate_paginated(api.list_bond_forfeitures(scen["bond_id"], OFFICER))
    assert len(procs) == 1, procs
    assert procs[0]["status"] == "FORFEITED", procs[0]["status"]


def test_fta_keeps_forfeited_bond_in_defendant_exposure(api):
    """PRD 3.6: "Because a forfeited bond remains a live exposure to the agency,
    recording the failure to appear also recomputes the defendant's
    `total_active_exposure_cents`, which deliberately keeps both `ACTIVE` and
    `FORFEITED` bonds in the exposure set."

    Design: Difficulty/transitive_cascade/fta_forfeit_proceeding_exposure_cascade_depth4
    """
    scen = setup_forfeited_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    defendant = validate_success(api.get_defendant(scen["def_id"], OFFICER))
    assert defendant["total_active_exposure_cents"] == 1_000_000, defendant["total_active_exposure_cents"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/exonerate_collateral_release_ledger_cascade_depth3
# ---------------------------------------------------------------------------
def test_exonerate_releases_collateral_and_zeroes_held(api):
    """PRD 3.7: "releases every held collateral item with the per-item refund
    ledger entries described in §3.4."
    PRD 3.4: "On exoneration, every `HELD` item on the bond transitions to
    `RELEASED`, which drives `collateral_held_cents` back down to 0."

    Design: Difficulty/transitive_cascade/exonerate_collateral_release_ledger_cascade_depth3
    """
    scen = setup_active_surety_bond(bail_amount_cents=2_000_000, liability_share_cents=2_000_000,
                                    collateral_value_cents=500_000)
    assert scen["bond"]["collateral_held_cents"] == 500_000, scen["bond"]["collateral_held_cents"]
    exon = validate_success(api.exonerate_bond(scen["def_id"], scen["bond_id"], OFFICER))
    assert exon["collateral_held_cents"] == 0, exon["collateral_held_cents"]
    items, _ = validate_paginated(api.list_collateral(scen["bond_id"], OFFICER))
    assert all(i["status"] == "RELEASED" for i in items), items


def test_exonerate_writes_negative_collateral_refund_ledger(api):
    """PRD 3.4: "the refund for an item is its `pledged_value_cents` reduced by a
    flat processing fee the agency retains, which is 25 dollars (2,500 cents) per
    item, and the result is floored at zero so a small pledge never produces a
    negative refund."
    PRD 3.4: "The corresponding ledger entry is of type `COLLATERAL_REFUND` with an
    `amount_cents` equal to the negative of that per-item refund, reflecting the
    outflow."

    One 500,000c item: refund 497,500; ledger amount_cents == -497500.

    Design: Difficulty/transitive_cascade/exonerate_collateral_release_ledger_cascade_depth3
    """
    scen = setup_active_surety_bond(bail_amount_cents=2_000_000, liability_share_cents=2_000_000,
                                    collateral_value_cents=500_000)
    validate_success(api.exonerate_bond(scen["def_id"], scen["bond_id"], OFFICER))
    entries, _ = validate_paginated(api.list_ledger(scen["bond_id"], OFFICER))
    refunds = find_ledger_entries(entries, "COLLATERAL_REFUND")
    assert len(refunds) == 1, refunds
    assert refunds[0]["amount_cents"] == -497500, refunds[0]["amount_cents"]
