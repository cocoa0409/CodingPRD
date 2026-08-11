"""Composite setup helpers for the literary-agency pipeline.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server). Setup calls
use the lenient get_success_data() validator so failures surface as clear
"Setup step failed" errors.

Identity threading: after creating an Agent record, every Agent-role call
uses make_agent_headers(agent["id"]) — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_agent_headers,
    make_contracts_manager_headers,
    make_royalties_accountant_headers,
)

ADMIN = TEST_USERS["agency_admin_headers"]
CM = TEST_USERS["contracts_manager_headers"]
RA = TEST_USERS["royalties_accountant_headers"]


# ---------------------------------------------------------------------------
# Tier 1: roster building blocks
# ---------------------------------------------------------------------------

def create_agency(name="Test Agency", commission_pct=0.15, slush_capacity=50) -> dict:
    """Create an agency. Returns the agency resource."""
    return get_success_data(api_client.create_agency(
        factories.create_agency_payload(
            name=name, commission_pct=commission_pct, slush_capacity=slush_capacity
        ),
        ADMIN,
    ))


def create_agent(agency_id: str, display_name="Agent One") -> dict:
    return get_success_data(api_client.create_agent(
        factories.create_agent_payload(agency_id, display_name=display_name), ADMIN
    ))


def create_author(agency_id: str, display_name="Author One") -> dict:
    return get_success_data(api_client.create_author(
        factories.create_author_payload(agency_id, display_name=display_name), ADMIN
    ))


def create_editor(agency_id: str, display_name="Ed A", imprint="Imprint A") -> dict:
    return get_success_data(api_client.create_editor(
        factories.create_editor_payload(agency_id, display_name=display_name, imprint=imprint),
        ADMIN,
    ))


def close_period(agency_id: str) -> dict:
    """Advance the royalty period by one. Returns the updated agency."""
    return get_success_data(api_client.close_period(agency_id, ADMIN))


def close_period_as_accountant(agency_id: str) -> dict:
    return get_success_data(api_client.close_period(agency_id, RA))


def close_books(agency_id: str) -> dict:
    return get_success_data(api_client.close_books(agency_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: query -> manuscript -> agreement pipeline
# ---------------------------------------------------------------------------

def intake_query(agent_id: str, author_id: str, genre="FICTION", word_count=90000) -> dict:
    """Intake a query letter as the given agent. Returns the QueryLetter."""
    return get_success_data(api_client.create_query_letter(
        factories.create_query_letter_payload(author_id, genre=genre, word_count=word_count),
        make_agent_headers(agent_id),
    ))


def assign_query(query_id: str, acting_agent_id: str, assignee_agent_id: str = None) -> dict:
    """Assign a query (RECEIVED -> IN_REVIEW). Defaults to self-assignment."""
    return get_success_data(api_client.assign_query(
        query_id,
        {"agent_id": assignee_agent_id or acting_agent_id},
        make_agent_headers(acting_agent_id),
    ))


def request_manuscript(query_id: str, agent_id: str, title="Test Manuscript") -> dict:
    """IN_REVIEW -> REQUESTED; returns the spawned Manuscript."""
    return get_success_data(api_client.request_manuscript(
        query_id, factories.request_manuscript_payload(title=title),
        make_agent_headers(agent_id),
    ))


def assign_reader(manuscript_id: str, acting_agent_id: str, reader_agent_id: str = None) -> dict:
    return get_success_data(api_client.assign_reader(
        manuscript_id,
        {"agent_id": reader_agent_id or acting_agent_id},
        make_agent_headers(acting_agent_id),
    ))


def evaluate_manuscript(manuscript_id: str, agent_id: str, eval_score=80) -> dict:
    return get_success_data(api_client.evaluate_manuscript(
        manuscript_id,
        factories.evaluate_manuscript_payload(eval_score=eval_score),
        make_agent_headers(agent_id),
    ))


def accept_manuscript(manuscript_id: str, agent_id: str) -> dict:
    return get_success_data(api_client.accept_manuscript(
        manuscript_id, make_agent_headers(agent_id)
    ))


def create_accepted_manuscript(agency_id: str, agent_id: str, author_id: str,
                               genre="FICTION", word_count=90000,
                               title="Test Manuscript", eval_score=80) -> dict:
    """query -> assign -> request-manuscript -> assign-reader -> evaluate -> accept.

    Returns a context dict with the query and the ACCEPTED manuscript.
    """
    query = intake_query(agent_id, author_id, genre=genre, word_count=word_count)
    assign_query(query["id"], agent_id)
    manuscript = request_manuscript(query["id"], agent_id, title=title)
    assign_reader(manuscript["id"], agent_id)
    evaluate_manuscript(manuscript["id"], agent_id, eval_score=eval_score)
    manuscript = accept_manuscript(manuscript["id"], agent_id)
    return {"query": query, "manuscript": manuscript}


def create_signed_agreement(agency_id: str, agent_id: str, author_id: str,
                            manuscript_id: str, commission_pct_override=None) -> dict:
    """Draft -> offer -> sign a client agreement. Returns the SIGNED agreement."""
    payload = factories.create_client_agreement_payload(author_id, manuscript_id, agent_id)
    if commission_pct_override is not None:
        payload["commission_pct_override"] = commission_pct_override
    agreement = get_success_data(api_client.create_client_agreement(
        payload, make_agent_headers(agent_id)
    ))
    get_success_data(api_client.offer_agreement(agreement["id"], make_agent_headers(agent_id)))
    return get_success_data(api_client.sign_agreement(
        agreement["id"], make_agent_headers(agent_id)
    ))


def setup_signed_pipeline(commission_pct=0.15, slush_capacity=50,
                          commission_pct_override=None, eval_score=80,
                          genre="FICTION", word_count=90000,
                          agency_name="Test Agency") -> dict:
    """Agency + agent + author + ACCEPTED manuscript + SIGNED agreement.

    Returns ctx: {agency, agent, author, query, manuscript, agreement}.
    """
    agency = create_agency(name=agency_name, commission_pct=commission_pct,
                           slush_capacity=slush_capacity)
    agent = create_agent(agency["id"])
    author = create_author(agency["id"])
    pipe = create_accepted_manuscript(
        agency["id"], agent["id"], author["id"],
        genre=genre, word_count=word_count, eval_score=eval_score,
    )
    agreement = create_signed_agreement(
        agency["id"], agent["id"], author["id"], pipe["manuscript"]["id"],
        commission_pct_override=commission_pct_override,
    )
    return {
        "agency": agency,
        "agent": agent,
        "author": author,
        "query": pipe["query"],
        "manuscript": pipe["manuscript"],
        "agreement": agreement,
    }


# ---------------------------------------------------------------------------
# Tier 3: submission rounds and offers
# ---------------------------------------------------------------------------

def create_round(manuscript_id: str, agent_id: str, max_editors=5,
                 auction_mode=False, valuation_mode=None) -> dict:
    """Create a DRAFT submission round. Returns the round (capture .version for open)."""
    overrides = {"max_editors": max_editors}
    if auction_mode:
        overrides["auction_mode"] = True
    if valuation_mode is not None:
        overrides["valuation_mode"] = valuation_mode
    return get_success_data(api_client.create_submission_round(
        factories.create_submission_round_payload(manuscript_id, agent_id, **overrides),
        make_agent_headers(agent_id),
    ))


def queue_submission(round_id: str, editor_id: str, agent_id: str) -> dict:
    return get_success_data(api_client.create_submission(
        factories.create_submission_payload(round_id, editor_id),
        make_agent_headers(agent_id),
    ))


def open_round(round_data: dict, agent_id: str) -> dict:
    """DRAFT -> OPEN with the round's current version (OCC)."""
    return get_success_data(api_client.open_submission_round(
        round_data["id"],
        {"expected_submission_round_version": round_data["version"]},
        make_agent_headers(agent_id),
    ))


def send_submission(submission_id: str, agent_id: str) -> dict:
    return get_success_data(api_client.send_submission(
        submission_id, make_agent_headers(agent_id)
    ))


def record_offer(submission_id: str, agent_id: str, advance_cents=500000,
                 pct_hardcover=0.10, pct_trade=0.08, pct_ebook=0.25,
                 royalty_basis=None, includes_film_rights=False,
                 includes_foreign_rights=False, includes_audio_rights=False) -> dict:
    """Record an offer against a SENT / UNDER_CONSIDERATION submission."""
    overrides = {
        "advance_cents": advance_cents,
        "royalty_pct_hardcover": pct_hardcover,
        "royalty_pct_trade": pct_trade,
        "royalty_pct_ebook": pct_ebook,
    }
    if royalty_basis is not None:
        overrides["royalty_basis"] = royalty_basis
    if includes_film_rights:
        overrides["includes_film_rights"] = True
    if includes_foreign_rights:
        overrides["includes_foreign_rights"] = True
    if includes_audio_rights:
        overrides["includes_audio_rights"] = True
    return get_success_data(api_client.create_offer(
        factories.create_offer_payload(submission_id, **overrides),
        make_agent_headers(agent_id),
    ))


def accept_offer(offer_id: str, cm_user_id="cm-1") -> dict:
    return get_success_data(api_client.accept_offer(
        offer_id, make_contracts_manager_headers(cm_user_id)
    ))


def get_deal_for_offer(offer_id: str) -> dict:
    """Resolve the Deal created by an offer acceptance via the offer_id filter."""
    data, _meta = validate_paginated(api_client.list_deals(CM, params={"offer_id": offer_id}))
    assert len(data) == 1, f"expected exactly one deal for offer {offer_id}, got {len(data)}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 4: deals, installments, statements
# ---------------------------------------------------------------------------

def setup_negotiating_deal(advance_cents=500000, pct_hardcover=0.10, pct_trade=0.08,
                           pct_ebook=0.25, royalty_basis=None,
                           commission_pct_override=None,
                           includes_film_rights=False, includes_foreign_rights=False,
                           includes_audio_rights=False, agency_name="Test Agency") -> dict:
    """Full pipeline up to an accepted offer: deal in NEGOTIATING.

    Returns ctx with agency/agent/author/editor/query/manuscript/agreement/
    round/submission/offer/deal.
    """
    ctx = setup_signed_pipeline(commission_pct_override=commission_pct_override,
                                agency_name=agency_name)
    agent_id = ctx["agent"]["id"]
    editor = create_editor(ctx["agency"]["id"])
    round_data = create_round(ctx["manuscript"]["id"], agent_id)
    submission = queue_submission(round_data["id"], editor["id"], agent_id)
    open_round(round_data, agent_id)
    submission = send_submission(submission["id"], agent_id)
    offer = record_offer(
        submission["id"], agent_id,
        advance_cents=advance_cents, pct_hardcover=pct_hardcover,
        pct_trade=pct_trade, pct_ebook=pct_ebook, royalty_basis=royalty_basis,
        includes_film_rights=includes_film_rights,
        includes_foreign_rights=includes_foreign_rights,
        includes_audio_rights=includes_audio_rights,
    )
    accept_offer(offer["id"])
    deal = get_deal_for_offer(offer["id"])
    ctx.update({
        "editor": editor, "round": round_data, "submission": submission,
        "offer": offer, "deal": deal,
    })
    return ctx


def execute_deal(deal: dict, cm_user_id="cm-1") -> dict:
    """NEGOTIATING -> EXECUTED with the deal's current version (OCC)."""
    return get_success_data(api_client.execute_deal(
        deal["id"], {"expected_deal_version": deal["version"]},
        make_contracts_manager_headers(cm_user_id),
    ))


def setup_executed_deal(**kwargs) -> dict:
    """setup_negotiating_deal + execute. ctx['deal'] is the EXECUTED deal."""
    ctx = setup_negotiating_deal(**kwargs)
    ctx["deal"] = execute_deal(ctx["deal"])
    return ctx


def get_installment(deal_id: str, milestone: str) -> dict:
    """Fetch the single AdvanceInstallment of a deal for a milestone."""
    data, _meta = validate_paginated(api_client.list_advance_installments(
        RA, params={"deal_id": deal_id, "milestone": milestone}
    ))
    assert len(data) == 1, (
        f"expected exactly one {milestone} installment for deal {deal_id}, got {len(data)}"
    )
    return data[0]


def list_installments(deal_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_advance_installments(
        RA, params={"deal_id": deal_id}
    ))
    return data


def mark_installment_paid(installment_id: str) -> dict:
    return get_success_data(api_client.mark_installment_paid(installment_id, RA))


def setup_active_deal(**kwargs) -> dict:
    """Executed deal whose ON_SIGNING installment is PAID (deal flips ACTIVE)."""
    ctx = setup_executed_deal(**kwargs)
    signing = get_installment(ctx["deal"]["id"], "ON_SIGNING")
    ctx["signing_installment"] = mark_installment_paid(signing["id"])
    return ctx


def create_statement(deal_id: str, period_index=0,
                     units=(0, 0, 0), receipts=(0, 0, 0),
                     publisher_reported_royalty_cents=0) -> dict:
    """Intake a royalty statement as the royalties accountant."""
    u_h, u_t, u_e = units
    r_h, r_t, r_e = receipts
    return get_success_data(api_client.create_royalty_statement(
        factories.create_royalty_statement_payload(
            deal_id,
            period_index=period_index,
            units_hardcover=u_h, units_trade=u_t, units_ebook=u_e,
            net_receipts_hardcover_cents=r_h, net_receipts_trade_cents=r_t,
            net_receipts_ebook_cents=r_e,
            publisher_reported_royalty_cents=publisher_reported_royalty_cents,
        ),
        RA,
    ))


def reconcile_statement(statement_id: str) -> dict:
    return get_success_data(api_client.reconcile_statement(statement_id, RA))


def get_deal(deal_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_deal(deal_id, headers or RA))


def get_query(query_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_query_letter(query_id, headers or ADMIN))


def get_manuscript(manuscript_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_manuscript(manuscript_id, headers or ADMIN))


def get_submission(submission_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_submission(submission_id, headers or ADMIN))


def get_offer(offer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_offer(offer_id, headers or ADMIN))


def get_agency(agency_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_agency(agency_id, headers or ADMIN))


def get_round(round_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_submission_round(round_id, headers or ADMIN))


def get_agreement(agreement_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_client_agreement(agreement_id, headers or ADMIN))


def get_statement(statement_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_royalty_statement(statement_id, headers or RA))


def get_installment_by_id(installment_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_advance_installment(installment_id, headers or RA))
