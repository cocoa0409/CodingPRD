"""Entity serializers — produce the public JSON shape for each resource.

Internal store dicts may carry helper keys (e.g. _risk_index) prefixed with an
underscore; serializers project only the PRD-declared fields.
"""

_COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(entity, fields):
    return {f: entity.get(f) for f in fields}


def gene(e):
    return _pick(e, _COMMON + ["symbol", "is_acmg_reportable", "status"])


def panel(e):
    return _pick(e, _COMMON + ["name", "list_price_cents", "requires_consent", "gene_count", "status"])


def panel_gene(e):
    return _pick(e, _COMMON + ["panel_id", "gene_id", "status"])


def provider(e):
    return _pick(e, _COMMON + ["npi", "full_name"])


def test_order(e):
    return _pick(e, _COMMON + [
        "patient_mrn", "patient_dob", "panel_id", "ordering_provider_id",
        "pipeline_status", "financial_status", "list_price_cents",
        "estimated_patient_responsibility_cents", "final_patient_responsibility_cents",
        "report_required_consent", "has_reportable_incidental", "cancel_reason",
    ])


def requisition(e):
    return _pick(e, _COMMON + ["test_order_id", "clinical_indication", "insurance_payer", "status"])


def consent(e):
    return _pick(e, _COMMON + ["test_order_id", "incidental_findings_opt_in", "signed_by_name", "status"])


def specimen(e):
    return _pick(e, _COMMON + [
        "test_order_id", "specimen_type", "collected_at", "received_at",
        "quantity_ng", "status", "superseded_by_specimen_id",
    ])


def variant(e):
    return _pick(e, _COMMON + [
        "test_order_id", "gene_id", "hgvs", "is_incidental",
        "classification", "classified_by_user_id",
    ])


def report(e):
    return _pick(e, _COMMON + [
        "test_order_id", "reportable_variant_ids", "incidental_disclosed",
        "signed_out_by_user_id", "amends_report_id", "status",
    ])


def billing(e):
    return _pick(e, _COMMON + [
        "test_order_id", "allowed_amount_cents", "coinsurance_collected_cents",
        "writeoff_cents", "status",
    ])


def sequencer(e):
    return _pick(e, _COMMON + ["instrument_name", "turnaround_buffer_minutes", "status"])


def sequencer_run(e):
    return _pick(e, _COMMON + [
        "sequencer_id", "test_order_id", "window_start", "window_end", "status",
    ])


def counselor(e):
    return _pick(e, _COMMON + ["counselor_name", "status"])


def referral(e):
    return _pick(e, _COMMON + [
        "test_order_id", "counselor_id", "triggering_variant_id", "reason",
        "slot_start", "slot_end", "status",
    ])


def clock(e):
    return {"current_utc": e.get("current_utc")}
