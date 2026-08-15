"""I-20 creation totals, issuance gate, funding variants, and supersession
invariants (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_i20_form,
    create_i20_form,
    create_sevis_record,
    create_student,
    get_i20_form,
    get_record,
    issue_i20_form,
    review_document,
    set_clock,
    setup_active_student,
    setup_student_with_issued_i20,
    submit_document,
    submit_verified_document,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_estimated_total_sums_cost_lines(api, dso_headers):
    """PRD §3.2: "The form's `estimated_total_cents` is the integer sum of
    those four lines."
    PRD §3.2: "New forms land in `DRAFT` status."

    Design: Corner/calculations/estimated_total_sums_cost_lines
    """
    student = create_student()
    record = create_sevis_record(student["id"])
    resp = api.create_i20_form(
        student["id"],
        {
            "sevis_record_id": record["id"],
            "program_name": "Mechanical Engineering",
            "tuition_cents": 1200000,
            "living_cents": 600000,
            "insurance_cents": 120000,
            "other_cents": 60000,
        },
        dso_headers,
    )
    form = validate_success(resp, 201)
    assert_i20_form(form)
    assert form["estimated_total_cents"] == 1980000
    assert form["status"] == "DRAFT"


def test_get_i20_not_found_returns_404(api, dso_headers):
    """PRD §2.6: "A request naming a nonexistent student is rejected with
    `ERR_STUDENT_NOT_FOUND`; a request naming a nonexistent non-student
    resource is rejected with `ERR_NOT_FOUND`."

    Design: Corner/endpoints/get_i20_not_found_returns_404
    """
    set_clock("2026-08-01T00:00:00Z")
    resp = api.get_i20_form("00000000-0000-0000-0000-000000000000", dso_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_i20_issue_from_issued_returns_not_draft(api, dso_headers):
    """PRD §3.2: "Issuance requires the form in `DRAFT` (otherwise
    `ERR_I20_NOT_DRAFT`), the parent record in `DRAFT`, `INITIAL`, or `ACTIVE`
    (otherwise `ERR_RECORD_NOT_ACTIVE`)".

    Design: Corner/state_machines/i20_issue_from_issued_returns_not_draft
    """
    ctx = setup_student_with_issued_i20()
    resp = api.issue_i20_form(ctx["i20"]["id"], dso_headers)
    validate_error(resp, ApiErrorId.ERR_I20_NOT_DRAFT, 409)
    assert get_i20_form(ctx["i20"]["id"])["status"] == "ISSUED"


class TestFundingProvisionalVsVerifiedGate:
    """Dual-variant funding computation at the issuance gate (PRD §3.2)."""

    def _setup(self, api, dso_headers):
        # Doc A VERIFIED 5,000,000; doc B SUBMITTED 2,000,000; I-20 total
        # 6,500,000 (provisional 7,000,000 >= total, verified 5,000,000 < total).
        set_clock("2026-08-01T00:00:00Z")
        student = create_student()
        record = create_sevis_record(student["id"])
        doc_a = submit_document(student["id"], 5000000, "2026-07-01", "BANK_STATEMENT")
        review_document(doc_a["id"], "VERIFIED")
        doc_b = submit_document(student["id"], 2000000, "2026-07-15", "SPONSOR_AFFIDAVIT")
        i20 = create_i20_form(
            student["id"], record["id"],
            tuition_cents=4000000, living_cents=1800000,
            insurance_cents=400000, other_cents=300000,
        )
        return student, doc_b, i20

    def test_issue_blocked_until_all_documents_verified(self, api, dso_headers):
        """PRD §3.2: "Verified funding is the sum of `amount_usd_cents` over the
        student's documents that are in `VERIFIED` status and within the 183-day
        freshness window at issuance time; falling short is rejected with
        `ERR_INSUFFICIENT_VERIFIED_FUNDING` (HTTP 402)."
        PRD §3.2: "A second, advisory figure — `provisional_funding_cents` — is
        computed the same way but also counts documents still in `SUBMITTED`
        status, so it is at least as large as the verified figure whenever
        unverified documents exist."

        Design: Difficulty/dual_variant_calc/funding_provisional_vs_verified_gate
        """
        _student, _doc_b, i20 = self._setup(api, dso_headers)
        resp = api.issue_i20_form(i20["id"], dso_headers)
        # Provisional coverage (7,000,000) already suffices, but the gate reads
        # the verified variant (5,000,000 < 6,500,000).
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VERIFIED_FUNDING, 402)
        assert get_i20_form(i20["id"])["status"] == "DRAFT"

    def test_issue_snapshots_verified_and_provisional_funding(self, api, dso_headers):
        """PRD §3.2: "Both figures are snapshotted onto the form at issuance and
        returned with it thereafter."
        PRD §3.2: "A second, advisory figure — `provisional_funding_cents` — is
        computed the same way but also counts documents still in `SUBMITTED`
        status, so it is at least as large as the verified figure whenever
        unverified documents exist."

        Design: Difficulty/dual_variant_calc/funding_provisional_vs_verified_gate
        """
        _student, doc_b, i20 = self._setup(api, dso_headers)
        validate_error(
            api.issue_i20_form(i20["id"], dso_headers),
            ApiErrorId.ERR_INSUFFICIENT_VERIFIED_FUNDING, 402,
        )
        review_document(doc_b["id"], "VERIFIED")
        issued = validate_success(api.issue_i20_form(i20["id"], dso_headers), 200)
        assert_i20_form(issued)
        assert issued["status"] == "ISSUED"
        assert issued["verified_funding_cents"] == 7000000
        assert issued["provisional_funding_cents"] == 7000000


class TestIssuedI20CountConservedUnderSupersede:
    """Program-change reissue keeps exactly one ISSUED form per record."""

    def _reissue(self, api, dso_headers):
        ctx = setup_active_student()
        student_id = ctx["student"]["id"]
        record_id = ctx["record"]["id"]
        old_form = ctx["i20"]
        new_form = create_i20_form(
            student_id, record_id,
            program_name="Computer Science",
            supersedes_i20_form_id=old_form["id"],
        )
        return ctx, old_form, new_form

    def test_program_change_reissue_supersedes_prior_form(self, api, dso_headers):
        """PRD §3.2: "A program change is expressed by drafting a form whose
        `supersedes_i20_form_id` names the currently `ISSUED` form it replaces;
        the field is otherwise unset."
        PRD §3.2: "When the new form names a `supersedes_i20_form_id`, the prior
        form transitions from `ISSUED` to `SUPERSEDED`, and every `ACTIVE`
        travel endorsement on the superseded form is voided to `VOIDED`."

        Design: Difficulty/compensating_invariant/issued_i20_count_conserved_under_supersede
        """
        _ctx, old_form, new_form = self._reissue(api, dso_headers)
        issued = issue_i20_form(new_form["id"])
        assert issued["status"] == "ISSUED"
        assert issued["program_name"] == "Computer Science"
        assert get_i20_form(old_form["id"])["status"] == "SUPERSEDED"

    def test_exactly_one_issued_form_after_reissue(self, api, dso_headers):
        """PRD §3.2: "When the new form names a `supersedes_i20_form_id`, the
        prior form transitions from `ISSUED` to `SUPERSEDED`, and every `ACTIVE`
        travel endorsement on the superseded form is voided to `VOIDED`."
        PRD §3.2: "Forms may be listed with the filters `student_id`,
        `sevis_record_id`, `supersedes_i20_form_id`, and `status`."

        Design: Difficulty/compensating_invariant/issued_i20_count_conserved_under_supersede
        """
        ctx, _old_form, new_form = self._reissue(api, dso_headers)
        issue_i20_form(new_form["id"])
        data, meta = validate_paginated(
            api.list_i20_forms(
                dso_headers,
                params={"sevis_record_id": ctx["record"]["id"], "status": "ISSUED"},
            )
        )
        assert meta["total_count"] == 1, (
            f"exactly one ISSUED form per record, got {meta['total_count']}"
        )
        assert data[0]["id"] == new_form["id"]
