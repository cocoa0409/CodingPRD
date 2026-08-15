"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as
clear "Setup step failed" errors instead of confusing assertion failures.

Identity threading: every Customer-role write goes through
make_customer_headers(customer_id) so X-User-ID equals the owning account id
(PRD 2.1). Claims filer/adjudicator identities use explicit operator ids.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLAIMS_USERS, TEST_DEFAULTS
from .factories import (
    create_attach_order_payload,
    create_board_grade_payload,
    create_box_order_payload,
    create_converting_booking_payload,
    create_corrugator_run_payload,
    create_customer_account_payload,
    create_inventory_program_payload,
    create_price_quote_payload,
    create_quality_claim_payload,
    create_receipt_payload,
    create_release_order_payload,
    create_work_shift_payload,
)
from .test_users import (
    TEST_USERS,
    make_claims_adjuster_headers,
    make_customer_headers,
    make_customer_service_headers,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]


# --- Tier 2: master data -------------------------------------------------

def create_customer(name=None, city=None, miles=None, credit_limit=None) -> dict:
    payload = create_customer_account_payload(
        account_name=name or TEST_DEFAULTS["CUSTOMER_NAME"],
        ship_to_city=city or TEST_DEFAULTS["CUSTOMER_CITY"],
        distance_miles_from_plant=(
            miles if miles is not None else TEST_DEFAULTS["CUSTOMER_MILES"]
        ),
        credit_limit_dollars=(
            credit_limit
            if credit_limit is not None
            else TEST_DEFAULTS["CUSTOMER_CREDIT_LIMIT"]
        ),
    )
    return get_success_data(api_client.create_customer_account(payload, SALES))


def create_grade(
    code=None, ect=None, flute=None, liner=None, burst=None, basis_weight=None
) -> dict:
    payload = create_board_grade_payload(
        grade_code=code or TEST_DEFAULTS["GRADE_CODE"],
        liner_combo=liner or TEST_DEFAULTS["GRADE_LINER"],
        flute=flute or TEST_DEFAULTS["GRADE_FLUTE"],
        ect_rating_lbs_per_in=ect if ect is not None else TEST_DEFAULTS["GRADE_ECT"],
        burst_rating_psi=burst if burst is not None else TEST_DEFAULTS["GRADE_BURST"],
        basis_weight_lbs_per_msf=(
            basis_weight
            if basis_weight is not None
            else TEST_DEFAULTS["GRADE_BASIS_WEIGHT"]
        ),
    )
    return get_success_data(api_client.create_board_grade(payload, ADMIN))


def create_grade_44bc() -> dict:
    return create_grade(
        code=TEST_DEFAULTS["GRADE44_CODE"],
        ect=TEST_DEFAULTS["GRADE44_ECT"],
        flute=TEST_DEFAULTS["GRADE44_FLUTE"],
        liner=TEST_DEFAULTS["GRADE44_LINER"],
        burst=TEST_DEFAULTS["GRADE44_BURST"],
        basis_weight=TEST_DEFAULTS["GRADE44_BASIS_WEIGHT"],
    )


def setup_customer_and_grade(**customer_kw):
    """Canonical customer (Acme, 120.0 mi LOCAL) + grade 32C.
    Returns (customer, grade)."""
    return create_customer(**customer_kw), create_grade()


# --- Tier 1/3: box order commercial progression ---------------------------

def create_draft_order(customer_id, grade_id, **order_over) -> dict:
    return get_success_data(
        api_client.create_box_order(
            create_box_order_payload(customer_id, grade_id, **order_over), SALES
        )
    )


def quote_order(order, unit_price=None, expires_on=None) -> dict:
    """Create a quote on a DRAFT/QUOTED order using its current version.
    Returns the created PriceQuote (OPEN)."""
    payload = create_price_quote_payload(
        order["version"],
        unit_price_per_msf=unit_price or TEST_DEFAULTS["UNIT_PRICE"],
        expires_on=expires_on or TEST_DEFAULTS["QUOTE_EXPIRES_ON"],
    )
    return get_success_data(api_client.create_price_quote(order["id"], payload, SALES))


def create_quoted_order(customer_id, grade_id, unit_price=None, **order_over):
    """DRAFT order + one OPEN quote. Returns (order, quote)."""
    order = create_draft_order(customer_id, grade_id, **order_over)
    quote = quote_order(order, unit_price=unit_price)
    return order, quote


def create_accepted_order(customer_id, grade_id, unit_price=None, **order_over):
    """Order walked to ACCEPTED. Returns (order, quote) with quote ACCEPTED."""
    order, quote = create_quoted_order(
        customer_id, grade_id, unit_price=unit_price, **order_over
    )
    accepted = get_success_data(api_client.accept_price_quote(quote["id"], SALES))
    order = get_success_data(api_client.get_box_order(order["id"], SALES))
    return order, accepted


# --- Tier 2/3: production (shifts, runs, bookings) ------------------------

def create_work_shift(
    machine_code="CORRUGATOR", shift_date=None, start_minute=None, end_minute=None
) -> dict:
    payload = create_work_shift_payload(
        machine_code=machine_code,
        shift_date=shift_date or TEST_DEFAULTS["SHIFT_DATE"],
        start_minute=(
            start_minute if start_minute is not None else TEST_DEFAULTS["SHIFT_START"]
        ),
        end_minute=end_minute if end_minute is not None else TEST_DEFAULTS["SHIFT_END"],
    )
    return get_success_data(api_client.create_work_shift(payload, PLANNER))


def create_corrugator_run(
    shift_id, grade_id, start_minute=480, end_minute=720, web_width_in=87.0
) -> dict:
    payload = create_corrugator_run_payload(
        shift_id,
        grade_id,
        start_minute=start_minute,
        end_minute=end_minute,
        web_width_in=web_width_in,
    )
    return get_success_data(api_client.create_corrugator_run(payload, PLANNER))


def attach_order(run_id, order_id, outs) -> dict:
    """Attach an ACCEPTED INTERNAL order to a run. Returns the run."""
    return get_success_data(
        api_client.attach_order_to_run(
            run_id, create_attach_order_payload(order_id, outs), PLANNER
        )
    )


def schedule_order_on_run(order_id, grade_id, outs=3, run_start=480, run_end=720,
                          web_width_in=87.0, shift=None):
    """Create CORRUGATOR shift (if absent) + run + attach. Order lands in
    SCHEDULED. Returns (shift, run)."""
    shift = shift or create_work_shift(machine_code="CORRUGATOR")
    run = create_corrugator_run(
        shift["id"], grade_id,
        start_minute=run_start, end_minute=run_end, web_width_in=web_width_in,
    )
    attach_order(run["id"], order_id, outs)
    return shift, run


def advance_order_to_awaiting_converting(order_id, grade_id, outs=3):
    """INTERNAL order: attach to a run and complete the run.
    Returns the order in AWAITING_CONVERTING."""
    _, run = schedule_order_on_run(order_id, grade_id, outs=outs)
    get_success_data(api_client.complete_corrugator_run(run["id"], PLANNER))
    return get_success_data(api_client.get_box_order(order_id, PLANNER))


def _machine_for_routing(routing_type: str) -> str:
    return "DIE_CUTTER" if routing_type == "DIE_CUT" else "FFG"


def book_order(order, booking_shift=None, start_minute=480, end_minute=600):
    """Book an AWAITING_CONVERTING order onto a routing-matched machine shift.
    Returns (booking, shift)."""
    shift = booking_shift or create_work_shift(
        machine_code=_machine_for_routing(order["routing_type"])
    )
    booking = get_success_data(
        api_client.create_converting_booking(
            create_converting_booking_payload(
                order["id"], shift["id"],
                start_minute=start_minute, end_minute=end_minute,
            ),
            PLANNER,
        )
    )
    return booking, shift


def advance_order_to_produced(order_id, grade_id, produced_qty, outs=3):
    """Full production: run attach/complete + booking start/complete.
    Returns (order, booking)."""
    order = advance_order_to_awaiting_converting(order_id, grade_id, outs=outs)
    booking, _ = book_order(order)
    get_success_data(api_client.start_converting_booking(booking["id"], PLANNER))
    get_success_data(
        api_client.complete_converting_booking(
            booking["id"], {"produced_qty": produced_qty}, PLANNER
        )
    )
    order = get_success_data(api_client.get_box_order(order_id, PLANNER))
    return order, booking


def setup_invoiced_order_scenario(produced_qty=2100, unit_price=None, **order_over):
    """Canonical pipeline: Acme (LOCAL 120 mi) + 32C + DIE_CUT INTERNAL
    29x36 qty 2000 inks [BLACK, RED] quoted at 60.00/MSF, produced 2100,
    invoiced. Returns dict with customer/grade/order/quote."""
    customer, grade = setup_customer_and_grade()
    order, quote = create_accepted_order(
        customer["id"], grade["id"], unit_price=unit_price, **order_over
    )
    order, booking = advance_order_to_produced(
        order["id"], grade["id"], produced_qty=produced_qty
    )
    invoiced = get_success_data(api_client.invoice_box_order(order["id"], SALES))
    return {
        "customer": customer,
        "grade": grade,
        "order": invoiced,
        "quote": quote,
        "booking": booking,
    }


# --- Tier 3: sheet-feeder path --------------------------------------------

def create_accepted_sheet_feeder_order(customer_id, grade_id, unit_price=90.00,
                                       **order_over):
    """SLOTTED SHEET_FEEDER order (supplier SheetCo) walked to ACCEPTED."""
    over = {
        "routing_type": "SLOTTED",
        "board_source": "SHEET_FEEDER",
        "sheet_supplier_name": "SheetCo",
        "quantity": 4000,
        "blank_width_in": 30.0,
        "blank_length_in": 40.0,
        "min_ect_required": 30,
        "ink_colors": ["BLACK"],
    }
    over.update(order_over)
    return create_accepted_order(customer_id, grade_id, unit_price=unit_price, **over)


def create_awaiting_sheet_feeder_order(customer_id, grade_id, unit_price=90.00,
                                       **order_over):
    """Sheet-feeder order walked ACCEPTED -> AWAITING_CONVERTING via
    mark-sheets-received. Returns (order, quote)."""
    order, quote = create_accepted_sheet_feeder_order(
        customer_id, grade_id, unit_price=unit_price, **order_over
    )
    order = get_success_data(api_client.mark_sheets_received(order["id"], PLANNER))
    return order, quote


# --- Tier 2/4: inventory programs and releases -----------------------------

def create_inventory_program(customer_id, grade_id, reorder_point=None,
                             replenishment_qty=None, **over) -> dict:
    payload = create_inventory_program_payload(
        customer_id,
        grade_id,
        reorder_point=(
            reorder_point
            if reorder_point is not None
            else TEST_DEFAULTS["REORDER_POINT"]
        ),
        replenishment_qty=(
            replenishment_qty
            if replenishment_qty is not None
            else TEST_DEFAULTS["REPLENISHMENT_QTY"]
        ),
        **over,
    )
    return get_success_data(api_client.create_inventory_program(payload, SALES))


def post_receipt(program_id, qty) -> dict:
    return get_success_data(
        api_client.create_program_receipt(program_id, create_receipt_payload(qty), PLANNER)
    )


def create_stocked_program(customer_id, grade_id, stock_qty=400, **program_kw) -> dict:
    """Program created ACTIVE then stocked with a single receipt."""
    program = create_inventory_program(customer_id, grade_id, **program_kw)
    if stock_qty:
        program = post_receipt(program["id"], stock_qty)
    return program


def get_program(program_id) -> dict:
    return get_success_data(api_client.get_inventory_program(program_id, PLANNER))


def create_release(program_id, qty, customer_id, ship_date=None) -> dict:
    """Customer creates a release on its own program (ownership-gated)."""
    headers = make_customer_headers(customer_id)
    payload = create_release_order_payload(
        qty, requested_ship_date=ship_date or TEST_DEFAULTS["SHIP_DATE"]
    )
    return get_success_data(
        api_client.create_release_order(program_id, payload, headers)
    )


def create_approved_release(program_id, qty, customer_id) -> dict:
    release = create_release(program_id, qty, customer_id)
    return get_success_data(api_client.approve_release_order(release["id"], ADMIN))


def setup_program_with_shipped_release(customer_id, grade_id, stock_qty=400,
                                       release_qty=350, **program_kw):
    """Program stocked to stock_qty; release of release_qty approved and
    shipped. Returns (program_after_ship, release)."""
    program = create_stocked_program(customer_id, grade_id, stock_qty, **program_kw)
    release = create_approved_release(program["id"], release_qty, customer_id)
    shipped = get_success_data(api_client.ship_release_order(release["id"], PLANNER))
    return get_program(program["id"]), shipped


# --- Tier 3/5: quality claims ----------------------------------------------

def create_claim(order_id, filer_id=None, claim_type="TRANSIT_DAMAGE",
                 defective_qty_claimed=500, measured_warp_pct=None) -> dict:
    """File a claim as CustomerService; filer id stamped on the claim."""
    filer = filer_id or CLAIMS_USERS["FILER_ID"]
    payload = create_quality_claim_payload(
        order_id,
        claim_type=claim_type,
        defective_qty_claimed=defective_qty_claimed,
    )
    if measured_warp_pct is not None:
        payload["measured_warp_pct"] = measured_warp_pct
    return get_success_data(
        api_client.create_quality_claim(payload, make_customer_service_headers(filer))
    )


def create_claim_under_review(order_id, filer_id=None, reviewer_id=None, **claim_kw):
    """Claim filed (CustomerService) and moved to UNDER_REVIEW
    (ClaimsAdjuster). Returns the claim."""
    filer = filer_id or CLAIMS_USERS["FILER_ID"]
    reviewer = reviewer_id or CLAIMS_USERS["ADJUDICATOR_ID"]
    claim = create_claim(order_id, filer_id=filer, **claim_kw)
    return get_success_data(
        api_client.start_claim_review(
            claim["id"], make_claims_adjuster_headers(reviewer)
        )
    )


def setup_invoiced_order_with_claim_under_review(produced_qty=2100, **claim_kw):
    """Invoiced canonical order + an UNDER_REVIEW claim.
    Returns dict(customer, grade, order, quote, claim)."""
    scenario = setup_invoiced_order_scenario(produced_qty=produced_qty)
    claim = create_claim_under_review(scenario["order"]["id"], **claim_kw)
    scenario["claim"] = claim
    return scenario
