"""Error tests: reuse cycles, vendor security obligations, allowance and seat ceilings."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_two_decimal
from test_helpers.constants import (
    CERT_NONE,
    JOB_RESERVED,
    PARTNER_APPROVED,
    PARTNER_ONBOARDING,
    SESSION_SCHEDULED,
)
from test_helpers.test_users import (
    ARTIST_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
)


class TestAssetReuseCycle:
    def test_relinking_onto_a_descendant_or_onto_itself_is_a_cycle(self, client):
        """The walk is over the whole prospective chain, so pointing a root at its own
        descendant and pointing it at itself are both refused, and the refused row is untouched.

        PRD: "A create or a repointing whose resulting chain would revisit an asset already on
        the walk is refused with `ERR_ASSET_REUSE_CYCLE`, and a chain longer than eight edges
        is refused with `ERR_VALIDATION`."
        PRD: "The discount is zero — `reuse_discount_pct` of 0.00 — in any of three cases: the
        depth is 0; the asset's **immediate** source has a `library_status` other than
        `LIBRARY_APPROVED`; or the asset's `reuse_source_stale` flag is true."

        Design: Corner/errors/asset_relink_creating_a_cycle_rejects
        """
        production = fx.open_production(
            client, title="Aurora Drift", production_code="AD01"
        )
        root = fx.create_asset(
            client,
            production["id"],
            asset_code="AD01_PROP_A",
            asset_type="PROP",
            base_complexity_points=100.00,
        )
        child = fx.create_asset(
            client,
            production["id"],
            asset_code="AD01_PROP_B",
            asset_type="PROP",
            base_complexity_points=80.00,
            derived_from_asset_id=root["id"],
        )
        assert child["reuse_depth"] == 1
        unrelated = fx.create_asset(
            client,
            production["id"],
            asset_code="AD01_PROP_C",
            asset_type="PROP",
            base_complexity_points=60.00,
        )

        validate_error(
            client.relink_asset_source(
                root["id"], f.relink_payload(child["id"]), PRODUCTION_MANAGER_HEADERS
            ),
            "ERR_ASSET_REUSE_CYCLE",
            422,
        )
        untouched = fx.read_asset(client, root["id"], ARTIST_HEADERS)
        assert untouched["derived_from_asset_id"] is None
        assert untouched["reuse_depth"] == 0
        assert_two_decimal(
            untouched["effective_complexity_points"], 100.00, "effective_complexity_points"
        )

        validate_error(
            client.relink_asset_source(
                root["id"], f.relink_payload(root["id"]), PRODUCTION_MANAGER_HEADERS
            ),
            "ERR_ASSET_REUSE_CYCLE",
            422,
        )

        relinked = validate_success(
            client.relink_asset_source(
                child["id"], f.relink_payload(unrelated["id"]), PRODUCTION_MANAGER_HEADERS
            )
        )
        assert relinked["derived_from_asset_id"] == unrelated["id"]
        assert relinked["reuse_depth"] == 1
        assert_two_decimal(relinked["reuse_discount_pct"], 0.00, "reuse_discount_pct")


class TestPartnerSecurityObligations:
    def test_an_uncertified_partner_can_never_leave_onboarding(self, client):
        """Approval is refused while the certification is NONE and the partner stays where it
        was, while a certified sibling approves and the uncertified one cannot be suspended
        either.

        PRD: "`ONBOARDING → APPROVED` requires the partner's `security_certification_level` to
        be something other than `NONE`, otherwise `ERR_SECURITY_REQUIREMENT_UNMET`; once
        approved, packages may be issued to the partner."
        PRD: "Any other requested move — for example `ONBOARDING → SUSPENDED`, or approving a
        partner that is already `APPROVED` — is refused with `ERR_PARTNER_STATE_INVALID`."

        Design: Corner/errors/partner_approval_without_certification_rejects
        """
        uncertified = fx.onboard_partner(
            client, legal_name="Sketch Loft", security_certification_level="NONE"
        )
        assert uncertified["security_certification_level"] == CERT_NONE
        assert uncertified["status"] == PARTNER_ONBOARDING
        assert uncertified["watermark_required"] is True
        assert uncertified["mfa_enforced"] is False

        certified = fx.onboard_partner(
            client, legal_name="Ink & Pixel Studios", security_certification_level="TIER1"
        )

        validate_error(
            client.set_partner_status(
                uncertified["id"], f.partner_status_payload("APPROVED"), COORDINATOR_HEADERS
            ),
            "ERR_SECURITY_REQUIREMENT_UNMET",
            422,
        )
        assert fx.read_partner(client, uncertified["id"])["status"] == PARTNER_ONBOARDING

        promoted = validate_success(
            client.set_partner_status(
                certified["id"], f.partner_status_payload("APPROVED"), COORDINATOR_HEADERS
            )
        )
        assert promoted["status"] == PARTNER_APPROVED

        validate_error(
            client.set_partner_status(
                uncertified["id"], f.partner_status_payload("SUSPENDED"), COORDINATOR_HEADERS
            ),
            "ERR_PARTNER_STATE_INVALID",
            409,
        )


class TestRenderAllowanceCeiling:
    def test_the_allowance_refuses_a_reservation_a_free_pool_would_accept(self, client):
        """A show whose render allowance is 500 cents cannot reserve an 840-cent job on an
        empty 100-core farm, the rejection consumes nothing, and a one-frame job fits.

        PRD: "The production's `render_committed_cents` plus its `render_actual_cents` plus
        this job's `estimated_cost_cents` is at most the production's
        `render_allowance_cents` — otherwise `ERR_RENDER_BUDGET_EXCEEDED` (402)."

        Design: Corner/errors/render_reservation_beyond_allowance_rejects
        """
        pool = fx.create_pool(
            client, name="FARM_A", total_cores=100, cost_per_core_hour_cents=175
        )
        production = fx.active_production(
            client,
            title="Paper Lanterns",
            production_code="AD06",
            format="SHORT",
            budget_cents=100000000,
            render_allowance_cents=500,
            gate_types=["SCRIPT"],
        )
        shot = fx.create_shot(
            client,
            production["id"],
            shot_code="AD06_010_0010",
            planned_finish_at="2026-09-30T00:00:00Z",
        )
        task = fx.task_for_stage(client, shot["id"], "LAYOUT")
        fx.assign_task(client, task["id"])
        pool_version = fx.read_pool(client, pool["id"])["version"]

        def attempt(frame_count):
            return client.create_render_job(
                f.render_job_payload(
                    pool["id"],
                    task["id"],
                    pool_version,
                    requested_cores=3,
                    window_start="2026-08-02T00:00:00Z",
                    window_end="2026-08-02T06:00:00Z",
                    frame_count=frame_count,
                    seconds_per_frame=50,
                ),
                PRODUCTION_MANAGER_HEADERS,
            )

        validate_error(attempt(120), "ERR_RENDER_BUDGET_EXCEEDED", 402)

        after_reject = fx.read_pool(client, pool["id"])
        assert after_reject["version"] == pool_version
        assert_two_decimal(
            after_reject["committed_core_hours"], 0.00, "committed_core_hours"
        )

        small = validate_success(attempt(1), 201)
        assert small["status"] == JOB_RESERVED
        assert small["estimated_cost_cents"] == 7

        assert fx.read_production(client, production["id"])["render_committed_cents"] == 7


class TestSeatCapacityCeiling:
    def test_the_seat_check_admits_a_full_house_and_refuses_one_more(self, client):
        """Booking exactly as many attendees as seats is legal, one more is a 422, and the
        rejected attempt leaves the identical window free.

        PRD: "And `attendee_count` may not exceed the room's `seat_capacity`, otherwise
        `ERR_ROOM_SEAT_CAPACITY_EXCEEDED`."

        Design: Corner/errors/session_attendee_count_beyond_seat_capacity_rejects
        """
        room = fx.calibrated_room(client, name="SMALL_1", seat_capacity=4)
        assert room["seat_capacity"] == 4
        production = fx.active_production(
            client, title="Aurora Drift", production_code="AD01", gate_types=["SCRIPT"]
        )

        def booking(attendee_count):
            return f.review_session_payload(
                production["id"],
                room["id"],
                window_start="2026-08-01T09:00:00Z",
                window_end="2026-08-01T10:00:00Z",
                attendee_count=attendee_count,
            )

        validate_error(
            client.create_review_session(booking(5), DIRECTOR_HEADERS),
            "ERR_ROOM_SEAT_CAPACITY_EXCEEDED",
            422,
        )

        booked = validate_success(
            client.create_review_session(booking(4), DIRECTOR_HEADERS), 201
        )
        assert booked["attendee_count"] == 4
        assert booked["status"] == SESSION_SCHEDULED

        _, meta = validate_paginated(
            client.list_review_sessions(
                DIRECTOR_HEADERS, {"screening_room_id": room["id"]}
            )
        )
        assert meta["total_count"] == 1
