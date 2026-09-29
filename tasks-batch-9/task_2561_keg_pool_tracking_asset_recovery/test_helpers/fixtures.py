"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD declares.  The helpers
use the lenient success reader so that a broken precondition surfaces as a
setup failure rather than as a confusing assertion inside a test.
"""

from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    chargeback_resolution_payload,
    claim_response_payload,
    clean_step_payload,
    commodity_index_payload,
    cooperation_agreement_payload,
    create_brewer_payload,
    create_distributor_payload,
    create_float_agreement_payload,
    create_issuance_order_payload,
    create_loss_assessment_payload,
    create_pool_payload,
    create_reconciliation_claim_payload,
    create_service_center_payload,
    create_service_cycle_payload,
    create_theft_investigation_payload,
    distribution_scan_payload,
    fill_scan_payload,
    import_keg_payload,
    inspect_step_payload,
    investigation_status_payload,
    pressure_test_step_payload,
    resolve_assessment_payload,
    retail_scan_payload,
    return_scan_payload,
)
from .test_users import (
    ANALYST_USER_ID,
    SECOND_ANALYST_USER_ID,
    SECOND_TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    make_analyst_headers,
    make_brewer_headers,
    make_distributor_headers,
    make_technician_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]
SECOND_TECHNICIAN = TEST_USERS["second_technician_headers"]
ANALYST = TEST_USERS["analyst_headers"]
SECOND_ANALYST = TEST_USERS["second_analyst_headers"]


# ==========================================================================
# Tier 0 — single-call primitives
# ==========================================================================


def pin_clock(to_iso8601: str = TEST_CLOCK_UTC) -> dict:
    """Reposition the logical clock.  Called first by every scenario so that
    dwell windows, certification intervals and claim windows are pinned."""
    return get_success_data(api_client.set_clock(to_iso8601, OPERATOR))


def post_index(
    effective_date: Optional[str] = None, usd_cents_per_kg: Optional[int] = None
) -> dict:
    return get_success_data(
        api_client.post_commodity_index(
            commodity_index_payload(effective_date, usd_cents_per_kg), OPERATOR
        )
    )


def create_brewer(**overrides) -> dict:
    return get_success_data(
        api_client.create_brewer(create_brewer_payload(**overrides), OPERATOR)
    )


def create_distributor(**overrides) -> dict:
    return get_success_data(
        api_client.create_distributor(create_distributor_payload(**overrides), OPERATOR)
    )


def sign_cooperation_agreement(
    distributor_id: str, cooperation_tier: str, effective_date: str, **overrides
) -> dict:
    return get_success_data(
        api_client.set_cooperation_agreement(
            distributor_id,
            cooperation_agreement_payload(cooperation_tier, effective_date, **overrides),
            OPERATOR,
        )
    )


def create_pool(**overrides) -> dict:
    return get_success_data(
        api_client.create_pool(create_pool_payload(**overrides), OPERATOR)
    )


def import_keg(pool_id: str, asset_tag: str, **overrides) -> dict:
    return get_success_data(
        api_client.import_keg(pool_id, import_keg_payload(asset_tag, **overrides), OPERATOR)
    )


def import_kegs(pool_id: str, asset_tags: List[str], **overrides) -> List[dict]:
    return [import_keg(pool_id, tag, **overrides) for tag in asset_tags]


def read_pool(pool_id: str) -> dict:
    return get_success_data(api_client.get_pool(pool_id, OPERATOR))


def read_keg(keg_id: str) -> dict:
    return get_success_data(api_client.get_keg(keg_id, OPERATOR))


def read_brewer(brewer_id: str) -> dict:
    return get_success_data(api_client.get_brewer(brewer_id, OPERATOR))


def read_distributor(distributor_id: str) -> dict:
    return get_success_data(api_client.get_distributor(distributor_id, OPERATOR))


def read_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_float_agreement(agreement_id, OPERATOR))


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_issuance_order(order_id, OPERATOR))


def read_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.get_loss_assessment(assessment_id, ANALYST))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_reconciliation_claim(claim_id, OPERATOR))


def read_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_service_cycle(cycle_id, OPERATOR))


def read_investigation(investigation_id: str) -> dict:
    return get_success_data(
        api_client.get_theft_investigation(investigation_id, ANALYST)
    )


def read_accrual(accrual_id: str) -> dict:
    return get_success_data(api_client.get_return_incentive(accrual_id, OPERATOR))


def keg_version(keg_id: str) -> int:
    """Fresh version of a keg, for the assessment concurrency guard."""
    return read_keg(keg_id)["version"]


def agreement_version(agreement_id: str) -> int:
    """Fresh version of an agreement, for the allocation concurrency guard."""
    return read_agreement(agreement_id)["version"]


def claim_version(claim_id: str) -> int:
    """Fresh version of a claim, for the response concurrency guard."""
    return read_claim(claim_id)["version"]


# ==========================================================================
# Tier 1 — agreement, order and scan progression
# ==========================================================================


def create_agreement(
    brewer_id: str, pool_id: str, float_size_kegs: int, **overrides
) -> dict:
    return get_success_data(
        api_client.create_float_agreement(
            create_float_agreement_payload(
                brewer_id, pool_id, float_size_kegs, **overrides
            ),
            OPERATOR,
        )
    )


def activate_agreement(agreement_id: str, effective_date: Optional[str] = None) -> dict:
    return get_success_data(
        api_client.activate_float_agreement(
            agreement_id,
            {"effective_date": effective_date or TEST_DEFAULTS["EFFECTIVE_DATE"]},
            OPERATOR,
        )
    )


def create_and_activate_agreement(
    brewer_id: str,
    pool_id: str,
    float_size_kegs: int,
    effective_date: Optional[str] = None,
    **overrides,
) -> dict:
    """Draft an agreement and activate it.  Returns the activated agreement."""
    agreement = create_agreement(brewer_id, pool_id, float_size_kegs, **overrides)
    return activate_agreement(agreement["id"], effective_date)


def create_order(agreement_id: str, requested_keg_count: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_issuance_order(
            create_issuance_order_payload(agreement_id, requested_keg_count, **overrides),
            OPERATOR,
        )
    )


def allocate_order(order_id: str, agreement_id: str) -> dict:
    """Allocate against the agreement's current version."""
    return get_success_data(
        api_client.allocate_issuance_order(
            order_id,
            {"expected_agreement_version": agreement_version(agreement_id)},
            OPERATOR,
        )
    )


def dispatch_order(order_id: str, dispatched_at: str) -> dict:
    return get_success_data(
        api_client.dispatch_issuance_order(
            order_id, {"dispatched_at": dispatched_at}, OPERATOR
        )
    )


def cancel_order(order_id: str, cancel_reason: str = "Brewer deferred the delivery.") -> dict:
    return get_success_data(
        api_client.cancel_issuance_order(
            order_id, {"cancel_reason": cancel_reason}, OPERATOR
        )
    )


def order_allocated_and_dispatched(
    agreement_id: str, requested_keg_count: int, dispatched_at: str, **overrides
) -> dict:
    """Request, allocate and dispatch one order.  Returns the dispatched order."""
    order = create_order(agreement_id, requested_keg_count, **overrides)
    allocate_order(order["id"], agreement_id)
    return dispatch_order(order["id"], dispatched_at)


def fill_scan(
    keg_id: str, brewer_id: str, scanned_at: str, brand_code: str, **overrides
) -> dict:
    """Record a fill scan as the filling brewer itself."""
    return get_success_data(
        api_client.scan_keg(
            keg_id,
            fill_scan_payload(brewer_id, scanned_at, brand_code, **overrides),
            make_brewer_headers(brewer_id),
        )
    )


def distribution_scan(
    keg_id: str, distributor_id: str, scanned_at: str, brand_code: str, **overrides
) -> dict:
    """Record a distribution scan as the receiving distributor itself."""
    return get_success_data(
        api_client.scan_keg(
            keg_id,
            distribution_scan_payload(distributor_id, scanned_at, brand_code, **overrides),
            make_distributor_headers(distributor_id),
        )
    )


def retail_scan(
    keg_id: str,
    distributor_id: str,
    retail_account_code: str,
    scanned_at: str,
    brand_code: str,
    **overrides,
) -> dict:
    """Record a retail scan.  The acting distributor is the one holding the
    keg; the scanned party is the retail account."""
    return get_success_data(
        api_client.scan_keg(
            keg_id,
            retail_scan_payload(retail_account_code, scanned_at, brand_code, **overrides),
            make_distributor_headers(distributor_id),
        )
    )


def return_scan(
    keg_id: str, distributor_id: str, scanned_at: str, brand_code: str, **overrides
) -> dict:
    """Record a return scan as the returning distributor itself."""
    return get_success_data(
        api_client.scan_keg(
            keg_id,
            return_scan_payload(distributor_id, scanned_at, brand_code, **overrides),
            make_distributor_headers(distributor_id),
        )
    )


def sweep_pool(pool_id: str) -> dict:
    return get_success_data(api_client.replenishment_sweep(pool_id, OPERATOR))


# ==========================================================================
# Tier 1b — servicing, loss, claim and investigation primitives
# ==========================================================================


def create_service_center(concurrent_cycle_capacity: int = 1, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_center(
            create_service_center_payload(concurrent_cycle_capacity, **overrides),
            OPERATOR,
        )
    )


def create_service_cycle(
    keg_id: str, service_center_id: str, received_at: str, headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.create_service_cycle(
            create_service_cycle_payload(keg_id, service_center_id, received_at),
            headers or OPERATOR,
        )
    )


def record_clean(cycle_id: str, occurred_at: str, caustic_cycle_minutes: int = 12,
                 technician_id: str = TECHNICIAN_USER_ID) -> dict:
    return get_success_data(
        api_client.record_service_step(
            cycle_id,
            clean_step_payload(occurred_at, caustic_cycle_minutes),
            make_technician_headers(technician_id),
        )
    )


def record_inspect(cycle_id: str, occurred_at: str, inspection_result: str = "PASS",
                   technician_id: str = TECHNICIAN_USER_ID) -> dict:
    return get_success_data(
        api_client.record_service_step(
            cycle_id,
            inspect_step_payload(occurred_at, inspection_result),
            make_technician_headers(technician_id),
        )
    )


def record_pressure_test(
    cycle_id: str,
    occurred_at: str,
    pressure_test_psi: float = 45,
    pressure_test_result: str = "PASS",
    technician_id: str = TECHNICIAN_USER_ID,
) -> dict:
    return get_success_data(
        api_client.record_service_step(
            cycle_id,
            pressure_test_step_payload(
                occurred_at, pressure_test_psi, pressure_test_result
            ),
            make_technician_headers(technician_id),
        )
    )


def release_cycle(cycle_id: str, released_at: str, headers: Optional[dict] = None) -> dict:
    """Release a pressure-tested cycle.  Defaults to the pool operator so the
    release is never performed by the technician who ran the test."""
    return get_success_data(
        api_client.release_service_cycle(
            cycle_id, {"released_at": released_at}, headers or OPERATOR
        )
    )


def open_loss_assessment(
    keg_id: str,
    cause: str,
    analyst_id: str = ANALYST_USER_ID,
    assessment_basis: Optional[str] = None,
    **overrides,
) -> dict:
    """Open a loss assessment against the keg's current version."""
    payload = create_loss_assessment_payload(
        keg_id, cause, keg_version(keg_id), **overrides
    )
    if assessment_basis is not None:
        payload["assessment_basis"] = assessment_basis
    return get_success_data(
        api_client.create_loss_assessment(payload, make_analyst_headers(analyst_id))
    )


def dispute_assessment(assessment_id: str, brewer_id: str, dispute_reason: str) -> dict:
    return get_success_data(
        api_client.dispute_loss_assessment(
            assessment_id,
            {"dispute_reason": dispute_reason},
            make_brewer_headers(brewer_id),
        )
    )


def resolve_assessment(
    assessment_id: str,
    resolution: str,
    analyst_id: str = SECOND_ANALYST_USER_ID,
    **overrides,
) -> dict:
    """Resolve an assessment.  Defaults to a second analyst so the resolver is
    never the analyst who opened it."""
    return get_success_data(
        api_client.resolve_loss_assessment(
            assessment_id,
            resolve_assessment_payload(resolution, **overrides),
            make_analyst_headers(analyst_id),
        )
    )


def settle_chargeback(assessment_id: str, amount_cents: int, **overrides) -> dict:
    return get_success_data(
        api_client.chargeback_resolution(
            assessment_id,
            chargeback_resolution_payload("SETTLE", amount_cents=amount_cents, **overrides),
            OPERATOR,
        )
    )


def reverse_chargeback(
    assessment_id: str, analyst_id: str = ANALYST_USER_ID, **overrides
) -> dict:
    return get_success_data(
        api_client.chargeback_resolution(
            assessment_id,
            chargeback_resolution_payload("REVERSE", **overrides),
            make_analyst_headers(analyst_id),
        )
    )


def file_claim(
    keg_id: str,
    claimant_distributor_id: str,
    misdelivered_to_brewer_id: str,
    claimed_offset_cents: int,
    evidence_scanned_at: str,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_reconciliation_claim(
            create_reconciliation_claim_payload(
                keg_id,
                misdelivered_to_brewer_id,
                claimed_offset_cents,
                evidence_scanned_at,
                **overrides,
            ),
            make_distributor_headers(claimant_distributor_id),
        )
    )


def respond_to_claim(claim_id: str, response: str, headers: dict, **overrides) -> dict:
    """Respond to a claim against its current version."""
    return get_success_data(
        api_client.respond_reconciliation_claim(
            claim_id,
            claim_response_payload(response, claim_version(claim_id), **overrides),
            headers,
        )
    )


def open_investigation(
    pool_id: str, keg_ids: List[str], analyst_id: str = ANALYST_USER_ID, **overrides
) -> dict:
    return get_success_data(
        api_client.create_theft_investigation(
            create_theft_investigation_payload(pool_id, keg_ids, **overrides),
            make_analyst_headers(analyst_id),
        )
    )


def set_investigation_status(
    investigation_id: str, action: str, analyst_id: str = ANALYST_USER_ID, **overrides
) -> dict:
    return get_success_data(
        api_client.set_investigation_status(
            investigation_id,
            investigation_status_payload(action, **overrides),
            make_analyst_headers(analyst_id),
        )
    )


def pay_accrual(accrual_id: str, paid_at: str) -> dict:
    return get_success_data(
        api_client.pay_return_incentive(accrual_id, {"paid_at": paid_at}, OPERATOR)
    )


# ==========================================================================
# Tier 2 — entity hierarchy: pool, fleet, brewer, distributor
# ==========================================================================


def setup_pool_with_kegs(
    keg_count: int = 4,
    asset_tag_prefix: str = "K-",
    pool_overrides: Optional[dict] = None,
    keg_specs: Optional[List[dict]] = None,
    clock: Optional[str] = TEST_CLOCK_UTC,
    with_index: bool = True,
) -> dict:
    """Pin the clock, post a stainless index reading, create one pool and
    import a fleet into it.

    ``keg_specs`` overrides the fleet one keg at a time; each entry is the
    import payload's optional fields (``fill_count``,
    ``fills_at_last_pressure_test``, ``last_pressure_test_at``,
    ``initial_custody_state``) plus an optional ``asset_tag``.
    """
    if clock is not None:
        pin_clock(clock)
    index = post_index() if with_index else None
    pool = create_pool(**(pool_overrides or {}))
    specs = keg_specs if keg_specs is not None else [{} for _ in range(keg_count)]
    kegs = []
    for position, spec in enumerate(specs, start=1):
        spec = dict(spec)
        asset_tag = spec.pop("asset_tag", f"{asset_tag_prefix}{position:04d}")
        kegs.append(import_keg(pool["id"], asset_tag, **spec))
    return {"index": index, "pool": pool, "kegs": kegs}


def setup_brewer_and_stocked_pool(
    keg_count: int = 4,
    brewer_overrides: Optional[dict] = None,
    pool_overrides: Optional[dict] = None,
    keg_specs: Optional[List[dict]] = None,
    clock: Optional[str] = TEST_CLOCK_UTC,
    with_index: bool = True,
) -> dict:
    """One brewer plus a stocked pool.  Returns
    ``{index, brewer, pool, kegs}``."""
    if clock is not None:
        pin_clock(clock)
    index = post_index() if with_index else None
    brewer = create_brewer(**(brewer_overrides or {}))
    stock = setup_pool_with_kegs(
        keg_count=keg_count,
        pool_overrides=pool_overrides,
        keg_specs=keg_specs,
        clock=None,
        with_index=False,
    )
    return {
        "index": index,
        "brewer": brewer,
        "pool": stock["pool"],
        "kegs": stock["kegs"],
    }


def setup_active_float(
    float_size_kegs: int = 4,
    keg_count: int = 4,
    brewer_overrides: Optional[dict] = None,
    pool_overrides: Optional[dict] = None,
    agreement_overrides: Optional[dict] = None,
    keg_specs: Optional[List[dict]] = None,
    effective_date: Optional[str] = None,
    clock: Optional[str] = TEST_CLOCK_UTC,
    with_index: bool = True,
) -> dict:
    """A brewer, a stocked pool and one activated float agreement over them.

    Returns ``{index, brewer, pool, kegs, agreement}`` where ``agreement`` is
    the response body of the activation.
    """
    base = setup_brewer_and_stocked_pool(
        keg_count=keg_count,
        brewer_overrides=brewer_overrides,
        pool_overrides=pool_overrides,
        keg_specs=keg_specs,
        clock=clock,
        with_index=with_index,
    )
    agreement = create_and_activate_agreement(
        base["brewer"]["id"],
        base["pool"]["id"],
        float_size_kegs,
        effective_date=effective_date,
        **(agreement_overrides or {}),
    )
    base["agreement"] = agreement
    return base


def setup_drafted_float(
    float_size_kegs: int = 4,
    keg_count: int = 4,
    brewer_overrides: Optional[dict] = None,
    pool_overrides: Optional[dict] = None,
    agreement_overrides: Optional[dict] = None,
    keg_specs: Optional[List[dict]] = None,
    clock: Optional[str] = TEST_CLOCK_UTC,
    with_index: bool = True,
) -> dict:
    """Same shape as :func:`setup_active_float` but the agreement is left in
    its drafted state, which gates nothing and cannot back an order."""
    base = setup_brewer_and_stocked_pool(
        keg_count=keg_count,
        brewer_overrides=brewer_overrides,
        pool_overrides=pool_overrides,
        keg_specs=keg_specs,
        clock=clock,
        with_index=with_index,
    )
    base["agreement"] = create_agreement(
        base["brewer"]["id"],
        base["pool"]["id"],
        float_size_kegs,
        **(agreement_overrides or {}),
    )
    return base


# ==========================================================================
# Tier 3 — full lifecycle shortcuts
# ==========================================================================


def setup_dispatched_float(
    requested_keg_count: int = 1,
    dispatched_at: str = "2026-08-01T00:00:00Z",
    float_size_kegs: int = 4,
    keg_count: int = 4,
    **setup_kwargs,
) -> dict:
    """Walk a float all the way to the brewer: activate the agreement, request
    an order, allocate it and dispatch it.

    Returns ``{index, brewer, pool, kegs, agreement, order, allocated_keg_ids}``.
    """
    ctx = setup_active_float(
        float_size_kegs=float_size_kegs, keg_count=keg_count, **setup_kwargs
    )
    order = create_order(ctx["agreement"]["id"], requested_keg_count)
    allocate_order(order["id"], ctx["agreement"]["id"])
    ctx["order"] = dispatch_order(order["id"], dispatched_at)
    ctx["allocated_keg_ids"] = ctx["order"]["allocated_keg_ids"]
    return ctx


def setup_filled_keg(
    scanned_at: str = "2026-08-01T12:00:00Z",
    dispatched_at: str = "2026-08-01T00:00:00Z",
    requested_keg_count: int = 1,
    float_size_kegs: int = 4,
    keg_count: int = 4,
    brand_code: Optional[str] = None,
    **setup_kwargs,
) -> dict:
    """Dispatch a float and record one fill scan on the first allocated keg.

    Returns the dispatched-float context plus ``{keg_id, fill_scan}``.
    """
    ctx = setup_dispatched_float(
        requested_keg_count=requested_keg_count,
        dispatched_at=dispatched_at,
        float_size_kegs=float_size_kegs,
        keg_count=keg_count,
        **setup_kwargs,
    )
    keg_id = ctx["allocated_keg_ids"][0]
    ctx["keg_id"] = keg_id
    ctx["fill_scan"] = fill_scan(
        keg_id,
        ctx["brewer"]["id"],
        scanned_at,
        brand_code or ctx["brewer"]["brand_code"],
    )
    return ctx


def setup_keg_in_trade(
    fill_scanned_at: str = "2026-08-01T12:00:00Z",
    distribution_scanned_at: str = "2026-08-01T14:00:00Z",
    distributor_overrides: Optional[dict] = None,
    cooperation_tier: Optional[str] = None,
    cooperation_effective_date: Optional[str] = None,
    **setup_kwargs,
) -> dict:
    """Fill a keg then hand it to a distributor, which opens the distributor
    accountability clock.

    Returns the filled-keg context plus ``{distributor, distribution_scan}``.
    """
    ctx = setup_filled_keg(scanned_at=fill_scanned_at, **setup_kwargs)
    distributor = create_distributor(**(distributor_overrides or {}))
    if cooperation_tier is not None:
        distributor = sign_cooperation_agreement(
            distributor["id"],
            cooperation_tier,
            cooperation_effective_date or TEST_DEFAULTS["EFFECTIVE_DATE"],
        )
    ctx["distributor"] = distributor
    ctx["distribution_scan"] = distribution_scan(
        ctx["keg_id"],
        distributor["id"],
        distribution_scanned_at,
        ctx["brewer"]["brand_code"],
    )
    return ctx


def setup_returned_keg(
    return_scanned_at: str = "2026-08-01T16:00:00Z",
    **setup_kwargs,
) -> dict:
    """Take a keg through fill, distribution and return, which mints the
    return incentive accrual.

    Returns the in-trade context plus ``{return_scan, accrual}``.
    """
    ctx = setup_keg_in_trade(**setup_kwargs)
    ctx["return_scan"] = return_scan(
        ctx["keg_id"],
        ctx["distributor"]["id"],
        return_scanned_at,
        ctx["brewer"]["brand_code"],
    )
    accruals, _ = _list_accruals(ctx["distributor"]["id"])
    ctx["accrual"] = accruals[0] if accruals else None
    return ctx


def _list_accruals(distributor_id: str) -> Tuple[List[dict], dict]:
    response = api_client.list_return_incentives(
        OPERATOR, params={"distributor_id": distributor_id}
    )
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def setup_proposed_assessment(
    cause: str = "LOST_IN_TRADE",
    assessment_basis: Optional[str] = None,
    analyst_id: str = ANALYST_USER_ID,
    **setup_kwargs,
) -> dict:
    """Fill a keg then open a loss assessment on it.

    Returns the filled-keg context plus ``{assessment}``.
    """
    ctx = setup_filled_keg(**setup_kwargs)
    ctx["assessment"] = open_loss_assessment(
        ctx["keg_id"], cause, analyst_id=analyst_id, assessment_basis=assessment_basis
    )
    return ctx


def setup_issued_chargeback(
    cause: str = "LOST_IN_TRADE",
    assessment_basis: Optional[str] = None,
    resolver_id: str = SECOND_ANALYST_USER_ID,
    **setup_kwargs,
) -> dict:
    """Open and uphold a loss assessment, which issues the chargeback and
    writes the keg off.

    Returns the proposed-assessment context with ``assessment`` replaced by
    the upheld row.
    """
    ctx = setup_proposed_assessment(
        cause=cause, assessment_basis=assessment_basis, **setup_kwargs
    )
    ctx["assessment"] = resolve_assessment(
        ctx["assessment"]["id"], "UPHELD", analyst_id=resolver_id
    )
    return ctx


# ==========================================================================
# Tier 4 — accumulation and threshold targeting
# ==========================================================================


def setup_pool_at_available_pct(
    keg_count: int,
    allocate_count: int,
    float_size_kegs: Optional[int] = None,
    dispatched_at: Optional[str] = None,
    **setup_kwargs,
) -> dict:
    """Stock a pool with ``keg_count`` kegs and move ``allocate_count`` of
    them out of float, so the pool's available percentage lands on a chosen
    value and its posture follows from it.

    Returns ``{index, brewer, pool, kegs, agreement, order}``; ``order`` is
    ``None`` when nothing was allocated.
    """
    ctx = setup_active_float(
        float_size_kegs=float_size_kegs or max(keg_count, allocate_count, 1),
        keg_count=keg_count,
        **setup_kwargs,
    )
    ctx["order"] = None
    if allocate_count:
        order = create_order(ctx["agreement"]["id"], allocate_count)
        order = allocate_order(order["id"], ctx["agreement"]["id"])
        if dispatched_at is not None:
            order = dispatch_order(order["id"], dispatched_at)
        ctx["order"] = order
        ctx["allocated_keg_ids"] = order["allocated_keg_ids"]
    return ctx


def setup_agreement_with_billed_fills(
    fill_instants: List[str],
    float_size_kegs: int = 4,
    keg_count: int = 4,
    dispatched_at: str = "2026-08-01T00:00:00Z",
    **setup_kwargs,
) -> dict:
    """Dispatch as many kegs as there are fill instants and record one fill on
    each, so the agreement's billed total accumulates through the volume
    tiers.

    Returns the dispatched-float context plus ``{fill_scans}`` in charge order.
    """
    ctx = setup_dispatched_float(
        requested_keg_count=len(fill_instants),
        dispatched_at=dispatched_at,
        float_size_kegs=float_size_kegs,
        keg_count=keg_count,
        **setup_kwargs,
    )
    scans = []
    for keg_id, scanned_at in zip(ctx["allocated_keg_ids"], fill_instants):
        scans.append(
            fill_scan(keg_id, ctx["brewer"]["id"], scanned_at, ctx["brewer"]["brand_code"])
        )
    ctx["fill_scans"] = scans
    return ctx


def setup_distributor_with_returns(
    return_specs: List[Tuple[str, str, str]],
    cooperation_tier: str = "BRONZE",
    cooperation_effective_date: Optional[str] = None,
    float_size_kegs: int = 4,
    keg_count: int = 4,
    dispatched_at: str = "2026-08-01T00:00:00Z",
    fill_instant: str = "2026-08-01T00:00:00Z",
    **setup_kwargs,
) -> dict:
    """Run several kegs through fill, distribution and return for one
    distributor so that its return statistics and cooperation tier accumulate.

    ``return_specs`` is a list of ``(fill_at, distribution_at, return_at)``
    instants, one per keg.  Returns the active-float context plus
    ``{distributor, accruals}``.
    """
    ctx = setup_dispatched_float(
        requested_keg_count=len(return_specs),
        dispatched_at=dispatched_at,
        float_size_kegs=float_size_kegs,
        keg_count=keg_count,
        **setup_kwargs,
    )
    distributor = create_distributor()
    distributor = sign_cooperation_agreement(
        distributor["id"],
        cooperation_tier,
        cooperation_effective_date or TEST_DEFAULTS["EFFECTIVE_DATE"],
    )
    ctx["distributor"] = distributor
    brand = ctx["brewer"]["brand_code"]
    for keg_id, (fill_at, distribute_at, return_at) in zip(
        ctx["allocated_keg_ids"], return_specs
    ):
        fill_scan(keg_id, ctx["brewer"]["id"], fill_at or fill_instant, brand)
        distribution_scan(keg_id, distributor["id"], distribute_at, brand)
        return_scan(keg_id, distributor["id"], return_at, brand)
    accruals, _ = _list_accruals(distributor["id"])
    ctx["accruals"] = accruals
    return ctx


def setup_brewer_on_probation(
    cause: str = "NOT_RETURNED_DWELL",
    pool_overrides: Optional[dict] = None,
    **setup_kwargs,
) -> dict:
    """Uphold one assessment large enough to push the brewer off its active
    standing, which suspends the float posture of its agreements.

    Returns the issued-chargeback context.
    """
    return setup_issued_chargeback(
        cause=cause,
        assessment_basis="REPLACEMENT_COST",
        pool_overrides=pool_overrides,
        **setup_kwargs,
    )


def setup_suspended_float_via_brewer_status(
    status: str = "PROBATION",
    status_reason: str = "Manual review of the account.",
    **setup_kwargs,
) -> dict:
    """Activate a float, then override the brewer's standing so the agreement's
    float posture is suspended.

    Returns the active-float context plus ``{brewer_after_status}``.
    """
    ctx = setup_active_float(**setup_kwargs)
    ctx["brewer_after_status"] = get_success_data(
        api_client.set_brewer_status(
            ctx["brewer"]["id"],
            {"status": status, "status_reason": status_reason},
            OPERATOR,
        )
    )
    return ctx


# ==========================================================================
# Tier 5 — servicing, claims and investigations at their late stages
# ==========================================================================


def setup_service_cycle(
    received_at: str = "2026-08-01T08:00:00Z",
    concurrent_cycle_capacity: int = 1,
    center_overrides: Optional[dict] = None,
    keg_count: int = 4,
    **setup_kwargs,
) -> dict:
    """Stock a pool, create a service centre and book one keg in off the float.

    Returns ``{index, pool, kegs, center, cycle, keg_id}``.
    """
    stock = setup_pool_with_kegs(keg_count=keg_count, **setup_kwargs)
    center = create_service_center(
        concurrent_cycle_capacity, **(center_overrides or {})
    )
    keg_id = stock["kegs"][0]["id"]
    cycle = create_service_cycle(keg_id, center["id"], received_at)
    stock.update({"center": center, "cycle": cycle, "keg_id": keg_id})
    return stock


def setup_cycle_ready_for_release(
    received_at: str = "2026-08-01T08:00:00Z",
    cleaned_at: str = "2026-08-01T08:30:00Z",
    inspected_at: str = "2026-08-01T08:45:00Z",
    pressure_tested_at: str = "2026-08-01T09:00:00Z",
    technician_id: str = TECHNICIAN_USER_ID,
    pressure_test_psi: float = 45,
    **setup_kwargs,
) -> dict:
    """Book a keg in and walk the cycle through cleaning, inspection and a
    passing pressure test, leaving it one release short of returning to float.

    Returns the service-cycle context with ``cycle`` at its pressure-tested
    stage.
    """
    ctx = setup_service_cycle(received_at=received_at, **setup_kwargs)
    record_clean(ctx["cycle"]["id"], cleaned_at, technician_id=technician_id)
    record_inspect(ctx["cycle"]["id"], inspected_at, technician_id=technician_id)
    ctx["cycle"] = record_pressure_test(
        ctx["cycle"]["id"],
        pressure_tested_at,
        pressure_test_psi=pressure_test_psi,
        technician_id=technician_id,
    )
    return ctx


def setup_quarantined_cycle(
    quarantine_step: str = "PRESSURE_TEST",
    received_at: str = "2026-08-01T08:00:00Z",
    cleaned_at: str = "2026-08-01T08:30:00Z",
    inspected_at: str = "2026-08-01T08:45:00Z",
    pressure_tested_at: str = "2026-08-01T09:00:00Z",
    technician_id: str = TECHNICIAN_USER_ID,
    **setup_kwargs,
) -> dict:
    """Drive a cycle into quarantine, either by a major inspection defect or by
    a failing pressure test.

    Returns the service-cycle context with ``cycle`` quarantined.
    """
    ctx = setup_service_cycle(received_at=received_at, **setup_kwargs)
    record_clean(ctx["cycle"]["id"], cleaned_at, technician_id=technician_id)
    if quarantine_step == "INSPECT":
        ctx["cycle"] = record_inspect(
            ctx["cycle"]["id"],
            inspected_at,
            inspection_result="MAJOR_DEFECT",
            technician_id=technician_id,
        )
        return ctx
    record_inspect(ctx["cycle"]["id"], inspected_at, technician_id=technician_id)
    ctx["cycle"] = record_pressure_test(
        ctx["cycle"]["id"],
        pressure_tested_at,
        pressure_test_psi=34,
        pressure_test_result="FAIL",
        technician_id=technician_id,
    )
    return ctx


def setup_misdelivery_evidence(
    owning_fill_at: str = "2026-08-01T08:00:00Z",
    distribution_at: str = "2026-08-01T10:00:00Z",
    other_brand_code: str = "CKB",
    other_brewer_name: str = "Copper Kettle Brewing",
    **setup_kwargs,
) -> dict:
    """Fill a keg under one brand, register a second brewer that owns another
    brand, and then record a distribution scan reading that other brand off
    the collar, which is the cross-brand evidence a claim needs.

    Returns ``{index, brewer, other_brewer, pool, kegs, agreement, order,
    keg_id, distributor, evidence_scan}``.
    """
    ctx = setup_filled_keg(scanned_at=owning_fill_at, **setup_kwargs)
    ctx["other_brewer"] = create_brewer(
        name=other_brewer_name, brand_code=other_brand_code
    )
    distributor = create_distributor()
    ctx["distributor"] = distributor
    ctx["evidence_scan"] = distribution_scan(
        ctx["keg_id"], distributor["id"], distribution_at, other_brand_code
    )
    return ctx


def setup_open_claim(
    claimed_offset_cents: int = 1200,
    **setup_kwargs,
) -> dict:
    """Build cross-brand evidence and file the reconciliation claim on it.

    Returns the misdelivery-evidence context plus ``{claim}``.
    """
    ctx = setup_misdelivery_evidence(**setup_kwargs)
    ctx["claim"] = file_claim(
        ctx["keg_id"],
        ctx["distributor"]["id"],
        ctx["other_brewer"]["id"],
        claimed_offset_cents,
        ctx["evidence_scan"]["scanned_at"],
    )
    return ctx


def setup_investigation_with_attached_kegs(
    attached_positions: Optional[List[int]] = None,
    keg_count: int = 4,
    analyst_id: str = ANALYST_USER_ID,
    **setup_kwargs,
) -> dict:
    """Stock a pool and open a theft investigation over some of its kegs.

    Returns ``{index, pool, kegs, investigation, attached_keg_ids}``.
    """
    stock = setup_pool_with_kegs(keg_count=keg_count, **setup_kwargs)
    positions = attached_positions if attached_positions is not None else [0, 1]
    attached = [stock["kegs"][position]["id"] for position in positions]
    stock["attached_keg_ids"] = attached
    stock["investigation"] = open_investigation(
        stock["pool"]["id"], attached, analyst_id=analyst_id
    )
    return stock


def setup_investigation_on_evidence_hold(
    held_positions: Optional[List[int]] = None,
    hold_started_at: str = "2026-08-01T12:00:00Z",
    analyst_id: str = ANALYST_USER_ID,
    **setup_kwargs,
) -> dict:
    """Open an investigation and place some of its attached kegs on evidence
    hold, which moves them out of their occupancy bucket.

    Returns the investigation context with ``investigation`` on hold plus
    ``{held_keg_ids}``.
    """
    ctx = setup_investigation_with_attached_kegs(analyst_id=analyst_id, **setup_kwargs)
    held = (
        [ctx["kegs"][position]["id"] for position in held_positions]
        if held_positions is not None
        else ctx["attached_keg_ids"][:1]
    )
    ctx["held_keg_ids"] = held
    ctx["investigation"] = set_investigation_status(
        ctx["investigation"]["id"],
        "EVIDENCE_HOLD",
        analyst_id=analyst_id,
        keg_ids=held,
        hold_started_at=hold_started_at,
    )
    return ctx
