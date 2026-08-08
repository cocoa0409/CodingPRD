"""Compliance flags, risk scoring, decay, delinquency cycle, and dual-variant risk."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    setup_active_registrant, open_flag, resolve_flag, set_clock, get_registrant,
    file_petition, TEST_USERS,
)

OFFICER = TEST_USERS["registration_officer_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]


def test_provisional_risk_counts_only_open_flags(api):
    """PRD 3.5: "The registrant's live `risk_score` is a decayed sum over the flags
    currently `OPEN`."
    PRD 3.5: "The flag type determines both a `severity` and a base weight
    `base_points`: `LATE_VERIFICATION` and `UNREPORTED_MOVE` are `MAJOR` and worth
    15 points; `TRAVEL_VIOLATION` is `MINOR` and worth 5 points".

    Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_adjudicated
    """
    jur, reg = setup_active_registrant(full_name="John Roe")
    major = open_flag(reg["id"], flag_type="UNREPORTED_MOVE")
    resolve_flag(major["id"])
    open_flag(reg["id"], flag_type="TRAVEL_VIOLATION")
    refreshed = get_registrant(reg["id"])
    assert refreshed["risk_score"] == 5, "only the OPEN MINOR TRAVEL_VIOLATION (5) counts"


def test_adjudicated_risk_counts_all_flags_undecayed(api):
    """PRD 3.8: "The `adjudicated_risk_score` is a lifetime risk figure computed
    over all of the registrant's flags ever opened — both `OPEN` and `RESOLVED` —
    using each flag's full `base_points` with no time decay, summed as whole
    integers."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_adjudicated
    """
    jur, reg = setup_active_registrant(full_name="John Roe")
    major = open_flag(reg["id"], flag_type="UNREPORTED_MOVE")
    resolve_flag(major["id"])
    open_flag(reg["id"], flag_type="TRAVEL_VIOLATION")
    pet = file_petition(reg["id"], petition_type="DEREGISTER")
    assert pet["adjudicated_risk_score"] == 20, "15 (RESOLVED MAJOR) + 5 (OPEN MINOR) == 20"


def test_risk_score_rounds_each_open_flag_before_summing(api):
    """PRD 2.9: "Flag risk contributions are rounded half up per flag first, and
    the registrant's `risk_score` is then the integer sum of those per-flag rounded
    contributions."
    PRD 3.5: "Its decay factor is one minus one one-hundredth per day open, but
    never allowed to fall below a floor of one half".

    Design: Difficulty/combinatorial_formula/risk_score_round_per_flag_then_sum
    """
    jur, reg = setup_active_registrant(full_name="Decay D")
    open_flag(reg["id"], flag_type="UNREPORTED_MOVE")   # MAJOR 15
    open_flag(reg["id"], flag_type="TRAVEL_VIOLATION")  # MINOR 5
    set_clock("2026-05-04T00:00:00Z")  # days_open = 3 -> decay 0.97
    refreshed = get_registrant(reg["id"])
    # round(15*0.97)=round(14.55)=15, round(5*0.97)=round(4.85)=5 => 20 (not 19).
    assert refreshed["risk_score"] == 20


def test_single_flag_contribution_rounds_half_up(api):
    """PRD 2.9: "Flag risk contributions are rounded half up per flag first, and
    the registrant's `risk_score` is then the integer sum of those per-flag rounded
    contributions."
    PRD 3.5: "Each flag's contribution is its `base_points` multiplied by that
    decay factor, rounded half up to a whole number".

    Design: Difficulty/combinatorial_formula/risk_score_round_per_flag_then_sum
    """
    jur, reg = setup_active_registrant(full_name="Decay D")
    open_flag(reg["id"], flag_type="UNREPORTED_MOVE")  # MAJOR 15
    set_clock("2026-05-04T00:00:00Z")  # decay 0.97 -> 15*0.97 = 14.55 -> round half up = 15
    refreshed = get_registrant(reg["id"])
    assert refreshed["risk_score"] == 15


def test_open_major_flag_flips_registrant_delinquent(api):
    """PRD 3.5: "Opening a flag recomputes the score. If the recomputed `risk_score`
    reaches or passes 15 while the registrant is `ACTIVE`, the registrant
    transitions `ACTIVE → DELINQUENT`".

    Design: Difficulty/non_linear_state_machine/registrant_active_delinquent_active_cycle
    """
    jur, reg = setup_active_registrant(full_name="Cyc C")
    open_flag(reg["id"], flag_type="UNREPORTED_MOVE")  # MAJOR 15 -> risk 15
    refreshed = get_registrant(reg["id"])
    assert refreshed["status"] == "DELINQUENT"
    assert refreshed["risk_score"] == 15


def test_resolving_last_flag_returns_registrant_to_active(api):
    """PRD 3.5: "When, after a resolution, the registrant has no `OPEN` flags
    remaining and the recomputed score is below 15 and the registrant is not an
    absconder, the registrant transitions `DELINQUENT → ACTIVE` with the score
    recomputed to zero."

    Design: Difficulty/non_linear_state_machine/registrant_active_delinquent_active_cycle
    """
    jur, reg = setup_active_registrant(full_name="Cyc C")
    fl = open_flag(reg["id"], flag_type="UNREPORTED_MOVE")
    resolved = resolve_flag(fl["id"])
    refreshed = get_registrant(reg["id"])
    assert refreshed["status"] == "ACTIVE"
    assert refreshed["risk_score"] == 0
    assert resolved["status"] == "RESOLVED"


def test_flag_open_then_resolve_conserves_risk_score(api):
    """PRD 3.5: "Resolving a flag is the compensating action: a
    `RegistrationOfficer` resolves an `OPEN` flag, which sets its `status` to
    `RESOLVED` and its `resolved_date` to the clock and recomputes `risk_score`."
    PRD 3.5: "the registrant transitions `DELINQUENT → ACTIVE` with the score
    recomputed to zero."

    Design: Difficulty/compensating_invariant/flag_open_resolve_conserves_risk_score
    """
    jur, reg = setup_active_registrant(full_name="Cons C")
    fl = open_flag(reg["id"], flag_type="UNREPORTED_MOVE")  # +15
    resolve_flag(fl["id"])                                   # -15
    refreshed = get_registrant(reg["id"])
    assert refreshed["risk_score"] == 0, "opening (+15) then resolving (-15) returns risk to 0"


def test_flag_open_then_resolve_returns_status_active(api):
    """PRD 3.5: "When, after a resolution, the registrant has no `OPEN` flags
    remaining and the recomputed score is below 15 and the registrant is not an
    absconder, the registrant transitions `DELINQUENT → ACTIVE` with the score
    recomputed to zero."

    Design: Difficulty/compensating_invariant/flag_open_resolve_conserves_risk_score
    """
    jur, reg = setup_active_registrant(full_name="Cons C")
    fl = open_flag(reg["id"], flag_type="UNREPORTED_MOVE")
    resolve_flag(fl["id"])
    refreshed = get_registrant(reg["id"])
    assert refreshed["status"] == "ACTIVE"


def test_resolving_already_resolved_flag_rejected(api):
    """PRD 3.5: "Resolving a flag that is not `OPEN` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/resolve_already_resolved_flag_returns_invalid_state
    """
    jur, reg = setup_active_registrant(full_name="Idem I")
    fl = open_flag(reg["id"], flag_type="UNREPORTED_MOVE")
    resolve_flag(fl["id"])
    resp = api.resolve_flag(fl["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_list_flags_returns_registrants_flags(api):
    """PRD 3.5: "Flags can be listed for a registrant, optionally narrowed by a
    `status` query filter."

    Design: Corner/endpoints/list_flags_by_registrant_reverse_reachable
    """
    jur, reg = setup_active_registrant(full_name="List L")
    fl = open_flag(reg["id"], flag_type="TRAVEL_VIOLATION")
    resp = api.list_flags(reg["id"], REVIEWER)
    data, meta = validate_paginated(resp)
    match = [f for f in data if f["id"] == fl["id"]]
    assert len(match) == 1, "the opened flag must appear in the registrant's flag list"
    assert match[0]["status"] == "OPEN"
