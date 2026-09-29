"""Domain registry, activation and the scorecard (PRD 3.1 / 3.4)."""

from decimal import Decimal

from flask import Blueprint, g

import db
import response
import services
import validation as v
from auth import endpoint, entitle
from errors import fail
from util import round2

bp = Blueprint("domains", __name__)

CODES = ("CUSTOMER", "PRODUCT", "VENDOR", "LOCATION")
STATUSES = ("DRAFT", "ACTIVE")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
CLASSIFICATIONS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
BASES = ("PROVISIONAL", "CERTIFIED")


@bp.post("/mdm/domains")
@endpoint("GovernanceAdmin")
def create_domain():
    body = v.body()
    code = v.req_enum(body, "code", CODES)
    name = v.req_str(body, "name", 1, 120)
    classification = v.req_enum(body, "classification_level", CLASSIFICATIONS)
    floor = v.opt_int(body, "notification_lead_days_floor", 0, 30, 5)
    expected = v.opt_int(body, "expected_attribute_count", 1, 50, 5)

    for existing in db.store.domains.values():
        if existing["code"] == code:
            fail("ERR_DUPLICATE_DOMAIN_CODE",
                 "A domain definition with this code already exists.")

    domain = db.create("Domain", {
        "code": code,
        "name": name,
        "status": "DRAFT",
        # A freshly defined domain has no authoritative source yet, so its
        # derived posture is already FROZEN.
        "governance_posture": "FROZEN",
        "classification_level": classification,
        "sensitive_handling_required": classification in services.SENSITIVE_LEVELS,
        "authoritative_source_code": None,
        "notification_lead_days_floor": floor,
        "expected_attribute_count": expected,
        "open_finding_weight": Decimal("0.00"),
        "quality_score_provisional": None,
        "quality_score_certified": None,
        "scorecard_run_seq": 0,
        "reference_data_revision": 0,
        "published_master_record_count": 0,
        "scheduled_change_count": 0,
        "activated_at": None,
    })
    db.store.domains[domain["id"]] = domain
    return response.created(domain)


@bp.get("/mdm/domains")
@endpoint("GovernanceAdmin", "DataOwner", "DataSteward", "ConsumerRep", "Auditor")
def list_domains():
    limit, offset = v.pagination()
    status = v.enum_filter("status", STATUSES)
    classification = v.enum_filter("classification_level", CLASSIFICATIONS)
    posture = v.enum_filter("governance_posture", POSTURES)

    rows = db.ordered(db.store.domains)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if classification is not None:
        rows = [r for r in rows if r["classification_level"] == classification]
    if posture is not None:
        rows = [r for r in rows if r["governance_posture"] == posture]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/domains/<domain_id>")
@endpoint("GovernanceAdmin", "DataOwner", "DataSteward", "ConsumerRep", "Auditor")
def read_domain(domain_id):
    domain = db.resolve(db.store.domains, domain_id, "ERR_DOMAIN_NOT_FOUND")
    return response.entity(domain)


@bp.post("/mdm/domains/<domain_id>/activate")
@endpoint("GovernanceAdmin")
def activate_domain(domain_id):
    domain = db.resolve(db.store.domains, domain_id, "ERR_DOMAIN_NOT_FOUND")

    if domain["status"] != "DRAFT":
        fail("ERR_DOMAIN_NOT_DRAFT", "The domain is not in DRAFT status.")

    if not db.active_rules_of(domain_id):
        fail("ERR_NO_QUALITY_RULES", "The domain holds no ACTIVE quality rule.")

    has_owner = False
    has_steward = False
    for assignment in db.assignments_of(domain_id):
        if assignment["status"] != "ACTIVE" or not db.assignment_covers_clock(assignment):
            continue
        if assignment["steward_role"] == "DATA_OWNER":
            has_owner = True
        elif assignment["steward_role"] == "DATA_STEWARD":
            has_steward = True
    if not (has_owner and has_steward):
        fail("ERR_STEWARDSHIP_INCOMPLETE",
             "The domain needs both an ACTIVE DATA_OWNER and an ACTIVE DATA_STEWARD assignment.")

    registration = db.active_authoritative_registration(domain_id)
    if registration is None:
        certified = False
    else:
        source = db.store.source_systems[registration["source_system_id"]]
        certified = source["status"] == "CERTIFIED"
    if not certified:
        fail("ERR_NO_CERTIFIED_AUTHORITATIVE_SOURCE",
             "The domain holds no ACTIVE AUTHORITATIVE registration on a CERTIFIED source system.")

    domain["status"] = "ACTIVE"
    domain["activated_at"] = db.now()
    services.recompute_domain(domain)
    db.touch_domain(domain)
    return response.entity(domain)


@bp.get("/mdm/domains/<domain_id>/scorecard")
@endpoint("GovernanceAdmin", "DataOwner", "DataSteward", "ConsumerRep", "Auditor")
def read_scorecard(domain_id):
    domain = db.resolve(db.store.domains, domain_id, "ERR_DOMAIN_NOT_FOUND")
    basis = v.enum_filter("basis", BASES) or "PROVISIONAL"

    measurements = services.stored_measurements(domain)
    _, score, evaluated, failed = services.evaluate_scorecard(domain, basis, measurements)
    from util import num
    return response.ok({
        "domain_id": domain["id"],
        "basis": basis,
        "weighted_score": num(score),
        "rules_evaluated_count": evaluated,
        "rules_failed_count": failed,
        "open_finding_weight": num(domain["open_finding_weight"]),
        "governance_posture": domain["governance_posture"],
    })


@bp.post("/mdm/domains/<domain_id>/scorecard-runs")
@endpoint("DataSteward", "DataOwner")
def create_scorecard_run(domain_id):
    domain = db.resolve(db.store.domains, domain_id, "ERR_DOMAIN_NOT_FOUND")

    body = v.body()
    basis = v.req_enum(body, "basis", BASES)
    raw_measurements = body.get("measurements")
    if not isinstance(raw_measurements, list):
        from errors import invalid
        invalid("Field 'measurements' must be an array.")
    measurements = {}
    for index, item in enumerate(raw_measurements):
        if not isinstance(item, dict):
            from errors import invalid
            invalid("Every entry of 'measurements' must be an object.")
        code = v.req_str(item, "rule_code", 1, 20)
        measured = v.req_num(item, "measured_pct", 0, 100)
        measurements[code] = measured

    entitle(domain)

    active_codes = set(r["rule_code"] for r in db.active_rules_of(domain_id))
    for code in measurements:
        if code not in active_codes:
            fail("ERR_UNKNOWN_RULE_CODE",
                 "Measurement rule_code '%s' does not name an ACTIVE rule of this domain." % code)

    if basis == "CERTIFIED":
        registration = db.active_authoritative_registration(domain_id)
        certified = False
        if registration is not None:
            source = db.store.source_systems[registration["source_system_id"]]
            certified = source["status"] == "CERTIFIED"
        if not certified:
            fail("ERR_NO_CERTIFIED_AUTHORITATIVE_SOURCE",
                 "A CERTIFIED-basis run requires an ACTIVE AUTHORITATIVE registration on a CERTIFIED source.")

    # --- pinned evaluation order (PRD 2.7) ---
    posture_before = domain["governance_posture"]
    multiplier = services.MULTIPLIER[posture_before]

    rows, score, evaluated_count, failed_count = services.evaluate_scorecard(
        domain, basis, measurements)

    run = db.create("ScorecardRun", {
        "domain_id": domain["id"],
        "run_seq": 0,
        "basis": basis,
        "measured_at": db.now(),
        "weighted_score": score,
        "rules_evaluated_count": evaluated_count,
        "rules_failed_count": failed_count,
        "findings_created_count": 0,
        "posture_before": posture_before,
        "posture_after": posture_before,
        "posture_multiplier_applied": round2(multiplier),
    }, common=False)

    created_count = 0
    for rule, measured in rows:
        if measured >= rule["threshold_pct"]:
            continue
        gap = round2(rule["threshold_pct"] - measured)
        existing = None
        for finding in db.findings_of_rule(rule["id"]):
            if finding["status"] in db.OPEN_FINDING_STATUSES:
                existing = finding
                break
        if existing is not None:
            existing["measured_pct"] = measured
            existing["gap_pct"] = gap
            db.bump(existing)
            continue
        finding = db.create("QualityFinding", {
            "scorecard_run_id": run["id"],
            "quality_rule_id": rule["id"],
            "status": "OPEN",
            "severity_weight": round2(services.BASE_POINTS[rule["severity"]] * multiplier),
            "measured_pct": measured,
            "gap_pct": gap,
            "assigned_steward_id": None,
            "planned_by_steward_id": None,
            "waived_by_steward_id": None,
            "due_at": None,
            "plan_note": None,
            "resolution_note": None,
            "waiver_justification": None,
            "opened_at": db.now(),
            "resolved_at": None,
        })
        db.store.quality_findings[finding["id"]] = finding
        created_count += 1

    run["findings_created_count"] = created_count

    domain["scorecard_run_seq"] += 1
    run["run_seq"] = domain["scorecard_run_seq"]
    if basis == "PROVISIONAL":
        domain["quality_score_provisional"] = score
    else:
        domain["quality_score_certified"] = score

    # Recompute open_finding_weight and the posture exactly once, after all of
    # the run's findings exist.
    run["posture_after"] = services.recompute_domain(domain)
    db.touch_domain(domain)

    db.store.scorecard_runs[run["id"]] = run
    return response.created(run)
