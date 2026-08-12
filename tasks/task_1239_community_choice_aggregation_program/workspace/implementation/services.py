"""Shared business logic: lookups, cascades, calculations (PRD §3)."""

from datetime import datetime, timezone
from decimal import Decimal

from errors import ApiError, ERR_NOT_FOUND
from store import STORE
from util import D, ceil_to_tenth, dec, round_half_up_int, whole_days

NOTICE_COOLING_OFF_DAYS = 30
ENROLLMENT_LAG_DAYS = 30
RA_PLANNING_RESERVE_MARGIN = Decimal("0.15")
TERMINATION_FEE_PCT = Decimal("0.20")
BPS_DENOMINATOR = Decimal(10000)

TERMINAL_LOCKDOWN = {
    "BillingExtract": {"SETTLED"},
    "RemittanceFile": {"SETTLED"},
    "BadDebtPool": {"TRUED_UP"},
    "ComplianceFiling": {"ACCEPTED_BY_CPUC"},
}


def not_found(what="Resource"):
    raise ApiError(ERR_NOT_FOUND, 404, f"{what} not found")


def get_or_404(coll, rid, what="Resource"):
    rec = coll.get(rid)
    if rec is None:
        not_found(what)
    return rec


def adopted_default_product():
    for p in STORE.products.values():
        if p["election_key"] == "DEFAULT" and p["status"] == "ADOPTED":
            return p
    return None


def adopted_product_for_election(election_key):
    for p in STORE.products.values():
        if p["election_key"] == election_key and p["status"] == "ADOPTED":
            return p
    return None


def covering_adopted_schedule(product_id, instant):
    """ADOPTED schedule of product whose [period_start, period_end) covers instant."""
    covering = []
    for s in STORE.schedules.values():
        if (s["product_id"] == product_id and s["status"] == "ADOPTED"
                and s["_period_start"] <= instant < s["_period_end"]):
            covering.append(s)
    if not covering:
        return None
    covering.sort(key=lambda s: (s["_created_dt"], s["_seq"]))
    return covering[0]


def default_product_ok(instant):
    prod = adopted_default_product()
    if prod is None:
        return False
    return covering_adopted_schedule(prod["id"], instant) is not None


def compute_margin_bps(energy, incumbent):
    """round_half_up(10000 * (incumbent - energy) / incumbent)."""
    return round_half_up_int(BPS_DENOMINATOR * (dec(incumbent) - dec(energy)) / dec(incumbent))


def unreversed_opt_out(account_id, notice_id):
    """An unreversed OPT_OUT request exists for this account under this notice."""
    for r in STORE.opt_outs.values():
        if (r["service_account_id"] == account_id
                and r["enrollment_notice_id"] == notice_id
                and r["election_type"] == "OPT_OUT"
                and r["reversal_of_request_id"] is None):
            reversed_ = any(x["reversal_of_request_id"] == r["id"]
                            for x in STORE.opt_outs.values())
            if not reversed_:
                return True
    return False


def advance_epoch():
    """Epoch-advance ops checkpoint (PRD §2.4): notice enrollment sweeps and
    supply-contract delivery transitions whose time gates are met."""
    now = STORE.now()
    advanced_notices = 0
    flipped_accounts = 0
    advanced_contracts = 0

    notices = sorted(STORE.notices.values(), key=lambda n: (n["_created_dt"], n["_seq"]))
    for notice in notices:
        if notice["status"] != "CLOSED":
            continue
        if now < notice["_enrollment_effective_on"]:
            continue
        # CLOSED -> ENROLLING -> SETTLED within the same checkpoint
        notice["status"] = "ENROLLING"
        STORE.touch(notice)
        count = 0
        accounts = sorted(STORE.accounts.values(), key=lambda a: (a["_created_dt"], a["_seq"]))
        for acct in accounts:
            if (acct["current_enrollment_notice_id"] == notice["id"]
                    and acct["enrollment_state"] == "NOTICED"
                    and not unreversed_opt_out(acct["id"], notice["id"])):
                acct["enrollment_state"] = "ENROLLED"
                acct["product_election"] = "DEFAULT"
                acct["vintage_year"] = notice["_enrollment_effective_on"].year
                STORE.touch(acct)
                count += 1
        notice["account_count_enrolled"] = count
        notice["status"] = "SETTLED"
        STORE.touch(notice)
        advanced_notices += 1
        flipped_accounts += count
        # Cascade link: flipped accounts bubble up to refresh Authority.updated_at,
        # explicitly WITHOUT incrementing Authority.version.
        if count > 0:
            auth = STORE.authority()
            if auth is not None:
                STORE.refresh_only(auth)

    contracts = sorted(STORE.contracts.values(), key=lambda c: (c["_created_dt"], c["_seq"]))
    for c in contracts:
        moved = False
        if c["status"] == "EXECUTED" and now >= c["_delivery_start"]:
            c["status"] = "DELIVERING"
            STORE.touch(c)
            moved = True
        if c["status"] == "DELIVERING" and now >= c["_delivery_end"]:
            c["status"] = "CLOSED"
            STORE.touch(c)
            moved = True
        if moved:
            advanced_contracts += 1

    return advanced_notices, flipped_accounts, advanced_contracts


def account_open_balance(acct):
    return acct["cumulative_billed_cents"] - acct["cumulative_remitted_cents"]


def find_matching_extract(remittance_period):
    """The ACCEPTED (preferred) or SETTLED extract for the remittance period."""
    accepted = None
    settled = None
    for e in sorted(STORE.extracts.values(), key=lambda x: (x["_created_dt"], x["_seq"])):
        if e["billing_month"] != remittance_period:
            continue
        if e["status"] == "ACCEPTED" and accepted is None:
            accepted = e
        elif e["status"] == "SETTLED" and settled is None:
            settled = e
    return accepted if accepted is not None else settled


def waterfall_apply(rf, extract):
    """Remittance waterfall (PRD §3.7). Returns list of (account_id, cents) applied."""
    net = rf["net_remittance_cents"]
    account_ids = {l["service_account_id"] for l in STORE.lines.values()
                   if l["billing_extract_id"] == extract["id"]}
    eligible = []
    for aid in account_ids:
        acct = STORE.accounts.get(aid)
        if acct is None:
            continue
        if acct["enrollment_state"] not in ("ENROLLED", "OPTED_BACK_TO_BUNDLED"):
            continue
        if account_open_balance(acct) <= 0:
            continue
        eligible.append(acct)
    eligible.sort(key=lambda a: (a["_created_dt"], a["_updated_dt"], a["_seq"]))

    remaining = net
    applications = []
    for acct in eligible:
        if remaining <= 0:
            break
        bal = account_open_balance(acct)
        credit = min(bal, remaining)
        if credit > 0:
            acct["cumulative_remitted_cents"] += credit
            STORE.touch(acct)
            applications.append((acct["id"], credit))
            remaining -= credit

    # Overpayment remainder: credited to the rate-stabilization reserve.
    if remaining > 0:
        auth = STORE.authority()
        if auth is not None:
            auth["climate_reserve_balance_cents"] += remaining

    rf["applied_cents"] = net
    rf["_applications"] = applications
    return applications


def waterfall_reverse(rf):
    """Dispute compensation: reverse every account credit applied at reconcile."""
    for aid, credit in rf.get("_applications", []):
        acct = STORE.accounts.get(aid)
        if acct is not None:
            acct["cumulative_remitted_cents"] -= credit
            STORE.touch(acct)
    rf["_applications"] = []
    rf["applied_cents"] = 0


def contract_termination_fee(contract, now):
    """Pinned evaluation order: remaining_fraction -> remaining_mwh -> fee -> clamp."""
    total_window_days = whole_days(contract["_delivery_end"] - contract["_delivery_start"])
    remaining_days = whole_days(contract["_delivery_end"] - now)
    if total_window_days <= 0:
        return 0
    remaining_fraction = D(remaining_days) / D(total_window_days)
    remaining_mwh = dec(contract["total_mwh"]) * remaining_fraction
    fee_dollars = remaining_mwh * dec(contract["price_dollars_per_mwh"]) * TERMINATION_FEE_PCT
    return round_half_up_int(fee_dollars * 100)


def reserve_debit(amount_cents):
    """Debit the Authority reserve, clamped at zero; bumps Authority version."""
    auth = STORE.authority()
    if auth is None:
        return 0
    debit = min(amount_cents, auth["climate_reserve_balance_cents"])
    if debit < 0:
        debit = 0
    auth["climate_reserve_balance_cents"] -= debit
    STORE.touch(auth)
    return debit


def forecast_compute(variant, period_year):
    """load_forecast_snapshot calculation (PRD §3.5)."""
    in_scope = [a for a in STORE.accounts.values()
                if a["enrollment_state"] in ("NOTICED", "ENROLLED")]

    total_kwh = D(0)
    total_kw = D(0)
    for a in sorted(in_scope, key=lambda x: (x["_created_dt"], x["_seq"])):
        total_kw += dec(a["annual_peak_kw"])
        if variant == "ACTUAL_TRUED":
            settled_usage = D(0)
            months = set()
            for line in STORE.lines.values():
                if line["service_account_id"] != a["id"]:
                    continue
                ext = STORE.extracts.get(line["billing_extract_id"])
                if ext is None or ext["status"] != "SETTLED":
                    continue
                settled_usage += D(line["usage_kwh"])
                months.add(ext["billing_month"])
            if months:
                effective = settled_usage * D(12) / D(len(months))
            else:
                effective = dec(a["annual_kwh_estimate"])
        else:
            effective = dec(a["annual_kwh_estimate"])
        total_kwh += effective

    total_energy_mwh = (total_kwh / D(1000)).quantize(Decimal("0.001"), rounding="ROUND_HALF_UP")
    coincident_peak_mw = (total_kw / D(1000)).quantize(Decimal("0.001"), rounding="ROUND_HALF_UP")
    ra_requirement_mw = ceil_to_tenth(coincident_peak_mw * (D(1) + RA_PLANNING_RESERVE_MARGIN))

    year_start = datetime(period_year, 1, 1, tzinfo=timezone.utc)
    year_end = datetime(period_year + 1, 1, 1, tzinfo=timezone.utc)
    contracted = D(0)
    for c in STORE.contracts.values():
        if c["status"] not in ("EXECUTED", "DELIVERING"):
            continue
        if c["_delivery_start"] < year_end and c["_delivery_end"] > year_start:
            contracted += dec(c["total_mwh"])
    coverage_gap_mwh = round_half_up_int(total_energy_mwh) - contracted
    return total_energy_mwh, coincident_peak_mw, ra_requirement_mw, coverage_gap_mwh


def rps_attainment(filing, authority):
    """renewable_content_attainment calculation (PRD §3.9)."""
    retired_total = D(0)
    eligible_weighted = D(0)
    for r in STORE.recs.values():
        if r["compliance_filing_id"] != filing["id"]:
            continue
        retired_total += dec(r["retired_mwh"])
        contract = STORE.contracts.get(r["supply_contract_id"])
        pct = dec(contract["rps_eligible_pct"]) if contract is not None else D(0)
        eligible_weighted += dec(r["retired_mwh"]) * pct
    rps_eligible_mwh = min(retired_total, eligible_weighted)

    retail_kwh = D(0)
    for line in STORE.lines.values():
        ext = STORE.extracts.get(line["billing_extract_id"])
        if ext is None or ext["status"] != "SETTLED":
            continue
        if ext["billing_month"].split("-")[0] != str(filing["compliance_year"]):
            continue
        retail_kwh += D(line["usage_kwh"])
    retail_mwh = retail_kwh / D(1000)

    if retail_mwh == 0:
        rps_actual_pct = D(0).quantize(Decimal("0.0001"))
    else:
        rps_actual_pct = (rps_eligible_mwh / retail_mwh).quantize(
            Decimal("0.0001"), rounding="ROUND_HALF_UP")
    target = dec(authority["rps_target_pct"]) * retail_mwh if authority else D(0)
    shortfall = target - rps_eligible_mwh
    if shortfall <= 0:
        rps_shortfall_mwh = 0
    else:
        rps_shortfall_mwh = int(shortfall.to_integral_value(rounding="ROUND_CEILING"))
    return rps_actual_pct, rps_shortfall_mwh
