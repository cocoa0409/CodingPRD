"""Business logic: scoring, fees, calibration, scheduling, sweeps, cascades."""

from decimal import Decimal, ROUND_HALF_UP

import db
from db import days, get_now, touch
from errors import (
    ApiError,
    ERR_INVALID_AUDIT_WINDOW,
    ERR_AUDITOR_WINDOW_OVERLAP,
    ERR_AUDIT_WINDOW_TOO_CLOSE,
    ERR_SCOPE_CATEGORY_UNSUPPORTED,
)

# ---------------------------------------------------------------------------
# §2.9 Audit scoring — integer arithmetic, floor halving, clamped at 0
# ---------------------------------------------------------------------------

_NC_WEIGHTS = {"CRITICAL": 25, "MAJOR": 10, "MINOR": 3}


def ncs_of_audit(audit_id):
    return [n for n in db.nonconformities.values() if n["audit_id"] == audit_id]


def compute_reported_score(audit_id):
    deduction = sum(_NC_WEIGHTS[n["grade"]] for n in ncs_of_audit(audit_id))
    return max(0, 100 - deduction)


def compute_resolved_score(audit_id):
    deduction = 0
    for nc in ncs_of_audit(audit_id):
        w = _NC_WEIGHTS[nc["grade"]]
        deduction += (w // 2) if nc["status"] == "CLOSED" else w
    return max(0, 100 - deduction)


# ---------------------------------------------------------------------------
# §2.9 Fees — Decimal, round-per-line-then-sum, ROUND_HALF_UP
# ---------------------------------------------------------------------------


def _rh2(value):
    """Round to 2 decimal places, half-up. Returns a float for the wire."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fee_quote(scheme, categories):
    return _rh2(
        Decimal(str(scheme["base_fee"]))
        + Decimal(len(categories)) * Decimal(str(scheme["per_category_fee"]))
    )


def fee_invoice(scheme, categories, actual_days, audit_type):
    total = Decimal(str(_rh2(scheme["base_fee"])))
    for cat in categories:
        mult = (
            Decimal(str(scheme["high_risk_multiplier"]))
            if cat.get("risk_tier") == "HIGH"
            else Decimal("1.0")
        )
        line = Decimal(str(scheme["per_category_fee"])) * mult
        total += Decimal(str(_rh2(line)))
    uplift = (
        Decimal(str(scheme["unannounced_uplift_pct"]))
        if audit_type == "UNANNOUNCED"
        else Decimal("0")
    )
    day_line = (
        Decimal(actual_days) * Decimal(str(scheme["day_rate"])) * (Decimal("1") + uplift)
    )
    total += Decimal(str(_rh2(day_line)))
    return float(total)


def compute_audit_fee(scheme, actual_days, audit_type):
    uplift = (
        Decimal(str(scheme["unannounced_uplift_pct"]))
        if audit_type == "UNANNOUNCED"
        else Decimal("0")
    )
    line = (
        Decimal(actual_days) * Decimal(str(scheme["day_rate"])) * (Decimal("1") + uplift)
    )
    return _rh2(line)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def application_of(audit):
    return db.applications.get(audit["application_id"])


def scheme_of_application(application):
    return db.schemes.get(application["scheme_id"]) if application else None


def scheme_of_audit(audit):
    return scheme_of_application(application_of(audit))


def client_id_of_audit(audit):
    application = application_of(audit)
    return application["client_id"] if application else None


def find_certificate_for_client_scheme(client_id, scheme_id, statuses=None):
    """Certificates for (client, scheme), optionally filtered by status.
    Multiple may exist historically; returns them in created_at order."""
    out = [
        c
        for c in db.certificates.values()
        if c["client_id"] == client_id and c["scheme_id"] == scheme_id
    ]
    if statuses is not None:
        out = [c for c in out if c["status"] in statuses]
    out.sort(key=lambda c: c["created_at"])
    return out


def listing_for_certificate(certificate_id):
    for listing in db.directory_listings.values():
        if listing["certificate_id"] == certificate_id:
            return listing
    return None


def audits_for_client_scheme(client_id, scheme_id):
    """All audits whose application belongs to (client, scheme), in
    sequence_number ASC order."""
    out = []
    for audit in db.audits.values():
        application = application_of(audit)
        if (
            application
            and application["client_id"] == client_id
            and application["scheme_id"] == scheme_id
        ):
            out.append(audit)
    # sequence_number is unique within one (client, scheme) chain.
    out.sort(key=lambda a: a["sequence_number"])
    return out


# ---------------------------------------------------------------------------
# §3.2 Auditor calibration & workload
# ---------------------------------------------------------------------------


def compute_calibration(auditor_id):
    """Returns (calibration_status, last_witnessed_on).

    CURRENT iff a PASS witness audit exists with witnessed_on >=
    now - min(scheme.witness_validity_days). The boundary is inclusive.
    FAIL witness audits never count. last_witnessed_on is the most recent
    PASS witness date (null when none). When no scheme exists, the minimum
    window over an empty set is undefined and no witness can qualify.
    """
    passes = [
        w
        for w in db.witness_audits.values()
        if w["auditor_id"] == auditor_id and w["result"] == "PASS"
    ]
    last_witnessed = None
    if passes:
        last_witnessed = max(w["witnessed_on"] for w in passes)
    status = "LAPSED"
    if db.schemes and passes:
        min_validity = min(s["witness_validity_days"] for s in db.schemes.values())
        cutoff = get_now() - days(min_validity)
        if any(w["witnessed_on"] >= cutoff for w in passes):
            status = "CURRENT"
    return status, last_witnessed


def compute_active_audit_count(auditor_id):
    return sum(
        1
        for a in db.audits.values()
        if a.get("auditor_id") == auditor_id
        and a["status"] in ("SCHEDULED", "IN_PROGRESS")
    )


def refresh_auditor(auditor):
    status, last_witnessed = compute_calibration(auditor["id"])
    auditor["calibration_status"] = status
    auditor["last_witnessed_on"] = last_witnessed
    auditor["active_audit_count"] = compute_active_audit_count(auditor["id"])


def serialize_auditor(auditor):
    refresh_auditor(auditor)
    return db.serialize(auditor, "auditors")


# ---------------------------------------------------------------------------
# §2.8 Window geometry
# ---------------------------------------------------------------------------


def window_bounds_days(audit_type, scheme):
    if audit_type == "UNANNOUNCED":
        return None, scheme["unannounced_min_window_days"]
    return scheme["announced_max_window_days"], None


def validate_window(audit_type, scheme, window_start, window_end, check_past=False):
    """Well-formedness rules of §2.8, all rejected with ERR_INVALID_AUDIT_WINDOW."""
    if window_start is None or window_end is None:
        raise ApiError(
            ERR_INVALID_AUDIT_WINDOW,
            "window_start and window_end must be valid ISO 8601 UTC timestamps",
            422,
        )
    if not window_start < window_end:
        raise ApiError(
            ERR_INVALID_AUDIT_WINDOW,
            "window_start must be strictly earlier than window_end",
            422,
        )
    length = window_end - window_start
    max_days, min_days = window_bounds_days(audit_type, scheme)
    if max_days is not None and length > days(max_days):
        raise ApiError(
            ERR_INVALID_AUDIT_WINDOW,
            "Announced audit window may span at most %d days" % max_days,
            422,
        )
    if min_days is not None and length < days(min_days):
        raise ApiError(
            ERR_INVALID_AUDIT_WINDOW,
            "Unannounced audit window must span at least %d days" % min_days,
            422,
        )
    if check_past and window_end < get_now():
        raise ApiError(
            ERR_INVALID_AUDIT_WINDOW, "window_end may not be in the past", 422
        )


def windows_intersect(s1, e1, s2, e2):
    """Inclusive-boundary intersection: overlap iff s1 <= e2 AND s2 <= e1."""
    return s1 <= e2 and s2 <= e1


def check_auditor_window_overlap(auditor_id, window_start, window_end, exclude_audit_id):
    for other in db.audits.values():
        if other["id"] == exclude_audit_id:
            continue
        if other.get("auditor_id") != auditor_id:
            continue
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if windows_intersect(
            window_start, window_end, other["window_start"], other["window_end"]
        ):
            raise ApiError(
                ERR_AUDITOR_WINDOW_OVERLAP,
                "Audit window intersects another committed audit window of this auditor",
                409,
            )


def check_min_gap(application, window_start, window_end, exclude_audit_id):
    """Sibling audits of the same client+scheme must be separated by at least
    scheme.min_audit_gap_days whenever one window ends before the other begins."""
    scheme = db.schemes.get(application["scheme_id"])
    gap = days(scheme["min_audit_gap_days"])
    for other in audits_for_client_scheme(application["client_id"], application["scheme_id"]):
        if other["id"] == exclude_audit_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        if other["window_end"] <= window_start:
            if window_start - other["window_end"] < gap:
                raise ApiError(
                    ERR_AUDIT_WINDOW_TOO_CLOSE,
                    "Window violates the minimum gap versus a sibling audit",
                    409,
                )
        elif window_end <= other["window_start"]:
            if other["window_start"] - window_end < gap:
                raise ApiError(
                    ERR_AUDIT_WINDOW_TOO_CLOSE,
                    "Window violates the minimum gap versus a sibling audit",
                    409,
                )


# ---------------------------------------------------------------------------
# Category support
# ---------------------------------------------------------------------------


def check_categories_supported(scheme, categories):
    supported = set(scheme["supported_category_codes"])
    for cat in categories:
        if cat.get("category_code") not in supported:
            raise ApiError(
                ERR_SCOPE_CATEGORY_UNSUPPORTED,
                "Category code %s is not supported by the scheme"
                % cat.get("category_code"),
                422,
            )


# ---------------------------------------------------------------------------
# §3.6 Next-audit projection
# ---------------------------------------------------------------------------


def create_next_audit(scheme, decided_audit):
    seq = decided_audit["sequence_number"] + 1
    audit_type = (
        "UNANNOUNCED" if seq % scheme["unannounced_every_n"] == 0 else "SURVEILLANCE"
    )
    window_start = max(
        decided_audit["decided_at"] + days(14),
        decided_audit["window_end"] + days(scheme["min_audit_gap_days"]),
    )
    window_days = (
        scheme["unannounced_min_window_days"]
        if audit_type == "UNANNOUNCED"
        else scheme["announced_max_window_days"]
    )
    window_end = window_start + days(window_days)
    now = get_now()
    audit = {
        "id": db.new_id(),
        "application_id": decided_audit["application_id"],
        "auditor_id": None,
        "decision_maker_id": None,
        "sequence_number": seq,
        "audit_type": audit_type,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "reported_score": None,
        "resolved_score": None,
        "audit_fee": None,
        "actual_days": None,
        "decision_outcome": None,
        "started_at": None,
        "reported_at": None,
        "decided_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.audits[audit["id"]] = audit
    return audit


# ---------------------------------------------------------------------------
# §2.10 Certificate status propagation / directory listing
# ---------------------------------------------------------------------------


def scope_summary(categories):
    return ",".join(sorted(c["category_code"] for c in categories))


def unlist_listing(certificate_id, when):
    listing = listing_for_certificate(certificate_id)
    if listing and listing["status"] != "UNLISTED":
        listing["status"] = "UNLISTED"
        listing["unlisted_at"] = when
        touch(listing)


def list_listing(certificate_id, when):
    listing = listing_for_certificate(certificate_id)
    if listing and listing["status"] != "LISTED":
        listing["status"] = "LISTED"
        listing["listed_at"] = when
        touch(listing)


def suspend_certificate(certificate, reason, when):
    certificate["status"] = "SUSPENDED"
    certificate["suspension_reason"] = reason
    certificate["status_changed_at"] = when
    touch(certificate)
    unlist_listing(certificate["id"], when)


def reinstate_certificate(certificate, when):
    certificate["status"] = "ACTIVE"
    certificate["suspension_reason"] = None
    certificate["status_changed_at"] = when
    touch(certificate)
    list_listing(certificate["id"], when)


def withdraw_certificate(certificate, when):
    certificate["status"] = "WITHDRAWN"
    certificate["status_changed_at"] = when
    touch(certificate)
    unlist_listing(certificate["id"], when)


def expire_certificate(certificate, when):
    certificate["status"] = "EXPIRED"
    certificate["status_changed_at"] = when
    touch(certificate)
    unlist_listing(certificate["id"], when)


def issue_certificate(scheme, application, audit, decided_at):
    certificate = {
        "id": db.new_id(),
        "client_id": application["client_id"],
        "scheme_id": application["scheme_id"],
        "application_id": application["id"],
        "audit_id": audit["id"],
        "certificate_number": db.next_certificate_number(),
        "product_categories": application["product_categories"],
        "scope_text": application["scope_text"],
        "valid_from": decided_at,
        "valid_to": decided_at + days(scheme["cert_validity_days"]),
        "status": "ACTIVE",
        "suspension_reason": None,
        "status_changed_at": decided_at,
        "final_fee": fee_invoice(
            scheme,
            application["product_categories"],
            audit["actual_days"],
            audit["audit_type"],
        ),
        "created_at": get_now(),
        "updated_at": get_now(),
        "version": 1,
    }
    db.certificates[certificate["id"]] = certificate
    client = db.clients.get(application["client_id"])
    listing = {
        "id": db.new_id(),
        "certificate_id": certificate["id"],
        "client_name": client["name"] if client else None,
        "scheme_code": scheme["code"],
        "scope_summary": scope_summary(certificate["product_categories"]),
        "status": "LISTED",
        "listed_at": decided_at,
        "unlisted_at": None,
        "created_at": get_now(),
        "updated_at": get_now(),
        "version": 1,
    }
    db.directory_listings[listing["id"]] = listing
    return certificate


# ---------------------------------------------------------------------------
# §2.6 Scheduled sweeps — fired when the logical clock is set
# ---------------------------------------------------------------------------


def run_sweeps():
    now = get_now()

    # overdue_nc_sweep: OPEN NCs past deadline, created_at ASC.
    candidates = [
        n
        for n in db.nonconformities.values()
        if n["status"] == "OPEN" and now > n["deadline"]
    ]
    # created_at ASC (PRD §2.6); stable sort keeps creation order on ties.
    candidates.sort(key=lambda n: n["created_at"])
    for nc in candidates:
        nc["status"] = "OVERDUE"
        touch(nc)
        audit = db.audits.get(nc["audit_id"])
        application = application_of(audit) if audit else None
        if not application:
            continue
        # An already-SUSPENDED certificate is not re-transitioned (no drift).
        active = find_certificate_for_client_scheme(
            application["client_id"], application["scheme_id"], statuses={"ACTIVE"}
        )
        if active:
            suspend_certificate(active[0], "NC_OVERDUE", now)

    # certificate_expiry_sweep: ACTIVE/SUSPENDED past valid_to, created_at ASC.
    expiring = [
        c
        for c in db.certificates.values()
        if c["status"] in ("ACTIVE", "SUSPENDED") and now > c["valid_to"]
    ]
    expiring.sort(key=lambda c: c["created_at"])
    for certificate in expiring:
        expire_certificate(certificate, now)
