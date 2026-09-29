"""
Composite setup helpers.

Every test runs against an empty database, so each one has to build the state it
needs from scratch through the documented endpoints. The helpers here are layered:

* tier 0 - the client, the logical clock, and small read/refresh wrappers
* tier 1 - one call each, returning the created resource
* tier 2 - small compositions: the reference catalogue, a vendor in review, an
  accepted shelf price
* tier 3 - the recurring backbone: an authorized vendor, a published ceiling, an
  adjudicated claim, a pending adjustment, a served sanction case, a failed visit
* tier 4 - whole scenarios assembled from tier 3

All helpers take the ``ApiClient`` as their first argument and return plain dicts
so a test can read fields directly. They validate leniently through
``get_success_data`` - a helper that fails means the *setup* broke, and the
assertions that matter live in the tests.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_LOGICAL_CLOCK
from .test_users import (
    ANALYST_HEADERS,
    INVESTIGATOR_HEADERS,
    SUPERVISOR_HEADERS,
    SUPERVISOR_TWO_HEADERS,
    SYSTEM_HEADERS,
    make_vendor_operator_headers,
)
from .types import (
    AdjustmentReasonCode,
    ReviewDecision,
    TrainingType,
    ViolationCode,
    VisitType,
)

# ---------------------------------------------------------------------------
# Canonical reference data used by the recurring setups
# ---------------------------------------------------------------------------

PEER_GROUP_CODE = "PG-SUPER-A"
MILK_CATEGORY_CODE = "MILK"
MILK_UPC = "00011122233"
MILK_BRAND = "Statewide Dairy"
JUICE_CATEGORY_CODE = "JUICE"
JUICE_UPC = "00077788899"
JUICE_BRAND = "Statewide Juice"
BREAD_CATEGORY_CODE = "BREAD"
BREAD_UPC = "00055566677"
BREAD_BRAND = "Statewide Bakery"

CYCLE_CODE = "2026Q3"
CYCLE_OPEN_AT = "2026-08-01T00:00:00Z"
CYCLE_DUE_AT = "2026-09-01T00:00:00Z"

TRAINING_COMPLETED_AT = "2026-07-15T00:00:00Z"
VENDOR_STORE_NAME = "Alpha Market"
VENDOR_REPORTED_CENTS = 6_000_000
BASE_SHELF_PRICE_CENTS = 320

# The maximum allowable reimbursement the canonical setup publishes for milk:
# a single contributing submission of 320 cents, the statewide fallback basis, a
# five per cent allowance and an idle cap, rounded once to 336.
CANONICAL_MILK_MAR_CENTS = 336


# ---------------------------------------------------------------------------
# Tier 0 - client, clock, reads
# ---------------------------------------------------------------------------


def make_api_client() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock and return the echoed body."""
    return get_success_data(api.set_clock(current_utc, SYSTEM_HEADERS))


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    """Put the logical clock back to the instant it reads before any client sets it."""
    return set_clock(api, DEFAULT_LOGICAL_CLOCK)


def run_risk_run(api: ApiClient) -> Dict[str, Any]:
    """Advance the risk epoch and return the run summary."""
    return get_success_data(api.risk_run(None, SYSTEM_HEADERS))


def get_peer_group(api: ApiClient, peer_group_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.get_peer_group(peer_group_id, headers or SUPERVISOR_HEADERS)
    )


def get_food_category(api: ApiClient, category_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.get_food_category(category_id, headers or SUPERVISOR_HEADERS)
    )


def get_food_item(api: ApiClient, food_item_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.get_authorized_food_item(food_item_id, headers or SUPERVISOR_HEADERS)
    )


def get_vendor(api: ApiClient, vendor_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_vendor(vendor_id, headers or SUPERVISOR_HEADERS))


def get_price_cycle(api: ApiClient, price_cycle_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.get_price_cycle(price_cycle_id, headers or SUPERVISOR_HEADERS)
    )


def get_price_submission(api: ApiClient, submission_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.get_price_submission(submission_id, headers or SUPERVISOR_HEADERS)
    )


def get_price_ceiling(api: ApiClient, ceiling_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.get_price_ceiling(ceiling_id, headers or SUPERVISOR_HEADERS)
    )


def get_visit(api: ApiClient, visit_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.get_monitoring_visit(visit_id, headers or SUPERVISOR_HEADERS)
    )


def get_claim(api: ApiClient, claim_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.get_redemption_claim(claim_id, headers or SUPERVISOR_HEADERS)
    )


def get_adjustment(api: ApiClient, adjustment_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.get_reimbursement_adjustment(adjustment_id, headers or SUPERVISOR_HEADERS)
    )


def get_sanction_case(api: ApiClient, case_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.get_sanction_case(case_id, headers or SUPERVISOR_HEADERS)
    )


def list_price_ceilings(
    api: ApiClient, params: Optional[Dict[str, Any]] = None, headers=None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_price_ceilings(headers or SUPERVISOR_HEADERS, params)
    )


def list_price_submissions(
    api: ApiClient, params: Optional[Dict[str, Any]] = None, headers=None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_price_submissions(headers or SUPERVISOR_HEADERS, params)
    )


def list_claim_lines(
    api: ApiClient, params: Optional[Dict[str, Any]] = None, headers=None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_claim_lines(headers or SUPERVISOR_HEADERS, params)
    )


def list_visits(
    api: ApiClient, params: Optional[Dict[str, Any]] = None, headers=None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_monitoring_visits(headers or SUPERVISOR_HEADERS, params)
    )


def list_adjustments(
    api: ApiClient, params: Optional[Dict[str, Any]] = None, headers=None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_reimbursement_adjustments(headers or SUPERVISOR_HEADERS, params)
    )


def list_sanction_cases(
    api: ApiClient, params: Optional[Dict[str, Any]] = None, headers=None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_sanction_cases(headers or SUPERVISOR_HEADERS, params)
    )


def claim_lines_of(api: ApiClient, claim_id: str, headers=None) -> List[Dict[str, Any]]:
    """The claim's lines in ascending ``line_number`` order."""
    lines, _ = list_claim_lines(api, {"redemption_claim_id": claim_id, "limit": 100}, headers)
    return sorted(lines, key=lambda line: line["line_number"])


def active_ceiling_for(
    api: ApiClient, peer_group_id: str, food_item_id: str, headers=None
) -> Dict[str, Any]:
    """The single ACTIVE maximum allowable reimbursement row for a pair."""
    rows, _ = list_price_ceilings(
        api,
        {
            "peer_group_id": peer_group_id,
            "food_item_id": food_item_id,
            "status": "ACTIVE",
            "limit": 100,
        },
        headers,
    )
    assert len(rows) == 1, f"expected exactly one ACTIVE ceiling, got {rows}"
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 1 - one call each
# ---------------------------------------------------------------------------


def create_peer_group(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """The canonical supermarket peer group unless overridden."""
    return get_success_data(
        api.create_peer_group(f.peer_group_payload(**overrides), SUPERVISOR_HEADERS)
    )


def create_food_category(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """The canonical milk category unless overridden."""
    return get_success_data(
        api.create_food_category(f.food_category_payload(**overrides), SUPERVISOR_HEADERS)
    )


def create_food_item(
    api: ApiClient, food_category_id: str, **overrides: Any
) -> Dict[str, Any]:
    """The canonical milk item under the given category unless overridden."""
    return get_success_data(
        api.create_authorized_food_item(
            f.authorized_food_item_payload(food_category_id, **overrides),
            SUPERVISOR_HEADERS,
        )
    )


def create_price_cycle(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """The canonical 2026Q3 cycle unless overridden."""
    return get_success_data(
        api.create_price_cycle(f.price_cycle_payload(**overrides), SUPERVISOR_HEADERS)
    )


def create_vendor(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A vendor application, which begins as an APPLICANT."""
    return get_success_data(
        api.create_vendor(f.vendor_payload(**overrides), ANALYST_HEADERS)
    )


def record_training(
    api: ApiClient,
    vendor_id: str,
    completed_at: str = TRAINING_COMPLETED_AT,
    training_type: str = TrainingType.INITIAL.value,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_training(
            vendor_id,
            f.training_payload(training_type=training_type, completed_at=completed_at),
            ANALYST_HEADERS,
        )
    )


def submit_application(api: ApiClient, vendor_id: str) -> Dict[str, Any]:
    return get_success_data(api.submit_application(vendor_id, None, ANALYST_HEADERS))


def authorize_vendor(api: ApiClient, vendor_id: str) -> Dict[str, Any]:
    return get_success_data(api.authorize_vendor(vendor_id, None, SUPERVISOR_HEADERS))


def submit_price(
    api: ApiClient,
    vendor_id: str,
    food_item_id: str,
    price_cycle_id: str,
    shelf_price_cents: int = BASE_SHELF_PRICE_CENTS,
) -> Dict[str, Any]:
    """A shelf price reported by the vendor itself."""
    return get_success_data(
        api.create_price_submission(
            f.price_submission_payload(
                vendor_id, food_item_id, price_cycle_id, shelf_price_cents
            ),
            make_vendor_operator_headers(vendor_id),
        )
    )


def accept_submission(api: ApiClient, submission_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.review_price_submission(
            submission_id,
            f.review_payload(decision=ReviewDecision.ACCEPT.value),
            ANALYST_HEADERS,
        )
    )


def reject_submission(
    api: ApiClient, submission_id: str, review_reason: str = "ABOVE_STATEWIDE_OUTLIER"
) -> Dict[str, Any]:
    return get_success_data(
        api.review_price_submission(
            submission_id,
            f.review_payload(
                decision=ReviewDecision.REJECT.value, review_reason=review_reason
            ),
            ANALYST_HEADERS,
        )
    )


def close_cycle(api: ApiClient, price_cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_price_cycle(price_cycle_id, None, SUPERVISOR_HEADERS))


def publish_cycle(api: ApiClient, price_cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.publish_ceilings(price_cycle_id, None, SUPERVISOR_HEADERS))


# ---------------------------------------------------------------------------
# Tier 2 - the reference catalogue and a vendor in review
# ---------------------------------------------------------------------------


def bootstrap_catalogue(
    api: ApiClient,
    with_juice: bool = False,
    with_cycle: bool = True,
    peer_group_overrides: Optional[Dict[str, Any]] = None,
    milk_category_overrides: Optional[Dict[str, Any]] = None,
    milk_item_overrides: Optional[Dict[str, Any]] = None,
    cycle_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    The two reference structures the rest of the system reads, plus a price cycle.

    Returns a bundle holding ``peer_group``, ``milk_category``, ``milk_item``,
    optionally ``juice_category`` and ``juice_item``, and optionally ``cycle``.
    """
    bundle: Dict[str, Any] = {}
    bundle["peer_group"] = create_peer_group(api, **(peer_group_overrides or {}))
    bundle["milk_category"] = create_food_category(
        api, **(milk_category_overrides or {})
    )
    bundle["milk_item"] = create_food_item(
        api, bundle["milk_category"]["id"], **(milk_item_overrides or {})
    )
    if with_juice:
        bundle["juice_category"] = create_food_category(
            api,
            code=JUICE_CATEGORY_CODE,
            name="Fruit Juice",
            min_stock_units=2,
            min_variety_count=1,
            max_units_per_transaction=4,
            stock_required=False,
        )
        bundle["juice_item"] = create_food_item(
            api,
            bundle["juice_category"]["id"],
            upc=JUICE_UPC,
            brand=JUICE_BRAND,
            container_size_oz=64,
            required_for_authorization=False,
        )
    if with_cycle:
        bundle["cycle"] = create_price_cycle(api, **(cycle_overrides or {}))
    return bundle


def add_bread_category(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A second participating stock category, so verification spans two categories."""
    payload = {
        "code": BREAD_CATEGORY_CODE,
        "name": "Whole Grain Bread",
        "min_stock_units": 3,
        "min_variety_count": 1,
        "max_units_per_transaction": 4,
        "stock_required": True,
    }
    payload.update(overrides)
    return create_food_category(api, **payload)


def vendor_in_review(
    api: ApiClient,
    store_name: str = VENDOR_STORE_NAME,
    reported_monthly_redemption_cents: int = VENDOR_REPORTED_CENTS,
    store_type: Optional[str] = None,
    with_training: bool = True,
    training_completed_at: str = TRAINING_COMPLETED_AT,
    **vendor_overrides: Any,
) -> Dict[str, Any]:
    """
    A vendor moved from APPLICANT to IN_REVIEW with its peer group assigned.

    Training is recorded first unless suppressed, since authorization needs it.
    """
    overrides: Dict[str, Any] = dict(vendor_overrides)
    if store_type is not None:
        overrides["store_type"] = store_type
    vendor = create_vendor(
        api,
        store_name=store_name,
        reported_monthly_redemption_cents=reported_monthly_redemption_cents,
        **overrides,
    )
    if with_training:
        record_training(api, vendor["id"], completed_at=training_completed_at)
    return submit_application(api, vendor["id"])


def vendor_with_accepted_price(
    api: ApiClient,
    food_item_id: str,
    price_cycle_id: str,
    shelf_price_cents: int = BASE_SHELF_PRICE_CENTS,
    **vendor_kwargs: Any,
) -> Dict[str, Any]:
    """A vendor in review whose shelf price for one item has been accepted."""
    vendor = vendor_in_review(api, **vendor_kwargs)
    submission = submit_price(
        api, vendor["id"], food_item_id, price_cycle_id, shelf_price_cents
    )
    submission = accept_submission(api, submission["id"])
    return {"vendor": get_vendor(api, vendor["id"]), "submission": submission}


# ---------------------------------------------------------------------------
# Tier 3 - the recurring backbone
# ---------------------------------------------------------------------------


def authorized_vendor_setup(
    api: ApiClient,
    with_juice: bool = False,
    shelf_price_cents: int = BASE_SHELF_PRICE_CENTS,
    juice_price_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """
    The catalogue, an open cycle, and one AUTHORIZED vendor with an accepted price.

    The cycle is left OPEN, so a caller that needs published ceilings continues
    with :func:`publish_canonical_ceilings`.

    Returns a bundle with ``peer_group``, ``milk_category``, ``milk_item``,
    optionally ``juice_category``/``juice_item``, ``cycle``, ``vendor``,
    ``submission``, optionally ``juice_submission``, and ``vendor_headers``.
    """
    bundle = bootstrap_catalogue(api, with_juice=with_juice)
    vendor = vendor_in_review(api)
    submission = submit_price(
        api,
        vendor["id"],
        bundle["milk_item"]["id"],
        bundle["cycle"]["id"],
        shelf_price_cents,
    )
    bundle["submission"] = accept_submission(api, submission["id"])
    if with_juice and juice_price_cents is not None:
        juice_submission = submit_price(
            api,
            vendor["id"],
            bundle["juice_item"]["id"],
            bundle["cycle"]["id"],
            juice_price_cents,
        )
        bundle["juice_submission"] = accept_submission(api, juice_submission["id"])
    bundle["vendor"] = authorize_vendor(api, vendor["id"])
    bundle["vendor_headers"] = make_vendor_operator_headers(vendor["id"])
    return bundle


def publish_canonical_ceilings(api: ApiClient, bundle: Dict[str, Any]) -> Dict[str, Any]:
    """
    Close and publish the bundle's cycle and record the resulting ACTIVE rows.

    Adds ``close_summary``, ``publish_summary``, ``cycle`` (refreshed) and
    ``milk_ceiling`` to the bundle, plus ``juice_ceiling`` when juice is in play.
    """
    bundle["close_summary"] = close_cycle(api, bundle["cycle"]["id"])
    bundle["publish_summary"] = publish_cycle(api, bundle["cycle"]["id"])
    bundle["cycle"] = get_price_cycle(api, bundle["cycle"]["id"])
    bundle["milk_ceiling"] = active_ceiling_for(
        api, bundle["peer_group"]["id"], bundle["milk_item"]["id"]
    )
    if "juice_submission" in bundle:
        bundle["juice_ceiling"] = active_ceiling_for(
            api, bundle["peer_group"]["id"], bundle["juice_item"]["id"]
        )
    bundle["vendor"] = get_vendor(api, bundle["vendor"]["id"])
    return bundle


def published_ceiling_setup(
    api: ApiClient,
    with_juice: bool = False,
    shelf_price_cents: int = BASE_SHELF_PRICE_CENTS,
    juice_price_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """
    The whole backbone: catalogue, authorized vendor, and a published ceiling.

    With the default shelf price of 320 cents the published milk ceiling is 336:
    one contributing submission, the statewide fallback basis, the five per cent
    allowance applied, and the cap idle.
    """
    bundle = authorized_vendor_setup(
        api,
        with_juice=with_juice,
        shelf_price_cents=shelf_price_cents,
        juice_price_cents=juice_price_cents,
    )
    return publish_canonical_ceilings(api, bundle)


def file_claim(
    api: ApiClient,
    vendor_id: str,
    lines: List[Dict[str, Any]],
    claim_month: str = "2026-07",
) -> Dict[str, Any]:
    """A month of redemptions filed by the vendor itself."""
    return get_success_data(
        api.create_redemption_claim(
            f.redemption_claim_payload(vendor_id, claim_month=claim_month, lines=lines),
            make_vendor_operator_headers(vendor_id),
        )
    )


def adjudicate(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return get_success_data(api.adjudicate_claim(claim_id, None, ANALYST_HEADERS))


def mark_paid(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return get_success_data(api.mark_claim_paid(claim_id, None, SUPERVISOR_HEADERS))


def adjudicated_claim_setup(
    api: ApiClient,
    lines: Optional[List[Dict[str, Any]]] = None,
    claim_month: str = "2026-07",
    with_juice: bool = False,
    juice_price_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """
    The backbone plus one adjudicated claim.

    The default single line buys one container of milk at the published ceiling, so
    the claim adjudicates to exactly that ceiling with no reduction.
    """
    bundle = published_ceiling_setup(
        api, with_juice=with_juice, juice_price_cents=juice_price_cents
    )
    if lines is None:
        lines = [
            f.claim_line_payload(1, MILK_UPC, 1, bundle["milk_ceiling"]["mar_cents"])
        ]
    claim = file_claim(api, bundle["vendor"]["id"], lines, claim_month=claim_month)
    bundle["claim"] = adjudicate(api, claim["id"])
    bundle["claim_lines"] = claim_lines_of(api, claim["id"])
    return bundle


def raise_adjustment(
    api: ApiClient,
    claim_id: str,
    expected_claim_version: int,
    recoupment_rate: float = 0.10,
    reason_code: str = AdjustmentReasonCode.EDIT_ERROR.value,
    headers=None,
) -> Dict[str, Any]:
    """A pending reimbursement adjustment against an adjudicated claim."""
    return get_success_data(
        api.create_reimbursement_adjustment(
            f.reimbursement_adjustment_payload(
                claim_id,
                expected_claim_version,
                reason_code=reason_code,
                recoupment_rate=recoupment_rate,
            ),
            headers or ANALYST_HEADERS,
        )
    )


def pending_adjustment_setup(
    api: ApiClient,
    recoupment_rate: float = 0.10,
    lines: Optional[List[Dict[str, Any]]] = None,
    creator_headers=None,
) -> Dict[str, Any]:
    """The backbone, an adjudicated claim, and one PENDING adjustment on it."""
    bundle = adjudicated_claim_setup(api, lines=lines)
    bundle["adjustment"] = raise_adjustment(
        api,
        bundle["claim"]["id"],
        bundle["claim"]["version"],
        recoupment_rate=recoupment_rate,
        headers=creator_headers,
    )
    bundle["claim"] = get_claim(api, bundle["claim"]["id"])
    return bundle


def apply_adjustment(api: ApiClient, adjustment_id: str, headers=None) -> Dict[str, Any]:
    """Apply a pending adjustment as a supervisor other than its creator."""
    return get_success_data(
        api.apply_adjustment(adjustment_id, None, headers or SUPERVISOR_TWO_HEADERS)
    )


def reverse_adjustment(
    api: ApiClient, adjustment_id: str, reversal_reason: Optional[str] = None, headers=None
) -> Dict[str, Any]:
    payload = (
        f.reversal_payload(reversal_reason)
        if reversal_reason is not None
        else f.reversal_payload()
    )
    return get_success_data(
        api.reverse_adjustment(adjustment_id, payload, headers or SUPERVISOR_TWO_HEADERS)
    )


def schedule_visit(
    api: ApiClient,
    vendor_id: str,
    scheduled_for: str,
    visit_type: str = VisitType.ROUTINE.value,
    headers=None,
) -> Dict[str, Any]:
    """Schedule one monitoring visit."""
    default_headers = (
        INVESTIGATOR_HEADERS
        if visit_type == VisitType.COMPLIANCE_BUY.value
        else ANALYST_HEADERS
    )
    return get_success_data(
        api.create_monitoring_visit(
            f.monitoring_visit_payload(
                vendor_id, visit_type=visit_type, scheduled_for=scheduled_for
            ),
            headers or default_headers,
        ),
        expected_status=201,
    )


def record_observation(
    api: ApiClient,
    visit_id: str,
    food_category_id: str,
    observed_units: int,
    observed_variety_count: int,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_observation(
            visit_id,
            f.observation_payload(
                food_category_id, observed_units, observed_variety_count
            ),
            headers or ANALYST_HEADERS,
        )
    )


def conduct_visit(
    api: ApiClient,
    visit_id: str,
    buy_items: Optional[List[Dict[str, Any]]] = None,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api.conduct_visit(
            visit_id, f.conduct_payload(buy_items), headers or ANALYST_HEADERS
        )
    )


def failed_visit_setup(
    api: ApiClient,
    bundle: Optional[Dict[str, Any]] = None,
    scheduled_for: str = "2026-08-05T00:00:00Z",
) -> Dict[str, Any]:
    """
    One routine visit conducted with no observations, so the milk category is
    missing and the visit fails.

    Builds the backbone first when no bundle is supplied. Adds ``visit`` and
    refreshes ``vendor``.
    """
    if bundle is None:
        bundle = published_ceiling_setup(api)
    visit = schedule_visit(api, bundle["vendor"]["id"], scheduled_for)
    bundle["visit"] = conduct_visit(api, visit["id"])
    bundle["vendor"] = get_vendor(api, bundle["vendor"]["id"])
    return bundle


def open_sanction_case(
    api: ApiClient,
    vendor_id: str,
    expected_vendor_version: int,
    violation_code: str = ViolationCode.CLASS_C.value,
    source_visit_id: Optional[str] = None,
    headers=None,
) -> Dict[str, Any]:
    """Open a sanction case by hand under the schedule."""
    return get_success_data(
        api.create_sanction_case(
            f.sanction_case_payload(
                vendor_id,
                expected_vendor_version,
                violation_code=violation_code,
                source_visit_id=source_visit_id,
            ),
            headers or INVESTIGATOR_HEADERS,
        )
    )


def serve_notice(api: ApiClient, case_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.serve_notice(case_id, None, headers or INVESTIGATOR_HEADERS)
    )


def served_case_setup(
    api: ApiClient,
    violation_code: str = ViolationCode.CLASS_C.value,
    bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    The backbone plus one sanction case served on the authorized vendor.

    Adds ``case`` (in NOTICE_SERVED) and refreshes ``vendor``.
    """
    if bundle is None:
        bundle = published_ceiling_setup(api)
    vendor = get_vendor(api, bundle["vendor"]["id"])
    case = open_sanction_case(
        api, vendor["id"], vendor["version"], violation_code=violation_code
    )
    bundle["case"] = serve_notice(api, case["id"])
    bundle["vendor"] = get_vendor(api, vendor["id"])
    return bundle


def elect_cmp(api: ApiClient, case_id: str, vendor_id: str) -> Dict[str, Any]:
    """The vendor itself elects the civil money penalty."""
    return get_success_data(
        api.elect_cmp(case_id, None, make_vendor_operator_headers(vendor_id))
    )


def impose_disqualification(api: ApiClient, case_id: str, headers=None) -> Dict[str, Any]:
    """Imposed by a principal other than the one that opened the case."""
    return get_success_data(
        api.impose_disqualification(case_id, None, headers or SUPERVISOR_TWO_HEADERS)
    )


def close_case(
    api: ApiClient,
    case_id: str,
    cmp_payment_cents: Optional[int] = None,
    headers=None,
) -> Dict[str, Any]:
    payload = (
        f.cmp_close_payload(cmp_payment_cents) if cmp_payment_cents is not None else None
    )
    return get_success_data(
        api.close_sanction_case(case_id, payload, headers or SUPERVISOR_HEADERS)
    )


# ---------------------------------------------------------------------------
# Tier 4 - whole scenarios
# ---------------------------------------------------------------------------


def two_authorized_vendors_setup(
    api: ApiClient,
    second_store_name: str = "Bravo Market",
    second_reported_cents: int = 7_000_000,
    second_shelf_price_cents: int = 349,
) -> Dict[str, Any]:
    """
    Two AUTHORIZED vendors inside the same peer group, both with accepted prices.

    Adds ``vendor_two``, ``submission_two`` and ``vendor_two_headers`` to the
    backbone bundle so a membership headcount can be watched across a sanction.
    """
    bundle = authorized_vendor_setup(api)
    second = vendor_in_review(
        api,
        store_name=second_store_name,
        reported_monthly_redemption_cents=second_reported_cents,
    )
    submission_two = submit_price(
        api,
        second["id"],
        bundle["milk_item"]["id"],
        bundle["cycle"]["id"],
        second_shelf_price_cents,
    )
    bundle["submission_two"] = accept_submission(api, submission_two["id"])
    bundle["vendor_two"] = authorize_vendor(api, second["id"])
    bundle["vendor_two_headers"] = make_vendor_operator_headers(second["id"])
    bundle["vendor"] = get_vendor(api, bundle["vendor"]["id"])
    bundle["peer_group"] = get_peer_group(api, bundle["peer_group"]["id"])
    return bundle


def compliance_buy_required_setup(
    api: ApiClient,
    first_visit_at: str = "2026-08-05T00:00:00Z",
    second_visit_at: str = "2026-08-06T00:00:00Z",
) -> Dict[str, Any]:
    """
    Two failed routine visits, which is what manufactures a compliance buy.

    The first visit is conducted before the second is scheduled, so the second is
    outside the blackout window of any still-scheduled visit. Adds ``visit_one``,
    ``visit_two`` and the system-created ``auto_visit``.
    """
    bundle = published_ceiling_setup(api)
    first = schedule_visit(api, bundle["vendor"]["id"], first_visit_at)
    bundle["visit_one"] = conduct_visit(api, first["id"])
    second = schedule_visit(api, bundle["vendor"]["id"], second_visit_at)
    bundle["visit_two"] = conduct_visit(api, second["id"])
    bundle["vendor"] = get_vendor(api, bundle["vendor"]["id"])
    auto_visits, _ = list_visits(
        api,
        {
            "vendor_id": bundle["vendor"]["id"],
            "visit_type": VisitType.COMPLIANCE_BUY.value,
            "limit": 100,
        },
    )
    bundle["auto_visit"] = auto_visits[0] if auto_visits else None
    return bundle


def peer_group_with_three_accepted_prices(
    api: ApiClient,
    peer_group_overrides: Dict[str, Any],
    prices: Tuple[int, int, int] = (200, 220, 300),
    reported_volumes: Tuple[int, int, int] = (1_000_000, 2_000_000, 3_000_000),
    store_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    One peer group holding three vendors in review, each with an accepted price.

    This is the shape the peer-group basis needs: enough submissions to clear
    ``min_submissions_for_ceiling`` without any statewide fallback.
    """
    bundle = bootstrap_catalogue(api, peer_group_overrides=peer_group_overrides)
    vendors = []
    submissions = []
    for index, (price, volume) in enumerate(zip(prices, reported_volumes), start=1):
        vendor = vendor_in_review(
            api,
            store_name=f"Peer Store {index}",
            reported_monthly_redemption_cents=volume,
            store_type=store_type,
        )
        submission = submit_price(
            api, vendor["id"], bundle["milk_item"]["id"], bundle["cycle"]["id"], price
        )
        submissions.append(accept_submission(api, submission["id"]))
        vendors.append(get_vendor(api, vendor["id"]))
    bundle["vendors"] = vendors
    bundle["submissions"] = submissions
    return bundle
