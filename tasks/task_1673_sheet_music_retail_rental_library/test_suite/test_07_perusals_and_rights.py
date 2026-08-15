"""Perusal holds and conversion, institution gates, and rights clearance."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_account,
    create_order,
    create_perusal_request,
    create_publisher,
    create_rental_set,
    create_rights_case,
    create_work,
    fetch_set,
    get_success_data,
    make_customer_headers,
    reserve_order,
    setup_shipped_perusal,
    validate_error,
    validate_success,
)

from test_helpers import ADVISOR, BILLING, CLERK


class TestPerusalHoldGeometry:
    def _setup_first_hold(self, api):
        """PR1 shipped at 2026-08-05: hold interval [08-05, 08-29] closed."""
        ws = setup_shipped_perusal(
            publisher_overrides=None, work_overrides=None,
            account_overrides={"account_name": "Choral Society School",
                               "credit_tier": "STANDARD", "credit_limit_cents": 0},
        )
        second = create_perusal_request(ws["account"]["id"], ws["work"]["id"],
                                        format="PHYSICAL")
        return ws, second

    def test_perusal_touching_prior_hold_end_conflicts(self, api):
        """PRD §2.10: "a new hold on the same work must begin strictly after the
        previous hold's end — adjacency is forbidden, because a returned approval
        copy sits in a three-day quarantine before the next perusal of that work
        may ship."
        PRD §3.7: "Approval stamps `ship_date` to the current clock date, sets
        `return_due_date` exactly twenty-one days later, and reserves the closed
        hold interval from `hold_start` (equal to `ship_date`) through `hold_end`
        (the return due date plus the three-day quarantine), a 24-day span in all".

        Design: Difficulty/resource_temporal_overlap/perusal_hold_closed_interval_with_quarantine
        """
        ws, second = self._setup_first_hold(api)
        first = get_success_data(api.get_perusal_request(ws["perusal"]["id"], CLERK))
        assert str(first["ship_date"]).startswith("2026-08-05")
        assert str(first["return_due_date"]).startswith("2026-08-26")
        assert str(first["hold_end"]).startswith("2026-08-29")

        # Shipping on 2026-08-29 would touch the prior hold's closed end.
        advance_clock("2026-08-29T00:00:00Z")
        resp = api.approve_perusal_request(second["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_PERUSAL_HOLD_CONFLICT)

    def test_perusal_starting_after_prior_hold_end_approved(self, api):
        """PRD §3.7: "no other `APPROVED`, `SHIPPED`, or `OVERDUE_PERUSAL` perusal
        on the same work may have a hold interval intersecting the new one — the
        new hold must begin strictly after every existing hold's end, with
        adjacency forbidden — and a violation is `ERR_PERUSAL_HOLD_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/perusal_hold_closed_interval_with_quarantine
        """
        ws, second = self._setup_first_hold(api)

        advance_clock("2026-08-30T00:00:00Z")  # strictly after hold_end 08-29
        approved = validate_success(api.approve_perusal_request(second["id"], CLERK))
        assert approved["status"] == "APPROVED"
        assert str(approved["hold_start"]).startswith("2026-08-30")


class TestPerusalInstitutionGate:
    def test_individual_account_cannot_create_perusal_request(self, api):
        """PRD §3.7: "the account must be of kind `SCHOOL` or `INSTITUTION`, both
        at filing and at approval, otherwise the request fails with
        `ERR_PERUSAL_REQUIRES_INSTITUTION` (HTTP 422)".

        Design: Corner/validations/individual_account_cannot_create_perusal_request
        """
        publisher = create_publisher("PI Pub", allows_digital_perusal=True)
        work = create_work(publisher["id"], title="PI Work", catalog_number="PI-1",
                           base_rental_rate_cents=5000, sale_price_cents=900,
                           license_format="PRINT_AND_DIGITAL", perusal_allowed=True)
        account = create_account("Solo2", account_kind="INDIVIDUAL")

        resp = api.create_perusal_request(
            {"account_id": account["id"], "work_id": work["id"], "format": "PHYSICAL"},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_PERUSAL_REQUIRES_INSTITUTION)

    def test_individual_account_cannot_create_purchase_order(self, api):
        """PRD §3.4: "A `Customer` or `BillingManager` submits a purchase order,
        but only for an account of kind `SCHOOL` or `INSTITUTION` — otherwise the
        request fails with `ERR_PO_REQUIRES_INSTITUTION` (HTTP 422)."

        Design: Corner/validations/individual_account_cannot_create_purchase_order
        """
        account = create_account("Solo Person", account_kind="INDIVIDUAL")

        resp = api.create_purchase_order(
            {
                "account_id": account["id"],
                "po_number": "PO-X",
                "authorized_amount_cents": 10000,
                "valid_from": "2026-08-01",
                "valid_until": "2027-06-30",
            },
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_PO_REQUIRES_INSTITUTION)


class TestDigitalPerusalGate:
    def test_digital_perusal_rejected_when_publisher_disallows(self, api):
        """PRD §3.7: "a `DIGITAL` format additionally requires the publisher's
        `allows_digital_perusal` flag and a work `license_format` other than
        `PRINT_ONLY`, else `ERR_LICENSE_FORMAT_NOT_AVAILABLE`".

        Design: Corner/validations/digital_perusal_rejected_when_publisher_disallows
        """
        publisher = create_publisher("DP Pub", allows_digital_perusal=False)
        work = create_work(publisher["id"], title="DP Work", catalog_number="DP-1",
                           base_rental_rate_cents=5000, sale_price_cents=900,
                           license_format="PRINT_AND_DIGITAL", perusal_allowed=True)
        account = create_account("DP School", credit_tier="STANDARD", credit_limit_cents=0)
        digital = create_perusal_request(account["id"], work["id"], format="DIGITAL")
        physical = create_perusal_request(account["id"], work["id"], format="PHYSICAL")

        resp = api.approve_perusal_request(digital["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_LICENSE_FORMAT_NOT_AVAILABLE)

        approved = validate_success(api.approve_perusal_request(physical["id"], CLERK))
        assert approved["status"] == "APPROVED", (
            "the publisher flag gates only the DIGITAL format"
        )


class TestPerusalConversion:
    def test_perusal_convert_to_rental_creates_reserved_order(self, api):
        """PRD §3.7: "A rental conversion additionally supplies `rental_set_id`,
        `copies_requested`, `checkout_date`, and `due_date`, and delegates to the
        full reservation chain of §3.5: every reserve precondition applies, and on
        success a new rental order appears directly in `RESERVED`."
        PRD §3.7: "Either way the perusal moves to `CONVERTED`,
        `converted_target_id` records the `id` of the created rental order or sale
        record".

        Design: Corner/endpoints/perusal_convert_to_rental_creates_reserved_order
        """
        ws = setup_shipped_perusal(
            work_overrides={"title": "CV Work", "catalog_number": "CV-1",
                            "base_rental_rate_cents": 10000, "sale_price_cents": 2000},
            account_overrides={"account_name": "CV School", "credit_tier": "STANDARD",
                               "credit_limit_cents": 0},
        )
        rental_set = create_rental_set(ws["work"]["id"], set_code="CV-SET",
                                       copy_count=10, replacement_value_cents=80000)

        converted = validate_success(api.convert_perusal_request(
            ws["perusal"]["id"],
            {
                "converted_target_kind": "RENTAL",
                "rental_set_id": rental_set["id"],
                "copies_requested": 3,
                "checkout_date": "2026-08-10",
                "due_date": "2026-09-09",
            },
            CLERK,
        ))
        assert converted["status"] == "CONVERTED"
        assert converted["converted_target_kind"] == "RENTAL"

        order = get_success_data(
            api.get_rental_order(converted["converted_target_id"], CLERK)
        )
        assert order["status"] == "RESERVED"
        assert order["copies_requested"] == 3
        assert fetch_set(rental_set["id"])["available_copy_count"] == 7


class TestRightsClearanceGate:
    def _setup_grand_rights_order(self, api):
        publisher = create_publisher("Pub Fourteen")
        work = create_work(publisher["id"], title="Opera Scene",
                           catalog_number="P14-001", ensemble_tier="ORCHESTRA",
                           base_rental_rate_cents=9000, sale_price_cents=3000,
                           license_format="PRINT_ONLY", rights_class="GRAND_RIGHTS")
        rental_set = create_rental_set(work["id"], set_code="SET-1201", copy_count=10,
                                       replacement_value_cents=90000)
        account = create_account("Opera Guild School", account_kind="INSTITUTION",
                                 credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        order = create_order(account["id"], rental_set["id"], copies=2)
        reserve_order(order["id"])
        return account, work, order

    def test_dispatch_blocked_while_case_open_or_license_required(self, api):
        """PRD §3.5: "for works whose `rights_class` is `GRAND_RIGHTS` or
        `RESTRICTED` there must exist a rights advisory case for this account and
        work that is `DECIDED` with determination `CLEARED`, else
        `ERR_RIGHTS_NOT_CLEARED`."
        PRD §3.9: "Works whose `rights_class` is `GRAND_RIGHTS` or `RESTRICTED` may
        not be dispatched until a rights advisory case for the same account and
        work has been decided `CLEARED`; `STANDARD` works need no case at all."

        Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_rights_advisory_state
        """
        account, work, order = self._setup_grand_rights_order(api)
        case = create_rights_case(account["id"], work["id"], venue_kind="EDUCATIONAL",
                                  question="Staged scene with costumes?")
        assert case["status"] == "OPEN"
        assert case["determination"] == "PENDING"

        resp_open = api.dispatch_rental_order(order["id"], CLERK)
        validate_error(resp_open, ApiErrorId.ERR_RIGHTS_NOT_CLEARED)

        get_success_data(api.decide_rights_case(case["id"], "LICENSE_REQUIRED", ADVISOR))
        resp_lic = api.dispatch_rental_order(order["id"], CLERK)
        validate_error(resp_lic, ApiErrorId.ERR_RIGHTS_NOT_CLEARED)
        stayed = get_success_data(api.get_rental_order(order["id"], CLERK))
        assert stayed["status"] == "RESERVED", (
            "a rejected dispatch must not move the order"
        )

    def test_dispatch_succeeds_after_cleared_determination(self, api):
        """PRD §3.5: "for works whose `rights_class` is `GRAND_RIGHTS` or
        `RESTRICTED` there must exist a rights advisory case for this account and
        work that is `DECIDED` with determination `CLEARED`, else
        `ERR_RIGHTS_NOT_CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_rights_advisory_state
        """
        account, work, order = self._setup_grand_rights_order(api)
        case = create_rights_case(account["id"], work["id"], venue_kind="EDUCATIONAL",
                                  question="Concert performance, no staging")
        decided = get_success_data(
            api.decide_rights_case(case["id"], "CLEARED", ADVISOR)
        )
        assert decided["status"] == "DECIDED"
        assert decided["determination"] == "CLEARED"

        dispatched = validate_success(api.dispatch_rental_order(order["id"], CLERK))
        assert dispatched["status"] == "DISPATCHED"


class TestRightsCaseRbac:
    def test_rights_advisor_cannot_decide_when_customer_role(self, api):
        """PRD §3.9: "A `RightsAdvisor` decides an `OPEN` case (any other state is
        `ERR_INVALID_STATE`) by supplying a `determination` of `CLEARED`,
        `LICENSE_REQUIRED`, or `PROHIBITED`".
        PRD §2.1: "A request whose role is not permitted for the operation is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/rights_advisor_cannot_decide_when_customer_role
        """
        publisher = create_publisher("RA2 Pub")
        work = create_work(publisher["id"], title="RA2 Work", catalog_number="RA2-1",
                           ensemble_tier="ORCHESTRA", base_rental_rate_cents=9000,
                           sale_price_cents=3000, license_format="PRINT_ONLY",
                           rights_class="GRAND_RIGHTS")
        account = create_account("RA2 School", credit_tier="STANDARD",
                                 credit_limit_cents=0)
        case = create_rights_case(
            account["id"], work["id"], venue_kind="CONCERT",
            question="Public performance cleared?",
            headers=make_customer_headers(account["id"]),
        )

        resp = api.decide_rights_case(
            case["id"], "CLEARED", make_customer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        stayed = get_success_data(api.get_rights_case(case["id"], ADVISOR))
        assert stayed["status"] == "OPEN"
        assert stayed["determination"] == "PENDING"
