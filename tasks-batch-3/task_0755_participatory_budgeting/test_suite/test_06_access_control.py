"""Access control and validation precedence: RBAC denials, ownership, priority ordering."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    scenario_on_ballot_proposal, scenario_empty_selection_ready,
    open_ballot, add_entry, transition,
    new_cycle, new_category, new_resident, verify_resident,
    new_proposal, submit_proposal, create_budget_cycle_payload,
    make_resident_headers, TEST_USERS,
)

ADMIN = TEST_USERS["budget_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / cast_wrong_phase_beats_allocation_cap
# ---------------------------------------------------------------------------

def _ballot_over_cap(api, *, phase_after):
    """ALLOCATION cycle (per-voter cap 5000): a DRAFT ballot whose single entry
    allocates 6000 against the ON_BALLOT proposal. Advance the cycle to `phase_after`."""
    sc = scenario_on_ballot_proposal(api, voting_method="ALLOCATION", per_voter_cap=5000)
    bid = open_ballot(api, sc["cyc"], sc["rid"])["id"]
    add_entry(api, bid, sc["rid"], sc["pid"], allocated_cents=6000)
    if phase_after == "SELECTION":
        transition(api, sc["cyc"], "SELECTION")
    sc["bid"] = bid
    return sc


def test_cast_in_wrong_phase_reports_phase_error_over_allocation_cap(api):
    """PRD §2.9: "The validation concerns across the whole API are applied in a fixed priority
    order, so that when several would fail the same request, the earliest-listed one is the
    one the caller sees."
    PRD §2.9: "then the owning cycle's phase requirement (`ERR_WRONG_PHASE`) ... Business
    rules specific to individual workflows — ... allocation caps, ... — are evaluated after
    these system-wide gates"

    Design: Difficulty/priority_pair_validation_conflict/cast_wrong_phase_beats_allocation_cap
    """
    sc = _ballot_over_cap(api, phase_after="SELECTION")
    resp = api.cast_ballot(sc["bid"], make_resident_headers(sc["rid"]))
    validate_error(resp, ApiErrorId.ERR_WRONG_PHASE.value)


def test_allocation_cap_fires_only_once_phase_gate_passes(api):
    """PRD §3.6: "the sum of the active entries' `allocated_cents` must not exceed the cycle's
    `per_voter_allocation_cap_cents`, evaluated inclusively so that a total exactly equal to
    the cap is allowed; exceeding it is rejected with `ERR_ALLOCATION_CAP_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/cast_wrong_phase_beats_allocation_cap
    """
    sc = _ballot_over_cap(api, phase_after="VOTING")  # phase gate passes; only the cap can fail
    resp = api.cast_ballot(sc["bid"], make_resident_headers(sc["rid"]))
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_CAP_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
#             create_proposal_category_not_found_beats_wrong_phase
# ---------------------------------------------------------------------------

def _cycle_in_development(api):
    cyc = new_cycle(api, name="PBpb")
    cat = new_category(api, cyc["id"])
    res = new_resident(api)
    transition(api, cyc["id"], "SUBMISSION")
    transition(api, cyc["id"], "DEVELOPMENT")
    return cyc["id"], cat["id"], res["id"]


def test_missing_category_reports_not_found_over_wrong_phase(api):
    """PRD §2.9: "then existence of every referenced resource, path identifiers before body
    foreign keys (the not-found codes above); then the owning cycle's phase requirement
    (`ERR_WRONG_PHASE`)"

    Design: Difficulty/priority_pair_validation_conflict/create_proposal_category_not_found_beats_wrong_phase
    """
    cyc_id, _cat_id, rid = _cycle_in_development(api)
    resp = api.create_proposal(
        cyc_id, {"category_id": NON_EXISTENT_UUID, "title": "X", "summary": "s"}, make_resident_headers(rid)
    )
    validate_error(resp, ApiErrorId.ERR_CATEGORY_NOT_FOUND.value)


def test_wrong_phase_fires_only_once_existence_passes(api):
    """PRD §2.4: "proposal creation and submission require the cycle to be in `SUBMISSION` ...
    When an operation is attempted against a cycle that is not in the phase it requires, the
    request is rejected with `ERR_WRONG_PHASE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/create_proposal_category_not_found_beats_wrong_phase
    """
    cyc_id, cat_id, rid = _cycle_in_development(api)  # cycle is in DEVELOPMENT, not SUBMISSION
    resp = api.create_proposal(
        cyc_id, {"category_id": cat_id, "title": "X", "summary": "s"}, make_resident_headers(rid)
    )
    validate_error(resp, ApiErrorId.ERR_WRONG_PHASE.value)


# ---------------------------------------------------------------------------
# Corner: validations / corner_submit_other_residents_proposal_rejected
# ---------------------------------------------------------------------------

def test_submitting_another_residents_proposal_rejected(api):
    """PRD §3.3: "only when the acting resident is the proposal's submitter — the acting
    `Resident`'s id must equal the proposal's `submitter_id`, or the request is rejected with
    `ERR_NOT_OWNER`."

    Design: Corner/validations/corner_submit_other_residents_proposal_rejected
    """
    cyc = new_cycle(api, name="PBno")
    cat = new_category(api, cyc["id"])
    r1 = new_resident(api, full_name="R1", residency_document_ref="d1")
    r2 = new_resident(api, full_name="R2", residency_document_ref="d2")
    transition(api, cyc["id"], "SUBMISSION")
    prop = new_proposal(api, cyc["id"], cat["id"], r1["id"])
    resp = api.submit_proposal(prop["id"], make_resident_headers(r2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)


# ---------------------------------------------------------------------------
# Corner: errors / corner_anonymous_on_admin_endpoint_unauthenticated
# ---------------------------------------------------------------------------

def test_anonymous_on_admin_endpoint_unauthenticated(api):
    """PRD §2.1: "The `Anonymous` role is only accepted on endpoints that explicitly list it;
    using `Anonymous` anywhere else is likewise treated as an authentication failure and
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/corner_anonymous_on_admin_endpoint_unauthenticated
    """
    resp = api.create_budget_cycle(create_budget_cycle_payload(name="X"), ANON)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Corner: roles / corner_resident_cannot_create_budget_cycle
# ---------------------------------------------------------------------------

def test_resident_cannot_create_budget_cycle(api):
    """PRD §2.1: "When the acting role is a known role but is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/roles/corner_resident_cannot_create_budget_cycle
    """
    res = new_resident(api)
    resp = api.create_budget_cycle(create_budget_cycle_payload(name="X"), make_resident_headers(res["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Corner: roles / corner_reviewer_cannot_run_selection
# ---------------------------------------------------------------------------

def test_reviewer_cannot_run_selection(api):
    """PRD §2.1: "When the acting role is a known role but is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/roles/corner_reviewer_cannot_run_selection
    """
    sc = scenario_empty_selection_ready(api, )
    resp = api.create_selection_run(sc["cyc"], {"expected_budgetcycle_version": sc["ver"]}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
