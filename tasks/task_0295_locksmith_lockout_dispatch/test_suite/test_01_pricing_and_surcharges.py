"""Quote pricing: the dispatch estimate vs the measured final, the after-hours and
emergency-lockout surcharge multipliers, and round-per-line precision.

Difficulty queue: dual_variant_calc (money), combinatorial_formula (mode-a, mode-b),
boundary_precision (1080 threshold). Corner queue: calculations baselines.
"""
from test_helpers import (
    validate_success,
    make_technician_headers,
    drive_job_to_on_site,
    draft_quote,
)


# ─── dual_variant_calc / quote_estimate_vs_final_money_divergence ──────────────
def test_estimate_and_final_diverge_for_same_quote(api):
    """PRD §3.5: "At draft time the system computes the quote's estimated_total_cents,
    a forward-looking dispatch estimate that uses only the flat call-out rate for the
    job's service_type and ignores measured labor and parts entirely."
    PRD §3.5: "The final total is a measured aggregation and diverges from the estimate
    because it adds the labor and parts the estimate omitted."

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_final_money_divergence
    """
    job, tech, _ = drive_job_to_on_site(
        customer_user_id="cust-dv1", service_type="REKEY", arrived_at_minute=645,
        job_overrides={"requested_at_minute": 600},
    )
    tech_h = make_technician_headers(tech["id"])
    quote = draft_quote(
        job["id"], tech["id"], labor_hours=2.5,
        part_lines=[{"lock_part_id": "x", "unit_price_cents": 1500, "quantity": 2},
                    {"lock_part_id": "y", "unit_price_cents": 999, "quantity": 3}],
    )
    assert quote["estimated_total_cents"] == 12000, (
        f"REKEY flat base 12000 expected, got {quote['estimated_total_cents']}"
    )
    submitted = validate_success(api.submit_quote(quote["id"], tech_h), 200)
    # labor 8000*2.5*1.0=20000; line1 1500*2=3000; line2 999*3=2997; total 25997
    assert submitted["final_total_cents"] == 25997, (
        f"final 25997 expected, got {submitted['final_total_cents']}"
    )
    assert submitted["estimated_total_cents"] != submitted["final_total_cents"]


def test_estimate_omits_labor_and_parts_at_draft(api):
    """PRD §3.5: "At draft time the system computes the quote's estimated_total_cents,
    a forward-looking dispatch estimate that uses only the flat call-out rate for the
    job's service_type and ignores measured labor and parts entirely."

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_final_money_divergence
    """
    job, tech, _ = drive_job_to_on_site(
        customer_user_id="cust-dv2", service_type="REKEY", arrived_at_minute=645,
        job_overrides={"requested_at_minute": 600},
    )
    # Two different labor/part loads must yield the SAME draft estimate (flat base only).
    quote_a = draft_quote(job["id"], tech["id"], labor_hours=2.5,
                          part_lines=[{"lock_part_id": "x", "unit_price_cents": 1500, "quantity": 2}])
    assert quote_a["estimated_total_cents"] == 12000


# ─── combinatorial_formula / final_total_nonlinear_multi_input_mode_a ──────────
def test_final_total_stacks_after_hours_and_emergency_lockout(api):
    """PRD §3.6: "if the job is flagged is_emergency and its service_type is LOCKOUT,
    the multiplier is further multiplied by 1.25; this emergency surcharge stacks only
    for emergency lockouts and never for other service types, even when flagged as
    emergencies."
    PRD §3.5: "The labor line is the labor rate of 8000 cents per hour multiplied by
    the quote's labor_hours and by the surcharge multiplier, rounded half up to whole
    cents."

    Design: Difficulty/combinatorial_formula/final_total_nonlinear_multi_input_mode_a
    """
    job, tech, _ = drive_job_to_on_site(
        customer_user_id="cust-cf1", service_type="LOCKOUT", arrived_at_minute=1130,
        base_travel_minutes=15,
        job_overrides={"is_emergency": True, "requested_at_minute": 1100},
    )
    tech_h = make_technician_headers(tech["id"])
    quote = draft_quote(job["id"], tech["id"], labor_hours=1.0,
                        part_lines=[{"lock_part_id": "x", "unit_price_cents": 333, "quantity": 1}])
    submitted = validate_success(api.submit_quote(quote["id"], tech_h), 200)
    # multiplier 1.5*1.25=1.875; labor 8000*1*1.875=15000; part round(333*1.875)=624; 15624
    assert submitted["final_total_cents"] == 15624, (
        f"final 15624 expected, got {submitted['final_total_cents']}"
    )


def test_final_total_dispatch_estimate_after_hours_lockout(api):
    """PRD §3.5: "The estimate is that base rate multiplied by the job's surcharge
    multiplier (§3.6), rounded half up to whole cents."
    PRD §3.6: "If the requested time falls in the after-hours window, it is multiplied
    by 1.5."

    Design: Difficulty/combinatorial_formula/final_total_nonlinear_multi_input_mode_a
    """
    job, tech, _ = drive_job_to_on_site(
        customer_user_id="cust-cf1b", service_type="LOCKOUT", arrived_at_minute=1130,
        base_travel_minutes=15,
        job_overrides={"is_emergency": True, "requested_at_minute": 1100},
    )
    quote = draft_quote(job["id"], tech["id"], labor_hours=1.0,
                        part_lines=[{"lock_part_id": "x", "unit_price_cents": 333, "quantity": 1}])
    # LOCKOUT base 9000 * 1.875 = 16875
    assert quote["estimated_total_cents"] == 16875, (
        f"estimate 16875 expected, got {quote['estimated_total_cents']}"
    )


# ─── combinatorial_formula / final_total_round_per_line_then_sum_mode_b ────────
def test_final_total_rounds_per_line_not_sum_then_round(api):
    """PRD §3.5: "The rounding is applied per line — each part line and the labor line
    are rounded individually and only then added — and must not be computed by summing
    raw products and rounding once at the end."

    Design: Difficulty/combinatorial_formula/final_total_round_per_line_then_sum_mode_b
    """
    job, tech, _ = drive_job_to_on_site(
        customer_user_id="cust-cf2", service_type="LOCKOUT", arrived_at_minute=1130,
        base_travel_minutes=15,
        job_overrides={"is_emergency": True, "requested_at_minute": 1100},
    )
    tech_h = make_technician_headers(tech["id"])
    quote = draft_quote(
        job["id"], tech["id"], labor_hours=1.0,
        part_lines=[{"lock_part_id": "x", "unit_price_cents": 333, "quantity": 1},
                    {"lock_part_id": "y", "unit_price_cents": 333, "quantity": 1}],
    )
    submitted = validate_success(api.submit_quote(quote["id"], tech_h), 200)
    # per line round(333*1.875)=624 each -> 624+624=1248; labor 15000; total 16248
    # (sum-then-round would give 16249)
    assert submitted["final_total_cents"] == 16248, (
        f"round-per-line total 16248 expected, got {submitted['final_total_cents']}"
    )


def test_two_part_lines_each_rounded_independently(api):
    """PRD §3.5: "walking the part_lines in the order they were submitted, each line
    contributes its unit_price_cents multiplied by its quantity and by the surcharge
    multiplier, rounded half up to whole cents for that line; these per-line amounts
    are accumulated."

    Design: Difficulty/combinatorial_formula/final_total_round_per_line_then_sum_mode_b
    """
    job, tech, _ = drive_job_to_on_site(
        customer_user_id="cust-cf2b", service_type="LOCKOUT", arrived_at_minute=1130,
        base_travel_minutes=15,
        job_overrides={"is_emergency": True, "requested_at_minute": 1100},
    )
    tech_h = make_technician_headers(tech["id"])
    quote = draft_quote(
        job["id"], tech["id"], labor_hours=1.0,
        part_lines=[{"lock_part_id": "x", "unit_price_cents": 333, "quantity": 1},
                    {"lock_part_id": "y", "unit_price_cents": 333, "quantity": 1}],
    )
    submitted = validate_success(api.submit_quote(quote["id"], tech_h), 200)
    assert submitted["final_total_cents"] == 16248


# ─── boundary_precision_check / after_hours_surcharge_threshold_1080_inclusive ─
def test_after_hours_surcharge_at_1080_inclusive(api):
    """PRD §3.6: "a request at or after minute 1080 (18:00), through the end of the
    day, is after-hours"
    PRD §3.6: "the boundary is inclusive at 1080 (minute 1080 triggers the surcharge,
    minute 1079 does not) and the morning cutoff at 480 is exclusive (minute 479 is
    after-hours, minute 480 is not)."

    Design: Difficulty/boundary_precision_check/after_hours_surcharge_threshold_1080_inclusive
    """
    job, tech, _ = drive_job_to_on_site(
        customer_user_id="cust-bp1", service_type="LOCKOUT", arrived_at_minute=1110,
        base_travel_minutes=15,
        job_overrides={"requested_at_minute": 1080},
    )
    quote = draft_quote(job["id"], tech["id"], labor_hours=0, part_lines=[])
    # LOCKOUT base 9000 * 1.5 = 13500
    assert quote["estimated_total_cents"] == 13500, (
        f"1080 triggers after-hours -> 13500, got {quote['estimated_total_cents']}"
    )


def test_after_hours_surcharge_not_applied_at_1079(api):
    """PRD §3.6: "the boundary is inclusive at 1080 (minute 1080 triggers the
    surcharge, minute 1079 does not) and the morning cutoff at 480 is exclusive
    (minute 479 is after-hours, minute 480 is not)."

    Design: Difficulty/boundary_precision_check/after_hours_surcharge_threshold_1080_inclusive
    """
    job, tech, _ = drive_job_to_on_site(
        customer_user_id="cust-bp1b", service_type="LOCKOUT", arrived_at_minute=1110,
        base_travel_minutes=15,
        job_overrides={"requested_at_minute": 1079},
    )
    quote = draft_quote(job["id"], tech["id"], labor_hours=0, part_lines=[])
    assert quote["estimated_total_cents"] == 9000, (
        f"1079 below threshold -> flat 9000, got {quote['estimated_total_cents']}"
    )


# ─── Corner: calculations baselines ───────────────────────────────────────────
def test_daytime_rekey_estimate_no_surcharge(api):
    """PRD §3.5: "The flat call-out rates are 9000 cents for LOCKOUT, 12000 cents for
    REKEY, 15000 cents for INSTALL, and 20000 cents for SAFE."
    PRD §3.6: "The multiplier starts at 1.0."

    Design: Corner/calculations/estimate_no_surcharge_daytime_baseline
    """
    job, tech, _ = drive_job_to_on_site(
        customer_user_id="cust-base", service_type="REKEY", arrived_at_minute=640,
        job_overrides={"requested_at_minute": 600},
    )
    quote = draft_quote(job["id"], tech["id"], labor_hours=1.0, part_lines=[])
    assert quote["estimated_total_cents"] == 12000


def test_after_hours_just_below_1080_no_surcharge(api):
    """PRD §3.6: "the after-hours surcharge applies when requested_at_minute is at
    least 1080 or is strictly less than 480; the boundary is inclusive at 1080
    (minute 1080 triggers the surcharge, minute 1079 does not) and the morning cutoff
    at 480 is exclusive (minute 479 is after-hours, minute 480 is not)."

    Design: Corner/calculations/after_hours_below_threshold_no_surcharge_1079
    """
    job, tech, _ = drive_job_to_on_site(
        customer_user_id="cust-1079", service_type="LOCKOUT", arrived_at_minute=1110,
        base_travel_minutes=10,
        job_overrides={"requested_at_minute": 1079},
    )
    quote = draft_quote(job["id"], tech["id"], labor_hours=1.0, part_lines=[])
    assert quote["estimated_total_cents"] == 9000


def test_emergency_surcharge_does_not_stack_for_non_lockout(api):
    """PRD §3.6: "this emergency surcharge stacks only for emergency lockouts and
    never for other service types, even when flagged as emergencies."

    Design: Corner/calculations/emergency_surcharge_only_stacks_for_lockout
    """
    job, tech, _ = drive_job_to_on_site(
        customer_user_id="cust-em", service_type="REKEY", arrived_at_minute=640,
        job_overrides={"is_emergency": True, "requested_at_minute": 600},
    )
    quote = draft_quote(job["id"], tech["id"], labor_hours=1.0, part_lines=[])
    # daytime REKEY, emergency flag ignored (not LOCKOUT) -> 12000
    assert quote["estimated_total_cents"] == 12000
