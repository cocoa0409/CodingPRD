"""Contractor delay claims: the float, the rate ceiling and the cause split."""
from test_helpers import (
    allocate_delay_claim,
    analyze_delay_claim,
    lodge_delay_claim,
    make_construction_engineer_headers,
    read_delay_claim,
    read_owner,
    read_project,
    validate_paginated,
    validate_success,
    world_commitment_breached,
)

WITHDRAWAL_REASON = "Cause re-opened after the contractor produced new float records."


def _breached_commitment(api):
    """A commitment reported eight days after its window closed."""
    world = world_commitment_breached(api)
    assert world["commitment"]["status"] == "BREACHED"
    assert world["commitment"]["late_days"] == 8
    return world


def test_withdrawing_the_allocation_restores_the_day_count_and_the_liability(api):
    """PRD 3.9: "Withdrawing an allocation is the compensating action: with a
    `withdrawal_reason`, the claim returns `ALLOCATED → UNDER_ANALYSIS`,
    `allocated_to_owner_cents` and `allocated_to_state_cents` are both reset to 0,
    and both conserved figures return to exactly their pre-allocation values."

    Design: Difficulty/compensating_invariant/withdraw_allocation_restores_compensable_delay_days_and_owner_liability
    """
    world = _breached_commitment(api)
    claim = lodge_delay_claim(
        api,
        world["commitment_id"],
        world["project_id"],
        contractor_name="Ridgeline Constructors",
        claimed_days=12,
        claimed_amount_cents=3_600_000,
    )
    analysed = analyze_delay_claim(api, claim["id"], "UTILITY_OWNER")
    assert analysed["status"] == "UNDER_ANALYSIS"
    assert analysed["compensable_days"] == 3
    assert analysed["daily_rate_cents"] == 250_000

    assert read_project(api, world["project_id"])["aggregate_compensable_delay_days"] == 0
    assert read_owner(api, world["owner_id"])["assessed_delay_liability_cents"] == 0

    allocated = allocate_delay_claim(api, claim["id"])
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_to_owner_cents"] == 750_000
    assert allocated["allocated_to_state_cents"] == 0
    assert read_project(api, world["project_id"])["aggregate_compensable_delay_days"] == 3
    assert read_owner(api, world["owner_id"])["assessed_delay_liability_cents"] == 750_000

    withdrawn = validate_success(
        api.withdraw_delay_allocation(
            claim["id"],
            {"withdrawal_reason": WITHDRAWAL_REASON},
            make_construction_engineer_headers(),
        )
    )
    assert withdrawn["status"] == "UNDER_ANALYSIS"
    assert withdrawn["allocated_to_owner_cents"] == 0
    assert withdrawn["allocated_to_state_cents"] == 0

    assert read_project(api, world["project_id"])["aggregate_compensable_delay_days"] == 0
    assert read_owner(api, world["owner_id"])["assessed_delay_liability_cents"] == 0

    survived = read_delay_claim(api, claim["id"])
    assert survived["compensable_days"] == 3
    assert survived["daily_rate_cents"] == 250_000
    assert survived["delay_cause"] == "UTILITY_OWNER"


def test_the_allocation_cycle_is_a_loop_that_recharges_the_same_liability(api):
    """PRD 3.9: "The claim can then be re-analysed and allocated again, which is why
    the allocation cycle `UNDER_ANALYSIS → ALLOCATED → UNDER_ANALYSIS` is a genuine
    loop rather than a one-way street."

    Design: Difficulty/compensating_invariant/withdraw_allocation_restores_compensable_delay_days_and_owner_liability
    """
    world = _breached_commitment(api)
    claim = lodge_delay_claim(
        api,
        world["commitment_id"],
        world["project_id"],
        contractor_name="Ridgeline Constructors",
        claimed_days=12,
        claimed_amount_cents=3_600_000,
    )
    analyze_delay_claim(api, claim["id"], "UTILITY_OWNER")
    allocate_delay_claim(api, claim["id"])
    validate_success(
        api.withdraw_delay_allocation(
            claim["id"],
            {"withdrawal_reason": WITHDRAWAL_REASON},
            make_construction_engineer_headers(),
        )
    )

    withdrawn = read_delay_claim(api, claim["id"])
    assert withdrawn["status"] == "UNDER_ANALYSIS"
    assert withdrawn["compensable_days"] == 3
    assert withdrawn["daily_rate_cents"] == 250_000

    reallocated = allocate_delay_claim(api, claim["id"])
    assert reallocated["status"] == "ALLOCATED"
    assert reallocated["allocated_to_owner_cents"] == 750_000
    assert reallocated["allocated_to_state_cents"] == 0
    assert (
        reallocated["allocated_to_owner_cents"] + reallocated["allocated_to_state_cents"]
        == 750_000
    )

    assert read_project(api, world["project_id"])["aggregate_compensable_delay_days"] == 3
    assert read_owner(api, world["owner_id"])["assessed_delay_liability_cents"] == 750_000


def test_the_float_nets_the_days_the_ceiling_caps_the_rate_and_the_cause_splits_it(api):
    """PRD 3.9: "`allocated_to_owner_cents` is the gross multiplied by that
    percentage divided by 100, rounded half up to whole cents, and
    `allocated_to_state_cents` is the gross minus `allocated_to_owner_cents` — a
    residual, so the two always sum to the gross exactly and the State's portion is
    never independently rounded."

    Design: Corner/calculations/delay_claim_allocation_nets_float_caps_the_rate_and_splits_by_cause
    """
    world = _breached_commitment(api)

    first = lodge_delay_claim(
        api,
        world["commitment_id"],
        world["project_id"],
        contractor_name="Granite Ridge Constructors",
        claimed_days=4,
        claimed_amount_cents=1_200_000,
    )
    analysed_first = analyze_delay_claim(api, first["id"], "UTILITY_OWNER")
    assert analysed_first["compensable_days"] == 3
    assert analysed_first["daily_rate_cents"] == 250_000
    allocated_first = allocate_delay_claim(api, first["id"])
    assert allocated_first["allocated_to_owner_cents"] == 750_000
    assert allocated_first["allocated_to_state_cents"] == 0

    second = lodge_delay_claim(
        api,
        world["commitment_id"],
        world["project_id"],
        contractor_name="Basalt Paving LLC",
        claimed_days=4,
        claimed_amount_cents=600_004,
    )
    analysed_second = analyze_delay_claim(api, second["id"], "THIRD_PARTY")
    assert analysed_second["compensable_days"] == 3
    assert analysed_second["daily_rate_cents"] == 150_001
    allocated_second = allocate_delay_claim(api, second["id"])
    assert allocated_second["allocated_to_owner_cents"] == 225_002
    assert allocated_second["allocated_to_state_cents"] == 225_001
    assert (
        allocated_second["allocated_to_owner_cents"]
        + allocated_second["allocated_to_state_cents"]
        == 450_003
    )

    assert read_project(api, world["project_id"])["aggregate_compensable_delay_days"] == 6
    assert read_owner(api, world["owner_id"])["assessed_delay_liability_cents"] == 975_002


def test_only_allocated_claims_reach_the_two_conserved_figures(api):
    """PRD 3.9: "The project's `aggregate_compensable_delay_days` is the sum of
    `compensable_days` across the project's claims whose `status` is `ALLOCATED`.
    The owner's `assessed_delay_liability_cents` is the sum of
    `allocated_to_owner_cents` across all claims in `ALLOCATED` whose commitment
    belongs to that owner. Claims in `SUBMITTED`, `UNDER_ANALYSIS` or `DENIED`
    contribute nothing to either figure."

    Design: Corner/calculations/aggregate_delay_counts_allocated_claims_and_ignores_analysed_and_denied_ones
    """
    world = _breached_commitment(api)
    engineer = make_construction_engineer_headers()

    allocated_claim = lodge_delay_claim(
        api,
        world["commitment_id"],
        world["project_id"],
        contractor_name="Granite Ridge Constructors",
        claimed_days=4,
        claimed_amount_cents=1_200_000,
    )
    analyze_delay_claim(api, allocated_claim["id"], "UTILITY_OWNER")
    allocate_delay_claim(api, allocated_claim["id"])

    analysed_claim = lodge_delay_claim(
        api,
        world["commitment_id"],
        world["project_id"],
        contractor_name="Basalt Paving LLC",
        claimed_days=4,
        claimed_amount_cents=1_200_000,
    )
    analysed = analyze_delay_claim(api, analysed_claim["id"], "UTILITY_OWNER")
    assert analysed["status"] == "UNDER_ANALYSIS"
    assert analysed["compensable_days"] == 3
    assert analysed["allocated_to_owner_cents"] == 0

    third_claim = lodge_delay_claim(
        api,
        world["commitment_id"],
        world["project_id"],
        contractor_name="Ridgeline Electrical",
        claimed_days=2,
        claimed_amount_cents=400_000,
    )

    denied = validate_success(
        api.deny_delay_claim(
            third_claim["id"],
            {"denial_reason": "Delay attributable to the contractor's own sequencing."},
            engineer,
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["compensable_days"] == 0
    assert denied["delay_cause"] is None

    assert read_project(api, world["project_id"])["aggregate_compensable_delay_days"] == 3
    assert read_owner(api, world["owner_id"])["assessed_delay_liability_cents"] == 750_000

    rows, meta = validate_paginated(
        api.list_delay_claims(
            engineer, {"project_id": world["project_id"], "status": "ALLOCATED"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == allocated_claim["id"]
