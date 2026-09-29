"""Cascades whose later links are reachable only through the earlier ones.

Neither trigger payload names the records that end up mutated: one sweep call
walks a task to an order set to a linked alert to that alert's open window to the
alert's firing ledger, and one specialty vote walks an order set to its sibling
assignments to the reviewers' minute ledgers to a linked alert's review stage.
"""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_success,
)


# ---------------------------------------------------------------------------
# Five links from one sweep
# ---------------------------------------------------------------------------


SEPSIS_REQUEST = {
    "title": "Sepsis bundle order set and duplicate therapy alert",
    "request_type": "BOTH",
    "clinical_domain": "HOSPITAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
}

LACTATE_ITEM = {
    "orderable_code": "LACTATE",
    "display_name": "Serum lactate",
    "item_category": "LAB",
    "high_alert_medication": False,
}

LINKED_ALERT = {
    "name": "Duplicate anticoagulant",
    "severity_tier": "TIER_2_INTERRUPTIVE",
    "override_reason_codes": ["CLINICALLY_APPROPRIATE", "PATIENT_TOLERATES"],
    "firing_criteria": {
        "trigger_event": "NEW_MEDICATION_ORDER",
        "expression": "active_order(anticoagulant) AND new_order(anticoagulant)",
    },
}


def _published_pair_with_an_open_window(committee):
    """A published order set, an ACTIVE linked alert and one OPEN window of firings."""
    fixtures.reset_clock()
    scenario = fixtures.setup_published_order_set_with_linked_alert(
        committee,
        go_live_at="2026-08-15T00:00:00Z",
        request_overrides=SEPSIS_REQUEST,
        item_payloads=[LACTATE_ITEM],
        alert_overrides=LINKED_ALERT,
    )
    alert_id = scenario["alert"]["id"]
    fixtures.run_alert_approval_stage(committee, alert_id)

    # activate a month later so the alert's own schedule outlives the order set's
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario["alert"] = fixtures.activate_alert(committee, alert_id)
    scenario["ingest"] = fixtures.ingest_firings(
        alert_id,
        "2026-09-01T00:00:00Z",
        fire_count=40,
        override_count=36,
        distinct_clinician_count=10,
        interval_seconds=3600,
    )
    scenario["window"] = fixtures.open_window(
        committee, alert_id, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
    )
    return scenario


def test_one_sweep_expires_a_task_then_its_order_set_then_the_linked_alert(committee):
    """Links one to three: nothing in the sweep payload names the alert.

    "A task whose `expiration_at` the clock has reached moves to `EXPIRED`,
    either `OVERDUE → EXPIRED` or, when the sweep never saw the intermediate
    step, `PENDING → EXPIRED`; and because that task expired, the order set it
    governs moves to `publication_state` `EXPIRED`". "every alert whose
    `linked_order_set_id` names it and whose `lifecycle_state` is `ACTIVE` moves
    to `SUSPENDED` with `suspension_reason` recorded as
    `SOURCE_CONTENT_EXPIRED` and `suspension_count` incremented by 1".

    Design: Difficulty/transitive_cascade/cascade_expiration_sweep_task_to_order_set_to_alert_to_window_to_ledger
    """
    scenario = _published_pair_with_an_open_window(committee)
    order_set_id = scenario["order_set"]["id"]
    alert_id = scenario["alert"]["id"]
    assert scenario["ingest"]["created_event_count"] == 40
    assert scenario["ingest"]["last_fired_at"] == "2026-09-02T15:00:00Z"
    assert scenario["window"]["state"] == "OPEN"
    assertions.assert_review_schedule(
        scenario["alert"], "2027-09-01T00:00:00Z", "2027-10-01T00:00:00Z"
    )

    # exactly the order set's expiration_at, 90 days before it may be archived
    fixtures.set_clock("2027-09-14T00:00:00Z")
    sweep = validate_success(
        api_client.run_expiration_sweep(
            factories.build_expiration_sweep_payload(dry_run=False),
            committee["chair_headers"],
        )
    )
    assertions.assert_sweep_counts(
        sweep,
        tasks_expired=1,
        tasks_marked_overdue=1,
        order_sets_expired=1,
        order_sets_marked_expiring=0,
        order_sets_archived=0,
        alerts_suspended=1,
        alerts_retired=0,
    )

    order_set = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_order_set_states(order_set, "APPROVED", "EXPIRED")

    alert = fixtures.read_alert(committee, alert_id)
    assertions.assert_alert_states(alert, "APPROVED", "SUSPENDED")
    assert alert["suspension_reason"] == "SOURCE_CONTENT_EXPIRED"
    assert alert["suspension_count"] == 1


def test_the_suspension_closes_the_open_window_and_rewrites_the_ledger(committee):
    """Links four and five: a window closes and computes an index nobody asked for.

    "Because the alert suspended, any burden window of that alert still in state
    `OPEN` is closed with `closure_reason` `SOURCE_SUSPENDED`, which computes
    that window's ... `burden_index`, `burden_index_clinician_weighted` and
    `burden_classification`; and because that window closed, the alert's
    `windowed_fire_count`, `unwindowed_fire_count`, `latest_burden_index` and
    `latest_burden_classification` are all recomputed."

    Design: Difficulty/transitive_cascade/cascade_expiration_sweep_task_to_order_set_to_alert_to_window_to_ledger
    """
    scenario = _published_pair_with_an_open_window(committee)
    alert_id = scenario["alert"]["id"]

    fixtures.set_clock("2027-09-14T00:00:00Z")
    sweep = validate_success(
        api_client.run_expiration_sweep(
            factories.build_expiration_sweep_payload(dry_run=False),
            committee["chair_headers"],
        )
    )
    assertions.assert_sweep_counts(sweep, burden_windows_closed=1)

    windows = fixtures.read_windows(committee, alert_id)
    assert len(windows) == 1
    window = windows[0]
    assert window["state"] == "CLOSED"
    assert window["closure_reason"] == "SOURCE_SUSPENDED"
    assertions.assert_burden_window_counts(window, 40, 36, 4, 10, 10)
    assertions.assert_burden_computation(
        window, 0.9000, 0.8000, 72.00, 50.00, "LOW_VALUE"
    )

    alert = fixtures.read_alert(committee, alert_id)
    assertions.assert_firing_ledger(alert, 40, 40, 0)
    assertions.assert_firing_ledger_identity(alert)
    assertions.assert_numeric_equals(alert["latest_burden_index"], 72.00, 2)
    assert alert["latest_burden_classification"] == "LOW_VALUE"


# ---------------------------------------------------------------------------
# Four links from one specialty vote
# ---------------------------------------------------------------------------


DELIRIUM_REQUEST = {
    "title": "Delirium screening order set and passive reminder",
    "request_type": "BOTH",
    "clinical_domain": "HOSPITAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
}

CAM_ICU_ITEM = {
    "orderable_code": "CAM-ICU",
    "display_name": "CAM-ICU screening",
    "item_category": "NURSING",
    "high_alert_medication": False,
}

PASSIVE_REMINDER = {
    "name": "Delirium screening reminder",
    "severity_tier": "TIER_3_PASSIVE",
    "override_reason_required": False,
    "firing_criteria": {
        "trigger_event": "ADMISSION_COMPLETE",
        "expression": "admitted AND age >= 65 AND no_cam_icu_in_24h",
    },
}


def _specialty_stage_with_an_approved_linked_alert(committee):
    """A build awaiting two specialty votes beside an already-approved linked alert."""
    fixtures.reset_clock()
    scenario = fixtures.setup_order_set_in_specialty_approval(
        committee,
        request_overrides=DELIRIUM_REQUEST,
        item_payloads=[CAM_ICU_ITEM],
    )
    order_set_id = scenario["order_set"]["id"]
    assert scenario["order_set"]["risk_class"] == "STANDARD"

    scenario["trigger_assignment"] = fixtures.assign_reviewer(
        committee,
        committee["specialists"][0]["id"],
        "SPECIALTY_APPROVAL",
        order_set_id=order_set_id,
    )
    scenario["sibling_assignment"] = fixtures.assign_reviewer(
        committee,
        committee["specialists"][1]["id"],
        "SPECIALTY_APPROVAL",
        order_set_id=order_set_id,
    )

    alert = fixtures.design_alert(
        committee,
        scenario["content_request"],
        linked_order_set_id=order_set_id,
        **PASSIVE_REMINDER,
    )
    scenario["alert_assignment"] = fixtures.assign_reviewer(
        committee,
        committee["specialists"][2]["id"],
        "SPECIALTY_APPROVAL",
        alert_id=alert["id"],
    )
    fixtures.cast_vote(
        committee,
        scenario["alert_assignment"]["id"],
        committee["specialist_headers"][2],
        "APPROVE",
    )
    scenario["alert"] = fixtures.read_alert(committee, alert["id"])
    assertions.assert_alert_states(scenario["alert"], "APPROVED", "UNPUBLISHED")
    return scenario


def test_a_specialty_revise_returns_the_build_to_draft_and_voids_its_siblings(committee):
    """Links one and two, with the triggering assignment deliberately spared.

    "First, `review_state` returns `SPECIALTY_APPROVAL → DRAFT` and
    `revision_round` increments by 1. Second, because the order set returned to
    `DRAFT`, every *other* assignment on it in state `ASSIGNED` or `CAST` moves
    to `VOIDED` with `void_reason` `ARTIFACT_RETURNED_TO_DRAFT`." "The
    triggering assignment itself stays `CAST` with its vote intact."

    Design: Difficulty/transitive_cascade/cascade_specialty_revise_voids_assignments_credits_workload_restages_alert
    """
    scenario = _specialty_stage_with_an_approved_linked_alert(committee)
    order_set_id = scenario["order_set"]["id"]
    assert scenario["trigger_assignment"]["estimated_minutes"] == 15
    assert scenario["alert_assignment"]["estimated_minutes"] == 10

    triggered = validate_success(
        api_client.cast_review_vote(
            scenario["trigger_assignment"]["id"],
            factories.build_cast_payload(
                "REVISE",
                evidence_concern=True,
                comment="Screening frequency contradicts the cited guideline",
            ),
            committee["specialist_headers"][0],
        )
    )
    assert triggered["state"] == "CAST"
    assert triggered["vote"] == "REVISE"

    order_set = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_order_set_states(order_set, "DRAFT", "UNPUBLISHED")
    assert order_set["revision_round"] == 1
    # the two cast peer assignments plus the untouched specialty assignment
    assert order_set["votes_voided_count"] == 3
    assert order_set["votes_cast_count"] == 1

    sibling = validate_success(
        api_client.get_review_assignment(
            scenario["sibling_assignment"]["id"], committee["chair_headers"]
        )
    )
    assert sibling["state"] == "VOIDED"
    assert sibling["void_reason"] == "ARTIFACT_RETURNED_TO_DRAFT"


def test_the_voids_credit_the_minute_ledgers_and_restage_the_linked_alert(committee):
    """Links three and four, and the alert's own assignment is left alone.

    "Third, because each of those assignments was voided, its reviewer's
    `review_workload_assigned_minutes` is reduced by that assignment's
    `estimated_minutes` and `review_workload_remaining_minutes` is recomputed.
    Fourth, because the order set is no longer in approval, every alert whose
    `linked_order_set_id` names it, whose `lifecycle_state` is `UNPUBLISHED` and
    whose `review_state` is `SPECIALTY_APPROVAL` or `APPROVED`, has its
    `review_state` forced back to `DRAFT` and its `restage_count` incremented by
    1."

    Design: Difficulty/transitive_cascade/cascade_specialty_revise_voids_assignments_credits_workload_restages_alert
    """
    scenario = _specialty_stage_with_an_approved_linked_alert(committee)
    sibling_reviewer_id = committee["specialists"][1]["id"]

    before = validate_success(
        api_client.get_clinician(sibling_reviewer_id, committee["chair_headers"])
    )
    assertions.assert_workload_ledger(before, 15, 465, 1)

    validate_success(
        api_client.cast_review_vote(
            scenario["trigger_assignment"]["id"],
            factories.build_cast_payload("REVISE", evidence_concern=True),
            committee["specialist_headers"][0],
        )
    )

    after = validate_success(
        api_client.get_clinician(sibling_reviewer_id, committee["chair_headers"])
    )
    assertions.assert_workload_ledger(after, 0, 480, 0)
    assertions.assert_workload_identity(after)

    peer = validate_success(
        api_client.get_clinician(committee["peers"][0]["id"], committee["chair_headers"])
    )
    # a void credits a CAST assignment's minutes back exactly as it does an ASSIGNED one
    assert peer["review_workload_assigned_minutes"] == 0
    assertions.assert_workload_identity(peer)

    alert = fixtures.read_alert(committee, scenario["alert"]["id"])
    assertions.assert_alert_states(alert, "DRAFT", "UNPUBLISHED")
    assert alert["restage_count"] == 1

    untouched = validate_success(
        api_client.get_review_assignment(
            scenario["alert_assignment"]["id"], committee["chair_headers"]
        )
    )
    # the cascade walks the artifact link; it does not sweep every assignment
    assert untouched["state"] == "CAST"
    alert_reviewer = validate_success(
        api_client.get_clinician(
            committee["specialists"][2]["id"], committee["chair_headers"]
        )
    )
    assert alert_reviewer["review_workload_assigned_minutes"] == 10
