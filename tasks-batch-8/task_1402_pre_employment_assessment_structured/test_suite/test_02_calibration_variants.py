"""Calibration index variants: RAW vs LENIENCY_ADJUSTED on identical scorecard data."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_active_cycle,
    create_calibrated_interviewer,
    create_candidate,
    invite_and_complete_candidate,
    book_completed_session,
    submit_scorecard,
    create_approved_guide,
    create_cycle_payload,
    assert_calibration,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["hm_headers"]


def _build_two_cycles_differing_only_in_scoring_mode():
    """Two cycles pinned to two guides that differ only in scoring_mode.

    Identical interview panels on each: candidate x1 rated iv1 COMM4/ANAL5,
    iv2 COMM5/ANAL3; candidate x2 rated iv1 COMM3/ANAL3, iv2 COMM4/ANAL4.
    Returns (calibration_record_of_iv1_raw_guide, calibration_record_of_iv1_adj_guide).
    """
    raw_setup = setup_active_cycle()  # default scoring_mode is RAW
    raw_cycle = raw_setup["cycle"]
    raw_guide = raw_setup["guide"]
    instrument = raw_setup["instrument"]
    requisition = raw_setup["requisition"]

    # Second cycle pinning a LENIENCY_ADJUSTED guide under the same requisition.
    adj_guide = create_approved_guide(scoring_mode="LENIENCY_ADJUSTED")
    resp = api_client.create_cycle(
        requisition["id"],
        create_cycle_payload(instrument["id"], adj_guide["id"], label="Cycle ADJ"),
        HM,
    )
    adj_cycle = get_success_data(resp)
    get_success_data(api_client.activate_cycle(adj_cycle["id"], HM))

    # Both interviewers hold a CALIBRATED record for EACH guide (four records total).
    iv1, cal_iv1_raw = create_calibrated_interviewer(raw_guide["id"])
    iv2, _cal_iv2_raw = create_calibrated_interviewer(raw_guide["id"])
    _, cal_iv1_adj = _certify_for(iv1, adj_guide["id"])
    _, _cal_iv2_adj = _certify_for(iv2, adj_guide["id"])

    def _panel(cycle, guide, cand_suffix, day1_hour, day2_hour):
        # Sessions for the same interviewer must not overlap across cycles; the
        # two panels are therefore placed in disjoint hours of each day.
        c1 = create_candidate(external_ref=f"C-{cand_suffix}1", full_name=f"Cand {cand_suffix}1",
                              email=f"c{cand_suffix}1@x.com", group_code="GROUP_A")
        c2 = create_candidate(external_ref=f"C-{cand_suffix}2", full_name=f"Cand {cand_suffix}2",
                              email=f"c{cand_suffix}2@x.com", group_code="GROUP_A")
        invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=50)
        invite_and_complete_candidate(cycle["id"], c2["id"], raw_score=50)
        # x1: iv1 COMM4/ANAL5, iv2 COMM5/ANAL3
        s1a = book_completed_session(cycle["id"], c1["id"], iv1["id"], guide["id"],
                                     f"2026-08-12T{day1_hour:02d}:00:00Z",
                                     f"2026-08-12T{day1_hour + 1:02d}:00:00Z")
        s1b = book_completed_session(cycle["id"], c1["id"], iv2["id"], guide["id"],
                                     f"2026-08-12T{day1_hour:02d}:00:00Z",
                                     f"2026-08-12T{day1_hour + 1:02d}:00:00Z")
        submit_scorecard(s1a["id"], iv1["id"],
                         ratings=[{"competency_code": "COMM", "rating": 4},
                                  {"competency_code": "ANAL", "rating": 5}])
        submit_scorecard(s1b["id"], iv2["id"],
                         ratings=[{"competency_code": "COMM", "rating": 5},
                                  {"competency_code": "ANAL", "rating": 3}])
        # x2: iv1 COMM3/ANAL3, iv2 COMM4/ANAL4
        s2a = book_completed_session(cycle["id"], c2["id"], iv1["id"], guide["id"],
                                     f"2026-08-13T{day2_hour:02d}:00:00Z",
                                     f"2026-08-13T{day2_hour + 1:02d}:00:00Z")
        s2b = book_completed_session(cycle["id"], c2["id"], iv2["id"], guide["id"],
                                     f"2026-08-13T{day2_hour:02d}:00:00Z",
                                     f"2026-08-13T{day2_hour + 1:02d}:00:00Z")
        submit_scorecard(s2a["id"], iv1["id"],
                         ratings=[{"competency_code": "COMM", "rating": 3},
                                  {"competency_code": "ANAL", "rating": 3}],
                         overall_recommendation="NO")
        submit_scorecard(s2b["id"], iv2["id"],
                         ratings=[{"competency_code": "COMM", "rating": 4},
                                  {"competency_code": "ANAL", "rating": 4}])

    _panel(raw_cycle, raw_guide, "R", day1_hour=9, day2_hour=9)
    _panel(adj_cycle, adj_guide, "D", day1_hour=11, day2_hour=11)
    return cal_iv1_raw, cal_iv1_adj


def _certify_for(interviewer, guide_id):
    """Create + certify one calibration record for (interviewer, guide_id)."""
    from test_helpers import create_calibration_payload, certify_calibration_payload
    resp = api_client.create_calibration(interviewer["id"], create_calibration_payload(guide_id), ADMIN)
    cal = get_success_data(resp)
    get_success_data(api_client.certify_calibration(cal["id"], certify_calibration_payload(), ADMIN))
    return interviewer, get_success_data(api_client.get_calibration(cal["id"], ADMIN))


def test_calibration_index_raw_guide(api):
    """PRD §3.6: "For a guide whose `scoring_mode` is `RAW`, the index is one minus the
    ratio of the mean absolute deviation to the scale, that ratio capped at one, rounded
    half-up to four decimal places."

    Deviations for iv1 vs peers: |4-5|, |5-3|, |3-4|, |3-4| -> mean 1.25, scale 4 ->
    1 - 1.25/4 = 0.6875.

    Design: Difficulty/dual_variant_calc/calibration_index_raw_vs_leniency_adjusted
    """
    cal_raw, _ = _build_two_cycles_differing_only_in_scoring_mode()
    data = validate_success(api.get_calibration(cal_raw["id"], ADMIN))
    assert_calibration(data)
    assert data["calibration_index"] == pytest.approx(0.6875, abs=0.0001)


def test_calibration_index_leniency_adjusted_strictly_lower(api):
    """PRD §3.6: "For `LENIENCY_ADJUSTED`, the same base index is multiplied by one minus
    half of a leniency term, where the leniency term is the absolute difference between
    the interviewer's own mean rating across the pairs and the cohort mean across all
    ratings in the pairs (the interviewer included), divided by the scale and capped at
    one; identical scorecard data therefore yields a strictly lower index whenever the
    interviewer drifts from the cohort mean."

    iv1 own mean 3.75 vs cohort 3.875 -> leniency 0.125/4 = 0.03125 ->
    0.6875 * (1 - 0.5*0.03125) = 0.6768.

    Design: Difficulty/dual_variant_calc/calibration_index_raw_vs_leniency_adjusted
    """
    cal_raw, cal_adj = _build_two_cycles_differing_only_in_scoring_mode()
    raw_idx = validate_success(api.get_calibration(cal_raw["id"], ADMIN))["calibration_index"]
    adj_data = validate_success(api.get_calibration(cal_adj["id"], ADMIN))
    adj_idx = adj_data["calibration_index"]
    assert adj_idx == pytest.approx(0.6768, abs=0.0001)
    assert adj_idx < raw_idx, (
        "identical ratings under LENIENCY_ADJUSTED yield a strictly lower index than RAW"
    )
