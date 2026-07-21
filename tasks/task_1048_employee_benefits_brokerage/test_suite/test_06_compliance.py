"""Compliance filings: segregation of duties, active-coverage guard, on-time/late filing."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_compliance_headers,
)
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["consultant_headers"]
OFFICER_A = make_compliance_headers("officer-a")
OFFICER_B = make_compliance_headers("officer-b")


# ===========================================================================
# Difficulty / priority_pair_validation_conflict — SoD beats referential
# ===========================================================================
def test_certify_same_officer_no_active_policy_sod_wins(api):
    """PRD §2.7: "Segregation of duties — on filing certification, the certifier's X-User-ID
    differs from prepared_by_user_id; otherwise ERR_SEGREGATION_OF_DUTIES (409)."
    PRD §2.7: "Active-coverage referential — on filing certification, the filing's client has
    at least one policy with lifecycle_status of ACTIVE; otherwise ERR_NO_ACTIVE_COVERAGE
    (409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_certify
    """
    client = fx.create_client(legal_name="Kappa Co", industry="HEALTHCARE")
    filing = fx.create_prepared_filing(client["id"], filing_type="ACA_1094C",
                                       due_date="2027-03-31T00:00:00Z", officer_id="officer-a")
    resp = api.certify_filing(filing["id"], OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_rejected_certify_leaves_filing_prepared(api):
    """PRD §3.7: "First, segregation of duties: the certifying officer's X-User-ID must
    differ from the prepared_by_user_id; if the same officer who prepared the filing attempts
    to certify it, the request is rejected with ERR_SEGREGATION_OF_DUTIES."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_certify
    """
    client = fx.create_client(legal_name="Kappa Co", industry="HEALTHCARE")
    filing = fx.create_prepared_filing(client["id"], filing_type="ACA_1094C",
                                       due_date="2027-03-31T00:00:00Z", officer_id="officer-a")
    api.certify_filing(filing["id"], OFFICER_A)
    fresh = validate_success(api.get_filing(filing["id"], CONSULTANT))
    assert fresh["status"] == "PREPARED"


# ===========================================================================
# Corner / state_machines — terminal lockdown after FILED
# ===========================================================================
def test_file_already_filed_filing_invalid_state(api):
    """PRD §3.7: "Both FILED and LATE are terminal."
    PRD §2.7: "State — the target resource is in a state from which the requested transition
    is defined; otherwise ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/filing_terminal_lockdown_after_file
    """
    client, policy = fx.setup_client_with_active_policy(legal_name="Filed Co",
                                                        monthly_premium_cents=500_000)
    filing = fx.create_prepared_filing(client["id"], filing_type="FORM_5500",
                                       due_date="2027-07-31T00:00:00Z", officer_id="officer-a")
    validate_success(api.certify_filing(filing["id"], OFFICER_B))
    filed = validate_success(api.file_filing(filing["id"], OFFICER_B))
    assert filed["status"] == "FILED"
    resp = api.file_filing(filing["id"], OFFICER_B)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_file_certified_filing_past_due_sets_late(api):
    """PRD §3.7: "Filing a certified filing branches on the clock against the filing's
    due_date: the same file action advances the filing to FILED when the logical clock is at
    or before the due date (recorded on time), and to LATE when the logical clock is past the
    due date (recorded late)."

    Design: Corner/state_machines/filing_file_late_sets_late_status
    """
    client, policy = fx.setup_client_with_active_policy(legal_name="Late Co",
                                                        monthly_premium_cents=500_000)
    filing = fx.create_prepared_filing(client["id"], filing_type="ERISA_SPD", plan_year=2025,
                                       due_date="2026-06-01T00:00:00Z", officer_id="officer-a")
    validate_success(api.certify_filing(filing["id"], OFFICER_B))
    # Clock default 2026-07-01 is past due_date 2026-06-01 -> LATE.
    filed = validate_success(api.file_filing(filing["id"], OFFICER_B))
    assert filed["status"] == "LATE"
