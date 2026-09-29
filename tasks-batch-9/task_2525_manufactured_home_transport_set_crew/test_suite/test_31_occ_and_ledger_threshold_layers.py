"""Anchored writes and the chargeback ledger's inclusive thresholds.

Two creation endpoints guard a parent's `version` (PRD §2.5) while that parent
advances on its own as its children are recorded (PRD §2.9); the chargeback
ledger then flips a plant to `PROBATION` on an inclusive boundary (PRD §3.1)
and unflips it on reversal (PRD §3.9).
"""

from test_helpers import (
    ApiErrorId,
    adjudicate_damage_claim,
    api_client,
    assert_allocation_sums_exactly,
    create_permit_payload,
    create_set_job_payload,
    current_order_version,
    current_section_version,
    make_claims_adjuster_headers,
    make_network_admin_headers,
    make_permit_desk_headers,
    measure_section,
    open_damage_claim,
    open_order,
    read_damage_claim,
    read_hauler,
    read_order,
    read_order_summary,
    read_permit,
    read_plant,
    read_section,
    read_set_crew,
    read_set_job,
    record_section,
    register_hauler,
    register_plant,
    register_set_crew,
    register_site,
    release_section,
    review_damage_claim,
    reverse_damage_claim,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _order_with_two_floors_then_a_site():
    """Record both floors, capture the order's `version`, then register the site so
    that captured figure is one behind."""
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    set_crew = register_set_crew(daily_capacity=2)
    order = open_order(plant["id"], section_count=2, destination_state="AZ", wind_zone="I")
    first = record_section(order["id"], plant["id"], section_index=1)
    record_section(
        order["id"], plant["id"], section_index=2, mates_to_section_id=first["id"]
    )
    stale_order_version = current_order_version(order["id"])
    register_site(order["id"], pad_type="RUNNER", pier_count=12)
    return {
        "plant": plant,
        "set_crew": set_crew,
        "order": order,
        "stale_order_version": stale_order_version,
    }


def test_booking_a_set_job_refuses_the_order_version_captured_before_the_site_landed():
    """PRD §2.5: "A request to create a set job must carry `expected_order_version`
    matching the current `version` of the `InstallationOrder` named in the body. If
    any other writer has advanced that order's `version` since the client last read
    it, the create is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."
    PRD §2.9: "Creating a child that changes a parent's derived state bumps the
    parent too: recording a home section or a site raises the order's `version`,
    requesting a permit raises the section's `version`, adding a route leg raises
    the permit's `version`, reserving an escort raises the escort crew's `version`,
    and booking a set job raises the order's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_set_job_create_412_on_stale_order_version_and_self_advancing_parent
    """
    world = _order_with_two_floors_then_a_site()
    order_id = world["order"]["id"]
    stale = world["stale_order_version"]
    admin = make_network_admin_headers()

    validate_error(
        api_client.create_set_job(
            create_set_job_payload(order_id, world["set_crew"]["id"], stale), admin
        ),
        ApiErrorId.ERR_STALE_ORDER_VERSION,
        412,
    )
    rows, _meta = validate_paginated(
        api_client.list_set_jobs(admin, params={"order_id": order_id})
    )
    assert rows == [], f"a refused booking must persist no set job, got {rows}"

    fresh = current_order_version(order_id)
    assert fresh == stale + 1, (
        f"registering the site raised the order's version by exactly 1, expected "
        f"{stale + 1}, got {fresh}"
    )

    booked = validate_success(
        api_client.create_set_job(
            create_set_job_payload(order_id, world["set_crew"]["id"], fresh), admin
        ),
        201,
    )
    assert booked["progress_status"] == "SCHEDULED", (
        f"a booked job opens at SCHEDULED, got {booked['progress_status']}"
    )
    assert booked["scope_status"] == "SCOPE_PENDING", (
        f"a booked job opens at SCOPE_PENDING, got {booked['scope_status']}"
    )
    assert read_order(order_id)["version"] == fresh + 1, (
        "booking a set job raises the order's version by exactly 1, expected "
        f"{fresh + 1}, got {read_order(order_id)['version']}"
    )


def test_an_accepted_booking_advances_the_order_so_the_same_version_is_already_stale():
    """PRD §2.5: "The reason this parent needs guarding is that a newly created set
    job legitimately supersedes the order's prior `SCHEDULED` set job, so a client
    working from a stale view of the order would silently retire a booking it never
    observed." PRD §3.6: "Booking a job on an order that already has a set job still
    sitting in `SCHEDULED` retires the old one: it moves `SCHEDULED → SUPERSEDED`
    and the order's posture is re-derived."

    Design: Corner/cross_cutting_complexity_layers/occ_set_job_create_412_on_stale_order_version_and_self_advancing_parent
    """
    world = _order_with_two_floors_then_a_site()
    order_id = world["order"]["id"]
    crew_id = world["set_crew"]["id"]
    admin = make_network_admin_headers()

    fresh = current_order_version(order_id)
    first_job = validate_success(
        api_client.create_set_job(create_set_job_payload(order_id, crew_id, fresh), admin),
        201,
    )

    after_first_booking = read_order(order_id)["version"]
    validate_error(
        api_client.create_set_job(create_set_job_payload(order_id, crew_id, fresh), admin),
        ApiErrorId.ERR_STALE_ORDER_VERSION,
        412,
    )
    assert read_order(order_id)["version"] == after_first_booking, (
        "the refused booking mutates nothing, expected version "
        f"{after_first_booking}, got {read_order(order_id)['version']}"
    )
    assert read_set_job(first_job["id"])["progress_status"] == "SCHEDULED", (
        "the sitting job survives a refused supersession, got "
        f"{read_set_job(first_job['id'])['progress_status']}"
    )

    fresh_again = current_order_version(order_id)
    assert fresh_again == fresh + 1, (
        f"the accepted booking raised the order's version by exactly 1, expected "
        f"{fresh + 1}, got {fresh_again}"
    )

    second_job = validate_success(
        api_client.create_set_job(
            create_set_job_payload(order_id, crew_id, fresh_again), admin
        ),
        201,
    )
    assert second_job["progress_status"] == "SCHEDULED", (
        f"the re-read booking is accepted at SCHEDULED, got {second_job['progress_status']}"
    )
    assert read_set_job(first_job["id"])["progress_status"] == "SUPERSEDED", (
        "the retired booking moves SCHEDULED -> SUPERSEDED, got "
        f"{read_set_job(first_job['id'])['progress_status']}"
    )


def _released_floor():
    """One floor walked AT_PLANT -> MEASURED -> PERMIT_PENDING, keeping both
    intermediate `version` figures."""
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    order = open_order(plant["id"], section_count=1, destination_state="AZ", wind_zone="I")
    section = record_section(order["id"], plant["id"], section_index=1)
    measured = measure_section(section["id"], plant["id"], 168, 150)
    released = release_section(section["id"], plant["id"])
    return {
        "plant": plant,
        "order": order,
        "section": section,
        "version_at_measure": measured["version"],
        "version_at_release": released["version"],
    }


def test_requesting_a_permit_refuses_the_section_version_captured_before_release():
    """PRD §2.5: "A request to create a transport permit must carry
    `expected_section_version` matching the current `version` of the `HomeSection`
    named in the body. If the section's `version` has advanced since the client last
    read it, the request is rejected with `ERR_STALE_SECTION_VERSION` (HTTP 412)."
    PRD §2.4: "Almost every row additionally carries `updated_at`, formatted
    identically to `created_at` and refreshed on every mutation that changes the
    row, and `version`, an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation of that row — including mutations that the row's
    owner never asked for, such as a recomputed balance or a cascaded status change."

    Design: Corner/cross_cutting_complexity_layers/occ_permit_create_412_on_stale_section_version_and_supersession
    """
    world = _released_floor()
    section_id = world["section"]["id"]
    stale = world["version_at_measure"]
    current = world["version_at_release"]
    desk = make_permit_desk_headers()

    assert current == stale + 1, (
        f"releasing the floor raised its version by exactly 1, expected {stale + 1}, "
        f"got {current}"
    )

    validate_error(
        api_client.create_permit(create_permit_payload(section_id, stale), desk),
        ApiErrorId.ERR_STALE_SECTION_VERSION,
        412,
    )
    rows, _meta = validate_paginated(
        api_client.list_permits(desk, params={"section_id": section_id})
    )
    assert rows == [], f"a refused request must persist no permit, got {rows}"
    assert read_section(section_id)["version"] == current, (
        f"the refused request mutates nothing, expected version {current}, "
        f"got {read_section(section_id)['version']}"
    )

    permit = validate_success(
        api_client.create_permit(create_permit_payload(section_id, current), desk), 201
    )
    assert permit["status"] == "REQUESTED", (
        f"a new permit opens at REQUESTED, got {permit['status']}"
    )
    assert permit["paid_amount_cents"] == 0, (
        f"a new permit opens with paid_amount_cents at 0, got {permit['paid_amount_cents']}"
    )


def test_requesting_a_permit_advances_the_floor_so_supersession_needs_a_fresh_read():
    """PRD §2.9: "requesting a permit raises the section's `version`". PRD §3.4:
    "Requesting a permit for a section and issuing state that already has a permit
    sitting in `REQUESTED` or `FEE_PAID` supersedes that earlier permit: it moves
    `REQUESTED → SUPERSEDED` or `FEE_PAID → SUPERSEDED` as the case may be, with
    **no fee refund** — whatever had been remitted stays frozen on the superseded
    row's `paid_amount_cents`."

    Design: Corner/cross_cutting_complexity_layers/occ_permit_create_412_on_stale_section_version_and_supersession
    """
    world = _released_floor()
    section_id = world["section"]["id"]
    at_release = world["version_at_release"]
    desk = make_permit_desk_headers()

    first_permit = validate_success(
        api_client.create_permit(create_permit_payload(section_id, at_release), desk), 201
    )
    after_first = current_section_version(section_id)
    assert after_first == at_release + 1, (
        f"requesting the permit raised the floor's version by exactly 1, expected "
        f"{at_release + 1}, got {after_first}"
    )

    validate_error(
        api_client.create_permit(
            create_permit_payload(section_id, at_release, planned_leg_count=2), desk
        ),
        ApiErrorId.ERR_STALE_SECTION_VERSION,
        412,
    )
    assert read_permit(first_permit["id"])["status"] == "REQUESTED", (
        "the sitting permit survives a refused supersession, got "
        f"{read_permit(first_permit['id'])['status']}"
    )
    assert read_section(section_id)["version"] == after_first, (
        f"the refused request mutates nothing, expected version {after_first}, "
        f"got {read_section(section_id)['version']}"
    )

    second_permit = validate_success(
        api_client.create_permit(
            create_permit_payload(section_id, after_first, planned_leg_count=2), desk
        ),
        201,
    )
    assert second_permit["status"] == "REQUESTED", (
        f"the re-read request is accepted at REQUESTED, got {second_permit['status']}"
    )
    retired = read_permit(first_permit["id"])
    assert retired["status"] == "SUPERSEDED", (
        f"the earlier permit moves REQUESTED -> SUPERSEDED, got {retired['status']}"
    )
    assert retired["paid_amount_cents"] == 0, (
        "the superseded row keeps whatever had been remitted, expected 0, "
        f"got {retired['paid_amount_cents']}"
    )
    rows, _meta = validate_paginated(
        api_client.list_permits(desk, params={"section_id": section_id})
    )
    assert len(rows) == 2, (
        f"exactly the two accepted permits exist, got {len(rows)} rows"
    )


def _two_plants_with_reviewed_claims():
    """Two plants, each with one `PLANT_QC` claim under review: 833,333 cents lands
    exactly on the probation line after the haircut, 833,332 lands one cent short."""
    set_logical_clock()
    plant_on_the_line = register_plant(state_code="AZ")
    plant_one_cent_short = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ"])
    set_crew = register_set_crew()

    claims = {}
    for key, plant, claimed in (
        ("on_the_line", plant_on_the_line, 833333),
        ("one_cent_short", plant_one_cent_short, 833332),
    ):
        order = open_order(plant["id"], section_count=1, destination_state="AZ", wind_zone="I")
        section = record_section(order["id"], plant["id"], section_index=1)
        claim = open_damage_claim(
            order["id"],
            section["id"],
            hauler["id"],
            set_crew["id"],
            headers=make_claims_adjuster_headers(),
            discovered_stage="PLANT_QC",
            claimed_amount_cents=claimed,
            blocks_set=False,
        )
        review_damage_claim(claim["id"])
        claims[key] = {"order": order, "section": section, "claim": claim}

    return {
        "plant_on_the_line": plant_on_the_line,
        "plant_one_cent_short": plant_one_cent_short,
        "hauler": hauler,
        "set_crew": set_crew,
        "claims": claims,
    }


def test_a_plant_flips_to_probation_at_exactly_seven_thousand_five_hundred_dollars():
    """PRD §3.1: "A plant starts life with a `chargeback_balance_cents` of 0 and a
    `status` of `ACTIVE`; that balance is a computed running total of the plant's
    share of settled damage claims, and the plant flips to `PROBATION` once the
    balance reaches seven thousand five hundred dollars — that is, at or above
    750,000 cents — falling back to `ACTIVE` if a reversal drops it below that line."
    PRD §3.9: "Whichever basis is chosen, the approved amount is computed the same
    way: the claimed amount less a ten percent approval haircut — that is, ninety
    percent of `claimed_amount_cents`, rounded half up to whole cents — and stored
    as `approved_amount_cents`."

    Design: Corner/cross_cutting_complexity_layers/plant_probation_threshold_at_exactly_750000_and_one_cent_short
    """
    world = _two_plants_with_reviewed_claims()

    on_the_line = adjudicate_damage_claim(
        world["claims"]["on_the_line"]["claim"]["id"], "STAGE"
    )
    assert on_the_line["approved_amount_cents"] == 750000, (
        "ninety percent of 833333 cents rounds half up to 750000, got "
        f"{on_the_line['approved_amount_cents']}"
    )
    assert on_the_line["plant_charge_cents"] == 750000, (
        "damage found at PLANT_QC charges the whole approved amount to the plant, "
        f"got {on_the_line['plant_charge_cents']}"
    )
    assert_allocation_sums_exactly(on_the_line)

    flipped = read_plant(world["plant_on_the_line"]["id"])
    assert flipped["chargeback_balance_cents"] == 750000, (
        f"the plant's balance is 750000, got {flipped['chargeback_balance_cents']}"
    )
    assert flipped["status"] == "PROBATION", (
        f"750000 cents is at the inclusive probation line, got {flipped['status']}"
    )

    one_cent_short = adjudicate_damage_claim(
        world["claims"]["one_cent_short"]["claim"]["id"], "STAGE"
    )
    assert one_cent_short["approved_amount_cents"] == 749999, (
        "ninety percent of 833332 cents rounds half up to 749999, got "
        f"{one_cent_short['approved_amount_cents']}"
    )
    still_active = read_plant(world["plant_one_cent_short"]["id"])
    assert still_active["chargeback_balance_cents"] == 749999, (
        f"the plant's balance is 749999, got {still_active['chargeback_balance_cents']}"
    )
    assert still_active["status"] == "ACTIVE", (
        f"one cent short of the line leaves the plant ACTIVE, got {still_active['status']}"
    )

    assert read_hauler(world["hauler"]["id"])["chargeback_balance_cents"] == 0, (
        "a stage adjudication charges only the owning party, so the carrier stays at 0"
    )
    assert read_set_crew(world["set_crew"]["id"])["chargeback_balance_cents"] == 0, (
        "a stage adjudication charges only the owning party, so the installer stays at 0"
    )

    summary = read_order_summary(world["claims"]["on_the_line"]["order"]["id"])
    assert summary["network_chargeback_cents"] == 1499999, (
        "the network total is the sum of both approved amounts, expected 1499999, "
        f"got {summary['network_chargeback_cents']}"
    )


def test_a_reversal_recomputes_the_probation_flag_rather_than_latching_it():
    """PRD §3.9: "The three charge fields are zeroed, `allocation_basis` and
    `approved_amount_cents` are cleared back to null, and every party's
    `chargeback_balance_cents` is recomputed in full — dropping the reversed claim
    from every sum, which decreases each balance by exactly what the adjudication
    had added and restores the conserved network chargeback total of §2.9."
    PRD §2.9: "The **network chargeback total** — the sum of every plant's, every
    hauler's and every set crew's `chargeback_balance_cents` — always equals the sum
    of `approved_amount_cents` over all adjudicated damage claims; reversing a claim
    therefore restores the total precisely, with no residue."

    Design: Corner/cross_cutting_complexity_layers/plant_probation_threshold_at_exactly_750000_and_one_cent_short
    """
    world = _two_plants_with_reviewed_claims()
    on_the_line_claim = world["claims"]["on_the_line"]["claim"]["id"]
    adjudicate_damage_claim(on_the_line_claim, "STAGE")
    adjudicate_damage_claim(world["claims"]["one_cent_short"]["claim"]["id"], "STAGE")
    assert read_plant(world["plant_on_the_line"]["id"])["status"] == "PROBATION", (
        "the plant must be on probation before the reversal is meaningful"
    )

    reversed_claim = reverse_damage_claim(on_the_line_claim)
    assert reversed_claim["status"] == "REVERSED", (
        f"the claim moves ADJUDICATED -> REVERSED, got {reversed_claim['status']}"
    )
    assert reversed_claim["approved_amount_cents"] is None, (
        f"approved_amount_cents is cleared to null, got {reversed_claim['approved_amount_cents']}"
    )
    assert reversed_claim["allocation_basis"] is None, (
        f"allocation_basis is cleared to null, got {reversed_claim['allocation_basis']}"
    )
    assert reversed_claim["plant_charge_cents"] == 0, (
        f"the charge fields are zeroed, got {reversed_claim['plant_charge_cents']}"
    )

    restored = read_plant(world["plant_on_the_line"]["id"])
    assert restored["chargeback_balance_cents"] == 0, (
        "the reversed claim drops out of the plant's sum, expected 0, got "
        f"{restored['chargeback_balance_cents']}"
    )
    assert restored["status"] == "ACTIVE", (
        f"a balance below the line returns the plant to ACTIVE, got {restored['status']}"
    )

    untouched = read_plant(world["plant_one_cent_short"]["id"])
    assert untouched["chargeback_balance_cents"] == 749999, (
        "the other plant's balance is unaffected, expected 749999, got "
        f"{untouched['chargeback_balance_cents']}"
    )
    assert untouched["status"] == "ACTIVE", (
        f"the other plant is still one cent short of the line, got {untouched['status']}"
    )

    summary = read_order_summary(world["claims"]["one_cent_short"]["order"]["id"])
    assert summary["network_chargeback_cents"] == 749999, (
        "the network total drops to the one surviving adjudication, expected 749999, "
        f"got {summary['network_chargeback_cents']}"
    )
    assert read_damage_claim(on_the_line_claim)["status"] == "REVERSED", (
        "the reversal is terminal, got "
        f"{read_damage_claim(on_the_line_claim)['status']}"
    )
