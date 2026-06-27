"""Message-thread SLA computation, auto panel assignment load-balancing, and
the derived panel_load_bucket reconciliation. PRD §3.4, §3.12, §3.1.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_active_member, setup_practice_and_provider,
    create_practice, create_provider, register_member,
    assign_pcp_manual, assign_pcp_auto, get_membership_for, charge_membership,
    make_member_headers, message_thread_payload, set_clock, ADMIN,
)


def test_thread_after_hours_deadline_four_hours(api):
    """PRD §3.12: "The 08:00 hour is `ROUTINE` and the 18:00 hour is `AFTER_HOURS`."
    PRD §3.12: "an `AFTER_HOURS` thread's `response_deadline` is its `created_at`
    plus 4 hours, reflecting the faster after-hours service-level commitment."

    Design: Corner/calculations/thread_after_hours_deadline_four_hours
    """
    # Open at 20:00Z (UTC hour 20 >= 18) -> AFTER_HOURS, deadline 20:00 + 4h = 00:00 next day.
    ctx = setup_active_member(clock="2026-06-01T08:00:00Z")
    set_clock("2026-06-01T20:00:00Z")
    member_h = make_member_headers(ctx["member"]["id"])
    thread = validate_success(api_client.create_message_thread(
        ctx["member"]["id"], message_thread_payload("fever"), member_h), 201)
    assert thread["priority"] == "AFTER_HOURS"
    assert thread["response_deadline"].startswith("2026-06-02T00:00:00")


def test_thread_open_boundary_hour_eight_is_routine(api):
    """PRD §3.12: "when the creation hour is at least 8 and below 18 the priority is
    `ROUTINE`, otherwise — before 8 or at/after 18 — it is `AFTER_HOURS`."
    PRD §3.12: "The 08:00 hour is `ROUTINE` and the 18:00 hour is `AFTER_HOURS`."
    PRD §3.12: "A `ROUTINE` thread's `response_deadline` is its `created_at` plus 24
    hours."

    Design: Corner/calculations/thread_business_open_boundary_hour_eight_is_routine
    """
    # Open at exactly 08:00Z -> ROUTINE, deadline next day 08:00Z.
    ctx = setup_active_member(clock="2026-06-01T08:00:00Z")
    member_h = make_member_headers(ctx["member"]["id"])
    thread = validate_success(api_client.create_message_thread(
        ctx["member"]["id"], message_thread_payload("checkup"), member_h), 201)
    assert thread["priority"] == "ROUTINE"
    assert thread["response_deadline"].startswith("2026-06-02T08:00:00")


def test_auto_assignment_load_balances_lowest_count(api):
    """PRD §3.4: "Candidates are ranked first by `active_panel_count` in ascending
    order so that the most lightly loaded provider is preferred."

    Design: Corner/calculations/panel_assignment_auto_load_balances_lowest_count
    """
    # provA holds 1 active member; provB holds 0. AUTO assigns the new member to provB.
    practice = create_practice(name="CA4")
    prov_a = create_provider(practice["id"], full_name="Dr A4", npi="4000000004")
    prov_b = create_provider(practice["id"], full_name="Dr B4", npi="4000000005")
    set_clock("2026-06-01T00:00:00Z")
    m1 = register_member(practice["id"], email="ca4a@x.com")
    assign_pcp_manual(m1["id"], prov_a["id"])
    mem1 = get_membership_for(m1["id"])
    charge_membership(m1["id"], mem1["id"], mem1["member_share_cents"], "SUCCEEDED")

    m3 = register_member(practice["id"], email="ca4c@x.com")
    assigned = validate_success(api_client.assign_pcp(
        m3["id"], {"mode": "AUTO"}, ADMIN), 200)
    assert assigned["assigned_provider_id"] == prov_b["id"]


def test_panel_load_bucket_reconciles_to_at_target(api):
    """PRD §3.1: "The derived `panel_load_bucket` is `UNDER_TARGET` while
    `active_panel_count` is below the practice's `panel_target`, `AT_TARGET` while
    `active_panel_count` is at least the `panel_target` but below the effective cap,
    and `FULL` once `active_panel_count` equals the effective cap."

    Design: Corner/cross_cutting_complexity_layers/derived_panel_load_bucket_recomputes_on_activation
    """
    # panel_target=1, panel_capacity=5: after one activation active_panel_count==1
    # (>= target 1, < cap 5) -> AT_TARGET.
    practice = create_practice(name="L2", panel_target=1, panel_hard_cap=5)
    provider = create_provider(practice["id"], full_name="Dr L2", npi="9000000001", panel_capacity=5)
    set_clock("2026-06-01T00:00:00Z")
    member = register_member(practice["id"], email="l2@x.com")
    assign_pcp_manual(member["id"], provider["id"])
    membership = get_membership_for(member["id"])
    charge_membership(member["id"], membership["id"], membership["member_share_cents"], "SUCCEEDED")
    provider_after = validate_success(api_client.get_provider(provider["id"], ADMIN), 200)
    assert provider_after["active_panel_count"] == 1
    assert provider_after["panel_load_bucket"] == "AT_TARGET"


def test_active_panel_count_immediately_visible(api):
    """PRD §2.5: "Whenever a member's `membership_status` changes, the system
    recomputes the assigned provider's `active_panel_count` and re-derives
    `panel_load_bucket`."
    PRD §2.5: "they must all fire as part of the triggering operation rather than
    being deferred."

    Design: Corner/consistency_model/immediate_panel_count_visible_after_activation
    """
    ctx = setup_active_member()
    provider = validate_success(api_client.get_provider(ctx["provider"]["id"], ADMIN), 200)
    assert provider["active_panel_count"] == 1
