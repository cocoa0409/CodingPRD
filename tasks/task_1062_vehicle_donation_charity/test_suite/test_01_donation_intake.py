"""Taking in a donation: the offer record, its two axes, and screening."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_donation,
    assert_donor,
    cancel_as_donor,
    create_donation_payload,
    create_vehicle_payload,
    is_valid_uuid,
    new_charity,
    new_donation,
    new_donor,
    read_donation,
    read_donor,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import accept, read_charity

UNSTORED_UUID = "11111111-1111-4111-8111-111111111111"


class TestDonationRecord:
    def test_donation_create_opens_both_axes_with_declared_defaults(self, api, intake_agent_headers):
        """PRD §3.2: "The new donation opens on both axes at once: its disposition
        `status` is `PENDING_REVIEW` and its money-side `payout_status` is `PENDING`."
        PRD §3.2: "The payload may also set `pickup_required`, which defaults to true
        and means the program must tow the vehicle; setting it false signals that the
        donor will drive the car in themselves."
        PRD §3.2: "Recording the offer raises the donor's `donation_count` by one."

        Design: Corner/entities/corner_donation_create_returns_201_with_initial_axes_and_defaults
        """
        charity = new_charity()
        donor = new_donor()

        response = api.create_donation(
            create_donation_payload(donor["id"], charity["id"]), intake_agent_headers
        )
        donation = validate_success(response, 201)

        assert_donation(donation)
        assert donation["status"] == "PENDING_REVIEW"
        assert donation["payout_status"] == "PENDING"
        assert donation["pickup_required"] is True, "pickup_required defaults to true when omitted"
        assert donation["pickup_attempts"] == 0
        assert donation["exception_type"] == "NONE"
        assert donation["version"] == 1
        assert donation["gross_proceeds_cents"] == 0
        assert donation["fmv_estimate_cents"] is None
        assert donation["deduction_amount_cents"] is None

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]

        assert read_donor(donor["id"])["donation_count"] == 1

    def test_donation_read_returns_the_stored_offer(self, api, intake_agent_headers):
        """PRD §3.2: "A donation offer is recorded by an intake agent or a program
        administrator against a payload naming the `donor_id` and the beneficiary
        `charity_id`, the `intake_channel` through which the offer arrived (`WEB`,
        `PHONE`, or `PARTNER`), and the `declared_condition` the donor self-reports —
        one of `EXCELLENT`, `GOOD`, `FAIR`, `POOR`, or `SALVAGE`."

        Design: Corner/entities/corner_donation_get_by_id_returns_the_stored_row
        """
        charity = new_charity()
        donor = new_donor()
        created = new_donation(
            donor["id"],
            charity["id"],
            intake_channel="PHONE",
            declared_condition="FAIR",
            pickup_required=False,
        )

        fetched = validate_success(api.get_donation(created["id"], intake_agent_headers), 200)

        assert fetched["id"] == created["id"]
        assert fetched["donor_id"] == donor["id"]
        assert fetched["charity_id"] == charity["id"]
        assert fetched["intake_channel"] == "PHONE"
        assert fetched["declared_condition"] == "FAIR"
        assert fetched["pickup_required"] is False

    def test_donation_identifiers_and_version_are_server_minted(self, api, intake_agent_headers):
        """PRD §2.4: "Every stored record is addressed by `id`, a server-minted UUID
        string. Identifiers carry no type prefix — a donation id and a vehicle id are
        indistinguishable by shape, and clients must never parse them."
        PRD §2.4: "Most records additionally carry `updated_at`, refreshed on every
        mutation of that record and initially equal to `created_at`, and `version`, an
        integer that begins at 1 when the record is created and increases by exactly 1
        on every mutation of that record."

        Design: Corner/entities/corner_system_fields_are_server_minted_on_donation
        """
        charity = new_charity()
        donor = new_donor()
        donation = new_donation(donor["id"], charity["id"], pickup_required=False)

        assert is_valid_uuid(donation["id"]), "the id is a bare UUID with no type prefix"
        assert not donation["id"].startswith("don"), "identifiers carry no type prefix"
        assert donation["version"] == 1
        assert donation["updated_at"] >= donation["created_at"]

        accepted = validate_success(api.accept_donation(donation["id"], intake_agent_headers), 200)
        assert accepted["version"] == 2, "accept is a mutation, so version rises by exactly 1"
        assert accepted["updated_at"] >= accepted["created_at"]

    def test_donation_read_with_unstored_id_returns_donation_not_found(
        self, api, intake_agent_headers
    ):
        """PRD §2.8: "Every identifier embedded in the URL path resolves to a stored
        row, validated left to right. Applies to every path-parameterised endpoint. The
        rejection names the entity that failed to resolve: `ERR_DONOR_NOT_FOUND`,
        `ERR_CHARITY_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`,
        `ERR_TITLE_RECORD_NOT_FOUND`, `ERR_TOW_VENDOR_NOT_FOUND`,
        `ERR_PICKUP_ORDER_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_AUCTION_LOT_NOT_FOUND`,
        `ERR_TAX_RECEIPT_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, or `ERR_TASK_NOT_FOUND`, each
        HTTP 404."

        Design: Corner/entities/corner_donation_get_with_unknown_id_returns_not_found
        """
        new_charity()

        response = api.get_donation(UNSTORED_UUID, intake_agent_headers)

        validate_error(response, ApiErrorId.ERR_DONATION_NOT_FOUND.value)
        assert response.json()["response_type"] == "error"

    def test_donation_create_without_charity_id_is_a_malformed_request(
        self, api, intake_agent_headers
    ):
        """PRD §2.8: "Every required body field is present and of the declared type,
        enum members are legal values, integers required to be positive are positive, and
        pagination parameters are in range — otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/corner_donation_create_missing_required_field_returns_invalid_request
        """
        donor = new_donor()

        response = api.create_donation(
            {"donor_id": donor["id"], "intake_channel": "WEB", "declared_condition": "GOOD"},
            intake_agent_headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert read_donor(donor["id"])["donation_count"] == 0, "the refused offer stored nothing"

    def test_donation_create_rejects_an_intake_channel_outside_the_enum(
        self, api, intake_agent_headers
    ):
        """PRD §3.2: "A donation offer is recorded by an intake agent or a program
        administrator against a payload naming the `donor_id` and the beneficiary
        `charity_id`, the `intake_channel` through which the offer arrived (`WEB`,
        `PHONE`, or `PARTNER`), and the `declared_condition` the donor self-reports —
        one of `EXCELLENT`, `GOOD`, `FAIR`, `POOR`, or `SALVAGE`."
        PRD §2.8: "Every required body field is present and of the declared type, enum
        members are legal values, integers required to be positive are positive, and
        pagination parameters are in range — otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/corner_donation_rejects_unknown_intake_channel_enum
        """
        charity = new_charity()
        donor = new_donor()

        response = api.create_donation(
            create_donation_payload(donor["id"], charity["id"], intake_channel="FAX"),
            intake_agent_headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        rows, meta = validate_paginated(
            api.list_donations(intake_agent_headers, params={"donor_id": donor["id"]})
        )
        assert rows == [] and meta["total_count"] == 0

    def test_vehicle_create_against_an_unstored_donation_is_a_body_foreign_key_failure(
        self, api, intake_agent_headers
    ):
        """PRD §2.8: "Every foreign key supplied in the request body resolves to a stored
        row, reported with that entity's not-found code. This applies to donation
        creation, vehicle creation, title-record creation, pickup-order creation,
        auction-lot creation, tax-receipt creation, and remittance-batch creation."

        Design: Corner/entities/corner_vehicle_create_with_unknown_donation_returns_donation_not_found
        """
        new_charity()
        orphan_donation_id = "22222222-2222-4222-8222-222222222222"

        response = api.create_vehicle(
            create_vehicle_payload(orphan_donation_id, make="Kia", model="Soul"),
            intake_agent_headers,
        )

        validate_error(response, ApiErrorId.ERR_DONATION_NOT_FOUND.value)
        rows, _ = validate_paginated(
            api.list_vehicles(intake_agent_headers, params={"donation_id": orphan_donation_id})
        )
        assert rows == []


class TestDonationListing:
    def test_donation_listing_pages_with_total_count_and_has_more(self, api, intake_agent_headers):
        """PRD §2.3: "For list responses the `meta` object carries four pagination fields:
        `limit` (the effective page size applied), `offset` (the effective starting
        position), `total_count` (the number of records matching the filter before
        pagination is applied), and `has_more` (true when records remain beyond the
        current page)."

        Design: Corner/entities/corner_donations_list_paginates_with_total_count_and_has_more
        """
        charity = new_charity()
        donor = new_donor()
        for _ in range(3):
            new_donation(donor["id"], charity["id"])

        first_response = api.list_donations(
            intake_agent_headers, params={"donor_id": donor["id"], "limit": 2, "offset": 0}
        )
        first, first_meta = validate_paginated(first_response)
        assert len(first) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_response.json()["response_type"] == "array"

        second_response = api.list_donations(
            intake_agent_headers, params={"donor_id": donor["id"], "limit": 2, "offset": 2}
        )
        second, second_meta = validate_paginated(second_response)
        assert len(second) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_response.json()["response_type"] == "array"

    def test_donation_listing_combines_a_status_filter_with_pagination(
        self, api, intake_agent_headers
    ):
        """PRD §3.2: "Donations are readable individually by every role, and listable
        with any combination of `donor_id`, `charity_id`, `status`, and `payout_status`
        filters."
        PRD §2.3: "A `limit` outside the range from 1 to 100 inclusive, or a negative
        `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/cross_cutting_layers/corner_donations_list_combines_status_filter_with_pagination
        """
        charity = new_charity()
        donor = new_donor()
        first = new_donation(donor["id"], charity["id"], pickup_required=False)
        accept(first["id"])
        second = new_donation(donor["id"], charity["id"], pickup_required=False)
        accept(second["id"])
        pending = new_donation(donor["id"], charity["id"], pickup_required=False)

        accepted_rows, accepted_meta = validate_paginated(
            api.list_donations(
                intake_agent_headers,
                params={"donor_id": donor["id"], "status": "ACCEPTED", "limit": 1, "offset": 0},
            )
        )
        assert len(accepted_rows) == 1
        assert accepted_meta["total_count"] == 2
        assert accepted_meta["has_more"] is True

        pending_rows, pending_meta = validate_paginated(
            api.list_donations(
                intake_agent_headers,
                params={
                    "donor_id": donor["id"],
                    "status": "PENDING_REVIEW",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert [row["id"] for row in pending_rows] == [pending["id"]]
        assert pending_meta["total_count"] == 1
        assert pending_meta["has_more"] is False

        over_limit = api.list_donations(
            intake_agent_headers, params={"donor_id": donor["id"], "limit": 200, "offset": 0}
        )
        validate_error(over_limit, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestScreening:
    def test_accept_moves_a_pending_offer_into_the_program(self, api, intake_agent_headers):
        """PRD §3.2: "An intake agent **accepts** an offer that is still
        `PENDING_REVIEW`, moving it `PENDING_REVIEW → ACCEPTED`; acceptance is refused if
        the donor is not `ACTIVE` or the beneficiary affiliate is not `ACTIVE`."

        Design: Corner/state_machines/corner_accept_moves_donation_from_pending_review_to_accepted
        """
        charity = new_charity()
        donor = new_donor()
        donation = new_donation(donor["id"], charity["id"], pickup_required=False)

        accepted = validate_success(api.accept_donation(donation["id"], intake_agent_headers), 200)

        assert accepted["status"] == "ACCEPTED"
        assert accepted["payout_status"] == "PENDING", "the money axis does not move on acceptance"
        assert accepted["version"] == 2

    def test_accept_on_a_declined_offer_is_refused(self, api, intake_agent_headers):
        """PRD §3.2: "Both acceptance and decline are refused with
        `ERR_INVALID_DONATION_STATE` from any other disposition."
        PRD §3.2: "The disposition axis ranges over `PENDING_REVIEW`, `ACCEPTED`,
        `PICKUP_BLOCKED`, `IN_CUSTODY`, `SOLD`, `UNSOLD`, `CLOSED`, `DECLINED`, and
        `CANCELLED`, of which `CLOSED`, `DECLINED`, and `CANCELLED` are terminal."

        Design: Corner/state_machines/corner_accept_on_declined_donation_returns_invalid_donation_state
        """
        charity = new_charity()
        donor = new_donor()
        donation = new_donation(
            donor["id"], charity["id"], declared_condition="POOR", pickup_required=False
        )
        validate_success(
            api.decline_donation(
                donation["id"], {"reason": "vehicle beyond salvage value"}, intake_agent_headers
            ),
            200,
        )

        response = api.accept_donation(donation["id"], intake_agent_headers)

        validate_error(response, ApiErrorId.ERR_INVALID_DONATION_STATE.value)
        after = read_donation(donation["id"])
        assert after["status"] == "DECLINED"
        assert after["payout_status"] == "WITHHELD"

    def test_second_accept_on_an_accepted_offer_is_refused_and_does_not_bump_version(
        self, api, intake_agent_headers
    ):
        """PRD §3.2: "Both acceptance and decline are refused with
        `ERR_INVALID_DONATION_STATE` from any other disposition."
        PRD §2.4: "Most records additionally carry `updated_at`, refreshed on every
        mutation of that record and initially equal to `created_at`, and `version`, an
        integer that begins at 1 when the record is created and increases by exactly 1
        on every mutation of that record."

        Design: Corner/state_machines/corner_second_accept_on_accepted_donation_is_not_idempotent
        """
        charity = new_charity()
        donor = new_donor()
        donation = new_donation(donor["id"], charity["id"], pickup_required=False)
        accept(donation["id"])

        response = api.accept_donation(donation["id"], intake_agent_headers)

        validate_error(response, ApiErrorId.ERR_INVALID_DONATION_STATE.value)
        assert read_donation(donation["id"])["version"] == 2, "the refused call is not a mutation"

    def test_decline_drives_the_money_axis_to_withheld_without_journalling(self, api):
        """PRD §3.2: "An agent may instead **decline** the offer with a `reason`, moving
        it `PENDING_REVIEW → DECLINED` and simultaneously driving the money axis
        `PENDING → WITHHELD`."
        PRD §3.2: "Declining moves no money, because at that point
        `net_to_charity_cents` is still zero and there is nothing to reverse."

        Design: Corner/state_machines/corner_decline_side_effect_sets_payout_status_withheld
        """
        charity = new_charity()
        donor = new_donor()
        donation = new_donation(
            donor["id"],
            charity["id"],
            intake_channel="PARTNER",
            declared_condition="SALVAGE",
            pickup_required=False,
        )

        declined = validate_success(
            api.decline_donation(
                donation["id"],
                {"reason": "no title available"},
                TEST_USERS["intake_agent_headers"],
            ),
            200,
        )

        assert declined["status"] == "DECLINED"
        assert declined["payout_status"] == "WITHHELD"
        entries, meta = validate_paginated(
            api.list_donation_ledger_entries(
                donation["id"], TEST_USERS["finance_officer_headers"]
            )
        )
        assert entries == [] and meta["total_count"] == 0
        assert read_charity(charity["id"])["pledged_balance_cents"] == 0

    def test_cancel_is_locked_out_once_the_donation_is_cancelled(self, api):
        """PRD §3.2: "A **cancellation** — available to the donation's own donor, and
        also to a program administrator — carries a `reason` and is permitted while the
        donation is in either `PENDING_REVIEW` or `ACCEPTED`; it drives the donation to
        `CANCELLED`."
        PRD §3.2: "Cancellation lowers the donor's `donation_count` by one and releases
        logistics: every pickup order for that donation still sitting in `SCHEDULED` is
        cancelled, and each such cancellation lowers that vendor's `booked_slots_count`
        by one."

        Design: Corner/state_machines/corner_cancel_on_cancelled_donation_is_locked_out
        """
        charity = new_charity()
        donor = new_donor()
        donation = new_donation(donor["id"], charity["id"], pickup_required=False)
        validate_success(cancel_as_donor(donation["id"], donor["id"], "sold privately"), 200)

        response = cancel_as_donor(donation["id"], donor["id"], "sold privately again")

        validate_error(response, ApiErrorId.ERR_INVALID_DONATION_STATE.value)
        assert read_donation(donation["id"])["status"] == "CANCELLED"
        assert read_donor(donor["id"])["donation_count"] == 0, "the count is not decremented twice"


class TestCounterpartyStanding:
    def test_donation_create_for_a_blocked_donor_is_refused(self, api, intake_agent_headers,
                                                            program_admin_headers):
        """PRD §3.1: "An administrator may move a donor to `BLOCKED` by supplying a
        `reason`; a blocked donor may not have new donations recorded, and neither
        existing offers from that donor may be accepted — both paths report
        `ERR_DONOR_BLOCKED`."

        Design: Corner/validations/corner_donation_create_for_blocked_donor_returns_donor_blocked
        """
        charity = new_charity()
        donor = new_donor()
        validate_success(
            api.block_donor(
                donor["id"], {"reason": "repeated fraudulent submissions"}, program_admin_headers
            ),
            200,
        )

        response = api.create_donation(
            create_donation_payload(donor["id"], charity["id"]), intake_agent_headers
        )

        validate_error(response, ApiErrorId.ERR_DONOR_BLOCKED.value)
        blocked = read_donor(donor["id"])
        assert_donor(blocked)
        assert blocked["status"] == "BLOCKED"
        assert blocked["donation_count"] == 0

    def test_donation_create_for_a_suspended_affiliate_is_refused(
        self, api, intake_agent_headers, program_admin_headers
    ):
        """PRD §3.1: "An affiliate that misbehaves can be moved to `SUSPENDED`; a
        suspended affiliate may accept no new donations and no new batches, and any
        attempt reports `ERR_CHARITY_SUSPENDED`."

        Design: Corner/validations/corner_donation_create_for_suspended_charity_returns_charity_suspended
        """
        suspended = new_charity(name="Suspended Trust")
        validate_success(api.suspend_charity(suspended["id"], program_admin_headers), 200)
        active = new_charity(name="Active Trust")
        donor = new_donor()

        refused = api.create_donation(
            create_donation_payload(donor["id"], suspended["id"]), intake_agent_headers
        )
        validate_error(refused, ApiErrorId.ERR_CHARITY_SUSPENDED.value)
        assert read_charity(suspended["id"])["status"] == "SUSPENDED"

        accepted = validate_success(
            api.create_donation(
                create_donation_payload(donor["id"], active["id"]), intake_agent_headers
            ),
            201,
        )
        assert accepted["status"] == "PENDING_REVIEW"
        assert read_donor(donor["id"])["donation_count"] == 1
