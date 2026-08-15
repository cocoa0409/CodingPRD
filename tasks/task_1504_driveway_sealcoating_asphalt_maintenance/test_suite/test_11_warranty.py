"""Warranty: record creation, claims, segregation of duties, and the
repair-work-order cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_warranty_claim,
    assert_warranty_record,
    clear_plan_for,
    create_route_sheet,
    create_warranty_claim_payload,
    find_invoice_for_work_order,
    find_warranty_record_for_work_order,
    get_warranty_claim,
    get_warranty_record,
    make_customer_headers,
    make_office_admin_headers,
    post_weather_snapshot,
    schedule_work_order,
    set_clock,
    setup_completed_job,
    setup_investigating_claim,
    setup_open_claim,
    setup_warranty_scenario,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["office_admin_headers"]
CREW_LEAD = TEST_USERS["crew_lead_headers"]

RESIDENTIAL_900 = dict(
    lot_kind="RESIDENTIAL_DRIVEWAY",
    address="1 Elm St",
    measured_area_sqft=900,
    crack_linear_ft=10,
    pothole_count=1,
    pothole_area_sqft=2,
    window_start_hour=7,
    window_end_hour=10,
    drive_minutes_est=15,
    vehicles_to_move=1,
)


class TestWarrantyFullRepairCycle:
    def test_claim_to_repair_completion_exhausts_record(self, api):
        """PRD §3.10: "Approval moves the claim to `APPROVED` and materializes
        a warranty-repair work order: execution `PENDING`, `warranty_claim_id`
        pointing back at the claim, `quoted_area_sqft` taken from the original
        work order's actual area, `quoted_total_cents` zeroed, scope flags
        copied from the original job, `coats` fixed at 1, and striping
        `NOT_REQUIRED`." and "scheduling it (exempt from the re-application
        interval) moves the claim from `APPROVED` to `REPAIR_SCHEDULED`, and
        its completion moves the claim to `RESOLVED` while the warranty record
        exhausts from `CLAIM_OPEN` to `EXHAUSTED`." PRD §3.7: "an invoice is
        born in `DRAFT` (§3.9) — priced on actual measurements for ordinary
        jobs, zeroed line-by-line for warranty repairs so its total is exactly
        zero cents."

        Design: Corner/state_machines/warranty_claim_full_repair_cycle
        """
        ctx = setup_completed_job(
            actuals={
                "actual_area_sqft": 1250,
                "actual_crack_ft": 44,
                "actual_pothole_area_sqft": 12,
                "actual_stripe_ft": 0,
                "gallons_used": 17,
            },
            delivered_gallons=200,
        )
        record = find_warranty_record_for_work_order(ctx["work_order"]["id"])
        assert_warranty_record(record)
        assert record["status"] == "ACTIVE"
        assert record["started_on"] == "2026-08-12"
        assert record["expires_on"] == "2027-08-12", (
            f"12 warranty months, 1 coat, from 2026-08-12, got {record['expires_on']}"
        )

        claim = validate_success(
            api.create_warranty_claim(
                {
                    "warranty_record_id": record["id"],
                    "claim_type": "CRACK_RECURRENCE",
                    "description": "Cracks re-opened within warranty",
                },
                make_customer_headers(ctx["customer"]["id"]),
            ),
            201,
        )
        assert get_warranty_record(record["id"])["status"] == "CLAIM_OPEN"

        investigated = validate_success(
            api.investigate_warranty_claim(claim["id"], make_office_admin_headers("admin-a"))
        )
        assert investigated["status"] == "INVESTIGATING"
        assert investigated["investigated_by"] == "admin-a"

        approved = validate_success(
            api.approve_warranty_claim(claim["id"], make_office_admin_headers("admin-b"))
        )
        assert approved["status"] == "APPROVED"
        repair_id = approved["repair_work_order_id"]
        assert repair_id is not None

        repair = validate_success(api.get_work_order(repair_id, TEST_USERS["dispatcher_headers"]))
        assert repair["execution_status"] == "PENDING"
        assert repair["warranty_claim_id"] == claim["id"]
        assert repair["quoted_area_sqft"] == 1250, (
            "the repair's area basis is the original work order's actual area"
        )
        assert repair["quoted_total_cents"] == 0
        assert repair["coats"] == 1
        assert repair["striping_status"] == "NOT_REQUIRED"

        # Schedule the repair (exempt from the 24-month re-application interval
        # even though next_seal_eligible_on is 2028-08-12).
        sheet2 = create_route_sheet(ctx["crew"]["id"], "2026-08-20")
        post_weather_snapshot(
            "2026-08-20", min_temp_f=66, max_temp_f=84, precip_probability_pct=5
        )
        scheduled = schedule_work_order(
            repair_id, sheet2["id"], ctx["lot"]["id"], "2026-08-20",
            window_start_hour=7, window_end_hour=10, drive_minutes_est=15,
            vehicles_to_move=2,
        )
        assert scheduled["execution_status"] == "SCHEDULED"
        assert get_warranty_claim(claim["id"])["status"] == "REPAIR_SCHEDULED"

        clear_plan_for(repair_id)
        set_clock("2026-08-20T07:00:00Z")
        validate_success(api.start_work_order(repair_id, CREW_LEAD))
        finished = validate_success(
            api.finish_work_order(
                repair_id,
                {
                    "actual_area_sqft": 400,
                    "actual_crack_ft": 30,
                    "actual_pothole_area_sqft": 0,
                    "actual_stripe_ft": 0,
                    "gallons_used": 6,
                },
                CREW_LEAD,
            )
        )
        set_clock(finished["cure_until"])
        completed = validate_success(api.complete_work_order(repair_id, CREW_LEAD))
        assert completed["execution_status"] == "COMPLETED"

        assert get_warranty_claim(claim["id"])["status"] == "RESOLVED"
        assert get_warranty_record(record["id"])["status"] == "EXHAUSTED"
        repair_invoice = find_invoice_for_work_order(repair_id)
        assert repair_invoice["total_cents"] == 0, "warranty work is free"


class TestWarrantyExpiryOnLateClaim:
    def test_claim_after_expiry_flips_record(self, api):
        """PRD §3.10: "If the current clock date has passed `expires_on`, the
        record lazily flips to `EXPIRED` and the filing fails with
        `ERR_WARRANTY_EXPIRED`."

        Design: Corner/state_machines/warranty_record_expires_on_late_claim
        """
        ctx = setup_warranty_scenario(**RESIDENTIAL_900)
        record = ctx["warranty_record"]
        assert record["expires_on"] == "2027-08-12"

        set_clock("2027-08-13T00:00:00Z")
        resp = api.create_warranty_claim(
            create_warranty_claim_payload(record["id"], claim_type="FADE",
                                          description="Coating faded"),
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED, 409)
        assert get_warranty_record(record["id"])["status"] == "EXPIRED", (
            "the lazy expiry flip is persisted"
        )


class TestSecondClaimWhileOpen:
    def test_second_claim_rejected_while_claim_open(self, api):
        """PRD §3.10: "Filing requires the record to be `ACTIVE` (else
        `ERR_WARRANTY_NOT_ACTIVE`)" and "A successful filing moves the record
        to `CLAIM_OPEN`."

        Design: Corner/errors/warranty_second_claim_while_open_rejected
        """
        ctx = setup_open_claim(**RESIDENTIAL_900)
        assert ctx["warranty_record"]["status"] == "CLAIM_OPEN"

        resp = api.create_warranty_claim(
            create_warranty_claim_payload(
                ctx["warranty_record"]["id"], claim_type="FADE",
                description="Second claim while first open",
            ),
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WARRANTY_NOT_ACTIVE, 409)


class TestInvestigateTwice:
    def test_investigate_requires_open_claim(self, api):
        """PRD §3.10: "An `OfficeAdmin` opens the investigation, moving the
        claim from `OPEN` to `INVESTIGATING` (else `ERR_CLAIM_NOT_OPEN`) and
        recording their identity in `investigated_by`."

        Design: Corner/errors/warranty_investigate_twice_rejected
        """
        ctx = setup_investigating_claim(**RESIDENTIAL_900)
        assert ctx["claim"]["status"] == "INVESTIGATING"
        assert ctx["claim"]["investigated_by"] == "admin-a"

        resp = api.investigate_warranty_claim(
            ctx["claim"]["id"], make_office_admin_headers("admin-c")
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_OPEN, 409)
        after = get_warranty_claim(ctx["claim"]["id"])
        assert after["investigated_by"] == "admin-a", (
            "a rejected re-investigation must not overwrite investigated_by"
        )


class TestSegregationOfDuties:
    def test_investigator_cannot_approve_but_peer_can_deny(self, api):
        """PRD §3.10: "Adjudication is segregated: whichever admin approves or
        denies the claim must be a different person than the investigator, and
        a matching identity is rejected with `ERR_SEGREGATION_OF_DUTIES`.
        Denial moves the claim to `DENIED` and returns the warranty record
        from `CLAIM_OPEN` to `ACTIVE`."

        Design: Corner/rbac/warranty_approve_same_investigator_forbidden
        """
        ctx = setup_investigating_claim(**RESIDENTIAL_900)
        claim_id = ctx["claim"]["id"]

        resp = api.approve_warranty_claim(claim_id, make_office_admin_headers("admin-a"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        denied = validate_success(
            api.deny_warranty_claim(claim_id, make_office_admin_headers("admin-b"))
        )
        assert_warranty_claim(denied)
        assert denied["status"] == "DENIED"
        assert get_warranty_record(ctx["warranty_record"]["id"])["status"] == "ACTIVE"
