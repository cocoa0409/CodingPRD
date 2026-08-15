"""Role-based access control and segregation-of-duties enforcement."""
from test_helpers import ApiErrorId, validate_error, validate_paginated, validate_success
from test_helpers.factories import create_photo_evidence_payload
from test_helpers.fixtures import (
    assign_work_order,
    create_bid,
    create_damage_report,
    create_inspection,
    create_work_order,
    setup_bid_requested_report,
    setup_portfolio,
    start_work_order,
    submit_bid,
    submit_work_order,
    upload_minimum_photos,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_field_crew_headers,
    make_quality_reviewer_headers,
    make_servicer_headers,
)

ADMIN = TEST_USERS["vendor_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestEndpointRoleGates:
    def test_dispatcher_cannot_approve_work_order_forbidden(self, api):
        """PRD: "The caller's role must be listed for the endpoint, and
        entity-backed ownership rules must hold — a `FieldCrew` caller acts as their
        own crew's `id`, a `Servicer` caller acts on their own properties' invoices
        and bids — or the request fails with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        and the endpoint catalogue lists work-order approve as "QA approves
        submission (SUBMITTED to APPROVED) | QualityReviewer".

        Design: Corner/rbac/dispatcher_cannot_approve_work_order_forbidden
        """
        ctx = setup_portfolio(item_code="GRASS_CUT")
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="GRASS_CUT", due_date="2026-08-08")
        assign_work_order(wo["id"], ctx["crew_id"], scheduled_date="2026-08-02")
        start_work_order(wo["id"], ctx["crew_id"])
        upload_minimum_photos(wo["id"], "GRASS_CUT", ctx["crew_id"], hash_prefix="rbac1")
        submit_work_order(wo["id"], ctx["crew_id"], 1000)
        resp = api.approve_work_order(wo["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        after = validate_success(api.get_work_order(wo["id"], ADMIN))
        assert after["status"] == "SUBMITTED", "the denied call changes nothing"

    def test_fieldcrew_cannot_assign_forbidden(self, api):
        """PRD: "The caller's role must be listed for the endpoint, and
        entity-backed ownership rules must hold — a `FieldCrew` caller acts as their
        own crew's `id`, a `Servicer` caller acts on their own properties' invoices
        and bids — or the request fails with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        and the catalogue lists assign as "Assign a crew and schedule date (ISSUED
        to ASSIGNED) | Dispatcher".

        Design: Corner/rbac/fieldcrew_cannot_assign_forbidden
        """
        ctx = setup_portfolio(item_code="INSPECTION", allowable_overrides={
            "max_per_occurrence_cents": 5000, "max_occurrences_per_calendar_year": 30,
            "aggregate_cap_cents_per_property_year": 100000})
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="INSPECTION", due_date="2026-08-09")
        resp = api.assign_work_order(
            wo["id"], {"crew_id": ctx["crew_id"], "scheduled_date": "2026-08-03"},
            make_field_crew_headers(ctx["crew_id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_servicer_cannot_record_inspection_forbidden(self, api):
        """PRD: "The caller's role must be listed for the endpoint, and
        entity-backed ownership rules must hold — a `FieldCrew` caller acts as their
        own crew's `id`, a `Servicer` caller acts on their own properties' invoices
        and bids — or the request fails with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        and the catalogue lists inspection record as "Record findings; VACANT
        completes, OCCUPIED and INDETERMINATE go to VERIFICATION_PENDING |
        FieldCrew".

        Design: Corner/rbac/servicer_cannot_record_inspection_forbidden
        """
        ctx = setup_portfolio(with_allowable=False, with_crew=False,
                              property_overrides={"heating_system": "NONE", "fixture_count": 4})
        ins = create_inspection(ctx["property_id"], due_date="2026-08-03")
        resp = api.record_inspection(
            ins["id"],
            {"occupancy_determination": "VACANT", "interior_access": False,
             "personal_property_present": False},
            make_servicer_headers(ctx["servicer_id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_vendoradmin_cannot_approve_bid_forbidden(self, api):
        """PRD: "The caller's role must be listed for the endpoint, and
        entity-backed ownership rules must hold — a `FieldCrew` caller acts as their
        own crew's `id`, a `Servicer` caller acts on their own properties' invoices
        and bids — or the request fails with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        and the catalogue lists bid approve as "Servicer approves a bid; spawns
        DAMAGE_REPAIR work order and rejects competing open bids | Servicer".

        Design: Corner/rbac/vendoradmin_cannot_approve_bid_forbidden
        """
        ctx = setup_bid_requested_report(damage_overrides={"damage_type": "THEFT",
                                                           "severity": "MODERATE",
                                                           "is_interior": True,
                                                           "description": "appliances stolen"})
        b = create_bid(ctx["damage_report_id"], ctx["crew_id"], 55000,
                       ctx["damage_report_version"])
        submit_bid(b["id"], ctx["crew_id"])
        resp = api.approve_bid(b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        after = validate_success(api.get_bid(b["id"], ADMIN))
        assert after["status"] == "SUBMITTED", "the denied call changes nothing"


class TestSegregationOfDuties:
    def test_sod_flag_clear_own_rejected(self, api):
        """PRD: "Clearing a flag is likewise a `QualityReviewer` action, but
        segregation of duties forbids self-clearance: the clearing reviewer's
        `X-User-ID` must differ from the `flagged_by_user_id` on the photo, or the
        clear is rejected with `ERR_SOD_FLAG_CLEAR`."

        Design: Corner/rbac/sod_flag_clear_own_rejected
        """
        ctx = setup_portfolio(with_allowable=False,
                              property_overrides={"heating_system": "NONE", "fixture_count": 4})
        dr = create_damage_report(ctx["property_id"], ctx["crew_id"],
                                  damage_type="VANDALISM", description="graffiti")
        photo = validate_success(api.create_photo_evidence(
            create_photo_evidence_payload(damage_report_id=dr["id"],
                                          category="DAMAGE_CLOSEUP",
                                          taken_at="2026-08-01T10:00:00Z",
                                          content_hash="sod-p1"),
            make_field_crew_headers(ctx["crew_id"])), expected_status=201)
        qa1 = make_quality_reviewer_headers("qa-1")
        qa2 = make_quality_reviewer_headers("qa-2")
        validate_success(api.flag_photo(photo["id"], {"reason": "no scale reference"}, qa1))
        own = api.clear_photo_flag(photo["id"], qa1)
        validate_error(own, ApiErrorId.ERR_SOD_FLAG_CLEAR)
        cleared = validate_success(api.clear_photo_flag(photo["id"], qa2))
        assert cleared["flagged"] is False, "a different reviewer clears successfully"
