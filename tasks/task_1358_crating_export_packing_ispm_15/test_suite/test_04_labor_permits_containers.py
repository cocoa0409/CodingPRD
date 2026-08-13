"""Labor bookings, on-site permits, and container load planning (PRD §3.4, §3.6, §3.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    create_labor_booking_payload, create_onsite_permit_payload,
    create_container_payload, create_crew_payload,
    create_customer, create_job, add_item, create_wood_batch,
    accept_quote, submit_and_approve_design, create_design_payload,
    setup_quoted_job_with_item, setup_job_with_approved_design,
    setup_sealed_crate, setup_container_for_crate,
    setup_accepted_job_with_crew, setup_two_jobs_same_customer,
    setup_two_sealed_dg_crates,
    assert_labor_booking, assert_onsite_permit, assert_container, assert_crate,
)
from test_helpers import TEST_USERS

SR = TEST_USERS["sales_rep_headers"]
CD = TEST_USERS["crating_designer_headers"]
SF = TEST_USERS["shop_foreman_headers"]
CO = TEST_USERS["compliance_officer_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]


# ---------------------------------------------------------------------------
# Labor booking economics (corner: calculations)
# ---------------------------------------------------------------------------

def test_onsite_booking_computes_hours_rate_and_total(api, shop_foreman_headers):
    """PRD §3.6: "`hours` is the interval's duration in seconds divided by 3600 and rounded to two decimals; `rate_cents_per_hour` is 8500 for `SHOP` work and 12000 for `ONSITE`; `travel_surcharge_cents` is a flat 15000 per `ONSITE` booking and zero for `SHOP`; and `total_cost_cents` is the hours-times-rate figure rounded half-up to whole cents plus the travel surcharge."
    PRD §3.6: "A booking is born `RESERVED`, is confirmed to `CONFIRMED`, completed to `COMPLETED`, and may be cancelled from `RESERVED` or `CONFIRMED`; any other lifecycle step is rejected with `ERR_INVALID_STATE`."

    Design: Corner/calculations/labor_booking_cost_computed
    """
    _, job, _, crew = setup_accepted_job_with_crew(mode="ONSITE",
                                                   capabilities=("ONSITE_PACK",))
    booking = validate_success(api.create_labor_booking(
        job["id"], create_labor_booking_payload(
            crew["id"], mode="ONSITE",
            start_at="2026-08-10T09:00:00Z", end_at="2026-08-10T11:30:00Z"),
        shop_foreman_headers), 201)
    assert_labor_booking(booking)
    assert booking["hours"] == pytest.approx(2.5, abs=0.001)
    assert booking["rate_cents_per_hour"] == 12000
    assert booking["travel_surcharge_cents"] == 15000
    assert booking["total_cost_cents"] == 45000
    assert booking["status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Crew overlap: half-open adjacency (difficulty: resource_temporal_overlap)
# ---------------------------------------------------------------------------

def _setup_crew_with_first_booking():
    customer, job, item, crew = setup_accepted_job_with_crew(
        capabilities=("SHOP_BUILD",),
        item_overrides={"description": "Fixture", "weight_kg": 40,
                        "declared_value_cents": 20000})
    bk1 = get_success_data(api_client.create_labor_booking(
        job["id"], create_labor_booking_payload(
            crew["id"], mode="SHOP",
            start_at="2026-08-10T09:00:00Z", end_at="2026-08-10T12:00:00Z"), SF))
    return customer, job, item, crew, bk1


def test_back_to_back_booking_on_same_crew_is_adjacency(api, shop_foreman_headers):
    """PRD §3.6: "the new half-open interval must not overlap any existing `RESERVED` or `CONFIRMED` booking of the same crew, though two bookings may touch back-to-back — one ending exactly when the next begins is adjacency, not overlap".

    Design: Difficulty/resource_temporal_overlap/crew_half_open_adjacency_vs_overlap
    """
    _, job, _, crew, _ = _setup_crew_with_first_booking()
    bk2 = validate_success(api.create_labor_booking(
        job["id"], create_labor_booking_payload(
            crew["id"], mode="SHOP",
            start_at="2026-08-10T12:00:00Z", end_at="2026-08-10T14:00:00Z"),
        shop_foreman_headers), 201)
    assert bk2["hours"] == pytest.approx(2.0, abs=0.001)
    assert bk2["status"] == "RESERVED"


def test_overlapping_booking_on_same_crew_rejected(api, shop_foreman_headers):
    """PRD §3.6: "the new half-open interval must not overlap any existing `RESERVED` or `CONFIRMED` booking of the same crew, though two bookings may touch back-to-back — one ending exactly when the next begins is adjacency, not overlap — and a genuine overlap is rejected with `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_half_open_adjacency_vs_overlap
    """
    _, job, _, crew, _ = _setup_crew_with_first_booking()
    get_success_data(api_client.create_labor_booking(
        job["id"], create_labor_booking_payload(
            crew["id"], mode="SHOP",
            start_at="2026-08-10T12:00:00Z", end_at="2026-08-10T14:00:00Z"), SF))
    res = api.create_labor_booking(
        job["id"], create_labor_booking_payload(
            crew["id"], mode="SHOP",
            start_at="2026-08-10T11:00:00Z", end_at="2026-08-10T13:00:00Z"),
        shop_foreman_headers)
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED", expected_status=409)
    data, meta = validate_paginated(api.list_labor_bookings(
        shop_foreman_headers, params={"crew_id": crew["id"]}))
    assert meta["total_count"] == 2, "the rejected booking must not be persisted"


# ---------------------------------------------------------------------------
# Crew qualification for hazmat jobs (corner: validations)
# ---------------------------------------------------------------------------

def test_crew_without_hazmat_cert_rejected_on_hazmat_job(api, shop_foreman_headers):
    """PRD §3.6: "Qualification is enforced at booking: the crew must hold the capability matching the mode — `SHOP_BUILD` for a `SHOP` job, `ONSITE_PACK` for an `ONSITE` job — and must additionally hold `HAZMAT_CERT` whenever the job contains any item flagged `hazmat` or carrying a battery (otherwise `ERR_CREW_UNQUALIFIED`)."

    Design: Corner/validations/crew_unqualified_for_hazmat_job
    """
    _, job, _, crew = setup_accepted_job_with_crew(
        capabilities=("SHOP_BUILD",),
        item_overrides={"description": "Solvent pump", "weight_kg": 40,
                        "hazmat": True, "declared_value_cents": 80000})
    res = api.create_labor_booking(
        job["id"], create_labor_booking_payload(crew["id"], mode="SHOP"),
        shop_foreman_headers)
    validate_error(res, "ERR_CREW_UNQUALIFIED", expected_status=422)


# ---------------------------------------------------------------------------
# On-site permit gate at start-packing (difficulty: cross_entity_state_dependency)
# ---------------------------------------------------------------------------

def _setup_onsite_design_job():
    return setup_job_with_approved_design(
        mode="ONSITE", incoterm="EXW",
        item_overrides={"description": "Lathe bed", "weight_kg": 50,
                        "declared_value_cents": 45000},
        batch_overrides={"received_board_feet": 5000, "stamps_acquired": 2},
        accept=True)


def test_onsite_start_packing_without_permit_rejected(api, shop_foreman_headers):
    """PRD §3.4: "an `ONSITE` job must hold an on-site permit in `CONFIRMED` status (otherwise `ERR_PERMIT_REQUIRED`)".

    Design: Difficulty/cross_entity_state_dependency/onsite_start_packing_requires_confirmed_permit
    """
    ctx = _setup_onsite_design_job()
    res = api.start_packing(ctx["job"]["id"], shop_foreman_headers)
    validate_error(res, "ERR_PERMIT_REQUIRED", expected_status=409)


def test_onsite_start_packing_with_requested_permit_still_rejected(api, shop_foreman_headers):
    """PRD §3.4: "an `ONSITE` job must hold an on-site permit in `CONFIRMED` status (otherwise `ERR_PERMIT_REQUIRED`)".
    PRD §3.6: "A `LogisticsCoordinator` confirms a `REQUESTED` permit to `CONFIRMED`; other lifecycle steps are rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/onsite_start_packing_requires_confirmed_permit
    """
    ctx = _setup_onsite_design_job()
    permit = get_success_data(api_client.create_onsite_permit(
        ctx["job"]["id"], create_onsite_permit_payload(
            window_start="2026-08-10T09:00:00Z", window_end="2026-08-10T12:00:00Z"), LC))
    res = api.start_packing(ctx["job"]["id"], shop_foreman_headers)
    validate_error(res, "ERR_PERMIT_REQUIRED", expected_status=409)

    get_success_data(api_client.confirm_onsite_permit(permit["id"], LC))
    started = validate_success(api.start_packing(ctx["job"]["id"], shop_foreman_headers), 200)
    assert started["status"] == "PACKING"


# ---------------------------------------------------------------------------
# Permit buffered-window conflict (difficulty: resource_temporal_overlap)
# ---------------------------------------------------------------------------

def test_permit_starting_inside_sixty_minute_buffer_rejected(api, logistics_coordinator_headers):
    """PRD §3.6: "the requested closed window, extended by a sixty-minute buffer on both sides, must not intersect the correspondingly buffered window of any other `REQUESTED` or `CONFIRMED` permit bearing the same `site_code` — touching within the buffer still counts as a conflict — and a violation is rejected with `ERR_PERMIT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/permit_buffered_window_conflict
    """
    _, job1, job2 = setup_two_jobs_same_customer("SITE-BUF")
    get_success_data(api_client.create_onsite_permit(
        job1["id"], create_onsite_permit_payload(
            window_start="2026-08-10T09:00:00Z", window_end="2026-08-10T12:00:00Z"), LC))
    res = api.create_onsite_permit(
        job2["id"], create_onsite_permit_payload(
            window_start="2026-08-10T12:30:00Z", window_end="2026-08-10T14:00:00Z"),
        logistics_coordinator_headers)
    validate_error(res, "ERR_PERMIT_WINDOW_CONFLICT", expected_status=409)


def test_permit_outside_buffer_accepted_and_copies_site_code(api, logistics_coordinator_headers):
    """PRD §3.6: "the server copies the `site_code` from the job's customer at creation, and the permit begins as `REQUESTED`".

    Design: Difficulty/resource_temporal_overlap/permit_buffered_window_conflict
    """
    _, job1, job2 = setup_two_jobs_same_customer("SITE-BUF")
    get_success_data(api_client.create_onsite_permit(
        job1["id"], create_onsite_permit_payload(
            window_start="2026-08-10T09:00:00Z", window_end="2026-08-10T12:00:00Z"), LC))
    # A window on the following day is outside the buffered window of the
    # existing permit under any consistent reading of the conflict rule.
    permit2 = validate_success(api.create_onsite_permit(
        job2["id"], create_onsite_permit_payload(
            window_start="2026-08-11T09:00:00Z", window_end="2026-08-11T12:00:00Z"),
        logistics_coordinator_headers), 201)
    assert_onsite_permit(permit2)
    assert permit2["site_code"] == "SITE-BUF"
    assert permit2["status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# Container payload boundary (difficulty: boundary_precision_check)
# ---------------------------------------------------------------------------

def _setup_two_sealed_crates_for_payload():
    """Big crate gross exactly 16780.0 kg; small crate gross 98.6 kg."""
    customer = create_customer(name="Weight Co", site_code="WGT-01")
    job = create_job(customer)
    item1 = add_item(job["id"], description="Press body", length_cm=200, width_cm=200,
                     height_cm=200, weight_kg=16229.2, declared_value_cents=900000)
    item2 = add_item(job["id"], description="Control box", weight_kg=50,
                     declared_value_cents=30000)
    batch = create_wood_batch(received_board_feet=5000, stamps_acquired=4)
    d1 = get_success_data(api_client.create_design(
        item1["id"], create_design_payload(item1["version"]), CD))
    d1 = submit_and_approve_design(d1["id"], batch["id"])
    d2 = get_success_data(api_client.create_design(
        item2["id"], create_design_payload(item2["version"]), CD))
    d2 = submit_and_approve_design(d2["id"], batch["id"])
    accept_quote(customer, job["id"])
    get_success_data(api_client.start_packing(job["id"], SF))
    crate1 = get_success_data(api_client.create_crate(item1["id"], {"design_id": d1["id"]}, SF))
    crate2 = get_success_data(api_client.create_crate(item2["id"], {"design_id": d2["id"]}, SF))
    for crate in (crate1, crate2):
        get_success_data(api_client.build_crate(crate["id"], SF))
        get_success_data(api_client.pack_crate(crate["id"],
                                               {"indicator_g": 75, "moisture_barrier": "NONE"}, SF))
        get_success_data(api_client.seal_crate(crate["id"], CO))
    container = get_success_data(api_client.create_container(
        create_container_payload(container_no="MSKU9990001", size="40FT",
                                 dunnage_weight_kg=10000), LC))
    return {"customer": customer, "job": job, "item1": item1, "item2": item2,
            "batch": batch, "crate1": crate1, "crate2": crate2, "container": container}


def test_load_crate_at_exact_payload_limit_accepted(api, logistics_coordinator_headers):
    """PRD §3.8: "The weight guard adds the container's current `payload_used_kg`, its `dunnage_weight_kg`, and the candidate crate's `gross_weight_kg`, and requires the sum to be no more than `max_payload_kg` — exactly at the limit is admissible — otherwise the load is rejected with `ERR_CONTAINER_OVERWEIGHT`."
    PRD §3.8: "The size pins the `max_payload_kg`: 21770 kilograms for a `20FT`, 26780 for a `40FT`, and 26680 for a `40HC`."

    Design: Difficulty/boundary_precision_check/container_payload_exact_max_allowed
    """
    ctx = _setup_two_sealed_crates_for_payload()
    crate1 = validate_success(api.get_crate(ctx["crate1"]["id"], LC), 200)
    assert crate1["gross_weight_kg"] == pytest.approx(16780.0, abs=0.001), \
        "16229.2 + 306 * 1.8"
    loaded = validate_success(api.load_crate(
        ctx["container"]["id"], {"crate_id": ctx["crate1"]["id"]},
        logistics_coordinator_headers), 200)
    assert loaded["status"] == "LOADED", \
        "10000 dunnage + 16780.0 == 26780 == max_payload_kg: inclusive boundary admissible"
    container = validate_success(api.get_container(ctx["container"]["id"], LC), 200)
    assert container["payload_used_kg"] == pytest.approx(16780.0, abs=0.001)


def test_load_crate_one_kg_over_payload_limit_rejected(api, logistics_coordinator_headers):
    """PRD §3.8: "requires the sum to be no more than `max_payload_kg` — exactly at the limit is admissible — otherwise the load is rejected with `ERR_CONTAINER_OVERWEIGHT`."

    Design: Difficulty/boundary_precision_check/container_payload_exact_max_allowed
    """
    ctx = _setup_two_sealed_crates_for_payload()
    get_success_data(api_client.load_crate(
        ctx["container"]["id"], {"crate_id": ctx["crate1"]["id"]}, LC))
    res = api.load_crate(ctx["container"]["id"], {"crate_id": ctx["crate2"]["id"]},
                         logistics_coordinator_headers)
    validate_error(res, "ERR_CONTAINER_OVERWEIGHT", expected_status=422)
    container = validate_success(api.get_container(ctx["container"]["id"], LC), 200)
    assert container["payload_used_kg"] == pytest.approx(16780.0, abs=0.001), \
        "a rejected load must not partially mutate the payload"
    crate2 = validate_success(api.get_crate(ctx["crate2"]["id"], LC), 200)
    assert crate2["status"] == "SEALED"


# ---------------------------------------------------------------------------
# Container payload conservation (difficulty: compensating_invariant)
# ---------------------------------------------------------------------------

def _setup_sealed_crate_and_20ft_container():
    ctx = setup_sealed_crate(
        item_overrides={"description": "Gearmotor", "weight_kg": 50,
                        "declared_value_cents": 30000},
        batch_overrides={"received_board_feet": 500, "stamps_acquired": 2})
    container = get_success_data(api_client.create_container(
        create_container_payload(container_no="TCLU2223334", size="20FT",
                                 dunnage_weight_kg=0), LC))
    ctx["container"] = container
    return ctx


def test_load_crate_adds_exact_gross_to_payload(api, logistics_coordinator_headers):
    """PRD §3.8: "The container's `payload_used_kg` is computed as the sum of the `gross_weight_kg` of the crates currently assigned to it in `LOADED` status".
    PRD §3.8: "A successful load sets the crate's `container_id`, adds the crate's gross weight to `payload_used_kg`, moves the crate from `SEALED` to `LOADED`".

    Design: Difficulty/compensating_invariant/container_payload_load_unload_conservation
    """
    ctx = _setup_sealed_crate_and_20ft_container()
    loaded = validate_success(api.load_crate(
        ctx["container"]["id"], {"crate_id": ctx["crate"]["id"]},
        logistics_coordinator_headers), 200)
    assert loaded["status"] == "LOADED"
    container = validate_success(api.get_container(ctx["container"]["id"], LC), 200)
    assert container["payload_used_kg"] == pytest.approx(98.6, abs=0.001), \
        "gross = 50 + 27 * 1.8"


def test_unload_crate_restores_payload_to_zero(api, logistics_coordinator_headers):
    """PRD §3.8: "Unloading is the mirror, available only while the container is `PLANNING` (otherwise `ERR_CONTAINER_INVALID_STATE`): the crate must currently be `LOADED`, its `container_id` is cleared, its gross weight leaves `payload_used_kg`, the crate returns to `SEALED`, and a job that had reached `LOADED` reverts to `READY_TO_LOAD`."

    Design: Difficulty/compensating_invariant/container_payload_load_unload_conservation
    """
    ctx = _setup_sealed_crate_and_20ft_container()
    get_success_data(api_client.load_crate(
        ctx["container"]["id"], {"crate_id": ctx["crate"]["id"]}, LC))
    unloaded = validate_success(api.unload_crate(
        ctx["container"]["id"], {"crate_id": ctx["crate"]["id"]},
        logistics_coordinator_headers), 200)
    assert unloaded["status"] == "SEALED"
    assert unloaded["container_id"] is None
    container = validate_success(api.get_container(ctx["container"]["id"], LC), 200)
    assert container["payload_used_kg"] == 0, "no drift after the load/unload pair"


# ---------------------------------------------------------------------------
# Freight class tier floors (corner: calculations)
# ---------------------------------------------------------------------------

def _setup_two_crates_for_freight_class():
    customer = create_customer(name="Freight Co", site_code="FRT-01")
    job = create_job(customer)
    item1 = add_item(job["id"], description="Dense 55", weight_kg=55,
                     declared_value_cents=10000)
    item2 = add_item(job["id"], description="Light 50", weight_kg=50,
                     declared_value_cents=10000)
    batch = create_wood_batch(received_board_feet=500, stamps_acquired=2)
    d1 = get_success_data(api_client.create_design(
        item1["id"], create_design_payload(item1["version"]), CD))
    d1 = submit_and_approve_design(d1["id"], batch["id"])
    d2 = get_success_data(api_client.create_design(
        item2["id"], create_design_payload(item2["version"]), CD))
    d2 = submit_and_approve_design(d2["id"], batch["id"])
    accept_quote(customer, job["id"])
    return item1, item2, d1, d2


def test_freight_class_above_inclusive_tier_floor(api, shop_foreman_headers):
    """PRD §3.4: "From density comes the NMFC `freight_class`, the first tier whose inclusive floor the density meets: at least 800 kilograms per cubic meter earns class `55`; at least 400 earns `60`; at least 200 earns `65`".
    PRD §3.4: "`freight_density_kg_m3` as the gross weight divided by that volume, rounded half-up to two decimals."

    Design: Corner/calculations/freight_class_tier_boundary
    """
    item1, _, d1, _ = _setup_two_crates_for_freight_class()
    crate1 = validate_success(api.create_crate(
        item1["id"], {"design_id": d1["id"]}, shop_foreman_headers), 201)
    assert_crate(crate1)
    assert crate1["freight_density_kg_m3"] == pytest.approx(402.71, abs=0.001), \
        "gross 103.6 / volume 0.257259 m3"
    assert crate1["freight_class"] == "60", "density meets the inclusive 400 floor"


def test_freight_class_just_below_tier_floor(api, shop_foreman_headers):
    """PRD §3.4: "at least 400 earns `60`; at least 200 earns `65`".

    Design: Corner/calculations/freight_class_tier_boundary
    """
    _, item2, _, d2 = _setup_two_crates_for_freight_class()
    crate2 = validate_success(api.create_crate(
        item2["id"], {"design_id": d2["id"]}, shop_foreman_headers), 201)
    assert crate2["freight_density_kg_m3"] == pytest.approx(383.27, abs=0.001), \
        "gross 98.6 / volume 0.257259 m3"
    assert crate2["freight_class"] == "65", "383.27 misses the 400 floor, meets 200"


# ---------------------------------------------------------------------------
# Container lock/unlock guards (corner: state_machines)
# ---------------------------------------------------------------------------

def test_unlock_locked_container_with_payload_rejected(api, logistics_coordinator_headers):
    """PRD §3.8: "Unlocking returns a `LOCKED` container to `PLANNING` only when its `payload_used_kg` is zero".

    Design: Corner/state_machines/container_unlock_with_payload_rejected
    """
    ctx = setup_sealed_crate(
        item_overrides={"description": "Gearmotor", "weight_kg": 50,
                        "declared_value_cents": 30000},
        batch_overrides={"received_board_feet": 500, "stamps_acquired": 2})
    setup_container_for_crate(ctx, size="20FT")
    get_success_data(api_client.lock_container(ctx["container"]["id"], LC))
    res = api.unlock_container(ctx["container"]["id"], logistics_coordinator_headers)
    validate_error(res, "ERR_CONTAINER_INVALID_STATE", expected_status=409)
    container = validate_success(api.get_container(ctx["container"]["id"], LC), 200)
    assert container["status"] == "LOCKED"
    assert container["payload_used_kg"] == pytest.approx(98.6, abs=0.001)


# ---------------------------------------------------------------------------
# Dangerous-goods segregation in a container (corner: validations)
# ---------------------------------------------------------------------------

def test_dg_class_one_crate_shares_container_with_no_other_dg(api, logistics_coordinator_headers):
    """PRD §3.8: "a crate whose item holds an `APPROVED` declaration of `dg_class` `1` may not share a container with any other crate carrying a dangerous-goods declaration of any class, and classes `3` and `5.1` may never be loaded into the same container; violations are rejected with `ERR_DG_SEGREGATION_VIOLATION`."

    Design: Corner/validations/dg_segregation_violation_on_load
    """
    ctx = setup_two_sealed_dg_crates()
    res = api.load_crate(ctx["container"]["id"], {"crate_id": ctx["crate2"]["id"]},
                         logistics_coordinator_headers)
    validate_error(res, "ERR_DG_SEGREGATION_VIOLATION", expected_status=422)
    crate2 = validate_success(api.get_crate(ctx["crate2"]["id"], LC), 200)
    assert crate2["status"] == "SEALED"
    container = validate_success(api.get_container(ctx["container"]["id"], LC), 200)
    assert container["payload_used_kg"] == pytest.approx(86.8, abs=0.001), \
        "only crate1 (gross 40 + 26 * 1.8 = 86.8) is aboard; the rejected load mutated nothing"
