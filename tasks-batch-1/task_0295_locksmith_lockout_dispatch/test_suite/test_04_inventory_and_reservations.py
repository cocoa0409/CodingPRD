"""Inventory and part reservations: the conserved unit ledger, the job-cancel and
complete-work cascades, the reserve/release compensation, the
authorization-before-discontinued priority, OCC on LockPart.version, and the stock /
quantity / discontinued / not-found reservation guards.

Difficulty queue: transitive_cascade (depth-3 cancel, depth-2 commit),
compensating_invariant (inventory units), priority_pair_validation_conflict
(safety beats constraint), boundary_precision (zero quantity).
Corner queue: entities (lockpart system fields), validations (insufficient stock,
discontinued), errors (lockpart not found), cross_cutting (OCC version increment,
OCC stale version).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_technician_headers,
    make_customer_headers,
    assert_lock_part_ledger_invariant,
    create_lock_part_payload,
    create_part_reservation_payload,
    create_lock_part,
    setup_drafted_quote,
    reserve_part,
    setup_drafted_quote_with_reservation,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]


# ─── transitive_cascade / job_cancel_cascades_quote_reservation_lockpart_depth3 ─
def test_job_cancel_cascades_to_quote_reservation_and_inventory(api):
    """PRD §3.13: "Every non-terminal quote of the job — those in DRAFTED, SUBMITTED,
    or APPROVED — moves to VOIDED. For each quote so voided, the cascade continues into
    inventory: every RESERVED part reservation under it moves to RELEASED, with the
    part's units_reserved decremented and its units_available incremented by the
    reservation's quantity, restocking the held units."

    Design: Difficulty/transitive_cascade/job_cancel_cascades_quote_reservation_lockpart_depth3
    """
    job, tech, quote, part, reservation = setup_drafted_quote_with_reservation(
        customer_user_id="cust-csc", units_total=5, quantity=2, sku="PIN-CSC"
    )
    assert part["units_available"] == 3 and part["units_reserved"] == 2
    cancelled = validate_success(api.cancel_service_job(job["id"], DISPATCHER), 200)
    assert cancelled["job_status"] == "CANCELLED"
    quote_after = validate_success(api.get_quote(quote["id"], DISPATCHER), 200)
    assert quote_after["status"] == "VOIDED"
    resv_after = validate_success(api.get_part_reservation(reservation["id"], DISPATCHER), 200)
    assert resv_after["status"] == "RELEASED"
    part_after = validate_success(api.get_lock_part(part["id"], INVENTORY), 200)
    assert part_after["units_available"] == 5
    assert part_after["units_reserved"] == 0
    assert_lock_part_ledger_invariant(part_after)


def test_job_cancel_voids_quote_and_restocks_each_hop(api):
    """PRD §3.13: "Cancellation drives the job to the terminal CANCELLED state and
    unwinds everything hanging off it in one operation."
    PRD §3.13: "every RESERVED part reservation under it moves to RELEASED, with the
    part's units_reserved decremented and its units_available incremented by the
    reservation's quantity, restocking the held units."

    Design: Difficulty/transitive_cascade/job_cancel_cascades_quote_reservation_lockpart_depth3
    """
    job, tech, quote, part, reservation = setup_drafted_quote_with_reservation(
        customer_user_id="cust-csc2", units_total=5, quantity=2, sku="PIN-CSC2"
    )
    validate_success(api.cancel_service_job(job["id"], DISPATCHER), 200)
    part_after = validate_success(api.get_lock_part(part["id"], INVENTORY), 200)
    assert part_after["units_committed"] == 0
    assert_lock_part_ledger_invariant(part_after)


# ─── transitive_cascade / quote_approve_then_complete_commits_..._depth2 ───────
def test_complete_work_commits_reservation_and_inventory(api):
    """PRD §3.10: "every RESERVED part reservation under that quote moves from RESERVED
    to COMMITTED, and for each, the corresponding part's units_reserved is decremented
    and its units_committed incremented by the reservation's quantity."

    Design: Difficulty/transitive_cascade/quote_approve_then_complete_commits_reservation_lockpart_depth2
    """
    part = create_lock_part(units_total=5, sku="PIN-CMT")
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-cmt")
    tech_h = make_technician_headers(tech["id"])
    reservation, part = reserve_part(quote["id"], part, 2, tech["id"])
    get_success_data(api.submit_quote(quote["id"], tech_h))
    get_success_data(api.approve_quote(quote["id"], make_customer_headers("cust-cmt")))
    get_success_data(api.complete_work(job["id"], tech_h))
    resv_after = validate_success(api.get_part_reservation(reservation["id"], DISPATCHER), 200)
    assert resv_after["status"] == "COMMITTED"
    part_after = validate_success(api.get_lock_part(part["id"], INVENTORY), 200)
    assert part_after["units_reserved"] == 0
    assert part_after["units_committed"] == 2
    assert part_after["units_available"] == 3
    assert_lock_part_ledger_invariant(part_after)


def test_complete_work_moves_units_reserved_to_committed(api):
    """PRD §3.10: "This is the point at which held stock becomes consumed stock; the
    units leave the reserved pool but stay out of available."

    Design: Difficulty/transitive_cascade/quote_approve_then_complete_commits_reservation_lockpart_depth2
    """
    part = create_lock_part(units_total=5, sku="PIN-CMT2")
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-cmt2")
    tech_h = make_technician_headers(tech["id"])
    _, part = reserve_part(quote["id"], part, 2, tech["id"])
    get_success_data(api.submit_quote(quote["id"], tech_h))
    get_success_data(api.approve_quote(quote["id"], make_customer_headers("cust-cmt2")))
    job_after = validate_success(api.complete_work(job["id"], tech_h), 200)
    assert job_after["job_status"] == "WORK_COMPLETE"
    part_after = validate_success(api.get_lock_part(part["id"], INVENTORY), 200)
    assert part_after["units_available"] == 3
    assert part_after["units_committed"] == 2


# ─── compensating_invariant / inventory_units_conserved_on_reserve_then_release ─
def test_reserve_then_reject_restores_units_no_drift(api):
    """PRD §3.9: "Rejecting the quote moves it from SUBMITTED to REJECTED and, as a
    cascade, releases every RESERVED part reservation under that quote back to
    inventory — each released reservation moves to RELEASED, the corresponding part's
    units_reserved is decremented and its units_available incremented by the
    reservation's quantity."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_on_reserve_then_release
    """
    part = create_lock_part(units_total=5, sku="PIN-COMP")
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-comp")
    tech_h = make_technician_headers(tech["id"])
    reservation, part = reserve_part(quote["id"], part, 2, tech["id"])
    assert part["units_available"] == 3
    get_success_data(api.submit_quote(quote["id"], tech_h))
    get_success_data(api.reject_quote(quote["id"], make_customer_headers("cust-comp")))
    resv_after = validate_success(api.get_part_reservation(reservation["id"], DISPATCHER), 200)
    assert resv_after["status"] == "RELEASED"
    part_after = validate_success(api.get_lock_part(part["id"], INVENTORY), 200)
    assert part_after["units_available"] == 5
    assert part_after["units_reserved"] == 0
    assert part_after["units_committed"] == 0
    assert_lock_part_ledger_invariant(part_after)


def test_reserve_then_release_conserves_total(api):
    """PRD §2.8: "the total physical units owned, units_total, always equals the sum of
    units_available (free to reserve), units_reserved (held by live reservations), and
    units_committed (consumed by completed work)."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_on_reserve_then_release
    """
    part = create_lock_part(units_total=5, sku="PIN-COMP2")
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-comp2")
    tech_h = make_technician_headers(tech["id"])
    _, after_reserve = reserve_part(quote["id"], part, 2, tech["id"])
    assert_lock_part_ledger_invariant(after_reserve)
    get_success_data(api.submit_quote(quote["id"], tech_h))
    get_success_data(api.reject_quote(quote["id"], make_customer_headers("cust-comp2")))
    part_after = validate_success(api.get_lock_part(part["id"], INVENTORY), 200)
    assert part_after["units_total"] == 5
    assert_lock_part_ledger_invariant(part_after)


# ─── priority_pair_validation_conflict / safety_beats_constraint_on_reservation ─
def test_authorization_missing_beats_discontinued_on_reservation(api):
    """PRD §3.7: "restricted-blank authorization is enforced as described below; the
    part must not be discontinued and the requested quantity must be a positive count
    of at least 1 (a DISCONTINUED part yields ERR_PART_DISCONTINUED, a non-positive
    quantity yields ERR_INVALID_QUANTITY)"
    PRD §3.8: "if none exists, the reservation is rejected with ERR_AUTHORIZATION_MISSING."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_reservation
    """
    # Restricted-blank part, then DISCONTINUED; no RESTRICTED_BLANK authorization on file.
    part = get_success_data(
        api.create_lock_part(
            create_lock_part_payload(sku="RB-PRI", units_total=1, restricted_blank=True),
            INVENTORY,
        )
    )
    discontinued = get_success_data(
        api.update_lock_part(
            part["id"],
            {"part_status": "DISCONTINUED", "expected_lockpart_version": part["version"]},
            INVENTORY,
        )
    )
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-pri", service_type="INSTALL")
    res = api.create_part_reservation(
        create_part_reservation_payload(
            on_site_quote_id=quote["id"], lock_part_id=part["id"], quantity=1,
            expected_lockpart_version=discontinued["version"],
        ),
        make_technician_headers(tech["id"]),
    )
    # authorization (safety) check fires before the discontinued (constraint) check
    validate_error(res, "ERR_AUTHORIZATION_MISSING", expected_status=403)


def test_restricted_blank_requires_authorization_on_file(api):
    """PRD §3.8: "When a reservation targets a LockPart whose restricted_blank flag is
    true, the system requires that the quote's parent job already have a
    RESTRICTED_BLANK authorization record on file; if none exists, the reservation is
    rejected with ERR_AUTHORIZATION_MISSING."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_reservation
    """
    part = get_success_data(
        api.create_lock_part(
            create_lock_part_payload(sku="RB-PRI2", units_total=3, restricted_blank=True),
            INVENTORY,
        )
    )
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-pri2", service_type="INSTALL")
    res = api.create_part_reservation(
        create_part_reservation_payload(
            on_site_quote_id=quote["id"], lock_part_id=part["id"], quantity=1,
            expected_lockpart_version=part["version"],
        ),
        make_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_AUTHORIZATION_MISSING", expected_status=403)


# ─── boundary_precision_check / reservation_zero_quantity_empty_count_boundary ──
def test_reservation_zero_quantity_rejected(api):
    """PRD §3.7: "the part must not be discontinued and the requested quantity must be
    a positive count of at least 1 (a DISCONTINUED part yields ERR_PART_DISCONTINUED, a
    non-positive quantity yields ERR_INVALID_QUANTITY)"

    Design: Difficulty/boundary_precision_check/reservation_zero_quantity_empty_count_boundary
    """
    part = create_lock_part(units_total=3, sku="PIN-Q0")
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-q0")
    res = api.create_part_reservation(
        create_part_reservation_payload(
            on_site_quote_id=quote["id"], lock_part_id=part["id"], quantity=0,
            expected_lockpart_version=part["version"],
        ),
        make_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_INVALID_QUANTITY", expected_status=422)


def test_reservation_quantity_one_accepted(api):
    """PRD §3.7: "the requested quantity must be a positive count of at least 1"

    Design: Difficulty/boundary_precision_check/reservation_zero_quantity_empty_count_boundary
    """
    part = create_lock_part(units_total=3, sku="PIN-Q1")
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-q1")
    reservation, _ = reserve_part(quote["id"], part, 1, tech["id"])
    assert reservation["status"] == "RESERVED"
    assert reservation["quantity"] == 1


# ─── Corner: entities / lockpart_system_fields_initialized ─────────────────────
def test_lockpart_system_fields_initialized_on_create(api):
    """PRD §2.8: "On creation a part's units_available equals its units_total, with
    units_reserved and units_committed both starting at 0."
    PRD §2.4: "an integer version that begins at 1 on creation and increments by one
    with each mutation."

    Design: Corner/entities/lockpart_system_fields_initialized
    """
    res = api.create_lock_part(create_lock_part_payload(sku="PIN-INIT", units_total=7), INVENTORY)
    part = validate_success(res, 201)
    assert part["units_available"] == 7
    assert part["units_reserved"] == 0
    assert part["units_committed"] == 0
    assert part["version"] == 1


# ─── Corner: validations / insufficient_stock_rejected ─────────────────────────
def test_insufficient_stock_rejected(api):
    """PRD §3.7: "the part must have enough free stock, meaning units_available is at
    least the requested quantity, else the reservation is refused with
    ERR_INSUFFICIENT_STOCK before any count changes."

    Design: Corner/validations/insufficient_stock_rejected
    """
    part = create_lock_part(units_total=3, sku="PIN-INS")
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-ins")
    res = api.create_part_reservation(
        create_part_reservation_payload(
            on_site_quote_id=quote["id"], lock_part_id=part["id"], quantity=5,
            expected_lockpart_version=part["version"],
        ),
        make_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_INSUFFICIENT_STOCK", expected_status=409)
    part_after = validate_success(api.get_lock_part(part["id"], INVENTORY), 200)
    assert part_after["units_available"] == 3, "no stock touched on refusal"


# ─── Corner: validations / discontinued_part_reservation_rejected ──────────────
def test_discontinued_part_reservation_rejected(api):
    """PRD §3.7: "a DISCONTINUED part yields ERR_PART_DISCONTINUED, a non-positive
    quantity yields ERR_INVALID_QUANTITY"

    Design: Corner/validations/discontinued_part_reservation_rejected
    """
    part = create_lock_part(units_total=3, sku="PIN-DISC")
    discontinued = get_success_data(
        api.update_lock_part(
            part["id"],
            {"part_status": "DISCONTINUED", "expected_lockpart_version": part["version"]},
            INVENTORY,
        )
    )
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-disc")
    res = api.create_part_reservation(
        create_part_reservation_payload(
            on_site_quote_id=quote["id"], lock_part_id=part["id"], quantity=1,
            expected_lockpart_version=discontinued["version"],
        ),
        make_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_PART_DISCONTINUED", expected_status=409)


# ─── Corner: errors / lockpart_not_found_on_reservation ────────────────────────
def test_reservation_against_nonexistent_part_not_found(api):
    """PRD §2.5: "a request that names a non-existent technician, bay, quote, dispatch,
    lock part, reservation, payment, or claim is rejected with the corresponding
    not-found error"

    Design: Corner/errors/lockpart_not_found_on_reservation
    """
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-lnf")
    res = api.create_part_reservation(
        create_part_reservation_payload(
            on_site_quote_id=quote["id"],
            lock_part_id="00000000-0000-4000-8000-000000000000",
            quantity=1, expected_lockpart_version=1,
        ),
        make_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_LOCKPART_NOT_FOUND", expected_status=404)


# ─── Corner: cross_cutting / occ_version_increments_on_reservation ─────────────
def test_reservation_increments_lockpart_version(api):
    """PRD §2.9: "a successful reservation decrements units_available and bumps the
    part's version, so a writer whose view of the part predates a prior reservation is
    holding an out-of-date availability count, and its create must be turned away on
    the version check before it can overspend the stock."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_reservation
    """
    part = create_lock_part(units_total=5, sku="PIN-VINC")
    assert part["version"] == 1
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-vinc")
    reserve_part(quote["id"], part, 1, tech["id"])
    part_after = validate_success(api.get_lock_part(part["id"], INVENTORY), 200)
    assert part_after["version"] == 2
    assert part_after["units_available"] == 4
    assert part_after["units_reserved"] == 1


# ─── Corner: cross_cutting / occ_stale_lockpart_version ────────────────────────
def test_stale_lockpart_version_rejected(api):
    """PRD §2.9: "If that value does not match the part's current version, the create
    is rejected with ERR_STALE_LOCKPART_VERSION and HTTP status 412, and no stock is
    touched."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lockpart_version_excluded
    """
    part = create_lock_part(units_total=5, sku="PIN-OCC")
    stale_version = part["version"]  # version 1
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-occ")
    tech_h = make_technician_headers(tech["id"])
    # first reservation succeeds and bumps version to 2
    get_success_data(
        api.create_part_reservation(
            create_part_reservation_payload(
                on_site_quote_id=quote["id"], lock_part_id=part["id"], quantity=2,
                expected_lockpart_version=stale_version,
            ),
            tech_h,
        )
    )
    # second reservation still carries the stale version-1 value
    res = api.create_part_reservation(
        create_part_reservation_payload(
            on_site_quote_id=quote["id"], lock_part_id=part["id"], quantity=1,
            expected_lockpart_version=stale_version,
        ),
        tech_h,
    )
    validate_error(res, "ERR_STALE_LOCKPART_VERSION", expected_status=412)
