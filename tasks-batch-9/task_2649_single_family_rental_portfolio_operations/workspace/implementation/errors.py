"""Error catalog (PRD section 5, verbatim statuses) and the ApiError exception."""

_TABLE = """
ERR_INVALID_REQUEST|400|The request payload is missing a required field, uses the wrong type, carries an out-of-range value, or supplies an inverted interval.
ERR_INVALID_ROLE|400|The X-User-Role header is absent or is not a recognised role.
ERR_UNAUTHENTICATED|401|The X-User-ID header is absent or empty.
ERR_NOT_ASSIGNED_VENDOR|403|This work order is assigned to a different vendor.
ERR_NOT_SLOT_OWNER|403|This booking or application belongs to a different prospect.
ERR_UNAUTHORIZED|403|The caller role is not permitted to invoke this endpoint.
ERR_COMPLIANCE_OBLIGATION_NOT_FOUND|404|No compliance obligation exists with the supplied identifier.
ERR_HOME_NOT_FOUND|404|No home exists with the supplied identifier.
ERR_LEASE_NOT_FOUND|404|No lease exists with the supplied identifier.
ERR_MARKET_NOT_FOUND|404|No market exists with the supplied identifier.
ERR_PROSPECT_NOT_FOUND|404|No prospect exists with the supplied identifier.
ERR_RENOVATION_PROJECT_NOT_FOUND|404|No renovation project exists with the supplied identifier.
ERR_RENTAL_APPLICATION_NOT_FOUND|404|No rental application exists with the supplied identifier.
ERR_SCOPE_TEMPLATE_NOT_FOUND|404|No scope template exists with the supplied identifier or code.
ERR_SHOWING_SLOT_NOT_FOUND|404|No showing slot exists with the supplied identifier.
ERR_UNDERWRITING_CASE_NOT_FOUND|404|No underwriting case exists with the supplied identifier.
ERR_VENDOR_CERTIFICATION_NOT_FOUND|404|No vendor certification exists with the supplied identifier.
ERR_VENDOR_NOT_FOUND|404|No vendor exists with the supplied identifier.
ERR_WORK_ORDER_NOT_FOUND|404|No work order exists with the supplied identifier.
ERR_APPLICATION_NOT_APPROVED|409|The rental application has not been approved or conditionally approved.
ERR_CASE_NOT_APPROVED|409|The home has no approved underwriting case, so no renovation project can be opened.
ERR_DUPLICATE_APPLICATION|409|This prospect already has a submitted application on this home.
ERR_DUPLICATE_CERTIFICATION|409|This vendor already holds an active certification with this certification code.
ERR_DUPLICATE_MARKET_CODE|409|A market with this code already exists.
ERR_DUPLICATE_PROJECT_FOR_HOME|409|This home already has a renovation project.
ERR_DUPLICATE_SCOPE_TEMPLATE_CODE|409|A scope template with this code already exists.
ERR_DUPLICATE_PROSPECT_EMAIL|409|A prospect with this email already exists.
ERR_HOME_NOT_ACQUIRED|409|The home has not been acquired, so its renovation scope cannot be locked.
ERR_HOME_NOT_VACANT|409|The home is not vacant, so this application cannot be screened.
ERR_INVALID_STATE|409|The entity is not in a state from which the requested transition is defined.
ERR_LEASE_ALREADY_EXISTS|409|This home already has a drafted or executed lease.
ERR_PROJECT_SCOPE_LOCKED|409|The renovation project is already rent ready and accepts no further work orders.
ERR_SEGREGATION_OF_DUTIES|409|The user who submitted this item may not decide or review it.
ERR_SHOWING_SLOT_NOT_AVAILABLE|409|The showing slot is not available for booking.
ERR_SHOWING_SLOT_OVERLAP|409|The showing window overlaps, or violates the buffer around, an existing slot on this home.
ERR_VENDOR_CAPACITY_EXCEEDED|409|The vendor's daily crew capacity would be exceeded on at least one date in the work window.
ERR_WORK_ORDER_NOT_ASSIGNED|409|This vendor-channel work order has no assigned vendor.
ERR_STALE_HOME_VERSION|412|expected_home_version does not match the current Home.version; re-read the home and retry.
ERR_STALE_PROSPECT_VERSION|412|expected_prospect_version does not match the current Prospect.version; re-read the prospect and retry.
ERR_BUDGET_BELOW_COMMITTED|422|The revised budget is below the cost already committed to work orders.
ERR_COST_VARIANCE_EXCEEDED|422|The quoted cost variance against benchmark exceeds this market's tolerance.
ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE|422|Only minor or major HOA violations may be waived.
ERR_DEPOSIT_NOT_FUNDED|422|The move-in deposit has not been fully funded.
ERR_DEPOSIT_OVERPAYMENT|422|The payment would push deposits paid above the required deposit.
ERR_DISPOSITION_NOT_ELIGIBLE|422|An individual-asset sale requires a vacant home.
ERR_EVIDENCE_REQUIRED|422|An evidence reference is required for this obligation type.
ERR_HOME_LEASING_FROZEN|422|This home is not open for lease execution.
ERR_HOME_SHOWINGS_BLOCKED|422|Showings and screening are blocked while this home is frozen.
ERR_IN_HOUSE_SAFETY_CRITICAL|422|Safety-critical scopes may not be dispatched to the in-house bench.
ERR_LEASE_TERM_INVALID|422|The lease term differs from this market's standard term and the caller cannot override it.
ERR_MARKET_MISMATCH|422|The referenced entities belong to different markets.
ERR_NO_ELIGIBLE_VENDOR|422|No vendor in this market satisfies the eligibility filter for this work order.
ERR_OBLIGATION_PAST_DUE|422|The planned resolution date falls after the obligation due date.
ERR_OBLIGATION_WORK_ORDER_MISMATCH|422|The referenced work order belongs to another home or has been voided.
ERR_PET_COUNT_EXCEEDED|422|The declared pet count exceeds this market's limit or does not match the breed list.
ERR_PROJECT_BUDGET_EXCEEDED|422|The work order would push committed cost above the project's approved budget.
ERR_PROJECT_SCOPE_EMPTY|422|The renovation project has no live work orders, so there is no scope to lock.
ERR_PROSPECT_FRAUD_BLOCKED|422|The prospect's fraud risk score exceeds this market's block threshold.
ERR_PROSPECT_IDENTITY_UNVERIFIED|422|The prospect has not passed identity verification.
ERR_RENT_CONCESSION_EXCEEDED|422|The monthly rent is below this market's maximum concession floor.
ERR_RESTRICTED_BREED|422|A declared pet breed is restricted in this market.
ERR_REVISION_LIMIT_EXCEEDED|422|This underwriting case has already used its two permitted revision rounds.
ERR_SETTLED_VALUE_INVALID|422|The settled assessment value is missing or outside the permitted range.
ERR_SLOT_DURATION_INVALID|422|The showing window is shorter than this market's minimum showing duration.
ERR_SLOT_IN_PAST|422|The showing window starts before the current time.
ERR_VENDOR_INACTIVE|422|The vendor is suspended and cannot receive dispatches.
ERR_VENDOR_INSURANCE_EXPIRED|422|The vendor's insurance has lapsed as of the current date.
ERR_VENDOR_NOT_CERTIFIED|422|The vendor holds no current certification for this scope template trade.
ERR_YIELD_BELOW_FLOOR|422|The underwritten yield on cost is below this market's underwriting floor.
ERR_COMPLETION_DATE_INVALID|422|The completion date precedes the work order's scheduled start date.
"""

CATALOG = {}
for _line in _TABLE.strip().splitlines():
    _id, _status, _msg = _line.split("|", 2)
    CATALOG[_id] = {"status": int(_status), "message": _msg}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        entry = CATALOG.get(error_id, {})
        self.error_id = error_id
        self.http_status = http_status or entry.get("status", 400)
        self.message = message or entry.get("message", error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
