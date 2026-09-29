"""Lightweight typed containers returned by the composite setup helpers.

These are plain dataclasses so tests can read ``ctx.cycle_id`` instead of
threading dictionaries of raw identifiers between steps.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CycleContext:
    """A cycle plus the disciplines provisioned inside it."""

    cycle_id: str
    cycle_code: str
    cycle: Dict[str, Any]
    discipline_ids: Dict[str, str] = field(default_factory=dict)
    disciplines: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def version(self) -> int:
        return self.cycle["version"]

    def discipline_id(self, code: str) -> str:
        return self.discipline_ids[code]


@dataclass
class ApplicantContext:
    """An applicant row plus the headers that authenticate as that artist."""

    applicant_id: str
    email: str
    applicant: Dict[str, Any]
    headers: Dict[str, str]


@dataclass
class ApplicationContext:
    """An application together with the artist and cycle it belongs to."""

    application_id: str
    application: Dict[str, Any]
    applicant: ApplicantContext
    cycle_id: str
    discipline_id: str
    portfolio_item_ids: List[str] = field(default_factory=list)


@dataclass
class PanelistContext:
    """A panelist row plus the headers that authenticate as that reviewer."""

    panelist_id: str
    email: str
    panelist: Dict[str, Any]
    headers: Dict[str, str]
    chair_headers: Optional[Dict[str, str]] = None


@dataclass
class ResidencyContext:
    """A residency plus everything needed to keep operating on it."""

    residency_id: str
    residency: Dict[str, Any]
    cycle_id: str
    applicant_id: str
    discipline_id: str
    applicant_headers: Optional[Dict[str, str]] = None
    application_id: Optional[str] = None

    @property
    def version(self) -> int:
        return self.residency["version"]

    @property
    def session_start_date(self) -> Optional[str]:
        return self.residency.get("session_start_date")

    @property
    def session_end_date(self) -> Optional[str]:
        return self.residency.get("session_end_date")


@dataclass
class StudioContext:
    """A studio row."""

    studio_id: str
    code: str
    studio: Dict[str, Any]

    @property
    def version(self) -> int:
        return self.studio["version"]


@dataclass
class HousingUnitContext:
    """A housing unit row."""

    housing_unit_id: str
    code: str
    unit: Dict[str, Any]

    @property
    def version(self) -> int:
        return self.unit["version"]


@dataclass
class SlateContext:
    """The result of locking a slate: the cycle and every scored application."""

    cycle: CycleContext
    applications: Dict[str, ApplicationContext] = field(default_factory=dict)
    panelists: Dict[str, PanelistContext] = field(default_factory=dict)
    chair: Optional[PanelistContext] = None
