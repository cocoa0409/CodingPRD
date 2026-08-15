"""Split-set negotiation: line ownership gates, pool-sum and participant
constraints, the dispute-revise cycle, supersede cardinality, and the
optimistic-concurrency guard on set creation."""
from test_helpers import (
    ApiErrorId,
    confirm_all_split_lines,
    create_split_set,
    create_split_set_payload,
    create_work,
    create_writer,
    get_work,
    list_split_lines,
    make_writer_headers,
    publisher_split_line,
    submit_split_set,
    validate_error,
    validate_paginated,
    validate_success,
    writer_split_line,
)
from test_helpers.fixtures import ADMIN


def _get_split_set(api, split_set_id):
    return validate_success(api.get_split_set(split_set_id, ADMIN))


class TestLineConfirmationGates:
    def test_split_line_confirm_before_submit_rejected(self, api):
        """PRD §3.3: "Both actions are permitted only while the parent set is `PENDING_CONFIRMATIONS` (else `ERR_INVALID_STATE_TRANSITION`), and both enforce the same ownership rule: a `WRITER` line may be confirmed or rejected only by a `Writer` caller whose `X-User-ID` equals the line's `writer_id` — a `PublisherAdmin` may not touch a `WRITER` line at all — while a `PUBLISHER` line may be confirmed or rejected only by a `PublisherAdmin`."

        Design: Corner/state_machines/split_line_confirm_before_submit_rejected
        """
        writer = create_writer(legal_name="W1")
        work = create_work(title="Early Confirm Song")
        split_set = create_split_set(work["id"], [(writer["id"], 10000)])
        assert split_set["status"] == "DRAFT"
        line = list_split_lines(split_set["id"])[0]

        resp = api.confirm_split_line(line["id"],
                                      make_writer_headers(writer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_split_line_double_confirm_rejected(self, api):
        """PRD §3.3: "Confirming a line moves it from `PENDING` to `CONFIRMED` and stamps `confirmed_at` from the logical clock; rejecting one moves it to `REJECTED` and stores the supplied `reason` in the line's `rejection_reason`. Both actions are permitted only while the parent set is `PENDING_CONFIRMATIONS` (else `ERR_INVALID_STATE_TRANSITION`)"

        Design: Corner/state_machines/split_line_double_confirm_rejected
        """
        writer = create_writer(legal_name="W1")
        work = create_work(title="Double Confirm Song")
        split_set = create_split_set(work["id"], [(writer["id"], 10000)])
        submit_split_set(split_set["id"])
        line = list_split_lines(split_set["id"])[0]

        confirmed = validate_success(api.confirm_split_line(
            line["id"], make_writer_headers(writer["id"])))
        assert confirmed["confirmation_status"] == "CONFIRMED"
        assert confirmed["confirmed_at"] is not None

        resp = api.confirm_split_line(line["id"],
                                      make_writer_headers(writer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestCreateConstraints:
    def test_split_pool_sum_invalid_rejected(self, api):
        """PRD §3.3: "The writer pool — the sum of `share_bp` over all `WRITER` lines — must total exactly 10000 basis points, and independently the publisher pool must total exactly 10000 basis points; any other sum is rejected with `ERR_SPLIT_SUM_INVALID`."

        Design: Corner/validations/split_pool_sum_invalid_rejected
        """
        writer = create_writer(legal_name="W1")
        work = create_work(title="Bad Sum Song")
        lines = [writer_split_line(writer["id"], 9000),
                 publisher_split_line("OurPub", 10000)]
        resp = api.create_split_set(
            create_split_set_payload(work["id"], work["version"], lines), ADMIN)
        validate_error(resp, ApiErrorId.ERR_SPLIT_SUM_INVALID)

    def test_duplicate_split_participant_rejected(self, api):
        """PRD §3.3: "And no `writer_id` may appear twice, nor any `publisher_name` twice, within one set; duplicates are rejected with `ERR_DUPLICATE_SPLIT_PARTICIPANT`."

        Design: Corner/validations/duplicate_split_participant_rejected
        """
        writer = create_writer(legal_name="W1")
        work = create_work(title="Dup Split Song")
        lines = [writer_split_line(writer["id"], 6000),
                 writer_split_line(writer["id"], 4000),
                 publisher_split_line("OurPub", 10000)]
        resp = api.create_split_set(
            create_split_set_payload(work["id"], work["version"], lines), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SPLIT_PARTICIPANT)

    def test_zero_share_bp_rejected_on_split_set_create(self, api):
        """PRD §3.3: "Every line's `share_bp` must be at least 1; a zero-share line is rejected with `ERR_ZERO_SHARE_LINE`."

        Design: Difficulty/boundary_precision_check/zero_share_bp_rejected_on_split_set_create
        """
        w1 = create_writer(legal_name="W1")
        w2 = create_writer(legal_name="W2", pro_affiliation="BMI")
        work = create_work(title="Zero Song")
        # Writer pool still sums to 10000, but one line carries a zero share.
        lines = [writer_split_line(w1["id"], 10000),
                 writer_split_line(w2["id"], 0),
                 publisher_split_line("OurPub", 10000)]
        resp = api.create_split_set(
            create_split_set_payload(work["id"], work["version"], lines), ADMIN)
        validate_error(resp, ApiErrorId.ERR_ZERO_SHARE_LINE)

    def test_zero_share_bp_boundary_one_accepted(self, api):
        """PRD §3.3: "Every line's `share_bp` must be at least 1; a zero-share line is rejected with `ERR_ZERO_SHARE_LINE`."
        PRD §3.3: "The writer pool — the sum of `share_bp` over all `WRITER` lines — must total exactly 10000 basis points, and independently the publisher pool must total exactly 10000 basis points; any other sum is rejected with `ERR_SPLIT_SUM_INVALID`."

        Design: Difficulty/boundary_precision_check/zero_share_bp_rejected_on_split_set_create
        """
        w1 = create_writer(legal_name="W1")
        w2 = create_writer(legal_name="W2", pro_affiliation="BMI")
        work = create_work(title="One Song")
        lines = [writer_split_line(w1["id"], 9999),
                 writer_split_line(w2["id"], 1),
                 publisher_split_line("OurPub", 10000)]
        data = validate_success(
            api.create_split_set(
                create_split_set_payload(work["id"], work["version"], lines),
                ADMIN),
            201)
        assert data["status"] == "DRAFT", "share_bp == 1 is the valid boundary"


class TestDisputeRevisionCycle:
    def _setup_pending_set(self):
        w1 = create_writer(legal_name="W1")
        w2 = create_writer(legal_name="W2", pro_affiliation="BMI")
        work = create_work(title="Cycle Song")
        split_set = create_split_set(
            work["id"], [(w1["id"], 6000), (w2["id"], 4000)])
        submit_split_set(split_set["id"])
        lines = list_split_lines(split_set["id"])
        return w1, w2, work, split_set, lines

    def test_dispute_then_revise_returns_to_draft(self, api):
        """PRD §3.3: "When any line of a set is rejected, the set immediately moves from `PENDING_CONFIRMATIONS` to `DISPUTED`, and the set's `dispute_reason` is copied from the rejecting line's reason."
        PRD §3.3: "revising a `DISPUTED` set — again a `PublisherAdmin` action, from no other state — deletes all of the set's existing lines, replaces them with the `lines` supplied in the revise call (each fresh line starting `PENDING`), clears `dispute_reason` to null, and returns the set to `DRAFT`, ready to be submitted again."

        Design: Difficulty/non_linear_state_machine/split_set_dispute_revision_cycle
        """
        w1, w2, work, split_set, lines = self._setup_pending_set()

        rejected = validate_success(api.reject_split_line(
            lines[1]["id"], "share too low", make_writer_headers(w2["id"])))
        assert rejected["confirmation_status"] == "REJECTED"

        disputed = _get_split_set(api, split_set["id"])
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "share too low", (
            "dispute_reason is copied from the rejecting line's reason")

        new_lines = [writer_split_line(w1["id"], 5000),
                     writer_split_line(w2["id"], 5000),
                     publisher_split_line("OurPub", 10000)]
        revised = validate_success(
            api.revise_split_set(split_set["id"], new_lines, ADMIN))
        assert revised["status"] == "DRAFT"
        assert revised["dispute_reason"] is None

        fresh = list_split_lines(split_set["id"])
        assert len(fresh) == 3, "revise replaces all lines"
        assert all(l["confirmation_status"] == "PENDING" for l in fresh)
        assert fresh[0]["share_bp"] == 5000
        assert {l["id"] for l in fresh}.isdisjoint({l["id"] for l in lines}), (
            "old lines must be deleted and replaced")

    def test_revised_set_confirms_to_confirmed(self, api):
        """PRD §3.3: "When the last `PENDING` line of a set becomes `CONFIRMED` — that is, when every line has confirmed — the set moves from `PENDING_CONFIRMATIONS` to `CONFIRMED`, and any other SplitSet of the same work that was `CONFIRMED` is moved to `SUPERSEDED`; the Work's `version` increments."
        PRD §3.3: "Note that only a `DRAFT` set can be submitted, so a revised set must go back through submission before lines can confirm."

        Design: Difficulty/non_linear_state_machine/split_set_dispute_revision_cycle
        """
        w1, w2, work, split_set, lines = self._setup_pending_set()
        validate_success(api.reject_split_line(
            lines[1]["id"], "share too low", make_writer_headers(w2["id"])))
        new_lines = [writer_split_line(w1["id"], 5000),
                     writer_split_line(w2["id"], 5000),
                     publisher_split_line("OurPub", 10000)]
        validate_success(api.revise_split_set(split_set["id"], new_lines, ADMIN))

        submit_split_set(split_set["id"])
        confirm_all_split_lines(split_set["id"])

        final = _get_split_set(api, split_set["id"])
        assert final["status"] == "CONFIRMED", (
            "DRAFT -> PENDING_CONFIRMATIONS -> DISPUTED -> DRAFT -> "
            "PENDING_CONFIRMATIONS -> CONFIRMED cycle must complete")


class TestSupersedeCardinality:
    def _setup_two_sets(self):
        w1 = create_writer(legal_name="W1")
        w2 = create_writer(legal_name="W2", pro_affiliation="BMI")
        work = create_work(title="Split Song")
        set_a = create_split_set(work["id"], [(w1["id"], 10000)])
        submit_split_set(set_a["id"])
        confirm_all_split_lines(set_a["id"])
        return w1, w2, work, set_a

    def test_newer_confirmation_supersedes_previous_confirmed_set(self, api):
        """PRD §3.3: "When the last `PENDING` line of a set becomes `CONFIRMED` — that is, when every line has confirmed — the set moves from `PENDING_CONFIRMATIONS` to `CONFIRMED`, and any other SplitSet of the same work that was `CONFIRMED` is moved to `SUPERSEDED`; the Work's `version` increments."

        Design: Difficulty/compensating_invariant/confirmed_split_set_cardinality_conserved_across_supersede
        """
        w1, w2, work, set_a = self._setup_two_sets()
        assert _get_split_set(api, set_a["id"])["status"] == "CONFIRMED"

        set_b = create_split_set(work["id"],
                                 [(w1["id"], 5000), (w2["id"], 5000)])
        submit_split_set(set_b["id"])
        confirm_all_split_lines(set_b["id"])

        assert _get_split_set(api, set_b["id"])["status"] == "CONFIRMED"
        assert _get_split_set(api, set_a["id"])["status"] == "SUPERSEDED", (
            "the previously CONFIRMED set must be superseded")

    def test_confirmed_cardinality_conserved_at_one(self, api):
        """PRD §3.3: "any other SplitSet of the same work that was `CONFIRMED` is moved to `SUPERSEDED`; the Work's `version` increments."
        PRD §3.3: "The split-sets list accepts optional `work_id` and `status` filters"

        Design: Difficulty/compensating_invariant/confirmed_split_set_cardinality_conserved_across_supersede
        """
        w1, w2, work, set_a = self._setup_two_sets()
        before, meta_before = validate_paginated(
            api.list_split_sets(
                ADMIN, params={"work_id": work["id"], "status": "CONFIRMED"}))
        assert len(before) == 1 and before[0]["id"] == set_a["id"], (
            "exactly one CONFIRMED set exists before the new confirmation")

        set_b = create_split_set(work["id"],
                                 [(w1["id"], 5000), (w2["id"], 5000)])
        submit_split_set(set_b["id"])
        confirm_all_split_lines(set_b["id"])

        after, meta_after = validate_paginated(
            api.list_split_sets(
                ADMIN, params={"work_id": work["id"], "status": "CONFIRMED"}))
        assert len(after) == 1 and after[0]["id"] == set_b["id"], (
            "count(CONFIRMED) is conserved at exactly 1 across the supersede")


class TestSplitSetOptimisticConcurrency:
    def test_occ_split_set_create_stale_version_rejected(self, api):
        """PRD §2.7: "Creating a SplitSet requires the request to carry `expected_work_version`, holding the `version` of the target Work as the client last observed it. If that value does not equal the Work's current `version` at the moment of creation — for example because another revision was created in the meantime, or a confirmation cascade advanced the Work — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.4: "creating a SplitSet increments the parent Work's `version` by 1, and creating an Advance increments the parent Writer's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_split_set_create_stale_version_rejected
        """
        w1 = create_writer(legal_name="W1")
        work = create_work(title="OCC Song")
        observed_version = work["version"]

        def _create(expected_version):
            lines = [writer_split_line(w1["id"], 10000),
                     publisher_split_line("OurPub", 10000)]
            return api.create_split_set(
                create_split_set_payload(work["id"], expected_version, lines),
                ADMIN)

        first = validate_success(_create(observed_version), 201)
        assert first["status"] == "DRAFT"

        stale = _create(observed_version)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_work(work["id"])["version"]
        assert fresh_version == observed_version + 1, (
            "the first create bumped the work version, staling the observation")

        second = validate_success(_create(fresh_version), 201)
        assert second["id"] != first["id"]
        assert get_work(work["id"])["version"] == fresh_version + 1
