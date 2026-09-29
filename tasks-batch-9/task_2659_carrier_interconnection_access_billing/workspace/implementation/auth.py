"""Authentication, authorisation, carrier scoping, segregation of duties and
optimistic concurrency (PRD 2.1, 2.6, 2.9)."""
from flask import request

from errors import ApiError
from store import db

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PLATFORM_ADMIN = "PlatformAdmin"
INTERCONNECTION_MANAGER = "InterconnectionManager"
NETWORK_PLANNER = "NetworkPlanner"
ACCESS_BILLING_ANALYST = "AccessBillingAnalyst"
DISPUTE_RESOLUTION_OFFICER = "DisputeResolutionOfficer"
REGULATORY_AFFAIRS_SPECIALIST = "RegulatoryAffairsSpecialist"
REVENUE_ASSURANCE_CONTROLLER = "RevenueAssuranceController"
CARRIER_REPRESENTATIVE = "CarrierRepresentative"

ALL_ROLES = (
    PLATFORM_ADMIN,
    INTERCONNECTION_MANAGER,
    NETWORK_PLANNER,
    ACCESS_BILLING_ANALYST,
    DISPUTE_RESOLUTION_OFFICER,
    REGULATORY_AFFAIRS_SPECIALIST,
    REVENUE_ASSURANCE_CONTROLLER,
    CARRIER_REPRESENTATIVE,
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_carrier_rep(self):
        return self.role == CARRIER_REPRESENTATIVE


def authenticate(allowed_roles):
    """Step 1 authentication, then step 2 authorisation (PRD 2.7)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "missing X-User-ID header")
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "missing X-User-Role header")
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "unknown role")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not call this operation" % role)
    return Actor(str(user_id).strip(), role)


def scope_check(actor, carrier_id):
    """Step 6 carrier scope. For a CarrierRepresentative the X-User-ID is the
    Carrier.id; anything reached outside it is refused."""
    if actor.is_carrier_rep and actor.user_id != carrier_id:
        raise ApiError("ERR_CARRIER_SCOPE_VIOLATION",
                       "carrier representative may only reach its own carrier")


def scope_filter(actor, rows, carrier_getter):
    if not actor.is_carrier_rep:
        return rows
    return [r for r in rows if carrier_getter(r) == actor.user_id]


def segregation_check(actor, issued_by_user_id):
    """Step 7 segregation of duties (PRD 2.9)."""
    if issued_by_user_id is not None and actor.user_id == issued_by_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the user who issued the invoice may not perform this operation")


def check_agreement_version(agreement, expected):
    if expected is not None and agreement["version"] != expected:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION",
                       "expected_agreement_version does not match stored version")


def check_carrier_version(carrier, expected):
    if expected is not None and carrier["version"] != expected:
        raise ApiError("ERR_STALE_CARRIER_VERSION",
                       "expected_carrier_version does not match stored version")


# ---------------------------------------------------------------- graph walks
def carrier_of_agreement(agreement):
    return agreement["carrier_id"]


def carrier_of_offer(offer):
    agreement = db.agreements.get(offer["agreement_id"])
    return agreement["carrier_id"] if agreement else None


def carrier_of_trunk_group(trunk_group):
    agreement = db.agreements.get(trunk_group["agreement_id"])
    return agreement["carrier_id"] if agreement else None


def carrier_of_measurement(measurement):
    tg = db.trunk_groups.get(measurement["trunk_group_id"])
    return carrier_of_trunk_group(tg) if tg else None


def carrier_of_order(order):
    tg = db.trunk_groups.get(order["trunk_group_id"])
    return carrier_of_trunk_group(tg) if tg else None


def carrier_of_batch(batch):
    return batch["carrier_id"]


def carrier_of_cdr(cdr):
    batch = db.usage_batches.get(cdr["usage_batch_id"])
    return batch["carrier_id"] if batch else None


def carrier_of_invoice(invoice):
    return invoice["carrier_id"]


def carrier_of_dispute(dispute):
    invoice = db.invoices.get(dispute["invoice_id"])
    return invoice["carrier_id"] if invoice else None


def carrier_of_case(case):
    batch = db.usage_batches.get(case["usage_batch_id"])
    return batch["carrier_id"] if batch else None


def carrier_of_factor_filing(filing):
    return filing["carrier_id"]
