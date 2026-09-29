"""Shared route helpers: path resolution, equality filters, list rendering."""

from db import serialize
from errors import fail
from response import list_response
from validation import bad, pagination, query_args

# ---- enumerations --------------------------------------------------------
PIGGYBACK_DOCTRINE = ("STATUTORY_STRICT", "RECIPROCITY_LIBERAL")
SOLICITATION_STATUS = ("DRAFT", "POSTED", "EVALUATION", "AWARD_PENDING",
                       "AWARDED", "FAILED", "CANCELLED")
AUDIT_PACKAGE_STATUS = ("NOT_ASSEMBLED", "ASSEMBLED", "CERTIFIED", "STALE")
QUALIFICATION_STATUS = ("UNQUALIFIED", "QUALIFIED", "SUSPENDED", "DEBARRED")
PERFORMANCE_TIER = ("PREFERRED", "STANDARD", "PROBATION")
RESPONSE_STATUS = ("SUBMITTED", "INFO_REQUESTED", "RESPONSIVE",
                   "NON_RESPONSIVE", "WITHDRAWN")
CONTRACT_STATUS = ("PENDING_EXECUTION", "ACTIVE", "SUSPENDED", "EXPIRED",
                   "TERMINATED")
COMPLIANCE_POSTURE = ("COMPLIANT", "WATCH", "DELINQUENT")
LINE_ITEM_STATUS = ("ACTIVE", "WITHDRAWN")
LINE_ITEM_ORIGIN = ("AWARD", "EXPANSION")
MEMBER_CATEGORY = ("STATE_AGENCY", "CITY", "COUNTY", "K12_DISTRICT",
                   "HIGHER_ED", "SPECIAL_DISTRICT", "NONPROFIT_501C3")
REGISTRATION_STATUS = ("PENDING_VERIFICATION", "DOCS_REQUESTED", "ACTIVE",
                       "SUSPENDED", "TERMINATED")
ANALYSIS_STATUS = ("PENDING", "DETERMINED", "VOIDED")
DETERMINATION = ("AUTHORIZED", "CONDITIONAL", "DENIED")
VOID_REASON = ("MEMBER_SUSPENDED", "MEMBER_TERMINATED", "CONTRACT_SUSPENDED",
               "CONTRACT_TERMINATED", "SUPERSEDED_BY_NEWER_ANALYSIS",
               "ADMIN_VOID")
USAGE_STATUS = ("RECORDED", "CONFIRMED", "RETRACTED")
REPORT_STATUS = ("DRAFT", "SUBMITTED", "ACCEPTED", "RECONCILED", "REJECTED")
FEE_STATUS = ("NOT_DUE", "DUE", "PAID", "DELINQUENT")
AMENDMENT_TYPE = ("RENEWAL", "PRICE_ADJUSTMENT", "PRODUCT_LINE_EXPANSION")
AMENDMENT_STATUS = ("PROPOSED", "APPROVED", "REJECTED", "WITHDRAWN")
PRICE_INDEX = ("CPI_U", "PPI_COMMODITY")
COMPLAINT_STATUS = ("INTAKE", "UNDER_INVESTIGATION", "SUBSTANTIATED",
                    "APPEALED", "DISMISSED", "OVERTURNED", "CLOSED")
COMPLAINT_SEVERITY = ("MINOR", "MAJOR", "CRITICAL")
COMPLAINT_CATEGORY = ("PRICING", "DELIVERY", "PRODUCT_QUALITY", "BILLING",
                      "SERVICE")


def fetch(collection, ident, error_id):
    """Ladder step 4/5: resolve an identifier or raise the entity's 404."""
    row = collection.get(ident)
    if row is None:
        fail(error_id)
    return row


def render_list(rows, args, filters):
    """Apply equality filters, then paginate.  ``filters`` maps name -> (field, enum)."""
    for name, spec in filters.items():
        raw = args.get(name)
        if raw is None:
            continue
        field, enum = spec
        if enum is not None and raw not in enum:
            bad("query parameter '%s' must be one of %s" % (name, ", ".join(enum)))
        rows = [r for r in rows if r.get(field) == raw]
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return list_response([serialize(r) for r in page], limit, offset, total)


def list_endpoint(rows_provider, filters):
    """Validate the query string first (step 3), then resolve rows."""
    args = query_args(filters.keys())
    limit_offset_checked = pagination()  # raises before path resolution
    del limit_offset_checked
    rows = rows_provider()
    return render_list(rows, args, filters)
