"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build complete precondition chains —
grower -> grove -> maturity test -> pool -> channels -> crew -> assignment ->
delivery -> sort run -> verify -> post -> pool pricing/settlement, plus the
caretaking billing chain and the export-lot certification chain — out of
PRD-declared endpoints only.

Identity threading: the Grower role is entity-backed, so every
ownership-gated call uses make_grower_headers(grower["id"]). Segregation of
duties (PRD §2.9) is satisfied by using distinct X-User-ID values per actor:
scenario fixtures create sort runs as operator f"op-{tag}" and verify them as
inspector f"qi-{tag}"; quarantine orders and certificates take explicit
officer ids.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK,
    DEFAULT_SAMPLED_AT,
    DEFAULT_WEEK_START,
    TEST_DEFAULTS,
)
from .factories import (
    create_advance_payload,
    create_assignment_payload,
    create_caretaking_invoice_payload,
    create_caretaking_order_payload,
    create_channel_payload,
    create_crew_payload,
    create_delivery_payload,
    create_export_lot_payload,
    create_grove_payload,
    create_grower_payload,
    create_maturity_test_payload,
    create_phyto_certificate_payload,
    create_pool_payload,
    create_quarantine_order_payload,
    create_room_payload,
    create_sort_run_payload,
    passing_maturity_payload,
)
from .test_users import (
    TEST_USERS,
    make_inspector_headers,
    make_officer_headers,
    make_operator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Drive the server's logical clock (PRD §2.5). Returns the payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-entity builders
# ---------------------------------------------------------------------------

def create_grower(grower_code="GR-1", display_name="Test Grower", **overrides):
    return get_success_data(api_client.create_grower(
        create_grower_payload(grower_code, display_name, **overrides), ADMIN))


def create_grove(grower_id, block_code="B1", variety="HAMLIN", acreage=50,
                 county_code=TEST_DEFAULTS["COUNTY_CODE"], caretaking_enrolled=False,
                 **overrides):
    return get_success_data(api_client.create_grove(
        create_grove_payload(grower_id, block_code, variety, acreage, county_code,
                             caretaking_enrolled, **overrides), ADMIN))


def create_crew(crew_code="CR-1", daily_capacity_boxes=TEST_DEFAULTS["CREW_CAPACITY"]):
    return get_success_data(api_client.create_crew(
        create_crew_payload(crew_code, daily_capacity_boxes), ADMIN))


def create_pool(variety="HAMLIN", week_start=DEFAULT_WEEK_START):
    return get_success_data(api_client.create_pool(
        create_pool_payload(variety, week_start), ACCOUNTANT))


def create_channel(channel_code, channel_type, destination_market, variety,
                   week_start=DEFAULT_WEEK_START, allocation_boxes=0,
                   price_cents_per_box=220, priority_rank=9,
                   accepts_grades=("FANCY", "CHOICE", "STANDARD", "JUICE")):
    return get_success_data(api_client.create_channel(
        create_channel_payload(channel_code, channel_type, destination_market, variety,
                               week_start, allocation_boxes, price_cents_per_box,
                               priority_rank, accepts_grades), ADMIN))


def create_room(room_code="RM-1", capacity_boxes=TEST_DEFAULTS["ROOM_CAPACITY"],
                min_hours=12, max_hours=72):
    return get_success_data(api_client.create_room(
        create_room_payload(room_code, capacity_boxes, min_hours, max_hours), ADMIN))


# ---------------------------------------------------------------------------
# Read helpers (staff reads are role-agnostic; admin headers used)
# ---------------------------------------------------------------------------

def get_grower(grower_id):
    return get_success_data(api_client.get_grower(grower_id, ADMIN))


def get_grove(grove_id):
    return get_success_data(api_client.get_grove(grove_id, ADMIN))


def get_maturity_test(test_id):
    return get_success_data(api_client.get_maturity_test(test_id, ADMIN))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_assignment(assignment_id, ADMIN))


def get_delivery(delivery_id):
    return get_success_data(api_client.get_delivery(delivery_id, ADMIN))


def get_session(session_id):
    return get_success_data(api_client.get_session(session_id, ADMIN))


def get_sort_run(run_id):
    return get_success_data(api_client.get_sort_run(run_id, ADMIN))


def get_channel(channel_id):
    return get_success_data(api_client.get_channel(channel_id, ADMIN))


def get_pool(pool_id):
    return get_success_data(api_client.get_pool(pool_id, ACCOUNTANT))


def get_advance(advance_id):
    return get_success_data(api_client.get_advance(advance_id, ACCOUNTANT))


def get_caretaking_order(order_id):
    return get_success_data(api_client.get_caretaking_order(order_id, ADMIN))


def get_caretaking_invoice(invoice_id):
    return get_success_data(api_client.get_caretaking_invoice(invoice_id, ADMIN))


def get_export_lot(lot_id):
    return get_success_data(api_client.get_export_lot(lot_id, ADMIN))


def get_certificate(cert_id):
    return get_success_data(api_client.get_phyto_certificate(cert_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: OCC-aware writers (re-read the parent's current version first)
# ---------------------------------------------------------------------------

def record_maturity_test(grove_id, sampled_at=DEFAULT_SAMPLED_AT, brix=9.0,
                         acid_pct=1.0, juice_pct=45.0, inspector_id="qi-fixture"):
    """Record a maturity test, threading the grove's current version (PRD §2.8)."""
    grove = get_grove(grove_id)
    payload = create_maturity_test_payload(
        grove["version"], sampled_at=sampled_at, brix=brix,
        acid_pct=acid_pct, juice_pct=juice_pct)
    return get_success_data(api_client.create_maturity_test(
        grove_id, payload, make_inspector_headers(inspector_id)))


def record_passing_maturity_test(grove, sampled_at=DEFAULT_SAMPLED_AT,
                                 inspector_id="qi-fixture"):
    """Record a maturity test whose measurements pass the grove's variety."""
    g = get_grove(grove["id"])
    payload = passing_maturity_payload(g["variety"], g["version"],
                                       sampled_at=sampled_at)
    return get_success_data(api_client.create_maturity_test(
        g["id"], payload, make_inspector_headers(inspector_id)))


def create_sort_run_for_delivery(delivery_id, fancy_boxes=0, choice_boxes=0,
                                 standard_boxes=0, juice_boxes=0, cull_boxes=0,
                                 color_score=8, defect_pct=5,
                                 operator_id="op-fixture"):
    """Create a sort run, threading the delivery's current version (PRD §2.8)."""
    delivery = get_delivery(delivery_id)
    payload = create_sort_run_payload(
        delivery_id, delivery["version"], fancy_boxes, choice_boxes,
        standard_boxes, juice_boxes, cull_boxes, color_score, defect_pct)
    return get_success_data(api_client.create_sort_run(
        payload, make_operator_headers(operator_id)))


def set_pool_price(pool_id):
    """Set/re-set the pool price, threading the pool's current version (PRD §2.8)."""
    pool = get_pool(pool_id)
    return get_success_data(api_client.set_pool_price(
        pool_id, {"expected_pool_version": pool["version"]}, ACCOUNTANT))


# ---------------------------------------------------------------------------
# Tier 2: channel spec builders (waterfall fixtures)
# ---------------------------------------------------------------------------

def jp_export_spec(code, variety, week_start=DEFAULT_WEEK_START, boxes=25,
                   price=900, rank=1, grades=("FANCY",)):
    return dict(channel_code=code, channel_type="EXPORT", destination_market="JAPAN",
                variety=variety, week_start=week_start, allocation_boxes=boxes,
                price_cents_per_box=price, priority_rank=rank,
                accepts_grades=tuple(grades))


def eu_export_spec(code, variety, week_start=DEFAULT_WEEK_START, boxes=10,
                   price=700, rank=2, grades=("FANCY",)):
    return dict(channel_code=code, channel_type="EXPORT", destination_market="EU",
                variety=variety, week_start=week_start, allocation_boxes=boxes,
                price_cents_per_box=price, priority_rank=rank,
                accepts_grades=tuple(grades))


def dom_fresh_spec(code, variety, week_start=DEFAULT_WEEK_START, boxes=40,
                   price=500, rank=2, grades=("FANCY", "CHOICE", "STANDARD")):
    return dict(channel_code=code, channel_type="DOMESTIC_FRESH",
                destination_market="DOMESTIC", variety=variety,
                week_start=week_start, allocation_boxes=boxes,
                price_cents_per_box=price, priority_rank=rank,
                accepts_grades=tuple(grades))


def juice_spec(code, variety, week_start=DEFAULT_WEEK_START, price=220, rank=9):
    return dict(channel_code=code, channel_type="JUICE", destination_market="NONE",
                variety=variety, week_start=week_start, allocation_boxes=0,
                price_cents_per_box=price, priority_rank=rank,
                accepts_grades=("FANCY", "CHOICE", "STANDARD", "JUICE"))


def create_channels_from_specs(specs):
    """Create channels from spec dicts. Returns {channel_code: channel}."""
    created = {}
    for spec in specs:
        channel = create_channel(**spec)
        created[spec["channel_code"]] = channel
    return created


# ---------------------------------------------------------------------------
# Tier 3: harvest chain (grower -> grove -> maturity -> crew -> assignment)
# ---------------------------------------------------------------------------

def setup_grove_with_maturity(tag, variety="HAMLIN", acreage=50,
                              county_code=TEST_DEFAULTS["COUNTY_CODE"],
                              caretaking_enrolled=False, with_maturity=True,
                              sampled_at=DEFAULT_SAMPLED_AT,
                              clock=DEFAULT_CLOCK):
    """Grower + grove (+ CURRENT PASS maturity test). Returns a scenario dict."""
    set_clock(clock)
    grower = create_grower(f"GR-{tag}", f"Grower {tag}")
    grove = create_grove(grower["id"], "B1", variety, acreage, county_code,
                         caretaking_enrolled)
    scenario = {"grower": grower, "grove": grove, "maturity_test": None}
    if with_maturity:
        scenario["maturity_test"] = record_passing_maturity_test(
            grove, sampled_at=sampled_at, inspector_id=f"qi-{tag}")
        scenario["grove"] = get_grove(grove["id"])
    return scenario


def setup_assignment_in_progress(tag, variety="HAMLIN", acreage=50,
                                 county_code=TEST_DEFAULTS["COUNTY_CODE"],
                                 caretaking_enrolled=False,
                                 crew_capacity=TEST_DEFAULTS["CREW_CAPACITY"],
                                 window_start=TEST_DEFAULTS["WINDOW_START"],
                                 window_end=TEST_DEFAULTS["WINDOW_END"],
                                 planned_boxes=100, clock=DEFAULT_CLOCK,
                                 sampled_at=DEFAULT_SAMPLED_AT):
    """Grower + grove + PASS maturity + crew + assignment walked to IN_PROGRESS."""
    scenario = setup_grove_with_maturity(
        tag, variety=variety, acreage=acreage, county_code=county_code,
        caretaking_enrolled=caretaking_enrolled, sampled_at=sampled_at, clock=clock)
    scenario["crew"] = create_crew(f"CR-{tag}", crew_capacity)
    scenario["assignment"] = get_success_data(api_client.create_assignment(
        create_assignment_payload(scenario["crew"]["id"], scenario["grove"]["id"],
                                  window_start, window_end, planned_boxes),
        SUPERVISOR))
    scenario["assignment"] = get_success_data(api_client.start_assignment(
        scenario["assignment"]["id"], SUPERVISOR))
    return scenario


def setup_delivery_received(tag, variety="HAMLIN", gross_boxes=100, tare_boxes=0,
                            with_pool=True, week_start=DEFAULT_WEEK_START,
                            channel_specs=None, **kwargs):
    """Full receiving chain: assignment IN_PROGRESS + delivery RECEIVED (+ pool)."""
    scenario = setup_assignment_in_progress(tag, variety=variety, **kwargs)
    scenario["pool"] = None
    if with_pool:
        scenario["pool"] = create_pool(variety, week_start)
    scenario["channels"] = {}
    if channel_specs:
        scenario["channels"] = create_channels_from_specs(channel_specs)
    scenario["delivery"] = get_success_data(api_client.create_delivery(
        create_delivery_payload(scenario["grove"]["id"],
                                scenario["assignment"]["id"],
                                gross_boxes, tare_boxes), SUPERVISOR))
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: sort-run lifecycle (create -> verify -> post)
# ---------------------------------------------------------------------------

def sort_run_lifecycle(delivery_id, fancy_boxes, choice_boxes, standard_boxes,
                       juice_boxes, cull_boxes, color_score, defect_pct,
                       operator_id, inspector_id, stop_at="posted"):
    """Create a sort run and walk it as far as `stop_at`
    ('created' | 'verified' | 'posted'). Returns the latest sort-run body."""
    run = create_sort_run_for_delivery(
        delivery_id, fancy_boxes, choice_boxes, standard_boxes, juice_boxes,
        cull_boxes, color_score, defect_pct, operator_id=operator_id)
    if stop_at == "created":
        return run
    run = get_success_data(api_client.verify_sort_run(
        run["id"], make_inspector_headers(inspector_id)))
    if stop_at == "verified":
        return run
    run = get_success_data(api_client.post_sort_run(
        run["id"], make_operator_headers(operator_id)))
    return run


def setup_posted_scenario(tag, variety="HAMLIN", week_start=DEFAULT_WEEK_START,
                          channel_specs=None,
                          gross_boxes=100, tare_boxes=0,
                          fancy_boxes=40, choice_boxes=30, standard_boxes=20,
                          juice_boxes=8, cull_boxes=2,
                          color_score=7, defect_pct=10,
                          stop_at="posted", **kwargs):
    """The packhouse workhorse: receiving chain + channels + sort run walked to
    `stop_at`. Default channels are the JP 25@900 / DOM 40@500 / JUICE @220
    trio; default outturn is 40F/30C/20S/8J/2Cu over 100 net boxes."""
    if channel_specs is None:
        channel_specs = [
            jp_export_spec(f"JP-{tag}", variety, week_start),
            dom_fresh_spec(f"DOM-{tag}", variety, week_start),
            juice_spec(f"JU-{tag}", variety, week_start),
        ]
    scenario = setup_delivery_received(
        tag, variety=variety, gross_boxes=gross_boxes, tare_boxes=tare_boxes,
        with_pool=True, week_start=week_start, channel_specs=channel_specs, **kwargs)
    scenario["sort_run"] = sort_run_lifecycle(
        scenario["delivery"]["id"], fancy_boxes, choice_boxes, standard_boxes,
        juice_boxes, cull_boxes, color_score, defect_pct,
        operator_id=f"op-{tag}", inspector_id=f"qi-{tag}", stop_at=stop_at)
    scenario["delivery"] = get_delivery(scenario["delivery"]["id"])
    scenario["pool"] = get_pool(scenario["pool"]["id"])
    scenario["channels"] = {
        code: get_channel(ch["id"]) for code, ch in scenario["channels"].items()}
    return scenario


# ---------------------------------------------------------------------------
# Tier 5: pool finalization (close-intake -> set-price -> settle)
# ---------------------------------------------------------------------------

def close_intake_and_set_price(pool_id):
    """Walk a pool OPEN -> INTAKE_CLOSED -> PRICED. Returns the priced pool."""
    get_success_data(api_client.close_pool_intake(pool_id, ACCOUNTANT))
    return set_pool_price(pool_id)


def setup_priced_scenario(tag, **kwargs):
    """Posted scenario with the pool additionally walked to PRICED."""
    scenario = setup_posted_scenario(tag, stop_at="posted", **kwargs)
    scenario["pool"] = close_intake_and_set_price(scenario["pool"]["id"])
    scenario["delivery"] = get_delivery(scenario["delivery"]["id"])
    return scenario


def settle_pool(pool_id):
    return get_success_data(api_client.settle_pool(pool_id, ACCOUNTANT))


def get_statements(pool_id, headers=ACCOUNTANT):
    return get_success_data(api_client.get_settlement_statements(pool_id, headers))


def create_and_approve_advance(grower_id, pool_id, amount_cents,
                               recoup_policy=None, requester_headers=None):
    """Request + approve an advance. Returns the ISSUED advance."""
    payload = create_advance_payload(grower_id, pool_id, amount_cents, recoup_policy)
    advance = get_success_data(api_client.create_advance(
        payload, requester_headers or ACCOUNTANT))
    return get_success_data(api_client.approve_advance(advance["id"], ACCOUNTANT))


# ---------------------------------------------------------------------------
# Tier 3: caretaking billing chain (order -> schedule -> complete -> invoice)
# ---------------------------------------------------------------------------

def setup_enrolled_grove(tag, acreage=30, variety="HAMLIN",
                         county_code=TEST_DEFAULTS["COUNTY_CODE"],
                         clock=DEFAULT_CLOCK):
    """Grower + caretaking-enrolled grove (no maturity needed for caretaking)."""
    return setup_grove_with_maturity(tag, variety=variety, acreage=acreage,
                                     county_code=county_code,
                                     caretaking_enrolled=True,
                                     with_maturity=False, clock=clock)


def create_completed_order(grove_id, service_type="MOW", service_date="2026-08-01",
                           acres_treated=1, chemical_cost_cents=None):
    """Caretaking order walked REQUESTED -> SCHEDULED -> COMPLETED."""
    order = get_success_data(api_client.create_caretaking_order(
        create_caretaking_order_payload(grove_id, service_type, service_date,
                                        acres_treated, chemical_cost_cents),
        SUPERVISOR))
    get_success_data(api_client.schedule_caretaking_order(order["id"], SUPERVISOR))
    return get_success_data(api_client.complete_caretaking_order(order["id"], SUPERVISOR))


def create_draft_invoice(grower_id, period_start="2026-08-01", period_end="2026-08-31"):
    return get_success_data(api_client.create_caretaking_invoice(
        create_caretaking_invoice_payload(grower_id, period_start, period_end),
        ACCOUNTANT))


def setup_issued_invoice(tag, service_type="MOW", service_date="2026-08-01",
                         acres_treated=11.111, acreage=30, **kwargs):
    """Enrolled grove + one COMPLETED order + invoice ISSUED.
    Returns dict(grower, grove, order, invoice)."""
    scenario = setup_enrolled_grove(tag, acreage=acreage, **kwargs)
    scenario["order"] = create_completed_order(
        scenario["grove"]["id"], service_type, service_date, acres_treated)
    scenario["invoice"] = create_draft_invoice(scenario["grower"]["id"])
    scenario["invoice"] = get_success_data(api_client.issue_caretaking_invoice(
        scenario["invoice"]["id"], ACCOUNTANT))
    scenario["order"] = get_caretaking_order(scenario["order"]["id"])
    scenario["grower"] = get_grower(scenario["grower"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: export certification chain (lot -> inspect -> certificate)
# ---------------------------------------------------------------------------

def create_export_lot(destination_market, variety, grade, boxes, source_channel_id,
                      source_grove_id, cold_treatment_hours=None,
                      officer_id="co-fixture"):
    return get_success_data(api_client.create_export_lot(
        create_export_lot_payload(destination_market, variety, grade, boxes,
                                  source_channel_id, source_grove_id,
                                  cold_treatment_hours),
        make_officer_headers(officer_id)))


def setup_inspection_ready_lot(scenario, channel_code, destination_market="JAPAN",
                               grade="FANCY", boxes=10, cold_treatment_hours=24,
                               officer_id="co-lot"):
    """Create a lot on a posted scenario's channel and request inspection.
    The requester's id is recorded as inspection_requested_by (PRD §3.9)."""
    lot = create_export_lot(
        destination_market, scenario["grove"]["variety"], grade, boxes,
        scenario["channels"][channel_code]["id"], scenario["grove"]["id"],
        cold_treatment_hours, officer_id=officer_id)
    return get_success_data(api_client.request_inspection(
        lot["id"], make_officer_headers(officer_id)))


def certify_lot(lot_id, certificate_number, inspection_result, issuer_id):
    """Record the inspection result against an INSPECTION_READY lot. The
    issuer's id must differ from the lot's inspection_requested_by (PRD §2.9)."""
    return get_success_data(api_client.create_phyto_certificate(
        lot_id, create_phyto_certificate_payload(certificate_number, inspection_result),
        make_officer_headers(issuer_id)))


def setup_certified_lot(tag, boxes=10, cold_treatment_hours=24, lot_officer_id=None,
                        cert_issuer_id=None, channel_code=None, **kwargs):
    """Posted scenario + BUILDING lot + INSPECTION_READY + PASS certificate.
    Returns the scenario dict extended with lot/certificate."""
    lot_officer_id = lot_officer_id or f"co-{tag}-a"
    cert_issuer_id = cert_issuer_id or f"co-{tag}-b"
    channel_code = channel_code or f"JP-{tag}"
    scenario = setup_posted_scenario(tag, **kwargs)
    lot = create_export_lot("JAPAN", scenario["grove"]["variety"], "FANCY", boxes,
                            scenario["channels"][channel_code]["id"],
                            scenario["grove"]["id"], cold_treatment_hours,
                            officer_id=lot_officer_id)
    lot = get_success_data(api_client.request_inspection(
        lot["id"], make_officer_headers(lot_officer_id)))
    certificate = certify_lot(lot["id"], f"PC-{tag}", "PASS", cert_issuer_id)
    scenario["lot"] = get_export_lot(lot["id"])
    scenario["certificate"] = certificate
    scenario["lot_officer_id"] = lot_officer_id
    scenario["cert_issuer_id"] = cert_issuer_id
    return scenario


# ---------------------------------------------------------------------------
# Tier 3: quarantine helpers
# ---------------------------------------------------------------------------

def create_quarantine(scope_type, pest_type, grove_id=None, county_code=None,
                      officer_id="co-quar"):
    payload = create_quarantine_order_payload(scope_type, grove_id=grove_id,
                                              county_code=county_code,
                                              pest_type=pest_type)
    return get_success_data(api_client.create_quarantine_order(
        payload, make_officer_headers(officer_id)))


def release_quarantine(order_id, inspection_passed=True, officer_id="co-release"):
    return api_client.release_quarantine_order(
        order_id, {"inspection_passed": inspection_passed},
        make_officer_headers(officer_id))
