"""Composite setup helpers.

These encapsulate the multi-step API sequences that put the system into the
states the tests need. Setup calls use get_success_data() so a broken
precondition surfaces as a clear "Setup failed" rather than an assertion error.

The harness restarts the server (empty DB) before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

ADMIN = TEST_USERS["system_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
FAID = TEST_USERS["financial_aid_officer_headers"]
ADVISOR = TEST_USERS["academic_advisor_headers"]


# --------------------------------------------------------------------------
# Tier 0: clock control
# --------------------------------------------------------------------------
def advance_clock_to(term_index: int):
    """Advance the deterministic term clock to term_index (PRD §3.1)."""
    return get_success_data(api_client.advance_clock({"to_term_index": term_index}, ADMIN))


# --------------------------------------------------------------------------
# Tier 1: configuration building blocks
# --------------------------------------------------------------------------
def create_open_program(**overrides) -> dict:
    """Create a program and open it (DRAFT -> OPEN). Returns the OPEN program."""
    prog = get_success_data(api_client.create_program(f.create_program_payload(**overrides), ADMIN))
    get_success_data(api_client.open_program(prog["id"], ADMIN))
    return get_success_data(api_client.get_program(prog["id"], ADMIN))


def create_running_cohort(program_id: str, **overrides) -> dict:
    """Create a cohort under an OPEN program and start it (FORMING -> RUNNING).

    Cohort start requires clock.current_term_index >= start_term_index; default
    start_term_index is 0, so the freshly-reset clock (0) satisfies it.
    """
    cohort = get_success_data(api_client.create_cohort(f.create_cohort_payload(program_id, **overrides), REGISTRAR))
    get_success_data(api_client.start_cohort(cohort["id"], REGISTRAR))
    return get_success_data(api_client.get_cohort(cohort["id"], REGISTRAR))


def create_student(**overrides) -> dict:
    return get_success_data(api_client.create_student(f.create_student_payload(**overrides), REGISTRAR))


def create_active_site(**overrides) -> dict:
    return get_success_data(api_client.create_externship_site(f.create_externship_site_payload(**overrides), ADVISOR))


# --------------------------------------------------------------------------
# Tier 2: program + cohort base setup
# --------------------------------------------------------------------------
def setup_program_and_cohort(program_overrides=None, cohort_overrides=None):
    """Active program + RUNNING cohort. Returns (program, cohort)."""
    program = create_open_program(**(program_overrides or {}))
    cohort = create_running_cohort(program["id"], **(cohort_overrides or {}))
    return program, cohort


# --------------------------------------------------------------------------
# Tier 3: agreement lifecycle
# --------------------------------------------------------------------------
def create_drafted_agreement(cohort_id, student_id=None, **overrides) -> dict:
    """Draft an agreement (DRAFTED). Creates a student if not provided."""
    if student_id is None:
        student_id = create_student()["id"]
    return get_success_data(
        api_client.create_agreement(f.create_agreement_payload(student_id, cohort_id, **overrides), REGISTRAR)
    )


def create_enrolled_agreement(cohort_id, student_id=None, **overrides) -> dict:
    """Draft + enroll an agreement (DRAFTED -> ENROLLED). Returns the ENROLLED agreement."""
    agr = create_drafted_agreement(cohort_id, student_id, **overrides)
    get_success_data(api_client.enroll_agreement(agr["id"], REGISTRAR))
    return get_success_data(api_client.get_agreement(agr["id"], REGISTRAR))


def setup_enrolled_agreement(program_overrides=None, cohort_overrides=None, agreement_overrides=None):
    """Full chain through one ENROLLED agreement.

    Returns (program, cohort, agreement).
    """
    program, cohort = setup_program_and_cohort(program_overrides, cohort_overrides)
    agreement = create_enrolled_agreement(cohort["id"], **(agreement_overrides or {}))
    return program, cohort, agreement


# --------------------------------------------------------------------------
# Tier 3b: attendance helpers
# --------------------------------------------------------------------------
def post_attendance(agreement_id, kind="THEORY", scheduled_hours=10, attended_hours=10, term_index=1) -> dict:
    """Post one attendance entry (POSTED) against an active agreement."""
    return get_success_data(
        api_client.create_attendance_entry(
            f.create_attendance_entry_payload(
                agreement_id,
                kind=kind,
                scheduled_hours=scheduled_hours,
                attended_hours=attended_hours,
                term_index=term_index,
            ),
            ADVISOR,
        )
    )


def setup_agreement_with_theory_hours(theory_hours, program_overrides=None, cohort_overrides=None,
                                      agreement_overrides=None, term_index=1):
    """ENROLLED agreement with `theory_hours` of POSTED THEORY attendance
    (scheduled == attended). Returns (program, cohort, agreement_refetched).
    """
    program, cohort, agreement = setup_enrolled_agreement(program_overrides, cohort_overrides, agreement_overrides)
    post_attendance(agreement["id"], kind="THEORY", scheduled_hours=theory_hours,
                    attended_hours=theory_hours, term_index=term_index)
    agreement = get_success_data(api_client.get_agreement(agreement["id"], REGISTRAR))
    return program, cohort, agreement


# --------------------------------------------------------------------------
# Tier 3c: graduation-ready agreement
# --------------------------------------------------------------------------
def setup_graduated_agreement(program_overrides=None, cohort_overrides=None,
                              agreement_overrides=None):
    """ENROLLED agreement built up to GRADUATED via full hours and zero balance.

    Uses a 1000h program (600 theory + 400 externship). Contract tuition is
    forced to 0 so ledger_balance is 0 (graduation gate). Posts 600 THEORY and
    400 EXTERNSHIP attended hours, then graduates. Returns (program, cohort,
    agreement_refetched).
    """
    prog_ov = {"required_clock_hours": 1000, "required_theory_hours": 600,
               "required_externship_hours": 400, "tuition_cents": 0}
    prog_ov.update(program_overrides or {})
    agr_ov = {"contract_tuition_cents": 0}
    agr_ov.update(agreement_overrides or {})
    program, cohort, agreement = setup_enrolled_agreement(prog_ov, cohort_overrides, agr_ov)
    post_attendance(agreement["id"], kind="THEORY", scheduled_hours=600, attended_hours=600, term_index=1)
    post_attendance(agreement["id"], kind="EXTERNSHIP", scheduled_hours=400, attended_hours=400, term_index=2)
    get_success_data(api_client.graduate_agreement(agreement["id"], REGISTRAR))
    agreement = get_success_data(api_client.get_agreement(agreement["id"], REGISTRAR))
    return program, cohort, agreement


# --------------------------------------------------------------------------
# Tier 4: aid disbursement
# --------------------------------------------------------------------------
def schedule_disbursement(agreement_id, disbursement_index=1, planned_amount_cents=200_000,
                          required_clock_hours_gate=0) -> dict:
    return get_success_data(
        api_client.create_disbursement(
            f.create_disbursement_payload(
                agreement_id,
                disbursement_index=disbursement_index,
                planned_amount_cents=planned_amount_cents,
                required_clock_hours_gate=required_clock_hours_gate,
            ),
            FAID,
        )
    )


def release_disbursement(disbursement_id) -> dict:
    return get_success_data(api_client.release_disbursement(disbursement_id, FAID))


def setup_agreement_with_released_aid(draw_amounts, scheduled_aid_cents=None,
                                      contract_tuition_cents=1_000_000,
                                      program_overrides=None, cohort_overrides=None,
                                      theory_hours=250):
    """ENROLLED agreement with N RELEASED aid draws (gate 0).

    draw_amounts: list of planned_amount_cents, released in index order.
    Posts `theory_hours` THEORY attendance first so any gate>0 would also pass.
    Returns (program, cohort, agreement_refetched, [disbursement_ids]).
    """
    if scheduled_aid_cents is None:
        scheduled_aid_cents = sum(draw_amounts)
    prog_ov = {"required_clock_hours": 1000, "tuition_cents": contract_tuition_cents}
    prog_ov.update(program_overrides or {})
    agr_ov = {"contract_tuition_cents": contract_tuition_cents,
              "scheduled_aid_cents": scheduled_aid_cents}
    program, cohort, agreement = setup_enrolled_agreement(prog_ov, cohort_overrides, agr_ov)
    if theory_hours > 0:
        post_attendance(agreement["id"], kind="THEORY", scheduled_hours=theory_hours,
                        attended_hours=theory_hours, term_index=1)
    disb_ids = []
    for i, amt in enumerate(draw_amounts, start=1):
        d = schedule_disbursement(agreement["id"], disbursement_index=i, planned_amount_cents=amt,
                                  required_clock_hours_gate=0)
        disb_ids.append(d["id"])
    for did in disb_ids:
        release_disbursement(did)
    agreement = get_success_data(api_client.get_agreement(agreement["id"], REGISTRAR))
    return program, cohort, agreement, disb_ids


# --------------------------------------------------------------------------
# Tier 5: withdrawal + refund
# --------------------------------------------------------------------------
def withdraw_agreement(agreement_id) -> dict:
    get_success_data(api_client.withdraw_agreement(agreement_id, REGISTRAR))
    return get_success_data(api_client.get_agreement(agreement_id, REGISTRAR))


def setup_withdrawn_agreement_for_refund(theory_hours=250, contract_tuition_cents=1_000_000,
                                         scheduled_aid_cents=0, withdrawal_clock_term=6,
                                         cancellation_window_term_index=0,
                                         cohort_overrides=None, program_overrides=None,
                                         released_draws=None):
    """ENROLLED agreement with `theory_hours` THEORY hours, optionally with
    RELEASED aid draws, advanced to `withdrawal_clock_term` and WITHDRAWN.

    Returns (program, cohort, agreement_refetched, [disbursement_ids]).
    """
    prog_ov = {"required_clock_hours": 1000, "required_theory_hours": 600,
               "required_externship_hours": 400, "tuition_cents": contract_tuition_cents}
    prog_ov.update(program_overrides or {})
    coh_ov = {"start_term_index": 0, "end_term_index": 8, "seat_capacity": 5}
    coh_ov.update(cohort_overrides or {})
    agr_ov = {"contract_tuition_cents": contract_tuition_cents,
              "scheduled_aid_cents": scheduled_aid_cents,
              "cancellation_window_term_index": cancellation_window_term_index}
    program, cohort, agreement = setup_enrolled_agreement(prog_ov, coh_ov, agr_ov)
    if theory_hours > 0:
        post_attendance(agreement["id"], kind="THEORY", scheduled_hours=theory_hours,
                        attended_hours=theory_hours, term_index=1)
    disb_ids = []
    if released_draws:
        for i, amt in enumerate(released_draws, start=1):
            d = schedule_disbursement(agreement["id"], disbursement_index=i,
                                      planned_amount_cents=amt, required_clock_hours_gate=0)
            disb_ids.append(d["id"])
        for did in disb_ids:
            release_disbursement(did)
    advance_clock_to(withdrawal_clock_term)
    agreement = withdraw_agreement(agreement["id"])
    return program, cohort, agreement, disb_ids


def create_refund_case(agreement_id, method="PRO_RATA", withdrawal_term_index=6) -> dict:
    return get_success_data(
        api_client.create_refund_case(
            f.create_refund_case_payload(agreement_id, method=method,
                                         withdrawal_term_index=withdrawal_term_index),
            FAID,
        )
    )


def setup_computed_refund_case(theory_hours=250, contract_tuition_cents=1_000_000,
                               scheduled_aid_cents=400_000, withdrawal_clock_term=6,
                               method="PRO_RATA", released_draws=(200_000, 200_000)):
    """Full chain to a COMPUTED refund case on a WITHDRAWN agreement with
    RELEASED aid draws. Returns (program, cohort, agreement_refetched,
    [disbursement_ids], refund_case, current_agreement_version).
    """
    program, cohort, agreement, disb_ids = setup_withdrawn_agreement_for_refund(
        theory_hours=theory_hours, contract_tuition_cents=contract_tuition_cents,
        scheduled_aid_cents=scheduled_aid_cents, withdrawal_clock_term=withdrawal_clock_term,
        released_draws=list(released_draws) if released_draws else None,
    )
    refund = create_refund_case(agreement["id"], method=method,
                                withdrawal_term_index=withdrawal_clock_term)
    agreement = get_success_data(api_client.get_agreement(agreement["id"], REGISTRAR))
    return program, cohort, agreement, disb_ids, refund, agreement["version"]


# --------------------------------------------------------------------------
# Tier 6: SAP standing chains
# --------------------------------------------------------------------------
def run_sap_review(agreement_id, checkpoint_term_index) -> dict:
    return get_success_data(
        api_client.create_sap_standing(
            f.create_sap_standing_payload(agreement_id, checkpoint_term_index=checkpoint_term_index),
            ADVISOR,
        )
    )


def setup_dismissed_sap_standing(cohort_span_end=8, theory_hours=250):
    """ENROLLED agreement carrying a DISMISSED latest SapStanding.

    Built via a prior WARNING review (checkpoint 4) then a sub-floor review
    (checkpoint 6) that escalates to DISMISSED. Program uses default SAP
    thresholds (warning 0.667, probation 0.5) and 1000 required clock hours.
    With 250 THEORY hours: at checkpoint 4 expected=500 -> pace 0.5 (WARNING);
    at checkpoint 6 expected=750 -> pace 0.3333 (<0.5) with prior WARNING ->
    DISMISSED.
    Returns (program, cohort, agreement_refetched, dismissed_sap_standing).
    """
    program, cohort, agreement = setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 700_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": cohort_span_end},
        agreement_overrides={"contract_tuition_cents": 700_000},
    )
    post_attendance(agreement["id"], kind="THEORY", scheduled_hours=theory_hours,
                    attended_hours=theory_hours, term_index=1)
    run_sap_review(agreement["id"], checkpoint_term_index=4)   # WARNING
    dismissed = run_sap_review(agreement["id"], checkpoint_term_index=6)  # DISMISSED
    agreement = get_success_data(api_client.get_agreement(agreement["id"], REGISTRAR))
    return program, cohort, agreement, dismissed


# --------------------------------------------------------------------------
# Tier 7: externship assignment
# --------------------------------------------------------------------------
def place_assignment(agreement_id, site_id, start_term_index=1, end_term_index=4,
                     planned_hours=100) -> dict:
    return get_success_data(
        api_client.create_assignment(
            f.create_assignment_payload(agreement_id, site_id, start_term_index=start_term_index,
                                        end_term_index=end_term_index, planned_hours=planned_hours),
            ADVISOR,
        )
    )


def setup_enrolled_with_placed_assignment(site_capacity=3, start_term_index=1, end_term_index=4,
                                          planned_hours=100, theory_hours=250):
    """ENROLLED agreement + ACTIVE site + one PLACED assignment.

    Returns (program, cohort, agreement, site, assignment).
    """
    program, cohort, agreement = setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 500_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 10},
        agreement_overrides={"contract_tuition_cents": 500_000},
    )
    if theory_hours > 0:
        post_attendance(agreement["id"], kind="THEORY", scheduled_hours=theory_hours,
                        attended_hours=theory_hours, term_index=0)
    site = create_active_site(daily_slot_capacity=site_capacity)
    assignment = place_assignment(agreement["id"], site["id"], start_term_index=start_term_index,
                                  end_term_index=end_term_index, planned_hours=planned_hours)
    return program, cohort, agreement, site, assignment
