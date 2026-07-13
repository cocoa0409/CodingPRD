"""Demolition eligibility, priority scoring, and the demolition cascade.

Covers difficulty instances 2a (weighted priority score), 6b (min-violations
boundary), 4b (demolish voids violation and waives fine) plus corner
balance-below-threshold.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_property_with_n_open_violations, setup_assessed_fine,
    transition_violation, assess_fine, advance_foreclosure, set_clock,
    get_property,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["code_officer_headers"]


# --- Difficulty 2a: weighted non-linear priority score ---------------------
def _demolition_scenario(api):
    """Five OPEN violations (severity 8), two escalated + fined (balance 70000,
    three remain OPEN), foreclosure at LIS_PENDENS, clock 100 days after
    registration. Returns (property_id, listing)."""
    ctx = setup_property_with_n_open_violations(
        api, n=5, base_fine_cents=30000, severity_weight=8, cure_period_days=5,
        category="SANITATION",
    )
    reg_id = ctx["registrant"]["id"]
    prop_id = ctx["property"]["id"]
    viols = ctx["violations"]
    set_clock(api, "2026-03-06T00:00:00Z")
    transition_violation(api, viols[0]["id"], "ESCALATE")
    transition_violation(api, viols[1]["id"], "ESCALATE")
    assess_fine(api, viols[0]["id"])
    assess_fine(api, viols[1]["id"])
    advance_foreclosure(api, prop_id, reg_id)   # NONE -> NOTICE_OF_DEFAULT
    advance_foreclosure(api, prop_id, reg_id)   # NOTICE_OF_DEFAULT -> LIS_PENDENS
    set_clock(api, "2026-06-09T00:00:00Z")      # 100 days vacant -> 3 whole months
    listing = validate_success(
        api.create_demolition_listing({"property_id": prop_id}, ADMIN),
        expected_status=201,
    )
    return prop_id, listing


def test_demolition_priority_score_weighted_components(api):
    """PRD §3.9: "The `priority_score` is the sum of four capped components,
    rounded half up to two decimal places. The severity component is the sum of the
    `severity_weight` of every violation on the property whose status is `OPEN` or
    `ESCALATED`, capped at 40. The vacancy component first counts the whole months
    the property has been vacant ... then awards 2 points per such month, capped at
    20. The balance component awards 1 point for every whole 10000 cents of
    `outstanding_balance_cents` ... capped at 25. The foreclosure component is fixed
    by the property's `foreclosure_status`: 15 for `REO`, 10 for
    `AUCTION_SCHEDULED`, 7 for `LIS_PENDENS`, 4 for `NOTICE_OF_DEFAULT`, and 0 for
    `NONE`."

    Design: Difficulty/combinatorial_formula/demolition_priority_weighted_nonlinear
    """
    _, listing = _demolition_scenario(api)
    assert listing["priority_score"] == 44


def test_demolition_priority_component_inputs(api):
    """PRD §2.6: "The `open_violation_count` is the number of the property's
    violations whose status is `OPEN` or `ESCALATED`." The severity, balance, and
    foreclosure inputs to the score are the property's OPEN/ESCALATED violation
    count (3), its outstanding balance (70000), and its LIS_PENDENS foreclosure
    stage.

    Design: Difficulty/combinatorial_formula/demolition_priority_weighted_nonlinear
    """
    prop_id, _ = _demolition_scenario(api)
    prop = get_property(api, prop_id)
    assert prop["open_violation_count"] == 3
    assert prop["outstanding_balance_cents"] == 70000
    assert prop["foreclosure_status"] == "LIS_PENDENS"


# --- Difficulty 6b: minimum-violations count boundary ----------------------
def _two_open_two_fined(api):
    """Four violations; two escalated+fined (balance 70000), two remain OPEN so
    open_violation_count is 2. Returns property_id."""
    ctx = setup_property_with_n_open_violations(
        api, n=4, base_fine_cents=30000, severity_weight=8, cure_period_days=5,
        category="SANITATION",
    )
    viols = ctx["violations"]
    set_clock(api, "2026-03-06T00:00:00Z")
    transition_violation(api, viols[0]["id"], "ESCALATE")
    transition_violation(api, viols[1]["id"], "ESCALATE")
    assess_fine(api, viols[0]["id"])
    assess_fine(api, viols[1]["id"])
    return ctx["property"]["id"]


def test_open_violation_count_excludes_fined(api):
    """PRD §2.6: "The `open_violation_count` is the number of the property's
    violations whose status is `OPEN` or `ESCALATED`." Two FINED violations do not
    count.

    Design: Difficulty/boundary_precision_check/demolition_min_violations_count_boundary
    """
    prop = get_property(api, _two_open_two_fined(api))
    assert prop["open_violation_count"] == 2


def test_demolition_listing_rejected_with_two_open_violations(api):
    """PRD §3.9: "the property must have accumulated at least 3 open violations —
    that is, its `open_violation_count` must be at least 3 — or the listing is
    rejected with `ERR_INSUFFICIENT_VIOLATIONS`."

    Design: Difficulty/boundary_precision_check/demolition_min_violations_count_boundary
    """
    prop_id = _two_open_two_fined(api)
    resp = api.create_demolition_listing({"property_id": prop_id}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VIOLATIONS.value)


# --- Difficulty 4b: demolish -> void violation -> waive fine ---------------
def _demolished_context(api):
    ctx = setup_assessed_fine(api, escalate_clock="2026-03-06T00:00:00Z",
                              base_fine_cents=40000, cure_period_days=5,
                              category="SANITATION", severity_weight=6)
    validate_success(api.demolish_property(ctx["property"]["id"], ADMIN))
    return ctx


def test_demolish_voids_fined_violation(api):
    """PRD §3.9: "Demolition drives `registration_status` to the terminal
    `DEMOLISHED` and then runs a cascade over the property's dependents ... In the
    first hop, every `Violation` of the property whose status is `OPEN`,
    `ESCALATED`, or `FINED` is transitioned to `VOIDED`."

    Design: Difficulty/transitive_cascade/demolish_voids_violation_waives_fine
    """
    ctx = _demolished_context(api)
    prop = get_property(api, ctx["property"]["id"])
    assert prop["registration_status"] == "DEMOLISHED"
    violation = validate_success(api.get_violation(ctx["violation"]["id"], OFFICER))
    assert violation["status"] == "VOIDED"


def test_demolish_waives_fine_and_restores_balance(api):
    """PRD §3.9: "In the second hop, caused by those violations being voided, every
    `Fine` belonging to a just-voided violation whose status is `ASSESSED` or
    `DISPUTED` is transitioned to `WAIVED`, and for each such waiver the system
    posts a `FINE_WAIVED` `LedgerEntry` of the negative `base_amount_cents` and
    recomputes the property's `outstanding_balance_cents`."

    Design: Difficulty/transitive_cascade/demolish_voids_violation_waives_fine
    """
    ctx = _demolished_context(api)
    fine = validate_success(api.get_fine(ctx["fine"]["id"], ADMIN))
    assert fine["status"] == "WAIVED"
    prop = get_property(api, ctx["property"]["id"])
    assert prop["outstanding_balance_cents"] == 10000


# --- Corner: demolition balance below threshold ----------------------------
def test_demolition_balance_below_threshold_returns_error(api):
    """PRD §3.9: "Then the property must carry a material balance: its
    `outstanding_balance_cents` must be at least 50000 cents, or the listing is
    rejected with `ERR_BALANCE_BELOW_DEMOLITION_THRESHOLD`."

    Design: Corner/validations/demolition_balance_below_threshold_returns_error
    """
    ctx = setup_property_with_n_open_violations(
        api, n=3, base_fine_cents=10000, severity_weight=6, cure_period_days=5,
        category="SANITATION",
    )
    prop = get_property(api, ctx["property"]["id"])
    assert prop["open_violation_count"] == 3
    assert prop["outstanding_balance_cents"] == 10000
    resp = api.create_demolition_listing({"property_id": ctx["property"]["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_BALANCE_BELOW_DEMOLITION_THRESHOLD.value)
