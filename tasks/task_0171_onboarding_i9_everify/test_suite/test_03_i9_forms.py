"""I-9 form lifecycle: create, lineage rules, void.

Covers PRD §3.3 (form creation, INITIAL/REVERIFICATION/REHIRE lineage,
DUPLICATE_INITIAL_FORM, void path).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock_to,
    api_client,
    assert_audit_action_present,
    assert_i9_form,
    create_employee,
    create_i9_form,
    create_i9_form_payload,
    list_audit_events,
    setup_employee_at_section1_only_for_everify_attempt,
    setup_employee_with_section2_done,
    TEST_USERS,
    validate_error,
    validate_success,
    void_form,
    void_form_payload,
)


# ===========================================================================
# Form creation — PRD §3.3
# ===========================================================================
class TestFormCreation:

    def test_create_initial_form_returns_draft(self, api, hr_staff_headers):
        """PRD §3.3: "`HRStaff` opens a new `I9Form` for an employee in
        state `DRAFT` by specifying `form_kind`"."""
        emp = create_employee()
        resp = api.create_i9_form(
            emp["id"], create_i9_form_payload(form_kind="INITIAL"),
            hr_staff_headers,
        )
        form = validate_success(resp, expected_status=201)
        assert_i9_form(form)
        assert form["form_status"] == "DRAFT"
        assert form["form_kind"] == "INITIAL"
        assert form["employee_id"] == emp["id"]

    def test_second_initial_form_returns_err_duplicate_initial_form(
            self, api, hr_staff_headers):
        """PRD §3.3: "An `INITIAL` form is unique per employee: a second
        concurrent `INITIAL` creation is rejected with
        `ERR_DUPLICATE_INITIAL_FORM`"."""
        emp = create_employee()
        first = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        # Second attempt — sequential here, but the rule is structural
        # not race-only.
        resp = api.create_i9_form(
            emp["id"], create_i9_form_payload(form_kind="INITIAL"),
            hr_staff_headers,
        )
        validate_error(resp, "ERR_DUPLICATE_INITIAL_FORM")


# ===========================================================================
# Form lineage — PRD §3.3 / §5: ERR_INVALID_FORM_LINEAGE
# ===========================================================================
class TestFormLineage:

    def test_reverification_without_supersedes_form_id_is_invalid_lineage(
            self, api, hr_staff_headers):
        """PRD §3.3: "A `REVERIFICATION` form requires
        `supersedes_form_id` to resolve to a form in state
        `SECTION_2_DONE` on the same employee".

        Claim: REVERIFICATION with NO supersedes_form_id → lineage
        violation (cannot resolve).
        """
        emp = create_employee()
        # Omit supersedes_form_id entirely.
        resp = api.create_i9_form(
            emp["id"],
            create_i9_form_payload(form_kind="REVERIFICATION"),
            hr_staff_headers,
        )
        validate_error(resp, "ERR_INVALID_FORM_LINEAGE")

    def test_reverification_pointing_at_draft_form_is_invalid_lineage(
            self, api, hr_staff_headers):
        """PRD §3.3: "A `REVERIFICATION` form requires
        `supersedes_form_id` to resolve to a form in state
        `SECTION_2_DONE` on the same employee".

        Claim: REVERIFICATION pointing at a DRAFT (not SECTION_2_DONE)
        form → ERR_INVALID_FORM_LINEAGE.
        """
        emp = create_employee()
        # First form left in DRAFT.
        draft_form = create_i9_form(
            employee_id=emp["id"], form_kind="INITIAL",
        )
        resp = api.create_i9_form(
            emp["id"],
            create_i9_form_payload(
                form_kind="REVERIFICATION",
                supersedes_form_id=draft_form["id"],
            ),
            hr_staff_headers,
        )
        validate_error(resp, "ERR_INVALID_FORM_LINEAGE")


# ===========================================================================
# Form void — PRD §3.3
# ===========================================================================
class TestFormVoid:

    def test_void_draft_form_transitions_to_voided(self, api,
                                                   hr_staff_headers):
        """PRD §3.3: "The transition from `DRAFT` to `VOIDED` has no
        further preconditions; ... an `AuditEvent` with action
        `FORM_VOIDED` is appended and the form's `form_status` becomes
        `VOIDED`"."""
        emp = create_employee()
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        resp = api.void_i9_form(
            form["id"], void_form_payload(version=form["version"]),
            hr_staff_headers,
        )
        voided = validate_success(resp, expected_status=200)
        assert voided["form_status"] == "VOIDED"
        # Audit trail must carry FORM_VOIDED.
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "FORM_VOIDED")

    def test_void_section1_done_form_succeeds(self, api, hr_staff_headers):
        """PRD §3.3: "the transition from `SECTION_1_DONE` to `VOIDED`
        additionally requires that no `EVerifyCase` has been opened
        against the form".

        Claim: void on SECTION_1_DONE (no case opened) → VOIDED.
        """
        ctx = setup_employee_at_section1_only_for_everify_attempt()
        form = ctx["form"]
        resp = api.void_i9_form(
            form["id"], void_form_payload(version=form["version"]),
            hr_staff_headers,
        )
        voided = validate_success(resp, expected_status=200)
        assert voided["form_status"] == "VOIDED"

    def test_void_section2_done_form_returns_err_invalid_state(self,
                                                              api,
                                                              hr_staff_headers):
        """PRD §3.3: "Voiding is not permitted after Section 2 has been
        signed; an attempt is rejected with `ERR_INVALID_STATE`"."""
        emp, form, _doc = setup_employee_with_section2_done()
        resp = api.void_i9_form(
            form["id"], void_form_payload(version=form["version"]),
            hr_staff_headers,
        )
        validate_error(resp, "ERR_INVALID_STATE")

    def test_void_after_initial_void_initial_form_again_allowed(self, api,
                                                                hr_staff_headers):
        """Difficulty-design recipe: at_most_one_initial_i9form_per_employee
        - "even after R's first INITIAL form is voided, creating a NEW
        form with form_kind=INITIAL is allowed only if no non-VOIDED
        INITIAL exists; tested by voiding then succeeding."

        PRD §3.3: "An `INITIAL` form is unique per employee" — coupled
        with VOIDED being terminal allows a fresh INITIAL after void.
        """
        emp = create_employee()
        first = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        void_form(form_id=first["id"], version=first["version"])
        # Now a second INITIAL is allowed because the prior is VOIDED.
        resp = api.create_i9_form(
            emp["id"], create_i9_form_payload(form_kind="INITIAL"),
            hr_staff_headers,
        )
        second = validate_success(resp, expected_status=201)
        assert second["form_kind"] == "INITIAL"
        assert second["form_status"] == "DRAFT"


# ===========================================================================
# Form list — PRD §4
# ===========================================================================
class TestFormList:

    def test_list_forms_filters_by_form_status(self, api, hr_staff_headers):
        """PRD §3.3: "The list-forms endpoint accepts filters by
        `form_status` and `form_kind` alongside pagination."."""
        emp = create_employee()
        create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        resp = api.list_i9_forms(
            emp["id"], hr_staff_headers,
            params={"form_status": "DRAFT", "limit": 50},
        )
        # Lenient list extraction.
        body = resp.json().get("data", [])
        if isinstance(body, dict):
            for k in ("items", "results", "forms"):
                if isinstance(body.get(k), list):
                    body = body[k]
                    break
        assert isinstance(body, list), (
            "list endpoint must return an array"
        )
        for f in body:
            assert f["form_status"] == "DRAFT"
            assert f["employee_id"] == emp["id"]
