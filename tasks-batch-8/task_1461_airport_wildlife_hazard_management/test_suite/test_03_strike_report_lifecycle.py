"""Strike-report lifecycle: FK checks, terminal-state lockdown, confirm
cascades, immediate consistency, and validation ordering."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    assert_carcass_record,
    set_clock,
    create_airport,
    create_species,
    create_biologist,
    create_strike_report_payload,
    create_draft_strike,
    create_under_review_strike,
    submit_strike,
    begin_review_strike,
    confirm_strike,
    setup_airport_with_biologists,
    get_airport,
    make_biologist_headers,
    NON_EXISTENT_UUID,
    ApiErrorId,
)


def test_fk_not_found_on_strike_report_species(api):
    """PRD §2.5: "Separately, every foreign key supplied in a request body
    must reference an existing record of the correct entity type; violations
    are rejected with `ERR_FK_NOT_FOUND` (HTTP 422)."

    Design: Corner/validations/fk_not_found_on_strike_report_species
    """
    set_clock()
    airport = create_airport(icao_code="KJJJ", name="Juliett Airport")
    b1 = create_biologist(airport["id"], is_senior=True, certification_id="CERT-J01")
    payload = create_strike_report_payload(
        airport["id"], b1["id"], NON_EXISTENT_UUID,
        strike_at="2026-07-15T10:00:00Z", aircraft_registration="N-J1",
    )
    res = api.create_strike_report(payload, make_biologist_headers(b1["id"]))
    validate_error(res, ApiErrorId.ERR_FK_NOT_FOUND.value, expected_status=422)


def test_strike_report_invalid_transition_from_terminal(api):
    """PRD §2.6: "The order is: authentication (`ERR_UNAUTHENTICATED`) first,
    then role authorization (`ERR_UNAUTHORIZED`), then path-identifier
    resolution (`ERR_NOT_FOUND`), then body foreign-key resolution
    (`ERR_FK_NOT_FOUND`), then state-machine legality (`ERR_INVALID_STATE`)"
    PRD §3.2: "Rejecting the strike (`UNDER_REVIEW → REJECTED`) requires only
    the segregation-of-duties check."

    Design: Corner/state_machines/strike_report_invalid_transition_from_terminal
    """
    set_clock()
    airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
        icao_code="KDDD", cert_senior="CERT-D01", cert_junior="CERT-D02",
    )
    sp = create_species(
        common_name="Ring-billed Gull", scientific_name="Larus delawarensis",
        guild="GULL", risk_tier="MEDIUM", body_mass_g=550,
        is_protected_federally=True,
    )
    strike = create_under_review_strike(
        airport["id"], b2, b1, sp["id"], aircraft_registration="N-D1",
    )
    rejected = validate_success(api.reject_strike_report(strike["id"], b1h), 200)
    assert rejected["status"] == "REJECTED"

    res = api.confirm_strike_report(strike["id"], {"confirmation_notes": "should fail"}, b1h)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_carcass_record_fk_reverse_reachable_via_parent(api):
    """PRD §3.2: "on success the server stamps `confirmed_by_biologist_id`
    with the acting biologist's `id`, recomputes the airport's
    trailing-twelve-month strike counts, recomputes the airport's
    `current_hazard_level`, and — if `carcass_present` is `true` and no
    `CarcassRecord` yet exists for this strike — auto-creates a
    `CarcassRecord` in `COLLECTED` with `species_id_at_collection` set to the
    strike's `species_id`."

    Design: Corner/entities/carcass_record_fk_reverse_reachable_via_parent
    """
    set_clock()
    airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
        icao_code="KCCC", cert_senior="CERT-C01", cert_junior="CERT-C02",
    )
    sp = create_species(
        common_name="Ring-billed Gull", scientific_name="Larus delawarensis",
        guild="GULL", risk_tier="MEDIUM", body_mass_g=550,
        is_protected_federally=True,
    )
    strike = create_draft_strike(
        airport["id"], b2, sp["id"], strike_at="2026-07-15T10:00:00Z",
        damage_class="MINOR", carcass_present=True, aircraft_registration="N-C1",
    )
    submit_strike(strike["id"], b2)
    begin_review_strike(strike["id"], b1)
    confirm_strike(strike["id"], b1, notes="carcass present")

    rows = validate_success(
        api.list_carcass_records_for_strike(strike["id"], b1h), 200,
    )
    assert isinstance(rows, list) and len(rows) == 1, (
        f"expected exactly one auto-created carcass record, got {len(rows)}"
    )
    assert_carcass_record(rows[0])
    assert rows[0]["strike_report_id"] == strike["id"]
    assert rows[0]["identification_status"] == "COLLECTED"


def test_immediate_consistency_after_strike_confirm(api):
    """PRD §3.2: "on success the server stamps `confirmed_by_biologist_id`
    with the acting biologist's `id`, recomputes the airport's
    trailing-twelve-month strike counts, recomputes the airport's
    `current_hazard_level`"
    PRD §3.5: "otherwise if `strikes_trailing_12m` is at least 10, the base is
    `HIGH`; otherwise if it is at least 5, the base is `ELEVATED`; otherwise
    the base is `LOW`."

    Design: Corner/consistency_model/immediate_consistency_after_strike_confirm
    """
    set_clock()
    airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
        icao_code="KUUU", cert_senior="CERT-U01", cert_junior="CERT-U02",
    )
    sp = create_species(
        common_name="Ring-billed Gull", scientific_name="Larus delawarensis",
        guild="GULL", risk_tier="MEDIUM", body_mass_g=550,
        is_protected_federally=True,
    )
    strike = create_under_review_strike(
        airport["id"], b2, b1, sp["id"], aircraft_registration="N-U1",
    )
    confirm_strike(strike["id"], b1)

    airport_after = get_airport(airport["id"], b1h)
    assert airport_after["strikes_trailing_12m"] == 1, (
        f"expected 1 immediately after confirm, got {airport_after['strikes_trailing_12m']}"
    )
    assert airport_after["current_hazard_level"] == "LOW"


class TestConfirmValidationOrdering:
    """Priority pair: state-machine legality outranks the senior-biologist
    requirement when both are violated on strike confirm."""

    def test_confirm_draft_by_nonsenior_reporter_returns_invalid_state(self, api):
        """PRD §2.6: "A request failing several of these surfaces only the
        earliest error in this order." (state-machine legality
        `ERR_INVALID_STATE` precedes the senior-biologist requirement
        `ERR_SENIOR_REQUIRED`.)

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_confirm
        """
        set_clock()
        airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
            icao_code="KIII", cert_senior="CERT-801", cert_junior="CERT-802",
        )
        sp = create_species(
            common_name="Bald Eagle", scientific_name="Haliaeetus leucocephalus",
            guild="RAPTOR", risk_tier="HIGH", body_mass_g=5500,
            is_protected_federally=True,
        )
        strike = create_draft_strike(
            airport["id"], b2, sp["id"], aircraft_registration="N501",
        )
        # B2 is the reporter AND non-senior AND the report is still DRAFT.
        res = api.confirm_strike_report(
            strike["id"], {"confirmation_notes": "should fail"}, b2h,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_confirm_under_review_high_risk_by_nonsenior_returns_senior_required(self, api):
        """PRD §3.2: "Confirming the strike (`UNDER_REVIEW → CONFIRMED`)
        requires non-empty `confirmation_notes`, requires the acting biologist
        to be different from the reporter, and requires either that the acting
        biologist be senior or that the species' `risk_tier` be `LOW` or
        `MEDIUM`"
        PRD §2.9: "violations are rejected with `ERR_SENIOR_REQUIRED`
        (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_confirm
        """
        set_clock()
        airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
            icao_code="KIJW", cert_senior="CERT-803", cert_junior="CERT-804",
        )
        b3 = create_biologist(
            airport["id"], is_senior=False, full_name="B Three",
            certification_id="CERT-805",
        )
        sp = create_species(
            common_name="Golden Eagle", scientific_name="Aquila chrysaetos",
            guild="RAPTOR", risk_tier="HIGH", body_mass_g=4600,
            is_protected_federally=True,
        )
        strike = create_under_review_strike(
            airport["id"], b2, b1, sp["id"], aircraft_registration="N502",
        )
        # B3 is not the reporter (segregation passes) but is non-senior on a
        # HIGH risk-tier species.
        res = api.confirm_strike_report(
            strike["id"], {"confirmation_notes": "attempt"},
            make_biologist_headers(b3["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SENIOR_REQUIRED.value, expected_status=403)
