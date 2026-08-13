"""Non-linear state machine cycles: ticket correction loop and training reopen
loop (PRD §3.3, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_open_period_scenario, create_site, create_ticket, validate_ticket,
    reject_ticket, create_event, set_clock,
    ApiErrorId, TEST_USERS, make_vendor_user_headers,
)

OFFICER = TEST_USERS["officer_headers"]
STEWARD = TEST_USERS["steward_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ============================================================ non_linear_state_machine (ticket)

def _cycle_scenario():
    site, vendor, contract, period = setup_open_period_scenario("Site CY")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=3000,
                       tare_weight_lbs=1000, external_ticket_ref="CY-T1")
    return site, vendor, contract, period, t1


def test_reject_drops_ticket_from_provisional_set(api):
    """PRD §3.3: "Rejection by a DataSteward requires only that the ticket be
    PENDING, failing otherwise with ERR_TICKET_NOT_PENDING; it records the
    supplied reason as the ticket's rejection_reason, drops the ticket out of
    the provisional set so the period's provisional totals shrink, and
    increments the period's version."

    Design: Difficulty/non_linear_state_machine/ticket_reject_resubmit_cycle
    """
    site, vendor, contract, period, t1 = _cycle_scenario()
    p_before = get_success_data(api.get_period(period["id"], OFFICER))
    assert p_before["total_waste_lbs_provisional"] == 2000
    rejected = get_success_data(
        api.reject_ticket(t1["id"], {"reason": "illegible scale ticket"}, STEWARD)
    )
    assert rejected["validation_status"] == "REJECTED"
    assert rejected["rejection_reason"] == "illegible scale ticket"
    p_after = get_success_data(api.get_period(period["id"], OFFICER))
    assert p_after["total_waste_lbs_provisional"] == 0


def test_resubmit_returns_ticket_to_pending_and_validates(api):
    """PRD §3.3: "Resubmission applies the corrections, recomputes
    net_weight_lbs, clears rejection_reason, returns the ticket to PENDING,
    and grows the containing period's provisional totals and version once
    more."

    Design: Difficulty/non_linear_state_machine/ticket_reject_resubmit_cycle
    """
    site, vendor, contract, period, t1 = _cycle_scenario()
    reject_ticket(t1["id"], "illegible scale ticket")
    resub = get_success_data(api.resubmit_ticket(
        t1["id"], {"gross_weight_lbs": 3000, "tare_weight_lbs": 1000},
        make_vendor_user_headers(vendor["id"]),
    ))
    assert resub["validation_status"] == "PENDING"
    assert resub.get("rejection_reason") is None
    # Cycle closes: validate after resubmit; rate becomes 100.00.
    validated = validate_ticket(t1["id"])
    assert validated["validation_status"] == "VALIDATED"
    p = get_success_data(api.get_period(period["id"], OFFICER))
    assert p["diversion_rate_certified_pct"] == pytest.approx(100.00, abs=0.005)


# ============================================================ non_linear_state_machine (event)

def _event_scenario():
    set_clock()
    site = create_site("Site CT")
    ev = create_event(site["id"], event_date="2026-08-05",
                      material_stream="MIXED_RECYCLABLES", contamination_pct=6)
    return site, ev


def test_training_lifecycle_assign_complete(api):
    """PRD §3.5: "Assigning training — permitted only from `OPEN`, otherwise
    `ERR_INVALID_STATE` — records `trainee_name` and `training_due_date` and
    moves the event to `TRAINING_ASSIGNED`. Completing training moves it from
    `TRAINING_ASSIGNED` to `TRAINING_COMPLETED`."

    Design: Difficulty/non_linear_state_machine/contamination_training_reopen_cycle
    """
    site, ev = _event_scenario()
    assert ev["severity"] == "MAJOR"  # 5 <= 6 < 10
    a = get_success_data(api.assign_training(
        ev["id"], {"trainee_name": "Dock Crew Lead", "training_due_date": "2026-08-20"},
        AUDITOR,
    ))
    assert a["status"] == "TRAINING_ASSIGNED"
    assert a["trainee_name"] == "Dock Crew Lead"
    c = get_success_data(api.complete_training(ev["id"], AUDITOR))
    assert c["status"] == "TRAINING_COMPLETED"


def test_failed_verification_reopens_event_and_clears_training(api):
    """PRD §3.5: "Verification takes a `passed` flag and is permitted only from
    `TRAINING_COMPLETED`: when `passed` is true the event moves to
    `VERIFIED_CLOSED`, a terminal state; when `passed` is false the event
    loops back to `OPEN` with `trainee_name` and `training_due_date` cleared,
    and the cycle restarts."

    Design: Difficulty/non_linear_state_machine/contamination_training_reopen_cycle
    """
    site, ev = _event_scenario()
    get_success_data(api.assign_training(
        ev["id"], {"trainee_name": "Dock Crew Lead", "training_due_date": "2026-08-20"},
        AUDITOR,
    ))
    get_success_data(api.complete_training(ev["id"], AUDITOR))
    failed = get_success_data(api.verify_event(ev["id"], {"passed": False}, AUDITOR))
    assert failed["status"] == "OPEN"
    assert failed.get("trainee_name") is None
    # Restart the loop and pass on the second attempt.
    get_success_data(api.assign_training(
        ev["id"], {"trainee_name": "Dock Crew Lead", "training_due_date": "2026-08-27"},
        AUDITOR,
    ))
    get_success_data(api.complete_training(ev["id"], AUDITOR))
    closed = get_success_data(api.verify_event(ev["id"], {"passed": True}, AUDITOR))
    assert closed["status"] == "VERIFIED_CLOSED"


# ============================================================ compensating_invariant

def test_validate_then_void_conserves_validated_pounds(api):
    """PRD §3.3: "The void subtracts exactly the ticket's net_weight_lbs from
    the period's certified totals, compensating the validation accrual exactly,
    reverses the ticket's accrued rebate estimate exactly, and increments the
    period's version."

    Design: Difficulty/compensating_invariant/validate_then_void_conserves_validated_pounds
    """
    site, vendor, contract, period = setup_open_period_scenario("Site IM")
    base = get_success_data(api.get_period(period["id"], OFFICER))
    assert base["total_waste_lbs_validated"] == 0
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=3000,
                       tare_weight_lbs=1000, external_ticket_ref="IM-T1")
    validate_ticket(t1["id"])
    after_val = get_success_data(api.get_period(period["id"], OFFICER))
    assert after_val["total_waste_lbs_validated"] == 2000
    assert after_val["diverted_lbs_validated"] == 2000
    get_success_data(api.void_ticket(t1["id"], {"reason": "duplicate scale record"}, STEWARD))
    after_void = get_success_data(api.get_period(period["id"], OFFICER))
    assert after_void["total_waste_lbs_validated"] == 0
    assert after_void["diverted_lbs_validated"] == 0
    assert after_void["total_waste_lbs_validated"] == base["total_waste_lbs_validated"]


def test_validate_then_void_conserves_validated_pounds_with_mixed_routes(api):
    """PRD §3.4: "`total_waste_lbs_validated` sums their `net_weight_lbs`, and
    `diverted_lbs_validated` sums the same measure over tickets whose
    `disposal_route` is one of the three diverted routes — `RECYCLING`,
    `COMPOSTING`, or `REUSE`; `LANDFILL` and `ENERGY_RECOVERY` never count as
    diverted."

    Design: Difficulty/compensating_invariant/validate_then_void_conserves_validated_pounds
    """
    site, vendor, contract, period = setup_open_period_scenario("Site IM2")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=3000,
                       tare_weight_lbs=1000, external_ticket_ref="IM2-T1")
    t2 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="LANDFILL", gross_weight_lbs=2000,
                       tare_weight_lbs=1000, external_ticket_ref="IM2-T2")
    validate_ticket(t1["id"])
    validate_ticket(t2["id"])
    mid = get_success_data(api.get_period(period["id"], OFFICER))
    assert mid["total_waste_lbs_validated"] == 3000
    assert mid["diverted_lbs_validated"] == 2000
    get_success_data(api.void_ticket(t1["id"], {"reason": "x"}, STEWARD))
    after = get_success_data(api.get_period(period["id"], OFFICER))
    assert after["total_waste_lbs_validated"] == 1000
    assert after["diverted_lbs_validated"] == 0


def test_validate_then_void_conserves_rebate_cents(api):
    """PRD §3.7: "The ticket's estimate is the rebate part minus the penalty
    part, and it accrues into the containing period's rebate_estimate_cents.
    Voiding the ticket later reverses its accrued estimate exactly."

    Design: Difficulty/compensating_invariant/validate_then_void_conserves_rebate_cents
    """
    site, vendor, contract, period = setup_open_period_scenario("Site IC")
    base = get_success_data(api.get_period(period["id"], OFFICER))
    assert base["rebate_estimate_cents"] == 0
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=5000,
                       tare_weight_lbs=1000, contamination_pct=3,
                       external_ticket_ref="IC-T1")
    validate_ticket(t1["id"])
    after_val = get_success_data(api.get_period(period["id"], OFFICER))
    # 2t * 10000c * 1.0, no penalty (pct 3 < 5)
    assert after_val["rebate_estimate_cents"] == 20000
    get_success_data(api.void_ticket(t1["id"], {"reason": "wrong contract referenced"}, STEWARD))
    after_void = get_success_data(api.get_period(period["id"], OFFICER))
    assert after_void["rebate_estimate_cents"] == 0
    assert after_void["rebate_estimate_cents"] == base["rebate_estimate_cents"]


def test_void_reversal_leaves_other_tickets_accrual_intact(api):
    """PRD §3.7: "Voiding the ticket later reverses its accrued estimate
    exactly."

    Design: Difficulty/compensating_invariant/validate_then_void_conserves_rebate_cents
    """
    site, vendor, contract, period = setup_open_period_scenario("Site IC2")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=5000,
                       tare_weight_lbs=1000, contamination_pct=3,
                       external_ticket_ref="IC2-T1")
    t2 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=3000,
                       tare_weight_lbs=1000, external_ticket_ref="IC2-T2")
    validate_ticket(t1["id"])
    validate_ticket(t2["id"])
    mid = get_success_data(api.get_period(period["id"], OFFICER))
    # t1: 2t*10000 = 20000; t2: 1t*10000 = 10000
    assert mid["rebate_estimate_cents"] == 30000
    get_success_data(api.void_ticket(t1["id"], {"reason": "x"}, STEWARD))
    after = get_success_data(api.get_period(period["id"], OFFICER))
    assert after["rebate_estimate_cents"] == 10000
