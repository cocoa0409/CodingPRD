"""Clinical scoring: MELD-Na / PELD finalization, the dialysis clamp, the sodium
branch, supersession, and current_meld_peld recompute.

Tests translate difficulty instances dvc_meld_vs_peld_clinical_scoring and
cf_meld_na_nonlinear_sodium_branch, and corner instances
corner_meld_dialysis_clamp_variant, corner_finalize_supersedes_prior_and_updates_current,
corner_finalize_already_finalized_score_invalid_state.
"""
from test_helpers import (
    validate_success, validate_error,
    api_client,
    set_clock, create_center, create_candidate, create_finalized_score,
    create_clinical_score_payload,
    make_center_headers,
)


def test_adult_finalize_yields_meld_na_kind(api):
    """PRD §3.3: "For an adult candidate (not pediatric), the MELD-Na formula
    applies and score_kind is MELD_NA."

    Design: Difficulty/dual_variant_calc/dvc_meld_vs_peld_clinical_scoring
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    candidate = create_candidate(center, mrn="A1",
                                 date_of_birth="1980-01-01T00:00:00Z")
    headers = make_center_headers(center["id"])
    score = validate_success(api.create_clinical_score(
        candidate["id"],
        create_clinical_score_payload(bilirubin_mg_dl=4.0, inr=2.0,
                                      creatinine_mg_dl=2.0, sodium_mmol_l=130),
        headers), 201)
    finalized = validate_success(api.finalize_clinical_score(score["id"], headers), 200)
    assert finalized["score_kind"] == "MELD_NA"


def test_adult_finalize_allocation_score_value(api):
    """PRD §3.3: "this base index is multiplied by 10 and rounded half-up to the
    nearest integer." PRD §3.3: "Finally the adjusted value is rounded half-up
    and clamped into the inclusive 6-to-40 band to yield allocation_score."

    Design: Difficulty/dual_variant_calc/dvc_meld_vs_peld_clinical_scoring
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    candidate = create_candidate(center, mrn="A1",
                                 date_of_birth="1980-01-01T00:00:00Z")
    headers = make_center_headers(center["id"])
    score = validate_success(api.create_clinical_score(
        candidate["id"],
        create_clinical_score_payload(bilirubin_mg_dl=4.0, inr=2.0,
                                      creatinine_mg_dl=2.0, sodium_mmol_l=130),
        headers), 201)
    finalized = validate_success(api.finalize_clinical_score(score["id"], headers), 200)
    assert finalized["allocation_score"] == 29


def test_meld_na_sodium_branch_applies_above_eleven(api):
    """PRD §3.3: "A sodium adjustment is applied only when that rounded base index
    exceeds 11: sodium is clamped into the inclusive band from 125.0 to 137.0, and
    the adjusted value is the base index plus 1.32 times (137 minus the clamped
    sodium), minus the product of 0.033, the base index, and (137 minus the
    clamped sodium)."

    Design: Difficulty/combinatorial_formula/cf_meld_na_nonlinear_sodium_branch
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    candidate = create_candidate(center, mrn="A2",
                                 date_of_birth="1980-01-01T00:00:00Z")
    headers = make_center_headers(center["id"])
    score = validate_success(api.create_clinical_score(
        candidate["id"],
        create_clinical_score_payload(bilirubin_mg_dl=3.0, inr=1.8,
                                      creatinine_mg_dl=2.0, sodium_mmol_l=130),
        headers), 201)
    finalized = validate_success(api.finalize_clinical_score(score["id"], headers), 200)
    assert finalized["score_kind"] == "MELD_NA"
    assert finalized["allocation_score"] == 28


def test_meld_na_creatinine_clamped_to_band(api):
    """PRD §3.3: "creatinine is the measured creatinine_mg_dl first floored at 1.0
    and then capped at 4.0 (that is, clamped into the inclusive 1.0-to-4.0 band)."

    Design: Difficulty/combinatorial_formula/cf_meld_na_nonlinear_sodium_branch
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    # Two adults: one with creatinine 10.0 (clamped to 4.0), one with exactly 4.0.
    cand_hi = create_candidate(center, mrn="CL1", date_of_birth="1980-01-01T00:00:00Z")
    cand_cap = create_candidate(center, mrn="CL2", date_of_birth="1980-01-01T00:00:00Z")
    s_hi = validate_success(api.create_clinical_score(
        cand_hi["id"],
        create_clinical_score_payload(bilirubin_mg_dl=3.0, inr=1.8,
                                      creatinine_mg_dl=10.0, sodium_mmol_l=130),
        headers), 201)
    s_cap = validate_success(api.create_clinical_score(
        cand_cap["id"],
        create_clinical_score_payload(bilirubin_mg_dl=3.0, inr=1.8,
                                      creatinine_mg_dl=4.0, sodium_mmol_l=130),
        headers), 201)
    f_hi = validate_success(api.finalize_clinical_score(s_hi["id"], headers), 200)
    f_cap = validate_success(api.finalize_clinical_score(s_cap["id"], headers), 200)
    # Creatinine 10.0 capped at 4.0 yields the same allocation_score as 4.0.
    assert f_hi["allocation_score"] == f_cap["allocation_score"]


def test_dialysis_clamps_creatinine_to_four(api):
    """PRD §3.3: "when on_dialysis_twice_in_week is true, creatinine is forced to
    4.0 regardless of the measured value."

    Design: Corner/calculations/corner_meld_dialysis_clamp_variant
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    dial = create_candidate(center, mrn="CA1", date_of_birth="1980-01-01T00:00:00Z")
    nodial = create_candidate(center, mrn="CA2", date_of_birth="1980-01-01T00:00:00Z")
    s_dial = validate_success(api.create_clinical_score(
        dial["id"],
        create_clinical_score_payload(bilirubin_mg_dl=2.0, inr=1.5,
                                      creatinine_mg_dl=1.2, sodium_mmol_l=135,
                                      on_dialysis_twice_in_week=True),
        headers), 201)
    s_nodial = validate_success(api.create_clinical_score(
        nodial["id"],
        create_clinical_score_payload(bilirubin_mg_dl=2.0, inr=1.5,
                                      creatinine_mg_dl=1.2, sodium_mmol_l=135,
                                      on_dialysis_twice_in_week=False),
        headers), 201)
    f_dial = validate_success(api.finalize_clinical_score(s_dial["id"], headers), 200)
    f_nodial = validate_success(api.finalize_clinical_score(s_nodial["id"], headers), 200)
    assert f_dial["allocation_score"] == 28
    assert f_nodial["allocation_score"] == 17


def test_finalize_supersedes_prior_and_updates_current_meld(api):
    """PRD §3.3: "If the candidate already has a prior FINALIZED clinical score,
    that prior score is moved to SUPERSEDED." PRD §3.3: "The system then recomputes
    current_meld_peld on the candidate to the allocation_score of the now-most-recent
    finalized score, where most recent is judged by effective_at, with ties broken
    by created_at."

    Design: Corner/calculations/corner_finalize_supersedes_prior_and_updates_current
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    cand = create_candidate(center, mrn="SU1", date_of_birth="1980-01-01T00:00:00Z")
    s1 = validate_success(api.create_clinical_score(
        cand["id"],
        create_clinical_score_payload(bilirubin_mg_dl=3.0, inr=1.8,
                                      creatinine_mg_dl=2.0, sodium_mmol_l=130,
                                      effective_at="2026-06-01T00:00:00Z"),
        headers), 201)
    validate_success(api.finalize_clinical_score(s1["id"], headers), 200)
    s2 = validate_success(api.create_clinical_score(
        cand["id"],
        create_clinical_score_payload(bilirubin_mg_dl=4.0, inr=2.0,
                                      creatinine_mg_dl=2.0, sodium_mmol_l=130,
                                      effective_at="2026-06-05T00:00:00Z"),
        headers), 201)
    f2 = validate_success(api.finalize_clinical_score(s2["id"], headers), 200)
    assert f2["allocation_score"] == 29

    s1_after = validate_success(api.get_clinical_score(s1["id"], headers), 200)
    assert s1_after["status"] == "SUPERSEDED"

    cand_after = validate_success(api.get_candidate(cand["id"], headers), 200)
    assert cand_after["current_meld_peld"] == 29


def test_finalize_already_finalized_score_rejected(api):
    """PRD §3.3: "Finalization is permitted only when the score is currently DRAFT
    — otherwise ERR_INVALID_STATE."

    Design: Corner/state_machines/corner_finalize_already_finalized_score_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    headers = make_center_headers(center["id"])
    cand = create_candidate(center, mrn="S1", date_of_birth="1980-01-01T00:00:00Z")
    score = create_finalized_score(center, cand)
    res = api.finalize_clinical_score(score["id"], headers)
    validate_error(res, "ERR_INVALID_STATE")
