"""Study opening, scoping terms, fee-cap boundary, and temporal-overlap conflicts.

Translates queue A (resource_temporal_overlap, boundary fee cap, cross_entity active-client)
and queue B (scope missing fee terms, version increment on scope) instances.
"""
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS, fixtures
import test_helpers.factories as f

SM = TEST_USERS["study_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/study_create_requires_active_client
# ---------------------------------------------------------------------------
def test_study_create_on_onboarding_client_rejected(api):
    """PRD §3.2: "A study opened for a client that is not ACTIVE is rejected with
    ERR_CLIENT_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/study_create_requires_active_client
    """
    cli = fixtures.create_client(api, active=False)  # left ONBOARDING
    resp = api.create_study(f.create_study_payload(cli["id"], "COST_SEGREGATION", tax_year=2024), SM)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_ACTIVE.value)


def test_study_create_succeeds_once_client_active(api):
    """PRD §3.1: "A study cannot be opened for a client until a StudyManager activates it,
    moving status from ONBOARDING to ACTIVE; only then is the client eligible to own studies."

    Design: Difficulty/cross_entity_state_dependency/study_create_requires_active_client
    """
    cli = fixtures.create_client(api, active=True)
    resp = api.create_study(f.create_study_payload(cli["id"], "COST_SEGREGATION", tax_year=2024), SM)
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/fee_percent_bps_at_cap_boundary
# ---------------------------------------------------------------------------
def test_fee_percent_bps_at_cap_accepted(api):
    """PRD §3.2: "A percent fee whose fee_percent_bps exceeds 3,000 basis points (that is,
    thirty percent of the realized benefit) is rejected with ERR_FEE_PERCENT_TOO_HIGH."

    Exactly 3000 does not exceed the cap → accepted, study advances to SCOPING.

    Design: Difficulty/boundary_precision_check/fee_percent_bps_at_cap_boundary
    """
    cli = fixtures.create_client(api)
    prop = fixtures.create_property(api, cli["id"])
    st = fixtures.create_study(api, cli["id"], "COST_SEGREGATION", tax_year=2024)
    resp = api.scope_study(st["id"],
                           {"fee_type": "PERCENT", "fee_percent_bps": 3000, "property_id": prop["id"]}, SM)
    data = validate_success(resp, 200)
    assert data["status"] == "SCOPING"
    assert data["fee_percent_bps"] == 3000


def test_fee_percent_bps_above_cap_rejected(api):
    """PRD §3.2: "A percent fee whose fee_percent_bps exceeds 3,000 basis points (that is,
    thirty percent of the realized benefit) is rejected with ERR_FEE_PERCENT_TOO_HIGH."

    Design: Difficulty/boundary_precision_check/fee_percent_bps_at_cap_boundary
    """
    cli = fixtures.create_client(api)
    prop = fixtures.create_property(api, cli["id"])
    st = fixtures.create_study(api, cli["id"], "COST_SEGREGATION", tax_year=2024)
    resp = api.scope_study(st["id"],
                           {"fee_type": "PERCENT", "fee_percent_bps": 3001, "property_id": prop["id"]}, SM)
    validate_error(resp, ApiErrorId.ERR_FEE_PERCENT_TOO_HIGH.value)


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/property_cost_seg_same_tax_year_overlap
# ---------------------------------------------------------------------------
def test_second_cost_seg_same_property_same_year_rejected(api):
    """PRD §3.2: "It is rejected with ERR_PROPERTY_STUDY_OVERLAP if any other non-CANCELLED
    cost-segregation study already exists for that same property with the same tax_year."

    Design: Difficulty/resource_temporal_overlap/property_cost_seg_same_tax_year_overlap
    """
    cli = fixtures.create_client(api)
    prop = fixtures.create_property(api, cli["id"])
    sa = fixtures.create_study(api, cli["id"], "COST_SEGREGATION", tax_year=2024)
    get_success_data(api.scope_study(sa["id"], f.scope_cost_seg_payload(prop["id"]), SM))
    sb = fixtures.create_study(api, cli["id"], "COST_SEGREGATION", tax_year=2024)
    resp = api.scope_study(sb["id"], f.scope_cost_seg_payload(prop["id"]), SM)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_STUDY_OVERLAP.value)


def test_second_cost_seg_different_year_allowed(api):
    """PRD §3.2: "It is rejected with ERR_PROPERTY_STUDY_OVERLAP if any other non-CANCELLED
    cost-segregation study already exists for that same property with the same tax_year."

    A different tax_year is not the same year, so no overlap: the second scope succeeds.

    Design: Difficulty/resource_temporal_overlap/property_cost_seg_same_tax_year_overlap
    """
    cli = fixtures.create_client(api)
    prop = fixtures.create_property(api, cli["id"])
    sa = fixtures.create_study(api, cli["id"], "COST_SEGREGATION", tax_year=2024)
    get_success_data(api.scope_study(sa["id"], f.scope_cost_seg_payload(prop["id"]), SM))
    sb = fixtures.create_study(api, cli["id"], "COST_SEGREGATION", tax_year=2025)
    resp = api.scope_study(sb["id"], f.scope_cost_seg_payload(prop["id"]), SM)
    data = validate_success(resp, 200)
    assert data["status"] == "SCOPING"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/rd_base_period_window_overlap
# ---------------------------------------------------------------------------
def test_rd_overlapping_base_period_rejected(api):
    """PRD §3.2: "An R&D study is rejected with ERR_RD_BASE_PERIOD_OVERLAP if any other
    non-CANCELLED R&D study for the same client has a base period, spanning the three tax
    years up to but not including its own tax_year, that overlaps this study's base period."

    tax_year 2024 → base [2021,2024); tax_year 2025 → base [2022,2025); these overlap.

    Design: Difficulty/resource_temporal_overlap/rd_base_period_window_overlap
    """
    cli = fixtures.create_client(api)
    sa = fixtures.create_study(api, cli["id"], "RD_CREDIT", tax_year=2024)
    get_success_data(api.scope_study(sa["id"], f.scope_rd_payload("ASC"), SM))
    sb = fixtures.create_study(api, cli["id"], "RD_CREDIT", tax_year=2025)
    resp = api.scope_study(sb["id"], f.scope_rd_payload("ASC"), SM)
    validate_error(resp, ApiErrorId.ERR_RD_BASE_PERIOD_OVERLAP.value)


def test_rd_non_overlapping_base_period_allowed(api):
    """PRD §3.2: "An R&D study is rejected with ERR_RD_BASE_PERIOD_OVERLAP if any other
    non-CANCELLED R&D study for the same client has a base period, spanning the three tax
    years up to but not including its own tax_year, that overlaps this study's base period."

    tax_year 2024 → base [2021,2024); tax_year 2028 → base [2025,2028); disjoint → allowed.

    Design: Difficulty/resource_temporal_overlap/rd_base_period_window_overlap
    """
    cli = fixtures.create_client(api)
    sa = fixtures.create_study(api, cli["id"], "RD_CREDIT", tax_year=2024)
    get_success_data(api.scope_study(sa["id"], f.scope_rd_payload("ASC"), SM))
    sb = fixtures.create_study(api, cli["id"], "RD_CREDIT", tax_year=2028)
    resp = api.scope_study(sb["id"], f.scope_rd_payload("ASC"), SM)
    data = validate_success(resp, 200)
    assert data["status"] == "SCOPING"


# ---------------------------------------------------------------------------
# Corner/validations/scope_fixed_missing_fee_terms_rejected
# ---------------------------------------------------------------------------
def test_scope_fixed_missing_fee_terms_rejected(api):
    """PRD §3.2: "A scope request whose fee terms are incomplete — a fixed fee without its
    flat amount, or a percent fee without its basis points — is rejected with
    ERR_MISSING_FEE_TERMS."

    Design: Corner/validations/scope_fixed_missing_fee_terms_rejected
    """
    cli = fixtures.create_client(api)
    prop = fixtures.create_property(api, cli["id"])
    st = fixtures.create_study(api, cli["id"], "COST_SEGREGATION", tax_year=2024)
    resp = api.scope_study(st["id"], {"fee_type": "FIXED", "property_id": prop["id"]}, SM)
    validate_error(resp, ApiErrorId.ERR_MISSING_FEE_TERMS.value)


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/study_version_increments_on_scope_mutation
# ---------------------------------------------------------------------------
def test_study_version_increments_on_scope(api):
    """PRD §2.4: "a version, an integer that starts at 1 and increments by one on every
    mutation."

    A freshly created study is version 1; scoping it (a mutation) advances it to 2.

    Design: Corner/cross_cutting_complexity_layers/study_version_increments_on_scope_mutation
    """
    cli = fixtures.create_client(api)
    prop = fixtures.create_property(api, cli["id"])
    st = fixtures.create_study(api, cli["id"], "COST_SEGREGATION", tax_year=2024)
    assert st["version"] == 1
    resp = api.scope_study(st["id"], f.scope_cost_seg_payload(prop["id"]), SM)
    data = validate_success(resp, 200)
    assert data["version"] == 2
