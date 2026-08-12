"""Entity -> public JSON dict serializers (computed fields resolved here)."""

import services


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _light(rec):
    # FixerSkill, TriageRecord, EventReport carry only id + created_at.
    return {"id": rec["id"], "created_at": rec["created_at"]}


def event(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "starts_at": rec["starts_at"],
            "ends_at": rec["ends_at"],
            "intake_item_cap": rec["intake_item_cap"],
            "status": rec["status"],
            "posture": services.posture(rec),
            "active_item_count": services.active_item_count(rec["id"]),
            "diversion_kg_verified": services.kg_out(
                services.diversion_kg(rec["id"], {"VERIFIED"})
            ),
            "diversion_kg_projected": services.kg_out(
                services.diversion_kg(rec["id"], {"VERIFIED", "RECORDED"})
            ),
            "parts_committed_cents": services.committed_parts_cost_event(rec["id"]),
        }
    )
    return out


def station(rec):
    out = _common(rec)
    out.update(
        {
            "event_id": rec["event_id"],
            "category": rec["category"],
            "label": rec["label"],
            "capacity": rec["capacity"],
            "status": rec["status"],
            "checked_in_fixer_count": services.checked_in_count(rec["id"]),
        }
    )
    return out


def fixer(rec):
    out = _common(rec)
    out.update(
        {
            "display_name": rec["display_name"],
            "email": rec["email"],
            "status": rec["status"],
            "safety_induction_completed_at": rec["safety_induction_completed_at"],
            "reliability_score": services.reliability(rec["id"]),
        }
    )
    return out


def skill(rec):
    out = _light(rec)
    out.update(
        {
            "fixer_id": rec["fixer_id"],
            "category": rec["category"],
            "level": rec["level"],
            "certified": rec["certified"],
        }
    )
    return out


def shift(rec):
    out = _common(rec)
    out.update(
        {
            "fixer_id": rec["fixer_id"],
            "station_id": rec["station_id"],
            "event_id": rec["event_id"],
            "start_time": rec["start_time"],
            "end_time": rec["end_time"],
            "status": rec["status"],
            "checked_in_at": rec["checked_in_at"],
        }
    )
    return out


def visitor(rec):
    out = _common(rec)
    out.update(
        {
            "full_name": rec["full_name"],
            "email": rec["email"],
            "phone": rec["phone"],
        }
    )
    return out


def waiver(rec):
    services.refresh_waiver(rec)
    out = _common(rec)
    out.update(
        {
            "visitor_id": rec["visitor_id"],
            "signed_at": rec["signed_at"],
            "safety_clause_accepted": rec["safety_clause_accepted"],
            "status": rec["status"],
        }
    )
    return out


def item(rec):
    out = _common(rec)
    out.update(
        {
            "event_id": rec["event_id"],
            "visitor_id": rec["visitor_id"],
            "category": rec["category"],
            "description": rec["description"],
            "hazard_flag": rec["hazard_flag"],
            "weight_kg_estimated": rec["weight_kg_estimated"],
            "status": rec["status"],
            "assigned_station_id": rec["assigned_station_id"],
            "assigned_fixer_id": rec["assigned_fixer_id"],
            "priority_score": rec["priority_score"],
            "required_skill_level": rec["required_skill_level"],
        }
    )
    return out


def triage(rec):
    out = _light(rec)
    out.update(
        {
            "item_id": rec["item_id"],
            "assessor_fixer_id": rec["assessor_fixer_id"],
            "severity": rec["severity"],
            "estimated_difficulty": rec["estimated_difficulty"],
            "diagnosis": rec["diagnosis"],
            "superseded_by_id": rec["superseded_by_id"],
            "is_current": rec["superseded_by_id"] is None,
        }
    )
    return out


def stock(rec):
    reserved = services.reserved_qty(rec["id"])
    out = _common(rec)
    out.update(
        {
            "sku": rec["sku"],
            "name": rec["name"],
            "category": rec["category"],
            "unit_cost_cents": rec["unit_cost_cents"],
            "quantity_on_hand": rec["quantity_on_hand"],
            "quantity_reserved": reserved,
            "quantity_available": rec["quantity_on_hand"] - reserved,
        }
    )
    return out


def reservation(rec):
    out = _common(rec)
    out.update(
        {
            "part_stock_id": rec["part_stock_id"],
            "repair_item_id": rec["repair_item_id"],
            "quantity": rec["quantity"],
            "unit_cost_cents": rec["unit_cost_cents"],
            "cost_cents": rec["cost_cents"],
            "status": rec["status"],
            "expires_at": rec["expires_at"],
        }
    )
    return out


def outcome(rec):
    out = _common(rec)
    out.update(
        {
            "item_id": rec["item_id"],
            "fixer_id": rec["fixer_id"],
            "outcome": rec["outcome"],
            "weight_kg_actual": rec["weight_kg_actual"],
            "parts_cost_cents": rec["parts_cost_cents"],
            "suggested_donation_cents": rec["suggested_donation_cents"],
            "verification_status": rec["verification_status"],
            "verified_by_user_id": rec["verified_by_user_id"],
        }
    )
    return out


def incident(rec):
    out = _common(rec)
    out.update(
        {
            "event_id": rec["event_id"],
            "item_id": rec["item_id"],
            "fixer_id": rec["fixer_id"],
            "reported_by_user_id": rec["reported_by_user_id"],
            "severity": rec["severity"],
            "description": rec["description"],
            "status": rec["status"],
            "resolution_action": rec["resolution_action"],
        }
    )
    return out


def donation(rec):
    out = _common(rec)
    out.update(
        {
            "event_id": rec["event_id"],
            "visitor_id": rec["visitor_id"],
            "donation_type": rec["donation_type"],
            "amount_cents": rec["amount_cents"],
            "in_kind_lines": rec["in_kind_lines"],
            "status": rec["status"],
            "received_at": rec["received_at"],
            "receipt_value_cents": rec["receipt_value_cents"],
            "campaign_value_cents": rec["campaign_value_cents"],
        }
    )
    return out


def report(rec):
    out = _light(rec)
    out.update(
        {
            "event_id": rec["event_id"],
            "generated_at": rec["generated_at"],
            "items_total": rec["items_total"],
            "items_fixed": rec["items_fixed"],
            "items_partially_fixed": rec["items_partially_fixed"],
            "items_not_repairable": rec["items_not_repairable"],
            "success_rate_strict": rec["success_rate_strict"],
            "success_rate_lenient": rec["success_rate_lenient"],
            "diversion_kg_verified": rec["diversion_kg_verified"],
            "diversion_kg_projected": rec["diversion_kg_projected"],
            "parts_cost_total_cents": rec["parts_cost_total_cents"],
            "donations_receipt_total_cents": rec["donations_receipt_total_cents"],
            "donations_campaign_total_cents": rec["donations_campaign_total_cents"],
        }
    )
    return out
