"""Sublicense grants: permission gate, revocation re-evaluates pass-through
legitimacy, and terminal-state decision lockdown (PRD section 3.5)."""
from test_helpers import (
    ApiErrorId,
    create_active_agreement,
    create_approved_grant,
    create_royalty_report_payload,
    create_sublicense_grant_payload,
    make_licensee_headers,
    make_report_line,
    validate_error,
    validate_success,
)


def test_sublicense_request_when_not_granted(api, analyst_headers):
    """PRD section 3.5: "the agreement's `sublicense_allowed` must be true —
    the last violation is rejected with `ERR_SUBLICENSING_NOT_GRANTED` (HTTP
    422)."

    Design: Corner/validations/sublicense_request_when_not_granted
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-77778-H2", sublicense_allowed=False
    )
    resp = api.create_sublicense_grant(
        create_sublicense_grant_payload(agreement["id"], sublicensee_name="Sub"),
        make_licensee_headers(licensee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SUBLICENSING_NOT_GRANTED)


def test_sublicense_revoked_blocks_pass_through_lines(api, analyst_headers):
    """PRD section 3.6: "If any line is flagged as sublicense revenue, the
    agreement must hold at least one `APPROVED` sublicense grant; otherwise
    the submission is rejected with `ERR_NO_APPROVED_SUBLICENSE` (HTTP 422)."
    PRD section 3.5: "an `APPROVED` grant may later be decided `REVOKED`.
    `REJECTED` and `REVOKED` are terminal."

    Design: Corner/state_machines/sublicense_revoked_blocks_pass_through_lines
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-67676-Y1",
        sublicense_allowed=True,
        sublicense_passthrough_rate_bp=800,
    )
    grant = create_approved_grant(agreement, licensee)
    resp = api.sublicense_decision(grant["id"], {"decision": "REVOKED"}, analyst_headers)
    revoked = validate_success(resp)
    assert revoked["status"] == "REVOKED"

    payload = create_royalty_report_payload(
        agreement["id"], licensee["id"],
        lines=[make_report_line(product_label="S1", gross_sales_cents=50_000,
                                is_sublicense_revenue=True)],
    )
    err = api.create_royalty_report(payload, make_licensee_headers(licensee["id"]))
    validate_error(err, ApiErrorId.ERR_NO_APPROVED_SUBLICENSE)


def test_sublicense_line_without_any_grant_rejected(api, analyst_headers):
    """PRD section 3.6: "If any line is flagged as sublicense revenue, the
    agreement must hold at least one `APPROVED` sublicense grant; otherwise
    the submission is rejected with `ERR_NO_APPROVED_SUBLICENSE` (HTTP 422)."

    Design: Corner/state_machines/sublicense_revoked_blocks_pass_through_lines
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-67677-Y2",
        sublicense_allowed=True,
        sublicense_passthrough_rate_bp=800,
    )
    # No grant exists at all (never requested).
    payload = create_royalty_report_payload(
        agreement["id"], licensee["id"],
        period_start="2026-04-01T00:00:00Z", period_end="2026-04-30T00:00:00Z",
        lines=[make_report_line(product_label="S9", gross_sales_cents=50_000,
                                is_sublicense_revenue=True)],
    )
    err = api.create_royalty_report(payload, make_licensee_headers(licensee["id"]))
    validate_error(err, ApiErrorId.ERR_NO_APPROVED_SUBLICENSE)


def test_sublicense_decision_on_terminal_state(api, analyst_headers):
    """PRD section 3.5: "`REJECTED` and `REVOKED` are terminal. Any decision
    attempted from a state that does not support it — approving an
    already-approved grant, revoking a pending one — is rejected with
    `ERR_SUBLICENSE_INVALID_STATE` (HTTP 409)."

    Design: Corner/errors/sublicense_decision_on_terminal_state
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-45464-O2", sublicense_allowed=True
    )
    resp = api.create_sublicense_grant(
        create_sublicense_grant_payload(agreement["id"]),
        make_licensee_headers(licensee["id"]),
    )
    grant = validate_success(resp, expected_status=201)
    resp = api.sublicense_decision(grant["id"], {"decision": "REJECTED"}, analyst_headers)
    rejected = validate_success(resp)
    assert rejected["status"] == "REJECTED"

    err = api.sublicense_decision(grant["id"], {"decision": "APPROVED"}, analyst_headers)
    validate_error(err, ApiErrorId.ERR_SUBLICENSE_INVALID_STATE)
