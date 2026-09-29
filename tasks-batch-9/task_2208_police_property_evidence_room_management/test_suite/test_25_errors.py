"""Error triggerability: header gates, custodian identity, missing references,
scoped uniqueness and the fiscal disbursement rule."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    adjudicate_case,
    case_payload,
    charge_case,
    disburse_payload,
    disposition_order_payload,
    evidence_item_payload,
    execute_order,
    log_and_store_item,
    make_evidence_technician_headers,
    offense_statute_payload,
    read_location,
    read_room,
    scan_payload,
    set_clock,
    setup_corner_base,
    setup_second_room,
    setup_started_audit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestUserContextHeaderGate:
    """The first stage of the validation order: both headers present and non-empty."""

    def test_request_without_user_headers_rejected(self, api):
        """A request carrying no user headers fails before any other rule is consulted.

        PRD 2.1: "Every request to the API must carry two headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, naming the role that
        principal is acting in."
        PRD 2.1: "If either header is absent or empty, the request is rejected with
        `ERR_MISSING_USER_CONTEXT` (HTTP 400)."
        PRD 2.10: "When a request could fail several checks at once, exactly one error is
        reported, and which one is determined by a fixed global priority."
        PRD 2.10: "Presence and non-emptiness of `X-User-Role` and `X-User-ID` —
        `ERR_MISSING_USER_CONTEXT` (400), on every endpoint."

        Design: Corner/errors/request_without_user_headers_rejected
        """
        env = setup_corner_base()

        headerless = api.get_property_room(env["room_id"], {})
        validate_error(headerless, ApiErrorId.ERR_MISSING_USER_CONTEXT, 400)

        empty_role = api.get_property_room(
            env["room_id"], {"X-User-ID": "op-1", "X-User-Role": ""}
        )
        validate_error(empty_role, ApiErrorId.ERR_MISSING_USER_CONTEXT, 400)

        missing_user_id = api.get_property_room(
            env["room_id"], {"X-User-Role": "PropertyRoomManager"}
        )
        validate_error(missing_user_id, ApiErrorId.ERR_MISSING_USER_CONTEXT, 400)

        # The header gate outranks request-shape validation, so an unusable body does
        # not change which single error is reported.
        headerless_intake = api.create_evidence_item(
            {"case_id": env["case1_id"], "category": "NOT_A_CATEGORY"}, {}
        )
        validate_error(headerless_intake, ApiErrorId.ERR_MISSING_USER_CONTEXT, 400)


class TestUnknownRoleGate:
    """The second stage: the acting role must be one of the six declared roles."""

    def test_request_with_unknown_role_rejected(self, api):
        """An unrecognised role string is an authentication failure, not a 403.

        PRD 2.1: "If `X-User-Role` is present but is not one of the six roles below, the
        request is rejected with `ERR_INVALID_ROLE` (HTTP 401)."
        PRD 2.1: "If the role is recognized but is not among the roles authorized for the
        requested endpoint (see the table in §4), the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD 2.10: "`X-User-Role` is one of the six declared roles — `ERR_INVALID_ROLE`
        (401), on every endpoint."

        Design: Corner/errors/request_with_unknown_role_rejected
        """
        env = setup_corner_base()

        unknown_role = api.get_property_room(
            env["room_id"], {"X-User-ID": "anybody", "X-User-Role": "PropertyClerk"}
        )
        validate_error(unknown_role, ApiErrorId.ERR_INVALID_ROLE, 401)

        # The role string is compared exactly, so a case variant is not recognised.
        lowercased_role = api.get_property_room(
            env["room_id"],
            {"X-User-ID": "anybody", "X-User-Role": "propertyroommanager"},
        )
        validate_error(lowercased_role, ApiErrorId.ERR_INVALID_ROLE, 401)


class TestEntityBackedCustodianIdentity:
    """The fourth stage: an entity-backed role must resolve to a matching custodian."""

    def test_custodian_role_type_mismatch_rejected(self, api):
        """Acting as a technician with a laboratory custodian's id is refused.

        PRD 2.1: "When `X-User-Role` is `EvidenceTechnician`, `Investigator`,
        `LabAnalyst` or `InternalAuditor`, `X-User-ID` is the `id` of the acting
        `Custodian` row, and that row's `role_type` must correspond to the acting role:
        `EvidenceTechnician` requires `role_type` of `EVIDENCE_TECH`, `Investigator`
        requires `INVESTIGATOR`, `LabAnalyst` requires `LAB_ANALYST`, and
        `InternalAuditor` requires `AUDITOR`."
        PRD 2.1: "If `X-User-ID` does not resolve to a `Custodian`, or resolves to one
        whose `role_type` does not correspond, the request is rejected with
        `ERR_CUSTODIAN_ROLE_MISMATCH` (HTTP 403)."
        PRD 2.10: "For entity-backed roles, `X-User-ID` resolves to a `Custodian` with
        the corresponding `role_type`, and `auditor_id` / `requested_by_custodian_id`
        equal `X-User-ID` where those fields are supplied —
        `ERR_CUSTODIAN_ROLE_MISMATCH` (403)."

        Design: Corner/errors/custodian_role_type_mismatch_rejected
        """
        env = setup_corner_base()
        payload = evidence_item_payload(
            env["case1_id"],
            item_description="Intake by the wrong custodian",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=100,
            seized_at="2026-07-31T12:00:00Z",
        )

        # L-200 is a LAB_ANALYST custodian, so it cannot act as an EvidenceTechnician.
        mismatch = api.create_evidence_item(
            payload, make_evidence_technician_headers(env["lab_id"])
        )
        validate_error(mismatch, ApiErrorId.ERR_CUSTODIAN_ROLE_MISMATCH, 403)

        # The same error covers an id that resolves to no custodian at all.
        unknown = api.create_evidence_item(
            payload, make_evidence_technician_headers(NON_EXISTENT_UUID)
        )
        validate_error(unknown, ApiErrorId.ERR_CUSTODIAN_ROLE_MISMATCH, 403)

        rows, meta = validate_paginated(api.list_evidence_items(env["manager"]))
        assert meta["total_count"] == 0
        assert rows == []


class TestAuditScanBarcodeResolution:
    """The seventh stage: a scanned barcode must resolve to an evidence item."""

    def test_scan_unknown_barcode_not_found(self, api):
        """A well-formed but unassigned barcode is a 404 that leaves the session alone.

        PRD 3.8: "The auditor submits a `barcode`; if it matches no evidence item the
        scan is refused with `ERR_BARCODE_NOT_FOUND`, and if the matched item belongs to
        a case of a different property room than the audited location the scan is refused
        with `ERR_BARCODE_FOREIGN_ROOM`."
        PRD 3.8: "A valid scan appends the item's identifier to
        `scanned_evidence_item_ids`, increments `scanned_item_count`, and appends a chain
        entry with `event_type` of `AUDIT_SCAN`."
        PRD 2.10: "Every identifier field in the request body resolves, in the endpoint's
        declared input order — the resource-specific 404 codes; a scanned `barcode` that
        matches no evidence item yields `ERR_BARCODE_NOT_FOUND` (404)."

        Design: Corner/errors/scan_unknown_barcode_not_found
        """
        env = setup_corner_base()
        location = read_location(env, env["loc_g9_id"])
        session = setup_started_audit(
            env,
            env["loc_g9_id"],
            location["version"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T17:00:00Z",
        )

        response = api.scan_audit_session(
            session["id"], scan_payload("CPD-26-00001-0009-9"), env["aud_headers"]
        )

        validate_error(response, ApiErrorId.ERR_BARCODE_NOT_FOUND, 404)
        after = validate_success(
            api.get_audit_session(session["id"], env["aud_headers"]), 200
        )
        assert after["status"] == "IN_PROGRESS"
        assert after["scanned_item_count"] == 0
        assert after["scanned_evidence_item_ids"] == []


class TestScopedUniqueness:
    """The fifteenth stage: case numbers are unique per room, offense codes globally."""

    def test_duplicate_case_number_rejected(self, api):
        """A case number may repeat across rooms but never inside one.

        PRD 3.1: "Opening a case requires the `property_room_id`, the
        `offense_statute_id` whose retention and destruction rules will govern its
        evidence, and a `case_number` matching exactly two digits, a hyphen, and five
        digits — for example `26-00001` — that must be unique within the room, failing
        which the request is refused with `ERR_DUPLICATE_CASE_NUMBER`."
        PRD 3.1: "Each statute carries an `offense_code` of 1 to 16 characters, unique
        across all statutes (a collision yields `ERR_DUPLICATE_OFFENSE_CODE`), a
        free-text `description`, and a `preservation_class` of `STANDARD`,
        `DRUG_SCHEDULE`, `BIOLOGICAL_INDEFINITE` or `HOMICIDE_PERMANENT`."
        PRD 2.10: "Scoped uniqueness — `ERR_DUPLICATE_AGENCY_CODE`,
        `ERR_DUPLICATE_OFFENSE_CODE`, `ERR_DUPLICATE_LOCATION_CODE`,
        `ERR_DUPLICATE_BADGE_NUMBER` or `ERR_DUPLICATE_CASE_NUMBER` (all 409), on
        property-room, offense-statute, storage-location, custodian and case creation
        respectively."
        PRD 2.4: "Cases may be filtered by `property_room_id`, `offense_statute_id` and
        `status`."

        Design: Corner/errors/duplicate_case_number_rejected
        """
        env = setup_corner_base()
        second = setup_second_room(env)

        duplicate = api.create_case(
            case_payload(env["room_id"], env["th3_id"], case_number="26-00001"),
            env["manager"],
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CASE_NUMBER, 409)

        # Uniqueness is scoped per room, so the second room may hold its own 26-00001.
        other_room_case = validate_success(
            api.create_case(
                case_payload(second["room_id"], env["th3_id"], case_number="26-00001"),
                env["manager"],
            ),
            201,
        )
        assert other_room_case["case_number"] == "26-00001"
        assert other_room_case["property_room_id"] == second["room_id"]

        # An offense code, by contrast, is unique across all statutes.
        duplicate_statute = api.create_offense_statute(
            offense_statute_payload(
                offense_code="TH-3",
                description="Duplicate statute code",
                preservation_class="STANDARD",
                statutory_retention_days=100,
                appeal_window_days=10,
                destruction_requires_court_order=False,
            ),
            env["manager"],
        )
        validate_error(duplicate_statute, ApiErrorId.ERR_DUPLICATE_OFFENSE_CODE, 409)

        rows, meta = validate_paginated(
            api.list_cases(env["manager"], params={"property_room_id": env["room_id"]})
        )
        assert meta["total_count"] == 3
        assert sorted(row["case_number"] for row in rows) == [
            "26-00001",
            "26-00002",
            "26-00003",
        ]


class TestDisbursementRequiresHeldProceeds:
    """The thirty-first stage: only an order holding proceeds may be disbursed."""

    def test_disburse_without_held_proceeds_rejected(self, api):
        """A destruction settles with nothing held, so disbursement is a fiscal refusal.

        PRD 3.7: "Non-auction dispositions have nothing to sell, so execution settles
        them immediately: an order whose `type` is `RETURN_TO_OWNER`, `DESTRUCTION` or
        `CONVERSION` continues `EXECUTED → SETTLED` inside the same request with
        `settled_net_proceeds_cents` of 0, `settlement_status` of `NONE`, and
        `settled_at` stamped from the logical clock."
        PRD 3.7: "That `SETTLED` position is a resting place rather than an ending:
        because `settlement_status` is `NONE` rather than `HELD`, any attempt to disburse
        such an order is refused with `ERR_NO_PROCEEDS_HELD`."
        PRD 3.7: "Disbursement is permitted only while `settlement_status` is `HELD`;
        otherwise it is refused with `ERR_NO_PROCEEDS_HELD`."
        PRD 2.7: "`PropertyRoom.escrow_balance_cents` equals the sum of
        `settled_net_proceeds_cents` across every disposition order whose
        `settlement_status` is `HELD` and whose evidence item belongs to a case of that
        room."
        PRD 2.10: "Disbursement requires held proceeds — `ERR_NO_PROCEEDS_HELD` (409), on
        disbursement."

        Design: Corner/errors/disburse_without_held_proceeds_rejected
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Broken bicycle for destruction",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=40000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        # Statute AB-1 carries 0 statutory and 0 appeal days, so the FINAL variant
        # falls back on the floor of intake plus 90 days, that is 2026-10-30.
        set_clock("2026-10-30T00:00:00Z")
        adjudicate_case(env, env["case2_id"])
        order = validate_success(
            api.create_disposition_order(
                disposition_order_payload(item["id"], "DESTRUCTION", env["tech_id"]),
                env["tech_headers"],
            ),
            201,
        )

        executed = execute_order(env, order["id"], env["tech2_id"], env["aud_id"])
        assert executed["status"] == "SETTLED"
        assert executed["settlement_status"] == "NONE"
        assert executed["settled_net_proceeds_cents"] == 0

        response = api.disburse_order(
            order["id"], disburse_payload("GL-2026-9001"), env["manager"]
        )

        validate_error(response, ApiErrorId.ERR_NO_PROCEEDS_HELD, 409)
        assert read_room(env)["escrow_balance_cents"] == 0
        final = validate_success(
            api.get_disposition_order(order["id"], env["manager"]), 200
        )
        assert final["status"] == "SETTLED"
        assert final["settlement_status"] == "NONE"
        assert final["payee_reference"] is None
