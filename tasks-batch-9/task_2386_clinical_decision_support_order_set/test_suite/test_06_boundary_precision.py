"""Thresholds probed one unit either side of the line.

The first pair moves a single firing across the retirement floor while holding the
stored burden index byte-identical, so the count is the only discriminator. The
second pair sits on the empty-input-set edge of the classification ladder, where a
zero index must not be mistaken for a cheap high-value alert.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# The 40-firing retirement floor
# ---------------------------------------------------------------------------


RENAL_REQUEST = {
    "title": "Renal dosing interruptive alert",
    "request_type": "ALERT",
    "clinical_domain": "NEPHROLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("KDIGO 2025", True),
        factories.build_citation("AJKD 2025;85:12", True),
    ],
}

RENAL_ALERT = {
    "name": "Renal dose adjustment required",
    "severity_tier": "TIER_2_INTERRUPTIVE",
    "override_reason_codes": ["CLINICALLY_APPROPRIATE", "DOSE_ALREADY_ADJUSTED"],
    "firing_criteria": {
        "trigger_event": "NEW_MEDICATION_ORDER",
        "expression": "eGFR < 30 AND new_order(renally_cleared_drug)",
    },
}


def _two_candidate_windows_one_firing_short(committee):
    """An ACTIVE alert with a qualifying window and a second window at 39 firings."""
    fixtures.reset_clock()
    scenario = fixtures.setup_approved_alert(
        committee, request_overrides=RENAL_REQUEST, alert_overrides=RENAL_ALERT
    )
    alert_id = scenario["alert"]["id"]

    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario["alert"] = fixtures.activate_alert(committee, alert_id)

    scenario["batch_one"] = fixtures.ingest_firings(
        alert_id,
        "2026-09-01T00:00:00Z",
        fire_count=40,
        override_count=36,
        distinct_clinician_count=10,
        interval_seconds=3600,
        override_reason_code="CLINICALLY_APPROPRIATE",
    )
    scenario["first_window"] = fixtures.open_window(
        committee, alert_id, "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z"
    )

    scenario["batch_two"] = fixtures.ingest_firings(
        alert_id,
        "2026-09-09T00:00:00Z",
        fire_count=39,
        override_count=36,
        distinct_clinician_count=10,
        interval_seconds=3600,
        override_reason_code="DOSE_ALREADY_ADJUSTED",
    )
    # opening the successor supersedes and closes the first window
    scenario["second_window"] = fixtures.open_window(
        committee, alert_id, "2026-09-08T00:00:00Z", "2026-09-15T00:00:00Z"
    )
    scenario["second_window"] = validate_success(
        api_client.close_burden_window(
            alert_id,
            scenario["second_window"]["id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            fixtures.ADMIN_HEADERS,
        )
    )
    return scenario


def test_a_candidate_window_one_firing_short_of_forty_fails_the_gate(committee):
    """39 firings refuse retirement even though the other two criteria pass.

    "The gate passes only when exactly two such candidate windows exist **and**
    every one of them satisfies all three of these conditions: its
    `override_rate` is at least 0.9000, its `fire_count` is at least 40, and its
    fire-weighted `burden_index` is at least 65.00." "When the gate fails ... the
    request is refused with `ERR_RETIREMENT_CRITERIA_NOT_MET` and the alert stays
    in its current `lifecycle_state`."

    Design: Difficulty/boundary_precision_check/boundary_retirement_gate_rejects_fire_count_39_and_accepts_40
    """
    scenario = _two_candidate_windows_one_firing_short(committee)
    alert_id = scenario["alert"]["id"]
    assert scenario["batch_one"]["created_event_count"] == 40
    assert scenario["batch_two"]["created_event_count"] == 39
    # 39 hourly firings from 2026-09-09 all fall inside the half-open successor
    assert scenario["batch_two"]["last_fired_at"] == "2026-09-10T14:00:00Z"

    windows = {w["id"]: w for w in fixtures.read_windows(committee, alert_id)}
    superseded = windows[scenario["first_window"]["id"]]
    assert superseded["state"] == "CLOSED"
    assert superseded["closure_reason"] == "SUPERSEDED_BY_NEW_WINDOW"
    assert superseded["fire_count"] == 40
    assertions.assert_numeric_equals(superseded["override_rate"], 0.9000, 4)
    assertions.assert_numeric_equals(superseded["burden_index"], 72.00, 2)

    short = scenario["second_window"]
    assert short["fire_count"] == 39
    assert short["override_count"] == 36
    # round(36 / 39, 4) and round(39 / 50, 4)
    assertions.assert_numeric_equals(short["override_rate"], 0.9231, 4)
    assertions.assert_numeric_equals(short["volume_factor"], 0.7800, 4)
    # round(0.9231 * 1.0 * 0.7800 * 100, 2) is round(72.0018, 2)
    assertions.assert_numeric_equals(short["burden_index"], 72.00, 2)
    assert short["burden_classification"] == "LOW_VALUE"

    refused = api_client.retire_alert(
        alert_id,
        factories.build_retire_payload(
            retirement_rationale="Two consecutive low-value windows"
        ),
        committee["chair_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_RETIREMENT_CRITERIA_NOT_MET, 409)

    alert = fixtures.read_alert(committee, alert_id)
    assertions.assert_alert_states(alert, "APPROVED", "ACTIVE")
    assertions.assert_firing_ledger(alert, 79, 79, 0)
    assert alert["retired_at"] is None


def test_the_fortieth_firing_earns_the_retirement_at_an_identical_index(committee):
    """One reopen and one late firing flip the same 72.00 window to eligible.

    "Reopening moves the window `CLOSED → OPEN`, resets `fire_count`,
    `override_count`, `accept_count`, `distinct_fired_clinician_count` and
    `distinct_overriding_clinician_count` to 0, resets `override_rate`,
    `volume_factor`, `burden_index`, ... and increments `reopen_count` by 1."
    "When retirement succeeds, `lifecycle_state` becomes `RETIRED` — a terminal
    state — and `retired_at` is set to the current instant. ... then every window
    of the alert in state `CLOSED` transitions to `FINALIZED`".

    Design: Difficulty/boundary_precision_check/boundary_retirement_gate_rejects_fire_count_39_and_accepts_40
    """
    scenario = _two_candidate_windows_one_firing_short(committee)
    alert_id = scenario["alert"]["id"]
    window_id = scenario["second_window"]["id"]

    reopened = validate_success(
        api_client.reopen_burden_window(
            alert_id,
            window_id,
            factories.build_reopen_window_payload(
                reopen_reason="One firing arrived late from the interface engine"
            ),
            fixtures.ADMIN_HEADERS,
        )
    )
    assertions.assert_window_reset(reopened, 1)

    late = fixtures.ingest_firings(
        alert_id,
        "2026-09-10T15:00:00Z",
        fire_count=1,
        override_count=0,
        distinct_clinician_count=1,
        interval_seconds=3600,
    )
    assert late["created_event_count"] == 1

    reclosed = validate_success(
        api_client.close_burden_window(
            alert_id,
            window_id,
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            fixtures.ADMIN_HEADERS,
        )
    )
    assert reclosed["fire_count"] == 40
    # the accepted firing leaves override_count at 36, so the index does not move
    assertions.assert_numeric_equals(reclosed["override_rate"], 0.9000, 4)
    assertions.assert_numeric_equals(reclosed["burden_index"], 72.00, 2)
    assert reclosed["reopen_count"] == 1

    retired = validate_success(
        api_client.retire_alert(
            alert_id,
            factories.build_retire_payload(
                retirement_rationale="Both windows now sit at the 40-firing floor"
            ),
            committee["chair_headers"],
        )
    )
    assertions.assert_alert_states(retired, "APPROVED", "RETIRED")
    # the logical clock has not advanced since activation
    assert retired["retired_at"] == "2026-09-01T00:00:00Z"

    windows = fixtures.read_windows(committee, alert_id)
    assert len(windows) == 2
    assert {w["state"] for w in windows} == {"FINALIZED"}


# ---------------------------------------------------------------------------
# The empty-input-set edge of the classification ladder
# ---------------------------------------------------------------------------


FALL_REQUEST = {
    "title": "Fall risk passive reminder",
    "request_type": "ALERT",
    "clinical_domain": "GERIATRICS",
    "urgency": "ROUTINE",
    "evidence_grade": "C",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("JAGS 2025;73:401", True),
        factories.build_citation("Unit fall audit 2025", False),
    ],
}

FALL_ALERT = {
    "name": "Fall risk reminder",
    "severity_tier": "TIER_3_PASSIVE",
    "override_reason_required": False,
    "firing_criteria": {
        "trigger_event": "NURSING_ASSESSMENT_FILED",
        "expression": "morse_score >= 45 AND no_fall_precautions_order",
    },
}


def _window_that_contains_no_firings(committee):
    """Ten September firings and one OPEN October window that excludes them all."""
    fixtures.reset_clock()
    scenario = fixtures.setup_approved_alert(
        committee, request_overrides=FALL_REQUEST, alert_overrides=FALL_ALERT
    )
    alert_id = scenario["alert"]["id"]

    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario["alert"] = fixtures.activate_alert(committee, alert_id)
    scenario["ingest"] = fixtures.ingest_firings(
        alert_id,
        "2026-09-01T00:00:00Z",
        fire_count=10,
        override_count=10,
        distinct_clinician_count=5,
        interval_seconds=3600,
    )
    scenario["window"] = fixtures.open_window(
        committee, alert_id, "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"
    )
    return scenario


def test_a_window_with_no_firings_classifies_as_no_signal_not_high_value(committee):
    """Zero firings yield a 0.00 index that the ladder must not call high value.

    "Its `override_rate` is `override_count` divided by `fire_count`, rounded
    half-up to four decimal places, and is 0.0000 when `fire_count` is 0."
    "`burden_classification` is derived from the fire-weighted `burden_index`
    alone, and the tests run in this order: if `fire_count` is 0 the
    classification is `NO_SIGNAL`; otherwise if `burden_index` is at least 65.00
    it is `LOW_VALUE`; otherwise if `burden_index` is at most 25.00 it is
    `HIGH_VALUE`".

    Design: Difficulty/boundary_precision_check/boundary_zero_firing_window_is_no_signal_not_high_value
    """
    scenario = _window_that_contains_no_firings(committee)
    assert scenario["ingest"]["created_event_count"] == 10
    assert scenario["ingest"]["last_fired_at"] == "2026-09-01T09:00:00Z"

    closed = validate_success(
        api_client.close_burden_window(
            scenario["alert"]["id"],
            scenario["window"]["id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            fixtures.ADMIN_HEADERS,
        )
    )

    assertions.assert_burden_window_counts(closed, 0, 0, 0, 0, 0)
    # the zero denominators are pinned values, not nulls and not division errors
    assertions.assert_burden_computation(closed, 0.0000, 0.0000, 0.00, 0.00, "NO_SIGNAL")
    assertions.assert_classification_from_index(closed)
    assert closed["severity_tier_snapshot"] == "TIER_3_PASSIVE"


def test_the_excluded_firings_stay_unwindowed_and_cannot_earn_retirement(committee):
    """The ten out-of-interval firings never reach the ledger's windowed column.

    "The input set for every computation is the alert's firing records whose
    `fired_at` is at or after `window_start` and strictly before `window_end`;
    firings of the same alert outside that interval are excluded."
    "`unwindowed_fire_count` is always `lifetime_fire_count` minus
    `windowed_fire_count`". "When the gate fails — because fewer than two closed
    windows exist ... the request is refused with
    `ERR_RETIREMENT_CRITERIA_NOT_MET`".

    Design: Difficulty/boundary_precision_check/boundary_zero_firing_window_is_no_signal_not_high_value
    """
    scenario = _window_that_contains_no_firings(committee)
    alert_id = scenario["alert"]["id"]

    validate_success(
        api_client.close_burden_window(
            alert_id,
            scenario["window"]["id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            fixtures.ADMIN_HEADERS,
        )
    )

    alert = fixtures.read_alert(committee, alert_id)
    assertions.assert_firing_ledger(alert, 10, 0, 10)
    assertions.assert_firing_ledger_identity(alert)
    assertions.assert_numeric_equals(alert["latest_burden_index"], 0.00, 2)
    assert alert["latest_burden_classification"] == "NO_SIGNAL"

    # a NO_SIGNAL window cannot be laundered into a retirement
    refused = api_client.retire_alert(
        alert_id,
        factories.build_retire_payload(retirement_rationale="Never fires in October"),
        committee["chair_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_RETIREMENT_CRITERIA_NOT_MET, 409)
    assertions.assert_alert_states(fixtures.read_alert(committee, alert_id), "APPROVED", "ACTIVE")
