"""Enrollment service: submission, certification, sweep, completion, withdrawal."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..calculations import (
    PROGRAM_MAX_PER_TERM,
    entitlement_used_chronological,
    housing_allowance,
    months_for_enrollment,
    tuition_payable,
    yellow_ribbon,
)
from ..clock import Clock
from ..errors import ApiError
from ..store import Store
from ..util import days_between, money, new_id, to_utc

VALID_TRAINING_TIME = {"FULL_TIME", "THREE_QUARTER", "HALF_TIME", "LESS_THAN_HALF"}
VALID_DELIVERY = {"IN_PERSON", "ONLINE_ONLY"}
MONTH_YEAR_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def _now_iso(store: Store) -> str:
    return Clock.format(store.clock.now())


def _bump_version(store: Store, entity: dict) -> None:
    entity["updated_at"] = _now_iso(store)
    entity["version"] = entity["version"] + 1


def _parse_term(ts: str, field: str) -> datetime:
    try:
        return Clock.parse(ts)
    except ValueError as e:
        raise ApiError("ERR_INVALID_BODY", f"{field}: {e}")


def _validate_term_range(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ApiError("ERR_INVALID_TERM_RANGE", "term_end must be strictly greater than term_start")


def _validate_overlap(store: Store, veteran_id: str, start: datetime, end: datetime, exclude_id: str | None = None) -> None:
    for e in store.enrollments.values():
        if e["id"] == exclude_id:
            continue
        if e["veteran_id"] != veteran_id:
            continue
        if e["status"] not in ("SUBMITTED", "CERTIFIED", "ACTIVE"):
            continue
        es = to_utc(Clock.parse(e["term_start"]))
        ee = to_utc(Clock.parse(e["term_end"]))
        if start < ee and es < end:
            raise ApiError("ERR_ENROLLMENT_OVERLAP", "enrollment overlap detected")


def submit_enrollment(store: Store, body: dict, *, caller_id: str, caller_role: str) -> dict:
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")

    veteran_id = body.get("veteran_id")
    school_id = body.get("school_id")
    term_start = body.get("term_start")
    term_end = body.get("term_end")
    tuition_charged = body.get("tuition_charged")
    training_time = body.get("training_time")
    delivery_mode = body.get("delivery_mode")

    if not isinstance(veteran_id, str):
        raise ApiError("ERR_INVALID_BODY", "veteran_id required")
    if veteran_id not in store.veterans:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "veteran_id does not resolve")
    if not isinstance(school_id, str):
        raise ApiError("ERR_INVALID_BODY", "school_id required")
    if school_id not in store.schools:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "school_id does not resolve")

    if not isinstance(term_start, str) or not isinstance(term_end, str):
        raise ApiError("ERR_INVALID_BODY", "term_start and term_end required as ISO 8601 strings")
    ts = _parse_term(term_start, "term_start")
    te = _parse_term(term_end, "term_end")

    if (
        isinstance(tuition_charged, bool)
        or not isinstance(tuition_charged, (int, float))
        or tuition_charged < 0
    ):
        raise ApiError("ERR_INVALID_BODY", "tuition_charged must be a non-negative number")
    if training_time not in VALID_TRAINING_TIME:
        raise ApiError("ERR_INVALID_BODY", "invalid training_time")
    if delivery_mode not in VALID_DELIVERY:
        raise ApiError("ERR_INVALID_BODY", "invalid delivery_mode")

    if caller_role == "Veteran" and caller_id != veteran_id:
        raise ApiError("ERR_FORBIDDEN", "veteran can only submit own enrollment")

    _validate_term_range(ts, te)
    _validate_overlap(store, veteran_id, ts, te)

    now = _now_iso(store)
    eid = new_id()
    enrollment = {
        "id": eid,
        "veteran_id": veteran_id,
        "school_id": school_id,
        "term_start": Clock.format(ts),
        "term_end": Clock.format(te),
        "tuition_charged": money(tuition_charged),
        "training_time": training_time,
        "delivery_mode": delivery_mode,
        "status": "SUBMITTED",
        "months_consumed": Decimal("0.00"),
        "certified_tuition_payable": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.enrollments[eid] = enrollment
    return enrollment


def update_enrollment(store: Store, eid: str, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "enrollment not found")

    if "version" in body and body["version"] is not None:
        if body["version"] != e["version"]:
            raise ApiError("ERR_VERSION_CONFLICT", "version conflict")

    # Allow updating term_start / term_end / tuition_charged when in SUBMITTED.
    if e["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "enrollment must be in SUBMITTED to update")

    if "term_start" in body or "term_end" in body:
        new_start_iso = body.get("term_start", e["term_start"])
        new_end_iso = body.get("term_end", e["term_end"])
        ns = _parse_term(new_start_iso, "term_start")
        ne = _parse_term(new_end_iso, "term_end")
        _validate_term_range(ns, ne)
        _validate_overlap(store, e["veteran_id"], ns, ne, exclude_id=eid)
        e["term_start"] = Clock.format(ns)
        e["term_end"] = Clock.format(ne)

    if "tuition_charged" in body:
        t = body["tuition_charged"]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or t < 0:
            raise ApiError("ERR_INVALID_BODY", "tuition_charged must be a non-negative number")
        e["tuition_charged"] = money(t)

    _bump_version(store, e)
    return e


def certify_enrollment(store: Store, eid: str) -> dict:
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "enrollment not found")
    if e["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "enrollment not in SUBMITTED")

    v = store.veterans[e["veteran_id"]]
    if v["discharge_status"] != "HONORABLE":
        raise ApiError("ERR_INELIGIBLE_DISCHARGE", "veteran discharge status not HONORABLE")

    school = store.schools[e["school_id"]]
    tier = v["post_911_eligibility_tier"]

    # Tuition payable.
    payable = tuition_payable(e["tuition_charged"], school["program_type"], tier)

    # Yellow Ribbon allocation (only if applicable).
    yr_row: dict | None = None
    if (
        school["yellow_ribbon_enrolled"]
        and Decimal(e["tuition_charged"]) > PROGRAM_MAX_PER_TERM[school["program_type"]]
    ):
        yr = yellow_ribbon(
            tuition_charged=e["tuition_charged"],
            program_type=school["program_type"],
            school_max_per_year=school["yellow_ribbon_max_per_year"],
            tier_pct=tier,
        )

        # Yellow Ribbon annual school-cap aggregate check.
        # Sum school_contribution across YR contributions on enrollments whose
        # term_start falls in same calendar year, for this school.
        prospective_school_contrib = Decimal(yr["school_contribution"])
        if prospective_school_contrib > 0:
            year = to_utc(Clock.parse(e["term_start"])).year
            total = Decimal("0")
            for existing_yr in store.yellow_ribbon_contributions.values():
                source_enr = store.enrollments.get(existing_yr["enrollment_id"])
                if source_enr is None:
                    continue
                if source_enr["school_id"] != school["id"]:
                    continue
                # School cap is per-veteran-per-year per spec; conservatively per-year per school per veteran.
                # The PRD says cumulative across YR contributions for the school cap. We aggregate per school.
                # Filter to same veteran (PRD 3.7 implies per-veteran-per-year), but the validation 16
                # text says "per academic year (Jan 1 .. Dec 31)" without explicit veteran scoping.
                # We honor the school cap as per-veteran-per-school-per-year, matching the per-veteran
                # ceiling stated in the school field description.
                if source_enr["veteran_id"] != e["veteran_id"]:
                    continue
                src_year = to_utc(Clock.parse(source_enr["term_start"])).year
                if src_year != year:
                    continue
                total += Decimal(existing_yr["school_contribution"])
            if total + prospective_school_contrib > Decimal(school["yellow_ribbon_max_per_year"]):
                raise ApiError(
                    "ERR_YELLOW_RIBBON_CAP_EXCEEDED",
                    "school yellow_ribbon contribution would exceed annual cap",
                )

        now = _now_iso(store)
        yrid = new_id()
        yr_row = {
            "id": yrid,
            "enrollment_id": eid,
            "tuition_gap": yr["tuition_gap"],
            "school_contribution": yr["school_contribution"],
            "va_match": yr["va_match"],
            "student_responsibility": yr["student_responsibility"],
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.yellow_ribbon_contributions[yrid] = yr_row

    e["status"] = "CERTIFIED"
    e["certified_tuition_payable"] = payable
    _bump_version(store, e)
    return e


def cancel_enrollment(store: Store, eid: str) -> dict:
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "enrollment not found")
    if e["status"] not in ("SUBMITTED", "CERTIFIED"):
        raise ApiError("ERR_INVALID_STATE", "enrollment not cancelable")

    was_certified = e["status"] == "CERTIFIED"
    prior_payable = e.get("certified_tuition_payable")
    veteran_id = e["veteran_id"]

    e["status"] = "CANCELED"
    _bump_version(store, e)

    if was_certified:
        # Emit compensation iff there was a prior TUITION_PAYMENT for this enrollment.
        had_prior = any(
            l for l in store.ledger_entries.values()
            if l["source_entity"] == "TUITION_PAYMENT"
            and l["source_id"] == eid
            and l["amount_dollars"] > 0
        )
        if had_prior and prior_payable is not None:
            _emit_ledger(
                store,
                veteran_id=veteran_id,
                source_entity="TUITION_PAYMENT",
                source_id=eid,
                amount_dollars=-Decimal(prior_payable),
            )
        # Reset any YR contribution to zero.
        for yr in store.yellow_ribbon_contributions.values():
            if yr["enrollment_id"] == eid:
                yr["tuition_gap"] = Decimal("0.00")
                yr["school_contribution"] = Decimal("0.00")
                yr["va_match"] = Decimal("0.00")
                yr["student_responsibility"] = Decimal("0.00")
                _bump_version(store, yr)

    return e


def complete_enrollment(store: Store, eid: str) -> dict:
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "enrollment not found")
    if e["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "enrollment not in ACTIVE")
    te = to_utc(Clock.parse(e["term_end"]))
    if store.clock.now() < te:
        raise ApiError("ERR_INVALID_STATE", "term_end not yet reached")

    veteran_id = e["veteran_id"]

    # Compute months_consumed for this enrollment (full term for COMPLETED).
    ts = to_utc(Clock.parse(e["term_start"]))
    days = max(0, days_between(ts, te))
    new_months = money(Decimal(days) / Decimal("30"))

    # Fiscal guard: project new total.
    enrolls_snapshot = [dict(x) for x in store.enrollments.values()]
    # Substitute the candidate enrollment with COMPLETED status & new months.
    for x in enrolls_snapshot:
        if x["id"] == eid:
            x["status"] = "COMPLETED"
            x["months_consumed"] = new_months
    projected_total = entitlement_used_chronological(enrolls_snapshot, now=store.clock.now())
    # Test whether this completion would push total above 36.00 — using the
    # uncapped sum so that boundary is detected before cap clamps.
    eligible_total = Decimal("0")
    for x in enrolls_snapshot:
        if x["status"] in ("COMPLETED", "WITHDRAWN"):
            eligible_total += months_for_enrollment(x, now=store.clock.now())
    if eligible_total > Decimal("36.00"):
        raise ApiError("ERR_ENTITLEMENT_EXCEEDED", "completion would exceed 36.00 entitlement cap")

    e["status"] = "COMPLETED"
    e["months_consumed"] = new_months
    _bump_version(store, e)

    # Recompute veteran's months_entitlement_used.
    from .veterans import recompute_entitlement

    recompute_entitlement(store, veteran_id)

    # Ledger entry.
    _emit_ledger(
        store,
        veteran_id=veteran_id,
        source_entity="ENTITLEMENT_DEBIT",
        source_id=eid,
        amount_dollars=-Decimal(new_months),
    )
    return e


def withdraw_enrollment(store: Store, eid: str, *, caller_id: str) -> dict:
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "enrollment not found")
    if e["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "enrollment not in ACTIVE")
    if caller_id != e["veteran_id"]:
        raise ApiError("ERR_FORBIDDEN", "only owning veteran may withdraw")

    veteran_id = e["veteran_id"]
    ts = to_utc(Clock.parse(e["term_start"]))
    te = to_utc(Clock.parse(e["term_end"]))
    now = store.clock.now()
    end_used = min(now, te)
    if end_used < ts:
        end_used = ts
    days = max(0, days_between(ts, end_used))
    new_months = money(Decimal(days) / Decimal("30"))

    enrolls_snapshot = [dict(x) for x in store.enrollments.values()]
    for x in enrolls_snapshot:
        if x["id"] == eid:
            x["status"] = "WITHDRAWN"
            x["months_consumed"] = new_months
    eligible_total = Decimal("0")
    for x in enrolls_snapshot:
        if x["status"] in ("COMPLETED", "WITHDRAWN"):
            eligible_total += months_for_enrollment(x, now=store.clock.now())
    if eligible_total > Decimal("36.00"):
        raise ApiError("ERR_ENTITLEMENT_EXCEEDED", "withdrawal would exceed 36.00 entitlement cap")

    e["status"] = "WITHDRAWN"
    e["months_consumed"] = new_months
    _bump_version(store, e)

    from .veterans import recompute_entitlement

    recompute_entitlement(store, veteran_id)

    _emit_ledger(
        store,
        veteran_id=veteran_id,
        source_entity="ENTITLEMENT_DEBIT",
        source_id=eid,
        amount_dollars=-Decimal(new_months),
    )
    return e


def post_housing_payment(store: Store, eid: str, body: dict) -> dict:
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "enrollment not found")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")
    my = body.get("month_year")
    if not isinstance(my, str) or not MONTH_YEAR_RE.match(my):
        raise ApiError("ERR_INVALID_BODY", "month_year must match YYYY-MM")

    # Term overlap: month must share at least one UTC day with [term_start, term_end).
    year_s, month_s = my.split("-", 1)
    year = int(year_s)
    month = int(month_s)
    from ..util import month_bounds

    m_start, m_end = month_bounds(year, month)
    ts = to_utc(Clock.parse(e["term_start"]))
    te = to_utc(Clock.parse(e["term_end"]))
    overlap_start = max(ts, m_start)
    overlap_end = min(te, m_end)
    if overlap_end <= overlap_start:
        raise ApiError("ERR_PAYMENT_OUTSIDE_TERM", "month does not overlap enrollment term")

    # Uniqueness on (enrollment_id, month_year).
    store.reserve_housing_payment_key(eid, my)

    veteran_id = e["veteran_id"]
    veteran = store.veterans[veteran_id]
    school = store.schools[e["school_id"]]

    # Active dependents at month start.
    active_count = 0
    for d in store.dependents.values():
        if d["veteran_id"] != veteran_id:
            continue
        if d["status"] != "ACTIVE":
            continue
        # If removed_at is before m_start, treat as inactive. (Removed-only ones.)
        # Since we only include ACTIVE, this is fine.
        active_count += 1

    bah_base = store.bah_for_zip(school["zip_bah_code"])
    calc = housing_allowance(
        month_year=my,
        enrollment=e,
        school=school,
        veteran=veteran,
        active_dep_count_at_month_start=active_count,
        bah_base=bah_base,
    )

    now = _now_iso(store)
    hid = new_id()
    hp = {
        "id": hid,
        "enrollment_id": eid,
        "month_year": my,
        "amount": calc["amount"],
        "computation_basis": calc["computation_basis"],
        "created_at": now,
    }
    store.housing_payments[hid] = hp

    _emit_ledger(
        store,
        veteran_id=veteran_id,
        source_entity="HOUSING_PAYMENT",
        source_id=hid,
        amount_dollars=Decimal(calc["amount"]),
    )
    return hp


def _emit_ledger(
    store: Store,
    *,
    veteran_id: str,
    source_entity: str,
    source_id: str,
    amount_dollars: Decimal,
) -> dict:
    now = _now_iso(store)
    lid = new_id()
    entry = {
        "id": lid,
        "veteran_id": veteran_id,
        "source_entity": source_entity,
        "source_id": source_id,
        "amount_dollars": money(amount_dollars),
        "posted_at": now,
        "created_at": now,
    }
    store.ledger_entries[lid] = entry
    return entry


def run_sweep(store: Store) -> dict:
    """Promote eligible CERTIFIED enrollments to ACTIVE and finalize old DENIED claims."""
    activated = 0
    now = store.clock.now()
    for e in store.enrollments.values():
        if e["status"] != "CERTIFIED":
            continue
        ts = to_utc(Clock.parse(e["term_start"]))
        if now < ts:
            continue
        v = store.veterans[e["veteran_id"]]
        if v["combined_rating"] <= 0:
            continue
        e["status"] = "ACTIVE"
        _bump_version(store, e)

        # Tuition ledger entry.
        if e["certified_tuition_payable"] is not None:
            _emit_ledger(
                store,
                veteran_id=e["veteran_id"],
                source_entity="TUITION_PAYMENT",
                source_id=e["id"],
                amount_dollars=Decimal(e["certified_tuition_payable"]),
            )
        # YR match ledger entry if YR contribution exists.
        for yr in store.yellow_ribbon_contributions.values():
            if yr["enrollment_id"] == e["id"]:
                if Decimal(yr["va_match"]) > 0:
                    _emit_ledger(
                        store,
                        veteran_id=e["veteran_id"],
                        source_entity="YELLOW_RIBBON_VA_MATCH",
                        source_id=yr["id"],
                        amount_dollars=Decimal(yr["va_match"]),
                    )
                break
        activated += 1

    # Finalize DENIED claims.
    from .claims import finalize_denied_after_365

    finalized = finalize_denied_after_365(store)

    return {"activated_enrollments": activated, "finalized_claims": finalized}
