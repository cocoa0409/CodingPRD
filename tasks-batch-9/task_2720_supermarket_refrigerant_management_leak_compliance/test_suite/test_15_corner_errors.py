"""
Error-identifier corners: every not-found code on its own read surface, and the
§2.9 losers proved reachable one at a time — identity, certification, machine
pressure class, chain of custody, repair chronology, both cylinder mass rules,
retirement recovery, the two reclaim gates and the fiscal band on a plan.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_CHARGE_EXCEEDS_NAMEPLATE,
    ERR_CYLINDER_FILL_LIMIT_EXCEEDED,
    ERR_FORBIDDEN_ROLE,
    ERR_INSUFFICIENT_CYLINDER_CONTENTS,
    ERR_INVALID_REQUEST,
    ERR_LEAK_EVENT_SYSTEM_MISMATCH,
    ERR_NEGATIVE_SYSTEM_CHARGE,
    ERR_OPEN_LEAK_EVENT_BLOCKS_RETIREMENT,
    ERR_PLAN_COST_OUT_OF_RANGE,
    ERR_RECLAIM_PURITY_NOT_VERIFIED,
    ERR_RECLAIM_QUANTITY_EXCEEDS_SHIPPED,
    ERR_RECOVERY_EQUIPMENT_INCOMPATIBLE,
    ERR_RECOVERY_EQUIPMENT_NOT_CERTIFIED,
    ERR_REPAIR_BEFORE_DETECTION,
    ERR_SYSTEM_CHARGE_NOT_RECOVERED,
    ERR_SYSTEM_NOT_FOUND,
    ERR_TECHNICIAN_CERT_EXPIRED,
    ERR_TECHNICIAN_CERT_TYPE_INVALID,
    ERR_TECHNICIAN_IDENTITY_MISMATCH,
    ERR_TIMESTAMP_AFTER_CLOCK,
    ERR_UNRECLAIMED_REFRIGERANT_REUSE,
    NOT_FOUND_BY_RESOURCE,
)
from test_helpers.assertions import (
    assert_array_envelope,
    assert_instant,
    assert_instant_is_none,
    assert_mass,
    assert_store_posture,
    assert_system_axes,
    assert_system_charge,
)
from test_helpers.test_users import (
    COMPLIANCE_MANAGER_HEADERS,
    make_technician_headers,
)
from test_helpers.types import (
    CERT_TYPE_I,
    CERT_TYPE_II,
    DISPOSITION_RECLAIMED,
    DISPOSITION_SENT_FOR_RECLAIM,
    EQUIPMENT_CERTIFIED,
    EVENT_OPEN,
    EVENT_VERIFICATION_PENDING,
    PLAN_DRAFT,
    PRESSURE_LOW,
    SERVICE_RECOVER_REFRIGERANT,
    SYSTEM_ACTIVE,
    SYSTEM_RETIRED,
)


def _total_count(response) -> int:
    """The `meta.total_count` of a listing, envelope checked on the way past."""
    return assert_array_envelope(response)["meta"]["total_count"]


def test_each_single_resource_read_returns_its_own_not_found_code(api):
    """
    §5 declares fourteen separate not-found identifiers rather than one generic
    404, so the same well-formed but unknown UUID must produce a different
    `error_id` on each collection — and on the projection sub-resource too.

    Design: Corner/errors/unknown_identifier_on_every_single_resource_read_returns_its_own_not_found_code
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")

    seen = {}
    for segment, error_id in NOT_FOUND_BY_RESOURCE.items():
        response = api.get_path(f"/{segment}/{NON_EXISTENT_UUID}", COMPLIANCE_MANAGER_HEADERS)
        assert response.status_code == 404, (
            f"GET /{segment}/{{unknown}} must be 404, got {response.status_code}"
        )
        body = validate_error(response, error_id, 404)
        assert body["error_id"] != "ERR_NOT_FOUND", "no shared generic 404 is permitted"
        seen[segment] = body["error_id"]

    assert len(set(seen.values())) == 14, (
        f"each read surface must carry its own code, got {sorted(set(seen.values()))}"
    )

    projection = api.get_path(
        f"/systems/{NON_EXISTENT_UUID}/leak-rate-projection", COMPLIANCE_MANAGER_HEADERS
    )
    validate_error(projection, ERR_SYSTEM_NOT_FOUND, 404)


def test_a_technician_may_not_file_a_record_under_another_technicians_id(api):
    """
    §2.1 threads the acting technician's own id through `X-User-ID`, so a genuine
    Technician on a Technician-only endpoint who names a colleague in the body is
    refused for identity, not for role.

    Design: Corner/errors/technician_filing_a_record_under_another_technicians_id_is_rejected
    """
    env = X.base_env(api)
    body = F.service_record_payload(
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        X.system_version(api, env["system_id"]),
        cylinder_id=env["cyl1_id"],
        refrigerant_added_lbs=10.0,
        duration_minutes=60,
    )

    refused = validate_error(
        api.create_service_record(body, make_technician_headers(env["tech2_id"])),
        ERR_TECHNICIAN_IDENTITY_MISMATCH,
        403,
    )
    assert refused["error_id"] != ERR_FORBIDDEN_ROLE, (
        "Technician is a permitted role on this endpoint; only the header is wrong"
    )

    assert _total_count(
        api.list_service_records(COMPLIANCE_MANAGER_HEADERS, {"system_id": env["system_id"]})
    ) == 0
    assert_system_charge(X.get_system(api, env["system_id"]), current_charge_lbs=80.0)
    assert X.system_version(api, env["system_id"]) == body["expected_system_version"]

    validate_success(
        api.create_service_record(body, make_technician_headers(env["tech1_id"])),
        expected_status=201,
    )


def test_an_expired_card_and_the_wrong_class_are_distinct_certification_errors(api):
    """
    §3.2 runs the expiry gate and the class-adequacy gate in that order and gives
    each its own code, and the expiry gate is measured against the timestamp of
    the work rather than against the logical clock.

    Design: Corner/errors/expired_certification_and_wrong_certification_class_are_distinct_errors
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    system = X.create_system(api, store["id"], rt404["id"])
    expired = X.create_technician(api, certification_expires_on="2026-07-01T00:00:00Z")
    wrong_class = X.create_second_technician(
        api,
        full_name="Priya Sandoval",
        epa_certification_number="EPA-608-33333",
        certification_type=CERT_TYPE_I,
        certification_expires_on="2027-12-31T00:00:00Z",
    )
    equipment = X.create_equipment(api, store["id"], wrong_class["id"])
    cylinder = X.create_cylinder(api, store["id"], rt404["id"])

    assert system["required_certification_type"] == CERT_TYPE_II
    version = system["version"]

    def _record(technician_id, performed_at):
        return F.service_record_payload(
            system["id"],
            technician_id,
            equipment["id"],
            version,
            cylinder_id=cylinder["id"],
            refrigerant_added_lbs=10.0,
            performed_at=performed_at,
            duration_minutes=60,
        )

    validate_error(
        api.create_service_record(
            _record(expired["id"], "2026-08-01T00:00:00Z"),
            make_technician_headers(expired["id"]),
        ),
        ERR_TECHNICIAN_CERT_EXPIRED,
        422,
    )
    validate_error(
        api.create_service_record(
            _record(wrong_class["id"], "2026-08-01T00:00:00Z"),
            make_technician_headers(wrong_class["id"]),
        ),
        ERR_TECHNICIAN_CERT_TYPE_INVALID,
        422,
    )

    assert _total_count(
        api.list_service_records(COMPLIANCE_MANAGER_HEADERS, {"system_id": system["id"]})
    ) == 0
    assert_system_charge(X.get_system(api, system["id"]), current_charge_lbs=80.0)

    validate_success(
        api.create_service_record(
            _record(expired["id"], "2026-06-15T00:00:00Z"),
            make_technician_headers(expired["id"]),
        ),
        expected_status=201,
    )


def test_a_low_pressure_machine_cannot_service_a_high_pressure_chemistry(api):
    """
    §3.2 keeps machine currency and machine suitability apart: a machine verified
    two months ago is CERTIFIED, so the only defect left is a LOW pressure class
    against a HIGH chemistry, and that must carry the incompatibility code.

    Design: Corner/errors/low_pressure_recovery_machine_cannot_service_a_high_pressure_chemistry
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    system = X.create_system(api, store["id"], rt404["id"])
    technician = X.create_second_technician(api, full_name="Marek Olsen")
    low_machine = X.create_equipment(
        api,
        store["id"],
        technician["id"],
        equipment_serial="RM-LOW-1",
        certified_for_pressure_class=PRESSURE_LOW,
    )
    cylinder = X.create_cylinder(api, store["id"], rt404["id"])

    assert low_machine["status"] == EQUIPMENT_CERTIFIED, (
        "the machine is current, so the certification gate cannot be the cause"
    )

    def _record(equipment_id):
        return F.service_record_payload(
            system["id"],
            technician["id"],
            equipment_id,
            system["version"],
            cylinder_id=cylinder["id"],
            refrigerant_added_lbs=10.0,
            duration_minutes=60,
        )

    refused = validate_error(
        api.create_service_record(
            _record(low_machine["id"]), make_technician_headers(technician["id"])
        ),
        ERR_RECOVERY_EQUIPMENT_INCOMPATIBLE,
        422,
    )
    assert refused["error_id"] != ERR_RECOVERY_EQUIPMENT_NOT_CERTIFIED

    assert _total_count(
        api.list_service_records(COMPLIANCE_MANAGER_HEADERS, {"system_id": system["id"]})
    ) == 0
    assert_system_charge(X.get_system(api, system["id"]), current_charge_lbs=80.0)
    assert_mass(
        X.get_cylinder(api, cylinder["id"])["current_contents_lbs"],
        40.0,
        "current_contents_lbs",
    )

    high_machine = X.create_equipment(api, store["id"], technician["id"])
    validate_success(
        api.create_service_record(
            _record(high_machine["id"]), make_technician_headers(technician["id"])
        ),
        expected_status=201,
    )


def test_refrigerant_awaiting_reclaim_cannot_be_charged_back_into_a_system(api):
    """
    §3.2's chain of custody outranks arithmetic: the shipped cylinder holds 0.0 lb,
    so the naive answer is the contents error, but §2.9 puts the disposition rule
    ahead of it and reuse of unreclaimed refrigerant is what must be reported.

    Design: Corner/errors/refrigerant_awaiting_reclaim_cannot_be_charged_back_into_a_system
    """
    # The clock sits at 04:00 so that the closing charge, which has to clear the
    # decontamination buffer, is still at or before it (§2.4).
    X.set_clock(api, "2026-08-01T04:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    system = X.create_system(api, store["id"], rt404["id"])
    technician = X.create_second_technician(api, full_name="Marek Olsen")
    equipment = X.create_equipment(api, store["id"], technician["id"])
    cylinder = X.create_cylinder(api, store["id"], rt404["id"], initial_contents_lbs=0.0)

    X.file_service_record(
        api,
        system["id"],
        technician["id"],
        equipment["id"],
        service_type=SERVICE_RECOVER_REFRIGERANT,
        cylinder_id=cylinder["id"],
        refrigerant_added_lbs=F.OMIT,
        refrigerant_recovered_lbs=20.0,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=45,
    )
    validate_success(
        api.ship_for_reclaim(
            cylinder["id"],
            F.reclaim_shipment_payload(reclaimer_name="Cascade Reclaim LLC"),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )

    shipped = X.get_cylinder(api, cylinder["id"])
    assert shipped["disposition"] == DISPOSITION_SENT_FOR_RECLAIM
    assert_mass(shipped["current_contents_lbs"], 0.0, "current_contents_lbs")
    assert_mass(shipped["shipped_for_reclaim_lbs"], 20.0, "shipped_for_reclaim_lbs")
    assert_system_charge(X.get_system(api, system["id"]), current_charge_lbs=60.0)

    def _charge(performed_at):
        return F.service_record_payload(
            system["id"],
            technician["id"],
            equipment["id"],
            X.system_version(api, system["id"]),
            cylinder_id=cylinder["id"],
            refrigerant_added_lbs=10.0,
            performed_at=performed_at,
            duration_minutes=30,
        )

    refused = validate_error(
        api.create_service_record(
            _charge("2026-08-01T00:00:00Z"), make_technician_headers(technician["id"])
        ),
        ERR_UNRECLAIMED_REFRIGERANT_REUSE,
        422,
    )
    assert refused["error_id"] != ERR_INSUFFICIENT_CYLINDER_CONTENTS, (
        "the disposition rule precedes the cylinder-contents rule"
    )

    assert _total_count(
        api.list_service_records(COMPLIANCE_MANAGER_HEADERS, {"system_id": system["id"]})
    ) == 1
    assert_system_charge(X.get_system(api, system["id"]), current_charge_lbs=60.0)
    still_shipped = X.get_cylinder(api, cylinder["id"])
    assert still_shipped["disposition"] == DISPOSITION_SENT_FOR_RECLAIM
    assert_mass(still_shipped["shipped_for_reclaim_lbs"], 20.0, "shipped_for_reclaim_lbs")

    reclaimed = validate_success(
        api.certify_reclaim(
            cylinder["id"],
            F.reclaim_certification_payload(20.0, "2026-08-01T00:00:00Z"),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert reclaimed["disposition"] == DISPOSITION_RECLAIMED
    # Four hours on, clear of the labour interval and the decontamination buffer,
    # so disposition is demonstrably the only thing that had barred the charge.
    validate_success(
        api.create_service_record(
            _charge("2026-08-01T04:00:00Z"), make_technician_headers(technician["id"])
        ),
        expected_status=201,
    )


def test_repair_attempt_cross_reference_and_backdating_are_each_caught(api):
    """
    §3.5 treats the `system_id` on a repair attempt as an asserted cross-reference
    and requires the work to postdate detection; a repair filed six days before the
    leak was found is a chronology fault, not a future-timestamp fault.

    Design: Corner/errors/repair_attempt_cross_reference_and_backdating_are_each_caught
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    system_a = X.create_system(
        api, store["id"], rt404["id"], full_charge_lbs=60.0, initial_charge_lbs=0.0
    )
    system_b = X.create_system(
        api, store["id"], rt404["id"], full_charge_lbs=60.0, initial_charge_lbs=0.0
    )
    technician = X.create_second_technician(api, full_name="Marek Olsen")
    equipment = X.create_equipment(api, store["id"], technician["id"])
    event = X.declare_leak_event(api, system_a["id"], detected_at="2026-08-01T00:00:00Z")

    X.set_clock(api, "2026-08-10T00:00:00Z")

    def _attempt(system_id, repair_completed_at):
        return F.repair_attempt_payload(
            event["id"], system_id, technician["id"], equipment["id"], repair_completed_at
        )

    validate_error(
        api.create_repair_attempt(
            _attempt(system_b["id"], "2026-08-05T00:00:00Z"),
            make_technician_headers(technician["id"]),
        ),
        ERR_LEAK_EVENT_SYSTEM_MISMATCH,
        422,
    )
    backdated = validate_error(
        api.create_repair_attempt(
            _attempt(system_a["id"], "2026-07-25T00:00:00Z"),
            make_technician_headers(technician["id"]),
        ),
        ERR_REPAIR_BEFORE_DETECTION,
        422,
    )
    assert backdated["error_id"] != ERR_TIMESTAMP_AFTER_CLOCK, (
        "2026-07-25 is well before the logical clock at 2026-08-10"
    )

    untouched = X.get_leak_event(api, event["id"])
    assert untouched["status"] == EVENT_OPEN
    assert untouched["repair_attempt_count"] == 0
    assert _total_count(
        api.list_repair_attempts(COMPLIANCE_MANAGER_HEADERS, {"leak_event_id": event["id"]})
    ) == 0

    validate_success(
        api.create_repair_attempt(
            _attempt(system_a["id"], "2026-08-05T00:00:00Z"),
            make_technician_headers(technician["id"]),
        ),
        expected_status=201,
    )
    assert X.get_leak_event(api, event["id"])["status"] == EVENT_VERIFICATION_PENDING


def test_the_fill_limit_and_the_empty_cylinder_are_each_reachable_alone(api):
    """
    §3.3 checks both ends of every transfer. Here the system side stays legal on
    both attempts (70.0 and 90.0 sit inside 0.0..100.0), so each refusal can only
    come from the cylinder: over its DOT fill limit, or below empty.

    Design: Corner/errors/cylinder_fill_limit_and_empty_cylinder_are_both_reachable_on_their_own
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    system = X.create_system(api, store["id"], rt404["id"])
    technician = X.create_second_technician(api, full_name="Marek Olsen")
    equipment = X.create_equipment(api, store["id"], technician["id"])
    nearly_full = X.create_cylinder(
        api,
        store["id"],
        rt404["id"],
        cylinder_serial="CYL-FULL",
        initial_contents_lbs=35.0,
    )
    nearly_empty = X.create_cylinder(
        api,
        store["id"],
        rt404["id"],
        cylinder_serial="CYL-NEARLY-EMPTY",
        initial_contents_lbs=5.0,
    )

    assert_mass(nearly_full["fill_limit_lbs"], 40.0, "fill_limit_lbs")
    version = system["version"]

    def _recovery(cylinder_id, recovered):
        return F.service_record_payload(
            system["id"],
            technician["id"],
            equipment["id"],
            version,
            service_type=SERVICE_RECOVER_REFRIGERANT,
            cylinder_id=cylinder_id,
            refrigerant_added_lbs=F.OMIT,
            refrigerant_recovered_lbs=recovered,
            duration_minutes=30,
        )

    over_limit = validate_error(
        api.create_service_record(
            _recovery(nearly_full["id"], 10.0), make_technician_headers(technician["id"])
        ),
        ERR_CYLINDER_FILL_LIMIT_EXCEEDED,
        422,
    )
    under_empty = validate_error(
        api.create_service_record(
            F.service_record_payload(
                system["id"],
                technician["id"],
                equipment["id"],
                version,
                cylinder_id=nearly_empty["id"],
                refrigerant_added_lbs=10.0,
                duration_minutes=30,
            ),
            make_technician_headers(technician["id"]),
        ),
        ERR_INSUFFICIENT_CYLINDER_CONTENTS,
        422,
    )
    for refused in (over_limit, under_empty):
        assert refused["error_id"] not in (
            ERR_CHARGE_EXCEEDS_NAMEPLATE,
            ERR_NEGATIVE_SYSTEM_CHARGE,
        ), "both system-side projections are legal, so neither system rule may fire"

    assert _total_count(
        api.list_service_records(COMPLIANCE_MANAGER_HEADERS, {"system_id": system["id"]})
    ) == 0
    assert_mass(
        X.get_cylinder(api, nearly_full["id"])["current_contents_lbs"], 35.0, "CYL-FULL"
    )
    assert_mass(
        X.get_cylinder(api, nearly_empty["id"])["current_contents_lbs"], 5.0, "CYL-NEARLY-EMPTY"
    )
    after = X.get_system(api, system["id"])
    assert_system_charge(after, current_charge_lbs=80.0)
    assert after["version"] == version

    validate_success(
        api.create_service_record(
            _recovery(nearly_full["id"], 5.0), make_technician_headers(technician["id"])
        ),
        expected_status=201,
    )


def test_a_system_still_holding_refrigerant_cannot_be_retired(api):
    """
    §3.7 gates retirement on physical recovery. With no leak events at all the
    open-event bar cannot fire, so the 80.0 lb still in the circuit is the only
    possible objection — and recovering it clears the way.

    Design: Corner/errors/a_system_still_holding_refrigerant_cannot_be_retired
    """
    env = X.base_env(
        api,
        with_second_technician=False,
        cylinder_overrides={
            "cylinder_serial": "CYL-BIG",
            "nominal_capacity_lbs": 200.0,
            "initial_contents_lbs": 0.0,
        },
    )

    refused = validate_error(
        api.retire_system(
            env["system_id"],
            F.retirement_payload(retirement_reason_code="END_OF_LIFE"),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_SYSTEM_CHARGE_NOT_RECOVERED,
        422,
    )
    assert refused["error_id"] != ERR_OPEN_LEAK_EVENT_BLOCKS_RETIREMENT, (
        "the system carries no leak events at all"
    )

    system = X.get_system(api, env["system_id"])
    assert_system_axes(system, operational_status=SYSTEM_ACTIVE)
    assert_instant_is_none(system["retired_on"], "retired_on")
    assert_store_posture(
        X.get_store(api, env["store_id"]),
        regulated_system_count=1,
        total_regulated_charge_lbs=100.0,
    )

    X.file_service_record(
        api,
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        service_type=SERVICE_RECOVER_REFRIGERANT,
        cylinder_id=env["cyl1_id"],
        refrigerant_added_lbs=F.OMIT,
        refrigerant_recovered_lbs=80.0,
        duration_minutes=180,
    )
    retired = validate_success(
        api.retire_system(
            env["system_id"],
            F.retirement_payload(retirement_reason_code="END_OF_LIFE"),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert_system_axes(retired, operational_status=SYSTEM_RETIRED)


def test_reclaim_quantity_and_purity_are_each_refused_on_their_own(api):
    """
    §3.2's closing step has two independent gates. Two cylinders shipped with the
    same 20.0 lb break one apiece — a quantity that would create mass, and a
    missing purity attestation — and neither certificate is partly applied.

    Design: Corner/errors/reclaim_certification_quantity_and_purity_are_checked_in_priority_order
    """
    # The second recovery is filed six hours on to clear the machine's
    # decontamination buffer, so the clock has to be at or after it (§2.4).
    X.set_clock(api, "2026-08-01T06:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    system = X.create_system(api, store["id"], rt404["id"])
    technician = X.create_second_technician(api, full_name="Marek Olsen")
    equipment = X.create_equipment(api, store["id"], technician["id"])
    cylinder_a = X.create_cylinder(
        api, store["id"], rt404["id"], cylinder_serial="CYL-A", initial_contents_lbs=0.0
    )
    cylinder_b = X.create_cylinder(
        api, store["id"], rt404["id"], cylinder_serial="CYL-B", initial_contents_lbs=0.0
    )

    for cylinder, performed_at in (
        (cylinder_a, "2026-08-01T00:00:00Z"),
        (cylinder_b, "2026-08-01T06:00:00Z"),
    ):
        X.file_service_record(
            api,
            system["id"],
            technician["id"],
            equipment["id"],
            service_type=SERVICE_RECOVER_REFRIGERANT,
            cylinder_id=cylinder["id"],
            refrigerant_added_lbs=F.OMIT,
            refrigerant_recovered_lbs=20.0,
            performed_at=performed_at,
            duration_minutes=30,
        )
        validate_success(
            api.ship_for_reclaim(
                cylinder["id"],
                F.reclaim_shipment_payload(reclaimer_name="Cascade Reclaim LLC"),
                COMPLIANCE_MANAGER_HEADERS,
            )
        )

    for cylinder in (cylinder_a, cylinder_b):
        shipped = X.get_cylinder(api, cylinder["id"])
        assert shipped["disposition"] == DISPOSITION_SENT_FOR_RECLAIM
        assert_mass(shipped["shipped_for_reclaim_lbs"], 20.0, "shipped_for_reclaim_lbs")
        assert_mass(shipped["current_contents_lbs"], 0.0, "current_contents_lbs")
    assert_system_charge(X.get_system(api, system["id"]), current_charge_lbs=40.0)

    validate_error(
        api.certify_reclaim(
            cylinder_a["id"],
            F.reclaim_certification_payload(
                25.0, "2026-08-01T00:00:00Z", reclaim_certificate_number="AHRI-700-A"
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_RECLAIM_QUANTITY_EXCEEDS_SHIPPED,
        422,
    )
    validate_error(
        api.certify_reclaim(
            cylinder_b["id"],
            F.reclaim_certification_payload(
                15.0,
                "2026-08-01T00:00:00Z",
                reclaim_certificate_number="AHRI-700-B",
                purity_verified=False,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_RECLAIM_PURITY_NOT_VERIFIED,
        422,
    )

    for cylinder in (cylinder_a, cylinder_b):
        untouched = X.get_cylinder(api, cylinder["id"])
        assert untouched["reclaim_certificate_number"] is None
        assert untouched["disposition"] == DISPOSITION_SENT_FOR_RECLAIM
        assert_mass(untouched["shipped_for_reclaim_lbs"], 20.0, "shipped_for_reclaim_lbs")
        assert_mass(untouched["current_contents_lbs"], 0.0, "current_contents_lbs")

    certified = validate_success(
        api.certify_reclaim(
            cylinder_a["id"],
            F.reclaim_certification_payload(
                20.0, "2026-08-01T00:00:00Z", reclaim_certificate_number="AHRI-700-A"
            ),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert certified["disposition"] == DISPOSITION_RECLAIMED
    assert_mass(certified["current_contents_lbs"], 20.0, "current_contents_lbs")
    assert_mass(certified["shipped_for_reclaim_lbs"], 0.0, "shipped_for_reclaim_lbs")


def test_a_plan_cost_above_the_statutory_ceiling_is_its_own_fiscal_error(api):
    """
    §3.7 bands the capital estimate above 0.00 and up to 5000000.00 inclusive. Six
    million is a well-typed decimal, so the generic shape check has nothing to say
    and the fiscal code must answer for it.

    Design: Corner/errors/retrofit_plan_cost_above_the_statutory_ceiling_is_its_own_fiscal_error
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    rt448 = X.create_r448a(api)
    system = X.create_system(api, store["id"], rt404["id"])

    def _plan(cost):
        return F.retrofit_plan_payload(
            system["id"],
            X.system_version(api, system["id"]),
            target_refrigerant_type_id=rt448["id"],
            due_on="2026-10-01T00:00:00Z",
            estimated_cost_usd=cost,
        )

    refused = validate_error(
        api.create_retrofit_plan(_plan(6000000.00), COMPLIANCE_MANAGER_HEADERS),
        ERR_PLAN_COST_OUT_OF_RANGE,
        422,
    )
    assert refused["error_id"] != ERR_INVALID_REQUEST, (
        "the payload is well-formed and correctly typed"
    )

    assert _total_count(
        api.list_retrofit_plans(COMPLIANCE_MANAGER_HEADERS, {"system_id": system["id"]})
    ) == 0
    assert X.system_version(api, system["id"]) == system["version"], (
        "a rejected plan does not consume the optimistic-concurrency token"
    )

    at_the_ceiling = validate_success(
        api.create_retrofit_plan(_plan(5000000.00), COMPLIANCE_MANAGER_HEADERS),
        expected_status=201,
    )
    assert at_the_ceiling["status"] == PLAN_DRAFT
    assert_instant(at_the_ceiling["due_on"], "2026-10-01T00:00:00Z", "due_on")

    validate_error(
        api.create_retrofit_plan(_plan(0.00), COMPLIANCE_MANAGER_HEADERS),
        ERR_PLAN_COST_OUT_OF_RANGE,
        422,
    )
