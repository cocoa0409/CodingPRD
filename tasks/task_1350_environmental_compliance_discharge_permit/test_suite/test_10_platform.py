"""Platform contract: user-context and role enforcement, the monotonic logical
clock, the append-only hash-chained audit log, and single-resource GET
round-trips across all twelve resource families (PRD §2.1, §2.5, §2.10, §4)."""
from test_helpers import (
    ApiErrorId,
    activate_swppp_plan,
    advance_custody_to_analyzed,
    assert_audit_entry,
    collect_sample,
    create_consent_order,
    create_dmr,
    create_effluent_limit,
    create_inspection,
    create_outfall,
    create_permit,
    create_permit_payload,
    create_renewal_application,
    create_swppp_plan,
    headers_missing_role,
    headers_with_undeclared_role,
    make_field_sampler_headers,
    record_lab_result,
    schedule_sample,
    set_clock,
    validate_error,
    validate_lab_result,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.fixtures import EM

READER = TEST_USERS["field_sampler_headers"]  # any authenticated role may read (§2.1)
GENESIS_HASH = "0" * 64

class TestUserContextAndRoles:
    def test_rbac_missing_user_context_header(self, api):
        """PRD §2.1: "A request missing either header, or naming a role outside this
        list, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/rbac/rbac_missing_user_context_header
        """
        payload = create_permit_payload(permit_number="NPDES-RBAC1")
        resp_missing = api.create_permit(payload, headers_missing_role())
        validate_error(resp_missing, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        resp_undeclared = api.create_permit(payload, headers_with_undeclared_role())
        validate_error(resp_undeclared, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_rbac_field_sampler_cannot_create_permit(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target operation
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST `/npdes/permits` ... | EnvironmentalManager |".

        Design: Corner/rbac/rbac_field_sampler_cannot_create_permit
        """
        resp = api.create_permit(
            create_permit_payload(permit_number="NPDES-RBAC2"),
            make_field_sampler_headers("sampler-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_environmental_manager_cannot_operate_clock(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target operation
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.5: "Operators advance the clock through a `SystemAdmin`-only
        capability".

        Design: Corner/rbac/rbac_environmental_manager_cannot_operate_clock
        """
        resp = api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, EM)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_get_endpoints_open_to_all_roles(self, api):
        """PRD §2.1: "`Any` is a pseudo-role: any authenticated caller holding one
        of the eight roles above may use every read (GET) endpoint in the system."

        Design: Corner/rbac/rbac_get_endpoints_open_to_all_roles
        """
        permit = create_permit(permit_number="NPDES-RBAC8")
        single = validate_success(api.get_permit(permit["id"], READER))
        assert single["id"] == permit["id"]
        rows, meta = validate_paginated(api.list_permits(READER))
        assert meta["total_count"] == 1 and rows[0]["id"] == permit["id"]

class TestLogicalClock:
    def test_clock_regression_rejected(self, api):
        """PRD §2.5: "The clock is monotonic: the supplied instant must be strictly
        after the current logical clock, otherwise the request is rejected with
        `ERR_CLOCK_REGRESSION` (HTTP 400)."

        Design: Corner/validations/clock_regression_rejected
        """
        set_clock("2026-08-10T00:00:00Z")

        resp_backwards = api.set_clock(
            {"to_iso8601": "2026-08-09T00:00:00Z"}, TEST_USERS["system_admin_headers"]
        )
        validate_error(resp_backwards, ApiErrorId.ERR_CLOCK_REGRESSION)

        resp_same = api.set_clock(
            {"to_iso8601": "2026-08-10T00:00:00Z"}, TEST_USERS["system_admin_headers"]
        )
        validate_error(resp_same, ApiErrorId.ERR_CLOCK_REGRESSION)

class TestAuditChain:
    def test_audit_hash_chain_links_and_genesis(self, api):
        """PRD §2.10: "Each entry stores `prev_entry_hash`, the SHA-256 hex of the
        previous entry — the very first entry uses sixty-four zero characters as its
        genesis — and `entry_hash`, computed as the lowercase SHA-256 hex of the
        pipe-joined concatenation ..." and "The chain is listable and filterable by
        `entity_type` and `entity_id`."
        PRD §3.1: "Issuance moves the permit `DRAFT → ACTIVE`, increments its
        `version` and appends a `PERMIT_ISSUED` audit entry."

        Design: Corner/calculations/audit_hash_chain_links_and_genesis
        """
        permit = create_permit(permit_number="NPDES-CALC10")
        outfall = create_outfall(permit["id"])
        create_effluent_limit(outfall["id"])
        validate_success(api.issue_permit(permit["id"], EM))
        # Four mutating operations -> exactly four audit entries (§2.10).

        entries, meta = validate_paginated(api.list_audit_entries(READER))
        assert len(entries) == 4 and meta["total_count"] == 4
        for entry in entries:
            assert_audit_entry(entry)

        assert entries[0]["prev_entry_hash"] == GENESIS_HASH, "genesis link"
        for previous, current in zip(entries, entries[1:]):
            assert current["prev_entry_hash"] == previous["entry_hash"], (
                "each entry links to its predecessor's entry_hash"
            )
        assert [e["entity_type"] for e in entries] == [
            "Permit", "Outfall", "EffluentLimit", "Permit",
        ]
        assert entries[3]["action"] == "PERMIT_ISSUED"
        assert entries[3]["actor_user_id"] == "em-1"
        assert entries[3]["actor_role"] == "EnvironmentalManager"

        permit_rows, permit_meta = validate_paginated(
            api.list_audit_entries(READER, params={"entity_type": "Permit"})
        )
        assert permit_meta["total_count"] == 2
        assert all(row["entity_type"] == "Permit" for row in permit_rows)

class TestSingleResourceRoundTrip:
    def test_get_endpoints_return_persisted_state(self, api):
        """PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects." and "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §3.3: "when this validation leaves every result of the sample `VALIDATED`
        with none `SUBMITTED` or `REJECTED` — closes the sample itself, moving its
        schedule status from `COLLECTED` to `CLOSED`."

        Design: Corner/endpoints/get_endpoints_return_persisted_state
        """
        # Build one resource of each of the twelve families via canonical flows.
        permit = create_permit(
            permit_number="NPDES-EP1", expiration_date="2026-12-31T00:00:00Z"
        )
        outfall = create_outfall(permit["id"])
        limit = create_effluent_limit(
            outfall["id"], parameter_code="TSS", limit_value=10.0,
            monitoring_frequency="MONTHLY",
        )
        validate_success(api.issue_permit(permit["id"], EM))

        sample = schedule_sample(outfall["id"], "TSS", "2026-08-05T08:00:00Z")
        collect_sample(sample["id"], clock_iso="2026-08-05T09:00:00Z")
        advance_custody_to_analyzed(sample["id"], "2026-08-05T09:00:00Z")
        result = record_lab_result(
            sample["id"], "TSS", 12.0, "2026-08-05T09:45:00Z"
        )
        set_clock("2026-08-05T10:00:00Z")
        result = validate_lab_result(result["id"])  # breaches 10.0 -> exceedance
        exceedance = validate_success(
            api.get_exceedance(result["exceedance_id"], READER)
        )
        corrective_action_id = exceedance["corrective_action_id"]

        dmr = create_dmr(outfall["id"], officer_id="co-1")
        plan = create_swppp_plan(permit["id"], plan_title="Plan A", version_label="rev-A")
        plan = activate_swppp_plan(plan["id"])
        inspection = create_inspection(plan["id"], "2026-08-10T08:00:00Z")
        renewal = create_renewal_application(permit["id"], "2031-12-31T00:00:00Z")
        order = create_consent_order(
            exceedance["id"], base_penalty_cents=1000, daily_accrual_cents=0,
            statutory_cap_cents=5_000_000,
        )

        # Every single-resource GET round-trips the persisted state.
        resp = api.get_permit(permit["id"], READER)
        assert resp.json()["response_type"] == "object"
        assert validate_success(api.get_permit(permit["id"], READER))["permit_number"] == "NPDES-EP1"
        assert validate_success(api.get_outfall(outfall["id"], READER))["outfall_number"] == "001"
        assert validate_success(
            api.get_effluent_limit(limit["id"], READER)
        )["limit_value"] == 10.0
        assert validate_success(
            api.get_sampling_event(sample["id"], READER)
        )["schedule_status"] == "CLOSED", "sample auto-closed once all results VALIDATED"
        assert validate_success(
            api.get_lab_result(result["id"], READER)
        )["validation_status"] == "VALIDATED"
        assert validate_success(
            api.get_exceedance(exceedance["id"], READER)
        )["notification_status"] == "PENDING_ORAL"
        assert validate_success(api.get_dmr(dmr["id"], READER))["status"] == "DRAFT"
        assert validate_success(api.get_swppp_plan(plan["id"], READER))["status"] == "ACTIVE"
        assert validate_success(
            api.get_inspection(inspection["id"], READER)
        )["status"] == "SCHEDULED"
        assert validate_success(
            api.get_corrective_action(corrective_action_id, READER)
        )["status"] == "OPEN"
        assert validate_success(
            api.get_renewal_application(renewal["id"], READER)
        )["status"] == "SUBMITTED"
        assert validate_success(
            api.get_consent_order(order["id"], READER)
        )["status"] == "PROPOSED"
