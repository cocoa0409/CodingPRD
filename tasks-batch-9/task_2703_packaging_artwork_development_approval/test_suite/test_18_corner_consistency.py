"""Immediate consistency: derived and cascaded values are in the write's own body."""

import pytest

from test_helpers import (
    ELEMENT_ORDER,
    api_client,
    brand,
    coord,
    legal,
    new_approved_brief,
    new_asset,
    new_version,
    quality,
    regulatory,
    submit_payload,
    task_decision_payload,
    validate_paginated,
    validate_success,
    verify_elements_payload,
)


class TestNothingConvergesAfterTheFact:
    """A verification run, a submit that opens stage 1, and the approval cascade."""

    def test_every_derived_value_is_readable_on_the_first_attempt(self):
        """Scores, tasks and the cascade are all visible with no retry and no second write.

        PRD §1: "Second, the system is **cascading**: approving one artwork version can, in
        a single request, complete a review route, approve a version, repoint an asset,
        obsolete a predecessor, auto-cancel that predecessor's plate orders and debit the
        asset's plate ledger."

        PRD §3.5: "Four review tasks are created from that plan — one per discipline — each
        stamped with its `discipline`, its `mode` and its `stage_no`, each starting with
        `decision` `PENDING`, and each with `is_active` false except the two stage-1 tasks,
        which are activated as the pass immediately moves `PENDING → IN_PROGRESS` inside the
        very same request."

        PRD §3.5: "Completion propagates to the artwork version in the same request."

        Design: Corner/consistency_model/every_write_response_already_carries_its_own_derived_and_cascaded_values
        """
        brief = new_approved_brief()
        asset = new_asset(brief["id"])
        version = new_version(asset)
        assert version["state"] == "DRAFT"
        assert version["pinned_claim_snapshot"] == []
        assert version["compliance_score"] is None

        verified = validate_success(
            api_client.verify_elements(
                version["id"],
                verify_elements_payload(
                    verification_note="Mandatory element verification run."
                ),
                coord(),
            ),
            200,
        )
        assert verified["state"] == "ELEMENTS_VERIFIED"
        assert verified["check_run_no"] == 1
        assert verified["compliance_score"] == pytest.approx(100.0, abs=0.01)
        assert verified["failed_element_count"] == 0
        assert verified["waived_element_count"] == 0

        echoed = validate_success(
            api_client.get_artwork_version(version["id"], coord()), 200
        )
        for field in ("state", "check_run_no", "compliance_score", "version"):
            assert echoed[field] == verified[field]

        checks, check_meta = validate_paginated(
            api_client.list_element_checks(
                coord(), params={"artwork_version_id": version["id"], "limit": 100}
            )
        )
        assert check_meta["total_count"] == 7
        assert [row["element_code"] for row in checks] == ELEMENT_ORDER
        assert all(row["result"] == "PASS" for row in checks)
        assert all(row["check_run_no"] == 1 for row in checks)

        first_check = validate_success(
            api_client.get_element_check(checks[0]["id"], coord()), 200
        )
        assert first_check["element_code"] == "NET_CONTENTS"
        assert first_check["check_run_no"] == 1
        assert first_check["result"] == "PASS"
        assert first_check["severity"] == "CRITICAL"
        assert first_check["deduction_points"] == pytest.approx(0.0, abs=0.01)
        assert first_check["waived_by_user_id"] is None

        submitted = validate_success(
            api_client.submit_artwork_version(
                version["id"],
                submit_payload(
                    submit_note="Route through brand, regulatory, legal and quality."
                ),
                coord(),
            ),
            200,
        )
        assert submitted["state"] == "IN_REVIEW"
        assert submitted["route_count"] == 1

        routes, route_meta = validate_paginated(
            api_client.list_review_routes(
                coord(),
                params={
                    "artwork_version_id": version["id"],
                    "status": "IN_PROGRESS",
                },
            )
        )
        assert route_meta["total_count"] == 1
        route_id = routes[0]["id"]
        assert routes[0]["route_no"] == 1
        assert routes[0]["current_stage_no"] == 1

        tasks, task_meta = validate_paginated(
            api_client.list_review_tasks(
                coord(), params={"review_route_id": route_id, "limit": 100}
            )
        )
        assert task_meta["total_count"] == 4
        opened = {row["discipline"]: row for row in tasks}
        assert opened["BRAND"]["stage_no"] == 1
        assert opened["BRAND"]["is_active"] is True
        assert opened["REGULATORY"]["stage_no"] == 1
        assert opened["REGULATORY"]["is_active"] is True
        assert opened["LEGAL"]["is_active"] is False
        assert opened["QUALITY"]["is_active"] is False
        assert all(row["decision"] == "PENDING" for row in tasks)

        validate_success(
            api_client.decide_review_task(
                opened["BRAND"]["id"],
                task_decision_payload("APPROVED", comment="Brand identity approved."),
                brand(),
            ),
            200,
        )
        validate_success(
            api_client.decide_review_task(
                opened["REGULATORY"]["id"],
                task_decision_payload("APPROVED", comment="Regulatory copy approved."),
                regulatory(),
            ),
            200,
        )

        advanced, _meta = validate_paginated(
            api_client.list_review_tasks(
                coord(), params={"review_route_id": route_id, "limit": 100}
            )
        )
        second_stage = {row["discipline"]: row for row in advanced}
        assert second_stage["LEGAL"]["is_active"] is True
        assert second_stage["QUALITY"]["is_active"] is False
        assert (
            validate_success(api_client.get_review_route(route_id, coord()), 200)[
                "current_stage_no"
            ]
            == 2
        )

        validate_success(
            api_client.decide_review_task(
                second_stage["LEGAL"]["id"],
                task_decision_payload("APPROVED", comment="No legal exposure."),
                legal(),
            ),
            200,
        )
        third_stage, _third_meta = validate_paginated(
            api_client.list_review_tasks(
                coord(),
                params={"review_route_id": route_id, "discipline": "QUALITY"},
            )
        )
        assert len(third_stage) == 1
        assert third_stage[0]["is_active"] is True

        final_task = validate_success(
            api_client.decide_review_task(
                third_stage[0]["id"],
                task_decision_payload("APPROVED", comment="Quality sign-off."),
                quality(),
            ),
            200,
        )
        assert final_task["decision"] == "APPROVED"
        assert final_task["decided_by_user_id"] == "u_qa"

        closed_route = validate_success(
            api_client.get_review_route(route_id, coord()), 200
        )
        assert closed_route["status"] == "COMPLETE_APPROVED"
        assert closed_route["current_stage_no"] == 3
        assert closed_route["conditional_count"] == 0
        assert closed_route["completed_at"].startswith("2026-08-01T00:00:00")

        cascaded_version = validate_success(
            api_client.get_artwork_version(version["id"], coord()), 200
        )
        assert cascaded_version["state"] == "APPROVED"
        assert cascaded_version["approved_at"].startswith("2026-08-01T00:00:00")
        assert cascaded_version["requires_reverification"] is False
        assert cascaded_version["pinned_claim_snapshot"] == []

        cascaded_asset = validate_success(
            api_client.get_artwork_asset(asset["id"], coord()), 200
        )
        assert cascaded_asset["current_approved_version_id"] == version["id"]
        assert cascaded_asset["obsolescence_state"] == "ACTIVE"

        assert (
            validate_success(api_client.get_review_route(route_id, coord()), 200)
            == closed_route
        )
        assert (
            validate_success(
                api_client.get_artwork_version(version["id"], coord()), 200
            )
            == cascaded_version
        )
        assert (
            validate_success(api_client.get_artwork_asset(asset["id"], coord()), 200)
            == cascaded_asset
        )
