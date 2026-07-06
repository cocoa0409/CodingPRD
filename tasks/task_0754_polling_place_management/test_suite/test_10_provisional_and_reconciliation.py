"""Provisional adjudication branching and results-return reconciliation.

Queue A (difficulty): non_linear_state_machine, dual_variant_calc.
Queue B: reconciliation balanced result, reconcile OCC stale version.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_open_place, setup_closed_place_ready_to_reconcile,
    create_provisional_ballot_payload,
)

ADMIN = TEST_USERS["election_admin_headers"]
CAPTAIN = TEST_USERS["precinct_captain_headers"]


def _cast(api, place_id, name, reason="NO_ID"):
    return get_success_data(
        api.create_provisional_ballot(create_provisional_ballot_payload(place_id, name, reason),
                                      CAPTAIN)
    )


# ---- non_linear_state_machine / provisional_ballot_branching_accept_vs_reject ----

def test_adjudication_branches_to_accepted_and_rejected(api):
    """PRD §3.7: "Supplying a `decision` of ACCEPT advances the ballot `CAST → ACCEPTED` and
    increments the owning place's `provisional_accepted_count` by one. Supplying a `decision`
    of REJECT advances it `CAST → REJECTED` and, unlike acceptance, does not touch
    `provisional_accepted_count`."

    Design: Difficulty/non_linear_state_machine/provisional_ballot_branching_accept_vs_reject
    """
    ctx = setup_open_place(api)
    pp_id = ctx["place"]["id"]
    pb_a = _cast(api, pp_id, "V1")
    pb_b = _cast(api, pp_id, "V2")
    accepted = validate_success(api.adjudicate_provisional(pb_a["id"], {"decision": "ACCEPT"}, CAPTAIN))
    rejected = validate_success(api.adjudicate_provisional(pb_b["id"], {"decision": "REJECT"}, CAPTAIN))
    assert accepted["status"] == "ACCEPTED"
    assert rejected["status"] == "REJECTED"


def test_adjudication_side_effects_on_place_counts(api):
    """PRD §3.7: "Supplying a `decision` of ACCEPT advances the ballot `CAST → ACCEPTED` and
    increments the owning place's `provisional_accepted_count` by one. Supplying a `decision`
    of REJECT advances it `CAST → REJECTED` and, unlike acceptance, does not touch
    `provisional_accepted_count`."

    Design: Difficulty/non_linear_state_machine/provisional_ballot_branching_accept_vs_reject
    """
    ctx = setup_open_place(api)
    pp_id = ctx["place"]["id"]
    pb_a = _cast(api, pp_id, "V1")
    pb_b = _cast(api, pp_id, "V2")
    get_success_data(api.adjudicate_provisional(pb_a["id"], {"decision": "ACCEPT"}, CAPTAIN))
    get_success_data(api.adjudicate_provisional(pb_b["id"], {"decision": "REJECT"}, CAPTAIN))
    place = get_success_data(api.get_polling_place(pp_id, ADMIN))
    assert place["provisional_accepted_count"] == 1, "only the ACCEPT increments accepted count"
    assert place["provisional_cast_count"] == 2


# ---- dual_variant_calc / reconciliation_machine_vs_reconciled_diverge ----

def _place_reconciled_with_three_accepted(api):
    """Open place, 5 provisionals cast (3 ACCEPT, 2 REJECT), close, reconcile scanner=95,
    epollbook=100. Returns the reconciled place."""
    ctx = setup_open_place(api)
    pp_id = ctx["place"]["id"]
    ballots = [_cast(api, pp_id, f"V{i}") for i in range(5)]
    for pb in ballots[:3]:
        get_success_data(api.adjudicate_provisional(pb["id"], {"decision": "ACCEPT"}, CAPTAIN))
    for pb in ballots[3:]:
        get_success_data(api.adjudicate_provisional(pb["id"], {"decision": "REJECT"}, CAPTAIN))
    closed = get_success_data(api.close_place(pp_id, CAPTAIN))
    reconciled = validate_success(api.reconcile_place(
        pp_id,
        {"scanner_tally": 95, "epollbook_checkins": 100, "spoiled_count": 0,
         "expected_polling_place_version": closed["version"]},
        CAPTAIN,
    ))
    return reconciled


def test_reconciliation_inclusive_variant_yields_mismatch(api):
    """PRD §3.9: "Concretely, `reconciliation_discrepancy` is the sum of `scanner_tally` and
    `provisional_accepted_count`, minus `epollbook_checkins`. The `reconciliation_status` is
    `BALANCED` when `reconciliation_discrepancy` is exactly zero, and `MISMATCH` otherwise."

    Design: Difficulty/dual_variant_calc/reconciliation_machine_vs_reconciled_diverge
    """
    place = _place_reconciled_with_three_accepted(api)
    assert place["reconciliation_discrepancy"] == -2, (
        f"95 + 3 - 100 = -2, got {place['reconciliation_discrepancy']}"
    )
    assert place["reconciliation_status"] == "MISMATCH"


def test_reconciliation_inputs_stored_on_place(api):
    """PRD §3.9: "The reconciled inclusive view adds the place's live count of accepted
    provisional ballots, `provisional_accepted_count` (which are hand-counted separately), to
    `scanner_tally`; it therefore differs from the machine-only view by exactly
    `provisional_accepted_count`."

    Design: Difficulty/dual_variant_calc/reconciliation_machine_vs_reconciled_diverge
    """
    place = _place_reconciled_with_three_accepted(api)
    assert place["provisional_accepted_count"] == 3
    assert place["scanner_tally"] == 95


# ---- calculations / reconciliation_balanced_zero_discrepancy ----

def test_reconciliation_balanced_when_tally_matches(api):
    """PRD §3.9: "The `reconciliation_status` is `BALANCED` when `reconciliation_discrepancy`
    is exactly zero, and `MISMATCH` otherwise."
    PRD §3.9: "On success the place's `scanner_tally`, `epollbook_checkins`, and
    `spoiled_count` are stored, the reconciliation figures are recomputed, `readiness_posture`
    becomes `RECONCILED`, and the place's `version` increments."

    Design: Corner/calculations/reconciliation_balanced_zero_discrepancy
    """
    ctx = setup_closed_place_ready_to_reconcile(api)
    pp_id, version = ctx["place"]["id"], ctx["place"]["version"]
    place = validate_success(api.reconcile_place(
        pp_id,
        {"scanner_tally": 100, "epollbook_checkins": 100, "spoiled_count": 0,
         "expected_polling_place_version": version},
        CAPTAIN,
    ))
    assert place["reconciliation_discrepancy"] == 0
    assert place["reconciliation_status"] == "BALANCED"
    assert place["readiness_posture"] == "RECONCILED"


# ---- errors / reconcile_stale_version_returns_412 ----

def test_reconcile_with_stale_version_rejected(api):
    """PRD §2.8: "If `expected_polling_place_version` does not equal the place's current
    `version` — meaning another writer advanced the place since the client read it — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/reconcile_stale_version_returns_412
    """
    ctx = setup_closed_place_ready_to_reconcile(api)
    pp_id, stale_version = ctx["place"]["id"], ctx["place"]["version"]
    # First reconcile succeeds and advances the place version.
    get_success_data(api.reconcile_place(
        pp_id,
        {"scanner_tally": 100, "epollbook_checkins": 100, "spoiled_count": 0,
         "expected_polling_place_version": stale_version},
        CAPTAIN,
    ))
    # Second reconcile still carries the pre-advance version -> stale.
    resp = api.reconcile_place(
        pp_id,
        {"scanner_tally": 101, "epollbook_checkins": 100, "spoiled_count": 0,
         "expected_polling_place_version": stale_version},
        CAPTAIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
