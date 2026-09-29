"""Type aliases for the CMBS Special Servicing API test suite."""

from typing import Any, Dict, List, Optional, Tuple

Json = Dict[str, Any]
Headers = Dict[str, str]
JsonList = List[Json]
Paginated = Tuple[JsonList, Json]

# Entity payload aliases (documentation value only; every payload is a plain dict).
TrustPayload = Json
LoanPayload = Json
TransferEventPayload = Json
BorrowerRequestPayload = Json
AppraisalPayload = Json
AdvancePayload = Json
WorkoutPlanPayload = Json
WorkoutAlternativePayload = Json
ConsultationPayload = Json
REOAssetPayload = Json
FeeAccrualPayload = Json
DistributionReportPayload = Json

CashFlow = Json
CashFlows = List[CashFlow]

OptionalStr = Optional[str]
OptionalFloat = Optional[float]
OptionalInt = Optional[int]
