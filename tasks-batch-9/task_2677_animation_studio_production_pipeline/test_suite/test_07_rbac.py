"""Authorization tests: role lists, segregation of duties and ownership scoping."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_instant, assert_two_decimal
from test_helpers.constants import (
    PACKAGE_IN_PROGRESS,
    PACKAGE_ISSUED,
    TASK_APPROVED,
    TASK_IN_PROGRESS,
    TASK_SUBMITTED,
)
from test_helpers.test_users import (
    ARTIST_ALT_HEADERS,
    ARTIST_HEADERS,
    ARTIST_USER_ID,
    PRODUCTION_MANAGER_HEADERS,
    SUPERVISOR_ALT_HEADERS,
    SUPERVISOR_HEADERS,
    SUPERVISOR_USER_ID,
    SUPERVISOR_USER_ID_ALT,
    make_artist_headers,
    make_partner_representative_headers,
)


def _active_show_with_shot(client, **overrides):
    overrides.setdefault("gate_types", ["SCRIPT"])
    overrides.setdefault("title", "Aurora Drift")
    overrides.setdefault("production_code", "AD01")
    production = fx.active_production(client, **overrides)
    shot = fx.create_shot(
        client,
        production["id"],
        shot_code="AD01_010_0010",
        planned_finish_at="2026-09-30T00:00:00Z",
    )
    return production, shot


class TestArtistWriteSurface:
    def test_the_role_check_runs_before_any_business_rule(self, client):
        """An artist posting a flawless shot body is refused on the role alone, and the assign
        an artist cannot make is a 409 in a production manager's hands — so the 403 was not a
        business rejection wearing another name.

        PRD: "If the headers are well formed but the named role is not listed as an authorized
        role for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD: "For a stage task whose `stage_order` is greater than 1, the sibling task of the
        same shot whose `stage_order` is one lower has status `APPROVED` — otherwise
        `ERR_PREVIOUS_STAGE_NOT_APPROVED` (409)."

        Design: Corner/rbac/artist_cannot_create_shots_or_assign_stages
        """
        production, shot = _active_show_with_shot(client)
        animation = fx.task_for_stage(client, shot["id"], "ANIMATION")

        refused_create = client.create_shot(
            f.shot_payload(
                production["id"],
                shot_code="AD01_010_0020",
                frame_count=96,
                budget_cents=800000,
                planned_finish_at="2026-09-30T00:00:00Z",
            ),
            ARTIST_HEADERS,
        )
        validate_error(refused_create, "ERR_UNAUTHORIZED", 403)

        refused_assign = client.assign_stage_task(
            animation["id"], f.assign_payload(ARTIST_USER_ID), ARTIST_HEADERS
        )
        validate_error(refused_assign, "ERR_UNAUTHORIZED", 403)

        out_of_order = client.assign_stage_task(
            animation["id"], f.assign_payload(ARTIST_USER_ID), PRODUCTION_MANAGER_HEADERS
        )
        validate_error(out_of_order, "ERR_PREVIOUS_STAGE_NOT_APPROVED", 409)

        _, meta = validate_paginated(
            client.list_shots(ARTIST_HEADERS, {"production_id": production["id"]})
        )
        assert meta["total_count"] == 1


class TestStageReviewSegregation:
    def test_the_submitting_identifier_cannot_decide_its_own_stage(self, client):
        """Segregation compares identifiers rather than roles, so the supervisor who submitted
        the stage as its assignee is refused and a different supervisor decides it at once.

        PRD: "If the two are equal, the decision is refused with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403), and no counter, timestamp or state moves."

        Design: Corner/rbac/stage_review_decision_rejects_the_submitting_user
        """
        _, shot = _active_show_with_shot(client)
        task = fx.task_for_stage(client, shot["id"], "LAYOUT")
        fx.assign_task(client, task["id"], artist_user_id=SUPERVISOR_USER_ID)
        submitted = fx.submit_task(
            client, task["id"], headers=make_artist_headers(SUPERVISOR_USER_ID), hours=6.0
        )
        assert submitted["submitted_by_user_id"] == SUPERVISOR_USER_ID
        assert submitted["status"] == TASK_SUBMITTED

        self_decision = client.decide_stage_task(
            task["id"], f.task_decision_payload("APPROVED"), SUPERVISOR_HEADERS
        )
        validate_error(self_decision, "ERR_SEGREGATION_OF_DUTIES", 403)

        unmoved = fx.read_task(client, task["id"], SUPERVISOR_HEADERS)
        assert unmoved["status"] == TASK_SUBMITTED
        assert unmoved["reviewed_by_user_id"] is None

        approved = validate_success(
            client.decide_stage_task(
                task["id"], f.task_decision_payload("APPROVED"), SUPERVISOR_ALT_HEADERS
            )
        )
        assert approved["status"] == TASK_APPROVED
        assert approved["reviewed_by_user_id"] == SUPERVISOR_USER_ID_ALT
        assert_instant(approved["approved_at"], "2026-08-01T00:00:00Z")


class TestPartnerRepresentativeScoping:
    def test_the_vendor_seat_is_scoped_by_endpoint_and_by_identity(self, client):
        """The vendor cannot read the show it works for, may read its own package, cannot
        accept somebody else's, and cannot grade its own work.

        PRD: "The vendor's read surface is deliberately narrow: it is authorized only on the
        stage-task and outsourcing-package read endpoints, so a partner probing productions,
        shots, assets, sessions, notes, pools, jobs or deliverables receives
        `ERR_UNAUTHORIZED`."
        PRD: "Ownership checks on any resource that references an `OutsourcePartner` compare
        the resource's foreign-key field to `X-User-ID`: accepting or delivering an
        outsourcing package requires `X-User-ID` to equal that package's `partner_id`, and a
        mismatch is rejected with `ERR_NOT_PACKAGE_PARTNER` (HTTP 403)."

        Design: Corner/rbac/partner_representative_cannot_read_productions_or_accept_others_packages
        """
        owner = fx.approved_partner(
            client,
            legal_name="Ink & Pixel Studios",
            security_certification_level="TIER1",
            mfa_enforced=True,
        )
        outsider = fx.approved_partner(
            client,
            legal_name="Sketch Loft",
            security_certification_level="TIER1",
            mfa_enforced=True,
        )
        production, shot = _active_show_with_shot(client)
        task = fx.task_for_stage(client, shot["id"], "LAYOUT")

        package = fx.issued_package(
            client,
            production["id"],
            owner["id"],
            package_code="AD01_PKG_01",
            security_tier="TIER1",
            fee_cents=500000,
            stage_task_ids=[task["id"]],
            quality_min_score=50.00,
        )
        assert package["status"] == PACKAGE_ISSUED

        owner_headers = make_partner_representative_headers(owner["id"])
        outsider_headers = make_partner_representative_headers(outsider["id"])

        validate_error(
            client.get_production(production["id"], owner_headers),
            "ERR_UNAUTHORIZED",
            403,
        )

        own_read = validate_success(
            client.get_outsource_package(package["id"], owner_headers)
        )
        assert own_read["status"] == PACKAGE_ISSUED
        assert own_read["fee_cents"] == 500000

        validate_error(
            client.accept_package(package["id"], {}, outsider_headers),
            "ERR_NOT_PACKAGE_PARTNER",
            403,
        )

        accepted = validate_success(
            client.accept_package(package["id"], {}, owner_headers)
        )
        assert accepted["status"] == PACKAGE_IN_PROGRESS
        assert accepted["fee_committed_cents"] == 500000

        validate_error(
            client.qc_decide_package(
                package["id"], f.package_qc_payload("PASS", 90), owner_headers
            ),
            "ERR_UNAUTHORIZED",
            403,
        )


class TestStageTaskOwnership:
    def test_a_second_artist_holds_the_role_but_not_the_task(self, client):
        """Log-hours and submit compare the caller against the assignee, so another artist's
        identical calls write nothing while the assignee's call is accepted.

        PRD: "On stage-task submission and hour logging, `X-User-ID` equals the task's
        `assigned_artist_user_id`, or the caller is the `PartnerRepresentative` whose
        identifier equals the `partner_id` of the partner behind the task's
        `outsource_package_id` — otherwise `ERR_NOT_TASK_OWNER` (403)."

        Design: Corner/rbac/artist_cannot_log_hours_on_another_artists_task
        """
        _, shot = _active_show_with_shot(client)
        task = fx.task_for_stage(client, shot["id"], "LAYOUT")
        assigned = fx.assign_task(client, task["id"])
        assert assigned["assigned_artist_user_id"] == ARTIST_USER_ID

        validate_error(
            client.log_hours(task["id"], f.log_hours_payload(3.0), ARTIST_ALT_HEADERS),
            "ERR_NOT_TASK_OWNER",
            403,
        )
        validate_error(
            client.submit_stage_task(
                task["id"], f.task_submit_payload(hours=3.0), ARTIST_ALT_HEADERS
            ),
            "ERR_NOT_TASK_OWNER",
            403,
        )

        untouched = fx.read_task(client, task["id"])
        assert_two_decimal(untouched["actual_hours"], 0.00, "actual_hours")
        assert untouched["status"] == TASK_IN_PROGRESS

        logged = validate_success(
            client.log_hours(task["id"], f.log_hours_payload(3.0), ARTIST_HEADERS)
        )
        assert_two_decimal(logged["actual_hours"], 3.00, "actual_hours")
