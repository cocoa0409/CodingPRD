"""Bid-domain calculations: bonds, leveling, tabulation ranking, ack flags."""
from decimal import Decimal, ROUND_HALF_UP

from db import DB, CLOCK, touch
from services import prequal as prequal_svc


def round_half_up_cents(product: Decimal) -> int:
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def required_bid_bond(base_bid_cents: int, pct) -> int:
    """round_half_up(base_bid_cents * pct) to integer cents; equality passes."""
    return round_half_up_cents(Decimal(base_bid_cents) * Decimal(str(pct)))


def resolve_adjustment(adj, bid) -> int:
    """resolved_amount_cents: amount verbatim, or round_half_up(base * pct).
    EXCLUDED_SCOPE contributes 0 to the leveled total (tracked on the sheet)."""
    if adj.get("amount_cents") is not None:
        return adj["amount_cents"]
    if adj.get("pct_of_base") is not None:
        return round_half_up_cents(Decimal(bid["base_bid_cents"]) * Decimal(str(adj["pct_of_base"])))
    return 0


def leveled_amount(bid) -> int:
    """base + SUM(resolved) over GC_ALLOWANCE/SUB_QUOTE; EXCLUDED_SCOPE contributes 0.
    Per-adjustment rounding happens in resolve_adjustment BEFORE summation."""
    total = bid["base_bid_cents"]
    for adj in DB.leveling_adjustments.values():
        if adj["bid_id"] != bid["id"]:
            continue
        if adj["treatment"] in ("GC_ALLOWANCE", "SUB_QUOTE"):
            total += adj["resolved_amount_cents"]
    return total


def has_exclusions(bid) -> bool:
    return any(
        a["bid_id"] == bid["id"] and a["treatment"] == "EXCLUDED_SCOPE"
        for a in DB.leveling_adjustments.values()
    )


def pending_ack_count(package_id: str, subcontractor_id: str) -> int:
    n = 0
    for ack in DB.acks.values():
        if ack["subcontractor_id"] != subcontractor_id or ack["status"] != "PENDING":
            continue
        add = DB.addendums.get(ack["addendum_id"])
        if add and add["bid_package_id"] == package_id:
            n += 1
    return n


def recompute_ack_complete_for(package_id: str, subcontractor_id: str) -> None:
    """addendum_ack_complete is True iff no PENDING ack for (package, subcontractor).
    Recomputed on that subcontractor's SUBMITTED bids of the package."""
    complete = pending_ack_count(package_id, subcontractor_id) == 0
    for bid in DB.bids.values():
        if (
            bid["bid_package_id"] == package_id
            and bid["subcontractor_id"] == subcontractor_id
            and bid["status"] == "SUBMITTED"
        ):
            if bid["addendum_ack_complete"] != complete:
                bid["addendum_ack_complete"] = complete
                touch(bid)


def submitted_bid(package_id: str, subcontractor_id: str):
    for bid in DB.bids.values():
        if (
            bid["bid_package_id"] == package_id
            and bid["subcontractor_id"] == subcontractor_id
            and bid["status"] == "SUBMITTED"
        ):
            return bid
    return None


# ---------------------------------------------------------------------------
# Tabulation
# ---------------------------------------------------------------------------
def _tie_key(bid):
    return (bid["_submitted_at_dt"], bid["_created_at_dt"])


def compliance_sweep(package) -> list:
    """Phase 1: disqualify SUBMITTED bids. Ack check runs BEFORE prequal check.
    Returns the list of compliant (still SUBMITTED) bids. Does not mutate on
    empty compliant set — caller checks and aborts before any change persists."""
    bids = [b for b in DB.bids.values()
            if b["bid_package_id"] == package["id"] and b["status"] == "SUBMITTED"]
    disqualified = []  # (bid, reason)
    compliant = []
    for bid in bids:
        if pending_ack_count(package["id"], bid["subcontractor_id"]) > 0:
            disqualified.append((bid, "MISSING_ADDENDUM_ACK"))
        elif not prequal_svc.has_approved_prequal(bid["subcontractor_id"]):
            disqualified.append((bid, "PREQUAL_LAPSED"))
        else:
            compliant.append(bid)
    return compliant, disqualified


def run_tabulation(package) -> None:
    """Full tabulate: sweep then ranking. Raises ERR_NO_COMPLIANT_BIDS with NO
    state changes when the compliant set is empty (checked before mutating)."""
    import errors

    compliant, disqualified = compliance_sweep(package)
    if len(compliant) == 0:
        raise errors.err_no_compliant_bids()

    # Persist disqualifications only after we know the call succeeds.
    for bid, reason in disqualified:
        bid["status"] = "DISQUALIFIED"
        bid["disqualification_reason"] = reason
        touch(bid)
        package["submitted_bid_count"] -= 1

    # Ranking: apparent by base_bid_cents; leveled by leveled amount.
    apparent_sorted = sorted(compliant, key=lambda b: (b["base_bid_cents"],) + _tie_key(b))
    leveled_sorted = sorted(compliant, key=lambda b: (leveled_amount(b),) + _tie_key(b))

    package["apparent_low_bid_id"] = apparent_sorted[0]["id"]
    package["leveled_low_bid_id"] = leveled_sorted[0]["id"]
    package["compliant_bid_count"] = len(compliant)

    # Snapshot each compliant bid's leveled rank (used later for feedback).
    package["_leveled_rank_by_bid"] = {b["id"]: i + 1 for i, b in enumerate(leveled_sorted)}
    package["_leveled_amount_by_bid"] = {b["id"]: leveled_amount(b) for b in compliant}
