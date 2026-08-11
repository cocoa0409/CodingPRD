"""SLA accounting: inclusive on-time boundary and lateness consequences."""
from datetime import datetime, timezone

from test_helpers import (
    TEST_USERS, get_consult, make_specialist_headers, set_clock,
    setup_assigned_consult, validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestSlaTimeliness:
    def test_on_time_at_exact_sla_deadline(self, api):
        """PRD §3.5: "A response created at or before `sla_due_at` — the boundary is
        inclusive — is recorded with `on_time` true; anything later is late."
        PRD §3.5: the consult's `sla_due_at` is "computed at assignment time as the
        consult's `created_at` plus the track's `urgent_target_hours` when the
        consult's `urgency` is `URGENT`, or plus the track's
        `response_time_target_hours` when it is `ROUTINE`."

        Design: Difficulty/boundary_precision_check/sla_on_time_at_exact_deadline_inclusive
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-BP1", provider_npi="1000000101",
            specialist_npi="2000000101",
            consult_overrides={
                "question_text": "Borderline QT prolongation on screening ECG before starting antiemetic; cardiology input requested.",
                "icd10_primary": "R94",
            },
        )
        consult = scenario["consult"]
        # 48h routine target from 2026-06-01T00:00:00Z -> 2026-06-03T00:00:00Z.
        assert _parse(consult["sla_due_at"]) == datetime(2026, 6, 3, tzinfo=timezone.utc)
        # Respond at the exact deadline instant.
        set_clock("2026-06-03T00:00:00Z")
        response = validate_success(api.create_response(
            consult["id"],
            {"disposition": "MANAGE_IN_PRIMARY_CARE",
             "recommendation_text": "QTc 470ms borderline; prefer ondansetron alternative metoclopramide and repeat ECG in 48h."},
            make_specialist_headers(scenario["specialist"]["id"]),
        ), 201)
        assert response["on_time"] is True, (
            "response created exactly at sla_due_at must be on_time (inclusive <=)"
        )

    def test_no_breach_or_review_flag_at_deadline(self, api):
        """PRD §3.5: "When a late response arrives, the consult's `sla_breached` flag
        is set true at that moment."
        PRD §3.5: review_required "flags the response for mandatory quality review
        when, at submission time, the membership's `standing` is `PROBATION`, or the
        `disposition` is `CONVERT_TO_VISIT`, or the response was not on time."

        Design: Difficulty/boundary_precision_check/sla_on_time_at_exact_deadline_inclusive
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-BP1", provider_npi="1000000101",
            specialist_npi="2000000101",
        )
        consult = scenario["consult"]
        set_clock("2026-06-03T00:00:00Z")  # exactly sla_due_at
        response = validate_success(api.create_response(
            consult["id"],
            {"disposition": "MANAGE_IN_PRIMARY_CARE",
             "recommendation_text": "QTc 470ms borderline; prefer ondansetron alternative metoclopramide and repeat ECG in 48h."},
            make_specialist_headers(scenario["specialist"]["id"]),
        ), 201)
        # On time at the boundary: no breach is set and no review gate is armed.
        assert get_consult(consult["id"])["sla_breached"] is False
        assert response["review_required"] is False

    def test_late_by_one_second_marks_on_time_false(self, api):
        """PRD §3.5: "A response created at or before `sla_due_at` — the boundary is
        inclusive — is recorded with `on_time` true; anything later is late. The
        response also records `response_minutes`, the whole minutes elapsed from the
        consult's creation to the response's creation. When a late response arrives,
        the consult's `sla_breached` flag is set true at that moment."

        Design: Corner/calculations/late_by_one_second_marks_on_time_false
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-C1", provider_npi="1000003001",
            specialist_npi="2000003001",
            consult_overrides={
                "question_text": "Carotid bruit found on exam, asymptomatic; asks about ultrasound urgency and statin start.",
                "icd10_primary": "R09",
            },
        )
        consult = scenario["consult"]
        # One second AFTER the 2026-06-03T00:00:00Z deadline.
        set_clock("2026-06-03T00:00:01Z")
        response = validate_success(api.create_response(
            consult["id"],
            {"disposition": "MANAGE_WITH_PLAN",
             "recommendation_text": "Carotid duplex within 2 weeks; start atorvastatin 40mg now for secondary prevention."},
            make_specialist_headers(scenario["specialist"]["id"]),
        ), 201)
        assert response["on_time"] is False
        # Whole minutes from creation to response: 48h00m01s truncates to 2880.
        assert response["response_minutes"] == 2880
        assert response["review_required"] is True, "lateness arms the review gate"
        assert get_consult(consult["id"])["sla_breached"] is True
