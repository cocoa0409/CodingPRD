"""Difficulty queue - rule compensating_invariant.

Two counter pairs that must survive a forward-then-inverse walk unchanged: the
settlement obligation counters of a closure plan under ALLOCATE/REVERSE, and the
depth-weighted nested exposure rollup under CONFIRM/SUSPEND/LIFT/REVERT.
"""
from test_helpers import (
    ApiErrorId,
    add_control_rows,
    add_nested,
    add_verified_owner,
    adjudicate_nested,
    approve_plan,
    calibrate,
    committee_decision,
    corridor,
    draft_plan,
    licensed_respondent,
    lift,
    new_jurisdiction,
    new_respondent,
    open_profile,
    open_questionnaire,
    overlay_row,
    read_nested,
    read_plan,
    read_profile,
    read_respondent,
    restrict,
    score_respondent,
    submit_plan,
    submit_questionnaire,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANALYST, OFFICER, RM, assess_questionnaire


DOMAINS = [
    "GOVERNANCE", "KYC_ONBOARDING", "TRANSACTION_MONITORING", "SANCTIONS_SCREENING",
    "PEP_HANDLING", "TRAINING", "AUDIT", "NESTED_CONTROLS",
]

ORIGINAL_OBLIGATION_CENTS = 12000000


def _flat_score(rid, rating=3, overlay=None):
    questionnaire = open_questionnaire(rid, version="V1")
    rows = add_control_rows(questionnaire["id"], rid, {d: rating for d in DOMAINS})
    submit_questionnaire(questionnaire["id"], rid)
    for domain, assessed in (overlay or {}).items():
        overlay_row(rows[domain]["id"], assessed_rating=assessed)
    assess_questionnaire(questionnaire["id"], "ONBOARDING_PROVISIONAL")
    return score_respondent(rid, "ONBOARDING_PROVISIONAL")


def _settlement_scenario():
    """Approved plan over three corridors expecting 3000000.00 / 2000000.00 / 2000000.00,
    deliberately supplied out of sort order, with a 12000000 cent obligation."""
    de = new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0,
        corridor_risk_weight=1.00, max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    at = new_jurisdiction(
        jurisdiction_code="AT", name="Austria", basel_aml_index=3.0,
        corridor_risk_weight=1.00,
    )["jurisdiction_code"]
    ch = new_jurisdiction(
        jurisdiction_code="CH", name="Switzerland", basel_aml_index=3.0,
        corridor_risk_weight=1.00,
    )["jurisdiction_code"]

    respondent = licensed_respondent(
        de, legal_name="Dortmund Korrespondenzbank AG",
        expected_monthly_volume_usd=7000000.00, expected_monthly_count=200,
    )
    rid = respondent["id"]
    add_verified_owner(rid, de, owner_name="Dortmund Holding", ownership_pct=100.00)
    scored = _flat_score(rid)
    assert scored["control_score"] == 60.00
    assert scored["control_credit"] == 0.2250
    assert scored["inherent_risk_score"] == 14.00  # 8.00 + 0 + 0 + 6
    assert scored["residual_risk_score"] == 10.85
    assert scored["risk_rating"] == "LOW"
    committee_decision(rid, "APPROVE")

    profile = open_profile(
        rid,
        [corridor(at, 2000000.00, 60), corridor(de, 3000000.00, 100),
         corridor(ch, 2000000.00, 40)],
        tolerance_pct=0.00,
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z",
    )
    calibrate(profile["id"])
    calibrated = read_profile(profile["id"])
    assert calibrated["calibration_state"] == "CALIBRATED"
    # Payload order is preserved on the thresholds; only ALLOCATE ever sorts.
    assert [entry["jurisdiction_code"] for entry in calibrated["corridor_thresholds"]] == [
        at, de, ch
    ]
    assert calibrated["aggregate_usd_threshold"] == 10010000.00

    plan = draft_plan(
        rid, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=ORIGINAL_OBLIGATION_CENTS,
    )
    submit_plan(plan["id"])
    approved = approve_plan(plan["id"])
    assert approved["state"] == "APPROVED"
    assert approved["notice_period_days"] == 105  # 90 base + 15 for the obligation
    assert approved["wind_down_cap_usd"] == 14700000.00
    assert approved["outstanding_obligation_cents"] == ORIGINAL_OBLIGATION_CENTS
    assert approved["settled_cents"] == 0
    assert approved["allocation_round"] == 0
    return {"de": de, "at": at, "ch": ch, "rid": rid, "plan": approved}


def _assert_conserved(plan):
    """The two invariants the specification states hold after every allocation and
    every reversal."""
    outstanding = plan["outstanding_obligation_cents"]
    assert outstanding + plan["settled_cents"] == ORIGINAL_OBLIGATION_CENTS
    assert 0 <= outstanding <= ORIGINAL_OBLIGATION_CENTS


def _lines(plan):
    return [(entry["jurisdiction_code"], entry["line_cents"]) for entry in
            plan["allocation_lines"]]


def test_the_whole_allocation_residue_lands_on_the_largest_corridor_in_both_signs(api):
    """5000000 cents leaves a +1 residue and 2 cents leaves a -1 residue against the same
    unsorted corridor set, and both residues go entirely onto the DE line - the largest
    expected volume - never spread across the two 2000000.00 corridors.

    Design: Difficulty/compensating_invariant/obligation_counters_are_conserved_across_allocate_reverse_with_the_residue_pinned_to_the_largest_corridor
    """
    scenario = _settlement_scenario()
    plan_id = scenario["plan"]["id"]

    first = validate_success(
        api.allocate_settlement(
            plan_id, {"action": "ALLOCATE", "amount_cents": 5000000}, RM
        )
    )
    # raw 2142857.14 / 1428571.43 / 1428571.43 -> 2142857 + 1428571 + 1428571 = 4999999,
    # residue +1 onto the first line in sort order.
    assert _lines(first) == [
        (scenario["de"], 2142858), (scenario["at"], 1428571), (scenario["ch"], 1428571)
    ]
    assert sum(entry["line_cents"] for entry in first["allocation_lines"]) == 5000000
    assert first["outstanding_obligation_cents"] == 7000000
    assert first["settled_cents"] == 5000000
    assert first["allocation_round"] == 1
    assert first["last_allocated_cents"] == 5000000
    _assert_conserved(first)

    second = validate_success(
        api.allocate_settlement(plan_id, {"action": "ALLOCATE", "amount_cents": 2}, RM)
    )
    # raw 0.857142 / 0.571428 / 0.571428 -> 1 + 1 + 1 = 3, residue -1 onto the DE line.
    assert _lines(second) == [
        (scenario["de"], 0), (scenario["at"], 1), (scenario["ch"], 1)
    ]
    assert sum(entry["line_cents"] for entry in second["allocation_lines"]) == 2
    assert second["outstanding_obligation_cents"] == 6999998
    assert second["settled_cents"] == 5000002
    assert second["allocation_round"] == 2
    assert second["last_allocated_cents"] == 2
    _assert_conserved(second)

    assert read_plan(plan_id)["state"] == "APPROVED"


def test_reversal_guards_hold_and_the_obligation_counters_return_to_their_start(api):
    """The reversal guards are checked against live counters at every step - no round to
    reverse, then a mismatched amount, then a mismatch again because the successful
    reversal zeroed `last_allocated_cents` - and the full round trip conserves the pair.

    Design: Difficulty/compensating_invariant/obligation_counters_are_conserved_across_allocate_reverse_with_the_residue_pinned_to_the_largest_corridor
    """
    scenario = _settlement_scenario()
    plan_id = scenario["plan"]["id"]

    validate_error(
        api.allocate_settlement(
            plan_id, {"action": "REVERSE", "amount_cents": 5000000}, RM
        ),
        ApiErrorId.ERR_NO_ALLOCATION_TO_REVERSE,
    )
    _assert_conserved(read_plan(plan_id))

    validate_success(
        api.allocate_settlement(
            plan_id, {"action": "ALLOCATE", "amount_cents": 5000000}, RM
        )
    )
    validate_success(
        api.allocate_settlement(plan_id, {"action": "ALLOCATE", "amount_cents": 2}, RM)
    )

    # last_allocated_cents is 2, so the earlier round's amount no longer reverses.
    validate_error(
        api.allocate_settlement(
            plan_id, {"action": "REVERSE", "amount_cents": 5000000}, RM
        ),
        ApiErrorId.ERR_REVERSAL_AMOUNT_MISMATCH,
    )

    reversed_plan = validate_success(
        api.allocate_settlement(plan_id, {"action": "REVERSE", "amount_cents": 2}, RM)
    )
    assert reversed_plan["outstanding_obligation_cents"] == 7000000
    assert reversed_plan["settled_cents"] == 5000000
    assert reversed_plan["allocation_round"] == 1
    assert reversed_plan["last_allocated_cents"] == 0
    _assert_conserved(reversed_plan)

    # A round remains, but last_allocated_cents is 0, so any positive amount mismatches.
    validate_error(
        api.allocate_settlement(
            plan_id, {"action": "REVERSE", "amount_cents": 5000000}, RM
        ),
        ApiErrorId.ERR_REVERSAL_AMOUNT_MISMATCH,
    )
    validate_error(
        api.allocate_settlement(
            plan_id, {"action": "ALLOCATE", "amount_cents": 7000001}, RM
        ),
        ApiErrorId.ERR_SETTLEMENT_EXCEEDS_OUTSTANDING,
    )
    _assert_conserved(read_plan(plan_id))

    final = validate_success(
        api.allocate_settlement(
            plan_id, {"action": "ALLOCATE", "amount_cents": 7000000}, RM
        )
    )
    # An exact multiple of the corridor split leaves no residue at all.
    assert _lines(final) == [
        (scenario["de"], 3000000), (scenario["at"], 2000000), (scenario["ch"], 2000000)
    ]
    assert final["outstanding_obligation_cents"] == 0
    assert final["settled_cents"] == ORIGINAL_OBLIGATION_CENTS
    assert final["allocation_round"] == 2
    assert final["last_allocated_cents"] == 7000000
    _assert_conserved(final)
    assert read_plan(plan_id)["state"] == "APPROVED"


def _nested_chain():
    """Respondent M with a depth-2 edge into respondent Z and a depth-1 leaf edge, both
    DISCLOSED, so the baseline rollup is 1*2 + 1*1 = 3 units."""
    de = new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0,
        corridor_risk_weight=1.00, max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    at = new_jurisdiction(
        jurisdiction_code="AT", name="Austria", basel_aml_index=3.0,
        corridor_risk_weight=1.00, nested_correspondent_prohibited=False,
    )["jurisdiction_code"]
    ch = new_jurisdiction(
        jurisdiction_code="CH", name="Switzerland", basel_aml_index=3.0,
        corridor_risk_weight=1.00, nested_correspondent_prohibited=False,
    )["jurisdiction_code"]

    # Z stays a PROSPECT; it exists only to lengthen M's chain by one hop.
    downstream = new_respondent(
        at, legal_name="Wien Zwischenbank AG", nested_activity_permitted=True
    )
    zid = downstream["id"]
    add_nested(zid, ch, downstream_institution_name="Zurich Leaf Bank")
    assert read_respondent(zid)["nested_exposure_units"] == 1  # 1 * depth 1

    respondent = licensed_respondent(
        de, legal_name="Muenster Korrespondenzbank AG",
        expected_monthly_volume_usd=5000000.00, expected_monthly_count=150,
        nested_activity_permitted=True,
    )
    rid = respondent["id"]
    add_verified_owner(rid, de, owner_name="Muenster Holding", ownership_pct=100.00)

    first = add_nested(
        rid, at, downstream_institution_name="Wien Zwischenbank AG",
        downstream_respondent_bank_id=zid,
    )
    second = add_nested(rid, ch, downstream_institution_name="Zurich Leaf Bank")
    assert first["state"] == "DISCLOSED"
    assert first["depth"] == 2  # 1 + one hop through Z's own live row
    assert second["state"] == "DISCLOSED"
    assert second["depth"] == 1

    baseline = read_respondent(rid)
    assert baseline["nested_exposure_units"] == 3
    assert baseline["disclosed_nested_count"] == 2
    assert baseline["undisclosed_nested_count"] == 0
    assert baseline["max_nested_depth"] == 2

    scored = _flat_score(rid, 3, overlay={"NESTED_CONTROLS": 3})
    assert scored["control_score"] == 60.00
    assert scored["inherent_risk_score"] == 24.00  # 8.00 + 0 + min(20, 8) + min(16, 6+2)
    assert scored["residual_risk_score"] == 18.60  # round(24.00*0.7750, 2)
    assert scored["risk_rating"] == "LOW"
    committee_decision(rid, "APPROVE")
    return {"rid": rid, "zid": zid, "first": first, "second": second}


def test_confirming_both_edges_adds_twice_the_depth_and_suspension_freezes_the_total(api):
    """Each CONFIRM from DISCLOSED moves that row's weight from 1 to 3, so the rollup
    climbs by twice the row's own depth - 4 for the depth-2 edge and 2 for the leaf - and
    the restriction cascade then suspends both rows without moving the total at all.

    Design: Difficulty/compensating_invariant/nested_exposure_units_survive_a_confirm_suspend_lift_revert_round_trip_with_depth_weighted_deltas
    """
    scenario = _nested_chain()
    rid = scenario["rid"]

    adjudicate_nested(scenario["first"]["id"], "CONFIRM")
    assert read_respondent(rid)["nested_exposure_units"] == 7  # 3*2 + 1*1

    adjudicate_nested(scenario["second"]["id"], "CONFIRM")
    confirmed = read_respondent(rid)
    assert confirmed["nested_exposure_units"] == 9  # 3*2 + 3*1
    assert confirmed["disclosed_nested_count"] == 2  # CONFIRMED still counts as disclosed
    assert confirmed["max_nested_depth"] == 2

    restricted = restrict(rid, "OFFICER_ACTION", payment_posture="SCREEN_ONLY")
    assert restricted["dd_state"] == "RESTRICTED"
    assert restricted["payment_posture"] == "SCREEN_ONLY"

    assert read_nested(scenario["first"]["id"])["state"] == "SUSPENDED"
    assert read_nested(scenario["second"]["id"])["state"] == "SUSPENDED"

    suspended = read_respondent(rid)
    assert suspended["nested_exposure_units"] == 9  # SUSPENDED shares weight 3
    assert suspended["disclosed_nested_count"] == 0  # but no longer counts as disclosed
    assert suspended["undisclosed_nested_count"] == 0
    assert suspended["max_nested_depth"] == 2  # suspended rows still carry the depth

    # The downstream respondent is untouched by anything happening upstream of it.
    assert read_respondent(scenario["zid"])["nested_exposure_units"] == 1


def test_lift_and_revert_walk_the_exposure_rollup_back_to_the_disclosed_baseline(api):
    """The compensating pair: the lift restores CONFIRMED without moving the units, then
    each REVERT gives back exactly twice its own depth, so every rollup field ends at its
    pre-confirmation value while the risk scores - frozen at approval - never move.

    Design: Difficulty/compensating_invariant/nested_exposure_units_survive_a_confirm_suspend_lift_revert_round_trip_with_depth_weighted_deltas
    """
    scenario = _nested_chain()
    rid = scenario["rid"]
    adjudicate_nested(scenario["first"]["id"], "CONFIRM")
    adjudicate_nested(scenario["second"]["id"], "CONFIRM")
    restrict(rid, "OFFICER_ACTION", payment_posture="SCREEN_ONLY")

    lifted = lift(rid)
    assert lifted["dd_state"] == "APPROVED"
    assert lifted["restriction_reason"] is None
    assert lifted["payment_posture"] == "SCREEN_ONLY"
    assert read_nested(scenario["first"]["id"])["state"] == "CONFIRMED"
    assert read_nested(scenario["second"]["id"])["state"] == "CONFIRMED"

    after_lift = read_respondent(rid)
    assert after_lift["nested_exposure_units"] == 9
    assert after_lift["disclosed_nested_count"] == 2

    reverted = adjudicate_nested(scenario["first"]["id"], "REVERT")
    assert reverted["state"] == "DISCLOSED"
    assert reverted["depth"] == 2
    assert read_respondent(rid)["nested_exposure_units"] == 5  # 1*2 + 3*1

    adjudicate_nested(scenario["second"]["id"], "REVERT")

    final = read_respondent(rid)
    assert final["nested_exposure_units"] == 3  # exactly the baseline
    assert final["disclosed_nested_count"] == 2
    assert final["undisclosed_nested_count"] == 0
    assert final["max_nested_depth"] == 2
    assert final["inherent_risk_score"] == 24.00  # adjudication never re-scores
    assert final["residual_risk_score"] == 18.60
    assert final["risk_rating"] == "LOW"
    assert read_respondent(scenario["zid"])["nested_exposure_units"] == 1
