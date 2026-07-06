"""Cascade behavior: project-cancel unwind (invoice void -> milestone revert),
and DELIVERY->HANDOFF forward cascade billing licenses."""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    make_client_headers,
    create_project_in_delivery,
    create_license_payload,
    issue_invoice,
)

SO = TEST_USERS["studio_ops_headers"]
DES = TEST_USERS["designer_headers"]
BO = TEST_USERS["billing_ops_headers"]


def test_handoff_advance_bills_reserved_license(api):
    """PRD §3.5: "When the advance into HANDOFF succeeds it also runs a forward
    cascade over the project's licenses: every license currently in RESERVED or
    CLEARED transitions to BILLED, as described in §3.7."

    Design: Difficulty/transitive_cascade/deliver_to_handoff_cascade_license_reserved_to_billed_depth2
    """
    studio, client, project, milestones = create_project_in_delivery(
        [40000], deposit_pct=0.30, tax_rate=0.0, deposit_cents=12000
    )
    sid, pid, cid = studio["id"], project["id"], client["id"]
    lic = validate_success(api.create_license(
        sid, create_license_payload(pid, "2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z", kind="STOCK", cost_cents=5000), SO
    ), expected_status=201)
    deliverable = get_success_data(
        api.create_deliverable(sid, pid, {"asset_type": "BRAND_GUIDE", "is_required_for_handoff": True}, DES)
    )
    get_success_data(api.deliver_deliverable(sid, pid, deliverable["id"], DES))
    get_success_data(api.accept_deliverable(sid, pid, deliverable["id"], make_client_headers(cid)))

    handed = validate_success(api.advance_project(sid, pid, SO))
    assert handed["status"] == "HANDOFF"
    lic_after = validate_success(api.get_license(sid, lic["id"], SO))
    assert lic_after["status"] == "BILLED", "RESERVED license billed by the handoff cascade"


def test_handoff_advance_reaches_handoff_state(api):
    """PRD §3.5: "A `StudioOps` operator advances the project from `DELIVERY` to `HANDOFF` only when two conditions both hold."

    Design: Difficulty/transitive_cascade/deliver_to_handoff_cascade_license_reserved_to_billed_depth2
    """
    studio, client, project, milestones = create_project_in_delivery(
        [40000], deposit_pct=0.30, tax_rate=0.0, deposit_cents=12000
    )
    sid, pid, cid = studio["id"], project["id"], client["id"]
    deliverable = get_success_data(
        api.create_deliverable(sid, pid, {"asset_type": "BRAND_GUIDE", "is_required_for_handoff": True}, DES)
    )
    get_success_data(api.deliver_deliverable(sid, pid, deliverable["id"], DES))
    get_success_data(api.accept_deliverable(sid, pid, deliverable["id"], make_client_headers(cid)))
    handed = validate_success(api.advance_project(sid, pid, SO))
    assert handed["status"] == "HANDOFF"
