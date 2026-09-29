"""Request-payload builders for every write endpoint.

Each builder emits only the fields the PRD declares as inputs for that
endpoint.  Derived fields are never supplied: "No endpoint accepts a derived
field as input, and an attempt to supply one is simply ignored rather than
honoured."  Callers override any field with a keyword argument and delete a
field by passing ``None`` through ``omit``.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CLOCK_ORIGIN,
    ROLE_PLATFORM_ADMIN,
)

_COUNTER = {"n": 0}


def next_seq() -> int:
    """Monotonic in-process counter for unique labels within one test."""
    _COUNTER["n"] += 1
    return _COUNTER["n"]


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply keyword overrides; a value of ``omit`` removes the key entirely."""
    for key, value in overrides.items():
        if value is omit:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel meaning "leave this field out of the request body entirely"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<omit>"


omit = _Omit()


# ----------------------------------------------------------------------
# Risk policy and clock
# ----------------------------------------------------------------------
def risk_policy_update(**overrides: Any) -> Dict[str, Any]:
    """Partial policy update: "only the keys supplied on the update are overwritten"."""
    return _merge({}, overrides)


def clock_setting(to_iso8601: str = CLOCK_ORIGIN, **overrides: Any) -> Dict[str, Any]:
    """Clock advance body: "A PlatformAdmin moves the clock by supplying a to_iso8601 instant"."""
    return _merge({"to_iso8601": to_iso8601}, overrides)


# ----------------------------------------------------------------------
# Retail stores and racks
# ----------------------------------------------------------------------
def store_payload(**overrides: Any) -> Dict[str, Any]:
    """A store carries "a name of 1 to 120 characters, a region_code of exactly two
    uppercase letters ... and an address_line of 1 to 200 characters"."""
    seq = next_seq()
    return _merge(
        {
            "name": f"Store {seq}",
            "region_code": "NE",
            "address_line": f"{seq} Market Street",
        },
        overrides,
    )


def card_rack_payload(store_id: str, **overrides: Any) -> Dict[str, Any]:
    """A rack carries a "rack_label of 1 to 40 characters that must be unique within
    that store, and carrying an expected_card_count between 0 and 500 inclusive"."""
    return _merge(
        {
            "store_id": store_id,
            "rack_label": f"RACK-{next_seq()}",
            "expected_card_count": 10,
        },
        overrides,
    )


def rack_audit_payload(
    observed_card_count: int = 10, seal_breaks_observed: int = 0, **overrides: Any
) -> Dict[str, Any]:
    """An audit reports "the observed_card_count physically counted in the fixture and
    the seal_breaks_observed"."""
    return _merge(
        {
            "observed_card_count": observed_card_count,
            "seal_breaks_observed": seal_breaks_observed,
        },
        overrides,
    )


def clear_tamper_payload(**overrides: Any) -> Dict[str, Any]:
    """Remediation "records a remediation_note"."""
    return _merge({"remediation_note": "Fixture replaced and re-sealed"}, overrides)


# ----------------------------------------------------------------------
# Gift cards
# ----------------------------------------------------------------------
def gift_card_payload(store_id: str, rack_id: str, **overrides: Any) -> Dict[str, Any]:
    """Stocking a physical card names "the store_id that stocked it and the rack_id it
    sits on"; card_number_masked is optional and server-generated when omitted."""
    return _merge({"store_id": store_id, "rack_id": rack_id}, overrides)


def masked_pan(last_four: str = "4242") -> str:
    """"four asterisks, a hyphen, four asterisks, a hyphen, four asterisks, a hyphen
    and then exactly four digits"."""
    return f"****-****-****-{last_four}"


def balance_inquiry_payload(channel: str = "POS", **overrides: Any) -> Dict[str, Any]:
    """An inquiry supplies "the channel it arrived on ... together with
    requester_ip_hash ... 1 to 128 characters long"."""
    return _merge(
        {"channel": channel, "requester_ip_hash": f"iphash-{next_seq()}"}, overrides
    )


def redemption_payload(
    amount_cents: int, merchant_store_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A redemption supplies "amount_cents, the merchant_store_id where the sale
    happened, and optionally pos_terminal_id and memo"."""
    return _merge(
        {"amount_cents": amount_cents, "merchant_store_id": merchant_store_id}, overrides
    )


def redemption_hold_payload(
    amount_cents: int,
    hold_start: str,
    hold_expires_at: str,
    expected_gift_card_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """A hold supplies "the amount_cents to reserve, the hold_start ..., the
    hold_expires_at ..., and the expected_gift_card_version"."""
    return _merge(
        {
            "amount_cents": amount_cents,
            "hold_start": hold_start,
            "hold_expires_at": hold_expires_at,
            "expected_gift_card_version": expected_gift_card_version,
        },
        overrides,
    )


def hold_settlement_payload(disposition: str = "RELEASE", **overrides: Any) -> Dict[str, Any]:
    """Settlement supplies "a disposition of either RELEASE or CAPTURE, an optional
    settle_note, and an optional merchant_store_id"."""
    return _merge({"disposition": disposition}, overrides)


def posture_override_payload(risk_posture: str, **overrides: Any) -> Dict[str, Any]:
    """An override supplies "the desired risk_posture ... together with a reason"."""
    return _merge(
        {"risk_posture": risk_posture, "reason": "Manual review outcome"}, overrides
    )


# ----------------------------------------------------------------------
# Issuance requests
# ----------------------------------------------------------------------
def physical_issuance_payload(
    store_id: str,
    rack_id: str,
    card_id: str,
    face_value_cents: int = 5000,
    **overrides: Any,
) -> Dict[str, Any]:
    """"A PHYSICAL request additionally requires store_id, rack_id, card_id ...,
    pos_terminal_id ..., and packaging_seal_intact"."""
    return _merge(
        {
            "channel": "PHYSICAL",
            "store_id": store_id,
            "rack_id": rack_id,
            "card_id": card_id,
            "pos_terminal_id": f"POS-{next_seq()}",
            "packaging_seal_intact": True,
            "face_value_cents": face_value_cents,
        },
        overrides,
    )


def digital_issuance_payload(
    face_value_cents: int = 5000,
    device_reputation_score: int = 90,
    email_age_days: int = 400,
    payment_risk_band: str = "LOW",
    **overrides: Any,
) -> Dict[str, Any]:
    """"A DIGITAL request must omit store_id, rack_id and card_id entirely ... and must
    instead supply device_reputation_score ...; email_age_days ...; payment_risk_band
    ...; and recipient_email_hash"."""
    return _merge(
        {
            "channel": "DIGITAL",
            "face_value_cents": face_value_cents,
            "device_reputation_score": device_reputation_score,
            "email_age_days": email_age_days,
            "payment_risk_band": payment_risk_band,
            "recipient_email_hash": f"emailhash-{next_seq()}",
        },
        overrides,
    )


def issuance_decision_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    """A held request is resolved by supplying "a decision of either APPROVE or DECLINE
    and an optional review_note"."""
    return _merge({"decision": decision}, overrides)


# ----------------------------------------------------------------------
# Ledger
# ----------------------------------------------------------------------
def reversal_payload(**overrides: Any) -> Dict[str, Any]:
    """Reversal "names the event to unwind and supplies a reversal_reason"."""
    return _merge({"reversal_reason": "Unauthorized redemption"}, overrides)


# ----------------------------------------------------------------------
# Bulk purchase orders
# ----------------------------------------------------------------------
def bulk_order_payload(
    store_id: str,
    card_quantity: int = 1,
    face_value_cents_each: int = 2000,
    **overrides: Any,
) -> Dict[str, Any]:
    """A bulk order states "the card_quantity requested, the face_value_cents_each ...,
    the purchaser_name ..., and the payment_method being tendered"."""
    return _merge(
        {
            "store_id": store_id,
            "card_quantity": card_quantity,
            "face_value_cents_each": face_value_cents_each,
            "purchaser_name": f"Purchaser {next_seq()}",
            "payment_method": "CASH",
        },
        overrides,
    )


def identity_payload(**overrides: Any) -> Dict[str, Any]:
    """Identity capture supplies "id_type, id_number_hash and id_expiry_date"."""
    return _merge(
        {
            "id_type": "DRIVERS_LICENSE",
            "id_number_hash": f"idhash-{next_seq()}",
            "id_expiry_date": "2030-01-01",
        },
        overrides,
    )


def bulk_decision_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    """A decision supplies "a decision of APPROVE, DECLINE or REQUEST_INFO, plus an
    optional decision_note"."""
    return _merge({"decision": decision}, overrides)


# ----------------------------------------------------------------------
# Draining alerts and referrals
# ----------------------------------------------------------------------
def draining_alert_payload(
    card_id: str, detection_basis: str = "MANUAL_REVIEW", **overrides: Any
) -> Dict[str, Any]:
    """A manual alert names "a card_id, stating the detection_basis ... and optionally
    a note explaining why"."""
    return _merge({"card_id": card_id, "detection_basis": detection_basis}, overrides)


def triage_payload(redemption_pattern_reviewed: bool = True, **overrides: Any) -> Dict[str, Any]:
    """Triage supplies "a triage_note and redemption_pattern_reviewed"."""
    return _merge(
        {
            "triage_note": "Redemption pattern inspected",
            "redemption_pattern_reviewed": redemption_pattern_reviewed,
        },
        overrides,
    )


def resolution_payload(resolution: str = "CONFIRM", **overrides: Any) -> Dict[str, Any]:
    """Resolution requires "a resolution of either CONFIRM or DISMISS together with a
    mandatory resolution_note"."""
    return _merge(
        {"resolution": resolution, "resolution_note": "Investigation complete"}, overrides
    )


def reopen_payload(**overrides: Any) -> Dict[str, Any]:
    """A reopen supplies "a reopen_reason"."""
    return _merge({"reopen_reason": "New evidence arrived"}, overrides)


def referral_payload(alert_id: str, **overrides: Any) -> Dict[str, Any]:
    """A referral names "the alert_id, the receiving agency_name ..., a packet_summary
    narrative of 1 to 2000 characters ..., and optionally a case_reference"."""
    return _merge(
        {
            "alert_id": alert_id,
            "agency_name": "State Retail Crime Unit",
            "packet_summary": "Card-draining packet with inquiry and redemption trail.",
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Victim claims
# ----------------------------------------------------------------------
def victim_claim_payload(
    card_id: str,
    disputed_amount_cents: int = 1000,
    purchased_at: str = CLOCK_ORIGIN,
    **overrides: Any,
) -> Dict[str, Any]:
    """Intake names "the drained card_id, the claimant_name ..., a claimant_contact
    ..., the disputed_amount_cents ..., and purchased_at"."""
    return _merge(
        {
            "card_id": card_id,
            "claimant_name": f"Claimant {next_seq()}",
            "claimant_contact": "claimant@example.com",
            "disputed_amount_cents": disputed_amount_cents,
            "purchased_at": purchased_at,
        },
        overrides,
    )


def evidence_request_payload(
    missing_evidence_kinds: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """An evidence request supplies "missing_evidence_kinds"."""
    kinds = ["PURCHASE_RECEIPT"] if missing_evidence_kinds is None else missing_evidence_kinds
    return _merge({"missing_evidence_kinds": kinds}, overrides)


def evidence_resubmit_payload(**overrides: Any) -> Dict[str, Any]:
    """A resubmission supplies "either or both of purchase_receipt_ref and
    packaging_photo_ref"."""
    return _merge({"purchase_receipt_ref": f"RCPT-{next_seq()}"}, overrides)


def claim_decision_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    """A decision takes "a decision of either APPROVE or DENY plus an optional
    decision_note"."""
    return _merge({"decision": decision}, overrides)


def rescind_payload(**overrides: Any) -> Dict[str, Any]:
    """A rescission carries "a mandatory rescind_reason"."""
    return _merge({"rescind_reason": "Claim was fraudulent"}, overrides)


# ----------------------------------------------------------------------
# Reseller listings
# ----------------------------------------------------------------------
def reseller_listing_payload(
    card_id: str,
    listed_balance_cents: int,
    marketplace_name: str = "GiftBay",
    asking_price_cents: int = 4500,
    **overrides: Any,
) -> Dict[str, Any]:
    """A listing names "the card_id being offered, the marketplace_name ..., the
    asking_price_cents being sought, and the listed_balance_cents the reseller claims
    the card carries"."""
    return _merge(
        {
            "card_id": card_id,
            "marketplace_name": marketplace_name,
            "asking_price_cents": asking_price_cents,
            "listed_balance_cents": listed_balance_cents,
        },
        overrides,
    )


def listing_validation_payload(**overrides: Any) -> Dict[str, Any]:
    """Validation "accepts an optional validation_note"."""
    return _merge({"validation_note": "Checked against live card"}, overrides)


# ----------------------------------------------------------------------
# Liability periods
# ----------------------------------------------------------------------
def liability_period_payload(
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A period carries "a label (1 to 40 characters, unique across all periods), a
    period_start and a period_end that must fall strictly after it"."""
    return _merge(
        {
            "label": f"PERIOD-{next_seq()}",
            "period_start": period_start,
            "period_end": period_end,
        },
        overrides,
    )


def period_close_payload(**overrides: Any) -> Dict[str, Any]:
    """Closing takes "an optional close_note"."""
    return _merge({"close_note": "Month-end close"}, overrides)


def period_restate_payload(
    expected_liability_period_version: int, **overrides: Any
) -> Dict[str, Any]:
    """Restating "requires the request to carry expected_liability_period_version" and
    "requires a restatement_note"."""
    return _merge(
        {
            "expected_liability_period_version": expected_liability_period_version,
            "restatement_note": "Final reserve booked",
        },
        overrides,
    )


ADMIN_ROLE = ROLE_PLATFORM_ADMIN
