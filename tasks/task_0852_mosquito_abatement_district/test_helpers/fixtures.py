"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the harness restarts the server (and therefore empties the
database) before every single test.  Setup calls use the lenient
``get_success_data`` validator so a broken precondition reports as a setup
failure rather than as a confusing assertion.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_applicator_payload,
    create_larval_inspection_payload,
    create_lab_pool_payload,
    create_notification_payload,
    create_pesticide_product_payload,
    create_risk_assessment_payload,
    create_sensitive_site_payload,
    create_service_area_payload,
    create_service_request_payload,
    create_trap_collection_payload,
    create_trap_site_payload,
    create_treatment_plan_payload,
    create_treatment_route_payload,
    create_weather_observation_payload,
)
from .test_users import (
    ADMIN,
    ECOLOGIST,
    LAB,
    MANAGER,
    RESIDENT,
    make_field_tech_headers,
    make_manager_headers,
    make_resident_headers,
    make_site_operator_headers,
)

CLOCK_BASE = "2026-06-01T00:00:00.000Z"


# ─── Tier 0: primitive builders ───────────────────────


def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock; only a DistrictAdmin may drive it."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_area(**overrides) -> dict:
    return get_success_data(
        api_client.create_service_area(create_service_area_payload(**overrides), ADMIN)
    )


def read_area(area_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_service_area(area_id, headers or MANAGER))


def area_version(area_id: str) -> int:
    return read_area(area_id, ECOLOGIST)["version"]


def create_applicator(**overrides) -> dict:
    return get_success_data(
        api_client.create_applicator(create_applicator_payload(**overrides), ADMIN)
    )


def set_applicator_status(applicator_id: str, status: str) -> dict:
    return get_success_data(
        api_client.set_applicator_status(applicator_id, {"status": status}, ADMIN)
    )


def read_applicator(applicator_id: str) -> dict:
    return get_success_data(api_client.get_applicator(applicator_id, MANAGER))


def create_sensitive_site(area_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sensitive_site(
            area_id, create_sensitive_site_payload(**overrides), ADMIN
        )
    )


def create_trap_site(area_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_trap_site(area_id, create_trap_site_payload(**overrides), ADMIN)
    )


def read_trap_site(trap_site_id: str) -> dict:
    return get_success_data(api_client.get_trap_site(trap_site_id, MANAGER))


def log_collection(trap_site_id: str, applicator_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_trap_collection(
            trap_site_id,
            create_trap_collection_payload(**overrides),
            make_field_tech_headers(applicator_id),
        )
    )


def submit_collection(collection_id: str, applicator_id: str) -> dict:
    return get_success_data(
        api_client.transition_trap_collection(
            collection_id, {"action": "SUBMIT"}, make_field_tech_headers(applicator_id)
        )
    )


def log_and_submit_collection(trap_site_id: str, applicator_id: str, **overrides) -> dict:
    collection = log_collection(trap_site_id, applicator_id, **overrides)
    submit_collection(collection["id"], applicator_id)
    return collection


def void_collection(collection_id: str, reason: str = "Trap knocked over") -> dict:
    return get_success_data(
        api_client.transition_trap_collection(
            collection_id, {"action": "VOID", "void_reason": reason}, MANAGER
        )
    )


def read_collection(collection_id: str) -> dict:
    return get_success_data(api_client.get_trap_collection(collection_id, MANAGER))


def create_pool(collection_id: str, pool_size: int = 50, **overrides) -> dict:
    payload = create_lab_pool_payload(pool_size=pool_size, **overrides)
    return get_success_data(api_client.create_lab_pool(collection_id, payload, LAB))


def start_pool_test(pool_id: str) -> dict:
    return get_success_data(
        api_client.transition_lab_pool(pool_id, {"action": "START_TEST"}, LAB)
    )


def record_pool_result(pool_id: str, result: str, ct_value=None) -> dict:
    payload = {"action": "RESULT", "result": result}
    if ct_value is not None:
        payload["ct_value"] = ct_value
    return get_success_data(api_client.transition_lab_pool(pool_id, payload, LAB))


def discard_pool(pool_id: str) -> dict:
    return get_success_data(
        api_client.transition_lab_pool(pool_id, {"action": "DISCARD"}, LAB)
    )


def read_pool(pool_id: str) -> dict:
    return get_success_data(api_client.get_lab_pool(pool_id, LAB))


def pool_in_testing(collection_id: str, pool_size: int = 50) -> dict:
    pool = create_pool(collection_id, pool_size)
    start_pool_test(pool["id"])
    return pool


def positive_pool(collection_id: str, pool_size: int = 50, ct_value: float = 28.4) -> dict:
    pool = pool_in_testing(collection_id, pool_size)
    record_pool_result(pool["id"], "POSITIVE", ct_value)
    return pool


def negative_pool(collection_id: str, pool_size: int = 50) -> dict:
    pool = pool_in_testing(collection_id, pool_size)
    record_pool_result(pool["id"], "NEGATIVE")
    return pool


def create_inspection(area_id: str, applicator_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_larval_inspection(
            area_id,
            create_larval_inspection_payload(**overrides),
            make_field_tech_headers(applicator_id),
        )
    )


def create_observation(area_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_weather_observation(
            area_id, create_weather_observation_payload(**overrides), ADMIN
        )
    )


def open_assessment(area_id: str, as_of_date: str = "2026-06-01", headers=None) -> dict:
    """Read the area's current version, then open an assessment guarded by it."""
    version = area_version(area_id)
    payload = create_risk_assessment_payload(version, as_of_date=as_of_date)
    return get_success_data(
        api_client.create_risk_assessment(area_id, payload, headers or ECOLOGIST)
    )


def confirm_assessment(assessment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.confirm_risk_assessment(assessment_id, headers or ECOLOGIST)
    )


def open_and_confirm_assessment(area_id: str, as_of_date: str = "2026-06-01") -> dict:
    assessment = open_assessment(area_id, as_of_date)
    return confirm_assessment(assessment["id"])


def read_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.get_risk_assessment(assessment_id, ECOLOGIST))


def create_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_pesticide_product(
            create_pesticide_product_payload(**overrides), ADMIN
        )
    )


def read_product(product_id: str) -> dict:
    return get_success_data(api_client.get_pesticide_product(product_id, MANAGER))


def create_plan(area_id: str, assessment_id: str, treatment_type: str = "LARVICIDE",
                headers=None) -> dict:
    payload = create_treatment_plan_payload(
        area_id, assessment_id, treatment_type=treatment_type
    )
    return get_success_data(
        api_client.create_treatment_plan(payload, headers or ECOLOGIST)
    )


def add_route(plan_id: str, applicator_id: str, product_id: str, headers=None,
              **overrides) -> dict:
    payload = create_treatment_route_payload(applicator_id, product_id, **overrides)
    return get_success_data(
        api_client.create_treatment_route(plan_id, payload, headers or ECOLOGIST)
    )


def plan_action(plan_id: str, action: str, headers=None, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.transition_treatment_plan(plan_id, body, headers or MANAGER)
    )


def route_action(route_id: str, action: str, headers=None, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.transition_treatment_route(route_id, body, headers or MANAGER)
    )


def read_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_treatment_plan(plan_id, MANAGER))


def read_route(route_id: str) -> dict:
    return get_success_data(api_client.get_treatment_route(route_id, MANAGER))


def issue_notification(plan_id: str, sensitive_site_id: str, **overrides) -> dict:
    payload = create_notification_payload(sensitive_site_id, **overrides)
    return get_success_data(api_client.create_notification(plan_id, payload, ADMIN))


def notification_action(notification_id: str, action: str, headers=None, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.transition_notification(notification_id, body, headers or ADMIN)
    )


def read_notification(notification_id: str) -> dict:
    return get_success_data(api_client.get_notification(notification_id, ADMIN))


def file_request(area_id: str, reporter_user_id: str = "u-res-1", **overrides) -> dict:
    payload = create_service_request_payload(area_id, **overrides)
    headers = make_resident_headers(reporter_user_id) if reporter_user_id else RESIDENT
    return get_success_data(api_client.create_service_request(payload, headers))


def request_action(request_id: str, action: str, headers=None, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.transition_service_request(request_id, body, headers or MANAGER)
    )


def read_request(request_id: str) -> dict:
    return get_success_data(api_client.get_service_request(request_id, MANAGER))


# ─── Tier 1: area / posture progression ───────────────

PRODUCT_PROFILES = {
    "LARVICIDE": {
        "name": "VectoBac 12AS",
        "epa_reg_no": "EPA-202",
        "active_ingredient": "BTI",
        "application_method": "LARVICIDE",
        "label_rate_ml_per_acre": 100.0,
        "reentry_interval_hours": 0,
        "cost_cents_per_liter": 4000,
        "received_total_ml": 100000.0,
    },
    "ADULTICIDE": {
        "name": "Permanone 30-30",
        "epa_reg_no": "EPA-101",
        "active_ingredient": "PERMETHRIN",
        "application_method": "ADULTICIDE",
        "label_rate_ml_per_acre": 100.0,
        "reentry_interval_hours": 12,
        "cost_cents_per_liter": 4000,
        "received_total_ml": 100000.0,
    },
    "AERIAL": {
        "name": "Trumpet EC",
        "epa_reg_no": "EPA-303",
        "active_ingredient": "NALED",
        "application_method": "AERIAL",
        "label_rate_ml_per_acre": 50.0,
        "reentry_interval_hours": 12,
        "cost_cents_per_liter": 3000,
        "received_total_ml": 50000.0,
    },
}


def setup_area_normal_posture(clock: str = CLOCK_BASE, area_overrides=None,
                              applicator_overrides=None) -> dict:
    """Area with a CONFIRMED assessment over an empty evidence base.

    latest_confirmed_vector_index is 0.00, so risk_posture stays NORMAL.
    """
    set_clock(clock)
    area = create_area(**(area_overrides or {}))
    applicator = create_applicator(**(applicator_overrides or {}))
    assessment = open_and_confirm_assessment(area["id"])
    return {"area": area, "applicator": applicator, "assessment": assessment}


def setup_area_emergency_posture(clock: str = CLOCK_BASE, area_overrides=None,
                                 applicator_overrides=None) -> dict:
    """Area whose confirmed vector index is 73.75, so risk_posture is EMERGENCY.

    Built from one SUBMITTED collection of 60 females over 2 trap-nights
    (abundance_index 30.00) and one RESULT_POSITIVE pool of 50 (mir 20.00).
    """
    set_clock(clock)
    area = create_area(**(area_overrides or {}))
    applicator = create_applicator(**(applicator_overrides or {}))
    trap_site = create_trap_site(area["id"])
    collection = log_and_submit_collection(
        trap_site["id"], applicator["id"],
        collection_date="2026-05-28", trap_nights=2, female_count=60,
    )
    pool = positive_pool(collection["id"])
    assessment = open_and_confirm_assessment(area["id"])
    return {
        "area": area,
        "applicator": applicator,
        "trap_site": trap_site,
        "collection": collection,
        "pool": pool,
        "assessment": assessment,
    }


# ─── Tier 2: plan / route hierarchy ───────────────────


def setup_plan_scenario(
    treatment_type: str = "LARVICIDE",
    posture: str = "NORMAL",
    clock: str = CLOCK_BASE,
    area_overrides=None,
    applicator_overrides=None,
    product_overrides=None,
    routes=None,
    approve: bool = True,
    approvers=None,
    sensitive_sites=None,
) -> dict:
    """Build a treatment plan and its routes, optionally driven to APPROVED.

    ``routes`` is a list of route payload overrides; ``sensitive_sites`` a list
    of protected-site payload overrides registered in the plan's area before the
    plan is drafted.
    """
    if posture == "EMERGENCY":
        base = setup_area_emergency_posture(clock, area_overrides, applicator_overrides)
    else:
        base = setup_area_normal_posture(clock, area_overrides, applicator_overrides)

    area, applicator = base["area"], base["applicator"]

    sites = []
    for site_overrides in (sensitive_sites or []):
        sites.append(create_sensitive_site(area["id"], **site_overrides))

    profile = dict(PRODUCT_PROFILES[treatment_type])
    profile.update(product_overrides or {})
    product = create_product(**profile)

    plan = create_plan(area["id"], base["assessment"]["id"], treatment_type)

    route_specs = routes if routes is not None else [{}]
    created_routes = []
    for index, spec in enumerate(route_specs):
        spec = dict(spec)
        spec.setdefault("route_code", f"R-{index + 1}")
        created_routes.append(
            add_route(plan["id"], applicator["id"], product["id"], **spec)
        )

    if approve:
        plan = plan_action(plan["id"], "SUBMIT", ECOLOGIST)
        signers = approvers or (
            ["u-mgr-1", "u-mgr-2"] if treatment_type == "AERIAL" else ["u-mgr-1"]
        )
        for signer in signers:
            plan = plan_action(plan["id"], "APPROVE", make_manager_headers(signer))

    bundle = dict(base)
    bundle.update({
        "product": product,
        "plan": plan,
        "routes": created_routes,
        "route": created_routes[0] if created_routes else None,
        "sites": sites,
        "site": sites[0] if sites else None,
    })
    return bundle


# ─── Tier 3: route lifecycle shortcuts ────────────────


def setup_committed_route(**kwargs) -> dict:
    """Approved plan whose first route has been COMMITTED."""
    bundle = setup_plan_scenario(**kwargs)
    bundle["route"] = route_action(bundle["route"]["id"], "COMMIT")
    return bundle


def setup_in_progress_plan(scheduled_start_at: str = "2026-06-05T09:00:00.000Z",
                           **kwargs) -> dict:
    """Committed route, plan SCHEDULED, clock advanced, plan STARTed."""
    bundle = setup_committed_route(**kwargs)
    bundle["plan"] = plan_action(
        bundle["plan"]["id"], "SCHEDULE", scheduled_start_at=scheduled_start_at
    )
    set_clock(scheduled_start_at)
    bundle["plan"] = plan_action(bundle["plan"]["id"], "START")
    return bundle


def setup_executed_route(actual_acres: float = 1.0, wind_speed_mph: float = 2.0,
                         **kwargs) -> dict:
    """Plan IN_PROGRESS whose first route has been EXECUTED by its own technician."""
    bundle = setup_in_progress_plan(**kwargs)
    bundle["route"] = route_action(
        bundle["route"]["id"], "EXECUTE",
        make_field_tech_headers(bundle["applicator"]["id"]),
        actual_acres=actual_acres, wind_speed_mph=wind_speed_mph,
    )
    return bundle


def setup_verified_route(**kwargs) -> dict:
    bundle = setup_executed_route(**kwargs)
    bundle["route"] = route_action(bundle["route"]["id"], "VERIFY")
    return bundle


def setup_completed_plan(**kwargs) -> dict:
    """Full lifecycle through COMPLETED, which writes the cost allocation."""
    bundle = setup_verified_route(**kwargs)
    bundle["plan"] = plan_action(bundle["plan"]["id"], "COMPLETE")
    return bundle


# ─── Tier 4: notice delivery shortcuts ────────────────


def setup_sent_notification(site_overrides=None, **kwargs) -> dict:
    """Approved plan with one registered protected site and a SENT notice."""
    kwargs.setdefault("sensitive_sites", [site_overrides or {}])
    bundle = setup_plan_scenario(**kwargs)
    notification = issue_notification(bundle["plan"]["id"], bundle["site"]["id"])
    bundle["notification"] = notification_action(notification["id"], "SEND")
    return bundle


def setup_acknowledged_notification(**kwargs) -> dict:
    bundle = setup_sent_notification(**kwargs)
    bundle["notification"] = notification_action(
        bundle["notification"]["id"], "ACKNOWLEDGE",
        make_site_operator_headers(bundle["site"]["id"]),
    )
    return bundle


# ─── Tier 5: complaint lifecycle shortcuts ────────────


def setup_triaged_request(priority: str = "ROUTINE", clock: str = CLOCK_BASE,
                          area_overrides=None, applicator_overrides=None,
                          request_overrides=None) -> dict:
    set_clock(clock)
    area = create_area(**(area_overrides or {}))
    applicator = create_applicator(**(applicator_overrides or {}))
    request = file_request(area["id"], **(request_overrides or {}))
    request = request_action(request["id"], "TRIAGE", priority=priority)
    return {"area": area, "applicator": applicator, "request": request}


def setup_assigned_request(**kwargs) -> dict:
    bundle = setup_triaged_request(**kwargs)
    bundle["request"] = request_action(
        bundle["request"]["id"], "ASSIGN",
        assigned_applicator_id=bundle["applicator"]["id"],
    )
    return bundle


def setup_inspected_request(verification_status: str = "FIELD_CONFIRMED", **kwargs) -> dict:
    bundle = setup_assigned_request(**kwargs)
    payload = {}
    if verification_status is not None:
        payload["verification_status"] = verification_status
    bundle["request"] = request_action(
        bundle["request"]["id"], "INSPECT",
        make_field_tech_headers(bundle["applicator"]["id"]), **payload,
    )
    return bundle


def setup_resolved_request(resolution_note: str = "Catch basin treated", **kwargs) -> dict:
    bundle = setup_inspected_request(**kwargs)
    bundle["request"] = request_action(
        bundle["request"]["id"], "RESOLVE",
        make_field_tech_headers(bundle["applicator"]["id"]),
        resolution_note=resolution_note,
    )
    return bundle


# ─── Tier 6: surveillance scenarios with pinned arithmetic ───


def setup_surveillance_dual_variant(clock: str = CLOCK_BASE) -> dict:
    """Evidence base whose provisional and confirmed variants diverge.

    Two SUBMITTED collections inside the 14-day window ending 2026-06-01
    (60 females / 2 trap-nights and 40 / 2, abundance_index 25.00); three pools of
    50 on the first collection — one positive, one negative, one still in testing;
    one inspection of 20 dips and 40 larvae; two observations whose raw daily
    degree-days are 12.55 and 11.55.  The OPEN assessment is created last.
    """
    set_clock(clock)
    area = create_area()
    applicator = create_applicator()
    trap_site = create_trap_site(area["id"])
    first = log_and_submit_collection(
        trap_site["id"], applicator["id"],
        collection_date="2026-05-28", trap_nights=2, female_count=60,
    )
    second = log_and_submit_collection(
        trap_site["id"], applicator["id"],
        collection_date="2026-05-29", trap_nights=2, female_count=40,
    )
    pool_positive = positive_pool(first["id"], 50)
    pool_negative = negative_pool(first["id"], 50)
    pool_open = pool_in_testing(first["id"], 50)
    create_inspection(
        area["id"], applicator["id"],
        inspection_date="2026-05-26", dips=20, larvae_count=40, habitat="CATCH_BASIN",
    )
    create_observation(area["id"], obs_date="2026-05-30", tmax_c=25.1, tmin_c=20.0)
    create_observation(area["id"], obs_date="2026-05-31", tmax_c=24.1, tmin_c=19.0)
    assessment = open_assessment(area["id"], "2026-06-01")
    return {
        "area": area,
        "applicator": applicator,
        "trap_site": trap_site,
        "collections": [first, second],
        "pools": {
            "positive": pool_positive,
            "negative": pool_negative,
            "in_testing": pool_open,
        },
        "assessment": assessment,
    }


def setup_single_positive_pool_assessment(female_count: int, trap_nights: int,
                                          pool_size: int = 50, ct_value: float = 26.0,
                                          clock: str = CLOCK_BASE,
                                          species: str = "CULEX_PIPIENS",
                                          trap_type: str = "CDC_LIGHT") -> dict:
    """One SUBMITTED collection plus one RESULT_POSITIVE pool, then an OPEN assessment.

    Used to drive the abundance component to a chosen value while the infection
    component sits at its 100.00 cap.
    """
    set_clock(clock)
    area = create_area()
    applicator = create_applicator()
    trap_site = create_trap_site(area["id"], trap_type=trap_type)
    collection = log_and_submit_collection(
        trap_site["id"], applicator["id"],
        collection_date="2026-05-28", trap_nights=trap_nights,
        female_count=female_count, species=species,
    )
    pool = positive_pool(collection["id"], pool_size, ct_value)
    assessment = open_assessment(area["id"], "2026-06-01")
    return {
        "area": area,
        "applicator": applicator,
        "trap_site": trap_site,
        "collection": collection,
        "pool": pool,
        "assessment": assessment,
    }


def setup_positive_cascade_scenario(clock: str = CLOCK_BASE) -> dict:
    """Everything the positive-result cascade touches, staged one step short of it.

    A SUBMITTED collection with a pool left IN_TESTING, a complaint triaged
    ROUTINE, and an OPEN assessment created after the complaint.
    """
    set_clock(clock)
    area = create_area()
    applicator = create_applicator()
    trap_site = create_trap_site(area["id"])
    collection = log_and_submit_collection(
        trap_site["id"], applicator["id"],
        collection_date="2026-05-28", trap_nights=2, female_count=60,
    )
    pool = pool_in_testing(collection["id"], 50)
    request = file_request(
        area["id"], category="ADULT_ACTIVITY",
        description="Biting at dusk in the park", x_m=300, y_m=300,
    )
    request = request_action(request["id"], "TRIAGE", priority="ROUTINE")
    assessment = open_assessment(area["id"], "2026-06-01")
    return {
        "area": area,
        "applicator": applicator,
        "trap_site": trap_site,
        "collection": collection,
        "pool": pool,
        "request": request,
        "assessment": assessment,
    }


def setup_aerial_plan_awaiting_schedule() -> dict:
    """An AERIAL plan one step short of SCHEDULE.

    EMERGENCY posture, an APIARY at (960, 1280) whose 1600 m buffer the route at
    (0, 0) touches exactly, two distinct approvers, an ACKNOWLEDGED notice for
    that apiary, and the single 40-acre route COMMITTED.
    """
    bundle = setup_plan_scenario(
        treatment_type="AERIAL",
        posture="EMERGENCY",
        sensitive_sites=[{"site_type": "APIARY", "x_m": 960, "y_m": 1280}],
        routes=[{
            "window_start": "2026-06-03T06:00:00.000Z",
            "window_end": "2026-06-03T09:00:00.000Z",
            "planned_acres": 40.0,
            "center_x_m": 0,
            "center_y_m": 0,
        }],
    )
    notification = issue_notification(
        bundle["plan"]["id"], bundle["site"]["id"], channel="EMAIL"
    )
    notification_action(notification["id"], "SEND")
    bundle["notification"] = notification_action(
        notification["id"], "ACKNOWLEDGE",
        make_site_operator_headers(bundle["site"]["id"]),
    )
    bundle["route"] = route_action(bundle["route"]["id"], "COMMIT")
    return bundle


# ─── Tier 7: commitment-gate scenarios ────────────────


def setup_adulticide_plan_at_normal_posture() -> dict:
    """An APPROVED ADULTICIDE plan whose area sits at NORMAL posture.

    One SUBMITTED collection of 60 females over 2 trap-nights and no pool at all,
    so the confirmed index is 24.00 and the posture stays NORMAL.
    """
    set_clock(CLOCK_BASE)
    area = create_area()
    applicator = create_applicator(license_category="ADULTICIDE")
    trap_site = create_trap_site(area["id"])
    collection = log_and_submit_collection(
        trap_site["id"], applicator["id"],
        collection_date="2026-05-28", trap_nights=2, female_count=60,
    )
    assessment = open_assessment(area["id"], "2026-06-01")
    assessment = confirm_assessment(assessment["id"])
    product = create_product(**PRODUCT_PROFILES["ADULTICIDE"])
    plan = create_plan(area["id"], assessment["id"], "ADULTICIDE")
    route = add_route(
        plan["id"], applicator["id"], product["id"],
        planned_acres=2.0, window_start="2026-06-05T09:00:00.000Z",
        window_end="2026-06-05T12:00:00.000Z",
    )
    plan = plan_action(plan["id"], "SUBMIT", ECOLOGIST)
    plan = plan_action(plan["id"], "APPROVE")
    return {
        "area": area,
        "applicator": applicator,
        "trap_site": trap_site,
        "collection": collection,
        "assessment": assessment,
        "product": product,
        "plan": plan,
        "route": route,
    }


def setup_occupancy_boundary_scenario() -> dict:
    """One COMMITTED route 09:00–12:00 plus two candidates at 12:44 and 12:45."""
    bundle = setup_plan_scenario(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        routes=[
            {"window_start": "2026-06-05T09:00:00.000Z",
             "window_end": "2026-06-05T12:00:00.000Z"},
            {"window_start": "2026-06-05T12:44:00.000Z",
             "window_end": "2026-06-05T13:44:00.000Z"},
            {"window_start": "2026-06-05T12:45:00.000Z",
             "window_end": "2026-06-05T13:45:00.000Z"},
        ],
    )
    bundle["routes"][0] = route_action(bundle["routes"][0]["id"], "COMMIT")
    bundle["route"] = bundle["routes"][0]
    return bundle


def setup_clearance_vs_occupancy_scenario() -> dict:
    """An un-notified APIARY at exactly 1600 m from a second, time-clashing route."""
    bundle = setup_plan_scenario(
        treatment_type="ADULTICIDE",
        posture="EMERGENCY",
        sensitive_sites=[{"site_type": "APIARY", "x_m": 960, "y_m": 1280}],
        routes=[
            {"window_start": "2026-06-05T09:00:00.000Z",
             "window_end": "2026-06-05T12:00:00.000Z",
             "planned_acres": 10.0, "center_x_m": 20000, "center_y_m": 20000},
            {"window_start": "2026-06-05T10:00:00.000Z",
             "window_end": "2026-06-05T11:00:00.000Z",
             "planned_acres": 5.0, "center_x_m": 0, "center_y_m": 0},
        ],
    )
    bundle["routes"][0] = route_action(bundle["routes"][0]["id"], "COMMIT")
    bundle["route"] = bundle["routes"][0]
    return bundle


def setup_reentry_boundary_scenario() -> dict:
    """A VERIFIED route ending 2026-06-05T12:00Z under a 12-hour re-entry interval.

    A second plan carries two candidate routes: one starting exactly at the
    end-of-quarantine instant and one starting a minute later.
    """
    bundle = setup_verified_route(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        product_overrides={"reentry_interval_hours": 12},
        routes=[{"window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T12:00:00.000Z"}],
    )
    second_plan = create_plan(
        bundle["area"]["id"], bundle["assessment"]["id"], "LARVICIDE"
    )
    boundary_route = add_route(
        second_plan["id"], bundle["applicator"]["id"], bundle["product"]["id"],
        route_code="R-2", window_start="2026-06-06T00:00:00.000Z",
        window_end="2026-06-06T01:00:00.000Z",
    )
    clear_route = add_route(
        second_plan["id"], bundle["applicator"]["id"], bundle["product"]["id"],
        route_code="R-3", window_start="2026-06-06T00:01:00.000Z",
        window_end="2026-06-06T01:01:00.000Z",
    )
    plan_action(second_plan["id"], "SUBMIT", ECOLOGIST)
    second_plan = plan_action(second_plan["id"], "APPROVE")
    bundle["second_plan"] = second_plan
    bundle["boundary_route"] = boundary_route
    bundle["clear_route"] = clear_route
    return bundle


def setup_area_at_seasonal_cap() -> dict:
    """Two EXECUTED routes in one area, plus a third APPROVED plan awaiting commit."""
    first = setup_executed_route(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        routes=[{"window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T10:00:00.000Z"}],
    )
    area, applicator, product = first["area"], first["applicator"], first["product"]
    assessment = first["assessment"]

    second_plan = create_plan(area["id"], assessment["id"], "LARVICIDE")
    second_route = add_route(
        second_plan["id"], applicator["id"], product["id"], route_code="R-2",
        window_start="2026-06-07T09:00:00.000Z", window_end="2026-06-07T10:00:00.000Z",
    )
    plan_action(second_plan["id"], "SUBMIT", ECOLOGIST)
    plan_action(second_plan["id"], "APPROVE")
    route_action(second_route["id"], "COMMIT")
    plan_action(
        second_plan["id"], "SCHEDULE", scheduled_start_at="2026-06-07T09:00:00.000Z"
    )
    set_clock("2026-06-07T09:00:00.000Z")
    plan_action(second_plan["id"], "START")
    route_action(
        second_route["id"], "EXECUTE", make_field_tech_headers(applicator["id"]),
        actual_acres=1.0, wind_speed_mph=2.0,
    )

    third_plan = create_plan(area["id"], assessment["id"], "LARVICIDE")
    third_route = add_route(
        third_plan["id"], applicator["id"], product["id"], route_code="R-3",
        window_start="2026-06-09T09:00:00.000Z", window_end="2026-06-09T10:00:00.000Z",
    )
    plan_action(third_plan["id"], "SUBMIT", ECOLOGIST)
    third_plan = plan_action(third_plan["id"], "APPROVE")

    first["second_plan"] = second_plan
    first["second_route"] = second_route
    first["third_plan"] = third_plan
    first["third_route"] = third_route
    return first


def setup_case_count_partition_area() -> dict:
    """One area holding three complaints: resolved, received, and closed.

    The area therefore reads total 3 / open 1 / resolved 1 / closed 1 before any
    compensating reopen.
    """
    set_clock(CLOCK_BASE)
    area = create_area()
    applicator = create_applicator(license_category="LARVICIDE_ONLY")

    request_a = file_request(
        area["id"], reporter_user_id="u-res-1", reporter_contact="a@example.com",
        category="STANDING_WATER", description="Standing water in alley", x_m=100, y_m=100,
    )
    request_action(request_a["id"], "TRIAGE", priority="PRIORITY")
    request_action(
        request_a["id"], "ASSIGN", assigned_applicator_id=applicator["id"]
    )
    request_action(
        request_a["id"], "INSPECT", make_field_tech_headers(applicator["id"]),
        verification_status="FIELD_CONFIRMED",
    )
    request_a = request_action(
        request_a["id"], "RESOLVE", make_field_tech_headers(applicator["id"]),
        resolution_note="Alley drained and larvicided",
    )

    request_b = file_request(
        area["id"], reporter_user_id="u-res-2", reporter_contact="b@example.com",
        category="DEAD_BIRD", description="Dead crow on the verge", x_m=200, y_m=200,
    )
    request_c = file_request(
        area["id"], reporter_user_id="u-res-3", reporter_contact="c@example.com",
        category="SPRAY_CONCERN", description="Duplicate of an earlier call",
        x_m=300, y_m=300,
    )
    request_c = request_action(request_c["id"], "CLOSE")

    return {
        "area": area,
        "applicator": applicator,
        "request_a": request_a,
        "request_b": request_b,
        "request_c": request_c,
    }
