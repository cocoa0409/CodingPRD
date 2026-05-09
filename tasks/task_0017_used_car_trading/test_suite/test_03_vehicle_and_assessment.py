"""Tests for PRD §3.1 — Vehicle registration, VIN format, AssessmentReport
state machine (DRAFT → ONSITE_PENDING → FINALIZED), and the three
calculations that fire on finalize: mileage verification, final valuation,
and vehicle assessment score.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_assessment_to_onsite,
    api_client,
    assert_assessment_report,
    assert_vehicle,
    create_assessment_payload,
    create_draft_assessment,
    create_vehicle_payload,
    finalize_assessment,
    make_seller_headers,
    onsite_findings_payload,
    register_seller,
    register_vehicle,
    setup_finalized_assessment,
    validate_error,
    validate_success,
    vin_history,
)


# ──────────────────────────────────────────────────────────
# §3.1 Vehicle creation and VIN format
# ──────────────────────────────────────────────────────────


def test_create_vehicle_starts_in_registered(api):
    """PRD §3.1: "The vehicle enters the system in vehicle_status REGISTERED.
    Two computed fields, assessment_score and valuation_cents, both start as
    null and are filled by the assessment workflow; verified_mileage_km is
    likewise null until the first finalised on-site report."
    """
    seller = register_seller()
    vehicle = register_vehicle(seller)
    assert_vehicle(vehicle)
    assert vehicle["vehicle_status"] == "REGISTERED"
    assert vehicle["assessment_score"] is None
    assert vehicle["valuation_cents"] is None
    assert vehicle["verified_mileage_km"] is None


def test_create_vehicle_ownership_points_to_registering_seller(api):
    """PRD §3.1: "ownership_seller_id initially points to the registering
    seller's id"."""
    seller = register_seller()
    vehicle = register_vehicle(seller)
    assert vehicle["ownership_seller_id"] == seller["id"]


@pytest.mark.parametrize(
    "bad_vin",
    [
        "1HGCM82633A00415",  # 16 chars
        "1HGCM82633A0041555",  # 18 chars
        "1HGCM82633I004155",  # contains I
        "1HGCM82633O004155",  # contains O
        "1HGCM82633Q004155",  # contains Q
        "1HGCM82633A00415-",  # contains symbol
    ],
)
def test_invalid_vin_rejected(api, bad_vin):
    """PRD §3.1: "The vin must consist of exactly 17 alphanumeric characters
    with no I, no O, and no Q; any other shape is rejected with
    ERR_VIN_INVALID."
    """
    seller = register_seller()
    res = api.create_vehicle(
        create_vehicle_payload(vin=bad_vin), make_seller_headers(seller["id"])
    )
    validate_error(res, "ERR_VIN_INVALID")


def test_model_year_below_1980_rejected(api):
    """PRD §3.1: "The model_year must be at least 1980 and at most the current
    calendar year." Any sane reader treats year 1979 as out of range; PRD
    does not name an error_id for the year violation, so the test only
    asserts the request fails (silence-pattern: error-precedence)."""
    seller = register_seller()
    res = api.create_vehicle(
        create_vehicle_payload(model_year=1979),
        make_seller_headers(seller["id"]),
    )
    assert res.status_code >= 400


# ──────────────────────────────────────────────────────────
# §3.1 AssessmentReport — DRAFT initial state
# ──────────────────────────────────────────────────────────


def test_assessment_report_starts_in_draft_with_derived_counts(api):
    """PRD §3.1: "The report enters in status DRAFT with accident_count,
    major_accident_count, and maintenance_count derived directly from the
    history records, and provisional_valuation_cents, final_valuation_cents,
    mileage_discrepancy_flag, and declared_mileage_km (the report's snapshot
    field) all initialised to their nulls and zeros."
    """
    seller = register_seller()
    vehicle = register_vehicle(seller)
    history = vin_history(accidents=2, major_accidents=1, maintenance=3)
    draft = create_draft_assessment(vehicle, vin_history_records=history)
    assert_assessment_report(draft)
    assert draft["status"] == "DRAFT"
    # vin_history()'s accidents= param gives MINOR severity; major_accidents
    # are also ACCIDENT events. Total ACCIDENT count = accidents + major.
    assert draft["accident_count"] == 3
    assert draft["major_accident_count"] == 1
    assert draft["maintenance_count"] == 3
    assert draft["provisional_valuation_cents"] is None
    assert draft["final_valuation_cents"] is None
    assert draft["mileage_discrepancy_flag"] is False


# ──────────────────────────────────────────────────────────
# §3.1 DRAFT → ONSITE_PENDING — provisional valuation
# ──────────────────────────────────────────────────────────


def test_request_onsite_with_empty_history_rejected(api):
    """PRD §3.1: "Requesting on-site inspection advances the report from
    DRAFT to ONSITE_PENDING. This requires vin_history_records to be
    non-empty; otherwise the transition is refused with ERR_INVALID_STATE."
    """
    seller = register_seller()
    vehicle = register_vehicle(seller)
    # Build an assessment then attempt to bypass — but factory always inserts
    # at least one record; supply an explicit empty list.
    payload = create_assessment_payload(vin_history_records=[])
    create_res = api.create_assessment(
        vehicle["id"],
        payload,
        {"X-User-ID": "00000000-0000-4000-8000-0000000a1501", "X-User-Role": "Inspector"},
    )
    if create_res.status_code >= 400:
        # Implementation chose to reject empty history at create time — also
        # acceptable; the PRD §3.1 says non-empty is required at request-onsite,
        # so creation may or may not enforce this. The test must observe the
        # rejection at the *latest* by the request-onsite step.
        return
    draft = validate_success(create_res, expected_status=201)
    res = api.request_onsite(
        draft["id"],
        {"X-User-ID": "00000000-0000-4000-8000-0000000a1501", "X-User-Role": "Inspector"},
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_provisional_valuation_known_inputs_yield_expected_cents(api):
    """PRD §3.1 (provisional formula): with declared_mileage_km=100000,
    1 minor ACCIDENT + 2 MAINTENANCE records, the provisional valuation
    is base * mileage_factor * (1 - history_penalty)
    = 1_000_000 * max(0.5, 1 - (100_000/200_000)*0.5) * (1 - (1*800 + 2*50)/10000)
    = 1_000_000 * 0.75 * (1 - 0.09)
    = 1_000_000 * 0.75 * 0.91
    = 682_500 cents (round_half_up at the final step).

    PRD §3.1: "Take the base price for the make-model-year (treat the
    platform-supplied base price as a constant of one million cents per
    vehicle for the purposes of this calculation), multiply by a mileage
    factor that is the larger of one half and the value of one minus the
    declared mileage in kilometres divided by the reference mileage of two
    hundred thousand kilometres and that ratio further multiplied by the
    mileage decay constant of one half, and then multiply by a history
    factor that is one minus the history penalty."
    """
    seller = register_seller()
    vehicle = register_vehicle(seller, declared_mileage_km=100_000)
    history = vin_history(accidents=1, maintenance=2)
    draft = create_draft_assessment(vehicle, vin_history_records=history)
    onsite_pending = advance_assessment_to_onsite(draft)
    assert onsite_pending["status"] == "ONSITE_PENDING"
    assert onsite_pending["provisional_valuation_cents"] == 682_500


def test_provisional_mileage_factor_floored_at_one_half(api):
    """PRD §3.1: "multiply by a mileage factor that is the larger of one half
    and the value of one minus the declared mileage in kilometres divided by
    the reference mileage of two hundred thousand kilometres and that ratio
    further multiplied by the mileage decay constant of one half".

    Setup: declared_mileage_km=300_000 (well above 200_000 reference); the
    formula yields max(0.5, 1 - 1.5*0.5) = max(0.5, 0.25) → clamped to 0.5.
    With no history events, provisional = 1_000_000 * 0.5 * 1 = 500_000.
    """
    seller = register_seller()
    vehicle = register_vehicle(seller, declared_mileage_km=300_000)
    history = vin_history(registrations=1)  # no penalty events
    draft = create_draft_assessment(vehicle, vin_history_records=history)
    onsite_pending = advance_assessment_to_onsite(draft)
    assert onsite_pending["provisional_valuation_cents"] == 500_000


# ──────────────────────────────────────────────────────────
# §3.1 ONSITE_PENDING → FINALIZED — final valuation, score, discrepancy
# ──────────────────────────────────────────────────────────


def test_finalize_without_onsite_findings_rejected(api):
    """PRD §3.1: "The body must carry an onsite_findings object with all four
    sub-grades (exterior_grade, interior_grade, mechanical_grade, each one of
    A, B, C, or D, plus mileage_km_observed), and the report's
    inspector_user_id must already be set; either omission rejects with
    ERR_INVALID_STATE."
    """
    seller = register_seller()
    vehicle = register_vehicle(seller)
    draft = create_draft_assessment(vehicle, vin_history_records=vin_history(maintenance=1))
    onsite_pending = advance_assessment_to_onsite(draft)
    res = api.finalize_assessment(
        onsite_pending["id"],
        {},  # no onsite_findings
        {"X-User-ID": "00000000-0000-4000-8000-0000000a1501", "X-User-Role": "Inspector"},
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_mileage_discrepancy_flag_set_when_observed_below_declared(api):
    """PRD §3.1: "If the difference is negative — that is, the observed
    reading is below what was declared — the mileage_discrepancy_flag is set
    to true."

    Setup: declared=100_000, observed=99_000 → delta=-1_000 < 0 → flag=true.
    """
    seller = register_seller()
    vehicle = register_vehicle(seller, declared_mileage_km=100_000)
    draft = create_draft_assessment(vehicle, vin_history_records=vin_history(maintenance=1))
    onsite_pending = advance_assessment_to_onsite(draft)
    finalized = finalize_assessment(
        onsite_pending,
        onsite=onsite_findings_payload(mileage_km_observed=99_000),
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["mileage_discrepancy_flag"] is True


def test_mileage_discrepancy_flag_set_when_ratio_exceeds_five_percent(api):
    """PRD §3.1: "If declared_mileage_km is greater than zero and the
    absolute value of the difference divided by the declared mileage is
    greater than the discrepancy tolerance of five percent, the flag is also
    set to true."

    Setup: declared=100_000, observed=110_000 → delta=10_000, ratio=0.10 > 0.05.
    """
    seller = register_seller()
    vehicle = register_vehicle(seller, declared_mileage_km=100_000)
    draft = create_draft_assessment(vehicle, vin_history_records=vin_history(maintenance=1))
    onsite_pending = advance_assessment_to_onsite(draft)
    finalized = finalize_assessment(
        onsite_pending,
        onsite=onsite_findings_payload(mileage_km_observed=110_000),
    )
    assert finalized["mileage_discrepancy_flag"] is True


def test_mileage_discrepancy_flag_clear_when_observed_equals_declared(api):
    """PRD §3.1: "In every other case the flag is false." — observed equal
    to declared yields delta=0, ratio=0, neither branch fires.
    """
    seller = register_seller()
    vehicle = register_vehicle(seller, declared_mileage_km=100_000)
    draft = create_draft_assessment(vehicle, vin_history_records=vin_history(maintenance=1))
    onsite_pending = advance_assessment_to_onsite(draft)
    finalized = finalize_assessment(
        onsite_pending,
        onsite=onsite_findings_payload(mileage_km_observed=100_000),
    )
    assert finalized["mileage_discrepancy_flag"] is False


def test_verified_mileage_written_to_vehicle_on_finalize(api, admin_headers):
    """PRD §3.1: "The system additionally writes the observed mileage to
    Vehicle.verified_mileage_km."
    """
    seller = register_seller()
    vehicle = register_vehicle(seller, declared_mileage_km=100_000)
    draft = create_draft_assessment(vehicle, vin_history_records=vin_history(maintenance=1))
    onsite_pending = advance_assessment_to_onsite(draft)
    finalize_assessment(
        onsite_pending,
        onsite=onsite_findings_payload(mileage_km_observed=99_000),
    )
    refreshed = validate_success(api.get_vehicle(vehicle["id"], admin_headers), 200)
    assert refreshed["verified_mileage_km"] == 99_000


def test_first_finalize_advances_vehicle_to_assessed(api, admin_headers):
    """PRD §3.1: "The first finalised report for a given vehicle advances the
    vehicle from REGISTERED to ASSESSED"."""
    seller, vehicle, finalized = setup_finalized_assessment()
    refreshed = validate_success(api.get_vehicle(vehicle["id"], admin_headers), 200)
    assert refreshed["vehicle_status"] == "ASSESSED"


def test_first_finalize_writes_assessment_score_and_valuation_to_vehicle(api, admin_headers):
    """PRD §3.1: "Store this on Vehicle.assessment_score and store the final
    valuation on Vehicle.valuation_cents."
    """
    seller, vehicle, finalized = setup_finalized_assessment()
    refreshed = validate_success(api.get_vehicle(vehicle["id"], admin_headers), 200)
    assert refreshed["assessment_score"] is not None
    assert refreshed["valuation_cents"] is not None
    # The valuation that lands on the Vehicle must match the report's final.
    assert refreshed["valuation_cents"] == finalized["final_valuation_cents"]


def test_subsequent_finalize_supersedes_prior_report(api, admin_headers):
    """PRD §3.1: "Whenever a newer report is finalised, every prior report
    for the same vehicle that was in FINALIZED is moved to SUPERSEDED."
    """
    seller, vehicle, first = setup_finalized_assessment(history=vin_history(maintenance=1))
    # Finalize a second report on the same vehicle.
    second_draft = create_draft_assessment(
        vehicle, vin_history_records=vin_history(maintenance=2)
    )
    second_onsite = advance_assessment_to_onsite(second_draft)
    finalize_assessment(
        second_onsite,
        onsite=onsite_findings_payload(mileage_km_observed=vehicle["declared_mileage_km"]),
    )
    first_after = validate_success(api.get_assessment(first["id"], admin_headers), 200)
    assert first_after["status"] == "SUPERSEDED"
