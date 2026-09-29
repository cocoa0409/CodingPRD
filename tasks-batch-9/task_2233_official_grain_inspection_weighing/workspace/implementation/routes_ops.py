"""Inspection requests, samples, grading results, protein analyses, weighings."""

from flask import Blueprint

import calc
import services as svc
import validation
from auth import (
    ANY_ROLE,
    APPLICANT_USER,
    LICENSED_INSPECTOR,
    SERVICE_ADMIN,
    SUPERVISING_INSPECTOR,
    acting_applicant_id,
    assert_applicant_scope,
    endpoint,
)
from envelope import apply_filters, created, listing, ok
from errors import ApiError
from store import db, days, new_row, serialize, touch

bp = Blueprint("ops", __name__)

PREFIX = "/grain-inspection"

INSPECTOR_ROLES = (LICENSED_INSPECTOR, SUPERVISING_INSPECTOR)
COMMODITIES = ("CORN", "SOYBEANS")
POINTS_OF_SERVICE = ("LOADING", "UNLOADING")
SERVICES = ("GRADING", "WEIGHING", "PROTEIN", "EXPORT_SUPERVISION")
SAMPLE_TYPES = ("ORIGINAL", "FILE", "APPEAL")

RETENTION_DAYS = 90


def scope_rows(rows, request_field="inspection_request_id"):
    """Restrict a listing to the acting applicant's own rows."""
    acting = acting_applicant_id()
    if acting is None:
        return rows
    out = []
    for row in rows:
        req = db.inspection_requests.get(row[request_field])
        if req is not None and req["applicant_id"] == acting:
            out.append(row)
    return out


def scope_via_request(row, request_field="inspection_request_id"):
    req = db.inspection_requests.get(row[request_field])
    assert_applicant_scope(req["applicant_id"] if req else None)


# ==========================================================================
# inspection requests
# ==========================================================================

@bp.post(PREFIX + "/inspection-requests")
@endpoint((SERVICE_ADMIN, APPLICANT_USER))
def create_inspection_request():
    body = validation.parse(
        {
            "applicant_id": {"required": True},
            "service_area_id": {"required": True},
            "commodity": {"type": "enum", "values": COMMODITIES, "required": True},
            "point_of_service": {"type": "enum", "values": POINTS_OF_SERVICE, "required": True},
            "lot_identifier": {"required": True},
            "declared_quantity_bushels": {"type": "number", "exclusive_min": 0, "required": True},
            "requested_services": {
                "type": "enum_array",
                "values": SERVICES,
                "min_items": 1,
                "max_items": 4,
                "required": True,
            },
        }
    )
    assert_applicant_scope(body["applicant_id"])
    applicant = svc.applicant(body["applicant_id"])
    area = svc.area(body["service_area_id"])

    requested = list(dict.fromkeys(body["requested_services"]))
    if "GRADING" not in requested:
        raise ApiError("ERR_SERVICE_NOT_REQUESTED")
    svc.assert_area_active(area)

    row = new_row(
        {
            "applicant_id": applicant["id"],
            "service_area_id": area["id"],
            "commodity": body["commodity"],
            "point_of_service": body["point_of_service"],
            "lot_identifier": body["lot_identifier"],
            "declared_quantity_bushels": body["declared_quantity_bushels"],
            "requested_services": requested,
            "grading_status": "OPEN",
            "weighing_status": "PENDING" if "WEIGHING" in requested else "NOT_REQUIRED",
            "certified_quantity_bushels": body["declared_quantity_bushels"],
            "grade_revision_count": 0,
        }
    )
    db.inspection_requests[row["id"]] = row
    return created(serialize(row))


@bp.get(PREFIX + "/inspection-requests")
@endpoint(ANY_ROLE)
def list_inspection_requests():
    rows = apply_filters(
        db.inspection_requests.values(),
        ("applicant_id", "service_area_id", "commodity", "grading_status", "weighing_status"),
    )
    acting = acting_applicant_id()
    if acting is not None:
        rows = [row for row in rows if row["applicant_id"] == acting]
    return listing(rows)


@bp.get(PREFIX + "/inspection-requests/<row_id>")
@endpoint(ANY_ROLE)
def get_inspection_request(row_id):
    row = svc.request(row_id)
    assert_applicant_scope(row["applicant_id"])
    return ok(serialize(row))


@bp.get(PREFIX + "/inspection-requests/<row_id>/certificates")
@endpoint(ANY_ROLE)
def list_request_certificates(row_id):
    row = svc.request(row_id)
    assert_applicant_scope(row["applicant_id"])
    rows = [c for c in db.certificates.values() if c["inspection_request_id"] == row["id"]]
    rows = apply_filters(rows, ("certificate_type", "status"))
    return listing(rows)


# ==========================================================================
# samples
# ==========================================================================

@bp.post(PREFIX + "/samples")
@endpoint(INSPECTOR_ROLES)
def create_sample():
    body = validation.parse(
        {
            "inspection_request_id": {"required": True},
            "sampling_device_id": {"required": True},
            "inspector_id": {"required": True},
            "sample_type": {"type": "enum", "values": SAMPLE_TYPES, "default": "ORIGINAL"},
            "seal_number": {"required": True},
            "portions_count": {"type": "int", "min": 1, "max": 10, "required": True},
        }
    )
    request_row = svc.request(body["inspection_request_id"])
    device = svc.equipment(body["sampling_device_id"])
    inspector = svc.inspector(body["inspector_id"])
    area = svc.area(request_row["service_area_id"])

    svc.assert_same_area(device, request_row)
    svc.assert_same_area(inspector, request_row)
    if device["equipment_kind"] != "SAMPLING_DEVICE":
        raise ApiError("ERR_EQUIPMENT_KIND_MISMATCH")

    svc.assert_area_active(area)
    svc.assert_equipment_usable(device)
    svc.assert_licence(inspector, svc.LINE_LICENCE_STATES)
    svc.assert_endorsement(inspector, "SAMPLING")

    for existing in db.samples.values():
        if (
            existing["inspection_request_id"] == request_row["id"]
            and existing["seal_number"] == body["seal_number"]
        ):
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")

    row = new_row(
        {
            "inspection_request_id": request_row["id"],
            "sampling_device_id": device["id"],
            "inspector_id": inspector["id"],
            "sample_type": body["sample_type"],
            "seal_number": body["seal_number"],
            "portions_count": body["portions_count"],
            "portions_consumed": 0,
            "portions_retained": 0,
            "portions_available": body["portions_count"],
            "integrity_status": "SEALED",
            "collected_at": db.now,
            "file_retention_until": db.now + days(RETENTION_DAYS),
        }
    )
    db.samples[row["id"]] = row

    if body["sample_type"] == "ORIGINAL" and request_row["grading_status"] == "OPEN":
        request_row["grading_status"] = "SAMPLED"
        touch(request_row)
    return created(serialize(row))


@bp.get(PREFIX + "/samples")
@endpoint(ANY_ROLE)
def list_samples():
    rows = apply_filters(
        db.samples.values(),
        (
            "inspection_request_id",
            "sampling_device_id",
            "inspector_id",
            "sample_type",
            "integrity_status",
        ),
    )
    return listing(scope_rows(rows))


@bp.get(PREFIX + "/samples/<row_id>")
@endpoint(ANY_ROLE)
def get_sample(row_id):
    row = svc.sample(row_id)
    scope_via_request(row)
    return ok(serialize(row))


@bp.post(PREFIX + "/samples/<row_id>/break-seal")
@endpoint((SUPERVISING_INSPECTOR,))
def break_sample_seal(row_id):
    row = svc.sample(row_id)
    validation.parse({"reason": {"nullable": True, "default": None}})
    if row["integrity_status"] not in ("SEALED", "CONSUMED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if svc.appeal_holding_sample(row["id"]) is not None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    row["integrity_status"] = "BROKEN"
    touch(row)
    return ok(serialize(row))


# ==========================================================================
# grading results
# ==========================================================================

@bp.post(PREFIX + "/grading-results")
@endpoint(INSPECTOR_ROLES)
def create_grading_result():
    body = validation.parse(
        {
            "inspection_request_id": {"required": True},
            "sample_id": {"required": True},
            "inspector_id": {"required": True},
            "appeal_id": {"nullable": True, "default": None},
            "test_weight_lbs_per_bushel": {"type": "number", "min": 20.0, "max": 70.0, "required": True},
            "moisture_pct": {"type": "number", "min": 0.0, "max": 40.0, "required": True},
            "damaged_total_pct": {"type": "number", "min": 0.0, "max": 100.0, "required": True},
            "heat_damaged_pct": {"type": "number", "min": 0.0, "max": 100.0, "required": True},
            "foreign_material_pct": {"type": "number", "min": 0.0, "max": 100.0, "required": True},
        }
    )
    request_row = svc.request(body["inspection_request_id"])
    sample_row = svc.sample(body["sample_id"])
    inspector = svc.inspector(body["inspector_id"])
    appeal_row = svc.appeal(body["appeal_id"]) if body["appeal_id"] is not None else None

    if sample_row["inspection_request_id"] != request_row["id"]:
        raise ApiError("ERR_SAMPLE_REQUEST_MISMATCH")

    challenged_cert = None
    if appeal_row is not None:
        challenged_cert = db.certificates.get(appeal_row["certificate_id"])
        if (
            appeal_row["status"] != "SAMPLE_ASSIGNED"
            or challenged_cert is None
            or challenged_cert["inspection_request_id"] != request_row["id"]
            or appeal_row["assigned_sample_id"] != sample_row["id"]
        ):
            raise ApiError("ERR_APPEAL_REGRADE_BINDING_INVALID")

    if appeal_row is not None:
        svc.assert_licence(inspector, ("ACTIVE",))
    else:
        svc.assert_licence(inspector, svc.LINE_LICENCE_STATES)
    svc.assert_sample_intact(sample_row)

    existing_original = svc.original_final_grading_result(request_row["id"])
    if appeal_row is None and existing_original is None:
        if request_row["grading_status"] != "SAMPLED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if appeal_row is not None and existing_original is not None:
        if existing_original["inspector_id"] == inspector["id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    svc.assert_endorsement(inspector, "GRADING")

    if svc.available_portions(sample_row) < 1:
        raise ApiError("ERR_SAMPLE_PORTIONS_EXHAUSTED")
    if appeal_row is None and existing_original is not None:
        raise ApiError("ERR_DUPLICATE_OPERATIVE_RECORD")
    if calc.dec(body["heat_damaged_pct"]) > calc.dec(body["damaged_total_pct"]):
        raise ApiError("ERR_FACTOR_SET_INCONSISTENT")

    observed = {key: body[key] for key in calc.FACTOR_KEYS}
    rounded, grade, limiting = calc.grade_determination(request_row["commodity"], observed)

    row = new_row(
        {
            "inspection_request_id": request_row["id"],
            "sample_id": sample_row["id"],
            "inspector_id": inspector["id"],
            "appeal_id": appeal_row["id"] if appeal_row else None,
            "supersedes_grading_result_id": None,
            "test_weight_lbs_per_bushel": body["test_weight_lbs_per_bushel"],
            "moisture_pct": body["moisture_pct"],
            "damaged_total_pct": body["damaged_total_pct"],
            "heat_damaged_pct": body["heat_damaged_pct"],
            "foreign_material_pct": body["foreign_material_pct"],
            "rounded_factors": rounded,
            "assigned_grade": grade,
            "limiting_factor": limiting,
            "status": "FINAL" if appeal_row is None else "SUPERSEDED",
        }
    )
    db.grading_results[row["id"]] = row
    svc.consume_portion(sample_row)

    if appeal_row is None:
        if request_row["grading_status"] == "SAMPLED":
            request_row["grading_status"] = "GRADED"
            touch(request_row)
    else:
        appeal_row["status"] = "UNDER_REVIEW"
        touch(appeal_row)

    return created(serialize(row))


@bp.get(PREFIX + "/grading-results")
@endpoint(ANY_ROLE)
def list_grading_results():
    rows = apply_filters(
        db.grading_results.values(),
        (
            "inspection_request_id",
            "sample_id",
            "inspector_id",
            "appeal_id",
            "supersedes_grading_result_id",
            "status",
        ),
    )
    return listing(scope_rows(rows))


@bp.get(PREFIX + "/grading-results/<row_id>")
@endpoint(ANY_ROLE)
def get_grading_result(row_id):
    row = svc.find("grading_results", row_id, "ERR_GRADING_RESULT_NOT_FOUND")
    scope_via_request(row)
    return ok(serialize(row))


# ==========================================================================
# protein analyses
# ==========================================================================

@bp.post(PREFIX + "/protein-analyses")
@endpoint(INSPECTOR_ROLES)
def create_protein_analysis():
    body = validation.parse(
        {
            "inspection_request_id": {"required": True},
            "sample_id": {"required": True},
            "instrument_id": {"required": True},
            "inspector_id": {"required": True},
            "protein_pct_as_is": {"type": "number", "min": 0.0, "max": 60.0, "required": True},
            "instrument_moisture_pct": {"type": "number", "min": 0.0, "max": 40.0, "required": True},
        }
    )
    request_row = svc.request(body["inspection_request_id"])
    sample_row = svc.sample(body["sample_id"])
    instrument = svc.equipment(body["instrument_id"])
    inspector = svc.inspector(body["inspector_id"])
    area = svc.area(request_row["service_area_id"])

    if sample_row["inspection_request_id"] != request_row["id"]:
        raise ApiError("ERR_SAMPLE_REQUEST_MISMATCH")
    svc.assert_same_area(instrument, request_row)
    svc.assert_same_area(inspector, request_row)
    if instrument["equipment_kind"] != "PROTEIN_INSTRUMENT":
        raise ApiError("ERR_EQUIPMENT_KIND_MISMATCH")
    svc.assert_service_requested(request_row, "PROTEIN")

    svc.assert_area_active(area)
    svc.assert_equipment_usable(instrument, allow_drift=True)
    svc.assert_licence(inspector, svc.LINE_LICENCE_STATES)
    svc.assert_sample_intact(sample_row)
    svc.assert_endorsement(inspector, "PROTEIN")

    if svc.available_portions(sample_row) < 1:
        raise ApiError("ERR_SAMPLE_PORTIONS_EXHAUSTED")

    final_grade = svc.final_grading_result(request_row["id"])
    if final_grade is not None:
        basis_source = "OFFICIAL_MOISTURE"
        moisture_source = final_grade["rounded_factors"]["moisture_pct"]
    else:
        basis_source = "INSTRUMENT_MOISTURE"
        moisture_source = body["instrument_moisture_pct"]
    reported, adjustment = calc.protein_conversion(body["protein_pct_as_is"], moisture_source)

    row = new_row(
        {
            "inspection_request_id": request_row["id"],
            "sample_id": sample_row["id"],
            "instrument_id": instrument["id"],
            "inspector_id": inspector["id"],
            "sequence_no": svc.next_instrument_sequence(instrument["id"]),
            "protein_pct_as_is": body["protein_pct_as_is"],
            "instrument_moisture_pct": body["instrument_moisture_pct"],
            "basis_source": basis_source,
            "moisture_source_pct": moisture_source,
            "protein_reported_pct": reported,
            "basis_adjustment_pct": adjustment,
            "status": "ACCEPTED",
        }
    )
    db.protein_analyses[row["id"]] = row
    svc.consume_portion(sample_row)
    return created(serialize(row))


@bp.post(PREFIX + "/protein-analyses/<row_id>/recompute")
@endpoint(INSPECTOR_ROLES)
def recompute_protein_analysis(row_id):
    row = svc.find("protein_analyses", row_id, "ERR_PROTEIN_ANALYSIS_NOT_FOUND")
    final_grade = svc.final_grading_result(row["inspection_request_id"])
    if (
        final_grade is None
        or row["status"] != "ACCEPTED"
        or row["basis_source"] != "INSTRUMENT_MOISTURE"
    ):
        raise ApiError("ERR_ANALYSIS_RECOMPUTE_NOT_APPLICABLE")

    moisture_source = final_grade["rounded_factors"]["moisture_pct"]
    reported, adjustment = calc.protein_conversion(row["protein_pct_as_is"], moisture_source)
    row["basis_source"] = "OFFICIAL_MOISTURE"
    row["moisture_source_pct"] = moisture_source
    row["protein_reported_pct"] = reported
    row["basis_adjustment_pct"] = adjustment
    row["status"] = "RECOMPUTED"
    touch(row)
    return ok(serialize(row))


@bp.get(PREFIX + "/protein-analyses")
@endpoint(ANY_ROLE)
def list_protein_analyses():
    rows = apply_filters(
        db.protein_analyses.values(),
        ("inspection_request_id", "sample_id", "instrument_id", "inspector_id", "status"),
    )
    return listing(scope_rows(rows))


@bp.get(PREFIX + "/protein-analyses/<row_id>")
@endpoint(ANY_ROLE)
def get_protein_analysis(row_id):
    row = svc.find("protein_analyses", row_id, "ERR_PROTEIN_ANALYSIS_NOT_FOUND")
    scope_via_request(row)
    return ok(serialize(row))


# ==========================================================================
# weighing records
# ==========================================================================

@bp.post(PREFIX + "/weighing-records")
@endpoint(INSPECTOR_ROLES)
def create_weighing_record():
    body = validation.parse(
        {
            "inspection_request_id": {"required": True},
            "scale_id": {"required": True},
            "weigher_inspector_id": {"required": True},
            "drafts": {"type": "drafts", "min_items": 1, "max_items": 20, "required": True},
            "dockage_pct": {"type": "number", "min": 0.0, "max": 15.0, "default": 0},
        }
    )
    request_row = svc.request(body["inspection_request_id"])
    scale = svc.equipment(body["scale_id"])
    weigher = svc.inspector(body["weigher_inspector_id"])
    area = svc.area(request_row["service_area_id"])

    svc.assert_same_area(scale, request_row)
    svc.assert_same_area(weigher, request_row)
    if scale["equipment_kind"] != "SCALE":
        raise ApiError("ERR_EQUIPMENT_KIND_MISMATCH")
    svc.assert_service_requested(request_row, "WEIGHING")

    svc.assert_area_active(area)
    svc.assert_equipment_usable(scale)
    svc.assert_licence(weigher, svc.LINE_LICENCE_STATES)

    operative = svc.operative_weighing_record(request_row["id"])
    if operative is None and request_row["weighing_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    svc.assert_endorsement(weigher, "WEIGHING")

    if operative is not None:
        raise ApiError("ERR_DUPLICATE_OPERATIVE_RECORD")

    drafts = body["drafts"]
    if any(draft["gross_lbs"] <= draft["tare_lbs"] for draft in drafts):
        raise ApiError("ERR_SCALE_CAPACITY_EXCEEDED")
    if scale["capacity_lbs"] is not None:
        if sum(draft["gross_lbs"] for draft in drafts) > scale["capacity_lbs"]:
            raise ApiError("ERR_SCALE_CAPACITY_EXCEEDED")

    weights = calc.official_net_weight(drafts, body["dockage_pct"], request_row["commodity"])

    row = new_row(
        {
            "inspection_request_id": request_row["id"],
            "scale_id": scale["id"],
            "weigher_inspector_id": weigher["id"],
            "supervisor_inspector_id": None,
            "drafts": [dict(draft) for draft in drafts],
            "dockage_pct": body["dockage_pct"],
            "dockage_lbs": weights["dockage_lbs"],
            "net_lbs": weights["net_lbs"],
            "provisional_net_lbs": weights["provisional_net_lbs"],
            "rounding_variance_lbs": weights["rounding_variance_lbs"],
            "net_bushels": weights["net_bushels"],
            "status": "WEIGHED",
        }
    )
    db.weighing_records[row["id"]] = row

    request_row["certified_quantity_bushels"] = weights["net_bushels"]
    request_row["weighing_status"] = "WEIGHED"
    touch(request_row)
    return created(serialize(row))


@bp.post(PREFIX + "/weighing-records/<row_id>/supervise")
@endpoint((SUPERVISING_INSPECTOR,))
def supervise_weighing_record(row_id):
    row = svc.find("weighing_records", row_id, "ERR_WEIGHING_RECORD_NOT_FOUND")
    body = validation.parse({"supervisor_inspector_id": {"required": True}})
    supervisor = svc.inspector(body["supervisor_inspector_id"])

    svc.assert_licence(supervisor, ("ACTIVE",))
    if row["status"] != "WEIGHED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if supervisor["id"] == row["weigher_inspector_id"]:
        raise ApiError("ERR_SELF_SUPERVISION_FORBIDDEN")
    svc.assert_endorsement(supervisor, "SUPERVISION")

    row["status"] = "SUPERVISED"
    row["supervisor_inspector_id"] = supervisor["id"]
    touch(row)

    request_row = db.inspection_requests.get(row["inspection_request_id"])
    if request_row is not None and request_row["weighing_status"] == "WEIGHED":
        request_row["weighing_status"] = "SUPERVISED"
        touch(request_row)
    return ok(serialize(row))


@bp.get(PREFIX + "/weighing-records")
@endpoint(ANY_ROLE)
def list_weighing_records():
    rows = apply_filters(
        db.weighing_records.values(),
        (
            "inspection_request_id",
            "scale_id",
            "weigher_inspector_id",
            "supervisor_inspector_id",
            "status",
        ),
    )
    return listing(scope_rows(rows))


@bp.get(PREFIX + "/weighing-records/<row_id>")
@endpoint(ANY_ROLE)
def get_weighing_record(row_id):
    row = svc.find("weighing_records", row_id, "ERR_WEIGHING_RECORD_NOT_FOUND")
    scope_via_request(row)
    return ok(serialize(row))
