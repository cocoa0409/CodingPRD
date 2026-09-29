"""Derived-state engine, cascades and cross-entity helpers."""
from decimal import Decimal

import calcs
import store
from errors import ApiError
from store import DB

# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------


def engagement_of_control(control):
    return DB["engagements"].get(control["engagement_id"])


def controls_of(engagement_id):
    return [c for c in store.rows("controls") if c["engagement_id"] == engagement_id]


def gaps_of(engagement_id):
    return [g for g in store.rows("gaps") if g["engagement_id"] == engagement_id]


def mappings_of_control(control_id):
    return [m for m in store.rows("criteria_mappings") if m["control_id"] == control_id]


def evidence_of_control(control_id):
    return [e for e in store.rows("evidence_requests") if e["control_id"] == control_id]


def samples_of_control(control_id):
    return [s for s in store.rows("audit_samples") if s["control_id"] == control_id]


def exceptions_of_sample(sample_id):
    return [e for e in store.rows("audit_exceptions") if e["audit_sample_id"] == sample_id]


def exceptions_of_engagement(engagement_id):
    out = []
    for exc in store.rows("audit_exceptions"):
        control = DB["controls"].get(exc["control_id"])
        if control is not None and control["engagement_id"] == engagement_id:
            out.append(exc)
    return out


def evidence_of_engagement(engagement_id):
    out = []
    for req in store.rows("evidence_requests"):
        control = DB["controls"].get(req["control_id"])
        if control is not None and control["engagement_id"] == engagement_id:
            out.append(req)
    return out


def engagement_of(row, kind):
    """Resolve the owning engagement for any row."""
    if kind == "engagement":
        return row
    if kind == "control":
        return DB["engagements"].get(row["engagement_id"])
    if kind in ("system_description", "gap", "subservice_organization", "cuec",
                "report_distribution", "bridge_letter", "customer_questionnaire"):
        return DB["engagements"].get(row["engagement_id"])
    if kind == "boundary_component":
        sd = DB["system_descriptions"].get(row["system_description_id"])
        return DB["engagements"].get(sd["engagement_id"]) if sd else None
    if kind in ("criteria_mapping", "evidence_request", "audit_sample", "audit_exception"):
        control = DB["controls"].get(row["control_id"])
        return DB["engagements"].get(control["engagement_id"]) if control else None
    return None


# --------------------------------------------------------------------------
# criteria coverage (PRD 3.3)
# --------------------------------------------------------------------------


def in_scope_criteria(engagement):
    out = [
        c
        for c in DB["trust_criteria"].values()
        if c["category"] in engagement["required_criteria_categories"]
        and engagement["report_type"] in c["applies_to_report_types"]
    ]
    out.sort(key=lambda c: (c["criterion_code"], c["_seq"]))
    return out


def _active_mappings_for_criterion(criterion_id):
    return [
        m
        for m in DB["criteria_mappings"].values()
        if m["status"] == "ACTIVE" and m["trust_criterion_id"] == criterion_id
    ]


def covered_readiness(engagement, criterion):
    for m in _active_mappings_for_criterion(criterion["id"]):
        control = DB["controls"].get(m["control_id"])
        if control is None:
            continue
        if control["engagement_id"] != engagement["id"]:
            continue
        if not control["in_scope"]:
            continue
        if control["design_status"] in ("DESIGN_MAPPED", "DESIGN_APPROVED"):
            return True
    return False


def covered_attestation(engagement, criterion):
    count = 0
    for m in _active_mappings_for_criterion(criterion["id"]):
        if m["mapping_type"] != "PRIMARY":
            continue
        control = DB["controls"].get(m["control_id"])
        if control is None:
            continue
        if control["engagement_id"] != engagement["id"]:
            continue
        if not control["in_scope"]:
            continue
        if control["design_status"] != "DESIGN_APPROVED":
            continue
        if control["operating_status"] != "TESTED_EFFECTIVE":
            continue
        count += 1
    return count >= criterion["min_primary_controls"]


def readiness_covered_ids(engagement):
    return {c["id"] for c in in_scope_criteria(engagement) if covered_readiness(engagement, c)}


def refresh_coverage(engagement):
    criteria = in_scope_criteria(engagement)
    total = len(criteria)
    cov_r = 0
    cov_a = 0
    covered_flags = {}
    for c in criteria:
        flag = covered_readiness(engagement, c)
        covered_flags[c["id"]] = flag
        if flag:
            cov_r += 1
        if covered_attestation(engagement, c):
            cov_a += 1
    engagement["criteria_in_scope_count"] = total
    engagement["covered_criteria_count_readiness"] = cov_r
    engagement["covered_criteria_count_attestation"] = cov_a
    if total == 0:
        engagement["criteria_coverage_pct_readiness"] = 0.0
        engagement["criteria_coverage_pct_attestation"] = 0.0
    else:
        engagement["criteria_coverage_pct_readiness"] = store.num2(
            Decimal(100) * Decimal(cov_r) / Decimal(total)
        )
        engagement["criteria_coverage_pct_attestation"] = store.num2(
            Decimal(100) * Decimal(cov_a) / Decimal(total)
        )
    _refresh_readiness_score(engagement, criteria, covered_flags)
    return engagement


def _refresh_readiness_score(engagement, criteria, covered_flags):
    categories = sorted(set(engagement["required_criteria_categories"]))
    if not categories:
        engagement["readiness_score"] = 0.0
        return
    total_score = Decimal("0")
    for category in categories:
        members = [c for c in criteria if c["category"] == category]
        total_k = len(members)
        if total_k == 0:
            score_k = Decimal("0.00")
        else:
            covered_k = sum(1 for c in members if covered_flags.get(c["id"]))
            raw = Decimal(100) * Decimal(covered_k) / Decimal(total_k)
            score_k = store.round_half_up(raw, 2)
        total_score += score_k
    engagement["readiness_score"] = store.num2(total_score / Decimal(len(categories)))


# --------------------------------------------------------------------------
# debt and posture (PRD 2.8, 3.5)
# --------------------------------------------------------------------------


def gap_live_points(gap):
    if gap["status"] in calcs.GAP_LIVE_STATUSES:
        return calcs.SEVERITY_POINTS[gap["severity"]]
    return 0


def debt_parts(engagement):
    base = sum(gap_live_points(g) for g in gaps_of(engagement["id"]))
    return calcs.debt_decomposition(base)


def refresh_open_exception_count(engagement):
    count = 0
    for exc in exceptions_of_engagement(engagement["id"]):
        if exc["disposition"] != "VOIDED":
            count += 1
    engagement["open_exception_count"] = count
    return count


def refresh_debt_and_posture(engagement):
    refresh_open_exception_count(engagement)
    base, surcharge, total = debt_parts(engagement)
    engagement["base_debt_points"] = base
    engagement["gap_debt_points"] = float(total)
    engagement["gap_posture"] = compute_posture(engagement, total)
    return engagement


def compute_posture(engagement, total_debt=None):
    if total_debt is None:
        total_debt = Decimal(str(engagement["gap_debt_points"]))
    has_critical_live = any(
        g["severity"] == "CRITICAL" and g["status"] in ("OPEN", "REOPENED")
        for g in gaps_of(engagement["id"])
    )
    exc = engagement["open_exception_count"]
    if (
        has_critical_live
        or total_debt >= calcs.FROZEN_DEBT_THRESHOLD
        or exc >= calcs.FROZEN_EXCEPTION_THRESHOLD
    ):
        return "FROZEN"
    if total_debt >= calcs.RESTRICTED_DEBT_THRESHOLD or exc >= calcs.RESTRICTED_EXCEPTION_THRESHOLD:
        return "RESTRICTED"
    return "OPEN"


def refresh_engagement(engagement):
    if engagement is None:
        return None
    refresh_coverage(engagement)
    refresh_debt_and_posture(engagement)
    return engagement


def open_gap_count(engagement):
    return sum(1 for g in gaps_of(engagement["id"]) if g["status"] in calcs.GAP_LIVE_STATUSES)


# --------------------------------------------------------------------------
# control counters
# --------------------------------------------------------------------------


def refresh_mapping_counts(control):
    active = [m for m in mappings_of_control(control["id"]) if m["status"] == "ACTIVE"]
    control["active_mapping_count"] = len(active)
    control["primary_mapping_count"] = sum(1 for m in active if m["mapping_type"] == "PRIMARY")
    return control


def refresh_tested_item_count(control):
    control["tested_item_count"] = sum(
        s["items_recorded"] for s in samples_of_control(control["id"]) if s["status"] != "VOIDED"
    )
    return control


def refresh_open_gap_count(control):
    control["open_gap_count"] = sum(
        1
        for g in DB["gaps"].values()
        if g["control_id"] == control["id"] and g["status"] in calcs.GAP_LIVE_STATUSES
    )
    return control


def refresh_inclusive_control_count(org):
    org["inclusive_control_count"] = sum(
        1
        for c in DB["controls"].values()
        if c["subservice_organization_id"] == org["id"] and c["in_scope"]
    )
    return org


def refresh_component_counts(system_description):
    comps = [
        b
        for b in DB["boundary_components"].values()
        if b["system_description_id"] == system_description["id"]
    ]
    system_description["in_scope_component_count"] = sum(
        1 for b in comps if b["scope_status"] == "IN_SCOPE"
    )
    system_description["carved_out_component_count"] = sum(
        1 for b in comps if b["scope_status"] == "CARVED_OUT"
    )
    return system_description


# --------------------------------------------------------------------------
# gap synthesis
# --------------------------------------------------------------------------


def create_gap(engagement, source, severity, control_id=None, trust_criterion_id=None,
               audit_exception_id=None, description=None):
    gap = store.new_row(
        "gaps",
        {
            "engagement_id": engagement["id"],
            "control_id": control_id,
            "trust_criterion_id": trust_criterion_id,
            "audit_exception_id": audit_exception_id,
            "source": source,
            "severity": severity,
            "status": "OPEN",
            "remediation_owner_user_id": None,
            "remediation_due_date": None,
            "reopen_count": 0,
            "debt_points": calcs.SEVERITY_POINTS[severity],
            "description": description,
        },
    )
    if control_id:
        control = DB["controls"].get(control_id)
        if control is not None:
            refresh_open_gap_count(control)
    return gap


def set_gap_status(gap, new_status):
    gap["status"] = new_status
    gap["debt_points"] = gap_live_points(gap)
    store.touch(gap)
    if gap["control_id"]:
        control = DB["controls"].get(gap["control_id"])
        if control is not None:
            refresh_open_gap_count(control)
    return gap


# --------------------------------------------------------------------------
# readiness assessment (PRD 3.5)
# --------------------------------------------------------------------------


def run_readiness_assessment(engagement):
    created = 0
    existing = gaps_of(engagement["id"])

    def guarded_control(control_id):
        for g in existing:
            if (
                g["source"] == "READINESS_ASSESSMENT"
                and g["control_id"] == control_id
                and g["status"] not in ("VERIFIED", "WITHDRAWN")
            ):
                return True
        return False

    def guarded_criterion(criterion_id):
        for g in existing:
            if (
                g["source"] == "READINESS_ASSESSMENT"
                and g["trust_criterion_id"] == criterion_id
                and g["status"] not in ("VERIFIED", "WITHDRAWN")
            ):
                return True
        return False

    controls = [c for c in controls_of(engagement["id"]) if c["in_scope"]]
    controls.sort(key=lambda c: (c["control_ref"], c["_seq"]))
    for control in controls:
        if control["primary_mapping_count"] == 0:
            severity = "HIGH"
        elif control["design_status"] != "DESIGN_APPROVED":
            severity = calcs.RISK_SEVERITY[control["risk_rating"]]
        else:
            continue
        if guarded_control(control["id"]):
            continue
        gap = create_gap(engagement, "READINESS_ASSESSMENT", severity, control_id=control["id"])
        existing.append(gap)
        created += 1

    for criterion in in_scope_criteria(engagement):
        if covered_readiness(engagement, criterion):
            continue
        severity = "HIGH" if criterion["category"] == "SECURITY" else "MODERATE"
        if guarded_criterion(criterion["id"]):
            continue
        gap = create_gap(
            engagement, "READINESS_ASSESSMENT", severity, trust_criterion_id=criterion["id"]
        )
        existing.append(gap)
        created += 1

    engagement["readiness_assessed_at"] = store.now_iso()
    return created


# --------------------------------------------------------------------------
# audit sample cascades (PRD 3.6)
# --------------------------------------------------------------------------


def conclude_sample(sample):
    control = DB["controls"][sample["control_id"]]
    engagement = engagement_of_control(control)
    rate = calcs.deviation_rate(sample)
    sample["deviation_rate"] = float(rate)
    sample["projected_failures"] = float(
        calcs.projected_failures(rate, sample["population_size_snapshot"])
    )
    if sample["items_failed"] <= sample["allowed_deviations"]:
        sample["status"] = "CONCLUDED_CLEAN"
        store.touch(sample)
        if control["operating_status"] == "IN_OBSERVATION":
            control["operating_status"] = "TESTED_EFFECTIVE"
            store.touch(control)
        refresh_tested_item_count(control)
        refresh_engagement(engagement)
        return sample

    sample["status"] = "CONCLUDED_EXCEPTIONS"
    store.touch(sample)
    created = []
    for item in sample["_items"]:
        if item["outcome"] in ("FAIL", "NOT_PROVIDED"):
            exc = store.new_row(
                "audit_exceptions",
                {
                    "audit_sample_id": sample["id"],
                    "control_id": control["id"],
                    "item_ordinal": item["ordinal"],
                    "failure_reason": item["failure_reason"],
                    "disposition": "UNEVALUATED",
                    "severity_assigned": None,
                    "projected_failures_upper": 0,
                    "pervasive_recommended": False,
                    "evaluated_by_user_id": None,
                    "evaluated_at": None,
                },
            )
            created.append(exc)
    if control["operating_status"] == "IN_OBSERVATION":
        control["operating_status"] = "TESTED_EXCEPTION"
        store.touch(control)
    refresh_tested_item_count(control)
    if created:
        lowest = min(created, key=lambda e: e["item_ordinal"])
        create_gap(
            engagement,
            "EXCEPTION_CASCADE",
            "HIGH",
            control_id=control["id"],
            audit_exception_id=lowest["id"],
        )
    refresh_engagement(engagement)
    return sample


def void_sample(sample):
    control = DB["controls"][sample["control_id"]]
    engagement = engagement_of_control(control)
    previous = sample["status"]
    sample["status"] = "VOIDED"
    sample["voided_at"] = store.now_iso()
    store.touch(sample)
    if previous == "CONCLUDED_CLEAN":
        if control["operating_status"] == "TESTED_EFFECTIVE":
            control["operating_status"] = "IN_OBSERVATION"
            store.touch(control)
    elif previous == "CONCLUDED_EXCEPTIONS":
        exc_ids = []
        for exc in exceptions_of_sample(sample["id"]):
            exc["disposition"] = "VOIDED"
            exc["severity_assigned"] = None
            store.touch(exc)
            exc_ids.append(exc["id"])
        for gap in gaps_of(engagement["id"]):
            if gap["audit_exception_id"] in exc_ids and gap["status"] != "WITHDRAWN":
                set_gap_status(gap, "WITHDRAWN")
        if control["operating_status"] == "TESTED_EXCEPTION":
            control["operating_status"] = "IN_OBSERVATION"
            store.touch(control)
    refresh_tested_item_count(control)
    refresh_engagement(engagement)
    return sample


# --------------------------------------------------------------------------
# subservice presentation-method cascades (PRD 3.2)
# --------------------------------------------------------------------------


def switch_to_inclusive(org, engagement):
    org["method"] = "INCLUSIVE"
    store.touch(org)
    for control in controls_of(engagement["id"]):
        if control["subservice_organization_id"] != org["id"]:
            continue
        if control["design_status"] == "DESIGN_CARVED_OUT":
            control["design_status"] = "DESIGN_DRAFT"
            control["in_scope"] = True
            store.touch(control)
    refresh_inclusive_control_count(org)
    refresh_engagement(engagement)
    return org


def switch_to_carve_out(org, engagement, csoc_narrative):
    before = readiness_covered_ids(engagement)
    org["method"] = "CARVE_OUT"
    org["csoc_narrative"] = csoc_narrative
    org["csoc_articulated"] = True
    org["carved_out_at"] = store.now_iso()
    store.touch(org)
    for control in controls_of(engagement["id"]):
        if control["subservice_organization_id"] != org["id"]:
            continue
        control["design_status"] = "DESIGN_CARVED_OUT"
        control["in_scope"] = False
        store.touch(control)
    refresh_inclusive_control_count(org)
    refresh_coverage(engagement)
    after = readiness_covered_ids(engagement)
    lost = [c for c in in_scope_criteria(engagement) if c["id"] in before and c["id"] not in after]
    for criterion in lost:
        create_gap(engagement, "COVERAGE_LOSS", "HIGH", trust_criterion_id=criterion["id"])
    refresh_engagement(engagement)
    return org


# --------------------------------------------------------------------------
# calendar ops-run (PRD 3.7)
# --------------------------------------------------------------------------


def calendar_run(engagement):
    clock = store.now_dt()
    missed = 0
    gaps_created = 0
    pending = []
    for req in evidence_of_engagement(engagement["id"]):
        if req["status"] not in ("SCHEDULED", "REJECTED"):
            continue
        due = store.parse_iso(req["due_date"])
        if due is not None and due < clock:
            control = DB["controls"][req["control_id"]]
            pending.append((control["control_ref"], req["period_index"], control["_seq"],
                            req["_seq"], req, control))
    pending.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    for _ref, _idx, _cs, _rs, req, control in pending:
        req["status"] = "MISSED"
        store.touch(req)
        control["evidence_scheduled_count"] = max(0, control["evidence_scheduled_count"] - 1)
        control["evidence_missed_count"] = control["evidence_missed_count"] + 1
        missed += 1
        if (
            control["evidence_missed_count"] >= calcs.MISSED_INEFFECTIVE_THRESHOLD
            and control["operating_status"] == "IN_OBSERVATION"
        ):
            control["operating_status"] = "TESTED_INEFFECTIVE"
            store.touch(control)
            create_gap(engagement, "EVIDENCE_MISS", "HIGH", control_id=control["id"])
            gaps_created += 1
            refresh_debt_and_posture(engagement)

    expired = 0
    for letter in store.rows("bridge_letters"):
        if letter["engagement_id"] != engagement["id"]:
            continue
        if letter["status"] != "ISSUED":
            continue
        as_of = store.parse_iso(letter["as_of_date"])
        if as_of is not None and as_of < clock:
            letter["status"] = "EXPIRED"
            store.touch(letter)
            expired += 1

    engagement["calendar_epoch"] = engagement["calendar_epoch"] + 1
    bump_engagement_version(engagement)
    refresh_engagement(engagement)
    return {
        "calendar_epoch": engagement["calendar_epoch"],
        "missed_evidence_count": missed,
        "expired_bridge_letter_count": expired,
        "gaps_created_count": gaps_created,
        "gap_posture": engagement["gap_posture"],
        "gap_debt_points": engagement["gap_debt_points"],
    }


# --------------------------------------------------------------------------
# engagement cascades
# --------------------------------------------------------------------------


def bump_engagement_version(engagement):
    engagement["updated_at"] = store.now_iso()
    engagement["version"] = engagement["version"] + 1
    return engagement


def abandon_engagement(engagement):
    for sd in store.rows("system_descriptions"):
        if sd["engagement_id"] != engagement["id"]:
            continue
        if sd["status"] in ("DRAFT", "IN_REVIEW"):
            sd["status"] = "WITHDRAWN"
            store.touch(sd)
    for gap in gaps_of(engagement["id"]):
        if gap["status"] in ("OPEN", "PLANNED", "REMEDIATED", "REOPENED"):
            set_gap_status(gap, "WITHDRAWN")
    return engagement


def start_observation_cascade(engagement):
    for control in controls_of(engagement["id"]):
        if not control["in_scope"]:
            continue
        if control["operating_status"] == "NOT_TESTED":
            control["operating_status"] = "IN_OBSERVATION"
            store.touch(control)
    return engagement


# --------------------------------------------------------------------------
# posture gates (PRD 2.7 steps 12 and 13)
# --------------------------------------------------------------------------


def require_not_frozen(engagement):
    if engagement["gap_posture"] == "FROZEN":
        raise ApiError("ERR_ENGAGEMENT_FROZEN")


def require_posture_open(engagement):
    if engagement["gap_posture"] != "OPEN":
        raise ApiError("ERR_ENGAGEMENT_RESTRICTED")


def require_phase(engagement, allowed):
    if engagement["status"] not in allowed:
        raise ApiError("ERR_ENGAGEMENT_PHASE_INVALID")


def criterion_in_scope(engagement, criterion):
    return (
        criterion["category"] in engagement["required_criteria_categories"]
        and engagement["report_type"] in criterion["applies_to_report_types"]
    )
