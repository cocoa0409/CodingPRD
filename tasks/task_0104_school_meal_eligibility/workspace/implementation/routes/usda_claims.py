"""UsdaReimbursementClaim endpoints. PRD §3.7."""

from flask import Blueprint, request, g

from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, stamp_common, lock, touch, iso_from_dt
from core.validation import (
    require_body, require_field, parse_iso8601, check_version,
)

from services.calculations import usda_rate_for_tier
from services.derived import student_allergy_blocks_menu_item
from services.relationships import (
    get_district_or_404, get_usda_claim_in_district,
)
from services.views import usda_claim_view


bp = Blueprint("usda_claims", __name__)


def _to_midnight_iso(field_name: str, value) -> str:
    """Parse an ISO 8601 instant and canonicalise it to the same string form we
    use throughout the API (3 fractional digits, trailing Z)."""
    if not isinstance(value, str):
        raise_error("ERR_VALIDATION", f"{field_name} must be a string")
    dt = parse_iso8601(value, field_name)
    return iso_from_dt(dt)


@bp.post("/districts/<district_id>/usda-claims")
@require_roles("AuditOfficer")
def create_claim(district_id):
    with lock():
        get_district_or_404(district_id)
        body = require_body(request)
        ps_raw = require_field(body, "period_start", kind="string")
        pe_raw = require_field(body, "period_end", kind="string")
        ps = _to_midnight_iso("period_start", ps_raw)
        pe = _to_midnight_iso("period_end", pe_raw)
        if pe < ps:
            raise_error("ERR_VALIDATION",
                        "period_end must be >= period_start")
        c = {
            "district_id": district_id,
            "period_start": ps,
            "period_end": pe,
            "status": "DRAFT",
            "serving_record_ids": [],
            "final_reimbursement_cents": 0,
            "provisional_total_cents": 0,
        }
        stamp_common(c)
        STORE.usda_claims[c["id"]] = c
        return success_object(usda_claim_view(c), status=201)


@bp.get("/districts/<district_id>/usda-claims/<claim_id>")
@require_roles("AuditOfficer")
def get_claim(district_id, claim_id):
    with lock():
        get_district_or_404(district_id)
        c = get_usda_claim_in_district(district_id, claim_id)
        return success_object(usda_claim_view(c))


@bp.post("/districts/<district_id>/usda-claims/<claim_id>/submit")
@require_roles("AuditOfficer")
def submit_claim(district_id, claim_id):
    with lock():
        get_district_or_404(district_id)
        c = get_usda_claim_in_district(district_id, claim_id)
        body = require_body(request)
        check_version(body, c)
        if c["status"] != "DRAFT":
            raise_error("ERR_INVALID_STATE",
                        f"Claim is not in DRAFT state (current={c['status']})")
        if c["period_end"] < c["period_start"]:
            raise_error("ERR_VALIDATION",
                        "period_end must be >= period_start")
        # Overlap check: against any other SUBMITTED/FINALIZED claim in same district.
        for other in STORE.usda_claims.values():
            if other["id"] == c["id"]:
                continue
            if other["district_id"] != district_id:
                continue
            if other["status"] not in ("SUBMITTED", "FINALIZED"):
                continue
            # Closed-closed overlap.
            if (other["period_end"] >= c["period_start"]
                    and other["period_start"] <= c["period_end"]):
                raise_error("ERR_CLAIM_PERIOD_OVERLAP",
                            "Another claim in {SUBMITTED, FINALIZED} overlaps this period")
        c["status"] = "SUBMITTED"
        touch(c)
        return success_object(usda_claim_view(c))


@bp.post("/districts/<district_id>/usda-claims/<claim_id>/finalize")
@require_roles("AuditOfficer")
def finalize_claim(district_id, claim_id):
    with lock():
        get_district_or_404(district_id)
        c = get_usda_claim_in_district(district_id, claim_id)
        body = require_body(request)
        check_version(body, c)
        if c["status"] != "SUBMITTED":
            raise_error("ERR_INVALID_STATE",
                        f"Claim is not in SUBMITTED state (current={c['status']})")
        # Snapshot rows: SERVED records with serving_date in [period_start, period_end].
        # Ordered by created_at ASC, id ASC.
        contained = []
        for r in STORE.meal_serving_records.values():
            if r["district_id"] != district_id:
                continue
            if r["status"] != "SERVED":
                continue
            if c["period_start"] <= r["serving_date"] <= c["period_end"]:
                contained.append(r)
        contained.sort(key=lambda r: (r["created_at"], r["id"]))
        # Segregation of duties: the AuditOfficer must not be the
        # DistrictReviewer who approved any FrlApplication minting a tier of
        # any student appearing in the contained rows. We check both the
        # currently-governing FrlApplication for the student AND any historical
        # APPROVED app for that student in this district.
        student_ids = {r["student_id"] for r in contained}
        for app in STORE.frl_applications.values():
            if app["district_id"] != district_id:
                continue
            if app["student_id"] not in student_ids:
                continue
            if app["status"] != "APPROVED":
                continue
            if app.get("reviewer_user_id") == g.user_id:
                raise_error("ERR_SEGREGATION_OF_DUTIES",
                            "AuditOfficer was the DistrictReviewer who approved a contained FrlApplication")
        # Chronological replay (usda_reimbursement_final).
        running_total = 0
        for r in contained:
            if r["status"] != "SERVED":
                continue  # already voided; contributes 0
            student = STORE.students[r["student_id"]]
            menu_item = STORE.menu_items[r["menu_item_id"]]
            eff_tier = student.get("eligibility_tier", "PAID")
            rate = usda_rate_for_tier(eff_tier, menu_item["reimbursable"])
            # Allergy block at finalize time overrides to 0.
            if student_allergy_blocks_menu_item(student, menu_item):
                rate = 0
            running_total += rate
        provisional_total = sum(
            r.get("provisional_reimbursement_cents", 0) or 0
            for r in contained
        )
        c["serving_record_ids"] = [r["id"] for r in contained]
        c["provisional_total_cents"] = provisional_total
        c["final_reimbursement_cents"] = running_total
        c["status"] = "FINALIZED"
        touch(c)
        return success_object(usda_claim_view(c))


@bp.post("/districts/<district_id>/usda-claims/<claim_id>/reject")
@require_roles("AuditOfficer")
def reject_claim(district_id, claim_id):
    with lock():
        get_district_or_404(district_id)
        c = get_usda_claim_in_district(district_id, claim_id)
        body = require_body(request)
        check_version(body, c)
        if c["status"] != "SUBMITTED":
            raise_error("ERR_INVALID_STATE",
                        f"Claim is not in SUBMITTED state (current={c['status']})")
        c["status"] = "REJECTED"
        touch(c)
        return success_object(usda_claim_view(c))
