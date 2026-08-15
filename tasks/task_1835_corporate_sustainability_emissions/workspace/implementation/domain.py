"""Entity serializers — emit only the public fields defined by the scaffold."""


def _pick(ent, fields):
    return {k: ent.get(k) for k in fields}


def ser_site(s):
    return _pick(s, (
        "id", "name", "country_code", "grid_region_code", "status",
        "created_at", "updated_at", "version",
    ))


def ser_factor(f):
    return _pick(f, (
        "id", "scope_category", "region_code", "unit", "value_tco2e_per_unit",
        "library_version", "valid_from", "valid_to", "status",
        "created_at", "updated_at", "version",
    ))


def ser_cycle(c):
    return _pick(c, (
        "id", "name", "reporting_year", "status", "readiness_pct",
        "pinned_library_version", "assurance_statement",
        "created_at", "updated_at", "version",
    ))


def ser_record(r):
    return _pick(r, (
        "id", "cycle_id", "site_id", "factor_id", "activity_type", "quantity",
        "unit", "period_start", "period_end", "status", "submitted_by_user_id",
        "reviewed_by_user_id", "reject_reason", "factor_value_snapshot", "tco2e",
        "created_at", "updated_at", "version",
    ))


def ser_evidence(e):
    return _pick(e, (
        "id", "activity_record_id", "supersedes_evidence_id", "file_name",
        "sha256_hex", "status", "uploaded_by_user_id", "verified_by_user_id",
        "retention_until", "created_at", "updated_at", "version",
    ))


def ser_inventory(inv):
    return _pick(inv, (
        "id", "cycle_id", "status", "scope1_tco2e", "scope2_location_tco2e",
        "scope2_market_tco2e", "scope3_tco2e", "scope3_provisional_tco2e",
        "total_tco2e", "computed_at", "created_at", "updated_at", "version",
    ))


def ser_engagement(e):
    return _pick(e, (
        "id", "cycle_id", "supplier_name", "category", "spend_usd",
        "contact_user_id", "due_date", "status", "round", "supplier_tco2e",
        "responded_at", "created_at", "updated_at", "version",
    ))


def ser_target(t):
    return _pick(t, (
        "id", "name", "base_year", "target_year", "reduction_pct",
        "scope_coverage", "base_year_total_tco2e", "baseline_source",
        "baseline_shift_pct", "baseline_shift_significant", "status",
        "trajectory_status", "created_at", "updated_at", "version",
    ))


def ser_instrument(i):
    return _pick(i, (
        "id", "registry", "serial_number", "technology", "vintage_year",
        "quantity_mwh", "status", "retired_for_cycle_id", "retired_for_site_id",
        "created_at", "updated_at", "version",
    ))


def ser_questionnaire(q):
    return _pick(q, (
        "id", "cycle_id", "framework", "prepared_by_user_id", "sections",
        "completeness_pct", "emissions_section_stale", "status",
        "review_decision_by", "review_notes",
        "created_at", "updated_at", "version",
    ))
