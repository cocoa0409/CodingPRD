"""
The role model at its edges: exclusive operations refused across every boundary,
shared operations honoured for every permitted role, authentication kept distinct
from authorization, both segregation-of-duties axes, and store scoping.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SEGREGATION_OF_DUTIES_INSPECTION,
    ERR_SEGREGATION_OF_DUTIES_VERIFICATION,
    ERR_STORE_SCOPE_VIOLATION,
    ERR_TECHNICIAN_IDENTITY_MISMATCH,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_array_envelope,
    assert_instant,
    assert_instant_is_none,
    assert_leak_event_schedule,
    assert_penalty_exposure,
    assert_store_posture,
    assert_system_axes,
    assert_system_charge,
)
from test_helpers.test_users import (
    COMPLIANCE_MANAGER_HEADERS,
    MISSING_ROLE_HEADERS,
    MISSING_USER_ID_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REGULATOR_2_HEADERS,
    REGULATOR_2_USER_ID,
    REGULATOR_HEADERS,
    REGULATOR_USER_ID,
    UNDECLARED_ROLE_HEADERS,
    make_store_manager_headers,
    make_technician_headers,
)
from test_helpers.types import (
    ATTEMPT_AWAITING_VERIFICATION,
    ATTEMPT_VERIFIED,
    DETECTION_AUTOMATED_MONITORING,
    DETECTION_MANUAL_INSPECTION,
    EVENT_FOLLOWUP_PENDING,
    EVENT_OPEN,
    EVENT_VERIFICATION_PENDING,
    EVENT_VERIFIED_CLOSED,
    INSPECTION_CLOSED,
    INSPECTION_OPEN,
    INSPECTION_RESPONDED,
    POSTURE_AT_RISK,
    POSTURE_COMPLIANT,
    RESULT_PASS,
    SEQUENCE_FOLLOWUP,
    SEQUENCE_INITIAL,
    STATE_COMPLIANT,
    TECHNICIAN_ACTIVE,
    TECHNICIAN_SUSPENDED,
)


def _total_count(response) -> int:
    """The `meta.total_count` of a listing, envelope checked on the way past."""
    return assert_array_envelope(response)["meta"]["total_count"]


def test_roles_cannot_reach_each_others_exclusive_operations(api):
    """
    §2.1 runs authorization before every other check, so five otherwise valid
    bodies are refused on the role header alone — including a Regulator body that
    a Technician could have filed verbatim and an empty sweep body.

    Design: Corner/rbac/roles_cannot_reach_each_others_exclusive_operations
    """
    env = X.base_env(api)
    version = X.system_version(api, env["system_id"])

    validate_error(
        api.create_system(
            F.system_payload(
                env["store_id"],
                env["rt404_id"],
                full_charge_lbs=80.0,
                initial_charge_lbs=0.0,
                installed_on="2025-06-01T00:00:00Z",
            ),
            make_technician_headers(env["tech2_id"]),
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    on_records = validate_error(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech2_id"],
                env["eq1_id"],
                version,
                cylinder_id=env["cyl1_id"],
                refrigerant_added_lbs=10.0,
                duration_minutes=60,
            ),
            REGULATOR_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    assert on_records["error_id"] != ERR_TECHNICIAN_IDENTITY_MISMATCH, (
        "the role gate runs ahead of the technician identity gate"
    )
    validate_error(
        api.create_inspection(
            F.inspection_payload(env["store_id"], citations=[], inspector_name="Inspector Vale"),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.change_technician_status(
            env["tech2_id"],
            F.technician_status_change_payload(TECHNICIAN_SUSPENDED, "CERT_UNDER_REVIEW"),
            REGULATOR_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    on_runs = validate_error(
        api.run_compliance_sweep(F.compliance_run_payload(), COMPLIANCE_MANAGER_HEADERS),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    assert on_runs["error_id"] != ERR_INVALID_REQUEST, (
        "the role gate also runs ahead of request-shape validation"
    )

    assert _total_count(api.list_systems(COMPLIANCE_MANAGER_HEADERS)) == 1
    assert _total_count(api.list_service_records(COMPLIANCE_MANAGER_HEADERS)) == 0
    assert _total_count(api.list_inspections(COMPLIANCE_MANAGER_HEADERS)) == 0
    assert X.get_technician(api, env["tech2_id"])["status"] == TECHNICIAN_ACTIVE

    system = X.get_system(api, env["system_id"])
    assert system["version"] == version
    assert_system_charge(system, current_charge_lbs=80.0)


def test_shared_writes_and_reads_are_open_to_every_permitted_role(api):
    """
    The positive half of §4: one system read is served identically to all five
    roles, store registration is honoured for two roles and manual leak-event
    declaration for two others, so no shared operation has been narrowed.

    Design: Corner/rbac/shared_writes_and_reads_are_open_to_every_permitted_role
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store_a = validate_success(
        api.create_store(F.store_payload(), PLATFORM_ADMIN_HEADERS), expected_status=201
    )
    store_b = validate_success(
        api.create_store(F.second_store_payload(), COMPLIANCE_MANAGER_HEADERS),
        expected_status=201,
    )
    rt404 = X.create_r404a(api)
    system_a = X.create_system(
        api, store_a["id"], rt404["id"], full_charge_lbs=60.0, initial_charge_lbs=0.0
    )
    system_b = X.create_system(
        api, store_a["id"], rt404["id"], full_charge_lbs=60.0, initial_charge_lbs=0.0
    )
    technician = X.create_technician(api)

    reads = [
        validate_success(api.get_system(system_a["id"], headers))
        for headers in (
            PLATFORM_ADMIN_HEADERS,
            COMPLIANCE_MANAGER_HEADERS,
            make_technician_headers(technician["id"]),
            make_store_manager_headers(store_a["id"]),
            REGULATOR_HEADERS,
        )
    ]
    assert all(read == reads[0] for read in reads), (
        "no role may receive a redacted or narrowed system body"
    )
    assert reads[0]["id"] == system_a["id"]

    event_a = validate_success(
        api.create_leak_event(
            F.leak_event_payload(
                system_a["id"], detection_method=DETECTION_AUTOMATED_MONITORING
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    event_b = validate_success(
        api.create_leak_event(
            F.leak_event_payload(system_b["id"], detection_method=DETECTION_MANUAL_INSPECTION),
            REGULATOR_HEADERS,
        ),
        expected_status=201,
    )
    for event, method in (
        (event_a, DETECTION_AUTOMATED_MONITORING),
        (event_b, DETECTION_MANUAL_INSPECTION),
    ):
        assert event["status"] == EVENT_OPEN
        assert event["detection_method"] == method
        assert_leak_event_schedule(event, repair_deadline="2026-08-31T00:00:00Z")

    assert _total_count(api.list_leak_events(COMPLIANCE_MANAGER_HEADERS)) == 2
    assert_store_posture(
        X.get_store(api, store_a["id"]),
        compliance_status=POSTURE_AT_RISK,
        open_leak_event_count=2,
    )

    validate_error(
        api.get_store(store_b["id"], make_store_manager_headers(store_a["id"])),
        ERR_STORE_SCOPE_VIOLATION,
        403,
    )


def test_a_missing_or_undeclared_role_header_is_an_authentication_failure(api):
    """
    §2.1 makes authentication a distinct, earlier failure than authorization: no
    role, an undeclared role and a missing user id all answer 401 — never 403, and
    never a 404 even though the addressed system exists.

    Design: Corner/rbac/request_with_missing_or_undeclared_role_header_is_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    system = X.create_system(
        api, store["id"], rt404["id"], full_charge_lbs=60.0, initial_charge_lbs=0.0
    )

    for headers in (MISSING_ROLE_HEADERS, UNDECLARED_ROLE_HEADERS):
        refused = api.get_system(system["id"], headers)
        assert refused.status_code == 401, (
            f"expected 401, got {refused.status_code} for headers {sorted(headers)}"
        )
        body = validate_error(refused, ERR_UNAUTHENTICATED, 401)
        assert body["error_id"] != ERR_FORBIDDEN_ROLE

    validate_error(
        api.create_store(
            F.store_payload(name="Eastgate Market", store_code="EG-003"),
            MISSING_USER_ID_HEADERS,
        ),
        ERR_UNAUTHENTICATED,
        401,
    )

    assert _total_count(api.list_stores(COMPLIANCE_MANAGER_HEADERS)) == 1


def test_a_technician_cannot_verify_the_repair_they_performed(api):
    """
    §3.5 keys segregation of duties on the technician entity rather than the role:
    Dana is a certified Technician acting under her own id, and her only defect is
    authorship of the attempt under test. Marek's identical body is accepted.

    Design: Corner/rbac/technician_cannot_verify_the_repair_they_performed
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    system = X.create_system(
        api, store["id"], rt404["id"], full_charge_lbs=60.0, initial_charge_lbs=0.0
    )
    dana = X.create_technician(api)
    marek = X.create_second_technician(api, full_name="Marek Olsen")
    equipment = X.create_equipment(api, store["id"], dana["id"])
    event = X.declare_leak_event(api, system["id"], detected_at="2026-08-01T00:00:00Z")

    X.set_clock(api, "2026-08-10T00:00:00Z")
    attempt = X.file_repair_attempt(
        api, event["id"], system["id"], dana["id"], equipment["id"], "2026-08-05T00:00:00Z"
    )

    pending = X.get_leak_event(api, event["id"])
    assert pending["status"] == EVENT_VERIFICATION_PENDING
    assert pending["repair_attempt_count"] == 1
    assert_leak_event_schedule(pending, verification_deadline="2026-08-15T00:00:00Z")

    def _test_body(technician_id):
        return F.verification_test_payload(
            event["id"],
            attempt["id"],
            technician_id,
            "2026-08-08T00:00:00Z",
            result=RESULT_PASS,
            measured_leak_rate_pct=0.0,
        )

    refused = validate_error(
        api.create_verification_test(
            _test_body(dana["id"]), make_technician_headers(dana["id"])
        ),
        ERR_SEGREGATION_OF_DUTIES_VERIFICATION,
        422,
    )
    assert refused["error_id"] not in (ERR_FORBIDDEN_ROLE, ERR_TECHNICIAN_IDENTITY_MISMATCH)

    assert X.get_leak_event(api, event["id"])["status"] == EVENT_VERIFICATION_PENDING
    assert (
        X.get_repair_attempt(api, attempt["id"])["outcome"] == ATTEMPT_AWAITING_VERIFICATION
    )

    initial = validate_success(
        api.create_verification_test(
            _test_body(marek["id"]), make_technician_headers(marek["id"])
        ),
        expected_status=201,
    )
    assert initial["test_sequence"] == SEQUENCE_INITIAL
    assert X.get_repair_attempt(api, attempt["id"])["outcome"] == ATTEMPT_VERIFIED

    after_initial = X.get_leak_event(api, event["id"])
    assert after_initial["status"] == EVENT_FOLLOWUP_PENDING
    assert_leak_event_schedule(after_initial, verification_deadline="2026-08-18T00:00:00Z")

    followup = X.file_verification_test(
        api,
        event["id"],
        attempt["id"],
        marek["id"],
        "2026-08-09T00:00:00Z",
        result=RESULT_PASS,
        measured_leak_rate_pct=0.0,
    )
    assert followup["test_sequence"] == SEQUENCE_FOLLOWUP

    closed = X.get_leak_event(api, event["id"])
    assert closed["status"] == EVENT_VERIFIED_CLOSED
    assert_instant(closed["closed_at"], "2026-08-10T00:00:00Z", "closed_at")
    assert_system_axes(X.get_system(api, system["id"]), compliance_state=STATE_COMPLIANT)
    assert_store_posture(
        X.get_store(api, store["id"]),
        compliance_status=POSTURE_COMPLIANT,
        open_leak_event_count=0,
    )


def test_a_regulator_cannot_close_the_inspection_they_opened(api):
    """
    §3.9's second segregation axis discriminates inside one role by `X-User-ID`:
    closure is Regulator-exclusive, so regulator-1 is barred only as the recorded
    opener, and regulator-2's identical body closes the matter.

    Design: Corner/rbac/regulator_cannot_close_the_inspection_they_opened
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    inspection = X.open_inspection(
        api,
        store["id"],
        citations=[F.citation("608-LEAK-REC")],
        inspector_name="Inspector Vale",
    )
    validate_success(
        api.respond_to_inspection(
            inspection["id"],
            F.inspection_response_payload(
                response_summary="Records reconciled and refiled.",
                corrective_action_code="RECORDS_CORRECTED",
            ),
            make_store_manager_headers(store["id"]),
        )
    )

    before = X.get_inspection(api, inspection["id"])
    assert before["opened_by_user_id"] == REGULATOR_USER_ID
    assert before["status"] == INSPECTION_RESPONDED

    refused = validate_error(
        api.close_inspection(
            inspection["id"],
            F.inspection_closure_payload(closure_note="Closing my own inspection."),
            REGULATOR_HEADERS,
        ),
        ERR_SEGREGATION_OF_DUTIES_INSPECTION,
        422,
    )
    assert refused["error_id"] not in (ERR_FORBIDDEN_ROLE, ERR_INVALID_STATE_TRANSITION)

    still_open = X.get_inspection(api, inspection["id"])
    assert still_open["status"] == INSPECTION_RESPONDED
    assert_instant_is_none(still_open["closed_at"], "closed_at")
    assert_store_posture(
        X.get_store(api, store["id"]), penalty_exposure_total_usd=275.55
    )

    closed = validate_success(
        api.close_inspection(
            inspection["id"],
            F.inspection_closure_payload(
                closure_note="Corrective action accepted by a second inspector."
            ),
            REGULATOR_2_HEADERS,
        )
    )
    assert closed["status"] == INSPECTION_CLOSED
    assert closed["closed_by_user_id"] == REGULATOR_2_USER_ID
    assert_instant(closed["closed_at"], "2026-08-01T00:00:00Z", "closed_at")

    assert_store_posture(X.get_store(api, store["id"]), penalty_exposure_total_usd=0.00)
    assert_penalty_exposure(
        X.get_inspection(api, inspection["id"]), penalty_exposure_usd=275.55
    )


def test_a_store_manager_cannot_reach_another_stores_resources(api):
    """
    §2.1 scopes a StoreManager per resource rather than per endpoint: the store
    read, the system read and the inspection response are each refused for the
    neighbouring store, while the same reads succeed for their own store.

    Design: Corner/rbac/store_manager_cannot_reach_another_stores_resources
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store_a = X.create_store(api)
    store_b = X.create_second_store(api)
    rt404 = X.create_r404a(api)
    system_b = X.create_system(
        api, store_b["id"], rt404["id"], full_charge_lbs=60.0, initial_charge_lbs=0.0
    )
    inspection_b = X.open_inspection(
        api,
        store_b["id"],
        citations=[F.citation("608-LEAK-REC")],
        inspector_name="Inspector Vale",
    )
    manager_of_a = make_store_manager_headers(store_a["id"])

    for response in (
        api.get_store(store_b["id"], manager_of_a),
        api.get_system(system_b["id"], manager_of_a),
        api.respond_to_inspection(
            inspection_b["id"],
            F.inspection_response_payload(
                response_summary="Not my store, but responding anyway.",
                corrective_action_code="RECORDS_CORRECTED",
            ),
            manager_of_a,
        ),
    ):
        assert response.status_code == 403, (
            f"a cross-store reach must be 403, not {response.status_code}"
        )
        validate_error(response, ERR_STORE_SCOPE_VIOLATION, 403)

    untouched = X.get_inspection(api, inspection_b["id"])
    assert untouched["status"] == INSPECTION_OPEN
    assert_instant_is_none(untouched["responded_at"], "responded_at")

    own = validate_success(api.get_store(store_a["id"], manager_of_a))
    assert own["id"] == store_a["id"]
    neighbour = validate_success(api.get_store(store_b["id"], COMPLIANCE_MANAGER_HEADERS))
    assert neighbour["id"] == store_b["id"]
