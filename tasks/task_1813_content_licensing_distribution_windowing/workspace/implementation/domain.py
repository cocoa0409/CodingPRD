"""Business logic: serializers, conflict rules, cascades, sweep, calculations.

All rules trace to PRD.md §2–§3 and SCAFFOLD.yaml §1.2/§1.3/§1.4.
"""
from errors import err, ERR_EXCLUSIVITY_CONFLICT, ERR_HOLDBACK_CONFLICT
from store import DB, mutate
from util import (
    CLOCK,
    add_days,
    apply_pct_round,
    fmt_dt,
    norm_num,
    round_half_up_int,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTENT_TYPES = {"FILM", "SERIES"}
PLATFORM_TYPES = {"SVOD", "AVOD", "TVOD", "EST"}
WINDOW_TYPES = {"THEATRICAL", "EST", "TVOD", "SVOD", "AVOD", "FREE_TV"}
FEE_MODELS = {"FLAT_FEE", "REVENUE_SHARE", "MINIMUM_GUARANTEE"}
PRORATION_MODES = {"DAILY_PRORATION", "MONTHLY_PRORATION"}
ATTRIBUTION_MODES = {"BY_REPORT_DATE", "BY_USAGE_PERIOD"}

# Cross-window holdback matrix: exclusive license on window W blocks candidate
# licenses on the listed windows for the given number of buffer days beyond
# the upstream license_end (PRD §3.4).
HOLDBACK_MATRIX = {
    "THEATRICAL": {"EST": 90, "TVOD": 90, "SVOD": 90, "AVOD": 90, "FREE_TV": 90},
    "EST": {"SVOD": 60, "AVOD": 60, "FREE_TV": 60},
    "TVOD": {"SVOD": 30, "AVOD": 30, "FREE_TV": 30},
    "SVOD": {"AVOD": 30, "FREE_TV": 30},
    "AVOD": {},
    "FREE_TV": {},
}

LIVE_LICENSE_STATES = ("EXECUTED", "ACTIVE")

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_title(t):
    return {
        **_common(t),
        "title_code": t["title_code"],
        "name": t["name"],
        "content_type": t["content_type"],
        "original_language": t["original_language"],
        "production_year": t["production_year"],
        "embargoed_territories": list(t["embargoed_territories"]),
    }


def ser_holder(h):
    return {
        **_common(h),
        "name": h["name"],
        "payee_reference": h["payee_reference"],
        "royalty_share_pct": norm_num(h["royalty_share_pct"]),
    }


def ser_platform(p):
    return {
        **_common(p),
        "name": p["name"],
        "platform_type": p["platform_type"],
        "metadata_spec_version": p["metadata_spec_version"],
        "required_asset_profiles": list(p["required_asset_profiles"]),
    }


def ser_slot(s):
    return {
        **_common(s),
        "title_id": s["title_id"],
        "rights_holder_id": s["rights_holder_id"],
        "territory_code": s["territory_code"],
        "language_code": s["language_code"],
        "window_type": s["window_type"],
        "sellable_from": fmt_dt(s["sellable_from"]),
        "sellable_to": fmt_dt(s["sellable_to"]),
        "slot_status": s["slot_status"],
    }


def ser_line(line):
    return {
        "slot_id": line["slot_id"],
        "license_start": fmt_dt(line["license_start"]),
        "license_end": fmt_dt(line["license_end"]),
        "exclusive": line["exclusive"],
        "fee_model": line["fee_model"],
        "flat_fee_cents": line["flat_fee_cents"],
        "revenue_share_pct": norm_num(line["revenue_share_pct"]),
        "minimum_guarantee_cents": line["minimum_guarantee_cents"],
        "proration_mode": line["proration_mode"],
        "line_status": line["line_status"],
        "created_license_id": line["created_license_id"],
    }


def ser_package(p):
    return {
        **_common(p),
        "platform_id": p["platform_id"],
        "name": p["name"],
        "offer_expires_at": fmt_dt(p["offer_expires_at"]),
        "package_status": p["package_status"],
        "lines": [ser_line(l) for l in p["lines"]],
        "guaranteed_total_cents": p["guaranteed_total_cents"],
        "discount_pct": p["discount_pct"],
        "discount_cents": p["discount_cents"],
        "net_total_cents": p["net_total_cents"],
        "offered_at": fmt_dt(p["offered_at"]) if p["offered_at"] else None,
    }


def ser_license(l):
    return {
        **_common(l),
        "package_id": l["package_id"],
        "platform_id": l["platform_id"],
        "slot_id": l["slot_id"],
        "territory_code": l["territory_code"],
        "language_code": l["language_code"],
        "window_type": l["window_type"],
        "license_start": fmt_dt(l["license_start"]),
        "license_end": fmt_dt(l["license_end"]),
        "exclusive": l["exclusive"],
        "fee_model": l["fee_model"],
        "flat_fee_cents": l["flat_fee_cents"],
        "revenue_share_pct": norm_num(l["revenue_share_pct"]),
        "minimum_guarantee_cents": l["minimum_guarantee_cents"],
        "proration_mode": l["proration_mode"],
        "allocated_fee_cents": l["allocated_fee_cents"],
        "recouped_cents": l["recouped_cents"],
        "royalty_payable_cents": l["royalty_payable_cents"],
        "outstanding_recoupment_cents": l["outstanding_recoupment_cents"],
        "termination_credit_cents": l["termination_credit_cents"],
        "holdback_until": fmt_dt(l["holdback_until"]) if l["holdback_until"] else None,
        "license_status": l["license_status"],
        "activated_at": fmt_dt(l["activated_at"]) if l["activated_at"] else None,
    }


def ser_batch(b):
    return {
        **_common(b),
        "license_id": b["license_id"],
        "asset_manifest": list(b["asset_manifest"]),
        "metadata_spec_version": b["metadata_spec_version"],
        "delivery_status": b["delivery_status"],
        "missing_profiles": list(b["missing_profiles"]),
        "attempt_count": b["attempt_count"],
        "submitted_at": fmt_dt(b["submitted_at"]) if b["submitted_at"] else None,
        "delivered_at": fmt_dt(b["delivered_at"]) if b["delivered_at"] else None,
    }


def ser_notice(n):
    return {
        **_common(n),
        "license_id": n["license_id"],
        "scheduled_for": fmt_dt(n["scheduled_for"]),
        "notice_status": n["notice_status"],
        "executed_at": fmt_dt(n["executed_at"]) if n["executed_at"] else None,
    }


def ser_report(r):
    return {
        **_common(r),
        "license_id": r["license_id"],
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "gross_revenue_cents": r["gross_revenue_cents"],
        "royalty_accrued_cents": r["royalty_accrued_cents"],
        "recoupment_applied_cents": r["recoupment_applied_cents"],
        "payable_cents": r["payable_cents"],
        "report_status": r["report_status"],
        "submitted_at": fmt_dt(r["submitted_at"]),
    }


def ser_statement(s):
    return {
        **_common(s),
        "rights_holder_id": s["rights_holder_id"],
        "period_start": fmt_dt(s["period_start"]),
        "period_end": fmt_dt(s["period_end"]),
        "attribution_mode": s["attribution_mode"],
        "included_report_ids": list(s["included_report_ids"]),
        "gross_revenue_cents": s["gross_revenue_cents"],
        "studio_net_royalty_cents": s["studio_net_royalty_cents"],
        "holder_royalty_due_cents": s["holder_royalty_due_cents"],
        "statement_status": s["statement_status"],
        "finalized_by_user_id": s["finalized_by_user_id"],
        "paid_by_user_id": s["paid_by_user_id"],
    }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def paginate(args):
    """Parse limit/offset query params (defaults 10/0, clamped to spec bounds)."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_page(records, args):
    limit, offset = paginate(args)
    total = len(records)
    return records[offset : offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Fee structures / guaranteed value
# ---------------------------------------------------------------------------


def guaranteed_value(fee_model, flat_fee_cents, minimum_guarantee_cents):
    if fee_model == "FLAT_FEE":
        return flat_fee_cents
    if fee_model == "MINIMUM_GUARANTEE":
        return minimum_guarantee_cents
    return 0


def validate_fee_structure(fee_model, flat_fee_cents, revenue_share_pct, minimum_guarantee_cents):
    """Priority-9 fiscal rule: fee fields consistent with fee_model.

    Returns the normalized (flat, share, mg) tuple with non-applicable fields
    coerced to 0 ("otherwise 0" per the entity table).
    """
    from errors import err, ERR_FEE_STRUCTURE_INVALID

    if fee_model == "FLAT_FEE":
        if not flat_fee_cents or flat_fee_cents <= 0:
            err(ERR_FEE_STRUCTURE_INVALID, "FLAT_FEE requires flat_fee_cents > 0")
        if (revenue_share_pct or 0) > 0 or (minimum_guarantee_cents or 0) > 0:
            err(
                ERR_FEE_STRUCTURE_INVALID,
                "FLAT_FEE forbids revenue_share_pct / minimum_guarantee_cents > 0",
            )
        return flat_fee_cents, 0, 0
    if fee_model == "REVENUE_SHARE":
        if revenue_share_pct is None or not (0 < revenue_share_pct <= 100):
            err(
                ERR_FEE_STRUCTURE_INVALID,
                "REVENUE_SHARE requires revenue_share_pct in (0,100]",
            )
        return 0, revenue_share_pct, 0
    # MINIMUM_GUARANTEE
    if not minimum_guarantee_cents or minimum_guarantee_cents <= 0:
        err(ERR_FEE_STRUCTURE_INVALID, "MINIMUM_GUARANTEE requires minimum_guarantee_cents > 0")
    if revenue_share_pct is None or not (0 < revenue_share_pct <= 100):
        err(ERR_FEE_STRUCTURE_INVALID, "MINIMUM_GUARANTEE requires revenue_share_pct in (0,100]")
    return 0, revenue_share_pct, minimum_guarantee_cents


# ---------------------------------------------------------------------------
# Holdback derivation and conflict checks (PRD §2.8, §3.4)
# ---------------------------------------------------------------------------


def derive_holdback_until(window_type, license_end):
    row = HOLDBACK_MATRIX[window_type]
    if not row:
        return None
    return add_days(license_end, next(iter(row.values())))


def _license_cell(lic):
    slot = DB.get("slots", lic["slot_id"])
    return slot["title_id"] if slot else None, lic["territory_code"], lic["language_code"], lic["window_type"]


def check_conflicts(cand_slot, start, end, window_type, exclusive, exclude_license_id=None):
    """Same-cell exclusivity (half-open) then cross-window holdback (closed,
    buffered) against all EXECUTED/ACTIVE licenses on the same
    title/territory/language. Same-cell exclusivity is reported first."""
    cand_title = cand_slot["title_id"]
    cand_terr = cand_slot["territory_code"]
    cand_lang = cand_slot["language_code"]

    def _candidates():
        for lic in DB.all("licenses"):
            if exclude_license_id is not None and lic["id"] == exclude_license_id:
                continue
            if lic["license_status"] not in LIVE_LICENSE_STATES:
                continue
            title_id, terr, lang, _win = _license_cell(lic)
            if title_id != cand_title or terr != cand_terr or lang != cand_lang:
                continue
            yield lic

    # Same-cell exclusivity overlap: half-open [start, end)
    for lic in _candidates():
        if lic["window_type"] != window_type:
            continue
        if lic["license_start"] < end and start < lic["license_end"] and (
            lic["exclusive"] or exclusive
        ):
            err(ERR_EXCLUSIVITY_CONFLICT, "same-cell exclusivity overlap")

    # Cross-window holdback: closed buffered interval
    for lic in _candidates():
        if not lic["exclusive"]:
            continue
        row = HOLDBACK_MATRIX[lic["window_type"]]
        if window_type not in row:
            continue
        hb_until = lic["holdback_until"]
        if hb_until is None:
            hb_until = derive_holdback_until(lic["window_type"], lic["license_end"])
        if start <= hb_until and end >= lic["license_start"]:
            err(ERR_HOLDBACK_CONFLICT, "candidate window intersects an exclusive holdback interval")


def check_pairwise_line_conflicts(cands):
    """Pairwise conflict checks between candidate lines of one package.

    Each cand is a dict with slot, license_start, license_end, window_type,
    exclusive. Both same-cell (half-open) and holdback (closed, buffered)
    directions are examined.
    """
    n = len(cands)
    # Same-cell first (matches the vs-existing precedence).
    for i in range(n):
        for j in range(i + 1, n):
            a, b = cands[i], cands[j]
            if (
                a["slot"]["title_id"] == b["slot"]["title_id"]
                and a["slot"]["territory_code"] == b["slot"]["territory_code"]
                and a["slot"]["language_code"] == b["slot"]["language_code"]
                and a["slot"]["window_type"] == b["slot"]["window_type"]
            ):
                if a["license_start"] < b["license_end"] and b["license_start"] < a["license_end"] and (
                    a["exclusive"] or b["exclusive"]
                ):
                    err(ERR_EXCLUSIVITY_CONFLICT, "two lines of the package conflict (same cell)")
    for i in range(n):
        for j in range(i + 1, n):
            a, b = cands[i], cands[j]
            if (
                a["slot"]["title_id"] != b["slot"]["title_id"]
                or a["slot"]["territory_code"] != b["slot"]["territory_code"]
                or a["slot"]["language_code"] != b["slot"]["language_code"]
            ):
                continue
            for src, dst in ((a, b), (b, a)):
                if not src["exclusive"]:
                    continue
                row = HOLDBACK_MATRIX[src["slot"]["window_type"]]
                dst_window = dst["slot"]["window_type"]
                if dst_window not in row:
                    continue
                hb_until = add_days(src["license_end"], row[dst_window])
                if dst["license_start"] <= hb_until and dst["license_end"] >= src["license_start"]:
                    err(ERR_HOLDBACK_CONFLICT, "two lines of the package conflict (holdback)")


# ---------------------------------------------------------------------------
# Encumbrance / blocking cascade (PRD §3.4)
# ---------------------------------------------------------------------------


def block_lines_on_slot(slot_id, tallies=None, exclude_package_id=None, expire_all_blocked=True):
    """Hop 1: OFFERED-package lines on this slot -> BLOCKED.

    When the slot is gone for good (withdrawal / rights lapse), hops 2-3 also
    run: an OFFERED package whose every line is BLOCKED -> EXPIRED, and its
    non-LICENSED lines -> NOT_SELECTED. Temporary encumbrance by an exclusive
    license only blocks (expire_all_blocked=False) so the lines can be
    restored to OFFERED when the encumbrance lifts."""
    for pkg in DB.all("packages"):
        if pkg["package_status"] != "OFFERED":
            continue
        if exclude_package_id is not None and pkg["id"] == exclude_package_id:
            continue
        changed = False
        for line in pkg["lines"]:
            if line["slot_id"] == slot_id and line["line_status"] == "OFFERED":
                line["line_status"] = "BLOCKED"
                changed = True
        if not changed:
            continue
        if expire_all_blocked and all(l["line_status"] == "BLOCKED" for l in pkg["lines"]):
            pkg["package_status"] = "EXPIRED"
            for l in pkg["lines"]:
                if l["line_status"] != "LICENSED":
                    l["line_status"] = "NOT_SELECTED"
            if tallies is not None:
                tallies["packages_expired"] += 1
        mutate(pkg)


def unblock_lines_on_slot(slot_id):
    """Release hop: BLOCKED lines referencing this slot inside OFFERED packages
    return to OFFERED."""
    for pkg in DB.all("packages"):
        if pkg["package_status"] != "OFFERED":
            continue
        changed = False
        for line in pkg["lines"]:
            if line["slot_id"] == slot_id and line["line_status"] == "BLOCKED":
                line["line_status"] = "OFFERED"
                changed = True
        if changed:
            mutate(pkg)


def encumber_slot(slot, tallies=None, exclude_package_id=None):
    """AVAILABLE -> ENCUMBERED (idempotent if already ENCUMBERED), then the
    cross-package block hop (no all-blocked expiry: the encumbrance can lift)."""
    if slot["slot_status"] == "AVAILABLE":
        slot["slot_status"] = "ENCUMBERED"
        mutate(slot)
    block_lines_on_slot(
        slot["id"],
        tallies=tallies,
        exclude_package_id=exclude_package_id,
        expire_all_blocked=False,
    )


def release_slot_if_free(slot):
    """ENCUMBERED -> AVAILABLE when no EXECUTED/ACTIVE exclusive license still
    references the slot; EXPIRED/WITHDRAWN slots are left alone (slot expiry
    dominates). Then the unblock hop runs."""
    if slot["slot_status"] != "ENCUMBERED":
        return
    for lic in DB.all("licenses"):
        if (
            lic["slot_id"] == slot["id"]
            and lic["exclusive"]
            and lic["license_status"] in LIVE_LICENSE_STATES
        ):
            return
    slot["slot_status"] = "AVAILABLE"
    mutate(slot)
    unblock_lines_on_slot(slot["id"])


# ---------------------------------------------------------------------------
# Takedown notices
# ---------------------------------------------------------------------------


def create_notice(lic):
    return DB.insert(
        "notices",
        {
            "license_id": lic["id"],
            "scheduled_for": lic["license_end"],
            "notice_status": "SCHEDULED",
            "executed_at": None,
        },
    )


def execute_notice_for_license(lic, when, tallies=None):
    for n in DB.all("notices"):
        if n["license_id"] == lic["id"] and n["notice_status"] == "SCHEDULED":
            n["notice_status"] = "EXECUTED"
            n["executed_at"] = when
            mutate(n)
            if tallies is not None:
                tallies["notices_executed"] += 1


# ---------------------------------------------------------------------------
# License creation / termination / credit
# ---------------------------------------------------------------------------


def create_license(
    slot,
    platform_id,
    license_start,
    license_end,
    exclusive,
    fee_model,
    flat_fee_cents,
    revenue_share_pct,
    minimum_guarantee_cents,
    proration_mode,
    package_id,
    allocated_fee_cents,
):
    lic = DB.insert(
        "licenses",
        {
            "package_id": package_id,
            "platform_id": platform_id,
            "slot_id": slot["id"],
            "territory_code": slot["territory_code"],
            "language_code": slot["language_code"],
            "window_type": slot["window_type"],
            "license_start": license_start,
            "license_end": license_end,
            "exclusive": exclusive,
            "fee_model": fee_model,
            "flat_fee_cents": flat_fee_cents,
            "revenue_share_pct": revenue_share_pct,
            "minimum_guarantee_cents": minimum_guarantee_cents,
            "proration_mode": proration_mode,
            "allocated_fee_cents": allocated_fee_cents,
            "recouped_cents": 0,
            "royalty_payable_cents": 0,
            "outstanding_recoupment_cents": minimum_guarantee_cents
            if fee_model == "MINIMUM_GUARANTEE"
            else 0,
            "termination_credit_cents": None,
            "holdback_until": derive_holdback_until(slot["window_type"], license_end)
            if exclusive
            else None,
            "license_status": "EXECUTED",
            "activated_at": None,
        },
    )
    create_notice(lic)
    if exclusive:
        encumber_slot(slot, exclude_package_id=package_id)
    return lic


def compute_termination_credit(lic, terminated_at):
    """Prorated credit per proration_mode (PRD §3.6). Integer cents, half-up."""
    basis = lic["allocated_fee_cents"]
    remaining_seconds = max(0, int((lic["license_end"] - terminated_at).total_seconds()))
    total_seconds = max(1, int((lic["license_end"] - lic["license_start"]).total_seconds()))
    if lic["proration_mode"] == "MONTHLY_PRORATION":
        remaining_days = remaining_seconds // 86400
        total_days = total_seconds // 86400
        blocks_remaining = remaining_days // 30
        blocks_total = -(-total_days // 30)  # ceil
        if blocks_remaining == 0 or blocks_total == 0:
            return 0
        return round_half_up_int(basis * blocks_remaining, blocks_total)
    # DAILY_PRORATION
    return round_half_up_int(basis * remaining_seconds, total_seconds)


def terminate_license(lic, terminated_at, tallies=None):
    """EXECUTED|ACTIVE -> TERMINATED with credit, immediate takedown, and the
    slot-release cascade (suppressed automatically when the slot is terminal)."""
    lic["termination_credit_cents"] = compute_termination_credit(lic, terminated_at)
    lic["license_status"] = "TERMINATED"
    mutate(lic)
    execute_notice_for_license(lic, terminated_at, tallies=tallies)
    if lic["exclusive"]:
        slot = DB.get("slots", lic["slot_id"])
        if slot is not None:
            release_slot_if_free(slot)


# ---------------------------------------------------------------------------
# Package volume discount (PRD §3.5, pinned evaluation order)
# ---------------------------------------------------------------------------


def apply_volume_discount(pkg, accepted_indices):
    """Run the tiered volume discount over the accepted lines. Stores
    discount_pct / discount_cents / net_total_cents on the package and returns
    {line_index: allocated_fee_cents}."""
    lines = pkg["lines"]

    def gv(i):
        l = lines[i]
        return guaranteed_value(l["fee_model"], l["flat_fee_cents"], l["minimum_guarantee_cents"])

    gross = sum(gv(i) for i in accepted_indices)
    if gross >= 5_000_000:
        pct = 15
    elif gross >= 2_000_000:
        pct = 10
    elif gross >= 500_000:
        pct = 5
    else:
        pct = 0
    discount_cents = round_half_up_int(gross * pct, 100)

    per_line = {}
    if gross > 0:
        remainder = discount_cents
        chosen = None
        for i in sorted(accepted_indices):
            g = gv(i)
            if g > 0 and chosen is None:
                chosen = i
            d = round_half_up_int(discount_cents * g, gross) if g > 0 else 0
            per_line[i] = d
            remainder -= d
        if chosen is not None:
            per_line[chosen] += remainder
    else:
        for i in accepted_indices:
            per_line[i] = 0

    pkg["discount_pct"] = pct
    pkg["discount_cents"] = discount_cents
    pkg["net_total_cents"] = gross - discount_cents
    return {i: gv(i) - per_line[i] for i in accepted_indices}


# ---------------------------------------------------------------------------
# Recoupment waterfall (PRD §3.8)
# ---------------------------------------------------------------------------


def book_report(lic, report):
    """Book a revenue report through the recoupment waterfall (same-request
    ledger update on the license)."""
    accrued = apply_pct_round(report["gross_revenue_cents"], lic["revenue_share_pct"])
    if lic["fee_model"] == "MINIMUM_GUARANTEE":
        applied = min(accrued, lic["outstanding_recoupment_cents"])
    else:
        applied = 0
    payable = accrued - applied
    report["royalty_accrued_cents"] = accrued
    report["recoupment_applied_cents"] = applied
    report["payable_cents"] = payable
    lic["recouped_cents"] += applied
    lic["royalty_payable_cents"] += payable
    if lic["fee_model"] == "MINIMUM_GUARANTEE":
        lic["outstanding_recoupment_cents"] = max(
            0, lic["minimum_guarantee_cents"] - lic["recouped_cents"]
        )
    else:
        lic["outstanding_recoupment_cents"] = 0
    mutate(lic)


def replay_recoupment(lic):
    """After a reversal: reset the ledger and replay the remaining SUBMITTED
    reports in chronological order (submitted_at ASC, tie-break created_at)."""
    lic["recouped_cents"] = 0
    lic["royalty_payable_cents"] = 0
    lic["outstanding_recoupment_cents"] = (
        lic["minimum_guarantee_cents"] if lic["fee_model"] == "MINIMUM_GUARANTEE" else 0
    )
    remaining = [
        r
        for r in DB.all("reports")
        if r["license_id"] == lic["id"] and r["report_status"] == "SUBMITTED"
    ]
    remaining.sort(key=lambda r: (r["submitted_at"], r["created_at"], r["_seq"]))
    for r in remaining:
        if lic["fee_model"] == "MINIMUM_GUARANTEE":
            applied = min(r["royalty_accrued_cents"], lic["outstanding_recoupment_cents"])
        else:
            applied = 0
        payable = r["royalty_accrued_cents"] - applied
        lic["recouped_cents"] += applied
        lic["royalty_payable_cents"] += payable
        if lic["fee_model"] == "MINIMUM_GUARANTEE":
            lic["outstanding_recoupment_cents"] = max(
                0, lic["minimum_guarantee_cents"] - lic["recouped_cents"]
            )
        else:
            lic["outstanding_recoupment_cents"] = 0
    mutate(lic)


# ---------------------------------------------------------------------------
# Statement attribution (PRD §3.9)
# ---------------------------------------------------------------------------


def compute_statement(stmt):
    holder = DB.get("holders", stmt["rights_holder_id"])
    included = []
    for r in DB.all("reports"):
        if r["report_status"] != "SUBMITTED":
            continue
        lic = DB.get("licenses", r["license_id"])
        if lic is None:
            continue
        slot = DB.get("slots", lic["slot_id"])
        if slot is None or slot["rights_holder_id"] != stmt["rights_holder_id"]:
            continue
        if stmt["attribution_mode"] == "BY_REPORT_DATE":
            if not (stmt["period_start"] <= r["submitted_at"] <= stmt["period_end"]):
                continue
        else:  # BY_USAGE_PERIOD — intersection, both intervals closed
            if not (
                r["period_start"] <= stmt["period_end"]
                and r["period_end"] >= stmt["period_start"]
            ):
                continue
        included.append(r)
    included.sort(key=lambda r: (r["submitted_at"], r["created_at"], r["_seq"]))
    stmt["included_report_ids"] = [r["id"] for r in included]
    stmt["gross_revenue_cents"] = sum(r["gross_revenue_cents"] for r in included)
    stmt["studio_net_royalty_cents"] = sum(r["payable_cents"] for r in included)
    stmt["holder_royalty_due_cents"] = apply_pct_round(
        stmt["studio_net_royalty_cents"], holder["royalty_share_pct"]
    )


# ---------------------------------------------------------------------------
# Expiration sweep (PRD §2.5, pinned order)
# ---------------------------------------------------------------------------


def run_sweep(now):
    tallies = {
        "slots_expired": 0,
        "licenses_expired": 0,
        "licenses_terminated": 0,
        "packages_expired": 0,
        "notices_executed": 0,
    }

    # (1) Slots first: AVAILABLE|ENCUMBERED with sellable_to <= now -> EXPIRED.
    expired_slot_ids = []
    for slot in DB.all("slots"):
        if slot["slot_status"] in ("AVAILABLE", "ENCUMBERED") and slot["sellable_to"] <= now:
            was_encumbered = slot["slot_status"] == "ENCUMBERED"
            slot["slot_status"] = "EXPIRED"
            mutate(slot)
            tallies["slots_expired"] += 1
            expired_slot_ids.append(slot["id"])
            if was_encumbered:
                # Rights-lapse cascade: live licenses -> TERMINATED (credit per
                # proration mode, terminated_at = sweep time); notices -> EXECUTED.
                for lic in DB.all("licenses"):
                    if lic["slot_id"] == slot["id"] and lic["license_status"] in LIVE_LICENSE_STATES:
                        terminate_license(lic, now, tallies=tallies)
                        tallies["licenses_terminated"] += 1
    # After slot expirations settle: blocked-line propagation + all-blocked
    # package expiry for every expired slot.
    for sid in expired_slot_ids:
        block_lines_on_slot(sid, tallies=tallies)

    # (2) Licenses second: EXECUTED|ACTIVE with license_end <= now -> EXPIRED.
    for lic in DB.all("licenses"):
        if lic["license_status"] in LIVE_LICENSE_STATES and lic["license_end"] <= now:
            lic["license_status"] = "EXPIRED"
            mutate(lic)
            tallies["licenses_expired"] += 1
            execute_notice_for_license(lic, now, tallies=tallies)
            if lic["exclusive"]:
                slot = DB.get("slots", lic["slot_id"])
                if slot is not None:
                    release_slot_if_free(slot)

    # (3) Packages third: OFFERED with offer_expires_at <= now -> EXPIRED.
    for pkg in DB.all("packages"):
        if pkg["package_status"] == "OFFERED" and pkg["offer_expires_at"] <= now:
            pkg["package_status"] = "EXPIRED"
            for l in pkg["lines"]:
                if l["line_status"] != "LICENSED":
                    l["line_status"] = "NOT_SELECTED"
            mutate(pkg)
            tallies["packages_expired"] += 1

    return tallies
