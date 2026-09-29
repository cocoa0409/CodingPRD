"""Endpoint surface: the create-read-list shape, action preconditions and link resolution."""
from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    calculate_run,
    confirm_booking,
    controller,
    create_advisor_agreement_payload,
    create_advisor_payload,
    new_advisor,
    new_booking,
    new_client,
    new_consortium,
    new_split_schedule,
    new_supplier,
    open_run,
    ops,
    read_advisor,
    read_agreement,
    read_booking,
    read_run,
    set_clock,
    setup_active_advisor,
    sign_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
ELITE_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.75},
    {"tier_level": 2, "min_production_cents": 4_000_000, "advisor_pct": 0.85},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]

MERIDIAN = {
    "name": "Meridian Air",
    "accreditation_scheme": "ARC",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 30,
}


def _standard_schedule(**overrides):
    payload = {
        "name": "Standard 2026",
        "tiers": STANDARD_TIERS,
        "platform_fee_tiers": FLAT_FEE_TIERS,
        "chargeback_retention_pct": 0.10,
    }
    payload.update(overrides)
    return new_split_schedule(**payload)


def test_an_agreement_is_created_read_back_and_listed_and_changed_only_by_its_successor():
    """PRD §3.2: "The server stamps `signed_at` from the logical clock, sets the new row's
    `status` to `ACTIVE`, and moves the advisor's previously `ACTIVE` agreement, if one
    exists, from `ACTIVE` to `SUPERSEDED`"

    Design: Corner/endpoints/corner_create_read_list_surface_has_no_update_or_delete
    """
    first_schedule = _standard_schedule()
    second_schedule = _standard_schedule(
        name="Elite 2026",
        tiers=ELITE_TIERS,
        platform_fee_tiers=[{"min_share_cents": 0, "fee_pct": 0.04}],
    )
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )

    first = validate_success(
        api_client.create_advisor_agreement(
            advisor["id"],
            create_advisor_agreement_payload(
                first_schedule["id"],
                advisor["version"],
                effective_date="2026-01-01",
                post_departure_advisor_pct=0.50,
            ),
            ops(),
        ),
        201,
    )
    assert first["status"] == "ACTIVE"
    assert first["signed_at"].startswith("2026-08-01T00:00:00")

    read_back = read_agreement(first["id"])
    assert read_back["split_schedule_id"] == first_schedule["id"]
    assert read_back["id"] == first["id"]

    bumped = read_advisor(advisor["id"])
    assert bumped["version"] == advisor["version"] + 1

    second = validate_success(
        api_client.create_advisor_agreement(
            advisor["id"],
            create_advisor_agreement_payload(
                second_schedule["id"],
                bumped["version"],
                effective_date="2026-07-01",
                post_departure_advisor_pct=0.55,
            ),
            ops(),
        ),
        201,
    )

    rows, meta = validate_paginated(
        api_client.list_advisor_agreements(ops(), {"advisor_id": advisor["id"]})
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert read_agreement(first["id"])["status"] == "SUPERSEDED"
    assert read_agreement(second["id"])["status"] == "ACTIVE"

    _, other_meta = validate_paginated(
        api_client.list_advisor_agreements(ops(), {"advisor_id": NON_EXISTENT_UUID})
    )
    assert other_meta["total_count"] == 0


def test_marking_travel_complete_needs_both_the_state_and_the_clock():
    """PRD §3.6: "The logical clock must have reached or passed the booking's
    `travel_end_date`; an attempt made earlier is refused with `ERR_TRAVELED_TOO_EARLY`
    (HTTP 409), and an attempt against a booking that is not `CONFIRMED` with
    `ERR_INVALID_BOOKING_STATE`."

    Design: Corner/endpoints/corner_traveled_action_enforces_clock_and_state_preconditions
    """
    supplier = new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=_standard_schedule(),
        suppliers=[supplier],
    )
    advisor = ctx["advisor"]
    client = new_client(
        advisor["id"], full_name="Nadia Okoye", home_state_code="NY"
    )
    booking = new_booking(
        advisor["id"],
        supplier["id"],
        client["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-08-05",
        travel_end_date="2026-08-10",
    )

    validate_error(
        api_client.mark_booking_traveled(booking["id"], ops()),
        "ERR_INVALID_BOOKING_STATE",
        409,
    )

    confirmed = confirm_booking(booking["id"], supplier["id"])
    assert confirmed["commission_status"] == "EXPECTED"

    validate_error(
        api_client.mark_booking_traveled(booking["id"], ops()),
        "ERR_TRAVELED_TOO_EARLY",
        409,
    )
    assert read_booking(booking["id"])["booking_status"] == "CONFIRMED"

    set_clock("2026-08-10T00:00:00Z")
    travelled = validate_success(
        api_client.mark_booking_traveled(booking["id"], ops())
    )
    assert travelled["booking_status"] == "TRAVELED"
    assert travelled["commission_status"] == "EXPECTED"

    validate_error(
        api_client.mark_booking_traveled(booking["id"], ops()),
        "ERR_INVALID_BOOKING_STATE",
        409,
    )
    assert read_booking(booking["id"])["booking_status"] == "TRAVELED"
    assert read_advisor(advisor["id"])["production_ytd_provisional_cents"] == 100_000


def test_both_link_bearing_creates_refuse_an_identifier_that_resolves_to_nothing():
    """PRD §2.8: "only afterwards are foreign keys supplied in the body resolved, in the
    order the fields are listed for that endpoint."
    PRD §2.8: "A rejected request has no effect whatsoever: no row is created, no counter
    moves, no `version` increments."

    Design: Corner/endpoints/corner_optional_consortium_and_schedule_links_must_resolve
    """
    consortium = new_consortium(
        name="Voyage Alliance",
        membership_fee_cents=50_000,
        marketing_fund_accrual_pct=0.02,
        consortium_channel_bonus_pct=0.01,
    )
    schedule = _standard_schedule()

    validate_error(
        api_client.create_advisor(
            create_advisor_payload(
                legal_name="Ghost Member",
                email="ghost.member@example.com",
                seller_of_travel_state="NY",
                consortium_id=NON_EXISTENT_UUID,
            ),
            ops(),
        ),
        "ERR_CONSORTIUM_NOT_FOUND",
        404,
    )
    _, empty = validate_paginated(api_client.list_advisors(ops()))
    assert empty["total_count"] == 0

    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
        consortium_id=consortium["id"],
    )
    assert advisor["consortium_id"] == consortium["id"]

    validate_error(
        api_client.create_advisor_agreement(
            advisor["id"],
            create_advisor_agreement_payload(
                NON_EXISTENT_UUID, advisor["version"], effective_date="2026-01-01"
            ),
            ops(),
        ),
        "ERR_SPLIT_SCHEDULE_NOT_FOUND",
        404,
    )
    assert read_advisor(advisor["id"])["version"] == advisor["version"]

    agreement = sign_agreement(
        advisor["id"], schedule["id"], effective_date="2026-01-01"
    )
    assert agreement["split_schedule_id"] == schedule["id"]

    rows, meta = validate_paginated(
        api_client.list_advisors(ops(), {"consortium_id": consortium["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [advisor["id"]]

    rows, meta = validate_paginated(
        api_client.list_advisor_agreements(
            ops(), {"split_schedule_id": schedule["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [agreement["id"]]


def test_a_run_with_nothing_to_settle_still_calculates_and_posts():
    """PRD §3.8: "An empty run is not an error: a run whose `statement_count` is 0 may be
    posted, and it transitions straight through to `CLOSED` within the same request."

    Design: Corner/endpoints/corner_empty_settlement_run_may_still_be_posted
    """
    schedule = _standard_schedule()
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    sign_agreement(advisor["id"], schedule["id"], effective_date="2026-01-01")

    never_calculated = open_run("2026-06")
    target = open_run("2026-07")
    assert target["status"] == "OPEN"
    assert target["statement_count"] == 0

    validate_error(
        api_client.post_settlement_run(never_calculated["id"], controller("ctrl-2")),
        "ERR_INVALID_RUN_STATE",
        409,
    )
    assert read_run(never_calculated["id"])["status"] == "OPEN"

    calculated = calculate_run(target["id"], "ctrl-1")
    assert calculated["status"] == "CALCULATED"
    assert calculated["statement_count"] == 0

    posted = validate_success(
        api_client.post_settlement_run(target["id"], controller("ctrl-2"))
    )
    assert posted["statement_count"] == 0
    assert posted["status"] == "CLOSED"

    final = read_run(target["id"])
    assert final["gross_commission_cents"] == 0
    assert final["advisor_share_total_cents"] == 0
    assert final["chargeback_total_cents"] == 0
    assert final["platform_fee_total_cents"] == 0
    assert final["marketing_fund_total_cents"] == 0
    assert final["net_payout_total_cents"] == 0
    assert read_advisor(advisor["id"])["lifetime_settled_share_cents"] == 0

    _, meta = validate_paginated(api_client.list_advisor_statements(ops()))
    assert meta["total_count"] == 0
