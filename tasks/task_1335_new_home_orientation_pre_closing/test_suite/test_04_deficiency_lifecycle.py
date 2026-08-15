"""Deficiency identification, classification, decisions, the repair /
re-inspection loop, withdrawal rules, sign-off, and pagination."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_buyer_headers,
    make_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


class TestIdentificationCrossReferences:
    def test_cross_home_appointment_reference_rejected(self, api):
        """PRD §3.4: "The referenced appointment must belong to the same home —
        a mismatch is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND`"

        Design: Corner/errors/cross_home_appointment_reference_rejected
        """
        community, buyer, rep = fx.setup_base()
        h1 = fx.setup_home(community["id"], buyer["id"], lot_number="L-101",
                           address="1 Riverbend Way")
        h2 = fx.setup_home(community["id"], buyer["id"], lot_number="L-102",
                           address="2 Riverbend Way")
        appt = fx.create_appointment(h1["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        resp = api.create_deficiency_item(
            {"home_id": h2["id"], "appointment_id": appt["id"],
             "title": "Wrong-home item"},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND)


class TestClassificationRules:
    def test_decide_on_unclassified_item_rejected(self, api, manager_headers):
        """PRD §3.4: "The before/after decision belongs to the
        `CustomerCareManager`, who sets `resolution` to
        `COMPLETE_BEFORE_CLOSING` or `COMPLETE_AFTER_CLOSING`, moving the item
        `CLASSIFIED` → `DECIDED`."
        PRD §2.8: "State — the target entity is in a valid from-state for the
        requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/decide_on_unclassified_item_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Paint scuff")
        resp = api.decide_deficiency_item(
            item["id"], {"resolution": "COMPLETE_BEFORE_CLOSING"}, manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cosmetic_photo_required_when_flag_on(self, api):
        """PRD §3.4: "When the classification is `COSMETIC` and the community's
        `cosmetic_photo_required` flag is true, `photo_evidence_ref` is
        mandatory and its absence is rejected with
        `ERR_PHOTO_EVIDENCE_REQUIRED`."

        Design: Corner/errors/photo_evidence_required_when_flag_on
        """
        community, buyer, rep = fx.setup_base()  # default flag: true
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Paint scuff")
        resp = api.classify_deficiency_item(
            item["id"],
            {"classification": "COSMETIC", "estimated_repair_cost_cents": 500},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PHOTO_EVIDENCE_REQUIRED)

    def test_cosmetic_photo_not_required_when_flag_off(self, api):
        """PRD §3.4: "When the classification is `COSMETIC` and the community's
        `cosmetic_photo_required` flag is true, `photo_evidence_ref` is
        mandatory and its absence is rejected with
        `ERR_PHOTO_EVIDENCE_REQUIRED`."

        Design: Corner/cross_cutting_complexity_layers/photo_not_required_when_flag_off
        """
        community, buyer, rep = fx.setup_base(
            community_overrides={"cosmetic_photo_required": False}
        )
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Paint scuff")
        classified = validate_success(api.classify_deficiency_item(
            item["id"],
            {"classification": "COSMETIC", "estimated_repair_cost_cents": 500},
            make_rep_headers(rep["id"]),
        ))
        assert classified["status"] == "CLASSIFIED"
        assert classified["classification"] == "COSMETIC"


class TestReinspectionRepairCycle:
    def test_fail_loops_back_then_pass_verifies(self, api, manager_headers):
        """PRD §3.5: "Each passing item moves `READY_FOR_REINSPECTION` →
        `VERIFIED`, while each failing item drops back `READY_FOR_REINSPECTION`
        → `IN_REPAIR` — the repair loop is unbounded, and an item may cycle
        until it passes."

        Design: Difficulty/non_linear_state_machine/deficiency_reinspection_fail_repair_cycle
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"],
                             closing_date="2026-09-20T17:00:00Z")
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    system_key="PLUMBING", title="Kitchen trap leaks")
        fx.classify_deficiency(item["id"], rep["id"],
                               estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(item["id"], "COMPLETE_BEFORE_CLOSING")
        fx.move_item_to_ready_for_reinspection(item["id"], rep["id"])

        fx.reinspect_item(item["id"], home["id"], rep["id"],
                          "2026-08-26T10:00:00Z", "FAIL")
        after_fail = get_success_data(
            api.get_deficiency_item(item["id"], manager_headers)
        )
        assert after_fail["status"] == "IN_REPAIR", (
            f"FAIL must loop the item back to IN_REPAIR, got {after_fail['status']}"
        )

        # The loop re-enters READY_FOR_REINSPECTION and passes on visit two.
        fx.complete_repair(item["id"], make_rep_headers(rep["id"]))
        fx.reinspect_item(item["id"], home["id"], rep["id"],
                          "2026-08-27T10:00:00Z", "PASS")
        after_pass = get_success_data(
            api.get_deficiency_item(item["id"], manager_headers)
        )
        assert after_pass["status"] == "VERIFIED", (
            f"second-visit PASS must land in VERIFIED, got {after_pass['status']}"
        )

    def test_fail_loop_re_enters_ready_for_reinspection(self, api, manager_headers):
        """PRD §3.5: "A `CustomerCareRep` starts repair, moving the item
        `DECIDED` → `IN_REPAIR`, and later marks repair complete, moving it
        `IN_REPAIR` → `READY_FOR_REINSPECTION`; each step recomputes the home's
        open-item counts."
        PRD §3.5: "each failing item drops back `READY_FOR_REINSPECTION` →
        `IN_REPAIR` — the repair loop is unbounded, and an item may cycle
        until it passes."

        Design: Difficulty/non_linear_state_machine/deficiency_reinspection_fail_repair_cycle
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"],
                             closing_date="2026-09-20T17:00:00Z")
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    system_key="PLUMBING", title="Kitchen trap leaks")
        fx.classify_deficiency(item["id"], rep["id"],
                               estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(item["id"], "COMPLETE_BEFORE_CLOSING")
        fx.move_item_to_ready_for_reinspection(item["id"], rep["id"])
        fx.reinspect_item(item["id"], home["id"], rep["id"],
                          "2026-08-26T10:00:00Z", "FAIL")
        # After the FAIL loop-back, complete-repair returns the item to
        # READY_FOR_REINSPECTION for another attempt.
        resp = api.complete_repair(item["id"], make_rep_headers(rep["id"]))
        looped = validate_success(resp)
        assert looped["status"] == "READY_FOR_REINSPECTION", (
            f"complete-repair after the loop must re-enter READY_FOR_REINSPECTION, "
            f"got {looped['status']}"
        )

    def test_visit_complete_with_unready_item_rejected(self, api, manager_headers):
        """PRD §3.5: "Every entry in `results` must reference a `DeficiencyItem`
        of the same home currently in `READY_FOR_REINSPECTION`; any other
        reference is rejected with `ERR_INVALID_STATE`."

        Design: Corner/endpoints/visit_complete_with_unready_item_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Trap leak")
        fx.classify_deficiency(item["id"], rep["id"],
                               estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(item["id"], "COMPLETE_BEFORE_CLOSING")
        resp = api.start_repair(item["id"], make_rep_headers(rep["id"]))
        assert resp.status_code == 200, f"Setup failed (start-repair): {resp.text}"
        visit = fx.schedule_visit(home["id"], rep["id"], "2026-08-26T10:00:00Z")
        fx.set_clock("2026-08-26T10:00:00Z")
        validate_error(
            api.complete_reinspection_visit(
                visit["id"],
                {"results": [{"deficiency_item_id": item["id"], "outcome": "PASS"}]},
                make_rep_headers(rep["id"]),
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        visit = get_success_data(api.get_reinspection_visit(visit["id"], manager_headers))
        assert visit["status"] == "SCHEDULED", (
            f"failed completion must leave the visit SCHEDULED, got {visit['status']}"
        )

    def test_visit_complete_too_early_rejected(self, api):
        """PRD §3.5: "The representative submits a `results` array pairing
        deficiency items with their outcomes, allowed only once the logical
        clock has reached the visit's `scheduled_start` — an earlier attempt
        is rejected with `ERR_VISIT_TOO_EARLY`."

        Design: Corner/errors/visit_complete_too_early_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        visit = fx.schedule_visit(home["id"], rep["id"], "2026-08-26T10:00:00Z")
        # Logical clock untouched at the 2026-08-01 startup default.
        resp = api.complete_reinspection_visit(
            visit["id"], {"results": []}, make_rep_headers(rep["id"])
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_TOO_EARLY)


class TestVisitSchedulingRules:
    def test_half_open_adjacency_and_daily_capacity_cap(self, api):
        """PRD §3.5: "a new visit conflicts — and is rejected with
        `ERR_VISIT_OVERLAP` — only when it begins strictly before an existing
        visit ends while the existing visit begins strictly before the new one
        ends, so a visit starting at the exact moment another finishes is
        allowed. In aggregate, the durations of that representative's visits in
        `SCHEDULED` or `COMPLETED` falling on the same UTC calendar date, plus
        the new visit's duration, must not exceed
        `daily_visit_capacity_minutes`; a total exactly equal to the cap is
        allowed, while one minute beyond it is rejected with
        `ERR_DAILY_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/visit_half_open_adjacency_with_daily_capacity_cap
        """
        community, buyer, rep = fx.setup_base()  # default capacity 240
        home = fx.setup_home(community["id"], buyer["id"])
        # Back-to-back hourly visits: half-open adjacency must not conflict.
        fx.schedule_visit(home["id"], rep["id"], "2026-08-26T09:00:00Z")
        fx.schedule_visit(home["id"], rep["id"], "2026-08-26T10:00:00Z")
        fx.schedule_visit(home["id"], rep["id"], "2026-08-26T11:00:00Z")
        fourth = fx.schedule_visit(home["id"], rep["id"], "2026-08-26T12:00:00Z")
        assert fourth["status"] == "SCHEDULED", (
            f"the 4th visit reaching exactly 240 minutes must be allowed, got {fourth['status']}"
        )
        resp = api.create_reinspection_visit(
            {"home_id": home["id"], "rep_id": rep["id"],
             "scheduled_start": "2026-08-26T13:00:00Z", "duration_minutes": 60},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DAILY_CAPACITY_EXCEEDED)

    def test_completed_visits_count_toward_daily_capacity(self, api, manager_headers):
        """PRD §3.5: "In aggregate, the durations of that representative's
        visits in `SCHEDULED` or `COMPLETED` falling on the same UTC calendar
        date, plus the new visit's duration, must not exceed
        `daily_visit_capacity_minutes`; a total exactly equal to the cap is
        allowed, while one minute beyond it is rejected with
        `ERR_DAILY_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/visit_half_open_adjacency_with_daily_capacity_cap
        """
        community, buyer, rep = fx.setup_base()  # default capacity 240
        home = fx.setup_home(community["id"], buyer["id"])
        v1 = fx.schedule_visit(home["id"], rep["id"], "2026-08-26T09:00:00Z")
        fx.schedule_visit(home["id"], rep["id"], "2026-08-26T10:00:00Z")
        fx.schedule_visit(home["id"], rep["id"], "2026-08-26T11:00:00Z")
        # Completing the first visit (180 minutes already booked that day)
        # leaves its 60 minutes inside the aggregate: 240 - 180 = 60 remains.
        fx.complete_visit(v1["id"], rep["id"], [], clock_at="2026-08-26T09:00:00Z")
        ok = api.create_reinspection_visit(
            {"home_id": home["id"], "rep_id": rep["id"],
             "scheduled_start": "2026-08-26T13:00:00Z", "duration_minutes": 60},
            make_rep_headers(rep["id"]),
        )
        fourth = validate_success(ok, expected_status=201)
        assert fourth["status"] == "SCHEDULED", (
            f"60 more minutes reach exactly the 240 cap and must be allowed, "
            f"got {fourth['status']}"
        )
        resp = api.create_reinspection_visit(
            {"home_id": home["id"], "rep_id": rep["id"],
             "scheduled_start": "2026-08-26T14:00:00Z", "duration_minutes": 61},
            make_rep_headers(rep["id"]),
        )
        # 180 + 60 + 61 = 301 > 240: one minute beyond the cap is rejected.
        validate_error(resp, ApiErrorId.ERR_DAILY_CAPACITY_EXCEEDED)

    def test_visit_pairwise_overlap_rejected(self, api):
        """PRD §3.5: "Pairwise, each existing `SCHEDULED` visit of the same
        representative occupies a half-open interval from its start to its
        start plus duration: a new visit conflicts — and is rejected with
        `ERR_VISIT_OVERLAP` — only when it begins strictly before an existing
        visit ends while the existing visit begins strictly before the new one
        ends"

        Design: Corner/errors/visit_pairwise_overlap_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        fx.schedule_visit(home["id"], rep["id"], "2026-08-26T09:00:00Z")
        resp = api.create_reinspection_visit(
            {"home_id": home["id"], "rep_id": rep["id"],
             "scheduled_start": "2026-08-26T09:30:00Z", "duration_minutes": 60},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_OVERLAP)


class TestWithdrawalRules:
    def test_withdraw_warrantable_classified_rejected(self, api):
        """PRD §3.4: "From `CLASSIFIED`, only a `COSMETIC` item may be
        withdrawn — a `WARRANTABLE`-classified item, or any item already past
        `CLASSIFIED`, is rejected with `ERR_WITHDRAW_NOT_ALLOWED`."

        Design: Corner/state_machines/withdraw_warrantable_classified_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Trap leak")
        fx.classify_deficiency(item["id"], rep["id"],
                               estimated_repair_cost_cents=20_000)
        resp = api.withdraw_deficiency_item(item["id"], make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_WITHDRAW_NOT_ALLOWED)


class TestSignOffGate:
    def test_signoff_before_verified_rejected(self, api):
        """PRD §3.5: "Signing off moves a `VERIFIED` item to the terminal
        `SIGNED_OFF`"
        PRD §2.8: "State — the target entity is in a valid from-state for the
        requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/signoff_before_verified_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Trap leak")
        fx.classify_deficiency(item["id"], rep["id"],
                               estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(item["id"], "COMPLETE_BEFORE_CLOSING")
        resp = api.start_repair(item["id"], make_rep_headers(rep["id"]))
        assert resp.status_code == 200, f"Setup failed (start-repair): {resp.text}"
        resp = api.sign_off_deficiency_item(item["id"], make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDeficiencyPagination:
    def test_limit_offset_interact_with_home_filter(self, api, manager_headers):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; when omitted it defaults to 10, and it accepts values from a
        minimum of 1 to a maximum of 100. The `offset` parameter sets how many
        items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/deficiency_list_pagination_interaction
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        for title in ("Item A", "Item B", "Item C"):
            fx.create_deficiency(home["id"], appt["id"], rep["id"], title=title)

        page1, meta1 = validate_paginated(api.list_deficiency_items(
            manager_headers, params={"home_id": home["id"], "limit": 2}
        ))
        assert len(page1) == 2, f"page 1 must hold exactly 2 rows, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_deficiency_items(
            manager_headers, params={"home_id": home["id"], "limit": 2, "offset": 2}
        ))
        assert len(page2) == 1, f"page 2 must hold the 3rd row only, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestImmediateConsistency:
    def test_get_echoes_identified_item(self, api, manager_headers):
        """PRD §3.4: "The new item lands in `IDENTIFIED`"
        PRD §2.5: "All eleven resources — `Community`, `Homebuyer`,
        `CustomerCareRep`, `Home`, `OrientationAppointment`, `Attendee`,
        `DeficiencyItem`, `ReinspectionVisit`, `EscrowHoldback`,
        `AcknowledgmentSignature`, and `FeedbackSurvey` — carry a standard set
        of system-managed fields"

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        created = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                       title="Paint scuff")
        fetched = validate_success(api.get_deficiency_item(created["id"], manager_headers))
        assert fetched["title"] == "Paint scuff"
        assert fetched["title"] == created["title"]
        assert fetched["status"] == "IDENTIFIED"
        assert fetched["status"] == created["status"]
        assert fetched["home_id"] == home["id"]
        assert fetched["classification"] is None, (
            f"classification must be null until classified, got {fetched['classification']}"
        )
