"""Composite setup helpers for multi-step test prerequisites.

The server is restarted before every test, so each helper builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
the lenient get_success_data() so failures surface as clear setup errors.

The logical clock reads exactly 2026-05-01T00:00:00Z at server startup
(PRD §2.5); helpers only move the clock when a scenario needs a later date.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_garment_item_payload,
    create_member_payload,
    create_part_item_payload,
    create_policy_payload,
    create_prescription_payload,
    create_pump_item_payload,
    create_pump_order_payload,
    create_resupply_order_payload,
    create_shipment_payload,
)
from .test_users import TEST_USERS, make_insurance_specialist_headers

CC = TEST_USERS["care_coordinator_headers"]
IS = TEST_USERS["insurance_specialist_headers"]
WH = TEST_USERS["warehouse_operator_headers"]
PA = TEST_USERS["platform_admin_headers"]


# ─── Tier 0: atomic creation helpers ────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical clock (PlatformAdmin-only, PRD §2.5)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, PA)
    )


def create_member(**overrides):
    return get_success_data(api_client.create_member(create_member_payload(**overrides), CC))


def create_policy(member_id, **overrides):
    return get_success_data(
        api_client.create_policy(create_policy_payload(member_id, **overrides), PA)
    )


def create_prescription(member_id, **overrides):
    return get_success_data(
        api_client.create_prescription(create_prescription_payload(member_id, **overrides), CC)
    )


def create_verified_prescription(member_id, **overrides):
    rx = create_prescription(member_id, **overrides)
    return get_success_data(api_client.verify_prescription(rx["id"], IS))


def create_pump_item(**overrides):
    return get_success_data(api_client.create_catalog_item(create_pump_item_payload(**overrides), PA))


def create_part_item(**overrides):
    return get_success_data(api_client.create_catalog_item(create_part_item_payload(**overrides), PA))


def create_garment_item(**overrides):
    return get_success_data(
        api_client.create_catalog_item(create_garment_item_payload(**overrides), PA)
    )


def create_order(member_id, policy_id, prescription_id, pump_item_id, headers=None, **overrides):
    return get_success_data(
        api_client.create_pump_order(
            create_pump_order_payload(
                member_id, policy_id, prescription_id, pump_item_id, **overrides
            ),
            headers or CC,
        )
    )


# ─── Tier 1/2: order progression fixtures ───────────────────────────────────

def setup_pending_order(policy_overrides=None, pump_overrides=None, rx_overrides=None,
                        member_overrides=None):
    """Member + ACTIVE policy + prescription (unverified) + pump + order in
    PENDING_QUALIFICATION. Returns dict of all created entities."""
    member = create_member(**(member_overrides or {}))
    policy = create_policy(member["id"], **(policy_overrides or {}))
    pump = create_pump_item(**(pump_overrides or {}))
    rx = create_prescription(member["id"], **(rx_overrides or {}))
    order = create_order(member["id"], policy["id"], rx["id"], pump["id"])
    return {"member": member, "policy": policy, "rx": rx, "pump": pump, "order": order}


def setup_pending_order_verified(policy_overrides=None, pump_overrides=None,
                                 rx_overrides=None, member_overrides=None):
    """Same as setup_pending_order but the prescription is VERIFIED."""
    ctx = setup_pending_order(policy_overrides, pump_overrides, rx_overrides, member_overrides)
    ctx["rx"] = get_success_data(api_client.verify_prescription(ctx["rx"]["id"], IS))
    return ctx


def setup_qualified_order(policy_overrides=None, pump_overrides=None, rx_overrides=None,
                          member_overrides=None, garment_lines=None):
    """Order qualified: VERIFIED prescription, qualify run, order QUALIFIED.

    garment_lines: optional list of (catalog_item_id, quantity) added before qualify.
    """
    ctx = setup_pending_order_verified(policy_overrides, pump_overrides, rx_overrides,
                                       member_overrides)
    for item_id, qty in (garment_lines or []):
        get_success_data(
            api_client.add_order_line(
                ctx["order"]["id"], {"catalog_item_id": item_id, "quantity": qty}, CC
            )
        )
    ctx["order"] = get_success_data(api_client.qualify_pump_order(ctx["order"]["id"], IS))
    return ctx


def setup_delivered_order(policy_overrides=None, pump_overrides=None, rx_overrides=None,
                          member_overrides=None, garment_lines=None, part_items=None):
    """Order driven to DELIVERED via a full shipment advance chain at the
    startup clock (2026-05-01). Adds 'shipment' to the returned context.

    part_items: optional list of kwargs dicts for covered PART catalog items to
    create BEFORE delivery so resupply schedules are minted by the cascade.
    """
    parts = [create_part_item(**kw) for kw in (part_items or [])]
    ctx = setup_qualified_order(policy_overrides, pump_overrides, rx_overrides,
                                member_overrides, garment_lines)
    shipment = get_success_data(
        api_client.create_shipment(
            create_shipment_payload(pump_order_id=ctx["order"]["id"]), WH
        )
    )
    for target in ("IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"):
        shipment = get_success_data(
            api_client.advance_shipment(shipment["id"], {"to_status": target}, WH)
        )
    ctx["shipment"] = shipment
    ctx["order"] = get_success_data(api_client.get_pump_order(ctx["order"]["id"], CC))
    ctx["parts"] = parts
    return ctx


def get_schedule_id(member_id, catalog_item_id):
    """Look up the auto-created resupply schedule for (member, part)."""
    data, _meta = validate_paginated(
        api_client.list_resupply_schedules(
            CC, params={"member_id": member_id, "catalog_item_id": catalog_item_id}
        )
    )
    assert len(data) == 1, f"expected exactly one schedule, got {len(data)}"
    return data[0]["id"]


def get_schedule(member_id, catalog_item_id):
    """Look up the full schedule row for (member, part)."""
    data, _meta = validate_paginated(
        api_client.list_resupply_schedules(
            CC, params={"member_id": member_id, "catalog_item_id": catalog_item_id}
        )
    )
    assert len(data) == 1, f"expected exactly one schedule, got {len(data)}"
    return data[0]


def setup_delivered_with_schedule(policy_overrides=None, part_overrides=None, **kwargs):
    """Delivered order whose catalog has one covered PART; adds 'schedule' and
    'part' to the context. Delivery happens at the startup clock 2026-05-01."""
    base_policy = {"resupply_frequency_days": 90}
    base_policy.update(policy_overrides or {})
    part_kw = {"covered_under_resupply": True, "max_qty_per_frequency": 4}
    part_kw.update(part_overrides or {})
    ctx = setup_delivered_order(policy_overrides=base_policy, part_items=[part_kw], **kwargs)
    ctx["part"] = ctx["parts"][0]
    ctx["schedule"] = get_schedule(ctx["member"]["id"], ctx["part"]["id"])
    return ctx


# ─── Tier 3: prior authorization fixtures ───────────────────────────────────

def setup_qualified_with_pa(policy_overrides=None, **kwargs):
    """Order QUALIFIED on a requires_prior_auth policy, PA created (SUBMITTED)."""
    base_policy = {"requires_prior_auth": True}
    base_policy.update(policy_overrides or {})
    ctx = setup_qualified_order(policy_overrides=base_policy, **kwargs)
    ctx["pa"] = get_success_data(
        api_client.create_prior_authorization({"pump_order_id": ctx["order"]["id"]}, IS)
    )
    return ctx


def approve_pa(pa_id, auth_number="AUTH-1", approved_until="2026-12-31"):
    """Payer decision APPROVED on a PA."""
    return get_success_data(
        api_client.payer_decision(
            pa_id,
            {"decision": "APPROVED", "auth_number": auth_number,
             "approved_until": approved_until},
            PA,
        )
    )


# ─── Tier 4: claims / billing fixtures ──────────────────────────────────────

def setup_delivered_with_claim(submitter_user_id="ins-1", **kwargs):
    """Delivered order + one SUBMITTED claim filed by the given specialist id."""
    ctx = setup_delivered_order(**kwargs)
    ctx["claim"] = get_success_data(
        api_client.create_claim(
            {"pump_order_id": ctx["order"]["id"]},
            make_insurance_specialist_headers(submitter_user_id),
        )
    )
    return ctx
