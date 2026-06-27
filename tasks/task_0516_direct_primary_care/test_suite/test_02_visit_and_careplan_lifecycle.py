"""Visit parallel status dimensions, care-plan revision cycle, and the
cross-entity eligibility gates on check-in and care-plan activation.
PRD §3.6, §3.10.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_active_member, setup_completed_annual_physical, setup_active_care_plan,
    book_in_person_visit, drive_member_past_due,
    make_provider_headers, make_member_headers, ApiErrorId,
    complete_visit_payload, ADMIN,
)


def test_visit_clinical_completed_with_billing_billable_parallel(api):
    """PRD §3.6: "A visit carries two independent status dimensions."
    PRD §3.6: "If the submitted `service_lines` are non-empty, the visit's
    `billing_status` advances to `BILLABLE`; if they are empty, `billing_status`
    remains `NOT_BILLABLE`."

    Design: Difficulty/non_linear_state_machine/visit_parallel_clinical_and_billing_dimensions
    """
    ctx = setup_active_member()
    booked = book_in_person_visit(ctx, "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z")
    prov_h = make_provider_headers(ctx["provider"]["id"])
    get_success_data(api_client.check_in_visit(booked["visit"]["id"], prov_h))
    visit = validate_success(api_client.complete_visit(
        booked["visit"]["id"],
        complete_visit_payload([{"service_code": "XRAY", "units": 1, "unit_charge_cents": 9000}]),
        prov_h), 200)
    assert visit["clinical_status"] == "COMPLETED"
    assert visit["billing_status"] == "BILLABLE"


def test_visit_dimensions_independent_after_completion(api):
    """PRD §3.6: "The billing dimension, `billing_status`, evolves separately
    through `NOT_BILLABLE`, `BILLABLE`, `INVOICED`, and `WRITTEN_OFF`. The two
    dimensions advance independently of each other."

    Design: Difficulty/non_linear_state_machine/visit_parallel_clinical_and_billing_dimensions
    """
    ctx = setup_active_member()
    booked = book_in_person_visit(ctx, "2026-06-02T11:00:00Z", "2026-06-02T11:30:00Z")
    prov_h = make_provider_headers(ctx["provider"]["id"])
    get_success_data(api_client.check_in_visit(booked["visit"]["id"], prov_h))
    get_success_data(api_client.complete_visit(
        booked["visit"]["id"],
        complete_visit_payload([{"service_code": "XRAY", "units": 1, "unit_charge_cents": 9000}]),
        prov_h))
    visit = validate_success(api_client.get_visit(booked["visit"]["id"], prov_h), 200)
    # clinical COMPLETED (terminal) but billing still BILLABLE, not yet INVOICED.
    assert visit["clinical_status"] == "COMPLETED"
    assert visit["billing_status"] == "BILLABLE"


def test_care_plan_revision_increments_on_reopen(api):
    """PRD §3.10: "A provider may reopen an `ACTIVE` plan, moving it to
    `UNDER_REVISION` and incrementing its `revision_number` by one."

    Design: Difficulty/non_linear_state_machine/care_plan_active_revision_cycle
    """
    ctx = setup_active_care_plan()
    prov_h = make_provider_headers(ctx["provider"]["id"])
    reopened = validate_success(api_client.reopen_care_plan(ctx["care_plan"]["id"], prov_h), 200)
    assert reopened["plan_status"] == "UNDER_REVISION"
    assert reopened["revision_number"] == 1


def test_care_plan_cycle_back_to_active(api):
    """PRD §3.10: "From `UNDER_REVISION` the plan may be activated again — back to
    `ACTIVE` — provided it is currently `UNDER_REVISION` and its `goal_count` is at
    least one."

    Design: Difficulty/non_linear_state_machine/care_plan_active_revision_cycle
    """
    ctx = setup_active_care_plan()
    prov_h = make_provider_headers(ctx["provider"]["id"])
    validate_success(api_client.reopen_care_plan(ctx["care_plan"]["id"], prov_h), 200)
    reactivated = validate_success(api_client.activate_care_plan(ctx["care_plan"]["id"], prov_h), 200)
    assert reactivated["plan_status"] == "ACTIVE"
    assert reactivated["revision_number"] == 1


def test_checkin_admits_past_due_member(api):
    """PRD §3.6: "A `Provider` checks a member in, advancing the visit from
    `BOOKED` to `CHECKED_IN`, provided the visit is currently `BOOKED` and the
    owning member's `membership_status` is `ACTIVE` or `PAST_DUE`."

    Design: Difficulty/cross_entity_state_dependency/visit_checkin_admits_pastdue_member
    """
    # Member is ACTIVE since 2026-06-01 (MONTHLY -> period end 2026-07-01),
    # holds a BOOKED future visit, then a FAILED charge at rollover -> PAST_DUE.
    ctx = setup_active_member()
    booked = book_in_person_visit(ctx, "2026-07-10T09:00:00Z", "2026-07-10T09:30:00Z")
    member = drive_member_past_due(ctx, rollover_clock="2026-07-01T00:00:00Z")
    assert member["membership_status"] == "PAST_DUE"
    prov_h = make_provider_headers(ctx["provider"]["id"])
    visit = validate_success(api_client.check_in_visit(booked["visit"]["id"], prov_h), 200)
    assert visit["clinical_status"] == "CHECKED_IN"


def test_checkin_past_due_member_stamps_checked_in_at(api):
    """PRD §3.6: "Check-in stamps the visit's `checked_in_at` with the current
    instant."

    Design: Difficulty/cross_entity_state_dependency/visit_checkin_admits_pastdue_member
    """
    ctx = setup_active_member()
    booked = book_in_person_visit(ctx, "2026-07-11T09:00:00Z", "2026-07-11T09:30:00Z")
    member = drive_member_past_due(ctx, rollover_clock="2026-07-01T00:00:00Z")
    assert member["membership_status"] == "PAST_DUE"
    prov_h = make_provider_headers(ctx["provider"]["id"])
    visit = validate_success(api_client.check_in_visit(booked["visit"]["id"], prov_h), 200)
    assert visit["clinical_status"] == "CHECKED_IN"
    assert visit["checked_in_at"] is not None


def test_careplan_activate_requires_completed_annual_physical(api):
    """PRD §3.10: "attempting to activate when the origin visit is not a completed
    annual physical is rejected with `ERR_MEMBER_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/careplan_activate_requires_origin_visit_completed_physical
    """
    # Build an ANNUAL_PHYSICAL visit left at CHECKED_IN (not COMPLETED) with a
    # DRAFT CarePlan (goal_count=1) referencing it.
    ctx = setup_active_member()
    prov_h = make_provider_headers(ctx["provider"]["id"])
    from test_helpers import create_slot, book_visit, create_care_plan_payload
    slot = create_slot(ctx["provider"]["id"], "IN_PERSON",
                       "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    visit = book_visit(ctx["member"]["id"], slot["id"], "ANNUAL_PHYSICAL", slot["version"])
    get_success_data(api_client.check_in_visit(visit["id"], prov_h))
    cp = get_success_data(api_client.create_care_plan(
        create_care_plan_payload(ctx["member"]["id"], visit["id"], goal_count=1), prov_h))
    res = api_client.activate_care_plan(cp["id"], prov_h)
    validate_error(res, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE.value)
    cp_after = validate_success(api_client.get_care_plan(cp["id"], prov_h), 200)
    assert cp_after["plan_status"] == "DRAFT"


def test_careplan_activate_eligible_when_physical_completed(api):
    """PRD §3.10: "Activation requires the plan to be in `DRAFT`, its `goal_count`
    to be at least one, and the origin visit to be a completed annual physical —
    that is, the referenced visit's `clinical_status` is `COMPLETED` and its
    `visit_type` is `ANNUAL_PHYSICAL`."

    Design: Difficulty/cross_entity_state_dependency/careplan_activate_requires_origin_visit_completed_physical
    """
    ctx = setup_completed_annual_physical(goal_count=1)
    prov_h = make_provider_headers(ctx["provider"]["id"])
    activated = validate_success(api_client.activate_care_plan(ctx["care_plan"]["id"], prov_h), 200)
    assert activated["plan_status"] == "ACTIVE"
