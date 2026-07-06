"""Eligibility adjudication and entitlement scoring.

Covers difficulty rules dual_variant_calc and combinatorial_formula (entitlement),
plus corner calculations/entities instances for eligibility outcomes and scoring.
"""
from test_helpers import (
    TEST_USERS,
    validate_success,
    get_success_data,
    setup_cemetery_with_gravesite,
    create_cemetery,
    open_case,
)

OFFICER = TEST_USERS["eligibility_officer_headers"]


# ===========================================================================
# dual_variant_calc — entitlement_score own vs sponsor-derived
# ===========================================================================
def test_entitlement_score_veteran_uses_own_service(api):
    """PRD §3.3: "For a veteran case every term reads the case's own fields."
    PRD §3.3: "A service bonus is then computed from whole years of service: take
    the service_days, divide by 365 and take the floor to get completed years,
    multiply by 3 points per year, and cap the result at 30 points"

    Design: Difficulty/dual_variant_calc/entitlement_score_own_vs_sponsor_derived
    """
    cem = create_cemetery(name="Riverside National", honors_squad_capacity=2)
    vet = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "character_of_discharge": "HONORABLE",
        "service_days": 3650, "died_on_active_duty": False,
    }, OFFICER))
    api.run_eligibility(cem["id"], vet["id"], OFFICER)
    vet_read = validate_success(api.get_burial_case(cem["id"], vet["id"], OFFICER))
    # base 100 + min(floor(3650/365)*3,30)=30 + honorable 10 = 140
    assert vet_read["entitlement_score"] == 140, \
        f"veteran own-service score expected 140, got {vet_read['entitlement_score']}"


def test_entitlement_score_dependent_derived_from_sponsor(api):
    """PRD §3.3: "For a spouse or dependent case the score is derived from the
    sponsor: the base term still uses the dependent's own role weight (60 or 40),
    but the service-bonus, death-in-service, and discharge terms all read the
    sponsor case's service_days, died_on_active_duty, and character_of_discharge
    rather than the dependent's own."

    Design: Difficulty/dual_variant_calc/entitlement_score_own_vs_sponsor_derived
    """
    cem = create_cemetery(name="Riverside National", honors_squad_capacity=2)
    vet = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "character_of_discharge": "HONORABLE",
        "service_days": 3650, "died_on_active_duty": False,
    }, OFFICER))
    api.run_eligibility(cem["id"], vet["id"], OFFICER)
    dep = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "DEPENDENT",
        "requested_class": "STANDARD", "reserving_case_id": vet["id"], "service_days": 0,
    }, OFFICER))
    api.run_eligibility(cem["id"], dep["id"], OFFICER)
    dep_read = validate_success(api.get_burial_case(cem["id"], dep["id"], OFFICER))
    vet_read = validate_success(api.get_burial_case(cem["id"], vet["id"], OFFICER))
    # dependent base 40 + sponsor service 30 + sponsor honorable 10 = 80
    assert dep_read["entitlement_score"] == 80, \
        f"dependent sponsor-derived score expected 80, got {dep_read['entitlement_score']}"
    assert dep_read["entitlement_score"] != vet_read["entitlement_score"]


# ===========================================================================
# dual_variant_calc — eligibility decision veteran-direct vs derived-dependent
# ===========================================================================
def test_veteran_other_than_honorable_denied_discharge_bar(api):
    """PRD §3.2: "if character_of_discharge is either OTHER_THAN_HONORABLE or
    DISHONORABLE, the case is denied with denial_reason of DISCHARGE_BAR"

    Design: Difficulty/dual_variant_calc/eligibility_decision_veteran_direct_vs_derived_dependent
    """
    cem = create_cemetery(name="Cardinal National", honors_squad_capacity=1)
    vet = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "character_of_discharge": "OTHER_THAN_HONORABLE",
        "service_days": 3650,
    }, OFFICER))
    det = validate_success(api.run_eligibility(cem["id"], vet["id"], OFFICER), expected_status=201)
    assert det["decision"] == "DENIED"
    assert det["denial_reason"] == "DISCHARGE_BAR"
    case_read = validate_success(api.get_burial_case(cem["id"], vet["id"], OFFICER))
    assert case_read["status"] == "INELIGIBLE"


def test_dependent_of_ineligible_sponsor_denied_sponsor_not_eligible(api):
    """PRD §3.2: "the sponsor is the case named by reserving_case_id, and if that
    sponsor is absent or its status is not one of ELIGIBLE, ASSIGNED, SCHEDULED,
    or INTERRED, the case is denied with denial_reason of SPONSOR_NOT_ELIGIBLE"

    Design: Difficulty/dual_variant_calc/eligibility_decision_veteran_direct_vs_derived_dependent
    """
    cem = create_cemetery(name="Cardinal National", honors_squad_capacity=1)
    vet = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "character_of_discharge": "OTHER_THAN_HONORABLE",
        "service_days": 3650,
    }, OFFICER))
    api.run_eligibility(cem["id"], vet["id"], OFFICER)  # sponsor -> INELIGIBLE
    dep = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "DEPENDENT",
        "requested_class": "STANDARD", "reserving_case_id": vet["id"],
        "character_of_discharge": "HONORABLE", "service_days": 5000,
    }, OFFICER))
    det = validate_success(api.run_eligibility(cem["id"], dep["id"], OFFICER), expected_status=201)
    assert det["decision"] == "DENIED"
    assert det["denial_reason"] == "SPONSOR_NOT_ELIGIBLE"
    dep_read = validate_success(api.get_burial_case(cem["id"], dep["id"], OFFICER))
    assert dep_read["status"] == "INELIGIBLE"


# ===========================================================================
# combinatorial_formula — entitlement score non-linear capped multi-term
# ===========================================================================
def test_entitlement_score_died_in_service_capped_multiterm(api):
    """PRD §3.3: "A death-in-service term adds 25 points when died_on_active_duty
    is true and nothing otherwise."
    PRD §3.3: "A service bonus is then computed from whole years of service: take
    the service_days, divide by 365 and take the floor to get completed years,
    multiply by 3 points per year, and cap the result at 30 points"

    Design: Difficulty/combinatorial_formula/entitlement_score_nonlinear_capped_multiterm
    """
    cem = create_cemetery(name="Freedom National", honors_squad_capacity=1)
    case = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "character_of_discharge": "GENERAL",
        "service_days": 400, "died_on_active_duty": True,
    }, OFFICER))
    det = validate_success(api.run_eligibility(cem["id"], case["id"], OFFICER), expected_status=201)
    assert det["basis"] == "DIED_IN_SERVICE"
    read = validate_success(api.get_burial_case(cem["id"], case["id"], OFFICER))
    assert read["status"] == "ELIGIBLE"
    # base 100 + min(floor(400/365)*3,30)=3 + died 25 + GENERAL(no honorable bonus)=0 = 128
    assert read["entitlement_score"] == 128, \
        f"expected non-linear capped score 128, got {read['entitlement_score']}"


def test_entitlement_score_clamped_to_ceiling(api):
    """PRD §3.3: "The four terms are summed, and the total is then clamped so that
    the final entitlement_score is the smaller of that sum and a ceiling of 150."

    Design: Difficulty/combinatorial_formula/entitlement_score_nonlinear_capped_multiterm
    """
    cem = create_cemetery(name="Ceiling National", honors_squad_capacity=1)
    # base 100 + service cap 30 + died 25 + honorable 10 = 165 -> clamp to 150
    case = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "character_of_discharge": "HONORABLE",
        "service_days": 3650, "died_on_active_duty": True,
    }, OFFICER))
    api.run_eligibility(cem["id"], case["id"], OFFICER)
    read = validate_success(api.get_burial_case(cem["id"], case["id"], OFFICER))
    assert read["entitlement_score"] == 150, \
        f"expected clamped ceiling 150, got {read['entitlement_score']}"


# ===========================================================================
# Corner: calculations — eligibility outcomes
# ===========================================================================
def test_insufficient_service_below_min_denied(api):
    """PRD §3.2: "if service_days is less than the minimum of 730 active-duty days,
    the case is denied with denial_reason of INSUFFICIENT_SERVICE"

    Design: Corner/calculations/eligibility_insufficient_service_denied
    """
    cem = create_cemetery(name="Service National", honors_squad_capacity=1)
    case = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "character_of_discharge": "HONORABLE",
        "service_days": 729,
    }, OFFICER))
    det = validate_success(api.run_eligibility(cem["id"], case["id"], OFFICER), expected_status=201)
    assert det["decision"] == "DENIED"
    assert det["denial_reason"] == "INSUFFICIENT_SERVICE"
    read = validate_success(api.get_burial_case(cem["id"], case["id"], OFFICER))
    assert read["status"] == "INELIGIBLE"


def test_overseas_case_at_us_cemetery_denied_mismatch(api):
    """PRD §3.2: "if the case's overseas designation does not equal its cemetery's
    overseas designation — that is, is_overseas_case differs from the cemetery's
    is_overseas — the case is denied with denial_reason of CEMETERY_MISMATCH"

    Design: Corner/calculations/overseas_case_at_us_cemetery_denied_cemetery_mismatch
    """
    cem = create_cemetery(name="Mismatch2 National", country_code="US", honors_squad_capacity=1)
    case = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "is_overseas_case": True,
        "character_of_discharge": "HONORABLE", "service_days": 3650,
    }, OFFICER))
    det = validate_success(api.run_eligibility(cem["id"], case["id"], OFFICER), expected_status=201)
    assert det["decision"] == "DENIED"
    assert det["denial_reason"] == "CEMETERY_MISMATCH"


def test_overseas_case_at_overseas_cemetery_basis_overseas_only(api):
    """PRD §3.2: "when a case that would otherwise be approved is both an overseas
    case and targets an overseas cemetery, its basis is set to OVERSEAS_ONLY in
    place of the basis the branch above would have assigned."

    Design: Corner/calculations/overseas_case_at_overseas_cemetery_basis_overseas_only
    """
    cem = create_cemetery(name="Manila American", country_code="PH", honors_squad_capacity=1)
    case = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "is_overseas_case": True,
        "character_of_discharge": "HONORABLE", "service_days": 3650,
    }, OFFICER))
    det = validate_success(api.run_eligibility(cem["id"], case["id"], OFFICER), expected_status=201)
    assert det["decision"] == "APPROVED"
    assert det["basis"] == "OVERSEAS_ONLY"
    read = validate_success(api.get_burial_case(cem["id"], case["id"], OFFICER))
    assert read["status"] == "ELIGIBLE"


# ===========================================================================
# Corner: entities — immutability & initial state & created cemetery
# ===========================================================================
def test_eligibility_determination_has_no_version(api):
    """PRD §2.4: "The EligibilityDetermination is an immutable audit record: it
    carries only an id and a created_at, and it has neither an updated_at nor a
    version field, because once written it is never modified."

    Design: Corner/entities/eligibility_determination_is_immutable_no_version
    """
    cem = create_cemetery(name="Immut National", honors_squad_capacity=1)
    case = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "character_of_discharge": "HONORABLE",
        "service_days": 3650,
    }, OFFICER))
    det = validate_success(api.run_eligibility(cem["id"], case["id"], OFFICER), expected_status=201)
    assert det["decision"] == "APPROVED"
    assert "version" not in det, "EligibilityDetermination must not carry a version field"
    assert "updated_at" not in det, "EligibilityDetermination must not carry an updated_at field"


def test_burial_case_starts_in_submitted(api):
    """PRD §3.2: "A freshly opened case starts in SUBMITTED."

    Design: Corner/state_machines/burial_case_starts_in_submitted
    """
    cem = create_cemetery(name="Init National", honors_squad_capacity=1)
    case = validate_success(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "character_of_discharge": "HONORABLE",
        "service_days": 3650,
    }, OFFICER), expected_status=201)
    assert case["status"] == "SUBMITTED"
