"""Derived-state engine: privilege derivation, posture recompute + cascade,
packet readiness, item invalidation, unit counters, completion expiry."""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import db
from services.core import all_entities, create_entity, touch
from util import add_months, parse_date_loose, parse_time_loose

COMPACT_STATES = ["AZ", "CO", "FL", "GA", "MD", "NC", "TN", "TX"]
FACILITY_STATE = "TX"
PSV_VALIDITY_DAYS = 180
RENEWAL_WINDOW_DAYS = 60
SCHEDULING_HORIZON_DAYS = 90
WEEKLY_HOUR_CAP_MINUTES = 3600
MIN_ACTIVE_DAYS = {"REPRIMAND": 0, "PROBATION": 90, "SUSPENSION": 30, "REVOCATION": 365}
CRITICAL_DAYS = 30
WARNING_DAYS = 60
CRITICAL_CAP = Decimal("0.49")
FISCAL_MONTH_DAY = (6, 30)

# Packet item catalog: item_type -> (weight, critical)
ITEM_DEFS = {
    "LICENSE_VERIFICATION": (40, True),
    "BLS": (20, True),
    "ACLS": (20, True),
    "COMPETENCY_ANNUAL": (15, True),
    "ATTESTATION": (5, False),
}
# Fixed materialization order; ACLS conditional on the target unit.
ITEM_ORDER = ["LICENSE_VERIFICATION", "BLS", "ACLS", "COMPETENCY_ANNUAL", "ATTESTATION"]

CREDIT = {
    "VERIFIED": Decimal("1"),
    "WAIVED": Decimal("0.5"),
    "SUBMITTED": Decimal("0.25"),
    "MISSING": Decimal("0"),
    "INVALIDATED": Decimal("0"),
}


# --- Privilege derivation -----------------------------------------------------

def _home_license(nurse):
    candidates = [
        lic for lic in all_entities("licenses")
        if lic["nurse_id"] == nurse["id"]
        and lic["status"] == "ACTIVE"
        and lic["state_code"] == nurse["primary_state_of_residence"]
    ]
    if not candidates:
        return None
    # expires_on DESC (ISO strings sort lexicographically), tie-break created_at ASC
    # (insertion sequence preserved by initial seq ordering).
    candidates.sort(key=lambda lic: lic["_seq"])
    candidates.sort(key=lambda lic: lic["expires_on"], reverse=True)
    return candidates[0]


def derive_privilege(nurse, reason=None):
    """privilege_scope_determination. Returns (changed, status, scope, home).

    Embedded derivations append a PrivilegeEvaluation only when status or scope
    changed. The explicit endpoint appends unconditionally (handled by caller).
    """
    licenses = [lic for lic in all_entities("licenses") if lic["nurse_id"] == nurse["id"]]
    home = _home_license(nurse)
    open_privilege_encumbrance = any(
        d for d in all_entities("disciplines")
        if d["nurse_id"] == nurse["id"]
        and d["scope"] == "PRIVILEGE"
        and d["status"] == "ADJUDICATED"
    )
    psor = nurse["primary_state_of_residence"]
    if home and home["multistate_flag"] and psor in COMPACT_STATES and not open_privilege_encumbrance:
        status = "ELIGIBLE_MULTISTATE"
        scope = sorted(COMPACT_STATES)
    elif home and home["multistate_flag"] and psor in COMPACT_STATES and open_privilege_encumbrance:
        status = "SINGLE_STATE_ONLY"
        scope = [psor]
    else:
        active_states = sorted({lic["state_code"] for lic in licenses if lic["status"] == "ACTIVE"})
        status = "SINGLE_STATE_ONLY" if active_states else "NONE"
        scope = active_states
    home_id = home["id"] if home else None
    changed = (status != nurse["multistate_privilege_status"]) or (scope != nurse["practice_scope"])
    if changed:
        nurse["multistate_privilege_status"] = status
        nurse["practice_scope"] = scope
        if reason is not None:
            append_evaluation(nurse, reason, status, scope, home_id)
    return changed, status, scope, home_id


def append_evaluation(nurse, reason, status, scope, home_id):
    return create_entity("evaluations", {
        "nurse_id": nurse["id"],
        "trigger_reason": reason,
        "resulting_status": status,
        "resulting_scope": list(scope),
        "home_license_id": home_id,
    })


# --- Credential posture --------------------------------------------------------

def compute_posture(nurse):
    """credential_posture_evaluation ladder (pinned order; unit set snapshotted first)."""
    # (1) Unit-derived requirement snapshot: units holding >= 1 SCHEDULED/IN_PROGRESS
    # shift of this nurse at this instant.
    unit_ids = {
        s["unit_id"] for s in all_entities("shifts")
        if s["nurse_id"] == nurse["id"] and s["status"] in ("SCHEDULED", "IN_PROGRESS")
    }
    unit_certs = set()
    for uid in unit_ids:
        unit = db.STORES["units"].get(uid)
        if unit:
            unit_certs.update(unit["required_cert_types"])

    # (3a) lifecycle gate
    if nurse["status"] != "ACTIVE":
        return "SCHEDULING_SUSPENDED"
    # (3b) adjudicated discipline gate
    if any(
        d for d in all_entities("disciplines")
        if d["nurse_id"] == nurse["id"]
        and d["status"] == "ADJUDICATED"
        and d["action_type"] in ("PROBATION", "SUSPENSION", "REVOCATION")
    ):
        return "PRACTICE_RESTRICTED"
    # (3c) practice-authority gate
    if FACILITY_STATE not in nurse["practice_scope"]:
        return "SCHEDULING_SUSPENDED"
    # (3d) deficit check
    for cert_type in ({"BLS"} | unit_certs):
        if not any(
            c for c in all_entities("certifications")
            if c["nurse_id"] == nurse["id"] and c["cert_type"] == cert_type and c["status"] == "ACTIVE"
        ):
            return "SCHEDULING_SUSPENDED"
    for req in all_entities("requirements"):
        if req["mandatory"] and nurse["employment_type"] in req["applies_to"]:
            if not any(
                cp for cp in all_entities("completions")
                if cp["nurse_id"] == nurse["id"]
                and cp["requirement_id"] == req["id"]
                and cp["status"] == "CURRENT"
            ):
                return "SCHEDULING_SUSPENDED"
    # (3e)
    return "CLEAR"


def recompute_posture(nurse, touch_nurse=True):
    """Persist a changed posture and fire the cascade exactly once on flips to
    non-CLEAR. Returns (changed, shifts_auto_cancelled, packets_voided)."""
    new_posture = compute_posture(nurse)
    if new_posture == nurse["credential_posture"]:
        return False, 0, 0
    nurse["credential_posture"] = new_posture
    if touch_nurse:
        touch(nurse)
    cancelled = 0
    voided = 0
    if new_posture != "CLEAR":
        now = db.logical_now()
        for shift in all_entities("shifts"):
            if (shift["nurse_id"] == nurse["id"] and shift["status"] == "SCHEDULED"
                    and parse_time_loose(shift["starts_at"]) > now):
                shift["status"] = "AUTO_CANCELLED"
                shift["cancel_reason"] = "POSTURE_" + new_posture
                touch(shift)
                unit_decrement(db.STORES["units"].get(shift["unit_id"]), shift["hours"])
                cancelled += 1
        for packet in all_entities("packets"):
            if packet["nurse_id"] == nurse["id"] and packet["status"] == "APPROVED":
                packet["status"] = "VOIDED"
                touch(packet)
                voided += 1
    return True, cancelled, voided


# --- Unit counters --------------------------------------------------------------

def _dec2(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def unit_increment(unit, hours):
    if unit is None:
        return
    unit["scheduled_hours_total"] = float(_dec2(unit["scheduled_hours_total"]) + _dec2(hours))
    unit["active_assignment_count"] += 1
    touch(unit)


def unit_decrement(unit, hours):
    if unit is None:
        return
    unit["scheduled_hours_total"] = float(_dec2(unit["scheduled_hours_total"]) - _dec2(hours))
    unit["active_assignment_count"] -= 1
    touch(unit)


# --- Packet items / readiness ----------------------------------------------------

def recompute_readiness(packet):
    items = [i for i in all_entities("packet_items") if i["packet_id"] == packet["id"]]
    total_weight = sum(Decimal(i["weight"]) for i in items)
    earned = sum(Decimal(i["weight"]) * CREDIT[i["status"]] for i in items)
    raw = (earned / total_weight).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if total_weight else Decimal("0")
    if any(i["critical"] and i["status"] in ("MISSING", "INVALIDATED") for i in items):
        raw = min(raw, CRITICAL_CAP)
    packet["readiness_score"] = float(raw)


def invalidate_items_for(credential_id):
    """VERIFIED items sourced from a lapsed credential row -> INVALIDATED.
    Recomputes owning packets' readiness; APPROVED packets -> VOIDED.
    Returns number of packets voided."""
    packet_ids = []
    for item in all_entities("packet_items"):
        if item["source_credential_id"] == credential_id and item["status"] == "VERIFIED":
            item["status"] = "INVALIDATED"
            touch(item)
            if item["packet_id"] not in packet_ids:
                packet_ids.append(item["packet_id"])
    voided = 0
    for pid in packet_ids:
        packet = db.STORES["packets"].get(pid)
        if packet is None:
            continue
        recompute_readiness(packet)
        if packet["status"] == "APPROVED":
            packet["status"] = "VOIDED"
            voided += 1
        touch(packet)
    return voided


# --- Competency completions -------------------------------------------------------

def compute_completion_expiry(requirement, completed_on):
    """competency_expiry_date: ROLLING anniversary vs FISCAL year-end (06-30)."""
    if requirement["window_mode"] == "ROLLING":
        return add_months(completed_on, requirement["validity_months"])
    fm, fd = FISCAL_MONTH_DAY
    fiscal_end = completed_on.replace(month=fm, day=fd)
    if fiscal_end >= completed_on:
        return fiscal_end
    return fiscal_end.replace(year=fiscal_end.year + 1)


def supersede_prior_completions(nurse_id, requirement_id, exclude_id):
    """New completion for (nurse, requirement) supersedes CURRENT/LAPSED priors;
    VERIFIED items sourced from them -> INVALIDATED."""
    for completion in all_entities("completions"):
        if (completion["nurse_id"] == nurse_id
                and completion["requirement_id"] == requirement_id
                and completion["id"] != exclude_id
                and completion["status"] in ("CURRENT", "LAPSED")):
            completion["status"] = "SUPERSEDED"
            touch(completion)
            invalidate_items_for(completion["id"])


# --- PSV freshness ------------------------------------------------------------------

def has_fresh_verified_psv(license_id):
    """A PSV is fresh iff status VERIFIED and valid_through >= current_date (inclusive)."""
    today = db.current_date()
    for psv in all_entities("psvs"):
        if psv["license_id"] == license_id and psv["status"] == "VERIFIED":
            if parse_date_loose(psv["valid_through"]) >= today:
                return True
    return False
