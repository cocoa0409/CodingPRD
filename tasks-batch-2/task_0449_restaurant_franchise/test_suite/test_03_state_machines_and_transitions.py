"""Lifecycle transitions and their side effects across the franchise entities.

Covers the agreement RENEWAL_PENDING branch-to-terminal difficulty instance, the
vendor-revoke depth-2 cascade, the net-sales zero boundary, and the state-machine
corner instances (initial states, invalid transitions, terminal lockdown, valid
side-effecting transitions, payment lifecycle, lifetime-net-sales reconciliation,
immediate consistency on first unit open).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    create_sales_report_payload,
    renew_agreement_payload,
    payment_payload,
    setup_open_unit,
    setup_brand_franchisee_territory,
    setup_renewal_pending_agreement,
    setup_issued_statement,
    setup_finalized_audit,
    create_unit,
    open_unit,
    create_approved_vendor,
    create_authorization,
    create_accepted_sales_report,
    create_issued_statement,
    write_off_payload,
    get_brand_version,
    close_period,
)

FRANCHISOR = TEST_USERS["franchisor_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: non_linear_state_machine / agreement_renewal_pending_branches
# ═══════════════════════════════════════════════════════════════════════════
def test_decline_renewal_terminates_and_releases_territory():
    """PRD §3.3: "Declining renewal moves the agreement RENEWAL_PENDING → TERMINATED. It
    requires only that the agreement be RENEWAL_PENDING (else ERR_INVALID_STATE). On
    success every territory held by the franchisee is released — its
    assigned_franchisee_id reset to null and its status returned to AVAILABLE."

    Design: Difficulty/non_linear_state_machine/agreement_renewal_pending_branches_to_three_terminals
    """
    brand, fz, terr, agreement, _ = setup_renewal_pending_agreement(
        owner_user_id="u_dec", territory_code="DEC"
    )
    data = validate_success(
        api_client.decline_renewal(agreement["id"], FRANCHISOR), expected_status=200
    )
    assert data["status"] == "TERMINATED"
    refreshed_terr = get_success_data(api_client.get_territory(terr["id"], FRANCHISOR))
    assert refreshed_terr["status"] == "AVAILABLE"
    assert refreshed_terr["assigned_franchisee_id"] is None


def test_decline_renewal_creates_no_successor():
    """PRD §3.3: "Declining renewal moves the agreement RENEWAL_PENDING → TERMINATED. It
    requires only that the agreement be RENEWAL_PENDING (else ERR_INVALID_STATE)."
    PRD §3.3: "The successor_agreement_id field begins null and is set on the prior
    agreement when it is renewed or transferred to point at the agreement that
    supersedes it."

    Design: Difficulty/non_linear_state_machine/agreement_renewal_pending_branches_to_three_terminals
    """
    brand, fz, terr, agreement, _ = setup_renewal_pending_agreement(
        owner_user_id="u_dec2", territory_code="DC2"
    )
    data = validate_success(
        api_client.decline_renewal(agreement["id"], FRANCHISOR), expected_status=200
    )
    assert data["status"] == "TERMINATED"
    assert data["successor_agreement_id"] is None, (
        "decline creates no successor, unlike RENEW/TRANSFER"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: transitive_cascade / vendor_revoke_disables_authorizations_depth2
# ═══════════════════════════════════════════════════════════════════════════
def test_vendor_revoke_disables_active_authorization():
    """PRD §3.10: "A compliance auditor may approve a vendor (approval_status PENDING →
    APPROVED) or revoke it (approval_status → REVOKED). Revoking a vendor cascades:
    every VendorAuthorization for that vendor currently in ACTIVE status is set to
    DISABLED."

    Design: Difficulty/transitive_cascade/vendor_revoke_disables_authorizations_depth2
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_rev", territory_code="REV")
    vendor = create_approved_vendor(brand["id"])
    auth = create_authorization(unit["id"], vendor["id"], qualifying_purchase_cents=500_000)
    data = validate_success(
        api_client.revoke_vendor(vendor["id"], AUDITOR), expected_status=200
    )
    assert data["approval_status"] == "REVOKED"  # hop 1
    refreshed_auth = get_success_data(
        api_client.get_vendor_authorization(auth["id"], FRANCHISOR)
    )
    assert refreshed_auth["status"] == "DISABLED"  # hop 2, caused by the revocation


def test_vendor_revoke_sets_approval_status_revoked():
    """PRD §3.10: "A compliance auditor may approve a vendor (approval_status PENDING →
    APPROVED) or revoke it (approval_status → REVOKED)."

    Design: Difficulty/transitive_cascade/vendor_revoke_disables_authorizations_depth2
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_rev2", territory_code="RV2")
    vendor = create_approved_vendor(brand["id"])
    assert vendor["approval_status"] == "APPROVED"
    revoked = validate_success(
        api_client.revoke_vendor(vendor["id"], AUDITOR), expected_status=200
    )
    assert revoked["approval_status"] == "REVOKED"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: boundary_precision_check / net_sales_zero_when_discounts_equal_gross
# ═══════════════════════════════════════════════════════════════════════════
def test_net_sales_floors_at_zero_when_discounts_equal_gross():
    """PRD §3.8: "On ingestion the system computes net_sales_cents as the gross sales
    minus the discounts, floored at 0 so it is never negative, and the report enters
    status POLLED."

    Design: Difficulty/boundary_precision_check/net_sales_zero_when_discounts_equal_gross
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_zns", territory_code="ZNS")
    data = validate_success(
        api_client.create_sales_report(
            create_sales_report_payload(unit["id"], 0, 250_000, discounts_cents=250_000),
            FRANCHISOR,
        ),
        expected_status=201,
    )
    assert data["net_sales_cents"] == 0, "max(0, 250000 - 250000)"
    assert data["status"] == "POLLED"


def test_net_sales_positive_when_discounts_below_gross():
    """PRD §3.8: "On ingestion the system computes net_sales_cents as the gross sales
    minus the discounts, floored at 0 so it is never negative."

    Design: Difficulty/boundary_precision_check/net_sales_zero_when_discounts_equal_gross
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_zns2", territory_code="ZN2")
    data = validate_success(
        api_client.create_sales_report(
            create_sales_report_payload(unit["id"], 0, 250_000, discounts_cents=249_999),
            FRANCHISOR,
        ),
        expected_status=201,
    )
    assert data["net_sales_cents"] == 1, "250000 - 249999 = 1, just above the floor"


# ═══════════════════════════════════════════════════════════════════════════
# Corner: state_machines / newly_created_unit_initial_states
# ═══════════════════════════════════════════════════════════════════════════
def test_new_unit_initial_states():
    """PRD §3.5: "On creation, operational_status is PLANNED and compliance_status is
    GOOD_STANDING."

    Design: Corner/state_machines/newly_created_unit_initial_states
    """
    brand, fz, terr = setup_brand_franchisee_territory(
        owner_user_id="u_init", territory_code="INI"
    )
    unit = validate_success(
        api_client.create_unit(
            {"franchisee_id": fz["id"], "territory_id": terr["id"], "address": "U1"},
            FRANCHISOR,
        ),
        expected_status=201,
    )
    assert unit["operational_status"] == "PLANNED"
    assert unit["compliance_status"] == "GOOD_STANDING"


# ═══════════════════════════════════════════════════════════════════════════
# Corner: state_machines / approve_already_approved_franchisee_invalid_state
# ═══════════════════════════════════════════════════════════════════════════
def test_approve_already_approved_franchisee_invalid_state():
    """PRD §3.2: "Approval by a franchisor moves the franchisee from APPLICANT to
    APPROVED; approving a franchisee that is not currently APPLICANT is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/approve_already_approved_franchisee_invalid_state
    """
    brand, fz, terr = setup_brand_franchisee_territory(
        owner_user_id="u_app", territory_code="APP"
    )  # franchisee already APPROVED by the fixture
    resp = api_client.approve_franchisee(fz["id"], FRANCHISOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: state_machines / issue_royalty_statement_without_accepted_sales_basis
# ═══════════════════════════════════════════════════════════════════════════
def test_issue_statement_without_accepted_basis_rejected():
    """PRD §3.8: "Issuing a statement (a finance-clerk action) moves it DRAFT → ISSUED
    and requires the statement to be DRAFT (else ERR_INVALID_STATE) and at least one
    ACCEPTED sales report to exist for the statement's unit and period (else
    ERR_NO_SALES_BASIS)."

    Design: Corner/state_machines/issue_royalty_statement_without_accepted_sales_basis
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_nob", territory_code="NOB")
    # A POLLED-only report exists (never accepted), so there is no ACCEPTED basis.
    get_success_data(
        api_client.create_sales_report(
            create_sales_report_payload(unit["id"], 0, 500_000), FRANCHISOR
        )
    )
    statement = get_success_data(
        api_client.create_royalty_statement(
            {"unit_id": unit["id"], "period_index": 0}, CLERK
        )
    )
    resp = api_client.issue_royalty_statement(statement["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_NO_SALES_BASIS.value)
    refreshed = get_success_data(api_client.get_royalty_statement(statement["id"], CLERK))
    assert refreshed["status"] == "DRAFT"


# ═══════════════════════════════════════════════════════════════════════════
# Corner: state_machines / write_off_from_terminal_written_off_invalid_state
# ═══════════════════════════════════════════════════════════════════════════
def test_second_write_off_on_written_off_statement_invalid_state():
    """PRD §3.8: "A statement progresses DRAFT → ISSUED → PAID, with OVERDUE and a
    terminal WRITTEN_OFF as additional fates."
    PRD §2.9: "then the target's state validity for the requested transition
    (ERR_INVALID_STATE)."

    Design: Corner/state_machines/write_off_from_terminal_written_off_invalid_state
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_woff", territory_code="WOF")
    create_accepted_sales_report(unit["id"], 0, 1_000_000)
    statement = create_issued_statement(unit["id"], 0)
    for _ in range(2):
        close_period(brand["id"])  # drive OVERDUE
    brand_v = get_brand_version(brand["id"])
    validate_success(
        api_client.write_off_royalty_statement(
            statement["id"], write_off_payload(brand_v), CLERK
        ),
        expected_status=200,
    )
    brand_v2 = get_brand_version(brand["id"])
    resp = api_client.write_off_royalty_statement(
        statement["id"], write_off_payload(brand_v2), CLERK
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: state_machines / open_remediation_on_pass_audit_no_remediation_needed
# ═══════════════════════════════════════════════════════════════════════════
def test_open_remediation_on_pass_audit_rejected():
    """PRD §3.7: "this requires the audit to be FINALIZED (else ERR_INVALID_STATE) and
    its grade to be CONDITIONAL or FAIL (else ERR_NO_REMEDIATION_NEEDED, since a passing
    audit needs no remediation)."

    Design: Corner/state_machines/open_remediation_on_pass_audit_no_remediation_needed
    """
    brand, fz, terr, unit, audit = setup_finalized_audit(
        95, 95, 95, 95, owner_user_id="u_orem", territory_code="ORM"
    )  # grade PASS
    resp = api_client.open_remediation(audit["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_NO_REMEDIATION_NEEDED.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: state_machines / agreement_renew_creates_executed_successor
# ═══════════════════════════════════════════════════════════════════════════
def test_renew_creates_executed_successor_and_links_it():
    """PRD §3.3: "On success the system creates a successor FranchiseAgreement in
    EXECUTED status for the same franchisee, with its fdd_version set to new_fdd_version
    and its term_end_period_index set to new_term_end_period_index, and sets the original
    agreement's successor_agreement_id to the new agreement's id."

    Design: Corner/state_machines/agreement_renew_creates_executed_successor
    """
    brand, fz, terr, agreement, _ = setup_renewal_pending_agreement(
        owner_user_id="u_renew", territory_code="RNW"
    )  # no SUSPENDED units → renewal allowed
    data = validate_success(
        api_client.renew_agreement(
            agreement["id"], renew_agreement_payload("2027.1", 6), FRANCHISOR
        ),
        expected_status=200,
    )
    assert data["status"] == "RENEWED"
    assert data["successor_agreement_id"] is not None
    successor = get_success_data(
        api_client.get_agreement(data["successor_agreement_id"], FRANCHISOR)
    )
    assert successor["status"] == "EXECUTED"
    assert successor["franchisee_id"] == fz["id"]
    assert successor["fdd_version"] == "2027.1"
    assert successor["term_end_period_index"] == 6


# ═══════════════════════════════════════════════════════════════════════════
# Corner: endpoints / payment_partial_then_full_marks_paid
# ═══════════════════════════════════════════════════════════════════════════
def test_partial_then_full_payment_marks_paid():
    """PRD §3.8: "If the cumulative amount_paid_cents reaches or exceeds total_due_cents,
    the statement moves to PAID; otherwise the statement stays in whatever status it was
    in (still ISSUED or still OVERDUE) with the partial payment recorded."

    Design: Corner/endpoints/payment_partial_then_full_marks_paid
    """
    brand, fz, terr, unit, statement = setup_issued_statement(1_000_000)
    # basis 1000000 → royalty 60000 + ad_fund 20000 = total 80000.
    assert statement["total_due_cents"] == 80000
    partial = validate_success(
        api_client.pay_royalty_statement(
            statement["id"], payment_payload(30000), CLERK
        ),
        expected_status=200,
    )
    assert partial["amount_paid_cents"] == 30000
    assert partial["status"] == "ISSUED", "partial payment leaves it ISSUED"
    full = validate_success(
        api_client.pay_royalty_statement(
            statement["id"], payment_payload(50000), CLERK
        ),
        expected_status=200,
    )
    assert full["amount_paid_cents"] == 80000
    assert full["status"] == "PAID"


# ═══════════════════════════════════════════════════════════════════════════
# Corner: endpoints / sales_report_lifetime_net_sales_reconciliation_on_accept
# ═══════════════════════════════════════════════════════════════════════════
def test_accept_report_reconciles_unit_lifetime_net_sales():
    """PRD §3.8: "The franchisor or a finance clerk accepts a report, moving it POLLED →
    ACCEPTED, which causes the owning unit's lifetime_net_sales_cents to be recomputed as
    the sum of net_sales_cents over all of that unit's accepted reports."

    Design: Corner/endpoints/sales_report_lifetime_net_sales_reconciliation_on_accept
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_life", territory_code="LIF")
    report = get_success_data(
        api_client.create_sales_report(
            create_sales_report_payload(unit["id"], 0, 700_000), FRANCHISOR
        )
    )
    # POLLED report does not count yet.
    before = get_success_data(api_client.get_unit(unit["id"], FRANCHISOR))
    assert before["lifetime_net_sales_cents"] == 0
    accepted = validate_success(
        api_client.accept_sales_report(report["id"], CLERK), expected_status=200
    )
    assert accepted["status"] == "ACCEPTED"
    after = get_success_data(api_client.get_unit(unit["id"], FRANCHISOR))
    assert after["lifetime_net_sales_cents"] == 700_000


# ═══════════════════════════════════════════════════════════════════════════
# Corner: consistency_model / immediate_consistency_unit_open_reflects
# ═══════════════════════════════════════════════════════════════════════════
def test_first_unit_open_immediately_activates_franchisee():
    """PRD §3.5: "Opening a unit triggers two side effects: if the owning franchisee is
    still APPROVED, it is promoted APPROVED → ACTIVE."
    PRD §3.2: "The transition from APPROVED to ACTIVE is automatic and happens the moment
    the franchisee's first unit transitions to operational OPEN — it is never invoked
    directly."

    Design: Corner/consistency_model/immediate_consistency_unit_open_reflects_in_same_response
    """
    brand, fz, terr = setup_brand_franchisee_territory(
        owner_user_id="u_imm", territory_code="IMM"
    )
    unit = create_unit(fz["id"], terr["id"])
    opened = open_unit(unit["id"], "u_imm")  # returns the open() response payload
    assert opened["operational_status"] == "OPEN"
    refreshed_fz = get_success_data(api_client.get_franchisee(fz["id"], FRANCHISOR))
    assert refreshed_fz["status"] == "ACTIVE", "cascaded APPROVED→ACTIVE on first open"
