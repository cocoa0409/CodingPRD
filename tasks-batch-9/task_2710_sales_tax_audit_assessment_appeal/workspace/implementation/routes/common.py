"""Shared route helpers."""
import re

from flask import g

import db
from errors import ApiError
from middleware import bad, filter_arg, pagination, paginate
from response import list_response, object_response
from services import derive

NAICS_RE = re.compile(r"^[0-9]{6}$")

FILING_FREQUENCIES = ("MONTHLY", "QUARTERLY", "ANNUAL")
COMPLIANCE_STATUSES = ("COMPLIANT", "DELINQUENT", "REVOKED")
SOURCE_TYPES = ("FEDERAL_1099K", "WHOLESALER_REPORT", "MARKETPLACE_REPORT")
MATCH_STATUSES = ("MATCHED", "UNDER_REPORTED", "OVER_REPORTED")
SELECTION_MODES = ("THRESHOLD", "QUOTA", "HYBRID")
LEAD_STATUSES = ("SCORED", "SELECTED", "NOT_SELECTED", "CONVERTED", "DECLINED")
AUDIT_TYPES = ("FIELD", "DESK", "MANAGED")
AUDIT_STATUSES = ("PLANNED", "SCOPED", "FIELDWORK", "REVIEW_COMPLETE", "ASSESSED", "CLOSED", "ABANDONED")
STATUTE_STATUSES = ("UNSET", "PROTECTED", "EXPIRING_SOON", "EXPIRED")
WAIVER_STATUSES = ("DRAFTED", "EXECUTED", "VOIDED")
METHODOLOGIES = ("MEAN_PER_UNIT", "RATIO_ESTIMATION")
AGREEMENT_STATUSES = ("PROPOSED", "COUNTERED", "AGREED", "SUPERSEDED")
CONFIDENCE_LEVELS = (9000, 9500, 9900)
ERROR_CLASSES = ("PENDING", "NO_ERROR", "UNREPORTED_TAXABLE_SALE", "CERTIFICATE_DEFECT", "RATE_ERROR")
EXEMPTION_TYPES = ("RESALE", "MANUFACTURING", "AGRICULTURAL", "NONPROFIT", "GOVERNMENT")
CERT_STATUSES = ("ON_FILE", "VALIDATED", "REJECTED", "CURED")
ASSET_CLASSES = ("CONSUMABLE", "CAPITAL_ASSET", "EXEMPT_MANUFACTURING")
ASSESSMENT_STATUSES = ("DRAFT", "DRAFT_STALE", "ISSUED", "FINAL", "WITHDRAWN", "SUPERSEDED")
COLLECTION_STATUSES = ("NOT_DUE", "DUE", "ARRANGED", "REFERRED", "SATISFIED")
ADJUSTMENT_KINDS = ("PENALTY_ABATEMENT", "PAYMENT", "APPEAL_REDUCTION", "ASSESSMENT_VACATED",
                    "COLLECTION_FEE", "OIC_WRITEOFF")
SYSTEM_ONLY_KINDS = ("PENALTY_ABATEMENT", "APPEAL_REDUCTION", "ASSESSMENT_VACATED",
                     "COLLECTION_FEE", "OIC_WRITEOFF")
ADJUSTMENT_STATUSES = ("POSTED", "REVERSED")
FORUMS = ("INFORMAL_CONFERENCE", "ADMINISTRATIVE_APPEAL", "TAX_TRIBUNAL")
PROCEEDING_STATUSES = ("OPEN", "DECIDED")
OUTCOMES = ("NONE", "SUSTAINED", "REDUCED", "REMANDED")
ARRANGEMENT_TYPES = ("INSTALLMENT_PLAN", "OFFER_IN_COMPROMISE")
ARRANGEMENT_STATUSES = ("REQUESTED", "APPROVED", "COMPLETED", "DEFAULTED", "CANCELLED")
ABATEMENT_FACTORS = ("FIRST_TIME_COMPLIANT", "RELIANCE_ON_WRITTEN_ADVICE",
                     "RECORDS_LOST_IN_DISASTER", "SUBSTANTIAL_COOPERATION")


def naics(data, name):
    from middleware import req_str

    value = req_str(data, name, 1, None)
    if not NAICS_RE.match(value):
        bad("%s must be a six-digit NAICS code." % name)
    return value


def path_get(kind, rid):
    """Tier 3: path existence, left to right."""
    return db.must_get(kind, rid)


def body_fk(kind, rid):
    """Tier 6: body foreign key resolution."""
    return db.must_get(kind, rid)


def require_owner(taxpayer_id):
    """Tier 4: ownership, only for the seven enumerated operations."""
    if g.role == "Taxpayer" and g.user_id != taxpayer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def one(kind, rec, status=200):
    return object_response(derive.view(kind, rec), status)


def listing(kind, records, extra_filters=None):
    limit, offset = pagination()
    total = len(records)
    page = paginate(records, limit, offset)
    return list_response(derive.views(kind, page), limit, offset, total)


def by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def apply_filter(records, field, allowed=None, arg_name=None, coerce=None):
    name = arg_name or field
    value = filter_arg(name, allowed)
    if value is None:
        return records
    if coerce is int:
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            bad("%s filter must be an integer." % name)
    elif coerce is bool:
        lowered = str(value).strip().lower()
        if lowered in ("true", "1"):
            value = True
        elif lowered in ("false", "0"):
            value = False
        else:
            bad("%s filter must be true or false." % name)
    return [r for r in records if r.get(field) == value]
