"""Award service: creation from an awarded application, serialization, and
ledger helpers (PRD §3.2)."""
import db
from services import common as c

AWARD_STATUSES = {"ACTIVE", "SUSPENDED", "PENDING_CLOSEOUT", "CLOSED"}


def create_award_from_application(app):
    """Cross-entity creation on POST /applications/{id}/award (PRD §3.2).

    Copies total_award_cents = requested_amount_cents, federal_share_pct, and
    the period dates; computes federal_ceiling_cents = round_half_up(
    total_award_cents * federal_share_pct); opens ACTIVE with both ledgers at 0.
    Caller already holds db.LOCK.
    """
    total_award_cents = app["requested_amount_cents"]
    federal_share_pct = app["federal_share_pct"]
    federal_ceiling_cents = c.apply_rate(total_award_cents, federal_share_pct)

    award = {
        "application_id": app["id"],
        "total_award_cents": total_award_cents,
        "federal_share_pct": federal_share_pct,
        "federal_ceiling_cents": federal_ceiling_cents,
        "period_start_date": app["period_start_date"],
        "period_end_date": app["period_end_date"],
        "federal_drawn_cents": 0,
        "federal_approved_expenditures_cents": 0,
        "status": "ACTIVE",
    }
    db.stamp_create(award)
    db.awards[award["id"]] = award
    return award


def serialize_award(award, extra=None):
    out = c.serialize(award)
    if extra:
        out.update(extra)
    return out


def recompute_federal_approved_expenditures(award):
    """Recompute Award.federal_approved_expenditures_cents on report ACCEPT
    (PRD §3.6): federal_share_pct * sum of approved_direct_cents over this
    award's ACCEPTED reports, round_half_up. Caller holds db.LOCK."""
    total_direct = 0
    for r in db.financial_reports.values():
        if r["award_id"] == award["id"] and r["status"] == "ACCEPTED":
            total_direct += r.get("approved_direct_cents", 0)
    award["federal_approved_expenditures_cents"] = c.apply_rate(
        total_direct, award["federal_share_pct"]
    )
