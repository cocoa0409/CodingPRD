"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All roles are opaque identities; where a flow
depends on who recorded or sold a resource (segregation of duties), callers
pass an explicit user id through the make_* header builders.
"""
import math

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_assignment_payload,
    create_breeding_season_payload,
    create_bull_payload,
    create_bull_turnout_payload,
    create_calf_crop_payload,
    create_drought_assessment_payload,
    create_herd_group_payload,
    create_lease_payload,
    create_lease_statement_payload,
    create_pasture_payload,
    create_preg_check_payload,
    create_ranch_payload,
    create_sale_lot_payload,
    create_supplement_program_payload,
    finalize_preg_check_payload,
    record_bse_payload,
    record_delivery_payload,
    record_reduction_payload,
    record_vaccine_payload,
    record_weaning_payload,
)
from .test_users import (
    TEST_USERS,
    make_ranch_manager_headers,
    make_range_manager_headers,
    make_herd_manager_headers,
    make_sales_agent_headers,
)

RANCH_MGR = TEST_USERS["ranch_manager_headers"]
RANGE_MGR = TEST_USERS["range_manager_headers"]
HERD_MGR = TEST_USERS["herd_manager_headers"]
SALES_AGENT = TEST_USERS["sales_agent_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and primitive transitions
# ---------------------------------------------------------------------------

def create_ranch(name="Test Ranch", hq_state="MT", destock_grace_days=None):
    """Create a ranch (born NORMAL, pct 100.0, seq 0). Returns the ranch."""
    payload = create_ranch_payload(name=name, hq_state=hq_state)
    if destock_grace_days is not None:
        payload["destock_grace_days"] = destock_grace_days
    return get_success_data(api_client.create_ranch(payload, RANCH_MGR))


def get_ranch(ranch_id):
    return get_success_data(api_client.get_ranch(ranch_id, RANGE_MGR))


def set_clock(to_iso8601):
    """Advance the logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, RANCH_MGR))


def create_pasture(ranch_id, name="Section", acreage=1000, tenure="DEEDED",
                   forage_type="NATIVE_RANGE", base_capacity_aum=100,
                   min_rest_days=None):
    payload = create_pasture_payload(
        ranch_id, name=name, acreage=acreage, tenure=tenure,
        forage_type=forage_type, base_capacity_aum=base_capacity_aum,
    )
    if min_rest_days is not None:
        payload["min_rest_days"] = min_rest_days
    return get_success_data(api_client.create_pasture(payload, RANGE_MGR))


def get_pasture(pasture_id):
    return get_success_data(api_client.get_pasture(pasture_id, RANGE_MGR))


def create_lease(ranch_id, pasture_id, lessor_name="Lessor",
                 start_date="2026-01-01", end_date="2026-12-31",
                 aum_allotment=50, settlement_basis="ACTUAL_USE", **overrides):
    """Create a lease in DRAFT."""
    payload = create_lease_payload(
        ranch_id, pasture_id, lessor_name=lessor_name, start_date=start_date,
        end_date=end_date, aum_allotment=aum_allotment,
        settlement_basis=settlement_basis, **overrides,
    )
    return get_success_data(api_client.create_lease(payload, RANGE_MGR))


def activate_lease(lease_id):
    return get_success_data(api_client.activate_lease(lease_id, RANGE_MGR))


def create_and_activate_lease(ranch_id, pasture_id, **kwargs):
    lease = create_lease(ranch_id, pasture_id, **kwargs)
    return activate_lease(lease["id"])


def create_herd_group(ranch_id, group_name="Cows", animal_class="MATURE_COW",
                      head_count=60, avg_weight_lbs=1000):
    return get_success_data(api_client.create_herd_group(
        create_herd_group_payload(
            ranch_id, group_name=group_name, animal_class=animal_class,
            head_count=head_count, avg_weight_lbs=avg_weight_lbs,
        ), HERD_MGR))


def get_herd_group(group_id):
    return get_success_data(api_client.get_herd_group(group_id, HERD_MGR))


def create_breeding_season(ranch_id, herd_group_id, season_year=2026,
                           planned_turnout_date="2026-04-15",
                           planned_removal_date="2026-06-15",
                           exposed_head_count=25):
    return get_success_data(api_client.create_breeding_season(
        create_breeding_season_payload(
            ranch_id, herd_group_id, season_year=season_year,
            planned_turnout_date=planned_turnout_date,
            planned_removal_date=planned_removal_date,
            exposed_head_count=exposed_head_count,
        ), HERD_MGR))


def create_bull(ranch_id, tag="B1", breed="ANGUS", birth_year=2021):
    return get_success_data(api_client.create_bull(
        create_bull_payload(ranch_id, tag=tag, breed=breed, birth_year=birth_year),
        HERD_MGR))


def record_bse(bull_id, result="PASSED", exam_date="2026-03-01", scrotal_cm=35.0):
    return get_success_data(api_client.record_bse(
        bull_id, record_bse_payload(result=result, exam_date=exam_date,
                                    scrotal_cm=scrotal_cm), HERD_MGR))


def schedule_turnout(bull_id, season_id, ranch_id, turnout_date="2026-04-15",
                     planned_removal_date="2026-06-15"):
    return get_success_data(api_client.create_bull_turnout(
        create_bull_turnout_payload(
            bull_id, season_id, ranch_id, turnout_date=turnout_date,
            planned_removal_date=planned_removal_date,
        ), HERD_MGR))


def turn_in_turnout(turnout_id):
    return get_success_data(api_client.turn_in_turnout(turnout_id, HERD_MGR))


def remove_turnout(turnout_id, removal_date="2026-06-15"):
    return get_success_data(api_client.remove_turnout(
        turnout_id, {"removal_date": removal_date}, HERD_MGR))


def begin_breeding(season_id):
    return get_success_data(api_client.begin_breeding(season_id, HERD_MGR))


def end_breeding(season_id):
    return get_success_data(api_client.end_breeding(season_id, HERD_MGR))


def drive_season_to_gestation(ranch_id, herd_group_id, exposed_head_count=25,
                              season_year=2026,
                              planned_turnout_date="2026-04-15",
                              planned_removal_date="2026-06-15",
                              exam_date="2026-03-01"):
    """Drive a breeding season PLANNED -> GESTATION with a fully qualified
    battery: ceil(exposed/25) bulls, all PASSED, turned in and removed.

    The logical clock is pinned at the turnout date while the battery is
    evaluated so the exam validity window (whose length is a system constant)
    is never in play for the breeding flow.
    Returns the season dict (in GESTATION).
    """
    season = create_breeding_season(
        ranch_id, herd_group_id, season_year=season_year,
        planned_turnout_date=planned_turnout_date,
        planned_removal_date=planned_removal_date,
        exposed_head_count=exposed_head_count,
    )
    n_bulls = math.ceil(exposed_head_count / 25)
    turnouts = []
    for i in range(n_bulls):
        bull = create_bull(ranch_id, tag=f"B{i + 1}")
        record_bse(bull["id"], result="PASSED", exam_date=exam_date,
                   scrotal_cm=34.5 + i * 0.5)
        turnouts.append(schedule_turnout(
            bull["id"], season["id"], ranch_id,
            turnout_date=planned_turnout_date,
            planned_removal_date=planned_removal_date,
        ))
    for t in turnouts:
        turn_in_turnout(t["id"])
    # Pin the clock at turnout day so the recorded exams are fresh when the
    # battery is evaluated.
    set_clock(f"{planned_turnout_date}T00:00:00Z")
    begin_breeding(season["id"])
    for t in turnouts:
        remove_turnout(t["id"], removal_date=planned_removal_date)
    end_breeding(season["id"])
    return get_success_data(api_client.get_breeding_season(season["id"], HERD_MGR))


def create_calf_crop(season_id, ranch_id, crop_year=2026, steer_head=100,
                     heifer_head=60):
    return get_success_data(api_client.create_calf_crop(
        create_calf_crop_payload(season_id, ranch_id, crop_year=crop_year,
                                 steer_head=steer_head, heifer_head=heifer_head),
        HERD_MGR))


def record_weaning(crop_id, weaning_date="2026-09-15", avg_wean_weight_lbs=560,
                   avg_wean_age_days=200, avg_birth_weight_lbs=80,
                   avg_dam_age_years=5):
    return get_success_data(api_client.record_weaning(
        crop_id,
        record_weaning_payload(
            weaning_date=weaning_date, avg_wean_weight_lbs=avg_wean_weight_lbs,
            avg_wean_age_days=avg_wean_age_days,
            avg_birth_weight_lbs=avg_birth_weight_lbs,
            avg_dam_age_years=avg_dam_age_years,
        ), HERD_MGR))


def enroll_preconditioning(crop_id):
    return get_success_data(api_client.enroll_preconditioning(crop_id, HERD_MGR))


def record_vaccine(crop_id, round_number, vaccine_date):
    return get_success_data(api_client.record_vaccine(
        crop_id, record_vaccine_payload(round_number, vaccine_date), HERD_MGR))


def certify_preconditioning(crop_id):
    return get_success_data(api_client.certify_preconditioning(crop_id, HERD_MGR))


def get_calf_crop(crop_id):
    return get_success_data(api_client.get_calf_crop(crop_id, HERD_MGR))


# ---------------------------------------------------------------------------
# Tier 2: hierarchy builders
# ---------------------------------------------------------------------------

def setup_ranch_with_group(head_count=60, avg_weight_lbs=1000,
                           animal_class="MATURE_COW", ranch_name="Ranch"):
    """Ranch + one herd group. Returns (ranch, group)."""
    ranch = create_ranch(name=ranch_name)
    group = create_herd_group(ranch["id"], animal_class=animal_class,
                              head_count=head_count, avg_weight_lbs=avg_weight_lbs)
    return ranch, group


def setup_weaned_crop(steer_head=100, heifer_head=60, exposed_head_count=50,
                      avg_dam_age_years=5, weaning_date="2026-09-15",
                      avg_wean_weight_lbs=560, avg_wean_age_days=200,
                      avg_birth_weight_lbs=80, clock_after_weaning=None):
    """Full chain: ranch -> cow group -> season in GESTATION -> calf crop ->
    weaning recorded. Returns dict of the built resources."""
    ranch, group = setup_ranch_with_group()
    season = drive_season_to_gestation(ranch["id"], group["id"],
                                       exposed_head_count=exposed_head_count)
    crop = create_calf_crop(season["id"], ranch["id"], steer_head=steer_head,
                            heifer_head=heifer_head)
    set_clock(f"{weaning_date}T00:00:00Z")
    crop = record_weaning(crop["id"], weaning_date=weaning_date,
                          avg_wean_weight_lbs=avg_wean_weight_lbs,
                          avg_wean_age_days=avg_wean_age_days,
                          avg_birth_weight_lbs=avg_birth_weight_lbs,
                          avg_dam_age_years=avg_dam_age_years)
    if clock_after_weaning:
        set_clock(clock_after_weaning)
    return {"ranch": ranch, "group": group, "season": season, "crop": crop}


def setup_enrolled_crop(steer_head=100, heifer_head=60, vaccine_round_1="2026-09-20",
                        vaccine_round_2="2026-10-10", **wean_kwargs):
    """Weaned crop also ENROLLED with both vaccine rounds recorded."""
    ctx = setup_weaned_crop(steer_head=steer_head, heifer_head=heifer_head,
                            **wean_kwargs)
    crop = ctx["crop"]
    enroll_preconditioning(crop["id"])
    record_vaccine(crop["id"], 1, vaccine_round_1)
    record_vaccine(crop["id"], 2, vaccine_round_2)
    ctx["crop"] = get_calf_crop(crop["id"])
    return ctx


def setup_certified_crop(steer_head=100, heifer_head=60,
                         weaning_date="2026-09-15", certify_date="2026-10-30",
                         **wean_kwargs):
    """Weaned + ENROLLED + two vaccine rounds + certified at exactly 45 days
    past weaning. Returns dict of the built resources."""
    ctx = setup_enrolled_crop(steer_head=steer_head, heifer_head=heifer_head,
                              weaning_date=weaning_date, **wean_kwargs)
    set_clock(f"{certify_date}T00:00:00Z")
    ctx["crop"] = certify_preconditioning(ctx["crop"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: sale-lot lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_sale_lot(crop_id, ranch_id, seller_user_id="u-sale-1", **overrides):
    return get_success_data(api_client.create_sale_lot(
        create_sale_lot_payload(crop_id, ranch_id, **overrides),
        make_sales_agent_headers(seller_user_id)))


def offer_lot(lot_id, seller_user_id="u-sale-1"):
    return get_success_data(api_client.offer_lot(
        lot_id, make_sales_agent_headers(seller_user_id)))


def contract_lot(lot_id, buyer_name="Buyer", seller_user_id="u-sale-1"):
    return get_success_data(api_client.contract_lot(
        lot_id, {"buyer_name": buyer_name},
        make_sales_agent_headers(seller_user_id)))


def deliver_lot(lot_id, delivered_avg_weight_lbs, seller_user_id="u-sale-1"):
    return get_success_data(api_client.deliver_lot(
        lot_id, {"delivered_avg_weight_lbs": delivered_avg_weight_lbs},
        make_sales_agent_headers(seller_user_id)))


def settle_lot(lot_id, settler_user_id="u-ranch-9"):
    return get_success_data(api_client.settle_lot(
        lot_id, make_ranch_manager_headers(settler_user_id)))


def setup_delivered_lot(steer_head=100, heifer_head=60, certified=True,
                        delivered_avg_weight_lbs=535, seller_user_id="u-sale-1",
                        **lot_overrides):
    """Weaned (optionally certified) crop plus one lot driven
    DRAFT -> OFFERED -> CONTRACTED -> DELIVERED. Returns dict of resources."""
    if certified:
        ctx = setup_certified_crop(steer_head=steer_head, heifer_head=heifer_head)
        lot_overrides.setdefault("precon_claim", "CERTIFIED")
    else:
        ctx = setup_weaned_crop(steer_head=steer_head, heifer_head=heifer_head)
    lot = create_sale_lot(ctx["crop"]["id"], ctx["ranch"]["id"],
                          seller_user_id=seller_user_id, **lot_overrides)
    offer_lot(lot["id"], seller_user_id=seller_user_id)
    contract_lot(lot["id"], seller_user_id=seller_user_id)
    lot = deliver_lot(lot["id"], delivered_avg_weight_lbs,
                      seller_user_id=seller_user_id)
    ctx["lot"] = lot
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: grazing assignments and the forage ledger
# ---------------------------------------------------------------------------

def create_assignment(pasture_id, herd_group_id, ranch_id,
                      start_date="2026-06-01", planned_end_date="2026-07-31"):
    return get_success_data(api_client.create_grazing_assignment(
        create_assignment_payload(pasture_id, herd_group_id, ranch_id,
                                  start_date=start_date,
                                  planned_end_date=planned_end_date),
        RANGE_MGR))


def complete_assignment(assignment_id, actual_end_date):
    return get_success_data(api_client.complete_assignment(
        assignment_id, {"actual_end_date": actual_end_date}, RANGE_MGR))


def cancel_assignment(assignment_id):
    return get_success_data(api_client.cancel_assignment(assignment_id, RANGE_MGR))


# ---------------------------------------------------------------------------
# Tier 4b: lease statements
# ---------------------------------------------------------------------------

def create_lease_statement(lease_id, ranch_id, period_year=2026,
                           recorder_user_id="u-range-1"):
    return get_success_data(api_client.create_lease_statement(
        create_lease_statement_payload(lease_id, ranch_id, period_year),
        make_range_manager_headers(recorder_user_id)))


def issue_statement(statement_id, recorder_user_id="u-range-1"):
    return get_success_data(api_client.issue_statement(
        statement_id, make_range_manager_headers(recorder_user_id)))


def setup_lease_scenario(base_capacity_aum=100, aum_allotment=50,
                         settlement_basis="ACTUAL_USE",
                         start_date="2026-01-01", end_date="2026-12-31",
                         tenure="LEASED", **lease_overrides):
    """Ranch + LEASED pasture + one ACTIVE lease. Returns dict of resources."""
    ranch = create_ranch()
    pasture = create_pasture(ranch["id"], tenure=tenure,
                             base_capacity_aum=base_capacity_aum)
    lease = create_and_activate_lease(
        ranch["id"], pasture["id"], aum_allotment=aum_allotment,
        settlement_basis=settlement_basis, start_date=start_date,
        end_date=end_date, **lease_overrides)
    return {"ranch": ranch, "pasture": pasture, "lease": lease}


def setup_issued_statement(base_capacity_aum=100, aum_allotment=50,
                           recorder_user_id="u-range-1", **lease_overrides):
    """ACTIVE lease plus a statement created AND issued by the same
    RangeManager identity (the segregation anchor). Returns dict."""
    ctx = setup_lease_scenario(base_capacity_aum=base_capacity_aum,
                               aum_allotment=aum_allotment, **lease_overrides)
    stmt = create_lease_statement(ctx["lease"]["id"], ctx["ranch"]["id"],
                                  recorder_user_id=recorder_user_id)
    stmt = issue_statement(stmt["id"], recorder_user_id=recorder_user_id)
    ctx["statement"] = stmt
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: drought assessment and destock orders
# ---------------------------------------------------------------------------

def create_drought_assessment(ranch_id, assessment_date, pasture_measurements):
    return get_success_data(api_client.create_drought_assessment(
        create_drought_assessment_payload(ranch_id, assessment_date,
                                          pasture_measurements), RANGE_MGR))


def finalize_assessment(assessment_id, expected_ranch_version):
    return get_success_data(api_client.finalize_assessment(
        assessment_id, {"expected_ranch_version": expected_ranch_version},
        RANGE_MGR))


def list_destock_orders(ranch_id=None):
    """List destock orders. Each test runs against an empty database with a
    single ranch, so an unfiltered list is equivalent to a per-ranch filter."""
    data, meta = validate_paginated(api_client.list_destock_orders(RANGE_MGR))
    return data, meta


def record_reduction(group_id, head_count, reason, destock_order_id=None):
    return get_success_data(api_client.record_reduction(
        group_id,
        record_reduction_payload(head_count, reason,
                                 destock_order_id=destock_order_id),
        HERD_MGR))


def setup_drought_ranch(grace_days=None):
    """Ranch with two DEEDED pastures (base 300 + 200) and three herd groups:
    40 GROWING @800, 60 MATURE_COW @1100, 20 REPLACEMENT_HEIFER @700.
    Returns dict of resources (demand 105.8 AUM/30d at these weights)."""
    ranch = create_ranch(name="Dry Ranch", hq_state="NV",
                         destock_grace_days=grace_days)
    p1 = create_pasture(ranch["id"], name="North", acreage=1500,
                        base_capacity_aum=300)
    p2 = create_pasture(ranch["id"], name="South", acreage=1000,
                        base_capacity_aum=200)
    g1 = create_herd_group(ranch["id"], group_name="Stockers",
                           animal_class="GROWING", head_count=40,
                           avg_weight_lbs=800)
    g2 = create_herd_group(ranch["id"], group_name="Cows",
                           animal_class="MATURE_COW", head_count=60,
                           avg_weight_lbs=1100)
    g3 = create_herd_group(ranch["id"], group_name="Heifers",
                           animal_class="REPLACEMENT_HEIFER", head_count=20,
                           avg_weight_lbs=700)
    return {"ranch": ranch, "p1": p1, "p2": p2, "g1": g1, "g2": g2, "g3": g3}


def setup_critical_drought():
    """Drought ranch finalized CRITICAL (pct 44.0, deficit 55.8) — the
    destock order and the DESTOCKING flip exist afterwards.
    Returns dict of resources including the order list."""
    ctx = setup_drought_ranch()
    ranch = ctx["ranch"]
    assessment = create_drought_assessment(
        ranch["id"], "2026-08-01",
        [{"pasture_id": ctx["p1"]["id"], "production_pct_of_normal": 40},
         {"pasture_id": ctx["p2"]["id"], "production_pct_of_normal": 50}])
    finalize_assessment(assessment["id"], ranch["version"])
    orders, _meta = list_destock_orders(ranch["id"])
    ctx["assessment"] = assessment
    ctx["orders"] = orders
    return ctx


# ---------------------------------------------------------------------------
# Supplement programs
# ---------------------------------------------------------------------------

def create_supplement_program(herd_group_id, ranch_id, program_type="MINERAL",
                              start_date="2026-01-01", end_date="2026-02-28",
                              feed_rate_oz_per_head_day=4,
                              cost_cents_per_ton=240000):
    return get_success_data(api_client.create_supplement_program(
        create_supplement_program_payload(
            herd_group_id, ranch_id, program_type=program_type,
            start_date=start_date, end_date=end_date,
            feed_rate_oz_per_head_day=feed_rate_oz_per_head_day,
            cost_cents_per_ton=cost_cents_per_ton,
        ), HERD_MGR))


def record_delivery(program_id, delivered_lbs, delivery_date="2026-01-10"):
    return get_success_data(api_client.record_delivery(
        program_id, record_delivery_payload(delivered_lbs, delivery_date),
        HERD_MGR))
