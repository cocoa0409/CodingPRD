"""Audits and findings: audit window boundary, scope overlap semantics,
state gating, close precondition, shortfall computation, cross-agreement
scope check, and 404 sweeps (PRD sections 3.7, 2.8)."""
from test_helpers import (
    ANALYST,
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_audit,
    create_accepted_report,
    create_active_agreement,
    create_audit,
    create_fieldwork_audit,
    create_finding,
    create_licensee,
    make_licensee_headers,
    make_report_line,
    setup_flagged_report,
    setup_open_finding,
    submit_report,
    validate_error,
    validate_report,
    validate_success,
)


def test_audit_window_last_day_boundary_auditable(api, analyst_headers):
    """PRD section 3.7: "the scope's end must fall on or after the cutoff
    computed as the current logical time minus the agreement's
    `audit_window_months`; a scope ending exactly on the cutoff is still
    auditable, while an older scope is rejected with
    `ERR_AUDIT_WINDOW_EXPIRED` (HTTP 422)." PRD section 2.6: "Before any
    clock-setting call has been made, the logical clock reads exactly
    2026-08-01T00:00:00Z."

    Design: Difficulty/boundary_precision_check/audit_window_last_day_boundary
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-33333-L1", audit_window_months=24,
        underreport_tolerance_bp=1000,
    )
    # cutoff = 2026-08-01 minus 24 months = 2024-08-01; exactly-on is auditable.
    resp = api.create_audit(
        {"agreement_id": agreement["id"],
         "scope_period_start": "2024-08-01T00:00:00Z",
         "scope_period_end": "2024-08-01T00:00:00Z"},
        analyst_headers,
    )
    audit = validate_success(resp, expected_status=201)
    assert audit["status"] == "INITIATED"


def test_audit_window_one_day_before_cutoff_expired(api, analyst_headers):
    """PRD section 3.7: "a scope ending exactly on the cutoff is still
    auditable, while an older scope is rejected with `ERR_AUDIT_WINDOW_EXPIRED`
    (HTTP 422)." PRD section 2.6: "Before any clock-setting call has been
    made, the logical clock reads exactly 2026-08-01T00:00:00Z."

    Design: Difficulty/boundary_precision_check/audit_window_last_day_boundary
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-33334-L2", audit_window_months=24,
        underreport_tolerance_bp=1000,
    )
    resp = api.create_audit(
        {"agreement_id": agreement["id"],
         "scope_period_start": "2024-07-30T00:00:00Z",
         "scope_period_end": "2024-07-31T00:00:00Z"},
        analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_EXPIRED)


def test_audit_scope_closed_interval_touch_overlaps(api, analyst_headers):
    """PRD section 3.7: "the closed scope interval must not overlap any
    existing audit of the same agreement in `INITIATED`, `FIELDWORK`, or
    `FINDINGS_ISSUED` status — and because the interval is closed, two scopes
    that merely touch at an endpoint do overlap. A collision is rejected with
    `ERR_AUDIT_SCOPE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/audit_scope_closed_interval_touch
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-77777-Q1", audit_window_months=24,
        underreport_tolerance_bp=1000,
    )
    create_audit(
        agreement,
        scope_period_start="2026-01-01T00:00:00Z",
        scope_period_end="2026-03-31T00:00:00Z",
    )
    resp = api.create_audit(
        {"agreement_id": agreement["id"],
         "scope_period_start": "2026-03-31T00:00:00Z",
         "scope_period_end": "2026-06-30T00:00:00Z"},
        analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_SCOPE_OVERLAP)


def test_audit_scope_starting_next_day_accepted(api, analyst_headers):
    """PRD section 3.7: "the closed scope interval must not overlap any
    existing audit of the same agreement in `INITIATED`, `FIELDWORK`, or
    `FINDINGS_ISSUED` status — and because the interval is closed, two scopes
    that merely touch at an endpoint do overlap." A scope beginning strictly
    after the existing end does not touch and is allowed.

    Design: Difficulty/resource_temporal_overlap/audit_scope_closed_interval_touch
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-77778-Q2", audit_window_months=24,
        underreport_tolerance_bp=1000,
    )
    create_audit(
        agreement,
        scope_period_start="2026-01-01T00:00:00Z",
        scope_period_end="2026-03-31T00:00:00Z",
    )
    resp = api.create_audit(
        {"agreement_id": agreement["id"],
         "scope_period_start": "2026-04-01T00:00:00Z",
         "scope_period_end": "2026-06-30T00:00:00Z"},
        analyst_headers,
    )
    audit = validate_success(resp, expected_status=201)
    assert audit["status"] == "INITIATED"


def test_finding_requires_audit_fieldwork(api, analyst_headers):
    """PRD section 3.7: "Findings are recorded during fieldwork. While the
    audit is in `FIELDWORK` — and only then, otherwise
    `ERR_AUDIT_INVALID_STATE` — an analyst records an **AuditFinding**".

    Design: Difficulty/cross_entity_state_dependency/finding_requires_audit_fieldwork
    """
    ctx = setup_flagged_report(patent_reference="US-55555-N1")
    audit = create_audit(ctx["agreement"])  # stays INITIATED
    resp = api.create_audit_finding(
        {"audit_id": audit["id"], "report_id": ctx["report"]["id"],
         "finding_type": "UNDERREPORTED_BASE", "audited_base_cents": 180_000},
        analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_INVALID_STATE)


def test_finding_allowed_during_fieldwork(api, analyst_headers):
    """PRD section 3.7: "Findings are recorded during fieldwork. While the
    audit is in `FIELDWORK` — and only then, otherwise
    `ERR_AUDIT_INVALID_STATE` — an analyst records an **AuditFinding** with
    the `audit_id`, the `report_id` under examination, a `finding_type`, and
    the `audited_base_cents` ... The finding is born `OPEN`".

    Design: Difficulty/cross_entity_state_dependency/finding_requires_audit_fieldwork
    """
    ctx = setup_flagged_report(patent_reference="US-55556-N2")
    audit = create_fieldwork_audit(ctx["agreement"])
    finding = create_finding(audit["id"], ctx["report"]["id"], audited_base_cents=180_000)
    assert finding["status"] == "OPEN"
    assert finding["recorded_by_user_id"]


def test_audit_close_blocked_with_open_findings(api, analyst_headers):
    """PRD section 3.7: "Closing carries an additional gate: every finding
    recorded under the audit must have reached a terminal status —
    `ACCEPTED`, `WAIVED`, or `RESOLVED` — before the audit can close;
    attempting to close with findings still `OPEN` or `DISPUTED` is likewise
    rejected with `ERR_AUDIT_INVALID_STATE`." and "A `LicensingAnalyst` may
    instead waive the finding — `resolution` of `WAIVED` — which closes it
    with no financial effect."

    Design: Corner/state_machines/audit_close_blocked_with_open_findings
    """
    ctx = setup_open_finding(patent_reference="US-56565-X1")
    advance_audit(ctx["audit"]["id"], "FINDINGS_ISSUED")

    resp = api.advance_audit(ctx["audit"]["id"], {"to_state": "CLOSED"}, analyst_headers)
    validate_error(resp, ApiErrorId.ERR_AUDIT_INVALID_STATE)

    resp = api.resolve_finding(ctx["finding"]["id"], {"resolution": "WAIVED"}, analyst_headers)
    validate_success(resp)

    resp = api.advance_audit(ctx["audit"]["id"], {"to_state": "CLOSED"}, analyst_headers)
    closed = validate_success(resp)
    assert closed["status"] == "CLOSED"


def test_shortfall_recomputed_minus_recognized(api, analyst_headers):
    """PRD section 3.7: "The amount already recognized for the report is its
    `final_royalty_cents` if the report was accepted or accepted with
    adjustment, and 0 otherwise. The royalty is then recomputed under the
    final-royalty rules of section 3.6 with `audited_base_cents` standing in
    for the product base ... The shortfall is the excess of the recomputed
    royalty over the recognized amount, floored at zero."

    Design: Corner/calculations/shortfall_recomputed_minus_recognized
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-11112-B2", underreport_tolerance_bp=1000,
        audit_window_months=24,
    )
    report = create_accepted_report(
        agreement, licensee,
        lines=[make_report_line(gross_sales_cents=100_000)],
    )
    # recognized = final 5000 (100000 * 5%).
    audit = create_fieldwork_audit(agreement)
    finding = create_finding(audit["id"], report["id"], audited_base_cents=150_000)
    # recomputed = 150000 * 5% = 7500; shortfall = 7500 - 5000 = 2500.
    assert finding["shortfall_cents"] == 2500


def test_finding_report_outside_audit_scope(api, analyst_headers):
    """PRD section 3.7: "The referenced report must be examinable: it must
    belong to the audit's agreement, its period must overlap the audit's
    scope, and it must be in `FLAGGED`, `AUDIT_REFERRED`, `ACCEPTED`, or
    `ACCEPTED_WITH_ADJUSTMENT` status — any shortfall there is rejected with
    `ERR_REPORT_NOT_IN_AUDIT_SCOPE` (HTTP 422)."

    Design: Corner/validations/finding_report_outside_audit_scope
    """
    la = create_licensee(legal_name="Sc A")
    lb = create_licensee(legal_name="Sc B")
    _, aga = create_active_agreement(
        la, patent_reference="US-99990-J2", underreport_tolerance_bp=1000,
        audit_window_months=24,
    )
    _, agb = create_active_agreement(
        lb, patent_reference="US-99991-K2", underreport_tolerance_bp=1000,
    )
    rb = submit_report(
        agb, lb, lines=[make_report_line(gross_sales_cents=100_000)]
    )
    validate_report(rb["id"], benchmark_net_sales_cents=200_000)

    audit = create_fieldwork_audit(aga)
    resp = api.create_audit_finding(
        {"audit_id": audit["id"], "report_id": rb["id"],
         "finding_type": "UNDERREPORTED_BASE", "audited_base_cents": 180_000},
        analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_IN_AUDIT_SCOPE)


def test_action_endpoints_not_found_sweep(api, analyst_headers, finance_headers):
    """PRD section 2.8 tier 3: "Path identifiers are resolved strictly
    left-to-right, and foreign-key references in the request body must exist.
    The first unresolvable reference produces the corresponding not-found
    error: ... `ERR_AUDIT_NOT_FOUND` for an audit, `ERR_FINDING_NOT_FOUND`
    for an audit finding, ... `ERR_SUBLICENSE_NOT_FOUND` for a sublicense
    grant, and `ERR_RUN_NOT_FOUND` for a distribution run — each with HTTP
    404."

    Design: Corner/errors/action_endpoints_not_found_sweep
    """
    cases = [
        (api.advance_audit(NON_EXISTENT_UUID, {"to_state": "FIELDWORK"}, analyst_headers),
         ApiErrorId.ERR_AUDIT_NOT_FOUND),
        (api.resolve_finding(NON_EXISTENT_UUID, {"resolution": "WAIVED"}, analyst_headers),
         ApiErrorId.ERR_FINDING_NOT_FOUND),
        (api.sublicense_decision(NON_EXISTENT_UUID, {"decision": "APPROVED"}, analyst_headers),
         ApiErrorId.ERR_SUBLICENSE_NOT_FOUND),
        (api.approve_distribution_run(NON_EXISTENT_UUID, finance_headers),
         ApiErrorId.ERR_RUN_NOT_FOUND),
    ]
    for resp, err_id in cases:
        validate_error(resp, err_id)


