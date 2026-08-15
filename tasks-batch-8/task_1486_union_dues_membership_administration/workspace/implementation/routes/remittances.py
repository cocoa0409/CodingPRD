"""CheckoffRemittance + RemittanceLine: receipt, line entry, reconciliation,
dispute resolution, posting (with auto-cure cascade), and void unwind."""
from flask import Blueprint, request

import db
import errors
import serializers
import utils
from middleware import require_roles, ALL_ROLES
from response import ok, ok_list
from services import dues as dues_svc
from services import ledger as ledger_svc

bp = Blueprint("remittances", __name__, url_prefix="/api/remittances")

TERMINAL_MEMBER_STATES = ("WITHDRAWN", "EXPELLED")


def get_remittance_or_404(remittance_id):
    rem = db.store.remittances.get(remittance_id)
    if rem is None:
        raise errors.remittance_not_found()
    return rem


def remittance_lines(remittance_id):
    rows = [l for l in db.store.remittance_lines.values()
            if l["remittance_id"] == remittance_id]
    rows.sort(key=lambda l: l["_seq"])
    return rows


def on_roster(member, rem):
    return (member["employer_id"] == rem["employer_id"]
            and member["local_id"] == rem["local_id"]
            and member["status"] not in TERMINAL_MEMBER_STATES)


def roster_members(rem, statuses=("ACTIVE", "DELINQUENT")):
    rows = [m for m in db.store.members.values()
            if m["employer_id"] == rem["employer_id"]
            and m["local_id"] == rem["local_id"]
            and m["status"] in statuses]
    rows.sort(key=lambda m: m["_seq"])
    return rows


@bp.route("", methods=["POST"])
@require_roles("OfficeClerk")
def create_remittance(user_id, role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    employer_id = utils.require_field(body, "employer_id")
    local_id = utils.require_field(body, "local_id")
    period = utils.require_field(body, "period")
    remitted_cents = utils.require_int(body, "remitted_cents")
    if employer_id not in db.store.employers:
        raise errors.employer_not_found_body()
    if local_id not in db.store.locals:
        raise errors.local_not_found_body()
    utils.parse_period(period)
    for r in db.store.remittances.values():
        if r["employer_id"] == employer_id and r["period"] == period:
            raise errors.remittance_exists()
    ts = db.fmt_ts(db.now())
    rem = {
        "id": utils.new_id(),
        "employer_id": employer_id,
        "local_id": local_id,
        "period": period,
        "remitted_cents": remitted_cents,
        "status": "RECEIVED",
        "dispute_status": "NONE",
        "expected_total_cents": None,
        "header_variance_cents": None,
        "missing_member_ids": [],
        "auto_cured_member_ids": [],
        "received_by_user_id": user_id,
        "posted_by_user_id": None,
        "posted_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
        "_produced_entry_ids": [],
    }
    db.store.remittances[rem["id"]] = rem
    return ok(serializers.remittance(rem), 201)


@bp.route("", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_remittances(user_id, role):
    rows = list(db.store.remittances.values())
    for f in ("employer_id", "local_id", "period", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r.get(f) == v]
    rows.sort(key=lambda r: r["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.remittance(r) for r in page], meta)


@bp.route("/<remittance_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_remittance(user_id, role, remittance_id):
    return ok(serializers.remittance(get_remittance_or_404(remittance_id)), 200)


@bp.route("/<remittance_id>/lines", methods=["POST"])
@require_roles("OfficeClerk")
def create_line(user_id, role, remittance_id):
    rem = get_remittance_or_404(remittance_id)
    if rem["status"] != "RECEIVED":
        raise errors.remittance_not_received()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    member_id = utils.require_field(body, "member_id")
    deducted = utils.require_int(body, "deducted_cents")
    gross = utils.require_int(body, "gross_wages_cents")
    member = db.store.members.get(member_id)
    if member is None:
        raise errors.member_not_found_body()
    if not on_roster(member, rem):
        raise errors.member_not_on_roster()
    for l in remittance_lines(remittance_id):
        if l["member_id"] == member_id:
            raise errors.duplicate_remittance_line()
    ts = db.fmt_ts(db.now())
    line = {
        "id": utils.new_id(),
        "remittance_id": remittance_id,
        "member_id": member_id,
        "deducted_cents": deducted,
        "gross_wages_cents": gross,
        "variance_cents": None,
        "line_status": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
    }
    db.store.remittance_lines[line["id"]] = line
    return ok(serializers.remittance_line(line), 201)


@bp.route("/<remittance_id>/lines", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_lines(user_id, role, remittance_id):
    get_remittance_or_404(remittance_id)
    rows = remittance_lines(remittance_id)
    page, meta = utils.paginate(rows)
    return ok_list([serializers.remittance_line(l) for l in page], meta)


def _finalize_or_synthesize(member, period, gross, rem, affected):
    """Finalize the member's PROVISIONAL with the line's gross wages, or
    synthesize a FINAL assessment (at the line's reported gross) when none
    exists. Records produced ledger entries on the remittance for void."""
    assessment = next(
        (a for a in db.store.assessments.values()
         if a["member_id"] == member["id"] and a["period"] == period), None)
    if assessment is not None and assessment["status"] == "FINAL":
        return assessment
    if assessment is None:
        assessment = dues_svc.create_assessment(member, period, gross, "FINAL")
        # The synthesized charge is NOT a finalize-delta: voiding negates only
        # CHECKOFF_CREDITs and finalize-delta entries, so this entry is not
        # tracked in _produced_entry_ids.
        ledger_svc.post_entry(
            member["id"], "ASSESSMENT_CHARGE", assessment["assessed_cents"],
            period, memo="remittance %s synthesized assessment" % rem["id"],
            assessment_id=assessment["id"], remittance_id=rem["id"])
    else:
        entry = dues_svc.finalize_assessment(assessment, gross)
        if entry is not None:
            entry["_remittance_id"] = rem["id"]
            rem["_produced_entry_ids"].append(entry["id"])
    affected.add(member["id"])
    return assessment


@bp.route("/<remittance_id>/reconcile", methods=["POST"])
@require_roles("SecretaryTreasurer")
def reconcile(user_id, role, remittance_id):
    rem = get_remittance_or_404(remittance_id)
    if rem["status"] != "RECEIVED":
        raise errors.remittance_not_received()
    lines = remittance_lines(remittance_id)
    # Roster re-validation runs before any variance is computed: a line whose
    # member no longer qualifies rejects the whole reconcile.
    for l in lines:
        member = db.store.members.get(l["member_id"])
        if member is None or not on_roster(member, rem):
            raise errors.member_not_on_roster()
    # Header must balance.
    deducted_sum = sum(l["deducted_cents"] for l in lines)
    header_variance = rem["remitted_cents"] - deducted_sum
    if header_variance != 0:
        rem["header_variance_cents"] = header_variance
        db.store.remittances[rem["id"]] = rem
        raise errors.remittance_unbalanced()

    affected = set()
    for l in lines:
        member = db.store.members[l["member_id"]]
        assessment = _finalize_or_synthesize(
            member, rem["period"], l["gross_wages_cents"], rem, affected)
        variance = l["deducted_cents"] - assessment["assessed_cents"]
        l["variance_cents"] = variance
        l["line_status"] = ("MATCHED" if variance == 0
                            else "UNDER_DEDUCTED" if variance < 0
                            else "OVER_DEDUCTED")
        db.touch(l)

    roster = roster_members(rem)
    lined_ids = {l["member_id"] for l in lines}
    expected = 0
    missing = []
    for m in roster:
        has_assessment = any(
            a["member_id"] == m["id"] and a["period"] == rem["period"]
            for a in db.store.assessments.values())
        if not has_assessment:
            continue
        assessment = next(a for a in db.store.assessments.values()
                          if a["member_id"] == m["id"]
                          and a["period"] == rem["period"])
        expected += assessment["assessed_cents"]
        if m["id"] not in lined_ids:
            missing.append(m["id"])

    rem["expected_total_cents"] = expected
    rem["header_variance_cents"] = header_variance
    rem["missing_member_ids"] = missing

    clean = all(l["variance_cents"] == 0 for l in lines) and not missing
    if clean:
        rem["status"] = "RECONCILED"
    else:
        # Parallel dimension: only the dispute dimension moves.
        if rem["dispute_status"] == "NONE":
            rem["dispute_status"] = "DISPUTED"
    db.touch(rem)
    for mid in affected:
        db.touch(db.store.members[mid])
    return ok(serializers.remittance(rem), 200)


@bp.route("/<remittance_id>/resolve-dispute", methods=["POST"])
@require_roles("SecretaryTreasurer")
def resolve_dispute(user_id, role, remittance_id):
    rem = get_remittance_or_404(remittance_id)
    if rem["status"] != "RECEIVED":
        raise errors.remittance_not_received()
    if rem["dispute_status"] != "DISPUTED":
        raise errors.dispute_not_active()
    # Resolution accepts union-assessed FINAL amounts; missing members'
    # assessments finalize at the floor with a wage base of zero.
    affected = set()
    for mid in rem["missing_member_ids"]:
        member = db.store.members.get(mid)
        if member is None:
            continue
        assessment = next(
            (a for a in db.store.assessments.values()
             if a["member_id"] == mid and a["period"] == rem["period"]
             and a["status"] == "PROVISIONAL"), None)
        if assessment is not None:
            entry = dues_svc.finalize_assessment(assessment, 0)
            if entry is not None:
                entry["_remittance_id"] = rem["id"]
                rem["_produced_entry_ids"].append(entry["id"])
            affected.add(mid)
    rem["dispute_status"] = "RESOLVED"
    rem["status"] = "RECONCILED"
    db.touch(rem)
    for mid in affected:
        db.touch(db.store.members[mid])
    return ok(serializers.remittance(rem), 200)


@bp.route("/<remittance_id>/post", methods=["POST"])
@require_roles("SecretaryTreasurer")
def post_remittance(user_id, role, remittance_id):
    rem = get_remittance_or_404(remittance_id)
    if rem["status"] != "RECONCILED":
        raise errors.remittance_not_reconciled()
    # Strictly chronological posting per employer: every other remittance of
    # the same employer with a strictly earlier period must be POSTED or VOID.
    for r in db.store.remittances.values():
        if (r["id"] != rem["id"] and r["employer_id"] == rem["employer_id"]
                and r["period"] < rem["period"]
                and r["status"] not in ("POSTED", "VOID")):
            raise errors.prior_period_unposted()
    if user_id == rem["received_by_user_id"]:
        raise errors.segregation_of_duties()

    affected = set()
    for l in remittance_lines(remittance_id):
        entry = ledger_svc.post_entry(
            l["member_id"], "CHECKOFF_CREDIT", -l["deducted_cents"],
            rem["period"], memo="remittance %s post" % rem["id"],
            remittance_id=rem["id"])
        rem["_produced_entry_ids"].append(entry["id"])
        affected.add(l["member_id"])
    for mid in sorted(affected):
        member = db.store.members[mid]
        ledger_svc.auto_cure(member, remittance=rem)
        db.touch(member)
    rem["status"] = "POSTED"
    rem["posted_at"] = db.fmt_ts(db.now())
    rem["posted_by_user_id"] = user_id
    db.touch(rem)
    return ok(serializers.remittance(rem), 200)


@bp.route("/<remittance_id>/void", methods=["POST"])
@require_roles("LocalAdmin")
def void_remittance(user_id, role, remittance_id):
    rem = get_remittance_or_404(remittance_id)
    if rem["status"] != "POSTED":
        raise errors.remittance_not_posted()
    # Strictly reverse-chronological unwind: no same-employer remittance with
    # a strictly later period may be POSTED.
    for r in db.store.remittances.values():
        if (r["id"] != rem["id"] and r["employer_id"] == rem["employer_id"]
                and r["period"] > rem["period"] and r["status"] == "POSTED"):
            raise errors.prior_period_unposted()
    # Period lock: the period's per-capita report may not be SUBMITTED/PAID.
    for r in db.store.per_capita_reports.values():
        if (r["local_id"] == rem["local_id"] and r["period"] == rem["period"]
                and r["status"] in ("SUBMITTED", "PAID")):
            raise errors.period_locked()

    affected = set()
    for entry_id in rem["_produced_entry_ids"]:
        original = db.store.ledger_entries.get(entry_id)
        if original is None:
            continue
        reversal = ledger_svc.post_entry(
            original["member_id"], "VOID_REVERSAL",
            -original["amount_cents"], original["period"],
            memo="void reversal of %s (remittance %s)" % (original["id"], rem["id"]),
            remittance_id=rem["id"])
        affected.add(original["member_id"])
    # Compensation: members auto-cured by this posting revert to DELINQUENT.
    for mid in rem["auto_cured_member_ids"]:
        member = db.store.members.get(mid)
        if member is not None and member["status"] == "ACTIVE":
            member["status"] = "DELINQUENT"
            db.touch(member)
    for mid in affected:
        db.touch(db.store.members[mid])
    rem["status"] = "VOID"
    db.touch(rem)
    return ok(serializers.remittance(rem), 200)
