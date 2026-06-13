"""Adherence scoring (cumulative vs rolling) and the no-show / adherence
lifecycle driven by the trailing 30-day window.

Difficulty queue (A): dual_variant_calc (adherence), boundary_precision_check
(no-show window).
Corner queue (B): endpoints (adherence read), cross_cutting_complexity_layers
(clock advance de-escalation).
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_bookable_scenario, setup_patient_with_n_missed, book_session,
    create_session_payload,
    TEST_USERS,
)

SCHED = TEST_USERS["scheduler_headers"]
NEPH = TEST_USERS["nephrologist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]


def _book_terminal_series(api, scenario, outcomes):
    """Walk a series of (service_date, outcome) tuples on the scenario's patient.

    outcome in {"C","M","N"}: complete / mark-missed / cancel. Returns nothing;
    each booking reads the live patient version so the OCC guard passes.
    """
    for service_date, outcome in outcomes:
        sess = book_session(scenario, service_date=service_date)
        if outcome == "C":
            api.check_in_session(sess["id"], SCHED)
            get_success_data(api.complete_session(sess["id"], SCHED))
        elif outcome == "M":
            get_success_data(api.mark_missed_session(sess["id"], SCHED))
        elif outcome == "N":
            get_success_data(api.cancel_session(sess["id"], SCHED))


# ─── dual_variant_calc / adherence_rolling_vs_cumulative ──────────────────
def test_adherence_cumulative_over_all_qualifiers(api):
    """PRD §3.7: "A score is 100 multiplied by the number of completed sessions
    in the considered set, divided by the sum of completed and missed sessions in
    that set, rounded half-up to one decimal place"
    PRD §3.7: "The `cumulative_score` considers all qualifying sessions ever."
    PRD §3.7: "considering only those whose `clinical_status` is `COMPLETED` or
    `MISSED` and excluding `CANCELLED` sessions from both the numerator and the
    denominator."

    Design: Difficulty/dual_variant_calc/adherence_rolling_vs_cumulative
    """
    scenario = setup_bookable_scenario(modality="HEMODIALYSIS", dialyzer_reuse_limit=99,
                                       coinsurance_pct=0.0, set_clock_to="2026-07-01T08:00:00Z")
    # Need both MWF and TTHS shifts for distinct weekdays; add a TTHS shift.
    tths = get_success_data(api.create_shift(
        {"clinic_id": scenario["clinic"]["id"], "code": "TTHS_AM", "day_pattern": "TTHS",
         "start_minute": 360, "end_minute": 600}, ADMIN))
    mwf = scenario["shift"]
    # 8 COMPLETED, 3 MISSED, 1 CANCELLED (excluded) on alternating MWF/TTHS dates.
    series = [
        ("2026-06-01", "C", mwf), ("2026-06-02", "C", tths), ("2026-06-03", "M", mwf),
        ("2026-06-04", "C", tths), ("2026-06-05", "N", mwf), ("2026-06-06", "M", tths),
        ("2026-06-08", "C", mwf), ("2026-06-09", "C", tths), ("2026-06-10", "M", mwf),
        ("2026-06-11", "C", tths), ("2026-06-12", "C", mwf), ("2026-06-13", "C", tths),
    ]
    for service_date, outcome, shift in series:
        sess = book_session(scenario, service_date=service_date, shift_id=shift["id"])
        if outcome == "C":
            api.check_in_session(sess["id"], SCHED)
            get_success_data(api.complete_session(sess["id"], SCHED))
        elif outcome == "M":
            get_success_data(api.mark_missed_session(sess["id"], SCHED))
        else:
            get_success_data(api.cancel_session(sess["id"], SCHED))

    adh = validate_success(api.get_adherence(scenario["patient"]["id"], NEPH), 200)
    # 8 C / (8 C + 3 M) = 72.727... -> 72.7
    assert adh["cumulative_score"] == pytest.approx(72.7, abs=0.05), \
        f"expected cumulative 72.7, got {adh['cumulative_score']}"


def test_adherence_rolling_diverges_from_cumulative(api):
    """PRD §3.7: "The `rolling_score` considers only the most recent 8 qualifying
    sessions in that same ordering — so identical underlying data can yield a
    different cumulative and rolling percentage."
    PRD §3.7: "The qualifying sessions are ordered by `service_date` ascending and
    then by `created_at` ascending."

    Design: Difficulty/dual_variant_calc/adherence_rolling_vs_cumulative
    """
    scenario = setup_bookable_scenario(modality="HEMODIALYSIS", dialyzer_reuse_limit=99,
                                       coinsurance_pct=0.0, set_clock_to="2026-07-01T08:00:00Z")
    tths = get_success_data(api.create_shift(
        {"clinic_id": scenario["clinic"]["id"], "code": "TTHS_AM", "day_pattern": "TTHS",
         "start_minute": 360, "end_minute": 600}, ADMIN))
    mwf = scenario["shift"]
    series = [
        ("2026-06-01", "C", mwf), ("2026-06-02", "C", tths), ("2026-06-03", "M", mwf),
        ("2026-06-04", "C", tths), ("2026-06-05", "N", mwf), ("2026-06-06", "M", tths),
        ("2026-06-08", "C", mwf), ("2026-06-09", "C", tths), ("2026-06-10", "M", mwf),
        ("2026-06-11", "C", tths), ("2026-06-12", "C", mwf), ("2026-06-13", "C", tths),
    ]
    for service_date, outcome, shift in series:
        sess = book_session(scenario, service_date=service_date, shift_id=shift["id"])
        if outcome == "C":
            api.check_in_session(sess["id"], SCHED)
            get_success_data(api.complete_session(sess["id"], SCHED))
        elif outcome == "M":
            get_success_data(api.mark_missed_session(sess["id"], SCHED))
        else:
            get_success_data(api.cancel_session(sess["id"], SCHED))

    adh = validate_success(api.get_adherence(scenario["patient"]["id"], NEPH), 200)
    # most recent 8 qualifiers (06-04 C, 06-06 M, 06-08 C, 06-09 C, 06-10 M,
    # 06-11 C, 06-12 C, 06-13 C) = 6 C / 2 M -> 100*6/8 = 75.0, distinct from 72.7.
    assert adh["rolling_score"] == pytest.approx(75.0, abs=0.05), \
        f"expected rolling 75.0, got {adh['rolling_score']}"
    assert adh["rolling_score"] != adh["cumulative_score"], \
        "rolling and cumulative must diverge on this data"


# ─── Corner: endpoints / adherence_computed_read_no_sessions ──────────────
def test_adherence_read_with_no_terminal_sessions(api):
    """PRD §3.7: "it is null when the considered set has no completed and no
    missed sessions."
    PRD §3.3: "A newly created patient starts with `adherence_status`
    `GOOD_STANDING`, an `account_balance_cents` of 0, and a `no_show_count_window`
    of 0."

    Design: Corner/endpoints/adherence_computed_read_no_sessions
    """
    clinic = get_success_data(api.create_clinic({"name": "AdhEmpty"}, ADMIN))
    patient = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "AE1", "full_name": "Ae One"}, SCHED))
    adh = validate_success(api.get_adherence(patient["id"], NEPH), 200)
    assert adh["cumulative_score"] is None
    assert adh["rolling_score"] is None
    assert adh["no_show_count_window"] == 0
    assert adh["adherence_status"] == "GOOD_STANDING"


# ─── boundary_precision_check / no_show_window_empty_vs_exactly_three ─────
def test_no_show_window_below_at_risk_stays_good_standing(api):
    """PRD §3.7: "when the recomputed `no_show_count_window` is at least 3 but
    below 5, the patient is `AT_RISK`; and when it is below 3, the patient is
    `GOOD_STANDING`."

    Design: Difficulty/boundary_precision_check/no_show_window_empty_vs_exactly_three_triggers_at_risk
    """
    bundle = setup_patient_with_n_missed(2, clock="2026-06-12T07:00:00Z",
                                         service_dates=["2026-06-01", "2026-06-03"])
    patient = validate_success(api.get_patient(bundle["patient"]["id"], SCHED), 200)
    assert patient["no_show_count_window"] == 2
    assert patient["adherence_status"] == "GOOD_STANDING"


def test_no_show_window_exactly_three_triggers_at_risk(api):
    """PRD §3.7: "a patient can escalate `GOOD_STANDING → AT_RISK` when the count
    reaches 3"
    PRD §3.7: "This count is recomputed both when a session is marked missed and
    whenever the clinic clock is set"

    Design: Difficulty/boundary_precision_check/no_show_window_empty_vs_exactly_three_triggers_at_risk
    """
    # Two MISSED already in window, then mark the third missed and check escalation.
    bundle = setup_patient_with_n_missed(2, clock="2026-06-12T07:00:00Z",
                                         service_dates=["2026-06-01", "2026-06-03"])
    scenario = bundle  # carries patient/order/station/shift
    sess = book_session(scenario, service_date="2026-06-05")
    after = validate_success(api.mark_missed_session(sess["id"], SCHED), 200)
    # the response is the session; re-read the patient for the derived fields
    patient = validate_success(api.get_patient(bundle["patient"]["id"], SCHED), 200)
    assert patient["no_show_count_window"] == 3
    assert patient["adherence_status"] == "AT_RISK"


# ─── Corner: cross_cutting / clock_advance_drops_no_show_back_to_good ─────
def test_clock_advance_empties_window_back_to_good_standing(api):
    """PRD §3.7: "advancing the clock can carry old missed sessions out of the
    window."
    PRD §3.7: "can de-escalate `AT_RISK → GOOD_STANDING` automatically when a
    clock advance drops the count below 3."

    Design: Corner/cross_cutting_complexity_layers/clock_advance_drops_no_show_back_to_good_standing
    """
    bundle = setup_patient_with_n_missed(
        3, clock="2026-06-12T07:00:00Z",
        service_dates=["2026-06-01", "2026-06-03", "2026-06-05"])
    before = validate_success(api.get_patient(bundle["patient"]["id"], SCHED), 200)
    assert before["no_show_count_window"] == 3
    assert before["adherence_status"] == "AT_RISK"

    api.set_clock("2026-08-01T07:00:00Z", ADMIN)
    after = validate_success(api.get_patient(bundle["patient"]["id"], SCHED), 200)
    assert after["no_show_count_window"] == 0
    assert after["adherence_status"] == "GOOD_STANDING"
