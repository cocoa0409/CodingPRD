"""Appeals: remand cycle, the reversal cascade re-eligibility recompute,
affirm leaving the determination unchanged, segregation of duties, dismissal."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_denied_determination, make_appeal_under_review,
    create_employer, create_claimant, add_wage_record,
    create_draft_claim, submit_claim, issue_monetary_determination,
    file_appeal, assign_referee, remand_appeal, decide_appeal, set_clock,
    assert_appeal, assert_determination, assert_claim,
    TEST_USERS,
)

ADJ = TEST_USERS["adjudicator_headers"]
CLERK = TEST_USERS["appeals_clerk_headers"]
REF = TEST_USERS["referee_headers"]


# ── Difficulty: non_linear_state_machine / appeal_remand_cycle_under_review ──

def test_appeal_remand_then_reassign_returns_under_review(api):
    """PRD §3.7: "The referee may remand it for further fact-finding, moving it
    UNDER_REVIEW → REMANDED, incrementing remand_count by one".
    PRD §3.7: "An AppealsClerk assigns a referee, supplying the assigned_referee_id;
    this moves the appeal SUBMITTED → UNDER_REVIEW (and is also the move that brings
    a remanded appeal REMANDED → UNDER_REVIEW)."

    Design: Difficulty/non_linear_state_machine/appeal_remand_cycle_under_review
    """
    scenario = make_appeal_under_review(adjudicator_id="adj-77", referee_id="ref-1")
    appeal_id = scenario["appeal"]["id"]
    remand_appeal(appeal_id)
    appeal = assign_referee(appeal_id, "ref-2")
    assert_appeal(appeal)
    assert appeal["status"] == "UNDER_REVIEW"
    assert appeal["remand_count"] == 1


def test_remand_increments_count_to_remanded_state(api):
    """PRD §3.7: "The referee may remand it for further fact-finding, moving it
    UNDER_REVIEW → REMANDED, incrementing remand_count by one".

    Design: Difficulty/non_linear_state_machine/appeal_remand_cycle_under_review
    """
    scenario = make_appeal_under_review(adjudicator_id="adj-78", referee_id="ref-1")
    appeal = remand_appeal(scenario["appeal"]["id"])
    assert appeal["status"] == "REMANDED"
    assert appeal["remand_count"] == 1


# ── Difficulty: transitive_cascade / appeal_reverse_cascades_claim_reeligible_recompute ──

def _denied_then_undisputed_under_review():
    """A DENIED monetary determination (STANDARD total 220000 with a disputed
    200000 record), then the dispute is resolved and the appeal goes UNDER_REVIEW.
    Returns (scenario dict, wr_disputed_id)."""
    employer = create_employer()
    claimant = create_claimant()
    add_wage_record(claimant["id"], employer["id"], "2025-Q1", 40000)
    add_wage_record(claimant["id"], employer["id"], "2025-Q2", 50000)
    add_wage_record(claimant["id"], employer["id"], "2025-Q3", 60000)
    add_wage_record(claimant["id"], employer["id"], "2025-Q4", 70000)
    wr_disputed = add_wage_record(claimant["id"], employer["id"], "2025-Q4",
                                  200000, is_disputed=True)
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    submit_claim(claim["id"], claimant["id"])
    set_clock("2026-04-10T00:00:00Z")
    det = issue_monetary_determination(claim["id"], adjudicator_id="adj-90")
    # Resolve the dispute (admin), then file + assign the appeal.
    get_success_data(api_client.update_wage_record(
        wr_disputed["id"], {"is_disputed": False}, TEST_USERS["program_admin_headers"]))
    appeal = file_appeal(det["id"], claimant["id"], filed_date="2026-04-20")
    appeal = assign_referee(appeal["id"], "ref-9")
    return ({"employer": employer, "claimant": claimant, "claim": claim,
             "determination": det, "appeal": appeal}, wr_disputed["id"])


def test_reverse_cascades_claim_back_to_eligible_with_recompute(api):
    """PRD §3.7: "When the reversed determination was a MONETARY determination that
    had been DENIED, reversing it flips the parent claim back to eligibility: the
    claim transitions MONETARILY_INELIGIBLE → MONETARILY_ELIGIBLE, the monetary
    calculations are re-run to set the claim's weekly_benefit_amount_cents,
    maximum_benefit_amount_cents, and remaining_balance_cents, the appealed
    determination's outcome becomes REVERSED with is_appealable false".

    Design: Difficulty/transitive_cascade/appeal_reverse_cascades_claim_reeligible_recompute
    """
    scenario, _ = _denied_then_undisputed_under_review()
    appeal = decide_appeal(scenario["appeal"]["id"], "REVERSE")
    det = get_success_data(api_client.get_determination(scenario["determination"]["id"], ADJ))
    claim = get_success_data(api_client.get_claim(scenario["claim"]["id"], ADJ))
    assert appeal["status"] == "DECIDED_REVERSED"
    assert det["outcome"] == "REVERSED"
    assert claim["status"] == "MONETARILY_ELIGIBLE"
    # Re-run with undisputed Q4 (70000+200000=270000 hq): WBA 10400, MBA 210000.
    assert claim["weekly_benefit_amount_cents"] == 10400
    assert claim["maximum_benefit_amount_cents"] == 210000


def test_reverse_marks_determination_not_appealable(api):
    """PRD §3.7: "Reversing moves it UNDER_REVIEW → DECIDED_REVERSED, sets the
    appealed determination's outcome to REVERSED and its is_appealable to false."

    Design: Difficulty/transitive_cascade/appeal_reverse_cascades_claim_reeligible_recompute
    """
    scenario, _ = _denied_then_undisputed_under_review()
    decide_appeal(scenario["appeal"]["id"], "REVERSE")
    det = get_success_data(api_client.get_determination(scenario["determination"]["id"], ADJ))
    assert det["outcome"] == "REVERSED"
    assert det["is_appealable"] is False


# ── Corner: state_machines / appeal_affirm_leaves_determination_unchanged ──

def test_affirm_leaves_determination_unchanged(api):
    """PRD §3.7: "Affirming moves it UNDER_REVIEW → DECIDED_AFFIRMED and leaves the
    appealed determination's outcome unchanged."

    Design: Corner/state_machines/appeal_affirm_leaves_determination_unchanged
    """
    scenario = make_appeal_under_review(adjudicator_id="adj-aff", referee_id="ref-aff")
    appeal = decide_appeal(scenario["appeal"]["id"], "AFFIRM")
    det = get_success_data(api_client.get_determination(scenario["determination"]["id"], ADJ))
    claim = get_success_data(api_client.get_claim(scenario["claim"]["id"], ADJ))
    assert appeal["status"] == "DECIDED_AFFIRMED"
    assert det["outcome"] == "DENIED"
    assert claim["status"] == "MONETARILY_INELIGIBLE"


# ── Corner: state_machines / remand_cap_enforced ──

def test_remand_cap_enforced(api):
    """PRD §3.7: "an appeal may be remanded at most twice, so a remand attempted
    when remand_count already equals 2 is rejected with ERR_REMAND_LIMIT."

    Design: Corner/state_machines/remand_cap_enforced
    """
    scenario = make_appeal_under_review(adjudicator_id="adj-cap", referee_id="ref-c1")
    appeal_id = scenario["appeal"]["id"]
    remand_appeal(appeal_id)                  # remand_count -> 1, REMANDED
    assign_referee(appeal_id, "ref-c2")       # -> UNDER_REVIEW
    remand_appeal(appeal_id)                  # remand_count -> 2, REMANDED
    assign_referee(appeal_id, "ref-c3")       # -> UNDER_REVIEW
    res = api.remand_appeal(appeal_id, {}, REF)  # third remand rejected
    validate_error(res, "ERR_REMAND_LIMIT", expected_status=422)


# ── Corner: state_machines / appeal_dismiss_terminal_lockdown ──

def test_assign_after_dismiss_is_invalid_state(api):
    """PRD §3.7: "An AppealsClerk may instead dismiss a submitted appeal, moving it
    SUBMITTED → DISMISSED".
    PRD §3.7: "The states DECIDED_AFFIRMED, DECIDED_REVERSED, WITHDRAWN, and
    DISMISSED are terminal."

    Design: Corner/state_machines/appeal_dismiss_terminal_lockdown
    """
    # Determination clock 2026-04-10 -> deadline 2026-05-10. A timely appeal
    # (filed 2026-04-20 <= 2026-05-10) reaches SUBMITTED; the clerk dismisses it
    # (SUBMITTED -> DISMISSED), then a later assign on the now-terminal DISMISSED
    # appeal is rejected with ERR_INVALID_STATE. (PRD §3.7: untimely *filing* is
    # itself rejected with ERR_UNTIMELY, so DISMISSED is reached via a timely
    # appeal that the clerk dismisses, not by filing late.)
    scenario = make_denied_determination(adjudicator_id="adj-term",
                                         filed_date="2026-01-04",
                                         det_clock="2026-04-10T00:00:00Z")
    appeal = file_appeal(scenario["determination"]["id"], scenario["claimant"]["id"],
                         filed_date="2026-04-20")
    get_success_data(api_client.dismiss_appeal(appeal["id"], {}, CLERK))
    res = api.assign_appeal(appeal["id"], {"assigned_referee_id": "ref-term"}, CLERK)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ── Corner: rbac / segregation_of_duties_same_adjudicator_rejected ──

def test_assign_same_adjudicator_segregation_of_duties(api):
    """PRD §2.9: "When an appeal of that determination is assigned a referee, the
    assigned_referee_id supplied must differ from that recorded
    issuing_adjudicator_id; an attempt to assign the same operator is rejected with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/rbac/segregation_of_duties_same_adjudicator_rejected
    """
    scenario = make_denied_determination(adjudicator_id="adj-sod",
                                         filed_date="2026-04-05",
                                         det_clock="2026-04-10T00:00:00Z")
    appeal = file_appeal(scenario["determination"]["id"], scenario["claimant"]["id"],
                         filed_date="2026-04-20")
    res = api.assign_appeal(appeal["id"], {"assigned_referee_id": "adj-sod"}, CLERK)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=422)
