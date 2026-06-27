"""Entity creation/defaults/validation, reverse-reachability listings, and RBAC.
"""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_claim,
    create_job,
    create_unit,
    create_chamber_payload,
    create_placement_payload,
    setup_dispatched_job,
    setup_job_with_chamber,
)
from test_helpers.fixtures import (
    DISPATCHER,
    ESTIMATOR,
    ADJUSTER,
    ADMIN,
)
from test_helpers.test_users import make_technician_headers


# ===========================================================================
# Entity creation / defaults / required fields (Corner/entities)
# ===========================================================================
class TestEntityCreation:
    def test_create_claim_defaults(self):
        """PRD §3.1: "On creation the claim's `status` is `OPEN`, its
        `settled_estimate_id` is null, and `adjuster_user_id` is set to the
        `X-User-ID` of the acting adjuster".
        PRD §2.4: "`version` — an integer that begins at 1 on creation".

        Design: Corner/entities/create_claim_returns_201_with_system_fields
        """
        resp = api.create_claim(
            {"carrier_name": "Acme", "policy_number": "PC1", "peril": "WATER",
             "coverage_limit_cents": 100000},
            ADJUSTER,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "OPEN"
        assert data["settled_estimate_id"] is None
        assert data["version"] == 1

    def test_create_job_missing_water_category_rejected(self):
        """PRD §3.1: "When the loss type is `WATER`, the payload must also carry the
        `water_category` ... and the `water_class` ...; both are required for a
        water loss and are rejected as `ERR_INVALID_REQUEST` if missing."

        Design: Corner/entities/create_job_missing_water_category_returns_invalid_request
        """
        claim = create_claim()
        resp = api.create_job(
            {"claim_id": claim["id"], "property_address": "X", "loss_type": "WATER"},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_job_category3_computes_antimicrobial(self):
        """PRD §3.1: "`antimicrobial_required` is set to true when the water
        category is 3, or when the loss type is `FIRE` or `SMOKE`; otherwise it is
        false."

        Design: Corner/entities/create_job_computes_antimicrobial_required_for_category3
        """
        claim = create_claim()
        resp = api.create_job(
            {"claim_id": claim["id"], "property_address": "X", "loss_type": "WATER",
             "water_category": 3, "water_class": 3},
            DISPATCHER,
        )
        data = validate_success(resp, 201)
        assert data["antimicrobial_required"] is True

    def test_create_job_invalid_loss_type_rejected(self):
        """PRD §2.9: "A job's `loss_type` is one of `WATER`, `FIRE`, or `SMOKE`."
        PRD §2.9: "the system rejects any out-of-enumeration value with
        `ERR_INVALID_REQUEST` (HTTP 422)".

        Design: Corner/entities/create_job_invalid_enum_loss_type_returns_invalid_request
        """
        claim = create_claim()
        resp = api.create_job(
            {"claim_id": claim["id"], "property_address": "X", "loss_type": "FLOOD"},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_nonexistent_job_not_found(self):
        """PRD §2.6: "The system resolves path identifiers left to right and
        rejects the request with `ERR_NOT_FOUND` at the first identifier that names
        no existing resource, before evaluating any body content or business rule."

        Design: Corner/entities/get_job_nonexistent_returns_not_found
        """
        resp = api.get_job(NON_EXISTENT_UUID, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_job_unknown_claim_reference_not_found(self):
        """PRD §2.6: "When a create, dispatch, or placement request carries a
        reference such as `claim_id`, `job_id`, `chamber_id`, `equipment_unit_id`,
        or `technician_id` that names no existing resource, the request is rejected
        with `ERR_REFERENCE_NOT_FOUND`."

        Design: Corner/entities/create_job_unknown_claim_returns_reference_not_found
        """
        resp = api.create_job(
            {"claim_id": NON_EXISTENT_UUID, "property_address": "X", "loss_type": "WATER",
             "water_category": 1, "water_class": 1},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)

    def test_equipment_unit_defaults_available(self):
        """PRD §3.1: "a newly registered unit's `status` is `AVAILABLE` with
        `active_placement_id` null."

        Design: Corner/entities/equipment_unit_create_defaults_available
        """
        resp = api.create_equipment_unit(
            {"asset_tag": "AM-C", "kind": "AIR_MOVER"}, ADMIN
        )
        data = validate_success(resp, 201)
        assert data["status"] == "AVAILABLE"
        assert data["active_placement_id"] is None


# ===========================================================================
# Reverse-reachability listings (Corner/endpoints)
# ===========================================================================
class TestListings:
    def test_list_chambers_filtered_by_job(self):
        """PRD §3.3: "Chambers can be retrieved individually or listed with filters
        by `job_id` or `status`."
        PRD §2.3: "Every list response includes these four fields inside the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_chambers_filtered_by_job_id
        """
        ctx = setup_dispatched_job(certification="WRT")
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        get_success_data(api.create_chamber(create_chamber_payload(job_id, room_label="R1"), tech_hdr))
        get_success_data(api.create_chamber(create_chamber_payload(job_id, room_label="R2"), tech_hdr))
        data, meta = validate_paginated(api.list_chambers(tech_hdr, params={"job_id": job_id}))
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert all(c["job_id"] == job_id for c in data)

    def test_list_placements_filtered_by_equipment_unit(self):
        """PRD §3.4: "Placements can be retrieved individually or listed, filtered
        by `job_id`, `chamber_id`, `equipment_unit_id`, or `status`."

        Design: Corner/endpoints/list_placements_reverse_reachable_by_equipment_unit
        """
        ctx = setup_job_with_chamber(certification="ASD")
        job_id = ctx["job"]["id"]
        ch_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        unit = create_unit(asset_tag="RR-AM", kind="AIR_MOVER")
        pl = get_success_data(
            api.create_placement(create_placement_payload(job_id, ch_id, unit["id"]), tech_hdr)
        )
        data, meta = validate_paginated(
            api.list_placements(tech_hdr, params={"equipment_unit_id": unit["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == pl["id"]


# ===========================================================================
# RBAC (Corner/rbac)
# ===========================================================================
class TestRbac:
    def test_estimator_cannot_dispatch(self):
        """PRD §2.1: "A request whose role is not permitted to perform the
        requested operation is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/estimator_cannot_dispatch_job
        """
        claim = create_claim()
        tech = get_success_data(
            api.create_technician({"full_name": "T", "certification": "WRT"}, ADMIN)
        )
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        resp = api.dispatch_job(job["id"], {"technician_id": tech["id"]}, ESTIMATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_technician_cannot_approve_estimate(self):
        """PRD §2.1: "A request whose role is not permitted to perform the
        requested operation is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/technician_cannot_approve_estimate
        """
        from test_helpers import create_estimate_payload
        claim = create_claim(coverage_limit_cents=9_000_000)
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        est = get_success_data(
            api.create_estimate(
                create_estimate_payload(job["id"], job["version"], estimated_drying_days=1,
                                        line_items=[{"qty": 1, "unit_price_cents": 5000}]),
                ESTIMATOR,
            )
        )
        resp = api.approve_estimate(est["id"], make_technician_headers("tech-x"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_missing_headers_unauthenticated(self):
        """PRD §2.1: "Every request to the API must carry two mandatory headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
        operational capacity under which they act. A request missing either header
        is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_headers_returns_unauthenticated
        """
        resp = api.list_jobs(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
