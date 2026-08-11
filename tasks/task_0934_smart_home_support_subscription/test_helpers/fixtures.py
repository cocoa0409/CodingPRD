"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only — nothing is seeded and nothing is assumed to exist at boot.
Setup calls use the lenient success validator so a broken preamble surfaces as
a setup failure rather than as a confusing assertion failure.
"""

from typing import Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    claim_device_payload,
    create_campaign_payload,
    create_catalog_payload,
    create_household_payload,
    create_member_payload,
    create_plan_payload,
    create_slot_payload,
    create_subscription_payload,
    create_technician_payload,
    create_ticket_payload,
    launch_ring_payload,
    open_rma_payload,
    place_order_payload,
)
from .test_users import (
    AGENT_USER_ID,
    TEST_USERS,
    make_billing_admin_headers,
    make_member_headers,
    make_owner_headers,
    make_technician_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["support_agent_headers"]
DEFAULT_CLOCK = TEST_DEFAULTS["CLOCK"]
BIG_PAGE = {"limit": 100, "offset": 0}


# ==========================================================================
# Tier 0 — primitives
# ==========================================================================
def set_clock(to_iso8601: str = DEFAULT_CLOCK) -> dict:
    """Move the logical clock and return the answering payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def new_plan(kind: str = "PRO", **overrides) -> dict:
    return get_success_data(
        api_client.create_subscription_plan(create_plan_payload(kind, **overrides), ADMIN)
    )


def new_household(**overrides) -> dict:
    return get_success_data(
        api_client.create_household(create_household_payload(**overrides), ADMIN)
    )


def new_member(household_id: str, member_role: str = "OWNER", **overrides) -> dict:
    return get_success_data(
        api_client.add_member(
            household_id, create_member_payload(member_role, **overrides), ADMIN
        )
    )


_OMITTED = object()


def new_subscription(household_id: str, plan_id: str, allow_overage=_OMITTED) -> dict:
    payload = create_subscription_payload(household_id, plan_id)
    if allow_overage is not _OMITTED:
        payload["allow_overage"] = allow_overage
    return get_success_data(api_client.create_subscription(payload, ADMIN))


def new_catalog(kind: str = "HUB", **overrides) -> dict:
    return get_success_data(
        api_client.create_catalog_entry(create_catalog_payload(kind, **overrides), ADMIN)
    )


def claim(
    household_id: str,
    catalog_entry_id: str,
    serial_number: str,
    owner_headers: dict,
    purchase_date: str = TEST_DEFAULTS["PURCHASE_DATE"],
) -> dict:
    return get_success_data(
        api_client.claim_device(
            claim_device_payload(
                household_id, catalog_entry_id, serial_number, purchase_date
            ),
            owner_headers,
        )
    )


def activate(device: dict, owner_headers: dict) -> dict:
    """Echo the token minted at claim; returns the activated device row."""
    return get_success_data(
        api_client.activate_device(
            device["id"], {"activation_code": device["activation_token"]}, owner_headers
        )
    )


def claim_and_activate(
    household_id: str,
    catalog_entry_id: str,
    serial_number: str,
    owner_headers: dict,
    purchase_date: str = TEST_DEFAULTS["PURCHASE_DATE"],
) -> dict:
    device = claim(
        household_id, catalog_entry_id, serial_number, owner_headers, purchase_date
    )
    return activate(device, owner_headers)


def new_technician(
    full_name: str = "Test Tech",
    region_code: str = TEST_DEFAULTS["REGION"],
    skills: Optional[List[str]] = None,
) -> dict:
    return get_success_data(
        api_client.create_technician(
            create_technician_payload(full_name, region_code, skills), ADMIN
        )
    )


def publish_slot(technician_id: str, start_at: str, end_at: str) -> dict:
    """Published by the technician themself, whose identity is the technician row id."""
    return get_success_data(
        api_client.publish_visit_slot(
            technician_id,
            create_slot_payload(start_at, end_at),
            make_technician_headers(technician_id),
        )
    )


def new_ticket(household_id: str, headers: dict, **fields) -> dict:
    return get_success_data(
        api_client.create_ticket(create_ticket_payload(household_id, **fields), headers)
    )


def first_response(ticket_id: str, note: str = "Triaged.") -> dict:
    return get_success_data(api_client.first_response(ticket_id, {"note": note}, AGENT))


def open_session(ticket_id: str) -> dict:
    return get_success_data(api_client.open_remote_session(ticket_id, {}, AGENT))


def complete_session(session_id: str, outcome: str, diagnostic_notes: str = "Notes.") -> dict:
    return get_success_data(
        api_client.complete_remote_session(
            session_id, {"outcome": outcome, "diagnostic_notes": diagnostic_notes}, AGENT
        )
    )


def new_campaign(
    catalog_entry_id: str,
    kind: str = "SECURITY_MANDATORY",
    target_firmware_version: str = "1.1.0",
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_campaign(
            create_campaign_payload(
                catalog_entry_id, kind, target_firmware_version, **overrides
            ),
            ADMIN,
        )
    )


def launch(
    campaign_id: str,
    ring_index: int,
    device_ids: Sequence[str],
    window_start_at: str,
    window_end_at: str,
) -> dict:
    return get_success_data(
        api_client.launch_ring(
            campaign_id,
            launch_ring_payload(
                ring_index, list(device_ids), window_start_at, window_end_at
            ),
            ADMIN,
        )
    )


def report_result(rollout_id: str, result: str) -> dict:
    """Reported by a PlatformAdmin, one of the two roles the PRD authorises."""
    return get_success_data(
        api_client.report_rollout_result(rollout_id, {"result": result}, ADMIN)
    )


def open_rma(device_id: str, expected_device_version: int, **extra) -> dict:
    return get_success_data(
        api_client.open_rma_case(
            open_rma_payload(device_id, expected_device_version, **extra), AGENT
        )
    )


def place_order(
    household_id: str,
    subscription_id: str,
    lines: List[dict],
    expected_subscription_version: int,
    billing_headers: dict,
) -> dict:
    return get_success_data(
        api_client.place_addon_order(
            place_order_payload(
                household_id, subscription_id, lines, expected_subscription_version
            ),
            billing_headers,
        )
    )


def book(ticket_id: str, slot_id: str) -> dict:
    return get_success_data(
        api_client.book_visit({"ticket_id": ticket_id, "slot_id": slot_id}, AGENT)
    )


# ==========================================================================
# Tier 0b — reads (all through PlatformAdmin, which every read authorises)
# ==========================================================================
def fetch_household(household_id: str) -> dict:
    return get_success_data(api_client.get_household(household_id, ADMIN))


def fetch_member(member_id: str) -> dict:
    return get_success_data(api_client.get_household_member(member_id, ADMIN))


def fetch_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_subscription_plan(plan_id, ADMIN))


def fetch_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, ADMIN))


def fetch_catalog_entry(catalog_entry_id: str) -> dict:
    return get_success_data(api_client.get_catalog_entry(catalog_entry_id, ADMIN))


def fetch_device(device_id: str) -> dict:
    return get_success_data(api_client.get_device(device_id, ADMIN))


def fetch_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.get_ticket(ticket_id, ADMIN))


def fetch_sla(ticket_id: str) -> dict:
    return get_success_data(api_client.get_ticket_sla(ticket_id, ADMIN))


def fetch_session(session_id: str) -> dict:
    return get_success_data(api_client.get_remote_session(session_id, ADMIN))


def fetch_technician(technician_id: str) -> dict:
    return get_success_data(api_client.get_technician(technician_id, ADMIN))


def fetch_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_visit_slot(slot_id, ADMIN))


def fetch_visit(visit_id: str) -> dict:
    return get_success_data(api_client.get_visit(visit_id, ADMIN))


def fetch_campaign(campaign_id: str) -> dict:
    return get_success_data(api_client.get_campaign(campaign_id, ADMIN))


def fetch_rollout(rollout_id: str) -> dict:
    return get_success_data(api_client.get_rollout(rollout_id, ADMIN))


def fetch_order(order_id: str) -> dict:
    return get_success_data(api_client.get_addon_order(order_id, ADMIN))


def fetch_rma(rma_id: str) -> dict:
    return get_success_data(api_client.get_rma_case(rma_id, ADMIN))


def fetch_survey(survey_id: str) -> dict:
    return get_success_data(api_client.get_survey(survey_id, ADMIN))


def _rows(response) -> List[dict]:
    body = response.json()
    assert 200 <= response.status_code < 300, (
        f"Setup failed: list call returned {response.status_code}: {body}"
    )
    return body["data"]


def list_devices(**filters) -> List[dict]:
    params = dict(BIG_PAGE)
    params.update(filters)
    return _rows(api_client.list_devices(ADMIN, params=params))


def list_tickets(**filters) -> List[dict]:
    params = dict(BIG_PAGE)
    params.update(filters)
    return _rows(api_client.list_tickets(ADMIN, params=params))


def list_rollouts(**filters) -> List[dict]:
    params = dict(BIG_PAGE)
    params.update(filters)
    return _rows(api_client.list_rollouts(ADMIN, params=params))


def list_credits(**filters) -> List[dict]:
    params = dict(BIG_PAGE)
    params.update(filters)
    return _rows(api_client.list_service_credits(ADMIN, params=params))


def list_surveys(**filters) -> List[dict]:
    params = dict(BIG_PAGE)
    params.update(filters)
    return _rows(api_client.list_surveys(ADMIN, params=params))


def list_orders(**filters) -> List[dict]:
    params = dict(BIG_PAGE)
    params.update(filters)
    return _rows(api_client.list_addon_orders(ADMIN, params=params))


def list_rma_cases(**filters) -> List[dict]:
    params = dict(BIG_PAGE)
    params.update(filters)
    return _rows(api_client.list_rma_cases(ADMIN, params=params))


def list_subscriptions(**filters) -> List[dict]:
    params = dict(BIG_PAGE)
    params.update(filters)
    return _rows(api_client.list_subscriptions(ADMIN, params=params))


def rollout_for_device(device_id: str) -> dict:
    rows = list_rollouts(device_id=device_id)
    assert len(rows) == 1, f"expected exactly one rollout for device {device_id}, got {len(rows)}"
    return rows[0]


# ==========================================================================
# Tier 1 — an account: plan + household + members + subscription
# ==========================================================================
def setup_account(
    plan_kind: str = "PRO",
    plan_overrides: Optional[dict] = None,
    allow_overage=_OMITTED,
    region_code: str = TEST_DEFAULTS["REGION"],
    roles: Sequence[str] = ("OWNER",),
    name: str = "Test House",
    email_prefix: str = "house",
    clock: Optional[str] = DEFAULT_CLOCK,
) -> Dict[str, object]:
    """Plan + household + the requested member roles + an ACTIVE subscription.

    Returns a dict carrying every created row plus ready-made, identity-threaded
    headers for each entity-backed household role.
    """
    if clock is not None:
        set_clock(clock)
    plan = new_plan(plan_kind, **(plan_overrides or {}))
    household = new_household(
        name=name, region_code=region_code, billing_email=f"{email_prefix}@example.com"
    )
    world: Dict[str, object] = {"plan": plan, "household": household}
    for role in roles:
        member = new_member(
            household["id"],
            role,
            full_name=f"{name} {role.title()}",
            email=f"{email_prefix}.{role.lower()}@example.com",
        )
        if role == "OWNER":
            world["owner"] = member
            world["owner_headers"] = make_owner_headers(member["id"])
        elif role == "MEMBER":
            world["member"] = member
            world["member_headers"] = make_member_headers(member["id"])
        elif role == "BILLING_ADMIN":
            world["billing"] = member
            world["billing_headers"] = make_billing_admin_headers(member["id"])
    world["subscription"] = new_subscription(
        household["id"], plan["id"], allow_overage=allow_overage
    )
    return world


def setup_account_with_catalog(
    catalog_kind: str = "HUB",
    **account_kwargs,
) -> Dict[str, object]:
    """An account plus one catalog model, keyed as ``catalog`` in the returned dict."""
    world = setup_account(**account_kwargs)
    world["catalog"] = new_catalog(catalog_kind)
    return world


# ==========================================================================
# Tier 2 — devices in a chosen lifecycle state
# ==========================================================================
def setup_active_device(
    catalog_kind: str = "HUB",
    serial_number: str = "HBX000001",
    purchase_date: str = TEST_DEFAULTS["PURCHASE_DATE"],
    **account_kwargs,
) -> Dict[str, object]:
    """An account, a catalog model, and one CLAIMED-then-ACTIVE device."""
    world = setup_account_with_catalog(catalog_kind, **account_kwargs)
    world["device"] = claim_and_activate(
        world["household"]["id"],
        world["catalog"]["id"],
        serial_number,
        world["owner_headers"],
        purchase_date,
    )
    return world


# ==========================================================================
# Tier 3 — ticket lifecycles
# ==========================================================================
def escalate_by_hardware_fault(ticket_id: str) -> dict:
    """Drive a NEW ticket to DISPATCH_PENDING / REQUIRED via one HARDWARE_FAULT verdict.

    first-response -> open session -> complete HARDWARE_FAULT. Returns the
    completed session row.
    """
    first_response(ticket_id)
    session = open_session(ticket_id)
    return complete_session(session["id"], "HARDWARE_FAULT", "Truck roll.")


def setup_escalated_ticket(
    world: Dict[str, object],
    severity: str = "P1",
    summary: str = "Needs a visit",
    device_id: Optional[str] = None,
) -> dict:
    """Open a ticket on an existing account and escalate it to dispatch-ready."""
    fields = {"severity": severity, "summary": summary}
    if device_id is not None:
        fields["device_id"] = device_id
    if "owner" in world:
        fields["opened_by_member_id"] = world["owner"]["id"]
        headers = world["owner_headers"]
    else:
        headers = AGENT
    ticket = new_ticket(world["household"]["id"], headers, **fields)
    escalate_by_hardware_fault(ticket["id"])
    return ticket


def setup_resolved_ticket(
    world: Dict[str, object],
    severity: str = "P2",
    summary: str = "Quick fix",
    first_response_at: str = "2026-05-01T00:10:00Z",
    resolved_at: str = "2026-05-01T00:20:00Z",
) -> dict:
    """Open a ticket, first-respond, open a session and resolve it at fixed instants."""
    ticket = new_ticket(
        world["household"]["id"],
        world["owner_headers"],
        severity=severity,
        summary=summary,
        opened_by_member_id=world["owner"]["id"],
    )
    set_clock(first_response_at)
    first_response(ticket["id"])
    session = open_session(ticket["id"])
    set_clock(resolved_at)
    complete_session(session["id"], "RESOLVED", "Fixed remotely.")
    return ticket


def setup_dispatch_world(
    slots: Sequence[Sequence[str]] = (("2026-05-05T09:00:00Z", "2026-05-05T11:00:00Z"),),
    technician_region: str = TEST_DEFAULTS["REGION"],
    technician_name: str = "Test Tech",
    **account_kwargs,
) -> Dict[str, object]:
    """An account plus one technician holding the requested OPEN slots."""
    world = setup_account(**account_kwargs)
    technician = new_technician(technician_name, technician_region, ["HUB"])
    world["technician"] = technician
    world["technician_headers"] = make_technician_headers(technician["id"])
    world["slots"] = [publish_slot(technician["id"], s, e) for s, e in slots]
    return world


# ==========================================================================
# Tier 4 — firmware campaigns with a launched ring
# ==========================================================================
def setup_ring(
    device_count: int = 1,
    kind: str = "SECURITY_MANDATORY",
    halt_failure_rate_pct: float = 0.5,
    target_firmware_version: str = "1.1.0",
    window: Sequence[str] = ("2026-05-01T00:00:00Z", "2026-05-10T00:00:00Z"),
    **account_kwargs,
) -> Dict[str, object]:
    """An account with ``device_count`` ACTIVE HUBs and ring 1 launched over all of them.

    Returns the world dict extended with ``devices``, ``campaign`` and
    ``rollouts`` (one rollout per device, in the same order).
    """
    account_kwargs.setdefault(
        "plan_overrides", {"included_device_count": max(device_count, 1)}
    )
    world = setup_account_with_catalog("HUB", **account_kwargs)
    devices = [
        claim_and_activate(
            world["household"]["id"],
            world["catalog"]["id"],
            f"HBX{i + 1:06d}",
            world["owner_headers"],
        )
        for i in range(device_count)
    ]
    world["devices"] = devices
    campaign = new_campaign(
        world["catalog"]["id"],
        kind,
        target_firmware_version,
        halt_failure_rate_pct=halt_failure_rate_pct,
    )
    world["campaign"] = launch(
        campaign["id"], 1, [d["id"] for d in devices], window[0], window[1]
    )
    world["campaign_id"] = campaign["id"]
    world["rollouts"] = [rollout_for_device(d["id"]) for d in devices]
    return world


# ==========================================================================
# Tier 5 — RMA cases in a chosen stage
# ==========================================================================
def setup_advance_replacement_case(
    serial_number: str = "HBX000001",
    **account_kwargs,
) -> Dict[str, object]:
    """A PRO account with one ACTIVE HUB and an ADVANCE_REPLACEMENT case in ROUTED."""
    account_kwargs.setdefault("plan_kind", "PRO")
    world = setup_active_device(serial_number=serial_number, **account_kwargs)
    world["rma"] = open_rma(world["device"]["id"], world["device"]["version"])
    return world


def setup_shipped_advance_case(**account_kwargs) -> Dict[str, object]:
    """As above, then ship the advance unit so the case is AWAITING_RETURN."""
    world = setup_advance_replacement_case(**account_kwargs)
    world["rma"] = get_success_data(
        api_client.ship_advance_replacement(world["rma"]["id"], {}, AGENT)
    )
    return world
