"""Optimistic concurrency and the immediate consistency model.

Every test here translates exactly one instance of the corner design index,
sections `cross_cutting_complexity_layers` and `consistency_model`.  The three
concurrency instances are all *sequential* stale-version probes — read a
`version`, let another accepted write advance it, then send the old value — so
their outcome is pinned by the PRD's ladder rather than by an interleaving the
PRD never fixes.

Each test builds its own preconditions from scratch: the harness restarts the
server first, so every test starts against an empty database whose logical clock
reads its startup value of 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_score,
    create_bond_issue,
    create_engagement,
    create_event_filing,
    create_notice,
    determine_notice,
    engagement_payload,
    filing_payload,
    issue_version,
    list_content_items,
    make_agent_headers,
    make_finance_director_headers,
    make_officer_headers,
    rating_action_payload,
    read_bond_issue,
    read_content_item,
    read_cycle,
    read_engagement,
    read_notice,
    read_undertaking,
    ready_item,
    record_rating_action,
    reinstate_undertaking,
    setup_cycle,
    setup_issue_with_undertaking,
    submit,
    suspend_undertaking,
    undertaking_version,
    validate_error,
    validate_paginated,
    validate_success,
    OFFICER_PREPARER_ID,
)

FD = make_finance_director_headers()
OFFICER = make_officer_headers()

# The design index registers every issue in this slice under one credit program.
ISSUE_OVERRIDES = {
    "issuer_program_code": "CIVICCENTER",
    "series_designation": "2026A",
    "security_type": "REVENUE",
    "dated_date": "2024-04-01",
    "final_maturity_date": "2056-04-01",
    "original_par_amount_cents": 100000000,
}


# --------------------------------------------------------------------------- #
# Module-local composite preconditions (fixtures.py builds no chain that pairs
# one MATERIAL notice with one DETERMINATION_PENDING notice on the same issue).
# --------------------------------------------------------------------------- #

def _setup_issue_with_two_notices() -> dict:
    """An OUTSTANDING issue with an ACTIVE undertaking, one notice determined
    MATERIAL and one notice left DETERMINATION_PENDING, plus the issue `version`
    the drafting client has observed."""
    context = setup_issue_with_undertaking(issue=dict(ISSUE_OVERRIDES))
    notice_ok = create_notice(
        context["issue"]["id"],
        event_type="TRUSTEE_SUBSTITUTION",
        occurrence_date="2026-07-28",
    )
    context["notice_ok"] = determine_notice(
        notice_ok["id"], "MATERIAL", determination_note="Successor trustee appointed."
    )
    context["notice_pending"] = create_notice(
        context["issue"]["id"],
        event_type="MERGER_OR_SALE",
        occurrence_date="2026-07-29",
    )
    context["v_obs"] = issue_version(context["issue"]["id"])
    return context


def _record_moodys_downgrade(issue_id: str, expected_issue_version: int) -> dict:
    """The unrelated accepted write that advances the issue's `version`."""
    return record_rating_action(
        issue_id,
        expected_issue_version=expected_issue_version,
        rating_agency="MOODYS",
        prior_rating="Aa2",
        new_rating="Aa3",
        occurrence_date="2026-07-30",
    )


def _draft_event_filing(issue_id: str, notice_id: str, expected_issue_version: int):
    """Raw response for a MATERIAL_EVENT_NOTICE draft on a pinned issue version."""
    return api_client.create_filing(
        filing_payload(
            issue_id,
            "MATERIAL_EVENT_NOTICE",
            expected_issue_version,
            material_event_id=notice_id,
        ),
        OFFICER,
    )


def _create_engagement_at_version(undertaking_id: str, expected_undertaking_version: int,
                                  **overrides):
    """Raw response for an engagement create on a pinned undertaking version."""
    payload = engagement_payload(
        undertaking_id,
        expected_undertaking_version,
        agent_name="Meridian Disclosure Services",
        effective_date="2026-07-20",
        expiration_date="2027-06-30",
        retainer_cents=250000,
    )
    payload.update(overrides)
    return api_client.create_engagement(payload, FD)


def _setup_submitted_event_filing() -> dict:
    """An ACTIVE engagement at retainer 250000 and a SUBMITTED
    MATERIAL_EVENT_NOTICE filing for a notice occurring 2026-07-28."""
    context = setup_issue_with_undertaking(issue=dict(ISSUE_OVERRIDES))
    context["engagement"] = create_engagement(
        context["undertaking"]["id"],
        agent_name="Meridian Disclosure Services",
        effective_date="2026-07-20",
        expiration_date="2027-06-30",
        retainer_cents=250000,
    )
    notice = create_notice(
        context["issue"]["id"],
        event_type="TRUSTEE_SUBSTITUTION",
        occurrence_date="2026-07-28",
    )
    context["notice"] = determine_notice(
        notice["id"], "MATERIAL", determination_note="Successor trustee appointed."
    )
    context["open_before"] = read_undertaking(
        context["undertaking"]["id"]
    )["open_obligation_count"]
    context["filing"] = create_event_filing(context["issue"]["id"], notice["id"])
    context["submitted"] = submit(context["filing"]["id"], context["engagement"]["id"])
    return context


def _setup_attested_cycle() -> dict:
    """A DRAFTING FY2026 cycle whose single 10000-bp OPERATING_DATA_TABLE item has
    been prepared and attested, so `completeness_score_pct` stands at 100.00."""
    context = setup_cycle(issue=dict(ISSUE_OVERRIDES))
    item = context["items"][0]
    context["item"] = ready_item(item["id"], context["requirements"][0])
    context["cycle"] = read_cycle(context["cycle"]["id"])
    return context


class TestFilingCreationVersionPrecondition:
    """POST /disclosure/filings guarded on `expected_issue_version` (PRD §2.8)."""

    def test_filing_creation_rejects_a_stale_view_of_the_issue(self):
        """A rating action advances the issue, so the drafting client's version is stale.

        PRD §2.8: "If another writer has advanced that issue's `version` since the client last read it — most commonly because a correcting filing for the same subject has already been opened, or because a defeasance has landed — the create is rejected with `ERR_ISSUE_VERSION_STALE` and HTTP 412."
        PRD §3.1: "The issue's own `current_rating` and `current_rating_agency` are overwritten with `new_rating` and `rating_agency`, the issue's `version` advances, and `open_material_event_count` on the issue and `open_obligation_count` on the undertaking are both recomputed."
        Design: Corner/cross_cutting_complexity_layers/filing_creation_rejects_a_stale_view_of_the_issue
        """
        context = _setup_issue_with_two_notices()
        assert context["notice_ok"]["status"] == "MATERIAL"
        assert context["notice_pending"]["status"] == "DETERMINATION_PENDING"
        v_obs = context["v_obs"]

        rating_notice = _record_moodys_downgrade(context["issue"]["id"], v_obs)
        assert rating_notice["event_type"] == "RATING_CHANGE"

        issue_after = read_bond_issue(context["issue"]["id"])
        assert issue_after["current_rating"] == "Aa3"
        assert issue_after["version"] == v_obs + 1

        response = _draft_event_filing(
            context["issue"]["id"], context["notice_ok"]["id"], v_obs
        )
        validate_error(response, ApiErrorId.ERR_ISSUE_VERSION_STALE.value)

    def test_staleness_is_reported_before_the_subject_state_complaint(self):
        """Priority 7 outranks the subject-state test, even on an unfileable subject.

        PRD §2.8: "The version comparison is evaluated before any state precondition on the target row, so a caller acting on stale data always learns that fact first rather than being told about a state conflict it could not have known about."
        PRD §3.7: "And the subject must be in its fileable state: for `ANNUAL_REPORT` the cycle must be `READY_TO_FILE`; for `FAILURE_TO_FILE_NOTICE` the cycle must be `DELINQUENT`; for `MATERIAL_EVENT_NOTICE` the notice must be `MATERIAL`; for `VOLUNTARY_FINANCIAL_OBLIGATION` the placement must be `DISCLOSURE_REQUIRED`."
        Design: Corner/cross_cutting_complexity_layers/filing_creation_rejects_a_stale_view_of_the_issue
        """
        context = _setup_issue_with_two_notices()
        v_obs = context["v_obs"]
        _record_moodys_downgrade(context["issue"]["id"], v_obs)
        v_new = issue_version(context["issue"]["id"])

        # The DETERMINATION_PENDING notice is genuinely unfileable, yet the stale
        # version is what the caller is told about first.
        stale_and_unfileable = _draft_event_filing(
            context["issue"]["id"], context["notice_pending"]["id"], v_obs
        )
        validate_error(stale_and_unfileable, ApiErrorId.ERR_ISSUE_VERSION_STALE.value)

        # With the version corrected, the subject complaint finally surfaces.
        unfileable_only = _draft_event_filing(
            context["issue"]["id"], context["notice_pending"]["id"], v_new
        )
        validate_error(unfileable_only, ApiErrorId.ERR_FILING_SUBJECT_MISMATCH.value)

    def test_the_observed_version_succeeds_and_the_refusals_left_no_draft(self):
        """Three refused attempts write nothing; the fourth, with the current version, drafts.

        PRD §3.7: "The draft opens at `status` `DRAFT`, `version` 1, `submission_attempt_count` 0, with `submitted_at`, `submitted_by_user_id`, `submitting_engagement_id`, `repository_receipt_id`, `repository_confirmed_at`, `rejection_reason`, and `superseded_by_filing_id` all null."
        PRD §2.8: "If another writer has advanced that issue's `version` since the client last read it — most commonly because a correcting filing for the same subject has already been opened, or because a defeasance has landed — the create is rejected with `ERR_ISSUE_VERSION_STALE` and HTTP 412."
        Design: Corner/cross_cutting_complexity_layers/filing_creation_rejects_a_stale_view_of_the_issue
        """
        context = _setup_issue_with_two_notices()
        v_obs = context["v_obs"]
        _record_moodys_downgrade(context["issue"]["id"], v_obs)
        v_new = issue_version(context["issue"]["id"])

        validate_error(
            _draft_event_filing(context["issue"]["id"], context["notice_ok"]["id"], v_obs),
            ApiErrorId.ERR_ISSUE_VERSION_STALE.value,
        )
        validate_error(
            _draft_event_filing(
                context["issue"]["id"], context["notice_pending"]["id"], v_obs
            ),
            ApiErrorId.ERR_ISSUE_VERSION_STALE.value,
        )
        validate_error(
            _draft_event_filing(
                context["issue"]["id"], context["notice_pending"]["id"], v_new
            ),
            ApiErrorId.ERR_FILING_SUBJECT_MISMATCH.value,
        )

        created = validate_success(
            _draft_event_filing(context["issue"]["id"], context["notice_ok"]["id"], v_new),
            201,
        )
        assert created["status"] == "DRAFT"
        assert created["version"] == 1
        assert created["submission_attempt_count"] == 0

        # Exactly one Filing row exists on this issue: none of the three refusals
        # persisted a draft.
        rows, meta = validate_paginated(
            api_client.list_filings(FD, params={"issue_id": context["issue"]["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [created["id"]]


def _record_rating_action_at_version(issue_id: str, expected_issue_version: int, **overrides):
    """Raw response for a rating action on a pinned issue version."""
    return api_client.create_rating_action(
        issue_id, rating_action_payload(expected_issue_version, **overrides), FD
    )


def _rating_change_notice_count(issue_id: str) -> int:
    _rows, meta = validate_paginated(
        api_client.list_material_event_notices(
            FD, params={"issue_id": issue_id, "event_type": "RATING_CHANGE"}
        )
    )
    return meta["total_count"]


class TestRatingActionsSerializeOnTheIssueVersion:
    """Two agencies acting on the same stale read of one issue (PRD §2.8)."""

    def test_a_stale_rating_action_leaves_the_issue_completely_untouched(self):
        """The refused second agency overwrites no rating and mints no second notice.

        PRD §2.8: "A rating action legitimately overwrites `current_rating` and `current_rating_agency`, so a second recording is valid in itself; the check forces the writer to have actually observed the rating its action supersedes."
        PRD §3.5: "And `filing_deadline_date` is the **tenth business day strictly after** `occurrence_date`, computed with the add-business-days rule of §2.6: the occurrence date itself is never counted whether or not it is a business day, and the result is the tenth business day encountered walking forward."
        PRD §3.1: "The issue's own `current_rating` and `current_rating_agency` are overwritten with `new_rating` and `rating_agency`, the issue's `version` advances, and `open_material_event_count` on the issue and `open_obligation_count` on the undertaking are both recomputed."
        Design: Corner/cross_cutting_complexity_layers/rating_actions_serialize_on_the_issue_version
        """
        issue = create_bond_issue(**ISSUE_OVERRIDES)
        v1 = issue["version"]

        first = _record_moodys_downgrade(issue["id"], v1)
        assert first["event_type"] == "RATING_CHANGE"
        assert first["filing_deadline_date"] == "2026-08-13"

        after_first = read_bond_issue(issue["id"])
        v2 = after_first["version"]
        assert v2 == v1 + 1
        assert after_first["current_rating"] == "Aa3"
        assert after_first["current_rating_agency"] == "MOODYS"

        # A second agency still holding the pre-downgrade version.
        stale = _record_rating_action_at_version(
            issue["id"],
            v1,
            rating_agency="SP",
            prior_rating="AA",
            new_rating="AA-",
            occurrence_date="2026-07-31",
        )
        validate_error(stale, ApiErrorId.ERR_ISSUE_VERSION_STALE.value)

        after_fail = read_bond_issue(issue["id"])
        assert after_fail["version"] == v2
        assert after_fail["current_rating"] == "Aa3"
        assert after_fail["current_rating_agency"] == "MOODYS"
        assert _rating_change_notice_count(issue["id"]) == 1

    def test_the_retry_with_the_observed_version_succeeds_and_both_notices_coexist(self):
        """Re-reading the issue is the whole cure: the second agency's action then lands.

        PRD §2.8: "A rating action legitimately overwrites `current_rating` and `current_rating_agency`, so a second recording is valid in itself; the check forces the writer to have actually observed the rating its action supersedes."
        PRD §3.5: "Duplicate suppression comes first: no other `MaterialEventNotice` on the same `issue_id` may share the same `event_type` **and** `occurrence_date` while its `status` is neither `NOT_MATERIAL` nor `VOID`; a collision returns `ERR_DUPLICATE_EVENT_NOTICE`."
        Design: Corner/cross_cutting_complexity_layers/rating_actions_serialize_on_the_issue_version
        """
        issue = create_bond_issue(**ISSUE_OVERRIDES)
        v1 = issue["version"]
        _record_moodys_downgrade(issue["id"], v1)
        v2 = issue_version(issue["id"])

        validate_error(
            _record_rating_action_at_version(
                issue["id"],
                v1,
                rating_agency="SP",
                prior_rating="AA",
                new_rating="AA-",
                occurrence_date="2026-07-31",
            ),
            ApiErrorId.ERR_ISSUE_VERSION_STALE.value,
        )

        v_after_fail = issue_version(issue["id"])
        second = validate_success(
            _record_rating_action_at_version(
                issue["id"],
                v_after_fail,
                rating_agency="SP",
                prior_rating="AA",
                new_rating="AA-",
                occurrence_date="2026-07-31",
            ),
            201,
        )
        assert second["event_type"] == "RATING_CHANGE"

        after_second = read_bond_issue(issue["id"])
        assert after_second["version"] == v2 + 1
        assert after_second["current_rating"] == "AA-"
        assert after_second["current_rating_agency"] == "SP"
        assert _rating_change_notice_count(issue["id"]) == 2


class TestEngagementCreationVersionPrecondition:
    """The one rule guarded by `expected_undertaking_version` (PRD §2.8)."""

    def test_engagement_creation_reports_staleness_before_undertaking_state(self):
        """One suspension breaks both the version precondition and the state gate; 412 wins.

        PRD §2.8: "The version comparison is evaluated before any state precondition on the target row, so a caller acting on stale data always learns that fact first rather than being told about a state conflict it could not have known about."
        PRD §2.8: "A new engagement legitimately supersedes the incumbent, so the create would otherwise succeed; the check forces the writer to have observed the engagement it is about to displace, and to have observed any suspension or termination of the undertaking itself."
        PRD §2.10: "10. Undertaking gate — the `Undertaking` that owns the target row is `ACTIVE` → `ERR_UNDERTAKING_NOT_ACTIVE` (409)."
        Design: Corner/cross_cutting_complexity_layers/engagement_creation_reports_staleness_before_undertaking_state
        """
        context = setup_issue_with_undertaking(issue=dict(ISSUE_OVERRIDES))
        undertaking_id = context["undertaking"]["id"]
        v1 = context["undertaking"]["version"]

        suspended = suspend_undertaking(
            undertaking_id, suspended_reason="Awaiting the audit; agent selection paused."
        )
        assert suspended["status"] == "SUSPENDED"
        v2 = suspended["version"]
        assert v2 == v1 + 1

        # Both defects live at once: the version is stale AND the gate is shut.
        both_defects = _create_engagement_at_version(undertaking_id, v1)
        validate_error(both_defects, ApiErrorId.ERR_UNDERTAKING_VERSION_STALE.value)

        # With the version corrected, the state gate is what remains.
        gate_only = _create_engagement_at_version(undertaking_id, v2)
        validate_error(gate_only, ApiErrorId.ERR_UNDERTAKING_NOT_ACTIVE.value)

    def test_reinstatement_invalidates_the_version_the_caller_was_just_told_to_use(self):
        """The cure for the gate is itself a mutation, so the version must be re-read.

        PRD §3.2: "Reinstating a `SUSPENDED` undertaking takes no payload at all, returns it to `ACTIVE`, and clears `suspended_reason` back to null."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row, again including cascaded mutations."
        PRD §2.8: "A mismatch is rejected with `ERR_UNDERTAKING_VERSION_STALE` and HTTP 412."
        Design: Corner/cross_cutting_complexity_layers/engagement_creation_reports_staleness_before_undertaking_state
        """
        context = setup_issue_with_undertaking(issue=dict(ISSUE_OVERRIDES))
        undertaking_id = context["undertaking"]["id"]
        v2 = suspend_undertaking(
            undertaking_id, suspended_reason="Awaiting the audit; agent selection paused."
        )["version"]

        reinstated = reinstate_undertaking(undertaking_id)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspended_reason"] is None
        v3 = reinstated["version"]
        assert v3 == v2 + 1

        stale_again = _create_engagement_at_version(undertaking_id, v2)
        validate_error(stale_again, ApiErrorId.ERR_UNDERTAKING_VERSION_STALE.value)

        engagement = validate_success(
            _create_engagement_at_version(undertaking_id, v3), 201
        )
        assert engagement["status"] == "ACTIVE"
        assert engagement["termination_reason"] is None

    def test_a_plain_creation_supersedes_the_incumbent_engagement(self):
        """The second engagement terminates the first as SUPERSEDED, not ISSUER_TERMINATED.

        PRD §3.10: "Creating a newer engagement supersedes the incumbent rather than colliding with it: every other non-`TERMINATED` engagement on the same undertaking is driven to `TERMINATED` with `termination_reason` `SUPERSEDED` and `superseded_by_engagement_id` pointing at the new row, and its `invoice_total_cents` freezes at whatever final value it then held."
        PRD §3.10: "Accepting the engagement increments the parent `Undertaking`'s `version`."
        Design: Corner/cross_cutting_complexity_layers/engagement_creation_reports_staleness_before_undertaking_state
        """
        context = setup_issue_with_undertaking(issue=dict(ISSUE_OVERRIDES))
        undertaking_id = context["undertaking"]["id"]

        first = validate_success(
            _create_engagement_at_version(undertaking_id, undertaking_version(undertaking_id)),
            201,
        )
        assert first["status"] == "ACTIVE"

        v4 = undertaking_version(undertaking_id)
        second = validate_success(
            _create_engagement_at_version(
                undertaking_id,
                v4,
                agent_name="Keystone Filing Agents",
                effective_date="2026-08-01",
                retainer_cents=400000,
            ),
            201,
        )
        assert second["status"] == "ACTIVE"

        incumbent = read_engagement(first["id"])
        assert incumbent["status"] == "TERMINATED"
        assert incumbent["termination_reason"] == "SUPERSEDED"
        assert incumbent["superseded_by_engagement_id"] == second["id"]


class TestConfirmationCascadeIsReadableImmediately:
    """No sweep, no reconcile step: one confirm must settle every hop (PRD §2.11)."""

    def test_the_confirmed_notice_is_discharged_on_the_very_next_call(self):
        """Hop 1 of the confirm cascade is visible to the read that follows it.

        PRD §2.11: "First, cascades are **immediate and complete within the request**. There is no deferred or eventual reconciliation: by the time the response is written, every dependent row and every derived field the change affects already holds its new value."
        PRD §3.5: "When the filing that carries the notice is confirmed, the notice is `FILED_TIMELY` if the date part of the filing's `submitted_at` is **less than or equal to** `filing_deadline_date` — a submission on the deadline date is timely — and `FILED_LATE` otherwise, with `days_late` set to the whole calendar days from `filing_deadline_date` to that submission date, floored at 0."
        PRD §2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`; until the clock is explicitly set, that instant is what all rules read, and the service must never fall back on real wall-clock time."
        Design: Corner/consistency_model/every_cascade_hop_is_readable_on_the_very_next_call
        """
        context = _setup_submitted_event_filing()
        assert context["notice"]["filing_deadline_date"] == "2026-08-11"
        assert context["notice"]["status"] == "MATERIAL"
        assert context["submitted"]["status"] == "SUBMITTED"
        assert str(context["submitted"]["submitted_at"])[:19] == "2026-08-01T00:00:00"

        confirmed = validate_success(
            api_client.confirm_filing(
                context["filing"]["id"],
                {"repository_receipt_id": "EMMA-RCPT-77001"},
                make_agent_headers(context["engagement"]["id"]),
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["repository_receipt_id"] == "EMMA-RCPT-77001"
        assert str(confirmed["repository_confirmed_at"])[:19] == "2026-08-01T00:00:00"
        # One bump for the submit and one for the confirm, on top of creation.
        assert confirmed["version"] == 3

        notice_after = read_notice(context["notice"]["id"])
        assert notice_after["status"] == "FILED_TIMELY"
        assert notice_after["filed_filing_id"] == context["filing"]["id"]
        assert notice_after["days_late"] == 0

    def test_the_agent_invoice_is_already_re_derived_with_no_sweep_in_between(self):
        """Hop 4 leaves `billable_filing_count` and `invoice_total_cents` correct at once.

        PRD §3.7: "Hop 4 re-derives the submitting engagement's `billable_filing_count` and then its `invoice_total_cents`, the latter sensitive to the posture hop 3 just wrote."
        PRD §3.10: "With F of 1, a `retainer_cents` of 250000, and posture `COMPLIANT`: the subtotal is 295000, the surcharge is 0, the capped figure is 295000, and `invoice_total_cents` is 300000 — the floor binds."
        PRD §2.11: "First, cascades are **immediate and complete within the request**. There is no deferred or eventual reconciliation: by the time the response is written, every dependent row and every derived field the change affects already holds its new value."
        Design: Corner/consistency_model/every_cascade_hop_is_readable_on_the_very_next_call
        """
        context = _setup_submitted_event_filing()
        assert context["engagement"]["billable_filing_count"] == 0

        validate_success(
            api_client.confirm_filing(
                context["filing"]["id"],
                {"repository_receipt_id": "EMMA-RCPT-77001"},
                make_agent_headers(context["engagement"]["id"]),
            ),
            200,
        )

        engagement_after = read_engagement(context["engagement"]["id"])
        assert engagement_after["billable_filing_count"] == 1
        assert engagement_after["invoice_total_cents"] == 300000

    def test_both_open_counters_fall_inside_the_confirming_request(self):
        """The undertaking's and the issue's derived counters move in the same request.

        PRD §3.5: "Either branch stamps `filed_filing_id`, re-derives `open_material_event_count` and `open_obligation_count`, and, when `financial_obligation_ref` is set, moves the referenced `DirectPlacement` from `DISCLOSURE_REQUIRED` to `DISCLOSED`."
        PRD §2.11: "Third, derived quantities are **recomputed from source, never adjusted in place**."
        PRD §3.8: "Step 6 derives `compliance_posture`, and here any delinquent cycle dominates the score bands outright: the posture is `DELINQUENT` whenever D is 1 or more, regardless of score; otherwise `IMPAIRED` at a score of 50.00 or above; otherwise `WATCH` at 25.00 or above; otherwise `COMPLIANT`."
        Design: Corner/consistency_model/every_cascade_hop_is_readable_on_the_very_next_call
        """
        context = _setup_submitted_event_filing()
        assert context["open_before"] == 1

        validate_success(
            api_client.confirm_filing(
                context["filing"]["id"],
                {"repository_receipt_id": "EMMA-RCPT-77001"},
                make_agent_headers(context["engagement"]["id"]),
            ),
            200,
        )

        undertaking_after = read_undertaking(context["undertaking"]["id"])
        assert undertaking_after["open_obligation_count"] == 0
        assert undertaking_after["compliance_posture"] == "COMPLIANT"
        assert_score(undertaking_after["disclosure_risk_score"], 0.00, "disclosure_risk_score")

        issue_after = read_bond_issue(context["issue"]["id"])
        assert issue_after["open_material_event_count"] == 0


WITHDRAWAL_REASON = (
    "Fiscal year restated; the cycle will be reopened under corrected periods."
)


class TestWithdrawalIsVisibleInItsOwnResponseBody:
    """The immediacy claim made against the WRITE's own body (PRD §2.11)."""

    def test_the_withdraw_response_already_reports_the_zeroed_score(self):
        """The write's own body carries WITHDRAWN and 0.00, not the pre-cascade 100.00.

        PRD §2.11: "First, cascades are **immediate and complete within the request**. There is no deferred or eventual reconciliation: by the time the response is written, every dependent row and every derived field the change affects already holds its new value."
        PRD §3.4: "Every `CycleContentItem` of the cycle whose `status` is `NOT_STARTED`, `DRAFT`, `READY`, or `WAIVED` moves to `VOID` in ascending `created_at` order, each with `readiness_factor` driven to 0.0. With the entire input set gone, `completeness_score_pct` is re-derived to 0.00."
        PRD §3.4: "A `DisclosureOfficer` supplies a `withdrawal_reason` and the cycle moves to `WITHDRAWN`."
        Design: Corner/consistency_model/a_withdrawal_is_fully_visible_in_its_own_response_body
        """
        context = _setup_attested_cycle()
        assert context["item"]["status"] == "READY"
        assert_score(context["cycle"]["completeness_score_pct"], 100.00,
                     "completeness_score_pct")

        withdrawn = validate_success(
            api_client.withdraw_cycle(
                context["cycle"]["id"], {"withdrawal_reason": WITHDRAWAL_REASON}, OFFICER
            ),
            200,
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert_score(withdrawn["completeness_score_pct"], 0.00, "completeness_score_pct")
        assert withdrawn["withdrawal_reason"] == WITHDRAWAL_REASON
        # PRD §2.4: the withdrawal mutates the cycle row, so its version advances by
        # exactly 1 over whatever it stood at before the call.  The preparation and
        # attestation that built this fixture each re-derived the cycle's persisted
        # `completeness_score_pct` and therefore already advanced it.
        assert withdrawn["version"] == context["cycle"]["version"] + 1

    def test_the_voided_item_and_the_re_derived_counters_are_readable_at_once(self):
        """The child row is VOID with readiness 0.0, its attester kept for the audit trail.

        PRD §3.4: "Every `CycleContentItem` of the cycle whose `status` is `NOT_STARTED`, `DRAFT`, `READY`, or `WAIVED` moves to `VOID` in ascending `created_at` order, each with `readiness_factor` driven to 0.0."
        PRD §3.4: "And the undertaking's `open_obligation_count` is re-derived from source, which is what makes the compensation exact: withdrawing a cycle created moments earlier must restore `open_obligation_count` to precisely the value it held before the creation."
        PRD §3.1: "Hop 3: every `CycleContentItem` of each closed cycle whose `status` is `NOT_STARTED`, `DRAFT`, `READY`, or `WAIVED` moves to `VOID` in ascending `created_at` order, each with `readiness_factor` driven to 0.0 — though an item that had been attested keeps its `attested_by_user_id` for the audit trail — and each affected cycle's `completeness_score_pct` falls to 0.00 because its entire input set has left."
        PRD §3.2: "Each accepted requirement re-derives the undertaking's `content_weight_bp_total` as the sum of `weight_bp` across all of that undertaking's requirements, which is the figure the weight-closure gate of §3.3 tests."
        Design: Corner/consistency_model/a_withdrawal_is_fully_visible_in_its_own_response_body
        """
        context = _setup_attested_cycle()
        assert read_undertaking(context["undertaking"]["id"])["open_obligation_count"] == 1

        validate_success(
            api_client.withdraw_cycle(
                context["cycle"]["id"], {"withdrawal_reason": WITHDRAWAL_REASON}, OFFICER
            ),
            200,
        )

        item_after = read_content_item(context["item"]["id"])
        assert item_after["status"] == "VOID"
        assert float(item_after["readiness_factor"]) == 0.0
        assert item_after["attested_by_user_id"] == OFFICER_PREPARER_ID

        undertaking_after = read_undertaking(context["undertaking"]["id"])
        assert undertaking_after["open_obligation_count"] == 0
        assert undertaking_after["content_weight_bp_total"] == 10000

    def test_the_list_projection_and_the_re_read_match_the_write_response(self):
        """Nothing converges after the fact: the index and the GET already agree.

        PRD §2.11: "First, cascades are **immediate and complete within the request**. There is no deferred or eventual reconciliation: by the time the response is written, every dependent row and every derived field the change affects already holds its new value."
        PRD §2.12: "Every one of those filters is optional, and all of them combine with `limit` and `offset`."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` is the size of the full filtered result set before the window is applied and `has_more` indicates whether any row remains beyond the returned window."
        Design: Corner/consistency_model/a_withdrawal_is_fully_visible_in_its_own_response_body
        """
        context = _setup_attested_cycle()
        written = validate_success(
            api_client.withdraw_cycle(
                context["cycle"]["id"], {"withdrawal_reason": WITHDRAWAL_REASON}, OFFICER
            ),
            200,
        )

        rows, meta = validate_paginated(
            api_client.list_annual_report_cycles(
                FD,
                params={
                    "undertaking_id": context["undertaking"]["id"],
                    "status": "WITHDRAWN",
                },
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [context["cycle"]["id"]]

        reread = read_cycle(context["cycle"]["id"])
        assert reread["status"] == "WITHDRAWN"
        assert_score(reread["completeness_score_pct"], 0.00, "completeness_score_pct")
        assert_score(
            reread["completeness_score_pct"],
            written["completeness_score_pct"],
            "completeness_score_pct",
        )

        # The voided item is likewise VOID in its own list projection.
        items = list_content_items(context["cycle"]["id"])
        assert [item["status"] for item in items] == ["VOID"]
