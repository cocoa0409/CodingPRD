"""Transitive cascades (vendor suspension, critical-event void) and numeric
boundary precision (PRD §3.1, §3.4, §3.5, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_open_period_scenario, setup_closed_period_with_rate,
    setup_application_under_review,
    create_site, create_vendor, create_active_contract, create_period,
    create_ticket, validate_ticket, create_goal, create_event,
    set_clock, create_application_payload,
    ApiErrorId, TEST_USERS, make_manager_headers, make_officer_headers,
)

OFFICER = TEST_USERS["officer_headers"]
MGR = TEST_USERS["manager_headers"]


# ============================================================ transitive_cascade

def _vs_scenario():
    """T1 PENDING 1000; T2 RECYCLING 2000 VALIDATED; T3 LANDFILL 1000 VALIDATED."""
    site, vendor, contract, period = setup_open_period_scenario("Site VS")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=2000,
                       tare_weight_lbs=1000, external_ticket_ref="VS-T1")
    t2 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=3000,
                       tare_weight_lbs=1000, external_ticket_ref="VS-T2")
    validate_ticket(t2["id"])
    t3 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="LANDFILL", gross_weight_lbs=2000,
                       tare_weight_lbs=1000, external_ticket_ref="VS-T3")
    validate_ticket(t3["id"])
    return site, vendor, contract, period, t1, t2, t3


def test_vendor_suspension_cascades_to_contract_and_pending_tickets(api):
    """PRD §3.1: "Suspension cascades down the chain: every ACTIVE contract of
    that vendor moves to SUSPENDED, and each newly suspended contract rejects
    its still-PENDING tickets, stamping rejection_reason as CONTRACT_SUSPENDED
    and shrinking the provisional totals of the periods that contained them."

    Design: Difficulty/transitive_cascade/vendor_suspend_transitive_cascade
    """
    site, vendor, contract, period, t1, t2, t3 = _vs_scenario()
    get_success_data(api.set_vendor_status(vendor["id"], {"to_status": "SUSPENDED"}, OFFICER))
    c = get_success_data(api.get_contract(contract["id"], OFFICER))
    assert c["status"] == "SUSPENDED"
    t1_after = get_success_data(api.get_ticket(t1["id"], OFFICER))
    assert t1_after["validation_status"] == "REJECTED"
    assert t1_after["rejection_reason"] == "CONTRACT_SUSPENDED"


def test_vendor_suspension_recomputes_period_provisional_only(api):
    """PRD §3.1: "each newly suspended contract rejects its still-PENDING
    tickets, stamping rejection_reason as CONTRACT_SUSPENDED and shrinking the
    provisional totals of the periods that contained them."

    Design: Difficulty/transitive_cascade/vendor_suspend_transitive_cascade
    """
    site, vendor, contract, period, t1, t2, t3 = _vs_scenario()
    before = get_success_data(api.get_period(period["id"], OFFICER))
    assert before["total_waste_lbs_provisional"] == 4000
    assert before["diversion_rate_provisional_pct"] == pytest.approx(75.00, abs=0.005)
    get_success_data(api.set_vendor_status(vendor["id"], {"to_status": "SUSPENDED"}, OFFICER))
    after = get_success_data(api.get_period(period["id"], OFFICER))
    assert after["total_waste_lbs_provisional"] == 3000
    assert after["diversion_rate_provisional_pct"] == pytest.approx(66.67, abs=0.005)
    # Certified set untouched: T2 and T3 remain VALIDATED.
    assert after["diversion_rate_certified_pct"] == pytest.approx(66.67, abs=0.005)


def _cc_scenario():
    """T1 RECYCLING 2000 VALIDATED (no pct -> estimate 10000c);
    T2 LANDFILL 1000 VALIDATED."""
    site, vendor, contract, period = setup_open_period_scenario("Site CC")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=3000,
                       tare_weight_lbs=1000, external_ticket_ref="CC-T1")
    validate_ticket(t1["id"])
    t2 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="LANDFILL", gross_weight_lbs=2000,
                       tare_weight_lbs=1000, external_ticket_ref="CC-T2")
    validate_ticket(t2["id"])
    return site, vendor, contract, period, t1, t2


def test_critical_event_voids_validated_ticket(api):
    """PRD §3.5: "If it is linked to a VALIDATED ticket, that ticket is voided
    on the spot — the VALIDATED → VOIDED transition runs with its full
    compensation of certified totals and rebate estimate — while a linked
    PENDING ticket is rejected instead."

    Design: Difficulty/transitive_cascade/critical_contamination_void_cascade
    """
    site, vendor, contract, period, t1, t2 = _cc_scenario()
    ev = create_event(site["id"], event_date="2026-08-06",
                      material_stream="MIXED_RECYCLABLES", contamination_pct=15,
                      ticket_id=t1["id"])
    assert ev["severity"] == "CRITICAL"
    t1_after = get_success_data(api.get_ticket(t1["id"], OFFICER))
    assert t1_after["validation_status"] == "VOIDED"


def test_critical_event_recomputes_period_and_standing(api):
    """PRD §3.5: "Standing is computed over the site's non-terminal events,
    meaning those in OPEN, TRAINING_ASSIGNED, or TRAINING_COMPLETED ... If any
    non-terminal event is CRITICAL, the site is on PROBATION."

    Design: Difficulty/transitive_cascade/critical_contamination_void_cascade
    """
    site, vendor, contract, period, t1, t2 = _cc_scenario()
    p_before = get_success_data(api.get_period(period["id"], OFFICER))
    assert p_before["total_waste_lbs_validated"] == 3000
    assert p_before["rebate_estimate_cents"] == 10000
    create_event(site["id"], event_date="2026-08-06",
                 material_stream="MIXED_RECYCLABLES", contamination_pct=15,
                 ticket_id=t1["id"])
    p_after = get_success_data(api.get_period(period["id"], OFFICER))
    assert p_after["total_waste_lbs_validated"] == 1000
    assert p_after["diversion_rate_certified_pct"] == pytest.approx(0.00, abs=0.005)
    assert p_after["rebate_estimate_cents"] == 0
    s = get_success_data(api.get_site(site["id"], OFFICER))
    assert s["program_standing"] == "PROBATION"


# ============================================================ boundary_precision_check

def _zw_scenario():
    """Closed period with certified rate exactly 90.00; ZERO_WASTE application
    under review (submitter mgr-1)."""
    site, period, app = setup_application_under_review(
        "Site ZW", level="ZERO_WASTE", submitter_id="mgr-1",
        tickets=[
            {"disposal_route": "RECYCLING", "gross_weight_lbs": 10,
             "tare_weight_lbs": 1, "external_ticket_ref": "ZW-T1"},
            {"disposal_route": "LANDFILL", "gross_weight_lbs": 2,
             "tare_weight_lbs": 1, "external_ticket_ref": "ZW-T2"},
        ],
    )
    return site, period, app


def test_zero_waste_threshold_exactly_90_approves(api):
    """PRD §3.8: "the reporting period's frozen diversion_rate_certified_pct
    must meet the requested level's threshold — 50.0 for BRONZE, 70.0 for
    SILVER, 85.0 for GOLD, and 90.0 for ZERO_WASTE — compared with the boundary
    inclusive and with no further rounding at decision time, so exactly 90.00
    earns ZERO_WASTE."

    Design: Difficulty/boundary_precision_check/zero_waste_threshold_exactly_90
    """
    site, period, app = _zw_scenario()
    p = get_success_data(api.get_period(period["id"], OFFICER))
    assert p["diversion_rate_certified_pct"] == pytest.approx(90.00, abs=0.005)
    decided = get_success_data(api.decide_application(
        app["id"], {"outcome": "APPROVED"}, make_officer_headers("officer-1")
    ))
    assert decided["status"] == "APPROVED"
    s = get_success_data(api.get_site(site["id"], OFFICER))
    assert s["certification_tier"] == "ZERO_WASTE"


def test_zero_waste_approval_sets_site_tier(api):
    """PRD §3.8: "Approval ripples outward. Any prior `APPROVED` application of
    the same site moves to `SUPERSEDED`, and the site's `certification_tier`
    becomes the newly approved application's `level_requested`."

    Design: Difficulty/boundary_precision_check/zero_waste_threshold_exactly_90
    """
    site, period, app = _zw_scenario()
    get_success_data(api.decide_application(
        app["id"], {"outcome": "APPROVED"}, make_officer_headers("officer-1")
    ))
    s = get_success_data(api.get_site(site["id"], OFFICER))
    assert s["certification_tier"] == "ZERO_WASTE"
    a = get_success_data(api.get_application(app["id"], OFFICER))
    assert a["status"] == "APPROVED"
    assert a.get("decided_by") == "officer-1"


def test_close_period_with_zero_validated_tickets(api):
    """PRD §3.4: "The diversion_rate_certified_pct is the diverted pounds
    multiplied by 100 and divided by the total pounds, rounded half-up to two
    decimal places, or exactly 0.00 when the total is zero."

    Design: Difficulty/boundary_precision_check/close_period_zero_validated_tickets
    """
    set_clock()
    site = create_site("Site EZ")
    period = create_period(site["id"])
    goal = create_goal(site["id"], metric="DIVERSION_RATE", target_value=80,
                       window_start="2026-08-01", window_end="2026-09-01")
    closed = get_success_data(api.close_period(period["id"], OFFICER))
    assert closed["status"] == "CLOSED"
    assert closed["total_waste_lbs_validated"] == 0
    assert closed["diversion_rate_certified_pct"] == pytest.approx(0.00, abs=0.005)
    assert closed["rebate_settled_cents"] == 0
    assert closed["cost_avoided_cents"] == 0
    g = get_success_data(api.get_goal(goal["id"], OFFICER))
    assert g["status"] == "MISSED"


def test_zero_denominator_rate_is_pinned_zero_not_error(api):
    """PRD §3.4: "or exactly 0.00 when the total is zero."
    PRD §3.6: "A DIVERSION_RATE goal is achieved when the frozen
    diversion_rate_certified_pct is greater than or equal to the goal's
    target_value."

    Design: Difficulty/boundary_precision_check/close_period_zero_validated_tickets
    """
    set_clock()
    site = create_site("Site EZ2")
    period = create_period(site["id"])
    goal_met = create_goal(site["id"], metric="DIVERSION_RATE", target_value=0,
                           window_start="2026-08-01", window_end="2026-09-01")
    closed = get_success_data(api.close_period(period["id"], OFFICER))
    assert closed["diversion_rate_certified_pct"] == pytest.approx(0.00, abs=0.005)
    g = get_success_data(api.get_goal(goal_met["id"], OFFICER))
    # 0.00 >= 0 with inclusive boundary -> ACHIEVED
    assert g["status"] == "ACHIEVED"
