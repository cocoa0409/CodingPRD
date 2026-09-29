"""Endpoints: the withdrawal bar after title passes and the two closeout gates."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


ADMIN = TEST_USERS["program_administrator_headers"]
MONITOR = TEST_USERS["compliance_monitor_headers"]

PROJECT_OVERRIDES = {
    "project_code": "EP-CLOSEOUT-1",
    "grant_program": "FMA",
    "period_of_performance_end_date": "2030-12-31",
}
PARCEL_OVERRIDES = {
    "apn": "APN-EP-CLOSEOUT-1",
    "site_address": "4401 River Rd",
    "acreage": 1.25,
    "occupancy_type": "OWNER_OCCUPIED",
    "structure_type": "SINGLE_FAMILY",
}
CONTRACTOR_OVERRIDES = {
    "name": "Northgate Demolition",
    "license_no": "DEM-7",
    "asbestos_certified": True,
    "max_concurrent_work_orders": 2,
}
WORK_ORDER_OVERRIDES = {
    "asbestos_survey_status": "CLEARED",
    "scheduled_start": "2026-09-01T08:00:00Z",
    "scheduled_end": "2026-09-03T17:00:00Z",
}
COMPLETE_OVERRIDES = {
    "total_debris_tons": 100.00,
    "recycled_tons": 30.00,
    "disposal_manifest_no": "MAN-CO-1",
    "disposal_facility_type": "COMBINED",
}
RECORD_OVERRIDES = {
    "recording_reference": "BK-9-PG-9",
    "maintenance_responsible_party": "City of Riverbend Parks Department",
}


def _withdraw(api, state, note):
    return api.record_participation(
        state["parcel"]["id"],
        factories.participation_payload(
            state["parcel"]["id"], "WITHDRAW", decision_note=note
        ),
        make_subrecipient_coordinator_headers(state["project"]["id"]),
    )


def test_withdrawal_is_barred_at_closed_at_demolished_and_after_recording(api):
    """The same call is refused three times as the acquisition walks its last three states.

    "It is barred once title has passed: if the parcel's `acquisition_status` is
    `CLOSED`, `DEMOLISHED` or `OPEN_SPACE_RECORDED`, the request is refused with
    `ERR_OPEN_SPACE_RESTRICTION_ACTIVE`, because the encumbrance is perpetual and the
    seller has already been paid."

    "Completion stores the four reported fields and `diversion_pct`, moves `status` to
    `COMPLETED`, moves the parcel's `acquisition_status` from `CLOSED` to `DEMOLISHED`."

    "`next_monitoring_due_date` is always an anchor date plus 36 calendar months, and
    the anchor changes over the restriction's life. At creation the anchor is
    `recorded_on`."

    Design: Corner/endpoints/withdrawal_is_refused_at_every_post_closing_stage_and_closeout_needs_clean_monitoring_and_ledger
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.work_order_in_progress(
        api,
        contractor_overrides=CONTRACTOR_OVERRIDES,
        work_order_overrides=WORK_ORDER_OVERRIDES,
        project_overrides=PROJECT_OVERRIDES,
        parcel_overrides=PARCEL_OVERRIDES,
    )
    coordinator = make_subrecipient_coordinator_headers(state["project"]["id"])
    assert state["parcel"]["acquisition_status"] == "CLOSED"

    validate_error(
        _withdraw(api, state, "owner changed mind after closing"),
        ApiErrorId.ERR_OPEN_SPACE_RESTRICTION_ACTIVE.value,
        409,
    )

    completed = validate_success(
        api.complete_demolition_work_order(
            state["work_order"]["id"],
            factories.complete_work_order_payload(
                state["work_order"]["id"], **COMPLETE_OVERRIDES
            ),
            coordinator,
        )
    )
    assert completed["status"] == "COMPLETED"
    demolished = validate_success(api.get_parcel(state["parcel"]["id"], ADMIN))
    assert demolished["acquisition_status"] == "DEMOLISHED"

    validate_error(
        _withdraw(api, state, "second attempt after demolition"),
        ApiErrorId.ERR_OPEN_SPACE_RESTRICTION_ACTIVE.value,
        409,
    )

    validate_success(
        api.record_closing_deed(
            state["closing"]["id"],
            factories.record_deed_payload(state["closing"]["id"], **RECORD_OVERRIDES),
            coordinator,
        )
    )
    recorded = validate_success(api.get_parcel(state["parcel"]["id"], ADMIN))
    assert recorded["acquisition_status"] == "OPEN_SPACE_RECORDED"

    validate_error(
        _withdraw(api, state, "third attempt after recording"),
        ApiErrorId.ERR_OPEN_SPACE_RESTRICTION_ACTIVE.value,
        409,
    )

    survivor = validate_success(api.get_parcel(state["parcel"]["id"], ADMIN))
    assert survivor["participation_status"] == "VOLUNTARY_CONFIRMED"
    assert survivor["acquisition_status"] == "OPEN_SPACE_RECORDED"

    restrictions, meta = validate_paginated(
        api.list_deed_restrictions(ADMIN, params={"parcel_id": state["parcel"]["id"]})
    )
    assert meta["total_count"] == 1
    assert restrictions[0]["recorded_on"] == "2026-08-01"
    assert restrictions[0]["next_monitoring_due_date"] == "2029-08-01"


def _recorded_open_space_carrying_a_lease_receipt(api):
    """One acquired, cleared and recorded parcel plus a 100,000-cent lease credit."""
    state = fixtures.parcel_open_space_recorded(
        api,
        record_overrides=RECORD_OVERRIDES,
        complete_overrides=COMPLETE_OVERRIDES,
        contractor_overrides=CONTRACTOR_OVERRIDES,
        work_order_overrides=WORK_ORDER_OVERRIDES,
        project_overrides=PROJECT_OVERRIDES,
        parcel_overrides=PARCEL_OVERRIDES,
    )
    assert state["parcel"]["acquisition_status"] == "OPEN_SPACE_RECORDED"
    assert state["restriction"]["next_monitoring_due_date"] == "2029-08-01"

    state["entry"] = fixtures.post_program_income(
        api, state["project"]["id"], entry_type="LEASE_REVENUE",
        amount_cents=100_000, posted_on="2026-08-01",
        applied_to_parcel_id=state["parcel"]["id"],
    )
    assert state["entry"]["federal_share_cents"] == 75_000

    state["project"] = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert state["project"]["program_income_balance_cents"] == 75_000
    assert state["project"]["federal_obligated_cents"] == 16_350_000
    return state


def _initiate(api, project_id):
    return api.closeout_mitigation_project(
        project_id, factories.closeout_payload(project_id, "INITIATE"), ADMIN
    )


def test_an_overdue_restriction_blocks_initiate_until_a_visit_re_anchors_the_schedule(api):
    """One day past the due date the grant cannot close, and one inspection reopens it.

    "A restriction is **overdue** when its `status` is `RECORDED`, `IN_COMPLIANCE` or
    `CURED` and its `next_monitoring_due_date` is strictly earlier than the date part of
    the logical clock."

    "No deed restriction on the project's parcels may be overdue - that is, no
    restriction with `status` in `RECORDED`, `IN_COMPLIANCE` or `CURED` may have a
    `next_monitoring_due_date` strictly earlier than the date part of the logical clock
    - otherwise `ERR_MONITORING_OVERDUE`."

    "A `COMPLIANT` finding recorded against a restriction in `RECORDED` or in `CURED`
    moves it to `IN_COMPLIANCE` and re-anchors `next_monitoring_due_date` to
    `inspection_date` plus 36 months."

    Design: Corner/endpoints/withdrawal_is_refused_at_every_post_closing_stage_and_closeout_needs_clean_monitoring_and_ledger
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _recorded_open_space_carrying_a_lease_receipt(api)

    api.set_clock("2029-08-02T00:00:00Z")
    validate_error(
        _initiate(api, state["project"]["id"]),
        ApiErrorId.ERR_MONITORING_OVERDUE.value,
        409,
    )
    still_approved = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert still_approved["status"] == "APPROVED"

    inspection = validate_success(
        api.create_monitoring_inspection(
            state["restriction"]["id"],
            factories.create_monitoring_inspection_payload(
                state["restriction"]["id"], finding="COMPLIANT",
                inspection_date="2029-08-02",
                narrative="open space intact, mowed twice this season",
            ),
            MONITOR,
        ),
        201,
    )
    assert inspection["finding"] == "COMPLIANT"

    restriction = validate_success(
        api.get_deed_restriction(state["restriction"]["id"], ADMIN)
    )
    assert restriction["status"] == "IN_COMPLIANCE"
    assert restriction["next_monitoring_due_date"] == "2032-08-02"

    initiated = validate_success(_initiate(api, state["project"]["id"]))
    assert initiated["status"] == "CLOSEOUT_PENDING"
    assert float(initiated["protected_open_space_acres"]) == 1.25


def test_finalizing_waits_for_the_ledger_to_be_driven_back_to_zero(api):
    """A reversal, not an expenditure, empties the balance and the same call then closes the grant.

    "`FINALIZE` requires the project's `status` to be `CLOSEOUT_PENDING`, otherwise
    `ERR_INVALID_PROJECT_STATE`, and requires `program_income_balance_cents` to be
    exactly 0, otherwise `ERR_PROGRAM_INCOME_OUTSTANDING`."

    "Reversal recomputes `program_income_balance_cents` and advances the project's
    `version` by 1."

    "`FINALIZE` moves `status` to `CLOSED_OUT` and advances the project's `version` by
    1."

    Design: Corner/endpoints/withdrawal_is_refused_at_every_post_closing_stage_and_closeout_needs_clean_monitoring_and_ledger
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _recorded_open_space_carrying_a_lease_receipt(api)

    api.set_clock("2029-08-02T00:00:00Z")
    validate_success(
        api.create_monitoring_inspection(
            state["restriction"]["id"],
            factories.create_monitoring_inspection_payload(
                state["restriction"]["id"], finding="COMPLIANT",
                inspection_date="2029-08-02",
                narrative="open space intact, mowed twice this season",
            ),
            MONITOR,
        ),
        201,
    )
    pending = validate_success(_initiate(api, state["project"]["id"]))
    assert pending["status"] == "CLOSEOUT_PENDING"
    assert pending["program_income_balance_cents"] == 75_000

    validate_error(
        api.closeout_mitigation_project(
            state["project"]["id"],
            factories.closeout_payload(state["project"]["id"], "FINALIZE"),
            ADMIN,
        ),
        ApiErrorId.ERR_PROGRAM_INCOME_OUTSTANDING.value,
        409,
    )
    unfinished = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert unfinished["status"] == "CLOSEOUT_PENDING"

    mirror = validate_success(
        api.reverse_program_income_entry(
            state["entry"]["id"],
            factories.reverse_program_income_entry_payload(
                state["entry"]["id"], reversal_note="receipt refunded to lessee"
            ),
            ADMIN,
        ),
        201,
    )
    assert mirror["status"] == "REVERSED"

    emptied = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert emptied["program_income_balance_cents"] == 0

    closed = validate_success(
        api.closeout_mitigation_project(
            state["project"]["id"],
            factories.closeout_payload(state["project"]["id"], "FINALIZE"),
            ADMIN,
        )
    )
    assert closed["status"] == "CLOSED_OUT"
    assert float(closed["protected_open_space_acres"]) == 1.25
    assert closed["federal_obligated_cents"] == 16_350_000
