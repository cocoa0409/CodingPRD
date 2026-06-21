"""Cross-entity cascades and state dependencies.

Covers difficulty queue A:
  - transitive_cascade / denied_appeal_dismissal_withdraws_terminates_decrements_site
  - non_linear_state_machine / agreement_loa_cycle_enrolled_loa_enrolled
  - cross_entity_state_dependency / externship_begin_requires_agreement_enrolled
  - cross_entity_state_dependency / cohort_complete_requires_no_open_agreements
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["system_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
ADVISOR = TEST_USERS["academic_advisor_headers"]


# --------------------------------------------------------------------------
# transitive_cascade / denied_appeal_dismissal_withdraws_terminates_decrements_site
# --------------------------------------------------------------------------
def test_denied_appeal_cascade_withdraws_agreement(api):
    """PRD §3.5: "A DENY moves appeal_status to APPEAL_DENIED; if this review is
    the agreement's latest SapStanding and its standing is DISMISSED, the parent
    agreement is cascade-withdrawn — its withdrawal_term_index is set to the
    clock's current_term_index, the cohort's enrolled_count decreases by 1 and the
    cohort's version increments, every PLACED or IN_PROGRESS externship assignment
    of the agreement is terminated with the corresponding site
    active_assignment_count decrements and site version increments, and the
    agreement's version increments."

    Design: Difficulty/transitive_cascade/denied_appeal_dismissal_withdraws_terminates_decrements_site
    """
    program, cohort, agreement, dismissed = fx.setup_dismissed_sap_standing()
    # Place an externship at a capacity-1 site so site.active_assignment_count == 1.
    site = fx.create_active_site(daily_slot_capacity=1)
    assignment = fx.place_assignment(agreement["id"], site["id"], start_term_index=1,
                                     end_term_index=4, planned_hours=100)
    site_before = validate_success(api.get_externship_site(site["id"], ADVISOR))
    assert site_before["active_assignment_count"] == 1, site_before

    validate_success(api.appeal_sap_standing(dismissed["id"], ADVISOR))
    validate_success(api.resolve_appeal(dismissed["id"], {"decision": "DENY"}, ADVISOR))

    agr_after = validate_success(api.get_agreement(agreement["id"], REGISTRAR))
    assert agr_after["status"] == "WITHDRAWN", agr_after


def test_denied_appeal_cascade_terminates_externship_and_decrements_site(api):
    """PRD §3.5: "every PLACED or IN_PROGRESS externship assignment of the
    agreement is terminated with the corresponding site active_assignment_count
    decrements and site version increments ..."
    PRD §3.8: "Terminating an externship from either PLACED or IN_PROGRESS (else
    ERR_INVALID_STATE) moves it to TERMINATED, decrements the site's
    active_assignment_count by 1, and increments the site's version."

    Design: Difficulty/transitive_cascade/denied_appeal_dismissal_withdraws_terminates_decrements_site
    """
    program, cohort, agreement, dismissed = fx.setup_dismissed_sap_standing()
    site = fx.create_active_site(daily_slot_capacity=1)
    assignment = fx.place_assignment(agreement["id"], site["id"], start_term_index=1,
                                     end_term_index=4, planned_hours=100)

    validate_success(api.appeal_sap_standing(dismissed["id"], ADVISOR))
    validate_success(api.resolve_appeal(dismissed["id"], {"decision": "DENY"}, ADVISOR))

    asn_after = validate_success(api.get_assignment(assignment["id"], ADVISOR))
    assert asn_after["status"] == "TERMINATED", asn_after
    site_after = validate_success(api.get_externship_site(site["id"], ADVISOR))
    assert site_after["active_assignment_count"] == 0, site_after


# --------------------------------------------------------------------------
# non_linear_state_machine / agreement_loa_cycle_enrolled_loa_enrolled
# --------------------------------------------------------------------------
def test_agreement_start_loa_moves_to_leave_of_absence(api):
    """PRD §3.3: "Starting a leave of absence requires the agreement to be
    ENROLLED (else ERR_INVALID_STATE) and its sap_standing to be anything other
    than DISMISSED (else ERR_SAP_DISMISSED), moving it to LEAVE_OF_ABSENCE."

    Design: Difficulty/non_linear_state_machine/agreement_loa_cycle_enrolled_loa_enrolled
    """
    _, _, agreement = fx.setup_enrolled_agreement(
        agreement_overrides={"contract_tuition_cents": 600_000},
        program_overrides={"tuition_cents": 600_000},
    )
    after_loa = validate_success(api.start_loa(agreement["id"], ADVISOR))
    assert after_loa["status"] == "LEAVE_OF_ABSENCE", after_loa


def test_agreement_return_from_loa_cycles_back_to_enrolled(api):
    """PRD §3.3: "Returning from leave requires the agreement to be
    LEAVE_OF_ABSENCE (else ERR_INVALID_STATE) and moves it back to ENROLLED."

    Design: Difficulty/non_linear_state_machine/agreement_loa_cycle_enrolled_loa_enrolled
    """
    _, _, agreement = fx.setup_enrolled_agreement(
        agreement_overrides={"contract_tuition_cents": 600_000},
        program_overrides={"tuition_cents": 600_000},
    )
    validate_success(api.start_loa(agreement["id"], ADVISOR))
    after_return = validate_success(api.return_from_loa(agreement["id"], ADVISOR))
    assert after_return["status"] == "ENROLLED", after_return


# --------------------------------------------------------------------------
# cross_entity_state_dependency / externship_begin_requires_agreement_enrolled
# --------------------------------------------------------------------------
def test_externship_begin_blocked_when_agreement_on_leave(api):
    """PRD §3.8: "Beginning an externship moves it PLACED → IN_PROGRESS: it
    requires the assignment to be PLACED (else ERR_INVALID_STATE), the clock's
    current_term_index to have reached at least the assignment's start_term_index
    (else ERR_EXTERNSHIP_NOT_STARTED), and the parent agreement to be ENROLLED
    (else ERR_AGREEMENT_NOT_ACTIVE)."

    Design: Difficulty/cross_entity_state_dependency/externship_begin_requires_agreement_enrolled
    """
    # Place an assignment with start 0, advance clock past start, then move
    # agreement to LEAVE_OF_ABSENCE so only the ENROLLED precondition fails.
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 500_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
        agreement_overrides={"contract_tuition_cents": 500_000},
    )
    site = fx.create_active_site(daily_slot_capacity=3)
    assignment = fx.place_assignment(agreement["id"], site["id"], start_term_index=0,
                                     end_term_index=4, planned_hours=100)
    fx.advance_clock_to(1)
    validate_success(api.start_loa(agreement["id"], ADVISOR))

    resp = api.begin_assignment(assignment["id"], ADVISOR)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)


def test_externship_begin_succeeds_when_agreement_enrolled(api):
    """PRD §3.8: "Beginning an externship moves it PLACED → IN_PROGRESS: it
    requires the assignment to be PLACED (else ERR_INVALID_STATE), the clock's
    current_term_index to have reached at least the assignment's start_term_index
    (else ERR_EXTERNSHIP_NOT_STARTED), and the parent agreement to be ENROLLED
    (else ERR_AGREEMENT_NOT_ACTIVE)."

    Design: Difficulty/cross_entity_state_dependency/externship_begin_requires_agreement_enrolled
    """
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 500_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
        agreement_overrides={"contract_tuition_cents": 500_000},
    )
    site = fx.create_active_site(daily_slot_capacity=3)
    assignment = fx.place_assignment(agreement["id"], site["id"], start_term_index=0,
                                     end_term_index=4, planned_hours=100)
    fx.advance_clock_to(1)
    # Agreement stays ENROLLED -> begin succeeds.
    began = validate_success(api.begin_assignment(assignment["id"], ADVISOR))
    assert began["status"] == "IN_PROGRESS", began


# --------------------------------------------------------------------------
# cross_entity_state_dependency / cohort_complete_requires_no_open_agreements
# --------------------------------------------------------------------------
def test_cohort_complete_blocked_by_open_agreement(api):
    """PRD §3.3: "Completing a cohort moves it RUNNING → COMPLETED; it requires
    the cohort to be RUNNING (else ERR_INVALID_STATE) and that no agreement of the
    cohort is still in ENROLLED or LEAVE_OF_ABSENCE (else
    ERR_OPEN_AGREEMENTS_EXIST)."

    Design: Difficulty/cross_entity_state_dependency/cohort_complete_requires_no_open_agreements
    """
    _, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"tuition_cents": 500_000},
        agreement_overrides={"contract_tuition_cents": 500_000},
    )
    resp = api.complete_cohort(cohort["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_OPEN_AGREEMENTS_EXIST.value)


def test_cohort_complete_succeeds_when_no_open_agreements(api):
    """PRD §3.3: "Completing a cohort moves it RUNNING → COMPLETED; it requires
    the cohort to be RUNNING (else ERR_INVALID_STATE) and that no agreement of the
    cohort is still in ENROLLED or LEAVE_OF_ABSENCE (else
    ERR_OPEN_AGREEMENTS_EXIST)."

    Design: Difficulty/cross_entity_state_dependency/cohort_complete_requires_no_open_agreements
    """
    # A cohort with only a CANCELLED (DRAFTED->CANCELLED) agreement has no open
    # agreement, so completion succeeds.
    program, cohort = fx.setup_program_and_cohort(
        program_overrides={"tuition_cents": 500_000})
    agr = fx.create_drafted_agreement(cohort["id"], contract_tuition_cents=500_000)
    validate_success(api.cancel_agreement(agr["id"], REGISTRAR))
    completed = validate_success(api.complete_cohort(cohort["id"], REGISTRAR))
    assert completed["status"] == "COMPLETED", completed
