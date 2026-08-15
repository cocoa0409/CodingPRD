"""Composite setup helpers.

The suite's interesting claims require the system to be in a late lifecycle
state (a funded loan, a committee decision in window, a issued letter). These
helpers encapsulate the multi-step setup chains so tests stay focused on
assertions. All helpers hit the live API through the shared client and use the
lenient setup validator, so a broken precondition surfaces as a clear
"Setup step failed" error naming the failing call.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    RATIONALE_BREACH, RATIONALE_COVERAGE, RATIONALE_DSCR, RATIONALE_LTV,
    RATIONALE_REG_O, RATIONALE_STRESS,
)
from .factories import (
    appraisal_payload, appraiser_payload, borrower_payload, checklist_item_payload,
    committee_decision_payload, committee_session_payload, covenant_payload,
    covenant_review_payload, funding_authorization_payload, letter_issue_payload,
    loan_application_payload, participation_payload, receive_report_payload,
    statement_payload, term_sheet_payload,
)
from .test_users import (
    TEST_USERS, make_appraisal_manager_headers, make_committee_chair_headers,
    make_committee_member_headers, make_credit_administrator_headers,
    make_credit_analyst_headers, make_credit_policy_officer_headers,
    make_relationship_manager_headers,
)

ADMIN = TEST_USERS["bank_admin_headers"]

# Standard officer bench: role key -> registration name / role / header builder.
_OFFICER_BENCH = [
    ("rm", "Rita RM", "RelationshipManager", make_relationship_manager_headers),
    ("an", "Andy Analyst", "CreditAnalyst", make_credit_analyst_headers),
    ("apm", "April Appraisals", "AppraisalManager", make_appraisal_manager_headers),
    ("ch", "Cheryl Chair", "CommitteeChair", make_committee_chair_headers),
    ("m1", "Member One", "CommitteeMember", make_committee_member_headers),
    ("m2", "Member Two", "CommitteeMember", make_committee_member_headers),
    ("m3", "Member Three", "CommitteeMember", make_committee_member_headers),
    ("m4", "Member Four", "CommitteeMember", make_committee_member_headers),
    ("po", "Polly Policy", "CreditPolicyOfficer", make_credit_policy_officer_headers),
    ("adm", "Adam Admin", "CreditAdministrator", make_credit_administrator_headers),
]

# Waiver rationales keyed by the rule_code they clear.
RULE_CODE_RATIONALES = {
    "STRESS_DSCR_MINIMUM": RATIONALE_STRESS,
    "REG_O_INSIDER": RATIONALE_REG_O,
    "DSCR_MINIMUM": RATIONALE_DSCR,
    "LTV_MAXIMUM": RATIONALE_LTV,
    "COLLATERAL_COVERAGE_MIN": RATIONALE_COVERAGE,
    "COVENANT_BREACH": RATIONALE_BREACH,
    "SINGLE_BORROWER_LIMIT": "Borrower exposure reduced within policy cap",
    "REQUIRED_DOC_WAIVER": "Document requirement waived per policy desk",
}


def setup_officers(keys=None) -> dict:
    """Register the officer bench. Returns {key: {"id", "role", "headers"}}.

    Entity-backed roles thread the real BankOfficer.id into X-User-ID, which is
    what makes the segregation-of-duties checks enforceable downstream.
    """
    wanted = set(keys) if keys else None
    bench = {}
    for key, name, role, builder in _OFFICER_BENCH:
        if wanted is not None and key not in wanted:
            continue
        officer = get_success_data(api_client.create_bank_officer({"full_name": name}, ADMIN))
        bench[key] = {"id": officer["id"], "role": role, "headers": builder(officer["id"])}
    return bench


# --- Single-step helpers -------------------------------------------------

def create_borrower(o, **overrides) -> dict:
    return get_success_data(api_client.create_borrower(borrower_payload(**overrides), o["rm"]["headers"]))


def create_loan_application(o, borrower_id, **overrides) -> dict:
    return get_success_data(api_client.create_loan_application(
        loan_application_payload(borrower_id, **overrides), o["rm"]["headers"]))


def attach_statement(o, app_id, shape="BEACON", **overrides) -> dict:
    return get_success_data(api_client.create_financial_statement(
        statement_payload(app_id, shape=shape, **overrides), o["an"]["headers"]))


def submit_application(o, app_id) -> dict:
    return get_success_data(api_client.submit_application(app_id, o["rm"]["headers"]))


def spread_statement(o, stmt_id) -> dict:
    return get_success_data(api_client.spread_statement(stmt_id, o["an"]["headers"]))


def finalize_statement(o, stmt_id) -> dict:
    return get_success_data(api_client.finalize_statement(stmt_id, o["an"]["headers"]))


def spread_and_finalize(o, stmt_id) -> dict:
    spread_statement(o, stmt_id)
    return finalize_statement(o, stmt_id)


def finalize_spreads(o, app_id) -> dict:
    return get_success_data(api_client.finalize_spreads(app_id, o["an"]["headers"]))


def get_application(o, app_id) -> dict:
    return get_success_data(api_client.get_loan_application(app_id, o["an"]["headers"]))


def get_borrower(o, borrower_id) -> dict:
    return get_success_data(api_client.get_borrower(borrower_id, o["an"]["headers"]))


def list_exceptions(o, app_id, rule_code=None, status=None) -> list:
    params = {}
    if rule_code:
        params["rule_code"] = rule_code
    if status:
        params["status"] = status
    data, _meta = _paginated(api_client.list_application_exceptions(app_id, o["po"]["headers"], params=params))
    return data


def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


def waive_exception(o, exception_id, rationale) -> dict:
    return get_success_data(api_client.waive_exception(
        exception_id, {"waiver_rationale": rationale}, o["po"]["headers"]))


def waive_all_open_exceptions(o, app_id) -> list:
    """Waive every currently OPEN exception on the application. Returns them."""
    waived = []
    for exc in list_exceptions(o, app_id, status="OPEN"):
        rationale = RULE_CODE_RATIONALES.get(exc["rule_code"], "Waiver granted after full policy review")
        waived.append(waive_exception(o, exc["id"], rationale))
    return waived


def clear_exceptions(o, app_id) -> dict:
    return get_success_data(api_client.clear_exceptions(app_id, o["po"]["headers"]))


def create_appraiser(o, **overrides) -> dict:
    return get_success_data(api_client.create_appraiser(appraiser_payload(**overrides), o["apm"]["headers"]))


def order_appraisal(o, app_id, appraiser_id, **overrides) -> dict:
    return get_success_data(api_client.create_appraisal(
        appraisal_payload(app_id, appraiser_id, **overrides), o["apm"]["headers"]))


def receive_report(o, appraisal_id, appraised_value_cents, orderly_liquidation_value_cents) -> dict:
    return get_success_data(api_client.receive_appraisal_report(
        appraisal_id,
        receive_report_payload(appraised_value_cents=appraised_value_cents,
                               orderly_liquidation_value_cents=orderly_liquidation_value_cents),
        o["apm"]["headers"]))


def review_appraisal(o, appraisal_id, outcome) -> dict:
    return get_success_data(api_client.review_appraisal(appraisal_id, {"outcome": outcome}, o["apm"]["headers"]))


def order_and_accept_appraisal(o, app_id, appraiser_id, appraised_value_cents,
                               orderly_liquidation_value_cents, **overrides) -> dict:
    aprl = order_appraisal(o, app_id, appraiser_id, **overrides)
    receive_report(o, aprl["id"], appraised_value_cents, orderly_liquidation_value_cents)
    return review_appraisal(o, aprl["id"], "ACCEPTED")


def submit_to_committee(o, app_id) -> dict:
    return get_success_data(api_client.submit_to_committee(app_id, o["an"]["headers"]))


def create_session(o, level="STANDARD", starts_at="2026-08-10T14:00:00Z",
                   ends_at="2026-08-10T15:30:00Z") -> dict:
    return get_success_data(api_client.create_committee_session(
        committee_session_payload(level=level, starts_at=starts_at, ends_at=ends_at),
        o["ch"]["headers"]))


def set_clock(to_iso8601) -> None:
    get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def open_decision(o, app_id, session_id) -> dict:
    """Open a committee decision pinned to the application's current version."""
    current = get_application(o, app_id)
    return get_success_data(api_client.create_committee_decision(
        committee_decision_payload(app_id, session_id, current["version"]), o["ch"]["headers"]))


def cast_vote(o, decision_id, officer_key, vote) -> dict:
    return get_success_data(api_client.cast_vote(decision_id, {"vote": vote}, o[officer_key]["headers"]))


def issue_term_sheet(o, app_id, amount_cents, **overrides) -> dict:
    """Issue a term sheet pinned to the application's current version."""
    current = get_application(o, app_id)
    return get_success_data(api_client.create_term_sheet(
        term_sheet_payload(app_id, amount_cents, current["version"], **overrides), o["rm"]["headers"]))


def respond_sheet(o, sheet_id, outcome) -> dict:
    return get_success_data(api_client.respond_term_sheet(sheet_id, {"outcome": outcome}, o["rm"]["headers"]))


def get_letter(o, app_id) -> dict:
    data, _meta = _paginated(api_client.list_commitment_letters(
        o["adm"]["headers"], params={"loan_application_id": app_id}))
    assert len(data) >= 1, "expected a commitment letter to exist for the application"
    return data[0]


def issue_letter(o, letter_id, **overrides) -> dict:
    return get_success_data(api_client.issue_commitment_letter(
        letter_id, letter_issue_payload(**overrides), o["adm"]["headers"]))


def accept_letter(o, letter_id) -> dict:
    return get_success_data(api_client.accept_commitment_letter(letter_id, o["adm"]["headers"]))


def add_checklist_item(o, app_id, **overrides) -> dict:
    return get_success_data(api_client.create_checklist_item(
        checklist_item_payload(app_id, **overrides), o["adm"]["headers"]))


def transition_item(o, item_id, to, officer="adm", **extra) -> dict:
    payload = {"to": to}
    payload.update(extra)
    return get_success_data(api_client.transition_checklist_item(item_id, payload, o[officer]["headers"]))


def approve_item(o, item_id) -> dict:
    transition_item(o, item_id, "RECEIVED")
    return transition_item(o, item_id, "APPROVED")


def add_covenant(o, app_id, **overrides) -> dict:
    return get_success_data(api_client.create_covenant(covenant_payload(app_id, **overrides), o["adm"]["headers"]))


def review_covenant(o, covenant_id, measured_value, period_end_date) -> dict:
    return get_success_data(api_client.review_covenant(
        covenant_id, covenant_review_payload(measured_value=measured_value, period_end_date=period_end_date),
        o["an"]["headers"]))


def request_funding(o, app_id, **overrides) -> dict:
    return get_success_data(api_client.create_funding_authorization(
        funding_authorization_payload(app_id, **overrides), o["adm"]["headers"]))


def authorize_funding(o, fa_id) -> dict:
    return get_success_data(api_client.authorize_funding(fa_id, o["po"]["headers"]))


def release_funding(o, fa_id) -> dict:
    return get_success_data(api_client.release_funding(fa_id, o["adm"]["headers"]))


def propose_participation(o, app_id, **overrides) -> dict:
    return get_success_data(api_client.create_participation(
        participation_payload(app_id, **overrides), o["rm"]["headers"]))


def submit_for_closing(o, app_id) -> dict:
    return get_success_data(api_client.submit_for_closing(app_id, o["adm"]["headers"]))


# --- Composite lifecycle fixtures -----------------------------------------

def deal_intake(*, officer_keys=("rm", "an"), borrower_kw=None, app_kw=None,
                statement_shape: Optional[str] = "BEACON", stmt_kw=None) -> dict:
    """Officers + borrower + INTAKE application (+ one attached statement)."""
    o = setup_officers(list(officer_keys))
    bor = create_borrower(o, **(borrower_kw or {}))
    app = create_loan_application(o, bor["id"], **(app_kw or {}))
    ctx = {"o": o, "borrower": bor, "application": app}
    if statement_shape is not None:
        ctx["statement"] = attach_statement(o, app["id"], shape=statement_shape, **(stmt_kw or {}))
    return ctx


def deal_spreading(**kw) -> dict:
    """deal_intake + submit -> SPREADING."""
    ctx = deal_intake(**kw)
    ctx["application"] = submit_application(ctx["o"], ctx["application"]["id"])
    return ctx


def deal_underwritten(**kw) -> dict:
    """deal_spreading + statement spread/finalize + finalize-spreads.

    The application lands in EXCEPTION_REVIEW (any OPEN exception) or
    APPRAISAL_REVIEW (none). The finalize-spreads response is stored as
    ctx["underwriting"].
    """
    kw.setdefault("officer_keys", ("rm", "an", "po"))
    ctx = deal_spreading(**kw)
    o = ctx["o"]
    spread_and_finalize(o, ctx["statement"]["id"])
    ctx["underwriting"] = finalize_spreads(o, ctx["application"]["id"])
    ctx["application"] = ctx["underwriting"]
    return ctx


def deal_appraisal_review(**kw) -> dict:
    """deal_underwritten, then (if exceptions are OPEN) waive all + clear.

    Ends in APPRAISAL_REVIEW regardless of whether the underwriting fired
    exceptions. The bench includes the AppraisalManager: appraisal work is the
    operation this stage exists for.
    """
    kw.setdefault("officer_keys", ("rm", "an", "po", "apm"))
    ctx = deal_underwritten(**kw)
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    if ctx["application"]["status"] == "EXCEPTION_REVIEW":
        waive_all_open_exceptions(o, app_id)
        ctx["application"] = clear_exceptions(o, app_id)
    assert ctx["application"]["status"] == "APPRAISAL_REVIEW", (
        f"expected APPRAISAL_REVIEW, got {ctx['application']['status']}")
    return ctx


def deal_committee_review(*, appraised_value_cents=400_000_000,
                          orderly_liquidation_value_cents=380_000_000,
                          collateral_class="REAL_ESTATE", appraiser_kw=None,
                          appraisal_kw=None, **kw) -> dict:
    """deal_appraisal_review + one ACCEPTED appraisal + submit-to-committee.

    The default deal is the clean MERIDIAN shape at a 200,000,000 request: the
    DSCR cap (~336,681,531), the LTV cap (320,000,000 = 400,000,000 x 0.80),
    and the single-borrower headroom all clear the request, so the sizing lands
    `proposed_amount_cents` at exactly 200,000,000 — a STANDARD-tier committee
    deal, matching `deal_decision_open`'s STANDARD default session.
    """
    kw.setdefault("officer_keys", ("rm", "an", "po", "apm", "ch"))
    kw.setdefault("app_kw", {"requested_amount_cents": 200_000_000, "term_months": 60})
    kw.setdefault("statement_shape", "MERIDIAN")
    ctx = deal_appraisal_review(**kw)
    o = ctx["o"]
    ctx["appraiser"] = create_appraiser(o, **(appraiser_kw or {}))
    ctx["appraisal"] = order_and_accept_appraisal(
        o, ctx["application"]["id"], ctx["appraiser"]["id"],
        appraised_value_cents, orderly_liquidation_value_cents,
        collateral_class=collateral_class, **(appraisal_kw or {}))
    ctx["sizing"] = submit_to_committee(o, ctx["application"]["id"])
    ctx["application"] = ctx["sizing"]
    assert ctx["application"]["status"] == "COMMITTEE_REVIEW", (
        f"expected COMMITTEE_REVIEW, got {ctx['application']['status']}")
    return ctx


def deal_decision_open(*, level="STANDARD",
                       session_window=("2026-08-10T14:00:00Z", "2026-08-10T15:30:00Z"),
                       vote_clock="2026-08-10T14:30:00Z", set_the_clock=True, **kw) -> dict:
    """deal_committee_review + matching session + (clock into window) + OPEN decision."""
    kw.setdefault("officer_keys", ("rm", "an", "po", "apm", "ch", "m1", "m2", "m3", "m4"))
    ctx = deal_committee_review(**kw)
    o = ctx["o"]
    ctx["session"] = create_session(o, level=level, starts_at=session_window[0], ends_at=session_window[1])
    if set_the_clock:
        set_clock(vote_clock)
    ctx["decision"] = open_decision(o, ctx["application"]["id"], ctx["session"]["id"])
    assert ctx["decision"]["status"] == "OPEN"
    return ctx


def approve_decision(ctx, level="STANDARD") -> dict:
    """Cast the votes that close the decision APPROVED for the given level."""
    o = ctx["o"]
    dec_id = ctx["decision"]["id"]
    if level == "LARGE":
        for member in ("m1", "m2", "m3", "m4"):
            cast_vote(o, dec_id, member, "APPROVE")
        ctx["decision"] = cast_vote(o, dec_id, "ch", "APPROVE")
    else:
        cast_vote(o, dec_id, "m1", "APPROVE")
        ctx["decision"] = cast_vote(o, dec_id, "m2", "APPROVE")
    assert ctx["decision"]["status"] == "APPROVED", (
        f"expected APPROVED, got {ctx['decision']['status']}")
    ctx["application"] = get_application(o, ctx["application"]["id"])
    assert ctx["application"]["status"] == "TERM_SHEET_NEGOTIATION"
    return ctx


def deal_approved(**kw) -> dict:
    """deal_decision_open + the approving votes -> TERM_SHEET_NEGOTIATION."""
    level = kw.get("level", "STANDARD")
    ctx = deal_decision_open(**kw)
    return approve_decision(ctx, level=level)


def deal_commitment(*, sheet_amount_cents=None, sheet_kw=None, **kw) -> dict:
    """deal_approved + term sheet issued and ACCEPTED -> COMMITMENT (letter DRAFT)."""
    kw.setdefault("officer_keys", ("rm", "an", "po", "apm", "ch", "m1", "m2", "m3", "m4", "adm"))
    ctx = deal_approved(**kw)
    o = ctx["o"]
    amount = sheet_amount_cents if sheet_amount_cents is not None else ctx["application"]["proposed_amount_cents"]
    ctx["sheet"] = issue_term_sheet(o, ctx["application"]["id"], amount, **(sheet_kw or {}))
    ctx["sheet"] = respond_sheet(o, ctx["sheet"]["id"], "ACCEPTED")
    ctx["application"] = get_application(o, ctx["application"]["id"])
    assert ctx["application"]["status"] == "COMMITMENT"
    ctx["letter"] = get_letter(o, ctx["application"]["id"])
    return ctx


def deal_letter_issued(*, letter_kw=None, **kw) -> dict:
    """deal_commitment + letter issued (ISSUED)."""
    ctx = deal_commitment(**kw)
    ctx["letter"] = issue_letter(ctx["o"], ctx["letter"]["id"], **(letter_kw or {}))
    return ctx


def deal_documentation(**kw) -> dict:
    """deal_letter_issued + letter accepted -> DOCUMENTATION."""
    ctx = deal_letter_issued(**kw)
    ctx["letter"] = accept_letter(ctx["o"], ctx["letter"]["id"])
    ctx["application"] = get_application(ctx["o"], ctx["application"]["id"])
    assert ctx["application"]["status"] == "DOCUMENTATION"
    return ctx


def deal_closing(*, with_closing_condition=True, **kw) -> dict:
    """deal_documentation + required DOCUMENT item APPROVED + covenant +
    (optional) required CLOSING_CONDITION item APPROVED + submit-for-closing."""
    ctx = deal_documentation(**kw)
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    ctx["doc_item"] = add_checklist_item(o, app_id, label="Executed promissory note")
    approve_item(o, ctx["doc_item"]["id"])
    ctx["covenant"] = add_covenant(o, app_id)
    if with_closing_condition:
        ctx["cc_item"] = add_checklist_item(o, app_id, category="CLOSING_CONDITION",
                                            label="Evidence of insurance")
        approve_item(o, ctx["cc_item"]["id"])
    ctx["application"] = submit_for_closing(o, app_id)
    assert ctx["application"]["status"] == "CLOSING"
    return ctx


def deal_funded(*, first_tranche_cents=120_000_000, **kw) -> dict:
    """deal_closing + first tranche requested/authorized/released -> FUNDED."""
    ctx = deal_closing(**kw)
    o = ctx["o"]
    ctx["fa1"] = request_funding(o, ctx["application"]["id"], amount_cents=first_tranche_cents)
    authorize_funding(o, ctx["fa1"]["id"])
    ctx["fa1"] = release_funding(o, ctx["fa1"]["id"])
    assert ctx["fa1"]["status"] == "RELEASED"
    ctx["application"] = get_application(o, ctx["application"]["id"])
    assert ctx["application"]["status"] == "FUNDED"
    ctx["letter"] = get_letter(o, ctx["application"]["id"])
    return ctx
