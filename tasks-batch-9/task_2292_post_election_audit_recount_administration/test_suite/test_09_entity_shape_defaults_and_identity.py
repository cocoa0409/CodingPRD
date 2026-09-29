"""Entity shapes: declared fields, server-computed fields, defaults and identity."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    constants,
    factories,
    fixtures,
    is_valid_uuid,
    make_custody_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["elections_director_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]
CUSTODY_OFFICER = TEST_USERS["custody_officer_headers"]

CANVASS_DAY = constants.TEST_DEFAULTS["CLOCK_CANVASS_DAY"]
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000001"


class TestElectionRegistrationShape:
    """The four supplied values come back beside every field the server derives."""

    def test_a_new_election_opens_on_track_with_both_windows_derived(self):
        """PRD §3.1: "A newly registered election opens in `status` `OPEN` with
        `timeline_status` `ON_TRACK`, `certification_risk_flag` false, `open_audit_count` and
        `open_recount_count` both zero, `certified_at` null,
        `effective_certification_deadline_at` equal to `certification_deadline_at` (no
        extension has been granted yet), and `contest_window_ends_at` set ten days after that
        effective deadline."

        Design: Corner/entities/election_create_returns_declared_fields_and_starts_open
        """
        fixtures.set_clock(CANVASS_DAY)

        response = api_client.create_election(
            factories.create_election_payload(), DIRECTOR
        )

        election = validate_success(response, 201)
        assertions.assert_election(election)
        assert election["jurisdiction_code"] == "ST-01"
        assert election["election_name"] == "2026 General Election"
        assert election["election_date"] == "2026-11-03"
        assertions.assert_same_instant(
            election["certification_deadline_at"],
            "2026-11-24T17:00:00Z",
            "certification_deadline_at",
        )
        assert election["status"] == "OPEN"
        assert election["timeline_status"] == "ON_TRACK"
        assert election["certification_risk_flag"] is False
        assert election["open_audit_count"] == 0
        assert election["open_recount_count"] == 0
        assert election["certified_at"] is None
        assertions.assert_same_instant(
            election["effective_certification_deadline_at"],
            "2026-11-24T17:00:00Z",
            "effective_certification_deadline_at",
        )
        assertions.assert_same_instant(
            election["contest_window_ends_at"],
            "2026-12-04T17:00:00Z",
            "contest_window_ends_at",
        )
        assert election["version"] == 1
        assert is_valid_uuid(election["id"])


class TestContestRetrievalShape:
    """A canvassed contest round-trips its configuration and its five derivations."""

    def test_a_canvassed_contest_returns_its_inputs_and_its_derived_margin(self):
        """PRD §3.1: "`margin_votes` becomes the winner's votes minus the runner-up's votes,
        and `margin_pct` becomes `margin_votes` divided by `ballots_cast`, multiplied by one
        hundred, and rounded half up to four decimal places." §3.1: "The same step sets
        `recount_request_deadline_at` to five days after `canvassed_at`."

        Design: Corner/entities/contest_get_returns_stored_values_and_canvass_derivations
        """
        scenario = fixtures.setup_canvassed_contest()

        response = api_client.get_contest(scenario["contest"]["id"], AUDIT_MANAGER)

        contest = validate_success(response)
        assertions.assert_contest(contest)
        assert contest["contest_label"] == "C1"
        assert contest["office_name"] == "State Auditor"
        assert contest["contest_type"] == "CANDIDATE"
        assert contest["candidate_names"] == ["ALVAREZ", "BRENNAN"]
        assert contest["ballots_cast"] == 6000
        assert contest["cvr_available"] is True
        assert contest["reported_votes"] == {"ALVAREZ": 3150, "BRENNAN": 2850}
        assert contest["winner_name"] == "ALVAREZ"
        assert contest["runner_up_name"] == "BRENNAN"
        assert contest["margin_votes"] == 300
        assert contest["margin_pct"] == pytest.approx(5.0000, abs=0.00005)
        assert contest["automatic_recount_required"] is False
        assertions.assert_same_instant(
            contest["recount_request_deadline_at"],
            "2026-11-10T09:00:00Z",
            "recount_request_deadline_at",
        )
        assert contest["status"] == "CANVASSED"
        assertions.assert_same_instant(
            contest["canvassed_at"], CANVASS_DAY, "canvassed_at"
        )
        assert contest["open_recount_count"] == 0
        assert contest["version"] == 2


class TestBallotBatchListing:
    """Six batches page in label order, with total_count counting the filtered set."""

    def test_two_pages_of_two_report_the_same_total_count_in_label_order(self):
        """PRD §2.3: "`total_count` is the number of rows matching the filters before the
        page window is applied and `has_more` states whether any matching row remains beyond
        the current window." §2.3: "ballot batches, ordered by `batch_label` ascending".

        Design: Corner/entities/ballot_batch_list_paginates_in_batch_label_order
        """
        scenario = fixtures.setup_canvassed_contest()
        contest_id = scenario["contest"]["id"]

        first_rows, first_meta = validate_paginated(
            api_client.list_ballot_batches(
                CUSTODY_OFFICER,
                params={"contest_id": contest_id, "limit": 2, "offset": 0},
            )
        )
        last_rows, last_meta = validate_paginated(
            api_client.list_ballot_batches(
                CUSTODY_OFFICER,
                params={"contest_id": contest_id, "limit": 2, "offset": 4},
            )
        )

        assert first_meta["total_count"] == 6
        assert first_meta["has_more"] is True
        assert [row["batch_label"] for row in first_rows] == ["B-001", "B-002"]
        assert last_meta["total_count"] == 6
        assert last_meta["has_more"] is False
        assert [row["batch_label"] for row in last_rows] == ["B-005", "B-006"]
        for row in first_rows + last_rows:
            assertions.assert_ballot_batch(row)
            assert row["custody_status"] == "SEALED"
            assert row["ballot_count"] == 1000


class TestUnknownAuditId:
    """The existence check names one 404 per entity, not a generic one."""

    def test_an_unresolvable_audit_id_returns_the_audit_specific_not_found(self):
        """PRD §2.9: "Every path identifier resolves to a stored row — otherwise the matching
        404 from the vocabulary in §2.5." §2.5 names `ERR_AUDIT_NOT_FOUND` in that vocabulary.

        Design: Corner/entities/audit_get_with_unknown_id_returns_audit_not_found
        """
        fixtures.set_clock(CANVASS_DAY)

        response = api_client.get_audit(UNKNOWN_UUID, AUDIT_MANAGER)

        validate_error(response, ApiErrorId.ERR_AUDIT_NOT_FOUND.value, 404)
        _rows, meta = validate_paginated(
            api_client.list_audits(AUDIT_MANAGER, params={"limit": 100})
        )
        assert meta["total_count"] == 0


class TestElectionRequiredFields:
    """The statutory deadline has no default, so omitting it is a shape violation."""

    def test_an_election_without_a_certification_deadline_is_refused(self):
        """PRD §2.9: "Request shape: the body parses, required fields are present, and every
        type, enum member, numeric range and string length is respected ... otherwise
        `ERR_VALIDATION`." §3.1: "Registration supplies four values: a `jurisdiction_code` ...
        an `election_date` given as an ISO calendar date with no time component, and the
        statutory `certification_deadline_at`."

        Design: Corner/entities/election_create_missing_certification_deadline_is_rejected
        """
        fixtures.set_clock(CANVASS_DAY)
        payload = factories.create_election_payload()
        del payload["certification_deadline_at"]

        response = api_client.create_election(payload, DIRECTOR)

        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)
        _rows, meta = validate_paginated(
            api_client.list_elections(DIRECTOR, params={"limit": 10})
        )
        assert meta["total_count"] == 0


class TestContestDefaults:
    """Omitted optional fields take their declared defaults, not a refusal."""

    def test_a_contest_created_without_cvr_starts_pending_with_null_derivations(self):
        """PRD §3.1: "an optional `cvr_available` flag that defaults to false ... A new
        contest begins in `status` `PENDING_CANVASS` with `reported_votes`, `winner_name`,
        `runner_up_name`, `margin_votes`, `margin_pct`, `recount_request_deadline_at` and
        `canvassed_at` all null, `automatic_recount_required` false and `open_recount_count`
        zero."

        Design: Corner/entities/contest_create_applies_declared_defaults
        """
        fixtures.set_clock(CANVASS_DAY)
        election = fixtures.create_election()
        payload = factories.create_contest_payload(election["id"])
        del payload["cvr_available"]

        response = api_client.create_contest(payload, DIRECTOR)

        contest = validate_success(response, 201)
        assertions.assert_contest(contest)
        assert contest["cvr_available"] is False
        assert contest["reported_votes"] is None
        assert contest["status"] == "PENDING_CANVASS"
        assert contest["canvassed_at"] is None
        assert contest["winner_name"] is None
        assert contest["runner_up_name"] is None
        assert contest["margin_votes"] is None
        assert contest["margin_pct"] is None
        assert contest["automatic_recount_required"] is False
        assert contest["recount_request_deadline_at"] is None
        assert contest["open_recount_count"] == 0
        assert contest["version"] == 1
        assert fixtures.read_election(election["id"])["status"] == "OPEN"


class TestAuditComputedFields:
    """The variant and the preview sample size are both server-derived at planning."""

    def test_three_methodologies_yield_their_own_variant_and_preview_size(self):
        """PRD §3.3: "Planning derives `measure_variant` from the methodology and never
        accepts it as input: risk-limiting and fixed-percentage audits take the variant
        `NET_MARGIN_SHIFT`, while comparison audits take `MAX_RELATIVE_OVERSTATEMENT`." §3.3:
        "When the contest is already `CANVASSED`, `planned_sample_size` is derived immediately
        as a preview".

        Design: Corner/entities/audit_measure_variant_and_sample_size_are_computed_from_audit_type
        """
        scenario = fixtures.setup_canvassed_contest()
        contest_id = scenario["contest"]["id"]

        risk_limiting = validate_success(
            api_client.create_audit(
                factories.create_audit_payload(contest_id), AUDIT_MANAGER
            ),
            201,
        )
        comparison = validate_success(
            api_client.create_audit(
                factories.create_audit_payload(
                    contest_id, audit_type="COMPARISON", prior_error_rate=0.10
                ),
                AUDIT_MANAGER,
            ),
            201,
        )
        fixed = validate_success(
            api_client.create_audit(
                factories.create_audit_payload(
                    contest_id,
                    audit_type="FIXED_PERCENTAGE",
                    risk_limit_alpha=None,
                    fixed_percentage_pct=5,
                ),
                AUDIT_MANAGER,
            ),
            201,
        )

        assertions.assert_audit(risk_limiting)
        assert risk_limiting["measure_variant"] == "NET_MARGIN_SHIFT"
        assert risk_limiting["planned_sample_size"] == 3
        assert comparison["measure_variant"] == "MAX_RELATIVE_OVERSTATEMENT"
        assert comparison["planned_sample_size"] == 2
        assert fixed["measure_variant"] == "NET_MARGIN_SHIFT"
        assert fixed["planned_sample_size"] == 2
        assert risk_limiting["status"] == "PLANNED"
        assert risk_limiting["escalation_level"] == 0
        assert risk_limiting["discrepancy_measure"] == pytest.approx(0.0, abs=0.00005)
        assert risk_limiting["random_seed"] is None
        assert risk_limiting["seed_published_at"] is None
        assert risk_limiting["sample_size_stale"] is False
        assert risk_limiting["fixed_percentage_pct"] is None
        assert fixed["risk_limit_alpha"] is None
        assert fixtures.read_election(scenario["election"]["id"])["open_audit_count"] == 3


class TestCustodyEventSystemFields:
    """Nothing about a custody event comes from the client."""

    def test_three_events_land_as_sequence_one_two_and_three_on_the_drawn_batch(self):
        """PRD §2.4: "the custody log is ordered by its monotonic per-batch `sequence_no`,
        which starts at 1 for the first event appended to a batch and increases by one for
        each subsequent event on that same batch." §2.10: "each row records the
        `ballot_batch_id` whose custody changed, an `event_type` ... the `actor_user_id` and
        `actor_role` copied from the triggering request's headers, the `seal_number_before`
        and `seal_number_after` values that bracket the event, the `occurred_at` instant read
        from the logical clock, and an optional `note`".

        Design: Corner/entities/custody_event_identity_and_sequence_are_server_assigned
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        drawn = scenario["audit_batches"][0]
        physical = fixtures.read_batch(drawn["ballot_batch_id"])
        validate_success(
            api_client.retrieve_audit_batch(
                drawn["id"],
                factories.retrieve_audit_batch_payload(
                    physical["version"],
                    physical["current_seal_number"],
                    note="Two-officer escort",
                ),
                make_custody_officer_headers("u-custody-1"),
            )
        )

        rows, meta = validate_paginated(
            api_client.list_ballot_batch_custody_events(
                physical["id"], CUSTODY_OFFICER, params={"limit": 10}
            )
        )

        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert [row["event_type"] for row in rows] == [
            "INTAKE",
            "AUTHORIZED",
            "CHECK_OUT",
        ]
        assertions.assert_custody_log_ordered(rows)
        for row in rows:
            assertions.assert_custody_event(row)
            assertions.assert_same_instant(row["occurred_at"], CANVASS_DAY, "occurred_at")
        check_out = rows[2]
        assert check_out["seal_number_before"] == physical["current_seal_number"]
        assert check_out["seal_number_after"] is None
        assert check_out["note"] == "Two-officer escort"
        assert check_out["actor_user_id"] == "u-custody-1"
        assert check_out["actor_role"] == "CustodyOfficer"
        assert len({row["id"] for row in rows}) == 3


class TestInputTypeConstraints:
    """Enum membership and numeric floors are all refused by the same shape gate."""

    def test_an_unknown_enum_member_and_a_zero_ballot_count_are_all_refused(self):
        """PRD §2.9: "This is pure shape validation with no database read: an unknown enum
        member, a negative ballot count, a non-integer cent amount, a `random_seed` that is
        not exactly ten digits, `limit=0` and `limit=101` all land here."

        Design: Corner/entities/enum_and_range_constraints_are_enforced_on_input_fields
        """
        scenario = fixtures.setup_canvassed_contest()
        contest_id = scenario["contest"]["id"]
        election_id = scenario["election"]["id"]

        bad_audit_type = api_client.create_audit(
            factories.create_audit_payload(contest_id, audit_type="PARTIAL_HAND_COUNT"),
            AUDIT_MANAGER,
        )
        bad_party = api_client.create_observer_credential(
            factories.create_observer_credential_payload(
                election_id, party_affiliation="GREEN"
            ),
            DIRECTOR,
        )
        bad_ballots_cast = api_client.create_contest(
            factories.create_contest_payload(
                election_id,
                contest_label="C2",
                office_name="State Treasurer",
                candidate_names=["CHEN", "DAVIS"],
                ballots_cast=0,
            ),
            DIRECTOR,
        )

        validate_error(bad_audit_type, ApiErrorId.ERR_VALIDATION.value, 422)
        validate_error(bad_party, ApiErrorId.ERR_VALIDATION.value, 422)
        validate_error(bad_ballots_cast, ApiErrorId.ERR_VALIDATION.value, 422)
        _audits, audit_meta = validate_paginated(
            api_client.list_audits(
                AUDIT_MANAGER, params={"contest_id": contest_id, "limit": 100}
            )
        )
        assert audit_meta["total_count"] == 0
        _credentials, credential_meta = validate_paginated(
            api_client.list_observer_credentials(
                DIRECTOR, params={"election_id": election_id, "limit": 100}
            )
        )
        assert credential_meta["total_count"] == 0
        _contests, contest_meta = validate_paginated(
            api_client.list_contests(
                DIRECTOR, params={"election_id": election_id, "limit": 100}
            )
        )
        assert contest_meta["total_count"] == 1
        assert fixtures.read_election(election_id)["open_audit_count"] == 0


class TestCustodyEventImmutability:
    """The log carries no version dimension and can only grow."""

    def test_an_intake_row_carries_no_updated_at_and_no_version(self):
        """PRD §2.4: "`CustodyEvent` rows are append-only and are never modified after they
        are written, so they carry only `id` and `created_at`: both `updated_at` and `version`
        are absent from a custody event." §2.10: "There is no endpoint that creates, edits or
        deletes a custody event; the log can only grow."

        Design: Corner/entities/custody_event_is_append_only_with_no_version_dimension
        """
        scenario = fixtures.setup_election_with_contest_and_batches()
        first_batch = fixtures.batch_by_label(scenario["batches"], "B-001")

        rows, meta = validate_paginated(
            api_client.list_custody_events(
                CUSTODY_OFFICER,
                params={"ballot_batch_id": first_batch["id"], "limit": 10},
            )
        )
        retrieved = validate_success(
            api_client.get_custody_event(rows[0]["id"], CUSTODY_OFFICER)
        )

        assert meta["total_count"] == 1
        assert rows[0]["sequence_no"] == 1
        assertions.assert_custody_event(retrieved)
        assert retrieved["event_type"] == "INTAKE"
        assert retrieved["ballot_batch_id"] == first_batch["id"]
        assert retrieved["seal_number_before"] is None
        assert retrieved["seal_number_after"] == "SEAL-001"
        assert "updated_at" not in retrieved
        assert "version" not in retrieved

    def test_the_cross_batch_log_orders_by_batch_then_sequence(self):
        """PRD §2.3: "the cross-batch custody event list, ordered by `ballot_batch_id`
        ascending and then by `sequence_no` ascending within each batch."

        Design: Corner/entities/custody_event_is_append_only_with_no_version_dimension
        """
        fixtures.setup_election_with_contest_and_batches()

        rows, meta = validate_paginated(
            api_client.list_custody_events(CUSTODY_OFFICER, params={"limit": 100})
        )

        assert meta["total_count"] == 6
        keys = [(row["ballot_batch_id"], row["sequence_no"]) for row in rows]
        assert keys == sorted(keys)
        assert all(row["event_type"] == "INTAKE" for row in rows)


class TestUnknownBodyForeignKey:
    """A body foreign key that resolves to nothing fails with the parent's own 404."""

    def test_a_contest_naming_an_unknown_election_is_refused(self):
        """PRD §2.9: "Every foreign key supplied in the request body resolves to a stored row
        — otherwise the matching 404. Applies to contest creation, single and bulk
        ballot-batch registration, audit planning, tally-team creation, hand-tally creation,
        ballot-interpretation referral, recount filing, corrective-action creation and
        observer credentialing."

        Design: Corner/entities/contest_create_with_unknown_election_id_returns_election_not_found
        """
        fixtures.set_clock(CANVASS_DAY)

        response = api_client.create_contest(
            factories.create_contest_payload(UNKNOWN_UUID), DIRECTOR
        )

        validate_error(response, ApiErrorId.ERR_ELECTION_NOT_FOUND.value, 404)
        _rows, meta = validate_paginated(
            api_client.list_contests(DIRECTOR, params={"limit": 100})
        )
        assert meta["total_count"] == 0


class TestFlatTopologyCoherence:
    """Two resolvable ids that belong to different elections are still incoherent."""

    def test_a_batch_pairing_one_elections_id_with_anothers_contest_is_refused(self):
        """PRD §2.9: "All referenced rows belong to the same election — otherwise
        `ERR_CROSS_ELECTION_REFERENCE`. Applies to single and bulk ballot-batch registration,
        hand-tally creation and observer credentialing: a hand tally may not pair a drawn
        batch from one election with a team from another, and a batch's `contest_id` must
        belong to its `election_id`."

        Design: Corner/entities/flat_topology_rejects_a_batch_whose_election_and_contest_disagree
        """
        fixtures.set_clock(CANVASS_DAY)
        first_election = fixtures.create_election()
        first_contest = fixtures.create_contest(first_election["id"])
        other_election = fixtures.create_election(
            jurisdiction_code="ST-09", election_name="2026 Municipal Runoff"
        )
        fixtures.create_contest(
            other_election["id"],
            contest_label="C9",
            office_name="City Comptroller",
            candidate_names=["HALE", "IRWIN"],
            ballots_cast=2000,
        )

        response = api_client.create_ballot_batch(
            factories.create_ballot_batch_payload(
                other_election["id"],
                first_contest["id"],
                batch_label="X-001",
                current_seal_number="SEAL-901",
            ),
            CUSTODY_OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_CROSS_ELECTION_REFERENCE.value, 422)
        _mine, other_meta = validate_paginated(
            api_client.list_ballot_batches(
                CUSTODY_OFFICER,
                params={"election_id": other_election["id"], "limit": 100},
            )
        )
        assert other_meta["total_count"] == 0
        _theirs, contest_meta = validate_paginated(
            api_client.list_ballot_batches(
                CUSTODY_OFFICER,
                params={"contest_id": first_contest["id"], "limit": 100},
            )
        )
        assert contest_meta["total_count"] == 0
