"""Composite setup helpers for the personal-injury case-management benchmark.

Every fixture builds its preconditions from scratch through PRD-declared endpoints
(see PRD §3.x). The runner restarts the API server before every individual pytest
test, so each test starts from an empty database — no entities, no clock state.

Fixtures use `get_success_data()` (lenient validator) so a setup failure surfaces
as a clear "Setup failed" trace rather than a cryptic assertion deep inside a test.

Per PRD §2.1, X-User-ID is treated as opaque for every role; no role is entity-backed.
Some fixtures DO need to pin a particular X-User-ID — specifically for the
segregation-of-duties check on DemandLetter send, where the partner's X-User-ID
must differ from the drafter's X-User-ID (PRD §3.4). Those fixtures take
`drafter_user_id` and `partner_user_id` as parameters with safe defaults.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_client_payload,
    create_case_payload,
    create_provider_payload,
    create_records_request_payload,
    create_damages_item_payload,
    create_lien_payload,
    agree_lien_payload,
    create_demand_letter_payload,
    create_offer_payload,
    accept_offer_payload,
    create_court_event_payload,
    release_disbursement_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_attorney_headers,
    make_managing_partner_headers,
)


_ANON_HEADERS: dict = {}
_PARALEGAL_HEADERS = TEST_USERS["paralegal_headers"]
_ATTORNEY_HEADERS = TEST_USERS["attorney_headers"]
_PARTNER_HEADERS = TEST_USERS["managing_partner_headers"]
_ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]


# ─── Tier 0: clock ──────────────────────────────────────────────


def set_clock(iso8601: str) -> dict:
    """Mutate SystemClock.current_utc (PRD §2.10)."""
    res = api_client.set_clock(set_clock_payload(iso8601), _ADMIN_HEADERS)
    return get_success_data(res)


# ─── Tier 1: low-level entity creation (one POST each) ──────────


def register_client(**overrides) -> dict:
    """POST /clients/register (PRD §3.1). No auth header required."""
    res = api_client.register_client(create_client_payload(**overrides),
                                     _ANON_HEADERS)
    return get_success_data(res)


def sign_retainer(client_id: str) -> dict:
    """POST /clients/{id}/sign-retainer (PRD §3.1)."""
    res = api_client.sign_retainer(client_id, _PARALEGAL_HEADERS)
    return get_success_data(res)


def create_case(client_id: str, **overrides) -> dict:
    """POST /cases (PRD §3.1)."""
    res = api_client.create_case(
        create_case_payload(client_id, **overrides), _PARALEGAL_HEADERS
    )
    return get_success_data(res)


def activate_case(case_id: str) -> dict:
    """POST /cases/{id}/activate (PRD §3.1)."""
    res = api_client.activate_case(case_id, _ATTORNEY_HEADERS)
    return get_success_data(res)


def register_provider(**overrides) -> dict:
    """POST /medical-providers (PRD §3.2)."""
    res = api_client.register_provider(create_provider_payload(**overrides),
                                       _PARALEGAL_HEADERS)
    return get_success_data(res)


def create_records_request(case_id: str, provider_id: str) -> dict:
    """POST /medical-records-requests (PRD §3.2)."""
    res = api_client.create_records_request(
        create_records_request_payload(case_id, provider_id), _PARALEGAL_HEADERS
    )
    return get_success_data(res)


def walk_records_request_to_reviewed(mrr_id: str) -> dict:
    """REQUESTED → RECEIVED → REVIEWED (PRD §3.2)."""
    get_success_data(api_client.receive_records_request(mrr_id, _PARALEGAL_HEADERS))
    res = api_client.review_records_request(mrr_id, _ATTORNEY_HEADERS)
    return get_success_data(res)


def create_proposed_damages(case_id: str, category: str, amount_cents: int) -> dict:
    """POST /damages-items in PROPOSED status (PRD §3.3)."""
    res = api_client.create_damages_item(
        create_damages_item_payload(case_id, category, amount_cents),
        _PARALEGAL_HEADERS,
    )
    return get_success_data(res)


def include_damages(item_id: str) -> dict:
    """POST /damages-items/{id}/include (PRD §3.3)."""
    res = api_client.include_damages_item(item_id, _ATTORNEY_HEADERS)
    return get_success_data(res)


def create_included_damages(case_id: str, category: str, amount_cents: int) -> dict:
    """Create a PROPOSED damages item then immediately INCLUDE it (PRD §3.3)."""
    item = create_proposed_damages(case_id, category, amount_cents)
    return include_damages(item["id"])


def create_demand_letter(case_id: str, pain_multiplier: float = 1.5,
                         drafter_user_id: str = "drafter-1") -> dict:
    """POST /demand-letters (PRD §3.4). Drafter's X-User-ID is pinned so callers
    can later send via a partner with a distinct user_id (segregation of duties)."""
    headers = make_attorney_headers(drafter_user_id)
    res = api_client.create_demand_letter(
        create_demand_letter_payload(case_id, pain_multiplier=pain_multiplier),
        headers,
    )
    return get_success_data(res)


def send_demand_letter(dl_id: str, partner_user_id: str = "partner-1") -> dict:
    """POST /demand-letters/{id}/send (PRD §3.4). Partner's X-User-ID is pinned
    so it differs from the drafter (segregation-of-duties guard)."""
    headers = make_managing_partner_headers(partner_user_id)
    res = api_client.send_demand_letter(dl_id, headers)
    return get_success_data(res)


def create_lien(case_id: str, provider_id: str, asserted_amount_cents: int) -> dict:
    """POST /medical-liens (PRD §3.7)."""
    res = api_client.create_lien(
        create_lien_payload(case_id, provider_id, asserted_amount_cents),
        _PARALEGAL_HEADERS,
    )
    return get_success_data(res)


def negotiate_lien(lien_id: str) -> dict:
    """POST /medical-liens/{id}/negotiate (PRD §3.7)."""
    res = api_client.negotiate_lien(lien_id, _PARALEGAL_HEADERS)
    return get_success_data(res)


def dispute_lien(lien_id: str) -> dict:
    """POST /medical-liens/{id}/dispute (PRD §3.7)."""
    res = api_client.dispute_lien(lien_id, _ATTORNEY_HEADERS)
    return get_success_data(res)


def resume_lien(lien_id: str) -> dict:
    """POST /medical-liens/{id}/resume-negotiation (PRD §3.7)."""
    res = api_client.resume_lien(lien_id, _ATTORNEY_HEADERS)
    return get_success_data(res)


def create_offer(case_id: str, offer_amount_cents: int, by_party: str = "CARRIER",
                 counter_to_offer_id: str = None) -> dict:
    """POST /settlement-offers (PRD §3.5)."""
    res = api_client.create_offer(
        create_offer_payload(case_id, offer_amount_cents, by_party,
                             counter_to_offer_id),
        _ATTORNEY_HEADERS,
    )
    return get_success_data(res)


def get_case_version(case_id: str) -> int:
    """Read Case.version via GET /cases/{id} (PRD §2.4, §2.10)."""
    res = api_client.get_case(case_id, _ATTORNEY_HEADERS)
    case = get_success_data(res)
    return case["version"]


def accept_offer(offer_id: str, expected_case_version: int,
                 partner_user_id: str = "partner-1") -> dict:
    """POST /settlement-offers/{id}/accept (PRD §3.6)."""
    headers = make_managing_partner_headers(partner_user_id)
    res = api_client.accept_offer(
        offer_id, accept_offer_payload(expected_case_version), headers
    )
    return get_success_data(res)


def create_court_event(case_id: str, event_type: str, scheduled_at: str,
                       duration_minutes: int = None) -> dict:
    """POST /court-events (PRD §3.8)."""
    res = api_client.create_court_event(
        create_court_event_payload(case_id, event_type, scheduled_at,
                                    duration_minutes),
        _ATTORNEY_HEADERS,
    )
    return get_success_data(res)


def file_suit(case_id: str) -> dict:
    """POST /cases/{id}/file-suit (PRD §3.8)."""
    res = api_client.file_suit(case_id, _PARTNER_HEADERS)
    return get_success_data(res)


def release_disbursement(disb_id: str, expected_case_version: int) -> dict:
    """POST /disbursements/{id}/release (PRD §3.7)."""
    res = api_client.release_disbursement(
        disb_id, release_disbursement_payload(expected_case_version), _PARTNER_HEADERS
    )
    return get_success_data(res)


def get_case(case_id: str) -> dict:
    """GET /cases/{id} (PRD §3.1)."""
    return get_success_data(api_client.get_case(case_id, _ATTORNEY_HEADERS))


def get_disbursement_for_case(case_id: str) -> dict:
    """Find the (single) Disbursement for a case via GET /disbursements?case_id=..."""
    res = api_client.list_disbursements(_ATTORNEY_HEADERS, params={"case_id": case_id})
    data = get_success_data(res)
    # data is a list (envelope.data for paginated list endpoints).
    assert isinstance(data, list) and len(data) >= 1, (
        f"Expected at least one Disbursement for case {case_id}, got {data!r}"
    )
    return data[0]


# ─── Tier 2: Case-state convenience builders ────────────────────


def setup_client_and_case(jurisdiction: str = "CA",
                          accident_date: str = "2024-06-15",
                          retainer_signed: bool = True,
                          **case_overrides) -> tuple:
    """Register client + (optionally) sign retainer + open case in INTAKE.

    Returns (client, case).
    """
    client = register_client()
    if retainer_signed:
        client = sign_retainer(client["id"])
    case = create_case(
        client["id"], accident_date=accident_date, jurisdiction=jurisdiction,
        **case_overrides,
    )
    return client, case


def setup_active_case(jurisdiction: str = "CA",
                      accident_date: str = "2024-06-15",
                      clock_iso: str = "2026-01-01T00:00:00Z",
                      **case_overrides) -> tuple:
    """Active CA case at the given clock with retainer signed.

    Returns (client, case_active).
    """
    set_clock(clock_iso)
    client, case = setup_client_and_case(jurisdiction=jurisdiction,
                                          accident_date=accident_date,
                                          retainer_signed=True,
                                          **case_overrides)
    case_active = activate_case(case["id"])
    return client, case_active


def setup_active_case_with_reviewed_records(
    jurisdiction: str = "CA",
    accident_date: str = "2024-06-15",
    clock_iso: str = "2026-01-01T00:00:00Z",
    **case_overrides,
) -> tuple:
    """Active case + one REVIEWED MedicalRecordsRequest.

    Returns (client, case, provider, mrr_reviewed).
    """
    client, case = setup_active_case(jurisdiction=jurisdiction,
                                      accident_date=accident_date,
                                      clock_iso=clock_iso,
                                      **case_overrides)
    provider = register_provider()
    mrr = create_records_request(case["id"], provider["id"])
    mrr_reviewed = walk_records_request_to_reviewed(mrr["id"])
    return client, case, provider, mrr_reviewed


# ─── Tier 3: ready-to-settle setups ─────────────────────────────


def setup_case_ready_for_settlement(
    jurisdiction: str = "CA",
    accident_date: str = "2024-06-15",
    clock_iso: str = "2026-01-01T00:00:00Z",
    damages_breakdown: dict = None,
    pain_multiplier: float = 1.5,
    drafter_user_id: str = "drafter-1",
    partner_user_id: str = "partner-1",
) -> tuple:
    """Active case → INCLUDED damages → demand letter SENT (Case in DEMAND_SENT).

    `damages_breakdown` is a dict mapping category → amount_cents. Defaults to
    a single MEDICAL_BILLS=1_000_000 item.

    Returns (client, case_after_send, provider).
    """
    if damages_breakdown is None:
        damages_breakdown = {"MEDICAL_BILLS": 1_000_000}
    client, case, provider, mrr = setup_active_case_with_reviewed_records(
        jurisdiction=jurisdiction,
        accident_date=accident_date,
        clock_iso=clock_iso,
    )
    for category, amount in damages_breakdown.items():
        create_included_damages(case["id"], category, amount)
    dl = create_demand_letter(case["id"], pain_multiplier=pain_multiplier,
                               drafter_user_id=drafter_user_id)
    send_demand_letter(dl["id"], partner_user_id=partner_user_id)
    return client, get_case(case["id"]), provider


def setup_case_in_negotiation_with_offer(
    jurisdiction: str = "CA",
    accident_date: str = "2024-06-15",
    clock_iso: str = "2026-01-01T00:00:00Z",
    damages_breakdown: dict = None,
    offer_amount_cents: int = 4_000_000,
    by_party: str = "CARRIER",
    pain_multiplier: float = 1.5,
    drafter_user_id: str = "drafter-1",
    partner_user_id: str = "partner-1",
) -> tuple:
    """Active case → demand sent → first CARRIER offer (Case in IN_NEGOTIATION).

    Returns (client, case_in_negotiation, provider, offer_pending).
    """
    client, case_after_send, provider = setup_case_ready_for_settlement(
        jurisdiction=jurisdiction,
        accident_date=accident_date,
        clock_iso=clock_iso,
        damages_breakdown=damages_breakdown,
        pain_multiplier=pain_multiplier,
        drafter_user_id=drafter_user_id,
        partner_user_id=partner_user_id,
    )
    offer = create_offer(case_after_send["id"], offer_amount_cents, by_party)
    return client, get_case(case_after_send["id"]), provider, offer


def settle_case_with_lien(
    jurisdiction: str = "CA",
    accident_date: str = "2024-06-15",
    clock_iso: str = "2026-01-01T00:00:00Z",
    damages_breakdown: dict = None,
    offer_amount_cents: int = 6_000_000,
    lien_asserted_cents: int = 1_500_000,
    partner_user_id: str = "partner-1",
) -> tuple:
    """Full pre-suit settle: active case → demand sent → lien asserted → offer accepted.

    Returns (client, case_settled, provider, lien_agreed, offer_accepted, disbursement).
    """
    if damages_breakdown is None:
        damages_breakdown = {"MEDICAL_BILLS": 1_000_000}
    client, case_after_send, provider = setup_case_ready_for_settlement(
        jurisdiction=jurisdiction,
        accident_date=accident_date,
        clock_iso=clock_iso,
        damages_breakdown=damages_breakdown,
    )
    # Assert a lien BEFORE the offer so the SETTLED cascade includes it.
    lien = create_lien(case_after_send["id"], provider["id"], lien_asserted_cents)
    offer = create_offer(case_after_send["id"], offer_amount_cents, "CARRIER")
    case_v = get_case_version(case_after_send["id"])
    offer_accepted = accept_offer(offer["id"], case_v, partner_user_id=partner_user_id)
    case_settled = get_case(case_after_send["id"])
    disb = get_disbursement_for_case(case_settled["id"])
    # Re-read the lien to get its post-cascade state.
    lien_after = get_success_data(api_client.get_lien(lien["id"], _ATTORNEY_HEADERS))
    return client, case_settled, provider, lien_after, offer_accepted, disb


def setup_settled_case_with_paid_liens(
    jurisdiction: str = "CA",
    accident_date: str = "2024-06-15",
    clock_iso: str = "2026-01-01T00:00:00Z",
    offer_amount_cents: int = 6_000_000,
    lien_asserted_cents: int = 500_000,
    damages_breakdown: dict = None,
) -> tuple:
    """Full lifecycle to RELEASED disbursement + PAID lien (case still SETTLED,
    not yet CLOSED).

    Returns (client, case_settled, disbursement_released, lien_paid).
    """
    client, case_settled, provider, lien, offer, disb = settle_case_with_lien(
        jurisdiction=jurisdiction,
        accident_date=accident_date,
        clock_iso=clock_iso,
        damages_breakdown=damages_breakdown,
        offer_amount_cents=offer_amount_cents,
        lien_asserted_cents=lien_asserted_cents,
    )
    case_v = get_case_version(case_settled["id"])
    release_disbursement(disb["id"], case_v)
    disb_after = get_success_data(api_client.get_disbursement(disb["id"], _ATTORNEY_HEADERS))
    lien_after = get_success_data(api_client.get_lien(lien["id"], _ATTORNEY_HEADERS))
    return client, get_case(case_settled["id"]), disb_after, lien_after
