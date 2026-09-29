"""Domain calculations and cascades (PRD sections 2.6, 2.7, 2.10, 3.3-3.9)."""

from errors import (
    ERR_FX_RATE_UNAVAILABLE,
    ERR_NO_QUALIFYING_RATE_PROGRAM,
    fail,
)
from store import (
    ASSESSMENT_CAP_BPS,
    ASSESSMENT_FLOOR_CENTS,
    AUTH_VALIDITY_HOURS,
    CROSS_BORDER_MIN_CENTS,
    CROSS_BORDER_RATE_BPS,
    DOWNGRADE_AUDIT_TRIGGER,
    MISREPRESENTATION_PENALTY_BPS,
    MIN_PENALTY_CENTS,
    SMALL_TICKET_MAX_CENTS,
    TIER_1_FLOOR_CENTS,
    TIER_2_FLOOR_CENTS,
    TIER_3_FLOOR_CENTS,
    TIER_DISCOUNT_BPS,
    new_row,
    sort_key,
    sorted_rows,
    store,
    touch,
)
from timeutil import (
    date_of_ms,
    days_in_quarter,
    parse_date,
    quarter_bounds,
    quarter_of_date,
    quarter_of_ms,
    round_half_up_2dp,
    round_half_up_div,
)

DAY_MS = 86400000
HOUR_MS = 3600000


# ---------------------------------------------------------------------------
# Category directory lookups (PRD 3.3)
# ---------------------------------------------------------------------------

def mcc_def_by_code(code):
    """The definition carrying this four-digit code, matched by string equality."""
    if code is None:
        return None
    for row in store.mcc_definitions.values():
        if row["mcc_code"] == code:
            return row
    return None


def mcc_code_exists(code):
    return mcc_def_by_code(code) is not None


def assignment_rank(row):
    """high_risk ascending, then mcc_code ascending, then created_at ascending."""
    return (1 if row["high_risk"] else 0, row["mcc_code"], row["_created_ms"], row["_seq"])


def definitions_for_business_type(business_type_key):
    return [
        row for row in store.mcc_definitions.values()
        if row["business_type_key"] == business_type_key
    ]


def select_definition_for_business_type(business_type_key):
    """The winner of the assignment ranking, or None when no candidate exists."""
    candidates = definitions_for_business_type(business_type_key)
    if not candidates:
        return None
    return sorted(candidates, key=assignment_rank)[0]


def program_eligibility_of(mcc_code):
    definition = mcc_def_by_code(mcc_code)
    if definition is None:
        return []
    return list(definition.get("program_eligibility") or [])


# ---------------------------------------------------------------------------
# Rate-program qualification (PRD 3.5 and 3.6)
# ---------------------------------------------------------------------------

def amortised_cost_bps(program, amount_cents):
    """base_rate_bps plus the per-item fee amortised into whole basis points."""
    per_item = int(program["per_item_fee_cents"])
    amortised = round_half_up_div(per_item * 10000, int(amount_cents))
    return int(program["base_rate_bps"]) + amortised


def candidate_programs(record, mcc_code, enforce_clearing_delay):
    """The rate programs a record may reach. Conditions are PRD 3.5's five plus,
    at finalization only, the program's clearing-delay tolerance."""
    eligibility = program_eligibility_of(mcc_code)
    present = set(record.get("data_elements") or [])
    out = []
    for program in store.rate_programs.values():
        category = program["category"]
        if mcc_code not in (program.get("eligible_mcc_codes") or []):
            continue
        if category not in ("STANDARD", "CPS_RETAIL") and category not in eligibility:
            continue
        if not set(program.get("requires_data_elements") or []).issubset(present):
            continue
        if category == "SMALL_TICKET" and int(record["amount_cents"]) > SMALL_TICKET_MAX_CENTS:
            continue
        if category != "STANDARD" and record["authorization_status"] != "AUTH_APPROVED":
            continue
        if enforce_clearing_delay and category != "STANDARD":
            if int(record["clearing_delay_hours"]) > int(program["max_clearing_delay_hours"]):
                continue
        out.append(program)
    return out


def select_rate_program(record, mcc_code, enforce_clearing_delay):
    """The cheapest candidate at this ticket size, or None when none survives."""
    candidates = candidate_programs(record, mcc_code, enforce_clearing_delay)
    if not candidates:
        return None
    amount = int(record["amount_cents"])
    ranked = sorted(
        candidates,
        key=lambda p: (
            amortised_cost_bps(p, amount),
            int(p["base_rate_bps"]),
            p["_created_ms"],
            p["_seq"],
        ),
    )
    return ranked[0]


def applicable_fx_row(base_currency, quote_currency):
    """The conversion row with the latest effective_from at or before the clock,
    breaking ties on the latest created_at (PRD 3.6 step three)."""
    now = store.now_ms()
    pool = [
        row for row in store.fx_rates.values()
        if row["base_currency"] == base_currency
        and row["quote_currency"] == quote_currency
        and row["effective_from"] <= now
    ]
    if not pool:
        return None
    pool.sort(key=lambda r: (r["effective_from"], r["_created_ms"], r["_seq"]))
    return pool[-1]


def compute_assessment(record, program, batch):
    """The four-step assessment pipeline. Returns (total, cross_border, fx)."""
    amount = int(record["amount_cents"])
    # Step one: ad-valorem rounded to whole cents, then the flat per-item fee.
    ad_valorem = round_half_up_div(amount * int(program["base_rate_bps"]), 10000)
    step_one = ad_valorem + int(program["per_item_fee_cents"])
    # Step two: the cross-border surcharge.
    if record["cross_border"]:
        surcharge = max(
            CROSS_BORDER_MIN_CENTS,
            round_half_up_div(amount * CROSS_BORDER_RATE_BPS, 10000),
        )
    else:
        surcharge = 0
    # Step three: the currency-conversion markup.
    if record["transaction_currency"] != batch["currency_code"]:
        fx_row = applicable_fx_row(record["transaction_currency"], batch["currency_code"])
        if fx_row is None:
            fail(ERR_FX_RATE_UNAVAILABLE)
        markup = round_half_up_div(amount * int(fx_row["markup_bps"]), 10000)
    else:
        markup = 0
    # Step four: cap first, then floor.
    raw = step_one + surcharge + markup
    ceiling = round_half_up_div(amount * ASSESSMENT_CAP_BPS, 10000)
    capped = min(raw, ceiling)
    total = max(capped, ASSESSMENT_FLOOR_CENTS)
    return total, surcharge, markup


def reference_program(record, mcc_code):
    """The cheapest non-fallback tier the category could ever reach, ignoring the
    record's data quality entirely (PRD 3.6)."""
    eligibility = program_eligibility_of(mcc_code)
    pool = []
    for program in store.rate_programs.values():
        category = program["category"]
        if mcc_code not in (program.get("eligible_mcc_codes") or []):
            continue
        if category == "STANDARD":
            continue
        if category != "CPS_RETAIL" and category not in eligibility:
            continue
        pool.append(program)
    if not pool:
        return None
    pool.sort(key=lambda p: (int(p["base_rate_bps"]), p["_created_ms"], p["_seq"]))
    return pool[0]


def resolve_downgrade_reason(record, mcc_code):
    """Five checks in a fixed order, stopping at the first that fires."""
    reference = reference_program(record, mcc_code)
    if reference is None:
        return "MCC_INELIGIBLE"
    present = set(record.get("data_elements") or [])
    required = set(reference.get("requires_data_elements") or [])
    if not required.issubset(present):
        return "MISSING_DATA_ELEMENTS"
    if int(record["clearing_delay_hours"]) > int(reference["max_clearing_delay_hours"]):
        return "LATE_CLEARING"
    if reference["category"] == "SMALL_TICKET" and int(record["amount_cents"]) > SMALL_TICKET_MAX_CENTS:
        return "TICKET_SIZE_INELIGIBLE"
    if record["authorization_status"] != "AUTH_APPROVED":
        return "AUTH_MISSING"
    return "MCC_INELIGIBLE"


# ---------------------------------------------------------------------------
# Row collections
# ---------------------------------------------------------------------------

def records_of_batch(batch_id):
    return sorted_rows([
        r for r in store.records.values() if r["settlement_batch_id"] == batch_id
    ])


def records_of_merchant(merchant_id):
    return sorted_rows([
        r for r in store.records.values() if r["merchant_id"] == merchant_id
    ])


def requests_of_merchant(merchant_id):
    return sorted_rows([
        r for r in store.reclass_requests.values() if r["merchant_id"] == merchant_id
    ])


def enrollments_of_merchant(merchant_id):
    return sorted_rows([
        e for e in store.enrollments.values() if e["merchant_id"] == merchant_id
    ])


def enrollments_of_program(program_id):
    return sorted_rows([
        e for e in store.enrollments.values() if e["incentive_program_id"] == program_id
    ])


def windows_of_acquirer(acquirer_id):
    return sorted_rows([
        w for w in store.windows.values() if w["acquirer_id"] == acquirer_id
    ])


def audits_of_merchant(merchant_id):
    return sorted_rows([
        a for a in store.audits.values() if a["merchant_id"] == merchant_id
    ])


def merchant_has_live_audit(merchant_id):
    return any(
        a["status"] in ("SCHEDULED", "FIELDWORK")
        for a in store.audits.values() if a["merchant_id"] == merchant_id
    )


def apply_changes(row, changes):
    """Write the changed fields and advance version only if something moved."""
    moved = False
    for field, value in changes.items():
        if row.get(field) != value:
            row[field] = value
            moved = True
    if moved:
        touch(row)
    return moved


# ---------------------------------------------------------------------------
# The assessment ledger (PRD 2.10)
# ---------------------------------------------------------------------------

LEDGER_STATUSES = ("QUALIFIED", "DOWNGRADED")


def recompute_batch_totals(batch):
    """Re-derive record_count and total_assessed_cents from the surviving rows."""
    rows = records_of_batch(batch["id"])
    total = 0
    for row in rows:
        if row["qualification_status"] in LEDGER_STATUSES:
            total += int(row["assessed_interchange_cents"])
    return apply_changes(batch, {
        "record_count": len(rows),
        "total_assessed_cents": total,
    })


def current_quarter():
    return quarter_of_ms(store.now_ms())


def recompute_merchant_ledger(merchant):
    """Re-derive lifetime_net_assessed_cents and downgrade_count_current_quarter."""
    rows = records_of_merchant(merchant["id"])
    lifetime = 0
    downgrades = 0
    quarter = current_quarter()
    for row in rows:
        if row["qualification_status"] in LEDGER_STATUSES:
            lifetime += int(row["assessed_interchange_cents"])
        if row["qualification_status"] != "DOWNGRADED":
            continue
        batch = store.batches.get(row["settlement_batch_id"])
        if batch is None or batch["status"] != "FINALIZED":
            continue
        batch_day = parse_date(batch["batch_date"])
        if batch_day is not None and quarter_of_date(batch_day) == quarter:
            downgrades += 1
    return apply_changes(merchant, {
        "lifetime_net_assessed_cents": lifetime,
        "downgrade_count_current_quarter": downgrades,
    })


# ---------------------------------------------------------------------------
# Acquirer compliance posture (PRD 3.2)
# ---------------------------------------------------------------------------

def recompute_acquirer_compliance(acquirer, allow_recovery=True):
    """missed_window_count is the number of windows currently in MISSED."""
    count = sum(
        1 for w in store.windows.values()
        if w["acquirer_id"] == acquirer["id"] and w["status"] == "MISSED"
    )
    changes = {"missed_window_count": count}
    if count > 0 and acquirer["compliance_status"] == "COMPLIANT":
        changes["compliance_status"] = "NON_COMPLIANT"
    elif count == 0 and allow_recovery and acquirer["compliance_status"] == "NON_COMPLIANT":
        changes["compliance_status"] = "COMPLIANT"
    return apply_changes(acquirer, changes)


# ---------------------------------------------------------------------------
# Reclassification suspension cascade (PRD 3.4)
# ---------------------------------------------------------------------------

LIVE_REQUEST_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")
AUTO_DENY_NOTE = "auto-denied by sustained category audit"


def supersede_live_requests(merchant_id):
    """Filing a new request retires every live predecessor."""
    for row in requests_of_merchant(merchant_id):
        if row["status"] in LIVE_REQUEST_STATUSES:
            apply_changes(row, {"status": "SUPERSEDED"})


def suspend_live_requests(merchant_id):
    """Snapshot the prior status and freeze the request pending the audit."""
    for row in requests_of_merchant(merchant_id):
        if row["status"] in LIVE_REQUEST_STATUSES:
            apply_changes(row, {
                "prior_status_before_suspension": row["status"],
                "status": "SUSPENDED_PENDING_AUDIT",
            })


def restore_suspended_requests(merchant_id):
    """A cleared audit restores each snapshot verbatim and nulls the slot."""
    for row in requests_of_merchant(merchant_id):
        if row["status"] != "SUSPENDED_PENDING_AUDIT":
            continue
        prior = row.get("prior_status_before_suspension")
        if prior is None:
            continue
        apply_changes(row, {
            "status": prior,
            "prior_status_before_suspension": None,
        })


def deny_suspended_requests(merchant_id):
    """A sustained audit auto-denies each suspended request."""
    for row in requests_of_merchant(merchant_id):
        if row["status"] != "SUSPENDED_PENDING_AUDIT":
            continue
        apply_changes(row, {
            "status": "DENIED",
            "decision_note": AUTO_DENY_NOTE,
        })


# ---------------------------------------------------------------------------
# The incentive capacity pool (PRD 2.10 and 3.8)
# ---------------------------------------------------------------------------

COMMITTED_STATUSES = ("ENROLLED", "PROBATION")
BLOCKING_ENROLLMENT_STATUSES = ("PENDING", "ENROLLED", "WAITLISTED", "PROBATION")


def recompute_capacity(program):
    """Re-derive the pool from the enrollments that currently hold capacity."""
    committed = 0
    enrolled = 0
    for row in enrollments_of_program(program["id"]):
        if row["status"] in COMMITTED_STATUSES:
            committed += int(row["committed_volume_cents"])
            enrolled += 1
    return apply_changes(program, {
        "uncommitted_capacity_cents": int(program["total_capacity_cents"]) - committed,
        "enrolled_count": enrolled,
    })


def after_capacity_debit(program):
    """A pool too small to admit a minimum commitment is functionally full."""
    recompute_capacity(program)
    if (program["enrollment_state"] == "OPEN"
            and int(program["uncommitted_capacity_cents"]) < int(program["min_commitment_cents"])):
        apply_changes(program, {"enrollment_state": "CLOSED_FULL"})


def after_capacity_release(program):
    """A release may reopen the program, and a reopening promotes the head of line."""
    recompute_capacity(program)
    if (program["enrollment_state"] == "CLOSED_FULL"
            and int(program["uncommitted_capacity_cents"]) >= int(program["reopen_threshold_cents"])):
        apply_changes(program, {"enrollment_state": "OPEN"})
        promote_head_of_line(program)


def promote_head_of_line(program):
    """Strict head-of-line service: only the earliest waitlisted row is considered
    and at most one row is ever promoted."""
    waitlisted = [
        e for e in enrollments_of_program(program["id"]) if e["status"] == "WAITLISTED"
    ]
    if not waitlisted:
        return None
    head = waitlisted[0]
    if int(head["committed_volume_cents"]) > int(program["uncommitted_capacity_cents"]):
        return None
    apply_changes(head, {"status": "ENROLLED", "enrolled_at": store.now_ms()})
    after_capacity_debit(program)
    return head


def terminate_ineligible_enrollments(merchant):
    """Every ENROLLED or PROBATION enrollment whose program no longer covers the
    merchant's category is terminated, releasing its capacity."""
    new_code = merchant["assigned_mcc"]
    for row in enrollments_of_merchant(merchant["id"]):
        if row["status"] not in COMMITTED_STATUSES:
            continue
        program = store.incentive_programs.get(row["incentive_program_id"])
        if program is None:
            continue
        if new_code in (program.get("eligible_mcc_codes") or []):
            continue
        apply_changes(row, {"status": "TERMINATED_INELIGIBLE"})
        after_capacity_release(program)


# ---------------------------------------------------------------------------
# Performance scoring, volume tier and credit (PRD 3.8)
# ---------------------------------------------------------------------------

def measurement_records(enrollment):
    """The merchant's QUALIFIED or DOWNGRADED records in FINALIZED batches whose
    batch_date falls from the enrolment date through the clock date, inclusive."""
    start = date_of_ms(enrollment["enrolled_at"]) if enrollment.get("enrolled_at") else None
    end = date_of_ms(store.now_ms())
    out = []
    for row in records_of_merchant(enrollment["merchant_id"]):
        if row["qualification_status"] not in LEDGER_STATUSES:
            continue
        batch = store.batches.get(row["settlement_batch_id"])
        if batch is None or batch["status"] != "FINALIZED":
            continue
        batch_day = parse_date(batch["batch_date"])
        if batch_day is None:
            continue
        if start is not None and batch_day < start:
            continue
        if batch_day > end:
            continue
        out.append((row, batch_day))
    return out


def achieved_volume(enrollment, basis):
    """Prior-quarter volume alone under TRAILING; plus the scaled-up current
    partial quarter under PROJECTED."""
    rows = measurement_records(enrollment)
    quarter = current_quarter()
    prior = 0
    current = 0
    for row, batch_day in rows:
        row_quarter = quarter_of_date(batch_day)
        if row_quarter < quarter:
            prior += int(row["amount_cents"])
        elif row_quarter == quarter:
            current += int(row["amount_cents"])
    if basis == "TRAILING":
        return prior
    today = date_of_ms(store.now_ms())
    quarter_start, _ = quarter_bounds(quarter[0], quarter[1])
    elapsed_days = (today - quarter_start).days + 1
    total_days = days_in_quarter(quarter[0], quarter[1])
    projection = round_half_up_div(current * total_days, elapsed_days)
    return prior + projection


def gross_assessed_volume(enrollment):
    """The full measurement window with no quarter partitioning."""
    total = 0
    for row, _ in measurement_records(enrollment):
        total += int(row["assessed_interchange_cents"])
    return total


def resolve_tier(gross_cents):
    if gross_cents >= TIER_3_FLOOR_CENTS:
        return "TIER_3"
    if gross_cents >= TIER_2_FLOOR_CENTS:
        return "TIER_2"
    if gross_cents >= TIER_1_FLOOR_CENTS:
        return "TIER_1"
    return "TIER_0"


def tier_and_credit(gross_cents):
    """The tier resolves from the gross figure and from nothing else; there is no
    second pass over the net figure."""
    tier = resolve_tier(gross_cents)
    credit = round_half_up_div(gross_cents * TIER_DISCOUNT_BPS[tier], 10000)
    return tier, credit, gross_cents - credit


def performance_score(achieved_cents, committed_cents):
    return round_half_up_2dp(achieved_cents * 100, committed_cents)


# ---------------------------------------------------------------------------
# Misrepresentation penalty (PRD 3.9)
# ---------------------------------------------------------------------------

def misrepresentation_penalty(lifetime_net_assessed_cents):
    return max(
        MIN_PENALTY_CENTS,
        round_half_up_div(int(lifetime_net_assessed_cents) * MISREPRESENTATION_PENALTY_BPS, 10000),
    )


# ---------------------------------------------------------------------------
# The downgrade tripwire (PRD 3.6)
# ---------------------------------------------------------------------------

def new_audit_row(merchant, trigger_reason, auditor_user_id=None):
    return new_row({
        "merchant_id": merchant["id"],
        "trigger_reason": trigger_reason,
        "status": "SCHEDULED",
        "auditor_user_id": auditor_user_id,
        "fieldwork_start": None,
        "fieldwork_end": None,
        "correct_mcc": None,
        "findings_note": None,
        "penalty_assessed_cents": 0,
        "mcc_at_audit_open": merchant["assigned_mcc"],
        "closed_by_user_id": None,
    })


def open_audit_on_merchant(merchant, trigger_reason, auditor_user_id=None):
    """Create the audit, freeze the merchant's posture and suspend its requests."""
    audit = new_audit_row(merchant, trigger_reason, auditor_user_id)
    store.audits[audit["id"]] = audit
    apply_changes(merchant, {
        "mcc_status_before_review": merchant["mcc_status"],
        "mcc_status": "UNDER_REVIEW",
    })
    suspend_live_requests(merchant["id"])
    return audit


def run_downgrade_tripwire(merchants):
    """Three or more downgrades in the quarter opens an audit by itself."""
    for merchant in sorted_rows(merchants):
        if int(merchant["downgrade_count_current_quarter"]) < DOWNGRADE_AUDIT_TRIGGER:
            continue
        if merchant["mcc_status"] not in ("PENDING_VERIFICATION", "VERIFIED"):
            continue
        if merchant_has_live_audit(merchant["id"]):
            continue
        open_audit_on_merchant(merchant, "DOWNGRADE_THRESHOLD", None)


# ---------------------------------------------------------------------------
# Interval arithmetic (PRD 3.2)
# ---------------------------------------------------------------------------

def rate_version_overlaps(candidate):
    """Half-open, strict on both comparisons, capacity one."""
    for rival in sorted_rows(list(store.rate_versions.values())):
        if rival["id"] == candidate["id"]:
            continue
        if rival["rate_program_id"] != candidate["rate_program_id"]:
            continue
        if rival["status"] != "PUBLISHED":
            continue
        if (candidate["effective_from"] < rival["effective_to"]
                and rival["effective_from"] < candidate["effective_to"]):
            return True
    return False


def platform_window_conflict(platform, window_start, window_end):
    """Closed intervals inflated by the platform's blackout buffer, non-strict
    comparisons, counted against max_concurrent_windows."""
    buffer_ms = int(platform["blackout_buffer_days"]) * DAY_MS
    collisions = 0
    for rival in sorted_rows(list(store.windows.values())):
        if rival["platform_id"] != platform["id"]:
            continue
        if rival["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        inflated_start = rival["window_start"] - buffer_ms
        inflated_end = rival["window_end"] + buffer_ms
        if window_start <= inflated_end and inflated_start <= window_end:
            collisions += 1
    return collisions >= int(platform["max_concurrent_windows"])


def clearing_delay_hours(auth_ms, clearing_ms):
    """Whole complete hours, truncated toward zero."""
    return int((int(clearing_ms) - int(auth_ms)) // HOUR_MS)


# ---------------------------------------------------------------------------
# The logical clock and its three-step sweep (PRD 2.6)
# ---------------------------------------------------------------------------

def set_logical_clock(target_ms):
    store.clock_ms = int(target_ms)

    # Step one: supersede rate versions whose exclusive end is at or before now.
    for version in sorted_rows(list(store.rate_versions.values())):
        if version["status"] == "PUBLISHED" and version["effective_to"] <= store.clock_ms:
            apply_changes(version, {"status": "SUPERSEDED"})

    # Step two: mark windows whose inclusive end is strictly earlier than now.
    touched = []
    for window in sorted_rows(list(store.windows.values())):
        if window["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if window["window_end"] >= store.clock_ms:
            continue
        apply_changes(window, {"status": "MISSED"})
        acquirer = store.acquirers.get(window["acquirer_id"])
        if acquirer is not None and all(a["id"] != acquirer["id"] for a in touched):
            touched.append(acquirer)
    for acquirer in sorted_rows(touched):
        recompute_acquirer_compliance(acquirer, allow_recovery=False)

    # Step three: expire authorizations strictly older than the 720-hour horizon.
    horizon_ms = AUTH_VALIDITY_HOURS * HOUR_MS
    for record in sorted_rows(list(store.records.values())):
        if record["authorization_status"] != "AUTH_APPROVED":
            continue
        if record["qualification_status"] != "PENDING":
            continue
        if store.clock_ms - int(record["auth_timestamp"]) > horizon_ms:
            apply_changes(record, {"authorization_status": "AUTH_EXPIRED"})


# ---------------------------------------------------------------------------
# The two qualification passes
# ---------------------------------------------------------------------------

def provisional_pass(record, batch, merchant):
    """Intake: the clearing-delay tolerance is deliberately not consulted."""
    program = select_rate_program(record, merchant["assigned_mcc"], False)
    if program is None:
        fail(ERR_NO_QUALIFYING_RATE_PROGRAM)
    total, _surcharge, _markup = compute_assessment(record, program, batch)
    return program, total


def definitive_pass(batch):
    """Every PENDING member record, in ascending created_at order, evaluated with
    the clearing-delay tolerance enforced. Nothing is committed until every record
    has produced a result, so a failure leaves the batch untouched."""
    pending = [
        r for r in records_of_batch(batch["id"]) if r["qualification_status"] == "PENDING"
    ]
    selections = []
    for record in pending:
        merchant = store.merchants.get(record["merchant_id"])
        mcc_code = merchant["assigned_mcc"] if merchant else None
        program = select_rate_program(record, mcc_code, True)
        if program is None:
            fail(ERR_NO_QUALIFYING_RATE_PROGRAM)
        selections.append((record, merchant, mcc_code, program))
    results = []
    for record, merchant, mcc_code, program in selections:
        total, surcharge, markup = compute_assessment(record, program, batch)
        if program["category"] == "STANDARD":
            status = "DOWNGRADED"
            reason = resolve_downgrade_reason(record, mcc_code)
        else:
            status = "QUALIFIED"
            reason = None
        results.append({
            "record": record,
            "merchant": merchant,
            "mcc_code": mcc_code,
            "program": program,
            "status": status,
            "reason": reason,
            "total": total,
            "surcharge": surcharge,
            "markup": markup,
        })
    return results
