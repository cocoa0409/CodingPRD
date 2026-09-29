"""Role authorization: exclusive operations, shared operations and segregation of duties."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    adjudicate_case,
    authorize_payload,
    case_payload,
    charge_case,
    execute_payload,
    log_and_store_item,
    open_order,
    read_item,
    reject_payload,
    release_payload,
    request_transfer,
    set_clock,
    setup_corner_base,
    storage_location_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCourtClerkExclusiveOperations:
    """The clerk's own operations and the shared operation it also holds."""

    def test_court_clerk_can_authorize_and_reject_disposition_orders(self, api):
        """Authorization, refusal and adjudication all succeed for a CourtClerk.

        Section 4 authorizes only the CourtClerk on the authorize and reject endpoints,
        and authorizes the CourtClerk alongside the PropertyRoomManager on adjudication.

        PRD 2.1: "**`CourtClerk`** — records adjudication, appeals and appeal resolution,
        and authorizes or refuses dispositions."
        PRD 2.1: "When `X-User-Role` is `PropertyRoomManager` or `CourtClerk`, `X-User-ID`
        is an opaque operator identifier that is not tied to any persisted entity; the
        server never compares it to any row's `id`."
        PRD 3.7: "When it does not hold, the order waits: a `CourtClerk` supplies a
        `court_order_number`, which moves the order `PENDING_COURT_AUTH → AUTHORIZED`,
        stamps `authorized_at`, and leaves `auto_authorized` false."
        PRD 3.7: "The same clerk may instead refuse the disposition, supplying a `reason`;
        refusal moves the order `PENDING_COURT_AUTH → REJECTED` without recording any
        `court_order_number`, returns the item's disposition dimension `ORDER_PENDING →
        RETAINED`, decrements the room's `disposal_eligible_count` and recomputes
        `posture` — the next nightly sweep will re-derive eligibility from scratch."
        PRD 3.4: "Adjudication, performed by a `CourtClerk` or a `PropertyRoomManager`,
        moves the case `CHARGED → ADJUDICATED`, stamps `adjudicated_at`, and then walks
        every evidence item of the case in ascending `created_at` order: for each item it
        creates a determination with a requested `basis` of `FINAL`, marks the prior
        determination superseded, rewrites the item's `retention_release_at` and
        `retention_basis`, appends a `RETENTION_SET` chain entry, and increments that
        item's `version` by 1."

        Design: Corner/rbac/court_clerk_can_authorize_and_reject_orders
        """
        env = setup_corner_base()
        gun1 = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_v_id"],
            item_description="Revolver to be destroyed",
            category="FIREARM",
            packaging_type="RIGID_BOX",
            appraised_value_cents=45000,
            seized_at="2026-07-30T09:00:00Z",
        )
        gun2 = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_v_id"],
            item_description="Shotgun contested by the court",
            category="FIREARM",
            packaging_type="RIGID_BOX",
            appraised_value_cents=46000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        set_clock("2026-10-30T00:00:00Z")

        adjudicated = adjudicate_case(env, env["case2_id"])
        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated["adjudicated_at"] == "2026-10-30T00:00:00.000Z"

        # A FIREARM can never be auto-authorized, so both orders wait for the court.
        order1 = open_order(env, gun1["id"], "DESTRUCTION")
        order2 = open_order(env, gun2["id"], "DESTRUCTION")
        assert order1["status"] == "PENDING_COURT_AUTH"
        assert order2["status"] == "PENDING_COURT_AUTH"

        authorized = validate_success(
            api.authorize_order(order1["id"], authorize_payload("CR-2026-4417"), env["clerk"]),
            200,
        )
        rejected = validate_success(
            api.reject_order(
                order2["id"],
                reject_payload("The firearm is subject to a pending forfeiture petition"),
                env["clerk"],
            ),
            200,
        )

        assert authorized["status"] == "AUTHORIZED"
        assert authorized["court_order_number"] == "CR-2026-4417"
        assert authorized["auto_authorized"] is False
        assert authorized["authorized_at"] == "2026-10-30T00:00:00.000Z"
        assert rejected["status"] == "REJECTED"
        assert rejected["court_order_number"] is None

        assert read_item(env, gun1["id"])["disposition_state"] == "ORDER_PENDING"
        assert read_item(env, gun2["id"])["disposition_state"] == "RETAINED"

    def test_case_creation_is_shared_by_the_manager_and_the_technician(self, api):
        """Both authorized roles may open a case; a third role is refused.

        Section 4 authorizes the PropertyRoomManager and the EvidenceTechnician on POST
        /cases, and the LabAnalyst is not among them.

        PRD 2.1: "If the role is recognized but is not among the roles authorized for the
        requested endpoint (see the table in §4), the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD 2.10: "The acting role is authorized for the endpoint —
        `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint."
        PRD 3.1: "A case opens in `OPEN` with `charged_at`, `adjudicated_at`,
        `appeal_opened_at` and `closed_at` all null and both `item_count` and
        `undisposed_item_count` at 0."

        Design: Corner/rbac/case_create_shared_operation_allowed_for_manager_and_technician
        """
        env = setup_corner_base()

        manager_case = validate_success(
            api.create_case(
                case_payload(env["room_id"], env["th3_id"], case_number="26-00101"),
                env["manager"],
            ),
            201,
        )
        technician_case = validate_success(
            api.create_case(
                case_payload(env["room_id"], env["th3_id"], case_number="26-00102"),
                env["tech_headers"],
            ),
            201,
        )
        validate_error(
            api.create_case(
                case_payload(env["room_id"], env["th3_id"], case_number="26-00103"),
                env["lab_headers"],
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )

        assert manager_case["status"] == "OPEN"
        assert manager_case["case_number"] == "26-00101"
        assert manager_case["item_count"] == 0
        assert manager_case["undisposed_item_count"] == 0
        assert technician_case["status"] == "OPEN"
        assert technician_case["case_number"] == "26-00102"

        rows, meta = validate_paginated(
            api.list_cases(env["manager"], params={"property_room_id": env["room_id"]})
        )
        # Three base cases plus the two just created; the analyst's case was refused.
        assert meta["total_count"] == 5
        assert "26-00103" not in [row["case_number"] for row in rows]


class TestForbiddenExclusiveOperations:
    """A role that is not listed for an endpoint is refused before anything else."""

    def test_evidence_technician_cannot_authorize_a_disposition_order(self, api):
        """Only the CourtClerk may authorize; technician and manager are both refused.

        Section 4 authorizes only the CourtClerk on the authorize endpoint, so neither the
        EvidenceTechnician who requested the order nor the PropertyRoomManager who will
        later execute it may record the court's authorization.

        PRD 2.1: "If the role is recognized but is not among the roles authorized for the
        requested endpoint (see the table in §4), the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD 2.10: "When a request could fail several checks at once, exactly one error is
        reported, and which one is determined by a fixed global priority."
        PRD 2.10: "The acting role is authorized for the endpoint —
        `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint."
        PRD 2.10: "The path-templated identifier resolves — the resource-specific 404
        named in §2.4, on every endpoint with a templated path segment."

        Design: Corner/rbac/evidence_technician_cannot_authorize_disposition_order
        """
        env = setup_corner_base()
        gun = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_v_id"],
            item_description="Revolver awaiting court authorization",
            category="FIREARM",
            packaging_type="RIGID_BOX",
            appraised_value_cents=45000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        set_clock("2026-10-30T00:00:00Z")
        adjudicate_case(env, env["case2_id"])
        order = open_order(env, gun["id"], "DESTRUCTION")
        assert order["status"] == "PENDING_COURT_AUTH"

        validate_error(
            api.authorize_order(
                order["id"], authorize_payload("CR-2026-9999"), env["tech_headers"]
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api.authorize_order(
                order["id"], authorize_payload("CR-2026-9999"), env["manager"]
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        # The role check sits above the path-identifier resolution in the fixed order.
        validate_error(
            api.authorize_order(
                NON_EXISTENT_UUID, authorize_payload("CR-2026-9999"), env["tech_headers"]
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )

        unchanged = validate_success(
            api.get_disposition_order(order["id"], env["manager"]), 200
        )
        assert unchanged["status"] == "PENDING_COURT_AUTH"
        assert unchanged["court_order_number"] is None
        assert unchanged["authorized_at"] is None

    def test_internal_auditor_cannot_release_a_custody_transfer(self, api):
        """Release is the technician's alone: neither auditor nor receiving analyst may.

        Section 4 authorizes only the EvidenceTechnician on the release endpoint, so the
        InternalAuditor who reads custody records and the LabAnalyst who will receive the
        item are both outside the authorized set.

        PRD 2.1: "If the role is recognized but is not among the roles authorized for the
        requested endpoint (see the table in §4), the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD 2.1: "**`InternalAuditor`** — schedules and conducts inventory audits, scans
        barcodes and reconciles a location."
        PRD 2.10: "The acting role is authorized for the endpoint —
        `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint."
        PRD 3.5: "Release is an `EvidenceTechnician` action and drives two state machines
        at once, moving the transfer `REQUESTED → RELEASED` and the item's custody
        dimension `STORED → CHECKED_OUT`."

        Design: Corner/rbac/internal_auditor_cannot_release_custody_transfer
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Swab awaiting laboratory release",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=100,
            seized_at="2026-07-31T12:00:00Z",
        )
        transfer = request_transfer(
            env,
            item["id"],
            env["lab_id"],
            "LAB_ANALYSIS",
            "2026-08-02T09:00:00Z",
            "2026-08-12T09:00:00Z",
            headers=env["lab_headers"],
        )
        assert transfer["status"] == "REQUESTED"

        validate_error(
            api.release_transfer(
                transfer["id"], release_payload("sig-auditor"), env["aud_headers"]
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api.release_transfer(
                transfer["id"], release_payload("sig-lab-self"), env["lab_headers"]
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )

        unchanged = validate_success(
            api.get_custody_transfer(transfer["id"], env["manager"]), 200
        )
        assert unchanged["status"] == "REQUESTED"
        assert unchanged["released_signature"] is None
        assert unchanged["from_custodian_id"] is None
        after = read_item(env, item["id"])
        assert after["custody_state"] == "STORED"
        assert after["current_holder_id"] is None

    def test_investigator_cannot_create_a_storage_location(self, api):
        """Room configuration belongs to the manager; the investigator is refused.

        Section 4 authorizes only the PropertyRoomManager on POST /storage-locations.

        PRD 2.1: "If the role is recognized but is not among the roles authorized for the
        requested endpoint (see the table in §4), the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD 2.1: "Configures the room, the offense statutes, the storage locations and the
        custodian roster; runs the nightly sweep; executes, settles and disburses
        dispositions; verifies owner claims; and adjudicates discrepancies."
        PRD 2.1: "Files charges and requests investigative-review transfers."
        PRD 2.10: "The acting role is authorized for the endpoint —
        `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint."

        Design: Corner/rbac/investigator_cannot_create_storage_location
        """
        env = setup_corner_base()
        body = storage_location_payload(
            env["room_id"], code="G-77", category="GENERAL", capacity_slots=5
        )
        _, before = validate_paginated(
            api.list_storage_locations(
                env["manager"], params={"property_room_id": env["room_id"]}
            )
        )

        validate_error(
            api.create_storage_location(body, env["inv_headers"]),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )

        rows, after = validate_paginated(
            api.list_storage_locations(
                env["manager"],
                params={"property_room_id": env["room_id"], "limit": 100},
            )
        )
        assert after["total_count"] == before["total_count"]
        assert "G-77" not in [row["code"] for row in rows]

        # The very same body is accepted from the authorized role, so only the role was wrong.
        created = validate_success(api.create_storage_location(body, env["manager"]), 201)
        assert created["code"] == "G-77"
        assert created["occupied_slots"] == 0
        assert created["status"] == "OPEN"


class TestSegregationOfDutiesAtExecution:
    """The two inequalities the service enforces when a disposition is executed."""

    def test_executor_may_not_be_the_requester_nor_the_witness(self, api):
        """Both limbs of the rule trip independently, and the witness may be the requester.

        PRD 2.11: "At disposition execution the service enforces two inequalities: the
        `executed_by_custodian_id` supplied at execution must differ from the
        `requested_by_custodian_id` recorded when the order was opened, and the
        `witness_custodian_id` must differ from the `executed_by_custodian_id`."
        PRD 2.11: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD 2.11: "Note that nothing forbids the witness from being the original requester
        — the constraint is only on the two pairs named."
        PRD 2.10: "Segregation of duties at execution — `ERR_SEGREGATION_OF_DUTIES` (409),
        on disposition execution."
        PRD 3.7: "Execution belongs solely to the `PropertyRoomManager`, who supplies the
        `executed_by_custodian_id` and the `witness_custodian_id`."

        Design: Corner/rbac/execute_actors_must_not_duplicate_requester_or_executor
        """
        env = setup_corner_base()
        item_a = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Scrap metal for destruction",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=40000,
            seized_at="2026-07-30T09:00:00Z",
        )
        item_b = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Second scrap bundle for destruction",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=40000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        set_clock("2026-10-30T00:00:00Z")
        adjudicate_case(env, env["case2_id"])
        order_a = open_order(env, item_a["id"], "DESTRUCTION")
        order_b = open_order(env, item_b["id"], "DESTRUCTION")
        assert order_a["status"] == "AUTHORIZED"
        assert order_a["auto_authorized"] is True
        assert order_a["requested_by_custodian_id"] == env["tech_id"]

        validate_error(
            api.execute_order(
                order_a["id"],
                execute_payload(env["tech_id"], env["aud_id"]),
                env["manager"],
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            409,
        )
        validate_error(
            api.execute_order(
                order_a["id"],
                execute_payload(env["tech2_id"], env["tech2_id"]),
                env["manager"],
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            409,
        )

        still_authorized = validate_success(
            api.get_disposition_order(order_a["id"], env["manager"]), 200
        )
        assert still_authorized["status"] == "AUTHORIZED"
        assert still_authorized["executed_by_custodian_id"] is None
        assert still_authorized["witness_custodian_id"] is None
        blocked = read_item(env, item_a["id"])
        assert blocked["disposition_state"] == "ORDER_PENDING"
        assert blocked["custody_state"] == "STORED"

        executed = validate_success(
            api.execute_order(
                order_a["id"],
                execute_payload(env["tech2_id"], env["aud_id"]),
                env["manager"],
            ),
            200,
        )
        # A DESTRUCTION order continues EXECUTED → SETTLED inside the same request.
        assert executed["status"] == "SETTLED"
        assert executed["executed_by_custodian_id"] == env["tech2_id"]
        assert executed["witness_custodian_id"] == env["aud_id"]

        # The witness is allowed to be the original requester: only executor-vs-requester
        # and witness-vs-executor are constrained.
        witness_is_requester = validate_success(
            api.execute_order(
                order_b["id"],
                execute_payload(env["tech2_id"], env["tech_id"]),
                env["manager"],
            ),
            200,
        )
        assert witness_is_requester["status"] == "SETTLED"
        assert witness_is_requester["witness_custodian_id"] == env["tech_id"]
