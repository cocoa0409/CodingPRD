"""Publishing, skipping, make-goods, completion cascades, compliance, and invariants.

Difficulty queue A: publish cascade depth-3; affidavit-void cascade depth-2;
insertions-published boundary; cancel gated by running notice; compensating money and
count invariants. Corner queue B: invalid re-publish; make-good non-skippable; insertion
reverse reachability; non-compliant make-good; publish-before-scheduled; immediate
consistency.
"""
from prd_bench_local_runner.testing import validate_success, validate_error, get_success_data
from test_helpers import (
    ApiErrorId,
    make_advertiser_headers, make_publisher_headers, compliance_officer_headers,
    publish_insertion_payload,
    setup_scheduled_notice, setup_running_notice, setup_published_notice,
    setup_affidavit_issued,
    skip_insertion, get_make_good_for, publish_insertion, weekly_dates, set_clock,
    get_notice, list_insertions,
)


# ===========================================================================
# Difficulty rule 4 — completion cascades
# ===========================================================================

class TestPublishFinalInsertionCascade:
    def test_final_publish_creates_draft_invoice(self, api):
        """PRD §3.6: "The system creates an `Affidavit` in `PENDING` status for the
        notice, and a `DRAFT` `Invoice` whose `account_id` and `notice_id` are copied
        from the notice."

        Design: Difficulty/transitive_cascade/publish_final_insertion_cascade_depth3
        """
        ref = setup_published_notice(api, line_count_actual=2)
        assert ref["notice"]["status"] == "PUBLISHED", ref["notice"]["status"]
        assert ref["invoice"] is not None, "a DRAFT invoice must be created at completion"
        assert ref["invoice"]["status"] == "DRAFT", ref["invoice"]["status"]

    def test_invoice_total_and_committed_recomputed(self, api):
        """PRD §3.6: "Finally, because a fresh `DRAFT` invoice now exists, the account's
        `committed_balance_cents` is recomputed."

        Design: Difficulty/transitive_cascade/publish_final_insertion_cascade_depth3
        """
        ref = setup_published_notice(api, line_count_actual=2)  # subtotal 1600 + fee 2500
        assert ref["invoice"]["total_cents"] == 4100, ref["invoice"]["total_cents"]
        acct = validate_success(
            api.get_account(ref["account"]["id"],
                          make_advertiser_headers(ref["account"]["id"])), 200)
        assert acct["committed_balance_cents"] == 4100, acct["committed_balance_cents"]
        assert acct["outstanding_balance_cents"] == 0, acct["outstanding_balance_cents"]


class TestAffidavitVoidCascade:
    def test_void_cascades_invoice_to_void(self, api):
        """PRD §3.7: "the notice reverts from `AFFIDAVIT_ISSUED` back to `PUBLISHED`
        (re-arming it for a corrected affidavit), the notice's `ISSUED` invoice moves to
        `VOID`, and the account's `outstanding_balance_cents` is recomputed, falling by
        that invoice's `total_cents`."

        Design: Difficulty/transitive_cascade/affidavit_void_cascade_depth2
        """
        ref = setup_affidavit_issued(api, line_count_actual=2)
        aff = validate_success(
            api.void_affidavit(ref["affidavit"]["id"], {"reason": "wrong parcel published"},
                              compliance_officer_headers()), 200)
        assert aff["status"] == "VOID", aff["status"]
        inv = validate_success(
            api.get_invoice(ref["invoice"]["id"],
                          make_advertiser_headers(ref["account"]["id"])), 200)
        assert inv["status"] == "VOID", inv["status"]

    def test_void_reverts_notice_and_clears_outstanding(self, api):
        """PRD §3.7: "the notice reverts from `AFFIDAVIT_ISSUED` back to `PUBLISHED`
        (re-arming it for a corrected affidavit), the notice's `ISSUED` invoice moves to
        `VOID`, and the account's `outstanding_balance_cents` is recomputed, falling by
        that invoice's `total_cents`."

        Design: Difficulty/transitive_cascade/affidavit_void_cascade_depth2
        """
        ref = setup_affidavit_issued(api, line_count_actual=2)
        api.void_affidavit(ref["affidavit"]["id"], {"reason": "wrong parcel published"},
                          compliance_officer_headers())
        notice = get_notice(api, ref["notice"]["id"], ref["account"])
        assert notice["status"] == "PUBLISHED", notice["status"]
        acct = validate_success(
            api.get_account(ref["account"]["id"],
                          make_advertiser_headers(ref["account"]["id"])), 200)
        assert acct["outstanding_balance_cents"] == 0, acct["outstanding_balance_cents"]


# ===========================================================================
# Difficulty rule 6 — insertions-published boundary
# ===========================================================================

class TestInsertionsPublishedBoundary:
    def test_below_required_notice_running_no_affidavit(self, api):
        """PRD §3.5: "While at least one but fewer than `required_insertions` insertions
        have published, the notice sits in `RUNNING`, and each such publication
        recomputes its `compliance_status`."

        Design: Difficulty/boundary_precision_check/insertions_published_reaches_required_boundary
        """
        ref = setup_running_notice(api)  # 1 of 2 published
        assert ref["notice"]["status"] == "RUNNING", ref["notice"]["status"]
        assert ref["notice"]["insertions_published"] == 1
        affs = get_success_data(
            api.list_notice_affidavits(ref["notice"]["id"],
                                      make_advertiser_headers(ref["account"]["id"])))
        assert len(affs) == 0, "no affidavit until the run completes"

    def test_reaching_required_completes_and_mints_affidavit(self, api):
        """PRD §3.6: "A notice's run completes the moment `insertions_published` reaches
        `required_insertions`. For a multi-insertion run this is the transition from
        `RUNNING` to `PUBLISHED`".

        Design: Difficulty/boundary_precision_check/insertions_published_reaches_required_boundary
        """
        ref = setup_running_notice(api)
        second = ref["insertions"][1]
        dates = ref["published_dates"]
        publish_insertion(api, second, ref["newspaper"], dates[1] + "T00:00:00Z", 2)
        notice = get_notice(api, ref["notice"]["id"], ref["account"])
        assert notice["insertions_published"] == 2
        assert notice["status"] == "PUBLISHED", notice["status"]
        affs = get_success_data(
            api.list_notice_affidavits(notice["id"],
                                      make_advertiser_headers(ref["account"]["id"])))
        assert len(affs) == 1, "exactly one affidavit is minted at completion"


# ===========================================================================
# Difficulty rule 7 — cancel gated by parent notice state
# ===========================================================================

class TestCancelGatedByRunningNotice:
    def test_cancel_sibling_rejected_while_running(self, api):
        """PRD §3.4: "The advertiser may also cancel a still-`SCHEDULED` insertion,
        moving it from `SCHEDULED` to `CANCELLED`; cancellation is allowed only while
        the parent notice is itself `SCHEDULED`, and because a `SCHEDULED` insertion was
        never counted, no counters change."

        Design: Difficulty/cross_entity_state_dependency/cancel_insertion_gated_by_running_notice_state
        """
        ref = setup_running_notice(api)  # notice RUNNING, second insertion still SCHEDULED
        second = ref["insertions"][1]
        assert second["status"] == "SCHEDULED"
        resp = api.cancel_insertion(second["id"],
                                    make_advertiser_headers(ref["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_insertion_stays_scheduled_and_notice_running(self, api):
        """PRD §3.4: "cancellation is allowed only while the parent notice is itself
        `SCHEDULED`, and because a `SCHEDULED` insertion was never counted, no counters
        change."

        Design: Difficulty/cross_entity_state_dependency/cancel_insertion_gated_by_running_notice_state
        """
        ref = setup_running_notice(api)
        second = ref["insertions"][1]
        api.cancel_insertion(second["id"], make_advertiser_headers(ref["account"]["id"]))
        after = validate_success(
            api.get_insertion(second["id"], make_advertiser_headers(ref["account"]["id"])), 200)
        assert after["status"] == "SCHEDULED", after["status"]
        notice = get_notice(api, ref["notice"]["id"], ref["account"])
        assert notice["status"] == "RUNNING", notice["status"]


# ===========================================================================
# Difficulty rule 9 — compensating invariants
# ===========================================================================

class TestOutstandingBalanceConservedIssueThenVoid:
    def test_outstanding_returns_to_zero_after_void(self, api):
        """PRD §3.7: "Voiding is refused if the notice's invoice has already been
        paid... Otherwise the void is a compensating reversal: the notice reverts from
        `AFFIDAVIT_ISSUED` back to `PUBLISHED` (re-arming it for a corrected affidavit),
        the notice's `ISSUED` invoice moves to `VOID`, and the account's
        `outstanding_balance_cents` is recomputed, falling by that invoice's
        `total_cents`."

        Design: Difficulty/compensating_invariant/outstanding_balance_conserved_issue_then_void
        """
        ref = setup_affidavit_issued(api, line_count_actual=2)
        api.void_affidavit(ref["affidavit"]["id"], {"reason": "correction"},
                          compliance_officer_headers())
        acct = validate_success(
            api.get_account(ref["account"]["id"],
                          make_advertiser_headers(ref["account"]["id"])), 200)
        assert acct["outstanding_balance_cents"] == 0, acct["outstanding_balance_cents"]

    def test_issue_raises_outstanding_by_total(self, api):
        """PRD §3.7: "Issuance cascades: the notice advances from `PUBLISHED` to
        `AFFIDAVIT_ISSUED`, the notice's `DRAFT` invoice advances to `ISSUED`, and —
        because an issued invoice is now money owed — the account's
        `outstanding_balance_cents` is recomputed, rising by the invoice's
        `total_cents`."

        Design: Difficulty/compensating_invariant/outstanding_balance_conserved_issue_then_void
        """
        ref = setup_affidavit_issued(api, line_count_actual=2)  # invoice total 4100 issued
        acct = validate_success(
            api.get_account(ref["account"]["id"],
                          make_advertiser_headers(ref["account"]["id"])), 200)
        assert acct["outstanding_balance_cents"] == 4100, acct["outstanding_balance_cents"]


class TestPaidInsertionCountConservedSkipThenMakeGood:
    def _skip_then_makegood_published(self, api):
        ref = setup_scheduled_notice(api)  # insertions 03-01 (ins1), 03-08 (ins2)
        insertions = ref["insertions"]
        ins1, ins2 = insertions[0], insertions[1]
        skip_insertion(api, ins1, ref["newspaper"])  # make-good scheduled 03-08
        mg = get_make_good_for(api, ins1, ref["newspaper"])
        publish_insertion(api, ins2, ref["newspaper"], "2026-03-08T00:00:00Z", 2)
        publish_insertion(api, mg, ref["newspaper"], "2026-03-08T00:00:00Z", 2)
        ref["mg"] = mg
        ref["notice"] = get_notice(api, ref["notice"]["id"], ref["account"])
        return ref

    def test_paid_count_excludes_make_good(self, api):
        """PRD §3.5: "Publishing also increments the notice's `insertions_published` by
        one, and — only when the insertion is not a make-good — increments
        `paid_insertion_count` by one; make-goods never increment the billable count."

        Design: Difficulty/compensating_invariant/paid_insertion_count_conserved_skip_then_makegood
        """
        ref = self._skip_then_makegood_published(api)
        assert ref["notice"]["paid_insertion_count"] == 1, ref["notice"]["paid_insertion_count"]
        assert ref["notice"]["insertions_published"] == 2, ref["notice"]["insertions_published"]

    def test_make_good_is_free(self, api):
        """PRD §3.5: "A make-good insertion is always free: its `cost_cents` is 0
        regardless of basis."

        Design: Difficulty/compensating_invariant/paid_insertion_count_conserved_skip_then_makegood
        """
        ref = self._skip_then_makegood_published(api)
        mg = validate_success(
            api.get_insertion(ref["mg"]["id"], make_publisher_headers(ref["newspaper"]["id"])), 200)
        assert mg["is_make_good"] is True
        assert mg["cost_cents"] == 0, mg["cost_cents"]
        assert ref["notice"]["status"] == "PUBLISHED", ref["notice"]["status"]


# ===========================================================================
# Corner queue B — state machine / calculation / consistency instances
# ===========================================================================

def test_publish_already_published_insertion_invalid(api):
    """PRD §3.5: "This is permitted only when the insertion is `SCHEDULED`, its parent
    notice is in `SCHEDULED` or `RUNNING` status, and the logical clock has reached or
    passed the insertion's `scheduled_date`".

    Design: Corner/state_machines/publish_already_published_insertion_invalid
    """
    ref = setup_running_notice(api)  # ins1 already PUBLISHED
    ins1 = ref["insertions"][0]
    assert ins1["status"] == "PUBLISHED"
    resp = api.publish_insertion(ins1["id"], publish_insertion_payload(2),
                                 make_publisher_headers(ref["newspaper"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    notice = get_notice(api, ref["notice"]["id"], ref["account"])
    assert notice["insertions_published"] == 1


def test_skip_make_good_insertion_rejected(api):
    """PRD §3.5: "A skip is allowed only on an insertion whose `is_make_good` is false;
    attempting to skip a make-good insertion (which would chain one make-good into
    another) is rejected with `ERR_MAKE_GOOD_NOT_SKIPPABLE` (HTTP 409)."

    Design: Corner/state_machines/skip_make_good_insertion_rejected
    """
    ref = setup_scheduled_notice(api, clock_iso=None)
    ins1 = ref["insertions"][0]
    skip_insertion(api, ins1, ref["newspaper"])
    mg = get_make_good_for(api, ins1, ref["newspaper"])
    resp = api.skip_insertion(mg["id"], make_publisher_headers(ref["newspaper"]["id"]))
    validate_error(resp, ApiErrorId.ERR_MAKE_GOOD_NOT_SKIPPABLE, expected_status=409)
    after = validate_success(
        api.get_insertion(mg["id"], make_publisher_headers(ref["newspaper"]["id"])), 200)
    assert after["status"] == "SCHEDULED", after["status"]


def test_fk_reverse_reachability_notice_insertions(api):
    """PRD §3.8: "a notice's proofs, insertions, and affidavits are each listable by the
    notice".
    PRD §3.4: "the first insertion runs on `first_publication_date`, and each subsequent
    insertion runs 7 days after the previous one."

    Design: Corner/state_machines/fk_reverse_reachability_notice_insertions
    """
    ref = setup_scheduled_notice(api, clock_iso=None)
    rows = get_success_data(
        api.list_notice_insertions(ref["notice"]["id"],
                                  make_advertiser_headers(ref["account"]["id"])))
    assert len(rows) == 2, f"expected 2 insertions, got {len(rows)}"
    assert rows[0]["sequence_number"] == 1
    assert rows[0]["scheduled_date"].startswith("2026-03-01")
    assert rows[1]["sequence_number"] == 2
    assert rows[1]["scheduled_date"].startswith("2026-03-08")


def test_compliance_non_compliant_when_makegood_past_cutoff(api):
    """PRD §3.6: "Once the requirement is met, the system takes the latest
    `published_date` among all the notice's `PUBLISHED` insertions — make-goods included
    — and compares it to the statutory cutoff, which is the notice's `deadline_date`
    minus `min_days_before_deadline` days. If that latest published date is on or before
    the cutoff, the notice is `COMPLIANT`; if it falls even one day past the cutoff, it
    is `NON_COMPLIANT`."

    Design: Corner/calculations/compliance_status_non_compliant_when_makegood_runs_past_cutoff
    """
    ref = setup_scheduled_notice(api, notice_overrides={"deadline_date": "2026-03-13"})
    ins1, ins2 = ref["insertions"][0], ref["insertions"][1]
    skip_insertion(api, ins2, ref["newspaper"])  # make-good scheduled 03-15
    mg = get_make_good_for(api, ins2, ref["newspaper"])
    publish_insertion(api, ins1, ref["newspaper"], "2026-03-01T00:00:00Z", 2)
    publish_insertion(api, mg, ref["newspaper"], "2026-03-15T00:00:00Z", 2)
    notice = get_notice(api, ref["notice"]["id"], ref["account"])
    assert notice["insertions_published"] == 2
    assert notice["compliance_status"] == "NON_COMPLIANT", notice["compliance_status"]
    assert notice["status"] == "PUBLISHED", notice["status"]


def test_publish_before_scheduled_date_rejected(api):
    """PRD §3.5: "the logical clock has reached or passed the insertion's
    `scheduled_date` — a publish attempted before that date is rejected with
    `ERR_PUBLISH_BEFORE_SCHEDULED` (HTTP 422)."

    Design: Corner/validations/publish_before_scheduled_date_rejected
    """
    ref = setup_scheduled_notice(api, clock_iso="2026-02-01T00:00:00Z")  # clock stays at 02-01
    ins1 = ref["insertions"][0]
    resp = api.publish_insertion(ins1["id"], publish_insertion_payload(2),
                                 make_publisher_headers(ref["newspaper"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PUBLISH_BEFORE_SCHEDULED, expected_status=422)


def test_immediate_consistency_publish_reflects_counters(api):
    """PRD §2.4: "Whenever a mutation cascades into a related resource — for example, a
    publisher publishing an insertion that in turn advances its parent notice — each
    individual resource that actually changes has its own `version` incremented and its
    own `updated_at` refreshed."
    PRD §3.5: "While at least one but fewer than `required_insertions` insertions have
    published, the notice sits in `RUNNING`".

    Design: Corner/consistency_model/immediate_consistency_publish_reflects_counters
    """
    ref = setup_running_notice(api)  # publishes ins1 then re-reads notice
    notice = get_notice(api, ref["notice"]["id"], ref["account"])
    assert notice["insertions_published"] == 1
    assert notice["status"] == "RUNNING", notice["status"]
