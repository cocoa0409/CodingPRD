"""Facility consults: the ESTIMATED->CONFIRMED re-score, the depth-3 dose-
confirmation cascade, the accepting/capacity gates, the consult-count invariant,
and net billing units.

Translations of Difficulty rules `dual_variant_calc` / `transitive_cascade` /
`cross_entity_state_dependency` / `compensating_invariant` and Corner
`calculations` / `validations`.
"""
from test_helpers import (
    ApiErrorId,
    create_facility_consult_payload,
    make_specialist_headers,
    make_toxicologist_headers,
    open_case,
    seed_facility,
    seed_specialist,
    setup_diverting_facility_case,
    setup_monitoring_case_with_consult,
    setup_triaged_consult,
    validate_error,
    validate_success,
)


def test_confirmed_variant_rescores_exposure_toxicity(api):
    """PRD §3.7: "First, every exposure on the case has its `confirmed_dose_mg` set
    from the consult's confirmed dose, and its `toxicity_score` (and
    `severity_band`) is recomputed under the CONFIRMED variant, which typically
    diverges from the ESTIMATED score."

    Design: Difficulty/dual_variant_calc/exposure_estimated_vs_confirmed_toxicity
    """
    ctx = setup_triaged_consult(api, dose_low=1000, dose_high=1500, weight=20, capacity=2)
    tox_headers = make_toxicologist_headers(ctx["tox"]["id"])
    api.close_facility_consult(ctx["consult"]["id"], {"confirmed_dose_mg": 5000}, tox_headers)
    exp = validate_success(api.get_exposure(ctx["exposure"]["id"],
                                            make_specialist_headers(ctx["spi"]["id"])))
    assert exp["toxicity_score"] == 1.67
    assert exp["severity_band"] == "CRITICAL"


def test_confirmed_dose_propagated_to_exposure(api):
    """PRD §3.3: "A `confirmed_dose_mg` field remains null until a facility consult
    later writes a laboratory-verified dose."

    Design: Difficulty/dual_variant_calc/exposure_estimated_vs_confirmed_toxicity
    """
    ctx = setup_triaged_consult(api, dose_low=1000, dose_high=1500, weight=20, capacity=2)
    tox_headers = make_toxicologist_headers(ctx["tox"]["id"])
    api.close_facility_consult(ctx["consult"]["id"], {"confirmed_dose_mg": 5000}, tox_headers)
    exp = validate_success(api.get_exposure(ctx["exposure"]["id"],
                                            make_specialist_headers(ctx["spi"]["id"])))
    assert exp["confirmed_dose_mg"] == 5000


def test_consult_close_rescores_assessment_to_critical(api):
    """PRD §3.7: "Second, the case's active risk assessment recomputes both its
    aggregate scores and its `risk_tier`."

    Design: Difficulty/transitive_cascade/consult_close_cascade_depth3
    """
    ctx = setup_monitoring_case_with_consult(api)
    tox_headers = make_toxicologist_headers(ctx["tox"]["id"])
    spi_headers = make_specialist_headers(ctx["spi"]["id"])
    api.close_facility_consult(ctx["consult"]["id"], {"confirmed_dose_mg": 5000}, tox_headers)
    exp = validate_success(api.get_exposure(ctx["exposure"]["id"], spi_headers))
    ra = validate_success(api.get_risk_assessment(ctx["ra"]["id"], spi_headers))
    assert exp["toxicity_score"] == 1.67
    assert ra["risk_tier"] == "CRITICAL"


def test_consult_close_critical_escalation_refers_case_and_cancels_followups(api):
    """PRD §3.7: "Third, if that recomputed `risk_tier` escalates to `CRITICAL`, the
    case is driven from `MONITORING` to `REFERRED`: its active home-management
    disposition moves to `SUPERSEDED`, and all of its `SCHEDULED` or `ATTEMPTED`
    follow-up calls are cancelled, each decrementing `pending_followup_count`."

    Design: Difficulty/transitive_cascade/consult_close_cascade_depth3
    """
    ctx = setup_monitoring_case_with_consult(api)
    tox_headers = make_toxicologist_headers(ctx["tox"]["id"])
    spi_headers = make_specialist_headers(ctx["spi"]["id"])
    api.close_facility_consult(ctx["consult"]["id"], {"confirmed_dose_mg": 5000}, tox_headers)
    case = validate_success(api.get_case(ctx["case"]["id"], spi_headers))
    assert case["status"] == "REFERRED"
    assert case["pending_followup_count"] == 0


def test_consult_on_diverting_facility_rejected(api):
    """PRD §3.7: "a consult against a facility whose `status` is not `ACCEPTING` is
    rejected with `ERR_FACILITY_NOT_ACCEPTING` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/consult_requires_accepting_facility
    """
    ctx = setup_diverting_facility_case(api)
    resp = api.create_facility_consult(
        create_facility_consult_payload(ctx["case"]["id"], ctx["facility"]["id"], 90),
        make_toxicologist_headers(ctx["tox"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_ACCEPTING)


def test_rejected_consult_leaves_facility_count_zero(api):
    """PRD §3.7: "A new consult starts in `ACTIVE`, increments the facility's
    `active_consult_count`, and stamps `requesting_specialist_id` from `X-User-ID`."

    Design: Difficulty/cross_entity_state_dependency/consult_requires_accepting_facility
    """
    ctx = setup_diverting_facility_case(api)
    api.create_facility_consult(
        create_facility_consult_payload(ctx["case"]["id"], ctx["facility"]["id"], 90),
        make_toxicologist_headers(ctx["tox"]["id"]))
    facility = validate_success(api.get_facility(ctx["facility"]["id"],
                                                 make_toxicologist_headers(ctx["tox"]["id"])))
    assert facility["active_consult_count"] == 0


def test_active_consult_count_returns_to_zero_after_close(api):
    """PRD §3.7: "On close, the consult computes its net `billing_units` and moves
    from `ACTIVE` to `CLOSED`, and the facility's `active_consult_count` is
    decremented by one."

    Design: Difficulty/compensating_invariant/facility_active_consult_count_invariant
    """
    ctx = setup_triaged_consult(api, dose_low=1200, dose_high=1500, weight=20, capacity=2)
    tox_headers = make_toxicologist_headers(ctx["tox"]["id"])
    api.close_facility_consult(ctx["consult"]["id"], {"confirmed_dose_mg": 1500}, tox_headers)
    facility = validate_success(api.get_facility(ctx["facility"]["id"], tox_headers))
    assert facility["active_consult_count"] == 0


def test_consult_status_closed_after_close(api):
    """PRD §3.7: "On close, the consult computes its net `billing_units` and moves
    from `ACTIVE` to `CLOSED`, and the facility's `active_consult_count` is
    decremented by one."

    Design: Difficulty/compensating_invariant/facility_active_consult_count_invariant
    """
    ctx = setup_triaged_consult(api, dose_low=1200, dose_high=1500, weight=20, capacity=2)
    tox_headers = make_toxicologist_headers(ctx["tox"]["id"])
    consult = validate_success(
        api.close_facility_consult(ctx["consult"]["id"], {"confirmed_dose_mg": 1500}, tox_headers))
    assert consult["status"] == "CLOSED"


def test_consult_billing_units_gross_keyed_discount(api):
    """PRD §3.7: "Gross units are a base of 2 units plus those specialist units,
    rounded half-up to 2 decimal places. A volume discount is then keyed on those
    gross (pre-discount) units: no discount when gross units are below 5, a 10
    percent discount when they are at least 5 but below 10, and a 20 percent
    discount when they are 10 or more. The net `billing_units` is the gross units
    multiplied by one minus the discount fraction, rounded half-up to 2 decimal
    places."

    Design: Corner/calculations/consult_billing_units_discount_correct
    """
    ctx = setup_triaged_consult(api, dose_low=3000, dose_high=3000, weight=20, capacity=2)
    tox_headers = make_toxicologist_headers(ctx["tox"]["id"])
    consult = validate_success(
        api.close_facility_consult(ctx["consult"]["id"], {"confirmed_dose_mg": 3000}, tox_headers))
    assert consult["billing_units"] == 5.85


def test_facility_at_capacity_rejected(api):
    """PRD §3.7: "a consult opened when the facility's `active_consult_count`
    already equals its `consult_capacity` is rejected with `ERR_FACILITY_AT_CAPACITY`
    (HTTP 409)."

    Design: Corner/validations/facility_at_capacity_rejected
    """
    facility = seed_facility(api, name="Small ED", consult_capacity=1)
    spi = seed_specialist(api)
    tox = seed_specialist(api, full_name="Tara Tox", credential="TOXICOLOGIST")
    case = open_case(api, spi["id"])
    tox_headers = make_toxicologist_headers(tox["id"])
    validate_success(api.create_facility_consult(
        create_facility_consult_payload(case["id"], facility["id"], 60), tox_headers), 201)
    resp = api.create_facility_consult(
        create_facility_consult_payload(case["id"], facility["id"], 60), tox_headers)
    validate_error(resp, ApiErrorId.ERR_FACILITY_AT_CAPACITY)
