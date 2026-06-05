"""Breadth tests for calculations (AQL lookup, COQ precision, supplier rating
bands, CAPA gate) and validation rules / precedence (queue B — Corner, sections
calculations + validations).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
)
from test_helpers import fixtures as fx


# ==========================================================================
# Corner/calculations/aql_sampling_code_letter_d_normal_correct_result
# ==========================================================================
def test_aql_code_letter_d_normal_lookup(api):
    """PRD 3.6: "For general level GII, the lot-size bands map as follows: 2
    through 8 gives code letter A; 9 through 15 gives B; 16 through 25 gives C; 26
    through 50 gives D; 51 through 90 gives E; 91 through 150 gives F; 151 through
    280 gives G; and 281 through 500 gives H."
    PRD 3.6: "at code letter D the sample size is 8 in every column with
    acceptance numbers of 0 at AQL 1.0, 0 at 2.5, and 1 at 4.0"
    PRD 3.6: "the rejection_number is the acceptance number plus one."

    Design: Corner/calculations/aql_sampling_code_letter_d_normal_correct_result
    """
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=40, aql_pct=2.5, inspection_level="GII")
    lot = fx.create_in_inspection_lot(inspector["id"], ip["id"], supplier["id"], actual_lot_size=40)
    assert lot["sample_size"] == 8
    assert lot["acceptance_number"] == 0
    assert lot["rejection_number"] == 1
    assert lot["severity_mode_used"] == "NORMAL"


# ==========================================================================
# Corner/calculations/aql_sampling_uses_plan_lot_size_not_actual
# ==========================================================================
def test_aql_uses_plan_lot_size_not_actual_lot_size(api):
    """PRD 3.6: "First a sample-size code letter is fixed from the plan's
    inspection_level and the plan's nominal lot_size — note that the code letter
    is driven by the plan's lot_size, not by the lot's actual_lot_size."
    PRD 3.6: "at code letter E the sample size is 13 with acceptance numbers 0, 1,
    and 1"

    Design: Corner/calculations/aql_sampling_uses_plan_lot_size_not_actual
    """
    # plan lot_size=60 -> band 51..90 -> letter E; aql 1.0 -> (E,1.0)={n:13,Ac:0}
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=60, aql_pct=1.0, inspection_level="GII")
    lot = fx.create_in_inspection_lot(inspector["id"], ip["id"], supplier["id"], actual_lot_size=300)
    assert lot["sample_size"] == 13
    assert lot["acceptance_number"] == 0


# ==========================================================================
# Corner/calculations/ncr_cost_of_quality_use_as_is_concession_precision
# ==========================================================================
def test_cost_of_quality_use_as_is_concession_precision(api):
    """PRD 3.3: "for USE_AS_IS, the base component is the unit_cost_cents
    multiplied by a concession factor of 0.30 and rounded half-up to whole cents,
    representing the negotiated write-down"
    PRD 3.3: "Each per-unit base component is then multiplied by a severity
    multiplier — 1.5 when severity is CRITICAL, 1.0 when MAJOR, and 0.5 when
    MINOR — and that product is rounded half-up to whole cents to form the
    per-unit line."

    Design: Corner/calculations/ncr_cost_of_quality_use_as_is_concession_precision
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    fx.set_clock("2026-06-15T00:00:00Z")
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=3,
                             unit_cost_cents=1000, part_number="P-PC")
    fx.approved_deviation(eng["id"], mgr["id"], ncr["id"], sup["id"], "P-PC",
                          valid_from="2026-06-01T00:00:00Z", valid_to="2026-12-01T00:00:00Z", max_qty=5)
    disp = validate_success(api.disposition_ncr(ncr["id"], {"disposition": "USE_AS_IS"}, fx.make_manager_headers(mgr["id"])))
    # round_half_up(1000*0.30)=300; per-line=round_half_up(300*0.5)=150; *3 = 450
    assert disp["disposition"] == "USE_AS_IS"
    assert disp["cost_of_quality_cents"] == 450


# ==========================================================================
# Corner/calculations/supplier_rating_excludes_pending_and_in_inspection_lots
# ==========================================================================
def test_supplier_rating_excludes_pending_lots(api):
    """PRD 3.6: "Dispositioning the lot moves it from IN_INSPECTION to a terminal
    state ... the lot is ACCEPTED: this increments the supplier's lots_inspected
    ..."
    PRD 3.7: "The lot factor rewards a clean acceptance history: if lots_inspected
    is zero it is 1.0, otherwise it is one minus the ratio of lots_rejected to
    lots_inspected, with the result floored at 0.0."

    Design: Corner/calculations/supplier_rating_excludes_pending_and_in_inspection_lots
    """
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII")
    fx.run_lot(inspector["id"], ip["id"], supplier["id"], defects_found=0)  # ACCEPTED
    fx.create_pending_lot(inspector["id"], ip["id"], supplier["id"])         # PENDING, not counted
    s = validate_success(api.get_supplier(supplier["id"], fx.TEST_USERS["manager_headers"]))
    assert s["lots_inspected"] == 1
    assert s["lots_rejected"] == 0
    assert s["quality_rating"] == pytest.approx(100.00, abs=0.001)


# ==========================================================================
# Corner/calculations/supplier_rating_band_disqualified_below_probation_at
# ==========================================================================
def test_supplier_rating_band_disqualified(api):
    """PRD 3.7: "a rating below 50.00 yields DISQUALIFIED. Both thresholds are
    inclusive at their lower bound."
    PRD 3.7: "The base score weights the lot factor at 0.6 and the nonconformance
    factor at 0.4 (the two weights sum to 1.0) ..."

    Design: Corner/calculations/supplier_rating_band_disqualified_below_probation_at
    """
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII")
    fx.run_lot(inspector["id"], ip["id"], supplier["id"], defects_found=3)  # REJECTED
    s = validate_success(api.get_supplier(supplier["id"], fx.TEST_USERS["manager_headers"]))
    # lot_factor=0, base=0.6*0+0.4*1=0.4 -> 40.00 -> DISQUALIFIED
    assert s["quality_rating"] == pytest.approx(40.00, abs=0.001)
    assert s["approval_status"] == "DISQUALIFIED"


# ==========================================================================
# Corner/calculations/capa_provisional_below_gate_blocks_verify
# ==========================================================================
def test_capa_provisional_below_gate_blocks_verify(api):
    """PRD 3.4: "verification requires that provisional_effectiveness be at least
    0.50, failing which the request is rejected with ERR_EFFECTIVENESS_TOO_LOW
    (HTTP 409) ..."
    PRD 3.4: "The projected (provisional) effectiveness, recorded in
    provisional_effectiveness and clamped to the range 0.00 through 1.00, is the
    total of the containment_count values across all D4 and D5 steps divided by
    the parent report's defect_qty (treating the divisor as 1 if defect_qty were
    ever zero), capped at 1.00 and rounded half-up to two decimal places."

    Design: Corner/calculations/capa_provisional_below_gate_blocks_verify
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    # containment=2 / defect_qty=5 = 0.40 < 0.50
    ncr, capa = fx.capa_to_verification(eng["id"], mgr["id"], sup["id"],
                                        containment_count=2, defect_qty=5, part_number="P-PG")
    assert capa["provisional_effectiveness"] == 0.40
    resp = api.transition_capa(capa["id"], {"action": "VERIFY"}, fx.make_manager_headers(mgr["id"]))
    validate_error(resp, ApiErrorId.ERR_EFFECTIVENESS_TOO_LOW.value, 409)
    after = validate_success(api.get_capa(capa["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "VERIFICATION"


# ==========================================================================
# Corner/validations/missing_user_role_header_unauthenticated
# ==========================================================================
def test_missing_user_role_header_unauthenticated(api):
    """PRD 2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized role names, the request is rejected with ERR_UNAUTHENTICATED (HTTP
    401)."

    Design: Corner/validations/missing_user_role_header_unauthenticated
    """
    resp = api.create_supplier({"name": "No Auth", "code": fx.f._unique_code("NOAUTH")},
                               {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ==========================================================================
# Corner/validations/transition_nonexistent_lot_not_found
# ==========================================================================
def test_transition_nonexistent_lot_not_found(api):
    """PRD 2.10: "Then every resource named in the URL path is checked for
    existence, left to right, yielding ERR_NOT_FOUND for the first that is
    missing."

    Design: Corner/validations/transition_nonexistent_lot_not_found
    """
    inspector = fx.create_inspector()
    resp = api.transition_inspection_lot(NON_EXISTENT_UUID, {"action": "START"}, fx.make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


# ==========================================================================
# Corner/validations/disposition_return_to_supplier_on_internal_ncr_not_allowed
# ==========================================================================
def test_disposition_return_to_supplier_on_internal_ncr_not_allowed(api):
    """PRD 3.3: "A choice of RETURN_TO_SUPPLIER is permitted only when the
    report's source is SUPPLIER; otherwise it is rejected with
    ERR_DISPOSITION_NOT_ALLOWED (HTTP 409)."

    Design: Corner/validations/disposition_return_to_supplier_on_internal_ncr_not_allowed
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    # INTERNAL source — no supplier attribution
    ncr = fx.create_open_ncr(eng["id"], source="INTERNAL", severity="MAJOR", defect_qty=2,
                             unit_cost_cents=1000, part_number="P-DA")
    resp = api.disposition_ncr(ncr["id"], {"disposition": "RETURN_TO_SUPPLIER"}, fx.make_manager_headers(mgr["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPOSITION_NOT_ALLOWED.value, 409)
    after = validate_success(api.get_ncr(ncr["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "OPEN"


# ==========================================================================
# Corner/validations/disposition_use_as_is_without_deviation_required
# ==========================================================================
def test_disposition_use_as_is_without_deviation_required(api):
    """PRD 3.3: "A choice of USE_AS_IS is permitted only when an APPROVED
    deviation exists for this report whose max_qty is at least the report's
    defect_qty and whose validity window contains the current server clock ...;
    absent such a deviation the request is rejected with ERR_DEVIATION_REQUIRED
    (HTTP 409)."

    Design: Corner/validations/disposition_use_as_is_without_deviation_required
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    fx.set_clock("2026-06-15T00:00:00Z")
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=2,
                             unit_cost_cents=1000, part_number="P-DR2")
    resp = api.disposition_ncr(ncr["id"], {"disposition": "USE_AS_IS"}, fx.make_manager_headers(mgr["id"]))
    validate_error(resp, ApiErrorId.ERR_DEVIATION_REQUIRED.value, 409)
    after = validate_success(api.get_ncr(ncr["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "OPEN"


# ==========================================================================
# Corner/validations/revision_create_out_of_sequence_revision_sequence
# ==========================================================================
def test_revision_create_out_of_sequence(api):
    """PRD 3.10: "At create time the revision_no must equal the parent control
    plan's current_revision_no plus one, or the create is rejected with
    ERR_REVISION_SEQUENCE (HTTP 409)."

    Design: Corner/validations/revision_create_out_of_sequence_revision_sequence
    """
    eng = fx.create_engineer()
    cp = fx.create_control_plan()
    ver = fx.read_control_plan_version(cp["id"])
    resp = api.create_control_plan_revision(
        {"control_plan_id": cp["id"], "revision_no": 2, "change_summary": "skip one",
         "expected_control_plan_version": ver},
        fx.make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_REVISION_SEQUENCE.value, 409)


# ==========================================================================
# Corner/validations/path_not_found_beats_invalid_request_body
# ==========================================================================
def test_path_not_found_beats_invalid_request_body(api):
    """PRD 2.10: "Then every resource named in the URL path is checked for
    existence, left to right, yielding ERR_NOT_FOUND for the first that is
    missing. Then every foreign key carried in the request body is checked,
    yielding ERR_FK_NOT_FOUND if any does not resolve to an existing resource of
    the correct type. Then the body itself is checked for well-formedness ...
    yielding ERR_INVALID_REQUEST."

    Design: Corner/validations/path_not_found_beats_invalid_request_body
    """
    mgr = fx.create_manager()
    resp = api.disposition_ncr(NON_EXISTENT_UUID, {"disposition": "NOT_A_DISPOSITION"},
                               fx.make_manager_headers(mgr["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)
    body = resp.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value


# ==========================================================================
# Corner/validations/forbidden_role_beats_path_not_found
# ==========================================================================
def test_forbidden_role_beats_path_not_found(api):
    """PRD 2.10: "Next the role's authority for the endpoint is checked, yielding
    ERR_FORBIDDEN_ROLE if the role is not permitted. Then every resource named in
    the URL path is checked for existence, left to right, yielding ERR_NOT_FOUND
    for the first that is missing."

    Design: Corner/validations/forbidden_role_beats_path_not_found
    """
    inspector = fx.create_inspector()
    # disposition is QualityManager-only; Inspector is forbidden, and NCR id is missing.
    resp = api.disposition_ncr(NON_EXISTENT_UUID, {"disposition": "REWORK"}, fx.make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    body = resp.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_NOT_FOUND.value
