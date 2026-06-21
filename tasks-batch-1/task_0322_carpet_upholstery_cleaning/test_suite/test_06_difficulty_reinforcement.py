"""Second-angle tests for every difficulty instance.

Each difficulty instance carries TWO tests: the primary one lives in its domain
file (test_01..test_05); the complement here asserts a distinct observable of the
same PRD rule (a different boundary point, a different side-effect field, or the
quote/settle read-back path) so the rule is pinned from two directions.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_quoted_job,
    setup_booked_job,
    setup_completed_job,
    setup_invoiced_job,
    setup_customer_with_wallet_credit,
    create_customer,
    create_catalog,
    create_crew,
    create_plan,
    create_job,
    add_room,
    add_addon,
    quote_job,
    book_job,
    start_job,
    complete_job,
    issue_invoice,
    get_crew_version,
    get_job,
    get_customer,
    get_invoice,
    get_slot_status_via_crew,
    count_reserved_slots,
    make_customer_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SERVICE_MANAGER = TEST_USERS["service_manager_headers"]
BILLING = TEST_USERS["billing_headers"]


# ─── dual_variant_calc ─────────────────────────────────────────

def test_quoted_price_frozen_and_read_back_on_job(api):
    """PRD §3.4: "Because the escalation surcharge appears only here, a job with
    three or more heavy rooms settles strictly higher than it quoted, while a
    lightly soiled job settles at the same figure it quoted."
    PRD §3.2: "This quote is a forward projection of the current room and add-on
    set; once frozen it is never recomputed."

    The frozen quoted_price_cents (24000) survives onto the COMPLETED job and is
    strictly below the settled price (28000) after invoicing the 3-HEAVY-room job.

    Design: Difficulty/dual_variant_calc/dual_variant_quote_vs_settle_heavy_job
    """
    ctx = setup_completed_job(
        rooms=[("Living Room", 100, "HEAVY"), ("Den", 120, "HEAVY"), ("Hall", 80, "HEAVY")],
        completed_at_minute=800)
    job = ctx["job"]
    assert job["quoted_price_cents"] == 24000
    invoice = issue_invoice(job)
    job_after = get_job(job["id"])
    assert job_after["quoted_price_cents"] == 24000, "quote is frozen, never recomputed"
    assert job_after["settled_price_cents"] == 28000
    assert job_after["settled_price_cents"] > job_after["quoted_price_cents"]


def test_protectant_after_room_scales_with_total_sqft(api):
    """PRD §3.2: "a PROTECTANT add-on takes the catalog's protectant_cents_per_sqft
    multiplied by the job's current total_sqft, rounded half up to whole cents."

    With protectant rate 12 and a 500-sqft room already present, the PROTECTANT
    line freezes to 12*500 = 6000 — the area-scaled branch, distinct from the
    zero-sqft branch.

    Design: Difficulty/dual_variant_calc/dual_variant_protectant_price_order_sensitivity
    """
    customer = create_customer()
    catalog = create_catalog()  # protectant 12/sqft
    job = create_job(customer, catalog["id"])
    add_room(job, customer["id"], area_label="Great Room", area_sqft=500, soiling_level="LIGHT")
    res = api.add_addon(job["id"], {"addon_type": "PROTECTANT"}, make_customer_headers(customer["id"]))
    addon = validate_success(res, 201)
    assert addon["line_price_cents"] == 6000, \
        f"12*500 = 6000 expected, got {addon['line_price_cents']}"


# ─── combinatorial_formula ────────────────────────────────────

def test_quote_without_plan_has_no_discount(api):
    """PRD §3.2: "the discount percentage is selected from the plan's cadence when
    the job names a recurring_plan_id ... and is zero when the job has no plan."
    PRD §3.1: "A one-off job with no plan earns no discount."

    Same room/add-on/furniture set as the discounted variant but with no plan: the
    quote equals the full pre-discount total 25350 (no 15% reduction).

    Design: Difficulty/combinatorial_formula/combinatorial_mode_a_nonlinear_quote_with_discount
    """
    ctx = setup_quoted_job(
        rooms=[("Living", 200, "LIGHT"), ("Office", 100, "MODERATE")],
        addons=["STAIN", "PROTECTANT"],
        move_furniture=True,
    )
    assert ctx["job"]["quoted_price_cents"] == 25350, \
        f"no-plan quote is the undiscounted 25350, got {ctx['job']['quoted_price_cents']}"


def test_round_then_sum_extends_to_more_rooms(api):
    """PRD §3.2: "that per-room line is rounded half up to whole cents *before*
    being added in; the rooms subtotal is the sum of those individually rounded
    room lines."

    Five identical rooms at rate 7, 3 sqft, MODERATE (26.25 -> 26 each) sum to 130;
    the forbidden sum-then-round path (131.25 -> 131) is excluded.

    Design: Difficulty/combinatorial_formula/combinatorial_mode_b_round_then_sum_order
    """
    ctx = setup_quoted_job(
        rooms=[("R1", 3, "MODERATE"), ("R2", 3, "MODERATE"), ("R3", 3, "MODERATE"),
               ("R4", 3, "MODERATE"), ("R5", 3, "MODERATE")],
        catalog_overrides={"base_rate_cents_per_sqft": 7},
    )
    assert ctx["job"]["quoted_price_cents"] == 130, \
        f"5*26 = 130 expected, got {ctx['job']['quoted_price_cents']}"


# ─── non_linear_state_machine ─────────────────────────────────

def test_denied_claim_leaves_wallet_untouched(api):
    """PRD §3.5: "Denying a claim, which transitions it FILED → DENIED, is
    deliberately the empty mirror of granting: no re-clean job is created, no rooms
    are copied, and no wallet credit is granted. A denied claim simply reaches its
    terminal state with no secondary effect whatsoever."

    The DENIED branch leaves wallet_credit_cents at 0 and reclean_job_id null.

    Design: Difficulty/non_linear_state_machine/nonlinear_guarantee_claim_fork_join
    """
    ctx = setup_completed_job(rooms=[("Rm", 100, "LIGHT")], completed_at_minute=200)
    customer = ctx["customer"]
    hdr = make_customer_headers(customer["id"])
    claim = validate_success(api.file_claim(
        {"cleaning_job_id": ctx["job"]["id"], "reason": "meh", "filed_at_minute": 300}, hdr), 201)
    denied = validate_success(api.deny_claim(claim["id"], SERVICE_MANAGER), 200)
    assert denied["status"] == "DENIED"
    assert denied["reclean_job_id"] is None
    cust_after = get_customer(customer["id"])
    assert cust_after["wallet_credit_cents"] == 0, "deny grants no credit"


def test_reschedule_keeps_job_booked_and_repoints_slot(api):
    """PRD §3.3: "A booked job may be rescheduled any number of times before it
    starts."
    PRD §3.3: "the job's scheduled_slot_id repointed to the new slot and the new
    crew's version incremented."

    Two consecutive reschedules each repoint scheduled_slot_id and leave the job
    BOOKED, releasing every prior slot — the cyclic loop on ScheduledSlot.

    Design: Difficulty/non_linear_state_machine/nonlinear_scheduled_slot_reschedule_cycle
    """
    ctx = setup_booked_job(rooms=[("Rm", 100, "LIGHT")], start_minute=600, end_minute=720)
    crew = ctx["crew"]
    job = ctx["job"]
    slot_0 = job["scheduled_slot_id"]

    v1 = get_crew_version(crew["id"])
    r1 = validate_success(api.reschedule_job(
        job["id"], {"crew_id": crew["id"], "start_minute": 900, "end_minute": 1020,
                    "expected_crew_version": v1}, DISPATCHER), 200)
    slot_1 = r1["scheduled_slot_id"]

    v2 = get_crew_version(crew["id"])
    r2 = validate_success(api.reschedule_job(
        job["id"], {"crew_id": crew["id"], "start_minute": 1200, "end_minute": 1320,
                    "expected_crew_version": v2}, DISPATCHER), 200)
    slot_2 = r2["scheduled_slot_id"]

    assert slot_0 != slot_1 != slot_2
    assert r2["lifecycle_status"] == "BOOKED"
    assert get_slot_status_via_crew(crew["id"], slot_0) == "RELEASED"
    assert get_slot_status_via_crew(crew["id"], slot_1) == "RELEASED"
    assert get_slot_status_via_crew(crew["id"], slot_2) == "RESERVED"


# ─── transitive_cascade ───────────────────────────────────────

def test_reclean_job_copies_customer_and_catalog(api):
    """PRD §3.5: "the system mints a re-clean CleaningJob in DRAFT lifecycle status,
    copying the origin job's customer_id, its service_catalog_id, and its
    recurring_plan_id, and setting the new job's origin_job_id to the origin job's
    id."

    The cascade's first hop (re-clean job creation) preserves the origin's
    customer_id and service_catalog_id.

    Design: Difficulty/transitive_cascade/cascade_grant_to_reclean_job_to_room_copy
    """
    ctx = setup_completed_job(
        rooms=[("Living", 100, "LIGHT"), ("Stairs", 150, "MODERATE")],
        completed_at_minute=800)
    customer = ctx["customer"]
    job_o = ctx["job"]
    hdr = make_customer_headers(customer["id"])
    claim = validate_success(api.file_claim(
        {"cleaning_job_id": job_o["id"], "reason": "resoiled", "filed_at_minute": 900}, hdr), 201)
    granted = validate_success(api.grant_claim(claim["id"], SERVICE_MANAGER), 200)
    reclean = get_job(granted["reclean_job_id"])
    assert reclean["customer_id"] == job_o["customer_id"]
    assert reclean["service_catalog_id"] == job_o["service_catalog_id"]


def test_void_writes_invoice_refund_ledger_entry(api):
    """PRD §3.4: "voiding refunds it by writing a WalletLedgerEntry whose
    delta_cents is the positive wallet_applied_cents and whose reason is
    INVOICE_REFUND."

    After void, the customer's ledger carries an INVOICE_REFUND entry of +2000 — a
    third hop of the void cascade distinct from the billing_status reset.

    Design: Difficulty/transitive_cascade/cascade_void_invoice_to_billing_to_wallet_refund
    """
    base = setup_customer_with_wallet_credit()
    customer = base["customer"]
    catalog = base["catalog"]
    crew = base["crew"]
    job_b = create_job(customer, catalog["id"])
    add_room(job_b, customer["id"], area_label="BillRoom", area_sqft=100, soiling_level="LIGHT")
    job_b = quote_job(job_b, customer["id"])
    job_b = book_job(job_b, crew["id"], 600, 720)
    job_b = start_job(job_b)
    job_b = complete_job(job_b, 800)
    invoice = issue_invoice(job_b)
    assert invoice["wallet_applied_cents"] == 2000

    validate_success(api.void_invoice(invoice["id"], BILLING), 200)

    data, meta = _list(api.list_customer_wallet_ledger(customer["id"], SERVICE_MANAGER))
    refunds = [e for e in data if e["reason"] == "INVOICE_REFUND"]
    assert len(refunds) == 1, f"exactly one INVOICE_REFUND entry expected, got {len(refunds)}"
    assert refunds[0]["delta_cents"] == 2000


# ─── priority_pair_validation_conflict ────────────────────────

def test_book_draft_job_does_not_create_slot(api):
    """PRD §2.6: "if the requested transition is not defined from the resource's
    current state, the request is rejected with the corresponding state error ...
    Only after all of these pass does the system evaluate the operation-specific
    business rules described in Section 3, such as room-count, crew compatibility,
    slot overlap."

    Because the DRAFT-job book fails the state gate before any business rule, the
    crew gains no new RESERVED slot beyond the one ALPHA already holds.

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_temporal_on_book
    """
    customer = create_customer()
    catalog = create_catalog()
    crew = create_crew(crew_name="Rig-PR2", turnaround_buffer_minutes=0)
    setup_booked_job(rooms=[("A", 100, "LIGHT")], customer=customer, catalog=catalog,
                     crew=crew, start_minute=600, end_minute=720)
    beta = create_job(customer, catalog["id"])
    add_room(beta, customer["id"], area_label="B", area_sqft=100, soiling_level="LIGHT")

    crew_v = get_crew_version(crew["id"])
    res = api.book_job(beta["id"],
                       {"crew_id": crew["id"], "start_minute": 650, "end_minute": 770,
                        "expected_crew_version": crew_v},
                       DISPATCHER)
    validate_error(res, "ERR_JOB_NOT_QUOTED", expected_status=409)
    assert count_reserved_slots(crew["id"]) == 1, "no extra slot reserved by the failed book"


def test_book_wrong_service_type_leaves_job_quoted(api):
    """PRD §3.3: "The crew's supported_service_type must equal the service type
    pinned by the job's catalog ... a mismatch is rejected with
    ERR_SERVICE_TYPE_MISMATCH."

    The referential rejection leaves the job in QUOTED (no transition to BOOKED),
    proving the book never reached any later effect.

    Design: Difficulty/priority_pair_validation_conflict/priority_referential_beats_fiscal_on_book
    """
    customer = create_customer()
    catalog = create_catalog(service_type="STEAM")
    dry_crew = create_crew(crew_name="Rig-DRY2", supported_service_type="DRY")
    ctx = setup_quoted_job(rooms=[("Rm", 100, "LIGHT")], customer=customer, catalog=catalog,
                           crew=dry_crew)
    crew_v = get_crew_version(dry_crew["id"])
    res = api.book_job(ctx["job"]["id"],
                       {"crew_id": dry_crew["id"], "start_minute": 600, "end_minute": 720,
                        "expected_crew_version": crew_v},
                       DISPATCHER)
    validate_error(res, "ERR_SERVICE_TYPE_MISMATCH", expected_status=409)
    job_after = get_job(ctx["job"]["id"])
    assert job_after["lifecycle_status"] == "QUOTED"
    assert job_after["scheduled_slot_id"] is None


# ─── boundary_precision_check ─────────────────────────────────

def test_escalation_triggers_at_exactly_three_heavy_rooms(api):
    """PRD §3.4: "if the running count of HEAVY rooms reaches three or more, a
    one-time escalation surcharge of 4000 cents is added."

    Three HEAVY rooms (100 sqft each, rate 50): rooms subtotal 3*8000 = 24000;
    the count reaches exactly 3 so the +4000 escalation applies -> settled 28000,
    strictly above the quoted 24000.

    Design: Difficulty/boundary_precision_check/boundary_heavy_escalation_count_at_three
    """
    ctx = setup_invoiced_job(
        rooms=[("H1", 100, "HEAVY"), ("H2", 100, "HEAVY"), ("H3", 100, "HEAVY")])
    job = ctx["job"]
    assert job["quoted_price_cents"] == 24000
    assert job["settled_price_cents"] == 28000, \
        f"escalation at exactly 3 heavy rooms -> 28000, got {job['settled_price_cents']}"


def test_guarantee_window_one_minute_inside_edge_granted(api):
    """PRD §3.5: "the claim is eligible when the elapsed time since completion ...
    is no greater than that window, with the boundary inclusive."

    dry_time 240 -> window 480; completed 1000, filed 1479 (one minute inside the
    inclusive edge) is eligible and the grant succeeds.

    Design: Difficulty/boundary_precision_check/boundary_guarantee_window_inclusive_edge
    """
    ctx = setup_completed_job(rooms=[("Rm", 100, "LIGHT")], completed_at_minute=1000)
    customer = ctx["customer"]
    hdr = make_customer_headers(customer["id"])
    claim = validate_success(api.file_claim(
        {"cleaning_job_id": ctx["job"]["id"], "reason": "inside", "filed_at_minute": 1479}, hdr), 201)
    granted = validate_success(api.grant_claim(claim["id"], SERVICE_MANAGER), 200)
    assert granted["status"] == "GRANTED"


# ─── cross_entity_state_dependency ────────────────────────────

def test_book_onto_available_crew_succeeds_after_oos_blocks(api):
    """PRD §3.3: "The named crew must be AVAILABLE; booking onto an out-of-service
    crew is rejected with ERR_CREW_UNAVAILABLE."

    Booking the same QUOTED job onto a separate AVAILABLE crew succeeds, confirming
    that the crew-status dependency — not the job — drove the earlier rejection.

    Design: Difficulty/cross_entity_state_dependency/cross_book_requires_crew_available
    """
    customer = create_customer()
    catalog = create_catalog()
    oos_crew = create_crew(crew_name="Rig-OOS2")
    validate_success(api.crew_out_of_service(oos_crew["id"], DISPATCHER), 200)
    ctx = setup_quoted_job(rooms=[("Rm", 100, "LIGHT")], customer=customer, catalog=catalog,
                           crew=oos_crew)
    oos_v = get_crew_version(oos_crew["id"])
    blocked = api.book_job(ctx["job"]["id"],
                           {"crew_id": oos_crew["id"], "start_minute": 600, "end_minute": 720,
                            "expected_crew_version": oos_v},
                           DISPATCHER)
    validate_error(blocked, "ERR_CREW_UNAVAILABLE", expected_status=409)

    good_crew = create_crew(crew_name="Rig-OK")
    ok = validate_success(api.book_job(ctx["job"]["id"],
                          {"crew_id": good_crew["id"], "start_minute": 600, "end_minute": 720,
                           "expected_crew_version": good_crew["version"]},
                          DISPATCHER), 200)
    assert ok["lifecycle_status"] == "BOOKED"


def test_active_customer_quote_succeeds(api):
    """PRD §3.2: "Quoting also requires the owning customer to be ACTIVE."
    PRD §3.2: "On a successful quote, ... the forward-looking quoted_price_cents is
    computed and frozen."

    An ACTIVE owner's quote succeeds (transitions DRAFT -> QUOTED), the positive
    twin of the SUSPENDED rejection — confirming customer status gates the quote.

    Design: Difficulty/cross_entity_state_dependency/cross_quote_requires_customer_active
    """
    customer = create_customer()
    catalog = create_catalog()
    job = create_job(customer, catalog["id"])
    add_room(job, customer["id"], area_label="Rm", area_sqft=100, soiling_level="LIGHT")
    res = api.quote_job(job["id"], make_customer_headers(customer["id"]))
    quoted = validate_success(res, 200)
    assert quoted["lifecycle_status"] == "QUOTED"


# ─── resource_temporal_overlap ────────────────────────────────

def test_book_adjacent_at_body_boundary_allowed(api):
    """PRD §3.3: "a new slot beginning exactly at the buffer boundary — immediately
    after the buffer elapses — is adjacent rather than overlapping and is allowed."

    Crew buffer 0 holds [600,720); a [720,780) request begins exactly at the body
    boundary (buffer elapsed immediately) and is allowed — the complement of the
    body-collision rejection.

    Design: Difficulty/resource_temporal_overlap/overlap_body_collision_on_crew
    """
    customer = create_customer()
    catalog = create_catalog()
    crew = create_crew(crew_name="Rig-ADJ0", turnaround_buffer_minutes=0)
    setup_booked_job(rooms=[("Rm1", 100, "LIGHT")], customer=customer, catalog=catalog,
                     crew=crew, start_minute=600, end_minute=720)
    two = setup_quoted_job(rooms=[("Rm2", 100, "LIGHT")], customer=customer, catalog=catalog,
                           crew=crew)
    crew_v = get_crew_version(crew["id"])
    res = api.book_job(two["job"]["id"],
                       {"crew_id": crew["id"], "start_minute": 720, "end_minute": 780,
                        "expected_crew_version": crew_v},
                       DISPATCHER)
    booked = validate_success(res, 200)
    assert booked["lifecycle_status"] == "BOOKED"


def test_book_exactly_at_buffer_boundary_allowed(api):
    """PRD §3.3: "a new slot beginning exactly at the buffer boundary — immediately
    after the buffer elapses — is adjacent rather than overlapping and is allowed."

    Crew buffer 30 holds [600,720); a [750,810) request begins exactly at 720+30 =
    750, the buffer boundary, and is allowed — the complement of the buffer-tail
    rejection.

    Design: Difficulty/resource_temporal_overlap/overlap_buffer_adjacency_on_crew
    """
    customer = create_customer()
    catalog = create_catalog()
    crew = create_crew(crew_name="Rig-ADJ30", turnaround_buffer_minutes=30)
    setup_booked_job(rooms=[("Rm1", 100, "LIGHT")], customer=customer, catalog=catalog,
                     crew=crew, start_minute=600, end_minute=720)
    two = setup_quoted_job(rooms=[("Rm2", 100, "LIGHT")], customer=customer, catalog=catalog,
                           crew=crew)
    crew_v = get_crew_version(crew["id"])
    res = api.book_job(two["job"]["id"],
                       {"crew_id": crew["id"], "start_minute": 750, "end_minute": 810,
                        "expected_crew_version": crew_v},
                       DISPATCHER)
    booked = validate_success(res, 200)
    assert booked["lifecycle_status"] == "BOOKED"


# ─── compensating_invariant ───────────────────────────────────

def test_invoice_then_void_leaves_job_reinvoiceable(api):
    """PRD §3.4: "Voiding is a compensation that undoes issuance: the job's
    billing_status is reset to UNBILLED and its invoice_id is cleared, returning
    the job to an unbilled state from which it could be invoiced afresh."

    After void, the job re-invoices successfully and the customer's applied wallet
    credit (2000) is available again for the fresh invoice — the conserved-balance
    invariant in action.

    Design: Difficulty/compensating_invariant/invariant_wallet_credit_conserved_on_invoice_then_void
    """
    base = setup_customer_with_wallet_credit()
    customer = base["customer"]
    catalog = base["catalog"]
    crew = base["crew"]
    job_b = create_job(customer, catalog["id"])
    add_room(job_b, customer["id"], area_label="BillRoom", area_sqft=100, soiling_level="LIGHT")
    job_b = quote_job(job_b, customer["id"])
    job_b = book_job(job_b, crew["id"], 600, 720)
    job_b = start_job(job_b)
    job_b = complete_job(job_b, 800)
    inv1 = issue_invoice(job_b)
    validate_success(api.void_invoice(inv1["id"], BILLING), 200)

    inv2 = validate_success(api.issue_invoice(job_b["id"], BILLING), 201)
    assert inv2["wallet_applied_cents"] == 2000, \
        f"restored credit re-applies 2000, got {inv2['wallet_applied_cents']}"
    assert inv2["id"] != inv1["id"]


def test_double_reschedule_then_cancel_clears_all_slots(api):
    """PRD §3.3: "When a cancelled job from QUOTED or BOOKED has a RESERVED slot
    attached, that slot is released, transitioning it RESERVED → RELEASED, and the
    job's scheduled_slot_id is cleared."

    Booking then rescheduling adds and re-points slots; cancelling releases the
    live one so the crew ends with zero RESERVED slots — the count returns to its
    pre-book value despite the intervening reschedule.

    Design: Difficulty/compensating_invariant/invariant_reserved_slot_count_conserved_on_book_then_cancel
    """
    customer = create_customer()
    catalog = create_catalog()
    crew = create_crew(crew_name="Rig-CN2")
    ctx = setup_booked_job(rooms=[("Rm", 100, "LIGHT")], customer=customer, catalog=catalog,
                           crew=crew, start_minute=600, end_minute=720)
    job = ctx["job"]
    v = get_crew_version(crew["id"])
    job = validate_success(api.reschedule_job(
        job["id"], {"crew_id": crew["id"], "start_minute": 900, "end_minute": 1020,
                    "expected_crew_version": v}, DISPATCHER), 200)
    assert count_reserved_slots(crew["id"]) == 1

    cancelled = validate_success(api.cancel_job(job["id"], make_customer_headers(customer["id"])), 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["scheduled_slot_id"] is None
    assert count_reserved_slots(crew["id"]) == 0, "crew returns to 0 reserved slots"


def _list(response):
    body = response.json()
    return body["data"], body["meta"]
