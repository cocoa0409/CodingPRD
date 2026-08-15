"""Domain constants, calculations, ledger posting, regulatory reporting and
clock sweeps (SCAFFOLD §1.2/§1.3, PRD §2.4/§2.9/§2.10/§3)."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
import util

# --- Enum vocabularies (SCAFFOLD §1.1) ---
PERMISSIBLE_GROUND_CODES = {
    "NONPAYMENT",
    "MATERIAL_MISREPRESENTATION",
    "SUBSTANTIAL_CHANGE_IN_RISK",
    "LICENSE_SUSPENSION",
}
ALL_GROUND_CODES = PERMISSIBLE_GROUND_CODES | {"INSURED_REQUEST"}
INTEREST_TYPES = {"MORTGAGEE", "LIENHOLDER", "ADDITIONAL_INTEREST"}
RECIPIENT_KINDS = {"POLICYHOLDER", "MORTGAGEE", "LIENHOLDER", "ADDITIONAL_INTEREST"}
NONRENEWAL_REASON_CODES = {
    "UNDERWRITING_GUIDELINES",
    "LOSS_HISTORY",
    "CARRIER_WITHDRAWAL",
    "RISK_INELIGIBLE",
}
NONRENEWAL_CONTENT_CODES = {
    "SPECIFIC_REASON",
    "LOSS_HISTORY_SUMMARY",
    "FAIR_PLAN_INFO",
    "APPEAL_RIGHTS",
}
APPEAL_FILED_BY = {"POLICYHOLDER", "MORTGAGEE"}

OPEN_CASE_STATUSES = {"DRAFT", "PENDING_APPROVAL", "APPROVED", "NOTICE_SENT"}
LIVE_POLICY_STATUSES = {"ACTIVE", "CANCEL_PENDING", "NONRENEWAL_PENDING"}

# Reinstatement fee tiers (SCAFFOLD §1.3 reinstatement_fee constants)
TIER1_DAYS = 10
TIER1_FEE_CENTS = 0
TIER2_DAYS = 30
TIER2_FEE_CENTS = 2500
TIER3_FEE_CENTS = 5000

# Lapse threshold (PRD §3.7: "more than thirty days")
LAPSE_THRESHOLD_DAYS = 30


# ---------------------------------------------------------------------------
# Shared lookups
# ---------------------------------------------------------------------------

def policy_profile(policy):
    return db.state_profiles[policy["state_profile_id"]]


def policy_interests(policy_id):
    return util.sort_chronological(
        [i for i in db.insured_interests.values() if i["policy_id"] == policy_id]
    )


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def base_notice_days(profile, ground_code):
    if ground_code == "NONPAYMENT":
        return profile["nonpayment_notice_days"]
    return profile["other_grounds_notice_days"]


def compute_earliest_effective_date(profile, policy, ground_code, requested_on):
    """notice_window calculation: requested_on + max(base, mortgagee days when
    the policy carries at least one insured interest)."""
    base = base_notice_days(profile, ground_code)
    interests = policy_interests(policy["id"])
    days = base
    if interests:
        days = max(base, profile["mortgagee_notice_days"])
    return requested_on + timedelta(days=days)


def resolve_return_method(profile, ground_code):
    if ground_code == "INSURED_REQUEST" and profile["short_rate_penalty_pct"] > 0:
        return "SHORT_RATE"
    return "PRO_RATA"


def _round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_return_premium_cents(policy, case, profile):
    """return_premium calculation. Two mandatory roundings in pinned order:
    unearned premium first, short-rate penalty second."""
    term_start = date.fromisoformat(policy["term_start_date"])
    term_end = date.fromisoformat(policy["term_end_date"])
    scheduled = date.fromisoformat(case["scheduled_effective_date"])
    term_days = (term_end - term_start).days
    elapsed_days = (scheduled - term_start).days
    elapsed_days = max(0, min(elapsed_days, term_days))
    unearned = _round_half_up_cents(
        Decimal(policy["total_premium_cents"])
        * Decimal(term_days - elapsed_days)
        / Decimal(term_days)
    )
    if case["return_method"] == "SHORT_RATE":
        return _round_half_up_cents(
            Decimal(unearned) * (Decimal(1) - Decimal(str(profile["short_rate_penalty_pct"])))
        )
    return unearned


def compute_reinstatement_fee(lapse_days):
    """Boundary: lapse sitting exactly on a tier bound falls in the lower tier."""
    if lapse_days <= TIER1_DAYS:
        return TIER1_FEE_CENTS
    if lapse_days <= TIER2_DAYS:
        return TIER2_FEE_CENTS
    return TIER3_FEE_CENTS


# ---------------------------------------------------------------------------
# Premium ledger (PRD §2.9) — entries carry only id + created_at, no
# updated_at/version (the one exception to common fields).
# ---------------------------------------------------------------------------

def post_ledger_entry(policy_id, entry_kind, amount_cents, effective_date, cancellation_case_id=None):
    entry = {
        "id": util.new_id(),
        "created_at": util.now_ts(),
        "_seq": db.next_seq(),
        "policy_id": policy_id,
        "entry_kind": entry_kind,
        "amount_cents": amount_cents,
        "effective_date": effective_date,
        "cancellation_case_id": cancellation_case_id,
    }
    db.ledger_entries[entry["id"]] = entry
    return entry


def find_return_entry(case_id):
    """The negative return entry originally posted for a cancellation case."""
    for e in db.ledger_entries.values():
        if e.get("cancellation_case_id") == case_id and e["entry_kind"] in (
            "RETURN_PRO_RATA",
            "RETURN_SHORT_RATE",
        ) and e["amount_cents"] < 0:
            return e
    return None


# ---------------------------------------------------------------------------
# Regulatory reporting (PRD §2.10) — rows auto-created OPEN on first cascade.
# ---------------------------------------------------------------------------

def bump_report(profile_id, period, field):
    key = (profile_id, period)
    report = None
    for r in db.regulatory_reports.values():
        if r["_key"] == key:
            report = r
            break
    if report is None:
        report = util.stamp_new(
            {
                "_key": key,
                "state_profile_id": profile_id,
                "report_period": period,
                "status": "OPEN",
                "nonrenewal_count": 0,
                "cancellation_count": 0,
                "rescinded_count": 0,
            }
        )
        db.regulatory_reports[report["id"]] = report
    report[field] += 1
    util.touch(report)
    return report


# ---------------------------------------------------------------------------
# Notice-set validation (SCAFFOLD §1.2 dispatch transitions, PRD §3.4/§3.6).
# Returns the normalized per-entry plan or raises the scaffold's error.
# ---------------------------------------------------------------------------

def validate_notice_set(payload_notices, policy, case_kind):
    """case_kind: 'cancellation' or 'nonrenewal'. Returns a list of plan dicts:
    {recipient_kind, insured_interest_id, insured_interest, mailed_on (date),
    tracking_code, required_days}."""
    if not isinstance(payload_notices, list) or len(payload_notices) == 0:
        from errors import err_notice_set_incomplete
        raise err_notice_set_incomplete()

    interests = policy_interests(policy["id"])
    plan = []
    policyholder_count = 0
    seen_interest_ids = set()

    for entry in payload_notices:
        if not isinstance(entry, dict):
            from errors import err_notice_set_incomplete
            raise err_notice_set_incomplete()
        util.check_fields(
            entry,
            required=["recipient_kind", "mailed_on_date", "tracking_code"],
            optional=["insured_interest_id"],
        )
        kind = entry["recipient_kind"]
        if kind not in RECIPIENT_KINDS:
            from errors import err_invalid_request
            raise err_invalid_request("recipient_kind is invalid")
        interest_id = entry.get("insured_interest_id")
        if kind == "POLICYHOLDER":
            policyholder_count += 1
            if interest_id is not None:
                from errors import err_invalid_request
                raise err_invalid_request("policyholder notice carries no insured_interest_id")
            plan.append(
                {
                    "recipient_kind": kind,
                    "insured_interest_id": None,
                    "insured_interest": None,
                    "mailed_on": util.parse_date(entry["mailed_on_date"], "mailed_on_date"),
                    "tracking_code": entry["tracking_code"],
                    "required_days": None,  # filled by caller (case-dependent)
                }
            )
        else:
            if interest_id is None or not isinstance(interest_id, str):
                from errors import err_invalid_request
                raise err_invalid_request("interest notice requires insured_interest_id")
            interest = db.insured_interests.get(interest_id)
            if interest is not None and interest["policy_id"] != policy["id"]:
                from errors import err_interest_policy_mismatch
                raise err_interest_policy_mismatch()
            if interest is None:
                # Unresolvable interest reference cannot satisfy the required set.
                from errors import err_notice_set_incomplete
                raise err_notice_set_incomplete()
            if interest["interest_type"] != kind:
                from errors import err_invalid_request
                raise err_invalid_request(
                    "recipient_kind does not match the interest's interest_type"
                )
            seen_interest_ids.add(interest_id)
            plan.append(
                {
                    "recipient_kind": kind,
                    "insured_interest_id": interest_id,
                    "insured_interest": interest,
                    "mailed_on": util.parse_date(entry["mailed_on_date"], "mailed_on_date"),
                    "tracking_code": entry["tracking_code"],
                    "required_days": None,
                }
            )

    if policyholder_count != 1 or seen_interest_ids != {i["id"] for i in interests}:
        from errors import err_notice_set_incomplete
        raise err_notice_set_incomplete()
    return plan


# ---------------------------------------------------------------------------
# Clock sweeps (PRD §2.4). Run, in order, on every clock advance.
# ---------------------------------------------------------------------------

def _policy_for_case(case):
    return db.policies[case["policy_id"]]


def sweep_cancellation_effectiveness():
    for case in list(db.cancellation_cases.values()):
        if case["status"] != "NOTICE_SENT":
            continue
        scheduled = date.fromisoformat(case["scheduled_effective_date"])
        if clock.today() < scheduled:
            continue
        # Every notice must be MAILED or DELIVERY_CONFIRMED; otherwise the
        # sweep refuses effectiveness (ERR_NOTICE_NOT_MAILED condition) and
        # the policy stays CANCEL_PENDING.
        notices = [n for n in db.notices.values() if n.get("cancellation_case_id") == case["id"]]
        if any(n["status"] in ("QUEUED", "RETURNED_UNDELIVERABLE") for n in notices):
            continue
        policy = _policy_for_case(case)
        profile = policy_profile(policy)

        case["return_premium_cents"] = compute_return_premium_cents(policy, case, profile)
        case["status"] = "EFFECTIVE"
        util.touch(case)

        policy["status"] = "CANCELLED"
        policy["cancellation_effective_date"] = case["scheduled_effective_date"]
        util.touch(policy)

        entry_kind = "RETURN_PRO_RATA" if case["return_method"] == "PRO_RATA" else "RETURN_SHORT_RATE"
        post_ledger_entry(
            policy["id"],
            entry_kind,
            -case["return_premium_cents"],
            case["scheduled_effective_date"],
            cancellation_case_id=case["id"],
        )
        bump_report(profile["id"], case["scheduled_effective_date"][:7], "cancellation_count")


def sweep_policy_expiry():
    for policy in list(db.policies.values()):
        if policy["status"] != "NONRENEWAL_PENDING":
            continue
        term_end = date.fromisoformat(policy["term_end_date"])
        if clock.today() < term_end:
            continue
        case = None
        for c in db.nonrenewal_cases.values():
            if c["policy_id"] == policy["id"] and c["status"] == "NOTICE_SENT":
                case = c
                break
        if case is None:
            continue
        profile = policy_profile(policy)

        case["status"] = "COMPLETED"
        util.touch(case)

        policy["status"] = "EXPIRED"
        util.touch(policy)

        bump_report(profile["id"], policy["term_end_date"][:7], "nonrenewal_count")


def sweep_reinstatement_expiry():
    for req in list(db.reinstatement_requests.values()):
        if req["status"] != "SUBMITTED":
            continue
        policy = db.policies[req["policy_id"]]
        if policy["status"] != "CANCELLED" or not policy["cancellation_effective_date"]:
            continue
        profile = policy_profile(policy)
        cancel_date = date.fromisoformat(policy["cancellation_effective_date"])
        deadline = cancel_date + timedelta(days=profile["reinstatement_window_days"])
        if clock.today() > deadline:
            req["status"] = "EXPIRED"
            util.touch(req)


def sweep_lapse_flags():
    for policy in list(db.policies.values()):
        if policy["status"] != "CANCELLED" or not policy["cancellation_effective_date"]:
            continue
        cancel_date = date.fromisoformat(policy["cancellation_effective_date"])
        elapsed = (clock.today() - cancel_date).days
        should_flag = elapsed > LAPSE_THRESHOLD_DAYS
        if policy["lapse_flag"] != should_flag:
            policy["lapse_flag"] = should_flag
            util.touch(policy)


def run_sweeps():
    sweep_cancellation_effectiveness()
    sweep_policy_expiry()
    sweep_reinstatement_expiry()
    sweep_lapse_flags()
