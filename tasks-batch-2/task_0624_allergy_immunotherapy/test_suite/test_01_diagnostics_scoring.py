"""Diagnostic panel scoring: per-test sensitization index, screening vs clinical
composites, IgE class boundaries, control-wheal default, immediate consistency.

Each test translates exactly one design-index instance (see the Design: line).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    create_patient_payload,
    create_panel_payload,
    create_skin_test_payload,
    create_blood_test_payload,
    create_patient,
    create_open_panel,
    add_skin_test,
    add_blood_test,
    TEST_USERS,
)

ALLERGIST = TEST_USERS["allergist_headers"]
FRONTDESK = TEST_USERS["frontdesk_headers"]


def test_screening_and_clinical_composite_diverge(api):
    """PRD §3.2: "The `screening_composite` is the mean of `sensitization_index`
    over all tests on the panel, rounded to two decimal places half-up. The
    `clinical_composite` is the mean of `sensitization_index` over only those
    tests whose `clinically_relevant` flag is true, rounded the same way".
    PRD §3.2: "a composite below 4 is `LOW`, a composite at least 4 but below 7
    is `MODERATE`, and a composite of 7 or more is `HIGH`."

    Three tests (SKIN wheal 8 relevant -> index 5, BLOOD IgE 18 relevant ->
    class 4, SKIN wheal 5 not relevant -> index 2): screening mean = (5+4+2)/3 =
    3.67, clinical mean = (5+4)/2 = 4.50, tier MODERATE from the clinical 4.50.

    Design: Difficulty/dual_variant_calc/panel_screening_vs_clinical_composite_diverge
    """
    patient = create_patient(epinephrine_on_file=True)
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="NE Tree+Grass")
    add_skin_test(patient["id"], panel["id"], wheal_mm=8, clinically_relevant=True, allergen_code="OAK")
    add_blood_test(patient["id"], panel["id"], specific_ige_ku=18, clinically_relevant=True, allergen_code="D_FARINAE")
    add_skin_test(patient["id"], panel["id"], wheal_mm=5, clinically_relevant=False, allergen_code="TIMOTHY")

    fetched = validate_success(api.get_panel(panel["id"], ALLERGIST), 200)
    assert fetched["screening_composite"] == 3.67, fetched["screening_composite"]
    assert fetched["clinical_composite"] == 4.5, fetched["clinical_composite"]
    assert fetched["recommended_tier"] == "MODERATE", fetched["recommended_tier"]


def test_panel_composite_branches_on_method_and_relevance(api):
    """PRD §3.2: "For a `SKIN` test ... the test's `sensitization_index` is the
    greater of zero and that difference". PRD §3.2: "The blood test's
    `sensitization_index` is that IgE class". PRD §3.2: "The `clinical_composite`
    is the mean of `sensitization_index` over only those tests whose
    `clinically_relevant` flag is true".

    SKIN wheal 8 (control 3) -> index 5; BLOOD IgE 18 -> class 4; SKIN wheal 5 ->
    index 2 (not relevant, excluded). Clinical composite = (5+4)/2 = 4.5.

    Design: Difficulty/combinatorial_formula/panel_composite_nonlinear_inclusion_branch
    """
    patient = create_patient(epinephrine_on_file=False)
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="Mixed")
    t1 = add_skin_test(patient["id"], panel["id"], wheal_mm=8, clinically_relevant=True, allergen_code="OAK")
    t2 = add_blood_test(patient["id"], panel["id"], specific_ige_ku=18, clinically_relevant=True, allergen_code="DUST")
    t3 = add_skin_test(patient["id"], panel["id"], wheal_mm=5, clinically_relevant=False, allergen_code="TIMOTHY")

    assert t1["sensitization_index"] == 5, t1["sensitization_index"]
    assert t2["sensitization_index"] == 4, t2["sensitization_index"]
    assert t3["sensitization_index"] == 2, t3["sensitization_index"]

    fetched = validate_success(api.get_panel(panel["id"], ALLERGIST), 200)
    assert fetched["clinical_composite"] == 4.5, fetched["clinical_composite"]


def test_blood_class_below_first_boundary_is_zero_and_negative(api):
    """PRD §3.2: "a value below 0.35 is class 0". PRD §3.2: "it `is_positive` when
    the class is at least 1, equivalently when `specific_ige_ku` is at least 0.35."

    IgE 0.34 kU/L < 0.35 -> class 0 -> sensitization_index 0, is_positive false.

    Design: Corner/entities/allergen_test_blood_class_boundary_zero_negative
    """
    patient = create_patient()
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="BloodEdge")
    test = add_blood_test(patient["id"], panel["id"], specific_ige_ku=0.34, clinically_relevant=True)
    assert test["sensitization_index"] == 0, test["sensitization_index"]
    assert test["is_positive"] is False, test["is_positive"]


def test_ige_class_at_3point5_boundary_is_class_three(api):
    """PRD §3.2: "at least 0.70 but below 3.5 is class 2, at least 3.5 but below
    17.5 is class 3". The blood test's sensitization_index is that IgE class.

    IgE exactly 3.5 kU/L is at the >= 3.5 boundary -> class 3 -> index 3.

    Design: Corner/calculations/ige_class_boundary_at_3point5_is_class_3
    """
    patient = create_patient()
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="ClassEdge")
    test = add_blood_test(patient["id"], panel["id"], specific_ige_ku=3.5, clinically_relevant=True)
    assert test["sensitization_index"] == 3, test["sensitization_index"]


def test_control_wheal_default_applied_when_omitted(api):
    """PRD §3.2: "When `control_wheal_mm` is omitted it defaults to 3." PRD §3.2:
    "For a `SKIN` test the system first computes the difference between `wheal_mm`
    and the panel's `control_wheal_mm`; the test's `sensitization_index` is the
    greater of zero and that difference".

    A panel created without control_wheal_mm reads 3; a SKIN wheal 6 then scores
    index 3 (6 - 3).

    Design: Corner/entities/panel_control_wheal_default_applied
    """
    patient = create_patient()
    panel = validate_success(
        api.create_panel(patient["id"], create_panel_payload(panel_name="DefaultCtrl"), ALLERGIST),
        201,
    )
    assert panel["control_wheal_mm"] == 3, panel["control_wheal_mm"]
    test = add_skin_test(patient["id"], panel["id"], wheal_mm=6, clinically_relevant=True, allergen_code="CAT")
    assert test["sensitization_index"] == 3, test["sensitization_index"]


def test_composites_visible_immediately_after_adding_test(api):
    """PRD §3.2: "Every test is scored on creation, and the panel's composites
    are recomputed at the same time." PRD §3.2: "if the panel has no
    clinically-relevant test, the `clinical_composite` is 0."

    Adding a SKIN wheal 6 (index 3, relevant) makes both composites read 3.0 on
    the panel read issued immediately afterward.

    Design: Corner/consistency_model/immediate_consistency_composites_visible_on_create
    """
    patient = create_patient()
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="Imm")
    add_skin_test(patient["id"], panel["id"], wheal_mm=6, clinically_relevant=True)
    fetched = validate_success(api.get_panel(panel["id"], ALLERGIST), 200)
    assert fetched["clinical_composite"] == 3.0, fetched["clinical_composite"]
    assert fetched["screening_composite"] == 3.0, fetched["screening_composite"]


def test_create_patient_returns_201_with_system_fields(api):
    """PRD §3.1: "The `status` field is an enum that is either `ACTIVE` or
    `INACTIVE`, beginning at `ACTIVE` on registration." PRD §3.1: "Registration
    may optionally declare `epinephrine_on_file`, a boolean recording whether the
    patient has a documented epinephrine auto-injector; when omitted it defaults
    to false." PRD §2.4: "`version` is an integer that begins at its initial
    value when the resource is created".

    Design: Corner/entities/create_patient_returns_201_with_system_fields
    """
    res = api.create_patient(
        create_patient_payload(full_name="Ada Vale", date_of_birth="1990-01-01"), FRONTDESK
    )
    patient = validate_success(res, 201)
    assert patient["status"] == "ACTIVE", patient["status"]
    assert patient["epinephrine_on_file"] is False, patient["epinephrine_on_file"]
    assert patient["version"] == 1, patient["version"]


def test_get_patient_not_found_returns_404(api):
    """PRD §2.5: "A request is rejected as soon as the first identifier in the
    path fails to resolve to an existing resource, returning `ERR_NOT_FOUND` for
    that identifier."

    Design: Corner/entities/get_patient_not_found_returns_404
    """
    from test_helpers import validate_error
    res = api.get_patient("00000000-0000-4000-8000-000000000000", FRONTDESK)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_panel_missing_panel_name_returns_400(api):
    """PRD §2.3 / §2.2 contract: required body fields must be present.
    PRD §3.2: "An `Allergist` opens a diagnostic panel for a patient by supplying
    a free-text `panel_name`". PRD §5 maps `ERR_INVALID_REQUEST` to 400 for a
    missing body field.

    Design: Corner/entities/create_panel_missing_required_field_returns_400
    """
    from test_helpers import validate_error
    patient = create_patient()
    res = api.create_panel(patient["id"], {"control_wheal_mm": 3}, ALLERGIST)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_list_patients_pagination_envelope(api):
    """PRD §2.3: "Every list response carries, inside the `meta` object of the
    envelope, the four pagination fields `limit`, `offset`, `total_count`, and
    `has_more`. `total_count` is the count of all items matching the query before
    pagination is applied, and `has_more` is true when items remain beyond the
    current page."

    Design: Corner/entities/list_patients_pagination_envelope
    """
    from test_helpers import validate_paginated
    create_patient(full_name="Eve Abel", date_of_birth="1990-01-01")
    create_patient(full_name="Fox Buhl", date_of_birth="1990-01-02")
    data, meta = validate_paginated(api.list_patients(FRONTDESK, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]
    assert len(data) == 1, len(data)
