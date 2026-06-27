"""Proofing, plant submission, and the page-lock cascade: the depth-2 cascade from
submit-plant, the cross-entity "all pages approved" precondition, the frozen-plant
guard on LOCKED pages, ladder-incomplete rejection, and proof round numbering.

Difficulty (queue A) and corner (queue B) instances appear here.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_proof_payload,
    create_yearbook,
    create_full_approved_yearbook,
    create_yearbook_with_open_proof_all_approved,
    create_yearbook_with_plant_submitted_proof,
    create_active_staff_assignment,
    create_approved_page,
    create_page,
    TEST_USERS,
)

ADVISER = TEST_USERS["adviser_headers"]
STAFF = TEST_USERS["staff_headers"]


# ─── Plant-submit cascade: pages LOCKED + phase PLANT (depth-2) ───────────────

def test_plant_submit_locks_pages_and_sets_phase_plant(api):
    """PRD §3.6: "When both hold, submitting to the plant cascades: every page
    currently in `APPROVED` on that yearbook transitions `APPROVED → LOCKED`, freezing
    the content so no further edits can land after the plant copy is made, and the
    yearbook's `production_phase` is recomputed to `PLANT`."

    Design: Difficulty/transitive_cascade/cascade_plant_submit_locks_pages_and_phase_depth2
    """
    yb, sa, pages, proof = create_yearbook_with_open_proof_all_approved(target_page_count=4)
    res = api.submit_plant_proof(proof["id"], ADVISER)
    proof_after = validate_success(res, 200)
    assert proof_after["status"] == "PLANT_SUBMITTED"

    page_after = validate_success(api.get_page(pages[0]["id"], ADVISER), 200)
    assert page_after["status"] == "LOCKED"

    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["production_phase"] == "PLANT"


def test_plant_submit_locks_every_approved_page(api):
    """PRD §3.6: "every page currently in `APPROVED` on that yearbook transitions
    `APPROVED → LOCKED`, freezing the content so no further edits can land after the
    plant copy is made".

    Design: Difficulty/transitive_cascade/cascade_plant_submit_locks_pages_and_phase_depth2
    """
    yb, sa, pages, proof = create_yearbook_with_open_proof_all_approved(target_page_count=4)
    validate_success(api.submit_plant_proof(proof["id"], ADVISER), 200)
    for page in pages:
        page_after = validate_success(api.get_page(page["id"], ADVISER), 200)
        assert page_after["status"] == "LOCKED"


# ─── Cross-entity: proof requires all pages approved ─────────────────────────

def test_plant_submit_requires_all_pages_approved(api):
    """PRD §3.6: "and every ladder page on the yearbook must be in `APPROVED`,
    otherwise it is rejected with `ERR_PAGES_NOT_ALL_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/cross_proof_requires_all_pages_approved
    """
    yb = create_yearbook(school_name="Tiny High", target_page_count=4)
    sa = create_active_staff_assignment(yb["id"])
    # 3 approved pages + 1 left DRAFT (ladder complete but not all approved).
    create_approved_page(yb["id"], sa["id"], 1, "STUDENT_LIFE")
    create_approved_page(yb["id"], sa["id"], 2, "ACADEMICS")
    create_approved_page(yb["id"], sa["id"], 3, "CLUBS")
    create_page(yb["id"], 4, "SIGNATURE", template_code="T",
                required_submission_count=0, assigned_staff_id=sa["id"])  # DRAFT
    proof = validate_success(
        api.create_proof(create_proof_payload(yb["id"]), ADVISER), 201
    )
    res = api.submit_plant_proof(proof["id"], ADVISER)
    validate_error(res, "ERR_PAGES_NOT_ALL_APPROVED")


def test_plant_submit_all_pages_approved_succeeds(api):
    """PRD §3.6: "and every ladder page on the yearbook must be in `APPROVED`,
    otherwise it is rejected with `ERR_PAGES_NOT_ALL_APPROVED`. When both hold,
    submitting to the plant cascades".

    Design: Difficulty/cross_entity_state_dependency/cross_proof_requires_all_pages_approved
    """
    # Contrast with the rejection case: when every page IS approved, submit-plant
    # is accepted and the proof advances to PLANT_SUBMITTED.
    yb, sa, pages, proof = create_yearbook_with_open_proof_all_approved(target_page_count=4)
    res = api.submit_plant_proof(proof["id"], ADVISER)
    proof_after = validate_success(res, 200)
    assert proof_after["status"] == "PLANT_SUBMITTED"


def test_plant_submit_with_incomplete_ladder_returns_ladder_incomplete(api):
    """PRD §3.6: "the yearbook must be ladder-complete (its `ladder_complete` flag
    true, i.e. `ladder_filled_count` equals `target_page_count`), otherwise the
    submission is rejected with `ERR_LADDER_INCOMPLETE`".

    Design: Corner/state_machines/plant_submit_with_incomplete_ladder_returns_ladder_incomplete
    """
    yb = create_yearbook(school_name="Tiny High", target_page_count=4)  # no pages
    proof = validate_success(
        api.create_proof(create_proof_payload(yb["id"]), ADVISER), 201
    )
    res = api.submit_plant_proof(proof["id"], ADVISER)
    validate_error(res, "ERR_LADDER_INCOMPLETE")


# ─── Frozen-plant guard on LOCKED pages ──────────────────────────────────────

def test_reopen_locked_page_after_plant_returns_plant_frozen(api):
    """PRD §3.4: "because a page only reaches `LOCKED` by way of a plant submission,
    the parent yearbook always has a `PLANT_SUBMITTED` or `PLANT_APPROVED` proof while
    the page is locked, so an attempt to reopen a `LOCKED` page is always rejected —
    and it is rejected specifically with the domain-meaningful `ERR_PLANT_FROZEN`
    rather than a generic invalid-state error."

    Design: Corner/state_machines/reopen_locked_page_after_plant_returns_plant_frozen
    """
    yb, sa, pages, proof = create_yearbook_with_plant_submitted_proof(target_page_count=4)
    res = api.request_changes_page(pages[0]["id"], ADVISER)
    validate_error(res, "ERR_PLANT_FROZEN")


# ─── Proof round numbering ───────────────────────────────────────────────────

def test_proof_round_number_increments_per_round(api):
    """PRD §3.6: "stamped with a `round_number` — a one-based ordinal that is one
    greater than the highest round number among existing proofs on the yearbook, so
    each new round increments."

    Design: Corner/state_machines/proof_round_number_increments_per_round
    """
    yb = create_yearbook()
    validate_success(api.create_proof(create_proof_payload(yb["id"]), ADVISER), 201)
    res = api.create_proof(create_proof_payload(yb["id"]), ADVISER)
    proof2 = validate_success(res, 201)
    assert proof2["round_number"] == 2
