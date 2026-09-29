"""Inclusive and strict boundaries: the 0.75 drill floor and its window edge, the
auto-sizing tolerances, and the NPO floors."""
import pytest

from test_helpers import (
    assert_instant_equals,
    ADMIN,
    INVENTORY,
    api_client,
    apply_permit,
    auto_size_for_case,
    create_evaluation_for,
    create_lot,
    day_of_verification_payload,
    draft_case,
    fetch_case,
    fetch_evaluation,
    fetch_lot,
    fetch_permit,
    fetch_practice,
    get_success_data,
    log_drill,
    make_anesthesia_coordinator_headers,
    record_inspection_result,
    run_compliance_sweep,
    schedule_inspection,
    set_env_clock,
    setup_practice_with_roster,
    sign_evaluation_as,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-09-11T10:00:00Z"

# --- drill_compliance_ratio_exactly_at_the_075_floor ---------------------------


def _practice_covering_three_of_four_drill_types():
    """A MODERATE_SEDATION application whose qualifying drills cover exactly three of
    the four required types, with the oldest sitting just inside the 365-day window.
    Three further drills are deliberately non-qualifying."""
    env = setup_practice_with_roster(clock=CLOCK)
    participants = [env["surgeon"]["id"], env["monitor"]["id"]]
    permit = apply_permit(env["practice_id"], "MODERATE_SEDATION", CLOCK)
    log_drill(env["practice_id"], "AIRWAY_OBSTRUCTION", "2025-10-01T10:00:00Z", participants)
    log_drill(env["practice_id"], "LARYNGOSPASM", "2026-09-01T10:00:00Z", participants)
    log_drill(env["practice_id"], "LOCAL_ANESTHETIC_TOXICITY", "2026-09-05T10:00:00Z", participants)
    # None of these three count: a deficient debrief, a duplicate type, and a type
    # this permit level does not require.
    log_drill(env["practice_id"], "CARDIAC_ARREST", "2026-09-06T10:00:00Z", participants,
              deficiency_noted=True)
    log_drill(env["practice_id"], "LARYNGOSPASM", "2026-09-07T10:00:00Z", participants)
    log_drill(env["practice_id"], "MALIGNANT_HYPERTHERMIA", "2026-09-08T10:00:00Z", participants)
    inspection = schedule_inspection(permit["id"], "2026-09-12T10:00:00Z")
    set_env_clock(env, "2026-09-12T10:00:00Z")
    env["permit"] = permit
    env["inspection"] = inspection
    return env, permit, inspection


def test_a_ratio_of_exactly_075_passes_the_inspection_into_active(api):
    """PRD 3.2: "The practice is drill-compliant when the ratio is at or above 0.75;
    because the comparison is inclusive, a ratio of exactly 0.75 passes. A
    `MODERATE_SEDATION` practice with three of its four types covered sits at 0.75 and
    is compliant; a `DEEP_SEDATION_GENERAL` practice with three of five sits at 0.60
    and is not."
    PRD 3.2: "A drill qualifies when it belongs to that practice, its
    `deficiency_noted` is false, its `conducted_at` falls strictly later than the
    instant exactly 365 days before the logical clock and at or before the logical
    clock itself, and its `drill_type` is a member of the required set."
    PRD 3.2: "A `PASSED` result on a permit in `INSPECTION_PENDING` whose
    `drill_compliance_ratio`, recomputed at that instant, is at or above 0.75 advances
    the permit to `ACTIVE`"

    Design: Difficulty/boundary_precision_check/drill_compliance_ratio_exactly_at_the_075_floor
    """
    env, permit, inspection = _practice_covering_three_of_four_drill_types()

    result = record_inspection_result(inspection["id"], 0, 0, 0)
    assert result["inspection_score"] == 100
    assert result["status"] == "PASSED"

    live = fetch_permit(permit["id"])
    assert float(live["drill_compliance_ratio"]) == pytest.approx(0.75, abs=0.001), (
        f"three distinct qualifying types over four required, got {live['drill_compliance_ratio']}"
    )
    assert live["status"] == "ACTIVE", (
        f"0.75 is at the floor and the comparison is inclusive, got {live['status']}"
    )
    assert live["last_enforcement_reason"] is None
    assert fetch_practice(env["practice_id"])["sedation_privilege_state"] == "PERMITTED"

    summary = get_success_data(
        api_client.get_compliance_summary(env["practice_id"], ADMIN)
    )
    assert summary["drill_compliant"] is True
    assert len(summary["required_drill_types"]) == 4
    assert len(summary["covered_drill_types"]) == 3, (
        "the deficient, duplicate and unrequired drills all fall out of coverage"
    )


def test_the_365_day_window_edge_drops_the_ratio_and_the_sweep_bites(api):
    """PRD 3.10: "In the drill pass, an `ACTIVE` permit whose `drill_compliance_ratio`,
    recomputed at sweep time, has fallen below 0.75 drops to `PROBATION` with
    `last_enforcement_reason` `DRILL_LAPSE`, `probation_count` increased by 1,
    `remediation_deadline_at` set to the logical clock plus 30 days, the privilege moved
    to `RESTRICTED`, and the practice's `CLEARED` `DEEP_SEDATION_GENERAL` cases
    deferred."
    PRD 3.2: "The ratio is recomputed whenever a drill is logged, whenever an
    inspection result is posted, on every read of the practice compliance view, and
    during the compliance sweep."

    Design: Difficulty/boundary_precision_check/drill_compliance_ratio_exactly_at_the_075_floor
    """
    env, permit, inspection = _practice_covering_three_of_four_drill_types()
    record_inspection_result(inspection["id"], 0, 0, 0)
    assert fetch_permit(permit["id"])["status"] == "ACTIVE"

    # One day past the 2025-10-01 drill's 365-day anniversary.
    set_env_clock(env, "2026-10-02T10:00:00Z")
    run_compliance_sweep(env["practice_id"])

    lapsed = fetch_permit(permit["id"])
    assert float(lapsed["drill_compliance_ratio"]) == pytest.approx(0.50, abs=0.001), (
        f"the oldest drill fell out of the trailing window, got {lapsed['drill_compliance_ratio']}"
    )
    assert lapsed["status"] == "PROBATION"
    assert lapsed["last_enforcement_reason"] == "DRILL_LAPSE"
    assert lapsed["probation_count"] == 1
    assert_instant_equals(lapsed["remediation_deadline_at"], "2026-11-01T10:00:00Z")
    assert fetch_practice(env["practice_id"])["sedation_privilege_state"] == "RESTRICTED"


# --- auto_size_tolerance_inclusive_edge_and_empty_pool -------------------------

def _three_lots_around_the_tolerance_edges():
    """Lot A sits exactly 0.5 mm and 2.0 mm from the request and is eligible; lot B is
    0.6 mm out; lot C expires exactly at midnight on the day of a 13:00 case."""
    env = setup_practice_with_roster(clock=CLOCK)
    case = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        procedure_category="IMPLANT",
        total_charge_cents=200000,
        with_monitor=False,
    )
    lot_a = create_lot(
        env["practice_id"], diameter_mm=4.8, length_mm=12.0, quantity_on_hand=3,
        unit_cost_cents=20000, expiry_date="2027-06-30T00:00:00Z", is_consignment=False,
    )
    lot_b = create_lot(
        env["practice_id"], diameter_mm=4.9, length_mm=10.0, quantity_on_hand=3,
        unit_cost_cents=20000, expiry_date="2027-06-30T00:00:00Z", is_consignment=False,
    )
    lot_c = create_lot(
        env["practice_id"], diameter_mm=4.3, length_mm=10.0, quantity_on_hand=3,
        unit_cost_cents=20000, expiry_date="2026-09-14T00:00:00Z", is_consignment=False,
    )
    return env, case, lot_a, lot_b, lot_c


def test_the_lot_exactly_at_both_tolerances_is_inside_the_candidate_pool(api):
    """PRD 3.7: "The candidate pool is every lot of the case's practice whose `status`
    is `AVAILABLE`, whose `expiry_date` falls after the case's `planned_start`, whose
    `available_quantity` is at least the requested `quantity`, whose `diameter_mm`
    differs from `requested_diameter_mm` by at most half a millimetre, and whose
    `length_mm` differs from `requested_length_mm` by at most two millimetres."
    PRD 3.7: "Both tolerance comparisons are inclusive and dimensions are compared to
    one decimal place, so a lot exactly 0.5 mm off the requested diameter is eligible
    while one 0.6 mm off is not."
    PRD 3.7: "The chosen lot becomes the reservation's `lot_id`, `selection_mode` is
    recorded as `AUTO_SIZED`, and the requested dimensions are retained on the
    reservation. Every pricing and ledger effect is identical to the explicit path."

    Design: Difficulty/boundary_precision_check/auto_size_tolerance_inclusive_edge_and_empty_pool
    """
    env, case, lot_a, lot_b, lot_c = _three_lots_around_the_tolerance_edges()

    reservation = auto_size_for_case(case["id"], 4.3, 10.0, quantity=1)

    assert reservation["lot_id"] == lot_a["id"], (
        "only the +0.5 mm / +2.0 mm lot survives the pool filters"
    )
    assert reservation["selection_mode"] == "AUTO_SIZED"
    assert reservation["status"] == "HELD"
    assert reservation["quantity"] == 1
    assert reservation["line_subtotal_cents"] == 20000
    assert reservation["restocking_fee_cents"] == 3000, (
        f"a 20000 subtotal sits in the fifteen percent tier, got {reservation['restocking_fee_cents']}"
    )
    assert reservation["consignment_credit_cents"] == 0
    assert reservation["consignment_liability_cents"] == 20000

    chosen = fetch_lot(lot_a["id"])
    assert chosen["quantity_reserved"] == 1
    assert chosen["available_quantity"] == 2
    assert fetch_lot(lot_b["id"])["quantity_reserved"] == 0, (
        "the 0.6 mm lot was never a candidate"
    )
    assert fetch_lot(lot_c["id"])["quantity_reserved"] == 0, (
        "a lot expiring at midnight is not strictly after a 13:00 planned start"
    )
    assert fetch_practice(env["practice_id"])["consignment_committed_cents"] == 20000


def test_an_empty_candidate_pool_is_refused_rather_than_approximated(api):
    """PRD 3.7: "If the pool is empty the request is refused with
    `ERR_NO_ELIGIBLE_IMPLANT_LOT` (HTTP 409); the quarantine test still answers
    `ERR_LOT_UNAVAILABLE` where it applies."

    A 3.5 mm request sits 1.3 mm from lot A and 0.8 mm from lot C, both well outside
    the half-millimetre tolerance, so the selector must refuse rather than pick the
    nearest lot.

    Design: Difficulty/boundary_precision_check/auto_size_tolerance_inclusive_edge_and_empty_pool
    """
    env, case, lot_a, lot_b, lot_c = _three_lots_around_the_tolerance_edges()

    response = api_client.auto_size_reservation(
        case["id"],
        {"requested_diameter_mm": 3.5, "requested_length_mm": 10.0, "quantity": 1},
        INVENTORY,
    )
    validate_error(response, "ERR_NO_ELIGIBLE_IMPLANT_LOT", 409)

    rows, _meta = validate_paginated(
        api_client.list_reservations(INVENTORY, {"case_id": case["id"]})
    )
    assert rows == [], "no reservation row may be created by a refused auto-size"
    assert fetch_lot(lot_a["id"])["quantity_reserved"] == 0
    assert fetch_practice(env["practice_id"])["consignment_committed_cents"] == 0


# --- npo_minutes_exactly_at_the_480_and_120_floors -----------------------------

def _signed_evaluation_at_the_operative_hour():
    """A SIGNED MODERATE_SEDATION evaluation scoring 23.0, with the logical clock
    standing exactly at the case's planned start."""
    env = setup_practice_with_roster(clock=CLOCK)
    case = draft_case(
        env,
        planned_anesthesia_level="MODERATE_SEDATION",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        procedure_category="IMPLANT",
        total_charge_cents=200000,
    )
    evaluation = create_evaluation_for(
        env, case["id"], env["monitor"]["id"],
        asa_class_recorded=2, airway_class_recorded=2, comorbidity_count=1,
    )
    signed = sign_evaluation_as(evaluation["id"], env["monitor"]["id"])
    set_env_clock(env, "2026-09-14T13:00:00Z")
    return env, case, signed


def test_one_minute_short_of_the_solids_floor_is_refused(api):
    """PRD 3.5: "First fasting: for any case whose `planned_anesthesia_level` is above
    `LOCAL_ONLY`, `npo_solids_minutes` must be at least 480 — eight hours without
    solids — and `npo_clears_minutes` at least 120, two hours without clear liquids; a
    shortfall in either is `ERR_FASTING_REQUIREMENT_UNMET` (HTTP 409)."
    PRD 3.5: "`npo_solids_minutes` is the whole minutes from `fasting_solids_last_at`
    to the logical clock at verification"

    Design: Difficulty/boundary_precision_check/npo_minutes_exactly_at_the_480_and_120_floors
    """
    env, case, signed = _signed_evaluation_at_the_operative_hour()
    assert signed["provisional_risk_score"] == pytest.approx(23.0, abs=0.01)
    assert signed["risk_band"] == "LOW"

    response = api_client.verify_evaluation(
        signed["id"],
        day_of_verification_payload(
            "CLEAR", "2026-09-14T05:01:00Z", "2026-09-14T11:00:00Z",
            escort_confirmed=True, escort_name="Ada Escort",
        ),
        make_anesthesia_coordinator_headers(env["verifier"]["id"]),
    )
    validate_error(response, "ERR_FASTING_REQUIREMENT_UNMET", 409)

    unchanged = fetch_evaluation(signed["id"])
    assert unchanged["status"] == "SIGNED", "479 minutes is one short of the floor"
    # PRD 3.5: "`final_risk_score` and `risk_band` are recomputed by the final
    # variant **before** any gate is evaluated, so the published score reflects
    # reality even on a rejected attempt." 23.0 core plus the 15-point sub-480
    # solids penalty is 38.0.
    assert unchanged["final_risk_score"] == pytest.approx(38.0, abs=0.01), (
        "the score is published before the gates run, got "
        f"{unchanged['final_risk_score']}"
    )
    assert unchanged["risk_band"] == "ELEVATED"


def test_exactly_480_minutes_clears_the_gate_and_attracts_no_penalty(api):
    """PRD 3.5: "Fifteen points are added when `npo_solids_minutes` is under 480."
    PRD 3.5: "The sum of the core score and the accumulated penalties, rounded half-up
    to two decimal places, is `final_risk_score`."
    PRD 3.5: "`CLEAR` moves the case's `clearance_status` from `EVALUATED` to
    `CLEARED`, which is the only route to a confirmable case."

    At exactly 480 minutes the penalty is not applied, so the final score equals the
    provisional 23.0 and the band stays LOW; one minute earlier it would have read
    38.0 and ELEVATED.

    Design: Difficulty/boundary_precision_check/npo_minutes_exactly_at_the_480_and_120_floors
    """
    env, case, signed = _signed_evaluation_at_the_operative_hour()

    verified = validate_success(
        api_client.verify_evaluation(
            signed["id"],
            day_of_verification_payload(
                "CLEAR", "2026-09-14T05:00:00Z", "2026-09-14T11:00:00Z",
                escort_confirmed=True, escort_name="Ada Escort",
            ),
            make_anesthesia_coordinator_headers(env["verifier"]["id"]),
        )
    )

    assert verified["npo_solids_minutes"] == 480
    assert verified["npo_clears_minutes"] == 120
    assert verified["final_risk_score"] == pytest.approx(23.0, abs=0.01), (
        f"no penalty applies at exactly the floor, got {verified['final_risk_score']}"
    )
    assert verified["final_risk_score"] != pytest.approx(38.0, abs=0.01)
    assert verified["risk_band"] == "LOW"
    assert verified["status"] == "VERIFIED"
    assert fetch_case(case["id"])["clearance_status"] == "CLEARED"
