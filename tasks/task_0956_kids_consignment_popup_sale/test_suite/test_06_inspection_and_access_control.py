"""Inspection audit trail, segregation of duties, and RBAC denials."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    book_and_check_in,
    create_event,
    create_item_for,
    create_slot,
    drop_off_item,
    get_item,
    make_consignor_headers,
    make_inspector_headers,
    make_volunteer_headers,
    open_intake,
    register_consignor,
    register_volunteer,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInspectionAuditTrail:

    def test_inspection_creates_audit_record(self, api, organizer_headers):
        """PRD §3.5: "Every inspection, pass or fail, creates an `InspectionRecord` naming the `item_id`, the `inspector_id` (taken from the inspector's `X-User-ID`), the `outcome`, and the `reasons`."
        PRD §3.5: "because records are immutable audit rows, they carry `id` and `created_at` only, with no `updated_at` or `version`."
        PRD §3.5: "A passing inspection moves the item `DROPPED_OFF` → `ACCEPTED`."

        Design: Corner/endpoints/inspection_creates_audit_record
        """
        event = create_event()
        open_intake(event["id"])
        consignor = register_consignor(event["id"], "Ann")
        slot = create_slot(event["id"])
        book_and_check_in(slot["id"], consignor["id"])
        item = create_item_for(consignor["id"], price_cents=500)
        drop_off_item(item["id"], consignor["id"])
        inspector = register_volunteer(event["id"], "Insp Ira")

        inspected = validate_success(
            api.inspect_item(item["id"], {"outcome": "PASS"},
                             make_inspector_headers(inspector["id"]))
        )
        assert inspected["status"] == "ACCEPTED"

        records, meta = validate_paginated(
            api.list_inspection_records(organizer_headers,
                                        params={"item_id": item["id"]})
        )
        assert meta["total_count"] == 1
        record = records[0]
        assert record["outcome"] == "PASS"
        assert record["inspector_id"] == inspector["id"], (
            "inspector_id must be taken from the acting Inspector's X-User-ID"
        )
        assert record["item_id"] == item["id"]
        assert "updated_at" not in record and "version" not in record, (
            "InspectionRecord is an audit row carrying only id and created_at"
        )


class TestSegregationOfDuties:

    def _setup_linked_inspector_past_deadline(self, api):
        """Event stuck in INTAKE_OPEN with the clock past presale_start; consignor
        Jo has a DROPPED_OFF item; volunteer Jo-Vol is linked to consignor Jo."""
        event = create_event()
        open_intake(event["id"])
        jo = register_consignor(event["id"], "Jo")
        jo_vol = register_volunteer(event["id"], "Jo Vol",
                                    linked_consignor_id=jo["id"])
        slot = create_slot(event["id"])
        book_and_check_in(slot["id"], jo["id"])
        item = create_item_for(jo["id"], price_cents=500)
        drop_off_item(item["id"], jo["id"])
        set_clock("2026-06-04T18:00:00Z")  # at/after presale_start (17:00)
        return event, jo, jo_vol, item

    def test_self_dealing_beats_inspection_deadline(self, api):
        """PRD §2.8: "sixth, segregation of duties on inspection (`ERR_INSPECTION_SELF_DEALING`); seventh, clock-window and interval rules (`ERR_INTAKE_WINDOW_CLOSED`, `ERR_INSPECTION_DEADLINE_PASSED`, `ERR_PICKUP_WINDOW_CLOSED`, `ERR_SHIFT_OVERLAP`, `ERR_INVALID_TIME_WINDOW`, `ERR_MARKDOWN_WINDOW_OVERLAP`, `ERR_NO_SHOW_TOO_EARLY`)".
        PRD §3.5: "If the acting volunteer's `linked_consignor_id` equals the item's `consignor_id`, the inspection is rejected with `ERR_INSPECTION_SELF_DEALING` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/self_dealing_beats_inspection_deadline
        """
        _event, _jo, jo_vol, item = self._setup_linked_inspector_past_deadline(api)
        resp = api.inspect_item(item["id"], {"outcome": "PASS"},
                                make_inspector_headers(jo_vol["id"]))
        validate_error(resp, ApiErrorId.ERR_INSPECTION_SELF_DEALING)
        assert resp.status_code == 403
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_INSPECTION_DEADLINE_PASSED, (
            "The segregation check (sixth) outranks the clock-window rule (seventh)"
        )
        assert get_item(item["id"])["status"] == "DROPPED_OFF"

    def test_self_dealing_rejected_before_deadline_too(self, api):
        """PRD §3.5: "If the acting volunteer's `linked_consignor_id` equals the item's `consignor_id`, the inspection is rejected with `ERR_INSPECTION_SELF_DEALING` (HTTP 403)."
        PRD §3.5: "the logical clock must sit strictly before `presale_start` — an inspection attempted at or after the presale opens is rejected with `ERR_INSPECTION_DEADLINE_PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/self_dealing_beats_inspection_deadline
        """
        event = create_event()
        open_intake(event["id"])
        jo = register_consignor(event["id"], "Jo")
        jo_vol = register_volunteer(event["id"], "Jo Vol",
                                    linked_consignor_id=jo["id"])
        slot = create_slot(event["id"])
        book_and_check_in(slot["id"], jo["id"])
        item = create_item_for(jo["id"], price_cents=500)
        drop_off_item(item["id"], jo["id"])
        # Clock remains 2026-06-01T10:00 inside intake — only self-dealing can fail.

        resp = api.inspect_item(item["id"], {"outcome": "PASS"},
                                make_inspector_headers(jo_vol["id"]))
        validate_error(resp, ApiErrorId.ERR_INSPECTION_SELF_DEALING)
        assert get_item(item["id"])["status"] == "DROPPED_OFF", (
            "A rejected inspection must not change the item's state"
        )


class TestAccessControl:

    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400) before any other evaluation."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        create_event()
        resp = api.list_sale_events(headers=None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)

    def test_consignor_cannot_create_shift_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        The PRD §4 endpoint table authorizes POST /volunteer-shifts for EventOrganizer only.

        Design: Corner/validations/consignor_cannot_create_shift_forbidden
        """
        event = create_event()
        consignor = register_consignor(event["id"], "Ann")
        resp = api.create_volunteer_shift(
            {"sale_event_id": event["id"], "role_name": "Floor",
             "start_time": "2026-05-28T09:00:00Z",
             "end_time": "2026-05-28T13:00:00Z", "capacity": 5},
            make_consignor_headers(consignor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_consignor_cannot_drop_off_other_consignors_item(self, api, organizer_headers):
        """PRD §2.1: "When `X-User-Role` is `Consignor`, `X-User-ID` is the `id` of the acting `Consignor`; ownership checks on any resource that references a `Consignor` compare the resource's foreign-key field (such as `consignor_id`, whether it arrives in the path or the body) to `X-User-ID`. A consignor may act only on their own items, bookings, and settlements."

        Design: Corner/validations/consignor_cannot_drop_off_other_consignors_item
        """
        event = create_event()
        open_intake(event["id"])
        ann = register_consignor(event["id"], "A")
        bob = register_consignor(event["id"], "B")
        slot = create_slot(event["id"], capacity=5)
        book_and_check_in(slot["id"], bob["id"])  # B holds a CHECKED_IN booking
        item_a = create_item_for(ann["id"], price_cents=500, title="A item")

        resp = api.drop_off_item(item_a["id"], make_consignor_headers(bob["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_item(item_a["id"])["status"] == "TAGGED"

    def test_volunteer_role_cannot_inspect(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        The PRD §4 endpoint table authorizes POST /items/{id}/inspect for Inspector only.

        Design: Corner/rbac/volunteer_cannot_inspect_role_forbidden
        """
        event = create_event()
        sam = register_volunteer(event["id"], "Sam")
        resp = api.inspect_item(NON_EXISTENT_UUID, {"outcome": "PASS"},
                                make_volunteer_headers(sam["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_cashier_cannot_finalize_settlement(self, api, cashier_headers):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        The PRD §4 endpoint table authorizes POST /settlements/{id}/finalize for EventOrganizer only.

        Design: Corner/rbac/cashier_cannot_finalize_settlement_forbidden
        """
        create_event()
        resp = api.finalize_settlement(NON_EXISTENT_UUID, cashier_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
