"""Operations report (pinned rounding order), list pagination, and RBAC authorization."""
from test_helpers import (
    api_client as api,
    validate_success, validate_error, validate_paginated,
    create_team_payload, create_risk_screening_payload, TEST_USERS,
    create_contact, create_screened_contact, set_clock,
)

SUP = TEST_USERS["supervisor_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _two_de_escalation_contacts_disposed_at_4m20s_and_7m30s():
    """Two MODERATE contacts created at clock 00:00; c2 disposed DE_ESCALATION at 00:04:20,
    c1 disposed DE_ESCALATION at 00:07:30. Per-contact minutes round 4.333->4 and 7.5->8."""
    c1 = create_screened_contact("att-c1", band="MODERATE")
    c2 = create_screened_contact("att-c2", band="MODERATE")
    set_clock("2026-03-01T00:04:20Z")
    validate_success(api.contact_state(c2["id"], {"to_status": "DE_ESCALATION"}, COUNSELOR), 200)
    set_clock("2026-03-01T00:07:30Z")
    validate_success(api.contact_state(c1["id"], {"to_status": "DE_ESCALATION"}, COUNSELOR), 200)


# ─── combinatorial_formula / avg_time_to_disposition_rounds_per_contact_before_sum ─

def test_avg_time_to_disposition_rounds_per_contact_before_summing():
    """PRD §3.9: "First, for each contact in the population, compute the elapsed time from its `created_at` to its `disposition_at` in minutes and round that per-contact figure to a whole number of minutes using round-half-up — this per-contact rounding happens before any summing."
    PRD §3.9: "Otherwise, sum the already-rounded per-contact minutes, divide by the number of contacts in the population, and round that mean to one decimal place using round-half-up."

    Per-contact 4.333->4 and 7.5->8; (4+8)/2 = 6.0 (sum-then-round would give 5.9).

    Design: Difficulty/combinatorial_formula/avg_time_to_disposition_rounds_per_contact_before_sum
    """
    _two_de_escalation_contacts_disposed_at_4m20s_and_7m30s()
    report = validate_success(api.get_operations_report(SUP), 200)
    assert report["avg_time_to_disposition_minutes"] == 6.0, (
        f"expected 6.0 (per-contact rounding first), got {report['avg_time_to_disposition_minutes']}"
    )
    assert report["total_contacts"] == 2, f"expected total_contacts 2, got {report['total_contacts']}"


def test_avg_time_to_disposition_empty_population_is_zero():
    """PRD §3.9: "The average-time-to-disposition figure is computed over the population of contacts that have a non-null `disposition_at` falling within the report window, treated as a half-open interval with `window_start` inclusive and `window_end` exclusive"
    PRD §3.9: "Then, if the population is empty, the average is 0.0."

    A window [00:10:00, 00:20:00) excludes both disposition_at times, so the population is
    empty and the average is 0.0.

    Design: Difficulty/combinatorial_formula/avg_time_to_disposition_rounds_per_contact_before_sum
    """
    _two_de_escalation_contacts_disposed_at_4m20s_and_7m30s()
    report = validate_success(api.get_operations_report(
        SUP, params={"window_start": "2026-03-01T00:10:00Z", "window_end": "2026-03-01T00:20:00Z"}), 200)
    assert report["avg_time_to_disposition_minutes"] == 0.0, (
        f"expected 0.0 for empty population, got {report['avg_time_to_disposition_minutes']}"
    )


# ─── Corner / contacts_list_returns_pagination_envelope ────────────────────────

def test_contacts_list_returns_pagination_envelope():
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100."
    PRD §2.3: "Each list response carries the pagination bookkeeping in the `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/contacts_list_returns_pagination_envelope
    """
    create_contact("pg-1", channel="PHONE")
    create_contact("pg-2", channel="CHAT")
    data, meta = validate_paginated(api.list_contacts(SUP, params={"limit": 1, "offset": 0}))
    assert len(data) == 1, f"expected 1 item with limit=1, got {len(data)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more True, got {meta['has_more']}"


# ─── Corner / RBAC ─────────────────────────────────────────────────────────────

def test_counselor_cannot_create_team():
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §2.1: "and in addition it exclusively owns team creation, center creation, closing a resolved contact, and the operations report."

    Design: Corner/rbac/counselor_cannot_create_team_returns_unauthorized
    """
    res = api.create_team(create_team_payload(name="Team U"), COUNSELOR)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_dispatcher_cannot_submit_screening():
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §2.1: "A `CrisisCounselor` handles the clinical stream: risk screening, safety-plan authoring and transitions, wellness-check outreach attempts, plus shared intake and the clinical disposition branches."

    Design: Corner/rbac/dispatcher_cannot_submit_screening_returns_unauthorized
    """
    contact = create_contact("rb-a-01", channel="PHONE")
    res = api.create_risk_screening(create_risk_screening_payload(
        contact["id"], screening_type="COMPREHENSIVE", suicidal_ideation=1,
        plan_specificity=1, means_access=False, prior_attempts=0), DISPATCHER)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_counselor_cannot_view_operations_report():
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §2.1: "and in addition it exclusively owns team creation, center creation, closing a resolved contact, and the operations report."

    Design: Corner/rbac/counselor_cannot_view_operations_report_returns_unauthorized
    """
    res = api.get_operations_report(COUNSELOR)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
