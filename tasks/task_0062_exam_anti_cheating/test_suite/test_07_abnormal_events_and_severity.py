"""AbnormalEvent recording and severity_classification.

Covers PRD §3.4 — base scores, channel/mode multipliers, severity
buckets, evidence requirement.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    assert_abnormal_event,
    attempt_active,
    exam_ready_for_candidates,
    post_abnormal_event,
    abnormal_event_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Severity formula boundaries (PRD §3.4)
# ===========================================================================
SEVERITY_CASES = [
    # (rule, channel, mode, expected_score, expected_severity)
    # FACE_LEAVE (30) × SCREEN (1.0) × REALTIME (1.0) = 30 → INFO
    ("FACE_LEAVE", "SCREEN", "REALTIME_ALERT", 30.00, "INFO"),
    # FACE_LEAVE (30) × CAMERA (1.2) × REALTIME (1.0) = 36 → WARNING (>=35)
    ("FACE_LEAVE", "CAMERA", "REALTIME_ALERT", 36.00, "WARNING"),
    # WINDOW_SWITCH (40) × SCREEN (1.0) × REALTIME (1.0) = 40 → WARNING
    ("WINDOW_SWITCH", "SCREEN", "REALTIME_ALERT", 40.00, "WARNING"),
    # WINDOW_SWITCH (40) × SCREEN (1.0) × AFTER_THE_FACT (0.5) = 20 → INFO
    ("WINDOW_SWITCH", "SCREEN", "AFTER_THE_FACT", 20.00, "INFO"),
    # MULTI_PERSON (70) × SCREEN (1.0) × REALTIME (1.0) = 70 → CRITICAL
    ("MULTI_PERSON", "SCREEN", "REALTIME_ALERT", 70.00, "CRITICAL"),
    # MULTI_PERSON (70) × SCREEN (1.0) × AFTER_THE_FACT (0.5) = 35 → WARNING
    ("MULTI_PERSON", "SCREEN", "AFTER_THE_FACT", 35.00, "WARNING"),
    # EXTERNAL_DEVICE (80) × NETWORK (1.0) × REALTIME (1.0) = 80 → CRITICAL
    ("EXTERNAL_DEVICE", "NETWORK", "REALTIME_ALERT", 80.00, "CRITICAL"),
    # EXTERNAL_DEVICE (80) × PROCESS (1.1) × REALTIME (1.0) = 88 → CRITICAL
    ("EXTERNAL_DEVICE", "PROCESS", "REALTIME_ALERT", 88.00, "CRITICAL"),
]


@pytest.mark.parametrize(
    "rule,channel,mode,expected_score,expected_severity", SEVERITY_CASES,
)
def test_severity_classification_table(
    api, rule, channel, mode, expected_score, expected_severity,
):
    """PRD §3.4: severity_score = base * channel_mult * mode_mult, rounded
    half up to 2 dp. Bucket: < 35 INFO, [35, 70) WARNING, >= 70 CRITICAL.

    Base by rule: FACE_LEAVE=30, WINDOW_SWITCH=40, MULTI_PERSON=70,
    EXTERNAL_DEVICE=80. Channel: SCREEN/NETWORK=1.0, PROCESS=1.1,
    CAMERA/AUDIO=1.2. Mode: REALTIME_ALERT=1.0, AFTER_THE_FACT=0.5.
    """
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    # The MULTI_PERSON & EXTERNAL_DEVICE CRITICAL events trigger the
    # disqualification cascade; that's fine for these severity
    # classification tests — we only inspect the AbnormalEvent body.
    res = api.record_abnormal_event(
        exam["id"], attempt["id"],
        abnormal_event_payload(
            detected_at=1100,
            monitoring_channel=channel,
            behavior_rule_code=rule,
            marking_mode=mode,
            # Evidence required for non-INFO severities (PRD §3.4).
            evidence_clip_uri="s3://evidence/x.mp4",
        ),
        headers=__import__(
            "test_helpers", fromlist=["TEST_USERS"],
        ).TEST_USERS["proctor_headers"],
    )
    event = validate_success(res, 201)
    assert_abnormal_event(event)
    assert event["severity_score"] == pytest.approx(expected_score, abs=0.01)
    assert event["severity"] == expected_severity


def test_severity_boundary_exactly_70_is_critical(api):
    """PRD §3.4: "a score at least 70 is CRITICAL." Boundary precision:
    severity_score == 70.00 must classify CRITICAL (the >= edge).

    Difficulty design: boundary_precision_check /
    severity_score_70_boundary_critical_vs_warning.
    """
    # difficulty: boundary_precision_check/severity_score_70_boundary_critical_vs_warning
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    event = post_abnormal_event(
        exam["id"], attempt["id"],
        detected_at=1100,
        behavior_rule_code="MULTI_PERSON",
        monitoring_channel="SCREEN",
        marking_mode="REALTIME_ALERT",
    )
    assert event["severity_score"] == pytest.approx(70.00, abs=0.01)
    assert event["severity"] == "CRITICAL"


def test_severity_boundary_exactly_35_is_warning(api):
    """PRD §3.4: "a score at least 35 and strictly less than 70 is
    WARNING." Boundary precision: severity_score == 35.00 must classify
    WARNING (the lower inclusive edge).
    """
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    event = post_abnormal_event(
        exam["id"], attempt["id"],
        detected_at=1100,
        behavior_rule_code="MULTI_PERSON",
        monitoring_channel="SCREEN",
        marking_mode="AFTER_THE_FACT",
    )
    assert event["severity_score"] == pytest.approx(35.00, abs=0.01)
    assert event["severity"] == "WARNING"


# ===========================================================================
# Evidence requirement (PRD §3.4)
# ===========================================================================
def test_evidence_required_for_non_info_severity(api, proctor_headers):
    """PRD §3.4: "Whenever the computed severity is anything other than
    INFO, the evidence URI is mandatory; omitting it rejects the call
    with ERR_EVIDENCE_REQUIRED."
    """
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    # WINDOW_SWITCH × SCREEN × REALTIME = 40 → WARNING (non-INFO).
    payload = abnormal_event_payload(
        detected_at=1100,
        behavior_rule_code="WINDOW_SWITCH",
        monitoring_channel="SCREEN",
        marking_mode="REALTIME_ALERT",
        evidence_clip_uri=None,
    )
    res = api.record_abnormal_event(
        exam["id"], attempt["id"], payload, proctor_headers,
    )
    validate_error(res, "ERR_EVIDENCE_REQUIRED")


def test_evidence_not_required_for_info_severity(api, proctor_headers):
    """PRD §3.4: "Whenever the computed severity is anything other than
    INFO, the evidence URI is mandatory." Negative: INFO severity must
    NOT require evidence.
    """
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    # FACE_LEAVE × SCREEN × REALTIME = 30 → INFO (< 35).
    payload = abnormal_event_payload(
        detected_at=1100,
        behavior_rule_code="FACE_LEAVE",
        monitoring_channel="SCREEN",
        marking_mode="REALTIME_ALERT",
        evidence_clip_uri=None,
    )
    res = api.record_abnormal_event(
        exam["id"], attempt["id"], payload, proctor_headers,
    )
    event = validate_success(res, 201)
    assert event["severity"] == "INFO"


# ===========================================================================
# Difficulty design: severity_score realtime vs after-the-fact diverge
# ===========================================================================
def test_realtime_vs_after_the_fact_diverge_on_same_inputs(api,
                                                          proctor_headers):
    """PRD §3.4: "a REALTIME_ALERT event uses the full 1.0 marking-mode
    coefficient and may trigger the recheck; an AFTER_THE_FACT event
    uses the 0.5 coefficient and never triggers a recheck."

    Difficulty design: dual_variant_calc /
    severity_score_realtime_vs_after_the_fact_on_abnormal_event.
    """
    # difficulty: dual_variant_calc/severity_score_realtime_vs_after_the_fact_on_abnormal_event
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    # Two separate attempts to avoid cascade interference. Pre-register
    # both candidates while the exam is still in OPEN_REGISTRATION (PRD
    # §3.1 bars registration after the OPEN_REGISTRATION → READY close).
    from test_helpers import pre_register_candidates
    pre_register_candidates(exam, 2)
    reg1, attempt1, cid1 = attempt_active(exam)
    reg2, attempt2, cid2 = attempt_active(exam)

    e1 = post_abnormal_event(
        exam["id"], attempt1["id"],
        detected_at=1100,
        behavior_rule_code="MULTI_PERSON",
        monitoring_channel="SCREEN",
        marking_mode="REALTIME_ALERT",
        headers=proctor_headers,
    )
    e2 = post_abnormal_event(
        exam["id"], attempt2["id"],
        detected_at=1100,
        behavior_rule_code="MULTI_PERSON",
        monitoring_channel="SCREEN",
        marking_mode="AFTER_THE_FACT",
        headers=proctor_headers,
    )
    # Same rule + channel; only marking_mode differs.
    assert e1["severity_score"] == pytest.approx(70.00, abs=0.01)
    assert e1["severity"] == "CRITICAL"
    assert e2["severity_score"] == pytest.approx(35.00, abs=0.01)
    assert e2["severity"] == "WARNING"

    # Cascade on attempt1 (REALTIME CRITICAL on MULTI_PERSON → DQ).
    from test_helpers import make_candidate_headers
    a1_after = validate_success(
        api.get_attempt(
            exam["id"], attempt1["id"], make_candidate_headers(cid1),
        ), 200,
    )
    a2_after = validate_success(
        api.get_attempt(
            exam["id"], attempt2["id"], make_candidate_headers(cid2),
        ), 200,
    )
    assert a1_after["status"] == "DISQUALIFIED"
    assert a2_after["status"] == "ACTIVE"  # no cascade for AFTER_THE_FACT
