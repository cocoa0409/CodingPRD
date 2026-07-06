"""Entity creation, retrieval, listing, validation, and FK integrity.

Corner queue (B): section entities.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, assert_study, assert_panelist,
    assert_quota_cell, assert_consent,
    create_study, create_quota_cell, create_panelist, create_consent,
    create_fielding_study_with_cell,
)

RM = TEST_USERS["research_manager_headers"]
OPS = TEST_USERS["panel_ops_headers"]
FC = TEST_USERS["field_coordinator_headers"]


def test_create_study_returns_201_with_defaults(api):
    """PRD §3.1: "A new study begins in DRAFT with its computed quota totals
    target_total_n and committed_total_n both at zero".
    PRD §3.1: "The body may also set required_consent_version, the consent-form
    version a panelist must have accepted to take part; if omitted it defaults
    to 1".

    Design: Corner/entities/create_study_returns_201_with_defaults
    """
    data = validate_success(api.create_study(
        {"title": "S1", "irb_protocol_number": "IRB-001", "estimated_minutes": 12,
         "base_incentive_points": 80, "screener_min_age": 18}, RM), expected_status=201)
    assert_study(data)
    assert data["status"] == "DRAFT"
    assert data["target_total_n"] == 0 and data["committed_total_n"] == 0
    assert data["required_consent_version"] == 1, \
        f"required_consent_version should default to 1, got {data['required_consent_version']}"


def test_create_panelist_returns_201_active_zeroed(api):
    """PRD §3.2: "A newly registered panelist starts in ACTIVE status ... with a
    points_balance of zero, a health_score of 100, and lifetime counters
    lifetime_invited_n and lifetime_completed_n at zero".

    Design: Corner/entities/create_panelist_returns_201_active_zeroed
    """
    data = validate_success(api.create_panelist(
        {"email": "np@x.com", "full_name": "New P", "age": 25, "segment_key": "SEG_NP"},
        OPS), expected_status=201)
    assert_panelist(data)
    assert data["status"] == "ACTIVE"
    assert data["points_balance"] == 0 and data["health_score"] == 100
    assert data["lifetime_invited_n"] == 0 and data["lifetime_completed_n"] == 0


def test_get_study_recomputes_quota_totals(api):
    """PRD §2.7: "target_total_n is the sum of target_n across the study's cells
    ... both are recomputed when a study is read or launched."

    Design: Corner/entities/get_study_recomputes_quota_totals
    """
    study = create_study(base_incentive_points=50, estimated_minutes=10, screener_min_age=0)
    create_quota_cell(study["id"], segment_key="SEG_GS", target_n=5)

    data = validate_success(api.get_study(study["id"], RM))
    assert data["target_total_n"] == 5, f"expected target_total_n 5, got {data['target_total_n']}"
    assert data["committed_total_n"] == 0


def test_list_panelists_paginated_envelope(api):
    """PRD §2.3: "The meta block of a list response reports limit, offset,
    total_count (the total number of records matching the query before the
    pagination window is applied), and has_more (true when records remain beyond
    the current window)."
    PRD §2.2: "The response_type is either 'object' for a single resource or
    'array' for a list of resources."

    Design: Corner/entities/list_panelists_paginated_envelope
    """
    create_panelist(email="l1@x.com", segment_key="SEG_L")
    create_panelist(email="l2@x.com", segment_key="SEG_L")

    data, meta = validate_paginated(api.list_panelists(OPS))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"default limit 10 >= 2, has_more should be False, got {meta['has_more']}"


def test_get_panelist_nonexistent_returns_not_found(api):
    """PRD §2.5: "If any referenced id — in the path or the request body — does
    not resolve to an existing entity, the request is rejected with ERR_NOT_FOUND
    (HTTP 404)."

    Design: Corner/entities/get_panelist_nonexistent_returns_not_found
    """
    validate_error(api.get_panelist(NON_EXISTENT_UUID, OPS), ApiErrorId.ERR_NOT_FOUND.value)


def test_create_study_missing_irb_returns_validation(api):
    """PRD §2.5: "Malformed bodies — a missing required field, a wrong type, or an
    enum value outside the allowed set — are rejected with ERR_VALIDATION
    (HTTP 400)."
    PRD §3.1: "A ResearchManager opens the lifecycle by creating a Study,
    supplying its title, its irb_protocol_number ... ".

    Design: Corner/entities/create_study_missing_irb_returns_validation
    """
    validate_error(api.create_study(
        {"title": "NoIrb", "estimated_minutes": 10, "base_incentive_points": 50,
         "screener_min_age": 0}, RM), ApiErrorId.ERR_VALIDATION.value)


def test_create_quota_cell_computed_counts_input_ignored(api):
    """PRD §3.1: "A cell is born with reserved_n and committed_n at zero,
    available_n equal to its target, and fill_status of OPEN."

    Design: Corner/entities/create_quota_cell_computed_counts_input_ignored
    """
    study = create_study(base_incentive_points=50, estimated_minutes=10, screener_min_age=0)
    data = validate_success(api.create_quota_cell(
        study["id"], {"segment_key": "SEG_QC", "target_n": 3}, RM), expected_status=201)
    assert_quota_cell(data)
    assert data["reserved_n"] == 0 and data["committed_n"] == 0
    assert data["available_n"] == 3, f"available_n should equal target 3, got {data['available_n']}"
    assert data["fill_status"] == "OPEN"


def test_create_consent_invalid_decision_enum_returns_validation(api):
    """PRD §2.5: "an enum value outside the allowed set — are rejected with
    ERR_VALIDATION (HTTP 400)."
    PRD §3.2: "a decision of ACCEPTED, DECLINED, or WITHDRAWN."

    Design: Corner/entities/create_consent_invalid_decision_enum_returns_validation
    """
    study = create_study(base_incentive_points=50, estimated_minutes=10, screener_min_age=0)
    panelist = create_panelist(email="en@x.com", segment_key="SEG_EN")
    validate_error(api.create_consent(
        {"panelist_id": panelist["id"], "study_id": study["id"], "consent_version": 1,
         "decision": "MAYBE"}, OPS), ApiErrorId.ERR_VALIDATION.value)


def test_consent_is_immutable_audit_record(api):
    """PRD §2.4: "Consent and AttentionCheck are immutable audit records. They
    carry only id and created_at — they have no updated_at field and no version
    field, because once written they are never modified."
    PRD §3.2: "The server stamps recorded_at from the logical clock."

    Design: Corner/entities/consent_immutable_no_update_endpoint
    """
    study = create_study(base_incentive_points=50, estimated_minutes=10, screener_min_age=0)
    panelist = create_panelist(email="im@x.com", segment_key="SEG_IM")
    consent = create_consent(panelist["id"], study["id"])

    data = validate_success(api.get_consent(consent["id"], OPS))
    assert_consent(data)  # asserts absence of updated_at / version
    assert data["recorded_at"].startswith("2026-03-01"), \
        f"recorded_at should be stamped at the default clock, got {data['recorded_at']}"


def test_create_quota_cell_nonexistent_study_returns_not_found(api):
    """PRD §2.5: "the parent must resolve before the child is considered. If any
    referenced id ... does not resolve to an existing entity, the request is
    rejected with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/create_quota_cell_nonexistent_study_returns_not_found
    """
    validate_error(api.create_quota_cell(
        NON_EXISTENT_UUID, {"segment_key": "SEG_X", "target_n": 2}, RM),
        ApiErrorId.ERR_NOT_FOUND.value)


def test_create_participation_nonexistent_quota_cell_returns_not_found(api):
    """PRD §2.5: "Foreign-key references inside request bodies (a study_id, a
    panelist_id, a quota_cell_id, a facility_id, a focus_group_id, a
    participation_id) are subject to the same existence check."

    Design: Corner/entities/create_participation_nonexistent_quota_cell_returns_not_found
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_FK")
    panelist = create_panelist(email="fk@x.com", segment_key="SEG_FK")
    validate_error(api.create_participation(
        {"study_id": study["id"], "panelist_id": panelist["id"],
         "quota_cell_id": NON_EXISTENT_UUID}, FC), ApiErrorId.ERR_NOT_FOUND.value)
