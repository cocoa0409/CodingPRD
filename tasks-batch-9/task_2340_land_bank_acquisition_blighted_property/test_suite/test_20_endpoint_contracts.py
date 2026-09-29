"""
The read surface of the API: what a creation echoes back, what a single read
returns, how a collection is filtered and ordered, and what the authority-wide
computed read reconciles.

Every test here starts from an empty store and builds, through the API's own
endpoints, both the rows it expects to see and at least one row it expects the
filter or the scope to leave out.
"""

from test_helpers import (
    CLERK_1,
    INTAKE_1,
    INV_1,
    TREAS_1,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_acquisition_packet,
    assert_demolition_run,
    assert_inventory_area_conserved,
    assert_title_action,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


# ── acquisition packets: create, read, filter ───────────────────────────────
def _packet_book_on_one_source(api):
    """
    One acquisition budget carrying three packets - a tax foreclosure and a
    donation left in due diligence and a third one declined - plus a fourth
    packet drawn on a second budget. The declined packet and the packet on the
    second budget are the rows the two filters must leave out.
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Packet CRUD Line",
        source_type="GENERAL_FUND",
        authorized_cents=900000,
        restriction="ACQUISITION_ONLY",
        expires_on="2029-12-31T00:00:00Z",
    )
    other_source = fixtures.create_funding_source(
        api,
        name="Second Acquisition Line",
        source_type="GRANT",
        authorized_cents=900000,
        restriction="ACQUISITION_ONLY",
        expires_on="2029-12-31T00:00:00Z",
    )
    parcels = [
        fixtures.create_property(
            api,
            address=f"{3220 + offset} Viburnum Ln",
            situs_ward=5,
            lot_area_sqft=6000,
            assessed_value_cents=250000,
            structure_present=offset == 0,
            structure_condition_grade="C",
            vacancy_months=3,
        )
        for offset in range(4)
    ]

    # The clock is moved between each opening so that the creation order of the
    # packets is unambiguous.
    fixtures.set_clock(api, "2026-08-01T01:00:00Z")
    foreclosure_payload = factories.without(
        factories.acquisition_packet_payload(
            parcels[0]["id"],
            funding_source["id"],
            channel="TAX_FORECLOSURE",
            title_search_fee_cents=6000,
            foreclosure_case_no="CV-2026-3220",
        ),
        "donor_name",
    )
    foreclosure_packet = validate_success(
        api.create_acquisition_packet(foreclosure_payload, INTAKE_1), 201
    )

    fixtures.set_clock(api, "2026-08-01T02:00:00Z")
    donation_payload = factories.acquisition_packet_payload(
        parcels[1]["id"], funding_source["id"], donor_name="Viburnum Family Trust"
    )
    donation_packet = validate_success(
        api.create_acquisition_packet(donation_payload, INTAKE_1), 201
    )

    fixtures.set_clock(api, "2026-08-01T03:00:00Z")
    declined_packet = fixtures.open_packet(
        api, parcels[2]["id"], funding_source["id"], donor_name="Viburnum Family Trust"
    )
    fixtures.decline_packet(api, declined_packet["id"])

    fixtures.set_clock(api, "2026-08-01T04:00:00Z")
    other_source_packet = fixtures.open_packet(
        api, parcels[3]["id"], other_source["id"], donor_name="Alder Family Trust"
    )

    return {
        "funding_source": funding_source,
        "other_source": other_source,
        "parcels": parcels,
        "foreclosure_packet": foreclosure_packet,
        "donation_packet": donation_packet,
        "declined_packet": declined_packet,
        "other_source_packet": other_source_packet,
    }


def test_packet_creation_stores_the_paperwork_its_channel_demands(api):
    """
    A packet keeps the docket number a tax foreclosure requires and the donor a
    donation requires, and carries neither field on the channel that does not
    ask for it.

    Each channel brings its own paperwork: a tax foreclosure requires the docket number as `foreclosure_case_no` and must not carry a donor, a donation requires the `donor_name` of record and must carry `offer_price_cents` of exactly zero, and a negotiated purchase carries neither of those two fields.

    Design: Corner/endpoints/acquisition_packet_crud_create_read_and_filtered_list
    """
    book = _packet_book_on_one_source(api)
    foreclosure = book["foreclosure_packet"]
    donation = book["donation_packet"]

    assert_acquisition_packet(foreclosure)
    assert foreclosure["status"] == "DUE_DILIGENCE"
    assert foreclosure["channel"] == "TAX_FORECLOSURE"
    assert foreclosure["foreclosure_case_no"] == "CV-2026-3220"
    assert foreclosure.get("donor_name") is None
    assert foreclosure["title_search_fee_cents"] == 6000
    assert foreclosure["committed_cents"] == 0

    assert_acquisition_packet(donation)
    assert donation["channel"] == "DONATION"
    assert donation["donor_name"] == "Viburnum Family Trust"
    assert donation["offer_price_cents"] == 0
    assert donation.get("foreclosure_case_no") is None


def test_reading_one_packet_answers_200_with_the_stored_row(api):
    """
    Reading a packet by its id answers 200 with the row exactly as it was
    written.

    Operations that advance or amend an existing record, including every state transition, every county data posting, the compliance sweep and every read, answer with `200 OK`.

    Design: Corner/endpoints/acquisition_packet_crud_create_read_and_filtered_list
    """
    book = _packet_book_on_one_source(api)
    created = book["foreclosure_packet"]

    fetched = validate_success(
        api.get_acquisition_packet(created["id"], TREAS_1), 200
    )

    assert_acquisition_packet(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["property_id"] == book["parcels"][0]["id"]
    assert fetched["funding_source_id"] == book["funding_source"]["id"]
    assert fetched["title_search_fee_cents"] == 6000
    assert fetched["status"] == "DUE_DILIGENCE"
    assert fetched["initiated_by_user_id"] == created["initiated_by_user_id"]


def test_packet_list_composes_two_filters_and_pages_the_oldest_first(api):
    """
    A packet list narrowed by funding source and status counts only the matching
    packets and returns them oldest first, so a one-record page opens with the
    earliest match.

    Unless a specific list states otherwise, records are returned sorted by `created_at` ascending.

    Design: Corner/endpoints/acquisition_packet_crud_create_read_and_filtered_list
    """
    book = _packet_book_on_one_source(api)

    packets, meta = validate_paginated(
        api.list_acquisition_packets(
            CLERK_1,
            {
                "funding_source_id": book["funding_source"]["id"],
                "status": "DUE_DILIGENCE",
                "limit": 1,
                "offset": 0,
            },
        )
    )

    # Two of the four packets match both filters: the declined one fails the
    # status filter and the one drawn on the second budget fails the source
    # filter.
    assert meta["total_count"] == 2
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert len(packets) == 1
    assert packets[0]["id"] == book["foreclosure_packet"]["id"]

    both_pages, all_meta = validate_paginated(
        api.list_acquisition_packets(
            CLERK_1,
            {
                "funding_source_id": book["funding_source"]["id"],
                "status": "DUE_DILIGENCE",
            },
        )
    )
    assert all_meta["total_count"] == 2
    assert [row["id"] for row in both_pages] == [
        book["foreclosure_packet"]["id"],
        book["donation_packet"]["id"],
    ]
    returned_ids = {row["id"] for row in both_pages}
    assert book["declined_packet"]["id"] not in returned_ids
    assert book["other_source_packet"]["id"] not in returned_ids


# ── the authority-wide computed read ───────────────────────────────────────
def _three_acquired_parcels_and_one_registry_parcel(api):
    """
    Three parcels taken in by donation with a 3,000-cent title search fee each -
    two in ward 7 and one in ward 8 - plus a large ward 7 parcel left in the
    prospect registry, which no area figure may count.
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Summary Line",
        source_type="GENERAL_FUND",
        authorized_cents=1000000,
        restriction="ACQUISITION_ONLY",
        expires_on="2029-12-31T00:00:00Z",
    )
    acquired = []
    for address, ward, area in (
        ("3230 Willow Ln", 7, 4000),
        ("3231 Willow Ln", 7, 5000),
        ("3232 Yew Ln", 8, 5000),
    ):
        parcel = fixtures.create_property(
            api,
            address=address,
            situs_ward=ward,
            lot_area_sqft=area,
            assessed_value_cents=150000,
            structure_present=False,
            structure_condition_grade="C",
            vacancy_months=2,
        )
        fixtures.acquire_property(
            api,
            parcel["id"],
            funding_source["id"],
            title_search_fee_cents=3000,
            donor_name="Willow Trust",
        )
        acquired.append(fixtures.read_property(api, parcel["id"]))

    registry_only = fixtures.create_property(
        api,
        address="3233 Willow Ln",
        situs_ward=7,
        lot_area_sqft=20000,
        assessed_value_cents=150000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=2,
    )
    return funding_source, acquired, registry_only


def test_inventory_summary_counts_only_the_parcels_the_authority_holds(api):
    """
    The authority-wide summary counts every acquired parcel and its area while
    leaving the registry-only prospect out of both area figures.

    `inventory_area_sqft` is the sum of `lot_area_sqft` over every parcel whose `custody_status` is `ACQUIRED`, `LISTED` or `REVERTED`; `conveyed_area_sqft` is the same sum over parcels in `CONVEYED`; and `inventory_property_count` is the number of parcels in the three inventory states.

    Design: Corner/endpoints/inventory_summary_computed_read_reconciles_ward_and_ledger
    """
    _, acquired, registry_only = _three_acquired_parcels_and_one_registry_parcel(api)
    assert [row["custody_status"] for row in acquired] == ["ACQUIRED"] * 3
    assert fixtures.read_property(api, registry_only["id"])["custody_status"] == (
        "PROSPECT"
    )

    summary = fixtures.inventory_summary(api, headers=TREAS_1)

    assert summary["inventory_property_count"] == 3
    assert summary["inventory_area_sqft"] == 14000
    assert summary["conveyed_area_sqft"] == 0
    assert summary["cure_pending_count"] == 0
    assert_inventory_area_conserved(summary, 14000)

    # Three closings disbursed the three 3,000-cent title search fees and left
    # nothing committed, so the identity reads 1,000,000 = 991,000 + 0 + 9,000.
    assert summary["total_authorized_cents"] == 1000000
    assert summary["total_committed_cents"] == 0
    assert summary["total_disbursed_cents"] == 9000
    assert summary["total_available_cents"] == 991000
    assert summary["total_authorized_cents"] == (
        summary["total_available_cents"]
        + summary["total_committed_cents"]
        + summary["total_disbursed_cents"]
    )


def test_inventory_summary_ward_filter_narrows_parcels_but_not_the_ledger(api):
    """
    Narrowing the summary to one ward narrows the parcel figures to that ward
    while the four ledger totals stay authority-wide.

    Finally, any staff role can read the authority-wide position, optionally narrowed to one `situs_ward`: `inventory_property_count`, `inventory_area_sqft` and `conveyed_area_sqft` from the conserved-area rules of §2.11, the `cure_pending_count` of agreements currently in their cure window, and the ledger identity totals across every funding source — `total_authorized_cents`, `total_committed_cents`, `total_disbursed_cents` and `total_available_cents`, which must always satisfy the identity of §2.8.

    Design: Corner/endpoints/inventory_summary_computed_read_reconciles_ward_and_ledger
    """
    _three_acquired_parcels_and_one_registry_parcel(api)

    ward_seven = fixtures.inventory_summary(api, situs_ward=7, headers=INV_1)

    # Two of the three acquired parcels sit in ward 7, for 9,000 of the 14,000
    # square feet; the 20,000-square-foot ward 7 prospect is still not counted.
    assert ward_seven["inventory_property_count"] == 2
    assert ward_seven["inventory_area_sqft"] == 9000
    assert ward_seven["conveyed_area_sqft"] == 0
    assert ward_seven["cure_pending_count"] == 0

    assert ward_seven["total_authorized_cents"] == 1000000
    assert ward_seven["total_committed_cents"] == 0
    assert ward_seven["total_disbursed_cents"] == 9000
    assert ward_seven["total_available_cents"] == 991000
    assert ward_seven["total_authorized_cents"] == (
        ward_seven["total_available_cents"]
        + ward_seven["total_committed_cents"]
        + ward_seven["total_disbursed_cents"]
    )


# ── the packet as a link between a parcel and a budget ──────────────────────
def test_an_unknown_budget_in_the_packet_body_names_the_funding_source(api):
    """
    Opening a packet against a real parcel but an unknown funding source is
    refused for the funding source the body could not resolve.

    References carried in a request body are resolved the same way and produce the same codes: `property_id` and `adjacent_property_id` resolve to a parcel (`ERR_PROPERTY_NOT_FOUND`), `applicant_id` to an applicant (`ERR_APPLICANT_NOT_FOUND`), `contractor_id` to a contractor (`ERR_CONTRACTOR_NOT_FOUND`), `funding_source_id` to a funding source (`ERR_FUNDING_SOURCE_NOT_FOUND`) and `application_id` to a disposition application (`ERR_APPLICATION_NOT_FOUND`).

    Design: Corner/endpoints/packet_creation_links_property_and_funding_source_both_ways
    """
    parcel = fixtures.create_property(
        api,
        address="3240 Zelkova Ln",
        situs_ward=5,
        lot_area_sqft=6000,
        assessed_value_cents=250000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=3,
    )
    payload = factories.acquisition_packet_payload(
        parcel["id"], NON_EXISTENT_UUID, donor_name="Zelkova Trust"
    )

    response = api.create_acquisition_packet(payload, INTAKE_1)

    validate_error(response, ApiErrorId.FUNDING_SOURCE_NOT_FOUND.value, 404)

    packets, meta = validate_paginated(api.list_acquisition_packets(CLERK_1))
    assert meta["total_count"] == 0
    assert packets == []


def test_the_packet_is_reachable_from_either_end_of_the_link(api):
    """
    Once the packet exists it answers both a query by its parcel and a query by
    its funding source, and neither query returns the packet drawn on the other
    parcel and budget.

    Parcels may be filtered by `custody_status`, `title_status`, `situs_ward` and `owner_of_record_applicant_id`; acquisition packets by `property_id`, `funding_source_id` and `status`; title actions by `status`; maintenance orders by `property_id`, `contractor_id`, `funding_source_id`, `demolition_run_id`, `status` and `work_type`; demolition runs by `status`; disposition applications by `property_id`, `applicant_id`, `status` and `program`; eligibility screenings by `outcome`; development agreements by `application_id`, `property_id` and `status`; and the authority-wide summary read by `situs_ward`.

    Design: Corner/endpoints/packet_creation_links_property_and_funding_source_both_ways
    """
    linked_source = fixtures.create_funding_source(
        api,
        name="Link Line",
        source_type="GRANT",
        authorized_cents=900000,
        restriction="ACQUISITION_ONLY",
        expires_on="2029-12-31T00:00:00Z",
    )
    other_source = fixtures.create_funding_source(
        api,
        name="Unrelated Link Line",
        source_type="GRANT",
        authorized_cents=900000,
        restriction="ACQUISITION_ONLY",
        expires_on="2029-12-31T00:00:00Z",
    )
    linked_parcel = fixtures.create_property(
        api,
        address="3240 Zelkova Ln",
        situs_ward=5,
        lot_area_sqft=6000,
        assessed_value_cents=250000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=3,
    )
    other_parcel = fixtures.create_property(
        api,
        address="3241 Zelkova Ln",
        situs_ward=5,
        lot_area_sqft=6000,
        assessed_value_cents=250000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=3,
    )

    packet = validate_success(
        api.create_acquisition_packet(
            factories.acquisition_packet_payload(
                linked_parcel["id"], linked_source["id"], donor_name="Zelkova Trust"
            ),
            INTAKE_1,
        ),
        201,
    )
    other_packet = fixtures.open_packet(
        api, other_parcel["id"], other_source["id"], donor_name="Unrelated Trust"
    )

    by_parcel, parcel_meta = validate_paginated(
        api.list_acquisition_packets(CLERK_1, {"property_id": linked_parcel["id"]})
    )
    assert parcel_meta["total_count"] == 1
    assert [row["id"] for row in by_parcel] == [packet["id"]]

    by_source, source_meta = validate_paginated(
        api.list_acquisition_packets(CLERK_1, {"funding_source_id": linked_source["id"]})
    )
    assert source_meta["total_count"] == 1
    assert [row["id"] for row in by_source] == [packet["id"]]

    # The unrelated packet is real, and both queries exclude it.
    assert other_packet["id"] != packet["id"]
    everything, all_meta = validate_paginated(api.list_acquisition_packets(CLERK_1))
    assert all_meta["total_count"] == 2
    assert {row["id"] for row in everything} == {packet["id"], other_packet["id"]}


# ── nested collections in their own declared order ─────────────────────────
def test_title_actions_on_a_parcel_come_oldest_first(api):
    """
    The title actions of a parcel are listed oldest first, and a status filter
    keeps only the round whose status matches.

    Four lists declare their own order: title actions on a parcel come oldest first, reuse hearings on a parcel come newest `hearing_at` first, the demolition runs drawn against a funding source come in ascending `run_sequence`, and the eligibility screenings of an application come in ascending `sequence_no`.

    Design: Corner/endpoints/nested_collections_list_oldest_first_with_status_filters
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Nested List Acquisition Line",
        source_type="GENERAL_FUND",
        authorized_cents=900000,
        restriction="ACQUISITION_ONLY",
        expires_on="2029-12-31T00:00:00Z",
    )
    parcel = fixtures.create_property(
        api,
        address="3250 Alder Row",
        situs_ward=9,
        lot_area_sqft=6000,
        assessed_value_cents=250000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=3,
    )
    fixtures.acquire_property(
        api, parcel["id"], funding_source["id"], donor_name="Alder Row Trust"
    )

    fixtures.set_clock(api, "2026-08-02T00:00:00Z")
    first_round = fixtures.open_title_action(api, parcel["id"], "QUIET_TITLE_SUIT")
    fixtures.adjudicate_title_action(api, first_round["id"], "DEFECT_REMAINS", 2)

    fixtures.set_clock(api, "2026-08-03T00:00:00Z")
    second_round = fixtures.open_title_action(api, parcel["id"], "LIEN_RELEASE")
    fixtures.adjudicate_title_action(api, second_round["id"], "CLEARED")

    assert_title_action(first_round)
    assert_title_action(second_round)
    assert first_round["round_no"] == 1
    assert second_round["round_no"] == 2

    actions, meta = validate_paginated(api.list_title_actions(parcel["id"], TREAS_1))
    assert meta["total_count"] == 2
    assert [row["id"] for row in actions] == [first_round["id"], second_round["id"]]
    assert actions[0]["round_no"] == 1
    assert actions[1]["round_no"] == 2

    cleared, cleared_meta = validate_paginated(
        api.list_title_actions(parcel["id"], INTAKE_1, {"status": "CLEARED"})
    )
    assert cleared_meta["total_count"] == 1
    assert [row["id"] for row in cleared] == [second_round["id"]]


def test_demolition_runs_on_a_source_come_in_ascending_run_sequence(api):
    """
    The demolition runs drawn against one funding source are listed in ascending
    run sequence, and a run drawn on another source is not among them.

    Four lists declare their own order: title actions on a parcel come oldest first, reuse hearings on a parcel come newest `hearing_at` first, the demolition runs drawn against a funding source come in ascending `run_sequence`, and the eligibility screenings of an application come in ascending `sequence_no`.

    Design: Corner/endpoints/nested_collections_list_oldest_first_with_status_filters
    """
    demolition_source = fixtures.create_funding_source(
        api,
        name="Nested List Demolition Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="DEMOLITION_ONLY",
        expires_on="2029-12-31T00:00:00Z",
    )
    other_source = fixtures.create_funding_source(
        api,
        name="Unrelated Demolition Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="DEMOLITION_ONLY",
        expires_on="2029-12-31T00:00:00Z",
    )

    # No parcel is registered at all, so every candidate pool is empty and each
    # run is created in PLANNED with nothing committed.
    first_run = fixtures.plan_demolition_run(api, demolition_source["id"], 400000)
    second_run = fixtures.plan_demolition_run(api, demolition_source["id"], 300000)
    other_run = fixtures.plan_demolition_run(api, other_source["id"], 200000)

    assert_demolition_run(first_run)
    assert_demolition_run(second_run)
    assert first_run["run_sequence"] == 1
    assert second_run["run_sequence"] == 2
    assert other_run["run_sequence"] == 1
    assert first_run["status"] == "PLANNED"
    assert first_run["properties_selected_count"] == 0

    runs, meta = validate_paginated(
        api.list_funding_source_demolition_runs(demolition_source["id"], TREAS_1)
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in runs] == [first_run["id"], second_run["id"]]
    assert [row["run_sequence"] for row in runs] == [1, 2]
    assert other_run["id"] not in {row["id"] for row in runs}

    last_page, page_meta = validate_paginated(
        api.list_funding_source_demolition_runs(
            demolition_source["id"], INV_1, {"limit": 1, "offset": 1}
        )
    )
    assert page_meta["total_count"] == 2
    assert page_meta["has_more"] is False
    assert [row["id"] for row in last_page] == [second_run["id"]]
