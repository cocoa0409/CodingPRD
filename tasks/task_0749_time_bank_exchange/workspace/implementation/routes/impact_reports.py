"""Impact report routes — §3.7."""
import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from flask import Blueprint, request
import db
from auth import require_role, ROLE_ADMIN
from errors import raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from response import envelope_object, envelope_array
from services import validators, pagination
from services.serializers import impact_report_dto
from db import parse_iso

bp = Blueprint("impact_reports", __name__)

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _month_range(report_month: str):
    """Return (start_dt, end_dt) as aware UTC datetimes for [first-of-month,
    first-of-next-month)."""
    y, m = report_month.split("-")
    y, m = int(y), int(m)
    if m < 1 or m > 12:
        raise_err(ERR_INVALID_REQUEST, "report_month month must be 01-12")
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return start, end


def _round_half_up_2dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@bp.route("/impact-reports", methods=["POST"])
def create_report():
    user_id, _ = require_role({ROLE_ADMIN})
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, ["report_month"])
    rm = validators.require_str(payload, "report_month")
    if not _MONTH_RE.match(rm):
        raise_err(ERR_INVALID_REQUEST, "report_month must be YYYY-MM")
    start, end = _month_range(rm)

    # SETTLED exchanges whose settled_at_utc lies in [start, end)
    settled = []
    for x in db.exchanges.values():
        if x["status"] != "SETTLED":
            continue
        sa = x.get("settled_at_utc")
        if not sa:
            continue
        sa_dt = parse_iso(sa)
        if start <= sa_dt < end:
            settled.append(x)

    # total_hours_exchanged: per-exchange rounded, then summed, then final round.
    total = Decimal("0")
    for x in settled:
        hrs = Decimal(x["committed_minutes"]) / Decimal(60)
        total += _round_half_up_2dp(hrs)
    total_hours = _round_half_up_2dp(total)

    # unique_active_members: distinct member_id on ledger entries whose posted_at
    # is in the month.
    members_seen = set()
    for e in db.ledger_entries.values():
        pa = parse_iso(e["posted_at"])
        if start <= pa < end:
            members_seen.add(e["member_id"])
    unique_active = len(members_seen)

    # top_skill_code: skill_code appearing on the most SETTLED exchanges in the
    # month. Tie-break: earliest settled_at_utc among that skill's settled
    # exchanges wins; then earliest LedgerEntry.posted_at; then alphabetic (ASCII).
    counts = {}
    earliest_settle = {}
    for x in settled:
        offer = db.skill_offers.get(x["offer_id"])
        if offer is None:
            continue
        code = offer["skill_code"]
        counts[code] = counts.get(code, 0) + 1
        sa_dt = parse_iso(x["settled_at_utc"])
        if code not in earliest_settle or sa_dt < earliest_settle[code]:
            earliest_settle[code] = sa_dt

    top_skill = None
    if counts:
        max_count = max(counts.values())
        contenders = [c for c, k in counts.items() if k == max_count]
        if len(contenders) == 1:
            top_skill = contenders[0]
        else:
            # earliest settled_at_utc
            contenders.sort(key=lambda c: earliest_settle[c])
            first_time = earliest_settle[contenders[0]]
            still_tied = [c for c in contenders if earliest_settle[c] == first_time]
            if len(still_tied) == 1:
                top_skill = still_tied[0]
            else:
                # earlier LedgerEntry.posted_at across relevant entries per skill
                earliest_post = {}
                for e in db.ledger_entries.values():
                    if e["entry_kind"] not in ("EARNED", "SPENT", "DISPUTE_REVERSAL"):
                        continue
                    xid = e.get("exchange_id")
                    if xid is None:
                        continue
                    x = db.exchanges.get(xid)
                    if x is None:
                        continue
                    offer = db.skill_offers.get(x["offer_id"])
                    if offer is None:
                        continue
                    if offer["skill_code"] not in still_tied:
                        continue
                    pa = parse_iso(e["posted_at"])
                    if start <= pa < end:
                        prev = earliest_post.get(offer["skill_code"])
                        if prev is None or pa < prev:
                            earliest_post[offer["skill_code"]] = pa
                if earliest_post:
                    still_tied2 = sorted(still_tied,
                                         key=lambda c: (earliest_post.get(c, end), c))
                    top_skill = still_tied2[0]
                else:
                    top_skill = sorted(still_tied)[0]

    r = {
        "report_month": rm,
        "total_hours_exchanged": float(total_hours),
        "unique_active_members": unique_active,
        "top_skill_code": top_skill,
        "generated_by_user_id": user_id,
    }
    db.stamp_new(r)
    db.impact_reports[r["id"]] = r
    return envelope_object(impact_report_dto(r), status=201)


@bp.route("/impact-reports", methods=["GET"])
def list_reports():
    require_role({ROLE_ADMIN})
    limit, offset = pagination.parse_pagination()
    items = list(db.impact_reports.values())
    rm = request.args.get("report_month")
    if rm is not None:
        items = [x for x in items if x["report_month"] == rm]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([impact_report_dto(x) for x in window], limit, offset, total)


@bp.route("/impact-reports/<rid>", methods=["GET"])
def get_report(rid):
    require_role({ROLE_ADMIN})
    r = db.impact_reports.get(rid)
    if r is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "ImpactReport not found")
    return envelope_object(impact_report_dto(r), status=200)
