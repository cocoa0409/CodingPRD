"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database, and the logical clock reads 2026-08-01T00:00:00Z until set). Setup
calls use get_success_data so failures surface as clear "Setup failed"
errors. All callers are responsible for their own assertions.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    add_load_line_payload,
    create_erection_sequence_payload,
    create_field_fix_payload,
    create_inspection_payload,
    create_job_payload,
    create_mill_order_payload,
    create_piece_payload,
    create_progress_billing_payload,
    create_shipping_load_payload,
    create_shop_drawing_payload,
    create_weld_payload,
    create_welder_payload,
    decide_drawing_payload,
    receive_mill_order_payload,
    respond_backcharge_payload,
    revise_drawing_payload,
    settle_backcharge_payload,
    set_clock_payload,
    submit_inspection_payload,
)
from .test_users import (
    TEST_USERS,
    make_detailer_headers,
    make_eor_headers,
    make_qc_inspector_headers,
    make_welder_headers,
)

ADMIN = TEST_USERS["fabricator_admin_headers"]
DETAILER = TEST_USERS["detailer_headers"]
EOR = TEST_USERS["eor_headers"]
FOREMAN = TEST_USERS["foreman_headers"]
QC = TEST_USERS["qc_inspector_headers"]
GC_PM = TEST_USERS["gc_pm_headers"]

DEFAULT_SUBMITTER = "det-1"
DEFAULT_APPROVER = "eor-1"
DEFAULT_INSPECTOR = "qc-1"


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}")


# ---------------------------------------------------------------------------
# Tier 1 — jobs, drawings, and the logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    _ok("set_clock", resp)


def create_job(name="Job", contract_value_cents=None, billing_basis="WEIGHT",
               requires_aisc_hold=None):
    payload = create_job_payload(
        name=name,
        contract_value_cents=(
            TEST_DEFAULTS["CONTRACT_VALUE_CENTS"]
            if contract_value_cents is None else contract_value_cents
        ),
        billing_basis=billing_basis,
        requires_aisc_hold=requires_aisc_hold,
    )
    resp = api_client.create_job(payload, ADMIN)
    return _ok("create_job", resp)


def award_job(job_id):
    resp = api_client.award_job(job_id, ADMIN)
    return _ok("award_job", resp)


def create_awarded_job(name="Job", **kwargs):
    job = create_job(name=name, **kwargs)
    return award_job(job["id"])


def get_job(job_id):
    resp = api_client.get_job(job_id, ADMIN)
    return _ok("get_job", resp)


def current_job_version(job_id):
    return get_job(job_id)["version"]


def create_drawing(job_id, drawing_number="D-1"):
    resp = api_client.create_shop_drawing(
        create_shop_drawing_payload(job_id, drawing_number=drawing_number),
        DETAILER,
    )
    return _ok("create_shop_drawing", resp)


def submit_drawing(drawing_id, submitter=DEFAULT_SUBMITTER):
    resp = api_client.submit_drawing(drawing_id, make_detailer_headers(submitter))
    return _ok("submit_drawing", resp)


def decide_drawing(drawing_id, decision="APPROVE", decider=DEFAULT_APPROVER):
    resp = api_client.decide_drawing(
        drawing_id, decide_drawing_payload(decision), make_eor_headers(decider)
    )
    return _ok("decide_drawing", resp)


def create_approved_drawing(job_id, drawing_number="D-1",
                            submitter=DEFAULT_SUBMITTER,
                            approver=DEFAULT_APPROVER):
    drawing = create_drawing(job_id, drawing_number)
    submit_drawing(drawing["id"], submitter)
    decided = decide_drawing(drawing["id"], "APPROVE", approver)
    assert decided["status"] == "APPROVED", (
        f"Setup failed at decide_drawing: expected APPROVED, "
        f"got {decided['status']}"
    )
    return decided


def revise_drawing(source_drawing_id, expected_drawing_version=None):
    """Cut the next revision (DRAFT) from a source drawing, reading the
    source's current version first when no token is supplied."""
    if expected_drawing_version is None:
        resp = api_client.get_shop_drawing(source_drawing_id, DETAILER)
        source = _ok("get_shop_drawing", resp)
        expected_drawing_version = source["version"]
    resp = api_client.revise_drawing(
        source_drawing_id,
        revise_drawing_payload(expected_drawing_version),
        DETAILER,
    )
    return _ok("revise_drawing", resp)


def revise_and_approve_drawing(source_drawing_id, submitter=DEFAULT_SUBMITTER,
                               approver=DEFAULT_APPROVER):
    """Revise a source drawing, submit the new revision, and approve it —
    firing the supersede cascade on the source when it was APPROVED."""
    new_rev = revise_drawing(source_drawing_id)
    submit_drawing(new_rev["id"], submitter)
    return decide_drawing(new_rev["id"], "APPROVE", approver)


def start_fabrication(job_id):
    resp = api_client.start_fabrication(job_id, ADMIN)
    return _ok("start_fabrication", resp)


def start_erection(job_id):
    resp = api_client.start_erection(job_id, ADMIN)
    return _ok("start_erection", resp)


# ---------------------------------------------------------------------------
# Tier 2 — fabrication readiness (job + approved drawing + released sequence
#           + received mill order)
# ---------------------------------------------------------------------------

def create_fabricating_job(name="Job", billing_basis="WEIGHT",
                           requires_aisc_hold=None, contract_value_cents=None,
                           drawing_number="D-1"):
    """Awarded job with one APPROVED drawing, moved to FABRICATING.
    Returns {"job": job, "drawing": drawing}."""
    job = create_awarded_job(
        name=name, billing_basis=billing_basis,
        requires_aisc_hold=requires_aisc_hold,
        contract_value_cents=contract_value_cents,
    )
    drawing = create_approved_drawing(job["id"], drawing_number)
    job = start_fabrication(job["id"])
    return {"job": job, "drawing": drawing}


def create_sequence(job_id, seq_number=1):
    resp = api_client.create_erection_sequence(
        create_erection_sequence_payload(job_id, seq_number=seq_number), FOREMAN
    )
    return _ok("create_erection_sequence", resp)


def release_sequence(sequence_id):
    resp = api_client.release_sequence(sequence_id, FOREMAN)
    return _ok("release_sequence", resp)


def create_released_sequence(job_id, seq_number=1):
    sequence = create_sequence(job_id, seq_number)
    return release_sequence(sequence["id"])


def place_mill_order(job_id, material_grade="A992", ordered_weight_lbs=None,
                     unit_price_per_cwt_cents=None, billing_mode="NOMINAL"):
    payload = create_mill_order_payload(
        job_id,
        material_grade=material_grade,
        ordered_weight_lbs=(
            TEST_DEFAULTS["ORDERED_WEIGHT_LBS"]
            if ordered_weight_lbs is None else ordered_weight_lbs
        ),
        unit_price_per_cwt_cents=(
            TEST_DEFAULTS["UNIT_PRICE_PER_CWT_CENTS"]
            if unit_price_per_cwt_cents is None else unit_price_per_cwt_cents
        ),
        billing_mode=billing_mode,
    )
    resp = api_client.create_mill_order(payload, ADMIN)
    return _ok("create_mill_order", resp)


def receive_mill_order(order_id, received_weight_lbs=None):
    resp = api_client.receive_mill_order(
        order_id, receive_mill_order_payload(received_weight_lbs), ADMIN
    )
    return _ok("receive_mill_order", resp)


def create_received_mill_order(job_id, **kwargs):
    received = kwargs.pop("received_weight_lbs", None)
    order = place_mill_order(job_id, **kwargs)
    return receive_mill_order(order["id"], received)


def setup_fabrication_ready(name="Job", billing_basis="WEIGHT",
                            requires_aisc_hold=None, begin_erection=False,
                            contract_value_cents=None):
    """Job in FABRICATING with one APPROVED drawing, one RELEASED sequence,
    and one RECEIVED mill order — the four piece-start gates all green.
    Returns {"job", "drawing", "sequence", "mill_order"}."""
    ctx = create_fabricating_job(
        name=name, billing_basis=billing_basis,
        requires_aisc_hold=requires_aisc_hold,
        contract_value_cents=contract_value_cents,
    )
    ctx["sequence"] = create_released_sequence(ctx["job"]["id"])
    if begin_erection:
        ctx["job"] = start_erection(ctx["job"]["id"])
    ctx["mill_order"] = create_received_mill_order(ctx["job"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — pieces through the shop/inspection/shipping pipeline
# ---------------------------------------------------------------------------

def create_piece(job_id, drawing_id, sequence_id, piece_mark="P1",
                 weight_lbs=800):
    resp = api_client.create_piece(
        create_piece_payload(
            job_id, drawing_id, sequence_id,
            piece_mark=piece_mark, weight_lbs=weight_lbs,
        ),
        FOREMAN,
    )
    return _ok("create_piece", resp)


def start_piece(piece_id):
    resp = api_client.start_piece(piece_id, FOREMAN)
    return _ok("start_piece", resp)


def create_in_shop_piece(ctx, piece_mark="P1", weight_lbs=800):
    piece = create_piece(
        ctx["job"]["id"], ctx["drawing"]["id"], ctx["sequence"]["id"],
        piece_mark=piece_mark, weight_lbs=weight_lbs,
    )
    started = start_piece(piece["id"])
    assert started["status"] == "IN_SHOP", (
        f"Setup failed at start_piece: expected IN_SHOP, "
        f"got {started['status']}"
    )
    return started


def schedule_final_inspection(job_id, piece_id):
    resp = api_client.create_inspection(
        create_inspection_payload(job_id, "FINAL_PIECE", piece_id=piece_id), QC
    )
    return _ok("create_inspection(FINAL_PIECE)", resp)


def submit_inspection(inspection_id, outcome="PASSED",
                      inspector=DEFAULT_INSPECTOR):
    resp = api_client.submit_inspection(
        inspection_id, submit_inspection_payload(outcome),
        make_qc_inspector_headers(inspector),
    )
    return _ok("submit_inspection", resp)


def pass_final_inspection(ctx, piece_id):
    """Schedule + pass the FINAL_PIECE inspection; the piece auto-advances
    IN_SHOP -> AWAITING_INSPECTION -> READY_TO_SHIP."""
    inspection = schedule_final_inspection(ctx["job"]["id"], piece_id)
    submitted = submit_inspection(inspection["id"], "PASSED")
    assert submitted["status"] == "PASSED", (
        f"Setup failed at submit_inspection: expected PASSED, "
        f"got {submitted['status']}"
    )
    return submitted


def create_ready_to_ship_piece(ctx, piece_mark="P1", weight_lbs=800):
    piece = create_in_shop_piece(ctx, piece_mark, weight_lbs)
    pass_final_inspection(ctx, piece["id"])
    resp = api_client.get_piece(piece["id"], FOREMAN)
    piece = _ok("get_piece", resp)
    assert piece["status"] == "READY_TO_SHIP", (
        f"Setup failed: expected READY_TO_SHIP, got {piece['status']}"
    )
    return piece


def create_load(job_id, load_number="L-1", laydown_slot="Y-1",
                delivery_date=None, trailer_capacity_lbs=None):
    resp = api_client.create_shipping_load(
        create_shipping_load_payload(
            job_id,
            load_number=load_number,
            laydown_slot=laydown_slot,
            delivery_date=delivery_date or TEST_DEFAULTS["DELIVERY_DATE"],
            trailer_capacity_lbs=(
                TEST_DEFAULTS["TRAILER_CAPACITY_LBS"]
                if trailer_capacity_lbs is None else trailer_capacity_lbs
            ),
        ),
        FOREMAN,
    )
    return _ok("create_shipping_load", resp)


def add_line(load_id, piece_id):
    resp = api_client.add_load_line(
        load_id, add_load_line_payload(piece_id), FOREMAN
    )
    return _ok("add_load_line", resp)


def remove_line(load_id, piece_id):
    resp = api_client.remove_load_line(load_id, piece_id, FOREMAN)
    return _ok("remove_load_line", resp)


def ship_load(load_id):
    resp = api_client.ship_load(load_id, FOREMAN)
    return _ok("ship_load", resp)


def erect_piece(piece_id):
    resp = api_client.erect_piece(piece_id, FOREMAN)
    return _ok("erect_piece", resp)


def create_shipped_piece(ctx, piece_mark="P1", weight_lbs=800,
                         load_number=None, laydown_slot=None,
                         trailer_capacity_lbs=None):
    """READY_TO_SHIP piece placed on its own load and shipped.
    Returns (piece, load)."""
    piece = create_ready_to_ship_piece(ctx, piece_mark, weight_lbs)
    load = create_load(
        ctx["job"]["id"],
        load_number=load_number or f"L-{piece_mark}",
        laydown_slot=laydown_slot or f"Y-{piece_mark}",
        trailer_capacity_lbs=trailer_capacity_lbs,
    )
    add_line(load["id"], piece["id"])
    shipped = ship_load(load["id"])
    assert shipped["status"] == "SHIPPED", (
        f"Setup failed at ship_load: expected SHIPPED, got {shipped['status']}"
    )
    resp = api_client.get_piece(piece["id"], FOREMAN)
    piece = _ok("get_piece", resp)
    assert piece["status"] == "SHIPPED", (
        f"Setup failed: expected SHIPPED piece, got {piece['status']}"
    )
    return piece, shipped


def create_erected_piece(ctx, piece_mark="P1", weight_lbs=800):
    piece, _load = create_shipped_piece(ctx, piece_mark, weight_lbs)
    erected = erect_piece(piece["id"])
    assert erected["status"] == "ERECTED", (
        f"Setup failed at erect_piece: expected ERECTED, "
        f"got {erected['status']}"
    )
    return erected


def setup_job_with_pieces(name="Job", billing_basis="WEIGHT",
                          piece_specs=((("P1", 1000, True),)),
                          begin_erection=False, requires_aisc_hold=None,
                          contract_value_cents=None):
    """Fabrication-ready job whose pieces are created from piece_specs — a
    list of (piece_mark, weight_lbs, erect) triples. Pieces flagged erect are
    walked start -> final-pass -> load -> ship -> erect on their own load.
    Returns {"job", "drawing", "sequence", "mill_order", "pieces"}."""
    ctx = setup_fabrication_ready(
        name=name, billing_basis=billing_basis,
        requires_aisc_hold=requires_aisc_hold, begin_erection=begin_erection,
        contract_value_cents=contract_value_cents,
    )
    ctx["pieces"] = {}
    for mark, weight, erect in piece_specs:
        if erect:
            piece = create_erected_piece(ctx, mark, weight)
        else:
            piece = create_piece(
                ctx["job"]["id"], ctx["drawing"]["id"], ctx["sequence"]["id"],
                piece_mark=mark, weight_lbs=weight,
            )
        ctx["pieces"][mark] = piece
    ctx["job"] = get_job(ctx["job"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — welders, welds, and the repair loop
# ---------------------------------------------------------------------------

def create_welder(full_name="Welder One", qual_process="FCAW",
                  qual_expires_on=None):
    resp = api_client.create_welder(
        create_welder_payload(
            full_name=full_name,
            qual_process=qual_process,
            qual_expires_on=qual_expires_on or TEST_DEFAULTS["QUAL_EXPIRES_ON"],
        ),
        ADMIN,
    )
    return _ok("create_welder", resp)


def log_weld(piece_id, welder_id, process="FCAW", weld_date=None,
             window_start="2026-08-01T09:00:00Z",
             window_end="2026-08-01T10:00:00Z"):
    """Log a weld as the welder themselves (entity-backed identity)."""
    resp = api_client.create_weld(
        create_weld_payload(
            piece_id, welder_id,
            process=process,
            weld_date=weld_date or TEST_DEFAULTS["WELD_DATE"],
            window_start=window_start, window_end=window_end,
        ),
        make_welder_headers(welder_id),
    )
    return _ok("create_weld", resp)


def schedule_weld_inspection(job_id, weld_id, kind):
    resp = api_client.create_inspection(
        create_inspection_payload(job_id, kind, weld_id=weld_id), QC
    )
    return _ok(f"create_inspection({kind})", resp)


def fail_weld_visual(job_id, weld_id, inspector=DEFAULT_INSPECTOR):
    inspection = schedule_weld_inspection(job_id, weld_id, "WELD_VISUAL")
    failed = submit_inspection(inspection["id"], "FAILED", inspector)
    assert failed["status"] == "FAILED"
    return failed


def pass_weld_visual(job_id, weld_id, inspector=DEFAULT_INSPECTOR):
    inspection = schedule_weld_inspection(job_id, weld_id, "WELD_VISUAL")
    passed = submit_inspection(inspection["id"], "PASSED", inspector)
    assert passed["status"] == "PASSED"
    return passed


def repair_weld(weld_id, welder_id):
    resp = api_client.repair_weld(weld_id, make_welder_headers(welder_id))
    return _ok("repair_weld", resp)


# ---------------------------------------------------------------------------
# Tier 5 — field fixes, backcharges, and progress billings
# ---------------------------------------------------------------------------

def create_field_fix(job_id, piece_id, repair_lines=None,
                     description="Field fix"):
    resp = api_client.create_field_fix(
        create_field_fix_payload(
            job_id, piece_id, repair_lines=repair_lines,
            description=description,
        ),
        FOREMAN,
    )
    return _ok("create_field_fix", resp)


def get_backcharge_for_fix(field_fix_id):
    resp = api_client.list_backcharges(GC_PM, params={"field_fix_id": field_fix_id})
    data = _ok("list_backcharges", resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly one backcharge for fix "
        f"{field_fix_id}, got {len(data) if isinstance(data, list) else data}"
    )
    return data[0]


def approve_field_fix(fix_id):
    """GC_PM approval: prices the fix and creates the PENDING backcharge.
    Returns (fix, backcharge)."""
    resp = api_client.approve_field_fix(fix_id, GC_PM)
    fix = _ok("approve_field_fix", resp)
    assert fix["status"] == "APPROVED"
    return fix, get_backcharge_for_fix(fix_id)


def respond_backcharge(backcharge_id, response="ACCEPT"):
    resp = api_client.respond_backcharge(
        backcharge_id, respond_backcharge_payload(response), GC_PM
    )
    return _ok("respond_backcharge", resp)


def settle_backcharge(backcharge_id, settled_amount_cents):
    resp = api_client.settle_backcharge(
        backcharge_id, settle_backcharge_payload(settled_amount_cents), ADMIN
    )
    return _ok("settle_backcharge", resp)


def setup_approved_fix_with_backcharge(ctx, piece_id, repair_lines=None):
    """Field fix on a shipped/erected piece, approved: returns
    (fix APPROVED, backcharge PENDING)."""
    fix = create_field_fix(ctx["job"]["id"], piece_id, repair_lines)
    return approve_field_fix(fix["id"])


def create_billing(job_id, period_label=None, expected_job_version=None):
    """Create a DRAFT billing; reads the job's current version when no OCC
    token is supplied."""
    if expected_job_version is None:
        expected_job_version = current_job_version(job_id)
    resp = api_client.create_progress_billing(
        create_progress_billing_payload(
            job_id, expected_job_version,
            period_label=period_label or TEST_DEFAULTS["PERIOD_LABEL"],
        ),
        ADMIN,
    )
    return _ok("create_progress_billing", resp)


def submit_billing(billing_id):
    resp = api_client.submit_billing(billing_id, ADMIN)
    return _ok("submit_billing", resp)


def approve_billing(billing_id):
    resp = api_client.approve_billing(billing_id, GC_PM)
    return _ok("approve_billing", resp)


def pay_billing(billing_id):
    resp = api_client.pay_billing(billing_id, GC_PM)
    return _ok("pay_billing", resp)


def void_billing(billing_id):
    resp = api_client.void_billing(billing_id, GC_PM)
    return _ok("void_billing", resp)
