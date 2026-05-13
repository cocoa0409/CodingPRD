"""Entity → dict serializers (returned in API responses)."""
import db


def serialize_business_unit(bu):
    return {
        "id": bu["id"],
        "created_at": bu["created_at"],
        "updated_at": bu["updated_at"],
        "version": bu["version"],
        "code": bu["code"],
        "name": bu["name"],
        "annual_budget_cents": bu["annual_budget_cents"],
        "actual_spend_cents": compute_business_unit_spend(bu["id"]),
        "status": bu["status"],
    }


def compute_business_unit_spend(business_unit_id: str) -> int:
    total = 0
    for cost in db.costs.values():
        for alloc in cost.get("allocations", []):
            if alloc.get("business_unit_id") == business_unit_id:
                total += alloc.get("allocated_cents", 0)
    return total


def serialize_agent(agent):
    counts = compute_agent_counts(agent["id"])
    workload = compute_workload_score(counts)
    perf = compute_performance_rating(agent["id"])
    return {
        "id": agent["id"],
        "created_at": agent["created_at"],
        "updated_at": agent["updated_at"],
        "version": agent["version"],
        "kind": agent["kind"],
        "full_name": agent["full_name"],
        "qualification_number": agent["qualification_number"],
        "qualification_verified": agent["qualification_verified"],
        "jurisdictions": list(agent["jurisdictions"]),
        "hourly_rate_cents": agent["hourly_rate_cents"],
        "active_case_count": counts["active_case_count"],
        "pending_action_count": counts["pending_action_count"],
        "upcoming_deadline_count": counts["upcoming_deadline_count"],
        "workload_score": workload,
        "performance_rating": perf,
        "status": agent["status"],
    }


def compute_agent_counts(agent_id: str) -> dict:
    active_case = 0
    for case in db.protection_cases.values():
        if case.get("assigned_agent_id") == agent_id and case.get("status") in ("OPEN", "IN_PROGRESS"):
            active_case += 1

    pending_action = 0
    for oa in db.office_actions.values():
        if oa.get("assigned_agent_id") == agent_id and oa.get("status") == "PENDING":
            pending_action += 1

    upcoming_deadline = 0
    from datetime import timedelta
    now = db.now()
    window_end = now + timedelta(days=30)
    for fee in db.annual_fees.values():
        if fee.get("assigned_agent_id") != agent_id:
            continue
        if fee.get("status") != "PENDING":
            continue
        due = db.parse_iso(fee.get("due_date"))
        if due is None:
            continue
        if now <= due <= window_end:
            upcoming_deadline += 1

    return {
        "active_case_count": active_case,
        "pending_action_count": pending_action,
        "upcoming_deadline_count": upcoming_deadline,
    }


def compute_workload_score(counts):
    from utils import round_half_up_decimals
    raw = (0.40 * counts["active_case_count"]
           + 0.30 * counts["pending_action_count"]
           + 0.30 * counts["upcoming_deadline_count"])
    return round_half_up_decimals(raw, 2)


def compute_performance_rating(agent_id: str) -> float:
    from utils import round_half_up_decimals
    relevant = []
    for case in db.protection_cases.values():
        if case.get("assigned_agent_id") != agent_id:
            continue
        if case.get("status") not in ("RESOLVED", "CLOSED"):
            continue
        relevant.append(case)
    # sort by updated_at DESC, id DESC; take 10
    relevant.sort(key=lambda c: (c.get("updated_at") or "", c.get("id") or ""), reverse=True)
    recent = relevant[:10]
    if not recent:
        return 0.00
    mapping = {"WON": 5.0, "SETTLED": 3.5, "DISMISSED": 2.0, "LOST": 1.0}
    scores = []
    for c in recent:
        oc = c.get("outcome")
        if oc in mapping:
            scores.append(mapping[oc])
    if not scores:
        return 0.00
    mean = sum(scores) / len(scores)
    return round_half_up_decimals(mean, 2)


def serialize_ip_right(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "ip_type": r["ip_type"],
        "title": r["title"],
        "handling_mode": r["handling_mode"],
        "assigned_agent_id": r.get("assigned_agent_id"),
        "business_unit_id": r["business_unit_id"],
        "status": r["status"],
        "primary_jurisdiction": r["primary_jurisdiction"],
        "certificate_archive_url": r.get("certificate_archive_url"),
        "registered_at": r.get("registered_at"),
    }


def serialize_jurisdiction_filing(jf):
    return {
        "id": jf["id"],
        "created_at": jf["created_at"],
        "updated_at": jf["updated_at"],
        "version": jf["version"],
        "ip_right_id": jf["ip_right_id"],
        "jurisdiction": jf["jurisdiction"],
        "filing_number": jf["filing_number"],
        "filed_at": jf["filed_at"],
        "status": jf["status"],
    }


def serialize_office_action(oa):
    return {
        "id": oa["id"],
        "created_at": oa["created_at"],
        "updated_at": oa["updated_at"],
        "version": oa["version"],
        "ip_right_id": oa["ip_right_id"],
        "jurisdiction_filing_id": oa["jurisdiction_filing_id"],
        "assigned_agent_id": oa["assigned_agent_id"],
        "response_due_at": oa["response_due_at"],
        "responded_at": oa.get("responded_at"),
        "status": oa["status"],
    }


def serialize_annual_fee(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "ip_right_id": f["ip_right_id"],
        "jurisdiction": f["jurisdiction"],
        "fee_year": f["fee_year"],
        "base_fee_cents": f["base_fee_cents"],
        "due_date": f["due_date"],
        "grace_end_date": f["grace_end_date"],
        "paid_at": f.get("paid_at"),
        "total_paid_cents": f.get("total_paid_cents", 0),
        "surcharge_cents": f.get("surcharge_cents", 0),
        "auto_pay_authorized": f.get("auto_pay_authorized", False),
        "assigned_agent_id": f["assigned_agent_id"],
        "status": f["status"],
    }


def serialize_contract(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "ip_right_id": c["ip_right_id"],
        "template_id": c["template_id"],
        "contract_type": c["contract_type"],
        "parties": [dict(p) for p in c["parties"]],
        "royalty_rate": c.get("royalty_rate"),
        "min_guarantee_cents": c.get("min_guarantee_cents"),
        "filed_with_authority": c.get("filed_with_authority", False),
        "status": c["status"],
        "business_unit_id": c["business_unit_id"],
    }


def serialize_contract_template(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "code": t["code"],
        "contract_type": t["contract_type"],
        "body": t["body"],
    }


def serialize_royalty_schedule(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "contract_id": s["contract_id"],
        "period_index": s["period_index"],
        "period_start": s["period_start"],
        "period_end": s["period_end"],
        "forecast_revenue_cents": s["forecast_revenue_cents"],
        "actual_revenue_cents": s.get("actual_revenue_cents", 0),
        "provisional_royalty_cents": s.get("provisional_royalty_cents", 0),
        "final_royalty_cents": s.get("final_royalty_cents", 0),
        "status": s["status"],
    }


def serialize_protection_case(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "ip_right_id": c["ip_right_id"],
        "assigned_agent_id": c["assigned_agent_id"],
        "business_unit_id": c["business_unit_id"],
        "route": c["route"],
        "status": c["status"],
        "outcome": c.get("outcome"),
        "recovered_amount_cents": c.get("recovered_amount_cents", 0),
        "legal_fees_cents": c.get("legal_fees_cents", 0),
        "agent_fees_cents": c.get("agent_fees_cents", 0),
        "punitive_cap_cents": c.get("punitive_cap_cents", 0),
        "distributed": c.get("distributed"),
        "rights_holder_currency": c.get("rights_holder_currency", "USD"),
    }


def serialize_evidence(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "protection_case_id": e["protection_case_id"],
        "kind": e["kind"],
        "collected_at": e["collected_at"],
        "storage_uri": e["storage_uri"],
        "chain_of_custody_hash": e.get("chain_of_custody_hash"),
    }


def serialize_cost(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "category": c["category"],
        "ip_right_id": c.get("ip_right_id"),
        "protection_case_id": c.get("protection_case_id"),
        "agent_id": c.get("agent_id"),
        "currency": c["currency"],
        "amount_native_cents": c["amount_native_cents"],
        "fx_rate_to_usd": c["fx_rate_to_usd"],
        "amount_usd_cents": c["amount_usd_cents"],
        "allocations": [dict(a) for a in c.get("allocations", [])],
        "allocation_rules": [dict(r) for r in c.get("allocation_rules", [])],
        "booked_at": c["booked_at"],
    }


def serialize_audit(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "subject_entity": a["subject_entity"],
        "subject_id": a["subject_id"],
        "actor_role": a["actor_role"],
        "actor_id": a["actor_id"],
        "event_type": a["event_type"],
        "from_state": a.get("from_state"),
        "to_state": a.get("to_state"),
        "payload": a.get("payload", {}),
    }
