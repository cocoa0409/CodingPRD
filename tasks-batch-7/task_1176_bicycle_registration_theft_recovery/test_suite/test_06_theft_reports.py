"""Theft reports: review loop, flag cascade, withdraw, version bookkeeping
(PRD §2.5, §3.4)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    register_owner,
    register_bicycle,
    owner_headers,
    file_theft_report,
    flag_report,
    set_clock,
    create_theft_report_payload,
    create_active_partner_org,
    partner_headers,
    create_intake,
    scan_intake,
    get_single_match_for_intake,
    get_notifications_for_owner,
    create_transfer_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestReviewLoop:
    def test_theft_report_review_info_cycle_twice_then_flag(self, api):
        """PRD §3.4: "Review is a dialogue, and the loop between registrar and owner
        is unbounded."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by
        1 with every modification to the resource, including modifications caused
        by a cascade from another entity's transition."

        Two full UNDER_REVIEW -> NEEDS_INFO -> UNDER_REVIEW loops (4 transitions)
        followed by flag: version 1 (create) + 5 transitions == 6.

        Design: Difficulty/non_linear_state_machine/theft_report_review_info_cycle
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(owner, serial_number="CYC100", declared_value_cents=90000)
        report = file_theft_report(owner, bicycle)
        for round_no in (1, 2):
            asked = validate_success(
                api.request_info_theft_report(
                    report["id"], {"info_request_text": f"round {round_no}"}, REGISTRAR
                )
            )
            assert asked["status"] == "NEEDS_INFO"
            answered = validate_success(
                api.respond_theft_report(
                    report["id"], {"response_text": f"answer {round_no}"},
                    owner_headers(owner),
                )
            )
            assert answered["status"] == "UNDER_REVIEW", (
                f"the review loop must be re-enterable (iteration {round_no})"
            )
        flagged = validate_success(api.flag_theft_report(report["id"], REGISTRAR))
        assert flagged["status"] == "FLAGGED"
        assert flagged["version"] == 6, (
            f"create=1 plus five transitions must yield version 6, got {flagged['version']}"
        )
        bicycle_after = validate_success(api.get_bicycle(bicycle["id"], REGISTRAR))
        assert bicycle_after["registry_status"] == "STOLEN"

    def test_review_loop_stores_request_and_response_text(self, api):
        """PRD §3.4: "A `Registrar` who needs more detail sends the report from
        `UNDER_REVIEW` to `NEEDS_INFO`, supplying an `info_request_text` that is
        stored on the report. The owner — and only the report's owner — answers by
        moving the report from `NEEDS_INFO` back to `UNDER_REVIEW`, supplying a
        `response_text` that is likewise stored."

        Design: Difficulty/non_linear_state_machine/theft_report_review_info_cycle
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(owner, serial_number="CYC101", declared_value_cents=90000)
        report = file_theft_report(owner, bicycle)
        asked = validate_success(
            api.request_info_theft_report(
                report["id"], {"info_request_text": "need receipt"}, REGISTRAR
            )
        )
        assert asked["info_request_text"] == "need receipt"
        answered = validate_success(
            api.respond_theft_report(
                report["id"], {"response_text": "receipt attached"}, owner_headers(owner)
            )
        )
        assert answered["status"] == "UNDER_REVIEW"
        assert answered["response_text"] == "receipt attached"
        # The loop is unbounded: a second round is accepted from UNDER_REVIEW.
        asked2 = validate_success(
            api.request_info_theft_report(
                report["id"], {"info_request_text": "need better photo"}, REGISTRAR
            )
        )
        assert asked2["status"] == "NEEDS_INFO"
        assert asked2["info_request_text"] == "need better photo"

    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that increments
        by 1 with every modification to the resource, including modifications
        caused by a cascade from another entity's transition."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(owner, serial_number="OCC300")
        report = file_theft_report(owner, bicycle)
        assert report["version"] == 1, f"fresh report version must be 1, got {report['version']}"
        v2 = validate_success(
            api.request_info_theft_report(
                report["id"], {"info_request_text": "need receipt"}, REGISTRAR
            )
        )
        assert v2["version"] == 2, f"request-info must bump version to 2, got {v2['version']}"
        v3 = validate_success(
            api.respond_theft_report(
                report["id"], {"response_text": "attached"}, owner_headers(owner)
            )
        )
        assert v3["version"] == 3, f"respond must bump version to 3, got {v3['version']}"


class TestReportCreationAndActionGuards:
    def test_report_already_open_constraint(self, api):
        """PRD §3.4: "A bicycle may have at most one non-terminal theft report —
        one in `UNDER_REVIEW`, `NEEDS_INFO`, or `FLAGGED`; a second filing while
        one is open is rejected with `ERR_REPORT_ALREADY_OPEN`."

        Design: Corner/validations/report_already_open_constraint
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(owner, serial_number="ROP100")
        file_theft_report(owner, bicycle, occurred_at="2026-05-03T00:00:00Z")
        resp = api.create_theft_report(
            create_theft_report_payload(bicycle["id"], occurred_at="2026-05-04T00:00:00Z"),
            owner_headers(owner),
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_ALREADY_OPEN, expected_status=409)

    def test_flag_nonexistent_report_returns_not_found_before_state(self, api):
        """PRD §2.6: "each identifier in the URL path must resolve to an existing
        row, checked sequentially from the leftmost segment; the first unresolvable
        segment produces its entity-specific 404" — here
        `ERR_THEFT_REPORT_NOT_FOUND`.
        PRD §2.6: "a failure at an earlier stage surfaces its error and masks every
        later-stage check."

        Design: Corner/validations/flag_nonexistent_report_returns_not_found_before_state
        """
        resp = api.flag_theft_report(NON_EXISTENT_UUID, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_THEFT_REPORT_NOT_FOUND, expected_status=404)

    def test_owner_cannot_flag_report(self, api):
        """PRD §4: POST /registry/theft-reports/{id}/flag is authorized for
        Registrar only.
        PRD §2.1: "A request whose role is well-formed but not permitted for the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/owner_cannot_flag_report
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(owner, serial_number="RBC100")
        report = file_theft_report(owner, bicycle)
        resp = api.flag_theft_report(report["id"], owner_headers(owner))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_flag_twice_rejected_idempotency(self, api):
        """PRD §3.4: "Flagging requires the report to be `UNDER_REVIEW` and the
        bicycle's `integrity_status` to be anything other than `MERGED`."
        PRD §3.4: "Either action invoked from a state that does not allow it is
        rejected with `ERR_THEFT_REPORT_NOT_ACTIONABLE`."

        Design: Corner/state_machines/flag_twice_rejected_idempotency
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(owner, serial_number="IDM100", declared_value_cents=60000)
        report = file_theft_report(owner, bicycle)
        flag_report(report["id"])
        bicycle_after_first = validate_success(api.get_bicycle(bicycle["id"], REGISTRAR))
        resp = api.flag_theft_report(report["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_THEFT_REPORT_NOT_ACTIONABLE, expected_status=409)
        bicycle_after_second = validate_success(api.get_bicycle(bicycle["id"], REGISTRAR))
        assert bicycle_after_second["registry_status"] == "STOLEN"
        assert bicycle_after_second["version"] == bicycle_after_first["version"], (
            "a rejected second flag must not mutate the bicycle again"
        )


class TestFlagCascade:
    def test_flag_cascade_report_bicycle_transfer_notification(self, api):
        """PRD §3.4: "The bicycle's `registry_status` moves from `REGISTERED` to
        `STOLEN`, incrementing the bicycle's `version`. Every `PENDING_ACCEPTANCE`
        transfer on that bicycle is force-cancelled to `CANCELLED`, each such
        transfer's `version` increments, and each cancellation creates a
        `TRANSFER_CANCELLED_STOLEN` notification addressed to that transfer's
        `to_owner_id` buyer."

        Design: Difficulty/transitive_cascade/flag_cascade_report_bicycle_transfer_notification
        """
        seller = register_owner("o1@x.com", "O One")
        buyer = register_owner("o2@x.com", "O Two")
        bicycle = register_bicycle(seller, serial_number="CSC100", declared_value_cents=80000)
        transfer = validate_success(
            api.create_transfer(
                create_transfer_payload(bicycle["id"], "o2@x.com", sale_price_cents=50000),
                owner_headers(seller),
            ),
            expected_status=201,
        )
        report = file_theft_report(seller, bicycle)
        flagged = validate_success(api.flag_theft_report(report["id"], REGISTRAR))
        assert flagged["status"] == "FLAGGED"
        bicycle_after = validate_success(api.get_bicycle(bicycle["id"], REGISTRAR))
        assert bicycle_after["registry_status"] == "STOLEN", (
            "link 1: the flag cascade must flip the bicycle to STOLEN"
        )
        transfer_after = validate_success(api.get_transfer(transfer["id"], REGISTRAR))
        assert transfer_after["status"] == "CANCELLED", (
            "link 2: the pending transfer must be force-cancelled by the bicycle flip"
        )
        buyer_notifications = get_notifications_for_owner(buyer["id"])
        kinds = [n["kind"] for n in buyer_notifications]
        assert "TRANSFER_CANCELLED_STOLEN" in kinds, (
            f"link 3: buyer must receive TRANSFER_CANCELLED_STOLEN, got {kinds}"
        )

    def test_flag_stamps_flagged_at_and_notifies_owner(self, api):
        """PRD §3.4: "On flag, the report moves to `FLAGGED`, its `flagged_at` is
        stamped from the current logical clock, and its `version` increments."
        PRD §3.4: "Finally, a `REPORT_FLAGGED` notification is created for the
        bicycle's `current_owner_id`."

        Design: Difficulty/transitive_cascade/flag_cascade_report_bicycle_transfer_notification
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(owner, serial_number="CSC101", declared_value_cents=80000)
        report = file_theft_report(owner, bicycle)
        set_clock("2026-05-04T12:34:56Z")
        flagged = validate_success(api.flag_theft_report(report["id"], REGISTRAR))
        assert flagged["status"] == "FLAGGED"
        assert flagged["flagged_at"] is not None and flagged["flagged_at"].startswith(
            "2026-05-04T12:34:56"
        ), f"flagged_at must be stamped from the logical clock, got {flagged['flagged_at']}"
        owner_notifications = get_notifications_for_owner(owner["id"])
        kinds = [n["kind"] for n in owner_notifications]
        assert "REPORT_FLAGGED" in kinds, (
            f"owner must receive REPORT_FLAGGED, got {kinds}"
        )


class TestWithdrawFromFlagged:
    def test_withdraw_flagged_report_reverts_bicycle_and_expires_matches(self, api):
        """PRD §3.4: "Withdrawing a `FLAGGED` report — the owner found the bike —
        is heavier: it is permitted only while no `MatchCandidate` on this report
        stands in `CONFIRMED` status (an attempt otherwise fails with
        `ERR_THEFT_REPORT_NOT_ACTIONABLE`), and it unwinds the flag. The bicycle's
        `registry_status` returns from `STOLEN` to `REGISTERED`, and every match
        candidate on this report still in `PROPOSED` or `NOTIFIED` transitions to
        `EXPIRED`, each with its own `version` increment."

        Design: Corner/state_machines/withdraw_flagged_report_reverts_bicycle_and_expires_matches
        """
        set_clock("2026-05-01T00:00:00Z")
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(
            owner, serial_number="WDR100", manufacturer="Giant", model="Defy",
            primary_color="Red", declared_value_cents=60000,
        )
        report = file_theft_report(owner, bicycle, occurred_at="2026-05-10T00:00:00Z")
        flag_report(report["id"])
        org = create_active_partner_org()
        intake = create_intake(
            org,
            serial_number_raw="WDR100",
            primary_color="Red",
            found_at="2026-05-12T00:00:00Z",
            appraised_value_cents=40000,
            manufacturer="Giant",
        )
        scan_intake(intake["id"], partner_headers(org))
        match = get_single_match_for_intake(intake["id"])
        assert match["status"] == "NOTIFIED"
        withdrawn = validate_success(
            api.withdraw_theft_report(report["id"], owner_headers(owner))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        bicycle_after = validate_success(api.get_bicycle(bicycle["id"], REGISTRAR))
        assert bicycle_after["registry_status"] == "REGISTERED", (
            "withdrawal from FLAGGED must close the registry cycle STOLEN -> REGISTERED"
        )
        match_after = validate_success(api.get_match(match["id"], REGISTRAR))
        assert match_after["status"] == "EXPIRED", (
            f"open matches on the withdrawn report must expire, got {match_after['status']}"
        )
