"""
The validation corners: each payload below breaks exactly one rule while
satisfying its neighbours, so the identifier that comes back names the rule that
actually fired, and the ledger it was aimed at is provably untouched.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_CHARGE_EXCEEDS_NAMEPLATE,
    ERR_CROSS_STORE_RESOURCE,
    ERR_DUPLICATE_IDENTIFIER,
    ERR_EXTENSION_REASON_NOT_APPLICABLE,
    ERR_EXTENSION_WINDOW_CLOSED,
    ERR_GRANTED_DAYS_EXCEED_REQUESTED,
    ERR_NEGATIVE_SYSTEM_CHARGE,
    ERR_REPORT_PERIOD_OVERLAP,
    ERR_RETROFIT_INCOMPATIBLE,
    ERR_RETROFIT_TARGET_REQUIRED,
    ERR_SERVICE_DATE_OUT_OF_RANGE,
    ERR_SERVICE_RECORD_ALREADY_VOIDED,
    ERR_TARGET_REFRIGERANT_PROHIBITED,
    ERR_TIMESTAMP_AFTER_CLOCK,
    ERR_VOID_NOT_PERMITTED,
)
from test_helpers.assertions import (
    assert_array_envelope,
    assert_extension_budget,
    assert_instant,
    assert_instant_is_none,
    assert_mass,
    assert_score,
    assert_system_charge,
)
from test_helpers.test_users import (
    COMPLIANCE_MANAGER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REGULATOR_HEADERS,
    make_technician_headers,
)
from test_helpers.types import (
    COMPAT_COMPATIBLE,
    COMPAT_INCOMPATIBLE,
    DECISION_APPROVE,
    DISPOSITION_VIRGIN,
    EXTENSION_PENDING,
    ODS_HCFC,
    PHASEDOWN_PROHIBITED,
    PLAN_DRAFT,
    PLAN_RETIRE,
    PRESSURE_HIGH,
    REASON_INDUSTRIAL_PROCESS_SHUTDOWN_REQUIRED,
    REASON_PARTS_UNAVAILABLE,
    REPORT_DRAFT,
    SERVICE_ADD_REFRIGERANT,
    SERVICE_RECOVER_REFRIGERANT,
)


def _total_count(response) -> int:
    """The `meta.total_count` of a listing, envelope checked on the way past."""
    return assert_array_envelope(response)["meta"]["total_count"]


def test_a_service_record_dated_after_the_logical_clock_is_rejected(api):
    """
    §2.4 forbids any physical-world timestamp ahead of the logical clock, so a
    record dated tomorrow is refused and no future-dated mass reaches the ledger.

    Design: Corner/validations/service_record_performed_after_the_logical_clock_is_rejected
    """
    env = X.base_env(api, with_second_technician=False)

    validate_error(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                env["system"]["version"],
                cylinder_id=env["cyl1_id"],
                service_type=SERVICE_ADD_REFRIGERANT,
                refrigerant_added_lbs=5.0,
                performed_at="2026-08-02T00:00:00Z",
                duration_minutes=60,
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        ERR_TIMESTAMP_AFTER_CLOCK,
        422,
    )

    system = X.get_system(api, env["system_id"])
    assert_system_charge(system, current_charge_lbs=80.0)
    assert system["version"] == 1
    assert_mass(
        X.get_cylinder(api, env["cyl1_id"])["current_contents_lbs"],
        40.0,
        "current_contents_lbs",
    )
    assert (
        _total_count(
            api.list_service_records(
                COMPLIANCE_MANAGER_HEADERS, {"system_id": env["system_id"]}
            )
        )
        == 0
    )


def test_a_service_record_before_the_system_was_installed_is_out_of_range(api):
    """
    §3.3 requires `performed_at` to be on or after `installed_on`. A 2024 date is
    legally in the past, so the clock rule is satisfied and the installation rule
    is the one that fires.

    Design: Corner/validations/service_record_before_system_installation_is_out_of_range
    """
    env = X.base_env(api, with_second_technician=False)

    body = validate_error(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                env["system"]["version"],
                cylinder_id=env["cyl1_id"],
                service_type=SERVICE_ADD_REFRIGERANT,
                refrigerant_added_lbs=5.0,
                performed_at="2024-12-01T00:00:00Z",
                duration_minutes=60,
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        ERR_SERVICE_DATE_OUT_OF_RANGE,
        422,
    )
    assert body["error_id"] != ERR_TIMESTAMP_AFTER_CLOCK

    assert_system_charge(
        X.get_system(api, env["system_id"]), current_charge_lbs=80.0, leak_rate_pct=0.0
    )
    assert (
        _total_count(
            api.list_service_records(
                COMPLIANCE_MANAGER_HEADERS, {"system_id": env["system_id"]}
            )
        )
        == 0
    )


def test_a_cylinder_from_another_store_cannot_feed_this_systems_record(api):
    """
    §3.3 requires the named cylinder to belong to the serviced system's store. The
    offending cylinder holds the right chemistry with ample contents, so ownership
    is the only broken rule.

    Design: Corner/validations/cylinder_from_another_store_cannot_feed_this_systems_record
    """
    env = X.base_env(api, with_cylinder=False, with_second_technician=False)
    other_store = X.create_second_store(api)
    foreign_cylinder = X.create_cylinder(
        api, other_store["id"], env["rt404_id"], cylinder_serial="CYL-0002"
    )

    validate_error(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                env["system"]["version"],
                cylinder_id=foreign_cylinder["id"],
                service_type=SERVICE_ADD_REFRIGERANT,
                refrigerant_added_lbs=10.0,
                performed_at="2026-08-01T00:00:00Z",
                duration_minutes=60,
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        ERR_CROSS_STORE_RESOURCE,
        422,
    )

    cylinder = X.get_cylinder(api, foreign_cylinder["id"])
    assert_mass(cylinder["current_contents_lbs"], 40.0, "current_contents_lbs")
    assert cylinder["disposition"] == DISPOSITION_VIRGIN
    system = X.get_system(api, env["system_id"])
    assert_system_charge(system, current_charge_lbs=80.0)
    assert system["version"] == 1


def test_a_second_store_reusing_a_store_code_is_a_duplicate(api):
    """
    §3.1 makes `store_code` globally unique, and only the code: the colliding
    create is refused while a fresh code succeeds even though the banner name
    repeats verbatim.

    Design: Corner/validations/duplicate_store_code_is_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    X.create_store(api)

    validate_error(
        api.create_store(
            F.store_payload(
                name="Northgate Market Annex", store_code="NG-001", state_code="OR"
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_DUPLICATE_IDENTIFIER,
        409,
    )

    validate_success(
        api.create_store(
            F.store_payload(
                name="Northgate Market", store_code="NG-002", state_code="OR"
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        expected_status=201,
    )
    assert _total_count(api.list_stores(COMPLIANCE_MANAGER_HEADERS)) == 2


def test_a_report_period_sharing_a_single_day_with_a_draft_is_an_overlap(api):
    """
    §3.9 treats reporting periods as inclusive at both ends and lets a still-DRAFT
    filing block, so a period starting on the incumbent's last day overlaps by one
    day while a period starting the next day is accepted.

    Design: Corner/validations/report_period_sharing_a_single_day_is_an_overlap
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    incumbent = validate_success(
        api.create_regulatory_report(
            F.regulatory_report_payload(
                store["id"],
                period_start="2026-01-01T00:00:00Z",
                period_end="2026-06-30T00:00:00Z",
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )

    validate_error(
        api.create_regulatory_report(
            F.regulatory_report_payload(
                store["id"],
                period_start="2026-06-30T00:00:00Z",
                period_end="2026-07-31T00:00:00Z",
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_REPORT_PERIOD_OVERLAP,
        409,
    )

    abutting = validate_success(
        api.create_regulatory_report(
            F.regulatory_report_payload(
                store["id"],
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-07-31T00:00:00Z",
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert_instant(abutting["due_on"], "2026-09-29T00:00:00Z", "due_on")

    assert (
        _total_count(
            api.list_regulatory_reports(
                COMPLIANCE_MANAGER_HEADERS, {"store_id": store["id"]}
            )
        )
        == 2
    )
    assert X.get_report(api, incumbent["id"])["status"] == REPORT_DRAFT


def test_charging_above_the_nameplate_is_rejected_with_contents_to_spare(api):
    """
    §3.3 checks both ends of the transfer. The cylinder holds 40.0 lbs so the
    insufficient-contents rule is satisfied; only the projected 105.0 lb system
    charge breaks the 100.0 lb nameplate.

    Design: Corner/validations/charge_above_nameplate_is_rejected_with_cylinder_contents_to_spare
    """
    env = X.base_env(api, with_second_technician=False)

    validate_error(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                env["system"]["version"],
                cylinder_id=env["cyl1_id"],
                service_type=SERVICE_ADD_REFRIGERANT,
                refrigerant_added_lbs=25.0,
                performed_at="2026-08-01T00:00:00Z",
                duration_minutes=60,
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        ERR_CHARGE_EXCEEDS_NAMEPLATE,
        422,
    )

    system = X.get_system(api, env["system_id"])
    assert_system_charge(system, current_charge_lbs=80.0)
    assert system["version"] == 1
    cylinder = X.get_cylinder(api, env["cyl1_id"])
    assert_mass(cylinder["current_contents_lbs"], 40.0, "current_contents_lbs")
    assert cylinder["disposition"] == DISPOSITION_VIRGIN


def test_recovering_more_than_the_system_holds_is_rejected(api):
    """
    §3.3 forbids a projected system charge below 0.0. An oversized empty cylinder
    keeps the fill-limit rule out of play, so the negative projection is the only
    thing wrong with the record.

    Design: Corner/validations/recovering_more_than_the_system_holds_is_rejected
    """
    env = X.base_env(
        api,
        with_second_technician=False,
        system_overrides={"initial_charge_lbs": 20.0},
        cylinder_overrides={
            "cylinder_serial": "CYL-BIG",
            "nominal_capacity_lbs": 200.0,
            "initial_contents_lbs": 0.0,
        },
    )
    assert_mass(env["cyl1"]["fill_limit_lbs"], 160.0, "fill_limit_lbs")

    validate_error(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                env["system"]["version"],
                cylinder_id=env["cyl1_id"],
                service_type=SERVICE_RECOVER_REFRIGERANT,
                refrigerant_added_lbs=F.OMIT,
                refrigerant_recovered_lbs=50.0,
                performed_at="2026-08-01T00:00:00Z",
                duration_minutes=60,
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        ERR_NEGATIVE_SYSTEM_CHARGE,
        422,
    )

    system = X.get_system(api, env["system_id"])
    assert_system_charge(system, current_charge_lbs=20.0)
    assert system["version"] == 1
    cylinder = X.get_cylinder(api, env["cyl1_id"])
    assert_mass(cylinder["current_contents_lbs"], 0.0, "current_contents_lbs")
    assert cylinder["disposition"] == DISPOSITION_VIRGIN


def test_the_industrial_shutdown_reason_does_not_apply_to_a_commercial_system(api):
    """
    §3.6 makes two of the four statutory reasons conditional on the parent system.
    The identical request body is refused under the industrial reason and accepted
    under PARTS_UNAVAILABLE, and a PENDING request moves no deadline.

    Design: Corner/validations/industrial_shutdown_extension_reason_does_not_apply_to_a_commercial_system
    """
    env = X.manual_event_env(api, with_second_technician=False)

    validate_error(
        api.create_extension_request(
            F.extension_request_payload(
                env["event_id"],
                reason_code=REASON_INDUSTRIAL_PROCESS_SHUTDOWN_REQUIRED,
                requested_days=10,
                justification="Process line cannot be shut down before the holiday season.",
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_EXTENSION_REASON_NOT_APPLICABLE,
        422,
    )

    accepted = validate_success(
        api.create_extension_request(
            F.extension_request_payload(
                env["event_id"],
                reason_code=REASON_PARTS_UNAVAILABLE,
                requested_days=10,
                justification="Compressor gasket kit on national backorder.",
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert accepted["status"] == EXTENSION_PENDING
    assert accepted["granted_days"] is None
    assert_instant(accepted["requested_at"], "2026-08-01T00:00:00Z", "requested_at")
    assert_instant(accepted["expires_at"], "2026-08-16T00:00:00Z", "expires_at")
    assert_instant(accepted["deadline_before"], "2026-08-31T00:00:00Z", "deadline_before")
    assert_instant_is_none(accepted["deadline_after"], "deadline_after")

    event = X.get_leak_event(api, env["event_id"])
    assert_instant(event["repair_deadline"], "2026-08-31T00:00:00Z", "repair_deadline")
    assert_extension_budget(event, 0, 30)
    assert (
        _total_count(
            api.list_extension_requests(
                COMPLIANCE_MANAGER_HEADERS, {"leak_event_id": env["event_id"]}
            )
        )
        == 1
    )


def test_the_retrofit_target_is_mandatory_one_way_and_forbidden_the_other(api):
    """
    §3.7 makes `target_refrigerant_type_id` required on a RETROFIT and forbidden on
    a RETIRE, reporting both violations under one identifier; a bare RETIRE plan
    bypasses the compatibility arithmetic entirely.

    Design: Corner/validations/retrofit_plan_target_chemistry_is_required_and_forbidden_by_plan_type
    """
    env = X.base_env(
        api, with_r448a=True, with_cylinder=False, with_second_technician=False
    )
    version = env["system"]["version"]

    validate_error(
        api.create_retrofit_plan(
            F.retrofit_plan_payload(
                env["system_id"],
                version,
                due_on="2026-12-01T00:00:00Z",
                estimated_cost_usd=50000.00,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_RETROFIT_TARGET_REQUIRED,
        422,
    )

    validate_error(
        api.create_retrofit_plan(
            F.retrofit_plan_payload(
                env["system_id"],
                version,
                plan_type=PLAN_RETIRE,
                target_refrigerant_type_id=env["rt448_id"],
                due_on="2026-12-01T00:00:00Z",
                estimated_cost_usd=50000.00,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_RETROFIT_TARGET_REQUIRED,
        422,
    )

    plan = validate_success(
        api.create_retrofit_plan(
            F.retrofit_plan_payload(
                env["system_id"],
                version,
                plan_type=PLAN_RETIRE,
                due_on="2026-12-01T00:00:00Z",
                estimated_cost_usd=50000.00,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert plan["status"] == PLAN_DRAFT
    assert_score(plan["compatibility_score"], 100.0, "compatibility_score")
    assert plan["compatibility_result"] == COMPAT_COMPATIBLE
    assert_score(plan["gwp_reduction_pct"], 0.0, "gwp_reduction_pct")
    assert plan["mandated"] is False

    assert (
        _total_count(
            api.list_retrofit_plans(
                COMPLIANCE_MANAGER_HEADERS, {"system_id": env["system_id"]}
            )
        )
        == 1
    )


def test_a_retrofit_to_a_prohibited_chemistry_is_rejected_at_creation(api):
    """
    §3.7 checks the target chemistry's phasedown standing when the plan is filed,
    not when it is submitted, so no plan row is written at all.

    Design: Corner/validations/retrofit_to_a_prohibited_refrigerant_is_rejected_at_creation
    """
    env = X.base_env(api, with_cylinder=False, with_second_technician=False)
    prohibited = validate_success(
        api.create_refrigerant_type(
            F.refrigerant_type_payload(
                name="R-22",
                gwp=1810,
                pressure_class=PRESSURE_HIGH,
                ods_class=ODS_HCFC,
                phasedown_status=PHASEDOWN_PROHIBITED,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )

    validate_error(
        api.create_retrofit_plan(
            F.retrofit_plan_payload(
                env["system_id"],
                env["system"]["version"],
                target_refrigerant_type_id=prohibited["id"],
                due_on="2026-12-01T00:00:00Z",
                estimated_cost_usd=50000.00,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_TARGET_REFRIGERANT_PROHIBITED,
        422,
    )

    assert (
        _total_count(
            api.list_retrofit_plans(
                COMPLIANCE_MANAGER_HEADERS, {"system_id": env["system_id"]}
            )
        )
        == 0
    )
    assert X.get_system(api, env["system_id"])["refrigerant_type_id"] == env["rt404_id"]


def test_an_incompatible_retrofit_can_be_drafted_but_never_submitted(api):
    """
    §3.7 lets the draft exist so the operator can read its score, and puts the
    compatibility gate on submission: a natural-refrigerant system converting to
    R-404A scores 42.5 and cannot pass that gate.

    Design: Corner/validations/incompatible_retrofit_can_be_drafted_but_not_submitted
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    r290 = X.create_r290(api)
    rt404 = X.create_r404a(api)
    system = X.create_system(api, store["id"], r290["id"])

    plan = validate_success(
        api.create_retrofit_plan(
            F.retrofit_plan_payload(
                system["id"],
                system["version"],
                target_refrigerant_type_id=rt404["id"],
                due_on="2026-12-01T00:00:00Z",
                estimated_cost_usd=50000.00,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert_score(plan["compatibility_score"], 42.5, "compatibility_score")
    assert plan["compatibility_result"] == COMPAT_INCOMPATIBLE
    assert_score(plan["gwp_reduction_pct"], 0.0, "gwp_reduction_pct")

    validate_error(
        api.submit_retrofit_plan(
            plan["id"],
            F.plan_submission_payload(
                submission_note="Submitting the incompatible conversion."
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_RETROFIT_INCOMPATIBLE,
        422,
    )

    stored = X.get_plan(api, plan["id"])
    assert stored["status"] == PLAN_DRAFT
    assert stored["submission_count"] == 0
    assert_instant_is_none(stored["submitted_at"], "submitted_at")


def test_a_regulator_cannot_grant_more_days_than_were_requested(api):
    """
    §3.6 orders the approval checks so that `granted_days` is measured against the
    request's own `requested_days` first: 15 against 10 is refused even though 15
    is well inside the event's 30-day budget.

    Design: Corner/validations/granting_more_days_than_requested_is_rejected
    """
    env = X.manual_event_env(api, with_second_technician=False)
    request = X.file_extension_request(
        api,
        env["event_id"],
        requested_days=10,
        justification="Compressor gasket kit on national backorder.",
    )

    validate_error(
        api.decide_extension_request(
            request["id"],
            F.extension_decision_payload(DECISION_APPROVE, granted_days=15),
            REGULATOR_HEADERS,
        ),
        ERR_GRANTED_DAYS_EXCEED_REQUESTED,
        422,
    )

    stored = X.get_extension_request(api, request["id"])
    assert stored["status"] == EXTENSION_PENDING
    assert stored["granted_days"] is None
    assert_instant_is_none(stored["decided_at"], "decided_at")
    assert_instant_is_none(stored["deadline_after"], "deadline_after")

    event = X.get_leak_event(api, env["event_id"])
    assert_instant(event["repair_deadline"], "2026-08-31T00:00:00Z", "repair_deadline")
    assert_extension_budget(event, 0, 30)


def test_an_extension_filed_after_the_repair_deadline_lapsed_is_rejected(api):
    """
    §3.6 makes an extension a forward-looking instrument: filed five days after the
    repair deadline it is refused, and the event's 30-day budget stays unspent.

    Design: Corner/validations/extension_filed_after_the_repair_deadline_has_lapsed_is_rejected
    """
    env = X.manual_event_env(api, with_second_technician=False)
    X.set_clock(api, "2026-09-05T00:00:00Z")

    validate_error(
        api.create_extension_request(
            F.extension_request_payload(
                env["event_id"],
                reason_code=REASON_PARTS_UNAVAILABLE,
                requested_days=10,
                justification="Compressor gasket kit on national backorder.",
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_EXTENSION_WINDOW_CLOSED,
        422,
    )

    assert (
        _total_count(
            api.list_extension_requests(
                COMPLIANCE_MANAGER_HEADERS, {"leak_event_id": env["event_id"]}
            )
        )
        == 0
    )
    event = X.get_leak_event(api, env["event_id"])
    assert_instant(event["repair_deadline"], "2026-08-31T00:00:00Z", "repair_deadline")
    assert_extension_budget(event, 0, 30)


def _one_addition_to_void(api):
    """
    The reference store with a single 10.0 lb top-up on it: the leak rate lands at
    10.0 percent, below the 20.0 threshold, so no leak event exists to complicate
    the compensation.
    """
    env = X.base_env(api, with_second_technician=False)
    record = X.file_service_record(
        api,
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        service_type=SERVICE_ADD_REFRIGERANT,
        cylinder_id=env["cyl1_id"],
        refrigerant_added_lbs=10.0,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=120,
    )
    env["record"] = record
    env["record_id"] = record["id"]
    return env


def test_voiding_a_service_record_twice_is_rejected(api):
    """
    §3.8 stamps the compensation on the first void and refuses the identical second
    call rather than silently succeeding, so the reversal can never hit the ledger
    twice.

    Design: Corner/validations/voiding_a_service_record_twice_is_rejected
    """
    env = _one_addition_to_void(api)

    voided = validate_success(
        api.void_service_record(
            env["record_id"],
            F.void_payload(void_reason_code="DATA_ENTRY_ERROR"),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert voided["voided"] is True
    assert_instant(voided["voided_at"], "2026-08-01T00:00:00Z", "voided_at")
    assert voided["void_reason_code"] == "DATA_ENTRY_ERROR"

    assert_system_charge(
        X.get_system(api, env["system_id"]), current_charge_lbs=80.0, leak_rate_pct=0.0
    )
    assert_mass(
        X.get_cylinder(api, env["cyl1_id"])["current_contents_lbs"],
        40.0,
        "current_contents_lbs",
    )

    validate_error(
        api.void_service_record(
            env["record_id"],
            F.void_payload(void_reason_code="DATA_ENTRY_ERROR"),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_SERVICE_RECORD_ALREADY_VOIDED,
        409,
    )

    assert_system_charge(X.get_system(api, env["system_id"]), current_charge_lbs=80.0)
    assert_instant(
        X.get_service_record(api, env["record_id"])["retention_until"],
        "2029-08-01T00:00:00Z",
        "retention_until",
    )


def test_voiding_a_record_past_its_retention_horizon_is_not_permitted(api):
    """
    §3.8 forbids compensating a record whose `retention_until` the clock has already
    passed: the record is archival evidence, still un-voided, and the 10.0 lb
    addition stays in the ledger.

    Design: Corner/validations/voiding_a_record_past_its_retention_horizon_is_not_permitted
    """
    env = _one_addition_to_void(api)
    assert_instant(
        env["record"]["retention_until"], "2029-08-01T00:00:00Z", "retention_until"
    )

    X.set_clock(api, "2029-08-02T00:00:00Z")
    validate_error(
        api.void_service_record(
            env["record_id"],
            F.void_payload(void_reason_code="DATA_ENTRY_ERROR"),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_VOID_NOT_PERMITTED,
        422,
    )

    stored = X.get_service_record(api, env["record_id"])
    assert stored["voided"] is False
    assert_instant_is_none(stored["voided_at"], "voided_at")
    assert stored["void_reason_code"] is None
    assert_system_charge(
        X.get_system(api, env["system_id"]), current_charge_lbs=90.0, leak_rate_pct=10.0
    )
