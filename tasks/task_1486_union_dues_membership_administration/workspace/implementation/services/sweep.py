"""Delinquency sweep (delinquency_evaluation, scaffold calculations[2]) and
shared member-status cascades.

Sweep processes the local's members in created_at ASC order; each member's
outcome is independent.
  aged = exists a FINAL assessment with remaining balance > 0 whose
         period <= current clock period - grace_periods (month arithmetic)
  over = arrears_cents >= delinquency_threshold_cents (inclusive)
"""
import db
import utils
from services import ledger as ledger_svc

NON_TERMINAL_TRANSFER_STATES = ("INITIATED", "PENDING_TARGET", "ACCEPTED_BY_TARGET")


def cancel_transfers(member_id, states):
    for t in db.store.transfers.values():
        if t["member_id"] == member_id and t["status"] in states:
            t["status"] = "CANCELLED"
            db.touch(t)


def _aged(member, local, current_period):
    """True when a FINAL assessment with remaining balance > 0 has
    period <= current_period - grace_periods."""
    cutoff_period = utils.period_add(current_period, -local["grace_periods"])
    _, _, _, remaining = ledger_svc.waterfall(member["id"])
    for a in db.store.assessments.values():
        if a["member_id"] != member["id"] or a["status"] != "FINAL":
            continue
        if a["period"] <= cutoff_period and remaining.get(a["id"], 0) > 0:
            return True
    return False


def run_sweep(local):
    now = db.now()
    cur_period = db.current_period()
    cur_date = now.date()
    result = {
        "newly_delinquent_member_ids": [],
        "notices_created": 0,
        "notices_expired": 0,
        "notices_cured": 0,
        "newly_suspended_member_ids": [],
        "expelled_member_ids": [],
    }
    members = [m for m in db.store.members.values()
               if m["local_id"] == local["id"]
               and m["status"] in ("ACTIVE", "DELINQUENT", "SUSPENDED")]
    members.sort(key=lambda m: m["_seq"])

    for member in members:
        arrears, _ = ledger_svc.balances(member["id"])
        over = arrears >= local["delinquency_threshold_cents"]
        aged = _aged(member, local, cur_period)

        if member["status"] == "SUSPENDED":
            if member.get("suspended_since"):
                since = utils.parse_datetime(member["suspended_since"]).date()
                if utils.add_months(since, local["expel_after_months"]) <= cur_date:
                    member["status"] = "EXPELLED"
                    member["suspended_since"] = None
                    cancel_transfers(member["id"], NON_TERMINAL_TRANSFER_STATES)
                    db.touch(member)
                    result["expelled_member_ids"].append(member["id"])
            continue

        sent = [n for n in db.store.notices.values()
                if n["member_id"] == member["id"] and n["status"] == "SENT"]
        expired = [n for n in sent
                   if utils.parse_datetime(n["cure_deadline"]) <= now]

        if member["status"] == "ACTIVE":
            if aged and over:
                member["status"] = "DELINQUENT"
                db.touch(member)
                result["newly_delinquent_member_ids"].append(member["id"])
                has_draft = any(
                    n["member_id"] == member["id"] and n["status"] == "DRAFT"
                    for n in db.store.notices.values())
                if not has_draft:
                    _create_draft_notice(member, arrears)
                    result["notices_created"] += 1
            continue

        # DELINQUENT
        if expired:
            if over:
                for n in expired:
                    n["status"] = "EXPIRED"
                    db.touch(n)
                    result["notices_expired"] += 1
                if member["suspension_count"] + 1 >= local["max_suspensions"]:
                    member["status"] = "EXPELLED"
                    cancel_transfers(member["id"], NON_TERMINAL_TRANSFER_STATES)
                    db.touch(member)
                    result["expelled_member_ids"].append(member["id"])
                else:
                    member["status"] = "SUSPENDED"
                    member["suspension_count"] += 1
                    member["suspended_since"] = db.fmt_ts(now)
                    cancel_transfers(member["id"], ("INITIATED", "PENDING_TARGET"))
                    db.touch(member)
                    result["newly_suspended_member_ids"].append(member["id"])
            else:
                # Window closed and arrears dropped: cure.
                for n in sent:
                    n["status"] = "CURED"
                    db.touch(n)
                    result["notices_cured"] += 1
                member["status"] = "ACTIVE"
                _delete_drafts(member["id"])
                db.touch(member)
        elif not (aged and over):
            # Defensive auto-cure path.
            for n in sent:
                n["status"] = "CURED"
                db.touch(n)
                result["notices_cured"] += 1
            member["status"] = "ACTIVE"
            _delete_drafts(member["id"])
            db.touch(member)

    return result


def _create_draft_notice(member, arrears):
    ts = db.fmt_ts(db.now())
    notice = {
        "id": utils.new_id(),
        "member_id": member["id"],
        "arrears_at_notice_cents": arrears,
        "sent_at": None,
        "cure_deadline": None,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
    }
    db.store.notices[notice["id"]] = notice
    return notice


def _delete_drafts(member_id):
    for n in list(db.store.notices.values()):
        if n["member_id"] == member_id and n["status"] == "DRAFT":
            del db.store.notices[n["id"]]
