"""Payload factories — one per entity, input fields only."""
from .constants import COMPLIANT_HTML_BODY

DEFAULTS = {
    "ACCOUNT_NAME": "Acme",
    "AUDIENCE_NAME": "Main",
    "FROM_EMAIL": "hi@acme.com",
    "TEMPLATE_NAME": "T",
    "TEMPLATE_SUBJECT": "Spring Sale",
    "CAMPAIGN_NAME": "C1",
    "JOURNEY_NAME": "Welcome flow",
    "SEGMENT_NAME": "SEG",
}


def create_account_payload(**overrides) -> dict:
    """POST /accounts — name, plus optional plan_tier / initial_send_credits / hourly_send_capacity."""
    payload = {"name": DEFAULTS["ACCOUNT_NAME"]}
    payload.update(overrides)
    return payload


def create_account_user_payload(**overrides) -> dict:
    """POST /accounts/{id}/users — email + user_role."""
    payload = {"email": "author@acme.com", "user_role": "CAMPAIGN_AUTHOR"}
    payload.update(overrides)
    return payload


def create_audience_payload(account_id: str, **overrides) -> dict:
    """POST /audiences — account_id, name, default_from_email, optional double_optin_required."""
    payload = {
        "account_id": account_id,
        "name": DEFAULTS["AUDIENCE_NAME"],
        "default_from_email": DEFAULTS["FROM_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_subscriber_payload(**overrides) -> dict:
    """POST /audiences/{id}/subscribers — email, consent_source, optional first_name."""
    payload = {"email": "s1@x.com", "consent_source": "API"}
    payload.update(overrides)
    return payload


def create_import_job_payload(rows, expected_audience_version, **overrides) -> dict:
    """POST /audiences/{id}/import-jobs — rows + expected_audience_version."""
    payload = {"rows": rows, "expected_audience_version": expected_audience_version}
    payload.update(overrides)
    return payload


def create_segment_payload(**overrides) -> dict:
    """POST /audiences/{id}/segments — name, consent_states, min_engagement_score, optional max_days_since_open."""
    payload = {
        "name": DEFAULTS["SEGMENT_NAME"],
        "consent_states": ["CONFIRMED"],
        "min_engagement_score": 0,
    }
    payload.update(overrides)
    return payload


def create_template_payload(account_id: str, **overrides) -> dict:
    """POST /templates — account_id, name, subject, html_body."""
    payload = {
        "account_id": account_id,
        "name": DEFAULTS["TEMPLATE_NAME"],
        "subject": DEFAULTS["TEMPLATE_SUBJECT"],
        "html_body": COMPLIANT_HTML_BODY,
    }
    payload.update(overrides)
    return payload


def create_campaign_payload(account_id: str, audience_id: str, template_id: str, **overrides) -> dict:
    """POST /campaigns — account_id, audience_id, template_id, name, plus the optional A/B fields."""
    payload = {
        "account_id": account_id,
        "audience_id": audience_id,
        "template_id": template_id,
        "name": DEFAULTS["CAMPAIGN_NAME"],
    }
    payload.update(overrides)
    return payload


def review_payload(decision: str, note=None) -> dict:
    """POST /campaigns/{id}/review — decision APPROVE | REQUEST_CHANGES, optional note."""
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


def schedule_payload(scheduled_at: str, expected_account_version: int, send_window_minutes: int = 60) -> dict:
    """POST /campaigns/{id}/schedule — scheduled_at, send_window_minutes, expected_account_version."""
    return {
        "scheduled_at": scheduled_at,
        "send_window_minutes": send_window_minutes,
        "expected_account_version": expected_account_version,
    }


def create_journey_payload(account_id: str, audience_id: str, steps, **overrides) -> dict:
    """POST /journeys — account_id, audience_id, name, trigger_event, steps."""
    payload = {
        "account_id": account_id,
        "audience_id": audience_id,
        "name": DEFAULTS["JOURNEY_NAME"],
        "trigger_event": "SUBSCRIBE_CONFIRMED",
        "steps": steps,
    }
    payload.update(overrides)
    return payload


def wait_step(step_index: int, wait_hours: int) -> dict:
    return {"step_index": step_index, "kind": "WAIT", "wait_hours": wait_hours}


def email_step(step_index: int, template_id: str) -> dict:
    return {"step_index": step_index, "kind": "EMAIL", "template_id": template_id}


def condition_step(step_index: int, condition_min_score: int, on_true: int, on_false: int) -> dict:
    return {
        "step_index": step_index,
        "kind": "CONDITION",
        "condition_min_score": condition_min_score,
        "on_true_step_index": on_true,
        "on_false_step_index": on_false,
    }


def clock_payload(to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc."""
    return {"to_iso8601": to_iso8601}


def event_payload(send_id: str, kind: str) -> dict:
    """POST /_events/emit — send_id + kind."""
    return {"send_id": send_id, "kind": kind}


def confirm_payload(confirmation_token: str) -> dict:
    return {"confirmation_token": confirmation_token}


def unsubscribe_payload(unsubscribe_token: str) -> dict:
    return {"unsubscribe_token": unsubscribe_token}


def import_rows(emails) -> list:
    """Build an import `rows` array from a list of email strings."""
    return [{"email": e} for e in emails]
