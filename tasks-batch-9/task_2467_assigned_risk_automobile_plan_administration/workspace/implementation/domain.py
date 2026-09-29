"""Derived state, cascades, the carrier selector and the resource serialisers."""

from decimal import Decimal

import calc
from store import db, days, new_row, touch, whole_days

ACTIVE_ASSIGNMENT_STATUSES = ("PENDING_ACCEPTANCE", "ACCEPTED", "POLICY_ISSUED")
LIVE_POLICY_STATUSES = ("IN_FORCE", "REASSIGNMENT_PENDING", "NON_RENEWAL_PENDING")
COUNTED_APPLICATION_STATUSES = (
    "CERTIFIED_AWAITING_ASSIGNMENT",
    "DEFERRED_NO_CARRIER",
    "ASSIGNED",
    "POLICY_ISSUED",
    "CLOSED_EXITED",
    "CLOSED_CANCELLED",
)


# --------------------------------------------------------------- formatting
def iso(value):
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def f1(value):
    return float(calc.dec1(value))


def f2(value):
    return float(calc.rhu(value, 2))


def f4(value):
    return float(calc.dec4(value))


# ------------------------------------------------------------- plan periods
def period_contains(period, instant):
    return period["window_start"] <= instant <= period["window_end"]


def current_period():
    """The plan period the live derivations read (OPEN, else RECONCILING)."""
    candidates = [
        p for p in db.plan_periods.values() if p["status"] in ("OPEN", "RECONCILING")
    ]
    if not candidates:
        return None

    def key(period):
        return (
            1 if period_contains(period, db.clock) else 0,
            1 if period["status"] == "OPEN" else 0,
            period["window_start"],
            period["_seq"],
        )

    return max(candidates, key=key)


def open_period_for_clock():
    for period in db.plan_periods.values():
        if period["status"] == "OPEN" and period_contains(period, db.clock):
            return period
    return None


def period_for_instant(instant):
    for period in db.plan_periods.values():
        if period_contains(period, instant):
            return period
    return None


def period_total_assignable_units(period):
    if period.get("_frozen_units") is not None:
        return period["_frozen_units"]
    return _live_total_assignable_units(period)


def _live_total_assignable_units(period):
    count = 0
    for app in db.applications.values():
        if app["certified_at"] is None:
            continue
        if app["status"] not in COUNTED_APPLICATION_STATUSES:
            continue
        if period_contains(period, app["certified_at"]):
            count += 1
    return count


def policy_car_years(policy, period):
    low = max(policy["effective_date"], period["window_start"])
    high = min(
        policy["expiration_date"], period["window_end"] + days(1), db.clock
    )
    return calc.car_years(whole_days(high, low))


def carrier_car_years(carrier, period):
    total = Decimal("0.0000")
    for policy in db.policies.values():
        if policy["carrier_id"] != carrier["id"]:
            continue
        if policy["policy_status"] == "CANCELLED":
            continue
        total += policy_car_years(policy, period)
    return calc.dec4(total)


def period_total_car_years(period):
    if period.get("_frozen_car_years") is not None:
        return period["_frozen_car_years"]
    total = Decimal("0.0000")
    for carrier in db.carriers.values():
        if carrier["status"] != "ACTIVE":
            continue
        total += carrier_car_years(carrier, period)
    return calc.dec4(total)


# ------------------------------------------------------------------ carrier
def carrier_assigned_risk_count(carrier):
    return sum(
        1
        for a in db.assignments.values()
        if a["carrier_id"] == carrier["id"] and a["status"] in ACTIVE_ASSIGNMENT_STATUSES
    )


def carrier_upheld_complaint_count(carrier):
    return sum(
        1
        for c in db.complaints.values()
        if c["carrier_id"] == carrier["id"] and c["status"] == "RESOLVED_UPHELD"
    )


def carrier_penalty_balance(carrier):
    return sum(
        r["penalty_cents"]
        for r in db.reconciliations.values()
        if r["carrier_id"] == carrier["id"] and r["status"] == "FINAL"
    )


def quota_targets():
    """Largest-remainder apportionment across the ACTIVE carriers."""
    actives = [c for c in db.carriers.values() if c["status"] == "ACTIVE"]
    period = current_period()
    total = period_total_assignable_units(period) if period else 0
    entries = [
        (c["id"], c["voluntary_market_share_bps"], c["enrollment_sequence"])
        for c in actives
    ]
    return calc.largest_remainder(total, entries)


def carrier_quota_target(carrier, targets=None):
    if carrier["status"] != "ACTIVE":
        return 0
    if targets is None:
        targets = quota_targets()
    return targets.get(carrier["id"], 0)


def carrier_variance(carrier, targets=None):
    assigned = carrier_assigned_risk_count(carrier)
    credit = carrier["voluntary_credit_units"]
    target = carrier_quota_target(carrier, targets)
    return calc.dec1(Decimal(assigned) + credit - Decimal(target))


def carrier_overallocated(carrier, targets=None):
    return carrier_variance(carrier, targets) > 0


def carrier_posture(carrier, targets=None):
    return calc.posture_for(
        carrier["status"],
        carrier["performance_score"],
        carrier["breach_count_current_period"],
        carrier_overallocated(carrier, targets),
    )


def adjust_score(carrier, delta):
    carrier["performance_score"] = calc.clamp_score(carrier["performance_score"] + delta)
    touch(carrier)


# ---------------------------------------------------------------- applicant
def applicant_chargeable_events(applicant):
    events = []
    app_ids = set()
    for app in db.applications.values():
        if app["applicant_id"] != applicant["id"]:
            continue
        app_ids.add(app["id"])
        if app["mvr_verified_at"] is not None and app["verified_violations"]:
            for violation in app["verified_violations"]:
                events.append(violation["conviction_date"])
    policy_ids = set()
    for policy in db.policies.values():
        if policy["_application_id"] in app_ids:
            policy_ids.add(policy["id"])
    for claim in db.claims.values():
        if claim["policy_id"] in policy_ids and claim["at_fault"]:
            events.append(claim["loss_date"])
    return events


def applicant_last_chargeable_event(applicant):
    events = applicant_chargeable_events(applicant)
    if not events:
        return applicant["first_licensed_date"]
    return max(events)


def applicant_clean_years(applicant):
    return calc.clean_years(db.clock, applicant_last_chargeable_event(applicant))


# -------------------------------------------------------------- application
def app_distinct_rejection_count(application):
    lower = db.clock - days(calc.VOLUNTARY_REJECTION_LOOKBACK_DAYS)
    codes = set()
    for rejection in db.market_rejections.values():
        if rejection["application_id"] != application["id"]:
            continue
        if lower <= rejection["rejection_date"] <= db.clock:
            codes.add(rejection["rejecting_carrier_naic_code"])
    return len(codes)


def application_violation_source(application):
    if application["mvr_verified_at"] is not None:
        return application["verified_violations"] or []
    return application["declared_violations"] or []


def recompute_estimate(application, rating_date=None):
    rating_date = rating_date or db.clock
    applicant = db.applicants[application["applicant_id"]]
    vehicle = db.vehicles[application["vehicle_id"]]
    points, factor, lines, final, charge, total = calc.rate(
        vehicle["garaging_territory_code"],
        vehicle["vehicle_class_code"],
        application_violation_source(application),
        applicant["driver_class"],
        rating_date,
    )
    application["surcharge_points_estimated"] = points
    application["estimated_annual_premium_cents"] = final
    application["estimated_expense_charge_cents"] = charge
    application["estimated_total_charge_cents"] = total


def recompute_required_deposit(application):
    application["required_deposit_cents"] = calc.required_deposit(
        application["estimated_total_charge_cents"]
    )


def application_policy(application):
    """The policy issued for this application, if any."""
    best = None
    for policy in db.policies.values():
        if policy["_application_id"] != application["id"]:
            continue
        if best is None or policy["_seq"] > best["_seq"]:
            best = policy
    return best


# ------------------------------------------------------------------- policy
def policy_application(policy):
    return db.applications[policy["_application_id"]]


def policy_open_complaint_count(policy):
    return sum(
        1
        for c in db.complaints.values()
        if c["policy_id"] == policy["id"] and c["status"] in ("OPEN", "FINDINGS_RECORDED")
    )


def policy_freeze_active(policy):
    return policy_open_complaint_count(policy) > 0


def derive_money_axis(policy):
    """Money axis for a live policy: PAID_IN_FULL vs PREMIUM_OUTSTANDING."""
    total = policy["total_annual_charge_cents"]
    credited = policy["premium_credited_cents"]
    policy["additional_premium_due_cents"] = max(0, total - credited)
    policy["premium_settlement_status"] = (
        "PAID_IN_FULL" if credited >= total else "PREMIUM_OUTSTANDING"
    )


def sweep_deposit(application, policy):
    """Move available deposit money into the policy's credited premium."""
    room = policy["total_annual_charge_cents"] - policy["premium_credited_cents"]
    if room <= 0:
        return 0
    amount = min(application["deposit_balance_cents"], room)
    if amount <= 0:
        return 0
    application["deposit_balance_cents"] -= amount
    policy["premium_credited_cents"] += amount
    return amount


def rate_policy(policy, driver_class=None):
    application = policy_application(policy)
    applicant = db.applicants[application["applicant_id"]]
    vehicle = db.vehicles[application["vehicle_id"]]
    points, factor, lines, final, charge, total = calc.rate(
        vehicle["garaging_territory_code"],
        vehicle["vehicle_class_code"],
        application_violation_source(application),
        driver_class or applicant["driver_class"],
        policy["effective_date"],
    )
    policy["surcharge_points_applied"] = points
    policy["surcharge_factor_applied"] = factor
    policy["premium_lines"] = lines
    policy["final_premium_cents"] = final
    policy["plan_expense_charge_cents"] = charge
    policy["total_annual_charge_cents"] = total


def policy_exposure_car_years(policy):
    period = current_period()
    if period is None:
        return Decimal("0.0000")
    return policy_car_years(policy, period)


def current_assignment(policy):
    return db.assignments.get(policy["_current_assignment_id"])


def close_policy_assignment(policy):
    assignment = current_assignment(policy)
    if assignment is not None and assignment["status"] in ACTIVE_ASSIGNMENT_STATUSES:
        assignment["status"] = "CLOSED"
        touch(assignment)
        carrier = db.carriers.get(assignment["carrier_id"])
        touch(carrier)


def mature_non_renewals():
    """A served non-renewal notice matures with the clock (PRD Section 2.12)."""
    for policy in list(db.policies.values()):
        if policy["policy_status"] != "NON_RENEWAL_PENDING":
            continue
        effective = policy["non_renewal_effective_date"]
        if effective is None or db.clock < effective:
            continue
        policy["policy_status"] = "NON_RENEWED"
        touch(policy)
        close_policy_assignment(policy)


def bubble_exit_complete(carrier):
    if carrier is None or carrier["status"] != "EXIT_NOTICED":
        return
    for policy in db.policies.values():
        if policy["carrier_id"] == carrier["id"] and policy["policy_status"] in LIVE_POLICY_STATUSES:
            return
    carrier["status"] = "EXIT_COMPLETE"
    touch(carrier)


def bubble_period_closed(period):
    if period["status"] != "RECONCILING":
        return
    actives = [c for c in db.carriers.values() if c["status"] == "ACTIVE"]
    if not actives:
        return
    for carrier in actives:
        found = False
        for reconciliation in db.reconciliations.values():
            if (
                reconciliation["carrier_id"] == carrier["id"]
                and reconciliation["plan_period_id"] == period["id"]
                and reconciliation["status"] == "FINAL"
            ):
                found = True
                break
        if not found:
            return
    period["status"] = "CLOSED"
    touch(period)


# ----------------------------------------------------------------- selector
def select_carrier(territory_code, excluded_carrier_id=None):
    """Greatest unmet quota first (PRD Section 3.3).  Returns (carrier, deficit)."""
    targets = quota_targets()
    candidates = []
    for carrier in db.carriers.values():
        if carrier["status"] != "ACTIVE":
            continue
        if carrier_posture(carrier, targets) != "OPEN":
            continue
        if territory_code not in carrier["licensed_territories"]:
            continue
        if excluded_carrier_id is not None and carrier["id"] == excluded_carrier_id:
            continue
        candidates.append(carrier)
    if not candidates:
        return None, None
    scored = []
    for carrier in candidates:
        deficit = carrier_quota_target(carrier, targets) - carrier_assigned_risk_count(carrier)
        scored.append((carrier, deficit))
    scored.sort(
        key=lambda item: (
            -item[1],
            -item[0]["voluntary_market_share_bps"],
            item[0]["created_at"],
            item[0]["enrollment_sequence"],
        )
    )
    return scored[0][0], scored[0][1]


def create_assignment(
    application,
    carrier,
    deficit,
    batch_sequence,
    assignment_kind,
    assignment_cycle_id=None,
    predecessor_assignment_id=None,
):
    row = new_row()
    row.update(
        {
            "application_id": application["id"],
            "carrier_id": carrier["id"],
            "assignment_cycle_id": assignment_cycle_id,
            "predecessor_assignment_id": predecessor_assignment_id,
            "batch_sequence": batch_sequence,
            "assignment_kind": assignment_kind,
            "status": "PENDING_ACCEPTANCE",
            "acceptance_deadline": row["created_at"] + days(calc.ACCEPTANCE_WINDOW_DAYS),
            "accepted_at": None,
            "deficit_score_at_selection": calc.dec1(Decimal(deficit)),
            "provisional_premium_cents": application["estimated_total_charge_cents"],
            "rescission_reason_code": None,
        }
    )
    db.assignments[row["id"]] = row
    touch(carrier)  # assigned_risk_count moved -> Section 2.12 propagation
    return row


def rescind_pending_assignments(carrier, reason_code):
    """Cascade used by the exit notice and by a posture fall to SUSPENDED."""
    rescinded = []
    pending = [
        a
        for a in db.assignments.values()
        if a["carrier_id"] == carrier["id"] and a["status"] == "PENDING_ACCEPTANCE"
    ]
    pending.sort(key=lambda a: (a["created_at"], a["batch_sequence"], a["_seq"]))
    for assignment in pending:
        assignment["status"] = "RESCINDED"
        assignment["rescission_reason_code"] = reason_code
        touch(assignment)
        application = db.applications.get(assignment["application_id"])
        if application is not None and application["status"] == "ASSIGNED":
            application["status"] = "CERTIFIED_AWAITING_ASSIGNMENT"
            touch(application)
        rescinded.append(assignment)
    if rescinded:
        touch(carrier)
    return rescinded


def apply_suspension_cascade(carrier):
    if carrier_posture(carrier) == "SUSPENDED":
        rescind_pending_assignments(carrier, "CARRIER_INELIGIBLE")


# -------------------------------------------------------------- serialisers
def carrier_out(carrier):
    targets = quota_targets()
    target = carrier_quota_target(carrier, targets)
    variance = carrier_variance(carrier, targets)
    return {
        "id": carrier["id"],
        "created_at": iso(carrier["created_at"]),
        "updated_at": iso(carrier["updated_at"]),
        "version": carrier["version"],
        "name": carrier["name"],
        "naic_code": carrier["naic_code"],
        "voluntary_market_share_bps": carrier["voluntary_market_share_bps"],
        "licensed_territories": list(carrier["licensed_territories"]),
        "enrollment_sequence": carrier["enrollment_sequence"],
        "status": carrier["status"],
        "exit_effective_date": iso(carrier["exit_effective_date"]),
        "performance_score": carrier["performance_score"],
        "breach_count_current_period": carrier["breach_count_current_period"],
        "upheld_complaint_count": carrier_upheld_complaint_count(carrier),
        "non_renewal_count_current_period": carrier["non_renewal_count_current_period"],
        "assigned_risk_count": carrier_assigned_risk_count(carrier),
        "voluntary_credit_units": f1(carrier["voluntary_credit_units"]),
        "quota_target_units": target,
        "quota_variance_units": f1(variance),
        "overallocated": variance > 0,
        "posture": carrier_posture(carrier, targets),
        "penalty_balance_cents": carrier_penalty_balance(carrier),
    }


def producer_out(producer):
    return {
        "id": producer["id"],
        "created_at": iso(producer["created_at"]),
        "updated_at": iso(producer["updated_at"]),
        "version": producer["version"],
        "name": producer["name"],
        "license_number": producer["license_number"],
        "appointed_territories": list(producer["appointed_territories"]),
        "status": producer["status"],
    }


def applicant_out(applicant):
    last_event = applicant_last_chargeable_event(applicant)
    return {
        "id": applicant["id"],
        "created_at": iso(applicant["created_at"]),
        "updated_at": iso(applicant["updated_at"]),
        "version": applicant["version"],
        "full_name": applicant["full_name"],
        "driver_license_number": applicant["driver_license_number"],
        "territory_code": applicant["territory_code"],
        "driver_class": applicant["driver_class"],
        "first_licensed_date": iso(applicant["first_licensed_date"]),
        "last_chargeable_event_date": iso(last_event),
        "clean_years_credited": calc.clean_years(db.clock, last_event),
        "voluntary_market_eligible": applicant["voluntary_market_eligible"],
    }


def vehicle_out(vehicle):
    return {
        "id": vehicle["id"],
        "created_at": iso(vehicle["created_at"]),
        "updated_at": iso(vehicle["updated_at"]),
        "version": vehicle["version"],
        "applicant_id": vehicle["applicant_id"],
        "vin": vehicle["vin"],
        "vehicle_class_code": vehicle["vehicle_class_code"],
        "garaging_territory_code": vehicle["garaging_territory_code"],
        "model_year": vehicle["model_year"],
    }


def _violations_out(violations):
    if violations is None:
        return None
    return [
        {"code": v["code"], "conviction_date": iso(v["conviction_date"])}
        for v in violations
    ]


def application_out(application):
    return {
        "id": application["id"],
        "created_at": iso(application["created_at"]),
        "updated_at": iso(application["updated_at"]),
        "version": application["version"],
        "applicant_id": application["applicant_id"],
        "producer_id": application["producer_id"],
        "vehicle_id": application["vehicle_id"],
        "intake_sequence": application["intake_sequence"],
        "requested_effective_date": iso(application["requested_effective_date"]),
        "declared_violations": _violations_out(application["declared_violations"]),
        "verified_violations": _violations_out(application["verified_violations"]),
        "mvr_verified_at": iso(application["mvr_verified_at"]),
        "status": application["status"],
        "cure_count": application["cure_count"],
        "certified_at": iso(application["certified_at"]),
        "certified_by_user_id": application["certified_by_user_id"],
        "rejection_reason_code": application["rejection_reason_code"],
        "distinct_rejection_count": app_distinct_rejection_count(application),
        "surcharge_points_estimated": application["surcharge_points_estimated"],
        "estimated_annual_premium_cents": application["estimated_annual_premium_cents"],
        "estimated_expense_charge_cents": application["estimated_expense_charge_cents"],
        "estimated_total_charge_cents": application["estimated_total_charge_cents"],
        "required_deposit_cents": application["required_deposit_cents"],
        "deposit_paid_total_cents": application["deposit_paid_total_cents"],
        "deposit_balance_cents": application["deposit_balance_cents"],
    }


def market_rejection_out(rejection):
    # An immutable evidentiary filing: id and created_at only (PRD Section 2.4).
    return {
        "id": rejection["id"],
        "created_at": iso(rejection["created_at"]),
        "application_id": rejection["application_id"],
        "rejecting_carrier_naic_code": rejection["rejecting_carrier_naic_code"],
        "rejection_date": iso(rejection["rejection_date"]),
        "reason_code": rejection["reason_code"],
        "document_reference": rejection["document_reference"],
    }


def plan_period_out(period):
    return {
        "id": period["id"],
        "created_at": iso(period["created_at"]),
        "updated_at": iso(period["updated_at"]),
        "version": period["version"],
        "period_code": period["period_code"],
        "window_start": iso(period["window_start"]),
        "window_end": iso(period["window_end"]),
        "underserved_territories": list(period["underserved_territories"]),
        "status": period["status"],
        "total_assignable_units": period_total_assignable_units(period),
        "total_assignable_car_years": f4(period_total_car_years(period)),
    }


def cycle_out(cycle):
    return {
        "id": cycle["id"],
        "created_at": iso(cycle["created_at"]),
        "updated_at": iso(cycle["updated_at"]),
        "version": cycle["version"],
        "plan_period_id": cycle["plan_period_id"],
        "window_start": iso(cycle["window_start"]),
        "window_end": iso(cycle["window_end"]),
        "status": cycle["status"],
        "assigned_count": cycle["assigned_count"],
        "deferred_count": cycle["deferred_count"],
        "run_at": iso(cycle["run_at"]),
    }


def assignment_out(assignment):
    return {
        "id": assignment["id"],
        "created_at": iso(assignment["created_at"]),
        "updated_at": iso(assignment["updated_at"]),
        "version": assignment["version"],
        "application_id": assignment["application_id"],
        "carrier_id": assignment["carrier_id"],
        "assignment_cycle_id": assignment["assignment_cycle_id"],
        "predecessor_assignment_id": assignment["predecessor_assignment_id"],
        "batch_sequence": assignment["batch_sequence"],
        "assignment_kind": assignment["assignment_kind"],
        "status": assignment["status"],
        "acceptance_deadline": iso(assignment["acceptance_deadline"]),
        "accepted_at": iso(assignment["accepted_at"]),
        "deficit_score_at_selection": f1(assignment["deficit_score_at_selection"]),
        "provisional_premium_cents": assignment["provisional_premium_cents"],
        "rescission_reason_code": assignment["rescission_reason_code"],
    }


def policy_out(policy):
    open_complaints = policy_open_complaint_count(policy)
    return {
        "id": policy["id"],
        "created_at": iso(policy["created_at"]),
        "updated_at": iso(policy["updated_at"]),
        "version": policy["version"],
        "assignment_id": policy["assignment_id"],
        "carrier_id": policy["carrier_id"],
        "policy_number": policy["policy_number"],
        "effective_date": iso(policy["effective_date"]),
        "expiration_date": iso(policy["expiration_date"]),
        "policy_status": policy["policy_status"],
        "premium_settlement_status": policy["premium_settlement_status"],
        "surcharge_points_applied": policy["surcharge_points_applied"],
        "surcharge_factor_applied": f2(policy["surcharge_factor_applied"]),
        "premium_lines": dict(policy["premium_lines"]),
        "final_premium_cents": policy["final_premium_cents"],
        "plan_expense_charge_cents": policy["plan_expense_charge_cents"],
        "total_annual_charge_cents": policy["total_annual_charge_cents"],
        "premium_credited_cents": policy["premium_credited_cents"],
        "additional_premium_due_cents": policy["additional_premium_due_cents"],
        "refund_paid_cents": policy["refund_paid_cents"],
        "balance_due_cents": policy["balance_due_cents"],
        "earned_premium_cents": policy["earned_premium_cents"],
        "refund_basis": policy["refund_basis"],
        "cancellation_reason_code": policy["cancellation_reason_code"],
        "cancellation_effective_date": iso(policy["cancellation_effective_date"]),
        "cancellation_initiated_by": policy["cancellation_initiated_by"],
        "non_renewal_notice_count": policy["non_renewal_notice_count"],
        "non_renewal_effective_date": iso(policy["non_renewal_effective_date"]),
        "rating_revision": policy["rating_revision"],
        "reassignment_required": policy["reassignment_required"],
        "open_complaint_count": open_complaints,
        "complaint_freeze_active": open_complaints > 0,
        "exposure_car_years_current_period": f4(policy_exposure_car_years(policy)),
    }


def claim_out(claim):
    return {
        "id": claim["id"],
        "created_at": iso(claim["created_at"]),
        "updated_at": iso(claim["updated_at"]),
        "version": claim["version"],
        "policy_id": claim["policy_id"],
        "loss_date": iso(claim["loss_date"]),
        "at_fault": claim["at_fault"],
        "coverage_line": claim["coverage_line"],
        "reserve_cents": claim["reserve_cents"],
        "reported_at": iso(claim["reported_at"]),
        "acknowledgement_deadline": iso(claim["acknowledgement_deadline"]),
        "acknowledged_at": iso(claim["acknowledged_at"]),
        "status": claim["status"],
        "standard_breach": claim["standard_breach"],
        "paid_cents": claim["paid_cents"],
    }


def complaint_out(complaint):
    return {
        "id": complaint["id"],
        "created_at": iso(complaint["created_at"]),
        "updated_at": iso(complaint["updated_at"]),
        "version": complaint["version"],
        "policy_id": complaint["policy_id"],
        "carrier_id": complaint["carrier_id"],
        "complaint_type": complaint["complaint_type"],
        "narrative": complaint["narrative"],
        "status": complaint["status"],
        "findings_recorded_by_user_id": complaint["findings_recorded_by_user_id"],
        "findings_note": complaint["findings_note"],
        "resolved_by_user_id": complaint["resolved_by_user_id"],
        "disposition": complaint["disposition"],
        "review_round": complaint["review_round"],
    }


def reconciliation_out(reconciliation):
    if reconciliation["basis"] == "POLICY_COUNT":
        obligation = int(reconciliation["obligation_units"])
        credited = f1(reconciliation["credited_units"])
        variance = f1(reconciliation["variance_units"])
    else:
        obligation = f4(reconciliation["obligation_units"])
        credited = f4(reconciliation["credited_units"])
        variance = f4(reconciliation["variance_units"])
    return {
        "id": reconciliation["id"],
        "created_at": iso(reconciliation["created_at"]),
        "updated_at": iso(reconciliation["updated_at"]),
        "version": reconciliation["version"],
        "carrier_id": reconciliation["carrier_id"],
        "plan_period_id": reconciliation["plan_period_id"],
        "basis": reconciliation["basis"],
        "obligation_units": obligation,
        "credited_units": credited,
        "variance_units": variance,
        "voluntary_credit_units_applied": f1(
            reconciliation["voluntary_credit_units_applied"]
        ),
        "penalty_cents": reconciliation["penalty_cents"],
        "status": reconciliation["status"],
    }


# ----------------------------------------------------------------- listings
def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total


def sort_default(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_carriers(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["enrollment_sequence"], r["_seq"]))


def sort_applications(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["intake_sequence"], r["_seq"]))


def sort_assignments(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["batch_sequence"], r["_seq"]))
