"""Lease contract endpoints + lease-end + assessment — PRD §3.4, §3.9, §3.10."""
from __future__ import annotations

from flask import Blueprint, g, request

from config import (
    LEASE_ELIGIBLE_TIERS,
    LEASE_TERMS,
    MILEAGE_ALLOWANCE_MAX,
    MILEAGE_ALLOWANCE_MIN,
    ROLE_CUSTOMER,
    ROLE_FINANCE_MANAGER,
    ROLE_LOAN_OFFICER,
)
from db import store
from errors import (
    err_assessment_not_disputed,
    err_assessment_not_found,
    err_assessment_not_issued,
    err_contract_not_activatable,
    err_customer_not_active,
    err_customer_not_found,
    err_down_payment_below_minimum,
    err_invalid_lease_end_election,
    err_invalid_odometer_reading,
    err_invalid_request,
    err_lease_not_matured,
    err_lease_not_pending_approval,
    err_lease_tier_ineligible,
    err_lease_window_overlap,
    err_vehicle_not_available,
    err_vehicle_not_found,
)
from middleware import is_customer, require_auth
from response import success
from routes._helpers import check_version, get_json, parse_version
from services.calculations import (
    lease_monthly_payment_cents,
    minimum_down_payment_lease_cents,
    purchase_quote_at_maturity,
    purchase_quote_early_buyout,
    residual_value_cents,
    tier_money_factor_micro,
)
from services.engine import (
    apply_lease_election,
    apply_odometer_reading,
    close_lease_and_cascade,
    create_draft_assessment,
    generate_payment_schedule,
    get_assessment_for_lease,
    get_customer_or_404,
    get_lease_contract_or_404,
    stamp_create,
    stamp_update,
)
from services.serializers import serialize_assessment, serialize_lease_contract

bp = Blueprint("lease_contracts", __name__)


def _check_customer_ownership(customer_id: str):
    if is_customer() and g.user_id != customer_id:
        raise err_customer_not_found()


# Non-terminal lease statuses for window-overlap check.
_NON_TERMINAL_LEASE_STATUSES = {
    "PENDING_APPROVAL", "APPROVED", "ACTIVE", "MATURED",
    "PURCHASED", "RENEWED", "RETURNED", "DEFAULTED",
}


# ── POST /customers/{customerId}/lease-contracts ───────────────────────────


@bp.post("/customers/<customer_id>/lease-contracts")
@require_auth([ROLE_LOAN_OFFICER])
def create_lease(customer_id):
    customer = get_customer_or_404(customer_id)
    body = get_json()
    vehicle_id = body.get("vehicle_id")
    if not isinstance(vehicle_id, str) or not vehicle_id:
        raise err_invalid_request("vehicle_id is required.")
    veh = store.vehicles.get(vehicle_id)
    if veh is None:
        raise err_vehicle_not_found()

    down_payment = body.get("down_payment_cents")
    if down_payment is None or isinstance(down_payment, bool) or not isinstance(down_payment, int):
        raise err_invalid_request("down_payment_cents must be an integer.")
    if down_payment < 0:
        raise err_invalid_request("down_payment_cents must be >= 0.")
    if down_payment > veh["msrp_cents"]:
        raise err_invalid_request("down_payment_cents must not exceed msrp_cents.")

    term_months = body.get("term_months")
    if term_months is None or isinstance(term_months, bool) or not isinstance(term_months, int):
        raise err_invalid_request("term_months must be an integer.")
    if term_months not in LEASE_TERMS:
        raise err_invalid_request(
            f"term_months must be one of {list(LEASE_TERMS)}."
        )

    mileage_allowance = body.get("mileage_allowance")
    if mileage_allowance is None or isinstance(mileage_allowance, bool) or not isinstance(mileage_allowance, int):
        raise err_invalid_request("mileage_allowance must be an integer.")
    if mileage_allowance < MILEAGE_ALLOWANCE_MIN or mileage_allowance > MILEAGE_ALLOWANCE_MAX:
        raise err_invalid_request(
            f"mileage_allowance must be in [{MILEAGE_ALLOWANCE_MIN}, {MILEAGE_ALLOWANCE_MAX}]."
        )

    with store.lock:
        lc = {
            "customer_id": customer_id,
            "vehicle_id": vehicle_id,
            "capitalized_cost_cents": veh["msrp_cents"] - down_payment,
            "down_payment_cents": down_payment,
            "term_months": term_months,
            "mileage_allowance": mileage_allowance,
            "money_factor_micro": None,
            "residual_value_cents": None,
            "monthly_payment_cents": None,
            "payments_made_count": 0,
            "payments_scheduled_count": None,
            "status": "PENDING_APPROVAL",
            "lease_end_election": None,
            "origination_day_index": None,
            "maturity_day_index": None,
        }
        stamp_create(lc)
        store.lease_contracts[lc["id"]] = lc
    return success(serialize_lease_contract(lc), 201)


# ── POST /customers/{customerId}/lease-contracts/{contractId}/approve ──────


@bp.post("/customers/<customer_id>/lease-contracts/<contract_id>/approve")
@require_auth([ROLE_LOAN_OFFICER])
def approve_lease(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    lc = get_lease_contract_or_404(customer_id, contract_id)
    body = get_json()
    expected = parse_version(body)
    check_version(lc, expected)

    if lc["status"] != "PENDING_APPROVAL":
        raise err_lease_not_pending_approval()
    if customer["status"] != "ACTIVE":
        raise err_customer_not_active()
    # Tier 7: TIER_4 or TIER_5_DECLINED are rejected (priority 7 — before down-payment check).
    if customer["fico_tier"] not in LEASE_ELIGIBLE_TIERS:
        raise err_lease_tier_ineligible()
    veh = store.vehicles.get(lc["vehicle_id"])
    if veh is None:
        raise err_vehicle_not_found()
    # Window-overlap check (priority 9 — before fiscal floors).
    new_origination = customer["clock_day_index"]
    new_maturity = new_origination + lc["term_months"] * 30
    for other in store.lease_contracts.values():
        if other["id"] == lc["id"]:
            continue
        if other["customer_id"] != customer_id:
            continue
        if other["status"] not in _NON_TERMINAL_LEASE_STATUSES:
            continue
        other_origination = other.get("origination_day_index")
        other_maturity = other.get("maturity_day_index")
        if other_origination is None or other_maturity is None:
            continue
        # Half-open intervals [start, end): overlap iff
        # start1 < end2 AND start2 < end1.
        if new_origination < other_maturity and other_origination < new_maturity:
            raise err_lease_window_overlap()
    # Down-payment minimum (priority 10).
    min_dp = minimum_down_payment_lease_cents(veh["msrp_cents"], customer["fico_tier"])
    if lc["down_payment_cents"] < min_dp:
        raise err_down_payment_below_minimum(
            f"down_payment_cents={lc['down_payment_cents']} below minimum {min_dp} for {customer['fico_tier']}."
        )
    if veh["status"] != "AVAILABLE":
        raise err_vehicle_not_available()

    with store.lock:
        veh["status"] = "LEASED"
        stamp_update(veh)
        mf = tier_money_factor_micro(customer["fico_tier"])
        lc["money_factor_micro"] = mf
        residual = residual_value_cents(veh["msrp_cents"], veh["residual_factor_bps"])
        lc["residual_value_cents"] = residual
        lc["monthly_payment_cents"] = lease_monthly_payment_cents(
            capitalized_cost_cents=lc["capitalized_cost_cents"],
            residual_value_cents=residual,
            money_factor_micro=mf,
            term_months=lc["term_months"],
        )
        lc["payments_scheduled_count"] = lc["term_months"]
        lc["origination_day_index"] = new_origination
        lc["maturity_day_index"] = new_maturity
        lc["status"] = "APPROVED"
        stamp_update(lc)
    return success(serialize_lease_contract(lc))


# ── POST /customers/{customerId}/lease-contracts/{contractId}/activate ─────


@bp.post("/customers/<customer_id>/lease-contracts/<contract_id>/activate")
@require_auth([ROLE_LOAN_OFFICER])
def activate_lease(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    lc = get_lease_contract_or_404(customer_id, contract_id)
    body = get_json()
    expected = parse_version(body)
    check_version(lc, expected)

    if lc["status"] != "APPROVED":
        raise err_contract_not_activatable(
            f"Lease is in {lc['status']}; activation requires APPROVED."
        )

    with store.lock:
        lc["status"] = "ACTIVE"
        stamp_update(lc)
        generate_payment_schedule(lc, contract_type="LEASE")
    return success(serialize_lease_contract(lc))


# ── GET /customers/{customerId}/lease-contracts/{contractId} ───────────────


@bp.get("/customers/<customer_id>/lease-contracts/<contract_id>")
@require_auth([ROLE_LOAN_OFFICER, ROLE_FINANCE_MANAGER, ROLE_CUSTOMER])
def get_lease(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    lc = get_lease_contract_or_404(customer_id, contract_id)
    return success(serialize_lease_contract(lc))


# ── GET .../purchase-quote ─────────────────────────────────────────────────


@bp.get("/customers/<customer_id>/lease-contracts/<contract_id>/purchase-quote")
@require_auth([ROLE_LOAN_OFFICER, ROLE_FINANCE_MANAGER, ROLE_CUSTOMER])
def get_lease_purchase_quote(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    lc = get_lease_contract_or_404(customer_id, contract_id)

    variant = request.args.get("variant", "AT_MATURITY")
    if variant not in {"AT_MATURITY", "EARLY_BUYOUT"}:
        raise err_invalid_request("variant must be AT_MATURITY or EARLY_BUYOUT.")
    residual = lc.get("residual_value_cents") or 0
    if variant == "AT_MATURITY":
        result = purchase_quote_at_maturity(residual)
    else:
        # EARLY_BUYOUT allowed only while ACTIVE.
        if lc["status"] != "ACTIVE":
            raise err_invalid_request(
                "EARLY_BUYOUT variant requires the lease to be ACTIVE."
            )
        result = purchase_quote_early_buyout(
            residual_value_cents=residual,
            payments_scheduled_count=lc.get("payments_scheduled_count") or 0,
            payments_made_count=lc.get("payments_made_count") or 0,
            monthly_payment_cents=lc.get("monthly_payment_cents") or 0,
        )
    return success(result)


# ── POST .../lease-end ─────────────────────────────────────────────────────


@bp.post("/customers/<customer_id>/lease-contracts/<contract_id>/lease-end")
@require_auth([ROLE_CUSTOMER])
def post_lease_end(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    lc = get_lease_contract_or_404(customer_id, contract_id)
    body = get_json()
    expected = parse_version(body)
    check_version(lc, expected)

    election = body.get("election")
    if election not in {"PURCHASE", "RENEW", "RETURN"}:
        raise err_invalid_lease_end_election()

    if lc["status"] != "MATURED":
        raise err_lease_not_matured()

    assessment = get_assessment_for_lease(customer_id, contract_id)
    if assessment is None:
        raise err_assessment_not_found()
    if assessment["odometer_reading"] is None:
        # Election cannot be honored without odometer.
        raise err_assessment_not_issued(
            "Lease-end election requires odometer_reading to be set on the assessment."
        )
    if assessment["status"] not in {"DRAFT", "ISSUED"}:
        raise err_assessment_not_issued(
            f"Assessment must be DRAFT or ISSUED; was {assessment['status']}."
        )

    with store.lock:
        apply_lease_election(lc, assessment, election)
    return success(serialize_lease_contract(lc))


# ── PATCH .../assessment ────────────────────────────────────────────────────


@bp.patch("/customers/<customer_id>/lease-contracts/<contract_id>/assessment")
@require_auth([ROLE_FINANCE_MANAGER])
def patch_assessment(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    lc = get_lease_contract_or_404(customer_id, contract_id)
    body = get_json()

    reading = body.get("odometer_reading")
    if reading is None or isinstance(reading, bool) or not isinstance(reading, int) or reading < 0:
        raise err_invalid_odometer_reading()

    assessment = get_assessment_for_lease(customer_id, contract_id)
    if assessment is None:
        raise err_assessment_not_found()
    expected = parse_version(body)
    check_version(assessment, expected)

    # PATCH transitions DRAFT → ISSUED. If already ISSUED/DISPUTED/etc, reject.
    if assessment["status"] != "DRAFT":
        raise err_assessment_not_issued(
            f"PATCH assessment requires DRAFT; was {assessment['status']}."
        )

    with store.lock:
        apply_odometer_reading(assessment, lc, reading)
        assessment["status"] = "ISSUED"
        stamp_update(assessment)
    return success(serialize_assessment(assessment))


# ── POST .../assessment/settle ─────────────────────────────────────────────


@bp.post("/customers/<customer_id>/lease-contracts/<contract_id>/assessment/settle")
@require_auth([ROLE_CUSTOMER])
def settle_assessment(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    lc = get_lease_contract_or_404(customer_id, contract_id)
    assessment = get_assessment_for_lease(customer_id, contract_id)
    if assessment is None:
        raise err_assessment_not_found()
    body = get_json()
    expected = parse_version(body)
    check_version(assessment, expected)

    if assessment["status"] != "ISSUED":
        raise err_assessment_not_issued()

    # Cross-entity dependency: all child Payments on parent LeaseContract must be PAID.
    for p in store.payments.values():
        if p["contract_id"] != contract_id:
            continue
        if p["status"] != "PAID":
            raise err_assessment_not_issued(
                "Cannot settle: outstanding payments on the parent lease."
            )

    with store.lock:
        assessment["status"] = "SETTLED"
        close_lease_and_cascade(lc, assessment)
        stamp_update(assessment)
    return success(serialize_assessment(assessment))


# ── POST .../assessment/dispute ────────────────────────────────────────────


@bp.post("/customers/<customer_id>/lease-contracts/<contract_id>/assessment/dispute")
@require_auth([ROLE_CUSTOMER])
def dispute_assessment(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    lc = get_lease_contract_or_404(customer_id, contract_id)
    assessment = get_assessment_for_lease(customer_id, contract_id)
    if assessment is None:
        raise err_assessment_not_found()
    body = get_json()
    expected = parse_version(body)
    check_version(assessment, expected)

    if assessment["status"] != "ISSUED":
        raise err_assessment_not_issued()

    with store.lock:
        assessment["status"] = "DISPUTED"
        stamp_update(assessment)
    return success(serialize_assessment(assessment))


# ── POST .../assessment/resolve ────────────────────────────────────────────


@bp.post("/customers/<customer_id>/lease-contracts/<contract_id>/assessment/resolve")
@require_auth([ROLE_FINANCE_MANAGER])
def resolve_assessment(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    lc = get_lease_contract_or_404(customer_id, contract_id)
    assessment = get_assessment_for_lease(customer_id, contract_id)
    if assessment is None:
        raise err_assessment_not_found()
    body = get_json()
    expected = parse_version(body)
    check_version(assessment, expected)

    if assessment["status"] != "DISPUTED":
        raise err_assessment_not_disputed()

    reading = body.get("revised_odometer_reading")
    if reading is None or isinstance(reading, bool) or not isinstance(reading, int) or reading < 0:
        raise err_invalid_odometer_reading()

    with store.lock:
        apply_odometer_reading(assessment, lc, reading)
        assessment["status"] = "RESOLVED"
        close_lease_and_cascade(lc, assessment)
        stamp_update(assessment)
    return success(serialize_assessment(assessment))
