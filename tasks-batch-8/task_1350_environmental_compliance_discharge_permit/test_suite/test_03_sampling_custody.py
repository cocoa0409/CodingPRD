"""Sampling events and chain of custody: scheduling gates, collection,
the auto-appended SEAL record, custody ordering, sweep-driven MISSED (PRD §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_custody_to_analyzed,
    assert_custody_record,
    assert_instant_equals,
    assert_sampling_event,
    collect_sample,
    create_active_permit,
    create_custody_event_payload,
    create_effluent_limit,
    create_outfall,
    create_permit,
    create_sampling_event_payload,
    make_field_sampler_headers,
    make_lab_analyst_headers,
    schedule_sample,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.fixtures import EM

ANY_HEADERS = TEST_USERS["regulator_headers"]  # reads are open to every role (PRD §2.1)

class TestSamplingEventCreation:
    def test_sampling_event_create_applies_defaults(self, api):
        """PRD §3.2: "optionally `collection_window_hours` — the symmetric window
        around the planned instant, defaulting to 24 hours and accepted between 1
        and 168 hours inclusive" and "A new event starts with `schedule_status`
        `SCHEDULED` and `custody_status` `NOT_SEALED`, with `collected_at` and
        `collected_by_user_id` null."

        Design: Corner/entities/sampling_event_create_applies_defaults
        """
        env = create_active_permit(permit_number="NPDES-ENT3")
        resp = api.create_sampling_event(
            create_sampling_event_payload(
                env["outfall"]["id"], "TSS", "2026-08-10T08:00:00Z"
            ),
            make_field_sampler_headers("sampler-1"),
        )
        data = validate_success(resp, expected_status=201)
        assert_sampling_event(data)
        assert data["collection_window_hours"] == 24, "default 24h window applied"
        assert data["schedule_status"] == "SCHEDULED"
        assert data["custody_status"] == "NOT_SEALED"
        assert data["collected_at"] is None
        assert data["collected_by_user_id"] is None

    def test_sample_schedule_rejected_without_covering_limit(self, api):
        """PRD §3.2: "an `ACTIVE` effluent limit for that outfall and parameter must
        exist whose effective range covers `scheduled_for` (`ERR_NO_ACTIVE_LIMIT`)."

        Design: Corner/validations/sample_schedule_rejected_without_covering_limit
        """
        env = create_active_permit(
            permit_number="NPDES-VAL5", parameter_code="COPPER", limit_value=1.0
        )
        resp = api.create_sampling_event(
            create_sampling_event_payload(
                env["outfall"]["id"], "TSS", "2026-08-10T08:00:00Z"
            ),
            make_field_sampler_headers("sampler-1"),
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_LIMIT)

    def test_error_permit_not_active_on_sample_schedule(self, api):
        """PRD §3.2: "the permit reached through the outfall must be `ACTIVE`
        (`ERR_PERMIT_NOT_ACTIVE`)"

        Design: Corner/errors/error_permit_not_active_on_sample_schedule
        """
        permit = create_permit(permit_number="NPDES-ERR11")
        outfall = create_outfall(permit["id"])
        create_effluent_limit(outfall["id"])  # permit stays DRAFT
        resp = api.create_sampling_event(
            create_sampling_event_payload(
                outfall["id"], "TSS", "2026-08-10T08:00:00Z"
            ),
            make_field_sampler_headers("sampler-1"),
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

    def test_error_outfall_inactive_on_sample_schedule(self, api):
        """PRD §3.2: "the outfall itself must be `ACTIVE` (`ERR_OUTFALL_INACTIVE`)"

        Design: Corner/errors/error_outfall_inactive_on_sample_schedule
        """
        env = create_active_permit(permit_number="NPDES-ERR12")
        validate_success(api.deactivate_outfall(env["outfall"]["id"], EM))
        resp = api.create_sampling_event(
            create_sampling_event_payload(
                env["outfall"]["id"], "TSS", "2026-08-10T08:00:00Z"
            ),
            make_field_sampler_headers("sampler-1"),
        )
        validate_error(resp, ApiErrorId.ERR_OUTFALL_INACTIVE)

class TestCollectionAndCancellation:
    def test_sample_collect_success_seals_custody(self, api):
        """PRD §3.2: "A successful collection stamps `collected_at` with the logical
        clock and `collected_by_user_id` with the caller, moves the schedule dimension
        `SCHEDULED → COLLECTED`, moves custody `NOT_SEALED → SEALED`, automatically
        appends a `SEAL` chain-of-custody record as `sequence_index` 1, increments
        the event's `version` and appends a `SAMPLE_COLLECTED` audit entry."

        Design: Corner/state_machines/sample_collect_success_seals_custody
        """
        env = create_active_permit(permit_number="NPDES-SM12")
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-10T08:00:00Z")
        set_clock("2026-08-10T09:00:00Z")

        collected = validate_success(
            api.collect_sampling_event(sample["id"], make_field_sampler_headers("sampler-1"))
        )
        assert collected["schedule_status"] == "COLLECTED"
        assert collected["custody_status"] == "SEALED"
        assert_instant_equals(collected["collected_at"], "2026-08-10T09:00:00Z", "collected_at")
        assert collected["collected_by_user_id"] == "sampler-1"

        chain, meta = validate_paginated(api.list_custody_events(sample["id"], ANY_HEADERS))
        assert len(chain) == 1 and meta["total_count"] == 1
        assert chain[0]["event_type"] == "SEAL" and chain[0]["sequence_index"] == 1

    def test_sample_cancel_after_collect_rejected(self, api):
        """PRD §3.2: "A `FieldSampler` may cancel an event whose schedule status is
        `SCHEDULED` (`ERR_SAMPLE_NOT_SCHEDULED`)"

        Design: Corner/state_machines/sample_cancel_after_collect_rejected
        """
        env = create_active_permit(permit_number="NPDES-SM14")
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-10T08:00:00Z")
        collect_sample(sample["id"], clock_iso="2026-08-10T08:00:00Z")

        resp = api.cancel_sampling_event(sample["id"], make_field_sampler_headers("sampler-1"))
        validate_error(resp, ApiErrorId.ERR_SAMPLE_NOT_SCHEDULED)

    def test_sample_terminal_lockdown_cancelled(self, api):
        """PRD §3.2: "A `FieldSampler` may cancel an event whose schedule status is
        `SCHEDULED` (`ERR_SAMPLE_NOT_SCHEDULED`)" and collection is only possible
        "while the event's schedule status is `SCHEDULED` (`ERR_SAMPLE_NOT_SCHEDULED`)".

        Design: Corner/state_machines/sample_terminal_lockdown_cancelled
        """
        env = create_active_permit(permit_number="NPDES-SM35")
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-10T08:00:00Z")
        validate_success(
            api.cancel_sampling_event(sample["id"], make_field_sampler_headers("sampler-1"))
        )
        set_clock("2026-08-10T08:00:00Z")

        resp_collect = api.collect_sampling_event(
            sample["id"], make_field_sampler_headers("sampler-1")
        )
        validate_error(resp_collect, ApiErrorId.ERR_SAMPLE_NOT_SCHEDULED)
        resp_cancel = api.cancel_sampling_event(
            sample["id"], make_field_sampler_headers("sampler-1")
        )
        validate_error(resp_cancel, ApiErrorId.ERR_SAMPLE_NOT_SCHEDULED)

    def test_sample_auto_missed_on_clock_sweep(self, api):
        """PRD §2.5: "A sampling event still `SCHEDULED` whose collection window has
        fully elapsed transitions to `MISSED`."

        Design: Corner/state_machines/sample_auto_missed_on_clock_sweep
        """
        env = create_active_permit(permit_number="NPDES-SM15")
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-05T08:00:00Z")

        # Window ends 2026-08-06T08:00:00Z; one second past it the sweep fires.
        set_clock("2026-08-06T08:00:01Z")
        after = validate_success(api.get_sampling_event(sample["id"], ANY_HEADERS))
        assert after["schedule_status"] == "MISSED"

    def test_error_sample_not_found_on_collect(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the
        corresponding 404: the resource-specific ... `ERR_SAMPLE_NOT_FOUND` ..."

        Design: Corner/errors/error_sample_not_found_on_collect
        """
        resp = api.collect_sampling_event(
            NON_EXISTENT_UUID, make_field_sampler_headers("sampler-1")
        )
        validate_error(resp, ApiErrorId.ERR_SAMPLE_NOT_FOUND)

class TestChainOfCustody:
    def test_custody_record_immutable_no_version(self, api):
        """PRD §2.4: "a ChainOfCustodyRecord, a PenaltyPayment and an AuditLogEntry
        each carry `id` and `created_at` only — `updated_at` and `version` are absent
        on these three, because they are never mutated after creation."
        PRD §3.2: "The full chain for a sample is listable, returned in
        `sequence_index` order".

        Design: Corner/entities/custody_record_immutable_no_version
        """
        env = create_active_permit(permit_number="NPDES-ENT7")
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-10T08:00:00Z")
        collect_sample(sample["id"], clock_iso="2026-08-10T08:00:00Z", sampler_id="sampler-1")

        transfer = validate_success(
            api.append_custody_event(
                sample["id"],
                create_custody_event_payload(
                    "TRANSFER", "2026-08-10T09:00:00Z",
                    from_party="sampler", to_party="courier",
                ),
                make_field_sampler_headers("sampler-1"),
            ),
            expected_status=201,
        )
        assert_custody_record(transfer)
        assert transfer["sequence_index"] == 2
        assert transfer["recorded_by_user_id"] == "sampler-1"

        chain, meta = validate_paginated(api.list_custody_events(sample["id"], ANY_HEADERS))
        assert len(chain) == 2 and meta["total_count"] == 2
        assert [r["sequence_index"] for r in chain] == [1, 2], "ordered by sequence_index"
        assert chain[0]["event_type"] == "SEAL" and chain[1]["event_type"] == "TRANSFER"
        for record in chain:
            assert_custody_record(record)
        assert chain[0]["recorded_by_user_id"] == "sampler-1", (
            "the auto-appended SEAL record is recorded against the collecting caller"
        )

    def test_custody_receive_lab_from_sealed_rejected(self, api):
        """PRD §3.2: "Any other pairing of event type to current custody position is
        rejected with `ERR_CUSTODY_OUT_OF_ORDER`."

        Design: Corner/state_machines/custody_receive_lab_from_sealed_rejected
        """
        env = create_active_permit(permit_number="NPDES-SM16")
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-10T08:00:00Z")
        collect_sample(sample["id"], clock_iso="2026-08-10T08:00:00Z")

        resp = api.append_custody_event(
            sample["id"],
            create_custody_event_payload(
                "RECEIVE_LAB", "2026-08-10T09:00:00Z",
                from_party="courier", to_party="lab",
            ),
            make_lab_analyst_headers("analyst-1"),
        )
        validate_error(resp, ApiErrorId.ERR_CUSTODY_OUT_OF_ORDER)
        after = validate_success(api.get_sampling_event(sample["id"], ANY_HEADERS))
        assert after["custody_status"] == "SEALED"

    def test_sample_schedule_and_custody_dimensions_evolve_independently(self, api):
        """PRD §3.2: "A sampling event carries two independent state dimensions from
        this point on. The schedule dimension runs `SCHEDULED → COLLECTED → CLOSED`,
        with `MISSED` and `CANCELLED` as terminal drop-offs; the custody dimension
        begins only at collection and runs `SEALED → IN_TRANSIT → LAB_RECEIVED →
        ANALYZED`."

        Design: Corner/state_machines/sample_schedule_and_custody_dimensions_evolve_independently
        """
        env = create_active_permit(permit_number="NPDES-SM17")
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-10T08:00:00Z")
        collect_sample(sample["id"], clock_iso="2026-08-10T08:00:00Z")
        advance_custody_to_analyzed(sample["id"], "2026-08-10T08:00:00Z")

        after = validate_success(api.get_sampling_event(sample["id"], ANY_HEADERS))
        assert after["schedule_status"] == "COLLECTED", (
            "custody steps do not move the schedule dimension"
        )
        assert after["custody_status"] == "ANALYZED"

        chain, _ = validate_paginated(api.list_custody_events(sample["id"], ANY_HEADERS))
        assert [r["event_type"] for r in chain] == [
            "SEAL", "TRANSFER", "RECEIVE_LAB", "ANALYSIS_START",
        ]
        assert [r["sequence_index"] for r in chain] == [1, 2, 3, 4]
