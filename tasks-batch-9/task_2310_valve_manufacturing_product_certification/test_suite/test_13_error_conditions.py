"""Error conditions: identity, design maturity, license scope and repeated certification.

Each of these is a specific error identifier rather than a generic refusal, and in every
case the refused write leaves the entities it touched exactly as it found them.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    CertStatus,
    CompliancePosture,
    ComponentStatus,
    ErrorId,
    LicenseStatus,
    ROLE_PRODUCT_ENGINEER,
    factories,
    fixtures,
    make_headers_without_identity,
    make_product_engineer_headers,
    make_quality_manager_headers,
)


def test_01_an_empty_identity_header_is_unauthenticated(api):
    """The identity check precedes everything else, so the design is never created.

    PRD §2.1: "Every request to every endpoint must carry two headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in which they act.
    If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/corner_missing_identity_header_returns_unauthenticated
    """
    response = api.create_valve_model(
        factories.valve_model_payload("BV-300-NOID", "BALL", 300, "CF8M", 100, "METAL", 420.0),
        make_headers_without_identity(ROLE_PRODUCT_ENGINEER),
    )

    validate_error(response, ErrorId.UNAUTHENTICATED, 401)
    rows, meta = validate_paginated(api.list_valve_models(make_quality_manager_headers()))
    assert rows == []
    assert meta["total_count"] == 0


def test_02_a_unit_may_not_be_opened_against_a_draft_design(api):
    """A prototype unit needs the design at least in review, so a draft design is refused
    and the body component is not consumed.

    PRD §3.3: "Creation enforces the traceability contract. The named design must be
    `IN_REVIEW` or `RELEASED`, otherwise `ERR_MODEL_NOT_RELEASED`." PRD §3.1: "This is also why
    a unit may be opened against a design that is only `IN_REVIEW`: prototype units have to
    exist and be type-tested before the design they belong to can be released, while
    certification of a production unit still demands a fully `RELEASED` design."

    Design: Corner/errors/corner_unit_creation_against_draft_model_returns_model_not_released
    """
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-C13",
        foundry_name="Corner Draft Castings",
        heat_number="H-C1301",
        mtr_document_ref="MTR-C1301",
        model_code="BV-300-DRAFT",
        release_design=False,
        license_code="MON-C13",
        scope_valve_types=["BALL"],
        grant_license=False,
    )

    response = api.create_valve_unit(
        factories.valve_unit_payload(
            line["model"]["id"],
            line["component"]["id"],
            line["license"]["id"],
            "SN-C13-1",
        ),
        make_product_engineer_headers(),
    )

    validate_error(response, ErrorId.MODEL_NOT_RELEASED, 409)
    assert fixtures.read_component(api, line["component"]["id"])["status"] == (
        ComponentStatus.CREATED
    )


def test_03_a_license_that_does_not_cover_the_valve_type_blocks_certification(api):
    """The license is granted and compliant, but it covers gate valves only, so a ball
    valve cannot be certified under it.

    PRD §3.7: "The design's `valve_type` must be a member of the license's
    `scope_valve_types`, otherwise `ERR_LICENSE_SCOPE_MISMATCH` (HTTP 422)."

    Design: Corner/errors/corner_license_scope_mismatch_blocks_certification
    """
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-C14",
        foundry_name="Corner Scope Castings",
        heat_number="H-C1401",
        mtr_document_ref="MTR-C1401",
        model_code="BV-300-SCOPE",
        valve_type="BALL",
        license_code="MON-C14",
        scope_valve_types=["GATE"],
        lead_auditor_user_id="aud-c14",
    )
    granted = fixtures.read_license(api, line["license"]["id"])
    assert granted["license_status"] == LicenseStatus.GRANTED
    assert granted["compliance_posture"] == CompliancePosture.COMPLIANT
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-C14-1",
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id="tech-c14")
    fixtures.record_pass_run(
        api, unit["id"], test_bench_code="BENCH-C14", technician_user_id="tech-c14"
    )

    response = api.valve_unit_cert_action(
        unit["id"],
        factories.cert_action_payload("CERTIFY"),
        make_quality_manager_headers("qm-c14"),
    )

    validate_error(response, ErrorId.LICENSE_SCOPE_MISMATCH, 422)
    assert fixtures.read_unit(api, unit["id"])["cert_status"] == CertStatus.TESTS_PASSED


def test_04_certifying_an_already_certified_unit_is_an_error_not_a_no_op(api):
    """The second certification is refused outright, and the first certifier's identity is
    left standing on the unit.

    PRD §2.10: "certifying a unit whose `cert_status` is already `CERTIFIED` is
    `ERR_UNIT_ALREADY_CERTIFIED` — a repeated certification is an error, never a no-op" PRD
    §3.7: "A successful certification writes `certified_by_user_id` from `X-User-ID` and
    `certified_at` from the current logical-clock instant".

    Design: Corner/errors/corner_repeated_certify_returns_already_certified
    """
    scenario = fixtures.build_certified_unit(
        api,
        serial_number="SN-C15-1",
        test_bench_code="BENCH-C15",
        technician_user_id="tech-c15",
        quality_manager_user_id="qm-c15",
        foundry_code="FDY-C15",
        foundry_name="Corner Repeat Castings",
        heat_number="H-C1501",
        mtr_document_ref="MTR-C1501",
        model_code="BV-300-REPEAT",
        license_code="MON-C15",
        scope_valve_types=["BALL"],
        lead_auditor_user_id="aud-c15",
    )
    assert scenario["unit"]["cert_status"] == CertStatus.CERTIFIED

    response = api.valve_unit_cert_action(
        scenario["unit"]["id"],
        factories.cert_action_payload("CERTIFY"),
        make_quality_manager_headers("qm-c16"),
    )

    validate_error(response, ErrorId.UNIT_ALREADY_CERTIFIED, 409)
    unchanged = fixtures.read_unit(api, scenario["unit"]["id"])
    assert unchanged["cert_status"] == CertStatus.CERTIFIED
    assert unchanged["certified_by_user_id"] == "qm-c15"
