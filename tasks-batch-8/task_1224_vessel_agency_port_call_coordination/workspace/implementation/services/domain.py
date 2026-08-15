"""Cross-aggregate domain logic: calculations, DA totals, mirrors, gates."""
from decimal import Decimal

import db
from errors import raise_err
from utils import dec, rhu_cents, round_pct_2dp, days_between, touch, new_entity

AGENCY_FEE_PCT = Decimal("0.025")
ADVANCE_PCT = Decimal("0.80")
LATE_CANCEL_PCT = Decimal("0.25")
VARIANCE_TOLERANCE = Decimal("10.0")

SO_KIND_TO_LINE_CATEGORY = {
    "PILOT": "PILOTAGE",
    "TUG": "TOWAGE",
    "LINEBOAT": "BERTH_HIRE",
    "LAUNCH": "CREW_COSTS",
}

DA_EDITABLE_STATUSES = {"PRO_FORMA", "SENT_TO_PRINCIPAL", "FUNDED"}
DA_FINALIZED_STATUSES = {"FINAL", "DISPUTED", "SETTLED"}
AUTHORITY_TYPES = {"PORT_STATE_CONTROL", "IMMIGRATION", "CUSTOMS", "HARBOR_MASTER"}


# ---------------------------------------------------------------- lookups
def get(store, entity_id):
    return db.STORES[store].get(entity_id)


def all_of(store):
    return db.STORES[store].values()


def current_da_for_call(port_call_id):
    """The at-most-one non-SUPERSEDED disbursement account of a call."""
    for da in all_of("disbursement_accounts"):
        if da["port_call_id"] == port_call_id and da["status"] != "SUPERSEDED":
            return da
    return None


def lines_of_da(da_id):
    return [l for l in all_of("da_lines") if l["da_id"] == da_id]


def advances_of_da(da_id):
    return [a for a in all_of("funding_advances") if a["da_id"] == da_id]


def mirror_line(da_id, source_ref):
    for line in all_of("da_lines"):
        if line["da_id"] == da_id and line.get("source_ref") == source_ref:
            return line
    return None


def published_tariff(port_code, component):
    for t in all_of("tariffs"):
        if (t["port_code"] == port_code and t["component"] == component
                and t["status"] == "PUBLISHED"):
            return t
    return None


def require_call_editable(call):
    if call["ops_status"] in ("CANCELLED", "CLOSED"):
        raise_err("ERR_PORT_CALL_NOT_EDITABLE",
                  "The parent port call is %s and no longer editable" % call["ops_status"])


# ---------------------------------------------------------------- lazy crew expiry
def lazy_expire_crew(crew):
    """SHORE_PASS_ISSUED flips to PASS_EXPIRED once the clock passes expiry."""
    if (crew["status"] == "SHORE_PASS_ISSUED"
            and crew.get("shore_pass_expires_at") is not None
            and db.now() > crew["shore_pass_expires_at"]):
        crew["status"] = "PASS_EXPIRED"
        touch(crew)


def lazy_expire_all_crew():
    for crew in all_of("crew_changes"):
        lazy_expire_crew(crew)


# ---------------------------------------------------------------- port dues
def port_dues_amount(tariff, vessel_gt, days, night, hazmat):
    """Tiered marginal pricing; one half-up rounding at the very end."""
    base = Decimal("0")
    prev = 0
    for tier in tariff["gt_tiers"]:
        upper = tier.get("gt_up_to")
        bound = upper if upper is not None else None
        covered = vessel_gt if bound is None else min(vessel_gt, bound)
        billable = covered - prev
        if billable > 0:
            base += dec(billable) * dec(tier["rate_cents"])
        if bound is None or vessel_gt <= bound:
            break
        prev = bound
    base_total = base * days
    amount = base_total
    if night:
        amount += base_total * dec(tariff["night_surcharge_pct"])
    if hazmat:
        amount += base_total * dec(tariff["hazmat_surcharge_pct"])
    return rhu_cents(amount)


def is_night(dt):
    return dt.hour >= 18 or dt.hour < 6


def port_dues_estimate(tariff, call):
    days = call["alongside_days_estimated"]
    return port_dues_amount(tariff, call["vessel_gt"], days,
                            is_night(call["eta"]), call["hazmat_flag"])


def port_dues_final(tariff, call):
    days = call["alongside_days_actual"] or 1
    return port_dues_amount(tariff, call["vessel_gt"], days,
                            is_night(call["actual_arrival_at"]), call["hazmat_flag"])


def seed_port_dues_line(da, call):
    """Seed the TARIFF PORT_DUES estimate line if a tariff is published."""
    tariff = published_tariff(call["port_code"], "PORT_DUES")
    if tariff is None:
        return None
    amount = port_dues_estimate(tariff, call)
    line = new_entity("da_lines", {
        "da_id": da["id"],
        "category": "PORT_DUES",
        "description": "Port dues per published tariff",
        "estimated_cents": amount,
        "actual_cents": None,
        "status": "ESTIMATED",
        "source_type": "TARIFF",
        "source_ref": None,
        "tariff_id": tariff["id"],
    })
    return line


# ---------------------------------------------------------------- agency fee / totals
def agency_fee_estimated(lines):
    """2.5% per line, each rounded half-up to integer cents, then summed."""
    total = 0
    for line in lines:
        total += rhu_cents(dec(line["estimated_cents"] or 0) * AGENCY_FEE_PCT)
    return total


def agency_fee_final(lines):
    total = 0
    for line in lines:
        total += rhu_cents(dec(line["actual_cents"] or 0) * AGENCY_FEE_PCT)
    return total


def recompute_da_totals(da, bump=True):
    """da_totals_calc: lines -> per-line fee -> advance requirement; funding."""
    lines = lines_of_da(da["id"])
    da["agency_fee_estimated_cents"] = agency_fee_estimated(lines)
    da["total_estimated_cents"] = (
        sum(l["estimated_cents"] or 0 for l in lines) + da["agency_fee_estimated_cents"]
    )
    da["advance_required_cents"] = rhu_cents(ADVANCE_PCT * dec(da["total_estimated_cents"]))
    advs = advances_of_da(da["id"])
    # Cumulative receipts: a REFUNDED advance was still received (its amount then
    # nets out via advances_refunded_cents), keeping funding_available >= 0 (§2.11)
    # and the auto-FUNDED gate of §3.8 coherent across create/refund cycles.
    da["advances_received_cents"] = sum(
        a["amount_cents"] for a in advs if a["status"] in ("RECEIVED", "APPLIED", "REFUNDED"))
    da["advances_applied_cents"] = sum(a["applied_cents"] for a in advs)
    da["advances_refunded_cents"] = sum(a["refunded_cents"] for a in advs)
    da["funding_available_cents"] = (da["advances_received_cents"]
                                     - da["advances_applied_cents"]
                                     - da["advances_refunded_cents"])
    if da["status"] in DA_FINALIZED_STATUSES and da["total_final_cents"] is not None:
        recompute_da_final(da, lines=lines)
    refresh_funding_posture(da)
    if bump:
        touch(da)


def recompute_da_final(da, lines=None):
    if lines is None:
        lines = lines_of_da(da["id"])
    da["agency_fee_final_cents"] = agency_fee_final(lines)
    da["total_final_cents"] = (
        sum(l["actual_cents"] or 0 for l in lines) + da["agency_fee_final_cents"]
    )
    da["balance_due_cents"] = da["total_final_cents"] - da["advances_applied_cents"]


def refresh_funding_posture(da):
    """Automatic SENT_TO_PRINCIPAL <-> FUNDED toggle on the funding gate."""
    net = da["advances_received_cents"] - da["advances_refunded_cents"]
    if da["status"] == "SENT_TO_PRINCIPAL" and net >= da["advance_required_cents"]:
        da["status"] = "FUNDED"
    elif da["status"] == "FUNDED" and net < da["advance_required_cents"]:
        da["status"] = "SENT_TO_PRINCIPAL"


# ---------------------------------------------------------------- variance
def po_variance_pct(estimated_cents, invoiced_cents):
    if estimated_cents == 0:
        return 0.0 if invoiced_cents == 0 else 999.99
    pct = (dec(invoiced_cents) - dec(estimated_cents)) / dec(estimated_cents) * 100
    return round_pct_2dp(pct)


def within_tolerance(variance_pct):
    return abs(dec(variance_pct)) <= VARIANCE_TOLERANCE


# ---------------------------------------------------------------- exposure
def principal_exposure(principal_id):
    forward = 0
    cash = 0
    for da in all_of("disbursement_accounts"):
        if da["status"] == "SUPERSEDED":
            continue
        call = get("port_calls", da["port_call_id"])
        if call is None or call["principal_id"] != principal_id:
            continue
        if call["ops_status"] in ("CLOSED", "CANCELLED"):
            continue
        if da["status"] in ("FINAL", "DISPUTED", "SETTLED"):
            forward += da["total_final_cents"] or 0
            cash += da["advances_applied_cents"] + max(
                0, (da["total_final_cents"] or 0) - da["advances_applied_cents"])
        else:
            forward += da["total_estimated_cents"] or 0
            cash += da["advances_applied_cents"]
    return forward, cash
