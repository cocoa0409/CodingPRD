"""Dispatch: reach snapshots, SMS billing, throttling, recipient resolution, OCC,
and validation precedence at the dispatch endpoint."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_gateway, create_contact, add_confirmed_channel,
    create_group, subscribe_group, setup_confirmed_contact_in_group,
    compose_group_alert, create_approved_group_alert, add_localization,
    dispatch_alert, setup_approved_single_recipient, setup_sent_single_recipient,
    run_tick, get_alert_notifications,
)

ADMIN = TEST_USERS["contact_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
INTEGRATOR = TEST_USERS["integrator_headers"]

EN_192 = ("Flash flood warning for the downtown river district. Move to higher ground "
          "immediately and avoid all low-lying roads, underpasses, and storm drains until "
          "further official notice is given here.")
ES_52 = "Aviso de inundacion repentina en el centro urbano ya"


def test_estimated_reach_counts_created_notifications(api):
    """PRD §3.5: "The alert's `estimated_reach` is set to the number of distinct contacts
    that received at least one created notification — a forward-looking snapshot that
    treats every queued send as a reach."

    Design: Difficulty/dual_variant_calc/alert_reach_estimated_vs_delivered
    """
    scenario = setup_approved_single_recipient(api, severity="WARNING", channels=["SMS"],
                                               localization_text="Boil water advisory in effect.")
    dispatched = dispatch_alert(api, scenario["alert"]["id"], scenario["alert"]["version"])
    assert dispatched["estimated_reach"] == 1, f"Expected estimated_reach 1, got {dispatched['estimated_reach']}"


def test_delivered_reach_counts_only_delivered(api):
    """PRD §3.7: "the alert's `delivered_reach` is set to the number of distinct contacts
    having at least one `DELIVERED` notification — the final tally, which excludes failed,
    exhausted, suppressed, and still-pending sends and therefore may be smaller than the
    forward-looking `estimated_reach` recorded at dispatch."

    Design: Difficulty/dual_variant_calc/alert_reach_estimated_vs_delivered
    """
    scenario = setup_sent_single_recipient(api, severity="WARNING", channels=["SMS"],
                                           localization_text="Boil water advisory in effect.")
    notif = scenario["notification"]
    get_success_data(api.delivery_report(notif["id"], {"outcome": "FAILED"}, INTEGRATOR))
    closed = validate_success(api.close_alert(scenario["alert"]["id"], DISPATCHER))
    assert closed["delivered_reach"] == 0, f"Expected delivered_reach 0 (only FAILED), got {closed['delivered_reach']}"


def test_sms_billable_segments_round_per_notification_then_sum(api):
    """PRD §3.5: "compute that localization's segment count as the length of its
    `message_text` divided by 160 rounded up to a whole number, and then sum those
    per-notification segment counts across all of the alert's SMS notifications. The
    rounding is performed per notification before summing, never by summing raw
    character counts and dividing once."

    Design: Difficulty/combinatorial_formula/sms_billable_segments_round_per_line_then_sum
    """
    set_clock(api, "2026-03-10T14:00:00Z")
    create_gateway(api, channel_type="SMS", capacity_per_window=100)
    group = create_group(api, name="G1")
    ca = create_contact(api, full_name="A", primary_language="EN")
    add_confirmed_channel(api, ca["id"], channel_type="SMS", address="+15550010")
    subscribe_group(api, ca["id"], group["id"])
    cb = create_contact(api, full_name="B", primary_language="ES")
    add_confirmed_channel(api, cb["id"], channel_type="SMS", address="+15550011")
    subscribe_group(api, cb["id"], group["id"])
    alert = compose_group_alert(api, group["id"], severity="WARNING", channels=["SMS"], title="Flood")
    add_localization(api, alert["id"], "EN", EN_192)
    add_localization(api, alert["id"], "ES", ES_52)
    get_success_data(api.submit_alert(alert["id"], DISPATCHER))
    approved = get_success_data(api.approve_alert(alert["id"], TEST_USERS["approver_headers"]))
    dispatched = dispatch_alert(api, alert["id"], approved["version"])
    assert dispatched["sms_billable_segments"] == 3, (
        f"Expected 3 (ceil(192/160)+ceil(52/160)=2+1), got {dispatched['sms_billable_segments']}")


def test_localization_segment_count_ceils_message_length(api):
    """PRD §3.3: "On creation the localization's `segment_count` is computed as the
    length of its `message_text` divided by 160 and rounded up to the next whole number."

    Design: Difficulty/combinatorial_formula/sms_billable_segments_round_per_line_then_sum
    """
    group = create_group(api, name="G1")
    alert = compose_group_alert(api, group["id"], severity="WARNING", channels=["SMS"], title="Flood")
    en_loc = get_success_data(api.add_localization(alert["id"], {"language": "EN", "message_text": EN_192}, DISPATCHER))
    es_loc = get_success_data(api.add_localization(alert["id"], {"language": "ES", "message_text": ES_52}, DISPATCHER))
    assert en_loc["segment_count"] == 2, f"Expected ceil(192/160)=2, got {en_loc['segment_count']}"
    assert es_loc["segment_count"] == 1, f"Expected ceil(52/160)=1, got {es_loc['segment_count']}"


def test_dispatch_at_capacity_boundary_allowed(api):
    """PRD §3.5: "For each requested `channel_type`, the serving gateway's projected
    `window_count` plus the number of new sends of that channel must not exceed the
    gateway's `capacity_per_window` — unless the alert's `severity` is `CRITICAL`, in
    which case the throttle is bypassed entirely; a non-critical alert that would exceed
    capacity is rejected with `ERR_THROTTLE_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/throttle_capacity_count_boundary_on_dispatch
    """
    scenario = setup_approved_single_recipient(api, severity="WARNING", channels=["SMS"], capacity=1)
    dispatched = dispatch_alert(api, scenario["alert"]["id"], scenario["alert"]["version"])
    assert dispatched["status"] == "DISPATCHING", (
        f"Projected window_count 1 == cap must be allowed, got status {dispatched['status']}")


def test_dispatch_over_capacity_boundary_rejected(api):
    """PRD §3.5: "a non-critical alert that would exceed capacity is rejected with
    `ERR_THROTTLE_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/throttle_capacity_count_boundary_on_dispatch
    """
    set_clock(api, "2026-03-10T14:00:00Z")
    create_gateway(api, channel_type="SMS", capacity_per_window=1)
    sa = setup_confirmed_contact_in_group(api, full_name="cA", address="+15550020", group_name="gA")
    sb = setup_confirmed_contact_in_group(api, full_name="cB", address="+15550021", group_name="gB")
    a1 = create_approved_group_alert(api, sa["group"]["id"], severity="WARNING", channels=["SMS"], title="A1")
    a2 = create_approved_group_alert(api, sb["group"]["id"], severity="WARNING", channels=["SMS"], title="A2")
    # First dispatch fills the window to 1 (== cap).
    dispatch_alert(api, a1["id"], a1["version"])
    # Second dispatch would project window_count 2 > cap 1.
    resp = api.dispatch_alert(a2["id"], {"expected_alert_version": a2["version"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_THROTTLE_EXCEEDED.value)


def test_dispatch_empty_group_returns_no_recipients(api):
    """PRD §3.5: "Finally, the resolved recipient set must be non-empty, or dispatch is
    rejected with `ERR_NO_RECIPIENTS`."

    Design: Corner/errors/no_recipients_on_empty_group_dispatch
    """
    set_clock(api, "2026-03-10T14:00:00Z")
    create_gateway(api, channel_type="SMS", capacity_per_window=100)
    group = create_group(api, name="G1")
    alert = create_approved_group_alert(api, group["id"], severity="WARNING", channels=["SMS"])
    resp = api.dispatch_alert(alert["id"], {"expected_alert_version": alert["version"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_NO_RECIPIENTS.value)


def test_dispatch_with_stale_version_rejected(api):
    """PRD §2.6: "If `expected_alert_version` does not match the alert's current
    `version`, the dispatch is rejected with `ERR_STALE_VERSION` (HTTP 412), so a
    dispatcher cannot fan notifications out against a superseded targeting or approval
    snapshot."

    Design: Corner/cross_cutting_complexity_layers/dispatch_stale_expected_version_returns_412
    """
    scenario = setup_approved_single_recipient(api, severity="WARNING", channels=["SMS"])
    stale = scenario["alert"]["version"] - 1
    resp = api.dispatch_alert(scenario["alert"]["id"], {"expected_alert_version": stale}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_dispatch_draft_alert_state_beats_throttle(api):
    """PRD §2.11: "For the dispatch endpoint specifically, this means the order of
    business checks is: state validity, then the stale-version check, then accessibility,
    then the effective-window check, then throttle capacity, and finally the recipient-set
    check."
    PRD §2.11: "After that comes state validity for the requested transition
    (`ERR_INVALID_STATE`, HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_unapproved_throttled_dispatch
    """
    set_clock(api, "2026-03-10T14:00:00Z")
    create_gateway(api, channel_type="SMS", capacity_per_window=0)  # would also breach throttle
    scenario = setup_confirmed_contact_in_group(api, full_name="Fay", address="+15550007")
    alert = compose_group_alert(api, scenario["group"]["id"], severity="WARNING", channels=["SMS"])
    add_localization(api, alert["id"], "EN", "Warning.")  # left in DRAFT, never submitted
    resp = api.dispatch_alert(alert["id"], {"expected_alert_version": alert["version"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_dispatch_draft_alert_leaves_status_unchanged(api):
    """PRD §3.5: "Dispatch itself is performed by a `Dispatcher` on an approved alert and
    advances it `APPROVED → DISPATCHING`."
    PRD §2.11: "After that comes state validity for the requested transition
    (`ERR_INVALID_STATE`, HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_unapproved_throttled_dispatch
    """
    set_clock(api, "2026-03-10T14:00:00Z")
    create_gateway(api, channel_type="SMS", capacity_per_window=0)
    scenario = setup_confirmed_contact_in_group(api, full_name="Fay", address="+15550007")
    alert = compose_group_alert(api, scenario["group"]["id"], severity="WARNING", channels=["SMS"])
    add_localization(api, alert["id"], "EN", "Warning.")
    api.dispatch_alert(alert["id"], {"expected_alert_version": alert["version"]}, DISPATCHER)
    reread = get_success_data(api.get_alert(alert["id"], DISPATCHER))
    assert reread["status"] == "DRAFT", f"Rejected dispatch must not transition; got {reread['status']}"


def test_dispatch_tty_gap_accessibility_beats_window_expired(api):
    """PRD §3.5: "Every targeted contact who is `tty_required` must have at least one
    `CONFIRMED`, `tty_capable` channel whose `channel_type` is among the alert's requested
    `channels`; if any such contact lacks one, dispatch is rejected with
    `ERR_ACCESSIBILITY_UNMET`."
    PRD §2.11: "the order of business checks is: state validity, then the stale-version
    check, then accessibility, then the effective-window check, then throttle capacity,
    and finally the recipient-set check."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_tty_expired_dispatch
    """
    scenario = setup_approved_single_recipient(
        api, severity="WARNING", channels=["SMS"], tty_required=True, tty_capable=False,
        effective_until="2026-03-10T12:00:00Z")  # window already expired at clock 14:00
    resp = api.dispatch_alert(scenario["alert"]["id"],
                              {"expected_alert_version": scenario["alert"]["version"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ACCESSIBILITY_UNMET.value)


def test_dispatch_tty_gap_leaves_alert_approved(api):
    """PRD §3.5: "if any such contact lacks one, dispatch is rejected with
    `ERR_ACCESSIBILITY_UNMET`."
    PRD §3.5: "Dispatch itself is performed by a `Dispatcher` on an approved alert and
    advances it `APPROVED → DISPATCHING`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_tty_expired_dispatch
    """
    scenario = setup_approved_single_recipient(
        api, severity="WARNING", channels=["SMS"], tty_required=True, tty_capable=False,
        effective_until="2026-03-10T12:00:00Z")
    api.dispatch_alert(scenario["alert"]["id"],
                       {"expected_alert_version": scenario["alert"]["version"]}, DISPATCHER)
    reread = get_success_data(api.get_alert(scenario["alert"]["id"], DISPATCHER))
    assert reread["status"] == "APPROVED", f"Rejected dispatch must leave alert APPROVED; got {reread['status']}"
