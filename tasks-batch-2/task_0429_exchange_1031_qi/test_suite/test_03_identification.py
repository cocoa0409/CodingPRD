"""Identification lifecycle: candidates, aggregate FMV, the 3-property and 200%
breadth rules, finalize/revoke branches.

Translates difficulty rule non_linear_state_machine (revoke branch) and corner
sections calculations / validations / state_machines.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    make_qi_coordinator_headers,
    setup_closed_exchange, setup_draft_identification, setup_finalized_identification,
)
from test_helpers.factories import (
    create_identification_payload, create_candidate_payload,
)


def _add_candidates(api, idn_id, coordinator_id, fmvs):
    headers = make_qi_coordinator_headers(coordinator_id)
    for i, fmv in enumerate(fmvs):
        validate_success(
            api.add_candidate(idn_id, create_candidate_payload(description=f"c{i}", estimated_fmv=fmv), headers),
            expected_status=201,
        )


# ── Aggregate FMV ────────────────────────────────────────────────────

def test_aggregate_identified_fmv_sums_candidates(api):
    """PRD §3.4: "the parent identification's `aggregate_identified_fmv` is recomputed
    as the sum of the `estimated_fmv` of every candidate under that identification
    whose status is still `CANDIDATE`."

    Design: Corner/calculations/aggregate_identified_fmv_excludes_withdrawn
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-agg")
    headers = make_qi_coordinator_headers("coord-agg")
    idn = validate_success(
        api.create_identification(closed["id"], create_identification_payload("TWO_HUNDRED_PCT"), headers),
        expected_status=201,
    )
    _add_candidates(api, idn["id"], "coord-agg", [400000, 300000])
    data = validate_success(api.get_identification(idn["id"], headers))
    assert data["aggregate_identified_fmv"] == pytest.approx(700000.00, abs=0.01)


# ── 3-property rule ──────────────────────────────────────────────────

def test_three_property_allows_three_high_value_candidates(api):
    """PRD §3.4: "Under the `THREE_PROPERTY` method, the document may be finalized only
    if it lists at most three candidates in `CANDIDATE` status, regardless of their
    values."

    Design: Corner/calculations/three_property_rule_allows_three_high_value_candidates
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-3p")
    headers = make_qi_coordinator_headers("coord-3p")
    idn = validate_success(
        api.create_identification(closed["id"], create_identification_payload("THREE_PROPERTY"), headers),
        expected_status=201,
    )
    _add_candidates(api, idn["id"], "coord-3p", [800000, 800000, 800000])
    data = validate_success(api.finalize_identification(idn["id"], headers))
    assert data["status"] == "FINALIZED", "3 candidates allowed regardless of aggregate value"
    ex = validate_success(api.get_exchange(closed["id"], headers))
    assert ex["compliance_posture"] == "IDENTIFIED"


def test_three_property_four_candidates_rejected(api):
    """PRD §3.4: "A finalize with more than three candidates is rejected with
    `ERR_THREE_PROPERTY_RULE_VIOLATED`."

    Design: Corner/validations/three_property_four_candidates_violation
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-4p")
    headers = make_qi_coordinator_headers("coord-4p")
    idn = validate_success(
        api.create_identification(closed["id"], create_identification_payload("THREE_PROPERTY"), headers),
        expected_status=201,
    )
    _add_candidates(api, idn["id"], "coord-4p", [100000, 100000, 100000, 100000])
    resp = api.finalize_identification(idn["id"], headers)
    validate_error(resp, ApiErrorId.ERR_THREE_PROPERTY_RULE_VIOLATED.value)


# ── 200% rule ────────────────────────────────────────────────────────

def test_two_hundred_pct_aggregate_exceeds_cap_rejected(api):
    """PRD §3.4: "Under the `TWO_HUNDRED_PCT` method, the document may be finalized only
    if the `aggregate_identified_fmv` is at most twice the relinquished property's
    `fair_market_value` ... A finalize that breaches this cap is rejected with
    `ERR_TWO_HUNDRED_PCT_RULE_VIOLATED`."

    Design: Corner/validations/two_hundred_pct_aggregate_exceeds_cap_violation
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-2h")
    headers = make_qi_coordinator_headers("coord-2h")
    idn = validate_success(
        api.create_identification(closed["id"], create_identification_payload("TWO_HUNDRED_PCT"), headers),
        expected_status=201,
    )
    _add_candidates(api, idn["id"], "coord-2h", [300000, 300000, 300000, 300000])
    resp = api.finalize_identification(idn["id"], headers)
    validate_error(resp, ApiErrorId.ERR_TWO_HUNDRED_PCT_RULE_VIOLATED.value)


def test_two_hundred_pct_aggregate_at_exact_cap_passes(api):
    """PRD §3.4: "the `aggregate_identified_fmv` is at most twice the relinquished
    property's `fair_market_value` — that is, the aggregate candidate value must not
    exceed 200% of the relinquished sale price."

    Design: Corner/validations/two_hundred_pct_aggregate_at_exact_cap_passes
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-cap")
    headers = make_qi_coordinator_headers("coord-cap")
    idn = validate_success(
        api.create_identification(closed["id"], create_identification_payload("TWO_HUNDRED_PCT"), headers),
        expected_status=201,
    )
    _add_candidates(api, idn["id"], "coord-cap", [250000, 250000, 250000, 250000])
    data = validate_success(api.finalize_identification(idn["id"], headers))
    assert data["status"] == "FINALIZED", "aggregate exactly 1000000 == 200% cap is inclusive"


# ── Finalize / revoke branches ───────────────────────────────────────

def test_revoke_draft_identification_withdraws_candidates(api):
    """PRD §3.4: "It sets the identification's `status` to `REVOKED` and cascades
    downward, moving every child candidate currently in `CANDIDATE` status to
    `WITHDRAWN`."

    Design: Difficulty/non_linear_state_machine/identification_draft_branches_finalize_or_revoke
    """
    exchange, trust, idn, cands = setup_draft_identification("FORWARD", "coord-rev")
    headers = make_qi_coordinator_headers("coord-rev")
    data = validate_success(api.revoke_identification(idn["id"], headers))
    assert data["status"] == "REVOKED"
    cand_after = validate_success(api.list_candidates(idn["id"], headers))[0]
    assert cand_after["status"] == "WITHDRAWN", "revoke cascades CANDIDATE -> WITHDRAWN"


def test_revoke_branch_leaves_posture_open(api):
    """PRD §2.8: "`OPEN` once the relinquished leg has closed but before any
    identification is finalized."

    Design: Difficulty/non_linear_state_machine/identification_draft_branches_finalize_or_revoke
    """
    exchange, trust, idn, cands = setup_draft_identification("FORWARD", "coord-rev2")
    headers = make_qi_coordinator_headers("coord-rev2")
    validate_success(api.revoke_identification(idn["id"], headers))
    ex = validate_success(api.get_exchange(exchange["id"], headers))
    assert ex["compliance_posture"] == "OPEN", (
        "no FINALIZED identification exists; revoke must not flip posture to IDENTIFIED"
    )


def test_finalize_draft_identification_branch_sets_identified(api):
    """PRD §3.4: "A successful finalize stamps `finalized_at` to the current clock,
    sets the identification's `status` to `FINALIZED`, recomputes the parent exchange's
    posture to `IDENTIFIED` (the cascade from identification finalize to exchange
    posture), and increments the identification's `version`."

    Design: Difficulty/non_linear_state_machine/identification_draft_branches_finalize_or_revoke
    """
    exchange, trust, idn, cands = setup_finalized_identification("FORWARD", "coord-fin")
    headers = make_qi_coordinator_headers("coord-fin")
    assert idn["status"] == "FINALIZED"
    ex = validate_success(api.get_exchange(exchange["id"], headers))
    assert ex["compliance_posture"] == "IDENTIFIED", "finalize branch cascades posture to IDENTIFIED"


def test_revoke_finalized_identification_rejected(api):
    """PRD §3.4: "Revocation is permitted only while the identification is in `DRAFT`
    status."
    PRD §2.10: "state-machine legality (`ERR_INVALID_STATE` when the target entity is
    not in a state from which the requested transition is defined)."

    Design: Corner/state_machines/revoke_finalized_identification_returns_invalid_state
    """
    exchange, trust, idn, cands = setup_finalized_identification("FORWARD", "coord-rvf")
    headers = make_qi_coordinator_headers("coord-rvf")
    resp = api.revoke_identification(idn["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_identification(idn["id"], headers))
    assert after["status"] == "FINALIZED", "FINALIZED identification stays FINALIZED"


def test_immutable_candidate_has_no_version_field(api):
    """PRD §2.4: "the **identified candidate property** (`IdentifiedProperty`) carries
    only `id` and `created_at`. It has neither an `updated_at` nor a `version` field."

    Design: Corner/entities/identified_property_immutable_no_version_field
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-imm")
    headers = make_qi_coordinator_headers("coord-imm")
    idn = validate_success(
        api.create_identification(closed["id"], create_identification_payload("THREE_PROPERTY"), headers),
        expected_status=201,
    )
    cand = validate_success(
        api.add_candidate(idn["id"], create_candidate_payload(estimated_fmv=420000), headers),
        expected_status=201,
    )
    assert cand["status"] == "CANDIDATE"
    assert "version" not in cand, "IdentifiedProperty must not carry a version field"
    assert "updated_at" not in cand, "IdentifiedProperty must not carry an updated_at field"
