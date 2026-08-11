"""DiversionCredit endpoints: create, read, finalize, dispute, void, settle."""
from flask import Blueprint

from db import store, new_record, touch, now_dt, now_iso
from errors import fail
from middleware import endpoint
from response import success
from services import calc, domain
from util import check_fields, get_body, paginate

bp = Blueprint("credits", __name__)


def _credit_view_guard(user_id, role, credit):
    """Entity-backed ownership on single-credit reads (p2)."""
    if role == "Resident":
        if credit is not None and credit.get("beneficiary_resident_id") != user_id:
            fail("ERR_UNAUTHORIZED", "Residents may only read their own credits")
    elif role == "SponsorManager":
        if credit is not None and credit.get("fund_id") is not None \
                and credit["fund_id"] != user_id:
            fail("ERR_UNAUTHORIZED", "SponsorManagers may only read their fund's credits")


@bp.route("/weight-tickets/<tid>/diversion-credits", methods=["POST"])
@endpoint(["ZoneOperator"])
def create_credit(user_id, role, tid):
    ticket = store.tickets.get(tid)
    get_body()
    if ticket is None:
        fail("ERR_NOT_FOUND", "WeightTicket not found: %s" % tid)
    # p5: ticket CERTIFIED or QUARANTINED
    if ticket["status"] not in ("CERTIFIED", "QUARANTINED"):
        fail("ERR_TICKET_NOT_CERTIFIED", "Ticket must be CERTIFIED")
    # p7: quarantine safety gate
    if ticket["status"] == "QUARANTINED":
        fail("ERR_TICKET_QUARANTINED", "Ticket is QUARANTINED")
    # p9g: no non-VOIDED credit for the ticket
    if domain.live_credit_on_ticket(tid) is not None:
        fail("ERR_CREDIT_EXISTS", "A non-VOIDED credit already exists for this ticket")
    # p9h: no OPEN contamination report on the ticket
    if domain.open_report_on_ticket(tid) is not None:
        fail("ERR_OPEN_REPORTS_REMAIN", "An OPEN contamination report exists on this ticket")
    severity = ticket["highest_upheld_severity"]
    projected, _, _, _ = calc.credit_value(
        ticket["certified_weight_kg"], ticket["grade"], severity, fund_available=None)
    rec = new_record()
    rec.update({
        "ticket_id": tid,
        "fund_id": None,
        "beneficiary_resident_id": domain.ticket_resident_id(ticket),
        "projected_cents": projected,
        "gross_cents": None,
        "applied_severity": severity,
        "has_hold": False,
        "status": "PROVISIONAL",
        "charity_allocations": [],
        "resident_share_cents": None,
        "settled_at": None,
        "_settled_at": None,
    })
    store.credits[rec["id"]] = rec
    return success(domain.credit_view(rec), code=201)


@bp.route("/weight-tickets/<tid>/diversion-credits", methods=["GET"])
@endpoint(["ZoneOperator", "Resident", "SponsorManager"])
def list_ticket_credits(user_id, role, tid):
    ticket = store.tickets.get(tid)
    if role == "Resident" and ticket is not None:
        if domain.ticket_resident_id(ticket) != user_id:
            fail("ERR_UNAUTHORIZED", "Residents may only read credits from their own pickups")
    if ticket is None:
        fail("ERR_NOT_FOUND", "WeightTicket not found: %s" % tid)
    items = [c for c in store.credits.values() if c["ticket_id"] == tid]
    if role == "SponsorManager":
        items = [c for c in items if c.get("fund_id") == user_id]
    page, meta = paginate(items)
    return success([domain.credit_view(c) for c in page], response_type="array",
                   pagination=meta)


@bp.route("/diversion-credits/<cid>", methods=["GET"])
@endpoint(["ZoneOperator", "Resident", "SponsorManager"])
def get_credit(user_id, role, cid):
    credit = store.credits.get(cid)
    _credit_view_guard(user_id, role, credit)
    if credit is None:
        fail("ERR_NOT_FOUND", "DiversionCredit not found: %s" % cid)
    return success(domain.credit_view(credit))


@bp.route("/diversion-credits/<cid>/finalize", methods=["POST"])
@endpoint(["ZoneOperator"])
def finalize_credit(user_id, role, cid):
    credit = store.credits.get(cid)
    get_body()
    if credit is None:
        fail("ERR_NOT_FOUND", "DiversionCredit not found: %s" % cid)
    # p5: PROVISIONAL or DISPUTED
    if credit["status"] not in ("PROVISIONAL", "DISPUTED"):
        fail("ERR_INVALID_STATE", "Credit must be PROVISIONAL or DISPUTED to finalize")
    ticket = store.tickets.get(credit["ticket_id"])
    # p9h: no OPEN report on the ticket
    if domain.open_report_on_ticket(credit["ticket_id"]) is not None:
        fail("ERR_OPEN_REPORTS_REMAIN", "An OPEN contamination report exists on this ticket")
    # p10: zone must have an ACTIVE fund
    zone_id = domain.zone_id_of_ticket(ticket)
    fund = domain.active_fund_for_zone(zone_id)
    if fund is None:
        fail("ERR_FUND_NOT_ACTIVE", "Zone has no ACTIVE sponsor fund")
    held, paid = domain.fund_amounts(fund["id"])
    available = fund["funded_total_cents"] - held - paid
    # A re-finalize from DISPUTED with has_hold=true reuses the existing hold
    # (no second hold), so the credit's own outstanding hold is headroom for
    # itself when re-checking sufficiency.
    if credit["has_hold"] and credit.get("gross_cents") is not None:
        available += credit["gross_cents"]
    severity = ticket["highest_upheld_severity"]
    gross, after_contam, bulk_bonus, _ = calc.credit_value(
        ticket["certified_weight_kg"], ticket["grade"], severity, fund_available=available)
    # p11: material cost + bulk bonus alone must fit the fund
    if after_contam + bulk_bonus > available:
        fail("ERR_FUND_INSUFFICIENT", "Fund available_cents is insufficient")
    credit["gross_cents"] = gross
    credit["fund_id"] = fund["id"]
    credit["applied_severity"] = severity
    if not credit["has_hold"]:
        credit["has_hold"] = True  # places the hold (held_cents is derived)
    credit["status"] = "FINALIZED"
    touch(credit)
    return success(domain.credit_view(credit))


@bp.route("/diversion-credits/<cid>/dispute", methods=["POST"])
@endpoint(["Resident", "ZoneOperator"])
def dispute_credit(user_id, role, cid):
    credit = store.credits.get(cid)
    if role == "Resident" and credit is not None \
            and credit.get("beneficiary_resident_id") != user_id:
        fail("ERR_UNAUTHORIZED", "Only the beneficiary resident may dispute")
    body = get_body()
    check_fields(body, {"reason": ("str", True)})
    if credit is None:
        fail("ERR_NOT_FOUND", "DiversionCredit not found: %s" % cid)
    if credit["status"] not in ("PROVISIONAL", "FINALIZED"):
        fail("ERR_INVALID_STATE", "Credit must be PROVISIONAL or FINALIZED to dispute")
    credit["status"] = "DISPUTED"  # hold state retained
    touch(credit)
    return success(domain.credit_view(credit))


@bp.route("/diversion-credits/<cid>/void", methods=["POST"])
@endpoint(["ZoneOperator"])
def void_credit(user_id, role, cid):
    credit = store.credits.get(cid)
    get_body()
    if credit is None:
        fail("ERR_NOT_FOUND", "DiversionCredit not found: %s" % cid)
    if credit["status"] not in ("PROVISIONAL", "DISPUTED", "FINALIZED"):
        fail("ERR_INVALID_STATE", "Credit must be PROVISIONAL, DISPUTED or FINALIZED to void")
    domain.void_credit_record(credit)
    return success(domain.credit_view(credit))


@bp.route("/diversion-credits/<cid>/settle", methods=["POST"])
@endpoint(["ZoneOperator"])
def settle_credit(user_id, role, cid):
    credit = store.credits.get(cid)
    get_body()
    if credit is None:
        fail("ERR_NOT_FOUND", "DiversionCredit not found: %s" % cid)
    # p5 dedicated forms
    if credit["status"] in ("PROVISIONAL", "DISPUTED"):
        fail("ERR_CREDIT_NOT_FINAL", "Credit must be FINALIZED to settle")
    if credit["status"] != "FINALIZED":
        fail("ERR_INVALID_STATE", "Credit must be FINALIZED to settle")
    if not credit["has_hold"]:
        fail("ERR_CREDIT_NOT_FINAL", "Credit holds no sponsor-fund hold")
    ticket = store.tickets.get(credit["ticket_id"])
    gross = credit["gross_cents"]
    # commit: hold converts to payment (both derived from flags/status)
    credit["has_hold"] = False
    credit["status"] = "SETTLED"
    credit["settled_at"] = now_iso()
    credit["_settled_at"] = now_dt()
    # charity split: floor each line first, then assign the remainder
    zone_id = domain.zone_id_of_ticket(ticket)
    zone = store.zones.get(zone_id)
    splits = zone["charity_splits"] if zone else []
    lines, remainder = calc.charity_split_lines(gross, splits, store.charities)
    if credit.get("beneficiary_resident_id") is not None:
        credit["resident_share_cents"] = remainder  # resident absorbs rounding slack
    else:
        credit["resident_share_cents"] = None
        if lines:
            # drop-box credit: remainder folds into the largest-pct line
            # (ties: lines are already ordered by charity created_at ASC, and
            # max() returns the first maximal item)
            top = max(lines, key=lambda l: l["pct"])
            top["amount_cents"] += remainder
    credit["charity_allocations"] = lines
    touch(credit)
    # bubble-up: source pickup WEIGHED -> SETTLED
    if ticket is not None and ticket["source_type"] == "PICKUP_REQUEST":
        pickup = store.pickups.get(ticket["source_id"])
        if pickup is not None and pickup["status"] == "WEIGHED":
            pickup["status"] = "SETTLED"
            touch(pickup)
    return success(domain.credit_view(credit))
