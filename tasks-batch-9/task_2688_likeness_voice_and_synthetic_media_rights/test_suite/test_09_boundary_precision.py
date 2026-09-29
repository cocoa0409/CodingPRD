"""Two boundaries that close on the value itself: 0.7500 and the removal day."""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

AT_THRESHOLD_DETECTION = {
    "suspect_url": "https://pirate.example/at-threshold",
    "detected_view_count": 6_000_000,
    "match_confidence": 0.925,
}

BELOW_THRESHOLD_DETECTION = {
    "suspect_url": "https://pirate.example/below-threshold",
    "detected_view_count": 6_000_000,
    "match_confidence": 0.920,
}


def _two_cases_astride_the_threshold():
    """One CLEAR living talent and two detections differing only in confidence."""
    scenario = fixtures.register_state_law_profile(overrides=fixtures.CAMPAIGN_PROFILE)
    fixtures.register_union_minimum(scenario, fixtures.SAG_ADVERTISING_ROW)
    fixtures.create_talent(scenario, fixtures.CAMPAIGN_TALENT)
    fixtures.open_case(scenario, AT_THRESHOLD_DETECTION)
    at_threshold = scenario["case"]
    fixtures.open_case(scenario, BELOW_THRESHOLD_DETECTION)
    below_threshold = scenario["case"]
    return scenario, at_threshold, below_threshold


def _dismiss(scenario, case):
    """Send a DISMISS at one case without asserting the outcome."""
    return api_client.triage_infringement_case(
        case["id"], factories.triage_payload("DISMISS"), scenario["compliance_headers"]
    )


def test_a_score_of_exactly_seven_five_zero_zero_may_not_be_dismissed():
    """0.7500 refuses the dismissal, 0.7470 on the same facts accepts it.

    The PRD states: "A confidence of 0.925 with six million views against a
    `CLEAR` talent gives 0.5550 plus 0.1500 plus 0.0450, exactly 0.7500. A
    confidence of 0.920 on the same facts gives 0.7470." The bar closes on the
    score itself: "A case whose `severity_score` is at or above 0.7500 may not be
    dismissed at all — the only permitted decision is `ISSUE_TAKEDOWN` — and the
    attempt is refused with `ERR_TAKEDOWN_MANDATORY`. That threshold is inclusive
    on the high side, so the worked case that scores exactly 0.7500 is already
    mandatory." The permitted dismissal lands where the PRD says it does: "A
    `DISMISS` where no license is matched, or where the matched license is no
    longer distributable, means there is nothing to license and nothing worth
    pursuing, and the case moves `DETECTED → DISMISSED_NO_ACTION` with
    `closure_outcome` recorded as `BELOW_ENFORCEMENT_THRESHOLD`." The refused case
    keeps the state it was opened in: "A new case is `DETECTED` with
    `legal_hold_applied_count` at zero and `triaged_by_user_id`,
    `escalated_by_user_id`, `closed_by_user_id`, `takedown_issued_at` and
    `closure_outcome` all null."

    Design: Difficulty/boundary_precision_check/severity_score_exactly_at_mandatory_takedown_threshold
    """
    scenario, at_threshold, below_threshold = _two_cases_astride_the_threshold()
    assert at_threshold["severity_score"] == 0.7500
    assert below_threshold["severity_score"] == 0.7470

    validate_error(_dismiss(scenario, at_threshold), "ERR_TAKEDOWN_MANDATORY")
    dismissed = validate_success(_dismiss(scenario, below_threshold), 200)

    assert dismissed["status"] == "DISMISSED_NO_ACTION"
    assert dismissed["closure_outcome"] == "BELOW_ENFORCEMENT_THRESHOLD"

    refused = fixtures.refresh_case(scenario, at_threshold)
    assert refused["status"] == "DETECTED"
    assertions.assert_fields_null(refused, "closure_outcome", "triaged_by_user_id")


def test_the_mandatory_case_still_accepts_the_one_decision_left_to_it():
    """The refused case takes ISSUE_TAKEDOWN, stamped at the untouched clock.

    The PRD states: "A successful takedown moves the case `DETECTED →
    TAKEDOWN_ISSUED`, stamps `takedown_issued_at` with the logical instant and
    records `triaged_by_user_id`." The instant is the startup default because no
    caller has moved the clock: "Before any caller moves it, the logical clock
    reads exactly `2026-08-01T00:00:00Z`; that is the fixed startup default, and
    the server never falls back to real time."

    Design: Difficulty/boundary_precision_check/severity_score_exactly_at_mandatory_takedown_threshold
    """
    scenario, at_threshold, _below_threshold = _two_cases_astride_the_threshold()
    validate_error(_dismiss(scenario, at_threshold), "ERR_TAKEDOWN_MANDATORY")

    issued = fixtures.triage_case(scenario, "ISSUE_TAKEDOWN", at_threshold)

    assert issued["status"] == "TAKEDOWN_ISSUED"
    assert issued["takedown_issued_at"] == "2026-08-01T00:00:00Z"
    assert issued["triaged_by_user_id"] == scenario["compliance_user_id"]
    assert issued["severity_score"] == 0.7500


def test_neither_dismissal_turned_on_the_unenforceability_carve_out():
    """Both cases are enforceable in the use state, so only the score decided.

    The PRD states: "One carve-out keeps such a case from becoming unresolvable:
    a case whose `enforceable_under_use_state` is false remains dismissible at any
    severity, because no takedown could issue in the detected state anyway." For a
    living performer that carve-out cannot apply: "`enforceable_under_use_state`
    is true when the talent is `LIVING`, and for a `DECEASED` talent is true only
    when `use_state_rights_until` is non-null and at or after the current logical
    instant."

    Design: Difficulty/boundary_precision_check/severity_score_exactly_at_mandatory_takedown_threshold
    """
    scenario, at_threshold, below_threshold = _two_cases_astride_the_threshold()

    assert fixtures.read_talent(scenario)["life_status"] == "LIVING"
    for case in (at_threshold, below_threshold):
        assert case["enforceable_under_use_state"] is True
        assert case["use_state_rights_until"] is None


LONG_RETENTION = {"biometric_retention_max_days": 3650}

TWO_YEAR_GRANT = {
    "effective_until": "2028-08-01T00:00:00Z",
    "permitted_use_notes": "Two year voice campaign",
}

WINDOW_CLOSING_IN_JULY = {"distribution_end": "2027-07-01T00:00:00Z"}


def _obligation_raised_on_the_second_of_august():
    """A LIVE licence whose window closed in July, swept on 2 August 2027.

    The retention ceiling is ten years and the grant runs to 2028, so phases one,
    four and five have nothing to move and the counts isolate the boundary.
    """
    scenario = fixtures.campaign_live_license(
        license_overrides=WINDOW_CLOSING_IN_JULY,
        profile_overrides=LONG_RETENTION,
        grant_overrides=TWO_YEAR_GRANT,
    )
    fixtures.move_clock("2027-08-02T00:00:00Z", scenario["admin_headers"])
    scenario["phase_two_report"] = fixtures.run_sweep(
        scenario, scenario["compliance_headers"]
    )
    return scenario


def _talent_cases(scenario):
    """Every case standing against the scenario's talent."""
    response = api_client.list_infringement_cases(
        scenario["compliance_headers"],
        params={"talent_id": scenario["talent"]["id"], "limit": 100},
    )
    data, _meta = validate_paginated(response)
    return data


def test_phase_two_dates_the_deadline_from_the_sweep_and_moves_nothing_else():
    """The closed window raises one obligation due fourteen days later.

    The PRD states: "Phase two opens removal obligations on expired licenses:
    every license whose `distribution_status` is `ISSUED` or `LIVE` and whose
    `distribution_end` is strictly earlier than the current logical instant moves
    to `REMOVAL_PENDING` with `removal_reason` of `TERM_EXPIRED` and a fresh
    `removal_deadline`." The deadline is dated from the sweep, not from the window:
    "In every case `removal_deadline` is computed as the current logical instant
    advanced by the domicile profile's `removal_window_days`: an obligation raised
    on 2 August 2027 for a talent in a state allowing fourteen days gives a
    deadline of `2027-08-16T00:00:00Z`, and the same obligation for a talent in a
    state allowing twenty-one days gives `2027-08-23T00:00:00Z`."

    Design: Difficulty/boundary_precision_check/removal_deadline_day_boundary_in_sweep_phase_three
    """
    scenario = _obligation_raised_on_the_second_of_august()

    assertions.assert_sweep_counts(
        scenario["phase_two_report"], expired_license_count=1, removal_pending_count=1
    )

    license_row = fixtures.refresh_license(scenario)
    assert license_row["distribution_status"] == "REMOVAL_PENDING"
    assert license_row["removal_reason"] == "TERM_EXPIRED"
    assert license_row["removal_deadline"] == "2027-08-16T00:00:00Z"


def test_equality_with_the_deadline_is_read_in_the_licensees_favour():
    """A sweep at the deadline instant finds nothing; one day later finds one.

    The PRD states: "Phase three punishes overdue removals. Every license whose
    `distribution_status` is `REMOVAL_PENDING`, whose `removal_deadline` is
    strictly earlier than the current logical instant, and whose
    `removal_confirmed_at` is still null has its `compliance_status` set to
    `NON_COMPLIANT` while its `distribution_status` stays exactly at
    `REMOVAL_PENDING` — this is the phase that demonstrates the two dimensions are
    genuinely independent. A sweep running at exactly the deadline instant does not
    mark the license non-compliant; a sweep one day later does."

    Design: Difficulty/boundary_precision_check/removal_deadline_day_boundary_in_sweep_phase_three
    """
    scenario = _obligation_raised_on_the_second_of_august()

    fixtures.move_clock("2027-08-16T00:00:00Z", scenario["admin_headers"])
    on_the_deadline = fixtures.run_sweep(scenario, scenario["compliance_headers"])
    assertions.assert_sweep_changed_nothing(on_the_deadline)

    untouched = fixtures.refresh_license(scenario)
    assert untouched["compliance_status"] == "VERIFIED"
    assert untouched["distribution_status"] == "REMOVAL_PENDING"

    fixtures.move_clock("2027-08-17T00:00:00Z", scenario["admin_headers"])
    one_day_late = fixtures.run_sweep(scenario, scenario["compliance_headers"])
    assertions.assert_sweep_counts(
        one_day_late, overdue_removal_count=1, opened_case_count=1
    )

    overdue = fixtures.refresh_license(scenario)
    assert overdue["compliance_status"] == "NON_COMPLIANT"
    assert overdue["distribution_status"] == "REMOVAL_PENDING"
    assert overdue["removal_confirmed_at"] is None


def test_the_overdue_sweep_opens_one_case_and_a_repeat_run_opens_no_second():
    """The auto-opened case copies the licence, and the second pass is inert.

    The PRD states: "Each such license also causes a fresh infringement case to be
    opened automatically, with `detection_source` of `SWEEP`, a `match_confidence`
    of 1.000, `suspect_url` copied from the license's `distribution_reference`,
    `detected_state_code` taken from the talent's `domicile_state_code`,
    `detected_channel` taken from the license's `channel`, and
    `matched_usage_license_id` naming that license." Its score is the one the PRD
    works: "the sweep-opened case scoring 0.6900 clears that floor while the 0.3550
    case does not." Re-running the sweep adds nothing: "Running it twice at the same
    logical instant changes nothing on the second pass — every phase's precondition
    is already false for the rows the first pass moved."

    Design: Difficulty/boundary_precision_check/removal_deadline_day_boundary_in_sweep_phase_three
    """
    scenario = _obligation_raised_on_the_second_of_august()
    fixtures.move_clock("2027-08-16T00:00:00Z", scenario["admin_headers"])
    fixtures.run_sweep(scenario, scenario["compliance_headers"])
    fixtures.move_clock("2027-08-17T00:00:00Z", scenario["admin_headers"])
    fixtures.run_sweep(scenario, scenario["compliance_headers"])

    cases = _talent_cases(scenario)
    assert len(cases) == 1
    assertions.assert_subset_equal(
        cases[0],
        {
            "detection_source": "SWEEP",
            "match_confidence": 1.000,
            "suspect_url": "spot-ref-001",
            "detected_channel": "ADVERTISING",
            "detected_state_code": scenario["talent"]["domicile_state_code"],
            "matched_usage_license_id": scenario["license"]["id"],
            "severity_score": 0.6900,
        },
    )

    second_pass = fixtures.run_sweep(scenario, scenario["compliance_headers"])
    assertions.assert_sweep_changed_nothing(second_pass)
    assert len(_talent_cases(scenario)) == 1
