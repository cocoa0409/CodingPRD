"""Lifecycle transitions: the side effects a legal one fires, and the refusals a
posture that does not start the transition produces.

Refused transitions are asserted to be completely inert — the posture, the
stamps they would have written and the version of the row all stay where they
were.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_AGENCY_MEMBERSHIP_TERMINAL,
    ERR_CAMPAIGN_INVALID_STATE,
    ERR_CYCLE_FROZEN,
    ERR_PLEDGE_COLLECTION_TERMINAL,
    ERR_REVIEW_ALREADY_CERTIFIED,
)
from test_helpers.assertions import (
    assert_bps,
    assert_is_false,
    assert_is_null,
    assert_is_true,
    assert_money,
    require_by,
)
from test_helpers.factories import (
    agency_review_payload,
    certify_payload,
    collection_payload,
    designation_line,
    panel_assignment_payload,
    pledge_payload,
    write_off_payload,
)
from test_helpers.fixtures import (
    create_active_employer,
    create_agency,
    create_campaign,
    create_coordinator,
    create_cycle,
    create_open_campaign,
    create_panelist,
    create_pledge,
    file_review,
    seat_panelist,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_allocations_director_headers,
    make_coordinator_headers,
    make_finance_reviewer_headers,
)

SELF_REPORTED_PASS = {
    "fiscal_year": 2025,
    "program_expense_ratio": "0.7800",
    "admin_expense_ratio": "0.1900",
    "months_operating_reserve": "4.00",
    "governance_checklist_passed_count": 8,
    "audit_opinion": "UNQUALIFIED",
}
AUDITED_UNCHANGED = {
    "audited_program_expense_ratio": "0.7800",
    "audited_admin_expense_ratio": "0.1900",
    "audited_months_operating_reserve": "4.00",
}
SELF_REPORTED_FAIL = {
    "program_expense_ratio": "0.6600",
    "admin_expense_ratio": "0.4000",
    "months_operating_reserve": "1.00",
    "governance_checklist_passed_count": 0,
    "audit_opinion": "NONE",
}
AUDITED_FAIL = {
    "audited_program_expense_ratio": "0.6600",
    "audited_admin_expense_ratio": "0.4000",
    "audited_months_operating_reserve": "1.00",
}


def test_filing_the_first_review_pulls_the_applicant_into_financial_review():
    """PRD 3.6: "Filing also moves the agency into `UNDER_FINANCIAL_REVIEW` —
    `APPLICANT → UNDER_FINANCIAL_REVIEW` for a first-time applicant,
    `GOOD_STANDING → UNDER_FINANCIAL_REVIEW` for an annual re-review, and
    `PROBATION → UNDER_FINANCIAL_REVIEW` for an agency trying to work its way back —
    and increments `open_review_count`."

    Filing is a transition on the agency addressed by the path, driven by the creation
    of a different row; the review itself arrives `PENDING` on self-reported figures,
    so the certified half of every field is still null.

    Design: Corner/state_machines/agency_review_creation_moves_applicant_to_under_financial_review
    """
    admin = make_admin_headers()
    agency = create_agency(
        legal_name="Eastbrook Health Partners",
        ein="600000004",
        primary_priority_area="HEALTH",
    )
    assert agency["membership_status"] == "APPLICANT"

    review = validate_success(
        api_client.create_agency_review(
            agency["id"], agency_review_payload(**SELF_REPORTED_PASS), admin
        ),
        201,
    )

    assert review["status"] == "PENDING"
    assert review["review_basis"] == "SELF_REPORTED"
    assert_money(review["preliminary_score"], "80.00", "preliminary_score")
    assert_is_null(review["certified_score"], "certified_score")
    assert_is_null(review["standards_met"], "standards_met")
    assert_is_false(review["restatement_penalty_applied"], "restatement_penalty_applied")
    assert_is_null(review["audited_program_expense_ratio"], "audited_program_expense_ratio")
    assert_is_null(review["audited_admin_expense_ratio"], "audited_admin_expense_ratio")
    assert_is_null(
        review["audited_months_operating_reserve"], "audited_months_operating_reserve"
    )

    reread = validate_success(api_client.get_agency(agency["id"], admin))
    assert reread["membership_status"] == "UNDER_FINANCIAL_REVIEW"
    assert reread["open_review_count"] == 1
    assert_is_null(reread["latest_standing_score"], "latest_standing_score")

    reviews, meta = validate_paginated(api_client.list_agency_reviews(agency["id"], admin))
    assert meta["total_count"] == 1
    assert reviews[0]["id"] == review["id"]
    assert reviews[0]["fiscal_year"] == 2025


def test_a_planned_campaign_refuses_both_of_the_transitions_it_cannot_start():
    """PRD 3.2: "The two terminal postures, `RECONCILED` and `ESCROW_HOLD`, are reached
    only through reconciliation, and a campaign transition attempted from a posture the
    transition does not start from is rejected with `ERR_CAMPAIGN_INVALID_STATE`."

    `PLANNED` has exactly one outgoing trigger, so neither closing solicitation nor
    reconciling may leave a trace behind.

    Design: Corner/state_machines/close_solicitation_on_planned_campaign_returns_campaign_invalid_state
    """
    admin = make_admin_headers()
    employer = create_active_employer(legal_name="Redstone Quarry", employee_count=140)
    campaign = create_campaign(
        employer["id"],
        campaign_year=2026,
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )
    assert campaign["posture"] == "PLANNED"

    validate_error(
        api_client.close_campaign_solicitation(campaign["id"], admin),
        ERR_CAMPAIGN_INVALID_STATE,
        409,
    )
    validate_error(
        api_client.reconcile_campaign(campaign["id"], admin),
        ERR_CAMPAIGN_INVALID_STATE,
        409,
    )

    reread = validate_success(api_client.get_campaign(campaign["id"], admin))
    assert reread["posture"] == "PLANNED"
    assert_is_null(reread["solicitation_closed_at"], "solicitation_closed_at")
    assert_is_null(reread["reconciled_at"], "reconciled_at")
    assert_is_null(reread["provisional_estimated_loss"], "provisional_estimated_loss")
    assert_is_null(reread["final_actual_loss"], "final_actual_loss")
    assert reread["version"] == 1, "no refused transition counts as a mutation"


def test_certifying_an_already_certified_review_is_refused_and_moves_nothing():
    """PRD 3.6: "The review must still be `PENDING`, or the attempt is refused with
    `ERR_REVIEW_ALREADY_CERTIFIED`; the review must belong to the agency named earlier
    in the path, or the attempt is refused with `ERR_REVIEW_AGENCY_MISMATCH`; and the
    agency must not be `SUSPENDED_MEMBERSHIP`, or the attempt is refused with
    `ERR_AGENCY_MEMBERSHIP_TERMINAL`."

    Certification is not idempotent: the replayed body is byte-identical to the one that
    succeeded, and it still has to be refused, leaving the agency's version where the
    first call left it.

    Design: Corner/state_machines/certify_same_review_twice_returns_review_already_certified
    """
    admin = make_admin_headers()
    agency = create_agency(
        legal_name="Cedar Hills Family Center",
        ein="600000005",
        primary_priority_area="FINANCIAL_STABILITY",
    )
    review = file_review(agency["id"], **SELF_REPORTED_PASS)

    certified = validate_success(
        api_client.certify_agency_review(
            agency["id"],
            review["id"],
            certify_payload(**AUDITED_UNCHANGED),
            make_finance_reviewer_headers(),
        )
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["review_basis"] == "AUDITED"
    assert_money(certified["certified_score"], "90.00", "certified_score")
    assert_is_true(certified["standards_met"], "standards_met")
    assert_is_false(certified["restatement_penalty_applied"], "restatement_penalty_applied")

    after_first = validate_success(api_client.get_agency(agency["id"], admin))
    assert after_first["membership_status"] == "GOOD_STANDING"
    assert_money(after_first["latest_standing_score"], "90.00", "latest_standing_score")
    assert after_first["open_review_count"] == 0

    validate_error(
        api_client.certify_agency_review(
            agency["id"],
            review["id"],
            certify_payload(**AUDITED_UNCHANGED),
            make_finance_reviewer_headers(),
        ),
        ERR_REVIEW_ALREADY_CERTIFIED,
        409,
    )

    after_replay = validate_success(api_client.get_agency(agency["id"], admin))
    assert after_replay["version"] == after_first["version"], (
        "the refused replay is not a mutation of the agency"
    )
    assert after_replay["membership_status"] == "GOOD_STANDING"
    reviews, _ = validate_paginated(api_client.list_agency_reviews(agency["id"], admin))
    still_certified = require_by(reviews, "id", review["id"])
    assert still_certified["status"] == "CERTIFIED"
    assert_money(still_certified["certified_score"], "90.00", "certified_score")


def test_a_written_off_pledge_accepts_neither_a_remittance_nor_a_second_write_off():
    """PRD 2.10: "Pledge collection status must not already be terminal, that is,
    neither `COLLECTED` nor `WRITTEN_OFF`, for remittances and write-offs
    (`ERR_PLEDGE_COLLECTION_TERMINAL`)."

    PRD 3.5: "First, the pledge's `collection_status` advances `PENDING → WRITTEN_OFF`
    or `PARTIAL → WRITTEN_OFF` according to where it stood, `write_off_reason_code`
    records the supplied reason, and `uncollected_amount` is fixed at `gross_amount`
    minus `collected_amount`."

    Design: Corner/state_machines/write_off_then_collect_on_written_off_pledge_returns_collection_terminal
    """
    admin = make_admin_headers()
    finance = make_finance_reviewer_headers()
    employer = create_active_employer(
        legal_name="Union Pacific Grain", employee_count=300
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )
    pledge = create_pledge(
        campaign["id"],
        donor_reference="W-001",
        giving_method="PAYROLL_DEDUCTION",
        gross_amount="500.00",
    )
    validate_success(api_client.confirm_pledge(pledge["id"], admin))
    written_off = validate_success(
        api_client.write_off_pledge(
            pledge["id"], write_off_payload(reason_code="TERMINATION"), finance
        )
    )
    assert written_off["collection_status"] == "WRITTEN_OFF"

    validate_error(
        api_client.create_collection(
            pledge["id"], collection_payload("100.00", "2026-08-01"), finance
        ),
        ERR_PLEDGE_COLLECTION_TERMINAL,
        409,
    )
    validate_error(
        api_client.write_off_pledge(
            pledge["id"], write_off_payload(reason_code="DONOR_REVOKED"), finance
        ),
        ERR_PLEDGE_COLLECTION_TERMINAL,
        409,
    )

    reread = validate_success(api_client.get_pledge(pledge["id"], admin))
    assert reread["collection_status"] == "WRITTEN_OFF"
    assert reread["write_off_reason_code"] == "TERMINATION", (
        "the second reason code never lands on the row"
    )
    assert_money(reread["collected_amount"], "0.00", "collected_amount")
    assert_money(reread["uncollected_amount"], "500.00", "uncollected_amount")
    assert reread["designation_status"] == "CONFIRMED", (
        "the write-off moves only the collection axis"
    )


def test_certifying_a_second_review_after_membership_suspension_is_refused():
    """PRD 3.6: "A score below 55.00 moves it
    `UNDER_FINANCIAL_REVIEW → SUSPENDED_MEMBERSHIP`, which is terminal."

    PRD 3.6: "The review must still be `PENDING`, or the attempt is refused with
    `ERR_REVIEW_ALREADY_CERTIFIED`; the review must belong to the agency named earlier
    in the path, or the attempt is refused with `ERR_REVIEW_AGENCY_MISMATCH`; and the
    agency must not be `SUSPENDED_MEMBERSHIP`, or the attempt is refused with
    `ERR_AGENCY_MEMBERSHIP_TERMINAL`."

    Both reviews were filed while the agency was still admissible, so the second
    certification violates the agency-side precondition alone — its own review is still
    `PENDING`, which is what makes the membership code the right answer.

    Design: Corner/state_machines/certify_second_review_on_suspended_agency_returns_membership_terminal
    """
    admin = make_admin_headers()
    finance = make_finance_reviewer_headers()
    agency = create_agency(
        legal_name="Lakeshore Rescue Mission",
        ein="600000006",
        primary_priority_area="BASIC_NEEDS",
    )
    first_review = file_review(agency["id"], fiscal_year=2025, **SELF_REPORTED_FAIL)
    second_review = file_review(agency["id"], fiscal_year=2024, **SELF_REPORTED_FAIL)
    assert_money(first_review["preliminary_score"], "0.00", "preliminary_score")

    certified = validate_success(
        api_client.certify_agency_review(
            agency["id"], first_review["id"], certify_payload(**AUDITED_FAIL), finance
        )
    )
    assert_money(certified["certified_score"], "0.00", "certified_score")
    assert_is_false(certified["standards_met"], "standards_met")

    suspended = validate_success(api_client.get_agency(agency["id"], admin))
    assert suspended["membership_status"] == "SUSPENDED_MEMBERSHIP"
    assert_money(suspended["latest_standing_score"], "0.00", "latest_standing_score")

    validate_error(
        api_client.certify_agency_review(
            agency["id"], second_review["id"], certify_payload(**AUDITED_FAIL), finance
        ),
        ERR_AGENCY_MEMBERSHIP_TERMINAL,
        409,
    )

    reviews, _ = validate_paginated(api_client.list_agency_reviews(agency["id"], admin))
    untouched = require_by(reviews, "id", second_review["id"])
    assert untouched["status"] == "PENDING", "the refused certification left the review alone"
    assert_is_null(untouched["certified_score"], "certified_score")


def test_a_frozen_cycle_refuses_another_seat_while_keeping_the_pool_it_funded():
    """PRD 3.7: "Seating is refused on a `FROZEN` cycle with `ERR_CYCLE_FROZEN`."

    PRD 3.7: "Freezing, also available to those two roles, is the deliberate end of a
    cycle: `OPEN → FROZEN` or `RESTRICTED → FROZEN`, with `awards_blocked` set to true."

    Freezing ends the cycle without emptying it: the pool the opening transition funded
    is still readable afterwards.

    Design: Corner/state_machines/panel_assignment_and_cycle_open_on_frozen_cycle_return_cycle_frozen
    """
    admin = make_admin_headers()
    director = make_allocations_director_headers()
    seated_panelist = create_panelist(
        full_name="Ivy Chen", email="ivy.chen@panel.example", expertise_area="HEALTH"
    )
    unseated_panelist = create_panelist(
        full_name="Owen Blake", email="owen.blake@panel.example", expertise_area="FINANCE"
    )
    cycle = create_cycle(
        cycle_year=2026,
        focus_priority_area="HEALTH",
        opening_undesignated_pool="200000.00",
        max_award_per_agency="90000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    seat = seat_panelist(
        cycle["id"], seated_panelist["id"], conflict_declared=False, assignment_role="CHAIR"
    )
    opened = validate_success(api_client.open_allocation_cycle(cycle["id"], director))
    assert opened["posture"] == "OPEN"
    assert_money(
        opened["available_undesignated_pool"], "200000.00", "available_undesignated_pool"
    )

    frozen = validate_success(api_client.freeze_allocation_cycle(cycle["id"], director))
    assert frozen["posture"] == "FROZEN"
    assert_is_true(frozen["awards_blocked"], "awards_blocked")
    assert_money(
        frozen["available_undesignated_pool"], "200000.00", "available_undesignated_pool"
    )

    validate_error(
        api_client.create_panel_assignment(
            cycle["id"],
            panel_assignment_payload(
                unseated_panelist["id"], conflict_declared=False, assignment_role="SCORER"
            ),
            admin,
        ),
        ERR_CYCLE_FROZEN,
        409,
    )

    roster, meta = validate_paginated(
        api_client.list_cycle_panel_assignments(cycle["id"], admin)
    )
    assert meta["total_count"] == 1, "the refused seating added nobody to the panel"
    assert roster[0]["id"] == seat["id"]

    reread = validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
    assert reread["posture"] == "FROZEN"
    assert_is_true(reread["awards_blocked"], "awards_blocked")
    assert_money(
        reread["available_undesignated_pool"], "200000.00", "available_undesignated_pool"
    )
    assert_money(reread["awarded_total"], "0.00", "awarded_total")


def test_confirming_a_pledge_fires_every_declared_side_effect_at_once():
    """PRD 3.3: "Either way, confirmation re-derives the campaign's
    `confirmed_gross_total`, `designated_gross_total`, `undesignated_gross_total` and
    `designation_fee_total`, re-derives the recording coordinator's
    `recorded_pledge_count`, and re-derives `designated_passthrough_ytd` for every
    agency the pledge designates."

    One 400.00 pledge carrying a single 300.00 line makes every one of those effects
    observable in a single hop.

    Design: Corner/state_machines/pledge_confirm_recomputes_campaign_totals_and_coordinator_count
    """
    admin = make_admin_headers()
    agency = create_agency(
        legal_name="Greenfield Food Pantry",
        ein="600000007",
        primary_priority_area="BASIC_NEEDS",
    )
    review = file_review(agency["id"], **SELF_REPORTED_PASS)
    validate_success(
        api_client.certify_agency_review(
            agency["id"],
            review["id"],
            certify_payload(**AUDITED_UNCHANGED),
            make_finance_reviewer_headers(),
        )
    )
    employer = create_active_employer(
        legal_name="Stonebridge Clinic Group", employee_count=220
    )
    coordinator = create_coordinator(
        employer["id"],
        full_name="Priya Nair",
        email="priya.nair@stonebridge.example",
        coordinator_role="LEAD",
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )
    pledge = validate_success(
        api_client.create_pledge(
            campaign["id"],
            pledge_payload(
                donor_reference="C-001",
                giving_method="PAYROLL_DEDUCTION",
                gross_amount="400.00",
                designations=[designation_line(agency["id"], "300.00")],
            ),
            make_coordinator_headers(coordinator["id"]),
        ),
        201,
    )

    confirmed = validate_success(api_client.confirm_pledge(pledge["id"], admin))

    assert confirmed["designation_status"] == "CONFIRMED"
    assert confirmed["collection_status"] == "PENDING"
    assert_money(confirmed["designated_amount_total"], "300.00", "designated_amount_total")
    assert_money(confirmed["undesignated_amount"], "100.00", "undesignated_amount")
    assert_money(confirmed["designation_fee_total"], "21.75", "designation_fee_total")
    assert_money(confirmed["net_designated_total"], "278.25", "net_designated_total")

    reread_campaign = validate_success(api_client.get_campaign(campaign["id"], admin))
    assert_money(reread_campaign["confirmed_gross_total"], "400.00", "confirmed_gross_total")
    assert_money(reread_campaign["designated_gross_total"], "300.00", "designated_gross_total")
    assert_money(
        reread_campaign["undesignated_gross_total"], "100.00", "undesignated_gross_total"
    )
    assert_money(
        reread_campaign["designation_fee_total"], "21.75", "campaign designation_fee_total"
    )

    roster, _ = validate_paginated(
        api_client.list_employer_coordinators(employer["id"], admin)
    )
    assert require_by(roster, "id", coordinator["id"])["recorded_pledge_count"] == 1

    reread_agency = validate_success(api_client.get_agency(agency["id"], admin))
    assert_money(
        reread_agency["designated_passthrough_ytd"],
        "0.00",
        "designated_passthrough_ytd",
    )


def test_severe_shrinkage_climbs_from_the_campaign_to_the_employer_and_its_roster():
    """PRD 3.5: "When it is 1500 or more, the boundary value 1500 itself counting as
    severe, the campaign lands in `SOLICITATION_CLOSED → ESCROW_HOLD` and the
    escrow-hold cascade fires: the host employer is forced `ACTIVE → SUSPENDED` with
    `suspended_reason` set to `ESCROW_HOLD_SHRINKAGE`, and every coordinator seated at
    that employer flips `ACTIVE → INACTIVE`."

    A single 1000.00 payroll pledge written off against a 0.00 reserve is a total loss
    of the confirmed gross — 10000 basis points — so reconciliation takes the severe
    fork and the consequences climb the hierarchy rather than descending it.

    Design: Corner/state_machines/campaign_escrow_hold_bubbles_up_to_employer_suspension_and_coordinator_inactivation
    """
    admin = make_admin_headers()
    finance = make_finance_reviewer_headers()
    employer = create_active_employer(
        legal_name="Talon Freight Systems",
        employee_count=95,
        payroll_periods_per_year=26,
        historical_shrinkage_rate_bps=800,
    )
    lead = create_coordinator(
        employer["id"],
        full_name="Karl Osei",
        email="karl.osei@talon.example",
        coordinator_role="LEAD",
    )
    department = create_coordinator(
        employer["id"],
        full_name="Rosa Lin",
        email="rosa.lin@talon.example",
        coordinator_role="DEPARTMENT",
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    pledge = create_pledge(
        campaign["id"],
        donor_reference="E-001",
        giving_method="PAYROLL_DEDUCTION",
        gross_amount="1000.00",
    )
    validate_success(api_client.confirm_pledge(pledge["id"], admin))
    validate_success(
        api_client.write_off_pledge(
            pledge["id"], write_off_payload(reason_code="EMPLOYER_DEFAULT"), finance
        )
    )

    closed = validate_success(api_client.close_campaign_solicitation(campaign["id"], admin))
    assert closed["posture"] == "SOLICITATION_CLOSED"
    assert_money(
        closed["provisional_estimated_loss"], "0.00", "provisional_estimated_loss"
    )
    assert_money(
        closed["projected_payroll_pledge_total"], "0.00", "projected_payroll_pledge_total"
    )

    reconciled = validate_success(api_client.reconcile_campaign(campaign["id"], admin))

    assert reconciled["posture"] == "ESCROW_HOLD"
    assert_money(reconciled["reserve_absorbed_amount"], "0.00", "reserve_absorbed_amount")
    assert_money(reconciled["final_actual_loss"], "1000.00", "final_actual_loss")
    assert_money(
        reconciled["final_net_expected_revenue"], "0.00", "final_net_expected_revenue"
    )
    assert_bps(reconciled["realized_shrinkage_rate_bps"], 10000, "realized_shrinkage_rate_bps")
    assert reconciled["reconciled_at"] is not None
    assert reconciled["reconciled_at"].startswith("2026-08-01"), (
        "the stamp comes from the logical clock, which sits at its default"
    )

    reread_pledge = validate_success(api_client.get_pledge(pledge["id"], admin))
    assert reread_pledge["designation_status"] == "LOCKED"

    reread_employer = validate_success(api_client.get_employer(employer["id"], admin))
    assert reread_employer["status"] == "SUSPENDED"
    assert reread_employer["suspended_reason"] == "ESCROW_HOLD_SHRINKAGE"

    roster, meta = validate_paginated(
        api_client.list_employer_coordinators(employer["id"], admin)
    )
    assert meta["total_count"] == 2
    assert require_by(roster, "id", lead["id"])["status"] == "INACTIVE"
    assert require_by(roster, "id", department["id"])["status"] == "INACTIVE"
