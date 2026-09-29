"""Helpers shared by the route modules."""

import re

from envelope import list_response
from serialize import project_many
from services import paginate, sorted_rows

SYSTEM_AREA_CODE_RE = re.compile(r"^[A-Z_]{2,24}$")
OEM_CODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")
# PRD 3.7: "exactly 17 characters drawn from uppercase letters and digits with
# the letters I, O and Q excluded, per the VIN standard".
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

REGIONS = ("NA", "EU", "APAC")
TIERS = ("BASIC", "PRO", "ENTERPRISE")
LICENSE_MODELS = ("SUBSCRIPTION", "PER_VEHICLE", "EITHER")
LICENSE_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")
ENTITLEMENT_MODELS = ("SUBSCRIPTION", "PER_VEHICLE")
ENTITLEMENT_STATUSES = ("PENDING", "ACTIVE", "LAPSED", "CANCELLED")
SEAT_STATUSES = ("ACTIVE", "REVOKED", "SUPERSEDED")
TOOL_STATUSES = ("IDLE", "OCCUPIED")
IDENTITY_STATUSES = ("UNVERIFIED", "VERIFIED", "SUSPENDED", "REVOKED")
PUBLICATION_TYPES = ("REPAIR_PROCEDURE", "TSB", "CALIBRATION_DOC")
REVIEW_STATUSES = ("DRAFT", "VALIDATED")
DISTRIBUTION_STATUSES = ("WITHHELD", "PUBLISHED", "SUPERSEDED", "RECALLED")
SESSION_STATUSES = ("REQUESTED", "ACTIVE", "COMPLETED", "EXPIRED", "TERMINATED")
JOB_TYPES = ("IMMOBILIZER_KEY", "MODULE_FLASH", "ADAS_CALIBRATION")
JOB_STATUSES = ("QUEUED", "IN_PROGRESS", "REVALIDATION_REQUIRED", "COMPLETED", "ABORTED")
SUBJECT_ENTITIES = (
    "Technician",
    "SeatAssignment",
    "GatewaySession",
    "ModuleProgrammingJob",
    "PublicationVersion",
    "License",
    "ShopEntitlement",
)
EVENT_TYPES = (
    "TECHNICIAN_VERIFIED",
    "TECHNICIAN_SUSPENDED",
    "SEAT_ASSIGNED",
    "SEAT_REVOKED",
    "SESSION_CREDENTIAL_ISSUED",
    "SESSION_COMPLETED",
    "SESSION_TERMINATED",
    "JOB_STARTED",
    "JOB_COMPLETED",
    "JOB_ABORTED",
    "JOB_REVALIDATION_REQUIRED",
    "VERSION_PUBLISHED",
    "VERSION_RECALLED",
    "LICENSE_TERMINATED",
    "ENTITLEMENT_SETTLED",
)


def paged(kind, rows, limit, offset, presorted=False):
    ordered = rows if presorted else sorted_rows(rows)
    page, total = paginate(ordered, limit, offset)
    return list_response(project_many(kind, page), limit, offset, total)
