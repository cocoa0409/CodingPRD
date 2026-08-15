"""Isolation orders: parallel status/compliance axes, audit compliance
boundary, and the non-compliance cascade (PRD §2.9, §3.9, §3.12)."""
from test_helpers import (
    ApiErrorId,
    assert_approx_equal,
    assert_instant_equal,
    create_audit,
    create_isolation_order,
    discontinue_isolation_order,
    get_isolation_order,
    get_unit,
    list_caps,
    setup_two_active_contact_orders,
    setup_unit_with_patient,
    start_isolation_order,
    validate_error,
)


def test_discontinue_preserves_non_compliant_axis(api, nurse_manager_headers):
    """PRD §3.9: "Discontinuing works from either `ORDERED` or `ACTIVE`
    (`ERR_ISOLATION_ALREADY_DISCONTINUED` otherwise), sets `discontinued_at`,
    and lands the order in terminal `DISCONTINUED` — while leaving
    `compliance_status` exactly as it stands. A discontinuation never resets the
    compliance axis."
    PRD §3.9: "The new order records the patient's `current_unit_id` as its
    `unit_id`, stamps `ordered_by_user_id` from the acting user and `ordered_at`
    from the clock, and starts with `status` `ORDERED` and `compliance_status`
    `NOT_AUDITED`."

    Design: Difficulty/non_linear_state_machine/isolation_order_parallel_status_and_compliance_axes
    """
    ctx = setup_unit_with_patient(unit_type="WARD")
    order = create_isolation_order(ctx["patient"]["id"], precaution_type="CONTACT")
    assert order["compliance_status"] == "NOT_AUDITED"
    start_isolation_order(order["id"])

    audit = create_audit(
        order["id"], observed_at="2026-08-03T10:00:00Z",
        elements_checked=9, elements_passed=8,
    )
    assert_approx_equal(audit["compliance_pct"], 88.9, "compliance_pct")
    assert audit["outcome"] == "NON_COMPLIANT"

    discontinue_isolation_order(order["id"])
    final = get_isolation_order(order["id"])
    assert final["status"] == "DISCONTINUED"
    assert final["compliance_status"] == "NON_COMPLIANT", (
        "the compliance axis must survive the status-axis transition"
    )
    assert final["discontinued_at"] is not None


def test_non_compliant_audit_spawns_cap_and_elevates_posture(
    api, nurse_manager_headers
):
    """PRD §3.9: "When that latest outcome is `NON_COMPLIANT`, the
    compliance-axis mutation cascades: the system creates a
    `CorrectiveActionPlan` for the order's unit with `source_type`
    `ISOLATION_AUDIT`, `source_ref_id` pointing at the audit, a system-generated
    `description`, a `due_date` fourteen days after the audit's `observed_at`,
    `created_by_user_id` set to the literal string `system`, and status starting
    directly at `ACTIVE`. That plan creation recomputes the unit's posture,
    driving `ELEVATED`."

    Design: Difficulty/non_linear_state_machine/isolation_order_parallel_status_and_compliance_axes
    """
    ctx = setup_unit_with_patient(unit_type="WARD")
    order = create_isolation_order(ctx["patient"]["id"], precaution_type="CONTACT")
    start_isolation_order(order["id"])
    create_audit(
        order["id"], observed_at="2026-08-03T10:00:00Z",
        elements_checked=9, elements_passed=8,
    )

    caps, meta = list_caps({"unit_id": ctx["unit"]["id"]})
    assert meta["total_count"] == 1, (
        f"exactly one auto-CAP must exist, got {meta['total_count']}"
    )
    assert caps[0]["source_type"] == "ISOLATION_AUDIT"
    assert caps[0]["status"] == "ACTIVE"
    assert get_unit(ctx["unit"]["id"])["surveillance_posture"] == "ELEVATED"


def _audit_and_collect(unit_id, order_id, observed_at, checked, passed):
    return create_audit(
        order_id, observed_at=observed_at,
        elements_checked=checked, elements_passed=passed,
    )


def test_noncompliant_audit_cascades_order_field_then_cap(
    api, nurse_manager_headers
):
    """PRD §3.9: "The order's `compliance_status` then follows last-audit-wins:
    it takes the `outcome` of the most recent audit by `observed_at`, breaking
    ties by the audit's `created_at`. When that latest outcome is
    `NON_COMPLIANT`, the compliance-axis mutation cascades: the system creates a
    `CorrectiveActionPlan` for the order's unit with `source_type`
    `ISOLATION_AUDIT`, `source_ref_id` pointing at the audit, a system-generated
    `description`, a `due_date` fourteen days after the audit's `observed_at`,
    `created_by_user_id` set to the literal string `system`, and status starting
    directly at `ACTIVE`."

    Design: Difficulty/transitive_cascade/audit_noncompliance_cascades_cap_then_posture
    """
    ctx = setup_unit_with_patient()
    order = create_isolation_order(ctx["patient"]["id"], precaution_type="AIRBORNE")
    start_isolation_order(order["id"])

    audit = _audit_and_collect(
        ctx["unit"]["id"], order["id"], "2026-08-02T09:00:00Z", 10, 7
    )
    assert_approx_equal(audit["compliance_pct"], 70.0, "compliance_pct")
    assert audit["outcome"] == "NON_COMPLIANT"

    order_after = get_isolation_order(order["id"])
    assert order_after["compliance_status"] == "NON_COMPLIANT", (
        "hop 1: the order field must take the audit outcome"
    )

    caps, meta = list_caps({"unit_id": ctx["unit"]["id"]})
    assert meta["total_count"] == 1, (
        f"hop 2: exactly one auto-created CAP expected, got {meta['total_count']}"
    )
    cap = caps[0]
    assert cap["source_type"] == "ISOLATION_AUDIT"
    assert cap["source_ref_id"] == audit["id"]
    assert cap["status"] == "ACTIVE"
    assert cap["created_by_user_id"] == "system"
    assert_instant_equal(cap["due_date"], "2026-08-16T09:00:00Z", "cap due_date")


def test_cap_creation_recomputes_unit_posture_and_version(
    api, nurse_manager_headers
):
    """PRD §3.9: "That plan creation recomputes the unit's posture, driving
    `ELEVATED`."
    PRD §2.9: "Every recomputation that changes the posture is a mutation of the
    unit and increments its `version`."

    Design: Difficulty/transitive_cascade/audit_noncompliance_cascades_cap_then_posture
    """
    ctx = setup_unit_with_patient()
    unit_v0 = ctx["unit"]["version"]
    assert ctx["unit"]["surveillance_posture"] == "NORMAL"
    order = create_isolation_order(ctx["patient"]["id"], precaution_type="AIRBORNE")
    start_isolation_order(order["id"])
    _audit_and_collect(ctx["unit"]["id"], order["id"], "2026-08-02T09:00:00Z", 10, 7)

    unit_after = get_unit(ctx["unit"]["id"])
    assert unit_after["surveillance_posture"] == "ELEVATED", (
        "hop 3: the auto-CAP must drive the unit posture to ELEVATED"
    )
    assert unit_after["version"] > unit_v0, (
        f"posture recompute must increment unit version ({unit_v0} -> "
        f"{unit_after['version']})"
    )


def test_audit_at_exactly_90_is_compliant_and_spawns_no_cap(
    api, nurse_manager_headers
):
    """PRD §3.9: "The system stamps `auditor_user_id` from the acting user,
    computes `compliance_pct` as one hundred times `elements_passed` divided by
    `elements_checked`, rounded to one decimal place half-up, and derives the
    audit's `outcome`: `COMPLIANT` when the rounded percentage is at least 90.0,
    `NON_COMPLIANT` otherwise. The comparison happens after rounding, so an
    audit at exactly 90.0 is compliant while one at 88.9 is not."

    Design: Difficulty/boundary_precision_check/isolation_audit_compliance_boundary_90_exactly
    """
    ctx = setup_two_active_contact_orders()
    audit = _audit_and_collect(
        ctx["unit"]["id"], ctx["order_1"]["id"], "2026-08-02T09:00:00Z", 10, 9
    )
    assert_approx_equal(audit["compliance_pct"], 90.0, "compliance_pct")
    assert audit["outcome"] == "COMPLIANT", "the 90.0 boundary is inclusive"
    assert get_isolation_order(ctx["order_1"]["id"])["compliance_status"] == "COMPLIANT"

    caps, meta = list_caps({"unit_id": ctx["unit"]["id"]})
    assert meta["total_count"] == 0, "a COMPLIANT audit must not create a CAP"


def test_audit_at_88_9_is_non_compliant_and_spawns_cap(api, nurse_manager_headers):
    """PRD §3.9: "The system stamps `auditor_user_id` from the acting user,
    computes `compliance_pct` as one hundred times `elements_passed` divided by
    `elements_checked`, rounded to one decimal place half-up, and derives the
    audit's `outcome`: `COMPLIANT` when the rounded percentage is at least 90.0,
    `NON_COMPLIANT` otherwise. The comparison happens after rounding, so an
    audit at exactly 90.0 is compliant while one at 88.9 is not."
    PRD §3.9: "When that latest outcome is `NON_COMPLIANT`, the compliance-axis
    mutation cascades: the system creates a `CorrectiveActionPlan` for the
    order's unit with `source_type` `ISOLATION_AUDIT`, `source_ref_id` pointing
    at the audit, a system-generated `description`, a `due_date` fourteen days
    after the audit's `observed_at`, `created_by_user_id` set to the literal
    string `system`, and status starting directly at `ACTIVE`."

    Design: Difficulty/boundary_precision_check/isolation_audit_compliance_boundary_90_exactly
    """
    ctx = setup_two_active_contact_orders()
    _audit_and_collect(
        ctx["unit"]["id"], ctx["order_1"]["id"], "2026-08-02T09:00:00Z", 10, 9
    )
    audit_fail = _audit_and_collect(
        ctx["unit"]["id"], ctx["order_2"]["id"], "2026-08-02T10:00:00Z", 9, 8
    )
    assert_approx_equal(audit_fail["compliance_pct"], 88.9, "compliance_pct")
    assert audit_fail["outcome"] == "NON_COMPLIANT"

    caps, meta = list_caps({"unit_id": ctx["unit"]["id"]})
    assert meta["total_count"] == 1, (
        f"only the NON_COMPLIANT audit creates a CAP, got {meta['total_count']}"
    )
    assert caps[0]["source_ref_id"] == audit_fail["id"]


def test_audit_elements_passed_exceeding_checked_rejected(api, nurse_manager_headers):
    """PRD §3.9: "The audit payload carries the `isolation_order_id`, the
    `observed_at` timestamp, `elements_checked` (at least 1), and
    `elements_passed` (at least 0 and no greater than `elements_checked`, else
    `ERR_AUDIT_ELEMENTS_INVALID`)."

    Design: Corner/validations/audit_elements_row_rule
    """
    ctx = setup_unit_with_patient(unit_type="WARD")
    order = create_isolation_order(ctx["patient"]["id"], precaution_type="DROPLET")
    start_isolation_order(order["id"])
    resp = api.create_isolation_audit(
        {
            "isolation_order_id": order["id"],
            "observed_at": "2026-08-02T09:00:00Z",
            "elements_checked": 10,
            "elements_passed": 11,
        },
        nurse_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_ELEMENTS_INVALID)
    assert resp.status_code == 422
