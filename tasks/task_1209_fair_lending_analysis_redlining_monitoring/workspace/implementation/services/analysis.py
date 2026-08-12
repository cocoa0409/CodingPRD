"""Analysis-run scope, staleness, denial impact ratio, pricing disparity."""
from decimal import Decimal, ROUND_HALF_UP

import db
from services.officer import D, PROTECTED, q

NET_OUTCOMES = ("ORIGINATED", "DENIED")
RAW_OUTCOMES = ("ORIGINATED", "DENIED", "WITHDRAWN", "APPROVED_NOT_ACCEPTED")


def in_scope(run, app):
    """snapshot_scope_membership: market + product + half-open decision period,
    status != EXCLUDED. Membership uses decision_date only."""
    return (
        app["market_id"] == run["market_id"]
        and app["product_type"] == run["product_type"]
        and run["period_start"] <= app["decision_date"] < run["period_end"]
        and app["status"] != "EXCLUDED"
    )


def dataset_stale(run):
    """True when an in-scope application (VALIDATED or corrected out of it)
    has updated_at strictly later than locked_at (millisecond precision)."""
    locked_at = run.get("locked_at")
    if not locked_at:
        return False
    for app in db.STORES["applications"].values():
        if (
            app["market_id"] == run["market_id"]
            and app["product_type"] == run["product_type"]
            and run["period_start"] <= app["decision_date"] < run["period_end"]
            and app["status"] in ("VALIDATED", "RECEIVED")
            and app["updated_at"] > locked_at
        ):
            return True
    return False


def app_frozen(app_id):
    """Frozen into a FINALIZED/ARCHIVED run snapshot."""
    for run in db.STORES["runs"].values():
        if run["status"] in ("FINALIZED", "ARCHIVED") and app_id in run.get(
            "_snapshot_ids", []
        ):
            return True
    return False


def _rate(rows, denom_outcomes):
    denom = [a for a in rows if a["outcome"] in denom_outcomes]
    if not denom:
        return None
    num = len([a for a in denom if a["outcome"] == "ORIGINATED"])
    return D(num) / D(len(denom))


def _ratio(protected_rate, control_rate):
    """Ratio of exact cohort rates, rounded half-up to 4dp, zero-control rule."""
    if protected_rate is None or control_rate is None:
        return None
    if control_rate == 0:
        return Decimal("1.0000") if protected_rate == 0 else Decimal("0.0000")
    return (protected_rate / control_rate).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def compute_run(run):
    """DATA_LOCKED -> COMPUTED. Caller has already verified staleness.

    Writes both denial-impact variants, both pricing-disparity variants,
    classification, screening flag, and auto-creates findings on breach.
    """
    snap = [
        db.STORES["applications"][i]
        for i in run["_snapshot_ids"]
        if i in db.STORES["applications"]
    ]
    rows = [a for a in snap if a["status"] == "VALIDATED"]
    control = [a for a in rows if a["applicant_group"] == "CONTROL"]
    protected = [a for a in rows if a["applicant_group"] in PROTECTED]

    rc_net = _rate(control, NET_OUTCOMES)
    rp_net = _rate(protected, NET_OUTCOMES)
    rc_raw = _rate(control, RAW_OUTCOMES)
    rp_raw = _rate(protected, RAW_OUTCOMES)

    ratio_net = _ratio(rp_net, rc_net)
    ratio_raw = _ratio(rp_raw, rc_raw)

    if ratio_net is None:
        classification = "NONE"
    elif ratio_net >= Decimal("0.90"):
        classification = "NONE"
    elif ratio_net >= Decimal("0.80"):
        classification = "MARGINAL"
    else:
        classification = "ADVERSE"

    if ratio_net is None or ratio_raw is None:
        screening_flag = False
    else:
        screening_flag = min(ratio_net, ratio_raw) < Decimal("0.80")

    # Pricing disparity over ORIGINATED snapshot rows.
    originated = [a for a in rows if a["outcome"] == "ORIGINATED"]
    o_prot = [a for a in originated if a["applicant_group"] in PROTECTED]
    o_ctrl = [a for a in originated if a["applicant_group"] == "CONTROL"]

    def mean_bps(apps):
        return D(sum(a["note_rate_bps"] for a in apps)) / D(len(apps))

    if not o_prot or not o_ctrl:
        unadjusted = None
        adjusted = None
    else:
        unadjusted = (mean_bps(o_prot) - mean_bps(o_ctrl)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        o_prot_adj = [a for a in o_prot if a["has_exception"] != "APPROVED"]
        o_ctrl_adj = [a for a in o_ctrl if a["has_exception"] != "APPROVED"]
        if not o_prot_adj or not o_ctrl_adj:
            adjusted = None
        else:
            adjusted = (mean_bps(o_prot_adj) - mean_bps(o_ctrl_adj)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )

    run["approval_rate_protected_net"] = None if rp_net is None else q(rp_net, 4)
    run["approval_rate_control_net"] = None if rc_net is None else q(rc_net, 4)
    run["impact_ratio_net"] = None if ratio_net is None else float(ratio_net)
    run["impact_ratio_raw"] = None if ratio_raw is None else float(ratio_raw)
    run["pricing_disparity_unadjusted_bps"] = (
        None if unadjusted is None else float(unadjusted)
    )
    run["pricing_disparity_adjusted_bps"] = None if adjusted is None else float(adjusted)
    run["adverse_classification"] = classification
    run["screening_flag"] = bool(screening_flag)
    run["status"] = "COMPUTED"
    db.touch(run)

    # Auto-findings on threshold breach.
    if screening_flag:
        _auto_finding(run, "DENIAL_DISPARITY", float(ratio_raw), 0.80)
    if unadjusted is not None and unadjusted > Decimal("15"):
        _auto_finding(run, "PRICING_DISPARITY", float(unadjusted), 15)


def _auto_finding(run, kind, metric_value, threshold_value):
    finding = db.new_record(
        {
            "analysis_run_id": run["id"],
            "kind": kind,
            "source": "AUTO",
            "metric_value": metric_value,
            "threshold_value": threshold_value,
            "notes": None,
            "status": "FLAGGED",
            "harmed_application_ids": [],
            "created_by_user_id": "system",
            "substantiated_by_user_id": None,
            "refute_reason": None,
            "reopen_count": 0,
            "superseded_by_finding_id": None,
        }
    )
    db.STORES["findings"][finding["id"]] = finding
    run["open_finding_count"] += 1
    db.touch(run)
    return finding
