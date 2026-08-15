"""Eviction pipeline, abandoned-aircraft storage, lease-version OCC, and aircraft rules."""
from test_helpers import (
    ApiErrorId,
    accept_offer,
    add_hangar,
    add_rate_schedule,
    api_client,
    create_aircraft_payload,
    create_airport,
    extend_offer,
    file_finding,
    get_eviction_case,
    get_hangar,
    get_lease,
    list_lease_eviction_cases,
    make_applicant_headers,
    make_tenant_headers,
    set_clock,
    setup_lease,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_eviction_full_lifecycle_with_aircraft_removal(api, manager_headers,
                                                       compliance_headers):
    """PRD §3.8: "Executing a case requires it to be `FILED` (`ERR_CASE_NOT_FILED`, HTTP 409) and carries the `expected_lease_version` concurrency guard of §2.7. Execution stamps `executed_at`, snapshots the abandoned-aircraft daily storage rate of 2500 cents into `abandoned_aircraft_storage_cents_per_day`, zeroes `storage_days_already_billed`, moves the case to `EXECUTED` and the lease to `EVICTED`, increments the lease's `version` by one, and recomputes the hangar's posture to `AVAILABLE` — the hangar is freed even though aircraft may still sit inside it, because storage now accrues against the evicted tenant."
    PRD §3.8: "A manager closes out an `EVICTED` lease (`ERR_LEASE_NOT_EVICTED`, HTTP 409) once every aircraft is `REMOVED`; if any aircraft remains `BASED`, the terminating request must carry `abandon_remaining_aircraft` set to true, otherwise it is rejected with `ERR_AIRCRAFT_STILL_BASED` (HTTP 409). Either close-out moves the lease to `TERMINATED` and resolves the case: `CLOSED_AIRCRAFT_REMOVED` when all aircraft were removed, or `CLOSED_AIRCRAFT_ABANDONED` when remaining aircraft are abandoned — in which case those aircraft flip to `REMOVED` with `removed_at` stamped and storage accrual stops."

    Design: Corner/state_machines/eviction_execute_then_terminate_full_abandoned_aircraft_flow
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KEVX", "cure_window_days": 30},
                      size_class="BOX", rate=80000, hangar_code="B-62",
                      applicant_name="Eve Evict")
    lease = ctx["lease"]
    set_clock("2026-08-05T00:00:00Z")
    file_finding(lease["id"], "NON_AERONAUTICAL_USE")
    set_clock("2026-09-05T00:00:00Z")  # past the 2026-09-04 cure deadline

    case = list_lease_eviction_cases(lease["id"])[0]
    lease_version = get_lease(lease["id"])["version"]

    executed = validate_success(
        api_client.execute_eviction_case(case["id"],
                                         {"expected_lease_version": lease_version},
                                         manager_headers)
    )
    assert executed["status"] == "EXECUTED"
    assert get_lease(lease["id"])["status"] == "EVICTED"
    assert get_hangar(ctx["hangar"]["id"])["posture"] == "AVAILABLE"

    # Aircraft still BASED: close-out without the abandonment flag rejects.
    resp = api_client.terminate_lease(lease["id"], {}, manager_headers)
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_STILL_BASED)

    aircraft, _ = validate_paginated(api_client.list_aircraft(lease["id"], manager_headers))
    validate_success(api_client.remove_aircraft(aircraft[0]["id"], manager_headers))

    terminated = validate_success(api_client.terminate_lease(lease["id"], {}, manager_headers))
    assert terminated["status"] == "TERMINATED"
    assert get_eviction_case(case["id"])["status"] == "CLOSED_AIRCRAFT_REMOVED"


def test_delinquency_eviction_guards(api, manager_headers):
    """PRD §3.8: "Delinquency takes a manual path instead: a manager files the case with `reason` `DELINQUENCY` (the `reason` enumeration also includes `NON_AERONAUTICAL_USE`) against a lease that is `DELINQUENT` (`ERR_LEASE_NOT_DELINQUENT`, HTTP 409) and whose `days_delinquent` has reached the fixed system threshold of thirty days (`ERR_DELINQUENCY_THRESHOLD_NOT_MET`, HTTP 402); such cases carry an empty `use_audit_finding_id`."
    PRD §3.4: "The delinquency figure is the largest overdue-day count among those same charges, or zero when none is past its grace window; it drives both the `DELINQUENT` status and the eviction threshold of §3.8."

    Design: Corner/errors/error_delinquency_threshold_and_lease_not_delinquent
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KDTH", "late_fee_grace_days": 5},
                      size_class="T_HANGAR", rate=100000, hangar_code="T-310",
                      applicant_name="Dee Thresh")
    lease = ctx["lease"]

    # While the lease is ACTIVE (charge not yet past grace), filing rejects.
    resp = api_client.file_eviction_case(lease["id"], {"reason": "DELINQUENCY"},
                                         manager_headers)
    validate_error(resp, ApiErrorId.ERR_LEASE_NOT_DELINQUENT)

    # At 2026-08-10 the August charge (due 08-01, grace ends 08-06) is 4 days
    # overdue: the lease is DELINQUENT but far below the thirty-day threshold.
    set_clock("2026-08-10T00:00:00Z")
    resp = api_client.file_eviction_case(lease["id"], {"reason": "DELINQUENCY"},
                                         manager_headers)
    validate_error(resp, ApiErrorId.ERR_DELINQUENCY_THRESHOLD_NOT_MET)

    after = get_lease(lease["id"])
    assert after["status"] == "DELINQUENT"
    assert after["days_delinquent"] == 4


def test_abandoned_aircraft_storage_accrual(api, manager_headers, compliance_headers):
    """PRD §3.8: "From execution onward, the sweep accrues storage for each `EXECUTED` case whose lease still has at least one `BASED` aircraft: it takes the whole days elapsed since `executed_at`, subtracts `storage_days_already_billed`, and when that difference is positive records an accrual of the day count multiplied by the snapshotted daily rate multiplied by the number of `BASED` aircraft on the lease, then advances `storage_days_already_billed` by the day count. Storage is charged per based aircraft per day."
    PRD §3.8: "Execution stamps `executed_at`, snapshots the abandoned-aircraft daily storage rate of 2500 cents into `abandoned_aircraft_storage_cents_per_day`, zeroes `storage_days_already_billed`, moves the case to `EXECUTED` and the lease to `EVICTED`, increments the lease's `version` by one, and recomputes the hangar's posture to `AVAILABLE` — the hangar is freed even though aircraft may still sit inside it, because storage now accrues against the evicted tenant."

    Design: Corner/calculations/abandoned_aircraft_storage_accrues_per_aircraft_per_day
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KABD", "cure_window_days": 30},
                      size_class="CORPORATE", rate=250000, hangar_code="C-120",
                      applicant_name="Abby Andon")
    lease = ctx["lease"]
    # A second BASED aircraft on the lease (the acceptance created the primary).
    validate_success(
        api_client.add_aircraft(lease["id"], create_aircraft_payload(is_primary=False),
                                make_tenant_headers(lease["id"])),
        expected_status=201,
    )

    set_clock("2026-08-05T00:00:00Z")
    file_finding(lease["id"], "NON_AERONAUTICAL_USE")
    set_clock("2026-09-05T00:00:00Z")
    case = list_lease_eviction_cases(lease["id"])[0]
    validate_success(
        api_client.execute_eviction_case(
            case["id"], {"expected_lease_version": get_lease(lease["id"])["version"]},
            manager_headers,
        )
    )

    # Five whole days after execution, with two BASED aircraft.
    set_clock("2026-09-10T00:00:00Z")
    after = get_eviction_case(case["id"])
    assert after["abandoned_aircraft_storage_cents_per_day"] == 2500
    assert after["storage_days_already_billed"] == 5, (
        f"expected 5 billed storage days, got {after['storage_days_already_billed']}"
    )


def test_occ_stale_lease_version_on_eviction_execute(api, manager_headers):
    """PRD §2.7: "Executing an eviction case requires the request to carry `expected_lease_version`, matched against the lease's current `version`; if the lease's version has advanced since the client last read it — for example because a payment cascade bumped the version and returned the lease to good standing — the execution is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "A successful payment updates charge statuses and `paid_cents` totals, recomputes the lease's `outstanding_balance_cents`, and increments the lease's `version`."

    Design: Corner/cross_cutting_layers/occ_stale_lease_version_on_eviction_execute
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KOCL", "late_fee_grace_days": 5},
                      size_class="T_HANGAR", rate=100000, hangar_code="T-240",
                      applicant_name="Olly Stale")
    lease = ctx["lease"]

    # At 2026-10-15 the August charge is 70 days past grace: DELINQUENT and
    # beyond the thirty-day eviction threshold.
    set_clock("2026-10-15T00:00:00Z")
    case = validate_success(
        api_client.file_eviction_case(lease["id"], {"reason": "DELINQUENCY"}, manager_headers),
        expected_status=201,
    )
    stale_version = get_lease(lease["id"])["version"]

    # A partial payment applies to charges and advances the lease version.
    validate_success(
        api_client.create_payment(lease["id"], {"amount_cents": 1000},
                                  make_tenant_headers(lease["id"]))
    )

    resp = api_client.execute_eviction_case(case["id"],
                                            {"expected_lease_version": stale_version},
                                            manager_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_eviction_case(case["id"])["status"] == "FILED"
    assert get_lease(lease["id"])["status"] == "EVICTION_PENDING"


def test_duplicate_n_number_across_leases_rejected(api, manager_headers):
    """PRD §3.4: "The tail number must be unique among aircraft currently `BASED` on active-phase leases at the same airport (`ERR_DUPLICATE_N_NUMBER`, HTTP 422)".

    Design: Difficulty/resource_temporal_overlap/n_number_aircraft_occupancy_overlap
    """
    airport = create_airport(airport_code="KDUP")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=90000)
    hangar1 = add_hangar(airport["id"], hangar_code="T-50", size_class="T_HANGAR")
    hangar2 = add_hangar(airport["id"], hangar_code="T-51", size_class="T_HANGAR")
    app1 = submit_application(airport["id"], applicant_name="Dan Dup1",
                              aircraft_n_number="N160DP")
    app2 = submit_application(airport["id"], applicant_name="Dan Dup2",
                              aircraft_n_number="N161DP")

    offer1 = extend_offer(airport["id"], hangar1["id"], app1["id"])
    lease1 = accept_offer(offer1, hangar1, app1)
    offer2 = extend_offer(airport["id"], hangar2["id"], app2["id"])
    lease2 = accept_offer(offer2, hangar2, app2)

    # N160DP is already BASED on lease1 at this airport.
    resp = api_client.add_aircraft(
        lease2["id"],
        create_aircraft_payload(n_number="N160DP", make_model="Cessna 172",
                                is_primary=False),
        make_tenant_headers(lease2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_N_NUMBER)


def test_original_lease_aircraft_unaffected_by_rejected_add(api, manager_headers):
    """PRD §3.4: "A tenant adds further aircraft to the lease with `n_number`, `make_model`, and `is_primary`, each record carrying its owning `lease_id`. The tail number must be unique among aircraft currently `BASED` on active-phase leases at the same airport (`ERR_DUPLICATE_N_NUMBER`, HTTP 422)".

    Design: Difficulty/resource_temporal_overlap/n_number_aircraft_occupancy_overlap
    """
    airport = create_airport(airport_code="KDU2")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=90000)
    hangar1 = add_hangar(airport["id"], hangar_code="T-52", size_class="T_HANGAR")
    hangar2 = add_hangar(airport["id"], hangar_code="T-53", size_class="T_HANGAR")
    app1 = submit_application(airport["id"], applicant_name="Dan Dup1",
                              aircraft_n_number="N160DP")
    app2 = submit_application(airport["id"], applicant_name="Dan Dup2",
                              aircraft_n_number="N161DP")
    lease1 = accept_offer(extend_offer(airport["id"], hangar1["id"], app1["id"]), hangar1, app1)
    lease2 = accept_offer(extend_offer(airport["id"], hangar2["id"], app2["id"]), hangar2, app2)

    validate_error(
        api_client.add_aircraft(lease2["id"],
                                create_aircraft_payload(n_number="N160DP"),
                                make_tenant_headers(lease2["id"])),
        ApiErrorId.ERR_DUPLICATE_N_NUMBER,
    )

    aircraft1, _ = validate_paginated(api_client.list_aircraft(lease1["id"], manager_headers))
    assert [a["n_number"] for a in aircraft1] == ["N160DP"]
    assert aircraft1[0]["status"] == "BASED"
    # The rejected add created nothing on lease2 beyond its primary aircraft.
    aircraft2, meta2 = validate_paginated(api_client.list_aircraft(lease2["id"],
                                                                   manager_headers))
    assert meta2["total_count"] == 1 and aircraft2[0]["n_number"] == "N161DP"


def test_duplicate_primary_aircraft_rejected(api, manager_headers):
    """PRD §3.4: "each lease has exactly one primary aircraft — the aeronautical-use anchor — so declaring a new primary while one already exists is rejected with `ERR_PRIMARY_AIRCRAFT_CONFLICT` (HTTP 422); the old primary must be removed first."

    Design: Corner/validations/duplicate_primary_aircraft_rejected
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KPRM"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-170", applicant_name="Pri Mary")
    lease = ctx["lease"]

    resp = api_client.add_aircraft(
        lease["id"],
        create_aircraft_payload(make_model="Piper PA-28", is_primary=True),
        make_tenant_headers(lease["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRIMARY_AIRCRAFT_CONFLICT)
