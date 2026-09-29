"""Entity -> JSON serializers with explicit field lists (PRD 1.1 field order)."""

from decimal import Decimal

from response import fmt_instant


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _dt(value):
    return fmt_instant(value)


def _common(entity, versioned=True):
    payload = {"created_at": _dt(entity["created_at"])}
    if versioned:
        payload["updated_at"] = _dt(entity["updated_at"])
        payload["version"] = entity["version"]
    return payload


def product(row):
    payload = {
        "id": row["id"],
        "model_code": row["model_code"],
        "product_type": row["product_type"],
        "material": row["material"],
        "duty_rating": row["duty_rating"],
        "working_length_ft": _num(row["working_length_ft"]),
        "retail_sku": row["retail_sku"],
        "rated_load_lb": row["rated_load_lb"],
        "safety_factor": _num(row["safety_factor"]),
        "required_test_load_lb": _num(row["required_test_load_lb"]),
        "required_pull_force_lbf": _num(row["required_pull_force_lbf"]),
        "max_allowed_deflection_in": _num(row["max_allowed_deflection_in"]),
        "design_status": row["design_status"],
        "market_status": row["market_status"],
        "design_frozen_at": _dt(row["design_frozen_at"]),
        "frozen_revision_id": row["frozen_revision_id"],
        "market_status_changed_at": _dt(row["market_status_changed_at"]),
        "stop_ship_reason_code": row["stop_ship_reason_code"],
        "held_registration_count": row["held_registration_count"],
        "risk_score_gross": _num(row["risk_score_gross"]),
        "risk_score_mitigated": _num(row["risk_score_mitigated"]),
        "dhf_retention_until": _dt(row["dhf_retention_until"]),
        "retention_anchor_source": row["retention_anchor_source"],
    }
    payload.update(_common(row))
    return payload


def design_revision(row):
    payload = {
        "id": row["id"],
        "product_id": row["product_id"],
        "revision_label": row["revision_label"],
        "joint_type": row["joint_type"],
        "structural_margin_pct": _num(row["structural_margin_pct"]),
        "rail_section_modulus_in3": _num(row["rail_section_modulus_in3"]),
        "supersedes_revision_id": row["supersedes_revision_id"],
        "status": row["status"],
        "review_round": row["review_round"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "reviewer_notes": row["reviewer_notes"],
        "superseded_at": _dt(row["superseded_at"]),
    }
    payload.update(_common(row))
    return payload


def product_document(row):
    payload = {
        "id": row["id"],
        "product_id": row["product_id"],
        "doc_kind": row["doc_kind"],
        "document_version": row["document_version"],
        "text_digest": row["text_digest"],
        "placement_zone": row["placement_zone"],
        "pictogram_count": row["pictogram_count"],
        "includes_assembly_instructions": row["includes_assembly_instructions"],
        "status": row["status"],
        "approved_at": _dt(row["approved_at"]),
    }
    payload.update(_common(row))
    return payload


def test_bench(row):
    payload = {
        "id": row["id"],
        "bench_code": row["bench_code"],
        "max_load_capacity_lb": _num(row["max_load_capacity_lb"]),
        "cooldown_minutes": row["cooldown_minutes"],
        "reserved_minutes_total": row["reserved_minutes_total"],
    }
    payload.update(_common(row))
    return payload


def bench_reservation(row):
    payload = {
        "id": row["id"],
        "test_bench_id": row["test_bench_id"],
        "test_campaign_id": row["test_campaign_id"],
        "start_at": _dt(row["start_at"]),
        "end_at": _dt(row["end_at"]),
        "duration_minutes": row["duration_minutes"],
        "status": row["status"],
    }
    payload.update(_common(row))
    return payload


def test_campaign(row):
    payload = {
        "id": row["id"],
        "product_id": row["product_id"],
        "design_revision_id": row["design_revision_id"],
        "purpose": row["purpose"],
        "listing_record_id": row["listing_record_id"],
        "sampled_lot_id": row["sampled_lot_id"],
        "sample_window_start": _dt(row["sample_window_start"]),
        "sample_window_end": _dt(row["sample_window_end"]),
        "status": row["status"],
        "audit_sample_size": row["audit_sample_size"],
        "escalation_tier": row["escalation_tier"],
        "prior_failure_rate_pct": _num(row["prior_failure_rate_pct"]),
        "load_test_count": row["load_test_count"],
        "failed_test_count": row["failed_test_count"],
        "started_at": _dt(row["started_at"]),
        "concluded_at": _dt(row["concluded_at"]),
    }
    payload.update(_common(row))
    return payload


def load_test(row):
    payload = {
        "id": row["id"],
        "test_campaign_id": row["test_campaign_id"],
        "test_code": row["test_code"],
        "applied_load_lb": _num(row["applied_load_lb"]),
        "measured_deflection_in": _num(row["measured_deflection_in"]),
        "permanent_set_in": _num(row["permanent_set_in"]),
        "outcome": row["outcome"],
        "failure_reason_code": row["failure_reason_code"],
    }
    payload.update(_common(row, versioned=False))
    return payload


def production_lot(row):
    payload = {
        "id": row["id"],
        "product_id": row["product_id"],
        "design_revision_id": row["design_revision_id"],
        "lot_code": row["lot_code"],
        "planned_units": row["planned_units"],
        "extrusion_heat_number": row["extrusion_heat_number"],
        "pultrusion_batch_id": row["pultrusion_batch_id"],
        "produced_units": row["produced_units"],
        "units_wip": row["units_wip"],
        "units_quarantined": row["units_quarantined"],
        "units_released": row["units_released"],
        "units_scrapped": row["units_scrapped"],
        "status": row["status"],
        "joint_sample_count": row["joint_sample_count"],
        "joint_fail_count": row["joint_fail_count"],
        "required_joint_sample_count": row["required_joint_sample_count"],
        "conformance_index": _num(row["conformance_index"]),
        "released_at": _dt(row["released_at"]),
        "quarantine_reason_code": row["quarantine_reason_code"],
        "disposition": row["disposition"],
    }
    payload.update(_common(row))
    return payload


def joint_sample(row):
    payload = {
        "id": row["id"],
        "production_lot_id": row["production_lot_id"],
        "sample_seq": row["sample_seq"],
        "pull_force_lbf": _num(row["pull_force_lbf"]),
        "required_pull_force_lbf": _num(row["required_pull_force_lbf"]),
        "margin_pct": row["margin_pct"],
        "result": row["result"],
    }
    payload.update(_common(row, versioned=False))
    return payload


def listing_body(row):
    payload = {
        "id": row["id"],
        "body_code": row["body_code"],
        "accredited_standards": list(row["accredited_standards"]),
        "audit_interval_days": row["audit_interval_days"],
    }
    payload.update(_common(row))
    return payload


def listing_record(row):
    payload = {
        "id": row["id"],
        "product_id": row["product_id"],
        "listing_body_id": row["listing_body_id"],
        "standard_code": row["standard_code"],
        "status": row["status"],
        "listed_at": _dt(row["listed_at"]),
        "audit_due_at": _dt(row["audit_due_at"]),
        "listing_expires_at": _dt(row["listing_expires_at"]),
        "suspended_at": _dt(row["suspended_at"]),
        "suspension_reason": row["suspension_reason"],
    }
    payload.update(_common(row))
    return payload


def consumer_registration(row):
    payload = {
        "id": row["id"],
        "production_lot_id": row["production_lot_id"],
        "recall_event_id": row["recall_event_id"],
        "consumer_email": row["consumer_email"],
        "purchase_channel": row["purchase_channel"],
        "purchase_date": _dt(row["purchase_date"]),
        "serial_suffix": row["serial_suffix"],
        "registration_status": row["registration_status"],
        "hold_flag": row["hold_flag"],
        "notified_at": _dt(row["notified_at"]),
        "acknowledged_at": _dt(row["acknowledged_at"]),
        "remedy_choice": row["remedy_choice"],
    }
    payload.update(_common(row))
    return payload


def field_incident(row):
    payload = {
        "id": row["id"],
        "product_id": row["product_id"],
        "production_lot_id": row["production_lot_id"],
        "consumer_registration_id": row["consumer_registration_id"],
        "incident_type": row["incident_type"],
        "injury_severity": row["injury_severity"],
        "occurred_at": _dt(row["occurred_at"]),
        "narrative": row["narrative"],
        "status": row["status"],
        "finding": row["finding"],
        "root_cause_code": row["root_cause_code"],
        "requires_capa": row["requires_capa"],
        "incident_points": _num(row["incident_points"]),
        "closed_at": _dt(row["closed_at"]),
    }
    payload.update(_common(row))
    return payload


def corrective_action(row):
    payload = {
        "id": row["id"],
        "field_incident_id": row["field_incident_id"],
        "design_revision_id": row["design_revision_id"],
        "supersedes_action_id": row["supersedes_action_id"],
        "action_summary": row["action_summary"],
        "authored_by_user_id": row["authored_by_user_id"],
        "status": row["status"],
        "verified_at": _dt(row["verified_at"]),
        "verified_by_user_id": row["verified_by_user_id"],
    }
    payload.update(_common(row))
    return payload


def recall_event(row):
    payload = {
        "id": row["id"],
        "product_id": row["product_id"],
        "remedy_type": row["remedy_type"],
        "affected_revision_ids": list(row["affected_revision_ids"]),
        "hazard_description": row["hazard_description"],
        "status": row["status"],
        "announced_at": _dt(row["announced_at"]),
        "exposure_units_shipped_basis": row["exposure_units_shipped_basis"],
        "exposure_units_registered_basis": row["exposure_units_registered_basis"],
        "notification_coverage_pct": _num(row["notification_coverage_pct"]),
        "units_remedied": row["units_remedied"],
        "units_outstanding": row["units_outstanding"],
        "closed_at": _dt(row["closed_at"]),
    }
    payload.update(_common(row))
    return payload
