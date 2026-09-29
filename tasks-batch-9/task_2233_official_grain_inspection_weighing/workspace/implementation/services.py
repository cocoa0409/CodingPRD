"""Shared domain services: lookups, the ledger, cascades and the expiry sweep."""

import calc
from errors import ApiError
from store import db, days, new_row, ordered, touch

NON_TERMINAL_WATCH = ("SCHEDULED", "IN_PROGRESS")
NON_TERMINAL_APPEAL = ("FILED", "SAMPLE_ASSIGNED", "UNDER_REVIEW")
OPERATIVE_WEIGHING = ("WEIGHED", "SUPERVISED")
LIVE_CERTIFICATE = ("ISSUED", "UNDER_APPEAL")
LINE_LICENCE_STATES = ("PROBATIONARY", "ACTIVE")


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def find(collection, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def area(row_id):
    return find("service_areas", row_id, "ERR_SERVICE_AREA_NOT_FOUND")


def applicant(row_id):
    return find("applicants", row_id, "ERR_APPLICANT_NOT_FOUND")


def inspector(row_id):
    return find("inspectors", row_id, "ERR_INSPECTOR_NOT_FOUND")


def equipment(row_id):
    return find("equipment", row_id, "ERR_EQUIPMENT_NOT_FOUND")


def request(row_id):
    return find("inspection_requests", row_id, "ERR_INSPECTION_REQUEST_NOT_FOUND")


def sample(row_id):
    return find("samples", row_id, "ERR_SAMPLE_NOT_FOUND")


def certificate(row_id):
    return find("certificates", row_id, "ERR_CERTIFICATE_NOT_FOUND")


def appeal(row_id):
    return find("appeals", row_id, "ERR_APPEAL_NOT_FOUND")


def rows(collection):
    return list(getattr(db, collection).values())


def where(collection, **filters):
    out = []
    for row in getattr(db, collection).values():
        if all(row.get(key) == value for key, value in filters.items()):
            out.append(row)
    return ordered(out)


# --------------------------------------------------------------------------
# gates shared between endpoints
# --------------------------------------------------------------------------

def assert_area_active(area_row):
    if area_row["status"] == "SUSPENDED":
        raise ApiError("ERR_SERVICE_AREA_SUSPENDED")


def assert_licence(inspector_row, states):
    if inspector_row["license_status"] not in states:
        raise ApiError("ERR_INSPECTOR_LICENSE_INVALID")


def assert_endorsement(inspector_row, endorsement):
    if endorsement not in (inspector_row.get("endorsements") or []):
        raise ApiError("ERR_ENDORSEMENT_MISSING")


def assert_equipment_usable(equipment_row, allow_drift=False):
    allowed = ("APPROVED", "DRIFT_WATCH") if allow_drift else ("APPROVED",)
    if equipment_row["approval_status"] not in allowed:
        raise ApiError("ERR_EQUIPMENT_NOT_APPROVED")
    certified_until = equipment_row.get("certified_until")
    if certified_until is None or certified_until <= db.now:
        raise ApiError("ERR_EQUIPMENT_NOT_APPROVED")


def assert_sample_intact(sample_row):
    if sample_row["integrity_status"] in ("BROKEN", "EXPIRED"):
        raise ApiError("ERR_SAMPLE_INTEGRITY_BROKEN")


def assert_service_requested(request_row, service):
    if service not in request_row["requested_services"]:
        raise ApiError("ERR_SERVICE_NOT_REQUESTED")


def assert_same_area(row, request_row):
    if row.get("service_area_id") != request_row["service_area_id"]:
        raise ApiError("ERR_SERVICE_AREA_MISMATCH")


# --------------------------------------------------------------------------
# sample portion accounting
# --------------------------------------------------------------------------

def refresh_portions(sample_row):
    sample_row["portions_available"] = (
        sample_row["portions_count"]
        - sample_row["portions_consumed"]
        - sample_row["portions_retained"]
    )
    return sample_row["portions_available"]


def available_portions(sample_row):
    if sample_row["integrity_status"] in ("BROKEN", "EXPIRED"):
        return 0
    return sample_row["portions_available"]


def consume_portion(sample_row):
    sample_row["portions_consumed"] += 1
    if refresh_portions(sample_row) <= 0 and sample_row["integrity_status"] == "SEALED":
        sample_row["integrity_status"] = "CONSUMED"
    touch(sample_row)


def release_consumed_portion(sample_row):
    if sample_row["portions_consumed"] > 0:
        sample_row["portions_consumed"] -= 1
    refresh_portions(sample_row)
    if sample_row["integrity_status"] == "CONSUMED" and sample_row["portions_available"] > 0:
        sample_row["integrity_status"] = "SEALED"
    touch(sample_row)


def retain_portion(sample_row):
    sample_row["portions_retained"] += 1
    refresh_portions(sample_row)
    touch(sample_row)


def release_retained_portion(sample_row):
    if sample_row["portions_retained"] > 0:
        sample_row["portions_retained"] -= 1
    refresh_portions(sample_row)
    touch(sample_row)


# --------------------------------------------------------------------------
# the conserved applicant ledger (PRD §2.8)
# --------------------------------------------------------------------------

def _rebalance(applicant_row):
    applicant_row["open_balance_cents"] = (
        applicant_row["charges_total_cents"] - applicant_row["credits_total_cents"]
    )


def charge(applicant_row, cents):
    applicant_row["charges_total_cents"] += cents
    _rebalance(applicant_row)
    touch(applicant_row)


def credit(applicant_row, cents):
    applicant_row["credits_total_cents"] += cents
    _rebalance(applicant_row)
    touch(applicant_row)


# --------------------------------------------------------------------------
# inspector performance and watch cascades
# --------------------------------------------------------------------------

def abort_watches(inspector_row, statuses):
    for watch in ordered(
        [
            w
            for w in db.vessel_watches.values()
            if w["supervisor_inspector_id"] == inspector_row["id"] and w["status"] in statuses
        ]
    ):
        watch["status"] = "ABORTED"
        touch(watch)
        area_row = db.service_areas.get(watch["service_area_id"])
        if area_row is not None and area_row["open_watch_count"] > 0:
            area_row["open_watch_count"] -= 1
            touch(area_row)


def recompute_performance(inspector_row):
    """Recompute the score in place; auto-suspend an ACTIVE inspector below 70.

    The caller is responsible for the single touch() of the inspector row.
    """
    inspector_row["performance_score"] = calc.performance_score(
        inspector_row["appeal_reversal_count"],
        inspector_row["check_sample_deviation_count"],
        inspector_row["late_certificate_count"],
        inspector_row["training_hours_completed"],
    )
    if (
        inspector_row["license_status"] == "ACTIVE"
        and inspector_row["performance_score"] < calc.AUTO_SUSPEND_BELOW
    ):
        inspector_row["license_status"] = "SUSPENDED"
        inspector_row["suspension_reason"] = "AUTO_PERFORMANCE"
        abort_watches(inspector_row, ("SCHEDULED",))


# --------------------------------------------------------------------------
# fee schedules
# --------------------------------------------------------------------------

def active_schedule(service_area_id, service_class):
    now = db.now
    candidates = []
    for schedule in db.fee_schedules.values():
        if schedule["service_area_id"] != service_area_id:
            continue
        if schedule["service_class"] != service_class:
            continue
        if schedule["status"] != "ACTIVE":
            continue
        if schedule["effective_from"] > now:
            continue
        if schedule["effective_to"] is not None and schedule["effective_to"] <= now:
            continue
        candidates.append(schedule)
    if not candidates:
        return None
    return ordered(candidates)[-1]


def windows_overlap(from_a, to_a, from_b, to_b):
    if to_a is not None and to_a <= from_b:
        return False
    if to_b is not None and to_b <= from_a:
        return False
    return True


# --------------------------------------------------------------------------
# certificate voiding and supersession
# --------------------------------------------------------------------------

def reverse_certificate(certificate_row, new_status):
    """Void or supersede a certificate, reversing its whole fee (PRD §2.8)."""
    certificate_row["status"] = new_status
    certificate_row["fee_settlement_status"] = "REVERSED"
    touch(certificate_row)
    request_row = db.inspection_requests.get(certificate_row["inspection_request_id"])
    if request_row is not None:
        applicant_row = db.applicants.get(request_row["applicant_id"])
        if applicant_row is not None and certificate_row["fee_total_cents"]:
            credit(applicant_row, certificate_row["fee_total_cents"])


def scale_failure_cascade(scale_row):
    """A scale that fails its certification test repudiates its weighings."""
    records = ordered(
        [
            record
            for record in db.weighing_records.values()
            if record["scale_id"] == scale_row["id"] and record["status"] in OPERATIVE_WEIGHING
        ]
    )
    for record in records:
        record["status"] = "VOIDED"
        touch(record)
        for cert in ordered(
            [
                c
                for c in db.certificates.values()
                if c.get("_weighing_record_id") == record["id"] and c["status"] in LIVE_CERTIFICATE
            ]
        ):
            reverse_certificate(cert, "VOIDED")
        request_row = db.inspection_requests.get(record["inspection_request_id"])
        if request_row is not None:
            request_row["certified_quantity_bushels"] = request_row["declared_quantity_bushels"]
            if request_row["weighing_status"] != "NOT_REQUIRED":
                request_row["weighing_status"] = "PENDING"
            touch(request_row)


def instrument_tolerance_cascade(instrument_row, window_start):
    """Reject the analyses this instrument produced since its previous check."""
    analyses = [
        analysis
        for analysis in db.protein_analyses.values()
        if analysis["instrument_id"] == instrument_row["id"]
        and analysis["status"] in ("ACCEPTED", "RECOMPUTED")
        and (window_start is None or analysis["created_at"] >= window_start)
    ]
    analyses.sort(key=lambda row: (row["created_at"], row["sequence_no"]))
    for analysis in analyses:
        analysis["status"] = "REJECTED_CALIBRATION"
        touch(analysis)
        sample_row = db.samples.get(analysis["sample_id"])
        if sample_row is not None:
            release_consumed_portion(sample_row)
        for cert in ordered(
            [
                c
                for c in db.certificates.values()
                if c.get("_protein_analysis_id") == analysis["id"] and c["status"] in LIVE_CERTIFICATE
            ]
        ):
            reverse_certificate(cert, "VOIDED")


# --------------------------------------------------------------------------
# grading / weighing / analysis helpers
# --------------------------------------------------------------------------

def final_grading_result(request_id):
    results = [
        result
        for result in db.grading_results.values()
        if result["inspection_request_id"] == request_id and result["status"] == "FINAL"
    ]
    if not results:
        return None
    return ordered(results)[-1]


def original_final_grading_result(request_id):
    results = [
        result
        for result in db.grading_results.values()
        if result["inspection_request_id"] == request_id
        and result["status"] == "FINAL"
        and result["appeal_id"] is None
    ]
    if not results:
        return None
    return ordered(results)[-1]


def appeal_regrade(appeal_id):
    results = [
        result for result in db.grading_results.values() if result["appeal_id"] == appeal_id
    ]
    if not results:
        return None
    return ordered(results)[-1]


def operative_weighing_record(request_id):
    records = [
        record
        for record in db.weighing_records.values()
        if record["inspection_request_id"] == request_id and record["status"] in OPERATIVE_WEIGHING
    ]
    if not records:
        return None
    return ordered(records)[-1]


def operative_analysis(request_id):
    analyses = [
        analysis
        for analysis in db.protein_analyses.values()
        if analysis["inspection_request_id"] == request_id
        and analysis["status"] in ("ACCEPTED", "RECOMPUTED")
    ]
    if not analyses:
        return None
    analyses.sort(key=lambda row: (row["created_at"], row["sequence_no"]))
    return analyses[-1]


def next_instrument_sequence(instrument_id):
    highest = 0
    for analysis in db.protein_analyses.values():
        if analysis["instrument_id"] == instrument_id:
            highest = max(highest, analysis["sequence_no"])
    return highest + 1


def next_certificate_sequence(applicant_id):
    highest = 0
    for cert in db.certificates.values():
        request_row = db.inspection_requests.get(cert["inspection_request_id"])
        if request_row is not None and request_row["applicant_id"] == applicant_id:
            highest = max(highest, cert["sequence_no"])
    return highest + 1


def non_terminal_appeal_for_certificate(certificate_id):
    for row in ordered(
        [
            a
            for a in db.appeals.values()
            if a["certificate_id"] == certificate_id and a["status"] in NON_TERMINAL_APPEAL
        ]
    ):
        return row
    return None


def appeal_holding_sample(sample_id):
    for row in db.appeals.values():
        if row["assigned_sample_id"] == sample_id and row["status"] in NON_TERMINAL_APPEAL:
            return row
    return None


# --------------------------------------------------------------------------
# certificate construction (shared by issuance and the appeal cascade)
# --------------------------------------------------------------------------

def build_certificate(
    request_row,
    certificate_type,
    issuing_inspector_id,
    fee_total_cents,
    overtime_applied,
    grading_result=None,
    weighing_record=None,
    analysis=None,
    superseded_certificate_id=None,
    appeal_id=None,
):
    applicant_row = db.applicants[request_row["applicant_id"]]
    issued_at = db.now
    grade_content = certificate_type in ("GRADE", "COMBINED", "EXPORT_CARGO", "APPEAL_GRADE")
    weight_content = certificate_type in ("WEIGHT", "COMBINED", "EXPORT_CARGO")
    cert = new_row(
        {
            "inspection_request_id": request_row["id"],
            "issuing_inspector_id": issuing_inspector_id,
            "superseded_certificate_id": superseded_certificate_id,
            "appeal_id": appeal_id,
            "certificate_type": certificate_type,
            "sequence_no": next_certificate_sequence(applicant_row["id"]),
            "grade_snapshot": grading_result["assigned_grade"] if (grade_content and grading_result) else None,
            "limiting_factor_snapshot": grading_result["limiting_factor"] if (grade_content and grading_result) else None,
            "net_lbs_snapshot": weighing_record["net_lbs"] if (weight_content and weighing_record) else None,
            "net_bushels_snapshot": weighing_record["net_bushels"] if (weight_content and weighing_record) else None,
            "protein_reported_pct_snapshot": analysis["protein_reported_pct"] if analysis else None,
            "certified_quantity_bushels": request_row["certified_quantity_bushels"],
            "overtime_applied": overtime_applied,
            "fee_total_cents": fee_total_cents,
            "fee_paid_cents": 0,
            "fee_settlement_status": "UNPAID",
            "issued_at": issued_at,
            "reinspection_deadline_at": issued_at + days(5),
            "appeal_deadline_at": issued_at + days(10),
            "status": "ISSUED",
            "_weighing_record_id": weighing_record["id"] if (weight_content and weighing_record) else None,
            "_protein_analysis_id": analysis["id"] if analysis else None,
        }
    )
    db.certificates[cert["id"]] = cert
    if fee_total_cents:
        charge(applicant_row, fee_total_cents)
    return cert


# --------------------------------------------------------------------------
# the expiry sweep (PRD §2.5)
# --------------------------------------------------------------------------

def _sweep_key(row):
    return (row["created_at"], row.get("sequence_no") or row["_seq"])


def expiry_sweep():
    now = db.now
    expired_equipment = 0
    expired_samples = 0
    expired_inspectors = 0

    for row in sorted(db.equipment.values(), key=_sweep_key):
        if row["approval_status"] in ("APPROVED", "DRIFT_WATCH"):
            if row["certified_until"] is not None and row["certified_until"] <= now:
                row["approval_status"] = "EXPIRED"
                touch(row)
                expired_equipment += 1

    for row in sorted(db.samples.values(), key=_sweep_key):
        if row["integrity_status"] in ("SEALED", "CONSUMED"):
            if row["file_retention_until"] is not None and row["file_retention_until"] <= now:
                row["integrity_status"] = "EXPIRED"
                touch(row)
                expired_samples += 1

    for row in sorted(db.inspectors.values(), key=_sweep_key):
        if row["license_status"] in ("ACTIVE", "PROBATIONARY"):
            if row["license_expires_at"] is not None and row["license_expires_at"] <= now:
                row["license_status"] = "EXPIRED"
                touch(row)
                abort_watches(row, ("SCHEDULED",))
                expired_inspectors += 1

    return {
        "expired_equipment_count": expired_equipment,
        "expired_sample_count": expired_samples,
        "expired_inspector_count": expired_inspectors,
    }
