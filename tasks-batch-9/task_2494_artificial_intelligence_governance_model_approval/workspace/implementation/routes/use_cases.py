"""Use case intake, classification, bindings, oversight filings, notices,
approval, revocation, reassessment closure and the ledger read."""
from flask import Blueprint

import clock
import constants
import db
import errors
import response
import validators as v
from errors import ApiError
from middleware import authorize, current_user_id
from services import calc, cascades, guards, queries

bp = Blueprint("use_cases", __name__)

UPDATABLE_INTAKE_FIELDS = (
    "title",
    "description",
    "affects_individuals",
    "decision_autonomy",
    "data_sensitivity",
    "individual_impact",
    "jurisdictions",
    "deployed_headcount_reach",
)


def _snapshot(use_case, variant, computation, cleared_gate_count, passed_eval_count):
    record = {
        "use_case_id": use_case["id"],
        "cycle_index": use_case["classification_cycle_index"],
        "variant": variant,
        "impact_points": computation["impact_points"],
        "autonomy_points": computation["autonomy_points"],
        "sensitivity_points": computation["sensitivity_points"],
        "reach_points": computation["reach_points"],
        "jurisdiction_points": computation["jurisdiction_points"],
        "base_score": computation["base_score"],
        "vendor_penalty": computation["vendor_penalty"],
        "control_credit": computation["control_credit"],
        "cleared_gate_count": cleared_gate_count,
        "passed_eval_count": passed_eval_count,
        "risk_score": computation["risk_score"],
        "risk_tier": computation["risk_tier"],
        "forced_prohibited": computation["forced_prohibited"],
        "computed_at": clock.now(),
    }
    return db.insert(db.classification_snapshots, record)


# --- 10. POST /use-cases --------------------------------------------------
@bp.post("/use-cases")
@authorize(constants.REQUESTER)
def file_use_case():
    body = v.get_body()
    guards.resolve_use_case_fk(body, "predecessor_use_case_id")     # step 7
    title = v.as_str(body, "title", required=True, min_len=1, max_len=160)
    business_unit = v.as_str(body, "business_unit", required=True, min_len=1, max_len=40)
    description = v.as_str(body, "description", required=True, min_len=1, max_len=2000)
    affects_individuals = v.as_bool(body, "affects_individuals", required=True)
    decision_autonomy = v.as_enum(
        body, "decision_autonomy", constants.DECISION_AUTONOMY, required=True
    )
    data_sensitivity = v.as_enum(
        body, "data_sensitivity", constants.DATA_SENSITIVITY, required=True
    )
    individual_impact = v.as_enum(
        body, "individual_impact", constants.INDIVIDUAL_IMPACT, required=True
    )
    jurisdictions = v.as_enum_list(
        body, "jurisdictions", constants.JURISDICTIONS, required=True
    )
    deployed_headcount_reach = v.as_int(
        body, "deployed_headcount_reach", required=True, minimum=0
    )
    predecessor_use_case_id = v.as_str(body, "predecessor_use_case_id")

    record = {
        "title": title,
        "business_unit": business_unit,
        "description": description,
        "requester_user_id": current_user_id(),
        "affects_individuals": affects_individuals,
        "decision_autonomy": decision_autonomy,
        "data_sensitivity": data_sensitivity,
        "individual_impact": individual_impact,
        "jurisdictions": jurisdictions,
        "deployed_headcount_reach": deployed_headcount_reach,
        "predecessor_use_case_id": predecessor_use_case_id,
        "status": "DRAFT",
        "classification_stale": False,
        "classification_cycle_index": 0,
        "risk_score": None,
        "risk_tier": None,
        "required_gate_types": [],
        "final_risk_score": None,
        "final_risk_tier": None,
        "control_credit": None,
        "vendor_penalty": None,
        "open_conditions_count": 0,
        "cleared_gate_count": 0,
        "monitoring_posture": "HEALTHY",
        "safety_flag": False,
        "approved_at": None,
        "approved_by_user_id": None,
        "approval_expires_at": None,
        "reassessment_interval_days": None,
        "reassessment_due_at": None,
        "reassessment_cycle_index": 0,
        "reassessment_status": "NOT_SCHEDULED",
        "rejection_reason": None,
        "revoked_at": None,
        "revocation_reason": None,
        "updated_at": clock.now(),
        "version": 1,
    }
    db.insert(db.use_cases, record)
    return response.object_response(record, 201)


# --- 11. GET /use-cases --------------------------------------------------
@bp.get("/use-cases")
@authorize(*constants.ALL_ROLES)
def list_use_cases():
    status = v.query_str("status")
    risk_tier = v.query_str("risk_tier")
    final_risk_tier = v.query_str("final_risk_tier")
    business_unit = v.query_str("business_unit")
    predecessor_use_case_id = v.query_str("predecessor_use_case_id")
    limit, offset = v.pagination_params()

    records = db.all_of(db.use_cases)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if risk_tier is not None:
        records = [r for r in records if r["risk_tier"] == risk_tier]
    if final_risk_tier is not None:
        records = [r for r in records if r["final_risk_tier"] == final_risk_tier]
    if business_unit is not None:
        records = [r for r in records if r["business_unit"] == business_unit]
    if predecessor_use_case_id is not None:
        records = [
            r for r in records if r["predecessor_use_case_id"] == predecessor_use_case_id
        ]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 12. GET /use-cases/{id} --------------------------------------------
@bp.get("/use-cases/<use_case_id>")
@authorize(*constants.ALL_ROLES)
def read_use_case(use_case_id):
    return response.object_response(guards.get_use_case(use_case_id))


# --- 13. PATCH /use-cases/{id} -----------------------------------------
@bp.patch("/use-cases/<use_case_id>")
@authorize(constants.REQUESTER)
def revise_use_case(use_case_id):
    use_case = guards.get_use_case(use_case_id)                     # step 3
    if current_user_id() != use_case["requester_user_id"]:
        raise ApiError(
            errors.ERR_UNAUTHORIZED,
            "only the filing Requester may revise this use case",
        )
    body = v.get_body()                                             # step 8
    v.require_any_field(body, UPDATABLE_INTAKE_FIELDS)
    title = v.as_str(body, "title", min_len=1, max_len=160)
    description = v.as_str(body, "description", min_len=1, max_len=2000)
    affects_individuals = v.as_bool(body, "affects_individuals")
    decision_autonomy = v.as_enum(body, "decision_autonomy", constants.DECISION_AUTONOMY)
    data_sensitivity = v.as_enum(body, "data_sensitivity", constants.DATA_SENSITIVITY)
    individual_impact = v.as_enum(body, "individual_impact", constants.INDIVIDUAL_IMPACT)
    jurisdictions = v.as_enum_list(body, "jurisdictions", constants.JURISDICTIONS)
    deployed_headcount_reach = v.as_int(body, "deployed_headcount_reach", minimum=0)

    guards.check_not_terminal(use_case)                             # step 10
    if use_case["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError(
            errors.ERR_USE_CASE_NOT_IN_DRAFT,
            "intake data is editable only from DRAFT or CHANGES_REQUESTED",
        )

    if title is not None:
        use_case["title"] = title
    if description is not None:
        use_case["description"] = description
    if affects_individuals is not None:
        use_case["affects_individuals"] = affects_individuals
    if decision_autonomy is not None:
        use_case["decision_autonomy"] = decision_autonomy
    if data_sensitivity is not None:
        use_case["data_sensitivity"] = data_sensitivity
    if individual_impact is not None:
        use_case["individual_impact"] = individual_impact
    if jurisdictions is not None:
        use_case["jurisdictions"] = jurisdictions
    if deployed_headcount_reach is not None:
        use_case["deployed_headcount_reach"] = deployed_headcount_reach

    use_case["status"] = "DRAFT"
    use_case["classification_stale"] = True
    cascades.void_gates(use_case)
    db.touch(use_case)
    return response.object_response(use_case)


# --- 14. POST /use-cases/{id}/classify ---------------------------------
@bp.post("/use-cases/<use_case_id>/classify")
@authorize(constants.GOVERNANCE_OFFICER)
def classify_use_case(use_case_id):
    use_case = guards.get_use_case(use_case_id)                     # step 3
    body = v.get_body()                                             # step 8
    expected = v.as_int(body, "expected_use_case_version", required=True)
    guards.check_use_case_version(use_case, expected)               # step 9
    guards.check_not_terminal(use_case)                             # step 10
    if use_case["status"] != "DRAFT":                                # step 11
        raise ApiError(
            errors.ERR_USE_CASE_NOT_IN_DRAFT,
            "classification is permitted only from DRAFT",
        )

    use_case["classification_cycle_index"] += 1
    computation = calc.compute_risk(use_case, vendor_penalty=0, control_credit=0)
    use_case["risk_score"] = computation["risk_score"]
    use_case["risk_tier"] = computation["risk_tier"]
    use_case["classification_stale"] = False
    _snapshot(use_case, "INTAKE_PROVISIONAL", computation, 0, 0)
    cascades.void_gates(use_case)

    if computation["forced_prohibited"]:
        use_case["required_gate_types"] = []
        use_case["status"] = "REJECTED"
        use_case["rejection_reason"] = constants.FORCED_PROHIBITED_REASON
        cascades.append_ledger(
            use_case["id"],
            "CLASSIFICATION_REJECTED",
            current_user_id(),
            "classification rejected: %s" % constants.FORCED_PROHIBITED_REASON,
        )
    else:
        use_case["required_gate_types"] = list(
            constants.REQUIRED_GATES[use_case["risk_tier"]]
        )
        use_case["status"] = "UNDER_REVIEW"
        cascades.create_required_gates(use_case)
    cascades.recompute_use_case_counters(use_case)
    db.touch(use_case)
    return response.object_response(use_case)


# --- 15. GET /use-cases/{id}/classification-snapshots ------------------
@bp.get("/use-cases/<use_case_id>/classification-snapshots")
@authorize(*constants.ALL_ROLES)
def list_snapshots(use_case_id):
    guards.get_use_case(use_case_id)
    variant = v.query_str("variant")
    limit, offset = v.pagination_params()
    records = db.ordered(
        [
            s
            for s in db.classification_snapshots.values()
            if s["use_case_id"] == use_case_id
        ]
    )
    if variant is not None:
        records = [r for r in records if r["variant"] == variant]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 16. GET /use-cases/{id}/review-gates ------------------------------
@bp.get("/use-cases/<use_case_id>/review-gates")
@authorize(*constants.ALL_ROLES)
def list_review_gates(use_case_id):
    guards.get_use_case(use_case_id)
    status = v.query_str("status")
    gate_type = v.query_str("gate_type")
    limit, offset = v.pagination_params()
    records = queries.gates_of(use_case_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if gate_type is not None:
        records = [r for r in records if r["gate_type"] == gate_type]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 21. POST /use-cases/{id}/model-bindings ---------------------------
@bp.post("/use-cases/<use_case_id>/model-bindings")
@authorize(constants.GOVERNANCE_OFFICER)
def create_model_binding(use_case_id):
    use_case = guards.get_use_case(use_case_id)                     # step 3
    body = v.get_body()
    asset = guards.resolve_model_asset_fk(body)                      # step 7
    model_asset_id = v.as_str(body, "model_asset_id", required=True)  # step 8
    expected = v.as_int(body, "expected_use_case_version", required=True)
    guards.check_use_case_version(use_case, expected)               # step 9
    guards.check_not_terminal(use_case)                             # step 10
    if use_case["risk_tier"] == "PROHIBITED":                        # step 21
        raise ApiError(
            errors.ERR_PROHIBITED_USE_CASE,
            "a PROHIBITED use case cannot be bound to a model",
        )
    if asset["status"] != "APPROVED_FOR_USE":                        # step 30
        raise ApiError(
            errors.ERR_MODEL_ASSET_NOT_APPROVED_FOR_USE,
            "asset %s is not APPROVED_FOR_USE" % model_asset_id,
            http_status=422,
        )

    for binding in queries.bindings_of(use_case_id):
        if binding["status"] in ("PINNED", "STALE"):
            cascades.retire_binding(binding, "SUPERSEDED_BY_NEW_BINDING")

    record = {
        "use_case_id": use_case_id,
        "model_asset_id": model_asset_id,
        "pinned_model_version": asset["version"],
        "status": "PINNED",
        "pinned_at": clock.now(),
        "superseded_reason": None,
        "updated_at": clock.now(),
        "version": 1,
    }
    db.insert(db.model_bindings, record)
    asset["active_binding_count"] += 1
    db.touch(use_case)
    return response.object_response(record, 201)


# --- 22. GET /use-cases/{id}/model-bindings ----------------------------
@bp.get("/use-cases/<use_case_id>/model-bindings")
@authorize(*constants.ALL_ROLES)
def list_use_case_bindings(use_case_id):
    guards.get_use_case(use_case_id)
    status = v.query_str("status")
    limit, offset = v.pagination_params()
    records = queries.bindings_of(use_case_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 23. POST /use-cases/{id}/oversight-designs ------------------------
@bp.post("/use-cases/<use_case_id>/oversight-designs")
@authorize(constants.REQUESTER)
def file_oversight_design(use_case_id):
    use_case = guards.get_use_case(use_case_id)                     # step 3
    body = v.get_body()                                             # step 8
    review_mode = v.as_enum(body, "review_mode", constants.REVIEW_MODES, required=True)
    sample_pct = v.as_int(body, "sample_pct", required=True, minimum=0, maximum=100)
    escalation_sla_hours = v.as_int(
        body, "escalation_sla_hours", required=True, minimum=0, maximum=240
    )
    reviewer_role = v.as_enum(body, "reviewer_role", constants.REVIEWER_ROLES, required=True)
    override_capability = v.as_bool(body, "override_capability", required=True)
    expected = v.as_int(body, "expected_use_case_version", required=True)
    guards.check_use_case_version(use_case, expected)               # step 9
    guards.check_not_terminal(use_case)                             # step 10

    for design in queries.designs_of(use_case_id):
        if design["status"] == "DRAFT":
            design["status"] = "REJECTED"
            design["decided_by_user_id"] = constants.SYSTEM_ACTOR
            design["decided_at"] = clock.now()
            db.touch(design)

    record = {
        "use_case_id": use_case_id,
        "review_mode": review_mode,
        "sample_pct": sample_pct,
        "escalation_sla_hours": escalation_sla_hours,
        "reviewer_role": reviewer_role,
        "override_capability": override_capability,
        "status": "DRAFT",
        "adequacy_score": calc.adequacy_score(
            review_mode, sample_pct, escalation_sla_hours, override_capability
        ),
        "required_adequacy_score": calc.required_adequacy(
            use_case["risk_tier"], use_case["decision_autonomy"]
        ),
        "decided_by_user_id": None,
        "decided_at": None,
        "updated_at": clock.now(),
        "version": 1,
    }
    db.insert(db.oversight_designs, record)
    db.touch(use_case)
    return response.object_response(record, 201)


# --- 24. GET /use-cases/{id}/oversight-designs -------------------------
@bp.get("/use-cases/<use_case_id>/oversight-designs")
@authorize(*constants.ALL_ROLES)
def list_oversight_designs(use_case_id):
    guards.get_use_case(use_case_id)
    status = v.query_str("status")
    limit, offset = v.pagination_params()
    records = queries.designs_of(use_case_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 30. POST /use-cases/{id}/disclosure-notices -----------------------
@bp.post("/use-cases/<use_case_id>/disclosure-notices")
@authorize(constants.REQUESTER, constants.GOVERNANCE_OFFICER)
def publish_disclosure_notice(use_case_id):
    use_case = guards.get_use_case(use_case_id)                     # step 3
    body = v.get_body()                                             # step 8
    notice_type = v.as_enum(body, "notice_type", constants.NOTICE_TYPES, required=True)
    jurisdiction = v.as_enum(body, "jurisdiction", constants.JURISDICTIONS, required=True)
    effective_from = v.as_datetime(body, "effective_from", required=True)
    effective_to = v.as_datetime(body, "effective_to", required=True)
    locale_count = v.as_int(body, "locale_count", required=True, minimum=1)
    if effective_to <= effective_from:
        raise errors.bad_request("effective_to must be strictly after effective_from")
    guards.check_not_terminal(use_case)                             # step 10

    buffer_days = constants.NOTICE_QUIET_BUFFER_DAYS               # step 35
    for existing in queries.notices_of(use_case_id):
        if existing["status"] != "PUBLISHED":
            continue
        if existing["notice_type"] != notice_type or existing["jurisdiction"] != jurisdiction:
            continue
        if (
            effective_from <= clock.plus_days(existing["effective_to"], buffer_days)
            and existing["effective_from"] <= clock.plus_days(effective_to, buffer_days)
        ):
            raise ApiError(
                errors.ERR_DISCLOSURE_WINDOW_CONFLICT,
                "notice window collides with published notice %s including the "
                "%d-day quiet buffer" % (existing["id"], buffer_days),
            )

    record = {
        "use_case_id": use_case_id,
        "notice_type": notice_type,
        "jurisdiction": jurisdiction,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "locale_count": locale_count,
        "status": "PUBLISHED",
        "withdrawn_at": None,
        "updated_at": clock.now(),
        "version": 1,
    }
    db.insert(db.disclosure_notices, record)
    return response.object_response(record, 201)


# --- 31. GET /use-cases/{id}/disclosure-notices ------------------------
@bp.get("/use-cases/<use_case_id>/disclosure-notices")
@authorize(*constants.ALL_ROLES)
def list_disclosure_notices(use_case_id):
    guards.get_use_case(use_case_id)
    status = v.query_str("status")
    jurisdiction = v.query_str("jurisdiction")
    notice_type = v.query_str("notice_type")
    limit, offset = v.pagination_params()
    records = queries.notices_of(use_case_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if jurisdiction is not None:
        records = [r for r in records if r["jurisdiction"] == jurisdiction]
    if notice_type is not None:
        records = [r for r in records if r["notice_type"] == notice_type]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 33. POST /use-cases/{id}/approve ---------------------------------
@bp.post("/use-cases/<use_case_id>/approve")
@authorize(constants.GOVERNANCE_OFFICER)
def approve_use_case(use_case_id):
    use_case = guards.get_use_case(use_case_id)                     # step 3
    body = v.get_body()                                             # step 8
    expected = v.as_int(body, "expected_use_case_version", required=True)
    guards.check_use_case_version(use_case, expected)               # step 9
    guards.check_not_terminal(use_case)                             # step 10
    if use_case["status"] != "READY_FOR_APPROVAL":                   # step 13
        raise ApiError(
            errors.ERR_USE_CASE_NOT_READY_FOR_APPROVAL,
            "approval requires status READY_FOR_APPROVAL",
        )
    if use_case["classification_stale"]:
        raise ApiError(
            errors.ERR_USE_CASE_NOT_READY_FOR_APPROVAL,
            "the classification behind this use case is stale",
        )
    if use_case["risk_tier"] == "PROHIBITED":                        # step 21
        raise ApiError(
            errors.ERR_PROHIBITED_USE_CASE, "a PROHIBITED use case can never be approved"
        )
    if use_case["safety_flag"]:                                      # step 22
        raise ApiError(
            errors.ERR_BIAS_EVALUATION_FAILED,
            "the use case carries an unresolved failed bias evaluation",
        )
    passed_types = queries.passed_eval_types(use_case_id)            # step 23
    for eval_type in constants.REQUIRED_EVALS.get(use_case["risk_tier"], ()):
        if eval_type not in passed_types:
            raise ApiError(
                errors.ERR_REQUIRED_EVALUATION_MISSING,
                "tier %s requires a PASSED %s evaluation"
                % (use_case["risk_tier"], eval_type),
            )
    if not any(d["status"] == "APPROVED" for d in queries.designs_of(use_case_id)):
        raise ApiError(                                              # step 24
            errors.ERR_OVERSIGHT_DESIGN_NOT_APPROVED,
            "an APPROVED oversight design is required before approval",
        )
    actor = current_user_id()                                        # step 26
    if actor == use_case["requester_user_id"]:
        raise ApiError(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "the signing officer may not be the use case's requester",
        )
    gates = queries.gates_of(use_case_id)
    for gate in gates:
        if gate["status"] == "CLEARED" and gate["cleared_by_user_id"] == actor:
            raise ApiError(
                errors.ERR_SEGREGATION_OF_DUTIES,
                "the signing officer may not have cleared a gate on this use case",
            )
    binding = queries.pinned_binding_of(use_case_id)                 # step 28
    if binding is None:
        raise ApiError(
            errors.ERR_MODEL_BINDING_MISSING, "approval requires a PINNED model binding"
        )
    asset = db.model_assets.get(binding["model_asset_id"])
    if asset is None or binding["pinned_model_version"] != asset["version"]:
        raise ApiError(                                              # step 29
            errors.ERR_MODEL_BINDING_STALE,
            "the pinned binding no longer matches its asset's current version",
        )
    now = clock.now()                                                # step 34
    notices = queries.notices_of(use_case_id)
    for jurisdiction in use_case["jurisdictions"]:
        in_force = [
            n
            for n in notices
            if n["status"] == "PUBLISHED"
            and n["jurisdiction"] == jurisdiction
            and n["effective_from"] <= now <= n["effective_to"]
        ]
        if not in_force:
            raise ApiError(
                errors.ERR_DISCLOSURE_NOT_PUBLISHED,
                "no PUBLISHED disclosure notice is in force for jurisdiction %s"
                % jurisdiction,
            )

    # --- approval finalization, six pinned steps (PRD 3.10) ---------------
    cleared_gate_count = sum(1 for g in gates if g["status"] == "CLEARED")
    passed_eval_count = queries.passed_eval_count(use_case_id)
    control_credit = calc.control_credit(cleared_gate_count, passed_eval_count)
    vendor_penalty = calc.vendor_penalty_for_asset(asset)
    computation = calc.compute_risk(use_case, vendor_penalty, control_credit)
    final_risk_score = computation["risk_score"]
    final_risk_tier = computation["risk_tier"]

    if final_risk_tier == "HIGH":                                    # step 41
        portfolio = sum(
            u["deployed_headcount_reach"]
            for u in queries.inventory_use_cases()
            if u["final_risk_tier"] == "HIGH"
        )
        if portfolio + use_case["deployed_headcount_reach"] > constants.PORTFOLIO_HIGH_TIER_REACH_CAP:
            raise ApiError(
                errors.ERR_PORTFOLIO_REACH_CAP_EXCEEDED,
                "approving this use case would push HIGH-tier portfolio reach past %d"
                % constants.PORTFOLIO_HIGH_TIER_REACH_CAP,
            )

    interval = calc.reassessment_interval_days(final_risk_tier)
    due_at = clock.plus_days(now, interval)

    use_case["cleared_gate_count"] = cleared_gate_count
    use_case["control_credit"] = control_credit
    use_case["vendor_penalty"] = vendor_penalty
    use_case["final_risk_score"] = final_risk_score
    use_case["final_risk_tier"] = final_risk_tier
    use_case["status"] = "APPROVED"
    use_case["approved_at"] = now
    use_case["approved_by_user_id"] = actor
    use_case["approval_expires_at"] = due_at
    use_case["reassessment_interval_days"] = interval
    use_case["reassessment_due_at"] = due_at
    use_case["reassessment_cycle_index"] = 1
    use_case["reassessment_status"] = "SCHEDULED"
    use_case["monitoring_posture"] = "HEALTHY"
    _snapshot(
        use_case, "DEPLOYMENT_FINAL", computation, cleared_gate_count, passed_eval_count
    )
    cascades.append_ledger(
        use_case_id,
        "APPROVAL_GRANTED",
        actor,
        "approval granted at tier %s" % final_risk_tier,
        reach_delta=use_case["deployed_headcount_reach"],
    )
    db.touch(use_case)

    predecessor_id = use_case["predecessor_use_case_id"]
    if predecessor_id is not None:
        predecessor = db.use_cases.get(predecessor_id)
        if predecessor is not None and predecessor["status"] == "APPROVED":
            cascades.revoke_use_case(predecessor, "SUPERSEDED", actor)

    return response.object_response(use_case)


# --- 34. POST /use-cases/{id}/revoke ----------------------------------
@bp.post("/use-cases/<use_case_id>/revoke")
@authorize(constants.GOVERNANCE_OFFICER)
def revoke(use_case_id):
    use_case = guards.get_use_case(use_case_id)                     # step 3
    body = v.get_body()                                             # step 8
    revocation_reason = v.as_str(body, "revocation_reason", required=True)
    guards.check_not_terminal(use_case)                             # step 10
    if use_case["status"] not in (
        "READY_FOR_APPROVAL",
        "APPROVED",
        "UNDER_REASSESSMENT",
        "SUSPENDED",
    ):
        raise ApiError(
            errors.ERR_USE_CASE_NOT_READY_FOR_APPROVAL,
            "revocation is available only from READY_FOR_APPROVAL, APPROVED, "
            "UNDER_REASSESSMENT or SUSPENDED",
        )
    cascades.revoke_use_case(use_case, revocation_reason, current_user_id())
    return response.object_response(use_case)


# --- 35. POST /use-cases/{id}/complete-reassessment ------------------
@bp.post("/use-cases/<use_case_id>/complete-reassessment")
@authorize(constants.GOVERNANCE_OFFICER)
def complete_reassessment(use_case_id):
    use_case = guards.get_use_case(use_case_id)                     # step 3
    body = v.get_body()                                             # step 8
    outcome = v.as_enum(body, "outcome", constants.REASSESSMENT_OUTCOMES, required=True)
    guards.check_not_terminal(use_case)                             # step 10
    if use_case["status"] != "UNDER_REASSESSMENT":                    # step 14
        raise ApiError(
            errors.ERR_REASSESSMENT_NOT_DUE,
            "closing a reassessment requires status UNDER_REASSESSMENT",
        )
    actor = current_user_id()
    if actor == use_case["requester_user_id"]:                        # step 26
        raise ApiError(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "the closing officer may not be the use case's requester",
        )
    now = clock.now()
    expires_at = use_case["approval_expires_at"]                      # step 40
    if expires_at is not None and now > expires_at:
        raise ApiError(
            errors.ERR_APPROVAL_EXPIRED,
            "the approval expired at %s" % clock.iso(expires_at),
        )
    if outcome == "CONFIRMED" and use_case["monitoring_posture"] != "HEALTHY":
        raise ApiError(
            errors.ERR_REASSESSMENT_NOT_DUE,
            "a CONFIRMED outcome requires a HEALTHY monitoring posture",
        )

    interval = use_case["reassessment_interval_days"] or calc.reassessment_interval_days(
        use_case["final_risk_tier"]
    )
    next_due = clock.plus_days(now, interval)
    if outcome == "CONFIRMED":
        use_case["status"] = "APPROVED"
        use_case["reassessment_cycle_index"] += 1
        use_case["reassessment_due_at"] = next_due
        use_case["approval_expires_at"] = next_due
        use_case["reassessment_status"] = "SCHEDULED"
        cascades.append_ledger(
            use_case_id,
            "REASSESSMENT_COMPLETED",
            actor,
            "reassessment cycle %d confirmed" % use_case["reassessment_cycle_index"],
        )
        db.touch(use_case)
    else:
        use_case["reassessment_status"] = "SCHEDULED"
        use_case["reassessment_due_at"] = next_due
        cascades.suspend_use_case(
            use_case, actor, "approval suspended by reassessment outcome SUSPEND"
        )
    return response.object_response(use_case)


# --- 36. GET /use-cases/{id}/ledger-entries -------------------------
@bp.get("/use-cases/<use_case_id>/ledger-entries")
@authorize(constants.GOVERNANCE_OFFICER)
def list_ledger_entries(use_case_id):
    guards.get_use_case(use_case_id)
    entry_type = v.query_str("entry_type")
    limit, offset = v.pagination_params()
    records = queries.ledger_of(use_case_id)
    if entry_type is not None:
        records = [r for r in records if r["entry_type"] == entry_type]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)
