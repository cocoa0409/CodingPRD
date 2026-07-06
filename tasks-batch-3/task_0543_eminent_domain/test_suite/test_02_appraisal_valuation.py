"""Appraisal dual-basis valuation, OCC on parcel version, finalize cascades,
and inspection-window overlap."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_project, create_parcel, create_appraisal, create_finalized_appraisal,
    finalize_appraisal, parcel_version,
    setup_open_negotiation,
    TEST_USERS,
)

AGENT = TEST_USERS["right_of_way_agent_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]


def _bare_parcel(api):
    project = create_project(api=api)
    parcel = create_parcel(project["id"], api=api)
    return project, parcel


# ---- dual_variant_calc / jc_offer_vs_condemnation_basis --------------------

def test_offer_basis_nets_special_benefits_against_severance(api):
    """PRD §3.3: "The **offer basis**, stored as `just_compensation_cents`, is
    `land_value_cents` plus `improvements_value_cents` plus the greater of zero
    and the quantity (`severance_damages_cents` minus `special_benefits_cents`)".

    Design: Difficulty/dual_variant_calc/jc_offer_vs_condemnation_basis
    """
    _, parcel = _bare_parcel(api)
    appr = create_finalized_appraisal(
        parcel["id"], land=20_000_000, improvements=5_000_000,
        severance=3_000_000, special=1_000_000, api=api)
    data = validate_success(api.get_appraisal(appr["id"], AGENT))
    assert data["just_compensation_cents"] == 27_000_000


def test_condemnation_basis_ignores_special_benefits(api):
    """PRD §3.3: "The **condemnation basis**, stored as `condemnation_basis_cents`,
    is `land_value_cents` plus `improvements_value_cents` plus the full
    `severance_damages_cents`, with special benefits *not* offset. Consequently the
    two bases differ by exactly the smaller of `severance_damages_cents` and
    `special_benefits_cents`."

    Design: Difficulty/dual_variant_calc/jc_offer_vs_condemnation_basis
    """
    _, parcel = _bare_parcel(api)
    appr = create_finalized_appraisal(
        parcel["id"], land=20_000_000, improvements=5_000_000,
        severance=3_000_000, special=1_000_000, api=api)
    data = validate_success(api.get_appraisal(appr["id"], AGENT))
    assert data["condemnation_basis_cents"] == 28_000_000
    assert data["condemnation_basis_cents"] - data["just_compensation_cents"] == 1_000_000


# ---- combinatorial_formula / jc_max_offset_floor_mode_a --------------------

def test_offer_basis_floors_severance_term_at_zero(api):
    """PRD §3.3: "the greater of zero and the quantity (`severance_damages_cents`
    minus `special_benefits_cents`) — that is, special benefits offset severance
    damages but can never drive the severance term below zero."

    Design: Difficulty/combinatorial_formula/jc_max_offset_floor_mode_a
    """
    _, parcel = _bare_parcel(api)
    appr = create_finalized_appraisal(
        parcel["id"], land=20_000_000, improvements=5_000_000,
        severance=1_000_000, special=3_000_000, api=api)
    data = validate_success(api.get_appraisal(appr["id"], AGENT))
    assert data["just_compensation_cents"] == 25_000_000


def test_condemnation_basis_adds_full_severance_regardless_of_special(api):
    """PRD §3.3: "The **condemnation basis**, stored as `condemnation_basis_cents`,
    is `land_value_cents` plus `improvements_value_cents` plus the full
    `severance_damages_cents`, with special benefits *not* offset."

    Design: Difficulty/combinatorial_formula/jc_max_offset_floor_mode_a
    """
    _, parcel = _bare_parcel(api)
    appr = create_finalized_appraisal(
        parcel["id"], land=20_000_000, improvements=5_000_000,
        severance=1_000_000, special=3_000_000, api=api)
    data = validate_success(api.get_appraisal(appr["id"], AGENT))
    assert data["condemnation_basis_cents"] == 26_000_000


# ---- Corner: appraisal computed fields -------------------------------------

def test_appraisal_computes_both_bases_from_value_inputs(api):
    """PRD §3.3: "The **offer basis**, stored as `just_compensation_cents`, is
    `land_value_cents` plus `improvements_value_cents` plus the greater of zero
    and the quantity (`severance_damages_cents` minus `special_benefits_cents`)".

    Design: Corner/entities/appraisal_computed_fields_ignore_input_overrides
    """
    _, parcel = _bare_parcel(api)
    v = parcel_version(parcel["id"], api=api)
    resp = api.create_appraisal(parcel["id"], {
        "appraiser_name": "AX", "land_value_cents": 10_000_000,
        "improvements_value_cents": 2_000_000, "severance_damages_cents": 4_000_000,
        "special_benefits_cents": 1_000_000, "expected_parcel_version": v}, APPRAISER)
    data = validate_success(resp, 201)
    assert data["just_compensation_cents"] == 15_000_000
    assert data["condemnation_basis_cents"] == 16_000_000


# ---- Corner: finalize an already-finalized appraisal -----------------------

def test_finalize_already_finalized_returns_invalid_state(api):
    """PRD §3.3: "Finalization is a separate `Appraiser` action that moves an
    appraisal's `status` from `DRAFT` to `FINALIZED`; attempting to finalize an
    appraisal that is not in `DRAFT` yields `ERR_INVALID_APPRAISAL_STATE`."

    Design: Corner/state_machines/finalize_already_finalized_appraisal_returns_invalid_state
    """
    _, parcel = _bare_parcel(api)
    appr = create_finalized_appraisal(
        parcel["id"], severance=0, special=0, api=api)
    resp = api.finalize_appraisal(appr["id"], APPRAISER)
    validate_error(resp, ApiErrorId.ERR_INVALID_APPRAISAL_STATE)


# ---- Corner: OCC on appraisal create ---------------------------------------

def test_appraisal_create_with_stale_version_returns_412(api):
    """PRD §2.7: "a create that arrives with an `expected_parcel_version` that
    does not match the parcel's current `version` is working from an outdated
    view of the parcel and is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/appraisal_create_stale_parcel_version_returns_412
    """
    _, parcel = _bare_parcel(api)
    stale = parcel_version(parcel["id"], api=api)
    create_appraisal(parcel["id"], version=stale, land=10_000_000,
                     improvements=1_000_000, severance=0, special=0, api=api)
    resp = api.create_appraisal(parcel["id"], {
        "appraiser_name": "AX", "land_value_cents": 12_000_000,
        "improvements_value_cents": 1_000_000, "expected_parcel_version": stale},
        APPRAISER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_appraisal_create_with_current_version_bumps_parcel_version(api):
    """PRD §3.3: "Every appraisal creation increments the parcel's `version` by
    one."

    Design: Corner/cross_cutting_complexity_layers/appraisal_create_correct_version_succeeds_and_bumps
    """
    _, parcel = _bare_parcel(api)
    v = parcel_version(parcel["id"], api=api)
    resp = api.create_appraisal(parcel["id"], {
        "appraiser_name": "AX", "land_value_cents": 10_000_000,
        "improvements_value_cents": 1_000_000, "expected_parcel_version": v},
        APPRAISER)
    validate_success(resp, 201)
    assert parcel_version(parcel["id"], api=api) == v + 1


# ---- Corner: finalize supersede reconciliation -----------------------------

def test_finalize_supersedes_prior_and_reconciles_appraised_value(api):
    """PRD §3.3: "any *other* appraisal for the same parcel that was previously
    `FINALIZED` is transitioned from `FINALIZED` to `SUPERSEDED`, so that a parcel
    has at most one live finalized valuation. Second, the parcel's
    `appraised_value_cents` is set to this appraisal's `just_compensation_cents`".

    Design: Corner/cross_cutting_complexity_layers/finalize_supersede_reconciliation_updates_appraised_value
    """
    _, parcel = _bare_parcel(api)
    appr1 = create_finalized_appraisal(
        parcel["id"], land=20_000_000, improvements=5_000_000,
        severance=3_000_000, special=1_000_000, api=api)
    appr2 = create_appraisal(
        parcel["id"], land=22_000_000, improvements=5_000_000,
        severance=5_000_000, special=2_000_000, api=api)
    finalize_appraisal(appr2["id"], api=api)
    a1 = validate_success(api.get_appraisal(appr1["id"], AGENT))
    a2 = validate_success(api.get_appraisal(appr2["id"], AGENT))
    assert a1["status"] == "SUPERSEDED"
    assert a2["status"] == "FINALIZED"
    parcel_now = validate_success(api.get_parcel(parcel["id"], AGENT))
    assert parcel_now["appraised_value_cents"] == 30_000_000


# ---- transitive_cascade / finalize_to_parcel_to_project_committed_cascade ---

def test_finalize_second_appraisal_reconciles_parcel_appraised_value(api):
    """PRD §3.3: "the parcel's `appraised_value_cents` is set to this appraisal's
    `just_compensation_cents`; because that valuation changed, the project's
    `committed_cents` is recomputed whenever the parcel currently sits in a
    committed acquisition status."

    Design: Difficulty/transitive_cascade/finalize_to_parcel_to_project_committed_cascade
    """
    ctx = setup_open_negotiation(api=api)  # parcel IN_NEGOTIATION, committed 27,000,000
    parcel_id = ctx["parcel"]["id"]
    appr2 = create_appraisal(
        parcel_id, land=22_000_000, improvements=5_000_000,
        severance=5_000_000, special=2_000_000, api=api)
    finalize_appraisal(appr2["id"], api=api)
    parcel_now = validate_success(api.get_parcel(parcel_id, AGENT))
    assert parcel_now["appraised_value_cents"] == 30_000_000


def test_finalize_second_appraisal_recomputes_project_committed_cents(api):
    """PRD §2.10: "`committed_cents` is the sum of `appraised_value_cents` over
    the project's parcels whose `acquisition_status` is one of `IN_NEGOTIATION`,
    `AGREED`, `IN_CONDEMNATION`, or `POSSESSED`."

    Design: Difficulty/transitive_cascade/finalize_to_parcel_to_project_committed_cascade
    """
    ctx = setup_open_negotiation(api=api)
    parcel_id = ctx["parcel"]["id"]
    project_id = ctx["project"]["id"]
    before = validate_success(api.get_project(project_id, AGENT))
    assert before["committed_cents"] == 27_000_000
    appr2 = create_appraisal(
        parcel_id, land=22_000_000, improvements=5_000_000,
        severance=5_000_000, special=2_000_000, api=api)
    finalize_appraisal(appr2["id"], api=api)
    after = validate_success(api.get_project(project_id, AGENT))
    assert after["committed_cents"] == 30_000_000


# ---- resource_temporal_overlap / appraiser_inspection_half_open_overlap ----

def test_overlapping_inspection_window_rejected(api):
    """PRD §3.3: "a new window that overlaps any existing appointment window for
    the same `appraiser_name` is rejected with `ERR_APPRAISER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/appraiser_inspection_half_open_overlap
    """
    _, parcel = _bare_parcel(api)
    appr = create_appraisal(parcel["id"], severance=0, special=0, api=api)
    validate_success(api.create_inspection_appointment(appr["id"], {
        "appraiser_name": "AX", "start_at": "2026-05-10T10:00:00Z",
        "end_at": "2026-05-10T11:00:00Z"}, APPRAISER), 201)
    resp = api.create_inspection_appointment(appr["id"], {
        "appraiser_name": "AX", "start_at": "2026-05-10T10:30:00Z",
        "end_at": "2026-05-10T11:30:00Z"}, APPRAISER)
    validate_error(resp, ApiErrorId.ERR_APPRAISER_DOUBLE_BOOKED)


def test_adjacent_inspection_window_accepted(api):
    """PRD §3.3: "a half-open window from `start_at` (inclusive) to `end_at`
    (exclusive), where `end_at` must be strictly after `start_at`".

    Design: Difficulty/resource_temporal_overlap/appraiser_inspection_half_open_overlap
    """
    _, parcel = _bare_parcel(api)
    appr = create_appraisal(parcel["id"], severance=0, special=0, api=api)
    validate_success(api.create_inspection_appointment(appr["id"], {
        "appraiser_name": "AX", "start_at": "2026-05-10T10:00:00Z",
        "end_at": "2026-05-10T11:00:00Z"}, APPRAISER), 201)
    resp = api.create_inspection_appointment(appr["id"], {
        "appraiser_name": "AX", "start_at": "2026-05-10T11:00:00Z",
        "end_at": "2026-05-10T12:00:00Z"}, APPRAISER)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
