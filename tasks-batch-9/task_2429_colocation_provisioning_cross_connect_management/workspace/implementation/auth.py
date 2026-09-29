"""Role-based access control and CustomerAdmin scoping.

PRD §2.1 / §2.5 rules 1, 2 and 5:
  1. X-User-Role names one of the five declared roles, else ERR_UNAUTHENTICATED.
  2. The role is authorized for the endpoint, else ERR_UNAUTHORIZED — checked
     before any path identifier is resolved.
  5. For a CustomerAdmin, X-User-ID is the acting Customer's id and every
     referenced resource belongs to that customer, else
     ERR_CUSTOMER_SCOPE_VIOLATION — checked after existence resolution.
"""

from flask import request

from errors import ApiError
from store import ROLES, store


class Actor(object):
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id
        self.customer_id = None

    # -- CustomerAdmin scope ------------------------------------------------

    @property
    def is_customer_admin(self):
        return self.role == "CustomerAdmin"

    def require_customer(self):
        """Resolve X-User-ID to a Customer. No-op for staff roles, whose
        X-User-ID is an opaque identifier tied to no persisted entity."""
        if not self.is_customer_admin:
            return None
        if self.customer_id is not None:
            return self.customer_id
        uid = self.user_id
        if not uid or uid not in store.customers:
            raise ApiError(
                "ERR_CUSTOMER_SCOPE_VIOLATION",
                "X-User-ID does not identify a customer",
            )
        self.customer_id = uid
        return self.customer_id

    def scope_customer_id(self, customer_id):
        if not self.is_customer_admin:
            return
        mine = self.require_customer()
        if customer_id != mine:
            raise ApiError(
                "ERR_CUSTOMER_SCOPE_VIOLATION",
                "resource belongs to another customer",
            )

    def scope_contract(self, contract):
        if contract is not None:
            self.scope_customer_id(contract.get("customer_id"))

    def scope_contract_id(self, contract_id):
        if contract_id is None:
            return
        self.scope_contract(store.contracts.get(contract_id))

    def scope_contact(self, contact):
        if contact is not None:
            self.scope_customer_id(contact.get("customer_id"))

    def scope_cabinet(self, cabinet):
        """A cabinet is owned through its contract; an unreserved cabinet has
        no owning customer to violate."""
        if cabinet is None:
            return
        self.scope_contract_id(cabinet.get("contract_id"))

    def scope_cabinet_id(self, cabinet_id):
        if cabinet_id is None:
            return
        self.scope_cabinet(store.cabinets.get(cabinet_id))

    def scope_circuit(self, circuit):
        if circuit is None:
            return
        self.scope_cabinet_id(circuit.get("cabinet_id"))

    # -- query-string filters ----------------------------------------------
    # A filter naming another customer's resource is a scope violation; a
    # filter naming nothing at all simply matches no rows.

    def scope_query(self, *pairs):
        """pairs of (kind, query-parameter name)."""
        if not self.is_customer_admin:
            return
        for kind, name in pairs:
            value = request.args.get(name)
            if not value:
                continue
            if kind == "customer":
                self.scope_customer_id(value)
            elif kind == "contract":
                if value in store.contracts:
                    self.scope_contract(store.contracts[value])
            elif kind == "cabinet":
                if value in store.cabinets:
                    self.scope_cabinet(store.cabinets[value])
            elif kind == "circuit":
                if value in store.circuits:
                    self.scope_circuit(store.circuits[value])
            elif kind == "contact":
                if value in store.contacts:
                    self.scope_contact(store.contacts[value])


def authorize(*allowed):
    """Rules 1 and 2, in that order, before anything else happens."""
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "":
        # PRD §2.1 names X-User-Role; the scaffold's shorthand is accepted too.
        role = request.headers.get("X-Role")
    if role is None:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = role.strip()
    if role == "" or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-Role must name one of the five declared roles",
        )
    if allowed and role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "role %s is not authorized for this operation" % role,
        )
    user_id = request.headers.get("X-User-ID")
    if user_id is not None:
        user_id = user_id.strip() or None
    return Actor(role, user_id)
