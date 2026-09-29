"""Lightweight structural type aliases for the interconnection domain.

These exist to make the helper and fixture signatures readable; the API returns
plain JSON so every alias is a ``dict`` at runtime.
"""

from typing import Any, Dict, List, Optional, Tuple

Json = Dict[str, Any]
JsonList = List[Json]
Headers = Dict[str, str]

Carrier = Json
Agreement = Json
NegotiationOffer = Json
TrunkGroup = Json
TrafficMeasurement = Json
TrunkAugmentOrder = Json
TariffFiling = Json
TrafficFactorFiling = Json
UsageBatch = Json
CallDetailRecord = Json
AccessInvoice = Json
BillingDispute = Json
ReconciliationCase = Json
ReserveLedgerEntry = Json
ReserveSummary = Json
ReciprocalSettlement = Json

PaginatedResult = Tuple[JsonList, Json]

# Entities that carry the full common-field set (id, created_at, updated_at,
# version) per the PRD's common-field policy.
VERSIONED_ENTITIES = (
    "carrier",
    "agreement",
    "trunk_group",
    "trunk_augment_order",
    "tariff_filing",
    "traffic_factor_filing",
    "usage_batch",
    "access_invoice",
    "billing_dispute",
    "reconciliation_case",
)

# Entities that carry only id and created_at.
IMMUTABLE_ENTITIES = (
    "negotiation_offer",
    "traffic_measurement",
    "call_detail_record",
    "reserve_ledger_entry",
)

__all__ = [
    "Any",
    "Dict",
    "List",
    "Optional",
    "Tuple",
    "Json",
    "JsonList",
    "Headers",
    "Carrier",
    "Agreement",
    "NegotiationOffer",
    "TrunkGroup",
    "TrafficMeasurement",
    "TrunkAugmentOrder",
    "TariffFiling",
    "TrafficFactorFiling",
    "UsageBatch",
    "CallDetailRecord",
    "AccessInvoice",
    "BillingDispute",
    "ReconciliationCase",
    "ReserveLedgerEntry",
    "ReserveSummary",
    "ReciprocalSettlement",
    "PaginatedResult",
    "VERSIONED_ENTITIES",
    "IMMUTABLE_ENTITIES",
]
