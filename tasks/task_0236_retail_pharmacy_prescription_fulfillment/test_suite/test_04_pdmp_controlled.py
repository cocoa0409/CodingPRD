"""PDMP risk scoring, monitoring posture cascade, controlled-substance lock.

Translations of queue A combinatorial_formula (PDMP), non_linear_state_machine
(Patient parallel dims), transitive_cascade (dispense -> posture), dual_variant
(PDMP committed), and queue B boundary / errors instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, create_pdmp_report_payload, clear_pdmp_block_payload,
)
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
TECH = TEST_USERS["technician_headers"]
PHARM = TEST_USERS["pharmacist_headers"]
CASH = TEST_USERS["cashier_headers"]


# ---------------------------------------------------------------------------
# Queue A — combinatorial weighted score: 3 fills x 3 prescribers -> 60 -> BLOCKED
# ---------------------------------------------------------------------------
def test_pdmp_weighted_score_nested_max_and_band_selection(api):
    """PRD §3.7: "The `risk_score` is the controlled-fill count multiplied by a
    per-fill weight of 10, plus the prescriber-shopping excess (the distinct
    prescriber count minus 1, but never below 0) multiplied by a per-prescriber
    weight of 15. The resulting flag is `BLOCKED` when the score is at least 60".

    Design: Difficulty/combinatorial_formula/pdmp_weighted_score_nested_max_and_band_selection
    """
    s = fx.setup_controlled_patient_with_dispenses(
        n_prescribers=3, n_dispenses=3, clock="2026-03-01T00:00:00.000Z",
        drug_overrides={"ndc": "00000-0003-01", "name": "Charlie CII",
                        "dea_schedule": "CII", "unit_price_cents": 1000},
        plan_overrides={"bin": "610003", "pcn": "PD", "name": "Plan D",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
    )
    data = validate_success(
        api.create_pdmp_report(create_pdmp_report_payload(s["patient"]["id"]), PHARM),
        expected_status=201,
    )
    assert data["distinct_prescriber_count"] == 3
    assert data["risk_score"] == 60  # 3*10 + max(3-1,0)*15 = 30 + 30
    assert data["resulting_flag"] == "BLOCKED"
    patient = validate_success(api.get_patient(s["patient"]["id"], PHARM))
    assert patient["controlled_status"] == "LOCKED"


# ---------------------------------------------------------------------------
# Queue A — committed dispense-time PDMP (3 fills, 1 prescriber) -> 30 -> REVIEW
# ---------------------------------------------------------------------------
def test_pdmp_risk_provisional_at_submit_vs_committed_at_dispense(api):
    """PRD §3.7: "The resulting flag is `BLOCKED` when the score is at least 60,
    otherwise `REVIEW` when the score is at least 30, otherwise `CLEAR`."
    PRD §3.7: "this regenerates the report using the committed variant and
    recomputes the patient's `pdmp_flag` and `controlled_status` from the
    `resulting_flag`."

    Design: Difficulty/dual_variant_calc/pdmp_risk_provisional_at_submit_vs_committed_at_dispense
    """
    s = fx.setup_controlled_patient_with_dispenses(
        n_prescribers=1, n_dispenses=3, clock="2026-03-01T00:00:00.000Z",
        drug_overrides={"ndc": "00000-0002-01", "name": "Bravo CII",
                        "dea_schedule": "CII", "unit_price_cents": 1000},
        plan_overrides={"bin": "610002", "pcn": "PC", "name": "Plan C",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
    )
    data = validate_success(
        api.create_pdmp_report(create_pdmp_report_payload(s["patient"]["id"]), PHARM),
        expected_status=201,
    )
    assert data["risk_score"] == 30  # 3 fills * 10, single prescriber -> no excess
    assert data["resulting_flag"] == "REVIEW"
    patient = validate_success(api.get_patient(s["patient"]["id"], PHARM))
    assert patient["pdmp_flag"] == "REVIEW"


# ---------------------------------------------------------------------------
# Queue A — Patient parallel dimensions flip together at block band
# ---------------------------------------------------------------------------
def test_patient_pdmp_parallel_dimension_flag_and_controlled_status(api):
    """PRD §3.2: "When the risk reaches the block band, the `pdmp_flag` becomes
    `BLOCKED` — whether the patient was previously `CLEAR` or `REVIEW` — and at
    that point the parallel `controlled_status` flips to `LOCKED`, after which
    new controlled claims are refused."

    Design: Difficulty/non_linear_state_machine/patient_pdmp_parallel_dimension_flag_and_controlled_status
    """
    s = fx.setup_controlled_patient_with_dispenses(
        n_prescribers=3, n_dispenses=3, clock="2026-03-01T00:00:00.000Z",
        drug_overrides={"ndc": "00000-0006-01", "name": "Echo CII",
                        "dea_schedule": "CII", "unit_price_cents": 1000},
        plan_overrides={"bin": "610006", "pcn": "PF", "name": "Plan F",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
    )
    patient = validate_success(api.get_patient(s["patient"]["id"], PHARM))
    assert patient["pdmp_flag"] == "BLOCKED"
    assert patient["controlled_status"] == "LOCKED"


# ---------------------------------------------------------------------------
# Queue A — depth-3 cascade from a single dispense
# ---------------------------------------------------------------------------
def test_dispense_cascades_pdmp_report_patient_flag_controlled_lock(api):
    """PRD §2.6: "when a fill reaches the dispensed state for a controlled drug,
    the system regenerates the patient's monitoring report, which in turn may
    drive the patient's `pdmp_flag` and then the patient's `controlled_status` —
    a three-step cascade from a single dispense."
    PRD §3.9: "if the drug is controlled, regenerates the patient's monitoring
    report under the committed variant and recomputes the patient's `pdmp_flag`
    and `controlled_status` from the result."

    Design: Difficulty/transitive_cascade/dispense_cascades_pdmp_report_patient_flag_controlled_lock
    """
    s = fx.setup_controlled_patient_with_dispenses(
        n_prescribers=3, n_dispenses=3, clock="2026-03-01T00:00:00.000Z",
        drug_overrides={"ndc": "00000-0007-01", "name": "Foxtrot CII",
                        "dea_schedule": "CII", "unit_price_cents": 1000},
        plan_overrides={"bin": "610007", "pcn": "PG", "name": "Plan G",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
    )
    last_fill = s["dispensed_fills"][-1]
    # B: the dispense regenerated a PdmpReport carrying the triggering fill_id.
    reports, _ = validate_paginated(
        api.list_pdmp_reports(PHARM, params={"patient_id": s["patient"]["id"]})
    )
    triggered = [r for r in reports if r.get("fill_id") == last_fill["id"]]
    assert triggered, "dispense must regenerate a PdmpReport keyed on the triggering fill"
    assert any(r["risk_score"] == 60 for r in triggered), \
        "the dispense-time report must score 60"
    # C + D: patient flag BLOCKED and controlled_status LOCKED.
    patient = validate_success(api.get_patient(s["patient"]["id"], PHARM))
    assert patient["pdmp_flag"] == "BLOCKED"
    assert patient["controlled_status"] == "LOCKED"


def test_pdmp_distinct_prescriber_excess_drives_block_band(api):
    """PRD §3.7: "plus the prescriber-shopping excess (the distinct prescriber
    count minus 1, but never below 0) multiplied by a per-prescriber weight of
    15."

    Design: Difficulty/combinatorial_formula/pdmp_weighted_score_nested_max_and_band_selection
    """
    # 3 distinct prescribers contribute (3-1)*15 = 30 of prescriber-shopping
    # weight on top of 3*10 fill weight -> 60. With a SINGLE prescriber the same
    # three fills would have scored only 30, so the excess term is load-bearing.
    s = fx.setup_controlled_patient_with_dispenses(
        n_prescribers=3, n_dispenses=3, clock="2026-03-01T00:00:00.000Z",
        drug_overrides={"ndc": "00000-0031-01", "name": "Charlie2 CII",
                        "dea_schedule": "CII", "unit_price_cents": 1000},
        plan_overrides={"bin": "610031", "pcn": "PD2", "name": "Plan D2",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
    )
    data = validate_success(
        api.create_pdmp_report(create_pdmp_report_payload(s["patient"]["id"]), PHARM),
        expected_status=201,
    )
    assert data["controlled_fill_count"] == 3
    assert data["distinct_prescriber_count"] == 3
    assert data["risk_score"] == 60


def test_committed_pdmp_report_records_lookback_and_counts(api):
    """PRD §3.7: "A report records the `patient_id` it concerns, the optional
    `fill_id` that triggered it (null for manual queries), the `lookback_days`
    (90), the `controlled_fill_count`, the `distinct_prescriber_count`, the
    `risk_score`, and the `resulting_flag` it drove the patient's posture to."

    Design: Difficulty/dual_variant_calc/pdmp_risk_provisional_at_submit_vs_committed_at_dispense
    """
    s = fx.setup_controlled_patient_with_dispenses(
        n_prescribers=1, n_dispenses=3, clock="2026-03-01T00:00:00.000Z",
        drug_overrides={"ndc": "00000-0032-01", "name": "Bravo2 CII",
                        "dea_schedule": "CII", "unit_price_cents": 1000},
        plan_overrides={"bin": "610032", "pcn": "PC2", "name": "Plan C2",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
    )
    data = validate_success(
        api.create_pdmp_report(create_pdmp_report_payload(s["patient"]["id"]), PHARM),
        expected_status=201,
    )
    # Manual query -> committed variant: 3 DISPENSED controlled fills, 1 prescriber.
    assert data["lookback_days"] == 90
    assert data["controlled_fill_count"] == 3
    assert data["distinct_prescriber_count"] == 1
    assert data["fill_id"] is None


def test_review_band_keeps_controlled_status_eligible(api):
    """PRD §3.2: "When a freshly computed report places the patient's risk in the
    review band, the `pdmp_flag` advances from `CLEAR` to `REVIEW`; the
    `controlled_status` stays `ELIGIBLE` and the pharmacist merely sees an
    advisory."

    Design: Difficulty/non_linear_state_machine/patient_pdmp_parallel_dimension_flag_and_controlled_status
    """
    # 3 fills, single prescriber -> score 30 -> REVIEW band; controlled_status
    # must stay ELIGIBLE (only the block band flips it to LOCKED).
    s = fx.setup_controlled_patient_with_dispenses(
        n_prescribers=1, n_dispenses=3, clock="2026-03-01T00:00:00.000Z",
        drug_overrides={"ndc": "00000-0033-01", "name": "Echo2 CII",
                        "dea_schedule": "CII", "unit_price_cents": 1000},
        plan_overrides={"bin": "610033", "pcn": "PF2", "name": "Plan F2",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
    )
    patient = validate_success(api.get_patient(s["patient"]["id"], PHARM))
    assert patient["pdmp_flag"] == "REVIEW"
    assert patient["controlled_status"] == "ELIGIBLE"


def test_dispense_cascade_locks_controlled_status_on_block(api):
    """PRD §3.2: "When the risk reaches the block band, the `pdmp_flag` becomes
    `BLOCKED` ... and at that point the parallel `controlled_status` flips to
    `LOCKED`, after which new controlled claims are refused."

    Design: Difficulty/transitive_cascade/dispense_cascades_pdmp_report_patient_flag_controlled_lock
    """
    # The third controlled dispense (across 3 prescribers) is the link that drives
    # the patient all the way to LOCKED via the regenerated report.
    s = fx.setup_controlled_patient_with_dispenses(
        n_prescribers=3, n_dispenses=3, clock="2026-03-01T00:00:00.000Z",
        drug_overrides={"ndc": "00000-0034-01", "name": "Foxtrot2 CII",
                        "dea_schedule": "CII", "unit_price_cents": 1000},
        plan_overrides={"bin": "610034", "pcn": "PG2", "name": "Plan G2",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
    )
    patient = validate_success(api.get_patient(s["patient"]["id"], PHARM))
    assert patient["controlled_status"] == "LOCKED"
    assert patient["pdmp_flag"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Queue B — empty history zero-count boundary
# ---------------------------------------------------------------------------
def test_pdmp_empty_history_zero_count_clear_flag(api):
    """PRD §3.7: "The resulting flag is `BLOCKED` when the score is at least 60,
    otherwise `REVIEW` when the score is at least 30, otherwise `CLEAR`."
    PRD §3.7: "The system counts the patient's qualifying controlled fills ...
    recording that as `controlled_fill_count`".

    Design: Difficulty/boundary_precision_check/pdmp_empty_history_zero_count_clear_flag
    """
    fx.set_clock("2026-03-01T00:00:00.000Z")
    patient = fx.create_patient(full_name="Pat Twelve", date_of_birth="2000-01-01")
    data = validate_success(
        api.create_pdmp_report(create_pdmp_report_payload(patient["id"]), PHARM),
        expected_status=201,
    )
    assert data["controlled_fill_count"] == 0
    assert data["risk_score"] == 0
    assert data["resulting_flag"] == "CLEAR"
    refreshed = validate_success(api.get_patient(patient["id"], PHARM))
    assert refreshed["pdmp_flag"] == "CLEAR"


def test_pdmp_zero_score_below_review_threshold_stays_clear(api):
    """PRD §3.7: "The resulting flag is `BLOCKED` when the score is at least 60,
    otherwise `REVIEW` when the score is at least 30, otherwise `CLEAR`."

    Design: Difficulty/boundary_precision_check/pdmp_empty_history_zero_count_clear_flag
    """
    # A score of 0 (no controlled fills) is strictly below the REVIEW threshold of
    # 30, so the resulting flag is CLEAR — the lower band boundary.
    fx.set_clock("2026-03-01T00:00:00.000Z")
    patient = fx.create_patient(full_name="Zero P", date_of_birth="2001-01-01")
    data = validate_success(
        api.create_pdmp_report(create_pdmp_report_payload(patient["id"]), PHARM),
        expected_status=201,
    )
    assert data["risk_score"] == 0
    assert data["resulting_flag"] == "CLEAR"


# ---------------------------------------------------------------------------
# Queue B — clear-pdmp-block when not blocked
# ---------------------------------------------------------------------------
def test_clear_pdmp_block_when_not_blocked(api):
    """PRD §3.2: "this requires the patient to currently be `BLOCKED` (otherwise
    `ERR_PATIENT_NOT_BLOCKED`)".

    Design: Corner/errors/clear_pdmp_block_when_not_blocked
    """
    fx.set_clock()
    patient = fx.create_patient(full_name="NotBlocked P", date_of_birth="1980-01-01")
    resp = api.clear_pdmp_block(patient["id"], clear_pdmp_block_payload(override_reason="test"),
                                PHARM)
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_BLOCKED.value)
