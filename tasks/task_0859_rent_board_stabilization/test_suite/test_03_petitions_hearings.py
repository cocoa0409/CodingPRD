"""Petitions, hearings, passthrough calculations, revision cycle, officer overlap.

Sources: Difficulty/combinatorial_formula, Difficulty/transitive_cascade,
Difficulty/non_linear_state_machine, Difficulty/cross_entity_state_dependency,
Difficulty/resource_temporal_overlap, Corner/calculations, Corner/state_machines.
"""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, get_success_data,
    make_landlord_headers, make_hearing_officer_headers,
    create_petition_payload, create_hearing_payload,
    create_landlord, create_officer, create_unit, create_tenant, create_active_tenancy,
    setup_capital_petition_hearing, setup_hardship_petition_hearing,
    setup_petition_under_review,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/capital_passthrough_tiered_cap_mode_a
# ---------------------------------------------------------------------------
def test_capital_passthrough_capped_grant_amount(api):
    """PRD §3.5: "The full passthrough is the smaller of the monthly amortized cost and
    this monthly cap." (cost 4,800,000/120 = 40000; cap = round(300000 * 0.06) = 18000 for
    a two-bedroom unit; min = 18000.)
    PRD §3.5: "On a GRANT, petition.granted_amount_cents is set to the full passthrough."

    Design: Difficulty/combinatorial_formula/capital_passthrough_tiered_cap_mode_a
    """
    ctx = setup_capital_petition_hearing(api, base_rent_cents=300000, bedrooms=2,
                                         requested_cost_cents=4800000, amortization_months=120)
    oheaders = make_hearing_officer_headers(ctx["officer_id"])
    validate_success(api.decide_hearing(ctx["hearing_id"], {"decision": "GRANT"}, oheaders))
    petition = validate_success(api.get_petition(ctx["petition_id"], oheaders))
    assert petition["granted_amount_cents"] == 18000
    unit = validate_success(api.get_unit(ctx["unit_id"], oheaders))
    assert unit["current_lawful_rent_cents"] == 318000


def test_capital_grant_sets_petition_granted_status(api):
    """PRD §3.5: "the petition transitions to `GRANTED` or `PARTIAL` respectively, the
    granted amount is **added** to the unit's `current_lawful_rent_cents`".

    Design: Difficulty/combinatorial_formula/capital_passthrough_tiered_cap_mode_a
    """
    ctx = setup_capital_petition_hearing(api, base_rent_cents=300000, bedrooms=2,
                                         requested_cost_cents=4800000, amortization_months=120)
    oheaders = make_hearing_officer_headers(ctx["officer_id"])
    hearing = validate_success(api.decide_hearing(ctx["hearing_id"], {"decision": "GRANT"}, oheaders))
    assert hearing["status"] == "HELD"
    assert hearing["decision"] == "GRANT"
    petition = validate_success(api.get_petition(ctx["petition_id"], oheaders))
    assert petition["status"] == "GRANTED"


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/hearing_grant_cascade_depth3
# ---------------------------------------------------------------------------
def _capital_hearing_with_tenancy(api):
    """Capital petition at HEARING_SCHEDULED on a unit that also has an ACTIVE tenancy."""
    ctx = setup_capital_petition_hearing(api, base_rent_cents=300000, bedrooms=2,
                                         requested_cost_cents=4800000, amortization_months=120)
    tenant = create_tenant(api)
    tenancy = create_active_tenancy(api, ctx["unit_id"], tenant["id"], ctx["landlord_id"])
    ctx["tenant"] = tenant
    ctx["tenancy"] = tenancy
    ctx["tenancy_id"] = tenancy["id"]
    return ctx


def test_grant_cascades_to_unit_and_tenancy(api):
    """PRD §3.5: "the granted amount is added to the unit's current_lawful_rent_cents, and
    that new lawful rent cascades to the unit's ACTIVE tenancy."
    PRD §2.6: "that tenancy's monthly_rent_cents is set to the unit's new lawful rent in the
    same operation."

    Design: Difficulty/transitive_cascade/hearing_grant_cascade_depth3
    """
    ctx = _capital_hearing_with_tenancy(api)
    oheaders = make_hearing_officer_headers(ctx["officer_id"])
    validate_success(api.decide_hearing(ctx["hearing_id"], {"decision": "GRANT"}, oheaders))
    unit = validate_success(api.get_unit(ctx["unit_id"], oheaders))
    tenancy = validate_success(api.get_tenancy(ctx["tenancy_id"], make_landlord_headers(ctx["landlord_id"])))
    assert unit["current_lawful_rent_cents"] == 318000
    assert tenancy["monthly_rent_cents"] == 318000


def test_grant_cascade_marks_petition_granted(api):
    """PRD §3.5: "the hearing moves to `HELD` with its `decision` recorded, the petition
    transitions to `GRANTED` or `PARTIAL` respectively".

    Design: Difficulty/transitive_cascade/hearing_grant_cascade_depth3
    """
    ctx = _capital_hearing_with_tenancy(api)
    oheaders = make_hearing_officer_headers(ctx["officer_id"])
    validate_success(api.decide_hearing(ctx["hearing_id"], {"decision": "GRANT"}, oheaders))
    petition = validate_success(api.get_petition(ctx["petition_id"], oheaders))
    assert petition["status"] == "GRANTED"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/petition_revision_cycle
# ---------------------------------------------------------------------------
def _petition_needs_revision(api):
    """Capital petition walked to NEEDS_REVISION."""
    ctx = setup_petition_under_review(
        api, "CAPITAL_IMPROVEMENT",
        petition_fields={"requested_cost_cents": 1200000, "amortization_months": 60})
    oheaders = make_hearing_officer_headers(ctx["officer_id"])
    get_success_data(api.request_revision_petition(ctx["petition_id"], oheaders,
                                                   {"reason": "insufficient invoices"}))
    return ctx


def test_resubmit_after_revision_increments_count(api):
    """PRD §3.5: "the landlord then resubmits (`NEEDS_REVISION → SUBMITTED`), and each such
    resubmission increments `revision_count` by one."

    Design: Difficulty/non_linear_state_machine/petition_revision_cycle
    """
    ctx = _petition_needs_revision(api)
    lheaders = make_landlord_headers(ctx["landlord_id"])
    petition = validate_success(api.submit_petition(ctx["petition_id"], lheaders))
    assert petition["revision_count"] == 1


def test_resubmit_after_revision_returns_to_submitted(api):
    """PRD §3.5: "From review the officer may send it back to the landlord for changes
    (UNDER_REVIEW → NEEDS_REVISION) ... the landlord then resubmits (NEEDS_REVISION → SUBMITTED)".

    Design: Difficulty/non_linear_state_machine/petition_revision_cycle
    """
    ctx = _petition_needs_revision(api)
    lheaders = make_landlord_headers(ctx["landlord_id"])
    petition = validate_success(api.submit_petition(ctx["petition_id"], lheaders))
    assert petition["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/hearing_requires_petition_under_review
# ---------------------------------------------------------------------------
def test_schedule_hearing_on_submitted_petition_rejected(api):
    """PRD §3.5: "moving the petition `UNDER_REVIEW → HEARING_SCHEDULED`; scheduling
    requires the petition to be `UNDER_REVIEW`, otherwise `ERR_PETITION_NOT_UNDER_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/hearing_requires_petition_under_review
    """
    landlord = create_landlord(api)
    officer = create_officer(api)
    unit = create_unit(api, landlord["id"], base_rent_cents=300000, bedrooms=2)
    lheaders = make_landlord_headers(landlord["id"])
    petition = get_success_data(api.create_petition(
        create_petition_payload(unit["id"], landlord["id"], "CAPITAL_IMPROVEMENT",
                                requested_cost_cents=1200000, amortization_months=120),
        lheaders))
    get_success_data(api.submit_petition(petition["id"], lheaders))  # SUBMITTED, not reviewed
    resp = api.schedule_hearing(
        petition["id"],
        create_hearing_payload(officer["id"], "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z"),
        CLERK)
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_UNDER_REVIEW)


def test_schedule_hearing_on_under_review_petition_succeeds(api):
    """PRD §3.5: "from UNDER_REVIEW the board clerk schedules a hearing, moving the petition
    UNDER_REVIEW → HEARING_SCHEDULED ... On success a Hearing is created in SCHEDULED status
    with a null decision, and the petition moves to HEARING_SCHEDULED."

    Design: Difficulty/cross_entity_state_dependency/hearing_requires_petition_under_review
    """
    ctx = setup_petition_under_review(
        api, "CAPITAL_IMPROVEMENT",
        petition_fields={"requested_cost_cents": 1200000, "amortization_months": 120})
    hearing = validate_success(api.schedule_hearing(
        ctx["petition_id"],
        create_hearing_payload(ctx["officer_id"], "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z"),
        CLERK), expected_status=201)
    assert hearing["status"] == "SCHEDULED"
    petition = validate_success(api.get_petition(ctx["petition_id"], CLERK))
    assert petition["status"] == "HEARING_SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/hearing_officer_buffered_overlap
# ---------------------------------------------------------------------------
def _officer_with_hearing_and_second_review(api):
    """One officer with a SCHEDULED hearing 10:00-11:00 (petition A), plus a second
    petition B in UNDER_REVIEW. Returns (officer_id, petition_b_id, unit-owner-landlord_id)."""
    landlord = create_landlord(api)
    officer = create_officer(api)
    unit = create_unit(api, landlord["id"], base_rent_cents=300000, bedrooms=2)
    lheaders = make_landlord_headers(landlord["id"])
    oheaders = make_hearing_officer_headers(officer["id"])

    pet_a = get_success_data(api.create_petition(
        create_petition_payload(unit["id"], landlord["id"], "CAPITAL_IMPROVEMENT",
                                requested_cost_cents=1200000, amortization_months=120), lheaders))
    get_success_data(api.submit_petition(pet_a["id"], lheaders))
    get_success_data(api.review_petition(pet_a["id"], oheaders))
    get_success_data(api.schedule_hearing(
        pet_a["id"],
        create_hearing_payload(officer["id"], "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z"),
        CLERK))

    pet_b = get_success_data(api.create_petition(
        create_petition_payload(unit["id"], landlord["id"], "CAPITAL_IMPROVEMENT",
                                requested_cost_cents=1200000, amortization_months=120), lheaders))
    get_success_data(api.submit_petition(pet_b["id"], lheaders))
    get_success_data(api.review_petition(pet_b["id"], oheaders))
    return officer["id"], pet_b["id"]


def test_officer_buffered_overlap_rejected(api):
    """PRD §3.5: "a conflict exists when the requested start is earlier than the existing
    hearing's end extended by thirty minutes, and the existing hearing's start is earlier
    than the requested end extended by thirty minutes." (11:15 < 11:30 conflicts.)

    Design: Difficulty/resource_temporal_overlap/hearing_officer_buffered_overlap
    """
    officer_id, pet_b_id = _officer_with_hearing_and_second_review(api)
    resp = api.schedule_hearing(
        pet_b_id,
        create_hearing_payload(officer_id, "2026-06-10T11:15:00Z", "2026-06-10T12:00:00Z"),
        CLERK)
    validate_error(resp, ApiErrorId.ERR_OFFICER_UNAVAILABLE)


def test_officer_start_exactly_at_buffer_end_allowed(api):
    """PRD §3.5: "A request whose start falls exactly at an existing hearing's end plus
    thirty minutes does not conflict and is allowed." (11:00 end + 30 min = 11:30.)

    Design: Difficulty/resource_temporal_overlap/hearing_officer_buffered_overlap
    """
    officer_id, pet_b_id = _officer_with_hearing_and_second_review(api)
    hearing = validate_success(api.schedule_hearing(
        pet_b_id,
        create_hearing_payload(officer_id, "2026-06-10T11:30:00Z", "2026-06-10T12:30:00Z"),
        CLERK), expected_status=201)
    assert hearing["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner/calculations
# ---------------------------------------------------------------------------
def test_hardship_passthrough_capped(api):
    """PRD §3.5: "For a HARDSHIP petition, the requested amount is the unit's
    current_lawful_rent_cents multiplied by the petition's requested_pct, rounded half-up.
    A hardship cap is the unit's current_lawful_rent_cents multiplied by 0.08 (eight
    percent), rounded half-up. The full passthrough is the smaller of the requested amount
    and the hardship cap." (min(60000, 24000) = 24000.)

    Design: Corner/calculations/hardship_passthrough_capped
    """
    ctx = setup_hardship_petition_hearing(api, base_rent_cents=300000, bedrooms=2,
                                          requested_pct=0.20)
    oheaders = make_hearing_officer_headers(ctx["officer_id"])
    validate_success(api.decide_hearing(ctx["hearing_id"], {"decision": "GRANT"}, oheaders))
    petition = validate_success(api.get_petition(ctx["petition_id"], oheaders))
    assert petition["granted_amount_cents"] == 24000
    unit = validate_success(api.get_unit(ctx["unit_id"], oheaders))
    assert unit["current_lawful_rent_cents"] == 324000


def test_partial_decision_applies_supplied_amount(api):
    """PRD §3.5: "On a PARTIAL, the officer supplies granted_amount_cents, which must be
    strictly greater than zero and strictly less than the full passthrough ... and
    petition.granted_amount_cents is set to that supplied amount."

    Design: Corner/calculations/partial_decision_applies_supplied_amount
    """
    ctx = setup_capital_petition_hearing(api, base_rent_cents=300000, bedrooms=2,
                                         requested_cost_cents=4800000, amortization_months=120)
    oheaders = make_hearing_officer_headers(ctx["officer_id"])
    validate_success(api.decide_hearing(
        ctx["hearing_id"], {"decision": "PARTIAL", "granted_amount_cents": 10000}, oheaders))
    petition = validate_success(api.get_petition(ctx["petition_id"], oheaders))
    assert petition["status"] == "PARTIAL"
    assert petition["granted_amount_cents"] == 10000
    unit = validate_success(api.get_unit(ctx["unit_id"], oheaders))
    assert unit["current_lawful_rent_cents"] == 310000


def test_partial_decision_at_or_above_full_rejected(api):
    """PRD §3.5: "On a PARTIAL, the officer supplies granted_amount_cents, which must be
    strictly greater than zero and strictly less than the full passthrough — anything
    outside that open interval is rejected with ERR_INVALID_GRANT_AMOUNT." (full = 18000.)

    Design: Corner/calculations/partial_decision_amount_at_or_above_full_rejected
    """
    ctx = setup_capital_petition_hearing(api, base_rent_cents=300000, bedrooms=2,
                                         requested_cost_cents=4800000, amortization_months=120)
    oheaders = make_hearing_officer_headers(ctx["officer_id"])
    resp = api.decide_hearing(
        ctx["hearing_id"], {"decision": "PARTIAL", "granted_amount_cents": 18000}, oheaders)
    validate_error(resp, ApiErrorId.ERR_INVALID_GRANT_AMOUNT)


# ---------------------------------------------------------------------------
# Corner/state_machines/petition_submit_from_submitted_invalid_state
# ---------------------------------------------------------------------------
def test_submit_from_submitted_invalid_state(api):
    """PRD §2.8: "State — the target resource is in a state from which the requested
    transition is defined, else ERR_INVALID_STATE (409)."
    PRD §3.5: "The petitioning landlord submits a DRAFT petition, moving it DRAFT → SUBMITTED."

    Design: Corner/state_machines/petition_submit_from_submitted_invalid_state
    """
    landlord = create_landlord(api)
    unit = create_unit(api, landlord["id"], base_rent_cents=300000, bedrooms=2)
    lheaders = make_landlord_headers(landlord["id"])
    petition = get_success_data(api.create_petition(
        create_petition_payload(unit["id"], landlord["id"], "CAPITAL_IMPROVEMENT",
                                requested_cost_cents=600000, amortization_months=60), lheaders))
    get_success_data(api.submit_petition(petition["id"], lheaders))
    resp = api.submit_petition(petition["id"], lheaders)  # already SUBMITTED
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
