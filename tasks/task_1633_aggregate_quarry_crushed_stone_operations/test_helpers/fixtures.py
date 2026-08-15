"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the
server before each test), so these helpers build complete precondition
chains out of PRD-declared endpoints only. All roles in this API use
opaque operator identities, so the shared TEST_USERS constants are safe to
use directly; segregation-of-duties pairings pick distinct user ids via
the make_* builders.

Setup calls use get_success_data() so a setup failure surfaces as a clear
"Setup step failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from .api_client import api_client
from .factories import (
    create_bench_payload,
    create_freight_zone_payload,
    create_gradation_test_payload,
    create_msha_citation_payload,
    create_msha_inspection_payload,
    create_plant_run_payload,
    create_product_spec_payload,
    create_queue_entry_payload,
    create_reclamation_bond_payload,
    create_royalty_agreement_payload,
    create_royalty_statement_payload,
    create_sales_order_payload,
    create_scale_calibration_payload,
    create_scale_payload,
    create_scale_ticket_payload,
    create_shot_plan_payload,
    create_site_payload,
    create_stockpile_payload,
    create_training_record_payload,
    stockpile_adjustment_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["quarry_admin_headers"]
MANAGER = TEST_USERS["site_manager_headers"]
FOREMAN = TEST_USERS["blast_foreman_headers"]          # X-User-ID bf-1
OPERATOR = TEST_USERS["plant_operator_headers"]        # X-User-ID po-1
SCALE_OP = TEST_USERS["scale_house_operator_headers"]  # X-User-ID sh-1
QC_1 = TEST_USERS["qc_technician_headers"]             # X-User-ID qc-1
SALES = TEST_USERS["sales_agent_headers"]              # X-User-ID sa-1
FINANCE = TEST_USERS["finance_clerk_headers"]          # X-User-ID fc-1
SAFETY = TEST_USERS["safety_officer_headers"]          # X-User-ID so-1

# A second QC technician identity (confirmer != reporter, PRD SoD rule).
from .test_users import make_qc_technician_headers  # noqa: E402
QC_2 = make_qc_technician_headers("qc-2")


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and reads
# ---------------------------------------------------------------------------

def create_site(name="Quarry Q1", permitted_acres=200,
                bond_rate_per_acre_usd=12000):
    """Create a quarry site. Born with zeroed aggregates, ADEQUATE, OPERATING."""
    payload = create_site_payload(name=name, permitted_acres=permitted_acres,
                                  bond_rate_per_acre_usd=bond_rate_per_acre_usd)
    return get_success_data(api_client.create_site(payload, ADMIN))


def get_site(site_id):
    return get_success_data(api_client.get_site(site_id, MANAGER))


def post_bond(site_id, amount_usd=100000, surety_name="SuretyCo"):
    """Post a surety bond; site coverage recomputes in the same request."""
    payload = create_reclamation_bond_payload(
        site_id, surety_name=surety_name, amount_usd=amount_usd)
    return get_success_data(api_client.create_reclamation_bond(payload,
                                                               FINANCE))


def create_bench(site_id, bench_label="BENCH-1400", elevation_ft=1400,
                 acreage=5.0):
    """Plan a bench (born PLANNED)."""
    payload = create_bench_payload(site_id, bench_label=bench_label,
                                   elevation_ft=elevation_ft, acreage=acreage)
    return get_success_data(api_client.create_bench(payload, MANAGER))


def get_bench(bench_id):
    return get_success_data(api_client.get_bench(bench_id, MANAGER))


def release_bench(bench_id):
    return get_success_data(api_client.release_bench(bench_id, MANAGER))


def create_released_bench(site_id, bench_label="BENCH-1400", elevation_ft=1400,
                          acreage=5.0):
    """Create a bench and release it (site must stand OPERATING)."""
    bench = create_bench(site_id, bench_label=bench_label,
                         elevation_ft=elevation_ft, acreage=acreage)
    return release_bench(bench["id"])


def create_spec(spec_code="A57", category="COARSE", gradation_bands=None,
                base_price_per_ton=12.50):
    """Create a product spec (born ACTIVE)."""
    payload = create_product_spec_payload(
        spec_code=spec_code, category=category,
        base_price_per_ton=base_price_per_ton)
    if gradation_bands is not None:
        payload["gradation_bands"] = gradation_bands
    return get_success_data(api_client.create_product_spec(payload, ADMIN))


def create_stockpile(site_id, spec_id, capacity_tons=5000):
    """Create a stockpile (born OPEN, all tonnages zero)."""
    payload = create_stockpile_payload(site_id, spec_id,
                                       capacity_tons=capacity_tons)
    return get_success_data(api_client.create_stockpile(payload, MANAGER))


def get_stockpile(pile_id):
    return get_success_data(api_client.get_stockpile(pile_id, MANAGER))


def adjust_stockpile(pile, delta_tons, reason="opening survey"):
    """Manual inventory adjustment carrying the pile's current version (OCC)."""
    payload = stockpile_adjustment_payload(delta_tons, pile["version"],
                                           reason=reason)
    return get_success_data(
        api_client.adjust_stockpile(pile["id"], payload, MANAGER))


def create_zone(zone_code="Z-LOCAL", distance_miles=25,
                base_freight_per_ton=6.00):
    """Create a freight zone (born ACTIVE)."""
    payload = create_freight_zone_payload(
        zone_code=zone_code, distance_miles=distance_miles,
        base_freight_per_ton=base_freight_per_ton)
    return get_success_data(api_client.create_freight_zone(payload, ADMIN))


def create_agreement(site_id, landowner_name="LW", base_rate_per_ton=0.25,
                     tier_threshold_tons=50, tier_rate_per_ton=0.40,
                     effective_from="2026-01-01"):
    """Create the site's royalty agreement (born ACTIVE)."""
    payload = create_royalty_agreement_payload(
        site_id, landowner_name=landowner_name,
        base_rate_per_ton=base_rate_per_ton,
        tier_threshold_tons=tier_threshold_tons,
        tier_rate_per_ton=tier_rate_per_ton, effective_from=effective_from)
    return get_success_data(api_client.create_royalty_agreement(payload,
                                                                FINANCE))


def create_scale(site_id, scale_code="TRUCK-01", scale_type="TRUCK"):
    """Register a scale (born OUT_OF_SERVICE)."""
    payload = create_scale_payload(site_id, scale_code=scale_code,
                                   scale_type=scale_type)
    return get_success_data(api_client.create_scale(payload, ADMIN))


def calibrate_scale(scale_id, calibrated_on="2026-02-02", as_left=0.10):
    """Record a calibration; as_left within 0.25 certifies the scale."""
    payload = create_scale_calibration_payload(
        scale_id, calibrated_on=calibrated_on, as_left_error_pct=as_left)
    return get_success_data(api_client.create_scale_calibration(payload,
                                                                ADMIN))


def create_certified_scale(site_id, scale_code="TRUCK-01", scale_type="TRUCK",
                           calibrated_on="2026-02-02"):
    """Register a scale and certify it with a PASS calibration."""
    scale = create_scale(site_id, scale_code=scale_code, scale_type=scale_type)
    calibrate_scale(scale["id"], calibrated_on=calibrated_on)
    return get_success_data(api_client.get_scale(scale["id"], ADMIN))


def create_training(miner_user_id="bf-1", course_type="TASK_TRAINING",
                    completed_on="2026-01-15", miner_name="Blaster One"):
    """Record an MSHA training course for a miner."""
    payload = create_training_record_payload(
        miner_name=miner_name, miner_user_id=miner_user_id,
        course_type=course_type, completed_on=completed_on)
    return get_success_data(api_client.create_training_record(payload, SAFETY))


def set_clock(to_iso8601):
    """Move the logical clock (QuarryAdmin-only test-driving capability)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_gradation_test(pile_id, sampled_at, sieve_results):
    """Report a gradation test (result computed at creation)."""
    payload = create_gradation_test_payload(
        pile_id, sampled_at=sampled_at, sieve_results=sieve_results)
    return get_success_data(api_client.create_gradation_test(payload, QC_1))


# ---------------------------------------------------------------------------
# Tier 2: drill-and-blast chains
# ---------------------------------------------------------------------------

def create_shot_plan(bench_id, hole_count=20, burden_ft=8, spacing_ft=10,
                     hole_depth_ft=40, explosive_per_hole_lbs=50):
    """Create a shot plan (born DRAFT, design tonnage computed)."""
    payload = create_shot_plan_payload(
        bench_id, hole_count=hole_count, burden_ft=burden_ft,
        spacing_ft=spacing_ft, hole_depth_ft=hole_depth_ft,
        explosive_per_hole_lbs=explosive_per_hole_lbs)
    return get_success_data(api_client.create_shot_plan(payload, FOREMAN))


def get_shot_plan(plan_id):
    return get_success_data(api_client.get_shot_plan(plan_id, MANAGER))


def submit_plan(plan_id):
    return get_success_data(api_client.submit_shot_plan(plan_id, FOREMAN))


def approve_plan(plan_id):
    """Approve as SiteManager sm-1 (submitter was bf-1, so SoD passes)."""
    return get_success_data(api_client.approve_shot_plan(plan_id, MANAGER))


def create_approved_plan(bench_id, **plan_overrides):
    """Create a plan and walk it DRAFT -> SUBMITTED -> APPROVED."""
    plan = create_shot_plan(bench_id, **plan_overrides)
    submit_plan(plan["id"])
    return approve_plan(plan["id"])


def advance_plan_to_loaded(plan_id, drilled_hole_count=20,
                           loaded_explosive_lbs=1000):
    """Walk APPROVED -> DRILLING -> DRILLED -> LOADED."""
    get_success_data(api_client.start_drilling(plan_id, FOREMAN))
    get_success_data(api_client.complete_drilling(
        plan_id, {"drilled_hole_count": drilled_hole_count}, FOREMAN))
    return get_success_data(api_client.load_shot_plan(
        plan_id, {"loaded_explosive_lbs": loaded_explosive_lbs}, FOREMAN))


def get_muckpile_for_plan(plan_id):
    """Reverse-discover the cascade-created muckpile of a fired plan."""
    resp = api_client.list_muckpiles(MANAGER, params={"shot_plan_id": plan_id})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly 1 muckpile for plan {plan_id}"
    return data[0]


def fire_plan(plan_id, fire_clock="2026-08-01T10:00:00Z"):
    """Fire a LOADED plan: training + blast window satisfied, then fire."""
    create_training(miner_user_id="bf-1")
    set_clock(fire_clock)
    return get_success_data(api_client.fire_shot_plan(plan_id, FOREMAN))


def setup_blast_site(bond_amount=100000, bench_label="BENCH-1400",
                     elevation_ft=1400, acreage=5.0,
                     fire_clock="2026-08-01T10:00:00Z", **plan_overrides):
    """Site + bond + released bench + shot plan walked to FIRED + muckpile.

    Returns dict(site, bond, bench, plan, muckpile). The plan's firing
    operator bf-1 holds a current TASK_TRAINING record and the clock sits
    inside the daily blasting window.
    """
    site = create_site()
    bond = post_bond(site["id"], amount_usd=bond_amount)
    bench = create_released_bench(site["id"], bench_label=bench_label,
                                  elevation_ft=elevation_ft, acreage=acreage)
    plan = create_approved_plan(bench["id"], **plan_overrides)
    advance_plan_to_loaded(plan["id"])
    plan = fire_plan(plan["id"], fire_clock=fire_clock)
    muckpile = get_muckpile_for_plan(plan["id"])
    return {"site": site, "bond": bond, "bench": bench, "plan": plan,
            "muckpile": muckpile}


# ---------------------------------------------------------------------------
# Tier 3: commercial chain (spec / zone / stockpile / order)
# ---------------------------------------------------------------------------

def create_order(site_id, spec_id, zone_id, customer_name="ACME",
                 quantity_tons=100):
    payload = create_sales_order_payload(
        site_id, spec_id, zone_id, customer_name=customer_name,
        quantity_tons=quantity_tons)
    return get_success_data(api_client.create_sales_order(payload, SALES))


def get_order(order_id):
    return get_success_data(api_client.get_sales_order(order_id, SALES))


def confirm_order(order_id):
    return get_success_data(api_client.confirm_sales_order(order_id, SALES))


def create_confirmed_order(site_id, spec_id, zone_id, customer_name="ACME",
                           quantity_tons=100):
    """Create an order and confirm it (availability decides CONFIRMED vs
    BACKORDERED). Returns the post-confirm order."""
    order = create_order(site_id, spec_id, zone_id,
                         customer_name=customer_name,
                         quantity_tons=quantity_tons)
    return confirm_order(order["id"])


def setup_ticketing_site(on_hand=200.0, quantity_tons=100,
                         with_agreement=True, calibrated_on="2026-02-02",
                         customer_name="ACME", spec_code="A57",
                         category="COARSE", capacity_tons=5000,
                         agreement_overrides=None):
    """Site + spec + zone + stockpile (adjusted to on_hand) + optional
    royalty agreement + certified TRUCK scale + one order walked through
    /confirm. Returns a context dict."""
    site = create_site()
    spec = create_spec(spec_code=spec_code, category=category)
    zone = create_zone()
    pile = create_stockpile(site["id"], spec["id"], capacity_tons=capacity_tons)
    if on_hand:
        pile = adjust_stockpile(pile, on_hand)
    agr = None
    if with_agreement:
        agr = create_agreement(site["id"], **(agreement_overrides or {}))
    scale = create_certified_scale(site["id"], calibrated_on=calibrated_on)
    order = create_confirmed_order(site["id"], spec["id"], zone["id"],
                                   customer_name=customer_name,
                                   quantity_tons=quantity_tons)
    return {"site": site, "spec": spec, "zone": zone, "pile": pile,
            "agreement": agr, "scale": scale, "order": order}


# ---------------------------------------------------------------------------
# Tier 4: scale-house chain (queue -> weigh-in -> scale-out -> weigh-out)
# ---------------------------------------------------------------------------

def queue_truck(site_id, truck_id="TRK-1", priority_class="CONTRACT",
                certified_tare_lbs=28000, max_payload_lbs=70000):
    payload = create_queue_entry_payload(
        site_id, truck_id=truck_id, priority_class=priority_class,
        certified_tare_lbs=certified_tare_lbs, max_payload_lbs=max_payload_lbs)
    return get_success_data(api_client.create_queue_entry(payload, SCALE_OP))


def call_next_truck(site_id):
    payload = {"site_id": site_id}
    return get_success_data(api_client.call_next_queue_entry(payload,
                                                             SCALE_OP))


def get_queue_entry(entry_id):
    return get_success_data(api_client.get_queue_entry(entry_id, SCALE_OP))


def weigh_in_truck(ctx, truck_id="TRK-1", gross_lbs=80000, order_id=None,
                   certified_tare_lbs=28000, max_payload_lbs=70000):
    """Queue a truck, dispatch it, and open a scale ticket against the
    context's confirmed order. Returns (queue_entry, ticket)."""
    entry = queue_truck(ctx["site"]["id"], truck_id=truck_id,
                        certified_tare_lbs=certified_tare_lbs,
                        max_payload_lbs=max_payload_lbs)
    call_next_truck(ctx["site"]["id"])
    payload = create_scale_ticket_payload(
        entry["id"], order_id or ctx["order"]["id"], ctx["scale"]["id"],
        gross_lbs=gross_lbs)
    ticket = get_success_data(api_client.create_scale_ticket(payload,
                                                             SCALE_OP))
    return entry, ticket


def move_to_scale_out(entry_id):
    return get_success_data(api_client.begin_scale_out(entry_id, SCALE_OP))


def weigh_out_ticket(ticket_id, tare_lbs=28000, allow_tare_variance=None):
    payload = {"tare_lbs": tare_lbs}
    if allow_tare_variance is not None:
        payload["allow_tare_variance"] = allow_tare_variance
    return get_success_data(api_client.weigh_out_ticket(ticket_id, payload,
                                                        SCALE_OP))


def complete_ticket(ctx, truck_id="TRK-1", gross_lbs=80000, tare_lbs=28000,
                    order_id=None, certified_tare_lbs=28000,
                    max_payload_lbs=70000):
    """Full ticket lifecycle: queue -> dispatch -> weigh-in -> scale-out ->
    weigh-out. Returns (queue_entry, completed_ticket)."""
    entry, ticket = weigh_in_truck(
        ctx, truck_id=truck_id, gross_lbs=gross_lbs, order_id=order_id,
        certified_tare_lbs=certified_tare_lbs, max_payload_lbs=max_payload_lbs)
    move_to_scale_out(entry["id"])
    ticket = weigh_out_ticket(ticket["id"], tare_lbs=tare_lbs)
    return entry, ticket


def get_ticket(ticket_id):
    return get_success_data(api_client.get_scale_ticket(ticket_id, MANAGER))


# ---------------------------------------------------------------------------
# Tier 5: plant runs
# ---------------------------------------------------------------------------

def setup_plant_run_site(capacity_tons=5000, spec_code="A57",
                         category="COARSE", **blast_kwargs):
    """Blast site (fired shot, muckpile) + spec + stockpile + certified BELT
    scale. Returns a context dict."""
    ctx = setup_blast_site(**blast_kwargs)
    spec = create_spec(spec_code=spec_code, category=category)
    pile = create_stockpile(ctx["site"]["id"], spec["id"],
                            capacity_tons=capacity_tons)
    belt = create_certified_scale(ctx["site"]["id"], scale_code="BELT-01",
                                  scale_type="BELT")
    ctx.update({"spec": spec, "pile": pile, "belt": belt})
    return ctx


def create_run(ctx, circuit_line="PRIMARY"):
    payload = create_plant_run_payload(ctx["site"]["id"],
                                       ctx["muckpile"]["id"],
                                       ctx["belt"]["id"],
                                       circuit_line=circuit_line)
    return get_success_data(api_client.create_plant_run(payload, OPERATOR))


def start_run(run_id):
    return get_success_data(api_client.start_plant_run(run_id, OPERATOR))


def complete_run(run_id, input_tons, outputs):
    payload = {"input_tons": input_tons, "outputs": outputs}
    return get_success_data(api_client.complete_plant_run(run_id, payload,
                                                          OPERATOR))


def get_run(run_id):
    return get_success_data(api_client.get_plant_run(run_id, OPERATOR))


def create_completed_run(ctx, input_tons, outputs, circuit_line="PRIMARY"):
    """Create -> start -> complete a run. Returns the completed run."""
    run = create_run(ctx, circuit_line=circuit_line)
    start_run(run["id"])
    return complete_run(run["id"], input_tons, outputs)


def get_muckpile(muckpile_id):
    return get_success_data(api_client.get_muckpile(muckpile_id, OPERATOR))


# ---------------------------------------------------------------------------
# Tier 6: royalty / MSHA helpers
# ---------------------------------------------------------------------------

def generate_statement(site_id, period_start, period_end):
    payload = create_royalty_statement_payload(site_id, period_start,
                                               period_end)
    return get_success_data(api_client.create_royalty_statement(payload,
                                                                FINANCE))


def get_statement(statement_id):
    return get_success_data(
        api_client.get_royalty_statement(statement_id, FINANCE))


def open_inspection(site_id, inspection_type="REGULAR"):
    payload = create_msha_inspection_payload(site_id,
                                             inspection_type=inspection_type)
    return get_success_data(api_client.create_msha_inspection(payload,
                                                              SAFETY))


def issue_citation(inspection_id, citation_code="56.14100", s_and_s=True,
                   abatement_due_on="2026-07-15"):
    payload = create_msha_citation_payload(
        inspection_id, citation_code=citation_code, s_and_s=s_and_s,
        abatement_due_on=abatement_due_on)
    return get_success_data(api_client.create_msha_citation(payload, SAFETY))
