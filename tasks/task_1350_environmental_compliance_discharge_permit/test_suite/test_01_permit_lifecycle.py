"""Permit and outfall lifecycle: creation defaults, issuance gates, shutdown
cascades and expiry sweeps (PRD §2.5, §2.9, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_instant_equals,
    assert_outfall,
    assert_permit,
    create_active_permit,
    create_effluent_limit,
    create_outfall,
    create_outfall_payload,
    create_permit,
    create_permit_payload,
    get_outfall_version,
    get_permit_state,
    is_iso8601_timestamp,
    is_valid_uuid,
    schedule_sample,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.fixtures import EM

ANY_HEADERS = TEST_USERS["field_sampler_headers"]  # reads are open to every role (PRD §2.1)

class TestPermitCreation:
    def test_permit_create_initializes_system_state(self, api):
        """PRD §3.1: "A new permit stands in `DRAFT`, with `superseded_by_permit_id` null,
        both compliance counters at zero and `compliance_posture` at `GOOD_STANDING`."

        Design: Corner/entities/permit_create_ignores_system_and_computed_fields
        """
        resp = api.create_permit(create_permit_payload(permit_number="NPDES-ENT1"), EM)
        data = validate_success(resp, expected_status=201)
        assert_permit(data)
        assert data["status"] == "DRAFT"
        assert data["compliance_posture"] == "GOOD_STANDING"
        assert data["open_corrective_action_count"] == 0
        assert data["open_exceedance_count"] == 0
        assert data["superseded_by_permit_id"] is None

        fetched = validate_success(api.get_permit(data["id"], ANY_HEADERS))
        assert fetched["id"] == data["id"]
        assert is_valid_uuid(fetched["id"])
        assert is_iso8601_timestamp(fetched["created_at"])
        assert is_iso8601_timestamp(fetched["updated_at"])
        assert isinstance(fetched["version"], int)

    def test_permit_create_rejects_expiration_not_after_effective(self, api):
        """PRD §3.1: "the expiration must be strictly after the effective date,
        else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/permit_create_rejects_expiration_not_after_effective
        """
        payload = create_permit_payload(
            permit_number="NPDES-ENT5",
            effective_date="2026-01-01T00:00:00Z",
            expiration_date="2026-01-01T00:00:00Z",
        )
        resp = api.create_permit(payload, EM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        data, meta = validate_paginated(api.list_permits(ANY_HEADERS))
        assert data == [] and meta["total_count"] == 0, "no permit may be persisted"

    def test_get_permit_not_found(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the corresponding
        404: the resource-specific `ERR_PERMIT_NOT_FOUND` ... where the path names such a
        resource, or the generic `ERR_NOT_FOUND` otherwise."

        Design: Corner/entities/get_permit_not_found
        """
        resp = api.get_permit(NON_EXISTENT_UUID, ANY_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_FOUND)

    def test_list_permits_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/list_permits_pagination_envelope
        """
        for number in ("NPDES-PAG1", "NPDES-PAG2", "NPDES-PAG3"):
            create_permit(
                permit_number=number, facility_name="P", receiving_water_body="R"
            )
        resp = api.list_permits(ANY_HEADERS, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, "page must hold exactly the requested 2 rows"
        assert meta["limit"] == 2 and meta["offset"] == 0
        assert meta["total_count"] == 3 and meta["has_more"] is True
        for row in data:
            assert_permit(row)

    def test_duplicate_permit_number_rejected(self, api):
        """PRD §3.1: "The permit number must be globally unique across all permits —
        a duplicate is rejected with `ERR_DUPLICATE_PERMIT_NUMBER`"

        Design: Corner/validations/duplicate_permit_number_rejected
        """
        create_permit(permit_number="NPDES-VAL1", facility_name="First Mill")
        resp = api.create_permit(
            create_permit_payload(
                permit_number="NPDES-VAL1",
                facility_name="Second Mill",
                receiving_water_body="Other River",
            ),
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERMIT_NUMBER)

class TestOutfallCreation:
    def test_outfall_create_applies_status_default(self, api):
        """PRD §3.1: "Every outfall begins life `ACTIVE`." and "Outfalls can be
        listed filtered by `permit_id` or `status`."

        Design: Corner/entities/outfall_create_applies_status_default
        """
        permit = create_permit(permit_number="NPDES-ENT2")
        outfall = create_outfall(permit["id"], outfall_number="001")
        assert_outfall(outfall)
        assert outfall["status"] == "ACTIVE", "default status must be applied"

        data, meta = validate_paginated(
            api.list_outfalls(ANY_HEADERS, params={"permit_id": permit["id"]})
        )
        assert meta["total_count"] == 1 and len(data) == 1
        assert data[0]["id"] == outfall["id"]

    def test_outfall_create_rejected_when_permit_terminated(self, api):
        """PRD §3.1: "Outfalls may be added while the permit is `DRAFT` or `ACTIVE`;
        against any other permit status the creation fails with `ERR_PERMIT_NOT_ACTIVE`."

        Design: Corner/entities/outfall_create_rejected_when_permit_terminated
        """
        env = create_active_permit(permit_number="NPDES-ENT9")
        validate_success(api.terminate_permit(env["permit"]["id"], EM))
        assert get_permit_state(env["permit"]["id"])["status"] == "TERMINATED"

        resp = api.create_outfall(
            create_outfall_payload(env["permit"]["id"], outfall_number="002"), EM
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

    def test_get_outfall_not_found(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the corresponding
        404: the resource-specific `ERR_PERMIT_NOT_FOUND`, `ERR_OUTFALL_NOT_FOUND`, ..."

        Design: Corner/entities/get_outfall_not_found
        """
        resp = api.get_outfall(NON_EXISTENT_UUID, ANY_HEADERS)
        validate_error(resp, ApiErrorId.ERR_OUTFALL_NOT_FOUND)

    def test_duplicate_outfall_number_within_permit_rejected(self, api):
        """PRD §3.1: "an `outfall_number` that must be unique within that permit
        (`ERR_DUPLICATE_OUTFALL_NUMBER`)"

        Design: Corner/validations/duplicate_outfall_number_within_permit_rejected
        """
        p1 = create_permit(permit_number="NPDES-VAL2A", facility_name="M1")
        p2 = create_permit(permit_number="NPDES-VAL2B", facility_name="M2")
        create_outfall(p1["id"], outfall_number="001")

        resp = api.create_outfall(create_outfall_payload(p1["id"], outfall_number="001"), EM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OUTFALL_NUMBER)

        other = create_outfall(p2["id"], outfall_number="001")
        assert other["outfall_number"] == "001", (
            "uniqueness is per-permit: the same number under another permit succeeds"
        )

class TestPermitIssuance:
    def test_permit_issue_success_from_draft(self, api):
        """PRD §3.1: "Issuance moves the permit `DRAFT → ACTIVE`, increments its
        `version` and appends a `PERMIT_ISSUED` audit entry."

        Design: Corner/state_machines/permit_issue_success_from_draft
        """
        permit = create_permit(permit_number="NPDES-SM1")
        outfall = create_outfall(permit["id"])
        create_effluent_limit(outfall["id"])
        version_before = permit["version"]

        issued = validate_success(api.issue_permit(permit["id"], EM))
        assert issued["status"] == "ACTIVE"
        assert issued["version"] == version_before + 1, (
            "issuance increments the permit's version"
        )

    def test_permit_issue_rejected_when_not_draft(self, api):
        """PRD §3.1: "the permit must be in `DRAFT` (`ERR_PERMIT_NOT_IN_DRAFT`)"

        Design: Corner/state_machines/permit_issue_rejected_when_not_draft
        """
        env = create_active_permit(permit_number="NPDES-SM2")
        resp = api.issue_permit(env["permit"]["id"], EM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_IN_DRAFT)

    def test_permit_issue_rejected_without_outfall(self, api):
        """PRD §3.1: "at least one `ACTIVE` outfall must exist for the permit
        (`ERR_PERMIT_NO_OUTFALL`)"

        Design: Corner/state_machines/permit_issue_rejected_without_outfall
        """
        permit = create_permit(permit_number="NPDES-SM3")
        resp = api.issue_permit(permit["id"], EM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NO_OUTFALL)
        assert get_permit_state(permit["id"])["status"] == "DRAFT"

    def test_permit_issue_rejected_when_outfall_lacks_active_limit(self, api):
        """PRD §3.1: "every `ACTIVE` outfall of the permit must hold at least one
        `ACTIVE` effluent limit (`ERR_OUTFALL_NO_ACTIVE_LIMIT`)"

        Design: Corner/state_machines/permit_issue_rejected_when_outfall_lacks_active_limit
        """
        permit = create_permit(permit_number="NPDES-SM4")
        create_outfall(permit["id"])
        resp = api.issue_permit(permit["id"], EM)
        validate_error(resp, ApiErrorId.ERR_OUTFALL_NO_ACTIVE_LIMIT)

    def test_permit_issue_rejected_before_effective_date(self, api):
        """PRD §3.1: "the logical clock must sit at or after `effective_date` and
        strictly before `expiration_date` (`ERR_PERMIT_NOT_ISSUABLE`)"

        Design: Corner/state_machines/permit_issue_rejected_before_effective_date
        """
        permit = create_permit(
            permit_number="NPDES-SM5",
            effective_date="2027-01-01T00:00:00Z",
            expiration_date="2030-12-31T00:00:00Z",
        )
        outfall = create_outfall(permit["id"])
        create_effluent_limit(outfall["id"])
        resp = api.issue_permit(permit["id"], EM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUABLE)

class TestPermitShutdownAndOutfallStates:
    def test_permit_terminate_from_draft_rejected(self, api):
        """PRD §3.1: "Termination, performed by an `EnvironmentalManager`, requires
        the permit `ACTIVE` (`ERR_PERMIT_NOT_ACTIVE`)"

        Design: Corner/state_machines/permit_terminate_from_draft_rejected
        """
        permit = create_permit(permit_number="NPDES-SM6")
        resp = api.terminate_permit(permit["id"], EM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

    def test_outfall_deactivate_success_cancels_scheduled_samples(self, api):
        """PRD §3.1: "Deactivation requires the outfall `ACTIVE` (`ERR_OUTFALL_INACTIVE`),
        moves it to `INACTIVE`, cancels every one of its sampling events still in
        `SCHEDULED`, and increments its `version`."

        Design: Corner/state_machines/outfall_deactivate_success_cancels_scheduled_samples
        """
        env = create_active_permit(permit_number="NPDES-SM7")
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-20T08:00:00Z")
        version_before = get_outfall_version(env["outfall"]["id"])

        deactivated = validate_success(api.deactivate_outfall(env["outfall"]["id"], EM))
        assert deactivated["status"] == "INACTIVE"
        assert deactivated["version"] == version_before + 1
        sample_after = validate_success(api.get_sampling_event(sample["id"], ANY_HEADERS))
        assert sample_after["schedule_status"] == "CANCELLED", (
            "the outfall's SCHEDULED events are cancelled by the cascade"
        )

    def test_outfall_reactivate_from_active_rejected(self, api):
        """PRD §3.1: "Reactivation requires the outfall `INACTIVE`
        (`ERR_OUTFALL_NOT_INACTIVE`)"

        Design: Corner/state_machines/outfall_reactivate_from_active_rejected
        """
        permit = create_permit(permit_number="NPDES-SM8")
        outfall = create_outfall(permit["id"])
        resp = api.reactivate_outfall(outfall["id"], EM)
        validate_error(resp, ApiErrorId.ERR_OUTFALL_NOT_INACTIVE)

    def test_outfall_reactivate_blocked_when_permit_not_active(self, api):
        """PRD §3.1: "Reactivation requires the outfall `INACTIVE`
        (`ERR_OUTFALL_NOT_INACTIVE`) and its parent permit `ACTIVE`
        (`ERR_PERMIT_NOT_ACTIVE`), and returns it to `ACTIVE`."

        Design: Corner/state_machines/outfall_reactivate_blocked_when_permit_not_active
        """
        env = create_active_permit(permit_number="NPDES-SM9")
        validate_success(api.terminate_permit(env["permit"]["id"], EM))
        outfall = validate_success(api.get_outfall(env["outfall"]["id"], ANY_HEADERS))
        assert outfall["status"] == "INACTIVE", "termination cascade deactivates outfalls"

        resp = api.reactivate_outfall(env["outfall"]["id"], EM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

class TestPermitCascadesAndSweep:
    def test_cascade_permit_terminate_deactivates_outfalls_and_cancels_samples(self, api):
        """PRD §2.9: "When a permit leaves service — through expiry, termination, or
        supersession by a renewal — every one of its `ACTIVE` outfalls transitions to
        `INACTIVE`, and every sampling event of those outfalls still in `SCHEDULED`
        transitions to `CANCELLED`."

        Design: Corner/cross_cutting_layers/cascade_permit_terminate_deactivates_outfalls_and_cancels_samples
        """
        env = create_active_permit(permit_number="NPDES-LAY1")
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-20T08:00:00Z")

        terminated = validate_success(api.terminate_permit(env["permit"]["id"], EM))
        assert terminated["status"] == "TERMINATED"
        outfall = validate_success(api.get_outfall(env["outfall"]["id"], ANY_HEADERS))
        assert outfall["status"] == "INACTIVE"
        sample_after = validate_success(api.get_sampling_event(sample["id"], ANY_HEADERS))
        assert sample_after["schedule_status"] == "CANCELLED"

    def test_scheduled_sweep_flips_permit_expired_and_cascades(self, api):
        """PRD §3.1: "Expiry is the sweep's work: when the logical clock reaches or
        passes `expiration_date` on an `ACTIVE` permit, the permit transitions
        `ACTIVE → EXPIRED` with the same outfall and sampling-event cascade and a
        `PERMIT_EXPIRED` audit entry recorded against the `system` actor."
        PRD §2.5: "The response reports the new `current_utc` and a `transitions_applied`
        count."

        Design: Corner/cross_cutting_layers/scheduled_sweep_flips_permit_expired_and_cascades
        """
        env = create_active_permit(
            permit_number="NPDES-LAY5", expiration_date="2026-08-10T00:00:00Z"
        )
        # The sample's 24h window (ending 2026-08-10T08:00:00Z) has NOT elapsed at
        # the sweep instant, so it is not MISSED-eligible: the only sweep transition
        # that can claim it is the permit-expiry cascade to CANCELLED.
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-09T08:00:00Z")

        sweep = set_clock("2026-08-10T00:00:00Z")
        # PRD §2.5 pins only that the response carries a `transitions_applied`
        # count of the time-based transitions the sweep applied — it does not
        # pin whether cascade hops (outfall/sample) are counted, so assert only
        # that the permit-expiry transition itself was counted.
        assert sweep["transitions_applied"] >= 1, (
            "the permit-expiry transition is applied and counted by the sweep"
        )
        assert_instant_equals(sweep["current_utc"], "2026-08-10T00:00:00Z", "current_utc")

        permit = get_permit_state(env["permit"]["id"])
        assert permit["status"] == "EXPIRED"
        outfall = validate_success(api.get_outfall(env["outfall"]["id"], ANY_HEADERS))
        assert outfall["status"] == "INACTIVE"
        sample_after = validate_success(api.get_sampling_event(sample["id"], ANY_HEADERS))
        assert sample_after["schedule_status"] == "CANCELLED"

    def test_immediate_read_after_write_reflects_mutation(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §3.1: "Issuance moves the permit `DRAFT → ACTIVE`".

        Design: Corner/consistency_model/immediate_read_after_write_reflects_mutation
        """
        permit = create_permit(permit_number="NPDES-CON1")
        outfall = create_outfall(permit["id"])
        create_effluent_limit(outfall["id"])

        issued = validate_success(api.issue_permit(permit["id"], EM))
        assert issued["status"] == "ACTIVE", "mutation visible in the same response"
        fetched = validate_success(api.get_permit(permit["id"], ANY_HEADERS))
        assert fetched["status"] == "ACTIVE", "subsequent read agrees with the write"
