"""Case creation, the petition transition and its gates, invalid transitions,
terminal-state lockdown, the chapter-7/chapter-13 branch from MEETING_HELD, and
the dismiss cascade.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, assert_case, assert_debtor,
    create_case_payload, create_debtor_payload,
    register_debtor, register_trustee, register_creditor, open_case,
    submit_means_test, add_income_and_expense_schedules, add_schedule, add_debt,
    petition, setup_draft_case_ready_to_petition, setup_filed_case,
    setup_case_at_meeting_held, file_stay_relief_motion,
    make_debtor_headers, make_trustee_headers, NON_EXISTENT_UUID,
)


# ─── Creation / defaults / existence (queue B entities, errors) ───────────

def test_create_case_returns_201_with_defaults(api):
    """PRD §3.2: "A freshly opened case begins with status equal to DRAFT,
    stay_posture equal to NONE, and means_test_result equal to NOT_RUN".
    PRD §2.4: "The version is an integer that starts at 1 when the resource is
    created".

    Design: Corner/entities/create_case_returns_201_with_defaults
    """
    debtor = register_debtor(full_name="Create Debtor")
    headers = make_debtor_headers(debtor["id"])
    res = api.create_case(create_case_payload(
        debtor["id"], filed_chapter="CHAPTER_7", state_code="CA", household_size=2), headers)
    case = validate_success(res, 201)
    assert_case(case)
    assert case["status"] == "DRAFT"
    assert case["stay_posture"] == "NONE"
    assert case["means_test_result"] == "NOT_RUN"
    assert case["version"] == 1


def test_get_case_not_found_returns_404(api):
    """PRD §2.6: "the first identifier that does not resolve produces
    ERR_NOT_FOUND (HTTP 404) before any later identifier is examined."

    Design: Corner/entities/get_case_not_found_returns_404
    """
    debtor = register_debtor(full_name="NF Debtor")
    headers = make_debtor_headers(debtor["id"])
    res = api.get_case(NON_EXISTENT_UUID, headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_case_missing_required_field_returns_invalid_request(api):
    """PRD §2.6: "the system verify that required body fields are present and
    that each value falls within its declared type or enumeration domain,
    rejecting violations with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_case_missing_required_field_returns_invalid_request
    """
    debtor = register_debtor(full_name="Missing Debtor")
    headers = make_debtor_headers(debtor["id"])
    payload = create_case_payload(debtor["id"], state_code="CA", household_size=1)
    del payload["filed_chapter"]
    res = api.create_case(payload, headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_case_invalid_chapter_enum_returns_invalid_request(api):
    """PRD §2.6: "the system verify that required body fields are present and
    that each value falls within its declared type or enumeration domain,
    rejecting violations with ERR_INVALID_REQUEST (HTTP 422)."
    PRD §3.2: "the filed_chapter the debtor petitions under — one of CHAPTER_7
    or CHAPTER_13".

    Design: Corner/entities/create_case_invalid_chapter_enum_returns_invalid_request
    """
    debtor = register_debtor(full_name="Enum Debtor")
    headers = make_debtor_headers(debtor["id"])
    res = api.create_case(create_case_payload(
        debtor["id"], filed_chapter="CHAPTER_11", state_code="CA", household_size=1), headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_debtor_default_prior_discharge_false(api):
    """PRD §3.1: "A debtor also carries prior_discharge_within_8y, a boolean
    defaulting to false".

    Design: Corner/entities/create_debtor_default_prior_discharge_false
    """
    res = api.create_debtor(
        create_debtor_payload(full_name="Default Debtor"), make_debtor_headers("bootstrap"))
    debtor = validate_success(res, 201)
    assert_debtor(debtor)
    assert debtor["prior_discharge_within_8y"] is False


def test_case_fk_debtor_not_found_returns_fk_not_found(api):
    """PRD §2.6: "a body foreign key that resolves to nothing produces
    ERR_FK_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/case_fk_debtor_not_found_returns_fk_not_found
    """
    real = register_debtor(full_name="Real Debtor")
    headers = make_debtor_headers(real["id"])
    res = api.create_case(create_case_payload(
        "11111111-1111-1111-1111-111111111111",
        filed_chapter="CHAPTER_7", state_code="CA", household_size=1), headers)
    validate_error(res, "ERR_FK_NOT_FOUND")


# ─── Petition transition + gates (queue B state machine, validations) ─────

def test_petition_from_draft_sets_filed_and_active_stay(api):
    """PRD §3.4: "When the petition succeeds, the case's status becomes FILED,
    its petition_date is set to the filing instant in UTC ..., its stay_posture
    becomes ACTIVE as the automatic stay arises, and its version increments."

    Design: Corner/state_machines/petition_from_draft_sets_filed_and_active_stay
    """
    debtor, case = setup_draft_case_ready_to_petition(filed_chapter="CHAPTER_13")
    headers = make_debtor_headers(debtor["id"])
    res = api.petition_case(case["id"], headers)
    after = validate_success(res, 200)
    assert after["status"] == "FILED"
    assert after["stay_posture"] == "ACTIVE"


def test_petition_missing_schedule_j_returns_invalid_state(api):
    """PRD §3.4: "It is permitted only when the case is still DRAFT, when the
    case has at least one Schedule row of letter I and at least one of letter J
    (income and expense schedules must both exist)".

    Design: Corner/state_machines/petition_missing_schedule_j_returns_invalid_state
    """
    debtor = register_debtor(full_name="NoJ Debtor")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_schedule(debtor, case, "I", description="wages")  # I only, no J
    headers = make_debtor_headers(debtor["id"])
    res = api.petition_case(case["id"], headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_chapter7_petition_with_abuse_presumption_blocked(api):
    """PRD §3.4: "if the case was filed under CHAPTER_7, the case's
    means_test_result must be PRESUMPTION_OK — a presumption of abuse bars a
    Chapter 7 petition, and the attempt is rejected with ERR_MEANS_TEST_ABUSE
    (HTTP 409)."

    Design: Corner/validations/chapter7_petition_with_abuse_presumption_blocked
    """
    debtor = register_debtor(full_name="Abuse7 Debtor", prior_discharge_within_8y=False)
    case = open_case(debtor, filed_chapter="CHAPTER_7")
    # disposable 300,000 * 60 = 18,000,000 >= floor and above median -> PRESUMPTION_ABUSE.
    submit_means_test(debtor, case, cmi_monthly_cents=600000,
                      monthly_expenses_cents=300000, median_annual_income_cents=6000000)
    add_income_and_expense_schedules(debtor, case)
    headers = make_debtor_headers(debtor["id"])
    res = api.petition_case(case["id"], headers)
    validate_error(res, "ERR_MEANS_TEST_ABUSE")
    after = validate_success(api.get_case(case["id"], headers), 200)
    assert after["status"] == "DRAFT"


# ─── Invalid transitions / terminal lockdown (queue B state machine) ──────

def test_confirm_case_from_draft_returns_invalid_state(api):
    """PRD §3.10: "the trustee confirms the case, advancing its status from
    MEETING_HELD to CONFIRMED; this requires that the case be MEETING_HELD".

    Design: Corner/state_machines/confirm_case_from_draft_returns_invalid_state
    """
    debtor = register_debtor(full_name="Inv Debtor")
    trustee = register_trustee(name="T-inv")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    res = api.confirm_case(case["id"], make_trustee_headers(trustee["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_dismiss_from_discharged_terminal_returns_invalid_state(api):
    """PRD §3.10: "Dismissal ... may be ordered by the trustee while the case is
    FILED, MEETING_HELD, or CONFIRMED." And: "Both DISCHARGED and DISMISSED are
    terminal case states."

    Design: Corner/state_machines/dismiss_from_discharged_terminal_returns_invalid_state
    """
    debtor, trustee, case = setup_case_at_meeting_held(
        filed_chapter="CHAPTER_7", prior_discharge_within_8y=False,
        room_code="R-term", scheduled_start="2026-09-01T09:00:00Z",
        scheduled_end="2026-09-01T10:00:00Z")
    t_headers = make_trustee_headers(trustee["id"])
    validate_success(api.discharge_case(case["id"], t_headers), 200)
    res = api.dismiss_case(case["id"], t_headers)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Chapter 7 / 13 branch from MEETING_HELD (queue A) ────────────────────

def test_chapter7_discharge_branch_wipes_unsecured(api):
    """PRD §3.10: "On the Chapter 7 path it advances the case from MEETING_HELD
    to DISCHARGED". And: "discharge sets the case's status to DISCHARGED and its
    stay_posture to TERMINATED, reduces the allowed_amount_cents of every debt of
    class UNSECURED to zero (those debts are discharged) while leaving SECURED
    and PRIORITY debts intact".

    Design: Difficulty/non_linear_state_machine/case_branch_chapter7_vs_chapter13_after_meeting
    """
    debtor = register_debtor(full_name="Branch Debtor", prior_discharge_within_8y=False)
    trustee = register_trustee(name="T-BR")
    creditor = register_creditor(name="Cr BR")
    case = open_case(debtor, filed_chapter="CHAPTER_7", state_code="NY")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    u_debt = add_debt(debtor, case, creditor, "UNSECURED", 80000)
    case = petition(debtor, case)
    from test_helpers import schedule_meeting, hold_meeting
    meeting = schedule_meeting(trustee, case, room_code="R-BR",
                               scheduled_start="2026-07-02T09:00:00Z",
                               scheduled_end="2026-07-02T10:00:00Z")
    hold_meeting(trustee, meeting)

    t_headers = make_trustee_headers(trustee["id"])
    res = api.discharge_case(case["id"], t_headers)
    after = validate_success(res, 200)
    assert after["status"] == "DISCHARGED"
    assert after["stay_posture"] == "TERMINATED"

    debt_after = validate_success(api.get_debt(u_debt["id"], t_headers), 200)
    assert debt_after["allowed_amount_cents"] == 0


def test_chapter13_confirm_branch_from_meeting_held(api):
    """PRD §3.10: "For a CHAPTER_13 case, the trustee confirms the case,
    advancing its status from MEETING_HELD to CONFIRMED ... A Chapter 7 case skips
    confirmation entirely and proceeds straight from MEETING_HELD to discharge."
    This is the Chapter 13 fork of the same MEETING_HELD branch point.

    Design: Difficulty/non_linear_state_machine/case_branch_chapter7_vs_chapter13_after_meeting
    """
    from test_helpers import (create_plan, file_plan, confirm_plan,
                              schedule_meeting, hold_meeting, submit_means_test,
                              add_income_and_expense_schedules, petition)
    debtor = register_debtor(full_name="Branch13 Debtor")
    trustee = register_trustee(name="T-BR13")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    case = petition(debtor, case)
    plan = create_plan(debtor, case, monthly_payment_cents=50000, plan_duration_months=36)
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-BR13",
                               scheduled_start="2026-07-02T11:00:00Z",
                               scheduled_end="2026-07-02T12:00:00Z")
    hold_meeting(trustee, meeting)
    confirm_plan(trustee, plan)  # no priority debts -> floor 0 -> feasible

    t_headers = make_trustee_headers(trustee["id"])
    res = api.confirm_case(case["id"], t_headers)
    after = validate_success(res, 200)
    assert after["status"] == "CONFIRMED"


# ─── Dismiss cascade (queue A) ─────────────────────────────────────────────

def test_dismiss_terminates_stay_and_moots_pending_motion(api):
    """PRD §3.10: "Dismissal sets the case's status to DISMISSED, sets its
    stay_posture to TERMINATED, moots the case by setting every PENDING
    stay-relief motion on it to DENIED, and increments the case's version."

    Design: Difficulty/transitive_cascade/dismiss_cascade_terminates_stay_and_moots_motion_depth2
    """
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_13")
    creditor = register_creditor(name="Cr DM")
    trustee = register_trustee(name="T-DM")
    s_debt = add_debt(debtor, case, creditor, "SECURED", 300000)
    motion = file_stay_relief_motion(creditor, case, s_debt)

    t_headers = make_trustee_headers(trustee["id"])
    res = api.dismiss_case(case["id"], t_headers)
    after = validate_success(res, 200)
    assert after["status"] == "DISMISSED"
    assert after["stay_posture"] == "TERMINATED"

    motion_after = validate_success(api.get_stay_relief_motion(motion["id"], t_headers), 200)
    assert motion_after["status"] == "DENIED"


def test_dismiss_from_meeting_held_also_terminates_stay_and_moots_motion(api):
    """PRD §3.10: "Dismissal ... may be ordered by the trustee while the case is
    FILED, MEETING_HELD, or CONFIRMED. Dismissal sets the case's status to
    DISMISSED, sets its stay_posture to TERMINATED, moots the case by setting
    every PENDING stay-relief motion on it to DENIED". The same cascade fires from
    a different valid source state (MEETING_HELD).

    Design: Difficulty/transitive_cascade/dismiss_cascade_terminates_stay_and_moots_motion_depth2
    """
    from test_helpers import (schedule_meeting, hold_meeting)
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_13")
    creditor = register_creditor(name="Cr DM2")
    trustee = register_trustee(name="T-DM2")
    s_debt = add_debt(debtor, case, creditor, "SECURED", 300000)
    motion = file_stay_relief_motion(creditor, case, s_debt)
    # Advance the case to MEETING_HELD before dismissing.
    meeting = schedule_meeting(trustee, case, room_code="R-DM2",
                               scheduled_start="2026-07-09T09:00:00Z",
                               scheduled_end="2026-07-09T10:00:00Z")
    hold_meeting(trustee, meeting)

    t_headers = make_trustee_headers(trustee["id"])
    after = validate_success(api.dismiss_case(case["id"], t_headers), 200)
    assert after["status"] == "DISMISSED"
    assert after["stay_posture"] == "TERMINATED"
    motion_after = validate_success(api.get_stay_relief_motion(motion["id"], t_headers), 200)
    assert motion_after["status"] == "DENIED"
