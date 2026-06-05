"""Breadth tests for entity CRUD, defaults, computed/system fields, and FK
integrity (queue B — Corner, section entities).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    NON_EXISTENT_UUID,
    ApiErrorId,
)
from test_helpers import fixtures as fx


# ==========================================================================
# Corner/entities/create_supplier_returns_201_defaults_applied
# ==========================================================================
def test_create_supplier_returns_201_with_pristine_defaults(api):
    """PRD 3.1: "A freshly created supplier starts in a pristine quality posture:
    its quality_rating is 100.00, its approval_status is APPROVED, and all of its
    computed counters — open_scar_count, lots_inspected, lots_rejected, and
    ncrs_attributed — are zero."

    Design: Corner/entities/create_supplier_returns_201_defaults_applied
    """
    resp = api.create_supplier({"name": "Acme Parts", "code": fx.f._unique_code("ACME")},
                               fx.TEST_USERS["manager_headers"])
    data = validate_success(resp, 201)
    assert data["quality_rating"] == pytest.approx(100.00, abs=0.001)
    assert data["approval_status"] == "APPROVED"
    assert data["open_scar_count"] == 0
    assert data["lots_inspected"] == 0
    assert data["lots_rejected"] == 0
    assert data["ncrs_attributed"] == 0
    assert data["version"] == 1


# ==========================================================================
# Corner/entities/create_ncr_returns_201_in_draft
# ==========================================================================
def test_create_ncr_returns_201_in_draft_with_stamp(api):
    """PRD 3.2: "Raising one creates a NonconformanceReport in DRAFT status with
    its created_by_personnel_id stamped to the acting engineer's X-User-ID and
    its budget_reserved_cents at 0."

    Design: Corner/entities/create_ncr_returns_201_in_draft
    """
    eng = fx.create_engineer()
    sup = fx.create_supplier()
    resp = api.create_ncr(
        {"title": "Bent flange", "source": "SUPPLIER", "severity": "MAJOR", "defect_qty": 3,
         "unit_cost_cents": 500, "part_number": "P-NCR", "supplier_id": sup["id"]},
        fx.make_engineer_headers(eng["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["disposition"] is None
    assert data["budget_reserved_cents"] == 0
    assert data["created_by_personnel_id"] == eng["id"]


# ==========================================================================
# Corner/entities/get_supplier_returns_stored_entity
# ==========================================================================
def test_get_supplier_returns_stored_code(api):
    """PRD 2.4: "Every resource carries a server-minted id that is a UUID with no
    type prefix, and a created_at timestamp formatted as an ISO 8601 UTC instant
    with three fractional digits."
    PRD 3.1: "A QualityManager also registers each Supplier by supplying a legal
    name and a short code that is unique across suppliers."

    Design: Corner/entities/get_supplier_returns_stored_entity
    """
    code = fx.f._unique_code("GET")
    created = fx.create_supplier(code=code)
    data = validate_success(api.get_supplier(created["id"], fx.TEST_USERS["manager_headers"]))
    assert data["code"] == code
    assert is_valid_uuid(data["id"])


# ==========================================================================
# Corner/entities/list_ncrs_paginated_envelope
# ==========================================================================
def test_list_ncrs_paginated_envelope(api):
    """PRD 2.3: "The pagination fields limit, offset, total_count, and has_more
    are reported in the meta object of a list response, where total_count is the
    total number of records matching the query before pagination and has_more
    indicates whether records remain beyond the returned page."

    Design: Corner/entities/list_ncrs_paginated_envelope
    """
    eng = fx.create_engineer()
    sup = fx.create_supplier()
    fx.create_draft_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=1,
                        unit_cost_cents=100, part_number="P-L")
    fx.create_draft_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=1,
                        unit_cost_cents=100, part_number="P-L")
    resp = api.list_ncrs(fx.TEST_USERS["manager_headers"], params={"supplier_id": sup["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ==========================================================================
# Corner/entities/get_supplier_nonexistent_id_not_found
# ==========================================================================
def test_get_supplier_nonexistent_id_not_found(api):
    """PRD 2.6: "the parent resource named earlier in the path must exist before
    the nested collection is considered, and a missing resource at any position
    yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_supplier_nonexistent_id_not_found
    """
    resp = api.get_supplier(NON_EXISTENT_UUID, fx.TEST_USERS["manager_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


# ==========================================================================
# Corner/entities/create_ncr_missing_severity_invalid_request
# ==========================================================================
def test_create_ncr_missing_severity_invalid_request(api):
    """PRD 2.10: "Then the body itself is checked for well-formedness — required
    fields present, enum values in range, and constrained integers non-negative —
    yielding ERR_INVALID_REQUEST."
    PRD 3.2: "The payload supplies a title, a source of SUPPLIER, INTERNAL, or
    AUDIT, a severity of CRITICAL, MAJOR, or MINOR, a defect_qty that must be at
    least 1, a unit_cost_cents that must be zero or greater, and a part_number."

    Design: Corner/entities/create_ncr_missing_severity_invalid_request
    """
    eng = fx.create_engineer()
    sup = fx.create_supplier()
    resp = api.create_ncr(
        {"title": "no severity", "source": "SUPPLIER", "defect_qty": 1, "unit_cost_cents": 100,
         "part_number": "P-RQ", "supplier_id": sup["id"]},
        fx.make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


# ==========================================================================
# Corner/entities/create_inspection_plan_default_level_gii
# ==========================================================================
def test_create_inspection_plan_defaults(api):
    """PRD 3.1: "an optional inspection_level that defaults to GII and may also be
    GI or GIII. A new inspection plan begins in NORMAL severity_mode (the
    alternative is TIGHTENED), with consecutive_rejects at 0 and needs_review
    false."

    Design: Corner/entities/create_inspection_plan_default_level_gii
    """
    cp = fx.create_control_plan()
    resp = api.create_inspection_plan(
        {"name": "IP Def", "control_plan_id": cp["id"], "part_number": "P-DEF",
         "lot_size": 120, "aql_pct": 4.0},
        fx.TEST_USERS["manager_headers"])
    data = validate_success(resp, 201)
    assert data["inspection_level"] == "GII"
    assert data["severity_mode"] == "NORMAL"
    assert data["consecutive_rejects"] == 0
    assert data["needs_review"] is False


# ==========================================================================
# Corner/entities/create_ncr_default_rework_hours_zero
# ==========================================================================
def test_create_ncr_default_rework_hours_zero(api):
    """PRD 3.2: "an optional rework_hours figure (the estimated labour hours to
    rework a single unit, defaulting to 0) feeds the later cost calculation."

    Design: Corner/entities/create_ncr_default_rework_hours_zero
    """
    eng = fx.create_engineer()
    sup = fx.create_supplier()
    resp = api.create_ncr(
        {"title": "no rework", "source": "SUPPLIER", "severity": "MAJOR", "defect_qty": 1,
         "unit_cost_cents": 100, "part_number": "P-DR", "supplier_id": sup["id"]},
        fx.make_engineer_headers(eng["id"]))
    data = validate_success(resp, 201)
    assert data["rework_hours"] == 0


# ==========================================================================
# Corner/entities/computed_ncr_cost_of_quality_rework_critical_ignores_client
# ==========================================================================
def test_cost_of_quality_rework_critical_computed_server_side(api):
    """PRD 3.3: "First, a per-unit labour figure is computed as the rework_hours
    multiplied by a labour rate of 6,000 cents per hour (that is, 60 dollars per
    hour), rounded half-up to whole cents."
    PRD 3.3: "Each per-unit base component is then multiplied by a severity
    multiplier — 1.5 when severity is CRITICAL, 1.0 when MAJOR, and 0.5 when
    MINOR — and that product is rounded half-up to whole cents to form the
    per-unit line."
    PRD 3.3: "The system computes cost_of_quality_cents and then re-reserves
    budget so that budget_reserved_cents equals the freshly computed cost of
    quality."

    Design: Corner/entities/computed_ncr_cost_of_quality_rework_critical_ignores_client
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="CRITICAL", defect_qty=2,
                             unit_cost_cents=1000, part_number="P-CF", rework_hours=1.0)
    disp = validate_success(api.disposition_ncr(ncr["id"], {"disposition": "REWORK"}, fx.make_manager_headers(mgr["id"])))
    # labour=round_half_up(1.0*6000)=6000; per-line=round_half_up(6000*1.5)=9000; *2 = 18000
    assert disp["disposition"] == "REWORK"
    assert disp["cost_of_quality_cents"] == 18000
    assert disp["budget_reserved_cents"] == 18000


# ==========================================================================
# Corner/entities/computed_budget_reserved_on_open_equals_qty_times_unit_cost
# ==========================================================================
def test_budget_reserved_on_open_equals_qty_times_unit_cost(api):
    """PRD 3.2: "At open time the system reserves budget against the quality
    reserve: the reserved figure, held in budget_reserved_cents, is the
    defect_qty multiplied by the unit_cost_cents, and that reservation stands as
    long as the report remains non-terminal."

    Design: Corner/entities/computed_budget_reserved_on_open_equals_qty_times_unit_cost
    """
    eng = fx.create_engineer()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=4,
                             unit_cost_cents=1000, part_number="P-BG")
    assert ncr["status"] == "OPEN"
    assert ncr["budget_reserved_cents"] == 4000


# ==========================================================================
# Corner/entities/system_fields_generated_on_supplier_create
# ==========================================================================
def test_system_fields_generated_on_supplier_create(api):
    """PRD 2.4: "an integer version that begins at 1 on creation and increments
    by one on every mutation that changes the resource."
    PRD 3.1: "A freshly created supplier starts in a pristine quality posture: its
    quality_rating is 100.00 ..."

    Design: Corner/entities/system_fields_generated_on_supplier_create
    """
    resp = api.create_supplier({"name": "Sys Co", "code": fx.f._unique_code("SYS")},
                               fx.TEST_USERS["manager_headers"])
    data = validate_success(resp, 201)
    assert data["version"] == 1
    assert data["quality_rating"] == pytest.approx(100.00, abs=0.001)
    assert is_valid_uuid(data["id"])


# ==========================================================================
# Corner/entities/create_ncr_invalid_source_enum_invalid_request
# ==========================================================================
def test_create_ncr_invalid_source_enum_invalid_request(api):
    """PRD 2.10: "Then the body itself is checked for well-formedness — required
    fields present, enum values in range, and constrained integers non-negative —
    yielding ERR_INVALID_REQUEST."
    PRD 3.2: "a source of SUPPLIER, INTERNAL, or AUDIT"

    Design: Corner/entities/create_ncr_invalid_source_enum_invalid_request
    """
    eng = fx.create_engineer()
    resp = api.create_ncr(
        {"title": "bad source", "source": "WHATEVER", "severity": "MAJOR", "defect_qty": 1,
         "unit_cost_cents": 100, "part_number": "P-EN"},
        fx.make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


# ==========================================================================
# Corner/entities/create_ncr_negative_defect_qty_invalid_request
# ==========================================================================
def test_create_ncr_zero_defect_qty_invalid_request(api):
    """PRD 3.2: "a defect_qty that must be at least 1"
    PRD 2.10: "the body itself is checked for well-formedness — required fields
    present, enum values in range, and constrained integers non-negative —
    yielding ERR_INVALID_REQUEST."

    Design: Corner/entities/create_ncr_negative_defect_qty_invalid_request
    """
    eng = fx.create_engineer()
    sup = fx.create_supplier()
    resp = api.create_ncr(
        {"title": "zero qty", "source": "SUPPLIER", "severity": "MAJOR", "defect_qty": 0,
         "unit_cost_cents": 100, "part_number": "P-NG", "supplier_id": sup["id"]},
        fx.make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


# ==========================================================================
# Corner/entities/eightdstep_is_immutable_no_version_field
# ==========================================================================
def test_eightdstep_has_no_version_field(api):
    """PRD 2.4: "There is one exception: the 8D step record carries only id and
    created_at — it has neither an updated_at nor a version, because a step is an
    append-only journal entry that is never mutated after it is recorded."
    PRD 3.4: "Step records are journal entries and are never edited once written."

    Design: Corner/entities/eightdstep_is_immutable_no_version_field
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_dispositioned_ncr(eng["id"], mgr["id"], supplier_id=sup["id"],
                                      disposition="REWORK", defect_qty=5, unit_cost_cents=1000,
                                      rework_hours=2.0, part_number="P-IM")
    capa = fx.open_capa(eng["id"], ncr["id"])
    resp = api.create_capa_step(capa["id"], {"discipline": "D1", "narrative": "team formed"},
                                fx.make_engineer_headers(eng["id"]))
    step = validate_success(resp, 201)
    assert step["discipline"] == "D1"
    assert step["capa_id"] == capa["id"]
    assert "version" not in step
    assert "updated_at" not in step
    listed, meta = validate_paginated(api.list_capa_steps(capa["id"], fx.make_engineer_headers(eng["id"])))
    assert len(listed) == 1


# ==========================================================================
# Corner/entities/create_capa_nonexistent_ncr_fk_not_found
# ==========================================================================
def test_create_capa_nonexistent_ncr_fk_not_found(api):
    """PRD 3.2: "Any foreign key supplied in the body must resolve to an existing
    resource of the right type, or the request fails with ERR_FK_NOT_FOUND (HTTP
    404)."

    Design: Corner/entities/create_capa_nonexistent_ncr_fk_not_found
    """
    eng = fx.create_engineer()
    resp = api.create_capa({"ncr_id": NON_EXISTENT_UUID, "title": "orphan capa"},
                           fx.make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value, 404)


# ==========================================================================
# Corner/entities/create_ncr_supplier_source_nonexistent_supplier_fk_not_found
# ==========================================================================
def test_create_ncr_nonexistent_supplier_fk_not_found(api):
    """PRD 3.2: "Any foreign key supplied in the body must resolve to an existing
    resource of the right type, or the request fails with ERR_FK_NOT_FOUND (HTTP
    404)."

    Design: Corner/entities/create_ncr_supplier_source_nonexistent_supplier_fk_not_found
    """
    eng = fx.create_engineer()
    resp = api.create_ncr(
        {"title": "orphan ncr", "source": "SUPPLIER", "severity": "MAJOR", "defect_qty": 1,
         "unit_cost_cents": 100, "part_number": "P-XF", "supplier_id": NON_EXISTENT_UUID},
        fx.make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value, 404)
