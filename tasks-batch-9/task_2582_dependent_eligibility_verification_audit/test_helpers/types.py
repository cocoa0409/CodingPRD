"""Structural aliases for the payloads this API hands back.

Responses are plain JSON dicts; the aliases below document which resource a
helper returns so test bodies read as domain language rather than as dictionary
plumbing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

Json = Dict[str, Any]
Headers = Dict[str, str]

AuditProgram = Json
Employee = Json
Dependent = Json
DocumentationRule = Json
AuditCase = Json
ProofSubmission = Json
AmnestyRemoval = Json
Appeal = Json
TerminationNotice = Json
ClaimRecovery = Json
PaidClaimLine = Json
CommunicationEvent = Json

Page = Tuple[List[Json], Json]


class Ctx(dict):
    """A scenario context: attribute access over the rows a fixture built.

    An audit wave is a chain of dependent rows (employee -> dependents ->
    program -> documentation rules -> case -> notices -> recoveries), and a
    scenario builder hands the whole chain back so a test can reach any link
    without rebuilding it.
    """

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value
