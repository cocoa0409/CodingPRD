"""Work-order release airworthiness gates and final-acceptance delegation (PRD §3.5, §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_work_order,
    create_approved_source,
    create_process_approval,
    create_released_po,
    create_work_order,
    set_clock,
    setup_fai_submitted,
    setup_wo_in_production,
    get_success_data,
    validate_error,
    validate_success,
)

CM = TEST_USERS["contracts_manager"]
MP = TEST_USERS["manufacturing_planner"]
QI = TEST_USERS["quality_inspector"]
QI2 = TEST_USERS["quality_inspector_2"]
QI9 = TEST_USERS["quality_inspector_9"]
CQR = TEST_USERS["customer_quality_rep"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / wo_release_requires_fai_approved
# ---------------------------------------------------------------------------

def test_wo_release_blocked_until_fai_approved(api):
    """PRD §3.5: "Then the gates: if the order's `flowdown_clauses` contain
    `AS9102_FAI`, an `APPROVED` first-article inspection must exist for the
    order's `part_number` and `part_revision`, failing with `ERR_FAI_REQUIRED`
    otherwise; and for each process named in `special_processes_required`, an
    `ACTIVE` special-process approval must exist for that `process_code`, whose
    window covers the current logical date — `valid_from` at or before it and
    the date before `valid_to` — held by an `APPROVED` source, failing with
    `ERR_PROCESS_NOT_APPROVED` otherwise."

    Design: Difficulty/cross_entity_state_dependency/wo_release_requires_fai_approved
    """
    bundle = create_released_po(
        part_number="P300",
        part_revision="F",
        quantity=1,
        flowdown_clauses=["AS9102_FAI"],
    )
    wo = create_work_order(bundle["po"]["id"], quantity=1)
    # FAI exists for the part+revision but is only SUBMITTED, not APPROVED.
    fai = setup_fai_submitted(part_number="P300", part_revision="F")
    assert fai["status"] == "SUBMITTED"
    resp = api_client.release_work_order(wo["id"], MP)
    validate_error(resp, ApiErrorId.ERR_FAI_REQUIRED.value)


def test_wo_release_succeeds_after_fai_approval(api):
    """PRD §3.5: "Then the gates: if the order's `flowdown_clauses` contain
    `AS9102_FAI`, an `APPROVED` first-article inspection must exist for the
    order's `part_number` and `part_revision`, failing with `ERR_FAI_REQUIRED`
    otherwise; and for each process named in `special_processes_required`, an
    `ACTIVE` special-process approval must exist for that `process_code`, whose
    window covers the current logical date — `valid_from` at or before it and
    the date before `valid_to` — held by an `APPROVED` source, failing with
    `ERR_PROCESS_NOT_APPROVED` otherwise. A clean release moves `PLANNED →
    RELEASED`."

    Design: Difficulty/cross_entity_state_dependency/wo_release_requires_fai_approved
    """
    bundle = create_released_po(
        part_number="P300",
        part_revision="F",
        quantity=1,
        flowdown_clauses=["AS9102_FAI"],
    )
    wo = create_work_order(bundle["po"]["id"], quantity=1)
    fai = setup_fai_submitted(part_number="P300", part_revision="F")
    resp = api_client.release_work_order(wo["id"], MP)
    validate_error(resp, ApiErrorId.ERR_FAI_REQUIRED.value)
    # Approve the FAI, then the release gate clears.
    validate_success(api_client.approve_fai(fai["id"], CQR))
    released = validate_success(api_client.release_work_order(wo["id"], MP))
    assert_work_order(released)
    assert released["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Corner: validations / wo_release_process_gate_missing
# ---------------------------------------------------------------------------

def test_wo_release_process_gate_missing(api):
    """PRD §3.5: "Then the gates: if the order's `flowdown_clauses` contain
    `AS9102_FAI`, an `APPROVED` first-article inspection must exist for the
    order's `part_number` and `part_revision`, failing with `ERR_FAI_REQUIRED`
    otherwise; and for each process named in `special_processes_required`, an
    `ACTIVE` special-process approval must exist for that `process_code`, whose
    window covers the current logical date — `valid_from` at or before it and
    the date before `valid_to` — held by an `APPROVED` source, failing with
    `ERR_PROCESS_NOT_APPROVED` otherwise."

    Design: Corner/validations/wo_release_process_gate_missing
    """
    bundle = create_released_po(quantity=1, requires_special_process=True)
    wo = create_work_order(
        bundle["po"]["id"], quantity=1, special_processes_required=["HEAT_TREAT"]
    )
    resp = api_client.release_work_order(wo["id"], MP)
    validate_error(resp, ApiErrorId.ERR_PROCESS_NOT_APPROVED.value)
    after = get_success_data(api_client.get_work_order(wo["id"], MP))
    assert after["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Corner: validations / wo_release_process_window_expired
# ---------------------------------------------------------------------------

def test_wo_release_process_window_expired(api):
    """PRD §3.5: "Then the gates: if the order's `flowdown_clauses` contain
    `AS9102_FAI`, an `APPROVED` first-article inspection must exist for the
    order's `part_number` and `part_revision`, failing with `ERR_FAI_REQUIRED`
    otherwise; and for each process named in `special_processes_required`, an
    `ACTIVE` special-process approval must exist for that `process_code`, whose
    window covers the current logical date — `valid_from` at or before it and
    the date before `valid_to` — held by an `APPROVED` source, failing with
    `ERR_PROCESS_NOT_APPROVED` otherwise."
    PRD §2.5: "All date- and time-dependent rules read a server-side logical
    clock, never wall-clock time: special-process approval windows, delegation
    windows and the post-revocation cooling-off period, the escape-report
    deadline, monthly rate-audit attribution, annual rebate attribution, and
    the logical timestamps stamped onto resources (`completed_at`,
    `shipped_at`, `submitted_at`, `revoked_at`)."

    Design: Corner/validations/wo_release_process_window_expired
    """
    bundle = create_released_po(quantity=1, requires_special_process=True)
    wo = create_work_order(
        bundle["po"]["id"], quantity=1, special_processes_required=["NDT"]
    )
    source = create_approved_source(approval_scope="SPECIAL_PROCESS")
    create_process_approval(
        source["id"],
        process_code="NDT",
        valid_from="2026-01-01",
        valid_to="2026-06-01",
        cert_reference="NADCAP-3",
    )
    # Default logical clock is 2026-08-01: outside the half-open window
    # [2026-01-01, 2026-06-01), so the gate fails.
    resp = api_client.release_work_order(wo["id"], MP)
    validate_error(resp, ApiErrorId.ERR_PROCESS_NOT_APPROVED.value)
    # Move the clock inside the window: the gate clears.
    set_clock("2026-05-01T00:00:00Z")
    released = validate_success(api_client.release_work_order(wo["id"], MP))
    assert released["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Corner: validations / wo_accept_delegation_gate
# ---------------------------------------------------------------------------

def test_wo_accept_delegation_gate(api):
    """PRD §3.5: "A `CustomerQualityRep` may always accept; that is customer
    source inspection. A `QualityInspector` may accept only under delegated
    authority: an `ACTIVE` delegation must exist whose `po_id` matches the work
    order's parent order, whose `inspector_user_id` equals the caller's
    `X-User-ID`, and whose closed window covers the current logical date —
    `valid_from` at or before it and `valid_to` at or after it — failing with
    `ERR_DELEGATION_REQUIRED` (403) otherwise."

    Design: Corner/validations/wo_accept_delegation_gate
    """
    # PO with DELEGATED_INSPECTION_PERMITTED; WO completed to
    # FINAL_INSPECTION (complete, but not yet accepted).
    bundle = setup_wo_in_production(
        wo_quantity=1,
        quantity=1,
        flowdown_clauses=["DELEGATED_INSPECTION_PERMITTED"],
    )
    wo = get_success_data(api_client.complete_work_order(bundle["wo"]["id"], MP))
    assert wo["status"] == "FINAL_INSPECTION"

    # Inspector insp-9 holds no delegation: final acceptance is refused.
    resp = api_client.accept_work_order(wo["id"], QI9)
    validate_error(resp, ApiErrorId.ERR_DELEGATION_REQUIRED.value)

    # The customer grants an in-window ACTIVE delegation to insp-9.
    validate_success(
        api_client.create_delegation(
            {
                "po_id": bundle["po"]["id"],
                "inspector_user_id": "insp-9",
                "valid_from": "2026-01-01",
                "valid_to": "2026-12-31",
            },
            CQR,
        ),
        expected_status=201,
    )
    accepted = validate_success(api_client.accept_work_order(wo["id"], QI9))
    assert_work_order(accepted)
    assert accepted["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Corner: validations / wo_quantity_over_unreleased_rejected
# ---------------------------------------------------------------------------

def test_wo_quantity_over_unreleased_rejected(api):
    """PRD §3.5: "The quantity may not exceed the order's
    `unreleased_quantity` — `ERR_QUANTITY_EXCEEDS_UNRELEASED` on overflow, with
    equality allowed — and creation debits `unreleased_quantity` by the planned
    quantity."

    Design: Corner/validations/wo_quantity_over_unreleased_rejected
    """
    bundle = create_released_po(quantity=10)
    po = bundle["po"]
    wo = create_work_order(po["id"], quantity=10)  # equality allowed
    assert wo["status"] == "PLANNED"
    po_after = get_success_data(api_client.get_purchase_order(po["id"], CM))
    assert po_after["unreleased_quantity"] == 0, (
        f"the full-quantity WO debits unreleased_quantity to zero, got "
        f"{po_after['unreleased_quantity']}"
    )
    resp = api_client.create_work_order(
        {"po_id": po["id"], "quantity": 1, "special_processes_required": []}, MP
    )
    validate_error(resp, ApiErrorId.ERR_QUANTITY_EXCEEDS_UNRELEASED.value)
