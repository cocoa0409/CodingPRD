"""Monogram licensing: the three-way audit closeout and the finding-driven freeze.

The closeout branches out of a single closed audit, and the two granting branches
partition the open-minor count at exactly five. Separately, a finding entry — not a
material disposition — is enough to freeze a license and stop a production programme.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    AuditState,
    BuildStatus,
    CertStatus,
    CompliancePosture,
    ErrorId,
    LicenseStatus,
    OrderStatus,
    assert_finding_identity,
    factories,
    fixtures,
    make_monogram_auditor_headers,
)


def _license_action_response(api, license_id, action, auditor_user_id):
    return api.monogram_license_action(
        license_id,
        factories.license_action_payload(action),
        make_monogram_auditor_headers(auditor_user_id),
    )


# ─── Five open minors: the conditional branch ───


def _closed_audit_with_five_open_minors(api):
    """A butterfly-scoped application whose audit closed with five minor findings open
    and no majors."""
    lic = fixtures.apply_for_license(
        api,
        license_code="MON-06",
        facility_code="FAC-2",
        scope_valve_types=["BUTTERFLY"],
        lead_auditor_user_id="aud-9",
    )
    fixtures.license_action(api, lic["id"], "START_AUDIT", "aud-9")
    fixtures.raise_findings(api, lic["id"], "MINOR", 5, "aud-9")
    fixtures.license_action(api, lic["id"], "CLOSE_AUDIT", "aud-9")
    return lic


def test_01_five_open_minors_close_the_grant_branch_and_open_the_conditional_one(api):
    """One closed audit, two mutually exclusive branches: the plain grant is refused at
    five open minors and the conditional grant is the branch that is available.

    PRD §3.6: "requires `open_major_finding_count` to be exactly 0 (otherwise
    `ERR_OPEN_MAJOR_FINDINGS`) and `open_minor_finding_count` to be 5 or more (otherwise
    `ERR_MINOR_FINDING_THRESHOLD`) — the two granting branches partition the
    minor-finding count exactly at five".

    Design: Difficulty/non_linear_state_machine/monogram_audit_closeout_branches_to_conditional_grant
    """
    lic = _closed_audit_with_five_open_minors(api)

    refused = _license_action_response(api, lic["id"], "GRANT", "aud-9")
    validate_error(refused, ErrorId.MINOR_FINDING_THRESHOLD, 409)

    granted = fixtures.license_action(api, lic["id"], "GRANT_CONDITIONAL", "aud-9")

    assert granted["license_status"] == LicenseStatus.CONDITIONAL
    assert granted["compliance_posture"] == CompliancePosture.CONDITIONAL
    assert granted["open_minor_finding_count"] == 5
    assert granted["open_major_finding_count"] == 0
    assert granted["audit_state"] == AuditState.CLOSED


def test_02_the_conditional_branch_stamps_a_grace_expiry_the_grant_branch_does_not(api):
    """The conditional branch carries a side effect the plain grant lacks: a grace
    deadline 180 days out from the instant of the grant.

    PRD §3.6: "it sets `granted_at` to the current instant, sets `conditional_expires_at`
    to that instant advanced by 180 days, and recomputes the posture to `CONDITIONAL`,
    under which certification of any unit carrying a special service is refused while
    plain units still certify."

    Design: Difficulty/non_linear_state_machine/monogram_audit_closeout_branches_to_conditional_grant
    """
    lic = _closed_audit_with_five_open_minors(api)

    granted = fixtures.license_action(api, lic["id"], "GRANT_CONDITIONAL", "aud-9")

    # A fresh system's logical clock reads 2026-08-01T00:00:00Z (PRD §2.5); 180 days on
    # from that instant is 2027-01-28T00:00:00Z.
    assert granted["granted_at"] is not None
    assert granted["granted_at"].startswith("2026-08-01T00:00:00"), (
        f"granted_at should be the logical-clock instant, got {granted['granted_at']!r}"
    )
    assert granted["conditional_expires_at"] is not None
    assert granted["conditional_expires_at"].startswith("2027-01-28T00:00:00"), (
        "The grace deadline is the grant instant advanced by 180 days, got "
        f"{granted['conditional_expires_at']!r}"
    )


# ─── Four open minors: the boundary that partitions the two branches ───


def _closed_audit_with_four_open_minors(api):
    """The same closeout one finding lower: four minor findings open, no majors."""
    lic = fixtures.apply_for_license(
        api,
        license_code="MON-12",
        facility_code="FAC-4",
        scope_valve_types=["BUTTERFLY"],
        lead_auditor_user_id="aud-3",
    )
    fixtures.license_action(api, lic["id"], "START_AUDIT", "aud-3")
    fixtures.raise_findings(api, lic["id"], "MINOR", 4, "aud-3")
    fixtures.license_action(api, lic["id"], "CLOSE_AUDIT", "aud-3")
    return lic


def test_03_four_open_minors_is_one_short_of_the_conditional_branch(api):
    """Exactly four open minors falls on the grant side of the partition, so the
    conditional branch is the one refused here.

    PRD §3.6: "requires `open_major_finding_count` to be exactly 0 (otherwise
    `ERR_OPEN_MAJOR_FINDINGS`) and `open_minor_finding_count` to be 5 or more (otherwise
    `ERR_MINOR_FINDING_THRESHOLD`) — the two granting branches partition the
    minor-finding count exactly at five".

    Design: Difficulty/boundary_precision_check/grant_at_exactly_four_open_minor_findings_partitions_closeout
    """
    lic = _closed_audit_with_four_open_minors(api)

    refused = _license_action_response(api, lic["id"], "GRANT_CONDITIONAL", "aud-3")

    validate_error(refused, ErrorId.MINOR_FINDING_THRESHOLD, 409)
    unchanged = fixtures.read_license(api, lic["id"])
    assert unchanged["license_status"] == LicenseStatus.APPLIED
    assert unchanged["open_minor_finding_count"] == 4
    assert unchanged["conditional_expires_at"] is None


def test_04_the_plain_grant_succeeds_at_exactly_four_and_leaves_no_grace_deadline(api):
    """Four or fewer open minors is a clean grant: the posture reads compliant and there
    is no conditional expiry to run out.

    PRD §3.6: "requires `open_major_finding_count` to be exactly 0 (otherwise
    `ERR_OPEN_MAJOR_FINDINGS`) and `open_minor_finding_count` to be 4 or fewer (otherwise
    `ERR_MINOR_FINDING_THRESHOLD`); it sets `granted_at` to the current logical-clock
    instant, clears `conditional_expires_at` to null, and recomputes the posture to
    `COMPLIANT`."

    Design: Difficulty/boundary_precision_check/grant_at_exactly_four_open_minor_findings_partitions_closeout
    """
    lic = _closed_audit_with_four_open_minors(api)

    granted = fixtures.license_action(api, lic["id"], "GRANT", "aud-3")

    assert granted["license_status"] == LicenseStatus.GRANTED
    assert granted["compliance_posture"] == CompliancePosture.COMPLIANT, (
        "Four open minors is below the five that would make the posture CONDITIONAL"
    )
    assert granted["open_minor_finding_count"] == 4
    assert granted["conditional_expires_at"] is None
    assert granted["granted_at"] is not None
    assert granted["granted_at"].startswith("2026-08-01T00:00:00")


# ─── The second major finding: a counter increment with three hops behind it ───


def _granted_gate_programme_with_one_open_major(api):
    """A forged gate programme in production under a granted license that already
    carries one open major finding."""
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-07",
        foundry_name="Eta Forge",
        country_code="IN",
        process="FORGING",
        material_grade="A105",
        max_pressure_class=300,
        heat_number="H-7001",
        mtr_document_ref="MTR-7001",
        qty_received_kg=400.000,
        carbon_equivalent_pct=0.40,
        impact_energy_j=25,
        model_code="GV-300-A105",
        valve_type="GATE",
        pressure_class=300,
        bore_size_mm=100,
        seat_type="METAL",
        base_break_torque_nm=600.0,
        net_weight_kg=95.000,
        license_code="MON-08",
        facility_code="FAC-3",
        scope_valve_types=["GATE"],
        lead_auditor_user_id="aud-2",
    )
    order = fixtures.create_order(
        api,
        line["model"]["id"],
        order_code="ETO-GATE",
        ordered_qty=2,
        unit_price_cents=900_000,
        customer_credit_limit_cents=5_000_000,
        datasheet_break_torque_nm=600.0,
        datasheet_torque_source="VENDOR_MEASURED",
    )
    fixtures.approve_order(api, order["id"])
    fixtures.release_order_to_production(api, order["id"])
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-GATE-1",
        engineered_order_id=order["id"],
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id="tech-2")
    fixtures.record_test(
        api,
        unit["id"],
        "SHELL",
        test_bench_code="BENCH-3",
        started_at="2026-08-01T08:00:00Z",
        ended_at="2026-08-01T09:00:00Z",
        test_pressure_bar=80.0,
        hold_seconds=60,
        technician_user_id="tech-2",
    )
    fixtures.record_test(
        api,
        unit["id"],
        "SEAT",
        test_bench_code="BENCH-3",
        started_at="2026-08-01T09:00:00Z",
        ended_at="2026-08-01T10:00:00Z",
        test_pressure_bar=60.0,
        hold_seconds=60,
        technician_user_id="tech-2",
    )
    unit = fixtures.certify_unit(api, unit["id"], quality_manager_user_id="qm-2")
    fixtures.raise_findings(api, line["license"]["id"], "MAJOR", 1, "aud-2")
    return {"line": line, "order": order, "unit": unit}


def test_05_the_second_open_major_freezes_the_posture_and_suspends_the_license(api):
    """One more major finding takes the open count from one to two, which is a suspension
    and not merely a worse posture.

    PRD §3.6: "It is `FROZEN` when `open_major_finding_count` is 2 or more, or when
    `license_status` is `SUSPENDED`, `DENIED` or `REVOKED`." PRD §3.6: "Failing that, it is
    `CONDITIONAL` when `open_major_finding_count` is exactly 1, or `open_minor_finding_count`
    is 5 or more, or `license_status` is `CONDITIONAL`." PRD §3.6: "Reaching two open majors
    is therefore not merely a posture change: it freezes the posture, suspends the license
    and decertifies the license's certified units in one motion."

    Design: Difficulty/transitive_cascade/second_major_finding_freezes_license_and_holds_order
    """
    scenario = _granted_gate_programme_with_one_open_major(api)
    before = fixtures.read_license(api, scenario["line"]["license"]["id"])
    assert before["open_major_finding_count"] == 1
    assert before["compliance_posture"] == CompliancePosture.CONDITIONAL

    fixtures.raise_findings(api, scenario["line"]["license"]["id"], "MAJOR", 1, "aud-2")

    license_row = fixtures.read_license(api, scenario["line"]["license"]["id"])
    assert license_row["total_major_raised"] == 2
    assert license_row["open_major_finding_count"] == 2
    assert license_row["compliance_posture"] == CompliancePosture.FROZEN
    assert license_row["license_status"] == LicenseStatus.SUSPENDED
    assert_finding_identity(license_row)


def test_06_the_freeze_reaches_the_unit_and_then_that_unit_s_production_programme(api):
    """Three hops from a counter increment: license, then unit, then the order the unit
    belongs to — with no material-traceability entity involved.

    PRD §3.6: "the effect cascades in three links: the posture becomes `FROZEN`; every
    unit with this `monogram_license_id` and `cert_status` `CERTIFIED` moves to
    `DECERTIFIED` with `decertification_reason` `LICENSE_SUSPENDED`; and each such unit's
    engineered order, if its `status` is `IN_PRODUCTION`, moves to `HELD` with
    `held_reason` `UNIT_DECERTIFIED`, while its documentation package, if `ISSUED`, moves
    to `VOIDED`." PRD §3.7: "a `build_status` of `ASSEMBLED` or `PACKAGED` falls back to
    `REWORK`".

    Design: Difficulty/transitive_cascade/second_major_finding_freezes_license_and_holds_order
    """
    scenario = _granted_gate_programme_with_one_open_major(api)

    fixtures.raise_findings(api, scenario["line"]["license"]["id"], "MAJOR", 1, "aud-2")

    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    order = fixtures.read_order(api, scenario["order"]["id"])

    assert unit["cert_status"] == CertStatus.DECERTIFIED
    assert unit["decertification_reason"] == "LICENSE_SUSPENDED"
    assert unit["build_status"] == BuildStatus.REWORK
    assert order["status"] == OrderStatus.HELD
    assert order["held_reason"] == "UNIT_DECERTIFIED"
    assert order["certified_unit_count"] == 0
