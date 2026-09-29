"""Review gate actions: take-up, conditions, clearance and reopening."""
from decimal import Decimal

from flask import Blueprint

import clock
import constants
import db
import errors
import response
import validators as v
from errors import ApiError
from middleware import authorize, current_role, current_user_id
from services import calc, cascades, guards, queries

bp = Blueprint("review_gates", __name__)


def _parent(gate):
    return db.use_cases.get(gate["use_case_id"])


def _check_gate_role(gate):
    """Step 27: the acting role must own the gate_type."""
    if constants.GATE_ROLE_MAP[gate["gate_type"]] != current_role():
        raise ApiError(
            errors.ERR_GATE_ROLE_MISMATCH,
            "role %s does not own %s gates" % (current_role(), gate["gate_type"]),
        )


def _gate_state_error(gate, allowed):
    return ApiError(
        errors.ERR_GATE_NOT_IN_REVIEWABLE_STATE,
        "gate %s is %s; this action requires one of %s"
        % (gate["id"], gate["status"], ", ".join(allowed)),
    )


def _bubble_after_condition_change(use_case):
    cascades.recompute_use_case_counters(use_case)
    if use_case["open_conditions_count"] == 0 and use_case["status"] == "CHANGES_REQUESTED":
        use_case["status"] = "UNDER_REVIEW"


# --- 17. POST /review-gates/{id}/start-review ---------------------------
@bp.post("/review-gates/<gate_id>/start-review")
@authorize(*constants.REVIEWER_ROLES)
def start_review(gate_id):
    gate = guards.get_review_gate(gate_id)                          # step 5
    use_case = _parent(gate)
    guards.check_not_terminal(use_case)                             # step 10
    if gate["status"] not in ("PENDING", "CONDITIONS_ISSUED"):       # step 12
        raise _gate_state_error(gate, ("PENDING", "CONDITIONS_ISSUED"))
    if use_case["status"] not in ("UNDER_REVIEW", "CHANGES_REQUESTED"):
        raise ApiError(
            errors.ERR_GATE_NOT_IN_REVIEWABLE_STATE,
            "gate review is permitted only while the use case is UNDER_REVIEW or "
            "CHANGES_REQUESTED",
        )
    _check_gate_role(gate)                                          # step 27

    was_conditions_issued = gate["status"] == "CONDITIONS_ISSUED"
    gate["status"] = "IN_REVIEW"
    gate["assigned_reviewer_user_id"] = current_user_id()
    if was_conditions_issued:
        gate["conditions"] = []
        gate["open_condition_count"] = 0
        gate["control_debt_index"] = Decimal("0.00")
    db.touch(gate)
    _bubble_after_condition_change(use_case)
    return response.object_response(gate)


# --- 18. POST /review-gates/{id}/issue-conditions -----------------------
@bp.post("/review-gates/<gate_id>/issue-conditions")
@authorize(*constants.REVIEWER_ROLES)
def issue_conditions(gate_id):
    gate = guards.get_review_gate(gate_id)                          # step 5
    body = v.get_body()                                             # step 8
    conditions = v.as_str_list(body, "conditions", required=True, min_len=1, max_len=20)
    decision_note = v.as_str(body, "decision_note")
    use_case = _parent(gate)
    guards.check_not_terminal(use_case)                             # step 10
    if gate["status"] != "IN_REVIEW":                                # step 12
        raise _gate_state_error(gate, ("IN_REVIEW",))
    _check_gate_role(gate)                                          # step 27

    gate["status"] = "CONDITIONS_ISSUED"
    gate["conditions"] = conditions
    gate["open_condition_count"] = len(conditions)
    gate["control_debt_index"] = calc.gate_control_debt(
        gate["gate_type"], len(conditions), gate["pinned_risk_tier"]
    )
    if decision_note is not None:
        gate["decision_note"] = decision_note
    db.touch(gate)

    cascades.recompute_use_case_counters(use_case)
    if use_case["status"] == "UNDER_REVIEW":
        use_case["status"] = "CHANGES_REQUESTED"
    return response.object_response(gate)


# --- 19. POST /review-gates/{id}/clear ---------------------------------
@bp.post("/review-gates/<gate_id>/clear")
@authorize(*constants.REVIEWER_ROLES)
def clear_gate(gate_id):
    gate = guards.get_review_gate(gate_id)                          # step 5
    body = v.get_body()                                             # step 8
    decision_note = v.as_str(body, "decision_note")
    use_case = _parent(gate)
    guards.check_not_terminal(use_case)                             # step 10
    if gate["status"] not in ("IN_REVIEW", "CONDITIONS_ISSUED"):      # step 12
        raise _gate_state_error(gate, ("IN_REVIEW", "CONDITIONS_ISSUED"))
    if (
        gate["pinned_classification_index"] != use_case["classification_cycle_index"]
        or use_case["classification_stale"]
    ):
        raise ApiError(
            errors.ERR_GATE_NOT_IN_REVIEWABLE_STATE,
            "gate %s is pinned to a superseded classification" % gate_id,
        )

    # step 23: the SECURITY gate demands a passed red-team run, and only that
    if gate["gate_type"] == "SECURITY":
        if "SECURITY_REDTEAM" not in queries.passed_eval_types(use_case["id"]):
            raise ApiError(
                errors.ERR_REQUIRED_EVALUATION_MISSING,
                "a SECURITY gate requires a PASSED SECURITY_REDTEAM evaluation",
            )

    actor = current_user_id()
    if actor == use_case["requester_user_id"]:                        # step 26
        raise ApiError(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "the clearing reviewer may not be the use case's requester",
        )
    _check_gate_role(gate)                                          # step 27

    if gate["gate_type"] == "LEGAL":
        binding = queries.pinned_binding_of(use_case["id"])           # step 28
        if binding is None:
            raise ApiError(
                errors.ERR_MODEL_BINDING_MISSING,
                "a LEGAL gate requires the use case to hold a PINNED model binding",
            )
        asset = db.model_assets.get(binding["model_asset_id"])         # step 31
        if asset is not None and asset["is_third_party"]:
            acceptable = [
                a
                for a in queries.accepted_assessments_of(asset["id"])
                if a["terms_grade"] in constants.ACCEPTABLE_VENDOR_GRADES
            ]
            if not acceptable:
                raise ApiError(
                    errors.ERR_VENDOR_ASSESSMENT_NOT_ACCEPTED,
                    "the bound third-party asset holds no ACCEPTED assessment graded "
                    "A, B or C",
                )

    if gate["gate_type"] == "PRIVACY":                               # step 34
        published = queries.notices_of(use_case["id"])
        for jurisdiction in use_case["jurisdictions"]:
            if not any(
                n["status"] == "PUBLISHED" and n["jurisdiction"] == jurisdiction
                for n in published
            ):
                raise ApiError(
                    errors.ERR_DISCLOSURE_NOT_PUBLISHED,
                    "jurisdiction %s has no PUBLISHED disclosure notice" % jurisdiction,
                )

    debt_before_clear = Decimal(gate["control_debt_index"])
    gate["debt_before_clear"] = debt_before_clear
    gate["control_debt_index"] = Decimal("0.00")
    gate["open_condition_count"] = 0
    gate["status"] = "CLEARED"
    gate["cleared_by_user_id"] = actor
    gate["cleared_at"] = clock.now()
    if decision_note is not None:
        gate["decision_note"] = decision_note
    db.touch(gate)

    cascades.append_ledger(
        use_case["id"],
        "GATE_CLEARED",
        actor,
        "%s gate cleared" % gate["gate_type"],
        debt_delta=-debt_before_clear,
    )
    cascades.recompute_use_case_counters(use_case)
    live = queries.live_gates_of(use_case["id"])
    if (
        use_case["status"] == "UNDER_REVIEW"
        and live
        and all(g["status"] == "CLEARED" for g in live)
        and use_case["cleared_gate_count"] == len(use_case["required_gate_types"])
    ):
        use_case["status"] = "READY_FOR_APPROVAL"
    return response.object_response(gate)


# --- 20. POST /review-gates/{id}/reopen -------------------------------
@bp.post("/review-gates/<gate_id>/reopen")
@authorize(constants.GOVERNANCE_OFFICER)
def reopen_gate(gate_id):
    gate = guards.get_review_gate(gate_id)                          # step 5
    body = v.get_body()                                             # step 8
    decision_note = v.as_str(body, "decision_note")
    use_case = _parent(gate)
    guards.check_not_terminal(use_case)                             # step 10
    if gate["status"] != "CLEARED":                                  # step 12
        raise _gate_state_error(gate, ("CLEARED",))
    if use_case["status"] not in ("UNDER_REVIEW", "CHANGES_REQUESTED", "READY_FOR_APPROVAL"):
        raise ApiError(
            errors.ERR_GATE_NOT_IN_REVIEWABLE_STATE,
            "reopening is permitted only while the use case is UNDER_REVIEW, "
            "CHANGES_REQUESTED or READY_FOR_APPROVAL",
        )

    debt_before_clear = Decimal(gate["debt_before_clear"])
    gate["status"] = "IN_REVIEW"
    gate["control_debt_index"] = debt_before_clear
    gate["open_condition_count"] = 0
    gate["cleared_by_user_id"] = None
    gate["cleared_at"] = None
    if decision_note is not None:
        gate["decision_note"] = decision_note
    db.touch(gate)

    cascades.append_ledger(
        use_case["id"],
        "GATE_REOPENED",
        current_user_id(),
        "%s gate reopened" % gate["gate_type"],
        debt_delta=debt_before_clear,
    )
    cascades.recompute_use_case_counters(use_case)
    if use_case["status"] == "READY_FOR_APPROVAL":
        use_case["status"] = "UNDER_REVIEW"
    return response.object_response(gate)
