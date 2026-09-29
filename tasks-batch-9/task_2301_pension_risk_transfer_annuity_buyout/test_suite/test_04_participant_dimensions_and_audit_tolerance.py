"""Three orthogonal participant state dimensions, the confidence score that spans them,
and the inclusive audit variance tolerance.
"""

from test_helpers.constants import (
    AUDIT_VARIANCE_TOLERANCE_CENTS,
    accounting_liability,
    data_confidence_for,
    data_status_for,
    recomputed_monthly_benefit,
    settlement_liability,
)
from test_helpers.fixtures import (
    build_authorized_plan,
    build_quoting_tranche,
    confirm_address,
    confirm_alive,
    create_participant,
    open_benefit_audit,
    read_participant,
    read_tranche,
    record_mortality,
    resolve_audit,
)

DEFERRED = "DEFERRED_VESTED"
MONTHLY_BENEFIT_CENTS = 100000
EARNINGS_CENTS = 200000
SERVICE_MONTHS = 400


def _assigned_clean_participant(api):
    """A confirmed, alive, closed-audit participant assigned to a quoting tranche."""
    authorized = build_authorized_plan(api, participants=[])
    participant = create_participant(
        api,
        authorized.plan_id,
        cohort=DEFERRED,
        stated_monthly_benefit_cents=MONTHLY_BENEFIT_CENTS,
        final_average_monthly_earnings_cents=EARNINGS_CENTS,
        credited_service_months=SERVICE_MONTHS,
    )
    confirm_address(api, participant["id"])
    confirm_alive(api, participant["id"])
    audit = open_benefit_audit(api, participant["id"])
    resolve_audit(api, audit["id"], "ACCEPT_AS_IS")
    participant = read_participant(api, participant["id"])
    quoting = build_quoting_tranche(
        api, authorized.plan_id, [participant], target_cohort=DEFERRED
    )
    return authorized, read_participant(api, participant["id"]), quoting


# ---------------------------------------------------------------------------
# Design: Difficulty/non_linear_state_machine/participant_three_dimensions_advance_independently
# ---------------------------------------------------------------------------


def test_the_confidence_score_walks_up_as_each_separate_defect_is_cleared(api):
    """Each dimension contributes its own deduction, and the 80-point floor is inclusive.

    PRD: "An `address_status` of `UNCONFIRMED` costs 40 points, while an
    `address_status` of `UNLOCATABLE` costs only 25 — an exhausted search is a
    documented outcome, an un-started one is not, so a participant whose locator
    ladder is exhausted can still reach 75 while one who has never been searched sits
    at 60."

    PRD: "The score is floored at 0, and `data_status` is `CLEAN` when the score is at
    least 80 and `NEEDS_REVIEW` otherwise."

    Design: Difficulty/non_linear_state_machine/participant_three_dimensions_advance_independently
    """
    authorized = build_authorized_plan(api, participants=[])
    fresh = create_participant(
        api,
        authorized.plan_id,
        cohort=DEFERRED,
        stated_monthly_benefit_cents=MONTHLY_BENEFIT_CENTS,
        final_average_monthly_earnings_cents=EARNINGS_CENTS,
        credited_service_months=SERVICE_MONTHS,
    )
    assert fresh["data_confidence_score"] == data_confidence_for(
        "UNCONFIRMED", "UNVERIFIED", "NOT_AUDITED"
    )
    assert fresh["data_status"] == "NEEDS_REVIEW"

    addressed = confirm_address(api, fresh["id"])
    assert addressed["address_status"] == "CONFIRMED"
    assert addressed["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "UNVERIFIED", "NOT_AUDITED"
    )
    assert addressed["data_status"] == "NEEDS_REVIEW"

    alive = confirm_alive(api, fresh["id"])
    assert alive["mortality_status"] == "ALIVE_CONFIRMED"
    assert alive["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "ALIVE_CONFIRMED", "NOT_AUDITED"
    )
    assert alive["data_status"] == "CLEAN"

    audit = open_benefit_audit(api, fresh["id"])
    assert audit["audit_status"] == "PASSED"
    during_audit = read_participant(api, fresh["id"])
    assert during_audit["benefit_audit_status"] == "AUDIT_OPEN"
    assert during_audit["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "ALIVE_CONFIRMED", "AUDIT_OPEN"
    )

    resolve_audit(api, audit["id"], "ACCEPT_AS_IS")
    closed = read_participant(api, fresh["id"])
    assert closed["benefit_audit_status"] == "PASSED_CLOSED"
    assert closed["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "ALIVE_CONFIRMED", "PASSED_CLOSED"
    )
    assert closed["data_status"] == "CLEAN"


def test_the_mortality_cycle_runs_without_disturbing_the_other_two_dimensions(api):
    """Mortality moves through its whole cycle while address and roster status hold still.

    PRD: "Note that this dimension has no terminal state: a record can move between
    confirmation and dispute indefinitely, and it evolves entirely independently of
    `participant_status` and `address_status` on the same row."

    Design: Difficulty/non_linear_state_machine/participant_three_dimensions_advance_independently
    """
    _authorized, participant, _quoting = _assigned_clean_participant(api)

    assert participant["participant_status"] == "ASSIGNED"
    assert participant["address_status"] == "CONFIRMED"
    assert participant["mortality_status"] == "ALIVE_CONFIRMED"

    observations = [participant]
    observations.append(
        record_mortality(api, participant["id"], "DEATH_MATCH", date_of_death="2026-07-14")
    )
    observations.append(
        record_mortality(
            api,
            participant["id"],
            "DISPUTE_FILED",
            dispute_reason=(
                "Surviving spouse produced a notarised affidavit contesting the match."
            ),
        )
    )
    observations.append(
        record_mortality(api, participant["id"], "DISPUTE_RESOLVED_ALIVE")
    )

    assert [row["mortality_status"] for row in observations] == [
        "ALIVE_CONFIRMED",
        "DECEASED_CONFIRMED",
        "DEATH_DISPUTED",
        "ALIVE_CONFIRMED",
    ]
    for row in observations:
        assert row["participant_status"] == "ASSIGNED"
        assert row["address_status"] == "CONFIRMED"
        assert row["benefit_audit_status"] == "PASSED_CLOSED"

    assert observations[-1]["date_of_death"] is None


def test_a_confirmed_death_blocks_the_tranche_while_the_confidence_score_stays_perfect(api):
    """Readiness and the confidence score are separate predicates over the same row.

    PRD: "The recorded date of death is stored; every election of that participant
    whose `election_status` is `NOTICE_SENT`, `ELECTED_LUMP_SUM`, or `ELECTED_ANNUITY`
    transitions to `VOIDED`; `data_confidence_score` and `data_status` are recomputed;
    and if the participant is assigned to a tranche in `DRAFT`, `QUOTING`, or
    `INSURER_SELECTED`, that tranche's `accounting_liability_cents` and
    `settlement_liability_cents` are recomputed and its `data_readiness_flag` is set to
    `BLOCKED`."

    PRD: "A `mortality_status` of `UNVERIFIED` or `DEATH_DISPUTED` costs 20 points."

    Design: Difficulty/non_linear_state_machine/participant_three_dimensions_advance_independently
    """
    _authorized, participant, quoting = _assigned_clean_participant(api)

    live_accounting = accounting_liability(MONTHLY_BENEFIT_CENTS, DEFERRED)
    live_settlement = settlement_liability(MONTHLY_BENEFIT_CENTS, DEFERRED)
    assert participant["accounting_liability_cents"] == live_accounting
    assert quoting.tranche["data_readiness_flag"] == "READY"
    assert quoting.tranche["accounting_liability_cents"] == live_accounting

    deceased = record_mortality(
        api, participant["id"], "DEATH_MATCH", date_of_death="2026-07-14"
    )
    assert deceased["accounting_liability_cents"] == 0
    assert deceased["settlement_liability_cents"] == 0
    assert deceased["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "DECEASED_CONFIRMED", "PASSED_CLOSED"
    )
    assert deceased["data_status"] == "CLEAN"

    blocked = read_tranche(api, quoting.tranche_id)
    assert blocked["data_readiness_flag"] == "BLOCKED"
    assert blocked["accounting_liability_cents"] == 0

    disputed = record_mortality(
        api,
        participant["id"],
        "DISPUTE_FILED",
        dispute_reason="Surviving spouse produced a notarised affidavit contesting the match.",
    )
    assert disputed["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "DEATH_DISPUTED", "PASSED_CLOSED"
    )
    assert disputed["data_status"] == data_status_for(disputed["data_confidence_score"])
    assert disputed["data_status"] == "CLEAN"

    restored = record_mortality(api, participant["id"], "DISPUTE_RESOLVED_ALIVE")
    assert restored["accounting_liability_cents"] == live_accounting
    assert restored["settlement_liability_cents"] == live_settlement
    assert restored["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "ALIVE_CONFIRMED", "PASSED_CLOSED"
    )


# ---------------------------------------------------------------------------
# Design: Difficulty/boundary_precision_check/audit_variance_tolerance_is_inclusive_on_both_signs
# ---------------------------------------------------------------------------

AUDIT_EARNINGS_CENTS = 400000
AUDIT_SERVICE_MONTHS = 380
AUDIT_RECOMPUTED_CENTS = 190000


def _audited(api, plan_id, stated_monthly_benefit_cents):
    participant = create_participant(
        api,
        plan_id,
        cohort=DEFERRED,
        stated_monthly_benefit_cents=stated_monthly_benefit_cents,
        final_average_monthly_earnings_cents=AUDIT_EARNINGS_CENTS,
        credited_service_months=AUDIT_SERVICE_MONTHS,
    )
    confirm_address(api, participant["id"])
    confirm_alive(api, participant["id"])
    audit = open_benefit_audit(api, participant["id"])
    return read_participant(api, participant["id"]), audit


def test_a_variance_of_exactly_the_tolerance_passes_on_both_signs(api):
    """Plus and minus five hundred cents both land in `PASSED`.

    PRD: "The `variance_cents` is the participant's `stated_monthly_benefit_cents`
    minus the `recomputed_monthly_benefit_cents`, and may be negative when the sponsor
    was understating the benefit."

    PRD: "When the absolute value of `variance_cents` is at most 500 cents, the audit
    lands in `PASSED` — the bound is inclusive, so a variance of exactly five dollars
    in either direction passes — the participant's `audited_monthly_benefit_cents` is
    left untouched, the participant's `benefit_audit_status` becomes `AUDIT_OPEN` and
    stays there until the audit is resolved, and the participant's
    `data_confidence_score` and `data_status` are recomputed."

    Design: Difficulty/boundary_precision_check/audit_variance_tolerance_is_inclusive_on_both_signs
    """
    authorized = build_authorized_plan(api, participants=[])
    assert (
        recomputed_monthly_benefit(AUDIT_EARNINGS_CENTS, AUDIT_SERVICE_MONTHS)
        == AUDIT_RECOMPUTED_CENTS
    )

    low_stated = AUDIT_RECOMPUTED_CENTS - AUDIT_VARIANCE_TOLERANCE_CENTS
    high_stated = AUDIT_RECOMPUTED_CENTS + AUDIT_VARIANCE_TOLERANCE_CENTS
    low_participant, low_audit = _audited(api, authorized.plan_id, low_stated)
    high_participant, high_audit = _audited(api, authorized.plan_id, high_stated)

    for audit in (low_audit, high_audit):
        assert audit["recomputed_monthly_benefit_cents"] == AUDIT_RECOMPUTED_CENTS
        assert audit["audit_status"] == "PASSED"

    assert low_audit["variance_cents"] == -AUDIT_VARIANCE_TOLERANCE_CENTS
    assert high_audit["variance_cents"] == AUDIT_VARIANCE_TOLERANCE_CENTS

    for participant, stated in ((low_participant, low_stated), (high_participant, high_stated)):
        assert participant["benefit_audit_status"] == "AUDIT_OPEN"
        # A passing audit leaves the audited figure exactly as it stood.
        assert participant["audited_monthly_benefit_cents"] == stated
        assert participant["data_confidence_score"] == data_confidence_for(
            "CONFIRMED", "ALIVE_CONFIRMED", "AUDIT_OPEN"
        )
        assert participant["data_status"] == "CLEAN"


def test_one_cent_past_the_tolerance_forks_to_correction_required(api):
    """The fork changes the status set but not the confidence score.

    PRD: "When the absolute value of `variance_cents` exceeds 500 cents, the audit
    lands in `CORRECTION_REQUIRED` instead, the participant's `benefit_audit_status`
    is set to `CORRECTION_REQUIRED`, `data_confidence_score` and `data_status` are
    recomputed, and — the branch-specific extra hop — if the participant is assigned
    to a tranche whose `tranche_status` is `DRAFT`, `QUOTING`, or `INSURER_SELECTED`,
    that tranche's `data_readiness_flag` is set to `BLOCKED`."

    PRD: "A `benefit_audit_status` of `NOT_AUDITED`, `AUDIT_OPEN`,
    `CORRECTION_REQUIRED`, or `REOPENED` costs 15 points."

    Design: Difficulty/boundary_precision_check/audit_variance_tolerance_is_inclusive_on_both_signs
    """
    authorized = build_authorized_plan(api, participants=[])

    inside_stated = AUDIT_RECOMPUTED_CENTS - AUDIT_VARIANCE_TOLERANCE_CENTS
    over_stated = inside_stated - 1
    inside_participant, inside_audit = _audited(api, authorized.plan_id, inside_stated)
    over_participant, over_audit = _audited(api, authorized.plan_id, over_stated)

    assert over_audit["recomputed_monthly_benefit_cents"] == AUDIT_RECOMPUTED_CENTS
    assert over_audit["variance_cents"] == -(AUDIT_VARIANCE_TOLERANCE_CENTS + 1)
    assert over_audit["audit_status"] == "CORRECTION_REQUIRED"
    assert over_participant["benefit_audit_status"] == "CORRECTION_REQUIRED"

    # One cent of variance separates the two branches; the score cannot tell them apart.
    assert inside_audit["audit_status"] == "PASSED"
    assert inside_participant["benefit_audit_status"] == "AUDIT_OPEN"
    assert (
        over_participant["data_confidence_score"]
        == inside_participant["data_confidence_score"]
        == data_confidence_for("CONFIRMED", "ALIVE_CONFIRMED", "CORRECTION_REQUIRED")
    )
    assert over_participant["data_status"] == "CLEAN"
    assert over_participant["audited_monthly_benefit_cents"] == over_stated
