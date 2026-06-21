"""Compensating-action ledger invariants and optimistic concurrency on transfer
completion.

Covers difficulty rule compensating_invariant and the corner OCC instances
(success path and stale-version rejection).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_applicant_headers, make_licensing_officer_headers,
    create_transfer_payload, complete_transfer_payload,
    TEST_USERS,
    setup_zoning_cleared_application, setup_active_license_with_transfer,
    setup_approved_transfer, get_application_fee_assessments, fee_sum,
    assessments_of_kind, set_clock,
)

OFFICER = TEST_USERS["licensing_officer_headers"]


def test_reject_reverses_application_fee_net_zero(api):
    """PRD §3.4: "Rejection records the officer's `X-User-ID` into
    `reviewed_by_user_id` and appends a `REVERSAL` assessment for the negative of
    the estimated fee, reversing the application-fee charge so that the net
    application ledger returns to zero."

    Design: Difficulty/compensating_invariant/reject_reverses_application_fee_net_zero
    """
    # MEDIUM, declared 4 -> APPLICATION_FEE 250 + 5*4 = 270.00.
    ctx = setup_zoning_cleared_application(
        category_overrides={
            "code": "REJ_MED", "risk_tier": "MEDIUM", "activity_base_risk": 20,
            "required_inspection_count": 0, "requires_zoning_check": False,
            "term_months": 12, "allowed_zones": ["C1"]},
        application_overrides={"declared_employee_count": 4, "requested_zone_code": "C1"},
    )
    app = ctx["application"]
    rejected = validate_success(api.reject_application(app["id"], OFFICER), 200)
    assert rejected["status"] == "REJECTED"

    ledger = get_application_fee_assessments(app["id"])
    assert fee_sum(ledger) == 0.00, f"net application ledger must be 0, got {fee_sum(ledger)}"
    reversals = assessments_of_kind(ledger, "REVERSAL")
    assert len(reversals) == 1 and reversals[0]["amount"] == -270.00, reversals


def test_transfer_cancel_zeroes_transfer_fee(api):
    """PRD §3.9: "A transfer in `REQUESTED` or `APPROVED` may be cancelled — by an
    `Applicant` or `LicensingOfficer`, or as the cascade from a license revocation
    — driving it to `CANCELLED` and setting its `transfer_fee` to zero."

    Design: Difficulty/compensating_invariant/transfer_cancel_zeroes_transfer_fee_quantity
    """
    ctx = setup_active_license_with_transfer(risk_tier="HIGH")
    tr = ctx["transfer"]
    seller_h = ctx["seller_headers"]
    cancelled = validate_success(api.cancel_transfer(tr["id"], seller_h), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["transfer_fee"] == 0, cancelled["transfer_fee"]


def test_occ_correct_version_completes_transfer(api):
    """PRD §2.7: "The completion request must carry `expected_license_version`, a
    non-optional field holding the `version` of the target license that the client
    last observed. If `expected_license_version` does not equal the license's
    current `version`, the completion is rejected with `ERR_STALE_VERSION` (HTTP
    412)."
    PRD §3.9: "On completion the license's `business_id` is reassigned to
    `to_business_id` (only the holding business moves; the owner-of-record name is
    not copied)".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_completes_transfer
    """
    ctx = setup_approved_transfer(risk_tier="MEDIUM")
    completed = validate_success(api.complete_transfer(
        ctx["transfer"]["id"],
        complete_transfer_payload(ctx["license_version"]), OFFICER), 200)
    assert completed["status"] == "COMPLETED"
    lic_after = get_success_data(api.get_license(ctx["license"]["id"], OFFICER))
    assert lic_after["business_id"] == ctx["buyer"]["id"], lic_after["business_id"]


def test_occ_stale_license_version_rejected(api):
    """PRD §2.7: "If `expected_license_version` does not equal the license's
    current `version`, the completion is rejected with `ERR_STALE_VERSION` (HTTP
    412). This rejection fires whenever another writer has advanced the license's
    version since the client read it — for instance, the license was renewed, or a
    competing transfer against the same license already completed — so the current
    writer's reassignment would clobber newer state."

    Design: Corner/errors/occ_stale_license_version_on_complete
    """
    # Approve transfer at version V, then renew the license (version advances), then
    # complete with the stale V -> ERR_STALE_VERSION.
    ctx = setup_active_license_with_transfer(risk_tier="MEDIUM")
    lic = ctx["license"]
    seller_h = ctx["seller_headers"]
    tr = ctx["transfer"]
    # Snapshot the stale version before approval/renewal mutate it.
    stale_v = get_success_data(api.get_license(lic["id"], OFFICER))["version"]
    get_success_data(api.approve_transfer(tr["id"], OFFICER))
    # Renewal within window advances License.version, making stale_v stale.
    set_clock("2027-05-15T00:00:00Z")
    get_success_data(api.renew_license(lic["id"], seller_h))

    res = api.complete_transfer(tr["id"], complete_transfer_payload(stale_v), OFFICER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
