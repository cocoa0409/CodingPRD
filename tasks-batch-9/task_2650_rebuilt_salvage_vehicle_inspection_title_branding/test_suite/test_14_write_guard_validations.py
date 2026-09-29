"""Write guards that refuse a request outright.

Natural-key uniqueness, rebuilder ownership, the submission and slot windows,
flood-capable stations, one live application per vehicle, conveyance dating,
VIN-plate identity, brand monotonicity across jurisdictions, escrow funding,
the record-keeping gate on reinstatement and the photographic minimum.
"""

import pytest

from test_helpers import (
    ADMIN_USER_ID,
    CLOCK_EPOCH,
    SECOND_ADMIN_USER_ID,
    TEST_USERS,
    api_client,
    checkpoint_results,
    complete_inspection_payload,
    create_application_payload,
    create_license_action_payload,
    create_title_transfer_payload,
    create_vehicle_payload,
    decide_recognition_request_payload,
    file_parts_document,
    license_rebuilder,
    make_inspector_headers,
    make_program_admin_headers,
    make_rebuilder_headers,
    read_application,
    read_damage_report,
    read_fee_quote,
    read_inspection,
    read_inspector,
    read_rebuilder,
    read_recognition_request,
    read_station,
    read_title,
    read_vehicle,
    register_vehicle,
    schedule_inspection_payload,
    set_clock,
    setup_docs_accepted_application,
    setup_draft_application,
    setup_inspection_in_progress,
    setup_salvage_titled_vehicle,
    setup_submission_ready_application,
    submit_application_payload,
    submit_recognition_request,
    take_license_action,
    validate_error,
    validate_paginated,
    validate_success,
    verify_parts_document,
)

ADMIN_HEADERS = TEST_USERS["program_admin_headers"]
CLERK_HEADERS = TEST_USERS["state_title_clerk_headers"]

DUPLICATE_VIN = "1HGCM82633A007301"


def test_second_vehicle_with_the_same_vin_is_refused():
    """A VIN already stamped on a registered car cannot be registered twice.

    PRD: "Attempting to register a vehicle whose `vin` already exists, license a rebuilder whose `license_number` already exists, commission an inspector whose `badge_number` already exists, open a station whose `station_code` already exists, or file a damage report whose `insurer_name` and `claim_number` pair already exists, is rejected with `ERR_DUPLICATE_NATURAL_KEY`."

    Design: Corner/validations/duplicate_vin_on_a_second_vehicle_create_is_rejected
    """
    first = register_vehicle(
        vin=DUPLICATE_VIN, model_year=2019, make="Honda", model="Accord", body_class="SEDAN"
    )

    response = api_client.create_vehicle(
        create_vehicle_payload(
            vin=DUPLICATE_VIN,
            model_year=2021,
            make="Toyota",
            model="Camry",
            body_class="SEDAN",
            registered_state_code="AZ",
        ),
        CLERK_HEADERS,
    )
    validate_error(response, "ERR_DUPLICATE_NATURAL_KEY")

    unchanged = read_vehicle(first["id"])
    assert unchanged["make"] == "Honda", (
        f"the first registration must be untouched, expected Honda, got {unchanged['make']}"
    )
    assert unchanged["model_year"] == 2019, (
        f"expected model_year 2019, got {unchanged['model_year']} after the refused create"
    )
    assert unchanged["vin"] == DUPLICATE_VIN, (
        f"expected vin {DUPLICATE_VIN}, got {unchanged['vin']}"
    )


def test_rebuilder_cannot_open_an_application_naming_another_rebuilder():
    """A rebuilder may not file an application in a competitor's name.

    PRD: "When `X-User-Role` is `Rebuilder`, `X-User-ID` is the `id` of the acting `Rebuilder` row; ownership checks on any resource that references a `Rebuilder` compare the resource's foreign-key field to `X-User-ID` — concretely, the target `RebuiltApplication`'s `rebuilder_id` (or, when the application is being created, the `rebuilder_id` carried in the request body) must equal `X-User-ID`."

    Design: Corner/validations/rebuilder_cannot_open_an_application_naming_another_rebuilder
    """
    env = setup_salvage_titled_vehicle()
    named_rebuilder = license_rebuilder(legal_name="Sierra Rebuilders LLC")
    acting_rebuilder = license_rebuilder(legal_name="Basin Body Works LLC")

    response = api_client.create_application(
        create_application_payload(
            env["vehicle_id"],
            named_rebuilder["id"],
            env["salvage_title_id"],
            declared_repair_cost_cents=800_000,
        ),
        make_rebuilder_headers(acting_rebuilder["id"]),
    )
    validate_error(response, "ERR_NOT_RESOURCE_OWNER")

    rows, meta = validate_paginated(
        api_client.list_applications(ADMIN_HEADERS, {"vehicle_id": env["vehicle_id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected no application on the vehicle, got {meta['total_count']}"
    )
    assert rows == [], f"expected no application rows, got {len(rows)}"

    vehicle = read_vehicle(env["vehicle_id"])
    assert vehicle["open_application_count"] == 0, (
        f"expected 0, got {vehicle['open_application_count']} after the refused create"
    )


def test_submitting_after_the_one_hundred_eighty_day_window_is_refused():
    """A rebuilder who lets the statutory window lapse cannot submit at all.

    PRD: "The logical clock must be no later than the salvage title's `issued_at` plus 180 days; a rebuilder who has not submitted by the end of that 180-day window loses it and is refused with `ERR_SUBMISSION_WINDOW_EXPIRED` (HTTP 422)."

    Design: Corner/validations/submitting_after_the_one_hundred_eighty_day_window_is_rejected
    """
    env = setup_submission_ready_application(body_class="TRAILER", deposit_cents=500_000)
    salvage_title = read_title(env["salvage_title_id"])
    assert salvage_title["issued_at"].startswith("2026-08-01T00:00:00"), (
        f"setup expected issuance at the clock epoch, got {salvage_title['issued_at']}"
    )

    set_clock("2027-02-01T00:00:00Z")

    response = api_client.submit_application(
        env["application_id"],
        submit_application_payload(),
        make_rebuilder_headers(env["rebuilder_id"]),
    )
    validate_error(response, "ERR_SUBMISSION_WINDOW_EXPIRED")

    application = read_application(env["application_id"])
    assert application["status"] == "DRAFT", (
        f"expected DRAFT, got {application['status']} after the refused submission"
    )
    assert application["fee_escrowed_cents"] == 0, (
        f"expected 0, got {application['fee_escrowed_cents']} — nothing may be escrowed"
    )

    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["fee_balance_cents"] == 500_000, (
        f"expected the deposit intact at 500000, got {rebuilder['fee_balance_cents']}"
    )
    assert rebuilder["escrowed_fee_total_cents"] == 0, (
        f"expected 0, got {rebuilder['escrowed_fee_total_cents']} after the refused submission"
    )


def test_scheduling_a_slot_at_the_current_clock_is_refused():
    """A bay booked for the very instant it is booked is not a future slot.

    PRD: "`scheduled_end_at` must be strictly after `scheduled_start_at`, and `scheduled_start_at` must be strictly after the logical clock — a slot at or before the current instant is refused with `ERR_INSPECTION_SLOT_IN_PAST` (HTTP 422)."

    Design: Corner/validations/scheduling_a_slot_at_the_current_clock_is_rejected_as_in_the_past
    """
    env = setup_docs_accepted_application(body_class="TRAILER", deposit_cents=500_000)

    response = api_client.schedule_inspection(
        env["application_id"],
        schedule_inspection_payload(
            env["inspector_id"],
            env["station_id"],
            env["app_version"],
            scheduled_start_at=CLOCK_EPOCH,
            scheduled_end_at="2026-08-01T02:00:00Z",
        ),
        CLERK_HEADERS,
    )
    validate_error(response, "ERR_INSPECTION_SLOT_IN_PAST")

    rows, meta = validate_paginated(
        api_client.list_inspections(ADMIN_HEADERS, {"application_id": env["application_id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected no attempt booked, got {meta['total_count']}"
    )
    assert rows == [], f"expected no attempt rows, got {len(rows)}"

    application = read_application(env["application_id"])
    assert application["status"] == "DOCS_ACCEPTED", (
        f"expected DOCS_ACCEPTED, got {application['status']} after the refused booking"
    )

    inspector = read_inspector(env["inspector_id"])
    assert inspector["scheduled_inspection_count"] == 0, (
        f"expected 0, got {inspector['scheduled_inspection_count']} — no interval may be held"
    )
    station = read_station(env["station_id"])
    assert station["scheduled_occupancy_count"] == 0, (
        f"expected 0, got {station['scheduled_occupancy_count']} — no bay may be held"
    )


def test_flood_branded_vehicle_cannot_be_booked_at_a_dry_station():
    """A flood-branded car needs a station equipped to inspect water damage.

    PRD: "When the inspected vehicle's `active_brand_code` is `FLOOD`, the nominated station's `supports_flood` must be true *and* the nominated inspector's `certifications` must contain `STRUCTURAL`; a violation of either half is refused with `ERR_STATION_NOT_FLOOD_CAPABLE` (HTTP 409)."

    Design: Corner/validations/flood_branded_vehicle_at_a_non_flood_capable_station_is_rejected
    """
    env = setup_docs_accepted_application(
        body_class="TRAILER",
        deposit_cents=500_000,
        report_overrides={
            "damage_type": "FLOOD",
            "flood_water_depth_cm": 60,
            "repair_estimate_cents": 200_000,
        },
        station_overrides={"supports_flood": False},
    )

    report = read_damage_report(env["damage_report_id"])
    assert report["recommended_brand_code"] == "FLOOD", (
        f"60 cm of standing water brands FLOOD, got {report['recommended_brand_code']}"
    )
    vehicle = read_vehicle(env["vehicle_id"])
    assert vehicle["active_brand_code"] == "FLOOD", (
        f"expected FLOOD on the vehicle, got {vehicle['active_brand_code']}"
    )
    assert read_station(env["station_id"])["supports_flood"] is False, (
        "setup expected a station with no flood capability"
    )

    response = api_client.schedule_inspection(
        env["application_id"],
        schedule_inspection_payload(
            env["inspector_id"],
            env["station_id"],
            env["app_version"],
            scheduled_start_at="2026-08-10T09:00:00Z",
            scheduled_end_at="2026-08-10T11:00:00Z",
        ),
        CLERK_HEADERS,
    )
    validate_error(response, "ERR_STATION_NOT_FLOOD_CAPABLE")

    _, meta = validate_paginated(
        api_client.list_inspections(ADMIN_HEADERS, {"application_id": env["application_id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected no attempt booked at the dry station, got {meta['total_count']}"
    )
    assert read_station(env["station_id"])["scheduled_occupancy_count"] == 0, (
        "the refused booking may not occupy a bay"
    )
    assert read_application(env["application_id"])["status"] == "DOCS_ACCEPTED", (
        "the application must still be awaiting a slot"
    )


def test_second_application_on_the_same_vehicle_is_refused():
    """One wreck may only carry one live conversion application.

    PRD: "Finally the vehicle's `open_application_count` must be 0 — a vehicle may have at most one live application at a time, and a second one is refused with `ERR_DUPLICATE_ACTIVE_APPLICATION` (HTTP 409)."

    Design: Corner/validations/second_application_for_the_same_vehicle_is_rejected_as_duplicate
    """
    env = setup_draft_application(body_class="TRAILER")
    assert read_vehicle(env["vehicle_id"])["open_application_count"] == 1, (
        "setup expected exactly one live application on the vehicle"
    )

    response = api_client.create_application(
        create_application_payload(
            env["vehicle_id"],
            env["rebuilder_id"],
            env["salvage_title_id"],
            declared_repair_cost_cents=290_000,
        ),
        make_rebuilder_headers(env["rebuilder_id"]),
    )
    validate_error(response, "ERR_DUPLICATE_ACTIVE_APPLICATION")

    rows, meta = validate_paginated(
        api_client.list_applications(ADMIN_HEADERS, {"vehicle_id": env["vehicle_id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected the one original application, got {meta['total_count']}"
    )
    assert rows[0]["id"] == env["application_id"], (
        f"expected {env['application_id']}, got {rows[0]['id']}"
    )

    vehicle = read_vehicle(env["vehicle_id"])
    assert vehicle["open_application_count"] == 1, (
        f"expected 1, got {vehicle['open_application_count']} after the refused create"
    )

    original = read_application(env["application_id"])
    assert original["declared_repair_cost_cents"] == 320_000, (
        "the refused create may not overwrite the original declaration, expected 320000, got "
        f"{original['declared_repair_cost_cents']}"
    )


def test_conveyance_dated_before_the_title_was_issued_is_refused():
    """A sale cannot take effect before the certificate being sold existed.

    PRD: "And `transfer_effective_at` must be at or after the outgoing title's `issued_at`, and may not predate the latest already-recorded conveyance on the chain; an earlier instant is refused with `ERR_TRANSFER_PREDATES_TITLE` (HTTP 422)."

    Design: Corner/validations/transfer_effective_before_the_title_issue_date_is_rejected
    """
    env = setup_salvage_titled_vehicle()
    assert env["salvage_title"]["issued_at"].startswith("2026-08-01T00:00:00"), (
        f"setup expected issuance at the clock epoch, got {env['salvage_title']['issued_at']}"
    )

    response = api_client.create_title_transfer(
        create_title_transfer_payload(
            env["salvage_title_id"],
            buyer_name="Marisol Vance",
            transfer_effective_at="2026-07-01T00:00:00Z",
            odometer_reading_miles=64_500,
        ),
        CLERK_HEADERS,
    )
    validate_error(response, "ERR_TRANSFER_PREDATES_TITLE")

    _, meta = validate_paginated(
        api_client.list_title_transfers(ADMIN_HEADERS, {"from_title_id": env["salvage_title_id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected no conveyance recorded, got {meta['total_count']}"
    )

    title = read_title(env["salvage_title_id"])
    assert title["status"] == "ACTIVE", (
        f"expected ACTIVE, got {title['status']} — nothing may supersede the title"
    )
    assert title["is_current"] is True, (
        f"expected is_current true, got {title['is_current']} after the refused conveyance"
    )
    assert title["transfer_sequence"] == 0, (
        f"expected the chain still one row long, got transfer_sequence {title['transfer_sequence']}"
    )


def test_completion_reading_a_different_vin_plate_is_refused():
    """An inspector whose plate reading disagrees with the record cannot close the attempt.

    PRD: "A completion whose `vin_plate_reading` differs from the vehicle's `vin` is refused with `ERR_VIN_MISMATCH` (HTTP 422) unless a finding with `category` of `VIN_ALTERATION` already stands on this attempt — in that case the mismatch is the documented defect the inspector came to record, and the completion is allowed to proceed to a `FAIL`."

    Design: Corner/validations/vin_plate_mismatch_at_completion_is_rejected
    """
    env = setup_inspection_in_progress(body_class="TRAILER", deposit_cents=500_000)
    recorded_vin = env["vin"]
    misread_vin = recorded_vin[:-1] + ("7" if recorded_vin[-1] != "7" else "8")
    assert misread_vin != recorded_vin, "the test needs a reading that differs from the record"
    assert len(misread_vin) == 17, f"a VIN is 17 characters, got {len(misread_vin)}"

    response = api_client.complete_inspection(
        env["inspection_id"],
        complete_inspection_payload(misread_vin, results=checkpoint_results()),
        make_inspector_headers(env["inspector_id"]),
    )
    validate_error(response, "ERR_VIN_MISMATCH")

    inspection = read_inspection(env["inspection_id"])
    assert inspection["status"] == "IN_PROGRESS", (
        f"expected IN_PROGRESS, got {inspection['status']} after the refused completion"
    )
    assert inspection["result"] is None, (
        f"expected no adjudicated result, got {inspection['result']}"
    )

    application = read_application(env["application_id"])
    assert application["attempts_completed"] == 0, (
        f"expected 0, got {application['attempts_completed']} — the attempt never closed"
    )
    assert read_vehicle(env["vehicle_id"])["vin"] == recorded_vin, (
        "the vehicle's recorded VIN must be untouched by the refused reading"
    )


def test_recognition_may_not_map_a_brand_onto_a_harsher_one():
    """A foreign state may soften a brand but never harden it.

    PRD: "Across jurisdictions, severity never hardens: a foreign state asked to recognise a brand may carry it as-is, downgrade it to a strictly less severe brand, or refuse to carry any brand at all, but it may never map it to a strictly more severe brand — that attempt is also refused with `ERR_BRAND_ESCALATION_FORBIDDEN` (HTTP 422)."

    Design: Corner/validations/interstate_recognition_downgrade_is_accepted_but_escalation_is_rejected
    """
    env = setup_salvage_titled_vehicle()
    title = read_title(env["salvage_title_id"])
    request = submit_recognition_request(
        env["salvage_title_id"], title["version"], requesting_state_code="AZ"
    )
    assert request["submitted_brand_code"] == "SALVAGE", (
        f"expected the SALVAGE snapshot, got {request['submitted_brand_code']}"
    )

    response = api_client.decide_recognition_request(
        request["id"],
        decide_recognition_request_payload(mapped_brand_code="NON_REPAIRABLE"),
        ADMIN_HEADERS,
    )
    validate_error(response, "ERR_BRAND_ESCALATION_FORBIDDEN")

    unchanged = read_recognition_request(request["id"])
    assert unchanged["status"] == "PENDING", (
        f"expected PENDING, got {unchanged['status']} after the refused decision"
    )
    assert unchanged["mapped_brand_code"] is None, (
        f"expected no mapped brand, got {unchanged['mapped_brand_code']}"
    )
    assert unchanged["outcome"] is None, (
        f"expected no outcome, got {unchanged['outcome']}"
    )
    assert unchanged["decided_at"] is None, (
        f"expected no decision instant, got {unchanged['decided_at']}"
    )

    still_salvage = read_title(env["salvage_title_id"])
    assert still_salvage["brand_code"] == "SALVAGE", (
        f"expected SALVAGE, got {still_salvage['brand_code']} on the offered title"
    )
    assert still_salvage["recognition_state"] == "RECOGNITION_PENDING", (
        f"expected RECOGNITION_PENDING, got {still_salvage['recognition_state']}"
    )


def test_recognition_refusing_to_carry_any_brand_is_accepted():
    """A state that declines to carry the brand at all still yields a decision.

    PRD: "The `outcome` follows mechanically from the comparison: it is `RECOGNIZED` when `mapped_brand_code` equals `submitted_brand_code`; it is `DOWNGRADED` when the mapped brand's severity is strictly lower than the submitted brand's but still above zero; and it is `REJECTED` when `mapped_brand_code` is `NONE`, meaning the state refuses to carry any brand at all."

    Design: Corner/validations/interstate_recognition_downgrade_is_accepted_but_escalation_is_rejected
    """
    env = setup_salvage_titled_vehicle()
    title = read_title(env["salvage_title_id"])
    request = submit_recognition_request(
        env["salvage_title_id"], title["version"], requesting_state_code="AZ"
    )

    decided = validate_success(
        api_client.decide_recognition_request(
            request["id"],
            decide_recognition_request_payload(mapped_brand_code="NONE"),
            ADMIN_HEADERS,
        )
    )

    assert decided["status"] == "DECIDED", (
        f"expected DECIDED, got {decided['status']} after the requesting state answered"
    )
    assert decided["mapped_brand_code"] == "NONE", (
        f"expected NONE, got {decided['mapped_brand_code']}"
    )
    assert decided["outcome"] == "REJECTED", (
        "a mapping onto NONE is a refusal to carry the brand, expected REJECTED, got "
        f"{decided['outcome']}"
    )
    assert decided["submitted_brand_code"] == "SALVAGE", (
        f"the snapshot must survive the decision, got {decided['submitted_brand_code']}"
    )

    title_after = read_title(env["salvage_title_id"])
    assert title_after["recognition_state"] == "DOWNGRADED", (
        f"a REJECTED outcome downgrades the recognition dimension, got {title_after['recognition_state']}"
    )
    assert title_after["brand_code"] == "SALVAGE", (
        f"the home state's own brand is untouched, got {title_after['brand_code']}"
    )
    assert title_after["status"] == "ACTIVE", (
        f"expected ACTIVE, got {title_after['status']} — recognition never supersedes"
    )


def test_submitting_without_a_funded_balance_is_refused():
    """A rebuilder with an empty ledger cannot buy its way into the queue.

    PRD: "And the rebuilder's `fee_balance_cents` must be at least the `total_program_charge_cents` that this very call computes, or the submission is refused with `ERR_INSUFFICIENT_FEE_BALANCE` (HTTP 402)."

    Design: Corner/validations/submitting_without_a_funded_fee_balance_is_rejected
    """
    env = setup_submission_ready_application(body_class="TRAILER", deposit_cents=0)
    assert read_rebuilder(env["rebuilder_id"])["fee_balance_cents"] == 0, (
        "setup expected a rebuilder that has deposited nothing"
    )

    quote = read_fee_quote(env["application_id"])
    assert quote["assessed_fee_cents"] == 7500, (
        f"the bare base fee is 7500 cents, got {quote['assessed_fee_cents']}"
    )
    assert quote["total_program_charge_cents"] == 7500, (
        f"expected a 7500-cent charge, got {quote['total_program_charge_cents']}"
    )

    response = api_client.submit_application(
        env["application_id"],
        submit_application_payload(),
        make_rebuilder_headers(env["rebuilder_id"]),
    )
    validate_error(response, "ERR_INSUFFICIENT_FEE_BALANCE")

    application = read_application(env["application_id"])
    assert application["status"] == "DRAFT", (
        f"expected DRAFT, got {application['status']} after the refused submission"
    )
    assert application["fee_escrowed_cents"] == 0, (
        f"expected 0, got {application['fee_escrowed_cents']} — no escrow may be taken"
    )

    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["fee_balance_cents"] == 0, (
        f"expected 0, got {rebuilder['fee_balance_cents']} on an unfunded ledger"
    )
    assert rebuilder["escrowed_fee_total_cents"] == 0, (
        f"expected 0, got {rebuilder['escrowed_fee_total_cents']} after the refused submission"
    )


def test_reinstating_below_the_rolling_score_threshold_is_refused():
    """Untraceable paperwork keeps a suspended rebuilder suspended.

    PRD: "An action of `REINSTATE` moves the licence `SUSPENDED → ACTIVE` and is doubly gated: the acting `X-User-ID` must differ from `suspended_by_user_id`, and the rebuilder's `recordkeeping_score_rolling` must be at least 60.00, or the request is refused with `ERR_RECORDKEEPING_SCORE_BLOCKS_ACTION` (HTTP 422)."

    Design: Corner/validations/reinstating_a_licence_below_the_rolling_score_threshold_is_rejected
    """
    env = setup_draft_application(body_class="TRAILER")
    structural = file_parts_document(
        env["application_id"],
        env["rebuilder_id"],
        doc_type="RECEIPT",
        part_class="STRUCTURAL",
        source_type="OWNER_SUPPLIED",
        amount_cents=120_000,
    )
    lighting = file_parts_document(
        env["application_id"],
        env["rebuilder_id"],
        doc_type="RECEIPT",
        part_class="LIGHTING",
        source_type="OWNER_SUPPLIED",
        amount_cents=30_000,
    )
    for document_id in (structural["id"], lighting["id"]):
        verified = verify_parts_document(document_id, env["inspector_id"])
        assert verified["status"] == "VERIFIED", (
            f"expected VERIFIED, got {verified['status']} on document {document_id}"
        )
        assert verified["traceable"] is False, (
            f"owner-supplied parts carry no traceable source, got {verified['traceable']}"
        )

    suspended = take_license_action(
        env["rebuilder_id"], "SUSPEND", make_program_admin_headers(ADMIN_USER_ID)
    )
    assert suspended["license_status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {suspended['license_status']}"
    )
    assert suspended["recordkeeping_score_rolling"] == pytest.approx(40.00, abs=0.01), (
        "two untraceable verified documents score 40.00, got "
        f"{suspended['recordkeeping_score_rolling']}"
    )

    response = api_client.create_license_action(
        env["rebuilder_id"],
        create_license_action_payload("REINSTATE"),
        make_program_admin_headers(SECOND_ADMIN_USER_ID),
    )
    validate_error(response, "ERR_RECORDKEEPING_SCORE_BLOCKS_ACTION")

    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["license_status"] == "SUSPENDED", (
        f"expected the licence still SUSPENDED, got {rebuilder['license_status']}"
    )
    assert rebuilder["suspended_by_user_id"] == ADMIN_USER_ID, (
        f"expected {ADMIN_USER_ID}, got {rebuilder['suspended_by_user_id']} after the refusal"
    )
    assert rebuilder["recordkeeping_score_rolling"] == pytest.approx(40.00, abs=0.01), (
        f"expected 40.00, got {rebuilder['recordkeeping_score_rolling']} on the re-read"
    )


def test_submitting_with_only_three_camera_angles_is_refused():
    """Three photographs are one short of the program's minimum coverage.

    PRD: "`photo_view_count` must be at least 4 — the program requires four distinct camera angles on file — or the submission is refused with `ERR_PHOTO_SET_INCOMPLETE` (HTTP 422)."

    Design: Corner/validations/submitting_with_only_three_photo_views_is_rejected
    """
    env = setup_submission_ready_application(
        body_class="TRAILER", deposit_cents=500_000, views=("FRONT", "REAR", "LEFT")
    )
    application = read_application(env["application_id"])
    assert application["photo_view_count"] == 3, (
        f"setup expected three distinct angles, got {application['photo_view_count']}"
    )
    assert application["documentation_completeness_pct"] == pytest.approx(100.00, abs=0.01), (
        "a trailer's part-class coverage is complete, so only the photographs are short, got "
        f"{application['documentation_completeness_pct']}"
    )

    response = api_client.submit_application(
        env["application_id"],
        submit_application_payload(),
        make_rebuilder_headers(env["rebuilder_id"]),
    )
    validate_error(response, "ERR_PHOTO_SET_INCOMPLETE")

    after = read_application(env["application_id"])
    assert after["status"] == "DRAFT", (
        f"expected DRAFT, got {after['status']} after the refused submission"
    )
    assert after["photo_view_count"] == 3, (
        f"expected 3, got {after['photo_view_count']} — the refusal changes nothing"
    )
    assert after["fee_escrowed_cents"] == 0, (
        f"expected 0, got {after['fee_escrowed_cents']} — no escrow may be taken"
    )
    assert read_rebuilder(env["rebuilder_id"])["fee_balance_cents"] == 500_000, (
        "the deposit must be left intact by the refused submission"
    )
