"""Distribution waterfall: tiered release offsets, clock-gated release, and the
temporal-release validation gate (§3.2).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    get_success_data, make_supplier_headers, TEST_USERS,
    create_program, create_supplier, create_worker, create_requisition,
    distribute, set_clock,
)
from test_helpers import factories as F

PM = TEST_USERS["program_manager_headers"]
HM = TEST_USERS["hiring_manager_headers"]


def _dist_for_supplier(distributions, supplier_id):
    matches = [d for d in distributions if d["supplier_id"] == supplier_id]
    assert len(matches) == 1, f"expected exactly one distribution for {supplier_id}"
    return matches[0]


# ===========================================================================
# Queue A: combinatorial_formula / distribution_waterfall_cumulative_offsets_over_distinct_tiers
# ===========================================================================

def test_waterfall_lowest_tier_released_immediately(api):
    """PRD §3.2: "the lowest distinct tier sits at position zero, so its offset
    is zero and its distributions are `RELEASED` immediately at distribution
    time"
    PRD §3.2: "Each distribution's `released_at` is the distribution clock plus
    its tier's release offset, measured in whole hours."

    Clock 2026-02-01; tier 1 at position 0 -> released_at == clock, RELEASED.

    Design: Difficulty/combinatorial_formula/distribution_waterfall_cumulative_offsets_over_distinct_tiers
    """
    program = create_program()
    set_clock(program["id"], "2026-02-01T00:00:00.000Z")
    s1 = create_supplier(program["id"], name="S1", tier=1)
    s2 = create_supplier(program["id"], name="S2", tier=2)
    s3 = create_supplier(program["id"], name="S3", tier=2)
    req = create_requisition(program["id"], tier_release_interval_hours=24)
    distribute(req["id"], [s1["id"], s2["id"], s3["id"]])
    dists, _ = api_paginated(api, req["id"])
    d1 = _dist_for_supplier(dists, s1["id"])
    assert d1["status"] == "RELEASED"
    assert d1["released_at"] == "2026-02-01T00:00:00.000Z", f"got {d1['released_at']}"


def test_waterfall_tied_tiers_share_single_offset(api):
    """PRD §3.2: "A tier's release offset is its zero-based position in that
    sorted list of distinct tiers, multiplied by the requisition's
    `tier_release_interval_hours`."
    PRD §3.2: "Distributions that share a tier share the same offset and the
    same `released_at`."

    Tiers 1/2/2, interval 24h: the two tier-2 distributions share released_at
    2026-02-02 (one distinct offset of 24h, not 24h then 48h), both PENDING.

    Design: Difficulty/combinatorial_formula/distribution_waterfall_cumulative_offsets_over_distinct_tiers
    """
    program = create_program()
    set_clock(program["id"], "2026-02-01T00:00:00.000Z")
    s1 = create_supplier(program["id"], name="S1", tier=1)
    s2 = create_supplier(program["id"], name="S2", tier=2)
    s3 = create_supplier(program["id"], name="S3", tier=2)
    req = create_requisition(program["id"], tier_release_interval_hours=24)
    distribute(req["id"], [s1["id"], s2["id"], s3["id"]])
    dists, _ = api_paginated(api, req["id"])
    d2 = _dist_for_supplier(dists, s2["id"])
    d3 = _dist_for_supplier(dists, s3["id"])
    assert d2["released_at"] == "2026-02-02T00:00:00.000Z", f"got {d2['released_at']}"
    assert d3["released_at"] == "2026-02-02T00:00:00.000Z", f"got {d3['released_at']}"
    assert d2["released_at"] == d3["released_at"]
    assert d2["status"] == "PENDING"
    assert d3["status"] == "PENDING"


# ===========================================================================
# Queue A: priority_pair_validation_conflict /
#          temporal_release_beats_fiscal_payrate_on_submittal_create
# ===========================================================================

def test_distribution_not_released_beats_pay_rate_ceiling(api):
    """PRD §3.2: "A supplier may create a submittal only once its distribution
    for that requisition is `RELEASED`; attempting to submit while the
    distribution is still `PENDING` — that is, while its `released_at` is after
    the current clock — is rejected with `ERR_DISTRIBUTION_NOT_RELEASED`."
    PRD §3.11: "Domain rules follow in this order: distribution-release timing,
    then the co-employment tenure safety stop, then milestone sequencing, then
    the negotiation-rounds cap, then remaining-openings, then the pay-rate
    ceiling, then the markup ceiling"

    Tier-2 supplier (Distribution PENDING) submits pay 99999 above max 10000;
    the higher-priority release gate wins -> ERR_DISTRIBUTION_NOT_RELEASED.

    Design: Difficulty/priority_pair_validation_conflict/temporal_release_beats_fiscal_payrate_on_submittal_create
    """
    program = create_program()
    set_clock(program["id"], "2026-02-01T00:00:00.000Z")
    s1 = create_supplier(program["id"], name="S1", tier=1)
    s2 = create_supplier(program["id"], name="S2", tier=2)
    worker = create_worker(program["id"])
    req = create_requisition(program["id"], max_pay_rate_cents=10000,
                             tier_release_interval_hours=24)
    distribute(req["id"], [s1["id"], s2["id"]])
    sh2 = make_supplier_headers(s2["id"])
    validate_error(
        api.create_submittal(
            F.create_submittal_payload(req["id"], s2["id"], worker["id"],
                                       pay_rate_cents=99999),
            sh2,
        ),
        ApiErrorId.ERR_DISTRIBUTION_NOT_RELEASED.value,
    )


def test_released_tier1_supplier_can_submit(api):
    """PRD §3.3: "The supplier's distribution for this requisition must be
    `RELEASED` first, as described in §3.2."
    PRD §3.2: "the lowest distinct tier sits at position zero, so its offset is
    zero and its distributions are `RELEASED` immediately at distribution time"

    The tier-1 supplier whose distribution is RELEASED may create a submittal.

    Design: Difficulty/priority_pair_validation_conflict/temporal_release_beats_fiscal_payrate_on_submittal_create
    """
    program = create_program()
    set_clock(program["id"], "2026-02-01T00:00:00.000Z")
    s1 = create_supplier(program["id"], name="S1", tier=1)
    s2 = create_supplier(program["id"], name="S2", tier=2)
    worker = create_worker(program["id"])
    req = create_requisition(program["id"], max_pay_rate_cents=10000,
                             tier_release_interval_hours=24)
    distribute(req["id"], [s1["id"], s2["id"]])
    sh1 = make_supplier_headers(s1["id"])
    data = validate_success(
        api.create_submittal(
            F.create_submittal_payload(req["id"], s1["id"], worker["id"],
                                       pay_rate_cents=8000),
            sh1,
        ),
        expected_status=201,
    )
    assert data["status"] == "SUBMITTED"


# ===========================================================================
# Queue B: endpoints / distribution_sweep_releases_tier2_after_clock_advance
# ===========================================================================

def test_clock_advance_releases_pending_tier2_distribution(api):
    """PRD §3.2: "When a `ProgramManager` advances the clock, the system sweeps
    every `PENDING` distribution whose `released_at` is at or before the new
    clock and flips it to `RELEASED`; the owning requisition remains
    `DISTRIBUTED` throughout."

    distribute at 2026-02-01; advance to 2026-02-02 flips the tier-2 distribution
    (released_at 2026-02-02) PENDING -> RELEASED.

    Design: Corner/endpoints/distribution_sweep_releases_tier2_after_clock_advance
    """
    program = create_program()
    set_clock(program["id"], "2026-02-01T00:00:00.000Z")
    s1 = create_supplier(program["id"], name="S1", tier=1)
    s2 = create_supplier(program["id"], name="S2", tier=2)
    req = create_requisition(program["id"], tier_release_interval_hours=24)
    distribute(req["id"], [s1["id"], s2["id"]])
    get_success_data(api.advance_clock(program["id"], {"to_iso8601": "2026-02-02T00:00:00.000Z"}, PM))
    dists, _ = api_paginated(api, req["id"], supplier_id=s2["id"])
    d2 = _dist_for_supplier(dists, s2["id"])
    assert d2["status"] == "RELEASED", f"got {d2['status']}"


# Helper that returns (list, meta) from the distributions list endpoint.
def api_paginated(api, requisition_id, supplier_id=None):
    from test_helpers import validate_paginated
    params = {"requisition_id": requisition_id}
    if supplier_id is not None:
        params["supplier_id"] = supplier_id
    return validate_paginated(api.list_distributions(PM, params=params))
