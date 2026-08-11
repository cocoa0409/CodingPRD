"""Quoting: provisional vs issued pricing, revision cycle, issue gates,
acceptance contract, expiry, and RBAC-relevant state transitions."""
import pytest

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, MODEL_STRAIGHT, MODEL_CURVED, MEASURE_STRAIGHT, MEASURE_CURVED,
    assert_quote, assert_agreement,
    set_clock, create_catalog_model, create_customer, schedule_assessment,
    measure_assessment, approve_assessment, setup_approved_assessment,
    setup_measured_assessment, create_draft_quote, create_issued_quote,
    issue_quote, create_unit, create_agreement, get_quote, get_customer,
    make_customer_headers, create_accept_payload,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
ASSESSOR = TEST_USERS["assessor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]


def _setup_curved_quote_scenario():
    """CURVED assessment (rise 2000 / run 4100 -> rail 4.56m) approved against
    the curved-capable catalog model; returns (customer, assessment)."""
    set_clock()
    create_catalog_model(MODEL_CURVED)
    base = setup_approved_assessment(MODEL_CURVED["model_code"], MEASURE_CURVED)
    return base["customer"], base["assessment"]


# ---------------------------------------------------------------------------
# Provisional vs issued totals (dual-variant quote pricing)
# ---------------------------------------------------------------------------

def test_provisional_total_uses_catalog_forward_estimate(api):
    """PRD §3.3: "For `PURCHASE`, the provisional total is the model's
    `base_purchase_price_cents` plus its `install_labor_hours` at the standard
    labor rate of 8,500 cents per hour."
    PRD §3.3: "The quote is born `DRAFT` with `revision_number` at 1, and the
    platform immediately computes a forward-looking `provisional_total_cents`
    from catalog data."

    Design: Difficulty/dual_variant_calc/quote_total_provisional_vs_issued_divergence
    """
    customer, assessment = _setup_curved_quote_scenario()
    quote = create_draft_quote(customer["id"], assessment["id"],
                               MODEL_CURVED["model_code"], "PURCHASE")
    assert_quote(quote)
    # 450000 + 6 * 8500
    assert quote["provisional_total_cents"] == 501000
    assert quote["status"] == "DRAFT"
    assert quote["revision_number"] == 1


def test_issued_total_swaps_to_actuals_with_rail_geometry(api):
    """PRD §3.3: "The rail materials cost comes first: the pinned
    `valid_rail_length_m` multiplied by 22,000 cents per metre, rounded half-up
    to a whole cent. If the staircase is `CURVED`, that rail cost is then
    multiplied by 1.35 and again rounded half-up to a whole cent."
    PRD §3.3: "The issued total is then the base plus the rail cost plus the
    model's `install_labor_hours` at the 8,500-cent hourly labor rate."
    PRD §3.1: "the square root of the sum of the squares of the rise and the
    run, each converted from millimetres to metres at 1,000 millimetres per
    metre, rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/quote_total_provisional_vs_issued_divergence
    """
    customer, assessment = _setup_curved_quote_scenario()
    quote = create_draft_quote(customer["id"], assessment["id"],
                               MODEL_CURVED["model_code"], "PURCHASE")
    issued = issue_quote(quote["id"])
    assert issued["status"] == "ISSUED"
    # rail = sqrt(2.0^2 + 4.1^2) = 4.56 m; rail cost = round(4.56*22000)=100320,
    # curved -> round(100320*1.35)=135432; total = 450000 + 135432 + 6*8500
    assert issued["valid_rail_length_m"] == pytest.approx(4.56, abs=0.001)
    assert issued["issued_total_cents"] == 636432


# ---------------------------------------------------------------------------
# Cyclic revision loop
# ---------------------------------------------------------------------------

def test_revise_returns_issued_quote_to_draft_and_clears_total(api):
    """PRD §3.3: "Before that happens, a `SalesRep` may pull an `ISSUED` quote
    back to `DRAFT` for revision — a cyclic loop in which `revision_number`
    increments by one and `issued_total_cents` is cleared back to 0 until the
    quote is re-issued."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle
    """
    set_clock()
    create_catalog_model()
    base = setup_approved_assessment()
    quote = create_issued_quote(base["customer"]["id"], base["assessment"]["id"])
    assert quote["revision_number"] == 1

    revised = validate_success(api.revise_quote(quote["id"], SALES), 200)
    assert revised["status"] == "DRAFT"
    assert revised["revision_number"] == 2
    assert revised["issued_total_cents"] == 0


def test_reissue_after_revise_recomputes_identical_total(api):
    """PRD §3.3: "Before that happens, a `SalesRep` may pull an `ISSUED` quote
    back to `DRAFT` for revision — a cyclic loop in which `revision_number`
    increments by one and `issued_total_cents` is cleared back to 0 until the
    quote is re-issued."
    PRD §3.3: "The issued total is then the base plus the rail cost plus the
    model's `install_labor_hours` at the 8,500-cent hourly labor rate."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle
    """
    set_clock()
    create_catalog_model()
    base = setup_approved_assessment()
    quote = create_issued_quote(base["customer"]["id"], base["assessment"]["id"])
    first_total = quote["issued_total_cents"]
    # straight model on straight assessment: 380000 + round(4.00*22000) + 4*8500
    assert first_total == 502000

    validate_success(api.revise_quote(quote["id"], SALES), 200)
    reissued = validate_success(api.issue_quote(quote["id"], SALES), 200)
    assert reissued["status"] == "ISSUED"
    assert reissued["revision_number"] == 2
    assert reissued["issued_total_cents"] == 502000


# ---------------------------------------------------------------------------
# Issue gate: cross-entity dependency on assessment state
# ---------------------------------------------------------------------------

def test_issue_quote_on_unapproved_assessment_rejected(api):
    """PRD §3.3: "The referenced assessment must be `APPROVED`, otherwise
    `ERR_ASSESSMENT_NOT_APPROVED` (409)."
    PRD §4: POST /stairlift-ops/customers/{id}/quotes — "Create a DRAFT Quote
    against a measured/approved assessment".

    Design: Difficulty/cross_entity_state_dependency/quote_issue_requires_assessment_approved
    """
    set_clock()
    create_catalog_model()
    base = setup_measured_assessment()  # MEASURED, never approved
    quote = create_draft_quote(base["customer"]["id"], base["assessment"]["id"])
    res = api.issue_quote(quote["id"], SALES)
    validate_error(res, ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED)
    after = get_quote(quote["id"])
    assert after["status"] == "DRAFT"


def test_issue_quote_on_approved_assessment_succeeds(api):
    """PRD §3.3: "The referenced assessment must be `APPROVED`, otherwise
    `ERR_ASSESSMENT_NOT_APPROVED` (409)."
    PRD §3.3: "Issuing stamps `issued_at` from the logical clock and sets
    `expires_at` to `issued_at` plus the platform-configured quote time-to-live
    `QUOTE_TTL_DAYS`; an audit event is appended."

    Design: Difficulty/cross_entity_state_dependency/quote_issue_requires_assessment_approved
    """
    set_clock()
    create_catalog_model()
    base = setup_approved_assessment()
    quote = create_draft_quote(base["customer"]["id"], base["assessment"]["id"])
    issued = validate_success(api.issue_quote(quote["id"], SALES), 200)
    assert issued["status"] == "ISSUED"
    assert issued["issued_at"] is not None
    assert issued["expires_at"] is not None


# ---------------------------------------------------------------------------
# Acceptance state gates and terminal lockdown
# ---------------------------------------------------------------------------

def test_quote_accept_from_draft_returns_invalid_state(api):
    """PRD §3.4: "The customer (or a `PlatformAdmin` acting on their behalf)
    accepts an `ISSUED` quote by naming the `equipment_unit_id` to reserve, the
    `expected_customer_version` concurrency token described in §2.6, and — for
    rentals — a `committed_rental_months` commitment of at least 3 months"
    PRD §2.8: "4. State permission — the target resource is in a state that
    permits the requested transition — failure yields `ERR_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/quote_accept_from_draft_returns_invalid_state
    """
    set_clock()
    create_catalog_model(model_code="SL-S")
    base = setup_approved_assessment("SL-S")
    quote = create_draft_quote(base["customer"]["id"], base["assessment"]["id"],
                               "SL-S")
    unit = create_unit("SL-S", serial="SN-DD-001")
    customer = get_customer(base["customer"]["id"])
    res = api.accept_quote(
        quote["id"], create_accept_payload(unit["id"], customer["version"]),
        make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_terminal_state_quote_accepted_locked(api):
    """PRD §3.3: "Before that happens, a `SalesRep` may pull an `ISSUED` quote
    back to `DRAFT` for revision" — only an ISSUED quote can be revised.
    PRD §2.8: "4. State permission — the target resource is in a state that
    permits the requested transition — failure yields `ERR_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/terminal_state_quote_accepted_locked
    """
    set_clock()
    create_catalog_model(model_code="SL-T")
    base = setup_approved_assessment("SL-T")
    bag = create_agreement(base["customer"]["id"], base["assessment"]["id"], "SL-T")
    quote_after = get_quote(bag["quote"]["id"])
    assert quote_after["status"] == "ACCEPTED"

    res = api.revise_quote(bag["quote"]["id"], SALES)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    res = api.issue_quote(bag["quote"]["id"], SALES)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

def test_expired_quote_accept_returns_quote_expired(api):
    """PRD §3.3: "Both revision and acceptance check freshness against the
    logical clock: an attempt on a quote whose `expires_at` has already passed
    is rejected with `ERR_QUOTE_EXPIRED` (409)."
    PRD §3.3: "When the logical clock passes a quote's `expires_at` while it is
    still `ISSUED`, the expiry sweep moves it to `EXPIRED` with a
    `QUOTE_EXPIRED` audit event."

    Note: once the sweep has run, the quote sits in EXPIRED, so a PRD-faithful
    implementation may surface either the freshness gate (ERR_QUOTE_EXPIRED) or
    the earlier state-permission gate (ERR_INVALID_STATE); both reject the
    accept with 409.

    Design: Corner/validations/expired_quote_accept_returns_quote_expired
    """
    set_clock()
    create_catalog_model(model_code="SL-EXP")
    base = setup_approved_assessment("SL-EXP")
    quote = create_issued_quote(base["customer"]["id"], base["assessment"]["id"],
                                "SL-EXP")
    unit = create_unit("SL-EXP", serial="SN-EXP-001")
    # TTL is 30 days; 2026-08-15 is well past expiry of a 2026-06-01 issue.
    set_clock("2026-08-15T00:00:00Z")
    customer = get_customer(base["customer"]["id"])
    res = api.accept_quote(
        quote["id"], create_accept_payload(unit["id"], customer["version"]),
        make_customer_headers(customer["id"]))
    validate_error_is_one_of(
        res, [ApiErrorId.ERR_QUOTE_EXPIRED, ApiErrorId.ERR_INVALID_STATE])


# ---------------------------------------------------------------------------
# Model compatibility and uniqueness gates
# ---------------------------------------------------------------------------

def test_model_incompatible_curved_on_straight_only_model(api):
    """PRD §3.3: "The catalog model must be compatible with the measured site:
    if the assessment's `staircase_kind` is `CURVED` the model must have
    `supports_curved`, and if the assessment recorded `has_outdoor_exposure`
    the model must have `supports_outdoor`; a mismatch is
    `ERR_MODEL_INCOMPATIBLE` (422)."

    Design: Corner/validations/model_incompatible_curved_on_straight_only_model
    """
    set_clock()
    create_catalog_model(model_code="SL-STR")  # supports_curved=False
    customer = create_customer(full_name="Incomp Irene")
    assessment = schedule_assessment(customer["id"])
    measure_assessment(assessment["id"], dict(MEASURE_STRAIGHT,
                                              staircase_kind="CURVED",
                                              stair_rise_mm=2400,
                                              stair_run_mm=4800))
    approve_assessment(assessment["id"], "SL-STR")
    quote = create_draft_quote(customer["id"], assessment["id"], "SL-STR")
    res = api.issue_quote(quote["id"], SALES)
    validate_error(res, ApiErrorId.ERR_MODEL_INCOMPATIBLE)


def test_error_active_quote_exists_triggerable(api):
    """PRD §3.3: "Finally, no other quote on the same customer may currently be
    `ISSUED`; a second live offer is `ERR_ACTIVE_QUOTE_EXISTS` (409)."

    Design: Corner/errors/error_active_quote_exists_triggerable
    """
    set_clock()
    create_catalog_model(model_code="SL-AQ")
    base = setup_approved_assessment("SL-AQ")
    first = create_issued_quote(base["customer"]["id"], base["assessment"]["id"],
                                "SL-AQ", "PURCHASE")
    assert first["status"] == "ISSUED"
    second = create_draft_quote(base["customer"]["id"], base["assessment"]["id"],
                                "SL-AQ", "RENTAL")
    res = api.issue_quote(second["id"], SALES)
    validate_error(res, ApiErrorId.ERR_ACTIVE_QUOTE_EXISTS)


# ---------------------------------------------------------------------------
# Immediate consistency of acceptance
# ---------------------------------------------------------------------------

def test_quote_accept_response_immediately_reflects_agreement(api):
    """PRD §3.4: "A new agreement is created in `PENDING_FUNDING`, carrying the
    `quote_id` of the accepted quote it consummates and the `customer_id`
    denormalized from that quote for reverse lookup, with its `mode` copied
    from the quote's `acquisition_mode`"
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/quote_accept_response_immediately_reflects_agreement
    """
    set_clock()
    create_catalog_model(model_code="SL-IC")
    base = setup_approved_assessment("SL-IC")
    quote = create_issued_quote(base["customer"]["id"], base["assessment"]["id"],
                                "SL-IC")
    unit = create_unit("SL-IC", serial="SN-IC-001")
    customer = get_customer(base["customer"]["id"])
    res = api.accept_quote(
        quote["id"], create_accept_payload(unit["id"], customer["version"]),
        make_customer_headers(customer["id"]))
    agreement = validate_success(res, 201)
    assert_agreement(agreement)
    assert agreement["status"] == "PENDING_FUNDING"
    assert agreement["quote_id"] == quote["id"]
    assert agreement["customer_id"] == customer["id"]
