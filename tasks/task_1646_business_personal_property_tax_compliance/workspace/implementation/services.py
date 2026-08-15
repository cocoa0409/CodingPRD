"""Business logic: calculations (PRD §3), state-machine cascades, clock
sweeps (§2.5). All money math uses Decimal with ROUND_HALF_UP per §2.6."""

import math
from datetime import date, timedelta
from decimal import Decimal

from util import round_half_up_cents, touch, append_audit


# ---------------------------------------------------------------------------
# Constants (scaffold §1.3)
# ---------------------------------------------------------------------------

EXEMPTION_TAX_CAP_PCT = 50
VARIANCE_TOLERANCE_CENTS = 100
UPLIFT_PCT = 10
MAX_INSTALLMENTS = 4
INSTALLMENT_SPACING_DAYS = 30
DAYS_PER_PENALTY_MONTH = 30
EXEMPTION_CURE_DAYS = 90
HALF_YEAR_CUTOFF_MONTH = 7

CATEGORIES = {
    "MACHINERY", "FURNITURE", "COMPUTER", "VEHICLE", "INVENTORY",
    "LEASEHOLD_IMPROVEMENT",
}
EXEMPTION_TYPES = {"FREEPORT", "POLLUTION_CONTROL", "HISTORIC"}


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------

def base_deadline_date(jurisdiction, tax_year):
    mm, dd = jurisdiction["base_deadline_mmdd"].split("-")
    return date(int(tax_year), int(mm), int(dd))


def lien_date(tax_year):
    return date(int(tax_year), 1, 1)


def find_class_rule(store, jurisdiction_id, category):
    for rule in store.class_rules.values():
        if rule["jurisdiction_id"] == jurisdiction_id and rule["category"] == category:
            return rule
    return None


def rule_proposal(rule):
    return "TAXABLE" if rule["is_taxable"] else "NON_TAXABLE"


def latest_recorded_disposal(store, asset_id):
    """The asset's current RECORDED/RECONCILED disposal (at most one RECORDED
    at a time; RECONCILED records persist as the 'active' disposal for the
    asset's disposed state)."""
    best = None
    for d in store.disposals.values():
        if d["asset_id"] == asset_id and d["disposal_status"] in ("RECORDED", "RECONCILED"):
            if best is None or d["created_at"] > best["created_at"]:
                best = d
    return best


# ---------------------------------------------------------------------------
# Calculation: asset_depreciation (scaffold §1.3)
# ---------------------------------------------------------------------------

def compute_age(rule, asset, tax_year):
    if rule["depreciation_convention"] == "FULL_YEAR":
        age = tax_year - asset["acquisition_date"].year
    else:  # HALF_YEAR
        isd = asset["in_service_date"]
        age = tax_year - isd.year - (1 if (isd.month, isd.day) >= (HALF_YEAR_CUTOFF_MONTH, 1) else 0)
    return max(age, 0)


def percent_good_for(rule, age):
    vector = rule["percent_good_vector"]
    if age < len(vector):
        return vector[age]
    return rule["percent_good_floor_pct"]


def compute_line(store, rule, asset, tax_year):
    """Compute one rendition line for an asset. Returns the line dict."""
    age = compute_age(rule, asset, tax_year)
    pct_good = percent_good_for(rule, age)
    raw = Decimal(asset["acquisition_cost_cents"]) * Decimal(pct_good) / Decimal(100)
    assessed = round_half_up_cents(raw)

    # Inclusion rules, evaluated after rounding (priority order per scaffold):
    disposal = latest_recorded_disposal(store, asset["id"])
    exclusion = None
    included = True
    if (
        disposal is not None
        and disposal["disposal_date"] < lien_date(tax_year)
    ):
        included = False
        exclusion = "DISPOSED"
    elif assessed < rule["de_minimis_line_cents"]:
        included = False
        exclusion = "DEMINIMIS"
    else:
        classification = asset.get("taxable_classification")
        if classification is None:
            # UNCLASSIFIED assets use the rule proposal
            classification = rule_proposal(rule)
        if classification == "NON_TAXABLE":
            included = False
            exclusion = "NON_TAXABLE"

    return {
        "line_no": None,  # assigned during assembly
        "asset_id": asset["id"],
        "category": asset["category"],
        "acquisition_cost_cents": asset["acquisition_cost_cents"],
        "age_years": age,
        "percent_good_applied": pct_good,
        "assessed_value_cents": assessed,
        "taxable_classification": asset.get("taxable_classification"),
        "included": included,
        "exclusion_reason": exclusion,
    }


def recompute_rendition_total(rendition):
    """rendition_total_aggregation: per-line rounding already applied; sum
    included lines only."""
    total = sum(
        line["assessed_value_cents"] for line in rendition["lines"] if line["included"]
    )
    rendition["total_assessed_value_cents"] = total


def generate_rendition_lines(store, rendition):
    """Rebuild lines from scratch. Caller has verified state and class-rule
    coverage."""
    from errors import ERR_CLASS_RULE_MISSING, raise_err

    in_scope = [
        a
        for a in store.assets.values()
        if a["client_id"] == rendition["client_id"]
        and a["jurisdiction_id"] == rendition["jurisdiction_id"]
        and a["acquisition_date"] < lien_date(rendition["tax_year"])
    ]
    # Coverage check: a class rule must cover every in-scope asset's category
    for a in in_scope:
        if find_class_rule(store, a["jurisdiction_id"], a["category"]) is None:
            raise_err(
                ERR_CLASS_RULE_MISSING,
                f"No class rule for ({a['jurisdiction_id']}, {a['category']})",
            )
    in_scope.sort(key=lambda a: (a["acquisition_date"], a["created_at"]))
    lines = []
    for idx, a in enumerate(in_scope, start=1):
        rule = find_class_rule(store, a["jurisdiction_id"], a["category"])
        line = compute_line(store, rule, a, rendition["tax_year"])
        line["line_no"] = idx
        lines.append(line)
    rendition["lines"] = lines
    recompute_rendition_total(rendition)
    touch(rendition)


def reclassify_line_refresh(store, asset):
    """Re-classification side effect: recompute the asset's line on any
    DRAFT/AMENDMENT_OPEN rendition of the same jurisdiction whose lien-date
    scope includes the asset."""
    for r in store.renditions.values():
        if r["rendition_status"] not in ("DRAFT", "AMENDMENT_OPEN"):
            continue
        if r["jurisdiction_id"] != asset["jurisdiction_id"]:
            continue
        if r["client_id"] != asset["client_id"]:
            continue
        if not (asset["acquisition_date"] < lien_date(r["tax_year"])):
            continue
        # regenerate lines wholesale (keeps numbering/sorting deterministic)
        generate_rendition_lines(store, r)


# ---------------------------------------------------------------------------
# Calculation: late_filing_penalty (scaffold §1.3)
# ---------------------------------------------------------------------------

def compute_lateness(store, rendition, filed_date):
    jurisdiction = store.jurisdictions[rendition["jurisdiction_id"]]
    deadline = rendition["deadline_date"]
    late_days = max(0, (filed_date - deadline).days)
    penalty_months = math.ceil(late_days / DAYS_PER_PENALTY_MONTH) if late_days > 0 else 0
    penalty_pct = min(
        penalty_months * jurisdiction["late_penalty_pct_per_month"],
        jurisdiction["max_late_penalty_pct"],
    )
    if jurisdiction["penalty_base"] == "VALUE_BASE":
        base = Decimal(rendition["total_assessed_value_cents"])
    else:  # TAX_BASE — nested rounding of the tax base before the penalty pct
        base = Decimal(
            round_half_up_cents(
                Decimal(rendition["total_assessed_value_cents"])
                * Decimal(str(jurisdiction["tax_rate"]))
            )
        )
    penalty = round_half_up_cents(base * Decimal(penalty_pct) / Decimal(100))
    rendition["late_days"] = late_days
    rendition["late_penalty_months"] = penalty_months
    rendition["late_penalty_cents"] = penalty
    rendition["is_late_filing"] = late_days > 0


# ---------------------------------------------------------------------------
# Calculation: tax_bill_validation (scaffold §1.3)
# ---------------------------------------------------------------------------

def _line_share(v_cents, line, rendition):
    total = rendition["total_assessed_value_cents"]
    if total <= 0:
        return 0
    return round_half_up_cents(
        Decimal(v_cents) * Decimal(line["assessed_value_cents"]) / Decimal(total)
    )


def run_bill_validation(store, bill):
    """Runs the pinned four-step computation. Mutates the bill's computed
    fields and validation_status. Returns nothing."""
    notice = store.notices[bill["notice_id"]]
    rendition = store.renditions[notice["rendition_id"]]
    jurisdiction = store.jurisdictions[rendition["jurisdiction_id"]]
    tax_rate = Decimal(str(bill["tax_rate"]))

    if notice["notice_status"] == "FINALIZED":
        v = notice["final_value_cents"]
    else:
        v = notice["notice_value_cents"]

    # Step 1: gross tax
    gross = round_half_up_cents(Decimal(v) * tax_rate)

    # Lines from the rendition's current (last-filed) lines
    lines_by_asset = {l["asset_id"]: l for l in rendition["lines"]}

    # Step 2: exemption credit
    lien = lien_date(rendition["tax_year"])
    qualifying_exemptions = []
    for e in store.exemptions.values():
        if e["application_status"] != "APPROVED":
            continue
        asset = store.assets.get(e["asset_id"])
        if asset is None:
            continue
        if e["asset_id"] not in lines_by_asset:
            continue
        if asset["client_id"] != rendition["client_id"]:
            continue
        # half-open interval [effective_date, expiration_date) contains lien date
        if e["effective_date"] <= lien < e["expiration_date"]:
            qualifying_exemptions.append(e)
    exemption_credit = 0
    if qualifying_exemptions:
        # largest exemption_pct wins; tie-break earliest created_at
        qualifying_exemptions.sort(key=lambda e: (-e["exemption_pct"], e["created_at"]))
        chosen = qualifying_exemptions[0]
        line = lines_by_asset[chosen["asset_id"]]
        v_line = _line_share(v, line, rendition)
        credit_a = round_half_up_cents(
            Decimal(round_half_up_cents(Decimal(v_line) * Decimal(chosen["exemption_pct"]) / Decimal(100)))
            * tax_rate
        )
        credit_cap = round_half_up_cents(Decimal(gross) * Decimal(EXEMPTION_TAX_CAP_PCT) / Decimal(100))
        exemption_credit = min(credit_a, credit_cap)

    # Step 3: abatement credit
    abatement_credit = 0
    for a in store.abatements.values():
        if a["agreement_status"] not in ("ACTIVE", "RECERTIFICATION_DUE"):
            continue
        if a["asset_id"] not in lines_by_asset:
            continue
        asset = store.assets.get(a["asset_id"])
        if asset is None or asset["client_id"] != rendition["client_id"]:
            continue
        if a["first_tax_year"] <= rendition["tax_year"] <= a["last_tax_year"]:
            line = lines_by_asset[a["asset_id"]]
            v_line = _line_share(v, line, rendition)
            credit_a = round_half_up_cents(
                Decimal(round_half_up_cents(Decimal(v_line) * Decimal(a["abatement_pct"]) / Decimal(100)))
                * tax_rate
            )
            abatement_credit = min(credit_a, gross - exemption_credit)
            break  # overlap rules guarantee uniqueness

    # Step 4: late component
    late = 0
    if (
        jurisdiction["penalty_base"] == "VALUE_BASE"
        and bill["due_date"] > rendition["deadline_date"]
    ):
        late = rendition["late_penalty_cents"]

    validated = gross - exemption_credit - abatement_credit + late
    bill["validated_amount_cents"] = validated
    bill["variance_cents"] = bill["billed_amount_cents"] - validated
    bill["validation_status"] = (
        "MATCHED" if abs(bill["variance_cents"]) <= VARIANCE_TOLERANCE_CENTS else "DISCREPANCY"
    )


def recompute_payment_status(bill):
    """payment_status derivation, pinned order (scaffold §1.2 note)."""
    paid_sum = sum(i["amount_cents"] for i in bill["installments"] if i["installment_status"] == "PAID")
    active = [i for i in bill["installments"] if i["installment_status"] in ("SCHEDULED", "LATE")]
    any_late = any(i["installment_status"] == "LATE" for i in bill["installments"])
    unscheduled = bill.get("unscheduled_amount_cents")

    if paid_sum == 0 and not active:
        status = "UNSCHEDULED"
    elif not active and (unscheduled or 0) == 0:
        status = "PAID"
    elif not active and (unscheduled or 0) > 0:
        status = "PARTIALLY_PAID"
    elif any_late:
        status = "DELINQUENT"
    elif paid_sum > 0:
        status = "PARTIALLY_PAID"
    else:
        status = "SCHEDULED"
    bill["payment_status"] = status


def revalidate_bill_cascade(store, bill, actor_id="system"):
    """Notice-finalization / abatement-termination cascade: revalidate a
    non-PENDING bill, cancel SCHEDULED/LATE installments, recompute
    unscheduled + payment_status, append BILL_REVALIDATED."""
    run_bill_validation(store, bill)
    for inst in bill["installments"]:
        if inst["installment_status"] in ("SCHEDULED", "LATE"):
            inst["installment_status"] = "CANCELLED"
    paid_sum = sum(i["amount_cents"] for i in bill["installments"] if i["installment_status"] == "PAID")
    bill["unscheduled_amount_cents"] = bill["validated_amount_cents"] - paid_sum
    recompute_payment_status(bill)
    touch(bill)
    notice = store.notices[bill["notice_id"]]
    rendition = store.renditions[notice["rendition_id"]]
    append_audit(
        store,
        rendition["client_id"],
        "BILL_REVALIDATED",
        f"Tax bill {bill['id']} revalidated",
        actor_id,
    )


# ---------------------------------------------------------------------------
# Calculation: accrual_forecast (scaffold §1.3)
# ---------------------------------------------------------------------------

def compute_forecast(store, client_id, tax_year, variant):
    """Returns (liability_cents, component_count, covered_rendition_ids)."""
    in_scope = [
        r
        for r in store.renditions.values()
        if r["client_id"] == client_id
        and r["tax_year"] == tax_year
        and r["rendition_status"] in ("FILED", "AMENDMENT_OPEN", "ACCEPTED")
    ]
    liability = 0
    for r in in_scope:
        jurisdiction = store.jurisdictions[r["jurisdiction_id"]]
        rate = Decimal(str(jurisdiction["tax_rate"]))
        if variant == "NOTICE_BASED":
            notices = [
                n for n in store.notices.values() if n["rendition_id"] == r["id"]
            ]
            if not notices:
                continue  # renditions without any notice contribute nothing
            notices.sort(key=lambda n: n["created_at"])
            latest = notices[-1]
            value = (
                latest["final_value_cents"]
                if latest["notice_status"] == "FINALIZED"
                else latest["notice_value_cents"]
            )
            liability += round_half_up_cents(Decimal(value) * rate)
        else:  # RENDERED_CONSERVATIVE
            value = r["total_assessed_value_cents"]
            uplifted = round_half_up_cents(
                Decimal(value) * Decimal(100 + UPLIFT_PCT) / Decimal(100)
            )
            liability += round_half_up_cents(Decimal(uplifted) * rate)
    return liability, len(in_scope), {r["id"] for r in in_scope}


# ---------------------------------------------------------------------------
# Staleness flagging helper
# ---------------------------------------------------------------------------

def flag_forecasts(store, client_id, tax_years, actor_id="system"):
    """Flag every PUBLISHED forecast for the client whose tax_year is in
    tax_years with needs_regeneration=true and a version bump; each flagging
    appends FORECAST_STALENESS_FLAGGED."""
    for f in store.forecasts.values():
        if (
            f["client_id"] == client_id
            and f["forecast_status"] == "PUBLISHED"
            and f["tax_year"] in tax_years
            and not f["needs_regeneration"]
        ):
            f["needs_regeneration"] = True
            touch(f)
            append_audit(
                store,
                client_id,
                "FORECAST_STALENESS_FLAGGED",
                f"Accrual forecast {f['id']} flagged for regeneration",
                actor_id,
            )


def flag_forecasts_force(store, client_id, tax_years, actor_id="system"):
    """Variant that flags even already-flagged forecasts (version bump + event
    each time the underlying data changes)."""
    for f in store.forecasts.values():
        if (
            f["client_id"] == client_id
            and f["forecast_status"] == "PUBLISHED"
            and f["tax_year"] in tax_years
        ):
            f["needs_regeneration"] = True
            touch(f)
            append_audit(
                store,
                client_id,
                "FORECAST_STALENESS_FLAGGED",
                f"Accrual forecast {f['id']} flagged for regeneration",
                actor_id,
            )


def flag_forecasts_uncovered(store, client_id, tax_year, rendition_id, actor_id="system"):
    """DRAFT->FILED flagging: only PUBLISHED forecasts for (client, tax_year)
    whose publish-time input set did NOT already cover this rendition."""
    for f in store.forecasts.values():
        if (
            f["client_id"] == client_id
            and f["forecast_status"] == "PUBLISHED"
            and f["tax_year"] == tax_year
            and rendition_id not in (f.get("_covered_rendition_ids") or set())
        ):
            f["needs_regeneration"] = True
            touch(f)
            append_audit(
                store,
                client_id,
                "FORECAST_STALENESS_FLAGGED",
                f"Accrual forecast {f['id']} flagged for regeneration",
                actor_id,
            )


# ---------------------------------------------------------------------------
# Notice finalization cascade (PRD §3.5 fork-join)
# ---------------------------------------------------------------------------

def finalize_notice(store, notice, final_value, actor_id="system"):
    notice["notice_status"] = "FINALIZED"
    notice["final_value_cents"] = final_value
    touch(notice)

    rendition = store.renditions[notice["rendition_id"]]
    if rendition["rendition_status"] == "FILED":
        rendition["rendition_status"] = "ACCEPTED"
        touch(rendition)

    # Revalidate every non-PENDING bill of this notice
    for bill in store.bills.values():
        if bill["notice_id"] == notice["id"] and bill["validation_status"] != "PENDING":
            revalidate_bill_cascade(store, bill, actor_id)

    # Flag published forecasts for client + tax year
    flag_forecasts(store, rendition["client_id"], {rendition["tax_year"]}, actor_id)

    append_audit(
        store,
        rendition["client_id"],
        "NOTICE_FINALIZED",
        f"Assessment notice {notice['id']} finalized",
        actor_id,
    )


# ---------------------------------------------------------------------------
# Clock sweeps (PRD §2.5, pinned order)
# ---------------------------------------------------------------------------

def run_clock_sweeps(store):
    today = store.clock_date()

    # (1) extensions EXPIRED
    for ext in store.extensions.values():
        if ext["extension_status"] != "GRANTED":
            continue
        rendition = store.renditions[ext["rendition_id"]]
        if today > ext["requested_extend_to_date"] and rendition["rendition_status"] == "DRAFT":
            ext["extension_status"] = "EXPIRED"
            touch(ext)

    # (2) notices past protest deadline FINALIZED
    for notice in list(store.notices.values()):
        if notice["notice_status"] in ("RECEIVED", "ACCEPTED") and today > notice["protest_deadline_date"]:
            finalize_notice(store, notice, notice["notice_value_cents"], actor_id="system")

    # (3) installments -> LATE; bill payment_status recomputed
    for bill in store.bills.values():
        changed = False
        for inst in bill["installments"]:
            if inst["installment_status"] == "SCHEDULED" and inst["due_date"] < today:
                inst["installment_status"] = "LATE"
                changed = True
                notice = store.notices[bill["notice_id"]]
                rendition = store.renditions[notice["rendition_id"]]
                append_audit(
                    store,
                    rendition["client_id"],
                    "INSTALLMENT_LATE",
                    f"Installment {inst['installment_no']} of bill {bill['id']} is late",
                    "system",
                )
        if changed:
            recompute_payment_status(bill)
            touch(bill)

    # (4) abatements -> RECERTIFICATION_DUE
    for ag in store.abatements.values():
        if ag["agreement_status"] != "ACTIVE":
            continue
        next_year = ag["last_recertified_year"] + 1
        if today >= date(next_year, 1, 1) and next_year <= ag["last_tax_year"]:
            ag["agreement_status"] = "RECERTIFICATION_DUE"
            touch(ag)

    # (5) SUSPENDED exemptions -> REVOKED past the 90-day cure period
    for e in store.exemptions.values():
        if e["application_status"] != "SUSPENDED":
            continue
        if e["suspended_date"] is not None and today > e["suspended_date"] + timedelta(days=EXEMPTION_CURE_DAYS):
            e["application_status"] = "REVOKED"
            touch(e)
            asset = store.assets.get(e["asset_id"])
            if asset is not None:
                append_audit(
                    store,
                    asset["client_id"],
                    "EXEMPTION_REVOKED",
                    f"Exemption application {e['id']} revoked",
                    "system",
                )
