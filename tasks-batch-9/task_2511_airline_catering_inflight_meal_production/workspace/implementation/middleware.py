"""Authentication, role authorization and airline scoping (PRD 2.1 / 2.10)."""

from flask import g, request

import db
from errors import fail

PLATFORM_ADMIN = "PlatformAdmin"
SCHEDULE_FEED_OPERATOR = "ScheduleFeedOperator"
AIRLINE_REP = "AirlineRep"
PRODUCTION_SUPERVISOR = "ProductionSupervisor"
QA_OFFICER = "QaOfficer"
LOAD_MASTER = "LoadMaster"
COMPLIANCE_OFFICER = "ComplianceOfficer"

ALL_ROLES = (
    PLATFORM_ADMIN,
    SCHEDULE_FEED_OPERATOR,
    AIRLINE_REP,
    PRODUCTION_SUPERVISOR,
    QA_OFFICER,
    LOAD_MASTER,
    COMPLIANCE_OFFICER,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_rep(self):
        return self.role == AIRLINE_REP


def actor():
    return getattr(g, "actor", None)


def authenticate(*allowed_roles):
    """Priority 10 then priority 20 of the validation ladder."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)

    if user_id is None or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()

    # An AirlineRep's identity IS an Airline.id, so it must resolve to a known
    # airline.  Every other role's identity is opaque and merely recorded.
    if role == AIRLINE_REP and db.get("airlines", user_id) is None:
        fail("ERR_UNAUTHENTICATED")

    allowed = allowed_roles if allowed_roles else ALL_ROLES
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE")

    g.actor = Actor(user_id, role)
    return g.actor


# ---------------------------------------------------------------------------
# airline scope resolution


def airline_of_flight(flight_id):
    flight = db.get("flights", flight_id)
    return flight["airline_id"] if flight else None


def airline_of_batch(batch):
    return airline_of_flight(batch["flight_id"]) if batch else None


def airline_of_cart(cart):
    return airline_of_flight(cart["flight_id"]) if cart else None


def airline_of_cart_item(item):
    cart = db.get("carts", item["cart_id"])
    return airline_of_cart(cart)


def airline_of_haccp_check(check):
    batch = db.get("production_batches", check["production_batch_id"])
    return airline_of_batch(batch)


def airline_of_manifest(manifest):
    return airline_of_flight(manifest["flight_id"]) if manifest else None


def airline_of_run(run):
    manifest = db.get("loading_manifests", run["loading_manifest_id"])
    return airline_of_manifest(manifest)


def airline_of_uplift(record):
    return airline_of_flight(record["flight_id"]) if record else None


def airline_of_waste(manifest):
    record = db.get("uplift_records", manifest["uplift_record_id"])
    return airline_of_uplift(record)


def require_scope(airline_id):
    """Priority 50: a rep may only reach rows of its own airline."""
    act = actor()
    if act is not None and act.is_rep and airline_id != act.user_id:
        fail("ERR_AIRLINE_SCOPE_VIOLATION")


def scoped(rows, resolver):
    """Filter a list endpoint's rows down to the rep's own airline."""
    act = actor()
    if act is None or not act.is_rep:
        return rows
    return [row for row in rows if resolver(row) == act.user_id]
