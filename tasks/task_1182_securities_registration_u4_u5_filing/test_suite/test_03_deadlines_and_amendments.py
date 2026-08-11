"""Filing deadlines, disclosure events, and amendment lifecycle tests
(PRD Sections 2.6, 3.6, 3.9)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_amendment_filing,
    assert_disclosure_event,
    assert_termination_filing,
    create_active_registration,
    create_active_registration_with_invoice,
    create_applicant,
    create_disclosure_event,
    create_firm,
    create_terminated_registration,
    file_amendment,
    get_affiliation,
    get_event,
    get_invoice,
    get_request,
    get_selection,
    get_termination_filing,
    issue_renewal_invoice,
    make_user_headers,
    set_clock,
    validate_error,
    validate_success,
)


def _create_affiliation(applicant_id, second_firm_id, first_req_id):
    return api_client.create_affiliation_request(
        {
            "applicant_id": applicant_id,
            "second_firm_id": second_firm_id,
            "first_registration_request_id": first_req_id,
        },
        make_user_headers("rp-cascade", "RegistrationPrincipal"),
    )


def _approve_affiliation(affiliation_id, reviewer_user_id):
    return api_client.approve_affiliation_request(
        affiliation_id, make_user_headers(reviewer_user_id, "ComplianceOfficer")
    )


class TestDeadlineBasisVariants:
    def test_amendment_deadline_calendar_basis_default(self, api):
        """PRD Section 2.6: "Under the `CALENDAR` basis, a deadline is the
        anchor instant plus the stated number of calendar days; weekends and
        holidays are ignored." PRD Section 2.6: "A disclosure event's
        amendment deadline, `amendment_due_at`, is anchored on the event's
        `reported_at` and runs 30 days." PRD Section 2.6: "A firm is created
        with the `CALENDAR` basis by default".

        Design: Difficulty/dual_variant_calc/amendment_deadline_calendar_vs_regulatory_basis
        """
        firm = create_firm()  # never patched: CALENDAR basis by default
        applicant = create_applicant()
        set_clock("2026-06-10T09:00:00Z")
        event = create_disclosure_event(
            applicant["id"], event_type="BANKRUPTCY", event_date="2026-06-01"
        )
        assert_disclosure_event(event)
        # 2026-06-10 + 30 calendar days = 2026-07-10.
        assert event["amendment_due_at"][:10] == "2026-07-10"

    def test_amendment_deadline_regulatory_basis(self, api, system_operator_headers):
        """PRD Section 2.6: "Under the `REGULATORY` basis, the deadline is the
        anchor plus the stated number of business days: counting begins on the
        day after the anchor and advances day by day, counting only days that
        fall Monday through Friday (the system holiday calendar is empty, so
        only weekends are skipped)." PRD Section 2.6: "a `SystemOperator` can
        switch the firm to the `REGULATORY` basis by patching the firm's
        `deadline_basis`, and the new basis applies prospectively to deadlines
        computed after the change".

        Design: Difficulty/dual_variant_calc/amendment_deadline_calendar_vs_regulatory_basis
        """
        # Link the applicant to the firm via an ACTIVE registration so "the
        # firm's configured deadline basis" (PRD Section 3.6) is determined.
        ctx = create_active_registration()
        validate_success(
            api.patch_firm(ctx["firm"]["id"], {"deadline_basis": "REGULATORY"},
                           system_operator_headers)
        )
        set_clock("2026-06-10T09:00:00Z")
        event = create_disclosure_event(
            ctx["applicant"]["id"], event_type="BANKRUPTCY", event_date="2026-06-01"
        )
        assert_disclosure_event(event)
        # 2026-06-10 + 30 business days (Mon-Fri) = 2026-07-22.
        assert event["amendment_due_at"][:10] == "2026-07-22"


class TestU5DeadlineAnchor:
    def test_amendment_then_u5_deadline_anchor_regulatory(self, api,
                                                          system_operator_headers):
        """PRD Section 2.6: "A termination filing's `filing_deadline_at` is
        anchored on the `termination_date` and likewise runs 30 days." PRD
        Section 3.9: "Filing stamps `filed_at`, computes `filing_deadline_at`
        as 30 days from the `termination_date` under the firm's deadline
        basis (§2.6), and sets `is_late` true when the filing instant falls
        strictly after that deadline."

        Design: Difficulty/combinatorial_formula/amendment_then_u5_deadline_anchor_mode_c
        """
        ctx = create_active_registration(
            category="IA",
            jurisdictions=("CA",),
            submitter_user_id="rp-anchor",
            reviewer_user_id="co-anchor",
            firm_overrides=None,
        )
        # Patch the firm to REGULATORY before the U5 deadline is computed.
        validate_success(
            api.patch_firm(ctx["firm"]["id"], {"deadline_basis": "REGULATORY"},
                           system_operator_headers)
        )
        set_clock("2026-07-31T12:00:00Z")
        u5 = validate_success(
            api.create_termination_filing(
                {
                    "registration_request_id": ctx["request"]["id"],
                    "termination_reason": "DISCHARGED",
                    "termination_date": "2026-07-31",
                },
                make_user_headers("rp-anchor-u5", "RegistrationPrincipal"),
            ),
            expected_status=201,
        )
        assert_termination_filing(u5)
        # Anchor is the INPUT termination_date: 2026-07-31 + 30 business days.
        assert u5["filing_deadline_at"][:10] == "2026-09-11"
        # Filed the same day it takes effect: not strictly after the deadline.
        assert u5["is_late"] is False
        # Filing cascade moves the registration to TERMINATED.
        assert get_request(ctx["request"]["id"])["status"] == "TERMINATED"

    def test_u5_deadline_anchor_calendar_basis(self, api):
        """PRD Section 3.9: "Filing stamps `filed_at`, computes
        `filing_deadline_at` as 30 days from the `termination_date` under the
        firm's deadline basis (§2.6), and sets `is_late` true when the filing
        instant falls strictly after that deadline." PRD Section 2.6: "Under
        the `CALENDAR` basis, a deadline is the anchor instant plus the stated
        number of calendar days".

        Design: Difficulty/combinatorial_formula/amendment_then_u5_deadline_anchor_mode_c
        """
        ctx = create_active_registration(
            category="IA",
            jurisdictions=("CA",),
            submitter_user_id="rp-anchor2",
            reviewer_user_id="co-anchor2",
        )
        set_clock("2026-07-31T12:00:00Z")
        u5 = validate_success(
            api.create_termination_filing(
                {
                    "registration_request_id": ctx["request"]["id"],
                    "termination_reason": "DISCHARGED",
                    "termination_date": "2026-07-31",
                },
                make_user_headers("rp-anchor2-u5", "RegistrationPrincipal"),
            ),
            expected_status=201,
        )
        # Same payload under the default CALENDAR basis: 2026-07-31 + 30
        # calendar days = 2026-08-30.
        assert u5["filing_deadline_at"][:10] == "2026-08-30"
        assert u5["is_late"] is False
        assert get_request(ctx["request"]["id"])["status"] == "TERMINATED"


class TestAmendmentLatenessBoundary:
    def _setup_two_events(self):
        ctx = create_active_registration(
            category="IA",
            jurisdictions=("CA",),
            submitter_user_id="rp-boundary",
            reviewer_user_id="co-boundary",
        )
        set_clock("2026-06-10T09:00:00Z")
        ev1 = create_disclosure_event(
            ctx["applicant"]["id"],
            event_type="CUSTOMER_COMPLAINT",
            event_date="2026-06-05",
        )
        ev2 = create_disclosure_event(
            ctx["applicant"]["id"],
            event_type="REGULATORY_ACTION",
            event_date="2026-06-05",
        )
        # Default CALENDAR basis: both events are due 2026-07-10.
        assert ev1["amendment_due_at"][:10] == "2026-07-10"
        assert ev2["amendment_due_at"][:10] == "2026-07-10"
        return ctx, ev1, ev2

    def test_amendment_is_late_strict_greater_than_on_time_side(self, api):
        """PRD Section 3.6: "its `is_late` is computed by comparing the filing
        instant against the event's `amendment_due_at`: strictly after the
        deadline means late. An on-time filing is created with `is_late` false
        and moves the event `OPEN → AMENDED`". PRD Section 2.6: "the computed
        deadline is inclusive through the end of the returned day —
        23:59:59.999Z."

        Design: Difficulty/boundary_precision_check/amendment_is_late_strict_greater_than
        """
        ctx, ev1, ev2 = self._setup_two_events()
        # Filed at the due date's inclusive end-of-day: on time.
        set_clock("2026-07-10T23:59:59Z")
        am1 = file_amendment(
            ev1["id"],
            narrative_text="On-time amendment filed at the deadline boundary second.",
        )
        assert_amendment_filing(am1)
        assert am1["is_late"] is False
        assert get_event(ev1["id"])["status"] == "AMENDED"

    def test_amendment_is_late_strict_greater_than_late_side(self, api):
        """PRD Section 3.6: "its `is_late` is computed by comparing the filing
        instant against the event's `amendment_due_at`: strictly after the
        deadline means late. ... a late filing is created with `is_late` true
        and moves the event `OPEN → LATE_AMENDED`."

        Design: Difficulty/boundary_precision_check/amendment_is_late_strict_greater_than
        """
        ctx, ev1, ev2 = self._setup_two_events()
        # Filed one second into the day after the due date: late.
        set_clock("2026-07-11T00:00:00Z")
        am2 = file_amendment(
            ev2["id"],
            narrative_text="Late amendment filed one second past the deadline day.",
        )
        assert_amendment_filing(am2)
        assert am2["is_late"] is True
        assert get_event(ev2["id"])["status"] == "LATE_AMENDED"


class TestAmendmentReturnCascade:
    def _setup_filed_amendment(self):
        ctx = create_active_registration(
            category="IA",
            jurisdictions=("CA",),
            submitter_user_id="rp-revert",
            reviewer_user_id="co-revert",
        )
        set_clock("2026-06-10T09:00:00Z")
        event = create_disclosure_event(
            ctx["applicant"]["id"],
            event_type="CIVIL_JUDGMENT",
            event_date="2026-06-01",
        )
        assert event["amendment_due_at"][:10] == "2026-07-10"
        set_clock("2026-06-20T00:00:00Z")
        amendment = file_amendment(
            event["id"],
            narrative_text="Amendment reporting the civil judgment with full case detail.",
            filer_user_id="rp-revert",
        )
        assert amendment["is_late"] is False
        set_clock("2026-06-25T00:00:00Z")
        return ctx, event, amendment

    def test_amendment_return_two_hop_reversion_cascade(self, api):
        """PRD Section 3.6: "A `ComplianceOfficer` other than the filer may
        return a `FILED` amendment, moving it to `RETURNED`. The return
        reopens the underlying event — its status reverts to `OPEN` — and its
        `amendment_due_at` is recomputed from the original `reported_at` under
        the same deadline basis: the 30-day clock does not restart from the
        return date".

        Design: Difficulty/transitive_cascade/amendment_return_two_hop_reversion_cascade
        """
        ctx, event, amendment = self._setup_filed_amendment()
        returned = validate_success(
            api.return_amendment_filing(
                amendment["id"], make_user_headers("co-revert", "ComplianceOfficer")
            )
        )
        assert returned["status"] == "RETURNED"

        event_after = get_event(event["id"])
        assert event_after["status"] == "OPEN"
        # The original 2026-07-10 deadline is preserved — not recomputed from
        # the 2026-06-25 return date.
        assert event_after["amendment_due_at"][:10] == "2026-07-10"

    def test_amendment_return_preserves_original_deadline_for_refiling(self, api):
        """PRD Section 3.6: "The `RETURNED` amendment row is immutable and
        remains queryable in that state; putting the event back on file means
        creating a brand-new amendment filing against the same
        `disclosure_event_id`, which begins its own `FILED` lifecycle while
        the old row stays `RETURNED`." PRD Section 3.6: "the 30-day clock does
        not restart from the return date, so a firm that sat on a returned
        amendment files the re-do against whatever remains of the original
        window."

        Design: Difficulty/transitive_cascade/amendment_return_two_hop_reversion_cascade
        """
        ctx, event, amendment = self._setup_filed_amendment()
        validate_success(
            api.return_amendment_filing(
                amendment["id"], make_user_headers("co-revert", "ComplianceOfficer")
            )
        )
        # Old row remains queryable in RETURNED.
        old = validate_success(api.get_amendment_filing(
            amendment["id"], make_user_headers("so-rv2", "SystemOperator")
        ))
        assert old["status"] == "RETURNED"

        # Re-file against the same event: a new FILED row; still on time
        # relative to the preserved original deadline (clock 2026-06-25).
        new_filing = file_amendment(
            event["id"],
            narrative_text="Replacement amendment filed after the first was returned.",
            filer_user_id="rp-revert",
        )
        assert new_filing["id"] != amendment["id"]
        assert new_filing["status"] == "FILED"
        assert new_filing["is_late"] is False
        assert get_event(event["id"])["status"] == "AMENDED"


class TestU5TerminationCascade:
    def _setup_cascade(self):
        """ACTIVE R1 at firm 1 + APPROVED affiliation to firm 2 + ISSUED invoice."""
        ctx = create_active_registration(
            category="IA",
            jurisdictions=("CA",),
            submitter_user_id="rp-cascade",
            reviewer_user_id="co-cascade",
        )
        firm2 = create_firm(legal_name="Cascade Two")
        affiliation = validate_success(
            _create_affiliation(
                ctx["applicant"]["id"], firm2["id"], ctx["request"]["id"]
            ),
            expected_status=201,
        )
        approved_aff = validate_success(
            _approve_affiliation(affiliation["id"], "co-cascade-2")
        )
        assert approved_aff["status"] == "APPROVED"
        invoice = issue_renewal_invoice(ctx["request"]["id"], 2027)
        assert invoice["status"] == "ISSUED"
        return ctx, firm2, approved_aff, invoice

    def test_u5_termination_three_hop_cascade(self, api):
        """PRD Section 3.9: "the request moves `ACTIVE → TERMINATED` with its
        `version` incremented; every jurisdiction selection still `APPROVED`
        flips to `RELINQUISHED`; every renewal invoice still `ISSUED` for the
        request is voided to `VOID`; and every affiliation request built on
        this registration as its `first_registration_request_id` and currently
        `APPROVED` is revoked to `REVOKED`."

        Design: Difficulty/transitive_cascade/u5_termination_three_hop_cascade
        """
        ctx, firm2, affiliation, invoice = self._setup_cascade()
        set_clock("2026-08-01T00:00:00Z")
        u5 = validate_success(
            api.create_termination_filing(
                {
                    "registration_request_id": ctx["request"]["id"],
                    "termination_reason": "DISCHARGED",
                    "termination_date": "2026-07-31",
                },
                make_user_headers("rp-cascade-u5", "RegistrationPrincipal"),
            ),
            expected_status=201,
        )
        assert u5["status"] == "FILED"

        # Hop 1: the registration itself.
        assert get_request(ctx["request"]["id"])["status"] == "TERMINATED"
        # Hop 2: the affiliation built on it.
        assert get_affiliation(affiliation["id"])["status"] == "REVOKED"
        # Hop 3: the issued invoice hanging on the request.
        assert get_invoice(invoice["id"])["status"] == "VOID"
        # Termination link: approved selections relinquished.
        sel = get_selection(ctx["selections"]["CA"]["id"])
        assert sel["status"] == "RELINQUISHED"

    def test_u5_termination_cascade_voids_invoice_and_stamps_filing(self, api):
        """PRD Section 3.9: "The filing enters `FILED` status, and the
        registration itself cascades: the request moves `ACTIVE → TERMINATED`
        with its `version` incremented ... every renewal invoice still
        `ISSUED` for the request is voided to `VOID`". PRD Section 3.7: "the
        desk auto-voids any invoice still `ISSUED` the moment its registration
        leaves `ACTIVE` — whether by withdrawal (§3.5) or by termination
        (§3.9)."

        Design: Difficulty/transitive_cascade/u5_termination_three_hop_cascade
        """
        ctx = create_active_registration_with_invoice(
            cycle_year=2027,
            invoice_clock="2026-12-01T00:00:00Z",
            submitter_user_id="rp-cascade3",
            reviewer_user_id="co-cascade3",
        )
        invoice = ctx["invoice"]
        set_clock("2027-01-10T00:00:00Z")
        u5 = validate_success(
            api.create_termination_filing(
                {
                    "registration_request_id": ctx["request"]["id"],
                    "termination_reason": "VOLUNTARY",
                    "termination_date": "2027-01-09",
                },
                make_user_headers("rp-cascade3-u5", "RegistrationPrincipal"),
            ),
            expected_status=201,
        )
        assert u5["status"] == "FILED"
        assert get_request(ctx["request"]["id"])["status"] == "TERMINATED"
        assert get_invoice(invoice["id"])["status"] == "VOID"


class TestU5CloseAndComments:
    def test_u5_close_blocked_by_inconsistent_comment(self, api):
        """PRD Section 3.9: "The contradiction map is fixed: a `VOLUNTARY`
        termination forbids the substrings "fired", "discharged", and
        "terminated for cause"". PRD Section 3.9: "The comment's score is the
        number of forbidden substrings present in its text: a score of zero
        leaves the comment `CONSISTENT`, and a score of one or more marks it
        `INCONSISTENT`. Anything short of all-`CONSISTENT` comments blocks
        both the close-amendment action above and the final close below."

        Design: Corner/state_machines/u5_close_blocked_by_inconsistent_comment
        """
        ctx = create_terminated_registration(
            termination_reason="VOLUNTARY",
            termination_date="2026-06-03",
            filing_clock="2026-06-03T00:00:00Z",
            filer_user_id="rp-cm-filer",
            category="IA",
            jurisdictions=("CA",),
            submitter_user_id="rp-cm",
            reviewer_user_id="co-cm",
        )
        u5 = ctx["u5"]
        comment = validate_success(
            api.create_u5_comment(
                {
                    "termination_filing_id": u5["id"],
                    "comment_text": "He was fired for cause after the incident.",
                },
                make_user_headers("rp-cm-commenter", "RegistrationPrincipal"),
            ),
            expected_status=201,
        )
        assert comment["disposition"] == "INCONSISTENT"

        resp = api.close_termination_filing(
            u5["id"], make_user_headers("co-cm-closer", "ComplianceOfficer")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestImmediateConsistency:
    def test_immediate_consistency_of_cascade(self, api):
        """PRD Section 3.9: "Filing stamps `filed_at` ... The filing enters
        `FILED` status, and the registration itself cascades: the request
        moves `ACTIVE → TERMINATED` with its `version` incremented". The
        cascade is part of the filing call itself, so the response and any
        subsequent read agree.

        Design: Corner/consistency_model/immediate_consistency_of_cascade
        """
        ctx = create_active_registration(
            category="IA",
            jurisdictions=("CA",),
            submitter_user_id="rp-im",
            reviewer_user_id="co-im",
        )
        set_clock("2026-08-01T00:00:00Z")
        u5 = validate_success(
            api.create_termination_filing(
                {
                    "registration_request_id": ctx["request"]["id"],
                    "termination_reason": "PERMITTED_TO_RESIGN",
                    "termination_date": "2026-07-31",
                },
                make_user_headers("rp-im-u5", "RegistrationPrincipal"),
            ),
            expected_status=201,
        )
        assert u5["status"] == "FILED"
        # A read in the same instant shows the terminated registration.
        assert get_request(ctx["request"]["id"])["status"] == "TERMINATED"
