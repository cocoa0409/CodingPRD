"""Schedule attachment (A/B/C/D/E) and validations.

Coverage targets (PRD §3.3 / §2.7):
- Each schedule_type can be attached once per return.
- Duplicate schedule_type -> ERR_DUPLICATE_SCHEDULE.
- SALT input over $10,000 -> ERR_SALT_CAP_EXCEEDED.
- Schedule mutations revert READY_TO_FILE -> DRAFT.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_schedule_a,
    add_schedule_b,
    add_schedule_c,
    add_schedule_d,
    add_schedule_e,
    assert_schedule,
    create_schedule_a_payload,
    make_taxpayer_headers,
    re_get_tax_return,
    SALT_CAP_CENTS,
    setup_active_taxpayer_with_draft_return,
    setup_ready_to_file_return,
    validate_error,
)


# ===========================================================================
# Happy path — each schedule type attaches once.
# ===========================================================================
class TestAttachSchedules:

    def test_attach_schedule_a(self, api):
        """PRD §3.3: "a return may attach up to one Schedule of each
        IRS schedule type identified by schedule_type — A for itemized
        deductions".

        Claim: POST schedules with schedule_type=A succeeds and the
        response reports schedule_type='A' with id+versioning.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        sched = add_schedule_a(
            taxpayer, tax_return["id"],
            itemized_salt_cents=500_000,
            itemized_charity_cents=100_000,
        )
        assert_schedule(sched)
        assert sched["schedule_type"] == "A"
        assert sched["itemized_salt_cents"] == 500_000

    def test_attach_schedule_c(self, api):
        """PRD §3.3: "Schedule C captures self-employment activity
        through schedule_c_gross_receipts_cents and
        schedule_c_expenses_cents."

        Claim: POST schedules with schedule_type=C echoes both fields.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        sched = add_schedule_c(
            taxpayer, tax_return["id"],
            schedule_c_gross_receipts_cents=2_000_000,
            schedule_c_expenses_cents=500_000,
        )
        assert sched["schedule_type"] == "C"
        assert sched["schedule_c_gross_receipts_cents"] == 2_000_000
        assert sched["schedule_c_expenses_cents"] == 500_000

    def test_attach_schedule_e(self, api):
        """PRD §3.3: "Schedule E captures rental real estate: the
        taxpayer provides schedule_e_rental_income_cents and
        schedule_e_rental_expenses_cents."

        Claim: schedule_type=E echoes both fields.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        sched = add_schedule_e(
            taxpayer, tax_return["id"],
            schedule_e_rental_income_cents=3_000_000,
            schedule_e_rental_expenses_cents=1_000_000,
        )
        assert sched["schedule_type"] == "E"
        assert sched["schedule_e_rental_income_cents"] == 3_000_000

    def test_attach_schedule_b_and_d_computed_only(self, api):
        """PRD §3.3: "Schedule B is purely computed" and "Schedule D's
        two computed fields ... are populated from the 1099_B
        documents attached to the return."

        Claim: B and D can be attached with no input fields.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        sched_b = add_schedule_b(taxpayer, tax_return["id"])
        sched_d = add_schedule_d(taxpayer, tax_return["id"])
        assert sched_b["schedule_type"] == "B"
        assert sched_d["schedule_type"] == "D"


# ===========================================================================
# Duplicate schedule_type — PRD §3.3 / priority 16
# ===========================================================================
class TestDuplicateSchedule:

    def test_duplicate_schedule_type_rejected(self, api):
        """PRD §3.3: "A duplicate schedule attempt for a type already
        present on the return is rejected with ERR_DUPLICATE_SCHEDULE."

        Claim: second Schedule A on the same return -> ERR_DUPLICATE_SCHEDULE.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        add_schedule_a(taxpayer, tax_return["id"], itemized_salt_cents=0)
        resp = api.create_schedule(
            tax_return["id"],
            create_schedule_a_payload(itemized_salt_cents=0),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCHEDULE.value)


# ===========================================================================
# SALT cap input — PRD §3.3 / priority 12
# ===========================================================================
class TestSaltCap:

    def test_salt_above_cap_rejected(self, api):
        """PRD §3.3: "The system rejects an itemized_salt_cents input
        larger than 1,000,000 cents (the $10,000 statutory SALT input
        cap) at write time with ERR_SALT_CAP_EXCEEDED".

        Claim: itemized_salt_cents > 1_000_000 -> ERR_SALT_CAP_EXCEEDED.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        resp = api.create_schedule(
            tax_return["id"],
            create_schedule_a_payload(itemized_salt_cents=SALT_CAP_CENTS + 1),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SALT_CAP_EXCEEDED.value)

    def test_salt_at_cap_accepted(self, api):
        """PRD §3.3: input-cap is 1,000,000 cents inclusive.

        Claim: itemized_salt_cents == 1_000_000 (exactly the cap)
        succeeds.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        sched = add_schedule_a(
            taxpayer, tax_return["id"],
            itemized_salt_cents=SALT_CAP_CENTS,
        )
        assert sched["itemized_salt_cents"] == SALT_CAP_CENTS


# ===========================================================================
# Schedule mutations revert READY_TO_FILE -> DRAFT — PRD §2.7 / §3.3
# ===========================================================================
class TestScheduleReverts:

    def test_create_schedule_on_ready_reverts_to_draft(self, api):
        """PRD §3.3: "As with income documents, any creation or patch
        on a Schedule belonging to a return in READY_TO_FILE reverts
        the parent to DRAFT".

        Claim: attaching a Schedule on a READY_TO_FILE return reverts
        the parent return to DRAFT.
        """
        taxpayer, ready_return, _ = setup_ready_to_file_return()
        assert ready_return["status"] == "READY_TO_FILE"
        add_schedule_c(
            taxpayer, ready_return["id"],
            schedule_c_gross_receipts_cents=10_000,
            schedule_c_expenses_cents=5_000,
        )
        after = re_get_tax_return(taxpayer, ready_return["id"])
        assert after["status"] == "DRAFT"
