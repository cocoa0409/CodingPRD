"""Standard written orders, the three delivery document rungs and proof of delivery."""

from test_helpers import (
    ApiErrorId,
    approx_mm,
    assert_appliance,
    assert_calendar_date,
    assert_written_order,
    build_scenario,
    create_written_order_payload,
    read_patient_version,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_written_order_supersedes_the_prior_one_for_the_same_item(api):
    """PRD §3.4: "Issuing a written order is guarded against a stale view of the patient, because
    it supersedes its predecessor: any earlier order for the same `patient_id` and the same
    `item_hcpcs` that is still `DRAFT` or `SIGNED` transitions to `SUPERSEDED`, and the patient's
    own `version` rises by 1."
    PRD §3.4: "Creation computes `f2f_age_days` as the whole number of days from
    `f2f_encounter_date` to `order_date`; a negative result means the encounter is dated after
    the order, which is nonsense and is refused with `ERR_VALIDATION`."
    PRD §3.4: "The order begins in `DRAFT`."

    Design: Corner/state_machines/new_written_order_supersedes_the_prior_one_for_the_same_item
    """
    scenario = build_scenario("referral_accepted")
    version = read_patient_version(scenario["pat_id"])
    first = validate_success(
        api.create_written_order(
            create_written_order_payload(scenario["pat_id"], scenario["phys_id"], version),
            scenario["phys_headers"],
        ),
        201,
    )
    validate_success(
        api.sign_written_order(
            first["id"], {"signed_on": "2026-05-11"}, scenario["phys_headers"]
        )
    )

    version_before_second = read_patient_version(scenario["pat_id"])
    second = validate_success(
        api.create_written_order(
            create_written_order_payload(
                scenario["pat_id"], scenario["phys_id"], version_before_second,
                order_date="2026-05-20", f2f_encounter_date="2026-05-01",
            ),
            scenario["phys_headers"],
        ),
        201,
    )
    assert_written_order(second)
    superseded = validate_success(
        api.get_written_order(first["id"], scenario["phys_headers"])
    )
    assert superseded["status"] == "SUPERSEDED"
    assert second["status"] == "DRAFT"
    assert second["f2f_age_days"] == 19
    patient = validate_success(api.get_patient(scenario["pat_id"], scenario["coord_headers"]))
    assert patient["version"] == version_before_second + 1


def test_delivery_against_an_unsigned_written_order_is_refused(api):
    """PRD §2.6 rung 26: "A `SIGNED` `WrittenOrder` exists for this patient whose `item_hcpcs`
    equals the appliance's `hcpcs_code` at delivery, or the claim's `hcpcs_code` at claim
    submission — otherwise `ERR_SWO_MISSING` (422). Applies to appliance delivery, and to claim
    submission for `claim_type` `INITIAL_DEVICE` or `REPLACEMENT`."
    PRD §3.5: "A custom device on a measured range of 8.00 mm therefore starts at 4.75 mm (0.60
    of 8.00 is 4.80; 4.80 divided by 0.25 is 19.2; rounded to 19 grains; 19 times 0.25 is 4.75),
    while a prefabricated device on the identical records starts at 4.00 mm (the smaller of 4.00
    and half of 8.00 is 4.00, which is already 16 whole grains)."

    Design: Corner/validations/delivery_without_a_signed_written_order_is_refused
    """
    scenario = build_scenario("written_order")
    set_clock("2026-06-01T00:00:00Z")
    validate_error(
        api.deliver_appliance(
            scenario["app_id"],
            {"delivered_on": "2026-06-01", "written_order_id": scenario["wo_id"]},
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_SWO_MISSING.value,
    )
    signed = validate_success(
        api.sign_written_order(
            scenario["wo_id"], {"signed_on": "2026-05-11"}, scenario["phys_headers"]
        )
    )
    assert signed["status"] == "SIGNED"

    delivered = validate_success(
        api.deliver_appliance(
            scenario["app_id"],
            {"delivered_on": "2026-06-01", "written_order_id": scenario["wo_id"]},
            scenario["dent_headers"],
        )
    )
    assert delivered["lifecycle_status"] == "DELIVERED"
    assert delivered["starting_advancement_mm"] == approx_mm(4.75)


def test_written_order_dated_after_the_delivery_is_refused(api):
    """PRD §2.6 rung 27: "That order's `order_date` is not later than the appliance's
    `delivered_on` — otherwise `ERR_SWO_AFTER_DELIVERY` (422). Same two endpoints and same claim
    types as rung 26."
    PRD §3.5: "The three checks fire in that order and never collapse into one another — a claim
    whose device was delivered before its order was written is refused for the ordering, not for
    the absence."

    Design: Corner/validations/written_order_dated_after_delivery_is_refused
    """
    scenario = build_scenario(
        "written_order_signed",
        written_order_overrides={
            "order_date": "2026-06-05", "f2f_encounter_date": "2026-05-20",
        },
        signed_on="2026-06-05",
    )
    set_clock("2026-06-05T00:00:00Z")
    error = validate_error(
        api.deliver_appliance(
            scenario["app_id"],
            {"delivered_on": "2026-06-01", "written_order_id": scenario["wo_id"]},
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_SWO_AFTER_DELIVERY.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_SWO_MISSING.value
    order = validate_success(
        api.get_written_order(scenario["wo_id"], scenario["phys_headers"])
    )
    assert order["status"] == "SIGNED"
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["lifecycle_status"] == "FABRICATED"


def test_stale_face_to_face_encounter_is_refused_at_delivery(api):
    """PRD §2.6 rung 28: "That order's `f2f_age_days` is at most 180 — otherwise
    `ERR_F2F_ENCOUNTER_STALE` (422). Same two endpoints and same claim types as rung 26. Rungs
    26, 27 and 28 fire in that order and never collapse into one another."
    PRD §3.5: "and that order's `f2f_age_days` must be at most 180, failing which the answer is
    `ERR_F2F_ENCOUNTER_STALE`. Exactly 180 days old still qualifies."

    Design: Corner/validations/stale_face_to_face_encounter_is_refused
    """
    scenario = build_scenario(
        "written_order_signed",
        written_order_overrides={
            "order_date": "2026-05-10", "f2f_encounter_date": "2025-11-10",
        },
    )
    order = validate_success(
        api.get_written_order(scenario["wo_id"], scenario["phys_headers"])
    )
    assert order["f2f_age_days"] == 181, "2025-11-10 to 2026-05-10 is 181 whole days"

    set_clock("2026-06-01T00:00:00Z")
    validate_error(
        api.deliver_appliance(
            scenario["app_id"],
            {"delivered_on": "2026-06-01", "written_order_id": scenario["wo_id"]},
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_F2F_ENCOUNTER_STALE.value,
    )
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["lifecycle_status"] == "FABRICATED"


def test_delivery_stamps_warranty_and_useful_lifetime_dates(api):
    """PRD §3.5: "A successful delivery moves the device `FABRICATED → DELIVERED`, persists
    `written_order_id` on the appliance, and computes three things. `warranty_end_date` is
    `delivered_on` plus 36 whole months. `useful_lifetime_end_date` is `delivered_on` plus the
    medical payer's `useful_lifetime_months`, 60 months by default."
    PRD §3.5: "`current_advancement_mm` is initialised equal to `starting_advancement_mm`."

    Design: Corner/calculations/delivery_stamps_warranty_and_useful_lifetime_dates
    """
    scenario = build_scenario("written_order_signed")
    set_clock("2026-06-01T00:00:00Z")
    delivered = validate_success(
        api.deliver_appliance(
            scenario["app_id"],
            {"delivered_on": "2026-06-01", "written_order_id": scenario["wo_id"]},
            scenario["dent_headers"],
        )
    )
    assert_appliance(delivered)
    assert_calendar_date(
        delivered["warranty_end_date"], "2029-06-01", "Appliance.warranty_end_date"
    )
    assert_calendar_date(
        delivered["useful_lifetime_end_date"], "2031-06-01",
        "Appliance.useful_lifetime_end_date",
    )
    assert delivered["lifecycle_status"] == "DELIVERED"
    assert delivered["written_order_id"] == scenario["wo_id"]
    assert delivered["current_advancement_mm"] == approx_mm(4.75)


def test_proof_of_delivery_records_without_moving_any_state_axis(api):
    """PRD §3.5: "Proof of delivery is captured separately, by the `Dentist` or the
    `ClinicCoordinator`, while the device is in `DELIVERED`: `pod_signed_on`, the date the
    patient signed, and `pod_method`, either `IN_PERSON` or `SHIPPED`. Capturing it persists both
    fields and moves no state axis at all."

    Design: Corner/endpoints/proof_of_delivery_records_without_moving_the_lifecycle_axis
    """
    scenario = build_scenario("delivered", with_pod=False)
    captured = validate_success(
        api.capture_proof_of_delivery(
            scenario["app_id"],
            {"pod_signed_on": "2026-06-02", "pod_method": "IN_PERSON"},
            scenario["dent_headers"],
        )
    )
    assert_calendar_date(captured["pod_signed_on"], "2026-06-02", "Appliance.pod_signed_on")
    assert captured["lifecycle_status"] == "DELIVERED"
    assert captured["pod_method"] == "IN_PERSON"
    assert captured["current_advancement_mm"] == approx_mm(4.75)
    assert captured["applied_visit_count"] == 0


def test_prefabricated_device_starts_at_four_millimetres(api):
    """PRD §3.5: "For a `PREFABRICATED` device it is the smaller of a fixed 4.00 mm and 0.50 of
    `max_protrusive_mm` — half the measured range."
    PRD §3.5: "Creation copies `patient_id` from the lab order's referral, and `appliance_kind`
    and `max_protrusive_mm` from the lab order itself, and derives `hcpcs_code`: `E0486` for a
    `CUSTOM_FABRICATED` device, `A9270` for a `PREFABRICATED` one."

    Design: Corner/calculations/prefabricated_appliance_starts_at_four_millimetres_and_bills_zero
    """
    scenario = build_scenario(
        "delivered",
        lab_order_overrides={"appliance_kind": "PREFABRICATED"},
        written_order_overrides={"item_hcpcs": "A9270"},
    )
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["appliance_kind"] == "PREFABRICATED"
    assert appliance["hcpcs_code"] == "A9270"
    assert appliance["starting_advancement_mm"] == approx_mm(4.00)

    claim = validate_success(
        api.create_claim(
            {
                "patient_id": scenario["pat_id"],
                "payer_id": scenario["payer_med_id"],
                "appliance_id": scenario["app_id"],
                "claim_type": "INITIAL_DEVICE",
                "hcpcs_code": "A9270",
                "date_of_service": "2026-06-01",
                "billed_cents": 60000,
                "written_order_id": scenario["wo_id"],
            },
            scenario["billing_headers"],
        ),
        201,
    )
    validate_success(api.submit_claim(claim["id"], {}, scenario["billing_headers"]))
    paid = validate_success(
        api.adjudicate_claim(
            claim["id"], {"outcome": "PAID"}, scenario["admin_headers"]
        )
    )
    assert paid["allowed_cents"] == 0
    assert paid["adjustment_cents"] == 60000
    assert paid["patient_responsibility_cents"] == 0
    assert paid["payer_paid_cents"] == 0
    assert paid["status"] == "PAID"


def test_stale_patient_version_blocks_written_order_creation(api):
    """PRD §2.7: "**Creating a `WrittenOrder`** requires `expected_patient_version` carrying the
    client's last observed `version` of the target `Patient`. A mismatch with the patient's
    current `version` is rejected with `ERR_STALE_VERSION` (412). A new standard written order
    for the same `item_hcpcs` supersedes the prior `DRAFT` or `SIGNED` order, so a stale writer
    would invalidate an order that was just issued from a newer clinical picture."

    Design: Corner/cross_cutting_complexity_layers/stale_patient_version_blocks_written_order_creation
    """
    scenario = build_scenario("referral_accepted")
    stale_version = read_patient_version(scenario["pat_id"])
    first = validate_success(
        api.create_written_order(
            create_written_order_payload(
                scenario["pat_id"], scenario["phys_id"], stale_version
            ),
            scenario["phys_headers"],
        ),
        201,
    )
    validate_error(
        api.create_written_order(
            create_written_order_payload(
                scenario["pat_id"], scenario["phys_id"], stale_version,
                order_date="2026-05-12",
            ),
            scenario["phys_headers"],
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )
    untouched = validate_success(
        api.get_written_order(first["id"], scenario["phys_headers"])
    )
    assert untouched["status"] == "DRAFT", "the rejected create must not supersede it"
    rows, meta = validate_paginated(
        api.list_written_orders(
            scenario["phys_headers"], {"patient_id": scenario["pat_id"]}
        )
    )
    assert meta["total_count"] == 1 and len(rows) == 1
