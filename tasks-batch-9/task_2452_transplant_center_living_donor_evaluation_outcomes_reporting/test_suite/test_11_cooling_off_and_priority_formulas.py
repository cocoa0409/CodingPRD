"""The nested cooling-off window and the component-first priority score."""
from test_helpers import (
    advance_clock,
    advance_to_cooling_off_end,
    clear_both_domains,
    create_active_recipient,
    create_donor,
    create_recipient,
    record_disclosure,
    setup_program_with_staff,
    update_recipient_status,
    validate_success,
)
from test_helpers.api_client import api_client


def _attest(env, donor_id):
    """Attest a donor whose disclosure has already been recorded."""
    advance_to_cooling_off_end(env, donor_id)
    return validate_success(
        api_client.record_advocacy_determination(
            donor_id, {"outcome": "ATTESTED"}, env["advocate_headers"]
        )
    )


def test_non_directed_re_disclosure_halves_the_extended_base_and_ceils_it():
    """PRD §3.3: "Start with the program's `cooling_off_days` as the base. If the
    donor has no `intended_recipient_id`, add a further seven days to the base,
    because a non-directed donor has no relationship pressing them toward a
    decision and is given a longer window to reconsider. Then, if
    `disclosure_sequence` has reached 2 or more — that is, on every re-consent —
    the effective window is the larger of two days and half the base rounded up to
    a whole day; otherwise the effective window is the base itself."
    PRD §3.3: "Re-consent is the more interesting case: besides advancing the
    sequence and the window, it clears `attestation_at` to null, clears
    `final_risk_index` to null, and re-derives `overall_status` down to
    `EVAL_IN_PROGRESS`."

    Design: Difficulty/combinatorial_formula/cooling_off_window_nested_max_ceil_on_re_disclosure
    """
    env = setup_program_with_staff(cooling_off_days=5)
    donor = create_donor(env, mrn="D-001", age_years=41)
    clear_both_domains(env, donor["id"])

    first_disclosure = record_disclosure(env, donor["id"])
    assert first_disclosure["disclosure_sequence"] == 1
    assert first_disclosure["cooling_off_ends_at"].startswith("2026-08-13T00:00:00"), (
        "the first window is the un-halved 5 + 7 non-directed days"
    )
    attested = _attest(env, donor["id"])
    assert attested["advocacy_status"] == "ATTESTED"
    assert attested["final_risk_index"] == 2.0

    re_disclosed = record_disclosure(env, donor["id"])
    assert re_disclosed["disclosure_sequence"] == 2
    assert re_disclosed["disclosure_at"].startswith("2026-08-13T00:00:00")
    assert re_disclosed["cooling_off_ends_at"].startswith("2026-08-19T00:00:00"), (
        "the re-consent window is the larger of two days and 12 halved rounded up, "
        "so six days, not twelve and not two"
    )
    assert re_disclosed["advocacy_status"] == "DISCLOSED"
    assert re_disclosed["attestation_at"] is None
    assert re_disclosed["final_risk_index"] is None
    assert re_disclosed["overall_status"] == "EVAL_IN_PROGRESS"
    assert re_disclosed["medical_status"] == "CLEARED"
    assert re_disclosed["psychosocial_status"] == "CLEARED"


def test_directed_re_disclosure_window_is_the_worked_four_day_reading():
    """PRD §3.3: "Two worked readings: a directed donor at a program with a
    seven-day base disclosed at midnight on the first of the month may be attested
    at exactly midnight on the eighth; a non-directed donor at the same program
    gets a fourteen-day base and cannot be attested until the fifteenth; and a
    directed donor at that program who is re-disclosed at six in the morning on the
    tenth faces a window of four days — the larger of two and seven halved rounded
    up — and may be attested from six in the morning on the fourteenth."
    PRD §3.3: "Finally, `cooling_off_ends_at` is `disclosure_at` plus that many
    whole days, with the time-of-day component carried over untouched."

    Design: Difficulty/combinatorial_formula/cooling_off_window_nested_max_ceil_on_re_disclosure
    """
    env = setup_program_with_staff(cooling_off_days=7)
    recipient = create_active_recipient(env, mrn="R-001")
    donor = create_donor(env, intended_recipient_id=recipient["id"], mrn="D-001")
    clear_both_domains(env, donor["id"])

    first_disclosure = record_disclosure(env, donor["id"])
    assert first_disclosure["cooling_off_ends_at"].startswith("2026-08-08T00:00:00"), (
        "a directed donor at a seven-day base disclosed at midnight on the first "
        "may be attested at midnight on the eighth"
    )
    _attest(env, donor["id"])

    advance_clock(env, "2026-08-10T06:00:00Z")
    re_disclosed = record_disclosure(env, donor["id"])
    assert re_disclosed["disclosure_sequence"] == 2
    assert re_disclosed["disclosure_at"].startswith("2026-08-10T06:00:00")
    assert re_disclosed["cooling_off_ends_at"].startswith("2026-08-14T06:00:00"), (
        "four days from six in the morning on the tenth, time of day carried over"
    )


def test_re_disclosure_window_never_falls_below_the_two_day_floor():
    """PRD §3.3: "Then, if `disclosure_sequence` has reached 2 or more — that is,
    on every re-consent — the effective window is the larger of two days and half
    the base rounded up to a whole day; otherwise the effective window is the base
    itself."
    PRD §3.3: "Finally, `cooling_off_ends_at` is `disclosure_at` plus that many
    whole days, with the time-of-day component carried over untouched."

    Design: Difficulty/combinatorial_formula/cooling_off_window_nested_max_ceil_on_re_disclosure
    """
    env = setup_program_with_staff(cooling_off_days=1)
    recipient = create_active_recipient(env, mrn="R-001")
    donor = create_donor(env, intended_recipient_id=recipient["id"], mrn="D-001")
    clear_both_domains(env, donor["id"])

    first_disclosure = record_disclosure(env, donor["id"])
    assert first_disclosure["cooling_off_ends_at"].startswith("2026-08-02T00:00:00")
    _attest(env, donor["id"])

    re_disclosed = record_disclosure(env, donor["id"])
    assert re_disclosed["cooling_off_ends_at"].startswith("2026-08-04T00:00:00"), (
        "half of a one-day base rounded up is one day, so the two-day floor binds"
    )


def test_priority_score_rounds_each_component_before_summing_them():
    """PRD §3.2: "`waitlist_priority_score` is the sum of five components, each of
    which is rounded half up to two decimal places *before* the addition, with the
    sum itself left unrounded."
    PRD §3.2: "The waiting component is `active_days_total` multiplied by 0.007, so
    a full year of listed time contributes 2.56 points, and the small weight is
    deliberate so that waiting never overwhelms urgency."
    PRD §3.2: "The dialysis component is `dialysis_years` multiplied by 1.005."
    PRD §3.2: "Because each component is rounded first, component-then-sum and
    sum-then-round can disagree in the second decimal place, and the
    component-first reading is the correct one."

    Design: Difficulty/combinatorial_formula/waitlist_priority_component_rounding_order
    """
    env = setup_program_with_staff()
    recipient = create_recipient(
        env,
        mrn="R-001",
        abo_blood_type="A",
        age_years=44,
        cpra=0.85,
        dialysis_years=3.005,
        medical_urgency_points=7,
    )
    update_recipient_status(
        env, recipient["id"], "APPROVED_NOT_LISTED", "WORKUP_COMPLETE", "2026-08-01T00:00:00Z"
    )
    update_recipient_status(
        env, recipient["id"], "ACTIVE", "LISTED", "2026-08-01T00:00:00Z"
    )
    advance_clock(env, "2027-08-02T00:00:00Z")

    held = update_recipient_status(
        env,
        recipient["id"],
        "INACTIVE_HOLD",
        "MEDICALLY_UNSUITABLE",
        "2027-08-02T00:00:00Z",
    )

    assert held["listing_status"] == "INACTIVE_HOLD"
    assert held["active_days_total"] == 366
    assert held["waitlist_priority_score"] == 23.58, (
        "14.0 urgency + 2.56 waiting + 3.02 dialysis + 4.0 sensitization + 0.0 pediatric"
    )


def test_priority_score_component_rounding_beats_the_sum_then_round_answer():
    """PRD §3.2: "Because each component is rounded first, component-then-sum and
    sum-then-round can disagree in the second decimal place, and the
    component-first reading is the correct one."
    PRD §3.2: "The sensitization component is a tier lookup on `cpra`, inclusive at
    each lower bound: 10 when `cpra` is at least 0.98, otherwise 4 when it is at
    least 0.80, otherwise 1 when it is at least 0.20, otherwise 0."

    Design: Difficulty/combinatorial_formula/waitlist_priority_component_rounding_order
    """
    env = setup_program_with_staff()
    recipient = create_recipient(
        env,
        mrn="R-002",
        abo_blood_type="A",
        age_years=44,
        cpra=0.85,
        dialysis_years=1.7,
        medical_urgency_points=7,
    )
    update_recipient_status(
        env, recipient["id"], "APPROVED_NOT_LISTED", "WORKUP_COMPLETE", "2026-08-01T00:00:00Z"
    )
    update_recipient_status(
        env, recipient["id"], "ACTIVE", "LISTED", "2026-08-01T00:00:00Z"
    )
    advance_clock(env, "2027-08-01T00:00:00Z")

    held = update_recipient_status(
        env, recipient["id"], "INACTIVE_HOLD", "MEDICALLY_UNSUITABLE", "2027-08-01T00:00:00Z"
    )

    assert held["active_days_total"] == 365
    assert held["waitlist_priority_score"] == 22.27, (
        "14.0 + round(2.555) 2.56 + round(1.7085) 1.71 + 4.0; the unrounded sum "
        "22.2635 would have rounded to 22.26 instead"
    )
