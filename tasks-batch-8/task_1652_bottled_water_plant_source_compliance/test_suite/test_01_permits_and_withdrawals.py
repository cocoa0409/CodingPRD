"""Permit registration, withdrawal accounting, and the permit lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_permit,
    assert_plant,
    create_permit,
    create_permit_payload,
    create_plant,
    create_plant_payload,
    create_withdrawal_event_payload,
    is_iso8601_timestamp,
    post_withdrawal_event,
    run_compliance,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
)
from test_helpers.fixtures import (
    PLANT_ADMIN, SOURCE_MONITOR, COMPLIANCE_OFFICER, QA1,
)


class TestPlantCreation:
    def test_plant_created_with_computed_defaults(self, api):
        """PRD §3.2: "A newly created plant starts at `GREEN` with
        `ops_run_index` 0 and both bottle pool counters at 0".

        Design: Corner/entities/plant_created_with_computed_defaults
        """
        resp = api.create_plant(create_plant_payload(name="Plant EN1"), PLANT_ADMIN)
        plant = validate_success(resp, expected_status=201)
        assert_plant(plant)
        assert plant["compliance_posture"] == "GREEN"
        assert plant["ops_run_index"] == 0
        assert plant["bottle_gross_pool_units"] == 0
        assert plant["bottle_sanitized_pool_units"] == 0
        assert plant["version"] == 1
        assert is_iso8601_timestamp(plant["created_at"])


class TestPermitBasics:
    def test_permit_retrieval_roundtrip(self, api):
        """PRD §3.1: "A new permit starts in `ACTIVE` status with
        `suspension_reason` null and all four withdrawal aggregates at zero."

        Design: Corner/entities/permit_retrieval_roundtrip
        """
        plant = create_plant("Plant EN2")
        created = create_permit(
            plant["id"], permit_number="SP-EN2", source_classification="WELL",
            daily_cap_gallons=5000, monthly_cap_gallons=100000,
        )
        resp = api.get_permit(created["id"], SOURCE_MONITOR)
        permit = validate_success(resp, expected_status=200)
        assert_permit(permit)
        assert permit["permit_number"] == "SP-EN2"
        assert permit["source_classification"] == "WELL"
        assert permit["status"] == "ACTIVE"
        assert permit["suspension_reason"] is None
        assert permit["withdrawn_month_provisional_gallons"] == 0
        assert permit["withdrawn_month_certified_gallons"] == 0
        assert permit["withdrawn_today_provisional_gallons"] == 0
        assert permit["withdrawn_today_certified_gallons"] == 0

    def test_permit_get_not_found_returns_404(self, api):
        """PRD §2.7: "the first identifier that does not correspond to an
        existing resource yields `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/permit_get_not_found_returns_404
        """
        create_plant("Plant EN4")
        resp = api.get_permit(NON_EXISTENT_UUID, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPermitInputShape:
    def test_permit_missing_daily_cap_rejected(self, api):
        """PRD §2.7 rung 11: "required fields must be present ... violations
        yield `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/permit_missing_daily_cap_rejected
        """
        plant = create_plant("Plant EN5")
        payload = create_permit_payload(permit_number="SP-EN5")
        del payload["daily_cap_gallons"]
        resp = api.create_permit(plant["id"], payload, COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_permit_invalid_source_classification_rejected(self, api):
        """PRD §2.7 rung 11: "required fields must be present, enums in range
        ... violations yield `ERR_INVALID_REQUEST` (HTTP 400)". PRD §3.1: "a
        `source_classification` of `SPRING`, `WELL`, or `MUNICIPAL`".

        Design: Corner/entities/permit_invalid_source_classification_rejected
        """
        plant = create_plant("Plant EN6")
        payload = create_permit_payload(
            permit_number="SP-EN6", source_classification="RIVER",
            daily_cap_gallons=5000, monthly_cap_gallons=100000,
        )
        resp = api.create_permit(plant["id"], payload, COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_permit_cap_relation_inverted_rejected(self, api):
        """PRD §3.1: "The daily cap must be a positive integer, the monthly
        cap must be no less than the daily cap".

        Design: Corner/entities/permit_cap_relation_inverted_rejected
        """
        plant = create_plant("Plant EN7")
        payload = create_permit_payload(
            permit_number="SP-EN7", daily_cap_gallons=10000, monthly_cap_gallons=5000,
        )
        resp = api.create_permit(plant["id"], payload, COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_permit_validity_window_inverted_rejected(self, api):
        """PRD §3.1: "the validity window `valid_from` through `valid_to`. The
        daily cap must be a positive integer, the monthly cap must be no less
        than the daily cap, and `valid_to` must fall after `valid_from`; the
        window itself is inclusive at both ends."

        Design: Corner/entities/permit_validity_window_inverted_rejected
        """
        plant = create_plant("Plant EN8")
        payload = create_permit_payload(
            permit_number="SP-EN8", daily_cap_gallons=5000, monthly_cap_gallons=100000,
            valid_from="2026-06-01", valid_to="2026-01-01",
        )
        resp = api.create_permit(plant["id"], payload, COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestWithdrawalEventInputShape:
    def test_withdrawal_event_zero_gallons_rejected(self, api):
        """PRD §3.1: "Each event carries a `withdrawal_date`, a positive
        integer `gallons`".

        Design: Corner/entities/withdrawal_event_zero_gallons_rejected
        """
        plant = create_plant("Plant EN9")
        permit = create_permit(plant["id"], permit_number="SP-EN9")
        payload = create_withdrawal_event_payload(
            gallons=0, meter_reading_start_gallons=0, meter_reading_end_gallons=0,
            expected_permit_version=permit["version"],
        )
        resp = api.create_withdrawal_event(permit["id"], payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestWithdrawalEventsPagination:
    def test_withdrawal_events_listing_pagination(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned
        ... Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the envelope's `meta` object."

        Design: Corner/entities/withdrawal_events_listing_pagination
        """
        plant = create_plant("Plant EN3")
        permit = create_permit(plant["id"], permit_number="SP-EN3")
        ev1, _ = post_withdrawal_event(permit["id"], gallons=1000)
        ev2, _ = post_withdrawal_event(permit["id"], gallons=2000, meter_start=1000)
        ev3, _ = post_withdrawal_event(permit["id"], gallons=3000, meter_start=3000)

        page1, meta1 = validate_paginated(api.list_permit_withdrawal_events(
            permit["id"], SOURCE_MONITOR, params={"limit": 2, "offset": 0}
        ))
        assert len(page1) == 2, f"page 1 should hold 2 items, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        assert {page1[0]["id"], page1[1]["id"]} == {ev1["id"], ev2["id"]}

        page2, meta2 = validate_paginated(api.list_permit_withdrawal_events(
            permit["id"], SOURCE_MONITOR, params={"limit": 2, "offset": 2}
        ))
        assert len(page2) == 1, f"page 2 should hold 1 item, got {len(page2)}"
        assert page2[0]["id"] == ev3["id"]
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 3


class TestPermitLifecycle:
    def test_permit_suspend_reinstate_roundtrip(self, api):
        """PRD §3.1: "A `ComplianceOfficer` may manually suspend an `ACTIVE`
        permit, which records `suspension_reason` as `MANUAL`" and "A
        successful reinstate returns the permit to `ACTIVE` with
        `suspension_reason` cleared to null and recomputes posture."

        Design: Corner/state_machines/permit_suspend_reinstate_roundtrip
        """
        plant = create_plant("Plant SM1")
        permit = create_permit(plant["id"], permit_number="SP-SM1")

        suspended = validate_success(api.suspend_permit(permit["id"], COMPLIANCE_OFFICER))
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL"

        reinstated = validate_success(api.reinstate_permit(permit["id"], COMPLIANCE_OFFICER))
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspension_reason"] is None

    def test_permit_suspend_twice_second_rejected(self, api):
        """PRD §3.1: "A `ComplianceOfficer` may manually suspend an `ACTIVE`
        permit" — the state machine admits suspend only from ACTIVE; PRD §2.7
        rung 5: "the target resource must be in a state that admits the
        operation ... (`ERR_INVALID_STATE` ...)".

        Design: Corner/state_machines/permit_suspend_twice_second_rejected
        """
        plant = create_plant("Plant SM2")
        permit = create_permit(plant["id"], permit_number="SP-SM2")
        validate_success(api.suspend_permit(permit["id"], COMPLIANCE_OFFICER))

        resp = api.suspend_permit(permit["id"], COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_permit_reinstate_blocked_after_source_fail(self, api):
        """PRD §3.1: "the most recent completed raw-source test for the
        permit — ordered by `collected_at`, ties broken by `created_at`
        ascending — must be a pass, unless none has ever completed. Either
        failure yields `ERR_REINSTATE_BLOCKED` (HTTP 409)."

        Design: Corner/state_machines/permit_reinstate_blocked_after_source_fail
        """
        plant = create_plant("Plant SM3")
        permit = create_permit(plant["id"], permit_number="SP-SM3")
        test = get_success_data(api.create_lab_test(
            plant["id"],
            {"test_type": "SOURCE_RAW", "subject_permit_id": permit["id"],
             "due_date": "2026-08-05"},
            QA1,
        ))
        validate_success(api.record_lab_result(
            test["id"], {"result": "FAIL", "collected_at": "2026-08-03T09:00:00Z"},
            QA1,
        ))
        permit_now = validate_success(api.get_permit(permit["id"], COMPLIANCE_OFFICER))
        assert permit_now["status"] == "SUSPENDED"

        resp = api.reinstate_permit(permit["id"], COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_REINSTATE_BLOCKED)
        permit_after = validate_success(api.get_permit(permit["id"], COMPLIANCE_OFFICER))
        assert permit_after["status"] == "SUSPENDED"

    def test_permit_close_terminal_lockdown(self, api):
        """PRD §3.1: "When the compliance run observes the current logical
        date past `valid_to`, a permit in `ACTIVE` or `SUSPENDED` moves to
        `EXPIRED` and posture is recomputed; an `EXPIRED` permit may then be
        closed by a `ComplianceOfficer`, reaching the terminal `CLOSED`
        state."

        Design: Corner/state_machines/permit_close_terminal_lockdown
        """
        plant = create_plant("Plant SM4")
        permit = create_permit(
            plant["id"], permit_number="SP-SM4",
            valid_from="2026-01-01", valid_to="2026-07-31",
        )
        validate_success(api.suspend_permit(permit["id"], COMPLIANCE_OFFICER))

        summary = validate_success(api.run_compliance(plant["id"], PLANT_ADMIN))
        assert summary["permits_expired"] == 1, "SUSPENDED permits expire too"

        expired = validate_success(api.get_permit(permit["id"], COMPLIANCE_OFFICER))
        assert expired["status"] == "EXPIRED"

        closed = validate_success(api.close_permit(permit["id"], COMPLIANCE_OFFICER))
        assert closed["status"] == "CLOSED"

        resp = api.suspend_permit(permit["id"], COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestWithdrawalCorrectionPaths:
    def test_withdrawal_event_void_of_finalized_rejected(self, api):
        """PRD §3.1: "Voiding a `FINALIZED` event is rejected with
        `ERR_EVENT_ALREADY_FINALIZED` (HTTP 409) — finalized history must be
        corrected by supersede instead".

        Design: Corner/state_machines/withdrawal_event_void_of_finalized_rejected
        """
        plant = create_plant("Plant SM5")
        permit = create_permit(plant["id"], permit_number="SP-SM5")
        ev, _ = post_withdrawal_event(permit["id"], gallons=1000)
        set_clock("2026-08-02T00:00:00Z")
        run_compliance(plant["id"])
        finalized = validate_success(api.get_withdrawal_event(ev["id"], SOURCE_MONITOR))
        assert finalized["status"] == "FINALIZED"

        resp = api.void_withdrawal_event(ev["id"], SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_EVENT_ALREADY_FINALIZED)

    def test_withdrawal_event_supersede_correction_chain(self, api):
        """PRD §3.1: "a new event created with `supersedes_event_id` pointing
        at an existing event of the same permit voids the referenced event and
        takes its place as a fresh `RECORDED` event" and "The cap check for
        the replacement excludes the event being superseded".

        Design: Corner/state_machines/withdrawal_event_supersede_correction_chain
        """
        plant = create_plant("Plant SM6")
        permit = create_permit(plant["id"], permit_number="SP-SM6")
        ev1, _ = post_withdrawal_event(permit["id"], gallons=5000)

        ev2, permit_after = post_withdrawal_event(
            permit["id"], gallons=5500, meter_start=5000, supersedes_event_id=ev1["id"]
        )
        assert ev2["status"] == "RECORDED"

        old = validate_success(api.get_withdrawal_event(ev1["id"], SOURCE_MONITOR))
        assert old["status"] == "VOIDED"

        # The superseded target drops out of every aggregate (PRD §3.1).
        assert permit_after["withdrawn_month_provisional_gallons"] == 5500

        page, meta = validate_paginated(api.list_withdrawal_events(
            SOURCE_MONITOR, params={"supersedes_event_id": ev1["id"]}
        ))
        assert meta["total_count"] == 1
        assert page[0]["id"] == ev2["id"]
