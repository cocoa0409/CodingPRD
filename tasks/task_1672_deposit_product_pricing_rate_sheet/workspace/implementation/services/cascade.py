"""Sheet activation cascade and migration execution (PRD 3.2 / 3.7)."""

from db import STORE, today
from services.rates import (
    CHANNELS,
    create_notice,
    recompute_account_rates,
)
from utils import add_days_iso, bump, today_iso


def create_channel_rows(sheet):
    """Scheduling side effects: 4 RateDeployment + 4 PRE_CHANGE notices in the
    fixed channel order BRANCH, ONLINE, MOBILE, CALL_CENTER."""
    from utils import stamp_new
    required_by = add_days_iso(sheet["effective_date"], -sheet["disclosure_lead_days"])
    for ch in CHANNELS:
        dep = {"sheet_id": sheet["id"], "channel": ch, "deployed_at": None,
               "status": "PENDING"}
        stamp_new(dep)
        STORE["deployments"][dep["id"]] = dep
    for ch in CHANNELS:
        create_notice(sheet["id"], None, ch, "PRE_CHANGE", required_by)


def adverse_notice_if_drop(account, old_rate, sheet_id, trigger_date):
    if old_rate - account["current_rate_bp"] >= 10:
        create_notice(
            sheet_id,
            account["id"],
            account["channel"],
            "RATE_CHANGE_ADVERSE",
            add_days_iso(trigger_date, 5),
        )


def activate_sheet(sheet):
    """SCHEDULED -> EFFECTIVE with the seven-link cascade (PRD 3.2)."""
    t = today()
    tiso = t.isoformat()
    pair = (sheet["product_id"], sheet["market_code"])
    old = None
    for s in STORE["sheets"].values():
        if (
            s["id"] != sheet["id"]
            and s["product_id"] == sheet["product_id"]
            and s["market_code"] == sheet["market_code"]
            and s["status"] == "EFFECTIVE"
        ):
            old = s
            break

    # Link 1: lineage + supersession + window truncation.
    sheet["supersedes_sheet_id"] = old["id"] if old else None
    if old is not None:
        old["status"] = "SUPERSEDED"
        old["end_date"] = sheet["effective_date"]
        bump(old)

        # Link 2 (cascade link 1): old sheet's DEPLOYED deployments retire.
        for d in STORE["deployments"].values():
            if d["sheet_id"] == old["id"] and d["status"] == "DEPLOYED":
                d["status"] = "RETIRED"
                bump(d)

        # Link 3 (cascade link 2): re-price accounts on the superseded sheet.
        for a in STORE["accounts"].values():
            if a["sheet_id"] != old["id"] or a["lifecycle"] == "CLOSED":
                continue
            product = STORE["products"][a["product_id"]]
            old_rate = a["current_rate_bp"]
            if product["term_months"] == 0:
                a["sheet_id"] = sheet["id"]
                recompute_account_rates(a)
            else:
                a["rate_source"] = "GRANDFATHERED"  # rate frozen, sheet unchanged
            bump(a)
            # Link 4 (cascade link 3): adverse-change notices.
            adverse_notice_if_drop(a, old_rate, sheet["id"], tiso)

        # Link 5: pending exception requests on the old sheet need a rebase.
        for e in STORE["exceptions"].values():
            if e["sheet_id"] == old["id"] and e["status"] in ("UNDER_REVIEW", "RETURNED"):
                e["status"] = "REBASE_REQUIRED"
                bump(e)

    # Link 6: advance the pair's repricing cycle.
    for c in STORE["cycles"].values():
        if (c["product_id"], c["market_code"]) == pair:
            c["last_reviewed_at"] = tiso
            bump(c)
            break

    # Link 7: action the motivating scan.
    if sheet.get("source_scan_id"):
        scan = STORE["scans"].get(sheet["source_scan_id"])
        if scan is not None and scan["status"] == "ANALYZED":
            scan["status"] = "ACTIONED"
            bump(scan)

    sheet["status"] = "EFFECTIVE"
    bump(sheet)
    return sheet


def execute_migration(batch):
    """EXECUTE cascade (PRD 3.7)."""
    tiso = today().isoformat()
    src = STORE["sheets"][batch["source_sheet_id"]]
    tgt = STORE["sheets"][batch["target_sheet_id"]]
    migrated = 0
    skipped = 0
    for a in STORE["accounts"].values():
        if a["sheet_id"] != src["id"] or a["rate_source"] != "GRANDFATHERED":
            continue
        if a["lifecycle"] == "CLOSED":
            skipped += 1
            continue
        old_rate = a["current_rate_bp"]
        a["rate_source"] = "SHEET"
        a["sheet_id"] = tgt["id"]
        recompute_account_rates(a)
        bump(a)
        migrated += 1
        adverse_notice_if_drop(a, old_rate, tgt["id"], tiso)
    batch["migrated_count"] = migrated
    batch["skipped_count"] = skipped
    batch["status"] = "COMPLETED"
    bump(batch)
    # Cascade link 2b: auto-retire the source when no GRANDFATHERED accounts remain.
    remaining = any(
        a["sheet_id"] == src["id"] and a["rate_source"] == "GRANDFATHERED"
        for a in STORE["accounts"].values()
    )
    if not remaining:
        src["status"] = "RETIRED"
        bump(src)
    return batch
