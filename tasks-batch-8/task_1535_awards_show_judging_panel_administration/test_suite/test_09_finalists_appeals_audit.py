"""Finalist notification and promotion, embargo visibility, appeals and the
retraction cascade, and the season audit chain (PRD §2.10, §2.11, §3.7, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    assert_announcement,
    assert_appeal,
    assert_audit_log,
    assert_entry,
    assert_finalist_record,
    assert_fulfillment_order,
    make_entrant_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.constants import GENESIS_HASH_PREV, T_AFTER_EMBARGO_LIFT
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestFinalistPromotion:
    def test_declined_finalist_promotes_next_ranked_entry(self, api):
        """PRD §3.7: "The entrant may instead decline, and the clock sweep
        auto-declines any `NOTIFIED` record whose acknowledgement window lapses;
        either path produces `DECLINED`, which is terminal, and triggers finalist
        promotion: the highest-ranked `NON_FINALIST` entry in the category,
        ordered by `final_composite_score` descending, then `FINAL`-round
        composite descending, then `created_at` ascending, is promoted to
        `FINALIST` with a fresh record in `PENDING` whose `announced_rank`
        inherits the vacated rank, while the declining entry's status becomes
        `NON_FINALIST`"

        Design: Corner/calculations/finalist_promotion_on_decline
        """
        bundle = fx.setup_finalists_locked(
            num_entries=3, finalist_slots=2, code="GALA-PROMO"
        )
        e1, e2, e3 = bundle["entries"]
        ent1 = bundle["entrants"][0]
        fin1 = bundle["finalist_records"][e1["id"]]
        fin2 = bundle["finalist_records"][e2["id"]]
        assert bundle["finalist_records"][e3["id"]] is None
        assert fin1["announced_rank"] == 1
        assert fin2["announced_rank"] == 2

        validate_success(api.notify_finalist(fin1["id"], ADMIN))
        declined = validate_success(
            api.decline_finalist(fin1["id"], make_entrant_headers(ent1["id"]))
        )
        assert_finalist_record(declined)
        assert declined["notification_status"] == "DECLINED"

        # Declining entry demoted; only remaining NON_FINALIST promoted.
        e1_now = fx.get_entry(e1["id"])
        assert e1_now["status"] == "NON_FINALIST"
        e3_now = fx.get_entry(e3["id"])
        assert e3_now["status"] == "FINALIST"
        promoted = fx.get_finalist_record(e3["id"])
        assert promoted is not None
        assert promoted["notification_status"] == "PENDING"
        assert promoted["announced_rank"] == 1, "the new record inherits the vacated rank"

        # The untouched finalist keeps its rank-2 record.
        e2_now = fx.get_entry(e2["id"])
        assert e2_now["status"] == "FINALIST"
        fin2_now = fx.get_finalist_record(e2["id"])
        assert fin2_now["id"] == fin2["id"]
        assert fin2_now["announced_rank"] == 2
        assert fin2_now["notification_status"] == "PENDING"


class TestEmbargoVisibility:
    def test_embargo_visible_stays_false_until_lift_and_live(self, api):
        """PRD §2.10: "A finalist record's `embargo_visible` becomes true only
        when the clock has reached `embargo_lifts_at` and the season stands in
        `CEREMONY_LIVE` or `PUBLISHED`; the go-live transition, the
        publish-results transition, and the clock sweep are the three moments at
        which the server re-evaluates the flag"
        PRD §3.7: "Each finalist record is born with `notification_status`
        `PENDING`, `notified_at` unset, and `embargo_visible` false"

        Design: Corner/calculations/embargo_visibility_flip
        """
        bundle = fx.setup_embargoed_season(
            num_entries=1, finalist_slots=1, code="GALA-EMBV"
        )
        entry = bundle["entries"][0]
        record = fx.get_finalist_record(entry["id"])
        assert record["embargo_visible"] is False

        fx.set_clock(T_AFTER_EMBARGO_LIFT)  # clock crosses the lift instant
        record_after = fx.get_finalist_record(entry["id"])
        assert record_after["embargo_visible"] is False, (
            "season is still EMBARGOED (not CEREMONY_LIVE/PUBLISHED), so the "
            "flag must stay false"
        )


class TestAppealCap:
    def test_third_open_appeal_rejected_at_cap(self, api):
        """PRD §3.8: "An entry may carry fewer than the season's
        `max_appeals_per_entry` appeals in the non-terminal states `FILED` and
        `UNDER_REVIEW`; a filing at the cap is rejected with
        `ERR_APPEAL_CAP_EXCEEDED`."
        PRD §3.8: "The `filed_by_entrant_id` must match the acting user's own
        `Entrant` `id`, and the filing entrant must own at least one
        non-`WITHDRAWN` entry in the appealed entry's category."

        Design: Corner/validations/appeal_cap_enforced
        """
        bundle = fx.setup_eligible_entry(
            "GALA-CAP", season_overrides={"max_appeals_per_entry": 2}
        )
        category, entry = bundle["category"], bundle["entry"]
        entrant2 = fx.register_entrant("e2@x.com", "Entrant 2")
        # Competitor standing: a non-WITHDRAWN entry of entrant 2 in the category.
        fx.create_draft_entry(category["id"], entrant2["id"], title="Work 2")

        first = fx.file_appeal(entry["id"], entrant2["id"], grounds="SCORING_ERROR", narrative="first")
        validate_success(first, expected_status=201)
        second = fx.file_appeal(
            entry["id"], entrant2["id"], grounds="PROCEDURAL_VIOLATION", narrative="second"
        )
        validate_success(second, expected_status=201)
        third = fx.file_appeal(
            entry["id"], entrant2["id"], grounds="ELIGIBILITY_MISREAD", narrative="third"
        )
        validate_error(third, ApiErrorId.ERR_APPEAL_CAP_EXCEEDED)


class TestAppealUpheldRetractionCascade:
    def _setup_appeal_under_review(self, api, code: str):
        """Season CEREMONY_LIVE with the winner announced; an appeal against the
        winner entry (grounds CONFLICT_UNDECLARED) taken UNDER_REVIEW."""
        bundle = fx.setup_announced_winner(
            num_entries=3, finalist_slots=2, code=code, matrix=fx.APPEAL_MATRIX
        )
        winner_entry = bundle["entries"][0]
        assert winner_entry["status"] == "WINNER"
        assert winner_entry["final_rank"] == 1
        filing_entrant = bundle["entrants"][2]  # owns the NON_FINALIST entry
        appeal_resp = fx.file_appeal(
            winner_entry["id"],
            filing_entrant["id"],
            grounds="CONFLICT_UNDECLARED",
            narrative="A panelist failed to declare an affiliation with the winner.",
        )
        appeal = validate_success(appeal_resp, expected_status=201)
        appeal = validate_success(api.take_appeal_under_review(appeal["id"], AUDITOR))
        assert appeal["status"] == "UNDER_REVIEW"
        bundle["appeal"] = appeal
        bundle["winner_entry"] = winner_entry
        bundle["filing_entrant"] = filing_entrant
        return bundle

    def test_upheld_rescore_voids_round(self, api):
        """PRD §3.8: "Upholding requires a `remedy` argument of `RESCORE`,
        `REINSTATE`, or `NONE`; it records `decided_at`, records the acting
        auditor's opaque id in `decided_by`, stores the `remedy`, and appends
        `APPEAL_UPHELD`. A `RESCORE` remedy voids the scoring round that
        produced the appealed score — `NORMALIZED` to `VOIDED`"
        PRD §2.11: "It starts `CLEAN`; it moves to `UNDER_REVIEW` when an appeal
        is taken under review, when a scoring round is voided on appeal, or when
        a winner announcement is retracted"

        Design: Difficulty/transitive_cascade/appeal_upheld_retraction_cascade
        """
        bundle = self._setup_appeal_under_review(api, "GALA-APU")
        upheld = validate_success(
            api.uphold_appeal(bundle["appeal"]["id"], {"remedy": "RESCORE"}, AUDITOR)
        )
        assert_appeal(upheld)
        assert upheld["status"] == "UPHELD"
        assert upheld["remedy"] == "RESCORE"
        assert upheld["decided_at"] is not None
        round_now = validate_success(api.get_round(bundle["round"]["id"], ADMIN))
        assert round_now["status"] == "VOIDED", (
            "RESCORE voids the scoring round that produced the appealed score"
        )
        season_now = fx.get_season(bundle["season"]["id"])
        assert season_now["integrity_flag"] == "UNDER_REVIEW"

    def test_retraction_disqualifies_winner_and_cancels_trophy(self, api):
        """PRD §3.8: "An `Auditor` retracts the announcement, recording a
        `retraction_reason`; the announcement moves from `ANNOUNCED` to
        `RETRACTED`, the season's `integrity_flag` becomes `UNDER_REVIEW`, and
        `WINNER_RETRACTED` is appended. The winner's disposition depends on the
        grounds: with `CONFLICT_UNDECLARED` the entry is disqualified outright —
        `disqualified_reason` is recorded, the entrant's
        `lifetime_disqualifications` is incremented by one (reaching three
        promotes the entrant to `BARRED`), the season's `active_entries_count`
        is decremented by one, and any linked fulfillment order not yet
        `SHIPPED` or `DELIVERED` is cancelled"
        PRD §3.8: "Retraction also cancels the winner's `TROPHY` order while it
        is still in `DRAFT`, `QUEUED`, or `IN_PRODUCTION`."

        Design: Difficulty/transitive_cascade/appeal_upheld_retraction_cascade
        """
        bundle = self._setup_appeal_under_review(api, "GALA-APR")
        validate_success(
            api.uphold_appeal(bundle["appeal"]["id"], {"remedy": "RESCORE"}, AUDITOR)
        )
        retracted = validate_success(
            api.retract_announcement(
                bundle["announcement"]["id"],
                {"retraction_reason": "undeclared conflict in final panel"},
                AUDITOR,
            )
        )
        assert_announcement(retracted)
        assert retracted["status"] == "RETRACTED"

        winner_now = fx.get_entry(bundle["winner_entry"]["id"])
        assert_entry(winner_now)
        assert winner_now["status"] == "DISQUALIFIED"
        assert winner_now["disqualified_reason"], "disqualification must record a reason"

        entrant_now = validate_success(
            api.get_entrant(bundle["entrants"][0]["id"], ADMIN)
        )
        assert entrant_now["lifetime_disqualifications"] == 1

        season_now = fx.get_season(bundle["season"]["id"])
        assert season_now["integrity_flag"] == "UNDER_REVIEW"

        orders = fx.get_success_data(
            api.list_entry_fulfillment_orders(bundle["winner_entry"]["id"], ADMIN)
        )
        trophy = [o for o in orders if o["item_type"] == "TROPHY"]
        assert len(trophy) == 1
        assert_fulfillment_order(trophy[0])
        assert trophy[0]["status"] == "CANCELLED"


class TestAuditChain:
    def test_audit_rows_hash_chained(self, api):
        """PRD §2.11: "Rows are hash-chained for tamper evidence: each row's
        `hash_chain_prev` is the SHA-256 of the previous audit row in the same
        season, with the genesis row using sixty-four zero hex characters, and
        each row's `hash_chain_self` is the SHA-256 computed over the
        concatenation of `hash_chain_prev`, `action`, `target_id`, and the
        canonical form of `detail`."
        PRD §3.1: "Publishing from `DRAFT` requires the parent season to be
        `DRAFT` or `OPEN`, the rubric weights to sum to exactly 10,000, a
        `panel_size` of at least 3, and at least one finalist slot — violations
        surface as `ERR_CONSTRAINT_VIOLATION` or `ERR_INVALID_STATE` — and
        appends a `CATEGORY_PUBLISH` audit row."
        PRD §3.1: "a premature or tardy attempt fails with `ERR_OUTSIDE_WINDOW`,
        and success appends a `SEASON_OPEN` audit row."

        Design: Corner/endpoints/audit_log_hash_chain_appended
        """
        season = fx.create_season("GALA-AUD")
        fx.create_published_category(season["id"], code="CAT-AUD")
        fx.open_season(season["id"])

        rows = fx.get_success_data(
            api.list_audit_logs(season["id"], AUDITOR, params={"limit": 100})
        )
        assert len(rows) == 2
        for row in rows:
            assert_audit_log(row)
        actions = {row["action"] for row in rows}
        assert actions == {"CATEGORY_PUBLISH", "SEASON_OPEN"}

        genesis = [r for r in rows if r["hash_chain_prev"] == GENESIS_HASH_PREV]
        assert len(genesis) == 1, "exactly one genesis row per season chain"
        self_hashes = {row["hash_chain_self"] for row in rows}
        for row in rows:
            if row["hash_chain_prev"] == GENESIS_HASH_PREV:
                continue
            assert row["hash_chain_prev"] in self_hashes, (
                "each subsequent row's hash_chain_prev must equal the previous "
                "row's hash_chain_self"
            )
