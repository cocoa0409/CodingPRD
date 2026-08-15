"""Business logic: fees, name matching, filing-office determination, lapse sweep,
cancellation/termination cascades, filing events, perfection reports, serializers.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import errors
from db import store
from util import add_months, fmt_dt, new_id, normalize_name

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLATERAL_CLASSES = {"GENERAL", "FIXTURE", "TIMBER_TO_BE_CUT", "AS_EXTRACTED"}
REQUEST_KINDS = {"NEW_UCC1", "AMENDMENT", "CONTINUATION", "TERMINATION"}
SERVICE_LEVELS = {"STANDARD", "EXPEDITED"}
AMENDMENT_SCOPES = {"DEBTOR_NAME", "COLLATERAL", "SECURED_PARTY"}
COLLATERAL_OPS = {"ADD", "DELETE", "RESTATE"}
SEARCH_PURPOSES = {"PRE_FILING", "POST_FILING_VERIFICATION"}
REJECTION_REASONS = {
    "NAME_MISMATCH", "FEE_INCORRECT", "WRONG_OFFICE",
    "MISSING_SIGNATURE", "DUPLICATE_FILING", "OTHER",
}
REPORT_MODES = {"AS_OF_NOW", "FORWARD_PROJECTION"}
NAME_RULES = {"DL_SAFE_HARBOR", "LEGAL_NAME_ONLY"}
DEBTOR_TYPES = {"ORGANIZATION", "INDIVIDUAL"}

KIND_FEE_DELTA_CENTS = {"NEW_UCC1": 0, "AMENDMENT": 1000, "CONTINUATION": 1500, "TERMINATION": 500}
SUPERGENERIC_COLLATERAL = {"ALL ASSETS", "ALL PERSONAL PROPERTY", "ALL ASSETS OF DEBTOR"}

# Request states that count as "open" for the open_ucc3_request_count ledger.
OPEN_REQUEST_STATES = {"DRAFT_INTAKE", "IN_REVIEW", "READY", "IN_PROCESS", "CORRECTION_REQUIRED"}
# States eligible for cascade cancellation (IN_PROCESS is never cascade-cancelled).
CASCADE_OPEN_STATES = {"DRAFT_INTAKE", "IN_REVIEW", "READY", "CORRECTION_REQUIRED"}

REQUEST_KIND_TO_FILING_KIND = {
    "NEW_UCC1": "INITIAL",
    "AMENDMENT": "AMENDMENT",
    "CONTINUATION": "CONTINUATION",
    "TERMINATION": "TERMINATION",
}

EFFECTIVENESS_MONTHS = 60
CONTINUATION_WINDOW_MONTHS = 6
REFILE_WINDOW_DAYS = 30
SEARCH_FRESHNESS_DAYS = 90


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def profile_by_code(state_code):
    return store.jurisdiction_by_code.get(state_code)


def touch(entity):
    """Every mutation refreshes updated_at and increments version."""
    entity["updated_at"] = store.clock
    entity["version"] = entity.get("version", 0) + 1


def stamp_new(entity):
    entity["created_at"] = store.clock
    entity["updated_at"] = store.clock
    entity["version"] = 1
    return entity


def append_event(filing, event_type, detail=None):
    ev = {
        "id": new_id(),
        "ucc_filing_id": filing["id"],
        "event_type": event_type,
        "event_detail": detail or {},
        "occurred_at": store.clock,
        "created_at": store.clock,
    }
    store.events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def determine_filing_office(profile, collateral_class, county_name):
    """COUNTY iff collateral_class is in the profile's county classes; then the
    county_name presence/membership rules apply."""
    if collateral_class in (profile["county_filing_collateral_classes"] or []):
        if not county_name:
            raise errors.err_county_required()
        if county_name not in (profile["county_names"] or []):
            raise errors.err_county_not_in_jurisdiction()
        return "COUNTY"
    return "STATE"


def name_of_record(debtor, profile):
    """Return (name_of_record_or_None, name_rule_applied)."""
    if debtor["debtor_type"] == "ORGANIZATION":
        return debtor["legal_name"], "LEGAL_NAME_ONLY"
    rule = profile["individual_name_rule"] if profile else "LEGAL_NAME_ONLY"
    if rule == "DL_SAFE_HARBOR":
        return debtor["drivers_license_name"], "DL_SAFE_HARBOR"
    return debtor["legal_name"], "LEGAL_NAME_ONLY"


def compute_fee_cents(profile, req):
    """Single pinned formula used by both the QUOTED (approve) and CHARGED (submit)
    variants; the variants differ only in which profile values they read."""
    subtotal = (
        profile["base_fee_cents"]
        + profile["per_additional_debtor_fee_cents"] * req["additional_debtor_count"]
        + (profile["county_surcharge_cents"] if req.get("filing_office") == "COUNTY" else 0)
        + KIND_FEE_DELTA_CENTS[req["kind"]]
    )
    if req.get("service_level") == "EXPEDITED":
        # Multiplier applied once to the integer subtotal; single round-half-up.
        return int((Decimal(subtotal) * Decimal("1.5")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return subtotal


# ---------------------------------------------------------------------------
# Cascades and sweeps
# ---------------------------------------------------------------------------

def withdraw_draft_attempts(req):
    for f in store.filings.values():
        if f["filing_request_id"] == req["id"] and f["effectiveness_status"] == "DRAFT":
            f["effectiveness_status"] = "WITHDRAWN"
            touch(f)
            append_event(f, "WITHDRAWN", {})


def decrement_root_ucc3_count(root):
    root["open_ucc3_request_count"] = max(0, root["open_ucc3_request_count"] - 1)
    touch(root)


def cancel_request(req, reason):
    """Shared cancellation path (client-initiated and cascade)."""
    req["status"] = "CANCELLED"
    req["cancel_reason"] = reason
    touch(req)
    withdraw_draft_attempts(req)
    if req["kind"] != "NEW_UCC1":
        root = store.filings.get(req["target_filing_id"])
        if root is not None:
            decrement_root_ucc3_count(root)


def lapse_if_due(filing):
    """ACTIVE -> LAPSED when expiration_at <= now (boundary lapses), with the
    continuation-request cascade."""
    if (
        filing["effectiveness_status"] == "ACTIVE"
        and filing["expiration_at"] is not None
        and filing["expiration_at"] <= store.clock
    ):
        filing["effectiveness_status"] = "LAPSED"
        touch(filing)
        append_event(filing, "LAPSED", {"expiration_at": fmt_dt(filing["expiration_at"])})
        for req in list(store.filing_requests.values()):
            if (
                req["kind"] == "CONTINUATION"
                and req["target_filing_id"] == filing["id"]
                and req["status"] in CASCADE_OPEN_STATES
            ):
                cancel_request(req, "TARGET_LAPSED")


def lapse_sweep():
    for f in list(store.filings.values()):
        lapse_if_due(f)


# ---------------------------------------------------------------------------
# Perfection report (PRD section 3.8)
# ---------------------------------------------------------------------------

def generate_perfection_report(client_id, mode, horizon_days):
    lapse_sweep()
    now = store.clock
    horizon = timedelta(days=horizon_days)
    # The portfolio universe is the client's INITIAL filings (UCC-3 attempts are
    # transactions on a root and are never counted as separate line items).
    universe = [
        f for f in store.filings.values()
        if f["filing_kind"] == "INITIAL"
        and store.filing_requests[f["filing_request_id"]]["client_id"] == client_id
    ]

    def is_active(f):
        return f["effectiveness_status"] == "ACTIVE"

    def is_reflected(f):
        return f["reflection_status"] == "REFLECTED"

    def exposure(filings):
        return sum(f["secured_amount_cents"] for f in filings)

    lapsed = [f for f in universe if f["effectiveness_status"] == "LAPSED"]
    terminated = [f for f in universe if f["effectiveness_status"] == "TERMINATED"]

    if mode == "AS_OF_NOW":
        as_of = now
        active = [f for f in universe if is_active(f)]
        perfected = [f for f in active if is_reflected(f)]
        unreflected = [f for f in active if f["reflection_status"] in ("UNVERIFIED", "DISCREPANCY")]
        expiring = [
            f for f in active
            if f["expiration_at"] is not None and f["expiration_at"] <= now + horizon
        ]
        projected = []
    else:  # FORWARD_PROJECTION
        as_of = now + horizon
        projected = [
            f for f in universe
            if is_active(f) and f["expiration_at"] is not None and f["expiration_at"] <= as_of
        ]
        active = [
            f for f in universe
            if is_active(f) and f["expiration_at"] is not None and f["expiration_at"] > as_of
        ]
        perfected = [f for f in active if is_reflected(f)]
        unreflected = [f for f in active if not is_reflected(f)]
        expiring = projected

    report = {
        "id": new_id(),
        "client_id": client_id,
        "mode": mode,
        "horizon_days": horizon_days,
        "as_of": as_of,
        "active_count": len(active),
        "perfected_count": len(perfected),
        "unreflected_count": len(unreflected),
        "expiring_within_horizon_count": len(expiring),
        "lapsed_count": len(lapsed),
        "terminated_count": len(terminated),
        "projected_lapsed_count": len(projected),
        "perfected_exposure_cents": exposure(perfected),
        "unperfected_exposure_cents": exposure(unreflected),
        "projected_lapsed_exposure_cents": exposure(projected),
        "created_at": store.clock,
    }
    store.reports[report["id"]] = report
    return report


# ---------------------------------------------------------------------------
# Serializers (datetimes are stored internally as datetime, rendered as
# second-precision ISO 8601 UTC strings)
# ---------------------------------------------------------------------------

def client_json(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "status": c["status"],
        "fees_charged_total_cents": c["fees_charged_total_cents"],
        "fees_refunded_total_cents": c["fees_refunded_total_cents"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def jurisdiction_json(p):
    return {
        "id": p["id"],
        "state_code": p["state_code"],
        "base_fee_cents": p["base_fee_cents"],
        "per_additional_debtor_fee_cents": p["per_additional_debtor_fee_cents"],
        "county_surcharge_cents": p["county_surcharge_cents"],
        "county_filing_collateral_classes": list(p["county_filing_collateral_classes"]),
        "county_names": list(p["county_names"]),
        "individual_name_rule": p["individual_name_rule"],
        "expedited_daily_capacity": p["expedited_daily_capacity"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def debtor_json(d):
    return {
        "id": d["id"],
        "client_id": d["client_id"],
        "debtor_type": d["debtor_type"],
        "legal_name": d["legal_name"],
        "jurisdiction_of_formation": d["jurisdiction_of_formation"],
        "drivers_license_name": d["drivers_license_name"],
        "created_at": fmt_dt(d["created_at"]),
        "updated_at": fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def secured_party_json(s):
    return {
        "id": s["id"],
        "client_id": s["client_id"],
        "name": s["name"],
        "reference_code": s["reference_code"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def request_json(r):
    return {
        "id": r["id"],
        "client_id": r["client_id"],
        "kind": r["kind"],
        "debtor_id": r["debtor_id"],
        "secured_party_id": r["secured_party_id"],
        "jurisdiction_code": r["jurisdiction_code"],
        "collateral_class": r["collateral_class"],
        "county_name": r["county_name"],
        "service_level": r["service_level"],
        "additional_debtor_count": r["additional_debtor_count"],
        "fee_authorization_cents": r["fee_authorization_cents"],
        "target_filing_id": r["target_filing_id"],
        "supporting_search_id": r["supporting_search_id"],
        "filing_office": r["filing_office"],
        "quoted_fee_cents": r["quoted_fee_cents"],
        "intake_submitted_by_user_id": r["intake_submitted_by_user_id"],
        "status": r["status"],
        "cancel_reason": r["cancel_reason"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def filing_json(f):
    return {
        "id": f["id"],
        "filing_request_id": f["filing_request_id"],
        "filing_kind": f["filing_kind"],
        "root_filing_id": f["root_filing_id"],
        "supersedes_attempt_id": f["supersedes_attempt_id"],
        "debtor_id": f["debtor_id"],
        "secured_party_id": f["secured_party_id"],
        "jurisdiction_code": f["jurisdiction_code"],
        "filing_office": f["filing_office"],
        "county_name": f["county_name"],
        "debtor_name_on_filing": f["debtor_name_on_filing"],
        "collateral_text": f["collateral_text"],
        "amendment_scope": f["amendment_scope"],
        "collateral_change_op": f["collateral_change_op"],
        "secured_amount_cents": f["secured_amount_cents"],
        "charged_fee_cents": f["charged_fee_cents"],
        "filing_number": f["filing_number"],
        "submitted_at": fmt_dt(f["submitted_at"]),
        "filed_at": fmt_dt(f["filed_at"]),
        "rejected_at": fmt_dt(f["rejected_at"]),
        "rejection_reason_code": f["rejection_reason_code"],
        "rejection_note": f["rejection_note"],
        "expiration_at": fmt_dt(f["expiration_at"]),
        "effectiveness_status": f["effectiveness_status"],
        "reflection_status": f["reflection_status"],
        "open_ucc3_request_count": f["open_ucc3_request_count"],
        "created_at": fmt_dt(f["created_at"]),
        "updated_at": fmt_dt(f["updated_at"]),
        "version": f["version"],
    }


def search_json(s):
    return {
        "id": s["id"],
        "client_id": s["client_id"],
        "purpose": s["purpose"],
        "debtor_id": s["debtor_id"],
        "jurisdiction_code": s["jurisdiction_code"],
        "county_name": s["county_name"],
        "subject_filing_id": s["subject_filing_id"],
        "status": s["status"],
        "through_date": fmt_dt(s["through_date"]),
        "prior_lien_count": s["prior_lien_count"],
        "priority_position_of_subject": s["priority_position_of_subject"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def hit_json(h):
    return {
        "id": h["id"],
        "lien_search_id": h["lien_search_id"],
        "found_debtor_name": h["found_debtor_name"],
        "found_filing_number": h["found_filing_number"],
        "found_filed_at": fmt_dt(h["found_filed_at"]),
        "secured_party_name": h["secured_party_name"],
        "hit_kind": h["hit_kind"],
        "is_subject_filing": h["is_subject_filing"],
        "created_at": fmt_dt(h["created_at"]),
    }


def report_json(r):
    return {
        "id": r["id"],
        "client_id": r["client_id"],
        "mode": r["mode"],
        "horizon_days": r["horizon_days"],
        "as_of": fmt_dt(r["as_of"]),
        "active_count": r["active_count"],
        "perfected_count": r["perfected_count"],
        "unreflected_count": r["unreflected_count"],
        "expiring_within_horizon_count": r["expiring_within_horizon_count"],
        "lapsed_count": r["lapsed_count"],
        "terminated_count": r["terminated_count"],
        "projected_lapsed_count": r["projected_lapsed_count"],
        "perfected_exposure_cents": r["perfected_exposure_cents"],
        "unperfected_exposure_cents": r["unperfected_exposure_cents"],
        "projected_lapsed_exposure_cents": r["projected_lapsed_exposure_cents"],
        "created_at": fmt_dt(r["created_at"]),
    }


def event_json(e):
    return {
        "id": e["id"],
        "ucc_filing_id": e["ucc_filing_id"],
        "event_type": e["event_type"],
        "event_detail": e["event_detail"],
        "occurred_at": fmt_dt(e["occurred_at"]),
        "created_at": fmt_dt(e["created_at"]),
    }
