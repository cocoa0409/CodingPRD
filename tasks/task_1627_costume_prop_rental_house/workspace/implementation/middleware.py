"""Auth header extraction, role checks, renter scoping, and lenient body parsing.

Validation priority (PRD 2.9):
  1 auth -> 2 role -> 3 renter scope -> 4 existence -> 5 state -> 6 OCC ->
  7 safety -> 8 referential -> 9 temporal -> 10 capacity -> 11 fiscal ->
  12 generic request shape (ERR_VALIDATION, lowest).
"""

from flask import request

from db import DB, ROLES, parse_date, parse_datetime_iso
from errors import fail


# ---------------------------------------------------------------------------
# Auth / role / scope
# ---------------------------------------------------------------------------

def authenticate():
    """Priority 1: X-User-ID and X-User-Role present; role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or unknown X-User-Role or X-User-ID header")
    return uid, role


def require_roles(role, allowed):
    """Priority 2: role permitted on this endpoint."""
    if role not in allowed:
        fail("ERR_FORBIDDEN", "Role %s is not permitted on this endpoint" % role)


def scope_check(uid, role, renter_id):
    """Priority 3: RenterContact may only act on resources of their own renter."""
    if role == "RenterContact" and renter_id != uid:
        fail("ERR_RENTER_SCOPE_VIOLATION",
             "RenterContact may only act on resources whose renter_id equals X-User-ID")


def renter_id_of_production(production_id):
    p = DB.productions.get(production_id)
    return p["renter_id"] if p else None


def renter_id_of_reservation(reservation_id):
    r = DB.reservations.get(reservation_id)
    return renter_id_of_production(r["production_id"]) if r else None


def renter_id_of_pull_list(pull_list_id):
    pl = DB.pull_lists.get(pull_list_id)
    return renter_id_of_production(pl["production_id"]) if pl else None


def renter_id_of_line(line_id):
    ln = DB.lines.get(line_id)
    return renter_id_of_pull_list(ln["pull_list_id"]) if ln else None


def renter_id_of_fitting(fitting_id):
    f = DB.fittings.get(fitting_id)
    return renter_id_of_line(f["pull_list_line_id"]) if f else None


def renter_id_of_claim(claim_id):
    c = DB.claims.get(claim_id)
    return renter_id_of_line(c["pull_list_line_id"]) if c else None


def renter_id_of_invoice(invoice_id):
    inv = DB.invoices.get(invoice_id)
    return renter_id_of_production(inv["production_id"]) if inv else None


def renter_id_of_cert(cert_id):
    c = DB.certificates.get(cert_id)
    return c["renter_id"] if c else None


# ---------------------------------------------------------------------------
# Lenient body parsing with deferred ERR_VALIDATION (priority 12)
# ---------------------------------------------------------------------------

class BodyReader:
    """Reads fields from the JSON body, collecting shape errors instead of
    raising immediately, so business-rule errors surface first."""

    def __init__(self):
        data = request.get_json(silent=True)
        self.data = data if isinstance(data, dict) else {}
        self.errors = []
        self.bad = set()

    def _mark(self, name, reason):
        self.errors.append("%s: %s" % (name, reason))
        self.bad.add(name)
        return None

    def present(self, name):
        return name in self.data and self.data[name] is not None

    def get_str(self, name, required=True):
        v = self.data.get(name)
        if v is None:
            if required:
                return self._mark(name, "is required")
            return None
        if not isinstance(v, str) or isinstance(v, bool):
            return self._mark(name, "must be a string")
        return v

    def get_int(self, name, required=True):
        v = self.data.get(name)
        if v is None:
            if required:
                return self._mark(name, "is required")
            return None
        if isinstance(v, bool) or not isinstance(v, int):
            return self._mark(name, "must be an integer")
        return v

    def get_num(self, name, required=True):
        v = self.data.get(name)
        if v is None:
            if required:
                return self._mark(name, "is required")
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return self._mark(name, "must be a number")
        return v

    def get_bool(self, name, required=True):
        v = self.data.get(name)
        if v is None:
            if required:
                return self._mark(name, "is required")
            return None
        if not isinstance(v, bool):
            return self._mark(name, "must be a boolean")
        return v

    def get_enum(self, name, allowed, required=True):
        v = self.data.get(name)
        if v is None:
            if required:
                return self._mark(name, "is required")
            return None
        if not isinstance(v, str) or v not in allowed:
            return self._mark(name, "must be one of %s" % ", ".join(allowed))
        return v

    def get_date(self, name, required=True):
        v = self.data.get(name)
        if v is None:
            if required:
                return self._mark(name, "is required")
            return None
        d = parse_date(v)
        if d is None:
            return self._mark(name, "must be an ISO date (YYYY-MM-DD)")
        return d

    def get_datetime(self, name, required=True):
        v = self.data.get(name)
        if v is None:
            if required:
                return self._mark(name, "is required")
            return None
        dt = parse_datetime_iso(v)
        if dt is None:
            return self._mark(name, "must be an ISO 8601 datetime")
        return dt

    def raise_if_errors(self):
        """Priority 12: surface generic request-shape errors last."""
        if self.errors:
            fail("ERR_VALIDATION", "; ".join(self.errors))
