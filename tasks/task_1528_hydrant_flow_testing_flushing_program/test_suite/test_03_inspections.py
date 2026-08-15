"""Inspection cycle: verification gates, segregation of duties, ownership
scoping, optimistic concurrency, the FAIL repair loop, and due tiers."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    api_client,
    TEST_USERS,
    make_supervisor_headers,
    make_owner_rep_headers,
    make_operator_headers,
    create_program,
    create_zone,
    create_hydrant,
    create_private_owner,
    create_private_hydrant,
    create_inspection_payload,
    open_inspection,
    record_inspection,
    verify_inspection,
    create_recorded_inspection,
    create_verified_inspection,
    get_hydrant,
    set_clock,
    setup_program_zone_hydrant,
)

ADMIN = TEST_USERS["admin_headers"]
OP1 = TEST_USERS["operator_headers"]
SUP1 = TEST_USERS["supervisor_headers"]


class TestVerifyTerminalState:
    def test_inspection_verify_twice_rejected(self, api):
        """PRD §3.2: "The inspection must be `PENDING_VERIFICATION`; otherwise
        the request is rejected with `ERR_INSPECTION_NOT_PENDING_VERIFICATION`."
        PRD §3.2: "When the decision is `VERIFY`, the inspection moves to
        `VERIFIED`, its `result` is set to `PASS` when `defects_found` is false
        and to `FAIL` when defects were found, `verified_by_user_id` is
        recorded, the hydrant's `last_verified_inspection_date` is set to the
        inspection's `performed_date`, the hydrant's `version` increments, and
        the hydrant's `inspection_tier` is recomputed from the new baseline."

        Design: Corner/state_machines/inspection_verify_twice_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        inspection = create_verified_inspection(hydrant["id"], defects_found=False)
        assert inspection["status"] == "VERIFIED"
        assert inspection["result"] == "PASS"

        resp = api.verify_inspection(inspection["id"], {"decision": "VERIFY"},
                                     make_supervisor_headers("sup_2"))
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_PENDING_VERIFICATION, 409)

        after = validate_success(api.get_inspection(inspection["id"], SUP1))
        assert after["status"] == "VERIFIED", "VERIFIED must be terminal for verify"
        assert after["result"] == "PASS"


class TestFailVerificationRepairLoop:
    def test_inspection_fail_verification_autocreates_work_order(self, api):
        """PRD §3.2: "when an inspection verifies with `result` `FAIL`, the
        system automatically creates a `RepairWorkOrder` in `DRAFT` status
        whose `hydrant_id` is the failed inspection's hydrant, whose
        `source_inspection_id` is the failed inspection's id, whose
        `created_by_user_id` is the literal string `system`, and whose
        `description` reads "Auto-generated from failed inspection"."
        PRD §3.2: "When the decision is `VERIFY`, the inspection moves to
        `VERIFIED`, its `result` is set to `PASS` when `defects_found` is false
        and to `FAIL` when defects were found, `verified_by_user_id` is
        recorded, the hydrant's `last_verified_inspection_date` is set to the
        inspection's `performed_date`, the hydrant's `version` increments, and
        the hydrant's `inspection_tier` is recomputed from the new baseline."

        Design: Corner/state_machines/inspection_fail_verification_autocreates_work_order
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        inspection = create_recorded_inspection(
            hydrant["id"],
            performed_date="2026-08-10T00:00:00Z",
            defects_found=True,
            condition_notes="broken cap",
        )
        verified = verify_inspection(inspection["id"], decision="VERIFY", headers=SUP1)
        assert verified["result"] == "FAIL", (
            f"defects_found true must yield result FAIL, got {verified['result']}"
        )
        assert verified["status"] == "VERIFIED"

        data, meta = validate_paginated(api.list_work_orders(SUP1))
        assert meta["total_count"] == 1, (
            f"exactly one auto-created work order must exist, got {meta['total_count']}"
        )
        wo = data[0]
        assert wo["status"] == "DRAFT"
        assert wo["hydrant_id"] == hydrant["id"]
        assert wo["source_inspection_id"] == inspection["id"]
        assert wo["created_by_user_id"] == "system"
        assert wo["description"] == "Auto-generated from failed inspection"

        after = get_hydrant(hydrant["id"])
        assert after["last_verified_inspection_date"] is not None
        assert after["last_verified_inspection_date"].startswith("2026-08-10"), (
            "last_verified_inspection_date must be the inspection's performed_date"
        )


class TestSegregationOfDuties:
    def test_sod_verify_own_inspection_rejected(self, api):
        """PRD §3.2: "Segregation of duties is enforced here: the supervisor's
        `X-User-ID` must differ from the inspection's `performed_by_user_id`,
        and a self-verification is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_verify_own_inspection_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        inspection = create_recorded_inspection(hydrant["id"])  # recorded by op_1

        # Role is correct (UtilitySupervisor) but X-User-ID equals the recorder.
        resp = api.verify_inspection(inspection["id"], {"decision": "VERIFY"},
                                     make_supervisor_headers("op_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        after = validate_success(api.get_inspection(inspection["id"], SUP1))
        assert after["status"] == "PENDING_VERIFICATION", (
            "rejected verification must leave the inspection PENDING_VERIFICATION"
        )


class TestOwnershipScope:
    def test_private_hydrant_record_by_operator_rejected(self, api):
        """PRD §3.2: "When the inspection's hydrant is `MUNICIPAL`, only a
        `FieldOperator` may record; when the hydrant is `PRIVATE`, only a
        `PrivateOwnerRep` whose `X-User-ID` equals the hydrant's
        `private_owner_id` may record. A mismatch is rejected with
        `ERR_HYDRANT_OWNERSHIP_MISMATCH`."

        Design: Corner/validations/private_hydrant_record_by_operator_rejected
        """
        program = create_program()
        zone = create_zone()
        owner = create_private_owner()
        hydrant = create_private_hydrant(program["id"], zone["id"], owner["id"],
                                         hydrant_number="H-P1")
        inspection = open_inspection(hydrant["id"])

        resp = api.record_inspection(
            inspection["id"],
            {"performed_date": "2026-08-10T00:00:00Z", "defects_found": False},
            OP1,
        )
        validate_error(resp, ApiErrorId.ERR_HYDRANT_OWNERSHIP_MISMATCH, 403)

        after = validate_success(api.get_inspection(inspection["id"], SUP1))
        assert after["status"] == "SCHEDULED", (
            "rejected record must leave the inspection SCHEDULED"
        )

    def test_private_owner_cannot_verify_inspection(self, api):
        """PRD §2.1: "`PrivateOwnerRep` — private hydrant owner's
        representative; may record inspection evidence only for privately owned
        hydrants."
        PRD §2.1: "a role outside the list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /inspections/{id}/verify is authorized for
        UtilitySupervisor only.

        Design: Corner/rbac/private_owner_cannot_verify_inspection
        """
        program = create_program()
        zone = create_zone()
        owner = create_private_owner()
        hydrant = create_private_hydrant(program["id"], zone["id"], owner["id"],
                                         hydrant_number="H-P1")
        inspection = open_inspection(hydrant["id"])
        record_inspection(inspection["id"], headers=make_owner_rep_headers(owner["id"]))

        resp = api.verify_inspection(inspection["id"], {"decision": "VERIFY"},
                                     make_owner_rep_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        after = validate_success(api.get_inspection(inspection["id"], SUP1))
        assert after["status"] == "PENDING_VERIFICATION"


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_inspection_create(self, api):
        """PRD §2.6: "Creating an inspection requires the request to carry
        `expected_hydrant_version`, matching the target hydrant's current
        `version`. If another writer has advanced the hydrant's version since
        the client last read it — a new inspection, a flow-test result, an
        outage cascade, a tier recompute — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from opening an
        inspection against a stale view of the asset."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_inspection_create
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        observed_version = hydrant["version"]

        first = open_inspection(hydrant["id"])
        assert first["status"] == "SCHEDULED"

        # Second create carrying the previously observed version is stale.
        resp = api.create_inspection(
            create_inspection_payload(
                hydrant["id"], observed_version, scheduled_date="2026-08-11T00:00:00Z"
            ),
            OP1,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        after = get_hydrant(hydrant["id"])
        assert after["latest_inspection_id"] == first["id"], (
            "the stale create must not move latest_inspection_id"
        )


class TestInspectionDueTiers:
    def test_inspection_tier_boundaries_via_sweep(self, api):
        """PRD §3.9: "The boundaries are pinned: a clock reading exactly equal
        to the due date yields `OVERDUE`; exactly the due date minus 30 days
        yields `DUE_SOON`; exactly the due date plus 90 days yields `CRITICAL`."
        PRD §3.9: "The tier derives from the hydrant's cycle — 12 months for
        `MUNICIPAL`, 6 months for `PRIVATE` — and a baseline that is the
        hydrant's `last_verified_inspection_date` when one exists and the
        hydrant's `created_at` when no inspection has yet verified."

        Design: Corner/calculations/inspection_tier_boundaries_via_sweep
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        # Never-inspected municipal hydrant: baseline created_at 2026-08-01,
        # cycle 12 months -> due 2027-08-01.

        set_clock("2027-07-02T00:00:00Z")  # exactly due - 30 days
        api.sweep_program(program["id"], ADMIN)
        tier = get_hydrant(hydrant["id"])["inspection_tier"]
        assert tier == "DUE_SOON", f"at due-30d the tier must be DUE_SOON, got {tier}"

        set_clock("2027-08-01T00:00:00Z")  # exactly the due date
        api.sweep_program(program["id"], ADMIN)
        tier = get_hydrant(hydrant["id"])["inspection_tier"]
        assert tier == "OVERDUE", f"at the due date the tier must be OVERDUE, got {tier}"

        set_clock("2027-10-30T00:00:00Z")  # exactly due + 90 days
        api.sweep_program(program["id"], ADMIN)
        tier = get_hydrant(hydrant["id"])["inspection_tier"]
        assert tier == "CRITICAL", f"at due+90d the tier must be CRITICAL, got {tier}"
