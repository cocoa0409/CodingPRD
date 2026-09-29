"""Requests that break two rules at once and must name only the higher one.

A release can be both overweight on the rear axle and impossible to build in
time, and a label request can name both a wrongly-staged order and a
certification belonging to a different order; in each case the ladder of §2.6
decides which failure is reported.
"""

from datetime import date, timedelta

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_CERTIFICATION_ORDER_MISMATCH,
    ERR_IN_SERVICE_DATE_INFEASIBLE,
    ERR_ORDER_INVALID_STATE,
    ERR_REAR_GAWR_EXCEEDED,
)
from test_helpers.assertions import assert_order_dimensions
from test_helpers.constants import (
    BASE_BUILD_DAYS_BY_BODY_TYPE,
    BODY_DUMP_16FT_HD,
    CLOCK_ORIGIN_DATE,
    DAYS_PER_HYDRAULIC_ITEM,
    vin_f550,
)
from test_helpers.factories import compliance_label_payload
from test_helpers.fixtures import (
    allocate,
    approve_certification,
    catalog_dump,
    catalog_service,
    draft_certification,
    install_body,
    new_body_spec,
    new_configuration,
    new_customer,
    new_order,
    new_slot,
    new_work_bay,
    plan_equipment,
    projection,
    read_order,
    received_and_inspected_chassis,
    release,
    start_slot,
    submit_engineering,
)


def _overweight_and_late_dump_order(api):
    """A heavy-duty dump body that is both too heavy on the rear axle and too late."""
    ns = catalog_dump(api)
    ns.heavy_body = new_body_spec(api, BODY_DUMP_16FT_HD)
    ns.customer = new_customer(api)
    ns.config = new_configuration(
        api, ns.cm["id"], ns.heavy_body["id"], config_code="CFG-DUMP-HD"
    )
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], availability_date="2026-08-10", measured=(4180, 2320)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-1801",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=96,
        requested_in_service_date="2026-09-01",
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.hoist_install = plan_equipment(
        api, ns.order["id"], ns.hoist["id"], 130, "PRIMARY", headers=users.TECHNICIAN
    )
    ns.order = submit_engineering(api, ns.order["id"])
    return ns


def _two_orders_at_different_compliance_stages(api):
    """Order A is only design certified; order B holds an approved measured certification."""
    ns = catalog_service(api, with_equipment=False)
    ns.bay = new_work_bay(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis_a = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(10), measured=(4820, 2680)
    )
    ns.chassis_b = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(11), measured=(4820, 2680)
    )
    ns.order_a = new_order(
        api,
        ns.config["id"],
        order_number="UO-1901",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=5000,
        requested_in_service_date="2026-09-15",
    )
    allocate(api, ns.order_a["id"], ns.chassis_a["id"])
    ns.order_a = submit_engineering(api, ns.order_a["id"])
    ns.cert_a = draft_certification(
        api, ns.order_a["id"], "AS_DESIGNED", expected_version=ns.order_a["version"]
    )
    ns.cert_a = approve_certification(api, ns.cert_a["id"])

    ns.order_b = new_order(
        api,
        ns.config["id"],
        order_number="UO-1902",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=5000,
        requested_in_service_date="2026-09-20",
    )
    allocate(api, ns.order_b["id"], ns.chassis_b["id"])
    ns.order_b = submit_engineering(api, ns.order_b["id"])
    ns.cert_b_designed = draft_certification(
        api, ns.order_b["id"], "AS_DESIGNED", expected_version=ns.order_b["version"]
    )
    ns.cert_b_designed = approve_certification(api, ns.cert_b_designed["id"])
    ns.order_b = release(api, ns.order_b["id"])
    ns.slot_b = new_slot(
        api,
        ns.order_b["id"],
        ns.bay["id"],
        "2026-09-01",
        "2026-09-10",
        slot_type="FINAL_QC",
    )
    ns.slot_b = start_slot(api, ns.slot_b["id"])
    ns.order_b = install_body(api, ns.order_b["id"], 2100)
    ns.cert_b_measured = draft_certification(
        api, ns.order_b["id"], "AS_MEASURED", expected_version=ns.order_b["version"]
    )
    ns.cert_b_measured = approve_certification(api, ns.cert_b_measured["id"])
    ns.order_a = read_order(api, ns.order_a["id"])
    ns.order_b = read_order(api, ns.order_b["id"])
    return ns


class TestReleaseWeightOutranksSchedule:
    """A rear-axle overrun and an impossible date collide on one release."""

    def test_the_rear_axle_overrun_is_the_reported_failure(self, api):
        """Regulatory weight is reported ahead of the temporal feasibility rule.

        The heavy-duty dump body puts 9785 pounds on an axle rated for 9450 and
        the requested date is a day too early, and the refusal names the axle.

        Design: Difficulty/priority_pair_validation_conflict/release_rear_gawr_outranks_in_service_date_infeasible
        """
        ns = _overweight_and_late_dump_order(api)

        response = api.release_order(ns.order["id"], users.SCHEDULER)

        error = validate_error(response, ERR_REAR_GAWR_EXCEEDED, 422)
        assert error["error_id"] != ERR_IN_SERVICE_DATE_INFEASIBLE

    def test_both_release_rules_were_genuinely_broken(self, api):
        """Neither rule is a straw man: each one really is violated.

        The design projection puts the rear axle above the model's rear axle
        rating, and the earliest feasible date — eighteen dump days plus five
        hydraulic days from the unit's availability — falls one day after the
        date the customer asked for.

        Design: Difficulty/priority_pair_validation_conflict/release_rear_gawr_outranks_in_service_date_infeasible
        """
        ns = _overweight_and_late_dump_order(api)

        designed = projection(api, ns.order["id"], "AS_DESIGNED")
        assert designed["rear_axle_load_lb"] == 9785
        assert designed["rear_axle_load_lb"] > ns.cm["rear_gawr_lb"]
        assert designed["gvw_lb"] == 13650
        assert designed["gvw_lb"] <= ns.cm["gvwr_lb"]

        span = BASE_BUILD_DAYS_BY_BODY_TYPE["DUMP"] + DAYS_PER_HYDRAULIC_ITEM
        start = max(date.fromisoformat(CLOCK_ORIGIN_DATE), date.fromisoformat("2026-08-10"))
        earliest = start + timedelta(days=span)
        assert earliest.isoformat() == "2026-09-02"
        assert ns.order["requested_in_service_date"] == "2026-09-01"
        assert date.fromisoformat(ns.order["requested_in_service_date"]) < earliest

    def test_the_refused_release_leaves_the_order_unpriced(self, api):
        """A refused release changes nothing, not even the invoice.

        The order stays under engineering review and its invoice total is still
        zero, because pricing only happens on a release that passes the gate.

        Design: Difficulty/priority_pair_validation_conflict/release_rear_gawr_outranks_in_service_date_infeasible
        """
        ns = _overweight_and_late_dump_order(api)

        validate_error(
            api.release_order(ns.order["id"], users.SCHEDULER), ERR_REAR_GAWR_EXCEEDED, 422
        )

        order = read_order(api, ns.order["id"])
        assert_order_dimensions(order, build_status="ENGINEERING_REVIEW")
        assert order["invoice_total_cents"] == 0


class TestLabelStateOutranksReferentialIntegrity:
    """A label request naming the wrong order and the wrong certification."""

    def test_the_order_state_is_the_reported_failure(self, api):
        """The state of the order being labelled is checked before the citation.

        Order A has only a design certification, so it may not be labelled at
        all; that state refusal is reported instead of the fact that the cited
        certification belongs to order B.

        Design: Difficulty/priority_pair_validation_conflict/label_order_state_outranks_certification_order_mismatch
        """
        ns = _two_orders_at_different_compliance_stages(api)

        response = api.create_compliance_label(
            compliance_label_payload(ns.order_a["id"], ns.cert_b_measured["id"]),
            users.OFFICER_ALT,
        )

        error = validate_error(response, ERR_ORDER_INVALID_STATE, 409)
        assert error["error_id"] != ERR_CERTIFICATION_ORDER_MISMATCH

    def test_both_label_rules_were_genuinely_broken(self, api):
        """Both the order stage and the citation are wrong at the same time.

        Order A sits at DESIGN_CERTIFIED while the cited certification is the
        approved measured one belonging to order B, which stands at
        MEASURED_CERTIFIED.

        Design: Difficulty/priority_pair_validation_conflict/label_order_state_outranks_certification_order_mismatch
        """
        ns = _two_orders_at_different_compliance_stages(api)

        assert_order_dimensions(ns.order_a, compliance_status="DESIGN_CERTIFIED")
        assert_order_dimensions(ns.order_b, compliance_status="MEASURED_CERTIFIED")
        assert ns.cert_b_measured["upfit_order_id"] == ns.order_b["id"]
        assert ns.cert_b_measured["upfit_order_id"] != ns.order_a["id"]
        assert ns.cert_b_measured["status"] == "APPROVED"

    def test_the_refused_request_leaves_the_order_without_any_label(self, api):
        """Nothing is persisted for the order whose label request was refused.

        No label anywhere in the plant points at order A, and both orders keep
        the compliance stage they had before the attempt.

        Design: Difficulty/priority_pair_validation_conflict/label_order_state_outranks_certification_order_mismatch
        """
        ns = _two_orders_at_different_compliance_stages(api)

        validate_error(
            api.create_compliance_label(
                compliance_label_payload(ns.order_a["id"], ns.cert_b_measured["id"]),
                users.OFFICER_ALT,
            ),
            ERR_ORDER_INVALID_STATE,
            409,
        )

        labels, _meta = validate_paginated(api.list_compliance_labels(users.OFFICER))
        assert [label for label in labels if label["upfit_order_id"] == ns.order_a["id"]] == []
        assert_order_dimensions(
            read_order(api, ns.order_a["id"]), compliance_status="DESIGN_CERTIFIED"
        )
