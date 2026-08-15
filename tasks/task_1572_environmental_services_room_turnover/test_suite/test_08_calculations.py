"""Calculation-rule claims: priority scores, time standards, audits, supplies,
productivity, snapshots."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    assert_instant_equal,
    create_bed_payload,
    create_clean_request_payload,
    create_placement_demand_payload,
    create_unit_payload,
    get_success_data,
    make_auditor_headers,
    make_technician_headers,
    set_clock,
    setup_basic_scenario,
    validate_paginated,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    complete_request,
    create_all_standards,
    create_bed,
    create_request,
    create_standard,
    create_staff,
    create_technician,
    create_unit,
    seed_supplies,
    start_request,
    submit_audit,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


def test_request_priority_score_tier_demand_breach_composition(api):
    """PRD §3.2: "Its `priority_score` is the sum of a tier base — 10000 for
    `STAT`, 5000 for `URGENT`, 0 for `STANDARD` — plus the highest
    `priority_score` among the contributing demands (zero when there are none),
    plus a breach boost of 2500 once the request's `sla_breached` flag is
    true; the sum is rounded to two decimal places, half up."
    PRD §3.3: "The `sla_breached` flag is set to true at an ops-run when the
    clock has moved strictly past `sla_due_at` while the request is `QUEUED`,
    `ASSIGNED`, or `IN_PROGRESS`; once true it stays true."

    Design: Corner/calculations/request_priority_score_tier_demand_breach_composition
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_standard("ROUTINE")
    bed = create_bed(unit["id"])
    req = create_request(bed["id"], "ROUTINE")
    assert req["priority_tier"] == "STANDARD"
    assert req["priority_score"] == 0.0

    demand = get_success_data(
        api.create_placement_demand(
            create_placement_demand_payload(
                unit_id=unit["id"], urgency_tier="URGENT"
            ),
            COORDINATOR,
        )
    )
    r = get_success_data(api.get_clean_request(req["id"], ANY))
    assert r["priority_tier"] == "URGENT"
    assert r["priority_score"] == pytest.approx(5550.0, abs=0.01)

    # At sla_due_at equality (08:45): no breach (strict >), wait 45 min.
    set_clock("2026-08-01T08:45:00Z")
    get_success_data(api.run_ops_run(unit["id"], ADMIN))
    r = get_success_data(api.get_clean_request(req["id"], ANY))
    assert r["sla_breached"] is False
    assert r["priority_score"] == pytest.approx(5640.0, abs=0.01)

    # One minute past: breach boost lands, wait 46 min.
    set_clock("2026-08-01T08:46:00Z")
    get_success_data(api.run_ops_run(unit["id"], ADMIN))
    r = get_success_data(api.get_clean_request(req["id"], ANY))
    assert r["sla_breached"] is True
    assert r["priority_score"] == pytest.approx(8142.0, abs=0.01)

    # Demand cancelled: tier collapses to STANDARD; boost is sticky.
    get_success_data(api.cancel_placement_demand(demand["id"], COORDINATOR))
    r = get_success_data(api.get_clean_request(req["id"], ANY))
    assert r["priority_tier"] == "STANDARD"
    assert r["sla_breached"] is True
    assert r["priority_score"] == pytest.approx(2500.0, abs=0.01)


def test_stat_cap_minutes_applies_under_outbreak(api):
    """PRD §3.3: "If the request's `priority_tier` is `STAT`, the target is
    then capped — it becomes the lesser of the rounded value and 45 minutes."
    PRD §3.2: "The request's `priority_tier` is the highest urgency tier among
    contributing demands."

    Design: Corner/calculations/stat_cap_minutes_applies_under_outbreak
    """
    from test_helpers.fixtures import setup_outbreak_active

    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_all_standards()
    setup_outbreak_active(unit["id"])
    bi1 = create_bed(unit["id"], "BI1", "ISOLATION")
    get_success_data(
        api.create_placement_demand(
            create_placement_demand_payload(
                unit_id=unit["id"], required_bed_kind="ISOLATION", urgency_tier="STAT"
            ),
            COORDINATOR,
        )
    )
    req = create_request(bi1["id"], "TERMINAL")
    assert req["priority_tier"] == "STAT"
    assert req["sla_target_minutes"] == 45
    assert_instant_equal(req["sla_due_at"], "2026-08-01T08:45:00Z")
    assert req["pinned_with_outbreak"] is True
    assert req["priority_score"] == pytest.approx(11050.0, abs=0.01)


def test_audit_fluorescent_threshold_boundary(api):
    """PRD §3.6: "For `FLUORESCENT_MARKER`, `threshold_used` is 0.85, and the
    result is `PASS` exactly when the `marker_fraction_removed` is greater than
    or equal to 0.85 — again, exactly at the boundary passes."

    Design: Corner/calculations/audit_fluorescent_threshold_boundary
    """
    ctx = setup_basic_scenario()
    # Drive two requests to PENDING_QA.
    bed2 = create_bed(ctx["unit"]["id"], "B2", "STANDARD")

    r1 = create_request(ctx["bed"]["id"], "ROUTINE")
    assign_request(r1["id"], ctx["tech"]["id"])
    start_request(r1["id"], ctx["tech"]["id"])
    set_clock("2026-08-01T08:45:00Z")
    complete_request(r1["id"], ctx["tech"]["id"])

    r2 = create_request(bed2["id"], "ROUTINE")
    assign_request(r2["id"], ctx["tech"]["id"])
    start_request(r2["id"], ctx["tech"]["id"])
    set_clock("2026-08-01T09:30:00Z")
    complete_request(r2["id"], ctx["tech"]["id"])

    au_pass = submit_audit(
        r1["id"],
        ctx["auditor"]["id"],
        audit_method="FLUORESCENT_MARKER",
        marker_fraction_removed=0.85,
    )
    assert au_pass["result"] == "PASS"
    assert au_pass["threshold_used"] == pytest.approx(0.85, abs=1e-9)

    au_fail = submit_audit(
        r2["id"],
        ctx["auditor"]["id"],
        audit_method="FLUORESCENT_MARKER",
        marker_fraction_removed=0.84,
    )
    assert au_fail["result"] == "FAIL"
    assert au_fail["threshold_used"] == pytest.approx(0.85, abs=1e-9)

    r1_after = get_success_data(api.get_clean_request(r1["id"], ANY))
    assert r1_after["status"] == "VERIFIED"
    b1_after = get_success_data(api.get_bed(ctx["bed"]["id"], ANY))
    assert b1_after["bed_status"] == "READY"

    r2_after = get_success_data(api.get_clean_request(r2["id"], ANY))
    assert r2_after["status"] == "NEEDS_RECLEAN"
    assert r2_after["reclean_count"] == 1
    b2_after = get_success_data(api.get_bed(bed2["id"], ANY))
    assert b2_after["bed_status"] == "VACANT_DIRTY"


def test_audit_threshold_follows_upgraded_clean_type(api):
    """PRD §3.6: "The threshold comes from the standard row for the request's
    *current* `clean_type`, so a request upgraded to `TERMINAL` by an outbreak
    is audited against the `TERMINAL` threshold."

    Design: Corner/calculations/audit_threshold_follows_upgraded_clean_type
    """
    from test_helpers.fixtures import setup_outbreak_active

    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_all_standards()
    seed_supplies()
    tech = create_technician("T1", certifications=["ISO_CERT"])
    get_success_data(api.clock_in_staff(tech["id"], make_technician_headers(tech["id"])))
    auditor = create_staff("A1", capabilities=("AUDIT",), display_name="Auditor One")
    bi1 = create_bed(unit["id"], "BI1", "ISOLATION")

    req = create_request(bi1["id"], "ISOLATION")
    assign_request(req["id"], tech["id"])
    setup_outbreak_active(unit["id"], pathogen_class="MRSA")

    upgraded = get_success_data(api.get_clean_request(req["id"], ANY))
    assert upgraded["clean_type"] == "TERMINAL"

    start_request(req["id"], tech["id"])
    set_clock("2026-08-01T09:00:00Z")
    complete_request(req["id"], tech["id"])
    au = submit_audit(req["id"], auditor["id"], rlu_reading=120)
    assert au["result"] == "FAIL"
    assert au["threshold_used"] == 100

    after = get_success_data(api.get_clean_request(req["id"], ANY))
    assert after["status"] == "NEEDS_RECLEAN"
    assert after["reclean_count"] == 1


def test_supply_bom_reclean_half_rate_rounding(api):
    """PRD §3.5: "When the request is in a reclean cycle — that is, it is being
    started with a `reclean_count` greater than zero — every line is halved,
    each line rounded half-up to a whole unit, so a `TERMINAL` reclean reserves
    3, 2, 4, and 1 across its four lines."

    Design: Corner/calculations/supply_bom_reclean_half_rate_rounding
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_all_standards()
    supplies = seed_supplies()
    t1 = create_technician("T1", certifications=["TERMINAL_CERT"])
    t2 = create_technician("T2", certifications=["TERMINAL_CERT"])
    auditor = create_staff("A1", capabilities=("AUDIT",), display_name="Auditor One")
    get_success_data(api.clock_in_staff(t1["id"], make_technician_headers(t1["id"])))
    get_success_data(api.clock_in_staff(t2["id"], make_technician_headers(t2["id"])))
    bed = create_bed(unit["id"], "B1", "STANDARD")

    req = create_request(bed["id"], "TERMINAL")
    assign_request(req["id"], t1["id"])
    start_request(req["id"], t1["id"])

    seal_after_first = get_success_data(
        api.get_supply_item(supplies["SEALANT"]["id"], ANY)
    )
    assert seal_after_first["reserved_quantity"] == 1

    set_clock("2026-08-01T09:30:00Z")
    complete_request(req["id"], t1["id"])
    submit_audit(req["id"], auditor["id"], rlu_reading=400)

    # Reclean leg at half rate.
    assign_request(req["id"], t2["id"])
    start_request(req["id"], t2["id"])
    seal_reclean = get_success_data(api.get_supply_item(supplies["SEALANT"]["id"], ANY))
    assert seal_reclean["reserved_quantity"] == 1
    assert seal_reclean["on_hand_quantity"] == 19

    set_clock("2026-08-01T10:00:00Z")
    complete_request(req["id"], t2["id"])

    d = get_success_data(api.get_supply_item(supplies["DISINFECTANT"]["id"], ANY))
    assert d["on_hand_quantity"] == 91
    assert d["reserved_quantity"] == 0
    p = get_success_data(api.get_supply_item(supplies["PPE_PACK"]["id"], ANY))
    assert p["on_hand_quantity"] == 45
    c = get_success_data(api.get_supply_item(supplies["CLOTH"]["id"], ANY))
    assert c["on_hand_quantity"] == 188
    s = get_success_data(api.get_supply_item(supplies["SEALANT"]["id"], ANY))
    assert s["on_hand_quantity"] == 18

    req_after = get_success_data(api.get_clean_request(req["id"], ANY))
    assert req_after["reclean_count"] == 1
    assert req_after["status"] == "PENDING_QA"


def test_productivity_zero_shift_seconds_yields_zero_score(api):
    """PRD §3.6: "The `productivity_score` itself is 0.00 while
    `shift_seconds_today` is zero."
    PRD §3.6: "Finally, `stat_eligible` holds when the technician has no
    verified cleans yet (`completed_clean_count` is zero) or when
    `productivity_score` has reached at least 80.00."

    Design: Corner/calculations/productivity_zero_shift_seconds_yields_zero_score
    """
    ctx = setup_basic_scenario()
    tech = ctx["tech"]
    req = create_request(ctx["bed"]["id"], "ROUTINE")
    assign_request(req["id"], tech["id"])
    start_request(req["id"], tech["id"])
    set_clock("2026-08-01T08:45:00Z")
    complete_request(req["id"], tech["id"])
    submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=100)

    prod = get_success_data(api.get_staff_productivity(tech["id"], ANY))
    assert prod["shift_seconds_today"] == 0
    assert prod["productivity_score"] == pytest.approx(0.0, abs=0.01)
    assert prod["verified_credit_total"] == pytest.approx(1.0, abs=0.01)
    assert prod["completed_clean_count"] == 1
    assert prod["stat_eligible"] is False


def test_productivity_efficiency_factor_floor_and_cap(api):
    """PRD §3.6: "The efficiency factor is the request's pinned
    `sla_target_minutes` divided by those actual minutes, clamped so it never
    falls below 0.50 and never exceeds 1.50. The per-clean credit is the base
    credit for the request's `clean_type` — 1.00 for `ROUTINE`, 1.50 for
    `ISOLATION`, 2.00 for `TERMINAL` — multiplied by the clamped factor, and it
    is rounded to two decimal places half-up **per clean, before summation**;
    `verified_credit_total` is the sum of those rounded credits."

    Design: Corner/calculations/productivity_efficiency_factor_floor_and_cap
    """
    ctx = setup_basic_scenario()
    tech = ctx["tech"]
    bed2 = create_bed(ctx["unit"]["id"], "B2", "STANDARD")

    # R1: 180 actual minutes -> ef 45/180 = 0.25 -> clamped 0.50 -> credit 0.50.
    r1 = create_request(ctx["bed"]["id"], "ROUTINE")
    assign_request(r1["id"], tech["id"])
    start_request(r1["id"], tech["id"])
    set_clock("2026-08-01T11:00:00Z")
    complete_request(r1["id"], tech["id"])
    submit_audit(r1["id"], ctx["auditor"]["id"], rlu_reading=100)

    # R2: 10 actual minutes -> ef 45/10 = 4.50 -> clamped 1.50 -> credit 1.50.
    r2 = create_request(bed2["id"], "ROUTINE")
    assign_request(r2["id"], tech["id"])
    start_request(r2["id"], tech["id"])
    set_clock("2026-08-01T11:10:00Z")
    complete_request(r2["id"], tech["id"])
    submit_audit(r2["id"], ctx["auditor"]["id"], rlu_reading=100)

    prod = get_success_data(api.get_staff_productivity(tech["id"], ANY))
    assert prod["verified_credit_total"] == pytest.approx(2.0, abs=0.01)
    assert prod["completed_clean_count"] == 2


def test_snapshot_empty_window_nulls_and_window_chaining(api):
    """PRD §3.9: "The window runs from the previous snapshot's `window_end` —
    or from the unit's `created_at` on the very first run — inclusive, up to
    the run's clock time, exclusive; the snapshot records those bounds as
    `window_start` and `window_end`, along with the unit's `ops_run_index`
    value *before* this run incremented it."
    PRD §3.9: "when the window's set is empty all four percentile fields are
    null and both counts are zero."

    Design: Corner/calculations/snapshot_empty_window_nulls_and_window_chaining
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_standard("ROUTINE")
    seed_supplies("DISINFECTANT", "CLOTH")
    tech = create_technician("T1")
    get_success_data(api.clock_in_staff(tech["id"], make_technician_headers(tech["id"])))
    auditor = create_staff("A1", capabilities=("AUDIT",), display_name="Auditor One")
    bed = create_bed(unit["id"], "B1", "STANDARD")

    # First run on an empty window.
    set_clock("2026-08-01T09:00:00Z")
    s1 = get_success_data(api.run_ops_run(unit["id"], ADMIN))
    assert_instant_equal(s1["window_start"], CLOCK_T0800)
    assert_instant_equal(s1["window_end"], "2026-08-01T09:00:00Z")
    assert s1["ops_run_index"] == 0
    assert s1["verified_count"] == 0
    assert s1["sla_breach_count"] == 0
    assert s1["tat_total_p50_minutes"] is None
    assert s1["tat_total_p90_minutes"] is None
    assert s1["tat_clean_p50_minutes"] is None
    assert s1["tat_clean_p90_minutes"] is None

    # Verify one clean inside the second window.
    req = create_request(bed["id"], "ROUTINE")
    assign_request(req["id"], tech["id"])
    start_request(req["id"], tech["id"])
    set_clock("2026-08-01T09:45:00Z")
    complete_request(req["id"], tech["id"])
    submit_audit(req["id"], auditor["id"], rlu_reading=100)

    set_clock("2026-08-01T10:00:00Z")
    s2 = get_success_data(api.run_ops_run(unit["id"], ADMIN))
    assert_instant_equal(s2["window_start"], "2026-08-01T09:00:00Z")
    assert_instant_equal(s2["window_end"], "2026-08-01T10:00:00Z")
    assert s2["ops_run_index"] == 1
    assert s2["verified_count"] == 1
    # verified_at 09:45 == sla_due_at 09:45 -> NOT strictly greater -> not a breach.
    assert s2["sla_breach_count"] == 0
    # bed created 08:00, never discharged -> tat_total = 105; tat_clean = 45.
    assert s2["tat_total_p50_minutes"] == 105
    assert s2["tat_clean_p50_minutes"] == 45

    unit_after = get_success_data(api.get_unit(unit["id"], ANY))
    assert unit_after["ops_run_index"] == 2


def test_snapshot_nearest_rank_percentile_selection(api):
    """PRD §3.9: "Percentiles use the nearest-rank method on the
    ascending-sorted series — the value at position ceiling of p hundredths
    times the set size, counting from one — with no interpolation."

    Design: Corner/calculations/snapshot_nearest_rank_percentile_selection
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_standard("ROUTINE")
    seed_supplies("DISINFECTANT", "CLOTH")
    auditor = create_staff("A1", capabilities=("AUDIT",), display_name="Auditor One")

    t1 = create_technician("T1")
    get_success_data(api.clock_in_staff(t1["id"], make_technician_headers(t1["id"])))
    b1 = create_bed(unit["id"], "B1", "STANDARD")
    r1 = create_request(b1["id"], "ROUTINE")
    assign_request(r1["id"], t1["id"])
    start_request(r1["id"], t1["id"])

    set_clock("2026-08-01T08:20:00Z")
    t2 = create_technician("T2")
    get_success_data(api.clock_in_staff(t2["id"], make_technician_headers(t2["id"])))
    b2 = create_bed(unit["id"], "B2", "STANDARD")
    r2 = create_request(b2["id"], "ROUTINE")
    assign_request(r2["id"], t2["id"])
    start_request(r2["id"], t2["id"])

    set_clock("2026-08-01T08:40:00Z")
    t3 = create_technician("T3")
    get_success_data(api.clock_in_staff(t3["id"], make_technician_headers(t3["id"])))
    b3 = create_bed(unit["id"], "B3", "STANDARD")
    r3 = create_request(b3["id"], "ROUTINE")
    assign_request(r3["id"], t3["id"])
    start_request(r3["id"], t3["id"])

    set_clock("2026-08-01T09:30:00Z")
    complete_request(r1["id"], t1["id"])
    complete_request(r2["id"], t2["id"])
    complete_request(r3["id"], t3["id"])
    submit_audit(r1["id"], auditor["id"], rlu_reading=100)
    submit_audit(r2["id"], auditor["id"], rlu_reading=100)
    submit_audit(r3["id"], auditor["id"], rlu_reading=100)

    set_clock("2026-08-01T09:31:00Z")
    snap = get_success_data(api.run_ops_run(unit["id"], ADMIN))
    assert snap["verified_count"] == 3
    assert snap["sla_breach_count"] == 3
    assert snap["tat_total_p50_minutes"] == 70
    assert snap["tat_total_p90_minutes"] == 90
    assert snap["tat_clean_p50_minutes"] == 70
    assert snap["tat_clean_p90_minutes"] == 90

    b1_after = get_success_data(api.get_bed(b1["id"], ANY))
    assert b1_after["tat_total_minutes"] == 90
    b2_after = get_success_data(api.get_bed(b2["id"], ANY))
    assert b2_after["tat_total_minutes"] == 70
    b3_after = get_success_data(api.get_bed(b3["id"], ANY))
    assert b3_after["tat_total_minutes"] == 50
