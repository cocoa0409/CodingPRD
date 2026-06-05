"""Emergency extensions (cyclic restore from EXHAUSTED, window enforcement),
apply-extension OCC, and the adjudicate-time availability/work-search gates."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_eligible_claim, make_exhausted_claim,
    create_extension_program, create_employer, create_claimant, add_wage_record,
    create_draft_claim, submit_claim, issue_monetary_determination,
    file_week, adjudicate_week, set_claim_balance,
    make_claimant_headers,
    TEST_USERS,
)

ADJ = TEST_USERS["adjudicator_headers"]
ADMIN = TEST_USERS["program_admin_headers"]


# ── Corner: state_machines / extension_apply_restores_balance_cyclic ──

def test_apply_extension_restores_eligibility_and_grows_mba(api):
    """PRD §3.6: "A successful apply sets the claim's emergency_extension_id to the
    program and extension_weeks_granted to the program's extra_weeks, recomputes
    maximum_benefit_amount_cents by adding the product of extension_weeks_granted
    and the weekly benefit amount to the base maximum ... and transitions the claim
    EXHAUSTED → MONETARILY_ELIGIBLE so further weeks can be paid."

    Design: Corner/state_machines/extension_apply_restores_balance_cyclic
    """
    # Claim (Q4+Q3 each 130000 -> qualifies; WBA 5000, base MBA 130000) driven to
    # EXHAUSTED; an active program granting 13 weeks -> MBA grows to
    # 130000 + 13*5000 = 195000, status returns to MONETARILY_ELIGIBLE.
    # (remaining_balance is not asserted: PRD §2.8 ties it to MBA minus paid weeks,
    # which the balance-hook setup leaves underivable.)
    program = create_extension_program(extra_weeks=13, trigger_start_date="2026-01-01",
                                       trigger_end_date="2026-12-31", waives_work_search=True,
                                       is_active=True)
    scenario = make_exhausted_claim(wages=[("2025-Q4", 130000), ("2025-Q3", 130000)],
                                    forced_balance=5000)
    claim_v = get_success_data(api_client.get_claim(scenario["claim"]["id"], ADJ))["version"]
    claim = get_success_data(api_client.apply_extension(
        scenario["claim"]["id"],
        {"program_id": program["id"], "expected_claim_version": claim_v},
        ADJ))
    assert claim["status"] == "MONETARILY_ELIGIBLE"
    assert claim["extension_weeks_granted"] == 13
    assert claim["maximum_benefit_amount_cents"] == 195000


# ── Corner: errors / extension_window_outside_rejected ──

def test_apply_extension_outside_window_rejected(api):
    """PRD §3.6: "A program covers the claim only when the program's is_active is
    true and the claim's filed_date falls on or after the program's
    trigger_start_date and on or before its trigger_end_date — both boundaries
    inclusive ... while a filed_date one day outside either boundary, or a program
    that is not active, is rejected with ERR_EXTENSION_WINDOW."

    Design: Corner/errors/extension_window_outside_rejected
    """
    # Claim filed 2026-04-05; program window [2026-06-01, 2026-12-31] starts after
    # the filed_date -> ERR_EXTENSION_WINDOW.
    program = create_extension_program(extra_weeks=13, trigger_start_date="2026-06-01",
                                       trigger_end_date="2026-12-31", is_active=True)
    scenario = make_exhausted_claim(wages=[("2025-Q4", 130000), ("2025-Q3", 130000)],
                                    forced_balance=5000)
    claim_v = get_success_data(api_client.get_claim(scenario["claim"]["id"], ADJ))["version"]
    res = api.apply_extension(
        scenario["claim"]["id"],
        {"program_id": program["id"], "expected_claim_version": claim_v},
        ADJ)
    validate_error(res, "ERR_EXTENSION_WINDOW", expected_status=422)


# ── Corner: cross_cutting_complexity_layers / occ_apply_extension_stale_claim_version ──

def test_apply_extension_stale_claim_version_rejected(api):
    """PRD §2.6: "Applying an emergency extension to a claim requires the request to
    carry expected_claim_version, holding the client's last observed version of the
    target Claim. If that value does not equal the claim's current version ... the
    apply is rejected with ERR_STALE_CLAIM_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_apply_extension_stale_claim_version
    """
    # Capture the claim version right after the determination, then let the
    # balance-hook + paid week advance the version. Apply-extension with the stale
    # captured version -> 412.
    program = create_extension_program(extra_weeks=13, trigger_start_date="2026-01-01",
                                       trigger_end_date="2026-12-31", is_active=True)
    employer = create_employer()
    claimant = create_claimant()
    # Q4+Q3 each 130000 -> qualifies (total 260000, hq 130000, 2*total >= 3*hq).
    add_wage_record(claimant["id"], employer["id"], "2025-Q4", 130000)
    add_wage_record(claimant["id"], employer["id"], "2025-Q3", 130000)
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    submit_claim(claim["id"], claimant["id"])
    issue_monetary_determination(claim["id"])
    stale_version = get_success_data(api_client.get_claim(claim["id"], ADJ))["version"]
    # Advance the claim version via balance hook + a paid week.
    set_claim_balance(claim["id"], 5000)
    wc = file_week(claim["id"], claimant["id"], "2026-04-11",
                   reported_earnings_cents=0, work_search_waived=True)
    adjudicate_week(wc["id"], "ELIGIBLE")
    get_success_data(api_client.pay_weekly_certification(wc["id"], {},
                     TEST_USERS["benefit_payment_officer_headers"]))
    res = api.apply_extension(
        claim["id"],
        {"program_id": program["id"], "expected_claim_version": stale_version},
        ADJ)
    validate_error(res, "ERR_STALE_CLAIM_VERSION", expected_status=412)


# ── Corner: validations / adjudicate_eligible_not_able_available_rejected ──

def test_adjudicate_eligible_not_able_available_rejected(api):
    """PRD §3.5: "the claimant must currently attest is_able_and_available true,
    failing which the decision is rejected with ERR_NOT_ABLE_AVAILABLE".

    Design: Corner/validations/adjudicate_eligible_not_able_available_rejected
    """
    scenario = make_eligible_claim(clmt_overrides={"is_able_and_available": False},
                                   wages=[("2025-Q4", 130000), ("2025-Q3", 130000)])
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", work_search_waived=True)
    res = api.adjudicate_weekly_certification(wc["id"], {"decision": "ELIGIBLE"}, ADJ)
    validate_error(res, "ERR_NOT_ABLE_AVAILABLE", expected_status=422)


# ── Corner: validations / work_search_insufficient_rejected ──

def test_work_search_insufficient_rejected(api):
    """PRD §3.5: "when work_search_required is true, the number of WorkSearchContact
    rows logged for the week must be at least three, failing which the decision is
    rejected with ERR_WORK_SEARCH_INSUFFICIENT."

    Design: Corner/validations/work_search_insufficient_rejected
    """
    # work_search_required week with only one contact logged (< 3).
    scenario = make_eligible_claim(wages=[("2025-Q4", 130000), ("2025-Q3", 130000)])
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"], "2026-04-11")
    assert wc["work_search_required"] is True
    get_success_data(api_client.create_work_search_contact(
        wc["id"],
        {"contact_type": "EMPLOYER_APPLICATION", "contact_date": "2026-04-08",
         "employer_id": scenario["employer"]["id"]},
        make_claimant_headers(scenario["claimant"]["id"])))
    res = api.adjudicate_weekly_certification(wc["id"], {"decision": "ELIGIBLE"}, ADJ)
    validate_error(res, "ERR_WORK_SEARCH_INSUFFICIENT", expected_status=422)


# ── Corner: validations / pay_against_exhausted_balance_rejected ──

def test_pay_against_exhausted_balance_rejected(api):
    """PRD §3.5: "It additionally enforces that the claim is not already exhausted:
    paying a week against a claim whose remaining_balance_cents is 0 is rejected
    with ERR_BALANCE_EXHAUSTED."

    Design: Corner/validations/pay_against_exhausted_balance_rejected
    """
    scenario = make_eligible_claim(wages=[("2025-Q4", 130000), ("2025-Q3", 130000)])
    set_claim_balance(scenario["claim"]["id"], 0)
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", work_search_waived=True)
    adjudicate_week(wc["id"], "ELIGIBLE")
    res = api.pay_weekly_certification(wc["id"], {},
                                       TEST_USERS["benefit_payment_officer_headers"])
    validate_error(res, "ERR_BALANCE_EXHAUSTED", expected_status=422)
