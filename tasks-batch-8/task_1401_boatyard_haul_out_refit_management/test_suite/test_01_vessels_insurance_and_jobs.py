"""Vessel registration, insurance gating, and refit-job opening."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_insurance,
    api_client,
    assert_vessel,
    create_refit_job,
    create_vessel,
    create_vessel_payload,
    create_vessel_with_insurance,
    get_job,
    is_valid_uuid,
    submit_refit_job,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

SW = TEST_USERS["service_writer_headers"]
YM = TEST_USERS["yard_manager_headers"]


class TestVesselRegistration:

    def test_vessel_creation_returns_201_with_system_fields(self):
        """PRD section 2.4: "Every persisted resource carries an `id` that is
        a server-minted UUID with no type prefix. Most resources additionally
        carry `created_at` and `updated_at` (both ISO 8601 UTC timestamps with
        three fractional digits) and a `version` integer that increments by
        one on every mutation of the resource."
        PRD section 3.1: "Registration captures the vessel's `name`, the
        owner's display `owner_name`, the `owner_user_id` that later scopes
        every `Owner`-role action on this vessel, the length overall
        `loa_ft`, the `beam_ft`, the `hull_type` (`POWER` or `SAIL`), and the
        `displacement_tons` used at lift time."

        Design: Corner/entities/vessel_creation_returns_201_with_system_fields
        """
        resp = api_client.create_vessel(
            create_vessel_payload(
                name="MV Nova", owner_name="O N", owner_user_id="owner-1",
                loa_ft=40, beam_ft=13, hull_type="POWER",
                displacement_tons=20),
            SW,
        )
        data = validate_success(resp, expected_status=201)
        assert_vessel(data)
        assert is_valid_uuid(data["id"]), "server must mint the vessel id"
        assert data["loa_ft"] == 40, "loa_ft must echo the registered value"
        assert data["hull_type"] == "POWER"
        assert data["owner_user_id"] == "owner-1"

    def test_vessel_list_pagination_and_owner_filter(self):
        """PRD section 2.3: "List endpoints accept `limit` and `offset` query
        parameters." and "The `meta` envelope of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD section 3.1: "Vessels can be listed with pagination, optionally
        filtered by `owner_user_id`, and fetched individually by any role."

        Design: Corner/entities/vessel_list_pagination_and_owner_filter
        """
        create_vessel(name="MV One", owner_user_id="owner-1", loa_ft=30,
                      beam_ft=10, hull_type="POWER", displacement_tons=10)
        v2 = create_vessel(name="MV Two", owner_user_id="owner-2", loa_ft=32,
                           beam_ft=11, hull_type="SAIL", displacement_tons=12)

        page, meta = validate_paginated(
            api_client.list_vessels(SW, params={"limit": 1}))
        assert meta["total_count"] == 2, \
            f"expected total_count 2, got {meta['total_count']}"
        assert meta["has_more"] is True, "limit=1 over 2 vessels has more"
        assert len(page) == 1

        filtered, meta2 = validate_paginated(
            api_client.list_vessels(SW, params={"owner_user_id": "owner-2"}))
        assert meta2["total_count"] == 1
        assert [v["id"] for v in filtered] == [v2["id"]], \
            "owner filter must return exactly the owner-2 vessel"

    def test_vessel_not_found_returns_404(self):
        """PRD section 2.9: "Existence comes fourth — path- and
        body-referenced identifiers (vessel, job, slot, row, assignment, work
        order, part, event, hold, entry) are resolved left to right, and the
        first missing reference yields `ERR_NOT_FOUND`."

        Design: Corner/entities/vessel_not_found_returns_404
        """
        resp = api_client.get_vessel(NON_EXISTENT_UUID, SW)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_vessel_missing_required_loa_returns_invalid_request(self):
        """PRD section 2.9: "Request shape comes fifth — missing required
        fields, invalid types, invalid enum membership, `scheduled_end` not
        strictly after `scheduled_start`, `end_date` before `start_date`,
        non-positive amounts, a `CHARGE` kind submitted through the ledger
        API, or subcontractor labor without a `subcontractor_name` all yield
        `ERR_VALIDATION`."

        Design: Corner/entities/vessel_missing_required_loa_returns_invalid_request
        """
        payload = create_vessel_payload(name="MV Bad", owner_name="O B",
                                        owner_user_id="owner-1")
        del payload["loa_ft"]
        resp = api_client.create_vessel(payload, SW)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_missing_auth_headers_returns_unauthenticated(self):
        """PRD section 2.1: "Every request carries two headers: `X-User-ID`
        and `X-User-Role`. A request missing either header, or presenting a
        role that is not one of the declared roles below, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        resp = api_client.list_vessels({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestJobOpening:

    def test_job_system_status_input_ignored(self):
        """PRD section 3.2: "The new job starts in `DRAFT`."

        Design: Corner/entities/job_system_status_input_ignored
        """
        vessel = create_vessel(name="MV Sys", owner_user_id="owner-1",
                               loa_ft=30, beam_ft=10, hull_type="POWER",
                               displacement_tons=10)
        resp = api_client.create_refit_job(
            {"vessel_id": vessel["id"], "status": "COMPLETE"}, SW)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT", \
            "a client-supplied status must not change the birth state"

    def test_duplicate_active_job_rejected(self):
        """PRD section 3.2: "One active job per vessel is a hard rule:
        creating a job while the vessel already has a job in any non-terminal
        state is rejected with `ERR_DUPLICATE_ACTIVE_JOB`."

        Design: Corner/validations/duplicate_active_job_rejected
        """
        vessel = create_vessel(name="MV Dup", owner_user_id="owner-1",
                               loa_ft=30, beam_ft=10, hull_type="POWER",
                               displacement_tons=10)
        create_refit_job(vessel["id"])
        resp = api_client.create_refit_job({"vessel_id": vessel["id"]}, SW)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_JOB)

    def test_submit_on_cancelled_job_returns_already_terminal(self):
        """PRD section 3.11: "`CLOSED` and `CANCELLED` are the job's terminal
        states; any state-transition attempt against a terminal job — or
        against a terminal slot, assignment, hold, part, ledger entry, or
        remediated event — is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/submit_on_cancelled_job_returns_already_terminal
        """
        vessel = create_vessel(name="MV Term", owner_user_id="owner-1",
                               loa_ft=30, beam_ft=10, hull_type="POWER",
                               displacement_tons=10)
        job = create_refit_job(vessel["id"])
        cancelled = validate_success(
            api_client.cancel_refit_job(job["id"], SW,
                                        payload={"reason": "Owner walked away"}))
        assert cancelled["status"] == "CANCELLED"
        resp = api_client.submit_refit_job(job["id"], SW)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestJobPatchOcc:

    def test_job_patch_stale_version_rejected(self):
        """PRD section 2.5: "Updating a refit job's editable fields requires
        the request to carry `expected_refit_job_version` holding the job's
        `version` as the client last observed it. If the job's current
        `version` no longer matches — because another writer has mutated the
        job since the client's read — the update is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from
        overwriting state it has not observed."
        PRD section 3.2: "While a job remains in `DRAFT` or `INTAKE`, a
        `ServiceWriter` may still update its `billing_mode` or `scope_notes`;
        this is the OCC-guarded patch described in §2.5, requiring
        `expected_refit_job_version`, and it increments the job's `version`
        by one."

        Design: Corner/complexity_layers/job_patch_occ_stale_version
        """
        vessel = create_vessel(name="MV Occ", owner_user_id="owner-1",
                               loa_ft=30, beam_ft=10, hull_type="POWER",
                               displacement_tons=10)
        job = create_refit_job(vessel["id"])
        observed_version = job["version"]

        patched = validate_success(api_client.patch_refit_job(
            job["id"],
            {"expected_refit_job_version": observed_version,
             "billing_mode": "MONTHLY_CONTRACT"},
            SW))
        assert patched["billing_mode"] == "MONTHLY_CONTRACT"
        assert patched["version"] == observed_version + 1, \
            "a successful patch increments the job's version by one"

        stale = api_client.patch_refit_job(
            job["id"],
            {"expected_refit_job_version": observed_version,
             "scope_notes": "stale edit"},
            SW)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


class TestInsuranceGate:

    def test_submit_rejected_with_expired_by_date_certificate(self):
        """PRD section 3.2: "The submit gate is insurance: the vessel must
        have a qualifying certificate at the current date per the selection
        rule of §3.1; otherwise the submit is rejected with
        `ERR_INSURANCE_MISSING`."
        PRD section 3.1: "The two dates form a half-open coverage window: a
        certificate covers a scheduled operation on date D only when
        `effective_date` is on or before D and `expiry_date` is strictly
        after D — a certificate expiring exactly on the operation date does
        not cover it."

        Design: Difficulty/cross_entity_state_dependency/submit_requires_qualifying_insurance
        """
        from test_helpers import set_clock
        set_clock("2026-08-01T09:00:00Z")
        vessel = create_vessel(name="MV Uninsured", owner_user_id="owner-1",
                               loa_ft=30, beam_ft=10, hull_type="POWER",
                               displacement_tons=10)
        add_insurance(vessel["id"], policy_no="OLD-1",
                      effective_date="2025-01-01", expiry_date="2026-07-01")
        job = create_refit_job(vessel["id"])

        resp = api_client.submit_refit_job(job["id"], SW)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_MISSING)

    def test_submit_succeeds_after_qualifying_certificate_added(self):
        """PRD section 3.2: "Submitting the job moves it from `DRAFT` to
        `INTAKE`."
        PRD section 3.1: "An empty candidate set means no qualifying
        certificate, and the guarded operation is rejected with
        `ERR_INSURANCE_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/submit_requires_qualifying_insurance
        """
        from test_helpers import set_clock
        set_clock("2026-08-01T09:00:00Z")
        vessel = create_vessel(name="MV Reinsured", owner_user_id="owner-1",
                               loa_ft=30, beam_ft=10, hull_type="POWER",
                               displacement_tons=10)
        add_insurance(vessel["id"], policy_no="OLD-1",
                      effective_date="2025-01-01", expiry_date="2026-07-01")
        job = create_refit_job(vessel["id"])
        validate_error(api_client.submit_refit_job(job["id"], SW),
                       ApiErrorId.ERR_INSURANCE_MISSING)

        add_insurance(vessel["id"], policy_no="NEW-1",
                      effective_date="2026-08-01", expiry_date="2027-06-01")
        data = validate_success(api_client.submit_refit_job(job["id"], SW))
        assert data["status"] == "INTAKE", \
            "with a qualifying certificate the job moves DRAFT -> INTAKE"

    def test_slot_booking_uses_latest_expiry_certificate(self):
        """PRD section 3.1: "Among the candidates the selector ranks by
        `expiry_date` descending, breaking ties by `created_at` descending
        (never by `id`)."
        PRD section 3.3: "Third, insurance: the vessel must have a qualifying
        certificate selected per §3.1 whose `expiry_date` is strictly after
        the `scheduled_start` date and whose `liability_coverage_cents` is at
        least 100000000, else the booking is rejected with
        `ERR_INSURANCE_MISSING`."

        Design: Corner/calculations/slot_booking_uses_latest_expiry_certificate
        """
        from test_helpers import create_submitted_job, set_clock
        set_clock("2026-08-01T09:00:00Z")
        vessel, _cert = create_vessel_with_insurance(
            name="MV Sel", owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="POWER", displacement_tons=10, policy_no="SH-1",
            expiry_date="2026-12-01")
        job = create_submitted_job(vessel["id"])

        short = api_client.create_lift_slot(
            {"job_id": job["id"], "kind": "HAUL_OUT",
             "scheduled_start": "2026-12-15T08:00:00Z",
             "scheduled_end": "2026-12-15T09:00:00Z",
             "vessel_displacement_tons": 10},
            YM)
        validate_error(short, ApiErrorId.ERR_INSURANCE_MISSING)

        add_insurance(vessel["id"], policy_no="LG-1",
                      effective_date="2026-06-01", expiry_date="2027-06-01")
        booked = validate_success(api_client.create_lift_slot(
            {"job_id": job["id"], "kind": "HAUL_OUT",
             "scheduled_start": "2026-12-15T08:00:00Z",
             "scheduled_end": "2026-12-15T09:00:00Z",
             "vessel_displacement_tons": 10},
            YM), expected_status=201)
        assert booked["status"] == "BOOKED"
        assert is_valid_uuid(booked["id"])
        assert get_job(job["id"])["status"] == "HAUL_SCHEDULED"
