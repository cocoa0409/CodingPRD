"""Subscription inventory, cancel-on-behalf lifecycle, and free-trial reminders."""
from test_helpers import (
    validate_success, validate_error,
    make_member_headers, make_agent_headers, make_admin_headers,
    setup_confirmed_charge, setup_active_subscription, setup_trial_subscription,
    setup_cancel_failed_subscription, setup_cancel_requested_subscription,
    create_member, create_subscription_payload, set_clock,
    ApiErrorId,
)


def test_subscription_initial_state_active(api):
    """PRD §3.3: "When `is_free_trial` is true, `trial_end_utc` must be supplied ... A new subscription has `status` `ACTIVE`."

    Design: Corner/state_machines/initial_state_subscription_active
    """
    member, la, charge = setup_confirmed_charge(amount_cents=1000)
    resp = api.create_subscription(
        create_subscription_payload(member["id"], charge["id"], plan_name="P", monthly_cost_cents=1000),
        headers=make_member_headers(member["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"


def test_trial_end_required_when_free_trial(api):
    """PRD §3.3: "When `is_free_trial` is true, `trial_end_utc` must be supplied; a trial subscription created without it is rejected with `ERR_TRIAL_END_REQUIRED`."

    Design: Corner/validations/subscription_trial_end_required
    """
    member, la, charge = setup_confirmed_charge(amount_cents=1500)
    resp = api.create_subscription(
        create_subscription_payload(member["id"], charge["id"], plan_name="T",
                                    monthly_cost_cents=1500, is_free_trial=True),
        headers=make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TRIAL_END_REQUIRED.value)


def test_fk_not_found_on_subscription_create(api):
    """PRD §2.8: "When a write body names another resource by a foreign-key field — for instance a `member_id`, `recurring_charge_id ... and that referenced resource does not exist, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/fk_not_found_on_subscription_create
    """
    member = create_member()
    resp = api.create_subscription(
        {"member_id": member["id"], "recurring_charge_id": "00000000-0000-0000-0000-000000000000",
         "plan_name": "P", "monthly_cost_cents": 1000},
        headers=make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


def test_dismiss_confirmed_charge_in_use_rejected(api):
    """PRD §3.2: "a `CONFIRMED` charge may be dismissed only when no subscription, negotiation case, or refund claim references it in a non-terminal state — attempting to dismiss a `CONFIRMED` charge that is still in use that way is rejected with `ERR_CHARGE_IN_USE`."

    Design: Corner/validations/dismiss_confirmed_charge_in_use_rejected
    """
    member, charge, sub = setup_active_subscription(monthly_cost_cents=5000, charge_amount_cents=5000)
    resp = api.dismiss_recurring_charge(charge["id"], headers=make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_CHARGE_IN_USE.value)


# --- Cancel-on-behalf lifecycle ---

def test_cancel_failed_can_be_requested_again(api):
    """PRD §3.3: "a member may re-request cancellation of a `CANCEL_FAILED` subscription, which (again requiring the member to be `ACTIVE` and to supply a matching `expected_subscription_version`) returns the subscription to `CANCEL_REQUESTED` and bumps the `version`. This retry loop may repeat."

    Design: Corner/state_machines/cancel_failed_retry_request_cancel_cycle
    """
    member, agent, sub = setup_cancel_failed_subscription()
    resp = api.request_cancel_subscription(
        sub["id"], {"expected_subscription_version": sub["version"]},
        headers=make_member_headers(member["id"]),
    )
    data = validate_success(resp)
    assert data["status"] == "CANCEL_REQUESTED"


def test_confirm_cancel_sets_cancelled_utc(api):
    """PRD §3.3: "confirming cancellation advances a `CANCEL_REQUESTED` subscription to `CANCELLED`, stamps `cancelled_utc` with the current clock value, sets `reminder_due` to false, and bumps the `version".
    PRD §2.10: "A platform operator may advance it by supplying a new instant as `to_iso8601`."

    Design: Corner/state_machines/confirm_cancel_sets_cancelled_utc_side_effect
    """
    member, agent, sub = setup_cancel_requested_subscription()
    set_clock("2026-03-15T00:00:00Z")
    resp = api.confirm_cancel_subscription(sub["id"], headers=make_agent_headers(agent["id"]))
    data = validate_success(resp)
    assert data["status"] == "CANCELLED"
    assert data["cancelled_utc"].startswith("2026-03-15T00:00:00")


def test_member_cannot_act_on_other_subscription(api):
    """PRD §2.1: "When a `Member` attempts to act on a resource whose owning `member_id` is not their own `X-User-ID`, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/member_cannot_act_on_other_members_subscription
    """
    owner, charge, sub = setup_active_subscription(monthly_cost_cents=5000, charge_amount_cents=5000)
    other = create_member(email="other-owner@x.com")
    resp = api.request_cancel_subscription(
        sub["id"], {"expected_subscription_version": sub["version"]},
        headers=make_member_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_list_subscriptions_by_member(api):
    """PRD §2.3: "the `meta` object carries the pagination fields `limit`, `offset`, `total_count` (the total number of records matching the query before pagination), and `has_more` (a boolean that is true when records remain beyond the current page)."

    Design: Corner/endpoints/fk_reverse_subscriptions_by_member
    """
    member, charge, sub = setup_active_subscription(monthly_cost_cents=1500, charge_amount_cents=1500)
    resp = api.list_subscriptions(headers=make_member_headers(member["id"]),
                                  params={"member_id": member["id"]})
    validate_success(resp)
    body = resp.json()
    assert body["meta"]["total_count"] == 1
    assert body["data"][0]["id"] == sub["id"]


# --- Trial reminders / clock ---

def test_trial_reminder_inclusive_lower_boundary(api):
    """PRD §3.3: "A reminder is due when the subscription is a free trial, the logical clock has reached or passed the instant that is `trial_reminder_lead_days` days before `trial_end_utc`, and the subscription has not yet been cancelled."
    PRD §3.3: "once `current_utc` is at or after `trial_end_utc` minus the lead-day window, `reminder_due` becomes true for an uncancelled trial."

    Design: Difficulty/resource_temporal_overlap/trial_reminder_window_inclusive_lower_boundary
    """
    member, charge, sub = setup_trial_subscription("2026-02-10T00:00:00Z", trial_reminder_lead_days=3)
    set_clock("2026-02-07T00:00:00Z")  # exactly trial_end - 3 days
    resp = api.get_subscription(sub["id"], headers=make_member_headers(member["id"]))
    data = validate_success(resp)
    assert data["reminder_due"] is True
    assert data["status"] == "ACTIVE"


def test_trial_reminder_before_edge_excluded(api):
    """PRD §3.3: "the logical clock has reached or passed the instant that is `trial_reminder_lead_days` days before `trial_end_utc".
    PRD §3.3: "once `current_utc` is at or after `trial_end_utc` minus the lead-day window, `reminder_due` becomes true for an uncancelled trial."

    Design: Difficulty/resource_temporal_overlap/trial_reminder_window_before_edge_excluded
    """
    member, charge, sub = setup_trial_subscription("2026-02-10T00:00:00Z", trial_reminder_lead_days=3)
    set_clock("2026-02-06T23:59:59Z")  # one second before the reminder edge
    resp = api.get_subscription(sub["id"], headers=make_member_headers(member["id"]))
    data = validate_success(resp)
    assert data["reminder_due"] is False


def test_trial_reminder_true_after_edge(api):
    """PRD §3.3: "once `current_utc` is at or after `trial_end_utc` minus the lead-day window, `reminder_due` becomes true for an uncancelled trial."
    PRD §3.3: "the logical clock has reached or passed the instant that is `trial_reminder_lead_days` days before `trial_end_utc".

    Design: Difficulty/resource_temporal_overlap/trial_reminder_window_inclusive_lower_boundary
    """
    member, charge, sub = setup_trial_subscription("2026-02-10T00:00:00Z", trial_reminder_lead_days=3)
    set_clock("2026-02-08T00:00:00Z")  # one day inside the window, after the inclusive edge
    data = validate_success(api.get_subscription(sub["id"], headers=make_member_headers(member["id"])))
    assert data["reminder_due"] is True


def test_trial_reminder_well_before_edge_false(api):
    """PRD §3.3: "A reminder is due when the subscription is a free trial, the logical clock has reached or passed the instant that is `trial_reminder_lead_days` days before `trial_end_utc`, and the subscription has not yet been cancelled."
    PRD §3.3: "once `current_utc` is at or after `trial_end_utc` minus the lead-day window, `reminder_due` becomes true for an uncancelled trial."

    Design: Difficulty/resource_temporal_overlap/trial_reminder_window_before_edge_excluded
    """
    member, charge, sub = setup_trial_subscription("2026-02-10T00:00:00Z", trial_reminder_lead_days=3)
    set_clock("2026-02-01T00:00:00Z")  # well before the 2026-02-07 reminder edge
    data = validate_success(api.get_subscription(sub["id"], headers=make_member_headers(member["id"])))
    assert data["reminder_due"] is False


def test_clock_default_before_set_no_reminder(api):
    """PRD §2.10: "At server startup the clock reads exactly `2026-01-01T00:00:00Z`; before any explicit clock-set call it holds this default and never falls back to wall-clock time."
    PRD §3.3: "once `current_utc` is at or after `trial_end_utc` minus the lead-day window, `reminder_due` becomes true for an uncancelled trial."

    Design: Corner/cross_cutting_complexity_layers/clock_default_before_set_is_epoch_default
    """
    member, charge, sub = setup_trial_subscription("2026-12-01T00:00:00Z", trial_reminder_lead_days=3)
    # clock never set -> default 2026-01-01, far before the reminder window
    resp = api.get_subscription(sub["id"], headers=make_member_headers(member["id"]))
    data = validate_success(resp)
    assert data["reminder_due"] is False
