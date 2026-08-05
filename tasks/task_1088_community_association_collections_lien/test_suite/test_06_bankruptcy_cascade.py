"""Bankruptcy automatic-stay cascade (depth-3) and dismissal lifting the stay."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_compliance_officer_headers,
    fixtures,
)

AGENT = TEST_USERS["collections_agent_headers"]
OFFICER2 = make_compliance_officer_headers("officer-2")


# --- transitive_cascade / tc_bankruptcy_stay_depth3 (queue A, >=2 tests) ---

def test_bankruptcy_moves_account_to_bankruptcy(api):
    """PRD §3.7: "The case opens in `FILED` — its `status` ranges over `FILED`, `DISCHARGED`,
    and `DISMISSED` — and moves the account into `BANKRUPTCY` from whatever collection stage
    it occupied."

    Design: Difficulty/transitive_cascade/tc_bankruptcy_stay_depth3
    """
    base = fixtures.setup_filed_referral(api, amount_cents=200000,
                                         sent_date="2026-01-01T00:00:00Z",
                                         record_date="2026-02-01T00:00:00Z")
    acct_id = base["account"]["id"]
    bk = fixtures.file_bankruptcy(api, acct_id, "2026-02-01T00:00:00Z",
                                  officer_id="officer-2", chapter="CH13", case_number="26-90001")
    assert bk["status"] == "FILED"
    acct = get_success_data(api.get_account(acct_id, AGENT))
    assert acct["status"] == "BANKRUPTCY"


def test_bankruptcy_stays_lien_and_referral(api):
    """PRD §3.7: "every `RECORDED` lien on the account moves to `STAYED`, and every
    `FORECLOSING` lien likewise moves to `STAYED`; every `FILED` or `REFERRED` foreclosure
    referral moves to `STAYED`; and any `ACTIVE` payment plan moves to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/tc_bankruptcy_stay_depth3
    """
    base = fixtures.setup_filed_referral(api, amount_cents=200000,
                                         sent_date="2026-01-01T00:00:00Z",
                                         record_date="2026-02-01T00:00:00Z")
    acct_id = base["account"]["id"]
    fixtures.file_bankruptcy(api, acct_id, "2026-02-01T00:00:00Z",
                             officer_id="officer-2", chapter="CH13", case_number="26-90001")
    lien = get_success_data(api.get_lien(base["lien"]["id"], AGENT))
    assert lien["status"] == "STAYED", lien["status"]
    ref = get_success_data(api.get_foreclosure_referral(base["referral"]["id"], AGENT))
    assert ref["status"] == "STAYED", ref["status"]


# --- Queue B: state_machines / bankruptcy_dismissal_lifts_stay ---

def test_bankruptcy_dismissal_lifts_stay(api):
    """PRD §3.7: "**Dismissal** (`FILED → DISMISSED`) lifts the stay and restores the
    pre-petition posture: the account returns from `BANKRUPTCY` to `DELINQUENT`, every
    `STAYED` lien returns to `RECORDED`, every `STAYED` referral returns to `REFERRED`, and
    any `SUSPENDED` plan returns to `ACTIVE`."

    Design: Corner/state_machines/bankruptcy_dismissal_lifts_stay
    """
    base = fixtures.setup_recorded_lien(api, amount_cents=200000,
                                        sent_date="2026-01-01T00:00:00Z",
                                        record_date="2026-02-01T00:00:00Z", officer_id="officer-1")
    acct_id, lien_id = base["account"]["id"], base["lien"]["id"]
    bk = fixtures.file_bankruptcy(api, acct_id, "2026-02-01T00:00:00Z",
                                  officer_id="officer-2", chapter="CH7", case_number="26-1")
    dismissed = validate_success(api.transition_bankruptcy_case(bk["id"], "DISMISSED", OFFICER2))
    assert dismissed["status"] == "DISMISSED"
    acct = get_success_data(api.get_account(acct_id, AGENT))
    assert acct["status"] == "DELINQUENT"
    lien = get_success_data(api.get_lien(lien_id, AGENT))
    assert lien["status"] == "RECORDED"
