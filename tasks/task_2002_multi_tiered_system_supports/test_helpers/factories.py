"""Payload factories — one per writable resource, input fields only (PRD §3/§4)."""


def create_district_payload(name="District D", academic_year="2025-2026", **overrides):
    payload = {"name": name, "academic_year": academic_year}
    payload.update(overrides)
    return payload


def create_school_payload(name="School S", grade_span_low=3, grade_span_high=5,
                          **overrides):
    payload = {"name": name, "grade_span_low": grade_span_low,
               "grade_span_high": grade_span_high}
    payload.update(overrides)
    return payload


def create_screening_window_payload(window_kind="FALL", opens_on="2026-08-01",
                                    closes_on="2026-08-31", **overrides):
    payload = {"window_kind": window_kind, "opens_on": opens_on,
               "closes_on": closes_on}
    payload.update(overrides)
    return payload


def create_benchmark_cut_point_payload(window_kind="FALL", grade_level=3,
                                       subject="READING", tier2_max_score=100,
                                       tier3_max_score=70, **overrides):
    payload = {"window_kind": window_kind, "grade_level": grade_level,
               "subject": subject, "tier2_max_score": tier2_max_score,
               "tier3_max_score": tier3_max_score}
    payload.update(overrides)
    return payload


def create_student_payload(full_name="Student", grade_level=3, **overrides):
    payload = {"full_name": full_name, "grade_level": grade_level}
    payload.update(overrides)
    return payload


def record_screening_score_payload(student_id, subject="READING", raw_score=80,
                                   **overrides):
    payload = {"student_id": student_id, "subject": subject, "raw_score": raw_score}
    payload.update(overrides)
    return payload


def create_catalog_entry_payload(title="Read Naturally", subject="READING",
                                 tier_target="TIER_2", grade_min=3, grade_max=5,
                                 session_minutes=30, sessions_per_week=3,
                                 probe_frequency="WEEKLY", **overrides):
    payload = {"title": title, "subject": subject, "tier_target": tier_target,
               "grade_min": grade_min, "grade_max": grade_max,
               "session_minutes": session_minutes,
               "sessions_per_week": sessions_per_week,
               "probe_frequency": probe_frequency}
    payload.update(overrides)
    return payload


def create_interventionist_payload(full_name="Interventionist I",
                                   weekly_minute_capacity=600,
                                   subjects=None, **overrides):
    payload = {"full_name": full_name,
               "weekly_minute_capacity": weekly_minute_capacity,
               "subjects": list(subjects) if subjects is not None else ["READING"]}
    payload.update(overrides)
    return payload


def create_plan_payload(catalog_entry_id, interventionist_id, expected_student_version,
                        **overrides):
    payload = {"catalog_entry_id": catalog_entry_id,
               "interventionist_id": interventionist_id,
               "expected_student_version": expected_student_version}
    payload.update(overrides)
    return payload


def plan_action_payload(expected_plan_version, **overrides):
    payload = {"expected_plan_version": expected_plan_version}
    payload.update(overrides)
    return payload


def exit_plan_payload(expected_plan_version, exit_kind, **overrides):
    payload = {"expected_plan_version": expected_plan_version, "exit_kind": exit_kind}
    payload.update(overrides)
    return payload


def record_probe_payload(administered_on, score, **overrides):
    payload = {"administered_on": administered_on, "score": score}
    payload.update(overrides)
    return payload


def record_session_payload(scheduled_on, minutes=30, outcome="DELIVERED", **overrides):
    payload = {"scheduled_on": scheduled_on, "minutes": minutes, "outcome": outcome}
    payload.update(overrides)
    return payload


def propose_tier_movement_payload(to_tier, rationale, expected_student_version,
                                  **overrides):
    payload = {"to_tier": to_tier, "rationale": rationale,
               "expected_student_version": expected_student_version}
    payload.update(overrides)
    return payload


def create_team_meeting_payload(scheduled_on="2026-08-06", **overrides):
    payload = {"scheduled_on": scheduled_on}
    payload.update(overrides)
    return payload


def ratify_payload(movement_id, expected_student_version, **overrides):
    payload = {"movement_id": movement_id,
               "expected_student_version": expected_student_version}
    payload.update(overrides)
    return payload


def record_consent_payload(consent_received_on, **overrides):
    payload = {"consent_received_on": consent_received_on}
    payload.update(overrides)
    return payload
