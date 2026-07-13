"""Payload factories — one per entity, input fields only."""

DEFAULT_SEASON = {
    "season_start": "2026-03-01T00:00:00Z",
    "season_end": "2026-09-01T00:00:00Z",
}

_email_counter = [0]


def unique_email(prefix="g") -> str:
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


def create_garden_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Community Garden",
        "season_label": "2026-MAIN",
        "season_start": DEFAULT_SEASON["season_start"],
        "season_end": DEFAULT_SEASON["season_end"],
    }
    defaults.update(overrides)
    return defaults


def create_plot_payload(garden_id, size="MEDIUM", label="P-1", **overrides) -> dict:
    defaults = {"garden_id": garden_id, "label": label, "size": size}
    defaults.update(overrides)
    return defaults


def create_gardener_payload(full_name="Test Gardener", email=None, **overrides) -> dict:
    defaults = {"full_name": full_name, "email": email or unique_email()}
    defaults.update(overrides)
    return defaults


def create_application_payload(gardener_id, garden_id, requested_size="MEDIUM", **overrides) -> dict:
    defaults = {
        "gardener_id": gardener_id,
        "garden_id": garden_id,
        "requested_size": requested_size,
    }
    defaults.update(overrides)
    return defaults


def assign_plot_payload(gardener_id, expected_plot_version, **overrides) -> dict:
    defaults = {
        "gardener_id": gardener_id,
        "expected_plot_version": expected_plot_version,
    }
    defaults.update(overrides)
    return defaults


def create_work_log_payload(assignment_id, hours, logged_on="2026-06-15T00:00:00Z", **overrides) -> dict:
    defaults = {"assignment_id": assignment_id, "hours": hours, "logged_on": logged_on}
    defaults.update(overrides)
    return defaults


def create_water_reading_payload(assignment_id, period_index, gallons_used,
                                 recorded_on="2026-04-01T00:00:00Z", **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "period_index": period_index,
        "gallons_used": gallons_used,
        "recorded_on": recorded_on,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_case_payload(assignment_id, violation_type="NEGLECT", **overrides) -> dict:
    defaults = {"assignment_id": assignment_id, "violation_type": violation_type}
    defaults.update(overrides)
    return defaults


def create_tool_payload(garden_id, name="Wheelbarrow 1", category="CART", **overrides) -> dict:
    defaults = {"garden_id": garden_id, "name": name, "category": category}
    defaults.update(overrides)
    return defaults


def create_tool_loan_payload(tool_id, gardener_id, checked_out_at, due_at, **overrides) -> dict:
    defaults = {
        "tool_id": tool_id,
        "gardener_id": gardener_id,
        "checked_out_at": checked_out_at,
        "due_at": due_at,
    }
    defaults.update(overrides)
    return defaults


def create_shed_booking_payload(garden_id, gardener_id, starts_at, ends_at,
                                purpose="STORAGE", **overrides) -> dict:
    defaults = {
        "garden_id": garden_id,
        "gardener_id": gardener_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "purpose": purpose,
    }
    defaults.update(overrides)
    return defaults
