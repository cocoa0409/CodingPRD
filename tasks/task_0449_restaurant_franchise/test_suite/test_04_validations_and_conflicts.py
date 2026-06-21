"""Cross-entity state gates, validation-precedence conflicts, resource overlap, and
temporal/business validations.

Covers the cross_entity_state_dependency, priority_pair_validation_conflict, and
resource_temporal_overlap difficulty instances plus the validations-section corner
instances. Precedence assertions rely on the explicit ordering PRD §2.9 states.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    make_franchisee_headers,
    create_sales_report_payload,
    create_vendor_authorization_payload,
    assign_territory_payload,
    transfer_agreement_payload,
    renew_agreement_payload,
    setup_brand_franchisee_territory,
    setup_open_unit,
    setup_renewal_pending_agreement,
    create_unit,
    open_unit,
    create_franchisee,
    approve_franchisee,
    create_territory,
    create_executed_agreement,
    create_accepted_sales_report,
    create_issued_statement,
    create_in_progress_audit,
    finalize_audit,
    create_development_schedule,
    close_period,
)
from test_helpers.factories import create_vendor_payload

FRANCHISOR = TEST_USERS["franchisor_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: cross_entity_state_dependency / unit_open_requires_territory_assigned
# ═══════════════════════════════════════════════════════════════════════════
def test_open_unit_with_unassigned_territory_rejected():
    """PRD §3.5: "the unit's territory_id must reference a territory whose status is
    ASSIGNED and whose assigned_franchisee_id equals the unit's franchisee (else
    ERR_TERRITORY_NOT_HELD)."

    Design: Difficulty/cross_entity_state_dependency/unit_open_requires_territory_assigned_to_franchisee
    """
    brand, fz, terr = setup_brand_franchisee_territory(
        owner_user_id="u_th", territory_code="TH"
    )
    # Create a SECOND, never-assigned (AVAILABLE) territory and a unit in it.
    avail_terr = create_territory(brand["id"], code="THX")
    unit = create_unit(fz["id"], avail_terr["id"])
    resp = api_client.open_unit(unit["id"], FRANCHISOR)
    validate_error(resp, ApiErrorId.ERR_TERRITORY_NOT_HELD.value)
    refreshed = get_success_data(api_client.get_unit(unit["id"], FRANCHISOR))
    assert refreshed["operational_status"] == "PLANNED"


def test_open_unit_in_assigned_territory_succeeds():
    """PRD §3.5: "the unit's territory_id must reference a territory whose status is
    ASSIGNED and whose assigned_franchisee_id equals the unit's franchisee."

    Design: Difficulty/cross_entity_state_dependency/unit_open_requires_territory_assigned_to_franchisee
    """
    brand, fz, terr = setup_brand_franchisee_territory(
        owner_user_id="u_th2", territory_code="TH2"
    )
    unit = create_unit(fz["id"], terr["id"])  # terr is ASSIGNED to fz
    opened = open_unit(unit["id"], "u_th2")
    assert opened["operational_status"] == "OPEN"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: cross_entity_state_dependency / audit_start_requires_unit_open
# ═══════════════════════════════════════════════════════════════════════════
def test_start_audit_on_planned_unit_rejected():
    """PRD §3.7: "Starting an audit (SCHEDULED → IN_PROGRESS) requires the audit to be
    SCHEDULED (else ERR_INVALID_STATE) and the target unit to be operationally OPEN
    (else ERR_UNIT_NOT_OPEN)."

    Design: Difficulty/cross_entity_state_dependency/audit_start_requires_unit_operational_open
    """
    brand, fz, terr = setup_brand_franchisee_territory(
        owner_user_id="u_uno", territory_code="UNO"
    )
    unit = create_unit(fz["id"], terr["id"])  # never opened → PLANNED
    audit = get_success_data(
        api_client.create_audit({"unit_id": unit["id"]}, AUDITOR)
    )
    resp = api_client.start_audit(audit["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_OPEN.value)
    refreshed = get_success_data(api_client.get_audit(audit["id"], AUDITOR))
    assert refreshed["status"] == "SCHEDULED"


def test_start_audit_on_open_unit_succeeds():
    """PRD §3.7: "Starting an audit (SCHEDULED → IN_PROGRESS) requires the audit to be
    SCHEDULED (else ERR_INVALID_STATE) and the target unit to be operationally OPEN
    (else ERR_UNIT_NOT_OPEN)."

    Design: Difficulty/cross_entity_state_dependency/audit_start_requires_unit_operational_open
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_uno2", territory_code="UN2")
    audit = get_success_data(
        api_client.create_audit({"unit_id": unit["id"]}, AUDITOR)
    )
    started = validate_success(
        api_client.start_audit(audit["id"], AUDITOR), expected_status=200
    )
    assert started["status"] == "IN_PROGRESS"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: priority_pair_validation_conflict / transfer_state_vs_obligations
# ═══════════════════════════════════════════════════════════════════════════
def test_transfer_on_executed_agreement_reports_invalid_state_over_obligations():
    """PRD §2.9: "then the target's state validity for the requested transition
    (ERR_INVALID_STATE). Business-rule checks specific to each operation are evaluated
    after those five universal gates."
    PRD §3.3: "Transferring the agreement moves it RENEWAL_PENDING → TRANSFERRED. It
    requires the agreement to be RENEWAL_PENDING (else ERR_INVALID_STATE)."

    Design: Difficulty/priority_pair_validation_conflict/agreement_transfer_state_vs_outstanding_obligations
    """
    # Seller franchisee is ACTIVE with an OPEN unit and an OVERDUE statement, but the
    # agreement is only EXECUTED (never begun renewal). Transfer therefore fails the
    # state gate (universal, evaluated first) before the obligations business rule.
    brand, seller, terr = setup_brand_franchisee_territory(
        owner_user_id="u_pp1", territory_code="PP1"
    )
    buyer = create_franchisee(
        brand["id"], owner_user_id="u_buyer1", is_existing_operator=True
    )
    approve_franchisee(buyer["id"])
    unit = create_unit(seller["id"], terr["id"])
    open_unit(unit["id"], "u_pp1")
    agreement = create_executed_agreement(seller["id"], 5)  # stays EXECUTED
    create_accepted_sales_report(unit["id"], 0, 1_000_000)
    statement = create_issued_statement(unit["id"], 0)
    close_period(brand["id"])
    close_period(brand["id"])  # drive the statement OVERDUE
    overdue = get_success_data(api_client.get_royalty_statement(statement["id"], CLERK))
    assert overdue["status"] == "OVERDUE"  # obligation precondition is genuinely present
    resp = api_client.transfer_agreement(
        agreement["id"], transfer_agreement_payload(buyer["id"]), FRANCHISOR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = get_success_data(api_client.get_agreement(agreement["id"], FRANCHISOR))
    assert refreshed["status"] == "EXECUTED", "unchanged"


def test_transfer_state_error_is_not_obligations_error():
    """PRD §2.9: "Business-rule checks specific to each operation are evaluated after
    those five universal gates."
    PRD §3.3: "It requires the agreement to be RENEWAL_PENDING (else
    ERR_INVALID_STATE)."

    Design: Difficulty/priority_pair_validation_conflict/agreement_transfer_state_vs_outstanding_obligations
    """
    brand, seller, terr = setup_brand_franchisee_territory(
        owner_user_id="u_pp1b", territory_code="P1B"
    )
    buyer = create_franchisee(
        brand["id"], owner_user_id="u_buyer1b", is_existing_operator=True
    )
    approve_franchisee(buyer["id"])
    unit = create_unit(seller["id"], terr["id"])
    open_unit(unit["id"], "u_pp1b")
    agreement = create_executed_agreement(seller["id"], 5)
    create_accepted_sales_report(unit["id"], 0, 1_000_000)
    create_issued_statement(unit["id"], 0)
    close_period(brand["id"])
    close_period(brand["id"])  # statement now OVERDUE → obligation precondition present
    resp = api_client.transfer_agreement(
        agreement["id"], transfer_agreement_payload(buyer["id"]), FRANCHISOR
    )
    # validate_error asserts the winning error is exactly ERR_INVALID_STATE (the p5
    # state gate), proving the lower-priority ERR_OUTSTANDING_OBLIGATIONS did not win.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: priority_pair_validation_conflict / owner_vs_vendor_not_approved
# ═══════════════════════════════════════════════════════════════════════════
def test_authorization_by_non_owner_reports_ownership_over_vendor_approval():
    """PRD §2.9: "then franchisee resource-ownership (ERR_NOT_RESOURCE_OWNER), then the
    target's state validity for the requested transition (ERR_INVALID_STATE). Business-
    rule checks specific to each operation are evaluated after those five universal
    gates."
    PRD §2.1: "an attempt to act on another franchisee's resources is rejected with
    ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/vendor_authorization_owner_vs_vendor_not_approved
    """
    # F1 owns the unit (owner u_f1). A PENDING (unapproved) vendor exists. An intruder
    # franchisee principal u_intruder (not the unit owner) attempts the authorization:
    # ownership gate (universal #4) fires before the vendor-approval business rule.
    brand, f1, terr, unit = setup_open_unit(owner_user_id="u_f1", territory_code="OW")
    vendor = get_success_data(
        api_client.create_vendor(create_vendor_payload(brand["id"], name="Pending Co"), AUDITOR)
    )  # stays PENDING
    resp = api_client.create_vendor_authorization(
        create_vendor_authorization_payload(
            unit["id"], vendor["id"], qualifying_purchase_cents=0
        ),
        make_franchisee_headers("u_intruder"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_authorization_ownership_error_is_not_vendor_approval_error():
    """PRD §2.9: "then franchisee resource-ownership (ERR_NOT_RESOURCE_OWNER) ...
    Business-rule checks specific to each operation are evaluated after those five
    universal gates."
    PRD §3.10: "An authorization may only reference a vendor whose approval_status is
    APPROVED; referencing a vendor that is not approved is rejected with
    ERR_VENDOR_NOT_APPROVED."

    Design: Difficulty/priority_pair_validation_conflict/vendor_authorization_owner_vs_vendor_not_approved
    """
    brand, f1, terr, unit = setup_open_unit(owner_user_id="u_f1b", territory_code="OWB")
    vendor = get_success_data(
        api_client.create_vendor(create_vendor_payload(brand["id"], name="Pending"), AUDITOR)
    )
    resp = api_client.create_vendor_authorization(
        create_vendor_authorization_payload(unit["id"], vendor["id"]),
        make_franchisee_headers("u_intruder2"),
    )
    # validate_error asserts the winning error is exactly ERR_NOT_RESOURCE_OWNER (the p4
    # ownership gate), proving the lower-priority ERR_VENDOR_NOT_APPROVED did not win.
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: resource_temporal_overlap / territory_exclusivity_single_holder
# ═══════════════════════════════════════════════════════════════════════════
def test_assign_already_assigned_territory_conflicts():
    """PRD §3.1: "Assigning a territory to a franchisee moves its status to ASSIGNED and
    records the holder in assigned_franchisee_id; attempting to assign a territory that
    is already ASSIGNED to another franchisee is likewise rejected with
    ERR_TERRITORY_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/territory_exclusivity_single_holder
    """
    brand, f1, terr = setup_brand_franchisee_territory(
        owner_user_id="u_excl1", territory_code="EX"
    )  # terr already ASSIGNED to f1
    f2 = create_franchisee(brand["id"], owner_user_id="u_excl2", legal_name="F2")
    approve_franchisee(f2["id"])
    resp = api_client.assign_territory(
        terr["id"], assign_territory_payload(f2["id"]), FRANCHISOR
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_CONFLICT.value)
    refreshed = get_success_data(api_client.get_territory(terr["id"], FRANCHISOR))
    assert refreshed["assigned_franchisee_id"] == f1["id"], "original grant intact"


def test_duplicate_territory_code_in_brand_conflicts():
    """PRD §3.1: "A territory's code must be unique within its brand; an attempt to
    create a second territory with a code already used in that brand is rejected with
    ERR_TERRITORY_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/territory_exclusivity_single_holder
    """
    brand, f1, terr = setup_brand_franchisee_territory(
        owner_user_id="u_excl3", territory_code="DUP"
    )
    resp = api_client.create_territory(
        {"brand_id": brand["id"], "code": "DUP", "name": "Another"}, FRANCHISOR
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_CONFLICT.value)


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: resource_temporal_overlap / audit_active_lifetime_capacity_one
# ═══════════════════════════════════════════════════════════════════════════
def test_second_active_audit_on_unit_conflicts():
    """PRD §3.7: "A unit may carry at most one audit in an active phase at a time: if
    the unit already has an audit in SCHEDULED or IN_PROGRESS, scheduling another is
    rejected with ERR_AUDIT_IN_PROGRESS."

    Design: Difficulty/resource_temporal_overlap/audit_active_lifetime_capacity_one_per_unit
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_cap1", territory_code="CP1")
    get_success_data(api_client.create_audit({"unit_id": unit["id"]}, AUDITOR))  # SCHEDULED
    resp = api_client.create_audit({"unit_id": unit["id"]}, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_AUDIT_IN_PROGRESS.value)


def test_second_audit_blocked_while_first_in_progress():
    """PRD §3.7: "A unit may carry at most one audit in an active phase at a time: if
    the unit already has an audit in SCHEDULED or IN_PROGRESS, scheduling another is
    rejected with ERR_AUDIT_IN_PROGRESS."

    Design: Difficulty/resource_temporal_overlap/audit_active_lifetime_capacity_one_per_unit
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_cap2", territory_code="CP2")
    audit = get_success_data(api_client.create_audit({"unit_id": unit["id"]}, AUDITOR))
    get_success_data(api_client.start_audit(audit["id"], AUDITOR))  # now IN_PROGRESS
    resp = api_client.create_audit({"unit_id": unit["id"]}, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_AUDIT_IN_PROGRESS.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: validations / sales_report_for_closed_period_rejected
# ═══════════════════════════════════════════════════════════════════════════
def test_sales_report_for_closed_period_rejected():
    """PRD §3.8: "A report's period_index must equal the brand's current_period_index —
    a closed period cannot be reported against — and a mismatch is rejected with
    ERR_PERIOD_CLOSED."

    Design: Corner/validations/sales_report_for_closed_period_rejected
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_pc", territory_code="PC")
    close_period(brand["id"])  # current_period_index → 1
    resp = api_client.create_sales_report(
        create_sales_report_payload(unit["id"], 0, 100_000), FRANCHISOR
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: validations / vendor_authorization_unapproved_vendor_rejected
# ═══════════════════════════════════════════════════════════════════════════
def test_authorize_unapproved_vendor_rejected():
    """PRD §3.10: "An authorization may only reference a vendor whose approval_status is
    APPROVED; referencing a vendor that is not approved is rejected with
    ERR_VENDOR_NOT_APPROVED."

    Design: Corner/validations/vendor_authorization_unapproved_vendor_rejected
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_vna", territory_code="VNA")
    vendor = get_success_data(
        api_client.create_vendor(create_vendor_payload(brand["id"]), AUDITOR)
    )  # PENDING
    resp = api_client.create_vendor_authorization(
        create_vendor_authorization_payload(unit["id"], vendor["id"]), FRANCHISOR
    )
    validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_APPROVED.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: validations / open_unit_for_unapproved_franchisee_rejected
# ═══════════════════════════════════════════════════════════════════════════
def test_open_unit_for_applicant_franchisee_rejected():
    """PRD §3.5: "Opening a planned unit ... requires three conditions: the unit must
    currently be operationally PLANNED (else ERR_INVALID_STATE); the owning franchisee
    must be in APPROVED or ACTIVE status (else ERR_FRANCHISEE_NOT_APPROVED)."

    Design: Corner/validations/open_unit_for_unapproved_franchisee_rejected
    """
    brand = get_success_data(api_client.create_brand({"name": "B"}, FRANCHISOR))
    terr = create_territory(brand["id"], code="UFA")
    franchisee = create_franchisee(brand["id"], owner_user_id="u_ufa")  # APPLICANT
    unit = create_unit(franchisee["id"], terr["id"])
    resp = api_client.open_unit(unit["id"], FRANCHISOR)
    validate_error(resp, ApiErrorId.ERR_FRANCHISEE_NOT_APPROVED.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: validations / begin_renewal_before_window_rejected
# ═══════════════════════════════════════════════════════════════════════════
def test_begin_renewal_before_window_rejected():
    """PRD §3.3: "Beginning renewal moves an executed agreement EXECUTED →
    RENEWAL_PENDING; it requires the agreement to be EXECUTED (else ERR_INVALID_STATE)
    and the renewal window to be open, meaning the brand's current_period_index is at
    least the agreement's term_end_period_index minus one. If the renewal window has not
    yet opened, the request is rejected with ERR_RENEWAL_WINDOW_CLOSED."

    Design: Corner/validations/begin_renewal_before_window_rejected
    """
    brand = get_success_data(api_client.create_brand({"name": "B"}, FRANCHISOR))
    franchisee = create_franchisee(brand["id"], owner_user_id="u_rwc")
    approve_franchisee(franchisee["id"])
    agreement = create_executed_agreement(franchisee["id"], 5)  # term_end 5, current 0
    resp = api_client.begin_renewal(agreement["id"], FRANCHISOR)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: validations / declare_breach_before_deadline_rejected
# ═══════════════════════════════════════════════════════════════════════════
def test_declare_breach_before_deadline_rejected():
    """PRD §3.4: "From BEHIND, the franchisor may declare a breach, moving the schedule
    BEHIND → BREACHED; this requires the schedule to be BEHIND (else ERR_INVALID_STATE)
    and the brand's current_period_index to be strictly greater than
    deadline_period_index (else ERR_DEADLINE_NOT_PASSED)."

    Design: Corner/validations/declare_breach_before_deadline_rejected
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_dnp", territory_code="DNP")
    schedule = create_development_schedule(fz["id"], required_units=2, deadline_period_index=2)
    close_period(brand["id"])  # current 1
    close_period(brand["id"])  # current 2 == deadline → schedule auto BEHIND
    behind = get_success_data(
        api_client.get_development_schedule(schedule["id"], FRANCHISOR)
    )
    assert behind["status"] == "BEHIND"
    resp = api_client.declare_breach(schedule["id"], FRANCHISOR)
    validate_error(resp, ApiErrorId.ERR_DEADLINE_NOT_PASSED.value)  # current 2 not > 2


# ═══════════════════════════════════════════════════════════════════════════
# Corner: validations / negative_gross_sales_rejected (discounts > gross)
# ═══════════════════════════════════════════════════════════════════════════
def test_discounts_exceeding_gross_rejected():
    """PRD §2.9: "Field-level structural validation — non-negative amounts, discounts
    not exceeding gross sales, audit section scores within range, and a positive
    required-unit count — surfaces as ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/validations/negative_gross_sales_rejected
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_neg", territory_code="NEG")
    resp = api_client.create_sales_report(
        create_sales_report_payload(unit["id"], 0, 50, discounts_cents=100), FRANCHISOR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: validations / terminate_franchisee_with_open_units_rejected
# ═══════════════════════════════════════════════════════════════════════════
def test_terminate_franchisee_with_open_units_rejected():
    """PRD §3.2: "Termination is blocked under two conditions: if any unit of the
    franchisee is still in operational OPEN, the request is rejected with
    ERR_FRANCHISEE_HAS_OPEN_UNITS."

    Design: Corner/validations/terminate_franchisee_with_open_units_rejected
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_hou", territory_code="HOU")
    resp = api_client.terminate_franchisee(fz["id"], FRANCHISOR)
    validate_error(resp, ApiErrorId.ERR_FRANCHISEE_HAS_OPEN_UNITS.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: validations / reinstate_without_remediation_audit_rejected
# ═══════════════════════════════════════════════════════════════════════════
def test_reinstate_without_remediation_audit_rejected():
    """PRD §3.6: "Reinstatement requires the unit to currently be SUSPENDED (else
    ERR_INVALID_STATE) and demands evidence of completed remediation: there must exist a
    finalized audit for the unit whose grade is not FAIL, created after the audit that
    caused the suspension. If no such qualifying remediation audit exists, reinstatement
    is rejected with ERR_REMEDIATION_INCOMPLETE."

    Design: Corner/validations/reinstate_without_remediation_audit_rejected
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_rem", territory_code="REM")
    audit = create_in_progress_audit(unit["id"])
    finalize_audit(audit["id"], 30, 30, 30, 30)  # FAIL → unit SUSPENDED
    resp = api_client.reinstate_unit(unit["id"], FRANCHISOR)
    validate_error(resp, ApiErrorId.ERR_REMEDIATION_INCOMPLETE.value)
    refreshed = get_success_data(api_client.get_unit(unit["id"], FRANCHISOR))
    assert refreshed["compliance_status"] == "SUSPENDED"


# ═══════════════════════════════════════════════════════════════════════════
# Corner: validations / renew_with_suspended_unit_compliance_block
# ═══════════════════════════════════════════════════════════════════════════
def test_renew_with_suspended_unit_compliance_block():
    """PRD §3.3: "Renewing the agreement moves it RENEWAL_PENDING → RENEWED. It requires
    the agreement to be RENEWAL_PENDING (else ERR_INVALID_STATE), that none of the
    franchisee's units is in compliance SUSPENDED (else ERR_COMPLIANCE_BLOCK)."

    Design: Corner/validations/renew_with_suspended_unit_compliance_block
    """
    # ACTIVE franchisee with an OPEN+SUSPENDED unit, an EXECUTED agreement at term_end 1,
    # advanced one period and begun renewal → RENEWAL_PENDING; the SUSPENDED unit blocks
    # the renew.
    brand, fz, terr, agreement, unit = setup_renewal_pending_agreement(
        owner_user_id="u_cb", territory_code="CB", with_open_unit=True
    )
    audit = create_in_progress_audit(unit["id"])
    finalize_audit(audit["id"], 30, 30, 30, 30)  # FAIL → unit SUSPENDED
    suspended = get_success_data(api_client.get_unit(unit["id"], FRANCHISOR))
    assert suspended["compliance_status"] == "SUSPENDED"
    resp = api_client.renew_agreement(
        agreement["id"], renew_agreement_payload("2027.1", 6), FRANCHISOR
    )
    validate_error(resp, ApiErrorId.ERR_COMPLIANCE_BLOCK.value)
