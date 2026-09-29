"""The rejection ladder of PRD 2.8 and the role and segregation gates above it."""

from test_helpers import (
    ADMIN_HEADERS,
    CLAIM_APPROVED,
    CLAIM_SUBMITTED,
    DECISION_REJECT,
    ELIGIBILITY_ELIGIBLE,
    EMPTY_USER_ID_ADMIN_HEADERS,
    EMPTY_USER_ID_QA_HEADERS,
    ERR_COMBUSTION_SAFETY_REQUIRED,
    ERR_COMFORT_COMPLAINT_NOT_FOUND,
    ERR_DUCT_SYSTEM_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LEAKAGE_TEST_NOT_FOUND,
    ERR_MASKING_INCOMPLETE,
    ERR_PROGRAM_BUDGET_EXCEEDED,
    ERR_PROJECT_NOT_FOUND,
    ERR_PROJECT_SAFETY_HOLD,
    ERR_REBATE_CLAIM_NOT_FOUND,
    ERR_SEAL_JOB_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TECHNICIAN_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_UTILITY_PROGRAM_NOT_FOUND,
    ERR_VERIFICATION_REPORT_NOT_FOUND,
    EXCLUSION_STRUCTURAL_DAMAGE,
    GRADE_C,
    INSPECTOR_HEADERS,
    JOB_SCHEDULED,
    MATERIAL_DUCT_BOARD,
    MATERIAL_FLEX,
    METHOD_PRESSURE_PAN,
    NON_EXISTENT_UUID,
    PROJECT_ACTIVE,
    PROJECT_SAFETY_HOLD,
    QA_HEADERS,
    REPORT_ISSUED,
    ROLE_QA_VERIFIER,
    ROLE_UTILITY_INSPECTOR,
    SCREENING_CLEARED,
    SEAL_STATUS_SEAL_PENDING,
    TEST_ACCEPTED,
    TEST_DRAFT,
    TEST_RECORDED,
    assert_program_ledger,
    factories as f,
    fixtures as fx,
    make_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_state_rung_answers_before_safety_and_completeness_on_start_injection(api):
    """A `SCHEDULED` run reports the state error even with two other rules unmet.

    PRD 2.8 rung 6: "the target resource is in a from-state that permits the requested
    transition, else the resource's invalid-state error (409). This rung is checked
    **before any business rule**, so an action fired from the wrong state reports the
    state error even when a safety, referential, structural or fiscal precondition is
    also unmet."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_start_injection
    """
    sc = fx.scenario_scheduled_job(api, with_combustion=False)
    job = sc.read_seal_job()
    assert job["status"] == JOB_SCHEDULED
    assert job["masked_register_count"] == 0

    validate_error(
        api.start_injection(sc.seal_job_id, None, sc.tech_headers),
        ERR_SEAL_JOB_INVALID_STATE,
        409,
    )

    after = sc.read_seal_job()
    assert after["status"] == JOB_SCHEDULED
    assert after["masked_register_count"] == 0
    assert sc.read_duct_system()["seal_status"] == SEAL_STATUS_SEAL_PENDING


def test_from_masking_the_safety_rung_answers_before_the_completeness_rung(api):
    """Once the state rung is satisfied, safety (8) still precedes completeness (10).

    PRD 2.8 orders rung 8 "**Combustion and project safety** — the four gates
    described in §2.12, all HTTP 422" ahead of rung 10 "**Structural and completeness
    constraints** — certification standing and expiry, masking completeness ... all
    HTTP 422".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_start_injection
    """
    sc = fx.scenario_scheduled_job(api, with_combustion=False)
    total = sc.duct_system["total_register_count"]
    partial = f.register_labels(total)[:-1]
    masked = validate_success(
        api.mask_registers(sc.seal_job_id, f.masks_payload(partial), sc.tech_headers)
    )
    assert masked["masked_register_count"] == total - 1

    # Both the combustion gate (8) and the masking gate (10) are unmet; 8 answers.
    validate_error(
        api.start_injection(sc.seal_job_id, None, sc.tech_headers),
        ERR_COMBUSTION_SAFETY_REQUIRED,
        422,
    )

    fx.add_combustion_test(sc)
    validate_error(
        api.start_injection(sc.seal_job_id, None, sc.tech_headers),
        ERR_MASKING_INCOMPLETE,
        422,
    )


def test_the_project_safety_hold_answers_before_the_programme_budget(api):
    """Safety (8) precedes the fiscal rung (12) on a claim that violates both.

    PRD 2.8 rung 8 is "**Combustion and project safety** ... all HTTP 422" and rung 12
    is "**Fiscal and performance gates** — the guarantee threshold, the program minimum
    reduction, and the remaining program budget, all HTTP 422".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_rebate_claim
    """
    sc = fx.scenario_issued_report(api, program={"annual_budget_cents": 100000})
    held = validate_success(
        api.raise_safety_hold(
            sc.project_id,
            f.safety_hold_payload(
                safety_hold_reason="homeowner reported flue odor after the retrofit"
            ),
            ADMIN_HEADERS,
        )
    )
    assert held["safety_hold"] is True
    assert held["status"] == PROJECT_SAFETY_HOLD

    validate_error(
        api.create_rebate_claim(
            f.rebate_claim_payload(
                sc.report_id, sc.program_id, documentation_bundle_ref="BUNDLE-99"
            ),
            ADMIN_HEADERS,
        ),
        ERR_PROJECT_SAFETY_HOLD,
        422,
    )

    assert_program_ledger(sc.read_program(), 0, 0, 100000)
    _rows, meta = validate_paginated(
        api.list_rebate_claims(ADMIN_HEADERS, verification_report_id=sc.report_id)
    )
    assert meta["total_count"] == 0


def test_releasing_the_hold_reveals_the_fiscal_refusal_underneath_it(api):
    """The same claim, with the safety rung satisfied, now fails on the budget.

    PRD 2.8 rung 12 evaluates the fiscal gates "among themselves in that order:
    `ERR_GUARANTEE_NOT_MET` first (on report issuance), then
    `ERR_REBATE_REDUCTION_BELOW_PROGRAM_MINIMUM`, then `ERR_PROGRAM_BUDGET_EXCEEDED`".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_rebate_claim
    """
    sc = fx.scenario_issued_report(api, program={"annual_budget_cents": 100000})
    validate_success(
        api.raise_safety_hold(sc.project_id, f.safety_hold_payload(), ADMIN_HEADERS)
    )
    validate_error(
        api.create_rebate_claim(
            f.rebate_claim_payload(sc.report_id, sc.program_id), ADMIN_HEADERS
        ),
        ERR_PROJECT_SAFETY_HOLD,
        422,
    )

    released = validate_success(
        api.release_safety_hold(
            sc.project_id, f.release_safety_hold_payload(), ADMIN_HEADERS
        )
    )
    assert released["safety_hold"] is False

    validate_error(
        api.create_rebate_claim(
            f.rebate_claim_payload(sc.report_id, sc.program_id), ADMIN_HEADERS
        ),
        ERR_PROGRAM_BUDGET_EXCEEDED,
        422,
    )
    assert_program_ledger(sc.read_program(), 0, 0, 100000)


def test_an_empty_user_id_is_rejected_before_anything_is_looked_up(api):
    """Authentication (1) outranks existence (4), so an unknown id still answers 401.

    PRD 2.1: "When `X-User-ID` is absent or empty the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401), and this check precedes every other check in the
    system."

    Design: Corner/validations/empty_user_id_header_is_rejected_before_existence_is_even_checked
    """
    validate_error(
        api.list_projects(EMPTY_USER_ID_ADMIN_HEADERS), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.get_project(NON_EXISTENT_UUID, EMPTY_USER_ID_QA_HEADERS),
        ERR_UNAUTHENTICATED,
        401,
    )
    # The same unknown identifier answers 404 once the caller is authenticated.
    validate_error(
        api.get_project(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_PROJECT_NOT_FOUND, 404
    )


def test_the_role_check_answers_before_the_existence_check(api):
    """Authorization (2) hides the 404 that the allowed role then reveals.

    PRD 2.8 rung 2: "the caller's role appears among the endpoint's permitted roles,
    else `ERR_UNAUTHORIZED` (403)", and rung 4: "every identifier in the path and every
    foreign key in the payload resolves to a live row, else the matching not-found error
    (404)."

    Design: Corner/validations/unauthorized_role_beats_not_found_on_an_unknown_duct_system
    """
    fx.set_clock(api, f.utc(2026, 8, 1))
    payload = f.exclude_payload(exclusion_reason=EXCLUSION_STRUCTURAL_DAMAGE)

    validate_error(
        api.exclude_duct_system(NON_EXISTENT_UUID, payload, QA_HEADERS),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.exclude_duct_system(NON_EXISTENT_UUID, payload, ADMIN_HEADERS),
        ERR_DUCT_SYSTEM_NOT_FOUND,
        404,
    )


def test_the_existence_check_answers_before_request_validity(api):
    """An unknown parent in the path outranks a doubly malformed body.

    PRD 2.8 rung 4: "The entity named by the path segment is checked before payload
    foreign keys", and rung 5 gathers "required fields present; enum values drawn from
    the declared sets ... Violations are `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/existence_beats_request_validity_on_an_unknown_parent_project
    """
    sc = fx.scenario_base(api)
    malformed = f.duct_system_payload(
        system_label="GHOST-1",
        total_register_count=4,
        design_cfm=-50.0,
        duct_material="TITANIUM_ALLOY",
    )

    validate_error(
        api.create_duct_system(NON_EXISTENT_UUID, malformed, ADMIN_HEADERS),
        ERR_PROJECT_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_duct_system(sc.project_id, malformed, ADMIN_HEADERS),
        ERR_INVALID_REQUEST,
        400,
    )

    _rows, meta = validate_paginated(
        api.list_duct_systems(sc.project_id, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0
    project = sc.read_project()
    assert project["duct_system_count"] == 0
    assert project["eligible_duct_system_count"] == 0


def test_every_unknown_identifier_reaches_its_own_not_found_code(api):
    """Six of the declared not-found codes, from both the body and the path.

    PRD 2.8 rung 4: "every identifier in the path and every foreign key in the payload
    resolves to a live row, else the matching not-found error (404)."

    Design: Corner/errors/every_unknown_identifier_reaches_its_own_not_found_code
    """
    sc = fx.scenario_with_baseline(api)

    validate_error(
        api.create_project(
            f.project_payload(
                utility_program_id=NON_EXISTENT_UUID, address_line="2 Nowhere Rd"
            ),
            ADMIN_HEADERS,
        ),
        ERR_UTILITY_PROGRAM_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_seal_job(
            f.seal_job_payload(
                sc.duct_system_id,
                sc.pre_test["id"],
                NON_EXISTENT_UUID,
                sc.duct_system_version(),
            ),
            sc.tech_headers,
        ),
        ERR_TECHNICIAN_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_leakage_test(NON_EXISTENT_UUID, QA_HEADERS),
        ERR_LEAKAGE_TEST_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_verification_report(NON_EXISTENT_UUID, QA_HEADERS),
        ERR_VERIFICATION_REPORT_NOT_FOUND,
        404,
    )
    validate_error(
        api.list_airflow_readings(NON_EXISTENT_UUID, sc.tech_headers),
        ERR_COMFORT_COMPLAINT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_rebate_claim(NON_EXISTENT_UUID, ADMIN_HEADERS),
        ERR_REBATE_CLAIM_NOT_FOUND,
        404,
    )

    _projects, project_meta = validate_paginated(api.list_projects(ADMIN_HEADERS))
    assert project_meta["total_count"] == 1
    _jobs, job_meta = validate_paginated(api.list_seal_jobs(ADMIN_HEADERS))
    assert job_meta["total_count"] == 0


def test_shared_operations_accept_either_declared_role(api):
    """Five endpoints, each shared between a different pair, run twice over.

    PRD 4 declares `POST /duct-sealing/projects/{id}/duct-systems` for
    "ProgramAdmin, FieldTechnician", `POST /duct-sealing/duct-systems/{id}/asbestos-screening`
    and `POST /duct-sealing/projects/{id}/safety-hold` for "ProgramAdmin, QAVerifier",
    `POST /duct-sealing/leakage-tests` for "FieldTechnician, QAVerifier", and
    `POST /duct-sealing/_clock/set_current_utc` for all four roles.

    Design: Corner/rbac/shared_operations_accept_either_declared_role
    """
    sc = fx.scenario_base(api)

    by_admin = validate_success(
        api.create_duct_system(
            sc.project_id, f.duct_system_payload(system_label="AHU-1"), ADMIN_HEADERS
        ),
        201,
    )
    by_tech = validate_success(
        api.create_duct_system(
            sc.project_id,
            f.duct_system_payload(
                system_label="AHU-2",
                total_register_count=6,
                design_cfm=800.0,
                duct_material=MATERIAL_FLEX,
                condition_grade=GRADE_C,
            ),
            sc.tech_headers,
        ),
        201,
    )

    screened_by_admin = validate_success(
        api.record_asbestos_screening(
            by_admin["id"],
            f.asbestos_screening_payload(lab_reference="LAB-2001"),
            ADMIN_HEADERS,
        )
    )
    screened_by_qa = validate_success(
        api.record_asbestos_screening(
            by_tech["id"],
            f.asbestos_screening_payload(lab_reference="LAB-2002"),
            QA_HEADERS,
        )
    )
    assert screened_by_admin["asbestos_screening_result"] == SCREENING_CLEARED
    assert screened_by_qa["asbestos_screening_result"] == SCREENING_CLEARED
    assert screened_by_admin["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert screened_by_qa["eligibility_status"] == ELIGIBILITY_ELIGIBLE

    test_by_tech = validate_success(
        api.create_leakage_test(
            f.leakage_test_payload(by_admin["id"]), sc.tech_headers
        ),
        201,
    )
    test_by_qa = validate_success(
        api.create_leakage_test(
            f.leakage_test_payload(by_tech["id"], method=METHOD_PRESSURE_PAN),
            QA_HEADERS,
        ),
        201,
    )
    assert test_by_tech["status"] == TEST_DRAFT
    assert test_by_tech["performed_by_user_id"] is None
    assert test_by_qa["status"] == TEST_DRAFT
    assert test_by_qa["performed_by_user_id"] is None

    held_by_qa = validate_success(
        api.raise_safety_hold(
            sc.project_id,
            f.safety_hold_payload(
                safety_hold_reason="QA smelled gas at the water heater"
            ),
            QA_HEADERS,
        )
    )
    assert held_by_qa["safety_hold"] is True
    assert held_by_qa["safety_hold_reason"] == "QA smelled gas at the water heater"
    assert (
        validate_success(
            api.release_safety_hold(
                sc.project_id, f.release_safety_hold_payload(), ADMIN_HEADERS
            )
        )["safety_hold"]
        is False
    )
    held_by_admin = validate_success(
        api.raise_safety_hold(
            sc.project_id,
            f.safety_hold_payload(
                safety_hold_reason="back office holding for a permit"
            ),
            ADMIN_HEADERS,
        )
    )
    assert held_by_admin["safety_hold_reason"] == "back office holding for a permit"
    released = validate_success(
        api.release_safety_hold(
            sc.project_id, f.release_safety_hold_payload(), ADMIN_HEADERS
        )
    )
    assert released["safety_hold"] is False
    assert released["status"] == PROJECT_ACTIVE

    # The clock is shared with every role, the inspector included.
    validate_success(api.set_clock(f.utc(2026, 8, 1, 6, 0), INSPECTOR_HEADERS))
    later = validate_success(
        api.create_duct_system(
            sc.project_id,
            f.duct_system_payload(
                system_label="AHU-3",
                total_register_count=4,
                design_cfm=500.0,
                duct_material=MATERIAL_DUCT_BOARD,
            ),
            sc.tech_headers,
        ),
        201,
    )
    assert later["created_at"] == f.stamp(2026, 8, 1, 6, 0)

    rows, meta = validate_paginated(
        api.list_duct_systems(sc.project_id, INSPECTOR_HEADERS)
    )
    assert meta["total_count"] == 3
    assert rows[0]["project_id"] == sc.project_id


def test_exclusive_operations_are_refused_to_every_other_role(api):
    """Four role-exclusive writes, each aimed at the wrong role, all answer 403.

    PRD 2.8 rung 2: "the caller's role appears among the endpoint's permitted roles,
    else `ERR_UNAUTHORIZED` (403)" — and it is checked before existence (4) and state
    (6). PRD 4 fixes the exclusivity of each of these endpoints.

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    sc = fx.scenario_scheduled_job(api)
    pre_test_id = sc.pre_test["id"]

    # Review is QAVerifier-exclusive; the 403 precedes the state error an ACCEPTED
    # test would otherwise earn.
    validate_error(
        api.review_leakage_test(
            pre_test_id, f.review_payload(decision=DECISION_REJECT), sc.tech_headers
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.mask_registers(sc.seal_job_id, f.masks_payload(["R1", "R2"]), QA_HEADERS),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_verification_report(
            f.verification_report_payload(
                sc.seal_job_id, pre_test_id, sc.seal_job_version()
            ),
            ADMIN_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_technician(
            f.technician_payload(full_name="Self Promoted", license_number="AS-9999"),
            sc.tech_headers,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    # The 403 also precedes the 404 the bogus report id would otherwise raise.
    validate_error(
        api.create_rebate_claim(
            f.rebate_claim_payload(
                NON_EXISTENT_UUID, sc.program_id, documentation_bundle_ref="BUNDLE-X"
            ),
            INSPECTOR_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.record_inspector_verification(
            NON_EXISTENT_UUID, f.inspector_verification_payload(), sc.tech_headers
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    # Nothing moved, and the shared read still answers the rejected caller.
    still = validate_success(api.get_leakage_test(pre_test_id, sc.tech_headers))
    assert still["status"] == TEST_ACCEPTED
    assert still["reviewed_by_user_id"] == QA_HEADERS["X-User-ID"]
    _claims, claim_meta = validate_paginated(api.list_rebate_claims(ADMIN_HEADERS))
    assert claim_meta["total_count"] == 0
    _reports, report_meta = validate_paginated(
        api.list_verification_reports(ADMIN_HEADERS)
    )
    assert report_meta["total_count"] == 0


def test_the_technician_who_measured_may_not_review_the_measurement(api):
    """The check reads `X-User-ID` alone, so the right role is not enough.

    PRD 2.9: "reviewing a leakage test requires that `X-User-ID` differ from that
    test's `performed_by_user_id`, so the technician who took a measurement cannot
    accept or reject it" and "Because the role itself is checked one rung earlier,
    presenting the same `X-User-ID` under a different `X-User-Role` does **not** escape
    this rule."

    Design: Corner/rbac/the_technician_who_measured_may_not_review_the_measurement
    """
    sc = fx.scenario_eligible_system(api)
    reserved = validate_success(
        api.create_leakage_test(
            f.leakage_test_payload(sc.duct_system_id), sc.tech_headers
        ),
        201,
    )
    validate_success(
        api.pressurize_leakage_test(
            reserved["id"], f.pressurize_payload(), sc.tech_headers
        )
    )
    recorded = validate_success(
        api.record_leakage_test(
            reserved["id"],
            f.record_payload(measured_leakage_cfm=300.0),
            sc.tech_headers,
        )
    )
    assert recorded["performed_by_user_id"] == sc.technician_id
    assert recorded["status"] == TEST_RECORDED

    # The correct role, but the measuring technician's own identifier.
    validate_error(
        api.review_leakage_test(
            reserved["id"],
            f.review_payload(review_note="looks fine to me"),
            make_headers(sc.technician_id, ROLE_QA_VERIFIER),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    untouched = validate_success(api.get_leakage_test(reserved["id"], QA_HEADERS))
    assert untouched["status"] == TEST_RECORDED
    assert untouched["reviewed_by_user_id"] is None
    assert sc.read_duct_system()["baseline_leakage_cfm25"] is None

    accepted = validate_success(
        api.review_leakage_test(
            reserved["id"],
            f.review_payload(review_note="independent review"),
            QA_HEADERS,
        )
    )
    assert accepted["status"] == TEST_ACCEPTED
    assert accepted["reviewed_by_user_id"] == QA_HEADERS["X-User-ID"]
    duct_system = sc.read_duct_system()
    assert duct_system["baseline_leakage_cfm25"] == 300.00
    assert duct_system["working_leakage_cfm25"] == 300.00

    # Segregation (3) still outranks the state rung (6) on the now-ACCEPTED test.
    validate_error(
        api.review_leakage_test(
            reserved["id"],
            f.review_payload(decision=DECISION_REJECT, review_note="trying again"),
            make_headers(sc.technician_id, ROLE_QA_VERIFIER),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert sc.read_duct_system()["baseline_leakage_cfm25"] == 300.00
    final = validate_success(api.get_leakage_test(reserved["id"], QA_HEADERS))
    assert final["status"] == TEST_ACCEPTED
    assert final["reviewed_by_user_id"] == QA_HEADERS["X-User-ID"]


def test_the_sealing_technician_may_not_issue_and_the_issuer_may_not_inspect(api):
    """Pairs (b) and (c), each reaching across entities the request never names.

    PRD 2.9: "issuing a verification report requires that `X-User-ID` differ from the
    `technician_id` of the seal job being verified" and "recording the inspector spot
    check on a rebate claim requires that `X-User-ID` differ from the
    `issued_by_user_id` of the verification report that claim was built on".

    Design: Corner/rbac/the_sealing_technician_may_not_issue_and_the_issuer_may_not_inspect
    """
    sc = fx.scenario_submitted_claim(api)

    validate_error(
        api.issue_verification_report(
            sc.report_id,
            f.issue_payload(signature_note="signing off on my own run"),
            make_headers(sc.technician_id, ROLE_QA_VERIFIER),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        api.record_inspector_verification(
            sc.claim_id,
            f.inspector_verification_payload(),
            make_headers(QA_HEADERS["X-User-ID"], ROLE_UTILITY_INSPECTOR),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    mid = sc.read_claim()
    assert mid["status"] == CLAIM_SUBMITTED
    assert mid["inspector_user_id"] is None

    approved = validate_success(
        api.record_inspector_verification(
            sc.claim_id, f.inspector_verification_payload(), INSPECTOR_HEADERS
        )
    )
    assert approved["status"] == CLAIM_APPROVED
    assert approved["inspector_user_id"] == INSPECTOR_HEADERS["X-User-ID"]
    assert approved["inspector_variance_pct"] == 3.64

    report = sc.read_report()
    assert report["status"] == REPORT_ISSUED
    assert report["issued_by_user_id"] == QA_HEADERS["X-User-ID"]
    assert_program_ledger(sc.read_program(), 307230, 0, 4692770)
