"""Laboratory purity analysis: banding, quality override, and segregation of
duties (PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    complete_fill_lot,
    create_test_fill_lot,
    create_test_plant,
    create_test_tank,
    get_cylinder,
    get_fill_lot,
    make_lab_analyst_headers,
    make_operator_headers,
    make_quality_manager_headers,
    setup_awaiting_analysis_lot,
    setup_planned_lot,
    start_fill_lot,
    validate_error,
    validate_success,
)

OP = TEST_USERS["production_operator_headers"]
LAB = TEST_USERS["lab_analyst_headers"]
QM = TEST_USERS["quality_manager_headers"]


# --- Corner: calculations / purity_marginal_band_then_override_releases ---

def test_marginal_band_at_one_and_half_limit_awaits_override(api):
    """PRD §3.4: "Each reading bands independently: a reading at or below its
    limit is OK, a reading above the limit but at or below one and a half times
    the limit is MARGINAL, and a reading above one and a half times the limit is
    FAIL — equality at the limit is OK, and equality at one-and-a-half-times the
    limit is MARGINAL."
    PRD §3.4: "for `O2`, carbon monoxide limited to 10 ppm and water to 20 ppm"
    PRD §3.4: "A `MARGINAL` result leaves the subject in `AWAITING_ANALYSIS`
    pending a quality decision."

    Design: Corner/calculations/purity_marginal_band_then_override_releases
    """
    ctx = setup_awaiting_analysis_lot(num_cylinders=1)
    lot = ctx["lot"]
    res = api.create_purity_analysis(
        {"subject_type": "FILL_LOT", "fill_lot_id": lot["id"],
         "readings": [{"analyte": "CO", "reading_ppm": 15}]},
        LAB,
    )
    analysis = validate_success(res, 201)
    assert analysis["result"] == "MARGINAL", "15 == 1.5 x the O2 CO limit of 10 ppm"
    assert analysis["status"] == "RECORDED"
    assert get_fill_lot(lot["id"])["status"] == "AWAITING_ANALYSIS", (
        "MARGINAL leaves the lot awaiting a quality decision"
    )


def test_override_releases_marginal_lot_as_pass_override(api):
    """PRD §3.4: "A successful override moves the analysis from `RECORDED` to
    `OVERRIDDEN` (its terminal state), rewrites the `result` to `PASS_OVERRIDE`,
    stamps `overridden_by_user_id`, releases the subject exactly as a `PASS`
    would — a waiting fill lot releases with its cylinders filled, a waiting
    blend order releases — and increments both the analysis's and the subject's
    `version`."

    Design: Corner/calculations/purity_marginal_band_then_override_releases
    """
    ctx = setup_awaiting_analysis_lot(num_cylinders=1)
    lot, cyl = ctx["lot"], ctx["cylinders"][0]
    analysis = validate_success(
        api.create_purity_analysis(
            {"subject_type": "FILL_LOT", "fill_lot_id": lot["id"],
             "readings": [{"analyte": "CO", "reading_ppm": 15}]},
            LAB,
        ),
        201,
    )
    overridden = validate_success(
        api.override_purity_analysis(analysis["id"], QM), 200
    )
    assert overridden["status"] == "OVERRIDDEN"
    assert overridden["result"] == "PASS_OVERRIDE"
    assert get_fill_lot(lot["id"])["status"] == "RELEASED"
    cyl_after = get_cylinder(cyl["id"])
    assert cyl_after["status"] == "FILLED"
    assert cyl_after["last_fill_lot_id"] == lot["id"]


# --- Corner: validations / analysis_on_planned_lot_rejected ---

def test_analysis_on_planned_lot_rejected(api):
    """PRD §3.4: "The subject must currently sit in `AWAITING_ANALYSIS`;
    analyzing anything else is rejected with `ERR_ANALYSIS_INVALID_STATE`."

    Design: Corner/validations/analysis_on_planned_lot_rejected
    """
    plant = create_test_plant(plant_name="P-VA5")
    tank = create_test_tank(plant["id"])
    lot = create_test_fill_lot(tank["id"])
    assert lot["status"] == "PLANNED"
    res = api.create_purity_analysis(
        {"subject_type": "FILL_LOT", "fill_lot_id": lot["id"],
         "readings": [{"analyte": "CO", "reading_ppm": 5}]},
        LAB,
    )
    validate_error(res, ApiErrorId.ERR_ANALYSIS_INVALID_STATE.value)
    assert get_fill_lot(lot["id"])["status"] == "PLANNED"


# --- Corner: rbac / segregation_filler_cannot_analyze_own_fill ---

def test_analyst_who_completed_fill_is_rejected(api):
    """PRD §3.4: "Segregation of duties is enforced by identity: the analyst's
    `X-User-ID`, stamped onto the analysis as `recorded_by_user_id`, must differ
    from the subject's `completed_by_user_id` on a fill lot or
    `blended_by_user_id` on a blend order, and a match is rejected with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Corner/rbac/segregation_filler_cannot_analyze_own_fill
    """
    filler = make_operator_headers("op-seg-1")
    ctx = setup_planned_lot(num_cylinders=1)
    lot, cyl = ctx["lot"], ctx["cylinders"][0]
    start_fill_lot(lot["id"], headers=filler)
    completed = complete_fill_lot(lot["id"], [cyl], headers=filler)
    assert completed["completed_by_user_id"] == "op-seg-1"

    res = api.create_purity_analysis(
        {"subject_type": "FILL_LOT", "fill_lot_id": lot["id"],
         "readings": [{"analyte": "CO", "reading_ppm": 5}]},
        make_lab_analyst_headers("op-seg-1"),
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value)


def test_distinct_analyst_records_and_releases(api):
    """PRD §3.4: "Segregation of duties is enforced by identity: the analyst's
    `X-User-ID`, stamped onto the analysis as `recorded_by_user_id`, must differ
    from the subject's `completed_by_user_id` on a fill lot or
    `blended_by_user_id` on a blend order, and a match is rejected with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."
    PRD §3.4: "A `PASS` releases the subject: a fill lot moves from
    `AWAITING_ANALYSIS` to `RELEASED`, and every cylinder reserved into it
    becomes `FILLED` with its `current_fill_lot_id` cleared and its
    `last_fill_lot_id` stamped with the lot's identity as permanent provenance"

    Design: Corner/rbac/segregation_filler_cannot_analyze_own_fill
    """
    ctx = setup_awaiting_analysis_lot(num_cylinders=1)
    lot = ctx["lot"]
    analysis = validate_success(
        api.create_purity_analysis(
            {"subject_type": "FILL_LOT", "fill_lot_id": lot["id"],
             "readings": [{"analyte": "CO", "reading_ppm": 5}]},
            make_lab_analyst_headers("lab-seg-1"),
        ),
        201,
    )
    assert analysis["result"] == "PASS"
    assert analysis["recorded_by_user_id"] == "lab-seg-1"
    assert get_fill_lot(lot["id"])["status"] == "RELEASED"


# --- Corner: rbac / override_actor_must_differ_from_recorder ---

def _setup_marginal_analysis():
    ctx = setup_awaiting_analysis_lot(num_cylinders=1)
    analysis = validate_success(
        api_client.create_purity_analysis(
            {"subject_type": "FILL_LOT", "fill_lot_id": ctx["lot"]["id"],
             "readings": [{"analyte": "CO", "reading_ppm": 15}]},
            make_lab_analyst_headers("lab-ovr-1"),
        ),
        201,
    )
    return ctx, analysis


def test_override_by_recorder_identity_rejected(api):
    """PRD §3.4: "The analysis must be in `RECORDED` status with a `result` of
    `MARGINAL` — anything else is rejected with `ERR_ANALYSIS_INVALID_STATE` —
    and the manager's identity must differ from the analysis's
    `recorded_by_user_id`, otherwise the override is rejected with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Corner/rbac/override_actor_must_differ_from_recorder
    """
    ctx, analysis = _setup_marginal_analysis()
    assert analysis["recorded_by_user_id"] == "lab-ovr-1"
    res = api.override_purity_analysis(
        analysis["id"], make_quality_manager_headers("lab-ovr-1")
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value)


def test_override_by_distinct_quality_manager_succeeds(api):
    """PRD §3.4: "The analysis must be in `RECORDED` status with a `result` of
    `MARGINAL` — anything else is rejected with `ERR_ANALYSIS_INVALID_STATE` —
    and the manager's identity must differ from the analysis's
    `recorded_by_user_id`, otherwise the override is rejected with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Corner/rbac/override_actor_must_differ_from_recorder
    """
    ctx, analysis = _setup_marginal_analysis()
    overridden = validate_success(
        api.override_purity_analysis(
            analysis["id"], make_quality_manager_headers("qm-ovr-1")
        ),
        200,
    )
    assert overridden["status"] == "OVERRIDDEN"
    assert overridden["result"] == "PASS_OVERRIDE"
    assert overridden["overridden_by_user_id"] == "qm-ovr-1"
    assert get_fill_lot(ctx["lot"]["id"])["status"] == "RELEASED"
