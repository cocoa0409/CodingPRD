"""In-memory data store, logical clock, datetime helpers, serializers."""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"


def parse_dt(value):
    """Parse an ISO8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits and Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.ingredients = {}
        self.specs = {}
        self.parameters = {}
        self.suppliers = {}
        self.qualifications = {}
        self.sources = {}
        self.contracts = {}
        self.observations = {}
        self.coas = {}
        self.findings = {}
        self.declarations = {}
        self.substitutions = {}
        self.assessments = {}
        self.audits = {}
        self.capas = {}
        self.clock = parse_dt(CLOCK_DEFAULT_ISO)
        self.clock_raw = CLOCK_DEFAULT_ISO
        self.seq = itertools.count(1)


STORE = Store()


def new_record(common=True):
    """Base fields for a persisted entity."""
    now = STORE.clock
    rec = {
        "id": new_id(),
        "_created_dt": now,
        "_seq": next(STORE.seq),
    }
    if common:
        rec["_updated_dt"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump version + updated_at on a mutated row."""
    rec["version"] += 1
    rec["_updated_dt"] = STORE.clock


def set_dt(rec, field, raw):
    """Store an input datetime field: raw string for echo, parsed for arithmetic."""
    rec[field] = raw
    rec[field + "__dt"] = parse_dt(raw)


def set_dt_system(rec, field, dt):
    """Store a system-set datetime field."""
    rec[field] = fmt_dt(dt)
    rec[field + "__dt"] = dt


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(rec):
    return {
        "created_at": fmt_dt(rec["_created_dt"]),
        "updated_at": fmt_dt(rec["_updated_dt"]),
        "version": rec["version"],
    }


def ser_ingredient(r):
    out = {
        "id": r["id"],
        "ingredient_code": r["ingredient_code"],
        "name": r["name"],
        "allergen_profile": r["allergen_profile"],
        "requires_dual_source": r["requires_dual_source"],
        "status": r["status"],
        "active_spec_id": r["active_spec_id"],
        "current_dual_source_breach": r["current_dual_source_breach"],
    }
    out.update(_common(r))
    return out


def ser_spec(r):
    out = {
        "id": r["id"],
        "ingredient_id": r["ingredient_id"],
        "spec_version_label": r["spec_version_label"],
        "supersedes_spec_id": r["supersedes_spec_id"],
        "effective_date": r["effective_date"],
        "author_user_id": r["author_user_id"],
        "reviewed_by_user_id": r["reviewed_by_user_id"],
        "status": r["status"],
        "version_note": r["version_note"],
    }
    out.update(_common(r))
    return out


def ser_parameter(r):
    out = {
        "id": r["id"],
        "spec_id": r["spec_id"],
        "parameter_name": r["parameter_name"],
        "criticality": r["criticality"],
        "uom": r["uom"],
        "target_value": r["target_value"],
        "min_value": r["min_value"],
        "max_value": r["max_value"],
    }
    out.update(_common(r))
    return out


def ser_supplier(r):
    out = {
        "id": r["id"],
        "supplier_code": r["supplier_code"],
        "legal_name": r["legal_name"],
        "risk_tier": r["risk_tier"],
        "country_of_operation": r["country_of_operation"],
        "status": r["status"],
        "composite_risk_score": r["composite_risk_score"],
        "last_audit_closed_at": r["last_audit_closed_at"],
        "open_overdue_capa_count": r["open_overdue_capa_count"],
        "requalification_cycle": r["requalification_cycle"],
    }
    out.update(_common(r))
    return out


def ser_qualification(r):
    out = {
        "id": r["id"],
        "supplier_id": r["supplier_id"],
        "questionnaire_score": r["questionnaire_score"],
        "document_pack_complete": r["document_pack_complete"],
        "decision_note": r["decision_note"],
        "status": r["status"],
        "evaluated_by_user_id": r["evaluated_by_user_id"],
    }
    out.update(_common(r))
    return out


def ser_source(r):
    out = {
        "id": r["id"],
        "ingredient_id": r["ingredient_id"],
        "supplier_id": r["supplier_id"],
        "pinned_spec_id": r["pinned_spec_id"],
        "approved_by_user_id": r["approved_by_user_id"],
        "status": r["status"],
        "suspension_reason": r["suspension_reason"],
    }
    out.update(_common(r))
    return out


def ser_contract(r):
    out = {
        "id": r["id"],
        "approved_source_id": r["approved_source_id"],
        "annual_committed_volume_kg": r["annual_committed_volume_kg"],
        "index_base_value": r["index_base_value"],
        "index_pass_through_pct": r["index_pass_through_pct"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "status": r["status"],
        "cumulative_shipped_kg": r["cumulative_shipped_kg"],
    }
    out.update(_common(r))
    return out


def ser_observation(r):
    # Immutable log: only id + created_at (no updated_at / version).
    return {
        "id": r["id"],
        "index_name": r["index_name"],
        "observed_at": r["observed_at"],
        "index_value": r["index_value"],
        "created_at": fmt_dt(r["_created_dt"]),
    }


def ser_coa(r):
    out = {
        "id": r["id"],
        "approved_source_id": r["approved_source_id"],
        "contract_id": r["contract_id"],
        "lot_number": r["lot_number"],
        "shipped_qty_kg": r["shipped_qty_kg"],
        "received_at": r["received_at"],
        "measured_values": r["measured_values"],
        "registered_by_user_id": r["registered_by_user_id"],
        "provisional_deviation_score": r["provisional_deviation_score"],
        "final_deviation_score": r["final_deviation_score"],
        "unit_price_applied": r["unit_price_applied"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_finding(r):
    out = {
        "id": r["id"],
        "coa_id": r["coa_id"],
        "parameter_name": r["parameter_name"],
        "observed_value": r["observed_value"],
        "violated_bound": r["violated_bound"],
        "excess_ratio": r["excess_ratio"],
        "criticality_at_finding": r["criticality_at_finding"],
        "disposition": r["disposition"],
        "disposition_note": r["disposition_note"],
    }
    out.update(_common(r))
    return out


def ser_declaration(r):
    out = {
        "id": r["id"],
        "approved_source_id": r["approved_source_id"],
        "declaration_type": r["declaration_type"],
        "payload": r["payload"],
        "valid_from": r["valid_from"],
        "valid_until": r["valid_until"],
        "collected_by_user_id": r["collected_by_user_id"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_substitution(r):
    out = {
        "id": r["id"],
        "ingredient_id": r["ingredient_id"],
        "from_approved_source_id": r["from_approved_source_id"],
        "to_approved_source_id": r["to_approved_source_id"],
        "reason_code": r["reason_code"],
        "formula_unit_cost_sensitivities": r["formula_unit_cost_sensitivities"],
        "requested_by_user_id": r["requested_by_user_id"],
        "impact_delta_per_unit": r["impact_delta_per_unit"],
        "requires_regulatory_signoff": r["requires_regulatory_signoff"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_assessment(r):
    out = {
        "id": r["id"],
        "substitution_request_id": r["substitution_request_id"],
        "parameter_deltas": r["parameter_deltas"],
        "total_delta_per_unit": r["total_delta_per_unit"],
        "allergen_delta_tags": r["allergen_delta_tags"],
        "coo_changed": r["coo_changed"],
    }
    out.update(_common(r))
    return out


def ser_audit(r):
    out = {
        "id": r["id"],
        "supplier_id": r["supplier_id"],
        "scheduled_window_start": r["scheduled_window_start"],
        "scheduled_window_end": r["scheduled_window_end"],
        "audit_score": r["audit_score"],
        "findings_summary": r["findings_summary"],
        "cadence_source": r["cadence_source"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_capa(r):
    out = {
        "id": r["id"],
        "audit_id": r["audit_id"],
        "description": r["description"],
        "due_date": r["due_date"],
        "response_text": r["response_text"],
        "verification_note": r["verification_note"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out
