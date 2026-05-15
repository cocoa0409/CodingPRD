"""Error-id catalogue for the hazmat-transport-permit API.

The 25 canonical error-id strings the API surface emits, paired with their
HTTP status codes as the PRD's §5 error catalogue declares.  This module
registers the mapping with the local-runner framework's validators so
``validate_error(response, expected_error_id)`` cross-checks the HTTP
status without the caller having to pass ``expected_status`` explicitly.

The auth tier is 401 (``ERR_UNAUTHENTICATED``) and 403 (``ERR_ROLE_NOT_PERMITTED``
default-deny and ``ERR_CROSS_TENANT_ACCESS`` per-row-ownership-deny).  The
existence tier has one 404 per addressable entity (seven entities, seven
ids).  The state tier is 409 (``ERR_INVALID_STATE_TRANSITION`` for the
same-row guard and ``ERR_PERMIT_NOT_ACTIVE`` for the cross-aggregate
parent-state guard on the trip-and-gps endpoints).  The business-safety
sub-tier holds the seven safety-domain 409 ids covering the
driver-endorsement, vehicle-inspection, route-approval, company-qualification,
the appeal-and-void-window timeouts, and the GPS in-window and
strict-monotonicity checks.  The business-constraint sub-tier holds the
natural-key-uniqueness 409, the vehicle-double-booking interval-overlap
409, the trip-vs-permit window-membership 409, the dedicated
permit-vehicle-list-cardinality 422 (the lone non-409 in the business
tier, reflecting the body-shape-as-business-constraint flavour of the
cardinality check), the two renewal-window edge 409s, the fiscal-tier
wallet-shortfall unique 402 ``ERR_INSUFFICIENT_WALLET_BALANCE``, the
idempotency-key-body-mismatch 409, the OCC ``ERR_VERSION_CONFLICT`` 409,
and the catch-all body-shape ``ERR_VALIDATION`` 422 at the bottom of the
priority order.

The catalogue is a closed set: the response envelope's ``data.error_id``
field always carries a string from this list, and every test-assertion in
the suite picks its expected ``error_id`` from a member of ``ApiErrorId``.
"""

from enum import Enum
from typing import Dict

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    """The 25 canonical error-id string-values the response envelope's
    error data carries."""

    # ── Auth tier ─────────────────────────────────────────────────────
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_ROLE_NOT_PERMITTED = "ERR_ROLE_NOT_PERMITTED"
    ERR_CROSS_TENANT_ACCESS = "ERR_CROSS_TENANT_ACCESS"

    # ── Existence tier (one per addressable entity) ──────────────────
    ERR_COMPANY_NOT_FOUND = "ERR_COMPANY_NOT_FOUND"
    ERR_DRIVER_NOT_FOUND = "ERR_DRIVER_NOT_FOUND"
    ERR_VEHICLE_NOT_FOUND = "ERR_VEHICLE_NOT_FOUND"
    ERR_ROUTE_NOT_FOUND = "ERR_ROUTE_NOT_FOUND"
    ERR_PERMIT_NOT_FOUND = "ERR_PERMIT_NOT_FOUND"
    ERR_TRIP_NOT_FOUND = "ERR_TRIP_NOT_FOUND"
    ERR_PENALTY_NOT_FOUND = "ERR_PENALTY_NOT_FOUND"

    # ── State tier ────────────────────────────────────────────────────
    ERR_INVALID_STATE_TRANSITION = "ERR_INVALID_STATE_TRANSITION"
    ERR_PERMIT_NOT_ACTIVE = "ERR_PERMIT_NOT_ACTIVE"

    # ── Business-safety sub-tier (5a, priorities 509–515) ────────────
    ERR_GPS_OUT_OF_WINDOW = "ERR_GPS_OUT_OF_WINDOW"
    ERR_DRIVER_ENDORSEMENT_INVALID = "ERR_DRIVER_ENDORSEMENT_INVALID"
    ERR_VEHICLE_INSPECTION_LAPSED = "ERR_VEHICLE_INSPECTION_LAPSED"
    ERR_GPS_OUT_OF_ORDER = "ERR_GPS_OUT_OF_ORDER"
    ERR_APPEAL_WINDOW_CLOSED = "ERR_APPEAL_WINDOW_CLOSED"
    ERR_VOID_WINDOW_CLOSED = "ERR_VOID_WINDOW_CLOSED"

    # ── Business-constraint and -referential sub-tier (5b/c, 520–531)
    ERR_DUPLICATE_IDENTIFIER = "ERR_DUPLICATE_IDENTIFIER"
    ERR_VEHICLE_DOUBLE_BOOKED = "ERR_VEHICLE_DOUBLE_BOOKED"
    ERR_OUTSIDE_VALIDITY_WINDOW = "ERR_OUTSIDE_VALIDITY_WINDOW"
    ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE = "ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE"
    ERR_ROUTE_NOT_APPROVED = "ERR_ROUTE_NOT_APPROVED"
    ERR_COMPANY_NOT_QUALIFIED = "ERR_COMPANY_NOT_QUALIFIED"

    # ── Renewal-window edges (5b temporal at 541/542) ────────────────
    ERR_RENEWAL_TOO_EARLY = "ERR_RENEWAL_TOO_EARLY"
    ERR_RENEWAL_AFTER_EXPIRY = "ERR_RENEWAL_AFTER_EXPIRY"

    # ── Fiscal tier (5d, priority 540) ───────────────────────────────
    ERR_INSUFFICIENT_WALLET_BALANCE = "ERR_INSUFFICIENT_WALLET_BALANCE"

    # ── Idempotency and OCC (5e at 550, 5f at 560) ───────────────────
    ERR_IDEMPOTENCY_KEY_REUSED = "ERR_IDEMPOTENCY_KEY_REUSED"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # ── Body-shape catch-all (Tier-5 floor at priority 590) ──────────
    ERR_VALIDATION = "ERR_VALIDATION"


HTTP_STATUS_CODES: Dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED.value: 401,
    ApiErrorId.ERR_ROLE_NOT_PERMITTED.value: 403,
    ApiErrorId.ERR_CROSS_TENANT_ACCESS.value: 403,
    ApiErrorId.ERR_COMPANY_NOT_FOUND.value: 404,
    ApiErrorId.ERR_DRIVER_NOT_FOUND.value: 404,
    ApiErrorId.ERR_VEHICLE_NOT_FOUND.value: 404,
    ApiErrorId.ERR_ROUTE_NOT_FOUND.value: 404,
    ApiErrorId.ERR_PERMIT_NOT_FOUND.value: 404,
    ApiErrorId.ERR_TRIP_NOT_FOUND.value: 404,
    ApiErrorId.ERR_PENALTY_NOT_FOUND.value: 404,
    ApiErrorId.ERR_INVALID_STATE_TRANSITION.value: 409,
    ApiErrorId.ERR_PERMIT_NOT_ACTIVE.value: 409,
    ApiErrorId.ERR_GPS_OUT_OF_WINDOW.value: 409,
    ApiErrorId.ERR_DRIVER_ENDORSEMENT_INVALID.value: 409,
    ApiErrorId.ERR_VEHICLE_INSPECTION_LAPSED.value: 409,
    ApiErrorId.ERR_GPS_OUT_OF_ORDER.value: 409,
    ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value: 409,
    ApiErrorId.ERR_VOID_WINDOW_CLOSED.value: 409,
    ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value: 409,
    ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value: 409,
    ApiErrorId.ERR_OUTSIDE_VALIDITY_WINDOW.value: 409,
    ApiErrorId.ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE.value: 422,
    ApiErrorId.ERR_ROUTE_NOT_APPROVED.value: 409,
    ApiErrorId.ERR_COMPANY_NOT_QUALIFIED.value: 409,
    ApiErrorId.ERR_RENEWAL_TOO_EARLY.value: 409,
    ApiErrorId.ERR_RENEWAL_AFTER_EXPIRY.value: 409,
    ApiErrorId.ERR_INSUFFICIENT_WALLET_BALANCE.value: 402,
    ApiErrorId.ERR_IDEMPOTENCY_KEY_REUSED.value: 409,
    ApiErrorId.ERR_VERSION_CONFLICT.value: 409,
    ApiErrorId.ERR_VALIDATION.value: 422,
}


# Register the mapping with the framework's validator module so the
# ``validate_error`` cross-check fires automatically without each test
# having to pass ``expected_status`` by hand.
set_error_http_status_map(HTTP_STATUS_CODES)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
