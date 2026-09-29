"""Arithmetic coverage: intervals, input-set filters, caps, tables, thresholds.

Each probe drives one formula to a literal: the 180-day high-risk review clock, a
window whose input set excludes the firing sitting exactly on its exclusive end,
two caps clipping the same ledger by different routes, the minute table read
through a snapshot, the delta weight table with its contraindication bonus, and
the sweep comparison one second either side of a due date.
"""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# The review schedule interval
# ---------------------------------------------------------------------------


POTASSIUM_REQUEST = {
    "title": "Potassium hard stop",
    "clinical_domain": "CRITICAL_CARE",
    "urgency": "SAFETY_URGENT",
    "evidence_grade": "A",
    "patient_safety_flag": True,
    "evidence_citations": [
        factories.build_citation("ISMP high alert list 2024", True),
        factories.build_citation("NEJM hyperkalemia 2019", True),
    ],
}

POTASSIUM_ALERT = {
    "name": "Potassium hard stop",
    "severity_tier": "TIER_1_HARD_STOP",
    "override_reason_codes": ["CLINICAL_JUDGMENT", "PATIENT_SPECIFIC_PLAN"],
    "hard_stop_justification": "Fatal arrhythmia risk documented in ISMP list",
    "firing_criteria": {
        "trigger_event": "ORDER_ENTRY",
        "expression": "potassium_iv_rate > 10",
    },
}


def test_activating_a_hard_stop_uses_the_180_day_clock_and_no_archive_date(committee):
    """The tier decides the interval, and an alert has no archival date at all.

    "`review_due_date` is the current instant plus the review interval for the
    alert's risk class, where an alert counts as `HIGH` risk when its
    `severity_tier` is `TIER_1_HARD_STOP` and `STANDARD` otherwise; `expiration_at`
    is that date plus the 30-day grace period. Alerts have no
    `archive_eligible_at`. An annual review task with `artifact_kind` `ALERT`,
    `state` `PENDING` and `cycle_index` 1 is created, and the parent request closes
    as `CLOSED_IMPLEMENTED` if its `request_type` is now satisfied." "a `STANDARD`
    artifact is reviewed 365 days after its anchor instant, a `HIGH` artifact after
    180 days."

    Design: Corner/calculations/calc_alert_activation_applies_the_180_day_high_risk_review_interval
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_approved_alert(
        committee,
        request_overrides=POTASSIUM_REQUEST,
        alert_overrides=POTASSIUM_ALERT,
    )
    alert_id = scenario["alert"]["id"]
    assert scenario["alert"]["required_approval_votes"] == 3
    assertions.assert_alert_states(scenario["alert"], "APPROVED", "UNPUBLISHED")

    # the anchor is the clock at activation, not the design instant of the alert
    fixtures.set_clock("2026-09-01T00:00:00Z")
    activated = validate_success(
        api_client.activate_alert(
            alert_id,
            factories.build_activation_payload(
                activation_note="Go live after committee sign-off"
            ),
            committee["chair_headers"],
        )
    )

    assertions.assert_alert_states(activated, "APPROVED", "ACTIVE")
    assertions.assert_review_schedule(
        activated, "2027-02-28T00:00:00Z", "2027-03-30T00:00:00Z"
    )
    assert "archive_eligible_at" not in activated

    tasks, meta = validate_paginated(
        api_client.list_annual_review_tasks(
            committee["chair_headers"], {"alert_id": alert_id}
        )
    )
    assert meta["total_count"] == 1
    assert tasks[0]["state"] == "PENDING"
    assert tasks[0]["artifact_kind"] == "ALERT"
    assert tasks[0]["cycle_index"] == 1
    assert tasks[0]["review_due_date"] == "2027-02-28T00:00:00Z"

    request = fixtures.read_request(committee, scenario["content_request"]["id"])
    assert request["status"] == "CLOSED_IMPLEMENTED"


# ---------------------------------------------------------------------------
# The burden window input set and its caps
# ---------------------------------------------------------------------------


LACTATE_ALERT_REQUEST = {
    "title": "Lactate follow-up alert",
    "clinical_domain": "HOSPITAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "evidence_citations": [
        factories.build_citation("Surviving Sepsis 2021", True),
        factories.build_citation("JAMA sepsis bundles 2018", True),
    ],
}

LACTATE_ALERT = {
    "name": "Repeat lactate reminder",
    "severity_tier": "TIER_2_INTERRUPTIVE",
    "override_reason_codes": ["CLINICAL_JUDGMENT", "PATIENT_REFUSED"],
    "firing_criteria": {
        "trigger_event": "LAB_RESULT",
        "expression": "lactate > 2.0 and no_repeat_in_6h",
    },
}


def _close(committee, alert_id, window_id):
    return validate_success(
        api_client.close_burden_window(
            alert_id,
            window_id,
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            fixtures.ADMIN_HEADERS,
        )
    )


def test_the_firing_landing_exactly_on_window_end_is_left_for_the_next_window(committee):
    """Four firings, three counted: the exclusive end drops the last one.

    "The interval is half-open: `window_start` is inclusive, `window_end` is
    exclusive, and a firing whose `fired_at` equals `window_end` belongs to the
    *next* window." "The input set for every computation is the alert's firing
    records whose `fired_at` is at or after `window_start` and strictly before
    `window_end`; firings of the same alert outside that interval are excluded."
    "`unwindowed_fire_count` is always `lifetime_fire_count` minus
    `windowed_fire_count`".

    Design: Corner/calculations/calc_burden_window_excludes_the_firing_at_exactly_window_end
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee,
        request_overrides=LACTATE_ALERT_REQUEST,
        alert_overrides=LACTATE_ALERT,
    )
    alert_id = scenario["alert"]["id"]

    batch = fixtures.ingest_firings(
        alert_id,
        "2026-08-02T00:00:00Z",
        fire_count=4,
        override_count=4,
        distinct_clinician_count=2,
        interval_seconds=3600,
        override_reason_code="CLINICAL_JUDGMENT",
    )
    assert batch["created_event_count"] == 4
    # the fourth firing lands exactly on the boundary chosen below
    assert batch["last_fired_at"] == "2026-08-02T03:00:00Z"

    window = fixtures.open_window(
        committee, alert_id, "2026-08-02T00:00:00Z", "2026-08-02T03:00:00Z"
    )
    closed = _close(committee, alert_id, window["id"])

    assertions.assert_burden_window_counts(closed, 3, 3, 0, 2, 2)
    # 3/3 overridden, round(3/50, 4) volume, tier multiplier 1.0 for TIER_2
    assertions.assert_burden_computation(closed, 1.0000, 0.0600, 6.00, 10.00, "HIGH_VALUE")
    assertions.assert_classification_from_index(closed)

    alert = fixtures.read_alert(committee, alert_id)
    # the excluded fourth firing stays on the unwindowed side of the ledger
    assertions.assert_firing_ledger(alert, 4, 3, 1)
    assertions.assert_firing_ledger_identity(alert)


def test_a_flood_of_firings_is_clipped_by_the_volume_and_index_caps(committee):
    """Both variants land on 100.00, arriving there by different arithmetic.

    "Its `volume_factor` is `fire_count` divided by an expected 50 firings per
    window, rounded half-up to four decimal places, then capped at 2.0. ...
    `burden_index` is then `override_rate` multiplied by the tier multiplier
    multiplied by `volume_factor` multiplied by 100, rounded half-up to two decimal
    places, and finally capped at 100.00." "Its volume factor is
    `distinct_fired_clinician_count` divided by an expected 20 clinicians per
    window, rounded half-up to four decimal places, then capped at 2.0." "if
    `burden_index` is at least 65.00 it is `LOW_VALUE`".

    Design: Corner/calculations/calc_burden_index_applies_the_volume_factor_and_index_caps
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee,
        request_overrides={**LACTATE_ALERT_REQUEST, "title": "Nuisance duplicate order alert"},
        alert_overrides={
            **LACTATE_ALERT,
            "name": "Duplicate order nag",
            "firing_criteria": {
                "trigger_event": "ORDER_ENTRY",
                "expression": "duplicate_within_24h",
            },
        },
    )
    alert_id = scenario["alert"]["id"]

    fixtures.ingest_firings(
        alert_id,
        "2026-08-02T00:00:00Z",
        fire_count=120,
        override_count=120,
        distinct_clinician_count=30,
        interval_seconds=3600,
        override_reason_code="CLINICAL_JUDGMENT",
    )
    window = fixtures.open_window(
        committee, alert_id, "2026-08-02T00:00:00Z", "2026-08-07T00:00:00Z"
    )
    fixtures.set_clock("2026-08-07T00:00:00Z")

    closed = _close(committee, alert_id, window["id"])

    assertions.assert_burden_window_counts(closed, 120, 120, 0, 30, 30)
    # round(120/50, 4) is 2.4000 before the factor cap; 200.00 before the index cap
    assertions.assert_burden_computation(
        closed, 1.0000, 2.0000, 100.00, 100.00, "LOW_VALUE"
    )
    assertions.assert_classification_from_index(closed)

    alert = fixtures.read_alert(committee, alert_id)
    assertions.assert_numeric_equals(alert["latest_burden_index"], 100.00, 2)
    assert alert["latest_burden_classification"] == "LOW_VALUE"


# ---------------------------------------------------------------------------
# The reviewer minute table, read through a snapshot
# ---------------------------------------------------------------------------


HEPARIN_REQUEST = {
    "title": "Heparin infusion order set",
    "request_type": "ORDER_SET",
    "clinical_domain": "CARDIOLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("CHEST 2020 anticoagulation", True),
        factories.build_citation("ISMP heparin safety 2022", True),
    ],
}


def test_a_high_alert_line_prices_the_peer_review_at_thirty_five_minutes(committee):
    """The high-alert item makes the build HIGH, and the debit follows the snapshot.

    "Step one determines `risk_class`: `HIGH` when the order set's
    `high_alert_item_count` is at least 1 or the parent request's
    `patient_safety_flag` is true, `STANDARD` otherwise. Step two takes the base
    vote requirement from that class — 3 votes for `HIGH`, 2 for `STANDARD`." "An
    order-set peer review costs 20 minutes on a `STANDARD` build and 35 on a `HIGH`
    one". "The assignment opens in state `ASSIGNED` with `vote`, `comment`,
    `cast_at`, `withdrawal_reason` and `void_reason` null and `evidence_concern`
    false."

    Design: Corner/calculations/calc_review_assignment_minutes_use_the_high_risk_class_snapshot
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_order_set_in_peer_review(
        committee,
        request_overrides=HEPARIN_REQUEST,
        order_set_overrides={"name": "Heparin infusion v1", "specialty": "CARDIOLOGY"},
        item_payloads=[factories.build_high_alert_item_payload(sequence_index=1)],
    )
    submitted = scenario["order_set"]
    assert submitted["high_alert_item_count"] == 1
    assert submitted["risk_class"] == "HIGH"
    assert submitted["peer_required_votes"] == 3

    reviewer = committee["peers"][0]
    assignment = validate_success(
        api_client.create_review_assignment(
            factories.build_review_assignment_payload(
                reviewer["id"],
                "PEER_REVIEW",
                order_set_id=submitted["id"],
                due_at="2026-08-08T00:00:00Z",
            ),
            committee["chair_headers"],
        ),
        201,
    )

    assert assignment["risk_class_snapshot"] == "HIGH"
    assert assignment["estimated_minutes"] == 35
    assertions.assert_order_set_review_minutes(assignment, "PEER_REVIEW", "HIGH")
    assert assignment["state"] == "ASSIGNED"
    assert assignment["vote"] is None
    assert assignment["evidence_concern"] is False
    assert assignment["due_at"] == "2026-08-08T00:00:00Z"

    debited = validate_success(
        api_client.get_clinician(reviewer["id"], committee["chair_headers"])
    )
    assertions.assert_workload_ledger(debited, 35, 445, 1)


# ---------------------------------------------------------------------------
# The delta weight table and its fork threshold
# ---------------------------------------------------------------------------


def test_one_contraindicated_delta_earns_the_bonus_without_forcing_review(committee):
    """Nine plus three plus three is fifteen, which still fast-tracks the release.

    "On creation the server assigns the delta's `weight` from its `change_type` — 5
    for `SEVERITY_INCREASED`, 3 for `NEW_INTERACTION`, 3 for
    `DOSING_BOUND_CHANGED`, 2 for `RETIRED_INTERACTION`, 1 for
    `SEVERITY_DECREASED` — plus a bonus of 4 when `new_severity` is
    `CONTRAINDICATED`." "`impact_score` is the sum, over every delta of the
    release, of that delta's weight ... A score below 25 routes it `RECEIVED →
    IMPACT_ANALYZED_FAST_TRACK`".

    Design: Corner/calculations/calc_vendor_impact_score_adds_the_contraindicated_severity_bonus
    """
    fixtures.reset_clock()
    release = fixtures.create_release(
        committee,
        vendor_name="Medisafe",
        release_label="2026.09",
        content_domain="DRUG_INTERACTION",
        received_at="2026-08-01T00:00:00Z",
    )
    assert release["review_cycle_state"] == "RECEIVED"
    assert release["impact_score"] is None

    severity_raised = fixtures.add_delta(
        committee,
        release["id"],
        rule_code="DDI-1001",
        change_type="SEVERITY_INCREASED",
        description="Warfarin plus fluconazole raised to contraindicated",
        drug_pair="warfarin|fluconazole",
        new_severity="CONTRAINDICATED",
        prior_severity="MAJOR",
    )
    new_interaction = fixtures.add_delta(
        committee,
        release["id"],
        rule_code="DDI-1002",
        change_type="NEW_INTERACTION",
        description="New major interaction",
        drug_pair="amiodarone|simvastatin",
        new_severity="MAJOR",
    )
    dosing_change = fixtures.add_delta(
        committee,
        release["id"],
        rule_code="DOSE-2001",
        change_type="DOSING_BOUND_CHANGED",
        description="Vancomycin renal bound tightened",
        new_severity="MODERATE",
    )
    # 5 for the change type plus the 4-point contraindication bonus
    assert severity_raised["weight"] == 9
    assert new_interaction["weight"] == 3
    assert dosing_change["weight"] == 3

    analysed = validate_success(
        api_client.run_vendor_release_impact_analysis(
            release["id"],
            factories.build_impact_analysis_payload(
                analysis_note="Quarterly interaction refresh"
            ),
            committee["pharmacist_headers"],
        )
    )

    assert analysed["impact_score"] == 15
    assert analysed["review_cycle_state"] == "IMPACT_ANALYZED_FAST_TRACK"
    assert analysed["delta_count"] == 3
    assert analysed["contraindicated_delta_count"] == 1
    assert analysed["dispositioned_delta_count"] == 0
    assert analysed["restaged_order_set_count"] == 0


# ---------------------------------------------------------------------------
# The sweep's threshold comparison
# ---------------------------------------------------------------------------


SEPSIS_REQUEST = {
    "title": "Sepsis bundle order set",
    "request_type": "ORDER_SET",
    "clinical_domain": "HOSPITAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("Surviving Sepsis 2021", True),
        factories.build_citation("JAMA sepsis bundles 2018", True),
    ],
}


def test_the_sweep_flips_the_task_on_the_due_date_and_not_a_second_before(committee):
    """23:59:59 moves nothing; the due instant itself moves both records.

    "So `review_due_date` is the anchor plus the interval for the artifact's
    `risk_class`, `expiration_at` is `review_due_date` plus a 30-day grace period,
    and `archive_eligible_at` is `expiration_at` plus a further 90 days." "A task
    in state `PENDING` whose `review_due_date` the clock has reached moves `PENDING
    → OVERDUE`, and because that task became overdue, the order set it governs
    moves `publication_state` `PUBLISHED → EXPIRING`".

    Design: Corner/calculations/calc_expiration_sweep_at_exactly_review_due_date_flips_the_task_overdue
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_published_order_set(
        committee,
        "2026-08-15T00:00:00Z",
        request_overrides=SEPSIS_REQUEST,
        order_set_overrides={"name": "Sepsis bundle v1", "specialty": "HOSPITAL_MEDICINE"},
        item_payloads=[
            factories.build_order_set_item_payload(
                orderable_code="LAB-LACT", sequence_index=1
            )
        ],
    )
    order_set_id = scenario["order_set"]["id"]
    assert scenario["order_set"]["risk_class"] == "STANDARD"
    assertions.assert_review_schedule(
        scenario["order_set"],
        "2027-08-15T00:00:00Z",
        "2027-09-14T00:00:00Z",
        "2027-12-13T00:00:00Z",
    )

    fixtures.set_clock("2027-08-14T23:59:59Z")
    early = validate_success(
        api_client.run_expiration_sweep(
            factories.build_expiration_sweep_payload(dry_run=False),
            committee["chair_headers"],
        )
    )
    # one second before the due date the comparison has not been reached
    assertions.assert_all_sweep_counts_zero(early)

    fixtures.set_clock("2027-08-15T00:00:00Z")
    swept = validate_success(
        api_client.run_expiration_sweep(
            factories.build_expiration_sweep_payload(dry_run=False),
            committee["chair_headers"],
        )
    )
    assertions.assert_sweep_counts(
        swept,
        tasks_marked_overdue=1,
        order_sets_marked_expiring=1,
        tasks_expired=0,
        order_sets_expired=0,
    )

    tasks, meta = validate_paginated(
        api_client.list_annual_review_tasks(
            committee["chair_headers"], {"order_set_id": order_set_id}
        )
    )
    assert meta["total_count"] == 1
    assert tasks[0]["state"] == "OVERDUE"
    assertions.assert_order_set_states(
        fixtures.read_order_set(committee, order_set_id), "APPROVED", "EXPIRING"
    )
