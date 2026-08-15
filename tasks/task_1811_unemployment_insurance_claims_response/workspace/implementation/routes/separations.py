"""ClaimantSeparation endpoints: intake and evidence-gated coding confirm."""
import re

from flask import Blueprint

from db import STORE
from errors import err, ERR_CODING_EVIDENCE_MISSING, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success
from services.core import find_or_404, new_record, serialize, touch
from util import as_dt, as_str, body_json, check_enum, req

bp = Blueprint("separations", __name__)

SEPARATION_REASONS = (
    "VOLUNTARY_QUIT",
    "DISCHARGE_MISCONDUCT",
    "DISCHARGE_NON_MISCONDUCT",
    "LAYOFF",
    "LEAVE_OF_ABSENCE",
)

MISCONDUCT_GATE_CATEGORIES = ("WRITTEN_WARNING", "SIGNED_POLICY", "FINAL_INCIDENT_REPORT")


@bp.post("/ui/separations")
def create_separation():
    require_roles("ClaimsAnalyst")
    body = body_json()
    employer_id = as_str(req(body, "employer_id"), "employer_id")
    claimant_name = as_str(req(body, "claimant_name"), "claimant_name")
    ssn_last4 = as_str(req(body, "ssn_last4"), "ssn_last4")
    if not re.fullmatch(r"\d{4}", ssn_last4):
        raise err(ERR_INVALID_REQUEST, 400, "ssn_last4 must be a 4-digit string")
    last_day_worked = as_dt(req(body, "last_day_worked"), "last_day_worked")
    separation_reason = check_enum(
        as_str(req(body, "separation_reason"), "separation_reason"),
        SEPARATION_REASONS, "separation_reason",
    )
    find_or_404(STORE.employers, employer_id, "employer")
    rec = new_record({
        "employer_id": employer_id,
        "claimant_name": claimant_name,
        "ssn_last4": ssn_last4,
        "last_day_worked": last_day_worked,
        "separation_reason": separation_reason,
        "reason_coding_confidence": "UNREVIEWED",
    })
    STORE.separations[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/ui/separations/<rid>")
def get_separation(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "AgencyLiaison")
    rec = find_or_404(STORE.separations, rid, "separation")
    return success(serialize(rec))


@bp.post("/ui/separations/<rid>/coding/confirm")
def confirm_coding(rid):
    require_roles("ClaimsAnalyst")
    sep = find_or_404(STORE.separations, rid, "separation")
    if sep["separation_reason"] == "DISCHARGE_MISCONDUCT":
        # Evidence gate: at least one warning/policy/incident document on some
        # claim referencing this separation.
        claim_ids = {
            c["id"] for c in STORE.claims.values() if c["separation_id"] == sep["id"]
        }
        found = any(
            d["claim_id"] in claim_ids and d["doc_category"] in MISCONDUCT_GATE_CATEGORIES
            for d in STORE.evidence.values()
        )
        if not found:
            raise err(
                ERR_CODING_EVIDENCE_MISSING,
                422,
                "misconduct coding confirm lacks warning/policy/incident evidence",
            )
    sep["reason_coding_confidence"] = "CONFIRMED"
    touch(sep)
    return success(serialize(sep))
