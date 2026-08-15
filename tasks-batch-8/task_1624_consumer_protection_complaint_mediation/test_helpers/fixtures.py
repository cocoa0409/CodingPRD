"""Composite setup helpers — multi-step PRD workflows built from public endpoints.

Every fixture builds its preconditions from scratch (the server restarts before
each test, so every test begins against an empty database and the logical clock
at 2026-08-01T00:00:00Z — PRD §2.6). Setup calls use get_success_data so a setup
failure surfaces as a clear "Setup step failed" error.

Identity threading: entity-backed callers (Consumer / Business / Mediator) always
use make_*_headers(entity["id"]); opaque staff use the shared TEST_USERS entries.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_business_payload,
    create_business_response_payload,
    create_close_unresolved_payload,
    create_complaint_payload,
    create_consumer_payload,
    create_mediation_room_payload,
    create_mediation_session_payload,
    create_mediator_payload,
    create_referral_payload,
    create_restitution_payment_payload,
    create_review_payload,
    create_scam_alert_payload,
    create_screen_payload,
    create_settlement_offer_payload,
    create_settlement_payload,
)
from .test_users import (
    TEST_USERS,
    make_business_headers,
    make_consumer_headers,
    make_mediator_headers,
)

ANONYMOUS = TEST_USERS["anonymous_headers"]
OFFICER_1 = TEST_USERS["intake_officer_headers"]
OFFICER_2 = TEST_USERS["intake_officer_2_headers"]
ATTORNEY_1 = TEST_USERS["enforcement_attorney_headers"]
ATTORNEY_9 = TEST_USERS["enforcement_attorney_2_headers"]
DIRECTOR_1 = TEST_USERS["unit_director_headers"]
DIRECTOR_2 = TEST_USERS["unit_director_2_headers"]
DIRECTOR_3 = TEST_USERS["unit_director_3_headers"]

DEFAULT_SESSION_START = "2026-08-10T10:00:00Z"
DEFAULT_SESSION_END = "2026-08-10T11:00:00Z"


# ---------------------------------------------------------------------------
# Primitive step helpers (single endpoint calls)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock; runs the ordered sweep (PRD §2.6)."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, DIRECTOR_1))


def register_consumer(**overrides) -> dict:
    return get_success_data(api_client.create_consumer(create_consumer_payload(**overrides), ANONYMOUS))


def register_business(**overrides) -> dict:
    return get_success_data(api_client.create_business(create_business_payload(**overrides), ANONYMOUS))


def register_mediator(**overrides) -> dict:
    return get_success_data(api_client.create_mediator(create_mediator_payload(**overrides), DIRECTOR_1))


def register_mediation_room(**overrides) -> dict:
    return get_success_data(api_client.create_mediation_room(create_mediation_room_payload(**overrides), DIRECTOR_1))


def register_case_parties(*, business_overrides=None, mediator_overrides=None,
                          consumer_overrides=None, room_overrides=None,
                          with_mediator=True, with_room=True) -> dict:
    """Register the standard cast: one consumer, one business, optionally one
    mediator and one room. Returns {"consumer", "business", "mediator", "room"}."""
    parties = {
        "consumer": register_consumer(**(consumer_overrides or {})),
        "business": register_business(**(business_overrides or {})),
    }
    if with_mediator:
        parties["mediator"] = register_mediator(**(mediator_overrides or {}))
    if with_room:
        parties["room"] = register_mediation_room(**(room_overrides or {}))
    return parties


def file_complaint(consumer: dict, business: dict, **overrides) -> dict:
    """File a complaint as its consumer (entity-backed ownership, PRD §3.2)."""
    payload = create_complaint_payload(consumer["id"], business["id"], **overrides)
    return get_success_data(api_client.create_complaint(payload, make_consumer_headers(consumer["id"])))


def screen_accept(complaint_id: str, officer=OFFICER_1) -> dict:
    return get_success_data(api_client.screen_complaint(complaint_id, create_screen_payload("ACCEPT"), officer))


def screen_decline(complaint_id: str, decline_reason: str, officer=OFFICER_1) -> dict:
    return get_success_data(
        api_client.screen_complaint(
            complaint_id, create_screen_payload("DECLINE", decline_reason=decline_reason), officer
        )
    )


def notify_business(complaint_id: str, officer=OFFICER_1) -> dict:
    return get_success_data(api_client.notify_business(complaint_id, officer))


def submit_response(complaint_id: str, business: dict, response_text: str = "we will make it right") -> dict:
    payload = create_business_response_payload(response_text=response_text)
    return get_success_data(
        api_client.submit_business_response(complaint_id, payload, make_business_headers(business["id"]))
    )


def review_response(response_id: str, verdict: str = "SUFFICIENT", officer=OFFICER_1) -> dict:
    return get_success_data(
        api_client.review_business_response(response_id, create_review_payload(verdict), officer)
    )


def offer_mediation(complaint_id: str, officer=OFFICER_1) -> dict:
    return get_success_data(api_client.offer_mediation(complaint_id, officer))


def propose_session(complaint_id: str, mediator: dict, room: dict,
                    starts_at: str = DEFAULT_SESSION_START, ends_at: str = DEFAULT_SESSION_END) -> dict:
    payload = create_mediation_session_payload(
        mediator["id"], room["id"], starts_at=starts_at, ends_at=ends_at
    )
    return get_success_data(
        api_client.create_mediation_session(complaint_id, payload, make_mediator_headers(mediator["id"]))
    )


def confirm_session(session_id: str, party_headers: dict) -> dict:
    return get_success_data(api_client.confirm_session(session_id, party_headers))


def dual_confirm_session(session_id: str, consumer: dict, business: dict) -> dict:
    """Both parties confirm; the second confirmation flips the session CONFIRMED
    and lifts the complaint to MEDIATION_ACTIVE (PRD §3.4)."""
    confirm_session(session_id, make_consumer_headers(consumer["id"]))
    return confirm_session(session_id, make_business_headers(business["id"]))


def complete_session(session_id: str, mediator: dict, payload: dict, at_clock: str = None) -> dict:
    """Complete a session as its owning mediator, optionally moving the clock first."""
    if at_clock is not None:
        set_clock(at_clock)
    return get_success_data(
        api_client.complete_session(session_id, payload, make_mediator_headers(mediator["id"]))
    )


def get_complaint(complaint_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_complaint(complaint_id, headers or OFFICER_1))


def get_business(business_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_business(business_id, headers or DIRECTOR_1))


def get_mediator(mediator_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_mediator(mediator_id, headers or DIRECTOR_1))


def get_settlement(settlement_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, headers or OFFICER_1))


def get_offer(offer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_settlement_offer(offer_id, headers or OFFICER_1))


def get_payment(payment_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_restitution_payment(payment_id, headers or OFFICER_1))


def complaint_version(complaint_id: str) -> int:
    return get_complaint(complaint_id)["version"]


def tender_offer(complaint_id: str, party: dict, party_role: str,
                 restitution_amount_cents: int, **overrides) -> dict:
    """Tender a settlement offer with the concurrency token (PRD §2.8): re-reads
    the complaint version, then posts as the tendering party."""
    version = complaint_version(complaint_id)
    payload = create_settlement_offer_payload(
        party_role, version, restitution_amount_cents=restitution_amount_cents, **overrides
    )
    if party_role == "BUSINESS":
        headers = make_business_headers(party["id"])
    else:
        headers = make_consumer_headers(party["id"])
    return get_success_data(api_client.create_settlement_offer(complaint_id, payload, headers))


def accept_offer(offer_id: str, counterparty: dict, counterparty_role: str) -> dict:
    """Counter-party acceptance (PRD §3.5)."""
    if counterparty_role == "BUSINESS":
        headers = make_business_headers(counterparty["id"])
    else:
        headers = make_consumer_headers(counterparty["id"])
    return get_success_data(api_client.accept_offer(offer_id, headers))


def create_settlement_for_complaint(complaint_id: str, mediator: dict) -> dict:
    """Document the latest accepted offer as a settlement (PRD §3.6), re-reading
    the complaint version for the concurrency token first."""
    version = complaint_version(complaint_id)
    return get_success_data(
        api_client.create_settlement(
            complaint_id, create_settlement_payload(version), make_mediator_headers(mediator["id"])
        )
    )


def execute_settlement(settlement_id: str, mediator: dict) -> dict:
    return get_success_data(
        api_client.execute_settlement(settlement_id, make_mediator_headers(mediator["id"]))
    )


def pledge_payment(business: dict, amount_cents: int, allocation_method: str = None) -> dict:
    overrides = {}
    if allocation_method is not None:
        overrides["allocation_method"] = allocation_method
    payload = create_restitution_payment_payload(business["id"], amount_cents, **overrides)
    return get_success_data(
        api_client.pledge_restitution_payment(business["id"], payload, make_business_headers(business["id"]))
    )


def mark_received(payment_id: str, officer=OFFICER_1) -> dict:
    return get_success_data(api_client.mark_payment_received(payment_id, officer))


def close_unresolved(complaint_id: str, officer=OFFICER_2, **overrides) -> dict:
    return get_success_data(
        api_client.close_unresolved(complaint_id, create_close_unresolved_payload(**overrides), officer)
    )


def refer_complaint(complaint_id: str, reason: str = "pattern of harm under review",
                    headers=OFFICER_1) -> dict:
    return get_success_data(
        api_client.refer_enforcement(complaint_id, create_referral_payload(reason=reason), headers)
    )


def draft_scam_alert(headers, **overrides) -> dict:
    return get_success_data(api_client.create_scam_alert(create_scam_alert_payload(**overrides), headers))


# ---------------------------------------------------------------------------
# Composite state progression
# ---------------------------------------------------------------------------
def drive_to_mediation_active(consumer: dict, business: dict, mediator: dict, room: dict,
                              *, complaint_overrides=None,
                              session_starts_at: str = DEFAULT_SESSION_START,
                              session_ends_at: str = DEFAULT_SESSION_END,
                              officer=OFFICER_1) -> dict:
    """File -> ACCEPT -> notify -> response -> SUFFICIENT -> offer-mediation ->
    session -> dual party confirmation. Returns {"complaint", "session", "response"}."""
    complaint = file_complaint(consumer, business, **(complaint_overrides or {}))
    screen_accept(complaint["id"], officer)
    notify_business(complaint["id"], officer)
    response = submit_response(complaint["id"], business)
    review_response(response["id"], "SUFFICIENT", officer)
    offer_mediation(complaint["id"], officer)
    session = propose_session(complaint["id"], mediator, room, session_starts_at, session_ends_at)
    dual_confirm_session(session["id"], consumer, business)
    return {
        "complaint": get_complaint(complaint["id"]),
        "session": get_success_data(api_client.get_mediation_session(session["id"], make_mediator_headers(mediator["id"]))),
        "response": response,
    }


def setup_mediation_active_case(**overrides) -> dict:
    """Register parties and drive one complaint into MEDIATION_ACTIVE (PRD §3.4)."""
    parties = register_case_parties(
        business_overrides=overrides.get("business_overrides"),
        mediator_overrides=overrides.get("mediator_overrides"),
        consumer_overrides=overrides.get("consumer_overrides"),
        room_overrides=overrides.get("room_overrides"),
    )
    driven = drive_to_mediation_active(
        parties["consumer"], parties["business"], parties["mediator"], parties["room"],
        complaint_overrides=overrides.get("complaint_overrides"),
        session_starts_at=overrides.get("session_starts_at", DEFAULT_SESSION_START),
        session_ends_at=overrides.get("session_ends_at", DEFAULT_SESSION_END),
        officer=overrides.get("officer", OFFICER_1),
    )
    return {**parties, **driven}


def drive_to_accepted_offer(ctx: dict, *, restitution_cents: int,
                            offer_by: str = "BUSINESS", **offer_overrides) -> dict:
    """From MEDIATION_ACTIVE: tender an offer and have the counter-party accept it
    (PRD §3.5). Returns the ACCEPTED offer (with cooling_off_until set)."""
    complaint = ctx["complaint"]
    if offer_by == "BUSINESS":
        offer = tender_offer(complaint["id"], ctx["business"], "BUSINESS", restitution_cents, **offer_overrides)
        offer = accept_offer(offer["id"], ctx["consumer"], "CONSUMER")
    else:
        offer = tender_offer(complaint["id"], ctx["consumer"], "CONSUMER", restitution_cents, **offer_overrides)
        offer = accept_offer(offer["id"], ctx["business"], "BUSINESS")
    return offer


def drive_to_executed_settlement(consumer: dict, business: dict, mediator: dict, room: dict,
                                 *, incident_date: str, description: str,
                                 category: str = "REFUND_REFUSAL",
                                 restitution_cents: int,
                                 session_starts_at: str, session_ends_at: str,
                                 amount_in_dispute_cents: int = None,
                                 officer=OFFICER_1,
                                 execute_clock: str = None) -> dict:
    """Full negotiation path (PRD §3.2-§3.6): file -> ... -> MEDIATION_ACTIVE ->
    business-tendered offer -> consumer accept -> clock to the end of cooling-off
    -> settlement documented (DRAFT) -> EXECUTED. Returns complaint/offer/settlement."""
    complaint_overrides = {
        "incident_date": incident_date,
        "category": category,
        "description": description,
        "amount_in_dispute_cents": amount_in_dispute_cents if amount_in_dispute_cents is not None else restitution_cents,
    }
    driven = drive_to_mediation_active(
        consumer, business, mediator, room,
        complaint_overrides=complaint_overrides,
        session_starts_at=session_starts_at,
        session_ends_at=session_ends_at,
        officer=officer,
    )
    ctx = {"consumer": consumer, "business": business, "mediator": mediator, "room": room, **driven}
    offer = drive_to_accepted_offer(ctx, restitution_cents=restitution_cents, offer_by="BUSINESS")
    # Execution first becomes permitted exactly at cooling_off_until (PRD §3.6).
    set_clock(execute_clock or offer["cooling_off_until"])
    settlement = create_settlement_for_complaint(driven["complaint"]["id"], mediator)
    settlement = execute_settlement(settlement["id"], mediator)
    return {
        **ctx,
        "offer": offer,
        "settlement": settlement,
        "complaint": get_complaint(driven["complaint"]["id"]),
    }


def setup_settled_case(*, restitution_cents: int = 5000, officer=OFFICER_1) -> dict:
    """Full lifecycle through SETTLED (PRD §3.7): executed settlement fulfilled by
    an exactly-covering CHRONOLOGICAL payment. Complaint ends SETTLED + EMBARGOED."""
    parties = register_case_parties()
    ctx = drive_to_executed_settlement(
        parties["consumer"], parties["business"], parties["mediator"], parties["room"],
        incident_date="2026-07-01", description="settle me",
        restitution_cents=restitution_cents,
        session_starts_at=DEFAULT_SESSION_START, session_ends_at=DEFAULT_SESSION_END,
        officer=officer,
    )
    settlement = ctx["settlement"]
    payment = pledge_payment(parties["business"], settlement["outstanding_cents"])
    payment = mark_received(payment["id"], officer)
    return {
        **ctx,
        "payment": payment,
        "settlement": get_settlement(settlement["id"]),
        "complaint": get_complaint(ctx["complaint"]["id"]),
        "business": get_business(parties["business"]["id"]),
    }


def setup_referred_case(*, category: str = "DECEPTIVE_PRACTICE", reason: str = "pattern of harm",
                        referral_headers=OFFICER_1, officer=OFFICER_1) -> dict:
    """Complaint screened ACCEPTED then referred to enforcement (PRD §3.8):
    case REFERRED_ENFORCEMENT, publication EMBARGOED, referral PENDING_REVIEW."""
    parties = register_case_parties(with_mediator=False, with_room=False)
    complaint = file_complaint(parties["consumer"], parties["business"], category=category)
    screen_accept(complaint["id"], officer)
    referral = refer_complaint(complaint["id"], reason, referral_headers)
    return {
        **parties,
        "complaint": get_complaint(complaint["id"]),
        "referral": referral,
    }
