"""GapFinding endpoints (PRD §3.3): list/get and disposition."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_RATIONALE_REQUIRED,
    ERR_FINDING_INVALID_STATE,
    ERR_STUDY_NOT_IN_REMEDIATION,
    ERR_FINDING_NOT_ACTIONABLE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import (
    touch, recompute_study_aggregates, check_study_auto_monitoring,
)
from validate import get_body, require_path_resource

bp = Blueprint("findings", __name__)

DISPOSITIONS = {"TARGETED", "MONITORED", "DISMISSED"}


@bp.get("/gap-findings")
def list_findings():
    return list_response("gap_findings", {
        "study_id": request.args.get("study_id"),
        "comparator_group_id": request.args.get("comparator_group_id"),
        "model_run_id": request.args.get("model_run_id"),
        "status": request.args.get("status"),
    })


@bp.get("/gap-findings/<rid>")
def get_finding(rid):
    return get_one("gap_findings", rid)


@bp.post("/gap-findings/<rid>/disposition")
def disposition_finding(rid):
    caller = authorized(["CompAnalyst"])
    finding = require_path_resource("gap_findings", rid)
    body = get_body()
    # Priority 3.7 (shape) before priority 4 (state) per PRD §2.8
    disposition = body.get("disposition")
    if disposition not in DISPOSITIONS:
        raise_error(ERR_INVALID_REQUEST,
                    "disposition must be TARGETED, MONITORED, or DISMISSED")
    rationale = body.get("disposition_rationale")
    if disposition == "DISMISSED":
        if rationale is None or not isinstance(rationale, str) or rationale.strip() == "":
            raise_error(ERR_RATIONALE_REQUIRED,
                        "disposition_rationale is required for DISMISSED")
    # Priority 4: state preconditions (finding first, then study)
    if finding["status"] != "FLAGGED":
        raise_error(ERR_FINDING_INVALID_STATE, "disposition requires a FLAGGED finding")
    study = db["pay_equity_studies"].get(finding["study_id"])
    if study is None or study["status"] != "REMEDIATION_OPEN":
        raise_error(ERR_STUDY_NOT_IN_REMEDIATION,
                    "finding disposition requires the study to be REMEDIATION_OPEN")
    # Priority 7: actionability for TARGETED
    if disposition == "TARGETED" and not finding["is_actionable"]:
        raise_error(ERR_FINDING_NOT_ACTIONABLE,
                    "TARGETED disposition requires is_actionable == true")

    finding["status"] = disposition
    finding["disposition_by_user_id"] = caller.user_id
    if disposition == "DISMISSED":
        finding["disposition_rationale"] = rationale
    touch(finding)

    recompute_study_aggregates(finding["study_id"])
    # Auto-monitoring check after every disposition (PRD §3.3)
    check_study_auto_monitoring(finding["study_id"])
    return success_object(public(finding))
