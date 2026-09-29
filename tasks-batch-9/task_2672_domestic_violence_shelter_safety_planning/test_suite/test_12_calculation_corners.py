"""Corner readings of the four derived quantities: the disclosure projection's allow-lists
and canonical ordering, the danger score's cap, rounding mode and input-set filter, the
secondary-trauma decay steps, and the posture precedence that outranks a band.
"""

from test_helpers import (
    ADMIN_HEADERS,
    MODERATE_FACTORS,
    advance_clock,
    api_client,
    decide_disclosure,
    read_admission,
    read_client,
    read_staff,
    record_wellness_check,
    seed_client,
    seed_disclosure_event,
    seed_hotline_advocate,
    seed_hotline_call,
    seed_imminent_client,
    seed_privacy_officer,
    seed_reserved_admission,
    seed_risk_assessment,
    validate_paginated,
    validate_success,
)

STARTUP_CLOCK = "2026-08-01T00:00:00.000Z"
TWO_ADULTS = {"household_size": 2, "minor_children_count": 0, "accessibility_required": False}
PAGE = {"limit": 10, "offset": 0}
SCRAMBLED_SIX_KEYS = [
    "hotline_call_transcript",
    "client_code",
    "shelter_street_address",
    "entry_date",
    "legal_name",
    "household_size",
]


def test_an_hmis_export_splits_six_scrambled_keys_three_and_three_in_vocabulary_order():
    """Only the five allowed keys pass, and both arrays come back sorted by the vocabulary.

    PRD: "`HMIS_EXPORT` allows exactly five keys — `client_code`, `household_size`,
    `minor_children_count`, `program_type` and `entry_date`."

    PRD: "**Both arrays are always emitted in the canonical vocabulary order above, never in
    the order the requester listed them**, so that two requests for the same keys in different
    orders produce byte-identical arrays."

    PRD: "If at least one requested key was suppressed, the very same request instead moves
    `REQUESTED` → `PARTIALLY_RELEASED`."

    Design: Corner/calculations/hmis_export_projection_releases_only_the_five_allowed_keys
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    officer = seed_privacy_officer("Opal Reed", max_caseload=12)
    client = seed_client(
        advocate,
        client_code="C-3001",
        legal_name="Ada Verne",
        household_size=3,
        minor_children_count=1,
        accessibility_required=False,
        location_confidential=True,
        hmis_disclosure_consent="GRANTED",
    )
    event = seed_disclosure_event(
        officer,
        client["id"],
        advocate.id,
        "HMIS_EXPORT",
        SCRAMBLED_SIX_KEYS,
        requester_org="Regional Continuum of Care",
    )

    response = decide_disclosure(officer, event["id"], "RELEASE")

    decided = validate_success(response, 200)
    assert decided["status"] == "PARTIALLY_RELEASED"
    assert decided["released_field_keys"] == ["client_code", "household_size", "entry_date"]
    assert decided["suppressed_field_keys"] == [
        "legal_name",
        "shelter_street_address",
        "hotline_call_transcript",
    ]
    assert decided["decided_by_staff_id"] == officer.id
    assert decided["decided_at"] == STARTUP_CLOCK
    assert decided["late_filed"] is False
    assert decided["decision_deadline_utc"] is None
    survivor = read_client(client["id"])
    assert survivor["confidentiality_posture"] == "NORMAL"
    assert survivor["version"] == client["version"]


def test_a_reserved_admission_and_an_unassessed_call_corroborate_nothing():
    """CORROBORATED_REVIEW is selected, yet the history on file is all outside its input set.

    PRD: "Cases still in `PETITION_DRAFTED` or already at `DENIED_FINAL` do not corroborate;
    admissions still `RESERVED` or already `CANCELLED` do not corroborate; and calls still in
    `RECEIVED` or `RISK_ASSESSED` do not corroborate."

    PRD: "Under `CORROBORATED_REVIEW`, the bonus is 6 points for each corroborating fact that
    holds."

    Design: Corner/calculations/corroborating_facts_exclude_reserved_admissions_and_undisposed_calls
    """
    scene, client, _request, admission = seed_reserved_admission(
        client_overrides=dict(TWO_ADULTS, client_code="C-3002", legal_name="Bess Crow"),
        assessment_overrides=dict(MODERATE_FACTORS),
        admission_overrides={"entry_date": "2026-08-07", "planned_exit_date": "2026-08-12"},
    )
    second_call = seed_hotline_call(
        scene.advocate, client["id"], presenting_concerns="Second call, situation worsened."
    )
    assert read_admission(scene.manager, admission["id"])["occupancy_status"] == "RESERVED"
    assert second_call["status"] == "RECEIVED"

    response = api_client.create_risk_assessment(
        second_call["id"],
        dict(MODERATE_FACTORS, corroborate_with_history=True),
        scene.advocate.headers,
    )

    review = validate_success(response, 201)
    assert review["variant_applied"] == "CORROBORATED_REVIEW"
    assert review["corroborating_fact_count"] == 0
    assert review["base_subtotal"] == 44.0
    assert review["escalation_multiplier"] == 1.10
    assert review["danger_score"] == 48.4
    assert review["risk_band"] == "MODERATE"
    survivor = read_client(client["id"])
    assert survivor["current_danger_score"] == 48.4
    assert survivor["current_risk_band"] == "MODERATE"


def test_twelve_stalking_contacts_and_seven_earn_the_same_fourteen_points():
    """The stalking term truncates at seven events, so the two clients score identically.

    PRD: "**First**, the weighted factor points are summed: 25 points when `weapon_access` is
    true and none otherwise; 20 points when `strangulation_history` is true; 15 points when
    `separation_recent` is true; 18 points when `threats_to_kill` is true; and 2 points for
    each stalking contact per week, counting at most 7 contacts even when
    `stalking_frequency_per_week` is higher — a survivor reporting 12 contacts a week and a
    survivor reporting 7 both earn 14 points from that factor."

    PRD: "`escalation_multiplier` is 1.25 when both `weapon_access` and
    `strangulation_history` are true, 1.10 when exactly one of the two is true, and 1.00 when
    neither is."

    Design: Corner/calculations/stalking_cap_limits_factor_points_at_seven_events
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    no_cofactors = {
        "weapon_access": False,
        "strangulation_history": False,
        "separation_recent": False,
        "threats_to_kill": False,
    }
    scored = []
    for code, name, concerns, contacts in (
        ("C-3003", "Cleo Nash", "He follows her almost every day.", 12),
        ("C-3004", "Dora Pike", "He waits outside work once a day.", 7),
    ):
        client = seed_client(
            advocate, client_code=code, legal_name=name, household_size=2,
            minor_children_count=0, accessibility_required=False, location_confidential=True,
        )
        call = seed_hotline_call(advocate, client["id"], presenting_concerns=concerns)
        assessment = seed_risk_assessment(
            advocate, call["id"], stalking_frequency_per_week=contacts, **no_cofactors
        )
        scored.append((client, assessment))

    (client_a, twelve_contacts), (client_b, seven_contacts) = scored
    assert twelve_contacts["danger_score"] == 14.0
    assert seven_contacts["danger_score"] == 14.0
    for assessment in (twelve_contacts, seven_contacts):
        assert assessment["base_subtotal"] == 14.0
        assert assessment["escalation_multiplier"] == 1.00
        assert assessment["risk_band"] == "LOW"
    for client in (client_a, client_b):
        survivor = read_client(client["id"])
        assert survivor["current_risk_band"] == "LOW"
        assert survivor["current_danger_score"] == 14.0
        assert survivor["confidentiality_posture"] == "NORMAL"


def test_an_exact_fifty_six_point_two_five_rounds_up_to_fifty_six_point_three():
    """Both co-factors and nothing else produce the value that discriminates the rounding mode.

    PRD: "**Fourth**, `danger_score` is the `base_subtotal` multiplied by the
    `escalation_multiplier`, rounded half up to one decimal place, and then capped at 100.0 —
    the cap is applied after the rounding, never before."

    PRD: "The `risk_band` follows from the capped score by threshold: `IMMINENT` at 75.0 or
    above, otherwise `ELEVATED` at 50.0 or above, otherwise `MODERATE` at 25.0 or above,
    otherwise `LOW`."

    Design: Corner/calculations/danger_score_rounds_half_up_at_the_hundredths_boundary
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    client = seed_client(
        advocate, client_code="C-3005", legal_name="Elsa Trent", household_size=2,
        minor_children_count=0, accessibility_required=False, location_confidential=True,
    )
    call = seed_hotline_call(
        advocate, client["id"], presenting_concerns="He keeps a pistol and has choked her before."
    )

    assessment = seed_risk_assessment(
        advocate,
        call["id"],
        weapon_access=True,
        strangulation_history=True,
        separation_recent=False,
        threats_to_kill=False,
        stalking_frequency_per_week=0,
    )

    assert assessment["base_subtotal"] == 45.0
    assert assessment["escalation_multiplier"] == 1.25
    assert assessment["danger_score"] == 56.3
    assert assessment["risk_band"] == "ELEVATED"
    survivor = read_client(client["id"])
    assert survivor["current_danger_score"] == 56.3
    assert survivor["confidentiality_posture"] == "NORMAL"


def test_one_wellness_check_decays_through_all_three_posture_bands_untouched():
    """Nothing but the clock moves, and the same 70 points read 70.0, then 42.0, then 0.0.

    PRD: "Each check stores its own undecayed weight as `contribution_points`: the
    `distress_scale` multiplied by 6, plus the `exposure_hours` multiplied by 0.5, and the whole
    sum then multiplied by 0.70 when `debrief_completed` is true or left as it stands when it is
    false, with the result rounded half up to one decimal place."

    PRD: "A check no more than 7 days old counts at its full `contribution_points`. A check
    older than 7 days but no more than 30 days old counts at 0.6 of its points. A check older
    than 30 days counts for nothing at all — no check is ever excluded from the calculation, it
    simply decays to a zero factor."

    PRD: "A clock advance reports `restaffed_posture_count`, the number of staff members whose
    `wellness_posture` actually changed value as a result, and increments the `version` of each
    staff member it changed."

    PRD: "A wellness check is an immutable event: it carries an `id` and a `created_at` and
    nothing else from the audit triple."

    Design: Corner/calculations/wellness_check_contribution_decays_at_the_seven_and_thirty_day_marks
    """
    advocate = seed_hotline_advocate("Rosa Marin", max_caseload=10)
    check = record_wellness_check(
        advocate.id,
        checked_on_utc="2026-08-01T00:00:00Z",
        exposure_hours=20.0,
        distress_scale=10,
        debrief_completed=False,
    )
    assert check["contribution_points"] == 70.0
    at_creation = read_staff(advocate.id)
    assert at_creation["active_caseload_count"] == 0
    assert at_creation["secondary_trauma_index"] == 70.0
    assert at_creation["wellness_posture"] == "FROZEN"

    day_seven = advance_clock("2026-08-08T00:00:00Z")
    day_seven_staff = read_staff(advocate.id)
    day_eight = advance_clock("2026-08-09T00:00:00Z")
    day_eight_staff = read_staff(advocate.id)
    day_thirty_one = advance_clock("2026-09-01T00:00:00Z")
    day_thirty_one_staff = read_staff(advocate.id)

    assert day_seven_staff["secondary_trauma_index"] == 70.0
    assert day_seven_staff["wellness_posture"] == "FROZEN"
    assert day_seven["restaffed_posture_count"] == 0
    assert day_eight_staff["secondary_trauma_index"] == 42.0
    assert day_eight_staff["wellness_posture"] == "RESTRICTED"
    assert day_eight["restaffed_posture_count"] == 1
    assert day_thirty_one_staff["secondary_trauma_index"] == 0.0
    assert day_thirty_one_staff["wellness_posture"] == "OPEN"
    assert day_thirty_one["restaffed_posture_count"] == 1
    for reading in (day_seven, day_eight, day_thirty_one):
        assert reading["expired_screening_request_count"] == 0
    rows, meta = validate_paginated(
        api_client.list_wellness_checks(advocate.id, ADMIN_HEADERS, params=dict(PAGE))
    )
    assert meta["total_count"] == 1
    assert rows[0]["contribution_points"] == 70.0
    assert "version" not in rows[0]


def test_a_mandated_report_decided_one_second_late_still_releases_everything():
    """The only kind with a deadline releases the whole vocabulary and is stamped late.

    PRD: "Its `decision_deadline_utc` is set only for a `MANDATED_REPORT`, as the event's
    `created_at` plus 24 hours; for every other `kind` it stays null, because only mandated
    reports are on a statutory clock."

    PRD: "`MANDATED_REPORT` allows the entire vocabulary, suppressing nothing."

    PRD: "Either release outcome stamps `decided_by_staff_id` with the acting officer, sets
    `decided_at` to the current clock reading, and evaluates `late_filed`: it becomes true only
    when the `kind` is `MANDATED_REPORT` and `decided_at` falls **strictly after**
    `decision_deadline_utc`."

    PRD: "A `MANDATED_REPORT` needs no release of information at all, since the duty to report
    exists independently of the survivor's consent, and it is likewise exempt from the consent
    gate."

    Design: Corner/calculations/mandated_report_decided_after_the_deadline_sets_late_filed
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    officer = seed_privacy_officer("Opal Reed", max_caseload=12)
    client = seed_client(
        advocate,
        client_code="C-3006",
        legal_name="Fay Orwell",
        household_size=3,
        minor_children_count=1,
        accessibility_required=False,
        location_confidential=True,
    )
    event = seed_disclosure_event(
        officer,
        client["id"],
        advocate.id,
        "MANDATED_REPORT",
        ["hotline_call_transcript", "legal_name", "shelter_street_address"],
        requester_org="County Child Protection",
    )
    assert event["decision_deadline_utc"] == "2026-08-02T00:00:00.000Z"
    assert event["roi_signed_on"] is None
    assert event["roi_expires_on"] is None
    advance_clock("2026-08-02T00:00:01Z")

    response = decide_disclosure(officer, event["id"], "RELEASE")

    decided = validate_success(response, 200)
    assert decided["status"] == "RELEASED"
    assert decided["suppressed_field_keys"] == []
    assert decided["released_field_keys"] == [
        "legal_name",
        "shelter_street_address",
        "hotline_call_transcript",
    ]
    assert decided["decided_at"] == "2026-08-02T00:00:01.000Z"
    assert decided["decided_by_staff_id"] == officer.id
    assert decided["late_filed"] is True


def test_denying_an_export_seals_a_client_who_was_only_heightened():
    """The sealing predicate wins over the imminent band it is evaluated ahead of.

    PRD: "It takes one of three values — `NORMAL`, `HEIGHTENED` or `SEALED` — and the
    derivation is evaluated strictly in that reverse order of severity, so that a client who
    qualifies for more than one posture always lands on the most protective."

    PRD: "A client is `SEALED` when either of two conditions holds: at least one of that
    client's shelter admissions currently has a `location_security_status` of `COMPROMISED`, or
    at least one of that client's disclosure events of kind `HMIS_EXPORT` currently sits in
    status `DENIED`."

    PRD: "`released_field_keys` stays an empty array and `suppressed_field_keys` receives
    **every** requested key, again in vocabulary order — a denial is recorded as total
    suppression rather than as an absence of data."

    Design: Corner/calculations/sealed_posture_outranks_heightened_when_both_conditions_hold
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    officer = seed_privacy_officer("Opal Reed", max_caseload=12)
    client, _call, assessment = seed_imminent_client(
        advocate,
        client_code="C-3007",
        legal_name="Gwen Halle",
        household_size=2,
        minor_children_count=0,
        accessibility_required=False,
        location_confidential=True,
        hmis_disclosure_consent="DENIED",
    )
    assert assessment["base_subtotal"] == 92.0
    assert assessment["escalation_multiplier"] == 1.25
    assert assessment["danger_score"] == 100.0
    before = read_client(client["id"])
    assert before["current_risk_band"] == "IMMINENT"
    assert before["confidentiality_posture"] == "HEIGHTENED"
    event = seed_disclosure_event(
        officer,
        client["id"],
        advocate.id,
        "HMIS_EXPORT",
        ["client_code", "household_size"],
        requester_org="Regional Continuum of Care",
    )

    response = decide_disclosure(
        officer,
        event["id"],
        "DENY",
        denial_reason="No signed consent for homeless-data-system participation.",
    )

    denied = validate_success(response, 200)
    assert denied["status"] == "DENIED"
    assert denied["released_field_keys"] == []
    assert denied["suppressed_field_keys"] == ["client_code", "household_size"]
    sealed = read_client(client["id"])
    assert sealed["confidentiality_posture"] == "SEALED"
    assert sealed["current_risk_band"] == "IMMINENT"
    assert sealed["hmis_disclosure_consent"] == "DENIED"
    assert sealed["protective_order_active"] is False
