"""Lightweight structural types for API payloads.

Responses are plain JSON dicts; these aliases document the shapes that helper
functions hand back so test bodies read as domain language rather than dicts.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

Json = Dict[str, Any]
Headers = Dict[str, str]

Market = Json
Supplier = Json
Certification = Json
ModelAgreement = Json
CommissionOverride = Json
RatePlan = Json
Offer = Json
DirectRateObservation = Json
ParityCase = Json
PlacementAgreement = Json
RankingRun = Json
RankingEntry = Json
OpaquePackage = Json
PackageComponent = Json
Booking = Json
DisputeCase = Json
SupplierScorecard = Json

Page = Tuple[List[Json], Json]


class Ctx(dict):
    """A bootstrap context: attribute access over a plain dict of built rows.

    Fixtures build up a chain of dependent rows (market -> supplier ->
    certification -> agreement -> rate plan -> offer) and hand the whole chain
    back so a test can reach any link without rebuilding it.
    """

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value
