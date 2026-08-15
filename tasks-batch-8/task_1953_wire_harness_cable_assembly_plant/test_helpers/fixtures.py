"""Composite setup helpers.

The test runner restarts the server before every test, so each test starts
against an empty database; every helper builds its preconditions from scratch
through the public API. Setup calls use the lenient get_success_data()
validator so failures surface as clear "Setup step failed" errors.

Identity threading: QualityInspector and LineOperator are entity-backed by
Operator — after creating an Operator, every inspector/operator call uses
make_quality_inspector_headers(operator["id"]) / make_line_operator_headers(...).

Logical clock: startup default is exactly 2026-08-01T00:00:00Z. Setup windows
and certification windows below are chosen to straddle that default.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as _default_api
from .factories import (
    create_applicator_payload,
    create_applicator_setup_payload,
    create_build_order_payload,
    create_certification_payload,
    create_component_payload,
    create_continuity_test_payload,
    create_consigned_lot_payload,
    create_drawing_payload,
    create_ecn_payload,
    create_hipot_test_payload,
    create_kit_issue_payload,
    create_machine_program_payload,
    create_operator_payload,
    create_pull_test_payload,
)
from .test_users import (
    TEST_USERS,
    make_line_operator_headers,
    make_quality_inspector_headers,
)

ENG = TEST_USERS["harness_engineer_headers"]
PROC = TEST_USERS["process_engineer_headers"]
QM = TEST_USERS["quality_manager_headers"]
PLAN = TEST_USERS["production_planner_headers"]
MAT = TEST_USERS["materials_clerk_headers"]
SHIP = TEST_USERS["shipping_clerk_headers"]

# A minimal single-line factory-stock BOM used by most flows.
DEFAULT_BOM = [
    {
        "find_number": "T1",
        "component_type": "TERMINAL",
        "mpn": "TERM-20",
        "qty_per_harness": 1,
        "supply_type": "FACTORY_STOCK",
        "unit_cost_cents": 100,
    }
]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creators (return parsed response data)
# ---------------------------------------------------------------------------

def make_drawing(api=None, **overrides):
    api = api or _default_api
    resp = api.create_drawing(create_drawing_payload(**overrides), ENG)
    return get_success_data(resp)


def make_component(api=None, drawing_id=None, **overrides):
    api = api or _default_api
    resp = api.create_component(create_component_payload(drawing_id, **overrides), ENG)
    return get_success_data(resp)


def release_drawing(api, drawing_id):
    api = api or _default_api
    return get_success_data(api.release_drawing(drawing_id, ENG))


def make_operator(api=None, name="Test Operator", badge="B-1000"):
    api = api or _default_api
    resp = api.create_operator(create_operator_payload(operator_name=name, badge_no=badge), QM)
    return get_success_data(resp)


def make_certification(api=None, operator_id=None, workmanship_class="IPC_CLASS_2",
                       issued_at="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z"):
    api = api or _default_api
    resp = api.create_operator_certification(
        create_certification_payload(
            operator_id,
            workmanship_class=workmanship_class,
            issued_at=issued_at,
            expires_at=expires_at,
        ),
        QM,
    )
    return get_success_data(resp)


def make_certified_operator(api=None, workmanship_class="IPC_CLASS_2", name="QI", badge="B-QI",
                            expires_at="2027-01-01T00:00:00Z"):
    """Create an operator holding an ACTIVE certification of the given class.
    Returns (operator, certification)."""
    api = api or _default_api
    operator = make_operator(api, name=name, badge=badge)
    cert = make_certification(
        api,
        operator_id=operator["id"],
        workmanship_class=workmanship_class,
        expires_at=expires_at,
    )
    return operator, cert


def make_applicator(api=None, **overrides):
    api = api or _default_api
    resp = api.create_applicator(create_applicator_payload(**overrides), PROC)
    return get_success_data(resp)


def make_machine_program(api=None, drawing_id=None, applicator_id=None, **overrides):
    api = api or _default_api
    resp = api.create_machine_program(
        create_machine_program_payload(drawing_id, applicator_id, **overrides), PROC
    )
    return get_success_data(resp)


def open_setup(api, applicator_id, program_id, setup_operator_id,
               start="2026-08-01T08:00:00Z", end="2026-08-01T09:00:00Z"):
    api = api or _default_api
    resp = api.create_applicator_setup(
        create_applicator_setup_payload(
            applicator_id, program_id, setup_operator_id,
            planned_start_at=start, planned_end_at=end,
        ),
        PROC,
    )
    return get_success_data(resp)


def close_setup(api, setup_id, closed_at="2026-08-01T09:00:00Z"):
    api = api or _default_api
    resp = api.close_applicator_setup(setup_id, {"closed_at": closed_at}, PROC)
    return get_success_data(resp)


def open_and_close_setup(api, applicator_id, program_id, setup_operator_id,
                         start="2026-08-01T08:00:00Z", end="2026-08-01T09:00:00Z",
                         closed_at=None):
    """Open a setup window and close it. Returns the CLOSED setup."""
    setup = open_setup(api, applicator_id, program_id, setup_operator_id, start, end)
    return close_setup(api, setup["id"], closed_at or end)


def record_pull_test(api, applicator_id, program_id, inspector_id,
                     sample_kind="FIRST_ARTICLE", measured_force_n=35.0):
    api = api or _default_api
    resp = api.create_crimp_pull_test(
        create_pull_test_payload(
            applicator_id, program_id,
            sample_kind=sample_kind, measured_force_n=measured_force_n,
        ),
        make_quality_inspector_headers(inspector_id),
    )
    return get_success_data(resp)


def make_consigned_lot(api=None, **overrides):
    api = api or _default_api
    resp = api.create_consigned_lot(create_consigned_lot_payload(**overrides), MAT)
    return get_success_data(resp)


def make_build_order(api=None, drawing_id=None, **overrides):
    api = api or _default_api
    resp = api.create_build_order(create_build_order_payload(drawing_id, **overrides), PLAN)
    return get_success_data(resp)


def make_ecn(api=None, drawing_id=None, **overrides):
    api = api or _default_api
    resp = api.create_ecn(create_ecn_payload(drawing_id, **overrides), ENG)
    return get_success_data(resp)


def advance_clock(api, to_iso8601):
    """Advance the logical clock (QualityManager-only test-driving endpoint)."""
    api = api or _default_api
    resp = api.set_clock({"to_iso8601": to_iso8601}, QM)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: released drawing + qualified tooling line
# ---------------------------------------------------------------------------

def make_released_drawing(api=None, bom=None, tag="RL", workmanship_class="IPC_CLASS_2",
                          customer_code="ACME", revision="A"):
    """Create a drawing with the given BOM lines and release it.
    Returns (drawing, components) where components maps find_number -> component."""
    api = api or _default_api
    bom = DEFAULT_BOM if bom is None else bom
    drawing = make_drawing(
        api,
        drawing_number=f"DWG-{tag}",
        customer_code=customer_code,
        revision=revision,
        workmanship_class=workmanship_class,
    )
    components = {}
    for spec in bom:
        spec = dict(spec)
        find = spec.pop("find_number")
        components[find] = make_component(api, drawing_id=drawing["id"], find_number=find, **spec)
    drawing = release_drawing(api, drawing["id"])
    return drawing, components


def setup_qualified_line(api=None, *, tag="QL", workmanship_class="IPC_CLASS_2",
                         bom=None, wire_gauge_awg=20, terminal_type="OPEN_BARREL",
                         terminal_mpn="TERM-20", wire_type="TXL",
                         applicator_mpn=None, first_article_force=35.0,
                         inspector=None, cert_expires_at="2027-01-01T00:00:00Z",
                         setup_start="2026-08-01T08:00:00Z",
                         setup_end="2026-08-01T09:00:00Z"):
    """Released drawing with BOM + applicator + program qualified through a
    closed setup and a passing first-article pull test by a certified inspector.

    Returns dict: drawing, components (find_number -> component), applicator,
    program, inspector, cert, setup. After this fixture the applicator is
    QUALIFIED and the program is QUALIFIED.
    """
    api = api or _default_api
    drawing, components = make_released_drawing(
        api, bom=bom, tag=tag, workmanship_class=workmanship_class
    )
    applicator = make_applicator(
        api,
        applicator_code=f"AP-{tag}",
        compatible_terminal_mpn=applicator_mpn or terminal_mpn,
    )
    program = make_machine_program(
        api,
        drawing_id=drawing["id"],
        applicator_id=applicator["id"],
        program_code=f"PG-{tag}",
        wire_gauge_awg=wire_gauge_awg,
        wire_type=wire_type,
        terminal_mpn=terminal_mpn,
        terminal_type=terminal_type,
    )
    if inspector is None:
        inspector, cert = make_certified_operator(
            api,
            workmanship_class=workmanship_class,
            name=f"QI {tag}",
            badge=f"B-QI-{tag}",
            expires_at=cert_expires_at,
        )
    else:
        cert = None
    setup = open_and_close_setup(
        api,
        applicator["id"],
        program["id"],
        inspector["id"],
        start=setup_start,
        end=setup_end,
    )
    record_pull_test(
        api,
        applicator["id"],
        program["id"],
        inspector["id"],
        sample_kind="FIRST_ARTICLE",
        measured_force_n=first_article_force,
    )
    applicator = get_success_data(api.get_applicator(applicator["id"], PROC))
    program = get_success_data(api.get_machine_program(program["id"], PROC))
    return {
        "drawing": drawing,
        "components": components,
        "applicator": applicator,
        "program": program,
        "inspector": inspector,
        "cert": cert,
        "setup": setup,
    }


def setup_line_ready_for_first_article(api=None, *, tag="FA",
                                       workmanship_class="IPC_CLASS_2", bom=None,
                                       wire_gauge_awg=20, terminal_type="OPEN_BARREL",
                                       terminal_mpn="TERM-20", wire_type="TXL",
                                       applicator_mpn=None,
                                       cert_expires_at="2027-01-01T00:00:00Z",
                                       setup_start="2026-08-01T08:00:00Z",
                                       setup_end="2026-08-01T09:00:00Z"):
    """Released drawing + applicator + DRAFT program + certified inspector +
    one CLOSED setup for the pair. No pull test recorded yet: the applicator
    is AVAILABLE with current_program_id pointing at the program — the exact
    precondition state for a FIRST_ARTICLE qualification attempt.
    """
    api = api or _default_api
    drawing, components = make_released_drawing(
        api, bom=bom, tag=tag, workmanship_class=workmanship_class
    )
    applicator = make_applicator(
        api,
        applicator_code=f"AP-{tag}",
        compatible_terminal_mpn=applicator_mpn or terminal_mpn,
    )
    program = make_machine_program(
        api,
        drawing_id=drawing["id"],
        applicator_id=applicator["id"],
        program_code=f"PG-{tag}",
        wire_gauge_awg=wire_gauge_awg,
        wire_type=wire_type,
        terminal_mpn=terminal_mpn,
        terminal_type=terminal_type,
    )
    inspector, cert = make_certified_operator(
        api,
        workmanship_class=workmanship_class,
        name=f"QI {tag}",
        badge=f"B-QI-{tag}",
        expires_at=cert_expires_at,
    )
    setup = open_and_close_setup(
        api, applicator["id"], program["id"], inspector["id"],
        start=setup_start, end=setup_end,
    )
    return {
        "drawing": drawing,
        "components": components,
        "applicator": applicator,
        "program": program,
        "inspector": inspector,
        "cert": cert,
        "setup": setup,
    }


# ---------------------------------------------------------------------------
# Tier 2: build orders, kits, issues
# ---------------------------------------------------------------------------

def release_order_to_kitting(api, order_id):
    api = api or _default_api
    return get_success_data(api.release_build_order_to_kitting(order_id, PLAN))


def get_order_kit(api, order_id, status=None):
    """Fetch this order's kit via the list endpoint filtered by build_order_id.
    With more than one kit, pass status to disambiguate (e.g. 'PICKING')."""
    api = api or _default_api
    params = {"build_order_id": order_id}
    if status is not None:
        params["status"] = status
    resp = api.list_kits(MAT, params=params)
    data, _meta = validate_paginated(resp)
    assert data, f"expected at least one kit for order {order_id}"
    return data[0]


def issue_line(api, kit_id, component_id, qty_issued, source="FACTORY_STOCK",
               consigned_lot_id=None):
    """Issue one BOM line into a PICKING kit. Returns the updated kit."""
    api = api or _default_api
    resp = api.create_kit_issue(
        kit_id,
        create_kit_issue_payload(component_id, qty_issued, source, consigned_lot_id),
        MAT,
    )
    return get_success_data(resp)


def deliver_kit(api, kit_id):
    api = api or _default_api
    return get_success_data(api.deliver_kit(kit_id, MAT))


def default_issue_plan(components, qty_ordered, default_lot_id=None):
    """Full-coverage issue plan: every BOM line at qty_per_harness * qty_ordered.
    CUSTOMER_CONSIGNED lines draw from default_lot_id."""
    plan = []
    for component in components.values():
        entry = {
            "find_number": component["find_number"],
            "qty_issued": component["qty_per_harness"] * qty_ordered,
            "source": "CONSIGNED_LOT" if component["supply_type"] == "CUSTOMER_CONSIGNED" else "FACTORY_STOCK",
        }
        if entry["source"] == "CONSIGNED_LOT":
            assert default_lot_id is not None, "consigned BOM line requires default_lot_id"
            entry["consigned_lot_id"] = default_lot_id
        plan.append(entry)
    return plan


def setup_order_in_build(api=None, *, line=None, tag="BO", qty_ordered=1,
                         material_budget_cents=None, order_code=None,
                         issue_plan=None, default_lot_id=None,
                         deliver=True, units=0, builder=None,
                         line_kwargs=None):
    """Create an order on a qualified line, release to kitting, issue the kit
    per the plan (default: full BOM coverage), optionally deliver line-side,
    then build `units` serialized harnesses as `builder`.

    Returns dict: line, order, kit, units (list), builder.
    After delivery the order is IN_BUILD; once qty_built + qty_scrapped reaches
    qty_ordered the order is TESTING.
    """
    api = api or _default_api
    if line is None:
        line = setup_qualified_line(api, tag=f"{tag}-L", **(line_kwargs or {}))
    order_kwargs = {"drawing_id": line["drawing"]["id"], "qty_ordered": qty_ordered,
                    "order_code": order_code or f"BO-{tag}"}
    if material_budget_cents is not None:
        order_kwargs["material_budget_cents"] = material_budget_cents
    order = make_build_order(api, **order_kwargs)
    order = release_order_to_kitting(api, order["id"])
    kit = get_order_kit(api, order["id"])
    plan = issue_plan
    if plan is None:
        plan = default_issue_plan(line["components"], qty_ordered, default_lot_id)
    for entry in plan:
        kit = issue_line(
            api,
            kit["id"],
            line["components"][entry["find_number"]]["id"],
            entry["qty_issued"],
            entry.get("source", "FACTORY_STOCK"),
            entry.get("consigned_lot_id"),
        )
    if deliver:
        kit = deliver_kit(api, kit["id"])
    if builder is None:
        builder = make_operator(api, name=f"LO {tag}", badge=f"B-LO-{tag}")
    built_units = []
    for _ in range(units):
        resp = api.create_harness_unit(order["id"], make_line_operator_headers(builder["id"]))
        built_units.append(get_success_data(resp))
    order = get_success_data(api.get_build_order(order["id"], PLAN))
    return {
        "line": line,
        "order": order,
        "kit": kit,
        "units": built_units,
        "builder": builder,
    }


# ---------------------------------------------------------------------------
# Tier 3: electrical testing / rework / scrap / ship lifecycle shortcuts
# ---------------------------------------------------------------------------

def record_continuity(api, unit_id, inspector_id, opens_count=0):
    api = api or _default_api
    resp = api.create_electrical_test_record(
        create_continuity_test_payload(unit_id, opens_count=opens_count),
        make_quality_inspector_headers(inspector_id),
    )
    return get_success_data(resp)


def record_hipot(api, unit_id, inspector_id, hipot_voltage_v=1000.0,
                 measured_leakage_ua=5.0, leakage_limit_ua=10.0, dwell_seconds=2.0):
    api = api or _default_api
    resp = api.create_electrical_test_record(
        create_hipot_test_payload(
            unit_id,
            hipot_voltage_v=hipot_voltage_v,
            measured_leakage_ua=measured_leakage_ua,
            leakage_limit_ua=leakage_limit_ua,
            dwell_seconds=dwell_seconds,
        ),
        make_quality_inspector_headers(inspector_id),
    )
    return get_success_data(resp)


def pass_unit_tests(api, unit_id, inspector_id, hipot_voltage_v=1000.0):
    """Record a passing continuity test and a passing hipot test on the unit.
    Returns the refreshed unit (TEST_PASS)."""
    api = api or _default_api
    record_continuity(api, unit_id, inspector_id, opens_count=0)
    record_hipot(api, unit_id, inspector_id, hipot_voltage_v=hipot_voltage_v)
    return get_success_data(api.get_harness_unit(unit_id, PLAN))


def fail_unit_into_rework(api, unit_id, inspector_id, opens_count=1):
    """Record a failing continuity test; the unit moves to REWORK."""
    return record_continuity(api, unit_id, inspector_id, opens_count=opens_count)


def complete_rework_cycle(api, unit_id, builder_id):
    api = api or _default_api
    resp = api.complete_rework(unit_id, make_line_operator_headers(builder_id))
    return get_success_data(resp)


def scrap_unit(api, unit_id, inspector_id, reason="DAMAGE"):
    api = api or _default_api
    resp = api.scrap_harness_unit(
        unit_id, {"reason": reason}, make_quality_inspector_headers(inspector_id)
    )
    return get_success_data(resp)


def ship_unit(api, unit_id):
    api = api or _default_api
    return get_success_data(api.ship_harness_unit(unit_id, SHIP))


def requalify_line(api, line, *, setup_start="2026-08-02T08:00:00Z",
                   setup_end="2026-08-02T09:00:00Z", force=31.0,
                   advance_clock_to="2026-08-02T00:00:00Z"):
    """Requalify a QUARANTINED applicator / HELD program: advance the logical
    clock past the quarantine (so the fresh setup unambiguously post-dates it),
    open + close a new setup for the pair, then record a passing FIRST_ARTICLE.
    Returns the recorded pull test."""
    api = api or _default_api
    if advance_clock_to is not None:
        advance_clock(api, advance_clock_to)
    open_and_close_setup(
        api,
        line["applicator"]["id"],
        line["program"]["id"],
        line["inspector"]["id"],
        start=setup_start,
        end=setup_end,
    )
    return record_pull_test(
        api,
        line["applicator"]["id"],
        line["program"]["id"],
        line["inspector"]["id"],
        sample_kind="FIRST_ARTICLE",
        measured_force_n=force,
    )
