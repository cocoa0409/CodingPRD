"""Oversight design decisions."""
from flask import Blueprint

import clock
import constants
import db
import errors
import response
import validators as v
from errors import ApiError
from middleware import authorize, current_user_id
from services import calc, guards

bp = Blueprint("oversight", __name__)


# --- 25. POST /oversight-designs/{id}/decide ---------------------------
@bp.post("/oversight-designs/<design_id>/decide")
@authorize(constants.GOVERNANCE_OFFICER)
def decide_oversight_design(design_id):
    design = guards.get_record(                                     # step 6
        db.oversight_designs, design_id, "oversight design"
    )
    body = v.get_body()                                             # step 8
    decision = v.as_enum(body, "decision", constants.DESIGN_DECISIONS, required=True)
    use_case = db.use_cases.get(design["use_case_id"])
    guards.check_not_terminal(use_case)                             # step 10
    if design["status"] != "DRAFT":                                  # step 15
        raise ApiError(
            errors.ERR_ASSESSMENT_ALREADY_DECIDED,
            "oversight design %s is already %s" % (design_id, design["status"]),
        )
    if use_case is not None and use_case["risk_tier"] == "PROHIBITED":
        raise ApiError(                                              # step 21
            errors.ERR_PROHIBITED_USE_CASE,
            "an oversight design on a PROHIBITED use case cannot be decided",
        )

    # adequacy is re-evaluated at decision time against the current tier
    design["adequacy_score"] = calc.adequacy_score(
        design["review_mode"],
        design["sample_pct"],
        design["escalation_sla_hours"],
        design["override_capability"],
    )
    design["required_adequacy_score"] = calc.required_adequacy(
        use_case["risk_tier"], use_case["decision_autonomy"]
    ) if use_case is not None else None

    if decision == "APPROVE":                                        # step 25
        required = design["required_adequacy_score"]
        if required is None or design["adequacy_score"] < required:
            raise ApiError(
                errors.ERR_OVERSIGHT_DESIGN_INADEQUATE,
                "adequacy_score %s does not meet the required %s"
                % (design["adequacy_score"], required),
            )

    design["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    design["decided_by_user_id"] = current_user_id()
    design["decided_at"] = clock.now()
    db.touch(design)
    return response.object_response(design)
