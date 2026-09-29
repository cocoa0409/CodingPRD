"""Endpoint side effects: what each call returns and what it leaves behind.

Every test here drives a real endpoint and then re-reads the neighbouring
resources through their own endpoints, so that a side effect the specification
mandates on a counter, a status or a companion boolean cannot be faked by the
response body alone.
"""

from test_helpers import (
    BRAND_SEVERITY,
    api_client,
    assert_append_only_resource,
    assert_fee_ledger_closes,
    assert_finding,
    assert_money_cents,
    assert_title_record,
    create_deposit_payload,
    file_parts_document,
    is_iso8601_timestamp,
    issue_rebuilt_title_payload,
    issue_title,
    license_rebuilder,
    make_program_admin_headers,
    make_state_title_clerk_headers,
    read_application,
    read_finding,
    read_inspector,
    read_parts_document,
    read_rebuilder,
    read_station,
    read_title,
    read_vehicle,
    record_conveyance,
    record_finding,
    register_vehicle,
    schedule_inspection,
    setup_draft_application,
    setup_failed_application,
    setup_inspection_in_progress,
    setup_passed_application,
    setup_program_actors,
    setup_rebuilt_title_issued,
    setup_scheduled_inspection,
    submit_application,
    validate_paginated,
    validate_success,
    verify_parts_document,
)


# ---------------------------------------------------------------------------
# the non-mutating fee quotation
# ---------------------------------------------------------------------------
def test_fee_quote_read_returns_the_five_part_charge_breakdown():
    """The quotation publishes all five charge intermediates and mutates nothing.

    PRD: "It exposes every intermediate of the charge computation side by side — `assessed_fee_cents`, `subtotal_cents`, `expedite_fee_cents`, `discount_cents` and `total_program_charge_cents` — and it never changes the application."
    Design: Corner/endpoints/fee_quote_read_returns_the_five_part_charge_breakdown
    """
    donor_vehicle = register_vehicle()
    donor_title = issue_title(donor_vehicle["id"])

    # A trailer requires no part class, so the package is complete from the
    # start and exactly one verified document drives the whole assessment.
    env = setup_draft_application(body_class="TRAILER", expedite_requested=True)
    document = file_parts_document(
        env["application_id"],
        env["rebuilder_id"],
        doc_type="PARTS_INVOICE",
        part_class="STRUCTURAL",
        source_type="USED_DONOR",
        amount_cents=300_000,
        donor_title_id=donor_title["id"],
    )
    verify_parts_document(document["id"], env["inspector_id"])
    for view in ("FRONT", "REAR", "LEFT", "RIGHT"):
        api_client.create_parts_document(
            env["application_id"],
            {
                "doc_type": "PHOTOGRAPH",
                "part_class": "PHOTO_SET",
                "source_type": "OWNER_SUPPLIED",
                "photo_view_code": view,
            },
            env["rebuilder_headers"],
        )
    submitted = submit_application(env["application_id"], env["rebuilder_id"])

    response = api_client.get_fee_quote(env["application_id"], make_state_title_clerk_headers())
    quote = validate_success(response, expected_status=200)

    assert quote["assessed_fee_cents"] == 24500, (
        "assessed_fee_cents is the 7,500-cent base plus a 12,500-cent structural "
        f"surcharge plus a 4,500-cent donor surcharge, got {quote['assessed_fee_cents']}"
    )
    assert quote["subtotal_cents"] == 24500, (
        "the subtotal adds no re-inspection fee at zero completed attempts, "
        f"got {quote['subtotal_cents']}"
    )
    assert quote["expedite_fee_cents"] == 1715, (
        "a subtotal of 24,500 cents sits below 25,000 and therefore draws the "
        f"seven percent expedite rate, got {quote['expedite_fee_cents']}"
    )
    assert quote["discount_cents"] == 0, (
        "a rebuilder with no titled applications earns no volume discount, "
        f"got {quote['discount_cents']}"
    )
    assert quote["total_program_charge_cents"] == 26215, (
        "the total is the subtotal plus the expedite fee minus the discount, "
        f"got {quote['total_program_charge_cents']}"
    )
    for field in (
        "assessed_fee_cents",
        "subtotal_cents",
        "expedite_fee_cents",
        "discount_cents",
        "total_program_charge_cents",
    ):
        assert_money_cents(quote[field], f"fee quote.{field}")

    after = read_application(env["application_id"])
    assert after["version"] == submitted["version"], (
        "reading the quotation must not bump the application version, "
        f"moved from {submitted['version']} to {after['version']}"
    )
    assert after["total_program_charge_cents"] == 26215, (
        "the application still carries the charge computed at submission, "
        f"got {after['total_program_charge_cents']}"
    )
    assert after["status"] == "SUBMITTED", (
        f"reading the quotation must not move the application, got {after['status']}"
    )


# ---------------------------------------------------------------------------
# cancelling a booked attempt
# ---------------------------------------------------------------------------
def test_cancelling_a_scheduled_attempt_releases_the_inspector_and_the_bay():
    """Cancellation stamps CLERK_REQUEST and gives back both capacity holds.

    PRD: "The attempt moves `SCHEDULED → CANCELLED` with `cancellation_reason` set to `CLERK_REQUEST`, and both the inspector's `scheduled_inspection_count` and the station's `scheduled_occupancy_count` are decremented."
    Design: Corner/endpoints/cancelling_a_scheduled_inspection_releases_the_inspector_and_the_bay
    """
    env = setup_scheduled_inspection()

    assert read_inspector(env["inspector_id"])["scheduled_inspection_count"] == 1, (
        "the booked attempt must occupy the inspector's calendar before cancellation"
    )
    assert read_station(env["station_id"])["scheduled_occupancy_count"] == 1, (
        "the booked attempt must occupy a station bay before cancellation"
    )

    response = api_client.cancel_inspection(
        env["inspection_id"],
        {"cancellation_note": "citizen asked for a different week"},
        make_state_title_clerk_headers(),
    )
    cancelled = validate_success(response, expected_status=200)

    assert cancelled["status"] == "CANCELLED", (
        f"a cancelled attempt reads CANCELLED, got {cancelled['status']}"
    )
    assert cancelled["cancellation_reason"] == "CLERK_REQUEST", (
        "a clerk-driven cancellation stamps CLERK_REQUEST, "
        f"got {cancelled['cancellation_reason']}"
    )
    assert read_inspector(env["inspector_id"])["scheduled_inspection_count"] == 0, (
        "cancellation must decrement the inspector's scheduled_inspection_count"
    )
    assert read_station(env["station_id"])["scheduled_occupancy_count"] == 0, (
        "cancellation must decrement the station's scheduled_occupancy_count"
    )


def test_cancelling_the_only_attempt_walks_the_application_back_to_docs_accepted():
    """The application's fallback status is conditional on attempts_completed.

    PRD: "The application's fallback status is conditional on how far it had got: when the cancelled attempt was its only `SCHEDULED` attempt and `attempts_completed` is 0, the application falls back `SCHEDULED → DOCS_ACCEPTED`; when `attempts_completed` is at least 1, it falls back `SCHEDULED → FAILED` instead, because a previously failed attempt is still the application's most recent outcome."
    Design: Corner/endpoints/cancelling_a_scheduled_inspection_releases_the_inspector_and_the_bay
    """
    first = setup_scheduled_inspection()
    assert read_application(first["application_id"])["attempts_completed"] == 0, (
        "no attempt has been completed yet on the first application"
    )
    validate_success(
        api_client.cancel_inspection(
            first["inspection_id"], {}, make_state_title_clerk_headers()
        ),
        expected_status=200,
    )
    fell_back = read_application(first["application_id"])
    assert fell_back["status"] == "DOCS_ACCEPTED", (
        "cancelling the only attempt of an application with no completed attempt "
        f"walks it back to DOCS_ACCEPTED, got {fell_back['status']}"
    )

    # Now the other branch: one attempt already completed as a failure.
    second = setup_failed_application()
    other_inspector = setup_program_actors(with_station=False, deposit_cents=0)["inspector"]
    reinspection = schedule_inspection(
        second["application_id"],
        other_inspector["id"],
        second["station_id"],
        read_application(second["application_id"])["version"],
        "2026-08-14T09:00:00Z",
        "2026-08-14T11:00:00Z",
    )
    assert read_application(second["application_id"])["status"] == "SCHEDULED", (
        "the re-inspection puts the failed application back into SCHEDULED"
    )
    validate_success(
        api_client.cancel_inspection(
            reinspection["id"], {}, make_state_title_clerk_headers()
        ),
        expected_status=200,
    )
    after = read_application(second["application_id"])
    assert after["attempts_completed"] == 1, (
        f"the completed failure still counts, got {after['attempts_completed']}"
    )
    assert after["status"] == "FAILED", (
        "cancelling the re-inspection of an application with a completed attempt "
        f"falls back to FAILED, got {after['status']}"
    )


# ---------------------------------------------------------------------------
# recording a finding against a named parts document
# ---------------------------------------------------------------------------
def test_recording_a_documentation_gap_finding_links_the_attempt_and_the_document():
    """A non-critical documentation gap is recorded, attributed and non-blocking.

    PRD: "The server writes `recorded_by_inspector_id` from the acting principal, sets `resolved` to false, and computes the finding's `blocking` flag, which is true exactly when `severity` is `CRITICAL` or `category` is `STOLEN_COMPONENT` or `VIN_ALTERATION`, and false otherwise."
    Design: Corner/endpoints/recording_a_finding_links_the_inspection_and_the_named_parts_document
    """
    env = setup_inspection_in_progress()
    cited = env["documents"]["STRUCTURAL"]

    response = api_client.create_finding(
        env["inspection_id"],
        {
            "category": "DOCUMENTATION_GAP",
            "severity": "MAJOR",
            "description": "the frame invoice omits the casting number",
            "parts_document_id": cited["id"],
        },
        env["inspector_headers"],
    )
    finding = validate_success(response, expected_status=201)

    assert_finding(finding)
    assert_append_only_resource(finding, "finding")
    assert finding["inspection_id"] == env["inspection_id"], (
        "the finding must name the attempt it was recorded on"
    )
    assert finding["parts_document_id"] == cited["id"], (
        "the finding must name the parts document it impeaches"
    )
    assert finding["recorded_by_inspector_id"] == env["inspector_id"], (
        "recorded_by_inspector_id comes from the acting principal, "
        f"got {finding['recorded_by_inspector_id']}"
    )
    assert finding["resolved"] is False, "a freshly recorded finding is unresolved"
    assert finding["blocking"] is False, (
        "a MAJOR documentation gap is neither CRITICAL nor a stolen-component or "
        "VIN-alteration category, so blocking must be false"
    )

    reread = read_finding(finding["id"])
    assert reread["id"] == finding["id"], "the finding must be readable by its own id"
    assert reread["blocking"] is False, "the stored finding carries the same blocking flag"


def test_a_non_blocking_finding_leaves_the_attempt_unforced():
    """blocking_findings_count counts only blocking findings, so forced_fail stays down.

    PRD: "A blocking finding raises the attempt's `blocking_findings_count`, which counts this attempt's findings whose `blocking` is true and whose `resolved` is false."
    Design: Corner/endpoints/recording_a_finding_links_the_inspection_and_the_named_parts_document
    """
    env = setup_inspection_in_progress()
    record_finding(
        env["inspection_id"],
        env["inspector_id"],
        category="DOCUMENTATION_GAP",
        severity="MAJOR",
        description="the frame invoice omits the casting number",
        parts_document_id=env["documents"]["STRUCTURAL"]["id"],
    )

    inspection = validate_success(
        api_client.get_inspection(env["inspection_id"], make_state_title_clerk_headers()),
        expected_status=200,
    )
    assert inspection["blocking_findings_count"] == 0, (
        "a non-blocking finding must not raise blocking_findings_count, "
        f"got {inspection['blocking_findings_count']}"
    )
    assert inspection["forced_fail"] is False, (
        "forced_fail latches only once blocking_findings_count reaches 1"
    )
    assert inspection["status"] == "IN_PROGRESS", (
        f"recording a finding leaves the attempt open, got {inspection['status']}"
    )


def test_a_documentation_gap_finding_sets_off_no_document_or_referral_cascade():
    """Only a stolen-component finding rejects the cited document and opens a referral.

    PRD: "A finding whose `category` is `STOLEN_COMPONENT` and which cites a `parts_document_id` sets off the longest cascade in the program, and every step of it must land."
    Design: Corner/endpoints/recording_a_finding_links_the_inspection_and_the_named_parts_document
    """
    env = setup_inspection_in_progress()
    cited = env["documents"]["STRUCTURAL"]
    before = read_application(env["application_id"])

    record_finding(
        env["inspection_id"],
        env["inspector_id"],
        category="DOCUMENTATION_GAP",
        severity="MAJOR",
        description="the frame invoice omits the casting number",
        parts_document_id=cited["id"],
    )

    document = read_parts_document(cited["id"])
    assert document["status"] == "VERIFIED", (
        "a documentation-gap finding does not reject the document it cites, "
        f"got {document['status']}"
    )
    assert document["rejection_reason"] is None, (
        f"no rejection reason is written, got {document['rejection_reason']}"
    )
    after = read_application(env["application_id"])
    assert after["documented_parts_cost_cents"] == before["documented_parts_cost_cents"], (
        "no verified amount was withdrawn, so documented_parts_cost_cents must hold at "
        f"{before['documented_parts_cost_cents']}, got {after['documented_parts_cost_cents']}"
    )
    assert read_vehicle(env["vehicle_id"])["fraud_hold"] == "NONE", (
        "no referral is synthesised, so the vehicle's fraud_hold stays NONE"
    )
    referrals, meta = validate_paginated(
        api_client.list_fraud_referrals(
            make_state_title_clerk_headers(), {"vehicle_id": env["vehicle_id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no fraud referral may exist against the vehicle, got {referrals}"
    )


def test_findings_are_reachable_through_both_the_attempt_and_the_document_filter():
    """The finding is reverse-reachable from the attempt and from the cited document.

    PRD: "Findings may be filtered by `inspection_id`, `parts_document_id`, `category` and `severity`."
    Design: Corner/endpoints/recording_a_finding_links_the_inspection_and_the_named_parts_document
    """
    env = setup_inspection_in_progress()
    cited = env["documents"]["STRUCTURAL"]
    finding = record_finding(
        env["inspection_id"],
        env["inspector_id"],
        category="DOCUMENTATION_GAP",
        severity="MAJOR",
        description="the frame invoice omits the casting number",
        parts_document_id=cited["id"],
    )

    headers = make_state_title_clerk_headers()
    by_inspection, inspection_meta = validate_paginated(
        api_client.list_findings(headers, {"inspection_id": env["inspection_id"]})
    )
    assert inspection_meta["total_count"] == 1, (
        f"the attempt has exactly one finding, got {inspection_meta['total_count']}"
    )
    assert [row["id"] for row in by_inspection] == [finding["id"]], (
        "the inspection_id filter must return exactly the recorded finding"
    )

    by_document, document_meta = validate_paginated(
        api_client.list_findings(headers, {"parts_document_id": cited["id"]})
    )
    assert document_meta["total_count"] == 1, (
        f"the cited document has exactly one finding, got {document_meta['total_count']}"
    )
    assert [row["id"] for row in by_document] == [finding["id"]], (
        "the parts_document_id filter must return exactly the recorded finding"
    )

    by_category, category_meta = validate_paginated(
        api_client.list_findings(
            headers, {"inspection_id": env["inspection_id"], "category": "STOLEN_COMPONENT"}
        )
    )
    assert category_meta["total_count"] == 0, (
        f"the finding is a DOCUMENTATION_GAP, not a STOLEN_COMPONENT, got {by_category}"
    )


# ---------------------------------------------------------------------------
# minting the rebuilt title
# ---------------------------------------------------------------------------
def test_issuing_a_rebuilt_title_supersedes_the_salvage_title_and_returns_the_new_record():
    """The mint returns a REBUILT successor and pushes the salvage row to SUPERSEDED.

    PRD: "A successful issuance mints a new title record whose `brand_code` is `REBUILT`, whose `predecessor_title_id` is the application's `salvage_title_id`, whose `status` is `ACTIVE`, whose `issued_at` is the logical clock, and whose `odometer_at_issue_miles` is taken from the vehicle's `last_odometer_miles`."
    Design: Corner/endpoints/issuing_a_rebuilt_title_supersedes_the_salvage_title_and_returns_the_new_record
    """
    env = setup_passed_application()
    vehicle_before = read_vehicle(env["vehicle_id"])

    response = api_client.issue_rebuilt_title(
        env["application_id"], issue_rebuilt_title_payload(), make_state_title_clerk_headers()
    )
    rebuilt = validate_success(response, expected_status=201)

    assert_title_record(rebuilt)
    assert rebuilt["brand_code"] == "REBUILT", (
        f"the minted title carries the REBUILT brand, got {rebuilt['brand_code']}"
    )
    assert rebuilt["brand_severity"] == BRAND_SEVERITY["REBUILT"], (
        f"brand_severity is the ladder value of REBUILT, got {rebuilt['brand_severity']}"
    )
    assert rebuilt["predecessor_title_id"] == env["salvage_title_id"], (
        "predecessor_title_id is the application's salvage_title_id, "
        f"got {rebuilt['predecessor_title_id']}"
    )
    assert rebuilt["status"] == "ACTIVE", (
        f"the minted title opens in ACTIVE, got {rebuilt['status']}"
    )
    assert rebuilt["is_current"] is True, "the minted title is the vehicle's current row"
    assert is_iso8601_timestamp(rebuilt["issued_at"]), (
        f"issued_at is stamped from the logical clock, got {rebuilt['issued_at']!r}"
    )
    assert rebuilt["odometer_at_issue_miles"] == vehicle_before["last_odometer_miles"], (
        "odometer_at_issue_miles is taken from the vehicle's last_odometer_miles "
        f"{vehicle_before['last_odometer_miles']}, got {rebuilt['odometer_at_issue_miles']}"
    )
    assert rebuilt["transfer_sequence"] == 1, (
        "the rebuilt row sits one step down the chain from the salvage title, "
        f"got {rebuilt['transfer_sequence']}"
    )

    superseded = read_title(env["salvage_title_id"])
    assert superseded["status"] == "SUPERSEDED", (
        f"the salvage title yields to its successor, got {superseded['status']}"
    )
    assert superseded["is_current"] is False, (
        "a superseded title's is_current is driven to false"
    )
    vehicle_after = read_vehicle(env["vehicle_id"])
    assert vehicle_after["active_brand_code"] == "REBUILT", (
        f"the vehicle's current brand becomes REBUILT, got {vehicle_after['active_brand_code']}"
    )
    assert "REBUILT" in vehicle_after["brand_history"], "brand_history gains REBUILT"
    assert "SALVAGE" in vehicle_after["brand_history"], (
        f"brand_history retains the earlier SALVAGE entry, got {vehicle_after['brand_history']}"
    )
    assert read_application(env["application_id"])["status"] == "TITLE_ISSUED", (
        "the application moves PASSED to TITLE_ISSUED"
    )


def test_issuing_a_rebuilt_title_captures_the_escrow_into_fees_consumed():
    """Issuance captures the escrow: consumed rises, escrow zeroes, balance holds.

    PRD: "The program captures the escrow — `fees_consumed_cents` rises by `fee_escrowed_cents`, which is then zeroed, so `escrowed_fee_total_cents` falls by the same amount and `fee_balance_cents` is untouched."
    Design: Corner/endpoints/issuing_a_rebuilt_title_supersedes_the_salvage_title_and_returns_the_new_record
    """
    env = setup_passed_application()
    application_before = read_application(env["application_id"])
    rebuilder_before = read_rebuilder(env["rebuilder_id"])
    escrowed = application_before["fee_escrowed_cents"]
    assert escrowed > 0, "a submitted application holds a positive escrow before issuance"
    assert rebuilder_before["escrowed_fee_total_cents"] == escrowed, (
        "the rebuilder's escrow total is the sum over its live applications, "
        f"got {rebuilder_before['escrowed_fee_total_cents']} against {escrowed}"
    )

    validate_success(
        api_client.issue_rebuilt_title(
            env["application_id"], issue_rebuilt_title_payload(), make_state_title_clerk_headers()
        ),
        expected_status=201,
    )

    application_after = read_application(env["application_id"])
    rebuilder_after = read_rebuilder(env["rebuilder_id"])
    assert application_after["fee_escrowed_cents"] == 0, (
        f"the captured escrow is zeroed, got {application_after['fee_escrowed_cents']}"
    )
    assert rebuilder_after["fees_consumed_cents"] == (
        rebuilder_before["fees_consumed_cents"] + escrowed
    ), (
        f"fees_consumed_cents must rise by the captured {escrowed}, "
        f"got {rebuilder_after['fees_consumed_cents']}"
    )
    assert rebuilder_after["escrowed_fee_total_cents"] == (
        rebuilder_before["escrowed_fee_total_cents"] - escrowed
    ), (
        f"escrowed_fee_total_cents must fall by {escrowed}, "
        f"got {rebuilder_after['escrowed_fee_total_cents']}"
    )
    assert rebuilder_after["fee_balance_cents"] == rebuilder_before["fee_balance_cents"], (
        "a capture leaves fee_balance_cents untouched, "
        f"moved from {rebuilder_before['fee_balance_cents']} to "
        f"{rebuilder_after['fee_balance_cents']}"
    )
    assert rebuilder_after["applications_titled_count"] == (
        rebuilder_before["applications_titled_count"] + 1
    ), (
        "applications_titled_count rises by 1, "
        f"got {rebuilder_after['applications_titled_count']}"
    )
    assert_fee_ledger_closes(rebuilder_after)


# ---------------------------------------------------------------------------
# reading the title chain back through the list filters
# ---------------------------------------------------------------------------
def test_title_records_is_current_filter_returns_only_the_successor_after_a_transfer():
    """After a conveyance exactly one row of the vehicle is is_current true.

    PRD: "A companion boolean, `is_current`, is true exactly when the row's `status` is `ACTIVE` and no other title record of the same vehicle is `ACTIVE`; it defaults to true on creation and is driven to false whenever the row leaves `ACTIVE`."
    Design: Corner/endpoints/title_records_list_filters_current_and_brand_across_a_transfer
    """
    env = setup_rebuilt_title_issued()
    conveyance = record_conveyance(env["rebuilt_title_id"])
    successor_id = conveyance["to_title_id"]

    headers = make_state_title_clerk_headers()
    current_rows, current_meta = validate_paginated(
        api_client.list_title_records(
            headers, {"vehicle_id": env["vehicle_id"], "is_current": "true"}
        )
    )
    assert current_meta["total_count"] == 1, (
        "exactly one title row of the vehicle may be current, "
        f"got {current_meta['total_count']}"
    )
    assert current_rows[0]["id"] == successor_id, (
        "the current row is the successor the conveyance minted, "
        f"got {current_rows[0]['id']} rather than {successor_id}"
    )
    assert current_rows[0]["status"] == "ACTIVE", (
        f"the current row is the ACTIVE one, got {current_rows[0]['status']}"
    )

    stale_rows, stale_meta = validate_paginated(
        api_client.list_title_records(
            headers, {"vehicle_id": env["vehicle_id"], "is_current": "false"}
        )
    )
    assert stale_meta["total_count"] == 2, (
        "the salvage and rebuilt rows have both left ACTIVE, "
        f"got {stale_meta['total_count']}"
    )
    assert successor_id not in [row["id"] for row in stale_rows], (
        "the successor must not appear among the non-current rows"
    )
    assert all(row["is_current"] is False for row in stale_rows), (
        "every row returned by the is_current=false filter reads false"
    )


def test_title_records_brand_filter_reports_the_prepagination_total_count():
    """total_count counts the filter matches before the page limit is applied.

    PRD: "The `meta` block of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the current page."
    Design: Corner/endpoints/title_records_list_filters_current_and_brand_across_a_transfer
    """
    env = setup_rebuilt_title_issued()
    conveyance = record_conveyance(env["rebuilt_title_id"])
    successor = read_title(conveyance["to_title_id"])
    assert successor["brand_code"] == "REBUILT", (
        "the successor carries the chain's most severe brand forward, "
        f"got {successor['brand_code']}"
    )

    headers = make_state_title_clerk_headers()
    first_page, first_meta = validate_paginated(
        api_client.list_title_records(
            headers, {"vehicle_id": env["vehicle_id"], "brand_code": "REBUILT", "limit": 1}
        )
    )
    assert len(first_page) == 1, f"a limit of 1 returns one row, got {len(first_page)}"
    assert first_meta["limit"] == 1, f"meta echoes the requested limit, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, f"offset defaults to 0, got {first_meta['offset']}"
    assert first_meta["total_count"] == 2, (
        "both the rebuilt title and its conveyed successor match the brand filter, "
        f"got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        "a second matching row remains beyond the first page"
    )
    assert first_page[0]["id"] == env["rebuilt_title_id"], (
        "list results are ordered by created_at ascending, so the rebuilt title leads"
    )

    second_page, second_meta = validate_paginated(
        api_client.list_title_records(
            headers,
            {
                "vehicle_id": env["vehicle_id"],
                "brand_code": "REBUILT",
                "limit": 1,
                "offset": 1,
            },
        )
    )
    assert second_meta["total_count"] == 2, (
        f"total_count ignores the page window, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, "no row remains beyond the second page"
    assert second_page[0]["id"] == successor["id"], (
        f"the second page carries the successor, got {second_page[0]['id']}"
    )

    salvage_rows, salvage_meta = validate_paginated(
        api_client.list_title_records(
            headers, {"vehicle_id": env["vehicle_id"], "brand_code": "SALVAGE"}
        )
    )
    assert salvage_meta["total_count"] == 1, (
        f"only the original salvage row carries the SALVAGE brand, got {salvage_rows}"
    )


# ---------------------------------------------------------------------------
# crediting program funds
# ---------------------------------------------------------------------------
def test_depositing_twice_returns_the_running_rebuilder_balance():
    """Each deposit adds to both money counters and bumps the rebuilder's version.

    PRD: "Each accepted deposit adds its `amount_cents` to the rebuilder's `fees_deposited_cents` and the same amount to its `fee_balance_cents`, and increments the rebuilder's `version` by 1."
    Design: Corner/endpoints/depositing_twice_returns_the_running_rebuilder_balance
    """
    rebuilder = license_rebuilder()
    assert rebuilder["fees_deposited_cents"] == 0, "a new rebuilder starts with nothing deposited"
    assert rebuilder["fee_balance_cents"] == 0, "a new rebuilder starts with a zero balance"
    admin = make_program_admin_headers()

    first = validate_success(
        api_client.create_deposit(
            rebuilder["id"], create_deposit_payload(amount_cents=250_000), admin
        ),
        expected_status=200,
    )
    assert first["fees_deposited_cents"] == 250_000, (
        f"the first deposit lands in fees_deposited_cents, got {first['fees_deposited_cents']}"
    )
    assert first["fee_balance_cents"] == 250_000, (
        f"the first deposit is immediately spendable, got {first['fee_balance_cents']}"
    )
    assert first["version"] == rebuilder["version"] + 1, (
        f"the deposit bumps the rebuilder version by 1, got {first['version']}"
    )

    second = validate_success(
        api_client.create_deposit(
            rebuilder["id"], create_deposit_payload(amount_cents=175_000), admin
        ),
        expected_status=200,
    )
    assert second["fees_deposited_cents"] == 425_000, (
        "fees_deposited_cents is the cumulative sum of every accepted deposit, "
        f"got {second['fees_deposited_cents']}"
    )
    assert second["fee_balance_cents"] == 425_000, (
        f"the running balance is the sum of both deposits, got {second['fee_balance_cents']}"
    )
    assert second["version"] == first["version"] + 1, (
        f"the second deposit bumps the version again, got {second['version']}"
    )
    assert second["escrowed_fee_total_cents"] == 0, (
        "no application has escrowed anything yet, "
        f"got {second['escrowed_fee_total_cents']}"
    )
    assert second["fees_consumed_cents"] == 0, (
        f"nothing has been captured yet, got {second['fees_consumed_cents']}"
    )
    assert_fee_ledger_closes(read_rebuilder(rebuilder["id"]))
