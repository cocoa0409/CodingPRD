"""Composite setup helpers.

Every helper builds its preconditions from scratch through published endpoints
only, because each test starts against an empty database with the logical clock
at its start-up instant.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_inspector_headers,
    make_property_owner_headers,
    make_supervisor_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]

# The instant most scenarios open at: one day before the canonical field visit.
DEFAULT_CLOCK = "2026-05-04T09:00:00Z"
VISIT_START = "2026-05-05T09:00:00Z"
VISIT_END = "2026-05-05T10:00:00Z"
VISIT_COMPLETED_AT = "2026-05-05T09:45:00Z"
SERVICE_AT = "2026-05-05T10:00:00Z"

# Assessment scores used by the canonical SEVERE-tier visit (index 83.50).
SEVERE_SCORES = {
    "harborage_score": 8,
    "attractant_score": 7,
    "sanitation_score": 6,
    "burrow_count": 4,
}
# Assessment scores producing a LOW tier (index 17.50).
LOW_SCORES = {
    "harborage_score": 2,
    "attractant_score": 2,
    "sanitation_score": 1,
    "burrow_count": 0,
}

INSPECTOR_SPECS = [
    ("Iris Vega", "B-101"),
    ("Ravi Shah", "B-102"),
    ("Nia Blake", "B-103"),
]


# ---------------------------------------------------------------------------
# Tier 0: single-call primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    """Drive the program logical clock to an explicit instant."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_zone(**overrides) -> dict:
    return get_success_data(api_client.create_zone(f.create_zone_payload(**overrides), ADMIN))


def create_owner(**overrides) -> dict:
    return get_success_data(
        api_client.create_property_owner(f.create_property_owner_payload(**overrides), ADMIN)
    )


def create_property(zone_id, owner_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_property(f.create_property_payload(zone_id, owner_id, **overrides), ADMIN)
    )


def create_officer(**overrides) -> dict:
    return get_success_data(api_client.create_officer(f.create_officer_payload(**overrides), ADMIN))


def file_complaint(property_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_complaint(
            f.create_complaint_payload(property_id, **overrides), headers or CLERK
        )
    )


def triage(complaint_id, supervisor_id, severity="HIGH", **overrides) -> dict:
    return get_success_data(
        api_client.triage_complaint(
            complaint_id, f.triage_payload(severity, **overrides),
            make_supervisor_headers(supervisor_id),
        )
    )


def schedule_visit(supervisor_id, kind, officer_id, scheduled_start, scheduled_end,
                   **overrides) -> dict:
    return get_success_data(
        api_client.create_inspection(
            f.create_inspection_payload(
                kind, officer_id, scheduled_start, scheduled_end, **overrides
            ),
            make_supervisor_headers(supervisor_id),
        )
    )


def start_visit(visit_id, officer_id) -> dict:
    return get_success_data(
        api_client.start_inspection(visit_id, make_inspector_headers(officer_id))
    )


def record_assessment(visit_id, officer_id, **scores) -> dict:
    return get_success_data(
        api_client.create_assessment(
            visit_id, f.create_assessment_payload(**scores),
            make_inspector_headers(officer_id),
        )
    )


def complete_visit(visit_id, officer_id, result, **overrides) -> dict:
    return get_success_data(
        api_client.complete_inspection(
            visit_id, f.complete_inspection_payload(result, **overrides),
            make_inspector_headers(officer_id),
        )
    )


def read_property_version(property_id, supervisor_id) -> int:
    data = get_success_data(
        api_client.get_property(property_id, make_supervisor_headers(supervisor_id))
    )
    return data["version"]


def read_order_version(order_id) -> int:
    data = get_success_data(api_client.get_abatement_order(order_id, FINANCE))
    return data["version"]


def issue_order(visit_id, supervisor_id, expected_property_version, **overrides) -> dict:
    return get_success_data(
        api_client.create_abatement_order(
            f.create_abatement_order_payload(
                visit_id, expected_property_version, **overrides
            ),
            make_supervisor_headers(supervisor_id),
        )
    )


def generate_notice(order_id, notice_type="ABATEMENT_ORDER",
                    delivery_method="CERTIFIED_MAIL", headers=None) -> dict:
    return get_success_data(
        api_client.create_notice(
            order_id, f.create_notice_payload(notice_type, delivery_method),
            headers or CLERK,
        )
    )


def record_service(notice_id, service_outcome="DELIVERED") -> dict:
    return get_success_data(
        api_client.record_service_result(
            notice_id, f.service_result_payload(service_outcome), CLERK
        )
    )


def city_abate(order_id, supervisor_id, actual_labor_hours=4,
               actual_materials_cents=12000, **overrides) -> dict:
    return get_success_data(
        api_client.city_abate_order(
            order_id,
            f.city_abate_payload(actual_labor_hours, actual_materials_cents, **overrides),
            make_supervisor_headers(supervisor_id),
        )
    )


def prepare_invoice(order_id, expected_abatement_order_version, headers=None) -> dict:
    return get_success_data(
        api_client.create_invoice(
            f.create_invoice_payload(order_id, expected_abatement_order_version),
            headers or FINANCE,
        )
    )


def approve_invoice(invoice_id, headers=None, **payload) -> dict:
    return get_success_data(
        api_client.approve_invoice(
            invoice_id, payload, headers or TEST_USERS["program_admin_headers"]
        )
    )


def install_station(property_id, officer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_bait_station(
            f.create_bait_station_payload(property_id, **overrides),
            make_inspector_headers(officer_id),
        )
    )


def record_reading(station_id, officer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_reading(
            station_id, f.create_reading_payload(**overrides),
            make_inspector_headers(officer_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: the program registry
# ---------------------------------------------------------------------------


def bootstrap_registry(clock=DEFAULT_CLOCK, inspectors=1, parcels=1,
                       owner_overrides=None, parcel_specs=None,
                       zone_overrides=None, with_supervisor=True):
    """Stand up zone, owner, parcels and officers, then return an env dict.

    `parcel_specs` is an optional list of per-parcel payload overrides; when it
    is omitted `parcels` identical RESIDENTIAL_MULTI parcels are registered with
    sequential parcel numbers.
    """
    set_clock(clock)
    zone = create_zone(**(zone_overrides or {}))
    owner = create_owner(**(owner_overrides or {}))

    if parcel_specs is None:
        parcel_specs = [{} for _ in range(parcels)]
    properties = []
    for idx, spec in enumerate(parcel_specs):
        payload = dict(spec)
        payload.setdefault("parcel_number", "APN-100%d" % (idx + 1))
        payload.setdefault("address_line", "%d Elm St" % (12 + 2 * idx))
        properties.append(create_property(zone["id"], owner["id"], **payload))

    officers = []
    for idx in range(inspectors):
        name, badge = INSPECTOR_SPECS[idx]
        officers.append(
            create_officer(full_name=name, badge_number=badge, rank="FIELD_INSPECTOR")
        )

    supervisor = None
    if with_supervisor:
        supervisor = create_officer(
            full_name="Sam Cole", badge_number="B-200", rank="SUPERVISOR"
        )

    env = {
        "zone": zone,
        "zone_id": zone["id"],
        "owner": owner,
        "owner_id": owner["id"],
        "owner_headers": make_property_owner_headers(owner["id"]),
        "properties": properties,
        "inspectors": officers,
        "supervisor": supervisor,
    }
    if properties:
        env["property"] = properties[0]
        env["prop_id"] = properties[0]["id"]
    for idx, prop in enumerate(properties):
        env["prop%d_id" % (idx + 1)] = prop["id"]
    for idx, officer in enumerate(officers):
        env["insp%d_id" % (idx + 1)] = officer["id"]
        env["insp%d_headers" % (idx + 1)] = make_inspector_headers(officer["id"])
    if officers:
        env["insp_id"] = officers[0]["id"]
        env["insp_headers"] = make_inspector_headers(officers[0]["id"])
    if supervisor is not None:
        env["sup_id"] = supervisor["id"]
        env["sup_headers"] = make_supervisor_headers(supervisor["id"])
    return env


# ---------------------------------------------------------------------------
# Tier 2: a complaint walked to a chosen point of its lifecycle
# ---------------------------------------------------------------------------


def setup_triaged_complaint(env=None, complaint_type="HARBORAGE",
                            reported_severity="HIGH", triage_severity=None,
                            property_id=None, description=None,
                            bootstrap_kwargs=None):
    """Register a complaint on a parcel and triage it. Returns (env, complaint)."""
    if env is None:
        env = bootstrap_registry(**(bootstrap_kwargs or {}))
    payload = {"complaint_type": complaint_type, "reported_severity": reported_severity}
    if description is not None:
        payload["description"] = description
    complaint = file_complaint(property_id or env["prop_id"], **payload)
    triaged = triage(
        complaint["id"], env["sup_id"], triage_severity or reported_severity
    )
    return env, triaged


def setup_in_progress_visit(env=None, officer_index=1, scores=None,
                            with_assessment=False, scheduled_start=VISIT_START,
                            scheduled_end=VISIT_END, start_clock=VISIT_START,
                            bootstrap_kwargs=None, complaint_type="HARBORAGE",
                            reported_severity="HIGH", triage_severity=None,
                            property_id=None):
    """Triaged complaint -> scheduled visit -> visit started (optionally with the
    assessment already recorded). Returns (env, complaint, visit)."""
    if env is None:
        bootstrap_kwargs = dict(bootstrap_kwargs or {})
        bootstrap_kwargs.setdefault("inspectors", max(officer_index, 1))
        env = bootstrap_registry(**bootstrap_kwargs)
    env, complaint = setup_triaged_complaint(
        env, complaint_type=complaint_type, reported_severity=reported_severity,
        triage_severity=triage_severity, property_id=property_id,
    )
    officer_id = env["insp%d_id" % officer_index]
    visit = schedule_visit(
        env["sup_id"], "INITIAL", officer_id, scheduled_start, scheduled_end,
        complaint_id=complaint["id"],
    )
    set_clock(start_clock)
    visit = start_visit(visit["id"], officer_id)
    if with_assessment:
        record_assessment(visit["id"], officer_id, **(scores or SEVERE_SCORES))
    return env, complaint, visit


def setup_completed_violation_visit(env=None, officer_index=1, scores=None,
                                    completed_at=VISIT_COMPLETED_AT,
                                    **visit_kwargs):
    """Walk a visit through to COMPLETED with result VIOLATION_FOUND.

    Returns (env, complaint, visit) with the parcel already re-scored by the
    reviewed chronic computation."""
    env, complaint, visit = setup_in_progress_visit(
        env=env, officer_index=officer_index, scores=scores or SEVERE_SCORES,
        with_assessment=True, **visit_kwargs
    )
    set_clock(completed_at)
    officer_id = env["insp%d_id" % officer_index]
    visit = complete_visit(visit["id"], officer_id, "VIOLATION_FOUND")
    return env, complaint, visit


# ---------------------------------------------------------------------------
# Tier 3: the abatement-order pipeline
# ---------------------------------------------------------------------------


def setup_issued_order(env=None, scores=None, required_actions=None,
                       officer_index=1, inspectors=2, **visit_kwargs):
    """Complaint -> visit -> VIOLATION_FOUND completion -> abatement order ISSUED.

    Returns the env dict enriched with complaint, visit and order."""
    if env is None:
        bootstrap_kwargs = visit_kwargs.pop("bootstrap_kwargs", {})
        bootstrap_kwargs.setdefault("inspectors", inspectors)
        env = bootstrap_registry(**bootstrap_kwargs)
    env, complaint, visit = setup_completed_violation_visit(
        env=env, officer_index=officer_index, scores=scores or SEVERE_SCORES,
        **visit_kwargs
    )
    version = read_property_version(env["prop_id"], env["sup_id"])
    overrides = {}
    if required_actions is not None:
        overrides["required_actions"] = required_actions
    order = issue_order(visit["id"], env["sup_id"], version, **overrides)
    env.update({
        "complaint": complaint,
        "comp_id": complaint["id"],
        "visit": visit,
        "visit_id": visit["id"],
        "order": order,
        "order_id": order["id"],
    })
    return env


def setup_served_order(env=None, serve_at=SERVICE_AT, delivery_method="CERTIFIED_MAIL",
                       service_outcome="DELIVERED", education_advisory=False,
                       **order_kwargs):
    """An abatement order carried through to SERVED by a served statutory notice."""
    env = setup_issued_order(env=env, **order_kwargs)
    notice = generate_notice(
        env["order_id"], "ABATEMENT_ORDER", delivery_method
    )
    set_clock(serve_at)
    record_service(notice["id"], service_outcome)
    env["notice"] = notice
    env["notice_id"] = notice["id"]
    if education_advisory:
        advisory = generate_notice(
            env["order_id"], "EDUCATIONAL_ADVISORY", "FIRST_CLASS_MAIL"
        )
        record_service(advisory["id"], "DELIVERED")
        env["advisory_notice_id"] = advisory["id"]
    env["order"] = get_success_data(
        api_client.get_abatement_order(env["order_id"], make_supervisor_headers(env["sup_id"]))
    )
    return env


def setup_escalated_order(env=None, reinspection_officer_index=2,
                          reinspection_start=None, reinspection_end=None,
                          start_clock=None, complete_clock=None, **served_kwargs):
    """A SERVED order pushed once round the negotiation loop: a re-inspection is
    booked on the compliance deadline and returns NON_COMPLIANT, leaving the
    order ESCALATED at escalation_level 1."""
    env = setup_served_order(env=env, **served_kwargs)
    deadline = env["order"]["compliance_deadline"]
    start = reinspection_start or deadline.replace(".000Z", "Z")
    end = reinspection_end or _plus_one_hour(start)
    officer_id = env["insp%d_id" % reinspection_officer_index]
    reinspection = schedule_visit(
        env["sup_id"], "REINSPECTION", officer_id, start, end,
        abatement_order_id=env["order_id"],
    )
    set_clock(start_clock or start)
    start_visit(reinspection["id"], officer_id)
    set_clock(complete_clock or _plus_minutes(start, 30))
    complete_visit(reinspection["id"], officer_id, "NON_COMPLIANT")
    env["reinspection"] = reinspection
    env["reinspection_id"] = reinspection["id"]
    env["order"] = get_success_data(
        api_client.get_abatement_order(env["order_id"], make_supervisor_headers(env["sup_id"]))
    )
    return env


def setup_city_abated_order(env=None, route="ESCALATED", actual_labor_hours=5.5,
                            actual_materials_cents=18750, abate_at=None,
                            **kwargs):
    """Record the city abatement, from either fork into CITY_ABATED.

    route "ESCALATED" runs the negotiation loop first; route "SERVED" jumps
    straight from SERVED once the compliance deadline has arrived."""
    if route == "ESCALATED":
        env = setup_escalated_order(env=env, **kwargs)
        instant = abate_at or "2026-05-12T11:00:00Z"
    else:
        env = setup_served_order(env=env, **kwargs)
        instant = abate_at or env["order"]["compliance_deadline"].replace(".000Z", "Z")
    set_clock(instant)
    order = city_abate(
        env["order_id"], env["sup_id"], actual_labor_hours, actual_materials_cents
    )
    env["order"] = order
    env["abated_at"] = instant
    return env


# ---------------------------------------------------------------------------
# Tier 4: cost recovery
# ---------------------------------------------------------------------------


def setup_draft_invoice(env=None, **abatement_kwargs):
    """A CITY_ABATED order with a DRAFT cost-recovery invoice prepared on it."""
    if env is None or "order_id" not in env:
        env = setup_city_abated_order(env=env, **abatement_kwargs)
    version = read_order_version(env["order_id"])
    invoice = prepare_invoice(env["order_id"], version)
    env["invoice"] = invoice
    env["inv_id"] = invoice["id"]
    return env


def setup_approved_invoice(env=None, escalated_approval=None, **draft_kwargs):
    """A DRAFT invoice approved by a ProgramAdmin who is not its preparer."""
    env = setup_draft_invoice(env=env, **draft_kwargs)
    payload = {}
    if escalated_approval is not None:
        payload["escalated_approval"] = escalated_approval
    invoice = approve_invoice(env["inv_id"], **payload)
    env["invoice"] = invoice
    return env


# ---------------------------------------------------------------------------
# Tier 5: surveillance
# ---------------------------------------------------------------------------


def setup_zone_with_station(env=None, station_code="BS-01",
                            bait_type="BAIT_BLOCK", **bootstrap_kwargs):
    """A zone holding one parcel with a single ACTIVE bait station on it."""
    if env is None:
        bootstrap_kwargs.setdefault("inspectors", 1)
        env = bootstrap_registry(**bootstrap_kwargs)
    station = install_station(
        env["prop_id"], env["insp_id"],
        station_code=station_code, bait_type=bait_type,
    )
    env["station"] = station
    env["station_id"] = station["id"]
    return env


# ---------------------------------------------------------------------------
# Small time helpers used to derive follow-on windows from a booked one
# ---------------------------------------------------------------------------


def _parse(instant: str):
    from datetime import datetime

    return datetime.strptime(
        instant.replace(".000Z", "Z"), "%Y-%m-%dT%H:%M:%SZ"
    )


def _render(moment) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _plus_one_hour(instant: str) -> str:
    from datetime import timedelta

    return _render(_parse(instant) + timedelta(hours=1))


def _plus_minutes(instant: str, minutes: int) -> str:
    from datetime import timedelta

    return _render(_parse(instant) + timedelta(minutes=minutes))


def setup_repeat_offender_parcel():
    """A parcel with one confirmed violation already on file and a second visit
    under way exactly 100 days later.

    The first visit completed on 2026-01-25T10:00:00Z carrying an assessment
    that scored 43.50; the second visit is IN_PROGRESS on 2026-05-05 with no
    assessment recorded yet. Returns the env dict with `visit_id` naming the
    second, still-open visit."""
    env = bootstrap_registry(
        clock="2026-01-20T09:00:00Z", inspectors=1,
        parcel_specs=[{"property_type": "RESIDENTIAL_MULTI", "unit_count": 6}],
    )
    first_complaint = file_complaint(
        env["prop_id"], complaint_type="HARBORAGE", reported_severity="HIGH",
        reporter_name="Ann Park",
    )
    triage(first_complaint["id"], env["sup_id"], "HIGH")
    first_visit = schedule_visit(
        env["sup_id"], "INITIAL", env["insp_id"],
        "2026-01-25T09:00:00Z", "2026-01-25T10:00:00Z",
        complaint_id=first_complaint["id"],
    )
    set_clock("2026-01-25T09:00:00Z")
    start_visit(first_visit["id"], env["insp_id"])
    record_assessment(
        first_visit["id"], env["insp_id"], harborage_score=4, attractant_score=4,
        sanitation_score=3, burrow_count=2, evidence_photo_count=2,
    )
    set_clock("2026-01-25T10:00:00Z")
    complete_visit(first_visit["id"], env["insp_id"], "VIOLATION_FOUND",
                   notes="Harborage confirmed")

    set_clock("2026-05-05T08:00:00Z")
    second_complaint = file_complaint(
        env["prop_id"], complaint_type="GARBAGE_ACCUMULATION",
        reporter_type="AGENCY", description="Refuse piled behind the building",
        reported_severity="HIGH",
    )
    triage(second_complaint["id"], env["sup_id"], "HIGH")
    second_visit = schedule_visit(
        env["sup_id"], "INITIAL", env["insp_id"],
        "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z",
        complaint_id=second_complaint["id"],
    )
    set_clock("2026-05-05T09:00:00Z")
    second_visit = start_visit(second_visit["id"], env["insp_id"])

    env.update({
        "first_complaint": first_complaint,
        "first_visit": first_visit,
        "complaint": second_complaint,
        "comp_id": second_complaint["id"],
        "visit": second_visit,
        "visit_id": second_visit["id"],
    })
    return env


def setup_certification_expiring_officer(expires_at="2026-05-05T09:00:00Z",
                                         clock=DEFAULT_CLOCK,
                                         visit_start=VISIT_START,
                                         visit_end=VISIT_END):
    """A scheduled visit whose assigned officer's certification lapses exactly at
    the instant the clock is moved to."""
    set_clock(clock)
    zone = create_zone()
    owner = create_owner()
    parcel = create_property(zone["id"], owner["id"])
    officer = create_officer(
        full_name="Iris Vega", badge_number="B-101", rank="FIELD_INSPECTOR",
        certification_expires_at=expires_at,
    )
    supervisor = create_officer(
        full_name="Sam Cole", badge_number="B-200", rank="SUPERVISOR"
    )
    complaint = file_complaint(
        parcel["id"], complaint_type="HARBORAGE", reported_severity="HIGH"
    )
    triage(complaint["id"], supervisor["id"], "HIGH")
    visit = schedule_visit(
        supervisor["id"], "INITIAL", officer["id"], visit_start, visit_end,
        complaint_id=complaint["id"],
    )
    set_clock(visit_start)
    return {
        "zone_id": zone["id"],
        "owner_id": owner["id"],
        "prop_id": parcel["id"],
        "insp_id": officer["id"],
        "insp1_id": officer["id"],
        "sup_id": supervisor["id"],
        "sup_headers": make_supervisor_headers(supervisor["id"]),
        "comp_id": complaint["id"],
        "visit": visit,
        "visit_id": visit["id"],
    }
