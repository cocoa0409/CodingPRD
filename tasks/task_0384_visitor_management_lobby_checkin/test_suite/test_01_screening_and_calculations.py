"""Screening decisions, risk scoring, and delivery-handling calculations.

Difficulty queue (A): dual_variant_calc, combinatorial_formula,
non_linear_state_machine (screening fork).
"""
from test_helpers import (
    validate_success,
    setup_site_floor_host, setup_site_host,
    create_visit, screen_visit, create_watchlist_entry,
    create_delivery,
    TEST_USERS,
)

LA = TEST_USERS["lobby_attendant_headers"]


def test_delivery_invoice_rounds_per_parcel_then_sums(api):
    """PRD 3.8: "for each fee in `parcel_fees_cents`, in the array order submitted,
    multiply the fee by 1.075 (a 7.5 percent surcharge), round that single parcel's
    surcharged amount half-up to whole cents, and only then add it to the running
    total. Rounding each parcel before summing produces a different total than
    summing the raw surcharged amounts and rounding once; only the
    round-per-parcel-then-sum order is correct."

    Parcels [107,107,113] at 7.5%: 115.025->115, 115.025->115, 121.475->121;
    sum = 351 (not the 352 the rejected sum-then-round order gives).

    Design: Difficulty/dual_variant_calc/dvc_delivery_invoice_round_order_on_deliverylog
    """
    site, host = setup_site_host()
    res = api.create_delivery(
        {"host_id": host["id"], "carrier": "FEDEX", "parcel_fees_cents": [107, 107, 113]},
        LA,
    )
    delivery = validate_success(res, 201)
    assert delivery["handling_invoice_cents"] == 351, (
        f"expected 351, got {delivery['handling_invoice_cents']}"
    )
    assert delivery["status"] == "RECEIVED"


def test_delivery_invoice_nested_rounding_order_mode_b(api):
    """PRD 3.8: "multiply the fee by 1.075 (a 7.5 percent surcharge), round that
    single parcel's surcharged amount half-up to whole cents, and only then add it
    to the running total. Rounding each parcel before summing produces a different
    total than summing the raw surcharged amounts and rounding once; only the
    round-per-parcel-then-sum order is correct."

    Parcels [107,107,113] -> 115+115+121 = 351 (rounding before summing).

    Design: Difficulty/combinatorial_formula/cf_delivery_invoice_nested_rounding_order_mode_b
    """
    site, host = setup_site_host()
    res = api.create_delivery(
        {"host_id": host["id"], "carrier": "UPS", "parcel_fees_cents": [107, 107, 113]},
        LA,
    )
    delivery = validate_success(res, 201)
    assert delivery["handling_invoice_cents"] == 351, (
        f"expected 351, got {delivery['handling_invoice_cents']}"
    )


def test_screening_deny_dominates_review_routes_to_denied(api):
    """PRD 3.4: "`DENY` strictly dominates `REVIEW`, so a visit that matches both a
    `DENY` entry and a `REVIEW` entry is denied, not flagged — severity dominance is
    evaluated before review routing, which makes the result deterministic regardless
    of entry order."
    PRD 3.4: "The raw score adds 50 for a name hit, 30 for a company hit, and 15 for
    a missing photo ID; these three contributions are independent and additive."

    NAME DENY + COMPANY REVIEW, id_scanned true -> risk_score 80, status DENIED.

    Design: Difficulty/dual_variant_calc/dvc_screening_decision_dominance_on_visit
    """
    site, floor, host = setup_site_floor_host()
    create_watchlist_entry(site["id"], "NAME", "jordan blake", severity="DENY", active=True)
    create_watchlist_entry(site["id"], "COMPANY", "acme corp", severity="REVIEW", active=True)
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Jordan Blake", visitor_company="Acme Corp", id_scanned=True,
    )
    screened = validate_success(api.screen_visit(visit["id"], LA))
    assert screened["status"] == "DENIED", f"expected DENIED, got {screened['status']}"
    assert screened["risk_score"] == 80, f"expected 80, got {screened['risk_score']}"


def test_risk_score_three_input_weighted_sum_under_clamp(api):
    """PRD 3.4: "The raw score adds 50 for a name hit, 30 for a company hit, and 15
    for a missing photo ID; these three contributions are independent and additive.
    The resulting `risk_score` is the raw total clamped into the inclusive range 0 to
    100 — values below 0 become 0 and values above 100 become 100, though with these
    weights the natural ceiling is 95."
    PRD 3.4: "`DENY` strictly dominates `REVIEW`, so a visit that matches both a
    `DENY` entry and a `REVIEW` entry is denied, not flagged".

    NAME DENY + COMPANY REVIEW + id_scanned false -> 50+30+15 = 95 (under ceiling),
    status DENIED.

    Design: Difficulty/combinatorial_formula/cf_risk_score_three_input_nonlinear_clamp_mode_a
    """
    site, floor, host = setup_site_floor_host()
    create_watchlist_entry(site["id"], "NAME", "jordan blake", severity="DENY", active=True)
    create_watchlist_entry(site["id"], "COMPANY", "acme corp", severity="REVIEW", active=True)
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Jordan Blake", visitor_company="Acme Corp", id_scanned=False,
    )
    screened = validate_success(api.screen_visit(visit["id"], LA))
    assert screened["risk_score"] == 95, f"expected 95, got {screened['risk_score']}"
    assert screened["status"] == "DENIED", f"expected DENIED, got {screened['status']}"


def test_screening_review_only_match_routes_to_flagged(api):
    """PRD 3.4: "On a REVIEW decision it auto-advances `SCREENING` to `FLAGGED`,
    parking the visit for security adjudication."
    PRD 3.4: "The raw score adds 50 for a name hit, 30 for a company hit, and 15 for
    a missing photo ID; these three contributions are independent and additive."

    Only one active COMPANY REVIEW entry matches (company hit, id_scanned true) ->
    risk_score 30, status FLAGGED (the FLAGGED fork of the screening branch).

    Design: Difficulty/non_linear_state_machine/nlsm_visit_branch_fork_at_screening
    """
    site, floor, host = setup_site_floor_host()
    create_watchlist_entry(site["id"], "COMPANY", "acme corp", severity="REVIEW", active=True)
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Clean Visitor", visitor_company="Acme Corp", id_scanned=True,
    )
    screened = validate_success(api.screen_visit(visit["id"], LA))
    assert screened["status"] == "FLAGGED", f"expected FLAGGED, got {screened['status']}"
    assert screened["risk_score"] == 30, f"expected 30, got {screened['risk_score']}"


def test_delivery_invoice_status_received_on_log(api):
    """PRD 3.8: "A new delivery starts in `RECEIVED` status with `picked_up_at` null.
    At logging time the system computes the `handling_invoice_cents`, the total
    handling invoice including a surcharge."

    The same [107,107,113] batch is logged RECEIVED with the round-per-parcel total of
    351 cents (second observable of the round-order instance).

    Design: Difficulty/dual_variant_calc/dvc_delivery_invoice_round_order_on_deliverylog
    """
    site, host = setup_site_host()
    res = api.create_delivery(
        {"host_id": host["id"], "carrier": "FEDEX", "parcel_fees_cents": [107, 107, 113]},
        LA,
    )
    delivery = validate_success(res, 201)
    assert delivery["status"] == "RECEIVED", f"expected RECEIVED, got {delivery['status']}"
    assert delivery["handling_invoice_cents"] == 351
    assert delivery["picked_up_at"] is None, "picked_up_at must be null on RECEIVED"


def test_delivery_invoice_single_parcel_round_half_up(api):
    """PRD 3.8: "multiply the fee by 1.075 (a 7.5 percent surcharge), round that
    single parcel's surcharged amount half-up to whole cents, and only then add it to
    the running total."
    PRD 2.10: "the one place rounding occurs — the per-parcel delivery handling
    surcharge — uses the round-half-up convention to the nearest whole cent, applied
    per parcel before any summation".

    A single parcel of 107 cents -> 115.025 -> 115 (round-half-up to whole cents),
    isolating the per-parcel rounding step of mode (b).

    Design: Difficulty/combinatorial_formula/cf_delivery_invoice_nested_rounding_order_mode_b
    """
    site, host = setup_site_host()
    res = api.create_delivery(
        {"host_id": host["id"], "carrier": "UPS", "parcel_fees_cents": [107]},
        LA,
    )
    delivery = validate_success(res, 201)
    assert delivery["handling_invoice_cents"] == 115, (
        f"expected 115, got {delivery['handling_invoice_cents']}"
    )


def test_screening_deny_dominance_prints_no_badge_terminal(api):
    """PRD 3.4: "On a DENY decision it auto-advances `SCREENING` to `DENIED`, a
    terminal state in which no badge is ever printed".
    PRD 3.4: "`DENY` strictly dominates `REVIEW`, so a visit that matches both a
    `DENY` entry and a `REVIEW` entry is denied, not flagged".

    The both-match visit lands in DENIED with no badge_number assigned (the terminal
    side of the dominance outcome).

    Design: Difficulty/dual_variant_calc/dvc_screening_decision_dominance_on_visit
    """
    site, floor, host = setup_site_floor_host()
    create_watchlist_entry(site["id"], "NAME", "jordan blake", severity="DENY", active=True)
    create_watchlist_entry(site["id"], "COMPANY", "acme corp", severity="REVIEW", active=True)
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Jordan Blake", visitor_company="Acme Corp", id_scanned=True,
    )
    screened = validate_success(api.screen_visit(visit["id"], LA))
    assert screened["status"] == "DENIED"
    assert screened["badge_number"] is None, "no badge is ever printed for a DENIED visit"


def test_risk_score_clamp_keeps_95_under_ceiling(api):
    """PRD 3.4: "The resulting `risk_score` is the raw total clamped into the inclusive
    range 0 to 100 — values below 0 become 0 and values above 100 become 100, though
    with these weights the natural ceiling is 95."
    PRD 2.10: "The watchlist `risk_score` is an integer clamped to the inclusive range
    from 0 to 100."

    With all three contributions present (50+30+15=95) the clamp leaves the value at
    95 — a value at the natural ceiling, below the 100 cap.

    Design: Difficulty/combinatorial_formula/cf_risk_score_three_input_nonlinear_clamp_mode_a
    """
    site, floor, host = setup_site_floor_host()
    create_watchlist_entry(site["id"], "NAME", "jordan blake", severity="DENY", active=True)
    create_watchlist_entry(site["id"], "COMPANY", "acme corp", severity="REVIEW", active=True)
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Jordan Blake", visitor_company="Acme Corp", id_scanned=False,
    )
    screened = validate_success(api.screen_visit(visit["id"], LA))
    assert screened["risk_score"] == 95
    assert 0 <= screened["risk_score"] <= 100


def test_screening_clear_branch_auto_advances_to_cleared(api):
    """PRD 3.4: "On a CLEAR decision the screening auto-advances the visit from
    `SCREENING` to `CLEARED`."
    PRD 3.4: "otherwise the decision is CLEAR."

    With no matching watchlist entry the visit takes the CLEARED fork (distinct from
    the FLAGGED and DENIED forks of the screening branch), risk_score 0.

    Design: Difficulty/non_linear_state_machine/nlsm_visit_branch_fork_at_screening
    """
    site, floor, host = setup_site_floor_host()
    create_watchlist_entry(site["id"], "COMPANY", "acme corp", severity="REVIEW", active=True)
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Clean Visitor", visitor_company="OtherCo", id_scanned=True,
    )
    screened = validate_success(api.screen_visit(visit["id"], LA))
    assert screened["status"] == "CLEARED", f"expected CLEARED, got {screened['status']}"
    assert screened["risk_score"] == 0, f"expected 0, got {screened['risk_score']}"
