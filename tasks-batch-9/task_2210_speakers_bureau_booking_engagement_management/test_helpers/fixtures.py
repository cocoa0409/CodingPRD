"""Composite setup helpers.

Each helper drives the public API only, in the order the PRD prescribes, and
returns a bundle dict whose keys name the rows it created.  Every bundle also
carries the header sets a test needs, including the entity-backed speaker and
client identities built from the ids of the rows that were actually created.

Bundle keys used consistently across helpers:

    speaker, client, inquiry, proposal, option, engagement, contract,
    travel_expense, invoice, remittance, feedback, claim, grant,
    admin_headers, agent_headers, speaker_headers, client_headers
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_STARTUP_UTC
from .test_users import (
    make_admin_headers,
    make_agent_headers,
    make_client_headers,
    make_speaker_headers,
)

SPEAKER_SIGNATURE_NAME = "Dana Reyes"
CLIENT_SIGNATURE_NAME = "M. Okafor"
DELIVERY_CLOCK_UTC = "2026-10-15T20:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1 helpers: single rows and clock control
# ---------------------------------------------------------------------------


def set_clock(api, to_iso8601: str = CLOCK_STARTUP_UTC) -> dict:
    """Move the logical clock; returns the clock payload."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601)))


def create_speaker(api, headers=None, **overrides) -> dict:
    headers = headers or make_admin_headers()
    return get_success_data(api.create_speaker(f.speaker_payload(**overrides), headers))


def create_second_speaker(api, headers=None, **overrides) -> dict:
    headers = headers or make_admin_headers()
    return get_success_data(
        api.create_speaker(f.second_speaker_payload(**overrides), headers)
    )


def create_client(api, headers=None, **overrides) -> dict:
    headers = headers or make_admin_headers()
    return get_success_data(api.create_client(f.client_payload(**overrides), headers))


def create_second_client(api, headers=None, **overrides) -> dict:
    headers = headers or make_admin_headers()
    return get_success_data(
        api.create_client(f.second_client_payload(**overrides), headers)
    )


def create_inquiry(api, client_row: dict, headers=None, **overrides) -> dict:
    headers = headers or make_agent_headers()
    return get_success_data(
        api.create_inquiry(f.inquiry_payload(client_row["id"], **overrides), headers)
    )


def qualify_inquiry(api, inquiry_id: str, headers=None) -> dict:
    headers = headers or make_agent_headers()
    return get_success_data(
        api.qualify_inquiry(inquiry_id, f.qualify_payload(), headers)
    )


def create_draft_proposal(api, inquiry: dict, headers=None, **overrides) -> dict:
    headers = headers or make_agent_headers()
    return get_success_data(
        api.create_proposal(
            inquiry["id"],
            f.proposal_payload(inquiry["version"], **overrides),
            headers,
        )
    )


def add_option(api, proposal: dict, speaker: dict, headers=None, **overrides) -> dict:
    headers = headers or make_agent_headers()
    return get_success_data(
        api.create_proposal_option(
            f.proposal_option_payload(proposal["id"], speaker["id"], **overrides),
            headers,
        )
    )


def create_hold(api, speaker: dict, headers=None, **overrides) -> dict:
    headers = headers or make_admin_headers()
    return get_success_data(
        api.create_speaker_hold(f.speaker_hold_payload(speaker["id"], **overrides), headers)
    )


# ---------------------------------------------------------------------------
# Small readers used by the composites
# ---------------------------------------------------------------------------


def read_speaker(api, speaker_id: str, headers=None) -> dict:
    return get_success_data(api.get_speaker(speaker_id, headers or make_admin_headers()))


def read_client(api, client_id: str, headers=None) -> dict:
    return get_success_data(api.get_client(client_id, headers or make_admin_headers()))


def read_inquiry(api, inquiry_id: str, headers=None) -> dict:
    return get_success_data(api.get_inquiry(inquiry_id, headers or make_agent_headers()))


def read_proposal(api, proposal_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_proposal(proposal_id, headers or make_agent_headers())
    )


def read_option(api, option_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_proposal_option(option_id, headers or make_agent_headers())
    )


def read_engagement(api, engagement_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_engagement(engagement_id, headers or make_admin_headers())
    )


def read_contract(api, contract_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_contract(contract_id, headers or make_admin_headers())
    )


def read_travel_expense(api, expense_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_travel_expense(expense_id, headers or make_admin_headers())
    )


def read_invoice(api, invoice_id: str, headers=None) -> dict:
    return get_success_data(api.get_invoice(invoice_id, headers or make_admin_headers()))


def read_remittance(api, remittance_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_remittance(remittance_id, headers or make_admin_headers())
    )


def read_grant(api, grant_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_exclusivity_grant(grant_id, headers or make_admin_headers())
    )


def read_hold(api, hold_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_speaker_hold(hold_id, headers or make_admin_headers())
    )


def read_feedback(api, feedback_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_feedback(feedback_id, headers or make_admin_headers())
    )


def read_claim(api, claim_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_circumvention_claim(claim_id, headers or make_admin_headers())
    )


def find_invoices_for(api, engagement_id: str, headers=None) -> list:
    data = get_success_data(
        api.list_invoices(
            headers or make_admin_headers(), params={"engagement_id": engagement_id}
        )
    )
    return data if isinstance(data, list) else data["items"]


def find_remittances_for(api, engagement_id: str, headers=None) -> list:
    data = get_success_data(
        api.list_remittances(
            headers or make_admin_headers(), params={"engagement_id": engagement_id}
        )
    )
    return data if isinstance(data, list) else data["items"]


def find_grants_for_speaker(api, speaker_id: str, headers=None) -> list:
    data = get_success_data(
        api.list_exclusivity_grants(
            headers or make_admin_headers(), params={"speaker_id": speaker_id}
        )
    )
    return data if isinstance(data, list) else data["items"]


def find_holds_for_speaker(api, speaker_id: str, headers=None) -> list:
    data = get_success_data(
        api.list_speaker_holds(
            headers or make_admin_headers(), params={"speaker_id": speaker_id}
        )
    )
    return data if isinstance(data, list) else data["items"]


# ---------------------------------------------------------------------------
# Tier 2 composites: the entity chain up to a live proposal
# ---------------------------------------------------------------------------


def setup_qualified_inquiry(
    api,
    speaker_overrides=None,
    client_overrides=None,
    inquiry_overrides=None,
    clock_utc: str = CLOCK_STARTUP_UTC,
) -> dict:
    """Speaker + client + inquiry, with the inquiry already QUALIFIED."""
    set_clock(api, clock_utc)
    speaker = create_speaker(api, **(speaker_overrides or {}))
    client_row = create_client(api, **(client_overrides or {}))
    inquiry = create_inquiry(api, client_row, **(inquiry_overrides or {}))
    inquiry = qualify_inquiry(api, inquiry["id"])
    return {
        "speaker": speaker,
        "client": client_row,
        "inquiry": inquiry,
        "admin_headers": make_admin_headers(),
        "agent_headers": make_agent_headers(),
        "speaker_headers": make_speaker_headers(speaker["id"]),
        "client_headers": make_client_headers(client_row["id"]),
    }


def setup_draft_proposal(
    api,
    speaker_overrides=None,
    client_overrides=None,
    inquiry_overrides=None,
    proposal_overrides=None,
    option_overrides=None,
    clock_utc: str = CLOCK_STARTUP_UTC,
) -> dict:
    """A DRAFT proposal carrying one OFFERED option."""
    bundle = setup_qualified_inquiry(
        api,
        speaker_overrides=speaker_overrides,
        client_overrides=client_overrides,
        inquiry_overrides=inquiry_overrides,
        clock_utc=clock_utc,
    )
    proposal = create_draft_proposal(
        api, bundle["inquiry"], **(proposal_overrides or {})
    )
    option = add_option(
        api, proposal, bundle["speaker"], **(option_overrides or {})
    )
    bundle["proposal"] = read_proposal(api, proposal["id"])
    bundle["option"] = option
    return bundle


def setup_presented_proposal(api, **kwargs) -> dict:
    """A PRESENTED proposal whose inquiry has advanced to PROPOSED."""
    bundle = setup_draft_proposal(api, **kwargs)
    get_success_data(
        api.present_proposal(bundle["proposal"]["id"], make_agent_headers())
    )
    bundle["proposal"] = read_proposal(api, bundle["proposal"]["id"])
    bundle["inquiry"] = read_inquiry(api, bundle["inquiry"]["id"])
    return bundle


def setup_presented_proposal_with_two_options(
    api,
    second_option_overrides=None,
    **kwargs,
) -> dict:
    """A PRESENTED proposal with two ranked options on two different speakers."""
    bundle = setup_draft_proposal(api, **kwargs)
    second_speaker = create_second_speaker(api)
    overrides = {"quoted_fee_cents": 1_150_000, "rank_no": 2, "travel_allowance_cents": 0}
    overrides.update(second_option_overrides or {})
    second_option = add_option(api, bundle["proposal"], second_speaker, **overrides)
    get_success_data(
        api.present_proposal(bundle["proposal"]["id"], make_agent_headers())
    )
    bundle["second_speaker"] = second_speaker
    bundle["second_speaker_headers"] = make_speaker_headers(second_speaker["id"])
    bundle["second_option"] = second_option
    bundle["proposal"] = read_proposal(api, bundle["proposal"]["id"])
    bundle["inquiry"] = read_inquiry(api, bundle["inquiry"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 3 composites: engagement lifecycle shortcuts
# ---------------------------------------------------------------------------


def setup_offered_engagement(api, **kwargs) -> dict:
    """The client has selected an option, so an OFFERED engagement exists."""
    bundle = setup_presented_proposal(api, **kwargs)
    engagement = get_success_data(
        api.select_proposal_option(
            bundle["proposal"]["id"],
            f.select_option_payload(bundle["option"]["id"]),
            bundle["client_headers"],
        )
    )
    bundle["selection_response"] = engagement
    bundle["engagement"] = read_engagement(api, engagement["id"])
    bundle["proposal"] = read_proposal(api, bundle["proposal"]["id"])
    bundle["option"] = read_option(api, bundle["option"]["id"])
    bundle["inquiry"] = read_inquiry(api, bundle["inquiry"]["id"])
    return bundle


def setup_confirmed_engagement(api, **kwargs) -> dict:
    """The speaker has accepted, so the engagement is CONFIRMED and held."""
    bundle = setup_offered_engagement(api, **kwargs)
    get_success_data(
        api.confirm_engagement(bundle["engagement"]["id"], bundle["speaker_headers"])
    )
    bundle["engagement"] = read_engagement(api, bundle["engagement"]["id"])
    bundle["speaker"] = read_speaker(api, bundle["speaker"]["id"])
    return bundle


def setup_drafted_contract(api, contract_overrides=None, **kwargs) -> dict:
    """A DRAFT contract attached to a CONFIRMED engagement."""
    bundle = setup_confirmed_engagement(api, **kwargs)
    contract = get_success_data(
        api.create_contract(
            bundle["engagement"]["id"],
            f.contract_payload(**(contract_overrides or {})),
            make_agent_headers(),
        )
    )
    bundle["contract"] = contract
    return bundle


def setup_sent_contract(api, **kwargs) -> dict:
    """A contract that has been issued to both parties for signature."""
    bundle = setup_drafted_contract(api, **kwargs)
    get_success_data(
        api.send_contract(bundle["contract"]["id"], make_agent_headers())
    )
    bundle["contract"] = read_contract(api, bundle["contract"]["id"])
    return bundle


def setup_contracted_engagement(api, **kwargs) -> dict:
    """Both signature legs are in, so the contract is EXECUTED."""
    bundle = setup_sent_contract(api, **kwargs)
    get_success_data(
        api.sign_contract(
            bundle["contract"]["id"],
            f.signature_payload(SPEAKER_SIGNATURE_NAME),
            bundle["speaker_headers"],
        )
    )
    get_success_data(
        api.sign_contract(
            bundle["contract"]["id"],
            f.signature_payload(CLIENT_SIGNATURE_NAME),
            bundle["client_headers"],
        )
    )
    bundle["contract"] = read_contract(api, bundle["contract"]["id"])
    bundle["engagement"] = read_engagement(api, bundle["engagement"]["id"])
    bundle["speaker"] = read_speaker(api, bundle["speaker"]["id"])
    return bundle


def setup_engagement_with_approved_travel(
    api, travel_overrides=None, **kwargs
) -> dict:
    """An executed engagement carrying one APPROVED travel receipt."""
    bundle = setup_contracted_engagement(api, **kwargs)
    expense = get_success_data(
        api.create_travel_expense(
            bundle["engagement"]["id"],
            f.travel_expense_payload(**(travel_overrides or {})),
            bundle["speaker_headers"],
        )
    )
    get_success_data(
        api.approve_travel_expense(expense["id"], make_agent_headers())
    )
    bundle["travel_expense"] = read_travel_expense(api, expense["id"])
    bundle["engagement"] = read_engagement(api, bundle["engagement"]["id"])
    return bundle


def setup_delivered_engagement(
    api, delivery_clock_utc: str = DELIVERY_CLOCK_UTC, **kwargs
) -> dict:
    """Delivery has been recorded, so the invoice and remittance both exist."""
    bundle = setup_contracted_engagement(api, **kwargs)
    return _deliver(api, bundle, delivery_clock_utc)


def setup_delivered_engagement_with_travel(
    api, delivery_clock_utc: str = DELIVERY_CLOCK_UTC, **kwargs
) -> dict:
    """Delivery recorded on an engagement that carries approved travel."""
    bundle = setup_engagement_with_approved_travel(api, **kwargs)
    return _deliver(api, bundle, delivery_clock_utc)


def _deliver(api, bundle: dict, delivery_clock_utc: str) -> dict:
    set_clock(api, delivery_clock_utc)
    get_success_data(
        api.deliver_engagement(bundle["engagement"]["id"], make_agent_headers())
    )
    bundle["engagement"] = read_engagement(api, bundle["engagement"]["id"])
    bundle["speaker"] = read_speaker(api, bundle["speaker"]["id"])
    bundle["client"] = read_client(api, bundle["client"]["id"])
    invoices = find_invoices_for(api, bundle["engagement"]["id"])
    remittances = find_remittances_for(api, bundle["engagement"]["id"])
    bundle["invoice"] = invoices[0] if invoices else None
    bundle["remittance"] = remittances[0] if remittances else None
    return bundle


# ---------------------------------------------------------------------------
# Tier 4 composites: collection, accumulation and threshold targeting
# ---------------------------------------------------------------------------


def setup_paid_engagement(api, **kwargs) -> dict:
    """The invoice has been settled in full, so the remittance is APPROVED."""
    bundle = setup_delivered_engagement(api, **kwargs)
    invoice = bundle["invoice"]
    get_success_data(
        api.create_invoice_payment(
            invoice["id"],
            f.payment_payload(invoice["amount_due_cents"]),
            make_admin_headers(),
        )
    )
    bundle["invoice"] = read_invoice(api, invoice["id"])
    bundle["remittance"] = read_remittance(api, bundle["remittance"]["id"])
    bundle["engagement"] = read_engagement(api, bundle["engagement"]["id"])
    bundle["client"] = read_client(api, bundle["client"]["id"])
    bundle["speaker"] = read_speaker(api, bundle["speaker"]["id"])
    return bundle


def setup_remitted_engagement(api, reference: str = "WIRE-771", **kwargs) -> dict:
    """The speaker has been paid out, so the settlement reaches REMITTED."""
    bundle = setup_paid_engagement(api, **kwargs)
    get_success_data(
        api.pay_remittance(
            bundle["remittance"]["id"],
            f.remittance_payout_payload(reference),
            make_admin_headers(),
        )
    )
    bundle["remittance"] = read_remittance(api, bundle["remittance"]["id"])
    bundle["engagement"] = read_engagement(api, bundle["engagement"]["id"])
    bundle["speaker"] = read_speaker(api, bundle["speaker"]["id"])
    return bundle


def setup_delivered_engagement_with_feedback(
    api, feedback_overrides=None, **kwargs
) -> dict:
    """A delivered engagement that already carries the client's feedback."""
    bundle = setup_delivered_engagement(api, **kwargs)
    feedback = get_success_data(
        api.create_feedback(
            bundle["engagement"]["id"],
            f.feedback_payload(**(feedback_overrides or {})),
            bundle["client_headers"],
        )
    )
    bundle["feedback"] = feedback
    bundle["speaker"] = read_speaker(api, bundle["speaker"]["id"])
    return bundle


def add_second_engagement_for_speaker(
    api,
    bundle: dict,
    event_start_utc: str,
    event_end_utc: str,
    valid_until_utc: str,
    quoted_fee_cents: int = f.DEFAULT_QUOTED_FEE_CENTS,
    contract_overrides=None,
    deliver: bool = True,
    delivery_clock_utc=None,
    setup_clock_utc: str = CLOCK_STARTUP_UTC,
) -> dict:
    """Run the whole chain a second time for the same speaker and client.

    Returns a nested bundle under the keys ``inquiry_2``, ``proposal_2``,
    ``option_2``, ``engagement_2``, ``contract_2``, ``invoice_2`` and
    ``remittance_2`` so accumulation across two engagements can be checked.
    """
    set_clock(api, setup_clock_utc)
    inquiry = create_inquiry(
        api,
        bundle["client"],
        event_start_utc=event_start_utc,
        event_end_utc=event_end_utc,
    )
    inquiry = qualify_inquiry(api, inquiry["id"])
    proposal = create_draft_proposal(api, inquiry, valid_until_utc=valid_until_utc)
    option = add_option(
        api, proposal, bundle["speaker"], quoted_fee_cents=quoted_fee_cents
    )
    get_success_data(api.present_proposal(proposal["id"], make_agent_headers()))
    engagement = get_success_data(
        api.select_proposal_option(
            proposal["id"],
            f.select_option_payload(option["id"]),
            bundle["client_headers"],
        )
    )
    get_success_data(api.confirm_engagement(engagement["id"], bundle["speaker_headers"]))
    contract = get_success_data(
        api.create_contract(
            engagement["id"],
            f.contract_payload(**(contract_overrides or {})),
            make_agent_headers(),
        )
    )
    get_success_data(api.send_contract(contract["id"], make_agent_headers()))
    get_success_data(
        api.sign_contract(
            contract["id"],
            f.signature_payload(SPEAKER_SIGNATURE_NAME),
            bundle["speaker_headers"],
        )
    )
    get_success_data(
        api.sign_contract(
            contract["id"],
            f.signature_payload(CLIENT_SIGNATURE_NAME),
            bundle["client_headers"],
        )
    )
    if deliver:
        set_clock(api, delivery_clock_utc or _two_hours_after(event_end_utc))
        get_success_data(api.deliver_engagement(engagement["id"], make_agent_headers()))
    bundle["inquiry_2"] = read_inquiry(api, inquiry["id"])
    bundle["proposal_2"] = read_proposal(api, proposal["id"])
    bundle["option_2"] = read_option(api, option["id"])
    bundle["engagement_2"] = read_engagement(api, engagement["id"])
    bundle["contract_2"] = read_contract(api, contract["id"])
    invoices = find_invoices_for(api, engagement["id"])
    remittances = find_remittances_for(api, engagement["id"])
    bundle["invoice_2"] = invoices[0] if invoices else None
    bundle["remittance_2"] = remittances[0] if remittances else None
    bundle["speaker"] = read_speaker(api, bundle["speaker"]["id"])
    bundle["client"] = read_client(api, bundle["client"]["id"])
    return bundle


def _two_hours_after(event_end_utc: str) -> str:
    """A clock reading comfortably after the given event end."""
    from datetime import datetime, timedelta, timezone

    parsed = datetime.fromisoformat(event_end_utc.replace("Z", "+00:00"))
    moved = parsed.astimezone(timezone.utc) + timedelta(hours=2)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def setup_two_delivered_engagements(
    api,
    second_feedback=None,
    first_feedback=None,
    **kwargs,
) -> dict:
    """Two delivered engagements for one speaker, optionally each with feedback.

    Used to walk the delivery counter and the rolling score up to a tier gate.
    """
    bundle = setup_delivered_engagement(api, **kwargs)
    if first_feedback is not None:
        bundle["feedback"] = get_success_data(
            api.create_feedback(
                bundle["engagement"]["id"],
                f.feedback_payload(**first_feedback),
                bundle["client_headers"],
            )
        )
    bundle = add_second_engagement_for_speaker(
        api,
        bundle,
        event_start_utc="2026-11-20T16:00:00Z",
        event_end_utc="2026-11-20T18:00:00Z",
        valid_until_utc="2026-10-30T00:00:00Z",
        setup_clock_utc="2026-10-16T00:00:00Z",
    )
    if second_feedback is not None:
        bundle["feedback_2"] = get_success_data(
            api.create_feedback(
                bundle["engagement_2"]["id"],
                f.feedback_payload(**second_feedback),
                bundle["client_headers"],
            )
        )
    bundle["speaker"] = read_speaker(api, bundle["speaker"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 5 composites: terminal states and downstream consequences
# ---------------------------------------------------------------------------


def setup_cancelled_engagement(
    api,
    cancellation_clock_utc: str,
    cancelled_by_headers_key: str = "client_headers",
    cancellation_reason: str = "the client cancelled the conference",
    extra_cancel_fields=None,
    **kwargs,
) -> dict:
    """An executed engagement that is then cancelled at a chosen clock reading."""
    bundle = setup_contracted_engagement(api, **kwargs)
    set_clock(api, cancellation_clock_utc)
    payload = f.cancellation_payload(cancellation_reason, **(extra_cancel_fields or {}))
    headers = bundle[cancelled_by_headers_key] if cancelled_by_headers_key in bundle else cancelled_by_headers_key
    bundle["cancellation_response"] = get_success_data(
        api.cancel_engagement(bundle["engagement"]["id"], payload, headers)
    )
    bundle["engagement"] = read_engagement(api, bundle["engagement"]["id"])
    bundle["speaker"] = read_speaker(api, bundle["speaker"]["id"])
    bundle["client"] = read_client(api, bundle["client"]["id"])
    invoices = find_invoices_for(api, bundle["engagement"]["id"])
    bundle["retention_invoice"] = invoices[0] if invoices else None
    return bundle


def setup_exclusivity_grant_scenario(
    api,
    exclusivity_days: int = 90,
    competitor_event_start_utc: str = "2026-12-05T16:00:00Z",
    competitor_event_end_utc: str = "2026-12-05T18:00:00Z",
    competitor_industry_code: str = "HEALTHCARE",
    competitor_valid_until_utc: str = "2026-11-15T00:00:00Z",
) -> dict:
    """One executed engagement that mints a grant, plus a competing offer.

    The second client's engagement is left at OFFERED so a test can attempt the
    speaker's confirmation and observe whether the grant blocks it.
    """
    bundle = setup_contracted_engagement(
        api, contract_overrides={"exclusivity_days": exclusivity_days}
    )
    grants = find_grants_for_speaker(api, bundle["speaker"]["id"])
    bundle["grant"] = grants[0] if grants else None

    competitor = create_second_client(
        api, industry_code=competitor_industry_code
    )
    competitor_headers = make_client_headers(competitor["id"])
    competitor_inquiry = create_inquiry(
        api,
        competitor,
        event_start_utc=competitor_event_start_utc,
        event_end_utc=competitor_event_end_utc,
    )
    competitor_inquiry = qualify_inquiry(api, competitor_inquiry["id"])
    competitor_proposal = create_draft_proposal(
        api, competitor_inquiry, valid_until_utc=competitor_valid_until_utc
    )
    competitor_option = add_option(api, competitor_proposal, bundle["speaker"])
    get_success_data(
        api.present_proposal(competitor_proposal["id"], make_agent_headers())
    )
    competitor_engagement = get_success_data(
        api.select_proposal_option(
            competitor_proposal["id"],
            f.select_option_payload(competitor_option["id"]),
            competitor_headers,
        )
    )
    bundle["competitor_client"] = competitor
    bundle["competitor_client_headers"] = competitor_headers
    bundle["competitor_inquiry"] = competitor_inquiry
    bundle["competitor_proposal"] = read_proposal(api, competitor_proposal["id"])
    bundle["competitor_option"] = competitor_option
    bundle["competitor_engagement"] = read_engagement(api, competitor_engagement["id"])
    return bundle


def setup_upheld_claim(
    api,
    direct_event_date_utc: str = "2026-12-14T18:00:00Z",
    direct_fee_cents: int = 1_000_000,
    **kwargs,
) -> dict:
    """A delivered engagement plus one UPHELD non-circumvention claim."""
    bundle = setup_delivered_engagement(api, **kwargs)
    claim = get_success_data(
        api.create_circumvention_claim(
            f.circumvention_claim_payload(
                bundle["client"]["id"],
                bundle["speaker"]["id"],
                bundle["engagement"]["id"],
                direct_event_date_utc,
                direct_fee_cents,
            ),
            make_admin_headers(),
        )
    )
    get_success_data(
        api.resolve_circumvention_claim(
            claim["id"], f.claim_resolution_payload("UPHOLD"), make_admin_headers()
        )
    )
    bundle["claim"] = read_claim(api, claim["id"])
    bundle["client"] = read_client(api, bundle["client"]["id"])
    return bundle


def setup_client_on_credit_hold(
    api,
    second_direct_event_date_utc: str = "2026-12-20T18:00:00Z",
    second_direct_fee_cents: int = 800_000,
    **kwargs,
) -> dict:
    """Two upheld claims against one client, which puts its credit on HOLD.

    A second engagement is delivered first so the two claims sit on different
    source engagements, as the duplicate rule requires.
    """
    bundle = setup_upheld_claim(api, **kwargs)
    bundle = add_second_engagement_for_speaker(
        api,
        bundle,
        event_start_utc="2026-11-20T16:00:00Z",
        event_end_utc="2026-11-20T18:00:00Z",
        valid_until_utc="2026-10-30T00:00:00Z",
        setup_clock_utc="2026-10-16T00:00:00Z",
    )
    second_claim = get_success_data(
        api.create_circumvention_claim(
            f.circumvention_claim_payload(
                bundle["client"]["id"],
                bundle["speaker"]["id"],
                bundle["engagement_2"]["id"],
                second_direct_event_date_utc,
                second_direct_fee_cents,
            ),
            make_admin_headers(),
        )
    )
    get_success_data(
        api.resolve_circumvention_claim(
            second_claim["id"],
            f.claim_resolution_payload("UPHOLD"),
            make_admin_headers(),
        )
    )
    bundle["claim_2"] = read_claim(api, second_claim["id"])
    bundle["client"] = read_client(api, bundle["client"]["id"])
    return bundle
