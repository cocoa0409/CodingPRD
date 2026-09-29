"""
Role-based access control at its edges: the narrowest role's single write, the
opaque care role's full reach, the platform role's non-hierarchical authority,
the two-dimensional ownership check on the two restaurant-backed roles, and the
per-row scope of the three segregation-of-duties comparisons.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CARE_DECIDER_HEADERS,
    CARE_FILER_HEADERS,
    CARE_HEADERS,
    CARE_ISSUER_HEADERS,
    CARE_REVOKER_HEADERS,
    GUEST_SERVICES_DECIDER_ID,
    GUEST_SERVICES_FILER_ID,
    GUEST_SERVICES_ISSUER_ID,
    make_care_headers,
    make_guest_headers,
    make_kitchen_headers,
    make_restaurant_headers,
)

# The recurring calendar. 2026-09-10 is a Thursday, whose day-of-week factor is
# the neutral 10000 basis points, and the demand tier stays STANDARD, so a cover
# costs the package's 12000 cent list price exactly.
SETUP_CLOCK = "2026-09-01T00:00:00Z"
SEATING_START = "2026-09-10T22:00:00Z"
SEATING_END = "2026-09-11T02:00:00Z"
# Exactly 48.0 hours before seating, where the STANDARD ladder band is 5000 bp.
CANCEL_AT_48H = "2026-09-08T22:00:00Z"

# A party of 2 at 12000 cents a cover: subtotal 24000, service charge 1740 at
# 725 bp, grand total 25740, deposit 7722 at 3000 bp.
TICKET_SUBTOTAL_CENTS = 24000
GRAND_TOTAL_CENTS = 25740
DEPOSIT_CENTS = 7722
# Cancelling at 48.0 hours: 5000 bp of the 7722 deposit is 3861, the rebooking
# fee band for that figure is 500, retention 4361 and the refund 3361.
FORFEITED_CENTS = 4361
REFUNDED_CENTS = 3361

CREDIT_EXPIRY = "2027-01-01T00:00:00Z"

# Two opaque care identifiers used to cross the file / decide / issue lineages.
CARE_ONE_ID = GUEST_SERVICES_FILER_ID
CARE_TWO_ID = GUEST_SERVICES_DECIDER_ID


def _std_chain(api, *, restaurant_overrides=None, seats_allocated=20):
    """One restaurant, one package, one DRAFT service and one ticket class."""
    FX.set_clock(api, SETUP_CLOCK)
    knobs = {
        "service_charge_bp": 725,
        "hold_ttl_minutes": 20,
        "offer_ttl_minutes": 15,
        "max_offer_rounds": 2,
        "goodwill_credit_cap_cents": 20000,
        "prep_lead_minutes": 45,
        "refund_scrutiny_threshold_cents": 300000,
    }
    knobs.update(restaurant_overrides or {})
    restaurant = FX.create_restaurant(api, **knobs)
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
        release_discount_bp=1500,
        kitchen_prep_minutes_per_cover=12,
        min_party_size=1,
        max_party_size=8,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-10",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="STANDARD",
        unsold_release_bp=5000,
        release_lead_minutes=180,
        waitlist_policy="FAIR_QUEUE",
        kitchen_prep_capacity_minutes=600,
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=seats_allocated,
        min_party_size=1,
        max_party_size=8,
    )
    return {
        "restaurant": restaurant,
        "restaurant_id": restaurant["id"],
        "package": package,
        "package_id": package["id"],
        "service": service,
        "service_id": service["id"],
        "ticket_class": ticket_class,
        "ticket_class_id": ticket_class["id"],
        "manager": make_restaurant_headers(restaurant["id"]),
        "kitchen": make_kitchen_headers(restaurant["id"]),
    }


def _kitchen_lead_world(api):
    """A published Thursday service with one table, and a CONFIRMED party-of-2
    booking carrying one ANAPHYLAXIS note and one ALLERGY note.
    """
    world = _std_chain(api)
    table = FX.create_table(
        api, world["restaurant_id"], table_code="T1", seats_min=2, seats_max=4
    )
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    guest = FX.create_guest(api, display_name="Kitchen World Guest")
    reservation = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest["id"], party_size=2
    )
    note_anaphylaxis = FX.add_dietary_note(
        api,
        reservation["id"],
        guest["id"],
        guest_index=1,
        severity="ANAPHYLAXIS",
        restriction_code="NUT",
        note_text="Airborne peanut reaction, no shared surfaces.",
    )
    note_allergy = FX.add_dietary_note(
        api,
        reservation["id"],
        guest["id"],
        guest_index=2,
        severity="ALLERGY",
        restriction_code="SHELLFISH",
        note_text="No shared fryer.",
    )
    world.update(
        {
            "table": table,
            "table_id": table["id"],
            "guest": guest,
            "guest_id": guest["id"],
            "guest_headers": make_guest_headers(guest["id"]),
            "reservation": reservation,
            "reservation_id": reservation["id"],
            "note_anaphylaxis": note_anaphylaxis,
            "note_allergy": note_allergy,
        }
    )
    return world


class TestKitchenLeadHasExactlyOneWriteAuthority:
    """The back-of-house lead decides notes and nothing else."""

    def test_kitchen_lead_decides_notes_both_ways_and_reads_the_reservation_notes(
        self, api
    ):
        """Accept, prep-reject and the scoped note read all succeed for the lead.

        "A `KitchenLead` decides a note by supplying a `decision` of either `ACCEPT` or `REJECT`."
        "Acceptance records the acting lead's `X-User-ID` as `acked_by_user_id` and re-derives the reservation's `prep_minutes_total`, which in turn re-tests the service's kitchen-prep capacity window."
        "It is recomputed whenever a note is created, acknowledged or amended, whenever an add-on line is appended, and again whenever a table is assigned."

        Design: Corner/rbac/rbac_kitchen_lead_acks_notes_but_cannot_seat_price_or_touch_money
        """
        world = _kitchen_lead_world(api)
        kitchen = make_kitchen_headers(world["restaurant_id"])

        # 2 covers at 12 minutes each, plus 15 for the anaphylaxis note and 6
        # for the allergy note.
        before = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        assert before["prep_minutes_total"] == 45

        accepted = get_success_data(
            api.ack_dietary_note(
                world["note_anaphylaxis"]["id"], F.ack_payload("ACCEPT"), kitchen
            )
        )
        assert accepted["ack_status"] == "ACKED"
        # The lead acts as the owning restaurant, so the recorded actor is that
        # restaurant's id.
        assert accepted["acked_by_user_id"] == world["restaurant_id"]

        rejected = get_success_data(
            api.ack_dietary_note(
                world["note_allergy"]["id"],
                F.reject_payload(reject_reason_code="CROSS_CONTAMINATION_RISK"),
                kitchen,
            )
        )
        assert rejected["ack_status"] == "PREP_REJECTED"
        assert rejected["reject_reason_code"] == "CROSS_CONTAMINATION_RISK"
        assert rejected["amend_count"] == 0

        # Severity minutes are counted regardless of the acknowledgement state,
        # so deciding both notes moves nothing.
        after = FX.read_reservation(api, world["reservation_id"], world["guest_headers"])
        assert after["prep_minutes_total"] == 45

        notes, meta = validate_paginated(
            api.list_reservation_dietary_notes(world["reservation_id"], kitchen)
        )
        assert meta["total_count"] == 2
        A.assert_created_at_ascending(notes)
        assert notes[0]["id"] == world["note_anaphylaxis"]["id"]
        assert notes[1]["id"] == world["note_allergy"]["id"]

    def test_kitchen_lead_cannot_run_the_floor_or_edit_the_catalogue(self, api):
        """Six seating and catalogue writes are refused on the role check alone.

        "This role deliberately cannot seat a party, cannot price anything, and cannot touch money."
        "If the acting role is not among the roles listed for the endpoint being called, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/rbac_kitchen_lead_acks_notes_but_cannot_seat_price_or_touch_money
        """
        world = _kitchen_lead_world(api)
        kitchen = make_kitchen_headers(world["restaurant_id"])

        # The anaphylaxis note is still PENDING, which would block a table
        # assignment on its own — but the role check is reached first, so the
        # refusal names the role and not the dietary blocker.
        validate_error(
            api.assign_table(
                world["reservation_id"],
                F.assign_table_payload(world["table_id"], SEATING_START),
                kitchen,
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.seat_reservation(world["reservation_id"], kitchen),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.complete_reservation(world["reservation_id"], kitchen),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_table(
                F.table_payload(world["restaurant_id"], table_code="T2"), kitchen
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.set_demand_tier(
                world["service_id"], F.demand_tier_payload("PEAK"), kitchen
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.pause_ticket_class(world["ticket_class_id"], kitchen),
            E.ERR_UNAUTHORIZED,
            403,
        )

        # Nothing the lead reached for moved.
        reservation = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_fulfillment_status(reservation, "CONFIRMED")
        assert reservation["assigned_table_id"] is None
        service = FX.read_service(api, world["service_id"], world["manager"])
        assert service["demand_tier"] == "STANDARD"
        assert service["status"] == "PUBLISHED"
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        assert ticket_class["status"] == "OPEN"
        tables, tables_meta = validate_paginated(
            api.list_restaurant_tables(world["restaurant_id"], world["manager"])
        )
        assert tables_meta["total_count"] == 1
        assert tables[0]["id"] == world["table_id"]

    def test_kitchen_lead_cannot_touch_money_or_platform_operations(self, api):
        """Payments, cancellation, compensation and onboarding are all refused.

        "This role deliberately cannot seat a party, cannot price anything, and cannot touch money."
        "If the acting role is not among the roles listed for the endpoint being called, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/rbac_kitchen_lead_acks_notes_but_cannot_seat_price_or_touch_money
        """
        world = _kitchen_lead_world(api)
        kitchen = make_kitchen_headers(world["restaurant_id"])

        validate_error(
            api.take_payment(
                world["reservation_id"], F.payment_payload(1000), kitchen
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.cancel_reservation(world["reservation_id"], kitchen),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_refund_exception(
                F.refund_exception_payload(world["reservation_id"], 1000), kitchen
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_goodwill_credit(
                F.goodwill_credit_payload(NON_EXISTENT_UUID, 1000, CREDIT_EXPIRY),
                kitchen,
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_guest(F.guest_payload(), kitchen), E.ERR_UNAUTHORIZED, 403
        )
        validate_error(
            api.set_clock("2026-09-11T03:00:00Z", kitchen), E.ERR_UNAUTHORIZED, 403
        )

        # The money picture is exactly the deposit the guest paid, on one row.
        reservation = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_money_breakdown(
            reservation,
            grand_total=GRAND_TOTAL_CENTS,
            deposit_due=DEPOSIT_CENTS,
            amount_paid=DEPOSIT_CENTS,
            refunded=0,
            forfeited=0,
        )
        A.assert_payment_status(reservation, "DEPOSIT_PAID")
        rows = FX.ledger_rows(api, world["reservation_id"], ADMIN_HEADERS)
        assert [row["kind"] for row in rows] == ["DEPOSIT_CHARGE"]
        assert rows[0]["amount_cents"] == DEPOSIT_CENTS

    def test_kitchen_lead_read_surface_stops_at_the_kitchen(self, api):
        """Guests, the ledger and the price quote are closed to the lead.

        "Every request to the API — reads included — must carry two headers."
        "If the acting role is not among the roles listed for the endpoint being called, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/rbac_kitchen_lead_acks_notes_but_cannot_seat_price_or_touch_money
        """
        world = _kitchen_lead_world(api)
        kitchen = make_kitchen_headers(world["restaurant_id"])

        validate_error(api.list_guests(kitchen), E.ERR_UNAUTHORIZED, 403)
        validate_error(
            api.list_payment_transactions(kitchen), E.ERR_UNAUTHORIZED, 403
        )
        validate_error(
            api.price_quote(world["ticket_class_id"], kitchen), E.ERR_UNAUTHORIZED, 403
        )

        # The kitchen's own reads remain open.
        notes, meta = validate_paginated(
            api.list_reservation_dietary_notes(world["reservation_id"], kitchen)
        )
        assert meta["total_count"] == 2
        note = FX.read_note(api, world["note_anaphylaxis"]["id"], kitchen)
        assert note["severity"] == "ANAPHYLAXIS"
        assert note["ack_status"] == "PENDING"


# The adjudication figures: 1000 cents approved out of the 4361 forfeited,
# leaving a 3361 cent shortfall that the compensating credit matches exactly.
APPROVED_CENTS = 1000
SHORTFALL_CENTS = 3361


def _care_world(api):
    """A published Thursday service and one guest, with no booking yet."""
    world = _std_chain(api)
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    guest = FX.create_guest(api, display_name="Care World Guest")
    world.update(
        {
            "guest": guest,
            "guest_id": guest["id"],
            "guest_headers": make_guest_headers(guest["id"]),
        }
    )
    return world


def _care_paid_and_cancelled(api, world):
    """A party-of-2 hold that a care operator pays for and later cancels."""
    reservation = FX.hold_seats(
        api, world["ticket_class_id"], world["guest_id"], party_size=2
    )
    paid = get_success_data(
        api.take_payment(
            reservation["id"], F.payment_payload(DEPOSIT_CENTS), CARE_FILER_HEADERS
        )
    )
    FX.confirm(api, reservation["id"], world["guest_id"])
    FX.set_clock(api, CANCEL_AT_48H)
    cancelled = get_success_data(
        api.cancel_reservation(reservation["id"], CARE_FILER_HEADERS)
    )
    return {"reservation_id": reservation["id"], "paid": paid, "cancelled": cancelled}


def _care_issued_credit(api, reservation_id):
    """File, decide and compensate with three distinct opaque operators."""
    exception = FX.file_refund_exception(
        api, reservation_id, FORFEITED_CENTS, headers=CARE_FILER_HEADERS
    )
    decided = FX.decide_refund_exception(
        api,
        exception["id"],
        decision="APPROVED",
        approved_cents=APPROVED_CENTS,
        decision_note_code="PARTIAL_GOODWILL",
        headers=CARE_DECIDER_HEADERS,
    )
    credit = FX.issue_goodwill_credit(
        api,
        exception["id"],
        SHORTFALL_CENTS,
        CREDIT_EXPIRY,
        headers=CARE_ISSUER_HEADERS,
    )
    return {"exception": exception, "decided": decided, "credit": credit}


class TestGuestServicesReachIsPlatformWide:
    """The opaque care role covers both the shared and the exclusive surface."""

    def test_care_operator_pays_and_cancels_on_the_guests_behalf(self, api):
        """The two operations shared with the guest both succeed for care.

        "Money arrives through payments taken by a `Guest` or, on the guest's behalf, by a `GuestServices` operator, each carrying only an `amount_cents`."
        "Cancellation is available to the `Guest` who holds the ticket and to `GuestServices` acting on that guest's behalf."

        Design: Corner/rbac/rbac_guest_services_exclusive_and_shared_operations_all_succeed
        """
        world = _care_world(api)
        staged = _care_paid_and_cancelled(api, world)

        A.assert_payment_status(staged["paid"], "DEPOSIT_PAID")
        A.assert_money_breakdown(
            staged["paid"],
            ticket_subtotal=TICKET_SUBTOTAL_CENTS,
            service_charge=1740,
            grand_total=GRAND_TOTAL_CENTS,
            deposit_due=DEPOSIT_CENTS,
            amount_paid=DEPOSIT_CENTS,
        )

        cancelled = staged["cancelled"]
        A.assert_fulfillment_status(cancelled, "CANCELLED")
        A.assert_payment_status(cancelled, "PARTIALLY_REFUNDED")
        assert cancelled["cancel_settlement_basis"] == "DEPOSIT_BASIS"
        assert cancelled["forfeited_cents"] == FORFEITED_CENTS
        assert cancelled["refunded_cents"] == REFUNDED_CENTS
        A.assert_settled_ledger_identity(cancelled)

        rows = FX.ledger_rows(api, staged["reservation_id"], CARE_HEADERS)
        by_kind = {row["kind"]: row for row in rows}
        assert sorted(by_kind) == ["DEPOSIT_CHARGE", "FORFEITURE", "REFUND"]
        assert by_kind["DEPOSIT_CHARGE"]["amount_cents"] == DEPOSIT_CENTS
        assert by_kind["FORFEITURE"]["amount_cents"] == FORFEITED_CENTS
        assert by_kind["REFUND"]["amount_cents"] == REFUNDED_CENTS
        for row in rows:
            A.assert_ledger_row_shape(row)
            A.assert_signed_amount(row)

    def test_three_distinct_care_operators_file_decide_and_compensate(self, api):
        """Filing, deciding and issuing are exclusive to care and all land.

        "Filing records the acting operator's `X-User-ID` as `requested_by_user_id`, which is precisely the id that is thereafter barred from deciding it."
        "On approval, `approved_cents` and `decision_note_code` are stored and `shortfall_cents` is derived as `requested_cents` less `approved_cents`."
        "After **every** `REFUND` row is written — from any trigger, at any restaurant — the refunded amount is credited to that guest's `lifetime_refunded_cents`."

        Design: Corner/rbac/rbac_guest_services_exclusive_and_shared_operations_all_succeed
        """
        world = _care_world(api)
        staged = _care_paid_and_cancelled(api, world)
        chain = _care_issued_credit(api, staged["reservation_id"])

        assert chain["exception"]["requested_by_user_id"] == GUEST_SERVICES_FILER_ID
        assert chain["exception"]["requested_cents"] == FORFEITED_CENTS
        assert chain["decided"]["status"] == "APPROVED"
        assert chain["decided"]["decided_by_user_id"] == GUEST_SERVICES_DECIDER_ID
        assert chain["decided"]["approved_cents"] == APPROVED_CENTS
        assert chain["decided"]["shortfall_cents"] == SHORTFALL_CENTS

        # The approval reverses part of the retention and refunds it, as a new
        # pair of rows rather than an edit of the settlement rows.
        rows = FX.ledger_rows(api, staged["reservation_id"], CARE_HEADERS)
        exception_rows = [
            row for row in rows if row["memo_code"] == "REFUND_EXCEPTION"
        ]
        assert sorted(row["kind"] for row in exception_rows) == [
            "FORFEITURE_REVERSAL",
            "REFUND",
        ]
        assert [row["amount_cents"] for row in exception_rows] == [
            APPROVED_CENTS,
            APPROVED_CENTS,
        ]

        reservation = FX.read_reservation(
            api, staged["reservation_id"], world["guest_headers"]
        )
        assert reservation["forfeited_cents"] == FORFEITED_CENTS - APPROVED_CENTS
        assert reservation["refunded_cents"] == REFUNDED_CENTS + APPROVED_CENTS
        A.assert_settled_ledger_identity(reservation)
        A.assert_signed_sum_matches(reservation, rows)

        guest = FX.read_guest(api, world["guest_id"], world["guest_headers"])
        assert guest["lifetime_refunded_cents"] == REFUNDED_CENTS + APPROVED_CENTS
        # Far below the restaurant's 300000 cent scrutiny threshold.
        assert guest["refund_scrutiny_flag"] is False

        credit = chain["credit"]
        assert credit["issued_by_user_id"] == GUEST_SERVICES_ISSUER_ID
        assert credit["refund_exception_id"] == chain["exception"]["id"]
        assert credit["guest_id"] == world["guest_id"]
        assert credit["restaurant_id"] == world["restaurant_id"]
        assert credit["issued_cents"] == SHORTFALL_CENTS
        assert credit["remaining_cents"] == SHORTFALL_CENTS
        A.assert_credit_status(credit)
        A.assert_credit_identity(credit)
        assert credit["status"] == "ISSUED"

    def test_care_redeems_the_credit_and_a_fourth_operator_revokes_the_rest(self, api):
        """Redemption is shared with the guest; revocation is care's alone.

        "Redeeming a credit is done by the `Guest` or by `GuestServices`, naming the target `reservation_id`, an `amount_cents` and an `expected_goodwill_credit_version`."
        "Otherwise, if `refunded_cents` plus `forfeited_cents` is zero, it is `FULLY_PAID` when `amount_paid_cents` is at least `grand_total_cents`; failing that, `DEPOSIT_PAID` when `amount_paid_cents` is at least `deposit_due_cents`; failing that, `UNPAID`."
        "It writes **no** `PaymentTransaction` row at all: cents the guest has already spent stay spent, on the reservations they were spent against."

        Design: Corner/rbac/rbac_guest_services_exclusive_and_shared_operations_all_succeed
        """
        world = _care_world(api)
        staged = _care_paid_and_cancelled(api, world)
        chain = _care_issued_credit(api, staged["reservation_id"])
        credit_id = chain["credit"]["id"]

        # The cancelled booking freed its seats, so the same guest may rebook.
        rebooking = FX.hold_seats(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )
        row = FX.redeem_goodwill_credit(
            api,
            credit_id,
            rebooking["id"],
            APPROVED_CENTS,
            headers=CARE_FILER_HEADERS,
        )
        assert row["kind"] == "GOODWILL_REDEMPTION"
        assert row["memo_code"] == "CREDIT_APPLIED"
        assert row["goodwill_credit_id"] == credit_id
        assert row["reservation_id"] == rebooking["id"]
        assert row["amount_cents"] == APPROVED_CENTS
        A.assert_ledger_row_shape(row)
        A.assert_signed_amount(row)

        redeemed = FX.read_credit(api, credit_id, CARE_HEADERS)
        assert redeemed["status"] == "PARTIALLY_REDEEMED"
        assert redeemed["redeemed_cents"] == APPROVED_CENTS
        assert redeemed["remaining_cents"] == SHORTFALL_CENTS - APPROVED_CENTS
        A.assert_credit_identity(redeemed)
        A.assert_credit_status(redeemed)

        rebooked = FX.read_reservation(api, rebooking["id"], world["guest_headers"])
        A.assert_money_breakdown(
            rebooked,
            grand_total=GRAND_TOTAL_CENTS,
            amount_paid=APPROVED_CENTS,
            goodwill_applied=APPROVED_CENTS,
        )
        assert rebooked["balance_due_cents"] == GRAND_TOTAL_CENTS - APPROVED_CENTS
        # 1000 cents is short of the 7722 cent deposit, so the money dimension
        # has not advanced at all.
        A.assert_payment_status(rebooked, "UNPAID")

        revoked = FX.revoke_goodwill_credit(
            api, credit_id, headers=CARE_REVOKER_HEADERS
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_cents"] == SHORTFALL_CENTS - APPROVED_CENTS
        assert revoked["remaining_cents"] == 0
        assert revoked["redeemed_cents"] == APPROVED_CENTS
        A.assert_credit_identity(revoked)
        A.assert_credit_status(revoked)

        # The claw-back moves cents on the credit only; the rebooking's single
        # ledger row is untouched.
        rebooked_rows = FX.ledger_rows(api, rebooking["id"], CARE_HEADERS)
        assert [r["kind"] for r in rebooked_rows] == ["GOODWILL_REDEMPTION"]
        assert rebooked_rows[0]["amount_cents"] == APPROVED_CENTS

    def test_care_operator_lists_guests_it_has_no_ownership_link_to(self, api):
        """A care identifier reads the guest roster without owning any row.

        "Because `GuestServices` and `PlatformAdmin` are opaque, no ownership comparison is performed for them; their reach is platform-wide."

        Design: Corner/rbac/rbac_guest_services_exclusive_and_shared_operations_all_succeed
        """
        world = _care_world(api)

        guests, meta = validate_paginated(api.list_guests(CARE_REVOKER_HEADERS))
        assert meta["total_count"] == 1
        assert guests[0]["id"] == world["guest_id"]
        assert guests[0]["email"] == world["guest"]["email"]


# The lapsed-hold window: a booking taken at 00:00 with the default 20 minute
# time to live has expired by 00:25.
SWEEP_CLOCK = "2026-09-01T00:25:00Z"


def _admin_world(api):
    """A published service carrying one unpaid PENDING hold."""
    world = _std_chain(api)
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    guest = FX.create_guest(api, display_name="Admin World Guest")
    reservation = FX.hold_seats(
        api, world["ticket_class_id"], guest["id"], party_size=2
    )
    world.update(
        {
            "guest": guest,
            "guest_id": guest["id"],
            "guest_headers": make_guest_headers(guest["id"]),
            "reservation": reservation,
            "reservation_id": reservation["id"],
        }
    )
    return world


class TestPlatformAdminAuthorityIsExclusiveAndNotSuperior:
    """The platform role owns onboarding, the sweep and the clock — only those."""

    def test_admin_sweep_expires_the_lapsed_hold_and_leaves_the_service_open(
        self, api
    ):
        """The sweep is the platform role's own operation and it lands.

        "The sweep advances every `PENDING` reservation whose `hold_expires_at_utc` the logical clock has reached along `PENDING → EXPIRED`."
        "Passing `close_service` as true additionally moves the service `PUBLISHED → CLOSED`."

        Design: Corner/rbac/rbac_platform_admin_ops_are_forbidden_to_others_and_grant_no_override
        """
        world = _admin_world(api)
        FX.set_clock(api, SWEEP_CLOCK)

        get_success_data(api.hold_sweep(world["service_id"], ADMIN_HEADERS))

        swept = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_fulfillment_status(swept, "EXPIRED")
        A.assert_payment_status(swept, "UNPAID")

        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=0, released=0, available=20, status="OPEN"
        )

        # The closing flag was never supplied, so the evening stays open.
        service = FX.read_service(api, world["service_id"], world["manager"])
        assert service["status"] == "PUBLISHED"

    def test_admin_onboarding_applies_the_documented_defaults(self, api):
        """Registering a restaurant and a guest is the platform role's alone.

        "Every knob is optional at registration and falls back to a documented default."
        "Everything else on a guest is a counter the platform maintains: `no_show_strikes`, `completed_reservations_count`, `transfers_initiated_count` and `lifetime_refunded_cents` all begin at 0, and `refund_scrutiny_flag` begins false."

        Design: Corner/rbac/rbac_platform_admin_ops_are_forbidden_to_others_and_grant_no_override
        """
        FX.set_clock(api, SETUP_CLOCK)

        restaurant = get_success_data(
            api.create_restaurant(
                {
                    "name": f"Second House {F.unique_suffix()}",
                    "service_charge_bp": 500,
                },
                ADMIN_HEADERS,
            )
        )
        A.assert_common_fields(restaurant)
        assert restaurant["service_charge_bp"] == 500
        for knob, default in C.RESTAURANT_DEFAULTS.items():
            if knob == "service_charge_bp":
                continue
            assert restaurant[knob] == default, knob

        guest = get_success_data(
            api.create_guest(
                {
                    "email": f"second.guest.{F.unique_suffix()}@example.com",
                    "display_name": "Second Guest",
                },
                ADMIN_HEADERS,
            )
        )
        A.assert_common_fields(guest)
        for field, default in C.GUEST_DEFAULTS.items():
            assert guest[field] == default, field

    def test_no_other_role_may_onboard_sweep_or_move_the_clock(self, api):
        """Eight attempts by the other four roles are all refused on the role.

        "A `PlatformAdmin` onboards restaurants and guests, drives the hold sweep, and sets the server's logical clock."
        "If the acting role is not among the roles listed for the endpoint being called, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/rbac_platform_admin_ops_are_forbidden_to_others_and_grant_no_override
        """
        world = _admin_world(api)
        FX.set_clock(api, SWEEP_CLOCK)
        guest_headers = world["guest_headers"]

        validate_error(
            api.create_restaurant(
                {"name": "Manager Cannot Onboard"}, world["manager"]
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_restaurant({"name": "Care Cannot Onboard"}, CARE_HEADERS),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_guest(F.guest_payload(), guest_headers),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_guest(F.guest_payload(), world["kitchen"]),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.hold_sweep(world["service_id"], world["manager"]),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.hold_sweep(world["service_id"], guest_headers),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.set_clock("2027-01-01T00:00:00Z", CARE_HEADERS),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.set_clock("2027-01-01T00:00:00Z", world["manager"]),
            E.ERR_UNAUTHORIZED,
            403,
        )

        # No restaurant was brought into existence by the refused calls.
        restaurants, meta = validate_paginated(
            api.list_restaurants(ADMIN_HEADERS, {"limit": 100})
        )
        assert meta["total_count"] == 1
        names = [row["name"] for row in restaurants]
        assert "Manager Cannot Onboard" not in names
        assert "Care Cannot Onboard" not in names

        # The refused clock writes left the logical clock where the platform
        # role last set it: a fresh hold still expires 20 minutes after 00:25.
        prober = FX.create_guest(api, display_name="Clock Prober")
        probe = FX.hold_seats(
            api, world["ticket_class_id"], prober["id"], party_size=2
        )
        assert F.parse_iso(probe["hold_expires_at_utc"]) == F.parse_iso(
            "2026-09-01T00:45:00Z"
        )
        # The unswept hold is still waiting, because no sweep ever ran.
        still_pending = FX.read_reservation(
            api, world["reservation_id"], guest_headers
        )
        A.assert_fulfillment_status(still_pending, "PENDING")

    def test_admin_authority_does_not_reach_into_the_other_roles_operations(
        self, api
    ):
        """The platform role is not a superuser over booking, floor or money.

        "If the acting role is not among the roles listed for the endpoint being called, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."
        "The checks below are evaluated **in the order given**, and the first check that fails is the error the client sees."

        Design: Corner/rbac/rbac_platform_admin_ops_are_forbidden_to_others_and_grant_no_override
        """
        world = _admin_world(api)
        version = FX.ticket_class_version(api, world["ticket_class_id"], ADMIN_HEADERS)

        validate_error(
            api.create_reservation(
                F.reservation_payload(
                    world["ticket_class_id"], world["guest_id"], version
                ),
                ADMIN_HEADERS,
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_service(
                F.service_payload(world["restaurant_id"], meal_period="LUNCH"),
                ADMIN_HEADERS,
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )
        # The role check sits above the path-identifier lookup, so these two
        # answer on the role and not on the missing row.
        validate_error(
            api.ack_dietary_note(
                NON_EXISTENT_UUID, F.ack_payload("ACCEPT"), ADMIN_HEADERS
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.decide_refund_exception(
                NON_EXISTENT_UUID,
                F.decide_payload(
                    decision="DENIED", decision_note_code="OUT_OF_POLICY"
                ),
                ADMIN_HEADERS,
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.take_payment(
                world["reservation_id"], F.payment_payload(DEPOSIT_CENTS), ADMIN_HEADERS
            ),
            E.ERR_UNAUTHORIZED,
            403,
        )

        # Nothing was booked, scheduled or paid.
        reservation = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_fulfillment_status(reservation, "PENDING")
        A.assert_payment_status(reservation, "UNPAID")
        assert reservation["amount_paid_cents"] == 0
        services, services_meta = validate_paginated(
            api.list_restaurant_services(world["restaurant_id"], world["manager"])
        )
        assert services_meta["total_count"] == 1
        assert services[0]["id"] == world["service_id"]


def _two_restaurant_world(api):
    """Two restaurants: the first fully trading with a CONFIRMED booking and a
    pending dietary note, the second owning nothing but a table of its own.
    """
    world = _std_chain(api)
    table_a = FX.create_table(
        api, world["restaurant_id"], table_code="TA", seats_min=2, seats_max=4
    )
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    guest = FX.create_guest(api, display_name="House A Guest")
    reservation = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest["id"], party_size=2
    )
    note = FX.add_dietary_note(
        api,
        reservation["id"],
        guest["id"],
        guest_index=1,
        severity="ALLERGY",
        restriction_code="SOY",
        note_text="No soy in any course.",
    )
    restaurant_b = FX.create_restaurant(api, service_charge_bp=725)
    table_b = FX.create_table(
        api, restaurant_b["id"], table_code="TB", seats_min=2, seats_max=4
    )
    world.update(
        {
            "table_a": table_a,
            "table_a_id": table_a["id"],
            "guest": guest,
            "guest_id": guest["id"],
            "guest_headers": make_guest_headers(guest["id"]),
            "reservation": reservation,
            "reservation_id": reservation["id"],
            "note": note,
            "note_id": note["id"],
            "restaurant_b": restaurant_b,
            "restaurant_b_id": restaurant_b["id"],
            "manager_b": make_restaurant_headers(restaurant_b["id"]),
            "kitchen_b": make_kitchen_headers(restaurant_b["id"]),
            "table_b": table_b,
            "table_b_id": table_b["id"],
        }
    )
    return world


class TestRestaurantBackedRolesAreConfinedToTheirOwnHouse:
    """Both restaurant-backed roles carry a restaurant id, and it is compared."""

    def test_a_second_managers_id_unlocks_nothing_of_the_first_houses(self, api):
        """Five manager operations on another house's rows are all refused.

        "When `X-User-Role` is `RestaurantManager`, `X-User-ID` is the `id` of the acting `Restaurant`."
        "Ownership checks compare `X-User-ID` to the `restaurant_id` of the target table, experience package, add-on or service, and for reservation-scoped floor operations to the `restaurant_id` of the service the reservation belongs to."
        "An entity-backed role acting on a resource it does not own is rejected with `ERR_FORBIDDEN_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/rbac_manager_and_kitchen_lead_cannot_act_on_another_restaurants_rows
        """
        world = _two_restaurant_world(api)
        manager_b = world["manager_b"]

        validate_error(
            api.assign_table(
                world["reservation_id"],
                F.assign_table_payload(world["table_a_id"], SEATING_START),
                manager_b,
            ),
            E.ERR_FORBIDDEN_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.set_demand_tier(
                world["service_id"], F.demand_tier_payload("PEAK"), manager_b
            ),
            E.ERR_FORBIDDEN_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.pause_ticket_class(world["ticket_class_id"], manager_b),
            E.ERR_FORBIDDEN_RESOURCE_OWNER,
            403,
        )
        # The ownership target of a create is the restaurant named in the body.
        validate_error(
            api.create_table(
                F.table_payload(world["restaurant_id"], table_code="TX"), manager_b
            ),
            E.ERR_FORBIDDEN_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.get_table(world["table_a_id"], manager_b),
            E.ERR_FORBIDDEN_RESOURCE_OWNER,
            403,
        )

        # The first house is exactly as it was.
        reservation = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_fulfillment_status(reservation, "CONFIRMED")
        assert reservation["assigned_table_id"] is None
        service = FX.read_service(api, world["service_id"], world["manager"])
        assert service["demand_tier"] == "STANDARD"
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        assert ticket_class["status"] == "OPEN"

        # And the second house still owns nothing but its own single table.
        tables_b, meta_b = validate_paginated(
            api.list_restaurant_tables(world["restaurant_b_id"], manager_b)
        )
        assert meta_b["total_count"] == 1
        assert tables_b[0]["id"] == world["table_b_id"]
        services_b, services_meta_b = validate_paginated(
            api.list_restaurant_services(world["restaurant_b_id"], manager_b)
        )
        assert services_meta_b["total_count"] == 0
        assert services_b == []

    def test_a_second_kitchen_lead_can_neither_read_nor_ack_the_first_houses_notes(
        self, api
    ):
        """The lead's restaurant id is compared on the note write and the read.

        "When `X-User-Role` is `KitchenLead`, `X-User-ID` is likewise the `id` of the acting `Restaurant`, and the same restaurant-ownership comparison applies to the dietary notes and reservations the lead may read or acknowledge."
        "For the entity-backed roles, the acting `X-User-ID` owns the target, on every guest-scoped and restaurant-scoped endpoint — otherwise `ERR_FORBIDDEN_RESOURCE_OWNER`."

        Design: Corner/rbac/rbac_manager_and_kitchen_lead_cannot_act_on_another_restaurants_rows
        """
        world = _two_restaurant_world(api)
        kitchen_b = world["kitchen_b"]

        validate_error(
            api.ack_dietary_note(
                world["note_id"], F.ack_payload("ACCEPT"), kitchen_b
            ),
            E.ERR_FORBIDDEN_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.list_reservation_dietary_notes(world["reservation_id"], kitchen_b),
            E.ERR_FORBIDDEN_RESOURCE_OWNER,
            403,
        )

        # The note was neither decided nor stamped with the wrong house.
        note = FX.read_note(api, world["note_id"], world["kitchen"])
        assert note["ack_status"] == "PENDING"
        assert note["acked_by_user_id"] is None

    def test_the_owning_house_succeeds_but_a_foreign_table_is_a_provenance_error(
        self, api
    ):
        """Past the ownership gate, a table from elsewhere fails on provenance.

        "Assigning a table is a `RestaurantManager` action carrying a `table_id` and a `seat_from_utc` seating instant."
        "The table must also belong to the same restaurant as the reservation's service, failing which the assignment is rejected with `ERR_TABLE_RESTAURANT_MISMATCH`, and the reservation's `party_size` must fall within the table's `seats_min` and `seats_max` inclusive, failing which the rejection is `ERR_TABLE_PARTY_SIZE_MISMATCH`."

        Design: Corner/rbac/rbac_manager_and_kitchen_lead_cannot_act_on_another_restaurants_rows
        """
        world = _two_restaurant_world(api)

        # The acting manager owns the reservation's service, so the ownership
        # check passes and the mismatch of the table itself is what answers.
        validate_error(
            api.assign_table(
                world["reservation_id"],
                F.assign_table_payload(world["table_b_id"], SEATING_START),
                world["manager"],
            ),
            E.ERR_TABLE_RESTAURANT_MISMATCH,
            422,
        )

        assigned = get_success_data(
            api.assign_table(
                world["reservation_id"],
                F.assign_table_payload(world["table_a_id"], SEATING_START),
                world["manager"],
            )
        )
        assert assigned["assigned_table_id"] == world["table_a_id"]
        A.assert_fulfillment_status(assigned, "CONFIRMED")

        acked = get_success_data(
            api.ack_dietary_note(
                world["note_id"], F.ack_payload("ACCEPT"), world["kitchen"]
            )
        )
        assert acked["ack_status"] == "ACKED"
        assert acked["acked_by_user_id"] == world["restaurant_id"]


def _crossed_lineage_world(api):
    """Two guests, two settled cancellations, and two exceptions filed by two
    different care operators — one each, on opposite reservations.
    """
    world = _std_chain(api)
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    guest_one = FX.create_guest(api, display_name="Crossed Guest One")
    guest_two = FX.create_guest(api, display_name="Crossed Guest Two")
    reservation_one = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest_one["id"], party_size=2
    )
    reservation_two = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest_two["id"], party_size=2
    )
    FX.set_clock(api, CANCEL_AT_48H)
    FX.cancel(api, reservation_one["id"], guest_one["id"])
    FX.cancel(api, reservation_two["id"], guest_two["id"])

    care_one = make_care_headers(CARE_ONE_ID)
    care_two = make_care_headers(CARE_TWO_ID)
    exception_one = FX.file_refund_exception(
        api,
        reservation_one["id"],
        FORFEITED_CENTS,
        headers=care_one,
        reason_code="MEDICAL",
    )
    exception_two = FX.file_refund_exception(
        api,
        reservation_two["id"],
        FORFEITED_CENTS,
        headers=care_two,
        reason_code="TRAVEL_DISRUPTION",
    )
    world.update(
        {
            "care_one": care_one,
            "care_two": care_two,
            "guest_one_id": guest_one["id"],
            "guest_two_id": guest_two["id"],
            "guest_one_headers": make_guest_headers(guest_one["id"]),
            "guest_two_headers": make_guest_headers(guest_two["id"]),
            "reservation_one_id": reservation_one["id"],
            "reservation_two_id": reservation_two["id"],
            "exception_one": exception_one,
            "exception_two": exception_two,
        }
    )
    return world


def _crossed_decisions(api, world):
    """Each operator adjudicates the exception the other one filed."""
    decided_one = FX.decide_refund_exception(
        api,
        world["exception_one"]["id"],
        decision="APPROVED",
        approved_cents=APPROVED_CENTS,
        decision_note_code="PARTIAL_GOODWILL",
        headers=world["care_two"],
    )
    decided_two = FX.decide_refund_exception(
        api,
        world["exception_two"]["id"],
        decision="APPROVED",
        approved_cents=APPROVED_CENTS,
        decision_note_code="PARTIAL_GOODWILL",
        headers=world["care_one"],
    )
    return decided_one, decided_two


def _crossed_credits(api, world):
    """Each operator compensates the exception it filed itself, which is legal
    because the comparison at issuance is against the decider.
    """
    credit_one = FX.issue_goodwill_credit(
        api,
        world["exception_one"]["id"],
        SHORTFALL_CENTS,
        CREDIT_EXPIRY,
        headers=world["care_one"],
    )
    credit_two = FX.issue_goodwill_credit(
        api,
        world["exception_two"]["id"],
        SHORTFALL_CENTS,
        CREDIT_EXPIRY,
        headers=world["care_two"],
    )
    return credit_one, credit_two


class TestSegregationOfDutiesIsScopedToTheRowNotTheOperator:
    """The three comparisons look only at the ids recorded on the row in hand."""

    def test_each_operator_may_decide_the_exception_the_other_one_filed(self, api):
        """Two crossed adjudications, no clash, because the filers differ.

        "Compensating a guest is a three-step chain — file, decide, compensate — and no single operator identifier may occupy two adjacent steps of it."
        "The operator deciding a refund exception must have an `X-User-ID` different from the `requested_by_user_id` recorded when the exception was filed."

        Design: Corner/rbac/segregation_of_duties_is_scoped_per_exception_not_per_operator
        """
        world = _crossed_lineage_world(api)
        assert world["exception_one"]["requested_by_user_id"] == CARE_ONE_ID
        assert world["exception_two"]["requested_by_user_id"] == CARE_TWO_ID

        decided_one, decided_two = _crossed_decisions(api, world)

        assert decided_one["status"] == "APPROVED"
        assert decided_one["decided_by_user_id"] == CARE_TWO_ID
        assert decided_one["approved_cents"] == APPROVED_CENTS
        assert decided_one["shortfall_cents"] == SHORTFALL_CENTS
        assert decided_two["status"] == "APPROVED"
        assert decided_two["decided_by_user_id"] == CARE_ONE_ID
        assert decided_two["approved_cents"] == APPROVED_CENTS
        assert decided_two["shortfall_cents"] == SHORTFALL_CENTS

        # Both approvals paid out, on their own reservation only.
        for reservation_id, headers in (
            (world["reservation_one_id"], world["guest_one_headers"]),
            (world["reservation_two_id"], world["guest_two_headers"]),
        ):
            rows = FX.ledger_rows(api, reservation_id, CARE_HEADERS)
            exception_rows = [
                row for row in rows if row["memo_code"] == "REFUND_EXCEPTION"
            ]
            assert sorted(row["kind"] for row in exception_rows) == [
                "FORFEITURE_REVERSAL",
                "REFUND",
            ]
            assert [row["amount_cents"] for row in exception_rows] == [
                APPROVED_CENTS,
                APPROVED_CENTS,
            ]
            reservation = FX.read_reservation(api, reservation_id, headers)
            assert reservation["forfeited_cents"] == FORFEITED_CENTS - APPROVED_CENTS
            assert reservation["refunded_cents"] == REFUNDED_CENTS + APPROVED_CENTS
            A.assert_settled_ledger_identity(reservation)

    def test_the_filer_may_issue_the_credit_the_other_operator_approved(self, api):
        """Issuance is barred only against the decider, so the filer may issue.

        "The operator issuing a goodwill credit against a decided exception must have an `X-User-ID` different from the `decided_by_user_id` recorded on that exception."
        "Issuance copies `guest_id` and `restaurant_id` from the exception's reservation and its service, so a credit is scoped to one guest at one restaurant; records the acting `X-User-ID` as `issued_by_user_id`, which must differ from the exception's `decided_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; and initialises `remaining_cents` to `issued_cents` with `redeemed_cents` and `revoked_cents` at 0 and `status` at `ISSUED`."

        Design: Corner/rbac/segregation_of_duties_is_scoped_per_exception_not_per_operator
        """
        world = _crossed_lineage_world(api)
        _crossed_decisions(api, world)
        credit_one, credit_two = _crossed_credits(api, world)

        assert credit_one["issued_by_user_id"] == CARE_ONE_ID
        assert credit_two["issued_by_user_id"] == CARE_TWO_ID
        for credit in (credit_one, credit_two):
            assert credit["status"] == "ISSUED"
            assert credit["issued_cents"] == SHORTFALL_CENTS
            assert credit["remaining_cents"] == SHORTFALL_CENTS
            assert credit["redeemed_cents"] == 0
            assert credit["revoked_cents"] == 0
            assert credit["restaurant_id"] == world["restaurant_id"]
            A.assert_credit_identity(credit)
            A.assert_credit_status(credit)

        # Neither credit picked up the other lineage's guest or exception.
        assert credit_one["guest_id"] == world["guest_one_id"]
        assert credit_one["refund_exception_id"] == world["exception_one"]["id"]
        assert credit_two["guest_id"] == world["guest_two_id"]
        assert credit_two["refund_exception_id"] == world["exception_two"]["id"]

    def test_each_operator_may_revoke_the_credit_the_other_one_issued(self, api):
        """Revocation compares against the issuer of that credit and nothing else.

        "The operator revoking a goodwill credit must have an `X-User-ID` different from the `issued_by_user_id` recorded on that credit."
        "Revocation sets `revoked_cents` to whatever `remaining_cents` stood at and sets `remaining_cents` to 0, so invariant I3 still holds, and moves the credit along `ISSUED → REVOKED` or `PARTIALLY_REDEEMED → REVOKED` as its prior state dictates."

        Design: Corner/rbac/segregation_of_duties_is_scoped_per_exception_not_per_operator
        """
        world = _crossed_lineage_world(api)
        _crossed_decisions(api, world)
        credit_one, credit_two = _crossed_credits(api, world)

        revoked_one = FX.revoke_goodwill_credit(
            api, credit_one["id"], headers=world["care_two"]
        )
        revoked_two = FX.revoke_goodwill_credit(
            api, credit_two["id"], headers=world["care_one"]
        )

        for revoked in (revoked_one, revoked_two):
            assert revoked["status"] == "REVOKED"
            assert revoked["revoked_cents"] == SHORTFALL_CENTS
            assert revoked["remaining_cents"] == 0
            assert revoked["redeemed_cents"] == 0
            A.assert_credit_identity(revoked)
            A.assert_credit_status(revoked)

        assert revoked_one["id"] == credit_one["id"]
        assert revoked_two["id"] == credit_two["id"]
