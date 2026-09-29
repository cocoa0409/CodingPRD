"""Request-payload builders.

Every builder returns a valid payload for its endpoint and accepts
`**overrides` so a test can vary exactly the one field it is about.
"""

from typing import Any, Dict, List, Optional

from .constants import CLOCK_STARTUP_DEFAULT
from .types import (
    AttributionBasis,
    BureauName,
    ConsentScope,
    ConsentSourceChannel,
    DepositPolicy,
    DuplicateResolution,
    FilingType,
    KbaOutcome,
    PartnerVertical,
    PayoutModel,
    SourceType,
    TrustTier,
    UtilityType,
    UspsOutcome,
    VerificationMethod,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay `overrides` on `base`; a None value still overwrites."""
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601: str = CLOCK_STARTUP_DEFAULT, **overrides: Any) -> Dict[str, Any]:
    """Body for the clock-control endpoint."""
    return _merge({"to_iso8601": to_iso8601}, overrides)


# ---------------------------------------------------------------------------
# Reference data (PRD 3.1)
# ---------------------------------------------------------------------------
def feed_source_payload(**overrides: Any) -> Dict[str, Any]:
    """A property-manager feed on a 0.1750 revenue share, TIER_B, 30-day window."""
    return _merge(
        {
            "name": "Metro PM Feed",
            "source_type": SourceType.PROPERTY_MANAGER.value,
            "referral_revenue_share_pct": 0.1750,
            "dedupe_window_days": 30,
            "trust_tier": TrustTier.TIER_B.value,
        },
        overrides,
    )


def resident_payload(**overrides: Any) -> Dict[str, Any]:
    """The primary resident, carrying the attributes the KBA vendor consumes."""
    return _merge(
        {
            "full_name": "Dana Ruiz",
            "email": "dana.ruiz@example.com",
            "phone_last4": "4417",
            "date_of_birth": "1988-04-12",
            "ssn_last4": "6621",
        },
        overrides,
    )


def second_resident_payload(**overrides: Any) -> Dict[str, Any]:
    """A second, unrelated resident sharing no identity signal with the first."""
    return _merge(
        {
            "full_name": "Priya Nadar",
            "email": "priya.nadar@example.com",
            "phone_last4": "2288",
            "date_of_birth": "1992-02-17",
            "ssn_last4": "7714",
        },
        overrides,
    )


def origin_address_payload(**overrides: Any) -> Dict[str, Any]:
    """The address being vacated, in postal code 30301."""
    return _merge(
        {
            "line1": "18 Maple Ct",
            "city": "Atlanta",
            "state_code": "GA",
            "postal_code": "30301",
        },
        overrides,
    )


def destination_address_payload(**overrides: Any) -> Dict[str, Any]:
    """The address being occupied, in postal code 30302, with a unit designator."""
    return _merge(
        {
            "line1": "402 Peachtree Way",
            "unit": "7B",
            "city": "Atlanta",
            "state_code": "GA",
            "postal_code": "30302",
        },
        overrides,
    )


def third_address_payload(**overrides: Any) -> Dict[str, Any]:
    """A third address in a different city and postal code, for contrast cases."""
    return _merge(
        {
            "line1": "77 Oak Ridge Rd",
            "city": "Macon",
            "state_code": "GA",
            "postal_code": "31201",
        },
        overrides,
    )


def undeliverable_address_payload(**overrides: Any) -> Dict[str, Any]:
    """An address whose postal_code begins with the non-deliverable prefix 000."""
    return _merge(
        {
            "line1": "5 Harbor Point",
            "city": "Atlanta",
            "state_code": "GA",
            "postal_code": "00012",
        },
        overrides,
    )


def electric_provider_payload(**overrides: Any) -> Dict[str, Any]:
    """A CREDIT_SCORE_BASED electric provider with a three-day lead time."""
    return _merge(
        {
            "name": "Georgia Metro Electric",
            "utility_type": UtilityType.ELECTRIC.value,
            "required_account_fields": ["account_holder_name", "service_start_date"],
            "deposit_policy": DepositPolicy.CREDIT_SCORE_BASED.value,
            "credit_check_required": True,
            "scheduling_lead_days": 3,
        },
        overrides,
    )


def water_provider_payload(**overrides: Any) -> Dict[str, Any]:
    """A water provider demanding no credit check and no lead time."""
    return _merge(
        {
            "name": "Atlanta Water Bureau",
            "utility_type": UtilityType.WATER.value,
            "required_account_fields": ["account_holder_name"],
            "deposit_policy": DepositPolicy.NONE.value,
            "credit_check_required": False,
            "scheduling_lead_days": 0,
        },
        overrides,
    )


def gas_provider_payload(**overrides: Any) -> Dict[str, Any]:
    """A FLAT-policy gas provider, whose flat_deposit_cents is the deposit base."""
    return _merge(
        {
            "name": "Peachtree Gas Co",
            "utility_type": UtilityType.GAS.value,
            "required_account_fields": ["account_holder_name"],
            "deposit_policy": DepositPolicy.FLAT.value,
            "flat_deposit_cents": 9900,
            "credit_check_required": True,
            "scheduling_lead_days": 1,
        },
        overrides,
    )


def alternate_electric_provider_payload(**overrides: Any) -> Dict[str, Any]:
    """A second electric provider with no deposit policy and a one-day lead time."""
    return _merge(
        {
            "name": "Piedmont Power Cooperative",
            "utility_type": UtilityType.ELECTRIC.value,
            "required_account_fields": ["account_holder_name"],
            "deposit_policy": DepositPolicy.NONE.value,
            "credit_check_required": False,
            "scheduling_lead_days": 1,
        },
        overrides,
    )


def territory_payload(provider_id: str, **overrides: Any) -> Dict[str, Any]:
    """A default-carrier territory row covering 30302 from 2026-01-01, open-ended."""
    return _merge(
        {
            "provider_id": provider_id,
            "postal_code": "30302",
            "state_code": "GA",
            "effective_from": "2026-01-01",
            "priority_rank": 1,
            "is_default_carrier": True,
        },
        overrides,
    )


def internet_partner_payload(**overrides: Any) -> Dict[str, Any]:
    """A REV_SHARE_PCT internet partner anchored on PLACEMENT_ACCEPTANCE."""
    return _merge(
        {
            "name": "Skyline Fiber",
            "vertical": PartnerVertical.INTERNET.value,
            "payout_model": PayoutModel.REV_SHARE_PCT.value,
            "rev_share_pct": 0.3,
            "attribution_window_days": 14,
            "attribution_basis": AttributionBasis.PLACEMENT_ACCEPTANCE.value,
            "monthly_placement_cap": 5,
        },
        overrides,
    )


def alternate_internet_partner_payload(**overrides: Any) -> Dict[str, Any]:
    """A second internet partner anchored on PLACEMENT_CLICK at a 0.2000 share."""
    return _merge(
        {
            "name": "Fiberline North",
            "vertical": PartnerVertical.INTERNET.value,
            "payout_model": PayoutModel.REV_SHARE_PCT.value,
            "rev_share_pct": 0.2,
            "attribution_window_days": 14,
            "attribution_basis": AttributionBasis.PLACEMENT_CLICK.value,
            "monthly_placement_cap": 5,
        },
        overrides,
    )


def insurance_partner_payload(**overrides: Any) -> Dict[str, Any]:
    """A FLAT_BOUNTY insurance partner paying 5000 cents per conversion."""
    return _merge(
        {
            "name": "Harbor Insurance",
            "vertical": PartnerVertical.INSURANCE.value,
            "payout_model": PayoutModel.FLAT_BOUNTY.value,
            "bounty_cents": 5000,
            "attribution_window_days": 30,
            "attribution_basis": AttributionBasis.PLACEMENT_CLICK.value,
            "monthly_placement_cap": 5,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Move intake (PRD 3.2)
# ---------------------------------------------------------------------------
def move_payload(
    resident_id: str,
    feed_source_id: str,
    origin_address_id: str,
    destination_address_id: str,
    move_date: str = "2026-08-20",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for move ingestion."""
    return _merge(
        {
            "resident_id": resident_id,
            "feed_source_id": feed_source_id,
            "origin_address_id": origin_address_id,
            "destination_address_id": destination_address_id,
            "move_date": move_date,
        },
        overrides,
    )


def duplicate_resolution_payload(
    resolution: str, expected_move_version: int, **overrides: Any
) -> Dict[str, Any]:
    """Body for duplicate resolution; MERGE_INTO additionally needs survivor_move_id."""
    return _merge(
        {"resolution": resolution, "expected_move_version": expected_move_version},
        overrides,
    )


def dismiss_payload(expected_move_version: int, **overrides: Any) -> Dict[str, Any]:
    """A DISMISS resolution, which leaves lifecycle_status entirely untouched."""
    return duplicate_resolution_payload(
        DuplicateResolution.DISMISS.value, expected_move_version, **overrides
    )


def merge_payload(
    expected_move_version: int, survivor_move_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A MERGE_INTO resolution folding this move into a survivor."""
    return duplicate_resolution_payload(
        DuplicateResolution.MERGE_INTO.value,
        expected_move_version,
        survivor_move_id=survivor_move_id,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Identity (PRD 3.3)
# ---------------------------------------------------------------------------
def kba_attempt_payload(**overrides: Any) -> Dict[str, Any]:
    """Open a KBA verification attempt."""
    return _merge({"method": VerificationMethod.KBA.value}, overrides)


def manual_override_payload(
    override_reason: str = "Passport inspected in branch", **overrides: Any
) -> Dict[str, Any]:
    """Record a compliance manual override, which requires a non-empty reason."""
    return _merge(
        {
            "method": VerificationMethod.MANUAL_OVERRIDE.value,
            "override_reason": override_reason,
        },
        overrides,
    )


def kba_result_payload(
    outcome: str = KbaOutcome.PASSED.value, score: int = 720, **overrides: Any
) -> Dict[str, Any]:
    """Vendor callback body; the passing bar is a score of at least 700."""
    return _merge({"outcome": outcome, "score": score}, overrides)


# ---------------------------------------------------------------------------
# Consent (PRD 3.4)
# ---------------------------------------------------------------------------
def consent_payload(
    scope: str,
    expected_resident_version: int,
    source_channel: str = ConsentSourceChannel.PM_FEED.value,
    consent_text_version: str = "v3",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for consent creation, guarded by expected_resident_version."""
    return _merge(
        {
            "scope": scope,
            "source_channel": source_channel,
            "consent_text_version": consent_text_version,
            "expected_resident_version": expected_resident_version,
        },
        overrides,
    )


def utility_consent_payload(expected_resident_version: int, **overrides: Any) -> Dict[str, Any]:
    """A UTILITY_SETUP consent, the scope provisioning work needs."""
    return consent_payload(
        ConsentScope.UTILITY_SETUP.value, expected_resident_version, **overrides
    )


def filing_consent_payload(expected_resident_version: int, **overrides: Any) -> Dict[str, Any]:
    """A USPS_FILING consent, the scope filing submission needs."""
    return consent_payload(
        ConsentScope.USPS_FILING.value, expected_resident_version, **overrides
    )


def marketing_consent_payload(expected_resident_version: int, **overrides: Any) -> Dict[str, Any]:
    """A PARTNER_MARKETING consent, the scope placement creation needs."""
    return consent_payload(
        ConsentScope.PARTNER_MARKETING.value,
        expected_resident_version,
        source_channel=ConsentSourceChannel.WEB_PORTAL.value,
        **overrides,
    )


def revocation_payload(revocation_reason: str = "Resident withdrew by phone", **overrides: Any) -> Dict[str, Any]:
    """Body for consent revocation; the reason is optional free text."""
    return _merge({"revocation_reason": revocation_reason}, overrides)


def marketing_preferences_payload(marketing_opt_out: bool, **overrides: Any) -> Dict[str, Any]:
    """Body for the resident-level marketing preference switch."""
    return _merge({"marketing_opt_out": marketing_opt_out}, overrides)


# ---------------------------------------------------------------------------
# Mapping and orders (PRD 3.5, 3.6)
# ---------------------------------------------------------------------------
def mapping_payload(utility_types: List[str], **overrides: Any) -> Dict[str, Any]:
    """Body for provider mapping; include_stop_orders also closes the old address."""
    return _merge({"utility_types": list(utility_types)}, overrides)


def schedule_payload(
    requested_service_date: str = "2026-08-05",
    scheduled_window_start: Optional[str] = None,
    scheduled_window_end: Optional[str] = None,
    account_data: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for order scheduling: a window on the requested date plus account data."""
    start = scheduled_window_start or f"{requested_service_date}T09:00:00Z"
    end = scheduled_window_end or f"{requested_service_date}T13:00:00Z"
    return _merge(
        {
            "requested_service_date": requested_service_date,
            "scheduled_window_start": start,
            "scheduled_window_end": end,
            "account_data": account_data
            if account_data is not None
            else {
                "account_holder_name": "Dana Ruiz",
                "service_start_date": requested_service_date,
            },
        },
        overrides,
    )


def credit_check_payload(bureau: str = BureauName.EXPERIAN.value, **overrides: Any) -> Dict[str, Any]:
    """Body for credit-check dispatch, which freezes the readiness snapshot."""
    return _merge({"bureau": bureau}, overrides)


def bureau_response_payload(score: int, **overrides: Any) -> Dict[str, Any]:
    """Bureau callback body; the score runs from 300 through 850 inclusive."""
    return _merge({"score": score}, overrides)


def deposit_payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    """Body for deposit payment, which must equal deposit_amount_cents exactly."""
    return _merge({"amount_cents": amount_cents}, overrides)


def activation_payload(confirmation_code: str = "CONF-88213", **overrides: Any) -> Dict[str, Any]:
    """Body for activation, which requires a non-empty confirmation code."""
    return _merge({"confirmation_code": confirmation_code}, overrides)


def provision_failure_payload(
    failure_reason: str = "Meter inaccessible at premises", **overrides: Any
) -> Dict[str, Any]:
    """Body for a provision failure, which requires a non-empty reason."""
    return _merge({"failure_reason": failure_reason}, overrides)


def closure_payload(final_read_note: str = "Final read 41255 kWh", **overrides: Any) -> Dict[str, Any]:
    """Body for closure; the final read note is optional."""
    return _merge({"final_read_note": final_read_note}, overrides)


def waiver_payload(waiver_reason: str = "Water included in the rent", **overrides: Any) -> Dict[str, Any]:
    """Body for a waiver, which requires a non-empty reason."""
    return _merge({"waiver_reason": waiver_reason}, overrides)


# ---------------------------------------------------------------------------
# Postal filings (PRD 3.7)
# ---------------------------------------------------------------------------
def filing_payload(
    forward_start_date: str = "2026-08-20",
    filing_type: str = FilingType.INDIVIDUAL.value,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for drafting a postal change-of-address filing."""
    return _merge(
        {"filing_type": filing_type, "forward_start_date": forward_start_date},
        overrides,
    )


def usps_confirmation_payload(
    usps_confirmation_code: str = "USPS-4471023", **overrides: Any
) -> Dict[str, Any]:
    """A CONFIRMED postal answer, which requires a non-empty confirmation code."""
    return _merge(
        {
            "outcome": UspsOutcome.CONFIRMED.value,
            "usps_confirmation_code": usps_confirmation_code,
        },
        overrides,
    )


def usps_rejection_payload(
    reject_reason: str = "Name mismatch on record", **overrides: Any
) -> Dict[str, Any]:
    """A REJECTED postal answer, which requires a non-empty reject reason."""
    return _merge(
        {"outcome": UspsOutcome.REJECTED.value, "reject_reason": reject_reason},
        overrides,
    )


def filing_cancellation_payload(
    cancellation_reason: str = "Filed against the wrong address", **overrides: Any
) -> Dict[str, Any]:
    """Body for withdrawing a filing; the reason is optional."""
    return _merge({"cancellation_reason": cancellation_reason}, overrides)


# ---------------------------------------------------------------------------
# Referrals (PRD 3.8)
# ---------------------------------------------------------------------------
def placement_payload(partner_id: str, expected_move_version: int, **overrides: Any) -> Dict[str, Any]:
    """Body for placement creation, guarded by expected_move_version."""
    return _merge(
        {"partner_id": partner_id, "expected_move_version": expected_move_version},
        overrides,
    )


def conversion_payload(gross_revenue_cents: int = 100000, **overrides: Any) -> Dict[str, Any]:
    """Body for conversion; the reported gross must be at least 1."""
    return _merge({"gross_revenue_cents": gross_revenue_cents}, overrides)


def decline_payload(decline_reason: str = "Household out of footprint", **overrides: Any) -> Dict[str, Any]:
    """Body for decline, the branch that posts no ledger entry."""
    return _merge({"decline_reason": decline_reason}, overrides)


def settlement_payload(settled_gross_revenue_cents: int = 100000, **overrides: Any) -> Dict[str, Any]:
    """Body for settlement, which recomputes both shares without the holdback."""
    return _merge({"settled_gross_revenue_cents": settled_gross_revenue_cents}, overrides)


def reversal_payload(reversal_reason: str = "Chargeback from partner", **overrides: Any) -> Dict[str, Any]:
    """Body for reversal, which returns the placement's ledger net to zero."""
    return _merge({"reversal_reason": reversal_reason}, overrides)


# ---------------------------------------------------------------------------
# Move-level actions (PRD 3.9)
# ---------------------------------------------------------------------------
def cancellation_payload(
    cancellation_reason: str = "Lease fell through", **overrides: Any
) -> Dict[str, Any]:
    """Body for move cancellation, the compensating unwind."""
    return _merge({"cancellation_reason": cancellation_reason}, overrides)


def clearance_payload(clearance_note: str = "Replacement order raised", **overrides: Any) -> Dict[str, Any]:
    """Body for attention clearance; the note is optional."""
    return _merge({"clearance_note": clearance_note}, overrides)


def status_payload(field: str, value: str) -> Dict[str, Any]:
    """A single-field status patch body, for example {"feed_status": "SUSPENDED"}."""
    return {field: value}
