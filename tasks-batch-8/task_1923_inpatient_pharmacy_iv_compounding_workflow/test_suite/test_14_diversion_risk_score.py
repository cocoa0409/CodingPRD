"""Diversion risk score: weighted signals, C_II multiplier, tiers (PRD §3.7)."""
import pytest

from test_helpers import (
    count_payload,
    create_drug,
    evaluate_risk_payload,
    fixtures,
    restock_payload,
    setup_station_with_pocket,
    validate_paginated,
    validate_success,
)


def _setup_subject_pattern(api):
    """Subject pharmacist records 4 after-hours wastes then 2 counts (variances
    -2, -4) on BOTH a C_II pocket and a NON_CONTROLLED pocket at one station."""
    subject, subject_headers = fixtures.make_pharmacist()  # subject under review
    witness, _ = fixtures.make_nurse()
    restocker, restocker_headers = fixtures.make_technician()
    drug_c2 = create_drug(name="C2 Drug", schedule="C_II")
    drug_nc = create_drug(name="NC Drug", schedule="NON_CONTROLLED")
    st = fixtures.create_station(name="ST-1")
    pk_c2 = fixtures.create_pocket(st["id"], drug_c2["id"], max_units=500)
    pk_nc = fixtures.create_pocket(st["id"], drug_nc["id"], max_units=500)
    fixtures.set_clock("2026-08-01T23:30:00Z")  # after-hours (>= 22 UTC)
    for pocket, drug in ((pk_c2, drug_c2), (pk_nc, drug_nc)):
        current = validate_success(
            api.restock_pocket(pocket["id"], restock_payload(50, pocket["version"]),
                               restocker_headers),
            200,
        )
        for _ in range(4):
            payload = {"units": 1}
            if drug["schedule"] == "C_II":
                payload["witness_staff_id"] = witness["id"]
            validate_success(
                api.waste_pocket(pocket["id"], payload, subject_headers), 200
            )
    fixtures.set_clock("2026-08-02T12:00:00Z")
    # NON_CONTROLLED counts stay below their threshold (5) but feed the score.
    api.count_pocket(pk_nc["id"], count_payload(44), subject_headers)
    api.count_pocket(pk_nc["id"], count_payload(42), subject_headers)
    # C_II counts breach threshold 2 and open DiscrepancyCases.
    count_c2_first = validate_success(
        api.count_pocket(pk_c2["id"], count_payload(44), subject_headers), 200
    )
    count_c2_second = validate_success(
        api.count_pocket(pk_c2["id"], count_payload(42), subject_headers), 200
    )
    fixtures.set_clock("2026-08-03T00:00:00Z")
    return subject, st, drug_c2, drug_nc, count_c2_first, count_c2_second


class TestDiversionRiskScoreTieredInteraction:
    def test_cii_multiplier_pushes_pattern_over_open_case_threshold(
        self, api, diversion_officer_headers
    ):
        """PRD §3.7: "Two escalation rules then apply: if any single count in the window has an absolute variance of at least 10 and the drug is `C_II`, the raw score is raised to at least 80; and if the drug is `C_II`, the raw score is multiplied by 1.5. The final score rounds half-up to 2 decimal places and tiers as follows: a score of at least 75 is `OPEN_CASE`; at least 50 but below 75 is `WATCH`; below 50 is `CLEAR`. The `OPEN_CASE` tier auto-creates a `DiversionCase` in `OPEN` status with `opened_via` of `RISK_SCORE`."

        Design: Difficulty/combinatorial_formula/diversion_risk_score_tiered_interaction
        """
        subject, st, drug_c2, _, cnt1, cnt2 = _setup_subject_pattern(api)
        # 50 - 4 wasted == 46 expected; counts 44 and 42 -> variances -2, -4
        assert cnt1["variance_units"] == -2
        assert cnt1["discrepancy_case_id"] is not None  # C_II threshold 2
        assert cnt2["variance_units"] == -4  # COUNT events do not adjust the ledger
        result = validate_success(
            api.evaluate_diversion_risk(
                evaluate_risk_payload(st["id"], subject["id"], drug_c2["id"]),
                diversion_officer_headers,
            ),
            200,
        )
        # raw 62 (variance 10*(6/2)=30, waste 5*4=20, after-hours 3*4=12) x 1.5
        assert result["score"] == pytest.approx(93.0, abs=0.005)
        assert result["tier"] == "OPEN_CASE"
        assert result["diversion_case_id"] is not None
        rows, meta = validate_paginated(
            api.list_diversion_cases(
                diversion_officer_headers,
                params={"subject_staff_id": subject["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["opened_via"] == "RISK_SCORE"
        assert rows[0]["status"] == "OPEN"

    def test_same_pattern_on_non_controlled_drug_scores_clear(
        self, api, diversion_officer_headers
    ):
        """PRD §3.7: "The raw score is 10 times the halved variance sum, plus 5 times the waste count, plus 3 times the after-hours count."
        PRD §3.7: "The waste signal `w` counts the window's `WASTE` events on pockets whose drug is controlled — any schedule other than `NON_CONTROLLED`."

        Design: Difficulty/combinatorial_formula/diversion_risk_score_tiered_interaction
        """
        subject, st, _, drug_nc, _, _ = _setup_subject_pattern(api)
        result = validate_success(
            api.evaluate_diversion_risk(
                evaluate_risk_payload(st["id"], subject["id"], drug_nc["id"]),
                diversion_officer_headers,
            ),
            200,
        )
        # Window restricted to the named drug's schedule (NON_CONTROLLED):
        # variance 10*((2+4)/2)=30, waste 5*0=0 (NC drug is not controlled),
        # after-hours 3*4=12 -> raw 42 -> CLEAR (< 50); no multiplier, no case.
        assert result["score"] == pytest.approx(42.0, abs=0.005)
        assert result["tier"] == "CLEAR"
        assert result["diversion_case_id"] is None
