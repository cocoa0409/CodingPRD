"""Optimistic concurrency control on the shared project budget ledger.

Covers queue B: cross_cutting_complexity_layers OCC instances (happy-path version
increment on place, stale-version place, stale-version deposit).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_client_headers,
    create_vendor_payload,
    create_payment_payload,
    setup_project_with_approved_room,
    create_specified_selection,
    create_draft_order_with_lines,
    create_ffe_item,
    create_client,
    create_project,
    create_vendor,
    project_version,
)

ADMIN = TEST_USERS["studio_admin_headers"]
DESIGNER = TEST_USERS["designer_headers"]
PC = TEST_USERS["procurement_coordinator_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — cross_cutting / occ_version_increments_on_place
# ─────────────────────────────────────────────────────────────────────────────
def test_place_with_correct_version_increments_project_version(api):
    """PRD §2.10: "The server compares that value against the project's current
    version; if they differ ... the write is rejected"
    PRD §3.5: "the project's committed_cents is recomputed, and from it the project's
    budget_status and posture are re-derived; and the project's version increments."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_place
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="OC-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    order = create_draft_order_with_lines(pid, vid, [sel["id"]])
    pv = project_version(pid)
    placed = validate_success(api.place_order(order["id"], {"expected_project_version": pv}, PC), 200)
    assert placed["status"] == "ORDERED", placed["status"]
    project_after = validate_success(api.get_project(pid, ADMIN), 200)
    assert project_after["version"] == pv + 1, (
        f"version after place should be {pv + 1}, got {project_after['version']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — cross_cutting / occ_stale_version_on_place_rejected_412
# ─────────────────────────────────────────────────────────────────────────────
def test_place_with_stale_version_rejected_412(api):
    """PRD §2.10: "if they differ — because some other writer has advanced the project
    since the client's last read — the write is rejected with ERR_STALE_VERSION and
    HTTP status 412, and no change is made."
    PRD §3.5: "two placements cannot both succeed against the same observed version —
    the second will find its expected_project_version stale."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_place_rejected_412
    """
    s = setup_project_with_approved_room()
    pid, rid = s["project"]["id"], s["room"]["id"]
    v1 = s["vendor"]
    v2 = create_vendor(name="V2", trade="MILLWORK")
    f1 = create_ffe_item(sku="ST-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    f2 = create_ffe_item(sku="ST-B", name="Table", category="FURNITURE", list_unit_cost_cents=30000, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=1, spec_note="b")
    o1 = create_draft_order_with_lines(pid, v1["id"], [s1["id"]])
    o2 = create_draft_order_with_lines(pid, v2["id"], [s2["id"]],
                                       window_start="2026-08-01T00:00:00Z",
                                       window_end="2026-08-02T00:00:00Z")
    stale_pv = project_version(pid)
    # First place advances the project version.
    validate_success(api.place_order(o1["id"], {"expected_project_version": stale_pv}, PC), 200)
    # Second place carries the now-stale version observed before the first place.
    res = api.place_order(o2["id"], {"expected_project_version": stale_pv}, PC)
    validate_error(res, "ERR_STALE_VERSION")
    after = validate_success(api.get_order(o2["id"], ADMIN), 200)
    assert after["status"] == "DRAFT", after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — cross_cutting / deposit_record_stale_version_rejected_412
# ─────────────────────────────────────────────────────────────────────────────
def test_record_deposit_with_stale_version_rejected_412(api):
    """PRD §2.10: "The second is recording a client deposit. A deposit triggers the
    deposit waterfall ... so the resulting allocation would be wrong, and the
    stale-version deposit is rejected with ERR_STALE_VERSION (HTTP 412)."
    PRD §3.10: "the request must carry expected_project_version matching the project's
    current version, and a mismatch is rejected with ERR_STALE_VERSION (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/deposit_record_stale_version_rejected_412
    """
    client = create_client()
    project = create_project(client["id"], budget_cents=100000000)
    pid = project["id"]
    stale_pv = project_version(pid)
    # First deposit advances the project version.
    validate_success(api.create_payment(
        pid, create_payment_payload(10000, stale_pv, received_at="2026-07-01T00:00:00Z"), ADMIN), 201)
    # Second deposit carries the stale (pre-first-deposit) version.
    res = api.create_payment(
        pid, create_payment_payload(5000, stale_pv, received_at="2026-07-02T00:00:00Z"), ADMIN)
    validate_error(res, "ERR_STALE_VERSION")
