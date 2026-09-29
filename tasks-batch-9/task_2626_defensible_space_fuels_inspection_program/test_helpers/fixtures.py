"""Composite setup builders for the fire-district API.

The PRD's interesting behaviour lives deep inside a long lifecycle: a cycle must
be activated before an inspection can be scheduled, an inspection must be
noticed before it can be completed, a notice must be overdue before abatement
can be authorised, and an order must be verified before cost recovery exists.
Rebuilding that prefix inline in every test would bury the behaviour under
setup, so this module exposes one builder per interesting resting state.

Every builder returns plain dictionaries of already-validated response data, and
each takes the client as its first argument so a test can compose them freely.

Note that the harness restarts the server before each test, so every builder
starts from an empty district with the logical clock at its initial value.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from . import factories as f
from .api_client import FireDistrictClient
from .constants import EPOCH_CLOCK_UTC, PROGRAM_TYPE_GRANT
from .test_users import (
    FIRE_MARSHAL_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    SECOND_FIRE_MARSHAL_HEADERS,
    TITLE_AGENT_HEADERS,
    make_community_organizer_headers,
    make_contractor_headers,
    make_inspector_headers,
    make_property_owner_headers,
)

ADMIN = PROGRAM_ADMIN_HEADERS
MARSHAL = FIRE_MARSHAL_HEADERS


@pytest.fixture
def client():
    """A client aimed at the district service under test."""
    return FireDistrictClient()


# ---------------------------------------------------------------------------
# Tier 1: logical clock and single-row creates
# ---------------------------------------------------------------------------

def set_clock(client, instant):
    """Move the logical clock; the PRD guarantees no transitions fire."""
    return validate_success(client.set_clock(instant, headers=ADMIN))


def create_cycle(client, season_year=2026, **overrides):
    return validate_success(
        client.create_cycle(f.cycle_payload(season_year, **overrides), headers=ADMIN),
        201,
    )


def activate_cycle(client, cycle_id):
    return validate_success(client.activate_cycle(cycle_id, headers=ADMIN))


def advance_cycle(client, cycle_id):
    return validate_success(client.advance_cycle(cycle_id, headers=ADMIN))


def close_cycle(client, cycle_id):
    return validate_success(client.close_cycle(cycle_id, headers=ADMIN))


def get_cycle(client, cycle_id, headers=None):
    return validate_success(client.get_cycle(cycle_id, headers=headers or ADMIN))


def create_community(client, **overrides):
    return validate_success(
        client.create_community(f.community_payload(**overrides), headers=ADMIN), 201
    )


def create_parcel(client, payload=None, **overrides):
    payload = payload if payload is not None else f.parcel_payload(**overrides)
    return validate_success(client.create_parcel(payload, headers=ADMIN), 201)


def create_moderate_parcel(client, **overrides):
    return create_parcel(client, f.moderate_parcel_payload(**overrides))


def create_very_high_parcel(client, **overrides):
    return create_parcel(client, f.very_high_parcel_payload(**overrides))


def create_extreme_parcel(client, **overrides):
    return create_parcel(client, f.extreme_parcel_payload(**overrides))


def create_inspector(client, **overrides):
    return validate_success(
        client.create_inspector(f.inspector_payload(**overrides), headers=ADMIN), 201
    )


def create_contractor(client, **overrides):
    return validate_success(
        client.create_contractor(f.contractor_payload(**overrides), headers=ADMIN), 201
    )


def get_parcel(client, parcel_id, headers=None):
    return validate_success(client.get_parcel(parcel_id, headers=headers or ADMIN))


def get_inspector(client, inspector_id, headers=None):
    return validate_success(
        client.get_inspector(inspector_id, headers=headers or ADMIN)
    )


def get_contractor(client, contractor_id, headers=None):
    return validate_success(
        client.get_contractor(contractor_id, headers=headers or ADMIN)
    )


def get_inspection(client, inspection_id, headers=None):
    return validate_success(
        client.get_inspection(inspection_id, headers=headers or ADMIN)
    )


def get_notice(client, notice_id, headers=None):
    return validate_success(client.get_notice(notice_id, headers=headers or ADMIN))


def get_order(client, order_id, headers=None):
    return validate_success(client.get_order(order_id, headers=headers or ADMIN))


def get_program(client, program_id, headers=None):
    return validate_success(
        client.get_support_program(program_id, headers=headers or ADMIN)
    )


def get_enrollment(client, enrollment_id, headers=None):
    return validate_success(
        client.get_enrollment(enrollment_id, headers=headers or ADMIN)
    )


def get_certificate(client, certificate_id, headers=None):
    return validate_success(
        client.get_certificate(certificate_id, headers=headers or ADMIN)
    )


def get_community(client, community_id, headers=None):
    return validate_success(
        client.get_community(community_id, headers=headers or ADMIN)
    )


def community_metrics(client, community_id, headers=None):
    return validate_success(
        client.get_community_metrics(community_id, headers=headers or ADMIN)
    )


def cycle_metrics(client, cycle_id, headers=None):
    return validate_success(
        client.get_cycle_metrics(cycle_id, headers=headers or ADMIN)
    )


def list_notices(client, headers=None, **params):
    return validate_paginated(client.list_notices(headers=headers or ADMIN, params=params))


def list_inspections(client, headers=None, **params):
    return validate_paginated(
        client.list_inspections(headers=headers or ADMIN, params=params)
    )


def list_parcels(client, headers=None, **params):
    return validate_paginated(client.list_parcels(headers=headers or ADMIN, params=params))


def list_orders(client, headers=None, **params):
    return validate_paginated(client.list_orders(headers=headers or ADMIN, params=params))


def list_payments(client, headers=None, **params):
    return validate_paginated(
        client.list_payments(headers=headers or ADMIN, params=params)
    )


def list_enrollments(client, headers=None, **params):
    return validate_paginated(
        client.list_enrollments(headers=headers or ADMIN, params=params)
    )


def list_certificates(client, headers=None, **params):
    return validate_paginated(
        client.list_certificates(headers=headers or ADMIN, params=params)
    )


def list_zone_evaluations(client, headers=None, **params):
    return validate_paginated(
        client.list_zone_evaluations(headers=headers or ADMIN, params=params)
    )


def priority_queue(client, cycle_id, headers=None, **params):
    return validate_paginated(
        client.get_priority_queue(cycle_id, headers=headers or ADMIN, params=params)
    )


# ---------------------------------------------------------------------------
# Tier 2: single lifecycle steps
# ---------------------------------------------------------------------------

def open_cycle(client, clock=EPOCH_CLOCK_UTC, season_year=2026, **overrides):
    """Set the clock, register a season and activate it."""
    if clock is not None:
        set_clock(client, clock)
    cycle = create_cycle(client, season_year, **overrides)
    return activate_cycle(client, cycle["id"])


def schedule_inspection(
    client,
    parcel_id,
    cycle_id,
    inspector_id,
    scheduled_start_utc="2026-08-20T09:00:00Z",
    scheduled_end_utc="2026-08-20T11:00:00Z",
    **overrides
):
    payload = f.inspection_payload(
        parcel_id,
        cycle_id,
        inspector_id,
        scheduled_start_utc,
        scheduled_end_utc,
        **overrides
    )
    return validate_success(client.create_inspection(payload, headers=ADMIN), 201)


def serve_notice(client, inspection_id, notice_method="CERTIFIED_MAIL"):
    """Serve the advance-notice of inspection required before any site visit."""
    return validate_success(
        client.serve_notice(
            inspection_id, f.notice_service_payload(notice_method), headers=ADMIN
        )
    )


def add_zone(client, inspection_id, inspector_id, zone, measured_clearance_ft, **kw):
    return validate_success(
        client.create_zone_evaluation(
            inspection_id,
            f.zone_payload(zone, measured_clearance_ft, **kw),
            headers=make_inspector_headers(inspector_id),
        ),
        201,
    )


def add_finding(client, inspection_id, inspector_id, item_code, status):
    return validate_success(
        client.create_hardening_finding(
            inspection_id,
            f.finding_payload(item_code, status),
            headers=make_inspector_headers(inspector_id),
        ),
        201,
    )


# Deficient clearances for the canonical HIGH-risk profile (slope_pct 30, so a
# 1.25 slope factor): every zone falls short, and ZONE_1 is the worst at MAJOR.
FAIL_CLEARANCES = {"ZONE_0_EMBER": 5.0, "ZONE_1": 15.0, "ZONE_2": 118.0}

# Clearances that meet or exceed every required distance for the same profile.
PASS_CLEARANCES = {"ZONE_0_EMBER": 10.0, "ZONE_1": 40.0, "ZONE_2": 130.0}


def add_zones(client, inspection_id, inspector_id, clearances=None):
    """Record exactly one evaluation for each of the three defensible-space zones."""
    clearances = clearances or FAIL_CLEARANCES
    rows = {}
    for zone in ("ZONE_0_EMBER", "ZONE_1", "ZONE_2"):
        rows[zone] = add_zone(
            client, inspection_id, inspector_id, zone, clearances[zone]
        )
    return rows


def complete_inspection(
    client, inspection_id, inspector_id, result="FAIL", violation_notice_method=None
):
    return validate_success(
        client.complete_inspection(
            inspection_id,
            headers=make_inspector_headers(inspector_id),
            payload=f.complete_inspection_payload(result, violation_notice_method),
        )
    )


def notice_for_parcel(client, parcel_id, status=None):
    """The single most recent notice standing against a parcel."""
    params = {"parcel_id": parcel_id}
    if status is not None:
        params["status"] = status
    rows, _meta = list_notices(client, **params)
    assert rows, "expected at least one notice for parcel %s" % parcel_id
    return rows[-1]


# ---------------------------------------------------------------------------
# Tier 3: inspection resting states
# ---------------------------------------------------------------------------

def noticed_world(
    client,
    clock=EPOCH_CLOCK_UTC,
    parcel_payload=None,
    certification_level="ADVANCED",
    scheduled_start_utc="2026-08-20T09:00:00Z",
    scheduled_end_utc="2026-08-20T11:00:00Z",
    notice_method="CERTIFIED_MAIL",
    season_year=2026,
):
    """An active cycle with one parcel whose inspection has been noticed."""
    cycle = open_cycle(client, clock, season_year)
    inspector = create_inspector(client, certification_level=certification_level)
    parcel = create_parcel(client, parcel_payload)
    inspection = schedule_inspection(
        client,
        parcel["id"],
        cycle["id"],
        inspector["id"],
        scheduled_start_utc,
        scheduled_end_utc,
    )
    inspection = serve_notice(client, inspection["id"], notice_method)
    return {
        "cycle": cycle,
        "inspector": inspector,
        "parcel": parcel,
        "inspection": inspection,
    }


def failed_world(
    client, clearances=None, violation_notice_method=None, fail_at=None, **kw
):
    """A completed FAIL inspection, its cascade applied and its notice ISSUED.

    ``fail_at`` moves the clock forward just before completion, which is how a
    notice can be issued later than some other row was created.
    """
    world = noticed_world(client, **kw)
    world["zones"] = add_zones(
        client, world["inspection"]["id"], world["inspector"]["id"], clearances
    )
    if fail_at is not None:
        set_clock(client, fail_at)
    world["inspection"] = complete_inspection(
        client,
        world["inspection"]["id"],
        world["inspector"]["id"],
        "FAIL",
        violation_notice_method,
    )
    world["notice"] = notice_for_parcel(client, world["parcel"]["id"])
    world["parcel"] = get_parcel(client, world["parcel"]["id"])
    return world


def passed_world(client, **kw):
    """A completed PASS inspection, leaving the parcel COMPLIANT."""
    world = noticed_world(client, **kw)
    world["zones"] = add_zones(
        client, world["inspection"]["id"], world["inspector"]["id"], PASS_CLEARANCES
    )
    world["inspection"] = complete_inspection(
        client, world["inspection"]["id"], world["inspector"]["id"], "PASS"
    )
    world["parcel"] = get_parcel(client, world["parcel"]["id"])
    return world


def overdue_world(client, overdue_at="2026-09-06T00:00:00Z", **kw):
    """A failed parcel whose compliance deadline has passed and been swept."""
    world = failed_world(client, **kw)
    set_clock(client, overdue_at)
    advance_cycle(client, world["cycle"]["id"])
    world["notice"] = get_notice(client, world["notice"]["id"])
    world["parcel"] = get_parcel(client, world["parcel"]["id"])
    return world


# ---------------------------------------------------------------------------
# Tier 4: abatement and cost recovery
# ---------------------------------------------------------------------------

def authorize_abatement(client, notice_id, estimated_cost_cents=500000):
    return validate_success(
        client.authorize_abatement(
            notice_id, f.authorize_payload(estimated_cost_cents), headers=MARSHAL
        ),
        201,
    )


def award_order(
    client,
    order_id,
    contractor_id,
    crew_hours=12.5,
    work_start_utc="2026-10-06T08:00:00Z",
    work_end_utc="2026-10-06T16:00:00Z",
):
    return validate_success(
        client.award_order(
            order_id,
            f.award_payload(contractor_id, crew_hours, work_start_utc, work_end_utc),
            headers=MARSHAL,
        )
    )


def complete_work(client, order_id, contractor_id, actual_crew_hours=12.5,
                  green_waste_tons=3.25):
    return validate_success(
        client.complete_work(
            order_id,
            f.complete_work_payload(actual_crew_hours, green_waste_tons),
            headers=make_contractor_headers(contractor_id),
        )
    )


def verify_completion(client, order_id, inspector_id, verified_note=None):
    return validate_success(
        client.verify_completion(
            order_id,
            headers=make_inspector_headers(inspector_id),
            payload=f.verify_completion_payload(verified_note),
        )
    )


def record_payment(client, order_id, amount_cents, method="CHECK", headers=None):
    return validate_success(
        client.record_payment(
            order_id, f.payment_payload(amount_cents, method), headers=headers or ADMIN
        ),
        201,
    )


def authorized_world(
    client, authorize_at="2026-10-06T00:00:00Z", estimated_cost_cents=500000, **kw
):
    """An overdue notice escalated into an AUTHORIZED abatement order."""
    world = overdue_world(client, **kw)
    if authorize_at is not None:
        set_clock(client, authorize_at)
    world["order"] = authorize_abatement(
        client, world["notice"]["id"], estimated_cost_cents
    )
    world["notice"] = get_notice(client, world["notice"]["id"])
    world["parcel"] = get_parcel(client, world["parcel"]["id"])
    return world


def awarded_world(
    client,
    crew_hours=12.5,
    work_start_utc="2026-10-06T08:00:00Z",
    work_end_utc="2026-10-06T16:00:00Z",
    contractor_overrides=None,
    **kw
):
    """An AWARDED order with the contractor's crew hours committed."""
    world = authorized_world(client, **kw)
    world["contractor"] = create_contractor(client, **(contractor_overrides or {}))
    world["order"] = award_order(
        client,
        world["order"]["id"],
        world["contractor"]["id"],
        crew_hours,
        work_start_utc,
        work_end_utc,
    )
    world["contractor"] = get_contractor(client, world["contractor"]["id"])
    return world


def work_complete_world(client, actual_crew_hours=12.5, green_waste_tons=3.25, **kw):
    """The contractor has reported the work as finished, awaiting verification.

    The clock is first moved to the order's ``work_start_utc`` because the PRD
    refuses a completion report before the crew's start instant.
    """
    world = awarded_world(client, **kw)
    set_clock(client, world["order"]["work_start_utc"])
    world["order"] = complete_work(
        client,
        world["order"]["id"],
        world["contractor"]["id"],
        actual_crew_hours,
        green_waste_tons,
    )
    return world


def invoiced_world(client, **kw):
    """A verified order: cost recovery computed and the invoice outstanding.

    Verification is performed by a second inspector because the PRD forbids the
    inspector who recorded the failing inspection from verifying its abatement.
    """
    world = work_complete_world(client, **kw)
    world["verifier"] = create_inspector(client)
    world["order"] = verify_completion(
        client, world["order"]["id"], world["verifier"]["id"]
    )
    world["notice"] = get_notice(client, world["notice"]["id"])
    world["parcel"] = get_parcel(client, world["parcel"]["id"])
    world["contractor"] = get_contractor(client, world["contractor"]["id"])
    return world


# ---------------------------------------------------------------------------
# Tier 5: support programmes, communities and certificates
# ---------------------------------------------------------------------------

def create_program(client, cycle_id, program_type=PROGRAM_TYPE_GRANT, **overrides):
    return validate_success(
        client.create_support_program(
            f.support_program_payload(cycle_id, program_type, **overrides),
            headers=ADMIN,
        ),
        201,
    )


def enroll(
    client,
    program_id,
    parcel_id,
    expected_program_version,
    vendor_invoice_cents=None,
    headers=None,
):
    return validate_success(
        client.create_enrollment(
            f.enrollment_payload(
                program_id, parcel_id, expected_program_version, vendor_invoice_cents
            ),
            headers=headers or ADMIN,
        ),
        201,
    )


def complete_enrollment(client, enrollment_id, attended=True):
    return validate_success(
        client.complete_enrollment(
            enrollment_id, f.complete_enrollment_payload(attended), headers=ADMIN
        )
    )


def cancel_enrollment(client, enrollment_id, headers=None, reason="Owner withdrew"):
    return validate_success(
        client.cancel_enrollment(
            enrollment_id, headers=headers or ADMIN, payload=f.reason_payload(reason)
        )
    )


def grant_world(
    client,
    clock=EPOCH_CLOCK_UTC,
    budget_total_cents=500000,
    capacity_slots=1,
    parcel_payload=None,
    **program_overrides
):
    """An active cycle carrying a cost-share grant programme and one parcel."""
    cycle = open_cycle(client, clock)
    program = create_program(
        client,
        cycle["id"],
        PROGRAM_TYPE_GRANT,
        budget_total_cents=budget_total_cents,
        capacity_slots=capacity_slots,
        **program_overrides
    )
    parcel = create_parcel(client, parcel_payload)
    return {"cycle": cycle, "program": program, "parcel": parcel}


def community_world(client, member_count=3, clock=EPOCH_CLOCK_UTC, season_year=2026):
    """An active cycle, a community in ORGANIZING and its member parcels."""
    cycle = open_cycle(client, clock, season_year)
    community = create_community(client)
    parcels = [
        create_parcel(client, f.parcel_payload(community_id=community["id"]))
        for _ in range(member_count)
    ]
    return {"cycle": cycle, "community": community, "parcels": parcels}


def open_certificate(client, parcel_id, headers=None, **overrides):
    return validate_success(
        client.open_certificate(
            parcel_id, f.certificate_payload(**overrides), headers=headers or TITLE_AGENT_HEADERS
        ),
        201,
    )


def decide_certificate(client, certificate_id, decision, note=None):
    return validate_success(
        client.certificate_decision(
            certificate_id, f.decision_payload(decision, note), headers=ADMIN
        )
    )


def issued_certificate(client, parcel_id, note="Clean defensible space record"):
    """A certificate opened and then issued against a certifiable parcel."""
    certificate = open_certificate(client, parcel_id)
    return decide_certificate(client, certificate["id"], "ISSUE", note)


def submit_certification(client, community_id, parcels_outreached_count):
    return validate_success(
        client.submit_certification(
            community_id,
            headers=make_community_organizer_headers(community_id),
            payload=f.submit_certification_payload(parcels_outreached_count),
        )
    )


def owner_headers(parcel):
    """PropertyOwner headers for the owner of a parcel."""
    return make_property_owner_headers(parcel["id"] if isinstance(parcel, dict) else parcel)
