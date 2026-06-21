"""Corner Coverage — endpoints, errors, and rbac sections.

Filtered list endpoints; triggerable ERR_AUTHORIZATION_EXHAUSTED at create;
RBAC denials for BillingClerk and Therapist; missing-auth ERR_UNAUTHENTICATED.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    set_clock,
    setup_active_poc,
    setup_poc_with_grant,
    create_grant,
    schedule_visit,
    complete_visit,
    finalize_visit,
    create_visit_payload,
    complete_visit_payload,
    finalize_visit_payload,
    make_therapist_headers,
    TEST_USERS,
)


# ─── Section: endpoints ─────────────────────────────────────────


def test_visits_list_filtered_by_authorization_grant_id(api):
    """PRD §4: "GET | /rehab/visits | List Visits with optional filters."
    PRD §2.3: "Each list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/visits_list_filtered_by_authorization_grant_id
    """
    ctx = setup_active_poc(insurance_type="COMMERCIAL")
    th = ctx["therapist"]["id"]
    grantA = create_grant(
        ctx["poc"]["id"], total_units_granted=10,
        effective_from="2026-06-01", effective_to="2026-06-30",
    )
    grantB = create_grant(
        ctx["poc"]["id"], total_units_granted=10,
        effective_from="2026-07-01", effective_to="2026-07-31",
    )
    # 2 visits under A, 1 under B.
    for date in ("2026-06-02", "2026-06-03"):
        schedule_visit(grantA["id"], th, f"{date}T09:00:00Z", f"{date}T09:30:00Z",
                       planned_minutes=30, cpt_code="CPT_97110_THER_EX")
    schedule_visit(grantB["id"], th, "2026-07-02T09:00:00Z", "2026-07-02T09:30:00Z",
                   planned_minutes=30, cpt_code="CPT_97110_THER_EX")
    # Filter by grant A — only 2 should appear.
    data, meta = validate_paginated(
        api.list_visits(TEST_USERS["billing_clerk_headers"],
                        params={"authorization_grant_id": grantA["id"]})
    )
    assert len(data) == 2
    for v in data:
        assert v["authorization_grant_id"] == grantA["id"]


# ─── Section: errors ────────────────────────────────────────────


def test_err_authorization_exhausted_triggers_on_visit_create_when_grant_full(api):
    """PRD §3.5: "if the visit would push `units_consumed` past `total_units_granted`
    on the grant, the scheduling call is rejected with `ERR_AUTHORIZATION_EXHAUSTED`
    (HTTP 409)."

    Design: Corner/errors/err_authorization_exhausted_triggers_on_visit_create_when_grant_full
    """
    ctx = setup_poc_with_grant(
        insurance_type="COMMERCIAL", total_units_granted=2,
    )
    th = ctx["therapist"]["id"]
    gid = ctx["grant"]["id"]
    # 1st visit: 30min/CPT_97110 → planned_units=2 → consumed=2 (full).
    schedule_visit(gid, th, "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z",
                   planned_minutes=30, cpt_code="CPT_97110_THER_EX")
    # 2nd visit pushes past total → rejected.
    res = api.create_visit(
        create_visit_payload(
            authorization_grant_id=gid, therapist_id=th,
            scheduled_start_utc="2026-06-03T09:00:00Z",
            scheduled_end_utc="2026-06-03T09:15:00Z",
            planned_minutes=15, cpt_code="CPT_97110_THER_EX",
        ),
        make_therapist_headers(th),
    )
    validate_error(res, "ERR_AUTHORIZATION_EXHAUSTED", expected_status=409)


# ─── Section: rbac ──────────────────────────────────────────────


def test_billing_clerk_cannot_complete_visit(api):
    """PRD §4: "POST | /rehab/visits/{id}/complete | Mark a SCHEDULED Visit COMPLETED
    with delivered minutes. | Therapist |"
    PRD §2.1: "A call whose role is not on the endpoint's authorized list (see §4) is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/billing_clerk_cannot_complete_visit
    """
    ctx = setup_poc_with_grant(insurance_type="COMMERCIAL", total_units_granted=10)
    th = ctx["therapist"]["id"]
    v = schedule_visit(
        ctx["grant"]["id"], th,
        "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z",
        planned_minutes=30, cpt_code="CPT_97110_THER_EX",
    )
    # BillingClerk attempts /complete — not in the authorized list.
    res = api.complete_visit(
        v["id"], complete_visit_payload(actual_minutes=30),
        TEST_USERS["billing_clerk_headers"],
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_therapist_cannot_finalize_visit(api):
    """PRD §4: "POST | /rehab/visits/{id}/finalize | Bill a COMPLETED Visit; cascades
    cumulative_billed_cents and capped_status. | BillingClerk |"
    PRD §2.1: "A call whose role is not on the endpoint's authorized list (see §4) is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/therapist_cannot_finalize_visit
    """
    ctx = setup_poc_with_grant(
        insurance_type="MEDICARE", medicare_enrolled=True,
        total_units_granted=10,
    )
    th = ctx["therapist"]["id"]
    v = schedule_visit(
        ctx["grant"]["id"], th,
        "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z",
        planned_minutes=30, cpt_code="CPT_97110_THER_EX",
    )
    complete_visit(v["id"], th, actual_minutes=30)
    poc_v = get_success_data(
        api.get_plan_of_care(ctx["poc"]["id"], TEST_USERS["billing_clerk_headers"])
    )["version"]
    # Therapist attempts /finalize — BillingClerk-only.
    res = api.finalize_visit(
        v["id"], finalize_visit_payload(expected_plan_of_care_version=poc_v),
        make_therapist_headers(th),
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two HTTP headers: `X-User-ID`,
    which uniquely identifies the acting principal, and `X-User-Role`, which names that
    principal's operational capacity. Either header missing — or both — causes the
    request to be rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_patients({})  # no auth headers at all
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
