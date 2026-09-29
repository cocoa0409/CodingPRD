"""Composite scenario builders.

Each test starts against an empty database, except for the singleton risk policy
which "is seeded at process start with all of the defaults below, so reading it
succeeds against an empty database".  Every builder therefore reaches its target
state exclusively through endpoints the PRD declares, and returns the parsed
resource so a test can read ids and versions from it.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import GiftCardApiClient
from .constants import CLOCK_ORIGIN
from .test_users import (
    make_fraud_analyst_headers,
    make_liability_accountant_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_reseller_partner_headers,
    make_risk_manager_headers,
    make_store_manager_headers,
)

_ISO = "%Y-%m-%dT%H:%M:%SZ"


# ----------------------------------------------------------------------
# Logical-clock arithmetic
# ----------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional digits."""
    text = value.replace("Z", "")
    if "." in text:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f")
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")


def format_instant(moment: datetime) -> str:
    """Render an instant in the whole-second ISO 8601 UTC form the API accepts."""
    return moment.strftime(_ISO)


def shift(base: str = CLOCK_ORIGIN, minutes: int = 0, hours: int = 0, days: int = 0) -> str:
    """An instant offset from a base instant, for hold intervals and windows."""
    return format_instant(
        parse_instant(base) + timedelta(minutes=minutes, hours=hours, days=days)
    )


# ----------------------------------------------------------------------
# Tier 1 — policy, clock, stores, racks
# ----------------------------------------------------------------------
def read_policy(client: GiftCardApiClient, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read the always-present singleton risk-policy row."""
    return validate_success(client.get_risk_policy(headers or make_platform_admin_headers()))


def set_policy(client: GiftCardApiClient, **settings: Any) -> Dict[str, Any]:
    """Partially update the risk policy; omitted keys "retain their current values"."""
    response = client.update_risk_policy(f.risk_policy_update(**settings), make_platform_admin_headers())
    return validate_success(response)


def advance_clock(client: GiftCardApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock, sweeping newly expired holds."""
    response = client.set_clock(f.clock_setting(to_iso8601), make_platform_admin_headers())
    return validate_success(response)


def create_store(client: GiftCardApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a retail store, born "with a floor_posture of OPEN"."""
    response = client.create_store(f.store_payload(**overrides), make_platform_admin_headers())
    return get_success_data(response)


def read_store(client: GiftCardApiClient, store_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read one store with its derived counters."""
    return validate_success(client.get_store(store_id, headers or make_platform_admin_headers()))


def create_rack(client: GiftCardApiClient, store_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register a rack, which is born INTACT with no audit yet."""
    response = client.create_card_rack(
        f.card_rack_payload(store_id, **overrides), make_platform_admin_headers()
    )
    return get_success_data(response)


def read_rack(client: GiftCardApiClient, rack_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read one rack with its latest audit numbers."""
    return validate_success(client.get_card_rack(rack_id, headers or make_platform_admin_headers()))


def audit_rack(
    client: GiftCardApiClient,
    rack_id: str,
    observed_card_count: int,
    seal_breaks_observed: int = 0,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Record a rack audit, re-deriving the rack's tamper classification."""
    response = client.audit_card_rack(
        rack_id,
        f.rack_audit_payload(observed_card_count, seal_breaks_observed),
        headers or make_pos_associate_headers(),
    )
    return validate_success(response)


def suspend_store_floor(client: GiftCardApiClient, store_id: str) -> Dict[str, Any]:
    """Drive a store to SUSPENDED through the rack-tamper cascade: a rack audited at or
    above the seal-break threshold is TAMPERED, and "if tampered_rack_count is at least
    1 the floor is SUSPENDED"."""
    rack = create_rack(client, store_id, expected_card_count=5)
    audit_rack(client, rack["id"], observed_card_count=5, seal_breaks_observed=3)
    return read_store(client, store_id)


def heighten_store_floor(client: GiftCardApiClient, store_id: str) -> Dict[str, Any]:
    """Drive a store to HEIGHTENED with a single SUSPECT rack: "if suspect_rack_count is
    at least 1 ... the floor is HEIGHTENED"."""
    rack = create_rack(client, store_id, expected_card_count=5)
    audit_rack(client, rack["id"], observed_card_count=5, seal_breaks_observed=1)
    return read_store(client, store_id)


# ----------------------------------------------------------------------
# Tier 2 — stocked and funded gift cards
# ----------------------------------------------------------------------
def stock_card(
    client: GiftCardApiClient, store_id: str, rack_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Stock a physical card, "created inactive with a zero balance"."""
    response = client.create_gift_card(
        f.gift_card_payload(store_id, rack_id, **overrides), make_pos_associate_headers()
    )
    return get_success_data(response)


def read_card(client: GiftCardApiClient, card_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read one card with its re-derived projection and both state dimensions."""
    return validate_success(client.get_gift_card(card_id, headers or make_platform_admin_headers()))


def open_physical_issuance(
    client: GiftCardApiClient,
    store_id: str,
    rack_id: str,
    card_id: str,
    face_value_cents: int = 5000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a PHYSICAL issuance request, created in state SUBMITTED."""
    response = client.create_issuance_request(
        f.physical_issuance_payload(store_id, rack_id, card_id, face_value_cents, **overrides),
        make_pos_associate_headers(),
    )
    return get_success_data(response)


def open_digital_issuance(
    client: GiftCardApiClient, face_value_cents: int = 5000, **overrides: Any
) -> Dict[str, Any]:
    """Open a DIGITAL issuance request, created in state SUBMITTED."""
    response = client.create_issuance_request(
        f.digital_issuance_payload(face_value_cents, **overrides), make_pos_associate_headers()
    )
    return get_success_data(response)


def screen_issuance(
    client: GiftCardApiClient, request_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Screen a submitted request, forking on floor posture or on the score bands."""
    return validate_success(
        client.screen_issuance_request(request_id, headers or make_pos_associate_headers())
    )


def decide_issuance(
    client: GiftCardApiClient,
    request_id: str,
    decision: str = "APPROVE",
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Manually resolve a held request through the same terminals as the automatic fork."""
    return validate_success(
        client.decide_issuance_request(
            request_id,
            f.issuance_decision_payload(decision, **overrides),
            headers or make_risk_manager_headers(),
        )
    )


def funded_physical_card(
    client: GiftCardApiClient,
    face_value_cents: int = 10000,
    store: Optional[Dict[str, Any]] = None,
    rack: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A store, an INTACT rack, a stocked card and a screened PHYSICAL issuance: an OPEN
    floor "drives the request straight to APPROVED", which activates the card and appends
    its ACTIVATION_LOAD.

    Returns a dict with the ``store``, ``rack``, ``request`` and the re-read ``card``.
    """
    store = store or create_store(client)
    rack = rack or create_rack(client, store["id"])
    card = stock_card(client, store["id"], rack["id"])
    request = open_physical_issuance(client, store["id"], rack["id"], card["id"], face_value_cents)
    request = screen_issuance(client, request["id"])
    return {
        "store": store,
        "rack": rack,
        "request": request,
        "card": read_card(client, card["id"]),
    }


def funded_digital_card(
    client: GiftCardApiClient, face_value_cents: int = 10000
) -> Dict[str, Any]:
    """A DIGITAL request whose signals score below the hold threshold reaches APPROVED,
    where "the server first mints a brand-new card with channel DIGITAL, no store, no
    rack".

    Returns a dict with the ``request`` and the minted ``card``.
    """
    request = open_digital_issuance(
        client,
        face_value_cents=face_value_cents,
        device_reputation_score=95,
        email_age_days=900,
        payment_risk_band="LOW",
    )
    request = screen_issuance(client, request["id"])
    return {"request": request, "card": read_card(client, request["card_id"])}


# ----------------------------------------------------------------------
# Tier 3 — ledger movement, holds and inquiries
# ----------------------------------------------------------------------
def redeem(
    client: GiftCardApiClient,
    card_id: str,
    amount_cents: int,
    merchant_store_id: str,
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Append a REDEMPTION event at the register."""
    response = client.create_redemption(
        card_id,
        f.redemption_payload(amount_cents, merchant_store_id, **overrides),
        headers or make_pos_associate_headers(),
    )
    return get_success_data(response)


def reverse(
    client: GiftCardApiClient, event_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Append the compensating REDEMPTION_REVERSAL, leaving the original untouched."""
    response = client.reverse_ledger_event(
        event_id, f.reversal_payload(**overrides), headers or make_risk_manager_headers()
    )
    return get_success_data(response)


def place_hold(
    client: GiftCardApiClient,
    card_id: str,
    amount_cents: int,
    hold_start: str,
    hold_expires_at: str,
    expected_gift_card_version: int,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Reserve part of a card's balance, guarded by the card's expected version."""
    response = client.create_redemption_hold(
        card_id,
        f.redemption_hold_payload(
            amount_cents, hold_start, hold_expires_at, expected_gift_card_version
        ),
        headers or make_pos_associate_headers(),
    )
    return get_success_data(response)


def hold_on_card(
    client: GiftCardApiClient,
    card_id: str,
    amount_cents: int,
    minutes: int = 360,
    base: str = CLOCK_ORIGIN,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Place a hold spanning ``minutes`` from ``base``, reading the card's current
    version first so the stale-version guard passes."""
    card = read_card(client, card_id)
    return place_hold(
        client,
        card_id,
        amount_cents,
        base,
        shift(base, minutes=minutes),
        card["version"],
        headers=headers,
    )


def settle_hold(
    client: GiftCardApiClient,
    hold_id: str,
    disposition: str = "RELEASE",
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Settle an ACTIVE hold, releasing the reservation or capturing it."""
    return validate_success(
        client.settle_redemption_hold(
            hold_id,
            f.hold_settlement_payload(disposition, **overrides),
            headers or make_pos_associate_headers(),
        )
    )


def inquire(
    client: GiftCardApiClient,
    card_id: str,
    channel: str = "POS",
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record a balance inquiry, which recomputes velocity and may raise an alert."""
    response = client.create_balance_inquiry(
        card_id,
        f.balance_inquiry_payload(channel, **overrides),
        headers or make_pos_associate_headers(),
    )
    return get_success_data(response)


def inquire_times(
    client: GiftCardApiClient, card_id: str, count: int, channel: str = "POS"
) -> List[Dict[str, Any]]:
    """Record ``count`` inquiries in sequence; velocity "is evaluated after the new row
    has been appended, so the triggering inquiry counts itself"."""
    return [inquire(client, card_id, channel) for _ in range(count)]


def override_posture(
    client: GiftCardApiClient, card_id: str, risk_posture: str, **overrides: Any
) -> Dict[str, Any]:
    """Set a card's posture "to exactly that value, upward or downward"."""
    return validate_success(
        client.override_card_posture(
            card_id, f.posture_override_payload(risk_posture, **overrides), make_risk_manager_headers()
        )
    )


# ----------------------------------------------------------------------
# Tier 4 — bulk orders
# ----------------------------------------------------------------------
def open_bulk_order(
    client: GiftCardApiClient,
    store_id: str,
    card_quantity: int = 1,
    face_value_cents_each: int = 2000,
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a bulk order, whose "initial state falls straight out of the total"."""
    response = client.create_bulk_purchase_order(
        f.bulk_order_payload(store_id, card_quantity, face_value_cents_each, **overrides),
        headers or make_pos_associate_headers(),
    )
    return get_success_data(response)


def capture_identity(
    client: GiftCardApiClient, order_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Capture the government identity a large bulk purchase requires."""
    return validate_success(
        client.verify_bulk_order_identity(
            order_id, f.identity_payload(**overrides), headers or make_pos_associate_headers()
        )
    )


def decide_bulk_order(
    client: GiftCardApiClient,
    order_id: str,
    decision: str = "APPROVE",
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Approve, decline or bounce a bulk order back for more information."""
    return validate_success(
        client.decide_bulk_purchase_order(
            order_id,
            f.bulk_decision_payload(decision, **overrides),
            headers or make_risk_manager_headers(),
        )
    )


def identity_verified_bulk_order(
    client: GiftCardApiClient,
    store_id: str,
    card_quantity: int = 20,
    face_value_cents_each: int = 5000,
) -> Dict[str, Any]:
    """A bulk order above the identity threshold, carried through identity capture to
    IDENTITY_VERIFIED."""
    order = open_bulk_order(client, store_id, card_quantity, face_value_cents_each)
    if order["state"] == "PENDING_IDENTITY":
        order = capture_identity(client, order["id"])
    return order


# ----------------------------------------------------------------------
# Tier 4 — draining alerts and referrals
# ----------------------------------------------------------------------
def open_alert(
    client: GiftCardApiClient,
    card_id: str,
    detection_basis: str = "MANUAL_REVIEW",
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Raise an alert manually; "A manually raised alert starts in OPEN"."""
    response = client.create_draining_alert(
        f.draining_alert_payload(card_id, detection_basis, **overrides),
        headers or make_fraud_analyst_headers(),
    )
    return get_success_data(response)


def read_alert(client: GiftCardApiClient, alert_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read one alert with its frozen exposure snapshot."""
    return validate_success(client.get_draining_alert(alert_id, headers or make_platform_admin_headers()))


def triage_alert(
    client: GiftCardApiClient, alert_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Triage an OPEN alert, recomputing the card's redemption-weighted drain score."""
    return validate_success(
        client.triage_draining_alert(
            alert_id, f.triage_payload(**overrides), headers or make_fraud_analyst_headers()
        )
    )


def resolve_alert(
    client: GiftCardApiClient,
    alert_id: str,
    resolution: str = "CONFIRM",
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Resolve a TRIAGED alert; the resolving caller must differ from the triager."""
    return validate_success(
        client.resolve_draining_alert(
            alert_id,
            f.resolution_payload(resolution, **overrides),
            headers or make_risk_manager_headers(),
        )
    )


def reopen_alert(
    client: GiftCardApiClient, alert_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Reopen a DISMISSED alert; triaged_by_user_id "is preserved across the reopen"."""
    return validate_success(
        client.reopen_draining_alert(
            alert_id, f.reopen_payload(**overrides), headers or make_risk_manager_headers()
        )
    )


def triaged_alert(
    client: GiftCardApiClient,
    card_id: str,
    detection_basis: str = "MANUAL_REVIEW",
    triager: Optional[Dict] = None,
) -> Dict[str, Any]:
    """An alert carried from OPEN to TRIAGED by a FraudAnalyst."""
    alert = open_alert(client, card_id, detection_basis)
    return triage_alert(client, alert["id"], headers=triager)


def confirmed_alert(
    client: GiftCardApiClient,
    card_id: str,
    detection_basis: str = "MANUAL_REVIEW",
    triager: Optional[Dict] = None,
    resolver: Optional[Dict] = None,
) -> Dict[str, Any]:
    """An alert carried to CONFIRMED, which freezes the card and blocks its VALIDATED
    listings.  Distinct triage and resolve identities keep segregation of duties clear."""
    alert = triaged_alert(
        client, card_id, detection_basis, triager or make_fraud_analyst_headers("analyst-triager")
    )
    return resolve_alert(
        client, alert["id"], "CONFIRM", headers=resolver or make_risk_manager_headers("risk-resolver")
    )


def file_referral(
    client: GiftCardApiClient, alert_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """File an immutable law-enforcement packet against a CONFIRMED alert."""
    response = client.create_law_enforcement_referral(
        f.referral_payload(alert_id, **overrides), headers or make_risk_manager_headers()
    )
    return get_success_data(response)


# ----------------------------------------------------------------------
# Tier 4 — reseller listings
# ----------------------------------------------------------------------
def submit_listing(
    client: GiftCardApiClient,
    card_id: str,
    listed_balance_cents: int,
    marketplace_name: str = "GiftBay",
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Submit a listing, "created in state SUBMITTED ... with block_reason empty"."""
    response = client.create_reseller_listing(
        f.reseller_listing_payload(
            card_id, listed_balance_cents, marketplace_name, **overrides
        ),
        headers or make_reseller_partner_headers(),
    )
    return get_success_data(response)


def validate_listing(
    client: GiftCardApiClient, listing_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Validate a SUBMITTED listing against the live card under the fixed check order."""
    return validate_success(
        client.validate_reseller_listing(
            listing_id,
            f.listing_validation_payload(**overrides),
            headers or make_fraud_analyst_headers(),
        )
    )


def validated_listing(
    client: GiftCardApiClient,
    card_id: str,
    listed_balance_cents: int,
    marketplace_name: str = "GiftBay",
) -> Dict[str, Any]:
    """A listing quoting the card's exact balance on a CLEAR, ACTIVE card reaches
    VALIDATED — the one non-terminal verdict the freeze cascade can later block."""
    listing = submit_listing(client, card_id, listed_balance_cents, marketplace_name)
    return validate_listing(client, listing["id"])


# ----------------------------------------------------------------------
# Tier 4 — victim claims
# ----------------------------------------------------------------------
def file_claim(
    client: GiftCardApiClient,
    card_id: str,
    disputed_amount_cents: int = 1000,
    purchased_at: str = CLOCK_ORIGIN,
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Intake a claim, created "in state SUBMITTED with evidence_round at 0"."""
    response = client.create_victim_claim(
        f.victim_claim_payload(card_id, disputed_amount_cents, purchased_at, **overrides),
        headers or make_pos_associate_headers(),
    )
    return get_success_data(response)


def read_claim(client: GiftCardApiClient, claim_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read one claim with its evidence-round counter and frozen reissue arithmetic."""
    return validate_success(client.get_victim_claim(claim_id, headers or make_platform_admin_headers()))


def request_evidence(
    client: GiftCardApiClient,
    claim_id: str,
    missing_evidence_kinds: Optional[List[str]] = None,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Bounce a SUBMITTED claim back, incrementing evidence_round by 1."""
    return validate_success(
        client.request_claim_evidence(
            claim_id,
            f.evidence_request_payload(missing_evidence_kinds),
            headers or make_fraud_analyst_headers(),
        )
    )


def resubmit_evidence(
    client: GiftCardApiClient, claim_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Return a claim to review; "only the references actually supplied are overwritten"."""
    return validate_success(
        client.resubmit_claim_evidence(
            claim_id,
            f.evidence_resubmit_payload(**overrides),
            headers or make_fraud_analyst_headers(),
        )
    )


def decide_claim(
    client: GiftCardApiClient,
    claim_id: str,
    decision: str = "APPROVE",
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Decide a SUBMITTED claim; the decider must differ from the claim's intake user."""
    return validate_success(
        client.decide_victim_claim(
            claim_id,
            f.claim_decision_payload(decision, **overrides),
            headers or make_risk_manager_headers(),
        )
    )


def rescind_claim(
    client: GiftCardApiClient, claim_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Compensate an APPROVED claim, unwinding every hop of the reissue cascade."""
    return validate_success(
        client.rescind_victim_claim(
            claim_id, f.rescind_payload(**overrides), headers or make_risk_manager_headers()
        )
    )


def approvable_claim(
    client: GiftCardApiClient,
    card_id: str,
    disputed_amount_cents: int,
    purchased_at: str = CLOCK_ORIGIN,
    channel: str = "PHYSICAL",
    intake: Optional[Dict] = None,
) -> Dict[str, Any]:
    """A claim carrying the evidence its card's channel requires: "A receipt reference is
    mandatory for every claim; a packaging photo reference is additionally mandatory when
    the referenced card's channel is PHYSICAL"."""
    evidence: Dict[str, Any] = {"purchase_receipt_ref": f"RCPT-{f.next_seq()}"}
    if channel == "PHYSICAL":
        evidence["packaging_photo_ref"] = f"PHOTO-{f.next_seq()}"
    return file_claim(
        client,
        card_id,
        disputed_amount_cents,
        purchased_at,
        headers=intake or make_pos_associate_headers("pos-intake"),
        **evidence,
    )


# ----------------------------------------------------------------------
# Tier 5 — liability periods
# ----------------------------------------------------------------------
def open_period(
    client: GiftCardApiClient,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a period over a half-open span, created "in OPEN with
    unauthorized_writeoff_cents at 0"."""
    response = client.create_liability_period(
        f.liability_period_payload(period_start, period_end, **overrides),
        make_liability_accountant_headers(),
    )
    return get_success_data(response)


def read_period(client: GiftCardApiClient, period_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read one period with both reserve numbers side by side."""
    return validate_success(
        client.get_liability_period(period_id, headers or make_liability_accountant_headers())
    )


def close_period(
    client: GiftCardApiClient, period_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Close a period, booking the provisional reserve on the prudent alert basis."""
    return validate_success(
        client.close_liability_period(
            period_id, f.period_close_payload(**overrides), headers or make_liability_accountant_headers()
        )
    )


def restate_period(
    client: GiftCardApiClient,
    period_id: str,
    expected_version: int,
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Restate a period under its stale-version guard, booking the final reserve."""
    return validate_success(
        client.restate_liability_period(
            period_id,
            f.period_restate_payload(expected_version, **overrides),
            headers or make_liability_accountant_headers(),
        )
    )


def read_exposure_summary(
    client: GiftCardApiClient, period_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """The computed read that "stores nothing and increments no version"."""
    return validate_success(
        client.get_exposure_summary(period_id, headers or make_liability_accountant_headers())
    )


def closed_period(
    client: GiftCardApiClient,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-09-01T00:00:00Z",
) -> Dict[str, Any]:
    """A period carried from OPEN to CLOSED, with the provisional reserve booked."""
    period = open_period(client, period_start, period_end)
    return close_period(client, period["id"])


# ----------------------------------------------------------------------
# Listing / collection readers
# ----------------------------------------------------------------------
def list_data_and_meta(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return the rows and the pagination meta of a list response."""
    body = response.json()
    assert response.status_code == 200, f"expected 200, got {response.status_code}: {body}"
    return body["data"], body["meta"]


def total_count(response) -> int:
    """The meta ``total_count`` is "the number of records matching the filters before the
    window is applied"."""
    rows, meta = list_data_and_meta(response)
    return meta["total_count"]


def store_manager_headers_for(store: Dict[str, Any]) -> Dict[str, str]:
    """"When X-User-Role is StoreManager, X-User-ID is the id of the acting RetailStore"."""
    return make_store_manager_headers(store["id"])
