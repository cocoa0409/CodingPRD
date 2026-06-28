"""Business-constraint validations: panel capacity, seat limits, empty care
plan, annual-physical-due satisfaction, and the invoice-charge happy path.
PRD §3.2, §3.3, §3.4, §3.5, §3.8, §3.10.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, setup_completed_annual_physical, setup_invoiced_visit,
    setup_active_member, create_practice, create_provider, create_employer,
    register_member, assign_pcp_manual, get_membership_for, charge_membership,
    allocate_seat, occupy_seat, create_slot, book_visit,
    make_member_headers, make_provider_headers, make_employer_headers,
    invoice_charge_payload, set_clock, ApiErrorId, ADMIN,
)


def test_assign_pcp_to_full_provider_returns_no_panel_capacity(api):
    """PRD §3.4: "A request that would push a provider to or past its effective cap,
    or an `AUTO` request that finds no eligible provider, is rejected with
    `ERR_NO_PANEL_CAPACITY`."

    Design: Corner/validations/assign_pcp_to_full_provider_returns_no_panel_capacity
    """
    practice = create_practice(name="V1", panel_target=1, panel_hard_cap=1)
    provider = create_provider(practice["id"], full_name="Dr V1", npi="5000000001", panel_capacity=1)
    set_clock("2026-06-01T00:00:00Z")
    m1 = register_member(practice["id"], email="v1a@x.com")
    assign_pcp_manual(m1["id"], provider["id"])
    mem1 = get_membership_for(m1["id"])
    charge_membership(m1["id"], mem1["id"], mem1["member_share_cents"], "SUCCEEDED")  # count -> 1 (cap)

    m2 = register_member(practice["id"], email="v1b@x.com")
    res = api_client.assign_pcp(m2["id"], {"mode": "MANUAL", "provider_id": provider["id"]}, ADMIN)
    validate_error(res, ApiErrorId.ERR_NO_PANEL_CAPACITY.value)


def test_occupy_seat_over_limit_returns_seat_limit_reached(api):
    """PRD §3.2: "Before the seat may be occupied, the employer must have an `OPEN`
    seat and its `occupied_seat_count` must be strictly below `sponsored_seat_limit`;
    if neither condition holds the request is rejected with `ERR_SEAT_LIMIT_REACHED`."

    Design: Corner/validations/occupy_seat_over_limit_returns_seat_limit_reached
    """
    practice = create_practice(name="V2")
    employer = create_employer(practice["id"], sponsored_seat_limit=1, sponsorship_pct=1.0)
    m1 = register_member(practice["id"], email="v2a@x.com")
    m2 = register_member(practice["id"], email="v2b@x.com")
    seat1 = allocate_seat(employer["id"])
    seat2 = allocate_seat(employer["id"])
    occupy_seat(employer["id"], seat1["id"], m1["id"])  # occupied_seat_count -> 1 == limit

    emp_h = make_employer_headers(employer["id"])
    emp_v = validate_success(api_client.get_employer(employer["id"], emp_h), 200)["version"]
    from test_helpers import occupy_seat_payload
    res = api_client.occupy_seat(
        employer["id"], seat2["id"], occupy_seat_payload(m2["id"], emp_v), emp_h)
    validate_error(res, ApiErrorId.ERR_SEAT_LIMIT_REACHED.value)


def test_activate_empty_care_plan_returns_care_plan_empty(api):
    """PRD §3.10: "Attempting to activate a plan whose `goal_count` is below one is
    rejected with `ERR_CARE_PLAN_EMPTY`."

    Design: Corner/validations/activate_empty_care_plan_returns_care_plan_empty
    """
    ctx = setup_completed_annual_physical(goal_count=0)
    prov_h = make_provider_headers(ctx["provider"]["id"])
    res = api_client.activate_care_plan(ctx["care_plan"]["id"], prov_h)
    validate_error(res, ApiErrorId.ERR_CARE_PLAN_EMPTY.value)


def test_first_annual_physical_allowed_when_due_on_null(api):
    """PRD §3.5: "When the requested `visit_type` is `ANNUAL_PHYSICAL`, the booking
    is permitted only when the member's `annual_physical_due_on` is null or is at or
    before the current clock instant — that is, the physical is due."

    Design: Corner/validations/physical_not_due_satisfaction_when_due_on_null
    """
    ctx = setup_active_member()  # never had a physical -> annual_physical_due_on null
    slot = create_slot(ctx["provider"]["id"], "IN_PERSON",
                       "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
    visit = book_visit(ctx["member"]["id"], slot["id"], "ANNUAL_PHYSICAL", slot["version"])
    assert visit["clinical_status"] == "BOOKED"
    assert visit["visit_type"] == "ANNUAL_PHYSICAL"


def test_invoice_charge_pays_cash_member_responsibility(api):
    """PRD §3.8: "The submitted `amount_cents` must equal the invoice's
    `member_responsibility_cents` net of the wallet credit applied, or the charge is
    rejected with `ERR_AMOUNT_MISMATCH`. On a successful charge the invoice advances
    from `ISSUED` to `PAID`."

    Design: Corner/endpoints/invoice_charge_pays_cash_member_responsibility
    """
    # Cash member, single XRAY 9000 (non-DPC) -> member_responsibility_cents 9000, wallet 0.
    ctx = setup_invoiced_visit(
        [{"service_code": "XRAY", "units": 1, "unit_charge_cents": 9000}],
        member_overrides={"has_insurance": False})
    assert ctx["invoice"]["member_responsibility_cents"] == 9000
    member_h = make_member_headers(ctx["member"]["id"])
    validate_success(api_client.charge_invoice(
        ctx["invoice"]["id"], invoice_charge_payload(9000, "SUCCEEDED"), member_h), 201)
    invoice = validate_success(api_client.get_invoice(ctx["invoice"]["id"], member_h), 200)
    assert invoice["invoice_status"] == "PAID"


def test_list_visits_filtered_by_member(api):
    """PRD §4: "List/filter visits by member, provider, or slot."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    count of all matching resources before pagination and `has_more` indicates
    whether further pages remain."

    Design: Corner/endpoints/list_visits_filtered_by_member
    """
    ctx = setup_active_member()
    slot = create_slot(ctx["provider"]["id"], "IN_PERSON",
                       "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z")
    book_visit(ctx["member"]["id"], slot["id"], "SAME_DAY", slot["version"])
    member_h = make_member_headers(ctx["member"]["id"])
    data, meta = validate_paginated(api_client.list_visits(
        member_h, params={"member_id": ctx["member"]["id"]}))
    assert meta["total_count"] == 1
