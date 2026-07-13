"""Composite setup helpers for the EOC incident / ICS benchmark.

Every helper builds its preconditions from scratch through PRD-declared
endpoints (§3, §4). The runner restarts the API server before every
individual pytest test, so each helper starts from an empty database — no
incidents, no pools, no state carried over.

Helpers use get_success_data() (lenient validator) internally, so a broken
setup step surfaces as a clear "Setup step failed" trace rather than a
confusing downstream assertion error.

Role identities (§2.1): the five section-chief roles are opaque, so their
shared TEST_USERS headers are used directly. JurisdictionLiaison is
entity-backed; helpers that drive a liaison offer thread the real
Jurisdiction.id through make_jurisdiction_liaison_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_incident_payload,
    create_jurisdiction_payload,
    create_resource_pool_payload,
    create_resource_request_payload,
    create_iap_payload,
    create_task_payload,
    create_shelter_payload,
    create_mutual_aid_request_payload,
    create_damage_assessment_payload,
    create_cost_record_payload,
)
from .test_users import TEST_USERS, make_jurisdiction_liaison_headers

EOC = TEST_USERS["eoc_manager_headers"]
LOG = TEST_USERS["logistics_chief_headers"]
OPS = TEST_USERS["operations_chief_headers"]
PLAN = TEST_USERS["planning_chief_headers"]
FIN = TEST_USERS["finance_chief_headers"]


# ─── Tier 0: primitive create/transition steps ───────────────────────
def create_incident(**overrides) -> dict:
    """Create an incident (op_status=MONITORING). PRD §3.1."""
    return get_success_data(api_client.create_incident(create_incident_payload(**overrides), EOC))


def activate_incident(incident_id: str) -> dict:
    """Advance an incident MONITORING -> ACTIVATED. PRD §3.1."""
    return get_success_data(
        api_client.transition_incident(incident_id, {"to_status": "ACTIVATED"}, EOC)
    )


def create_activated_incident(**overrides) -> dict:
    """Create an incident and activate it. Returns the activated incident."""
    inc = create_incident(**overrides)
    activate_incident(inc["id"])
    return get_incident(inc["id"])


def get_incident(incident_id: str) -> dict:
    """Fetch a single incident (any role may read). PRD §4."""
    return get_success_data(api_client.get_incident(incident_id, EOC))


def incident_version(incident_id: str) -> int:
    """Read the incident's current version for OCC-guarded creates (§2.6)."""
    return get_incident(incident_id)["version"]


def create_jurisdiction(**overrides) -> dict:
    """Register a mutual-aid partner jurisdiction. PRD §3.6."""
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), EOC)
    )


def create_pool(jurisdiction_id: str, **overrides) -> dict:
    """Create a resource pool under a jurisdiction. PRD §3.2."""
    return get_success_data(
        api_client.create_resource_pool(
            create_resource_pool_payload(jurisdiction_id, **overrides), LOG
        )
    )


def get_pool(pool_id: str) -> dict:
    return get_success_data(api_client.get_resource_pool(pool_id, LOG))


def create_jurisdiction_and_pool(**pool_overrides) -> tuple:
    """Register a jurisdiction and stand up one pool under it.
    Returns (jurisdiction, pool)."""
    jur = create_jurisdiction(name="Pool Owner Jurisdiction")
    pool = create_pool(jur["id"], **pool_overrides)
    return jur, pool


# ─── Tier 1: ResourceRequest lifecycle ───────────────────────────────
def create_request(incident_id: str, **overrides) -> dict:
    """Create an ICS-213RR resource request (DRAFT). PRD §3.2."""
    return get_success_data(
        api_client.create_resource_request(
            create_resource_request_payload(incident_id, **overrides), OPS
        )
    )


def submit_request(request_id: str) -> dict:
    """DRAFT -> SUBMITTED (OperationsChief). PRD §3.2."""
    return get_success_data(
        api_client.transition_resource_request(request_id, {"to_status": "SUBMITTED"}, OPS)
    )


def source_request(request_id: str, pool_id: str) -> dict:
    """SUBMITTED -> SOURCED against a pool (LogisticsChief). PRD §3.2."""
    return get_success_data(
        api_client.transition_resource_request(
            request_id, {"to_status": "SOURCED", "pool_id": pool_id}, LOG
        )
    )


def fill_request(request_id: str, deploy_start: str, deploy_end: str) -> dict:
    """SOURCED -> FILLED with a deployment window (LogisticsChief). PRD §3.3."""
    return get_success_data(
        api_client.transition_resource_request(
            request_id,
            {"to_status": "FILLED", "deploy_start": deploy_start, "deploy_end": deploy_end},
            LOG,
        )
    )


def create_filled_request(
    incident_id: str,
    pool_id: str,
    quantity: int = 3,
    deploy_start: str = "2026-03-01T08:00:00Z",
    deploy_end: str = "2026-03-01T18:00:00Z",
    resource_type: str = "VEHICLE",
) -> dict:
    """Full ResourceRequest path DRAFT -> ... -> FILLED. Returns the filled request."""
    req = create_request(incident_id, resource_type=resource_type, requested_quantity=quantity)
    submit_request(req["id"])
    source_request(req["id"], pool_id)
    return fill_request(req["id"], deploy_start, deploy_end)


# ─── Tier 2: IAP + Task ──────────────────────────────────────────────
def create_iap(incident_id: str, **overrides) -> dict:
    """Create an IAP (DRAFT), reading the incident version for OCC. PRD §3.4."""
    version = overrides.pop("expected_incident_version", None)
    if version is None:
        version = incident_version(incident_id)
    return get_success_data(
        api_client.create_iap(create_iap_payload(incident_id, version, **overrides), PLAN)
    )


def publish_iap(iap_id: str) -> dict:
    """DRAFT -> PUBLISHED (PlanningChief). PRD §3.4."""
    return get_success_data(
        api_client.transition_iap(iap_id, {"to_status": "PUBLISHED"}, PLAN)
    )


def create_published_iap(incident_id: str, **overrides) -> dict:
    """Create and publish an IAP. Returns the published IAP."""
    iap = create_iap(incident_id, **overrides)
    return publish_iap(iap["id"])


def create_task(iap_id: str, **overrides) -> dict:
    """Create a task/objective under an IAP (PLANNED). PRD §3.4."""
    return get_success_data(
        api_client.create_task(create_task_payload(iap_id, **overrides), PLAN)
    )


def assign_task(task_id: str) -> dict:
    """PLANNED -> ASSIGNED (OperationsChief). PRD §3.4."""
    return get_success_data(
        api_client.transition_task(task_id, {"to_status": "ASSIGNED"}, OPS)
    )


# ─── Tier 3: Shelter ─────────────────────────────────────────────────
def create_shelter(incident_id: str, **overrides) -> dict:
    """Create a shelter (PLANNED). PRD §3.5."""
    return get_success_data(
        api_client.create_shelter(create_shelter_payload(incident_id, **overrides), OPS)
    )


def open_shelter(shelter_id: str) -> dict:
    """PLANNED -> OPEN (OperationsChief). PRD §3.5."""
    return get_success_data(
        api_client.transition_shelter(shelter_id, {"to_status": "OPEN"}, OPS)
    )


def create_open_shelter(incident_id: str, **overrides) -> dict:
    """Create and open a shelter. Returns the opened shelter."""
    sh = create_shelter(incident_id, **overrides)
    return open_shelter(sh["id"])


def adjust_occupancy(shelter_id: str, **deltas) -> dict:
    """Apply a check_in/check_out/reserve/release_reserve delta. PRD §3.5."""
    return get_success_data(
        api_client.adjust_shelter_occupancy(shelter_id, deltas, OPS)
    )


# ─── Tier 4: DamageAssessment + declaration eligibility ──────────────
def create_damage_assessment(incident_id: str, **overrides) -> dict:
    """Record a damage assessment (DRAFT). PRD §3.7."""
    return get_success_data(
        api_client.create_damage_assessment(
            create_damage_assessment_payload(incident_id, **overrides), PLAN
        )
    )


def validate_damage_assessment(da_id: str) -> dict:
    """DRAFT -> VALIDATED (PlanningChief). PRD §3.7."""
    return get_success_data(
        api_client.transition_damage_assessment(da_id, {"to_status": "VALIDATED"}, PLAN)
    )


def add_validated_damage(incident_id: str, estimated_loss, infrastructure_category="CAT_C_ROADS"):
    """Create and validate one damage assessment, raising total_verified_damage."""
    da = create_damage_assessment(
        incident_id,
        site_name="Assessed Site",
        estimated_loss=estimated_loss,
        infrastructure_category=infrastructure_category,
    )
    return validate_damage_assessment(da["id"])


def setup_eligible_incident(damage=5_000_000, declaration_category="EMERGENCY", **inc_overrides) -> dict:
    """Activated incident driven to declaration ELIGIBLE by validating a single
    damage assessment of `damage` dollars. PRD §3.1, §3.7. Returns the re-fetched
    incident (declaration_status ELIGIBLE when damage >= 5,000,000)."""
    inc = create_activated_incident(declaration_category=declaration_category, **inc_overrides)
    add_validated_damage(inc["id"], damage)
    return get_incident(inc["id"])


# ─── Tier 5: CostRecord ──────────────────────────────────────────────
def create_cost_record(incident_id: str, **overrides) -> dict:
    """Document a FEMA-PA cost record (ESTIMATED), reading the incident version
    for OCC. PRD §3.8."""
    version = overrides.pop("expected_incident_version", None)
    if version is None:
        version = incident_version(incident_id)
    return get_success_data(
        api_client.create_cost_record(
            create_cost_record_payload(incident_id, version, **overrides), FIN
        )
    )


def finalize_cost_record(cost_id: str, actual_cost) -> dict:
    """ESTIMATED -> ACTUAL with actual_cost (FinanceChief). PRD §3.8."""
    return get_success_data(
        api_client.transition_cost_record(
            cost_id, {"to_status": "ACTUAL", "actual_cost": actual_cost}, FIN
        )
    )


def void_cost_record(cost_id: str) -> dict:
    """ESTIMATED/ACTUAL -> VOID (FinanceChief). PRD §3.8."""
    return get_success_data(
        api_client.transition_cost_record(cost_id, {"to_status": "VOID"}, FIN)
    )


# ─── Tier 6: MutualAidRequest negotiation ────────────────────────────
def create_mutual_aid_request(incident_id: str, to_jurisdiction_id: str, **overrides) -> dict:
    """Open an EMAC mutual-aid request (REQUESTED). PRD §3.6."""
    return get_success_data(
        api_client.create_mutual_aid_request(
            create_mutual_aid_request_payload(incident_id, to_jurisdiction_id, **overrides), LOG
        )
    )


def offer_mutual_aid(ma_id: str, jurisdiction_id: str, offered_units: int) -> dict:
    """Liaison offer/re-offer -> OFFERED (ownership-gated on jurisdiction_id). PRD §3.6."""
    headers = make_jurisdiction_liaison_headers(jurisdiction_id)
    return get_success_data(
        api_client.transition_mutual_aid_request(
            ma_id, {"to_status": "OFFERED", "offered_units": offered_units}, headers
        )
    )


def counter_mutual_aid(ma_id: str, countered_units: int) -> dict:
    """LogisticsChief counter -> COUNTERED. PRD §3.6."""
    return get_success_data(
        api_client.transition_mutual_aid_request(
            ma_id, {"to_status": "COUNTERED", "countered_units": countered_units}, LOG
        )
    )


def setup_offered_mutual_aid(offered_units: int = 4, requested_units: int = 5) -> tuple:
    """Activated incident + jurisdiction + a MutualAidRequest driven to OFFERED.
    Returns (incident, jurisdiction, mutual_aid_request)."""
    inc = create_activated_incident(name="Mutual Aid Incident")
    jur = create_jurisdiction(name="Partner Jurisdiction")
    ma = create_mutual_aid_request(inc["id"], jur["id"], resource_type="PERSONNEL", requested_units=requested_units)
    offer_mutual_aid(ma["id"], jur["id"], offered_units)
    return inc, jur, get_success_data(api_client.get_mutual_aid_request(ma["id"], LOG))


# ─── Tier 7: cross-entity composites for difficulty setups ───────────
def setup_filled_request_scenario(
    quantity: int = 3,
    total_units: int = 10,
    deploy_start: str = "2026-03-01T08:00:00Z",
    deploy_end: str = "2026-03-01T18:00:00Z",
    resource_type: str = "VEHICLE",
    **pool_overrides,
) -> dict:
    """Activated incident + jurisdiction + pool + one FILLED request.
    Returns {incident, jurisdiction, pool, request} (all re-fetched)."""
    inc = create_activated_incident(name="Filled Request Incident")
    jur, pool = create_jurisdiction_and_pool(
        resource_type=resource_type, total_units=total_units, **pool_overrides
    )
    req = create_filled_request(
        inc["id"], pool["id"], quantity=quantity,
        deploy_start=deploy_start, deploy_end=deploy_end, resource_type=resource_type,
    )
    return {
        "incident": get_incident(inc["id"]),
        "jurisdiction": jur,
        "pool": get_pool(pool["id"]),
        "request": req,
    }


def setup_assigned_task_backed_by_filled_request() -> dict:
    """Depth-3 cascade precondition: activated incident, pool, FILLED request,
    PUBLISHED IAP, and an ASSIGNED task whose resource_request_id is that request.
    Returns {incident, jurisdiction, pool, request, iap, task}. PRD §3.3, §3.4."""
    scenario = setup_filled_request_scenario(quantity=3, total_units=10)
    inc = scenario["incident"]
    iap = create_published_iap(
        inc["id"],
        operational_period_start="2026-03-01T06:00:00Z",
        operational_period_end="2026-03-02T06:00:00Z",
    )
    task = create_task(iap["id"], title="Clear Route", resource_request_id=scenario["request"]["id"])
    assign_task(task["id"])
    scenario["iap"] = iap
    scenario["task"] = get_success_data(api_client.get_task(task["id"], PLAN))
    scenario["pool"] = get_pool(scenario["pool"]["id"])
    return scenario
