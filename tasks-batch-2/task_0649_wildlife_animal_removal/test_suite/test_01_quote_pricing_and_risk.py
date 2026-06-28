"""Quote pricing (provisional/final, round-then-sum, emergency surcharge) and
infestation-risk scoring (initial/residual, weighted non-linear, regulated bump).

Covers difficulty queue A rules dual_variant_calc (cost + risk domains) and
combinatorial_formula, plus corner-queue calculation/consistency instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    create_capture_payload,
    make_field_technician_headers,
    make_property_owner_headers,
    setup_open_work_order,
    setup_sent_quote,
    setup_draft_quote,
    set_trap,
    relocate_capture,
    pull_trap,
    start_repair,
    complete_repair,
    fetch_work_order,
    fetch_quote,
)
import test_helpers as th

api = th.api_client


# ─── dual_variant_calc / quote_total_provisional_vs_final_cost_domain ────────

def test_provisional_total_sums_all_line_items_round_then_sum():
    """PRD §3.3: "Each line's raw amount is rounded to the nearest whole cent using
    round-half-up, and the rounded line amounts are then summed to give `provisional_total_cents`."
    PRD §3.3: "On send, the system computes `provisional_total_cents` as the forward-looking
    estimate over **all** line items."

    Design: Difficulty/dual_variant_calc/quote_total_provisional_vs_final_cost_domain
    """
    base = setup_sent_quote(
        entry_points=[
            {"severity": "MAJOR", "estimated_individuals": 4, "location_label": "NE soffit"},
            {"severity": "MODERATE", "estimated_individuals": 3, "location_label": "SW vent"},
        ],
        line_items=[
            {"line_type": "TRAP", "quantity": 3, "unit_price_cents": 4000},
            {"line_type": "TRAP", "quantity": 2, "unit_price_cents": 5500},
            {"line_type": "EXCLUSION", "quantity": 2, "unit_price_cents": 9000},
        ],
    )
    assert base["quote"]["provisional_total_cents"] == 41000, (
        f"Expected provisional 41000, got {base['quote']['provisional_total_cents']}"
    )


def test_final_total_sums_only_performed_lines_at_close():
    """PRD §3.7: "The **final total** is computed when the work order auto-closes and is the
    chronological actual: it sums only the line items whose `performed` flag is true."
    PRD §3.7: "The final total diverges from the provisional whenever any quoted line went
    unperformed."

    Design: Difficulty/dual_variant_calc/quote_total_provisional_vs_final_cost_domain
    """
    # EP1 + EP2; TRAP qty3@4000, TRAP qty2@5500, EXCLUSION qty2@9000.
    # Only the first trap (sp species) is SET-then-relocated; second TRAP line never set.
    # Both exclusion repairs (ep1, ep2) completed. final == 30000 (one TRAP line + EXCLUSION line).
    base = setup_open_work_order(
        entry_points=[
            {"severity": "MAJOR", "estimated_individuals": 4, "location_label": "NE soffit"},
            {"severity": "MODERATE", "estimated_individuals": 3, "location_label": "SW vent"},
        ],
        line_items=[
            {"line_type": "TRAP", "quantity": 3, "unit_price_cents": 4000},
            {"line_type": "TRAP", "quantity": 2, "unit_price_cents": 5500},
            {"line_type": "EXCLUSION", "quantity": 2, "unit_price_cents": 9000},
        ],
    )
    wo = base["work_order"]
    tech = base["technician"]
    sp_id = base["species"][0]["id"]
    ep1, ep2 = base["entry_points"]

    trap = set_trap(wo["id"], sp_id, tech["id"])
    relocate_capture(trap["id"], tech["id"], release_latitude=40.145)  # removal -> CLEARED
    rep1 = start_repair(wo["id"], ep1["id"], tech["id"])
    rep2 = start_repair(wo["id"], ep2["id"], tech["id"])
    complete_repair(wo["id"], rep1["id"], tech["id"])
    complete_repair(wo["id"], rep2["id"], tech["id"])  # exclusion -> SEALED, auto-close

    quote = fetch_quote(base["quote"]["id"])
    wo_final = fetch_work_order(wo["id"])
    assert wo_final["lifecycle"] == "CLOSED", f"Expected CLOSED, got {wo_final['lifecycle']}"
    assert quote["provisional_total_cents"] == 41000
    assert quote["final_total_cents"] == 30000, (
        f"Expected final 30000, got {quote['final_total_cents']}"
    )


# ─── dual_variant_calc / infestation_risk_initial_vs_residual_risk_domain ────

def test_initial_risk_score_over_all_entry_points_at_accept():
    """PRD §3.4: "Its `initial_risk_score` is computed as the forward-looking infestation
    score over **all** entry points of the inspection (the initial variant), and its
    `net_charged_cents` is initialized to the quote's `provisional_total_cents`."
    PRD §3.4: "The initial variant computed at acceptance sums over every entry point of the
    inspection (none are sealed yet)"

    Design: Difficulty/dual_variant_calc/infestation_risk_initial_vs_residual_risk_domain
    """
    # EP1 regulated risk_weight 2.0, individuals 4, MAJOR => 4*2.0*3.5*1.5 = 42.0
    # EP2 non-regulated risk_weight 1.0, individuals 3, MODERATE => 3*1.0*2.0 = 6.0; total 48.0
    sp_reg = th.create_species(is_regulated=True, risk_weight=2.0,
                               relocation_min_miles=5, relocation_max_miles=25,
                               common_name="Bat")
    sp_n = th.create_species(is_regulated=False, risk_weight=1.0,
                             relocation_min_miles=0, relocation_max_miles=50,
                             common_name="Mouse")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5),
        entry_points=[
            {"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 4},
            {"species": sp_n, "severity": "MODERATE", "estimated_individuals": 3},
        ],
        line_items=[
            {"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000},
            {"species": sp_reg, "line_type": "EXCLUSION", "quantity": 1, "unit_price_cents": 9000},
        ],
    )
    assert base["work_order"]["initial_risk_score"] == 48.0, (
        f"Expected initial 48.0, got {base['work_order']['initial_risk_score']}"
    )


def test_residual_risk_score_over_open_entry_points_at_close():
    """PRD §3.6: "the `residual_risk_score` is recomputed using the residual variant of the
    infestation score over only the entry points whose `seal_status` remains `OPEN`"
    PRD §3.4: "the residual variant computed at close (see §3.6) sums over only the entry
    points whose `seal_status` is still `OPEN`, so it diverges from the initial score by the
    contribution of every entry point that was sealed."

    Design: Difficulty/dual_variant_calc/infestation_risk_initial_vs_residual_risk_domain
    """
    # Both entry points non-regulated here (so the trap may be SET/pulled without a permit).
    sp_reg = th.create_species(is_regulated=False, risk_weight=2.0,
                               relocation_min_miles=0, relocation_max_miles=50,
                               common_name="Bat")
    sp_n = th.create_species(is_regulated=False, risk_weight=1.0,
                             relocation_min_miles=0, relocation_max_miles=50,
                             common_name="Mouse")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5),
        entry_points=[
            {"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 4},
            {"species": sp_n, "severity": "MODERATE", "estimated_individuals": 3},
        ],
        line_items=[
            {"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000},
            {"species": sp_reg, "line_type": "EXCLUSION", "quantity": 1, "unit_price_cents": 9000},
        ],
    )
    wo = base["work_order"]
    tech = base["technician"]
    ep1, ep2 = base["entry_points"]  # ep1 stays OPEN, ep2 sealed

    trap = set_trap(wo["id"], sp_reg["id"], tech["id"])
    pull_trap(trap["id"], tech["id"])  # removal -> CLEARED
    rep2 = start_repair(wo["id"], ep2["id"], tech["id"])
    complete_repair(wo["id"], rep2["id"], tech["id"])  # only ep2 sealed; exclusion SEALED -> close

    wo_final = fetch_work_order(wo["id"])
    assert wo_final["lifecycle"] == "CLOSED", f"Expected CLOSED, got {wo_final['lifecycle']}"
    # initial over both EPs = 4*2.0*3.5 + 3*1.0*2.0 = 28.0 + 6.0 = 34.0.
    assert wo_final["initial_risk_score"] == 34.0
    # residual over only the still-OPEN ep1 = 4*2.0*3.5 = 28.0; diverges by ep2's 6.0 contribution.
    assert wo_final["residual_risk_score"] == 28.0, (
        f"Expected residual 28.0, got {wo_final['residual_risk_score']}"
    )


# ─── combinatorial_formula / quote_round_then_sum_emergency_order_pinned_mode_b ─

def test_emergency_surcharge_round_then_sum_pinned_order():
    """PRD §3.3: "For each line, the raw amount is the `quantity` multiplied by
    `unit_price_cents`, multiplied by the surcharge factor — that factor is 1 plus fifteen
    percent when the quote's `emergency_flag` is set, and exactly 1 otherwise."
    PRD §2.7: "The rounding order is fixed as round-then-sum and must not be reordered to
    sum-then-round."

    Design: Difficulty/combinatorial_formula/quote_round_then_sum_emergency_order_pinned_mode_b
    """
    # Emergency inspection; three TRAP lines each qty 1 @110. Raw line = 110*1.15 = 126.50 ->
    # round-half-up 127; sum = 381. (sum-then-round would yield 380.)
    base = setup_sent_quote(
        is_emergency=True,
        line_items=[
            {"line_type": "TRAP", "quantity": 1, "unit_price_cents": 110},
            {"line_type": "TRAP", "quantity": 1, "unit_price_cents": 110},
            {"line_type": "TRAP", "quantity": 1, "unit_price_cents": 110},
        ],
    )
    assert base["quote"]["emergency_flag"] is True
    assert base["quote"]["provisional_total_cents"] == 381, (
        f"Expected 381 (round-then-sum), got {base['quote']['provisional_total_cents']}"
    )


def test_emergency_flag_pinned_from_inspection_at_quote_creation():
    """PRD §3.3: "The quote is born in `DRAFT` status, and its `emergency_flag` is copied from
    the parent inspection's `is_emergency` at creation time so the surcharge basis is pinned
    even if the inspection later changes."

    Design: Difficulty/combinatorial_formula/quote_round_then_sum_emergency_order_pinned_mode_b
    """
    base = setup_draft_quote(
        is_emergency=True,
        line_items=[{"line_type": "TRAP", "quantity": 1, "unit_price_cents": 110}],
    )
    assert base["quote"]["emergency_flag"] is True


# ─── combinatorial_formula / infestation_risk_weighted_nonlinear_mode_a ──────

def test_infestation_risk_weighted_nonlinear_with_regulated_bump():
    """PRD §3.4: "For each entry point in the variant's input set, the contribution is the
    entry point's `estimated_individuals` multiplied by its species' `risk_weight`, multiplied
    by a severity factor — 1.0 for `MINOR`, 2.0 for `MODERATE`, and 3.5 for `MAJOR`."
    PRD §3.4: "If that entry point's species `is_regulated`, the contribution is then
    multiplied by 1.5."

    Design: Difficulty/combinatorial_formula/infestation_risk_weighted_nonlinear_mode_a
    """
    # EP1 regulated weight 2.0, individuals 4, MAJOR => 4*2.0*3.5*1.5 = 42.0
    # EP2 non-regulated weight 1.0, individuals 3, MODERATE => 3*1.0*2.0 = 6.0; total 48.0
    sp_reg = th.create_species(is_regulated=True, risk_weight=2.0,
                               relocation_min_miles=5, relocation_max_miles=25,
                               common_name="Fox")
    sp_n = th.create_species(is_regulated=False, risk_weight=1.0,
                             relocation_min_miles=0, relocation_max_miles=50,
                             common_name="Rat")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5),
        entry_points=[
            {"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 4},
            {"species": sp_n, "severity": "MODERATE", "estimated_individuals": 3},
        ],
        line_items=[
            {"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000},
        ],
    )
    assert base["work_order"]["initial_risk_score"] == 48.0, (
        f"Expected 48.0, got {base['work_order']['initial_risk_score']}"
    )


def test_infestation_risk_regulated_branch_multiplies_by_one_point_five():
    """PRD §3.4: "If that entry point's species `is_regulated`, the contribution is then
    multiplied by 1.5."

    Design: Difficulty/combinatorial_formula/infestation_risk_weighted_nonlinear_mode_a
    """
    # Single regulated EP: individuals 2, MAJOR, weight 2.0 => 2*2.0*3.5*1.5 = 21.0
    sp_reg = th.create_species(is_regulated=True, risk_weight=2.0,
                               relocation_min_miles=5, relocation_max_miles=25,
                               common_name="Coyote")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5),
        entry_points=[{"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 2}],
        line_items=[
            {"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000},
        ],
    )
    assert base["work_order"]["initial_risk_score"] == 21.0, (
        f"Expected 21.0, got {base['work_order']['initial_risk_score']}"
    )


# ─── Corner: calculations.relocation_distance_below_min_band_edge_rejected ───

def test_relocation_below_min_band_edge_rejected():
    """PRD §3.6: "The release is lawful only when this rounded distance is at least the
    species' `relocation_min_miles` and at most its `relocation_max_miles` — both band edges
    inclusive; a distance outside the band is rejected with `ERR_RELOCATION_DISTANCE` and no
    capture persists."

    Design: Corner/calculations/relocation_distance_below_min_band_edge_rejected
    """
    sp = th.create_species(relocation_min_miles=5, relocation_max_miles=25, common_name="Mink")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    trap = set_trap(wo["id"], sp["id"], tech["id"])
    # Release at 40.05 -> 3.45 mi (< min 5) -> reject; trap stays SET.
    res = api.create_capture(
        trap["id"],
        create_capture_payload(release_latitude=40.05, release_longitude=-75.0),
        make_field_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_RELOCATION_DISTANCE", expected_status=422)
    trap_after = th.fetch_trap_placement(trap["id"])
    assert trap_after["status"] == "SET", f"Expected SET (no capture persisted), got {trap_after['status']}"


# ─── Corner: calculations.relocation_distance_compliant_release_persists ─────

def test_compliant_relocation_persists_with_computed_distance():
    """PRD §3.6: "The server computes `release_distance_miles` as the great-circle (haversine)
    distance from the property's coordinates to the release site, using an Earth radius of
    3958.8 miles, rounded to two decimal places using round-half-up."
    PRD §3.6: "On a compliant release a capture event is created with `disposition` of
    `RELOCATED` (the only disposition that ever persists), and the trap moves from `SET` to
    `SPENT`."

    Design: Corner/calculations/relocation_distance_compliant_release_persists
    """
    sp = th.create_species(relocation_min_miles=5, relocation_max_miles=25, common_name="Coon")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    trap = set_trap(wo["id"], sp["id"], tech["id"])

    res = api.create_capture(
        trap["id"],
        create_capture_payload(release_latitude=40.145, release_longitude=-75.0),
        make_field_technician_headers(tech["id"]),
    )
    capture = validate_success(res, 201)
    assert capture["release_distance_miles"] == 10.02, (
        f"Expected 10.02, got {capture['release_distance_miles']}"
    )
    assert capture["disposition"] == "RELOCATED"


# ─── Corner: calculations.warranty_window_within_deadline_accepted ───────────

def test_warranty_claim_within_deadline_and_qualified_accepted():
    """PRD §3.9: "The claim is eligible when its `reported_at` is at or before the warranty
    deadline, where the deadline is the work order's close timestamp plus thirty days and the
    boundary is inclusive (a `reported_at` exactly equal to the deadline still accepts)."
    PRD §3.9: "The claim is accepted (status `ACCEPTED`) only when it is both eligible and
    qualified"

    Design: Corner/calculations/warranty_window_within_deadline_accepted
    """
    base = th.setup_closed_work_order_via_pull_and_seal(clock_at="2026-05-01T00:00:00Z")
    wo = base["work_order"]
    assert wo["lifecycle"] == "CLOSED"
    owner = make_property_owner_headers(base["account"]["id"])

    claim = validate_success(api.create_warranty_claim(
        wo["id"], th.create_warranty_claim_payload(reported_at="2026-05-15T00:00:00Z",
                                                    description="noise again"),
        owner), 201)
    adjudicated = validate_success(
        api.adjudicate_warranty_claim(claim["id"], th.TEST_USERS["compliance_officer_headers"]), 200)
    assert adjudicated["status"] == "ACCEPTED", (
        f"Expected ACCEPTED, got {adjudicated['status']}"
    )


# ─── Corner: consistency_model.immediate_visibility_of_provisional_total ─────

def test_send_response_carries_provisional_total_immediately():
    """PRD §3.3: "On send, the system computes `provisional_total_cents` as the forward-looking
    estimate over **all** line items."
    PRD §2.5: "The system applies these cascades synchronously and immediately: by the time a
    write returns, every dependent resource it touched has been updated, its `updated_at`
    refreshed, and its `version` incremented."

    Design: Corner/consistency_model/immediate_visibility_of_provisional_total_in_send_response
    """
    base = setup_draft_quote(
        line_items=[{"line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    res = api.send_quote(base["quote"]["id"], th.TEST_USERS["dispatcher_headers"])
    sent = validate_success(res, 200)
    assert sent["provisional_total_cents"] == 4000, (
        f"Expected 4000 in send response, got {sent['provisional_total_cents']}"
    )
