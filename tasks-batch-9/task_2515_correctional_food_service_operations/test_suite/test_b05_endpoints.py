"""Endpoint behaviour: partial updates, action endpoints, computed reads and links.

These cases pin what one request to one route does — which fields it rewrites, which
it leaves frozen, and what the read side reports afterwards.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, ApiErrorId, assertions, factories, fixtures
from test_helpers import test_users as users


def test_correcting_one_tray_segment_re_derives_only_the_served_total(
    api: ApiClient,
) -> None:
    """A partial update rewrites the supplied segment, recomputes the served total, leaves
    the untouched segment alone and never revisits the frozen expected figure.

    The PRD states: "While a record is `OPEN`, a supervisor may correct any subset of the
    four served tray counts. Each supplied count replaces the stored one,
    `total_trays_served` is recomputed from whatever the three site counts now read, and
    `version` is incremented by 1." The expected figure is frozen at creation: "That frozen
    value never moves again even if the forecast is somehow revisited."

    Design: Corner/endpoints/corner_patch_service_record_recomputes_total_trays
    """
    ctx = fixtures.open_service_record(
        api,
        fixtures.locked_forecast(
            api,
            contract_overrides={"contract_code": "CFS-2515-P01"},
            facility_overrides={
                "facility_code": "FAC-P01",
                "sharps_authorized_count": 12,
            },
        ),
    )
    record = ctx["record"]
    assert record["total_trays_served"] == 13
    assert record["expected_service_trays"] == 14
    assert record["version"] == 1

    patched = validate_success(
        api.patch_meal_service_record(
            record["id"], {"trays_served_general": 11}, users.FOOD_SUPERVISOR
        )
    )
    assert patched["trays_served_general"] == 11
    assert patched["trays_served_segregation"] == 2
    assert patched["trays_served_satellite"] == 1
    assert patched["special_diet_trays_served"] == 0
    assert patched["total_trays_served"] == 14
    assert patched["expected_service_trays"] == 14
    assert patched["missed_meal_count"] == 0
    assert patched["status"] == "OPEN"
    assertions.assert_version_bumped_by(record, patched)
    assert patched["version"] == 2


def test_a_work_bar_sanction_reaches_the_incident_the_worker_and_the_kitchen(
    api: ApiClient,
) -> None:
    """One disposition call closes the incident, bars the worker off its detail and drops
    the facility's open-incident tally back to zero.

    The PRD states: "because the incident became `SANCTIONED`, the worker's
    `contraband_strike_count` rises by 1. Hop 2: because that count reached the bar
    threshold of 2, or because `sanction_type` is `WORK_BAR` regardless of the count, the
    worker's `clearance_status` becomes `BARRED` ... In either of those outcomes the
    worker's `assignment_status` becomes `UNASSIGNED` with `work_area` set to null and
    `version` incremented by 1." It also states: "The dispositioning user may not be the
    reporting user: a match against `discovered_by_user_id` is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/endpoints/corner_contraband_sanction_bars_the_worker
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-P02")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-P02", sharps_authorized_count=12
    )
    worker = fixtures.enrolled_worker(
        api, facility["id"], booking_number="BK-P02", sharps_eligible=True
    )["worker"]
    assigned = validate_success(
        api.assign_inmate_worker(
            worker["id"], factories.assign_payload("COOK_CHILL"), users.FOOD_SUPERVISOR
        )
    )
    assert assigned["assignment_status"] == "ASSIGNED"
    assert assigned["work_area"] == "COOK_CHILL"

    incident = validate_success(
        api.create_contraband_incident(
            factories.contraband_incident_payload(
                facility["id"],
                item_class="YEAST_ALCOHOL",
                severity="MAJOR",
                narrative="Fermenting jug behind the mixer.",
                inmate_worker_id=worker["id"],
            ),
            users.OFFICER,
        ),
        201,
    )
    assert incident["status"] == "OPEN"
    assert incident["discovered_by_user_id"] == users.user_id_of(users.OFFICER)
    assert incident["sanction_type"] is None
    # One open incident is below the restrict threshold of two.
    assert fixtures.read_facility(api, facility["id"])["kitchen_posture"] == "OPEN"

    sanctioned = validate_success(
        api.disposition_contraband_incident(
            incident["id"],
            factories.disposition_payload("SANCTIONED", sanction_type="WORK_BAR"),
            users.OFFICER_2,
        )
    )
    assert sanctioned["status"] == "SANCTIONED"
    assert sanctioned["sanction_type"] == "WORK_BAR"
    assert sanctioned["disposition_by_user_id"] == users.user_id_of(users.OFFICER_2)

    barred = fixtures.read_worker(api, worker["id"])
    assert barred["clearance_status"] == "BARRED"
    assert barred["assignment_status"] == "UNASSIGNED"
    assert barred["work_area"] is None
    assert barred["contraband_strike_count"] == 1

    quiet = fixtures.read_facility(api, facility["id"])
    assert quiet["open_contraband_incident_count"] == 0
    assert quiet["kitchen_posture"] == "OPEN"


def test_a_perfectly_served_month_reads_back_as_a_hundred_with_no_variant_chosen(
    api: ApiClient,
) -> None:
    """The computed summary mirrors the ledger a close wrote: a shortfall exactly at
    tolerance accrues nothing, the score stays at 100 and no damages variant is claimed.

    The PRD states that the summary "returns `total_trays_served`, `meal_days_served`,
    `missed_meal_total`, `substitution_rate_pct`, `grievance_sla_breach_count`,
    `raw_liquidated_damages_cents`, `substitution_surcharge_cents`,
    `liquidated_damages_cents`, `cost_recovery_credit_cents`,
    `net_liquidated_damages_cents`, `performance_score` and `ld_variant` in a single flat
    object". It also fixes the tolerance: "at an expected count of 156 trays the tolerance
    is exactly 3 ... At an expected count of 156 with no special-diet shortfall, 153 trays
    served yields 0 while 152 yields 1."

    Design: Corner/endpoints/corner_performance_summary_read_matches_the_ledger
    """
    ctx = fixtures.locked_forecast(
        api,
        contract_overrides={"contract_code": "CFS-2515-P03"},
        facility_overrides={
            "facility_code": "FAC-P03",
            "sharps_authorized_count": 12,
        },
        count_overrides={
            "general_population": 130,
            "segregation_population": 20,
            "satellite_population": 12,
            "medical_population": 0,
        },
    )
    assertions.assert_decimal_2dp(
        ctx["cycle"]["approved_cost_cents_per_meal_day"], 315.00
    )
    forecast = ctx["forecast"]
    assert forecast["line_trays"] == 156
    assert forecast["waste_allowance_trays"] == 8
    assert forecast["total_forecast_trays"] == 164
    assert forecast["forecast_special_diet_trays"] == 0

    opened = fixtures.open_service_record(
        api,
        ctx,
        trays_served_general=121,
        trays_served_segregation=20,
        trays_served_satellite=12,
        special_diet_trays_served=0,
    )["record"]
    assert opened["expected_service_trays"] == 156
    assert opened["total_trays_served"] == 153

    closed = validate_success(
        api.close_meal_service_record(
            opened["id"],
            factories.close_service_record_payload(
                fixtures.read_contract(api, ctx["contract"]["id"])["version"]
            ),
            users.FOOD_SUPERVISOR,
        )
    )
    assert closed["status"] == "CLOSED"
    assert closed["total_trays_served"] == 153
    assert closed["missed_meal_count"] == 0

    summary = validate_success(
        api.get_performance_summary(ctx["contract"]["id"], users.AUDITOR)
    )
    assert summary["total_trays_served"] == 153
    assert summary["meal_days_served"] == 51
    assert summary["missed_meal_total"] == 0
    assertions.assert_decimal_2dp(summary["substitution_rate_pct"], 0.00)
    assert summary["grievance_sla_breach_count"] == 0
    assert summary["raw_liquidated_damages_cents"] == 0
    assert summary["substitution_surcharge_cents"] == 0
    assert summary["liquidated_damages_cents"] == 0
    assert summary["cost_recovery_credit_cents"] == 0
    assert summary["net_liquidated_damages_cents"] == 0
    assertions.assert_decimal_2dp(summary["performance_score"], 100.00)
    assert summary["ld_variant"] is None


def test_the_worker_junction_needs_a_real_inmate_and_admits_only_one_row(
    api: ApiClient,
) -> None:
    """An unknown inmate leaves no worker row behind; the valid link is retrievable by its
    inmate filter and cannot be duplicated.

    The PRD states: "An inmate may hold at most one worker record: a second enrolment for
    the same `inmate_id` is rejected with `ERR_DUPLICATE_RESOURCE`. A new worker opens with
    `clearance_status` `CLEARED`, `assignment_status` `UNASSIGNED`, `work_area` null and
    `contraband_strike_count` 0", and `sharps_eligible` "defaults to false".

    Design: Corner/endpoints/corner_inmate_worker_link_requires_both_ends_to_exist
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-P04")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-P04", sharps_authorized_count=12
    )
    inmate = fixtures.create_inmate(api, facility["id"], booking_number="BK-P04")

    validate_error(
        api.create_inmate_worker(
            factories.inmate_worker_payload(
                NON_EXISTENT_UUID, facility["id"], sharps_eligible=factories.OMIT
            ),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_INMATE_NOT_FOUND.value,
        404,
    )
    _, empty_meta = validate_paginated(
        api.list_inmate_workers(
            users.FOOD_SUPERVISOR, params={"facility_id": facility["id"]}
        )
    )
    assert empty_meta["total_count"] == 0

    worker = validate_success(
        api.create_inmate_worker(
            factories.inmate_worker_payload(
                inmate["id"], facility["id"], sharps_eligible=factories.OMIT
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assertions.assert_worker_enrollment_defaults(worker)
    assert worker["inmate_id"] == inmate["id"]
    assert worker["facility_id"] == facility["id"]
    assert worker["sharps_eligible"] is False

    data, meta = validate_paginated(
        api.list_inmate_workers(
            users.FOOD_SUPERVISOR, params={"inmate_id": inmate["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in data] == [worker["id"]]

    validate_error(
        api.create_inmate_worker(
            factories.inmate_worker_payload(inmate["id"], facility["id"]),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE.value,
        409,
    )
