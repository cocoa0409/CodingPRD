"""Composite setup helpers that build preconditions through declared endpoints only.

Every helper starts from an empty database and drives the public API in the order
the workflow narrative requires: chain registration, principal onboarding, rate
card activation, principal promotion, item setup and catalog validation, review
scheduling and opening, deck preparation and submission, optional negotiation,
lock, award decision, optional acceptance, and finally distribution posting.

The two entity-backed roles carry real entity identifiers: a `RetailerBuyer`
sends the acting `Retailer.id` and a `PrincipalPortalUser` sends the acting
`Principal.id`, so ownership checks resolve to the intended chain or principal
rather than tripping the scope band.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDIT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    make_principal_portal_headers,
    make_retailer_buyer_headers,
)
from .types import (
    AmortizationMethod,
    CatalogDecision,
    DeductionReasonCode,
    PrincipalStatus,
    PromotionEventType,
)

# Clock instants used repeatedly by the workflow: the deadline instant a review is
# locked at, and a date inside the default decision window where it is decided.
LOCK_INSTANT = "2026-08-20T00:00:00Z"
DECIDE_INSTANT = "2026-09-02T00:00:00Z"


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
def set_clock(api: ApiClient, current_utc: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    response = api.set_clock(F.clock_payload(current_utc), headers or BROKER_ADMIN_HEADERS)
    return get_success_data(response, 200)


# --------------------------------------------------------------------------- #
# Chains and principals
# --------------------------------------------------------------------------- #
def create_retailer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_retailer(F.retailer_payload(**overrides), BROKER_ADMIN_HEADERS)
    return get_success_data(response, 201)


def create_principal(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_principal(F.principal_payload(**overrides), BROKER_ADMIN_HEADERS)
    return get_success_data(response, 201)


def get_principal(api: ApiClient, principal_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_principal(principal_id, BROKER_ADMIN_HEADERS), 200)


def create_agreement(
    api: ApiClient,
    principal_id: str,
    retailer_id: str,
    activate: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = F.agreement_payload(principal_id, retailer_id, **overrides)
    agreement = get_success_data(api.create_agreement(payload, BROKER_ADMIN_HEADERS), 201)
    if activate:
        agreement = get_success_data(
            api.activate_agreement(agreement["id"], BROKER_ADMIN_HEADERS), 200
        )
    return agreement


def set_principal_active(api: ApiClient, principal_id: str) -> Dict[str, Any]:
    """Promotion out of PROSPECT needs at least one ACTIVE agreement in place."""
    response = api.set_principal_status(
        principal_id, F.principal_status_payload(PrincipalStatus.ACTIVE), BROKER_ADMIN_HEADERS
    )
    return get_success_data(response, 200)


def active_principal(
    api: ApiClient,
    retailer_id: str,
    principal_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Onboard a principal, activate one rate card for the chain, and promote it."""
    principal = create_principal(api, **(principal_overrides or {}))
    agreement = create_agreement(
        api, principal["id"], retailer_id, **(agreement_overrides or {})
    )
    principal = set_principal_active(api, principal["id"])
    return {"principal": principal, "agreement": agreement}


# --------------------------------------------------------------------------- #
# Items and catalog validation
# --------------------------------------------------------------------------- #
def create_item(api: ApiClient, principal_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api.create_item(F.item_payload(principal_id, **overrides), ACCOUNT_MANAGER_HEADERS)
    return get_success_data(response, 201)


def validate_item_catalog(
    api: ApiClient,
    item_id: str,
    retailer_id: str,
    upc: str,
    **submission_overrides: Any,
) -> Dict[str, Any]:
    """Submit catalog data then rule on it; the decision is a RetailerBuyer action."""
    get_success_data(
        api.submit_catalog(
            item_id, F.catalog_submission_payload(upc=upc, **submission_overrides), ACCOUNT_MANAGER_HEADERS
        ),
        200,
    )
    response = api.decide_catalog(
        item_id,
        F.catalog_decision_payload(CatalogDecision.VALIDATED),
        make_retailer_buyer_headers(retailer_id),
    )
    return get_success_data(response, 200)


def validated_item(
    api: ApiClient,
    principal_id: str,
    retailer_id: str,
    upc: str = C.UPC_1,
    **item_overrides: Any,
) -> Dict[str, Any]:
    item = create_item(api, principal_id, upc=upc, **item_overrides)
    return validate_item_catalog(api, item["id"], retailer_id, upc)


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #
def create_review(api: ApiClient, retailer_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api.create_review(
        F.review_payload(retailer_id, **overrides), make_retailer_buyer_headers(retailer_id)
    )
    return get_success_data(response, 201)


def open_review(api: ApiClient, review_id: str, retailer_id: str) -> Dict[str, Any]:
    response = api.open_review(review_id, make_retailer_buyer_headers(retailer_id))
    return get_success_data(response, 200)


def opened_review(api: ApiClient, retailer_id: str, **overrides: Any) -> Dict[str, Any]:
    review = create_review(api, retailer_id, **overrides)
    return open_review(api, review["id"], retailer_id)


def get_review(api: ApiClient, review_id: str, retailer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_review(review_id, make_retailer_buyer_headers(retailer_id)), 200)


def lock_review(
    api: ApiClient, review_id: str, retailer_id: str, at_instant: str = LOCK_INSTANT
) -> Dict[str, Any]:
    """Locking requires the clock to have reached the submission deadline."""
    set_clock(api, at_instant)
    response = api.lock_review(review_id, make_retailer_buyer_headers(retailer_id))
    return get_success_data(response, 200)


def decide_review(
    api: ApiClient,
    review_id: str,
    retailer_id: str,
    authorized_item_ids: List[str],
    default_store_count: Optional[int] = None,
    at_instant: Optional[str] = DECIDE_INSTANT,
) -> Dict[str, Any]:
    """Decide inside the half-open decision window, pinning the review version."""
    if at_instant is not None:
        set_clock(api, at_instant)
    review = get_review(api, review_id, retailer_id)
    kwargs: Dict[str, Any] = {}
    if default_store_count is not None:
        kwargs["default_store_count"] = default_store_count
    response = api.decide_review(
        review_id,
        F.decide_payload(review["version"], authorized_item_ids, **kwargs),
        make_retailer_buyer_headers(retailer_id),
    )
    return get_success_data(response, 200)


def lock_and_decide(
    api: ApiClient,
    review_id: str,
    retailer_id: str,
    authorized_item_ids: List[str],
    default_store_count: Optional[int] = None,
    lock_at: str = LOCK_INSTANT,
    decide_at: str = DECIDE_INSTANT,
) -> Dict[str, Any]:
    lock_review(api, review_id, retailer_id, lock_at)
    return decide_review(
        api, review_id, retailer_id, authorized_item_ids, default_store_count, decide_at
    )


# --------------------------------------------------------------------------- #
# Presentations
# --------------------------------------------------------------------------- #
def create_presentation(
    api: ApiClient, review_id: str, principal_id: str, item_ids: List[str]
) -> Dict[str, Any]:
    response = api.create_presentation(
        F.presentation_payload(review_id, principal_id, item_ids), ACCOUNT_MANAGER_HEADERS
    )
    return get_success_data(response, 201)


def submit_presentation(api: ApiClient, presentation_id: str) -> Dict[str, Any]:
    response = api.submit_presentation(presentation_id, ACCOUNT_MANAGER_HEADERS)
    return get_success_data(response, 200)


def submitted_presentation(
    api: ApiClient, review_id: str, principal_id: str, item_ids: List[str]
) -> Dict[str, Any]:
    presentation = create_presentation(api, review_id, principal_id, item_ids)
    return submit_presentation(api, presentation["id"])


# --------------------------------------------------------------------------- #
# Slotting deals
# --------------------------------------------------------------------------- #
def create_deal(api: ApiClient, presentation_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api.create_deal(F.deal_payload(presentation_id, **overrides), ACCOUNT_MANAGER_HEADERS)
    return get_success_data(response, 201)


def propose(api: ApiClient, deal_id: str, fee_per_store_cents: int) -> Dict[str, Any]:
    response = api.propose_deal(
        deal_id, F.propose_payload(fee_per_store_cents), ACCOUNT_MANAGER_HEADERS
    )
    return get_success_data(response, 200)


def counter(
    api: ApiClient,
    deal_id: str,
    retailer_id: str,
    fee_per_store_cents: int,
    counter_forecast_annual_units: Optional[int] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if counter_forecast_annual_units is not None:
        kwargs["counter_forecast_annual_units"] = counter_forecast_annual_units
    response = api.counter_deal(
        deal_id,
        F.counter_payload(fee_per_store_cents, **kwargs),
        make_retailer_buyer_headers(retailer_id),
    )
    return get_success_data(response, 200)


def proposed_deal(
    api: ApiClient, presentation_id: str, fee_per_store_cents: int = 50000, **overrides: Any
) -> Dict[str, Any]:
    """Open a negotiation and put a broker offer on the table."""
    deal = create_deal(
        api, presentation_id, requested_fee_per_store_cents=fee_per_store_cents, **overrides
    )
    return propose(api, deal["id"], fee_per_store_cents)


def accept_as_buyer(api: ApiClient, deal_id: str, retailer_id: str, principal_id: str) -> Dict[str, Any]:
    """A buyer may only accept a standing broker offer (deal in PROPOSED)."""
    principal = get_principal(api, principal_id)
    response = api.accept_deal(
        deal_id, F.accept_payload(principal["version"]), make_retailer_buyer_headers(retailer_id)
    )
    return get_success_data(response, 200)


def accept_as_broker(api: ApiClient, deal_id: str, principal_id: str) -> Dict[str, Any]:
    """The broker may only accept a standing retailer counter (deal in COUNTERED)."""
    principal = get_principal(api, principal_id)
    response = api.accept_deal(
        deal_id, F.accept_payload(principal["version"]), ACCOUNT_MANAGER_HEADERS
    )
    return get_success_data(response, 200)


def get_deal(api: ApiClient, deal_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_deal(deal_id, ACCOUNT_MANAGER_HEADERS), 200)


# --------------------------------------------------------------------------- #
# Authorizations
# --------------------------------------------------------------------------- #
def list_authorizations(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = api.list_authorizations(ACCOUNT_MANAGER_HEADERS, params or None)
    return get_success_data(response, 200)


def authorizations_for_review(api: ApiClient, review_id: str) -> List[Dict[str, Any]]:
    return list_authorizations(api, review_id=review_id)


def authorization_for_deal(api: ApiClient, deal_id: str) -> Dict[str, Any]:
    rows = list_authorizations(api, slotting_deal_id=deal_id)
    assert rows, f"expected at least one authorization linked to deal {deal_id}"
    return rows[0]


def get_authorization(api: ApiClient, authorization_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_authorization(authorization_id, ACCOUNT_MANAGER_HEADERS), 200)


def get_voids_report(api: ApiClient, authorization_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_voids_report(authorization_id, ACCOUNT_MANAGER_HEADERS), 200)


# --------------------------------------------------------------------------- #
# Distribution ledger
# --------------------------------------------------------------------------- #
def post_period(
    api: ApiClient,
    authorization_id: str,
    retailer_id: str,
    period_index: int = 1,
    reported_store_count: int = 400,
    distributed_store_count: int = 380,
    reported_case_volume: int = 1000,
) -> Dict[str, Any]:
    """Post one period, reading the authorization's current version for the pin."""
    authorization = get_authorization(api, authorization_id)
    payload = F.snapshot_payload(
        authorization_id,
        authorization["version"],
        period_index=period_index,
        reported_store_count=reported_store_count,
        distributed_store_count=distributed_store_count,
        reported_case_volume=reported_case_volume,
    )
    response = api.post_snapshot(payload, make_retailer_buyer_headers(retailer_id))
    return get_success_data(response, 201)


def reverse_period(api: ApiClient, snapshot_id: str, retailer_id: str) -> Dict[str, Any]:
    response = api.reverse_snapshot(snapshot_id, make_retailer_buyer_headers(retailer_id))
    return get_success_data(response, 201)


def list_snapshots(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = api.list_snapshots(ACCOUNT_MANAGER_HEADERS, params or None)
    return get_success_data(response, 200)


# --------------------------------------------------------------------------- #
# Promotion events
# --------------------------------------------------------------------------- #
def create_promotion(api: ApiClient, authorization_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api.create_promotion(
        F.promotion_payload(authorization_id, **overrides), ACCOUNT_MANAGER_HEADERS
    )
    return get_success_data(response, 201)


def create_demo(
    api: ApiClient,
    authorization_id: str,
    window_start: str,
    window_end: str,
    store_code: str = "S001",
    **overrides: Any,
) -> Dict[str, Any]:
    response = api.create_promotion(
        F.demo_payload(authorization_id, window_start, window_end, store_code, **overrides),
        ACCOUNT_MANAGER_HEADERS,
    )
    return get_success_data(response, 201)


def commit_promotion(api: ApiClient, promotion_event_id: str) -> Dict[str, Any]:
    response = api.commit_promotion(promotion_event_id, ACCOUNT_MANAGER_HEADERS)
    return get_success_data(response, 200)


def execute_promotion(api: ApiClient, promotion_event_id: str, actual_funding_cents: int) -> Dict[str, Any]:
    response = api.execute_promotion(
        promotion_event_id, F.execute_promotion_payload(actual_funding_cents), ACCOUNT_MANAGER_HEADERS
    )
    return get_success_data(response, 200)


def get_promotion(api: ApiClient, promotion_event_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_promotion(promotion_event_id, ACCOUNT_MANAGER_HEADERS), 200)


def executed_promotion(
    api: ApiClient,
    authorization_id: str,
    window_start: str,
    window_end: str,
    planned_funding_cents: int,
    actual_funding_cents: int,
    execute_at: str,
    event_type: str = PromotionEventType.PRICE_FEATURE,
) -> Dict[str, Any]:
    """Plan, commit, advance the clock past the window, then record execution."""
    promotion = create_promotion(
        api,
        authorization_id,
        event_type=event_type,
        window_start=window_start,
        window_end=window_end,
        planned_funding_cents=planned_funding_cents,
    )
    commit_promotion(api, promotion["id"])
    set_clock(api, execute_at)
    return execute_promotion(api, promotion["id"], actual_funding_cents)


# --------------------------------------------------------------------------- #
# Deductions
# --------------------------------------------------------------------------- #
def create_deduction(
    api: ApiClient, retailer_id: str, principal_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = api.create_deduction(
        F.deduction_payload(retailer_id, principal_id, **overrides),
        make_retailer_buyer_headers(retailer_id),
    )
    return get_success_data(response, 201)


def file_claim(api: ApiClient, deduction_id: str, claim_amount_cents: int) -> Dict[str, Any]:
    response = api.dispute_deduction(
        deduction_id, F.dispute_payload(claim_amount_cents), ACCOUNT_MANAGER_HEADERS
    )
    return get_success_data(response, 200)


def substantiate(api: ApiClient, deduction_id: str, document_ref: str) -> Dict[str, Any]:
    response = api.substantiate_deduction(
        deduction_id, F.substantiate_payload(document_ref), ACCOUNT_MANAGER_HEADERS
    )
    return get_success_data(response, 200)


def substantiate_twice(
    api: ApiClient, deduction_id: str, refs: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Approval needs at least two documents, so evidence is attached in pairs."""
    document_refs = refs or ["POD-1001", "INV-2002"]
    result: Dict[str, Any] = {}
    for ref in document_refs:
        result = substantiate(api, deduction_id, ref)
    return result


def approve_recovery(api: ApiClient, deduction_id: str) -> Dict[str, Any]:
    """Approval is segregated: the approver differs from the recorded filer."""
    response = api.approve_recovery(deduction_id, AUDIT_MANAGER_HEADERS)
    return get_success_data(response, 200)


def deny_recovery(api: ApiClient, deduction_id: str, denial_reason: str = "Not evidenced") -> Dict[str, Any]:
    response = api.deny_recovery(
        deduction_id, F.deny_payload(denial_reason), AUDIT_MANAGER_HEADERS
    )
    return get_success_data(response, 200)


def get_deduction(api: ApiClient, deduction_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_deduction(deduction_id, ACCOUNT_MANAGER_HEADERS), 200)


def substantiated_deduction(
    api: ApiClient,
    retailer_id: str,
    principal_id: str,
    amount_cents: int = 90000,
    claim_amount_cents: Optional[int] = None,
    reason_code: str = DeductionReasonCode.SHORTAGE,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record a deduction, file the full claim and attach two documents."""
    deduction = create_deduction(
        api,
        retailer_id,
        principal_id,
        reason_code=reason_code,
        amount_cents=amount_cents,
        **overrides,
    )
    file_claim(api, deduction["id"], claim_amount_cents if claim_amount_cents is not None else amount_cents)
    return substantiate_twice(api, deduction["id"])


# --------------------------------------------------------------------------- #
# Whole-workflow composites
# --------------------------------------------------------------------------- #
def awarded_authorization_without_deal(
    api: ApiClient,
    retailer_overrides: Optional[Dict[str, Any]] = None,
    principal_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    review_overrides: Optional[Dict[str, Any]] = None,
    upc: str = C.UPC_1,
    default_store_count: int = 400,
) -> Dict[str, Any]:
    """Award one slot with no live negotiation, so the authorization auto-advances.

    Branch A of the award decision auto-advances an authorization with no linked
    deal from PENDING_SETUP to AUTHORIZED while it stays UNBILLED.
    """
    retailer = create_retailer(api, **(retailer_overrides or {}))
    bundle = active_principal(api, retailer["id"], principal_overrides, agreement_overrides)
    principal = bundle["principal"]
    item = validated_item(api, principal["id"], retailer["id"], upc=upc)
    review = opened_review(api, retailer["id"], **(review_overrides or {}))
    presentation = submitted_presentation(api, review["id"], principal["id"], [item["id"]])
    review = lock_and_decide(
        api, review["id"], retailer["id"], [item["id"]], default_store_count=default_store_count
    )
    authorization = authorizations_for_review(api, review["id"])[0]
    return {
        "retailer": retailer,
        "principal": principal,
        "agreement": bundle["agreement"],
        "item": item,
        "review": review,
        "presentation": presentation,
        "authorization": authorization,
    }


def amortizing_deal(
    api: ApiClient,
    fee_per_store_cents: int = 12500,
    store_count_in_scope: int = 400,
    item_count_in_scope: int = 1,
    forecast_annual_units: int = 0,
    amortization_periods: int = 6,
    amortization_method: str = AmortizationMethod.FORECAST_STRAIGHT,
    retailer_overrides: Optional[Dict[str, Any]] = None,
    principal_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    review_overrides: Optional[Dict[str, Any]] = None,
    upc: str = C.UPC_1,
) -> Dict[str, Any]:
    """Drive the full chain to an accepted deal in AMORTIZING with its authorization.

    The buyer accepts the standing broker offer after the award decision, which is
    what advances the deal ACCEPTED to AMORTIZING and fires the three-hop cascade.
    """
    retailer = create_retailer(api, **(retailer_overrides or {}))
    bundle = active_principal(api, retailer["id"], principal_overrides, agreement_overrides)
    principal = bundle["principal"]
    item = validated_item(api, principal["id"], retailer["id"], upc=upc)
    review = opened_review(api, retailer["id"], **(review_overrides or {}))
    presentation = submitted_presentation(api, review["id"], principal["id"], [item["id"]])
    deal = proposed_deal(
        api,
        presentation["id"],
        fee_per_store_cents=fee_per_store_cents,
        store_count_in_scope=store_count_in_scope,
        item_count_in_scope=item_count_in_scope,
        forecast_annual_units=forecast_annual_units,
        amortization_periods=amortization_periods,
        amortization_method=amortization_method,
    )
    review = lock_and_decide(api, review["id"], retailer["id"], [item["id"]])
    deal = accept_as_buyer(api, deal["id"], retailer["id"], principal["id"])
    authorization = authorization_for_deal(api, deal["id"])
    return {
        "retailer": retailer,
        "principal": get_principal(api, principal["id"]),
        "agreement": bundle["agreement"],
        "item": item,
        "review": review,
        "presentation": presentation,
        "deal": deal,
        "authorization": authorization,
    }


def read_as_portal_user(api: ApiClient, path_builder: str, principal_id: str) -> Dict[str, Any]:
    """Helper for the read-only portal role, whose X-User-ID is the principal id."""
    headers = make_principal_portal_headers(principal_id)
    return get_success_data(api._request("GET", path_builder, None, headers), 200)
