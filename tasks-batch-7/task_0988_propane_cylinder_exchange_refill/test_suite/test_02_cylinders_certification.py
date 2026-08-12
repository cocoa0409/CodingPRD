"""Cylinder registration, certification cycle, and the condemn cascade (PRD §2.4, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_cylinder,
    condemn_cylinder,
    create_cylinder_payload,
    create_site,
    create_technician,
    get_site,
    make_technician_headers,
    record_certification,
    register_fleet_cylinders,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK1 = TEST_USERS["site_clerk_headers"]


class TestCylinderRegistration:
    def test_cylinder_registration_computes_initial_certification(self, api):
        """PRD §3.2: "Registration also initializes the certification ledger on the cylinder itself: `cert_status` begins `CERTIFIED`, `certified_on` is set to the `manufacture_date`, `cert_method_last` begins `INITIAL`, and `certification_expires_on` is the manufacture date advanced by twelve years."

        Design: Corner/entities/cylinder_registration_computes_initial_certification
        """
        res = api.create_cylinder(
            create_cylinder_payload(
                serial_number="SN-INIT", owner_kind="FLEET",
                manufacture_date="2020-01-15", initial_fill="FULL",
            ),
            ADMIN,
        )
        cyl = validate_success(res, 201)
        assert_cylinder(cyl)
        assert cyl["certified_on"] == "2020-01-15"
        assert cyl["certification_expires_on"] == "2032-01-15", "manufacture date + 12 years"
        assert cyl["cert_method_last"] == "INITIAL"
        assert cyl["cert_status"] == "CERTIFIED"
        assert cyl["fill_status"] == "FULL"

    def test_customer_cylinder_with_site_rejected(self, api):
        """PRD §3.2: "customer cylinders must always be registered with `current_site_id` null, since a customer bottle lives with its owner — a customer cylinder created with a site is rejected with `ERR_VALIDATION`."

        Design: Corner/entities/customer_cylinder_with_site_rejected
        """
        site = create_site(name="S")
        res = api.create_cylinder(
            create_cylinder_payload(
                serial_number="SN-CUST", owner_kind="CUSTOMER", initial_fill="EMPTY",
                current_site_id=site["id"],
            ),
            CLERK1,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


class TestCertificationExpiryBoundary:
    def test_certification_expiry_day_still_certified(self, api):
        """PRD §2.4: "On the calendar date equal to `certification_expires_on` itself the cylinder remains `CERTIFIED` through end of day; the sweep is strictly-greater only."
        PRD §3.2: "certification_expires_on` is the manufacture date advanced by twelve years."

        Design: Difficulty/boundary_precision_check/certification_expiry_day_still_certified
        """
        cyl = register_fleet_cylinders(count=1, manufacture_date="2014-06-01",
                                       serial_prefix="FE")[0]
        assert cyl["certification_expires_on"] == "2026-06-01"
        advance_clock("2026-06-01T00:00:00Z")  # exactly the expiry date
        read = validate_success(api.get_cylinder(cyl["id"], ADMIN), 200)
        assert read["cert_status"] == "CERTIFIED"

    def test_certification_day_after_expiry_flips_recert_due(self, api):
        """PRD §2.4: "Advancing the clock triggers the certification sweep described in §3.2: every cylinder whose `cert_status` is `CERTIFIED` and whose `certification_expires_on` is strictly before the new current date flips to `RECERT_DUE`."

        Design: Difficulty/boundary_precision_check/certification_expiry_day_still_certified
        """
        cyl = register_fleet_cylinders(count=1, manufacture_date="2014-06-01",
                                       serial_prefix="FE")[0]
        advance_clock("2026-06-02T00:00:00Z")  # one day past the 2026-06-01 expiry
        read = validate_success(api.get_cylinder(cyl["id"], ADMIN), 200)
        assert read["cert_status"] == "RECERT_DUE"


class TestRecertificationCycle:
    def test_recert_due_to_certified_cycle(self, api):
        """PRD §3.2: "A `PASS` outcome is immediately effective: the record lands in `RECORDED` status, `performed_on` is stamped with the current logical date, the cylinder's prior expiry is snapshotted into `previous_expires_on`, and `new_expires_on` is computed as `performed_on` advanced by five years for a `VISUAL` recertification or seven years for a `HYDROSTATIC` one."
        PRD §3.2: "The cylinder's `certified_on`, `certification_expires_on`, and `cert_method_last` are updated to match, and its `cert_status` becomes `CERTIFIED` — this holds both for a voluntary recertification of an already-`CERTIFIED` cylinder and for curing a `RECERT_DUE` one."

        Design: Difficulty/non_linear_state_machine/cylinder_recert_due_to_certified_cycle
        """
        cyl = register_fleet_cylinders(count=1, manufacture_date="2014-06-01",
                                       serial_prefix="FC")[0]
        tech = create_technician(cert_level="FULL", name="Tech One")
        advance_clock("2026-06-02T00:00:00Z")  # past 2026-06-01 expiry
        mid = validate_success(api.get_cylinder(cyl["id"], ADMIN), 200)
        assert mid["cert_status"] == "RECERT_DUE"

        record = record_certification(cyl["id"], tech, method="VISUAL", outcome="PASS")
        assert record["status"] == "RECORDED"
        assert record["new_expires_on"] == "2031-06-02", "performed 2026-06-02 + 5 years"
        after = validate_success(api.get_cylinder(cyl["id"], ADMIN), 200)
        assert after["cert_status"] == "CERTIFIED"
        assert after["certified_on"] == "2026-06-02"
        assert after["cert_method_last"] == "VISUAL"
        assert after["certification_expires_on"] == "2031-06-02"
        assert after["fill_status"] == "FULL", "fill dimension is untouched by the cert cycle"

    def test_voluntary_recert_of_certified_cylinder(self, api):
        """PRD §3.2: "The cylinder's `certified_on`, `certification_expires_on`, and `cert_method_last` are updated to match, and its `cert_status` becomes `CERTIFIED` — this holds both for a voluntary recertification of an already-`CERTIFIED` cylinder and for curing a `RECERT_DUE` one."
        PRD §3.2: "`new_expires_on` is computed as `performed_on` advanced by five years for a `VISUAL` recertification or seven years for a `HYDROSTATIC` one."

        Design: Difficulty/non_linear_state_machine/cylinder_recert_due_to_certified_cycle
        """
        cyl = register_fleet_cylinders(count=1, serial_prefix="FV")[0]
        assert cyl["cert_status"] == "CERTIFIED"
        tech = create_technician(cert_level="FULL", name="Voluntary Tech")
        record = record_certification(cyl["id"], tech, method="HYDROSTATIC", outcome="PASS")
        assert record["status"] == "RECORDED"
        # performed at the startup logical date 2026-05-01; HYDROSTATIC adds 7 years.
        assert record["performed_on"] == "2026-05-01"
        assert record["new_expires_on"] == "2033-05-01"
        after = validate_success(api.get_cylinder(cyl["id"], ADMIN), 200)
        assert after["cert_status"] == "CERTIFIED"
        assert after["cert_method_last"] == "HYDROSTATIC"
        assert after["certification_expires_on"] == "2033-05-01"


class TestCondemnation:
    def test_condemned_cylinder_certification_lockdown(self, api):
        """PRD §3.2: "Condemnation is terminal: a `CONDEMNED` cylinder can never be filled, accepted as a return, or certified again — any such attempt is rejected with `ERR_CYLINDER_CONDEMNED`."

        Design: Corner/state_machines/condemned_cylinder_certification_lockdown
        """
        cyl = register_fleet_cylinders(count=1, manufacture_date="2014-06-01",
                                       fill="EMPTY", serial_prefix="CD")[0]
        t1 = create_technician(cert_level="FULL", name="T1")
        t2 = create_technician(cert_level="FULL", name="T2")
        condemn_cylinder(cyl["id"], t1, t2)
        res = api.create_certification_record(
            {"cylinder_id": cyl["id"], "method": "HYDROSTATIC", "outcome": "PASS"},
            make_technician_headers(t1["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CYLINDER_CONDEMNED, expected_status=409)

    def test_condemn_confirm_inventory_alert_chain(self, api):
        """PRD §3.2: "On confirmation the record becomes `CONFIRMED`, `confirmer_technician_id` is set, and a three-hop cascade fires: first the cylinder's `cert_status` becomes `CONDEMNED`; second, because the cylinder has left the sellable population, its former site's cage counts recompute; third, if the cylinder had been `FULL` at a site and the recomputed `full_on_hand` now sits at or below the site's `reorder_floor_full`, the site's `restock_alert` flips to true."
        PRD §2.8: "condemned cylinders are excluded from all three regardless of fill state."

        Design: Difficulty/transitive_cascade/condemn_confirm_inventory_alert_chain
        """
        site = create_site(name="Condemn Site")  # par 12 -> reorder_floor 6
        cyls = register_fleet_cylinders(site_id=site["id"], count=7, fill="FULL",
                                        serial_prefix="FD")
        condemned = cyls[0]
        t1 = create_technician(cert_level="FULL", name="Tech One")
        t2 = create_technician(cert_level="FULL", name="Tech Two")
        before = get_site(site["id"])
        assert before["full_on_hand"] == 7
        assert before["restock_alert"] is False, "7 > floor 6"

        record = record_certification(condemned["id"], t1, method="VISUAL",
                                      outcome="CONDEMN", note="dent at collar")
        assert record["status"] == "PENDING_SECOND"
        confirmed = validate_success(
            api.confirm_certification_record(record["id"], {},
                                             make_technician_headers(t2["id"])),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"
        cyl_after = validate_success(api.get_cylinder(condemned["id"], ADMIN), 200)
        assert cyl_after["cert_status"] == "CONDEMNED"
        after = get_site(site["id"])
        assert after["full_on_hand"] == 6, "CONDEMNED excluded from the counts"
        assert after["restock_alert"] is True, "6 <= 6, inclusive floor"

    def test_condemn_reject_leaves_cylinder_untouched(self, api):
        """PRD §3.2: "On rejection the record becomes `REJECTED`, `confirmer_technician_id` is likewise set, and the cylinder is untouched."

        Design: Difficulty/transitive_cascade/condemn_confirm_inventory_alert_chain
        """
        site = create_site(name="Reject Site")
        cyl = register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL",
                                       serial_prefix="RJ")[0]
        t1 = create_technician(cert_level="FULL", name="Reject T1")
        t2 = create_technician(cert_level="FULL", name="Reject T2")
        record = record_certification(cyl["id"], t1, method="VISUAL", outcome="CONDEMN")
        rejected = validate_success(
            api.reject_certification_record(record["id"], {},
                                            make_technician_headers(t2["id"])),
            200,
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["confirmer_technician_id"] == t2["id"]
        cyl_after = validate_success(api.get_cylinder(cyl["id"], ADMIN), 200)
        assert cyl_after["cert_status"] == "CERTIFIED"
        assert cyl_after["fill_status"] == "FULL"
        assert get_site(site["id"])["full_on_hand"] == 1
