"""Role-based access control and segregation of duties (PRD §2.1, §3.5)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ApiErrorId,
    AUDITOR,
    SAFETY,
    create_employee_payload,
    create_item_payload,
    create_job_role_payload,
    create_machine_payload,
    create_manager_override_payload,
    make_employee_headers,
    make_manager_headers,
    setup_cost_center,
    setup_employee,
    setup_item,
    setup_job_role,
    setup_manager,
    setup_machine,
    setup_machine_with_slot,
    setup_vend_scenario,
    stock_slot,
    vend_ok,
)


def test_rbac_employee_cannot_create_item(api):
    """PRD §2.1: "Role authorization then gates each endpoint per §4; a role
    not permitted for the endpoint, or a `Manager` assertion by an Employee
    whose `is_manager` flag is false, is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (403)."

    Design: Corner/rbac/rbac_employee_cannot_create_item
    """
    cc = setup_cost_center(code="CC-RB1", name="Ops")
    role = setup_job_role(role_name="RBAC-R1")
    emp, emp_headers = setup_employee(role["id"], cc["id"], employee_code="E-RB1",
                                      full_name="Tech RB1")

    resp = api.create_item(
        create_item_payload(sku="RBAC-X", name="Gloves", category="GENERAL",
                            base_list_price_cents=100),
        emp_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_rbac_manager_without_flag_cannot_grant_override(api):
    """PRD §2.1: "Role authorization then gates each endpoint per §4; a role
    not permitted for the endpoint, or a `Manager` assertion by an Employee
    whose `is_manager` flag is false, is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (403)."

    Design: Corner/rbac/rbac_manager_without_flag_cannot_grant_override
    """
    cc = setup_cost_center(code="CC-RB2", name="Ops")
    role = setup_job_role(role_name="TECH-RB")
    item = setup_item(sku="RBAC-M", base_list_price_cents=100)
    emp, _ = setup_employee(role["id"], cc["id"], employee_code="E-RB2",
                            full_name="Tech RB")
    fake_mgr = get_success_data(
        api.create_employee(
            create_employee_payload(employee_code="F-RB2", full_name="Fake Mgr",
                                    job_role_id=role["id"],
                                    home_cost_center_id=cc["id"],
                                    is_manager=False),
            ADMIN,
        )
    )
    fake_mgr_headers = make_manager_headers(fake_mgr["id"])

    resp = api.create_manager_override(
        create_manager_override_payload(
            employee_id=emp["id"], item_id=item["id"], approved_qty=2,
            valid_from="2026-05-01", valid_until="2026-05-31", reason_code="OTHER",
        ),
        fake_mgr_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_rbac_auditor_cannot_create_machines(api):
    """PRD §2.1: "Role authorization then gates each endpoint per §4; a role
    not permitted for the endpoint, or a `Manager` assertion by an Employee
    whose `is_manager` flag is false, is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (403)."

    Design: Corner/rbac/rbac_auditor_cannot_create_machines
    """
    setup_job_role(role_name="RBAC-R3")
    resp = api.create_machine(
        create_machine_payload(location_code="LOC-RB3", site_name="P30", model="VM-1"),
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_segregation_self_override_forbidden(api):
    """PRD §3.5: "segregation of duties forbids granting to oneself — a
    grantor equal to the grantee's `employee_id` fails with
    `ERR_SELF_OVERRIDE_FORBIDDEN` (403)."

    Design: Corner/rbac/segregation_self_override_forbidden
    """
    cc = setup_cost_center(code="CC-RB4", name="Ops")
    role = setup_job_role(role_name="LEAD-RS")
    item = setup_item(sku="RBAC-S", base_list_price_cents=100)
    mgr, mgr_headers = setup_manager(role["id"], cc["id"], employee_code="M-RB4",
                                     full_name="Self Mgr")

    resp = api.create_manager_override(
        create_manager_override_payload(
            employee_id=mgr["id"], item_id=item["id"], approved_qty=2,
            valid_from="2026-05-01", valid_until="2026-05-31", reason_code="OTHER",
        ),
        mgr_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SELF_OVERRIDE_FORBIDDEN)


def test_segregation_self_reversal_forbidden(api):
    """PRD §3.5: "A `Manager` reverses an issuance currently in `POSTED` —
    any other state fails with `ERR_ISSUANCE_ALREADY_REVERSED` — and may
    never reverse their own vend: a reversing identity equal to the
    issuance's `employee_id` fails with `ERR_SELF_REVERSAL_FORBIDDEN` (403)."

    Design: Corner/rbac/segregation_self_reversal_forbidden
    """
    cc = setup_cost_center(code="CC-RB5", name="Ops")
    role = setup_job_role(role_name="LEAD-RR")
    item = setup_item(sku="RBAC-R", base_list_price_cents=100)
    get_success_data(
        api.create_issuance_policy(
            {"job_role_id": role["id"], "item_id": item["id"],
             "period_limit_qty": 10, "period_window_days": 30},
            ADMIN,
        )
    )
    mgr_a = get_success_data(
        api.create_employee(
            create_employee_payload(employee_code="M-RB5A", full_name="Mgr A",
                                    job_role_id=role["id"],
                                    home_cost_center_id=cc["id"], is_manager=True),
            ADMIN,
        )
    )
    mgr_b = get_success_data(
        api.create_employee(
            create_employee_payload(employee_code="M-RB5B", full_name="Mgr B",
                                    job_role_id=role["id"],
                                    home_cost_center_id=cc["id"], is_manager=True),
            ADMIN,
        )
    )
    mgr_a_emp_headers = make_employee_headers(mgr_a["id"])
    mgr_a_mgr_headers = make_manager_headers(mgr_a["id"])
    mgr_b_mgr_headers = make_manager_headers(mgr_b["id"])

    machine, slot = setup_machine_with_slot(item["id"], capacity=20, par_level=0)
    stock_slot(machine, slot, 5)

    iss = vend_ok(mgr_a_emp_headers, machine, slot, qty=1, idempotency_key="rr-1")

    # Self-reversal: mgrA (who vended) tries to reverse own vend as Manager.
    resp = api.reverse_issuance(iss["id"], mgr_a_mgr_headers)
    validate_error(resp, ApiErrorId.ERR_SELF_REVERSAL_FORBIDDEN)

    # Different manager reversal succeeds.
    resp2 = api.reverse_issuance(iss["id"], mgr_b_mgr_headers)
    data = validate_success(resp2, 200)
    assert data["status"] == "REVERSED"


def test_safety_officer_fit_test_write_scope(api):
    """PRD §3.2: "A `SafetyOfficer` records a fit test with the `item_id`, the
    `tested_on` date, and a `result` of `PASS` or `FAIL`; the system appends
    an entry to the employee's `fit_tests` carrying its own `fit_test_id`,
    `item_id`, `tested_on`, `result`, `expires_on`, and `status`. A `PASS`
    earns an `expires_on` of the test date plus 365 days and a `VALID`
    status".

    Design: Corner/rbac/safety_officer_fit_test_write_scope
    """
    cc = setup_cost_center(code="CC-RB6", name="Ops")
    role = setup_job_role(role_name="PAINTER-RF")
    item = setup_item(sku="RBAC-F", name="Half Mask", category="RESPIRATOR",
                      base_list_price_cents=900)
    emp, emp_headers = setup_employee(role["id"], cc["id"], employee_code="E-RB6",
                                      full_name="Painter RF")

    # SafetyOfficer create succeeds.
    ok_resp = api.record_fit_test(
        emp["id"],
        {"item_id": item["id"], "tested_on": "2026-04-15", "result": "PASS"},
        SAFETY,
    )
    ok = validate_success(ok_resp, 201)
    entries = ok["fit_tests"]
    assert isinstance(entries, list) and len(entries) == 1
    assert entries[0]["expires_on"] == "2027-04-15"
    assert entries[0]["result"] == "PASS"

    # Employee role may NOT record fit tests.
    deny_resp = api.record_fit_test(
        emp["id"],
        {"item_id": item["id"], "tested_on": "2026-04-16", "result": "PASS"},
        emp_headers,
    )
    validate_error(deny_resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
