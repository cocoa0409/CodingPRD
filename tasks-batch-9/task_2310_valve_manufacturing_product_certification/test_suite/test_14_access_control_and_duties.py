"""Access control by role, by acting identity and by tenancy.

Three different refusals live here and they are deliberately distinct: the wrong role on
an endpoint, the right role held by the wrong person, and the right role in the wrong works.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    CertStatus,
    CompliancePosture,
    ErrorId,
    factories,
    fixtures,
    make_monogram_auditor_headers,
    make_quality_manager_headers,
    make_supplier_rep_headers,
    make_test_technician_headers,
)


def _tests_passed_unit(api, *, suffix, technician_user_id, scope=("BALL",)):
    """A unit off a released, in-scope design taken as far as TESTS_PASSED."""
    line = fixtures.build_traceable_line(
        api,
        foundry_code=f"FDY-{suffix}",
        foundry_name=f"Corner Duty Castings {suffix}",
        heat_number=f"H-{suffix}01",
        mtr_document_ref=f"MTR-{suffix}01",
        model_code=f"BV-300-{suffix}",
        license_code=f"MON-{suffix}",
        scope_valve_types=list(scope),
        lead_auditor_user_id=f"aud-{suffix}",
    )
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number=f"SN-{suffix}-1",
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id=technician_user_id)
    fixtures.record_pass_run(
        api,
        unit["id"],
        test_bench_code=f"BENCH-{suffix}",
        technician_user_id=technician_user_id,
    )
    return {"line": line, "unit": unit}


def test_01_a_test_technician_may_not_certify_the_unit_it_tested(api):
    """Certification is not among the technician's powers, so the attempt is a role refusal
    and the unit keeps waiting for a quality manager.

    PRD §3.7: "Certification is the act that turns a tested unit into a saleable, documented
    article, and it belongs solely to the `QualityManager`." PRD §2.1: "A value of `X-User-Role`
    that is not one of those seven, or that is one of them but is not authorised for the
    endpoint being called, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/corner_test_technician_cannot_certify_a_unit
    """
    scenario = _tests_passed_unit(api, suffix="C16", technician_user_id="tech-c16")

    response = api.valve_unit_cert_action(
        scenario["unit"]["id"],
        factories.cert_action_payload("CERTIFY"),
        make_test_technician_headers("tech-c16"),
    )

    validate_error(response, ErrorId.ROLE_NOT_PERMITTED, 403)
    unchanged = fixtures.read_unit(api, scenario["unit"]["id"])
    assert unchanged["cert_status"] == CertStatus.TESTS_PASSED
    assert unchanged["certified_by_user_id"] is None


def test_02_the_person_who_witnessed_a_test_may_not_certify_the_unit(api):
    """The role is right and the identity is wrong: the same operator identifier appears on
    a test record of the unit, so the certification is a duty conflict.

    PRD §2.11: "The `QualityManager` who certifies a valve unit must not appear as the
    `performed_by_user_id` of **any** test record on that unit; a collision is
    `ERR_SOD_TEST_WITNESS_CONFLICT` (HTTP 403)." PRD §2.11: "Two constraints in this system are
    enforced against `X-User-ID` rather than against the role, so the role check passes and the
    identity check still fails."

    Design: Corner/rbac/corner_certify_by_the_test_witness_returns_duty_conflict
    """
    scenario = _tests_passed_unit(api, suffix="C17", technician_user_id="qm-c17")

    response = api.valve_unit_cert_action(
        scenario["unit"]["id"],
        factories.cert_action_payload("CERTIFY"),
        make_quality_manager_headers("qm-c17"),
    )

    validate_error(response, ErrorId.SOD_TEST_WITNESS_CONFLICT, 403)
    unchanged = fixtures.read_unit(api, scenario["unit"]["id"])
    assert unchanged["cert_status"] == CertStatus.TESTS_PASSED
    assert unchanged["certified_by_user_id"] is None


def test_03_the_lead_auditor_may_not_waive_a_finding_on_its_own_license(api):
    """Raising was open to the lead auditor and waiving is not, so the major finding stays
    open and the posture stays conditional.

    PRD §2.11: "The `MonogramAuditor` who waives an audit finding must not be the license's
    `lead_auditor_user_id`; a collision is `ERR_SOD_AUDIT_WAIVER_CONFLICT` (HTTP 403). Raising
    and closing findings remain open to the lead auditor — only waiving is restricted, because
    waiving is the only finding action that removes a blocker without corrective action." PRD
    §3.6: "Failing that, it is `CONDITIONAL` when `open_major_finding_count` is exactly 1, or
    `open_minor_finding_count` is 5 or more, or `license_status` is `CONDITIONAL`."

    Design: Corner/rbac/corner_lead_auditor_cannot_waive_a_finding_on_own_license
    """
    lic = fixtures.apply_for_license(
        api,
        license_code="MON-C18",
        facility_code="FAC-C18",
        scope_valve_types=["BALL"],
        lead_auditor_user_id="aud-c18",
    )
    fixtures.license_action(api, lic["id"], "START_AUDIT", "aud-c18")
    raised = fixtures.raise_findings(api, lic["id"], "MAJOR", 1, auditor_user_id="aud-c18")
    assert raised["open_major_finding_count"] == 1
    assert raised["compliance_posture"] == CompliancePosture.CONDITIONAL

    response = api.create_finding_entry(
        lic["id"],
        factories.finding_entry_payload("WAIVE", "MAJOR"),
        make_monogram_auditor_headers("aud-c18"),
    )

    validate_error(response, ErrorId.SOD_AUDIT_WAIVER_CONFLICT, 403)
    unchanged = fixtures.read_license(api, lic["id"])
    assert unchanged["waived_major_finding_count"] == 0
    assert unchanged["open_major_finding_count"] == 1
    assert unchanged["compliance_posture"] == CompliancePosture.CONDITIONAL


def test_04_a_supplier_rep_may_not_read_another_works_heat_lot(api):
    """The role is permitted on the retrieval endpoint, but the lot belongs to a different
    works, so the read is a tenancy refusal rather than a role refusal.

    PRD §2.1: "A supplier representative may declare a heat lot only with a `foundry_id`
    equal to its own `X-User-ID`, may list heat lots but sees only rows whose `foundry_id`
    matches, and may retrieve a single heat lot only when that lot belongs to it. A cross-tenant
    read or write is rejected with `ERR_FOUNDRY_SCOPE_VIOLATION` (HTTP 403) — deliberately
    distinct from `ERR_ROLE_NOT_PERMITTED`, because the role was correct and only the tenancy
    was wrong."

    Design: Corner/rbac/corner_supplier_rep_cannot_read_another_foundrys_heat_lot
    """
    works_a = fixtures.create_foundry(
        api, foundry_code="FDY-C19A", name="Corner Tenancy Castings A", country_code="IN"
    )
    works_b = fixtures.create_foundry(
        api, foundry_code="FDY-C19B", name="Corner Tenancy Castings B", country_code="IN"
    )
    lot = fixtures.create_heat_lot(
        api, works_a["id"], heat_number="H-C1901", mtr_document_ref="MTR-C1901"
    )

    response = api.get_heat_lot(lot["id"], make_supplier_rep_headers(works_b["id"]))

    validate_error(response, ErrorId.FOUNDRY_SCOPE_VIOLATION, 403)
    own_read = fixtures.read_lot(
        api, lot["id"], headers=make_supplier_rep_headers(works_a["id"])
    )
    assert own_read["foundry_id"] == works_a["id"]
