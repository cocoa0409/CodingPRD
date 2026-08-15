"""Budget ledgers: two availability readings, conservation, and fiscal gates."""
from test_helpers import (
    TEST_USERS, assert_budget_conservation,
    make_building, make_teacher,
    register_teacher, setup_catalog_scenario, setup_completed_course,
    validate_error, validate_success, make_teacher_headers,
)
from test_helpers.factories import create_budget_payload, create_registration_payload


class TestDualVariantBudgetAvailability:
    def _encumbered_ledger(self):
        """Allocated 100000 with one 10000 registration-fee encumbrance, nothing spent."""
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "FEE-15", "clock_hours": 15,
                              "fee_cents": 10000},
            with_budget=100000)
        teacher = make_teacher(sc.building["id"], email="t2@x.com")
        registration = register_teacher(teacher["id"], sc.section["id"])
        assert registration["status"] == "REGISTERED"
        return sc

    def test_encumbrance_basis_is_the_blocking_variant(self, api):
        """PRD §2.7: "The **encumbrance basis** — `available_cents`, computed as
        the allocation minus both encumbered and spent — is the blocking variant
        used by every encumbering operation: a seat with a fee, a workshop
        approval, a waitlist promotion. A budget with 100000 cents allocated and
        10000 cents encumbered has 90000 cents of encumbrance-basis
        availability."

        Design: Difficulty/dual_variant_calc/dual_variant_budget_availability_encumbrance_vs_cash
        """
        sc = self._encumbered_ledger()
        summary = validate_success(api.get_budget_summary(
            sc.budget["id"], TEST_USERS["officer_headers"]), 200)
        assert summary["encumbered_cents"] == 10000
        assert summary["spent_cents"] == 0
        assert summary["available_cents"] == 90000, "100000 - 10000 - 0"

    def test_cash_basis_is_the_reporting_variant(self, api):
        """PRD §2.7: "The **cash basis** — the allocation minus spent only, which
        would read 100000 on the same ledger — is a reporting variant exposed
        only through the budget summary endpoint as `cash_basis_available_cents`;
        it never gates an operation."

        Design: Difficulty/dual_variant_calc/dual_variant_budget_availability_encumbrance_vs_cash
        """
        sc = self._encumbered_ledger()
        summary = validate_success(api.get_budget_summary(
            sc.budget["id"], TEST_USERS["officer_headers"]), 200)
        assert summary["cash_basis_available_cents"] == 100000, "100000 - 0"
        assert summary["available_cents"] != summary["cash_basis_available_cents"], (
            "two availability algorithms diverge on the same in-flight ledger")


class TestBudgetConservationRegisterDrop:
    def _registered_scenario(self):
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "INV-1", "clock_hours": 10,
                              "fee_cents": 20000},
            with_budget=500000)
        teacher = make_teacher(sc.building["id"], email="tn@x.com")
        registration = register_teacher(teacher["id"], sc.section["id"])
        return sc, teacher, registration

    def test_forward_action_preserves_conservation(self, api):
        """PRD §2.7: "Together with `allocated_cents` they satisfy a standing
        invariant at all times: the allocation equals encumbered plus spent plus
        available." PRD §3.3: "the encumbrance raises the budget's
        `encumbered_cents` by the fee, bumps the budget's `version`, and stamps
        the registration's `encumbered_cents` with the fee amount."

        Design: Difficulty/compensating_invariant/invariant_budget_conservation_register_drop
        """
        sc, _teacher, registration = self._registered_scenario()
        assert registration["encumbered_cents"] == 20000
        budget = validate_success(api.get_budget(
            sc.budget["id"], TEST_USERS["coordinator_headers"]), 200)
        assert budget["encumbered_cents"] == 20000
        assert budget["spent_cents"] == 0
        assert budget["available_cents"] == 480000
        assert_budget_conservation(budget)

    def test_compensating_drop_returns_ledger_to_zero_drift(self, api):
        """PRD §3.3: "the registration becomes `DROPPED`, its `encumbered_cents`
        is subtracted from the budget's `encumbered_cents` and zeroed on the
        registration (budget `version` bumped)". PRD §2.7: "the allocation equals
        encumbered plus spent plus available" at all times.

        Design: Difficulty/compensating_invariant/invariant_budget_conservation_register_drop
        """
        sc, teacher, registration = self._registered_scenario()
        validate_success(api.drop_registration(
            registration["id"], make_teacher_headers(teacher["id"])), 200)
        budget = validate_success(api.get_budget(
            sc.budget["id"], TEST_USERS["coordinator_headers"]), 200)
        assert budget["encumbered_cents"] == 0, "register+drop pair nets to zero drift"
        assert budget["spent_cents"] == 0
        assert budget["available_cents"] == 500000
        assert_budget_conservation(budget)


def test_budget_duplicate_rejected(api):
    """PRD §2.7: "Every building's annual PD allocation is tracked as a
    `BuildingBudget` row, unique per (`building_id`, `fiscal_year`) pair —
    attempting to create a second budget for the same pair fails with
    `ERR_BUDGET_ALREADY_EXISTS`."

    Design: Corner/validations/budget_duplicate_rejected
    """
    building = make_building()
    validate_success(api.create_budget(
        create_budget_payload(building["id"], fiscal_year=2026,
                              allocated_cents=100000),
        TEST_USERS["officer_headers"]), 201)
    res = api.create_budget(
        create_budget_payload(building["id"], fiscal_year=2026,
                              allocated_cents=200000),
        TEST_USERS["officer_headers"])
    validate_error(res, "ERR_BUDGET_ALREADY_EXISTS", expected_status=400)


def test_budget_close_with_encumbrance_rejected(api):
    """PRD §3.1: "Closing moves `OPEN` → `CLOSED` and is permitted only when
    `encumbered_cents` is exactly zero; a close attempted with outstanding
    commitments is rejected with `ERR_BUDGET_HAS_ENCUMBRANCES`."

    Design: Corner/validations/budget_close_with_encumbrance_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "BC-1", "clock_hours": 5,
                          "fee_cents": 10000},
        with_budget=500000)
    teacher = make_teacher(sc.building["id"], email="tbc@x.com")
    register_teacher(teacher["id"], sc.section["id"])
    res = api.close_budget(sc.budget["id"], TEST_USERS["officer_headers"])
    validate_error(res, "ERR_BUDGET_HAS_ENCUMBRANCES", expected_status=400)


def test_registration_budget_insufficient_rejected(api):
    """PRD §3.3: "If the section's `fee_cents` is greater than zero, the fee is
    encumbered against the teacher's building budget for the fiscal year of the
    section's `starts_at`: that budget must exist and be `OPEN`
    (`ERR_BUDGET_NOT_OPEN`) and its `available_cents` must cover the fee
    (`ERR_BUDGET_INSUFFICIENT`)".

    Design: Corner/validations/registration_budget_insufficient_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "BI-1", "clock_hours": 5,
                          "fee_cents": 10000},
        with_budget=5000)
    teacher = make_teacher(sc.building["id"], email="tbi@x.com")
    res = api.create_registration(
        create_registration_payload(teacher["id"], sc.section["id"]),
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_BUDGET_INSUFFICIENT", expected_status=400)


def test_registration_budget_not_open_rejected(api):
    """PRD §3.3: "that budget must exist and be `OPEN` (`ERR_BUDGET_NOT_OPEN`)
    and its `available_cents` must cover the fee (`ERR_BUDGET_INSUFFICIENT`)".
    PRD §3.1: "A new budget is `DRAFT` with both ledgers at zero ... and only an
    `OPEN` budget accepts encumbrances."

    Design: Corner/validations/registration_budget_not_open_rejected
    """
    set_up = setup_catalog_scenario(
        course_overrides={"course_code": "NO-1", "clock_hours": 5,
                          "fee_cents": 10000})
    # Budget exists but was never opened (DRAFT).
    budget = validate_success(api.create_budget(
        create_budget_payload(set_up.building["id"], fiscal_year=2026,
                              allocated_cents=500000),
        TEST_USERS["officer_headers"]), 201)
    assert budget["status"] == "DRAFT"
    teacher = make_teacher(set_up.building["id"], email="tno@x.com")
    res = api.create_registration(
        create_registration_payload(teacher["id"], set_up.section["id"]),
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_BUDGET_NOT_OPEN", expected_status=400)


def test_budget_summary_after_completion_spent(api):
    """PRD §3.5: "when the registration's `encumbered_cents` is positive, that
    amount leaves the budget's `encumbered_cents` and lands in its `spent_cents`,
    bumping the budget's `version`." PRD §3.1: "The read-only budget summary
    reports `allocated_cents`, `encumbered_cents`, `spent_cents`, the blocking
    `available_cents`, and the reporting-only `cash_basis_available_cents`, per
    the two availability readings of §2.7."

    Design: Corner/endpoints/budget_summary_after_completion_spent
    """
    sc = setup_completed_course(clock_hours=5, fee_cents=10000,
                                course_overrides={"course_code": "SU-1"},
                                with_budget=500000)
    assert sc.registration["status"] == "COMPLETED"
    summary = validate_success(api.get_budget_summary(
        sc.budget["id"], TEST_USERS["officer_headers"]), 200)
    assert summary["encumbered_cents"] == 0, "settled"
    assert summary["spent_cents"] == 10000
    assert summary["available_cents"] == 490000
    assert summary["cash_basis_available_cents"] == 490000, (
        "variants converge once nothing is in flight")
    assert summary["allocated_cents"] == (
        summary["encumbered_cents"] + summary["spent_cents"]
        + summary["available_cents"])
