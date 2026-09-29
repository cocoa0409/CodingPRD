"""
Error surfaces reached one at a time: every existence check, every state gate,
the frozen floor, the money guards, the calendar guards and the one coherence
check that pre-empts booth membership.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    AppointmentState,
    BoothStatus,
    DealStatus,
    FloorPosture,
    FulfillmentStatus,
    ObligationStatus,
    QualificationStatus,
    ShowStatus,
    SpaceContractStatus,
    ViolationStatus,
    factories as f,
    fixtures as fx,
    make_director_headers,
    make_floor_manager_headers,
    make_sales_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)

REP = make_sales_rep_headers("u_sr_1")
DIRECTOR = make_director_headers("u_sd_1")
FLOOR = make_floor_manager_headers("u_fm_1")

UNKNOWN_VENUE_CONTRACT_ID = "00000000-0000-4000-8000-0000000000a1"
UNKNOWN_SPACE_CONTRACT_ID = "00000000-0000-4000-8000-0000000000a2"
UNKNOWN_APPOINTMENT_ID = "00000000-0000-4000-8000-0000000000a3"
UNKNOWN_PACKAGE_ID = "00000000-0000-4000-8000-0000000000a4"
UNKNOWN_DEAL_ID = "00000000-0000-4000-8000-0000000000a5"
UNKNOWN_OBLIGATION_ID = "00000000-0000-4000-8000-0000000000a6"
UNKNOWN_RULE_VIOLATION_ID = "00000000-0000-4000-8000-0000000000a7"


def _two_deal_env(client: ApiClient) -> dict:
    """
    One package holding both its units: Alder's deal signed with two pending
    obligations, Basalt's deal still proposed.
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100])
    show_id = env["show"]["id"]
    alder = fx.exhibitor(client, "Alder Textiles",
                         contact_email="space@alder.example",
                         consecutive_years=1, headers=fx.SALES_REP_HEADERS)
    basalt = fx.exhibitor(client, "Basalt Cookware",
                          contact_email="space@basalt.example",
                          consecutive_years=4, headers=fx.SALES_REP_HEADERS)
    package = fx.sponsorship_package(
        client, show_id, package_code="PLATINUM", list_price_cents=1000000,
        price_floor_cents=700000, inventory_total=2,
        obligation_codes=["LOGO_PLACEMENT", "STAGE_BANNER"],
        priority_point_value=40,
    )
    signed = fx.signed_deal(client, package["id"], alder["id"], 900000,
                            proposer_headers=REP, signer_headers=DIRECTOR)
    proposed = fx.proposed_deal(client, package["id"], basalt["id"], 900000,
                                headers=REP)
    obligations = fx.read_obligations(client, signed["id"])
    assert len(obligations) == 2
    env.update({"show_id": show_id, "alder": alder, "basalt": basalt,
                "package": package, "signed_deal": signed,
                "proposed_deal": proposed, "obligations": obligations})
    return env


def _package_row(client: ApiClient, show_id: str, package_id: str) -> dict:
    rows, _ = validate_paginated(
        client.list_sponsorship_packages(show_id, fx.DIRECTOR_HEADERS)
    )
    return next(row for row in rows if row["id"] == package_id)


def test_six_unknown_identifiers_each_name_the_entity_that_was_missing(
    client: ApiClient,
):
    """
    A read and an action for each of six entity types, all against ids that
    resolve to nothing.

    "**Existence**, path resources before body references, in this order: venue
    contract (`ERR_VENUE_CONTRACT_NOT_FOUND`), show (`ERR_SHOW_NOT_FOUND`),
    exhibitor (`ERR_EXHIBITOR_NOT_FOUND`), booth (`ERR_BOOTH_NOT_FOUND`), space
    contract (`ERR_SPACE_CONTRACT_NOT_FOUND`), selection appointment
    (`ERR_APPOINTMENT_NOT_FOUND`), sponsorship package
    (`ERR_SPONSORSHIP_PACKAGE_NOT_FOUND`), sponsorship deal
    (`ERR_SPONSORSHIP_DEAL_NOT_FOUND`), fulfillment obligation
    (`ERR_OBLIGATION_NOT_FOUND`), registration (`ERR_REGISTRATION_NOT_FOUND`), rule
    violation (`ERR_RULE_VIOLATION_NOT_FOUND`), each HTTP 404."

    Design: Corner/errors/every_missing_reference_reports_its_own_entity_not_found
    """
    env = _two_deal_env(client)
    pinned_version = fx.show_version(client, env["show_id"])

    validate_error(
        client.get_venue_contract(UNKNOWN_VENUE_CONTRACT_ID, fx.DIRECTOR_HEADERS),
        ApiErrorId.VENUE_CONTRACT_NOT_FOUND,
        404,
    )
    validate_error(
        client.get_space_contract(UNKNOWN_SPACE_CONTRACT_ID, fx.SALES_REP_HEADERS),
        ApiErrorId.SPACE_CONTRACT_NOT_FOUND,
        404,
    )
    validate_error(
        client.exercise_appointment(
            UNKNOWN_APPOINTMENT_ID, f.exercise_payload(pinned_version, 200), REP
        ),
        ApiErrorId.APPOINTMENT_NOT_FOUND,
        404,
    )
    validate_error(
        client.create_sponsorship_deal(
            UNKNOWN_PACKAGE_ID,
            f.sponsorship_deal_payload(env["alder"]["id"], 900000), REP,
        ),
        ApiErrorId.SPONSORSHIP_PACKAGE_NOT_FOUND,
        404,
    )
    validate_error(
        client.get_sponsorship_deal(UNKNOWN_DEAL_ID, fx.SALES_REP_HEADERS),
        ApiErrorId.SPONSORSHIP_DEAL_NOT_FOUND,
        404,
    )
    validate_error(
        client.adjudicate(UNKNOWN_RULE_VIOLATION_ID,
                          f.adjudicate_payload("UPHELD"), DIRECTOR),
        ApiErrorId.RULE_VIOLATION_NOT_FOUND,
        404,
    )

    assert fx.show_version(client, env["show_id"]) == pinned_version
    package = _package_row(client, env["show_id"], env["package"]["id"])
    assert package["inventory_committed"] == 2
    assert package["inventory_available"] == 0


def test_a_real_obligation_under_the_wrong_deal_is_simply_not_found(
    client: ApiClient,
):
    """
    Under a nested path the pair is the identity: the obligation of the signed deal
    does not exist under the proposed one.

    "An obligation that exists but whose `sponsorship_deal_id` points at a
    different deal is reported as `ERR_OBLIGATION_NOT_FOUND` (HTTP 404), not as a
    validation error — under a nested path, the path *is* the identity."  "the deal
    identifier first, the obligation identifier second, resolved left to right as
    §2.10 requires"

    Design: Corner/errors/every_missing_reference_reports_its_own_entity_not_found
    """
    env = _two_deal_env(client)
    signed_id = env["signed_deal"]["id"]
    proposed_id = env["proposed_deal"]["id"]
    obligation = env["obligations"][0]

    validate_error(
        client.resolve_obligation(signed_id, UNKNOWN_OBLIGATION_ID,
                                  f.resolve_obligation_payload("DELIVERED"), FLOOR),
        ApiErrorId.OBLIGATION_NOT_FOUND,
        404,
    )
    validate_error(
        client.resolve_obligation(proposed_id, obligation["id"],
                                  f.resolve_obligation_payload("DELIVERED"), FLOOR),
        ApiErrorId.OBLIGATION_NOT_FOUND,
        404,
    )

    still_pending = {row["id"]: row
                     for row in fx.read_obligations(client, signed_id)}
    assert still_pending[obligation["id"]]["status"] == ObligationStatus.PENDING
    assert fx.read_deal(client, signed_id)["resolved_obligation_count"] == 0

    untouched = fx.read_deal(client, proposed_id)
    assert untouched["deal_status"] == DealStatus.PROPOSED
    assert untouched["fulfillment_status"] == FulfillmentStatus.NOT_STARTED


# ── Three rows, three gates: the Show, the appointment and the obligation ────
DESK_CLOCK = "2027-03-01T09:30:00Z"
C050 = f.inline_booth_payload("C050", 10, 20)


def _gated_env(client: ApiClient) -> dict:
    """
    Harbor Ceramics has already spent its desk slot on A100 and the producer has
    already delivered the one banner it promised.
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    harbor = fx.exhibitor(client, "Harbor Ceramics",
                          contact_email="space@harbor.example",
                          consecutive_years=2, headers=fx.SALES_REP_HEADERS)
    package = fx.sponsorship_package(
        client, show_id, package_code="BANNER", list_price_cents=500000,
        price_floor_cents=400000, inventory_total=1,
        obligation_codes=["LOGO_PLACEMENT"], priority_point_value=4,
    )
    deal = fx.signed_deal(client, package["id"], harbor["id"], 500000,
                          proposer_headers=REP, signer_headers=DIRECTOR)
    obligation = fx.read_obligations(client, deal["id"])[0]
    delivered = validate_success(
        client.resolve_obligation(
            deal["id"], obligation["id"],
            f.resolve_obligation_payload(
                "DELIVERED", note="Banner hung on the west wall"),
            FLOOR,
        )
    )
    assert delivered["status"] == ObligationStatus.DELIVERED

    appointment = fx.scheduled_appointment(
        client, show_id, harbor["id"], 1,
        "2027-03-01T09:00:00Z", "2027-03-01T11:00:00Z",
    )
    fx.set_clock(client, DESK_CLOCK)
    validate_success(client.advance_selection_round(show_id, fx.DIRECTOR_HEADERS))

    harbor_headers = fx.make_exhibitor_headers(harbor["id"])
    exercised = validate_success(
        client.exercise_appointment(
            appointment["id"],
            f.exercise_payload(fx.show_version(client, show_id), 400,
                               premium_placement_requested=True,
                               booth_ids=[env["booth_by_number"]["A100"]["id"]]),
            harbor_headers,
        ),
        201,
    )
    env.update({
        "show_id": show_id, "harbor": harbor, "harbor_headers": harbor_headers,
        "package": package, "deal": deal, "obligation": obligation,
        "appointment": appointment, "exercised": exercised,
    })
    return env


def test_the_post_show_report_is_refused_while_the_edition_is_still_selecting(
    client: ApiClient,
):
    """
    The reader has the right role and the edition exists; only its status refuses.

    "It is a computed read available to a `ShowDirector` or a `SalesRep`, and only
    for an edition whose status is `CLOSED`; asking for it earlier is refused with
    `ERR_SHOW_NOT_CLOSED`."

    Design: Corner/errors/each_state_gated_read_or_action_reports_its_own_status_error
    """
    env = _gated_env(client)

    validate_error(
        client.get_post_show_report(env["show_id"], fx.DIRECTOR_HEADERS),
        ApiErrorId.SHOW_NOT_CLOSED,
        409,
    )

    assert fx.read_show(client, env["show_id"])["status"] == ShowStatus.SPACE_SELECTION


def test_an_exercised_appointment_refuses_the_replay_before_counting_contracts(
    client: ApiClient,
):
    """
    A second exercise of the same slot would also be a duplicate hold, but the
    state gate is reached first and reports the appointment.

    "The appointment must be in state `ACTIVE`, or the request fails with
    `ERR_INVALID_APPOINTMENT_STATE`."  "**Per-row state preconditions**, in this
    order: ... appointment state (`ERR_INVALID_APPOINTMENT_STATE`)"  "**Inventory,
    uniqueness and bounded loops**, in this order: ... duplicate active contract
    (`ERR_DUPLICATE_ACTIVE_CONTRACT`)"

    Design: Corner/errors/each_state_gated_read_or_action_reports_its_own_status_error
    """
    env = _gated_env(client)
    show_id = env["show_id"]
    assert env["exercised"]["status"] == SpaceContractStatus.OFFERED
    assert (
        validate_success(
            client.get_selection_appointment(env["appointment"]["id"],
                                             fx.DIRECTOR_HEADERS)
        )["state"]
        == AppointmentState.EXERCISED
    )
    pinned_version = fx.show_version(client, show_id)

    validate_error(
        client.exercise_appointment(
            env["appointment"]["id"],
            f.exercise_payload(pinned_version, 200),
            env["harbor_headers"],
        ),
        ApiErrorId.INVALID_APPOINTMENT_STATE,
        409,
    )

    appointment = validate_success(
        client.get_selection_appointment(env["appointment"]["id"],
                                        fx.DIRECTOR_HEADERS)
    )
    assert appointment["state"] == AppointmentState.EXERCISED

    rows, meta = validate_paginated(
        client.list_space_contracts(
            fx.SALES_REP_HEADERS,
            {"show_id": show_id, "exhibitor_id": env["harbor"]["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["status"] == SpaceContractStatus.OFFERED
    assert fx.show_version(client, show_id) == pinned_version


def test_a_delivered_obligation_refuses_the_replay_and_credits_four_points_once(
    client: ApiClient,
):
    """
    A different operator, a different disposition, a reason supplied — and still
    refused, because the credit has already fired.

    "the obligation must still be `PENDING`, or the request is refused with
    `ERR_OBLIGATION_ALREADY_RESOLVED`, which is the guard that stops a second
    resolve from double-crediting the sponsor"  "a single-obligation deal jumps
    `NOT_STARTED → COMPLETE` in one step"  "when `fulfillment_credited` is false,
    the package's `priority_point_value` is added to the exhibitor's
    `sponsorship_fulfillment_points`, `fulfillment_credited` is set to true"

    Design: Corner/errors/each_state_gated_read_or_action_reports_its_own_status_error
    """
    env = _gated_env(client)
    deal_id = env["deal"]["id"]

    validate_error(
        client.resolve_obligation(
            deal_id, env["obligation"]["id"],
            f.resolve_obligation_payload(
                "WAIVED", note="Second attempt at the same obligation"),
            # A waive must come from a `ShowDirector`: "a waive disposition
            # arriving from a `FloorManager` is answered with
            # `ERR_ROLE_NOT_PERMITTED`", and role authorisation outranks the
            # per-row state gate this test is aiming at.
            make_director_headers("u_sd_2"),
        ),
        ApiErrorId.OBLIGATION_ALREADY_RESOLVED,
        409,
    )

    obligation = fx.read_obligations(client, deal_id)[0]
    assert obligation["status"] == ObligationStatus.DELIVERED
    assert obligation["resolved_by_user_id"] == "u_fm_1"

    deal = fx.read_deal(client, deal_id)
    assert deal["resolved_obligation_count"] == 1
    assert deal["fulfillment_status"] == FulfillmentStatus.COMPLETE
    assert deal["fulfillment_credited"] is True

    exhibitor = fx.read_exhibitor(client, env["harbor"]["id"])
    assert exhibitor["sponsorship_fulfillment_points"] == 4


# ── A floor at one hundred percent: inventory shut, money still open ─────────
def _frozen_single_booth_floor(client: ApiClient) -> dict:
    """A one-booth edition whose only booth is signed away, so the floor is full."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100])
    show_id = env["show"]["id"]
    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example",
                          consecutive_years=6, headers=fx.SALES_REP_HEADERS)
    basalt = fx.exhibitor(client, "Basalt Stoneworks",
                          contact_email="space@basalt.example",
                          consecutive_years=1, headers=fx.SALES_REP_HEADERS)
    offered = fx.offered_contract(
        client, show_id, nordic["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], headers=REP,
        premium_placement_requested=True,
    )
    contract = fx.sign_contract(client, offered, 389070)
    env.update({"show_id": show_id, "nordic": nordic, "basalt": basalt,
                "contract": contract,
                "nordic_headers": fx.make_exhibitor_headers(nordic["id"])})
    return env


def test_a_full_floor_refuses_the_next_hold_before_looking_for_a_booth(
    client: ApiClient,
):
    """
    The request names no booths at all, so an empty selector pool is also waiting
    — but the posture gate answers first.

    "The posture is then `FROZEN` when `committed_ratio_pct` is at least 100"  "A
    `FROZEN` floor blocks the four operations that would consume new inventory —
    opening a space contract, exercising a selection appointment, rebooking onto
    this show, and adding a booth to the floor plan — each with
    `ERR_SHOW_FLOOR_FROZEN` (HTTP 409)."  "**Standing and floor safety**, in this
    order: exhibitor suspension (`ERR_EXHIBITOR_SUSPENDED`), frozen floor
    (`ERR_SHOW_FLOOR_FROZEN`)"  "**Inventory, uniqueness and bounded loops**, in
    this order: booth availability (`ERR_BOOTH_NOT_AVAILABLE`), empty selector pool
    (`ERR_NO_ELIGIBLE_BOOTH`)"

    Design: Corner/errors/a_frozen_floor_refuses_new_holds_but_still_takes_money_to_the_invoice_ceiling
    """
    env = _frozen_single_booth_floor(client)
    show = fx.read_show(client, env["show_id"])
    assert show["sellable_booth_sqft"] == 400
    assert show["assigned_net_sqft"] == 400
    assert show["held_net_sqft"] == 0
    assert show["available_net_sqft"] == 0
    assert show["committed_ratio_pct"] == 100
    assert show["floor_posture"] == FloorPosture.FROZEN

    validate_error(
        client.create_space_contract(
            f.space_contract_payload(env["show_id"], env["basalt"]["id"],
                                     show["version"], 100),
            REP,
        ),
        ApiErrorId.SHOW_FLOOR_FROZEN,
        409,
    )

    rows, meta = validate_paginated(
        client.list_space_contracts(
            fx.SALES_REP_HEADERS, {"exhibitor_id": env["basalt"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_frozen_floor_still_takes_money_up_to_the_invoice_and_no_further(
    client: ApiClient,
):
    """
    Two payments against the same signed hold: the one that fits is taken, the one
    that overshoots the invoice is refused and changes nothing.

    "Posture never blocks signing, depositing, cancelling, adjudicating or closing
    out an existing hold — a frozen floor must always remain workable back down to
    `OPEN`."  "The one ceiling is the invoice: the existing `deposit_paid_cents`
    plus the new `amount_cents` may not exceed `invoice_total_cents`, and an
    over-payment is refused with `ERR_DEPOSIT_EXCEEDS_INVOICE`."

    Design: Corner/errors/a_frozen_floor_refuses_new_holds_but_still_takes_money_to_the_invoice_ceiling
    """
    env = _frozen_single_booth_floor(client)
    contract_id = env["contract"]["id"]
    assert env["contract"]["invoice_total_cents"] == 1556280
    assert env["contract"]["min_deposit_cents"] == 389070
    assert env["contract"]["deposit_paid_cents"] == 389070

    topped_up = validate_success(
        client.post_deposit(contract_id, f.deposit_payload(100000),
                            env["nordic_headers"])
    )
    assert topped_up["deposit_paid_cents"] == 489070
    assert fx.read_show(client, env["show_id"])["floor_posture"] == FloorPosture.FROZEN

    validate_error(
        client.post_deposit(contract_id, f.deposit_payload(1100000),
                            env["nordic_headers"]),
        ApiErrorId.DEPOSIT_EXCEEDS_INVOICE,
        422,
    )

    reread = fx.read_contract(client, contract_id)
    assert reread["deposit_paid_cents"] == 489070
    assert reread["invoice_total_cents"] == 1556280
    assert reread["status"] == SpaceContractStatus.SIGNED


# ── The two money guards that answer last ───────────────────────────────────
B200 = f.inline_booth_payload("B200", 20, 30)


def _countered_hold_and_platinum(client: ApiClient) -> dict:
    """
    A thousand-square-foot floor forty percent committed, one countered hold and
    one package whose percentage floor sits above its stated floor.
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, B200])
    show_id = env["show"]["id"]
    alder = fx.exhibitor(client, "Alder Textiles",
                         contact_email="space@alder.example",
                         consecutive_years=1, headers=fx.SALES_REP_HEADERS)
    alder_headers = fx.make_exhibitor_headers(alder["id"])
    contract = fx.offered_contract(
        client, show_id, alder["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], headers=REP,
        premium_placement_requested=True,
    )
    countered = validate_success(
        client.negotiate(contract["id"], f.counter_payload(30), alder_headers)
    )
    package = fx.sponsorship_package(
        client, show_id, package_code="PLATINUM", list_price_cents=900000,
        price_floor_cents=700000, inventory_total=2,
        obligation_codes=["LOGO_PLACEMENT"], priority_point_value=6,
    )
    env.update({"show_id": show_id, "alder": alder,
                "alder_headers": alder_headers, "contract": countered,
                "package": package})
    return env


def test_a_forty_five_percent_discount_is_refused_even_to_a_show_director(
    client: ApiClient,
):
    """
    The floor is `OPEN` and the approver is the one role allowed to go deep, so the
    only rule left is the absolute cap.

    "A discount above 10 percent may only be approved by a `ShowDirector`; a
    `SalesRep` attempting it is refused with `ERR_DISCOUNT_APPROVAL_REQUIRED`. No
    role, the `ShowDirector` included, may approve more than 40 percent; beyond that
    the answer is `ERR_DISCOUNT_EXCEEDS_CAP`."  "And a discount above 10 percent
    requires an `OPEN` floor, so on a `SPACE_LOCKED` show the deep discount is
    refused with `ERR_SHOW_FLOOR_SPACE_LOCKED`"

    Design: Corner/errors/each_money_guard_on_a_discount_or_a_sponsorship_price_reports_its_own_error
    """
    env = _countered_hold_and_platinum(client)
    show = fx.read_show(client, env["show_id"])
    assert show["sellable_booth_sqft"] == 1000
    assert show["committed_ratio_pct"] == 40
    assert show["floor_posture"] == FloorPosture.OPEN

    validate_error(
        client.negotiate(env["contract"]["id"], f.reoffer_payload(45),
                         make_director_headers("u_sd_9")),
        ApiErrorId.DISCOUNT_EXCEEDS_CAP,
        422,
    )

    reread = fx.read_contract(client, env["contract"]["id"])
    assert reread["status"] == SpaceContractStatus.COUNTERED
    assert reread["approved_discount_pct"] == 0
    assert reread["requested_discount_pct"] == 30
    assert reread["negotiation_round"] == 1
    assert reread["last_offer_by_user_id"] is None


def test_the_percentage_floor_binds_above_the_stated_floor_by_a_single_cent_band(
    client: ApiClient,
):
    """
    A price that satisfies `price_floor_cents` exactly is still below eighty percent
    of the list price; the eighty-percent figure itself is accepted.

    "the price must clear two independent floors: `negotiated_price_cents` must be
    at least the package's `price_floor_cents`, and it must also be at least 80
    percent of `list_price_cents` — that is, the list price multiplied by one
    hundred less twenty, divided by one hundred, rounded half up — so that no
    package can be discounted by more than a fifth. The binding floor is whichever
    of the two is higher, and a price below it is
    `ERR_SPONSORSHIP_PRICE_BELOW_FLOOR`."  "A proposal consumes a unit
    **immediately**: `inventory_committed` rises by one and `inventory_available`
    falls by one"

    Design: Corner/errors/each_money_guard_on_a_discount_or_a_sponsorship_price_reports_its_own_error
    """
    env = _countered_hold_and_platinum(client)
    package_id = env["package"]["id"]
    assert env["package"]["price_floor_cents"] == 700000
    assert env["package"]["list_price_cents"] == 900000

    validate_error(
        client.create_sponsorship_deal(
            package_id,
            f.sponsorship_deal_payload(env["alder"]["id"], 700000), REP,
        ),
        ApiErrorId.SPONSORSHIP_PRICE_BELOW_FLOOR,
        422,
    )
    assert _package_row(client, env["show_id"], package_id)["inventory_available"] == 2

    deal = validate_success(
        client.create_sponsorship_deal(
            package_id,
            f.sponsorship_deal_payload(env["alder"]["id"], 720000), REP,
        ),
        201,
    )
    assert deal["negotiated_price_cents"] == 720000
    assert deal["deal_status"] == DealStatus.PROPOSED
    assert _package_row(client, env["show_id"], package_id)["inventory_available"] == 1


# ── Four unrelated constraint families on one fixture ───────────────────────
SHOW_2029 = {
    "edition_year": 2029,
    "move_in_start": "2029-03-01",
    "event_start": "2029-03-05",
    "event_end": "2029-03-07",
    "move_out_end": "2029-03-09",
    "base_rate_cents_per_sqft": 3400,
}


def _four_family_env(client: ApiClient) -> dict:
    """A signed hold and a waitlisted badge on one edition still open for selection."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example",
                          consecutive_years=6, headers=fx.SALES_REP_HEADERS)
    nordic_headers = fx.make_exhibitor_headers(nordic["id"])
    offered = fx.offered_contract(
        client, show_id, nordic["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], headers=REP,
        premium_placement_requested=True,
    )
    contract = fx.sign_contract(client, offered, 389070)
    registration = validate_success(
        client.create_registration(
            show_id,
            f.registration_payload(
                category="BUYER", company_name="Meridian Grocers",
                job_title="Category Manager", purchasing_authority="RECOMMENDER",
                annual_spend_band="K250K_1M", email="cm@meridian.example",
            ),
            fx.REGISTRANT_HEADERS,
        ),
        201,
    )
    env.update({"show_id": show_id, "nordic": nordic,
                "nordic_headers": nordic_headers, "contract": contract,
                "registration": registration})
    return env


def test_a_floor_plan_that_under_reserves_aisles_is_refused_at_creation(
    client: ApiClient,
):
    """
    A 2029 edition inside the agreement's term, clashing with nothing, whose only
    fault is that it keeps a quarter of the hall for aisles.

    "the `aisle_ratio_pct` is an integer from 0 through 90 and may not fall below
    the hall's `min_aisle_ratio_pct`, which is checked at creation and again at
    publication and reported as `ERR_AISLE_RATIO_VIOLATION`"

    Design: Corner/errors/aisle_appointment_window_service_window_and_waiver_reason_each_report_their_own_error
    """
    env = _four_family_env(client)
    venue_contract_id = env["venue_contract"]["id"]

    validate_error(
        client.create_show(
            f.show_payload(venue_contract_id, aisle_ratio_pct=25, **SHOW_2029),
            fx.DIRECTOR_HEADERS,
        ),
        ApiErrorId.AISLE_RATIO_VIOLATION,
        422,
    )

    rows, meta = validate_paginated(
        client.list_venue_contract_shows(venue_contract_id, fx.DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 1
    assert [row["edition_year"] for row in rows] == [2027]


def test_an_inverted_window_and_a_post_event_window_are_both_refused(
    client: ApiClient,
):
    """
    Two bookings against the same round: one whose bounds are the wrong way round,
    one that sits after the doors open.

    "The window is half-open: it includes `window_start` and excludes `window_end`."
    "The window must be well-formed and timely — `window_start` strictly before
    `window_end`, and both falling on or before the show's `event_start` — or the
    request is refused with `ERR_INVALID_APPOINTMENT_WINDOW`."

    Design: Corner/errors/aisle_appointment_window_service_window_and_waiver_reason_each_report_their_own_error
    """
    env = _four_family_env(client)
    show_id = env["show_id"]
    exhibitor_id = env["nordic"]["id"]

    validate_error(
        client.create_selection_appointment(
            show_id,
            f.appointment_payload(exhibitor_id, 1, "2027-03-01T11:00:00Z",
                                  "2027-03-01T09:00:00Z"),
            fx.SALES_REP_HEADERS,
        ),
        ApiErrorId.INVALID_APPOINTMENT_WINDOW,
        422,
    )
    validate_error(
        client.create_selection_appointment(
            show_id,
            f.appointment_payload(exhibitor_id, 1, "2027-03-06T09:00:00Z",
                                  "2027-03-06T11:00:00Z"),
            fx.SALES_REP_HEADERS,
        ),
        ApiErrorId.INVALID_APPOINTMENT_WINDOW,
        422,
    )

    rows, meta = validate_paginated(
        client.list_selection_appointments(
            fx.DIRECTOR_HEADERS,
            {"show_id": show_id, "exhibitor_id": exhibitor_id},
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_labor_order_dated_after_the_hall_is_struck_is_refused(
    client: ApiClient,
):
    """
    The contract is `SIGNED` and the show is open for services; only the calendar
    refuses the order.

    "The date part of `ordered_at` may not fall after the show's `move_out_end`;
    ordering into a hall that has already been struck is refused with
    `ERR_SERVICE_ORDER_WINDOW_CLOSED`."

    Design: Corner/errors/aisle_appointment_window_service_window_and_waiver_reason_each_report_their_own_error
    """
    env = _four_family_env(client)
    contract_id = env["contract"]["id"]
    assert fx.read_show(client, env["show_id"])["move_out_end"] == "2027-03-09"

    validate_error(
        client.create_service_order(
            contract_id,
            f.service_order_payload("LABOR", 8, "2027-03-20T00:00:00Z"),
            env["nordic_headers"],
        ),
        ApiErrorId.SERVICE_ORDER_WINDOW_CLOSED,
        422,
    )

    rows, meta = validate_paginated(
        client.list_service_orders(contract_id, env["nordic_headers"])
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_waiver_and_an_override_both_demand_a_reason_that_is_actually_there(
    client: ApiClient,
):
    """
    One reason omitted altogether and one supplied as an empty string: the same
    error answers both, and neither row moves.

    "An `OPEN → WAIVED` disposition is the mirror image and propagates nothing. It
    requires a present, non-empty `waiver_reason`; a waiver without one is refused
    with `ERR_WAIVER_REASON_REQUIRED`."  "by supplying a `decision` of either
    `QUALIFIED` or `REJECTED` together with a mandatory non-empty `reason`; an
    override arriving without one is refused with `ERR_WAIVER_REASON_REQUIRED`"
    "The previously computed `qualification_score` is deliberately preserved
    untouched"

    Design: Corner/errors/aisle_appointment_window_service_window_and_waiver_reason_each_report_their_own_error
    """
    env = _four_family_env(client)
    registration = env["registration"]
    fx.transition(client, env["show_id"], ShowStatus.SELLING)
    fx.transition(client, env["show_id"], ShowStatus.ON_SITE)
    citation = validate_success(
        client.create_rule_violation(
            env["contract"]["id"],
            f.rule_violation_payload(
                "NOISE",
                notes=("Sound stage measured well above the aisle limit during "
                       "the demo"),
            ),
            FLOOR,
        ),
        201,
    )
    assert citation["status"] == ViolationStatus.OPEN
    assert registration["qualification_score"] == 50
    assert registration["qualification_status"] == QualificationStatus.WAITLISTED

    validate_error(
        client.adjudicate(citation["id"], f.adjudicate_payload("WAIVED"),
                          DIRECTOR),
        ApiErrorId.WAIVER_REASON_REQUIRED,
        422,
    )
    validate_error(
        client.screen_registration(registration["id"],
                                   f.screen_payload("QUALIFIED", ""),
                                   fx.DIRECTOR_HEADERS),
        ApiErrorId.WAIVER_REASON_REQUIRED,
        422,
    )

    citations, _ = validate_paginated(
        client.list_rule_violations(env["contract"]["id"], fx.DIRECTOR_HEADERS)
    )
    still_open = next(row for row in citations if row["id"] == citation["id"])
    assert still_open["status"] == ViolationStatus.OPEN
    assert still_open["waiver_reason"] is None
    assert fx.read_exhibitor(client, env["nordic"]["id"])["penalty_points"] == 0

    reread = validate_success(
        client.get_registration(registration["id"], fx.DIRECTOR_HEADERS)
    )
    assert reread["qualification_status"] == QualificationStatus.WAITLISTED
    assert reread["qualification_score"] == 50
    assert reread["screening_override_reason"] is None


# ── The appointment is the identity of an exercise ───────────────────────────
SHOW_2028 = {
    "edition_year": 2028,
    "move_in_start": "2028-03-01",
    "event_start": "2028-03-05",
    "event_end": "2028-03-07",
    "move_out_end": "2028-03-09",
    "base_rate_cents_per_sqft": 3400,
}
F100 = f.booth_payload("F100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)


def test_an_active_appointment_may_not_claim_the_next_editions_booth(
    client: ApiClient,
):
    """
    The slot is `ACTIVE`, the window is open and the exhibitor is the right one —
    but the booth in the body belongs to the 2028 edition.

    "The appointment's own `exhibitor_id` must be the acting exhibitor and its
    `show_id` must be the show whose booths are being claimed, or the request fails
    with `ERR_APPOINTMENT_EXHIBITOR_MISMATCH`."  "And on an exercise, an appointment
    whose own show does not match the booths being claimed reports
    `ERR_APPOINTMENT_EXHIBITOR_MISMATCH` rather than `ERR_BOOTH_NOT_IN_SHOW`,
    because on that operation the appointment is the identity of the request."

    Design: Corner/errors/an_appointment_cannot_be_exercised_onto_another_editions_booth
    """
    fx.set_clock(client, CLOCK)
    this_year = fx.published_show(client, [A100, C050])
    next_year = fx.published_show(client, [F100],
                                  venue_contract=this_year["venue_contract"],
                                  **SHOW_2028)
    show_id = this_year["show"]["id"]
    harbor = fx.exhibitor(client, "Harbor Ceramics",
                          contact_email="space@harbor.example",
                          consecutive_years=2, headers=fx.SALES_REP_HEADERS)
    appointment = fx.scheduled_appointment(
        client, show_id, harbor["id"], 1,
        "2027-03-01T09:00:00Z", "2027-03-01T11:00:00Z",
    )
    fx.set_clock(client, DESK_CLOCK)
    validate_success(client.advance_selection_round(show_id, fx.DIRECTOR_HEADERS))
    activated = validate_success(
        client.get_selection_appointment(appointment["id"], fx.DIRECTOR_HEADERS)
    )
    assert activated["state"] == AppointmentState.ACTIVE
    pinned_version = fx.show_version(client, show_id)
    foreign_booth_id = next_year["booth_by_number"]["F100"]["id"]

    validate_error(
        client.exercise_appointment(
            appointment["id"],
            f.exercise_payload(pinned_version, 400,
                               premium_placement_requested=True,
                               booth_ids=[foreign_booth_id]),
            fx.SALES_REP_HEADERS,
        ),
        ApiErrorId.APPOINTMENT_EXHIBITOR_MISMATCH,
        422,
    )

    reread = validate_success(
        client.get_selection_appointment(appointment["id"], fx.DIRECTOR_HEADERS)
    )
    assert reread["state"] == AppointmentState.ACTIVE
    assert reread["show_id"] == show_id

    foreign_booth = fx.read_booth(client, foreign_booth_id)
    assert foreign_booth["status"] == BoothStatus.AVAILABLE
    assert foreign_booth["space_contract_id"] is None
    assert fx.read_show(client, next_year["show"]["id"])["held_net_sqft"] == 0

    home_booth = fx.read_booth(client, this_year["booth_by_number"]["A100"]["id"])
    assert home_booth["status"] == BoothStatus.AVAILABLE

    rows, meta = validate_paginated(
        client.list_space_contracts(fx.SALES_REP_HEADERS,
                                    {"exhibitor_id": harbor["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert fx.show_version(client, show_id) == pinned_version
