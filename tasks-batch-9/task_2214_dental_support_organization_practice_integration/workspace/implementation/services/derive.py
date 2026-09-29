"""Derived fields: relationship indexes, counters, the posture ladder and rollups.

Every `source: computed` field in the scaffold is recomputed from the rows it
depends on, so a counter can never drift from the ledger it summarises.
"""

import clock
import config
import db
from services import calc

# ------------------------------------------------------------------- indexes


def practices_of_affiliation(affiliation_id):
    return db.find("practices", affiliation_id=affiliation_id)


def practices_of_vendor(vendor_id):
    return db.find("practices", conversion_vendor_id=vendor_id)


def employments_of_practice(practice_id):
    return db.find("doctor_employments", practice_id=practice_id)


def batches_of_practice(practice_id):
    return db.find("migration_batches", practice_id=practice_id)


def contracts_of_practice(practice_id):
    return db.find("payer_contracts", practice_id=practice_id)


def enrollments_of_contract(contract_id):
    return db.find("payer_enrollments", payer_contract_id=contract_id)


def enrollments_of_employment(employment_id):
    return db.find("payer_enrollments", doctor_employment_id=employment_id)


def enrollments_of_practice(practice_id):
    rows = []
    for contract in contracts_of_practice(practice_id):
        rows.extend(enrollments_of_contract(contract["id"]))
    return db.ordered(rows)


def line_items_of_agreement(agreement_id):
    return db.find("service_line_items", service_agreement_id=agreement_id)


def agreements_of_practice(practice_id):
    return db.find("service_agreements", practice_id=practice_id)


def fee_items_of_contract(contract_id):
    return db.find("fee_schedule_items", payer_contract_id=contract_id)


def tranches_of_affiliation(affiliation_id):
    return db.find("earnout_tranches", affiliation_id=affiliation_id)


def consolidations_of_practice(practice_id):
    return db.find("vendor_consolidations", practice_id=practice_id)


def exceptions_of_employment(employment_id):
    return db.find("supply_preference_exceptions", doctor_employment_id=employment_id)


def reviews_of_employment(employment_id):
    return db.find("clinical_quality_reviews", doctor_employment_id=employment_id)


def practice_of_employment(employment):
    return db.get("practices", employment["practice_id"])


def affiliation_of_practice(practice):
    return db.get("affiliations", practice["affiliation_id"])


def affiliation_of_employment(employment):
    practice = practice_of_employment(employment)
    return affiliation_of_practice(practice) if practice else None


# ------------------------------------------------------------------ affiliation


def practice_count(affiliation):
    return len(practices_of_affiliation(affiliation["id"]))


def earnout_reserved_cents(affiliation):
    return sum(
        t["reserved_cents"]
        for t in tranches_of_affiliation(affiliation["id"])
        if t["status"] == "RESERVED"
    )


def earnout_settled_cents(affiliation):
    return sum(
        t["awarded_cents"]
        for t in tranches_of_affiliation(affiliation["id"])
        if t["status"] == "SETTLED"
    )


def earnout_unallocated_cents(affiliation):
    return (
        affiliation["earnout_pool_cents"]
        - earnout_reserved_cents(affiliation)
        - earnout_settled_cents(affiliation)
    )


# --------------------------------------------------------------------- vendor


def active_window_count(vendor):
    """SCHEDULED batches whose practice names this vendor (HELD windows are parked)."""
    total = 0
    for practice in practices_of_vendor(vendor["id"]):
        for batch in batches_of_practice(practice["id"]):
            if batch["status"] == "SCHEDULED":
                total += 1
    return total


# ------------------------------------------------------------------- practice


def active_doctor_count(practice):
    return sum(
        1
        for e in employments_of_practice(practice["id"])
        if e["employment_status"] == "ACTIVE"
    )


def charts_migrated_count(practice):
    return sum(
        batch["records_validated"]
        for batch in batches_of_practice(practice["id"])
        if batch["status"] in ("VALIDATED", "RECONCILED")
    )


def pending_credentialing_count(practice):
    return sum(
        1
        for e in enrollments_of_practice(practice["id"])
        if e["status"] == "SUBMITTED"
    )


def denied_enrollment_count(practice):
    return sum(
        1 for e in enrollments_of_practice(practice["id"]) if e["status"] == "DENIED"
    )


def quarantined_batch_count(practice):
    return sum(
        1
        for batch in batches_of_practice(practice["id"])
        if batch["status"] == "QUARANTINED"
    )


def integration_posture(practice):
    """PRD 2.6 ladder — first matching clause wins."""
    if practice["affiliation_status"] != "AFFILIATED":
        return "PRE_CLOSE"
    if active_doctor_count(practice) == 0:
        return "FROZEN"
    if quarantined_batch_count(practice) > 0 or denied_enrollment_count(practice) > 0:
        return "RESTRICTED"
    if (
        pending_credentialing_count(practice) > 0
        or charts_migrated_count(practice) < practice["charts_total_expected"]
    ):
        return "STABILIZING"
    return "INTEGRATED"


def clinical_coverage_gap(practice):
    return integration_posture(practice) == "FROZEN"


# ----------------------------------------------------------------- employment


def credentialing_rollup(employment):
    """PRD 3.4 dimension B. SUSPENDED rows count as neither approved nor pending."""
    rows = enrollments_of_employment(employment["id"])
    if not rows:
        return "PENDING"
    statuses = [row["status"] for row in rows]
    if any(status == "DENIED" for status in statuses):
        return "DENIED"
    if all(status == "APPROVED" for status in statuses):
        return "APPROVED"
    if any(status == "SUBMITTED" for status in statuses):
        return "SUBMITTED"
    return "PENDING"


# ------------------------------------------------------------------ agreement


def line_item_count(agreement):
    return len(line_items_of_agreement(agreement["id"]))


# ------------------------------------------------------------------- contract


def fee_schedule_item_count(contract):
    return len(fee_items_of_contract(contract["id"]))


def enrollment_open_count(contract):
    return sum(
        1
        for row in enrollments_of_contract(contract["id"])
        if row["status"] in ("NOT_STARTED", "SUBMITTED")
    )


def blended_impact_cents(contract):
    """Plain sum of the stored per-line impacts; null until a line exists."""
    items = fee_items_of_contract(contract["id"])
    if not items:
        return None
    return sum(item["line_impact_cents"] for item in items)


def contract_has_approved_enrollment(contract):
    return any(
        row["status"] == "APPROVED" for row in enrollments_of_contract(contract["id"])
    )


# ---------------------------------------------------------------------- batch


def records_pending(batch):
    return batch["records_total"] - batch["records_validated"] - batch["records_quarantined"]


# --------------------------------------------------------------- enrollment


def lead_days(enrollment):
    if enrollment["submitted_at"] is None or enrollment["effective_date"] is None:
        return None
    return clock.whole_days_between(
        enrollment["submitted_at"], enrollment["effective_date"]
    )


# ------------------------------------------------------------- serialization


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = clock.to_iso(row["created_at"])
    if "updated_at" in row:
        out["updated_at"] = clock.to_iso(row["updated_at"])
    if "version" in row:
        out["version"] = row["version"]
    return out


def affiliation(row):
    return _common(
        row,
        {
            "seller_group_name": row["seller_group_name"],
            "status": row["status"],
            "purchase_price_cents": row["purchase_price_cents"],
            "earnout_pool_cents": row["earnout_pool_cents"],
            "earnout_reserved_cents": earnout_reserved_cents(row),
            "earnout_settled_cents": earnout_settled_cents(row),
            "earnout_unallocated_cents": earnout_unallocated_cents(row),
            "baseline_ebitda_cents": row["baseline_ebitda_cents"],
            "baseline_net_collections_cents": row["baseline_net_collections_cents"],
            "earnout_measurement_state": row["earnout_measurement_state"],
            "repricing_round": row["repricing_round"],
            "post_close_doctor_term_months": row["post_close_doctor_term_months"],
            "practice_count": practice_count(row),
            "diligence_opened_at": clock.to_iso_instant(row["diligence_opened_at"]),
            "signed_date": clock.to_iso_instant(row["signed_date"]),
            "close_date": clock.to_iso_instant(row["close_date"]),
        },
    )


def conversion_vendor(row):
    return _common(
        row,
        {
            "name": row["name"],
            "max_concurrent_windows": row["max_concurrent_windows"],
            "active_window_count": active_window_count(row),
        },
    )


def practice(row):
    return _common(
        row,
        {
            "affiliation_id": row["affiliation_id"],
            "conversion_vendor_id": row["conversion_vendor_id"],
            "name": row["name"],
            "state_code": row["state_code"],
            "charts_total_expected": row["charts_total_expected"],
            "affiliation_status": row["affiliation_status"],
            "integration_posture": integration_posture(row),
            "staffing_model_state": row["staffing_model_state"],
            "fte_hygiene_ratio_bps": row["fte_hygiene_ratio_bps"],
            "active_doctor_count": active_doctor_count(row),
            "charts_migrated_count": charts_migrated_count(row),
            "pending_credentialing_count": pending_credentialing_count(row),
            "denied_enrollment_count": denied_enrollment_count(row),
            "quarantined_batch_count": quarantined_batch_count(row),
            "clinical_coverage_gap": clinical_coverage_gap(row),
        },
    )


def doctor(row):
    return _common(
        row,
        {
            "full_name": row["full_name"],
            "npi": row["npi"],
            "license_number": row["license_number"],
            "license_state": row["license_state"],
            "is_seller_owner": row["is_seller_owner"],
            "specialty": row["specialty"],
        },
    )


def doctor_employment(row):
    return _common(
        row,
        {
            "practice_id": row["practice_id"],
            "doctor_id": row["doctor_id"],
            "employment_status": row["employment_status"],
            "credentialing_status": row["credentialing_status"],
            "records_custody_state": row["records_custody_state"],
            "non_compete_enforcement_state": row["non_compete_enforcement_state"],
            "base_salary_monthly_cents": row["base_salary_monthly_cents"],
            "collections_pct_bps": row["collections_pct_bps"],
            "comp_model": row["comp_model"],
            "legacy_annual_comp_cents": row["legacy_annual_comp_cents"],
            "harmonized_annual_comp_cents": row["harmonized_annual_comp_cents"],
            "harmonization_delta_cents": row["harmonization_delta_cents"],
            "is_harmonized": row["is_harmonized"],
            "post_close_term_months": row["post_close_term_months"],
            "non_compete_months": row["non_compete_months"],
            "non_compete_radius_miles": row["non_compete_radius_miles"],
            "non_compete_end_date": clock.to_iso_instant(row["non_compete_end_date"]),
            "offer_accepted": row["offer_accepted"],
            "comp_effective_date": clock.to_iso_instant(row["comp_effective_date"]),
            "separation_date": clock.to_iso_instant(row["separation_date"]),
            "separation_reason": row["separation_reason"],
        },
    )


def service_agreement(row):
    return _common(
        row,
        {
            "practice_id": row["practice_id"],
            "status": row["status"],
            "fee_model": row["fee_model"],
            "mgmt_fee_bps": row["mgmt_fee_bps"],
            "scope_findings_count": row["scope_findings_count"],
            "review_round": row["review_round"],
            "line_item_count": line_item_count(row),
            "effective_date": clock.to_iso_instant(row["effective_date"]),
        },
    )


def service_line_item(row):
    return {
        "id": row["id"],
        "service_agreement_id": row["service_agreement_id"],
        "service_code": row["service_code"],
        "service_domain": row["service_domain"],
        "is_clinical": row["is_clinical"],
        "monthly_fee_cents": row["monthly_fee_cents"],
        "created_at": clock.to_iso(row["created_at"]),
    }


def migration_batch(row):
    return _common(
        row,
        {
            "practice_id": row["practice_id"],
            "batch_label": row["batch_label"],
            "records_total": row["records_total"],
            "records_validated": row["records_validated"],
            "records_quarantined": row["records_quarantined"],
            "records_pending": records_pending(row),
            "status": row["status"],
            "cutover_start_at": clock.to_iso_instant(row["cutover_start_at"]),
            "cutover_end_at": clock.to_iso_instant(row["cutover_end_at"]),
            "validation_error_rate_bps": row["validation_error_rate_bps"],
            "remediation_round": row["remediation_round"],
        },
    )


def payer_contract(row):
    return _common(
        row,
        {
            "practice_id": row["practice_id"],
            "payer_name": row["payer_name"],
            "transition_state": row["transition_state"],
            "dso_schedule_effective_date": clock.to_iso_instant(
                row["dso_schedule_effective_date"]
            ),
            "blended_impact_cents": blended_impact_cents(row),
            "fee_schedule_item_count": fee_schedule_item_count(row),
            "enrollment_open_count": enrollment_open_count(row),
            "erosion_override_ack": row["erosion_override_ack"],
        },
    )


def fee_schedule_item(row):
    return {
        "id": row["id"],
        "payer_contract_id": row["payer_contract_id"],
        "procedure_code": row["procedure_code"],
        "legacy_allowed_cents": row["legacy_allowed_cents"],
        "dso_allowed_cents": row["dso_allowed_cents"],
        "annual_volume": row["annual_volume"],
        "line_impact_cents": row["line_impact_cents"],
        "created_at": clock.to_iso(row["created_at"]),
    }


def payer_enrollment(row):
    return _common(
        row,
        {
            "payer_contract_id": row["payer_contract_id"],
            "doctor_employment_id": row["doctor_employment_id"],
            "status": row["status"],
            "effective_date": clock.to_iso_instant(row["effective_date"]),
            "term_date": clock.to_iso_instant(row["term_date"]),
            "submitted_at": clock.to_iso_instant(row["submitted_at"]),
            "decided_at": clock.to_iso_instant(row["decided_at"]),
            "lead_days": lead_days(row),
            "denial_reason": row["denial_reason"],
            "submission_round": row["submission_round"],
        },
    )


def earnout_tranche(row):
    return _common(
        row,
        {
            "affiliation_id": row["affiliation_id"],
            "period_label": row["period_label"],
            "measurement_start": clock.to_iso_instant(row["measurement_start"]),
            "measurement_end": clock.to_iso_instant(row["measurement_end"]),
            "status": row["status"],
            "variant_applied": row["variant_applied"],
            "reported_net_collections_cents": row["reported_net_collections_cents"],
            "reported_expenses_cents": row["reported_expenses_cents"],
            "annualized_net_collections_cents": row["annualized_net_collections_cents"],
            "annualized_expenses_cents": row["annualized_expenses_cents"],
            "final_net_collections_cents": row["final_net_collections_cents"],
            "final_expenses_cents": row["final_expenses_cents"],
            "lag_holdback_cents": row["lag_holdback_cents"],
            "management_fee_cents": row["management_fee_cents"],
            "adjusted_ebitda_cents": row["adjusted_ebitda_cents"],
            "growth_bps": row["growth_bps"],
            "multiple_bps": row["multiple_bps"],
            "reserved_cents": row["reserved_cents"],
            "awarded_cents": row["awarded_cents"],
            "clawed_back_cents": row["clawed_back_cents"],
            "reserved_by_user_id": row["reserved_by_user_id"],
            "settled_by_user_id": row["settled_by_user_id"],
        },
    )


def supply_preference_exception(row):
    return _common(
        row,
        {
            "doctor_employment_id": row["doctor_employment_id"],
            "vendor_category": row["vendor_category"],
            "item_code": row["item_code"],
            "annual_qty": row["annual_qty"],
            "formulary_unit_cents": row["formulary_unit_cents"],
            "preferred_unit_cents": row["preferred_unit_cents"],
            "clinical_rationale": row["clinical_rationale"],
            "status": row["status"],
            "incremental_cost_cents": row["incremental_cost_cents"],
            "decided_by_doctor_id": row["decided_by_doctor_id"],
        },
    )


def vendor_consolidation(row):
    return _common(
        row,
        {
            "practice_id": row["practice_id"],
            "vendor_category": row["vendor_category"],
            "baseline_annual_spend_cents": row["baseline_annual_spend_cents"],
            "formulary_annual_spend_cents": row["formulary_annual_spend_cents"],
            "status": row["status"],
            "gross_savings_cents": row["gross_savings_cents"],
            "exception_leakage_cents": row["exception_leakage_cents"],
            "projected_savings_cents": row["projected_savings_cents"],
            "exception_count_applied": row["exception_count_applied"],
        },
    )


def clinical_quality_review(row):
    return _common(
        row,
        {
            "doctor_employment_id": row["doctor_employment_id"],
            "period_label": row["period_label"],
            "charts_sampled": row["charts_sampled"],
            "charts_with_findings": row["charts_with_findings"],
            "treatment_plan_overrides": row["treatment_plan_overrides"],
            "status": row["status"],
            "finding_rate_bps": row["finding_rate_bps"],
            "override_rate_bps": row["override_rate_bps"],
            "score_bps": row["score_bps"],
            "closed_by_doctor_id": row["closed_by_doctor_id"],
            "outcome_note": row["outcome_note"],
        },
    )


SERIALIZERS = {
    "affiliations": affiliation,
    "conversion_vendors": conversion_vendor,
    "practices": practice,
    "doctors": doctor,
    "doctor_employments": doctor_employment,
    "service_agreements": service_agreement,
    "service_line_items": service_line_item,
    "migration_batches": migration_batch,
    "payer_contracts": payer_contract,
    "fee_schedule_items": fee_schedule_item,
    "payer_enrollments": payer_enrollment,
    "earnout_tranches": earnout_tranche,
    "supply_preference_exceptions": supply_preference_exception,
    "vendor_consolidations": vendor_consolidation,
    "clinical_quality_reviews": clinical_quality_review,
}


def serialize(kind, row):
    return SERIALIZERS[kind](row)


def serialize_many(kind, rows):
    return [SERIALIZERS[kind](row) for row in rows]


# ------------------------------------------------- derived-state fingerprints

DERIVED_KINDS = (
    "affiliations",
    "conversion_vendors",
    "practices",
    "service_agreements",
    "payer_contracts",
    "migration_batches",
    "doctor_employments",
)


def fingerprint(kind, row):
    """The derived surface of a row; a change here is a mutation of the row."""
    if kind == "affiliations":
        return (
            practice_count(row),
            earnout_reserved_cents(row),
            earnout_settled_cents(row),
            earnout_unallocated_cents(row),
        )
    if kind == "conversion_vendors":
        return (active_window_count(row),)
    if kind == "practices":
        return (
            active_doctor_count(row),
            charts_migrated_count(row),
            pending_credentialing_count(row),
            denied_enrollment_count(row),
            quarantined_batch_count(row),
            integration_posture(row),
            clinical_coverage_gap(row),
        )
    if kind == "service_agreements":
        return (line_item_count(row),)
    if kind == "payer_contracts":
        return (
            fee_schedule_item_count(row),
            enrollment_open_count(row),
            blended_impact_cents(row),
        )
    if kind == "migration_batches":
        return (records_pending(row),)
    if kind == "doctor_employments":
        return (credentialing_rollup(row),)
    return ()
