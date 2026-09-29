"""Two ledgers taken out and put back, checked for drift at every step.

A reviewer's time budget is debited, cast against, withdrawn and re-debited by an
identical assignment. An alert's firing ledger has forty firings moved from the
unwindowed half to the windowed half and back again, with five out-of-window
firings that must never be swept in.
"""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    make_peer_reviewer_headers,
    make_specialty_approver_headers,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# The reviewer workload ledger
# ---------------------------------------------------------------------------


INSULIN_REQUEST = {
    "title": "Insulin infusion order set and hard stop",
    "request_type": "BOTH",
    "clinical_domain": "ENDOCRINOLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "A",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("ADA 2026 standards", True),
        factories.build_citation("ISMP high-alert list 2025", True),
    ],
}

INSULIN_ITEM = {
    "orderable_code": "INSULIN-INF",
    "display_name": "Insulin regular infusion 1 unit/mL",
    "item_category": "MEDICATION",
    "high_alert_medication": True,
    "default_dose": "0.1 unit/kg/hr",
}

INSULIN_HARD_STOP = {
    "name": "Insulin concentration hard stop",
    "severity_tier": "TIER_1_HARD_STOP",
    "override_reason_codes": ["PHARMACY_VERIFIED", "PROTOCOL_EXCEPTION"],
    "hard_stop_justification": (
        "Wrong-concentration insulin infusions have caused fatal hypoglycaemia; "
        "committee mandated a hard stop"
    ),
    "firing_criteria": {
        "trigger_event": "NEW_MEDICATION_ORDER",
        "expression": "insulin_infusion AND concentration != 1_unit_per_mL",
    },
}


def _one_reviewer_two_reviewable_artifacts(committee):
    """A dual-role reviewer at rest, a HIGH-risk build in peer review and a hard stop."""
    fixtures.reset_clock()
    reviewer = fixtures.register_clinician(
        ["PeerReviewer", "SpecialtyApprover"],
        full_name="Dr Lam",
        specialty="CARDIOLOGY",
        review_workload_capacity_minutes=480,
    )
    release = fixtures.create_release(committee)
    content_request = fixtures.setup_accepted_request(committee, **INSULIN_REQUEST)
    order_set = fixtures.build_order_set(
        committee,
        content_request,
        release["id"],
        name="Insulin infusion",
        specialty="ENDOCRINOLOGY",
    )
    fixtures.add_item(committee, order_set["id"], **INSULIN_ITEM)
    submitted = fixtures.submit_for_peer_review(
        committee, order_set["id"], submission_note="High-alert build ready"
    )
    alert = fixtures.design_alert(committee, content_request, **INSULIN_HARD_STOP)
    return {
        "reviewer": reviewer,
        "peer_headers": make_peer_reviewer_headers(reviewer["id"]),
        "specialty_headers": make_specialty_approver_headers(reviewer["id"]),
        "order_set": submitted,
        "alert": alert,
    }


def _read_reviewer(committee, reviewer_id):
    return validate_success(
        api_client.get_clinician(reviewer_id, committee["chair_headers"])
    )


def _reviewers_assignments(committee, reviewer_id):
    response = api_client.list_review_assignments(
        committee["chair_headers"], {"reviewer_id": reviewer_id, "limit": 100}
    )
    data, _meta = validate_paginated(response)
    return data


def _assign(committee, reviewer_id, review_kind, **target):
    return validate_success(
        api_client.create_review_assignment(
            factories.build_review_assignment_payload(reviewer_id, review_kind, **target),
            committee["chair_headers"],
        ),
        201,
    )


def test_two_debits_are_priced_by_snapshot_and_a_cast_leaves_the_minutes_alone(committee):
    """35 plus 30 minutes go out, and casting one of them spends nothing back.

    "An order-set peer review costs 20 minutes on a `STANDARD` build and 35 on a
    `HIGH` one ... An alert review is priced by tier instead: 30 minutes for
    `TIER_1_HARD_STOP`, 18 for `TIER_2_INTERRUPTIVE` and 10 for
    `TIER_3_PASSIVE`." "Casting moves the assignment `ASSIGNED → CAST` ... and
    leaves the workload debit in place — the minutes were consumed by doing the
    work, so casting never credits the ledger."

    Design: Difficulty/compensating_invariant/compensating_reviewer_workload_minutes_conserved_across_withdraw_and_reassign
    """
    scenario = _one_reviewer_two_reviewable_artifacts(committee)
    reviewer_id = scenario["reviewer"]["id"]
    assert scenario["order_set"]["risk_class"] == "HIGH"
    assert scenario["order_set"]["peer_required_votes"] == 3
    assertions.assert_workload_ledger(scenario["reviewer"], 0, 480, 0)

    peer_assignment = _assign(
        committee, reviewer_id, "PEER_REVIEW", order_set_id=scenario["order_set"]["id"]
    )
    assert peer_assignment["risk_class_snapshot"] == "HIGH"
    assert peer_assignment["estimated_minutes"] == 35
    assertions.assert_workload_ledger(_read_reviewer(committee, reviewer_id), 35, 445, 1)

    alert_assignment = _assign(
        committee, reviewer_id, "SPECIALTY_APPROVAL", alert_id=scenario["alert"]["id"]
    )
    # priced by tier, not by the specialty-approval table's 25 minutes for HIGH
    assert alert_assignment["estimated_minutes"] == 30
    assertions.assert_workload_ledger(_read_reviewer(committee, reviewer_id), 65, 415, 2)

    cast = validate_success(
        api_client.cast_review_vote(
            alert_assignment["id"],
            factories.build_cast_payload("APPROVE"),
            scenario["specialty_headers"],
        )
    )
    assert cast["state"] == "CAST"

    after_cast = _read_reviewer(committee, reviewer_id)
    assert after_cast["review_workload_assigned_minutes"] == 65
    assert after_cast["review_workload_remaining_minutes"] == 415
    assertions.assert_workload_identity(after_cast)
    assertions.assert_workload_matches_assignments(
        after_cast, _reviewers_assignments(committee, reviewer_id)
    )


def test_a_withdrawal_and_an_identical_reassignment_leave_no_drift(committee):
    """The ledger returns to the byte twice over a withdraw-reassign-withdraw trip.

    "Withdrawal ... moves the assignment `ASSIGNED → WITHDRAWN`, reduces the
    reviewer's `review_workload_assigned_minutes` by that assignment's
    `estimated_minutes` ... restoring the pre-assignment ledger exactly, with no
    drift." "A clinician may hold at most one assignment in state `ASSIGNED` or
    `CAST` per artifact-and-`review_kind` pair, and a second one is
    `ERR_DUPLICATE_REVIEW_ASSIGNMENT`; assignments already in `VOIDED` or
    `WITHDRAWN` do not block a fresh assignment."

    Design: Difficulty/compensating_invariant/compensating_reviewer_workload_minutes_conserved_across_withdraw_and_reassign
    """
    scenario = _one_reviewer_two_reviewable_artifacts(committee)
    reviewer_id = scenario["reviewer"]["id"]
    order_set_id = scenario["order_set"]["id"]

    peer_assignment = _assign(
        committee, reviewer_id, "PEER_REVIEW", order_set_id=order_set_id
    )
    alert_assignment = _assign(
        committee, reviewer_id, "SPECIALTY_APPROVAL", alert_id=scenario["alert"]["id"]
    )
    validate_success(
        api_client.cast_review_vote(
            alert_assignment["id"],
            factories.build_cast_payload("APPROVE"),
            scenario["specialty_headers"],
        )
    )

    withdrawn = validate_success(
        api_client.withdraw_review_assignment(
            peer_assignment["id"],
            factories.build_withdraw_payload(
                withdrawal_reason="Reviewer recused for the first pass"
            ),
            committee["chair_headers"],
        )
    )
    assert withdrawn["state"] == "WITHDRAWN"
    credited = _read_reviewer(committee, reviewer_id)
    # exactly the peer assignment's 35 minutes came back, and only those
    assert credited["review_workload_assigned_minutes"] == 30
    assert credited["review_workload_remaining_minutes"] == 450
    assertions.assert_workload_identity(credited)
    assertions.assert_workload_matches_assignments(
        credited, _reviewers_assignments(committee, reviewer_id)
    )

    replacement = _assign(
        committee, reviewer_id, "PEER_REVIEW", order_set_id=order_set_id
    )
    assert replacement["estimated_minutes"] == 35
    restored = _read_reviewer(committee, reviewer_id)
    assert restored["review_workload_assigned_minutes"] == 65
    assert restored["review_workload_remaining_minutes"] == 415
    assertions.assert_workload_identity(restored)

    validate_success(
        api_client.withdraw_review_assignment(
            replacement["id"],
            factories.build_withdraw_payload(
                withdrawal_reason="Rebalancing the committee roster"
            ),
            committee["chair_headers"],
        )
    )
    final = _read_reviewer(committee, reviewer_id)
    assert final["review_workload_assigned_minutes"] == 30
    assert final["review_workload_remaining_minutes"] == 450
    assertions.assert_workload_identity(final)
    assertions.assert_workload_matches_assignments(
        final, _reviewers_assignments(committee, reviewer_id)
    )


# ---------------------------------------------------------------------------
# The alert firing ledger
# ---------------------------------------------------------------------------


QTC_REQUEST = {
    "title": "QTc prolongation interruptive alert",
    "request_type": "ALERT",
    "clinical_domain": "CARDIOLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
}

QTC_ALERT = {
    "name": "QTc prolonging combination",
    "severity_tier": "TIER_2_INTERRUPTIVE",
    "override_reason_codes": ["CLINICALLY_APPROPRIATE", "ECG_PENDING"],
    "firing_criteria": {
        "trigger_event": "NEW_MEDICATION_ORDER",
        "expression": "qtc >= 500 AND new_order(qt_prolonging_agent)",
    },
}


def _forty_in_window_and_five_outside(committee):
    """An OPEN September window over 40 firings, with 5 November firings outside it."""
    fixtures.reset_clock()
    scenario = fixtures.setup_approved_alert(
        committee, request_overrides=QTC_REQUEST, alert_overrides=QTC_ALERT
    )
    alert_id = scenario["alert"]["id"]

    fixtures.set_clock("2026-09-01T00:00:00Z")
    fixtures.activate_alert(committee, alert_id)
    scenario["batch_a"] = fixtures.ingest_firings(
        alert_id,
        "2026-09-01T00:00:00Z",
        fire_count=40,
        override_count=36,
        distinct_clinician_count=10,
        interval_seconds=3600,
        override_reason_code="CLINICALLY_APPROPRIATE",
    )
    fixtures.set_clock("2026-11-05T00:00:00Z")
    scenario["batch_b"] = fixtures.ingest_firings(
        alert_id,
        "2026-11-01T00:00:00Z",
        fire_count=5,
        override_count=5,
        distinct_clinician_count=3,
        interval_seconds=3600,
        override_reason_code="ECG_PENDING",
    )
    scenario["window"] = fixtures.open_window(
        committee, alert_id, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
    )
    return scenario


def test_closing_a_window_shifts_the_partition_without_minting_firings(committee):
    """Forty firings move sides while the lifetime total stays at forty-five.

    "`windowed_fire_count` is the sum of `fire_count` over that alert's burden
    windows in state `CLOSED` or `FINALIZED`. `unwindowed_fire_count` is always
    `lifetime_fire_count` minus `windowed_fire_count`". "`lifetime_fire_count`
    counts every firing record ever ingested for the alert and never decreases."
    "`lifetime_override_count` accumulates the number of firing records for this
    alert whose `accepted` is false, across the alert's whole life."

    Design: Difficulty/compensating_invariant/compensating_alert_firing_ledger_conserved_across_window_close_and_reopen
    """
    scenario = _forty_in_window_and_five_outside(committee)
    alert_id = scenario["alert"]["id"]
    assert scenario["batch_a"]["created_event_count"] == 40
    assert scenario["batch_b"]["created_event_count"] == 5
    assert scenario["window"]["state"] == "OPEN"

    at_rest = fixtures.read_alert(committee, alert_id)
    assertions.assert_firing_ledger(at_rest, 45, 0, 45)
    assert at_rest["latest_burden_index"] is None

    closed = fixtures.close_window(
        committee, alert_id, scenario["window"]["id"], closure_reason="MANUAL_CLOSE"
    )
    # the five November firings are excluded by the half-open filter
    assert closed["fire_count"] == 40
    assert closed["override_count"] == 36
    assertions.assert_numeric_equals(closed["burden_index"], 72.00, 2)
    assert closed["burden_classification"] == "LOW_VALUE"

    after_close = fixtures.read_alert(committee, alert_id)
    assertions.assert_firing_ledger(after_close, 45, 40, 5)
    assertions.assert_firing_ledger_identity(after_close)
    assertions.assert_numeric_equals(after_close["latest_burden_index"], 72.00, 2)
    assert after_close["latest_burden_classification"] == "LOW_VALUE"
    # 36 in-window plus 5 out-of-window overrides, a ledger windows never touch
    assert after_close["lifetime_override_count"] == 41


def test_a_close_reopen_close_round_trip_leaves_the_ledger_byte_identical(committee):
    """Reopening moves exactly the same forty back, then the reclose repeats itself.

    "Reopening a closed window discards that window's counts and subtracts them
    back out of `windowed_fire_count`, leaving `lifetime_fire_count` untouched,
    so the three numbers stay consistent across arbitrarily many
    close-and-reopen cycles." "`latest_burden_index` and
    `latest_burden_classification` are recomputed from whatever `CLOSED` or
    `FINALIZED` windows remain, or set to null when none remain."

    Design: Difficulty/compensating_invariant/compensating_alert_firing_ledger_conserved_across_window_close_and_reopen
    """
    scenario = _forty_in_window_and_five_outside(committee)
    alert_id = scenario["alert"]["id"]
    window_id = scenario["window"]["id"]

    fixtures.close_window(committee, alert_id, window_id, closure_reason="MANUAL_CLOSE")

    reopened = validate_success(
        api_client.reopen_burden_window(
            alert_id,
            window_id,
            factories.build_reopen_window_payload(
                reopen_reason="Interface backfill under investigation"
            ),
            fixtures.ADMIN_HEADERS,
        )
    )
    assertions.assert_window_reset(reopened, 1)

    after_reopen = fixtures.read_alert(committee, alert_id)
    # byte-identical to the pre-close reading: exactly the 40 that left came back
    assertions.assert_firing_ledger(after_reopen, 45, 0, 45)
    assertions.assert_firing_ledger_identity(after_reopen)
    assert after_reopen["latest_burden_index"] is None
    assert after_reopen["latest_burden_classification"] is None

    reclosed = fixtures.close_window(
        committee, alert_id, window_id, closure_reason="MANUAL_CLOSE"
    )
    assert reclosed["fire_count"] == 40
    assert reclosed["override_count"] == 36
    assertions.assert_numeric_equals(reclosed["burden_index"], 72.00, 2)
    assert reclosed["burden_classification"] == "LOW_VALUE"
    # the second close does not reset the compensation counter
    assert reclosed["reopen_count"] == 1

    final = fixtures.read_alert(committee, alert_id)
    assertions.assert_firing_ledger(final, 45, 40, 5)
    assertions.assert_firing_ledger_identity(final)
    assertions.assert_numeric_equals(final["latest_burden_index"], 72.00, 2)
    assert final["latest_burden_classification"] == "LOW_VALUE"
