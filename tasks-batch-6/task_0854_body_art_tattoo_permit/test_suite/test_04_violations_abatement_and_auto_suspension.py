"""Citing violations, the abatement cycle and the auto-suspension cascade."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    assert_violation,
    cite_violation,
    create_active_artist,
    create_permitted_establishment,
    decide_correction,
    read_establishment,
    schedule_inspection,
    set_clock,
    start_inspection_at,
    submit_correction,
    validate_paginated,
    validate_success,
)

HO = TEST_USERS["health_officer_headers"]
INSP = TEST_USERS["inspector_headers"]
CLERK = TEST_USERS["records_clerk_headers"]


def _issued_noncritical_violation(name: str, address: str):
    establishment = create_permitted_establishment(name=name, street_address=address)
    inspection = start_inspection_at(
        establishment["id"], "2026-05-05T00:00:00Z", "2026-05-05T02:00:00Z"
    )
    violation = cite_violation(
        inspection["id"], "STER_004", "NONCRITICAL", "Autoclave log gap."
    )
    return establishment, inspection, violation


def test_correction_rejected_before_the_deadline_returns_the_citation_to_issued(api):
    """PRD §3.4: "The abatement deadline is computed at creation and written to
    `abatement_due_at`. A `CRITICAL` citation must be abated within 3 days of
    `issued_at`; a `NONCRITICAL` citation gets 14 days."
    PRD §3.4: "Rejected strictly before `abatement_due_at`, the citation returns
    `CORRECTION_SUBMITTED → ISSUED` with `correction_note` and
    `correction_submitted_at` cleared back to null and the establishment's counters
    untouched — this is the revision loop, and it may repeat as many times as the
    operator can manage while the deadline holds."

    Design: Difficulty/non_linear_state_machine/violation_correction_reject_cycles_back_to_issued
    """
    establishment, _inspection, violation = _issued_noncritical_violation(
        "Loop Ink", "3 Birch Ln"
    )
    assert_violation(violation)
    assert_instant_equals(
        violation["abatement_due_at"], "2026-05-19T00:00:00Z", "abatement_due_at"
    )

    submit_correction(violation["id"], establishment["id"], "First attempt at correction.")
    rejected = decide_correction(violation["id"], "REJECT")

    assert rejected["status"] == "ISSUED"
    assert rejected["correction_note"] is None
    assert rejected["correction_submitted_at"] is None


def test_second_correction_after_a_rejection_can_still_be_verified(api):
    """PRD §3.4: "The owning `EstablishmentOperator` submits a `correction_note`
    describing the corrective action taken, which drives the citation `ISSUED →
    CORRECTION_SUBMITTED` and stamps `correction_submitted_at` with the current
    logical-clock instant."
    PRD §3.4: "A verification drives `CORRECTION_SUBMITTED → VERIFIED`, which removes
    the row from the open set: `open_violation_count` and
    `open_critical_violation_count` are recomputed, `risk_score` and
    `operating_posture` follow, and the establishment's `version` increments by one."

    Design: Difficulty/non_linear_state_machine/violation_correction_reject_cycles_back_to_issued
    """
    establishment, _inspection, violation = _issued_noncritical_violation(
        "Loop Ink Two", "4 Birch Ln"
    )
    submit_correction(violation["id"], establishment["id"], "First attempt at correction.")
    decide_correction(violation["id"], "REJECT")

    resubmitted = submit_correction(
        violation["id"], establishment["id"], "Second attempt, log rebuilt."
    )
    assert resubmitted["status"] == "CORRECTION_SUBMITTED"

    verified = decide_correction(violation["id"], "VERIFY")
    assert verified["status"] == "VERIFIED"

    parent = read_establishment(establishment["id"])
    assert parent["open_violation_count"] == 0
    assert parent["risk_score"] == 25


def test_issuing_a_violation_moves_the_open_counters_and_the_risk_figure(api):
    """PRD §3.4: "**Hop one:** the establishment's `open_violation_count` and
    `open_critical_violation_count` are recomputed."
    PRD §3.7: "The open-non-critical term contributes 5 points for each violation in
    the open set that is not critical — that is, for the difference between
    `open_violation_count` and `open_critical_violation_count`."

    Design: Difficulty/compensating_invariant/violation_issue_then_verified_correction_returns_open_counts_to_baseline
    """
    establishment = create_permitted_establishment(
        name="Counter Ink", street_address="17 Alder St"
    )
    baseline = read_establishment(establishment["id"])
    assert baseline["open_violation_count"] == 0
    assert baseline["risk_score"] == 25

    inspection = start_inspection_at(
        establishment["id"], "2026-05-05T00:00:00Z", "2026-05-05T02:00:00Z"
    )
    cite_violation(inspection["id"], "STER_004", "NONCRITICAL", "Autoclave log gap.")

    after_issue = read_establishment(establishment["id"])
    assert after_issue["open_violation_count"] == 1
    assert after_issue["risk_score"] == 30, (
        f"25 sterilization points plus one open non-critical, got {after_issue['risk_score']}"
    )


def test_issue_then_verified_correction_returns_the_counters_to_baseline(api):
    """PRD §3.4: "Submitting a correction changes nothing about the establishment's
    counters, because `CORRECTION_SUBMITTED` is still an open status — the shop does
    not get credit for claiming a fix, only for having one verified."
    PRD §3.4: "A verification drives `CORRECTION_SUBMITTED → VERIFIED`, which removes
    the row from the open set: `open_violation_count` and
    `open_critical_violation_count` are recomputed, `risk_score` and
    `operating_posture` follow, and the establishment's `version` increments by one."

    Design: Difficulty/compensating_invariant/violation_issue_then_verified_correction_returns_open_counts_to_baseline
    """
    establishment, _inspection, violation = _issued_noncritical_violation(
        "Counter Ink Two", "18 Alder St"
    )

    submitted = submit_correction(
        violation["id"], establishment["id"], "Log rebuilt from device printouts."
    )
    assert submitted["status"] == "CORRECTION_SUBMITTED"
    during = read_establishment(establishment["id"])
    assert during["open_violation_count"] == 1, "CORRECTION_SUBMITTED is still open"

    verified = decide_correction(violation["id"], "VERIFY")
    assert verified["status"] == "VERIFIED"

    parent = read_establishment(establishment["id"])
    assert parent["open_violation_count"] == 0
    assert parent["open_critical_violation_count"] == 0
    assert parent["risk_score"] == 25, "Exactly the pre-issuance figure"
    assert parent["operating_posture"] == "OPEN"


def _cascade_scenario():
    """ACTIVE premises with one ACTIVE artist, an IN_PROGRESS visit already carrying
    three critical citations and a second ROUTINE visit still SCHEDULED."""
    establishment = create_permitted_establishment(
        name="Cascade Custom", street_address="5 Willow Way"
    )
    artist = create_active_artist(establishment["id"], "Nova Reed")
    later = schedule_inspection(
        establishment["id"],
        inspection_type="ROUTINE",
        scheduled_start_at="2026-06-01T00:00:00Z",
        scheduled_end_at="2026-06-01T02:00:00Z",
    )
    inspection = start_inspection_at(
        establishment["id"], "2026-05-05T00:00:00Z", "2026-05-05T02:00:00Z"
    )
    for code, text in (
        ("BBP_001", "Sharps container overfull."),
        ("BBP_002", "No single-use needle documentation."),
        ("BBP_003", "Reused ink caps observed."),
    ):
        cite_violation(inspection["id"], code, "CRITICAL", text)
    return establishment, artist, inspection, later


def test_fourth_critical_citation_auto_generates_a_suspension(api):
    """PRD §3.4: "**Hop three:** because the risk figure moved, the suspension breakpoint
    is tested — when `risk_score` has reached 80 or higher and no enforcement action
    against that establishment is currently `ACTIVE`, the system creates one of its
    own: `subject_type` `ESTABLISHMENT`, `action_type` `SUSPENSION`, `reason_code`
    `RISK_THRESHOLD`, `auto_generated` true and `issued_by_user_id` set to the literal
    string `SYSTEM`."
    PRD §3.4: "**Hop four:** because that action is `ACTIVE`, the establishment transitions
    `ACTIVE → SUSPENDED` and its `operating_posture` becomes `CLOSED`."
    PRD §3.7: "The open-critical term contributes 15 points for each violation counted
    in `open_critical_violation_count`."

    Design: Difficulty/transitive_cascade/fourth_critical_violation_cascades_to_auto_suspension_artist_and_inspection_fallout
    """
    establishment, _artist, inspection, _later = _cascade_scenario()

    fourth = cite_violation(
        inspection["id"], "BBP_004", "CRITICAL", "Autoclave inoperable."
    )
    assert fourth["status"] == "ISSUED"

    parent = read_establishment(establishment["id"])
    assert parent["open_critical_violation_count"] == 4
    assert parent["open_violation_count"] == 4
    assert parent["risk_score"] == 85, (
        f"25 sterilization points plus 4 x 15 open critical, got {parent['risk_score']}"
    )
    assert parent["permit_status"] == "SUSPENDED"
    assert parent["operating_posture"] == "CLOSED"

    rows, meta = validate_paginated(
        api.list_enforcement_actions(
            HO, params={"establishment_id": establishment["id"]}
        )
    )
    assert meta["total_count"] == 1, f"Expected exactly one action, got {meta['total_count']}"
    action = rows[0]
    assert action["auto_generated"] is True
    assert action["action_type"] == "SUSPENSION"
    assert action["reason_code"] == "RISK_THRESHOLD"
    assert action["issued_by_user_id"] == "SYSTEM"
    assert action["status"] == "ACTIVE"


def test_auto_suspension_deactivates_the_roster_and_cancels_routine_visits(api):
    """PRD §3.4: "**Hop five:** because the establishment became `SUSPENDED`, every artist
    there holding `ACTIVE` or `PROBATION` drops to `INACTIVE` and every `SCHEDULED`
    `ROUTINE` inspection there is `CANCELLED`, with `active_artist_count` recomputed
    and the establishment's `version` incremented."
    PRD §3.3: "When an establishment is suspended out of `ACTIVE`, every one of its
    inspections that is still `SCHEDULED` and whose `inspection_type` is `ROUTINE`
    moves `SCHEDULED → CANCELLED`, in ascending `created_at` order, each bumping its
    own `version` by one."

    Design: Difficulty/transitive_cascade/fourth_critical_violation_cascades_to_auto_suspension_artist_and_inspection_fallout
    """
    establishment, artist, inspection, later = _cascade_scenario()

    cite_violation(inspection["id"], "BBP_004", "CRITICAL", "Autoclave inoperable.")

    parent = read_establishment(establishment["id"])
    assert parent["active_artist_count"] == 0

    stored_artist = validate_success(api.get_artist(artist["id"], HO))
    assert stored_artist["permit_status"] == "INACTIVE"

    cancelled = validate_success(api.get_inspection(later["id"], HO))
    assert cancelled["status"] == "CANCELLED"

    ongoing = validate_success(api.get_inspection(inspection["id"], HO))
    assert ongoing["status"] == "IN_PROGRESS", (
        "Only SCHEDULED ROUTINE visits are cancelled by the suspension"
    )


def test_violation_list_filters_by_inspection_and_severity(api):
    """PRD §3.4: "Individual citations are readable, and the collection accepts filters
    on `inspection_id`, `status` and `severity`."
    PRD §2.3: "For list responses the `meta` object carries `limit` and `offset`
    echoing the effective values, `total_count` giving the number of rows matching the
    filters before pagination is applied, and `has_more` indicating whether any
    further rows remain beyond the current page."

    Design: Corner/endpoints/violations_filtered_list_by_inspection_with_pagination
    """
    establishment = create_permitted_establishment(
        name="Filter Ink", street_address="40 Fortieth St"
    )
    inspection = start_inspection_at(
        establishment["id"], "2026-05-05T00:00:00Z", "2026-05-05T02:00:00Z"
    )
    cite_violation(inspection["id"], "STER_004", "NONCRITICAL", "Autoclave log gap.")
    cite_violation(inspection["id"], "HAND_002", "NONCRITICAL", "Soap dispenser empty.")
    critical = cite_violation(
        inspection["id"], "BBP_001", "CRITICAL", "Sharps container overfull."
    )

    rows, meta = validate_paginated(
        api.list_violations(
            CLERK, params={"inspection_id": inspection["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert all(row["inspection_id"] == inspection["id"] for row in rows)

    crit_rows, crit_meta = validate_paginated(
        api.list_violations(
            CLERK, params={"inspection_id": inspection["id"], "severity": "CRITICAL"}
        )
    )
    assert crit_meta["total_count"] == 1
    assert crit_rows[0]["id"] == critical["id"]


def test_risk_score_of_exactly_sixty_flips_the_posture_to_restricted(api):
    """PRD §2.11: "Otherwise the permit is `ACTIVE`, and the posture is `RESTRICTED`
    when either the `risk_score` has reached 60 or higher, or the
    `open_critical_violation_count` is greater than zero."
    PRD §3.7: "The open-non-critical term contributes 5 points for each violation in
    the open set that is not critical — that is, for the difference between
    `open_violation_count` and `open_critical_violation_count`."

    Design: Corner/cross_cutting_complexity_layers/risk_threshold_flips_posture_at_exactly_sixty
    """
    establishment = create_permitted_establishment(
        name="Threshold Sixty Ink", street_address="55 Fiftyfifth St"
    )
    inspection = start_inspection_at(
        establishment["id"], "2026-05-05T00:00:00Z", "2026-05-05T02:00:00Z"
    )
    for code in ("STER_004", "HAND_002", "SIGN_001", "WASTE_003", "TOWEL_005", "FLOOR_006"):
        cite_violation(inspection["id"], code, "NONCRITICAL", f"{code} observed.")

    six = read_establishment(establishment["id"])
    assert six["risk_score"] == 55
    assert six["operating_posture"] == "OPEN"

    cite_violation(
        inspection["id"], "LIGHT_007", "NONCRITICAL", "Insufficient task lighting."
    )

    seven = read_establishment(establishment["id"])
    assert seven["risk_score"] == 60
    assert seven["operating_posture"] == "RESTRICTED", (
        "60 is the restricted breakpoint, so the comparison must admit equality"
    )
    assert seven["open_violation_count"] == 7
    assert seven["open_critical_violation_count"] == 0
    assert seven["permit_status"] == "ACTIVE", "60 is below the suspension breakpoint of 80"


def test_clock_sweep_escalates_an_overdue_issued_citation(api):
    """PRD §3.4: "When the logical clock is advanced, the second step of the sweep
    visits every violation still sitting in `ISSUED` whose `abatement_due_at` is at or
    before the new instant and moves it `ISSUED → ESCALATED`, processing rows in
    ascending `created_at` order, recomputing the owning establishment's `risk_score`
    and `operating_posture` for each, and appending each identifier to the
    `escalated_violation_ids` array in the sweep response."
    PRD §3.4: "The open set is defined across every violation reachable through that
    establishment's inspections whose status is `ISSUED`, `CORRECTION_SUBMITTED` or
    `ESCALATED`, with the critical counter restricted further to rows whose `severity`
    is `CRITICAL`; no time window applies to either count."

    Design: Corner/state_machines/clock_sweep_escalates_overdue_issued_violation
    """
    establishment = create_permitted_establishment(
        name="Overdue Ink", street_address="16 Sixteenth St"
    )
    inspection = start_inspection_at(
        establishment["id"], "2026-05-05T00:00:00Z", "2026-05-05T02:00:00Z"
    )
    violation = cite_violation(
        inspection["id"], "BBP_001", "CRITICAL", "Sharps container overfull."
    )
    assert_instant_equals(
        violation["abatement_due_at"], "2026-05-08T00:00:00Z", "abatement_due_at"
    )

    sweep = set_clock("2026-05-08T00:00:00Z")
    assert_instant_equals(sweep["current_utc"], "2026-05-08T00:00:00Z", "current_utc")
    assert violation["id"] in sweep["escalated_violation_ids"]

    stored = validate_success(api.get_violation(violation["id"], HO))
    assert stored["status"] == "ESCALATED"

    parent = read_establishment(establishment["id"])
    assert parent["open_violation_count"] == 1, "ESCALATED remains inside the open set"
    assert parent["open_critical_violation_count"] == 1
    assert parent["risk_score"] == 40
    assert parent["operating_posture"] == "RESTRICTED"
