"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API and
returns a context dict with the artifacts tests assert against. Setup calls use
the lenient get_success_data() so a broken precondition surfaces as a clear
"Setup failed" error instead of a confusing assertion failure.

Context keys (populated as the chain advances):
  builder, app, loads, me, invoice, commitment, permit, crew, booking,
  meter_set, plt, inspector, turn_on_events, gis
plus the matching *_headers for ownership-gated calls.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_appliance_load_payload,
    create_builder_payload,
    create_crew_booking_payload,
    create_field_crew_payload,
    create_gis_as_built_payload,
    create_inspector_payload,
    create_main_extension_payload,
    create_meter_set_payload,
    create_permit_payload,
    create_purge_leak_test_payload,
    create_service_application_payload,
    create_turn_on_event_payload,
    complete_turn_on_payload,
    payment_payload,
    record_as_built_payload,
    refund_payload,
)
from .test_users import (
    TEST_USERS,
    make_builder_headers,
    make_inspector_headers,
)

DEFAULT_LOADS = [{"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 80000}]
TWO_LOADS = [
    {"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 80000},
    {"appliance_type": "WATER_HEATER", "quantity": 1, "btuh_input_rating": 40000},
]
TWO_ASPHALT_CROSSINGS = [
    {"surface_type": "ASPHALT", "length_ft": 12.0, "width_ft": 3.0},
    {"surface_type": "ASPHALT", "length_ft": 8.0, "width_ft": 3.0},
]
ONE_ASPHALT_CROSSING = [{"surface_type": "ASPHALT", "length_ft": 12.0, "width_ft": 3.0}]

ADMIN = TEST_USERS["admin_headers"]
REP = TEST_USERS["rep_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
CLERK_B = TEST_USERS["clerk_headers"]
CLERK_C = TEST_USERS["clerk_c_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]
GIS_ANALYST = TEST_USERS["gis_analyst_headers"]


# ---------------------------------------------------------------------------
# Atomic helpers
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_builder(**overrides) -> dict:
    return get_success_data(
        api_client.create_builder(create_builder_payload(**overrides), REP),
    )


def create_application(builder: dict, **overrides) -> dict:
    headers = make_builder_headers(builder["id"])
    return get_success_data(
        api_client.create_service_application(
            create_service_application_payload(builder["id"], **overrides), headers
        )
    )


def add_load(app_id: str, builder_id: str, **load) -> dict:
    headers = make_builder_headers(builder_id)
    return get_success_data(
        api_client.create_appliance_load(
            create_appliance_load_payload(app_id, **load), headers
        )
    )


def submit_application(app_id: str, builder_id: str) -> dict:
    return get_success_data(
        api_client.submit_application(app_id, make_builder_headers(builder_id))
    )


def confirm_load(app_id: str) -> dict:
    return get_success_data(api_client.confirm_load(app_id, REP))


def create_design(app_id: str, design_footage_ft=100, crossings=None, rock=False) -> dict:
    return get_success_data(
        api_client.create_main_extension(
            create_main_extension_payload(
                app_id,
                design_footage_ft=design_footage_ft,
                crossings=list(crossings or []),
                rock_excavation_expected=rock,
            ),
            ENGINEER,
        )
    )


def submit_design(me_id: str) -> dict:
    return get_success_data(api_client.submit_design(me_id, ENGINEER))


def approve_design(me_id: str, rep_headers=None) -> dict:
    return get_success_data(api_client.approve_design(me_id, rep_headers or REP))


def accept_quote(me_id: str, builder_id: str) -> dict:
    return get_success_data(
        api_client.accept_quote(me_id, make_builder_headers(builder_id))
    )


def get_invoice_for_extension(me_id: str) -> dict:
    resp = api_client.list_ciac_invoices(CLERK_B, params={"main_extension_id": me_id})
    body = get_success_data(resp)
    assert isinstance(body, list) and len(body) == 1, (
        f"Setup failed: expected exactly one invoice for main extension {me_id}"
    )
    return body[0]


def get_commitment_for_application(app_id: str, headers=None) -> dict:
    resp = api_client.list_timeline_commitments(
        headers or REP, params={"service_application_id": app_id}
    )
    body = get_success_data(resp)
    assert isinstance(body, list) and len(body) >= 1, (
        f"Setup failed: expected a timeline commitment for application {app_id}"
    )
    return body[0]


def refresh_application(app_id: str) -> dict:
    return get_success_data(api_client.get_service_application(app_id, REP))


def refresh_main_extension(me_id: str) -> dict:
    return get_success_data(api_client.get_main_extension(me_id, ENGINEER))


def refresh_invoice(ci_id: str) -> dict:
    return get_success_data(api_client.get_ciac_invoice(ci_id, CLERK_B))


def refresh_meter_set(ms_id: str) -> dict:
    return get_success_data(api_client.get_meter_set(ms_id, TECHNICIAN))


def refresh_permit(p_id: str) -> dict:
    return get_success_data(api_client.get_permit(p_id, COORDINATOR))


def refresh_booking(bk_id: str) -> dict:
    return get_success_data(api_client.get_crew_booking(bk_id, SUPERVISOR))


def refresh_purge_leak_test(plt_id: str) -> dict:
    return get_success_data(api_client.get_purge_leak_test(plt_id, TECHNICIAN))


def refresh_commitment(tc_id: str) -> dict:
    return get_success_data(api_client.get_timeline_commitment(tc_id, REP))


def refresh_gis(gis_id: str) -> dict:
    return get_success_data(api_client.get_gis_as_built(gis_id, SUPERVISOR))


def pay_invoice(ci_id: str, amount_cents: int, clerk_headers=None, method="ACH") -> dict:
    return get_success_data(
        api_client.record_payment(
            ci_id, payment_payload(amount_cents=amount_cents, method=method),
            clerk_headers or CLERK_B,
        )
    )


def refund_invoice(ci_id: str, amount_cents: int, clerk_headers=None, method="ACH") -> dict:
    return get_success_data(
        api_client.record_refund(
            ci_id, refund_payload(amount_cents=amount_cents, method=method),
            clerk_headers or CLERK_C,
        )
    )


def create_approved_road_cut_permit(app_id: str, crossings=None, expires_at="2026-12-31") -> dict:
    permit = get_success_data(
        api_client.create_permit(
            create_permit_payload(app_id, crossings=list(crossings or ONE_ASPHALT_CROSSING)),
            COORDINATOR,
        )
    )
    get_success_data(api_client.file_permit(permit["id"], COORDINATOR))
    return get_success_data(
        api_client.record_permit_decision(
            permit["id"], {"decision": "APPROVED", "expires_at": expires_at}, COORDINATOR
        )
    )


def create_crew(specialty="GENERAL", capacity=480, name="Crew A") -> dict:
    return get_success_data(
        api_client.create_field_crew(
            create_field_crew_payload(
                crew_name=name, specialty=specialty, daily_capacity_minutes=capacity
            ),
            ADMIN,
        )
    )


def create_booking(app_id, crew_id, work_date="2026-08-10", start=540, end=1020,
                   scope="SERVICE_INSTALL") -> dict:
    return get_success_data(
        api_client.create_crew_booking(
            create_crew_booking_payload(
                app_id, crew_id, work_date=work_date, start_minute=start,
                end_minute=end, scope=scope,
            ),
            SUPERVISOR,
        )
    )


def confirm_booking(bk_id: str) -> dict:
    return get_success_data(api_client.confirm_booking(bk_id, SUPERVISOR))


def create_pressure_test_inspector(name="Insp Ray") -> dict:
    return get_success_data(
        api_client.create_inspector(create_inspector_payload(full_name=name), ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 1: application state progression
# ---------------------------------------------------------------------------
def setup_draft_app(loads=None, set_clock_to="2026-08-01T09:00:00Z", **app_overrides) -> dict:
    """Builder + DRAFT application with the given load rows (default: none)."""
    if set_clock_to:
        set_clock(set_clock_to)
    builder = create_builder()
    app = create_application(builder, **app_overrides)
    builder_headers = make_builder_headers(builder["id"])
    load_rows = [
        add_load(app["id"], builder["id"], **spec) for spec in (loads or [])
    ]
    ctx = {
        "builder": builder,
        "builder_headers": builder_headers,
        "app": app,
        "loads": load_rows,
    }
    return ctx


def setup_submitted_app(loads=None, **app_overrides) -> dict:
    """DRAFT + loads -> SUBMITTED (load calculation persisted)."""
    ctx = setup_draft_app(loads=loads if loads is not None else list(DEFAULT_LOADS),
                          **app_overrides)
    ctx["app"] = submit_application(ctx["app"]["id"], ctx["builder"]["id"])
    return ctx


def setup_load_confirmed_app(loads=None, **app_overrides) -> dict:
    """SUBMITTED -> LOAD_CONFIRMED (loads frozen)."""
    ctx = setup_submitted_app(loads=loads, **app_overrides)
    ctx["app"] = confirm_load(ctx["app"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: design / quote chain
# ---------------------------------------------------------------------------
def setup_design_app(loads=None, design_footage_ft=100, crossings=None, rock=False,
                     **app_overrides) -> dict:
    """LOAD_CONFIRMED + main extension created (application in DESIGN)."""
    ctx = setup_load_confirmed_app(loads=loads, **app_overrides)
    ctx["me"] = create_design(ctx["app"]["id"], design_footage_ft, crossings, rock)
    return ctx


def setup_quoted_app(loads=None, design_footage_ft=100, crossings=None, rock=False,
                     rep_headers=None, **app_overrides) -> dict:
    """Design submitted + approved: invoice ISSUED (or PAID at zero), commitment
    PROPOSED, application QUOTED."""
    ctx = setup_design_app(loads=loads, design_footage_ft=design_footage_ft,
                           crossings=crossings, rock=rock, **app_overrides)
    ctx["me"] = submit_design(ctx["me"]["id"])
    ctx["me"] = approve_design(ctx["me"]["id"], rep_headers=rep_headers)
    ctx["invoice"] = get_invoice_for_extension(ctx["me"]["id"])
    ctx["commitment"] = get_commitment_for_application(ctx["app"]["id"])
    ctx["app"] = refresh_application(ctx["app"]["id"])
    return ctx


def setup_ciac_pending_app(loads=None, design_footage_ft=100, crossings=None, rock=False,
                           **app_overrides) -> dict:
    """Builder accepts the quote: extension ACCEPTED, application CIAC_PENDING
    (or straight to APPROVED_FOR_CONSTRUCTION when the invoice total is zero)."""
    ctx = setup_quoted_app(loads=loads, design_footage_ft=design_footage_ft,
                           crossings=crossings, rock=rock, **app_overrides)
    ctx["me"] = accept_quote(ctx["me"]["id"], ctx["builder"]["id"])
    ctx["invoice"] = refresh_invoice(ctx["invoice"]["id"])
    ctx["app"] = refresh_application(ctx["app"]["id"])
    return ctx


def setup_paid_ciac_app(loads=None, design_footage_ft=100, crossings=None, rock=False,
                        payment_amount=None, clerk_headers=None, **app_overrides) -> dict:
    """CIAC_PENDING + one full payment -> invoice PAID, application
    APPROVED_FOR_CONSTRUCTION. payment_amount must equal the invoice balance."""
    ctx = setup_ciac_pending_app(loads=loads, design_footage_ft=design_footage_ft,
                                 crossings=crossings, rock=rock, **app_overrides)
    amount = payment_amount
    if amount is None:
        amount = ctx["invoice"]["balance_due_cents"]
    if amount:
        pay_invoice(ctx["invoice"]["id"], amount, clerk_headers=clerk_headers)
    ctx["invoice"] = refresh_invoice(ctx["invoice"]["id"])
    ctx["app"] = refresh_application(ctx["app"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: construction chain
# ---------------------------------------------------------------------------
def setup_service_installed_app(loads=None, design_footage_ft=100, crossings=None,
                                rock=False, payment_amount=None, clerk_headers=None,
                                scope="MAIN_CONSTRUCTION", specialty="MAIN_EXTENSION",
                                work_date="2026-08-10", start=540, end=1020,
                                with_permit=None, **app_overrides) -> dict:
    """Full construction path: paid/zero CIAC, (approved ROAD_CUT permit when the
    design has crossings), confirmed booking, schedule-construction, booking
    complete. Application SERVICE_INSTALLED, extension CONSTRUCTED."""
    ctx = setup_paid_ciac_app(loads=loads, design_footage_ft=design_footage_ft,
                              crossings=crossings, rock=rock,
                              payment_amount=payment_amount,
                              clerk_headers=clerk_headers, **app_overrides)
    if with_permit is None:
        with_permit = bool(crossings)
    if with_permit:
        ctx["permit"] = create_approved_road_cut_permit(ctx["app"]["id"])
    ctx["crew"] = create_crew(specialty=specialty)
    ctx["booking"] = create_booking(ctx["app"]["id"], ctx["crew"]["id"],
                                    work_date=work_date, start=start, end=end,
                                    scope=scope)
    ctx["booking"] = confirm_booking(ctx["booking"]["id"])
    ctx["app"] = get_success_data(
        api_client.schedule_construction(ctx["app"]["id"], SUPERVISOR)
    )
    ctx["booking"] = get_success_data(
        api_client.complete_booking(ctx["booking"]["id"], SUPERVISOR)
    )
    ctx["app"] = refresh_application(ctx["app"]["id"])
    ctx["me"] = refresh_main_extension(ctx["me"]["id"])
    return ctx


def setup_as_built_recorded_app(actual_footage_ft=100, actual_unit_cost_cents=4500,
                                actual_rock_excavation=False, actual_crossings=None,
                                **kwargs) -> dict:
    """SERVICE_INSTALLED + as-built recorded (extension AS_BUILT_RECORDED)."""
    ctx = setup_service_installed_app(**kwargs)
    ctx["me"] = get_success_data(
        api_client.record_as_built(
            ctx["me"]["id"],
            record_as_built_payload(
                actual_footage_ft=actual_footage_ft,
                actual_unit_cost_cents=actual_unit_cost_cents,
                actual_rock_excavation=actual_rock_excavation,
                actual_crossings=list(actual_crossings or []),
            ),
            SUPERVISOR,
        )
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: meter work / testing / turn-on chain
# ---------------------------------------------------------------------------
def setup_meter_installed_app(technician_id="tech-1", serial_number="M-9001",
                              **kwargs) -> dict:
    """SERVICE_INSTALLED + meter set created, sized, ordered, installed.
    Application METER_WORK, meter set INSTALLED."""
    from .test_users import make_technician_headers
    tech_headers = make_technician_headers(technician_id)
    ctx = setup_service_installed_app(**kwargs)
    ctx["meter_set"] = get_success_data(
        api_client.create_meter_set(create_meter_set_payload(ctx["app"]["id"]), tech_headers)
    )
    ctx["meter_set"] = get_success_data(
        api_client.size_meter_set(ctx["meter_set"]["id"], ENGINEER)
    )
    ctx["meter_set"] = get_success_data(
        api_client.mark_meter_ordered(
            ctx["meter_set"]["id"], {"serial_number": serial_number}, tech_headers
        )
    )
    ctx["meter_set"] = get_success_data(
        api_client.install_meter_set(ctx["meter_set"]["id"], tech_headers)
    )
    ctx["app"] = refresh_application(ctx["app"]["id"])
    return ctx


def record_purge_leak_test(ms_id: str, technician_id="tech-1", **overrides) -> dict:
    from .test_users import make_technician_headers
    return get_success_data(
        api_client.create_purge_leak_test(
            create_purge_leak_test_payload(ms_id, **overrides),
            make_technician_headers(technician_id),
        )
    )


def setup_testing_app(observed_drop=0.200, technician_id="tech-1", **kwargs) -> dict:
    """METER_WORK + one purge/leak test RECORDED. Meter set and application
    both in TESTING."""
    ctx = setup_meter_installed_app(technician_id=technician_id, **kwargs)
    ctx["plt"] = record_purge_leak_test(
        ctx["meter_set"]["id"], technician_id=technician_id,
        observed_pressure_drop_psi=observed_drop,
    )
    ctx["meter_set"] = refresh_meter_set(ctx["meter_set"]["id"])
    ctx["app"] = refresh_application(ctx["app"]["id"])
    return ctx


def setup_turn_on_app(observed_drop=0.200, technician_id="tech-1", **kwargs) -> dict:
    """TESTING + witness-certified PASS: meter set READY_FOR_TURN_ON,
    application TURN_ON."""
    ctx = setup_testing_app(observed_drop=observed_drop, technician_id=technician_id,
                            **kwargs)
    ctx["inspector"] = create_pressure_test_inspector()
    get_success_data(
        api_client.certify_purge_leak_test(
            ctx["plt"]["id"], make_inspector_headers(ctx["inspector"]["id"])
        )
    )
    ctx["plt"] = refresh_purge_leak_test(ctx["plt"]["id"])
    ctx["meter_set"] = refresh_meter_set(ctx["meter_set"]["id"])
    ctx["app"] = refresh_application(ctx["app"]["id"])
    return ctx


def verify_turn_on(app_id: str, load_id: str, technician_id="tech-1", **overrides) -> dict:
    """Schedule + complete one turn-on event to VERIFIED."""
    from .test_users import make_technician_headers
    tech_headers = make_technician_headers(technician_id)
    event = get_success_data(
        api_client.create_turn_on_event(
            create_turn_on_event_payload(app_id, load_id), tech_headers
        )
    )
    return get_success_data(
        api_client.complete_turn_on_event(
            event["id"], complete_turn_on_payload(**overrides), tech_headers
        )
    )


def setup_energized_app(loads=None, technician_id="tech-1", **kwargs) -> dict:
    """TURN_ON + every load row VERIFIED + energize: application ENERGIZED,
    meter set ENERGIZED."""
    load_specs = loads if loads is not None else list(DEFAULT_LOADS)
    ctx = setup_turn_on_app(loads=load_specs, technician_id=technician_id, **kwargs)
    ctx["turn_on_events"] = [
        verify_turn_on(ctx["app"]["id"], load["id"], technician_id=technician_id)
        for load in ctx["loads"]
    ]
    from .test_users import make_technician_headers
    ctx["app"] = get_success_data(
        api_client.energize_application(
            ctx["app"]["id"], make_technician_headers(technician_id)
        )
    )
    ctx["meter_set"] = refresh_meter_set(ctx["meter_set"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: GIS / completion chain
# ---------------------------------------------------------------------------
def setup_gis_review_app(depth_inches=24.0, **kwargs) -> dict:
    """ENERGIZED + GIS as-built SUBMITTED: application GIS_REVIEW."""
    ctx = setup_energized_app(**kwargs)
    ctx["gis"] = get_success_data(
        api_client.create_gis_as_built(
            create_gis_as_built_payload(ctx["app"]["id"], depth_inches=depth_inches),
            SUPERVISOR,
        )
    )
    ctx["app"] = refresh_application(ctx["app"]["id"])
    return ctx


def setup_gis_validated_app(depth_inches=24.0, **kwargs) -> dict:
    """GIS_REVIEW + as-built VALIDATED."""
    ctx = setup_gis_review_app(depth_inches=depth_inches, **kwargs)
    ctx["gis"] = get_success_data(api_client.validate_gis(ctx["gis"]["id"], GIS_ANALYST))
    return ctx
