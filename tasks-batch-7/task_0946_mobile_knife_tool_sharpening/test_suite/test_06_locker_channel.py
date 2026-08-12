"""The customer-operated locker: assignment, deposit, release, expiry and abandonment."""
from test_helpers import (
    ApiErrorId, ADMIN,
    api_client, assess_item, bench_intake, build_config, create_compartment,
    locker_assign, make_account_owner_headers, make_technician_headers,
    read_compartment, read_item, read_request,
    set_clock, setup_locker_delivered, setup_locker_deposited, setup_locker_request,
    validate_error, validate_success,
    assert_locker_compartment, assert_same_instant,
)


def test_locker_visit_runs_from_assignment_through_to_release():
    """PRD 3.8: "For a `LOCKER` request, the fork runs the other way: each item's
    `custody_location` moves `BENCH → LOCKER`, the compartment moves `ASSIGNED → OCCUPIED`,
    and `hold_expires_at` is reset to the logical clock plus 72 hours."
    PRD 3.6: "On success the compartment moves `OCCUPIED → AVAILABLE`, its `access_code` and
    `current_service_request_id` are cleared, `last_released_at` is stamped with the logical
    clock, and every item moves `custody_location` `LOCKER → DELIVERED` with `delivered_at`
    stamped — which, as §3.8 describes, closes any open loaner on that request and runs the
    inspection chain."

    Design: Corner/state_machines/locker_channel_runs_end_to_end_from_assign_to_release
    """
    world = build_config(with_van=False)
    create_compartment(site_code="SITE-A", size="SMALL")
    request, items, compartment, access_code = setup_locker_delivered(
        world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    assert items[0]["service_status"] == "DELIVERED"
    assert items[0]["custody_location"] == "LOCKER"

    released = validate_success(api_client.release_locker_compartment(
        compartment["id"], {"access_code": access_code},
        make_account_owner_headers(world["account"]["id"])))
    assert_locker_compartment(released)
    assert released["status"] == "AVAILABLE"
    assert released["access_code"] is None
    assert released["current_service_request_id"] is None
    assert released["stored_item_count"] == 0
    assert_same_instant(released["last_released_at"], "2026-05-01T00:00:00Z", "last_released_at")

    item = read_item(items[0]["id"])
    assert item["service_status"] == "DELIVERED"
    assert item["custody_location"] == "DELIVERED"
    assert read_request(request["id"])["status"] == "COMPLETED"


def test_hold_expiry_then_abandonment_dispositions_the_contents():
    """PRD 3.6: "An administrator may move a compartment `OCCUPIED → HOLD_EXPIRED` once the
    logical clock has reached or passed `hold_expires_at`; that clears the `access_code` so
    the customer can no longer self-serve. Later, once the clock has reached `hold_expires_at`
    plus a further 168 hours of grace, the administrator may abandon the contents: every item
    of `current_service_request_id` moves `LOCKER → ABANDONED` on the custody axis and, on the
    work axis, `INTAKE_PENDING → ABANDONED` or `ASSESSED → ABANDONED` depending on which of
    the two it was sitting at when the grace ran out, the compartment moves `HOLD_EXPIRED →
    AVAILABLE`, `current_service_request_id` is cleared, and `last_released_at` is stamped."

    Design: Corner/state_machines/locker_hold_expiry_then_abandonment_dispositions_the_contents
    """
    world = build_config(with_van=False, with_bench=False)
    compartment = create_compartment(site_code="SITE-A", size="SMALL")
    _request, items, _compartment, _code = setup_locker_deposited(
        world, [("CHEF_KNIFE", "ROUTINE_HONE")])

    early = api_client.expire_hold_locker_compartment(compartment["id"], ADMIN)
    validate_error(early, ApiErrorId.ERR_INVALID_STATE.value, 409)

    set_clock("2026-05-04T00:00:00Z")
    expired = validate_success(
        api_client.expire_hold_locker_compartment(compartment["id"], ADMIN))
    assert expired["status"] == "HOLD_EXPIRED"

    set_clock("2026-05-11T00:00:00Z")
    abandoned = validate_success(
        api_client.abandon_locker_compartment(compartment["id"], ADMIN))
    assert abandoned["status"] == "AVAILABLE"
    assert abandoned["current_service_request_id"] is None
    assert_same_instant(abandoned["last_released_at"], "2026-05-11T00:00:00Z",
                        "last_released_at")

    item = read_item(items[0]["id"])
    assert item["custody_location"] == "ABANDONED"
    assert item["service_status"] == "ABANDONED"


def test_compartment_selector_picks_the_smallest_fitting_size():
    """PRD 3.6: "Eligible compartments are ranked by size rank *ascending* — the smallest
    compartment that fits wins, so large compartments stay free for large jobs — with ties
    broken by `created_at` ascending."
    PRD 3.6: "On success the compartment moves `AVAILABLE → ASSIGNED`, a 6-digit `access_code`
    is minted, `current_service_request_id` is set to the request, and `hold_expires_at` is set
    to the logical clock plus 72 hours."

    Design: Corner/calculations/compartment_selector_picks_the_smallest_fitting_size
    """
    world = build_config(with_van=False, with_bench=False)
    large = create_compartment(site_code="SITE-A", size="LARGE")
    medium = create_compartment(site_code="SITE-A", size="MEDIUM")
    small = create_compartment(site_code="SITE-A", size="SMALL")
    request, _items = setup_locker_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])

    chosen = locker_assign(request["id"], world["account"]["id"])
    assert chosen["id"] == small["id"]
    assert chosen["status"] == "ASSIGNED"
    assert chosen["current_service_request_id"] == request["id"]
    assert_same_instant(chosen["hold_expires_at"], "2026-05-04T00:00:00Z", "hold_expires_at")
    assert read_compartment(medium["id"])["status"] == "AVAILABLE"
    assert read_compartment(large["id"])["status"] == "AVAILABLE"


def test_compartment_size_unfit_when_only_a_small_box_exists():
    """PRD 3.6: "Second: if every available compartment at the site fails the size-rank or
    item-capacity test, the answer is `ERR_COMPARTMENT_SIZE_UNFIT`."
    PRD 2.6 rung 43: "At least one available compartment at the site satisfies both the
    size-rank test and the item-capacity test. Otherwise `ERR_COMPARTMENT_SIZE_UNFIT` (422).
    Applies to locker assignment; pre-empts rungs 44–57."

    Design: Corner/validations/compartment_size_unfit_when_only_a_small_box_exists
    """
    world = build_config(specs=("GARDEN_PRUNER",), with_van=False, with_bench=False,
                         account_kwargs={"name": "Green Yard", "account_type": "RESIDENTIAL",
                                         "zone_code": "ZONE_W",
                                         "contact_email": "me@greenyard.test"})
    compartment = create_compartment(site_code="SITE-A", size="SMALL")
    request, _items = setup_locker_request(world, [("GARDEN_PRUNER", "ROUTINE_HONE")])

    response = api_client.locker_assign_service_request(
        request["id"], make_account_owner_headers(world["account"]["id"]))
    error = validate_error(response, ApiErrorId.ERR_COMPARTMENT_SIZE_UNFIT.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_NO_AVAILABLE_COMPARTMENT.value
    assert read_compartment(compartment["id"])["status"] == "AVAILABLE"


def test_site_with_no_compartments_reports_no_available_compartment():
    """PRD 3.6: "First: if the site named by `locker_site_code` has no compartments at all,
    the answer is `ERR_NO_AVAILABLE_COMPARTMENT`."
    PRD 2.6 rung 49: "After the site, size, capacity and turnaround filters described in §3.6
    have been applied, the compartment candidate pool is not empty. Otherwise
    `ERR_NO_AVAILABLE_COMPARTMENT` (409). Applies to locker assignment; pre-empts rungs
    50–57."

    Design: Corner/validations/no_available_compartment_when_the_site_has_none
    """
    world = build_config(with_van=False, with_bench=False)
    elsewhere = create_compartment(site_code="SITE-A", size="SMALL")
    request, _items = setup_locker_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")],
                                           site_code="SITE-Z")

    response = api_client.locker_assign_service_request(
        request["id"], make_account_owner_headers(world["account"]["id"]))
    validate_error(response, ApiErrorId.ERR_NO_AVAILABLE_COMPARTMENT.value, 409)
    assert read_compartment(elsewhere["id"])["status"] == "AVAILABLE"


def test_wrong_access_code_on_deposit_is_refused():
    """PRD 2.6 rung 57: "The `access_code` supplied equals the compartment's `access_code`.
    Otherwise `ERR_ACCESS_CODE_INVALID` (403). Applies to locker deposit and locker release."
    PRD 3.6: "**Deposit** is the customer physically loading the compartment, and it requires
    the supplied `access_code` to equal the compartment's."

    Design: Corner/validations/wrong_access_code_on_deposit_is_refused
    """
    world = build_config(with_van=False, with_bench=False)
    compartment = create_compartment(site_code="SITE-A", size="SMALL")
    request, items = setup_locker_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    locker_assign(request["id"], world["account"]["id"])

    response = api_client.deposit_locker_compartment(
        compartment["id"], {"access_code": "000000"},
        make_account_owner_headers(world["account"]["id"]))
    validate_error(response, ApiErrorId.ERR_ACCESS_CODE_INVALID.value, 403)

    reread = read_compartment(compartment["id"])
    assert reread["status"] == "ASSIGNED"
    assert reread["stored_item_count"] == 0
    assert read_item(items[0]["id"])["custody_location"] == "CUSTOMER"
    assert read_request(request["id"])["status"] == "SUBMITTED"


def test_release_at_the_hold_expiry_instant_is_refused():
    """PRD 2.6 rung 21: "The logical clock is strictly before the compartment's
    `hold_expires_at`. Otherwise `ERR_LOCKER_HOLD_EXPIRED` (409). Applies to locker deposit
    and locker release; pre-empts rungs 22–57."
    PRD 3.6: "**Release** is collection. It requires the compartment to be `OCCUPIED`, the
    logical clock to be strictly before `hold_expires_at`, every item of the holding request to
    have `service_status` `DELIVERED`, and the supplied `access_code` to match."

    Design: Corner/validations/locker_release_after_the_hold_expires_is_refused
    """
    world = build_config(with_van=False)
    compartment = create_compartment(site_code="SITE-A", size="SMALL")
    _request, items, _compartment, access_code = setup_locker_delivered(
        world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    set_clock("2026-05-04T00:00:00Z")

    response = api_client.release_locker_compartment(
        compartment["id"], {"access_code": access_code},
        make_account_owner_headers(world["account"]["id"]))
    validate_error(response, ApiErrorId.ERR_LOCKER_HOLD_EXPIRED.value, 409)

    assert read_compartment(compartment["id"])["status"] == "OCCUPIED"
    item = read_item(items[0]["id"])
    assert item["custody_location"] == "LOCKER"
    assert item["service_status"] == "DELIVERED"


def test_locker_value_authorization_blocks_the_second_high_value_reassessment():
    """PRD 3.6: "Whenever a technician re-prices a locker-channel item, the compartment's
    `stored_value_cents` after the re-pricing must not exceed 25000 cents, unless the request's
    `locker_high_value_authorized` is true; a breach is
    `ERR_LOCKER_VALUE_AUTHORIZATION_REQUIRED`."
    PRD 3.6: "`stored_value_cents` is the sum of `final_gross_cents` over the items of
    `current_service_request_id` whose `custody_location` is `LOCKER` *or* `BENCH` — the value
    follows the metal into the shop, because the shop's liability does not end when the
    compartment empties."

    Design: Corner/validations/locker_value_authorization_required_on_the_second_reassessment
    """
    world = build_config(specs=("DELI_SLICER_BLADE",), tech_certs=["SLICER"], with_van=False,
                         account_kwargs={"name": "Deli Row", "account_type": "COMMERCIAL",
                                         "contact_email": "ops@delirow.test"})
    compartment = create_compartment(site_code="SITE-A", size="LARGE")
    request, items, _c, _code = setup_locker_deposited(
        world,
        [("DELI_SLICER_BLADE", "ROUTINE_HONE"), ("DELI_SLICER_BLADE", "ROUTINE_HONE")],
        locker_high_value_authorized=False)
    bench_intake(request["id"], world["bench"]["id"], world["tech"]["id"])
    first = assess_item(items[0]["id"], "HANDLE_WORK", world["tech"]["id"])
    assert first["final_gross_cents"] == 13500
    assert first["requires_reauthorization"] is True

    response = api_client.assess_request_item(
        items[1]["id"], {"assessed_damage_tier": "HANDLE_WORK"},
        make_technician_headers(world["tech"]["id"]))
    validate_error(response, ApiErrorId.ERR_LOCKER_VALUE_AUTHORIZATION_REQUIRED.value, 409)

    second = read_item(items[1]["id"])
    assert second["assessed_damage_tier"] is None
    assert second["final_gross_cents"] == 4500
    assert read_compartment(compartment["id"])["stored_value_cents"] == 18000


def _released_compartment_world():
    """One SMALL box at SITE-A released at the default clock, plus a waiting request."""
    world = build_config(with_van=False, with_bench=False)
    compartment = create_compartment(site_code="SITE-A", size="SMALL")
    first, _items = setup_locker_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    locker_assign(first["id"], world["account"]["id"])
    validate_success(api_client.cancel_service_request(
        first["id"], make_account_owner_headers(world["account"]["id"])))
    return world, compartment


def test_reassignment_twenty_nine_minutes_after_release_hits_the_turnaround_buffer():
    """PRD 2.6 rung 35: "Every size-fitting available compartment at the site satisfies the
    condition that the logical clock is at or after that compartment's `last_released_at` plus
    30 minutes; the boundary is inclusive, so a clock reading exactly 30 minutes after the
    release passes. Otherwise `ERR_LOCKER_TURNAROUND_CONFLICT` (409)."
    PRD 3.6: "Third: if at least one available compartment passes size and capacity but every
    such compartment fails the 30-minute turnaround test, the answer is
    `ERR_LOCKER_TURNAROUND_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/locker_turnaround_buffer_blocks_reassignment_at_twenty_nine_minutes
    """
    world, compartment = _released_compartment_world()
    set_clock("2026-05-01T00:29:00Z")
    second, _items = setup_locker_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])

    response = api_client.locker_assign_service_request(
        second["id"], make_account_owner_headers(world["account"]["id"]))
    validate_error(response, ApiErrorId.ERR_LOCKER_TURNAROUND_CONFLICT.value, 409)

    reread = read_compartment(compartment["id"])
    assert reread["status"] == "AVAILABLE"
    assert reread["current_service_request_id"] is None
    assert_same_instant(reread["last_released_at"], "2026-05-01T00:00:00Z", "last_released_at")
    assert read_request(second["id"])["status"] == "SUBMITTED"


def test_reassignment_exactly_thirty_minutes_after_release_is_accepted():
    """PRD 2.6 rung 35: "Every size-fitting available compartment at the site satisfies the
    condition that the logical clock is at or after that compartment's `last_released_at` plus
    30 minutes; the boundary is inclusive, so a clock reading exactly 30 minutes after the
    release passes. Otherwise `ERR_LOCKER_TURNAROUND_CONFLICT` (409)."
    PRD 3.6: "A compartment is eligible when it is `AVAILABLE`, its `site_code` equals the
    request's `locker_site_code`, its own size rank is at least the required rank, its size's
    item capacity is at least the request's `item_count`, and either its `last_released_at` is
    null or the logical clock is at or after `last_released_at` plus 30 minutes."

    Design: Difficulty/resource_temporal_overlap/locker_turnaround_buffer_blocks_reassignment_at_twenty_nine_minutes
    """
    world, compartment = _released_compartment_world()
    set_clock("2026-05-01T00:30:00Z")
    second, _items = setup_locker_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])

    assigned = locker_assign(second["id"], world["account"]["id"])
    assert assigned["id"] == compartment["id"]
    assert assigned["status"] == "ASSIGNED"
    assert assigned["current_service_request_id"] == second["id"]
    assert_same_instant(assigned["hold_expires_at"], "2026-05-04T00:30:00Z", "hold_expires_at")
