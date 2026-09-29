"""Lightweight structural types shared by the helper layer and the test suite.

These are convenience containers for the identifiers a composite fixture hands
back; they carry no business logic and make no assertions.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

JsonDict = Dict[str, Any]
Headers = Dict[str, str]


@dataclass
class AgreementScenario:
    """An agreement plus the crew base that made activation possible."""

    agreement: JsonDict
    crew_base: JsonDict
    base_headers: Headers = field(default_factory=dict)

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def crew_base_id(self) -> str:
        return self.crew_base["id"]

    @property
    def agreement_version(self) -> int:
        return self.agreement["version"]


@dataclass
class StaffedBaseScenario:
    """An active agreement with a base staffed by line-qualified captains."""

    agreement: JsonDict
    crew_base: JsonDict
    base_headers: Headers
    pilots: List[JsonDict] = field(default_factory=list)
    aircraft: List[JsonDict] = field(default_factory=list)

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def crew_base_id(self) -> str:
        return self.crew_base["id"]

    @property
    def pilot_ids(self) -> List[str]:
        return [pilot["id"] for pilot in self.pilots]

    @property
    def aircraft_ids(self) -> List[str]:
        return [tail["id"] for tail in self.aircraft]

    @property
    def captain_pilot_id(self) -> str:
        return self.pilots[0]["id"]

    @property
    def aircraft_id(self) -> str:
        return self.aircraft[0]["id"]


@dataclass
class CycleScenario:
    """A settlement month sitting on top of a staffed base and an inducted tail."""

    agreement: JsonDict
    crew_base: JsonDict
    base_headers: Headers
    pilots: List[JsonDict]
    aircraft: List[JsonDict]
    cycle: JsonDict
    legs: List[JsonDict] = field(default_factory=list)

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def crew_base_id(self) -> str:
        return self.crew_base["id"]

    @property
    def cycle_id(self) -> str:
        return self.cycle["id"]

    @property
    def cycle_version(self) -> int:
        return self.cycle["version"]

    @property
    def aircraft_id(self) -> str:
        return self.aircraft[0]["id"]

    @property
    def captain_pilot_id(self) -> str:
        return self.pilots[0]["id"]

    @property
    def pilot_ids(self) -> List[str]:
        return [pilot["id"] for pilot in self.pilots]

    @property
    def aircraft_ids(self) -> List[str]:
        return [tail["id"] for tail in self.aircraft]

    @property
    def leg_ids(self) -> List[str]:
        return [leg["id"] for leg in self.legs]


@dataclass
class SettledCycleScenario:
    """A closed month with its published scorecard, ready for invoicing."""

    agreement: JsonDict
    crew_base: JsonDict
    base_headers: Headers
    cycle: JsonDict
    legs: List[JsonDict]
    scorecard: JsonDict
    invoice: Optional[JsonDict] = None

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def cycle_id(self) -> str:
        return self.cycle["id"]

    @property
    def cycle_version(self) -> int:
        return self.cycle["version"]

    @property
    def scorecard_id(self) -> str:
        return self.scorecard["id"]

    @property
    def invoice_id(self) -> str:
        assert self.invoice is not None, "scenario was built without an invoice"
        return self.invoice["id"]

    @property
    def leg_ids(self) -> List[str]:
        return [leg["id"] for leg in self.legs]


__all__ = [
    "JsonDict",
    "Headers",
    "AgreementScenario",
    "StaffedBaseScenario",
    "CycleScenario",
    "SettledCycleScenario",
]
