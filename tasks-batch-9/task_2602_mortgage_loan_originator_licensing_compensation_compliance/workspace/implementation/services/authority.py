"""Licence authority (PRD 2.8) and advertising disclosure findings (PRD 3.8).

Every interval here is half-open: a licence covers instant T when
authority_effective_at <= T < expiration_date, and a sponsorship covers T when
effective_at <= T and (relinquished_at is null or T < relinquished_at).
"""
from db import db, sort_key

AUTHORITY_STATUSES = ("ACTIVE", "RENEWAL_PENDING")
RADIO_MAX_CHARS = 300
TRIGGER_TERM = "no closing cost"


def licenses_of(originator_id):
    return [r for r in db.license_registrations.values()
            if r["originator_id"] == originator_id]


def transfers_of(license_id):
    return [r for r in db.sponsorship_transfers.values()
            if r["license_registration_id"] == license_id]


def active_transfer(license_id):
    rows = [r for r in transfers_of(license_id) if r["status"] == "ACTIVE"]
    if not rows:
        return None
    rows.sort(key=sort_key)
    return rows[-1]


def sponsorship_covers(transfer, at):
    if transfer["effective_at"] is None or transfer["effective_at"] > at:
        return False
    relinquished = transfer["relinquished_at"]
    return relinquished is None or at < relinquished


def license_covers(lic, at):
    if lic["status"] not in AUTHORITY_STATUSES:
        return False
    eff = lic["authority_effective_at"]
    if eff is None:
        return False
    return eff <= at and at < lic["expiration_date"]


def license_sponsored(lic, at):
    return any(sponsorship_covers(t, at) for t in transfers_of(lic["id"]))


def authorized_state_codes(originator, at=None):
    """The set of state codes the originator may lawfully act in at instant
    `at` (defaults to the current logical clock), sorted ascending."""
    if at is None:
        at = db.clock
    if originator["employment_status"] != "EMPLOYED":
        return []
    codes = set()
    for lic in licenses_of(originator["id"]):
        if not license_covers(lic, at):
            continue
        if license_sponsored(lic, at):
            codes.add(lic["state_code"])
    return sorted(codes)


def authority_probe(originator, state_code, at=None):
    """Three-stage authority test used when taking and when locking a loan,
    decomposed exactly as PRD 3.4 enumerates it. Returns None when authorised,
    otherwise the error_id, in the fixed order 13 -> 14 -> 15.

      13 ERR_LICENSE_NOT_ACTIVE   no licence row for (originator, state) sits in
                                  ACTIVE or RENEWAL_PENDING
      14 ERR_STATE_NOT_AUTHORIZED such a licence exists but the instant falls
                                  outside its half-open authority interval, or
                                  employment_status is not EMPLOYED
      15 ERR_SPONSORSHIP_REQUIRED the authorising licence has no sponsorship
                                  interval covering the instant
    """
    if at is None:
        at = db.clock
    in_state = [lic for lic in licenses_of(originator["id"])
                if lic["state_code"] == state_code
                and lic["status"] in AUTHORITY_STATUSES]
    if not in_state:
        return "ERR_LICENSE_NOT_ACTIVE"
    covering = [lic for lic in in_state if license_covers(lic, at)]
    if not covering or originator["employment_status"] != "EMPLOYED":
        return "ERR_STATE_NOT_AUTHORIZED"
    if not any(license_sponsored(lic, at) for lic in covering):
        return "ERR_SPONSORSHIP_REQUIRED"
    return None


def authorizing_license(originator_id, state_code, at=None):
    """The licence that actually confers authority for (originator, state)."""
    if at is None:
        at = db.clock
    rows = [lic for lic in licenses_of(originator_id)
            if lic["state_code"] == state_code
            and license_covers(lic, at) and license_sponsored(lic, at)]
    if not rows:
        return None
    rows.sort(key=sort_key)
    return rows[-1]


def publish_authority_probe(advertisement, at=None):
    """Publishing requires authority in every target state (PRD 3.8)."""
    if at is None:
        at = db.clock
    originator = db.originators[advertisement["originator_id"]]
    allowed = set(authorized_state_codes(originator, at))
    for code in sorted(advertisement["target_state_codes"]):
        if code not in allowed:
            return "ERR_STATE_NOT_AUTHORIZED"
    return None


def disclosure_findings(advertisement):
    """Recompute the advertisement's disclosure findings, de-duplicated and
    sorted ascending."""
    originator = db.originators.get(advertisement["originator_id"])
    findings = []
    disclosed_ids = advertisement.get("disclosed_nmls_ids") or []
    disclosed_numbers = advertisement.get("disclosed_license_numbers") or []
    if originator is None or originator["nmls_unique_id"] not in disclosed_ids:
        findings.append("MISSING_NMLS_ID")
    for code in sorted(advertisement.get("target_state_codes") or []):
        candidates = [lic for lic in licenses_of(advertisement["originator_id"])
                      if lic["state_code"] == code
                      and lic["status"] in AUTHORITY_STATUSES]
        if not candidates:
            findings.append("NO_LICENSE_" + code)
            continue
        candidates.sort(key=sort_key)
        chosen = candidates[-1]
        if chosen["license_number"] not in disclosed_numbers:
            findings.append("MISSING_LICENSE_NUMBER_" + code)
    text = advertisement.get("content_text") or ""
    if advertisement["medium"] == "RADIO" and len(text) > RADIO_MAX_CHARS:
        findings.append("RADIO_SCRIPT_TOO_LONG")
    if advertisement["medium"] in ("WEB", "SOCIAL"):
        if TRIGGER_TERM in text.lower() and "APR" not in text:
            findings.append("TRIGGER_TERM_WITHOUT_APR")
    return sorted(set(findings))
