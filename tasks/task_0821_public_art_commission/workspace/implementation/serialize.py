"""Entity -> public JSON dict serializers (computed fields resolved here)."""
import db

_COMMON = ("id", "created_at", "updated_at", "version")


def _common(rec, out):
    for k in _COMMON:
        out[k] = rec[k]
    return out


def project_committed(project_id):
    return sum(
        c["allocation_cents"]
        for c in db.commissions.values()
        if c["project_id"] == project_id and c["status"] != "CANCELLED"
    )


def contract_paid(contract_id):
    return sum(
        m["amount_cents"]
        for m in db.milestones.values()
        if m["contract_id"] == contract_id and m["status"] == "PAID"
    )


def project(rec):
    committed = project_committed(rec["id"])
    out = {
        "name": rec["name"],
        "construction_budget_cents": rec["construction_budget_cents"],
        "certified_construction_budget_cents": rec["certified_construction_budget_cents"],
        "percent_rate": rec["percent_rate"],
        "art_budget_cents": rec["art_budget_cents"],
        "committed_cents": committed,
        "uncommitted_cents": rec["art_budget_cents"] - committed,
        "status": rec["status"],
    }
    return _common(rec, out)


def commission(rec):
    out = {
        "project_id": rec["project_id"],
        "title": rec["title"],
        "allocation_cents": rec["allocation_cents"],
        "awarded_submission_id": rec["awarded_submission_id"],
        "status": rec["status"],
    }
    return _common(rec, out)


def call(rec):
    out = {
        "commission_id": rec["commission_id"],
        "call_type": rec["call_type"],
        "submission_deadline": rec["submission_deadline"],
        "quorum_min": rec["quorum_min"],
        "status": rec["status"],
    }
    return _common(rec, out)


def artist(rec):
    out = {
        "display_name": rec["display_name"],
        "email": rec["email"],
        "region": rec["region"],
    }
    return _common(rec, out)


def submission(rec):
    out = {
        "call_id": rec["call_id"],
        "artist_id": rec["artist_id"],
        "proposed_budget_cents": rec["proposed_budget_cents"],
        "composite_score": rec["composite_score"],
        "status": rec["status"],
    }
    return _common(rec, out)


def panelist(rec):
    out = {
        "call_id": rec["call_id"],
        "evaluator_name": rec["evaluator_name"],
        "has_conflict": rec["has_conflict"],
        "recused": rec["recused"],
    }
    return _common(rec, out)


def score(rec):
    out = {
        "submission_id": rec["submission_id"],
        "panelist_id": rec["panelist_id"],
        "artistic_merit": rec["artistic_merit"],
        "feasibility": rec["feasibility"],
        "community_impact": rec["community_impact"],
        "durability": rec["durability"],
        "weighted_value": rec["weighted_value"],
    }
    return _common(rec, out)


def contract(rec):
    paid = contract_paid(rec["id"])
    out = {
        "commission_id": rec["commission_id"],
        "submission_id": rec["submission_id"],
        "contract_amount_cents": rec["contract_amount_cents"],
        "paid_cents": paid,
        "remaining_cents": rec["contract_amount_cents"] - paid,
        "status": rec["status"],
    }
    return _common(rec, out)


def milestone(rec):
    out = {
        "contract_id": rec["contract_id"],
        "sequence": rec["sequence"],
        "title": rec["title"],
        "pct": rec["pct"],
        "amount_cents": rec["amount_cents"],
        "status": rec["status"],
    }
    return _common(rec, out)


def site(rec):
    out = {
        "name": rec["name"],
        "address": rec["address"],
        "capacity": rec["capacity"],
        "current_artwork_id": rec["current_artwork_id"],
        "status": rec["status"],
    }
    return _common(rec, out)


def artwork(rec):
    out = {
        "title": rec["title"],
        "acquisition_type": rec["acquisition_type"],
        "contract_id": rec["contract_id"],
        "site_id": rec["site_id"],
        "appraised_value_cents": rec["appraised_value_cents"],
        "install_date": rec["install_date"],
        "location_status": rec["location_status"],
        "condition_status": rec["condition_status"],
        "deaccession_method": rec["deaccession_method"],
        "deaccession_proceeds_cents": rec["deaccession_proceeds_cents"],
    }
    return _common(rec, out)


def conservation_record(rec):
    # Immutable event entry: only id + created_at (no updated_at / version).
    return {
        "id": rec["id"],
        "artwork_id": rec["artwork_id"],
        "record_type": rec["record_type"],
        "condition_after": rec["condition_after"],
        "notes": rec["notes"],
        "performed_at": rec["performed_at"],
        "created_at": rec["created_at"],
    }


def loan(rec):
    out = {
        "artwork_id": rec["artwork_id"],
        "borrower_name": rec["borrower_name"],
        "loan_start": rec["loan_start"],
        "loan_end": rec["loan_end"],
        "status": rec["status"],
    }
    return _common(rec, out)
