"""Response projections. Field sets follow SCAFFOLD entities exactly."""
import calc
import services
from core import iso, now, num, ok_list, pagination


def audit_stamps(rec, out):
    out["created_at"] = iso(rec["created_at"])
    out["updated_at"] = iso(rec["updated_at"])
    out["version"] = rec["version"]
    return out


def plain(rec, fields, times=(), numbers=()):
    out = {"id": rec["id"]}
    for name in fields:
        out[name] = rec.get(name)
    for name in times:
        out[name] = iso(rec.get(name))
    for name in numbers:
        value = rec.get(name)
        out[name] = None if value is None else num(value)
    return out


def paged(items, serializer, limit, offset):
    total = len(items)
    window = items[offset : offset + limit]
    return ok_list([serializer(row) for row in window], total, limit, offset)


def paged_now(items, serializer):
    limit, offset = pagination()
    return paged(items, serializer, limit, offset)


# ---------------------------------------------------------------- projections
def jurisdiction(rec):
    out = plain(
        rec,
        [
            "code",
            "name",
            "unit_price_required",
            "unit_price_uom_rule",
            "unit_price_decimal_places",
            "unit_price_rounding",
            "default_rate_variant",
            "overcharge_refund_policy",
            "refund_fixed_bonus_cents",
            "refund_cap_cents",
            "refund_budget_per_audit_cents",
            "penalty_per_violation_cents",
            "penalty_max_cents",
            "signage_disclosure_codes",
            "grace_period_hours",
            "accountability_variant",
        ],
        numbers=["scanner_error_rate_threshold_pct"],
    )
    return audit_stamps(rec, out)


def store(rec):
    out = plain(
        rec,
        [
            "store_number",
            "name",
            "jurisdiction_id",
            "compliance_posture",
            "label_backlog_count",
            "open_finding_count",
            "escalated_finding_count",
            "failed_audit_count_30d",
            "signage_violation_count",
            "refund_liability_outstanding_cents",
            "refund_paid_total_cents",
            "cumulative_penalty_exposure_cents",
            "executed_file_count",
        ],
    )
    return audit_stamps(rec, out)


def aisle(rec):
    out = plain(
        rec,
        ["store_id", "aisle_code", "category_code", "assigned_associate_id"],
        times=["last_audit_closed_at"],
    )
    return audit_stamps(rec, out)


def associate(rec):
    out = plain(
        rec,
        [
            "store_id",
            "employee_number",
            "full_name",
            "role_code",
            "training_status",
            "last_training_module_code",
            "issued_action_count",
            "verified_placement_count",
        ],
        times=["certification_expires_at"],
        numbers=["last_training_score_pct", "accountability_score"],
    )
    return audit_stamps(rec, out)


def price_change_file(rec):
    out = plain(
        rec,
        ["file_number", "jurisdiction_id", "priority", "scope_store_ids", "status",
         "superseded_by_file_id"],
        times=["effective_date", "distributed_at"],
    )
    total, verified = services.line_counts(rec["id"])
    out["line_count"] = total
    out["verified_line_count"] = verified
    return audit_stamps(rec, out)


def price_change_line(rec):
    out = plain(
        rec,
        [
            "price_change_file_id",
            "item_upc",
            "item_description",
            "category_code",
            "old_retail_cents",
            "new_retail_cents",
            "net_content_uom",
            "promo_flag",
            "line_status",
            "unit_price_basis_uom",
        ],
        numbers=["net_content_qty", "unit_price_display_cents", "unit_price_basis_qty"],
    )
    return audit_stamps(rec, out)


def label_task(rec):
    out = plain(
        rec,
        [
            "store_id",
            "price_change_line_id",
            "aisle_id",
            "assigned_associate_id",
            "placed_by_associate_id",
            "verified_by_associate_id",
            "print_status",
            "placement_status",
            "printed_label_serial",
            "rejection_count",
            "observed_shelf_price_cents",
        ],
        times=[
            "scheduled_start_at",
            "scheduled_end_at",
            "due_at",
            "placed_at",
            "verified_at",
        ],
    )
    out["overdue"] = calc.is_overdue(rec, now())
    return audit_stamps(rec, out)


def scanner_audit(rec):
    out = plain(
        rec,
        [
            "store_id",
            "aisle_id",
            "auditor_associate_id",
            "audit_type",
            "status",
            "outcome",
            "rate_variant_applied",
            "reopen_count",
        ],
        times=["scan_window_start", "scan_window_end", "closed_at"],
        numbers=["gross_error_rate_pct", "net_overcharge_rate_pct", "error_rate_pct"],
    )
    sample, over, under = services.audit_counts(rec["id"])
    out["sample_size"] = sample
    out["overcharge_count"] = over
    out["undercharge_count"] = under
    return audit_stamps(rec, out)


def scan_line(rec):
    out = plain(
        rec,
        [
            "scanner_audit_id",
            "item_upc",
            "shelf_price_cents",
            "register_price_cents",
            "variance_cents",
            "classification",
            "category_code",
        ],
    )
    out["created_at"] = iso(rec["created_at"])
    return out


def promo_signage(rec):
    out = plain(
        rec,
        [
            "store_id",
            "aisle_id",
            "price_change_line_id",
            "sign_code",
            "disclosure_codes",
            "status",
            "missing_disclosure_codes",
            "compliance_state",
        ],
        times=["promo_start_at", "promo_end_at", "posted_at", "removed_at"],
    )
    return audit_stamps(rec, out)


def regulatory_inspection(rec):
    out = plain(
        rec,
        [
            "store_id",
            "scanner_audit_id",
            "inspector_ref",
            "status",
            "finding_count",
            "penalty_exposure_cents",
            "refund_liability_cents",
            "refund_credit_cents",
            "assessed_penalty_cents",
            "response_round",
            "remediation_summary",
        ],
        times=["inspection_date", "closed_at"],
    )
    return audit_stamps(rec, out)


def inspection_finding(rec):
    out = plain(
        rec,
        [
            "regulatory_inspection_id",
            "finding_code",
            "severity",
            "affected_item_count",
            "affected_aisle_code",
            "status",
            "penalty_component_cents",
            "remediation_action_code",
            "remediation_evidence_ref",
            "waiver_reason",
        ],
    )
    return audit_stamps(rec, out)


def refund_claim(rec):
    out = plain(
        rec,
        [
            "scan_line_id",
            "store_id",
            "customer_ref",
            "claimed_amount_cents",
            "policy_applied",
            "status",
            "denial_reason",
        ],
        times=["paid_at"],
    )
    return audit_stamps(rec, out)


def exception_report(rec):
    out = plain(
        rec,
        [
            "store_id",
            "audit_count",
            "scan_line_count",
            "top_category_code",
            "category_breakdown",
            "root_cause_code",
            "remediation_owner_associate_id",
            "status",
            "closure_note",
        ],
        times=["period_start_at", "period_end_at"],
        numbers=["top_category_error_rate_pct"],
    )
    return audit_stamps(rec, out)


def accountability_action(rec):
    out = plain(
        rec,
        [
            "associate_id",
            "trigger_code",
            "action_type",
            "status",
            "score_weight",
            "source_ref",
            "issued_by_ref",
            "void_reason",
        ],
    )
    return audit_stamps(rec, out)
