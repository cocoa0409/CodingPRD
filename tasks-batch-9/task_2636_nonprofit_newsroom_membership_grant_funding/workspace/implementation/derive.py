"""Derived-field recomputation and the cascade engines of §3.3, §3.5 and §3.7."""

from datetime import timedelta

import calc
from core import (
    DB, apply_changes, clock_date, day_start, find, iso_date, iso_ms, now_clock,
    parse_date, parse_instant, round_half_up, rows, touch,
)


# ---------------------------------------------------------------------------
# Fiscal period sustainability
# ---------------------------------------------------------------------------

def recompute_period(period, balance_delta=0, extra=None):
    """Re-derive all nine sustainability fields on the RECOGNIZED basis, folding
    an optional reserve-balance movement into the very same row mutation."""
    changes = dict(extra or {})
    if balance_delta:
        changes["reserve_balance_cents"] = int(period["reserve_balance_cents"]) + int(balance_delta)
    balance = changes.get("reserve_balance_cents", period["reserve_balance_cents"])
    total, shares, hhi, top_source = calc.revenue_diversification_index(period, "RECOGNIZED")
    target_months, target_cents, ratio_bps, posture, cap_bps = calc.reserve_policy_posture(
        period["monthly_expense_base_cents"], balance, hhi, top_source)
    changes.update({
        "recognized_revenue_cents": total,
        "stream_shares_bps": shares,
        "concentration_hhi": hhi,
        "top_source_share_bps": top_source,
        "reserve_months_target": target_months,
        "operating_reserve_target_cents": target_cents,
        "reserve_months_ratio_bps": ratio_bps,
        "sustainability_posture": posture,
        "restricted_release_cap_pct_bps": cap_bps,
    })
    return apply_changes(period, changes)


def sustainability_view(period, basis):
    """Projection used by GET /fiscal-periods/{id}/sustainability."""
    if basis == "PIPELINE":
        total, shares, hhi, top_source = calc.revenue_diversification_index(period, "PIPELINE")
        target_months, target_cents, ratio_bps, posture, cap_bps = calc.reserve_policy_posture(
            period["monthly_expense_base_cents"], period["reserve_balance_cents"], hhi, top_source)
    else:
        total = period["recognized_revenue_cents"]
        shares = period["stream_shares_bps"]
        hhi = period["concentration_hhi"]
        top_source = period["top_source_share_bps"]
        target_months = period["reserve_months_target"]
        target_cents = period["operating_reserve_target_cents"]
        ratio_bps = period["reserve_months_ratio_bps"]
        posture = period["sustainability_posture"]
        cap_bps = period["restricted_release_cap_pct_bps"]
    return {
        "basis": basis,
        "recognized_revenue_cents": total,
        "membership_share_bps": shares.get("MEMBERSHIP", 0),
        "major_gift_share_bps": shares.get("MAJOR_GIFT", 0),
        "grants_share_bps": shares.get("GRANTS", 0),
        "events_share_bps": shares.get("EVENTS", 0),
        "syndication_share_bps": shares.get("SYNDICATION", 0),
        "concentration_hhi": hhi,
        "top_source_share_bps": top_source,
        "reserve_months_target": target_months,
        "operating_reserve_target_cents": target_cents,
        "reserve_months_ratio_bps": ratio_bps,
        "sustainability_posture": posture,
        "restricted_release_cap_pct_bps": cap_bps,
    }


# ---------------------------------------------------------------------------
# Coverage area
# ---------------------------------------------------------------------------

def recompute_coverage_area(area, extra=None):
    disclosed = set()
    stale = False
    for disclosure in DB["firewall_disclosures"].values():
        if disclosure.get("coverage_area_id") != area["id"]:
            continue
        if disclosure.get("status") == "ACTIVE":
            disclosed.add(disclosure.get("funder_id"))
        elif disclosure.get("status") == "REATTESTATION_REQUIRED":
            stale = True
    restricted_grants = 0
    for proposal in DB["grant_proposals"].values():
        if proposal.get("coverage_area_id") != area["id"]:
            continue
        if proposal.get("status") not in ("AWARDED", "SUSPENDED"):
            continue
        if calc.is_restricted_scope(proposal.get("restriction_type")):
            restricted_grants += 1
    changes = dict(extra or {})
    changes.update({
        "disclosure_status": "STALE" if stale else "CURRENT",
        "publication_gate": "BLOCKED" if stale else "OPEN",
        "restricted_grant_count": restricted_grants,
        "disclosed_funder_count": len(disclosed),
    })
    return apply_changes(area, changes)


def disclosed_funder_ids(area_id):
    seen = []
    for disclosure in rows("firewall_disclosures"):
        if disclosure.get("coverage_area_id") == area_id and disclosure.get("status") == "ACTIVE":
            if disclosure.get("funder_id") not in seen:
                seen.append(disclosure.get("funder_id"))
    return seen


def active_disclosure(funder_id, coverage_area_id):
    for disclosure in rows("firewall_disclosures"):
        if (disclosure.get("funder_id") == funder_id
                and disclosure.get("coverage_area_id") == coverage_area_id
                and disclosure.get("status") == "ACTIVE"):
            return disclosure
    return None


def stale_disclosure(funder_id, coverage_area_id=None):
    for disclosure in rows("firewall_disclosures"):
        if disclosure.get("funder_id") != funder_id:
            continue
        if coverage_area_id is not None and disclosure.get("coverage_area_id") != coverage_area_id:
            continue
        if disclosure.get("status") == "REATTESTATION_REQUIRED":
            return disclosure
    return None


# ---------------------------------------------------------------------------
# Funder
# ---------------------------------------------------------------------------

def funder_lifetime_committed(funder_id):
    total = 0
    for contribution in DB["contributions"].values():
        if (contribution.get("funder_id") == funder_id
                and contribution.get("settlement_status") == "SETTLED"):
            total += int(contribution.get("amount_cents") or 0)
    for proposal in DB["grant_proposals"].values():
        if (proposal.get("funder_id") == funder_id
                and proposal.get("status") in ("AWARDED", "CLOSED")):
            total += int(proposal.get("awarded_amount_cents") or 0)
    return total


def funder_risk_preview(funder, overrides=None):
    """Score the funder as if `overrides` were already applied."""
    candidate = dict(funder)
    if overrides:
        candidate.update(overrides)
    reliability = calc.funder_reporting_reliability_bps(funder["id"])
    requests = calc.funder_editorial_request_count(funder["id"])
    score = calc.funder_independence_risk(
        candidate, candidate.get("risk_basis"),
        reliability_bps=reliability, editorial_requests=requests)
    return score, reliability, requests


def recompute_funder(funder, extra=None):
    changes = dict(extra or {})
    score, reliability, requests = funder_risk_preview(funder, changes)
    changes.update({
        "prior_editorial_requests_count": requests,
        "reporting_reliability_bps": reliability,
        "independence_risk_score": score,
        "lifetime_committed_cents": funder_lifetime_committed(funder["id"]),
    })
    return apply_changes(funder, changes)


# ---------------------------------------------------------------------------
# Member
# ---------------------------------------------------------------------------

def member_lifetime_giving(member_id):
    total = 0
    for contribution in DB["contributions"].values():
        if (contribution.get("member_id") == member_id
                and contribution.get("settlement_status") == "SETTLED"):
            total += int(contribution.get("amount_cents") or 0)
    return total


def member_giving_changes(member, extra=None):
    """lifetime_giving_cents recomputes freely; is_major_donor and
    cultivation_locked latch true and never fall back."""
    changes = dict(extra or {})
    lifetime = member_lifetime_giving(member["id"])
    major = bool(member.get("is_major_donor")) or lifetime >= calc.MAJOR_DONOR_THRESHOLD_CENTS
    changes["lifetime_giving_cents"] = lifetime
    changes["is_major_donor"] = major
    changes["cultivation_locked"] = bool(member.get("cultivation_locked")) or major
    return changes


def member_schedule_changes(member, tier, cycle_start_date, status=None):
    status = status or member.get("status")
    next_renewal, grace_expires = calc.member_renewal_schedule(
        cycle_start_date, tier["renewal_cadence"], tier.get("grace_period_days"))
    changes = {
        "cycle_start_date": iso_date(cycle_start_date),
        "next_renewal_date": iso_date(next_renewal),
    }
    changes["grace_expires_at"] = iso_ms(grace_expires) if status == "GRACE" else None
    return changes


def recompute_member_giving(member, extra=None):
    return apply_changes(member, member_giving_changes(member, extra))


# ---------------------------------------------------------------------------
# Grant proposal / grant report helpers
# ---------------------------------------------------------------------------

def proposal_reports_ordered(proposal_id):
    """due_date ascending with created_at ascending as the tie-break -- ids are
    never part of the ordering."""
    items = [r for r in rows("grant_reports") if r.get("grant_proposal_id") == proposal_id]
    return sorted(items, key=lambda r: (r.get("due_date") or "", r["_seq"]))


def reallocate_release_buckets(proposal):
    reports = proposal_reports_ordered(proposal["id"])
    allocations = calc.allocate_release_buckets(
        int(proposal.get("awarded_amount_cents") or 0), len(reports))
    for report, allocation in zip(reports, allocations):
        apply_changes(report, {"allocated_release_cents": allocation})


def release_capacity(proposal):
    """Unconsumed capacity across the waterfall buckets."""
    reports = proposal_reports_ordered(proposal["id"])
    if not reports:
        return (int(proposal.get("awarded_amount_cents") or 0)
                - int(proposal.get("released_cents") or 0))
    total = 0
    for report in reports:
        total += (int(report.get("allocated_release_cents") or 0)
                  - int(report.get("consumed_release_cents") or 0))
    return total


def consume_release(proposal, amount_cents):
    """Fill buckets in due_date ascending order."""
    remaining = int(amount_cents)
    for report in proposal_reports_ordered(proposal["id"]):
        if remaining <= 0:
            break
        room = (int(report.get("allocated_release_cents") or 0)
                - int(report.get("consumed_release_cents") or 0))
        if room <= 0:
            continue
        fill = min(remaining, room)
        apply_changes(report, {
            "consumed_release_cents": int(report.get("consumed_release_cents") or 0) + fill})
        remaining -= fill


def proposal_is_delinquent(proposal_id):
    for report in DB["grant_reports"].values():
        if report.get("grant_proposal_id") == proposal_id and report.get("status") == "OVERDUE":
            return True
    return False


def recompute_proposal_compliance(proposal, extra=None):
    changes = dict(extra or {})
    changes["compliance_flag"] = ("DELINQUENT" if proposal_is_delinquent(proposal["id"])
                                  else "COMPLIANT")
    return apply_changes(proposal, changes)


def suspend_proposal(proposal, reason, extra=None):
    """AWARDED -> SUSPENDED: released money is clawed back into returned_cents
    and the fiscal period's reserve balance is debited by the same amount."""
    clawed = int(proposal.get("released_cents") or 0)
    changes = dict(extra or {})
    changes.update({
        "status": "SUSPENDED",
        "suspended_reason": reason,
        "released_cents": 0,
        "returned_cents": int(proposal.get("returned_cents") or 0) + clawed,
    })
    apply_changes(proposal, changes)
    period = DB["fiscal_periods"].get(proposal.get("fiscal_period_id"))
    if period is not None:
        recompute_period(period, balance_delta=-clawed)
    area = DB["coverage_areas"].get(proposal.get("coverage_area_id"))
    if area is not None:
        recompute_coverage_area(area)


# ---------------------------------------------------------------------------
# The five-hop funder restriction cascade (§3.5)
# ---------------------------------------------------------------------------

def firewall_cascade(funder, reason):
    """Hops 2-5: stale disclosures -> blocked beats -> suspended grants ->
    re-derived fiscal posture.  Every touched row bumps its own version."""
    affected_area_ids = []
    for disclosure in rows("firewall_disclosures"):
        if disclosure.get("funder_id") != funder["id"]:
            continue
        if disclosure.get("status") != "ACTIVE":
            continue
        apply_changes(disclosure, {
            "status": "REATTESTATION_REQUIRED",
            "reattestation_reason": reason,
        })
        area_id = disclosure.get("coverage_area_id")
        if area_id not in affected_area_ids:
            affected_area_ids.append(area_id)

    for area_id in affected_area_ids:
        area = DB["coverage_areas"].get(area_id)
        if area is None:
            continue
        recompute_coverage_area(area)
        for proposal in rows("grant_proposals"):
            if proposal.get("coverage_area_id") != area_id:
                continue
            if proposal.get("status") != "AWARDED":
                continue
            suspend_proposal(proposal, "FIREWALL_BREACH")


def restrict_funder(funder, reason, counters=None, extra=None):
    """Hop 1 plus hops 2-5."""
    changes = dict(extra or {})
    changes["status"] = "RESTRICTED"
    changes["restricted_at"] = iso_ms(now_clock())
    recompute_funder(funder, changes)
    if counters is not None:
        counters["funders_restricted"] += 1
    firewall_cascade(funder, reason)


# ---------------------------------------------------------------------------
# The four-hop report delinquency cascade (§3.7)
# ---------------------------------------------------------------------------

def report_delinquency_cascade(report, counters):
    report["_ever_overdue"] = True
    apply_changes(report, {"status": "OVERDUE"})
    counters["reports_moved_to_overdue"] += 1

    proposal = DB["grant_proposals"].get(report.get("grant_proposal_id"))
    if proposal is None:
        return
    if proposal.get("status") == "AWARDED":
        suspend_proposal(proposal, "REPORT_DELINQUENCY", extra={"compliance_flag": "DELINQUENT"})
        counters["proposals_suspended"] += 1
    else:
        apply_changes(proposal, {"compliance_flag": "DELINQUENT"})

    funder = DB["funders"].get(proposal.get("funder_id"))
    if funder is None:
        return
    recompute_funder(funder)
    if (int(funder.get("independence_risk_score") or 0) >= calc.RISK_HARD_BAR
            and funder.get("status") in ("PROSPECT", "CLEARED")):
        restrict_funder(funder, "FUNDER_RESTRICTED", counters)
    period = DB["fiscal_periods"].get(proposal.get("fiscal_period_id"))
    if period is not None:
        recompute_period(period)
    area = DB["coverage_areas"].get(proposal.get("coverage_area_id"))
    if area is not None:
        recompute_coverage_area(area)


# ---------------------------------------------------------------------------
# Collaboration cost split
# ---------------------------------------------------------------------------

def confirmed_partners(collaboration_id):
    return [p for p in rows("collaboration_partners")
            if p.get("collaboration_id") == collaboration_id
            and p.get("status") == "CONFIRMED"]


def syndication_revenue(collaboration_id):
    total = 0
    for contribution in DB["contributions"].values():
        if (contribution.get("collaboration_id") == collaboration_id
                and contribution.get("revenue_stream") == "SYNDICATION"
                and contribution.get("settlement_status") == "SETTLED"):
            total += int(contribution.get("amount_cents") or 0)
    return total


def recompute_collaboration_counts(collaboration, extra=None):
    changes = dict(extra or {})
    changes["partner_count"] = len(confirmed_partners(collaboration["id"]))
    changes["syndication_revenue_cents"] = syndication_revenue(collaboration["id"])
    return apply_changes(collaboration, changes)


def recompute_collaboration_split(collaboration, extra=None):
    """Largest-remainder apportionment across the lead and the confirmed
    partners; the sum of the parts always equals total_cost_cents."""
    partners = confirmed_partners(collaboration["id"])
    shares = [int(collaboration.get("lead_cost_share_bps") or 0)]
    shares += [int(p.get("cost_share_bps") or 0) for p in partners]
    amounts, ranks = calc.largest_remainder_split(
        int(collaboration.get("total_cost_cents") or 0), shares)
    for index, partner in enumerate(partners):
        apply_changes(partner, {
            "cost_owed_cents": amounts[index + 1],
            "remainder_rank": ranks[index + 1],
        })
    lead_cost = amounts[0] if amounts else 0
    changes = dict(extra or {})
    changes["partner_count"] = len(partners)
    changes["lead_cost_cents"] = lead_cost
    changes["allocated_cost_cents"] = lead_cost + sum(amounts[1:])
    changes["syndication_revenue_cents"] = syndication_revenue(collaboration["id"])
    return apply_changes(collaboration, changes)
