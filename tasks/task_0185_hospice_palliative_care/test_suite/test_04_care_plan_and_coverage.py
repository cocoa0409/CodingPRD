"""Interdisciplinary care plans (cyclic revise loop, IDG completeness, supersede OCC) and
medication / DME coverage adjudication (active-plan reference, terminal-dx coverage, the
coverage-vs-plan precedence). PRD §3.5, §3.8, §3.13, §2.7.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    assert_care_plan,
    assert_coverage_item,
    setup_provider_and_election,
    setup_election_with_active_plan,
    setup_election_with_superseded_plan,
    create_care_plan,
    get_election,
    create_coverage_item_payload,
    create_care_plan_payload,
    TEST_USERS,
)

CLINICAL = TEST_USERS["clinical_headers"]


# ─── Non-linear state machine: cyclic revise loop ─────────────────────

def test_care_plan_revision_supersedes_prior_and_increments_revision(api):
    """PRD §3.5: "when a revision is committed, the named prior plan transitions from ACTIVE to
    SUPERSEDED and the new plan's revision_number becomes the prior plan's revision number plus
    one."

    Design: Difficulty/non_linear_state_machine/careplan_cyclic_revise_loop
    """
    provider, election, plan1, plan2 = setup_election_with_superseded_plan(
        election_date="2026-01-01T00:00:00Z")
    assert_care_plan(plan2)
    assert plan2["revision_number"] == 2, "revision_number 1 -> 2"
    assert plan2["status"] == "ACTIVE"
    p1 = validate_success(api.get_care_plan(plan1["id"], CLINICAL), 200)
    assert p1["status"] == "SUPERSEDED", "prior plan flips ACTIVE -> SUPERSEDED"


def test_only_one_active_plan_per_election_after_revision(api):
    """PRD §3.5: "A revision names the prior ACTIVE plan it replaces through its
    supersedes_plan_id (a self-reference into the care-plan set); when a revision is committed,
    the named prior plan transitions from ACTIVE to SUPERSEDED..."

    Design: Difficulty/non_linear_state_machine/careplan_cyclic_revise_loop
    """
    provider, election, plan1, plan2 = setup_election_with_superseded_plan(
        election_date="2026-01-01T00:00:00Z")
    plans, _ = validate_paginated(api.list_election_care_plans(
        election["id"], CLINICAL, params={"status": "ACTIVE", "limit": 100}))
    active_ids = {p["id"] for p in plans if p["status"] == "ACTIVE"}
    assert active_ids == {plan2["id"]}, (
        f"exactly one ACTIVE plan (the latest revision) should remain, got {active_ids}")


# ─── Priority-pair: item-not-covered beats plan-not-active ────────────

def test_uncovered_item_on_superseded_plan_returns_item_not_covered(api):
    """PRD §3.13: "For coverage items, the terminal-diagnosis coverage check
    (ERR_ITEM_NOT_COVERED) precedes the active-plan reference check (ERR_PLAN_NOT_ACTIVE)."
    PRD §3.8: "an order whose related_to_terminal_dx is false is rejected with
    ERR_ITEM_NOT_COVERED (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/item_not_covered_beats_plan_not_active_referential
    """
    provider, election, plan1, plan2 = setup_election_with_superseded_plan(
        election_date="2026-01-01T00:00:00Z")
    # plan1 is SUPERSEDED (would trip ERR_PLAN_NOT_ACTIVE) AND the item is not terminal-dx
    # related (ERR_ITEM_NOT_COVERED). The coverage check is checked first.
    payload = create_coverage_item_payload(election["id"], plan1["id"], item_type="MEDICATION",
                                            related_to_terminal_dx=False)
    res = api.create_coverage_item(payload, CLINICAL)
    validate_error(res, "ERR_ITEM_NOT_COVERED")


def test_uncovered_item_on_active_plan_returns_item_not_covered(api):
    """PRD §3.8: "an order whose related_to_terminal_dx is false is rejected with
    ERR_ITEM_NOT_COVERED (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/item_not_covered_beats_plan_not_active_referential
    """
    provider, election, plan1 = setup_election_with_active_plan(
        election_date="2026-01-01T00:00:00Z")
    payload = create_coverage_item_payload(election["id"], plan1["id"], item_type="DME",
                                            related_to_terminal_dx=False)
    res = api.create_coverage_item(payload, CLINICAL)
    validate_error(res, "ERR_ITEM_NOT_COVERED")


# ─── Cross-entity state dependency: coverage item needs ACTIVE plan ───

def test_covered_item_on_superseded_plan_returns_plan_not_active(api):
    """PRD §3.8: "The named care_plan_id must reference an ACTIVE care plan belonging to the
    same election; a reference to a plan that is not active, or that belongs to a different
    election, is rejected with ERR_PLAN_NOT_ACTIVE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/coverage_item_requires_active_care_plan
    """
    provider, election, plan1, plan2 = setup_election_with_superseded_plan(
        election_date="2026-01-01T00:00:00Z")
    # Item IS terminal-dx related, so coverage passes; plan1 is SUPERSEDED → ERR_PLAN_NOT_ACTIVE.
    payload = create_coverage_item_payload(election["id"], plan1["id"], item_type="DME",
                                            related_to_terminal_dx=True)
    res = api.create_coverage_item(payload, CLINICAL)
    validate_error(res, "ERR_PLAN_NOT_ACTIVE")


def test_covered_item_on_active_plan_succeeds(api):
    """PRD §3.8: "Coverage adjudication then sets the item's coverage_status: an item is COVERED
    when, and only when, its related_to_terminal_dx is true."

    Design: Difficulty/cross_entity_state_dependency/coverage_item_requires_active_care_plan
    """
    provider, election, plan1, plan2 = setup_election_with_superseded_plan(
        election_date="2026-01-01T00:00:00Z")
    payload = create_coverage_item_payload(election["id"], plan2["id"], item_type="DME",
                                            related_to_terminal_dx=True)
    item = validate_success(api.create_coverage_item(payload, CLINICAL), 201)
    assert_coverage_item(item)
    assert item["coverage_status"] == "COVERED"


# ─── Corner: review_due_offset_days default ───────────────────────────

def test_care_plan_review_due_offset_defaults_to_15(api):
    """PRD §3.5: "The plan also carries a review_due_offset_days, the calendar interval after the
    plan's creation at which the next mandatory interdisciplinary review falls due, which
    defaults to 15 and must be at least 1."

    Design: Corner/entities/care_plan_review_due_offset_default_applied
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z")
    plan = create_care_plan(election["id"], election["version"])
    assert plan["review_due_offset_days"] == 15


# ─── Corner: IDG incomplete rejected ──────────────────────────────────

def test_care_plan_missing_counselor_rejected(api):
    """PRD §3.5: "The list must include all four core disciplines PHYSICIAN, NURSE, SOCIAL_WORK,
    and COUNSELOR; a plan whose idg_members is missing any of these four is rejected with
    ERR_IDG_INCOMPLETE (HTTP 422)."

    Design: Corner/validations/idg_incomplete_rejected
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z")
    payload = create_care_plan_payload(election["id"], election["version"],
                                       idg_members=["PHYSICIAN", "NURSE", "SOCIAL_WORK"])
    res = api.create_care_plan(payload, CLINICAL)
    validate_error(res, "ERR_IDG_INCOMPLETE")


# ─── Corner: valid coverage item passes ───────────────────────────────

def test_terminal_dx_medication_under_active_plan_covered(api):
    """PRD §3.8: "an item is COVERED when, and only when, its related_to_terminal_dx is true."

    Design: Corner/validations/valid_coverage_item_passes
    """
    provider, election, plan1 = setup_election_with_active_plan(
        election_date="2026-01-01T00:00:00Z")
    payload = create_coverage_item_payload(election["id"], plan1["id"], item_type="MEDICATION",
                                            related_to_terminal_dx=True)
    item = validate_success(api.create_coverage_item(payload, CLINICAL), 201)
    assert item["coverage_status"] == "COVERED"


# ─── Corner: OCC stale election version on care-plan supersede ────────

def test_care_plan_supersede_with_stale_version_rejected(api):
    """PRD §2.7: "For a care-plan create, the request must likewise carry
    expected_election_version equal to the election's current version; if another writer has
    already committed a revision that superseded the same prior plan, the supersede target is no
    longer active and the client's election view is stale, so the create is rejected with
    ERR_STALE_ELECTION_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/careplan_supersede_stale_election_occ
    """
    provider, election, plan1 = setup_election_with_active_plan(
        election_date="2026-01-01T00:00:00Z")
    # election["version"] is the pre-plan1 version; creating plan1 already advanced it, so this
    # value is now stale by one.
    payload = create_care_plan_payload(election["id"], election["version"],
                                       supersedes_plan_id=plan1["id"])
    res = api.create_care_plan(payload, CLINICAL)
    validate_error(res, "ERR_STALE_ELECTION_VERSION")


# ─── Corner: care-plan coverage-items reverse lookup ──────────────────

def test_list_coverage_items_under_care_plan(api):
    """PRD §4 (endpoint): "GET /hospice/care-plans/{id}/coverage-items — List coverage items
    ordered under a care plan revision."
    PRD §3.8: "A CoverageItem names its election_id, the governing care_plan_id..."

    Design: Corner/endpoints/careplan_coverage_items_reverse_lookup
    """
    provider, election, plan1 = setup_election_with_active_plan(
        election_date="2026-01-01T00:00:00Z")
    payload = create_coverage_item_payload(election["id"], plan1["id"], item_type="DME",
                                            related_to_terminal_dx=True)
    item = validate_success(api.create_coverage_item(payload, CLINICAL), 201)
    data, meta = validate_paginated(api.list_care_plan_coverage_items(plan1["id"], CLINICAL))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == item["id"]
