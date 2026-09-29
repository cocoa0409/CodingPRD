"""Unwinding writes that must put every aggregate back exactly where it started."""

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_fields

DEEP_WELL = dict(
    spud_year=1969,
    total_depth_ft=8000,
    casing_strings=3,
    methane_scfd=310,
    groundwater_depth_ft=180,
    population_within_1000ft=3,
    surface_disturbance_acres=1.25,
)
QUIET_SHALLOW_WELL = dict(
    spud_year=1981,
    total_depth_ft=2500,
    casing_strings=2,
    methane_scfd=50,
    groundwater_depth_ft=600,
    population_within_1000ft=1,
    surface_disturbance_acres=0.5,
)


def _job_funded_from_three_streams(api):
    """A 6070196 estimate split 1000000 / 1500000 / 3570196 across the waterfall."""
    operator = fx.make_unbonded_operator(
        api, name="Powder River Orphans", region_code="WY"
    )
    orphan = fx.make_confirmed_orphan_well(api, operator=operator)
    procurement = fx.make_active_contract(
        api, scope_description="single orphan well plugging"
    )
    job = fx.make_plugging_job(
        api,
        orphan["well"]["id"],
        procurement["contract"]["id"],
        scheduled_start="2026-09-01T00:00:00Z",
    )

    bond_source = fx.make_funding_source(
        api,
        kind="FORFEITED_BOND",
        name="Forfeited bond - Powder River Orphans",
        authorized_cents=1000000,
        expires_at="2027-12-31T00:00:00Z",
        bond_operator_id=operator["id"],
    )
    federal_source = fx.make_funding_source(
        api,
        kind="FEDERAL_GRANT",
        name="IIJA orphan well formula grant FY26",
        authorized_cents=10000000,
        expires_at="2027-06-30T00:00:00Z",
        federal_match_required_pct=40,
    )
    state_source = fx.make_funding_source(
        api,
        kind="STATE_FUND",
        name="Wyoming orphan well account",
        authorized_cents=10000000,
        expires_at="2027-12-31T00:00:00Z",
    )
    allocations = fx.commit_funding(api, job["id"])
    by_source = {row["source_id"]: row for row in allocations}
    return {
        "operator": operator,
        "job": job,
        "bond_source": bond_source,
        "federal_source": federal_source,
        "state_source": state_source,
        "bond_allocation": by_source[bond_source["id"]],
        "federal_allocation": by_source[federal_source["id"]],
        "state_allocation": by_source[state_source["id"]],
    }


def test_deobligating_the_first_allocation_restores_its_source_exactly(api):
    """The forfeited bond returns to a committed figure of exactly zero.

    Its 1000000 cents were fully committed, which had exhausted it; the deobligation
    puts the figure back to its pre-commitment value, reopens the source and lowers the
    job's funded total by exactly that amount without touching the other two streams.

    PRD: "It sets `status` to `DEOBLIGATED` and stamps `deobligated_at` from the logical
    clock." ... "and a source that had been sitting at `EXHAUSTED` transitions
    `EXHAUSTED → ACTIVE`."

    Design: Difficulty/compensating_invariant/deobligation_restores_funding_source_committed_cents_exactly
    """
    bundle = _job_funded_from_three_streams(api)
    bond_source_id = bundle["bond_source"]["id"]

    before = fx.read_source(api, bond_source_id)
    assert_cents(before["committed_cents"], 1000000, "committed_cents before")
    assert_fields(before, status="EXHAUSTED")

    deobligated = fx.transition_allocation(
        api, bundle["bond_allocation"]["id"], "DEOBLIGATE"
    )
    assert_fields(
        deobligated, status="DEOBLIGATED", deobligated_at="2026-08-01T00:00:00Z"
    )

    after = fx.read_source(api, bond_source_id)
    assert_cents(after["committed_cents"], 0, "committed_cents after")
    assert_cents(after["disbursed_cents"], 0, "disbursed_cents")
    assert_fields(after, status="ACTIVE")

    federal = fx.read_source(api, bundle["federal_source"]["id"])
    state = fx.read_source(api, bundle["state_source"]["id"])
    assert_cents(federal["committed_cents"], 1500000, "federal committed_cents")
    assert_cents(state["committed_cents"], 3570196, "state committed_cents")
    assert_fields(
        fx.read_allocation(api, bundle["federal_allocation"]["id"]), status="COMMITTED"
    )
    assert_fields(
        fx.read_allocation(api, bundle["state_allocation"]["id"]), status="COMMITTED"
    )

    assert_cents(
        fx.read_job(api, bundle["job"]["id"])["funded_cents"], 5070196, "funded_cents"
    )


def test_the_money_invariant_holds_before_and_after_the_deobligation(api):
    """Committed cents on the sources always equal the live allocations they back.

    The three sources hold 6070196 cents against three live allocations, and after the
    deobligation both sides read 5070196 - the returned cents leave the ledger on both
    sides of the identity at once.

    PRD: "Because the allocation leaves the committed-or-disbursed set, the source's
    `committed_cents` is recomputed and its available authority is restored exactly to
    its pre-commitment value; the job's `funded_cents` is recomputed and therefore falls
    by the deobligated `allocated_cents`"

    Design: Difficulty/compensating_invariant/deobligation_restores_funding_source_committed_cents_exactly
    """
    bundle = _job_funded_from_three_streams(api)
    source_ids = [
        bundle["bond_source"]["id"],
        bundle["federal_source"]["id"],
        bundle["state_source"]["id"],
    ]
    allocation_ids = [
        bundle["bond_allocation"]["id"],
        bundle["federal_allocation"]["id"],
        bundle["state_allocation"]["id"],
    ]

    def committed_total():
        return sum(fx.read_source(api, sid)["committed_cents"] for sid in source_ids)

    def live_allocation_total():
        rows = [fx.read_allocation(api, aid) for aid in allocation_ids]
        return sum(
            row["allocated_cents"] for row in rows if row["status"] != "DEOBLIGATED"
        )

    assert_cents(committed_total(), 6070196, "committed total before")
    assert_cents(live_allocation_total(), 6070196, "live allocation total before")

    fx.transition_allocation(api, bundle["bond_allocation"]["id"], "DEOBLIGATE")

    assert_cents(committed_total(), 5070196, "committed total after")
    assert_cents(live_allocation_total(), 5070196, "live allocation total after")


def _pending_transfer_of_the_deep_well(api):
    """A PENDING transfer that would move 1000000 cents of exposure from O1 to O2."""
    releasing = fx.make_operator(
        api,
        name="Uinta Basin Legacy",
        region_code="UT",
        bond_amount_cents=1250000,
    )
    receiving = fx.make_operator(
        api,
        name="Wasatch Acquisition Co",
        region_code="UT",
        bond_amount_cents=2000000,
    )
    shallow = fx.make_well(api, releasing["id"], **QUIET_SHALLOW_WELL)
    deep = fx.make_well(api, releasing["id"], **DEEP_WELL)
    other = fx.make_well(api, receiving["id"], **QUIET_SHALLOW_WELL)
    transfer = fx.transfer_well(api, deep["id"], receiving["id"])
    return {
        "releasing": releasing,
        "receiving": receiving,
        "shallow": shallow,
        "deep": deep,
        "other": other,
        "transfer": transfer,
    }


def test_approving_the_transfer_moves_capped_exposure_between_operators(api):
    """The deep well carries 1000000 cents of capped exposure with it.

    The forward-looking requirement was computed at proposal time under the receiving
    operator's own variant, and approval makes it real: the releasing operator drops to
    250000 and the receiving one rises to 1250000, with the well population conserved.

    PRD: "the well must not already be committed to closure, so its `status` must not be
    `PLUGGING_SCHEDULED`, `PLUGGED` or `RECLAIMED`; and the receiving operator's posted
    `bond_amount_cents` must be at least its `transferee_required_bond_cents`."

    Design: Difficulty/compensating_invariant/voiding_a_transfer_restores_both_operators_assurance_aggregates
    """
    bundle = _pending_transfer_of_the_deep_well(api)
    assert_fields(
        bundle["transfer"],
        status="PENDING",
        from_operator_id=bundle["releasing"]["id"],
        to_operator_id=bundle["receiving"]["id"],
    )
    assert_cents(
        bundle["transfer"]["transferee_required_bond_cents"],
        1250000,
        "transferee_required_bond_cents",
    )

    approved = fx.decide_transfer(
        api, bundle["transfer"]["id"], "APPROVE", "transferee assurance verified"
    )
    assert_fields(
        approved, status="APPROVED", approved_at="2026-08-01T00:00:00Z"
    )

    assert_fields(
        fx.read_well(api, bundle["deep"]["id"]), operator_id=bundle["receiving"]["id"]
    )
    releasing = fx.read_operator(api, bundle["releasing"]["id"])
    receiving = fx.read_operator(api, bundle["receiving"]["id"])
    assert_cents(releasing["required_bond_cents"], 250000, "releasing required_bond_cents")
    assert_cents(receiving["required_bond_cents"], 1250000, "receiving required_bond_cents")
    assert_fields(releasing, active_well_count=1, status="ACTIVE")
    assert_fields(receiving, active_well_count=2, status="ACTIVE")
    assert releasing["active_well_count"] + receiving["active_well_count"] == 3, (
        "the two operators must still hold three wells between them"
    )


def test_voiding_the_transfer_restores_both_operators_exactly(api):
    """The void is the precise compensating write of the approval.

    Both operators return to the requirement and the well count they had before the
    approval, the well goes back to its original operator, and the untouched wells never
    move at all.

    PRD: "both operators' `active_well_count`, `orphan_candidate_count` and
    `required_bond_cents` are recomputed so that the pre-approval values are restored
    exactly, and each may again flip between `ACTIVE` and `DELINQUENT`."

    Design: Difficulty/compensating_invariant/voiding_a_transfer_restores_both_operators_assurance_aggregates
    """
    bundle = _pending_transfer_of_the_deep_well(api)
    transfer_id = bundle["transfer"]["id"]

    fx.decide_transfer(api, transfer_id, "APPROVE", "transferee assurance verified")
    voided = fx.decide_transfer(
        api, transfer_id, "VOID", "title defect discovered in the assignment"
    )
    assert_fields(
        voided,
        status="VOIDED",
        voided_at="2026-08-01T00:00:00Z",
        void_reason="MANUAL_VOID",
    )

    assert_fields(
        fx.read_well(api, bundle["deep"]["id"]), operator_id=bundle["releasing"]["id"]
    )
    releasing = fx.read_operator(api, bundle["releasing"]["id"])
    receiving = fx.read_operator(api, bundle["receiving"]["id"])
    assert_cents(releasing["required_bond_cents"], 1250000, "releasing required_bond_cents")
    assert_cents(receiving["required_bond_cents"], 250000, "receiving required_bond_cents")
    assert_fields(releasing, active_well_count=2, status="ACTIVE")
    assert_fields(receiving, active_well_count=1, status="ACTIVE")
    assert releasing["active_well_count"] + receiving["active_well_count"] == 3, (
        "the two operators must still hold three wells between them"
    )

    assert_fields(
        fx.read_well(api, bundle["shallow"]["id"]), operator_id=bundle["releasing"]["id"]
    )
    assert_fields(
        fx.read_well(api, bundle["other"]["id"]), operator_id=bundle["receiving"]["id"]
    )
