"""
Lightweight typing aliases and the field groups every resource must expose.

The API returns plain JSON, so these are documentation-grade aliases plus the
two audit-field groups of PRD 2.4: most resources carry the full complement of
id / created_at / updated_at / version, while CalibrationRun and
LicenseUsageRecord are immutable and expose only id and created_at.
"""

from typing import Any, Dict, List, Tuple

Json = Dict[str, Any]
JsonList = List[Json]
Headers = Dict[str, str]
Page = Tuple[JsonList, Json]

# PRD 2.4: "Every other resource in the system ... carries the full complement
# of id, created_at, updated_at and version."
MUTABLE_AUDIT_FIELDS = ("id", "created_at", "updated_at", "version")

# PRD 2.4: "a CalibrationRun and a LicenseUsageRecord expose only id and
# created_at. Both updated_at and version are absent from those two resources."
IMMUTABLE_AUDIT_FIELDS = ("id", "created_at")
IMMUTABLE_FORBIDDEN_FIELDS = ("updated_at", "version")

# Resources whose rows are immutable once written.
IMMUTABLE_RESOURCES = ("CalibrationRun", "LicenseUsageRecord")
