"""Common record helpers and entity lookups (PRD §2.4, §2.5)."""

from db import store, new_id
from errors import not_found


def base_record():
    """Common fields per PRD §2.4: id, created_at, updated_at, version.

    version starts at 1 at creation and increments on every mutation.
    """
    ts = store.now_str()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(rec):
    """One mutation event on a versioned resource: version +1, updated_at."""
    rec["version"] = int(rec.get("version", 1)) + 1
    rec["updated_at"] = store.now_str()
    return rec


def public(rec):
    """Serialize a stored record, hiding internal underscore-prefixed keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_records(records):
    """List default sort: created_at ascending (PRD §2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def _get(table, rid, label):
    rec = table.get(rid)
    if rec is None:
        raise not_found(f"{label} {rid} not found")
    return rec


def get_style(rid):
    return _get(store.styles, rid, "Style")


def get_tech_pack(rid):
    return _get(store.tech_packs, rid, "TechPack")


def get_operation_spec(rid):
    return _get(store.operation_specs, rid, "OperationSpec")


def get_trim_item(rid):
    return _get(store.trim_items, rid, "TrimItem")


def get_trim_requirement(rid):
    return _get(store.trim_requirements, rid, "TrimRequirement")


def get_fabric_roll(rid):
    return _get(store.fabric_rolls, rid, "FabricRoll")


def get_production_order(rid):
    return _get(store.production_orders, rid, "ProductionOrder")


def get_marker(rid):
    return _get(store.markers, rid, "Marker")


def get_bundle(rid):
    return _get(store.bundles, rid, "Bundle")


def get_sewing_line(rid):
    return _get(store.sewing_lines, rid, "SewingLine")


def get_line_assignment(rid):
    return _get(store.line_assignments, rid, "LineAssignment")


def get_operator(rid):
    return _get(store.operators, rid, "Operator")


def get_piece_work_entry(rid):
    return _get(store.piece_work_entries, rid, "PieceWorkEntry")


def get_payroll_run(rid):
    return _get(store.payroll_runs, rid, "PayrollRun")


def get_quality_audit(rid):
    return _get(store.quality_audits, rid, "QualityAudit")


def pack_requirements(pack_id):
    return [r for r in sorted_records(store.trim_requirements.values())
            if r["tech_pack_id"] == pack_id]


def pack_operations(pack_id):
    return sorted(
        [o for o in store.operation_specs.values() if o["tech_pack_id"] == pack_id],
        key=lambda o: o["sequence_no"],
    )


def order_bundles(order_id):
    return sorted_records(
        [b for b in store.bundles.values() if b["production_order_id"] == order_id]
    )
