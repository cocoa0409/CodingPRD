"""Role authorization, customer ownership scope, and optimistic concurrency."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_design_engineer_headers,
    make_customer_contact_headers,
    make_customer,
    make_engineer,
    make_job,
    make_design,
    make_sealed_design,
    submit_design,
    seal_submitted_design,
    make_lumber_lot,
    reserve_lumber,
    setup_exploded_list_with_lot,
    setup_sealed_roof_design,
    setup_change_order_requested,
    create_jig_payload,
    create_design_payload,
    create_change_order_payload,
    create_lumber_reservation_payload,
    change_order_fresh,
    lot_fresh,
    job_fresh,
)

PM = TEST_USERS["plant_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
IM = TEST_USERS["inventory_manager_headers"]
SFL = TEST_USERS["shop_floor_lead_headers"]
SC = TEST_USERS["shipping_coordinator_headers"]


class TestRoleAuthorization:
    def test_engineer_cannot_create_jig(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized list is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4: POST
        `/plant/jig-setups` — Create an immutable jig setup with its changeover
        matrix — is authorized for PlantManager only.

        Design: Corner/rbac/engineer_cannot_create_jig
        """
        eng = make_engineer("1")
        resp = api.create_jig_setup(create_jig_payload(setup_code="JIG-X"),
                                    make_design_engineer_headers(eng["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        _, meta = validate_paginated(api.list_jig_setups(PM))
        assert meta["total_count"] == 0

    def test_shop_floor_cannot_reserve(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized list is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4: POST
        `/plant/material-reservations` — Reserve lumber against a line or plates
        against a list — is authorized for ProductionPlanner only.

        Design: Corner/rbac/shop_floor_cannot_reserve
        """
        lot = make_lumber_lot(received_board_feet=500.0)
        resp = api.create_reservation(
            {"lot_id": lot["id"], "expected_lot_version": lot["version"],
             "reserved_bf": 10.0}, SFL)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert lot_fresh(lot["id"])["available_bf"] == pytest.approx(500.00), \
            "a role-rejected write leaves the lot untouched"

    def test_coordinator_cannot_assess_change_order(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized list is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4: POST
        `/plant/change-orders/{id}/assess` — `REQUESTED` to `IMPACT_ASSESSED` — is
        authorized for ProductionPlanner only.

        Design: Corner/rbac/coordinator_cannot_assess_change_order
        """
        ns = setup_change_order_requested(by_customer=False)
        resp = api.assess_change_order(ns.co1["id"], {}, SC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert change_order_fresh(ns.co1["id"])["status"] == "REQUESTED"


class TestCustomerOwnershipScope:
    def test_customer_forbidden_from_other_customers_job(self, api):
        """PRD §2.1: "a `CustomerContact` acting outside its own customer scope —
        creating a job for another customer, filing a claim against another customer's
        delivery, withdrawing another customer's change order, or reading another
        customer's jobs, designs, loads, claims, or change orders — is rejected with
        `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/customer_forbidden_from_other_customers_job
        """
        cust_a = make_customer(company_name="A Co")
        cust_b = make_customer(company_name="B Co")
        job_a = make_job(cust_a, job_name="A Job")
        resp = api.get_job(job_a["id"], make_customer_contact_headers(cust_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        ok = validate_success(api.get_job(job_a["id"], make_customer_contact_headers(cust_a["id"])))
        assert ok["id"] == job_a["id"], "the owning customer reads its own job"


class TestOptimisticConcurrency:
    def test_occ_reservation_stale_lot_version(self, api):
        """PRD §2.6: "`POST /plant/material-reservations` requires
        `expected_lot_version` matching the target lot's current `version`; a mismatch
        is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). Another writer may
        legitimately have created, consumed, or released a reservation against the
        same lot, mutating its availability, so the current writer's view of remaining
        availability is stale."

        Design: Corner/cross_cutting_complexity_layers/occ_reservation_stale_lot_version
        """
        ns = setup_exploded_list_with_lot(job_name="OCC Job")
        stale_version = ns.lot6["version"]
        r1 = reserve_lumber(ns.lot6["id"], ns.lines["TC-1"]["id"], 126.00)
        assert r1["status"] == "RESERVED"
        advanced = lot_fresh(ns.lot6["id"])
        assert advanced["version"] > stale_version, "the first write bumped the lot version"
        # Plenty of availability remains; the stale version alone rejects the write.
        resp = api.create_reservation(
            create_lumber_reservation_payload(ns.lot6["id"], stale_version,
                                              ns.lines["TC-1"]["id"], 10.0), PP)
        validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION)
        lot = lot_fresh(ns.lot6["id"])
        assert lot["version"] == advanced["version"], "the rejected write left no trace"
        assert lot["available_bf"] == pytest.approx(374.00)

    def test_occ_design_revision_stale_job_version(self, api):
        """PRD §2.6: "`POST /plant/jobs/{job_id}/designs` requires
        `expected_job_version` matching the target job's current `version`; a mismatch
        is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412). A new design revision
        legitimately coexists with — and is intended to supersede — the current sealed
        revision, so a sequential second create would otherwise succeed on a stale job
        view."

        Design: Corner/cross_cutting_complexity_layers/occ_design_revision_stale_job_version
        """
        cust = make_customer()
        eng = make_engineer("1")
        job = make_job(cust, job_name="OCC2 Job")
        stale_version = job["version"]
        confirmed = validate_success(api.confirm_job(job["id"], PM))
        assert confirmed["version"] > stale_version, "confirm increments the job version"
        resp = api.create_design(
            job["id"], create_design_payload(stale_version),
            make_design_engineer_headers(eng["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_JOB_VERSION)
        ok = get_success_data(api.create_design(
            job["id"], create_design_payload(job_fresh(job["id"])["version"]),
            make_design_engineer_headers(eng["id"])))
        assert ok["status"] == "DRAFT" and ok["revision_no"] == 1

    def test_occ_change_order_stale_job_version(self, api):
        """PRD §2.6: "`POST /plant/jobs/{job_id}/change-orders` likewise requires
        `expected_job_version`; a mismatch is rejected with `ERR_STALE_JOB_VERSION`
        (HTTP 412). A second change order against the same sealed design is a
        legitimate product operation, so the stale-view create is rejected to force
        the writer to re-read the job."

        Design: Corner/cross_cutting_complexity_layers/occ_change_order_stale_job_version
        """
        ns = setup_sealed_roof_design(job_name="OCC3 Job", contract=100000)
        stale_version = job_fresh(ns.job["id"])["version"]
        co1 = get_success_data(api.create_change_order(
            ns.job["id"], create_change_order_payload(ns.dsg1["id"], stale_version,
                                                      reason="first"), PP))
        assert co1["status"] == "REQUESTED"
        assert job_fresh(ns.job["id"])["version"] > stale_version, \
            "each change-order create increments the job's version"
        resp = api.create_change_order(
            ns.job["id"], create_change_order_payload(ns.dsg1["id"], stale_version,
                                                      reason="second"), PP)
        validate_error(resp, ApiErrorId.ERR_STALE_JOB_VERSION)
