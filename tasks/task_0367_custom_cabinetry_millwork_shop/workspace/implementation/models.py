"""Record construction, common-field management, and serialization.

Common fields (PRD §2.4): id (UUID), created_at, updated_at (ISO8601 UTC with
3 fractional digits), version (int starting at 1, +1 on every mutation).
"""
from db import store, new_id, now_iso


def _base_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(record):
    """Mutation bump: refresh updated_at and increment version (PRD §2.4 / §2.8)."""
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1


# --------------------------------------------------------------------------
# Computed-field recompute helpers
# --------------------------------------------------------------------------
def material_reserved_sheets(material_id):
    total = 0
    for r in store.reservations.values():
        if r["material_id"] == material_id and r["status"] in ("HELD", "COMMITTED"):
            total += r["sheets"]
    return total


def project_specs(project_id):
    return [s for s in store.specs.values() if s["project_id"] == project_id]


def project_active_finish(project_id):
    for f in store.finish_selections.values():
        if f["project_id"] == project_id and f["is_active"]:
            return f
    return None


def project_billed_to_date(project_id):
    total = 0
    for d in store.draws.values():
        if d["project_id"] == project_id and d["status"] in ("ISSUED", "PAID"):
            total += d["amount_cents"]
    return total


def project_paid_to_date(project_id):
    total = 0
    for d in store.draws.values():
        if d["project_id"] == project_id and d["status"] == "PAID":
            total += d["amount_cents"]
    return total


def customer_lifetime_paid(customer_id):
    total = 0
    proj_ids = {p["id"] for p in store.projects.values() if p["customer_id"] == customer_id}
    for d in store.draws.values():
        if d["project_id"] in proj_ids and d["status"] == "PAID":
            total += d["amount_cents"]
    return total


def project_open_change_delta(project_id):
    # APPROVED change orders contribute; folding happens immediately on approve,
    # so this is an informational running sum of approved deltas.
    total = 0
    for c in store.change_orders.values():
        if c["project_id"] == project_id and c["status"] == "APPROVED":
            total += c.get("delta_cents") or 0
    return total


# --------------------------------------------------------------------------
# Serialization: strip private keys, attach computed fields
# --------------------------------------------------------------------------
_PRIVATE = ("_seq",)


def _public(record, computed=None):
    out = {k: v for k, v in record.items() if k not in _PRIVATE}
    if computed:
        out.update(computed)
    return out


def serialize_shop(r):
    return _public(r)


def serialize_customer(r):
    return _public(r, {
        "lifetime_paid_cents": customer_lifetime_paid(r["id"]),
    })


def serialize_project(r):
    return _public(r, {
        "billed_to_date_cents": project_billed_to_date(r["id"]),
        "paid_to_date_cents": project_paid_to_date(r["id"]),
        "open_change_delta_cents": project_open_change_delta(r["id"]),
    })


def serialize_spec(r):
    return _public(r)


def serialize_material(r):
    reserved = material_reserved_sheets(r["id"])
    return _public(r, {
        "reserved_sheets": reserved,
        "available_sheets": r["on_hand_sheets"] - reserved,
    })


def serialize_reservation(r):
    return _public(r)


def serialize_machine(r):
    return _public(r)


def serialize_build_job(r):
    return _public(r)


def serialize_finish(r):
    return _public(r)


def serialize_draw(r):
    return _public(r)


def serialize_change_order(r):
    return _public(r)


def serialize_installation(r):
    return _public(r)


def serialize_punch(r):
    return _public(r)
