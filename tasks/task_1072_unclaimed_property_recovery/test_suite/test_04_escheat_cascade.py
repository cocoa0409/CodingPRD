"""Report acceptance: the depth-3 escheat cascade (report -> property -> ledger +
custody account) and the invalid-state guard on accepting an un-reviewed report.

Translates queue A (transitive_cascade/report_accept_escheat_custody) and queue B
(state_machines/accept_draft_report_returns_invalid_state).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, factories as f, fixtures,
)
from test_helpers.test_users import make_holder_headers, make_examiner_headers


def _report_ready_to_accept(api):
    """Holder + AC01 interest property (face 100000) + CA custody account; report
    submitted and moved UNDER_AUDIT at clock 2026-07-15 (3 dormant years)."""
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    pt = fixtures.create_property_type(api, code="AC01", dormancy_basis="LAST_ACTIVITY",
                                       dormancy_period_years=3, interest_bearing=True)
    sa = fixtures.create_state_account(api, "CA")
    prop = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_last_known_state="CA", amount_cents=100000,
        last_activity_date="2020-01-01T00:00:00Z"), hh), 201)
    validate_success(api.evaluate_dormancy(prop["id"], hh), 200)
    fixtures.set_clock(api, "2026-07-15T00:00:00Z")
    report = validate_success(api.create_report(f.create_report_payload(holder["id"], "CA", 2026), hh), 201)
    r1 = validate_success(api.add_property(report["id"], f.add_property_payload(prop["id"], report["version"]), hh), 200)
    validate_success(api.submit_report(report["id"], {"declared_total_cents": r1["total_remitted_cents"]}, hh), 200)
    ex = make_examiner_headers()
    validate_success(api.begin_review(report["id"], ex), 200)
    return holder, hh, pt, sa, prop, report, ex


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/report_accept_escheat_custody
# ---------------------------------------------------------------------------
def test_accept_escheats_attached_property(api):
    """PRD §3.5: "Acceptance moves the report to ACCEPTED, which is terminal, and triggers the
    central escheat cascade."
    PRD §3.5: "When a report is accepted, every attached property still in REPORTED transitions
    to ESCHEATED."
    PRD §3.5: "The property's remitted_amount_cents is the face principal plus the applied
    interest, rounded half-up to whole cents."

    Face 100000, interest-bearing, 3 dormant years: interest 100000*0.02*3 = 6000, remitted 106000.

    Design: Difficulty/transitive_cascade/report_accept_escheat_custody
    """
    holder, hh, pt, sa, prop, report, ex = _report_ready_to_accept(api)
    accepted = validate_success(api.accept_report(report["id"], ex), 200)
    assert accepted["status"] == "ACCEPTED"
    after = validate_success(api.get_property(prop["id"], hh), 200)
    assert after["status"] == "ESCHEATED", f"attached property must escheat, got {after['status']}"
    assert after["remitted_amount_cents"] == 106000, \
        f"remitted must be 106000, got {after['remitted_amount_cents']}"


def test_accept_credits_custody_account(api):
    """PRD §3.5: "Each escheated property produces a custody credit: the system writes a
    REMIT_IN LedgerEntry for that property's remitted_amount_cents against the custody account
    whose state_code is the property's escheat_state ..., then recomputes that account's
    custody_balance_cents, which rises by the remitted amount."

    Design: Difficulty/transitive_cascade/report_accept_escheat_custody
    """
    holder, hh, pt, sa, prop, report, ex = _report_ready_to_accept(api)
    validate_success(api.accept_report(report["id"], ex), 200)
    account = validate_success(api.get_state_account(sa["id"], make_examiner_headers()), 200)
    assert account["custody_balance_cents"] == 106000, \
        f"custody must rise by the remitted 106000, got {account['custody_balance_cents']}"


# ---------------------------------------------------------------------------
# Corner/state_machines/accept_draft_report_returns_invalid_state
# ---------------------------------------------------------------------------
def test_accept_draft_report_rejected(api):
    """PRD §2.12: "State validity is checked fourth: if the target resource is not in a state
    from which the requested transition is defined, the request is rejected with
    ERR_INVALID_STATE (HTTP 409)."
    PRD §3.5: "A StateExaminer begins review of a SUBMITTED report, moving it to UNDER_AUDIT.
    From UNDER_AUDIT, the examiner either rejects the report ... or accepts it."

    Accepting a DRAFT report (never submitted/reviewed) is rejected; it stays DRAFT.

    Design: Corner/state_machines/accept_draft_report_returns_invalid_state
    """
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    report = validate_success(api.create_report(f.create_report_payload(holder["id"], "CA", 2026), hh), 201)
    ex = make_examiner_headers()
    validate_error(api.accept_report(report["id"], ex), ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_report(report["id"], hh), 200)
    assert after["status"] == "DRAFT"
