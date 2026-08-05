"""Make-ready fee pricing, estimate issuance, capacity boundary, and OCC.

Queue A — dual_variant_calc (make-ready ESTIMATE vs FINAL),
combinatorial_formula (multi-input non-linear make-ready fee),
boundary_precision_check (pole-capacity exact fit).
Queue B — endpoints (OCC stale-version on estimate issue).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_engineer_headers, make_attacher_headers, make_permit_officer_headers,
    setup_base, create_estimate_issued_application, create_granted_application,
    create_surveyed_application, create_accepted_application,
    get_make_ready_invoice_for_application,
    COMPLEX_SURVEY, api_client,
)

COORD = TEST_USERS["coordinator_headers"]

# ESTIMATE variant survey inputs → make_ready_fee_estimate_cents = 210450.
_SIMPLE_8H = {
    "estimated_labor_hours": 8,
    "make_ready_required": True,
    "existing_attacher_count": 2,
    "complexity_class": "SIMPLE",
}


# ─── Queue A: dual_variant_calc (make-ready ESTIMATE vs FINAL) ──────────────
def test_make_ready_estimate_variant_value(api):
    """PRD §3.3: "otherwise the base labor is the labor hours multiplied by the
    labor rate and then by the complexity multiplier. A transfer cost is added
    for incumbent lines: `existing_attacher_count` multiplied by 7,500 cents
    each."
    PRD §3.3: "The **estimate variant**, computed here at issuance, uses the
    surveyed `estimated_labor_hours` as the labor hours and then inflates the
    subtotal by a fifteen-percent contingency buffer — the subtotal multiplied
    by 1.15 — with the result rounded half-up to whole cents and stored as
    `make_ready_fee_estimate_cents`."

    Design: Difficulty/dual_variant_calc/make_ready_fee_estimate_vs_final_on_application
    """
    ctx = create_granted_application(actual_labor_hours=10, survey_overrides=COMPLEX_SURVEY)
    app = ctx["app"]
    assert app["make_ready_fee_estimate_cents"] == 210450
    assert app["make_ready_fee_final_cents"] != app["make_ready_fee_estimate_cents"]


def test_make_ready_final_variant_value_and_invoice_trueup(api):
    """PRD §3.4: "The **final variant** of the make-ready fee is computed exactly
    as the estimate variant but using the reported `actual_labor_hours` in place
    of the estimated hours and applying no contingency buffer — the subtotal is
    rounded half-up directly and stored as `make_ready_fee_final_cents`. The
    `MAKE_READY` invoice's `amount_cents` is trued up to this final fee".

    Design: Difficulty/dual_variant_calc/make_ready_fee_estimate_vs_final_on_application
    """
    ctx = create_granted_application(actual_labor_hours=10, survey_overrides=COMPLEX_SURVEY)
    assert ctx["app"]["make_ready_fee_final_cents"] == 225000
    invoice = get_make_ready_invoice_for_application(ctx["app"]["id"])
    assert invoice["amount_cents"] == 225000


# ─── Queue A: combinatorial_formula (multi-input non-linear make-ready) ─────
def test_make_ready_fee_multi_input_nonlinear_estimate(api):
    """PRD §3.3: "Begin with the owner's `make_ready_labor_rate_cents_per_hour`
    as the labor rate and a complexity multiplier of 1.75 when `complexity_class`
    is `COMPLEX` and 1.0 when it is `SIMPLE`. If `make_ready_required` is false,
    the base labor component is zero; otherwise the base labor is the labor
    hours multiplied by the labor rate and then by the complexity multiplier."
    PRD §3.3: "The **estimate variant**, computed here at issuance, uses the
    surveyed `estimated_labor_hours` as the labor hours and then inflates the
    subtotal by a fifteen-percent contingency buffer — the subtotal multiplied
    by 1.15 — with the result rounded half-up to whole cents and stored as
    `make_ready_fee_estimate_cents`."

    Design: Difficulty/combinatorial_formula/make_ready_fee_multi_input_nonlinear
    """
    ctx = create_estimate_issued_application(
        app_overrides={"purpose": "COAX"}, survey_overrides=COMPLEX_SURVEY
    )
    assert ctx["app"]["make_ready_fee_estimate_cents"] == 210450


def test_make_ready_fee_complexity_multiplier_selects_nonlinearly(api):
    """PRD §3.3: "Begin with the owner's `make_ready_labor_rate_cents_per_hour`
    as the labor rate and a complexity multiplier of 1.75 when `complexity_class`
    is `COMPLEX` and 1.0 when it is `SIMPLE`. If `make_ready_required` is false,
    the base labor component is zero; otherwise the base labor is the labor
    hours multiplied by the labor rate and then by the complexity multiplier."

    Design: Difficulty/combinatorial_formula/make_ready_fee_multi_input_nonlinear
    """
    complex_ctx = create_estimate_issued_application(survey_overrides=COMPLEX_SURVEY)
    simple_ctx = create_estimate_issued_application(survey_overrides=_SIMPLE_8H)
    # COMPLEX: round((8*12000*1.75 + 2*7500) * 1.15) = 210450
    # SIMPLE:  round((8*12000*1.00 + 2*7500) * 1.15) = 127650
    assert complex_ctx["app"]["make_ready_fee_estimate_cents"] == 210450
    assert simple_ctx["app"]["make_ready_fee_estimate_cents"] == 127650
    assert (complex_ctx["app"]["make_ready_fee_estimate_cents"]
            != simple_ctx["app"]["make_ready_fee_estimate_cents"])


# ─── Queue A: boundary_precision_check (pole capacity exact fit) ────────────
def test_pole_capacity_exact_fit_accept_succeeds(api):
    """PRD §3.3: "the `requested_space_inches` must be no greater than the pole's
    `usable_communication_space_inches` less its `occupied_space_inches` and less
    its `reserved_space_inches`, or `ERR_INSUFFICIENT_POLE_SPACE`".
    PRD §3.3: "On acceptance the application's `reserved_space_inches` is set
    equal to `requested_space_inches`, raising the pole's `reserved_space_inches`".

    Design: Difficulty/boundary_precision_check/pole_capacity_exact_fit_inclusive
    """
    ctx = create_estimate_issued_application(
        pole_overrides={"usable_communication_space_inches": 6},
        app_overrides={"requested_space_inches": 6, "requested_position_inches": 240},
        survey_overrides={"estimated_labor_hours": 4, "make_ready_required": True,
                          "existing_attacher_count": 0, "complexity_class": "SIMPLE"},
    )
    res = api.estimate_decision_application(
        ctx["app"]["id"], {"decision": "ACCEPT"}, make_attacher_headers(ctx["attacher"]["id"])
    )
    app = validate_success(res, 200)
    assert app["status"] == "ESTIMATE_ACCEPTED"
    assert app["reserved_space_inches"] == 6


def test_pole_capacity_exact_fit_reserves_on_pole(api):
    """PRD §3.3: "the `requested_space_inches` must be no greater than the pole's
    `usable_communication_space_inches` less its `occupied_space_inches` and less
    its `reserved_space_inches`, or `ERR_INSUFFICIENT_POLE_SPACE`".
    PRD §3.3: "On acceptance the application's `reserved_space_inches` is set
    equal to `requested_space_inches`, raising the pole's `reserved_space_inches`".

    Design: Difficulty/boundary_precision_check/pole_capacity_exact_fit_inclusive
    """
    ctx = create_accepted_application(
        pole_overrides={"usable_communication_space_inches": 6},
        app_overrides={"requested_space_inches": 6, "requested_position_inches": 240},
        survey_overrides={"estimated_labor_hours": 4, "make_ready_required": True,
                          "existing_attacher_count": 0, "complexity_class": "SIMPLE"},
    )
    pole = get_success_data(api_client.get_pole(ctx["pole"]["id"], COORD))
    assert pole["reserved_space_inches"] == 6


# ─── Queue B: endpoints (OCC stale-version on estimate) ────────────────────
def test_occ_estimate_stale_version_returns_412(api):
    """PRD §2.6: "Because a prior estimate issuance legitimately supersedes the
    fee preview and increments the application's `version` by one, a subsequent
    issuance that still carries the older `expected_application_version` will
    fail the stale-version check".

    Design: Corner/endpoints/occ_estimate_stale_version_returns_412
    """
    ctx = create_surveyed_application()
    app_id = ctx["app"]["id"]
    stale_version = ctx["app"]["version"]
    eng = make_engineer_headers("eng-1")
    # First issuance supersedes and bumps the version.
    get_success_data(api.estimate_application(
        app_id, {"expected_application_version": stale_version}, eng))
    # Second issuance still carrying the pre-supersede version is rejected.
    res = api.estimate_application(
        app_id, {"expected_application_version": stale_version}, eng)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
