"""Employer registration, commercial-term defaults and benefit-plan supersession."""

import pytest
from test_helpers import (
    ApiErrorId,
    assert_benefit_plan,
    assert_employer,
    assert_envelope,
    benefit_plan_payload,
    create_active_plan,
    create_draft_plan,
    create_dependent,
    create_employee,
    create_employer,
    dependent_payload,
    employee_payload,
    employer_payload,
    read_employer,
    reservation_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

NETWORK_ADMIN = TEST_USERS["network_admin"]
BENEFITS_ADMIN = TEST_USERS["benefits_admin"]
CARE_COORDINATOR = TEST_USERS["care_coordinator"]


class TestEmployerRegistration:
    def test_registered_employer_reads_back_with_the_terms_it_was_given(self, api):
        """A retrieval returns the stored commercial terms unchanged.

        PRD 3.1: "Commercial terms follow, all optional at creation and all
        defaulted: `contract_status` is one of `ACTIVE`, `SUSPENDED` or
        `TERMINATED` and defaults to `ACTIVE`".

        Design: Corner/entities/corner_employer_retrieval_returns_stored_row
        """
        created = validate_success(
            api.create_employer(
                employer_payload(
                    industry_code="RETAIL",
                    admin_fee_pct=0.12,
                    invoicing_cycle="QUARTERLY",
                    adult_elder_extension_enabled=True,
                ),
                NETWORK_ADMIN,
            ),
            expected_status=201,
        )

        response = api.get_employer(created["id"], NETWORK_ADMIN)
        fetched = validate_success(response)
        assert_envelope(response.json(), "object")
        assert_employer(fetched)

        assert fetched["id"] == created["id"]
        assert fetched["industry_code"] == "RETAIL"
        assert fetched["admin_fee_pct"] == pytest.approx(0.12, abs=0.0001)
        assert fetched["invoicing_cycle"] == "QUARTERLY"
        assert fetched["adult_elder_extension_enabled"] is True
        assert fetched["ytd_billed_cents"] == 0

    def test_employer_creation_without_industry_code_is_rejected_and_writes_nothing(self, api):
        """A missing required field fails request shape and leaves no row behind.

        PRD 2.8 band 1: "Every field the endpoint marks required must be present
        and of the declared type, and no enum-valued field may carry a member
        outside its declared set — otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/corner_employer_create_missing_required_field_rejected
        """
        payload = employer_payload()
        payload.pop("industry_code")

        validate_error(
            api.create_employer(payload, NETWORK_ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value
        )

        _, meta = validate_paginated(api.list_employers(NETWORK_ADMIN))
        assert meta["total_count"] == 0

    def test_omitted_optional_inputs_take_their_declared_defaults(self, api):
        """Employer, plan, employee and dependent all fall back to declared defaults.

        PRD 3.1: "`fiscal_year_start_month` defaults to 1; `invoicing_cycle` is
        `MONTHLY` or `QUARTERLY` and defaults to `MONTHLY`, recording the cadence
        agreed with the client but scheduling nothing on its own; `admin_fee_pct`
        defaults to 0.085".

        Design: Corner/entities/corner_optional_inputs_fall_back_to_declared_defaults
        """
        employer = validate_success(
            api.create_employer(employer_payload(), NETWORK_ADMIN), expected_status=201
        )
        assert employer["contract_status"] == "ACTIVE"
        assert employer["fiscal_year_start_month"] == 1
        assert employer["invoicing_cycle"] == "MONTHLY"
        assert employer["admin_fee_pct"] == pytest.approx(0.085, abs=0.0001)
        assert employer["overage_billing_enabled"] is True
        assert employer["adult_elder_extension_enabled"] is False

        plan = validate_success(
            api.create_benefit_plan(
                benefit_plan_payload(employer["id"], employer["version"]), BENEFITS_ADMIN
            ),
            expected_status=201,
        )
        assert_benefit_plan(plan)
        assert plan["status"] == "DRAFT"
        assert plan["in_home_min_billable_hours"] == pytest.approx(4, abs=0.01)
        assert plan["max_dependents_per_reservation"] == 3
        assert plan["cancellation_window_hours"] == 24
        assert plan["effective_to"] is None
        assert plan["superseded_by_plan_id"] is None
        assert plan["enrolled_employee_count"] == 0

        activated = validate_success(api.activate_benefit_plan(plan["id"], BENEFITS_ADMIN))
        employee = validate_success(
            api.create_employee(
                employee_payload(employer["id"], activated["id"]), BENEFITS_ADMIN
            ),
            expected_status=201,
        )
        assert employee["employment_status"] == "ACTIVE"
        assert employee["eligibility_status"] == "ELIGIBLE"
        assert employee["entitlement_days_used"] == pytest.approx(0, abs=0.01)
        assert employee["entitlement_days_reserved"] == pytest.approx(0, abs=0.01)
        assert employee["no_show_strike_count"] == 0

        dependent = validate_success(
            api.create_dependent(employee["id"], dependent_payload(), BENEFITS_ADMIN),
            expected_status=201,
        )
        assert dependent["status"] == "ACTIVE"
        assert dependent["care_notes"] == ""

    def test_new_row_carries_version_one_and_amendment_restamps_updated_at(self, api):
        """created_at is frozen, updated_at tracks the clock and version counts mutations.

        PRD 2.5: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
        timestamp refreshed on every mutation, and `version`, an integer that
        starts at 1 on creation and increments by exactly 1 on every mutation of
        that row — including mutations that only rewrite derived counters."

        Design: Corner/entities/corner_system_fields_stamp_version_one_and_clock_timestamps
        """
        employer = create_employer(api)
        assert employer["version"] == 1
        assert employer["created_at"] == employer["updated_at"]
        assert employer["created_at"].startswith("2026-08-01T00:00:00")

        set_clock(api, "2026-08-05T00:00:00Z")
        amended = validate_success(
            api.patch_employer(employer["id"], {"admin_fee_pct": 0.0900}, BENEFITS_ADMIN)
        )

        assert amended["version"] == 2
        assert amended["created_at"] == employer["created_at"]
        assert amended["updated_at"].startswith("2026-08-05T00:00:00")

    def test_amendment_revises_named_fields_leaves_the_rest_and_bumps_version(self, api):
        """A partial amendment touches only the keys it carries.

        PRD 3.1: "Amending an employer is a `benefits_admin` operation and may
        revise `contract_status`, `admin_fee_pct`, `invoicing_cycle`,
        `overage_billing_enabled`, `adult_elder_extension_enabled` and
        `fiscal_year_start_month`."

        Design: Corner/endpoints/corner_patch_employer_updates_fields_and_bumps_version
        """
        employer = create_employer(api, invoicing_cycle="QUARTERLY")
        assert employer["version"] == 1

        amended = validate_success(
            api.patch_employer(
                employer["id"],
                {"admin_fee_pct": 0.10, "adult_elder_extension_enabled": True},
                BENEFITS_ADMIN,
            )
        )
        assert amended["version"] == 2
        assert amended["admin_fee_pct"] == pytest.approx(0.10, abs=0.0001)
        assert amended["adult_elder_extension_enabled"] is True
        assert amended["invoicing_cycle"] == "QUARTERLY"
        assert amended["contract_status"] == "ACTIVE"

        validate_error(
            api.patch_employer(employer["id"], {"admin_fee_pct": 1.5}, BENEFITS_ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )

        after = read_employer(api, employer["id"])
        assert after["version"] == 2
        assert after["admin_fee_pct"] == pytest.approx(0.10, abs=0.0001)
        assert after["ytd_billed_cents"] == 0


class TestBenefitPlanDrafting:
    def test_plan_draft_with_a_stale_employer_version_is_refused_then_retried(self, api):
        """The employer version guard fires before anything is written.

        PRD 2.6: "If that value differs from the employer's current `version`, the
        creation is rejected with `ERR_STALE_EMPLOYER_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/corner_stale_employer_version_blocks_plan_draft_then_retry_succeeds
        """
        employer = create_employer(api)
        stale_version = employer["version"]
        assert stale_version == 1

        amended = validate_success(
            api.patch_employer(employer["id"], {"admin_fee_pct": 0.1}, BENEFITS_ADMIN)
        )
        assert amended["version"] == 2
        assert amended["admin_fee_pct"] == pytest.approx(0.1, abs=0.0001)

        stale_payload = benefit_plan_payload(employer["id"], stale_version, plan_code="PLAN-RETRY")
        validate_error(
            api.create_benefit_plan(stale_payload, BENEFITS_ADMIN),
            ApiErrorId.ERR_STALE_EMPLOYER_VERSION.value,
        )

        rows, meta = validate_paginated(
            api.list_employer_benefit_plans(employer["id"], BENEFITS_ADMIN)
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        fresh_payload = dict(stale_payload, expected_employer_version=amended["version"])
        plan = validate_success(
            api.create_benefit_plan(fresh_payload, BENEFITS_ADMIN), expected_status=201
        )
        assert plan["status"] == "DRAFT"
        assert plan["version"] == 1

        assert read_employer(api, employer["id"])["version"] == 2

    def test_activation_before_effective_from_is_refused_until_the_clock_catches_up(self, api):
        """Activation needs effective_from at or before the logical clock.

        PRD 3.1: "the plan's `effective_from` is at or before the logical clock,
        and the plan's `effective_to` is either null or strictly after the logical
        clock (otherwise `ERR_PLAN_EFFECTIVE_WINDOW`)".

        Design: Corner/state_machines/corner_activate_plan_before_effective_from_is_rejected
        """
        employer = create_employer(api)
        plan = create_draft_plan(api, employer["id"], effective_from="2026-09-01")

        validate_error(
            api.activate_benefit_plan(plan["id"], BENEFITS_ADMIN),
            ApiErrorId.ERR_PLAN_EFFECTIVE_WINDOW.value,
        )
        still_draft = validate_success(api.get_benefit_plan(plan["id"], BENEFITS_ADMIN))
        assert still_draft["status"] == "DRAFT"
        assert still_draft["version"] == plan["version"]

        set_clock(api, "2026-09-01T00:00:00Z")
        activated = validate_success(api.activate_benefit_plan(plan["id"], BENEFITS_ADMIN))
        assert activated["status"] == "ACTIVE"
        assert activated["enrolled_employee_count"] == 0
        assert activated["superseded_by_plan_id"] is None

    def test_employer_plan_and_invoice_guards_each_return_their_own_code(self, api):
        """A battery over the employer, plan and invoice error surfaces.

        PRD 3.1: "Once the plan is `ACTIVE` it is frozen: an amendment attempt
        returns `ERR_PLAN_NOT_EDITABLE`, and the only way to change terms is to
        activate a successor."

        Design: Corner/errors/corner_employer_plan_and_invoice_error_battery
        """
        employer_e = create_employer(api, name="Ashford Foods Employer E")
        employer_f = create_employer(api, name="Ashford Foods Employer F")

        validate_error(
            api.create_employer(
                employer_payload(name="Ashford Foods Employer E"), NETWORK_ADMIN
            ),
            ApiErrorId.ERR_DUPLICATE_KEY.value,
        )

        plan_1 = create_active_plan(
            api, employer_e["id"], plan_code="PLAN-E1", effective_from="2026-01-01"
        )
        plan_2 = create_draft_plan(
            api, employer_e["id"], plan_code="PLAN-E2", effective_from="2026-07-01"
        )
        plan_3 = create_draft_plan(
            api, employer_e["id"], plan_code="PLAN-E3", effective_from="2025-12-01"
        )
        plan_f = create_active_plan(
            api, employer_f["id"], plan_code="PLAN-F1", effective_from="2026-01-01"
        )

        # A plan belonging to another employer cannot enrol this employer's staff.
        validate_error(
            api.create_employee(
                employee_payload(employer_e["id"], plan_f["id"]), BENEFITS_ADMIN
            ),
            ApiErrorId.ERR_PLAN_EMPLOYER_MISMATCH.value,
        )

        validate_error(
            api.patch_benefit_plan(plan_1["id"], {"no_show_charge_cents": 500}, BENEFITS_ADMIN),
            ApiErrorId.ERR_PLAN_NOT_EDITABLE.value,
        )
        validate_error(
            api.activate_benefit_plan(plan_1["id"], BENEFITS_ADMIN),
            ApiErrorId.ERR_BENEFITPLAN_STATE_INVALID.value,
        )
        validate_error(
            api.activate_benefit_plan(plan_3["id"], BENEFITS_ADMIN),
            ApiErrorId.ERR_ACTIVE_PLAN_EXISTS.value,
        )

        activated_2 = validate_success(api.activate_benefit_plan(plan_2["id"], BENEFITS_ADMIN))
        assert activated_2["status"] == "ACTIVE"
        superseded_1 = validate_success(api.get_benefit_plan(plan_1["id"], BENEFITS_ADMIN))
        assert superseded_1["status"] == "SUPERSEDED"
        assert superseded_1["superseded_by_plan_id"] == plan_2["id"]

        validate_error(
            api.activate_benefit_plan(plan_1["id"], BENEFITS_ADMIN),
            ApiErrorId.ERR_BENEFITPLAN_TERMINAL.value,
        )

        validate_error(
            api.create_employer_invoice(
                employer_e["id"],
                {"period_start": "2026-08-31", "period_end": "2026-08-01"},
                NETWORK_ADMIN,
            ),
            ApiErrorId.ERR_INVALID_PERIOD.value,
        )

        invoice = validate_success(
            api.create_employer_invoice(
                employer_e["id"],
                {"period_start": "2026-08-01", "period_end": "2026-08-31"},
                NETWORK_ADMIN,
            ),
            expected_status=201,
        )
        assert invoice["total_cents"] == 0
        assert invoice["line_count"] == 0

        validate_error(
            api.create_employer_invoice(
                employer_e["id"],
                {"period_start": "2026-08-15", "period_end": "2026-09-15"},
                NETWORK_ADMIN,
            ),
            ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP.value,
        )
        validate_error(
            api.pay_invoice(invoice["id"], {"paid_amount_cents": 0}, NETWORK_ADMIN),
            ApiErrorId.ERR_INVOICE_STATE_INVALID.value,
        )
        validate_error(
            api.issue_invoice(invoice["id"], NETWORK_ADMIN),
            ApiErrorId.ERR_INVOICE_EMPTY.value,
        )

        validate_success(
            api.patch_employer(employer_e["id"], {"contract_status": "TERMINATED"}, BENEFITS_ADMIN)
        )
        validate_error(
            api.activate_benefit_plan(plan_3["id"], BENEFITS_ADMIN),
            ApiErrorId.ERR_EMPLOYER_CONTRACT_INACTIVE.value,
        )


class TestSupersessionAndEmployeeRemapping:
    """A successor design retires the incumbent but re-enrols nobody."""

    @staticmethod
    def _two_plan_world(api):
        employer = create_employer(api)
        plan_1 = create_active_plan(
            api, employer["id"], plan_code="PLAN-P1", effective_from="2026-01-01"
        )
        employee = create_employee(api, employer["id"], plan_1["id"])
        dependent = create_dependent(api, employee["id"])
        plan_2 = create_draft_plan(
            api, employer["id"], plan_code="PLAN-P2", effective_from="2026-02-01"
        )
        return employer, plan_1, plan_2, employee, dependent

    def test_activating_the_successor_supersedes_the_incumbent_and_links_it(self, api):
        """Supersession moves forward in effective-date order and records the link.

        PRD 3.1: "the incumbent moves `ACTIVE → SUPERSEDED` and its
        `superseded_by_plan_id` is set to the newly activated plan's identifier".

        Design: Difficulty/cross_entity_state_dependency/reservation_intake_blocked_by_superseded_plan_until_employee_remapped
        """
        _, plan_1, plan_2, employee, _ = self._two_plan_world(api)

        activated_2 = validate_success(api.activate_benefit_plan(plan_2["id"], BENEFITS_ADMIN))
        assert activated_2["status"] == "ACTIVE"

        superseded_1 = validate_success(api.get_benefit_plan(plan_1["id"], BENEFITS_ADMIN))
        assert superseded_1["status"] == "SUPERSEDED"
        assert superseded_1["superseded_by_plan_id"] == plan_2["id"]

        # Supersession re-enrols nobody.
        assert validate_success(api.get_employee(employee["id"], BENEFITS_ADMIN))[
            "benefit_plan_id"
        ] == plan_1["id"]

    def test_intake_against_a_superseded_design_is_refused_with_plan_not_active(self, api):
        """An employee still pointing at the retired design cannot book care.

        PRD 3.1: "a new reservation for an employee still pointing at the
        superseded design is refused with `ERR_PLAN_NOT_ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/reservation_intake_blocked_by_superseded_plan_until_employee_remapped
        """
        _, _, plan_2, employee, dependent = self._two_plan_world(api)
        validate_success(api.activate_benefit_plan(plan_2["id"], BENEFITS_ADMIN))

        payload = reservation_payload(
            employee["id"],
            [dependent["id"]],
            "2026-08-14T09:00:00Z",
            "2026-08-14T15:00:00Z",
        )
        validate_error(
            api.create_reservation(payload, CARE_COORDINATOR),
            ApiErrorId.ERR_PLAN_NOT_ACTIVE.value,
        )

        _, meta = validate_paginated(
            api.list_employee_reservations(employee["id"], CARE_COORDINATOR)
        )
        assert meta["total_count"] == 0

    def test_remapping_the_employee_unblocks_the_identical_intake_payload(self, api):
        """The very same request succeeds once the employee points at the live plan.

        PRD 3.2: "A later amendment may revise `employment_status`, `email`, or
        move the person to a different `ACTIVE` plan of the same employer via
        `benefit_plan_id`".

        Design: Difficulty/cross_entity_state_dependency/reservation_intake_blocked_by_superseded_plan_until_employee_remapped
        """
        _, _, plan_2, employee, dependent = self._two_plan_world(api)
        activated_2 = validate_success(api.activate_benefit_plan(plan_2["id"], BENEFITS_ADMIN))

        payload = reservation_payload(
            employee["id"],
            [dependent["id"]],
            "2026-08-14T09:00:00Z",
            "2026-08-14T15:00:00Z",
        )
        validate_error(
            api.create_reservation(payload, CARE_COORDINATOR),
            ApiErrorId.ERR_PLAN_NOT_ACTIVE.value,
        )

        remapped = validate_success(
            api.patch_employee(
                employee["id"], {"benefit_plan_id": activated_2["id"]}, BENEFITS_ADMIN
            )
        )
        assert remapped["benefit_plan_id"] == activated_2["id"]

        reservation = validate_success(
            api.create_reservation(payload, CARE_COORDINATOR), expected_status=201
        )
        assert reservation["fulfillment_status"] == "INTAKE"
        assert reservation["benefit_plan_id"] == activated_2["id"]
        assert reservation["plan_version_pinned"] == activated_2["version"]
