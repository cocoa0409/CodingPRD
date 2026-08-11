"""Calculation rules (SCAFFOLD calculations table)."""

from datetime import datetime, timezone

from db import stores, now_dt, parse_date


MEDICARE_KINDS = ("MEDICARE_PART_A", "MEDICARE_PART_B", "MEDICARE_ADVANTAGE")


def _months_after(date_obj, months):
    """Add N months to a date. Clamp day to month length."""
    y = date_obj.year
    m = date_obj.month + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    # days in month
    if m == 12:
        next_first = datetime(y + 1, 1, 1).date()
    else:
        next_first = datetime(y, m + 1, 1).date()
    first = datetime(y, m, 1).date()
    dim = (next_first - first).days
    d = min(date_obj.day, dim)
    return datetime(y, m, d).date()


def msp_determination(q, config):
    """msp_determination calculation. Returns MEDICARE_PRIMARY | MEDICARE_SECONDARY | MSP_EXEMPT."""
    now = now_dt().date()
    threshold = config["msp_employer_size_threshold"]
    coord_months = config["esrd_coordination_months"]

    has_group = bool(q.get("has_employer_group_health"))
    esrd_flag = bool(q.get("esrd_flag"))
    esrd_onset = q.get("esrd_onset_date")
    is_65 = bool(q.get("is_age_65_plus"))
    disability = bool(q.get("disability_flag"))
    employer_size = q.get("employer_size") or 0

    # 1. No group plan -> MEDICARE_PRIMARY
    if not has_group:
        return "MEDICARE_PRIMARY"
    # 2/3. ESRD window
    if esrd_flag and esrd_onset:
        onset = parse_date(esrd_onset)
        coord_end = _months_after(onset, coord_months)
        if coord_end > now:
            return "MEDICARE_SECONDARY"
        return "MEDICARE_PRIMARY"
    # 4/5. Age-based
    if is_65:
        if employer_size >= threshold:
            return "MEDICARE_SECONDARY"
        return "MEDICARE_PRIMARY"
    # 6. Disability-based
    if disability and employer_size >= threshold:
        return "MEDICARE_SECONDARY"
    # 7.
    return "MSP_EXEMPT"


def active_config():
    for c in stores["rule_configs"].values():
        if c.get("status") == "ACTIVE":
            return c
    return None


def in_scope_coverages(member_id, as_of_service_date):
    """VERIFIED coverages active on as_of_service_date."""
    svc = parse_date(as_of_service_date)
    out = []
    for cov in stores["coverages"].values():
        if cov["member_id"] != member_id:
            continue
        if cov.get("verification_status") != "VERIFIED":
            continue
        ef = parse_date(cov["effective_from"])
        et = parse_date(cov["effective_to"]) if cov.get("effective_to") else None
        if ef <= svc and (et is None or et >= svc):
            out.append(cov)
    return out


def _birthday_key(cov):
    dob = cov.get("policy_holder_dob")
    if dob:
        try:
            d = parse_date(dob)
            md = (d.month, d.day)
            year = d.year
        except Exception:
            md = (12, 31)
            year = 9999
    else:
        md = (12, 31)
        year = 9999
    return (md, year, cov.get("created_at", ""), cov.get("id", ""))


def primacy_rule_selection(member, in_scope, questionnaire, config):
    """primacy_rule_selection calculation.

    Returns (deciding_rule, ordered_coverages_list).
    """
    if len(in_scope) == 0:
        return ("NONE", [])
    if len(in_scope) == 1:
        return ("NONE", list(in_scope))

    relation = member.get("relation_to_subscriber")

    # 1. CUSTODIAL_DECREE
    if relation == "CHILD" and member.get("custodial_decree_on_file"):
        parent_covs = [c for c in in_scope if c.get("subscriber_relationship") == "PARENT"]
        if len(parent_covs) >= 2:
            # Cannot know the decree's designated parent; fall back to BIRTHDAY_RULE
            ordered = sorted(parent_covs, key=_birthday_key)
            rest = [c for c in in_scope if c not in parent_covs]
            ordered.extend(rest)
            return ("BIRTHDAY_RULE", ordered)
        # fall back to BIRTHDAY_RULE on full set
        ordered = sorted(in_scope, key=_birthday_key)
        return ("BIRTHDAY_RULE", ordered)

    # 2. MEDICARE_MSP
    medicare_covs = [c for c in in_scope if c.get("coverage_kind", "").startswith("MEDICARE_")]
    if medicare_covs and questionnaire is not None:
        result = questionnaire.get("msp_result")
        group_covs = [c for c in in_scope if c.get("coverage_kind") == "GROUP_HEALTH"]
        others = [c for c in in_scope if c not in medicare_covs and c not in group_covs]
        if result == "MEDICARE_PRIMARY":
            ordered = medicare_covs + group_covs + others
        elif result == "MEDICARE_SECONDARY":
            ordered = group_covs + medicare_covs + others
        else:  # MSP_EXEMPT
            ordered = medicare_covs + group_covs + others
        return ("MEDICARE_MSP", ordered)

    # 3. ACTIVE_VS_RETIRED
    active_group = [c for c in in_scope
                    if c.get("coverage_kind") == "GROUP_HEALTH"
                    and member.get("employment_status") == "ACTIVE"]
    retired_group = [c for c in in_scope
                     if c.get("coverage_kind") == "GROUP_HEALTH"
                     and member.get("employment_status") in ("RETIRED", "COBRA")]
    if active_group and retired_group:
        rest = [c for c in in_scope if c not in active_group and c not in retired_group]
        ordered = active_group + retired_group + rest
        return ("ACTIVE_VS_RETIRED", ordered)

    # 4/5. Dependent-child rules
    if relation == "CHILD":
        parent_covs = [c for c in in_scope if c.get("subscriber_relationship") == "PARENT"]
        if len(parent_covs) >= 2:
            dep_rule = config.get("dependent_primacy_rule") if config else "BIRTHDAY_RULE"
            rest = [c for c in in_scope if c not in parent_covs]
            if dep_rule == "GENDER_RULE":
                male = [c for c in parent_covs if c.get("policy_holder_gender") == "MALE"]
                nonmale = [c for c in parent_covs if c.get("policy_holder_gender") != "MALE"]
                ordered = male + nonmale + rest
                return ("GENDER_RULE", ordered)
            ordered = sorted(parent_covs, key=_birthday_key)
            ordered.extend(rest)
            return ("BIRTHDAY_RULE", ordered)

    # 6. LONGER_ENROLLMENT
    if relation == "SELF":
        ordered = sorted(
            in_scope,
            key=lambda c: (c.get("effective_from", ""), c.get("created_at", ""), c.get("id", "")),
        )
        return ("LONGER_ENROLLMENT", ordered)

    # Default: order by created_at for determinism
    ordered = sorted(in_scope, key=lambda c: (c.get("created_at", ""), c.get("id", "")))
    return ("NONE", ordered)


def line_paid_primary(line):
    """primary_payment_calculation per line."""
    return min(line["allowed_cents"], line["billed_cents"])


def line_paid_secondary(line):
    """secondary_payment_calculation per line."""
    base = min(line["allowed_cents"], line["billed_cents"])
    return max(0, base - (line.get("primary_paid_cents") or 0))


def compute_claim_payment(claim, primary_is_ours):
    """Compute per-line paid_cents and claim totals."""
    lines = [l for l in stores["claim_lines"].values() if l["claim_id"] == claim["id"]]
    lines.sort(key=lambda l: l.get("line_number", 0))
    total_allowed = 0
    total_paid = 0
    total_primary = 0
    for line in lines:
        if primary_is_ours:
            paid = line_paid_primary(line)
        else:
            paid = line_paid_secondary(line)
        line["paid_cents"] = paid
        total_allowed += line["allowed_cents"]
        total_paid += paid
        total_primary += line.get("primary_paid_cents") or 0
    claim["total_allowed_cents"] = total_allowed
    claim["total_paid_cents"] = total_paid
    claim["total_primary_paid_cents"] = 0 if primary_is_ours else total_primary


def primary_is_ours_for_determination(det):
    """True when ordered_coverage_ids[0] is OUR_PLAN coverage."""
    ids = det.get("ordered_coverage_ids") or []
    if not ids:
        return True  # no coverages -> treat as primary (our plan pays)
    first = stores["coverages"].get(ids[0])
    if first is None:
        return True
    return first.get("coverage_kind") == "OUR_PLAN"


def savings_period_aggregation(period):
    """savings_period_aggregation calculation. Returns the three totals."""
    start = parse_date(period["period_start_date"])
    end = parse_date(period["period_end_date"])

    total_avoided = 0
    for claim in stores["claims"].values():
        det_id = claim.get("primacy_determination_id")
        if not det_id:
            continue
        det = stores["determinations"].get(det_id)
        if det is None:
            continue
        if primary_is_ours_for_determination(det):
            continue  # only secondary-position claims
        svc = parse_date(claim["service_date"])
        if not (start <= svc <= end):
            continue
        for line in stores["claim_lines"].values():
            if line["claim_id"] != claim["id"]:
                continue
            total_avoided += line["allowed_cents"] - (line.get("paid_cents") or 0)

    total_recovered = 0
    for r in stores["reimbursements"].values():
        rcv = parse_date(r["received_at"])
        if start <= rcv <= end:
            total_recovered += r["amount_cents"]

    total_adjusted = 0
    for a in stores["adjustments"].values():
        if a.get("status") != "APPLIED":
            continue
        upd = parse_date(a["updated_at"])
        if start <= upd <= end:
            total_adjusted += 1

    return {
        "total_avoided_cents": total_avoided,
        "total_recovered_cents": total_recovered,
        "total_claims_adjusted": total_adjusted,
    }
