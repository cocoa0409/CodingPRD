"""Shared route helpers: list filtering and paged responses."""
from flask import request

from middleware import paginate
from response import list_response
from services import serialize

# enum vocabularies (read from the specification, never invented)
ACCEPTANCE_CLASSES = ["ACCEPTED_ALL_ROUTINGS", "CARGO_ONLY", "EMBARGOED_SPECIES"]
SPECIES_STATUSES = ["ACTIVE", "RETIRED"]
RESTRICTION_TYPES = ["SNUB_NOSED", "BANNED", "CARGO_ONLY", "WEIGHT_CAPPED"]
BREED_STATUSES = ["ACTIVE", "WITHDRAWN"]
DOCUMENT_TYPES = ["HEALTH_CERTIFICATE", "RABIES_VACCINATION", "IMPORT_PERMIT",
                  "PARASITE_TREATMENT"]
CONFIG_STATUSES = ["ACTIVE", "SUPERSEDED"]
STATION_STATUSES = ["ACCEPTING", "SUSPENDED"]
DIRECTIONS = ["ORIGIN", "DESTINATION"]
ROUTING_TYPES = ["CABIN", "CHECKED", "CARGO"]
LEG_STATUSES = ["SCHEDULED", "DELAYED", "CANCELLED", "DEPARTED", "ARRIVED"]
BOOKING_STATUSES = ["PENDING", "CONFIRMED", "HOLD_PARTIAL", "REBOOK_REQUIRED",
                    "IN_TRANSIT", "INTERRUPTED", "COMPLETED", "CANCELLED"]
COMPLIANCE_STATUSES = ["UNVERIFIED", "IN_REVIEW", "VERIFIED", "DEFICIENT", "EXPIRED"]
ANIMAL_KINDS = ["PET", "SERVICE_ANIMAL"]
ANIMAL_STATUSES = ["DRAFT", "SCREENED", "TRAVEL_READY", "IN_TRANSIT", "DELIVERED",
                   "DENIED", "DECEASED"]
SEGMENT_STATUSES = ["RESERVED", "ACCEPTED", "COMPLETED", "OFFLOADED", "RELEASED"]
DOCUMENT_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "VERIFIED", "REJECTED", "EXPIRED"]
ALLOCATION_STATUSES = ["RESERVED", "OCCUPIED", "RELEASED"]
CHECK_TYPES = ["WATER", "FEED", "VISUAL", "SANITATION"]
CHECK_OUTCOMES = ["NORMAL", "CONCERN"]
INCIDENT_TYPES = ["INJURY", "LOSS", "DEATH"]
INCIDENT_STATUSES = ["REPORTED", "INVESTIGATING", "REGULATOR_DISCLOSED", "CLOSED"]
VETERINARY_FINDINGS = ["CARRIER_ATTRIBUTABLE", "PRE_EXISTING_CONDITION", "INDETERMINATE"]

MONTH_DAY_PATTERN = r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$"
SPECIES_CODE_PATTERN = r"^[A-Z_]{2,24}$"
IATA_PATTERN = r"^[A-Z]{3}$"
COUNTRY_PATTERN = r"^[A-Z]{2}$"


def apply_filters(rows, specs):
    """specs: iterable of (query_param, field_name, kind)."""
    for param, field, kind in specs:
        raw = request.args.get(param)
        if raw is None:
            continue
        if kind == "bool":
            token = raw.strip().lower()
            if token in ("true", "1"):
                wanted = True
            elif token in ("false", "0"):
                wanted = False
            else:
                return []
            rows = [r for r in rows if r[field] is wanted]
        else:
            rows = [r for r in rows if r[field] == raw]
    return rows


def listing(entity, rows, ctx, specs=()):
    rows = apply_filters(rows, specs)
    total = len(rows)
    page = paginate(rows, ctx.limit, ctx.offset)
    return list_response(serialize.dump_all(entity, page), ctx.limit, ctx.offset, total)
