"""Domain helpers: entity factory, serializers, cascade utilities."""
from db import STORE, new_id, next_seq, now_dt, now_iso, fmt_dt
from errors import not_found
import calc


def new_entity():
    """Common system fields (PRD §2.5): id, created_at, updated_at, version."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def bump(entity):
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def get_or_404(collection, entity_id, label="Resource"):
    entity = collection.get(entity_id)
    if entity is None:
        raise not_found(f"{label} {entity_id} not found")
    return entity


def program_of(entity):
    return STORE.programs.get(entity["program_id"])


def bump_program(prog):
    bump(prog)


def regen_draft_invoices(program_id):
    """§2.7: a program-level figure mutation regenerates every DRAFT invoice's
    lines, bumping each such invoice's version and updated_at. DRAFT lines are
    computed lazily at read time, so the bump is the observable effect."""
    for inv in STORE.invoices.values():
        if inv["program_id"] == program_id and inv["status"] == "DRAFT":
            bump(inv)


def by_created(items):
    """Default list order: creation timestamp ascending (insertion tiebreak)."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_customer(c):
    out = _common(c)
    out.update({
        "name": c["name"],
        "contact_email": c["contact_email"],
        "credit_status": c["credit_status"],
    })
    return out


def serialize_aircraft(a):
    out = _common(a)
    out.update({
        "customer_id": a["customer_id"],
        "tail_number": a["tail_number"],
        "model": a["model"],
        "max_delta_lbs": a["max_delta_lbs"],
        "status": a["status"],
    })
    return out


def serialize_program(p):
    out = _common(p)
    gallons, cost = calc.material_estimate(p)
    committed = calc.committed_delivery_date(p)
    out.update({
        "aircraft_id": p["aircraft_id"],
        "customer_id": p["customer_id"],
        "base_price_cents": p["base_price_cents"],
        "daily_penalty_rate_cents": p["daily_penalty_rate_cents"],
        "penalty_cap_pct": p["penalty_cap_pct"],
        "contractual_delivery_date": fmt_dt(p["contractual_delivery_date"]),
        "committed_delivery_date": fmt_dt(committed),
        "actual_delivery_date": fmt_dt(p["actual_delivery_date"]) if p["actual_delivery_date"] else None,
        "status": p["status"],
        "total_contract_value_cents": calc.total_contract_value_cents(p),
        "discovery_cost_total_cents": calc.discovery_cost_total_cents(p["id"]),
        "billed_total_cents": billed_total_cents(p["id"]),
        "penalty_final_cents": p["penalty_final_cents"],
        "projected_penalty_cents": calc.delivery_penalty(p, "projection"),
        "rework_cycles": p["rework_cycles"],
        "approved_scheme_id": p["approved_scheme_id"],
        "material_estimate_gallons": gallons,
        "material_estimate_cost_cents": cost,
    })
    return out


def billed_total_cents(program_id):
    total = 0
    for inv in calc.invoices_of(program_id):
        if inv["status"] in ("ISSUED", "PAID"):
            total += inv["total_cents"]
    return total


def serialize_scheme(s):
    out = _common(s)
    out.update({
        "program_id": s["program_id"],
        "drawing_ref": s["drawing_ref"],
        "painted_area_sqft": s["painted_area_sqft"],
        "coat_count": s["coat_count"],
        "stripe_pct": s["stripe_pct"],
        "status": s["status"],
        "superseded_by_id": s["superseded_by_id"],
    })
    return out


def serialize_assessment(a):
    out = _common(a)
    out.update({
        "program_id": a["program_id"],
        "status": a["status"],
        "decision": a["decision"],
        "corrosion_severity": a["corrosion_severity"],
        "findings_note": a["findings_note"],
        "revision": a["revision"],
    })
    return out


def serialize_discovery(d):
    out = _common(d)
    out.update({
        "program_id": d["program_id"],
        "assessment_id": d["assessment_id"],
        "source": d["source"],
        "description": d["description"],
        "safety_linked": d["safety_linked"],
        "status": d["status"],
        "est_cost_cents": d["est_cost_cents"],
        "est_hours": d["est_hours"],
        "actual_cost_cents": d["actual_cost_cents"],
        "defer_reason": d["defer_reason"],
    })
    return out


def serialize_change_order(c):
    out = _common(c)
    out.update({
        "program_id": c["program_id"],
        "kind": c["kind"],
        "delta_price_cents": c["delta_price_cents"],
        "delta_days": c["delta_days"],
        "description": c["description"],
        "acknowledges_weight_record_id": c["acknowledges_weight_record_id"],
        "status": c["status"],
        "counter_note": c["counter_note"],
        "negotiation_round": c["negotiation_round"],
    })
    return out


def serialize_bay(b):
    out = _common(b)
    out.update({
        "name": b["name"],
        "daily_rate_cents": b["daily_rate_cents"],
        "status": b["status"],
    })
    return out


def serialize_slot(s):
    out = _common(s)
    out.update({
        "bay_id": s["bay_id"],
        "program_id": s["program_id"],
        "start_at": fmt_dt(s["start_at"]),
        "end_at": fmt_dt(s["end_at"]),
        "status": s["status"],
    })
    return out


def serialize_booth(b):
    out = _common(b)
    out.update({
        "name": b["name"],
        "hourly_rate_cents": b["hourly_rate_cents"],
        "cure_buffer_hours": b["cure_buffer_hours"],
    })
    return out


def serialize_booking(b):
    out = _common(b)
    out.update({
        "booth_id": b["booth_id"],
        "program_id": b["program_id"],
        "start_at": fmt_dt(b["start_at"]),
        "end_at": fmt_dt(b["end_at"]),
        "status": b["status"],
        "actual_hours": b["actual_hours"],
        "scheduled_fee_cents": b["scheduled_fee_cents"],
        "actual_fee_cents": b["actual_fee_cents"],
    })
    return out


def serialize_lot(lot):
    out = _common(lot)
    out.update({
        "program_id": lot["program_id"],
        "description": lot["description"],
        "material": lot["material"],
        "quantity": lot["quantity"],
        "estimated_weight_lbs": lot["estimated_weight_lbs"],
        "status": lot["status"],
        "fail_count": lot["fail_count"],
    })
    return out


def serialize_burn_test(t):
    # Append-only record: id + created_at only, no updated_at/version (§2.5).
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "lot_id": t["lot_id"],
        "test_method": t["test_method"],
        "result": t["result"],
        "lab_name": t["lab_name"],
        "test_sequence": t["test_sequence"],
    }


def serialize_weight_record(w):
    out = _common(w)
    out.update({
        "program_id": w["program_id"],
        "scheme_id": w["scheme_id"],
        "variant": w["variant"],
        "removal_weight_lbs": w["removal_weight_lbs"],
        "installed_weight_lbs": w["installed_weight_lbs"],
        "film_lbs": w["film_lbs"],
        "delta_lbs": w["delta_lbs"],
        "status": w["status"],
        "prepared_by_user_id": w["prepared_by_user_id"],
    })
    return out


def serialize_inspection(i):
    out = _common(i)
    out.update({
        "program_id": i["program_id"],
        "inspection_type": i["inspection_type"],
        "status": i["status"],
        "major_defects": i["major_defects"],
        "minor_defects": i["minor_defects"],
        "rework_of_id": i["rework_of_id"],
    })
    return out


def serialize_delay_event(e):
    out = _common(e)
    out.update({
        "program_id": e["program_id"],
        "category": e["category"],
        "impact_days": e["impact_days"],
        "reason": e["reason"],
        "source": e["source"],
        "status": e["status"],
        "event_seq": e["event_seq"],
    })
    return out


def serialize_invoice(inv):
    out = _common(inv)
    if inv["status"] == "DRAFT":
        prog = STORE.programs.get(inv["program_id"])
        lines, total = calc.compute_invoice_lines(prog, inv["kind"])
    else:
        lines, total = inv["lines"], inv["total_cents"]
    out.update({
        "program_id": inv["program_id"],
        "kind": inv["kind"],
        "status": inv["status"],
        "lines": lines,
        "total_cents": total,
        "issued_at": fmt_dt(inv["issued_at"]) if inv["issued_at"] else None,
    })
    return out
