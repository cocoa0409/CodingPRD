"""Case opening, reference-BLL dual variant, priority classification, medical track.

Queue A: dual_variant_calc, boundary_precision_check, non_linear_state_machine.
Queue B: state_machines, calculations, validations.
"""
from test_helpers import (
    api_client, validate_success, validate_error, assert_case,
    create_dwelling_payload, create_child_payload, create_blood_lead_test_payload,
    create_case_payload, setup_case, record_blood_lead_test, TEST_USERS,
)

IC = TEST_USERS["intake_headers"]
PA = TEST_USERS["program_admin_headers"]
CM = TEST_USERS["case_manager_headers"]


# ─── dual_variant_calc / provisional_vs_confirmed_reference_bll ────────
def test_case_opens_with_provisional_capillary_reference(api):
    """PRD §3.2: "`reference_bll_ug_dl` is set verbatim to the qualifying test's
    `bll_ug_dl` — even if that qualifying test is a capillary screen — and
    `reference_basis` is set to `PROVISIONAL`."
    PRD §3.2: "`CLASS_I` when the reference is at least 45, otherwise `CLASS_II` when
    it is at least 20, otherwise `CLASS_III`."

    Design: Difficulty/dual_variant_calc/provisional_vs_confirmed_reference_bll
    """
    ctx = setup_case(income_tier="VERY_LOW", bll=46.0,
                     specimen_type="CAPILLARY", test_kind="SCREENING")
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["reference_basis"] == "PROVISIONAL"
    assert case["reference_bll_ug_dl"] == 46.0
    assert case["priority_class"] == "CLASS_I"


def test_venous_diagnostic_switches_reference_to_confirmed(api):
    """PRD §3.2: "the system considers all of that child's blood-lead tests whose
    `specimen_type` is `VENOUS` and whose `test_kind` is either `SCREENING` or
    `DIAGNOSTIC`, takes the maximum `bll_ug_dl` among them, sets `reference_bll_ug_dl`
    to that maximum, and sets `reference_basis` to `CONFIRMED`."
    PRD §3.2: "`CLASS_I` when the reference is at least 45, otherwise `CLASS_II` when
    it is at least 20, otherwise `CLASS_III`."

    Design: Difficulty/dual_variant_calc/provisional_vs_confirmed_reference_bll
    """
    ctx = setup_case(income_tier="VERY_LOW", bll=46.0,
                     specimen_type="CAPILLARY", test_kind="SCREENING")
    record_blood_lead_test(ctx["ch_id"], bll_ug_dl=30.0, specimen_type="VENOUS",
                           test_kind="DIAGNOSTIC", collected_at="2026-05-04T10:00:00Z")
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["reference_basis"] == "CONFIRMED"
    assert case["reference_bll_ug_dl"] == 30.0
    assert case["priority_class"] == "CLASS_II"


# ─── boundary_precision_check / bll_case_open_threshold_boundary ───────
def test_case_open_below_bll_threshold_rejected(api):
    """PRD §3.2: "the qualifying test's `bll_ug_dl` must be at least the case-opening
    threshold of 3.5 micrograms per deciliter, and a level below that is rejected with
    `ERR_BLL_BELOW_THRESHOLD` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/bll_case_open_threshold_boundary
    """
    d = validate_success(api_client.create_dwelling(create_dwelling_payload(), PA), 201)
    child = validate_success(api_client.create_child(create_child_payload(d["id"]), IC), 201)
    test = validate_success(api_client.create_blood_lead_test(
        create_blood_lead_test_payload(child["id"], bll_ug_dl=3.4,
                                        specimen_type="CAPILLARY", test_kind="SCREENING"), IC), 201)
    res = api_client.create_case(create_case_payload(child["id"], d["id"], test["id"]), IC)
    validate_error(res, "ERR_BLL_BELOW_THRESHOLD")


def test_case_open_exactly_at_bll_threshold_opens_class_iii(api):
    """PRD §3.2: "the qualifying test's `bll_ug_dl` must be at least the case-opening
    threshold of 3.5 micrograms per deciliter".
    PRD §3.2: "Because the case can only exist when the reference is at least the 3.5
    threshold, the `CLASS_III` band is the floor. The comparison is made on the
    one-decimal reference value, and each boundary is an inclusive lower bound."

    Design: Difficulty/boundary_precision_check/bll_case_open_threshold_boundary
    """
    d = validate_success(api_client.create_dwelling(create_dwelling_payload(), PA), 201)
    child = validate_success(api_client.create_child(create_child_payload(d["id"]), IC), 201)
    test = validate_success(api_client.create_blood_lead_test(
        create_blood_lead_test_payload(child["id"], bll_ug_dl=3.5,
                                        specimen_type="CAPILLARY", test_kind="SCREENING"), IC), 201)
    case = validate_success(
        api_client.create_case(create_case_payload(child["id"], d["id"], test["id"]), IC), 201)
    assert case["reference_bll_ug_dl"] == 3.5
    assert case["priority_class"] == "CLASS_III"


# ─── non_linear_state_machine / case_parallel_axes_independent ─────────
def test_first_followup_advances_medical_only(api):
    """PRD §3.3: "The medical track lives on `medical_status` and evolves independently
    of the environmental `case_status`."
    PRD §3.3: "When a venous follow-up comes back below 3.5 for a case currently
    `ELEVATED`, `medical_status` advances to `MONITORING` — the first sub-threshold
    reading."
    PRD §3.4: "the first investigation scheduled for an `OPEN` case advances its
    `case_status` to `INVESTIGATION`."

    Design: Difficulty/non_linear_state_machine/case_parallel_axes_independent
    """
    from test_helpers import build_remediation_scenario
    ctx = build_remediation_scenario(stage="investigation", income_tier="LOW", bll=22.0)
    record_blood_lead_test(ctx["ch_id"], bll_ug_dl=2.0, specimen_type="VENOUS",
                           test_kind="FOLLOWUP", collected_at="2026-06-01T10:00:00Z")
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["medical_status"] == "MONITORING"
    assert case["case_status"] == "INVESTIGATION"


def test_second_followup_resolves_medical_case_status_unchanged(api):
    """PRD §3.3: "A second consecutive venous follow-up below 3.5 while the case is
    `MONITORING` advances it to `RESOLVED`."
    PRD §3.3: "The medical track lives on `medical_status` and evolves independently
    of the environmental `case_status`."

    Design: Difficulty/non_linear_state_machine/case_parallel_axes_independent
    """
    from test_helpers import build_remediation_scenario
    ctx = build_remediation_scenario(stage="investigation", income_tier="LOW", bll=22.0)
    record_blood_lead_test(ctx["ch_id"], bll_ug_dl=2.0, specimen_type="VENOUS",
                           test_kind="FOLLOWUP", collected_at="2026-06-01T10:00:00Z")
    record_blood_lead_test(ctx["ch_id"], bll_ug_dl=1.5, specimen_type="VENOUS",
                           test_kind="FOLLOWUP", collected_at="2026-07-01T10:00:00Z")
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["medical_status"] == "RESOLVED"
    assert case["case_status"] == "INVESTIGATION"


# ─── Corner: state_machines / case_initial_states_open_and_elevated ────
def test_case_initial_states_open_elevated_provisional(api):
    """PRD §3.2: "On success the case is created with `case_status` set to `OPEN` and
    `medical_status` set to `ELEVATED`."
    PRD §3.2: "`reference_bll_ug_dl` is set verbatim to the qualifying test's
    `bll_ug_dl` — even if that qualifying test is a capillary screen — and
    `reference_basis` is set to `PROVISIONAL`."

    Design: Corner/state_machines/case_initial_states_open_and_elevated
    """
    ctx = setup_case(income_tier="LOW", bll=22.0, specimen_type="VENOUS", test_kind="DIAGNOSTIC")
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert_case(case)
    assert case["case_status"] == "OPEN"
    assert case["medical_status"] == "ELEVATED"
    assert case["reference_basis"] == "PROVISIONAL"
    assert case["priority_class"] == "CLASS_II"


# ─── Corner: calculations / priority_class_i_boundary_at_45 ────────────
def test_priority_class_i_at_reference_45(api):
    """PRD §3.2: "`priority_class` is recomputed from it: `CLASS_I` when the reference
    is at least 45, otherwise `CLASS_II` when it is at least 20, otherwise `CLASS_III`."
    PRD §3.2: "The comparison is made on the one-decimal reference value, and each
    boundary is an inclusive lower bound."

    Design: Corner/calculations/priority_class_i_boundary_at_45
    """
    ctx = setup_case(income_tier="LOW", bll=45.0, specimen_type="VENOUS", test_kind="DIAGNOSTIC")
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["reference_bll_ug_dl"] == 45.0
    assert case["priority_class"] == "CLASS_I"


# ─── Corner: validations / case_qualifying_test_child_mismatch_rejected ─
def test_case_qualifying_test_child_mismatch_rejected(api):
    """PRD §3.2: "first, the qualifying test must belong to the same child, meaning its
    recorded child must equal the supplied `child_id`; a mismatch is rejected with
    `ERR_QUALIFYING_TEST_MISMATCH` (HTTP 422)."

    Design: Corner/validations/case_qualifying_test_child_mismatch_rejected
    """
    d = validate_success(api_client.create_dwelling(create_dwelling_payload(), PA), 201)
    child_a = validate_success(api_client.create_child(create_child_payload(d["id"]), IC), 201)
    child_b = validate_success(api_client.create_child(create_child_payload(d["id"]), IC), 201)
    test_b = validate_success(api_client.create_blood_lead_test(
        create_blood_lead_test_payload(child_b["id"], bll_ug_dl=30.0), IC), 201)
    res = api_client.create_case(create_case_payload(child_a["id"], d["id"], test_b["id"]), IC)
    validate_error(res, "ERR_QUALIFYING_TEST_MISMATCH")


# ─── Corner: validations / case_open_nonexistent_child_returns_not_found ─
def test_case_open_nonexistent_child_returns_not_found(api):
    """PRD §2.8: "every path `id` and every foreign-key target in the body resolves to
    an existing resource, checked left to right in the order they appear; the first
    unresolved reference yields the matching `ERR_<RESOURCE>_NOT_FOUND` (404)."

    Design: Corner/validations/case_open_nonexistent_child_returns_not_found
    """
    res = api_client.create_case(create_case_payload(
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
        "00000000-0000-4000-8000-000000000003",
    ), IC)
    validate_error(res, "ERR_CHILD_NOT_FOUND")
