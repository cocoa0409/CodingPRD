"""Shared domain operations: cascades, ledger re-derivation and lookups.

Because the aggregate ledgers are derived at read time (see serialize.py),
"re-derive the pool" here means "bump the parent row so its version and
updated_at record the mutation", which is exactly what PRD section 2.8 asks for.
"""

import calc
from errors import fail
from store import add_days, add_years, by_seq, db, fmt_iso, now_clock, parse_iso, touch


# ---- lookups --------------------------------------------------------------

def soft_get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return collection.get(row_id)


def get_or_404(collection, row_id, error_id):
    row = soft_get(collection, row_id)
    if row is None:
        fail(error_id)
    return row


def project_of_issue(issue):
    return soft_get(db.projects, issue.get("project_id")) if issue else None


def project_of_draw(draw):
    issue = soft_get(db.bond_issues, draw.get("bond_issue_id")) if draw else None
    return project_of_issue(issue)


def project_of_row(row):
    return soft_get(db.projects, row.get("project_id")) if row else None


def project_of_delivery(delivery):
    if delivery is None:
        return None
    allocation = soft_get(db.credit_allocations, delivery.get("credit_allocation_id"))
    return project_of_row(allocation)


def developer_of_project(project):
    return soft_get(db.developers, project.get("developer_id")) if project else None


def require_developer_active(project):
    """Ladder rule 8 (priority 80)."""
    developer = developer_of_project(project)
    if developer is None:
        return
    if developer.get("status") != "ACTIVE":
        fail("ERR_DEVELOPER_NOT_ACTIVE",
             "Sponsor standing is %s; project-advancing writes are frozen."
             % developer.get("status"))


# ---- cap pool -------------------------------------------------------------

def rederive_pool(pool):
    """Mark the pool as re-derived: version += 1, updated_at refreshed."""
    if pool is not None:
        touch(pool)
    return pool


def defer_on_exhaustion(pool, awarded_allocation):
    """PRD 3.3: an award that exhausts the pool defers the oversized pendings."""
    ledger = calc.pool_ledger(pool)
    if ledger["pool_status"] != "EXHAUSTED":
        return
    awardable = ledger["awardable_cents"]
    candidates = [a for a in calc.pool_allocations(pool["id"])
                  if a.get("status") == "PENDING" and a["id"] != awarded_allocation["id"]
                  and (a.get("requested_amount_cents") or 0) > awardable]
    for allocation in by_seq(candidates):
        allocation["status"] = "DEFERRED"
        touch(allocation)
        project = project_of_row(allocation)
        if project is not None:
            project["volume_cap_deferral_count"] = (
                project.get("volume_cap_deferral_count") or 0) + 1
            project["financing_stalled"] = True
            touch(project)


def reinstate_deferred(pool):
    """PRD 3.3: cap coming back reinstates every deferred request."""
    if calc.pool_ledger(pool)["pool_status"] == "EXHAUSTED":
        return
    deferred = [a for a in calc.pool_allocations(pool["id"])
                if a.get("status") == "DEFERRED"]
    for allocation in by_seq(deferred):
        allocation["status"] = "PENDING"
        touch(allocation)
        project = project_of_row(allocation)
        if project is not None:
            project["financing_stalled"] = False
            touch(project)


def live_allocation_exists(project_id):
    return any(a.get("status") in ("PENDING", "AWARDED", "COMMITTED")
               for a in calc.project_allocations(project_id))


def allocation_is_committed_to_issue(allocation):
    return any(b.get("status") in ("ISSUED", "CONVERTED", "MANDATORY_REDEEMED")
               for b in db.bond_issues.values()
               if b.get("volume_cap_allocation_id") == allocation["id"])


# ---- units ---------------------------------------------------------------

def refresh_unit_rent(unit, project):
    unit["restricted_rent_cents"] = calc.restricted_rent_ceiling(unit, project)


def rederive_project_from_units(project):
    """Every designation change re-derives the project counters (version += 1)."""
    touch(project)


def activate_units(project):
    """Conversion cascade: PROPOSED -> ACTIVE, refreshing restricted rents."""
    for unit in calc.project_units(project["id"]):
        if unit.get("status") == "PROPOSED":
            unit["status"] = "ACTIVE"
            refresh_unit_rent(unit, project)
            touch(unit)


def release_units(project):
    """Extended-use release cascade: ACTIVE -> RELEASED, rent cleared."""
    for unit in calc.project_units(project["id"]):
        if unit.get("status") == "ACTIVE":
            unit["status"] = "RELEASED"
            unit["restricted_rent_cents"] = None
            touch(unit)


def recorded_agreement(project_id):
    for agreement in by_seq(calc.project_agreements(project_id)):
        if agreement.get("status") == "RECORDED":
            return agreement
    return None


def release_agreement_and_units(project):
    agreement = recorded_agreement(project["id"])
    if agreement is not None:
        agreement["status"] = "RELEASED"
        touch(agreement)
    release_units(project)


# ---- conversion / stabilization cascade ---------------------------------

def stabilize_project(project, conversion_date_raw):
    """PRD 3.7 three-level cascade fired by a successful conversion."""
    project["development_status"] = "STABILIZED"
    project["compliance_start_date"] = conversion_date_raw
    touch(project)

    agreement = recorded_agreement(project["id"])
    start = parse_iso(conversion_date_raw)
    if agreement is not None and start is not None:
        compliance_end = fmt_iso(add_years(start, agreement.get("compliance_period_years") or 0))
        extended_end = fmt_iso(add_years(start, agreement.get("extended_use_years") or 0))
        agreement["compliance_period_end_date"] = compliance_end
        agreement["extended_use_end_date"] = extended_end
        touch(agreement)
        project["compliance_end_date"] = compliance_end
        project["extended_use_end_date"] = extended_end
    activate_units(project)


def restamp_extended_use(project, agreement):
    """Re-recording after an amendment refreshes the end dates when stabilized."""
    start = parse_iso(project.get("compliance_start_date"))
    if start is None:
        return
    compliance_end = fmt_iso(add_years(start, agreement.get("compliance_period_years") or 0))
    extended_end = fmt_iso(add_years(start, agreement.get("extended_use_years") or 0))
    agreement["compliance_period_end_date"] = compliance_end
    agreement["extended_use_end_date"] = extended_end
    project["compliance_end_date"] = compliance_end
    project["extended_use_end_date"] = extended_end


# ---- negative arbitrage -------------------------------------------------

def recompute_negative_arbitrage(issue):
    total, accruals = calc.negative_arbitrage_series(issue)
    for draw in calc.issue_draws(issue["id"]):
        if draw["id"] in accruals:
            new_value = accruals[draw["id"]]
            if draw.get("negative_arbitrage_accrual_cents") != new_value:
                draw["negative_arbitrage_accrual_cents"] = new_value
                touch(draw)
    issue["negative_arbitrage_cents"] = total


# ---- compliance cascades ------------------------------------------------

def noncompliance_cascade(project, shortfall_bps):
    """PRD 3.9: finding -> project axis -> credit allocation -> deliveries."""
    allocations = by_seq(calc.project_credit_allocations(project["id"]))

    already_pending = [a for a in allocations if a.get("status") == "RECAPTURE_PENDING"]
    if already_pending:
        # A second consecutive finding terminates the allocation.
        for allocation in already_pending:
            allocation["status"] = "RECAPTURED"
            touch(allocation)
        if project.get("compliance_status") == "RESTRICTED":
            project["compliance_status"] = "NONCOMPLIANT"
            touch(project)
        return

    if project.get("compliance_status") == "RESTRICTED":
        project["compliance_status"] = "NONCOMPLIANT"
        touch(project)

    for allocation in allocations:
        if allocation.get("status") != "ISSUED":
            continue
        allocation["status"] = "RECAPTURE_PENDING"
        allocation["recapture_amount_cents"] = calc.recapture_exposure(
            allocation.get("annual_credit_cents") or 0, shortfall_bps)
        touch(allocation)
        for delivery in by_seq(calc.allocation_deliveries(allocation["id"])):
            if delivery.get("status") == "ACCEPTED":
                delivery["status"] = "RECAPTURE_FLAGGED"
                touch(delivery)


def cure_cascade(project):
    """PRD 3.9: a later clearing report reverses the chain."""
    if project.get("compliance_status") != "NONCOMPLIANT":
        return
    project["compliance_status"] = "RESTRICTED"
    touch(project)
    for allocation in by_seq(calc.project_credit_allocations(project["id"])):
        if allocation.get("status") != "RECAPTURE_PENDING":
            continue
        allocation["status"] = "ISSUED"
        allocation["recapture_amount_cents"] = 0
        touch(allocation)
        for delivery in by_seq(calc.allocation_deliveries(allocation["id"])):
            if delivery.get("status") == "RECAPTURE_FLAGGED":
                delivery["status"] = "ACCEPTED"
                touch(delivery)


def triggering_report_year(project_id):
    """reporting_year of the finding that put the project in NONCOMPLIANT."""
    found = [r for r in calc.project_reports(project_id)
             if r.get("status") == "NONCOMPLIANCE_FOUND"]
    if not found:
        return None
    return max((r.get("reporting_year") or 0) for r in found)


# ---- the logical clock pass ---------------------------------------------

def advance_clock(new_instant, raw_value):
    """PRD 3.9: one pass over every time-gated transition, in the pinned order."""
    db.clock = new_instant
    db.clock_raw = raw_value

    # 1. awarded cap allocations whose expiry_date is now strictly past
    for allocation in by_seq(list(db.allocations.values())):
        if allocation.get("status") != "AWARDED":
            continue
        expiry = parse_iso(allocation.get("expiry_date"))
        if expiry is not None and new_instant > expiry:
            allocation["status"] = "EXPIRED"
            touch(allocation)
            pool = soft_get(db.cap_pools, allocation.get("cap_pool_id"))
            rederive_pool(pool)

    # 2. scheduled inspections whose window_end is now strictly past
    for inspection in by_seq(list(db.inspections.values())):
        if inspection.get("status") != "SCHEDULED":
            continue
        window_end = parse_iso(inspection.get("window_end"))
        if window_end is not None and new_instant > window_end:
            inspection["status"] = "MISSED"
            touch(inspection)

    # 3. the compliance axis rolls over
    for project in by_seq(list(db.projects.values())):
        if project.get("compliance_status") == "RESTRICTED":
            end = parse_iso(project.get("compliance_end_date"))
            if end is not None and new_instant > end:
                project["compliance_status"] = "EXTENDED_USE"
                touch(project)
        if project.get("compliance_status") == "EXTENDED_USE":
            end = parse_iso(project.get("extended_use_end_date"))
            if end is not None and new_instant > end:
                project["compliance_status"] = "RELEASED"
                touch(project)
                release_agreement_and_units(project)


def clock_stamp():
    return fmt_iso(now_clock())


def plus_days(raw_value, days):
    parsed = parse_iso(raw_value)
    if parsed is None:
        return None
    return fmt_iso(add_days(parsed, days))
