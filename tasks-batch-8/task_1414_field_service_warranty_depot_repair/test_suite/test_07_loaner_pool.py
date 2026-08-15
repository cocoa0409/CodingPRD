"""Loaner pool: windows, selector policy, credit gate, reservation lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    authorize_rma,
    create_customer,
    create_loaner_unit,
    create_model,
    create_reservation,
    create_unit,
    create_draft_rma,
    get_customer,
    get_loaner_unit,
    get_reservation,
    inspect_loaner,
    loaner_reservation_payload,
    return_reservation,
    setup_authorized_loaner_with_reservation,
    setup_authorized_rma,
    setup_catalog,
    ship_reservation,
    validate_error,
    validate_success,
)


def _setup_two_loaner_rmas(deposit=10000, credit=100000):
    """Two AUTHORIZED LOANER RMAs (distinct units, same model), one pool unit."""
    model = create_model()
    customer = create_customer(credit_limit_cents=credit)
    unit_1 = create_unit(model["id"], customer["id"], serial_number="SN-LW-1")
    unit_2 = create_unit(model["id"], customer["id"], serial_number="SN-LW-2")
    lu = create_loaner_unit(model["id"], deposit_value_cents=deposit)
    rma_1 = create_draft_rma(customer["id"], unit_1["id"], service_option="LOANER")
    rma_2 = create_draft_rma(customer["id"], unit_2["id"], service_option="LOANER")
    authorize_rma(rma_1["id"])
    authorize_rma(rma_2["id"])
    return {"model": model, "customer": customer, "lu": lu,
            "rma_1": rma_1, "rma_2": rma_2}


def test_adjacent_half_open_window_allowed(api):
    """PRD §3.7: "Window conflicts use half-open semantics: the new window
    conflicts with an existing `RESERVED` or `SHIPPED` reservation on the same
    unit exactly when the new start is before the existing end and the existing
    start is before the new end, and back-to-back adjacency — the new start
    equal to the existing end — is allowed; a conflict is rejected with
    `ERR_LOANER_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/loaner_window_half_open_adjacency
    """
    ctx = _setup_two_loaner_rmas()
    lu = ctx["lu"]
    create_reservation(ctx["rma_1"]["id"], lu["id"],
                       start_date="2026-08-10", end_date="2026-08-20")
    # Adjacency: new start == existing end is allowed under half-open semantics.
    res_b = create_reservation(ctx["rma_2"]["id"], lu["id"],
                               start_date="2026-08-20", end_date="2026-08-25")
    assert res_b["loaner_unit_id"] == lu["id"]
    assert res_b["status"] == "RESERVED"


def test_one_day_overlap_rejected(api):
    """PRD §3.7: "Window conflicts use half-open semantics: the new window
    conflicts with an existing `RESERVED` or `SHIPPED` reservation on the same
    unit exactly when the new start is before the existing end and the existing
    start is before the new end, and back-to-back adjacency — the new start
    equal to the existing end — is allowed; a conflict is rejected with
    `ERR_LOANER_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/loaner_window_half_open_adjacency
    """
    ctx = _setup_two_loaner_rmas()
    lu = ctx["lu"]
    create_reservation(ctx["rma_1"]["id"], lu["id"],
                       start_date="2026-08-10", end_date="2026-08-20")
    create_reservation(ctx["rma_2"]["id"], lu["id"],
                       start_date="2026-08-20", end_date="2026-08-25")
    # 2026-08-19 < 2026-08-20 cuts into the first reservation's window.
    overlap = api.create_loaner_reservation(
        ctx["rma_2"]["id"],
        loaner_reservation_payload(loaner_unit_id=lu["id"],
                                   start_date="2026-08-19",
                                   end_date="2026-08-21"),
        TEST_USERS["intake_agent_headers"])
    validate_error(overlap, ApiErrorId.ERR_LOANER_WINDOW_OVERLAP)
    assert overlap.status_code == 409
    assert get_customer(ctx["customer"]["id"])["deposit_exposure_cents"] == 20000, (
        "only the two live reservations may count toward exposure")


def test_loaner_window_empty_range_rejected(api):
    """PRD §3.7: "The reservation names a half-open window — a `start_date` that
    is inclusive and an `end_date` that is exclusive, with the end required to
    be strictly after the start or the request fails with
    `ERR_INVALID_LOANER_WINDOW`"

    Design: Corner/validations/loaner_window_empty_range_rejected
    """
    ctx = _setup_two_loaner_rmas()
    res = api.create_loaner_reservation(
        ctx["rma_1"]["id"],
        loaner_reservation_payload(loaner_unit_id=ctx["lu"]["id"],
                                   start_date="2026-08-10",
                                   end_date="2026-08-10"),
        TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_LOANER_WINDOW)
    assert res.status_code == 422


def test_loaner_reservation_on_standard_option_rejected(api):
    """PRD §3.7: "A customer whose RMA carries a `service_option` of `LOANER` or
    `ADVANCE_EXCHANGE` can have a pool unit reserved by an `IntakeAgent`;
    attempting to reserve against a `STANDARD` RMA is rejected with
    `ERR_SERVICE_OPTION_INCOMPATIBLE`."

    Design: Corner/validations/loaner_reservation_on_standard_option_rejected
    """
    ctx = setup_authorized_rma()  # STANDARD service option
    lu = create_loaner_unit(ctx["model"]["id"], deposit_value_cents=10000)
    res = api.create_loaner_reservation(
        ctx["rma"]["id"],
        loaner_reservation_payload(loaner_unit_id=lu["id"]),
        TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_SERVICE_OPTION_INCOMPATIBLE)
    assert res.status_code == 422
    assert get_loaner_unit(lu["id"])["status"] == "AVAILABLE"


def test_loaner_explicit_model_mismatch_rejected(api):
    """PRD §3.7: "An explicit pick whose model differs from the model of the
    RMA's unit is rejected with `ERR_LOANER_MODEL_MISMATCH`."

    Design: Corner/validations/loaner_explicit_model_mismatch_rejected
    """
    model = create_model()
    model2 = create_model(replacement_cost_cents=50000, flat_rate_repair_cents=9000)
    customer = create_customer()
    unit = create_unit(model["id"], customer["id"])
    lu9 = create_loaner_unit(model2["id"], asset_tag="LU-9",
                             deposit_value_cents=10000)
    rma = create_draft_rma(customer["id"], unit["id"], service_option="LOANER")
    authorize_rma(rma["id"])
    res = api.create_loaner_reservation(
        rma["id"], loaner_reservation_payload(loaner_unit_id=lu9["id"]),
        TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_LOANER_MODEL_MISMATCH)
    assert res.status_code == 422


def test_credit_limit_inclusive_boundary_then_exceeded(api):
    """PRD §3.7: "Before any reservation is created, the customer's deposit
    headroom is checked: the customer's `deposit_exposure_cents` plus the
    candidate unit's `deposit_value_cents` must not exceed the customer's
    `credit_limit_cents`, or the reservation fails with
    `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/credit_limit_inclusive_boundary_then_exceeded
    """
    model = create_model()
    customer = create_customer(credit_limit_cents=50000)
    unit_1 = create_unit(model["id"], customer["id"], serial_number="SN-CL-1")
    unit_2 = create_unit(model["id"], customer["id"], serial_number="SN-CL-2")
    lu1 = create_loaner_unit(model["id"], asset_tag="LU-CL-1",
                             deposit_value_cents=50000)
    lu2 = create_loaner_unit(model["id"], asset_tag="LU-CL-2",
                             deposit_value_cents=1)
    rma_1 = create_draft_rma(customer["id"], unit_1["id"], service_option="LOANER")
    rma_2 = create_draft_rma(customer["id"], unit_2["id"], service_option="LOANER")
    authorize_rma(rma_1["id"])
    authorize_rma(rma_2["id"])

    # exposure 0 + 50000 == limit 50000: allowed (must not exceed).
    res1 = create_reservation(rma_1["id"], lu1["id"])
    assert res1["status"] == "RESERVED"

    # exposure 50000 + 1 > 50000: rejected.
    over = api.create_loaner_reservation(
        rma_2["id"], loaner_reservation_payload(loaner_unit_id=lu2["id"]),
        TEST_USERS["intake_agent_headers"])
    validate_error(over, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    assert over.status_code == 402
    assert get_customer(customer["id"])["deposit_exposure_cents"] == 50000, (
        "the rejected reservation must not add exposure")


def test_loaner_auto_select_ranking_and_grade_exclusion(api):
    """PRD §3.7: "When `loaner_unit_id` is omitted, the selector considers pool
    units that are `AVAILABLE`, whose `model_id` matches the RMA's unit model,
    and whose `condition_grade` is `A` or `B` — grade `C` is excluded from
    auto-select — ranks them by `completed_loan_cycles` ascending with ties
    broken by `created_at` ascending (never by identifier), and takes the
    first; an empty candidate set rejects the request with
    `ERR_LOANER_UNAVAILABLE`."

    Design: Corner/calculations/loaner_auto_select_ranking_and_grade_exclusion
    """
    from test_helpers import set_clock
    model = create_model()
    customer = create_customer(credit_limit_cents=200000)
    unit = create_unit(model["id"], customer["id"])
    # Distinct creation instants make the created_at tie-break observable
    # regardless of whether timestamps follow the logical clock.
    set_clock("2026-08-01T00:00:00Z")
    lu_c = create_loaner_unit(model["id"], asset_tag="LU-C", condition_grade="C",
                              deposit_value_cents=10000)
    set_clock("2026-08-02T00:00:00Z")
    lu_a = create_loaner_unit(model["id"], asset_tag="LU-A", condition_grade="A",
                              deposit_value_cents=10000)
    set_clock("2026-08-03T00:00:00Z")
    lu_b = create_loaner_unit(model["id"], asset_tag="LU-B", condition_grade="B",
                              deposit_value_cents=10000)
    set_clock("2026-08-01T00:00:00Z")

    rma = create_draft_rma(customer["id"], unit["id"], service_option="LOANER")
    authorize_rma(rma["id"])
    res = api.create_loaner_reservation(
        rma["id"], loaner_reservation_payload(), TEST_USERS["intake_agent_headers"])
    reservation = validate_success(res, 201)
    assert reservation["loaner_unit_id"] == lu_a["id"], (
        "selector must take the earliest-created eligible unit (LU-C excluded "
        f"by grade); picked {reservation['loaner_unit_id']}")
    assert get_loaner_unit(lu_a["id"])["status"] == "RESERVED"
    assert get_loaner_unit(lu_c["id"])["status"] == "AVAILABLE"
    assert get_loaner_unit(lu_b["id"])["status"] == "AVAILABLE"


def test_loaner_auto_select_empty_pool_rejected(api):
    """PRD §3.7: "When `loaner_unit_id` is omitted, the selector considers pool
    units that are `AVAILABLE`, whose `model_id` matches the RMA's unit model,
    and whose `condition_grade` is `A` or `B` — grade `C` is excluded from
    auto-select — ranks them by `completed_loan_cycles` ascending with ties
    broken by `created_at` ascending (never by identifier), and takes the
    first; an empty candidate set rejects the request with
    `ERR_LOANER_UNAVAILABLE`."

    Design: Corner/calculations/loaner_auto_select_empty_pool_rejected
    """
    model = create_model()
    customer = create_customer()
    unit = create_unit(model["id"], customer["id"])
    lu_c = create_loaner_unit(model["id"], asset_tag="LU-C-ONLY",
                              condition_grade="C", deposit_value_cents=10000)
    rma = create_draft_rma(customer["id"], unit["id"], service_option="LOANER")
    authorize_rma(rma["id"])
    res = api.create_loaner_reservation(
        rma["id"], loaner_reservation_payload(), TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_LOANER_UNAVAILABLE)
    assert res.status_code == 409
    assert get_loaner_unit(lu_c["id"])["status"] == "AVAILABLE"


def test_cancel_authorized_releases_reserved_loaner(api):
    """PRD §3.2: "From `AUTHORIZED` it additionally unwinds the loaner
    commitment: every reservation of the RMA still in `RESERVED` moves to
    `CANCELLED`, each such reservation's loaner unit returns from `RESERVED` to
    `AVAILABLE`, and the customer's `deposit_exposure_cents` is decremented by
    each released unit's `deposit_value_cents`, before the `CANCELLED`
    notification fires."

    Design: Corner/state_machines/cancel_authorized_releases_reserved_loaner
    """
    ctx = setup_authorized_loaner_with_reservation()
    cancelled = validate_success(
        api.cancel_rma(ctx["rma"]["id"], TEST_USERS["intake_agent_headers"]), 200)
    assert cancelled["status"] == "CANCELLED"
    assert get_reservation(ctx["res"]["id"])["status"] == "CANCELLED", (
        "the RESERVED reservation must be cancelled by the cascade")
    assert get_loaner_unit(ctx["lu"]["id"])["status"] == "AVAILABLE", (
        "the loaner unit must return to AVAILABLE")
    assert get_customer(ctx["customer"]["id"])["deposit_exposure_cents"] == 0, (
        "deposit exposure must drop back to 0")


def test_reservation_create_then_cancel_restores_exposure(api):
    """PRD §3.7: "Creating the reservation moves the chosen loaner unit from
    `AVAILABLE` to `RESERVED`, stamps the reservation in `RESERVED` with its
    `mode` copied from the RMA's `service_option`, and adds the unit's
    `deposit_value_cents` to the customer's `deposit_exposure_cents`."
    PRD §3.7: "Cancelling a reservation that has not yet shipped returns it from
    `RESERVED` to `CANCELLED`, the unit from `RESERVED` to `AVAILABLE`, and
    releases the deposit exposure; the same release cascades from an RMA
    cancellation (§3.2) and from the daily auto-cancel (§3.9)."

    Design: Difficulty/compensating_invariant/deposit_exposure_reservation_cancel_invariant
    """
    ctx = setup_authorized_loaner_with_reservation()
    cust_id = ctx["customer"]["id"]
    assert get_customer(cust_id)["deposit_exposure_cents"] == 40000, (
        f"reservation create must add the 40000 deposit, got "
        f"{get_customer(cust_id)['deposit_exposure_cents']}")

    cancelled = validate_success(
        api.cancel_loaner_reservation(ctx["res"]["id"],
                                      TEST_USERS["intake_agent_headers"]), 200)
    assert cancelled["status"] == "CANCELLED"
    assert get_customer(cust_id)["deposit_exposure_cents"] == 0, (
        "cancel must restore the exposure invariant exactly to 0")


def test_reservation_cancel_returns_unit_available(api):
    """PRD §3.7: "Cancelling a reservation that has not yet shipped returns it
    from `RESERVED` to `CANCELLED`, the unit from `RESERVED` to `AVAILABLE`, and
    releases the deposit exposure; the same release cascades from an RMA
    cancellation (§3.2) and from the daily auto-cancel (§3.9)."

    Design: Difficulty/compensating_invariant/deposit_exposure_reservation_cancel_invariant
    """
    ctx = setup_authorized_loaner_with_reservation()
    assert get_loaner_unit(ctx["lu"]["id"])["status"] == "RESERVED"
    validate_success(api.cancel_loaner_reservation(ctx["res"]["id"],
                                                   TEST_USERS["intake_agent_headers"]),
                     200)
    assert get_loaner_unit(ctx["lu"]["id"])["status"] == "AVAILABLE", (
        "cancel must return the unit to AVAILABLE")
    assert get_reservation(ctx["res"]["id"])["status"] == "CANCELLED"


def test_loaner_unit_full_cycle_returns_available(api):
    """PRD §3.7: "A `PASS` returns the unit to `AVAILABLE` and increments its
    `completed_loan_cycles` by one, completing the loan cycle that the
    auto-selector later ranks on."
    PRD §3.7: "Return logistics depend on condition. Receiving a loaner back
    takes a `condition` and an optional `damage_assessment_cents`; return is a
    `LOANER`-mode workflow, and attempting it on an `ADVANCE_EXCHANGE`
    reservation is rejected with `ERR_INVALID_RESERVATION_STATE`. A return in OK
    condition closes the reservation as `CLOSED_RETURNED`"

    Design: Difficulty/non_linear_state_machine/loaner_unit_full_cycle
    """
    ctx = setup_authorized_loaner_with_reservation()
    ship_reservation(ctx["res"]["id"])
    returned = return_reservation(ctx["res"]["id"], condition="OK")
    assert returned["status"] == "CLOSED_RETURNED"
    assert get_loaner_unit(ctx["lu"]["id"])["status"] == "INSPECTION"

    inspected = inspect_loaner(ctx["lu"]["id"], "PASS")
    assert inspected["status"] == "AVAILABLE", (
        f"inspect PASS must close the cycle to AVAILABLE, got {inspected['status']}")
    assert inspected["completed_loan_cycles"] == 1, (
        f"the closed loop must increment completed_loan_cycles to 1, got "
        f"{inspected['completed_loan_cycles']}")


def test_loaner_return_releases_exposure_and_zero_fee_without_due_date(api):
    """PRD §3.7: "The fee is zero while `due_date` is unset, and zero when the
    as-of date is on or before the `due_date` — a loaner returned on its due
    date owes nothing."
    PRD §3.7: "Either way the accrued `late_fee_cents` is finalized per the rule
    below, `returned_at` is pinned, the unit moves from `SHIPPED_OUT` to
    `INSPECTION`, and the customer's deposit exposure is released."

    Design: Difficulty/non_linear_state_machine/loaner_unit_full_cycle
    """
    ctx = setup_authorized_loaner_with_reservation()
    ship_reservation(ctx["res"]["id"])
    # The repaired unit has not shipped, so due_date is unset.
    returned = return_reservation(ctx["res"]["id"], condition="OK")
    assert returned["late_fee_cents"] == 0, (
        f"fee must be zero while due_date is unset, got {returned['late_fee_cents']}")
    assert returned["status"] == "CLOSED_RETURNED"
    assert get_customer(ctx["customer"]["id"])["deposit_exposure_cents"] == 0


def test_inspect_available_loaner_rejected(api):
    """PRD §3.7: "Post-return, a `DepotTechnician` inspects the unit with an
    `outcome`; inspection of a unit not in `INSPECTION` is rejected with
    `ERR_INVALID_LOANER_STATE`."

    Design: Corner/state_machines/inspect_available_loaner_rejected
    """
    model = create_model()
    lu = create_loaner_unit(model["id"])
    res = api.inspect_loaner_unit(lu["id"], {"outcome": "PASS"},
                                  TEST_USERS["depot_technician_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_LOANER_STATE)
    assert res.status_code == 409
    after = get_loaner_unit(lu["id"])
    assert after["status"] == "AVAILABLE"
    assert after["completed_loan_cycles"] == 0
