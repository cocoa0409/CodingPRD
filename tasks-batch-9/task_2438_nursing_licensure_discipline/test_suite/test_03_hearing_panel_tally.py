"""Panel voting: the descending tier walk, the frozen floor, and continuances."""
from test_helpers import (
    FIVE_MEMBER_PANEL,
    PRESIDING,
    THREE_MEMBER_PANEL,
    ApiClient,
    cast_votes,
    record_hearing_event,
    reread_proceeding,
    seed_convened_proceeding,
    validate_success,
)

_FRAUD_COMPLAINT = {
    "complainant_type": "EMPLOYER",
    "violation_category": "FRAUD",
    "incident_date": "2026-07-10T00:00:00Z",
    "allegation_codes": ["FRD-BILL"],
    "employer_custodian_codes": ["MERCY-GEN"],
}

_FRAUD_DEMAND = {
    "record_class": "EMPLOYER_PERSONNEL",
    "custodian_code": "MERCY-GEN",
    "hold_start_at": "2026-08-05T00:00:00Z",
    "hold_end_at": "2026-09-05T00:00:00Z",
}


def _five_member_fraud_panel(api: ApiClient):
    """A convened five-member panel on a fraud complaint with produced records."""
    return seed_convened_proceeding(
        api,
        FIVE_MEMBER_PANEL,
        proceeding_overrides={"hearing_date": "2026-09-15T00:00:00Z",
                              "notice_period_days": 30},
        program_overrides={
            "program_code": "OH-BSN-11",
            "program_name": "Cuyahoga BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8700,
        },
        nurse_overrides={"full_name": "Marta Villalobos", "birth_year": 1979,
                         "ssn_last4": "9040"},
        page_count=42,
        evidence_overrides=_FRAUD_DEMAND,
        **_FRAUD_COMPLAINT,
    )


def _split_ballots():
    """Three revocation votes, one suspension, one reprimand."""
    return [("bm-1", "REVOCATION"), ("bm-2", "REVOCATION"), ("bm-3", "REVOCATION"),
            ("bm-4", "SUSPENSION"), ("bm-5", "REPRIMAND")]


def test_three_of_five_revocation_ballots_adopt_suspension_not_revocation(api: ApiClient):
    """PRD §3.8: "The system walks the ladder from index 6 down to index 1, and
    at each index counts the seated members whose effective tier index is at or
    above that index."

    PRD §3.8: "The threshold applied is the board's `revocation_vote_threshold_bp`
    at index 6 and the board's `majority_vote_threshold_bp` at every other index,
    and the test is integer cross-multiplication: the support count multiplied by
    10000 must be at or above the threshold multiplied by the seated count."

    PRD §3.8: "The first index that clears its own threshold is adopted, and the
    walk stops there."

    PRD §3.8: "`CLOSE_HEARING` moves `HEARING_CONVENED` to `DELIBERATION`,
    requires at least one vote cast by a seated non-recused member, and writes
    the tallied result into `adopted_sanction_tier`."

    Design: Difficulty/combinatorial_formula/panel_tally_walks_tier_ladder_from_revocation_downward
    """
    ctx = _five_member_fraud_panel(api)
    cast_votes(api, ctx["proceeding_id"], _split_ballots())

    closed = validate_success(
        api.record_hearing_event(ctx["proceeding_id"], {"event_type": "CLOSE_HEARING"},
                                 PRESIDING)
    )

    assert closed["adopted_sanction_tier"] == "SUSPENSION", (
        "Three of five revocation votes fall short of the two-thirds revocation "
        f"threshold, so suspension is adopted; got {closed['adopted_sanction_tier']}"
    )
    assert closed["status"] == "DELIBERATION", (
        f"Closing the hearing moves the proceeding to DELIBERATION, got {closed['status']}"
    )


def test_sanction_floor_frozen_at_convene_sits_below_the_adopted_tier(api: ApiClient):
    """PRD §3.8: "The base index comes from the complaint's
    `violation_category`: a practice-standard allegation starts at 1, fraud and
    substance use start at 3, a boundary violation starts at 4, and criminal
    conduct starts at 5."

    PRD §3.8: "Mitigation is accumulated as 2 if the complaint's
    `complainant_type` is `SELF_REPORT`, plus 1 if the nurse's
    `atd_participation_count` is 0, plus 2 if the complaint has at least one
    records demand and every one of them stands at `PRODUCED`."

    PRD §3.8: "The floor index is the base index plus the net score halved and
    rounded **toward positive infinity** — so a net of negative three contributes
    negative one, not negative two — and the result is then clamped to the range
    1 through 6."

    PRD §3.8: "Segregation of duties is applied at creation and is not negotiable
    afterwards: the calling board member's identity becomes
    `presiding_member_user_id` and is **removed** from `seated_member_user_ids`
    if it appears there, so the presiding member is never part of the panel that
    votes."

    Design: Difficulty/combinatorial_formula/panel_tally_walks_tier_ladder_from_revocation_downward
    """
    ctx = _five_member_fraud_panel(api)
    assert ctx["proceeding"]["sanction_floor_tier"] == "FINE", (
        "A fraud base of 3 less a mitigation net of three halved upward is index 2, "
        f"got {ctx['proceeding']['sanction_floor_tier']}"
    )

    cast_votes(api, ctx["proceeding_id"], _split_ballots())
    validate_success(
        api.record_hearing_event(ctx["proceeding_id"], {"event_type": "CLOSE_HEARING"},
                                 PRESIDING)
    )

    proceeding = reread_proceeding(api, ctx["proceeding_id"])
    assert proceeding["sanction_floor_tier"] == "FINE", (
        "The floor is computed once, at convene, and frozen thereafter"
    )
    assert proceeding["recused_member_user_ids"] == [], (
        "No panel member offered this nurse a monitoring agreement, so nobody recuses"
    )
    assert len(proceeding["votes"]) == 5, (
        f"Five ballots were cast and the array is append-only, got {len(proceeding['votes'])}"
    )
    assert proceeding["presiding_member_user_id"] == "bm-presiding", (
        "The calling board member becomes the presiding member"
    )
    assert "bm-presiding" not in proceeding["seated_member_user_ids"], (
        "The presiding member is never part of the voting panel"
    )


_BOUNDARY_COMPLAINT = {
    "complainant_type": "PATIENT",
    "violation_category": "BOUNDARY_VIOLATION",
    "incident_date": "2026-07-04T00:00:00Z",
    "employer_custodian_codes": ["LAKESIDE-2"],
}

_BOUNDARY_DEMAND = {
    "record_class": "EMPLOYER_INCIDENT",
    "custodian_code": "LAKESIDE-2",
    "hold_start_at": "2026-08-02T00:00:00Z",
    "hold_end_at": "2026-08-20T00:00:00Z",
}


def _continued_proceeding(api: ApiClient):
    """A convened proceeding that has been continued to a later hearing date."""
    ctx = seed_convened_proceeding(
        api,
        THREE_MEMBER_PANEL,
        proceeding_overrides={"hearing_date": "2026-09-15T00:00:00Z",
                              "notice_period_days": 30},
        program_overrides={
            "program_code": "OH-BSN-31",
            "program_name": "Hocking BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8000,
        },
        nurse_overrides={"full_name": "Owen Baptiste", "birth_year": 1983,
                         "ssn_last4": "1188"},
        page_count=8,
        evidence_overrides=_BOUNDARY_DEMAND,
        **_BOUNDARY_COMPLAINT,
    )
    ctx["proceeding"] = record_hearing_event(
        api, ctx["proceeding_id"], "CONTINUE",
        new_hearing_date="2026-11-01T00:00:00Z",
    )
    return ctx


def test_reconvening_after_a_continuance_returns_to_hearing_convened(api: ApiClient):
    """PRD §3.8: "`CONTINUE` moves `HEARING_CONVENED` to `CONTINUED`, replaces
    `hearing_date` with the supplied `new_hearing_date`, resets `noticed_at` to
    the logical clock — so the notice period must be satisfied afresh against the
    new date — and increments `continuance_count` by one."

    PRD §3.8: "`CONVENE` is permitted from `NOTICED` or `CONTINUED` and moves the
    proceeding to `HEARING_CONVENED`."

    Design: Difficulty/non_linear_state_machine/hearing_continuance_cycle_returns_to_convened_state
    """
    ctx = _continued_proceeding(api)
    assert ctx["proceeding"]["status"] == "CONTINUED", (
        f"A continuance parks the proceeding at CONTINUED, got {ctx['proceeding']['status']}"
    )

    reconvened = validate_success(
        api.record_hearing_event(ctx["proceeding_id"], {"event_type": "CONVENE"},
                                 PRESIDING)
    )

    assert reconvened["status"] == "HEARING_CONVENED", (
        f"Convening from CONTINUED returns to HEARING_CONVENED, got {reconvened['status']}"
    )
    assert reconvened["continuance_count"] == 1, (
        f"One continuance has been spent, got {reconvened['continuance_count']}"
    )
    assert reconvened["hearing_date"].startswith("2026-11-01T00:00:00"), (
        f"The continuance replaced the hearing date, got {reconvened['hearing_date']}"
    )
    assert reconvened["noticed_at"].startswith("2026-08-01T00:00:00"), (
        f"`noticed_at` was reset to the logical clock, got {reconvened['noticed_at']}"
    )


def test_reconvening_refreezes_the_floor_and_leaves_no_tier_adopted(api: ApiClient):
    """PRD §3.8: "Convening recomputes `recused_member_user_ids` against the
    nurse's monitoring history as it now stands and freezes the sanction floor
    into `sanction_floor_tier`."

    PRD §3.8: "the panel must have quorum, meaning the count of
    `seated_member_user_ids` less `recused_member_user_ids` must be at least 3,
    refused otherwise with `ERR_QUORUM_NOT_MET`."

    PRD §3.8: "The proceeding takes `status` `NOTICED`, stamps `noticed_at` from
    the logical clock, starts `continuance_count` at 0, `votes` as an empty
    array, `sanction_floor_tier` and `adopted_sanction_tier` at `NONE`, and
    `ordered_restriction_codes` as an empty array with `order_issued_at` null."

    Design: Difficulty/non_linear_state_machine/hearing_continuance_cycle_returns_to_convened_state
    """
    ctx = _continued_proceeding(api)

    reconvened = validate_success(
        api.record_hearing_event(ctx["proceeding_id"], {"event_type": "CONVENE"},
                                 PRESIDING)
    )

    assert reconvened["sanction_floor_tier"] == "PROBATION", (
        "A boundary-violation base of 4 less a mitigation net of three halved "
        f"upward is index 3, got {reconvened['sanction_floor_tier']}"
    )
    assert reconvened["adopted_sanction_tier"] == "NONE", (
        "No ballots have been cast, so no tier is adopted"
    )
    assert reconvened["votes"] == [], (
        "The vote array is still empty after the second convene"
    )
    assert reconvened["recused_member_user_ids"] == [], (
        "Recusals are recomputed at convene and this nurse has no monitoring history"
    )
    seated = len(reconvened["seated_member_user_ids"]) - len(
        reconvened["recused_member_user_ids"]
    )
    assert seated >= 3, f"Quorum requires at least three unrecused seats, got {seated}"
