"""Entity lifecycle, derived-field reconciliation, cascades and lazy expiry."""

import uuid
from datetime import timedelta

import calc
from db import db
from errors import fail

DEAL_TERMINAL_STAGES = ("CLOSED", "DEAD", "ROFR_LOST", "TERMINATED")
DISPUTE_OPEN_STATUSES = ("OPEN", "CURE_PENDING", "REOPENED")


# --------------------------------------------------------------------- basics

def now():
    return db.current_utc


def iso(value):
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (value.microsecond // 1000)) + "Z"


def iso_date(value):
    if value is None:
        return None
    return value.isoformat()


def new_entity(**fields):
    stamp = now()
    entity = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    entity.update(fields)
    return entity


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] = entity["version"] + 1
    return entity


def common(entity):
    return {
        "id": entity["id"],
        "created_at": iso(entity["created_at"]),
        "updated_at": iso(entity["updated_at"]),
        "version": entity["version"],
    }


def ordered(values):
    return sorted(values, key=lambda item: (item["created_at"], item["_seq"]))


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


# ------------------------------------------------------------- serialization

def portfolio_json(p):
    out = common(p)
    out.update({
        "name": p["name"],
        "program_code": p["program_code"],
        "total_capital_cents": p["total_capital_cents"],
        "committed_capital_cents": p["committed_capital_cents"],
        "deployed_capital_cents": p["deployed_capital_cents"],
        "available_capital_cents": p["available_capital_cents"],
        "utilization_bps": p["utilization_bps"],
        "capital_posture": p["capital_posture"],
        "active_deal_count": p["active_deal_count"],
    })
    return out


def facility_json(f):
    out = common(f)
    out.update({
        "portfolio_id": f["portfolio_id"],
        "facility_name": f["facility_name"],
        "advance_rate_bps": f["advance_rate_bps"],
        "valuation_basis": f["valuation_basis"],
        "carrier_concentration_limit_bps": f["carrier_concentration_limit_bps"],
        "pledged_eligible_total_cents": f["pledged_eligible_total_cents"],
        "concentration_excess_cents": f["concentration_excess_cents"],
        "borrowing_base_cents": f["borrowing_base_cents"],
        "advances_outstanding_cents": f["advances_outstanding_cents"],
        "compliance_state": f["compliance_state"],
        "pledged_stream_count": f["pledged_stream_count"],
    })
    return out


def tower_company_json(t):
    out = common(t)
    out.update({
        "legal_name": t["legal_name"],
        "rofr_required": t["rofr_required"],
        "rofr_window_days": t["rofr_window_days"],
        "notice_email": t["notice_email"],
        "site_count": t["site_count"],
    })
    return out


def tower_site_json(s):
    out = common(s)
    out.update({
        "tower_company_id": s["tower_company_id"],
        "site_code": s["site_code"],
        "state_code": s["state_code"],
        "ground_area_sqft": s["ground_area_sqft"],
        "structure_type": s["structure_type"],
        "lease_stream_count": s["lease_stream_count"],
    })
    return out


def landowner_json(l):
    out = common(l)
    out.update({
        "legal_name": l["legal_name"],
        "entity_type": l["entity_type"],
        "contact_email": l["contact_email"],
        "outreach_status": outreach_status(l),
        "open_dispute_count": l["open_dispute_count"],
    })
    return out


def stream_json(s):
    out = common(s)
    out.update({
        "tower_site_id": s["tower_site_id"],
        "landowner_id": s["landowner_id"],
        "current_annual_rent_cents": s["current_annual_rent_cents"],
        "escalator_type": s["escalator_type"],
        "escalator_pct_bps": s["escalator_pct_bps"],
        "remaining_term_months": s["remaining_term_months"],
        "rent_redirection_status": s["rent_redirection_status"],
        "tenancy_quality_score": s["tenancy_quality_score"],
        "anchor_carrier_name": s["anchor_carrier_name"],
        "acquisition_status": s["acquisition_status"],
        "servicing_status": s["servicing_status"],
        "cumulative_revenue_share_landowner_cents": s["cumulative_revenue_share_landowner_cents"],
        "cumulative_revenue_share_acquirer_cents": s["cumulative_revenue_share_acquirer_cents"],
        "active_tenancy_count": s["active_tenancy_count"],
    })
    return out


def tenancy_json(t):
    out = common(t)
    out.update({
        "lease_stream_id": t["lease_stream_id"],
        "carrier_name": t["carrier_name"],
        "carrier_credit_tier": t["carrier_credit_tier"],
        "tenancy_type": t["tenancy_type"],
        "monthly_rent_share_cents": t["monthly_rent_share_cents"],
        "term_end_date": iso_date(t["term_end_date"]),
        "status": t["status"],
        "redirection_notice_status": t["redirection_notice_status"],
        "quality_points": t["quality_points"],
    })
    return out


def valuation_json(v):
    out = common(v)
    out.update({
        "lease_stream_id": v["lease_stream_id"],
        "method": v["method"],
        "prepaid_term_months": v["prepaid_term_months"],
        "tenancy_quality_score_snapshot": v["tenancy_quality_score_snapshot"],
        "discount_rate_bps": v["discount_rate_bps"],
        "growth_rate_bps": v["growth_rate_bps"],
        "horizon_years": v["horizon_years"],
        "value_cents": v["value_cents"],
        "max_bid_cents": v["max_bid_cents"],
        "status": v["status"],
        "approved_by_user_id": v["approved_by_user_id"],
        "approved_at": iso(v["approved_at"]),
    })
    return out


def deal_json(d):
    out = common(d)
    out.update({
        "portfolio_id": d["portfolio_id"],
        "lease_stream_id": d["lease_stream_id"],
        "valuation_id": d["valuation_id"],
        "easement_type": d["easement_type"],
        "easement_term_years": d["easement_term_years"],
        "revenue_share_bps": d["revenue_share_bps"],
        "stage": d["stage"],
        "capital_state": d["capital_state"],
        "rofr_state": d["rofr_state"],
        "negotiation_rounds": d["negotiation_rounds"],
        "agreed_consideration_cents": d["agreed_consideration_cents"],
        "broker_fee_bps": d["broker_fee_bps"],
        "broker_fee_cents": d["broker_fee_cents"],
        "holdback_cents": d["holdback_cents"],
        "net_landowner_proceeds_cents": d["net_landowner_proceeds_cents"],
        "total_commitment_cents": d["total_commitment_cents"],
        "escrow_funded_cents": d["escrow_funded_cents"],
        "escrow_disbursed_cents": d["escrow_disbursed_cents"],
        "escrow_holdback_cents": d["escrow_holdback_cents"],
        "escrow_refunded_cents": d["escrow_refunded_cents"],
        "easement_status": d["easement_status"],
        "recording_ref": d["recording_ref"],
        "recorded_at": iso(d["recorded_at"]),
        "closed_by_user_id": d["closed_by_user_id"],
    })
    return out


def settlement_json(d):
    return {
        "deal_id": d["id"],
        "agreed_consideration_cents": d["agreed_consideration_cents"],
        "broker_fee_bps": d["broker_fee_bps"],
        "broker_fee_cents": d["broker_fee_cents"],
        "holdback_cents": d["holdback_cents"],
        "net_landowner_proceeds_cents": d["net_landowner_proceeds_cents"],
        "total_commitment_cents": d["total_commitment_cents"],
        "escrow_funded_cents": d["escrow_funded_cents"],
        "escrow_disbursed_cents": d["escrow_disbursed_cents"],
        "escrow_holdback_cents": d["escrow_holdback_cents"],
        "escrow_refunded_cents": d["escrow_refunded_cents"],
    }


def offer_json(o):
    out = common(o)
    out.update({
        "deal_id": o["deal_id"],
        "offer_type": o["offer_type"],
        "amount_cents": o["amount_cents"],
        "prepaid_term_months": o["prepaid_term_months"],
        "expires_at": iso(o["expires_at"]),
        "round_number": o["round_number"],
        "counter_amount_cents": o["counter_amount_cents"],
        "status": o["status"],
        "sent_at": iso(o["sent_at"]),
        "decided_at": iso(o["decided_at"]),
        "decided_by_user_id": o["decided_by_user_id"],
    })
    return out


def title_json(t):
    out = common(t)
    out.update({
        "deal_id": t["deal_id"],
        "review_status": t["review_status"],
        "consent_status": t["consent_status"],
        "mortgage_present": t["mortgage_present"],
        "lender_name": t["lender_name"],
        "exception_count": t["exception_count"],
        "open_exception_count": t["open_exception_count"],
        "consent_requested_at": iso(t["consent_requested_at"]),
        "consent_expires_at": iso(t["consent_expires_at"]),
        "snda_required": t["snda_required"],
        "consent_decided_by_user_id": t["consent_decided_by_user_id"],
        "ordered_at": iso(t["ordered_at"]),
    })
    return out


def rofr_json(n):
    out = common(n)
    out.update({
        "deal_id": n["deal_id"],
        "served_at": iso(n["served_at"]),
        "window_start": iso(n["window_start"]),
        "window_end": iso(n["window_end"]),
        "window_days_snapshot": n["window_days_snapshot"],
        "status": n["status"],
        "responded_at": iso(n["responded_at"]),
        "responded_by_user_id": n["responded_by_user_id"],
    })
    return out


def dispute_json(d):
    out = common(d)
    out.update({
        "lease_stream_id": d["lease_stream_id"],
        "dispute_type": d["dispute_type"],
        "description": d["description"],
        "raised_by_role": d["raised_by_role"],
        "status": d["status"],
        "cure_attempts": d["cure_attempts"],
        "cure_deadline": iso(d["cure_deadline"]),
        "resolved_at": iso(d["resolved_at"]),
    })
    return out


def pledge_json(p):
    out = common(p)
    out.update({
        "facility_id": p["facility_id"],
        "lease_stream_id": p["lease_stream_id"],
        "pledge_start_date": iso_date(p["pledge_start_date"]),
        "pledge_end_date": iso_date(p["pledge_end_date"]),
        "valuation_basis_snapshot": p["valuation_basis_snapshot"],
        "basis_value_cents": p["basis_value_cents"],
        "haircut_bps": p["haircut_bps"],
        "eligible_value_cents": p["eligible_value_cents"],
        "status": p["status"],
    })
    return out


def amendment_json(a):
    out = common(a)
    out.update({
        "lease_stream_id": a["lease_stream_id"],
        "event_type": a["event_type"],
        "gross_amount_cents": a["gross_amount_cents"],
        "pass_through_cost_cents": a["pass_through_cost_cents"],
        "effective_date": iso_date(a["effective_date"]),
        "effective_pass_through_cents": a["effective_pass_through_cents"],
        "net_amount_cents": a["net_amount_cents"],
        "share_bps_applied": a["share_bps_applied"],
        "landowner_share_cents": a["landowner_share_cents"],
        "acquirer_share_cents": a["acquirer_share_cents"],
        "status": a["status"],
        "reversal_reason": a["reversal_reason"],
    })
    return out


# ---------------------------------------------------------------- lookups

def find(collection, entity_id, error_id):
    entity = getattr(db, collection).get(entity_id)
    if entity is None:
        fail(error_id)
    return entity


def fk(body_dict, key, collection, error_id):
    """Body foreign-key resolution (validation order step 4, before shape).

    An absent reference is left to the shape check; a present but unresolvable
    reference is the per-entity 404."""
    if key not in body_dict or body_dict[key] is None:
        return None
    raw = body_dict[key]
    entity = getattr(db, collection).get(raw) if isinstance(raw, str) else None
    if entity is None:
        fail(error_id)
    return entity


def deals_of_stream(stream_id):
    return ordered([d for d in db.deals.values() if d["lease_stream_id"] == stream_id])


def active_deal_of_stream(stream_id):
    for deal in deals_of_stream(stream_id):
        if deal["stage"] not in DEAL_TERMINAL_STAGES:
            return deal
    return None


def closed_deal_of_stream(stream_id):
    found = None
    for deal in deals_of_stream(stream_id):
        if deal["stage"] == "CLOSED":
            found = deal
    return found


def deal_of_stream_for_revenue_share(stream_id):
    return closed_deal_of_stream(stream_id)


def tenancies_of(stream_id):
    return ordered([t for t in db.tenancies.values() if t["lease_stream_id"] == stream_id])


def valuations_of(stream_id):
    return ordered([v for v in db.valuations.values() if v["lease_stream_id"] == stream_id])


def approved_valuation_of(stream_id):
    for valuation in valuations_of(stream_id):
        if valuation["status"] == "APPROVED":
            return valuation
    return None


def offers_of(deal_id):
    return ordered([o for o in db.offers.values() if o["deal_id"] == deal_id])


def title_reports_of(deal_id):
    return ordered([t for t in db.title_reports.values() if t["deal_id"] == deal_id])


def title_report_of(deal_id):
    reports = title_reports_of(deal_id)
    return reports[-1] if reports else None


def rofr_notices_of(deal_id):
    return ordered([n for n in db.rofr_notices.values() if n["deal_id"] == deal_id])


def disputes_of(stream_id):
    return ordered([d for d in db.disputes.values() if d["lease_stream_id"] == stream_id])


def pledges_of_stream(stream_id):
    return ordered([p for p in db.pledges.values() if p["lease_stream_id"] == stream_id])


def pledges_of_facility(facility_id):
    return ordered([p for p in db.pledges.values() if p["facility_id"] == facility_id])


def amendments_of(stream_id):
    return ordered([a for a in db.amendments.values() if a["lease_stream_id"] == stream_id])


def tower_company_of_stream(stream):
    site = db.tower_sites.get(stream["tower_site_id"])
    if site is None:
        return None
    return db.tower_companies.get(site["tower_company_id"])


def open_disputes_count(stream_id):
    return len([d for d in disputes_of(stream_id) if d["status"] in DISPUTE_OPEN_STATUSES])


# ---------------------------------------------------------------- landowner

def outreach_status(landowner):
    if landowner["suppress_outreach"]:
        return "DO_NOT_CONTACT"
    return landowner["derived_outreach_status"]


def set_derived_outreach(landowner, value):
    if landowner["derived_outreach_status"] != value:
        landowner["derived_outreach_status"] = value
        touch(landowner)


def recompute_open_dispute_count(landowner):
    if landowner is None:
        return
    count = 0
    for stream in db.lease_streams.values():
        if stream["landowner_id"] != landowner["id"]:
            continue
        count += open_disputes_count(stream["id"])
    if landowner["open_dispute_count"] != count:
        landowner["open_dispute_count"] = count
        touch(landowner)


# ---------------------------------------------------------------- portfolio

def recompute_portfolio(portfolio):
    if portfolio is None:
        return
    committed = 0
    deployed = 0
    active = 0
    for deal in db.deals.values():
        if deal["portfolio_id"] != portfolio["id"]:
            continue
        if deal["capital_state"] in ("RESERVED", "ESCROWED"):
            committed += deal["total_commitment_cents"]
        elif deal["capital_state"] == "DISBURSED":
            deployed += deal["total_commitment_cents"]
        if deal["stage"] not in DEAL_TERMINAL_STAGES:
            active += 1
    available = portfolio["total_capital_cents"] - committed - deployed
    util = calc.utilization_bps(committed + deployed, portfolio["total_capital_cents"])
    posture = calc.capital_posture(util)

    changed = (
        portfolio["committed_capital_cents"] != committed
        or portfolio["deployed_capital_cents"] != deployed
        or portfolio["available_capital_cents"] != available
        or portfolio["utilization_bps"] != util
        or portfolio["capital_posture"] != posture
        or portfolio["active_deal_count"] != active
    )
    portfolio["committed_capital_cents"] = committed
    portfolio["deployed_capital_cents"] = deployed
    portfolio["available_capital_cents"] = available
    portfolio["utilization_bps"] = util
    portfolio["capital_posture"] = posture
    portfolio["active_deal_count"] = active
    if changed:
        touch(portfolio)

    # Posture cascade into deals sitting on outreach.  Applied at the level of the
    # recomputed posture (not only on the edge into FROZEN) so the state machine's
    # precondition -- CAPITAL_HOLD exactly while the posture is FROZEN -- always holds.
    parked, resumed = ("CAPITAL_HOLD", "OUTREACH") if posture == "FROZEN" else ("OUTREACH", "CAPITAL_HOLD")
    for deal in ordered(list(db.deals.values())):
        if deal["portfolio_id"] == portfolio["id"] and deal["stage"] == resumed:
            deal["stage"] = parked
            touch(deal)


# ---------------------------------------------------------------- facility

def recompute_facility(facility):
    if facility is None:
        return
    pledged = [p for p in pledges_of_facility(facility["id"]) if p["status"] == "PLEDGED"]
    values = [p["eligible_value_cents"] for p in pledged]
    gross, excess, base = calc.borrowing_base(
        values, facility["carrier_concentration_limit_bps"], facility["advance_rate_bps"])
    count = len([p for p in pledges_of_facility(facility["id"]) if p["status"] != "RELEASED"])
    compliance = ("BORROWING_BASE_DEFICIT"
                  if facility["advances_outstanding_cents"] > base else "COMPLIANT")
    changed = (
        facility["pledged_eligible_total_cents"] != gross
        or facility["concentration_excess_cents"] != excess
        or facility["borrowing_base_cents"] != base
        or facility["compliance_state"] != compliance
        or facility["pledged_stream_count"] != count
    )
    facility["pledged_eligible_total_cents"] = gross
    facility["concentration_excess_cents"] = excess
    facility["borrowing_base_cents"] = base
    facility["compliance_state"] = compliance
    facility["pledged_stream_count"] = count
    if changed:
        touch(facility)


def projected_borrowing_base(facility, exclude_pledge_id=None):
    values = []
    for pledge in pledges_of_facility(facility["id"]):
        if pledge["id"] == exclude_pledge_id or pledge["status"] != "PLEDGED":
            continue
        values.append(pledge["eligible_value_cents"])
    _gross, _excess, base = calc.borrowing_base(
        values, facility["carrier_concentration_limit_bps"], facility["advance_rate_bps"])
    return base


def pledge_basis_value(facility, stream):
    if facility["valuation_basis"] == "MARK_TO_MODEL":
        valuation = approved_valuation_of(stream["id"])
        return valuation["value_cents"] if valuation else 0
    deal = closed_deal_of_stream(stream["id"])
    return deal["total_commitment_cents"] if deal else 0


def revalue_pledges_of_stream(stream):
    """Servicing-condition driven pledge lifecycle (PRD 3.9 pledge lifecycle)."""
    facilities = []
    for pledge in pledges_of_stream(stream["id"]):
        if pledge["status"] == "RELEASED":
            continue
        before = (pledge["status"], pledge["eligible_value_cents"], pledge["haircut_bps"])
        if stream["servicing_status"] in ("IMPAIRED", "DELINQUENT"):
            pledge["status"] = "INELIGIBLE"
        elif pledge["status"] == "INELIGIBLE":
            pledge["status"] = "PLEDGED"
        pledge["haircut_bps"] = calc.haircut_bps_for(stream["servicing_status"])
        pledge["eligible_value_cents"] = calc.eligible_value(
            pledge["status"], stream["servicing_status"], pledge["basis_value_cents"])
        if (pledge["status"], pledge["eligible_value_cents"], pledge["haircut_bps"]) != before:
            touch(pledge)
        facility = db.facilities.get(pledge["facility_id"])
        if facility is not None and facility not in facilities:
            facilities.append(facility)
    for facility in facilities:
        recompute_facility(facility)


def set_servicing_status(stream, value):
    if stream["servicing_status"] == value:
        return
    stream["servicing_status"] = value
    touch(stream)
    revalue_pledges_of_stream(stream)


# ---------------------------------------------------------------- lease stream

def recompute_stream_roster(stream):
    """Recompute tenancy_quality_score, anchor_carrier_name, active_tenancy_count."""
    scored = []
    anchor = None
    active = 0
    for tenancy in tenancies_of(stream["id"]):
        if tenancy["status"] not in ("ACTIVE", "HOLDOVER"):
            if tenancy["quality_points"] != 0:
                tenancy["quality_points"] = 0
                touch(tenancy)
            continue
        points, whole = calc.tenancy_points(
            tenancy["carrier_credit_tier"], tenancy["tenancy_type"], tenancy["status"])
        if tenancy["quality_points"] != whole:
            tenancy["quality_points"] = whole
            touch(tenancy)
        scored.append(points)
        active += 1
        if tenancy["tenancy_type"] == "ANCHOR" and anchor is None:
            anchor = tenancy["carrier_name"]
    stream["tenancy_quality_score"] = calc.tenancy_quality_score(scored)
    stream["anchor_carrier_name"] = anchor if anchor is not None else "UNASSIGNED"
    stream["active_tenancy_count"] = active


def invalidate_valuations(stream):
    """Roster writes invalidate pricing: DRAFT and APPROVED become STALE."""
    for valuation in valuations_of(stream["id"]):
        if valuation["status"] == "DRAFT":
            valuation["status"] = "STALE"
            touch(valuation)
        elif valuation["status"] == "APPROVED":
            pinned_closed = any(
                d["valuation_id"] == valuation["id"] and d["stage"] == "CLOSED"
                for d in db.deals.values())
            if not pinned_closed:
                valuation["status"] = "STALE"
                touch(valuation)


def roster_write(stream):
    """Applied after any tenancy create / reclassification."""
    had_anchor = stream["anchor_carrier_name"] != "UNASSIGNED"
    recompute_stream_roster(stream)
    touch(stream)
    invalidate_valuations(stream)
    lost_anchor = had_anchor and stream["anchor_carrier_name"] == "UNASSIGNED"
    if (lost_anchor and stream["acquisition_status"] == "ACQUIRED"
            and stream["servicing_status"] in ("PERFORMING", "WATCHLIST")):
        set_servicing_status(stream, "DELINQUENT")


# ---------------------------------------------------------------- deal helpers

def recompute_settlement(deal):
    if deal["agreed_consideration_cents"] is None:
        return
    figures = calc.settlement(deal["agreed_consideration_cents"],
                              open_disputes_count(deal["lease_stream_id"]))
    changed = any(deal[key] != value for key, value in figures.items())
    deal.update(figures)
    if changed:
        touch(deal)


def release_capital(deal, refund_escrow=False):
    if deal["capital_state"] in ("RESERVED", "ESCROWED"):
        if refund_escrow and deal["capital_state"] == "ESCROWED":
            deal["escrow_refunded_cents"] = deal["escrow_funded_cents"]
        deal["capital_state"] = "RELEASED"


def set_stream_acquisition(stream, value):
    if stream["acquisition_status"] != value:
        stream["acquisition_status"] = value
        touch(stream)


def kill_deal(deal, stage, stream_status):
    """Shared cascade for title failure, consent denial and exercised refusal."""
    deal["stage"] = stage
    release_capital(deal)
    touch(deal)
    stream = db.lease_streams.get(deal["lease_stream_id"])
    if stream is not None:
        set_stream_acquisition(stream, stream_status)
    recompute_portfolio(db.portfolios.get(deal["portfolio_id"]))


def join_conditions(deal):
    """Returns the blocking error_id or None when the clearance join holds."""
    if deal["rofr_state"] == "PENDING":
        return "ERR_ROFR_WINDOW_OPEN"
    report = title_report_of(deal["id"])
    if report is not None and report["mortgage_present"] and report["consent_status"] != "GRANTED":
        return "ERR_MORTGAGE_CONSENT_MISSING"
    if report is None or report["review_status"] != "CLEARED" or report["open_exception_count"] > 0:
        return "ERR_TITLE_EXCEPTIONS_OPEN"
    return None


def evaluate_join(deal):
    """Automatic (side-effect driven) evaluation of the DILIGENCE join."""
    if deal is None or deal["stage"] != "DILIGENCE":
        return False
    if join_conditions(deal) is not None:
        return False
    deal["stage"] = "CLEAR_TO_CLOSE"
    deal["easement_status"] = "DRAFTED"
    touch(deal)
    return True


def reopen_diligence(deal):
    if deal is None or deal["stage"] != "CLEAR_TO_CLOSE":
        return
    deal["stage"] = "DILIGENCE"
    deal["easement_status"] = "NOT_DRAFTED"
    touch(deal)


# ---------------------------------------------------------------- lazy expiry

def sweep_expiries():
    """PRD 2.6: offer lapse, consent expiry and refusal-window lapse are applied
    lazily so that no client can observe a stale non-expired state."""
    current = now()

    for offer in ordered(list(db.offers.values())):
        if offer["status"] == "SENT" and current >= offer["expires_at"]:
            offer["status"] = "LAPSED"
            touch(offer)

    for report in ordered(list(db.title_reports.values())):
        if (report["consent_status"] == "REQUESTED"
                and report["consent_expires_at"] is not None
                and current >= report["consent_expires_at"]):
            report["consent_status"] = "EXPIRED"
            touch(report)
            reopen_diligence(db.deals.get(report["deal_id"]))

    for notice in ordered(list(db.rofr_notices.values())):
        if notice["status"] == "SERVED" and current >= notice["window_end"]:
            notice["status"] = "EXPIRED"
            touch(notice)
            deal = db.deals.get(notice["deal_id"])
            if deal is not None and deal["rofr_state"] == "PENDING":
                deal["rofr_state"] = "WAIVED_BY_LAPSE"
                touch(deal)
                evaluate_join(deal)


def consent_window_end(start):
    return start + timedelta(days=calc.CONSENT_VALIDITY_DAYS)
