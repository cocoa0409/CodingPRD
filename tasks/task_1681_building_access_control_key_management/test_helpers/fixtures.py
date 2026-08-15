"""Composite setup helpers.

Every helper builds preconditions from scratch against a fresh database using
only PRD-declared endpoints. Setup calls use the lenient get_success_data()
validator so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import ALL_DAYS
from .factories import (
    create_building_payload,
    create_key_node_payload,
    create_door_payload,
    create_person_payload,
    create_credential_payload,
    create_access_group_payload,
    create_work_order_payload,
    create_rekey_campaign_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["security_admin_headers"]
OFFICER = TEST_USERS["security_officer_headers"]
DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------

def create_building(name="Test Building", **config) -> dict:
    resp = api_client.create_building(create_building_payload(name=name, **config), ADMIN)
    return get_success_data(resp)


def set_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    get_success_data(resp)


def create_key_node(building_id, level, label, **overrides) -> dict:
    resp = api_client.create_key_node(
        create_key_node_payload(building_id, level, label, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_master_change_chain(building_id, master_label="M", change_label="C1"):
    """MASTER root -> CHANGE child. Returns (master, change)."""
    master = create_key_node(building_id, "MASTER", master_label)
    change = create_key_node(building_id, "CHANGE", change_label, parent_id=master["id"])
    return master, change


def create_door(building_id, key_node_id, door_code="D-1", **overrides) -> dict:
    resp = api_client.create_door(
        create_door_payload(building_id, key_node_id, door_code, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_person(building_id, full_name, kind, **overrides) -> dict:
    resp = api_client.create_person(
        create_person_payload(building_id, full_name, kind, **overrides), DESK
    )
    return get_success_data(resp)


def create_credential(building_id, key_node_id, serial_no, type="FOB", **overrides) -> dict:
    resp = api_client.create_credential(
        create_credential_payload(building_id, key_node_id, serial_no, type, **overrides),
        DESK,
    )
    return get_success_data(resp)


def issue_credential(credential_id, person_id, expires_at=None) -> dict:
    payload = {"person_id": person_id}
    if expires_at is not None:
        payload["expires_at"] = expires_at
    resp = api_client.issue_credential(credential_id, payload, DESK)
    return get_success_data(resp)


def create_access_group(building_id, name, door_ids=None, person_ids=None,
                        days_of_week=None, window_start_utc="00:00",
                        window_end_utc="23:59") -> dict:
    payload = create_access_group_payload(
        building_id,
        name,
        door_ids=door_ids or [],
        person_ids=person_ids or [],
        days_of_week=days_of_week or list(ALL_DAYS),
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
    )
    resp = api_client.create_access_group(payload, ADMIN)
    return get_success_data(resp)


def access_check(door_id, credential_id, mode="RECORDED", headers=None) -> dict:
    resp = api_client.access_check(
        door_id, {"credential_id": credential_id, "mode": mode}, headers or OFFICER
    )
    return get_success_data(resp)


def run_ops(building_id) -> dict:
    resp = api_client.run_ops(building_id, OFFICER)
    return get_success_data(resp)


def get_incident_for_credential(credential_id) -> dict:
    resp = api_client.list_incidents(OFFICER, params={"credential_id": credential_id})
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly one incident for credential {credential_id}"
    )
    return data[0]


def get_propped_incident_for_door(door_id) -> dict:
    resp = api_client.list_incidents(
        OFFICER, params={"door_id": door_id, "type": "PROPPED_DOOR"}
    )
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly one PROPPED_DOOR incident for door {door_id}"
    )
    return data[0]


def get_alert_for_door(door_id) -> dict:
    resp = api_client.list_propped_alerts(OFFICER, params={"door_id": door_id})
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) >= 1, (
        f"Setup failed: expected a propped alert for door {door_id}"
    )
    return data[0]


def list_charges(**filters) -> list:
    resp = api_client.list_charges(DESK, params=filters)
    data = get_success_data(resp)
    assert isinstance(data, list), "Setup failed: charge list did not return an array"
    return data


def list_work_orders(**filters) -> list:
    resp = api_client.list_work_orders(OFFICER, params=filters)
    data = get_success_data(resp)
    assert isinstance(data, list), "Setup failed: work-order list did not return an array"
    return data


def get_credential(credential_id) -> dict:
    return get_success_data(api_client.get_credential(credential_id, DESK))


def get_door(door_id) -> dict:
    return get_success_data(api_client.get_door(door_id, OFFICER))


def get_key_node(key_node_id) -> dict:
    return get_success_data(api_client.get_key_node(key_node_id, ADMIN))


def get_campaign(campaign_id) -> dict:
    return get_success_data(api_client.get_rekey_campaign(campaign_id, ADMIN))


def get_incident(incident_id) -> dict:
    return get_success_data(api_client.get_incident(incident_id, OFFICER))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — building + MASTER->CHANGE chain (+ optional door)
# ---------------------------------------------------------------------------

def setup_building_with_chain(building_name="Test House", with_door=False,
                              door_code="D-1", **building_config) -> dict:
    """Building + MASTER root + CHANGE child (+ optionally one door on the CHANGE node)."""
    building = create_building(building_name, **building_config)
    master, change = create_master_change_chain(building["id"])
    ctx = {"building": building, "master": master, "change": change}
    if with_door:
        ctx["door"] = create_door(building["id"], change["id"], door_code)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: access-ready door — door + holder + issued credential + 24/7 group
# ---------------------------------------------------------------------------

def setup_access_ready_door(building_name="Access House", person_kind="STAFF",
                            person_name="Staff One", credential_serial="K-1",
                            credential_type="FOB", clock="2026-08-01T08:00:00Z",
                            group_start="00:00", group_end="23:59",
                            **building_config) -> dict:
    """Building + M->C1 + door + ACTIVE person + ISSUED credential + access group
    covering the door/person all week over [group_start, group_end)."""
    ctx = setup_building_with_chain(building_name, with_door=True, **building_config)
    set_clock(clock)
    person = create_person(ctx["building"]["id"], person_name, person_kind,
                           **({"unit_label": "U-1"} if person_kind == "RESIDENT" else {}))
    cred = create_credential(ctx["building"]["id"], ctx["change"]["id"],
                             credential_serial, credential_type)
    if person_kind == "VENDOR":
        issue_credential(cred["id"], person["id"], expires_at="2026-08-01T23:00:00Z")
    else:
        issue_credential(cred["id"], person["id"])
    group = create_access_group(
        ctx["building"]["id"], "All", door_ids=[ctx["door"]["id"]],
        person_ids=[person["id"]], window_start_utc=group_start, window_end_utc=group_end,
    )
    ctx.update({"person": person, "credential": cred, "group": group})
    return ctx


def setup_propped_door_open(building_name="Propped House", threshold=120,
                            open_at="2026-08-01T08:00:00Z", **building_config) -> dict:
    """Access-ready door whose RECORDED grant at `open_at` set open_since."""
    config = {"default_propped_threshold_seconds": threshold}
    config.update(building_config)
    ctx = setup_access_ready_door(building_name, clock=open_at, **config)
    result = access_check(ctx["door"]["id"], ctx["credential"]["id"], mode="RECORDED")
    assert result["outcome"] == "GRANTED", "Setup failed: opening access check not GRANTED"
    ctx["open_event_id"] = result["access_event_id"]
    return ctx


def setup_open_propped_alert(building_name="Alert House", threshold=120,
                             open_at="2026-08-01T08:00:00Z",
                             detect_at="2026-08-01T08:03:00Z", **building_config) -> dict:
    """Propped door + run-ops at detect_at (duration > threshold) -> one OPEN alert."""
    ctx = setup_propped_door_open(building_name, threshold=threshold, open_at=open_at,
                                  **building_config)
    set_clock(detect_at)
    summary = run_ops(ctx["building"]["id"])
    assert summary["propped_alerts_created"] == 1, (
        "Setup failed: run-ops did not create the expected propped alert"
    )
    ctx["alert"] = get_alert_for_door(ctx["door"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: lost-credential incident
# ---------------------------------------------------------------------------

def setup_lost_credential_incident(building_name="Incident House", with_door=True,
                                   holder_kind="STAFF", holder_name="Staff One",
                                   credential_serial="K-1", credential_type="FOB",
                                   on_master_node=False,
                                   clock="2026-08-01T09:00:00Z",
                                   **building_config) -> dict:
    """Building + M->C1 (+ door) + holder + issued credential; credential reported
    lost -> LOST_CREDENTIAL incident. Returns ctx with 'incident'."""
    ctx = setup_building_with_chain(building_name, with_door=with_door, **building_config)
    set_clock(clock)
    person = create_person(ctx["building"]["id"], holder_name, holder_kind,
                           **({"unit_label": "U-1"} if holder_kind == "RESIDENT" else {}))
    node = ctx["master"] if on_master_node else ctx["change"]
    cred = create_credential(ctx["building"]["id"], node["id"], credential_serial,
                             credential_type)
    issue_credential(cred["id"], person["id"])
    resp = api_client.report_lost_credential(cred["id"], DESK)
    get_success_data(resp)
    incident = get_incident_for_credential(cred["id"])
    ctx.update({"person": person, "credential": cred, "incident": incident})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: move-out settlement
# ---------------------------------------------------------------------------

def setup_moved_out_settlement(building_name="Settlement House", deposit_cents=0,
                               credential_specs=(("F-1", "FOB"),),
                               clock="2026-08-01T09:00:00Z", **building_config) -> dict:
    """Resident holding the given credentials is moved out; returns ctx with the
    DRAFT settlement charge in ctx['charge'] and credentials in ctx['credentials']."""
    ctx = setup_building_with_chain(building_name, **building_config)
    set_clock(clock)
    person = create_person(ctx["building"]["id"], "Res One", "RESIDENT",
                           unit_label="U-1", key_deposit_cents=deposit_cents)
    creds = []
    for serial, ctype in credential_specs:
        cred = create_credential(ctx["building"]["id"], ctx["change"]["id"], serial, ctype)
        issue_credential(cred["id"], person["id"])
        creds.append(cred)
    resp = api_client.move_out_person(person["id"], DESK)
    get_success_data(resp)
    charges = list_charges(person_id=person["id"], kind="MOVE_OUT_SETTLEMENT")
    assert len(charges) == 1, "Setup failed: settlement charge not created at move-out"
    ctx.update({"person": person, "credentials": creds, "charge": charges[0]})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4/5: approved rekey campaign over the CHANGE node of a M->C1 chain
# ---------------------------------------------------------------------------

def setup_approved_campaign(building_name="Rekey House", with_issued_credential=True,
                            clock="2026-08-01T10:00:00Z", **building_config) -> dict:
    """Building + M->C1 + door D-1 + resident holding FOB FB-1 on C1; proactive
    campaign on C1 approved; its single REKEY work order started.
    Returns ctx with 'campaign' and 'work_orders'."""
    ctx = setup_building_with_chain(building_name, with_door=True, **building_config)
    set_clock(clock)
    person = create_person(ctx["building"]["id"], "Res One", "RESIDENT", unit_label="U-1")
    cred = create_credential(ctx["building"]["id"], ctx["change"]["id"], "FB-1", "FOB")
    if with_issued_credential:
        issue_credential(cred["id"], person["id"])
    resp = api_client.create_rekey_campaign(
        create_rekey_campaign_payload(ctx["building"]["id"], ctx["change"]["id"]), ADMIN
    )
    campaign = get_success_data(resp)
    resp = api_client.approve_rekey_campaign(campaign["id"], ADMIN)
    get_success_data(resp)
    work_orders = list_work_orders(campaign_id=campaign["id"])
    assert work_orders, "Setup failed: no REKEY work orders minted at approval"
    ctx.update({"person": person, "credential": cred, "campaign": campaign,
                "work_orders": work_orders})
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: the two-branch tower scenario shared by the campaign cost tests.
# GM -> M1 -> {C1, C2}; doors D-1A/D-1B on C1, D-2A on C2; staff S1 holds master
# key MK-1 (M1) reported lost; resident R1 holds fob FB-1 (C1); campaign on M1
# billed to S1 approved.
# ---------------------------------------------------------------------------

def setup_tower_campaign_approved(building_config=None) -> dict:
    config = {
        "vendor_badge_pool_max": 2,
        "alert_escalation_minutes": 30,
        "audit_retention_days": 30,
        "default_propped_threshold_seconds": 120,
        "base_fee_cents": 15000,
        "per_door_fee_cents": 7500,
        "per_key_reissue_fee_cents": 2500,
        "emergency_surcharge_pct": 20,
        "business_open_utc": "08:00",
        "business_close_utc": "18:00",
    }
    if building_config:
        config.update(building_config)
    building = create_building("Tower", **config)
    set_clock("2026-08-01T09:00:00Z")
    gm = create_key_node(building["id"], "GRAND_MASTER", "GM")
    m1 = create_key_node(building["id"], "MASTER", "M1", parent_id=gm["id"])
    c1 = create_key_node(building["id"], "CHANGE", "C1", parent_id=m1["id"])
    c2 = create_key_node(building["id"], "CHANGE", "C2", parent_id=m1["id"])
    d1 = create_door(building["id"], c1["id"], "D-1A")
    create_door(building["id"], c1["id"], "D-1B")
    create_door(building["id"], c2["id"], "D-2A")
    s1 = create_person(building["id"], "Staff One", "STAFF")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    mk1 = create_credential(building["id"], m1["id"], "MK-1", "METAL_KEY")
    f1 = create_credential(building["id"], c1["id"], "FB-1", "FOB")
    issue_credential(mk1["id"], s1["id"])
    issue_credential(f1["id"], r1["id"])
    resp = api_client.report_lost_credential(mk1["id"], DESK)
    get_success_data(resp)
    incident = get_incident_for_credential(mk1["id"])
    resp = api_client.create_rekey_campaign(
        create_rekey_campaign_payload(
            building["id"], m1["id"], incident_id=incident["id"],
            bill_to="PERSON", bill_person_id=s1["id"],
        ),
        ADMIN,
    )
    campaign = get_success_data(resp)
    resp = api_client.start_incident_review(incident["id"], OFFICER)
    get_success_data(resp)
    resp = api_client.approve_rekey_campaign(campaign["id"], ADMIN)
    get_success_data(resp)
    work_orders = list_work_orders(campaign_id=campaign["id"])
    assert len(work_orders) == 3, (
        f"Setup failed: expected 3 REKEY work orders, got {len(work_orders)}"
    )
    return {
        "building": building, "gm": gm, "m1": m1, "c1": c1, "c2": c2, "d1": d1,
        "s1": s1, "r1": r1, "mk1": mk1, "f1": f1, "incident": incident,
        "campaign": campaign, "work_orders": work_orders,
    }
