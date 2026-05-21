"""Mutation services for each entity. These implement the state machines,
cascades, and validations from SCAFFOLD §1.2 and PRD §3.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..clock import now_dt, now_iso
from ..errors import APIError
from ..store import get_store
from ..util import (
    add_days,
    first_sunday_on_or_before,
    format_iso_date,
    new_id,
    parse_iso8601,
    parse_iso_date,
)
from . import calculations as calc


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _new_common(now: str) -> Dict[str, Any]:
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def _bump(entity: Dict[str, Any], now: str) -> None:
    entity["updated_at"] = now
    entity["version"] = entity.get("version", 1) + 1


def _claim_exists(claim_id: str) -> Dict[str, Any]:
    store = get_store()
    c = store.claims.get(claim_id)
    if c is None:
        raise APIError("ERR_NOT_FOUND", f"Claim '{claim_id}' not found", 404)
    return c


def _claimant_exists(claimant_id: str) -> Dict[str, Any]:
    store = get_store()
    c = store.claimants.get(claimant_id)
    if c is None:
        raise APIError("ERR_NOT_FOUND", f"Claimant '{claimant_id}' not found", 404)
    return c


def _employer_exists(employer_id: str) -> Dict[str, Any]:
    store = get_store()
    e = store.employers.get(employer_id)
    if e is None:
        raise APIError("ERR_NOT_FOUND", f"Employer '{employer_id}' not found", 404)
    return e


def _certification_exists(cert_id: str) -> Dict[str, Any]:
    store = get_store()
    c = store.weekly_certifications.get(cert_id)
    if c is None:
        raise APIError("ERR_NOT_FOUND", f"WeeklyCertification '{cert_id}' not found", 404)
    return c


def _overpayment_exists(overpayment_id: str) -> Dict[str, Any]:
    store = get_store()
    o = store.overpayments.get(overpayment_id)
    if o is None:
        raise APIError("ERR_NOT_FOUND", f"Overpayment '{overpayment_id}' not found", 404)
    return o


def _appeal_exists(appeal_id: str) -> Dict[str, Any]:
    store = get_store()
    a = store.appeals.get(appeal_id)
    if a is None:
        raise APIError("ERR_NOT_FOUND", f"Appeal '{appeal_id}' not found", 404)
    return a


def _check_occ(entity: Dict[str, Any], supplied_version: Optional[int]) -> None:
    if supplied_version is None:
        return
    if entity.get("version") != supplied_version:
        raise APIError("ERR_VERSION_CONFLICT", "Version mismatch (OCC)", 409)


def _recompute_lifetime_overpayment(claimant_id: str) -> None:
    store = get_store()
    total = 0
    for o in store.overpayments.values():
        if o["status"] != "OUTSTANDING":
            continue
        cl = store.claims.get(o["claim_id"])
        if cl is None:
            continue
        if cl["claimant_id"] != claimant_id:
            continue
        total += o["balance_cents"]
    cm = store.claimants.get(claimant_id)
    if cm is not None:
        if cm.get("lifetime_overpayment_balance_cents", 0) != total:
            cm["lifetime_overpayment_balance_cents"] = total
            _bump(cm, now_iso())


def _recompute_employer_rate(employer_id: str) -> None:
    """Recompute experience_rate_bps for the employer and bump if changed."""
    store = get_store()
    emp = store.employers.get(employer_id)
    if emp is None:
        return
    active_sum = 0
    relieved_sum = 0
    for ch in store.employer_charges.values():
        if ch["employer_id"] != employer_id:
            continue
        if ch["status"] == "ACTIVE":
            active_sum += ch["charge_cents"]
        elif ch["status"] == "RELIEVED":
            relieved_sum += ch["charge_cents"]
        # REVERSED rows don't count.
    new_rate = calc.compute_experience_rate_bps(
        emp["reserve_ratio_basis_cents"],
        emp["taxable_payroll_cents"],
        active_sum,
        relieved_sum,
    )
    if new_rate != emp["experience_rate_bps"]:
        emp["experience_rate_bps"] = new_rate
        _bump(emp, now_iso())


# -----------------------------------------------------------------------------
# Claimant
# -----------------------------------------------------------------------------
def create_claimant(payload: Dict[str, Any]) -> Dict[str, Any]:
    store = get_store()
    now = now_iso()
    entity = _new_common(now)
    entity.update({
        "ssn_last4": payload["ssn_last4"],
        "full_name": payload["full_name"],
        "state_residence": payload["state_residence"],
        "date_of_birth": payload["date_of_birth"],
        "lifetime_overpayment_balance_cents": 0,
    })
    store.claimants[entity["id"]] = entity
    return entity


# -----------------------------------------------------------------------------
# Employer
# -----------------------------------------------------------------------------
def create_employer(payload: Dict[str, Any]) -> Dict[str, Any]:
    store = get_store()
    ein = payload["ein"]
    if ein in store.employer_eins:
        raise APIError("ERR_VALIDATION_FAILED", "ein must be unique", 422)
    now = now_iso()
    entity = _new_common(now)
    entity.update({
        "ein": ein,
        "legal_name": payload["legal_name"],
        "reserve_ratio_basis_cents": payload["reserve_ratio_basis_cents"],
        "taxable_payroll_cents": payload["taxable_payroll_cents"],
        # Initial experience rate from raw reserve ratio (no charges yet)
        "experience_rate_bps": calc.compute_experience_rate_bps(
            payload["reserve_ratio_basis_cents"],
            payload["taxable_payroll_cents"],
            0,
            0,
        ),
    })
    store.employers[entity["id"]] = entity
    store.employer_eins[ein] = entity["id"]
    return entity


# -----------------------------------------------------------------------------
# WageRecord
# -----------------------------------------------------------------------------
def create_wage_record(claimant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    store = get_store()
    _claimant_exists(claimant_id)
    employer_id = payload["employer_id"]
    _employer_exists(employer_id)

    quarter_year = payload["quarter_year"]
    current_year = now_dt().year
    if not (2000 <= quarter_year <= current_year):
        raise APIError(
            "ERR_VALIDATION_FAILED",
            "quarter_year must be between 2000 and current year",
            422,
        )

    now = now_iso()
    entity = {
        "id": new_id(),
        "created_at": now,
        "claimant_id": claimant_id,
        "employer_id": employer_id,
        "quarter_year": quarter_year,
        "quarter_index": payload["quarter_index"],
        "wages_cents": payload["wages_cents"],
    }
    store.wage_records[entity["id"]] = entity
    return entity


# -----------------------------------------------------------------------------
# Claim — open / submit / adjudicate / apply-extension
# -----------------------------------------------------------------------------
def open_claim(claimant_id: str) -> Dict[str, Any]:
    store = get_store()
    _claimant_exists(claimant_id)
    now = now_iso()
    entity = _new_common(now)
    entity.update({
        "claimant_id": claimant_id,
        "filing_date": None,
        "benefit_year_start": None,
        "benefit_year_end": None,
        "base_period_variant": None,
        "base_period_total_wages_cents": 0,
        "high_quarter_wages_cents": 0,
        "weekly_benefit_amount_cents": 0,
        "max_weeks_of_eligibility": 0,
        "status": "DRAFT",
        "weeks_paid": 0,
        "weeks_remaining": 0,
        "pandemic_extension_weeks_granted": 0,
        "extension_id": None,
        "assigned_adjudicator_id": None,
        "decision_at": None,
    })
    store.claims[entity["id"]] = entity
    return entity


def submit_claim(claim_id: str, acting_user_id: str) -> Dict[str, Any]:
    store = get_store()
    claim = _claim_exists(claim_id)
    if claim["claimant_id"] != acting_user_id:
        raise APIError("ERR_NOT_OWNER", "Claimant does not own this Claim", 403)

    if claim["status"] != "DRAFT":
        raise APIError("ERR_INVALID_STATE", f"Cannot submit a Claim in state {claim['status']}", 409)

    # Verify at least one WageRecord in candidate base periods.
    filing_dt = now_dt()
    fy, fm = filing_dt.year, filing_dt.month
    wage_records = list(store.wage_records.values())

    # Quick existence check across either candidate base period.
    fyr, fq = calc.filing_quarter(fy, fm)
    std_qs = calc.standard_base_period_quarters(fyr, fq)
    alt_qs = calc.alternate_base_period_quarters(fyr, fq)
    combined = set(std_qs) | set(alt_qs)
    has_wage = any(
        wr["claimant_id"] == claim["claimant_id"]
        and (wr["quarter_year"], wr["quarter_index"]) in combined
        for wr in wage_records
    )
    if not has_wage:
        raise APIError("ERR_INVALID_STATE", "Claimant has no wage records in candidate base periods", 409)

    # Run calculations.
    variant, total_wages, hq_wages, _ = calc.choose_base_period(
        wage_records, claim["claimant_id"], fy, fm
    )
    wba = calc.compute_weekly_benefit_amount(hq_wages)
    max_weeks = calc.compute_max_weeks(total_wages, wba)

    # Filing date and benefit-year window.
    filing_iso = now_iso()
    filing_date_only = filing_dt.date()
    by_start = first_sunday_on_or_before(filing_date_only)
    by_end = add_days(by_start, 364)

    claim["filing_date"] = filing_iso
    claim["benefit_year_start"] = format_iso_date(by_start)
    claim["benefit_year_end"] = format_iso_date(by_end)
    claim["base_period_variant"] = variant
    claim["base_period_total_wages_cents"] = total_wages
    claim["high_quarter_wages_cents"] = hq_wages
    claim["weekly_benefit_amount_cents"] = wba
    claim["max_weeks_of_eligibility"] = max_weeks
    claim["weeks_remaining"] = max_weeks  # no extensions yet, no weeks paid
    claim["status"] = "PENDING_ADJUDICATION"
    _bump(claim, filing_iso)
    return claim


def adjudicate_claim(
    claim_id: str,
    decision: str,
    actor_user_id: str,
    version: Optional[int],
) -> Dict[str, Any]:
    claim = _claim_exists(claim_id)
    if claim["status"] != "PENDING_ADJUDICATION":
        raise APIError(
            "ERR_INVALID_STATE",
            f"Cannot adjudicate a Claim in state {claim['status']}",
            409,
        )

    if decision == "ELIGIBLE":
        if (
            claim["base_period_total_wages_cents"] < calc.MIN_BASE_PERIOD_WAGES_CENTS
            or claim["high_quarter_wages_cents"] < calc.MIN_HIGH_QUARTER_WAGES_CENTS
            or claim["weekly_benefit_amount_cents"] <= 0
        ):
            raise APIError(
                "ERR_INSUFFICIENT_BASE_PERIOD_WAGES",
                "Base period wages or high-quarter wages fall below required floors",
                422,
            )
    _check_occ(claim, version)
    now = now_iso()
    if decision == "ELIGIBLE":
        claim["status"] = "MONETARILY_ELIGIBLE"
    elif decision == "DENIED":
        claim["status"] = "DENIED"
    else:
        raise APIError("ERR_VALIDATION_FAILED", "decision must be ELIGIBLE or DENIED", 422)
    claim["assigned_adjudicator_id"] = actor_user_id
    claim["decision_at"] = now
    _bump(claim, now)
    return claim


def apply_extension(
    claim_id: str,
    extension_id: str,
    acting_user_id: str,
    version: Optional[int],
) -> Dict[str, Any]:
    store = get_store()
    claim = _claim_exists(claim_id)
    if claim["claimant_id"] != acting_user_id:
        raise APIError("ERR_NOT_OWNER", "Claimant does not own this Claim", 403)

    ext = store.pandemic_extensions.get(extension_id)
    if ext is None:
        raise APIError("ERR_NOT_FOUND", f"PandemicExtension '{extension_id}' not found", 404)

    # PRD §3.4: "extensions cannot be stacked, and a second apply-extension
    # on the same claim is rejected with ERR_EXTENSION_ALREADY_APPLIED."
    # PRD §3.8: "Two apply-extension requests on the same EXHAUSTED claim
    # serialize on the extension_id immutability rule; the first writer
    # wins and the second is rejected with ERR_EXTENSION_ALREADY_APPLIED."
    # The "second apply" scenario inherently puts the claim in EXTENDED
    # (because the first apply transitioned it). To make §3.4 and §3.8
    # observable, the extension_id immutability check is evaluated
    # before the EXHAUSTED-state gate: any claim that already carries
    # an extension_id is rejected on the stacking rule regardless of
    # the claim's current status.
    if claim.get("extension_id") is not None:
        raise APIError("ERR_EXTENSION_ALREADY_APPLIED", "Claim already has an extension applied", 409)

    if claim["status"] != "EXHAUSTED":
        raise APIError(
            "ERR_INVALID_STATE",
            f"Cannot apply extension on a Claim in state {claim['status']}",
            409,
        )

    # Must have an ACTIVE extension whose window contains SystemClock.now
    now_d = now_dt().date()
    eff_start = parse_iso_date(ext["effective_start"])
    eff_end = parse_iso_date(ext["effective_end"])
    if ext["status"] != "ACTIVE" or eff_start is None or eff_end is None or not (eff_start <= now_d <= eff_end):
        raise APIError("ERR_NO_ACTIVE_EXTENSION", "No ACTIVE PandemicExtension in current window", 409)

    _check_occ(claim, version)
    now = now_iso()
    claim["extension_id"] = extension_id
    claim["pandemic_extension_weeks_granted"] = ext["extra_weeks"]
    new_remaining = max(
        0,
        claim["max_weeks_of_eligibility"]
        + claim["pandemic_extension_weeks_granted"]
        - claim["weeks_paid"],
    )
    claim["weeks_remaining"] = new_remaining
    claim["status"] = "EXTENDED"
    _bump(claim, now)
    return claim


# -----------------------------------------------------------------------------
# Weekly Certification + the payment cascade
# -----------------------------------------------------------------------------
def _check_benefit_year_open(claim: Dict[str, Any]) -> None:
    """Reject if SystemClock.now > benefit_year_end (Claim is CLOSED)."""
    if claim["status"] == "CLOSED":
        raise APIError("ERR_BENEFIT_YEAR_EXPIRED", "Claim's benefit year has expired", 409)


def submit_weekly_certification(
    claim_id: str,
    acting_user_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    store = get_store()
    claim = _claim_exists(claim_id)
    if claim["claimant_id"] != acting_user_id:
        raise APIError("ERR_NOT_OWNER", "Claimant does not own this Claim", 403)

    # State legality first.
    if claim["status"] == "CLOSED":
        raise APIError("ERR_BENEFIT_YEAR_EXPIRED", "Claim's benefit year has expired", 409)
    if claim["status"] not in {"MONETARILY_ELIGIBLE", "ACTIVE", "EXTENDED", "EXHAUSTED"}:
        raise APIError(
            "ERR_INVALID_STATE",
            f"Cannot submit a weekly certification on a Claim in state {claim['status']}",
            409,
        )

    week_ending = payload["week_ending_date"]
    week_dt = parse_iso_date(week_ending)
    if week_dt is None:
        raise APIError("ERR_VALIDATION_FAILED", "week_ending_date must be a valid ISO date", 422)

    # ERR_NOT_SATURDAY (priority 9). Python's weekday(): Mon=0..Sun=6. Saturday=5.
    if week_dt.weekday() != 5:
        raise APIError("ERR_NOT_SATURDAY", "week_ending_date must be a Saturday", 422)

    # ERR_WEEK_OUT_OF_RANGE (priority 10)
    # Must lie within [benefit_year_start, benefit_year_end] (inclusive)
    by_start = parse_iso_date(claim.get("benefit_year_start"))
    by_end = parse_iso_date(claim.get("benefit_year_end"))
    if by_start is None or by_end is None or not (by_start <= week_dt <= by_end):
        raise APIError(
            "ERR_WEEK_OUT_OF_RANGE",
            "week_ending_date outside benefit year window",
            409,
        )

    # PRD §3.3: "Submitting one whose week_ending_date is not strictly
    # later than the latest APPROVED certification's week_ending_date
    # for this claim ... is rejected with ERR_WEEK_OUT_OF_RANGE."
    # PRD §3.8: a simultaneous same-week submission is rejected with
    # ERR_DUPLICATE_WEEK on the uniqueness constraint (the loser's
    # week_ending_date equals — not strictly earlier than — the
    # winner's). To make both rules consistent, the "not strictly later"
    # check only fires when the new week is STRICTLY EARLIER than the
    # latest APPROVED week; the equality case is the duplicate-week
    # collision and surfaces below as ERR_DUPLICATE_WEEK.
    latest_approved = None
    for c in store.weekly_certifications.values():
        if c["claim_id"] != claim_id or c["status"] != "APPROVED":
            continue
        d = parse_iso_date(c["week_ending_date"])
        if d is None:
            continue
        if latest_approved is None or d > latest_approved:
            latest_approved = d
    if latest_approved is not None and week_dt < latest_approved:
        raise APIError(
            "ERR_WEEK_OUT_OF_RANGE",
            "week_ending_date must be strictly later than the latest APPROVED certification",
            409,
        )

    # ERR_DUPLICATE_WEEK (priority 11)
    key = (claim_id, week_ending)
    if key in store.cert_unique:
        raise APIError("ERR_DUPLICATE_WEEK", "A certification already exists for this week", 409)

    earnings = payload["earnings_reported_cents"]
    able = payload["able_and_available"]
    entries_payload = payload.get("work_search_entries", [])
    if not isinstance(entries_payload, list):
        raise APIError("ERR_VALIDATION_FAILED", "work_search_entries must be a list", 422)

    # ERR_INSUFFICIENT_WORK_SEARCH (priority 12)
    if len(entries_payload) < calc.MIN_WORK_SEARCH_CONTACTS:
        raise APIError(
            "ERR_INSUFFICIENT_WORK_SEARCH",
            f"At least {calc.MIN_WORK_SEARCH_CONTACTS} work-search entries are required",
            422,
        )

    # Validate each work-search entry shape.
    valid_methods = {"ONLINE_APPLICATION", "IN_PERSON", "PHONE", "EMAIL", "REFERRAL"}
    cleaned_entries = []
    for idx, ent in enumerate(entries_payload):
        if not isinstance(ent, dict):
            raise APIError("ERR_VALIDATION_FAILED", f"work_search_entries[{idx}] must be an object", 422)
        for fld in ("contact_date", "employer_name", "contact_method"):
            if fld not in ent or not isinstance(ent[fld], str):
                raise APIError(
                    "ERR_VALIDATION_FAILED",
                    f"work_search_entries[{idx}].{fld} is required and must be a string",
                    422,
                )
        if ent["contact_method"] not in valid_methods:
            raise APIError(
                "ERR_VALIDATION_FAILED",
                f"work_search_entries[{idx}].contact_method must be one of {sorted(valid_methods)}",
                422,
            )
        if parse_iso_date(ent["contact_date"]) is None:
            raise APIError(
                "ERR_VALIDATION_FAILED",
                f"work_search_entries[{idx}].contact_date must be a valid ISO date",
                422,
            )
        cleaned_entries.append(ent)

    # Compute payable amount.
    payable = calc.compute_payable_amount(claim["weekly_benefit_amount_cents"], earnings)

    # Create certification entity.
    now = now_iso()
    cert = _new_common(now)
    cert.update({
        "claim_id": claim_id,
        "week_ending_date": week_ending,
        "status": "SUBMITTED",
        "earnings_reported_cents": earnings,
        "able_and_available": able,
        "work_search_count": len(cleaned_entries),
        "payable_amount_cents": payable,
        "payment_id": None,
    })
    store.weekly_certifications[cert["id"]] = cert
    store.cert_unique[key] = cert["id"]

    # Create work-search entry rows
    for ent in cleaned_entries:
        wse = {
            "id": new_id(),
            "created_at": now,
            "certification_id": cert["id"],
            "contact_date": ent["contact_date"],
            "employer_name": ent["employer_name"],
            "contact_method": ent["contact_method"],
        }
        store.work_search_entries[wse["id"]] = wse

    # Determine APPROVED vs DENIED.
    can_approve = (
        claim["status"] in {"MONETARILY_ELIGIBLE", "ACTIVE", "EXTENDED"}
        and claim.get("weeks_remaining", 0) > 0
        and len(cleaned_entries) >= calc.MIN_WORK_SEARCH_CONTACTS
        and able is True
        and payable > 0
    )

    if can_approve:
        _approve_certification(cert, claim, now)
    else:
        cert["status"] = "DENIED"
        _bump(cert, now)

    return cert


def _approve_certification(cert: Dict[str, Any], claim: Dict[str, Any], now: str) -> None:
    """Transition SUBMITTED -> APPROVED and fire the payment cascade."""
    store = get_store()
    cert["status"] = "APPROVED"
    _bump(cert, now)

    # Create BenefitPayment.
    payment = {
        "id": new_id(),
        "created_at": now,
        "claim_id": claim["id"],
        "certification_id": cert["id"],
        "amount_cents": cert["payable_amount_cents"],
        "issued_at": now,
        "status": "ISSUED",
        "reversed_reason": None,
    }
    store.benefit_payments[payment["id"]] = payment
    cert["payment_id"] = payment["id"]

    # Employer charge allocation.
    _allocate_charges_for_payment(claim, payment, now)

    # Recompute weeks_paid/weeks_remaining; cascade claim status.
    _recompute_claim_weeks_and_state(claim, now)


def _allocate_charges_for_payment(
    claim: Dict[str, Any], payment: Dict[str, Any], now: str
) -> None:
    """Create EmployerCharge rows for the new payment per pinned rounding order;
    then recompute each charged employer's experience_rate_bps.
    """
    store = get_store()
    bp_total = claim.get("base_period_total_wages_cents", 0)
    if bp_total <= 0 or payment["amount_cents"] <= 0:
        return

    # Resolve base period quarters from variant.
    filing_dt = parse_iso8601(claim["filing_date"]) if claim.get("filing_date") else None
    if filing_dt is None:
        return
    fy, fq = calc.filing_quarter(filing_dt.year, filing_dt.month)
    if claim["base_period_variant"] == "ALTERNATE":
        quarters = calc.alternate_base_period_quarters(fy, fq)
    else:
        quarters = calc.standard_base_period_quarters(fy, fq)
    qset = set(quarters)

    # Sum wages_E per employer for this claimant in those quarters.
    per_employer: Dict[str, int] = {}
    for wr in store.wage_records.values():
        if wr["claimant_id"] != claim["claimant_id"]:
            continue
        if (wr["quarter_year"], wr["quarter_index"]) not in qset:
            continue
        per_employer[wr["employer_id"]] = per_employer.get(wr["employer_id"], 0) + wr["wages_cents"]

    if not per_employer:
        return

    # Keep deterministic order: sort by employer_id ASC for the iteration that builds
    # raw, then the residual distributor will sort by wages DESC, id ASC.
    ordered = sorted(per_employer.items(), key=lambda kv: kv[0])
    allocations = calc.allocate_employer_charges(payment["amount_cents"], bp_total, ordered)

    for (emp_id, charge_cents) in allocations:
        ch = _new_common(now)
        ch.update({
            "employer_id": emp_id,
            "claim_id": claim["id"],
            "payment_id": payment["id"],
            "charge_cents": charge_cents,
            "status": "ACTIVE",
        })
        store.employer_charges[ch["id"]] = ch

    # Recompute experience rate for each affected employer.
    for emp_id in per_employer.keys():
        _recompute_employer_rate(emp_id)


def _recompute_claim_weeks_and_state(claim: Dict[str, Any], now: str) -> None:
    """Recompute weeks_paid / weeks_remaining and apply state cascade."""
    store = get_store()
    weeks_paid = sum(
        1
        for c in store.weekly_certifications.values()
        if c["claim_id"] == claim["id"] and c["status"] == "APPROVED"
    )
    cap = claim["max_weeks_of_eligibility"] + claim.get("pandemic_extension_weeks_granted", 0)
    weeks_remaining = max(0, cap - weeks_paid)
    claim["weeks_paid"] = weeks_paid
    claim["weeks_remaining"] = weeks_remaining

    old_status = claim["status"]
    if old_status == "MONETARILY_ELIGIBLE":
        claim["status"] = "ACTIVE"

    if weeks_remaining == 0 and claim["status"] in {"ACTIVE", "EXTENDED"}:
        claim["status"] = "EXHAUSTED"

    _bump(claim, now)


# -----------------------------------------------------------------------------
# Audit & Overpayment
# -----------------------------------------------------------------------------
def audit_certification(
    cert_id: str,
    classification: str,
    reason: str,
    version: Optional[int],
) -> Dict[str, Any]:
    store = get_store()
    cert = _certification_exists(cert_id)
    if cert["status"] != "APPROVED":
        raise APIError(
            "ERR_INVALID_STATE",
            f"Cannot audit a certification in state {cert['status']}",
            409,
        )
    payment_id = cert.get("payment_id")
    if not payment_id:
        raise APIError("ERR_INVALID_STATE", "Certification has no linked payment", 409)
    payment = store.benefit_payments.get(payment_id)
    if payment is None or payment["status"] != "ISSUED":
        raise APIError("ERR_INVALID_STATE", "Linked BenefitPayment is not ISSUED", 409)

    if classification not in {"AGENCY_ERROR", "NON_FRAUD", "FRAUD"}:
        raise APIError("ERR_VALIDATION_FAILED", "classification must be one of {AGENCY_ERROR, NON_FRAUD, FRAUD}", 422)

    _check_occ(cert, version)

    now = now_iso()
    claim = _claim_exists(cert["claim_id"])

    # Reverse the payment.
    payment["status"] = "REVERSED"
    payment["reversed_reason"] = reason

    # Create Overpayment.
    overpayment = _new_common(now)
    overpayment.update({
        "claim_id": claim["id"],
        "certification_id": cert["id"],
        "principal_cents": payment["amount_cents"],
        "balance_cents": payment["amount_cents"],
        "classification": classification,
        "status": "OUTSTANDING",
    })
    store.overpayments[overpayment["id"]] = overpayment

    # Reverse linked EmployerCharge rows whose status is ACTIVE.
    affected_employers = set()
    for ch in list(store.employer_charges.values()):
        if ch["payment_id"] != payment["id"]:
            continue
        if ch["status"] == "ACTIVE":
            ch["status"] = "REVERSED"
            _bump(ch, now)
            affected_employers.add(ch["employer_id"])
    for emp_id in affected_employers:
        _recompute_employer_rate(emp_id)

    # Transition cert -> OVERPAID.
    cert["status"] = "OVERPAID"
    _bump(cert, now)

    # Recompute claim weeks_paid/weeks_remaining and possibly revert EXHAUSTED -> ACTIVE/EXTENDED.
    weeks_paid = sum(
        1
        for c in store.weekly_certifications.values()
        if c["claim_id"] == claim["id"] and c["status"] == "APPROVED"
    )
    cap = claim["max_weeks_of_eligibility"] + claim.get("pandemic_extension_weeks_granted", 0)
    weeks_remaining = max(0, cap - weeks_paid)
    claim["weeks_paid"] = weeks_paid
    claim["weeks_remaining"] = weeks_remaining
    if claim["status"] == "EXHAUSTED" and weeks_remaining > 0:
        if claim.get("extension_id"):
            claim["status"] = "EXTENDED"
        else:
            claim["status"] = "ACTIVE"
    _bump(claim, now)

    # Recompute lifetime overpayment.
    _recompute_lifetime_overpayment(claim["claimant_id"])

    return cert


# -----------------------------------------------------------------------------
# Overpayment actions: repay / waive / write-off
# -----------------------------------------------------------------------------
def repay_overpayment(
    overpayment_id: str,
    amount_cents: int,
    acting_user_id: str,
    version: Optional[int],
) -> Dict[str, Any]:
    store = get_store()
    o = _overpayment_exists(overpayment_id)
    claim = _claim_exists(o["claim_id"])
    if claim["claimant_id"] != acting_user_id:
        raise APIError("ERR_NOT_OWNER", "Claimant does not own this Overpayment", 403)

    if o["status"] != "OUTSTANDING":
        raise APIError("ERR_INVALID_STATE", f"Cannot repay an Overpayment in state {o['status']}", 409)

    if amount_cents <= 0 or amount_cents > o["balance_cents"]:
        raise APIError("ERR_REPAY_EXCEEDS_BALANCE", "Repayment amount exceeds outstanding balance", 409)

    _check_occ(o, version)

    now = now_iso()
    o["balance_cents"] -= amount_cents
    if o["balance_cents"] == 0:
        o["status"] = "REPAID"
    _bump(o, now)

    _recompute_lifetime_overpayment(claim["claimant_id"])
    return o


def waive_overpayment(overpayment_id: str, version: Optional[int]) -> Dict[str, Any]:
    o = _overpayment_exists(overpayment_id)
    if o["status"] != "OUTSTANDING":
        raise APIError("ERR_INVALID_STATE", f"Cannot waive an Overpayment in state {o['status']}", 409)
    if o["classification"] == "FRAUD":
        raise APIError("ERR_FRAUD_NOT_WAIVABLE", "FRAUD overpayments cannot be waived", 403)
    _check_occ(o, version)

    claim = _claim_exists(o["claim_id"])
    now = now_iso()
    o["balance_cents"] = 0
    o["status"] = "WAIVED"
    _bump(o, now)

    _recompute_lifetime_overpayment(claim["claimant_id"])
    return o


def write_off_overpayment(overpayment_id: str, version: Optional[int]) -> Dict[str, Any]:
    o = _overpayment_exists(overpayment_id)
    if o["status"] != "OUTSTANDING":
        raise APIError("ERR_INVALID_STATE", f"Cannot write off an Overpayment in state {o['status']}", 409)

    created_dt = parse_iso8601(o["created_at"])
    if created_dt is None:
        raise APIError("ERR_VALIDATION_FAILED", "Bad overpayment created_at", 422)
    elapsed_days = (now_dt() - created_dt).days
    if elapsed_days < calc.STATUTE_OF_LIMITATIONS_DAYS:
        raise APIError(
            "ERR_STATUTE_NOT_REACHED",
            "Statute of limitations has not yet elapsed",
            409,
        )
    _check_occ(o, version)

    claim = _claim_exists(o["claim_id"])
    now = now_iso()
    o["balance_cents"] = 0
    o["status"] = "WRITTEN_OFF"
    _bump(o, now)

    _recompute_lifetime_overpayment(claim["claimant_id"])
    return o


# -----------------------------------------------------------------------------
# Appeals
# -----------------------------------------------------------------------------
def _resolve_subject_for_appeal(
    subject_type: str, subject_id: str
) -> Tuple[Dict[str, Any], Optional[str], Optional[str]]:
    """Return (subject_entity, adjudicator_id, decision_at) for the appeal subject.

    The subject_entity is the Claim / Certification / Overpayment row.
    The adjudicator_id is the Adjudicator who decided the subject:
      - For MONETARY_DETERMINATION: claim.assigned_adjudicator_id
      - For WEEKLY_DENIAL: the decision is the claim's adjudicator (the same
        adjudicator who would later audit weeks); per scaffold, we copy the
        adjudicator who decided the subject -> for a WEEKLY_DENIAL the system
        is the deciding "actor" so we copy the claim's assigned_adjudicator_id
        (the agency officer of record for that claim).
      - For OVERPAYMENT_ASSESSMENT: the audit was issued by an Adjudicator;
        we copy the claim's assigned_adjudicator_id (it is the same agency).
    """
    store = get_store()
    if subject_type == "MONETARY_DETERMINATION":
        cl = store.claims.get(subject_id)
        if cl is None:
            raise APIError("ERR_NOT_FOUND", f"Claim '{subject_id}' not found", 404)
        return cl, cl.get("assigned_adjudicator_id"), cl.get("decision_at")
    if subject_type == "WEEKLY_DENIAL":
        cert = store.weekly_certifications.get(subject_id)
        if cert is None:
            raise APIError("ERR_NOT_FOUND", f"WeeklyCertification '{subject_id}' not found", 404)
        cl = store.claims.get(cert["claim_id"])
        adj_id = cl.get("assigned_adjudicator_id") if cl else None
        return cert, adj_id, cert.get("updated_at")
    if subject_type == "OVERPAYMENT_ASSESSMENT":
        o = store.overpayments.get(subject_id)
        if o is None:
            raise APIError("ERR_NOT_FOUND", f"Overpayment '{subject_id}' not found", 404)
        cl = store.claims.get(o["claim_id"])
        adj_id = cl.get("assigned_adjudicator_id") if cl else None
        return o, adj_id, o.get("created_at")
    raise APIError("ERR_VALIDATION_FAILED", "Invalid subject_type", 422)


def file_appeal(
    claim_id: str,
    subject_type: str,
    subject_id: str,
    assigned_appeal_officer_id: str,
    acting_user_id: str,
) -> Dict[str, Any]:
    store = get_store()
    claim = _claim_exists(claim_id)
    if claim["claimant_id"] != acting_user_id:
        raise APIError("ERR_NOT_OWNER", "Claimant does not own this Claim", 403)

    if subject_type not in {"MONETARY_DETERMINATION", "WEEKLY_DENIAL", "OVERPAYMENT_ASSESSMENT"}:
        raise APIError("ERR_VALIDATION_FAILED", "subject_type invalid", 422)

    subj, adjudicator_id, decision_at = _resolve_subject_for_appeal(subject_type, subject_id)

    # Subject must belong to the named claim.
    if subject_type == "MONETARY_DETERMINATION":
        if subj["id"] != claim_id:
            raise APIError("ERR_NOT_FOUND", "Subject does not belong to claim", 404)
    elif subject_type == "WEEKLY_DENIAL":
        if subj["claim_id"] != claim_id:
            raise APIError("ERR_NOT_FOUND", "Subject does not belong to claim", 404)
    elif subject_type == "OVERPAYMENT_ASSESSMENT":
        if subj["claim_id"] != claim_id:
            raise APIError("ERR_NOT_FOUND", "Subject does not belong to claim", 404)

    # Uniqueness on (subject_type, subject_id).
    if (subject_type, subject_id) in store.appeal_unique:
        raise APIError(
            "ERR_APPEAL_ALREADY_FILED",
            "An Appeal already exists for this subject",
            409,
        )

    now = now_iso()
    now_d = now_dt()
    filed_at = now
    # deadline_at = filed_at + 30 days
    deadline_dt = now_d
    from datetime import timedelta
    deadline_dt = now_d + timedelta(days=calc.APPEAL_WINDOW_DAYS)
    deadline_iso = (
        deadline_dt.strftime("%Y-%m-%dT%H:%M:%S")
        + f".{deadline_dt.microsecond // 1000:03d}Z"
    )

    appeal = _new_common(now)
    appeal.update({
        "claim_id": claim_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "subject_locked_version": subj.get("version", 1),
        "assigned_adjudicator_id": adjudicator_id,
        "assigned_appeal_officer_id": assigned_appeal_officer_id,
        "filed_at": filed_at,
        "deadline_at": deadline_iso,
        "status": "FILED",
        "decision_at": None,
    })

    # Late check: if decision_at + APPEAL_WINDOW_DAYS < now, immediately DISMISSED_LATE.
    if decision_at:
        dec_dt = parse_iso8601(decision_at)
        if dec_dt is not None and (now_d - dec_dt).days > calc.APPEAL_WINDOW_DAYS:
            # PRD §3.6: "the surfaced error path is ERR_APPEAL_WINDOW_EXPIRED"
            raise APIError(
                "ERR_APPEAL_WINDOW_EXPIRED",
                "Appeal filed past the appeal window",
                409,
            )

    store.appeals[appeal["id"]] = appeal
    store.appeal_unique[(subject_type, subject_id)] = appeal["id"]
    return appeal


def start_hearing(appeal_id: str, acting_user_id: str) -> Dict[str, Any]:
    a = _appeal_exists(appeal_id)
    if a["status"] != "FILED":
        raise APIError("ERR_INVALID_STATE", f"Cannot start hearing on Appeal in state {a['status']}", 409)
    if a.get("assigned_adjudicator_id") and acting_user_id == a["assigned_adjudicator_id"]:
        raise APIError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            "AppealOfficer cannot be the same person as the assigned adjudicator",
            403,
        )
    if acting_user_id != a["assigned_appeal_officer_id"]:
        raise APIError("ERR_FORBIDDEN", "AppealOfficer is not assigned to this appeal", 403)

    deadline_dt = parse_iso8601(a["deadline_at"])
    if deadline_dt is not None and now_dt() > deadline_dt:
        # Auto-dismiss; clients should never get here if sweep ran, but be defensive.
        a["status"] = "DISMISSED_LATE"
        _bump(a, now_iso())
        return a

    now = now_iso()
    a["status"] = "IN_HEARING"
    _bump(a, now)
    return a


def decide_appeal(
    appeal_id: str,
    decision: str,
    acting_user_id: str,
    version: Optional[int],
) -> Dict[str, Any]:
    store = get_store()
    a = _appeal_exists(appeal_id)
    if a["status"] != "IN_HEARING":
        raise APIError("ERR_INVALID_STATE", f"Cannot decide Appeal in state {a['status']}", 409)
    if a.get("assigned_adjudicator_id") and acting_user_id == a["assigned_adjudicator_id"]:
        raise APIError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            "AppealOfficer cannot be the same person as the assigned adjudicator",
            403,
        )
    if acting_user_id != a["assigned_appeal_officer_id"]:
        raise APIError("ERR_FORBIDDEN", "AppealOfficer is not assigned to this appeal", 403)

    if decision not in {"SUSTAINED", "REVERSED"}:
        raise APIError("ERR_VALIDATION_FAILED", "decision must be SUSTAINED or REVERSED", 422)

    # Version-pin check on the subject.
    subj, _adj, _dec = _resolve_subject_for_appeal(a["subject_type"], a["subject_id"])
    current_subject_version = subj.get("version", 1)
    if current_subject_version != a["subject_locked_version"]:
        raise APIError(
            "ERR_STALE_APPEAL_SUBJECT",
            "Subject entity version has changed since appeal was filed",
            409,
        )

    _check_occ(a, version)

    now = now_iso()
    if decision == "SUSTAINED":
        a["status"] = "SUSTAINED"
        a["decision_at"] = now
        _bump(a, now)
        return a

    # REVERSED -> apply remedy per subject_type.
    a["status"] = "REVERSED"
    a["decision_at"] = now
    _bump(a, now)

    if a["subject_type"] == "MONETARY_DETERMINATION":
        # Claim DENIED -> MONETARILY_ELIGIBLE
        cl = store.claims.get(a["subject_id"])
        if cl is not None and cl["status"] == "DENIED":
            cl["status"] = "MONETARILY_ELIGIBLE"
            cl["weeks_remaining"] = cl["max_weeks_of_eligibility"]
            _bump(cl, now)
    elif a["subject_type"] == "WEEKLY_DENIAL":
        cert = store.weekly_certifications.get(a["subject_id"])
        if cert is not None and cert["status"] == "DENIED":
            claim = store.claims.get(cert["claim_id"])
            if claim is not None:
                _approve_certification(cert, claim, now)
    elif a["subject_type"] == "OVERPAYMENT_ASSESSMENT":
        o = store.overpayments.get(a["subject_id"])
        if o is not None and o["status"] == "OUTSTANDING":
            claim = store.claims.get(o["claim_id"])
            o["balance_cents"] = 0
            o["status"] = "WAIVED"
            _bump(o, now)
            if claim is not None:
                _recompute_lifetime_overpayment(claim["claimant_id"])

    return a


def withdraw_appeal(appeal_id: str, acting_user_id: str) -> Dict[str, Any]:
    store = get_store()
    a = _appeal_exists(appeal_id)
    claim = store.claims.get(a["claim_id"])
    if claim is None or claim["claimant_id"] != acting_user_id:
        raise APIError("ERR_NOT_OWNER", "Claimant does not own this Appeal", 403)
    if a["status"] != "FILED":
        raise APIError("ERR_INVALID_STATE", f"Cannot withdraw an Appeal in state {a['status']}", 409)
    now = now_iso()
    a["status"] = "WITHDRAWN"
    _bump(a, now)
    return a


# -----------------------------------------------------------------------------
# EmployerCharge relief
# -----------------------------------------------------------------------------
def relieve_charge(
    employer_id: str,
    charge_id: str,
    reason: str,
    acting_role: str,
    acting_user_id: str,
) -> Dict[str, Any]:
    store = get_store()
    _employer_exists(employer_id)
    ch = store.employer_charges.get(charge_id)
    if ch is None or ch["employer_id"] != employer_id:
        raise APIError("ERR_NOT_FOUND", f"EmployerCharge '{charge_id}' not found", 404)

    # EmployerAgent must own the employer.
    if acting_role == "EmployerAgent" and acting_user_id != employer_id:
        raise APIError("ERR_NOT_OWNER", "EmployerAgent does not own this Employer", 403)

    if ch["status"] != "ACTIVE":
        raise APIError("ERR_INVALID_STATE", f"Cannot relieve charge in state {ch['status']}", 409)

    now = now_iso()
    ch["status"] = "RELIEVED"
    _bump(ch, now)
    _recompute_employer_rate(employer_id)
    return ch


# -----------------------------------------------------------------------------
# PandemicExtension
# -----------------------------------------------------------------------------
def create_pandemic_extension(payload: Dict[str, Any]) -> Dict[str, Any]:
    store = get_store()
    eff_start = parse_iso_date(payload["effective_start"])
    eff_end = parse_iso_date(payload["effective_end"])
    if eff_start is None or eff_end is None:
        raise APIError("ERR_VALIDATION_FAILED", "effective_start/effective_end must be valid ISO dates", 422)
    if eff_end < eff_start:
        raise APIError("ERR_VALIDATION_FAILED", "effective_end must be >= effective_start", 422)

    now = now_iso()
    entity = _new_common(now)
    entity.update({
        "program_name": payload["program_name"],
        "effective_start": payload["effective_start"],
        "effective_end": payload["effective_end"],
        "extra_weeks": payload["extra_weeks"],
        "status": "SCHEDULED",
    })
    # If we're already past effective_start at creation time, activate immediately.
    now_d = now_dt().date()
    if now_d > eff_end:
        entity["status"] = "EXPIRED"
    elif now_d >= eff_start:
        entity["status"] = "ACTIVE"
    store.pandemic_extensions[entity["id"]] = entity
    return entity
