"""Deficiency ticket due dates, the unit penalty ledger and unit posture.

Every scenario in this module builds its own world from scratch: a single
`Environment of Care` chapter carrying the whole readiness weight, one completed
mock tracer that freezes the unit's base score, and rounding sessions that
ticket deficiencies against it.
"""

from datetime import datetime, timedelta
from typing import Any, Dict

from test_helpers import (
    assign_owner,
    close_rounding_session,
    create_chapter,
    create_standard,
    create_unit,
    make_unit_manager_headers,
    open_rounding_session,
    raise_deficiency,
    record_observation,
    schedule_tracer,
    set_clock,
    tracer_action,
    validate_success,
)

CLOCK = "2026-08-10T00:00:00Z"


# ---------------------------------------------------------------------------
# Private setup chains
# ---------------------------------------------------------------------------

def _setup_unit_scored_78_with_open_eoc_session(
    unit_name: str, bed_count: int
) -> Dict[str, Any]:
    """Chapter EC at weight 100 with two standards, a unit whose single
    COMPLETED tracer froze at a chapter rate of 0.7800 (base score 78.00, band
    CONDITIONAL), the logical clock pinned at 2026-08-10T00:00:00Z and one OPEN
    ENVIRONMENT_OF_CARE rounding session on the unit."""
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    first = create_standard(chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    second = create_standard(chapter["id"], "EC.02.05.01", "Utility systems", "INDIRECT_IMPACT")
    assign_owner(first["id"], "owner-1", "PRIMARY")
    unit = create_unit(unit_name, "ICU", bed_count)
    tracer = schedule_tracer(
        unit["id"],
        chapter["id"],
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T10:00:00Z",
        tracer_type="SYSTEM",
        expected_unit_version=unit["version"],
    )
    set_clock(CLOCK)
    tracer_action(tracer["id"], "START")
    record_observation(tracer["id"], first["id"], "COMPLIANT", 39)
    record_observation(tracer["id"], second["id"], "NON_COMPLIANT", 11)
    tracer = tracer_action(tracer["id"], "COMPLETE")
    session = open_rounding_session(
        unit["id"], "ENVIRONMENT_OF_CARE", "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"
    )
    return {
        "chapter": chapter,
        "first_standard": first,
        "second_standard": second,
        "unit": unit,
        "tracer": tracer,
        "session": session,
    }


def _setup_unassessed_unit_with_closed_life_safety_high_ticket() -> Dict[str, Any]:
    """Unit ED-1 with no tracers at all — so its readiness_band is still
    NOT_ASSESSED — plus one CLOSED LIFE_SAFETY rounding session holding a single
    HIGH ticket, with the logical clock pinned at 2026-08-10T00:00:00Z."""
    chapter = create_chapter("LS", "Life Safety", 25, 1)
    standard = create_standard(
        chapter["id"], "LS.02.01.01", "Sprinkler coverage", "INDIRECT_IMPACT"
    )
    unit = create_unit("ED-1", "ED", 24)
    set_clock(CLOCK)
    session = open_rounding_session(
        unit["id"], "LIFE_SAFETY", "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"
    )
    ticket = raise_deficiency(
        session["id"], standard["id"], "HIGH", "Sprinkler head obstructed"
    )
    session = close_rounding_session(session["id"])
    return {
        "chapter": chapter,
        "standard": standard,
        "unit": unit,
        "session": session,
        "ticket": ticket,
    }


def _instant_delta_days(earlier: str, later: str) -> float:
    parsed_earlier = datetime.strptime(earlier, "%Y-%m-%dT%H:%M:%S.%fZ")
    parsed_later = datetime.strptime(later, "%Y-%m-%dT%H:%M:%S.%fZ")
    return (parsed_later - parsed_earlier) / timedelta(days=1)


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/deficiency_due_at_band_snapshot_precedes_own_penalty
# ---------------------------------------------------------------------------

def test_deficiency_due_at_uses_band_snapshot_taken_before_own_penalty(
    api, safety_officer_headers
):
    """PRD §3.5: "**First**, the server snapshots the unit's `readiness_band` exactly as persisted at the start of the request — this ticket's points are not yet part of `open_deficiency_penalty_points`, so the snapshot does not see itself."
    PRD §3.5: "**Second**, a base allowance is taken from the severity: a `LOW` deficiency gets forty-five days, a `MODERATE` one thirty days, a `HIGH` one fourteen days, and an `IMMEDIATE_THREAT` one a single day."
    PRD §3.5: "**Third**, if the snapshot band was `AT_RISK` or `NOT_READY`, the allowance is halved — specifically, it becomes the larger of one day and the base allowance divided by two with any fraction discarded — and the ticket's `accelerated` flag is set to true; if the snapshot band was `READY`, `CONDITIONAL` or `NOT_ASSESSED`, the allowance stands unchanged and `accelerated` is false."
    PRD §3.5: "**Fourth**, `due_at` is set to the current logical clock plus that many days, counted as exact twenty-four-hour multiples."

    Design: Difficulty/combinatorial_formula/deficiency_due_at_band_snapshot_precedes_own_penalty
    """
    built = _setup_unit_scored_78_with_open_eoc_session("ICU-3", 20)
    session_id = built["session"]["id"]

    first_ticket = validate_success(
        api.create_deficiency(
            session_id,
            {
                "standard_id": built["first_standard"]["id"],
                "description": "Soiled utility room unlocked",
                "severity": "MODERATE",
            },
            safety_officer_headers,
        ),
        201,
    )
    second_ticket = validate_success(
        api.create_deficiency(
            session_id,
            {
                "standard_id": built["first_standard"]["id"],
                "description": "Fire extinguisher inspection overdue",
                "severity": "HIGH",
            },
            safety_officer_headers,
        ),
        201,
    )

    # Snapshot band CONDITIONAL at 78.00: a MODERATE ticket keeps its full
    # thirty-day allowance.
    assert first_ticket["due_at"] == "2026-09-09T00:00:00.000Z"
    assert first_ticket["accelerated"] is False
    # Snapshot band still CONDITIONAL at 75.00 — the first ticket's own three
    # points were absorbed but did not push the band into the accelerating set,
    # so the HIGH ticket keeps its full fourteen days.
    assert second_ticket["due_at"] == "2026-08-24T00:00:00.000Z"
    assert second_ticket["accelerated"] is False


def test_third_deficiency_accelerates_once_prior_ticket_dropped_band_to_at_risk(
    api, safety_officer_headers
):
    """PRD §3.5: "**Third**, if the snapshot band was `AT_RISK` or `NOT_READY`, the allowance is halved — specifically, it becomes the larger of one day and the base allowance divided by two with any fraction discarded — and the ticket's `accelerated` flag is set to true; if the snapshot band was `READY`, `CONDITIONAL` or `NOT_ASSESSED`, the allowance stands unchanged and `accelerated` is false."
    PRD §3.5: "Steps one through four never observe anything written in steps six and seven, even though step seven can push the band into the accelerating set — a second ticket raised immediately afterwards will see that new band, but this one does not."

    Design: Difficulty/combinatorial_formula/deficiency_due_at_band_snapshot_precedes_own_penalty
    """
    built = _setup_unit_scored_78_with_open_eoc_session("ICU-3", 20)
    session_id = built["session"]["id"]

    raise_deficiency(
        session_id, built["first_standard"]["id"], "MODERATE", "Soiled utility room unlocked"
    )
    second_ticket = validate_success(
        api.create_deficiency(
            session_id,
            {
                "standard_id": built["first_standard"]["id"],
                "description": "Fire extinguisher inspection overdue",
                "severity": "HIGH",
            },
            safety_officer_headers,
        ),
        201,
    )
    third_ticket = validate_success(
        api.create_deficiency(
            session_id,
            {
                "standard_id": built["second_standard"]["id"],
                "description": "Medical gas shutoff unlabeled",
                "severity": "HIGH",
            },
            safety_officer_headers,
        ),
        201,
    )

    # Snapshot band AT_RISK at 68.00 halves the fourteen-day allowance to seven.
    assert third_ticket["due_at"] == "2026-08-17T00:00:00.000Z"
    assert third_ticket["accelerated"] is True
    # Two tickets of identical severity, seven days apart, purely because the
    # second one's own insertion moved the band the third one snapshots.
    assert second_ticket["severity"] == "HIGH"
    assert third_ticket["severity"] == "HIGH"
    assert _instant_delta_days(third_ticket["due_at"], second_ticket["due_at"]) == 7


def test_unit_ledger_and_posture_after_three_deficiencies_of_one_session(
    api, safety_officer_headers
):
    """PRD §3.5: "**Sixth**, the ticket is inserted and its points are added to the unit's `open_deficiency_penalty_points`."
    PRD §3.5: "**Seventh** and last, the unit's `readiness_score`, `readiness_band` and `posture` are recomputed."
    PRD §3.3: "The score is the base minus the capped penalty, floored at zero so it can never go negative, rounded half up to two decimal places."
    PRD §3.3: "The band is then read off four thresholds: `READY` at 90.00 or above, `CONDITIONAL` at 75.00 or above, `AT_RISK` at 60.00 or above, and `NOT_READY` below that."
    PRD §3.3: "`OPEN → RESTRICTED` fires automatically whenever the unit's `open_deficiency_penalty_points` changes — on ticket creation, on escalation, on a failed verification — and the resulting total is at least fifteen points."

    Design: Difficulty/combinatorial_formula/deficiency_due_at_band_snapshot_precedes_own_penalty
    """
    built = _setup_unit_scored_78_with_open_eoc_session("ICU-3", 20)
    session_id = built["session"]["id"]

    raise_deficiency(
        session_id, built["first_standard"]["id"], "MODERATE", "Soiled utility room unlocked"
    )
    raise_deficiency(
        session_id,
        built["first_standard"]["id"],
        "HIGH",
        "Fire extinguisher inspection overdue",
    )
    raise_deficiency(
        session_id, built["second_standard"]["id"], "HIGH", "Medical gas shutoff unlabeled"
    )

    unit = validate_success(api.get_unit(built["unit"]["id"], safety_officer_headers))
    assert unit["open_deficiency_penalty_points"] == 17
    assert float(unit["readiness_score"]) == 61.00
    assert unit["readiness_band"] == "AT_RISK"
    assert unit["posture"] == "RESTRICTED"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/posture_restrict_points_exact_fifteen_boundary
# ---------------------------------------------------------------------------

def test_unit_posture_stays_open_at_fourteen_penalty_points(api, safety_officer_headers):
    """PRD §3.4: "Otherwise `tracer_score` is `earned_weight` divided by `scored_weight`, multiplied by one hundred, rounded half up to two decimal places, and `contributes_to_readiness` becomes true."
    PRD §3.3: "`OPEN → RESTRICTED` fires automatically whenever the unit's `open_deficiency_penalty_points` changes — on ticket creation, on escalation, on a failed verification — and the resulting total is at least fifteen points."
    PRD §3.5: "**Fifth**, `penalty_points` is set from the severity — one point for `LOW`, three for `MODERATE`, seven for `HIGH`, fifteen for `IMMEDIATE_THREAT`."
    PRD §3.3: "The band is then read off four thresholds: `READY` at 90.00 or above, `CONDITIONAL` at 75.00 or above, `AT_RISK` at 60.00 or above, and `NOT_READY` below that."

    Design: Difficulty/boundary_precision_check/posture_restrict_points_exact_fifteen_boundary
    """
    built = _setup_unit_scored_78_with_open_eoc_session("ICU-9", 16)
    session_id = built["session"]["id"]
    unit_id = built["unit"]["id"]

    # Thirty-nine of fifty scored weight earned freezes the tracer at 78.00.
    assert float(built["tracer"]["tracer_score"]) == 78.00

    first_ticket = validate_success(
        api.create_deficiency(
            session_id,
            {
                "standard_id": built["first_standard"]["id"],
                "description": "Blocked panel",
                "severity": "HIGH",
            },
            safety_officer_headers,
        ),
        201,
    )
    assert first_ticket["due_at"] == "2026-08-24T00:00:00.000Z"
    assert first_ticket["accelerated"] is False

    at_seven = validate_success(api.get_unit(unit_id, safety_officer_headers))
    assert at_seven["open_deficiency_penalty_points"] == 7
    assert at_seven["posture"] == "OPEN"
    assert float(at_seven["readiness_score"]) == 71.00
    assert at_seven["readiness_band"] == "AT_RISK"

    second_ticket = validate_success(
        api.create_deficiency(
            session_id,
            {
                "standard_id": built["first_standard"]["id"],
                "description": "Eyewash overdue",
                "severity": "HIGH",
            },
            safety_officer_headers,
        ),
        201,
    )
    assert second_ticket["due_at"] == "2026-08-17T00:00:00.000Z"
    assert second_ticket["accelerated"] is True

    # Fourteen points is exactly one point below the restricting threshold.
    at_fourteen = validate_success(api.get_unit(unit_id, safety_officer_headers))
    assert at_fourteen["open_deficiency_penalty_points"] == 14
    assert at_fourteen["posture"] == "OPEN"
    assert float(at_fourteen["readiness_score"]) == 64.00


def test_unit_posture_restricts_at_exactly_fifteen_penalty_points(
    api, safety_officer_headers
):
    """PRD §3.3: "`OPEN → RESTRICTED` fires automatically whenever the unit's `open_deficiency_penalty_points` changes — on ticket creation, on escalation, on a failed verification — and the resulting total is at least fifteen points."
    PRD §3.5: "**Third**, if the snapshot band was `AT_RISK` or `NOT_READY`, the allowance is halved — specifically, it becomes the larger of one day and the base allowance divided by two with any fraction discarded — and the ticket's `accelerated` flag is set to true; if the snapshot band was `READY`, `CONDITIONAL` or `NOT_ASSESSED`, the allowance stands unchanged and `accelerated` is false."
    PRD §3.3: "The score is the base minus the capped penalty, floored at zero so it can never go negative, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/posture_restrict_points_exact_fifteen_boundary
    """
    built = _setup_unit_scored_78_with_open_eoc_session("ICU-9", 16)
    session_id = built["session"]["id"]
    unit_id = built["unit"]["id"]

    raise_deficiency(session_id, built["first_standard"]["id"], "HIGH", "Blocked panel")
    raise_deficiency(session_id, built["first_standard"]["id"], "HIGH", "Eyewash overdue")

    third_ticket = validate_success(
        api.create_deficiency(
            session_id,
            {
                "standard_id": built["second_standard"]["id"],
                "description": "Corridor clutter",
                "severity": "LOW",
            },
            safety_officer_headers,
        ),
        201,
    )
    # Snapshot band AT_RISK halves forty-five days to twenty-two, the fraction
    # discarded.
    assert third_ticket["due_at"] == "2026-09-01T00:00:00.000Z"
    assert third_ticket["accelerated"] is True

    at_fifteen = validate_success(api.get_unit(unit_id, safety_officer_headers))
    assert at_fifteen["open_deficiency_penalty_points"] == 15
    assert at_fifteen["posture"] == "RESTRICTED"
    assert float(at_fifteen["readiness_score"]) == 63.00
    assert at_fifteen["readiness_band"] == "AT_RISK"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/deficiency_ticket_failed_verification_revision_cycle
# ---------------------------------------------------------------------------

def test_failed_verification_returns_ticket_to_open_without_touching_the_ledger(
    api, safety_officer_headers
):
    """PRD §3.5: "**Third**, if the snapshot band was `AT_RISK` or `NOT_READY`, the allowance is halved — specifically, it becomes the larger of one day and the base allowance divided by two with any fraction discarded — and the ticket's `accelerated` flag is set to true; if the snapshot band was `READY`, `CONDITIONAL` or `NOT_ASSESSED`, the allowance stands unchanged and `accelerated` is false."
    PRD §3.5: "It moves a ticket `REMEDIATED → OPEN`, is reserved to the `SafetyOfficer`, and likewise requires the rounding session to be `CLOSED` or fails with `ERR_SESSION_NOT_CLOSED`."
    PRD §3.5: "It increments `failed_verification_count` by one and deliberately leaves the unit's `open_deficiency_penalty_points` untouched, because the ticket never left the non-verified population that the ledger counts."

    Design: Difficulty/non_linear_state_machine/deficiency_ticket_failed_verification_revision_cycle
    """
    built = _setup_unassessed_unit_with_closed_life_safety_high_ticket()
    ticket_id = built["ticket"]["id"]
    unit_id = built["unit"]["id"]
    unit_manager = make_unit_manager_headers(unit_id)

    # Band NOT_ASSESSED never accelerates: a HIGH ticket keeps fourteen days.
    assert built["ticket"]["due_at"] == "2026-08-24T00:00:00.000Z"
    assert built["ticket"]["accelerated"] is False

    validate_success(
        api.transition_deficiency_ticket(ticket_id, {"action": "START_WORK"}, unit_manager)
    )
    validate_success(
        api.transition_deficiency_ticket(ticket_id, {"action": "MARK_REMEDIATED"}, unit_manager)
    )
    failed = validate_success(
        api.transition_deficiency_ticket(
            ticket_id,
            {"action": "FAIL_VERIFICATION", "note": "Obstruction still present"},
            safety_officer_headers,
        )
    )

    assert failed["state"] == "OPEN"
    assert failed["failed_verification_count"] == 1

    unit = validate_success(api.get_unit(unit_id, safety_officer_headers))
    assert unit["open_deficiency_penalty_points"] == 7


def test_revision_cycle_exits_through_verify_and_releases_the_ledger(
    api, safety_officer_headers
):
    """PRD §3.5: "The revision cycle `REMEDIATED → OPEN → IN_PROGRESS → REMEDIATED` may repeat without limit."
    PRD §3.5: "`VERIFY` moves a ticket `REMEDIATED → VERIFIED` and is reserved to the `SafetyOfficer` — a `UnitManager` attempting it is refused, since no unit may verify its own remediation."
    PRD §3.5: "Verification stamps `verified_by_user_id` with the acting principal and releases the ticket's `penalty_points` from the unit's `open_deficiency_penalty_points`."

    Design: Difficulty/non_linear_state_machine/deficiency_ticket_failed_verification_revision_cycle
    """
    built = _setup_unassessed_unit_with_closed_life_safety_high_ticket()
    ticket_id = built["ticket"]["id"]
    unit_id = built["unit"]["id"]
    unit_manager = make_unit_manager_headers(unit_id)

    validate_success(
        api.transition_deficiency_ticket(ticket_id, {"action": "START_WORK"}, unit_manager)
    )
    validate_success(
        api.transition_deficiency_ticket(ticket_id, {"action": "MARK_REMEDIATED"}, unit_manager)
    )
    validate_success(
        api.transition_deficiency_ticket(
            ticket_id,
            {"action": "FAIL_VERIFICATION", "note": "Obstruction still present"},
            safety_officer_headers,
        )
    )
    validate_success(
        api.transition_deficiency_ticket(ticket_id, {"action": "START_WORK"}, unit_manager)
    )
    validate_success(
        api.transition_deficiency_ticket(ticket_id, {"action": "MARK_REMEDIATED"}, unit_manager)
    )
    verified = validate_success(
        api.transition_deficiency_ticket(ticket_id, {"action": "VERIFY"}, safety_officer_headers)
    )

    assert verified["state"] == "VERIFIED"
    assert verified["failed_verification_count"] == 1

    unit = validate_success(api.get_unit(unit_id, safety_officer_headers))
    assert unit["open_deficiency_penalty_points"] == 0
    assert unit["posture"] == "OPEN"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/unit_penalty_ledger_restores_posture_after_verification
# ---------------------------------------------------------------------------

def test_verifying_one_low_ticket_releases_its_point_and_unrestricts_the_unit(
    api, safety_officer_headers
):
    """PRD §2.9: "The **unit penalty ledger** pins `HospitalUnit.open_deficiency_penalty_points` to the sum of `penalty_points` over every deficiency ticket of that unit that has not reached `VERIFIED` — that is, every ticket in `OPEN`, `IN_PROGRESS`, `REMEDIATED` or `ESCALATED`."
    PRD §3.5: "Verification stamps `verified_by_user_id` with the acting principal and releases the ticket's `penalty_points` from the unit's `open_deficiency_penalty_points`."
    PRD §3.3: "`RESTRICTED → OPEN` fires on the verification of a deficiency ticket once the released points leave the total strictly below fifteen, and likewise recomputes the score and band."

    Design: Difficulty/compensating_invariant/unit_penalty_ledger_restores_posture_after_verification
    """
    built = _setup_unit_scored_78_with_open_eoc_session("ICU-9", 16)
    session_id = built["session"]["id"]
    unit_id = built["unit"]["id"]

    raise_deficiency(session_id, built["first_standard"]["id"], "HIGH", "Blocked panel")
    raise_deficiency(session_id, built["first_standard"]["id"], "HIGH", "Eyewash overdue")
    low_ticket = raise_deficiency(
        session_id, built["second_standard"]["id"], "LOW", "Corridor clutter"
    )

    before = validate_success(api.get_unit(unit_id, safety_officer_headers))
    assert before["open_deficiency_penalty_points"] == 15
    assert before["posture"] == "RESTRICTED"
    assert float(before["readiness_score"]) == 63.00

    validate_success(
        api.transition_deficiency_ticket(
            low_ticket["id"], {"action": "START_WORK"}, safety_officer_headers
        )
    )
    validate_success(
        api.transition_deficiency_ticket(
            low_ticket["id"], {"action": "MARK_REMEDIATED"}, safety_officer_headers
        )
    )
    close_rounding_session(session_id)
    verified = validate_success(
        api.transition_deficiency_ticket(
            low_ticket["id"], {"action": "VERIFY"}, safety_officer_headers
        )
    )
    assert verified["state"] == "VERIFIED"

    after = validate_success(api.get_unit(unit_id, safety_officer_headers))
    assert after["open_deficiency_penalty_points"] == 14
    assert after["posture"] == "OPEN"
    assert float(after["readiness_score"]) == 64.00
    assert after["readiness_band"] == "AT_RISK"


def test_verification_leaves_the_remaining_non_verified_tickets_untouched(
    api, safety_officer_headers
):
    """PRD §2.9: "The **unit penalty ledger** pins `HospitalUnit.open_deficiency_penalty_points` to the sum of `penalty_points` over every deficiency ticket of that unit that has not reached `VERIFIED` — that is, every ticket in `OPEN`, `IN_PROGRESS`, `REMEDIATED` or `ESCALATED`."
    PRD §2.9: "Raising a ticket adds its points; verifying a ticket removes them; escalating a ticket that gains severity replaces its old contribution with the new one."

    Design: Difficulty/compensating_invariant/unit_penalty_ledger_restores_posture_after_verification
    """
    built = _setup_unit_scored_78_with_open_eoc_session("ICU-9", 16)
    session_id = built["session"]["id"]
    unit_id = built["unit"]["id"]

    first_high = raise_deficiency(
        session_id, built["first_standard"]["id"], "HIGH", "Blocked panel"
    )
    second_high = raise_deficiency(
        session_id, built["first_standard"]["id"], "HIGH", "Eyewash overdue"
    )
    low_ticket = raise_deficiency(
        session_id, built["second_standard"]["id"], "LOW", "Corridor clutter"
    )

    validate_success(
        api.transition_deficiency_ticket(
            low_ticket["id"], {"action": "START_WORK"}, safety_officer_headers
        )
    )
    validate_success(
        api.transition_deficiency_ticket(
            low_ticket["id"], {"action": "MARK_REMEDIATED"}, safety_officer_headers
        )
    )
    close_rounding_session(session_id)
    validate_success(
        api.transition_deficiency_ticket(
            low_ticket["id"], {"action": "VERIFY"}, safety_officer_headers
        )
    )

    first_after = validate_success(
        api.get_deficiency_ticket(first_high["id"], safety_officer_headers)
    )
    second_after = validate_success(
        api.get_deficiency_ticket(second_high["id"], safety_officer_headers)
    )
    assert first_after["state"] == "OPEN"
    assert second_after["state"] == "OPEN"

    unit = validate_success(api.get_unit(unit_id, safety_officer_headers))
    # Exactly the severity sum of the two remaining non-VERIFIED HIGH tickets.
    assert unit["open_deficiency_penalty_points"] == (
        first_after["penalty_points"] + second_after["penalty_points"]
    )
    assert unit["open_deficiency_penalty_points"] == 14
