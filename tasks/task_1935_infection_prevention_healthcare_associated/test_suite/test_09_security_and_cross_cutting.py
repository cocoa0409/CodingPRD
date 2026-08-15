"""Auth headers, role authorization, segregation of duties, uniqueness
constraints, optimistic concurrency, and reverse-FK list filters
(PRD §2.1, §2.5, §2.8, §3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_cap,
    create_audit,
    create_cap,
    create_case_under_review,
    create_device_day_count,
    create_employee,
    create_exposure,
    create_facility,
    create_facility_payload,
    create_isolation_order,
    create_manual_investigation,
    create_monthly_summary,
    create_patient,
    create_unit,
    director_headers,
    get_device_day_count,
    setup_facility_unit,
    setup_unit_with_patient,
    setup_unit_with_patient_and_episode,
    start_isolation_order,
    submit_cap_for_verification,
    submit_summary,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_auth_header_rejected_before_any_business_logic(api):
    """PRD §2.1: "Every request to the API must carry two HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
    capacity in which they act. A request in which either header is missing or
    empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
    PRD §2.5: "**Presence of identity headers.** Missing or empty `X-User-ID` or
    `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)
    before anything else is examined."

    Design: Corner/validations/missing_auth_header_rejected_before_any_business_logic
    """
    payload = create_facility_payload()
    resp_none = api.create_facility(payload, {})
    validate_error(resp_none, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert resp_none.status_code == 400

    resp_role_only = api.create_facility(payload, {"X-User-Role": "PlatformAdmin"})
    validate_error(
        resp_role_only, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    )


def test_rbac_wrong_role_denied_on_exclusive_operations(
    api, admin_headers, ip_headers, director_headers, nurse_manager_headers,
    health_nurse_headers
):
    """PRD §2.1: "A request whose role is not on the endpoint's authorized list
    is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.5: "**Role authorization.** A role not on the endpoint's authorized
    list yields `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: the endpoint table assigns each operation its authorized role(s),
    e.g. "POST `/api/infection-cases` | Open a suspected HAI case |
    InfectionPreventionist" and "POST `/api/_clock/set_current_utc` | Set the
    server logical clock | PlatformAdmin".

    Design: Corner/roles/rbac_wrong_role_denied_on_exclusive_operations
    """
    ctx = setup_unit_with_patient_and_episode()
    case = create_case_under_review(
        ctx["patient"]["id"], linked_device_episode_id=ctx["episode"]["id"]
    )
    summary = create_monthly_summary(ctx["unit"]["id"], "2026-08")

    resp1 = api.begin_review(case["id"], nurse_manager_headers)
    validate_error(resp1, ApiErrorId.ERR_FORBIDDEN_ROLE)

    resp2 = api.create_infection_case(
        {
            "patient_id": ctx["patient"]["id"],
            "case_type": "OTHER_BSI",
            "suspected_organism": "E. coli",
            "first_positive_specimen_at": "2026-08-05T10:00:00Z",
        },
        director_headers,
    )
    validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_ROLE)

    resp3 = api.create_device_day_count(
        {
            "unit_id": ctx["unit"]["id"],
            "count_date": "2026-08-06T00:00:00Z",
            "central_line_days": 5,
            "urinary_catheter_days": 5,
            "ventilator_days": 5,
            "patient_days": 40,
        },
        ip_headers,
    )
    validate_error(resp3, ApiErrorId.ERR_FORBIDDEN_ROLE)

    resp4 = api.accept_summary(summary["id"], ip_headers)
    validate_error(resp4, ApiErrorId.ERR_FORBIDDEN_ROLE)

    resp5 = api.create_employee_exposure(
        {
            "employee_id": NON_EXISTENT_UUID,
            "exposure_type": "SKIN",
            "occurred_at": "2026-08-01T10:00:00Z",
            "source_hbv_status": "UNKNOWN",
            "source_hcv_status": "UNKNOWN",
            "source_hiv_status": "UNKNOWN",
        },
        nurse_manager_headers,
    )
    validate_error(resp5, ApiErrorId.ERR_FORBIDDEN_ROLE)

    resp6 = api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, ip_headers)
    validate_error(resp6, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_segregation_of_duty_on_summary_accept_and_cap_verify(api):
    """PRD §2.5: "**Segregation of duties.** Acceptance of a summary by the user
    who submitted it, or verification of a corrective action plan by the user
    who created it, is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403)."
    PRD §3.7: "Acceptance requires `SUBMITTED` status
    (`ERR_SUMMARY_NOT_REVIEWABLE`) and enforces segregation of duties: the
    accepting user's `X-User-ID` must differ from `submitted_by_user_id`,
    otherwise `ERR_SEGREGATION_OF_DUTY`."
    PRD §3.12: "Segregation of duties applies: the verifying user's `X-User-ID`
    must differ from `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTY` —
    with the deliberate consequence that system-created plans, whose
    `created_by_user_id` is the literal `system`, are verifiable by any
    director."

    Design: Corner/roles/segregation_of_duty_on_summary_accept_and_cap_verify
    """
    facility, unit = setup_facility_unit()
    summary = create_monthly_summary(unit["id"], "2026-08")
    submit_summary(summary["id"], user_id="ip-user-1")

    cap = create_cap(
        unit["id"], "SIR_HIGH", summary["id"], user_id="ip-user-1",
        description="sustained high SIR review", due_date="2026-08-25T00:00:00Z",
    )
    activate_cap(cap["id"], user_id="ip-user-1")
    submit_cap_for_verification(
        cap["id"], user_id="ip-user-1",
        evidence_notes="line-rounding audit evidence",
    )

    # Same human id, even wearing the reviewer role, may not accept/verify.
    resp_accept = api.accept_summary(
        summary["id"], director_headers("ip-user-1")
    )
    validate_error(resp_accept, ApiErrorId.ERR_SEGREGATION_OF_DUTY)
    assert resp_accept.status_code == 403

    resp_verify = api.verify_cap(cap["id"], director_headers("ip-user-1"))
    validate_error(resp_verify, ApiErrorId.ERR_SEGREGATION_OF_DUTY)
    assert resp_verify.status_code == 403

    accepted = validate_success(
        api.accept_summary(summary["id"], director_headers("dir-user-2"))
    )
    assert accepted["status"] == "ACCEPTED"

    verified = validate_success(api.verify_cap(cap["id"], director_headers("dir-user-2")))
    assert verified["status"] == "VERIFIED"


def test_constraint_family_duplicates_and_row_rules(
    api, admin_headers, ip_headers, nurse_manager_headers
):
    """PRD §3.6: "Only one row may exist per unit and calendar date — a
    duplicate yields `ERR_DUPLICATE_DEVICE_DAY_COUNT`."
    PRD §3.6: "Each of the three device-day figures must be no greater than
    `patient_days`; a violation is rejected with
    `ERR_DEVICE_DAYS_EXCEED_PATIENT_DAYS`."
    PRD §3.7: "One summary may exist per unit and month; a duplicate is
    `ERR_DUPLICATE_SUMMARY_MONTH`."
    PRD §3.1: "its `nhsn_org_id` (the NHSN organization identifier, unique
    across all facilities — a duplicate is rejected with
    `ERR_DUPLICATE_NHSN_ORG_ID`)"
    PRD §3.2: "A `UnitNurseManager` registers an inpatient admission by
    supplying the patient's `mrn` — a medical record number unique across the
    hospital, with duplicates rejected as `ERR_DUPLICATE_MRN` — the
    `admitted_at` timestamp, and the `unit_id` of the initial inpatient unit."
    PRD §3.9: "At most one order per patient and precaution type may be open at
    a time, where open means `ORDERED` or `ACTIVE`; a conflicting second order
    is rejected with `ERR_DUPLICATE_ISOLATION_ORDER`."
    PRD §3.8: "A duplicate open investigation — same unit, same organism under
    case-insensitive comparison, existing status `TRIGGERED` or `CONFIRMED` — is
    rejected with `ERR_DUPLICATE_OUTBREAK_OPEN`."

    Design: Corner/validations/constraint_family_duplicates_and_row_rules
    """
    facility = create_facility(nhsn_org_id="ORG-1")
    unit = create_unit(facility["id"], name="ICU-V4")
    create_device_day_count(unit["id"], "2026-08-01T00:00:00Z")
    create_monthly_summary(unit["id"], "2026-08")
    patient = create_patient(unit["id"], mrn="MRN-DUP")
    create_isolation_order(patient["id"], precaution_type="CONTACT")
    create_manual_investigation(unit["id"], "VRE")

    resp1 = api.create_device_day_count(
        {
            "unit_id": unit["id"],
            "count_date": "2026-08-01T00:00:00Z",
            "central_line_days": 21,
            "urinary_catheter_days": 10,
            "ventilator_days": 5,
            "patient_days": 40,
        },
        nurse_manager_headers,
    )
    validate_error(resp1, ApiErrorId.ERR_DUPLICATE_DEVICE_DAY_COUNT)

    resp2 = api.create_device_day_count(
        {
            "unit_id": unit["id"],
            "count_date": "2026-08-02T00:00:00Z",
            "central_line_days": 45,
            "urinary_catheter_days": 10,
            "ventilator_days": 5,
            "patient_days": 40,
        },
        nurse_manager_headers,
    )
    validate_error(resp2, ApiErrorId.ERR_DEVICE_DAYS_EXCEED_PATIENT_DAYS)
    assert resp2.status_code == 422

    resp3 = api.create_monthly_summary(
        {"unit_id": unit["id"], "month": "2026-08"}, ip_headers
    )
    validate_error(resp3, ApiErrorId.ERR_DUPLICATE_SUMMARY_MONTH)

    resp4 = api.create_facility(
        create_facility_payload(nhsn_org_id="ORG-1"), admin_headers
    )
    validate_error(resp4, ApiErrorId.ERR_DUPLICATE_NHSN_ORG_ID)

    resp5 = api.create_patient(
        {"mrn": "MRN-DUP", "admitted_at": "2026-08-02T08:00:00Z",
         "unit_id": unit["id"]},
        nurse_manager_headers,
    )
    validate_error(resp5, ApiErrorId.ERR_DUPLICATE_MRN)

    resp6 = api.create_isolation_order(
        {"patient_id": patient["id"], "precaution_type": "CONTACT"}, ip_headers
    )
    validate_error(resp6, ApiErrorId.ERR_DUPLICATE_ISOLATION_ORDER)

    resp7 = api.create_outbreak_investigation(
        {"unit_id": unit["id"], "organism": "vre"}, ip_headers
    )
    validate_error(resp7, ApiErrorId.ERR_DUPLICATE_OUTBREAK_OPEN)


def test_occ_stale_version_device_day_count_and_facility(
    api, admin_headers, nurse_manager_headers
):
    """PRD §2.8: "Correcting a device-day denominator row requires the request
    to carry `expected_device_day_count_version`, holding the `version` of the
    `DeviceDayCount` row as the client last observed it."
    PRD §2.8: "If the supplied value does not match the row's current `version`,
    the correction is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.8: "Updating a facility's configuration requires the request to carry
    `expected_facility_version`, holding the `version` of the `Facility` as the
    client last observed it."
    PRD §2.8: "A mismatch against the facility's current `version` is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_version_device_day_count_and_facility
    """
    facility, unit = setup_facility_unit()
    fac_v1 = facility["version"]
    row = create_device_day_count(unit["id"], "2026-08-01T00:00:00Z")
    row_v1 = row["version"]

    ok_row = validate_success(
        api.update_device_day_count(
            row["id"],
            {"central_line_days": 22, "urinary_catheter_days": 10,
             "ventilator_days": 5, "patient_days": 40,
             "expected_device_day_count_version": row_v1},
            nurse_manager_headers,
        )
    )
    assert ok_row["version"] == row_v1 + 1

    resp_stale_row = api.update_device_day_count(
        row["id"],
        {"central_line_days": 23, "urinary_catheter_days": 10,
         "ventilator_days": 5, "patient_days": 40,
         "expected_device_day_count_version": row_v1},
        nurse_manager_headers,
    )
    validate_error(resp_stale_row, ApiErrorId.ERR_STALE_VERSION)
    assert resp_stale_row.status_code == 412
    assert get_device_day_count(row["id"])["central_line_days"] == 22, (
        "a stale correction must not overwrite the row"
    )

    ok_fac = validate_success(
        api.update_facility(
            facility["id"],
            {"sir_high_threshold": 1.5, "expected_facility_version": fac_v1},
            admin_headers,
        )
    )
    assert ok_fac["version"] == fac_v1 + 1

    resp_stale_fac = api.update_facility(
        facility["id"],
        {"sir_high_threshold": 2.0, "expected_facility_version": fac_v1},
        admin_headers,
    )
    validate_error(resp_stale_fac, ApiErrorId.ERR_STALE_VERSION)
    assert resp_stale_fac.status_code == 412

    ok_fac2 = validate_success(
        api.update_facility(
            facility["id"],
            {"sir_high_threshold": 2.0,
             "expected_facility_version": ok_fac["version"]},
            admin_headers,
        )
    )
    assert ok_fac2["version"] == ok_fac["version"] + 1
    assert ok_fac2["sir_high_threshold"] == 2.0


def test_fk_reverse_reachability_filtered_lists(
    api, nurse_manager_headers, health_nurse_headers
):
    """PRD §3.9: "Audits may be listed with an `isolation_order_id` filter."
    PRD §3.11: "Exposures may be listed with `employee_id`, `status`, or
    `source_patient_id` filters."

    Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
    """
    ctx = setup_unit_with_patient(unit_type="OR")
    patient_2 = create_patient(ctx["unit"]["id"])
    order = create_isolation_order(patient_2["id"], precaution_type="CONTACT")
    start_isolation_order(order["id"])
    audit = create_audit(
        order["id"], observed_at="2026-08-03T09:00:00Z",
        elements_checked=10, elements_passed=10,
    )
    employee = create_employee(ctx["unit"]["id"])
    exposure = create_exposure(
        employee["id"], source_patient_id=ctx["patient"]["id"],
        occurred_at="2026-08-04T10:00:00Z",
    )

    audits, audits_meta = validate_paginated(
        api.list_isolation_audits(
            nurse_manager_headers, params={"isolation_order_id": order["id"]}
        )
    )
    assert audits_meta["total_count"] == 1
    assert audits[0]["id"] == audit["id"]

    by_employee, emp_meta = validate_paginated(
        api.list_employee_exposures(
            health_nurse_headers, params={"employee_id": employee["id"]}
        )
    )
    assert emp_meta["total_count"] == 1
    assert by_employee[0]["id"] == exposure["id"]

    by_source, src_meta = validate_paginated(
        api.list_employee_exposures(
            health_nurse_headers, params={"source_patient_id": ctx["patient"]["id"]}
        )
    )
    assert src_meta["total_count"] == 1
    assert by_source[0]["id"] == exposure["id"]
