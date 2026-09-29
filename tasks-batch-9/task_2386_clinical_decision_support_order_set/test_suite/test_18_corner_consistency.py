"""Consistency coverage: the write's own response is already the truth.

Both probes compare a mutation's response body against the very next read, one
on a recalibrated score and one on a whole set of derived window measures plus
the denormalized ledger they feed.
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
# A recomputed score, in the response that recomputed it
# ---------------------------------------------------------------------------


def test_the_triage_response_already_carries_the_recalibrated_score(committee):
    """80.00 provisional becomes 58.00 calibrated in the POST body itself.

    "Consistency is immediate; there is no deferred reconciliation queue." "it
    awards 40 points for evidence grade `A`, 30 for `B`, 18 for `C` and 8 for
    `EXPERT_OPINION`; adds 0 points for urgency `ROUTINE`, 12 for `EXPEDITED` and 25
    for `SAFETY_URGENT`; adds a further 15 points when `patient_safety_flag` is true
    ... `priority_score_basis` is set to `INTAKE_PROVISIONAL` to record which variant
    produced the stored number." "The citation component is 6 points for each
    peer-reviewed citation, capped at 40 points however many there are. The urgency
    and safety components are the same as before". "The server derives
    `peer_reviewed_citation_count` as the number of `evidence_citations` entries
    whose `peer_reviewed` is true".

    Design: Corner/consistency_model/consistency_immediate_triage_response_carries_the_recalibrated_priority_score
    """
    fixtures.reset_clock()
    request = fixtures.create_request(
        committee,
        title="Sepsis hard stop request",
        request_type="ALERT",
        clinical_domain="CRITICAL_CARE",
        urgency="SAFETY_URGENT",
        evidence_grade="A",
        patient_safety_flag=True,
        evidence_citations=[
            factories.build_citation("Surviving Sepsis 2021", True),
            factories.build_citation("NEJM 2018 sepsis", True),
            factories.build_citation("JAMA 2019 bundles", True),
        ],
    )
    # 40 for grade A, 25 for SAFETY_URGENT and 15 for the safety flag
    assertions.assert_numeric_equals(request["priority_score"], 80.00, 2)
    assert request["priority_score_basis"] == "INTAKE_PROVISIONAL"

    posted = validate_success(
        api_client.triage_content_request(
            request["id"],
            factories.build_triage_payload(
                "ACCEPT", triage_note="Safety urgent, accept immediately"
            ),
            committee["chair_headers"],
        )
    )
    # 18 for three peer-reviewed citations, plus 25 and 15, with no backlog bonus
    assertions.assert_numeric_equals(posted["priority_score"], 58.00, 2)
    assert posted["priority_score_basis"] == "COMMITTEE_CALIBRATED"
    assert posted["status"] == "TRIAGE_ACCEPTED"
    assert posted["peer_reviewed_citation_count"] == 3

    reread = validate_success(
        api_client.get_content_request(request["id"], committee["admin_headers"])
    )
    assertions.assert_numeric_equals(reread["priority_score"], 58.00, 2)
    assert reread["priority_score"] == posted["priority_score"]
    assert reread["priority_score_basis"] == posted["priority_score_basis"]


# ---------------------------------------------------------------------------
# Every derived measure, and the ledger it feeds, without a lag
# ---------------------------------------------------------------------------


CONSISTENCY_REQUEST = {
    "title": "Immediate consistency advisory",
    "request_type": "ALERT",
    "clinical_domain": "INTERNAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "evidence_citations": [
        factories.build_citation("Guideline A", True),
        factories.build_citation("Guideline B", True),
    ],
}

CONSISTENCY_ALERT = {
    "name": "Immediate consistency alert",
    "severity_tier": "TIER_2_INTERRUPTIVE",
    "override_reason_codes": ["CLINICAL_JUDGMENT", "PATIENT_REFUSED"],
    "firing_criteria": {"trigger_event": "ORDER_ENTRY", "expression": "flag_g"},
}


def test_the_window_close_response_is_already_the_whole_computation(committee):
    """Both indices arrive with the close, and the alert already agrees.

    "Consistency is immediate; there is no deferred reconciliation queue." "From
    that set the server computes `fire_count` as the number of firings,
    `override_count` as the number with `accepted` false, `accept_count` as the
    number with `accepted` true, `distinct_fired_clinician_count` as the number of
    distinct `firing_clinician_ref` values, and `distinct_overriding_clinician_count`
    as the number of distinct `firing_clinician_ref` values among the firings with
    `accepted` false." "Its volume factor is `distinct_fired_clinician_count` divided
    by an expected 20 clinicians per window, rounded half-up to four decimal places,
    then capped at 2.0." "Closing a window also updates the alert's ledger:
    `windowed_fire_count` increases by the window's `fire_count`,
    `unwindowed_fire_count` becomes `lifetime_fire_count` minus
    `windowed_fire_count`, and `latest_burden_index` and
    `latest_burden_classification` are set from the most recently closed window".

    Design: Corner/consistency_model/consistency_immediate_window_close_response_carries_every_computed_field
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee,
        request_overrides=CONSISTENCY_REQUEST,
        alert_overrides=CONSISTENCY_ALERT,
    )
    alert_id = scenario["alert"]["id"]

    fixtures.ingest_firings(
        alert_id,
        "2026-08-02T00:00:00Z",
        fire_count=50,
        override_count=25,
        distinct_clinician_count=5,
        interval_seconds=3600,
        override_reason_code="CLINICAL_JUDGMENT",
    )
    window = fixtures.open_window(
        committee, alert_id, "2026-08-02T00:00:00Z", "2026-08-05T00:00:00Z"
    )
    fixtures.set_clock("2026-08-05T00:00:00Z")

    closed = validate_success(
        api_client.close_burden_window(
            alert_id,
            window["id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            fixtures.ADMIN_HEADERS,
        )
    )

    assert closed["state"] == "CLOSED"
    assertions.assert_burden_window_counts(closed, 50, 25, 25, 5, 5)
    # 25/50 against 50 expected fires, versus 5/5 against 20 expected clinicians
    assertions.assert_burden_computation(
        closed, 0.5000, 1.0000, 50.00, 25.00, "MONITOR"
    )
    assertions.assert_classification_from_index(closed)

    alert = fixtures.read_alert(committee, alert_id)
    assertions.assert_numeric_equals(alert["latest_burden_index"], 50.00, 2)
    assert alert["latest_burden_classification"] == closed["burden_classification"]
    assertions.assert_firing_ledger(alert, 50, 50, 0)
    assertions.assert_firing_ledger_identity(alert)

    _windows, meta = validate_paginated(
        api_client.list_burden_windows(alert_id, committee["chair_headers"])
    )
    assert meta["total_count"] == 1
