"""RateCase endpoints (PRD 3.1, 3.3-3.8)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_DATE_RANGE,
    ERR_DEFICIENCY_NOTES_REQUIRED,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_TARIFF_STATE,
    ERR_INVALID_ASSET_STATE,
    ERR_NO_TEST_YEAR_ENTRIES,
    ERR_ENTRIES_NOT_LOCKED,
    ERR_UNRESOLVED_ADJUSTMENTS,
    ERR_NO_RATE_BASE_ITEMS,
    ERR_NONPOSITIVE_REVENUE_REQUIREMENT,
    ERR_RR_MISMATCH,
    ERR_OVERDUE_DATA_REQUESTS_EXIST,
    ERR_NO_RECOMMENDED_SETTLEMENT,
    ERR_CLASS_TARIFF_MISSING,
    ERR_NO_ACCEPTED_FILING,
    ERR_CASE_NUMBER_NOT_UNIQUE,
    ERR_TARIFF_NOT_FOUND,
    ERR_ASSET_NOT_FOUND,
    ERR_CLASS_NOT_IN_CASE,
    ERR_CLASS_NOT_FOUND,
)
from middleware import authorized, ALL_READ_ROLES
from response import success_object
from routes.helpers import get_one, list_response, query_arg, serialize_case
from services.calculations import (
    amortization_amounts,
    class_cost_allocation,
    revenue_requirement,
    tiered_marginal_cents,
)
from services.core import new_record, recompute_entry_adjusted, touch
from util import CLOCK, parse_datetime, fmt_datetime, round_half_up_signed
from validate import (
    get_body,
    no_unknown_fields,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    req_str_list,
    require_path_resource,
)

bp = Blueprint("rate_cases", __name__)

CASE_STATUSES = (
    "DRAFT", "FILED", "DEFICIENT", "ACCEPTED", "DISCOVERY", "HEARING",
    "SETTLEMENT", "ORDER_PENDING", "DECIDED", "RATES_IMPLEMENTED",
    "COMPLIANCE_MONITORING", "CLOSED",
)


def _load_case(case_id):
    return require_path_resource("rate_cases", case_id)


@bp.post("/rate-cases")
def create_rate_case():
    body = get_body()
    no_unknown_fields(body, {
        "case_number", "utility_name", "test_year_start", "test_year_end",
        "return_on_rate_base_bp", "proposed_revenue_requirement_cents",
        "allocation_method",
    })
    case_number = req_str(body, "case_number")
    utility_name = req_str(body, "utility_name")
    ty_start = req_datetime(body, "test_year_start")
    ty_end = req_datetime(body, "test_year_end")
    ror_bp = req_int(body, "return_on_rate_base_bp", minimum=1, maximum=3000)
    proposed_rr = req_int(body, "proposed_revenue_requirement_cents")
    method = req_enum(body, "allocation_method", ("COINCIDENT_PEAK", "ENERGY_AVERAGE"))
    if parse_datetime(ty_end) <= parse_datetime(ty_start):
        raise_error(ERR_INVALID_DATE_RANGE, "test_year_end must be strictly after test_year_start")
    authorized(["UtilityFiler"])
    for other in db["rate_cases"].values():
        if other["case_number"] == case_number:
            raise_error(ERR_CASE_NUMBER_NOT_UNIQUE, f"case_number {case_number} already exists")
    rec = new_record("rate_cases", {
        "case_number": case_number,
        "utility_name": utility_name,
        "test_year_start": fmt_datetime(parse_datetime(ty_start)),
        "test_year_end": fmt_datetime(parse_datetime(ty_end)),
        "return_on_rate_base_bp": ror_bp,
        "proposed_revenue_requirement_cents": proposed_rr,
        "allocation_method": method,
        "discovery_close_at": None,
        "authorized_revenue_requirement_cents": None,
        "overdue_data_request_count": 0,
        "assented_proposal_count": 0,
        "status": "DRAFT",
    })
    return success_object(serialize_case(rec), status=201)


@bp.get("/rate-cases")
def list_rate_cases():
    return list_response("rate_cases")


@bp.get("/rate-cases/<case_id>")
def get_rate_case(case_id):
    return get_one("rate_cases", case_id)


def _transition(case, allowed_from, new_status):
    if case["status"] not in allowed_from:
        raise_error(
            ERR_INVALID_CASE_STATE,
            f"case is {case['status']}; requires {' or '.join(allowed_from)}",
        )
    case["status"] = new_status
    touch(case)


@bp.post("/rate-cases/<case_id>/submit-filing")
def submit_filing(case_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["UtilityFiler"])
    case = _load_case(case_id)
    if case["status"] not in ("DRAFT", "DEFICIENT"):
        raise_error(ERR_INVALID_CASE_STATE, "submit-filing requires DRAFT or DEFICIENT")
    # Pinned case-level guard order (PRD 3.3)
    entries = [e for e in db["test_year_entries"].values() if e["rate_case_id"] == case["id"]]
    if len(entries) == 0:
        raise_error(ERR_NO_TEST_YEAR_ENTRIES, "at least one TestYearEntry is required")
    if any(e["status"] != "LOCKED" for e in entries):
        raise_error(ERR_ENTRIES_NOT_LOCKED, "every TestYearEntry must be LOCKED")
    if any(
        a["rate_case_id"] == case["id"] and a["status"] in ("PROPOSED", "DISPUTED")
        for a in db["adjustments"].values()
    ):
        raise_error(ERR_UNRESOLVED_ADJUSTMENTS, "case has PROPOSED or DISPUTED adjustments")
    if not any(
        i["rate_case_id"] == case["id"] and i["status"] in ("SUBMITTED", "AUDITED")
        for i in db["rate_base_items"].values()
    ):
        raise_error(ERR_NO_RATE_BASE_ITEMS, "at least one RateBaseItem must be SUBMITTED or AUDITED")
    # Pinned fiscal guard order
    rr = revenue_requirement(case, "as_filed")
    if rr["revenue_requirement_cents"] <= 0:
        raise_error(ERR_NONPOSITIVE_REVENUE_REQUIREMENT,
                    "computed as-filed revenue requirement must be > 0")
    if abs(case["proposed_revenue_requirement_cents"] - rr["revenue_requirement_cents"]) > 100:
        raise_error(ERR_RR_MISMATCH,
                    "proposed revenue requirement differs from computed as-filed by more than 100 cents")
    # Acceptance cascade: every VERIFIED adjustment -> ACCEPTED
    for a in db["adjustments"].values():
        if a["rate_case_id"] == case["id"] and a["status"] == "VERIFIED":
            a["status"] = "ACCEPTED"
            touch(a)
            entry = db["test_year_entries"].get(a["test_year_entry_id"])
            if entry is not None:
                recompute_entry_adjusted(entry)
    case["status"] = "FILED"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/rate-cases/<case_id>/deficiency-review")
def deficiency_review(case_id):
    body = get_body()
    no_unknown_fields(body, {"outcome", "deficiency_notes"})
    outcome = req_enum(body, "outcome", ("ACCEPTED", "DEFICIENT"))
    notes = body.get("deficiency_notes")
    if outcome == "DEFICIENT" and (notes is None or not isinstance(notes, str) or notes.strip() == ""):
        raise_error(ERR_DEFICIENCY_NOTES_REQUIRED, "deficiency_notes required when outcome is DEFICIENT")
    authorized(["CommissionStaff"])
    case = _load_case(case_id)
    if case["status"] != "FILED":
        raise_error(ERR_INVALID_CASE_STATE, "deficiency-review requires FILED")
    case["status"] = "ACCEPTED" if outcome == "ACCEPTED" else "DEFICIENT"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/rate-cases/<case_id>/open-discovery")
def open_discovery(case_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["CommissionStaff"])
    case = _load_case(case_id)
    if case["status"] != "ACCEPTED":
        raise_error(ERR_INVALID_CASE_STATE, "open-discovery requires ACCEPTED")
    from util import plus_days_iso
    case["discovery_close_at"] = plus_days_iso(CLOCK.now(), 120)
    case["status"] = "DISCOVERY"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/rate-cases/<case_id>/advance-to-hearing")
def advance_to_hearing(case_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["ALJ"])
    case = _load_case(case_id)
    if case["status"] != "DISCOVERY":
        raise_error(ERR_INVALID_CASE_STATE, "advance-to-hearing requires DISCOVERY")
    if case["overdue_data_request_count"] != 0:
        raise_error(ERR_OVERDUE_DATA_REQUESTS_EXIST, "overdue data requests exist")
    case["status"] = "HEARING"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/rate-cases/<case_id>/open-settlement-window")
def open_settlement_window(case_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["ALJ"])
    case = _load_case(case_id)
    if case["status"] != "HEARING":
        raise_error(ERR_INVALID_CASE_STATE, "open-settlement-window requires HEARING")
    case["status"] = "SETTLEMENT"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/rate-cases/<case_id>/advance-to-order-pending")
def advance_to_order_pending(case_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["ALJ"])
    case = _load_case(case_id)
    if case["status"] != "SETTLEMENT":
        raise_error(ERR_INVALID_CASE_STATE, "advance-to-order-pending requires SETTLEMENT")
    if not any(
        p["rate_case_id"] == case["id"] and p["status"] == "RECOMMENDED"
        for p in db["settlement_proposals"].values()
    ):
        raise_error(ERR_NO_RECOMMENDED_SETTLEMENT, "no RECOMMENDED settlement proposal")
    case["status"] = "ORDER_PENDING"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/rate-cases/<case_id>/issue-order")
def issue_order(case_id):
    body = get_body()
    no_unknown_fields(body, {"approved_tariff_ids", "approved_asset_ids"})
    tariff_ids = req_str_list(body, "approved_tariff_ids")
    asset_ids = req_str_list(body, "approved_asset_ids")
    authorized(["ALJ"])
    case = _load_case(case_id)
    if case["status"] != "ORDER_PENDING":
        raise_error(ERR_INVALID_CASE_STATE, "issue-order requires ORDER_PENDING")
    # Existence of all ids (tariffs before assets), then state/case membership
    tariffs = []
    for tid in tariff_ids:
        t = db["tariff_rates"].get(tid)
        if t is None:
            raise_error(ERR_TARIFF_NOT_FOUND, f"tariff id not found: {tid}")
        tariffs.append(t)
    assets = []
    for aid in asset_ids:
        a = db["regulatory_assets"].get(aid)
        if a is None:
            raise_error(ERR_ASSET_NOT_FOUND, f"asset id not found: {aid}")
        assets.append(a)
    for t in tariffs:
        if t["rate_case_id"] != case["id"] or t["status"] != "PROPOSED":
            raise_error(ERR_INVALID_TARIFF_STATE,
                        "approved tariff ids must reference PROPOSED tariffs of this case")
    for a in assets:
        if a["rate_case_id"] != case["id"] or a["status"] != "DEFERRED":
            raise_error(ERR_INVALID_ASSET_STATE,
                        "approved asset ids must reference DEFERRED assets of this case")
    # Adopt the RECOMMENDED proposal (largest round_number if several)
    recommended = [
        p for p in db["settlement_proposals"].values()
        if p["rate_case_id"] == case["id"] and p["status"] == "RECOMMENDED"
    ]
    adopted = max(recommended, key=lambda p: p["round_number"]) if recommended else None
    if adopted is not None:
        case["authorized_revenue_requirement_cents"] = adopted["proposed_revenue_requirement_cents"]
        adopted["status"] = "ADOPTED"
        touch(adopted)
    approved_set = set(tariff_ids)
    for t in [t for t in db["tariff_rates"].values()
              if t["rate_case_id"] == case["id"] and t["status"] == "PROPOSED"]:
        if t["id"] in approved_set:
            t["status"] = "APPROVED"
            touch(t)
            cls = db["customer_classes"].get(t["customer_class_id"])
            if cls is not None:
                cls["approved_revenue_cents"] = t["proposed_revenue_cents"]
                touch(cls)
        else:
            t["status"] = "REJECTED"
            touch(t)
    approved_assets = set(asset_ids)
    for a in [a for a in db["regulatory_assets"].values()
              if a["rate_case_id"] == case["id"] and a["status"] == "DEFERRED"]:
        if a["id"] in approved_assets:
            a["status"] = "APPROVED_FOR_AMORTIZATION"
            touch(a)
            for idx, amount in enumerate(
                amortization_amounts(a["principal_cents"], a["amortization_months"]), start=1
            ):
                new_record("amortization_entries", {
                    "regulatory_asset_id": a["id"],
                    "rate_case_id": case["id"],
                    "period_index": idx,
                    "amount_cents": amount,
                    "posted_at": None,
                    "status": "PENDING",
                })
        else:
            a["status"] = "DISALLOWED"
            touch(a)
    case["status"] = "DECIDED"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/rate-cases/<case_id>/implement-rates")
def implement_rates(case_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["UtilityFiler"])
    case = _load_case(case_id)
    if case["status"] != "DECIDED":
        raise_error(ERR_INVALID_CASE_STATE, "implement-rates requires DECIDED")
    classes = [c for c in db["customer_classes"].values() if c["rate_case_id"] == case["id"]]
    for c in classes:
        if not any(
            t["customer_class_id"] == c["id"] and t["status"] == "APPROVED"
            for t in db["tariff_rates"].values()
        ):
            raise_error(ERR_CLASS_TARIFF_MISSING,
                        f"class {c['class_code']} has no APPROVED tariff")
    for t in db["tariff_rates"].values():
        if t["rate_case_id"] == case["id"] and t["status"] == "APPROVED":
            t["status"] = "EFFECTIVE"
            touch(t)
    for a in db["regulatory_assets"].values():
        if a["rate_case_id"] == case["id"] and a["status"] == "APPROVED_FOR_AMORTIZATION":
            a["status"] = "AMORTIZING"
            touch(a)
    case["status"] = "RATES_IMPLEMENTED"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/rate-cases/<case_id>/begin-compliance-monitoring")
def begin_compliance_monitoring(case_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["CommissionStaff"])
    case = _load_case(case_id)
    if case["status"] != "RATES_IMPLEMENTED":
        raise_error(ERR_INVALID_CASE_STATE, "begin-compliance-monitoring requires RATES_IMPLEMENTED")
    case["status"] = "COMPLIANCE_MONITORING"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/rate-cases/<case_id>/close")
def close_case(case_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["ALJ"])
    case = _load_case(case_id)
    if case["status"] != "COMPLIANCE_MONITORING":
        raise_error(ERR_INVALID_CASE_STATE, "close requires COMPLIANCE_MONITORING")
    if not any(
        f["rate_case_id"] == case["id"] and f["status"] == "ACCEPTED"
        for f in db["compliance_filings"].values()
    ):
        raise_error(ERR_NO_ACCEPTED_FILING, "no ACCEPTED compliance filing")
    case["status"] = "CLOSED"
    touch(case)
    return success_object(serialize_case(case))


# ---------------------------------------------------------------------------
# Computed reads (PRD 3.8)
# ---------------------------------------------------------------------------

@bp.get("/rate-cases/<case_id>/revenue-requirement")
def get_revenue_requirement(case_id):
    variant = query_arg("variant")
    if variant is None:
        variant = "as_filed"
    if variant not in ("as_filed", "as_audited"):
        raise_error(ERR_INVALID_REQUEST, "variant must be as_filed or as_audited")
    authorized(ALL_READ_ROLES)
    case = _load_case(case_id)
    return success_object(revenue_requirement(case, variant))


@bp.get("/rate-cases/<case_id>/cost-allocation")
def get_cost_allocation(case_id):
    method = query_arg("method")
    authorized(ALL_READ_ROLES)
    case = _load_case(case_id)
    if method is None:
        method = case["allocation_method"]
    if method not in ("COINCIDENT_PEAK", "ENERGY_AVERAGE"):
        raise_error(ERR_INVALID_REQUEST, "method must be COINCIDENT_PEAK or ENERGY_AVERAGE")
    return success_object(class_cost_allocation(case, method))


@bp.get("/rate-cases/<case_id>/bill-impact")
def get_bill_impact(case_id):
    class_id = query_arg("customer_class_id")
    if class_id is None:
        raise_error(ERR_INVALID_REQUEST, "customer_class_id is required")
    kwh_raw = query_arg("monthly_kwh")
    if kwh_raw is None:
        raise_error(ERR_INVALID_REQUEST, "monthly_kwh is required")
    try:
        monthly_kwh = int(kwh_raw)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "monthly_kwh must be an integer")
    if monthly_kwh < 0:
        raise_error(ERR_INVALID_REQUEST, "monthly_kwh must be >= 0")
    tariff_id = query_arg("tariff_id")
    authorized(ALL_READ_ROLES)
    case = _load_case(case_id)
    cls = db["customer_classes"].get(class_id)
    if cls is None:
        raise_error(ERR_CLASS_NOT_FOUND, f"class id not found: {class_id}")
    tariff = None
    if tariff_id is not None:
        tariff = db["tariff_rates"].get(tariff_id)
        if tariff is None:
            raise_error(ERR_TARIFF_NOT_FOUND, f"tariff id not found: {tariff_id}")
    if cls["rate_case_id"] != case["id"]:
        raise_error(ERR_CLASS_NOT_IN_CASE, "customer_class_id belongs to a different case")
    if tariff is None:
        # Selection rule: EFFECTIVE with the latest effective_start; else the
        # most recently created PROPOSED tariff of the class; else 404.
        effective = [
            t for t in db["tariff_rates"].values()
            if t["customer_class_id"] == cls["id"] and t["status"] == "EFFECTIVE"
        ]
        if effective:
            tariff = max(effective, key=lambda t: (parse_datetime(t["effective_start"]), t["_seq"]))
        else:
            proposed = [
                t for t in db["tariff_rates"].values()
                if t["customer_class_id"] == cls["id"] and t["status"] == "PROPOSED"
            ]
            if proposed:
                tariff = max(proposed, key=lambda t: (t["created_at"], t["_seq"]))
            else:
                raise_error(ERR_TARIFF_NOT_FOUND, "no EFFECTIVE or PROPOSED tariff for the class")
    present_bill = cls["present_customer_charge_cents"] + tiered_marginal_cents(
        monthly_kwh, cls["present_tiers"])
    if present_bill <= 0:
        raise_error(ERR_INVALID_REQUEST, "present bill must be > 0 to compute impact")
    proposed_bill = tariff["proposed_customer_charge_cents"] + tiered_marginal_cents(
        monthly_kwh, tariff["proposed_tiers"])
    impact_bp = round_half_up_signed(10000 * (proposed_bill - present_bill), present_bill)
    return success_object({
        "present_bill_cents": present_bill,
        "proposed_bill_cents": proposed_bill,
        "impact_pct_bp": impact_bp,
    })
