"""Row shapes: what the server mints, what it defaults, and what it refuses to store."""

from test_helpers import (
    GALLERY_MANAGER,
    GALLERY_MANAGER_2,
    GALLERY_MANAGER_2_ID,
    INTAKE_APPRAISER,
    LOGISTICS_COORDINATOR,
    LOGISTICS_COORDINATOR_ID,
    NON_EXISTENT_UUID,
    SCORES_GRADE_A,
    ApiErrorId,
    api_client,
    consignor_payload,
    create_agreement,
    create_active_agreement,
    create_consignor,
    create_item,
    create_price_schedule,
    create_truck,
    fetch_agreement,
    fetch_consignor,
    fetch_consignor_ledger,
    fetch_item,
    fetch_price_schedule,
    get_success_data,
    item_payload,
    pickup_job_payload,
    price_schedule_step_payload,
    is_valid_uuid,
    screen_item,
    take_custody,
    total_count,
    validate_error,
)

ONE_STEP = [(1, 0, 0.0, 0)]


def test_registering_a_consignor_mints_the_account_defaults_the_client_never_sent():
    """Six submitted facts come back beside five figures only the server can know.

    PRD 3.1: "A freshly registered consignor opens with `status` `ACTIVE`,
    `escheat_state` `NONE`, `unclaimed_balance_cents` of 0, `lifetime_credits_cents` of
    0, and `last_activity_at` stamped with the current logical clock so the dormancy
    curve begins from registration rather than from the first sale."

    PRD 2.4: "Every resource carries a server-minted `id` that is a UUID string with no
    type prefix of any kind."

    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/consignor_creation_returns_201_with_system_defaults
    """
    payload = consignor_payload(
        display_name="Dana Reeve",
        address_line="14 Mill St",
        floor_number=3,
        has_elevator=False,
        payout_method="CHECK",
    )
    response = api_client.create_consignor(payload, GALLERY_MANAGER)
    assert response.status_code == 201, (
        f"Expected 201 on registration, got {response.status_code}"
    )
    body = response.json()
    data = get_success_data(response)

    assert data["display_name"] == "Dana Reeve", (
        f"Expected the submitted name, got {data['display_name']}"
    )
    assert data["email"] == payload["email"], (
        f"Expected the submitted email, got {data['email']}"
    )
    assert data["address_line"] == "14 Mill St", (
        f"Expected the submitted address, got {data['address_line']}"
    )
    assert data["floor_number"] == 3, (
        f"Expected floor 3, got {data['floor_number']}"
    )
    assert data["has_elevator"] is False, (
        f"Expected no elevator, got {data['has_elevator']}"
    )
    assert data["payout_method"] == "CHECK", (
        f"Expected CHECK, got {data['payout_method']}"
    )

    assert data["status"] == "ACTIVE", f"Expected ACTIVE, got {data['status']}"
    assert data["escheat_state"] == "NONE", (
        f"Expected NONE, got {data['escheat_state']}"
    )
    assert data["unclaimed_balance_cents"] == 0, (
        f"Expected an empty balance, got {data['unclaimed_balance_cents']}"
    )
    assert data["lifetime_credits_cents"] == 0, (
        f"Expected no lifetime credits, got {data['lifetime_credits_cents']}"
    )
    assert data["last_activity_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the logical clock stamped, got {data['last_activity_at']}"
    )
    assert data["version"] == 1, f"Expected version 1, got {data['version']}"
    assert is_valid_uuid(data["id"]), (
        f"Expected a bare UUID with no type prefix, got {data['id']}"
    )

    assert body["response_type"] == "object", (
        f"Expected an object envelope, got {body['response_type']}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"Expected a req_-prefixed request id, got {body['meta']['api_request_id']}"
    )
    assert body["meta"]["api_request_timestamp"], (
        "Expected a request timestamp in meta"
    )


def test_reading_a_consignor_back_returns_the_row_registration_minted():
    """The read is the write: same id, same created_at, same version 1.

    PRD 3.1: "A `payout_method` may be supplied and must be one of `ACH`, `CHECK` or
    `STORE_CREDIT`; when it is omitted the account defaults to `ACH`."

    PRD 2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with
    three fractional digits, taken from the logical clock described in §2.5 at the
    instant the row was inserted."

    Design: Corner/entities/consignor_retrieval_returns_the_stored_row
    """
    created = create_consignor(
        display_name="Dana Reeve", address_line="14 Mill St", floor_number=3
    )

    stored = fetch_consignor(created["id"])
    assert stored["id"] == created["id"], (
        f"Expected the same id back, got {stored['id']}"
    )
    assert stored["created_at"] == created["created_at"], (
        f"Expected created_at {created['created_at']} untouched, "
        f"got {stored['created_at']}"
    )
    assert stored["version"] == 1, (
        f"Expected a read to leave version at 1, got {stored['version']}"
    )
    assert stored["status"] == "ACTIVE", f"Expected ACTIVE, got {stored['status']}"
    assert stored["unclaimed_balance_cents"] == 0, (
        f"Expected an empty balance, got {stored['unclaimed_balance_cents']}"
    )
    assert stored["payout_method"] == "ACH", (
        f"Expected the ACH default because the create call omitted it, "
        f"got {stored['payout_method']}"
    )


def test_omitting_the_payout_method_settles_the_account_on_ach():
    """The one input field with a declared default takes it on both the write and the read.

    PRD 3.1: "A `payout_method` may be supplied and must be one of `ACH`, `CHECK` or
    `STORE_CREDIT`; when it is omitted the account defaults to `ACH`."

    Design: Corner/entities/omitting_payout_method_applies_the_ach_default
    """
    payload = consignor_payload(display_name="Alpha", address_line="1 A St")
    assert "payout_method" not in payload, (
        "This test must submit no payout_method at all"
    )

    response = api_client.create_consignor(payload, GALLERY_MANAGER)
    assert response.status_code == 201, (
        f"Expected 201 on registration, got {response.status_code}"
    )
    created = get_success_data(response)
    assert created["payout_method"] == "ACH", (
        f"Expected the ACH default in the create response, "
        f"got {created['payout_method']}"
    )
    assert fetch_consignor(created["id"])["payout_method"] == "ACH", (
        "Expected the ACH default to have been persisted, not merely echoed"
    )


def test_consignor_listing_windows_three_rows_two_at_a_time():
    """total_count counts the matches; has_more reports whether the window ran out.

    PRD 2.3: "`total_count` is the number of rows matching the request's filters before
    the window is applied, and `has_more` is true exactly when rows remain beyond the
    current window."

    PRD 2.3: "When `limit` is omitted it defaults to 10; the smallest accepted value is
    1 and the largest accepted value is 100."

    Design: Corner/entities/consignor_listing_is_paginated_with_total_count_and_has_more
    """
    for name in ("Alpha", "Bravo", "Charlie"):
        create_consignor(display_name=name)

    first = api_client.list_consignors(GALLERY_MANAGER, params={"limit": 2, "offset": 0})
    assert first.status_code == 200, (
        f"Expected 200 on the listing, got {first.status_code}"
    )
    body = first.json()
    assert body["response_type"] == "array", (
        f"Expected an array envelope, got {body['response_type']}"
    )
    assert len(body["data"]) == 2, (
        f"Expected exactly 2 rows in the window, got {len(body['data'])}"
    )
    assert body["meta"]["total_count"] == 3, (
        f"Expected 3 matches, got {body['meta']['total_count']}"
    )
    assert body["meta"]["has_more"] is True, (
        f"Expected rows to remain, got has_more {body['meta']['has_more']}"
    )
    assert body["meta"]["limit"] == 2 and body["meta"]["offset"] == 0, (
        f"Expected the window echoed back, got {body['meta']}"
    )

    second = api_client.list_consignors(
        GALLERY_MANAGER, params={"limit": 2, "offset": 2}
    ).json()
    assert len(second["data"]) == 1, (
        f"Expected the remaining single row, got {len(second['data'])}"
    )
    assert second["meta"]["total_count"] == 3, (
        f"Expected 3 matches again, got {second['meta']['total_count']}"
    )
    assert second["meta"]["has_more"] is False, (
        f"Expected nothing beyond the window, got has_more {second['meta']['has_more']}"
    )


def test_a_well_formed_uuid_naming_no_piece_is_a_not_found_rather_than_a_blank():
    """Path resolution answers 404 with the item-flavoured code, not an empty success.

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on
    every path-addressed endpoint."

    Design: Corner/entities/reading_an_unknown_item_id_returns_not_found
    """
    create_consignor(display_name="Alpha")

    response = api_client.get_item(NON_EXISTENT_UUID, GALLERY_MANAGER)
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error", (
        f"Expected an error envelope, got {response.json()['response_type']}"
    )


def _one_active_agreement():
    """A one-step schedule, a ground-floor consignor and an ACTIVE agreement over both."""
    schedule = create_price_schedule(steps=ONE_STEP)
    consignor = create_consignor(display_name="Alpha", address_line="1 A St")
    agreement = create_active_agreement(consignor["id"], schedule["id"], term_days=365)
    return {"schedule": schedule, "consignor": consignor, "agreement": agreement}


def test_intake_without_a_declared_value_stores_nothing():
    """A required field with no default is a schema violation, not a silent null.

    PRD 3.2: "a `declared_value_cents` of at least 1000 representing the consignor's
    declared replacement value"

    PRD 2.9: "the body carries all required fields with correct types, every enum value
    is in range, and every numeric bound holds"

    Design: Corner/entities/item_creation_without_declared_value_cents_is_rejected
    """
    world = _one_active_agreement()
    agreement_id = world["agreement"]["id"]

    payload = item_payload(
        agreement_id,
        title="Walnut credenza",
        category="CASEGOOD",
        photo_count=4,
        volume_cuft=12,
        footprint_sqft=20,
    )
    payload.pop("declared_value_cents")

    response = api_client.create_item(payload, INTAKE_APPRAISER)
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)

    assert fetch_agreement(agreement_id)["item_count"] == 0, (
        "Expected the refused intake to leave item_count at 0"
    )
    listed = api_client.list_items(
        GALLERY_MANAGER, params={"agreement_id": agreement_id, "limit": 100}
    )
    assert total_count(listed) == 0, (
        f"Expected no piece stored, got {total_count(listed)}"
    )


def test_a_category_outside_the_six_declared_values_stores_nothing():
    """ANTIQUE is not merchandise this gallery recognises.

    PRD 3.2: "a `category` that must be one of `SOFA`, `DINING`, `CASEGOOD`, `RUG`, `ART`
    or `OUTDOOR`"

    PRD 2.9: "the body carries all required fields with correct types, every enum value
    is in range, and every numeric bound holds"

    Design: Corner/entities/item_category_outside_the_declared_enum_is_rejected
    """
    world = _one_active_agreement()
    agreement_id = world["agreement"]["id"]

    response = api_client.create_item(
        item_payload(
            agreement_id,
            title="Victorian sideboard",
            category="ANTIQUE",
            declared_value_cents=60_000,
            photo_count=4,
            volume_cuft=12,
            footprint_sqft=20,
        ),
        INTAKE_APPRAISER,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)

    assert fetch_agreement(agreement_id)["item_count"] == 0, (
        "Expected the refused intake to leave item_count at 0"
    )


def test_a_crew_of_seven_movers_is_refused_before_anything_is_quoted():
    """The declared ceiling is six, so seven never reaches the surcharge formula.

    PRD 3.4: "a `crew_size` of between 2 and 6 movers inclusive"

    PRD 2.9: "the body carries all required fields with correct types, every enum value
    is in range, and every numeric bound holds"

    Design: Corner/entities/crew_size_above_the_declared_ceiling_is_rejected
    """
    world = _one_active_agreement()
    consignor_id = world["consignor"]["id"]
    piece = create_item(
        world["agreement"]["id"],
        title="Walnut credenza",
        category="CASEGOOD",
        declared_value_cents=60_000,
        photo_count=4,
        volume_cuft=12,
        footprint_sqft=20,
    )
    screen_item(piece["id"], scores=SCORES_GRADE_A)
    truck = create_truck(name="BOX-1", capacity_volume_cuft=100)

    response = api_client.create_pickup_job(
        pickup_job_payload(
            consignor_id,
            truck["id"],
            "2026-08-01T09:00:00Z",
            "2026-08-01T12:00:00Z",
            crew_size=7,
            item_ids=[piece["id"]],
        ),
        LOGISTICS_COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)

    listed = api_client.list_pickup_jobs(
        LOGISTICS_COORDINATOR, params={"consignor_id": consignor_id, "limit": 100}
    )
    assert total_count(listed) == 0, (
        f"Expected no job reserved, got {total_count(listed)}"
    )
    stored = fetch_item(piece["id"])
    assert stored["lifecycle_state"] == "SCREEN_ACCEPTED", (
        f"Expected the piece still SCREEN_ACCEPTED, got {stored['lifecycle_state']}"
    )
    assert stored["pickup_job_id"] is None, (
        f"Expected no job attached, got {stored['pickup_job_id']}"
    )


def test_the_job_counts_its_own_load_and_snapshots_the_residence():
    """Neither the load figures nor the access facts appear in the request body.

    PRD 3.4: "`declared_elevator` is a copy of the consignor's `has_elevator`, and
    `declared_stair_flights` is the consignor's `floor_number` reduced by 1 but never
    below zero"

    PRD 3.4: "then charge 2,500 cents per block, so a 41-cubic-foot load pays for five
    blocks"

    PRD 3.4: "it reads `declared_stair_flights`, `declared_elevator` and the quoted
    `crew_size`, writes the result to `quoted_surcharge_cents`, and mints no ledger entry
    whatsoever"

    PRD 3.4: "A new job opens in `status` `SCHEDULED` with `scheduled_by_user_id`
    recording the acting `X-User-ID`."

    Design: Corner/entities/pickup_job_item_count_and_volume_are_derived_from_the_attached_items
    """
    world = _one_active_agreement()
    consignor_id = world["consignor"]["id"]
    agreement_id = world["agreement"]["id"]

    credenza = create_item(
        agreement_id,
        title="Walnut credenza",
        category="CASEGOOD",
        declared_value_cents=55_001,
        photo_count=4,
        volume_cuft=20,
        footprint_sqft=18,
    )
    nightstand = create_item(
        agreement_id,
        title="Oak nightstand",
        category="CASEGOOD",
        declared_value_cents=20_004,
        photo_count=4,
        volume_cuft=13,
        footprint_sqft=12,
    )
    screen_item(credenza["id"], scores=SCORES_GRADE_A)
    screen_item(nightstand["id"], scores=SCORES_GRADE_A)
    truck = create_truck(name="BOX-1", capacity_volume_cuft=100)

    response = api_client.create_pickup_job(
        pickup_job_payload(
            consignor_id,
            truck["id"],
            "2026-08-01T09:00:00Z",
            "2026-08-01T12:00:00Z",
            crew_size=2,
            item_ids=[credenza["id"], nightstand["id"]],
        ),
        LOGISTICS_COORDINATOR,
    )
    assert response.status_code == 201, (
        f"Expected 201 on reservation, got {response.status_code}"
    )
    job = get_success_data(response)

    assert job["item_count"] == 2, (
        f"Expected two attached pieces, got {job['item_count']}"
    )
    assert job["total_volume_cuft"] == 33, (
        f"Expected 20 + 13 cubic feet, got {job['total_volume_cuft']}"
    )
    assert job["declared_stair_flights"] == 0, (
        f"Expected a ground-floor residence to declare zero flights, "
        f"got {job['declared_stair_flights']}"
    )
    assert job["declared_elevator"] is False, (
        f"Expected the consignor's has_elevator copied, "
        f"got {job['declared_elevator']}"
    )
    assert job["quoted_surcharge_cents"] == 22_000, (
        f"Expected 12000 plus four volume blocks, "
        f"got {job['quoted_surcharge_cents']}"
    )
    assert job["final_surcharge_cents"] is None, (
        f"Expected no final figure before completion, "
        f"got {job['final_surcharge_cents']}"
    )
    assert job["surcharge_variance_cents"] is None, (
        f"Expected no variance before completion, "
        f"got {job['surcharge_variance_cents']}"
    )
    assert job["status"] == "SCHEDULED", (
        f"Expected SCHEDULED, got {job['status']}"
    )
    assert job["scheduled_by_user_id"] == LOGISTICS_COORDINATOR_ID, (
        f"Expected the acting coordinator recorded, "
        f"got {job['scheduled_by_user_id']}"
    )

    loaded = fetch_item(credenza["id"])
    assert loaded["lifecycle_state"] == "SCHEDULED_PICKUP", (
        f"Expected SCHEDULED_PICKUP, got {loaded['lifecycle_state']}"
    )
    assert loaded["pickup_job_id"] == job["id"], (
        f"Expected the piece pointed at the new job, got {loaded['pickup_job_id']}"
    )
    assert fetch_consignor_ledger(consignor_id) == [], (
        "Expected the quoted variant to mint no ledger entry"
    )


def test_activation_stamps_the_term_and_the_approver_from_an_empty_body():
    """The body is empty, yet three fields and a version arrive on the row.

    PRD 3.2: "On success, `effective_at` is stamped with the current logical clock,
    `expires_at` is computed as `effective_at` advanced by `term_days` whole days — that
    is, by `term_days` multiplied by 86,400 seconds — `approved_by_user_id` records the
    acting `X-User-ID`, and the agreement's `version` increments by 1."

    PRD 3.2: "A drafted agreement opens in `status` `DRAFT` with an `item_count` of 0,
    and both `effective_at` and `expires_at` stay null until activation."

    Design: Corner/entities/agreement_activation_stamps_only_server_minted_fields
    """
    schedule = create_price_schedule(steps=ONE_STEP)
    consignor = create_consignor(display_name="Alpha", address_line="1 A St")
    drafted = create_agreement(consignor["id"], schedule["id"], term_days=365)
    assert drafted["status"] == "DRAFT", (
        f"Expected a DRAFT agreement to start from, got {drafted['status']}"
    )
    assert drafted["effective_at"] is None and drafted["expires_at"] is None, (
        f"Expected both term stamps null before activation, "
        f"got {drafted['effective_at']} and {drafted['expires_at']}"
    )

    response = api_client.activate_agreement(drafted["id"], GALLERY_MANAGER_2)
    assert response.status_code == 200, (
        f"Expected 200 on activation, got {response.status_code}"
    )
    activated = get_success_data(response)

    assert activated["status"] == "ACTIVE", (
        f"Expected ACTIVE, got {activated['status']}"
    )
    assert activated["effective_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the logical clock stamped, got {activated['effective_at']}"
    )
    assert activated["expires_at"].startswith("2027-08-01T00:00:00"), (
        f"Expected 365 whole days on from the clock, got {activated['expires_at']}"
    )
    assert activated["approved_by_user_id"] == GALLERY_MANAGER_2_ID, (
        f"Expected the approving manager rather than the drafting one, "
        f"got {activated['approved_by_user_id']}"
    )
    assert activated["version"] == 2, (
        f"Expected version 2 after the first mutation, got {activated['version']}"
    )
    assert activated["id"] == drafted["id"], (
        f"Expected the same id, got {activated['id']}"
    )
    assert activated["created_at"] == drafted["created_at"], (
        f"Expected created_at untouched, got {activated['created_at']}"
    )


def test_a_ledger_entry_exposes_no_version_and_no_updated_at():
    """A minted-and-never-amended row carries only id and created_at from the common set.

    PRD 2.4: "Two resource kinds are deliberately immutable once written and therefore
    carry neither `updated_at` nor `version`: a `PriceScheduleStep`, which is appended
    and never edited, and a `PayoutLedgerEntry`, which is minted and never amended."

    PRD 2.11: "names the piece it is attributable to through `item_id` (null for
    account-level entries such as a pickup surcharge or a disbursement)"

    PRD 2.11: "Three reporting columns exist only on a `PAYOUT_DISBURSEMENT_DEBIT` and
    are null on every other `entry_type`: `withholding_cents`, `processing_fee_cents` and
    `net_payout_cents`."

    Design: Corner/entities/payout_ledger_entries_carry_no_version_and_no_updated_at
    """
    world = _one_active_agreement()
    consignor_id = world["consignor"]["id"]
    credenza = create_item(
        world["agreement"]["id"],
        title="Walnut credenza",
        category="CASEGOOD",
        declared_value_cents=60_000,
        photo_count=4,
        volume_cuft=12,
        footprint_sqft=20,
    )
    screen_item(credenza["id"], scores=SCORES_GRADE_A)
    take_custody(consignor_id, [credenza["id"]])

    response = api_client.list_consignor_ledger_entries(
        consignor_id, GALLERY_MANAGER, params={"limit": 100}
    )
    assert response.status_code == 200, (
        f"Expected 200 on the ledger read, got {response.status_code}"
    )
    assert total_count(response) == 1, (
        f"Expected the single surcharge entry, got {total_count(response)}"
    )
    entry = get_success_data(response)[0]

    assert entry["entry_type"] == "PICKUP_SURCHARGE_DEBIT", (
        f"Expected PICKUP_SURCHARGE_DEBIT, got {entry['entry_type']}"
    )
    assert entry["amount_cents"] == -17_000, (
        f"Expected 12000 plus two volume blocks as a debit, "
        f"got {entry['amount_cents']}"
    )
    assert entry["balance_after_cents"] == -17_000, (
        f"Expected -17000, got {entry['balance_after_cents']}"
    )
    assert entry["item_id"] is None, (
        f"Expected an account-level entry, got item_id {entry['item_id']}"
    )
    for column in ("withholding_cents", "processing_fee_cents", "net_payout_cents"):
        assert entry[column] is None, (
            f"Expected {column} null on a surcharge entry, got {entry[column]}"
        )
    assert "id" in entry and "created_at" in entry, (
        f"Expected id and created_at, got {sorted(entry)}"
    )
    assert "version" not in entry, (
        f"Expected no version key on a ledger row, got {entry.get('version')}"
    )
    assert "updated_at" not in entry, (
        f"Expected no updated_at key on a ledger row, got {entry.get('updated_at')}"
    )


def test_appending_a_step_to_a_schedule_that_does_not_exist_changes_nothing():
    """The body foreign key is resolved before the append, and the real schedule is untouched.

    PRD 2.9: "Every foreign key supplied in the request body resolves to a stored row,
    validated in the order the keys appear in that endpoint's input list."

    PRD 3.1: "A successful append recomputes `step_count` and increments the schedule's
    `version` by 1."

    Design: Corner/entities/appending_a_step_to_an_unknown_schedule_is_rejected
    """
    schedule = create_price_schedule(steps=ONE_STEP)
    assert schedule["step_count"] == 1, (
        f"Expected one step attached, got {schedule['step_count']}"
    )

    response = api_client.create_price_schedule_step(
        price_schedule_step_payload(NON_EXISTENT_UUID, 1, 0, 0.15, 0), GALLERY_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_SCHEDULE_NOT_FOUND, 404)

    stored = fetch_price_schedule(schedule["id"])
    assert stored["step_count"] == 1, (
        f"Expected step_count still 1, got {stored['step_count']}"
    )
    assert stored["version"] == 2, (
        f"Expected version 2 from the one real append, got {stored['version']}"
    )
    listed = api_client.list_price_schedule_steps(
        schedule["id"], GALLERY_MANAGER, params={"limit": 100}
    )
    assert total_count(listed) == 1, (
        f"Expected one stored step, got {total_count(listed)}"
    )


def test_intake_against_an_agreement_that_does_not_exist_mints_no_orphan():
    """The piece reaches its owner only through the agreement, so an unknown one is fatal.

    PRD 2.9: "Every foreign key supplied in the request body resolves to a stored row,
    validated in the order the keys appear in that endpoint's input list."

    PRD 3.2: "`consignor_id` is copied from the named agreement at intake, so a piece can
    never be attributed to a consignor who did not sign for it."

    Design: Corner/entities/item_creation_against_an_unknown_agreement_fk_is_rejected
    """
    create_price_schedule(steps=ONE_STEP)
    create_consignor(display_name="Alpha", address_line="1 A St")

    response = api_client.create_item(
        item_payload(
            NON_EXISTENT_UUID,
            title="Walnut credenza",
            category="CASEGOOD",
            declared_value_cents=60_000,
            photo_count=4,
            volume_cuft=12,
            footprint_sqft=20,
        ),
        INTAKE_APPRAISER,
    )
    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_FOUND, 404)

    listed = api_client.list_items(GALLERY_MANAGER, params={"limit": 100})
    assert total_count(listed) == 0, (
        f"Expected no piece stored anywhere, got {total_count(listed)}"
    )
