"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use the lenient get_success_data
validator so failures surface as clear "Setup step failed" errors.

Identity threading: PlantManager / LineOperator / QualityTechnician /
RoutePlanner identities are opaque (X-User-ID is recorded for audit and
segregation-of-duties checks); CoManufacturer is entity-backed, so every
ownership-gated co-man call uses make_coman_headers(cm["id"]) with the real
entity id — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    complete_run_payload,
    create_agreement_payload,
    create_changeover_payload,
    create_co_manufacturer_payload,
    create_display_case_payload,
    create_line_payload,
    create_oil_movement_payload,
    create_product_payload,
    create_promo_window_payload,
    create_run_payload,
    create_shipment_payload,
    create_slot_payload,
    create_weight_check_payload,
)
from .test_users import (
    TEST_USERS,
    make_coman_headers,
    make_line_operator_headers,
    make_quality_tech_headers,
)

PM = TEST_USERS["plant_manager_headers"]
OP = TEST_USERS["line_operator_headers"]
QT = TEST_USERS["quality_tech_headers"]
RP = TEST_USERS["route_planner_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and reads
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Set the server's logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, PM))


def create_product(**overrides):
    """Create a product recipe. Returns the product."""
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), PM)
    )


def create_plain_product(name="Plain Chips", **overrides):
    """Allergen-free PLAIN product (changeover matrix yields NONE on a fresh line)."""
    return create_product(name=name, allergen_profile=[], flavor_group="PLAIN",
                          **overrides)


def create_dairy_product(name="Cheese Puffs", **overrides):
    """DAIRY / CHEESE product used to seed a line's allergen profile."""
    defaults = {"allergen_profile": ["DAIRY"], "flavor_group": "CHEESE"}
    defaults.update(overrides)
    return create_product(name=name, **defaults)


def create_line(**overrides):
    """Create a production line (atomically creates its 1:1 FryerOil)."""
    return get_success_data(
        api_client.create_line(create_line_payload(**overrides), PM)
    )


def get_line(line_id):
    return get_success_data(api_client.get_line(line_id, PM))


def get_line_version(line_id):
    """Read the line's current version (the OCC scheduling basis)."""
    return get_line(line_id)["version"]


def get_line_fryer_oil(line_id):
    """Fetch the line's 1:1 FryerOil child via the list filter."""
    data, meta = validate_paginated(api_client.list_fryer_oils(PM, {"line_id": line_id}))
    assert len(data) == 1, f"expected exactly one FryerOil for line {line_id}"
    return data[0]


def schedule_run(line_id, product_id, start="2026-08-02T08:00:00Z",
                 end="2026-08-02T10:00:00Z", lbs_planned=100, cases_planned=10):
    """Observe the line version, then schedule a run (OCC on the line version)."""
    line_v = get_line_version(line_id)
    return get_success_data(api_client.create_run(
        create_run_payload(
            line_id, product_id, line_v,
            scheduled_start=start, scheduled_end=end,
            lbs_planned=lbs_planned, cases_planned=cases_planned,
        ), PM))


def start_run(run_id, operator_id="op-1"):
    return get_success_data(
        api_client.start_run(run_id, make_line_operator_headers(operator_id)))


def record_weight_check(run_id, bag_weight_g=100.0, lbs_fried_since_last_check=0,
                        avg_fry_temp_c=180.0, checker_id="qt-1"):
    return get_success_data(api_client.create_weight_check(
        create_weight_check_payload(
            run_id, bag_weight_g=bag_weight_g,
            lbs_fried_since_last_check=lbs_fried_since_last_check,
            avg_fry_temp_c=avg_fry_temp_c,
        ), make_quality_tech_headers(checker_id)), )


def record_weight_checks(run_id, specs, checker_id="qt-1"):
    """Record a series of checks. Each spec: (bag_weight_g, lbs_fried, temp_c)."""
    out = []
    for bag, lbs, temp in specs:
        out.append(record_weight_check(
            run_id, bag_weight_g=bag, lbs_fried_since_last_check=lbs,
            avg_fry_temp_c=temp, checker_id=checker_id))
    return out


def complete_run(run_id, operator_id="op-1", **overrides):
    return get_success_data(api_client.complete_run(
        run_id, complete_run_payload(**overrides),
        make_line_operator_headers(operator_id)))


def disposition_run(run_id, disposition, tech_id="qt-1"):
    return get_success_data(api_client.quality_disposition(
        run_id, disposition, make_quality_tech_headers(tech_id)))


# ---------------------------------------------------------------------------
# Tier 2/3: run lifecycle composites
# ---------------------------------------------------------------------------

def setup_running_run(product_overrides=None, line_overrides=None,
                      start="2026-08-02T08:00:00Z", end="2026-08-02T10:00:00Z",
                      lbs_planned=100, cases_planned=10,
                      clock="2026-08-02T08:00:00Z"):
    """Product + line + run started. Returns dict(product, line, run)."""
    product = create_plain_product(**(product_overrides or {}))
    line = create_line(**(line_overrides or {}))
    run = schedule_run(line["id"], product["id"], start=start, end=end,
                       lbs_planned=lbs_planned, cases_planned=cases_planned)
    if clock is not None:
        set_clock(clock)
    run = start_run(run["id"])
    return {"product": product, "line": line, "run": run}


def setup_completed_run(product_overrides=None, line_overrides=None,
                        start="2026-08-01T00:00:00Z", end="2026-08-01T02:00:00Z",
                        lbs_planned=100, cases_planned=10,
                        check_specs=((100.0, 100, 180.0),),
                        complete_overrides=None,
                        completed_at=None):
    """Run taken through start, checks, and completion.

    Defaults schedule the run at the startup default clock so completion lands
    at 2026-08-01T00:00:00Z. Returns dict(product, line, run).
    """
    product = create_plain_product(**(product_overrides or {}))
    line = create_line(**(line_overrides or {}))
    run = schedule_run(line["id"], product["id"], start=start, end=end,
                       lbs_planned=lbs_planned, cases_planned=cases_planned)
    run = start_run(run["id"])
    record_weight_checks(run["id"], check_specs or ())
    if completed_at is not None:
        set_clock(completed_at)
    run = complete_run(run["id"], **(complete_overrides or {}))
    return {"product": product, "line": line, "run": run}


def setup_passed_run(**kwargs):
    """Completed run with quality disposition PASS. Returns the same dict."""
    ctx = setup_completed_run(**kwargs)
    ctx["run"] = disposition_run(ctx["run"]["id"], "PASS")
    return ctx


def setup_system_held_run(lbs_planned=20000, cases_planned=1000,
                          check_specs=((100.1, 5000, 180.0),
                                       (100.1, 5000, 180.0),
                                       (100.1, 3250, 180.0))):
    """Run forced to HELD by the oil TPM cascade (13,250 lbs -> tpm 27.0).

    Returns dict(product, line, run, oil) with oil in QUALITY_HOLD at exactly
    tpm 27.0 and the run HELD with a null (system) holder.
    """
    ctx = setup_running_run(start="2026-08-02T08:00:00Z",
                            end="2026-08-02T16:00:00Z",
                            lbs_planned=lbs_planned, cases_planned=cases_planned)
    record_weight_checks(ctx["run"]["id"], check_specs)
    ctx["oil"] = get_line_fryer_oil(ctx["line"]["id"])
    ctx["run"] = get_success_data(api_client.get_run(ctx["run"]["id"], PM))
    return ctx


# ---------------------------------------------------------------------------
# Changeover composites
# ---------------------------------------------------------------------------

def setup_required_changeover(run1_complete=True):
    """Line whose current profile is [DAIRY]/CHEESE plus a scheduled PLAIN run.

    run1 (dairy product) is completed so the line's current allergen profile
    becomes [DAIRY]; run2 (plain product) is then scheduled, which auto-creates
    a REQUIRED changeover (FULL_WASH — allergen removal).

    The returned `line` is a snapshot taken after run1 completes and BEFORE
    run2 is scheduled — its `posture` is IDLE per PRD §2.8 (the auto-created
    changeover does not exist yet). The post-changeover server state has
    posture CLEANING; re-fetch with get_line to observe it.

    Returns dict(product_dairy, product_plain, line, run1, run2, changeover).
    """
    p_dairy = create_dairy_product()
    p_plain = create_plain_product()
    line = create_line()
    run1 = schedule_run(line["id"], p_dairy["id"],
                        start="2026-08-02T08:00:00Z", end="2026-08-02T10:00:00Z")
    set_clock("2026-08-02T08:00:00Z")
    start_run(run1["id"])
    record_weight_check(run1["id"], bag_weight_g=100.0,
                        lbs_fried_since_last_check=100, avg_fry_temp_c=180.0)
    complete_run(run1["id"])
    # Snapshot the line before run2's scheduling auto-creates the REQUIRED
    # changeover: with run1 completed and the FryerOil ACTIVE, PRD §2.8 derives
    # posture IDLE at this point. Callers needing the post-changeover posture
    # re-fetch via get_line(line_id).
    line = get_line(line["id"])
    run2 = schedule_run(line["id"], p_plain["id"],
                        start="2026-08-02T12:00:00Z", end="2026-08-02T14:00:00Z")
    changeovers, _ = validate_paginated(api_client.list_changeovers(PM))
    assert len(changeovers) == 1, "expected exactly one auto-created changeover"
    return {
        "product_dairy": p_dairy,
        "product_plain": p_plain,
        "line": line,
        "run1": run1,
        "run2": run2,
        "changeover": changeovers[0],
    }


def clean_and_validate_changeover(changeover_id, cleaner_id="op-1",
                                  swabber_id="qt-1", validator_id="qt-1"):
    """REQUIRED -> CLEANING -> SWAB_PENDING -> VALIDATED via the cleaning cycle."""
    get_success_data(api_client.begin_cleaning(
        changeover_id, make_line_operator_headers(cleaner_id)))
    get_success_data(api_client.record_swab(
        changeover_id, "PASS", make_quality_tech_headers(swabber_id)))
    return get_success_data(api_client.validate_changeover(
        changeover_id, make_quality_tech_headers(validator_id)))


# ---------------------------------------------------------------------------
# Promo window / display case composites
# ---------------------------------------------------------------------------

def setup_active_promo_window(quota_total_cases=10,
                              window_start_date="2026-08-01",
                              window_end_date="2026-08-31",
                              product_overrides=None):
    """Product + ACTIVE promo window. Returns dict(product, window)."""
    product = create_plain_product(**(product_overrides or {}))
    window = get_success_data(api_client.create_promo_window(
        create_promo_window_payload(
            product["id"], quota_total_cases=quota_total_cases,
            window_start_date=window_start_date,
            window_end_date=window_end_date), PM))
    window = get_success_data(api_client.activate_promo_window(window["id"], PM))
    return {"product": product, "window": window}


def setup_promo_run_scenario(quota_total_cases=10, accepted_cases=20,
                             window_start_date="2026-08-01",
                             window_end_date="2026-08-31"):
    """ACTIVE window + COMPLETED run with `accepted_cases` accepted cases.

    Returns dict(product, line, window, run). The clock is left at the startup
    default (the run completes at 2026-08-01T00:00:00Z).
    """
    ctx = setup_active_promo_window(quota_total_cases=quota_total_cases,
                                    window_start_date=window_start_date,
                                    window_end_date=window_end_date)
    line = create_line()
    run = schedule_run(line["id"], ctx["product"]["id"],
                       start="2026-08-01T00:00:00Z", end="2026-08-01T02:00:00Z",
                       lbs_planned=accepted_cases * 10,
                       cases_planned=accepted_cases)
    start_run(run["id"])
    record_weight_check(run["id"], bag_weight_g=100.0,
                        lbs_fried_since_last_check=accepted_cases * 10,
                        avg_fry_temp_c=180.0)
    run = complete_run(run["id"], lbs_produced=accepted_cases * 10,
                       cases_produced=accepted_cases, rejected_cases=0,
                       seasoning_actual_pct=4.0)
    return {"product": ctx["product"], "line": line, "window": ctx["window"],
            "run": run}


def create_display_case(window_id, run_id, cases_planned):
    return get_success_data(api_client.create_display_case(
        create_display_case_payload(window_id, run_id,
                                    cases_planned=cases_planned), PM))


# ---------------------------------------------------------------------------
# Co-manufacturing composites
# ---------------------------------------------------------------------------

def setup_active_agreement(weekly_capacity_lbs=10000, rate_per_lb_cents=50,
                           budget_cents=1000000, name="TollCo"):
    """CoManufacturer + ACTIVE agreement. Returns dict(coman, agreement).

    The agreement's owning partner is dict(coman); ownership-gated calls must
    use make_coman_headers(coman["id"]).
    """
    coman = get_success_data(api_client.create_co_manufacturer(
        create_co_manufacturer_payload(name=name), PM))
    agreement = get_success_data(api_client.create_agreement(
        create_agreement_payload(
            coman["id"], weekly_capacity_lbs=weekly_capacity_lbs,
            rate_per_lb_cents=rate_per_lb_cents, budget_cents=budget_cents), PM))
    agreement = get_success_data(api_client.activate_agreement(agreement["id"], PM))
    return {"coman": coman, "agreement": agreement}


def book_slot(agreement_id, product_id, coman_id, reserved_lbs=100,
              week_start_date="2026-09-07", as_plant_manager=False):
    """Book a slot under the agreement as its owning partner (or the plant)."""
    headers = TEST_USERS["plant_manager_headers"] if as_plant_manager \
        else make_coman_headers(coman_id)
    return get_success_data(api_client.create_slot(
        create_slot_payload(agreement_id, product_id,
                            week_start_date=week_start_date,
                            reserved_lbs=reserved_lbs), headers))


# ---------------------------------------------------------------------------
# Shipment composites
# ---------------------------------------------------------------------------

def create_shipment(run_id, cases=1, requested_route="DSD", transit_days=None):
    overrides = {}
    if transit_days is not None:
        overrides["transit_days"] = transit_days
    return get_success_data(api_client.create_shipment(
        create_shipment_payload(run_id, cases=cases,
                                requested_route=requested_route, **overrides), RP))
