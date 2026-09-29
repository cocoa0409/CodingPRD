"""Fresh recomputation of every derived / materialized posture field (PRD 2.12)."""
from datetime import timedelta
from decimal import Decimal

import calc
import store
from store import S, now, touch

# ------------------------------------------------------------ child lookups ----


def stats_of(prequalification_id):
    return [r for r in S.safety_statistics.values() if r["prequalification_id"] == prequalification_id]


def programs_of(prequalification_id):
    return [r for r in S.written_programs.values() if r["prequalification_id"] == prequalification_id]


def plans_of(prequalification_id):
    return [r for r in S.improvement_plans.values() if r["prequalification_id"] == prequalification_id]


def variances_of(prequalification_id):
    return [r for r in S.variances.values() if r["prequalification_id"] == prequalification_id]


def grants_of_prequal(prequalification_id):
    return [r for r in S.site_access_grants.values() if r["prequalification_id"] == prequalification_id]


def links_of_prequal(prequalification_id):
    return [r for r in S.subcontractor_links.values() if r["prequalification_id"] == prequalification_id]


def certs_of(contractor_id):
    return [r for r in S.insurance_certificates.values() if r["contractor_id"] == contractor_id]


def preqs_of_contractor(contractor_id):
    return [r for r in S.prequalifications.values() if r["contractor_id"] == contractor_id]


def preqs_of_client(client_id):
    return [r for r in S.prequalifications.values() if r["client_id"] == client_id]


def workers_of(contractor_id):
    return [r for r in S.workers.values() if r["contractor_id"] == contractor_id]


def quals_of(worker_id):
    return [r for r in S.worker_qualifications.values() if r["worker_id"] == worker_id]


def sites_of(client_id):
    return [r for r in S.sites.values() if r["client_id"] == client_id]


def incidents_of_site(site_id):
    return [r for r in S.incident_reports.values() if r["site_id"] == site_id]


def incidents_of_contractor(contractor_id):
    return [r for r in S.incident_reports.values() if r["contractor_id"] == contractor_id]


# --------------------------------------------------- prequal review dimensions -


def governing_statistic(prequalification_id, admitted):
    rows = [r for r in stats_of(prequalification_id) if r["verification_status"] in admitted]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["reporting_year"], r["created_at"], r["_seq"]))
    return rows[-1]


def statistics_verification_status(prequalification_id):
    rows = stats_of(prequalification_id)
    if not rows:
        return "NOT_SUBMITTED"
    governing = governing_statistic(prequalification_id, ("PENDING", "VERIFIED"))
    if governing is None:
        return "REJECTED"
    return governing["verification_status"]


def document_review_status(preq):
    contractor = S.contractors[preq["contractor_id"]]
    required = calc.required_program_set(contractor["hazard_profile"])
    rows = programs_of(preq["id"])
    by_type = {}
    for row in rows:
        by_type[row["program_type"]] = row
    for program_type in required:
        row = by_type.get(program_type)
        if row is not None and row["review_status"] == "DEFICIENT":
            return "DEFICIENT"
    satisfied = True
    for program_type in required:
        row = by_type.get(program_type)
        if row is None or row["review_status"] not in ("ACCEPTED", "WAIVED"):
            satisfied = False
            break
    if satisfied:
        return "COMPLETE"
    if preq["status"] == "DRAFT":
        return "NOT_STARTED"
    return "IN_PROGRESS"


def plan_projected_status(plan):
    """PRD 2.12: a plan reads OVERDUE once its due_date is at or before the clock."""
    if plan["status"] in ("OPEN", "SUBMITTED") and plan["due_date"] <= now():
        return "OVERDUE"
    return plan["status"]


# ----------------------------------------------------------------- sites -------


def site_granted_worker_count(site_id):
    return len(
        [
            r
            for r in S.site_access_grants.values()
            if r["site_id"] == site_id and r["status"] == "GRANTED"
        ]
    )


def site_access_gate_status(site_id):
    severities = [
        r["severity"] for r in incidents_of_site(site_id) if r["review_status"] == "OPEN"
    ]
    return calc.gate_status_from_severities(severities)


def recompute_site(site):
    """Conserved counter plus gate posture; the row advances its own version
    only when one of the two values actually changes."""
    count = site_granted_worker_count(site["id"])
    gate = site_access_gate_status(site["id"])
    if site["granted_worker_count"] != count or site["access_gate_status"] != gate:
        site["granted_worker_count"] = count
        site["access_gate_status"] = gate
        touch(site)


# ------------------------------------------------------------ contractors ------


def open_severe_incident_count(contractor_id):
    return len(
        [
            r
            for r in incidents_of_contractor(contractor_id)
            if r["review_status"] == "OPEN" and r["severity"] in calc.SEVERE_SEVERITIES
        ]
    )


def incident_review_flag(contractor_id):
    for r in incidents_of_contractor(contractor_id):
        if r["review_status"] == "OPEN" and r["severity"] in calc.REVIEW_FLAG_SEVERITIES:
            return True
    return False


def open_deficiency_count(contractor_id):
    total = 0
    for preq in preqs_of_contractor(contractor_id):
        if preq["status"] == "CONDITIONAL":
            total += len(preq["deficiency_codes"])
    return total


def recompute_open_deficiency_count(contractor):
    contractor["open_deficiency_count"] = open_deficiency_count(contractor["id"])


def recompute_verified_coverage_types(contractor):
    clock = now()
    live = set()
    for cert in certs_of(contractor["id"]):
        if cert["verification_status"] != "VERIFIED":
            continue
        if calc.lifecycle_status(cert, clock) in calc.LIVE_LIFECYCLE:
            live.add(cert["coverage_type"])
    contractor["verified_coverage_types"] = [c for c in calc.COVERAGE_TYPES if c in live]


def recompute_incident_counters(contractor):
    contractor["open_severe_incident_count"] = open_severe_incident_count(contractor["id"])
    contractor["incident_review_flag"] = incident_review_flag(contractor["id"])


def rematerialize_available_aggregate(contractor):
    """Depletion is driven by the contractor's open severe incident counter."""
    depleting = contractor["open_severe_incident_count"]
    for cert in certs_of(contractor["id"]):
        value = calc.available_aggregate(cert["aggregate_limit"], depleting)
        if cert["available_aggregate"] != value:
            cert["available_aggregate"] = value
            touch(cert)


def rematerialize_certificates(contractor):
    """Requalification-run step 4: both lifecycle_status and available_aggregate."""
    clock = now()
    depleting = contractor["open_severe_incident_count"]
    for cert in certs_of(contractor["id"]):
        lifecycle = calc.lifecycle_status(cert, clock)
        available = calc.available_aggregate(cert["aggregate_limit"], depleting)
        if cert["lifecycle_status"] != lifecycle or cert["available_aggregate"] != available:
            cert["lifecycle_status"] = lifecycle
            cert["available_aggregate"] = available
            touch(cert)


def live_certificates(contractor_id, coverage_type=None):
    """VERIFIED certificates whose freshly recomputed lifecycle is live."""
    clock = now()
    out = []
    for cert in certs_of(contractor_id):
        if cert["verification_status"] != "VERIFIED":
            continue
        if coverage_type is not None and cert["coverage_type"] != coverage_type:
            continue
        if calc.lifecycle_status(cert, clock) in calc.LIVE_LIFECYCLE:
            out.append(cert)
    return out


# ------------------------------------------------------ threshold resolution ---


def client_scoped_severity_rank(contractor_id, client_id):
    """PRD 3.6 step 1: highest severity among incidents filed against this
    contractor at any site it has ever been badged into with this client,
    inside the trailing 365 days (both endpoints inclusive)."""
    preq_ids = set(
        p["id"]
        for p in S.prequalifications.values()
        if p["contractor_id"] == contractor_id and p["client_id"] == client_id
    )
    site_ids = set(
        g["site_id"] for g in S.site_access_grants.values() if g["prequalification_id"] in preq_ids
    )
    if not site_ids:
        return 0
    clock = now()
    floor = clock - timedelta(days=calc.INCIDENT_LOOKBACK_DAYS)
    best = 0
    for report in incidents_of_contractor(contractor_id):
        if report["site_id"] not in site_ids:
            continue
        if report["occurred_at"] < floor or report["occurred_at"] > clock:
            continue
        best = max(best, calc.SEVERITY_RANK[report["severity"]])
    return best


def approved_variance_values(prequalification_id):
    """Approved, unexpired variances on the four graded requirement codes."""
    clock = now()
    out = {}
    for variance in variances_of(prequalification_id):
        if variance["status"] != "APPROVED":
            continue
        if variance["expires_at"] is None or variance["expires_at"] <= clock:
            continue
        if variance["requirement_code"] in calc.METRIC_ORDER:
            out[variance["requirement_code"]] = variance["requested_value"]
    return out


def resolve_thresholds(preq, provisional):
    """Returns (thresholds dict, tightening factor, hazard tier)."""
    contractor = S.contractors[preq["contractor_id"]]
    client = S.clients[preq["client_id"]]
    rank = client_scoped_severity_rank(contractor["id"], client["id"])
    tier = calc.hazard_tier(contractor["hazard_profile"], rank)
    thresholds, factor = calc.tighten_thresholds(client, tier, provisional)
    if not provisional:
        thresholds = calc.overlay_variances(thresholds, approved_variance_values(preq["id"]))
    return thresholds, factor, tier


def metrics_from(statistic):
    return {
        "TRIR": statistic["trir"],
        "DART": statistic["dart_rate"],
        "EMR": statistic["emr"],
        "CITATION_POINTS": Decimal(statistic["citation_points"]),
    }


def weights_of(client):
    return {
        "TRIR": client["weight_trir"],
        "DART": client["weight_dart"],
        "EMR": client["weight_emr"],
        "CITATION_POINTS": client["weight_citation"],
    }


def score_variant(preq, statistic, provisional):
    client = S.clients[preq["client_id"]]
    thresholds, factor, tier = resolve_thresholds(preq, provisional)
    total, _subs = calc.composite_score(metrics_from(statistic), thresholds, weights_of(client))
    return total, thresholds, factor, tier


# --------------------------------------------------------- subcontractor -------


def active_links(prequalification_id):
    return [r for r in links_of_prequal(prequalification_id) if r["status"] == "ACTIVE"]


def link_depth(prequalification_id, parent_contractor_id, prime_contractor_id):
    if parent_contractor_id == prime_contractor_id:
        return 1
    for link in active_links(prequalification_id):
        if link["child_contractor_id"] == parent_contractor_id:
            return link["depth"] + 1
    return None


def flow_down_status(link):
    prime = S.prequalifications[link["prequalification_id"]]
    if prime["status"] in ("REJECTED", "EXPIRED", "SUSPENDED"):
        return "DEFICIENT"
    child_preqs = [
        p
        for p in preqs_of_contractor(link["child_contractor_id"])
        if p["client_id"] == prime["client_id"]
    ]
    for preq in child_preqs:
        if preq["status"] in ("APPROVED", "CONDITIONAL"):
            return "SATISFIED"
    for preq in child_preqs:
        if preq["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW"):
            return "PENDING"
    return "DEFICIENT"


def recompute_flow_down(prequalification_id):
    for link in active_links(prequalification_id):
        value = flow_down_status(link)
        if link["flow_down_status"] != value:
            link["flow_down_status"] = value
            touch(link)


# ---------------------------------------------------------- coverage gate ------


def coverage_gate(contractor, client):
    """Validation priority 28 then 29: every required coverage type must be
    backed by a VERIFIED, freshly-live certificate, and each such certificate
    must clear the depleted-aggregate adequacy test."""
    from errors import fail

    backing = []
    for coverage_type in client["required_coverage_types"]:
        certs = live_certificates(contractor["id"], coverage_type)
        if not certs:
            fail(
                "ERR_MISSING_VERIFIED_COVERAGE",
                "No verified, currently effective %s certificate." % coverage_type,
            )
        backing.extend(certs)
    tier = contractor["base_hazard_tier"]
    depleting = contractor["open_severe_incident_count"]
    for cert in backing:
        if not calc.aggregate_adequate(
            cert["coverage_type"], cert["aggregate_limit"], depleting, tier
        ):
            fail(
                "ERR_COVERAGE_LIMIT_INSUFFICIENT",
                "Available aggregate for %s is below its floor." % cert["coverage_type"],
            )
