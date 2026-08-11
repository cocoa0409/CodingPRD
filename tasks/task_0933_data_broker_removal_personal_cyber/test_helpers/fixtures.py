"""Composite setup helpers.

Every helper builds its preconditions from scratch through published
endpoints only — the database is empty at the start of every test.  Setup
calls use the lenient validator so a broken precondition surfaces as a clear
"setup failed" rather than as a confusing assertion deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .api_errors import ApiErrorId
from . import factories as f
from .constants import FAMILY_PLAN, SOLO_PLAN, FAMILY_PLUS_PLAN
from .test_users import (
    ADMIN, AGENT, AGENT_BETA, AUDITOR,
    ADMIN_USER_ID, AGENT_ALPHA_ID, AGENT_BETA_ID, AUDITOR_USER_ID,
    make_account_owner_headers, make_member_headers, make_agent_headers,
)


# --------------------------------------------------------------------------
# Tier 0 — primitives
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock. Returns {current_utc, previous_utc}."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_plan(**overrides) -> dict:
    return get_success_data(api.create_plan(f.create_plan_payload(**overrides), ADMIN))


def create_family_plan(**overrides) -> dict:
    return create_plan(**{**FAMILY_PLAN, **overrides})


def create_solo_plan(**overrides) -> dict:
    return create_plan(**{**SOLO_PLAN, **overrides})


def create_family_plus_plan(**overrides) -> dict:
    return create_plan(**{**FAMILY_PLUS_PLAN, **overrides})


def create_broker(**overrides) -> dict:
    return get_success_data(api.create_broker(f.create_broker_payload(**overrides), ADMIN))


# --------------------------------------------------------------------------
# Tier 1 — the household
# --------------------------------------------------------------------------

class Household(dict):
    """A plan, an account, its primary member and that member's headers."""

    @property
    def account_id(self):
        return self["account_id"]

    @property
    def owner_id(self):
        return self["owner_id"]

    @property
    def owner(self):
        return self["owner"]

    @property
    def plan_id(self):
        return self["plan_id"]


def open_household(plan=None, email="owner@example.com",
                   full_name="Dana Owner", **plan_overrides) -> Household:
    """Register a plan (FAMILY by default) and open an account on it."""
    if plan is None:
        plan = create_family_plan(**plan_overrides)
    account = get_success_data(api.create_account(
        f.create_account_payload(plan["id"],
                                 primary_member_email=email,
                                 primary_member_full_name=full_name),
        ADMIN,
    ))
    owner_id = account["primary_member_id"]
    return Household(
        plan=plan,
        plan_id=plan["id"],
        account=account,
        account_id=account["id"],
        owner_id=owner_id,
        owner=make_account_owner_headers(owner_id),
    )


def read_account(household) -> dict:
    return get_success_data(api.get_account(household["account_id"], ADMIN))


def account_version(household) -> int:
    return read_account(household)["version"]


def first_cycle(household) -> dict:
    data, _ = _paginate(api.list_billing_cycles(household["account_id"], ADMIN))
    return data[0]


def open_cycle(household) -> dict:
    """The account's single cycle in OPEN, or None when there is none."""
    data, _ = _paginate(api.list_billing_cycles(household["account_id"], ADMIN))
    for cycle in data:
        if cycle["status"] == "OPEN":
            return cycle
    return None


def _paginate(response):
    body = response.json()
    assert response.status_code == 200, f"Setup failed: {response.status_code} {response.text}"
    return body["data"], body["meta"]


def invite_member(household, email="kid@example.com", full_name="Robin Kid",
                  role_in_family="MINOR") -> dict:
    """Invite one household member, reading the account version first."""
    payload = f.invite_member_payload(account_version(household),
                                      email=email, full_name=full_name,
                                      role_in_family=role_in_family)
    return get_success_data(api.invite_member(household["account_id"], payload,
                                              household["owner"]))


def invite_and_activate_member(household, email="kid@example.com",
                               full_name="Robin Kid",
                               role_in_family="MINOR") -> dict:
    """Invite a member and redeem their token, returning the ACTIVE row."""
    member = invite_member(household, email=email, full_name=full_name,
                           role_in_family=role_in_family)
    return get_success_data(api.activate_member(member["id"],
                                                member["invitation_token"],
                                                make_member_headers(member["id"])))


# --------------------------------------------------------------------------
# Tier 2 — monitored profiles and identifiers
# --------------------------------------------------------------------------

def draft_profile(household, member_id=None, headers=None, **overrides) -> dict:
    member_id = member_id or household["owner_id"]
    headers = headers or household["owner"]
    return get_success_data(api.create_monitored_profile(
        f.create_monitored_profile_payload(member_id, **overrides), headers))


def profile_version(profile_id, headers) -> int:
    return get_success_data(api.get_monitored_profile(profile_id, headers))["version"]


def add_identifier(profile_id, headers, identifier_type="EMAIL",
                   identifier_value="dana@example.com") -> dict:
    """Add one identifier, always reading the profile's current version first."""
    payload = f.add_identifier_payload(profile_version(profile_id, headers),
                                       identifier_type=identifier_type,
                                       identifier_value=identifier_value)
    return get_success_data(api.add_identifier(profile_id, payload, headers))


def setup_active_profile(household, member_id=None, headers=None,
                         identifier_value="dana@example.com",
                         identifier_type="EMAIL", **overrides) -> dict:
    """Draft a profile, attach one identifier and activate it.

    Returns the ACTIVE profile row (the activation response).
    """
    headers = headers or household["owner"]
    profile = draft_profile(household, member_id=member_id, headers=headers, **overrides)
    add_identifier(profile["id"], headers,
                   identifier_type=identifier_type,
                   identifier_value=identifier_value)
    return get_success_data(api.activate_profile(profile["id"], headers))


def read_profile(profile_id, headers=None) -> dict:
    return get_success_data(api.get_monitored_profile(profile_id, headers or ADMIN))


# --------------------------------------------------------------------------
# Tier 3 — scans, findings and exposures
# --------------------------------------------------------------------------

def queue_scan(profile_id, kind="INITIAL", headers=None) -> dict:
    return get_success_data(api.create_scan_run(
        f.create_scan_run_payload(profile_id, kind), headers or AGENT))


def start_scan(scan_id) -> dict:
    return get_success_data(api.start_scan(scan_id, AGENT))


def complete_scan(scan_id) -> dict:
    return get_success_data(api.complete_scan(scan_id, AGENT))


def record_finding(scan_id, broker_id, exposure_kind="PEOPLE_SEARCH",
                   source_url=None) -> dict:
    payload = f.record_finding_payload(broker_id, exposure_kind=exposure_kind)
    if source_url is not None:
        payload["source_url"] = source_url
    return get_success_data(api.record_finding(scan_id, payload, AGENT))


def run_scan(profile_id, broker_ids=(), kind="INITIAL", complete=True,
             exposure_kind="PEOPLE_SEARCH"):
    """Queue → start → one finding per broker → optionally complete.

    Returns (scan, [exposure rows in broker order]).
    """
    scan = queue_scan(profile_id, kind)
    start_scan(scan["id"])
    exposures = [record_finding(scan["id"], broker_id, exposure_kind=exposure_kind,
                                source_url=f"https://broker-{i}.example/dana")
                 for i, broker_id in enumerate(broker_ids)]
    if complete:
        complete_scan(scan["id"])
    return scan, exposures


def read_exposure(exposure_id, headers=None) -> dict:
    return get_success_data(api.get_exposure(exposure_id, headers or ADMIN))


def count_exposures(headers=None, **params) -> int:
    _, meta = _paginate(api.list_exposures(headers or ADMIN, params=params))
    return meta["total_count"]


# --------------------------------------------------------------------------
# Tier 4 — removal-request lifecycles
# --------------------------------------------------------------------------

def draft_removal(exposure_id, headers=None) -> dict:
    return get_success_data(api.create_removal_request(exposure_id, headers or AGENT))


def submit_removal(request_id, agent_headers=None) -> dict:
    return get_success_data(api.submit_removal_request(request_id, agent_headers or AGENT))


def acknowledge_removal(request_id, broker_reference="QL-1") -> dict:
    return get_success_data(api.acknowledge_removal_request(request_id,
                                                            broker_reference, AGENT))


def complete_removal(request_id, agent_headers=None) -> dict:
    """Completion must come from an agent identity other than the submitter."""
    return get_success_data(api.complete_removal_request(request_id,
                                                         agent_headers or AGENT_BETA))


def reject_removal(request_id, rejection_reason_code="IDENTITY_MISMATCH") -> dict:
    return get_success_data(api.reject_removal_request(request_id,
                                                       rejection_reason_code, AGENT))


def suppress_exposure(exposure_id, broker_reference="QL-1") -> dict:
    """Draft → submit → acknowledge → complete, which suppresses the exposure.

    Returns the COMPLETED removal request.
    """
    request = draft_removal(exposure_id)
    submit_removal(request["id"])
    acknowledge_removal(request["id"], broker_reference)
    return complete_removal(request["id"])


def acknowledged_removal(exposure_id, broker_reference="QL-1") -> dict:
    request = draft_removal(exposure_id)
    submit_removal(request["id"])
    return acknowledge_removal(request["id"], broker_reference)


def read_removal(request_id, headers=None) -> dict:
    return get_success_data(api.get_removal_request(request_id, headers or ADMIN))


def drive_removal_around_loop(exposure_id, laps, broker_reference_prefix="QL"):
    """Draft, then run `laps` full submit → acknowledge → reject → escalate laps.

    After the final lap the request sits in REJECTED with escalation_count
    equal to `laps`, which is the state the escalation cap is probed from.
    Returns the removal request id.
    """
    request = draft_removal(exposure_id)
    rid = request["id"]
    for lap in range(laps + 1):
        submit_removal(rid)
        acknowledge_removal(rid, f"{broker_reference_prefix}-{lap + 1}")
        reject_removal(rid)
        if lap < laps:
            get_success_data(api.escalate_removal_request(rid, AGENT))
    return rid


# --------------------------------------------------------------------------
# Tier 5 — add-ons, device seats and billing
# --------------------------------------------------------------------------

def buy_addon(household, addon_type="VPN", seats_total=2,
              per_seat_fee_cents=300, headers=None) -> dict:
    payload = f.create_addon_payload(addon_type=addon_type,
                                     seats_total=seats_total,
                                     per_seat_fee_cents=per_seat_fee_cents)
    return get_success_data(api.create_addon(household["account_id"], payload,
                                             headers or household["owner"]))


def read_addon(addon_id, headers=None) -> dict:
    return get_success_data(api.get_addon(addon_id, headers or ADMIN))


def addon_version(addon_id, headers=None) -> int:
    return read_addon(addon_id, headers)["version"]


def bind_seat(household, addon_id, member_id=None, device_label="Dana Laptop",
              headers=None) -> dict:
    """Bind one seat, always reading the add-on's current version first."""
    headers = headers or household["owner"]
    payload = f.create_device_seat_payload(addon_id,
                                           member_id or household["owner_id"],
                                           addon_version(addon_id, headers),
                                           device_label=device_label)
    return get_success_data(api.create_device_seat(payload, headers))


def setup_addon_with_seat(household, addon_type="VPN", seats_total=2,
                          per_seat_fee_cents=300, device_label="Dana Laptop"):
    """An ACTIVE add-on carrying exactly one BOUND seat. Returns (addon, seat)."""
    addon = buy_addon(household, addon_type=addon_type, seats_total=seats_total,
                      per_seat_fee_cents=per_seat_fee_cents)
    seat = bind_seat(household, addon["id"], device_label=device_label)
    return addon, seat


def read_seat(seat_id, headers=None) -> dict:
    return get_success_data(api.get_device_seat(seat_id, headers or ADMIN))


def release_seat(seat_id, headers) -> dict:
    return get_success_data(api.release_seat(seat_id, headers))


# --------------------------------------------------------------------------
# Tier 6 — breach monitoring
# --------------------------------------------------------------------------

def create_breach_event(**overrides) -> dict:
    return get_success_data(api.create_breach_event(
        f.create_breach_event_payload(**overrides), ADMIN))


def ingest_breach(breach_event_id, matched_identifier_values) -> dict:
    return get_success_data(api.ingest_breach_event(breach_event_id,
                                                    matched_identifier_values, ADMIN))


def alerts_for_event(breach_event_id, headers=None):
    data, meta = _paginate(api.list_breach_alerts(headers or ADMIN,
                                                  params={"breach_event_id": breach_event_id}))
    return data, meta


def read_alert(alert_id, headers=None) -> dict:
    return get_success_data(api.get_breach_alert(alert_id, headers or ADMIN))


def add_credential_finding(profile_id, finding_type="BREACHED_PASSWORD",
                           detail="mail vault") -> dict:
    return get_success_data(api.create_credential_finding(
        f.create_credential_finding_payload(profile_id, finding_type, detail=detail),
        AGENT))


def read_hygiene(profile_id, headers=None) -> dict:
    return get_success_data(api.get_hygiene_score(profile_id, headers or ADMIN))


# --------------------------------------------------------------------------
# Tier 7 — ledger and statement reads
# --------------------------------------------------------------------------

def ledger_entries(account_id, headers=None, **params):
    """Return (rows, meta) for the account's ledger under the given filters."""
    query = {"account_id": account_id}
    query.update(params)
    return _paginate(api.list_ledger_entries(headers or ADMIN, params=query))


def entitlement_statement(household, headers=None) -> dict:
    return get_success_data(api.get_entitlement_statement(
        household["account_id"], headers or ADMIN))


# --------------------------------------------------------------------------
# Tier 8 — full scenarios shared by several difficulty translations
# --------------------------------------------------------------------------

def setup_household_with_exposure(broker_overrides=None, plan=None,
                                  exposure_kind="PEOPLE_SEARCH", **plan_overrides):
    """The workhorse: household → active profile → active broker → one FOUND
    exposure discovered by a COMPLETED initial scan.

    Returns a dict with household, profile, broker, scan and exposure.
    """
    household = open_household(plan=plan, **plan_overrides)
    broker = create_broker(**(broker_overrides or {}))
    profile = setup_active_profile(household)
    scan, exposures = run_scan(profile["id"], [broker["id"]],
                               kind="INITIAL", complete=True,
                               exposure_kind=exposure_kind)
    return {
        "household": household,
        "profile": profile,
        "broker": broker,
        "scan": scan,
        "exposure": exposures[0],
    }


def setup_household_with_two_exposures(broker_a=None, broker_b=None, **plan_overrides):
    """Household → active profile → two brokers → one FOUND exposure at each,
    both discovered by the same COMPLETED initial scan."""
    household = open_household(**plan_overrides)
    first = create_broker(**(broker_a or {"name": "BrokerOne"}))
    second = create_broker(**(broker_b or {"name": "BrokerTwo"}))
    profile = setup_active_profile(household)
    scan, exposures = run_scan(profile["id"], [first["id"], second["id"]],
                               kind="INITIAL", complete=True)
    return {
        "household": household,
        "profile": profile,
        "broker_a": first,
        "broker_b": second,
        "scan": scan,
        "exposure_a": exposures[0],
        "exposure_b": exposures[1],
    }


def setup_suppressed_exposure(broker_overrides=None, **plan_overrides):
    """As setup_household_with_exposure, then drive the exposure to SUPPRESSED
    through a completed removal request at the startup clock instant."""
    world = setup_household_with_exposure(broker_overrides=broker_overrides,
                                          **plan_overrides)
    world["first_request"] = suppress_exposure(world["exposure"]["id"])
    world["exposure"] = read_exposure(world["exposure"]["id"])
    return world


def setup_verifying_broker_world(expires_at="2026-05-10T00:00:00Z"):
    """A broker that demands identity evidence, one FOUND exposure at it, and a
    DRAFTED removal request — the state the identity gate is probed from.

    The document is not created here; each test decides whether one exists.
    """
    world = setup_household_with_exposure(
        broker_overrides={"name": "EuroRecords", "opt_out_method": "EMAIL",
                          "jurisdiction": "EU", "response_window_days": 20,
                          "requires_identity_verification": True},
        exposure_kind="CREDIT_HEADER",
    )
    world["request"] = draft_removal(world["exposure"]["id"])
    world["document_expires_at"] = expires_at
    return world


def upload_and_verify_document(household, expires_at, document_type="PASSPORT",
                               document_reference="PASS-99812") -> dict:
    document = get_success_data(api.create_identity_document(
        household["owner_id"],
        f.create_identity_document_payload(document_type=document_type,
                                           document_reference=document_reference,
                                           expires_at=expires_at),
        household["owner"]))
    return get_success_data(api.verify_identity_document(document["id"], AGENT))

