"""The forward liability estimate, the committed ledger and the posture cascade."""
from test_helpers import (
    CANCELLATION_REASON,
    CANON_BETTERMENT_AMOUNT_CENTS,
    CANON_BETTERMENT_RATIO,
    CANON_COMMITMENT_DAYS,
    CANON_ESTIMATE_STATE_SHARE_CENTS,
    CANON_STATE_LIABILITY_CENTS,
    OFFICER_USER_ID,
    VOID_REASON,
    approve_plan,
    assert_settlement_figures,
    assert_version_advanced_by,
    cancel_commitment,
    certify_cleared,
    circulate_agreement,
    commit_window,
    draft_agreement,
    draft_determination,
    grant_permit,
    identify_conflict,
    issue_determination,
    make_agreement_officer_headers,
    read_clearance_summary,
    read_commitment,
    read_conflict,
    read_owner,
    read_plan,
    read_project,
    register_facility,
    register_owner,
    register_project,
    revise_project,
    select_resolution,
    set_clock,
    submit_plan,
    validate_success,
    void_agreement,
    world_plan_approved,
)

PERMIT_FIBER_FACILITY = {
    "facility_type": "FIBER_CONDUIT",
    "station_begin": 500.0,
    "station_end": 520.0,
    "offset_ft": 8.0,
    "depth_in": 30,
    "material": "HDPE conduit",
    "installed_year": 1992,
    "occupancy_basis": "PERMIT",
    "record_source": "OWNER_ATLAS",
}

SECOND_DUCT_BANK = {
    "facility_type": "BURIED_ELECTRIC",
    "station_begin": 300.0,
    "station_end": 340.0,
    "offset_ft": 11.0,
    "depth_in": 44,
    "material": "PVC duct bank",
    "installed_year": 1968,
    "occupancy_basis": "PRIVATE_EASEMENT",
    "record_source": "AS_BUILT",
}

REVISED_PLAN = {
    "estimated_cost_cents": 39_000_000,
    "replacement_in_kind_cost_cents": 32_000_000,
    "proposed_capacity_ratio": 1.20,
    "work_days": 10,
}


def _plan_awaiting_its_share(api, *, authority_cents=1_000_000):
    """A submitted plan on a conflict whose determination is still under review."""
    project = register_project(api, name="SR-14 Spot Improvement",
                              reimbursement_authority_cents=authority_cents)
    owner = register_owner(api)
    facility = register_facility(api, owner["id"])
    conflict = identify_conflict(api, project["id"], facility["id"])
    select_resolution(api, conflict["id"], "RELOCATE")
    plan = submit_plan(api, conflict["id"])
    determination = draft_determination(api, conflict["id"])
    return {
        "project_id": project["id"],
        "owner_id": owner["id"],
        "facility_id": facility["id"],
        "conflict_id": conflict["id"],
        "plan": plan,
        "plan_id": plan["id"],
        "determination_id": determination["id"],
    }


def test_issuing_the_share_lifts_the_liability_over_the_authority_and_blocks_funding(api):
    """PRD 3.4: "Then the cascade fires: the conflict's `state_share_pct` is set to
    `final_state_share_pct` and the conflict advances `RESOLUTION_SELECTED →
    RESPONSIBILITY_SET`; the project's `estimated_state_liability_cents` is
    recomputed; the project's `clearance_posture` is recomputed and becomes
    `FUNDING_BLOCKED` when the new estimate exceeds `reimbursement_authority_cents`."

    Design: Difficulty/transitive_cascade/issuing_prior_rights_cascades_conflict_share_to_project_liability_to_funding_block
    """
    world = _plan_awaiting_its_share(api)
    before = read_project(api, world["project_id"])
    assert before["estimated_state_liability_cents"] == 0
    assert before["clearance_posture"] == "CLEARANCE_PENDING"

    issued = issue_determination(api, world["determination_id"])
    assert issued["status"] == "ISSUED"
    assert issued["final_state_share_pct"] == 100

    conflict = read_conflict(api, world["conflict_id"])
    assert conflict["state_share_pct"] == 100
    assert conflict["status"] == "RESPONSIBILITY_SET"

    project = read_project(api, world["project_id"])
    assert project["estimated_state_liability_cents"] == CANON_STATE_LIABILITY_CENTS
    assert project["clearance_posture"] == "FUNDING_BLOCKED"
    assert project["total_committed_reimbursement_cents"] == 0
    assert project["status"] == "CLEARANCE_ACTIVE"

    assert read_plan(api, world["plan_id"])["betterment_amount_cents"] == (
        CANON_BETTERMENT_AMOUNT_CENTS
    )


def test_the_liability_estimate_counts_the_conflict_at_a_zero_share_until_issuance(api):
    """PRD 3.5: "Plans still in `SUBMITTED`, `UNDER_REVIEW` or `REVISION_REQUESTED`
    count exactly like `APPROVED` ones, because the estimate is forward-looking and
    pending scope is still scope; and a conflict whose determination has not been
    issued still participates, at a `state_share_pct` that is 0 until issuance."

    Design: Difficulty/transitive_cascade/issuing_prior_rights_cascades_conflict_share_to_project_liability_to_funding_block
    """
    world = _plan_awaiting_its_share(api)
    assert world["plan"]["status"] == "SUBMITTED"
    assert world["plan"]["betterment_ratio"] == CANON_BETTERMENT_RATIO
    assert read_conflict(api, world["conflict_id"])["state_share_pct"] is None

    before = read_clearance_summary(api, world["project_id"])
    assert before["estimated_state_liability_cents"] == 0
    assert before["clearance_posture"] == "CLEARANCE_PENDING"
    assert before["open_conflict_count"] == 1
    assert before["untriaged_conflict_count"] == 0
    assert before["remaining_authority_cents"] == 1_000_000

    issue_determination(api, world["determination_id"])

    after = read_clearance_summary(api, world["project_id"])
    assert after["estimated_state_liability_cents"] == CANON_STATE_LIABILITY_CENTS
    assert after["clearance_posture"] == "FUNDING_BLOCKED"
    assert after["total_committed_reimbursement_cents"] == 0
    assert after["reimbursement_authority_cents"] == 1_000_000
    assert after["remaining_authority_cents"] == 1_000_000


def test_the_liability_reads_the_governing_plan_and_drops_the_cleared_conflict(api):
    """PRD 3.5: "Only conflicts whose `status` is not `CLEARED` are considered. For
    each such conflict the *governing plan* is the plan of that conflict with the
    greatest `created_at` among those whose `status` is not `SUPERSEDED`; a conflict
    has at most one, and a conflict with none contributes 0."

    Design: Corner/calculations/state_liability_uses_the_governing_plan_and_drops_cleared_conflicts
    """
    project = register_project(api)
    owner = register_owner(api)
    facility_a = register_facility(api, owner["id"])
    facility_b = register_facility(api, owner["id"], **SECOND_DUCT_BANK)
    facility_c = register_facility(api, owner["id"], **PERMIT_FIBER_FACILITY)

    protected = identify_conflict(
        api, project["id"], facility_a["id"], clearance_deficiency_in=4
    )
    select_resolution(api, protected["id"], "PROTECT_IN_PLACE")
    cleared = certify_cleared(api, protected["id"], "Concrete encasement in place.")
    assert cleared["status"] == "CLEARED"
    assert cleared["state_share_pct"] is None

    relocating = identify_conflict(
        api,
        project["id"],
        facility_b["id"],
        conflict_station=320.0,
        clearance_deficiency_in=18,
    )
    select_resolution(api, relocating["id"], "RELOCATE")
    determination = draft_determination(api, relocating["id"])
    issue_determination(api, determination["id"])
    superseded_plan = submit_plan(api, relocating["id"])
    governing_plan = submit_plan(api, relocating["id"], **REVISED_PLAN)

    untriaged = identify_conflict(
        api,
        project["id"],
        facility_c["id"],
        conflict_station=510.0,
        clearance_deficiency_in=9,
    )
    assert untriaged["status"] == "IDENTIFIED"
    assert untriaged["state_share_pct"] is None

    assert read_plan(api, superseded_plan["id"])["status"] == "SUPERSEDED"
    assert read_plan(api, governing_plan["id"])["status"] == "SUBMITTED"

    summary = read_clearance_summary(api, project["id"])
    assert summary["estimated_state_liability_cents"] == 26_666_679
    assert summary["estimated_state_liability_cents"] != CANON_STATE_LIABILITY_CENTS
    assert summary["open_conflict_count"] == 2
    assert summary["untriaged_conflict_count"] == 1
    assert summary["total_committed_reimbursement_cents"] == 0
    assert summary["remaining_authority_cents"] == 100_000_000
    assert summary["clearance_posture"] == "AT_RISK"


def test_the_funding_rule_masks_the_untriaged_conflict_until_authority_is_raised(api):
    """PRD 2.11: "The four rules are an ordered cascade, and **the first rule that
    matches sets the posture**; later rules are not consulted. This ordering is why a
    funding breach masks an untriaged conflict, and why an imminent relocation window
    masks ordinary pending clearance work."

    Design: Corner/calculations/clearance_posture_rule_one_masks_rule_two_until_authority_is_raised
    """
    project = register_project(api, reimbursement_authority_cents=1_000_000)
    owner = register_owner(api)
    facility_a = register_facility(api, owner["id"])
    facility_b = register_facility(api, owner["id"], **PERMIT_FIBER_FACILITY)

    conflict = identify_conflict(api, project["id"], facility_a["id"])
    select_resolution(api, conflict["id"], "RELOCATE")
    determination = draft_determination(api, conflict["id"])
    issue_determination(api, determination["id"])
    identify_conflict(
        api,
        project["id"],
        facility_b["id"],
        conflict_station=510.0,
        clearance_deficiency_in=9,
    )
    submit_plan(api, conflict["id"])

    blocked = read_clearance_summary(api, project["id"])
    assert blocked["estimated_state_liability_cents"] == CANON_STATE_LIABILITY_CENTS
    assert blocked["untriaged_conflict_count"] == 1
    assert blocked["clearance_posture"] == "FUNDING_BLOCKED"
    assert blocked["remaining_authority_cents"] == 1_000_000

    before = read_project(api, project["id"])
    revised = revise_project(
        api, project["id"], reimbursement_authority_cents=100_000_000
    )
    assert revised["clearance_posture"] == "AT_RISK"
    assert_version_advanced_by(before, revised)

    after = read_clearance_summary(api, project["id"])
    assert after["clearance_posture"] == "AT_RISK"
    assert after["estimated_state_liability_cents"] == CANON_STATE_LIABILITY_CENTS
    assert after["remaining_authority_cents"] == 100_000_000


def test_the_warning_lookahead_is_inclusive_on_the_sixtieth_day(api):
    """PRD 2.11: "The look-ahead boundary is inclusive: a commitment whose
    `window_end` is exactly 60 days after the current clock instant already makes the
    project `AT_RISK`."

    Design: Corner/calculations/clearance_warning_lookahead_is_inclusive_at_exactly_sixty_days
    """
    world = world_plan_approved(api)
    commitment = commit_window(
        api,
        world["plan_id"],
        world["owner_id"],
        window_start="2027-04-05T00:00:00Z",
        window_end="2027-04-30T00:00:00Z",
    )
    assert commitment["status"] == "COMMITTED"

    set_clock(api, "2027-02-28T00:00:00Z")
    day_sixty_one = read_clearance_summary(api, world["project_id"])
    assert day_sixty_one["clearance_posture"] == "CLEARANCE_PENDING"
    assert day_sixty_one["at_risk_commitment_count"] == 0
    assert day_sixty_one["overdue_commitment_count"] == 0

    set_clock(api, "2027-03-01T00:00:00Z")
    day_sixty = read_clearance_summary(api, world["project_id"])
    assert day_sixty["clearance_posture"] == "AT_RISK"
    assert day_sixty["at_risk_commitment_count"] == 1
    assert day_sixty["overdue_commitment_count"] == 0

    assert read_conflict(api, world["conflict_id"])["status"] == "RELOCATION_SCHEDULED"
    untouched = read_commitment(api, commitment["id"])
    assert untouched["status"] == "COMMITTED"
    assert untouched["version"] == commitment["version"]


def test_the_summary_figures_reconcile_after_creation_and_after_reversal(api):
    """PRD 2.8: "Conserved means an action that raises a figure and a compensating
    action that reverses it must leave the figure at exactly its prior value, not off
    by a single cent or a single rounding step."

    Design: Corner/cross_cutting_complexity_layers/the_derived_project_figures_reconcile_after_create_update_and_reversal_of_their_sources
    """
    project = register_project(api)
    owner = register_owner(api)
    facility = register_facility(api, owner["id"])

    empty = read_clearance_summary(api, project["id"])
    assert empty["estimated_state_liability_cents"] == 0
    assert empty["total_committed_reimbursement_cents"] == 0
    assert empty["remaining_authority_cents"] == 100_000_000

    conflict = identify_conflict(api, project["id"], facility["id"])
    select_resolution(api, conflict["id"], "RELOCATE")
    determination = draft_determination(api, conflict["id"])
    issue_determination(api, determination["id"])
    plan = submit_plan(api, conflict["id"])
    grant_permit(api, conflict["id"])
    approve_plan(api, plan["id"])

    commitment = commit_window(api, plan["id"], owner["id"])
    assert read_owner(api, owner["id"])["open_commitment_days"] == CANON_COMMITMENT_DAYS

    agreement = draft_agreement(api, plan["id"])
    circulate_agreement(api, agreement["id"])
    validate_success(
        api.execute_agreement(
            agreement["id"], make_agreement_officer_headers(OFFICER_USER_ID)
        )
    )

    committed = read_clearance_summary(api, project["id"])
    assert committed["estimated_state_liability_cents"] == CANON_STATE_LIABILITY_CENTS
    assert committed["total_committed_reimbursement_cents"] == (
        CANON_ESTIMATE_STATE_SHARE_CENTS
    )
    assert committed["remaining_authority_cents"] == 70_930_000

    cancel_commitment(api, commitment["id"], owner["id"], CANCELLATION_REASON)
    void_agreement(api, agreement["id"], VOID_REASON)

    reversed_summary = read_clearance_summary(api, project["id"])
    assert read_owner(api, owner["id"])["open_commitment_days"] == 0
    assert reversed_summary["total_committed_reimbursement_cents"] == 0
    assert reversed_summary["remaining_authority_cents"] == 100_000_000
    assert reversed_summary["estimated_state_liability_cents"] == (
        CANON_STATE_LIABILITY_CENTS
    )
    assert reversed_summary["open_conflict_count"] == 1
    assert reversed_summary["clearance_posture"] == "CLEARANCE_PENDING"


def test_every_derived_figure_appears_in_the_response_that_produced_it(api):
    """PRD 2.8: "Derived means no client writes them: they are recomputed by the
    server from their inputs whenever any input changes."

    Design: Corner/consistency_model/every_derived_figure_is_visible_in_the_same_response_that_caused_it
    """
    project = register_project(
        api, reimbursement_authority_cents=CANON_ESTIMATE_STATE_SHARE_CENTS
    )
    owner = register_owner(api)
    facility = register_facility(api, owner["id"])
    conflict = identify_conflict(api, project["id"], facility["id"])
    select_resolution(api, conflict["id"], "RELOCATE")
    determination = draft_determination(api, conflict["id"])

    issued = issue_determination(api, determination["id"])
    assert issued["final_state_share_pct"] == 100

    plan = submit_plan(api, conflict["id"])
    assert plan["betterment_ratio"] == CANON_BETTERMENT_RATIO
    assert plan["betterment_amount_cents"] == CANON_BETTERMENT_AMOUNT_CENTS

    grant_permit(api, conflict["id"])
    approve_plan(api, plan["id"])

    drafted = draft_agreement(api, plan["id"])
    assert_settlement_figures(
        drafted,
        cost_basis="ESTIMATE_BASIS",
        eligible_cost_cents=40_000_000,
        indirect_cost_cents=5_000_000,
        betterment_credit_cents=14_400_000,
        net_allowable_cents=30_600_000,
        participation_tier_pct=95,
        state_share_cents=CANON_ESTIMATE_STATE_SHARE_CENTS,
        owner_share_cents=1_530_000,
    )

    circulate_agreement(api, drafted["id"])
    executed = validate_success(
        api.execute_agreement(
            drafted["id"], make_agreement_officer_headers(OFFICER_USER_ID)
        )
    )
    assert executed["execution_status"] == "EXECUTED"
    assert executed["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS

    summary = read_clearance_summary(api, project["id"])
    assert summary["total_committed_reimbursement_cents"] == (
        CANON_ESTIMATE_STATE_SHARE_CENTS
    )
    assert summary["remaining_authority_cents"] == 0
    assert summary["clearance_posture"] == "CLEARANCE_PENDING"

    again = read_clearance_summary(api, project["id"])
    assert again == summary
