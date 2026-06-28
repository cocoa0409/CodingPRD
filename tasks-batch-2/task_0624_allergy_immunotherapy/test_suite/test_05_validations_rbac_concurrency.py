"""Validations, priority conflicts, RBAC denials, and optimistic-concurrency
guards on the immunotherapy plan.

Each test translates exactly one design-index instance (see the Design: line).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    create_patient_payload,
    create_panel_payload,
    create_plan_payload,
    create_lot_payload,
    mix_vial_payload,
    administer_shot_payload,
    create_patient,
    create_open_panel,
    add_skin_test,
    finalize_panel,
    create_draft_plan,
    create_red_active_plan,
    create_lot,
    mix_vial,
    administer_shot,
    get_plan,
    create_held_plan_via_systemic,
    TEST_USERS,
    build_user_headers,
)

ALLERGIST = TEST_USERS["allergist_headers"]
PHARMACIST = TEST_USERS["pharmacist_headers"]
NURSE = TEST_USERS["nurse_headers"]
BILLER = TEST_USERS["biller_headers"]
FRONTDESK = TEST_USERS["frontdesk_headers"]


def test_epinephrine_safety_beats_insufficient_volume(api):
    """PRD §3.6: "Finally, if the vial's color is `SILVER` — the maintenance
    concentration — the patient's `epinephrine_on_file` must be true, or the
    request is rejected with `ERR_EPINEPHRINE_NOT_ON_FILE`." PRD §3.6: "The
    vial's `remaining_volume_ml` must be at least the scheduled draw volume; if
    the scheduled draw exceeds what remains, the request is rejected with
    `ERR_VIAL_INSUFFICIENT_VOLUME`".

    A SILVER draw on a patient without epinephrine on file AND below the
    scheduled draw volume violates both; the safety error
    ERR_EPINEPHRINE_NOT_ON_FILE is returned.

    Design: Difficulty/priority_pair_validation_conflict/epinephrine_safety_beats_insufficient_volume_fiscal
    """
    patient = create_patient(epinephrine_on_file=False)
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="Severe")
    add_skin_test(patient["id"], panel["id"], wheal_mm=10, clinically_relevant=True, allergen_code="OAK")
    panel = finalize_panel(patient["id"], panel["id"])
    plan = validate_success(api.create_plan(create_plan_payload(patient["id"], panel["id"]), ALLERGIST), 201)
    assert plan["starting_vial_color"] == "GREEN", plan["starting_vial_color"]

    green_lot = create_lot("GREEN")
    green_vial = mix_vial(plan["id"], green_lot["id"], plan["version"], prepared_volume_ml=5.0)
    plan_now = get_plan(plan["id"])
    sil_lot = create_lot("SILVER")
    sil_vial = mix_vial(plan["id"], sil_lot["id"], plan_now["version"], prepared_volume_ml=0.05)
    activated = validate_success(api.activate_plan(plan["id"], ALLERGIST), 200)

    res = api.administer_shot(
        plan["id"], administer_shot_payload(sil_vial["id"], activated["version"]), NURSE
    )
    validate_error(res, "ERR_EPINEPHRINE_NOT_ON_FILE", expected_status=422)


def test_held_plan_state_beats_temporal_on_shot(api):
    """PRD §3.7: "while a plan is `HELD`, no new shot visit may be administered,
    and an attempt to do so is rejected with `ERR_PLAN_HELD`." PRD §3.6: "a held
    plan specifically with `ERR_PLAN_HELD`."

    Administering on a HELD plan returns the state error ERR_PLAN_HELD.

    Design: Difficulty/priority_pair_validation_conflict/state_held_beats_observation_temporal
    """
    ctx = create_held_plan_via_systemic(prepared_volume_ml=5.0)
    res = api.administer_shot(
        ctx["plan"]["id"], administer_shot_payload(ctx["vial"]["id"], ctx["held_version"]), NURSE
    )
    validate_error(res, "ERR_PLAN_HELD", expected_status=409)


def test_skin_test_carrying_ige_value_rejected(api):
    """PRD §3.2: "a `SKIN` test must carry `wheal_mm` ... and must not carry
    `specific_ige_ku` ... A test that supplies the wrong measurement for its
    method, or omits the required one, is rejected with
    `ERR_TEST_METHOD_MISMATCH`."

    Design: Corner/validations/skin_test_with_ige_value_returns_method_mismatch
    """
    patient = create_patient()
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="Mismatch")
    res = api.add_test(
        patient["id"], panel["id"],
        {"allergen_code": "DUST", "method": "SKIN", "specific_ige_ku": 12, "clinically_relevant": True},
        ALLERGIST,
    )
    validate_error(res, "ERR_TEST_METHOD_MISMATCH", expected_status=422)


def test_duplicate_lot_number_rejected(api):
    """PRD §3.4: "The `lot_number` must be unique among all lots that are not
    recalled; registering a lot whose number collides with an existing
    non-recalled lot is rejected with `ERR_DUPLICATE_LOT_NUMBER`."

    Design: Corner/validations/duplicate_lot_number_returns_conflict
    """
    validate_success(
        api.create_lot(create_lot_payload("RED", "RED-DUP-UNIQUE"), PHARMACIST), 201
    )
    res = api.create_lot(create_lot_payload("RED", "RED-DUP-UNIQUE"), PHARMACIST)
    validate_error(res, "ERR_DUPLICATE_LOT_NUMBER", expected_status=409)


def test_vial_from_other_plan_rejected(api):
    """PRD §3.6: "The referenced vial must belong to the same plan named in the
    path, or the request is rejected with `ERR_VIAL_PLAN_MISMATCH`."

    A shot on plan A using plan B's vial returns ERR_VIAL_PLAN_MISMATCH.

    Design: Corner/validations/vial_plan_mismatch_returns_error
    """
    ctx_a = create_red_active_plan(prepared_volume_ml=5.0)
    ctx_b = create_red_active_plan(prepared_volume_ml=5.0)
    res = api.administer_shot(
        ctx_a["plan"]["id"],
        administer_shot_payload(ctx_b["vial"]["id"], ctx_a["version"]),
        NURSE,
    )
    validate_error(res, "ERR_VIAL_PLAN_MISMATCH", expected_status=422)


def test_open_panel_for_inactive_patient_rejected(api):
    """PRD §3.1: "An `INACTIVE` patient may not have new panels, plans, or shot
    visits created against them; any such attempt is rejected with
    `ERR_PATIENT_INACTIVE`." PRD §3.2: "A panel may not be opened for an
    `INACTIVE` patient."

    Design: Corner/validations/new_panel_against_inactive_patient_rejected
    """
    patient = create_patient()
    validate_success(api.update_patient(patient["id"], {"status": "INACTIVE"}, FRONTDESK), 200)
    res = api.create_panel(patient["id"], create_panel_payload(panel_name="Blocked"), ALLERGIST)
    validate_error(res, "ERR_PATIENT_INACTIVE", expected_status=422)


def test_insufficient_volume_returns_fiscal_error(api):
    """PRD §3.6: "The vial's `remaining_volume_ml` must be at least the scheduled
    draw volume; if the scheduled draw exceeds what remains, the request is
    rejected with `ERR_VIAL_INSUFFICIENT_VOLUME`".

    A RED-start shot scheduled 0.10 mL against a RED vial prepared with only 0.05
    mL (patient has epinephrine on file, so no safety rule fires) returns
    ERR_VIAL_INSUFFICIENT_VOLUME.

    Design: Corner/validations/insufficient_volume_returns_fiscal_error
    """
    ctx = create_red_active_plan(prepared_volume_ml=0.05)
    res = api.administer_shot(
        ctx["plan"]["id"], administer_shot_payload(ctx["vial"]["id"], ctx["version"]), NURSE
    )
    validate_error(res, "ERR_VIAL_INSUFFICIENT_VOLUME", expected_status=422)


def test_systemic_reaction_without_epinephrine_rejected(api):
    """PRD §3.6: "the grade must be `SYSTEMIC` (otherwise
    `ERR_REACTION_GRADE_MISMATCH`), and `epinephrine_administered` must be true
    (otherwise `ERR_EPINEPHRINE_REQUIRED`)."

    Design: Corner/validations/epinephrine_required_on_systemic_reaction
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    visit = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    res = api.record_reaction(
        visit["id"], {"reaction_grade": "SYSTEMIC", "epinephrine_administered": False}, NURSE
    )
    validate_error(res, "ERR_EPINEPHRINE_REQUIRED", expected_status=422)


def test_nurse_cannot_finalize_panel(api):
    """PRD §4: the finalize-panel endpoint is authorized for Allergist only.
    PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/nurse_cannot_finalize_panel_forbidden
    """
    patient = create_patient()
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="Rbac")
    add_skin_test(patient["id"], panel["id"], wheal_mm=7, clinically_relevant=True, allergen_code="OAK")
    res = api.finalize_panel(patient["id"], panel["id"], NURSE)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_biller_cannot_mix_vial(api):
    """PRD §4: the mix-vial endpoint is authorized for Pharmacist only. PRD §2.1:
    "When the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/biller_cannot_mix_vial_forbidden
    """
    patient, panel, plan = create_draft_plan()
    lot = create_lot("RED")
    res = api.mix_vial(
        plan["id"], mix_vial_payload(lot["id"], plan["version"], prepared_volume_ml=5.0), BILLER
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value
    for either, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    res = api.list_patients(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_stale_plan_version_on_second_vial_mix_rejected(api):
    """PRD §2.6: "When the pharmacist mixes a new serum vial onto a plan, the
    request must carry `expected_plan_version` matching the target plan's current
    `version`. If the plan's `version` has advanced since the client last read it
    — because a prior vial mix advanced the ladder color ... — the create is
    rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412)".

    First mix succeeds and bumps the version; a second mix carrying the original
    (now stale) version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_on_vial_mix
    """
    patient, panel, plan = create_draft_plan()
    v0 = plan["version"]
    lot = create_lot("RED")
    mix_vial(plan["id"], lot["id"], v0, prepared_volume_ml=5.0)
    res = api.mix_vial(
        plan["id"], mix_vial_payload(lot["id"], v0, prepared_volume_ml=5.0), PHARMACIST
    )
    validate_error(res, "ERR_STALE_PLAN_VERSION", expected_status=412)


def test_stale_plan_version_on_second_shot_visit_rejected(api):
    """PRD §2.6: "when the nurse administers a shot visit on a plan, the request
    must carry `expected_plan_version` matching the plan's current `version`. If
    the plan's `version` has moved since the nurse last read it — because a prior
    visit released and advanced the ladder ... — the administration is rejected
    with `ERR_STALE_PLAN_VERSION` (HTTP 412)".

    The first shot bumps the plan version; a second shot carrying the pre-shot
    version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_on_shot_visit
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    v2 = ctx["version"]
    administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], v2)
    res = api.administer_shot(
        ctx["plan"]["id"], administer_shot_payload(ctx["vial"]["id"], v2), NURSE
    )
    validate_error(res, "ERR_STALE_PLAN_VERSION", expected_status=412)
