"""Access control, segregation of duties and optimistic concurrency."""
from datetime import datetime

import pytest

from test_helpers import (
    ADJUDICATOR_USER_ID,
    AUDITOR_USER_ID,
    GRANTS_OFFICER_USER_ID,
    SECOND_GRANTS_OFFICER_USER_ID,
    SPECIALIST_USER_ID,
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    applicant_payload,
    cost_review,
    create_applicant,
    create_drawdown,
    create_facility,
    create_project,
    deobligation_payload,
    determine_eligibility,
    disaster_payload,
    drawdown_payload,
    facility_payload,
    get_applicant,
    get_appeal,
    get_deobligation,
    get_disaster,
    get_drawdown,
    get_facility,
    get_project,
    make_adjudicator_headers,
    make_admin_headers,
    make_applicant_agent_headers,
    make_auditor_headers,
    make_grants_officer_headers,
    make_specialist_headers,
    screen_facility,
    set_clock,
    setup_appeal_under_review,
    setup_closeout_requested_project,
    setup_declaration,
    setup_eligible_applicant,
    setup_obligated_project,
    setup_validated_project,
    submit_project,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so timestamps compare by value, not by text."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# One exclusive operation per role, plus the operation two roles share.
# ---------------------------------------------------------------------------
def _platform_admin_declares_a_disaster(api):
    set_clock(TEST_DEFAULTS["CLOCK"])
    data = validate_success(
        api.create_disaster(
            disaster_payload(), make_admin_headers()
        ),
        201,
    )
    assert data["status"] == "DECLARED", (
        f"Expected DECLARED, got {data['status']} after declaring a disaster"
    )


def _applicant_agent_registers_a_facility(api):
    scenario = setup_eligible_applicant()
    applicant_id = scenario["applicant"]["id"]
    data = validate_success(
        api.create_facility(
            facility_payload(applicant_id, name="Riverside Pump Station"),
            make_applicant_agent_headers(applicant_id),
        ),
        201,
    )
    assert data["applicant_id"] == applicant_id, (
        f"Expected applicant_id {applicant_id}, got {data['applicant_id']} after register"
    )
    assert data["eligibility_status"] == "PENDING", (
        f"Expected PENDING, got {data['eligibility_status']} after register"
    )


def _program_specialist_screens_a_facility(api):
    scenario = setup_eligible_applicant()
    facility = create_facility(scenario["applicant"]["id"])
    data = validate_success(
        api.screen_facility(facility["id"], make_specialist_headers(SPECIALIST_USER_ID))
    )
    assert data["eligibility_status"] == "ELIGIBLE", (
        f"Expected ELIGIBLE, got {data['eligibility_status']} after screening"
    )
    assert data["version"] == 2, f"Expected version 2, got {data['version']} after screening"


def _grants_officer_obligates_a_project(api):
    scenario = setup_validated_project(
        project_overrides={"estimated_repair_cost_cents": 1_000_000},
        line_items=[{"cost_type": "MATERIALS", "claimed_cents": 1_000_000}],
    )
    data = validate_success(
        api.obligate_project(
            scenario["project"]["id"], make_grants_officer_headers(GRANTS_OFFICER_USER_ID)
        )
    )
    assert data["status"] == "OBLIGATED", (
        f"Expected OBLIGATED, got {data['status']} after obligate"
    )
    assert data["federal_share_obligated_cents"] == 750_000, (
        f"Expected 750000, got {data['federal_share_obligated_cents']} after obligate"
    )
    assert data["obligated_by_user_id"] == GRANTS_OFFICER_USER_ID, (
        f"Expected {GRANTS_OFFICER_USER_ID}, got {data['obligated_by_user_id']} after obligate"
    )


def _appeals_adjudicator_decides_an_appeal(api):
    scenario = setup_appeal_under_review(
        500_000,
        relief_requested_cents=200_000,
        reason="DISALLOWED_COST",
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    data = validate_success(
        api.decide_appeal(
            scenario["appeal"]["id"],
            {
                "decision": "DENY",
                "decision_rationale": "The materials were outside the eligible scope",
            },
            make_adjudicator_headers(ADJUDICATOR_USER_ID),
        )
    )
    assert data["status"] == "DENIED", f"Expected DENIED, got {data['status']} after decide"
    assert data["decided_by_user_id"] == ADJUDICATOR_USER_ID, (
        f"Expected {ADJUDICATOR_USER_ID}, got {data['decided_by_user_id']} after decide"
    )


def _state_auditor_certifies_closeout(api):
    scenario = setup_closeout_requested_project(
        project_overrides={"estimated_repair_cost_cents": 1_000_000},
        line_items=[{"cost_type": "MATERIALS", "claimed_cents": 1_000_000}],
    )
    data = validate_success(
        api.certify_closeout(
            scenario["project"]["id"],
            {"audit_finding": "Documented costs agree with the approved scope"},
            make_auditor_headers(AUDITOR_USER_ID),
        )
    )
    assert data["status"] == "CLOSED", f"Expected CLOSED, got {data['status']} after certify"
    assert data["federal_share_final_cents"] == 750_000, (
        f"Expected 750000, got {data['federal_share_final_cents']} after certify"
    )
    assert data["closeout_variance_cents"] == 0, (
        f"Expected 0, got {data['closeout_variance_cents']} after certifying a SMALL project"
    )


def _grants_officer_records_a_deobligation(api):
    scenario = setup_obligated_project(
        project_overrides={"estimated_repair_cost_cents": 1_000_000},
        line_items=[{"cost_type": "MATERIALS", "claimed_cents": 1_000_000}],
    )
    project = get_project(scenario["project"]["id"])
    data = validate_success(
        api.create_deobligation(
            deobligation_payload(
                project["id"], 100_000, project["version"], "DISALLOWED_COST"
            ),
            make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        ),
        201,
    )
    assert data["status"] == "PROPOSED", (
        f"Expected PROPOSED, got {data['status']} after recording a determination"
    )
    assert data["determined_by_user_id"] == SECOND_GRANTS_OFFICER_USER_ID, (
        f"Expected {SECOND_GRANTS_OFFICER_USER_ID}, got {data['determined_by_user_id']}"
    )
    assert get_project(project["id"])["pending_deobligation_cents"] == 100_000, (
        "Expected 100000 pending on the project after recording a determination"
    )


def _state_auditor_records_a_deobligation(api):
    scenario = setup_obligated_project(
        project_overrides={"estimated_repair_cost_cents": 1_000_000},
        line_items=[{"cost_type": "MATERIALS", "claimed_cents": 1_000_000}],
    )
    project = get_project(scenario["project"]["id"])
    data = validate_success(
        api.create_deobligation(
            deobligation_payload(
                project["id"], 100_000, project["version"], "PROCUREMENT_NONCOMPLIANCE"
            ),
            make_auditor_headers(AUDITOR_USER_ID),
        ),
        201,
    )
    assert data["status"] == "PROPOSED", (
        f"Expected PROPOSED, got {data['status']} after recording a determination"
    )
    assert data["determined_by_user_id"] == AUDITOR_USER_ID, (
        f"Expected {AUDITOR_USER_ID}, got {data['determined_by_user_id']}"
    )
    assert get_project(project["id"])["pending_deobligation_cents"] == 100_000, (
        "Expected 100000 pending on the project after recording a determination"
    )


@pytest.mark.parametrize(
    "exercise_operation",
    [
        pytest.param(
            _platform_admin_declares_a_disaster, id="PlatformAdmin-declares-a-disaster"
        ),
        pytest.param(
            _applicant_agent_registers_a_facility, id="ApplicantAgent-registers-a-facility"
        ),
        pytest.param(
            _program_specialist_screens_a_facility, id="ProgramSpecialist-screens-a-facility"
        ),
        pytest.param(
            _grants_officer_obligates_a_project, id="GrantsOfficer-obligates-a-project"
        ),
        pytest.param(
            _appeals_adjudicator_decides_an_appeal, id="AppealsAdjudicator-decides-an-appeal"
        ),
        pytest.param(
            _state_auditor_certifies_closeout, id="StateAuditor-certifies-closeout"
        ),
        pytest.param(
            _grants_officer_records_a_deobligation,
            id="GrantsOfficer-records-a-deobligation",
        ),
        pytest.param(
            _state_auditor_records_a_deobligation, id="StateAuditor-records-a-deobligation"
        ),
    ],
)
def test_each_role_may_exercise_its_own_operation(api, exercise_operation):
    """PRD §2.1: "`PlatformAdmin` — the state program office administrator. Declares
    disasters, defines and extends incident periods, registers applicants, advances the
    reporting epoch for an applicant, and drives the logical clock."

    PRD §2.1: "`ApplicantAgent` — the authorized agent of exactly one applicant.
    Registers facilities, force account resources, contracts and insurance policies;
    collects damage assessment observations; formulates and submits projects; answers
    requests for information; claims costs; requests and refunds cash; files progress
    reports; requests closeout; and files appeals."

    PRD §2.1: "`ProgramSpecialist` — the state reviewer. Determines applicant
    eligibility, screens facilities, validates or rejects damage assessment sites,
    reviews procurement compliance, reviews cost eligibility of individual claimed
    lines, issues requests for information, and validates or denies projects at cost
    review."

    PRD §2.1: "`GrantsOfficer` — the obligation and cash officer. Obligates validated
    projects, records insurance settlements, disburses or rejects drawdowns, and
    finalizes deobligation determinations. May also record a deobligation
    determination."

    PRD §2.1: "`AppealsAdjudicator` — the independent adjudicator. Decides first- and
    second-level appeals."

    PRD §2.1: "`StateAuditor` — the closeout auditor. Certifies project closeout, may
    record a deobligation determination, and reads every record."

    Design: Corner/rbac/every_role_exercises_one_exclusive_operation_and_the_shared_deobligation
    """
    exercise_operation(api)


# ---------------------------------------------------------------------------
# Rung 1 — header presence and role recognition.
# ---------------------------------------------------------------------------
def test_missing_either_auth_header_is_unauthenticated(api):
    """PRD §2.1: "Every request — including reads — must carry two headers."

    PRD §2.1: "If either header is absent, or if the value in `X-User-Role` is not one
    of the six roles defined below, the request is rejected with `ERR_UNAUTHENTICATED`
    (401)."

    PRD §2.7: "Checks are therefore evaluated in the following fixed order, and the
    **first** failing rung decides the response."

    Design: Corner/rbac/missing_required_x_user_id_header_returns_unauthenticated
    """
    scenario = setup_declaration()
    disaster_id = scenario["disaster"]["id"]

    validate_error(
        api.get_disaster(disaster_id, {"X-User-Role": "StateAuditor"}),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
    validate_error(
        api.get_disaster(disaster_id, {"X-User-ID": AUDITOR_USER_ID}),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
    # Neither header at all on a write: rung 1 fires ahead of the rung 2 role check.
    validate_error(
        api.create_applicant(
            applicant_payload(disaster_id), {"Content-Type": "application/json"}
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )

    _rows, meta = validate_paginated(api.list_applicants(TEST_USERS["admin_headers"]))
    assert meta["total_count"] == 0, (
        f"Expected 0 applicants, got {meta['total_count']} after the unauthenticated write"
    )


# ---------------------------------------------------------------------------
# Rung 2 — role authorization for the target endpoint.
# ---------------------------------------------------------------------------
def test_only_a_program_specialist_may_screen_a_facility(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not among the
    roles authorized for the target endpoint in §4, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (403)."

    PRD §3.2: "Screening is a `ProgramSpecialist` capability that drives the facility
    from `PENDING` to either `ELIGIBLE` or `INELIGIBLE`, and it is admissible only from
    `PENDING`."

    PRD §3.2: "Whichever branch fires, `screened_at` is stamped with the logical clock
    and the facility's `version` increments by 1; the `PENDING → ELIGIBLE` branch
    additionally clears `screening_failure_reason` to null, and the
    `PENDING → INELIGIBLE` branch sets it to the first failed rule's code."

    Design: Corner/rbac/applicant_agent_cannot_run_facility_screening
    """
    scenario = setup_eligible_applicant()
    applicant_id = scenario["applicant"]["id"]
    facility = create_facility(applicant_id, name="Riverside Pump Station")

    validate_error(
        api.screen_facility(facility["id"], make_applicant_agent_headers(applicant_id)),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.screen_facility(
            facility["id"], make_grants_officer_headers(GRANTS_OFFICER_USER_ID)
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )

    untouched = get_facility(facility["id"])
    assert untouched["eligibility_status"] == "PENDING", (
        f"Expected PENDING, got {untouched['eligibility_status']} after both refusals"
    )
    assert untouched["version"] == 1, (
        f"Expected version 1, got {untouched['version']} after both refusals"
    )
    assert untouched["screened_at"] is None, (
        f"Expected screened_at null, got {untouched['screened_at']} after both refusals"
    )

    screened = validate_success(
        api.screen_facility(facility["id"], make_specialist_headers(SPECIALIST_USER_ID))
    )
    assert screened["eligibility_status"] == "ELIGIBLE", (
        f"Expected ELIGIBLE, got {screened['eligibility_status']} after specialist screen"
    )
    assert screened["version"] == 2, (
        f"Expected version 2, got {screened['version']} after specialist screen"
    )


# ---------------------------------------------------------------------------
# Rung 3 — ApplicantAgent ownership scope.
# ---------------------------------------------------------------------------
def test_applicant_agent_cannot_touch_another_applicants_facility(api):
    """PRD §2.1: "Concretely, an `ApplicantAgent` may act only where
    `Facility.applicant_id`, `Project.applicant_id`,
    `ForceAccountResource.applicant_id`, `Contract.applicant_id`,
    `Drawdown.applicant_id` and `ProgressReport.applicant_id` equal `X-User-ID`; where
    an `InsurancePolicy` is reached, the owning `Facility`'s applicant must equal
    `X-User-ID`; where a `CostLineItem` is reached, its `Project`'s applicant must equal
    `X-User-ID`; and where an `Appeal` is filed, the appealed `Deobligation`'s `Project`
    must belong to `X-User-ID`."

    PRD §2.1: "Any violation of this rule is rejected with
    `ERR_APPLICANT_SCOPE_VIOLATION` (403)."

    PRD §2.7: "`ApplicantAgent` ownership scope over every applicant-scoped resource
    named in the path or the body — `ERR_APPLICANT_SCOPE_VIOLATION` (403)."

    Design: Corner/rbac/applicant_agent_cannot_amend_another_applicants_facility
    """
    scenario = setup_declaration()
    disaster_id = scenario["disaster"]["id"]
    applicant_a = determine_eligibility(
        create_applicant(
            disaster_id, name="City of Harborview", population_served=120_000
        )["id"]
    )
    applicant_b = determine_eligibility(
        create_applicant(
            disaster_id, name="Harborview Rural Water District", population_served=40_000
        )["id"]
    )
    facility_a = create_facility(applicant_a["id"], name="Riverside Pump Station")
    agent_b = make_applicant_agent_headers(applicant_b["id"])

    # The role is authorized for PATCH, so the scope check is what must fire.
    validate_error(
        api.amend_facility(facility_a["id"], {"in_active_use": False}, agent_b),
        ApiErrorId.ERR_APPLICANT_SCOPE_VIOLATION,
    )
    validate_error(
        api.create_facility(
            facility_payload(
                applicant_a["id"], name="Poached Substation", facility_type="UTILITY"
            ),
            agent_b,
        ),
        ApiErrorId.ERR_APPLICANT_SCOPE_VIOLATION,
    )

    untouched = get_facility(facility_a["id"])
    assert untouched["in_active_use"] is True, (
        f"Expected in_active_use True, got {untouched['in_active_use']} after the refusal"
    )
    assert untouched["version"] == 1, (
        f"Expected version 1, got {untouched['version']} after the refusal"
    )

    _rows, meta = validate_paginated(
        api.list_facilities(
            TEST_USERS["admin_headers"], params={"applicant_id": applicant_a["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"Expected 1 facility for applicant A, got {meta['total_count']} after the refusals"
    )


# ---------------------------------------------------------------------------
# Rung 29 — segregation of duties.
# ---------------------------------------------------------------------------
def test_obligating_officer_may_not_disburse_against_that_project(api):
    """PRD §2.10: "The `GrantsOfficer` whose identifier was recorded in
    `Project.obligated_by_user_id` when the project was obligated may not be the officer
    who disburses a drawdown against that project."

    PRD §2.10: "An attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403); the
    disbursing officer's identifier is what lands in `Drawdown.disbursed_by_user_id`."

    PRD §3.8: "Paying sets `approved_cents` to the full `requested_cents`, sets `status`
    to `PAID`, and records `disbursed_by_user_id`; because `approved_cents` moved, the
    applicant's `total_drawn_cents`, `cash_on_hand_cents` and
    `available_drawdown_cents` are recomputed, and because `cash_on_hand_cents` moved,
    the declaration's `total_drawn_cents` is recomputed; the drawdown's, the
    applicant's and the declaration's `version` each increment by 1."

    Design: Corner/rbac/disbursing_officer_cannot_be_the_obligating_officer
    """
    scenario = setup_obligated_project(
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
        officer_user_id=GRANTS_OFFICER_USER_ID,
    )
    applicant_id = scenario["applicant"]["id"]
    assert scenario["project"]["federal_share_obligated_cents"] == 1_500_000, (
        "Expected 1500000 obligated, got "
        f"{scenario['project']['federal_share_obligated_cents']}"
    )
    drawdown = create_drawdown(applicant_id, scenario["project"]["id"], 400_000)

    validate_error(
        api.disburse_drawdown(
            drawdown["id"],
            {"decision": "PAY"},
            make_grants_officer_headers(GRANTS_OFFICER_USER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    untouched = get_drawdown(drawdown["id"])
    assert untouched["status"] == "REQUESTED", (
        f"Expected REQUESTED, got {untouched['status']} after the refusal"
    )
    assert untouched["approved_cents"] == 0, (
        f"Expected 0, got {untouched['approved_cents']} after the refusal"
    )
    assert untouched["disbursed_by_user_id"] is None, (
        f"Expected null, got {untouched['disbursed_by_user_id']} after the refusal"
    )
    before = get_applicant(applicant_id)
    assert before["total_drawn_cents"] == 0, (
        f"Expected 0 drawn, got {before['total_drawn_cents']} after the refusal"
    )
    assert before["cash_on_hand_cents"] == 0, (
        f"Expected 0 cash on hand, got {before['cash_on_hand_cents']} after the refusal"
    )

    paid = validate_success(
        api.disburse_drawdown(
            drawdown["id"],
            {"decision": "PAY"},
            make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        )
    )
    assert paid["status"] == "PAID", f"Expected PAID, got {paid['status']} after disburse"
    assert paid["approved_cents"] == 400_000, (
        f"Expected 400000, got {paid['approved_cents']} after disburse"
    )
    assert paid["disbursed_by_user_id"] == SECOND_GRANTS_OFFICER_USER_ID, (
        f"Expected {SECOND_GRANTS_OFFICER_USER_ID}, got {paid['disbursed_by_user_id']}"
    )

    after = get_applicant(applicant_id)
    assert after["total_drawn_cents"] == 400_000, (
        f"Expected 400000 drawn, got {after['total_drawn_cents']} after disburse"
    )
    assert after["available_drawdown_cents"] == 1_100_000, (
        f"Expected 1100000 available, got {after['available_drawdown_cents']} after disburse"
    )


def test_determining_user_may_not_decide_the_appeal_against_it(api):
    """PRD §2.10: "The user whose identifier was recorded in
    `Deobligation.determined_by_user_id` may not decide an appeal against that
    determination, even when that user legitimately holds `AppealsAdjudicator` duty as
    well."

    PRD §2.10: "The attempt is rejected with the same `ERR_SEGREGATION_OF_DUTIES`
    (403), and a clean decision records the adjudicator in `Appeal.decided_by_user_id`."

    PRD §3.9: "**`SUBMITTED → DENIED`** sets `relief_granted_cents` to 0 and moves
    **nothing** outside the appeal row — no determination, project, applicant or
    declaration field changes, and no version other than the appeal's increments."

    Design: Corner/rbac/adjudicator_cannot_decide_an_appeal_on_own_determination
    """
    scenario = setup_appeal_under_review(
        500_000,
        relief_requested_cents=200_000,
        reason="DISALLOWED_COST",
        headers=make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        officer_user_id=SECOND_GRANTS_OFFICER_USER_ID,
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    appeal_id = scenario["appeal"]["id"]
    deobligation_id = scenario["deobligation"]["id"]
    assert scenario["deobligation"]["determined_by_user_id"] == SECOND_GRANTS_OFFICER_USER_ID, (
        f"Expected {SECOND_GRANTS_OFFICER_USER_ID}, got "
        f"{scenario['deobligation']['determined_by_user_id']} on the determination"
    )

    conflicted = make_adjudicator_headers(SECOND_GRANTS_OFFICER_USER_ID)
    validate_error(
        api.decide_appeal(
            appeal_id,
            {"decision": "GRANT", "decision_rationale": "Deciding my own determination"},
            conflicted,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    # The bar is on the user, not on the decision value.
    validate_error(
        api.decide_appeal(
            appeal_id,
            {
                "decision": "DENY",
                "decision_rationale": "Deciding my own determination the other way",
            },
            conflicted,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    untouched_appeal = get_appeal(appeal_id)
    assert untouched_appeal["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {untouched_appeal['status']} after both refusals"
    )
    assert untouched_appeal["decided_at"] is None, (
        f"Expected decided_at null, got {untouched_appeal['decided_at']} after both refusals"
    )
    assert untouched_appeal["decided_by_user_id"] is None, (
        f"Expected decided_by_user_id null, got {untouched_appeal['decided_by_user_id']}"
    )
    untouched_determination = get_deobligation(deobligation_id)
    assert untouched_determination["status"] == "FINAL", (
        f"Expected FINAL, got {untouched_determination['status']} after both refusals"
    )
    assert untouched_determination["reversed_cents"] == 0, (
        f"Expected 0 reversed, got {untouched_determination['reversed_cents']}"
    )

    decided = validate_success(
        api.decide_appeal(
            appeal_id,
            {
                "decision": "DENY",
                "decision_rationale": "The documentation does not support the claimed costs",
            },
            make_adjudicator_headers(ADJUDICATOR_USER_ID),
        )
    )
    assert decided["status"] == "DENIED", (
        f"Expected DENIED, got {decided['status']} after the independent decision"
    )
    assert decided["decided_by_user_id"] == ADJUDICATOR_USER_ID, (
        f"Expected {ADJUDICATOR_USER_ID}, got {decided['decided_by_user_id']} after decide"
    )


# ---------------------------------------------------------------------------
# Rung 7 — optimistic concurrency on the two ledger writes.
# ---------------------------------------------------------------------------
def test_stale_expected_applicant_version_rejects_the_drawdown(api):
    """PRD §2.8: "Creating a drawdown requires a non-optional
    `expected_applicant_version` field in the request body, carrying the client's last
    observed `version` of the target `Applicant`."

    PRD §2.8: "If it does not equal that applicant's current `version`, the create is
    rejected with `ERR_STALE_APPLICANT_VERSION` (412) and nothing is written."

    PRD §3.8: "A created drawdown sits in `REQUESTED` with `approved_cents` 0,
    `refunded_cents` 0, `disbursed_by_user_id` null and `rejection_reason` null, and the
    create increments the applicant's `version` by 1 — which is why a client intending
    to file two drawdowns in a row must re-read the applicant between them."

    Design: Corner/cross_cutting_complexity_layers/stale_applicant_version_on_drawdown_create_returns_412
    """
    scenario = setup_obligated_project(
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    applicant_id = scenario["applicant"]["id"]
    project_id = scenario["project"]["id"]
    agent = make_applicant_agent_headers(applicant_id)

    stale_version = get_applicant(applicant_id)["version"]
    first = validate_success(
        api.create_drawdown(
            drawdown_payload(applicant_id, project_id, 300_000, stale_version), agent
        ),
        201,
    )
    assert first["status"] == "REQUESTED", (
        f"Expected REQUESTED, got {first['status']} on the first drawdown"
    )
    after_first = get_applicant(applicant_id)
    assert after_first["version"] == stale_version + 1, (
        f"Expected version {stale_version + 1}, got {after_first['version']} after the create"
    )

    validate_error(
        api.create_drawdown(
            drawdown_payload(applicant_id, project_id, 300_000, stale_version), agent
        ),
        ApiErrorId.ERR_STALE_APPLICANT_VERSION,
    )

    untouched = get_applicant(applicant_id)
    assert untouched["version"] == after_first["version"], (
        f"Expected version {after_first['version']} untouched, got {untouched['version']}"
    )
    assert untouched["total_drawn_cents"] == 0, (
        f"Expected 0 drawn, got {untouched['total_drawn_cents']} after the 412"
    )
    _rows, meta = validate_paginated(
        api.list_drawdowns(
            TEST_USERS["admin_headers"], params={"applicant_id": applicant_id}
        )
    )
    assert meta["total_count"] == 1, (
        f"Expected 1 drawdown, got {meta['total_count']} after the rejected create"
    )

    fresh_version = get_applicant(applicant_id)["version"]
    assert fresh_version == stale_version + 1, (
        f"Expected fresh version {stale_version + 1}, got {fresh_version}"
    )
    second = validate_success(
        api.create_drawdown(
            drawdown_payload(applicant_id, project_id, 300_000, fresh_version), agent
        ),
        201,
    )
    assert second["status"] == "REQUESTED", (
        f"Expected REQUESTED, got {second['status']} on the replayed drawdown"
    )

    rows, meta = validate_paginated(
        api.list_drawdowns(
            TEST_USERS["admin_headers"], params={"applicant_id": applicant_id}
        )
    )
    assert meta["total_count"] == 2, (
        f"Expected 2 drawdowns, got {meta['total_count']} after the re-read create"
    )
    assert all(row["status"] == "REQUESTED" for row in rows), (
        f"Expected both drawdowns REQUESTED, got {[row['status'] for row in rows]}"
    )
    assert get_applicant(applicant_id)["total_drawn_cents"] == 0, (
        "Expected 0 drawn while both drawdowns are still REQUESTED"
    )


def test_stale_expected_project_version_rejects_the_deobligation(api):
    """PRD §2.8: "Creating a deobligation determination requires a non-optional
    `expected_project_version` field in the request body, carrying the client's last
    observed `version` of the target `Project`."

    PRD §2.8: "If it does not equal that project's current `version`, the create is
    rejected with `ERR_STALE_PROJECT_VERSION` (412) and nothing is written."

    PRD §3.9: "Because it exists, the project's and the applicant's
    `pending_deobligation_cents` are recomputed, `drawdown_status` becomes `SUSPENDED`
    and the declaration's `suspended_applicant_count` is refreshed; the project's
    `version` and the applicant's `version` each increment by 1."

    Design: Corner/cross_cutting_complexity_layers/stale_project_version_on_deobligation_create_returns_412
    """
    scenario = setup_obligated_project(
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    project_id = scenario["project"]["id"]
    applicant_id = scenario["applicant"]["id"]
    stale_version = scenario["project"]["version"]

    first = validate_success(
        api.create_deobligation(
            deobligation_payload(project_id, 500_000, stale_version, "SCOPE_REDUCTION"),
            make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        ),
        201,
    )
    assert first["status"] == "PROPOSED", (
        f"Expected PROPOSED, got {first['status']} on the first determination"
    )
    after_first = get_project(project_id)
    assert after_first["version"] == stale_version + 1, (
        f"Expected version {stale_version + 1}, got {after_first['version']} after the create"
    )
    assert after_first["pending_deobligation_cents"] == 500_000, (
        f"Expected 500000 pending, got {after_first['pending_deobligation_cents']}"
    )

    validate_error(
        api.create_deobligation(
            deobligation_payload(project_id, 500_000, stale_version, "DISALLOWED_COST"),
            make_auditor_headers(AUDITOR_USER_ID),
        ),
        ApiErrorId.ERR_STALE_PROJECT_VERSION,
    )

    untouched = get_project(project_id)
    assert untouched["version"] == after_first["version"], (
        f"Expected version {after_first['version']} untouched, got {untouched['version']}"
    )
    assert untouched["pending_deobligation_cents"] == 500_000, (
        f"Expected 500000 pending, got {untouched['pending_deobligation_cents']} after the 412"
    )
    _rows, meta = validate_paginated(
        api.list_deobligations(
            TEST_USERS["admin_headers"], params={"project_id": project_id}
        )
    )
    assert meta["total_count"] == 1, (
        f"Expected 1 determination, got {meta['total_count']} after the rejected create"
    )

    fresh_version = get_project(project_id)["version"]
    assert fresh_version == stale_version + 1, (
        f"Expected fresh version {stale_version + 1}, got {fresh_version}"
    )
    second = validate_success(
        api.create_deobligation(
            deobligation_payload(project_id, 500_000, fresh_version, "DISALLOWED_COST"),
            make_auditor_headers(AUDITOR_USER_ID),
        ),
        201,
    )
    assert second["determined_by_user_id"] == AUDITOR_USER_ID, (
        f"Expected {AUDITOR_USER_ID}, got {second['determined_by_user_id']} on the retry"
    )

    assert get_project(project_id)["pending_deobligation_cents"] == 1_000_000, (
        "Expected 1000000 pending on the project after both determinations"
    )
    assert get_applicant(applicant_id)["drawdown_status"] == "SUSPENDED", (
        "Expected SUSPENDED drawdown_status while determinations are PROPOSED"
    )


# ---------------------------------------------------------------------------
# The single-audit threshold boundary and the cascade it opens.
# ---------------------------------------------------------------------------
def test_single_audit_threshold_bites_at_exactly_seventy_five_million_cents(api):
    """PRD §3.7: "Because `total_obligated_cents` moved, the single-audit test runs:
    when it now stands at or above 75,000,000 cents — seven hundred fifty thousand
    dollars of federal award — and the applicant's `monitoring_status` is still
    `STANDARD`, `audit_requirement` becomes `SINGLE_AUDIT` and `monitoring_status`
    escalates `MONITORING:STANDARD → MONITORING:ENHANCED`."

    PRD §3.7: "Because `monitoring_status` became `ENHANCED`, the system creates one
    progress report row for this applicant in status `DUE`, for the quarter containing
    the current logical clock, with `quarter_label`, `period_start_at`, `period_end_at`
    and `due_at` all derived by the quarter rules of §3.8."

    PRD §3.7: "Then the repair share is that net repair figure multiplied by the
    declaration's `federal_cost_share_pct` and rounded half up to whole cents, **and
    separately** the mitigation share is `mitigation_approved_cents` multiplied by the
    same `federal_cost_share_pct` and rounded half up to whole cents."

    PRD §3.8: "`period_start_at` is the first instant of that quarter of that year in
    UTC; `period_end_at` is the first instant of the following quarter, and because the
    period is half-open that end instant belongs to the next quarter rather than this
    one; and `due_at` is `period_end_at` plus the reporting grace period of thirty
    days."

    Design: Corner/cross_cutting_complexity_layers/single_audit_threshold_triggers_at_exactly_75000000_obligated
    """
    scenario = setup_declaration()
    disaster_id = scenario["disaster"]["id"]

    applicant_a = determine_eligibility(
        create_applicant(
            disaster_id, name="City of Harborview", population_served=120_000
        )["id"]
    )
    applicant_b = determine_eligibility(
        create_applicant(
            disaster_id, name="Harborview Rural Water District", population_served=40_000
        )["id"]
    )
    facility_a = screen_facility(
        create_facility(applicant_a["id"], name="Riverside Pump Station")["id"]
    )
    facility_b = screen_facility(
        create_facility(
            applicant_b["id"], name="District Wellfield", facility_type="UTILITY"
        )["id"]
    )

    project_a = create_project(
        applicant_a["id"],
        facility_a["id"],
        title="Pump station rebuild",
        scope_of_work="Rebuild the pump station",
        estimated_repair_cost_cents=100_000_000,
    )
    project_b = create_project(
        applicant_b["id"],
        facility_b["id"],
        title="Wellfield rebuild",
        scope_of_work="Rebuild the wellfield",
        estimated_repair_cost_cents=99_999_999,
    )
    submit_project(project_a["id"], applicant_a["id"])
    submit_project(project_b["id"], applicant_b["id"])
    cost_review(project_a["id"])
    cost_review(project_b["id"])

    obligated_a = validate_success(
        api.obligate_project(
            project_a["id"], make_grants_officer_headers(GRANTS_OFFICER_USER_ID)
        )
    )
    obligated_b = validate_success(
        api.obligate_project(
            project_b["id"], make_grants_officer_headers(GRANTS_OFFICER_USER_ID)
        )
    )

    assert obligated_a["federal_share_obligated_cents"] == 75_000_000, (
        f"Expected 75000000, got {obligated_a['federal_share_obligated_cents']} after obligate"
    )
    assert obligated_a["size_class"] == "LARGE", (
        f"Expected LARGE, got {obligated_a['size_class']} after obligate"
    )
    assert obligated_b["federal_share_obligated_cents"] == 74_999_999, (
        f"Expected 74999999, got {obligated_b['federal_share_obligated_cents']} after obligate"
    )
    assert obligated_b["size_class"] == "LARGE", (
        f"Expected LARGE, got {obligated_b['size_class']} after obligate"
    )

    ledger_a = get_applicant(applicant_a["id"])
    assert ledger_a["total_obligated_cents"] == 75_000_000, (
        f"Expected 75000000 obligated, got {ledger_a['total_obligated_cents']}"
    )
    assert ledger_a["audit_requirement"] == "SINGLE_AUDIT", (
        f"Expected SINGLE_AUDIT, got {ledger_a['audit_requirement']} at the threshold"
    )
    assert ledger_a["monitoring_status"] == "ENHANCED", (
        f"Expected ENHANCED, got {ledger_a['monitoring_status']} at the threshold"
    )

    ledger_b = get_applicant(applicant_b["id"])
    assert ledger_b["total_obligated_cents"] == 74_999_999, (
        f"Expected 74999999 obligated, got {ledger_b['total_obligated_cents']}"
    )
    assert ledger_b["audit_requirement"] == "NONE", (
        f"Expected NONE, got {ledger_b['audit_requirement']} one cent short"
    )
    assert ledger_b["monitoring_status"] == "STANDARD", (
        f"Expected STANDARD, got {ledger_b['monitoring_status']} one cent short"
    )

    rows_a, meta_a = validate_paginated(
        api.list_progress_reports(
            TEST_USERS["admin_headers"], params={"applicant_id": applicant_a["id"]}
        )
    )
    assert meta_a["total_count"] == 1, (
        f"Expected 1 progress report for the escalated applicant, got {meta_a['total_count']}"
    )
    report = rows_a[0]
    assert report["quarter_label"] == "2026-Q3", (
        f"Expected 2026-Q3, got {report['quarter_label']} on the auto-created report"
    )
    assert report["status"] == "DUE", (
        f"Expected DUE, got {report['status']} on the auto-created report"
    )
    assert _instant(report["period_start_at"]) == _instant("2026-07-01T00:00:00Z"), (
        f"Expected period_start_at 2026-07-01T00:00:00Z, got {report['period_start_at']}"
    )
    assert _instant(report["period_end_at"]) == _instant("2026-10-01T00:00:00Z"), (
        f"Expected period_end_at 2026-10-01T00:00:00Z, got {report['period_end_at']}"
    )
    assert _instant(report["due_at"]) == _instant("2026-10-31T00:00:00Z"), (
        f"Expected due_at 2026-10-31T00:00:00Z, got {report['due_at']}"
    )

    _rows_b, meta_b = validate_paginated(
        api.list_progress_reports(
            TEST_USERS["admin_headers"], params={"applicant_id": applicant_b["id"]}
        )
    )
    assert meta_b["total_count"] == 0, (
        f"Expected no progress report one cent short, got {meta_b['total_count']}"
    )

    declaration = get_disaster(disaster_id)
    assert declaration["enhanced_monitoring_applicant_count"] == 1, (
        "Expected 1 enhanced-monitoring applicant, got "
        f"{declaration['enhanced_monitoring_applicant_count']}"
    )
    assert declaration["total_obligated_cents"] == 149_999_999, (
        f"Expected 149999999 obligated, got {declaration['total_obligated_cents']}"
    )
