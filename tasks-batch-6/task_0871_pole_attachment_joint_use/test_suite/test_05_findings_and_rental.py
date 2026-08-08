"""Unauthorized-attachment findings, penalty tiers, dual-variant back rental,
round-per-line annual rental, survey input errors, and overdue sweep.

Queue A — dual_variant_calc (GOOD_FAITH vs BAD_FAITH back rental),
combinatorial_formula (round-per-line-then-sum annual rental).
Queue B — calculations (penalty tier 2), errors (unknown crew, invalid window),
endpoints (clock advance marks invoice OVERDUE).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_engineer_headers, make_attacher_headers,
    create_annual_rental_invoice_payload,
    setup_owner, setup_pole, setup_attacher, setup_base,
    create_finding, create_legalized_attachment, submit_application, submit_survey,
    set_clock, api_client, NON_EXISTENT_UUID,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["field_auditor_headers"]


# ─── Queue A: dual_variant_calc (back rental GOOD_FAITH vs BAD_FAITH) ───────
def test_back_rental_good_faith_single_year_and_penalty(api):
    """PRD §3.6: "The annual line is the owner's `annual_rental_rate_cents`
    multiplied by `discovered_space_inches`, divided by twelve, and rounded
    half-up."
    PRD §3.6: "a good-faith finding (`good_faith` true) is charged exactly one
    year of the annual line".
    PRD §3.6: "it is 25,000 cents when `discovered_space_inches` is twelve
    inches or fewer, and 50,000 cents when it exceeds twelve inches."

    Design: Difficulty/dual_variant_calc/back_rental_good_faith_vs_bad_faith_on_finding
    """
    owner = setup_owner(owner_category="ILEC")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher(company_name="GF", cin="CINGF", contact_email="gf@x.com")
    res = api.create_finding(
        {"pole_id": pole["id"], "attacher_id": attacher["id"], "discovered_space_inches": 12,
         "discovered_position_inches": 200, "good_faith": True, "estimated_install_years_ago": 7},
        AUDITOR,
    )
    finding = validate_success(res, 201)
    assert finding["back_rental_cents"] == 1000
    assert finding["penalty_cents"] == 25000


def test_back_rental_bad_faith_capped_five_years(api):
    """PRD §3.6: "a bad-faith finding (`good_faith` false) is charged the annual
    line multiplied by the smaller of `estimated_install_years_ago` and five
    years, capping multi-year exposure at five years."
    PRD §3.6: "An `UNAUTHORIZED` invoice is then issued for the sum of
    `penalty_cents` and `back_rental_cents`".

    Design: Difficulty/dual_variant_calc/back_rental_good_faith_vs_bad_faith_on_finding
    """
    owner = setup_owner(owner_category="ILEC")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher(company_name="BF", cin="CINBF", contact_email="bf@x.com")
    res = api.create_finding(
        {"pole_id": pole["id"], "attacher_id": attacher["id"], "discovered_space_inches": 12,
         "discovered_position_inches": 260, "good_faith": False, "estimated_install_years_ago": 7},
        AUDITOR,
    )
    finding = validate_success(res, 201)
    # annual_line = round(1000*12/12) = 1000; back = 1000 * min(7,5) = 5000
    assert finding["back_rental_cents"] == 5000
    invoice = get_success_data(api_client.get_invoice(finding["penalty_invoice_id"], COORD))
    assert invoice["amount_cents"] == 25000 + 5000


# ─── Queue A: combinatorial_formula (round-per-line-then-sum) ───────────────
def _three_active_one_inch_attachments():
    owner = setup_owner(owner_category="MUNICIPAL")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    for pos in (100, 130, 160):
        create_legalized_attachment(pole["id"], attacher["id"], space_inches=1, position_inches=pos)
    return owner, pole, attacher


def test_annual_rental_round_per_line_then_sum_amount(api):
    """PRD §3.7: "For each candidate, a per-line amount is computed as the
    owner's `annual_rental_rate_cents` multiplied by that attachment's
    `allotted_space_inches`, divided by twelve, and rounded half-up to whole
    cents. The invoice's `amount_cents` is the sum of those already-rounded
    per-line amounts — rounding is applied to each line before summation, which
    can differ from rounding a single grand total."

    Design: Difficulty/combinatorial_formula/annual_rental_round_per_line_then_sum
    """
    owner, pole, attacher = _three_active_one_inch_attachments()
    res = api.create_invoice(
        create_annual_rental_invoice_payload(attacher["id"], owner["id"]), COORD
    )
    invoice = validate_success(res, 201)
    # per_line = round(1000*1/12) = 83; 83*3 = 249 (NOT round(1000*3/12) = 250)
    assert invoice["amount_cents"] == 249
    assert invoice["invoice_type"] == "ANNUAL_RENTAL"


def test_annual_rental_line_items_rounded_individually(api):
    """PRD §3.7: "The invoice's `amount_cents` is the sum of those
    already-rounded per-line amounts — rounding is applied to each line before
    summation, which can differ from rounding a single grand total."

    Design: Difficulty/combinatorial_formula/annual_rental_round_per_line_then_sum
    """
    owner, pole, attacher = _three_active_one_inch_attachments()
    res = api.create_invoice(
        create_annual_rental_invoice_payload(attacher["id"], owner["id"]), COORD
    )
    invoice = validate_success(res, 201)
    lines = invoice["line_items"]
    assert len(lines) == 3
    assert all(line["amount_cents"] == 83 for line in lines)
    assert sum(line["amount_cents"] for line in lines) == invoice["amount_cents"] == 249


# ─── Queue B: calculations (penalty tier 2) ────────────────────────────────
def test_penalty_tier2_above_boundary(api):
    """PRD §3.6: "The `penalty_cents` follows a size tier: it is 25,000 cents
    when `discovered_space_inches` is twelve inches or fewer, and 50,000 cents
    when it exceeds twelve inches."

    Design: Corner/calculations/penalty_tier2_above_boundary
    """
    owner = setup_owner(owner_category="ILEC")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    res = api.create_finding(
        {"pole_id": pole["id"], "attacher_id": attacher["id"], "discovered_space_inches": 13,
         "discovered_position_inches": 150, "good_faith": True, "estimated_install_years_ago": 1},
        AUDITOR,
    )
    finding = validate_success(res, 201)
    assert finding["penalty_cents"] == 50000


# ─── Queue B: errors (unknown crew, invalid window) ────────────────────────
def test_survey_with_unknown_crew_not_found(api):
    """PRD §3.2: "the crew must exist and belong to the same owner as the pole,
    failing which the response is `ERR_CREW_NOT_FOUND`".

    Design: Corner/errors/survey_with_unknown_crew_not_found
    """
    owner = setup_owner()
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    app = submit_application(pole["id"], attacher["id"])
    res = api.survey_application(
        app["id"],
        {"crew_id": NON_EXISTENT_UUID, "window_start": "2026-05-10T08:00:00Z",
         "window_end": "2026-05-10T12:00:00Z", "estimated_labor_hours": 4,
         "make_ready_required": True, "existing_attacher_count": 0,
         "complexity_class": "SIMPLE", "findings": "ok"},
        make_engineer_headers("eng-1"),
    )
    validate_error(res, "ERR_CREW_NOT_FOUND", expected_status=404)


def test_survey_invalid_window_rejected(api):
    """PRD §3.2: "the window's `window_end` must be strictly later than its
    `window_start`, else `ERR_INVALID_WINDOW`".

    Design: Corner/errors/survey_invalid_window_rejected
    """
    ctx = setup_base()
    app = submit_application(ctx["pole"]["id"], ctx["attacher"]["id"])
    res = api.survey_application(
        app["id"],
        {"crew_id": ctx["crew"]["id"], "window_start": "2026-05-10T12:00:00Z",
         "window_end": "2026-05-10T08:00:00Z", "estimated_labor_hours": 4,
         "make_ready_required": True, "existing_attacher_count": 0,
         "complexity_class": "SIMPLE", "findings": "ok"},
        make_engineer_headers("eng-1"),
    )
    validate_error(res, "ERR_INVALID_WINDOW", expected_status=422)


# ─── Queue B: endpoints (clock advance marks invoice OVERDUE) ──────────────
def test_clock_advance_marks_invoice_overdue(api):
    """PRD §2.9: "Advancing the clock triggers two scheduled sweeps: every
    `Invoice` still `ISSUED` whose `due_at` is now in the past transitions to
    `OVERDUE`".

    Design: Corner/endpoints/clock_advance_marks_invoice_overdue
    """
    owner = setup_owner(owner_category="ILEC")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    finding = create_finding(pole["id"], attacher["id"], discovered_space_inches=8,
                             discovered_position_inches=150)
    inv_id = finding["penalty_invoice_id"]
    set_clock("2026-06-01T00:00:00Z")
    invoice = get_success_data(api_client.get_invoice(inv_id, COORD))
    assert invoice["status"] == "OVERDUE"
