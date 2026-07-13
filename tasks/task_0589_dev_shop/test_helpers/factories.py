"""Payload factories — one per entity, input fields only (PRD 3.x)."""
import itertools

_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_client_payload(**overrides) -> dict:
    """Client registration (PRD 3.1)."""
    defaults = {
        "name": _unique("Acme Corp"),
        "billing_email": "ap@acme.test",
        "country_code": "US",
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(**overrides) -> dict:
    """Lead creation (PRD 3.1). All three fields are required."""
    defaults = {
        "client_id": None,
        "title": "Acme Portal",
        "source_channel": "REFERRAL",
    }
    defaults.update(overrides)
    return defaults


def qualify_payload(**overrides) -> dict:
    """Qualification decision (PRD 3.1). `note` is optional."""
    defaults = {"outcome": "QUALIFY"}
    defaults.update(overrides)
    return defaults


def sow_payload(**overrides) -> dict:
    """Statement of work (PRD 3.1)."""
    defaults = {
        "billing_model": "TIME_AND_MATERIALS",
        "contract_value": 100000.00,
        "budget_hours_cap": 500,
        "standard_hourly_rate": 200.00,
        "start_date": "2026-05-01",
        "end_date": "2026-08-31",
    }
    defaults.update(overrides)
    return defaults


def sign_payload(**overrides) -> dict:
    """SOW signature (PRD 3.1)."""
    defaults = {"signed_by_name": "Ada Client"}
    defaults.update(overrides)
    return defaults


def create_milestone_payload(**overrides) -> dict:
    """Milestone creation (PRD 3.2)."""
    defaults = {
        "engagement_id": None,
        "sequence": 1,
        "title": "Phase 1 - Design",
        "amount": 5000.00,
        "due_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_sprint_payload(**overrides) -> dict:
    """Sprint creation (PRD 3.2). `milestone_id` is optional."""
    defaults = {
        "engagement_id": None,
        "name": "Sprint 1",
        "start_date": "2026-05-04",
        "end_date": "2026-05-18",
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(**overrides) -> dict:
    """Ticket creation (PRD 3.3). `blocking_ticket_id` is optional."""
    defaults = {
        "sprint_id": None,
        "title": "Checkout flow",
        "estimated_hours": 8,
        "assignee_user_id": "eng-001",
    }
    defaults.update(overrides)
    return defaults


def create_time_entry_payload(**overrides) -> dict:
    """Time-entry creation (PRD 3.4). `billable` (default true) and `note` are
    optional and are deliberately omitted from the defaults so that the
    server-side default is exercised unless a test overrides it."""
    defaults = {
        "ticket_id": None,
        "work_date": "2026-05-05",
        "hours": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_change_request_payload(**overrides) -> dict:
    """Change-request creation (PRD 3.6)."""
    defaults = {
        "engagement_id": None,
        "title": "Add multi-currency checkout",
        "delta_hours": 30,
        "rush": False,
        "expected_engagement_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(**overrides) -> dict:
    """Release creation (PRD 3.7)."""
    defaults = {
        "engagement_id": None,
        "milestone_id": None,
        "version_label": "v1.0.0",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    """Invoice creation (PRD 3.8). milestone_id / retainer_id / period_start /
    period_end are supplied only as the kind demands."""
    defaults = {
        "engagement_id": None,
        "kind": "MILESTONE",
        "expected_engagement_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_retainer_payload(**overrides) -> dict:
    """Retainer creation (PRD 3.9)."""
    defaults = {
        "client_id": None,
        "engagement_id": None,
        "start_date": "2026-05-01",
        "end_date": "2026-07-31",
        "monthly_fee": 4000.00,
        "included_hours": 10,
        "sla_tier": "GOLD",
    }
    defaults.update(overrides)
    return defaults


def create_support_incident_payload(**overrides) -> dict:
    """Support-incident creation (PRD 3.9)."""
    defaults = {
        "retainer_id": None,
        "severity": "SEV1",
        "summary": "Checkout returns 500",
    }
    defaults.update(overrides)
    return defaults
