"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All roles are opaque identities; segregation-of-
duties flows thread explicit user ids through the make_* builders.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    carcass_record,
    create_assignment_payload,
    create_close_out_payload,
    create_death_loss_payload,
    create_feed_call_payload,
    create_health_event_payload,
    create_hedge_payload,
    create_insurance_claim_payload,
    create_lot_payload,
    create_owner_payload,
    create_pen_payload,
    create_ration_assignment_payload,
    create_ration_payload,
)
from .test_users import (
    TEST_USERS,
    make_claims_adjuster_headers,
    make_claims_treasurer_headers,
)

FYM = TEST_USERS["feedyard_manager_headers"]
FM = TEST_USERS["feed_manager_headers"]
CHT = TEST_USERS["cattle_health_tech_headers"]
RM = TEST_USERS["risk_manager_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
TRE = TEST_USERS["claims_treasurer_headers"]
BC = TEST_USERS["billing_clerk_headers"]
ANY = TEST_USERS["any_headers"]

DEFAULT_ARRIVAL = "2026-08-01"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and the logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (FeedyardManager-only)."""
    return get_success_data(api_client.set_clock(to_iso8601, FYM))


def create_owner(owner_name=None, billing_email=None) -> dict:
    """Create an owner (born ACTIVE, balance 0). Returns the owner."""
    overrides = {}
    if owner_name is not None:
        overrides["owner_name"] = owner_name
    if billing_email is not None:
        overrides["billing_email"] = billing_email
    return get_success_data(
        api_client.create_owner(create_owner_payload(**overrides), FYM))


def suspend_owner(owner_id: str) -> dict:
    return get_success_data(
        api_client.patch_owner(owner_id, {"status": "SUSPENDED"}, FYM))


def create_pen(pen_code=None, capacity_head=100) -> dict:
    """Create a pen (born EMPTY, occupancy 0). Returns the pen."""
    overrides = {"capacity_head": capacity_head}
    if pen_code is not None:
        overrides["pen_code"] = pen_code
    return get_success_data(
        api_client.create_pen(create_pen_payload(**overrides), FYM))


def pen_to_maintenance(pen_id: str) -> dict:
    return get_success_data(
        api_client.patch_pen(pen_id, {"status": "MAINTENANCE"}, FYM))


def create_ration(ration_name=None, step_level=1, cost_per_ton_cents=20000) -> dict:
    overrides = {"step_level": step_level,
                 "cost_per_ton_cents": cost_per_ton_cents}
    if ration_name is not None:
        overrides["ration_name"] = ration_name
    return get_success_data(
        api_client.create_ration(create_ration_payload(**overrides), FM))


def create_lot(owner_id, lot_number=None, sex_class="STEER", head_count_in=10,
               in_weight_total_lbs=7000, purchase_cost_cents=1400000,
               arrival_date=DEFAULT_ARRIVAL, commingle_allowed=None) -> dict:
    """Receive a lot (born OPEN with all accumulators at zero)."""
    overrides = {
        "sex_class": sex_class,
        "head_count_in": head_count_in,
        "in_weight_total_lbs": in_weight_total_lbs,
        "purchase_cost_cents": purchase_cost_cents,
        "arrival_date": arrival_date,
    }
    if lot_number is not None:
        overrides["lot_number"] = lot_number
    if commingle_allowed is not None:
        overrides["commingle_allowed"] = commingle_allowed
    return get_success_data(
        api_client.create_lot(create_lot_payload(owner_id, **overrides), FYM))


# ---------------------------------------------------------------------------
# Tier 2: pen placement, ration windows, feed calls, health, death, claims
# ---------------------------------------------------------------------------

def assign_pen(pen_id, lot_id, head_count, start_date=DEFAULT_ARRIVAL) -> dict:
    """Place head of a lot into a pen (ACTIVE assignment)."""
    return get_success_data(api_client.create_assignment(
        create_assignment_payload(pen_id, lot_id, head_count=head_count,
                                  start_date=start_date), FYM))


def assign_ration(lot_id, ration_id, start_date=DEFAULT_ARRIVAL,
                  end_date="2026-08-10") -> dict:
    """Put a lot on a ration for the half-open window [start_date, end_date)."""
    return get_success_data(api_client.create_ration_assignment(
        create_ration_assignment_payload(lot_id, ration_id, start_date=start_date,
                                         end_date=end_date), FM))


def post_first_feed_call(pen_id, call_date, base_qty_lbs_per_head) -> dict:
    """Post a pen's first feed call (base_qty input branch)."""
    return get_success_data(api_client.create_feed_call(
        create_feed_call_payload(pen_id, call_date=call_date,
                                 base_qty_lbs_per_head=base_qty_lbs_per_head), FM))


def post_next_feed_call(pen_id, call_date, bunk_score) -> dict:
    """Post a subsequent feed call (bunk_score input branch)."""
    return get_success_data(api_client.create_feed_call(
        {"pen_id": pen_id, "call_date": call_date, "bunk_score": bunk_score}, FM))


def record_health_event(lot_id, treatment_date=DEFAULT_ARRIVAL,
                        drug_product="DRAXXIN", withdrawal_days=0,
                        head_treated=1, treatment_cost_cents=1000) -> dict:
    return get_success_data(api_client.create_health_event(
        create_health_event_payload(
            lot_id, treatment_date=treatment_date, drug_product=drug_product,
            withdrawal_days=withdrawal_days, head_treated=head_treated,
            treatment_cost_cents=treatment_cost_cents), CHT))


def record_death_loss(lot_id, loss_date=DEFAULT_ARRIVAL, head_count=1,
                      cause="RESPIRATORY", insured=False) -> dict:
    return get_success_data(api_client.create_death_loss(
        create_death_loss_payload(lot_id, loss_date=loss_date,
                                  head_count=head_count, cause=cause,
                                  insured=insured), CHT))


def file_claim(death_loss_id, claimed_amount_cents) -> dict:
    return get_success_data(api_client.create_insurance_claim(
        create_insurance_claim_payload(death_loss_id,
                                       claimed_amount_cents=claimed_amount_cents),
        CHT))


def decide_claim(claim_id, decision, decider_user_id="adj-1",
                 approved_amount_cents=None) -> dict:
    payload = {"decision": decision}
    if approved_amount_cents is not None:
        payload["approved_amount_cents"] = approved_amount_cents
    return get_success_data(api_client.decide_claim(
        claim_id, payload, make_claims_adjuster_headers(decider_user_id)))


def appeal_claim(claim_id, user_id="adj-1") -> dict:
    return get_success_data(
        api_client.appeal_claim(claim_id, make_claims_adjuster_headers(user_id)))


def pay_claim(claim_id, payer_user_id="tre-1", payer_role="treasurer") -> dict:
    headers = (make_claims_treasurer_headers(payer_user_id)
               if payer_role == "treasurer"
               else make_claims_adjuster_headers(payer_user_id))
    return get_success_data(api_client.pay_claim(claim_id, headers))


def get_lot(lot_id) -> dict:
    return get_success_data(api_client.get_lot(lot_id, ANY))


def get_pen(pen_id) -> dict:
    return get_success_data(api_client.get_pen(pen_id, ANY))


def get_owner(owner_id) -> dict:
    return get_success_data(api_client.get_owner(owner_id, ANY))


def list_lot_assignments(lot_id) -> list:
    return validate_success(api_client.list_lot_assignments(lot_id, ANY))


def list_lot_invoices(lot_id) -> list:
    return validate_success(api_client.list_lot_invoices(lot_id, ANY))


def list_lot_hedges(lot_id) -> list:
    return validate_success(api_client.list_lot_hedges(lot_id, ANY))


def list_lot_health_events(lot_id) -> list:
    return validate_success(api_client.list_lot_health_events(lot_id, ANY))


def list_lot_close_outs(lot_id) -> list:
    return validate_success(api_client.list_lot_close_outs(lot_id, ANY))


# ---------------------------------------------------------------------------
# Tier 3: lot marketing / shipping / close-out lifecycle
# ---------------------------------------------------------------------------

def market_lot(lot_id) -> dict:
    return get_success_data(api_client.market_lot(lot_id, FYM))


def ship_lot(lot_id, ship_date, out_weight_total_lbs) -> dict:
    return get_success_data(api_client.ship_lot(
        lot_id, {"ship_date": ship_date,
                 "out_weight_total_lbs": out_weight_total_lbs}, FYM))


def create_draft_close_out(lot_id, expected_lot_version,
                           pricing_basis="PER_CARCASS",
                           grid_base_price_cents_per_cwt=19000) -> dict:
    return get_success_data(api_client.create_close_out(
        create_close_out_payload(
            lot_id, expected_lot_version, pricing_basis=pricing_basis,
            grid_base_price_cents_per_cwt=grid_base_price_cents_per_cwt), RM))


def confirm_close_out(close_out_id, carcass_records) -> dict:
    return get_success_data(api_client.confirm_close_out(
        close_out_id, {"carcass_records": carcass_records}, RM))


def choice_carcasses(count, hot_carcass_weight_lbs=500, quality_grade="CHOICE",
                     yield_grade=3) -> list:
    """A list of identical carcass records, one per shipped head."""
    return [carcass_record(hot_carcass_weight_lbs=hot_carcass_weight_lbs,
                           quality_grade=quality_grade, yield_grade=yield_grade)
            for _ in range(count)]


def setup_owner_with_lot(owner_name=None, lot_number=None, **lot_kwargs) -> tuple:
    """Owner + one OPEN lot. Returns (owner, lot)."""
    owner = create_owner(owner_name=owner_name) if owner_name else create_owner()
    lot = create_lot(owner["id"], lot_number=lot_number, **lot_kwargs)
    return owner, lot


def setup_lot_with_assignment(owner_name=None, pen_code=None, lot_number=None,
                              head_count_in=10, head_assigned=None,
                              **lot_kwargs) -> dict:
    """Owner + pen + lot + one ACTIVE pen assignment."""
    owner = create_owner(owner_name=owner_name)
    pen = create_pen(pen_code=pen_code) if pen_code else create_pen()
    lot = create_lot(owner["id"], lot_number=lot_number,
                     head_count_in=head_count_in, **lot_kwargs)
    assignment = assign_pen(pen["id"], lot["id"],
                            head_assigned if head_assigned is not None
                            else head_count_in)
    return {"owner": owner, "pen": pen, "lot": lot, "assignment": assignment}


def setup_marketed_lot(**kwargs) -> dict:
    ws = setup_lot_with_assignment(**kwargs)
    ws["lot"] = market_lot(ws["lot"]["id"])
    return ws


def setup_shipped_lot(ship_date="2026-08-02", out_weight_total_lbs=7500,
                      clock_to=None, **kwargs) -> dict:
    """Owner + pen + lot + assignment, lot MARKETED then SHIPPED.

    The workspace dict carries the lot's post-ship ``version`` so OCC-guarded
    close-out creation can be chained directly.
    """
    if clock_to is not None:
        set_clock(clock_to)
    ws = setup_lot_with_assignment(**kwargs)
    ws["lot"] = market_lot(ws["lot"]["id"])
    ws["lot"] = ship_lot(ws["lot"]["id"], ship_date, out_weight_total_lbs)
    ws["lot_version"] = ws["lot"]["version"]
    return ws


def setup_closed_out_lot(carcasses=None, pricing_basis="PER_CARCASS",
                         grid_base_price_cents_per_cwt=19000,
                         **kwargs) -> dict:
    """Full lifecycle through close-out confirm: owner + pen + lot shipped,
    DRAFT close-out created and confirmed. Returns owner/pen/lot/close_out/
    invoice plus the post-confirm lot version."""
    ws = setup_shipped_lot(**kwargs)
    head_shipped = ws["lot"]["head_shipped"]
    records = carcasses if carcasses is not None else choice_carcasses(head_shipped)
    close_out = create_draft_close_out(ws["lot"]["id"], ws["lot_version"],
                                       pricing_basis=pricing_basis,
                                       grid_base_price_cents_per_cwt=grid_base_price_cents_per_cwt)
    close_out = confirm_close_out(close_out["id"], records)
    ws["close_out"] = close_out
    ws["lot"] = get_lot(ws["lot"]["id"])
    ws["lot_version"] = ws["lot"]["version"]
    invoices = list_lot_invoices(ws["lot"]["id"])
    ws["invoice"] = invoices[0] if invoices else None
    return ws


# ---------------------------------------------------------------------------
# Tier 4: cost-accumulation composites
# ---------------------------------------------------------------------------

def setup_commingled_pen(pen_code, lot_specs, ration_name="R-COMM",
                         ration_cost_per_ton_cents=20000, owner_name=None,
                         ration_end_date="2026-08-10") -> dict:
    """One pen commingling N compatible lots on one shared ration.

    ``lot_specs`` is a list of dicts with keys lot_number, head_count_in,
    in_weight_total_lbs, purchase_cost_cents (arrival fixed 2026-08-01,
    commingle_allowed true). Ration windows are created BEFORE the pen
    assignments so created_at order matches the assignment order given.
    Returns {owner, pen, ration, lots, assignments} with lists in spec order.
    """
    owner = create_owner(owner_name=owner_name)
    pen = create_pen(pen_code=pen_code,
                     capacity_head=max(200, sum(s["head_count_in"]
                                                for s in lot_specs)))
    ration = create_ration(ration_name=ration_name,
                           cost_per_ton_cents=ration_cost_per_ton_cents)
    lots = [create_lot(owner["id"], lot_number=s["lot_number"],
                       sex_class="STEER",
                       head_count_in=s["head_count_in"],
                       in_weight_total_lbs=s["in_weight_total_lbs"],
                       purchase_cost_cents=s["purchase_cost_cents"],
                       commingle_allowed=True)
            for s in lot_specs]
    for lot in lots:
        assign_ration(lot["id"], ration["id"], end_date=ration_end_date)
    assignments = [assign_pen(pen["id"], lot["id"], s["head_count_in"])
                   for lot, s in zip(lots, lot_specs)]
    return {"owner": owner, "pen": pen, "ration": ration,
            "lots": lots, "assignments": assignments}


def setup_lot_with_insured_loss(owner_name=None, lot_number=None,
                                head_count_in=5, in_weight_total_lbs=3500,
                                purchase_cost_cents=700000,
                                loss_date=DEFAULT_ARRIVAL, loss_head=1,
                                claim_amount_cents=None) -> dict:
    """Owner + OPEN lot + an insured death loss (optionally with a filed claim)."""
    owner = create_owner(owner_name=owner_name)
    lot = create_lot(owner["id"], lot_number=lot_number,
                     head_count_in=head_count_in,
                     in_weight_total_lbs=in_weight_total_lbs,
                     purchase_cost_cents=purchase_cost_cents)
    death_loss = record_death_loss(lot["id"], loss_date=loss_date,
                                   head_count=loss_head, insured=True)
    ws = {"owner": owner, "lot": lot, "death_loss": death_loss}
    if claim_amount_cents is not None:
        ws["claim"] = file_claim(death_loss["id"], claim_amount_cents)
    return ws


def setup_full_cost_lifecycle(owner_name, pen_code, ration_name, lot_number,
                              clock_to="2026-08-03T00:00:00Z") -> dict:
    """The canonical full-cost lifecycle shared by the cost-of-gain, invoice
    evaluation-order, and close-out cascade recipes.

    Builds: clock advanced to 2026-08-03; owner + pen + step-1 ration
    (20000c/ton); lot of 10 steers (7000 lbs, 1400000c) with all 10 head
    assigned; ration window [2026-08-01, 2026-08-05); one feed call on
    2026-08-01 at 20.0 lbs/head; one health event (0 withdrawal days, 5000c);
    one insured death of 1 head on 2026-08-02 claimed at 140745c, approved by
    adj-1 and paid by tre-1. The lot is left OPEN (post-payment) so callers
    can read the provisional cost of gain and then market/ship/close out.
    """
    set_clock(clock_to)
    owner = create_owner(owner_name=owner_name)
    pen = create_pen(pen_code=pen_code)
    ration = create_ration(ration_name=ration_name, step_level=1,
                           cost_per_ton_cents=20000)
    lot = create_lot(owner["id"], lot_number=lot_number, sex_class="STEER",
                     head_count_in=10, in_weight_total_lbs=7000,
                     purchase_cost_cents=1400000)
    assign_pen(pen["id"], lot["id"], 10)
    assign_ration(lot["id"], ration["id"], end_date="2026-08-05")
    feed_call = post_first_feed_call(pen["id"], "2026-08-01", 20.0)
    health_event = record_health_event(lot["id"], treatment_date="2026-08-01",
                                       drug_product="DRAXXIN", withdrawal_days=0,
                                       head_treated=1, treatment_cost_cents=5000)
    death_loss = record_death_loss(lot["id"], loss_date="2026-08-02",
                                   head_count=1, cause="RESPIRATORY", insured=True)
    claim = file_claim(death_loss["id"], 140745)
    claim = decide_claim(claim["id"], "APPROVE", decider_user_id="adj-1")
    claim = pay_claim(claim["id"], payer_user_id="tre-1")
    return {"owner": owner, "pen": pen, "ration": ration, "lot": get_lot(lot["id"]),
            "feed_call": feed_call, "health_event": health_event,
            "death_loss": death_loss, "claim": claim}


def market_ship_and_draft_close_out(ws, ship_date, out_weight_total_lbs,
                                    pricing_basis="PER_CARCASS",
                                    grid_base_price_cents_per_cwt=19000) -> dict:
    """Market + ship the workspace lot, then open a DRAFT close-out against
    the post-ship lot version. Mutates and returns the workspace dict."""
    lot = market_lot(ws["lot"]["id"])
    lot = ship_lot(lot["id"], ship_date, out_weight_total_lbs)
    ws["lot"] = lot
    ws["lot_version"] = lot["version"]
    ws["close_out"] = create_draft_close_out(
        lot["id"], lot["version"], pricing_basis=pricing_basis,
        grid_base_price_cents_per_cwt=grid_base_price_cents_per_cwt)
    return ws


def create_hedge(lot_id, expected_lot_version, contract_month="2026-12",
                 side=None, quantity_contracts=1,
                 entry_price_cents_per_cwt=19000) -> dict:
    overrides = {"contract_month": contract_month,
                 "quantity_contracts": quantity_contracts,
                 "entry_price_cents_per_cwt": entry_price_cents_per_cwt}
    if side is not None:
        overrides["side"] = side
    return get_success_data(api_client.create_hedge(
        create_hedge_payload(lot_id, expected_lot_version, **overrides), RM))


def offset_hedge(hedge_id, exit_price_cents_per_cwt,
                 offset_date=DEFAULT_ARRIVAL) -> dict:
    return get_success_data(api_client.offset_hedge(
        hedge_id, {"exit_price_cents_per_cwt": exit_price_cents_per_cwt,
                   "offset_date": offset_date}, RM))
