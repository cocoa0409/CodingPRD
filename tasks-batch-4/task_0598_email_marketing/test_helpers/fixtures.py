"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints:
the API server is restarted (and its database emptied) before every individual test.
Setup calls use the lenient validator so a broken precondition surfaces as a clear
"Setup failed" rather than as a confusing assertion deep inside a test.

Identity threading: `CampaignAuthor` and `ComplianceApprover` are entity-backed roles
(PRD §2.1), so every ownership-gated call below passes the real AccountUser id through
make_campaign_author_headers() / make_compliance_approver_headers().
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO, COMPLIANT_HTML_BODY, TEST_DEFAULTS
from .factories import (
    clock_payload,
    confirm_payload,
    create_account_payload,
    create_account_user_payload,
    create_audience_payload,
    create_campaign_payload,
    create_import_job_payload,
    create_journey_payload,
    create_segment_payload,
    create_subscriber_payload,
    create_template_payload,
    email_step,
    event_payload,
    import_rows,
    review_payload,
    schedule_payload,
    unsubscribe_payload,
    wait_step,
)
from .test_users import (
    ANONYMOUS,
    PLATFORM,
    make_campaign_author_headers,
    make_compliance_approver_headers,
)

DISPATCH_AT = TEST_DEFAULTS["DISPATCH_AT"]  # "2026-05-02T10:00:00Z"
SEND_WINDOW = TEST_DEFAULTS["SEND_WINDOW_MINUTES"]  # 60


# ─── Logical-clock helpers (PRD §2.4) ───────────────────────────────────────

def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value.replace("Z", "").split(".")[0], "%Y-%m-%dT%H:%M:%S").replace(
        tzinfo=timezone.utc
    )


def shift(base_iso: str, **delta) -> str:
    """Return `base_iso` moved by the supplied timedelta keywords (hours=, days=, minutes=)."""
    return iso(parse_iso(base_iso) + timedelta(**delta))


CLOCK_START = parse_iso(CLOCK_START_ISO)


def set_clock(to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc — moves the server's logical clock."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), PLATFORM))


def ops_run() -> dict:
    """POST /_ops/run — advance the operations epoch through its five phases."""
    return get_success_data(api_client.ops_run(PLATFORM))


def advance_epoch_to(to_iso8601: str) -> dict:
    """Move the clock to `to_iso8601`, then run one operations epoch."""
    set_clock(to_iso8601)
    return ops_run()


# ─── Tenant provisioning (PRD §3.1) ─────────────────────────────────────────

class Tenant:
    """An account, its operators and their headers."""

    def __init__(self, account, author, approver, dual=None):
        self.account = account
        self.id = account["id"]
        self.author = author
        self.author_id = author["id"] if author else None
        self.author_headers = make_campaign_author_headers(author["id"]) if author else None
        self.approver = approver
        self.approver_id = approver["id"] if approver else None
        self.approver_headers = (
            make_compliance_approver_headers(approver["id"]) if approver else None
        )
        self.dual = dual
        self.dual_id = dual["id"] if dual else None

    def refresh(self) -> dict:
        """Re-read the account (also the way a client captures expected_account_version)."""
        self.account = get_success_data(api_client.get_account(self.id, PLATFORM))
        return self.account

    @property
    def version(self) -> int:
        return self.refresh()["version"]


def provision_tenant(
    plan_tier="ESSENTIALS",
    initial_send_credits=TEST_DEFAULTS["SEND_CREDITS"],
    hourly_send_capacity=TEST_DEFAULTS["HOURLY_SEND_CAPACITY"],
    name="Acme",
    with_author=True,
    with_approver=True,
    with_dual=False,
) -> Tenant:
    """Create an account plus the operators the tests act as."""
    payload = create_account_payload(
        name=name,
        plan_tier=plan_tier,
        initial_send_credits=initial_send_credits,
        hourly_send_capacity=hourly_send_capacity,
    )
    account = get_success_data(api_client.create_account(payload, PLATFORM))

    author = approver = dual = None
    if with_author:
        author = get_success_data(
            api_client.create_account_user(
                account["id"],
                create_account_user_payload(email="author@acme.com", user_role="CAMPAIGN_AUTHOR"),
                PLATFORM,
            )
        )
    if with_approver:
        approver = get_success_data(
            api_client.create_account_user(
                account["id"],
                create_account_user_payload(email="appr@acme.com", user_role="COMPLIANCE_APPROVER"),
                PLATFORM,
            )
        )
    if with_dual:
        dual = get_success_data(
            api_client.create_account_user(
                account["id"],
                create_account_user_payload(email="dual@acme.com", user_role="DUAL"),
                PLATFORM,
            )
        )
    return Tenant(account, author, approver, dual)


def create_dual_only_tenant(
    plan_tier="ESSENTIALS",
    initial_send_credits=TEST_DEFAULTS["SEND_CREDITS"],
    hourly_send_capacity=TEST_DEFAULTS["HOURLY_SEND_CAPACITY"],
) -> tuple:
    """Account whose single operator holds user_role DUAL (so it may claim either header)."""
    account = get_success_data(
        api_client.create_account(
            create_account_payload(
                plan_tier=plan_tier,
                initial_send_credits=initial_send_credits,
                hourly_send_capacity=hourly_send_capacity,
            ),
            PLATFORM,
        )
    )
    dual = get_success_data(
        api_client.create_account_user(
            account["id"],
            create_account_user_payload(email="dual@acme.com", user_role="DUAL"),
            PLATFORM,
        )
    )
    return account, dual


# ─── Audiences and subscribers (PRD §3.2) ───────────────────────────────────

def create_audience(tenant: Tenant, name="Main", double_optin_required=False, headers=None) -> dict:
    return get_success_data(
        api_client.create_audience(
            create_audience_payload(
                tenant.id, name=name, double_optin_required=double_optin_required
            ),
            headers or tenant.author_headers or PLATFORM,
        )
    )


def add_subscriber(audience_id: str, email: str, headers, consent_source="API", **overrides) -> dict:
    return get_success_data(
        api_client.create_subscriber(
            audience_id,
            create_subscriber_payload(email=email, consent_source=consent_source, **overrides),
            headers,
        )
    )


def add_subscribers(audience_id: str, emails, headers, consent_source="API") -> list:
    """Add each address in order; on a single-opt-in audience each lands directly in CONFIRMED."""
    return [add_subscriber(audience_id, e, headers, consent_source) for e in emails]


def add_confirmed_subscribers(audience_id: str, count: int, headers, prefix="s") -> list:
    """Add `count` contacts named s1@x.com .. sN@x.com to a single-opt-in audience."""
    return add_subscribers(audience_id, [f"{prefix}{i}@x.com" for i in range(1, count + 1)], headers)


def confirm_subscriber(subscriber: dict) -> dict:
    """Anonymous double-opt-in confirmation with the token minted at creation."""
    return get_success_data(
        api_client.confirm_subscriber(
            subscriber["id"], confirm_payload(subscriber["confirmation_token"]), ANONYMOUS
        )
    )


def unsubscribe(subscriber: dict) -> dict:
    """Anonymous one-click unsubscribe with the subscriber's stable unsubscribe_token."""
    return get_success_data(
        api_client.unsubscribe_subscriber(
            subscriber["id"], unsubscribe_payload(subscriber["unsubscribe_token"]), ANONYMOUS
        )
    )


def read_subscriber(subscriber_id: str, headers=PLATFORM) -> dict:
    return get_success_data(api_client.get_subscriber(subscriber_id, headers))


def read_audience(audience_id: str, headers=PLATFORM) -> dict:
    return get_success_data(api_client.get_audience(audience_id, headers))


def audience_version(audience_id: str, headers=PLATFORM) -> int:
    return read_audience(audience_id, headers)["version"]


def run_import(audience_id: str, emails, headers, expected_version=None) -> dict:
    """POST /audiences/{id}/import-jobs with a freshly read expected_audience_version."""
    version = expected_version if expected_version is not None else audience_version(audience_id)
    return get_success_data(
        api_client.create_import_job(
            audience_id, create_import_job_payload(import_rows(emails), version), headers
        )
    )


# ─── Templates and campaigns (PRD §3.5) ─────────────────────────────────────

def create_template(tenant: Tenant, html_body=COMPLIANT_HTML_BODY, name="T", subject="Spring Sale") -> dict:
    return get_success_data(
        api_client.create_template(
            create_template_payload(tenant.id, name=name, subject=subject, html_body=html_body),
            tenant.author_headers,
        )
    )


def create_published_template(
    tenant: Tenant, html_body=COMPLIANT_HTML_BODY, name="T", subject="Spring Sale"
) -> dict:
    """Create a template and walk DRAFT -> PUBLISHED. Returns the published template (version 2)."""
    template = create_template(tenant, html_body=html_body, name=name, subject=subject)
    return get_success_data(api_client.publish_template(template["id"], tenant.author_headers))


def create_campaign(tenant: Tenant, audience_id: str, template_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_campaign(
            create_campaign_payload(tenant.id, audience_id, template_id, **overrides),
            tenant.author_headers,
        )
    )


def create_approved_campaign(tenant: Tenant, audience_id: str, template_id: str, **overrides) -> dict:
    """Create -> submit-review -> APPROVE. Returns the campaign in APPROVED."""
    campaign = create_campaign(tenant, audience_id, template_id, **overrides)
    get_success_data(api_client.submit_campaign_review(campaign["id"], tenant.author_headers))
    return get_success_data(
        api_client.review_campaign(
            campaign["id"], review_payload("APPROVE"), tenant.approver_headers
        )
    )


def schedule(tenant: Tenant, campaign_id: str, scheduled_at=DISPATCH_AT, send_window_minutes=SEND_WINDOW):
    """Schedule a campaign with a freshly captured expected_account_version. Returns the raw response."""
    return api_client.schedule_campaign(
        campaign_id,
        schedule_payload(scheduled_at, tenant.version, send_window_minutes),
        tenant.author_headers,
    )


def schedule_ok(tenant: Tenant, campaign_id: str, scheduled_at=DISPATCH_AT, send_window_minutes=SEND_WINDOW) -> dict:
    return get_success_data(schedule(tenant, campaign_id, scheduled_at, send_window_minutes))


def read_campaign(campaign_id: str, headers=PLATFORM) -> dict:
    return get_success_data(api_client.get_campaign(campaign_id, headers))


# ─── Dispatch and telemetry (PRD §3.7, §3.8) ────────────────────────────────

def sends_of_campaign(campaign_id: str, headers=PLATFORM) -> list:
    """Sends of one campaign, in created_at ASC order — i.e. in recipient-snapshot order."""
    data = get_success_data(api_client.list_sends(headers, {"campaign_id": campaign_id, "limit": 100}))
    return data if isinstance(data, list) else data.get("data", [])


def sends_of_journey(journey_id: str, headers=PLATFORM) -> list:
    data = get_success_data(api_client.list_sends(headers, {"journey_id": journey_id, "limit": 100}))
    return data if isinstance(data, list) else data.get("data", [])


def read_send(send_id: str, headers=PLATFORM) -> dict:
    return get_success_data(api_client.get_send(send_id, headers))


def emit(send_id: str, kind: str) -> dict:
    """POST /_events/emit — inject one delivery-infrastructure event against a send."""
    return get_success_data(api_client.emit_event(event_payload(send_id, kind), PLATFORM))


def deliver(send_id: str) -> dict:
    return emit(send_id, "DELIVERED")


def open_send(send_id: str) -> dict:
    return emit(send_id, "OPEN")


def click_send(send_id: str) -> dict:
    return emit(send_id, "CLICK")


def suppressions_of(account_id: str, headers=PLATFORM) -> list:
    data = get_success_data(api_client.list_suppressions(account_id, headers, {"limit": 100}))
    return data if isinstance(data, list) else data.get("data", [])


def billing_cycles_of(account_id: str, headers=PLATFORM) -> list:
    data = get_success_data(api_client.list_billing_cycles(account_id, headers, {"limit": 100}))
    return data if isinstance(data, list) else data.get("data", [])


# ─── Tier 2/3: full dispatch scenarios ──────────────────────────────────────

class Dispatched:
    """A tenant whose campaign has been scheduled and dispatched into SENDING."""

    def __init__(self, tenant, audience, template, campaign, subscribers, sends):
        self.tenant = tenant
        self.account_id = tenant.id
        self.audience = audience
        self.audience_id = audience["id"]
        self.template = template
        self.campaign = campaign
        self.campaign_id = campaign["id"]
        self.subscribers = subscribers
        self.sends = sends
        self.send_ids = [s["id"] for s in sends]


def setup_dispatched_campaign(
    num_subscribers=1,
    plan_tier="ESSENTIALS",
    initial_send_credits=TEST_DEFAULTS["SEND_CREDITS"],
    hourly_send_capacity=TEST_DEFAULTS["HOURLY_SEND_CAPACITY"],
    scheduled_at=DISPATCH_AT,
    send_window_minutes=SEND_WINDOW,
    html_body=COMPLIANT_HTML_BODY,
    **campaign_overrides,
) -> Dispatched:
    """Account -> operators -> single-opt-in audience with N CONFIRMED contacts -> published
    template -> campaign -> submit -> approve -> schedule -> clock to scheduled_at -> ops run.

    Returns the tenant, the audience, the campaign (now SENDING) and its minted Sends,
    in recipient-snapshot order.
    """
    tenant = provision_tenant(
        plan_tier=plan_tier,
        initial_send_credits=initial_send_credits,
        hourly_send_capacity=hourly_send_capacity,
    )
    audience = create_audience(tenant, double_optin_required=False)
    subscribers = add_confirmed_subscribers(audience["id"], num_subscribers, tenant.author_headers)
    template = create_published_template(tenant, html_body=html_body)
    campaign = create_approved_campaign(tenant, audience["id"], template["id"], **campaign_overrides)
    campaign = schedule_ok(tenant, campaign["id"], scheduled_at, send_window_minutes)
    advance_epoch_to(scheduled_at)
    sends = sends_of_campaign(campaign["id"])
    return Dispatched(tenant, audience, template, campaign, subscribers, sends)


def setup_sent_campaign(num_subscribers=1, **kwargs) -> Dispatched:
    """As setup_dispatched_campaign, then DELIVER every send so the campaign bubbles to SENT."""
    env = setup_dispatched_campaign(num_subscribers=num_subscribers, **kwargs)
    for send_id in env.send_ids:
        deliver(send_id)
    env.campaign = read_campaign(env.campaign_id)
    return env


def setup_ab_sent_campaign(num_subscribers=4, variant_split_pct=50, **kwargs) -> Dispatched:
    """An A/B campaign dispatched and fully delivered, so it sits in SENT with A/B labelled sends."""
    return setup_sent_campaign(
        num_subscribers=num_subscribers,
        ab_test_enabled=True,
        variant_split_pct=variant_split_pct,
        variant_b_subject="Spring Sale (B)",
        name="AB1",
        **kwargs,
    )


def setup_approved_campaign(
    num_subscribers=2,
    plan_tier="ESSENTIALS",
    initial_send_credits=TEST_DEFAULTS["SEND_CREDITS"],
    hourly_send_capacity=TEST_DEFAULTS["HOURLY_SEND_CAPACITY"],
    double_optin_required=False,
    html_body=COMPLIANT_HTML_BODY,
    **campaign_overrides,
) -> Dispatched:
    """Everything up to (but not including) the schedule: campaign sits in APPROVED."""
    tenant = provision_tenant(
        plan_tier=plan_tier,
        initial_send_credits=initial_send_credits,
        hourly_send_capacity=hourly_send_capacity,
    )
    audience = create_audience(tenant, double_optin_required=double_optin_required)
    subscribers = add_confirmed_subscribers(audience["id"], num_subscribers, tenant.author_headers)
    template = create_published_template(tenant, html_body=html_body)
    campaign = create_approved_campaign(tenant, audience["id"], template["id"], **campaign_overrides)
    return Dispatched(tenant, audience, template, campaign, subscribers, [])


def setup_suspended_account(num_extra_subscribers=2) -> dict:
    """Drive an account to SUSPENDED via the hard-bounce threshold (PRD §2.10).

    Campaign C1 dispatches 4 sends; 3 are DELIVERED and the 4th HARD_BOUNCES, so the
    account holds exactly 4 scored sends of which exactly 1 hard-bounced (rate 0.25).
    A second audience with `num_extra_subscribers` contacts is left free for a follow-up
    campaign. Returns a dict with the tenant, both audiences, the template and campaign C1.
    """
    tenant = provision_tenant(
        plan_tier="ESSENTIALS",
        initial_send_credits=TEST_DEFAULTS["SEND_CREDITS"],
        hourly_send_capacity=TEST_DEFAULTS["HOURLY_SEND_CAPACITY"],
    )
    aud1 = create_audience(tenant, name="L1", double_optin_required=False)
    aud2 = create_audience(tenant, name="L2", double_optin_required=False)
    add_subscribers(aud1["id"], [f"a{i}@x.com" for i in range(1, 5)], tenant.author_headers)
    add_subscribers(
        aud2["id"],
        [f"b{i}@x.com" for i in range(1, num_extra_subscribers + 1)],
        tenant.author_headers,
    )
    template = create_published_template(tenant)
    c1 = create_approved_campaign(tenant, aud1["id"], template["id"], name="C1")
    schedule_ok(tenant, c1["id"], DISPATCH_AT, SEND_WINDOW)
    advance_epoch_to(DISPATCH_AT)
    sends = sends_of_campaign(c1["id"])
    deliver(sends[0]["id"])
    deliver(sends[1]["id"])
    deliver(sends[2]["id"])
    emit(sends[3]["id"], "HARD_BOUNCE")
    return {
        "tenant": tenant,
        "audience_1": aud1,
        "audience_2": aud2,
        "template": template,
        "campaign_1": c1,
        "sends_1": sends,
    }


def setup_lifetime_vs_rolling_engagement() -> dict:
    """One contact with a deliberately split send history (PRD §3.4).

    Campaign C1 is dispatched at 2026-05-02T10:00:00Z and its send to s1 is DELIVERED,
    OPENED and CLICKED. Campaign C2 is dispatched 123 days later, at 2026-09-02T10:00:00Z,
    and its send to s1 is DELIVERED. The caller triggers the final OPEN.

    Returns the tenant, the subscriber and both send ids.
    """
    old_dispatch = "2026-05-02T10:00:00Z"
    new_dispatch = "2026-09-02T10:00:00Z"

    tenant = provision_tenant(plan_tier="FREE", initial_send_credits=50, hourly_send_capacity=100)
    audience = create_audience(tenant, double_optin_required=False)
    s1 = add_subscriber(audience["id"], "s1@x.com", tenant.author_headers)
    template = create_published_template(tenant)

    c1 = create_approved_campaign(tenant, audience["id"], template["id"], name="C1")
    schedule_ok(tenant, c1["id"], old_dispatch, SEND_WINDOW)
    advance_epoch_to(old_dispatch)
    send_1 = sends_of_campaign(c1["id"])[0]["id"]
    deliver(send_1)
    open_send(send_1)
    click_send(send_1)

    set_clock("2026-09-01T00:00:00Z")
    c2 = create_approved_campaign(tenant, audience["id"], template["id"], name="C2")
    schedule_ok(tenant, c2["id"], new_dispatch, SEND_WINDOW)
    advance_epoch_to(new_dispatch)
    send_2 = sends_of_campaign(c2["id"])[0]["id"]
    deliver(send_2)

    return {
        "tenant": tenant,
        "audience": audience,
        "subscriber_id": s1["id"],
        "old_send_id": send_1,
        "new_send_id": send_2,
    }


# ─── Journeys (PRD §3.10) ───────────────────────────────────────────────────

class JourneyEnv:
    def __init__(self, tenant, audience, template, journey):
        self.tenant = tenant
        self.audience = audience
        self.audience_id = audience["id"]
        self.template = template
        self.journey = journey
        self.journey_id = journey["id"]


def setup_active_journey(
    steps=None,
    wait_hours=24,
    trigger_event="SUBSCRIBE_CONFIRMED",
    double_optin_required=False,
    publish_template=True,
    initial_send_credits=0,
) -> JourneyEnv:
    """Account -> audience -> (published) template -> journey -> activate.

    The default step list is `WAIT 24h` then `EMAIL`, which is the shape that exercises
    the WAIT-stops / EMAIL-continues rules of the epoch's third phase. The account is
    granted no send credits by default, so a journey email that wrongly debited the
    ledger would be immediately visible.
    """
    tenant = provision_tenant(initial_send_credits=initial_send_credits)
    audience = create_audience(tenant, double_optin_required=double_optin_required)
    template = (
        create_published_template(tenant, name="T", subject="Welcome")
        if publish_template
        else create_template(tenant, name="T", subject="Welcome")
    )
    if steps is None:
        steps = [wait_step(0, wait_hours), email_step(1, template["id"])]
    journey = get_success_data(
        api_client.create_journey(
            create_journey_payload(
                tenant.id, audience["id"], steps, name="Welcome flow", trigger_event=trigger_event
            ),
            tenant.author_headers,
        )
    )
    journey = get_success_data(api_client.activate_journey(journey["id"], tenant.author_headers))
    return JourneyEnv(tenant, audience, template, journey)


def enrollments_of_journey(journey_id: str, headers=PLATFORM) -> list:
    data = get_success_data(
        api_client.list_journey_enrollments(journey_id, headers, {"limit": 100})
    )
    return data if isinstance(data, list) else data.get("data", [])


def enrollments_of_subscriber(subscriber_id: str, headers=PLATFORM) -> list:
    data = get_success_data(
        api_client.list_subscriber_enrollments(subscriber_id, headers, {"limit": 100})
    )
    return data if isinstance(data, list) else data.get("data", [])


def read_journey(journey_id: str, headers=PLATFORM) -> dict:
    return get_success_data(api_client.get_journey(journey_id, headers))


# ─── Segments (PRD §3.4) ────────────────────────────────────────────────────

def create_segment(audience_id: str, headers, **overrides) -> dict:
    return get_success_data(
        api_client.create_segment(audience_id, create_segment_payload(**overrides), headers)
    )


def segments_of(audience_id: str, headers=PLATFORM) -> list:
    data = get_success_data(api_client.list_segments(audience_id, headers, {"limit": 100}))
    return data if isinstance(data, list) else data.get("data", [])
