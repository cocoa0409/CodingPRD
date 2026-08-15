"""Top-down allocations: largest-remainder waterfall, zero-weight equal split,
leaf landing, supersede conservation, discard terminality, and OCC guard."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    activate_territory,
    add_territory,
    apply_allocation,
    assert_allocation,
    create_allocation,
    create_plan,
    get_plan,
    get_territory,
    plan_version,
    setup_open_plan,
    setup_open_plan_with_children,
    validate_error,
    validate_success,
)


def _apply(api, alloc_id, plan_id, version):
    return api.apply_allocation(alloc_id, version, ADMIN)


def test_allocation_distributes_remainder_cent_to_largest_fraction(api):
    """PRD: "each child receives the floor of its raw share, and the remaining
    cents — the pool minus the sum of those floors — are handed out one cent at
    a time to children ordered by the fractional part of their raw share,
    largest first, ties broken by child creation order, earliest first."
    PRD: "In all cases the scope's own `assigned_quota_cents` becomes exactly
    the pool, each active child's `assigned_quota_cents` becomes its share, and
    the conservation invariant holds: the children's shares sum back to the
    pool with zero drift."

    Pool 1000001 over potentials 100/200/700: raw shares 100000.1 / 200000.2 /
    700000.7, so the single remainder cent lands on child C (fraction .7).

    Design: Difficulty/combinatorial_formula/allocation_largest_remainder_three_way
    """
    fx = setup_open_plan_with_children(potentials=(100, 200, 700),
                                       target=1000001, productivity=500000,
                                       label="FY27-ALLOC")
    plan_id = fx["plan"]["id"]
    ta, tb, tc = (c["id"] for c in fx["children"])
    alloc = create_allocation(plan_id, fx["root"]["id"], 1000001)
    applied = apply_allocation(alloc["id"], plan_id)
    assert applied["status"] == "APPLIED"

    shares = {tid: get_territory(tid)["assigned_quota_cents"]
              for tid in (ta, tb, tc)}
    assert shares[ta] == 100000
    assert shares[tb] == 200000
    assert shares[tc] == 700001, \
        "largest fractional part .7 wins the single remainder cent"
    assert sum(shares.values()) == 1000001, "zero drift"
    assert get_territory(fx["root"]["id"])["assigned_quota_cents"] == 1000001


def test_allocation_results_ordered_by_child_creation(api):
    """PRD: "The run's `results` record one row per active child — the child's
    `territory_id` and its `allocated_cents` — ordered by child creation
    timestamp ascending, and the array is empty when the scope had no active
    children."

    Design: Difficulty/combinatorial_formula/allocation_largest_remainder_three_way
    """
    fx = setup_open_plan_with_children(potentials=(100, 200, 700),
                                       target=1000001, productivity=500000,
                                       label="FY27-ALLOC2")
    plan_id = fx["plan"]["id"]
    ta, tb, tc = (c["id"] for c in fx["children"])
    alloc = create_allocation(plan_id, fx["root"]["id"], 1000001)
    applied = apply_allocation(alloc["id"], plan_id)
    assert_allocation(applied)
    assert [row["territory_id"] for row in applied["results"]] == [ta, tb, tc]
    assert [row["allocated_cents"] for row in applied["results"]] == [
        100000, 200000, 700001]


def test_allocation_zero_weight_equal_split(api):
    """PRD: "When the total weight is zero and children exist, the pool is
    split equally instead: each child receives the floor of the pool divided by
    the child count, and the leftover cents go one each in child creation
    order."

    Pool 100000 over three zero-potential children lands 33334 on the
    earliest-created child and 33333 on the other two.

    Design: Corner/calculations/allocation_zero_weight_equal_split
    """
    fx = setup_open_plan_with_children(potentials=(0, 0, 0), target=100000,
                                       label="FY27-ZW")
    plan_id = fx["plan"]["id"]
    ta, tb, tc = (c["id"] for c in fx["children"])
    alloc = create_allocation(plan_id, fx["root"]["id"], 100000)
    apply_allocation(alloc["id"], plan_id)
    shares = [get_territory(tid)["assigned_quota_cents"]
              for tid in (ta, tb, tc)]
    assert shares == [33334, 33333, 33333]
    assert sum(shares) == 100000


def test_allocation_leaf_scope_lands_full_pool(api):
    """PRD: "When the scope has no active children at all, the scope retains
    the entire pool."
    PRD: "the array is empty when the scope had no active children."

    Design: Corner/calculations/allocation_leaf_scope_lands_full_pool
    """
    base = setup_open_plan(label="FY27-LEAF")
    plan_id = base["plan"]["id"]
    alloc = create_allocation(plan_id, base["t"]["id"], 100000)
    applied = apply_allocation(alloc["id"], plan_id)
    assert applied["status"] == "APPLIED"
    assert applied["results"] == []
    assert get_territory(base["t"]["id"])["assigned_quota_cents"] == 100000


def test_allocation_discard_terminal_lockdown(api):
    """PRD: "A draft run may instead be discarded while the plan is `OPEN`,
    moving it to `DISCARDED` with no quota changes at all."
    PRD: "Then the entity's own from-state is checked against the requested
    transition (`ERR_INVALID_STATE_TRANSITION`)"

    Applying a DISCARDED allocation is an invalid transition and writes no
    quota.

    Design: Corner/state_machines/allocation_discard_terminal_lockdown
    """
    base = setup_open_plan(label="FY27-DISC")
    plan_id = base["plan"]["id"]
    alloc = create_allocation(plan_id, base["t"]["id"], 100000)
    discarded = validate_success(api.discard_allocation(alloc["id"], ADMIN),
                                 200)
    assert discarded["status"] == "DISCARDED"
    validate_error(_apply(api, alloc["id"], plan_id, plan_version(plan_id)),
                   ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
    assert get_territory(base["t"]["id"])["assigned_quota_cents"] is None


def _setup_first_allocation_applied():
    """OPEN plan; root R with ACTIVE children A, B, C (potentials 100, 200,
    700); first allocation of pool 1000001 already applied on R."""
    fx = setup_open_plan_with_children(potentials=(100, 200, 700),
                                       target=1000001, productivity=500000,
                                       label="FY27-INV")
    al1 = create_allocation(fx["plan"]["id"], fx["root"]["id"], 1000001)
    al1 = apply_allocation(al1["id"], fx["plan"]["id"])
    fx["al1"] = al1
    return fx


def test_second_apply_supersedes_first(api):
    """PRD: "Applying a run supersedes its predecessor: any other allocation
    over the same `scope_territory_id` still in `APPLIED` status flips to
    `SUPERSEDED`, terminal."

    Design: Difficulty/compensating_invariant/allocation_pool_conservation_on_reapply
    """
    fx = _setup_first_allocation_applied()
    plan_id = fx["plan"]["id"]
    al2 = create_allocation(plan_id, fx["root"]["id"], 1000001)
    al2 = apply_allocation(al2["id"], plan_id)
    assert al2["status"] == "APPLIED"
    assert validate_success(
        api.get_allocation(fx["al1"]["id"], ADMIN), 200)["status"] == \
        "SUPERSEDED"


def test_children_quotas_conserved_across_reapply(api):
    """PRD: "In all cases the scope's own `assigned_quota_cents` becomes
    exactly the pool, each active child's `assigned_quota_cents` becomes its
    share, and the conservation invariant holds: the children's shares sum back
    to the pool with zero drift."

    After the superseding apply the children still sum to exactly 1000001
    (100000 + 200000 + 700001) — no double-count, no drift — and the scope
    retains exactly the pool.

    Design: Difficulty/compensating_invariant/allocation_pool_conservation_on_reapply
    """
    fx = _setup_first_allocation_applied()
    plan_id = fx["plan"]["id"]
    al2 = create_allocation(plan_id, fx["root"]["id"], 1000001)
    apply_allocation(al2["id"], plan_id)
    shares = [get_territory(c["id"])["assigned_quota_cents"]
              for c in fx["children"]]
    assert shares == [100000, 200000, 700001]
    assert sum(shares) == 1000001
    assert get_territory(fx["root"]["id"])["assigned_quota_cents"] == 1000001


def test_occ_allocation_apply_stale_version_rejected(api):
    """PRD: "Each of these requests must carry the field
    `expected_plan_year_version`, holding the plan version the client last
    observed; the field is non-optional on exactly these three operations. When
    the supplied value does not match the plan's current `version`, the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Stale apply is rejected 412 and the allocation stays DRAFT; the same call
    with the observed version applies and bumps the plan version by one.

    Design: Corner/cross_cutting_complexity_layers/occ_allocation_apply_stale_version_rejected
    """
    base = setup_open_plan(label="FY27-OCC")
    plan_id = base["plan"]["id"]
    alloc = create_allocation(plan_id, base["t"]["id"], 100000)
    pv = plan_version(plan_id)

    validate_error(_apply(api, alloc["id"], plan_id, pv - 1),
                   ApiErrorId.ERR_STALE_VERSION, 412)
    assert validate_success(api.get_allocation(alloc["id"], ADMIN),
                            200)["status"] == "DRAFT"

    applied = validate_success(_apply(api, alloc["id"], plan_id, pv), 200)
    assert applied["status"] == "APPLIED"
    assert get_plan(plan_id)["version"] == pv + 1


def test_allocation_create_requires_open_plan_rejected(api):
    """PRD: "Operations gated on an earlier phase — `DRAFT` or `OPEN`, or
    strictly `OPEN` for allocation writes — fail with `ERR_PLAN_NOT_OPEN` when
    the plan has advanced past the required phase without being locked."
    PRD: "With the plan `OPEN`, an administrator drafts a top-down allocation
    by naming the `plan_year_id`, the `scope_territory_id` whose pool is to be
    distributed, and a strictly positive `pool_cents`"

    Allocation drafting against a DRAFT (not LOCKED) plan is refused.

    Design: Corner/validations/allocation_create_requires_open_plan_rejected
    """
    plan = create_plan(label="FY27-NOOPEN")
    t = add_territory(plan["id"], name="T")
    activate_territory(t["id"])
    resp = api.create_allocation(
        {"plan_year_id": plan["id"], "scope_territory_id": t["id"],
         "pool_cents": 100000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_OPEN, 409)
