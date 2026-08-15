"""Payload factories — one per creatable resource, input fields only.

Optional fields are omitted unless a value is supplied, so factories never
smuggle defaults the server is responsible for applying.
"""


def create_staff_payload(full_name="Test Staff", role_capability="REPORTER",
                         home_desk="METRO", hourly_rate_cents=6000,
                         max_concurrent_assignments=None) -> dict:
    payload = {
        "full_name": full_name,
        "role_capability": role_capability,
        "home_desk": home_desk,
        "hourly_rate_cents": hourly_rate_cents,
    }
    if max_concurrent_assignments is not None:
        payload["max_concurrent_assignments"] = max_concurrent_assignments
    return payload


def create_pitch_payload(title="Test Pitch", summary="Angle summary",
                         desk="METRO", deadline_at="2026-08-03T00:00:00Z",
                         urgency="STANDARD") -> dict:
    return {
        "title": title,
        "summary": summary,
        "desk": desk,
        "deadline_at": deadline_at,
        "urgency": urgency,
    }


def create_assignment_payload(story_id, staff_id, assignment_role="REPORTER",
                              start_at="2026-08-01T08:00:00Z",
                              end_at="2026-08-01T09:00:00Z",
                              planned_effort_minutes=60) -> dict:
    return {
        "story_id": story_id,
        "staff_id": staff_id,
        "assignment_role": assignment_role,
        "start_at": start_at,
        "end_at": end_at,
        "planned_effort_minutes": planned_effort_minutes,
    }


def create_review_payload(review_type, verdict, expected_story_version,
                          notes=None) -> dict:
    payload = {
        "review_type": review_type,
        "verdict": verdict,
        "expected_story_version": expected_story_version,
    }
    if notes is not None:
        payload["notes"] = notes
    return payload


def schedule_payload(slot_id, expected_story_version) -> dict:
    return {
        "slot_id": slot_id,
        "expected_story_version": expected_story_version,
    }


def create_slot_payload(channel="PRINT",
                        window_start="2026-08-05T18:00:00Z",
                        window_end="2026-08-05T19:00:00Z",
                        capacity=1) -> dict:
    return {
        "channel": channel,
        "window_start": window_start,
        "window_end": window_end,
        "capacity": capacity,
    }


def create_correction_payload(severity="MINOR",
                              correction_text="Correction text") -> dict:
    return {
        "severity": severity,
        "correction_text": correction_text,
    }


def create_analytics_report_payload(variant="SETTLED",
                                    window_start="2026-08-01T07:00:00Z",
                                    window_end="2026-08-02T07:00:00Z",
                                    views=100, engagement_minutes=50) -> dict:
    return {
        "variant": variant,
        "window_start": window_start,
        "window_end": window_end,
        "views": views,
        "engagement_minutes": engagement_minutes,
    }


def create_breaking_event_payload(title="Breaking event", priority_band=2,
                                  window_start="2026-08-01T09:00:00Z",
                                  window_end="2026-08-01T12:00:00Z",
                                  call_in_pool_size=None) -> dict:
    payload = {
        "title": title,
        "priority_band": priority_band,
        "window_start": window_start,
        "window_end": window_end,
    }
    if call_in_pool_size is not None:
        payload["call_in_pool_size"] = call_in_pool_size
    return payload
