"""Requests that break two independent rules at once.  Each pair is exercised
twice: once with both rules live, so the higher rung's error is the answer, and
once with the higher rung satisfied, so the lower rung's error surfaces and the
suppressed rule is shown to have been genuinely live all along.
"""

from test_helpers import (
    NO_PSYCH_SCREENING,
    TEST_USERS,
    ApiErrorId,
    assert_money,
    get_production,
    setup_cleared_applicant,
    setup_docusoap_production,
    setup_executed_agreement,
    setup_location,
    setup_minor_protection,
    setup_open_call,
    setup_production,
    setup_published_casting_call,
    setup_shoot_block,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["production_admin_headers"]
CD = TEST_USERS["casting_director_headers"]
BA1 = TEST_USERS["business_affairs_headers"]

HARBOUR_LIVES = {
    "format_type": "DOCUSOAP",
    "jurisdiction_code": "CA",
    "episode_order": 4,
    "stipend_pool_cents": 10_000_000,
    "welfare_budget_cents": 10_000_000,
    "minor_participant_cap": 0,
}

TEEN_TRIALS = {
    "format_type": "COMPETITION_HIGH_STRESS",
    "jurisdiction_code": "CA",
    "season_number": 2,
    "episode_order": 10,
    "stipend_pool_cents": 50_000_000,
    "welfare_budget_cents": 10_000_000,
    "minor_participant_cap": 2,
}


class TestRestrictedPostureBeatsVenueCapacity:
    """A publish request that is both posture-blocked (rung 12, a state rule)
    and over venue capacity (rung 43, a fiscal rule)."""

    def _two_productions_sharing_a_venue(self, restrict_the_publisher: bool):
        """Venue C hosts a live 400-seat open call for one production, while a
        second production holds a 300-seat draft whose window overlaps it."""
        venue = setup_location(
            name="Venue C", capacity=500, filming_permit_number="PRM-3003"
        )
        neighbour = setup_docusoap_production(
            title="Harbour Lives Z", season_number=9, **HARBOUR_LIVES
        )
        setup_open_call(
            neighbour["id"],
            venue["id"],
            min_age=18,
            max_age=60,
            exclusivity_window_days=0,
            open_call_window_start_utc="2026-08-05T00:00:00Z",
            open_call_window_end_utc="2026-08-15T00:00:00Z",
            expected_attendance=400,
        )

        publisher = setup_docusoap_production(
            title="Harbour Lives D", season_number=2, **HARBOUR_LIVES
        )
        draft_call = setup_open_call(
            publisher["id"],
            venue["id"],
            publish=False,
            min_age=18,
            max_age=60,
            exclusivity_window_days=0,
            open_call_window_start_utc="2026-08-10T00:00:00Z",
            open_call_window_end_utc="2026-08-20T00:00:00Z",
            expected_attendance=300,
        )
        referral_call = setup_published_casting_call(
            publisher["id"], min_age=18, max_age=60, exclusivity_window_days=0
        )

        if restrict_the_publisher:
            applicant = setup_cleared_applicant(
                referral_call["id"],
                items=NO_PSYCH_SCREENING,
                legal_name="Nia Doyle",
                date_of_birth="1988-12-01",
            )
            agreement = setup_executed_agreement(
                applicant["id"],
                publisher["id"],
                exclusivity_window_days=0,
                confidentiality_tier="STANDARD",
                depiction_rights_scope="FULL",
                stipend_structure="PER_EPISODE",
                base_stipend_cents=2_250_000,
                episodes_committed=4,
                press_appearance_obligation_count=0,
                reunion_obligation=False,
            )
            assert_money(
                agreement["total_stipend_commitment_cents"], 9_000_000, "final stipend"
            )
        return venue, publisher, draft_call

    def test_the_state_rung_answers_and_the_capacity_rung_is_suppressed(self, api):
        """PRD §2.6: "The ladder below is exhaustive and is evaluated strictly
        top to bottom."
        PRD §2.6: "The owning production's `casting_posture` is not `RESTRICTED`
        on casting-call publish, and not `RESTRICTED` on applicant intake when
        the receiving call's `channel` is `OPEN_CALL`, otherwise
        `ERR_CASTING_RESTRICTED` (409)."
        PRD §2.6: "On casting-call publish, the venue's aggregate expected
        attendance stays within capacity, otherwise
        `ERR_VENUE_CAPACITY_EXCEEDED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/restricted_posture_beats_venue_capacity_on_publish
        """
        _venue, publisher, draft_call = self._two_productions_sharing_a_venue(
            restrict_the_publisher=True
        )
        restricted = get_production(publisher["id"])
        assert restricted["casting_posture"] == "RESTRICTED"

        validate_error(
            api.publish_casting_call(draft_call["id"], CD),
            ApiErrorId.ERR_CASTING_RESTRICTED.value,
            409,
        )

        # Nothing about the rejected publish took effect.
        unchanged = validate_success(api.get_casting_call(draft_call["id"], CD))
        assert unchanged["status"] == "DRAFT"
        assert unchanged["published_at"] is None
        # The suppressed rung was live too: the venue holds 500 seats and the
        # 400 already published plus this call's 300 would have been 700.
        published, _meta = validate_paginated(
            api.list_casting_calls(CD, {"status": "PUBLISHED", "channel": "OPEN_CALL"})
        )
        assert sum(row["expected_attendance"] for row in published) == 400

    def test_clearing_the_state_rung_lets_the_capacity_rung_answer(self, api):
        """PRD §2.6: "Because most operations in this API are guarded by several
        independent rules at once, the order in which those rules are evaluated
        is part of the contract: the first rule that fails determines the
        response, and no later rule is evaluated. A client that fixes the
        reported problem and retries may then encounter the next rule down the
        ladder."
        PRD §3.2: "The venue capacity check then runs: the expected attendances
        of every other casting call at the same venue that is already
        `PUBLISHED`, has channel `OPEN_CALL`, and whose inclusive intake window
        intersects this one, are summed together with this call's own
        `expected_attendance`, and if that aggregate exceeds the venue's
        `capacity` the publication is refused with
        `ERR_VENUE_CAPACITY_EXCEEDED`."
        PRD §3.2: "Two inclusive windows intersect when neither one's start
        falls after the other's end."

        Design: Difficulty/priority_pair_validation_conflict/restricted_posture_beats_venue_capacity_on_publish
        """
        _venue, publisher, draft_call = self._two_productions_sharing_a_venue(
            restrict_the_publisher=False
        )
        assert get_production(publisher["id"])["casting_posture"] == "OPEN", (
            "with no executed agreement the publisher clears rung 12"
        )

        validate_error(
            api.publish_casting_call(draft_call["id"], CD),
            ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value,
            409,
        )
        still_draft = validate_success(api.get_casting_call(draft_call["id"], CD))
        assert still_draft["status"] == "DRAFT"
        assert still_draft["published_at"] is None


class TestExpiredWorkPermitBeatsLocationBlockConflict:
    """A shoot-block schedule that both calls a minor whose permit has lapsed
    (rung 26, a safety rule) and overlaps a buffered block at the same venue
    (rung 42, a temporal rule)."""

    def _minor_and_an_occupied_stage(self, permit_expires_on: str):
        """One executed minor agreement plus one SCHEDULED block whose buffered
        occupancy runs to 11:00Z on 2026-10-05."""
        production = setup_production(title="Teen Trials S2", **TEEN_TRIALS)
        stage = setup_location(
            name="Stage A", capacity=500, filming_permit_number="PRM-1001"
        )
        call = setup_published_casting_call(
            production["id"], min_age=13, max_age=45, exclusivity_window_days=0
        )
        applicant = setup_cleared_applicant(
            call["id"],
            minor=True,
            legal_name="Hana Kim",
            date_of_birth="2011-05-20",
            guardian_name="Iris Kim",
        )
        packet = setup_minor_protection(
            applicant["id"],
            work_permit_number="CA-WP-88001",
            permit_expires_on=permit_expires_on,
            education_hours_scheduled_weekly=15,
            trust_deposit_pct=0.15,
        )
        assert packet["status"] == "COMPLETE"

        agreement = setup_executed_agreement(applicant["id"], production["id"])
        assert_money(
            agreement["total_stipend_commitment_cents"], 220_000, "final stipend"
        )

        # No epoch sweep is run, so the packet keeps its COMPLETE status and no
        # welfare hold exists even once the clock has passed the permit date.
        set_clock("2026-10-05T06:00:00Z")

        occupant = setup_shoot_block(
            production["id"],
            stage["id"],
            block_kind="STUDIO",
            start_utc="2026-10-05T08:00:00Z",
            end_utc="2026-10-05T10:00:00Z",
            participant_agreement_ids=[],
            expected_crowd_headcount=0,
            onset_minor_hours=0,
        )
        assert occupant["status"] == "SCHEDULED"
        return production, stage, packet, agreement, occupant

    def _colliding_payload(self, production_id, location_id, agreement_id):
        return {
            "production_id": production_id,
            "location_id": location_id,
            "block_kind": "STUDIO",
            "start_utc": "2026-10-05T09:00:00Z",
            "end_utc": "2026-10-05T11:00:00Z",
            "participant_agreement_ids": [agreement_id],
            "expected_crowd_headcount": 0,
            "onset_minor_hours": 2.0,
        }

    def test_the_safety_rung_answers_and_the_temporal_rung_is_suppressed(self, api):
        """PRD §2.6: "Minor work permits are unexpired: on agreement send for a
        minor applicant, and on shoot-block scheduling for every minor called to
        the block, `permit_expires_on` is strictly after the logical clock's
        date, otherwise `ERR_WORK_PERMIT_EXPIRED` (422)."
        PRD §2.6: "On shoot-block scheduling, the block does not collide with
        another block at the same venue, otherwise
        `ERR_LOCATION_BLOCK_CONFLICT` (409)."
        PRD §3.7: "The sweep is the only mechanism that applies expiry, lapse
        and breach; moving the logical clock alone changes nothing."

        Design: Difficulty/priority_pair_validation_conflict/expired_work_permit_beats_location_block_conflict
        """
        production, stage, packet, agreement, occupant = self._minor_and_an_occupied_stage(
            "2026-08-20"
        )

        validate_error(
            api.create_shoot_block(
                self._colliding_payload(production["id"], stage["id"], agreement["id"]),
                PA,
            ),
            ApiErrorId.ERR_WORK_PERMIT_EXPIRED.value,
            422,
        )

        # The packet is untouched by the refusal and still reads COMPLETE.
        packets, _pmeta = validate_paginated(
            api.list_minor_protections(packet["applicant_id"], PA)
        )
        assert [row["status"] for row in packets] == ["COMPLETE"]
        rows, meta = validate_paginated(
            api.list_shoot_blocks(PA, {"production_id": production["id"]})
        )
        assert meta["total_count"] == 1, "no second block was created"
        assert rows[0]["id"] == occupant["id"]
        assert rows[0]["status"] == "SCHEDULED"

    def test_an_unexpired_permit_lets_the_temporal_rung_answer(self, api):
        """PRD §2.6: "the first rule that fails determines the response, and no
        later rule is evaluated."
        PRD §3.8: "And the block must not collide with another block at the same
        venue: each block occupies the half-open interval that begins at its
        `start_utc` and ends at its `end_utc` extended by the venue's
        `turnaround_buffer_minutes`, and if that extended interval intersects the
        extended interval of any other block at the same location whose `status`
        is `SCHEDULED` or `ROLLING`, the scheduling is refused with
        `ERR_LOCATION_BLOCK_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/expired_work_permit_beats_location_block_conflict
        """
        production, stage, packet, agreement, occupant = self._minor_and_an_occupied_stage(
            "2027-03-31"
        )

        # The permit now outlives the clock, so rung 26 passes and the buffered
        # occupancy [08:00Z, 11:00Z) is what refuses the [09:00Z, 11:00Z) ask.
        validate_error(
            api.create_shoot_block(
                self._colliding_payload(production["id"], stage["id"], agreement["id"]),
                PA,
            ),
            ApiErrorId.ERR_LOCATION_BLOCK_CONFLICT.value,
            409,
        )
        assert packet["permit_expires_on"] == "2027-03-31"
        _rows, meta = validate_paginated(
            api.list_shoot_blocks(PA, {"production_id": production["id"]})
        )
        assert meta["total_count"] == 1
        assert (
            validate_success(api.get_shoot_block(occupant["id"], PA))["status"]
            == "SCHEDULED"
        )
