from flask import Blueprint

import calc
import core
import gates
import ops
import serialize
from core import fail, get, new_row, now, parse_iso, touch
from gates import check_state

bp = Blueprint("keys", __name__)

KEY_READ_ROLES = ["Dispatcher", "PlatformAdmin", "FieldTech", "Auditor", "Owner"]
ISSUANCE_READ_ROLES = ["Dispatcher", "PlatformAdmin", "Vendor", "Auditor", "FieldTech"]


@bp.post("/property-care/properties/<pid>/key-assets")
def create_key_asset(pid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    prop = gates.fetch_path("properties", pid)
    body = gates.body_json()
    gates.validate_payload(body, [
        ("key_type", "string", True),
        ("label", "string", True),
        ("copies_total", "integer", True),
        ("current_code", "string", False),
    ])
    key_type = body["key_type"]
    key = new_row(
        "key_assets",
        property_id=prop["id"],
        key_type=key_type,
        label=body["label"],
        copies_total=body["copies_total"],
        copies_on_hand=body["copies_total"],
        copies_issued_outstanding=0,
        copies_lost=0,
        current_code=(body.get("current_code") if key_type == "LOCKBOX" else None),
        code_rotation_count=0,
        active_grant_count=0,
        rekey_pending_flag=False,
    )
    return core.ok(serialize.key_asset(key), 201)


@bp.get("/property-care/key-assets")
def list_key_assets():
    gates.begin(KEY_READ_ROLES)
    return gates.list_response("key_assets", ["property_id", "key_type"], serialize.key_asset)


@bp.get("/property-care/key-assets/<kid>")
def read_key_asset(kid):
    role, user_id = gates.begin(KEY_READ_ROLES)
    key = gates.fetch_path("key_assets", kid)
    prop = get("properties", key["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    return core.ok(serialize.key_asset(key))


@bp.post("/property-care/key-assets/<kid>/rotate-code")
def rotate_code(kid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    key = gates.fetch_path("key_assets", kid)
    body = gates.body_json()
    expected = body.get("expected_key_asset_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != key["version"]:
            fail("ERR_STALE_KEY_ASSET_VERSION", "The key asset has been modified.")
    gates.validate_payload(body, [
        ("new_code", "string", True),
        ("expected_key_asset_version", "integer", True),
    ])
    key["code_rotation_count"] += 1
    key["current_code"] = body["new_code"]
    ops.invalidate_stale_grants(key)
    touch(key)
    return core.ok(serialize.key_asset(key))


@bp.post("/property-care/key-assets/<kid>/issuances")
def create_issuance(kid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    key = gates.fetch_path("key_assets", kid)
    body = gates.body_json()
    # ---- G3 rung 12 then rung 14 ----
    vendor = None
    if isinstance(body.get("vendor_id"), str):
        vendor = gates.fetch_body_fk("vendors", body["vendor_id"], "ERR_VENDOR_NOT_FOUND")
    if isinstance(body.get("vendor_assignment_id"), str):
        if get("vendor_assignments", body["vendor_assignment_id"]) is None:
            fail("ERR_LINKED_RESOURCE_NOT_FOUND", "The vendor assignment does not exist.")
    # ---- G8b key custody ----
    if vendor is not None:
        for issuance in calc.children("key_issuances", "vendor_id", vendor["id"]):
            if issuance["status"] in ("OVERDUE", "LOST"):
                fail("ERR_VENDOR_KEY_OVERDUE", "The vendor holds an overdue or lost key.")
    if key["rekey_pending_flag"]:
        fail("ERR_KEY_REKEY_PENDING", "A rekey is pending on this key asset.")
    requested = body.get("copies_issued", 1)
    if isinstance(requested, int) and not isinstance(requested, bool):
        if calc.key_copies_on_hand(key) < requested:
            fail("ERR_KEY_COPIES_UNAVAILABLE", "Not enough copies are on hand.")
    # ---- G10 ----
    gates.validate_payload(body, [
        ("vendor_id", "string", True),
        ("vendor_assignment_id", "string", False),
        ("copies_issued", "integer", False),
    ])
    issuance = ops.create_key_issuance(key, body["vendor_id"], body.get("vendor_assignment_id"),
                                       body.get("copies_issued", 1))
    return core.ok(serialize.key_issuance(issuance), 201)


@bp.get("/property-care/key-issuances")
def list_issuances():
    gates.begin(ISSUANCE_READ_ROLES)
    return gates.list_response("key_issuances",
                               ["key_asset_id", "vendor_id", "vendor_assignment_id", "status"],
                               serialize.key_issuance)


@bp.get("/property-care/key-issuances/<iid>")
def read_issuance(iid):
    gates.begin(ISSUANCE_READ_ROLES)
    issuance = gates.fetch_path("key_issuances", iid)
    return core.ok(serialize.key_issuance(issuance))


@bp.post("/property-care/key-issuances/<iid>/return")
def return_key(iid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    issuance = gates.fetch_path("key_issuances", iid)
    check_state("key_issuance", issuance, ["ISSUED", "OVERDUE"])
    if issuance["status"] == "ISSUED":
        if now() > issuance["return_deadline_at"]:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The return deadline has passed; the issuance must be marked overdue first.")
        issuance["status"] = "RETURNED"
    else:
        issuance["status"] = "RETURNED_LATE"
    issuance["returned_at"] = now()
    touch(issuance)
    return core.ok(serialize.key_issuance(issuance))


@bp.post("/property-care/key-issuances/<iid>/mark-overdue")
def mark_overdue(iid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    issuance = gates.fetch_path("key_issuances", iid)
    check_state("key_issuance", issuance, ["ISSUED"])
    from datetime import timedelta
    if not now() > issuance["return_deadline_at"] + timedelta(hours=core.KEY_OVERDUE_GRACE_HOURS):
        fail("ERR_ISSUANCE_NOT_OVERDUE", "The grace window has not yet elapsed.")
    issuance["status"] = "OVERDUE"
    issuance["overdue_days"] = calc.key_overdue_days(issuance)
    touch(issuance)
    return core.ok(serialize.key_issuance(issuance))


@bp.post("/property-care/key-issuances/<iid>/declare-lost")
def declare_lost(iid):
    role, user_id = gates.begin(["Dispatcher", "PlatformAdmin"])
    issuance = gates.fetch_path("key_issuances", iid)
    check_state("key_issuance", issuance, ["OVERDUE"])
    issuance["overdue_days"] = calc.key_overdue_days(issuance)
    if issuance["overdue_days"] < core.KEY_LOST_THRESHOLD_DAYS:
        fail("ERR_LOST_THRESHOLD_NOT_MET", "The loss threshold has not been reached.")
    issuance["status"] = "LOST"
    touch(issuance)
    key = get("key_assets", issuance["key_asset_id"])
    for grant in calc.children("access_grants", "key_issuance_id", issuance["id"]):
        if grant["status"] in ("PENDING", "ACTIVE"):
            grant["status"] = "INVALIDATED"
            grant["invalidated_reason"] = "KEY_LOST"
            touch(grant)
    if key is not None:
        touch(key)
        # LOST -> REKEY_ORDERED continues inside the same request when no rekey is pending
        if not key["rekey_pending_flag"]:
            issuance["status"] = "REKEY_ORDERED"
            key["rekey_pending_flag"] = True
            prop = get("properties", key["property_id"])
            completed = [v for v in calc.children("visits", "property_id", key["property_id"])
                         if v["status"] == "COMPLETED" and v["completed_at"] is not None]
            completed.sort(key=lambda v: (v["completed_at"], v["_seq"]))
            visit_id = completed[-1]["id"] if completed else None
            finding = ops.create_finding(
                key["property_id"], visit_id, "KEY_LOST", "HIGH", "SECURITY",
                "Key lost; rekey ordered.", status="TRIAGED")
            finding["triaged_at"] = now()
            finding["escalation_score"] = calc.finding_escalation_score(finding, prop)
            wo = ops.create_work_order(finding, "REKEY", 1.0, core.REKEY_FEE_CENTS,
                                       user_id, key_asset_id=key["id"])
            finding["status"] = "WORK_ORDERED"
            wo["status"] = "PENDING_APPROVAL"
            calc.run_cost_chain(wo)
    return core.ok(serialize.key_issuance(issuance))


# ---------------------------------------------------------------------------
# Access grants
# ---------------------------------------------------------------------------
@bp.post("/property-care/key-assets/<kid>/access-grants")
def create_grant(kid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    key = gates.fetch_path("key_assets", kid)
    body = gates.body_json()
    if isinstance(body.get("vendor_id"), str):
        gates.fetch_body_fk("vendors", body["vendor_id"], "ERR_VENDOR_NOT_FOUND")
    gates.resolve_optional_fks(body, ["key_issuance_id"])
    expected = body.get("expected_key_asset_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != key["version"]:
            fail("ERR_STALE_KEY_ASSET_VERSION", "The key asset has been modified.")
    gates.validate_payload(body, [
        ("vendor_id", "string", True),
        ("window_start_at", "datetime", True),
        ("window_end_at", "datetime", True),
        ("expected_key_asset_version", "integer", True),
        ("key_issuance_id", "string", False),
    ])
    gates.fetch_body_fk("vendors", body["vendor_id"], "ERR_VENDOR_NOT_FOUND")
    gates.check_interval(body, "window_start_at", "window_end_at")
    grant = ops.create_access_grant(key, body["vendor_id"], parse_iso(body["window_start_at"]),
                                    parse_iso(body["window_end_at"]), body.get("key_issuance_id"))
    return core.ok(serialize.access_grant(grant), 201)


@bp.get("/property-care/access-grants")
def list_grants():
    gates.begin(ISSUANCE_READ_ROLES)
    return gates.list_response("access_grants",
                               ["key_asset_id", "vendor_id", "key_issuance_id", "status"],
                               serialize.access_grant)


@bp.get("/property-care/access-grants/<gid>")
def read_grant(gid):
    gates.begin(ISSUANCE_READ_ROLES)
    grant = gates.fetch_path("access_grants", gid)
    return core.ok(serialize.access_grant(grant))


@bp.post("/property-care/access-grants/<gid>/activate")
def activate_grant(gid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    grant = gates.fetch_path("access_grants", gid)
    check_state("access_grant", grant, ["PENDING"])
    key = get("key_assets", grant["key_asset_id"])
    # ---- G8b rung 51 then rung 52 ----
    if not calc.access_grant_capacity_ok(grant, key):
        fail("ERR_ACCESS_CAPACITY_EXCEEDED", "The key's concurrent access capacity is exhausted.")
    if grant["rotation_index_at_grant"] != key["code_rotation_count"]:
        fail("ERR_ACCESS_GRANT_INVALID", "The grant carries a stale rotation index.")
    if not (grant["window_start_at"] <= now() <= grant["window_end_at"]):
        fail("ERR_GRANT_WINDOW_NOT_OPEN", "The logical clock lies outside the grant window.")
    grant["status"] = "ACTIVE"
    touch(grant)
    return core.ok(serialize.access_grant(grant))


@bp.post("/property-care/access-grants/<gid>/revoke")
def revoke_grant(gid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    grant = gates.fetch_path("access_grants", gid)
    body = gates.body_json()
    reason = gates.enum_discriminator(body, "revoke_reason", core.REVOKE_REASONS)
    check_state("access_grant", grant, ["ACTIVE"])
    if reason == "WINDOW_ELAPSED":
        if not now() > grant["window_end_at"]:
            fail("ERR_INVALID_STATE_TRANSITION", "The grant window has not yet elapsed.")
        grant["status"] = "EXPIRED"
    else:
        grant["status"] = "REVOKED"
    touch(grant)
    return core.ok(serialize.access_grant(grant))
