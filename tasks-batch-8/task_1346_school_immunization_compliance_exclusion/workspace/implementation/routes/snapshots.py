"""ComplianceSnapshot endpoints (PRD §3.9)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from db import clock, parse_iso, format_iso, stamp_new, touch
from errors import (
    ApiError,
    ERR_SNAPSHOT_EXISTS,
    ERR_SNAPSHOT_FINALIZED,
    ERR_SNAPSHOT_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import success_object
from services.evaluation import (
    GRADES,
    applicable_requirements,
    evaluate_requirement,
    snapshot_view,
)
from services.validate import req_datetime, req_enum, req_string, require_body

RATE_VARIANTS = ("CENSUS_DATE", "EVER_ENROLLED")


def _round_half_up_1(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _cell_members(school_code, grade, census_date, variant):
    """Membership per PRD §3.9."""
    members = []
    for s in db.students.values():
        if s["school_code"] != school_code or s["grade"] != grade:
            continue
        enroll = parse_iso(s["enrollment_date"])
        if enroll > census_date:
            continue
        if variant == "CENSUS_DATE" and s["status"] == "WITHDRAWN":
            continue
        members.append(s)
    return members


def _student_reconciled_compliant(student):
    """All applicable requirements SATISFIED under REGISTRY_RECONCILED."""
    for req in applicable_requirements(student):
        if not evaluate_requirement(student, req, "REGISTRY_RECONCILED"):
            return False
    return True


def _student_has_approved_exemption(student):
    for ex in db.exemption_requests.values():
        if ex["student_id"] == student["id"] and ex["status"] == "APPROVED":
            return True
    return False


def register(app):

    @app.post("/api/compliance-snapshots/generate")
    def generate_snapshot():
        require_roles("RegistryCoordinator")
        body = require_body(request.get_json(silent=True))
        school_year = req_string(body, "school_year")
        school_code = req_string(body, "school_code")
        grade = req_enum(body, "grade", GRADES)
        census_date = req_datetime(body, "census_date")
        rate_variant = req_enum(body, "rate_variant", RATE_VARIANTS)

        # 8f: reject if a FINALIZED snapshot exists for the same cell
        for existing in db.compliance_snapshots.values():
            if existing["school_year"] == school_year \
                    and existing["school_code"] == school_code \
                    and existing["grade"] == grade \
                    and existing["rate_variant"] == rate_variant:
                if existing["status"] == "FINALIZED":
                    raise ApiError(
                        ERR_SNAPSHOT_EXISTS,
                        "A FINALIZED snapshot already exists for this cell.",
                        409,
                    )
                else:
                    # DRAFT: supersede by regenerating — drop old draft.
                    del db.compliance_snapshots[existing["id"]]
                    break

        members = _cell_members(school_code, grade, census_date, rate_variant)
        enrolled_count = len(members)
        compliant_count = sum(1 for s in members if _student_reconciled_compliant(s))
        exempt_count = sum(1 for s in members if _student_has_approved_exemption(s))
        if enrolled_count == 0:
            compliance_rate = None
        else:
            rate = Decimal("100") * Decimal(compliant_count) / Decimal(enrolled_count)
            compliance_rate = _round_half_up_1(rate)

        snapshot = {
            "school_year": school_year,
            "school_code": school_code,
            "grade": grade,
            "census_date": format_iso(census_date),
            "rate_variant": rate_variant,
            "enrolled_count": enrolled_count,
            "compliant_count": compliant_count,
            "exempt_count": exempt_count,
            "compliance_rate": compliance_rate,
            "status": "DRAFT",
        }
        stamp_new(snapshot)
        db.compliance_snapshots[snapshot["id"]] = snapshot
        return success_object(snapshot_view(snapshot), status=201)

    @app.post("/api/compliance-snapshots/<sid>/finalize")
    def finalize_snapshot(sid):
        require_roles("DistrictHealthOfficer")
        snapshot = db.compliance_snapshots.get(sid)
        if snapshot is None:
            raise ApiError(ERR_SNAPSHOT_NOT_FOUND, "Snapshot not found.", 404)
        if snapshot["status"] != "DRAFT":
            raise ApiError(
                ERR_SNAPSHOT_FINALIZED,
                "finalize requires the snapshot to be in DRAFT.",
                409,
            )
        snapshot["status"] = "FINALIZED"
        touch(snapshot)
        return success_object(snapshot_view(snapshot))

    @app.post("/api/compliance-snapshots/district-rollup")
    def district_rollup():
        require_roles("DistrictHealthOfficer")
        body = require_body(request.get_json(silent=True))
        school_year = req_string(body, "school_year")
        grade = req_enum(body, "grade", GRADES)
        # census_date = current clock; membership CENSUS_DATE variant
        census_date = clock.now()

        # All school_codes present among students of this grade enrolled on/before census_date
        school_codes = set()
        for s in db.students.values():
            if s["grade"] != grade:
                continue
            enroll = parse_iso(s["enrollment_date"])
            if enroll > census_date:
                continue
            school_codes.add(s["school_code"])

        weighted_sum = Decimal("0")
        enrolled_total = 0
        schools_included = 0
        for code in school_codes:
            members = _cell_members(code, grade, census_date, "CENSUS_DATE")
            enrolled = len(members)
            if enrolled == 0:
                continue
            compliant = sum(1 for s in members if _student_reconciled_compliant(s))
            rate_s = Decimal("100") * Decimal(compliant) / Decimal(enrolled)
            rounded_rate_s = Decimal(str(_round_half_up_1(rate_s)))
            weighted_sum += rounded_rate_s * Decimal(enrolled)
            enrolled_total += enrolled
            schools_included += 1

        if schools_included == 0:
            district_rate = None
        else:
            district_rate = _round_half_up_1(weighted_sum / Decimal(enrolled_total))

        return success_object({
            "school_year": school_year,
            "grade": grade,
            "district_rate": district_rate,
            "schools_included": schools_included,
            "enrolled_total": enrolled_total,
        })
