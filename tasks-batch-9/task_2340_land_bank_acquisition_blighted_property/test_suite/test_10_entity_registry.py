"""
Parcel registry and contractor registration.

Each test builds every row it needs through the API's own endpoints, starting
from an empty database at the logical clock's fixed default instant.
"""

from test_helpers import (
    CLERK_1,
    INTAKE_1,
    INTAKE_2,
    INTAKE_OFFICER_2,
    INV_1,
    NON_EXISTENT_UUID,
    assert_contractor,
    assert_funding_source,
    assert_ledger_position,
    assert_property,
    assert_score,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

REGISTRY_PARCEL = {
    "parcel_id": "APN-200001",
    "address": "1 Alder St",
    "situs_ward": 3,
    "lot_area_sqft": 6400,
    "assessed_value_cents": 420000,
    "structure_present": True,
    "structure_condition_grade": "D",
    "vacancy_months": 14,
}


def test_property_create_opens_in_prospect_custody_and_clouded_title(api):
    """
    Registering a parcel returns 201 with custody PROSPECT, title CLOUDED and
    every submitted intake field stored as supplied.

    "A newly registered parcel enters custody `PROSPECT` and title `CLOUDED`."
    Design: Corner/entities/property_create_returns_prospect_registry_row
    """
    response = api.create_property(
        factories.property_payload(**REGISTRY_PARCEL), INTAKE_1
    )

    parcel = validate_success(response, 201)
    assert_property(parcel)
    assert parcel["custody_status"] == "PROSPECT"
    assert parcel["title_status"] == "CLOUDED"
    # The registry entry precedes any acquisition, so the physical picture of
    # the parcel is exactly what intake supplied.
    assert parcel["parcel_id"] == "APN-200001"
    assert parcel["address"] == "1 Alder St"
    assert parcel["situs_ward"] == 3
    assert parcel["lot_area_sqft"] == 6400
    assert parcel["assessed_value_cents"] == 420000
    assert parcel["structure_present"] is True
    assert parcel["structure_condition_grade"] == "D"
    assert parcel["vacancy_months"] == 14


def test_property_create_zeroes_counters_and_nulls_acquisition_fields(api):
    """
    A freshly registered parcel carries a false secured flag, zero counters and
    a zero blight score, and leaves every acquisition and milestone field null.

    "Its `secured` flag is false; its `nuisance_complaint_count`, `open_code_violation_count`, `delinquent_tax_balance_cents`, `pre_acquisition_delinquency_cents` and `acquisition_cost_cents` are all zero; its `current_blight_score` is zero; and `intake_blight_score`, `acquisition_channel`, `acquired_at`, `last_mow_at`, `demolished_at`, `listed_at` and `owner_of_record_applicant_id` are all null."
    Design: Corner/entities/property_create_returns_prospect_registry_row
    """
    response = api.create_property(
        factories.property_payload(**REGISTRY_PARCEL), INTAKE_1
    )

    parcel = validate_success(response, 201)
    assert_property(parcel)
    assert parcel["secured"] is False
    assert parcel["nuisance_complaint_count"] == 0
    assert parcel["open_code_violation_count"] == 0
    assert parcel["delinquent_tax_balance_cents"] == 0
    assert parcel["pre_acquisition_delinquency_cents"] == 0
    assert parcel["acquisition_cost_cents"] == 0
    assert_score(parcel["current_blight_score"], 0)
    # The provisional intake score is stamped only when an acquisition closes.
    for field in (
        "intake_blight_score",
        "acquisition_channel",
        "acquired_at",
        "last_mow_at",
        "demolished_at",
        "listed_at",
        "owner_of_record_applicant_id",
    ):
        assert parcel[field] is None, f"{field} must be null at registration"


def test_property_get_returns_posted_snapshot_and_recomputed_score(api):
    """
    A parcel read back after a code-enforcement snapshot shows the overwritten
    counts and the blight score recomputed from them, not a fresh computation
    of its own.

    "An `IntakeOfficer` posts the code-enforcement snapshot, supplying `open_code_violation_count` and `nuisance_complaint_count`, which overwrite the stored values outright; the parcel's `current_blight_score` is then recomputed, while `intake_blight_score` is never touched again."
    Design: Corner/entities/property_get_returns_stored_registry_fields
    """
    parcel = fixtures.create_property(
        api,
        parcel_id="APN-200002",
        address="2 Alder St",
        situs_ward=3,
        lot_area_sqft=6400,
        assessed_value_cents=420000,
        structure_present=True,
        structure_condition_grade="D",
        vacancy_months=14,
    )
    posted = fixtures.post_code_violations(
        api, parcel["id"], open_code_violation_count=1, nuisance_complaint_count=3
    )

    stored = validate_success(api.get_property(parcel["id"], CLERK_1))

    assert_property(stored)
    assert stored["open_code_violation_count"] == 1
    assert stored["nuisance_complaint_count"] == 3
    # 30 for a standing grade D structure, 14 months of vacancy at 0.25, three
    # complaints at 1.5 under the 12-point cap, one violation at 3 under the
    # 15-point cap, no inventory neighbours and no holding term while
    # acquired_at is null.
    assert_score(stored["current_blight_score"], 41.0)
    assert_score(stored["current_blight_score"], posted["current_blight_score"])
    assert stored["intake_blight_score"] is None
    assert stored["address"] == "2 Alder St"
    assert stored["situs_ward"] == 3
    assert stored["assessed_value_cents"] == 420000


def test_property_list_filters_by_ward_with_pagination_meta(api):
    """
    Listing parcels filtered by situs_ward returns only that ward's parcels, and
    limit, offset, total_count and has_more describe the filtered set.

    "Parcels may be filtered by `custody_status`, `title_status`, `situs_ward` and `owner_of_record_applicant_id`; acquisition packets by `property_id`, `funding_source_id` and `status`; title actions by `status`; maintenance orders by `property_id`, `contractor_id`, `funding_source_id`, `demolition_run_id`, `status` and `work_type`; demolition runs by `status`; disposition applications by `property_id`, `applicant_id`, `status` and `program`; eligibility screenings by `outcome`; development agreements by `application_id`, `property_id` and `status`; and the authority-wide summary read by `situs_ward`."
    Design: Corner/entities/property_list_filters_by_ward_and_paginates
    """
    ward_3 = [
        fixtures.create_property(
            api,
            parcel_id=parcel_id,
            address=address,
            situs_ward=3,
            lot_area_sqft=5000,
            assessed_value_cents=100000,
            structure_present=False,
            structure_condition_grade="C",
            vacancy_months=1,
        )
        for parcel_id, address in (
            ("APN-200010", "10 Birch St"),
            ("APN-200011", "11 Birch St"),
            ("APN-200012", "12 Birch St"),
        )
    ]
    ward_4 = fixtures.create_property(
        api,
        parcel_id="APN-200013",
        address="13 Cedar St",
        situs_ward=4,
        lot_area_sqft=5000,
        assessed_value_cents=100000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=1,
    )

    rows, meta = validate_paginated(
        api.list_properties(
            INV_1,
            {"custody_status": "PROSPECT", "situs_ward": 3, "limit": 2, "offset": 0},
        )
    )

    assert len(rows) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    returned_ids = [row["id"] for row in rows]
    assert ward_4["id"] not in returned_ids
    assert set(returned_ids) <= {parcel["id"] for parcel in ward_3}
    for row in rows:
        assert row["situs_ward"] == 3
        assert row["custody_status"] == "PROSPECT"


def test_property_list_returns_oldest_registration_first(api):
    """
    The parcel list has no order of its own, so its first page opens with the
    parcel registered earliest.

    "Unless a specific list states otherwise, records are returned sorted by `created_at` ascending."
    Design: Corner/entities/property_list_filters_by_ward_and_paginates
    """
    first = fixtures.create_property(
        api, parcel_id="APN-200014", address="14 Birch St", situs_ward=3
    )
    fixtures.create_property(
        api, parcel_id="APN-200015", address="15 Birch St", situs_ward=3
    )
    fixtures.create_property(
        api, parcel_id="APN-200016", address="16 Birch St", situs_ward=3
    )

    rows, meta = validate_paginated(
        api.list_properties(INV_1, {"situs_ward": 3, "limit": 2, "offset": 0})
    )

    assert meta["total_count"] == 3
    assert rows[0]["parcel_id"] == "APN-200014"
    assert rows[0]["id"] == first["id"]


def test_property_get_unknown_id_returns_property_not_found(api):
    """
    Reading a parcel id that matches no registry row is a 404 that names the
    parcel as the missing resource.

    "Identifiers in a request path are resolved strictly left to right, and the first one that matches no record ends the request with a 404 naming that resource: an unknown parcel yields `ERR_PROPERTY_NOT_FOUND`, an unknown acquisition packet `ERR_PACKET_NOT_FOUND`, an unknown title action `ERR_TITLE_ACTION_NOT_FOUND`, an unknown maintenance order `ERR_ORDER_NOT_FOUND`, an unknown demolition run `ERR_RUN_NOT_FOUND`, an unknown disposition application `ERR_APPLICATION_NOT_FOUND`, an unknown development agreement `ERR_AGREEMENT_NOT_FOUND`, an unknown applicant `ERR_APPLICANT_NOT_FOUND` and an unknown funding source `ERR_FUNDING_SOURCE_NOT_FOUND`."
    Design: Corner/entities/property_get_unknown_id_returns_not_found
    """
    response = api.get_property(NON_EXISTENT_UUID, INTAKE_1)

    validate_error(response, "ERR_PROPERTY_NOT_FOUND")


def test_property_create_without_lot_area_is_rejected_and_persists_nothing(api):
    """
    Registration without lot_area_sqft is a malformed request rather than a
    parcel with a defaulted area, and no registry row survives the attempt.

    "Request shape: required fields, enum membership, numeric ranges and the conditional-required pairings — `openings_count` present exactly when `work_type` is `SECURE`, `foreclosure_case_no` present exactly when `channel` is `TAX_FORECLOSURE`, `donor_name` present exactly when `channel` is `DONATION`, `offer_price_cents` exactly zero when `channel` is `DONATION`, `support_count` no greater than `comment_count`, `defect_count` at least 1 exactly when `outcome` is `DEFECT_REMAINS`, `limit` within 1 to 100 and `offset` not negative. All of these are `ERR_INVALID_REQUEST`."
    Design: Corner/entities/property_create_missing_lot_area_rejected
    """
    payload = factories.without(
        factories.property_payload(
            parcel_id="APN-200020",
            address="20 Dogwood St",
            situs_ward=3,
            assessed_value_cents=100000,
            structure_present=False,
            structure_condition_grade="C",
            vacancy_months=1,
        ),
        "lot_area_sqft",
    )

    response = api.create_property(payload, INTAKE_1)

    validate_error(response, "ERR_INVALID_REQUEST")
    rows, meta = validate_paginated(api.list_properties(INTAKE_1, {"limit": 100}))
    assert meta["total_count"] == 0
    assert all(row["parcel_id"] != "APN-200020" for row in rows)


def test_contractor_create_defaults_debarred_to_false(api):
    """
    A contractor registered without the debarred flag comes back usable, with
    debarred false.

    "The `debarred` flag may be supplied and defaults to false when omitted."
    Design: Corner/entities/contractor_create_defaults_debarred_to_false
    """
    payload = factories.without(
        factories.contractor_payload(
            name="Default Debarment Test Co",
            license_expires_on="2027-12-31T00:00:00Z",
            max_concurrent_crews=2,
            specialties=factories.specialties("MOW", "SECURE", "DEMOLITION"),
        ),
        "debarred",
    )

    contractor = validate_success(api.create_contractor(payload, INV_1), 201)

    assert_contractor(contractor)
    assert contractor["debarred"] is False
    assert contractor["max_concurrent_crews"] == 2
    assert contractor["specialties"] == ["MOW", "SECURE", "DEMOLITION"]


def _negotiated_purchase_packet(api, property_id, funding_source_id):
    """Open a negotiated-purchase packet, which carries no donor name."""
    payload = factories.without(
        factories.acquisition_packet_payload(
            property_id,
            funding_source_id,
            channel="NEGOTIATED_PURCHASE",
            offer_price_cents=20000,
            title_search_fee_cents=10000,
        ),
        "donor_name",
    )
    return validate_success(api.create_acquisition_packet(payload, INTAKE_1), 201)


def _acquisition_setup(api):
    """An acquisition-restricted budget, a PROSPECT parcel and an approved packet."""
    funding_source = fixtures.create_acquisition_funding_source(
        api, name="Acquisition Revolving Line", authorized_cents=500000
    )
    parcel = fixtures.create_property(
        api,
        parcel_id="APN-200030",
        address="30 Elder St",
        situs_ward=3,
        lot_area_sqft=5000,
        assessed_value_cents=200000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=2,
    )
    packet = _negotiated_purchase_packet(api, parcel["id"], funding_source["id"])
    approved = fixtures.board_approve_packet(api, packet["id"], "R-2026-301")
    assert approved["committed_cents"] == 30000
    return funding_source, parcel, packet


def test_property_acquisition_fields_are_stamped_when_the_packet_closes(api):
    """
    Closing an acquisition packet is what writes the parcel's acquisition
    channel, acquisition instant and acquisition cost and moves it into custody
    ACQUIRED.

    "The parcel must still be `PROSPECT`, and the close drives the custody transition `PROSPECT → ACQUIRED` together with the whole intake stamping: the parcel copies the packet's channel into `acquisition_channel`, records `acquired_at` at the current instant, sets `acquisition_cost_cents` to the packet's offer price plus title search fee, and freezes the parcel's current `delinquent_tax_balance_cents` into `pre_acquisition_delinquency_cents` — the only delinquency the board will ever be able to discharge."
    Design: Corner/entities/property_acquisition_fields_computed_at_packet_close
    """
    _, parcel, packet = _acquisition_setup(api)
    assert parcel["acquisition_channel"] is None
    assert parcel["acquired_at"] is None
    assert parcel["acquisition_cost_cents"] == 0

    # The officer who opened the file may not sign the deed into inventory.
    validate_success(
        api.close_packet(packet["id"], {"deed_reference": "BK-4500-PG-01"}, INTAKE_2)
    )

    acquired = validate_success(api.get_property(parcel["id"], INTAKE_1))
    assert_property(acquired)
    assert acquired["custody_status"] == "ACQUIRED"
    assert acquired["acquisition_channel"] == "NEGOTIATED_PURCHASE"
    assert acquired["acquisition_cost_cents"] == 30000
    # The clock has not been moved, so the close lands on its default instant.
    assert acquired["acquired_at"].startswith("2026-08-01T00:00:00")
    assert acquired["pre_acquisition_delinquency_cents"] == 0


def test_packet_close_swaps_commitment_into_disbursement(api):
    """
    Closing the packet records the closing officer and converts the committed
    cost into money spent, leaving the ledger identity intact.

    "The packet itself moves `BOARD_APPROVED → CLOSED`, records `closed_by_user_id`, and drops its `committed_cents` to zero as the commitment converts into money spent: the funding source's `disbursed_cents` grows by the offer price plus the title search fee, its `committed_cents` falls by exactly the same amount, and `available_cents` is recomputed — a swap that leaves the conserved ledger identity untouched."
    Design: Corner/entities/property_acquisition_fields_computed_at_packet_close
    """
    funding_source, _, packet = _acquisition_setup(api)

    closed = validate_success(
        api.close_packet(packet["id"], {"deed_reference": "BK-4500-PG-02"}, INTAKE_2)
    )

    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == INTAKE_OFFICER_2
    assert closed["committed_cents"] == 0
    ledger = validate_success(
        api.get_funding_source(funding_source["id"], CLERK_1)
    )
    assert_funding_source(ledger)
    assert_ledger_position(
        ledger,
        authorized_cents=500000,
        committed_cents=0,
        disbursed_cents=30000,
        available_cents=470000,
    )
