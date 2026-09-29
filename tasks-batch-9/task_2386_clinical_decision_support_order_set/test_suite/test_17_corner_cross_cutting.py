"""Cross-cutting coverage: the two version guards and a rate threshold.

The alert guard is broken by the caller's own previous write; the request's
version counter is followed across a whole intake loop and then replayed; and a
classification boundary is straddled by a single override.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ADVISORY_REQUEST = {
    "title": "Passive advisory bundle",
    "request_type": "ALERT",
    "clinical_domain": "INTERNAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "evidence_citations": [
        factories.build_citation("Guideline A", True),
        factories.build_citation("Guideline B", True),
    ],
}



# ---------------------------------------------------------------------------
# The request version counter across a whole intake loop
# ---------------------------------------------------------------------------


def test_the_request_version_counts_every_write_including_the_childs(committee):
    """Five versions, four scores and one replayed guard value.

    "Returning a request advances `INTAKE_SUBMITTED → RETURNED_TO_SPONSOR` and
    increments `return_count` by 1; both `priority_score` and `priority_score_basis`
    are left exactly as they were." "the array replaces the stored one wholesale,
    `peer_reviewed_citation_count` is recomputed from it, `priority_score` is
    recomputed with the intake-provisional variant, `priority_score_basis` returns to
    `INTAKE_PROVISIONAL`, and `status` returns to `INTAKE_SUBMITTED`." "Creating the
    first build artifact on a request — order set or alert — advances that request
    `TRIAGE_ACCEPTED → BUILD_IN_PROGRESS` and increments the request's `version`."
    "If that value does not equal the content request's current `version`, the
    request is rejected with `ERR_STALE_CONTENT_REQUEST_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/layer_version_increments_on_every_write_to_a_content_request
    """
    fixtures.reset_clock()
    release = fixtures.create_release(
        committee, content_domain="DOSING", received_at="2026-08-01T00:00:00Z"
    )
    submitted = fixtures.create_request(
        committee,
        title="Version ledger request",
        request_type="ORDER_SET",
        clinical_domain="CARDIOLOGY",
        urgency="ROUTINE",
        evidence_grade="B",
        evidence_citations=[factories.build_citation("Guideline A", True)],
    )
    assert submitted["version"] == 1
    assert submitted["status"] == "INTAKE_SUBMITTED"
    # 30 for grade B, nothing for ROUTINE and nothing for the absent safety flag
    assertions.assert_numeric_equals(submitted["priority_score"], 30.00, 2)

    returned = validate_success(
        api_client.triage_content_request(
            submitted["id"],
            factories.build_triage_payload(
                "RETURN", triage_note="Please add peer-reviewed evidence"
            ),
            committee["chair_headers"],
        )
    )
    assert returned["version"] == 2
    assert returned["status"] == "RETURNED_TO_SPONSOR"
    assert returned["return_count"] == 1
    assertions.assert_numeric_equals(returned["priority_score"], 30.00, 2)
    assert returned["priority_score_basis"] == "INTAKE_PROVISIONAL"

    resubmitted = validate_success(
        api_client.resubmit_content_request(
            submitted["id"],
            factories.build_resubmit_payload(
                evidence_citations=[
                    factories.build_citation("Circulation 2021", True),
                    factories.build_citation("JACC 2022", True),
                    factories.build_citation("NEJM 2020", True),
                ],
                evidence_grade="A",
            ),
            committee["sponsor_headers"],
        )
    )
    assert resubmitted["version"] == 3
    assert resubmitted["status"] == "INTAKE_SUBMITTED"
    assert resubmitted["peer_reviewed_citation_count"] == 3
    # the provisional variant reads the raised grade and ignores the citations
    assertions.assert_numeric_equals(resubmitted["priority_score"], 40.00, 2)
    assert resubmitted["priority_score_basis"] == "INTAKE_PROVISIONAL"

    accepted = validate_success(
        api_client.triage_content_request(
            submitted["id"],
            factories.build_triage_payload(
                "ACCEPT", triage_note="Evidence now sufficient"
            ),
            committee["chair_headers"],
        )
    )
    assert accepted["version"] == 4
    assert accepted["status"] == "TRIAGE_ACCEPTED"
    # 6 * 3 peer-reviewed citations under the 40-point cap, no urgency or safety
    assertions.assert_numeric_equals(accepted["priority_score"], 18.00, 2)
    assert accepted["priority_score_basis"] == "COMMITTEE_CALIBRATED"

    guard_value = accepted["version"]
    order_set = validate_success(
        api_client.create_order_set(
            submitted["id"],
            factories.build_order_set_payload(
                committee["builder"]["id"],
                release["id"],
                guard_value,
                name="Version ledger set v1",
                specialty="CARDIOLOGY",
            ),
            committee["builder_headers"],
        ),
        201,
    )
    assert order_set["review_state"] == "DRAFT"

    built = fixtures.read_request(committee, submitted["id"])
    assert built["version"] == 5
    assert built["status"] == "BUILD_IN_PROGRESS"

    replayed = api_client.create_order_set(
        submitted["id"],
        factories.build_order_set_payload(
            committee["builder"]["id"],
            release["id"],
            guard_value,
            name="Version ledger set v2",
            specialty="CARDIOLOGY",
        ),
        committee["builder_headers"],
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_CONTENT_REQUEST_VERSION, 412)


# ---------------------------------------------------------------------------
# A classification boundary straddled by one override
# ---------------------------------------------------------------------------


BOUNDARY_ALERT = {
    "name": "Boundary interruptive",
    "severity_tier": "TIER_2_INTERRUPTIVE",
    "override_reason_codes": ["CLINICAL_JUDGMENT", "PATIENT_REFUSED"],
    "firing_criteria": {"trigger_event": "ORDER_ENTRY", "expression": "flag_f"},
}


def test_one_override_fewer_moves_the_window_off_the_low_value_verdict(committee):
    """Exactly 65.00 is low value; 63.34 is only worth monitoring.

    "otherwise if `burden_index` is at least 65.00 it is `LOW_VALUE`; otherwise if
    `burden_index` is at most 25.00 it is `HIGH_VALUE`; otherwise it is `MONITOR`."
    "Its `override_rate` is `override_count` divided by `fire_count`, rounded
    half-up to four decimal places". "because overlap is computed on half-open
    intervals, a new window whose `window_start` equals an existing window's
    `window_end` is merely adjacent and is allowed". "`latest_burden_index` and
    `latest_burden_classification` are set from the most recently closed window,
    taken in order of `window_start` descending with `created_at` descending as the
    tie-break."

    Design: Corner/cross_cutting_complexity_layers/layer_burden_classification_boundary_at_index_exactly_65_00
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee,
        request_overrides={**ADVISORY_REQUEST, "title": "Boundary advisory bundle"},
        alert_overrides=BOUNDARY_ALERT,
    )
    alert_id = scenario["alert"]["id"]

    fixtures.ingest_firings(
        alert_id,
        "2026-08-02T00:00:00Z",
        fire_count=120,
        override_count=39,
        distinct_clinician_count=10,
        interval_seconds=3600,
        override_reason_code="CLINICAL_JUDGMENT",
    )
    fixtures.ingest_firings(
        alert_id,
        "2026-08-07T00:00:00Z",
        fire_count=120,
        override_count=38,
        distinct_clinician_count=10,
        interval_seconds=3600,
        override_reason_code="CLINICAL_JUDGMENT",
    )
    fixtures.set_clock("2026-08-12T00:00:00Z")

    first = fixtures.open_window(
        committee, alert_id, "2026-08-02T00:00:00Z", "2026-08-07T00:00:00Z"
    )
    on_the_line = validate_success(
        api_client.close_burden_window(
            alert_id,
            first["id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            fixtures.ADMIN_HEADERS,
        )
    )
    assertions.assert_burden_window_counts(on_the_line, 120, 39, 81, 10, 10)
    # 0.3250 * 1.0 tier * 2.0000 capped volume * 100 lands exactly on the threshold
    assertions.assert_burden_computation(
        on_the_line, 0.3250, 2.0000, 65.00, 50.00, "LOW_VALUE"
    )
    assertions.assert_classification_from_index(on_the_line)

    second = fixtures.open_window(
        committee, alert_id, "2026-08-07T00:00:00Z", "2026-08-12T00:00:00Z"
    )
    just_under = validate_success(
        api_client.close_burden_window(
            alert_id,
            second["id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            fixtures.ADMIN_HEADERS,
        )
    )
    assertions.assert_burden_window_counts(just_under, 120, 38, 82, 10, 10)
    # round(38/120, 4) is 0.3167, which multiplies out to 63.34
    assertions.assert_burden_computation(
        just_under, 0.3167, 2.0000, 63.34, 50.00, "MONITOR"
    )
    assertions.assert_classification_from_index(just_under)

    alert = fixtures.read_alert(committee, alert_id)
    assertions.assert_firing_ledger(alert, 240, 240, 0)
    assertions.assert_firing_ledger_identity(alert)
    assertions.assert_numeric_equals(alert["latest_burden_index"], 63.34, 2)
    assert alert["latest_burden_classification"] == "MONITOR"
