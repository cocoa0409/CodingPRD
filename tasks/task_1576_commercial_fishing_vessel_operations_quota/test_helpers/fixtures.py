"""Composite setup helpers.

Each helper builds a multi-step scenario from an empty database using only
PRD-declared endpoints, using the lenient get_success_data() validator so a
broken setup fails loudly with "Setup failed" instead of a confusing assert.

Every test runs against a freshly restarted server with an empty database and
the logical clock reading exactly 2026-08-01T00:00:00Z (PRD §2.5).
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    create_catch_report_payload,
    create_crew_contract_payload,
    create_expense_payload,
    create_fishing_trip_payload,
    create_gear_asset_payload,
    create_gear_event_payload,
    create_landing_declaration_payload,
    create_observer_payload,
    create_permit_payload,
    create_quota_holding_payload,
    create_quota_transfer_payload,
    create_season_opening_payload,
    create_vessel_payload,
    create_violation_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_captain_headers,
    make_crew_member_headers,
    make_observer_headers,
    make_vessel_owner_headers,
)

REG = TEST_USERS["regulator_headers"]
CLERK = TEST_USERS["clerk_headers"]
COORD = TEST_USERS["coordinator_headers"]


# --- Tier 1: single-resource builders ---------------------------------------

def create_active_vessel(observer_coverage_class="PARTIAL", vms_unit_id=None,
                         vessel_name="FV Aurora", home_port="HOMER", length_ft=58,
                         license_number=None):
    """Register a vessel and activate it. Returns the ACTIVE vessel dict."""
    payload = create_vessel_payload(
        vessel_name=vessel_name, home_port=home_port, length_ft=length_ft,
        observer_coverage_class=observer_coverage_class,
    )
    if license_number is not None:
        payload["license_number"] = license_number
    if vms_unit_id is not None:
        payload["vms_unit_id"] = vms_unit_id
    vessel = get_success_data(api_client.create_vessel(payload, REG))
    get_success_data(api_client.activate_vessel(vessel["id"], REG))
    return get_success_data(api_client.get_vessel(vessel["id"], REG))


def create_permit(vessel_id, fishery_code="HALIBUT", gear_type="LONGLINE"):
    return get_success_data(api_client.create_permit(
        vessel_id, create_permit_payload(fishery_code=fishery_code, gear_type=gear_type), REG))


def create_holding(vessel_id, fishery_code="HALIBUT", season_year=2026, initial_pounds=10000):
    return get_success_data(api_client.create_quota_holding(
        vessel_id,
        create_quota_holding_payload(
            fishery_code=fishery_code, season_year=season_year, initial_pounds=initial_pounds),
        REG))


def create_opening(fishery_code="HALIBUT", area_code="3A",
                   opens_at="2026-08-05T00:00:00Z", closes_at="2026-08-25T00:00:00Z",
                   tac_pounds=100000):
    return get_success_data(api_client.create_season_opening(
        create_season_opening_payload(
            fishery_code=fishery_code, area_code=area_code,
            opens_at=opens_at, closes_at=closes_at, tac_pounds=tac_pounds),
        REG))


def advance_clock(to_iso8601):
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), REG))


def plan_trip(vessel_id, opening_id, departure="2026-08-10T06:00:00Z",
              return_="2026-08-12T06:00:00Z", gear_requirements=None, as_role="VesselOwner"):
    payload = create_fishing_trip_payload(
        vessel_id=vessel_id, season_opening_id=opening_id,
        planned_departure_utc=departure, planned_return_utc=return_,
    )
    if gear_requirements is not None:
        payload["gear_requirements"] = gear_requirements
    headers = (make_vessel_owner_headers(vessel_id) if as_role == "VesselOwner"
               else make_captain_headers(vessel_id))
    return get_success_data(api_client.create_fishing_trip(payload, headers))


def add_crew_contract(vessel_id, crew_name="Alice", share_points=1,
                      joined_at="2026-01-15T00:00:00Z"):
    return get_success_data(api_client.create_crew_contract(
        vessel_id,
        create_crew_contract_payload(
            crew_name=crew_name, share_points=share_points, joined_at=joined_at),
        make_vessel_owner_headers(vessel_id)))


def add_expense(trip_id, vessel_id, category="FUEL", amount_cents=120000,
                incurred_at="2026-08-11T00:00:00Z"):
    return get_success_data(api_client.create_expense(
        trip_id,
        create_expense_payload(
            category=category, amount_cents=amount_cents, incurred_at=incurred_at),
        make_captain_headers(vessel_id)))


def add_gear_asset(vessel_id, gear_type="LONGLINE", units_total=4):
    return get_success_data(api_client.create_gear_asset(
        vessel_id, create_gear_asset_payload(gear_type=gear_type, units_total=units_total),
        make_vessel_owner_headers(vessel_id)))


def add_gear_event(asset_id, vessel_id, event_type="LOSS", units=1,
                   occurred_at="2026-08-11T05:00:00Z", trip_id=None):
    payload = create_gear_event_payload(
        event_type=event_type, units=units, occurred_at=occurred_at)
    if trip_id is not None:
        payload["trip_id"] = trip_id
    return get_success_data(api_client.create_gear_event(
        asset_id, payload, make_captain_headers(vessel_id)))


def register_observer(observer_name="Obs One", certification_level="B", home_base="HOMER"):
    return get_success_data(api_client.create_observer(
        create_observer_payload(
            observer_name=observer_name,
            certification_level=certification_level,
            home_base=home_base),
        COORD))


def cite_violation(vessel_id, violation_type="OVER_QUOTA", details="citation", trip_id=None):
    payload = create_violation_payload(
        vessel_id=vessel_id, violation_type=violation_type, details=details)
    if trip_id is not None:
        payload["trip_id"] = trip_id
    return get_success_data(api_client.create_violation(payload, REG))


# --- Tier 2: vessel / fishery setup -----------------------------------------

def setup_vessel_ready(observer_coverage_class="PARTIAL", vms_unit_id=None,
                       holding_pounds=10000, fishery_code="HALIBUT",
                       gear_type="LONGLINE", with_holding=True,
                       vessel_name="FV Aurora", home_port="HOMER", length_ft=58):
    """ACTIVE vessel + ISSUED permit (+ ACTIVE quota holding). Returns ctx."""
    vessel = create_active_vessel(observer_coverage_class=observer_coverage_class,
                                  vms_unit_id=vms_unit_id, vessel_name=vessel_name,
                                  home_port=home_port, length_ft=length_ft)
    permit = create_permit(vessel["id"], fishery_code=fishery_code, gear_type=gear_type)
    holding = (create_holding(vessel["id"], fishery_code=fishery_code,
                              initial_pounds=holding_pounds)
               if with_holding else None)
    return {"vessel": vessel, "permit": permit, "holding": holding}


def setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000,
                        fishery_code="HALIBUT"):
    """Two ACTIVE vessels with ISSUED permits and holdings. Returns ctx with
    v1/p1/h1 and v2/p2/h2."""
    v1 = create_active_vessel(vessel_name="FV Aurora", home_port="HOMER")
    p1 = create_permit(v1["id"], fishery_code=fishery_code, gear_type="LONGLINE")
    h1 = create_holding(v1["id"], fishery_code=fishery_code, initial_pounds=holding1_pounds)
    v2 = create_active_vessel(observer_coverage_class="EXEMPT",
                              vessel_name="FV Bristol", home_port="KODIAK", length_ft=42)
    p2 = create_permit(v2["id"], fishery_code=fishery_code, gear_type="POT")
    h2 = create_holding(v2["id"], fishery_code=fishery_code, initial_pounds=holding2_pounds)
    return {"v1": v1, "p1": p1, "h1": h1, "v2": v2, "p2": p2, "h2": h2}


def propose_transfer(v1_id, v2_id, pounds=5000, price_per_lb_cents=400,
                     fishery_code="HALIBUT", season_year=2026):
    return get_success_data(api_client.create_quota_transfer(
        create_quota_transfer_payload(
            from_vessel_id=v1_id, to_vessel_id=v2_id, fishery_code=fishery_code,
            season_year=season_year, pounds=pounds, price_per_lb_cents=price_per_lb_cents),
        make_vessel_owner_headers(v1_id)))


def get_availability(holding_id):
    return get_success_data(api_client.get_quota_holding_availability(holding_id, REG))


# --- Tier 3: trip execution --------------------------------------------------

def get_trip_assignment(trip_id):
    """Return the (single) observer assignment row of a trip."""
    rows, _meta = _list_assignments(trip_id)
    assert len(rows) == 1, f"expected exactly one assignment for trip {trip_id}, got {len(rows)}"
    return rows[0]


def _list_assignments(trip_id):
    resp = api_client.list_observer_assignments(COORD, params={"trip_id": trip_id})
    data = validate_success(resp, 200)
    return data, resp.json()["meta"]


def list_trip_assignments(trip_id):
    rows, _meta = _list_assignments(trip_id)
    return rows


def setup_executed_trip(catch_lbs=4000, holding_pounds=10000,
                        observer_coverage_class="PARTIAL",
                        departure="2026-08-10T06:00:00Z",
                        return_="2026-08-12T06:00:00Z",
                        catch_at="2026-08-11T06:00:00Z",
                        vms_unit_id=None, tac_pounds=100000,
                        opening=None, vessel=None):
    """ACTIVE vessel + permit + holding + opening; trip departed, one HARVEST
    catch report filed, trip returned. Returns ctx with the RETURNED trip."""
    if vessel is None:
        ctx = setup_vessel_ready(observer_coverage_class=observer_coverage_class,
                                 vms_unit_id=vms_unit_id,
                                 holding_pounds=holding_pounds)
        vessel = ctx["vessel"]
        permit = ctx["permit"]
        holding = ctx["holding"]
    else:
        permit = holding = None
    if opening is None:
        opening = create_opening(tac_pounds=tac_pounds)
    advance_clock(departure)
    trip = plan_trip(vessel["id"], opening["id"], departure=departure, return_=return_)
    captain = make_captain_headers(vessel["id"])
    get_success_data(api_client.depart_trip(trip["id"], captain))
    report = get_success_data(api_client.create_catch_report(
        trip["id"], create_catch_report_payload(reported_lbs=catch_lbs, reported_at=catch_at),
        captain))
    advance_clock(return_)
    get_success_data(api_client.return_trip(trip["id"], captain))
    trip = get_success_data(api_client.get_fishing_trip(trip["id"], REG))
    return {"vessel": vessel, "permit": permit, "holding": holding,
            "opening": opening, "trip": trip, "report": report}


def declare_and_submit(trip_id, vessel_id, declared_lbs=4000, lines=None,
                       port_code="HOMER"):
    """Create the trip's landing declaration and submit it. Returns SUBMITTED
    declaration."""
    payload = create_landing_declaration_payload(port_code=port_code)
    if lines is not None:
        payload["lines"] = lines
    else:
        payload["lines"] = [{"fishery_code": "HALIBUT", "declared_lbs": declared_lbs}]
    captain = make_captain_headers(vessel_id)
    declaration = get_success_data(api_client.create_landing_declaration(
        trip_id, payload, captain))
    get_success_data(api_client.submit_landing_declaration(declaration["id"], captain))
    return get_success_data(api_client.get_landing_declaration(declaration["id"], REG))


def verify_and_finalize(declaration_id):
    get_success_data(api_client.verify_landing_declaration(declaration_id, REG))
    get_success_data(api_client.finalize_landing_declaration(declaration_id, REG))
    return get_success_data(api_client.get_landing_declaration(declaration_id, REG))


def setup_landing_finalized_trip(catch_lbs=4000, holding_pounds=10000, **kwargs):
    """Executed trip whose declaration is FINALIZED (trip LANDING_FINALIZED)."""
    ctx = setup_executed_trip(catch_lbs=catch_lbs, holding_pounds=holding_pounds, **kwargs)
    declaration = declare_and_submit(ctx["trip"]["id"], ctx["vessel"]["id"],
                                     declared_lbs=catch_lbs)
    ctx["declaration"] = verify_and_finalize(declaration["id"])
    ctx["trip"] = get_success_data(api_client.get_fishing_trip(ctx["trip"]["id"], REG))
    return ctx


# --- Tier 4: settlement scenarios -------------------------------------------

def setup_settlement_draft(gross_revenue_cents=1000000,
                           expenses=(), verify_expenses=(),
                           reject_expenses=(),
                           gear_loss_units=0,
                           crew=(("Alice", 1, "2026-01-15T00:00:00Z"),),
                           **trip_kwargs):
    """LANDING_FINALIZED trip + crew contracts + adjudicated expenses + gear
    loss + settlement created in DRAFT.

    expenses: iterable of (category, amount_cents, incurred_at)
    verify_expenses / reject_expenses: indices into the created expense list
    """
    ctx = setup_landing_finalized_trip(**trip_kwargs)
    vessel_id = ctx["vessel"]["id"]
    trip_id = ctx["trip"]["id"]
    if gear_loss_units:
        asset = add_gear_asset(vessel_id)
        add_gear_event(asset["id"], vessel_id, event_type="LOSS",
                       units=gear_loss_units, trip_id=trip_id)
        ctx["gear_asset"] = asset
    expense_rows = []
    for category, amount, incurred_at in expenses:
        expense_rows.append(add_expense(trip_id, vessel_id, category=category,
                                        amount_cents=amount, incurred_at=incurred_at))
    for i in verify_expenses:
        get_success_data(api_client.verify_expense(expense_rows[i]["id"], CLERK))
    for i in reject_expenses:
        get_success_data(api_client.reject_expense(expense_rows[i]["id"], CLERK))
    ctx["expenses"] = expense_rows
    contracts = []
    for crew_name, points, joined_at in crew:
        contracts.append(add_crew_contract(vessel_id, crew_name=crew_name,
                                           share_points=points, joined_at=joined_at))
    ctx["contracts"] = contracts
    ctx["settlement"] = get_success_data(api_client.create_trip_settlement(
        trip_id, {"gross_revenue_cents": gross_revenue_cents}, CLERK))
    return ctx


def setup_settlement_calculated(**kwargs):
    """Settlement driven through calculate. Returns ctx with CALCULATED settlement."""
    ctx = setup_settlement_draft(**kwargs)
    get_success_data(api_client.calculate_settlement(ctx["settlement"]["id"], CLERK))
    ctx["settlement"] = get_success_data(
        api_client.get_trip_settlement(ctx["settlement"]["id"], CLERK))
    return ctx


# --- Tier 5: observer-covered trips ------------------------------------------

def setup_trip_with_confirmed_observer(observer_coverage_class="FULL",
                                       certification_level="A",
                                       holding_pounds=10000,
                                       departure="2026-08-10T06:00:00Z",
                                       return_="2026-08-12T06:00:00Z",
                                       coverage_from="2026-08-10T00:00:00Z",
                                       coverage_to="2026-08-12T06:00:00Z"):
    """ACTIVE vessel + permit + holding + opening + PLANNED observer-required
    trip whose auto-created assignment is ASSIGNED then CONFIRMED."""
    ctx = setup_vessel_ready(observer_coverage_class=observer_coverage_class,
                             holding_pounds=holding_pounds)
    opening = create_opening()
    observer = register_observer(certification_level=certification_level)
    trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                     departure=departure, return_=return_)
    assignment = get_trip_assignment(trip["id"])
    get_success_data(api_client.assign_observer(
        assignment["id"],
        {"observer_id": observer["id"], "coverage_from": coverage_from,
         "coverage_to": coverage_to,
         "expected_observer_version": observer["version"]},
        COORD))
    get_success_data(api_client.confirm_observer_assignment(
        assignment["id"], make_observer_headers(observer["id"])))
    ctx.update({"opening": opening, "observer": observer, "trip": trip,
                "assignment": get_success_data(
                    api_client.get_observer_assignment(assignment["id"], COORD))})
    return ctx


# --- Tier 6: compliance scenarios -------------------------------------------

def adjudicate(violation_id):
    return get_success_data(api_client.adjudicate_violation(violation_id, REG))


def get_vessel(vessel_id):
    return get_success_data(api_client.get_vessel(vessel_id, REG))


def get_permit_status(vessel_id):
    resp = api_client.list_permits(vessel_id, REG)
    rows = validate_success(resp, 200)
    return rows[0]["status"]


def get_trip(trip_id):
    return get_success_data(api_client.get_fishing_trip(trip_id, REG))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_observer_assignment(assignment_id, COORD))


def get_observer(observer_id):
    return get_success_data(api_client.get_observer(observer_id, COORD))


def get_opening(opening_id):
    return get_success_data(api_client.get_season_opening(opening_id, REG))


def get_declaration(declaration_id):
    return get_success_data(api_client.get_landing_declaration(declaration_id, REG))


def get_transfer(transfer_id):
    return get_success_data(api_client.get_quota_transfer(transfer_id, REG))


def get_holding(holding_id):
    return get_success_data(api_client.get_quota_holding(holding_id, REG))


def get_settlement(settlement_id):
    return get_success_data(api_client.get_trip_settlement(settlement_id, CLERK))


def get_violation(violation_id):
    return get_success_data(api_client.get_violation(violation_id, REG))


def crew_headers_for(contract_id):
    return make_crew_member_headers(contract_id)
