"""Entity creation/read contract, computed-field reads, listing, RBAC
segregation of duties, ownership, and the missing-header guard.

Covers corner entity / endpoint / rbac / consistency_model instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_plan, assert_event, assert_invoice,
    create_plan_payload, create_beneficiary_payload, create_event_payload,
    create_payment_payload, terminate_early_payload, set_clock_payload,
    TEST_USERS, make_beneficiary_headers, make_role_headers,
)
from test_helpers import fixtures as fx

_ADMIN = TEST_USERS["plan_administrator_headers"]
_SPONSOR = TEST_USERS["plan_sponsor_headers"]
_BILLING = TEST_USERS["billing_agent_headers"]


def test_create_plan_applies_defaults(api):
    """PRD §3.1: "The administrative load applied to the applicable premium for
    ordinary coverage months is standard_admin_fee_pct, defaulting to 0.02 (two
    percent) and constrained to the range from zero through 0.02 inclusive."
    PRD §3.1: "The length of the election window is election_window_days,
    defaulting to 60."
    PRD §3.1: "The grace period for the very first premium is
    initial_premium_grace_days, defaulting to 45".
    PRD §3.1: "A newly created plan has status of ACTIVE; the only other plan
    status is TERMINATED."

    Design: Corner/entities/create_plan_returns_201_with_defaults_applied
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    resp = api.create_plan(create_plan_payload(name="Defaults Plan", applicable_premium_cents=60000), _ADMIN)
    plan = validate_success(resp, 201)
    assert_plan(plan)
    assert plan["standard_admin_fee_pct"] == 0.02, f"std fee {plan['standard_admin_fee_pct']}"
    assert plan["election_window_days"] == 60, f"window {plan['election_window_days']}"
    assert plan["initial_premium_grace_days"] == 45, f"grace {plan['initial_premium_grace_days']}"
    assert plan["status"] == "ACTIVE", f"status {plan['status']}"


def test_create_beneficiary_missing_relationship_rejected(api):
    """PRD §2.9: "request-body shape — enum members must be recognized values,
    monetary amounts must be greater than zero, any coverage_month must be a
    well-formed YYYY-MM string, and required fields must be present
    (ERR_INVALID_REQUEST)".
    PRD §3.1: "a PlanAdministrator or a PlanSponsor registers a qualified
    beneficiary by supplying the plan_id it belongs to, the full_name, the
    relationship (one of EMPLOYEE, SPOUSE, or DEPENDENT), and the
    original_coverage_start date".

    Design: Corner/entities/create_beneficiary_missing_required_field_returns_invalid_request
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    payload = create_beneficiary_payload(plan["id"])
    del payload["relationship"]
    resp = api.create_beneficiary(payload, _SPONSOR)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_create_event_invalid_event_type_rejected(api):
    """PRD §3.2: "The recognized event types are TERMINATION, REDUCTION_OF_HOURS,
    DIVORCE, DEATH_OF_EMPLOYEE, MEDICARE_ENTITLEMENT, and DEPENDENT_AGE_OUT."

    Design: Corner/entities/create_event_invalid_enum_event_type_returns_invalid_request
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])
    payload = create_event_payload(plan["id"], ben["id"], event_type="FURLOUGH")
    resp = api.create_event(payload, _SPONSOR)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_get_nonexistent_enrollment_returns_not_found(api):
    """PRD §2.7: "the server validates the path resource and any
    foreign-key-referenced resources from left to right, rejecting with
    ERR_NOT_FOUND the first identifier in the chain that does not resolve to an
    existing resource."

    Design: Corner/entities/get_enrollment_nonexistent_id_returns_not_found
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    resp = api.get_enrollment("00000000-0000-4000-8000-000000000000", _ADMIN)
    validate_error(resp, "ERR_NOT_FOUND")


def test_divorce_event_computes_36_max_coverage_months(api):
    """PRD §3.2: "the system computes the base maximum COBRA duration into
    max_coverage_months: a TERMINATION or a REDUCTION_OF_HOURS yields 18 months,
    while a DIVORCE, a DEATH_OF_EMPLOYEE, a MEDICARE_ENTITLEMENT, or a
    DEPENDENT_AGE_OUT yields 36 months."

    Design: Corner/entities/max_coverage_months_computed_36_for_divorce
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"], relationship="SPOUSE")
    payload = create_event_payload(
        plan["id"], ben["id"], event_type="DIVORCE", coverage_loss_date="2026-05-01T00:00:00.000Z"
    )
    resp = api.create_event(payload, _SPONSOR)
    event = validate_success(resp, 201)
    assert_event(event)
    assert event["max_coverage_months"] == 36, f"max_coverage_months {event['max_coverage_months']}"
    assert event["status"] == "RECORDED", f"status {event['status']}"


def test_create_event_unknown_beneficiary_returns_not_found(api):
    """PRD §2.7: "rejecting with ERR_NOT_FOUND the first identifier in the chain
    that does not resolve to an existing resource."

    Design: Corner/entities/create_event_unknown_beneficiary_fk_returns_not_found
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    payload = create_event_payload(plan["id"], "00000000-0000-4000-8000-000000000000")
    resp = api.create_event(payload, _SPONSOR)
    validate_error(resp, "ERR_NOT_FOUND")


def test_list_plan_beneficiaries_paginated_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list responses include the
    following fields in the meta object of the response envelope: limit, offset,
    total_count, and has_more."

    Design: Corner/entities/list_beneficiaries_paginated_envelope
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    fx.create_beneficiary(plan["id"], full_name="B One", relationship="EMPLOYEE")
    fx.create_beneficiary(plan["id"], full_name="B Two", relationship="SPOUSE")
    resp = api.list_plan_beneficiaries(plan["id"], _ADMIN)
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 beneficiaries, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count {meta['total_count']}"
    assert meta["has_more"] is False, f"has_more {meta['has_more']}"


def test_list_invoices_filtered_by_account(api):
    """PRD §2.7: "every other cross-link — an event's plan_id and beneficiary_id,
    a notice's event_id, an enrollment's notice_id, an account's enrollment_id,
    an invoice's account_id, a payment's account_id, a subsidy's enrollment_id, a
    certificate's beneficiary_id and enrollment_id — is followed by id or
    surfaced through a filterable list, never by URL nesting."
    PRD §2.2: "The response_type is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_invoices_filtered_by_account
    """
    ctx = fx.setup_active_enrollment()  # April invoiced+paid
    acct_id = ctx["account"]["id"]
    fx.create_invoice(acct_id, "2026-05")  # May invoiced
    resp = api.list_invoices(_BILLING, params={"account_id": acct_id})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 invoices, got {len(data)}"


def test_invoice_returned_fully_computed_in_same_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.5: "For a FULL_MONTH invoice the amount due equals the gross premium".

    Design: Corner/consistency_model/immediate_invoice_visible_in_same_response
    """
    ctx = fx.setup_elected_enrollment()
    acct_id = ctx["account"]["id"]
    from test_helpers import create_invoice_payload
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-04"), _BILLING)
    inv = validate_success(resp, 201)
    assert_invoice(inv)
    assert inv["amount_due_cents"] == 61200, f"amount_due {inv['amount_due_cents']}"
    assert inv["coverage_month_index"] == 1, f"index {inv['coverage_month_index']}"


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_sponsor_cannot_send_election_notice(api):
    """PRD §2.1: "When a well-identified caller invokes an operation their role is
    not permitted to perform, the request is rejected with ERR_FORBIDDEN_FOR_ROLE."
    PRD §3.3: "Once an event is recorded, a PlanAdministrator issues the election
    notice that opens the beneficiary's election window."

    Design: Corner/rbac/sponsor_cannot_send_election_notice
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])
    event = fx.create_event(plan["id"], ben["id"])
    resp = api.send_notice(event["id"], _SPONSOR)
    validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE")


def test_billing_agent_cannot_terminate_early(api):
    """PRD §2.1: "When a well-identified caller invokes an operation their role is
    not permitted to perform, the request is rejected with ERR_FORBIDDEN_FOR_ROLE."
    PRD §3.9: "A PlanAdministrator may end an active enrollment early, before it
    would otherwise run to term, by supplying a reason."

    Design: Corner/rbac/billing_agent_cannot_terminate_early
    """
    ctx = fx.setup_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    resp = api.terminate_early(enr_id, terminate_early_payload("OTHER_GROUP_COVERAGE"), _BILLING)
    validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE")


def test_beneficiary_cannot_pay_other_beneficiary_account(api):
    """PRD §2.7: "When a caller with role QualifiedBeneficiary elects on a notice
    or posts a payment to an account, the server compares the targeted record's
    beneficiary_id to X-User-ID; if they differ, the request is rejected with
    ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/beneficiary_cannot_pay_other_beneficiary_account
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben1 = fx.create_beneficiary(plan["id"], full_name="B One")
    ben2 = fx.create_beneficiary(plan["id"], full_name="B Two")
    event1 = fx.create_event(plan["id"], ben1["id"])
    notice1 = fx.send_notice(event1["id"])
    fx.set_clock("2026-04-10T00:00:00.000Z")
    enr1 = fx.elect(notice1["id"], ben1["id"])
    acct1 = fx.get_account_for_enrollment(enr1["id"])
    fx.create_invoice(acct1["id"], "2026-04")
    # B2 pays on B1's account.
    resp = api.create_payment(
        acct1["id"], create_payment_payload(61200, "2026-04"), make_beneficiary_headers(ben2["id"])
    )
    validate_error(resp, "ERR_NOT_RESOURCE_OWNER")


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: X-User-ID,
    identifying the acting user, and X-User-Role, declaring the operational
    capacity under which the request is made. If either header is missing or
    malformed, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    Design: Corner/rbac/missing_user_context_header_returns_400
    """
    resp = api.create_plan(create_plan_payload(name="NoAuth Plan", applicable_premium_cents=60000), {})
    validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
