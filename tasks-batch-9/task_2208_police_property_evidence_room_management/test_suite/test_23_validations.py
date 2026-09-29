"""Validation rules: packaging, storage suitability, signatures, windows and disposition gates."""

from test_helpers import (
    ApiErrorId,
    add_general_bin,
    add_oversized_yard,
    adjudicate_case,
    assign_storage,
    charge_case,
    custody_transfer_payload,
    disposition_order_payload,
    evidence_item_payload,
    list_discrepancies,
    log_and_store_item,
    log_item,
    open_order,
    read_case,
    read_custodian,
    read_item,
    read_location,
    reconcile_audit,
    release_payload,
    request_transfer,
    resolve_discrepancy,
    resolve_discrepancy_payload,
    run_sweep,
    scan_barcode,
    scan_payload,
    schedule_audit,
    set_clock,
    setup_corner_base,
    setup_second_room,
    start_audit,
    storage_assignment_payload,
    suspend_custodian,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPackagingStandards:
    """The per-category packaging allow-list policed at evidence-item intake."""

    def test_narcotics_and_general_items_reject_a_sharps_tube(self, api):
        """The packaging matrix is a per-category allow-list, not one global rule.

        PRD 3.2: "Packaging standards are enforced per category, and a mismatch is
        refused with `ERR_PACKAGING_NOT_PERMITTED` (HTTP 422)."
        PRD 3.2: "`NARCOTICS` may only be packaged as `SEALED_ENVELOPE` or `RIGID_BOX`."
        PRD 3.2: "A `GENERAL` item may use any packaging type except `SHARPS_TUBE`."
        PRD 3.2: "Finally the owning case has `item_count` and `undisposed_item_count`
        each incremented by 1 and its `version` incremented by 1."

        Design: Corner/validations/narcotics_packaged_in_sharps_tube_rejected
        """
        env = setup_corner_base()

        narcotics_response = api.create_evidence_item(
            evidence_item_payload(
                env["case1_id"],
                item_description="Suspected fentanyl powder",
                category="NARCOTICS",
                packaging_type="SHARPS_TUBE",
                appraised_value_cents=0,
                seized_at="2026-07-31T12:00:00Z",
            ),
            env["tech_headers"],
        )
        validate_error(
            narcotics_response, ApiErrorId.ERR_PACKAGING_NOT_PERMITTED, 422
        )

        general_response = api.create_evidence_item(
            evidence_item_payload(
                env["case1_id"],
                item_description="Loose paperwork",
                category="GENERAL",
                packaging_type="SHARPS_TUBE",
                appraised_value_cents=0,
                seized_at="2026-07-31T12:00:00Z",
            ),
            env["tech_headers"],
        )
        validate_error(general_response, ApiErrorId.ERR_PACKAGING_NOT_PERMITTED, 422)

        _, meta = validate_paginated(
            api.list_evidence_items(env["manager"], params={"case_id": env["case1_id"]})
        )
        assert meta["total_count"] == 0
        case = read_case(env, env["case1_id"])
        assert case["item_count"] == 0
        assert case["undisposed_item_count"] == 0

    def test_permitted_packaging_per_category_is_accepted_at_intake(self, api):
        """Each category's own allow-list admits packaging another category forbids.

        PRD 3.2: "A `BIOLOGICAL` item may only be packaged as `SHARPS_TUBE` or
        `RIGID_BOX`."
        PRD 3.2: "A `FIREARM` may only be packaged as `RIGID_BOX` or `CHAIN_TAG_ONLY`."
        PRD 3.2: "An `OVERSIZED` item may only be packaged as `PALLET_WRAP` or
        `CHAIN_TAG_ONLY`."
        PRD 3.2: "A `BIOLOGICAL` item requires `REFRIGERATED`."
        PRD 3.2: "A `CURRENCY`, `FIREARM` or `NARCOTICS` item requires
        `HIGH_VALUE_VAULT`."
        PRD 3.2: "An `OVERSIZED` item requires `OVERSIZED_YARD`."
        PRD 3.2: "First the service computes `item_sequence` as one more than the number
        of evidence items already recorded against the same `case_id`; disposed items are
        counted, so a sequence number is never reused within a case."
        PRD 3.2: "The stored `barcode` is then the `agency_code`, a hyphen, the
        `case_number`, a hyphen, the four-character zero-padded `item_sequence`, a
        hyphen, and the check digit."

        Design: Corner/validations/permitted_packaging_intake_succeeds
        """
        env = setup_corner_base()

        biological = validate_success(
            api.create_evidence_item(
                evidence_item_payload(
                    env["case1_id"],
                    item_description="Blood tube",
                    category="BIOLOGICAL",
                    packaging_type="SHARPS_TUBE",
                    appraised_value_cents=0,
                    seized_at="2026-07-31T12:00:00Z",
                ),
                env["tech_headers"],
            ),
            201,
        )
        firearm = validate_success(
            api.create_evidence_item(
                evidence_item_payload(
                    env["case1_id"],
                    item_description="Seized revolver",
                    category="FIREARM",
                    packaging_type="CHAIN_TAG_ONLY",
                    appraised_value_cents=45000,
                    seized_at="2026-07-31T12:00:00Z",
                ),
                env["tech_headers"],
            ),
            201,
        )
        oversized = validate_success(
            api.create_evidence_item(
                evidence_item_payload(
                    env["case1_id"],
                    item_description="Wrapped pallet of copper pipe",
                    category="OVERSIZED",
                    packaging_type="PALLET_WRAP",
                    appraised_value_cents=90000,
                    seized_at="2026-07-31T12:00:00Z",
                ),
                env["tech_headers"],
            ),
            201,
        )

        assert biological["required_storage_category"] == "REFRIGERATED"
        # A firearm is high-risk regardless of its 45000 cent appraisal.
        assert firearm["required_storage_category"] == "HIGH_VALUE_VAULT"
        assert oversized["required_storage_category"] == "OVERSIZED_YARD"

        assert biological["item_sequence"] == 1
        assert firearm["item_sequence"] == 2
        assert oversized["item_sequence"] == 3
        assert biological["barcode"] == "CPD-26-00001-0001-2"
        assert firearm["barcode"] == "CPD-26-00001-0002-9"
        assert oversized["barcode"] == "CPD-26-00001-0003-6"

        case = read_case(env, env["case1_id"])
        assert case["item_count"] == 3
        assert case["undisposed_item_count"] == 3


class TestStorageSuitability:
    """Category, temperature and capacity checks on the storage-assignment endpoint."""

    def test_refrigerated_bin_recorded_above_four_degrees_cannot_receive_items(self, api):
        """The temperature ceiling gates both the named bin and the automatic selection.

        PRD 3.3: "If that category is `REFRIGERATED`, the location's `temperature_c` must
        be at most 4.0; a warmer reading yields `ERR_REFRIGERATION_OUT_OF_RANGE`."
        PRD 3.3: "The eligible pool is every storage location whose `property_room_id`
        matches the room of the item's case, whose `status` is `OPEN`, whose `category`
        equals the item's `required_storage_category`, whose `occupied_slots` is strictly
        less than its `capacity_slots`, and — for refrigerated locations only — whose
        `temperature_c` is at most 4.0."
        PRD 2.7: "`StorageLocation.occupied_slots` equals the number of evidence items
        whose `storage_location_id` is that location and whose `custody_state` is either
        `STORED` or `CHECKED_OUT`."

        Design: Corner/validations/refrigerated_bin_above_four_degrees_assignment_rejected
        """
        env = setup_corner_base()
        item1 = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Sexual assault kit",
            category="BIOLOGICAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=0,
            seized_at="2026-07-31T12:00:00Z",
        )
        item2 = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Buccal swab set",
            category="BIOLOGICAL",
            packaging_type="SHARPS_TUBE",
            appraised_value_cents=0,
            seized_at="2026-07-31T12:05:00Z",
        )

        warm_response = api.assign_storage(
            item1["id"],
            storage_assignment_payload(env["loc_rw_id"]),
            env["tech_headers"],
        )
        validate_error(warm_response, ApiErrorId.ERR_REFRIGERATION_OUT_OF_RANGE, 409)

        # The category matches; only the recorded reading is out of compliance.
        stored = assign_storage(env, item1["id"], env["loc_r_id"])
        assert stored["storage_location_id"] == env["loc_r_id"]
        assert stored["custody_state"] == "STORED"

        # R-09 has more free slots than R-01 now, yet it is not in the eligible pool.
        autoselected = assign_storage(env, item2["id"])
        assert autoselected["storage_location_id"] == env["loc_r_id"]

        warm_location = read_location(env, env["loc_rw_id"])
        assert warm_location["occupied_slots"] == 0
        cold_location = read_location(env, env["loc_r_id"])
        assert cold_location["occupied_slots"] == 2

    def test_high_value_item_cannot_be_assigned_to_a_general_bin(self, api):
        """Suitability follows the item's derived category, not the bin's free space.

        PRD 3.3: "The location's `category` must equal the item's
        `required_storage_category`, otherwise `ERR_STORAGE_CATEGORY_MISMATCH`."
        PRD 3.2: "A `CURRENCY`, `FIREARM` or `NARCOTICS` item requires
        `HIGH_VALUE_VAULT`."
        PRD 3.3: "A successful assignment writes `storage_location_id` onto the item,
        increments the chosen location's `occupied_slots` by 1 and that location's
        `version` by 1, appends a chain entry with `event_type` of `STORAGE_ASSIGN`, and
        recomputes the room's `posture`."

        Design: Corner/validations/high_value_item_assigned_to_general_bin_rejected
        """
        env = setup_corner_base()
        item = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Banded currency 2500 dollars",
            category="CURRENCY",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=250000,
            seized_at="2026-07-31T12:00:00Z",
        )
        assert item["required_storage_category"] == "HIGH_VALUE_VAULT"
        # G-01 has two free slots, so space is not what refuses the assignment.
        general_bin = read_location(env, env["loc_g_id"])
        assert general_bin["occupied_slots"] == 0

        mismatch_response = api.assign_storage(
            item["id"],
            storage_assignment_payload(env["loc_g_id"]),
            env["tech_headers"],
        )
        validate_error(mismatch_response, ApiErrorId.ERR_STORAGE_CATEGORY_MISMATCH, 409)

        stored = assign_storage(env, item["id"], env["loc_v_id"])
        assert stored["storage_location_id"] == env["loc_v_id"]
        assert stored["custody_state"] == "STORED"
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 0
        assert read_location(env, env["loc_v_id"])["occupied_slots"] == 1

    def test_named_bin_at_capacity_refuses_a_second_item(self, api):
        """Two individually valid items collide on the collective occupancy of one bin.

        PRD 3.3: "And the location's `occupied_slots` must be strictly less than its
        `capacity_slots`, otherwise `ERR_STORAGE_LOCATION_FULL`."
        PRD 2.7: "`StorageLocation.occupied_slots` equals the number of evidence items
        whose `storage_location_id` is that location and whose `custody_state` is either
        `STORED` or `CHECKED_OUT`."
        PRD 3.3: "Storage assignment advances an item's custody dimension from `LOGGED`
        to `STORED` and is performed by an `EvidenceTechnician`."
        PRD 2.4: "Property rooms, offense statutes, storage locations, custodians, cases,
        evidence items, retention determinations, custody transfers, disposition orders,
        owner claims, audit sessions and discrepancies additionally carry `updated_at`,
        refreshed on every mutation, and `version`, an integer that increments by one on
        every mutation — including mutations that only touch derived counters."

        Design: Corner/validations/storage_assignment_to_full_location_rejected
        """
        env = setup_corner_base()
        item1 = log_item(
            env,
            case_id=env["case1_id"],
            item_description="First bagged item",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=500,
            seized_at="2026-07-31T12:00:00Z",
        )
        item2 = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Second bagged item",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=500,
            seized_at="2026-07-31T12:05:00Z",
        )
        assign_storage(env, item1["id"], env["loc_g9_id"])
        tight_bin = read_location(env, env["loc_g9_id"])
        assert tight_bin["capacity_slots"] == 1
        assert tight_bin["occupied_slots"] == 1
        version_before = tight_bin["version"]

        full_response = api.assign_storage(
            item2["id"],
            storage_assignment_payload(env["loc_g9_id"]),
            env["tech_headers"],
        )
        validate_error(full_response, ApiErrorId.ERR_STORAGE_LOCATION_FULL, 409)

        after_refusal = read_location(env, env["loc_g9_id"])
        assert after_refusal["occupied_slots"] == 1
        assert after_refusal["version"] == version_before
        assert read_item(env, item2["id"])["custody_state"] == "LOGGED"

        # The same item is accepted by the bin that still has room.
        fallback = assign_storage(env, item2["id"], env["loc_g_id"])
        assert fallback["storage_location_id"] == env["loc_g_id"]
        assert fallback["custody_state"] == "STORED"

    def test_autoselect_with_an_empty_eligible_pool_is_refused(self, api):
        """An empty eligible pool is a different failure from a bin being full.

        PRD 3.3: "If the eligible pool is empty, the assignment is refused with
        `ERR_NO_ELIGIBLE_STORAGE`."
        PRD 3.3: "The eligible pool is every storage location whose `property_room_id`
        matches the room of the item's case, whose `status` is `OPEN`, whose `category`
        equals the item's `required_storage_category`, whose `occupied_slots` is strictly
        less than its `capacity_slots`, and — for refrigerated locations only — whose
        `temperature_c` is at most 4.0."
        PRD 3.2: "An `OVERSIZED` item requires `OVERSIZED_YARD`."

        Design: Corner/validations/autoselect_with_no_eligible_location_rejected
        """
        env = setup_corner_base()
        item = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Wrapped pallet of copper pipe",
            category="OVERSIZED",
            packaging_type="PALLET_WRAP",
            appraised_value_cents=90000,
            seized_at="2026-07-31T12:00:00Z",
        )
        assert item["required_storage_category"] == "OVERSIZED_YARD"
        # The room's bins are GENERAL, HIGH_VALUE_VAULT and REFRIGERATED only.
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 0
        assert read_location(env, env["loc_r_id"])["occupied_slots"] == 0

        empty_pool_response = api.assign_storage(
            item["id"], storage_assignment_payload(), env["tech_headers"]
        )
        validate_error(empty_pool_response, ApiErrorId.ERR_NO_ELIGIBLE_STORAGE, 409)
        assert read_item(env, item["id"])["custody_state"] == "LOGGED"

        yard = add_oversized_yard(env, code="Y-01", capacity_slots=2)

        chosen = assign_storage(env, item["id"])
        assert chosen["storage_location_id"] == yard["id"]
        assert chosen["custody_state"] == "STORED"


class TestCustodyTransferValidations:
    """Signature capture, window sanity and custodian eligibility on transfers."""

    def test_release_out_of_a_dual_signature_vault_demands_a_witness(self, api):
        """The second signature is required by the bin the item currently sits in.

        PRD 3.5: "It requires a `released_signature` in the request, and a
        `witness_signature` when the item's current storage location has
        `requires_dual_signature` set to true — omitting the second signature in that
        case is refused with `ERR_WITNESS_SIGNATURE_REQUIRED`."
        PRD 3.1: "The optional `requires_dual_signature` flag defaults to false; when
        true, releasing any item out of that location demands a witness signature
        alongside the releasing signature."
        PRD 3.5: "Release is an `EvidenceTechnician` action and drives two state machines
        at once, moving the transfer `REQUESTED → RELEASED` and the item's custody
        dimension `STORED → CHECKED_OUT`."

        Design: Corner/validations/release_from_dual_signature_vault_without_witness_rejected
        """
        env = setup_corner_base()
        assert env["loc_v"]["requires_dual_signature"] is True
        vault_item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_v_id"],
            item_description="Banded currency for counterfeit exam",
            category="CURRENCY",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=250000,
            seized_at="2026-07-31T12:00:00Z",
        )
        vault_transfer = request_transfer(
            env,
            vault_item["id"],
            env["lab_id"],
            "LAB_ANALYSIS",
            "2026-08-02T09:00:00Z",
            "2026-08-12T09:00:00Z",
            headers=env["lab_headers"],
        )

        solo_response = api.release_transfer(
            vault_transfer["id"], release_payload("sig-solo"), env["tech_headers"]
        )
        validate_error(solo_response, ApiErrorId.ERR_WITNESS_SIGNATURE_REQUIRED, 422)
        assert read_item(env, vault_item["id"])["custody_state"] == "STORED"

        witnessed = validate_success(
            api.release_transfer(
                vault_transfer["id"],
                release_payload("sig-solo", "sig-witness"),
                env["tech_headers"],
            ),
            200,
        )
        assert witnessed["status"] == "RELEASED"
        assert witnessed["witness_signature"] == "sig-witness"
        assert read_item(env, vault_item["id"])["custody_state"] == "CHECKED_OUT"

        # The rule is conditional on the location: G-01 was created without the flag.
        assert env["loc_g"]["requires_dual_signature"] is False
        plain_item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Notebook for review",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=500,
            seized_at="2026-07-31T12:00:00Z",
        )
        plain_transfer = request_transfer(
            env,
            plain_item["id"],
            env["inv_id"],
            "INVESTIGATIVE_REVIEW",
            "2026-08-02T09:00:00Z",
            "2026-08-05T09:00:00Z",
            headers=env["inv_headers"],
        )
        plain_released = validate_success(
            api.release_transfer(
                plain_transfer["id"], release_payload("sig-solo"), env["tech_headers"]
            ),
            200,
        )
        assert plain_released["status"] == "RELEASED"
        assert read_item(env, plain_item["id"])["custody_state"] == "CHECKED_OUT"

    def test_due_back_at_must_be_strictly_after_released_at(self, api):
        """The window exclusion sits exactly at equality, not one millisecond later.

        PRD 3.5: "`due_back_at` must be strictly after `released_at`, and a window that
        is not is refused with `ERR_INVALID_TRANSFER_WINDOW`."
        PRD 3.5: "The new row starts with `status` of `REQUESTED`, with
        `from_custodian_id`, all three signature fields, `returned_at` and
        `denial_reason` null, and it increments both the receiving custodian's
        `open_escort_count` and the item's `open_transfer_count`."

        Design: Corner/validations/transfer_due_back_not_after_release_rejected
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Notebook for review",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=500,
            seized_at="2026-07-31T12:00:00Z",
        )

        equal_response = api.create_custody_transfer(
            custody_transfer_payload(
                item["id"],
                env["inv_id"],
                "INVESTIGATIVE_REVIEW",
                "2026-08-02T09:00:00Z",
                "2026-08-02T09:00:00Z",
            ),
            env["inv_headers"],
        )
        validate_error(equal_response, ApiErrorId.ERR_INVALID_TRANSFER_WINDOW, 422)

        inverted_response = api.create_custody_transfer(
            custody_transfer_payload(
                item["id"],
                env["inv_id"],
                "INVESTIGATIVE_REVIEW",
                "2026-08-02T09:00:00Z",
                "2026-08-01T09:00:00Z",
            ),
            env["inv_headers"],
        )
        validate_error(inverted_response, ApiErrorId.ERR_INVALID_TRANSFER_WINDOW, 422)

        one_millisecond = validate_success(
            api.create_custody_transfer(
                custody_transfer_payload(
                    item["id"],
                    env["inv_id"],
                    "INVESTIGATIVE_REVIEW",
                    "2026-08-02T09:00:00Z",
                    "2026-08-02T09:00:00.001Z",
                ),
                env["inv_headers"],
            ),
            201,
        )
        assert one_millisecond["status"] == "REQUESTED"

        _, meta = validate_paginated(
            api.list_custody_transfers(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert read_custodian(env, env["inv_id"])["open_escort_count"] == 1

    def test_transfer_to_a_suspended_custodian_is_refused(self, api):
        """Suspension is a business constraint, not an authentication failure.

        PRD 2.11: "A custodian whose `status` is `SUSPENDED` may not act, hold, audit,
        execute or witness, and any operation referencing such a custodian is rejected
        with `ERR_CUSTODIAN_SUSPENDED`."
        PRD 2.10: "Every custodian referenced as actor, holder, auditor, executor or
        witness has `status` of `ACTIVE` — `ERR_CUSTODIAN_SUSPENDED` (409)."
        PRD 3.1: "A `PropertyRoomManager` may suspend a custodian by supplying a
        `reason`, which moves `status` from `ACTIVE` to `SUSPENDED` and stores the text in
        `suspension_reason`."

        Design: Corner/validations/suspended_custodian_transfer_rejected
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Cartridge casings",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=100,
            seized_at="2026-07-31T12:00:00Z",
        )
        suspended = suspend_custodian(
            env, env["lab_id"], reason="Pending internal affairs review"
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "Pending internal affairs review"
        assert suspended["role_type"] == "LAB_ANALYST"

        # The suspended analyst is both the caller and the receiving holder.
        response = api.create_custody_transfer(
            custody_transfer_payload(
                item["id"],
                env["lab_id"],
                "LAB_ANALYSIS",
                "2026-08-02T09:00:00Z",
                "2026-08-12T09:00:00Z",
            ),
            env["lab_headers"],
        )
        validate_error(response, ApiErrorId.ERR_CUSTODIAN_SUSPENDED, 409)

        _, meta = validate_paginated(
            api.list_custody_transfers(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_custodian(env, env["lab_id"])["open_escort_count"] == 0


class TestDispositionOrderGates:
    """The preservation, case-disposability and retention-maturity gates at order creation."""

    def test_destruction_of_an_indefinitely_preserved_item_is_refused(self, api):
        """The preservation class is examined ahead of case status and retention maturity.

        PRD 3.7: "Then the preservation class is examined: a `DESTRUCTION` order for an
        item whose statute has a `preservation_class` of `BIOLOGICAL_INDEFINITE` or
        `HOMICIDE_PERMANENT` is refused with `ERR_PRESERVATION_CLASS_FORBIDS_DESTRUCTION`."
        PRD 3.4: "Otherwise, if the statute's `preservation_class` is
        `BIOLOGICAL_INDEFINITE` or `HOMICIDE_PERMANENT`, the resolved basis is
        `INDEFINITE`, the release instant is null and `statute_days_applied` is 0."
        PRD 3.4: "A null release instant means the item may never leave the room on
        retention grounds alone."

        Design: Corner/validations/destruction_of_biological_indefinite_case_rejected
        """
        env = setup_corner_base()
        item = log_item(
            env,
            case_id=env["case3_id"],
            item_description="Preserved assault kit",
            category="BIOLOGICAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=0,
            seized_at="2026-07-31T12:00:00Z",
        )
        assert item["retention_basis"] == "INDEFINITE"
        assert item["retention_release_at"] is None
        assign_storage(env, item["id"], env["loc_r_id"])
        # Case 26-00003 is still OPEN and the item is still RETAINED, so the request
        # also violates the case-disposability and retention-maturity gates.
        assert read_case(env, env["case3_id"])["status"] == "OPEN"

        response = api.create_disposition_order(
            disposition_order_payload(item["id"], "DESTRUCTION", env["tech_id"]),
            env["tech_headers"],
        )
        validate_error(
            response, ApiErrorId.ERR_PRESERVATION_CLASS_FORBIDS_DESTRUCTION, 409
        )

        assert read_item(env, item["id"])["disposition_state"] == "RETAINED"
        _, meta = validate_paginated(
            api.list_disposition_orders(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_matured_item_on_a_merely_charged_case_is_not_disposable(self, api):
        """Retention maturity alone does not make an unadjudicated case disposable.

        PRD 3.7: "Then case disposability: the case's `status` must be `ADJUDICATED` or
        `CLOSED`, unless the item has `is_found_property` set to true **and** a
        `disposition_state` of `UNCLAIMED_ELIGIBLE`, in which case found property may be
        disposed of regardless of where the case stands; otherwise the request is refused
        with `ERR_CASE_NOT_DISPOSABLE`."
        PRD 3.8: "**Step three** matures retention: every item whose `custody_state` is
        `STORED` and whose `retention_release_at` is non-null and at or before the current
        instant moves `RETAINED → DISPOSAL_ELIGIBLE`."
        PRD 3.7: "Automatic authorization applies only when all four of the following
        hold: the order's `type` is `DESTRUCTION`; the case's statute has
        `destruction_requires_court_order` set to false; the item's `category` is none of
        `FIREARM`, `CURRENCY`, `NARCOTICS` or `BIOLOGICAL`; and the item's
        `appraised_value_cents` is strictly below 500000 cents, so that an item appraised
        at exactly five thousand dollars still requires a judge."

        Design: Corner/validations/unadjudicated_case_disposition_order_rejected
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Stolen power tool",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=30000,
            seized_at="2026-07-31T12:00:00Z",
        )
        assert item["retention_release_at"] == "2027-08-01T00:00:00.000Z"
        charge_case(env, env["case1_id"])
        set_clock("2027-08-01T00:00:00Z")
        room = run_sweep(env)

        assert room["disposal_eligible_count"] == 1
        assert read_item(env, item["id"])["disposition_state"] == "DISPOSAL_ELIGIBLE"
        assert read_case(env, env["case1_id"])["status"] == "CHARGED"

        response = api.create_disposition_order(
            disposition_order_payload(item["id"], "DESTRUCTION", env["tech_id"]),
            env["tech_headers"],
        )
        validate_error(response, ApiErrorId.ERR_CASE_NOT_DISPOSABLE, 409)
        assert read_item(env, item["id"])["disposition_state"] == "DISPOSAL_ELIGIBLE"

        # Adjudication is the only input that changes; the identical request then passes.
        adjudicate_case(env, env["case1_id"])
        order = open_order(env, item["id"], "DESTRUCTION")
        assert order["auto_authorized"] is True
        assert order["status"] == "AUTHORIZED"
        assert read_item(env, item["id"])["disposition_state"] == "ORDER_PENDING"

    def test_retained_item_on_an_adjudicated_case_reports_immature_retention(self, api):
        """A RETAINED item falls through the state stage to the retention-maturity gate.

        PRD 3.7: "Finally retention maturity: an item still in `RETAINED` is refused with
        `ERR_RETENTION_NOT_MATURED`, because its `retention_release_at` is either null or
        still in the future."
        PRD 2.10: "One carve-out applies: when a disposition order is opened, an item
        whose `disposition_state` is `RETAINED` or `COURT_HOLD` is **not** reported at
        this stage — those cases are reported by the domain checks at stages 23, 24 and
        25 — so this stage reports only the remaining illegal disposition states
        `ORDER_PENDING` and `DISPOSED`, using `ERR_ITEM_DISPOSITION_STATE_INVALID`."
        PRD 2.4: "Property rooms, offense statutes, storage locations, custodians, cases,
        evidence items, retention determinations, custody transfers, disposition orders,
        owner claims, audit sessions and discrepancies additionally carry `updated_at`,
        refreshed on every mutation, and `version`, an integer that increments by one on
        every mutation — including mutations that only touch derived counters."

        Design: Corner/validations/retention_not_matured_order_rejected
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Stolen power tool",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=30000,
            seized_at="2026-07-31T12:00:00Z",
        )
        charge_case(env, env["case1_id"])
        set_clock("2026-09-15T00:00:00Z")
        adjudicate_case(env, env["case1_id"])

        before = read_item(env, item["id"])
        assert before["retention_release_at"] == "2027-04-16T00:00:00.000Z"
        assert before["retention_basis"] == "FINAL"
        assert before["disposition_state"] == "RETAINED"
        # The case is ADJUDICATED, so the case-disposability gate has already passed.
        assert read_case(env, env["case1_id"])["status"] == "ADJUDICATED"

        response = api.create_disposition_order(
            disposition_order_payload(item["id"], "DESTRUCTION", env["tech_id"]),
            env["tech_headers"],
        )
        validate_error(response, ApiErrorId.ERR_RETENTION_NOT_MATURED, 409)

        after = read_item(env, item["id"])
        assert after["version"] == before["version"]
        assert after["disposition_state"] == "RETAINED"
        _, meta = validate_paginated(
            api.list_disposition_orders(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestAuditAndDiscrepancyValidations:
    """Barcode ownership at scan time and resolution-kind compatibility."""

    def test_scanning_another_rooms_barcode_is_refused(self, api):
        """A resolvable barcode belonging to another room is a domain failure, not a 404.

        PRD 3.8: "The auditor submits a `barcode`; if it matches no evidence item the
        scan is refused with `ERR_BARCODE_NOT_FOUND`, and if the matched item belongs to a
        case of a different property room than the audited location the scan is refused
        with `ERR_BARCODE_FOREIGN_ROOM`."
        PRD 3.8: "A valid scan appends the item's identifier to
        `scanned_evidence_item_ids`, increments `scanned_item_count`, and appends a chain
        entry with `event_type` of `AUDIT_SCAN`."
        PRD 3.2: "The stored `barcode` is then the `agency_code`, a hyphen, the
        `case_number`, a hyphen, the four-character zero-padded `item_sequence`, a
        hyphen, and the check digit."

        Design: Corner/validations/scan_barcode_from_other_room_rejected
        """
        env = setup_corner_base()
        second = setup_second_room(env)
        foreign_item = validate_success(
            api.create_evidence_item(
                evidence_item_payload(
                    second["case_id"],
                    item_description="Other agency toolbox",
                    category="GENERAL",
                    packaging_type="RIGID_BOX",
                    appraised_value_cents=7000,
                    seized_at="2026-07-31T12:00:00Z",
                ),
                second["tech_headers"],
            ),
            201,
        )
        assert foreign_item["barcode"] == "MPD-26-90001-0001-5"

        session = schedule_audit(
            env,
            env["loc_g9_id"],
            env["loc_g9_version"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T17:00:00Z",
        )
        start_audit(env, session["id"])

        response = api.scan_audit_session(
            session["id"],
            scan_payload(foreign_item["barcode"]),
            env["aud_headers"],
        )
        validate_error(response, ApiErrorId.ERR_BARCODE_FOREIGN_ROOM, 409)

        after = validate_success(
            api.get_audit_session(session["id"], env["manager"]), 200
        )
        assert after["scanned_item_count"] == 0
        assert after["scanned_evidence_item_ids"] == []
        assert after["misplaced_count"] == 0

        _, scan_meta = validate_paginated(
            api.list_chain_events(
                env["manager"],
                params={
                    "evidence_item_id": foreign_item["id"],
                    "event_type": "AUDIT_SCAN",
                },
            )
        )
        assert scan_meta["total_count"] == 0
        _, discrepancy_meta = validate_paginated(
            api.list_discrepancies(
                env["manager"], params={"audit_session_id": session["id"]}
            )
        )
        assert discrepancy_meta["total_count"] == 0

    def test_a_misplaced_discrepancy_cannot_be_written_off(self, api):
        """Writing off is reserved for items that could not be produced at all.

        PRD 3.8: "Resolving as `WRITTEN_OFF` accepts the loss: it is permitted only for a
        `MISSING` discrepancy, and requesting it for a `MISPLACED` one is refused with
        `ERR_DISCREPANCY_RESOLUTION_NOT_PERMITTED`."
        PRD 3.8: "If the scanned item's `storage_location_id` is not the audited
        location, the item is physically present in the wrong place, and a discrepancy is
        raised on the spot with `kind` of `MISPLACED` and `status` of `OPEN`, incrementing
        the room's `open_discrepancy_count` and triggering a `posture` recomputation."
        PRD 3.8: "Resolving a `MISPLACED` discrepancy as `FOUND` instead relocates the
        item into the audited location: it requires that location to have
        `occupied_slots` strictly below `capacity_slots` (`ERR_STORAGE_LOCATION_FULL`) and
        its `category` to equal the item's `required_storage_category`
        (`ERR_STORAGE_CATEGORY_MISMATCH`), and on success the item's
        `storage_location_id` becomes the audited location while the old location's
        `occupied_slots` is decremented by 1 and the new location's incremented by 1."

        Design: Corner/validations/discrepancy_written_off_on_misplaced_rejected
        """
        env = setup_corner_base()
        spare = add_general_bin(env, code="G-02", capacity_slots=4)
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=spare["id"],
            item_description="Misplaced camera",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=300000,
            seized_at="2026-07-31T12:00:00Z",
        )
        session = schedule_audit(
            env,
            env["loc_g9_id"],
            env["loc_g9_version"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T17:00:00Z",
        )
        start_audit(env, session["id"])
        scan_barcode(env, session["id"], item["barcode"])
        reconcile_audit(env, session["id"])

        discrepancies = list_discrepancies(env, audit_session_id=session["id"])
        assert len(discrepancies) == 1
        discrepancy = discrepancies[0]
        # The item sat in G-02 rather than the audited G-09.
        assert discrepancy["kind"] == "MISPLACED"
        assert discrepancy["status"] == "OPEN"

        response = api.resolve_discrepancy(
            discrepancy["id"],
            resolve_discrepancy_payload("WRITTEN_OFF", "Accepting the loss"),
            env["manager"],
        )
        validate_error(
            response, ApiErrorId.ERR_DISCREPANCY_RESOLUTION_NOT_PERMITTED, 422
        )
        # The refused write-off never reached the MISSING to PURGED transition.
        assert read_item(env, item["id"])["custody_state"] == "STORED"

        resolved = resolve_discrepancy(
            env, discrepancy["id"], "FOUND", "Camera relocated into G-09"
        )
        assert resolved["status"] == "RESOLVED_FOUND"

        relocated = read_item(env, item["id"])
        assert relocated["custody_state"] == "STORED"
        assert relocated["storage_location_id"] == env["loc_g9_id"]
