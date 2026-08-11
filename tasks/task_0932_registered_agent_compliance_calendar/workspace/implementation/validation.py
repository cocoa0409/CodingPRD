"""Rung 13 (ERR_INVALID_REQUEST) and rung 14 (ERR_INVALID_ENUM).

THE CLOSED ENUM-ROUTING LIST.  PRD 2.9 rung 14 routes EXACTLY these request
body fields to ERR_INVALID_ENUM and no others:

    entity_type, boi_exempt_class      (legal entity create / patch)
    owner_status                       (beneficial owner patch)
    annual_report_basis, franchise_tax_basis, grace_basis, late_fee_style
                                       (jurisdiction rule publication)
    obligation_type                    (compliance obligation create)
    filing_kind, expedite_tier         (both filing drafts + refile)
    sop_class                          (service-of-process receipt)
    report_kind                        (BOI report draft)
    result                             (name-clearance record-result)
    outcome                            (filings/record-outcome and
                                        boi-reports/record-outcome)

No other field routes here.  Deliberate exclusions, each named:
  * every query-string filter (status, obligation_type, filing_kind,
    lifecycle_status, owner_status, result, sop_class, report_kind,
    registration_kind, state_code, ...) -- PRD 2.3 makes filters exact-match
    narrowing, so an unrecognised filter value narrows to the empty set and
    returns an empty page, never a 4xx;
  * `rebuild_types` on the calendar rebuild -- PRD 3.6 says in so many words
    that a member outside the declared obligation types "is a malformed
    request and is rejected with ERR_INVALID_REQUEST, since rebuild_types is
    not one of the fields that route to ERR_INVALID_ENUM";
  * free-text fields (legal_name, billing_email, provider_name,
    requested_name, fallback_assumed_name, conflicting_name, certificate_number,
    plaintiff_name, court_case_number, rejection_reason, waiver_reason,
    denial_reason, tax_clearance_reference, residential_address, full_name,
    id_document_number) -- unconstrained strings;
  * every numeric / boolean / date / id field -- out-of-range or wrongly typed
    values are rung-13 failures (ERR_INVALID_REQUEST).
"""

from errors import ApiError
import timeutil


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


class Body:
    def __init__(self, payload):
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            _bad("Request body must be a JSON object.")
        self.payload = payload
        self._pending_enums = []

    # -- presence -----------------------------------------------------------
    def has(self, name):
        return name in self.payload and self.payload[name] is not None

    def raw(self, name):
        return self.payload.get(name)

    def _fetch(self, name, required, default):
        if name not in self.payload or self.payload[name] is None:
            if required:
                _bad("Field '%s' is required." % name)
            return default, False
        return self.payload[name], True

    # -- scalar types -------------------------------------------------------
    def string(self, name, required=False, default=None, non_empty=True, max_len=None):
        value, present = self._fetch(name, required, default)
        if not present:
            return value
        if not isinstance(value, str):
            _bad("Field '%s' must be a string." % name)
        if non_empty and not value.strip():
            _bad("Field '%s' must be non-empty." % name)
        if max_len is not None and len(value) > max_len:
            _bad("Field '%s' must be at most %d characters." % (name, max_len))
        return value

    def integer(self, name, required=False, default=None, minimum=None, maximum=None):
        value, present = self._fetch(name, required, default)
        if not present:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            _bad("Field '%s' must be an integer." % name)
        if minimum is not None and value < minimum:
            _bad("Field '%s' must be >= %s." % (name, minimum))
        if maximum is not None and value > maximum:
            _bad("Field '%s' must be <= %s." % (name, maximum))
        return value

    def number(self, name, required=False, default=None, gt=None, maximum=None):
        value, present = self._fetch(name, required, default)
        if not present:
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad("Field '%s' must be a number." % name)
        if gt is not None and not value > gt:
            _bad("Field '%s' must be greater than %s." % (name, gt))
        if maximum is not None and value > maximum:
            _bad("Field '%s' must be <= %s." % (name, maximum))
        return value

    def boolean(self, name, required=False, default=None):
        value, present = self._fetch(name, required, default)
        if not present:
            return value
        if not isinstance(value, bool):
            _bad("Field '%s' must be a boolean." % name)
        return value

    def date(self, name, required=False, default=None):
        value, present = self._fetch(name, required, default)
        if not present:
            return value
        if not isinstance(value, str):
            _bad("Field '%s' must be an ISO date string." % name)
        parsed = timeutil.parse_date(value)
        if parsed is None:
            _bad("Field '%s' must be an ISO date in YYYY-MM-DD form." % name)
        return parsed

    def instant(self, name, required=False, default=None):
        value, present = self._fetch(name, required, default)
        if not present:
            return value
        if not isinstance(value, str):
            _bad("Field '%s' must be an ISO 8601 instant." % name)
        parsed = timeutil.parse_instant(value)
        if parsed is None:
            _bad("Field '%s' must be a valid ISO 8601 instant." % name)
        return parsed

    def state_code(self, name, required=False, default=None):
        value = self.string(name, required=required, default=default)
        if value is None or value is default and name not in self.payload:
            return value
        if not (isinstance(value, str) and len(value) == 2 and value.isalpha() and value.isupper()):
            _bad("Field '%s' must be exactly two uppercase letters." % name)
        return value

    def identifier(self, name, required=False, default=None):
        value, present = self._fetch(name, required, default)
        if not present:
            return value
        if not isinstance(value, str) or not value.strip():
            _bad("Field '%s' must be an id string." % name)
        return value

    def string_list(self, name, required=False, default=None, allowed=None):
        value, present = self._fetch(name, required, default)
        if not present:
            return value
        if not isinstance(value, list):
            _bad("Field '%s' must be a list." % name)
        for member in value:
            if not isinstance(member, str):
                _bad("Field '%s' must contain only strings." % name)
            if allowed is not None and member not in allowed:
                _bad("Field '%s' contains an undeclared member." % name)
        return value

    def bracket_list(self, name, key, default=None):
        """authorized_shares_tiers / gross_receipts_brackets shape check."""
        value, present = self._fetch(name, False, default)
        if not present:
            return list(default or [])
        if not isinstance(value, list):
            _bad("Field '%s' must be a list." % name)
        cleaned = []
        for member in value:
            if not isinstance(member, dict):
                _bad("Field '%s' items must be objects." % name)
            bound = member.get(key)
            if bound is not None and (isinstance(bound, bool) or not isinstance(bound, int)):
                _bad("Field '%s' items need an integer or null '%s'." % (name, key))
            tax = member.get("tax_cents")
            if isinstance(tax, bool) or not isinstance(tax, int):
                _bad("Field '%s' items need an integer 'tax_cents'." % name)
            cleaned.append({key: bound, "tax_cents": tax})
        return cleaned

    # -- rung 14 ------------------------------------------------------------
    def enum(self, name, members, required=False, default=None):
        """Rung 13 presence/type is checked now; membership is DEFERRED to
        check_enums() so that every rung-13 failure anywhere in the body wins
        over any rung-14 failure, as the ladder requires."""
        value, present = self._fetch(name, required, default)
        if not present:
            return value
        if not isinstance(value, str):
            _bad("Field '%s' must be a string." % name)
        self._pending_enums.append((name, value, members))
        return value

    def check_enums(self):
        for name, value, members in self._pending_enums:
            if value not in members:
                raise ApiError(
                    "ERR_INVALID_ENUM",
                    "Field '%s' carries a value that is not a declared member." % name,
                )
        self._pending_enums = []
