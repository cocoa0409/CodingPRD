"""W-4 form lifecycle — DRAFT → FILED → SUPERSEDED cyclic across amendments."""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    validate_success,
    set_clock,
    create_employee,
    create_w4_draft,
    create_and_file_w4,
    get_w4_form,
    create_w4_form_payload,
    TEST_USERS,
)


# =========================================================================
# Queue (A) Difficulty — rule 4 transitive_cascade (instance 2, depth-2)
# =========================================================================

class TestW4FileSupersedeCascade:
    """Filing a new W-4 supersedes the prior one in a 2-hop cascade per PRD §3.1."""

    def test_filing_amendment_supersedes_prior_w4(self, api):
        """PRD §3.1: "Filing also fires two cascade hops: if the new W-4 carries
        a `supersedes_w4_id` pointing at a prior form, that prior form is
        immediately transitioned from `FILED` to `SUPERSEDED`"

        Setup: prior W-4 FILED for tax_year=2025 SINGLE; new W-4 DRAFT for
        same employee/year with supersedes_w4_id pointing to prior. File the
        new W-4 → prior transitions FILED → SUPERSEDED.

        Design: Difficulty/transitive_cascade/w4_file_supersede_cascade_depth_2
        """
        set_clock("2025-06-01T00:00:00.000Z")
        emp = create_employee()
        old_w4 = create_and_file_w4(emp["id"], tax_year=2025, filing_status="SINGLE")
        new_w4 = create_w4_draft(
            emp["id"], tax_year=2025, filing_status="MARRIED_JOINT",
            supersedes_w4_id=old_w4["id"],
        )

        file_res = api_client.file_w4_form(new_w4["id"], TEST_USERS["hr_clerk_headers"])
        validate_success(file_res, expected_status=200)

        new_after = get_w4_form(new_w4["id"])
        old_after = get_w4_form(old_w4["id"])
        assert new_after["status"] == "FILED"
        assert old_after["status"] == "SUPERSEDED", \
            f"prior W-4 must transition to SUPERSEDED, got {old_after['status']}"


# =========================================================================
# Queue (B) Corner — state_machines + entities
# =========================================================================

class TestW4InitialState:
    def test_post_w4_form_creates_draft(self, api):
        """PRD §3.1: "The form is created in `DRAFT`, with `filed_at` initially
        null."

        Design: Corner/state_machines/w4form_initial_state_draft
        """
        emp = create_employee()
        w4 = create_w4_draft(emp["id"])
        assert w4["status"] == "DRAFT"
        assert w4.get("filed_at") is None


class TestW4Defaults:
    def test_w4_create_omitting_optional_fields_uses_zero_defaults(self, api):
        """PRD §3.1: "The optional dollar-valued inputs all default to zero:
        `dependents_amount_cents` (the Step-3 dependents credit in cents),
        `other_income_cents` (Step-4(a)), `deductions_cents` (Step-4(b)), and
        `extra_withholding_cents` (Step-4(c) extra per-paycheck withholding)."

        Design: Corner/entities/w4_form_create_with_defaults
        """
        emp = create_employee(full_name="W4 Defaults")
        w4 = create_w4_draft(emp["id"], tax_year=2025, filing_status="SINGLE")
        assert w4["status"] == "DRAFT"
        assert w4["dependents_amount_cents"] == 0
        assert w4["other_income_cents"] == 0
        assert w4["deductions_cents"] == 0
        assert w4["extra_withholding_cents"] == 0
        assert w4.get("supersedes_w4_id") is None
        assert w4.get("filed_at") is None


# =========================================================================
# Queue (B) Corner — validations supersede_target_invalid
# =========================================================================

class TestSupersedeTargetValidation:
    def test_supersede_target_in_different_tax_year_is_rejected(self, api):
        """PRD §3.1: "When `supersedes_w4_id` is non-null on either creation or
        filing, the referenced prior form must currently be in `FILED` status,
        must belong to the same `employee_id`, and must cover the same
        `tax_year`. Any deviation — wrong status, wrong employee, mismatched
        year — is rejected with `ERR_SUPERSEDE_TARGET_INVALID`."

        Setup: prior W-4 FILED for tax_year=2025; new W-4 attempts to supersede
        it for tax_year=2026 → ERR_SUPERSEDE_TARGET_INVALID.

        Design: Corner/validations/supersede_target_invalid_wrong_year
        """
        emp = create_employee()
        old_w4 = create_and_file_w4(emp["id"], tax_year=2025, filing_status="SINGLE")
        res = api_client.create_w4_form(
            create_w4_form_payload(
                employee_id=emp["id"],
                tax_year=2026,
                filing_status="MARRIED_JOINT",
                supersedes_w4_id=old_w4["id"],
            ),
            TEST_USERS["hr_clerk_headers"],
        )
        validate_error(res, "ERR_SUPERSEDE_TARGET_INVALID", expected_status=422)
