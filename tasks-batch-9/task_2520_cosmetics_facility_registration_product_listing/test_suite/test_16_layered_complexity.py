"""The layered behaviours: two optimistic-concurrency guards seen as real
write-conflict detectors — a sibling filing consuming the facility token and a
sibling withdrawal round consuming the recall token — and the compliance sweep
proved to be a checkpoint per clock value rather than per call.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import OFFICER_HEADERS, make_facility_registrant_headers
from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X

ASTER_LABS = "Aster Labs Newark"
ASTER_HOLDINGS = "Aster Holdings LLC"
BRIGHTLINE_HOLDINGS = "Brightline Beauty Holdings"
HALCYON_HOLDINGS = "Halcyon Personal Care Group"
DESIGNEE_NAME = "Aster Brands Inc"
CHANGE_EFFECTIVE_DATE = "2026-08-01"
FILING_DEADLINE_AT = "2026-09-30T23:59:59.999Z"


def _registered_establishment(api):
    """One approved establishment whose version is read straight off the approval."""
    return X.create_registered_facility(
        api, facility_name=ASTER_LABS, owner_operator_name=ASTER_HOLDINGS,
        state_or_province="NJ",
    )


class TestASiblingFilingConsumesTheFacilityVersionToken:
    """The token is invalidated by a write on the parent, not by a bad payload."""

    def test_the_first_filing_lands_with_its_sixty_day_deadline(self, api):
        """A filing declaring the version just read is accepted, and its deadline falls at the very
        end of the sixtieth day after the transfer took effect.

        PRD: "The new filing starts in `status` `FILED`, records the establishment through its `facility_id`, stamps `filed_at` with the logical-clock instant at which the server accepted it, and derives `filing_deadline_at` as the end of the day 60 days after `change_effective_date` — that is, the instant 23:59:59.999Z on that day, so a filing made at any point during the deadline day is on time."
        PRD: "The boolean `is_late_filing` is true exactly when `filed_at` is strictly after `filing_deadline_at`, and false otherwise, including the boundary case where the two are equal."
        PRD: "Both `decision_note` and `decided_by_user_id` are null while the filing is `FILED` or `SUPERSEDED`."

        Design: Corner/complexity_layers/second_ownership_filing_with_the_first_filings_version_is_rejected
        """
        facility = _registered_establishment(api)
        registrant = make_facility_registrant_headers(facility["id"])

        filing = get_success_data(
            api.file_ownership_change(
                facility["id"],
                F.ownership_change_payload(facility["version"],
                                           change_effective_date=CHANGE_EFFECTIVE_DATE,
                                           new_owner_operator_name=BRIGHTLINE_HOLDINGS),
                registrant,
            )
        )

        assert filing["status"] == K.OWNERSHIP_CHANGE_STATUS_FILED
        assert filing["facility_id"] == facility["id"]
        assert filing["filed_at"] == K.DEFAULT_CLOCK_UTC
        assert filing["filing_deadline_at"] == FILING_DEADLINE_AT
        assert filing["is_late_filing"] is False
        assert filing["decision_note"] is None
        assert filing["decided_by_user_id"] is None
        assert X.read_facility(api, facility["id"])["version"] == facility["version"] + 1

    def test_the_second_filing_replaying_the_consumed_version_is_rejected(self, api):
        """The first filing raised the establishment's version, so a second filing built from the
        pre-filing snapshot is a write conflict and nothing of it survives.

        PRD: "If the facility's version has advanced since the caller last read it, the filing is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412)."
        PRD: "On success the service supersedes each prior filing that is still open, inserts the new filing, and increments the facility's `version` by exactly 1 — which means replaying the identical request with the now-stale version fails, so ownership-change filing is deliberately not idempotent."

        Design: Corner/complexity_layers/second_ownership_filing_with_the_first_filings_version_is_rejected
        """
        facility = _registered_establishment(api)
        registrant = make_facility_registrant_headers(facility["id"])
        first = get_success_data(
            api.file_ownership_change(
                facility["id"],
                F.ownership_change_payload(facility["version"],
                                           change_effective_date=CHANGE_EFFECTIVE_DATE,
                                           new_owner_operator_name=BRIGHTLINE_HOLDINGS),
                registrant,
            )
        )

        validate_error(
            api.file_ownership_change(
                facility["id"],
                F.ownership_change_payload(facility["version"],
                                           change_effective_date=CHANGE_EFFECTIVE_DATE,
                                           new_owner_operator_name=HALCYON_HOLDINGS),
                registrant,
            ),
            E.ERR_STALE_FACILITY_VERSION,
        )

        rows, meta = validate_paginated(
            api.list_ownership_changes(facility["id"], registrant, {"limit": K.MAX_LIMIT})
        )
        assert meta["total_count"] == 1
        assert A.ids_of(rows) == [first["id"]]
        assert rows[0]["status"] == K.OWNERSHIP_CHANGE_STATUS_FILED
        assert X.read_facility(api, facility["id"])["version"] == facility["version"] + 1

    def test_the_refreshed_version_files_the_change_and_supersedes_the_first(self, api):
        """Re-reading the establishment yields a usable token, and the accepted filing pushes its
        predecessor out of the open slot without renaming the owner of record.

        PRD: "On acceptance of the filing itself, the service first moves **every** filing of that establishment still sitting in `FILED` to `SUPERSEDED`, so at most one filing per establishment is ever open, and only then inserts the new row."
        PRD: "`FILED → ACCEPTED` overwrites the establishment's `owner_operator_name` with `new_owner_operator_name`, sets `abbreviated_renewal_eligible` to false, appends an `OWNERSHIP_CHANGE` ledger entry whose `subject_entity` is `OwnershipChangeUpdate` and whose `subject_id` is the filing, and increments both the filing's `version` and the establishment's `version` by exactly 1."

        Design: Corner/complexity_layers/second_ownership_filing_with_the_first_filings_version_is_rejected
        """
        facility = _registered_establishment(api)
        registrant = make_facility_registrant_headers(facility["id"])
        first = get_success_data(
            api.file_ownership_change(
                facility["id"],
                F.ownership_change_payload(facility["version"],
                                           change_effective_date=CHANGE_EFFECTIVE_DATE,
                                           new_owner_operator_name=BRIGHTLINE_HOLDINGS),
                registrant,
            )
        )

        refreshed = X.read_facility(api, facility["id"])
        assert refreshed["version"] == facility["version"] + 1

        second = get_success_data(
            api.file_ownership_change(
                facility["id"],
                F.ownership_change_payload(refreshed["version"],
                                           change_effective_date=CHANGE_EFFECTIVE_DATE,
                                           new_owner_operator_name=HALCYON_HOLDINGS),
                registrant,
            )
        )
        assert second["status"] == K.OWNERSHIP_CHANGE_STATUS_FILED

        superseded, _ = validate_paginated(
            api.list_ownership_changes(
                facility["id"], registrant,
                {"status": K.OWNERSHIP_CHANGE_STATUS_SUPERSEDED, "limit": K.MAX_LIMIT},
            )
        )
        assert A.ids_of(superseded) == [first["id"]]
        still_open, _ = validate_paginated(
            api.list_ownership_changes(
                facility["id"], registrant,
                {"status": K.OWNERSHIP_CHANGE_STATUS_FILED, "limit": K.MAX_LIMIT},
            )
        )
        assert A.ids_of(still_open) == [second["id"]]

        after = X.read_facility(api, facility["id"])
        assert after["owner_operator_name"] == ASTER_HOLDINGS
        assert after["version"] == facility["version"] + 2


def _recall_with_an_accepted_plan(api):
    """An establishment, a listing, and a recall whose retail-level plan OFF-1 accepted."""
    bundle = X.registered_facility_with_listing(
        api,
        listing_overrides={"product_name": "Aster Blush Powder", "lot_authorized_units": 5000},
        person_overrides={"legal_name": DESIGNEE_NAME},
        facility_overrides={"facility_name": ASTER_LABS,
                            "owner_operator_name": ASTER_HOLDINGS},
    )
    bundle["recall"] = X.recall_with_accepted_plan(
        api, bundle["listing_id"], bundle["agent"],
        initiation_basis=K.INITIATION_BASIS_MANDATORY, officer=OFFICER_HEADERS,
    )
    bundle["recall_id"] = bundle["recall"]["id"]
    return bundle


class TestASiblingRoundConsumesTheRecallVersionToken:
    """The same guard on another aggregate, where the conflict would destroy a production."""

    def test_the_first_round_opens_empty_and_moves_the_recall_to_executing(self, api):
        """Opening a round against the version read at the plan decision is accepted, and the round
        starts with nothing produced while the recall enters execution.

        PRD: "A successful open creates a `MarketWithdrawal` with `status` `OPEN`, `records_produced_count` 0, `shipped_units_total` 0, `outstanding_units_total` 0 and both recovery rates 0.00, moves the recall to `EXECUTING` — from `PLAN_ACCEPTED`, from `EXTENDED`, or as a self-loop from `EXECUTING` — and raises the recall's `version` by exactly 1."

        Design: Corner/complexity_layers/second_withdrawal_with_the_first_withdrawals_version_is_rejected
        """
        bundle = _recall_with_an_accepted_plan(api)
        accepted_version = bundle["recall"]["version"]

        first = X.open_withdrawal(api, bundle["recall"], OFFICER_HEADERS, K.DEPTH_RETAIL)

        assert first["status"] == K.WITHDRAWAL_STATUS_OPEN
        assert first["scope_depth"] == K.DEPTH_RETAIL
        assert first["records_produced_count"] == 0
        assert first["shipped_units_total"] == 0
        assert first["outstanding_units_total"] == 0
        A.assert_two_decimal_value(first["reported_recovery_rate"], 0.00, "reported rate")
        A.assert_two_decimal_value(first["verified_recovery_rate"], 0.00, "verified rate")

        recall = X.read_recall(api, bundle["recall_id"])
        assert recall["status"] == K.RECALL_STATUS_EXECUTING
        assert recall["version"] == accepted_version + 1

    def test_the_second_round_replaying_the_plan_decision_version_is_rejected(self, api):
        """The round-one open consumed the token, so a round-two open carrying it is a write
        conflict — and no forked second round exists afterwards.

        PRD: "A mismatch is rejected with `ERR_STALE_RECALL_VERSION` (HTTP 412)."
        PRD: "The reason this operation is guarded at all is destructive: opening a new round **supersedes** the recall's prior non-terminal withdrawal and releases the distribution records that round had produced, so a caller acting on a stale version would silently throw away another party's document production."

        Design: Corner/complexity_layers/second_withdrawal_with_the_first_withdrawals_version_is_rejected
        """
        bundle = _recall_with_an_accepted_plan(api)
        accepted_version = bundle["recall"]["version"]
        first = X.open_withdrawal(api, bundle["recall"], OFFICER_HEADERS, K.DEPTH_RETAIL)

        validate_error(
            api.open_withdrawal(
                bundle["recall_id"],
                F.withdrawal_payload(accepted_version, K.DEPTH_CONSUMER),
                OFFICER_HEADERS,
            ),
            E.ERR_STALE_RECALL_VERSION,
        )

        rows, meta = validate_paginated(
            api.list_withdrawals(bundle["recall_id"], OFFICER_HEADERS, {"limit": K.MAX_LIMIT})
        )
        assert meta["total_count"] == 1
        assert A.ids_of(rows) == [first["id"]]
        assert rows[0]["status"] == K.WITHDRAWAL_STATUS_OPEN

    def test_the_refreshed_version_opens_the_superseding_round(self, api):
        """After a re-read the deeper round opens, and it displaces its predecessor rather than
        running beside it — two rows, newest first, only one of them live.

        PRD: "Opening two rounds in succession under one executing recall is perfectly legal in either order — round two supersedes round one — but a caller who read the recall's `version` before round one existed must re-read it before opening round two."
        PRD: "Any predecessor withdrawal whose `status` was `OPEN`, `RECORDS_PRODUCED`, `INTERIM_REVIEWED` or `EXTENDED_INEFFECTIVE` becomes `SUPERSEDED`, which is terminal: each of its linked distribution records has its `withdrawal_id` cleared back to null so the successor round can produce them afresh, and the predecessor's `records_produced_count`, `shipped_units_total` and `outstanding_units_total` are all zeroed."
        PRD: "Withdrawal rounds under a recall are listed newest first with an optional `status` filter, and each round is readable on its own, exposing every pinned intermediate of the verified-basis calculation."

        Design: Corner/complexity_layers/second_withdrawal_with_the_first_withdrawals_version_is_rejected
        """
        bundle = _recall_with_an_accepted_plan(api)
        accepted_version = bundle["recall"]["version"]
        first = X.open_withdrawal(api, bundle["recall"], OFFICER_HEADERS, K.DEPTH_RETAIL)
        validate_error(
            api.open_withdrawal(
                bundle["recall_id"],
                F.withdrawal_payload(accepted_version, K.DEPTH_CONSUMER),
                OFFICER_HEADERS,
            ),
            E.ERR_STALE_RECALL_VERSION,
        )

        refreshed = X.read_recall(api, bundle["recall_id"])
        assert refreshed["version"] == accepted_version + 1

        second = X.open_withdrawal(api, refreshed, OFFICER_HEADERS, K.DEPTH_CONSUMER)
        assert second["id"] != first["id"]
        assert second["status"] == K.WITHDRAWAL_STATUS_OPEN
        assert second["scope_depth"] == K.DEPTH_CONSUMER

        rows, meta = validate_paginated(
            api.list_withdrawals(bundle["recall_id"], OFFICER_HEADERS, {"limit": K.MAX_LIMIT})
        )
        assert meta["total_count"] == 2
        assert A.ids_of(rows) == [second["id"], first["id"]]
        assert X.read_withdrawal(api, first["id"])["status"] == K.WITHDRAWAL_STATUS_SUPERSEDED


WINDOW_OPEN_INSTANT = "2028-05-02T00:00:00Z"


class TestTheSweepIsACheckpointPerClockValue:
    """Real work on the first run, none on the second, with the clock held still."""

    def _establishment_on_the_first_day_of_its_window(self, api):
        """An establishment approved on 2026-08-01, observed on the day its window opens."""
        facility = _registered_establishment(api)
        X.set_clock(api, WINDOW_OPEN_INSTANT)
        return facility

    def test_the_first_sweep_marks_the_establishment_renewal_due(self, api):
        """The window opened today, so the checkpoint finds exactly one establishment to advise and
        nothing to lapse — coverage still has three months to run.

        PRD: "An establishment whose `registration_status` is `REGISTERED` and whose `renewal_window_open_date` has arrived is moved to `RENEWAL_DUE`, and each such move is counted in `renewal_due_facility_count`."
        PRD: "From `period_end`, two further dates fall out: `renewal_window_open_date` is 90 days before `period_end`, and `grace_end_date` is 60 days after `period_end`."

        Design: Corner/complexity_layers/sweep_is_a_checkpoint_that_does_not_repeat_its_work_at_a_fixed_clock
        """
        facility = self._establishment_on_the_first_day_of_its_window(api)

        result = X.run_sweep(api)

        A.assert_sweep_counters(result, renewal_due_facility_count=1)
        assert result["swept_at"] == WINDOW_OPEN_INSTANT

        after = X.read_facility(api, facility["id"])
        assert after["registration_status"] == K.REGISTRATION_STATUS_RENEWAL_DUE
        assert after["current_period_end"] == K.CANONICAL_PERIOD_END
        assert after["renewal_window_open_date"] == K.CANONICAL_RENEWAL_WINDOW_OPEN_DATE
        assert after["grace_end_date"] == K.CANONICAL_GRACE_END_DATE

    def test_the_repeat_sweep_at_the_same_clock_claims_no_work(self, api):
        """Running the checkpoint again without moving the clock reports every counter at zero and
        writes nothing, so the establishment's version is untouched by the second observation.

        PRD: "Running it twice without moving the logical clock in between yields a second response whose every counter is zero and whose `swept_at` equals the clock, because each of the three steps selects only records whose state still admits the transition, and the first run has already moved them all."
        PRD: "That property is what makes the sweep safe to run as often as an operator likes: it is an observation of the clock, not an increment of anything."

        Design: Corner/complexity_layers/sweep_is_a_checkpoint_that_does_not_repeat_its_work_at_a_fixed_clock
        """
        facility = self._establishment_on_the_first_day_of_its_window(api)
        X.run_sweep(api)
        after_first = X.read_facility(api, facility["id"])

        repeat = X.run_sweep(api)

        A.assert_sweep_counters(repeat)
        assert repeat["swept_at"] == WINDOW_OPEN_INSTANT

        after_second = X.read_facility(api, facility["id"])
        assert after_second["registration_status"] == K.REGISTRATION_STATUS_RENEWAL_DUE
        assert after_second["version"] == after_first["version"]

    def test_the_repeat_sweep_appends_nothing_to_the_ledger(self, api):
        """A checkpoint that claims no work leaves the append-only ledger byte for byte where the
        first run left it — no duplicate compliance fact is recorded for one clock value.

        PRD: "Entries are never updated and never deleted; the only way to correct the record is to append a further entry."
        PRD: "Running it twice without moving the logical clock in between yields a second response whose every counter is zero and whose `swept_at` equals the clock, because each of the three steps selects only records whose state still admits the transition, and the first run has already moved them all."

        Design: Corner/complexity_layers/sweep_is_a_checkpoint_that_does_not_repeat_its_work_at_a_fixed_clock
        """
        facility = self._establishment_on_the_first_day_of_its_window(api)
        X.run_sweep(api)
        before, before_meta = X.read_ledger(api, facility["id"])

        X.run_sweep(api)

        after, after_meta = X.read_ledger(api, facility["id"])
        assert after_meta["total_count"] == before_meta["total_count"]
        assert A.ids_of(after) == A.ids_of(before)
        assert [row["sequence_no"] for row in after] == [row["sequence_no"] for row in before]
        assert [row["entry_type"] for row in after] == [row["entry_type"] for row in before]
