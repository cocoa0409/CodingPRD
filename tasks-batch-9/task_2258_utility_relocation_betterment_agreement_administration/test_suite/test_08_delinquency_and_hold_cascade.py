"""Late relocations, the two-strike hold and the administrative release."""
from test_helpers import (
    CANON_ESTIMATE_STATE_SHARE_CENTS,
    add_second_relocate_chain,
    commit_window,
    disallow_cost_document,
    read_agreement,
    read_commitment,
    read_conflict,
    read_cost_document,
    read_owner,
    read_project,
    release_owner_hold,
    report_complete,
    set_clock,
    submit_cost_document,
    world_commitment,
    world_final_billing_open,
    world_owner_on_hold,
)

EASEMENT_REACH_B = {
    "facility_type": "BURIED_ELECTRIC",
    "station_begin": 200.0,
    "station_end": 240.0,
    "offset_ft": 12.5,
    "depth_in": 48,
    "material": "PVC duct bank",
    "installed_year": 1968,
    "occupancy_basis": "PRIVATE_EASEMENT",
    "record_source": "AS_BUILT",
}

PLAN_B = {
    "estimated_cost_cents": 20_000_000,
    "replacement_in_kind_cost_cents": 20_000_000,
    "proposed_capacity_ratio": 1.00,
    "work_days": 9,
}


def _two_windows_and_a_billing_agreement(api, *, extra_documents=()):
    """One owner owing two relocation windows, with billing already open on the first."""
    world = world_final_billing_open(api)
    documents = [
        submit_cost_document(
            api,
            world["agreement_id"],
            world["owner_id"],
            doc_type="LABOR",
            amount_cents=12_345_678,
            incurred_on="2027-04-02T00:00:00Z",
            support_reference="PR-2027-04-A",
        )
    ]
    for spec in extra_documents:
        row = submit_cost_document(api, world["agreement_id"], world["owner_id"], **spec)
        documents.append(disallow_cost_document(api, row["id"]))
    world["documents"] = documents
    world["document_ids"] = [row["id"] for row in documents]

    add_second_relocate_chain(
        api,
        world,
        facility_overrides=EASEMENT_REACH_B,
        conflict_overrides={"conflict_station": 220.0, "clearance_deficiency_in": 14},
        plan_overrides=PLAN_B,
    )
    world["commitment"] = commit_window(api, world["plan_id"], world["owner_id"])
    world["commitment_id"] = world["commitment"]["id"]
    world["commitment_b"] = commit_window(
        api,
        world["plan_b_id"],
        world["owner_id"],
        window_start="2027-05-05T00:00:00Z",
        window_end="2027-05-20T00:00:00Z",
        committed_work_days=9,
    )
    world["commitment_b_id"] = world["commitment_b"]["id"]
    return world


def test_the_second_breach_carries_the_hold_into_the_agreement_and_its_document(api):
    """PRD 3.7: "First, the owner's `delinquency_strikes` increments by 1. Second,
    once `delinquency_strikes` reaches 2 — the delinquency hold threshold — the
    owner's `reimbursement_hold` flips from false to true. Third, because the owner
    is now on reimbursement hold, every reimbursement agreement of that owner whose
    `settlement_status` is `PENDING_FINAL_INVOICE` moves to `settlement_status`
    `HELD`. Fourth, because those agreements went on hold, every cost document of
    those agreements whose `review_status` is `SUBMITTED` moves to `review_status`
    `HELD`."

    Design: Difficulty/transitive_cascade/second_breach_cascades_commitment_to_owner_to_agreement_to_cost_document
    """
    world = _two_windows_and_a_billing_agreement(api)
    document_id = world["document_ids"][0]
    assert read_cost_document(api, document_id)["review_status"] == "SUBMITTED"

    set_clock(api, "2027-04-28T00:00:00Z")
    first = report_complete(
        api, world["commitment_id"], world["owner_id"], "Duct bank relocated eight days late."
    )
    assert first["status"] == "BREACHED"
    assert first["late_days"] == 8

    owner_after_first = read_owner(api, world["owner_id"])
    assert owner_after_first["delinquency_strikes"] == 1
    assert owner_after_first["reimbursement_hold"] is False
    assert read_agreement(api, world["agreement_id"])["settlement_status"] == (
        "PENDING_FINAL_INVOICE"
    )
    assert read_cost_document(api, document_id)["review_status"] == "SUBMITTED"

    set_clock(api, "2027-05-28T00:00:00Z")
    second = report_complete(
        api,
        world["commitment_b_id"],
        world["owner_id"],
        "Second relocation finished eight days late.",
    )
    assert second["status"] == "BREACHED"
    assert second["late_days"] == 8

    owner = read_owner(api, world["owner_id"])
    assert owner["delinquency_strikes"] == 2
    assert owner["reimbursement_hold"] is True
    assert owner["open_commitment_days"] == 0

    agreement = read_agreement(api, world["agreement_id"])
    assert agreement["settlement_status"] == "HELD"
    assert agreement["execution_status"] == "EXECUTED"
    assert agreement["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS

    assert read_cost_document(api, document_id)["review_status"] == "HELD"
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == CANON_ESTIMATE_STATE_SHARE_CENTS


def test_the_hold_does_not_disturb_the_executed_ledger_or_the_conflicts(api):
    """PRD 3.7: "Each row touched at each link is a real mutation with its own
    `version` increment, and only the third and fourth links are reversed by an
    administrative hold release; the strikes themselves are cleared only by that
    same release."

    Design: Difficulty/transitive_cascade/second_breach_cascades_commitment_to_owner_to_agreement_to_cost_document
    """
    world = world_owner_on_hold(api)
    owner = world["owner"]
    assert owner["delinquency_strikes"] == 2
    assert owner["reimbursement_hold"] is True
    assert owner["open_commitment_days"] == 0

    assert read_commitment(api, world["commitment_id"])["status"] == "BREACHED"
    assert read_commitment(api, world["commitment_id"])["late_days"] == 8
    assert read_commitment(api, world["commitment_b_id"])["status"] == "BREACHED"
    assert read_commitment(api, world["commitment_b_id"])["late_days"] == 8

    agreement = read_agreement(api, world["agreement_id"])
    assert agreement["settlement_status"] == "HELD"
    assert agreement["execution_status"] == "EXECUTED"
    assert agreement["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS
    assert agreement["cost_basis"] == "ESTIMATE_BASIS"
    assert read_cost_document(api, world["document_ids"][0])["review_status"] == "HELD"

    assert read_conflict(api, world["conflict_id"])["status"] == "RELOCATION_SCHEDULED"
    assert read_conflict(api, world["conflict_b_id"])["status"] == "RELOCATION_SCHEDULED"
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == CANON_ESTIMATE_STATE_SHARE_CENTS


def test_releasing_the_hold_restores_held_rows_and_spares_the_disallowed_one(api):
    """PRD 3.1: "Releasing the hold requires a `release_note` and performs four
    things in one transaction: `reimbursement_hold` returns to false,
    `delinquency_strikes` resets to 0, every reimbursement agreement of this owner
    sitting in `settlement_status` `HELD` returns to `PENDING_FINAL_INVOICE`, and
    every cost document of those agreements sitting in `review_status` `HELD`
    returns to `SUBMITTED`."

    Design: Corner/state_machines/release_hold_restores_held_rows_only_and_leaves_disallowed_documents_alone
    """
    world = _two_windows_and_a_billing_agreement(
        api,
        extra_documents=[
            {
                "doc_type": "EQUIPMENT",
                "amount_cents": 5_555_555,
                "incurred_on": "2027-04-15T00:00:00Z",
                "support_reference": "EQ-3001",
            }
        ],
    )
    submitted_id, disallowed_id = world["document_ids"]

    set_clock(api, "2027-04-28T00:00:00Z")
    assert report_complete(
        api, world["commitment_id"], world["owner_id"], "Late: rock encountered."
    )["late_days"] == 8
    set_clock(api, "2027-05-28T00:00:00Z")
    assert report_complete(
        api, world["commitment_b_id"], world["owner_id"], "Late again: crew shortage."
    )["late_days"] == 8

    assert read_agreement(api, world["agreement_id"])["settlement_status"] == "HELD"
    assert read_cost_document(api, submitted_id)["review_status"] == "HELD"
    assert read_cost_document(api, disallowed_id)["review_status"] == "DISALLOWED"

    released = release_owner_hold(
        api, world["owner_id"], "Delinquency cured under a corrective action plan."
    )
    assert released["reimbursement_hold"] is False
    assert released["delinquency_strikes"] == 0
    assert released["open_commitment_days"] == 0

    agreement = read_agreement(api, world["agreement_id"])
    assert agreement["settlement_status"] == "PENDING_FINAL_INVOICE"
    assert agreement["execution_status"] == "EXECUTED"

    assert read_cost_document(api, submitted_id)["review_status"] == "SUBMITTED"

    spared = read_cost_document(api, disallowed_id)
    assert spared["review_status"] == "DISALLOWED"
    assert spared["disallowed_amount_cents"] == 5_555_555
    assert spared["exclusion_reason"] == "NOT_SUPPORTED"


def test_one_breach_records_eight_late_days_and_a_single_strike(api):
    """PRD 3.7: "If the clock instant is later than `window_end`, the commitment
    moves to `BREACHED`, `late_days` is set to the difference between
    `actual_complete_at` and `window_end` expressed in days and rounded up to the
    next whole day (floored at 0), and a four-link cascade fires."

    Design: Corner/state_machines/first_breach_records_late_days_and_one_strike_without_imposing_a_hold
    """
    world = world_commitment(api)
    assert world["commitment"]["status"] == "COMMITTED"
    set_clock(api, "2027-04-28T00:00:00Z")

    breached = report_complete(
        api,
        world["commitment_id"],
        world["owner_id"],
        "Backfill finished eight days after the committed window.",
    )
    assert breached["status"] == "BREACHED"
    assert breached["late_days"] == 8
    assert breached["actual_complete_at"] == "2027-04-28T00:00:00Z"

    owner = read_owner(api, world["owner_id"])
    assert owner["delinquency_strikes"] == 1
    assert owner["reimbursement_hold"] is False
    assert owner["open_commitment_days"] == 0

    assert read_conflict(api, world["conflict_id"])["status"] == "RELOCATION_SCHEDULED"
    assert read_project(api, world["project_id"])["clearance_posture"] == (
        "CLEARANCE_PENDING"
    )
