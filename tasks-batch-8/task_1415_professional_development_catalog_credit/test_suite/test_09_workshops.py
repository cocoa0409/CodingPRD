"""External workshops: pre-approval windows, revision cycle, segregation of
duties, and the nested-minimum reimbursement."""
from test_helpers import (
    TEST_USERS, api_client, make_admin, make_building, make_budget,
    make_teacher, make_workshop, set_clock, validate_error, validate_success,
    workshop_to_attended, workshop_to_approved, workshop_to_submitted,
    make_building_admin_headers, make_officer_headers, make_teacher_headers,
)


class TestReimbursementNestedMin:
    """Two workshops in one fiscal year: W1 reimburses 240000, leaving 10000 of
    the 250000 annual cap; W2's min(150000 receipt, 120000 est, 10000 remaining
    cap) selects the cap remainder."""

    def _two_workshop_scenario(self):
        set_clock()
        building = make_building(name="East MS", building_code="EMS")
        budget = make_budget(building["id"], allocated_cents=1000000)
        teacher = make_teacher(building["id"], lane="MA", email="t3@x.com")
        admin = make_admin(building["id"], email="a1@x.com")
        w1 = make_workshop(teacher["id"], title="W1", provider="P1",
                           starts_at="2026-09-01T09:00:00Z",
                           ends_at="2026-09-02T17:00:00Z",
                           est_cost_cents=240000, clock_hours_claimed=20)
        w1 = workshop_to_attended(w1["id"], teacher["id"], admin["id"],
                                  actual_hours=20, receipt_cents=240000,
                                  evidence_clock="2026-09-03T00:00:00Z")
        paid1 = validate_success(api_client.reimburse_workshop(
            w1["id"], make_officer_headers("officer-1")), 200)
        set_clock("2026-09-05T00:00:00Z")
        w2 = make_workshop(teacher["id"], title="W2", provider="P2",
                           starts_at="2026-10-05T09:00:00Z",
                           ends_at="2026-10-06T17:00:00Z",
                           est_cost_cents=120000, clock_hours_claimed=12)
        w2 = workshop_to_attended(w2["id"], teacher["id"], admin["id"],
                                  actual_hours=12, receipt_cents=150000,
                                  evidence_clock="2026-10-07T00:00:00Z")
        return building, budget, teacher, w1, paid1, w2

    def test_reimbursement_selects_cap_remainder(self, api):
        """PRD §3.10: "The reimbursed amount is a nested minimum of three
        quantities: the `receipt_cents` evidenced, the `est_cost_cents` approved,
        and the teacher's remaining annual cap. The cap is 250000 cents per
        fiscal year, where the grouping year is the fiscal year of each
        workshop's `starts_at`; the remainder is 250000 minus the sum of
        `reimbursed_cents` over the teacher's workshops already in `REIMBURSED`
        in that same fiscal year, floored at zero, and it is computed before this
        reimbursement is applied."

        Design: Difficulty/combinatorial_formula/combinatorial_reimbursement_nested_min
        """
        _b, _bud, _t, _w1, paid1, w2 = self._two_workshop_scenario()
        assert paid1["reimbursed_cents"] == 240000, "min(240000, 240000, 250000)"
        paid2 = validate_success(api.reimburse_workshop(
            w2["id"], make_officer_headers("officer-1")), 200)
        assert paid2["status"] == "REIMBURSED"
        assert paid2["reimbursed_cents"] == 10000, (
            "min(150000 receipt, 120000 est, 10000 remaining cap)")

    def test_annual_cap_fully_consumed_in_ledger(self, api):
        """PRD §3.10: "Success records `reimbursed_cents`, moves the request to
        terminal `REIMBURSED`, releases the full `est_cost_cents` from the
        budget's `encumbered_cents`, adds the reimbursed amount to its
        `spent_cents`, and bumps the budget's `version`."

        Design: Difficulty/combinatorial_formula/combinatorial_reimbursement_nested_min
        """
        _b, budget, _t, _w1, _paid1, w2 = self._two_workshop_scenario()
        validate_success(api.reimburse_workshop(
            w2["id"], make_officer_headers("officer-1")), 200)
        ledger = validate_success(api.get_budget(
            budget["id"], TEST_USERS["coordinator_headers"]), 200)
        assert ledger["spent_cents"] == 250000, (
            "240000 + 10000 — the teacher's FY2026 reimbursed total hits the cap")
        assert ledger["encumbered_cents"] == 0, "both encumbrances settled"


class TestWorkshopRevisionCycle:
    def _rejected_then_revised(self):
        set_clock()
        building = make_building(name="Central HS", building_code="CHS")
        budget = make_budget(building["id"], allocated_cents=500000)
        teacher = make_teacher(building["id"], lane="MA", email="t5@x.com")
        admin = make_admin(building["id"], email="a5@x.com")
        workshop = make_workshop(teacher["id"], title="W Cycle", provider="PX",
                                 starts_at="2026-12-01T09:00:00Z",
                                 ends_at="2026-12-02T17:00:00Z",
                                 est_cost_cents=50000, clock_hours_claimed=10)
        workshop_to_submitted(workshop["id"], teacher["id"])
        rejected = validate_success(api_client.reject_workshop(
            workshop["id"], {"reason": "cost too high"},
            make_building_admin_headers(admin["id"])), 200)
        revised = validate_success(api_client.revise_workshop(
            workshop["id"], {"est_cost_cents": 45000},
            make_teacher_headers(teacher["id"])), 200)
        return building, budget, teacher, admin, workshop, rejected, revised

    def test_rejected_revises_back_to_draft(self, api):
        """PRD §3.10: "Rejection instead moves `SUBMITTED` → `REJECTED`,
        recording the payload's `reason` into `reject_reason`. A rejected request
        may be revised back to `DRAFT` by the teacher or a coordinator at most
        three times: revision overwrites whichever editable fields (`title`,
        `provider`, `starts_at`, `ends_at`, `est_cost_cents`,
        `clock_hours_claimed`) appear in the payload, increments
        `revision_count`, and a fourth attempt is `ERR_REVISION_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/non_linear_workshop_revision_cycle
        """
        _b, _bud, _t, _a, _w, rejected, revised = self._rejected_then_revised()
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason"] == "cost too high"
        assert revised["status"] == "DRAFT", "cycle REJECTED -> DRAFT traversed"
        assert revised["revision_count"] == 1
        assert revised["est_cost_cents"] == 45000, "revision overwrote the estimate"

    def test_cycle_completes_to_approved_on_same_id(self, api):
        """PRD §3.10: "On approval the estimate is encumbered against that budget
        (bumping its `version`), the request's `approved_by_user_id` is stamped
        with the approver's `X-User-ID` — the segregation-of-duties anchor — and
        the request becomes `APPROVED`."

        Design: Difficulty/non_linear_state_machine/non_linear_workshop_revision_cycle
        """
        _b, budget, teacher, admin, workshop, _rej, revised = (
            self._rejected_then_revised())
        workshop_to_submitted(workshop["id"], teacher["id"])
        approved = validate_success(api.approve_workshop(
            workshop["id"], make_building_admin_headers(admin["id"])), 200)
        assert approved["status"] == "APPROVED"
        assert approved["id"] == workshop["id"], "the cycle preserves identity"
        assert approved["approved_by_user_id"] == admin["id"]
        ledger = validate_success(api.get_budget(
            budget["id"], TEST_USERS["coordinator_headers"]), 200)
        assert ledger["encumbered_cents"] == 45000, (
            "the revised estimate is encumbered, not the original 50000")


def test_workshop_submit_lead_time_rejected(api):
    """PRD §3.10: "Submission — by the teacher or a coordinator — moves `DRAFT`
    → `SUBMITTED` and enforces the pre-approval lead: the workshop's `starts_at`
    must be at least fourteen days after the logical now, else
    `ERR_PREAPPROVAL_LEAD_TIME`."

    Design: Corner/validations/workshop_submit_lead_time_rejected
    """
    set_clock()
    building = make_building(name="LT Bldg", building_code="LT1")
    teacher = make_teacher(building["id"], email="tlt@x.com")
    workshop = make_workshop(teacher["id"], title="W Lead",
                             starts_at="2026-08-10T09:00:00Z",
                             ends_at="2026-08-10T17:00:00Z",
                             est_cost_cents=10000, clock_hours_claimed=6)
    res = api.submit_workshop(workshop["id"], make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_PREAPPROVAL_LEAD_TIME", expected_status=400)


def test_workshop_approval_after_start_rejected(api):
    """PRD §3.10: "Approval requires the logical now to be strictly before
    `starts_at` — approving at or after the start is `ERR_APPROVAL_AFTER_START`".

    Design: Corner/validations/workshop_approval_after_start_rejected
    """
    set_clock()
    building = make_building(name="AS Bldg", building_code="AS1")
    make_budget(building["id"], allocated_cents=500000)
    teacher = make_teacher(building["id"], email="tas@x.com")
    admin = make_admin(building["id"], email="aas@x.com")
    workshop = make_workshop(teacher["id"], title="W Late",
                             starts_at="2026-08-20T09:00:00Z",
                             ends_at="2026-08-21T17:00:00Z",
                             est_cost_cents=10000, clock_hours_claimed=6)
    workshop_to_submitted(workshop["id"], teacher["id"])  # 19-day lead: valid
    set_clock("2026-08-21T00:00:00Z")
    res = api.approve_workshop(workshop["id"],
                               make_building_admin_headers(admin["id"]))
    validate_error(res, "ERR_APPROVAL_AFTER_START", expected_status=400)


def test_workshop_complete_before_start_rejected(api):
    """PRD §3.10: "After the workshop, completion evidence moves `APPROVED` →
    `ATTENDED`: the logical now must be at or after `starts_at`
    (`ERR_WORKSHOP_NOT_STARTED`)".

    Design: Corner/validations/workshop_complete_before_start_rejected
    """
    set_clock()
    building = make_building(name="NS Bldg", building_code="NS1")
    make_budget(building["id"], allocated_cents=500000)
    teacher = make_teacher(building["id"], email="tns@x.com")
    admin = make_admin(building["id"], email="ans@x.com")
    workshop = make_workshop(teacher["id"], title="W Future",
                             starts_at="2026-12-01T09:00:00Z",
                             ends_at="2026-12-02T17:00:00Z",
                             est_cost_cents=10000, clock_hours_claimed=6)
    workshop_to_approved(workshop["id"], teacher["id"], admin["id"])
    res = api.complete_workshop(
        workshop["id"], {"actual_hours": 6, "receipt_cents": 9000},
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_WORKSHOP_NOT_STARTED", expected_status=400)


def test_workshop_revision_limit_rejected(api):
    """PRD §3.10: "A rejected request may be revised back to `DRAFT` by the
    teacher or a coordinator at most three times: revision overwrites whichever
    editable fields (`title`, `provider`, `starts_at`, `ends_at`,
    `est_cost_cents`, `clock_hours_claimed`) appear in the payload, increments
    `revision_count`, and a fourth attempt is `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Corner/validations/workshop_revision_limit_rejected
    """
    set_clock()
    building = make_building(name="RV Bldg", building_code="RV1")
    teacher = make_teacher(building["id"], email="trv@x.com")
    admin = make_admin(building["id"], email="arv@x.com")
    workshop = make_workshop(teacher["id"], title="W Rev",
                             starts_at="2026-12-01T09:00:00Z",
                             ends_at="2026-12-02T17:00:00Z",
                             est_cost_cents=10000, clock_hours_claimed=6)
    expected_counts = [1, 2, 3]
    for i, expected in enumerate(expected_counts):
        workshop_to_submitted(workshop["id"], teacher["id"])
        validate_success(api.reject_workshop(
            workshop["id"], {"reason": f"r{i + 1}"},
            make_building_admin_headers(admin["id"])), 200)
        revised = validate_success(api.revise_workshop(
            workshop["id"], {"title": f"W Rev {i + 2}"},
            make_teacher_headers(teacher["id"])), 200)
        assert revised["revision_count"] == expected
    # Fourth rejection leaves revision_count at 3; the fourth revise is refused.
    workshop_to_submitted(workshop["id"], teacher["id"])
    validate_success(api.reject_workshop(
        workshop["id"], {"reason": "r4"},
        make_building_admin_headers(admin["id"])), 200)
    res = api.revise_workshop(workshop["id"], {"title": "W Rev 5"},
                              make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_REVISION_LIMIT_EXCEEDED", expected_status=400)


def test_segregation_approver_cannot_reimburse(api):
    """PRD §2.1: "A `BusinessOfficer` attempting to reimburse or deny
    reimbursement on a workshop whose `approved_by_user_id` equals the officer's
    own `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.10: "The reimbursed amount is a nested minimum of three quantities:
    the `receipt_cents` evidenced, the `est_cost_cents` approved, and the
    teacher's remaining annual cap."

    Design: Corner/validations/segregation_approver_cannot_reimburse
    """
    set_clock()
    building = make_building(name="SD Bldg", building_code="SD1")
    make_budget(building["id"], allocated_cents=500000)
    teacher = make_teacher(building["id"], email="tsd@x.com")
    admin = make_admin(building["id"], email="asd@x.com")
    workshop = make_workshop(teacher["id"], title="W SoD",
                             starts_at="2026-09-01T09:00:00Z",
                             ends_at="2026-09-02T17:00:00Z",
                             est_cost_cents=30000, clock_hours_claimed=8)
    workshop_to_attended(workshop["id"], teacher["id"], admin["id"],
                         actual_hours=8, receipt_cents=25000,
                         evidence_clock="2026-09-03T00:00:00Z")
    # The approver's own id presented under the BusinessOfficer role is refused.
    res = api.reimburse_workshop(workshop["id"],
                                 make_officer_headers(admin["id"]))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    # A different officer succeeds and pays min(25000, 30000, 250000).
    paid = validate_success(api.reimburse_workshop(
        workshop["id"], make_officer_headers("officer-9")), 200)
    assert paid["status"] == "REIMBURSED"
    assert paid["reimbursed_cents"] == 25000


def test_building_scope_violation_on_approve(api):
    """PRD §3.10: "Approval belongs to a `BuildingAdmin` scoped to the request's
    `building_id` (acting outside that building is
    `ERR_BUILDING_SCOPE_VIOLATION`)."

    Design: Corner/validations/building_scope_violation_on_approve
    """
    set_clock()
    b1 = make_building(name="Sc B1", building_code="SC1")
    b2 = make_building(name="Sc B2", building_code="SC2")
    teacher = make_teacher(b1["id"], email="tsc@x.com")
    admin_other = make_admin(b2["id"], email="asc@x.com")
    workshop = make_workshop(teacher["id"], title="W Scope",
                             starts_at="2026-12-01T09:00:00Z",
                             ends_at="2026-12-02T17:00:00Z",
                             est_cost_cents=30000, clock_hours_claimed=8)
    workshop_to_submitted(workshop["id"], teacher["id"])
    res = api.approve_workshop(workshop["id"],
                               make_building_admin_headers(admin_other["id"]))
    validate_error(res, "ERR_BUILDING_SCOPE_VIOLATION", expected_status=403)


def test_approve_approved_workshop_rejected(api):
    """PRD §3.10: approval moves `SUBMITTED` → `APPROVED`; per PRD §2.10 step 6 a
    lifecycle violation surfaces as `ERR_INVALID_STATE`, and PRD §3.10: "On
    approval the estimate is encumbered against that budget (bumping its
    `version`)" — so the encumbrance applies exactly once.

    Design: Corner/state_machines/approve_approved_workshop_rejected
    """
    set_clock()
    building = make_building(name="ID Bldg", building_code="ID1")
    budget = make_budget(building["id"], allocated_cents=500000)
    teacher = make_teacher(building["id"], email="tid@x.com")
    admin = make_admin(building["id"], email="aid@x.com")
    workshop = make_workshop(teacher["id"], title="W ID",
                             starts_at="2026-12-01T09:00:00Z",
                             ends_at="2026-12-02T17:00:00Z",
                             est_cost_cents=30000, clock_hours_claimed=8)
    approved = workshop_to_approved(workshop["id"], teacher["id"], admin["id"])
    assert approved["status"] == "APPROVED"
    res = api.approve_workshop(workshop["id"],
                               make_building_admin_headers(admin["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=400)
    ledger = validate_success(api.get_budget(
        budget["id"], TEST_USERS["coordinator_headers"]), 200)
    assert ledger["encumbered_cents"] == 30000, "encumbrance applied exactly once"
