"""Common-element warranty: the structural window selector, the inclusive expiry, the
triage fork with its bounded reopen cycle, the closed remediation interval and the
dual-basis warrantability read.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_cents,
    assert_decimal_equals,
    assert_instant,
    assert_page,
)
from test_helpers.factories import (
    claim_payload,
    component_payload,
    remediation_payload,
)
from test_helpers.fixtures import (
    assign_agreement,
    build_registered_project,
    deliver_pos,
    evaluate_threshold,
    fund_escrow,
    harden,
    make_agreement,
    make_batch,
    make_claim,
    release_batch,
    schedule_remediation,
    set_clock,
    triage_claim,
)
from test_helpers.test_users import (
    engineer_headers,
    escrow_headers,
    lender_headers,
    sponsor_headers,
)

ROOF_NON_STRUCTURAL = component_payload(
    "ROOF", 30, 10, 10000000, 0, "EXCELLENT", 0, False, False
)
FOUNDATION_STRUCTURAL = component_payload(
    "FOUNDATION", 30, 10, 5000000, 0, "GOOD", 0, False, True
)


def test_warranty_window_length_selected_by_structural_flag(api):
    """PRD: The claim's `warranty_expires_at` is pinned at filing from the project's
    `warranty_start_at` — which equals `declaration_recorded_at` — plus a window
    selected entirely by the component's `is_structural` flag: 60 months for a
    structural component and 24 months for a non-structural one, each month being
    exactly 2592000 seconds.

    Design: Corner/calculations/warranty_window_length_selected_by_structural_flag
    """
    built = build_registered_project(
        api,
        "44 Cove Lane, Bangor ME",
        1968,
        unit_specs=(("101", 10000),),
        components=[ROOF_NON_STRUCTURAL, FOUNDATION_STRUCTURAL],
        annual_operating_expense_cents=1000000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
        total_unit_count=2,
        with_pos=False,
    )
    project_id = built["project"]["id"]
    roof, foundation = built["components"]

    project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_instant(project["warranty_start_at"], "2026-08-01T00:00:00Z")
    assert_decimal_equals(
        validate_success(
            api.get_assessment(built["assessment"]["id"], sponsor_headers())
        )["score"],
        "98.33",
        "score",
    )

    roof_claim = validate_success(
        api.create_claim(
            project_id,
            claim_payload(
                roof["id"],
                "roof membrane blistering",
                400000,
                built["units"][0]["id"],
            ),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert_instant(roof_claim["reported_at"], "2026-08-01T00:00:00Z")
    assert_instant(roof_claim["warranty_expires_at"], "2028-07-21T00:00:00Z")
    assert roof_claim["status"] == "SUBMITTED"
    assert_cents(roof_claim["accrued_charge_cents"], 0, "accrued_charge_cents")
    assert roof_claim["reopen_count"] == 0

    foundation_claim = validate_success(
        api.create_claim(
            project_id,
            claim_payload(
                foundation["id"],
                "foundation wall crack",
                400000,
                built["units"][0]["id"],
            ),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert_instant(foundation_claim["warranty_expires_at"], "2031-07-06T00:00:00Z")
    assert_instant(foundation_claim["reported_at"], "2026-08-01T00:00:00Z")

    final = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(
        final["warranty_reserve_charge_cents"], 0, "warranty_reserve_charge_cents"
    )


def test_warranty_claim_one_second_past_the_component_window_is_refused(api):
    """PRD: **The expiry comparison is inclusive**: a claim is admissible while the
    logical clock is at or before `warranty_expires_at`, and one instant past it the
    filing, triage or reopening is refused with `ERR_WARRANTY_PERIOD_EXPIRED` (409).

    Design: Corner/errors/warranty_claim_one_second_past_the_component_window_is_refused
    """
    built = build_registered_project(
        api,
        "44 Cove Lane, Bangor ME",
        1968,
        unit_specs=(("101", 5000), ("102", 5000)),
        components=[
            ROOF_NON_STRUCTURAL,
            component_payload("FOUNDATION", 50, 10, 8000000, 0, "EXCELLENT", 0, False, True),
        ],
        annual_operating_expense_cents=1000000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
        with_pos=False,
    )
    project_id = built["project"]["id"]
    roof, foundation = built["components"]

    assert_instant(
        validate_success(api.get_project(project_id, sponsor_headers()))[
        "warranty_start_at"
        ],
        "2026-08-01T00:00:00Z",
    )
    assert validate_success(api.get_component(roof["id"], sponsor_headers()))[
        "is_structural"
    ] is False
    assert validate_success(api.get_component(foundation["id"], sponsor_headers()))[
        "is_structural"
    ] is True

    # at the exact expiry instant the non-structural window is still open
    set_clock(api, "2028-07-21T00:00:00Z")
    admitted = validate_success(
        api.create_claim(
            project_id,
            claim_payload(
                roof["id"],
                "membrane blistering over unit 101",
                400000,
                built["units"][0]["id"],
            ),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert admitted["status"] == "SUBMITTED"
    assert_instant(admitted["warranty_expires_at"], "2028-07-21T00:00:00Z")
    assert_instant(admitted["reported_at"], "2028-07-21T00:00:00Z")
    assert_cents(admitted["accrued_charge_cents"], 0, "accrued_charge_cents")
    assert admitted["reopen_count"] == 0

    set_clock(api, "2028-07-21T00:00:01Z")
    validate_error(
        api.create_claim(
            project_id,
            claim_payload(
                roof["id"],
                "second membrane defect",
                400000,
                built["units"][0]["id"],
            ),
            sponsor_headers(),
        ),
        "ERR_WARRANTY_PERIOD_EXPIRED",
        expected_status=409,
    )

    # the structural window on the sibling component is untouched by that refusal
    structural = validate_success(
        api.create_claim(
            project_id,
            claim_payload(
                foundation["id"],
                "footing settlement crack",
                400000,
                built["units"][0]["id"],
            ),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert_instant(structural["warranty_expires_at"], "2031-07-06T00:00:00Z")
    assert structural["status"] == "SUBMITTED"

    _, meta = validate_paginated(api.list_project_claims(project_id, sponsor_headers()))
    assert_page(meta, total_count=2)


def test_warrantability_contract_basis_vs_closed_basis(api):
    """PRD: **The two verdicts are persisted separately and routinely disagree on the
    identical agreement book.**

    Design: Difficulty/dual_variant_calc/warrantability_contract_basis_vs_closed_basis
    """
    built = build_registered_project(
        api,
        "41 Kestrel Street, Providence RI",
        1968,
        unit_specs=(("U-1", 5000), ("U-2", 5000)),
        components=[
            component_payload(
                "FOUNDATION", 40, 20, 10000000, 5000, "EXCELLENT", 0, False, True
            )
        ],
        annual_operating_expense_cents=875000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
        section_word_count=200,
        body_ref_prefix="s3://pos/k",
    )
    project_id = built["project"]["id"]
    u1, u2 = built["units"]

    closed_agreement = make_agreement(
        api, u1["id"], "Alice Owner", "TAX-OO-1", "OWNER_OCCUPANT", 30000000, 3000000
    )
    deliver_pos(api, closed_agreement["id"])
    fund_escrow(api, closed_agreement["id"], 3000000)
    set_clock(api, "2026-08-16T00:00:00Z")
    harden(api, closed_agreement["id"])
    batch = make_batch(
        api,
        project_id,
        1,
        "2026-08-16T00:00:00Z",
        "2026-09-16T00:00:00Z",
        50.0,
        1,
    )
    assign_agreement(api, batch["id"], closed_agreement["id"])
    evaluate_threshold(api, batch["id"])
    release_batch(api, batch["id"])
    validate_success(api.close_agreement(closed_agreement["id"], escrow_headers()))

    signed_agreement = make_agreement(
        api, u2["id"], "Beta Holdings LLC", "TAX-INV-9", "INVESTOR", 28000000, 2800000
    )

    summary = validate_success(api.warrantability_summary(project_id, lender_headers()))
    project = validate_success(api.get_project(project_id, sponsor_headers()))
    for row in (summary, project):
        assert_decimal_equals(
            row["owner_occupancy_pct_contract_basis"], "50.00", "owner contract"
        )
        assert_decimal_equals(
            row["investor_concentration_pct_contract_basis"], "50.00", "investor contract"
        )
        assert_decimal_equals(
            row["owner_occupancy_pct_closed_basis"], "100.00", "owner closed"
        )
        assert_decimal_equals(
            row["investor_concentration_pct_closed_basis"], "0.00", "investor closed"
        )
        assert_decimal_equals(row["single_investor_max_pct"], "50.00", "single investor")
        assert_decimal_equals(row["presale_sold_pct"], "50.00", "presale_sold_pct")
        assert row["warrantability_verdict"] == "NON_WARRANTABLE"
        assert row["warrantability_verdict_closed_basis"] == "NON_WARRANTABLE"

    first = validate_success(api.get_agreement(closed_agreement["id"], sponsor_headers()))
    assert first["contract_status"] == "CLOSED"
    assert first["escrow_status"] == "DISBURSED"
    second = validate_success(
        api.get_agreement(signed_agreement["id"], sponsor_headers())
    )
    assert second["contract_status"] == "SIGNED"
    assert second["escrow_status"] == "PENDING"

    assert validate_success(api.get_unit(u1["id"], sponsor_headers()))[
        "sale_status"
    ] == "SOLD"
    assert validate_success(api.get_unit(u2["id"], sponsor_headers()))[
        "sale_status"
    ] == "UNDER_CONTRACT"

    assert_cents(project["escrow_deposits_received_cents"], 3000000, "received")
    assert_cents(project["escrow_disbursed_cents"], 3000000, "disbursed")
    assert_cents(project["escrow_balance_cents"], 0, "balance")
    assert_cents(project["escrow_reconciliation_delta_cents"], 0, "delta")
    assert project["status"] == "CLOSINGS"

    end_batch = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert end_batch["status"] == "RELEASED"
    assert_decimal_equals(end_batch["presale_pct"], "50.00", "batch presale_pct")


def test_warranty_claim_triage_fork_and_bounded_reopen_cycle(api):
    """PRD: Reopening requires the clock to be at or before `warranty_expires_at` and
    requires `reopen_count` to be **strictly below** 2, so the third reopening is
    refused with `ERR_CLAIM_REOPEN_LIMIT_REACHED` (409) — a claim may be reopened twice
    and no more.

    Design: Difficulty/non_linear_state_machine/warranty_claim_triage_fork_and_bounded_reopen_cycle
    """
    built = build_registered_project(
        api,
        "9 Tannery Wharf, Salem MA",
        1971,
        unit_specs=(("T-1", 5000), ("T-2", 5000)),
        components=[
            component_payload(
                "FOUNDATION", 40, 20, 10000000, 5000, "EXCELLENT", 0, False, True
            )
        ],
        annual_operating_expense_cents=875000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
        max_overlapping_remediations=2,
        section_word_count=210,
        body_ref_prefix="s3://pos/t",
    )
    project_id = built["project"]["id"]
    u1, u2 = built["units"]
    foundation = built["components"][0]

    agreement = make_agreement(
        api, u1["id"], "Dana Owner", "TAX-OO-7", "OWNER_OCCUPANT", 26000000, 2600000
    )
    deliver_pos(api, agreement["id"])
    fund_escrow(api, agreement["id"], 2600000)
    set_clock(api, "2026-08-16T00:00:00Z")
    harden(api, agreement["id"])
    batch = make_batch(
        api, project_id, 1, "2026-08-16T00:00:00Z", "2026-09-16T00:00:00Z", 50.0, 1
    )
    assign_agreement(api, batch["id"], agreement["id"])
    evaluate_threshold(api, batch["id"])
    release_batch(api, batch["id"])
    validate_success(api.close_agreement(agreement["id"], escrow_headers()))
    assert validate_success(api.get_unit(u1["id"], sponsor_headers()))[
        "sale_status"
    ] == "SOLD"
    assert validate_success(api.get_unit(u2["id"], sponsor_headers()))[
        "sale_status"
    ] == "UNSOLD"

    denied_claim = make_claim(
        api,
        project_id,
        foundation["id"],
        "hairline crack in garage slab, cosmetic",
        2000000,
        u1["id"],
    )
    admitted_claim = make_claim(
        api,
        project_id,
        foundation["id"],
        "differential settlement at the north footing",
        4000000,
        u1["id"],
    )
    assert validate_success(api.get_project(project_id, sponsor_headers()))[
        "warranty_reserve_charge_cents"
    ] == 0

    # the DENY branch accrues nothing and never touches the project's ledger
    denied = validate_success(
        api.triage_claim(
            denied_claim["id"],
            {"decision": "DENY", "triage_note": "cosmetic, outside the structural warranty"},
            engineer_headers(),
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["triage_outcome"] == "DENIED"
    assert_cents(denied["accrued_charge_cents"], 0, "denied accrued_charge_cents")
    assert_instant(denied["warranty_expires_at"], "2031-07-06T00:00:00Z")
    assert_cents(
        validate_success(api.get_project(project_id, sponsor_headers()))[
            "warranty_reserve_charge_cents"
        ],
        0,
        "warranty_reserve_charge_cents",
    )

    # the ADMIT branch accrues min(claimed, 60% of replacement cost)
    admitted = validate_success(
        api.triage_claim(
            admitted_claim["id"],
            {"decision": "ADMIT", "triage_note": "settlement confirmed by level survey"},
            engineer_headers(),
        )
    )
    assert admitted["status"] == "TRIAGED_ADMISSIBLE"
    assert admitted["triage_outcome"] == "ADMISSIBLE"
    assert_cents(admitted["accrued_charge_cents"], 4000000, "accrued_charge_cents")
    assert_cents(
        validate_success(api.get_project(project_id, sponsor_headers()))[
            "warranty_reserve_charge_cents"
        ],
        4000000,
        "warranty_reserve_charge_cents",
    )

    schedule_remediation(
        api, admitted_claim["id"], "2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z"
    )
    set_clock(api, "2026-09-04T00:00:00Z")
    validate_success(
        api.complete_claim(
            admitted_claim["id"], sponsor_headers(), {"completion_note": "underpinning poured"}
        )
    )
    reopened = validate_success(
        api.reopen_claim(
            admitted_claim["id"],
            sponsor_headers(),
            {"reopen_reason": "settlement recurred after cure"},
        )
    )
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened["remediation_start_at"] is None
    assert reopened["remediation_end_at"] is None

    # cycle 1: the uplift is applied before the cap
    cycle_one = validate_success(
        api.triage_claim(
            admitted_claim["id"],
            {"decision": "ADMIT", "triage_note": "recurrence admitted, cycle 1"},
            engineer_headers(),
        )
    )
    assert cycle_one["status"] == "TRIAGED_ADMISSIBLE"
    assert_cents(cycle_one["accrued_charge_cents"], 5000000, "accrued_charge_cents")
    assert_cents(
        validate_success(api.get_project(project_id, sponsor_headers()))[
            "warranty_reserve_charge_cents"
        ],
        5000000,
        "warranty_reserve_charge_cents",
    )

    schedule_remediation(
        api, admitted_claim["id"], "2026-09-10T00:00:00Z", "2026-09-12T00:00:00Z"
    )
    set_clock(api, "2026-09-13T00:00:00Z")
    validate_success(
        api.complete_claim(
            admitted_claim["id"],
            sponsor_headers(),
            {"completion_note": "second cure complete"},
        )
    )
    second_reopen = validate_success(
        api.reopen_claim(
            admitted_claim["id"],
            sponsor_headers(),
            {"reopen_reason": "settlement recurred a second time"},
        )
    )
    assert second_reopen["reopen_count"] == 2

    # cycle 2: 5000000 + uplift 1250000 clamps to the 6000000 cap, so the ledger
    # delta is 1000000 rather than 1250000
    cycle_two = validate_success(
        api.triage_claim(
            admitted_claim["id"],
            {"decision": "ADMIT", "triage_note": "recurrence admitted, cycle 2"},
            engineer_headers(),
        )
    )
    assert_cents(cycle_two["accrued_charge_cents"], 6000000, "accrued_charge_cents")
    assert_cents(
        validate_success(api.get_project(project_id, sponsor_headers()))[
            "warranty_reserve_charge_cents"
        ],
        6000000,
        "warranty_reserve_charge_cents",
    )

    schedule_remediation(
        api, admitted_claim["id"], "2026-09-20T00:00:00Z", "2026-09-22T00:00:00Z"
    )
    set_clock(api, "2026-09-23T00:00:00Z")
    validate_success(
        api.complete_claim(
            admitted_claim["id"],
            sponsor_headers(),
            {"completion_note": "third cure complete"},
        )
    )
    validate_error(
        api.reopen_claim(
            admitted_claim["id"], sponsor_headers(), {"reopen_reason": "third recurrence"}
        ),
        "ERR_CLAIM_REOPEN_LIMIT_REACHED",
        expected_status=409,
    )

    final = validate_success(api.get_claim(admitted_claim["id"], sponsor_headers()))
    assert final["status"] == "REMEDIATED"
    assert final["reopen_count"] == 2
    assert_instant(final["remediation_start_at"], "2026-09-20T00:00:00Z")
    assert_instant(final["remediation_end_at"], "2026-09-22T00:00:00Z")


def test_remediation_closed_interval_cooldown_and_depth_cap(api):
    """PRD: Both comparisons are inclusive, so touching endpoints collide — a window
    beginning at the exact instant another ends is a collision, not adjacency — and a
    gap of exactly 259200 seconds **still collides**. The earliest admissible start on
    the same component is the existing end plus 259200 seconds plus one second.

    Design: Difficulty/resource_temporal_overlap/remediation_closed_interval_cooldown_and_depth_cap
    """
    built = build_registered_project(
        api,
        "27 Joist Street, Somerville MA",
        1955,
        unit_specs=(("J-1", 5000), ("J-2", 5000)),
        components=[
            component_payload(
                "FOUNDATION", 40, 20, 10000000, 5000, "EXCELLENT", 0, False, True
            ),
            component_payload("ROOF", 20, 10, 4000000, 5000, "GOOD", 0, False, False),
        ],
        annual_operating_expense_cents=875000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
        max_overlapping_remediations=1,
        body_ref_prefix="s3://pos/j",
    )
    project_id = built["project"]["id"]
    unit = built["units"][0]
    foundation, roof = built["components"]

    # the admitting triage requires an actual owner, so J-1 is taken to SOLD
    agreement = make_agreement(
        api, unit["id"], "Joel Owner", "TAX-OO-J", "OWNER_OCCUPANT", 26000000, 2600000
    )
    deliver_pos(api, agreement["id"])
    fund_escrow(api, agreement["id"], 2600000)
    set_clock(api, "2026-08-16T00:00:00Z")
    harden(api, agreement["id"])
    batch = make_batch(
        api, project_id, 1, "2026-08-16T00:00:00Z", "2026-09-16T00:00:00Z", 50.0, 1
    )
    assign_agreement(api, batch["id"], agreement["id"])
    evaluate_threshold(api, batch["id"])
    release_batch(api, batch["id"])
    validate_success(api.close_agreement(agreement["id"], escrow_headers()))
    assert validate_success(api.get_unit(unit["id"], sponsor_headers()))[
        "sale_status"
    ] == "SOLD"

    claim_one = make_claim(
        api,
        project_id,
        foundation["id"],
        "footing settlement at the north bay",
        4000000,
        unit["id"],
    )
    triage_claim(api, claim_one["id"], "ADMIT", "settlement confirmed by level survey")
    scheduled = schedule_remediation(
        api, claim_one["id"], "2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z"
    )
    assert scheduled["status"] == "REMEDIATION_SCHEDULED"

    claim_two = make_claim(
        api,
        project_id,
        foundation["id"],
        "second footing crack at the south bay",
        1000000,
        unit["id"],
    )
    triage_claim(api, claim_two["id"], "ADMIT", "separate defect on the same footing")
    claim_three = make_claim(
        api,
        project_id,
        roof["id"],
        "membrane seam failure over the stairwell",
        500000,
        unit["id"],
    )
    triage_claim(
        api, claim_three["id"], "ADMIT", "seam failure is a covered common-element defect"
    )
    before_two = validate_success(api.get_claim(claim_two["id"], sponsor_headers()))
    assert before_two["status"] == "TRIAGED_ADMISSIBLE"
    assert before_two["remediation_start_at"] is None

    # probe 1: a gap of exactly the 259200-second cooldown still collides
    validate_error(
        api.schedule_remediation(
            claim_two["id"],
            remediation_payload("2026-09-06T00:00:00Z", "2026-09-08T00:00:00Z"),
            sponsor_headers(),
        ),
        "ERR_REMEDIATION_WINDOW_OVERLAP",
        expected_status=409,
    )
    refused = validate_success(api.get_claim(claim_two["id"], sponsor_headers()))
    assert refused["status"] == "TRIAGED_ADMISSIBLE"
    assert refused["remediation_start_at"] is None
    assert refused["version"] == before_two["version"]

    # probe 2: one second later is the first admissible start
    second = validate_success(
        api.schedule_remediation(
            claim_two["id"],
            remediation_payload("2026-09-06T00:00:01Z", "2026-09-08T00:00:01Z"),
            sponsor_headers(),
        )
    )
    assert second["status"] == "REMEDIATION_SCHEDULED"
    assert_instant(second["remediation_start_at"], "2026-09-06T00:00:01Z")
    assert_instant(second["remediation_end_at"], "2026-09-08T00:00:01Z")

    # probe 3: a different component, so the aggregate depth test is what fires
    validate_error(
        api.schedule_remediation(
            claim_three["id"],
            remediation_payload("2026-09-02T00:00:00Z", "2026-09-02T12:00:00Z"),
            sponsor_headers(),
        ),
        "ERR_REMEDIATION_CAPACITY_EXCEEDED",
        expected_status=409,
    )

    # probe 4: the closed aggregate interval counts the shared endpoint instant twice
    validate_error(
        api.schedule_remediation(
            claim_three["id"],
            remediation_payload("2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z"),
            sponsor_headers(),
        ),
        "ERR_REMEDIATION_CAPACITY_EXCEEDED",
        expected_status=409,
    )

    # probe 5: clear of every occupied window, and no cross-component cooldown exists
    third = validate_success(
        api.schedule_remediation(
            claim_three["id"],
            remediation_payload("2026-09-11T00:00:00Z", "2026-09-12T00:00:00Z"),
            sponsor_headers(),
        )
    )
    assert third["status"] == "REMEDIATION_SCHEDULED"
    assert_instant(third["remediation_start_at"], "2026-09-11T00:00:00Z")

    first = validate_success(api.get_claim(claim_one["id"], sponsor_headers()))
    assert_instant(first["remediation_start_at"], "2026-09-01T00:00:00Z")
    assert_cents(first["accrued_charge_cents"], 4000000, "claim one charge")
    assert_cents(second["accrued_charge_cents"], 1000000, "claim two charge")
    assert_cents(third["accrued_charge_cents"], 500000, "claim three charge")
    for row in (first, second, third):
        assert row["reopen_count"] == 0
        assert row["status"] == "REMEDIATION_SCHEDULED"

    project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(
        project["warranty_reserve_charge_cents"], 5500000, "warranty_reserve_charge_cents"
    )
    assert project["max_overlapping_remediations"] == 1
    _, meta = validate_paginated(api.list_project_claims(project_id, sponsor_headers()))
    assert_page(meta, total_count=3)
