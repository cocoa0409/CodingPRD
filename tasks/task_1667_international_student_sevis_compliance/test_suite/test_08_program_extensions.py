"""Program extension proration, supersede cascade, timing gate, and OCC
claims (PRD §2.8, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_i20_form,
    assert_program_extension,
    create_extension,
    decide_extension,
    get_i20_form,
    get_record,
    issue_endorsement,
    review_document,
    set_clock,
    setup_active_student,
    setup_extension_requested,
    submit_document,
    validate_error,
    validate_paginated,
    validate_success,
)

_PRORATED_LINES = {
    "tuition_cents": 100001,
    "living_cents": 55557,
    "insurance_cents": 33333,
    "other_cents": 11113,
}


class TestExtensionProrationPerLineRounding:
    """Per-line round-half-up, then sum: 76 days -> 3 months."""

    def _setup(self):
        return setup_extension_requested(
            new_program_end_date="2027-08-15",
            reason="Thesis completion",
            funding_cents=250000,
            i20_overrides=dict(_PRORATED_LINES),
        )

    def _replacement_form(self, api, dso_headers, old_i20_id):
        data, meta = validate_paginated(
            api.list_i20_forms(dso_headers,
                               params={"supersedes_i20_form_id": old_i20_id})
        )
        assert meta["total_count"] == 1
        return data[0]

    def test_extension_proration_rounds_per_line_then_sums(self, api, dso_headers):
        """PRD §3.8: "The day gap between the current `program_end_date` and the
        `new_program_end_date` is converted to whole months by dividing by 30
        and rounding up. Each of the four lines — tuition, living, insurance,
        other — is treated as an annual basis: the line's cents figure is
        multiplied by the extended month count, divided by 12, and rounded
        half-up to whole cents, line by line. The replacement form's
        `estimated_total_cents` is then the integer sum of those four
        already-rounded lines."

        Design: Difficulty/combinatorial_formula/extension_proration_per_line_rounding
        """
        ctx = self._setup()
        decide_extension(ctx["extension"]["id"], "APPROVED")
        new_form = self._replacement_form(api, dso_headers, ctx["i20"]["id"])
        assert_i20_form(new_form)
        # 2027-05-31 -> 2027-08-15 is 76 days -> ceil(76/30) = 3 months.
        assert new_form["tuition_cents"] == 25000     # round_half_up(25000.25)
        assert new_form["living_cents"] == 13889      # round_half_up(13889.25)
        assert new_form["insurance_cents"] == 8333    # round_half_up(8333.25)
        assert new_form["other_cents"] == 2778        # round_half_up(2778.25)
        # Per-line-then-sum is the contract: 25000+13889+8333+2778 == 50000
        # (sum-then-round of the raw values would yield 50001).
        assert new_form["estimated_total_cents"] == 50000

    def test_extension_approval_issues_replacement_and_supersedes_prior(
        self, api, dso_headers,
    ):
        """PRD §3.8: "Approval executes a coordinated multi-entity update. The
        record's `program_end_date` advances to the approved
        `new_program_end_date`, and the record's `version` increments again. A
        new I-20 is auto-created and immediately issued with the prorated cost
        lines, naming the previously issued form as its
        `supersedes_i20_form_id`. That prior form transitions from `ISSUED` to
        `SUPERSEDED`, and each of its `ACTIVE` travel endorsements is voided to
        `VOIDED`."

        Design: Difficulty/combinatorial_formula/extension_proration_per_line_rounding
        """
        ctx = self._setup()
        decide_extension(ctx["extension"]["id"], "APPROVED")
        new_form = self._replacement_form(api, dso_headers, ctx["i20"]["id"])
        assert new_form["status"] == "ISSUED"
        assert new_form["supersedes_i20_form_id"] == ctx["i20"]["id"]
        assert get_i20_form(ctx["i20"]["id"])["status"] == "SUPERSEDED"
        assert get_record(ctx["student"]["id"])["program_end_date"] == "2027-08-15"


class TestExtensionApprovalSupersedeVoidsEndorsements:
    """Approval supersedes the ISSUED form; supersede voids its endorsements."""

    def _setup(self):
        ctx = setup_extension_requested(new_program_end_date="2027-06-30",
                                        reason="Research delay")
        endorsement = issue_endorsement(ctx["i20"]["id"], "2026-12-12", "2027-01-10")
        ctx["endorsement"] = endorsement
        return ctx

    def test_extension_approval_supersedes_prior_form(self, api, dso_headers):
        """PRD §3.8: "A new I-20 is auto-created and immediately issued with the
        prorated cost lines, naming the previously issued form as its
        `supersedes_i20_form_id`. That prior form transitions from `ISSUED` to
        `SUPERSEDED`, and each of its `ACTIVE` travel endorsements is voided to
        `VOIDED`."

        Design: Difficulty/transitive_cascade/extension_approval_supersede_voids_endorsements
        """
        ctx = self._setup()
        decide_extension(ctx["extension"]["id"], "APPROVED")

        assert get_i20_form(ctx["i20"]["id"])["status"] == "SUPERSEDED"
        data, meta = validate_paginated(
            api.list_i20_forms(dso_headers,
                               params={"supersedes_i20_form_id": ctx["i20"]["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["status"] == "ISSUED"
        assert data[0]["program_end_date"] == "2027-06-30"
        assert get_record(ctx["student"]["id"])["program_end_date"] == "2027-06-30"

    def test_extension_approval_voids_active_endorsements(self, api, dso_headers):
        """PRD §3.8: "That prior form transitions from `ISSUED` to `SUPERSEDED`,
        and each of its `ACTIVE` travel endorsements is voided to `VOIDED`."
        PRD §3.6: "And whenever the parent form is superseded or cancelled, each
        of its `ACTIVE` endorsements is voided to `VOIDED` — this is how both
        the program-extension auto-issue in §3.8 and record termination in §3.9
        retire outstanding signatures."

        Design: Difficulty/transitive_cascade/extension_approval_supersede_voids_endorsements
        """
        ctx = self._setup()
        decide_extension(ctx["extension"]["id"], "APPROVED")
        endorsements, meta = validate_paginated(
            api.list_travel_endorsements(ctx["i20"]["id"], dso_headers)
        )
        assert meta["total_count"] == 1
        assert endorsements[0]["id"] == ctx["endorsement"]["id"]
        assert endorsements[0]["status"] == "VOIDED"


def test_extension_not_forward_returns_extension_not_forward(api, dso_headers):
    """PRD §3.8: "The new end date must be strictly later than the record's
    current `program_end_date` (otherwise `ERR_EXTENSION_NOT_FORWARD`)."

    Design: Corner/validations/extension_not_forward_returns_extension_not_forward
    """
    ctx = setup_active_student()
    record = get_record(ctx["student"]["id"])
    resp = api.create_program_extension(
        ctx["student"]["id"],
        {"new_program_end_date": "2027-05-31",  # equal to current end: not forward
         "reason": "No-op extension",
         "expected_sevis_record_version": record["version"]},
        dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_EXTENSION_NOT_FORWARD, 409)


def test_extension_decision_twice_returns_not_requested(api, dso_headers):
    """PRD §3.8: "Approving an extension requires the request in `REQUESTED`
    (otherwise `ERR_EXTENSION_NOT_REQUESTED`), the student's record `ACTIVE`
    (otherwise `ERR_RECORD_NOT_ACTIVE`), and the clock date on or before the
    current `program_end_date` — an extension decided after the program has
    already ended is rejected with `ERR_EXTENSION_WINDOW_CLOSED`."
    PRD §3.8: "Denial requires only the `REQUESTED` state; both decisions accept
    an optional `note` recorded as `decision_note`, and both outcomes are
    terminal."

    Design: Corner/validations/extension_decision_twice_returns_not_requested
    """
    ctx = setup_extension_requested(new_program_end_date="2027-06-30",
                                    reason="Research delay")
    approved = decide_extension(ctx["extension"]["id"], "APPROVED")
    assert_program_extension(approved)
    assert approved["status"] == "APPROVED"
    resp = api.decide_program_extension(
        ctx["extension"]["id"], {"decision": "DENIED"}, dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_EXTENSION_NOT_REQUESTED, 409)


def test_extension_request_stale_record_version_returns_412(api, dso_headers):
    """PRD §2.8: "Requesting a program extension requires the request to carry
    `expected_sevis_record_version` equal to the student's SEVIS record's
    current `version`. A mismatch is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.8: "Filing the request lands it in `REQUESTED` and increments the
    SEVIS record's `version` by one."

    Design: Corner/cross_cutting_layers/extension_request_stale_record_version_returns_412
    """
    ctx = setup_active_student()
    student_id = ctx["student"]["id"]
    record_version = get_record(student_id)["version"]

    first = validate_success(
        api.create_program_extension(
            student_id,
            {"new_program_end_date": "2027-06-30", "reason": "Research delay",
             "expected_sevis_record_version": record_version},
            dso_headers,
        ),
        201,
    )
    assert first["status"] == "REQUESTED"

    # The first filing advanced the record version by one; the same observed
    # version is now stale for a second writer.
    resp = api.create_program_extension(
        student_id,
        {"new_program_end_date": "2027-08-15",
         "reason": "Second requester with stale view",
         "expected_sevis_record_version": record_version},
        dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    assert get_record(student_id)["version"] == record_version + 1, (
        "exactly one extension request mutated the record"
    )


class TestExtensionApproveTemporalBeatsFiscal:
    """Priority pair: deadline rule (band 8) beats funding sufficiency (band 9)
    at extension approval."""

    def test_approval_past_program_end_reports_window_closed_with_stale_funding(
        self, api, dso_headers,
    ):
        """PRD §2.9: "When a single request would violate several rules, the
        system reports the first applicable failure in a fixed priority order
        rather than an arbitrary one:"
        PRD §2.9: "8. **Deadline and window rules.** Registration deadline
        (`ERR_REGISTRATION_DEADLINE_PASSED`), RCL add/drop close
        (`ERR_RCL_ADD_DROP_CLOSED`), enrollment-credit edits after add/drop
        (`ERR_ADD_DROP_CLOSED`), OPT filing and OPT_POST start windows
        (`ERR_OPT_WINDOW_CLOSED`), CPT/OPT_PRE end-date containment
        (`ERR_AUTH_WINDOW_INVALID`), extension-approval cutoff
        (`ERR_EXTENSION_WINDOW_CLOSED`), extension forward-progress
        (`ERR_EXTENSION_NOT_FORWARD`), and the FINAL_TERM containment check
        (`ERR_RCL_NOT_FINAL_TERM`)."
        PRD §2.9: "9. **Funding sufficiency.** Verified fresh funding must cover
        the relevant cost figure at I-20 issuance and at extension approval
        (`ERR_INSUFFICIENT_VERIFIED_FUNDING`, HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/extension_approve_temporal_beats_fiscal
        """
        ctx = setup_extension_requested(new_program_end_date="2027-08-15",
                                        reason="Thesis completion")
        # Past current program_end 2027-05-31; the 2026-07-01 funding document
        # is also 349 days old and therefore stale (funding would fail too).
        set_clock("2027-06-15T00:00:00Z")
        resp = api.decide_program_extension(
            ctx["extension"]["id"], {"decision": "APPROVED"}, dso_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EXTENSION_WINDOW_CLOSED, 409)

    def test_approval_past_program_end_reports_window_closed_with_thin_funding(
        self, api, dso_headers,
    ):
        """PRD §3.8: "Approving an extension requires the request in `REQUESTED`
        (otherwise `ERR_EXTENSION_NOT_REQUESTED`), the student's record `ACTIVE`
        (otherwise `ERR_RECORD_NOT_ACTIVE`), and the clock date on or before the
        current `program_end_date` — an extension decided after the program has
        already ended is rejected with `ERR_EXTENSION_WINDOW_CLOSED`."
        PRD §3.8: "The funding check reuses the verified-fresh-funding
        computation of §3.2: verified documents within the 183-day freshness
        window must cover the prorated extension cost, with a shortfall rejected
        as `ERR_INSUFFICIENT_VERIFIED_FUNDING` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/extension_approve_temporal_beats_fiscal
        """
        ctx = setup_extension_requested(new_program_end_date="2027-08-15",
                                        reason="Thesis completion")
        # Add a fresh but insufficient verified document (1,000 cents), so the
        # fiscal rule would fail on its own merits at decision time.
        set_clock("2027-01-15T00:00:00Z")
        doc = submit_document(ctx["student"]["id"], 1000, "2027-01-10")
        review_document(doc["id"], "VERIFIED")
        # Past current program_end 2027-05-31: temporal rule applies too and
        # must be reported first.
        set_clock("2027-06-15T00:00:00Z")
        resp = api.decide_program_extension(
            ctx["extension"]["id"], {"decision": "APPROVED"}, dso_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EXTENSION_WINDOW_CLOSED, 409)
