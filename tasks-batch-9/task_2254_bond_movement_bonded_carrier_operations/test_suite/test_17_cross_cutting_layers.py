"""Layers that cut across the whole contract: the two optimistic-concurrency
guards, and a sanction score sitting one bucket short of the transit throttle."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_deadline,
    assert_field,
    assert_money,
    assert_petition_offer,
    assert_points,
)
from test_helpers.fixtures import (
    M1_DEADLINE,
    build_broken_seal_in_transit,
    build_filed_movement,
    build_late_arrival_claim,
)


class TestStaleMovementVersion:
    """An amendment must quote the version the client has actually read."""

    def test_the_version_seen_at_filing_is_stale_once_the_movement_has_departed(
        self, client
    ):
        """Departure took the movement from version 1 to version 2, so the extension
        quoting 1 is refused outright and creates nothing; the retry quoting 2 is
        accepted and itself bumps the movement to version 3 without granting a day.

        PRD: "If that value does not equal the movement's current `version`, the submission is rejected with `ERR_STALE_MOVEMENT_VERSION` (HTTP 412)."

        PRD: "Both are submitted by the movement's own carrier against a `movement_id`, both carry a `justification_code` drawn from `CONSIGNEE_CHANGE`, `CARRIER_EQUIPMENT_FAILURE`, `PORT_CONGESTION`, and `WEATHER_DELAY`, both carry the mandatory `expected_movement_version` of §2.9, and both open at `status` `SUBMITTED` with `granted_days`, `decided_by_user_id`, `decided_at`, `decision_reason_code`, and `resulting_deadline_utc` all null."

        PRD: "The submission also increments the movement's `version`, which is precisely why the next client must re-read before submitting again."

        Design: Corner/cross_cutting_complexity_layers/stale_movement_version_blocks_the_amendment_then_the_fresh_one_passes
        """
        world = build_filed_movement(client)
        movement_id = world.movements["MAN-0001"]
        version_at_filing = world.read_movement(movement_id)["version"]
        assert version_at_filing == 1, (
            f"a freshly filed movement should stand at version 1 but stands at "
            f"{version_at_filing}"
        )
        version_after_departure = world.depart(movement_id)["version"]
        assert version_after_departure == 2, (
            f"departure is a mutation and should carry the movement to version 2 but "
            f"left it at {version_after_departure}"
        )

        validate_error(
            client.submit_amendment(
                factories.extension_payload(
                    movement_id, version_at_filing, 3, "WEATHER_DELAY"
                ),
                world.carrier,
            ),
            api_errors.ERR_STALE_MOVEMENT_VERSION,
            412,
        )

        _rows, meta = world.amendments(movement_id)
        assert meta["total_count"] == 0, (
            f"the stale submission must not be stored but the movement carries "
            f"{meta['total_count']} amendment requests"
        )
        assert_field(
            world.read_movement(movement_id), "version", 2, "movement"
        )

        accepted = validate_success(
            client.submit_amendment(
                factories.extension_payload(
                    movement_id, version_after_departure, 3, "WEATHER_DELAY"
                ),
                world.carrier,
            ),
            201,
        )
        assert_field(accepted, "status", "SUBMITTED", "amendment request")
        assert_field(accepted, "requested_days", 3, "amendment request")
        assert_field(accepted, "granted_days", None, "amendment request")
        assert_field(accepted, "resulting_deadline_utc", None, "amendment request")

        movement = world.read_movement(movement_id)
        assert_field(movement, "version", 3, "movement")
        assert_field(movement, "extension_days_granted", 0, "movement")
        assert_deadline(movement, deadline=M1_DEADLINE)


class TestStaleClaimVersion:
    """A second petition must quote the version the first petition left behind."""

    def test_a_second_petition_quoting_the_pre_petition_version_is_refused(
        self, client
    ):
        """Filing the first petition drove the claim to PETITIONED and version 2, so
        the second petition still quoting version 1 is refused and the live petition
        is neither superseded nor recomputed.

        PRD: "If that value does not equal the claim's current `version`, the filing is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412)."

        PRD: "Filing a petition opens it at `status` `SUBMITTED` and `round` 1, records `filed_by_user_id` as the filing carrier's `X-User-ID`, leaves `decided_by_user_id` and `decision_reason_code` null, drives the claim `ISSUED → PETITIONED`, increments the claim's `version`, and moves any earlier petition on the same claim still in `SUBMITTED` or `SUPPLEMENT_REQUESTED` to `SUPERSEDED` with `decision_reason_code` `SUPERSEDED_BY_NEWER_PETITION`."

        PRD: "Step three applies a round-dependent cap: fifty hundredths when the petition's `round` is 1, seventy-five hundredths when it is 2."

        PRD: "Step four computes `net_before_fee` as the claim's `assessed_amount` multiplied by one minus `mitigation_pct`, rounded half-up to two decimal places."

        PRD: "Step five selects `processing_fee` from a tier chosen on `net_before_fee` **only**: a net strictly below 2,000.00 draws a flat fee of 100.00; a net of at least 2,000.00 but strictly below 10,000.00 draws a flat fee of 250.00; a net of 10,000.00 or more draws two and a half hundredths of the net, rounded half-up to two decimal places."

        PRD: "Step six sets `offer_amount` to the lesser of the claim's `assessed_amount` and the sum of `net_before_fee` and `processing_fee`, rounded half-up to two decimal places, so an offer can never exceed the gross it mitigates."

        Design: Corner/cross_cutting_complexity_layers/stale_claim_version_blocks_a_second_petition
        """
        world, claim = build_late_arrival_claim(client)
        version_at_issue = claim["version"]

        first_petition = world.file_petition(
            claim["id"],
            ["FIRST_VIOLATION"],
            "PET-0120",
            expected_claim_version=version_at_issue,
        )

        validate_error(
            client.file_petition(
                factories.petition_payload(
                    claim["id"],
                    version_at_issue,
                    ["FIRST_VIOLATION", "CARGO_SECURED_INTACT"],
                    "PET-0121",
                ),
                world.carrier,
            ),
            api_errors.ERR_STALE_CLAIM_VERSION,
            412,
        )

        rows, meta = world.petitions(claim["id"])
        assert meta["total_count"] == 1, (
            f"the stale filing must not be stored, leaving the one live petition, but "
            f"the claim carries {meta['total_count']}"
        )
        assert rows[0]["id"] == first_petition["id"], (
            "the surviving petition should be the one that was accepted"
        )
        assert_field(rows[0], "status", "SUBMITTED", "petition")
        assert_field(rows[0], "narrative_reference", "PET-0120", "petition")
        assert_petition_offer(
            rows[0],
            mitigation_pct=0.20,
            net_before_fee=987.68,
            processing_fee=100.00,
            offer_amount=1087.68,
        )

        live_claim = world.read_claim(claim["id"])
        assert_field(live_claim, "status", "PETITIONED", "claim")
        assert_field(live_claim, "version", 2, "claim")


class TestSanctionScoreBelowTheThrottle:
    """Four points is one bucket short of the throttle, so the next filing earns
    its full window."""

    def test_four_points_leave_the_next_filing_with_the_whole_thirty_five_days(
        self, client
    ):
        """A single seal violation scores the statutory minimum and four undecayed
        points; because four is below six, the next interport IT filing still earns
        30 plus 5 days and its deadline runs a full 35 days from the filing instant.

        PRD: "The raw assessment is the greater of a statutory minimum of 1,000.00 and the per-diem rate of 250.00 multiplied by the severity multiplied by the chargeable day count, that product rounded half-up to two decimal places."

        PRD: "The type weights are 2 for `LATE_ARRIVAL`, 3 for `NO_PROOF_OF_EXPORT`, 4 for `SEAL_VIOLATION`, 4 for `UNAUTHORIZED_DIVERSION`, and 6 for `NON_ARRIVAL`."

        PRD: "A claim aged 90 days or fewer decays not at all and counts at full weight; one aged more than 90 but no more than 180 days counts at three quarters of its weight; one aged more than 180 but no more than 365 days counts at half; and one aged more than 365 days counts for nothing at all."

        PRD: "At 6.0 or above, the **transit throttle** of §3.2 halves the earned transit window on every new filing."

        PRD: "If the origin port's `region_code` differs from the destination port's `region_code`, an interport leg surcharge of 5 further days is added."

        Design: Corner/cross_cutting_complexity_layers/four_sanction_points_stay_below_the_throttle_threshold
        """
        world = build_broken_seal_in_transit(client, break_clock="2026-08-05T00:00:00Z")
        claim = world.issue_claim(
            world.movements["MAN-0001"], "SEAL_VIOLATION", "SEAL_BROKEN_IN_TRANSIT"
        )
        assert_field(claim, "overdue_days_at_issue", 0, "claim")
        assert_money(claim["assessed_amount"], 1000.00, "assessed_amount")

        carrier = world.read_carrier()
        assert_points(carrier["sanction_points"], 4.0)
        assert_field(carrier, "custodial_status", "ACTIVE", "carrier")

        next_leg = validate_success(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0090",
                    bond_id=world.bond_id,
                ),
                world.carrier,
            ),
            201,
        )
        assert_deadline(
            next_leg,
            anchor="2026-08-05T00:00:00Z",
            deadline="2026-09-09T00:00:00Z",
            transit_days_allowed=35,
        )

        assert_bond_amounts(
            world.read_bond(), obligated=1083.50, available=48916.50, status="ACTIVE"
        )
