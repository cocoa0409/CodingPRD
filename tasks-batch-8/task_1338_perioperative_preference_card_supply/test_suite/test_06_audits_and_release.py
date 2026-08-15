"""Card accuracy audit lifecycle and pick-list release snapshots/listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_pct,
    get_audit_for_case,
    get_success_data,
    make_case,
    make_published_card,
    make_supply_item,
    make_surgeon,
    make_surgeon_headers,
    release_pick_list,
    setup_completed_case,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
ANY = TEST_USERS["any_headers"]


def _glove():
    return make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                            unit_cost_cents=250, substitute_group="GLOVES",
                            initial_on_hand=100)


def _completed_one_line(surgeon_name="Dr. Loop", procedure="CATH", room="OR-5",
                        start="2026-09-01T08:00:00Z", duration=45):
    """Completed 1-line case (1x GLOVE-PR used fully) -> audit GENERATED."""
    surgeon = make_surgeon(full_name=surgeon_name, specialty="CARD")
    glove = _glove()
    ctx = setup_completed_case(
        surgeon, [glove],
        [{"item_index": 0, "quantity": 1, "designation": "OPEN"}],
        usage_by_index={0: 1},
        procedure_name=procedure,
        scheduled_start=start,
        expected_duration_min=duration,
        room=room,
    )
    return surgeon, ctx


class TestAuditDisputeCycle:
    def test_audit_dispute_rereview_cycle(self):
        """PRD §3.6: "A `Surgeon` may dispute an audit from those same two
        states ... A dispute moves the audit to `DISPUTED` and stores the
        optional `comment` as the audit's `dispute_comment`, the latest comment
        being the one retained. The analyst then re-opens a `DISPUTED` audit
        for review — only from `DISPUTED`, otherwise `ERR_AUDIT_NOT_DISPUTED`
        — returning it to `UNDER_REVIEW`, from which it may be disputed again
        or finally accepted."

        Design: Difficulty/non_linear_state_machine/audit_dispute_rereview_cycle
        """
        surgeon, ctx = _completed_one_line()
        audit = ctx["audit"]

        d1 = validate_success(api_client.dispute_card_audit(
            audit["id"], {"comment": "waste attribution wrong"},
            make_surgeon_headers(surgeon["id"]),
        ))
        assert d1["status"] == "DISPUTED"

        r1 = validate_success(api_client.reopen_card_audit_review(audit["id"], ANALYST))
        assert r1["status"] == "UNDER_REVIEW"

        d2 = validate_success(api_client.dispute_card_audit(
            audit["id"], {"comment": "still wrong"},
            make_surgeon_headers(surgeon["id"]),
        ))
        assert d2["status"] == "DISPUTED"

        get_success_data(api_client.reopen_card_audit_review(audit["id"], ANALYST))
        a = validate_success(api_client.accept_card_audit(audit["id"], ANALYST))
        assert a["status"] == "ACCEPTED"

        final = get_success_data(api_client.get_card_audit(audit["id"], ANY))
        assert final["dispute_comment"] == "still wrong"
        assert_pct(final["line_match_pct"], 100.0, "line_match_pct")

    def test_audit_cycle_second_dispute_allowed(self):
        """PRD §3.6: "returning it to `UNDER_REVIEW`, from which it may be
        disputed again or finally accepted."

        Design: Difficulty/non_linear_state_machine/audit_dispute_rereview_cycle
        """
        surgeon, ctx = _completed_one_line(
            surgeon_name="Dr. Loop2", procedure="CATH", room="OR-5",
            start="2026-09-02T08:00:00Z",
        )
        audit = ctx["audit"]
        api_client.dispute_card_audit(
            audit["id"], {"comment": "first"},
            make_surgeon_headers(surgeon["id"]),
        )
        api_client.reopen_card_audit_review(audit["id"], ANALYST)
        d = validate_success(api_client.dispute_card_audit(
            audit["id"], {"comment": "second"},
            make_surgeon_headers(surgeon["id"]),
        ))
        assert d["status"] == "DISPUTED"
        assert d["dispute_comment"] == "second"


class TestAuditTerminalAndGuards:
    def test_accept_audit_twice_terminal_lockdown(self):
        """PRD §3.6: "A `SupplyChainAnalyst` accepts an audit from either
        `GENERATED` or `UNDER_REVIEW`, moving it to the terminal `ACCEPTED`
        state; accepting from any other state is rejected with
        `ERR_AUDIT_NOT_ACTIONABLE`."

        Design: Corner/state_machines/accept_audit_twice_terminal_lockdown
        """
        _, ctx = _completed_one_line(surgeon_name="Dr. Term", procedure="TKA",
                                     room="OR-1", start="2026-09-05T08:00:00Z",
                                     duration=60)
        audit = ctx["audit"]
        get_success_data(api_client.accept_card_audit(audit["id"], ANALYST))
        resp = api_client.accept_card_audit(audit["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_ACTIONABLE)
        after = get_success_data(api_client.get_card_audit(audit["id"], ANY))
        assert after["status"] == "ACCEPTED"

    def test_reopen_generated_audit_returns_not_disputed(self):
        """PRD §3.6: "The analyst then re-opens a `DISPUTED` audit for review
        — only from `DISPUTED`, otherwise `ERR_AUDIT_NOT_DISPUTED`"

        Design: Corner/state_machines/reopen_generated_audit_returns_not_disputed
        """
        _, ctx = _completed_one_line(surgeon_name="Dr. Gen", procedure="TKA",
                                     room="OR-1", start="2026-09-05T08:00:00Z",
                                     duration=60)
        audit = ctx["audit"]
        resp = api_client.reopen_card_audit_review(audit["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_DISPUTED)
        after = get_success_data(api_client.get_card_audit(audit["id"], ANY))
        assert after["status"] == "GENERATED"


class TestReleaseSnapshot:
    def test_release_creates_snapshot_lines_with_frozen_costs(self):
        """PRD §3.4: "Release creates the pick list in `GENERATED` status,
        stamped with the case's `case_id` and carrying `card_id` and
        `card_version_number` copied from the case's pin, along with one pick
        list line per line of the pinned card version. Each pick line snapshots
        the card line's `designation`, its planned quantity as `qty_requested`,
        the item's release-time `unit_cost_cents`, and the `pick_sequence` for
        stable ordering, and begins in `PENDING` with `qty_picked` and
        `qty_returned_unopened` at zero. In the same atomic step the case's
        `standard_cost_cents` is computed"

        Design: Corner/endpoints/release_creates_snapshot_lines_with_frozen_costs
        """
        surgeon = make_surgeon(full_name="Dr. Snap")
        glove = _glove()
        card = make_published_card(
            surgeon["id"], "TKA",
            [{"supply_item_id": glove["id"], "quantity": 2, "designation": "OPEN",
              "pick_sequence": 1}],
        )
        case = make_case(surgeon["id"], card["id"],
                         scheduled_start="2026-09-05T08:00:00Z",
                         expected_duration_min=60, room="OR-1")
        pl, lines = release_pick_list(case["id"])
        assert pl["card_version_number"] == 1
        assert len(lines) == 1
        line = lines[0]
        assert line["qty_requested"] == 2
        assert line["designation"] == "OPEN"
        assert line["unit_cost_cents"] == 250
        assert line["status"] == "PENDING"
        case_after = get_success_data(api_client.get_case(case["id"], ANY))
        assert case_after["standard_cost_cents"] == 500
        assert case_after["status"] == "PICKING_RELEASED"


class TestListFilters:
    def test_pick_list_lines_filtered_list_returns_own_lines_only(self):
        """PRD §3.4: "Pick list lines may be listed with `pick_list_id`,
        `supply_item_id`, `substituted_item_id`, and `status` filters, always
        in `pick_sequence` order."

        Design: Corner/endpoints/pick_list_lines_filtered_list_returns_own_lines_only
        """
        surgeon = make_surgeon(full_name="Dr. Filt")
        glove = _glove()
        card = make_published_card(
            surgeon["id"], "TKA",
            [{"supply_item_id": glove["id"], "quantity": 1, "designation": "OPEN"}],
        )
        case_1 = make_case(surgeon["id"], card["id"],
                           scheduled_start="2026-09-05T08:00:00Z",
                           expected_duration_min=60, room="OR-1")
        pl_1, _ = release_pick_list(case_1["id"])
        case_2 = make_case(surgeon["id"], card["id"],
                           scheduled_start="2026-09-05T10:30:00Z",
                           expected_duration_min=60, room="OR-2")
        release_pick_list(case_2["id"])
        rows, meta = validate_paginated(
            api_client.list_pick_list_lines(ANY, params={"pick_list_id": pl_1["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["pick_list_id"] == pl_1["id"]

    def test_preference_cards_list_paginates_with_limit_offset(self):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10 when omitted ... The `offset` parameter specifies how
        many items to skip and defaults to 0. ... The `meta` envelope of every
        list response carries `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/preference_cards_list_paginates_with_limit_offset
        """
        surgeon = make_surgeon(full_name="Dr. Page")
        for proc in ("P1", "P2", "P3"):
            api_client.create_preference_card(
                {"surgeon_id": surgeon["id"], "procedure_name": proc}, ANALYST
            )
        page1 = api_client.list_preference_cards(
            ANY, params={"surgeon_id": surgeon["id"], "limit": 2}
        )
        rows1, meta1 = validate_paginated(page1)
        assert len(rows1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2 = api_client.list_preference_cards(
            ANY, params={"surgeon_id": surgeon["id"], "limit": 2, "offset": 2}
        )
        rows2, meta2 = validate_paginated(page2)
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
