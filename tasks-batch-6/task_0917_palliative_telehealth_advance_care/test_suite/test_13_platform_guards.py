"""Platform guards: stale-version guards, the logical clock and access control."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, assert_same_instant, headers_without_role
from test_helpers import factories as f
from test_helpers.fixtures import (
    ADMIN,
    CHAPLAIN,
    HOSPICE_DIRECTOR,
    INTAKE,
    NURSE,
    PHYSICIAN,
    SOCIAL_WORKER,
    active_care_plan,
    attested_idt_conference,
    certified_hospice_election,
    enroll_patient,
    open_benefit_period,
    patient_version,
    read_care_plan,
    read_election,
    set_clock,
    witnessed_document,
)


# ---------------------------------------------------------------------------
# The three stale-version guards
# ---------------------------------------------------------------------------
def test_a_second_execution_carrying_the_pre_write_patient_version_is_rejected(api):
    """PRD 2.7: "`POST /palliative/advance-care-documents/{id}/execute` requires
    `expected_patient_version`, carrying the `version` of the patient the document
    belongs to as the client last read it. If it does not equal the patient's
    current `version`, the execution is rejected with `ERR_STALE_PATIENT_VERSION`
    (HTTP 412)."
    PRD 3.3: "Executing stamps `executed_at` from the logical clock, sets
    `reattest_due_at` to exactly 365 days after `executed_at`, moves the document
    `PENDING_EXECUTION → EXECUTED`, and increments the patient's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_patient_version_rejects_the_second_document_execution
    """
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z",
        full_name="Yara Cohen",
        jurisdiction_code="JUR_TWO_WITNESS",
    )
    first = witnessed_document(
        patient["id"], witnesses=2, document_type="LIVING_WILL", stated_code_status="DNR"
    )
    second = witnessed_document(
        patient["id"],
        witnesses=2,
        document_type="LIVING_WILL",
        stated_code_status="DNR_DNI",
        supersedes_document_id=first["id"],
    )
    version_before = patient_version(patient["id"])

    validate_success(
        api.execute_document(
            first["id"], {"expected_patient_version": version_before}, PHYSICIAN
        )
    )

    stale = api.execute_document(
        second["id"], {"expected_patient_version": version_before}, PHYSICIAN
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PATIENT_VERSION.value, 412)

    retried = validate_success(
        api.execute_document(
            second["id"],
            {"expected_patient_version": patient_version(patient["id"])},
            PHYSICIAN,
        )
    )
    assert retried["status"] == "EXECUTED"

    superseded = validate_success(api.get_document(first["id"], SOCIAL_WORKER))
    assert superseded["status"] == "SUPERSEDED"


def test_a_second_revision_carrying_the_pre_revision_plan_version_is_rejected(api):
    """PRD 2.7: "`POST /palliative/care-plans/{id}/revisions` requires
    `expected_care_plan_version`, carrying the plan's `version` as the client last
    read it. A mismatch with the plan's current `version` is rejected with
    `ERR_STALE_CARE_PLAN_VERSION` (HTTP 412). The guard exists because a revision
    replaces `problem_list` wholesale; a client working from a stale plan would
    silently discard problems added by an earlier accepted revision."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_care_plan_version_rejects_the_second_revision
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Zeb Karlsen")
    plan = active_care_plan(patient["id"], plan_title="Plan", problem_list=["pain"])
    version_before = plan["version"]

    validate_success(
        api.revise_care_plan(
            plan["id"],
            {
                "expected_care_plan_version": version_before,
                "revised_problem_list": ["pain", "dyspnea"],
            },
            NURSE,
        )
    )
    validate_success(api.activate_care_plan(plan["id"], {}, NURSE))

    stale = api.revise_care_plan(
        plan["id"],
        {"expected_care_plan_version": version_before, "revised_problem_list": ["nausea"]},
        NURSE,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_CARE_PLAN_VERSION.value, 412)

    final = read_care_plan(plan["id"])
    assert final["status"] == "ACTIVE"
    assert final["revision_number"] == 1
    assert final["problem_list"] == ["pain", "dyspnea"], (
        "the rejected revision must not have replaced the accepted problem list"
    )


def test_a_second_benefit_period_carrying_the_pre_period_election_version_is_rejected(api):
    """PRD 2.7: "`POST /palliative/hospice-elections/{id}/periods` requires
    `expected_election_version`, carrying the election's `version` as the client
    last read it. A mismatch with the election's current `version` is rejected
    with `ERR_STALE_ELECTION_VERSION` (HTTP 412). The guard exists because each
    accepted period advances `current_period_number` and the benefit-period
    arithmetic; a client holding a stale election would compute the wrong period
    length and the wrong face-to-face requirement."
    PRD 2.7: "All three checks sit at rung 8 of the ladder, so a frozen patient, a
    bad state or a missing row is reported before the version is even compared."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_election_version_rejects_the_second_benefit_period
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Ada Villanueva")
    attested_idt_conference(patient["id"], held_at="2026-06-02T09:00:00Z")
    election = certified_hospice_election(patient["id"], diagnosis="G30.9")
    version_before = election["version"]

    open_benefit_period(election["id"], "2026-06-02T00:00:00Z", version_before)

    stale = api.open_hospice_period(
        election["id"],
        {
            "expected_election_version": version_before,
            "period_start": "2026-08-31T00:00:00Z",
        },
        HOSPICE_DIRECTOR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ELECTION_VERSION.value, 412)

    retried = open_benefit_period(
        election["id"], "2026-08-31T00:00:00Z", read_election(election["id"])["version"]
    )
    assert retried["current_period_number"] == 2
    assert_same_instant(
        retried["current_period_end"],
        "2026-11-29T00:00:00Z",
        "HospiceElection.current_period_end",
    )
    assert retried["cumulative_benefit_days"] == 180


# ---------------------------------------------------------------------------
# Path existence
# ---------------------------------------------------------------------------
def test_reading_an_unknown_patient_id_is_a_not_found(api):
    """PRD 2.5: "**Path existence.** Every identifier embedded in the request path
    resolves to an existing row, checked left to right. Otherwise
    `ERR_RESOURCE_NOT_FOUND` (404). Applies to every endpoint that has a path
    identifier."
    PRD 2.12: "Path identifiers are always the resource's `id`; no endpoint
    addresses a row by a business key such as `mrn`."

    Design: Corner/entities/patient_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-06-01T00:00:00Z")

    missing = api.get_patient(NON_EXISTENT_UUID, ADMIN)
    validate_error(missing, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)


# ---------------------------------------------------------------------------
# The logical clock's declared starting value
# ---------------------------------------------------------------------------
def test_the_logical_clock_starts_at_its_declared_instant(api):
    """PRD 2.4: "The server does not read the host machine's wall clock. It
    maintains a **logical clock** whose value is exactly `2026-05-01T00:00:00Z`
    until it is moved, and which never falls back to real time under any
    circumstance."
    PRD 2.4: "`created_at` (string): an ISO 8601 UTC timestamp recording when the
    row was created."

    Design: Corner/endpoints/logical_clock_defaults_to_the_declared_startup_instant
    """
    created = validate_success(
        api.create_patient(f.patient_payload(full_name="Ugo Bianchi"), INTAKE), 201
    )

    fetched = validate_success(api.get_patient(created["id"], ADMIN))
    assert_same_instant(
        fetched["created_at"], "2026-05-01T00:00:00Z", "Patient.created_at"
    )
    assert_same_instant(
        fetched["updated_at"], "2026-05-01T00:00:00Z", "Patient.updated_at"
    )
    assert fetched["version"] == 1


# ---------------------------------------------------------------------------
# Authentication and authorisation
# ---------------------------------------------------------------------------
def test_a_request_without_the_role_header_is_unauthenticated(api):
    """PRD 2.1: "Every request to the API — reads included — must carry two
    headers. `X-User-ID` identifies the acting user and `X-User-Role` declares the
    capacity in which that user is acting. A request that omits either header, or
    that supplies an `X-User-Role` which is not one of the ten declared roles, is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/request_with_missing_x_user_role_header_returns_unauthenticated
    """
    patient = validate_success(
        api.create_patient(
            f.patient_payload(full_name="Vik Sandhu"), INTAKE
        ),
        201,
    )

    unauthenticated = api.get_patient(patient["id"], headers_without_role("u_admin_1"))
    validate_error(unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_a_chaplain_may_not_write_a_medication_order(api):
    """PRD 2.1: "A request that carries valid headers but names a role that is not
    authorised for the endpoint being called is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403). The authorised role list for each endpoint is given in section 4."
    PRD 2.1: "A `Chaplain` attends interdisciplinary conferences and attests the
    spiritual-care note."

    Design: Corner/rbac/chaplain_cannot_create_a_medication_order_returns_unauthorized
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Wes Amari")

    unauthorized = api.create_medication_order(
        f.medication_order_payload(
            patient["id"], drug="MORPHINE_PO", dose_amount=30, days_supply=14
        ),
        CHAPLAIN,
    )
    validate_error(unauthorized, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    rows, meta = validate_paginated(
        api.list_patient_medication_orders(patient["id"], PHYSICIAN)
    )
    assert rows == [], f"the refused request must not have persisted an order, got {rows}"
    assert meta["total_count"] == 0
