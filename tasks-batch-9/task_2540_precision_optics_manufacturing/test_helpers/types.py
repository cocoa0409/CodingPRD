"""Lightweight type aliases for the precision optics manufacturing API.

These aliases document the shapes that flow between the helpers and the tests.
They are deliberately permissive: the API returns JSON objects and the tests
assert on individual members rather than on whole structures.
"""

from typing import Any, Dict, List, Tuple

Headers = Dict[str, str]
Payload = Dict[str, Any]
Params = Dict[str, Any]

OpticalDesign = Dict[str, Any]
ToleranceAllocation = Dict[str, Any]
GlassLot = Dict[str, Any]
WorkOrder = Dict[str, Any]
MetrologyInstrument = Dict[str, Any]
ProcessRun = Dict[str, Any]
MetrologyReport = Dict[str, Any]
CoatingChamber = Dict[str, Any]
CoatingRun = Dict[str, Any]
Assembly = Dict[str, Any]
AssemblyComponent = Dict[str, Any]
InspectionRecord = Dict[str, Any]
ExportClassification = Dict[str, Any]
DocumentationPackage = Dict[str, Any]
ReleaseReadiness = Dict[str, Any]

SpectralSample = Dict[str, Any]
SpectralTrace = List[SpectralSample]

PaginatedResult = Tuple[List[Dict[str, Any]], Dict[str, Any]]
