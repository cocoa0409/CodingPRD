"""Light-weight typing aliases shared by the Pentest Assurance test helpers."""

from typing import Any, Dict, List, Optional, Tuple

JsonObject = Dict[str, Any]
JsonList = List[JsonObject]
Headers = Dict[str, str]
QueryParams = Dict[str, Any]
PaginatedResult = Tuple[JsonList, JsonObject]

# Record aliases, kept deliberately loose: the server owns the schema and the
# tests read fields from the envelope's ``data`` payload directly.
Asset = JsonObject
TestPlan = JsonObject
ScopeItem = JsonObject
Engagement = JsonObject
RulesOfEngagement = JsonObject
AuthorizedTarget = JsonObject
Tester = JsonObject
TesterAssignment = JsonObject
Finding = JsonObject
CriticalAlert = JsonObject
Remediation = JsonObject
RetestVerification = JsonObject
TrainingRecommendation = JsonObject

OptionalStr = Optional[str]
OptionalInt = Optional[int]
OptionalFloat = Optional[float]


class Scenario(dict):
    """A bag of records produced by a scenario builder.

    Behaves as a plain dictionary but also exposes attribute access so a test
    can read ``scenario.engagement`` as well as ``scenario["engagement"]``.
    """

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value
