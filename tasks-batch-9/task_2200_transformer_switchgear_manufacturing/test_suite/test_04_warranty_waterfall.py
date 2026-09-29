"""The warranty credit waterfall and the two-levels-away warranty window."""

from test_helpers import (
    CONTRACT_ADMIN,
    FIELD_SERVICE_ENGINEER,
    QUALITY_ENGINEER,
    USER_FIELD_2,
    USER_QUALITY_1,
    assert_bucket_allocation,
    assert_instant_equals,
    assert_net_contract_value,
    assert_punch_aggregates,
    create_bay,
    create_component,
    create_job,
    create_order,
    create_release,
    create_supplier,
    deliver_release,
    drive_order_to_closed,
    drive_order_to_in_production,
    energize_job,
    failure_analysis_report_payload,
    issue_label,
    make_headers,
    read_order,
    run_fat_to_conclusion,
    set_clock,
    warranty_claim_payload,
)
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId

SETTLER = make_headers("u_ca_1", "ContractAdmin")


def test_one_liability_cap_binds_by_exhaustion_on_one_claim_and_not_at_all_on_its_sibling(
    api,
):
    """PRD 3.9: "The labor sub-limit is then the granted parts amount multiplied
    by 60 and divided by one hundred... The labor grant is the least of the labor
    claim, that sub-limit, and the remaining balance... The freight grant is the
    least of the freight claim, the freight cap of two hundred and fifty thousand
    cents, and the remaining balance"; "sibling claims on the same order do not
    share it".

    Design: Difficulty/combinatorial_formula/warranty_waterfall_cap_exhaustion_mode_vs_labor_sublimit_plus_freight_cap_mode
    """
    set_clock(api, "2026-01-05T00:00:00Z")
    supplier = create_supplier(
        api, supplier_code="SUP-W03", legal_name="Aurora Magnetics", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="BSH-500",
        category="HV_BUSHING",
        lead_time_days=60,
        quantity_on_hand=10,
        allocation_policy="PREEMPTIBLE",
    )
    order = create_order(
        api,
        order_number="TX-WAR-0003",
        product_family="POWER_TRANSFORMER",
        rated_kv=12,
        contract_value_cents=4000000,
    )
    bay = create_bay(
        api, bay_code="BAY-W03", max_kv=145, changeover_buffer_hours=4,
        supports_impulse=True,
    )
    drive_order_to_closed(
        api,
        order,
        component["id"],
        bay["id"],
        fat_window_start_at="2026-02-10T08:00:00Z",
        fat_start_clock_at="2026-02-10T09:00:00Z",
        mobilization_at="2026-02-15T08:00:00Z",
        energize_clock_at="2026-03-01T08:00:00Z",
        quantity=4,
        need_by_date="2026-06-01T00:00:00Z",
        carrier_reference="CR-W03",
    )

    set_clock(api, "2026-05-10T00:00:00Z")

    def open_claim(claim_number, rma_number, parts, labor, freight):
        claim = validate_success(
            api.create_warranty_claim(
                order["id"],
                warranty_claim_payload(
                    claim_number=claim_number,
                    suspect_component_id=component["id"],
                    failure_reported_at="2026-05-10T00:00:00Z",
                    parts_claim_cents=parts,
                    labor_claim_cents=labor,
                    freight_claim_cents=freight,
                    consequential_claim_cents=0,
                ),
                CONTRACT_ADMIN,
            ),
            201,
        )
        assert claim["status"] == "SUBMITTED"
        assert claim["liability_cap_cents"] == 0
        assert claim["credit_issued_cents"] == 0
        # The cap is pinned once, when the return authorization is issued.
        pinned = validate_success(
            api.issue_rma(claim["id"], {"rma_number": rma_number}, CONTRACT_ADMIN)
        )
        assert pinned["liability_cap_cents"] == 1000000
        validate_success(api.receive_unit(claim["id"], {}, QUALITY_ENGINEER))
        report = validate_success(
            api.create_failure_analysis_report(
                claim["id"],
                failure_analysis_report_payload(
                    attributed_supplier_id=supplier["id"],
                    root_cause_code="SUPPLIER_DEFECT",
                    authored_by_user_id="u_qe_2",
                    quarantine_recommended=False,
                    defect_weight=3,
                ),
                QUALITY_ENGINEER,
            ),
            201,
        )
        validate_success(
            api.publish_failure_analysis_report(report["id"], {}, QUALITY_ENGINEER)
        )
        warrantable = validate_success(
            api.get_warranty_claim(claim["id"], CONTRACT_ADMIN)
        )
        assert warrantable["status"] == "WARRANTABLE"
        return warrantable

    claim_x = open_claim("WC-X", "RMA-X", 700000, 500000, 400000)
    claim_y = open_claim("WC-Y", "RMA-Y", 200000, 500000, 400000)

    # X: the remaining balance runs out inside LABOR, so FREIGHT is truncated
    # to zero before its own cap can ever bind.
    assert_bucket_allocation(claim_x, 700000, 300000, 0, 0)
    assert claim_x["credit_issued_cents"] == 1000000

    # Y: the same cap never binds; the 60%-of-granted-parts sub-limit binds
    # LABOR and the freight cap binds FREIGHT.
    assert_bucket_allocation(claim_y, 200000, 120000, 250000, 0)
    assert claim_y["credit_issued_cents"] == 570000
    assert claim_y["credit_issued_cents"] < claim_y["liability_cap_cents"]

    settled_x = validate_success(
        api.settle_warranty_claim(
            claim_x["id"], {"settled_by_user_id": "u_ca_1"}, SETTLER
        )
    )
    assert settled_x["status"] == "SETTLED"
    settled_y = validate_success(
        api.settle_warranty_claim(
            claim_y["id"], {"settled_by_user_id": "u_ca_1"}, SETTLER
        )
    )
    assert settled_y["status"] == "SETTLED"

    final_order = read_order(api, order["id"])
    assert final_order["warranty_credit_total_cents"] == 1570000
    assert final_order["net_contract_value_cents"] == 2430000
    assert_net_contract_value(final_order)


def test_warranty_window_admissibility_hangs_on_grandchild_punch_items(api):
    """PRD 3.9: "The candidate anchors are the commissioning jobs on the order
    whose status is `COMPLETE`... When no complete job exists the attempt is
    refused with `ERR_WARRANTY_WINDOW_UNAVAILABLE`."; the window "runs 18
    calendar months from the anchor when the order's `product_family` is
    `POWER_TRANSFORMER`", with "day-of-month overflow clamped to the last day of
    the target month", and "a `failure_reported_at` exactly equal to the expiry
    is out of time and rejected with `ERR_WARRANTY_WINDOW_EXPIRED`".

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_creatability_hangs_on_grandchild_punch_items_via_commissioning_job_status
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    supplier = create_supplier(
        api, supplier_code="SUP-XED2", legal_name="Harbor Magnetics", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="BSH-XED2",
        category="HV_BUSHING",
        lead_time_days=60,
        quantity_on_hand=10,
        allocation_policy="PREEMPTIBLE",
    )
    order = create_order(
        api,
        order_number="TX-XED-0002",
        product_family="POWER_TRANSFORMER",
        rated_kv=12,
        contract_value_cents=8000000,
    )
    bay = create_bay(api, bay_code="BAY-XED2", max_kv=145, changeover_buffer_hours=4)
    material = drive_order_to_in_production(
        api, order, component["id"], quantity=4, need_by_date="2026-12-01T00:00:00Z"
    )
    fat = run_fat_to_conclusion(
        api,
        order["id"],
        bay["id"],
        "2026-06-10T08:00:00Z",
        "2026-06-10T09:00:00Z",
        result="PASS",
        fat_overrides={"witness_required": False},
    )
    issue_label(api, order["id"], material["drawing"]["id"], fat["report"]["id"])
    release = create_release(api, order["id"])
    deliver_release(api, release["id"], "CR-XED2")
    job = create_job(
        api, order["id"], release["id"], mobilization_at="2026-08-20T08:00:00Z"
    )
    set_clock(api, "2026-08-20T08:00:00Z")
    energized = energize_job(api, job["id"], "2026-08-31T12:00:00Z")

    # The empty punch list reports a complete-looking ratio, yet the job does
    # not advance: completion is evaluated only on punch item state changes.
    assert energized["status"] == "PUNCH_OPEN"
    assert_instant_equals(energized["energized_at"], "2026-08-31T12:00:00Z")
    assert_punch_aggregates(energized, 0, 0, 10000)

    def raise_item(severity, description_text):
        return validate_success(
            api.create_punch_list_item(
                job["id"],
                {"severity": severity, "description_text": description_text},
                FIELD_SERVICE_ENGINEER,
            ),
            201,
        )

    def resolve_item(item_id):
        validate_success(
            api.assign_punch_list_item(
                item_id, {"assigned_to_user_id": USER_FIELD_2}, FIELD_SERVICE_ENGINEER
            )
        )
        return validate_success(
            api.resolve_punch_list_item(
                item_id, {"resolved_by_user_id": USER_FIELD_2}, FIELD_SERVICE_ENGINEER
            )
        )

    def close_item(item_id):
        resolve_item(item_id)
        return validate_success(
            api.close_punch_list_item(
                item_id, {"closed_by_user_id": USER_QUALITY_1}, QUALITY_ENGINEER
            )
        )

    def read_job():
        return validate_success(
            api.get_commissioning_job(job["id"], FIELD_SERVICE_ENGINEER)
        )

    pi_block = raise_item("BLOCKING", "Ground grid continuity out of spec")
    pi_major = raise_item("MAJOR", "Bushing torque re-check required")
    pi_minor = raise_item("MINOR", "Nameplate legend misprint")
    assert_punch_aggregates(read_job(), 3, 1, 0)

    # One claim, one identical return-authorization call, attempted four times.
    claim = validate_success(
        api.create_warranty_claim(
            order["id"],
            warranty_claim_payload(
                claim_number="WC-XED-1",
                suspect_component_id=component["id"],
                failure_reported_at="2026-08-31T12:00:00Z",
                parts_claim_cents=100000,
                labor_claim_cents=50000,
                freight_claim_cents=20000,
                consequential_claim_cents=0,
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )
    assert claim["status"] == "SUBMITTED"

    def attempt_rma():
        return api.issue_rma(
            claim["id"], {"rma_number": "RMA-XED-1"}, CONTRACT_ADMIN
        )

    validate_error(attempt_rma(), ApiErrorId.WARRANTY_WINDOW_UNAVAILABLE, 409)

    # Bouncing an item back is not closing it: the aggregates do not move.
    resolve_item(pi_minor["id"])
    bounced = validate_success(
        api.reject_punch_list_item(
            pi_minor["id"], {"reason": "Cosmetic - deferred to O&M"}, QUALITY_ENGINEER
        )
    )
    assert bounced["status"] == "OPEN"
    assert bounced["reject_count"] == 1
    assert_punch_aggregates(read_job(), 3, 1, 0)
    validate_error(attempt_rma(), ApiErrorId.WARRANTY_WINDOW_UNAVAILABLE, 409)

    # Clearing the only BLOCKING item is not sufficient either.
    close_item(pi_block["id"])
    after_block = read_job()
    assert after_block["status"] == "PUNCH_OPEN"
    assert_punch_aggregates(after_block, 2, 0, 3333)
    validate_error(attempt_rma(), ApiErrorId.WARRANTY_WINDOW_UNAVAILABLE, 409)

    close_item(pi_major["id"])
    after_major = read_job()
    assert after_major["status"] == "PUNCH_OPEN"
    assert_punch_aggregates(after_major, 1, 0, 6666)

    # The last close flips the job with no call ever addressed to it.
    close_item(pi_minor["id"])
    complete = read_job()
    assert complete["status"] == "COMPLETE"
    assert complete["startup_certificate_issued"] is True
    assert_punch_aggregates(complete, 0, 0, 10000)
    assert read_order(api, order["id"])["fulfillment_status"] == "CLOSED"

    admitted = validate_success(attempt_rma())
    assert admitted["status"] == "RMA_ISSUED"
    assert admitted["liability_cap_cents"] == 2000000

    # The anchor is 2026-08-31T12:00:00Z, so the 18-month expiry clamps the
    # thirty-first onto the last day of February 2028, a leap year.
    set_clock(api, "2028-03-01T00:00:00Z")

    def claim_at(claim_number, failure_reported_at):
        return validate_success(
            api.create_warranty_claim(
                order["id"],
                warranty_claim_payload(
                    claim_number=claim_number,
                    suspect_component_id=component["id"],
                    failure_reported_at=failure_reported_at,
                    parts_claim_cents=100000,
                    labor_claim_cents=0,
                    freight_claim_cents=0,
                    consequential_claim_cents=0,
                ),
                CONTRACT_ADMIN,
            ),
            201,
        )

    in_time = claim_at("WC-XED-2", "2028-02-29T11:59:59Z")
    accepted = validate_success(
        api.issue_rma(in_time["id"], {"rma_number": "RMA-XED-2"}, CONTRACT_ADMIN)
    )
    assert accepted["status"] == "RMA_ISSUED"

    out_of_time = claim_at("WC-XED-3", "2028-02-29T12:00:00Z")
    validate_error(
        api.issue_rma(out_of_time["id"], {"rma_number": "RMA-XED-3"}, CONTRACT_ADMIN),
        ApiErrorId.WARRANTY_WINDOW_EXPIRED,
        409,
    )
