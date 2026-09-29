"""Composite setup helpers.

Each test starts against an empty database, so every precondition here is built
from scratch through PRD-declared endpoints only. Setup calls use the lenient
`get_success_data()` validator so a broken precondition surfaces as a setup
failure rather than as a confusing assertion inside a test body.
"""

import itertools
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import ALL_TEST_CODES, CLOCK_START_UTC, MANDATED_DOCUMENT_KINDS, TEST_DEFAULTS
from .factories import (
    acknowledge_payload,
    create_audit_campaign_payload,
    create_bench_reservation_payload,
    create_consumer_registration_payload,
    create_corrective_action_payload,
    create_design_revision_payload,
    create_field_incident_payload,
    create_joint_sample_payload,
    create_listing_body_payload,
    create_listing_record_payload,
    create_load_test_payload,
    create_product_document_payload,
    create_product_payload,
    create_production_lot_payload,
    create_recall_event_payload,
    create_test_bench_payload,
    create_test_campaign_payload,
    disposition_payload,
    freeze_design_payload,
    quarantine_payload,
    resolve_investigation_payload,
    review_design_revision_payload,
    start_campaign_payload,
    start_production_payload,
    unique_suffix,
)
from .test_users import TEST_USERS, make_certification_body_headers

ENGINEER = TEST_USERS["design_engineer_headers"]
APPROVER = TEST_USERS["design_approver_headers"]
TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
CONSUMER = TEST_USERS["consumer_headers"]
DIRECTOR = TEST_USERS["safety_director_headers"]
SYSOP = TEST_USERS["system_operator_headers"]

# Document payload shapes that satisfy the three artwork rules of PRD §3.3.
DOCUMENT_SHAPES: Dict[str, Dict[str, Any]] = {
    "DUTY_RATING_LABEL": {"placement_zone": "SIDE_RAIL_UPPER"},
    "WARNING_LABEL": {"placement_zone": "SIDE_RAIL_LOWER", "pictogram_count": 3},
    "INSTRUCTION_LABEL": {"placement_zone": "BACK_RAIL"},
    "CERT_MARK_LABEL": {"placement_zone": "TOP_CAP"},
    "RETAIL_CARTON": {},
    "ASSEMBLY_INSTRUCTION_SHEET": {"includes_assembly_instructions": True},
    "CONSUMER_SAFETY_SHEET": {},
}

_BENCH_WINDOW_BASE = datetime(2026, 8, 2, 8, 0, 0)
_bench_window_counter = itertools.count(0)


# ---------------------------------------------------------------------------
# Instants and the logical clock
# ---------------------------------------------------------------------------
def iso(moment: datetime) -> str:
    """Format an instant the way the PRD writes them: ISO 8601 UTC."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the deterministic logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, SYSOP))


def next_bench_window(duration_minutes: int = 240) -> Tuple[str, str]:
    """A fresh bench window on its own calendar day, so no two fixture
    reservations ever collide through the cooldown buffer."""
    day = _BENCH_WINDOW_BASE + timedelta(days=next(_bench_window_counter))
    return iso(day), iso(day + timedelta(minutes=duration_minutes))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def get_product_data(product_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_product(product_id, ENGINEER))


def get_revision_data(revision_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_design_revision(revision_id, ENGINEER))


def get_bench_data(bench_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_test_bench(bench_id, TECHNICIAN))


def get_reservation_data(reservation_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_bench_reservation(reservation_id, TECHNICIAN))


def get_campaign_data(campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_test_campaign(campaign_id, TECHNICIAN))


def get_lot_data(lot_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_production_lot(lot_id, SUPERVISOR))


def get_listing_record_data(record_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_listing_record(record_id, OFFICER))


def get_registration_data(registration_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_consumer_registration(registration_id, OFFICER)
    )


def get_incident_data(incident_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_field_incident(incident_id, DIRECTOR))


def get_corrective_action_data(action_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_corrective_action(action_id, DIRECTOR))


def get_recall_data(recall_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_recall_event(recall_id, DIRECTOR))


def get_dossier_data(product_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_liability_dossier(product_id, OFFICER))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and state progression
# ---------------------------------------------------------------------------
def create_product(**overrides) -> Dict[str, Any]:
    """Catalogue a ladder model (PRD §3.1)."""
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), ENGINEER)
    )


def create_draft_revision(product_id: str, **overrides) -> Dict[str, Any]:
    """Create a design revision, reading the product's live `version` for the
    mandatory `expected_product_version`."""
    product = get_product_data(product_id)
    payload = create_design_revision_payload(
        product_id, product["version"], **overrides
    )
    return get_success_data(api_client.create_design_revision(payload, ENGINEER))


def submit_revision(revision_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_design_revision(revision_id, headers or ENGINEER)
    )


def create_submitted_revision(product_id: str, **overrides) -> Dict[str, Any]:
    revision = create_draft_revision(product_id, **overrides)
    return submit_revision(revision["id"])


def create_approved_revision(product_id: str, **overrides) -> Dict[str, Any]:
    """Create → submit → APPROVE a revision. Returns the APPROVED revision."""
    revision = create_submitted_revision(product_id, **overrides)
    return get_success_data(
        api_client.review_design_revision(
            revision["id"], review_design_revision_payload("APPROVE"), APPROVER
        )
    )


def create_changes_requested_revision(product_id: str, **overrides) -> Dict[str, Any]:
    revision = create_submitted_revision(product_id, **overrides)
    return get_success_data(
        api_client.review_design_revision(
            revision["id"],
            review_design_revision_payload("REQUEST_CHANGES"),
            APPROVER,
        )
    )


def create_test_bench(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_test_bench(create_test_bench_payload(**overrides), TECHNICIAN)
    )


def create_listing_body(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_listing_body(create_listing_body_payload(**overrides), OFFICER)
    )


def file_listing_record(
    product_id: str, listing_body_id: str, **overrides
) -> Dict[str, Any]:
    payload = create_listing_record_payload(product_id, listing_body_id, **overrides)
    return get_success_data(api_client.create_listing_record(payload, OFFICER))


def create_document(product_id: str, doc_kind: str, **overrides) -> Dict[str, Any]:
    """Draft a label or packaging document with a shape that satisfies the
    artwork rules for its kind."""
    shape = dict(DOCUMENT_SHAPES.get(doc_kind, {}))
    shape.update(overrides)
    payload = create_product_document_payload(product_id, doc_kind, **shape)
    return get_success_data(api_client.create_product_document(payload, ENGINEER))


def create_and_approve_document(
    product_id: str, doc_kind: str, **overrides
) -> Dict[str, Any]:
    document = create_document(product_id, doc_kind, **overrides)
    return get_success_data(
        api_client.approve_product_document(document["id"], OFFICER)
    )


def approve_mandated_documents(product_id: str) -> List[Dict[str, Any]]:
    """Approve one document of every mandated kind the retail-release gate reads."""
    return [
        create_and_approve_document(product_id, kind) for kind in MANDATED_DOCUMENT_KINDS
    ]


# ---------------------------------------------------------------------------
# Tier 2: campaigns on benches
# ---------------------------------------------------------------------------
def create_campaign(
    product_id: str,
    design_revision_id: str,
    purpose: str = "DESIGN_QUALIFICATION",
    **overrides,
) -> Dict[str, Any]:
    payload = create_test_campaign_payload(
        product_id, design_revision_id, purpose, **overrides
    )
    return get_success_data(api_client.create_test_campaign(payload, TECHNICIAN))


def reserve_bench(
    bench_id: str,
    campaign_id: str,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
    duration_minutes: int = 240,
) -> Dict[str, Any]:
    if start_at is None or end_at is None:
        start_at, end_at = next_bench_window(duration_minutes)
    payload = create_bench_reservation_payload(bench_id, campaign_id, start_at, end_at)
    return get_success_data(api_client.create_bench_reservation(payload, TECHNICIAN))


def start_campaign(campaign_id: str, reservation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.start_test_campaign(
            campaign_id, start_campaign_payload(reservation_id), TECHNICIAN
        )
    )


def start_campaign_on_new_reservation(
    campaign_id: str, bench_id: str, duration_minutes: int = 240
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    reservation = reserve_bench(
        bench_id, campaign_id, duration_minutes=duration_minutes
    )
    campaign = start_campaign(campaign_id, reservation["id"])
    return campaign, reservation


def record_passing_load_test(
    campaign_id: str, product: Dict[str, Any], test_code: str = "STATIC_VERTICAL"
) -> Dict[str, Any]:
    """A load test that exactly meets the required load with no deflection and no
    permanent set — a PASS for any model."""
    payload = create_load_test_payload(
        test_code=test_code,
        applied_load_lb=float(product["required_test_load_lb"]),
        measured_deflection_in=0.000,
        permanent_set_in=0.000,
    )
    return get_success_data(api_client.create_load_test(campaign_id, payload, TECHNICIAN))


def record_failing_load_test(
    campaign_id: str, product: Dict[str, Any], test_code: str = "STATIC_VERTICAL"
) -> Dict[str, Any]:
    """A load test one pound below the required load — FAIL with
    `LOAD_BELOW_REQUIRED`."""
    payload = create_load_test_payload(
        test_code=test_code,
        applied_load_lb=round(float(product["required_test_load_lb"]) - 1.00, 2),
        measured_deflection_in=0.000,
        permanent_set_in=0.000,
    )
    return get_success_data(api_client.create_load_test(campaign_id, payload, TECHNICIAN))


def record_full_test_matrix(campaign_id: str, product: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Record one passing load test for every declared `test_code`, so whichever
    required set the model's `product_type` implies is fully covered."""
    return [
        record_passing_load_test(campaign_id, product, code) for code in ALL_TEST_CODES
    ]


def conclude_campaign(campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.conclude_test_campaign(campaign_id, TECHNICIAN))


def run_campaign_to_passed(
    product: Dict[str, Any],
    design_revision_id: str,
    purpose: str = "DESIGN_QUALIFICATION",
    bench_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Plan → reserve → start → full passing test matrix → conclude PASSED."""
    if bench_id is None:
        bench_id = create_test_bench()["id"]
    campaign = create_campaign(product["id"], design_revision_id, purpose)
    start_campaign_on_new_reservation(campaign["id"], bench_id)
    record_full_test_matrix(campaign["id"], product)
    return conclude_campaign(campaign["id"])


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts for a model
# ---------------------------------------------------------------------------
def setup_frozen_product(**product_overrides) -> Dict[str, Any]:
    """Model with an APPROVED revision, a PASSED design-qualification campaign,
    and `design_status` `DESIGN_FROZEN`.

    Returns a context dict with keys: product, revision, bench,
    qualification_campaign.
    """
    product = create_product(**product_overrides)
    revision = create_approved_revision(product["id"])
    bench = create_test_bench()
    product = get_product_data(product["id"])
    campaign = run_campaign_to_passed(
        product, revision["id"], "DESIGN_QUALIFICATION", bench["id"]
    )
    product = get_success_data(
        api_client.freeze_design(
            product["id"], freeze_design_payload(revision["id"]), APPROVER
        )
    )
    return {
        "product": product,
        "revision": revision,
        "bench": bench,
        "qualification_campaign": campaign,
    }


def setup_listed_product(ctx: Optional[Dict[str, Any]] = None, **product_overrides):
    """Frozen model plus a `LISTED` listing record held by an accredited body.

    Adds keys: listing_body, listing_record, listing_campaign.
    """
    ctx = ctx or setup_frozen_product(**product_overrides)
    product, revision, bench = ctx["product"], ctx["revision"], ctx["bench"]
    body = create_listing_body()
    record = file_listing_record(product["id"], body["id"])
    listing_campaign = run_campaign_to_passed(
        product, revision["id"], "CERTIFICATION_LISTING", bench["id"]
    )
    record = get_success_data(
        api_client.grant_listing(
            record["id"], make_certification_body_headers(body["id"])
        )
    )
    ctx.update(
        {
            "listing_body": body,
            "listing_record": record,
            "listing_campaign": listing_campaign,
            "product": get_product_data(product["id"]),
        }
    )
    return ctx


def setup_retail_released_product(
    ctx: Optional[Dict[str, Any]] = None, **product_overrides
) -> Dict[str, Any]:
    """Listed model with every mandated document approved and `market_status`
    `RETAIL_RELEASED`. Adds key: documents.
    """
    ctx = ctx or setup_listed_product(**product_overrides)
    documents = approve_mandated_documents(ctx["product"]["id"])
    product = get_success_data(
        api_client.release_to_retail(ctx["product"]["id"], OFFICER)
    )
    ctx.update({"documents": documents, "product": product})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/4: production lots and joint sampling
# ---------------------------------------------------------------------------
def traceability_fields(material: str) -> Dict[str, Any]:
    """The process-traceability field the model's construction process demands."""
    if material == "ALUMINUM_EXTRUSION":
        return {"extrusion_heat_number": f"HEAT-{unique_suffix()}"}
    if material == "FIBERGLASS_PULTRUSION":
        return {"pultrusion_batch_id": f"PB-{unique_suffix()}"}
    return {}


def open_lot(product: Dict[str, Any], design_revision_id: str, **overrides) -> Dict[str, Any]:
    fields = traceability_fields(product["material"])
    fields.update(overrides)
    payload = create_production_lot_payload(
        product["id"], design_revision_id, **fields
    )
    return get_success_data(api_client.create_production_lot(payload, SUPERVISOR))


def start_lot_production(
    lot_id: str, produced_units: int = TEST_DEFAULTS["PRODUCED_UNITS"]
) -> Dict[str, Any]:
    return get_success_data(
        api_client.start_production(
            lot_id, start_production_payload(produced_units), SUPERVISOR
        )
    )


def add_joint_samples(
    lot_id: str, pull_forces: List[float], start_seq: int = 1
) -> List[Dict[str, Any]]:
    """Record one joint integrity sample per supplied pull force."""
    samples = []
    for offset, force in enumerate(pull_forces):
        payload = create_joint_sample_payload(start_seq + offset, force)
        samples.append(
            get_success_data(api_client.create_joint_sample(lot_id, payload, TECHNICIAN))
        )
    return samples


def add_passing_joint_samples(
    lot_id: str, required_pull_force_lbf: float, count: int = 4, start_seq: int = 1
) -> List[Dict[str, Any]]:
    """`count` samples five percent above the snapshot requirement, so every
    sample passes and the lot's `conformance_index` clears the release floor."""
    force = round(float(required_pull_force_lbf) * 1.05, 2)
    return add_joint_samples(lot_id, [force] * count, start_seq)


def setup_lot_in_process(
    ctx: Optional[Dict[str, Any]] = None,
    produced_units: int = TEST_DEFAULTS["PRODUCED_UNITS"],
    **product_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Retail-released model plus one lot in `IN_PROCESS` with units built."""
    ctx = ctx or setup_retail_released_product(**product_overrides)
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], produced_units)
    return ctx, lot


def setup_released_lot(
    ctx: Optional[Dict[str, Any]] = None,
    produced_units: int = TEST_DEFAULTS["PRODUCED_UNITS"],
    sample_count: int = 4,
    **product_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Retail-released model plus one `RELEASED` lot that cleared all four
    sampling gates."""
    ctx, lot = setup_lot_in_process(ctx, produced_units, **product_overrides)
    add_passing_joint_samples(
        lot["id"], ctx["product"]["required_pull_force_lbf"], sample_count
    )
    lot = get_success_data(api_client.release_production_lot(lot["id"], SUPERVISOR))
    return ctx, lot


def quarantine_lot(lot_id: str, reason_code: str = "JOINT_INTEGRITY", headers=None):
    return get_success_data(
        api_client.quarantine_production_lot(
            lot_id, quarantine_payload(reason_code), headers or SUPERVISOR
        )
    )


def dispose_lot(lot_id: str, disposition: str = "RELEASE", headers=None):
    return get_success_data(
        api_client.disposition_production_lot(
            lot_id, disposition_payload(disposition), headers or SUPERVISOR
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: consumer registrations
# ---------------------------------------------------------------------------
def register_consumer(lot_id: str, **overrides) -> Dict[str, Any]:
    payload = create_consumer_registration_payload(lot_id, **overrides)
    return get_success_data(api_client.create_consumer_registration(payload, CONSUMER))


def register_consumers(lot_id: str, count: int, **overrides) -> List[Dict[str, Any]]:
    return [register_consumer(lot_id, **overrides) for _ in range(count)]


# ---------------------------------------------------------------------------
# Tier 4: periodic audits
# ---------------------------------------------------------------------------
def plan_audit_campaign(
    ctx: Dict[str, Any],
    sampled_lot_id: str,
    sample_window_start: str,
    sample_window_end: str,
    **overrides,
) -> Dict[str, Any]:
    payload = create_audit_campaign_payload(
        ctx["product"]["id"],
        ctx["revision"]["id"],
        ctx["listing_record"]["id"],
        sampled_lot_id,
        sample_window_start,
        sample_window_end,
        **overrides,
    )
    return get_success_data(api_client.create_test_campaign(payload, TECHNICIAN))


def run_audit_campaign(
    ctx: Dict[str, Any],
    sampled_lot_id: str,
    sample_window_start: str,
    sample_window_end: str,
    failing_tests: int = 0,
    extra_tests: int = 0,
    bench_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Plan → start → record `audit_sample_size` (+ extra) load tests, of which
    `failing_tests` fail → conclude. Returns the concluded audit campaign."""
    campaign = plan_audit_campaign(
        ctx, sampled_lot_id, sample_window_start, sample_window_end
    )
    start_campaign_on_new_reservation(
        campaign["id"], bench_id or ctx["bench"]["id"]
    )
    product = get_product_data(ctx["product"]["id"])
    total = int(campaign["audit_sample_size"]) + extra_tests
    for index in range(total):
        if index < failing_tests:
            record_failing_load_test(campaign["id"], product)
        else:
            record_passing_load_test(campaign["id"], product)
    return conclude_campaign(campaign["id"])


# ---------------------------------------------------------------------------
# Tier 4/5: field incidents and corrective actions
# ---------------------------------------------------------------------------
def report_incident(product_id: str, **overrides) -> Dict[str, Any]:
    payload = create_field_incident_payload(product_id, **overrides)
    return get_success_data(api_client.create_field_incident(payload, DIRECTOR))


def investigate_incident(incident_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.investigate_field_incident(incident_id, DIRECTOR)
    )


def setup_incident_under_investigation(product_id: str, **overrides) -> Dict[str, Any]:
    incident = report_incident(product_id, **overrides)
    return investigate_incident(incident["id"])


def setup_incident_root_cause(
    product_id: str, root_cause_code: str = "RIVET_SHEAR_MARGIN", **overrides
) -> Dict[str, Any]:
    incident = setup_incident_under_investigation(product_id, **overrides)
    return get_success_data(
        api_client.resolve_investigation(
            incident["id"],
            resolve_investigation_payload("ROOT_CAUSE_IDENTIFIED", root_cause_code),
            DIRECTOR,
        )
    )


def setup_incident_not_substantiated(product_id: str, **overrides) -> Dict[str, Any]:
    incident = setup_incident_under_investigation(product_id, **overrides)
    return get_success_data(
        api_client.resolve_investigation(
            incident["id"],
            resolve_investigation_payload("NOT_SUBSTANTIATED", None),
            DIRECTOR,
        )
    )


def open_corrective_action(
    incident_id: str, author_headers: Optional[Dict] = None, **overrides
) -> Dict[str, Any]:
    incident = get_incident_data(incident_id)
    payload = create_corrective_action_payload(
        incident_id, incident["version"], **overrides
    )
    return get_success_data(
        api_client.create_corrective_action(payload, author_headers or ENGINEER)
    )


def setup_open_capa(
    product_id: str, root_cause_code: str = "RIVET_SHEAR_MARGIN", **overrides
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Incident in `CAPA_OPENED` plus its `OPEN` corrective action."""
    incident = setup_incident_root_cause(product_id, root_cause_code, **overrides)
    action = open_corrective_action(incident["id"])
    return get_incident_data(incident["id"]), action


def verify_corrective_action(action_id: str, headers: Optional[Dict] = None):
    return get_success_data(
        api_client.verify_corrective_action(action_id, headers or APPROVER)
    )


def setup_verified_capa(
    product_id: str, root_cause_code: str = "RIVET_SHEAR_MARGIN", **overrides
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Incident driven all the way to `CLOSED` through corrective-action
    verification. Returns (incident, action)."""
    incident, action = setup_open_capa(product_id, root_cause_code, **overrides)
    action = verify_corrective_action(action["id"])
    return get_incident_data(incident["id"]), action


# ---------------------------------------------------------------------------
# Tier 5: recall lifecycle
# ---------------------------------------------------------------------------
def draft_recall(
    product_id: str, affected_revision_ids: List[str], **overrides
) -> Dict[str, Any]:
    payload = create_recall_event_payload(
        product_id, affected_revision_ids, **overrides
    )
    return get_success_data(api_client.create_recall_event(payload, DIRECTOR))


def announce_recall(recall_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.announce_recall(recall_id, DIRECTOR))


def notify_recall(recall_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.notify_recall(recall_id, DIRECTOR))


def setup_announced_recall(
    ctx: Dict[str, Any], affected_revision_ids: Optional[List[str]] = None, **overrides
) -> Dict[str, Any]:
    recall = draft_recall(
        ctx["product"]["id"],
        affected_revision_ids or [ctx["revision"]["id"]],
        **overrides,
    )
    return announce_recall(recall["id"])


def setup_recall_in_progress(
    ctx: Dict[str, Any], affected_revision_ids: Optional[List[str]] = None, **overrides
) -> Dict[str, Any]:
    recall = setup_announced_recall(ctx, affected_revision_ids, **overrides)
    return notify_recall(recall["id"])


def acknowledge_registration(
    registration_id: str, remedy_choice: str = "REPAIR_KIT", headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.acknowledge_recall(
            registration_id, acknowledge_payload(remedy_choice), headers or CONSUMER
        )
    )


# ---------------------------------------------------------------------------
# Convenience: the whole chain in one call
# ---------------------------------------------------------------------------
def setup_shipping_product_with_registered_units(
    registration_count: int = 2,
    produced_units: int = TEST_DEFAULTS["PRODUCED_UNITS"],
    **product_overrides,
) -> Dict[str, Any]:
    """Retail-released model, one `RELEASED` lot, and `registration_count`
    consumer registrations against that lot.

    Returns the model context with added keys: lot, registrations.
    """
    ctx, lot = setup_released_lot(produced_units=produced_units, **product_overrides)
    registrations = register_consumers(lot["id"], registration_count)
    ctx.update(
        {
            "lot": get_lot_data(lot["id"]),
            "registrations": registrations,
            "product": get_product_data(ctx["product"]["id"]),
        }
    )
    return ctx


CLOCK_START = CLOCK_START_UTC
