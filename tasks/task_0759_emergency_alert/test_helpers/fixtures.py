"""Composite setup helpers for the Emergency-Alert API.

Every helper builds its preconditions from scratch (the server database is empty at
the start of each test) using only PRD-declared endpoints. Setup calls use the
lenient get_success_data() so a broken precondition surfaces as a clear "Setup failed".

Identity threading: after a Contact is created, any ownership-gated call (channel
confirm/opt-out, notification acknowledge, self subscription) uses
make_contact_headers(contact["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS,
    DISPATCHER_ID,
    APPROVER_ID,
    make_contact_headers,
    make_dispatcher_headers,
    make_approver_headers,
)
from .factories import (
    create_contact_payload,
    create_channel_payload,
    create_group_payload,
    create_subscription_payload,
    create_alert_payload,
    create_localization_payload,
    create_gateway_payload,
)
from .constants import (
    DEFAULT_TEST_CLOCK,
    DEFAULT_EFFECTIVE_FROM,
    DEFAULT_EFFECTIVE_UNTIL,
)

ADMIN = TEST_USERS["contact_admin_headers"]
INTEGRATOR = TEST_USERS["integrator_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
APPROVER = TEST_USERS["approver_headers"]


# ---------------------------------------------------------------- infra helpers
def set_clock(api, iso):
    return get_success_data(api.set_clock({"to_iso8601": iso}, INTEGRATOR))


def run_tick(api):
    return get_success_data(api.run_tick(INTEGRATOR))


# --------------------------------------------------------------- simple creators
def create_gateway(api, channel_type="SMS", capacity_per_window=100, name=None):
    payload = create_gateway_payload(
        name=name or f"{channel_type}-GW",
        channel_type=channel_type,
        capacity_per_window=capacity_per_window,
    )
    return get_success_data(api.create_gateway(payload, ADMIN))


def create_contact(api, **overrides):
    return get_success_data(api.create_contact(create_contact_payload(**overrides), ADMIN))


def add_confirmed_channel(api, contact_id, channel_type="SMS", address="+15550000",
                          tty_capable=False):
    """Add a channel to a contact and confirm its opt-in as the owning contact.
    Returns the CONFIRMED channel resource."""
    ch = get_success_data(api.add_channel(
        contact_id,
        create_channel_payload(channel_type=channel_type, address=address,
                               tty_capable=tty_capable),
        ADMIN,
    ))
    confirmed = get_success_data(api.confirm_channel(
        ch["id"],
        {"confirmation_token": ch["confirmation_token"]},
        make_contact_headers(contact_id),
    ))
    return confirmed


def create_group(api, name="G1"):
    return get_success_data(api.create_group(create_group_payload(name=name), ADMIN))


def subscribe_group(api, contact_id, group_id):
    return get_success_data(api.create_subscription(
        create_subscription_payload(contact_id, "GROUP", group_id=group_id), ADMIN))


def subscribe_geo(api, contact_id, center_lat, center_lon, radius_m):
    return get_success_data(api.create_subscription(
        create_subscription_payload(contact_id, "GEO", center_lat=center_lat,
                                    center_lon=center_lon, radius_m=radius_m), ADMIN))


# ----------------------------------------------------------- recipient scenarios
def setup_confirmed_contact_in_group(api, full_name="Person", primary_language="EN",
                                     tty_required=False, channel_type="SMS",
                                     address="+15550000", tty_capable=False,
                                     group_id=None, group_name="G1"):
    """One contact with a CONFIRMED channel, subscribed to a (new or given) group.
    Returns dict {contact, channel, group}."""
    contact = create_contact(api, full_name=full_name, primary_language=primary_language,
                             tty_required=tty_required)
    channel = add_confirmed_channel(api, contact["id"], channel_type=channel_type,
                                    address=address, tty_capable=tty_capable)
    if group_id is None:
        group = create_group(api, name=group_name)
        group_id = group["id"]
    else:
        group = {"id": group_id}
    subscribe_group(api, contact["id"], group_id)
    return {"contact": contact, "channel": channel, "group": group}


# ------------------------------------------------------------- alert composition
def compose_group_alert(api, group_id, severity="WARNING", channels=None, title="Warn",
                        template_id=None, effective_from=DEFAULT_EFFECTIVE_FROM,
                        effective_until=DEFAULT_EFFECTIVE_UNTIL):
    payload = create_alert_payload(
        title=title, severity=severity, channels=channels or ["SMS"],
        target_type="GROUP", target_group_id=group_id,
        effective_from=effective_from, effective_until=effective_until,
    )
    if template_id is not None:
        payload["template_id"] = template_id
    return get_success_data(api.create_alert(payload, DISPATCHER))


def compose_geo_alert(api, center_lat, center_lon, radius_m, severity="WARNING",
                      channels=None, title="Geo",
                      effective_from=DEFAULT_EFFECTIVE_FROM,
                      effective_until=DEFAULT_EFFECTIVE_UNTIL):
    payload = create_alert_payload(
        title=title, severity=severity, channels=channels or ["SMS"],
        target_type="GEO", center_lat=center_lat, center_lon=center_lon, radius_m=radius_m,
        effective_from=effective_from, effective_until=effective_until,
    )
    return get_success_data(api.create_alert(payload, DISPATCHER))


def add_localization(api, alert_id, language="EN", message_text="Warning."):
    return get_success_data(api.add_localization(
        alert_id, create_localization_payload(language=language, message_text=message_text),
        DISPATCHER))


def submit_alert(api, alert_id):
    return get_success_data(api.submit_alert(alert_id, DISPATCHER))


def approve_alert(api, alert_id):
    return get_success_data(api.approve_alert(alert_id, APPROVER))


def create_approved_group_alert(api, group_id, severity="WARNING", channels=None,
                                localization_text="Warning.",
                                effective_from=DEFAULT_EFFECTIVE_FROM,
                                effective_until=DEFAULT_EFFECTIVE_UNTIL, title="Warn"):
    """Compose -> localize (EN) -> submit -> approve. Returns the APPROVED alert."""
    alert = compose_group_alert(api, group_id, severity=severity, channels=channels,
                                title=title, effective_from=effective_from,
                                effective_until=effective_until)
    add_localization(api, alert["id"], "EN", localization_text)
    submit_alert(api, alert["id"])
    return approve_alert(api, alert["id"])


def dispatch_alert(api, alert_id, expected_version):
    return get_success_data(api.dispatch_alert(
        alert_id, {"expected_alert_version": expected_version}, DISPATCHER))


# ----------------------------------------------------- full single-recipient flows
def setup_approved_single_recipient(api, severity="WARNING", channels=None, capacity=100,
                                    tty_required=False, tty_capable=False,
                                    primary_language="EN",
                                    localization_text="Warning.",
                                    clock=DEFAULT_TEST_CLOCK,
                                    effective_from=DEFAULT_EFFECTIVE_FROM,
                                    effective_until=DEFAULT_EFFECTIVE_UNTIL,
                                    address="+15550000"):
    """Clock + one gateway + one confirmed contact in a group + an APPROVED group alert.
    Returns dict {gateway, contact, channel, group, alert} where alert is APPROVED and
    carries its current version."""
    set_clock(api, clock)
    gw_type = (channels or ["SMS"])[0]
    gateway = create_gateway(api, channel_type=gw_type, capacity_per_window=capacity)
    scenario = setup_confirmed_contact_in_group(
        api, primary_language=primary_language, tty_required=tty_required,
        channel_type=gw_type, address=address, tty_capable=tty_capable)
    alert = create_approved_group_alert(
        api, scenario["group"]["id"], severity=severity, channels=channels,
        localization_text=localization_text, effective_from=effective_from,
        effective_until=effective_until)
    return {"gateway": gateway, "contact": scenario["contact"],
            "channel": scenario["channel"], "group": scenario["group"], "alert": alert}


def setup_dispatched_single_recipient(api, **kwargs):
    """As setup_approved_single_recipient, then dispatch (notifications left QUEUED).
    Returns the scenario dict with 'alert' refreshed to the DISPATCHING alert."""
    scenario = setup_approved_single_recipient(api, **kwargs)
    dispatched = dispatch_alert(api, scenario["alert"]["id"], scenario["alert"]["version"])
    scenario["alert"] = dispatched
    return scenario


def get_alert_notifications(api, alert_id, headers=None, params=None):
    q = {"alert_id": alert_id}
    if params:
        q.update(params)
    resp = api.list_notifications(headers or DISPATCHER, params=q)
    return get_success_data(resp)


def setup_sent_single_recipient(api, **kwargs):
    """Dispatch then tick once so the single notification is SENT (alert SENT,
    pending_count=1). Returns scenario dict plus 'notification' (the SENT one)."""
    scenario = setup_dispatched_single_recipient(api, **kwargs)
    run_tick(api)
    notifs = get_alert_notifications(api, scenario["alert"]["id"])
    scenario["notification"] = notifs[0]
    return scenario


def setup_two_channel_recipient_one_delivered(api, clock=DEFAULT_TEST_CLOCK):
    """One contact with CONFIRMED SMS and EMAIL channels in a group; an alert on both
    channels dispatched and ticked so both notifications are SENT; the SMS one then
    reported DELIVERED while the EMAIL one is left SENT. Returns dict with the contact.

    Yields a reliability denominator of 2 (both in {SENT,DELIVERED}); optimistic hits
    are both (SENT+DELIVERED), strict hits are only the DELIVERED one.
    """
    set_clock(api, clock)
    create_gateway(api, channel_type="SMS", capacity_per_window=100)
    create_gateway(api, channel_type="EMAIL", capacity_per_window=100)
    contact = create_contact(api, full_name="Bob", primary_language="EN")
    sms_ch = add_confirmed_channel(api, contact["id"], channel_type="SMS", address="+15550002")
    add_confirmed_channel(api, contact["id"], channel_type="EMAIL", address="bob@x.com")
    group = create_group(api, name="G1")
    subscribe_group(api, contact["id"], group["id"])
    alert = create_approved_group_alert(api, group["id"], severity="WARNING",
                                        channels=["SMS", "EMAIL"],
                                        localization_text="Air quality advisory.")
    dispatch_alert(api, alert["id"], alert["version"])
    run_tick(api)
    sms_notifs = get_alert_notifications(api, alert["id"], params={"channel_id": sms_ch["id"]})
    get_success_data(api.delivery_report(sms_notifs[0]["id"], {"outcome": "DELIVERED"}, INTEGRATOR))
    return {"contact": contact, "alert": alert}
