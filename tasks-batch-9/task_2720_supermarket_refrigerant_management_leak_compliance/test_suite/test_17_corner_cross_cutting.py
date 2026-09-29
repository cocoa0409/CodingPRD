"""
The optimistic-concurrency token of §2.8: the two writes it guards, the version
ledger that makes it meaningful, and offset paging over an append-only listing.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_CHARGE_EXCEEDS_NAMEPLATE,
    ERR_RETROFIT_TARGET_REQUIRED,
    ERR_STALE_SYSTEM_VERSION,
)
from test_helpers.assertions import (
    assert_array_envelope,
    assert_store_posture,
    assert_system_charge,
    ids_of,
)
from test_helpers.test_users import (
    COMPLIANCE_MANAGER_HEADERS,
    REGULATOR_HEADERS,
    make_store_manager_headers,
    make_technician_headers,
)
from test_helpers.types import (
    DETECTION_AUTOMATED_MONITORING,
    EVENT_OPEN,
    EVENT_VERIFIED_CLOSED,
    PLAN_DRAFT,
    PLAN_RETIRE,
    PLAN_SUPERSEDED,
)


def _occ_env(api, with_r448a: bool = False):
    """
    A 100.0 lb R-404A rack holding 80.0 lbs at version 1, worked by a single
    UNIVERSAL technician with the HIGH-pressure machine assigned to him and a
    50.0 lb cylinder holding 40.0 lbs — the minimum standing state in which a
    service record, a retrofit plan and a void are all legal writes.
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    env = {"store_id": store["id"], "rt404_id": rt404["id"]}
    if with_r448a:
        env["rt448_id"] = X.create_r448a(api)["id"]
    system = X.create_system(api, store["id"], rt404["id"])
    technician = X.create_second_technician(
        api, full_name="Marek Olsen", certification_expires_on="2027-12-31T00:00:00Z"
    )
    equipment = X.create_equipment(api, store["id"], technician["id"])
    cylinder = X.create_cylinder(api, store["id"], rt404["id"])
    env.update(
        system=system,
        system_id=system["id"],
        tech_id=technician["id"],
        eq_id=equipment["id"],
        cyl_id=cylinder["id"],
    )
    return env


def _service_records_of(api, system_id) -> int:
    body = assert_array_envelope(
        api.list_service_records(COMPLIANCE_MANAGER_HEADERS, {"system_id": system_id})
    )
    return body["meta"]["total_count"]


def test_a_stale_system_version_stops_the_second_service_record(api):
    """
    Filing a record is itself what bumps the system's version, so a client that
    reads the token once and writes twice is refused on the second write with
    412 — and only on the token, since the body it sent was otherwise legal.

    Design: Corner/cross_cutting_layers/service_record_with_a_stale_system_version_is_refused_with_precondition_failed
    """
    env = _occ_env(api)
    assert env["system"]["version"] == 1

    stale_token = X.system_version(api, env["system_id"])
    assert stale_token == 1

    X.file_service_record(
        api,
        env["system_id"],
        env["tech_id"],
        env["eq_id"],
        stale_token,
        cylinder_id=env["cyl_id"],
        refrigerant_added_lbs=10.0,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=30,
    )
    after_first = X.get_system(api, env["system_id"])
    assert after_first["version"] == 2
    assert_system_charge(after_first, current_charge_lbs=90.0, leak_rate_pct=10.0)

    # The same body twice over: 90.0 + 10.0 is exactly the nameplate charge, so
    # nothing but the consumed token can stand in its way. The clock moves to the
    # instant of that second visit, since §2.4 forbids a future `performed_at`;
    # setting the clock mutates no entity, so the token stays stale.
    X.set_clock(api, "2026-08-01T04:00:00Z")
    second = F.service_record_payload(
        env["system_id"],
        env["tech_id"],
        env["eq_id"],
        stale_token,
        cylinder_id=env["cyl_id"],
        refrigerant_added_lbs=10.0,
        performed_at="2026-08-01T04:00:00Z",
        duration_minutes=30,
    )
    refused = validate_error(
        api.create_service_record(second, make_technician_headers(env["tech_id"])),
        ERR_STALE_SYSTEM_VERSION,
        412,
    )
    assert refused["error_id"] != ERR_CHARGE_EXCEEDS_NAMEPLATE

    assert _service_records_of(api, env["system_id"]) == 1
    unmoved = X.get_system(api, env["system_id"])
    assert unmoved["version"] == 2
    assert_system_charge(unmoved, current_charge_lbs=90.0, leak_rate_pct=10.0)
    assert X.list_leak_events(api, system_id=env["system_id"])["meta"]["total_count"] == 0

    accepted = validate_success(
        api.create_service_record(
            dict(second, expected_system_version=X.system_version(api, env["system_id"])),
            make_technician_headers(env["tech_id"]),
        ),
        expected_status=201,
    )
    assert accepted["leak_rate_pct_after"] is not None

    settled = X.get_system(api, env["system_id"])
    assert settled["version"] == 3
    assert_system_charge(settled, current_charge_lbs=100.0, leak_rate_pct=20.0)

    events = X.list_leak_events(api, system_id=env["system_id"])
    assert events["meta"]["total_count"] == 1
    assert events["data"][0]["status"] == EVENT_OPEN


def test_a_stale_system_version_stops_a_plan_from_superseding_another(api):
    """
    A plan create silently supersedes the DRAFT plan already on the system, so
    the token check has to run before that destruction: the client holding the
    pre-plan version is refused and the standing DRAFT survives untouched.

    Design: Corner/cross_cutting_layers/retrofit_plan_with_a_stale_system_version_is_refused_before_it_can_supersede
    """
    env = _occ_env(api, with_r448a=True)
    stale_token = X.system_version(api, env["system_id"])
    assert stale_token == 1

    plan1 = X.file_retrofit_plan(
        api,
        env["system_id"],
        stale_token,
        target_refrigerant_type_id=env["rt448_id"],
        due_on="2026-10-01T00:00:00Z",
        estimated_cost_usd=120000.00,
    )
    assert plan1["status"] == PLAN_DRAFT
    assert X.get_system(api, env["system_id"])["version"] == 2

    # A RETIRE plan legitimately carries no target refrigerant, so the shape of
    # this body is beyond reproach and only the token is out of date.
    retire_plan = F.retrofit_plan_payload(
        env["system_id"],
        stale_token,
        plan_type=PLAN_RETIRE,
        due_on="2026-11-01T00:00:00Z",
        estimated_cost_usd=45000.00,
    )
    assert "target_refrigerant_type_id" not in retire_plan
    refused = validate_error(
        api.create_retrofit_plan(retire_plan, COMPLIANCE_MANAGER_HEADERS),
        ERR_STALE_SYSTEM_VERSION,
        412,
    )
    assert refused["error_id"] != ERR_RETROFIT_TARGET_REQUIRED

    assert X.get_plan(api, plan1["id"])["status"] == PLAN_DRAFT
    plans = assert_array_envelope(
        api.list_retrofit_plans(COMPLIANCE_MANAGER_HEADERS, {"system_id": env["system_id"]})
    )
    assert plans["meta"]["total_count"] == 1
    assert X.get_system(api, env["system_id"])["version"] == 2

    plan2 = validate_success(
        api.create_retrofit_plan(
            dict(retire_plan, expected_system_version=X.system_version(api, env["system_id"])),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert plan2["status"] == PLAN_DRAFT
    assert X.get_plan(api, plan1["id"])["status"] == PLAN_SUPERSEDED
    assert X.get_system(api, env["system_id"])["version"] == 3


def test_the_system_version_advances_only_on_writes_and_by_exactly_one(api):
    """
    Three different write families touch a system — a record, a plan and a void —
    and each advances its version by exactly one, while any number of reads in
    between leave it alone, which is what lets a client tell "someone else wrote"
    from "I re-read".

    Design: Corner/cross_cutting_layers/system_version_increments_on_every_parent_bumping_write_and_never_on_a_read
    """
    env = _occ_env(api, with_r448a=True)
    assert env["system"]["version"] == 1

    observed = [X.get_system(api, env["system_id"])["version"]]
    observed.append(
        validate_success(
            api.get_system(env["system_id"], make_store_manager_headers(env["store_id"]))
        )["version"]
    )

    record = X.file_service_record(
        api,
        env["system_id"],
        env["tech_id"],
        env["eq_id"],
        observed[0],
        cylinder_id=env["cyl_id"],
        refrigerant_added_lbs=10.0,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=30,
    )
    observed.append(X.get_system(api, env["system_id"])["version"])

    X.file_retrofit_plan(
        api,
        env["system_id"],
        observed[-1],
        target_refrigerant_type_id=env["rt448_id"],
        due_on="2026-10-01T00:00:00Z",
        estimated_cost_usd=120000.00,
    )
    observed.append(X.get_system(api, env["system_id"])["version"])

    voided = validate_success(
        api.void_service_record(
            record["id"],
            F.void_payload(void_reason_code="KEYED_IN_ERROR"),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert voided["voided"] is True
    observed.append(X.get_system(api, env["system_id"])["version"])

    assert observed == [1, 1, 2, 3, 4]

    restored = X.get_system(api, env["system_id"])
    assert_system_charge(restored, current_charge_lbs=80.0, leak_rate_pct=0.0)

    replay = F.service_record_payload(
        env["system_id"],
        env["tech_id"],
        env["eq_id"],
        2,
        cylinder_id=env["cyl_id"],
        refrigerant_added_lbs=10.0,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=30,
    )
    validate_error(
        api.create_service_record(replay, make_technician_headers(env["tech_id"])),
        ERR_STALE_SYSTEM_VERSION,
        412,
    )


def _open_page(api, offset: int):
    """One two-row window of the OPEN leak events, envelope checked."""
    return assert_array_envelope(
        api.list_leak_events(
            COMPLIANCE_MANAGER_HEADERS, {"status": EVENT_OPEN, "limit": 2, "offset": offset}
        )
    )


def test_offset_paging_stays_coherent_when_a_row_is_inserted_mid_walk(api):
    """
    Five events are paged two at a time and a sixth is declared between the
    first and second page reads. Because the listing is ordered by `created_at`
    ascending with insertion order as the tie-breaker, the appended row lands
    last: the second page still shows the third and fourth events, nothing is
    duplicated or skipped, and `total_count` alone reflects the insert.

    Design: Corner/cross_cutting_layers/offset_pagination_and_status_filtering_stay_coherent_across_an_inserted_row
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    systems = [
        X.create_empty_system(api, store["id"], rt404["id"])["id"] for _ in range(6)
    ]
    events = [X.declare_leak_event(api, system_id)["id"] for system_id in systems[:5]]

    page1 = _open_page(api, 0)
    assert ids_of(page1["data"]) == events[:2]
    assert page1["meta"]["total_count"] == 5
    assert page1["meta"]["has_more"] is True

    sixth = validate_success(
        api.create_leak_event(
            F.leak_event_payload(
                systems[5], detection_method=DETECTION_AUTOMATED_MONITORING
            ),
            REGULATOR_HEADERS,
        ),
        expected_status=201,
    )
    events.append(sixth["id"])

    page2 = _open_page(api, 2)
    assert ids_of(page2["data"]) == events[2:4]
    assert page2["meta"]["total_count"] == 6
    assert page2["meta"]["has_more"] is True

    page3 = _open_page(api, 4)
    assert ids_of(page3["data"]) == events[4:6]
    assert page3["meta"]["total_count"] == 6
    assert page3["meta"]["has_more"] is False

    closed = assert_array_envelope(
        api.list_leak_events(
            COMPLIANCE_MANAGER_HEADERS,
            {"status": EVENT_VERIFIED_CLOSED, "limit": 2, "offset": 0},
        )
    )
    assert closed["data"] == []
    assert closed["meta"]["total_count"] == 0
    assert closed["meta"]["has_more"] is False

    assert_store_posture(X.get_store(api, store["id"]), open_leak_event_count=6)
