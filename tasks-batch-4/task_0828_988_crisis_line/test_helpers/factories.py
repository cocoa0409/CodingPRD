"""Payload factories — one per entity, input fields only."""

# Default dated windows anchored on the logical-clock startup day.
DEFAULT_SHIFT_START = "2026-03-01T00:00:00Z"
DEFAULT_SHIFT_END = "2026-03-01T12:00:00Z"
DEFAULT_WINDOW_START = "2026-03-01T00:30:00Z"
DEFAULT_WINDOW_END = "2026-03-01T01:00:00Z"
DEFAULT_BED_WINDOW_START = "2026-03-01T02:00:00Z"
DEFAULT_BED_WINDOW_END = "2026-03-01T06:00:00Z"


def create_contact_payload(channel="PHONE", caller_key="ck-default", **overrides) -> dict:
    defaults = {"channel": channel, "caller_key": caller_key}
    defaults.update(overrides)
    return defaults


def create_risk_screening_payload(contact_id, screening_type="COMPREHENSIVE",
                                   suicidal_ideation=0, plan_specificity=0,
                                   means_access=False, prior_attempts=0, **overrides) -> dict:
    defaults = {
        "contact_id": contact_id,
        "screening_type": screening_type,
        "suicidal_ideation": suicidal_ideation,
        "plan_specificity": plan_specificity,
        "means_access": means_access,
        "prior_attempts": prior_attempts,
    }
    defaults.update(overrides)
    return defaults


def create_safety_plan_payload(contact_id, coping_strategies=None,
                               warning_signs=None, **overrides) -> dict:
    defaults = {
        "contact_id": contact_id,
        "coping_strategies": coping_strategies if coping_strategies is not None else ["breathe"],
        "warning_signs": warning_signs if warning_signs is not None else ["insomnia"],
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(name="Test Team", coverage_zone="Z1", capacity=1,
                        shift_start=DEFAULT_SHIFT_START, shift_end=DEFAULT_SHIFT_END,
                        **overrides) -> dict:
    defaults = {
        "name": name,
        "coverage_zone": coverage_zone,
        "capacity": capacity,
        "shift_start": shift_start,
        "shift_end": shift_end,
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(contact_id, team_id, expected_team_version,
                            window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END,
                            requested_acuity="HIGH", **overrides) -> dict:
    defaults = {
        "contact_id": contact_id,
        "team_id": team_id,
        "window_start": window_start,
        "window_end": window_end,
        "requested_acuity": requested_acuity,
        "expected_team_version": expected_team_version,
    }
    defaults.update(overrides)
    return defaults


def create_center_payload(name="Test Center", bed_capacity=1,
                          accepted_acuities=None, **overrides) -> dict:
    defaults = {
        "name": name,
        "bed_capacity": bed_capacity,
        "accepted_acuities": accepted_acuities if accepted_acuities is not None else ["HIGH"],
    }
    defaults.update(overrides)
    return defaults


def create_bed_referral_payload(contact_id, crisis_center_id, expected_crisis_center_version,
                                acuity="HIGH", window_start=DEFAULT_BED_WINDOW_START,
                                window_end=DEFAULT_BED_WINDOW_END, **overrides) -> dict:
    defaults = {
        "contact_id": contact_id,
        "crisis_center_id": crisis_center_id,
        "acuity": acuity,
        "window_start": window_start,
        "window_end": window_end,
        "expected_crisis_center_version": expected_crisis_center_version,
    }
    defaults.update(overrides)
    return defaults
