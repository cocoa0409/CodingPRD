"""Validation violations: auth headers, duplicate jurisdiction code, return
counts, photo documentation, item linkage, and unassessed items."""
import test_helpers as th
from test_helpers import (
    ApiErrorId,
    add_item,
    api_client,
    complete_inspection,
    create_inspection_item_payload,
    create_jurisdiction,
    create_jurisdiction_profile_payload,
    create_property,
    create_tenancy,
    create_unit,
    get_success_data,
    get_tenancy,
    make_inspector_headers,
    make_manager_admin_headers,
    make_property_manager_headers,
    schedule_inspection,
    setup_notice_given,
    setup_occupied_tenancy,
    validate_error,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()
INSP = make_inspector_headers()


class TestMissingAuthHeaders:
    def test_missing_auth_headers_rejected(self):
        """PRD §2.1: "Each request must include `X-User-ID` to identify the
        acting user and `X-User-Role` to specify their operational capacity."
        and "A request whose headers are missing or malformed is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        A request with no auth headers fails even when the payload is valid.

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api_client.create_jurisdiction_profile(
            create_jurisdiction_profile_payload(interest_required=False,
                                                annual_interest_rate_bp=0),
            headers=None,
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestDuplicateJurisdictionCode:
    def test_duplicate_jurisdiction_code_rejected(self):
        """PRD §2.10: "A `JurisdictionProfile` captures, under a unique `code`
        (attempting to register a duplicate code is rejected with
        `ERR_DUPLICATE_JURISDICTION_CODE`)".

        The second profile with code CA-ACT fails.

        Design: Corner/validations/duplicate_jurisdiction_code_rejected
        """
        create_jurisdiction(interest_required=False, annual_interest_rate_bp=0)
        resp = api_client.create_jurisdiction_profile(
            create_jurisdiction_profile_payload(
                code="CA-ACT", deposit_return_deadline_days=30,
                dispute_window_days=10, interest_required=True,
                annual_interest_rate_bp=100, interest_basis="WHOLE_YEARS",
                stale_check_days=90, small_claims_cap_cents=500_000,
                bad_faith_multiplier=3, lock_change_allowed=False,
                allow_actual_cost_charge=True),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_JURISDICTION_CODE)


class TestReturnCountExceedsIssued:
    def test_return_count_exceeds_issued_rejected(self):
        """PRD §3.3: "A returned count that exceeds the corresponding issued
        count is rejected with `ERR_RETURN_COUNT_EXCEEDS_ISSUED`."

        Recording keys_returned 3 when keys_issued == 2 fails (422); counts
        unchanged.

        Design: Corner/validations/return_count_exceeds_issued_rejected
        """
        ctx = setup_occupied_tenancy()
        ten = ctx["tenancy"]
        assert ten["keys_issued"] == 2
        resp = api_client.record_key_return(
            ten["id"], {"keys_returned": 3, "fobs_returned": 0}, PM)
        validate_error(resp, ApiErrorId.ERR_RETURN_COUNT_EXCEEDS_ISSUED)
        assert get_tenancy(ten["id"])["keys_returned"] == 0


class TestPhotoDocumentation:
    def test_photo_documentation_required_rejected(self):
        """PRD §3.2: "Photographic evidence is mandatory for anything below
        move-in-ready: an item whose condition is `WORN`, `DAMAGED`, or
        `MISSING` must carry a `photo_count` of at least one, or the item
        write is rejected with `ERR_PHOTO_DOCUMENTATION_REQUIRED`."

        A WORN item with photo_count 0 fails (422) at creation.

        Design: Corner/validations/photo_documentation_required_rejected
        """
        # Tenancy PENDING_MOVE_IN + DRAFT MOVE_IN inspection.
        jur = create_jurisdiction(interest_required=False, annual_interest_rate_bp=0)
        prop = create_property(jur["id"])
        unit = create_unit(prop["id"])
        ten = create_tenancy(unit["id"], lease_start_on="2026-09-01",
                             lease_end_on="2027-09-01")
        mi = schedule_inspection(ten["id"], "MOVE_IN",
                                 scheduled_start_at="2026-09-01T09:00:00Z",
                                 scheduled_end_at="2026-09-01T10:00:00Z")
        resp = api_client.add_inspection_item(
            mi["id"],
            create_inspection_item_payload(area_name="hallway_paint",
                                           category="PAINT", condition="WORN",
                                           photo_count=0),
            INSP,
        )
        validate_error(resp, ApiErrorId.ERR_PHOTO_DOCUMENTATION_REQUIRED)


class TestItemLinkMismatch:
    def test_item_link_mismatch_rejected(self):
        """PRD §3.2: "Move-out items may point back through
        `linked_move_in_item_id` to the matching item from the same tenancy's
        `COMPLETED` move-in inspection; a link pointing anywhere else — an
        item of another tenancy, or of an inspection that never reached
        `COMPLETED` — is rejected with `ERR_ITEM_LINK_MISMATCH`."

        A MOVE_OUT item on tenancy A linked to tenancy B's move-in item
        fails (409).

        Design: Corner/validations/item_link_mismatch_rejected
        """
        api_client.set_clock({"to_iso8601": "2025-01-10T00:00:00Z"}, ADMIN)
        jur = create_jurisdiction()
        prop = create_property(jur["id"])
        unit_a = create_unit(prop["id"], unit_number="1A")
        unit_b = create_unit(prop["id"], unit_number="1B")
        ten_a = create_tenancy(unit_a["id"], tenant_display_name="T A")
        ten_b = create_tenancy(unit_b["id"], tenant_display_name="T B")
        mi_a = schedule_inspection(ten_a["id"], "MOVE_IN")
        complete_inspection(mi_a["id"])
        mi_b = schedule_inspection(ten_b["id"], "MOVE_IN")
        mi_item_b = add_item(mi_b["id"], area_name="carpet", category="CARPET",
                             condition="GOOD", photo_count=2)
        complete_inspection(mi_b["id"])
        api_client.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN)
        get_success_data(api_client.give_notice(ten_a["id"], PM))
        mo_a = schedule_inspection(ten_a["id"], "MOVE_OUT")
        resp = api_client.add_inspection_item(
            mo_a["id"],
            create_inspection_item_payload(
                area_name="carpet", category="CARPET", condition="DAMAGED",
                photo_count=3, determination="TENANT_DAMAGE",
                linked_move_in_item_id=mi_item_b["id"],
                replacement_cost_cents=182_500),
            INSP,
        )
        validate_error(resp, ApiErrorId.ERR_ITEM_LINK_MISMATCH)


class TestUnassessedItemBlocksCompletion:
    def test_unassessed_item_blocks_completion(self):
        """PRD §3.4: "every single item must have been assessed — a
        `determination` still reading `UNASSESSED` blocks completion with
        `ERR_ITEM_NOT_ASSESSED`".

        MOVE_OUT completion with one UNASSESSED item fails (409); the tenancy
        stays NOTICE_GIVEN and the inspection stays DRAFT.

        Design: Corner/validations/unassessed_item_blocks_completion
        """
        ctx = setup_notice_given()
        mo = schedule_inspection(ctx["tenancy"]["id"], "MOVE_OUT")
        add_item(mo["id"], area_name="kitchen_floor", category="OTHER",
                 condition="FAIR", photo_count=1)  # no determination => UNASSESSED
        resp = api_client.complete_inspection(mo["id"], INSP)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_ASSESSED)
        assert get_tenancy(ctx["tenancy"]["id"])["status"] == "NOTICE_GIVEN"
        data = get_success_data(api_client.get_inspection(mo["id"], PM))
        assert data["status"] == "DRAFT"
