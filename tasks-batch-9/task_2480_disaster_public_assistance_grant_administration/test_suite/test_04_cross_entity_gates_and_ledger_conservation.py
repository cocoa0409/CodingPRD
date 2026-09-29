"""Cross-entity state gates and the two conserved ledger quantities.

Each blocked operation is exercised twice: once against the blocking
cross-entity state (proving the exact error identifier and that no ledger
field moved) and once with that blocking state cleared (proving the very
same call is otherwise admissible).
"""
from datetime import datetime, timedelta

from test_helpers import (
    GRANTS_OFFICER_USER_ID,
    SECOND_GRANTS_OFFICER_USER_ID,
    ApiErrorId,
    close_obligations,
    cost_review,
    deobligation_payload,
    drawdown_payload,
    finalize_deobligation,
    get_applicant,
    get_deobligation,
    get_disaster,
    get_drawdown,
    get_project,
    make_admin_headers,
    make_applicant_agent_headers,
    make_grants_officer_headers,
    setup_obligated_project,
    setup_paid_drawdown,
    setup_proposed_deobligation,
    setup_submitted_project,
    setup_validated_project,
    validate_error,
    validate_paginated,
    validate_success,
)

# The declaration every scenario below is built under: a 0.75 federal share and
# the forty-thousand-dollar small-project threshold.
DECLARATION_START_AT = "2026-06-10T00:00:00Z"
DECLARATION_END_AT = "2026-06-25T00:00:00Z"
CLOCK_AT = "2026-07-01T00:00:00Z"

# One MATERIALS claim of $38,000 documented inside the incident period.  Reviewed
# it lands ALLOWED at 3,800,000 cents, which is the repair basis at cost review.
DOCUMENTED_LINES = [
    {
        "cost_type": "MATERIALS",
        "claimed_cents": 3_800_000,
        "work_start_at": "2026-06-12T08:00:00Z",
        "work_end_at": "2026-06-12T17:00:00Z",
    }
]

# A $38,000 repair basis is SMALL, so the mitigation cap is 20 percent of it —
# 760,000 cents — and the obligated federal share is
# round(3,800,000 x 0.75) + round(760,000 x 0.75) = 2,850,000 + 570,000.
OBLIGATED_SHARE_CENTS = 3_420_000

PROJECT_TITLE = "Pump station intake rebuild"
PROJECT_SCOPE = "Rebuild intake structure"


def _disaster_overrides(declaration_number: str) -> dict:
    return {
        "declaration_number": declaration_number,
        "state_code": "TX",
        "incident_type": "FLOOD",
        "incident_start_at": DECLARATION_START_AT,
        "incident_end_at": DECLARATION_END_AT,
        "population": 900_000,
        "federal_cost_share_pct": 0.75,
        "small_project_threshold_cents": 4_000_000,
    }


def _project_overrides(mitigation_requested_cents: int) -> dict:
    return {
        "category": "C",
        "title": PROJECT_TITLE,
        "scope_of_work": PROJECT_SCOPE,
        "estimated_repair_cost_cents": 5_000_000,
        "mitigation_requested_cents": mitigation_requested_cents,
    }


def _instant(value: str) -> datetime:
    """Parse one of the server's ISO 8601 UTC instants."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Project -> Disaster: obligation is refused once the declaration is closed
# ---------------------------------------------------------------------------
def test_obligate_refused_once_declaration_closed_to_obligations(api):
    """PRD §3.1: "Once closed, both project submission and project obligation
    under that declaration fail with `ERR_DISASTER_NOT_OPEN` — a `VALIDATED`
    project that missed the window can no longer be funded."

    PRD §3.7: "The project must be `VALIDATED`, the declaration must still be
    `DECLARED` (`ERR_DISASTER_NOT_OPEN`), and the obtain-and-maintain flood
    insurance bar of §3.6 must be satisfied (`ERR_INSURANCE_REQUIREMENT_UNMET`)."

    Design: Difficulty/cross_entity_state_dependency/project_obligate_blocked_by_closed_declaration
    """
    scenario = setup_validated_project(
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4917"),
        project_overrides=_project_overrides(0),
    )
    disaster_id = scenario["disaster"]["id"]
    applicant_id = scenario["applicant"]["id"]
    project_id = scenario["project"]["id"]

    # A project waiting in VALIDATED is not an open review, so the declaration
    # closes over it.
    closed = close_obligations(disaster_id)
    assert closed["status"] == "OBLIGATION_CLOSED", (
        f"Expected OBLIGATION_CLOSED, got {closed['status']} after close-obligations"
    )

    before_project = get_project(project_id)

    response = api.obligate_project(
        project_id, make_grants_officer_headers()
    )
    validate_error(response, ApiErrorId.ERR_DISASTER_NOT_OPEN)

    after_project = get_project(project_id)
    assert after_project["status"] == "VALIDATED", (
        f"Expected VALIDATED, got {after_project['status']} after the refused obligate"
    )
    assert after_project["federal_share_obligated_cents"] == 0, (
        "Expected 0, got "
        f"{after_project['federal_share_obligated_cents']} federal_share_obligated_cents "
        "after the refused obligate"
    )
    assert after_project["obligated_by_user_id"] is None, (
        f"Expected null obligated_by_user_id, got {after_project['obligated_by_user_id']!r}"
    )
    assert after_project["version"] == before_project["version"], (
        f"Expected project version {before_project['version']}, got {after_project['version']} "
        "after the refused obligate"
    )

    applicant = get_applicant(applicant_id)
    assert applicant["total_obligated_cents"] == 0, (
        f"Expected 0, got {applicant['total_obligated_cents']} total_obligated_cents "
        "after the refused obligate"
    )
    assert applicant["available_drawdown_cents"] == 0, (
        f"Expected 0, got {applicant['available_drawdown_cents']} available_drawdown_cents "
        "after the refused obligate"
    )

    disaster = get_disaster(disaster_id)
    assert disaster["total_obligated_cents"] == 0, (
        f"Expected 0, got {disaster['total_obligated_cents']} declaration "
        "total_obligated_cents after the refused obligate"
    )


def test_obligate_succeeds_while_declaration_still_declared(api):
    """PRD §3.7: "The project must be `VALIDATED`, the declaration must still be
    `DECLARED` (`ERR_DISASTER_NOT_OPEN`), and the obtain-and-maintain flood
    insurance bar of §3.6 must be satisfied (`ERR_INSURANCE_REQUIREMENT_UNMET`)."

    PRD §3.7: "Then the repair share is that net repair figure multiplied by the
    declaration's `federal_cost_share_pct` and rounded half up to whole cents,
    **and separately** the mitigation share is `mitigation_approved_cents`
    multiplied by the same `federal_cost_share_pct` and rounded half up to whole
    cents."

    Design: Difficulty/cross_entity_state_dependency/project_obligate_blocked_by_closed_declaration
    """
    scenario = setup_validated_project(
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4917"),
        project_overrides=_project_overrides(0),
    )
    disaster_id = scenario["disaster"]["id"]
    applicant_id = scenario["applicant"]["id"]
    project_id = scenario["project"]["id"]

    assert get_disaster(disaster_id)["status"] == "DECLARED", (
        "The declaration must still be DECLARED for the positive control"
    )

    project = validate_success(
        api.obligate_project(project_id, make_grants_officer_headers())
    )
    assert project["status"] == "OBLIGATED", (
        f"Expected OBLIGATED, got {project['status']} after obligate"
    )
    # The basis fell back to the 5,000,000-cent estimate with no mitigation, so
    # round(5,000,000 x 0.75) + round(0 x 0.75) = 3,750,000.
    assert project["federal_share_obligated_cents"] == 3_750_000, (
        f"Expected 3750000, got {project['federal_share_obligated_cents']} after obligate"
    )

    applicant = get_applicant(applicant_id)
    assert applicant["total_obligated_cents"] == 3_750_000, (
        f"Expected 3750000, got {applicant['total_obligated_cents']} total_obligated_cents "
        "after obligate"
    )
    assert get_disaster(disaster_id)["total_obligated_cents"] == 3_750_000, (
        "Expected 3750000 declaration total_obligated_cents after obligate"
    )


# ---------------------------------------------------------------------------
# Drawdown -> Applicant: cash cannot be requested while drawdowns are suspended
# ---------------------------------------------------------------------------
def test_drawdown_creation_refused_while_applicant_drawdowns_suspended(api):
    """PRD §3.8: "The applicant must be `ELIGIBLE`
    (`ERR_APPLICANT_NOT_ELIGIBLE`); the referenced project must be `OBLIGATED`
    (`ERR_PROJECT_INVALID_STATE`); the project must belong to the same applicant
    as the drawdown (`ERR_CROSS_APPLICANT_REFERENCE`); the applicant's
    `drawdown_status` must be `ACTIVE` (`ERR_DRAWDOWN_SUSPENDED`); and
    `requested_cents` must not exceed `available_drawdown_cents`, where equality
    is expressly allowed — drawing the last available cent is legitimate — with
    an excess rejected as `ERR_DRAWDOWN_EXCEEDS_AVAILABLE` and the
    payment-required status 402."

    PRD §3.8: "After **every** recomputation, `drawdown_status` is set to
    `SUSPENDED` whenever `delinquent_report_count` is greater than 0 or
    `pending_deobligation_cents` is greater than 0, and to `ACTIVE` whenever both
    are exactly 0."

    Design: Difficulty/cross_entity_state_dependency/drawdown_creation_blocked_by_suspended_applicant
    """
    scenario = setup_proposed_deobligation(
        500_000,
        reason="PROCUREMENT_NONCOMPLIANCE",
        headers=make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4918"),
        project_overrides=_project_overrides(900_000),
        line_items=DOCUMENTED_LINES,
    )
    disaster_id = scenario["disaster"]["id"]
    applicant_id = scenario["applicant"]["id"]
    project_id = scenario["project"]["id"]
    deobligation_id = scenario["deobligation"]["id"]

    before = get_applicant(applicant_id)
    assert before["pending_deobligation_cents"] == 500_000, (
        f"Expected 500000, got {before['pending_deobligation_cents']} pending_deobligation_cents"
    )
    assert before["drawdown_status"] == "SUSPENDED", (
        f"Expected SUSPENDED, got {before['drawdown_status']} after the PROPOSED determination"
    )
    # Availability is untouched by a merely proposed determination, so the
    # requested cash is well inside it and only the suspension can bite.
    assert before["available_drawdown_cents"] == OBLIGATED_SHARE_CENTS, (
        f"Expected {OBLIGATED_SHARE_CENTS}, got {before['available_drawdown_cents']} "
        "available_drawdown_cents"
    )

    response = api.create_drawdown(
        drawdown_payload(applicant_id, project_id, 100_000, before["version"]),
        make_applicant_agent_headers(applicant_id),
    )
    validate_error(response, ApiErrorId.ERR_DRAWDOWN_SUSPENDED)

    rows, meta = validate_paginated(api.list_drawdowns(make_admin_headers()))
    assert meta["total_count"] == 0, (
        f"Expected 0 drawdown rows, got {meta['total_count']} after the refused request"
    )
    assert rows == [], f"Expected no drawdown rows, got {rows}"

    after = get_applicant(applicant_id)
    assert after["total_drawn_cents"] == 0, (
        f"Expected 0, got {after['total_drawn_cents']} total_drawn_cents after the refused request"
    )
    assert after["cash_on_hand_cents"] == 0, (
        f"Expected 0, got {after['cash_on_hand_cents']} cash_on_hand_cents after the refused request"
    )
    assert after["available_drawdown_cents"] == OBLIGATED_SHARE_CENTS, (
        f"Expected {OBLIGATED_SHARE_CENTS}, got {after['available_drawdown_cents']} "
        "available_drawdown_cents after the refused request"
    )
    assert after["version"] == before["version"], (
        f"Expected applicant version {before['version']}, got {after['version']} "
        "after the refused request"
    )

    assert get_deobligation(deobligation_id)["status"] == "PROPOSED", (
        "The blocking determination must still be PROPOSED"
    )
    assert get_disaster(disaster_id)["total_drawn_cents"] == 0, (
        "Expected 0 declaration total_drawn_cents after the refused request"
    )


def test_drawdown_creation_succeeds_once_suspension_lifted(api):
    """PRD §3.9: "Because `deobligated_cents` moved, the applicant's
    `total_obligated_cents`, `pending_deobligation_cents` and
    `available_drawdown_cents` are recomputed; because the applicant's pending
    figure has returned to 0 and `delinquent_report_count` is also 0,
    `drawdown_status` returns to `ACTIVE` and the declaration's
    `suspended_applicant_count` is recomputed; the declaration's
    `total_obligated_cents` is recomputed as well."

    PRD §3.8: "A created drawdown sits in `REQUESTED` with `approved_cents` 0,
    `refunded_cents` 0, `disbursed_by_user_id` null and `rejection_reason` null,
    and the create increments the applicant's `version` by 1 — which is why a
    client intending to file two drawdowns in a row must re-read the applicant
    between them."

    Design: Difficulty/cross_entity_state_dependency/drawdown_creation_blocked_by_suspended_applicant
    """
    scenario = setup_proposed_deobligation(
        500_000,
        reason="PROCUREMENT_NONCOMPLIANCE",
        headers=make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4918"),
        project_overrides=_project_overrides(900_000),
        line_items=DOCUMENTED_LINES,
    )
    applicant_id = scenario["applicant"]["id"]
    project_id = scenario["project"]["id"]

    # Clear the blocking cross-entity state: finalizing the determination drops
    # pending_deobligation_cents back to 0, which reactivates drawdowns.
    finalize_deobligation(scenario["deobligation"]["id"])

    applicant = get_applicant(applicant_id)
    assert applicant["pending_deobligation_cents"] == 0, (
        f"Expected 0, got {applicant['pending_deobligation_cents']} pending_deobligation_cents "
        "after finalization"
    )
    assert applicant["drawdown_status"] == "ACTIVE", (
        f"Expected ACTIVE, got {applicant['drawdown_status']} after finalization"
    )

    drawdown = validate_success(
        api.create_drawdown(
            drawdown_payload(applicant_id, project_id, 100_000, applicant["version"]),
            make_applicant_agent_headers(applicant_id),
        ),
        expected_status=201,
    )
    assert drawdown["status"] == "REQUESTED", (
        f"Expected REQUESTED, got {drawdown['status']} after the accepted request"
    )
    assert drawdown["requested_cents"] == 100_000, (
        f"Expected 100000, got {drawdown['requested_cents']} requested_cents"
    )
    assert drawdown["approved_cents"] == 0, (
        f"Expected 0, got {drawdown['approved_cents']} approved_cents on a new drawdown"
    )
    assert drawdown["disbursed_by_user_id"] is None, (
        f"Expected null disbursed_by_user_id, got {drawdown['disbursed_by_user_id']!r}"
    )


# ---------------------------------------------------------------------------
# Appeal -> Deobligation: only a FINAL determination is appealable
# ---------------------------------------------------------------------------
def test_appeal_refused_against_still_proposed_determination(api):
    """PRD §3.9: "Only a `FINAL` determination is appealable — a `PROPOSED` or
    `REVERSED` one yields `ERR_DEOBLIGATION_NOT_FINAL` — and `filed_at`, stamped
    from the logical clock, must be at or before the determination's
    `appeal_deadline_at`, with a clock instant exactly equal to the deadline
    still inside the window and anything later rejected as
    `ERR_APPEAL_WINDOW_EXPIRED`."

    PRD §3.9: "A new determination sits in `PROPOSED` with
    `determined_by_user_id` recording the acting user, `finalized_at` null,
    `appeal_deadline_at` null and `reversed_cents` 0."

    Design: Difficulty/cross_entity_state_dependency/appeal_filing_blocked_by_unfinalized_determination
    """
    scenario = setup_proposed_deobligation(
        500_000,
        reason="SCOPE_REDUCTION",
        headers=make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4919"),
        project_overrides=_project_overrides(900_000),
        line_items=DOCUMENTED_LINES,
    )
    applicant_id = scenario["applicant"]["id"]
    project_id = scenario["project"]["id"]
    deobligation_id = scenario["deobligation"]["id"]

    before = get_deobligation(deobligation_id)
    assert before["status"] == "PROPOSED", (
        f"Expected PROPOSED, got {before['status']} before the appeal attempt"
    )
    assert before["finalized_at"] is None, (
        f"Expected null finalized_at, got {before['finalized_at']!r} on a PROPOSED determination"
    )
    assert before["appeal_deadline_at"] is None, (
        f"Expected null appeal_deadline_at, got {before['appeal_deadline_at']!r} "
        "on a PROPOSED determination"
    )

    response = api.create_appeal(
        {
            "deobligation_id": deobligation_id,
            "grounds": "The reduced scope was approved in writing",
            "relief_requested_cents": 500_000,
        },
        make_applicant_agent_headers(applicant_id),
    )
    validate_error(response, ApiErrorId.ERR_DEOBLIGATION_NOT_FINAL)

    rows, meta = validate_paginated(api.list_appeals(make_admin_headers()))
    assert meta["total_count"] == 0, (
        f"Expected 0 appeal rows, got {meta['total_count']} after the refused filing"
    )
    assert rows == [], f"Expected no appeal rows, got {rows}"

    after = get_deobligation(deobligation_id)
    assert after["status"] == "PROPOSED", (
        f"Expected PROPOSED, got {after['status']} after the refused filing"
    )
    assert after["reversed_cents"] == 0, (
        f"Expected 0, got {after['reversed_cents']} reversed_cents after the refused filing"
    )
    assert after["version"] == before["version"], (
        f"Expected determination version {before['version']}, got {after['version']} "
        "after the refused filing"
    )

    project = get_project(project_id)
    assert project["deobligated_cents"] == 0, (
        f"Expected 0, got {project['deobligated_cents']} deobligated_cents after the refused filing"
    )
    assert project["pending_deobligation_cents"] == 500_000, (
        f"Expected 500000, got {project['pending_deobligation_cents']} "
        "pending_deobligation_cents after the refused filing"
    )


def test_appeal_accepted_once_determination_finalized(api):
    """PRD §3.9: "Only a `FINAL` determination is appealable — a `PROPOSED` or
    `REVERSED` one yields `ERR_DEOBLIGATION_NOT_FINAL` — and `filed_at`, stamped
    from the logical clock, must be at or before the determination's
    `appeal_deadline_at`, with a clock instant exactly equal to the deadline
    still inside the window and anything later rejected as
    `ERR_APPEAL_WINDOW_EXPIRED`."

    PRD §3.9: "A filed appeal sits in `SUBMITTED` with `relief_granted_cents` 0,
    `decided_at` null, `decided_by_user_id` null and `decision_rationale` null."

    Design: Difficulty/cross_entity_state_dependency/appeal_filing_blocked_by_unfinalized_determination
    """
    scenario = setup_proposed_deobligation(
        500_000,
        reason="SCOPE_REDUCTION",
        headers=make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4919"),
        project_overrides=_project_overrides(900_000),
        line_items=DOCUMENTED_LINES,
    )
    applicant_id = scenario["applicant"]["id"]
    deobligation_id = scenario["deobligation"]["id"]

    # Clear the blocking cross-entity state: finalization opens the window.
    determination = finalize_deobligation(deobligation_id)
    assert determination["status"] == "FINAL", (
        f"Expected FINAL, got {determination['status']} after finalization"
    )

    appeal = validate_success(
        api.create_appeal(
            {
                "deobligation_id": deobligation_id,
                "grounds": "The reduced scope was approved in writing",
                "relief_requested_cents": 500_000,
            },
            make_applicant_agent_headers(applicant_id),
        ),
        expected_status=201,
    )
    assert appeal["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {appeal['status']} on the accepted filing"
    )
    assert appeal["level"] == "FIRST", (
        f"Expected FIRST, got {appeal['level']} with no prior_appeal_id supplied"
    )
    assert appeal["relief_granted_cents"] == 0, (
        f"Expected 0, got {appeal['relief_granted_cents']} relief_granted_cents on a new appeal"
    )
    assert appeal["decided_at"] is None, (
        f"Expected null decided_at, got {appeal['decided_at']!r} on a new appeal"
    )
    assert appeal["decided_by_user_id"] is None, (
        f"Expected null decided_by_user_id, got {appeal['decided_by_user_id']!r} on a new appeal"
    )


# ---------------------------------------------------------------------------
# Disaster -> Project: closing obligations is barred by an open project review
# ---------------------------------------------------------------------------
def test_close_obligations_refused_while_a_project_is_under_review(api):
    """PRD §3.1: "No project anywhere under the declaration — that is, under any
    of its applicants — may still be in `UNDER_REVIEW` or `RFI_ISSUED`, because
    closing the declaration while a review is open would strand that review with
    nowhere to land."

    PRD §3.1: "Any open review yields `ERR_PROJECT_REVIEWS_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/close_obligations_blocked_by_open_project_review
    """
    scenario = setup_submitted_project(
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4920"),
        project_overrides=_project_overrides(0),
    )
    disaster_id = scenario["disaster"]["id"]
    project_id = scenario["project"]["id"]

    assert get_project(project_id)["status"] == "UNDER_REVIEW", (
        "The child project must be UNDER_REVIEW for this gate to bite"
    )
    before = get_disaster(disaster_id)

    response = api.close_obligations(disaster_id, make_admin_headers())
    validate_error(response, ApiErrorId.ERR_PROJECT_REVIEWS_OPEN)

    after = get_disaster(disaster_id)
    assert after["status"] == "DECLARED", (
        f"Expected DECLARED, got {after['status']} after the refused close-obligations"
    )
    assert after["version"] == before["version"], (
        f"Expected declaration version {before['version']}, got {after['version']} "
        "after the refused close-obligations"
    )
    assert after["total_obligated_cents"] == 0, (
        f"Expected 0, got {after['total_obligated_cents']} declaration total_obligated_cents "
        "after the refused close-obligations"
    )
    assert after["total_drawn_cents"] == 0, (
        f"Expected 0, got {after['total_drawn_cents']} declaration total_drawn_cents "
        "after the refused close-obligations"
    )
    assert get_project(project_id)["status"] == "UNDER_REVIEW", (
        "The refused close-obligations must leave the project's review open"
    )


def test_close_obligations_succeeds_over_a_project_waiting_in_validated(api):
    """PRD §3.1: "Note what is *not* required: a project sitting in `VALIDATED`
    and still waiting for money is not an open review, so the declaration may
    close over it."

    PRD §3.1: "Closing sets `status` to `OBLIGATION_CLOSED` and increments the
    declaration's `version` by 1; a second attempt on an already-closed
    declaration yields `ERR_DISASTER_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/close_obligations_blocked_by_open_project_review
    """
    scenario = setup_submitted_project(
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4920"),
        project_overrides=_project_overrides(0),
    )
    disaster_id = scenario["disaster"]["id"]
    project_id = scenario["project"]["id"]

    # Clear the blocking cross-entity state: the review lands in VALIDATED.
    project = cost_review(project_id, decision="VALIDATE")
    assert project["status"] == "VALIDATED", (
        f"Expected VALIDATED, got {project['status']} after cost review"
    )
    before = get_disaster(disaster_id)

    disaster = validate_success(api.close_obligations(disaster_id, make_admin_headers()))
    assert disaster["status"] == "OBLIGATION_CLOSED", (
        f"Expected OBLIGATION_CLOSED, got {disaster['status']} after close-obligations"
    )
    assert disaster["version"] == before["version"] + 1, (
        f"Expected declaration version {before['version'] + 1}, got {disaster['version']} "
        "after close-obligations"
    )


# ---------------------------------------------------------------------------
# Conserved quantity 1 — the obligation ledger
# ---------------------------------------------------------------------------
def test_full_final_deobligation_returns_obligation_ledger_to_start(api):
    """PRD §2.9: "Obligating a project for some amount and then finalizing a
    determination for exactly that amount must leave `total_obligated_cents` —
    and the declaration's `total_obligated_cents` — exactly where they started."

    PRD §3.8: "`total_obligated_cents` is the sum, over the applicant's projects
    in status `OBLIGATED`, `CLOSEOUT_REQUESTED` or `CLOSED`, of
    `federal_share_obligated_cents` less `deobligated_cents`; projects in
    `DRAFT`, `UNDER_REVIEW`, `RFI_ISSUED`, `VALIDATED` or `DENIED` contribute
    nothing."

    Design: Difficulty/compensating_invariant/obligation_ledger_conserved_by_full_final_deobligation
    """
    scenario = setup_obligated_project(
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4927"),
        project_overrides=_project_overrides(900_000),
        line_items=DOCUMENTED_LINES,
    )
    disaster_id = scenario["disaster"]["id"]
    applicant_id = scenario["applicant"]["id"]
    project_id = scenario["project"]["id"]
    project = scenario["project"]

    assert project["repair_eligible_cents"] == 3_800_000, (
        f"Expected 3800000, got {project['repair_eligible_cents']} repair_eligible_cents"
    )
    assert project["mitigation_approved_cents"] == 760_000, (
        f"Expected 760000, got {project['mitigation_approved_cents']} mitigation_approved_cents"
    )
    assert project["federal_share_obligated_cents"] == OBLIGATED_SHARE_CENTS, (
        f"Expected {OBLIGATED_SHARE_CENTS}, got {project['federal_share_obligated_cents']} "
        "federal_share_obligated_cents"
    )
    assert get_applicant(applicant_id)["total_obligated_cents"] == OBLIGATED_SHARE_CENTS, (
        f"Expected {OBLIGATED_SHARE_CENTS} total_obligated_cents before the compensating pair"
    )
    assert get_disaster(disaster_id)["total_obligated_cents"] == OBLIGATED_SHARE_CENTS, (
        f"Expected {OBLIGATED_SHARE_CENTS} declaration total_obligated_cents "
        "before the compensating pair"
    )

    determination = validate_success(
        api.create_deobligation(
            deobligation_payload(
                project_id, OBLIGATED_SHARE_CENTS, project["version"], "SCOPE_REDUCTION"
            ),
            make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        ),
        expected_status=201,
    )
    validate_success(
        api.finalize_deobligation(
            determination["id"], make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID)
        )
    )

    applicant = get_applicant(applicant_id)
    assert applicant["total_obligated_cents"] == 0, (
        f"Expected 0, got {applicant['total_obligated_cents']} total_obligated_cents "
        "after the full final deobligation"
    )
    assert applicant["available_drawdown_cents"] == 0, (
        f"Expected 0, got {applicant['available_drawdown_cents']} available_drawdown_cents "
        "after the full final deobligation"
    )
    assert applicant["pending_deobligation_cents"] == 0, (
        f"Expected 0, got {applicant['pending_deobligation_cents']} pending_deobligation_cents "
        "after the full final deobligation"
    )
    assert applicant["drawdown_status"] == "ACTIVE", (
        f"Expected ACTIVE, got {applicant['drawdown_status']} after the full final deobligation"
    )
    assert get_disaster(disaster_id)["total_obligated_cents"] == 0, (
        "Expected 0 declaration total_obligated_cents after the full final deobligation"
    )


def test_full_final_deobligation_preserves_the_forward_obligation_record(api):
    """PRD §3.9: "Because the determination became final, the money actually
    leaves the obligation: the project's `deobligated_cents` rises by
    `amount_cents` and its `pending_deobligation_cents` falls by the same
    amount."

    PRD §3.9: "It stamps `finalized_at` from the logical clock and sets
    `appeal_deadline_at` to that instant plus the sixty-day appeal window."

    Design: Difficulty/compensating_invariant/obligation_ledger_conserved_by_full_final_deobligation
    """
    scenario = setup_obligated_project(
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4927"),
        project_overrides=_project_overrides(900_000),
        line_items=DOCUMENTED_LINES,
    )
    project_id = scenario["project"]["id"]

    determination = validate_success(
        api.create_deobligation(
            deobligation_payload(
                project_id,
                OBLIGATED_SHARE_CENTS,
                scenario["project"]["version"],
                "SCOPE_REDUCTION",
            ),
            make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        ),
        expected_status=201,
    )
    finalized = validate_success(
        api.finalize_deobligation(
            determination["id"], make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID)
        )
    )

    project = get_project(project_id)
    # Conservation is a net identity, not an erasure: the forward action stands.
    assert project["federal_share_obligated_cents"] == OBLIGATED_SHARE_CENTS, (
        f"Expected {OBLIGATED_SHARE_CENTS}, got {project['federal_share_obligated_cents']} "
        "federal_share_obligated_cents after the full final deobligation"
    )
    assert project["deobligated_cents"] == OBLIGATED_SHARE_CENTS, (
        f"Expected {OBLIGATED_SHARE_CENTS}, got {project['deobligated_cents']} deobligated_cents "
        "after the full final deobligation"
    )
    assert project["pending_deobligation_cents"] == 0, (
        f"Expected 0, got {project['pending_deobligation_cents']} project "
        "pending_deobligation_cents after the full final deobligation"
    )

    assert finalized["status"] == "FINAL", (
        f"Expected FINAL, got {finalized['status']} after finalization"
    )
    assert _instant(finalized["finalized_at"]) == _instant("2026-07-01T00:00:00Z"), (
        f"Expected finalized_at at 2026-07-01T00:00:00Z, got {finalized['finalized_at']}"
    )
    assert _instant(finalized["appeal_deadline_at"]) == _instant("2026-08-30T00:00:00Z"), (
        f"Expected appeal_deadline_at at 2026-08-30T00:00:00Z, got "
        f"{finalized['appeal_deadline_at']}"
    )
    assert _instant(finalized["appeal_deadline_at"]) - _instant(
        finalized["finalized_at"]
    ) == timedelta(days=60), "The appeal window must be exactly sixty days wide"


# ---------------------------------------------------------------------------
# Conserved quantity 2 — the cash ledger
# ---------------------------------------------------------------------------
def test_full_drawdown_refund_returns_cash_ledger_to_start(api):
    """PRD §2.9: "A paid drawdown of some amount followed by a full refund of
    that amount must leave `cash_on_hand_cents`, `available_drawdown_cents` and
    the declaration's `total_drawn_cents` exactly where they started, while
    `total_drawn_cents` and `total_refunded_cents` each rise by that amount."

    PRD §3.8: "The `PAID → REFUNDED` transition writes `refunded_cents` and sets
    `status` to `REFUNDED`; the applicant's `total_refunded_cents`,
    `cash_on_hand_cents` and `available_drawdown_cents` are recomputed, the
    declaration's `total_drawn_cents` follows, and the drawdown's, applicant's
    and declaration's `version` each increment by 1."

    Design: Difficulty/compensating_invariant/cash_ledger_conserved_by_full_drawdown_refund
    """
    scenario = setup_paid_drawdown(
        1_000_000,
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4928"),
        project_overrides=_project_overrides(900_000),
        line_items=DOCUMENTED_LINES,
    )
    disaster_id = scenario["disaster"]["id"]
    applicant_id = scenario["applicant"]["id"]
    drawdown_id = scenario["drawdown"]["id"]

    paid_applicant = get_applicant(applicant_id)
    assert paid_applicant["cash_on_hand_cents"] == 1_000_000, (
        f"Expected 1000000, got {paid_applicant['cash_on_hand_cents']} cash_on_hand_cents "
        "after payment"
    )
    assert paid_applicant["available_drawdown_cents"] == 2_420_000, (
        f"Expected 2420000, got {paid_applicant['available_drawdown_cents']} "
        "available_drawdown_cents after payment"
    )
    assert get_disaster(disaster_id)["total_drawn_cents"] == 1_000_000, (
        "Expected 1000000 declaration total_drawn_cents after payment"
    )

    drawdown = validate_success(
        api.refund_drawdown(
            drawdown_id,
            {"refund_cents": 1_000_000},
            make_applicant_agent_headers(applicant_id),
        )
    )
    assert drawdown["status"] == "REFUNDED", (
        f"Expected REFUNDED, got {drawdown['status']} after the full refund"
    )
    assert drawdown["approved_cents"] == 1_000_000, (
        f"Expected 1000000, got {drawdown['approved_cents']} approved_cents after the full refund"
    )
    assert drawdown["refunded_cents"] == 1_000_000, (
        f"Expected 1000000, got {drawdown['refunded_cents']} refunded_cents after the full refund"
    )

    applicant = get_applicant(applicant_id)
    assert applicant["cash_on_hand_cents"] == 0, (
        f"Expected 0, got {applicant['cash_on_hand_cents']} cash_on_hand_cents "
        "after the full refund"
    )
    assert applicant["available_drawdown_cents"] == OBLIGATED_SHARE_CENTS, (
        f"Expected {OBLIGATED_SHARE_CENTS}, got {applicant['available_drawdown_cents']} "
        "available_drawdown_cents after the full refund"
    )
    assert get_disaster(disaster_id)["total_drawn_cents"] == 0, (
        "Expected 0 declaration total_drawn_cents after the full refund"
    )


def test_full_drawdown_refund_records_both_legs_and_spares_the_obligation_ledger(api):
    """PRD §3.8: "Note that a refunded drawdown still counts toward
    `total_drawn_cents` — the pair of figures records that cash went out and came
    back, while `cash_on_hand_cents` records the net truth."

    PRD §2.9: "A paid drawdown of some amount followed by a full refund of that
    amount must leave `cash_on_hand_cents`, `available_drawdown_cents` and the
    declaration's `total_drawn_cents` exactly where they started, while
    `total_drawn_cents` and `total_refunded_cents` each rise by that amount."

    Design: Difficulty/compensating_invariant/cash_ledger_conserved_by_full_drawdown_refund
    """
    scenario = setup_paid_drawdown(
        1_000_000,
        clock=CLOCK_AT,
        disaster_overrides=_disaster_overrides("DR-4928"),
        project_overrides=_project_overrides(900_000),
        line_items=DOCUMENTED_LINES,
    )
    applicant_id = scenario["applicant"]["id"]
    project_id = scenario["project"]["id"]
    drawdown_id = scenario["drawdown"]["id"]

    validate_success(
        api.refund_drawdown(
            drawdown_id,
            {"refund_cents": 1_000_000},
            make_applicant_agent_headers(applicant_id),
        )
    )

    applicant = get_applicant(applicant_id)
    assert applicant["total_drawn_cents"] == 1_000_000, (
        f"Expected 1000000, got {applicant['total_drawn_cents']} total_drawn_cents "
        "after the full refund"
    )
    assert applicant["total_refunded_cents"] == 1_000_000, (
        f"Expected 1000000, got {applicant['total_refunded_cents']} total_refunded_cents "
        "after the full refund"
    )
    # The cash pair never touches the obligation ledger.
    assert applicant["total_obligated_cents"] == OBLIGATED_SHARE_CENTS, (
        f"Expected {OBLIGATED_SHARE_CENTS}, got {applicant['total_obligated_cents']} "
        "total_obligated_cents after the full refund"
    )

    assert (
        get_drawdown(drawdown_id)["disbursed_by_user_id"] == SECOND_GRANTS_OFFICER_USER_ID
    ), (
        f"Expected {SECOND_GRANTS_OFFICER_USER_ID}, got "
        f"{get_drawdown(drawdown_id)['disbursed_by_user_id']!r} in disbursed_by_user_id"
    )
    assert get_project(project_id)["obligated_by_user_id"] == GRANTS_OFFICER_USER_ID, (
        f"Expected {GRANTS_OFFICER_USER_ID}, got "
        f"{get_project(project_id)['obligated_by_user_id']!r} in obligated_by_user_id"
    )
