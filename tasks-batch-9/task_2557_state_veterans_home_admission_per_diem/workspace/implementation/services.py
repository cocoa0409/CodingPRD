"""Cross-record workflows: queue recomputation, the certification and
occupancy cascades, cost-share computation, claim attribution/pricing and the
nightly operations checkpoint."""
from datetime import timedelta

import calc
from calc import (
    BED_HOLD_MAX_DAYS,
    BED_HOLD_PAYABLE_DAYS_PER_MONTH,
    BED_HOLD_RATE_BPS,
    CARE_PLAN_REVIEW_DAYS,
    COST_SHARE_TIER_BOUNDS_CENTS,
    COST_SHARE_TIER_BPS,
    FEDERAL_OFFSET_CAP_BPS,
    FEDERAL_OFFSET_SHARE_BPS,
    MAX_DECLINED_OFFERS,
    MEDICAL_CAP_BY_TIER_CENTS,
    OFFER_WINDOW_DAYS,
    PER_DIEM_RATE_CENTS,
    apply_bps,
    round_half_up,
)
from store import (
    clock_date,
    date_in_month,
    days_in_month,
    format_date,
    format_datetime,
    month_bounds,
    month_of_date,
    new_record,
    now_iso,
    order_key,
    parse_date,
    store,
    touch,
    touch_once,
)

TERMINAL_QUEUE_STATUSES = ("ADMITTED", "EXPIRED", "CANCELLED")


# ------------------------------------------------------ waitlist / queue ----
def unit_entries(unit_id):
    return [w for w in store.waitlist_entries.values() if w["care_unit_id"] == unit_id]


def applicant_entries(applicant_id):
    return [w for w in store.waitlist_entries.values() if w["applicant_id"] == applicant_id]


def recompute_queue(unit_id):
    """waitlist_queue_order: rank ACTIVE/OFFERED entries, zero the rest."""
    entries = unit_entries(unit_id)
    candidates = []
    for entry in entries:
        if entry["status"] in ("ACTIVE", "OFFERED"):
            candidates.append(entry)
        else:
            entry["queue_position"] = 0
    for entry in candidates:
        applicant = store.applicants.get(entry["applicant_id"])
        if applicant:
            entry["priority_class_snapshot"] = applicant["priority_class"]
            entry["rank_score_snapshot"] = applicant["priority_score"]

    def sort_key(entry):
        applicant = store.applicants.get(entry["applicant_id"]) or {}
        return (
            -(applicant.get("priority_score") or 0),
            applicant.get("application_received_date") or "",
            entry["created_at"],
            entry["_seq"],
        )

    candidates.sort(key=sort_key)
    for index, entry in enumerate(candidates, start=1):
        entry["queue_position"] = index
    return candidates


def recompute_applicant_score(applicant, bump=True):
    if applicant["priority_class"] is not None:
        applicant["priority_class"] = calc.compute_priority_class(applicant)
    applicant["priority_score"] = calc.compute_priority_score(applicant)
    if bump:
        touch_once(applicant)
    for entry in applicant_entries(applicant["id"]):
        if entry["status"] in ("ACTIVE", "OFFERED"):
            recompute_queue(entry["care_unit_id"])
            unit = store.care_units.get(entry["care_unit_id"])
            if unit and bump:
                touch_once(unit)


# --------------------------------------------------- certification chains ----
def void_draft_claims(home):
    """Hop 4 of the decertification cascade: void DRAFT claims, release days."""
    for claim in sorted(store.claims.values(), key=order_key):
        if claim["veterans_home_id"] != home["id"] or claim["status"] != "DRAFT":
            continue
        claim["status"] = "VOID"
        touch(claim)
        release_days(claim)


def release_days(claim):
    for day in store.census_days.values():
        if day["per_diem_claim_id"] == claim["id"]:
            day["per_diem_claim_id"] = None


def decertification_cascade(unit):
    """Hops 2-4; hop 1 (status/score/date + unit version) is done by the caller."""
    for entry in sorted(unit_entries(unit["id"]), key=order_key):
        if entry["status"] in ("ACTIVE", "OFFERED"):
            entry["status"] = "CANCELLED"
            entry["offer_expires_at"] = None
            entry["queue_position"] = 0
            touch_once(entry)
    recompute_queue(unit["id"])
    home = calc.home_of_unit(unit)
    if home and home["recognition_status"] == "RECOGNIZED":
        home["recognition_status"] = "SUSPENDED"
        touch_once(home)
        void_draft_claims(home)


def reinstatement_cascade(unit):
    """Hop 3; hops 1-2 are done by the caller."""
    home = calc.home_of_unit(unit)
    if not home:
        return
    if calc.decertified_unit_count(home) == 0 and home["recognition_status"] == "SUSPENDED":
        home["recognition_status"] = "RECOGNIZED"
        touch_once(home)


def revoke_offers_when_restricted(unit):
    """A posture that tightened to RESTRICTED/FROZEN reverts outstanding offers.

    A posture revocation is NOT a decline: declined_offer_count is untouched.
    """
    if calc.operational_posture(unit) == "OPEN":
        return
    for entry in sorted(unit_entries(unit["id"]), key=order_key):
        if entry["status"] == "OFFERED":
            entry["status"] = "ACTIVE"
            entry["offer_expires_at"] = None
            touch_once(entry)


# ----------------------------------------------------- care plan helpers ----
def resident_plans(resident_id):
    return [p for p in store.care_plans.values() if p["resident_id"] == resident_id]


def governing_plans(resident_id):
    return [p for p in resident_plans(resident_id) if p["status"] in ("ACTIVE", "REVIEW_DUE")]


def active_plan(resident_id):
    rows = [p for p in resident_plans(resident_id) if p["status"] == "ACTIVE"]
    return max(rows, key=order_key) if rows else None


# ------------------------------------------------------------ cost share ----
def resident_income_records(resident_id, month, statuses):
    return [
        ir
        for ir in store.income_records.values()
        if ir["resident_id"] == resident_id
        and ir["effective_month"] == month
        and ir["verification_status"] in statuses
    ]


def resident_day_rows(resident_id, month):
    return [
        d
        for d in store.census_days.values()
        if d["resident_id"] == resident_id
        and d["census_class"] == "RESIDENT_DAY"
        and date_in_month(parse_date(d["service_date"]), month)
    ]


def compute_cost_share(resident, variant, month, declared_medical_expense_cents):
    """The pinned ten-step waterfall of PRD 3.7."""
    statuses = ("UNVERIFIED", "VERIFIED") if variant == "PROVISIONAL" else ("VERIFIED",)
    gross = 0
    for record in resident_income_records(resident["id"], month, statuses):
        gross += round_half_up(
            record["monthly_amount_cents"] * record["countable_rate_bps"], 10000
        )

    home = calc.home_of_resident(resident)
    pna = home["personal_needs_allowance_monthly_cents"] if home else 0
    net_before_medical = max(0, gross - pna)

    low, high = COST_SHARE_TIER_BOUNDS_CENTS
    if net_before_medical <= low:
        tier = "TIER_1"
    elif net_before_medical <= high:
        tier = "TIER_2"
    else:
        tier = "TIER_3"

    if variant == "PROVISIONAL":
        allowed_medical = 0
    else:
        allowed_medical = min(declared_medical_expense_cents, MEDICAL_CAP_BY_TIER_CENTS[tier])

    net_after_medical = max(0, net_before_medical - allowed_medical)
    band1 = min(net_after_medical, low)
    band2 = min(max(net_after_medical - low, 0), high - low)
    band3 = max(net_after_medical - high, 0)
    tiered = (
        apply_bps(band1, COST_SHARE_TIER_BPS[0])
        + apply_bps(band2, COST_SHARE_TIER_BPS[1])
        + apply_bps(band3, COST_SHARE_TIER_BPS[2])
    )

    if variant == "PROVISIONAL":
        first_day, last_day = month_bounds(month)
        start = max(parse_date(resident["admission_date"]), first_day)
        day_count = max(0, (last_day - start).days + 1)
        offset = 0
        monthly = max(
            0, round_half_up((tiered - offset) * day_count, days_in_month(month))
        )
    else:
        day_count = len(resident_day_rows(resident["id"], month))
        rate = PER_DIEM_RATE_CENTS[resident["current_care_level"]]
        arm_a = round_half_up(rate * day_count * FEDERAL_OFFSET_SHARE_BPS, 10000)
        arm_b = round_half_up(tiered * FEDERAL_OFFSET_CAP_BPS, 10000)
        offset = min(arm_a, arm_b)
        monthly = max(0, tiered - offset)

    return {
        "gross_countable_income_cents": gross,
        "pna_deduction_cents": pna,
        "income_tier": tier,
        "allowed_medical_deduction_cents": allowed_medical,
        "tiered_share_cents": tiered,
        "resident_day_count": day_count,
        "federal_per_diem_offset_cents": offset,
        "monthly_cost_share_cents": monthly,
    }


# ------------------------------------------------------ claim attribution ----
def month_days_for_unit(care_unit_id, claim_month):
    rows = [
        d
        for d in store.census_days.values()
        if d["care_unit_id"] == care_unit_id
        and date_in_month(parse_date(d["service_date"]), claim_month)
        and d["census_class"] != "ABSENT_DAY"
    ]
    return sorted(rows, key=lambda d: (d["service_date"], d["created_at"], d["_seq"]))


def _held_by_live_claim(day, claim_id, takeover_id):
    held = day.get("per_diem_claim_id")
    if not held or held == claim_id or (takeover_id and held == takeover_id):
        return False
    other = store.claims.get(held)
    if other is None:
        return False
    return other["status"] in ("SUBMITTED", "PAID")


def has_consumed_day(care_unit_id, claim_month, claim_id=None, takeover_id=None):
    """Single-attribution guard: any day locked by a SUBMITTED/PAID claim."""
    for day in month_days_for_unit(care_unit_id, claim_month):
        if _held_by_live_claim(day, claim_id, takeover_id):
            return True
    return False


def attributable_days(care_unit_id, claim_month, claim_id=None, takeover_id=None):
    return [
        day
        for day in month_days_for_unit(care_unit_id, claim_month)
        if not _held_by_live_claim(day, claim_id, takeover_id)
    ]


def price_claim(claim, days):
    unit = store.care_units.get(claim["care_unit_id"])
    rate = PER_DIEM_RATE_CENTS[unit["care_level"]]
    resident_days = sum(1 for d in days if d["census_class"] == "RESIDENT_DAY")
    bed_hold_days = sum(1 for d in days if d["census_class"] == "BED_HOLD_DAY")
    distinct_residents = len(set(d["resident_id"] for d in days))
    if claim["basis"] == "AUDITED_BASIS":
        per_day = apply_bps(rate, BED_HOLD_RATE_BPS)
        payable = min(bed_hold_days, BED_HOLD_PAYABLE_DAYS_PER_MONTH)
        billable = resident_days + payable
        amount = rate * resident_days + per_day * payable
    else:
        billable = resident_days + bed_hold_days
        amount = rate * billable
    claim["resident_day_count"] = resident_days
    claim["bed_hold_day_count"] = bed_hold_days
    claim["billable_day_count"] = billable
    claim["claim_amount_cents"] = amount
    claim["census_reported_resident_count"] = distinct_residents


def attribute_and_price(claim, takeover_id=None):
    days = attributable_days(
        claim["care_unit_id"], claim["claim_month"], claim["id"], takeover_id
    )
    for day in days:
        day["per_diem_claim_id"] = claim["id"]
    price_claim(claim, days)
    return days


# --------------------------------------------------------- occupancy sync ----
def sync_unit(unit):
    """A bed-count/posture recomputation is a mutation of the unit."""
    if unit is None:
        return
    touch_once(unit)
    recompute_queue(unit["id"])


# ------------------------------------------------ nightly census checkpoint ----
def _hold_window(resident, window_end):
    hold_start = parse_date(resident["bed_hold_started_on"]) if resident["bed_hold_started_on"] else None
    if hold_start is None:
        return None, None, 0
    end_date = parse_date(resident["last_hospitalization_end_date"]) if resident["last_hospitalization_end_date"] else None
    if end_date is not None and end_date > hold_start:
        hold_end = end_date
        prior_closed = resident["bed_hold_days_used"] - (hold_end - hold_start).days
    elif resident["occupancy_status"] == "DISCHARGED" and resident["discharge_date"]:
        hold_end = parse_date(resident["discharge_date"]) + timedelta(days=1)
        prior_closed = resident["bed_hold_days_used"]
    else:
        hold_end = window_end + timedelta(days=1)
        prior_closed = resident["bed_hold_days_used"]
    return hold_start, hold_end, prior_closed


def classify_date(resident, service_date, window_end):
    hold_start, hold_end, prior_closed = _hold_window(resident, window_end)
    if hold_start is None or not (hold_start <= service_date < hold_end):
        return "RESIDENT_DAY"
    used_at_end = prior_closed + (service_date - hold_start).days
    return "BED_HOLD_DAY" if used_at_end < BED_HOLD_MAX_DAYS else "ABSENT_DAY"


def _scope_residents(home_id):
    rows = sorted(store.residents.values(), key=order_key)
    if home_id is None:
        return rows
    unit_ids = set(u["id"] for u in calc.home_units(home_id))
    return [r for r in rows if r["care_unit_id"] in unit_ids]


def _existing_census(resident_id):
    return set(
        d["service_date"] for d in store.census_days.values() if d["resident_id"] == resident_id
    )


def census_run(through_date_str, home_id, actor_user_id):
    through = parse_date(through_date_str)
    counters = {
        "generated_census_day_count": 0,
        "pna_credited_resident_count": 0,
        "cost_share_debited_resident_count": 0,
        "skipped_cost_share_debit_count": 0,
        "offered_waitlist_entry_count": 0,
        "expired_offer_count": 0,
        "review_due_care_plan_count": 0,
    }
    residents = _scope_residents(home_id)

    # ---- Step 1: materialise the census -----------------------------------
    for resident in residents:
        admission = parse_date(resident["admission_date"])
        if resident["last_census_date"]:
            window_start = max(admission, parse_date(resident["last_census_date"]) + timedelta(days=1))
        else:
            window_start = admission
        discharge = parse_date(resident["discharge_date"]) if resident["discharge_date"] else None
        window_end = min(through, discharge) if discharge else through
        if resident["occupancy_status"] == "DISCHARGED":
            if discharge is None or discharge < window_start:
                continue
        if window_start > window_end:
            continue
        already = _existing_census(resident["id"])
        unit = store.care_units.get(resident["care_unit_id"])
        care_level = unit["care_level"] if unit else resident["current_care_level"]
        cursor = window_start
        while cursor <= window_end:
            key = format_date(cursor)
            if key not in already:
                census_class = classify_date(resident, cursor, window_end)
                day = new_record()
                day.update(
                    {
                        "resident_id": resident["id"],
                        "care_unit_id": resident["care_unit_id"],
                        "per_diem_claim_id": None,
                        "service_date": key,
                        "census_class": census_class,
                        "care_level": care_level,
                        "per_diem_eligible": census_class in ("RESIDENT_DAY", "BED_HOLD_DAY"),
                        "payable_rate_cents": calc.payable_rate_for(care_level, census_class),
                    }
                )
                store.census_days[day["id"]] = day
                counters["generated_census_day_count"] += 1
            cursor += timedelta(days=1)
        resident["last_census_date"] = format_date(window_end)
        touch_once(resident)

    # Steps 2 and 3 act on the non-DISCHARGED residents of the run's scope.
    active_residents = [r for r in residents if r["occupancy_status"] != "DISCHARGED"]
    run_month = month_of_date(through)

    # ---- Step 2: credit the personal needs allowance ----------------------
    for resident in active_residents:
        home = calc.home_of_resident(resident)
        if home is None:
            continue
        amount = home["personal_needs_allowance_monthly_cents"]
        if amount <= 0:
            continue
        if _has_month_posting(resident["id"], "PNA_CREDIT", run_month):
            continue
        post_transaction(
            resident,
            "PNA_CREDIT",
            amount,
            through_date_str,
            "personal needs allowance",
            actor_user_id,
        )
        counters["pna_credited_resident_count"] += 1

    # ---- Step 3: debit the monthly cost share ----------------------------
    for resident in active_residents:
        home = calc.home_of_resident(resident)
        if home is None:
            continue
        share = calc.mirrored_cost_share(resident)
        if share <= 0:
            continue
        if _has_month_posting(resident["id"], "COST_SHARE_DEBIT", run_month):
            continue
        projected = calc.trust_fund_balance(resident["id"]) - share
        if projected < home["personal_needs_allowance_monthly_cents"]:
            counters["skipped_cost_share_debit_count"] += 1
            continue
        post_transaction(
            resident,
            "COST_SHARE_DEBIT",
            share,
            through_date_str,
            "monthly cost share",
            actor_user_id,
        )
        counters["cost_share_debited_resident_count"] += 1

    # ---- Step 4: advance the waitlist ------------------------------------
    if home_id is None:
        units = sorted(store.care_units.values(), key=order_key)
    else:
        units = sorted(calc.home_units(home_id), key=order_key)

    scored = set()
    for unit in units:
        for entry in unit_entries(unit["id"]):
            if entry["status"] not in ("ACTIVE", "OFFERED"):
                continue
            applicant = store.applicants.get(entry["applicant_id"])
            if applicant is None or applicant["id"] in scored:
                continue
            scored.add(applicant["id"])
            applicant["priority_score"] = calc.compute_priority_score(applicant)
            touch_once(applicant)
    for unit in units:
        recompute_queue(unit["id"])

    for unit in units:
        if calc.operational_posture(unit) != "OPEN":
            continue
        if calc.available_bed_count(unit) < 1:
            continue
        entries = unit_entries(unit["id"])
        if any(e["status"] == "OFFERED" for e in entries):
            continue
        head = None
        for entry in entries:
            if entry["status"] == "ACTIVE" and entry["queue_position"] == 1:
                head = entry
                break
        if head is None:
            continue
        head["status"] = "OFFERED"
        head["offer_expires_at"] = format_datetime(
            store.clock + timedelta(days=OFFER_WINDOW_DAYS)
        )
        touch_once(head)
        touch_once(unit)
        recompute_queue(unit["id"])
        counters["offered_waitlist_entry_count"] += 1

    now = now_iso()
    for unit in units:
        changed = False
        for entry in sorted(unit_entries(unit["id"]), key=order_key):
            if entry["status"] != "OFFERED" or not entry["offer_expires_at"]:
                continue
            if now <= entry["offer_expires_at"]:
                continue
            entry["status"] = "ACTIVE"
            entry["offer_expires_at"] = None
            touch_once(entry)
            applicant = store.applicants.get(entry["applicant_id"])
            if applicant:
                applicant["declined_offer_count"] += 1
                applicant["priority_score"] = calc.compute_priority_score(applicant)
                touch_once(applicant)
            counters["expired_offer_count"] += 1
            changed = True
        if changed:
            touch_once(unit)
            recompute_queue(unit["id"])

    for unit in units:
        changed = False
        for entry in sorted(unit_entries(unit["id"]), key=order_key):
            if entry["status"] != "ACTIVE":
                continue
            applicant = store.applicants.get(entry["applicant_id"])
            if applicant is None or applicant["declined_offer_count"] < MAX_DECLINED_OFFERS:
                continue
            entry["status"] = "EXPIRED"
            entry["queue_position"] = 0
            entry["offer_expires_at"] = None
            touch_once(entry)
            changed = True
        if changed:
            touch_once(unit)
    for unit in units:
        recompute_queue(unit["id"])

    # ---- Step 5: flag care-plan reviews ----------------------------------
    scoped_resident_ids = set(r["id"] for r in residents)
    for plan in sorted(store.care_plans.values(), key=order_key):
        if plan["resident_id"] not in scoped_resident_ids:
            continue
        if plan["status"] != "ACTIVE" or not plan["review_due_date"]:
            continue
        if plan["review_due_date"] < through_date_str:
            plan["status"] = "REVIEW_DUE"
            touch_once(plan)
            counters["review_due_care_plan_count"] += 1

    counters["current_utc"] = now_iso()
    return counters


def _has_month_posting(resident_id, txn_type, month):
    for txn in store.transactions.values():
        if txn["resident_id"] != resident_id or txn["txn_type"] != txn_type:
            continue
        if month_of_date(parse_date(txn["effective_date"])) == month:
            return True
    return False


def signed_amount(txn_type, amount_cents):
    if txn_type in ("DEPOSIT", "PNA_CREDIT"):
        return amount_cents
    return -amount_cents


def post_transaction(resident, txn_type, amount_cents, effective_date, memo, user_id,
                     reverses_transaction_id=None, signed=None):
    txn = new_record()
    txn.update(
        {
            "resident_id": resident["id"],
            "reverses_transaction_id": reverses_transaction_id,
            "txn_type": txn_type,
            "amount_cents": amount_cents,
            "signed_amount_cents": signed if signed is not None else signed_amount(txn_type, amount_cents),
            "effective_date": effective_date,
            "recorded_by_user_id": user_id,
            "memo": memo,
        }
    )
    store.transactions[txn["id"]] = txn
    touch_once(resident)
    return txn
