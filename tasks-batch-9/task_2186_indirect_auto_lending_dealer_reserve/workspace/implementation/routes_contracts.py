"""Routes: retail contracts, funding-package documents, funding and
portfolio (chargeback) events."""
from datetime import timedelta
from fractions import Fraction

from flask import Blueprint, g

from core import (
    store, clock, new_rec, bump, stamp, putdt, dtv, fail, ok, list_response,
    require_roles, scope_dealer_id, get_body, v_str, v_int, v_enum, v_dt, v_id,
    get_dealer, get_application, get_contract, get_document, qfilter,
    is_dealer_principal, serialize, ALL_ROLES, rhu, months_from_days,
    BASE_REQUIRED_DOC_TYPES, DOC_TYPES, FUNDING_WINDOW_DAYS,
    EARLY_PAYOFF_SEASONING_MONTHS, PROBATION_MIN_FUNDED_COUNT,
    PROBATION_EARLY_PAYOFF_RATE_BPS,
)
import services as S

bp = Blueprint("contracts", __name__)


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
@bp.route("/lending/contracts", methods=["POST"])
def create_contract():
    require_roles("DealerPrincipal")
    body = get_body()
    application_id = v_id(body, "application_id", required=True)
    contract_apr = v_int(body, "contract_apr_bps", required=True)
    date_raw, contract_date = v_dt(body, "contract_date", required=True)

    app = get_application(application_id)
    scope_dealer_id(app["dealer_id"])

    if app["status"] != "APPROVED":
        fail("ERR_APPLICATION_NOT_APPROVED", "The application is not APPROVED.")

    dealer = get_dealer(app["dealer_id"])
    if dealer["compliance_hold"]:
        fail("ERR_DEALER_COMPLIANCE_HOLD", "The dealership is under a compliance hold.")
    if dealer["status"] != "ACTIVE":
        fail("ERR_DEALER_NOT_ACTIVE", "The dealership is not ACTIVE.")

    if contract_apr < app["buy_rate_apr_bps"] or contract_apr > app["max_contract_apr_bps"]:
        fail("ERR_MARKUP_CAP_EXCEEDED", "contract_apr_bps lies outside the permitted band.")

    tier = store.tiers.get(app["assigned_tier_id"])
    if tier is None:
        fail("ERR_ADVANCE_LIMIT_EXCEEDED", "The assigned tier is unavailable.")
    advance_limit = rhu(Fraction(app["collateral_value_cents"] * tier["advance_rate_pct"], 100))
    if app["amount_financed_cents"] > advance_limit:
        fail("ERR_ADVANCE_LIMIT_EXCEEDED", "The amount financed exceeds the advance limit.")

    contract = new_rec()
    contract["application_id"] = app["id"]
    contract["dealer_id"] = app["dealer_id"]
    contract["agreement_id"] = app["agreement_id"]
    contract["contract_apr_bps"] = contract_apr
    putdt(contract, "contract_date", date_raw, contract_date)
    contract["amount_financed_cents"] = app["amount_financed_cents"]
    contract["term_months"] = app["term_months"]
    contract["buy_rate_apr_bps"] = app["buy_rate_apr_bps"]
    contract["markup_bps"] = contract_apr - app["buy_rate_apr_bps"]
    contract["monitoring_cohort"] = app["monitoring_cohort"]
    contract["acquisition_fee_cents"] = tier["acquisition_fee_cents"]
    required = list(BASE_REQUIRED_DOC_TYPES)
    if app["stipulation_count"] > 0:
        required.append("INCOME_VERIFICATION")
    contract["required_doc_types"] = required
    contract["funding_status"] = "PENDING_DOCS"
    contract["reserve_status"] = "NONE"
    contract["verified_doc_count"] = 0
    contract["doc_defect_count"] = 0
    stamp(contract, "funded_at", None)
    contract["funded_by_user_id"] = None
    contract["reserve_accrued_cents"] = 0
    contract["incentive_accrued_cents"] = 0
    contract["dealer_proceeds_cents"] = 0
    contract["unpaid_principal_cents"] = 0
    contract["months_seasoned"] = 0
    contract["payoff_months_seasoned"] = None
    store.contracts[contract["id"]] = contract

    app["status"] = "CONTRACTED"
    bump(app)
    return ok(serialize(contract), 201)


@bp.route("/lending/contracts/<contract_id>", methods=["GET"])
def read_contract(contract_id):
    require_roles(*ALL_ROLES)
    contract = get_contract(contract_id)
    scope_dealer_id(contract["dealer_id"])
    return ok(serialize(contract))


@bp.route("/lending/contracts", methods=["GET"])
def list_contracts():
    require_roles(*ALL_ROLES)
    records = list(store.contracts.values())
    if is_dealer_principal():
        records = [c for c in records if c["dealer_id"] == g.user_id]
    for name in ("dealer_id", "application_id", "agreement_id", "funding_status", "reserve_status"):
        value = qfilter(name)
        if value is not None:
            records = [c for c in records if c.get(name) == value]
    records.sort(key=lambda c: (c.get("created_at") or "", c.get("_seq") or 0))
    return list_response(records)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@bp.route("/lending/contracts/<contract_id>/documents", methods=["POST"])
def upload_document(contract_id):
    require_roles("DealerPrincipal")
    contract = get_contract(contract_id)
    scope_dealer_id(contract["dealer_id"])
    body = get_body()
    doc_type = v_enum(body, "doc_type", DOC_TYPES, required=True)
    reference = v_str(body, "document_reference", required=True, min_len=1, max_len=64)
    for existing in S.contract_documents(contract_id):
        if existing["doc_type"] == doc_type:
            fail("ERR_INVALID_REQUEST", "A document of this type already exists for the contract.")

    doc = new_rec()
    doc["contract_id"] = contract_id
    doc["doc_type"] = doc_type
    doc["document_reference"] = reference
    doc["status"] = "RECEIVED"
    doc["defect_code"] = None
    doc["verified_by_user_id"] = None
    stamp(doc, "verified_at", None)
    store.documents[doc["id"]] = doc
    return ok(serialize(doc), 201)


@bp.route("/lending/contracts/<contract_id>/documents", methods=["GET"])
def list_documents(contract_id):
    require_roles(*ALL_ROLES)
    contract = get_contract(contract_id)
    scope_dealer_id(contract["dealer_id"])
    records = S.contract_documents(contract_id)
    status = qfilter("status")
    if status is not None:
        records = [d for d in records if d["status"] == status]
    doc_type = qfilter("doc_type")
    if doc_type is not None:
        records = [d for d in records if d["doc_type"] == doc_type]
    return list_response(records)


@bp.route("/lending/documents/<document_id>/verify", methods=["POST"])
def verify_document(document_id):
    require_roles("FundingSpecialist")
    doc = get_document(document_id)
    body = get_body()
    outcome = v_enum(body, "outcome", ("VERIFY", "REJECT"), required=True)
    defect_code = v_str(body, "defect_code", required=False, min_len=1, max_len=None, default=None)

    contract = store.contracts.get(doc["contract_id"])
    if contract is None or contract["funding_status"] not in ("PENDING_DOCS", "DOCS_VERIFIED"):
        fail("ERR_INVALID_STATE", "The contract's funding package may no longer be re-worked.")

    required = contract["required_doc_types"]
    if outcome == "VERIFY":
        if doc["status"] not in ("RECEIVED", "REJECTED"):
            fail("ERR_INVALID_STATE", "A VERIFY outcome is not permitted from status %s." % doc["status"])
        doc["status"] = "VERIFIED"
        doc["defect_code"] = None
        doc["verified_by_user_id"] = g.user_id
        stamp(doc, "verified_at", clock.now())
        bump(doc)
        if doc["doc_type"] in required:
            contract["verified_doc_count"] += 1
            verified_types = set(
                d["doc_type"] for d in S.contract_documents(contract["id"]) if d["status"] == "VERIFIED"
            )
            if contract["funding_status"] == "PENDING_DOCS" and all(t in verified_types for t in required):
                contract["funding_status"] = "DOCS_VERIFIED"
                contract["verified_doc_count"] = len(required)
            bump(contract)
    else:
        if doc["status"] not in ("RECEIVED", "VERIFIED"):
            fail("ERR_INVALID_STATE", "A REJECT outcome is not permitted from status %s." % doc["status"])
        was_verified = doc["status"] == "VERIFIED"
        doc["status"] = "REJECTED"
        doc["defect_code"] = defect_code if defect_code else "UNSPECIFIED_DEFECT"
        doc["verified_by_user_id"] = g.user_id
        stamp(doc, "verified_at", clock.now())
        bump(doc)
        contract["doc_defect_count"] += 1
        if was_verified and doc["doc_type"] in required:
            contract["verified_doc_count"] -= 1
            if contract["funding_status"] == "DOCS_VERIFIED":
                contract["funding_status"] = "PENDING_DOCS"
        bump(contract)
    return ok(serialize(doc))


# ---------------------------------------------------------------------------
# Funding
# ---------------------------------------------------------------------------
@bp.route("/lending/contracts/<contract_id>/fund", methods=["POST"])
def fund_contract(contract_id):
    require_roles("FundingSpecialist")
    contract = get_contract(contract_id)
    body = get_body()
    funding_raw, funding_date = v_dt(body, "funding_date", required=True)

    if contract["funding_status"] != "DOCS_VERIFIED":
        fail("ERR_DOCS_NOT_VERIFIED", "The funding package is not fully verified.")
    dealer = get_dealer(contract["dealer_id"])
    if dealer["compliance_hold"]:
        fail("ERR_DEALER_COMPLIANCE_HOLD", "The dealership is under a compliance hold.")
    app = store.applications.get(contract["application_id"])
    decisioned_by = app.get("decisioned_by_user_id") if app else None
    if decisioned_by is not None and g.user_id == decisioned_by:
        fail("ERR_SEGREGATION_OF_DUTIES", "The funder may not be the analyst who decisioned the file.")
    if dealer["status"] != "ACTIVE":
        fail("ERR_DEALER_NOT_ACTIVE", "The dealership is not ACTIVE.")

    decisioned_at = dtv(app, "decisioned_at") if app else None
    if decisioned_at is not None and (funding_date - decisioned_at) > timedelta(days=FUNDING_WINDOW_DAYS):
        fail("ERR_FUNDING_WINDOW_EXPIRED", "The funding window has expired.")
    if funding_date < dtv(contract, "contract_date"):
        fail("ERR_FUNDING_WINDOW_EXPIRED", "funding_date precedes the contract_date.")

    if dealer["outstanding_principal_cents"] + contract["amount_financed_cents"] > dealer["funding_line_cents"]:
        fail("ERR_DEALER_FUNDING_LINE_EXCEEDED", "Funding would exceed the dealership's funding line.")

    agreement = store.agreements.get(contract["agreement_id"])
    reserve = S.reserve_accrued(contract, agreement, contract["term_months"])
    incentive = S.incentive_accrued(contract)

    putdt(contract, "funded_at", funding_raw, funding_date)
    contract["funded_by_user_id"] = g.user_id
    contract["reserve_accrued_cents"] = reserve
    contract["incentive_accrued_cents"] = incentive
    contract["dealer_proceeds_cents"] = (
        contract["amount_financed_cents"] - contract["acquisition_fee_cents"] + reserve + incentive
    )
    contract["unpaid_principal_cents"] = contract["amount_financed_cents"]
    contract["funding_status"] = "FUNDED"
    contract["reserve_status"] = "ACCRUED"
    bump(contract)

    S.post_entry(dealer, contract["id"], "PARTICIPATION_ACCRUAL", reserve, "PARTICIPATION_ACCRUAL")
    S.post_entry(dealer, contract["id"], "INCENTIVE_ACCRUAL", incentive, "INCENTIVE_ACCRUAL")

    S.recompute_reserve_balance(dealer)
    S.recompute_exposure(dealer)
    dealer["total_funded_ever_count"] += 1
    S.recompute_early_payoff_rate(dealer)
    bump(dealer)
    return ok(serialize(contract))


# ---------------------------------------------------------------------------
# Portfolio events / reserve chargeback
# ---------------------------------------------------------------------------
@bp.route("/lending/contracts/<contract_id>/chargeback-events", methods=["POST"])
def create_chargeback_event(contract_id):
    require_roles("PortfolioAdmin")
    contract = get_contract(contract_id)
    body = get_body()
    event_type = v_enum(body, "event_type", ("EARLY_PAYOFF", "DEFAULT"), required=True)
    date_raw, event_date = v_dt(body, "event_date", required=True)

    if contract["funding_status"] != "FUNDED":
        fail("ERR_INVALID_STATE", "Only a FUNDED contract may carry a portfolio event.")
    funded_at = dtv(contract, "funded_at")
    if event_date < funded_at:
        fail("ERR_INVALID_EVENT_DATE", "event_date precedes the contract's funded_at.")

    dealer = get_dealer(contract["dealer_id"])
    agreement = store.agreements.get(contract["agreement_id"])
    months = months_from_days(funded_at, event_date)
    window_months, within, participation_cb, incentive_cb, total = S.compute_chargeback(
        contract, agreement, months
    )
    earned_to_date = S.reserve_accrued(contract, agreement, months)

    event = new_rec(versioned=False)
    event["contract_id"] = contract["id"]
    event["event_type"] = event_type
    putdt(event, "event_date", date_raw, event_date)
    event["months_seasoned"] = months
    event["window_months"] = window_months
    event["within_window"] = within
    event["participation_chargeback_cents"] = participation_cb
    event["incentive_chargeback_cents"] = incentive_cb
    event["chargeback_total_cents"] = total
    event["earned_to_date_reserve_cents"] = earned_to_date
    store.events[event["id"]] = event

    contract["months_seasoned"] = months
    if event_type == "EARLY_PAYOFF":
        contract["payoff_months_seasoned"] = months
        contract["funding_status"] = "PAID_OFF"
    else:
        contract["funding_status"] = "DEFAULTED"
    contract["reserve_status"] = "CHARGED_BACK" if within else "EARNED"

    if within:
        S.post_entry(dealer, contract["id"], "CHARGEBACK", -total, "CHARGEBACK")
        dealer["chargeback_count"] += 1
        S.recompute_reserve_balance(dealer)
        dealer["scorecard_stale"] = True

    if event_type == "EARLY_PAYOFF":
        if months < EARLY_PAYOFF_SEASONING_MONTHS:
            dealer["early_payoff_count"] += 1
            S.recompute_early_payoff_rate(dealer)
            if (dealer["status"] == "ACTIVE"
                    and dealer["total_funded_ever_count"] >= PROBATION_MIN_FUNDED_COUNT
                    and dealer["early_payoff_rate_bps"] >= PROBATION_EARLY_PAYOFF_RATE_BPS):
                S.auto_suspend(dealer, "AUTO_EARLY_PAYOFF_RATE")
    else:
        dealer["default_count"] += 1

    contract["unpaid_principal_cents"] = S.straight_line_unpaid(contract, months)
    S.recompute_exposure(dealer)
    contract["unpaid_principal_cents"] = 0
    bump(contract)
    bump(dealer)
    return ok(serialize(event), 201)


@bp.route("/lending/contracts/<contract_id>/chargeback-events", methods=["GET"])
def list_chargeback_events(contract_id):
    require_roles(*ALL_ROLES)
    contract = get_contract(contract_id)
    scope_dealer_id(contract["dealer_id"])
    records = [e for e in store.events.values() if e["contract_id"] == contract_id]
    event_type = qfilter("event_type")
    if event_type is not None:
        records = [e for e in records if e["event_type"] == event_type]
    records.sort(key=lambda e: (e.get("created_at") or "", e.get("_seq") or 0))
    return list_response(records)
