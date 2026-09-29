"""Conserved quantities and the compensating actions that must restore them.

Exercises the three quantities the API conserves across a compensating pair
(PRD §2.10): the center's `aggregate_effective_rent_cents` across approving and
rescinding a reduction (PRD §3.5), its `total_gla_sqft` and
`protected_exclusive_count` across recording and abandoning a redevelopment
(PRD §3.9), and its occupied-area figures across going dark and reopening
(PRD §3.3).
"""
from test_helpers import (
    DEFAULT_CLOCK_UTC,
    abandon_plan,
    add_clause,
    add_condition,
    approve_election,
    assert_cents,
    assert_center_quantities,
    assert_lease_dimensions,
    assert_null,
    assert_pct,
    build_center_with_leases,
    elect_remedy,
    fetch_center,
    fetch_clause,
    fetch_condition,
    fetch_election,
    fetch_lease,
    fetch_plan,
    go_dark,
    plan_redevelopment,
    record_plan,
    reopen_lease,
    rescind_election,
)

# --------------------------------------------------------------------------
# Shared scenario construction (PRD §3.1)
# --------------------------------------------------------------------------
# A 300,000 sqft center whose five leases demise 255,000 sqft in total, so a
# fully open center reads 85.00 pct occupancy and 13,700,000 cents of aggregate
# effective rent (PRD §2.5, §3.5).
CENTER_TOTAL_GLA_SQFT = 300000
FULL_OCCUPIED_GLA_SQFT = 255000
FULL_OCCUPANCY_PCT = 85.00
FULL_AGGREGATE_RENT_CENTS = 13700000

LEASE_SPECS = (
    {
        "suite_code": "A1",
        "gla_sqft": 120000,
        "parcel_kind": "ANCHOR_BOX",
        "primary_use_code": "DISCOUNT_DEPT",
        "base_rent_monthly_cents": 6000000,
        "expiration_date": "2036-12-31",
        "tenant_legal_name": "Boxmart Retail Inc",
        "is_national_chain": True,
    },
    {
        "suite_code": "A2",
        "gla_sqft": 100000,
        "parcel_kind": "ANCHOR_BOX",
        "primary_use_code": "GROCERY",
        "base_rent_monthly_cents": 4000000,
        "expiration_date": "2036-12-31",
        "tenant_legal_name": "Grocerway Foods LLC",
        "is_national_chain": True,
    },
    {
        "suite_code": "I1",
        "gla_sqft": 2000,
        "parcel_kind": "INLINE",
        "primary_use_code": "COFFEE",
        "base_rent_monthly_cents": 1000000,
        "expiration_date": "2036-12-31",
        "tenant_legal_name": "Bean Theory Coffee LLC",
        "is_national_chain": False,
    },
    {
        "suite_code": "I2",
        "gla_sqft": 3000,
        "parcel_kind": "INLINE",
        "primary_use_code": "BOOKS",
        "base_rent_monthly_cents": 1200000,
        "expiration_date": "2036-12-31",
        "tenant_legal_name": "Margin Books LLC",
        "is_national_chain": False,
    },
    {
        "suite_code": "I3",
        "gla_sqft": 30000,
        "parcel_kind": "INLINE",
        "primary_use_code": "FITNESS",
        "base_rent_monthly_cents": 1500000,
        "expiration_date": "2036-12-31",
        "tenant_legal_name": "Pulse Fitness Group",
        "is_national_chain": True,
    },
)


def _build_leased_center(api):
    """Stand up the five-suite center with every store open (PRD §3.1, §3.3)."""
    return build_center_with_leases(
        api,
        [dict(spec) for spec in LEASE_SPECS],
        total_gla_sqft=CENTER_TOTAL_GLA_SQFT,
        occupancy_grace_days=30,
        center_name="Northgate Crossing",
        clock=DEFAULT_CLOCK_UTC,
    )


def _build_breach_by_dark_suite(api, required_occupancy_pct):
    """Abstract an ONGOING condition on I1, then send the 30,000 sqft suite dark.

    The condition is abstracted while every store is open, so it is created
    ``SATISFIED``; the dark suite then drops occupancy to 75.00 pct and the live
    strict engine flips it to ``BREACHED`` with a zero grace period, which makes
    the benefited lease ``ELIGIBLE`` in the same request (PRD §3.3).
    """
    scenario = _build_leased_center(api)
    condition = add_condition(
        api,
        scenario.lease_id("I1"),
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=required_occupancy_pct,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    go_dark(api, scenario.lease_id("I3"))
    scenario["condition"] = fetch_condition(api, condition["id"])
    return scenario


def _build_planned_redemise(api):
    """Three exclusive-use clauses, then a REDEMISE plan removing 45,000 sqft.

    Two clauses are ``CENTER_WIDE`` and one is ``PAD_EXCLUDED``, so the center
    carries a `protected_exclusive_count` of 3 and only the two center-wide
    clauses are impacted by the plan (PRD §3.2, §3.9).
    """
    scenario = _build_leased_center(api)
    scenario["clause_coffee"] = add_clause(
        api,
        scenario.lease_id("I1"),
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )
    scenario["clause_books"] = add_clause(
        api,
        scenario.lease_id("I2"),
        protected_use_codes=["BOOKS"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )
    scenario["clause_stationery"] = add_clause(
        api,
        scenario.lease_id("I2"),
        protected_use_codes=["STATIONERY"],
        exclusivity_scope="PAD_EXCLUDED",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=1500,
        incidental_sales_pct_cap=10.0,
    )
    scenario["plan"] = plan_redevelopment(
        api, scenario.center_id, plan_kind="REDEMISE", removed_gla_sqft=45000
    )
    return scenario


# --------------------------------------------------------------------------
# Aggregate rent: approving a reduction and rescinding it (PRD §2.10, §3.5)
# --------------------------------------------------------------------------
def test_election_floor_lifts_a_two_point_shortfall_to_five_percent(api):
    """A 2.00-point shortfall prices at the 5.00-point floor, capped at 25.00.

    PRD: "The result is raised to a minimum of 5.00 points, and the raised value is then lowered to a maximum of the condition's `max_reduction_pct`."

    Design: Difficulty/compensating_invariant/rescission_restores_aggregate_rent_and_zeroes_abatement_ledger
    """
    scenario = _build_breach_by_dark_suite(api, 77.0)
    lease_id = scenario.lease_id("I1")

    election = elect_remedy(
        api,
        lease_id,
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=scenario["condition"]["id"],
    )
    approve_election(api, election["id"])
    rescind_election(
        api, election["id"], rescission_reason_code="LANDLORD_BUYOUT"
    )

    # 77.00 required against 75.00 controlling occupancy is a 2.00-point
    # shortfall; tier 1 leaves it at 2.00, the floor raises it to 5.00 and the
    # 25.00 cap does not bite.  The pinned figures survive the rescission.
    election = fetch_election(api, election["id"])
    assert_pct(election["shortfall_pct_at_election"], 2.00, "shortfall_pct_at_election")
    assert_pct(election["reduction_pct"], 5.00, "reduction_pct")
    assert_cents(
        election["reduced_rent_monthly_cents"], 950000, "reduced_rent_monthly_cents"
    )
    assert election["status"] == "RESCINDED", election["status"]


def test_approving_the_reduction_drops_aggregate_rent_by_the_lease_delta(api):
    """Approval reduces the lease's rent to 950000 and the center's aggregate by exactly that delta.

    PRD: "The lease's `remedy_status` becomes `REMEDY_ACTIVE`, `effective_rent_monthly_cents` is recomputed sum-then-round, `total_abated_cents` is recomputed round-then-sum, the lease's `version` advances, and the center's `aggregate_effective_rent_cents` drops by exactly the lease delta."

    Design: Difficulty/compensating_invariant/rescission_restores_aggregate_rent_and_zeroes_abatement_ledger
    """
    scenario = _build_breach_by_dark_suite(api, 77.0)
    lease_id = scenario.lease_id("I1")
    pre_approval = fetch_center(api, scenario.center_id)
    assert_cents(
        pre_approval["aggregate_effective_rent_cents"],
        FULL_AGGREGATE_RENT_CENTS,
        "aggregate_effective_rent_cents",
    )

    election = elect_remedy(
        api,
        lease_id,
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=scenario["condition"]["id"],
    )
    approve_election(api, election["id"])

    # Sum-then-round on a single 5.00 pct reduction: 1000000 * 95 / 100.
    lease = fetch_lease(api, lease_id)
    assert_lease_dimensions(
        lease, remedy_status="REMEDY_ACTIVE", effective_rent_monthly_cents=950000
    )
    center = fetch_center(api, scenario.center_id)
    assert_cents(
        center["aggregate_effective_rent_cents"],
        pre_approval["aggregate_effective_rent_cents"] - 50000,
        "aggregate_effective_rent_cents",
    )
    assert_center_quantities(center, aggregate_effective_rent_cents=13650000)


def test_rescission_returns_aggregate_rent_to_its_pre_approval_value(api):
    """Rescinding the reduction restores aggregate rent exactly and zeroes the abatement ledger.

    PRD: "Rescinding an active reduction reverses the abatement retroactively and in full: `abated_to_date_cents` is reset to 0, `total_abated_cents` is recomputed from the remaining qualifying elections, `effective_rent_monthly_cents` is recomputed, and `aggregate_effective_rent_cents` returns to exactly its pre-approval value with zero drift."

    Design: Difficulty/compensating_invariant/rescission_restores_aggregate_rent_and_zeroes_abatement_ledger
    """
    scenario = _build_breach_by_dark_suite(api, 77.0)
    lease_id = scenario.lease_id("I1")
    pre_approval = fetch_center(api, scenario.center_id)

    election = elect_remedy(
        api,
        lease_id,
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=scenario["condition"]["id"],
    )
    approve_election(api, election["id"])
    rescind_election(
        api, election["id"], rescission_reason_code="LANDLORD_BUYOUT"
    )

    election = fetch_election(api, election["id"])
    assert election["status"] == "RESCINDED", election["status"]
    assert_cents(election["abated_to_date_cents"], 0, "abated_to_date_cents")

    # The reduction is reversed in full, so the lease pays base rent again.
    lease = fetch_lease(api, lease_id)
    assert_lease_dimensions(
        lease, effective_rent_monthly_cents=1000000, total_abated_cents=0
    )
    center = fetch_center(api, scenario.center_id)
    assert_cents(
        center["aggregate_effective_rent_cents"],
        pre_approval["aggregate_effective_rent_cents"],
        "aggregate_effective_rent_cents",
    )
    assert_center_quantities(
        center, aggregate_effective_rent_cents=FULL_AGGREGATE_RENT_CENTS
    )


def test_rescission_leaves_the_lease_eligible_while_the_condition_is_breached(api):
    """With no active reduction left and the condition still breached, the lease falls to ELIGIBLE.

    PRD: "The lease's `remedy_status` falls from `REMEDY_ACTIVE` to `ELIGIBLE` when no active reduction remains and at least one condition of the lease is still `BREACHED`, or to `NONE` when no breached condition remains."

    Design: Difficulty/compensating_invariant/rescission_restores_aggregate_rent_and_zeroes_abatement_ledger
    """
    scenario = _build_breach_by_dark_suite(api, 77.0)
    lease_id = scenario.lease_id("I1")

    election = elect_remedy(
        api,
        lease_id,
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=scenario["condition"]["id"],
    )
    approve_election(api, election["id"])
    rescind_election(
        api, election["id"], rescission_reason_code="LANDLORD_BUYOUT"
    )

    # The 30,000 sqft suite is still dark, so occupancy is still 75.00 pct
    # against the condition's 77.00 pct requirement.
    condition = fetch_condition(api, scenario["condition"]["id"])
    assert condition["status"] == "BREACHED", condition["status"]
    assert_lease_dimensions(fetch_lease(api, lease_id), remedy_status="ELIGIBLE")


# --------------------------------------------------------------------------
# Protected rights: recording a redevelopment and abandoning it (PRD §3.9)
# --------------------------------------------------------------------------
def test_planned_redemise_pins_the_post_plan_denominator(api):
    """Planning the redemise pins `gla_after_sqft` at 300000 minus the 45000 removed.

    PRD: "`gla_after_sqft` is the center's `total_gla_sqft` minus `removed_gla_sqft` at creation time."

    Design: Difficulty/compensating_invariant/abandoned_redevelopment_restores_gla_and_protected_clause_count
    """
    scenario = _build_planned_redemise(api)

    plan = fetch_plan(api, scenario["plan"]["id"])
    assert plan["removed_gla_sqft"] == 45000, plan["removed_gla_sqft"]
    assert plan["gla_after_sqft"] == 255000, plan["gla_after_sqft"]
    # Nothing moves at planning time: the denominator is still the full area.
    assert_center_quantities(
        fetch_center(api, scenario.center_id), total_gla_sqft=CENTER_TOTAL_GLA_SQFT
    )


def test_planned_redemise_counts_only_center_wide_clauses_as_impacted(api):
    """Only the two CENTER_WIDE clauses are impacted, and that makes consent required.

    PRD: "`impacted_clause_count` is the number of `ACTIVE` exclusive-use clauses on non-`TERMINATED` leases of the center whose `exclusivity_scope` is `CENTER_WIDE` or `RADIUS_INCLUSIVE` — a `PAD_EXCLUDED` clause is by construction not impacted by a pad sale."

    Design: Difficulty/compensating_invariant/abandoned_redevelopment_restores_gla_and_protected_clause_count
    """
    scenario = _build_planned_redemise(api)

    plan = fetch_plan(api, scenario["plan"]["id"])
    assert plan["impacted_clause_count"] == 2, plan["impacted_clause_count"]
    assert plan["consent_required"] is True, plan["consent_required"]
    # All three clauses are ACTIVE on non-terminated leases before recording.
    assert_center_quantities(
        fetch_center(api, scenario.center_id), protected_exclusive_count=3
    )


def test_recording_suspends_center_wide_clauses_and_shrinks_the_center(api):
    """Recording drops total area to 255000 and suspends both center-wide clauses.

    PRD: "When the plan required consent, every `ACTIVE` exclusive-use clause of the center whose `exclusivity_scope` is `CENTER_WIDE` becomes `SUSPENDED` with `suspended_by_plan_id` set to this plan's id, while `RADIUS_INCLUSIVE` clauses survive the pad sale untouched; `protected_exclusive_count` is recomputed, and a use that previously conflicted may now screen clear."

    Design: Difficulty/compensating_invariant/abandoned_redevelopment_restores_gla_and_protected_clause_count
    """
    scenario = _build_planned_redemise(api)
    plan_id = scenario["plan"]["id"]

    record_plan(api, plan_id, consent_confirmed=True)

    for key in ("clause_coffee", "clause_books"):
        clause = fetch_clause(api, scenario[key]["id"])
        assert clause["status"] == "SUSPENDED", (key, clause["status"])
        assert clause["suspended_by_plan_id"] == plan_id, clause["suspended_by_plan_id"]
    # The PAD_EXCLUDED clause is untouched, so one protection survives.
    stationery = fetch_clause(api, scenario["clause_stationery"]["id"])
    assert stationery["status"] == "ACTIVE", stationery["status"]
    assert_null(stationery["suspended_by_plan_id"], "suspended_by_plan_id")
    assert_center_quantities(
        fetch_center(api, scenario.center_id),
        total_gla_sqft=255000,
        protected_exclusive_count=1,
        redevelopment_status="RECORDED",
    )


def test_abandoning_restores_total_gla_and_protected_exclusive_count(api):
    """Abandoning the recorded plan restores the area, the occupancy and the clause cardinality exactly.

    PRD: "Abandoning a recorded plan adds `removed_gla_sqft` back to the center's `total_gla_sqft`, returns every clause whose `suspended_by_plan_id` names this plan to `ACTIVE` with `suspended_by_plan_id` cleared to null, restores `protected_exclusive_count` to exactly its pre-record cardinality, recomputes `open_occupancy_pct` against the restored denominator, re-evaluates every `ONGOING` condition of the center — which can re-breach a condition the recording had cured — and re-derives posture."

    Design: Difficulty/compensating_invariant/abandoned_redevelopment_restores_gla_and_protected_clause_count
    """
    scenario = _build_planned_redemise(api)
    plan_id = scenario["plan"]["id"]
    pre_record = fetch_center(api, scenario.center_id)

    record_plan(api, plan_id, consent_confirmed=True)
    abandon_plan(api, plan_id, abandon_reason_code="FINANCING_WITHDRAWN")

    center = fetch_center(api, scenario.center_id)
    assert center["total_gla_sqft"] == pre_record["total_gla_sqft"], (
        center["total_gla_sqft"],
        pre_record["total_gla_sqft"],
    )
    assert (
        center["protected_exclusive_count"] == pre_record["protected_exclusive_count"]
    ), (center["protected_exclusive_count"], pre_record["protected_exclusive_count"])
    assert_pct(
        center["open_occupancy_pct"],
        pre_record["open_occupancy_pct"],
        "open_occupancy_pct",
    )
    assert_center_quantities(
        center,
        total_gla_sqft=CENTER_TOTAL_GLA_SQFT,
        occupied_gla_sqft=FULL_OCCUPIED_GLA_SQFT,
        open_occupancy_pct=FULL_OCCUPANCY_PCT,
        protected_exclusive_count=3,
    )
    for key in ("clause_coffee", "clause_books", "clause_stationery"):
        clause = fetch_clause(api, scenario[key]["id"])
        assert clause["status"] == "ACTIVE", (key, clause["status"])
        assert_null(clause["suspended_by_plan_id"], "suspended_by_plan_id")


def test_abandoned_plan_returns_redevelopment_status_to_none(api):
    """With no other plan planned or recorded, the center's redevelopment status returns to NONE.

    PRD: "In every case the center's `redevelopment_status` returns to `NONE` once no other plan of that center is `RECORDED` or `PLANNED`."

    Design: Difficulty/compensating_invariant/abandoned_redevelopment_restores_gla_and_protected_clause_count
    """
    scenario = _build_planned_redemise(api)
    plan_id = scenario["plan"]["id"]

    record_plan(api, plan_id, consent_confirmed=True)
    abandon_plan(api, plan_id, abandon_reason_code="FINANCING_WITHDRAWN")

    plan = fetch_plan(api, plan_id)
    assert plan["status"] == "ABANDONED", plan["status"]
    assert_center_quantities(
        fetch_center(api, scenario.center_id), redevelopment_status="NONE"
    )


# --------------------------------------------------------------------------
# Occupied area: going dark and reopening (PRD §2.10, §3.3)
# --------------------------------------------------------------------------
def test_reopen_restores_occupied_area_and_counts_to_pre_dark_values(api):
    """Reopening the 30,000 sqft suite restores every occupancy figure with no drift.

    PRD: "`opened_at` is re-stamped, `dark_since` returns to null, and `occupied_gla_sqft`, `open_occupancy_pct`, `operating_store_count`, and `open_anchor_count` are restored to exactly their pre-dark values."

    Design: Difficulty/compensating_invariant/reopen_restores_occupied_area_and_cures_condition_without_drift
    """
    scenario = _build_breach_by_dark_suite(api, 81.67)
    pre_dark = scenario["center"]
    dark_lease_id = scenario.lease_id("I3")

    reopen_lease(api, dark_lease_id, as_tenant_id=scenario.tenant_id("I3"))

    lease = fetch_lease(api, dark_lease_id)
    assert_lease_dimensions(lease, premises_status="OPEN")
    assert_null(lease["dark_since"], "dark_since")

    center = fetch_center(api, scenario.center_id)
    for field in ("occupied_gla_sqft", "operating_store_count", "open_anchor_count"):
        assert center[field] == pre_dark[field], (field, center[field], pre_dark[field])
    assert_pct(
        center["open_occupancy_pct"], pre_dark["open_occupancy_pct"], "open_occupancy_pct"
    )
    assert_center_quantities(
        center,
        occupied_gla_sqft=FULL_OCCUPIED_GLA_SQFT,
        open_occupancy_pct=FULL_OCCUPANCY_PCT,
        operating_store_count=3,
        open_anchor_count=2,
    )


def test_reopen_cures_the_condition_and_clears_breach_detected_at(api):
    """The re-evaluated condition flips BREACHED to CURED with its breach stamp cleared.

    PRD: "Every `ONGOING` condition of the center is re-evaluated; conditions that now pass flip `BREACHED → CURED` with `breach_detected_at` cleared to null and `consecutive_breach_days` reset to 0."

    Design: Difficulty/compensating_invariant/reopen_restores_occupied_area_and_cures_condition_without_drift
    """
    scenario = _build_breach_by_dark_suite(api, 81.67)
    assert scenario["condition"]["status"] == "BREACHED", scenario["condition"]["status"]

    reopen_lease(api, scenario.lease_id("I3"), as_tenant_id=scenario.tenant_id("I3"))

    # 85.00 pct occupancy clears the 81.67 pct requirement again.
    condition = fetch_condition(api, scenario["condition"]["id"])
    assert condition["status"] == "CURED", condition["status"]
    assert_null(condition["breach_detected_at"], "breach_detected_at")
    assert condition["consecutive_breach_days"] == 0, condition["consecutive_breach_days"]


def test_reopen_returns_the_benefited_lease_to_remedy_status_none(api):
    """The benefited lease's only breach has cured, so it leaves remedy eligibility.

    PRD: "A benefited lease whose only breach has cured returns `remedy_status` from `ELIGIBLE` to `NONE` with `remedy_eligible_at` cleared, while a lease that already has an approved active reduction stays at `REMEDY_ACTIVE` until that election is rescinded or consummated."

    Design: Difficulty/compensating_invariant/reopen_restores_occupied_area_and_cures_condition_without_drift
    """
    scenario = _build_breach_by_dark_suite(api, 81.67)
    benefited_lease_id = scenario.lease_id("I1")
    assert_lease_dimensions(
        fetch_lease(api, benefited_lease_id), remedy_status="ELIGIBLE"
    )

    reopen_lease(api, scenario.lease_id("I3"), as_tenant_id=scenario.tenant_id("I3"))

    lease = fetch_lease(api, benefited_lease_id)
    assert_lease_dimensions(lease, remedy_status="NONE")
    assert_null(lease["remedy_eligible_at"], "remedy_eligible_at")


def test_reopen_restores_aggregate_rent_over_the_open_leases(api):
    """No election ever attached, so aggregate rent is the untouched sum of base rents.

    PRD: "The center's `aggregate_effective_rent_cents` is then the sum of `effective_rent_monthly_cents` over the leases of that center whose `premises_status` is `OPEN` or `DARK`."

    Design: Difficulty/compensating_invariant/reopen_restores_occupied_area_and_cures_condition_without_drift
    """
    scenario = _build_breach_by_dark_suite(api, 81.67)
    pre_dark = scenario["center"]

    reopen_lease(api, scenario.lease_id("I3"), as_tenant_id=scenario.tenant_id("I3"))

    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I1")),
        effective_rent_monthly_cents=1000000,
    )
    center = fetch_center(api, scenario.center_id)
    assert_cents(
        center["aggregate_effective_rent_cents"],
        pre_dark["aggregate_effective_rent_cents"],
        "aggregate_effective_rent_cents",
    )
    assert_center_quantities(
        center, aggregate_effective_rent_cents=FULL_AGGREGATE_RENT_CENTS
    )


def test_reopen_returns_the_center_to_compliant_posture(api):
    """With no breached condition, no open violation and 85.00 pct occupancy, posture is COMPLIANT.

    PRD: "Otherwise the posture is `WATCH` when `open_violation_count` is at least one, or when the center is assessable and its `open_occupancy_pct` is strictly below 70.00."

    Design: Difficulty/compensating_invariant/reopen_restores_occupied_area_and_cures_condition_without_drift
    """
    scenario = _build_breach_by_dark_suite(api, 81.67)

    reopen_lease(api, scenario.lease_id("I3"), as_tenant_id=scenario.tenant_id("I3"))

    assert_center_quantities(
        fetch_center(api, scenario.center_id),
        open_occupancy_pct=FULL_OCCUPANCY_PCT,
        open_violation_count=0,
        compliance_posture="COMPLIANT",
    )
