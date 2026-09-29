"""Service contract, spare pool and warranty case endpoints."""

from fractions import Fraction

from flask import Blueprint

import aggregates
import auth
import calc
import envelope
import serializers
import store
import validators as v
from errors import ApiError
from numeric import to_fraction

bp = Blueprint("service", __name__)


def _rank(module):
    """Colour-bin rank of a module (A1 0 ... B2 3); None when uncalibrated."""
    return module.get("color_bin_rank")


# ===========================================================================
# Service contracts
# ===========================================================================
@bp.route("/service-contracts", methods=["POST"])
def create_contract():
    auth.require("ServiceManager")
    body = v.body()
    project_id = v.get_id(body, "project_id")
    tier = v.get_enum(body, "tier", calc.TIERS)
    spare_pct_bp = v.get_int(body, "spare_pct_bp", minimum=0, maximum=5000)
    term_months = v.get_int(body, "term_months", minimum=12, maximum=120)

    project = store.display_projects.get(project_id)          # rung 5
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    # rung 41 — at most one contract per project
    for other in store.service_contracts.values():
        if other["project_id"] == project_id:
            raise ApiError("ERR_CONTRACT_ALREADY_EXISTS")
    # rung 54 — the tier's spare floor is checked only after uniqueness
    if spare_pct_bp < calc.TIER_MIN_SPARE_PCT_BP[tier]:
        raise ApiError("ERR_SPARE_PCT_BELOW_MINIMUM")

    required = calc.spare_required_count(project["module_count"], spare_pct_bp)
    fees = calc.annual_fee(project["total_area_sqm"], tier, required)
    rec = store.new_record({
        "project_id": project_id,
        "tier": tier,
        "spare_pct_bp": spare_pct_bp,
        "term_months": term_months,
        "response_hours": calc.TIER_RESPONSE_HOURS[tier],
        "spare_required_count": required,
        "gross_fee_cents": fees["gross_fee_cents"],
        "subtotal_fee_cents": fees["subtotal_fee_cents"],
        "volume_discount_pct": fees["volume_discount_pct"],
        "annual_fee_cents": fees["annual_fee_cents"],
        "sla_breach_count": 0,
        "warranty_start_at": None,
        "contract_state": "PENDING",
    })
    store.service_contracts[rec["id"]] = rec
    return envelope.object_response(serializers.service_contract(rec), 201)


@bp.route("/service-contracts/<service_contract_id>", methods=["GET"])
def get_contract(service_contract_id):
    auth.require(*auth.ALL_ROLES)
    rec = store.service_contracts.get(service_contract_id)
    if rec is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND")
    return envelope.object_response(serializers.service_contract(rec))


@bp.route("/service-contracts", methods=["GET"])
def list_contracts():
    auth.require(*auth.ALL_ROLES)
    limit, offset = v.pagination()
    project_id = v.query_str("project_id")
    state = v.query_enum("contract_state", calc.CONTRACT_STATES)
    rows = aggregates.by_created(store.service_contracts.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if state is not None:
        rows = [r for r in rows if r["contract_state"] == state]
    return envelope.paginated(rows, limit, offset, serializers.service_contract)


# ===========================================================================
# Spare pool
# ===========================================================================
def _spare_candidates(contract):
    """Free CALIBRATED stock of the contract's project model (selector filter a)."""
    project = store.display_projects.get(contract["project_id"])
    model_id = project["display_model_id"] if project is not None else None
    return [m for m in store.modules.values()
            if m["module_state"] == "CALIBRATED"
            and m["display_model_id"] == model_id
            and m["reserved_service_contract_id"] is None]


@bp.route("/service-contracts/<service_contract_id>/spare-reservations", methods=["POST"])
def reserve_spare(service_contract_id):
    auth.require("ServiceManager")
    body = v.body()
    module_id = v.get_id(body, "module_id", required=False)
    expected = v.get_int(body, "expected_service_contract_version")

    module = None
    if module_id is not None:                                  # rung 8
        module = store.modules.get(module_id)
        if module is None:
            raise ApiError("ERR_MODULE_NOT_FOUND")
    contract = store.service_contracts.get(service_contract_id)   # rung 11
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND")
    if expected != contract["version"]:                        # rung 15
        raise ApiError("ERR_STALE_CONTRACT_VERSION")
    if module is not None:
        if module["module_state"] != "CALIBRATED":             # rung 19
            raise ApiError("ERR_INVALID_MODULE_STATE")
    else:
        candidates = _spare_candidates(contract)
        if not candidates:                                     # rung 52
            raise ApiError("ERR_NO_ELIGIBLE_SPARE_MODULE")
        # colour_bin_rank DESC, measured_brightness_nits ASC, created_at ASC
        candidates.sort(key=lambda m: (-(m["color_bin_rank"] or 0),
                                       m["measured_brightness_nits"],
                                       m["created_at"], m["_seq"]))
        module = candidates[0]

    module["reserved_service_contract_id"] = contract["id"]
    store.touch(module)
    aggregates.contract_health(contract, False, "up")
    return envelope.object_response(serializers.module(module), 201)


@bp.route("/service-contracts/<service_contract_id>/spare-releases", methods=["POST"])
def release_spare(service_contract_id):
    auth.require("ServiceManager")
    body = v.body()
    module_id = v.get_id(body, "module_id")
    expected = v.get_int(body, "expected_service_contract_version")

    module = store.modules.get(module_id)                      # rung 8
    if module is None:
        raise ApiError("ERR_MODULE_NOT_FOUND")
    contract = store.service_contracts.get(service_contract_id)   # rung 11
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND")
    if expected != contract["version"]:                        # rung 15
        raise ApiError("ERR_STALE_CONTRACT_VERSION")
    if module["reserved_service_contract_id"] != contract["id"]:   # rung 50
        raise ApiError("ERR_SPARE_NOT_RESERVED")

    module["reserved_service_contract_id"] = None
    store.touch(module)
    aggregates.contract_health(contract, False, "pool_down")
    return envelope.object_response(serializers.module(module), 201)


# ===========================================================================
# Warranty cases
# ===========================================================================
@bp.route("/service-cases", methods=["POST"])
def open_case():
    auth.require("ServiceManager")
    body = v.body()
    contract_id = v.get_id(body, "service_contract_id")
    cabinet_id = v.get_id(body, "cabinet_id")
    case_type = v.get_enum(body, "case_type", calc.CASE_TYPES)
    severity = v.get_enum(body, "severity", calc.SEVERITIES)
    symptom = v.get_str(body, "symptom", min_len=0, max_len=240)
    # Payload symmetry is strict: each case type must omit the other's field.
    if case_type == "MODULE_FAULT":
        v.forbid(body, "measured_brightness_nits",
                 "measured_brightness_nits must be omitted for a MODULE_FAULT case.")
    else:
        v.forbid(body, "faulty_module_id",
                 "faulty_module_id must be omitted for a BRIGHTNESS_DEGRADATION case.")
    faulty_module_id = v.get_id(body, "faulty_module_id", required=False)
    brightness = v.get_int(body, "measured_brightness_nits", required=False, minimum=0)

    cab = store.cabinets.get(cabinet_id)                       # rung 7
    if cab is None:
        raise ApiError("ERR_CABINET_NOT_FOUND")
    faulty = None
    if faulty_module_id is not None:                            # rung 8
        faulty = store.modules.get(faulty_module_id)
        if faulty is None:
            raise ApiError("ERR_MODULE_NOT_FOUND")
    contract = store.service_contracts.get(contract_id)         # rung 11
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND")
    if contract["contract_state"] != "ACTIVE":                  # rung 24
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    # rung 39 — the cabinet must belong to the contract's project, and a
    # nominated faulty module must be installed in that very cabinet.
    if cab["project_id"] != contract["project_id"]:
        raise ApiError("ERR_MODULE_GRID_MISMATCH")
    if faulty is not None and (faulty["cabinet_id"] != cab["id"]
                               or faulty["module_state"] != "INSTALLED"):
        raise ApiError("ERR_MODULE_GRID_MISMATCH")
    # rung 47 — the measurement each type demands
    if case_type == "MODULE_FAULT" and faulty_module_id is None:
        raise ApiError("ERR_MEASUREMENT_REQUIRED")
    if case_type == "BRIGHTNESS_DEGRADATION" and brightness is None:
        raise ApiError("ERR_MEASUREMENT_REQUIRED")

    reported_at = store.logical_now()
    minutes = Fraction(contract["response_hours"] * 60) \
        * calc.SEVERITY_RESPONSE_MULTIPLIER[severity]
    deadline = store.add_minutes(reported_at, int(minutes))
    rec = store.new_record({
        "service_contract_id": contract_id,
        "cabinet_id": cabinet_id,
        "faulty_module_id": faulty_module_id,
        "case_type": case_type,
        "severity": severity,
        "symptom": symptom,
        "measured_brightness_nits": brightness,
        "reported_at": reported_at,
        "response_deadline_at": deadline,
        "responded_at": None,
        "response_breached": False,
        "elapsed_warranty_months": None,
        "allowed_degradation_pct": None,
        "degradation_pct": None,
        "shortfall_pct": None,
        "assessment_basis": None,
        "credit_cents": None,
        "denial_reason": None,
        "resolved_faulty_module_id": None,
        "replacement_module_id": None,
        "case_state": "OPEN",
    })
    store.service_cases[rec["id"]] = rec
    return envelope.object_response(serializers.service_case(rec), 201)


@bp.route("/service-cases/<service_case_id>/respond", methods=["POST"])
def respond_case(service_case_id):
    auth.require("ServiceManager")
    v.body()
    case = store.service_cases.get(service_case_id)             # rung 12
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    if case["case_state"] != "OPEN":                            # rung 23
        raise ApiError("ERR_INVALID_CASE_STATE")
    contract = store.service_contracts.get(case["service_contract_id"])
    if contract is None or contract["contract_state"] != "ACTIVE":   # rung 24
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")

    responded_at = store.logical_now()
    breached = store.ms(responded_at) > store.ms(case["response_deadline_at"])
    case["responded_at"] = responded_at
    case["response_breached"] = breached
    case["case_state"] = "RESPONDED"
    store.touch(case)
    if breached:
        contract["sla_breach_count"] += 1
        aggregates.contract_health(contract, False, "sla_down")
    return envelope.object_response(serializers.service_case(case))


@bp.route("/service-cases/<service_case_id>/assess", methods=["POST"])
def assess_case(service_case_id):
    auth.require("ServiceManager")
    body = v.body()
    decision = v.get_enum(body, "decision", ("APPROVE", "DENY"))
    basis = v.get_enum(body, "assessment_basis", calc.ASSESSMENT_BASES, required=False)

    case = store.service_cases.get(service_case_id)             # rung 12
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    if case["case_state"] != "RESPONDED":                       # rung 23
        raise ApiError("ERR_INVALID_CASE_STATE")
    contract = store.service_contracts.get(case["service_contract_id"])
    if contract is None or contract["contract_state"] != "ACTIVE":   # rung 24
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")

    if decision == "DENY":
        reason = v.get_str(body, "denial_reason", min_len=1, max_len=240)
        case["denial_reason"] = reason
        case["credit_cents"] = 0
        case["assessment_basis"] = None
        case["resolved_faulty_module_id"] = None
        case["replacement_module_id"] = None
        case["case_state"] = "DENIED"
        store.touch(case)
        return envelope.object_response(serializers.service_case(case))

    cab = store.cabinets.get(case["cabinet_id"])
    model = aggregates.model_of_cabinet(cab)
    months = None
    allowed = None
    degradation = None
    shortfall = None
    if case["case_type"] == "BRIGHTNESS_DEGRADATION":
        seconds = (store.ms(case["reported_at"])
                   - store.ms(contract["warranty_start_at"])) // 1000
        months = calc.elapsed_warranty_months(seconds)
        allowed, degradation, shortfall = calc.degradation_figures(
            model, case["measured_brightness_nits"], months)
        if to_fraction(shortfall) <= 0:                         # rung 48
            raise ApiError("ERR_DEGRADATION_WITHIN_ALLOWANCE")

    installed = aggregates.installed_modules(cab["id"])
    if not installed:                                            # rung 49
        raise ApiError("ERR_NO_REPLACEABLE_MODULE")

    if case["case_type"] == "BRIGHTNESS_DEGRADATION":
        if basis is None:
            v.fail("Field 'assessment_basis' is required to approve a "
                   "BRIGHTNESS_DEGRADATION case.")
        # faulty_module_selector: dimmest INSTALLED panel, created_at ASC
        installed.sort(key=lambda m: (m["measured_brightness_nits"],
                                      m["created_at"], m["_seq"]))
        resolved = installed[0]["id"]
        credit = calc.credit_cents(basis, calc.cabinet_value_cents(model),
                                   months, shortfall)
    else:
        # MODULE_FAULT skips the degradation arithmetic entirely.
        resolved = case["faulty_module_id"]
        credit = 0

    case["elapsed_warranty_months"] = months
    case["allowed_degradation_pct"] = allowed
    case["degradation_pct"] = degradation
    case["shortfall_pct"] = shortfall
    case["assessment_basis"] = basis
    case["credit_cents"] = credit
    case["denial_reason"] = None
    case["resolved_faulty_module_id"] = resolved
    case["case_state"] = "APPROVED"
    store.touch(case)
    return envelope.object_response(serializers.service_case(case))


@bp.route("/service-cases/<service_case_id>/fulfil", methods=["POST"])
def fulfil_case(service_case_id):
    auth.require("ServiceManager")
    body = v.body()
    replacement_id = v.get_id(body, "replacement_module_id", required=False)
    expected = v.get_int(body, "expected_cabinet_version")

    replacement = None
    if replacement_id is not None:                               # rung 8
        replacement = store.modules.get(replacement_id)
        if replacement is None:
            raise ApiError("ERR_MODULE_NOT_FOUND")
    case = store.service_cases.get(service_case_id)              # rung 12
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    cab = store.cabinets.get(case["cabinet_id"])
    if cab is None:
        raise ApiError("ERR_CABINET_NOT_FOUND")
    if expected != cab["version"]:                               # rung 14
        raise ApiError("ERR_STALE_CABINET_VERSION")
    if case["case_state"] != "APPROVED":                         # rung 23
        raise ApiError("ERR_INVALID_CASE_STATE")
    contract = store.service_contracts.get(case["service_contract_id"])
    if contract is None or contract["contract_state"] != "ACTIVE":   # rung 24
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")

    outgoing = store.modules.get(case["resolved_faulty_module_id"])
    out_rank = (_rank(outgoing) or 0) if outgoing is not None else 0
    if replacement is not None:
        if replacement["reserved_service_contract_id"] != case["service_contract_id"]:
            raise ApiError("ERR_SPARE_NOT_RESERVED")             # rung 50
        if abs((_rank(replacement) or 0) - out_rank) > calc.COLOR_BIN_RANK_TOLERANCE:
            raise ApiError("ERR_COLOR_BIN_MISMATCH")             # rung 51
    else:
        project = store.display_projects.get(contract["project_id"])
        model_id = project["display_model_id"] if project is not None else None
        candidates = [m for m in store.modules.values()
                      if m["module_state"] == "CALIBRATED"
                      and m["display_model_id"] == model_id
                      and m["reserved_service_contract_id"] == case["service_contract_id"]
                      and abs((m["color_bin_rank"] or 0) - out_rank)
                      <= calc.COLOR_BIN_RANK_TOLERANCE]
        if not candidates:                                       # rung 52
            raise ApiError("ERR_NO_ELIGIBLE_SPARE_MODULE")
        candidates.sort(key=lambda m: (abs((m["color_bin_rank"] or 0) - out_rank),
                                       -m["measured_brightness_nits"],
                                       m["created_at"], m["_seq"]))
        replacement = candidates[0]

    # hop 1 — the case records the spare and reaches its terminal state
    case["replacement_module_id"] = replacement["id"]
    case["case_state"] = "FULFILLED"
    store.touch(case)
    # hop 2 — the swap itself; the outgoing module keeps its cabinet_id
    slot = None
    if outgoing is not None:
        slot = outgoing["slot_index"]
        outgoing["module_state"] = "RETURNED"
        outgoing["slot_index"] = None
        store.touch(outgoing)
    replacement["module_state"] = "INSTALLED"
    replacement["cabinet_id"] = cab["id"]
    replacement["slot_index"] = slot
    replacement["replaces_module_id"] = outgoing["id"] if outgoing is not None else None
    replacement["reserved_service_contract_id"] = None
    store.touch(replacement)
    # the cabinet's as-built quality figures move with its new module set
    store.touch(cab)
    # hops 3 and 4 — the spare pool drawdown may suspend the contract
    aggregates.contract_health(contract, False, "pool_down")
    return envelope.object_response(serializers.service_case(case))


@bp.route("/service-cases/<service_case_id>", methods=["GET"])
def get_case(service_case_id):
    auth.require(*auth.ALL_ROLES)
    case = store.service_cases.get(service_case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    return envelope.object_response(serializers.service_case(case))


@bp.route("/service-cases", methods=["GET"])
def list_cases():
    auth.require(*auth.ALL_ROLES)
    limit, offset = v.pagination()
    filters = {
        "service_contract_id": v.query_str("service_contract_id"),
        "cabinet_id": v.query_str("cabinet_id"),
        "faulty_module_id": v.query_str("faulty_module_id"),
        "resolved_faulty_module_id": v.query_str("resolved_faulty_module_id"),
        "replacement_module_id": v.query_str("replacement_module_id"),
        "case_type": v.query_enum("case_type", calc.CASE_TYPES),
        "case_state": v.query_enum("case_state", calc.CASE_STATES),
    }
    rows = aggregates.by_created(store.service_cases.values())
    for field, wanted in filters.items():
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return envelope.paginated(rows, limit, offset, serializers.service_case)
