"""Cross-cutting layers: the two optimistic-concurrency guards on a block, and the
risk score that clamps and escalates inside the same incident request.
"""

from test_helpers import (
    COMPLIANCE,
    COORDINATOR,
    assemble_block,
    block_terms_payload,
    carve_sub_block,
    carve_sub_block_payload,
    import_attendee,
    read_block,
    record_incident,
    record_rogue_vendor,
    register_event,
    register_hotel,
    request_block_changes,
    setup_contracted_block,
    submit_terms,
    validate_error,
    validate_success,
)


class TestStaleTermsSubmission:
    def test_resubmitting_against_the_pre_bounce_version_is_refused(self, api):
        """PRD §2.8: "A terms submission — `POST /housing/hotel-blocks/{id}/terms` —
        requires a non-optional `expected_hotel_block_version` field in its payload,
        carrying the client's last observed `version` of the target `HotelBlock`. If
        that value does not equal the block's current `version`, the submission is
        rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412)."
        PRD §3.2: "Submitting terms advances the block `DRAFT → TERMS_SUBMITTED`, and
        resubmitting after the hotel pushes back advances it `CHANGES_REQUESTED →
        TERMS_SUBMITTED`; both are coordinator actions and both are protected by the
        stale-block check of §2.8."
        PRD §3.2: "A submission overwrites `negotiated_nightly_rate_cents`,
        `commission_pct`, `rebate_per_room_night_cents`, `cutoff_date` and
        `reduction_rights_pct` wholesale from the payload — there is no partial merge —
        increases `revision_round` by one, and bumps the block's `version`."

        Design: Corner/cross-cutting complexity layers/stale_block_version_on_terms_submission_rejected
        """
        event = register_event()
        hotel = register_hotel()
        draft = assemble_block(event["id"], hotel["id"])
        submitted = submit_terms(draft)
        assert submitted["revision_round"] == 1

        bounced = request_block_changes(draft["id"], hotel["id"])
        assert bounced["status"] == "CHANGES_REQUESTED"
        assert bounced["version"] > submitted["version"]

        stale = api.submit_block_terms(
            draft["id"],
            block_terms_payload(
                submitted["version"], negotiated_nightly_rate_cents=20900
            ),
            COORDINATOR,
        )
        validate_error(stale, "ERR_STALE_BLOCK_VERSION", 412)

        untouched = read_block(draft["id"])
        assert untouched["status"] == "CHANGES_REQUESTED"
        assert untouched["version"] == bounced["version"]
        assert untouched["revision_round"] == 1
        assert untouched["negotiated_nightly_rate_cents"] == 21900

        refreshed = submit_terms(untouched, negotiated_nightly_rate_cents=20900)
        assert refreshed["status"] == "TERMS_SUBMITTED"
        assert refreshed["revision_round"] == 2
        assert refreshed["negotiated_nightly_rate_cents"] == 20900


class TestStaleSubBlockCarve:
    def test_a_carve_sized_against_the_pre_carve_inventory_is_refused(self, api):
        """PRD §2.8: "A sub-block carve — `POST
        /housing/hotel-blocks/{id}/sub-blocks` — likewise requires a non-optional
        `expected_hotel_block_version` carrying the client's last observed `version` of
        the parent `HotelBlock`, and a mismatch against the block's current `version`
        is rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412)."
        PRD §2.8: "Carving is additive and would legitimately succeed from the same
        block state, so the stale-version check is the only thing that stops a carve
        sized against an `unassigned_rooms_per_night` figure that has since moved."
        PRD §3.3: "Every carve is stamped with a `carve_seq` drawn from a single
        monotonic one-based global counter"

        Design: Corner/cross-cutting complexity layers/stale_block_version_on_sub_block_carve_rejected
        """
        ctx = setup_contracted_block()
        block_id = ctx["block"]["id"]
        pre_carve_version = ctx["block"]["version"]

        general = carve_sub_block(block_id, "GENERAL", 6)
        assert general["carve_seq"] == 1
        post_carve = read_block(block_id)
        assert post_carve["unassigned_rooms_per_night"] == 4
        assert post_carve["version"] > pre_carve_version

        stale = api.carve_sub_block(
            block_id,
            carve_sub_block_payload(
                "STAFF", 3, pre_carve_version, eligibility_code="STAFF-2026"
            ),
            COORDINATOR,
        )
        validate_error(stale, "ERR_STALE_BLOCK_VERSION", 412)

        after_refusal = read_block(block_id)
        assert after_refusal["version"] == post_carve["version"]
        assert after_refusal["unassigned_rooms_per_night"] == 4, (
            "the refused carve must not spend the 4 rooms that would have covered it"
        )

        refreshed = carve_sub_block(
            block_id, "STAFF", 3, eligibility_code="STAFF-2026"
        )
        assert refreshed["approval_status"] == "PENDING_APPROVAL"
        assert refreshed["carve_seq"] == 2
        assert read_block(block_id)["unassigned_rooms_per_night"] == 1


class TestRiskScoreClampAndEscalation:
    def test_the_second_incident_clamps_the_score_and_opens_the_review(self, api):
        """PRD §3.8: "The score starts from a base of 10, adds 25 for each counted
        incident, adds 15 for each distinct `contact_channel` appearing among the
        counted incidents, and adds a further 20 if any counted incident has
        `solicited_payment` true — that bonus is awarded once, not per incident. The
        result is clamped to the range 0 through 100 inclusive and stored as
        `risk_score`."
        PRD §3.8: "The moment a newly recorded incident pushes `risk_score` to 60 or
        above while the vendor is still in `REPORTED`, the vendor transitions
        `REPORTED → UNDER_REVIEW` inside that same request and its `version` is
        bumped."
        PRD §3.8: "`verified_incident_count` is the number of counted incidents."

        Design: Corner/cross-cutting complexity layers/vendor_risk_score_crosses_review_threshold_and_clamps
        """
        event = register_event()
        first_guest = import_attendee(event["id"], index=1)
        second_guest = import_attendee(event["id"], index=2)
        vendor = record_rogue_vendor(event["id"])

        record_incident(
            vendor["id"],
            first_guest["id"],
            contact_channel="EMAIL",
            occurred_at="2026-07-20T10:00:00Z",
            solicited_payment=False,
        )
        # 10 + 25 + 15 == 50: one channel, no solicitation, still below 60.
        midway = validate_success(api.get_rogue_vendor(vendor["id"], COMPLIANCE))
        assert midway["risk_score"] == 50
        assert midway["status"] == "REPORTED"

        record_incident(
            vendor["id"],
            second_guest["id"],
            contact_channel="PHONE",
            occurred_at="2026-07-22T09:30:00Z",
            solicited_payment=True,
        )

        after = validate_success(api.get_rogue_vendor(vendor["id"], COMPLIANCE))
        # Raw 10 + 50 + 30 + 20 == 110, clamped to the ceiling.
        assert after["risk_score"] == 100
        assert after["status"] == "UNDER_REVIEW"
        assert after["verified_incident_count"] == 2
        assert after["warning_issued_count"] == 0
        assert after["version"] > midway["version"]

        # Escalation alone warns nobody: that is the confirmation cascade's job.
        for guest in (first_guest, second_guest):
            row = validate_success(api.get_attendee(guest["id"], COORDINATOR))
            assert row["warning_count"] == 0
            assert row["housing_risk_flag"] is False
