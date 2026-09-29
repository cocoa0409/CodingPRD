"""Cross-cutting layers: optimistic concurrency, thresholds, censuses and long chains.

These cases pin the mechanisms that cut across entities — the three version tokens, the
posture waterfall, the special-diet census and the two damages variants — by running
them end to end rather than one field at a time. The last case covers the domain's
read-after-write model: there is no eventual-consistency window, so a counter a child
write moves on its parent is already settled when the child's response returns.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, ApiErrorId, assertions, factories, fixtures
from test_helpers import test_users as users


def test_a_housing_move_invalidates_a_diet_order_token_that_still_looks_valid(
    api: ApiClient,
) -> None:
    """The interleaved movement changes nothing a diet order would check except the
    inmate's version, so only the token catches the stale create.

    The PRD states: "Creating a diet order requires `expected_inmate_version`, carrying the
    client's last observed `version` of the inmate named by `inmate_id`. If that value does
    not equal the inmate's current `version`, the create is rejected with
    `ERR_STALE_INMATE_VERSION` and HTTP 412." It also states: "The create also increments
    the named inmate's `version` by 1, because the inmate's diet picture has changed even
    though `active_diet_order_count` does not move until verification."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_diet_order_create_rejects_stale_inmate_version
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-C01")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-C01", sharps_authorized_count=12
    )
    inmate = fixtures.create_inmate(api, facility["id"], booking_number="BK-C01")
    stale_version = inmate["version"]
    assert stale_version == 1
    assert inmate["status"] == "IN_CUSTODY"

    moved = validate_success(
        api.record_inmate_movement(
            inmate["id"],
            factories.movement_payload("HOUSING_CHANGE", housing_unit="MEDICAL"),
            users.OFFICER,
        )
    )
    assert moved["version"] == 2
    assert moved["status"] == "IN_CUSTODY"
    assert moved["housing_unit"] == "MEDICAL"

    validate_error(
        api.create_diet_order(
            factories.medical_diet_order_payload(inmate["id"], stale_version),
            users.DIETITIAN,
        ),
        ApiErrorId.ERR_STALE_INMATE_VERSION.value,
        412,
    )
    _, meta = validate_paginated(
        api.list_diet_orders(users.DIETITIAN, params={"inmate_id": inmate["id"]})
    )
    assert meta["total_count"] == 0

    order = validate_success(
        api.create_diet_order(
            factories.medical_diet_order_payload(inmate["id"], moved["version"]),
            users.DIETITIAN,
        ),
        201,
    )
    assert order["status"] == "PENDING_VERIFICATION"

    after = validate_success(api.get_inmate(inmate["id"], users.OFFICER))
    # The accepted create advanced the inmate again, so replaying the fresh token
    # would now fail too.
    assert after["version"] == 3
    assert after["active_diet_order_count"] == 0


def test_a_clean_sharps_audit_invalidates_a_batch_token_without_changing_the_posture(
    api: ApiClient,
) -> None:
    """The interleaved audit leaves the posture OPEN and the shortfall at zero, yet the
    batch create built on the pre-audit facility version is refused.

    The PRD states: "Creating a production batch requires `expected_facility_version`,
    carrying the client's last observed `version` of the facility named by `facility_id`. A
    mismatch against the facility's current `version` is rejected with
    `ERR_STALE_FACILITY_VERSION` and HTTP 412. A sharps audit that finds no shortfall
    advances the facility's `version` and rewrites `sharps_on_board_count` while leaving
    `kitchen_posture` at `OPEN`, so a batch create issued strictly after that audit completes
    sees an identical posture and would otherwise be accepted against a stale view of chiller
    occupancy and sharps."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_batch_create_rejects_stale_facility_version
    """
    ctx = fixtures.locked_forecast(
        api,
        contract_overrides={"contract_code": "CFS-2515-C02"},
        facility_overrides={
            "facility_code": "FAC-C02",
            "sharps_authorized_count": 12,
        },
    )
    facility_id = ctx["facility"]["id"]
    stale_version = ctx["facility"]["version"]
    assert stale_version == 1

    audited = validate_success(
        api.sharps_audit(
            facility_id, factories.sharps_audit_payload(12), users.OFFICER
        )
    )
    assert audited["version"] == 2
    assert audited["kitchen_posture"] == "OPEN"
    assert audited["sharps_audit_shortfall"] == 0
    assert audited["sharps_on_board_count"] == 12

    payload = factories.production_batch_payload(
        facility_id, ctx["forecast"]["id"], stale_version
    )
    validate_error(
        api.create_production_batch(payload, users.FOOD_SUPERVISOR),
        ApiErrorId.ERR_STALE_FACILITY_VERSION.value,
        412,
    )
    _, meta = validate_paginated(
        api.list_facility_production_batches(facility_id, users.FOOD_SUPERVISOR)
    )
    assert meta["total_count"] == 0

    batch = validate_success(
        api.create_production_batch(
            factories.production_batch_payload(
                facility_id, ctx["forecast"]["id"], audited["version"]
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert batch["production_stage"] == "PLANNED"
    assert batch["qa_status"] == "QA_PENDING"
    assert batch["version"] == 1
    # Creating a batch "increments the facility's `version` by 1, because the
    # facility's chiller occupancy has changed" (PRD §3.5).
    assert fixtures.read_facility(api, facility_id)["version"] == 3


def test_two_sibling_records_cannot_post_onto_the_same_ledger_snapshot(
    api: ApiClient,
) -> None:
    """Closing the breakfast record advances the contract, so the lunch close held on the
    pre-read token is refused; on the retry each close has posted exactly once.

    The PRD states: "Closing a meal service record requires
    `expected_service_contract_version`, carrying the client's last observed `version` of the
    service contract that owns the record's facility. A mismatch against that contract's
    current `version` is rejected with `ERR_STALE_CONTRACT_VERSION` and HTTP 412. Closing a
    different service record ... advance[s] the contract's `version` and mutate[s]
    `missed_meal_total` without changing the contract's `status`, so a close issued strictly
    afterwards would see the same contract status and post its damages delta onto a stale
    ledger snapshot."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_service_record_close_rejects_stale_contract_version
    """
    ctx = fixtures.locked_forecast(
        api,
        contract_overrides={"contract_code": "CFS-2515-C03"},
        facility_overrides={
            "facility_code": "FAC-C03",
            "sharps_authorized_count": 12,
        },
        forecast_overrides={"meal_slot": "BREAKFAST"},
    )
    facility_id = ctx["facility"]["id"]
    contract_id = ctx["contract"]["id"]

    lunch_forecast = validate_success(
        api.create_meal_forecast(
            factories.meal_forecast_payload(
                facility_id,
                ctx["population_count"]["id"],
                service_date=ctx["forecast"]["service_date"],
                meal_slot="LUNCH",
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    lunch_forecast = validate_success(
        api.lock_meal_forecast(lunch_forecast["id"], users.FOOD_SUPERVISOR)
    )
    assert lunch_forecast["status"] == "LOCKED"

    breakfast_record = fixtures.open_service_record(api, ctx)["record"]
    lunch_record = fixtures.open_service_record(
        api, dict(ctx, forecast=lunch_forecast)
    )["record"]
    assert breakfast_record["expected_service_trays"] == 14
    assert lunch_record["expected_service_trays"] == 14

    stale_contract_version = fixtures.read_contract(api, contract_id)["version"]
    closed_breakfast = validate_success(
        api.close_meal_service_record(
            breakfast_record["id"],
            factories.close_service_record_payload(stale_contract_version),
            users.FOOD_SUPERVISOR,
        )
    )
    assert closed_breakfast["status"] == "CLOSED"
    # 13 served against 14 expected, with a tolerance of floor(14 * 0.02) == 0.
    assert closed_breakfast["missed_meal_count"] == 1

    mid = fixtures.read_contract(api, contract_id)
    assert mid["version"] == stale_contract_version + 1
    assert mid["status"] == "ACTIVE"
    assert mid["missed_meal_total"] == 1

    validate_error(
        api.close_meal_service_record(
            lunch_record["id"],
            factories.close_service_record_payload(stale_contract_version),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_STALE_CONTRACT_VERSION.value,
        412,
    )
    assert fixtures.read_service_record(api, lunch_record["id"])["status"] == "OPEN"

    closed_lunch = validate_success(
        api.close_meal_service_record(
            lunch_record["id"],
            factories.close_service_record_payload(mid["version"]),
            users.FOOD_SUPERVISOR,
        )
    )
    assert closed_lunch["status"] == "CLOSED"
    assert closed_lunch["missed_meal_count"] == 1

    summary = validate_success(
        api.get_performance_summary(contract_id, users.AUDITOR)
    )
    # Each close posted exactly once: no double count and no lost delta.
    assert summary["total_trays_served"] == 26
    assert summary["missed_meal_total"] == 2


def test_the_second_open_incident_flips_the_posture_and_the_first_disposition_releases_it(
    api: ApiClient,
) -> None:
    """One open incident leaves the kitchen open; the second restricts it and blocks the
    assignment; clearing one incident releases the posture with no explicit release call.

    The PRD states clause 4 of the waterfall: "Otherwise, if
    `open_contraband_incident_count` is at least 2, the posture is `RESTRICTED`", and that
    posture "is recomputed from scratch, not incrementally adjusted ... Because it is
    recomputed from scratch, clearing the last remaining cause returns a facility to `OPEN`
    with no explicit release operation." The gate itself: "Three operations put food or
    people into the kitchen and are therefore gated on posture: scheduling a production
    batch, assigning a kitchen worker to a work area, and signing a tool out of the shadow
    board."

    Design: Corner/cross_cutting_complexity_layers/corner_contraband_threshold_flips_posture_at_two
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-C04")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-C04", sharps_authorized_count=12
    )
    facility_id = facility["id"]
    assert facility["kitchen_posture"] == "OPEN"
    assert facility["open_contraband_incident_count"] == 0

    worker = fixtures.enrolled_worker(
        api, facility_id, booking_number="BK-C04", sharps_eligible=True
    )["worker"]
    assert worker["assignment_status"] == "UNASSIGNED"

    validate_success(
        api.create_contraband_incident(
            factories.contraband_incident_payload(
                facility_id,
                item_class="YEAST_ALCOHOL",
                severity="MINOR",
                narrative="Sugar packets hoarded in a mop sink.",
            ),
            users.OFFICER,
        ),
        201,
    )
    at_one = fixtures.read_facility(api, facility_id)
    # At the threshold minus one, nothing changes.
    assert at_one["open_contraband_incident_count"] == 1
    assert at_one["kitchen_posture"] == "OPEN"

    second = validate_success(
        api.create_contraband_incident(
            factories.contraband_incident_payload(
                facility_id,
                item_class="SHARP",
                severity="MINOR",
                narrative="Sharpened plastic shard on the tray line.",
            ),
            users.OFFICER,
        ),
        201,
    )
    at_two = fixtures.read_facility(api, facility_id)
    assert at_two["open_contraband_incident_count"] == 2
    assert at_two["kitchen_posture"] == "RESTRICTED"

    validate_error(
        api.assign_inmate_worker(
            worker["id"],
            factories.assign_payload("SERVING_LINE"),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_KITCHEN_POSTURE_BLOCKED.value,
        409,
    )
    assert fixtures.read_worker(api, worker["id"])["assignment_status"] == "UNASSIGNED"

    cleared = validate_success(
        api.disposition_contraband_incident(
            second["id"], factories.disposition_payload("CLEARED"), users.OFFICER_2
        )
    )
    assert cleared["status"] == "CLEARED"
    # Only a SANCTIONED disposition cascades onto the worker.
    still_clear = fixtures.read_worker(api, worker["id"])
    assert still_clear["clearance_status"] == "CLEARED"
    assert still_clear["contraband_strike_count"] == 0

    released = fixtures.read_facility(api, facility_id)
    assert released["open_contraband_incident_count"] == 1
    assert released["kitchen_posture"] == "OPEN"

    assigned = validate_success(
        api.assign_inmate_worker(
            worker["id"],
            factories.assign_payload("SERVING_LINE"),
            users.FOOD_SUPERVISOR,
        )
    )
    assert assigned["assignment_status"] == "ASSIGNED"
    assert assigned["work_area"] == "SERVING_LINE"


def test_the_special_diet_census_follows_one_order_around_its_whole_life(
    api: ApiClient,
) -> None:
    """The census rises on verification, falls on suspension, comes back to exactly one
    after a reverification round trip and falls to zero on revocation.

    The PRD states: "`Facility.active_special_diet_count` is the number of `ACTIVE` diet
    orders whose inmate sits at that facility *and* is still `IN_CUSTODY`. Orders in
    `PENDING_VERIFICATION`, `SUSPENDED`, `EXPIRED` or `REVOKED` are excluded from both." It
    also requires reconciliation rather than blind adjustment: derived counters "must always
    agree with a count over their source rows after the operation completes".

    Design: Corner/cross_cutting_complexity_layers/corner_special_diet_census_tracks_every_source_change
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-C05")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-C05", sharps_authorized_count=12
    )
    facility_id = facility["id"]
    assert facility["active_special_diet_count"] == 0

    inmate = fixtures.create_inmate(api, facility_id, booking_number="BK-C05")
    order = validate_success(
        api.create_diet_order(
            factories.medical_diet_order_payload(inmate["id"], inmate["version"]),
            users.DIETITIAN,
        ),
        201,
    )
    assert order["status"] == "PENDING_VERIFICATION"
    assert fixtures.read_facility(api, facility_id)["active_special_diet_count"] == 0

    verified = validate_success(
        api.verify_diet_order(
            order["id"], users.MEDICAL, {"verification_note": "Chart reviewed."}
        )
    )
    assert verified["status"] == "ACTIVE"
    assert fixtures.read_facility(api, facility_id)["active_special_diet_count"] == 1

    suspended = validate_success(
        api.suspend_diet_order(
            order["id"],
            {"suspension_reason": "Tray refused three services running."},
            users.FOOD_SUPERVISOR,
        )
    )
    assert suspended["status"] == "SUSPENDED"
    assert fixtures.read_facility(api, facility_id)["active_special_diet_count"] == 0

    requeued = validate_success(
        api.request_reverification(order["id"], users.DIETITIAN)
    )
    assert requeued["status"] == "PENDING_VERIFICATION"
    assert requeued["reverification_count"] == 1
    assert fixtures.read_facility(api, facility_id)["active_special_diet_count"] == 0

    reactivated = validate_success(
        api.verify_diet_order(
            order["id"], users.MEDICAL_2, {"verification_note": "Chart re-reviewed."}
        )
    )
    assert reactivated["status"] == "ACTIVE"
    # Exactly 1, never 2: the census is a count over source rows.
    assert fixtures.read_facility(api, facility_id)["active_special_diet_count"] == 1

    revoked = validate_success(
        api.revoke_diet_order(
            order["id"],
            {"revocation_reason": "Renal indication resolved."},
            users.DIETITIAN,
        )
    )
    assert revoked["status"] == "REVOKED"
    assert fixtures.read_facility(api, facility_id)["active_special_diet_count"] == 0
    assert (
        validate_success(api.get_inmate(inmate["id"], users.DIETITIAN))[
            "active_diet_order_count"
        ]
        == 0
    )


def test_the_parents_sharps_counters_are_settled_when_the_child_write_returns(
    api: ApiClient,
) -> None:
    """A read issued straight after the issuance reports the moved counters, the balanced
    accountability identity and the parent's advanced version, with no lag.

    The PRD states: "For a sharp class it increments the facility's `sharps_issued_count` and
    decrements `sharps_on_board_count`; it then recomputes `kitchen_posture` and increments
    the facility's `version` by 1." It fixes the identity that "must hold at every instant:
    for each facility, `sharps_on_board_count` plus `sharps_issued_count` plus
    `sharps_unaccounted_count` equals `sharps_authorized_count`", where
    "`sharps_on_board_count` is maintained as the residual: it starts equal to
    `sharps_authorized_count` when the facility is registered, falls by 1 on each issue".

    Design: Corner/consistency_model/corner_write_response_and_immediate_read_agree
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-M01")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-M01", sharps_authorized_count=12
    )
    facility_id = facility["id"]
    assert facility["sharps_on_board_count"] == 12
    assert facility["version"] == 1

    worker = fixtures.enrolled_worker(
        api, facility_id, booking_number="BK-M01", sharps_eligible=True
    )["worker"]
    assigned = validate_success(
        api.assign_inmate_worker(
            worker["id"], factories.assign_payload("COOK_CHILL"), users.FOOD_SUPERVISOR
        )
    )
    assert assigned["assignment_status"] == "ASSIGNED"

    issuance = validate_success(
        api.create_tool_issuance(
            factories.tool_issuance_payload(
                facility_id,
                worker["id"],
                tool_class="MEAT_SAW",
                tool_serial="MS-M01-1",
                shadow_board_slot=4,
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert issuance["status"] == "ISSUED"
    assert issuance["issued_by_user_id"] == users.user_id_of(users.FOOD_SUPERVISOR)
    assertions.assert_instant(issuance["issued_at"], "2026-08-01T00:00:00Z")
    assert issuance["recovered"] is False

    summary = validate_success(api.get_sharps_summary(facility_id, users.OFFICER))
    # Read at the same logical instant as the write: no re-read delay.
    assert summary["sharps_on_board_count"] == 11
    assert summary["sharps_issued_count"] == 1
    assert summary["sharps_unaccounted_count"] == 0
    assert summary["sharps_authorized_count"] == 12
    assertions.assert_sharps_summary_conservation(summary)
    assert summary["kitchen_posture"] == "OPEN"

    # The parent's derived posture and version were settled inside the child's write.
    parent = validate_success(api.get_facility(facility_id, users.CONTRACT_ADMIN))
    assert parent["version"] == 2
    assert parent["sharps_on_board_count"] == 11
    assert parent["sharps_issued_count"] == 1
    assert parent["kitchen_posture"] == "OPEN"
