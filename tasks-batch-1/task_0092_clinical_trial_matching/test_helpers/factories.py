"""Payload factories — one per write endpoint, input fields only (PRD §3)."""


# ─── Clock (PRD §3.8) ───────────────────────────────────


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


# ─── Trial (PRD §3.1) ───────────────────────────────────


def create_trial_payload(**overrides) -> dict:
    payload = {
        "title": "Test Trial",
        "target_enrollment": 5,
        "randomization_method": "SIMPLE",
    }
    payload.update(overrides)
    return payload


# ─── EligibilityCriterion (PRD §3.1) ────────────────────


def create_criterion_payload(**overrides) -> dict:
    payload = {
        "kind": "INCLUSION",
        "attribute": "age_years",
        "comparator": "GE",
        "threshold": 18,
    }
    payload.update(overrides)
    return payload


# ─── RandomizationArm (PRD §3.1) ────────────────────────


def create_arm_payload(**overrides) -> dict:
    payload = {
        "name": "TREATMENT",
        "allocation_weight": 1,
    }
    payload.update(overrides)
    return payload


# ─── ConsentDocument (PRD §3.2) ─────────────────────────


def create_consent_document_payload(**overrides) -> dict:
    payload = {"body_hash": "h1"}
    payload.update(overrides)
    return payload


def activate_consent_payload(expected_trial_version: int, **overrides) -> dict:
    payload = {"expected_trial_version": expected_trial_version}
    payload.update(overrides)
    return payload


# ─── IRBReview (PRD §3.2) ───────────────────────────────


def create_irb_review_payload(scope: str = "PROTOCOL", **overrides) -> dict:
    payload = {"scope": scope}
    payload.update(overrides)
    return payload


def decide_irb_review_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ─── Participant (PRD §3.3) ─────────────────────────────


def create_participant_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Participant",
        "age_years": 40,
        "weight_kg": 80,
        "hba1c": 6.0,
    }
    payload.update(overrides)
    return payload


def update_participant_payload(**overrides) -> dict:
    return dict(overrides)


# ─── Screening (PRD §3.3) ───────────────────────────────


def screen_participant_payload(participant_id: str, **overrides) -> dict:
    payload = {"participant_id": participant_id}
    payload.update(overrides)
    return payload


# ─── Enrollment (PRD §3.4) ──────────────────────────────


def create_enrollment_payload(screening_id: str, **overrides) -> dict:
    payload = {"screening_id": screening_id}
    payload.update(overrides)
    return payload


def transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ─── Visit (PRD §3.6) ───────────────────────────────────


def create_visit_payload(sequence_index: int, scheduled_at: str,
                         draw_window_minutes: int, **overrides) -> dict:
    payload = {
        "sequence_index": sequence_index,
        "scheduled_at": scheduled_at,
        "draw_window_minutes": draw_window_minutes,
    }
    payload.update(overrides)
    return payload


def complete_visit_payload(drawn_at: str, **overrides) -> dict:
    payload = {"drawn_at": drawn_at}
    payload.update(overrides)
    return payload


# ─── AdverseEvent (PRD §3.5) ────────────────────────────


def create_adverse_event_payload(severity: str, occurred_at: str, **overrides) -> dict:
    payload = {
        "severity": severity,
        "occurred_at": occurred_at,
    }
    payload.update(overrides)
    return payload


def review_adverse_event_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload
