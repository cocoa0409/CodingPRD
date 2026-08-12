"""Equipment rental lifecycle: settlement math, state gates, availability."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_rental_agreement,
    create_rental_agreement,
    create_rental_agreement_payload,
    create_rental_item,
    get_member,
    get_rental_agreement,
    get_rental_item_via_list,
    register_ready_member,
    set_clock,
    validate_error,
    validate_success,
)

RANGE_OFFICER = TEST_USERS["range_officer_headers"]


class TestRentalSettlement:
    def test_rental_settlement_late_days_and_damage(self, api):
        """PRD §3.6: "the billable days are the whole UTC calendar days between
        the checkout date and the return date, with a minimum of one day; the
        rental charge is those days times the item's `daily_rate_cents`; the
        late days are the whole UTC calendar days by which the return date
        passed `due_date`, floored at zero (day-granularity — a return later on
        the due date is not late); the late fee is 500 cents per late day; and
        the settlement total is rental charge plus late fee plus
        `damage_fee_cents`."
        PRD §3.6: "Returning stamps `returned_at`, moves the agreement to
        `RETURNED`, and releases the item back to `AVAILABLE`."

        Design: Corner/calculations/rental_settlement_late_days_and_damage
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("rent@x.com", wallet_cents=20000)
        item = create_rental_item("Bow Y", "BOW", 2500)
        agreement = create_rental_agreement(
            item["id"], member["id"], "2026-05-02"
        )

        set_clock("2026-05-04T10:00:00Z")
        returned = validate_success(
            api.return_rental_agreement(
                agreement["id"],
                {"returned_condition": "DAMAGED", "damage_fee_cents": 1200},
                RANGE_OFFICER,
            ),
            200,
        )
        assert returned["status"] == "RETURNED"
        assert get_rental_item_via_list(item["id"])["status"] == "AVAILABLE", (
            "the item is released at return, before settle"
        )

        settled = validate_success(
            api.settle_rental_agreement(agreement["id"], RANGE_OFFICER), 200
        )
        assert_rental_agreement(settled)
        # 3 billable days x 2500 = 7500; 2 late days x 500 = 1000; damage 1200.
        assert settled["settlement_total_cents"] == 9700
        assert settled["status"] == "SETTLED"
        assert get_member(member["id"])["wallet_balance_cents"] == 10300


class TestRentalStateGates:
    def test_rental_settle_from_open_rejected(self, api):
        """PRD §3.6: "Settlement, also `RangeOfficer`-only, requires `RETURNED`
        and computes `settlement_total_cents`".
        PRD §3.6: "Return is a `RangeOfficer` action on an `OPEN` agreement
        (`ERR_RENTAL_INVALID_STATE` from any other state)."
        PRD §2.8: "Only after the request is well-formed do state-machine
        preconditions fire (the specific state error of the target transition,
        such as `ERR_SESSION_NOT_BOOKED`)".

        Design: Corner/state_machines/rental_settle_from_open_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("rs@x.com")
        item = create_rental_item("Bow X", "BOW", 2500)
        agreement = create_rental_agreement(
            item["id"], member["id"], "2026-05-02"
        )

        resp = api.settle_rental_agreement(agreement["id"], RANGE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_RENTAL_INVALID_STATE)
        after = get_rental_agreement(agreement["id"])
        assert after["status"] == "OPEN"
        assert after["settlement_total_cents"] is None

    def test_rental_of_rented_item_rejected(self, api):
        """PRD §3.6: "the item must be `AVAILABLE`
        (`ERR_RENTAL_ITEM_UNAVAILABLE` otherwise)".
        PRD §3.6: "Creation stamps `checked_out_at` from the logical clock,
        opens the agreement in `OPEN`, and moves the item from `AVAILABLE` to
        `RENTED`."

        Design: Corner/validations/rental_of_rented_item_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_ready_member("rr@x.com")
        item = create_rental_item("Bow Z", "BOW", 2500)
        create_rental_agreement(item["id"], member["id"], "2026-05-02")

        resp = api.create_rental_agreement(
            create_rental_agreement_payload(item["id"], member["id"], "2026-05-03"),
            RANGE_OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_RENTAL_ITEM_UNAVAILABLE)
        assert get_rental_item_via_list(item["id"])["status"] == "RENTED"
        agreements = validate_success(
            api.list_rental_agreements(
                RANGE_OFFICER, params={"rental_item_id": item["id"]}
            ),
            200,
        )
        assert len(agreements) == 1, "exactly one OPEN agreement may exist"
