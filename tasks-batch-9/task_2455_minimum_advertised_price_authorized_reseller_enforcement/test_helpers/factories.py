"""Payload factories.

Each factory returns a valid request body for one endpoint, carrying only the
fields the PRD says a client supplies.  Server-computed properties (`id`,
`created_at`, `updated_at`, `version`, statuses and every derived money or
points field) are never included.  Overrides are applied last so a caller can
drop a field with ``None`` semantics by popping it after the call.
"""
import itertools

from .constants import DEFAULT_CLOCK, EVIDENCE_HASH_1, EVIDENCE_HASH_3
from .types import (
    AgreementResponseDecision,
    Channel,
    ChannelScope,
    ChargebackDisputeDecision,
    DealerInputSource,
    DeliveryChannel,
    ExceptionDecision,
    ExceptionType,
    ExposureVariant,
    ProductLifecycle,
    ReviewDecision,
    SupplyStatus,
    TestPurchaseOutcome,
    ViolationDisputeDecision,
)

_seq = itertools.count(1)


def _next():
    return next(_seq)


# --------------------------------------------------------------------------- #
# Pricing policies (PRD 3.1)
# --------------------------------------------------------------------------- #
def pricing_policy_payload(**overrides):
    payload = {"policy_code": f"MAP-2026-{_next():04d}"}
    payload.update(overrides)
    return payload


def policy_review_decision_payload(decision=ReviewDecision.APPROVE_FOR_PUBLICATION.value, **overrides):
    payload = {"decision": decision, "legal_review_notes": "Antitrust review complete."}
    payload.update(overrides)
    return payload


def policy_publish_payload(effective_from=DEFAULT_CLOCK, **overrides):
    payload = {"effective_from": effective_from}
    payload.update(overrides)
    return payload


def policy_withdraw_payload(**overrides):
    payload = {"withdrawn_reason": "Superseded by a revised programme."}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Products (PRD 3.2)
# --------------------------------------------------------------------------- #
def product_payload(governing_policy_id, **overrides):
    payload = {
        "sku": f"SKU-AUDIO-{_next():04d}",
        "name": "Reference Studio Headphones",
        "msrp_cents": 20000,
        "standard_map_floor_cents": 15000,
        "governing_policy_id": governing_policy_id,
    }
    payload.update(overrides)
    return payload


def product_adjustment_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


def effective_floor_params(channel=Channel.MARKETPLACE.value, **overrides):
    params = {"channel": channel}
    params.update(overrides)
    return params


# --------------------------------------------------------------------------- #
# Distributors and resellers (PRD 3.3)
# --------------------------------------------------------------------------- #
def distributor_payload(**overrides):
    payload = {
        "legal_name": f"Northwind Distribution {_next():04d}",
        "annual_chargeback_cap_cents": 10_000_000,
    }
    payload.update(overrides)
    return payload


def reseller_payload(**overrides):
    payload = {
        "legal_name": f"Sunrise Audio Retail {_next():04d}",
        "contact_email": "compliance@sunrise-audio.example",
        "primary_channel": Channel.MARKETPLACE.value,
    }
    payload.update(overrides)
    return payload


def supply_status_payload(supply_status=SupplyStatus.HOLD.value, **overrides):
    payload = {"supply_status": supply_status}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Reseller agreements (PRD 3.4)
# --------------------------------------------------------------------------- #
def agreement_payload(reseller_id, policy_id, **overrides):
    payload = {
        "reseller_id": reseller_id,
        "policy_id": policy_id,
        "permitted_channels": [Channel.MARKETPLACE.value],
        "quality_obligations": ["AUTHENTICITY_LABELING"],
        "term_ends_at": "2027-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def agreement_response_payload(
    decision=AgreementResponseDecision.COUNTERSIGN.value, **overrides
):
    payload = {"decision": decision}
    if decision == AgreementResponseDecision.COUNTERSIGN.value:
        payload["non_negotiation_acknowledged"] = True
    else:
        payload["decline_reason"] = "Channel restrictions unacceptable."
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Price observations (PRD 3.5)
# --------------------------------------------------------------------------- #
def observation_payload(product_id, **overrides):
    payload = {
        "product_id": product_id,
        "channel": Channel.MARKETPLACE.value,
        "seller_display_name": "BargainAudioHub",
        "listing_url": "https://marketplace.example/listing/1",
        "listed_price_cents": 14000,
        "observed_at": DEFAULT_CLOCK,
        "evidence_hash": EVIDENCE_HASH_1,
    }
    payload.update(overrides)
    return payload


def bundle_component(sku, msrp_cents):
    return {"sku": sku, "msrp_cents": msrp_cents}


def bundle_observation_payload(product_id, sku, **overrides):
    payload = observation_payload(
        product_id,
        is_bundle=True,
        bundle_total_price_cents=30000,
        bundle_components=[bundle_component(sku, 20000), bundle_component("SKU-CABLE-1", 10000)],
    )
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Violations (PRD 3.7)
# --------------------------------------------------------------------------- #
def cure_submission_payload(**overrides):
    payload = {
        "cure_evidence_url": "https://marketplace.example/listing/1?corrected",
        "corrected_price_cents": 15000,
        "evidence_hash": EVIDENCE_HASH_3,
    }
    payload.update(overrides)
    return payload


def violation_dispute_payload(**overrides):
    payload = {"dispute_reason": "The listing price shown was a display error."}
    payload.update(overrides)
    return payload


def violation_dispute_decision_payload(
    decision=ViolationDisputeDecision.REJECT.value, **overrides
):
    payload = {"decision": decision, "decision_reason": "Evidence reviewed."}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Enforcement notices (PRD 3.7)
# --------------------------------------------------------------------------- #
def notice_payload(reseller_id, violation_id, expected_reseller_version, **overrides):
    payload = {
        "reseller_id": reseller_id,
        "violation_id": violation_id,
        "delivery_channel": DeliveryChannel.EMAIL.value,
        "expected_reseller_version": expected_reseller_version,
    }
    payload.update(overrides)
    return payload


def rescind_payload(**overrides):
    payload = {"rescinded_reason": "Notice issued on incomplete evidence."}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Pricing exceptions (PRD 3.6)
# --------------------------------------------------------------------------- #
def exception_payload(product_id, **overrides):
    payload = {
        "product_id": product_id,
        "exception_type": ExceptionType.PROMOTIONAL_EVENT.value,
        "starts_at": "2026-09-01T00:00:00Z",
        "ends_at": "2026-09-10T00:00:00Z",
        "requested_override_floor_cents": 12000,
    }
    payload.update(overrides)
    return payload


def clearance_exception_payload(product_id, **overrides):
    payload = {
        "product_id": product_id,
        "exception_type": ExceptionType.CLEARANCE.value,
        "starts_at": "2026-09-01T00:00:00Z",
        "ends_at": "2026-09-10T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def exception_decision_payload(decision=ExceptionDecision.APPROVE.value, **overrides):
    payload = {"decision": decision, "decision_reason": "Marketing plan cleared."}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Serial units and test purchases (PRD 3.8)
# --------------------------------------------------------------------------- #
def serial_unit_payload(product_id, shipped_distributor_id, **overrides):
    payload = {
        "serial_number": f"SN-{_next():06d}",
        "product_id": product_id,
        "lot_code": "LOT-A",
        "shipped_distributor_id": shipped_distributor_id,
    }
    payload.update(overrides)
    return payload


def ship_downstream_payload(downstream_reseller_id, **overrides):
    payload = {"downstream_reseller_id": downstream_reseller_id}
    payload.update(overrides)
    return payload


def test_purchase_payload(observation_id, **overrides):
    payload = {
        "observation_id": observation_id,
        "ordered_at": DEFAULT_CLOCK,
        "purchase_price_cents": 13000,
    }
    payload.update(overrides)
    return payload


# This factory is named after the "test purchase" entity of PRD 3.8, so its name
# collides with pytest's `test_*` collection rule once a test module imports it.
# Mark it as not-a-test so pytest leaves it alone.
test_purchase_payload.__test__ = False


def serial_capture_payload(serial_number, **overrides):
    payload = {"serial_number": serial_number}
    payload.update(overrides)
    return payload


def confirm_outcome_payload(outcome=TestPurchaseOutcome.UNAUTHORIZED.value, **overrides):
    payload = {"outcome": outcome, "outcome_reason": "Seller holds no authorization."}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Chargebacks (PRD 3.9)
# --------------------------------------------------------------------------- #
def chargeback_payload(
    distributor_id, test_purchase_id, expected_distributor_version, diverted_units=1, **overrides
):
    payload = {
        "distributor_id": distributor_id,
        "test_purchase_id": test_purchase_id,
        "diverted_units": diverted_units,
        "expected_distributor_version": expected_distributor_version,
    }
    payload.update(overrides)
    return payload


def chargeback_dispute_payload(**overrides):
    payload = {"dispute_reason": "Units were shipped under a different lot."}
    payload.update(overrides)
    return payload


def chargeback_dispute_decision_payload(
    decision=ChargebackDisputeDecision.UPHOLD.value, **overrides
):
    payload = {"decision": decision, "decision_reason": "Shipping records reviewed."}
    payload.update(overrides)
    return payload


def exposure_params(variant=ExposureVariant.TRACE_ATTRIBUTED.value, **overrides):
    params = {"variant": variant}
    params.update(overrides)
    return params


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #
def clock_payload(to_iso8601):
    return {"to_iso8601": to_iso8601}


__all__ = [
    "pricing_policy_payload",
    "policy_review_decision_payload",
    "policy_publish_payload",
    "policy_withdraw_payload",
    "product_payload",
    "product_adjustment_payload",
    "effective_floor_params",
    "distributor_payload",
    "reseller_payload",
    "supply_status_payload",
    "agreement_payload",
    "agreement_response_payload",
    "observation_payload",
    "bundle_component",
    "bundle_observation_payload",
    "cure_submission_payload",
    "violation_dispute_payload",
    "violation_dispute_decision_payload",
    "notice_payload",
    "rescind_payload",
    "exception_payload",
    "clearance_exception_payload",
    "exception_decision_payload",
    "serial_unit_payload",
    "ship_downstream_payload",
    "test_purchase_payload",
    "serial_capture_payload",
    "confirm_outcome_payload",
    "chargeback_payload",
    "chargeback_dispute_payload",
    "chargeback_dispute_decision_payload",
    "exposure_params",
    "clock_payload",
]
