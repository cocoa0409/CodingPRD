"""State machines: declared initial states, terminal lockdown, cycles and axes.

Every machine in the service starts where the PRD says it starts, refuses any
action from a state its transitions do not accept, and — where the vocabulary
allows a loop — comes back round with the right counters and the right
compensating money. The two parallel-axis entities are read on both axes at
once, because neither axis may be moved by the other's transitions.
"""

import pytest

from test_helpers import (
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    advance_clock,
    assert_blanket_axes,
    assert_cents_equal,
    assert_composer_money,
    assert_composition_axes,
    assert_created,
    assert_credit_exposure,
    assert_credits_equal,
    assert_declared_error,
    assert_ok,
    assert_page,
    assert_pct_equal,
    assert_same_instant,
    assert_status,
    assert_sweep_lists,
    issue_per_use_license,
    ledger_entries,
    make_composer_headers,
    new_accepted_deal,
    new_active_agreement,
    new_active_blanket,
    new_cataloged_work,
    new_composer,
    new_cue_sheet,
    new_deal_ground,
    new_detected_claim,
    new_draft_agreement,
    new_draft_blanket,
    new_ingested_work,
    new_licensee,
    open_usage_report,
    read_agreement,
    read_blanket_agreement,
    read_claim,
    read_composer,
    read_composition,
    read_cue_sheet,
    read_license,
    read_licensee,
    read_usage_report,
    register_cue_sheet,
    select_ledger_entries,
    submit_sync_request,
    submit_usage_report,
)
from test_helpers import factories as build
from test_helpers.api_errors import (
    ERR_AGREEMENT_STATE_INVALID,
    ERR_BLANKET_STATE_INVALID,
    ERR_CLAIM_STATE_INVALID,
    ERR_COMPOSITION_STATE_INVALID,
    ERR_SYNC_REQUEST_STATE_INVALID,
)

FILM_TIER = {"media_type": "FILM", "base_rate_cents": 600000}
BIG_LICENSEE = {"legal_name": "Northwind Pictures", "credit_limit_cents": 10000000}
FILM_REQUEST = {
    "media_type": "FILM",
    "distribution_scale": "NATIONAL",
    "requested_term_start": "2026-09-01T00:00:00Z",
}


# ---------------------------------------------------------------------------
# Declared initial states
# ---------------------------------------------------------------------------


class TestDeclaredInitialStates:
    def test_ingested_work_starts_on_both_axes_at_their_first_value(self, api):
        """PRD §3.2: "The work lands with `catalog_status` `INGESTED`,
        `availability_status` `AVAILABLE` and `version` 1."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        work = new_ingested_work(api, title="Harbour Lights")

        assert_composition_axes(work.composition, "INGESTED", "AVAILABLE")
        assert work.composition["version"] == 1

    def test_drafted_agreement_starts_with_no_round_and_no_proposal(self, api):
        """PRD §3.1: "A new agreement lands in `DRAFT` with `amendment_round` at 0 and
        every proposal field null."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
        agreement = new_draft_agreement(api, composer["id"])

        assert_status(agreement, "DRAFT")
        assert agreement["amendment_round"] == 0
        assert agreement["pending_writer_share_pct"] is None
        assert agreement["pending_publisher_share_pct"] is None
        assert agreement["pending_sync_fee_share_pct"] is None
        assert agreement["pending_holdback_days"] is None
        assert agreement["signed_at"] is None

    def test_raised_sync_request_starts_submitted_with_no_quote(self, api):
        """PRD §3.4: "A new request lands in `SUBMITTED` with `revision_round` 0 and
        every quote field null."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        deal = submit_sync_request(
            api,
            new_deal_ground(api, tier_overrides=FILM_TIER, licensee_overrides=BIG_LICENSEE),
            requested_term_months=24,
            **FILM_REQUEST,
        )

        assert_status(deal.sync_request, "SUBMITTED")
        assert deal.sync_request["revision_round"] == 0
        assert deal.sync_request["quoted_fee_cents"] is None
        assert deal.sync_request["quoted_spend_basis_cents"] is None
        assert deal.sync_request["quoted_discount_pct"] is None
        assert deal.sync_request["quote_expires_at"] is None

    def test_drafted_blanket_agreement_starts_draft_and_compliant(self, api):
        """PRD §3.6: "A new agreement lands with `coverage_status` `DRAFT` and
        `reporting_status` `COMPLIANT`."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        blanket = new_draft_blanket(api)

        assert_blanket_axes(blanket.agreement, "DRAFT", "COMPLIANT")
        assert blanket.agreement["delinquent_since"] is None

    def test_opened_usage_report_starts_due_with_zero_pool_figures(self, api):
        """PRD §3.6: "New reports land in `DUE` with zero pool figures and an empty
        `pool_allocations` array."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        blanket = open_usage_report(api, new_active_blanket(api))
        report = blanket.usage_report

        assert_status(report, "DUE")
        assert_cents_equal(report["pool_cents"], 0, "pool_cents")
        assert_cents_equal(report["pool_admin_fee_cents"], 0, "pool_admin_fee_cents")
        assert_cents_equal(report["pool_distributable_cents"], 0, "pool_distributable_cents")
        assert report["pool_allocations"] == []

    def test_collected_cue_sheet_starts_collected(self, api):
        """PRD §3.7: "A new sheet lands in `COLLECTED`."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        work = new_cataloged_work(api)
        blanket = open_usage_report(api, new_active_blanket(api))
        sheet = new_cue_sheet(
            api,
            [build.cue(work.composition_id, "THEME", 45)],
            usage_report_id=blanket.usage_report_id,
            production_title="Coastal Nights S01E01",
        )

        assert_status(sheet, "COLLECTED")
        assert sheet["society_reference"] is None
        assert sheet["registration_round"] == 0

    def test_built_claim_starts_detected_with_its_exposure_already_computed(self, api):
        """PRD §3.8: "The claim copies `composition_id` from the match, lands in
        `DETECTED`, and computes its exposure figures immediately."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        work = new_cataloged_work(api)
        match, claim = new_detected_claim(
            api,
            work.composition_id,
            source_platform="UGC_VIDEO",
            matched_seconds=120,
            confidence_pct=96.0,
        )

        assert_status(claim, "DETECTED")
        assert claim["composition_id"] == work.composition_id
        assert claim["fingerprint_match_id"] == match["id"]
        assert_cents_equal(claim["statutory_amount_cents"], 120000, "statutory_amount_cents")
        assert_cents_equal(claim["settlement_floor_cents"], 36000, "settlement_floor_cents")
        assert claim["settlement_amount_cents"] is None
        assert claim["settlement_basis"] is None


# ---------------------------------------------------------------------------
# Terminal states refuse every further action
# ---------------------------------------------------------------------------


def _delivered_per_use_deal(api):
    """A FILM per-use deal carried quote -> accept -> issue -> deliver.

    No edit work is ever asked for, so delivery straight from `ACCEPTED` with a
    single asset is the legal path and the request reaches `DELIVERED`.
    """
    deal = new_accepted_deal(
        api,
        None,
        FILM_TIER,
        BIG_LICENSEE,
        14,
        requested_term_months=24,
        **FILM_REQUEST,
    )
    issue_per_use_license(api, deal)
    deal.sync_request = assert_ok(
        api.deliver_sync_request(
            deal.sync_request_id,
            build.deliver_payload(1, delivery_note="master only"),
            CATALOG_ADMIN,
        )
    )
    return deal


def _fire_sync_request_action(api, action, deal):
    """Call one of the six sync-request action endpoints with its own role."""
    sync_request_id = deal.sync_request_id
    if action == "review":
        return api.review_sync_request(sync_request_id, None, LICENSING_AGENT)
    if action == "quote":
        return api.quote_sync_request(sync_request_id, build.quote_payload(14), LICENSING_AGENT)
    if action == "accept":
        return api.accept_sync_request(sync_request_id, None, deal.licensee_headers)
    if action == "request-revision":
        return api.request_sync_revision(
            sync_request_id, build.revision_payload("one more pass"), deal.licensee_headers
        )
    if action == "decline":
        return api.decline_sync_request(
            sync_request_id, {"reason": "changed mind"}, LICENSING_AGENT
        )
    if action == "start-edit":
        return api.start_sync_request_edit(
            sync_request_id, {"edit_note": "trim to 30s"}, CATALOG_ADMIN
        )
    if action == "deliver":
        return api.deliver_sync_request(sync_request_id, build.deliver_payload(1), CATALOG_ADMIN)
    raise AssertionError(f"unknown sync-request action {action!r}")


class TestDeliveredSyncRequestIsTerminal:
    @pytest.mark.parametrize(
        "action",
        [
            "review",
            "quote",
            "accept",
            "request-revision",
            "decline",
            "start-edit",
            "deliver",
        ],
    )
    def test_every_action_on_a_delivered_request_is_refused(self, api, action):
        """PRD §3.4: "`DECLINED` and `DELIVERED` are terminal, and any action attempted
        on a request in a state the transition does not accept is refused with
        `ERR_SYNC_REQUEST_STATE_INVALID`."

        Design: Corner/state_machines/delivered_sync_request_is_terminal_and_rejects_every_further_action
        """
        deal = _delivered_per_use_deal(api)
        license_id = deal.license_id

        refused = _fire_sync_request_action(api, action, deal)
        assert_declared_error(refused, ERR_SYNC_REQUEST_STATE_INVALID)

        reread = assert_ok(api.get_sync_request(deal.sync_request_id, LICENSING_AGENT))
        assert_status(reread, "DELIVERED")
        assert reread["delivered_asset_count"] == 1
        assert reread["revision_round"] == 0
        assert reread["decline_reason"] is None
        assert reread["license_id"] == license_id


def _terminated_agreement(api):
    """A composer whose only agreement is ACTIVE and then terminated.

    The composer owns no works, so the withdrawal cascade has nothing to touch
    and the agreement's own fields are the whole picture.
    """
    composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
    agreement = new_active_agreement(api, composer["id"])
    agreement = assert_ok(
        api.terminate_agreement(agreement["id"], {"reason": "catalogue exit"}, RIGHTS_MANAGER)
    )
    return composer, agreement


def _fire_agreement_action(api, action, agreement_id, composer_id):
    """Call one of the five agreement action endpoints with its own role."""
    composer_headers = make_composer_headers(composer_id)
    if action == "submit-for-signature":
        return api.submit_agreement_for_signature(agreement_id, None, RIGHTS_MANAGER)
    if action == "sign":
        return api.sign_agreement(
            agreement_id, {"signature_name": "Nadia Okoro"}, composer_headers
        )
    if action == "amendments":
        return api.create_amendment(
            agreement_id,
            build.amendment_payload(
                proposed_writer_share_pct=60.00,
                proposed_publisher_share_pct=40.00,
                proposed_sync_fee_share_pct=45.00,
            ),
            RIGHTS_MANAGER,
        )
    if action == "amendment-decision":
        return api.decide_amendment(agreement_id, {"decision": "ACCEPT"}, composer_headers)
    if action == "terminate":
        return api.terminate_agreement(agreement_id, {"reason": "again"}, RIGHTS_MANAGER)
    raise AssertionError(f"unknown agreement action {action!r}")


class TestTerminatedAgreementIsTerminal:
    @pytest.mark.parametrize(
        "action",
        [
            "submit-for-signature",
            "sign",
            "amendments",
            "amendment-decision",
            "terminate",
        ],
    )
    def test_every_action_on_a_terminated_agreement_is_refused(self, api, action, clock_origin):
        """PRD §3.1: "Any agreement action attempted from a state the transition does
        not accept — signing a `DRAFT`, amending a `TERMINATED` — is refused with
        `ERR_AGREEMENT_STATE_INVALID`."

        Design: Corner/state_machines/terminated_agreement_is_terminal_and_rejects_further_transitions
        """
        composer, agreement = _terminated_agreement(api)

        refused = _fire_agreement_action(api, action, agreement["id"], composer["id"])
        assert_declared_error(refused, ERR_AGREEMENT_STATE_INVALID)

        reread = read_agreement(api, agreement["id"])
        assert_status(reread, "TERMINATED")
        assert_same_instant(reread["terminated_at"], clock_origin)
        assert_pct_equal(reread["writer_share_pct"], 50.00, "writer_share_pct")
        assert reread["amendment_round"] == 0
        assert reread["pending_writer_share_pct"] is None


# ---------------------------------------------------------------------------
# Invalid-from transitions on the claim machine
# ---------------------------------------------------------------------------


def _detected_claim_on_a_cataloged_work(api):
    """A 96.0-confidence UGC_VIDEO detection over 120 seconds, claimed."""
    work = new_cataloged_work(api, title="Harbour Lights")
    _match, claim = new_detected_claim(
        api,
        work.composition_id,
        source_platform="UGC_VIDEO",
        matched_seconds=120,
        confidence_pct=96.0,
    )
    return work, claim


class TestInfringementClaimInvalidFromStates:
    @pytest.mark.parametrize("action", ["dispute", "settle", "escalate"])
    def test_claim_actions_not_declared_from_detected_are_refused(self, api, action):
        """PRD §2.6: "**Target state precondition** — on every action endpoint that
        drives a state machine: the target row's state field is not among the states the
        transition accepts → the entity's state-invalid error (409), namely
        `ERR_AGREEMENT_STATE_INVALID`, `ERR_COMPOSITION_STATE_INVALID`,
        `ERR_SYNC_REQUEST_STATE_INVALID`, `ERR_LICENSE_STATE_INVALID`,
        `ERR_BLANKET_STATE_INVALID`, `ERR_REPORT_STATE_INVALID`,
        `ERR_CUE_SHEET_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID` or
        `ERR_STATEMENT_STATE_INVALID`."

        Design: Corner/state_machines/infringement_claim_invalid_from_state_transitions_rejected
        """
        work, claim = _detected_claim_on_a_cataloged_work(api)

        if action == "dispute":
            refused = api.dispute_claim(
                claim["id"], {"dispute_note": "counter-notice too early"}, RIGHTS_MANAGER
            )
        elif action == "settle":
            refused = api.settle_claim(
                claim["id"], build.settle_claim_payload("STATUTORY"), RIGHTS_MANAGER
            )
        else:
            refused = api.escalate_claim(
                claim["id"], {"escalation_note": "straight to litigation"}, RIGHTS_MANAGER
            )
        assert_declared_error(refused, ERR_CLAIM_STATE_INVALID)

        reread = read_claim(api, claim["id"])
        assert_status(reread, "DETECTED")
        assert reread["settlement_amount_cents"] is None
        assert_composition_axes(
            read_composition(api, work.composition_id), "CATALOGED", "AVAILABLE"
        )

    def test_second_notice_and_early_escalation_are_refused(self, api):
        """PRD §3.8: "Noticing a claim twice, escalating one still in `NOTICED`, or
        acting at all on one already `SETTLED` or `ESCALATED`, is refused with
        `ERR_CLAIM_STATE_INVALID`."

        Design: Corner/state_machines/infringement_claim_invalid_from_state_transitions_rejected
        """
        work, claim = _detected_claim_on_a_cataloged_work(api)

        noticed = assert_ok(
            api.notice_claim(claim["id"], {"notice_channel": "EMAIL"}, RIGHTS_MANAGER)
        )
        assert_status(noticed, "NOTICED")
        assert_composition_axes(
            read_composition(api, work.composition_id), "CATALOGED", "RESTRICTED"
        )

        assert_declared_error(
            api.escalate_claim(
                claim["id"], {"escalation_note": "skip the dispute"}, RIGHTS_MANAGER
            ),
            ERR_CLAIM_STATE_INVALID,
        )
        assert_declared_error(
            api.notice_claim(claim["id"], {"notice_channel": "EMAIL"}, RIGHTS_MANAGER),
            ERR_CLAIM_STATE_INVALID,
        )

        disputed = assert_ok(
            api.dispute_claim(
                claim["id"], {"dispute_note": "user filed a counter-notice"}, RIGHTS_MANAGER
            )
        )
        assert_status(disputed, "DISPUTED")
        assert_composition_axes(
            read_composition(api, work.composition_id), "CATALOGED", "RESTRICTED"
        )

        assert_declared_error(
            api.notice_claim(claim["id"], {"notice_channel": "POST"}, RIGHTS_MANAGER),
            ERR_CLAIM_STATE_INVALID,
        )

        final = read_claim(api, claim["id"])
        assert_status(final, "DISPUTED")
        assert_cents_equal(final["statutory_amount_cents"], 120000, "statutory_amount_cents")
        assert_cents_equal(final["settlement_floor_cents"], 36000, "settlement_floor_cents")
        assert final["settlement_amount_cents"] is None


# ---------------------------------------------------------------------------
# The same transition fired twice on one row
# ---------------------------------------------------------------------------


class TestRepeatedTransitionIsRefusedTheSecondTime:
    def test_second_submit_for_signature_is_refused(self, api):
        """PRD §3.1: "Any agreement action attempted from a state the transition does
        not accept — signing a `DRAFT`, amending a `TERMINATED` — is refused with
        `ERR_AGREEMENT_STATE_INVALID`."

        Design: Corner/state_machines/repeated_transition_on_the_same_row_is_rejected_the_second_time
        """
        composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
        agreement = new_draft_agreement(api, composer["id"])

        first = assert_ok(
            api.submit_agreement_for_signature(agreement["id"], None, RIGHTS_MANAGER)
        )
        assert_status(first, "PENDING_SIGNATURE")

        assert_declared_error(
            api.submit_agreement_for_signature(agreement["id"], None, RIGHTS_MANAGER),
            ERR_AGREEMENT_STATE_INVALID,
        )
        assert_status(read_agreement(api, agreement["id"]), "PENDING_SIGNATURE")

    def test_second_catalog_attempt_is_refused_and_leaves_the_version_alone(self, api):
        """PRD §3.2: "Cataloguing a work that is already `CATALOGED`, or already
        `RETIRED`, is refused with `ERR_COMPOSITION_STATE_INVALID`."

        Design: Corner/state_machines/repeated_transition_on_the_same_row_is_rejected_the_second_time
        """
        work = new_ingested_work(api)

        cataloged = assert_ok(api.catalog_composition(work.composition_id, None, CATALOG_ADMIN))
        assert_composition_axes(cataloged, "CATALOGED", "AVAILABLE")
        assert cataloged["version"] == 2

        assert_declared_error(
            api.catalog_composition(work.composition_id, None, CATALOG_ADMIN),
            ERR_COMPOSITION_STATE_INVALID,
        )
        reread = read_composition(api, work.composition_id)
        assert_composition_axes(reread, "CATALOGED", "AVAILABLE")
        assert reread["version"] == 2

    def test_second_blanket_activation_is_refused_and_leaves_the_version_alone(self, api):
        """PRD §3.6: "Activating a non-`DRAFT` agreement, or terminating one already
        `EXPIRED` or `TERMINATED`, is refused with `ERR_BLANKET_STATE_INVALID`."

        Design: Corner/state_machines/repeated_transition_on_the_same_row_is_rejected_the_second_time
        """
        blanket = new_draft_blanket(api)

        activated = assert_ok(
            api.activate_blanket_agreement(blanket.agreement_id, None, LICENSING_AGENT)
        )
        assert_blanket_axes(activated, "ACTIVE", "COMPLIANT")
        assert activated["version"] == 2

        assert_declared_error(
            api.activate_blanket_agreement(blanket.agreement_id, None, LICENSING_AGENT),
            ERR_BLANKET_STATE_INVALID,
        )
        reread = read_blanket_agreement(api, blanket.agreement_id)
        assert_blanket_axes(reread, "ACTIVE", "COMPLIANT")
        assert reread["version"] == 2


# ---------------------------------------------------------------------------
# Blanket termination sweeps only the reports still due
# ---------------------------------------------------------------------------


class TestBlanketTerminationRejectsOnlyDueReports:
    def test_termination_sweeps_the_due_report_and_leaves_the_submitted_one(self, api):
        """PRD §3.6: "Termination by a `LicensingAgent` with a `reason` is reachable
        from `DRAFT` or `ACTIVE`; from `ACTIVE` it also rejects every usage report of
        the agreement still sitting in `DUE`, setting each one's `rejection_reason` to
        the literal `BLANKET_TERMINATED` and processing them in `created_at` ascending
        order, while from `DRAFT` there are no reports to reject because the agreement
        never carried any."

        Design: Corner/state_machines/blanket_termination_cascades_only_due_reports_to_rejected
        """
        work = new_cataloged_work(api)
        blanket = new_active_blanket(api, new_licensee(api, legal_name="Meridian Broadcasting"))

        open_usage_report(api, blanket)
        august_report_id = blanket.usage_report_id
        new_cue_sheet(
            api,
            [build.cue(work.composition_id, "THEME", 45)],
            usage_report_id=august_report_id,
            production_title="Coastal Nights S01E01",
        )
        submit_usage_report(api, blanket)

        september_report = assert_created(
            api.create_usage_report(
                build.usage_report_payload(
                    blanket.agreement_id,
                    period_start="2026-09-01T00:00:00Z",
                    period_end="2026-09-30T00:00:00Z",
                ),
                LICENSING_AGENT,
            )
        )

        terminated = assert_ok(
            api.terminate_blanket_agreement(
                blanket.agreement_id, {"reason": "broadcaster wound up"}, LICENSING_AGENT
            )
        )
        assert_blanket_axes(terminated, "TERMINATED", "COMPLIANT")

        swept = read_usage_report(api, september_report["id"])
        assert_status(swept, "REJECTED")
        assert swept["rejection_reason"] == "BLANKET_TERMINATED"

        untouched = read_usage_report(api, august_report_id)
        assert_status(untouched, "SUBMITTED")
        assert untouched["rejection_reason"] is None

        rows, meta = assert_page(
            api.list_usage_reports(
                {"blanket_agreement_id": blanket.agreement_id, "status": "REJECTED"},
                RIGHTS_MANAGER,
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [september_report["id"]]

        assert ledger_entries(api, work.composer_id) == []
        assert_composer_money(read_composer(api, work.composer_id), accrued_unpaid_cents=0)


# ---------------------------------------------------------------------------
# The usage-report reject / resubmit loop
# ---------------------------------------------------------------------------


def _submitted_report_without_registration(api):
    """A CATALOGED work, an ACTIVE MONTHLY blanket and a report already SUBMITTED.

    The attached sheet is left in `COLLECTED`: submission only requires that a
    sheet is attached, and nothing here should compute a pool.
    """
    work = new_cataloged_work(api)
    blanket = new_active_blanket(api, new_licensee(api, legal_name="Meridian Broadcasting"))
    open_usage_report(api, blanket)
    new_cue_sheet(
        api,
        [build.cue(work.composition_id, "THEME", 45)],
        usage_report_id=blanket.usage_report_id,
        production_title="Coastal Nights S01E01",
    )
    submit_usage_report(api, blanket)
    return work, blanket


class TestUsageReportRejectResubmitCycle:
    def test_resubmission_count_counts_only_the_submissions_after_the_first(self, api):
        """PRD §3.6: "It records `submitted_at` from the clock, and on the path from
        `REJECTED` it also increments `resubmission_count` by 1 and clears
        `rejection_reason` to null."

        Design: Corner/state_machines/usage_report_reject_resubmit_cycle_increments_resubmission_count
        """
        _work, blanket = _submitted_report_without_registration(api)
        report_id = blanket.usage_report_id

        assert blanket.usage_report["resubmission_count"] == 0

        rejected = assert_ok(
            api.reject_usage_report(
                report_id, {"reason": "cue durations disputed"}, RIGHTS_MANAGER
            )
        )
        assert_status(rejected, "REJECTED")
        assert rejected["rejection_reason"] == "cue durations disputed"
        assert rejected["resubmission_count"] == 0

        resubmitted = assert_ok(
            api.submit_usage_report(report_id, None, blanket.licensee_headers)
        )
        assert_status(resubmitted, "SUBMITTED")
        assert resubmitted["resubmission_count"] == 1
        assert resubmitted["rejection_reason"] is None

        assert_ok(
            api.reject_usage_report(report_id, {"reason": "still disputed"}, RIGHTS_MANAGER)
        )
        resubmitted_again = assert_ok(
            api.submit_usage_report(report_id, None, blanket.licensee_headers)
        )
        assert_status(resubmitted_again, "SUBMITTED")
        assert resubmitted_again["resubmission_count"] == 2
        assert resubmitted_again["rejection_reason"] is None

    def test_rejection_computes_no_pool_and_appends_no_ledger_entry(self, api):
        """PRD §3.6: "A `RightsManager` may reject a `SUBMITTED` report with a `reason`
        recorded as `rejection_reason`; rejection computes no pool and appends no ledger
        entry, and the `REJECTED → SUBMITTED` loop is unbounded."

        Design: Corner/state_machines/usage_report_reject_resubmit_cycle_increments_resubmission_count
        """
        work, blanket = _submitted_report_without_registration(api)
        report_id = blanket.usage_report_id

        for reason in ("cue durations disputed", "still disputed"):
            rejected = assert_ok(
                api.reject_usage_report(report_id, {"reason": reason}, RIGHTS_MANAGER)
            )
            assert_status(rejected, "REJECTED")
            assert_cents_equal(rejected["pool_cents"], 0, "pool_cents")
            assert_cents_equal(rejected["pool_admin_fee_cents"], 0, "pool_admin_fee_cents")
            assert_cents_equal(
                rejected["pool_distributable_cents"], 0, "pool_distributable_cents"
            )
            assert rejected["pool_allocations"] == []
            assert ledger_entries(api, work.composer_id) == []

            assert_ok(api.submit_usage_report(report_id, None, blanket.licensee_headers))

        final = read_usage_report(api, report_id)
        assert_status(final, "SUBMITTED")
        assert_cents_equal(final["pool_cents"], 0, "pool_cents")
        assert final["pool_allocations"] == []
        assert ledger_entries(api, work.composer_id) == []


# ---------------------------------------------------------------------------
# The cue-sheet society cycle
# ---------------------------------------------------------------------------


def _collected_three_cue_sheet(api):
    """One ASCAP composer, one CATALOGED work and one COLLECTED NETWORK sheet.

    THEME, FEATURE and BACKGROUND at 45 seconds each on a NETWORK sheet come to
    1.50 + 0.98 + 0.53 = 3.01 credits.
    """
    work = new_cataloged_work(api, composer_overrides={"pro_affiliation": "ASCAP"})
    blanket = new_active_blanket(api, new_licensee(api, legal_name="Meridian Broadcasting"))
    open_usage_report(api, blanket)
    sheet = new_cue_sheet(
        api,
        [
            build.cue(work.composition_id, "THEME", 45),
            build.cue(work.composition_id, "FEATURE", 45),
            build.cue(work.composition_id, "BACKGROUND", 45),
        ],
        usage_report_id=blanket.usage_report_id,
        production_title="Coastal Nights S01E01",
    )
    return work, sheet


class TestCueSheetSocietyRejectionCycle:
    def test_reregistration_after_a_society_rejection_increments_the_round(self, api):
        """PRD §3.7: "Re-registration after a society rejection is unbounded and
        increments `registration_round` each time."

        Design: Corner/state_machines/society_rejection_then_reregistration_increments_registration_round
        """
        _work, sheet = _collected_three_cue_sheet(api)

        registered = register_cue_sheet(api, sheet["id"], "ASCAP-2026-0001")
        assert_status(registered, "REGISTERED")
        assert registered["registration_round"] == 1
        assert registered["society_reference"] == "ASCAP-2026-0001"

        rejected = assert_ok(
            api.record_society_decision(
                sheet["id"],
                {"decision": "REJECT", "rejection_reason": "cue timings unreadable"},
                RIGHTS_MANAGER,
            )
        )
        assert_status(rejected, "REJECTED_BY_SOCIETY")
        assert rejected["rejection_reason"] == "cue timings unreadable"
        assert rejected["registration_round"] == 1

        reregistered = register_cue_sheet(api, sheet["id"], "ASCAP-2026-0002")
        assert_status(reregistered, "REGISTERED")
        assert reregistered["registration_round"] == 2
        assert reregistered["society_reference"] == "ASCAP-2026-0002"
        assert reregistered["rejection_reason"] is None

    def test_society_rejection_appends_the_compensating_performance_reversal(self, api):
        """PRD §3.7: "On `REJECT` a `rejection_reason` must be supplied, absent which
        the request is refused with `ERR_VALIDATION`; the sheet moves `REGISTERED →
        REJECTED_BY_SOCIETY`, and one compensating entry with the performance-reversal
        origin is appended per previously credited composer, each for the negation of
        the performance amount it compensates."

        Design: Corner/state_machines/society_rejection_then_reregistration_increments_registration_round
        """
        work, sheet = _collected_three_cue_sheet(api)

        register_cue_sheet(api, sheet["id"], "ASCAP-2026-0001")
        assert_composer_money(
            read_composer(api, work.composer_id), accrued_unpaid_cents=1882
        )

        assert_ok(
            api.record_society_decision(
                sheet["id"],
                {"decision": "REJECT", "rejection_reason": "cue timings unreadable"},
                RIGHTS_MANAGER,
            )
        )
        assert_composer_money(read_composer(api, work.composer_id), accrued_unpaid_cents=0)

        register_cue_sheet(api, sheet["id"], "ASCAP-2026-0002")
        assert_composer_money(
            read_composer(api, work.composer_id), accrued_unpaid_cents=1882
        )

        entries = ledger_entries(api, work.composer_id)
        assert len(entries) == 3
        performance = select_ledger_entries(entries, source_type="PERFORMANCE")
        reversal = select_ledger_entries(entries, source_type="PERFORMANCE_REVERSAL")
        assert len(performance) == 2
        assert len(reversal) == 1
        for entry in performance:
            assert_cents_equal(entry["amount_cents"], 1882, "performance amount_cents")
        assert_cents_equal(reversal[0]["amount_cents"], -1882, "reversal amount_cents")
        for entry in entries:
            assert entry["source_ref_id"] == sheet["id"]
            assert entry["cash_recognized_at"] is None

    def test_lifetime_performance_credits_return_to_their_pre_registration_value(self, api):
        """PRD §3.7: "Because the sheet has now left both `REGISTERED` and
        `ACCEPTED_BY_SOCIETY`, `lifetime_performance_credits` on every cited work
        returns to its pre-registration value."

        Design: Corner/state_machines/society_rejection_then_reregistration_increments_registration_round
        """
        work, sheet = _collected_three_cue_sheet(api)

        assert [line["credits"] for line in sheet["cue_credit_breakdown"]] == [
            pytest.approx(1.50, abs=0.01),
            pytest.approx(0.98, abs=0.01),
            pytest.approx(0.53, abs=0.01),
        ]
        assert_credits_equal(sheet["total_credits"], 3.01, "total_credits")
        assert sheet["total_seconds"] == 135
        assert_credits_equal(
            read_composition(api, work.composition_id)["lifetime_performance_credits"],
            0.00,
            "lifetime_performance_credits",
        )

        register_cue_sheet(api, sheet["id"], "ASCAP-2026-0001")
        assert_credits_equal(
            read_composition(api, work.composition_id)["lifetime_performance_credits"],
            3.01,
            "lifetime_performance_credits",
        )

        assert_ok(
            api.record_society_decision(
                sheet["id"],
                {"decision": "REJECT", "rejection_reason": "cue timings unreadable"},
                RIGHTS_MANAGER,
            )
        )
        assert_credits_equal(
            read_composition(api, work.composition_id)["lifetime_performance_credits"],
            0.00,
            "lifetime_performance_credits",
        )

        register_cue_sheet(api, sheet["id"], "ASCAP-2026-0002")
        assert_credits_equal(
            read_composition(api, work.composition_id)["lifetime_performance_credits"],
            3.01,
            "lifetime_performance_credits",
        )
        assert_status(read_cue_sheet(api, sheet["id"]), "REGISTERED")


# ---------------------------------------------------------------------------
# Clock-driven licence expiry
# ---------------------------------------------------------------------------


def _issued_three_month_film_license(api):
    """A FILM per-use licence in ISSUED for 2026-09-01 over three months.

    Base 600000 x FILM 2.20 x NATIONAL 1.00 x term 0.70 gives a core of 924000,
    the 5.00 percent band then takes the fee to 877800 and the composer's 40
    percent sync share to 351120.
    """
    deal = new_accepted_deal(
        api,
        None,
        FILM_TIER,
        BIG_LICENSEE,
        14,
        requested_term_months=3,
        **FILM_REQUEST,
    )
    return issue_per_use_license(api, deal)


class TestLicenseExpiryByClock:
    def test_expiry_releases_committed_credit_without_reversing_the_accrual(self, api):
        """PRD §3.5: "Expiry lowers the licensee's `committed_spend_cents` by
        `final_fee_cents` and raises `credit_available_cents` by the same amount, and
        recomputes the work's `active_license_count` and `exclusive_block_until` — so
        the work's block lifts as soon as no other exclusive licence in `ISSUED` or
        `ACTIVE` still covers it."

        Design: Corner/state_machines/license_expiry_by_clock_releases_committed_credit_without_reversal
        """
        deal = _issued_three_month_film_license(api)

        assert_cents_equal(deal.license["final_fee_cents"], 877800, "final_fee_cents")
        assert_pct_equal(deal.license["final_discount_pct"], 5.00, "final_discount_pct")
        assert deal.license["term_end"].startswith("2026-11-30")
        assert_credit_exposure(read_licensee(api, deal.licensee_id), 877800, 0, 9122200)

        advance_clock(api, "2026-12-01T00:00:00Z")

        expired = read_license(api, deal.license_id)
        assert_status(expired, "EXPIRED")
        assert expired["revoke_reason"] is None
        assert_cents_equal(expired["collected_amount_cents"], 0, "collected_amount_cents")

        assert_credit_exposure(read_licensee(api, deal.licensee_id), 0, 0, 10000000)
        work_after = read_composition(api, deal.composition_id)
        assert work_after["active_license_count"] == 0
        assert work_after["exclusive_block_until"] is None

        entries = ledger_entries(api, deal.work.composer_id)
        assert len(entries) == 1
        assert entries[0]["source_type"] == "SYNC_FEE"
        assert_cents_equal(entries[0]["amount_cents"], 351120, "SYNC_FEE amount_cents")
        assert select_ledger_entries(entries, source_type="SYNC_FEE_REVERSAL") == []
        assert_composer_money(
            read_composer(api, deal.work.composer_id), accrued_unpaid_cents=351120
        )

    def test_the_sweep_reports_the_expired_licence_in_its_own_array(self, api):
        """PRD §2.5: "The response body reports `current_utc`, the new clock value, plus
        `expired_license_ids`, `expired_blanket_agreement_ids` and
        `delinquent_blanket_agreement_ids` — the three arrays of identifiers the sweep
        touched."

        Design: Corner/state_machines/license_expiry_by_clock_releases_committed_credit_without_reversal
        """
        deal = _issued_three_month_film_license(api)

        sweep = advance_clock(api, "2026-12-01T00:00:00Z")

        assert_same_instant(sweep["current_utc"], "2026-12-01T00:00:00Z")
        assert_sweep_lists(
            sweep,
            expired_license_ids=[deal.license_id],
            expired_blanket_agreement_ids=[],
            delinquent_blanket_agreement_ids=[],
        )


# ---------------------------------------------------------------------------
# The blanket reporting axis moves on its own
# ---------------------------------------------------------------------------


def _active_blanket_with_one_due_august_report(api):
    """An ACTIVE MONTHLY blanket over [2026-08-01, 2027-08-01) with 2026-08 due."""
    work = new_cataloged_work(api)
    blanket = new_active_blanket(api, new_licensee(api, legal_name="Meridian Broadcasting"))
    open_usage_report(api, blanket)
    return work, blanket


class TestBlanketReportingAxisMovesIndependently:
    def test_reporting_axis_turns_delinquent_only_past_the_grace_window(self, api):
        """PRD §3.6: "A cadence period is overdue at a given instant when that instant
        is later than the period's `period_end` plus a grace window of 15 days and no
        report for that agreement with that `period_start` sits in `SUBMITTED` or
        `ACCEPTED`."

        Design: Corner/state_machines/blanket_reporting_axis_moves_delinquent_then_compliant_while_coverage_holds
        """
        _work, blanket = _active_blanket_with_one_due_august_report(api)

        on_the_boundary = advance_clock(api, "2026-09-15T00:00:00Z")
        assert_sweep_lists(on_the_boundary, delinquent_blanket_agreement_ids=[])
        still_compliant = read_blanket_agreement(api, blanket.agreement_id)
        assert_blanket_axes(still_compliant, "ACTIVE", "COMPLIANT")
        assert still_compliant["delinquent_since"] is None

        past_the_boundary = advance_clock(api, "2026-09-16T00:00:00Z")
        assert_sweep_lists(
            past_the_boundary, delinquent_blanket_agreement_ids=[blanket.agreement_id]
        )
        delinquent = read_blanket_agreement(api, blanket.agreement_id)
        assert_blanket_axes(delinquent, "ACTIVE", "DELINQUENT")
        assert_same_instant(delinquent["delinquent_since"], "2026-09-16T00:00:00Z")

    def test_submission_restores_compliance_while_coverage_stays_active(self, api):
        """PRD §3.6: "Submission additionally re-evaluates the agreement's reporting
        axis and can move it `DELINQUENT → COMPLIANT`, which clears `delinquent_since`
        to null; that move is allowed only once every cadence period whose grace window
        has already closed has a report in `SUBMITTED` or `ACCEPTED`."

        Design: Corner/state_machines/blanket_reporting_axis_moves_delinquent_then_compliant_while_coverage_holds
        """
        work, blanket = _active_blanket_with_one_due_august_report(api)

        advance_clock(api, "2026-09-16T00:00:00Z")
        assert_blanket_axes(
            read_blanket_agreement(api, blanket.agreement_id), "ACTIVE", "DELINQUENT"
        )

        new_cue_sheet(
            api,
            [build.cue(work.composition_id, "THEME", 45)],
            usage_report_id=blanket.usage_report_id,
            production_title="Coastal Nights S01E01",
            broadcast_date="2026-08-10T00:00:00Z",
        )
        submitted = assert_ok(
            api.submit_usage_report(blanket.usage_report_id, None, blanket.licensee_headers)
        )
        assert_status(submitted, "SUBMITTED")
        assert_same_instant(submitted["submitted_at"], "2026-09-16T00:00:00Z")

        restored = read_blanket_agreement(api, blanket.agreement_id)
        assert_blanket_axes(restored, "ACTIVE", "COMPLIANT")
        assert restored["delinquent_since"] is None


# ---------------------------------------------------------------------------
# The amendment cycle and its two decision branches
# ---------------------------------------------------------------------------


AMENDMENT_ONE = {
    "proposed_writer_share_pct": 60.00,
    "proposed_publisher_share_pct": 40.00,
    "proposed_sync_fee_share_pct": 45.00,
    "proposed_holdback_days": 30,
}
AMENDMENT_TWO = {
    "proposed_writer_share_pct": 70.00,
    "proposed_publisher_share_pct": 30.00,
    "proposed_sync_fee_share_pct": 50.00,
    "proposed_holdback_days": 60,
}


def _active_fifty_fifty_agreement(api):
    """An ACTIVE agreement at writer 50, publisher 50, sync fee 40, holdback 0."""
    composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
    agreement = new_active_agreement(
        api, composer["id"], sync_fee_share_pct=40.00, holdback_days=0
    )
    return composer, agreement


class TestAmendmentDecisionBranches:
    def test_a_pending_amendment_leaves_the_effective_terms_untouched(self, api):
        """PRD §3.1: "The transition `ACTIVE → AMENDMENT_PENDING` copies the proposal
        into `pending_writer_share_pct`, `pending_publisher_share_pct`,
        `pending_sync_fee_share_pct` and `pending_holdback_days` and leaves the
        effective share fields entirely untouched — royalty maths carried out while an
        amendment is pending still uses the old, effective values."

        Design: Corner/state_machines/amendment_reject_versus_accept_diverge_on_effective_terms
        """
        _composer, agreement = _active_fifty_fifty_agreement(api)

        pending = assert_ok(
            api.create_amendment(agreement["id"], dict(AMENDMENT_ONE), RIGHTS_MANAGER)
        )

        assert_status(pending, "AMENDMENT_PENDING")
        assert_pct_equal(pending["pending_writer_share_pct"], 60.00, "pending_writer_share_pct")
        assert_pct_equal(
            pending["pending_publisher_share_pct"], 40.00, "pending_publisher_share_pct"
        )
        assert_pct_equal(
            pending["pending_sync_fee_share_pct"], 45.00, "pending_sync_fee_share_pct"
        )
        assert pending["pending_holdback_days"] == 30
        assert_pct_equal(pending["writer_share_pct"], 50.00, "writer_share_pct")
        assert_pct_equal(pending["publisher_share_pct"], 50.00, "publisher_share_pct")
        assert_pct_equal(pending["sync_fee_share_pct"], 40.00, "sync_fee_share_pct")
        assert pending["holdback_days"] == 0
        assert pending["amendment_round"] == 0

    def test_a_rejected_amendment_changes_nothing_and_keeps_the_round(self, api):
        """PRD §3.1: "On `REJECT`, all four pending fields are cleared to null and both
        `amendment_round` and every effective field are left exactly as they were."

        Design: Corner/state_machines/amendment_reject_versus_accept_diverge_on_effective_terms
        """
        composer, agreement = _active_fifty_fifty_agreement(api)
        assert_ok(api.create_amendment(agreement["id"], dict(AMENDMENT_ONE), RIGHTS_MANAGER))

        decided = assert_ok(
            api.decide_amendment(
                agreement["id"], {"decision": "REJECT"}, make_composer_headers(composer["id"])
            )
        )

        assert_status(decided, "ACTIVE")
        assert decided["amendment_round"] == 0
        assert_pct_equal(decided["writer_share_pct"], 50.00, "writer_share_pct")
        assert_pct_equal(decided["publisher_share_pct"], 50.00, "publisher_share_pct")
        assert_pct_equal(decided["sync_fee_share_pct"], 40.00, "sync_fee_share_pct")
        assert decided["holdback_days"] == 0
        assert decided["pending_writer_share_pct"] is None
        assert decided["pending_publisher_share_pct"] is None
        assert decided["pending_sync_fee_share_pct"] is None
        assert decided["pending_holdback_days"] is None

    def test_an_accepted_amendment_copies_every_pending_value_and_bumps_the_round(self, api):
        """PRD §3.1: "On `ACCEPT`, each pending value is copied into its matching
        effective field, `amendment_round` increases by 1, and all four pending fields
        are then cleared to null."

        Design: Corner/state_machines/amendment_reject_versus_accept_diverge_on_effective_terms
        """
        composer, agreement = _active_fifty_fifty_agreement(api)
        composer_headers = make_composer_headers(composer["id"])

        assert_ok(api.create_amendment(agreement["id"], dict(AMENDMENT_ONE), RIGHTS_MANAGER))
        assert_ok(
            api.decide_amendment(agreement["id"], {"decision": "REJECT"}, composer_headers)
        )

        second = assert_ok(
            api.create_amendment(agreement["id"], dict(AMENDMENT_TWO), RIGHTS_MANAGER)
        )
        assert_status(second, "AMENDMENT_PENDING")
        assert_pct_equal(second["pending_writer_share_pct"], 70.00, "pending_writer_share_pct")
        assert second["pending_holdback_days"] == 60

        accepted = assert_ok(
            api.decide_amendment(agreement["id"], {"decision": "ACCEPT"}, composer_headers)
        )

        assert_status(accepted, "ACTIVE")
        assert accepted["amendment_round"] == 1
        assert_pct_equal(accepted["writer_share_pct"], 70.00, "writer_share_pct")
        assert_pct_equal(accepted["publisher_share_pct"], 30.00, "publisher_share_pct")
        assert_pct_equal(accepted["sync_fee_share_pct"], 50.00, "sync_fee_share_pct")
        assert accepted["holdback_days"] == 60
        assert accepted["pending_writer_share_pct"] is None
        assert accepted["pending_publisher_share_pct"] is None
        assert accepted["pending_sync_fee_share_pct"] is None
        assert accepted["pending_holdback_days"] is None
