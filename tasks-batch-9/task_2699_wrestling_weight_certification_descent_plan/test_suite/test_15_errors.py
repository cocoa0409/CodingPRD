"""
Error triggerability: the declared refusals of the certification regime.

Five families of refusal are exercised here, each against a world built only
through the declared endpoints.

The first is the pre-competition certification-database check on competition
entry (§3.7): an uncertified wrestler is refused with ``ERR_WRESTLER_NOT_CERTIFIED``
before any class arithmetic runs, while a certified wrestler asking for a class
beneath the floor computed as of the event date is refused with
``ERR_CLASS_BELOW_CERTIFIED_MINIMUM`` and the floor class itself is admitted.

The second is the pair of appeal-side bounds (§3.4): once as many retest rounds
as ``max_appeal_retest_rounds`` are recorded against an assessment, a fresh
filing against that same assessment is ``ERR_APPEAL_ROUND_LIMIT`` and a further
retest order is ``ERR_APPEAL_INVALID_STATE``.

The third is the entry-side pair of bracket constraints (§3.7, §3.8): a new
entry on a locked bracket is ``ERR_BRACKET_LOCKED``, while the state office's
weight-class change on that same locked bracket is the declared exemption and
succeeds; a class change on an entry that weigh-in closure auto-scratched is
``ERR_ENTRY_INVALID_STATE``.

The fourth is the pair of "already resolved" refusals (§3.9): a second medical
review of a ``REVIEWED`` flag is ``ERR_HEALTH_FLAG_INVALID_STATE`` and a second
finalize of a scored audit is ``ERR_AUDIT_INVALID_STATE``, and neither refusal
disturbs the severity ledger or the audit's stored score.

The fifth is the first gate of the whole precedence chain (§2.1, §2.8): a
missing header or an undeclared role name is an authentication failure with
``ERR_UNAUTHENTICATED``, never the ``ERR_UNAUTHORIZED`` reserved for a declared
role acting outside an endpoint's role list.
"""

from typing import Dict, List, Tuple

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_instant_equals,
    assert_row_count,
    assert_severity_ledger,
)
from test_helpers.constants import (
    APPEAL_RETEST_COMPLETED,
    APPEAL_RETEST_ORDERED,
    APPEAL_SUBMITTED,
    APPEAL_UNDER_REVIEW,
    ASSESSMENT_DAY_INSTANT,
    ASSESSMENT_VALIDATED,
    ASSESSOR_CERTIFIED,
    AUDIT_FINALIZED,
    AUDIT_INCONCLUSIVE,
    AUDIT_TYPE_ASSESSOR_SAMPLE,
    CANON_MIN_WEIGHT_CLASS_LBS,
    CANON_TARGET_CLASS_LBS,
    CANON_USG_FAIL,
    DEFAULT_AUDIT_MIN_SAMPLE_COUNT,
    DEFAULT_MAX_APPEAL_RETEST_ROUNDS,
    DEFAULT_WEIGHT_CLASSES,
    ENTRY_ENTERED,
    ENTRY_SCRATCHED,
    ENTRY_SEEDED,
    FLAG_HYDRATION_FAIL,
    FLAG_OPEN,
    FLAG_REVIEWED,
    METHOD_SKINFOLD,
    SCRATCH_REASON_NO_WEIGH_IN,
    SCORING_WORST_CASE,
    SEASON_OPEN,
    SEASON_SETUP,
    SEX_FEMALE,
    SEX_MALE,
    WRESTLER_UNCERTIFIED,
)
from test_helpers.test_users import (
    INVALID_IDENTITY_HEADERS,
    MEDICAL_REVIEWER,
    STATE_OFFICE,
    UNKNOWN_ROLE,
)

# ── Figures the tests below pin ──────────────────────────────────────

# The event every entry attempt is made against.  A WEEKLY_STEP schedule that
# starts 2026-11-02 has its last milestone dated 2026-12-07, so this date is
# past the whole schedule and the governing allowable weight is that last row.
ENTRY_EVENT_DATE = "2026-12-12"

# One rung below the floor class of the canonical measurement, and a declared
# member of the ladder, so the refusal is the class-floor one and not the
# malformed-value one (§2.5).
CLASS_BELOW_THE_FLOOR_LBS = 144

# One rung above the floor class, used for the class change that §3.8 exempts
# from the bracket lock.
CLASS_ABOVE_THE_FLOOR_LBS = 157

# A second reading by the same assessor on the same UTC calendar day, which is
# inside the assessor's daily capacity of three (§3.3).
SECOND_READING_AT = "2026-11-01T09:30:00Z"

# The appeal-ordered retest, taken by the reviewing assessor later the same day.
RETEST_ASSESSED_AT = "2026-11-01T11:00:00Z"

# The reviewing assessor's own credential number, globally unique (§3.2).
REVIEWER_CREDENTIAL_NUMBER = "AS-1002"

# Weigh-in day zero of the locked event: the clock has to stand on the event
# date for the reading to be inside the declared day range (§3.8).
WEIGH_IN_INSTANT = "2026-12-12T07:00:00Z"
PASSING_WEIGHT_LBS = 149.0

# The audit window and the single remeasured sample it carries.  One sample is
# below ``audit_min_sample_count`` of three, so the audit is unscoreable (§3.9).
AUDIT_WINDOW_START = "2026-11-01"
REMEASURED_BODY_FAT_PCT = 17.5

# The malformed identity header sets §2.1 pins: an absent ``X-User-ID``, an
# absent ``X-User-Role``, and a role name that is not one of the five declared
# ones.  An empty role name is likewise not one of the five.
_PINNED_IDENTITY_PROBES = (
    "no headers at all",
    "missing user id",
    "missing role",
    "unknown role name",
    "empty role",
)


def _identity_probes() -> List[Tuple[str, Dict[str, str]]]:
    """The header sets the requirements declare as authentication failures."""
    return [
        (label, headers)
        for label, headers in INVALID_IDENTITY_HEADERS
        if label in _PINNED_IDENTITY_PROBES
    ]


# ── Composite worlds ─────────────────────────────────────────────────

def _certified_and_uncertified_rosters(api) -> fixtures.Scenario:
    """One certified wrestler on a plan and one wrestler never assessed.

    The certified wrestler carries the canonical figures, so §3.3 fixes their
    ``min_weight_class_lbs`` at 150, and their WEEKLY_STEP plan is certified.
    The second roster member has no assessment at all, so §3.1 leaves their
    certification dimension at ``UNCERTIFIED``.
    """
    scenario = fixtures.certified_wrestler(api)
    uncertified = fixtures.create_wrestler(
        api, scenario.team_id, "Uma Nolan", SEX_FEMALE, 9
    )
    event = fixtures.create_event(
        api, scenario.season_id, "State Qualifier", ENTRY_EVENT_DATE
    )
    scenario.update(
        uncertified=uncertified,
        uncertified_id=uncertified["id"],
        event=event,
        event_id=event["id"],
    )
    return scenario


def _appeal_with_the_round_limit_reached(api) -> fixtures.Scenario:
    """One appeal carrying as many recorded retest rounds as the season allows.

    The chain is the one §3.4 declares: a coach files against the validated
    assessment inside the filing window, the state office assigns a reviewing
    assessor who is not the one who produced the result, that reviewer orders a
    retest, the retest is opened by the reviewer and finalized — which advances
    the appeal ``RETEST_ORDERED -> RETEST_COMPLETED`` — and the reviewer then
    orders a second retest, closing the cycle and taking
    ``retest_round_count`` to the season's ``max_appeal_retest_rounds`` of two.
    """
    scenario = fixtures.assessed_wrestler(api)
    reviewer = fixtures.create_certified_assessor(
        api,
        full_name="Sam Okafor",
        credential_number=REVIEWER_CREDENTIAL_NUMBER,
        certified_methods=[METHOD_SKINFOLD],
    )

    appeal = fixtures.file_appeal(api, scenario.assessment_id, scenario.team_id)
    assert appeal["status"] == APPEAL_SUBMITTED
    assert appeal["retest_round_count"] == 0
    # §2.4: the stamp is taken from the logical clock, not from wall time.
    assert_instant_equals(appeal["filed_at"], ASSESSMENT_DAY_INSTANT, "filed_at")

    under_review = fixtures.assign_reviewer(api, appeal["id"], reviewer["id"])
    assert under_review["status"] == APPEAL_UNDER_REVIEW

    ordered = fixtures.order_retest(api, appeal["id"], reviewer["id"])
    assert ordered["status"] == APPEAL_RETEST_ORDERED
    assert ordered["retest_round_count"] == 1

    retest = fixtures.create_assessment(
        api,
        scenario.wrestler_id,
        reviewer["id"],
        assessed_at=RETEST_ASSESSED_AT,
        body_fat_pct=14.6,
        appeal_id=appeal["id"],
        retest_of_assessment_id=scenario.assessment_id,
    )
    fixtures.finalize_assessment(api, retest["id"], reviewer["id"])

    completed = fixtures.read_appeal(api, appeal["id"])
    assert completed["status"] == APPEAL_RETEST_COMPLETED
    assert completed["retest_assessment_id"] == retest["id"]
    # §3.3 exempts the contested assessment from the supersede rule, so the
    # appeal still has a VALIDATED result to litigate.
    contested = fixtures.read_assessment(api, scenario.assessment_id)
    assert contested["status"] == ASSESSMENT_VALIDATED

    reordered = fixtures.order_retest(api, appeal["id"], reviewer["id"])
    assert reordered["status"] == APPEAL_RETEST_ORDERED
    assert reordered["retest_round_count"] == DEFAULT_MAX_APPEAL_RETEST_ROUNDS

    scenario.update(
        reviewer=reviewer,
        reviewer_id=reviewer["id"],
        appeal=reordered,
        appeal_id=appeal["id"],
        retest=retest,
        retest_id=retest["id"],
    )
    return scenario


def _locked_bracket(api) -> fixtures.Scenario:
    """An event whose bracket is locked, holding one seeded and one scratched entry.

    Two wrestlers of the same team are certified to class 150 and both entered.
    Only the first weighs in, so §3.8's weigh-in closure scratches the second
    with ``NO_WEIGH_IN``, and the first seeding run out of ``WEIGH_IN_CLOSED``
    seeds the survivor and sets ``bracket_locked`` true.
    """
    scenario = fixtures.certified_wrestler(api)
    other = fixtures.create_wrestler(
        api, scenario.team_id, "Blake Nunez", SEX_MALE, 12
    )
    other_assessment = fixtures.create_validated_assessment(
        api, other["id"], scenario.assessor_id, assessed_at=SECOND_READING_AT
    )
    fixtures.create_certified_plan(
        api, other["id"], scenario.team_id, other_assessment["id"]
    )

    event = fixtures.create_event(
        api, scenario.season_id, "Locked Bracket Open", ENTRY_EVENT_DATE
    )
    seeded_entry = fixtures.create_entry(
        api,
        event["id"],
        scenario.wrestler_id,
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=6,
    )
    scratched_entry = fixtures.create_entry(
        api,
        event["id"],
        other["id"],
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=2,
    )

    fixtures.open_weigh_ins(api, event["id"])
    fixtures.move_clock(api, WEIGH_IN_INSTANT)
    fixtures.record_weigh_in(
        api, event["id"], seeded_entry["id"], 0, PASSING_WEIGHT_LBS
    )
    fixtures.close_weigh_ins(api, event["id"])
    event = fixtures.seed_event(api, event["id"])

    assert event["bracket_locked"] is True
    assert event["seed_integrity_sum"] == 1

    seeded_entry = fixtures.read_entry(api, seeded_entry["id"])
    assert seeded_entry["status"] == ENTRY_SEEDED
    assert seeded_entry["seed_number"] == 1

    scratched_entry = fixtures.read_entry(api, scratched_entry["id"])
    assert scratched_entry["status"] == ENTRY_SCRATCHED
    assert scratched_entry["scratch_reason"] == SCRATCH_REASON_NO_WEIGH_IN

    scenario.update(
        other=other,
        other_id=other["id"],
        event=event,
        event_id=event["id"],
        seeded_entry=seeded_entry,
        seeded_entry_id=seeded_entry["id"],
        scratched_entry=scratched_entry,
        scratched_entry_id=scratched_entry["id"],
    )
    return scenario


def _open_flag_and_unscoreable_audit(api) -> fixtures.Scenario:
    """One OPEN hydration flag on the ledger and one audit that cannot be scored.

    A second reading on the same wrestler fails hydration, which §3.3 answers
    with a ``HYDRATION_FAIL`` flag of severity 1, and the audit opened over the
    validated reading carries a single sample — below the season's
    ``audit_min_sample_count`` of three (§3.9).
    """
    scenario = fixtures.assessed_wrestler(api)
    dehydrated = fixtures.create_assessment(
        api,
        scenario.wrestler_id,
        scenario.assessor_id,
        assessed_at=SECOND_READING_AT,
        measured_weight_lbs=158.0,
        urine_specific_gravity=CANON_USG_FAIL,
    )
    fixtures.finalize_assessment(api, dehydrated["id"], scenario.assessor_id)

    flags = fixtures.flags_of_wrestler(api, scenario.wrestler_id, FLAG_OPEN)
    assert len(flags) == 1
    flag = flags[0]
    assert flag["source"] == FLAG_HYDRATION_FAIL
    assert flag["severity"] == 1
    assert_severity_ledger(fixtures.read_team(api, scenario.team_id), 1)

    audit = fixtures.open_audit(
        api,
        scenario.season_id,
        AUDIT_TYPE_ASSESSOR_SAMPLE,
        SCORING_WORST_CASE,
        AUDIT_WINDOW_START,
        assessor_id=scenario.assessor_id,
        samples=factories.audit_samples(
            [(scenario.assessment_id, REMEASURED_BODY_FAT_PCT)]
        ),
    )
    assert audit["sample_count"] == 1

    scenario.update(
        flag=flag,
        flag_id=flag["id"],
        audit=audit,
        audit_id=audit["id"],
    )
    return scenario


# ── The certification-database refusals on competition entry ─────────

def test_entry_of_a_wrestler_with_no_validated_assessment_is_refused(api):
    """An uncertified wrestler cannot be entered in any class.

    §3.7 refuses a wrestler whose ``certification_status`` is ``UNCERTIFIED`` or
    ``SUSPENDED`` with ``ERR_WRESTLER_NOT_CERTIFIED``, and §2.8 puts that check
    ahead of the class arithmetic — so the refusal stands even for the class the
    certified roster member is admitted into.  The refused call creates nothing:
    §3.7 increments ``entry_count`` only on a successful entry.

    Design: Corner/errors/not_certified_and_class_below_minimum_errors_triggerable
    """
    scenario = _certified_and_uncertified_rosters(api)

    uncertified = fixtures.read_wrestler(api, scenario.uncertified_id)
    assert uncertified["certification_status"] == WRESTLER_UNCERTIFIED
    assert uncertified["source_assessment_id"] is None

    refused = api.create_entry(
        scenario.event_id,
        factories.entry_payload(
            scenario.uncertified_id, CANON_TARGET_CLASS_LBS, season_win_count=0
        ),
        scenario.coach,
    )
    validate_error(refused, api_errors.ERR_WRESTLER_NOT_CERTIFIED, 409)

    assert fixtures.read_event(api, scenario.event_id)["entry_count"] == 0
    assert_row_count(
        api.list_entries(STATE_OFFICE, {"event_id": scenario.event_id, "limit": 100}),
        0,
        "entries of the event",
    )


def test_entry_below_the_floor_class_is_refused_while_the_floor_class_is_admitted(api):
    """The class-floor refusal is a 422 distinct from the malformed-value one.

    The canonical measurement fixes the wrestler's ``min_weight_class_lbs`` at
    150 (§3.3), and their certified WEEKLY_STEP schedule keeps the floor there as
    of the event date (§3.7).  Class 144 is a declared member of the season's
    ladder, so §2.5's ``ERR_INVALID_WEIGHT_CLASS`` does not apply; it is beneath
    the wrestler's lowest eligible class, which §3.7 refuses with
    ``ERR_CLASS_BELOW_CERTIFIED_MINIMUM``.  The very same request at 150 is
    admitted, landing in ``ENTERED`` and incrementing ``entry_count`` once.

    Design: Corner/errors/not_certified_and_class_below_minimum_errors_triggerable
    """
    scenario = _certified_and_uncertified_rosters(api)

    assert CLASS_BELOW_THE_FLOOR_LBS in DEFAULT_WEIGHT_CLASSES
    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["min_weight_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS

    refused = api.create_entry(
        scenario.event_id,
        factories.entry_payload(
            scenario.wrestler_id, CLASS_BELOW_THE_FLOOR_LBS, season_win_count=2
        ),
        scenario.coach,
    )
    validate_error(refused, api_errors.ERR_CLASS_BELOW_CERTIFIED_MINIMUM, 422)
    assert fixtures.read_event(api, scenario.event_id)["entry_count"] == 0

    admitted = validate_success(
        api.create_entry(
            scenario.event_id,
            factories.entry_payload(
                scenario.wrestler_id, CANON_TARGET_CLASS_LBS, season_win_count=2
            ),
            scenario.coach,
        ),
        201,
    )
    assert admitted["status"] == ENTRY_ENTERED
    assert admitted["weight_class_lbs"] == CANON_TARGET_CLASS_LBS
    assert admitted["seed_number"] is None
    assert admitted["latest_effective_weight_lbs"] is None
    assert admitted["scratch_reason"] is None
    assert admitted["weight_class_change_count"] == 0

    assert fixtures.read_event(api, scenario.event_id)["entry_count"] == 1


# ── The appeal-side bounds on relitigating one measurement ────────────

def test_fresh_appeal_filing_is_refused_once_the_round_limit_is_reached(api):
    """The retest bound is on the assessment, not on the one appeal.

    §3.4 refuses a fresh filing with ``ERR_APPEAL_ROUND_LIMIT`` when the
    assessment under appeal already has as many retest rounds recorded across any
    appeal of that assessment as ``max_appeal_retest_rounds`` allows — two, by
    default.  The filing window is still open, so timeliness is not what refuses
    this call, and the refused filing creates no second appeal row.

    Design: Corner/errors/appeal_invalid_state_and_retest_round_limit_errors_triggerable
    """
    scenario = _appeal_with_the_round_limit_reached(api)

    refused = api.create_appeal(
        scenario.assessment_id,
        factories.appeal_payload(
            scenario.team_id, "Second bite at the same assessment"
        ),
        scenario.coach,
    )
    validate_error(refused, api_errors.ERR_APPEAL_ROUND_LIMIT, 409)

    assert_row_count(
        api.list_appeals(
            STATE_OFFICE, {"assessment_id": scenario.assessment_id, "limit": 100}
        ),
        1,
        "appeals of the contested assessment",
    )


def test_a_third_retest_order_is_refused_by_the_round_count_precondition(api):
    """The retest cycle is bounded, and the refusal leaves the counter alone.

    §3.4 permits an order only while ``retest_round_count`` is strictly less than
    the season's ``max_appeal_retest_rounds`` and calls the attempt at the bound
    ``ERR_APPEAL_INVALID_STATE``.  Because the refused call performs no mutation,
    §2.4's bookkeeping leaves both the round count and the appeal's ``version``
    exactly where the second order left them.

    Design: Corner/errors/appeal_invalid_state_and_retest_round_limit_errors_triggerable
    """
    scenario = _appeal_with_the_round_limit_reached(api)
    before = scenario.appeal

    refused = api.order_appeal_retest(
        scenario.appeal_id, fixtures.assessor_headers(scenario.reviewer_id)
    )
    validate_error(refused, api_errors.ERR_APPEAL_INVALID_STATE, 409)

    after = fixtures.read_appeal(api, scenario.appeal_id)
    assert after["status"] == APPEAL_RETEST_ORDERED
    assert after["retest_round_count"] == DEFAULT_MAX_APPEAL_RETEST_ROUNDS
    assert after["version"] == before["version"]


# ── The entry-side bracket constraints and the one exemption ──────────

def test_new_entry_on_a_locked_bracket_is_refused_while_the_class_change_is_exempt(api):
    """A locked bracket admits no new competitor, but still admits a class change.

    §3.7 refuses every new entry on an event whose ``bracket_locked`` flag a first
    successful seeding run has set true, with ``ERR_BRACKET_LOCKED``, and names
    state-office weight-class changes and reseeds as the only sanctioned way to
    alter a locked bracket.  §3.8 then makes that exemption concrete: the change
    sets the new class, increments ``weight_class_change_count``, keeps the entry
    in ``SEEDED`` and reseeds both the vacated and the destination group, so §2.9's
    ``seed_integrity_sum`` still reports one contiguous run beginning at 1.

    Design: Corner/errors/bracket_locked_and_entry_invalid_state_errors_triggerable
    """
    scenario = _locked_bracket(api)

    refused = api.create_entry(
        scenario.event_id,
        factories.entry_payload(
            scenario.other_id, CANON_TARGET_CLASS_LBS, season_win_count=2
        ),
        scenario.coach,
    )
    validate_error(refused, api_errors.ERR_BRACKET_LOCKED, 409)

    changed = validate_success(
        api.change_entry_weight_class(
            scenario.seeded_entry_id,
            factories.weight_class_change_payload(
                CLASS_ABOVE_THE_FLOOR_LBS, scenario.seeded_entry["version"]
            ),
            STATE_OFFICE,
        )
    )
    assert changed["weight_class_lbs"] == CLASS_ABOVE_THE_FLOOR_LBS
    assert changed["status"] == ENTRY_SEEDED
    assert changed["seed_number"] == 1
    assert changed["weight_class_change_count"] == 1

    event = fixtures.read_event(api, scenario.event_id)
    assert event["bracket_locked"] is True
    assert event["seed_integrity_sum"] == 1
    assert event["reseed_required"] is False


def test_weight_class_change_on_a_scratched_entry_is_refused(api):
    """A scratched entry is beyond even the state office's reach.

    §3.8 declares that an entry already ``SCRATCHED`` or ``DISQUALIFIED`` is
    ``ERR_ENTRY_INVALID_STATE`` on a weight-class change.  The class asked for is
    a declared ladder member at or above the wrestler's floor and the version pin
    is current, so nothing earlier in §2.8's precedence chain intervenes, and the
    refused call leaves the entry's class, its change counter and its ``version``
    exactly as weigh-in closure left them.

    Design: Corner/errors/bracket_locked_and_entry_invalid_state_errors_triggerable
    """
    scenario = _locked_bracket(api)
    before = scenario.scratched_entry

    refused = api.change_entry_weight_class(
        scenario.scratched_entry_id,
        factories.weight_class_change_payload(
            CLASS_ABOVE_THE_FLOOR_LBS, before["version"]
        ),
        STATE_OFFICE,
    )
    validate_error(refused, api_errors.ERR_ENTRY_INVALID_STATE, 409)

    after = fixtures.read_entry(api, scenario.scratched_entry_id)
    assert after["status"] == ENTRY_SCRATCHED
    assert after["scratch_reason"] == SCRATCH_REASON_NO_WEIGH_IN
    assert after["weight_class_lbs"] == CANON_TARGET_CLASS_LBS
    assert after["weight_class_change_count"] == 0
    assert after["version"] == before["version"]


# ── The "already resolved" refusals of the health and audit layers ────

def test_a_second_medical_review_of_a_reviewed_flag_is_refused(api):
    """A flag that has been reviewed is closed to further review.

    §3.9 makes only ``OPEN`` and ``ESCALATED`` flags reviewable and answers a
    review of one already ``REVIEWED`` or ``DISMISSED`` with
    ``ERR_HEALTH_FLAG_INVALID_STATE``.  The first review is the compensating
    action §2.9 requires: it removes the flag's severity from the team's
    ``open_flag_severity_total``, which returns the ledger to 0 and the derived
    posture to ``CLEAR``.  The refused second review is inert — the ledger stays
    at 0 and the flag's ``review_note`` and ``version`` are untouched.

    Design: Corner/errors/health_flag_and_audit_invalid_state_errors_triggerable
    """
    scenario = _open_flag_and_unscoreable_audit(api)

    reviewed = fixtures.review_flag(api, scenario.flag_id, FLAG_REVIEWED)
    assert reviewed["status"] == FLAG_REVIEWED
    assert reviewed["review_note"] is not None
    assert reviewed["reviewer_user_id"] is not None
    assert_severity_ledger(fixtures.read_team(api, scenario.team_id), 0)

    refused = api.review_health_flag(
        scenario.flag_id,
        factories.flag_review_payload(FLAG_REVIEWED, "A second physician look."),
        MEDICAL_REVIEWER,
    )
    validate_error(refused, api_errors.ERR_HEALTH_FLAG_INVALID_STATE, 409)

    after = fixtures.read_flag(api, scenario.flag_id)
    assert after["status"] == FLAG_REVIEWED
    assert after["review_note"] == reviewed["review_note"]
    assert after["version"] == reviewed["version"]
    assert_severity_ledger(fixtures.read_team(api, scenario.team_id), 0)


def test_a_second_finalize_of_an_inconclusive_audit_is_refused(api):
    """An unscoreable audit still lands in FINALIZED, and stays there.

    §3.9 declares that an audit whose ``sample_count`` is strictly below the
    season's ``audit_min_sample_count`` is unscoreable: its ``outcome`` becomes
    ``INCONCLUSIVE``, its ``discrepancy_score`` stays null, it lands in
    ``FINALIZED`` all the same, the subject assessor's ``last_audit_outcome``
    reflects that verdict, and no cascade runs — the credential stands and every
    assessment survives.  Finalizing is accepted only out of ``OPEN``, so the
    second attempt is ``ERR_AUDIT_INVALID_STATE`` and leaves the scored row,
    including its ``version``, exactly as the first finalize left it.

    Design: Corner/errors/health_flag_and_audit_invalid_state_errors_triggerable
    """
    scenario = _open_flag_and_unscoreable_audit(api)
    assert scenario.audit["sample_count"] < DEFAULT_AUDIT_MIN_SAMPLE_COUNT

    finalized = fixtures.finalize_audit(api, scenario.audit_id)
    assert finalized["status"] == AUDIT_FINALIZED
    assert finalized["outcome"] == AUDIT_INCONCLUSIVE
    assert finalized["discrepancy_score"] is None
    assert finalized["voided_assessment_count"] == 0

    assessor = fixtures.read_assessor(api, scenario.assessor_id)
    assert assessor["status"] == ASSESSOR_CERTIFIED
    assert assessor["last_audit_outcome"] == AUDIT_INCONCLUSIVE
    assert assessor["voided_assessment_count"] == 0
    sampled = fixtures.read_assessment(api, scenario.assessment_id)
    assert sampled["status"] == ASSESSMENT_VALIDATED

    refused = api.finalize_audit(scenario.audit_id, STATE_OFFICE)
    validate_error(refused, api_errors.ERR_AUDIT_INVALID_STATE, 409)

    after = fixtures.read_audit(api, scenario.audit_id)
    assert after["status"] == AUDIT_FINALIZED
    assert after["outcome"] == AUDIT_INCONCLUSIVE
    assert after["discrepancy_score"] is None
    assert after["voided_assessment_count"] == 0
    assert after["version"] == finalized["version"]


# ── The first gate: authentication before anything else ──────────────

@pytest.mark.parametrize("label, headers", _identity_probes())
def test_a_request_without_an_established_identity_is_refused(api, label, headers):
    """No identity, no request — whatever the endpoint would otherwise allow.

    §2.1 refuses a request whose ``X-User-ID`` or ``X-User-Role`` is absent, or
    whose ``X-User-Role`` is not one of the five declared role names, with
    ``ERR_UNAUTHENTICATED``.  §2.8 puts that gate ahead of role authorization and
    ahead of any path-identifier lookup, so an endpoint every role may read is
    refused just the same, and the refusal touches nothing: the very same read,
    carrying an identity, returns the season untouched.

    Design: Corner/errors/unauthenticated_missing_or_unknown_role_header_rejected
    """
    season = fixtures.create_season(api)
    assert season["status"] == SEASON_SETUP

    refused = api.get_season(season["id"], headers)
    validate_error(refused, api_errors.ERR_UNAUTHENTICATED, 401)

    readable = validate_success(api.get_season(season["id"], STATE_OFFICE))
    assert readable["status"] == SEASON_SETUP, label
    assert readable["version"] == season["version"], label


def test_an_undeclared_role_name_authenticates_no_better_than_a_forbidden_one(api):
    """An unknown role is a 401; a declared role off the list is a 403.

    §2.1 draws the line precisely: a role name outside the five declared ones
    fails authentication with ``ERR_UNAUTHENTICATED``, while a well-formed
    identity in a declared role that the endpoint does not list fails
    authorization with ``ERR_UNAUTHORIZED``.  §4 lists the season status endpoint
    for ``StateOffice`` alone, so ``MedicalReviewer`` — a role §4 does admit to
    reading the season — draws the 403.  Neither refusal advances the lifecycle,
    and the state office's identical request then does, incrementing the season's
    ``version`` by exactly one (§3.1).

    Design: Corner/errors/unauthenticated_missing_or_unknown_role_header_rejected
    """
    season = fixtures.create_season(api)
    payload = factories.season_status_payload(SEASON_OPEN)

    unauthenticated = api.set_season_status(season["id"], payload, UNKNOWN_ROLE)
    validate_error(unauthenticated, api_errors.ERR_UNAUTHENTICATED, 401)

    unauthorized = api.set_season_status(season["id"], payload, MEDICAL_REVIEWER)
    validate_error(unauthorized, api_errors.ERR_UNAUTHORIZED, 403)

    untouched = validate_success(api.get_season(season["id"], MEDICAL_REVIEWER))
    assert untouched["status"] == SEASON_SETUP
    assert untouched["version"] == season["version"]

    opened = fixtures.set_season_status(api, season["id"], SEASON_OPEN)
    assert opened["status"] == SEASON_OPEN
    assert opened["version"] == season["version"] + 1
