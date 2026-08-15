"""Receivership Fiduciary API — Flask application.

All endpoints under /v1. In-memory store, logical clock, OCC on Case.version
for the two cash-debiting payment endpoints. Validation cascade per PRD §2.10:
auth(1) -> role(2) -> shape(3) -> existence(4) -> OCC(5) -> from-state(6) ->
cross-entity state gates(7) -> authority gate(8) -> court-calendar gates(9) ->
uniqueness/interval/aggregate in fixed sub-order(10) -> collateral usability(11)
-> fiscal checks(12).
"""
import os
from datetime import timedelta

from flask import Flask

import errors
import middleware
import services as svc
from db import store, iso_out
from response import success_object, success_list, error_response

app = Flask(__name__)


@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(errors.err_not_found("Route not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(errors.err_not_found("Route not found"))


@app.errorhandler(500)
def handle_500(e):
    return error_response(errors.ApiError("ERR_INTERNAL", "Internal server error", 500))


def _touch(entity):
    entity["updated_at"] = store.now_iso()
    entity["version"] += 1


def _new_entity(entity_id):
    now_iso = store.now_iso()
    return {
        "id": entity_id,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "_created_dt": store.now(),
    }


# ===========================================================================
# Cases
# ===========================================================================

@app.post("/v1/cases")
def create_case():
    middleware.require_roles("Court")
    body = svc.get_json_body()
    case_number = svc.require_string(body, "case_number")
    court_jurisdiction = svc.require_string(body, "court_jurisdiction")
    debtor_name = svc.require_string(body, "debtor_name")
    appointed_receiver_name = svc.require_string(body, "appointed_receiver_name")
    appointment_effective_at = svc.parse_dt(
        svc.require_field(body, "appointment_effective_at"), "appointment_effective_at"
    )
    authority_limit_cents = svc.require_nonnegative_int(body, "authority_limit_cents")
    business_operation_authorized = svc.require_bool(body, "business_operation_authorized")
    bar_date = svc.parse_dt(svc.require_field(body, "bar_date"), "bar_date")
    reporting_interval_days = svc.require_positive_int(body, "reporting_interval_days")
    operating_reserve_cents = svc.require_nonnegative_int(body, "operating_reserve_cents")

    # (10a) unique case_number per court_jurisdiction
    for c in store.cases.values():
        if c["case_number"] == case_number and c["court_jurisdiction"] == court_jurisdiction:
            raise errors.err_duplicate_case_number()

    case = _new_entity(store.new_id())
    case.update(
        case_number=case_number,
        court_jurisdiction=court_jurisdiction,
        debtor_name=debtor_name,
        appointed_receiver_name=appointed_receiver_name,
        authority_limit_cents=authority_limit_cents,
        business_operation_authorized=business_operation_authorized,
        reporting_interval_days=reporting_interval_days,
        operating_reserve_cents=operating_reserve_cents,
        status="ACTIVE",
        cash_on_hand_cents=0,
        marshalled_value_cents=0,
        allowed_claims_total_cents=0,
        posture="NORMAL",
        _appointment_effective_at=appointment_effective_at,
        _bar_date=bar_date,
    )
    store.cases[case["id"]] = case
    return success_object(svc.serialize_case(case), 201)


@app.get("/v1/cases/<case_id>")
def get_case(case_id):
    middleware.require_roles("Court", "Receiver", "Creditor")
    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")
    return success_object(svc.serialize_case(case))


@app.post("/v1/cases/<case_id>/discharge")
def discharge_case(case_id):
    middleware.require_roles("Court")
    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")
    # (6) from-state: discharge requires DISTRIBUTING
    if case["status"] != "DISTRIBUTING":
        raise errors.err_invalid_state("Discharge requires the case to be DISTRIBUTING")
    # (10h) aggregate preconditions
    plans = svc.case_plans(case_id)
    if not any(p["status"] == "EXECUTED" for p in plans):
        raise errors.err_discharge_blocked("No plan of this case is EXECUTED")
    if any(c["status"] == "FILED" for c in svc.case_claims(case_id)):
        raise errors.err_discharge_blocked("A claim of this case is still FILED")
    if any(f["status"] in ("FILED", "APPROVED") for f in svc.case_fee_applications(case_id)):
        raise errors.err_discharge_blocked("A fee application of this case is FILED or APPROVED")
    if not any(
        r["report_type"] == "FINAL" and r["status"] == "ACCEPTED"
        for r in svc.case_reports(case_id)
    ):
        raise errors.err_discharge_blocked("No ACCEPTED FINAL status report exists")
    if any(a["status"] == "IDENTIFIED" for a in svc.case_assets(case_id)):
        raise errors.err_discharge_blocked("An asset of this case is still IDENTIFIED")
    svc.recompute_case_derived(case)
    if case["cash_on_hand_cents"] != 0:
        raise errors.err_discharge_blocked("cash_on_hand_cents is not zero")

    case["status"] = "DISCHARGED"
    _touch(case)
    # side effect: every engagement APPROVED or EXHAUSTED -> CLOSED
    for e in svc.case_engagements(case_id):
        if e["status"] in ("APPROVED", "EXHAUSTED"):
            e["status"] = "CLOSED"
            _touch(e)
    return success_object(svc.serialize_case(case))


@app.get("/v1/cases/<case_id>/assets")
def list_case_assets(case_id):
    middleware.require_roles("Court", "Receiver")
    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")
    limit, offset = svc.parse_pagination()
    items = [a for a in store.assets.values() if a["case_id"] == case_id]
    status = _filter_arg("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    asset_class = _filter_arg("asset_class")
    if asset_class is not None:
        items = [a for a in items if a["asset_class"] == asset_class]
    items.sort(key=lambda a: (a["_created_dt"], a["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([svc.serialize_asset(a) for a in page], limit, offset, total)


@app.get("/v1/cases/<case_id>/engagements")
def list_case_engagements(case_id):
    middleware.require_roles("Court", "Receiver")
    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")
    limit, offset = svc.parse_pagination()
    items = [e for e in store.engagements.values() if e["case_id"] == case_id]
    status = _filter_arg("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    role_type = _filter_arg("role_type")
    if role_type is not None:
        items = [e for e in items if e["role_type"] == role_type]
    items.sort(key=lambda e: (e["_created_dt"], e["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([svc.serialize_engagement(e) for e in page], limit, offset, total)


@app.get("/v1/cases/<case_id>/authorization-requests")
def list_case_authorization_requests(case_id):
    middleware.require_roles("Court", "Receiver")
    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")
    limit, offset = svc.parse_pagination()
    items = [r for r in store.authorization_requests.values() if r["case_id"] == case_id]
    status = _filter_arg("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    request_type = _filter_arg("request_type")
    if request_type is not None:
        items = [r for r in items if r["request_type"] == request_type]
    items.sort(key=lambda r: (r["_created_dt"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(
        [svc.serialize_authorization_request(r) for r in page], limit, offset, total
    )


@app.get("/v1/cases/<case_id>/status-reports")
def list_case_status_reports(case_id):
    middleware.require_roles("Court", "Receiver")
    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")
    limit, offset = svc.parse_pagination()
    items = [r for r in store.status_reports.values() if r["case_id"] == case_id]
    report_type = _filter_arg("report_type")
    if report_type is not None:
        items = [r for r in items if r["report_type"] == report_type]
    status = _filter_arg("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([svc.serialize_status_report(r) for r in page], limit, offset, total)


def _filter_arg(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ===========================================================================
# Assets
# ===========================================================================

ASSET_CLASSES = {"REAL_PROPERTY", "CASH", "SECURITIES", "RECEIVABLE", "EQUIPMENT", "OTHER"}


@app.post("/v1/assets")
def create_asset():
    middleware.require_roles("Receiver")
    body = svc.get_json_body()
    case_id = svc.require_string(body, "case_id")
    description = svc.require_string(body, "description")
    asset_class = svc.require_enum(body, "asset_class", ASSET_CLASSES)
    estimated_value_cents = svc.require_nonnegative_int(body, "estimated_value_cents")

    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")

    asset = _new_entity(store.new_id())
    asset.update(
        case_id=case_id,
        description=description,
        asset_class=asset_class,
        estimated_value_cents=estimated_value_cents,
        liquidation_value_cents=None,
        liquidated_at=None,
        status="IDENTIFIED",
    )
    store.assets[asset["id"]] = asset
    # side effect: case marshalled_value_cents recomputed
    svc.recompute_case_derived(case)
    case["updated_at"] = store.now_iso()
    return success_object(svc.serialize_asset(asset), 201)


@app.get("/v1/assets/<asset_id>")
def get_asset(asset_id):
    middleware.require_roles("Court", "Receiver")
    asset = store.assets.get(asset_id)
    if asset is None:
        raise errors.err_not_found("Asset not found")
    return success_object(svc.serialize_asset(asset))


def _asset_terminal_transition(asset_id, request_type, body, need_liquidation_value):
    middleware.require_roles("Receiver")
    liquidation_value_cents = None
    authorization_id = None
    if need_liquidation_value:
        liquidation_value_cents = svc.require_nonnegative_int(body, "liquidation_value_cents")
    if "authorization_id" in body and body["authorization_id"] is not None:
        if not isinstance(body["authorization_id"], str):
            raise errors.err_invalid_request("Field 'authorization_id' must be a string")
        authorization_id = body["authorization_id"]

    asset = store.assets.get(asset_id)
    if asset is None:
        raise errors.err_not_found("Asset not found")
    # (6) from-state
    if asset["status"] != "IDENTIFIED":
        raise errors.err_invalid_state("Asset is not IDENTIFIED")
    case = store.cases.get(asset["case_id"])
    # (7) case gate
    if case is None or case["status"] != "ACTIVE":
        raise errors.err_case_not_active("Owning case is not ACTIVE")
    # (8) authority-limit gate
    if asset["estimated_value_cents"] > case["authority_limit_cents"]:
        if authorization_id is None:
            raise errors.err_authorization_required()
        auth = store.authorization_requests.get(authorization_id)
        if (
            auth is None
            or auth["status"] != "APPROVED"
            or auth["request_type"] != request_type
            or auth["related_asset_id"] != asset["id"]
            or auth["case_id"] != case["id"]
        ):
            raise errors.err_authorization_mismatch()
    return asset, case, liquidation_value_cents


@app.post("/v1/assets/<asset_id>/liquidate")
def liquidate_asset(asset_id):
    middleware.require_roles("Receiver")
    body = svc.get_json_body()
    asset, case, liquidation_value_cents = _asset_terminal_transition(
        asset_id, "ASSET_LIQUIDATION", body, need_liquidation_value=True
    )
    asset["status"] = "LIQUIDATED"
    asset["liquidation_value_cents"] = liquidation_value_cents
    asset["liquidated_at"] = store.now_iso()
    _touch(asset)
    # side effects: cash += proceeds, marshalled + posture recomputed, version bumped
    svc.touch_case_for_recompute(case, bump_version=True)
    return success_object(svc.serialize_asset(asset))


@app.post("/v1/assets/<asset_id>/abandon")
def abandon_asset(asset_id):
    middleware.require_roles("Receiver")
    body = svc.get_json_body() if _has_body() else {}
    asset, case, _ = _asset_terminal_transition(
        asset_id, "ASSET_ABANDONMENT", body, need_liquidation_value=False
    )
    asset["status"] = "ABANDONED"
    _touch(asset)
    # side effect: marshalled_value recomputed (asset excluded)
    svc.recompute_case_derived(case)
    case["updated_at"] = store.now_iso()
    return success_object(svc.serialize_asset(asset))


def _has_body():
    from flask import request
    return request.content_length is not None and request.content_length > 0


@app.get("/v1/assets/<asset_id>/authorization-requests")
def list_asset_authorization_requests(asset_id):
    middleware.require_roles("Court", "Receiver")
    asset = store.assets.get(asset_id)
    if asset is None:
        raise errors.err_not_found("Asset not found")
    limit, offset = svc.parse_pagination()
    items = [
        r for r in store.authorization_requests.values()
        if r["related_asset_id"] == asset_id
    ]
    status = _filter_arg("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(
        [svc.serialize_authorization_request(r) for r in page], limit, offset, total
    )


# ===========================================================================
# Claims
# ===========================================================================

CREDITOR_TYPES = {"SECURED", "PRIORITY_TAX", "PRIORITY_WAGE", "GENERAL_UNSECURED", "INVESTOR"}


@app.post("/v1/claims")
def create_claim():
    middleware.require_roles("Receiver", "Creditor")
    body = svc.get_json_body()
    case_id = svc.require_string(body, "case_id")
    creditor_name = svc.require_string(body, "creditor_name")
    creditor_type = svc.require_enum(body, "creditor_type", CREDITOR_TYPES)
    filed_amount_cents = svc.require_positive_int(body, "filed_amount_cents")
    # conditional: collateral_asset_id iff SECURED
    collateral_asset_id = body.get("collateral_asset_id")
    if creditor_type == "SECURED":
        if collateral_asset_id is None:
            raise errors.err_invalid_request(
                "collateral_asset_id is required for SECURED claims"
            )
        if not isinstance(collateral_asset_id, str):
            raise errors.err_invalid_request("collateral_asset_id must be a string")
    else:
        if collateral_asset_id is not None:
            raise errors.err_invalid_request(
                "collateral_asset_id is forbidden for non-SECURED claims"
            )

    # (4) existence: case, then collateral asset in same case
    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")
    asset = None
    if creditor_type == "SECURED":
        asset = store.assets.get(collateral_asset_id)
        if asset is None or asset["case_id"] != case_id:
            raise errors.err_not_found("Collateral asset not found in this case")

    # (7) case gate: claim create requires ACTIVE
    if case["status"] != "ACTIVE":
        raise errors.err_case_not_active("Owning case is not ACTIVE")

    # (9) bar-date gate: filed_at (logical clock) must be <= bar_date
    filed_at = store.now()
    if filed_at > case["_bar_date"]:
        raise errors.err_claim_barred()

    # (11) collateral usability: must not be ABANDONED
    if asset is not None and asset["status"] == "ABANDONED":
        raise errors.err_collateral_not_eligible()

    claim = _new_entity(store.new_id())
    claim.update(
        case_id=case_id,
        creditor_name=creditor_name,
        creditor_type=creditor_type,
        filed_amount_cents=filed_amount_cents,
        collateral_asset_id=collateral_asset_id if creditor_type == "SECURED" else None,
        filed_at=store.now_iso(),
        status="FILED",
        allowed_amount_cents=None,
        secured_allowed_cents=None,
        priority_allowed_cents=None,
        general_allowed_cents=None,
        investor_allowed_cents=None,
        determined_at=None,
    )
    store.claims[claim["id"]] = claim
    return success_object(svc.serialize_claim(claim), 201)


@app.get("/v1/claims")
def list_claims():
    middleware.require_roles("Court", "Receiver", "Creditor")
    limit, offset = svc.parse_pagination()
    items = list(store.claims.values())
    case_id = _filter_arg("case_id")
    if case_id is not None:
        items = [c for c in items if c["case_id"] == case_id]
    collateral_asset_id = _filter_arg("collateral_asset_id")
    if collateral_asset_id is not None:
        items = [c for c in items if c["collateral_asset_id"] == collateral_asset_id]
    status = _filter_arg("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    creditor_type = _filter_arg("creditor_type")
    if creditor_type is not None:
        items = [c for c in items if c["creditor_type"] == creditor_type]
    items.sort(key=lambda c: (c["_created_dt"], c["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([svc.serialize_claim(c) for c in page], limit, offset, total)


@app.get("/v1/claims/<claim_id>")
def get_claim(claim_id):
    middleware.require_roles("Court", "Receiver", "Creditor")
    claim = store.claims.get(claim_id)
    if claim is None:
        raise errors.err_not_found("Claim not found")
    return success_object(svc.serialize_claim(claim))


@app.post("/v1/claims/<claim_id>/determine")
def determine_claim(claim_id):
    middleware.require_roles("Receiver")
    body = svc.get_json_body()
    determination = svc.require_enum(body, "determination", {"ALLOWED", "DISALLOWED"})
    allowed_amount_cents = None
    if determination == "ALLOWED":
        if "allowed_amount_cents" not in body or body["allowed_amount_cents"] is None:
            raise errors.err_invalid_request(
                "allowed_amount_cents is required when determination is ALLOWED"
            )
        allowed_amount_cents = svc.require_nonnegative_int(body, "allowed_amount_cents")

    claim = store.claims.get(claim_id)
    if claim is None:
        raise errors.err_not_found("Claim not found")
    # (6) from-state
    if claim["status"] != "FILED":
        raise errors.err_invalid_state("Claim is not FILED")
    case = store.cases.get(claim["case_id"])
    # (7) case gate: ACTIVE or DISTRIBUTING
    if case is None or case["status"] not in ("ACTIVE", "DISTRIBUTING"):
        raise errors.err_case_not_active("Owning case is not ACTIVE or DISTRIBUTING")
    # (12) fiscal: allowed <= filed
    if determination == "ALLOWED" and allowed_amount_cents > claim["filed_amount_cents"]:
        raise errors.err_allowed_exceeds_filed()

    if determination == "ALLOWED":
        claim["allowed_amount_cents"] = allowed_amount_cents
        s, p, g, i = svc.determine_claim_buckets(claim)
        claim["secured_allowed_cents"] = s
        claim["priority_allowed_cents"] = p
        claim["general_allowed_cents"] = g
        claim["investor_allowed_cents"] = i
        claim["determined_at"] = store.now_iso()
        claim["status"] = "ALLOWED"
    else:
        claim["allowed_amount_cents"] = None
        claim["secured_allowed_cents"] = None
        claim["priority_allowed_cents"] = None
        claim["general_allowed_cents"] = None
        claim["investor_allowed_cents"] = None
        claim["determined_at"] = store.now_iso()
        claim["status"] = "DISALLOWED"
    _touch(claim)

    # side effects: recompute allowed total; if changed while a plan is FILED -> WITHDRAWN
    old_total = case["allowed_claims_total_cents"]
    svc.recompute_case_derived(case)
    case["updated_at"] = store.now_iso()
    if case["allowed_claims_total_cents"] != old_total:
        svc.withdraw_filed_plan_if_totals_changed(case)
    return success_object(svc.serialize_claim(claim))


@app.post("/v1/claims/<claim_id>/reconsider")
def reconsider_claim(claim_id):
    middleware.require_roles("Court")
    claim = store.claims.get(claim_id)
    if claim is None:
        raise errors.err_not_found("Claim not found")
    # (6) from-state: ALLOWED or DISALLOWED
    if claim["status"] not in ("ALLOWED", "DISALLOWED"):
        raise errors.err_invalid_state("Claim is not in a determined state")
    case = store.cases.get(claim["case_id"])
    if case is None or case["status"] not in ("ACTIVE", "DISTRIBUTING"):
        raise errors.err_case_not_active("Owning case is not ACTIVE or DISTRIBUTING")

    was_allowed = claim["status"] == "ALLOWED"
    if was_allowed:
        claim["allowed_amount_cents"] = None
        claim["secured_allowed_cents"] = None
        claim["priority_allowed_cents"] = None
        claim["general_allowed_cents"] = None
        claim["investor_allowed_cents"] = None
    claim["determined_at"] = None
    claim["status"] = "FILED"
    _touch(claim)

    old_total = case["allowed_claims_total_cents"]
    svc.recompute_case_derived(case)
    case["updated_at"] = store.now_iso()
    if was_allowed:
        if case["allowed_claims_total_cents"] != old_total:
            svc.withdraw_filed_plan_if_totals_changed(case)
        # cancel every SCHEDULED payment of this claim
        affected_plans = set()
        for p in store.distribution_payments.values():
            if p["claim_id"] == claim["id"] and p["status"] == "SCHEDULED":
                p["status"] = "CANCELLED"
                _touch(p)
                affected_plans.add(p["plan_id"])
        for plan_id in affected_plans:
            plan = store.distribution_plans.get(plan_id)
            if plan is not None:
                svc.maybe_execute_plan(plan)
    return success_object(svc.serialize_claim(claim))


@app.get("/v1/claims/<claim_id>/payments")
def list_claim_payments(claim_id):
    middleware.require_roles("Court", "Receiver", "Creditor")
    claim = store.claims.get(claim_id)
    if claim is None:
        raise errors.err_not_found("Claim not found")
    limit, offset = svc.parse_pagination()
    items = [p for p in store.distribution_payments.values() if p["claim_id"] == claim_id]
    status = _filter_arg("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    # ordered by priority_class rank ASC
    items.sort(key=lambda p: (svc.PRIORITY_CLASS_RANK[p["priority_class"]], p["_created_dt"], p["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(
        [svc.serialize_distribution_payment(p) for p in page], limit, offset, total
    )


# ===========================================================================
# Engagements
# ===========================================================================

ROLE_TYPES = {"COUNSEL", "ACCOUNTANT", "AUCTIONEER", "BROKER"}
FEE_ARRANGEMENTS = {"HOURLY", "CONTINGENT"}


@app.post("/v1/engagements")
def create_engagement():
    middleware.require_roles("Receiver")
    body = svc.get_json_body()
    case_id = svc.require_string(body, "case_id")
    professional_name = svc.require_string(body, "professional_name")
    firm_name = svc.require_string(body, "firm_name")
    role_type = svc.require_enum(body, "role_type", ROLE_TYPES)
    fee_arrangement = svc.require_enum(body, "fee_arrangement", FEE_ARRANGEMENTS)
    fee_cap_cents = svc.require_positive_int(body, "fee_cap_cents")
    hourly_rate_cents = body.get("hourly_rate_cents")
    contingency_pct = body.get("contingency_pct")
    if fee_arrangement == "HOURLY":
        if hourly_rate_cents is None:
            raise errors.err_invalid_request("hourly_rate_cents is required for HOURLY")
        if isinstance(hourly_rate_cents, bool) or not isinstance(hourly_rate_cents, int):
            raise errors.err_invalid_request("hourly_rate_cents must be an integer")
        if contingency_pct is not None:
            raise errors.err_invalid_request("contingency_pct is forbidden for HOURLY")
    else:
        if contingency_pct is None:
            raise errors.err_invalid_request("contingency_pct is required for CONTINGENT")
        if isinstance(contingency_pct, bool) or not isinstance(contingency_pct, (int, float)):
            raise errors.err_invalid_request("contingency_pct must be a number")
        if hourly_rate_cents is not None:
            raise errors.err_invalid_request("hourly_rate_cents is forbidden for CONTINGENT")

    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")

    # (10b) at most one PROPOSED/APPROVED engagement per (case_id, role_type)
    for e in store.engagements.values():
        if (
            e["case_id"] == case_id
            and e["role_type"] == role_type
            and e["status"] in ("PROPOSED", "APPROVED")
        ):
            raise errors.err_engagement_already_active()

    engagement = _new_entity(store.new_id())
    engagement.update(
        case_id=case_id,
        professional_name=professional_name,
        firm_name=firm_name,
        role_type=role_type,
        fee_arrangement=fee_arrangement,
        hourly_rate_cents=hourly_rate_cents if fee_arrangement == "HOURLY" else None,
        contingency_pct=contingency_pct if fee_arrangement == "CONTINGENT" else None,
        fee_cap_cents=fee_cap_cents,
        total_fees_paid_cents=0,
        status="PROPOSED",
    )
    store.engagements[engagement["id"]] = engagement
    return success_object(svc.serialize_engagement(engagement), 201)


@app.get("/v1/engagements/<engagement_id>")
def get_engagement(engagement_id):
    middleware.require_roles("Court", "Receiver")
    engagement = store.engagements.get(engagement_id)
    if engagement is None:
        raise errors.err_not_found("Engagement not found")
    return success_object(svc.serialize_engagement(engagement))


@app.post("/v1/engagements/<engagement_id>/decide")
def decide_engagement(engagement_id):
    middleware.require_roles("Court")
    body = svc.get_json_body()
    decision = svc.require_enum(body, "decision", {"APPROVE", "REJECT"})
    engagement = store.engagements.get(engagement_id)
    if engagement is None:
        raise errors.err_not_found("Engagement not found")
    # (6) from-state
    if engagement["status"] != "PROPOSED":
        raise errors.err_invalid_state("Engagement is not PROPOSED")
    if decision == "APPROVE":
        case = store.cases.get(engagement["case_id"])
        # (7) case gate on approval: ACTIVE or DISTRIBUTING
        if case is None or case["status"] not in ("ACTIVE", "DISTRIBUTING"):
            raise errors.err_case_not_active("Owning case is not ACTIVE or DISTRIBUTING")
        engagement["status"] = "APPROVED"
    else:
        engagement["status"] = "DENIED"
    _touch(engagement)
    return success_object(svc.serialize_engagement(engagement))


@app.get("/v1/engagements/<engagement_id>/fee-applications")
def list_engagement_fee_applications(engagement_id):
    middleware.require_roles("Court", "Receiver")
    engagement = store.engagements.get(engagement_id)
    if engagement is None:
        raise errors.err_not_found("Engagement not found")
    limit, offset = svc.parse_pagination()
    items = [
        f for f in store.fee_applications.values()
        if f["engagement_id"] == engagement_id
    ]
    status = _filter_arg("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items.sort(key=lambda f: (f["_created_dt"], f["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(
        [svc.serialize_fee_application(f) for f in page], limit, offset, total
    )


# ===========================================================================
# Fee Applications
# ===========================================================================

@app.post("/v1/fee-applications")
def create_fee_application():
    middleware.require_roles("Receiver")
    body = svc.get_json_body()
    engagement_id = svc.require_string(body, "engagement_id")
    period_start = svc.parse_dt(svc.require_field(body, "period_start"), "period_start")
    period_end = svc.parse_dt(svc.require_field(body, "period_end"), "period_end")
    if period_start >= period_end:
        raise errors.err_invalid_request("period_start must be before period_end")
    expenses_cents = svc.require_nonnegative_int(body, "expenses_cents")

    engagement = store.engagements.get(engagement_id)
    if engagement is None:
        raise errors.err_not_found("Engagement not found")

    time_entries = body.get("time_entries")
    recovery_basis_cents = body.get("recovery_basis_cents")
    if engagement["fee_arrangement"] == "HOURLY":
        if not isinstance(time_entries, list) or len(time_entries) == 0:
            raise errors.err_invalid_request(
                "time_entries must be a non-empty array for HOURLY engagements"
            )
        for entry in time_entries:
            if not isinstance(entry, dict):
                raise errors.err_invalid_request("Each time entry must be an object")
            hours = entry.get("hours")
            rate = entry.get("rate_cents")
            if isinstance(hours, bool) or not isinstance(hours, (int, float)):
                raise errors.err_invalid_request("Each time entry needs numeric 'hours'")
            if isinstance(rate, bool) or not isinstance(rate, int):
                raise errors.err_invalid_request("Each time entry needs integer 'rate_cents'")
        if recovery_basis_cents is not None:
            raise errors.err_invalid_request(
                "recovery_basis_cents is forbidden for HOURLY applications"
            )
    else:  # CONTINGENT
        if time_entries is not None and len(time_entries) > 0:
            raise errors.err_invalid_request(
                "time_entries must be absent or empty for CONTINGENT applications"
            )
        if recovery_basis_cents is None:
            raise errors.err_invalid_request(
                "recovery_basis_cents is required for CONTINGENT applications"
            )
        if isinstance(recovery_basis_cents, bool) or not isinstance(recovery_basis_cents, int):
            raise errors.err_invalid_request("recovery_basis_cents must be an integer")

    # (7) engagement must be APPROVED
    if engagement["status"] != "APPROVED":
        raise errors.err_engagement_not_approved()

    # (10e) half-open period non-overlap among non-DENIED applications of this engagement
    for f in store.fee_applications.values():
        if f["engagement_id"] != engagement_id or f["status"] == "DENIED":
            continue
        if period_start < f["_period_end"] and f["_period_start"] < period_end:
            raise errors.err_fee_period_overlap()

    requested = svc.compute_requested_amount(
        engagement, time_entries or [], expenses_cents, recovery_basis_cents
    )

    application = _new_entity(store.new_id())
    application.update(
        engagement_id=engagement_id,
        time_entries=time_entries if engagement["fee_arrangement"] == "HOURLY" else (time_entries or None),
        expenses_cents=expenses_cents,
        recovery_basis_cents=(
            recovery_basis_cents if engagement["fee_arrangement"] == "CONTINGENT" else None
        ),
        requested_amount_cents=requested,
        approved_amount_cents=None,
        status="FILED",
        _period_start=period_start,
        _period_end=period_end,
    )
    store.fee_applications[application["id"]] = application
    return success_object(svc.serialize_fee_application(application), 201)


@app.post("/v1/fee-applications/<application_id>/decide")
def decide_fee_application(application_id):
    middleware.require_roles("Court")
    body = svc.get_json_body()
    decision = svc.require_enum(body, "decision", {"APPROVE", "REJECT"})
    approved_amount_cents = None
    if decision == "APPROVE":
        if "approved_amount_cents" not in body or body["approved_amount_cents"] is None:
            raise errors.err_invalid_request(
                "approved_amount_cents is required when decision is APPROVE"
            )
        approved_amount_cents = svc.require_nonnegative_int(body, "approved_amount_cents")

    application = store.fee_applications.get(application_id)
    if application is None:
        raise errors.err_not_found("Fee application not found")
    # (6) from-state
    if application["status"] != "FILED":
        raise errors.err_invalid_state("Fee application is not FILED")

    if decision == "APPROVE":
        # (12) approved <= requested
        if approved_amount_cents > application["requested_amount_cents"]:
            raise errors.err_amount_exceeds_request()
        # (12) fee cap: committed (APPROVED or PAID) + new <= fee_cap_cents (equality ok)
        engagement = store.engagements.get(application["engagement_id"])
        committed = 0
        for f in store.fee_applications.values():
            if (
                f["engagement_id"] == application["engagement_id"]
                and f["status"] in ("APPROVED", "PAID")
            ):
                committed += f["approved_amount_cents"] or 0
        if engagement is not None and committed + approved_amount_cents > engagement["fee_cap_cents"]:
            raise errors.err_fee_cap_exceeded()
        application["approved_amount_cents"] = approved_amount_cents
        application["status"] = "APPROVED"
    else:
        application["status"] = "DENIED"
    _touch(application)
    return success_object(svc.serialize_fee_application(application))


@app.post("/v1/fee-applications/<application_id>/pay")
def pay_fee_application(application_id):
    middleware.require_roles("Receiver")
    body = svc.get_json_body()
    expected_case_version = svc.require_int(body, "expected_case_version")

    application = store.fee_applications.get(application_id)
    if application is None:
        raise errors.err_not_found("Fee application not found")
    engagement = store.engagements.get(application["engagement_id"])
    case = store.cases.get(engagement["case_id"]) if engagement is not None else None
    if case is None:
        raise errors.err_not_found("Case not found")
    # (5) OCC
    if expected_case_version != case["version"]:
        raise errors.err_stale_case_version()
    # (6) from-state
    if application["status"] != "APPROVED":
        raise errors.err_invalid_state("Fee application is not APPROVED")
    # (7) case gate: ACTIVE or DISTRIBUTING
    if case["status"] not in ("ACTIVE", "DISTRIBUTING"):
        raise errors.err_case_not_active("Owning case is not ACTIVE or DISTRIBUTING")
    # (12) cash sufficiency
    svc.recompute_case_derived(case)
    if case["cash_on_hand_cents"] < application["approved_amount_cents"]:
        raise errors.err_insufficient_estate_funds()

    application["status"] = "PAID"
    _touch(application)
    # side effects: debit cash, bump version, recompute posture + engagement fees
    svc.touch_case_for_recompute(case, bump_version=True)
    svc.recompute_engagement_fees(engagement)
    engagement["updated_at"] = store.now_iso()
    if (
        engagement["status"] == "APPROVED"
        and engagement["total_fees_paid_cents"] >= engagement["fee_cap_cents"]
    ):
        engagement["status"] = "EXHAUSTED"
        engagement["version"] += 1
    return success_object(svc.serialize_fee_application(application))


# ===========================================================================
# Authorization Requests
# ===========================================================================

REQUEST_TYPES = {"EXPENDITURE", "ASSET_LIQUIDATION", "ASSET_ABANDONMENT", "BUSINESS_DECISION"}
ASSET_REQUEST_TYPES = {"ASSET_LIQUIDATION", "ASSET_ABANDONMENT"}


@app.post("/v1/authorization-requests")
def create_authorization_request():
    middleware.require_roles("Receiver")
    body = svc.get_json_body()
    case_id = svc.require_string(body, "case_id")
    request_type = svc.require_enum(body, "request_type", REQUEST_TYPES)
    description = svc.require_string(body, "description")
    amount_cents = svc.require_positive_int(body, "amount_cents")
    related_asset_id = body.get("related_asset_id")
    if request_type in ASSET_REQUEST_TYPES:
        if related_asset_id is None:
            raise errors.err_invalid_request(
                f"related_asset_id is required for {request_type}"
            )
        if not isinstance(related_asset_id, str):
            raise errors.err_invalid_request("related_asset_id must be a string")
    else:
        if related_asset_id is not None:
            raise errors.err_invalid_request(
                f"related_asset_id is forbidden for {request_type}"
            )

    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")
    if related_asset_id is not None:
        asset = store.assets.get(related_asset_id)
        if asset is None or asset["case_id"] != case_id:
            raise errors.err_not_found("Related asset not found in this case")

    # (7) filing requires the owning case ACTIVE
    if case["status"] != "ACTIVE":
        raise errors.err_case_not_active("Owning case is not ACTIVE")

    authreq = _new_entity(store.new_id())
    authreq.update(
        case_id=case_id,
        request_type=request_type,
        description=description,
        amount_cents=amount_cents,
        related_asset_id=related_asset_id if request_type in ASSET_REQUEST_TYPES else None,
        status="SUBMITTED",
        decided_at=None,
    )
    store.authorization_requests[authreq["id"]] = authreq
    return success_object(svc.serialize_authorization_request(authreq), 201)


@app.post("/v1/authorization-requests/<request_id>/decide")
def decide_authorization_request(request_id):
    middleware.require_roles("Court")
    body = svc.get_json_body()
    decision = svc.require_enum(body, "decision", {"APPROVE", "REJECT"})
    authreq = store.authorization_requests.get(request_id)
    if authreq is None:
        raise errors.err_not_found("Authorization request not found")
    # (6) from-state
    if authreq["status"] != "SUBMITTED":
        raise errors.err_invalid_state("Authorization request is not SUBMITTED")
    case = store.cases.get(authreq["case_id"])

    if decision == "APPROVE":
        if authreq["request_type"] == "EXPENDITURE":
            # (12) cash sufficiency
            svc.recompute_case_derived(case)
            if case["cash_on_hand_cents"] < authreq["amount_cents"]:
                raise errors.err_insufficient_estate_funds()
        authreq["status"] = "APPROVED"
        authreq["decided_at"] = store.now_iso()
        _touch(authreq)
        if authreq["request_type"] == "EXPENDITURE":
            svc.touch_case_for_recompute(case, bump_version=True)
    else:
        authreq["status"] = "DENIED"
        authreq["decided_at"] = store.now_iso()
        _touch(authreq)
    return success_object(svc.serialize_authorization_request(authreq))


# ===========================================================================
# Status Reports
# ===========================================================================

REPORT_TYPES = {"PERIODIC", "FINAL"}


@app.post("/v1/status-reports")
def create_status_report():
    middleware.require_roles("Receiver")
    body = svc.get_json_body()
    case_id = svc.require_string(body, "case_id")
    report_type = svc.require_enum(body, "report_type", REPORT_TYPES)
    period_start = svc.parse_dt(svc.require_field(body, "period_start"), "period_start")
    period_end = svc.parse_dt(svc.require_field(body, "period_end"), "period_end")
    narrative = svc.require_string(body, "narrative")
    if period_end <= period_start:
        raise errors.err_invalid_request("period_end must be after period_start")

    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")

    # (7) case gates: PERIODIC requires ACTIVE; FINAL requires DISTRIBUTING
    if report_type == "PERIODIC":
        if case["status"] != "ACTIVE":
            raise errors.err_case_not_active("PERIODIC reports require the case to be ACTIVE")
    else:
        if case["status"] != "DISTRIBUTING":
            raise errors.err_case_not_active("FINAL reports require the case to be DISTRIBUTING")

    # (10f) overlap BEFORE gap; non-REJECTED reports of the same case
    for r in store.status_reports.values():
        if r["case_id"] != case_id or r["status"] == "REJECTED":
            continue
        if period_start < r["_period_end"] and r["_period_start"] < period_end:
            raise errors.err_report_period_overlap()
    next_start = svc.compute_next_report_period_start(case)
    if period_start != next_start:
        raise errors.err_report_period_gap()

    report = _new_entity(store.new_id())
    report.update(
        case_id=case_id,
        report_type=report_type,
        narrative=narrative,
        status="FILED",
        _period_start=period_start,
        _period_end=period_end,
    )
    store.status_reports[report["id"]] = report
    return success_object(svc.serialize_status_report(report), 201)


@app.post("/v1/status-reports/<report_id>/decide")
def decide_status_report(report_id):
    middleware.require_roles("Court")
    body = svc.get_json_body()
    decision = svc.require_enum(body, "decision", {"APPROVE", "REJECT"})
    report = store.status_reports.get(report_id)
    if report is None:
        raise errors.err_not_found("Status report not found")
    # (6) from-state
    if report["status"] != "FILED":
        raise errors.err_invalid_state("Status report is not FILED")
    report["status"] = "ACCEPTED" if decision == "APPROVE" else "REJECTED"
    _touch(report)
    # ACCEPTED advances the calendar (computed fields recompute on read; refresh updated_at on case)
    if decision == "APPROVE":
        case = store.cases.get(report["case_id"])
        if case is not None:
            case["updated_at"] = store.now_iso()
    return success_object(svc.serialize_status_report(report))


# ===========================================================================
# Distribution Plans
# ===========================================================================

def _validate_plan_filing(case, reserve_cents, exclude_plan_id=None):
    """Re-run all creation validations for plan filing/amendment (in cascade order)."""
    # (7) case ACTIVE
    if case["status"] != "ACTIVE":
        raise errors.err_case_not_active("Plan filing requires the case to be ACTIVE")
    # (9) no overdue report
    if svc.compute_report_overdue(case):
        raise errors.err_status_report_overdue()
    # (10c) no other plan FILED or APPROVED
    for p in store.distribution_plans.values():
        if p["case_id"] == case["id"] and p["id"] != exclude_plan_id and p["status"] in ("FILED", "APPROVED"):
            raise errors.err_plan_already_open()
    # (10d) no claim FILED
    for c in store.claims.values():
        if c["case_id"] == case["id"] and c["status"] == "FILED":
            raise errors.err_undetermined_claims()
    # (12) reserve <= cash
    svc.recompute_case_derived(case)
    if reserve_cents > case["cash_on_hand_cents"]:
        raise errors.err_reserve_exceeds_pool()


@app.post("/v1/distribution-plans")
def create_distribution_plan():
    middleware.require_roles("Receiver")
    body = svc.get_json_body()
    case_id = svc.require_string(body, "case_id")
    reserve_cents = svc.require_nonnegative_int(body, "reserve_cents")

    case = store.cases.get(case_id)
    if case is None:
        raise errors.err_not_found("Case not found")
    _validate_plan_filing(case, reserve_cents)

    plan = _new_entity(store.new_id())
    plan.update(
        case_id=case_id,
        reserve_cents=reserve_cents,
        pool_snapshot_cents=case["cash_on_hand_cents"] - reserve_cents,
        status="FILED",
        approved_at=None,
    )
    store.distribution_plans[plan["id"]] = plan
    return success_object(svc.serialize_distribution_plan(plan), 201)


@app.get("/v1/distribution-plans")
def list_distribution_plans():
    middleware.require_roles("Court", "Receiver", "Creditor")
    limit, offset = svc.parse_pagination()
    items = list(store.distribution_plans.values())
    case_id = _filter_arg("case_id")
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    status = _filter_arg("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["_created_dt"], p["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(
        [svc.serialize_distribution_plan(p) for p in page], limit, offset, total
    )


@app.get("/v1/distribution-plans/<plan_id>")
def get_distribution_plan(plan_id):
    middleware.require_roles("Court", "Receiver", "Creditor")
    plan = store.distribution_plans.get(plan_id)
    if plan is None:
        raise errors.err_not_found("Distribution plan not found")
    return success_object(svc.serialize_distribution_plan(plan))


@app.post("/v1/distribution-plans/<plan_id>/decide")
def decide_distribution_plan(plan_id):
    middleware.require_roles("Court")
    body = svc.get_json_body()
    decision = svc.require_enum(body, "decision", {"APPROVE", "REJECT"})
    plan = store.distribution_plans.get(plan_id)
    if plan is None:
        raise errors.err_not_found("Distribution plan not found")
    # (6) from-state
    if plan["status"] != "FILED":
        raise errors.err_invalid_state("Distribution plan is not FILED")

    if decision == "APPROVE":
        case = store.cases.get(plan["case_id"])
        plan["status"] = "APPROVED"
        plan["approved_at"] = store.now_iso()
        _touch(plan)
        # cascade: case ACTIVE -> DISTRIBUTING, then payment generation on entry
        if case is not None and case["status"] == "ACTIVE":
            svc.recompute_case_derived(case)
            case["status"] = "DISTRIBUTING"
            _touch(case)
            svc.run_final_waterfall(plan, case)
    else:
        plan["status"] = "REJECTED"
        _touch(plan)
    return success_object(svc.serialize_distribution_plan(plan))


@app.post("/v1/distribution-plans/<plan_id>/amend")
def amend_distribution_plan(plan_id):
    middleware.require_roles("Receiver")
    body = svc.get_json_body() if _has_body() else {}
    plan = store.distribution_plans.get(plan_id)
    if plan is None:
        raise errors.err_not_found("Distribution plan not found")
    reserve_cents = plan["reserve_cents"]
    if "reserve_cents" in body and body["reserve_cents"] is not None:
        reserve_cents = svc.require_nonnegative_int(body, "reserve_cents")
    # (6) from-state
    if plan["status"] != "REJECTED":
        raise errors.err_invalid_state("Only a REJECTED plan may be amended")

    case = store.cases.get(plan["case_id"])
    if case is None:
        raise errors.err_not_found("Case not found")
    _validate_plan_filing(case, reserve_cents, exclude_plan_id=plan["id"])

    plan["reserve_cents"] = reserve_cents
    plan["pool_snapshot_cents"] = case["cash_on_hand_cents"] - reserve_cents
    plan["status"] = "FILED"
    _touch(plan)
    return success_object(svc.serialize_distribution_plan(plan))


@app.get("/v1/distribution-plans/<plan_id>/payments")
def list_plan_payments(plan_id):
    middleware.require_roles("Court", "Receiver", "Creditor")
    plan = store.distribution_plans.get(plan_id)
    if plan is None:
        raise errors.err_not_found("Distribution plan not found")
    limit, offset = svc.parse_pagination()
    items = [p for p in store.distribution_payments.values() if p["plan_id"] == plan_id]
    status = _filter_arg("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    priority_class = _filter_arg("priority_class")
    if priority_class is not None:
        items = [p for p in items if p["priority_class"] == priority_class]

    def sort_key(p):
        claim = store.claims.get(p["claim_id"])
        claim_created = claim["_created_dt"] if claim is not None else p["_created_dt"]
        return (svc.PRIORITY_CLASS_RANK[p["priority_class"]], claim_created, p["id"])

    items.sort(key=sort_key)
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(
        [svc.serialize_distribution_payment(p) for p in page], limit, offset, total
    )


# ===========================================================================
# Distribution Payments
# ===========================================================================

@app.post("/v1/distribution-payments/<payment_id>/pay")
def pay_distribution_payment(payment_id):
    middleware.require_roles("Receiver")
    body = svc.get_json_body()
    expected_case_version = svc.require_int(body, "expected_case_version")

    payment = store.distribution_payments.get(payment_id)
    if payment is None:
        raise errors.err_not_found("Distribution payment not found")
    plan = store.distribution_plans.get(payment["plan_id"])
    case = store.cases.get(plan["case_id"]) if plan is not None else None
    if case is None:
        raise errors.err_not_found("Case not found")
    # (5) OCC
    if expected_case_version != case["version"]:
        raise errors.err_stale_case_version()
    # (6) from-state
    if payment["status"] != "SCHEDULED":
        raise errors.err_invalid_state("Distribution payment is not SCHEDULED")
    # (10g) senior-class gate
    my_rank = svc.PRIORITY_CLASS_RANK[payment["priority_class"]]
    for other in store.distribution_payments.values():
        if (
            other["plan_id"] == payment["plan_id"]
            and other["status"] == "SCHEDULED"
            and svc.PRIORITY_CLASS_RANK[other["priority_class"]] < my_rank
        ):
            raise errors.err_senior_class_unpaid()
    # (12) cash sufficiency
    svc.recompute_case_derived(case)
    if case["cash_on_hand_cents"] < payment["scheduled_amount_cents"]:
        raise errors.err_insufficient_estate_funds()

    payment["status"] = "PAID"
    payment["paid_amount_cents"] = payment["scheduled_amount_cents"]
    payment["paid_at"] = store.now_iso()
    _touch(payment)
    svc.touch_case_for_recompute(case, bump_version=True)
    # bubble-up: plan -> EXECUTED when no SCHEDULED remain
    if plan is not None:
        svc.maybe_execute_plan(plan)
    return success_object(svc.serialize_distribution_payment(payment))


@app.post("/v1/distribution-payments/<payment_id>/void")
def void_distribution_payment(payment_id):
    middleware.require_roles("Court")
    payment = store.distribution_payments.get(payment_id)
    if payment is None:
        raise errors.err_not_found("Distribution payment not found")
    # (6) from-state
    if payment["status"] != "PAID":
        raise errors.err_invalid_state("Distribution payment is not PAID")
    plan = store.distribution_plans.get(payment["plan_id"])
    # (7) plan must still be APPROVED (not EXECUTED)
    if plan is None or plan["status"] != "APPROVED":
        raise errors.err_plan_not_executing()
    case = store.cases.get(plan["case_id"])

    payment["status"] = "VOIDED"
    _touch(payment)
    # side effect: credit cash back, bump version, recompute posture
    if case is not None:
        svc.touch_case_for_recompute(case, bump_version=True)
    return success_object(svc.serialize_distribution_payment(payment))


# ===========================================================================
# Logical clock (test-driving endpoint)
# ===========================================================================

@app.post("/v1/_clock/set_current_utc")
def set_current_utc():
    middleware.require_roles("SystemAdmin")
    body = svc.get_json_body()
    to_iso8601 = svc.require_field(body, "to_iso8601")
    dt = svc.parse_dt(to_iso8601, "to_iso8601")
    store.logical_now = dt
    return success_object({"current_utc": iso_out(store.logical_now)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
