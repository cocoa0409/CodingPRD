"""Auth context extraction and role authorization (pipeline tiers 1-2)."""

from flask import request

import errors

ROLES = ("PlatformAdmin", "AccountManager", "WaterChemist", "CustomerContact")

ALL_ROLES = ["PlatformAdmin", "AccountManager", "WaterChemist", "CustomerContact"]
PA = ["PlatformAdmin"]
AM = ["AccountManager"]
WC = ["WaterChemist"]
CC = ["CustomerContact"]

# (method, path-template) -> allowed roles. "Any" in the endpoint table means
# every authenticated role.
ENDPOINT_ROLES = {
    ("POST", "/wt/_clock/set_current_utc"): PA,

    ("POST", "/wt/accounts"): AM,
    ("GET", "/wt/accounts"): ["AccountManager", "WaterChemist", "PlatformAdmin"],
    ("GET", "/wt/accounts/<accountId>"): ALL_ROLES,
    ("POST", "/wt/accounts/<accountId>/suspend"): AM,
    ("POST", "/wt/accounts/<accountId>/reactivate"): AM,
    ("POST", "/wt/accounts/<accountId>/close"): AM,

    ("POST", "/wt/assets"): WC,
    ("GET", "/wt/assets"): ALL_ROLES,
    ("GET", "/wt/assets/<assetId>"): ALL_ROLES,
    ("GET", "/wt/assets/<assetId>/water-savings"): ALL_ROLES,
    ("POST", "/wt/assets/<assetId>/commission"): WC,
    ("POST", "/wt/assets/<assetId>/decommission"): WC,
    ("POST", "/wt/assets/<assetId>/blowdown-events"): WC,
    ("GET", "/wt/assets/<assetId>/blowdown-events"): ALL_ROLES,

    ("POST", "/wt/program-designs"): WC,
    ("GET", "/wt/program-designs"): ALL_ROLES,
    ("GET", "/wt/program-designs/<designId>"): ALL_ROLES,
    ("POST", "/wt/program-designs/<designId>/record-survey"): WC,
    ("POST", "/wt/program-designs/<designId>/draft"): WC,
    ("POST", "/wt/program-designs/<designId>/propose"): WC,
    ("POST", "/wt/program-designs/<designId>/accept"): CC,
    ("POST", "/wt/program-designs/<designId>/request-revision"): CC,
    ("POST", "/wt/program-designs/<designId>/reopen-survey"): WC,
    ("POST", "/wt/program-designs/<designId>/withdraw"): WC,

    ("POST", "/wt/products"): PA,
    ("GET", "/wt/products"): ["AccountManager", "WaterChemist", "PlatformAdmin"],
    ("GET", "/wt/products/<productId>"): ["AccountManager", "WaterChemist", "PlatformAdmin"],
    ("POST", "/wt/products/<productId>/delist"): PA,

    ("POST", "/wt/feed-stations"): WC,
    ("GET", "/wt/feed-stations"): ALL_ROLES,
    ("GET", "/wt/feed-stations/<stationId>"): ALL_ROLES,
    ("POST", "/wt/feed-stations/<stationId>/bring-online"): WC,
    ("POST", "/wt/feed-stations/<stationId>/lockout"): WC,
    ("POST", "/wt/feed-stations/<stationId>/telemetry"): WC,
    ("GET", "/wt/feed-stations/<stationId>/telemetry"): ALL_ROLES,

    ("POST", "/wt/test-routes"): WC,
    ("GET", "/wt/test-routes"): ALL_ROLES,
    ("GET", "/wt/test-routes/<routeId>"): ALL_ROLES,
    ("POST", "/wt/test-routes/<routeId>/stops"): WC,
    ("GET", "/wt/test-routes/<routeId>/stops"): ALL_ROLES,
    ("POST", "/wt/test-routes/<routeId>/publish"): WC,
    ("POST", "/wt/test-routes/<routeId>/cancel"): WC,

    ("GET", "/wt/route-stops"): ALL_ROLES,
    ("GET", "/wt/route-stops/<stopId>"): ALL_ROLES,
    ("POST", "/wt/route-stops/<stopId>/arrive"): WC,
    ("POST", "/wt/route-stops/<stopId>/mark-missed"): WC,
    ("POST", "/wt/route-stops/<stopId>/water-test-results"): WC,
    ("GET", "/wt/route-stops/<stopId>/water-test-results"): ALL_ROLES,

    ("GET", "/wt/water-test-results"): ALL_ROLES,
    ("GET", "/wt/water-test-results/<resultId>"): ALL_ROLES,
    ("POST", "/wt/water-test-results/<resultId>/confirm"): WC,
    ("POST", "/wt/water-test-results/<resultId>/void"): WC,

    ("GET", "/wt/corrective-actions"): ALL_ROLES,
    ("GET", "/wt/corrective-actions/<actionId>"): ALL_ROLES,
    ("POST", "/wt/corrective-actions/<actionId>/approve"): WC,
    ("POST", "/wt/corrective-actions/<actionId>/apply"): WC,
    ("POST", "/wt/corrective-actions/<actionId>/decline"): WC,

    ("POST", "/wt/racks"): WC,
    ("GET", "/wt/racks"): ALL_ROLES,
    ("GET", "/wt/racks/<rackId>"): ALL_ROLES,
    ("POST", "/wt/racks/<rackId>/archive"): WC,
    ("POST", "/wt/racks/<rackId>/coupons"): WC,
    ("GET", "/wt/racks/<rackId>/coupons"): ALL_ROLES,
    ("POST", "/wt/coupons/<couponId>/remove"): WC,

    ("POST", "/wt/legionella-plans"): WC,
    ("GET", "/wt/legionella-plans"): ALL_ROLES,
    ("GET", "/wt/legionella-plans/<planId>"): ALL_ROLES,
    ("POST", "/wt/legionella-plans/<planId>/activate"): WC,
    ("POST", "/wt/legionella-plans/<planId>/validate"): WC,
    ("POST", "/wt/legionella-plans/<planId>/declare-delinquent"): WC,
    ("POST", "/wt/legionella-plans/<planId>/suspend"): AM,
    ("POST", "/wt/legionella-plans/<planId>/return-to-draft"): WC,

    ("POST", "/wt/delivery-orders"): AM,
    ("GET", "/wt/delivery-orders"): ALL_ROLES,
    ("GET", "/wt/delivery-orders/<orderId>"): ALL_ROLES,
    ("POST", "/wt/delivery-orders/<orderId>/submit"): AM,
    ("POST", "/wt/delivery-orders/<orderId>/schedule"): AM,
    ("POST", "/wt/delivery-orders/<orderId>/dispatch"): AM,
    ("POST", "/wt/delivery-orders/<orderId>/confirm-delivery"): WC,
    ("POST", "/wt/delivery-orders/<orderId>/fail"): WC,
    ("POST", "/wt/delivery-orders/<orderId>/close"): WC,
    ("POST", "/wt/delivery-orders/<orderId>/cancel"): AM,

    ("POST", "/wt/invoices"): AM,
    ("GET", "/wt/invoices"): ALL_ROLES,
    ("GET", "/wt/invoices/<invoiceId>"): ALL_ROLES,
    ("POST", "/wt/invoices/<invoiceId>/issue"): AM,
    ("POST", "/wt/invoices/<invoiceId>/pay"): CC,
    ("POST", "/wt/invoices/<invoiceId>/void"): AM,
}


def authenticate():
    """Pipeline tiers 1-2. Returns (user_id, role) or raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        raise errors.missing_context()
    if role not in ROLES:
        raise errors.unauthorized_role()
    rule = request.url_rule
    if rule is not None and rule.rule.startswith("/wt/"):
        allowed = ENDPOINT_ROLES.get((request.method, rule.rule))
        if allowed is not None and role not in allowed:
            raise errors.unauthorized_role()
    return user_id, role
