"""The thirteen pinned calculations (§3) plus the derived-field recomputers."""
from decimal import Decimal

from common import (ACCEPT_NO_CHANGE_SEVERITY_CEILING, BASE_SLA_HOURS,
                    DISCLOSURE_PASS_THRESHOLD, EXPEDITE_CREDITS_PER_WINDOW,
                    MIN_SCREENSHOTS_PER_CLASS, PHASE_PCTS,
                    POSTURE_INDEX_FLOOR, PROVISIONAL_CONFIDENCE_FLOOR,
                    RATING_BANDS, ROLLING_WINDOW_DAYS, d2, d4, days, get_row,
                    hours, now_dt, rows, touch)

# --------------------------------------------------------------------------
# Static weight tables
# --------------------------------------------------------------------------
SEVERITY_WEIGHTS = {"SAFETY": 5, "PRIVACY": 4, "COMMERCE": 3, "LEGAL": 3,
                    "DESIGN": 1}
GRACE_DAYS = {"SAFETY": 14, "PRIVACY": 30, "COMMERCE": 45, "LEGAL": 30,
              "DESIGN": 60}
MAPPING_FACTOR = {
    "PASSED": Decimal("1.0"), "WAIVED_BY_PLATFORM": Decimal("1.0"),
    "STALE": Decimal("0.5"), "IN_PROGRESS": Decimal("0.25"),
    "NOT_STARTED": Decimal("0.0"), "FAILED": Decimal("0.0"),
}
DISCLOSURE_PENALTY = {"CRITICAL": 40, "MAJOR": 20, "MINOR": 5}
OVER_DISCLOSURE_PENALTY = 2
STANDING_PENALTY = {"CRITICAL": 12, "MAJOR": 6, "MINOR": 2}
STANDING_APPEAL_CREDIT = 3
STANDING_CLEAN_ROLLOUT_CREDIT = 2
SLA_HOURS_BY_BAND = {"EXPEDITED": 12, "HIGH": 24, "NORMAL": 48, "LOW": 96}
DIM_BAND = {0: 0, 1: 9, 2: 12, 3: 17}
DIMENSIONS = ["violence", "sexual_content", "drugs_alcohol",
              "gambling_simulated", "horror", "profanity"]
DIMENSION_LABELS = {
    "violence": "VIOLENCE",
    "sexual_content": "SEXUAL_CONTENT",
    "drugs_alcohol": "DRUGS_ALCOHOL",
    "gambling_simulated": "GAMBLING_SIMULATED",
    "horror": "HORROR",
    "profanity": "PROFANITY",
}
RATING_BOOLEANS = ["unrestricted_web_access", "user_generated_content",
                   "ugc_moderation_enabled", "real_money_gambling", "contests"]
RESERVED_STATES = ["WAITING_FOR_REVIEW", "IN_REVIEW"]
CONSUMED_STATES = ["APPROVED", "REJECTED", "METADATA_REJECTED",
                   "APPEAL_PENDING", "REJECTED_FINAL", "SUPERSEDED"]

# --------------------------------------------------------------------------
# Row navigation helpers
# --------------------------------------------------------------------------


def account_of_app(app):
    return get_row("publisher_account", app["publisher_account_id"])


def app_of(row):
    return get_row("app_record", row.get("app_record_id"))


def submissions_of_app(app_id):
    return [s for s in rows("submission") if s["app_record_id"] == app_id]


def mappings_of_app(app_id):
    return [m for m in rows("feature_mapping") if m["app_record_id"] == app_id]


def assessments_of_app(app_id):
    return [a for a in rows("impact_assessment") if a["app_record_id"] == app_id]


def findings_of_submission(sub_id):
    return [f for f in rows("behavior_finding") if f["submission_id"] == sub_id]


def findings_of_app(app_id):
    ids = {s["id"] for s in submissions_of_app(app_id)}
    return [f for f in rows("behavior_finding") if f["submission_id"] in ids]


def plans_of_app(app_id):
    return [p for p in rows("rollout_plan") if p["app_record_id"] == app_id]


def apps_of_account(account_id):
    return [a for a in rows("app_record")
            if a["publisher_account_id"] == account_id]


def submissions_of_account(account_id):
    app_ids = {a["id"] for a in apps_of_account(account_id)}
    return [s for s in rows("submission") if s["app_record_id"] in app_ids]


def credentials_of_account(account_id):
    return [c for c in rows("signing_credential")
            if c["publisher_account_id"] == account_id]


# --------------------------------------------------------------------------
# feature_compliance_index (§3.4)
# --------------------------------------------------------------------------
def feature_compliance_index(app):
    earned = Decimal("0")
    total = Decimal("0")
    any_row = False
    for m in mappings_of_app(app["id"]):
        rule = get_row("guideline_rule", m["guideline_rule_id"])
        if rule is None or rule["status"] != "EFFECTIVE":
            continue
        any_row = True
        weight = Decimal(str(m.get("risk_weight") or 0))
        earned += weight * MAPPING_FACTOR[m["self_review_status"]]
        total += weight
    if not any_row or total == 0:
        return d2("0")
    return d2(Decimal("100") * earned / total)


def active_distribution_cert_present(app):
    for c in credentials_of_account(app["publisher_account_id"]):
        if (c["credential_type"] == "DISTRIBUTION_CERT"
                and c["platform"] == app["platform"]
                and c["status"] in ("ACTIVE", "EXPIRING_SOON")):
            return True
    return False


# --------------------------------------------------------------------------
# compliance_posture (§2.8)
# --------------------------------------------------------------------------
def compliance_posture(app, index):
    account = account_of_app(app)
    frozen = []
    if account is not None and account["program_status"] in ("SUSPENDED", "TERMINATED"):
        frozen.append("ACCOUNT_NOT_IN_GOOD_STANDING")
    if any(a["status"] == "OVERDUE" for a in assessments_of_app(app["id"])):
        frozen.append("IMPACT_OVERDUE")
    if any(f["severity"] == "CRITICAL" and f["status"] in ("OPEN", "DISPUTED")
           for f in findings_of_app(app["id"])):
        frozen.append("CRITICAL_FINDING_OPEN")
    if frozen:
        return "FROZEN", frozen
    restricted = []
    if account is not None and account["program_status"] == "EXPIRED":
        restricted.append("MEMBERSHIP_EXPIRED")
    if not active_distribution_cert_present(app):
        restricted.append("NO_ACTIVE_DISTRIBUTION_CERT")
    if index < POSTURE_INDEX_FLOOR:
        restricted.append("COMPLIANCE_INDEX_BELOW_FLOOR")
    if any(a["status"] in ("OPEN", "IN_ASSESSMENT", "REMEDIATION_REQUIRED")
           for a in assessments_of_app(app["id"])):
        restricted.append("OPEN_IMPACT_ASSESSMENT")
    if restricted:
        return "RESTRICTED", restricted
    return "OPEN", []


def recompute_app_posture(app, bump=True):
    """Recompute index + posture; advance version only when something changed."""
    index = feature_compliance_index(app)
    posture, codes = compliance_posture(app, index)
    changed = (app.get("feature_compliance_index") != index
               or app.get("compliance_posture") != posture
               or app.get("posture_reason_codes") != codes)
    app["feature_compliance_index"] = index
    app["compliance_posture"] = posture
    app["posture_reason_codes"] = codes
    if changed and bump:
        touch(app)
    return changed


# --------------------------------------------------------------------------
# disclosure_accuracy_score (§3.7) — two deliberately divergent variants
# --------------------------------------------------------------------------
def _matched(declared, finding):
    for d in declared:
        if not isinstance(d, dict):
            continue
        if (d.get("data_type") == finding["data_type"]
                and d.get("purpose") == finding["observed_purpose"]
                and bool(d.get("linked_to_user")) == bool(finding["observed_linked_to_user"])
                and bool(d.get("used_for_tracking")) == bool(finding["observed_tracking"])):
            return True
    return False


def _disclosure_score(submission, scope, apply_over_disclosure):
    declared = submission.get("declared_privacy_items") or []
    penalty = 0
    for f in scope:
        if not _matched(declared, f):
            penalty += DISCLOSURE_PENALTY[f["severity"]]
    over = 0
    if apply_over_disclosure:
        scoped_types = {f["data_type"] for f in scope}
        for d in declared:
            if isinstance(d, dict) and d.get("data_type") not in scoped_types:
                over += 1
    raw = 100 - penalty - (OVER_DISCLOSURE_PENALTY * over if apply_over_disclosure else 0)
    if raw < 0:
        raw = 0
    return d4(Decimal(raw) / Decimal(100))


def provisional_scope(submission):
    checked = submission.get("pre_review_checked_at")
    if checked is None:
        return []
    from common import parse_iso
    limit = parse_iso(checked)
    out = []
    for f in findings_of_submission(submission["id"]):
        if f["status"] != "OPEN":
            continue
        if parse_iso(f["detected_at"]) > limit:
            continue
        if Decimal(str(f["scanner_confidence"])) < PROVISIONAL_CONFIDENCE_FLOOR:
            continue
        out.append(f)
    return out


def final_scope(submission):
    return [f for f in findings_of_submission(submission["id"])
            if f["status"] in ("OPEN", "DISPUTED")]


def recompute_provisional_score(submission, bump=True):
    value = _disclosure_score(submission, provisional_scope(submission), False)
    if submission.get("disclosure_accuracy_score_provisional") != value:
        submission["disclosure_accuracy_score_provisional"] = value
        if bump:
            touch(submission)
        return True
    return False


def recompute_final_score(submission, bump=True):
    value = _disclosure_score(submission, final_scope(submission), True)
    if submission.get("disclosure_accuracy_score_final") != value:
        submission["disclosure_accuracy_score_final"] = value
        if bump:
            touch(submission)
        return True
    return False


# --------------------------------------------------------------------------
# derived_age_rating (§3.7)
# --------------------------------------------------------------------------
def derived_age_rating(answers):
    bands = [DIM_BAND[int(answers[d])] for d in DIMENSIONS]
    base = max(bands)
    driving = None
    for name, band in zip(DIMENSIONS, bands):
        if band == base:
            driving = DIMENSION_LABELS[name]
            break
    if answers.get("real_money_gambling"):
        floor_age = 18
    elif (answers.get("unrestricted_web_access")
          or (answers.get("user_generated_content")
              and not answers.get("ugc_moderation_enabled"))):
        floor_age = 17
    elif answers.get("contests"):
        floor_age = 12
    else:
        floor_age = 0
    raw = max(base, floor_age)
    if int(answers["gambling_simulated"]) >= 2:
        raw = max(raw, 17)
    rating = None
    for band in RATING_BANDS:
        if band >= raw:
            rating = band
            break
    if rating is None:
        rating = RATING_BANDS[-1]
    dimension = "FLOOR_RULE" if floor_age > base else driving
    return rating, dimension


# --------------------------------------------------------------------------
# standing_score (§3.9) — ROLLING_365 and LIFETIME_UNDECAYED
# --------------------------------------------------------------------------
def _penalty_rows(account_id):
    sub_ids = {s["id"] for s in submissions_of_account(account_id)}
    return [r for r in rows("rejection_reason")
            if r["submission_id"] in sub_ids
            and r["appeal_disposition"] != "OVERTURNED"]


def _age_days(instant, now):
    from common import parse_iso
    delta = now - parse_iso(instant)
    return delta.days if delta.days >= 0 else -((-delta).days)


def _in_window(instant, lower):
    from common import parse_iso
    if instant is None:
        return False
    if lower is None:
        return True
    return parse_iso(instant) >= lower


def standing_details(account):
    now = now_dt()
    lower = now - days(ROLLING_WINDOW_DAYS)
    penalties = _penalty_rows(account["id"])
    decayed = Decimal("0")
    undecayed = Decimal("0")
    event_count = 0
    strikes = 0
    for r in penalties:
        weight = Decimal(STANDING_PENALTY[r["severity"]])
        undecayed += weight
        if _in_window(r["recorded_at"], lower):
            event_count += 1
            age = _age_days(r["recorded_at"], now)
            if age <= 90:
                factor = Decimal("1.0")
            elif age <= 180:
                factor = Decimal("0.5")
            else:
                factor = Decimal("0.25")
            decayed += weight * factor
            if r["severity"] == "CRITICAL":
                strikes += 1
    sub_ids = {s["id"] for s in submissions_of_account(account["id"])}
    appeals = [a for a in rows("appeal_request")
               if a["submission_id"] in sub_ids
               and a["state"] in ("OVERTURNED", "PARTIALLY_OVERTURNED")]
    app_ids = {a["id"]: a for a in apps_of_account(account["id"])}
    plans = [p for p in rows("rollout_plan")
             if p["app_record_id"] in app_ids and p["state"] == "COMPLETED"
             and app_ids[p["app_record_id"]]["rollback_count"] == 0]
    credit_rolling = Decimal("0")
    credit_lifetime = Decimal("0")
    for a in appeals:
        credit_lifetime += STANDING_APPEAL_CREDIT
        if _in_window(a["decided_at"], lower):
            credit_rolling += STANDING_APPEAL_CREDIT
    for p in plans:
        credit_lifetime += STANDING_CLEAN_ROLLOUT_CREDIT
        if _in_window(p["completed_at"], lower):
            credit_rolling += STANDING_CLEAN_ROLLOUT_CREDIT
    rolling = _clamp_score(Decimal("100") - decayed + credit_rolling)
    lifetime = _clamp_score(Decimal("100") - undecayed + credit_lifetime)
    used, remaining = expedite_ledger(account)
    return {
        "standing_score_rolling_365": rolling,
        "standing_score_lifetime": lifetime,
        "expedite_credits_remaining": remaining,
        "credits_used_in_window": used,
        "rejection_strike_count": strikes,
        "penalty_event_count": event_count,
        "decayed_penalty_total": d2(decayed),
        "undecayed_penalty_total": d2(undecayed),
        "credit_total": d2(credit_rolling),
    }


def _clamp_score(value):
    value = d2(value)
    if value < Decimal("0.00"):
        return d2("0")
    if value > Decimal("100.00"):
        return d2("100")
    return value


def expedite_ledger(account):
    now = now_dt()
    lower = now - days(ROLLING_WINDOW_DAYS)
    used = 0
    for e in rows("expedite_request"):
        if e["publisher_account_id"] != account["id"]:
            continue
        if e["state"] not in ("GRANTED", "CONSUMED"):
            continue
        if _in_window(e.get("granted_at"), lower):
            used += 1
    remaining = EXPEDITE_CREDITS_PER_WINDOW - used
    return used, remaining


def recompute_account_standing(account, bump=True):
    details = standing_details(account)
    changed = False
    for field in ("standing_score_rolling_365", "standing_score_lifetime",
                  "expedite_credits_remaining", "rejection_strike_count"):
        if account.get(field) != details[field]:
            account[field] = details[field]
            changed = True
    if changed and bump:
        touch(account)
    return changed


# --------------------------------------------------------------------------
# review_capacity_allocation (§3.8)
# --------------------------------------------------------------------------
def window_counters(window):
    reserved = 0
    consumed = 0
    for s in rows("submission"):
        if s.get("review_window_id") != window["id"]:
            continue
        if s["state"] in RESERVED_STATES:
            reserved += 1
        elif s["state"] in CONSUMED_STATES:
            consumed += 1
    available = window["capacity_slots"] - reserved - consumed
    return reserved, consumed, available


def sync_window(window, bump=True):
    reserved, consumed, available = window_counters(window)
    changed = (window.get("slots_reserved") != reserved
               or window.get("slots_consumed") != consumed
               or window.get("slots_available") != available)
    window["slots_reserved"] = reserved
    window["slots_consumed"] = consumed
    window["slots_available"] = available
    if changed and bump:
        touch(window)
    return changed


def sync_all_windows(bump=False):
    for w in rows("review_capacity_window"):
        sync_window(w, bump=bump)


def select_capacity_window(app):
    now = now_dt()
    from common import parse_iso
    eligible = []
    for w in rows("review_capacity_window"):
        if w["status"] != "OPEN" or w["platform"] != app["platform"]:
            continue
        if not (parse_iso(w["starts_at"]) <= now < parse_iso(w["ends_at"])):
            continue
        reserved, consumed, available = window_counters(w)
        if available < 1:
            continue
        eligible.append((available, w))
    if not eligible:
        return None
    eligible.sort(key=lambda pair: (-pair[0], parse_iso(pair[1]["starts_at"]),
                                    pair[1]["created_at"], pair[1]["_seq"]))
    return eligible[0][1]


# --------------------------------------------------------------------------
# review_priority_score (§3.8) — single forward pass, steps 1..6
# --------------------------------------------------------------------------
def priority_pass(submission, account, first_time=False):
    from common import fmt_iso, parse_iso
    now = now_dt()
    if first_time:
        submission["queued_at"] = fmt_iso(now)
        submission["provisional_deadline_at"] = fmt_iso(now + hours(BASE_SLA_HOURS))
    queued_at = parse_iso(submission["queued_at"])
    provisional = parse_iso(submission["provisional_deadline_at"])
    hours_remaining = (Decimal((provisional - now).total_seconds())
                       / Decimal(3600))
    pressure = (Decimal(BASE_SLA_HOURS) - hours_remaining) / Decimal(BASE_SLA_HOURS)
    if pressure < Decimal("0"):
        pressure = Decimal("0")
    if pressure > Decimal("1"):
        pressure = Decimal("1")
    standing_component = Decimal(str(account["standing_score_lifetime"]))
    urgency_component = Decimal("100") * pressure
    provisional_score = submission.get("disclosure_accuracy_score_provisional")
    if provisional_score is None:
        provisional_score = Decimal("1.0000")
    risk_component = Decimal("100") * (Decimal("1") - Decimal(str(provisional_score)))
    score = _clamp_score(Decimal("0.50") * standing_component
                         + Decimal("0.30") * urgency_component
                         - Decimal("0.20") * risk_component)
    if submission.get("submission_channel") == "EXPEDITED":
        band = "EXPEDITED"
    elif score >= Decimal("70.00"):
        band = "HIGH"
    elif score >= Decimal("40.00"):
        band = "NORMAL"
    else:
        band = "LOW"
    submission["priority_score"] = score
    submission["priority_band"] = band
    submission["effective_review_deadline_at"] = fmt_iso(
        queued_at + hours(SLA_HOURS_BY_BAND[band]))
    return score, band


# --------------------------------------------------------------------------
# impact_severity (§3.5)
# --------------------------------------------------------------------------
def exposure_factor(app):
    if app["distribution_state"] in ("PHASED_ROLLOUT", "FULLY_RELEASED", "PAUSED"):
        return Decimal("1.5")
    return Decimal("1.0")


def impact_severity(rule, affected_codes, app):
    factor = exposure_factor(app)
    return d2(Decimal(rule["severity_weight"]) * Decimal(len(affected_codes))
              * factor), factor


def remediation_deadline(rule):
    from common import fmt_iso, parse_iso
    return fmt_iso(parse_iso(rule["effective_from"])
                   + hours(24 * rule["remediation_grace_days"]))


# --------------------------------------------------------------------------
# commission_settlement_cents (§3.11)
# --------------------------------------------------------------------------
def commission_rate(account, item):
    base = (Decimal("0.15") if account["commerce_program_tier"] == "SMALL_BUSINESS"
            else Decimal("0.30"))
    rate = base
    if (item["item_type"] == "SUBSCRIPTION"
            and (item.get("subscriber_retention_months") or 0) >= 12):
        rate = min(rate, Decimal("0.15"))
    if item["item_type"] == "EXTERNAL_PAYMENT_LINK":
        rate = d2(rate - Decimal("0.03"))
    return d2(rate)


def recompute_commission(item, account):
    from common import cents
    rate = commission_rate(account, item)
    amount = cents(Decimal(item.get("reported_gross_cents") or 0) * rate)
    changed = (item.get("commission_rate_applied") != rate
               or item.get("commission_cents") != amount)
    item["commission_rate_applied"] = rate
    item["commission_cents"] = amount
    return changed


def settlement(app, period_label):
    from common import cents
    account = account_of_app(app)
    lines = []
    gross_total = 0
    commission_total = 0
    for item in rows("commerce_item"):
        if item["app_record_id"] != app["id"]:
            continue
        if item["status"] != "APPROVED":
            continue
        if item.get("reported_period_label") != period_label:
            continue
        rate = commission_rate(account, item)
        gross = item.get("reported_gross_cents") or 0
        amount = cents(Decimal(gross) * rate)
        gross_total += gross
        commission_total += amount
        lines.append({
            "commerce_item_id": item["id"],
            "reference_name": item["reference_name"],
            "item_type": item["item_type"],
            "reported_gross_cents": gross,
            "commission_rate_applied": rate,
            "commission_cents": amount,
        })
    return {
        "period_label": period_label,
        "line_count": len(lines),
        "gross_cents_total": gross_total,
        "commission_cents_total": commission_total,
        "net_cents_total": gross_total - commission_total,
        "lines": lines,
    }


# --------------------------------------------------------------------------
# MetadataLocale derivations (§3.6)
# --------------------------------------------------------------------------
REQUIRED_CLASSES = {"IOS": ["PHONE_65", "TABLET_129"], "ANDROID": ["PHONE_65"]}


def required_device_classes(platform):
    return list(REQUIRED_CLASSES.get(platform, ["PHONE_65"]))


def locale_is_complete(locale, platform):
    if not locale.get("title"):
        return False
    counts = locale.get("screenshot_counts") or {}
    for cls in required_device_classes(platform):
        value = counts.get(cls)
        if not isinstance(value, int) or isinstance(value, bool):
            return False
        if value < MIN_SCREENSHOTS_PER_CLASS:
            return False
    return True


# --------------------------------------------------------------------------
# rollout_audience_allocation (§3.10)
# --------------------------------------------------------------------------
def share_pair(phase_index):
    released = d2(PHASE_PCTS[phase_index])
    return released, d2(Decimal("100.00") - released)


def zero_share():
    return d2("0"), d2("100")
