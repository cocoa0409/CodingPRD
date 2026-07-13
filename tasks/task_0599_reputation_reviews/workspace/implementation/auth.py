"""Authentication, authorization, tenant scoping and path resolution.

Validation precedence (PRD 2.9):
  1 auth -> 2 authz -> 3 tenant -> 4 path existence -> 5 body-ref existence
  -> 6 well-formedness -> 7 OCC -> 8 FROZEN -> 9 RESTRICTED -> 10 state -> ...
"""

from functools import wraps

from flask import g, request

import store
from errors import err

ROLES = (
    "PlatformAdmin",
    "BusinessOwner",
    "LocationManager",
    "ResponseAgent",
    "ComplianceOfficer",
    "Anonymous",
)

ID_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


def endpoint(roles):
    """Route decorator: priority 1 (401) then priority 2 (403)."""
    allowed = tuple(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get(ROLE_HEADER)
            user_id = request.headers.get(ID_HEADER)

            # priority 1 -- authentication
            if not role or role not in ROLES:
                raise err("ERR_UNAUTHENTICATED")
            if not user_id and not (role == "Anonymous" and "Anonymous" in allowed):
                raise err("ERR_UNAUTHENTICATED")

            # priority 2 -- authorization
            if role not in allowed:
                raise err("ERR_UNAUTHORIZED")

            g.role = role
            g.user_id = user_id or None
            g.touched = set()
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# --- tenant scoping (priority 3) ------------------------------------------
def _cross_tenant():
    return err("ERR_CROSS_TENANT_ACCESS")


def check_business_scope(business_id):
    """Target hangs beneath the Business named by `business_id`."""
    if g.role == "BusinessOwner":
        if g.user_id != business_id:
            raise _cross_tenant()
    elif g.role == "LocationManager":
        loc = store.locations.get(g.user_id)
        if loc is None or loc["business_id"] != business_id:
            raise _cross_tenant()


def check_location_scope(location):
    """Target hangs beneath the given Location record."""
    if g.role == "BusinessOwner":
        if g.user_id != location["business_id"]:
            raise _cross_tenant()
    elif g.role == "LocationManager":
        if g.user_id != location["id"]:
            raise _cross_tenant()


# --- path resolution (priority 4) -----------------------------------------
def resolve_business(business_id):
    check_business_scope(business_id)
    biz = store.businesses.get(business_id)
    if biz is None:
        raise err("ERR_BUSINESS_NOT_FOUND")
    return biz


def resolve_location(location_id):
    # A LocationManager's identity is the location id itself, so the tenant
    # check can precede the existence lookup, as PRD 2.9 requires.
    if g.role == "LocationManager" and g.user_id != location_id:
        raise _cross_tenant()
    loc = store.locations.get(location_id)
    if loc is None:
        raise err("ERR_LOCATION_NOT_FOUND")
    if g.role == "BusinessOwner" and g.user_id != loc["business_id"]:
        raise _cross_tenant()
    return loc


def resolve_listing(listing_id):
    li = store.listings.get(listing_id)
    if li is None:
        raise err("ERR_LISTING_NOT_FOUND")
    loc = store.locations[li["location_id"]]
    check_location_scope(loc)
    return li, loc


def resolve_campaign(campaign_id):
    c = store.campaigns.get(campaign_id)
    if c is None:
        raise err("ERR_CAMPAIGN_NOT_FOUND")
    loc = store.locations[c["location_id"]]
    check_location_scope(loc)
    return c, loc


def resolve_request(request_id):
    r = store.review_requests.get(request_id)
    if r is None:
        raise err("ERR_REQUEST_NOT_FOUND")
    campaign = store.campaigns[r["campaign_id"]]
    loc = store.locations[campaign["location_id"]]
    check_location_scope(loc)
    return r, campaign, loc


def resolve_review(review_id):
    r = store.reviews.get(review_id)
    if r is None:
        raise err("ERR_REVIEW_NOT_FOUND")
    loc = store.locations[r["location_id"]]
    check_location_scope(loc)
    return r, loc


def resolve_response(response_id):
    resp = store.review_responses.get(response_id)
    if resp is None:
        raise err("ERR_RESPONSE_NOT_FOUND")
    review = store.reviews[resp["review_id"]]
    loc = store.locations[review["location_id"]]
    check_location_scope(loc)
    return resp, review, loc


def resolve_escalation(escalation_id):
    e = store.escalations.get(escalation_id)
    if e is None:
        raise err("ERR_ESCALATION_NOT_FOUND")
    review = store.reviews[e["review_id"]]
    loc = store.locations[review["location_id"]]
    check_location_scope(loc)
    return e, review, loc


def resolve_survey(survey_id):
    s = store.surveys.get(survey_id)
    if s is None:
        raise err("ERR_SURVEY_NOT_FOUND")
    loc = store.locations[s["location_id"]]
    check_location_scope(loc)
    return s, loc


def resolve_widget(widget_id):
    w = store.widgets.get(widget_id)
    if w is None:
        raise err("ERR_WIDGET_NOT_FOUND")
    loc = store.locations[w["location_id"]]
    check_location_scope(loc)
    return w, loc


def resolve_contact(contact_id):
    c = store.contacts.get(contact_id)
    if c is None:
        raise err("ERR_CONTACT_NOT_FOUND")
    check_business_scope(c["business_id"])
    return c
