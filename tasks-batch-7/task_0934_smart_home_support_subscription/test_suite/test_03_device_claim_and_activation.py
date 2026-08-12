"""Claiming a unit, the warranty pin, the onboarding handshake and reclaim."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_device,
    assert_is_null,
    assert_same_instant,
    claim,
    claim_and_activate,
    claim_device_payload,
    create_ticket_payload,
    fetch_device,
    fetch_household,
    fetch_subscription,
    list_tickets,
    set_clock,
    setup_account_with_catalog,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["support_agent_headers"]


# ==========================================================================
# Claim-time computations
# ==========================================================================
def test_claim_sets_server_owned_fields_and_the_tier_extended_warranty(api):
    """PRD 3.3: "The device is created with `lifecycle_status` `CLAIMED`,
    `firmware_status` `CURRENT`, `activation_attempts` 0, `activated_at` null and
    `firmware_version` unset, and the household's `entitled_device_count` together
    with the subscription's `overage_device_count` are recomputed."
    PRD 3.3: "A single-use `activation_token` is generated and returned on the
    created row, and `activation_expires_at` is set to the claim instant plus 1440
    minutes, which is 24 hours."
    PRD 3.3: "If the household's subscription has `status` `ACTIVE` or `PAST_DUE`
    **and** the in-force plan's `warranty_extension_months` is greater than 0, the
    total term is the base months plus the extension months and `warranty_basis` is
    recorded as `TIER_EXTENDED`; otherwise the total term is the base months alone
    and `warranty_basis` is recorded as `BASE_ONLY`."

    24 base months plus the PRO plan's 12-month extension from a 2026-04-01
    purchase gives 2029-04-01.

    Design: Corner/entities/device_system_and_computed_fields_ignore_client_supplied_values
    """
    world = setup_account_with_catalog(
        "HUB", plan_kind="PRO", allow_overage=False, name="Sys House", email_prefix="sys"
    )

    data = validate_success(
        api.claim_device(
            claim_device_payload(
                world["household"]["id"], world["catalog"]["id"], "HBX000001", "2026-04-01"
            ),
            world["owner_headers"],
        ),
        201,
    )

    assert_device(data)
    assert data["lifecycle_status"] == "CLAIMED"
    assert data["firmware_status"] == "CURRENT"
    assert data["activation_attempts"] == 0
    assert_same_instant(
        data["activation_expires_at"],
        "2026-05-02T00:00:00Z",
        "Device.activation_expires_at",
    )
    assert data["warranty_basis"] == "TIER_EXTENDED"
    assert_same_instant(
        data["warranty_expires_at"], "2029-04-01T00:00:00Z", "Device.warranty_expires_at"
    )
    assert_is_null(data, "activated_at", "Device")
    assert data["version"] == 1


def test_warranty_is_base_only_when_the_plan_grants_no_extension(api):
    """PRD 3.3: "If the household's subscription has `status` `ACTIVE` or `PAST_DUE`
    **and** the in-force plan's `warranty_extension_months` is greater than 0, the
    total term is the base months plus the extension months and `warranty_basis` is
    recorded as `TIER_EXTENDED`; otherwise the total term is the base months alone
    and `warranty_basis` is recorded as `BASE_ONLY`."
    PRD 3.3: "The `warranty_expires_at` instant is then midnight UTC of the date
    obtained by adding that whole number of months to `purchase_date`, clamping to
    the last day of the target month when the target month has no such
    day-of-month"

    Design: Corner/calculations/warranty_base_only_when_the_plan_grants_no_extension
    """
    world = setup_account_with_catalog(
        "HUB",
        plan_kind="BASIC",
        plan_overrides={"included_device_count": 2},
        allow_overage=False,
        name="War House",
        email_prefix="war",
    )

    data = validate_success(
        api.claim_device(
            claim_device_payload(
                world["household"]["id"], world["catalog"]["id"], "HBX000001", "2026-04-01"
            ),
            world["owner_headers"],
        ),
        201,
    )

    assert data["warranty_basis"] == "BASE_ONLY"
    assert_same_instant(
        data["warranty_expires_at"], "2028-04-01T00:00:00Z", "Device.warranty_expires_at"
    )


def test_claim_without_a_serial_number_is_a_body_shape_failure(api):
    """PRD 2.9 rung 20: "Request-body shape: every required field is present, every
    field has the correct JSON type, and every declared numeric range is honoured"
    PRD 3.3: "Claiming a unit onto a household is an `Owner` or `PlatformAdmin` act
    and takes `household_id`, `catalog_entry_id`, `serial_number` and
    `purchase_date`."

    Design: Corner/entities/device_claim_missing_required_serial_returns_invalid_request
    """
    world = setup_account_with_catalog(
        "HUB", plan_kind="PRO", allow_overage=False, name="Req House", email_prefix="req"
    )

    response = api.claim_device(
        {
            "household_id": world["household"]["id"],
            "catalog_entry_id": world["catalog"]["id"],
            "purchase_date": "2026-04-01",
        },
        world["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    assert fetch_household(world["household"]["id"])["entitled_device_count"] == 0


def test_duplicate_serial_number_is_rejected_as_already_claimed(api):
    """PRD 3.3: "a serial already recorded on any other device — including one long
    since decommissioned — is `ERR_SERIAL_ALREADY_CLAIMED`."
    PRD 2.9 rung 29: "The claimed `serial_number` is not already recorded on any
    `Device` row, in any `lifecycle_status` including `DECOMMISSIONED` — otherwise
    `ERR_SERIAL_ALREADY_CLAIMED`. Applies to device claiming only."

    Design: Corner/validations/duplicate_serial_number_is_rejected_as_already_claimed
    """
    world = setup_account_with_catalog(
        "HUB", plan_kind="PRO", allow_overage=False, name="Dup House", email_prefix="dup"
    )
    claim(
        world["household"]["id"], world["catalog"]["id"], "HBX000001", world["owner_headers"]
    )

    response = api.claim_device(
        claim_device_payload(
            world["household"]["id"], world["catalog"]["id"], "HBX000001", "2026-04-01"
        ),
        world["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_SERIAL_ALREADY_CLAIMED.value, 409)

    assert fetch_household(world["household"]["id"])["entitled_device_count"] == 1


def test_device_read_with_unknown_id_reports_device_not_found(api):
    """PRD 2.9 rung 9: "Every `Device` id named in the path or body exists, including
    every entry of a ring launch's `device_ids` list — otherwise
    `ERR_DEVICE_NOT_FOUND`. Applies to the device endpoints, ticket creation, RMA
    opening and ring launching."

    Design: Corner/entities/device_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_device("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_DEVICE_NOT_FOUND.value, 404)


def test_device_listing_honours_limit_and_reports_the_pagination_envelope(api):
    """PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, its
    minimum accepted value is 1 and its maximum accepted value is 100."
    PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching
    the filters before pagination is applied and `has_more` is true exactly when rows
    remain beyond the current page."

    Design: Corner/entities/device_list_returns_pagination_envelope_and_honours_limit
    """
    world = setup_account_with_catalog(
        "SENSOR",
        plan_kind="PRO",
        plan_overrides={"included_device_count": 5},
        allow_overage=False,
        name="Page House",
        email_prefix="page",
    )
    for serial in ("SNB000001", "SNB000002", "SNB000003"):
        claim(
            world["household"]["id"],
            world["catalog"]["id"],
            serial,
            world["owner_headers"],
        )

    response = api.list_devices(
        ADMIN, params={"household_id": world["household"]["id"], "limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_reclaim_on_an_active_device_is_not_eligible(api):
    """PRD 3.3: "Reclaim requested against a device in any other lifecycle state is
    refused with `ERR_RECLAIM_NOT_ELIGIBLE`."
    PRD 3.3: "A correct code succeeds: `lifecycle_status` moves from `CLAIMED` to
    `ACTIVE`, `activated_at` is stamped with the logical-clock instant,
    `firmware_version` is set to the catalog entry's `current_firmware_version`,
    `activation_token` is cleared to null, the household's `active_device_count` is
    recomputed and `Device.version` rises by one."

    Design: Corner/state_machines/reclaim_on_an_active_device_is_rejected_as_not_eligible
    """
    world = setup_account_with_catalog(
        "HUB", plan_kind="PRO", allow_overage=False, name="Rec2 House", email_prefix="rec2"
    )
    device = claim_and_activate(
        world["household"]["id"], world["catalog"]["id"], "HBX000001", world["owner_headers"]
    )

    response = api.reclaim_device(device["id"], {}, AGENT)
    validate_error(response, ApiErrorId.ERR_RECLAIM_NOT_ELIGIBLE.value, 409)

    current = fetch_device(device["id"])
    assert current["lifecycle_status"] == "ACTIVE"
    assert_is_null(current, "activation_token", "Device")


def test_overage_books_nothing_when_fewer_than_five_days_remain(api):
    """PRD 3.3: "If at least 5 days remain, the charge is the plan's
    `overage_fee_cents_per_device` multiplied by the days remaining, divided by 30,
    rounded half up to whole cents; that amount is added both to
    `overage_charges_cents_this_cycle` and to `next_invoice_adjustment_cents`. If
    fewer than 5 days remain, nothing is charged now — but the device is still
    flagged `is_overage`, so the full per-device fee applies from the next cycle
    onward."

    2026-05-27 leaves 4 whole days of a cycle ending 2026-05-31.

    Design: Corner/calculations/overage_charge_is_zero_when_fewer_than_five_days_remain_in_the_cycle
    """
    world = setup_account_with_catalog(
        "HUB",
        plan_kind="PRO",
        plan_overrides={"included_device_count": 1},
        allow_overage=True,
        name="Late House",
        email_prefix="late",
    )
    first = claim(
        world["household"]["id"], world["catalog"]["id"], "HBX000001", world["owner_headers"]
    )
    set_clock("2026-05-27T00:00:00Z")

    second = validate_success(
        api.claim_device(
            claim_device_payload(
                world["household"]["id"], world["catalog"]["id"], "HBX000002", "2026-04-01"
            ),
            world["owner_headers"],
        ),
        201,
    )

    assert second["is_overage"] is True
    assert fetch_device(first["id"])["is_overage"] is False
    subscription = fetch_subscription(world["subscription"]["id"])
    assert subscription["overage_device_count"] == 1
    assert subscription["overage_charges_cents_this_cycle"] == 0
    assert subscription["next_invoice_adjustment_cents"] == 0
    assert fetch_household(world["household"]["id"])["entitled_device_count"] == 2


def test_decommissioned_device_gate_blocks_a_ticket_naming_that_device(api):
    """PRD 2.8: "If the `Device` the request resolves to has `lifecycle_status` equal
    to `DECOMMISSIONED`, the request is refused with `ERR_DEVICE_DECOMMISSIONED`
    (HTTP 409)."
    PRD 3.5: "a ticket naming a decommissioned device is refused by gate 2 with
    `ERR_DEVICE_DECOMMISSIONED`."
    PRD 3.4: "From `CLAIMED`, the move to `DECOMMISSIONED` recomputes the household's
    `entitled_device_count`."

    Design: Corner/validations/decommissioned_device_gate_blocks_ticket_creation_for_that_device
    """
    world = setup_account_with_catalog(
        "HUB", plan_kind="PRO", allow_overage=False, name="Decom House", email_prefix="dec"
    )
    device = claim(
        world["household"]["id"], world["catalog"]["id"], "HBX000001", world["owner_headers"]
    )
    validate_success(api.decommission_device(device["id"], {}, world["owner_headers"]), 200)

    response = api.create_ticket(
        create_ticket_payload(
            world["household"]["id"],
            severity="P2",
            summary="Old hub noise",
            device_id=device["id"],
            opened_by_member_id=world["owner"]["id"],
        ),
        world["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DEVICE_DECOMMISSIONED.value, 409)

    assert fetch_device(device["id"])["lifecycle_status"] == "DECOMMISSIONED"
    assert fetch_household(world["household"]["id"])["entitled_device_count"] == 0
    assert list_tickets(household_id=world["household"]["id"]) == []


def test_device_version_rises_by_exactly_one_on_each_mutation(api):
    """PRD 2.4: "a `version` integer that begins at 1 when the row is created and
    increases by exactly 1 each time the row is mutated."
    PRD 2.4: "**`Device`** — bumped by every operation that changes either of its two
    status axes or its onboarding fields: activation (successful or failed),
    reclaim, decommission, transfer, transfer acceptance, entry into and exit from
    service hold, entry into and exit from RMA suspension, enrolment in a firmware
    ring, every rollout result, deferral, retry, and blocking or unblocking of a
    rollout."

    Design: Corner/cross_cutting_layers/device_version_increments_by_one_on_every_mutation
    """
    world = setup_account_with_catalog(
        "HUB", plan_kind="PRO", allow_overage=False, name="Ver House", email_prefix="ver"
    )

    claimed = validate_success(
        api.claim_device(
            claim_device_payload(
                world["household"]["id"], world["catalog"]["id"], "HBX000001", "2026-04-01"
            ),
            world["owner_headers"],
        ),
        201,
    )
    assert claimed["version"] == 1

    activated = validate_success(
        api.activate_device(
            claimed["id"],
            {"activation_code": claimed["activation_token"]},
            world["owner_headers"],
        ),
        200,
    )
    assert activated["version"] == 2

    decommissioned = validate_success(
        api.decommission_device(claimed["id"], {}, world["owner_headers"]), 200
    )
    assert decommissioned["version"] == 3
    assert decommissioned["lifecycle_status"] == "DECOMMISSIONED"
    # The logical clock never moved, so updated_at is still the claim instant.
    assert_same_instant(
        decommissioned["updated_at"], "2026-05-01T00:00:00Z", "Device.updated_at"
    )


# ==========================================================================
# Difficulty: the boundary claim that lands exactly on included_device_count
# ==========================================================================
def test_claim_landing_exactly_on_the_included_count_is_not_an_overage_device(api):
    """PRD 3.3: "If that post-claim count is less than or equal to *included*, the
    device is inside the entitlement and `is_overage` is set false — note the
    boundary, so the claim that brings the count to exactly the included number is
    free."

    Design: Difficulty/boundary_precision_check/claim_that_lands_exactly_on_included_device_count_is_not_overage
    """
    world = setup_account_with_catalog(
        "SENSOR",
        plan_kind="PLUS",
        allow_overage=True,
        name="Edge House",
        email_prefix="edge",
    )
    claim(
        world["household"]["id"], world["catalog"]["id"], "SNB000001", world["owner_headers"]
    )

    second = validate_success(
        api.claim_device(
            claim_device_payload(
                world["household"]["id"], world["catalog"]["id"], "SNB000002", "2026-04-01"
            ),
            world["owner_headers"],
        ),
        201,
    )

    assert second["is_overage"] is False
    assert fetch_household(world["household"]["id"])["entitled_device_count"] == 2


def test_claim_landing_exactly_on_the_included_count_books_no_overage_cents(api):
    """PRD 3.3: "**Second, the overage charge**, which runs only when the entitlement
    check returned an overage."
    PRD 3.2: "`overage_device_count` counts the household's devices flagged
    `is_overage` whose `lifecycle_status` is `CLAIMED`, `ACTIVE`, `SERVICE_HOLD`,
    `SUSPENDED_RMA` or `TRANSFER_PENDING`."

    Design: Difficulty/boundary_precision_check/claim_that_lands_exactly_on_included_device_count_is_not_overage
    """
    world = setup_account_with_catalog(
        "SENSOR",
        plan_kind="PLUS",
        allow_overage=True,
        name="Edge House",
        email_prefix="edge",
    )
    claim(
        world["household"]["id"], world["catalog"]["id"], "SNB000001", world["owner_headers"]
    )
    claim(
        world["household"]["id"], world["catalog"]["id"], "SNB000002", world["owner_headers"]
    )

    subscription = fetch_subscription(world["subscription"]["id"])
    assert subscription["overage_device_count"] == 0
    assert subscription["overage_charges_cents_this_cycle"] == 0
    assert subscription["next_invoice_adjustment_cents"] == 0


# ==========================================================================
# Difficulty: rung 28 pre-empts rung 50
# ==========================================================================
def _cap_bound_world():
    world = setup_account_with_catalog(
        "HUB",
        plan_kind="BASIC",
        allow_overage=False,
        name="Cap House",
        email_prefix="cap",
    )
    claim(
        world["household"]["id"], world["catalog"]["id"], "HBX000001", world["owner_headers"]
    )
    return world


def test_serial_prefix_mismatch_is_reported_rather_than_the_entitlement_cap(api):
    """PRD 2.9 rung 28: "The claimed `serial_number` starts with the catalog entry's
    `serial_prefix` — otherwise `ERR_SERIAL_MODEL_MISMATCH` (HTTP 422). Applies to
    device claiming only."
    PRD 2.9: "Rungs are evaluated strictly in ascending priority order; **the first
    rung that fails is the error reported, and no later rung is evaluated**."

    The household is already at its 1-device entitlement with `allow_overage` false,
    so rung 50 would also fail; rung 28 is reported because it sits above it.

    Design: Difficulty/priority_pair_validation_conflict/serial_model_mismatch_preempts_device_cap_exceeded
    """
    world = _cap_bound_world()

    response = api.claim_device(
        claim_device_payload(
            world["household"]["id"], world["catalog"]["id"], "XXX000009", "2026-04-01"
        ),
        world["owner_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_SERIAL_MODEL_MISMATCH.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_DEVICE_CAP_EXCEEDED.value


def test_serial_prefix_mismatch_writes_nothing_to_the_household_counters(api):
    """PRD 2.9 rung 50: "The post-operation `entitled_device_count` does not exceed the
    plan's `included_device_count` unless the subscription's `allow_overage` is true
    — otherwise `ERR_DEVICE_CAP_EXCEEDED`. Applies to device claiming, transfer
    acceptance and add-on order placement."
    PRD 3.3: "a prefix mismatch is `ERR_SERIAL_MODEL_MISMATCH`"

    Design: Difficulty/priority_pair_validation_conflict/serial_model_mismatch_preempts_device_cap_exceeded
    """
    world = _cap_bound_world()

    api.claim_device(
        claim_device_payload(
            world["household"]["id"], world["catalog"]["id"], "XXX000009", "2026-04-01"
        ),
        world["owner_headers"],
    )

    assert fetch_household(world["household"]["id"])["entitled_device_count"] == 1


# ==========================================================================
# Difficulty: rung 30 pre-empts rung 32
# ==========================================================================
def _expired_token_world():
    world = setup_account_with_catalog(
        "HUB", plan_kind="PRO", allow_overage=False, name="Expiry House", email_prefix="exp"
    )
    device = claim(
        world["household"]["id"], world["catalog"]["id"], "HBX000001", world["owner_headers"]
    )
    # activation_expires_at is the claim instant plus 24 hours; move the clock to
    # exactly that instant, which is NOT strictly before it.
    set_clock("2026-05-02T00:00:00Z")
    world["device"] = device
    return world


def test_expired_activation_token_is_reported_rather_than_the_bad_code(api):
    """PRD 2.9 rung 32: "Because this rung sits below rungs 30 and 31, an expired token
    reports expiry rather than a bad code, and a third bad code reports the attempt
    cap rather than a bad code. Applies to device activation."
    PRD 3.3: "If the logical clock is at or after `activation_expires_at`, the attempt
    reports `ERR_ACTIVATION_TOKEN_EXPIRED`"

    Design: Difficulty/priority_pair_validation_conflict/activation_token_expiry_preempts_invalid_activation_code
    """
    world = _expired_token_world()

    response = api.activate_device(
        world["device"]["id"], {"activation_code": "BADCODE1"}, world["owner_headers"]
    )
    error = validate_error(response, ApiErrorId.ERR_ACTIVATION_TOKEN_EXPIRED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ACTIVATION_CODE_INVALID.value


def test_expired_activation_moves_the_row_to_reclaimable_without_counting_an_attempt(api):
    """PRD 3.3: "and the expiry path still moves the row: `lifecycle_status` goes from
    `CLAIMED` to `RECLAIMABLE`, `activation_token` is cleared to null,
    `activation_attempts` is left exactly as it was, and `Device.version` rises by
    one."

    Design: Difficulty/priority_pair_validation_conflict/activation_token_expiry_preempts_invalid_activation_code
    """
    world = _expired_token_world()

    api.activate_device(
        world["device"]["id"], {"activation_code": "BADCODE1"}, world["owner_headers"]
    )

    device = fetch_device(world["device"]["id"])
    assert device["lifecycle_status"] == "RECLAIMABLE"
    assert device["activation_attempts"] == 0
    assert_is_null(device, "activation_token", "Device")
    assert device["version"] == world["device"]["version"] + 1


# ==========================================================================
# Difficulty: the CLAIMED -> RECLAIMABLE -> CLAIMED -> ACTIVE loop
# ==========================================================================
def _three_bad_codes_world():
    world = setup_account_with_catalog(
        "HUB", plan_kind="PRO", allow_overage=False, name="Reclaim House", email_prefix="rec"
    )
    device = claim(
        world["household"]["id"], world["catalog"]["id"], "HBX000001", world["owner_headers"]
    )
    world["device"] = device
    return world


def test_first_two_bad_codes_only_count_while_the_third_moves_the_row(api):
    """PRD 3.3: "Only then is the code itself compared: a `activation_code` that does
    not equal `activation_token` on a first or second failure reports
    `ERR_ACTIVATION_CODE_INVALID`, increments `activation_attempts` by one, leaves
    `lifecycle_status` at `CLAIMED` and bumps `Device.version`."
    PRD 3.3: "A device that already carries 3 recorded failures, or whose third
    failure this call would be, reports `ERR_ACTIVATION_ATTEMPTS_EXCEEDED`; on the
    third-failure path the row moves too, with `activation_attempts` set to 3,
    `lifecycle_status` moved from `CLAIMED` to `RECLAIMABLE`, `activation_token`
    cleared to null and `Device.version` bumped."

    Design: Difficulty/non_linear_state_machine/device_reclaim_loop_returns_row_to_claimed_and_resets_attempts
    """
    world = _three_bad_codes_world()
    device_id = world["device"]["id"]
    owner = world["owner_headers"]

    validate_error(
        api.activate_device(device_id, {"activation_code": "BADCODE1"}, owner),
        ApiErrorId.ERR_ACTIVATION_CODE_INVALID.value,
        422,
    )
    after_first = fetch_device(device_id)
    assert after_first["lifecycle_status"] == "CLAIMED"
    assert after_first["activation_attempts"] == 1

    validate_error(
        api.activate_device(device_id, {"activation_code": "BADCODE2"}, owner),
        ApiErrorId.ERR_ACTIVATION_CODE_INVALID.value,
        422,
    )
    after_second = fetch_device(device_id)
    assert after_second["lifecycle_status"] == "CLAIMED"
    assert after_second["activation_attempts"] == 2

    validate_error(
        api.activate_device(device_id, {"activation_code": "BADCODE3"}, owner),
        ApiErrorId.ERR_ACTIVATION_ATTEMPTS_EXCEEDED.value,
        409,
    )
    after_third = fetch_device(device_id)
    assert after_third["lifecycle_status"] == "RECLAIMABLE"
    assert after_third["activation_attempts"] == 3
    assert_is_null(after_third, "activation_token", "Device")


def test_reclaim_returns_the_row_to_claimed_and_a_fresh_token_activates_it(api):
    """PRD 3.3: "A device stranded in `RECLAIMABLE` is recovered by a `SupportAgent` or
    `PlatformAdmin`: the reclaim operation mints a fresh `activation_token`, sets
    `activation_expires_at` to the current logical-clock instant plus 1440 minutes,
    resets `activation_attempts` to 0 and returns `lifecycle_status` to `CLAIMED`,
    closing the onboarding loop `CLAIMED → RECLAIMABLE → CLAIMED`."
    PRD 3.3: "A correct code succeeds: `lifecycle_status` moves from `CLAIMED` to
    `ACTIVE`, `activated_at` is stamped with the logical-clock instant,
    `firmware_version` is set to the catalog entry's `current_firmware_version`,
    `activation_token` is cleared to null, the household's `active_device_count` is
    recomputed and `Device.version` rises by one."

    Design: Difficulty/non_linear_state_machine/device_reclaim_loop_returns_row_to_claimed_and_resets_attempts
    """
    world = _three_bad_codes_world()
    device_id = world["device"]["id"]
    owner = world["owner_headers"]
    for code in ("BADCODE1", "BADCODE2", "BADCODE3"):
        api.activate_device(device_id, {"activation_code": code}, owner)

    reclaimed = validate_success(api.reclaim_device(device_id, {}, AGENT), 200)
    assert reclaimed["lifecycle_status"] == "CLAIMED"
    assert reclaimed["activation_attempts"] == 0
    assert reclaimed["activation_token"]

    activated = validate_success(
        api.activate_device(
            device_id, {"activation_code": reclaimed["activation_token"]}, owner
        ),
        200,
    )
    assert activated["lifecycle_status"] == "ACTIVE"
    # The firmware axis never moved during the whole lifecycle loop.
    assert activated["firmware_status"] == "CURRENT"
    assert activated["firmware_version"] == "1.0.0"
    assert_is_null(activated, "activation_token", "Device")
