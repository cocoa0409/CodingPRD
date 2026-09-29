"""
The authorisation ladder: the four auth gates in their declared order, the three
separation-of-duties legs, and the endpoints two roles genuinely share.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BoothStatus,
    DealStatus,
    FloorPosture,
    FulfillmentStatus,
    NO_ROLE_HEADERS,
    ObligationStatus,
    RateVariant,
    ShowStatus,
    SpaceContractStatus,
    UNKNOWN_ROLE_HEADERS,
    ViolationStatus,
    factories as f,
    fixtures as fx,
    make_director_headers,
    make_exhibitor_headers,
    make_exhibitor_headers_without_identity,
    make_floor_manager_headers,
    make_sales_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)

REP = make_sales_rep_headers("u_sr_1")
REP_2 = make_sales_rep_headers("u_sr_2")
DIRECTOR = make_director_headers("u_sd_1")
DIRECTOR_2 = make_director_headers("u_sd_2")
DIRECTOR_3 = make_director_headers("u_sd_3")
FLOOR = make_floor_manager_headers("u_fm_1")

ROGUE_2029 = {
    "name": "Rogue Edition",
    "edition_year": 2029,
    "move_in_start": "2029-03-01",
    "event_start": "2029-03-05",
    "event_end": "2029-03-07",
    "move_out_end": "2029-03-09",
    "base_rate_cents_per_sqft": 3400,
}


# ── The four auth gates, in their declared order ────────────────────────────
def _two_exhibitor_env(client: ApiClient) -> dict:
    """
    Alder's hold is still `OFFERED` and Basalt's is signed, so one contract is
    reachable by exactly one exhibitor identity.
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    booths = env["booth_by_number"]
    alder = fx.exhibitor(client, "Alder Textiles",
                         contact_email="space@alder.example",
                         consecutive_years=1, headers=fx.SALES_REP_HEADERS)
    basalt = fx.exhibitor(client, "Basalt Stoneworks",
                          contact_email="space@basalt.example",
                          consecutive_years=1, headers=fx.SALES_REP_HEADERS)
    alder_contract = fx.offered_contract(
        client, show_id, alder["id"], 400, [booths["A100"]["id"]],
        headers=REP, premium_placement_requested=True,
    )
    basalt_offer = fx.offered_contract(
        client, show_id, basalt["id"], 200, [booths["C050"]["id"]], headers=REP,
    )
    basalt_contract = fx.sign_contract(client, basalt_offer, 163750)
    package = fx.sponsorship_package(
        client, show_id, package_code="BANNER", list_price_cents=500000,
        price_floor_cents=400000, inventory_total=1,
        obligation_codes=["LOGO_PLACEMENT"], priority_point_value=4,
    )
    deal = fx.proposed_deal(client, package["id"], alder["id"], 500000,
                            headers=DIRECTOR)
    env.update({"show_id": show_id, "alder": alder, "basalt": basalt,
                "alder_contract": alder_contract,
                "basalt_contract": basalt_contract,
                "package": package, "deal": deal})
    return env


def test_an_unrecognised_role_and_a_missing_role_are_both_unauthenticated(
    client: ApiClient,
):
    """
    The same well-formed creation body, once from a role that does not exist and
    once with no role header at all.

    "Exactly five roles are recognised, spelled precisely as follows:
    `ShowDirector`, `SalesRep`, `FloorManager`, `Exhibitor`, and `Registrant`. When
    `X-Role` is absent, or when it holds any string other than these five, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else
    is considered."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
    """
    env = _two_exhibitor_env(client)
    venue_contract_id = env["venue_contract"]["id"]
    body = f.show_payload(venue_contract_id, **ROGUE_2029)

    validate_error(
        client.create_show(body, UNKNOWN_ROLE_HEADERS),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    validate_error(
        client.create_show(body, NO_ROLE_HEADERS),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )

    rows, meta = validate_paginated(
        client.list_venue_contract_shows(venue_contract_id, fx.DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 1
    assert [row["edition_year"] for row in rows] == [2027]


def test_a_registrant_cannot_open_an_edition_and_a_rep_cannot_sign_a_sponsorship(
    client: ApiClient,
):
    """
    Two recognised roles reaching two operations that belong to the director alone.

    "When `X-Role` is present and recognised but the role is not among those the
    addressed endpoint permits, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP
    403)."  "A `Registrant` submits its own registration for screening and holds no
    other authority anywhere in the API."  "but a `SalesRep` may never sign a
    sponsorship deal and may never approve a discount above the threshold"

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
    """
    env = _two_exhibitor_env(client)
    venue_contract_id = env["venue_contract"]["id"]

    validate_error(
        client.create_show(f.show_payload(venue_contract_id, **ROGUE_2029),
                           fx.REGISTRANT_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        client.sign_sponsorship_deal(env["deal"]["id"], REP),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )

    _, meta = validate_paginated(
        client.list_venue_contract_shows(venue_contract_id, fx.DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 1

    deal = fx.read_deal(client, env["deal"]["id"])
    assert deal["deal_status"] == DealStatus.PROPOSED
    assert deal["signed_by_user_id"] is None


def test_identity_answers_before_scope_and_scope_answers_before_the_money(
    client: ApiClient,
):
    """
    Three signatures on Alder's hold: one from an id that resolves to nothing, one
    with no `X-Role-Id` at all, and one from a real but different exhibitor.

    "When `X-Role` is `Exhibitor`, the request must additionally carry `X-Role-Id`,
    and that value is the `id` of the acting `Exhibitor` row. If `X-Role-Id` is
    absent, or does not resolve to an existing exhibitor, the request fails with
    `ERR_IDENTITY_REQUIRED` (HTTP 403)."  "Ownership checks on any resource that
    references an exhibitor compare the resource's exhibitor foreign key to
    `X-Role-Id`: a space contract's `exhibitor_id`"  "A mismatch is
    `ERR_EXHIBITOR_SCOPE_VIOLATION` (HTTP 403)"

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
    """
    env = _two_exhibitor_env(client)
    contract_id = env["alder_contract"]["id"]
    pinned_version = fx.show_version(client, env["show_id"])
    body = f.sign_payload(pinned_version, 389070)

    validate_error(
        client.sign_space_contract(
            contract_id, body, make_exhibitor_headers("u_not_an_exhibitor")
        ),
        ApiErrorId.IDENTITY_REQUIRED,
        403,
    )
    validate_error(
        client.sign_space_contract(
            contract_id, body, make_exhibitor_headers_without_identity()
        ),
        ApiErrorId.IDENTITY_REQUIRED,
        403,
    )
    validate_error(
        client.sign_space_contract(
            contract_id, body, make_exhibitor_headers(env["basalt"]["id"])
        ),
        ApiErrorId.EXHIBITOR_SCOPE_VIOLATION,
        403,
    )

    reread = fx.read_contract(client, contract_id)
    assert reread["status"] == SpaceContractStatus.OFFERED
    assert reread["deposit_paid_cents"] == 0
    assert reread["signed_at"] is None
    assert (
        fx.read_booth(client, env["booth_by_number"]["A100"]["id"])["status"]
        == BoothStatus.HELD
    )
    assert fx.show_version(client, env["show_id"]) == pinned_version


# ── The three separation-of-duties legs ─────────────────────────────────────
B200 = f.inline_booth_payload("B200", 20, 30)
D010 = f.inline_booth_payload("D010", 10, 10)


def _self_approval_env(client: ApiClient) -> dict:
    """
    Every recorded operator id is set up to be the one that will try to approve its
    own work: u_sr_1 made the last offer, u_sd_3 wrote the citation, u_sd_1
    proposed the deal.
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, B200, D010])
    show_id = env["show"]["id"]
    booths = env["booth_by_number"]
    alder = fx.exhibitor(client, "Alder Textiles",
                         contact_email="space@alder.example",
                         consecutive_years=1, headers=fx.SALES_REP_HEADERS)
    basalt = fx.exhibitor(client, "Basalt Stoneworks",
                          contact_email="space@basalt.example",
                          consecutive_years=1, headers=fx.SALES_REP_HEADERS)
    alder_headers = make_exhibitor_headers(alder["id"])
    contract = fx.offered_contract(
        client, show_id, alder["id"], 400, [booths["A100"]["id"]],
        headers=REP, premium_placement_requested=True,
    )
    validate_success(client.negotiate(contract["id"], f.counter_payload(12),
                                      alder_headers))
    validate_success(client.negotiate(contract["id"], f.reoffer_payload(8), REP))
    countered = validate_success(
        client.negotiate(contract["id"], f.counter_payload(25), alder_headers)
    )
    basalt_offer = fx.offered_contract(
        client, show_id, basalt["id"], 100, [booths["D010"]["id"]], headers=REP,
    )
    basalt_contract = fx.sign_contract(client, basalt_offer, 81875)
    package = fx.sponsorship_package(
        client, show_id, package_code="PLATINUM", list_price_cents=900000,
        price_floor_cents=700000, inventory_total=1,
        obligation_codes=["LOGO_PLACEMENT"], priority_point_value=6,
    )
    deal = fx.proposed_deal(client, package["id"], alder["id"], 800000,
                            headers=DIRECTOR)
    env.update({"show_id": show_id, "alder": alder, "basalt": basalt,
                "alder_headers": alder_headers, "contract": countered,
                "basalt_contract": basalt_contract,
                "package": package, "deal": deal})
    return env


def test_the_proposer_cannot_sign_its_own_deal_but_a_second_director_can(
    client: ApiClient,
):
    """
    One deal, two director operators: the one that priced it is refused, the other
    commits the show and mints the obligation.

    "First, the operator who packaged and priced a sponsorship may not be the
    operator who commits the show to it: signing a sponsorship deal requires an
    `X-User-ID` different from the deal's `proposed_by_user_id`, and a match is
    rejected with `ERR_SOD_SPONSORSHIP_SIGN` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_refuses_every_self_approval_on_all_three_legs
    """
    env = _self_approval_env(client)
    deal_id = env["deal"]["id"]
    assert env["deal"]["proposed_by_user_id"] == "u_sd_1"

    validate_error(
        client.sign_sponsorship_deal(deal_id, DIRECTOR),
        ApiErrorId.SOD_SPONSORSHIP_SIGN,
        403,
    )
    assert fx.read_deal(client, deal_id)["deal_status"] == DealStatus.PROPOSED

    signed = validate_success(client.sign_sponsorship_deal(deal_id, DIRECTOR_2))
    assert signed["deal_status"] == DealStatus.SIGNED
    assert signed["signed_by_user_id"] == "u_sd_2"

    obligations = fx.read_obligations(client, deal_id)
    assert len(obligations) == 1
    assert obligations[0]["status"] == ObligationStatus.PENDING


def test_the_reporter_cannot_rule_on_its_own_citation_but_a_peer_can(
    client: ApiClient,
):
    """
    The citation stays `OPEN` under its own author's ruling and costs five points
    under another director's.

    "Second, the floor manager who wrote a citation may not rule on it, for either
    disposition: adjudicating a rule violation requires an `X-User-ID` different
    from that violation's `reported_by_user_id`, and a match is
    `ERR_SOD_VIOLATION_ADJUDICATION` (HTTP 403)."  "An `OPEN → UPHELD` disposition
    writes `adjudicated_by_user_id` and sets the citation's `penalty_points` from
    the penalty schedule: ten for `BOOTH_HEIGHT`, five for `NOISE`, eight for
    `AISLE_ENCROACHMENT` and fifteen for `SALES_CONDUCT`."

    Design: Corner/rbac/segregation_of_duties_refuses_every_self_approval_on_all_three_legs
    """
    env = _self_approval_env(client)
    fx.transition(client, env["show_id"], ShowStatus.SELLING)
    fx.transition(client, env["show_id"], ShowStatus.ON_SITE)
    citation = validate_success(
        client.create_rule_violation(
            env["basalt_contract"]["id"],
            f.rule_violation_payload(
                "NOISE", notes="Amplified demo audible three aisles away"),
            DIRECTOR_3,
        ),
        201,
    )
    citation_id = citation["id"]
    assert citation["reported_by_user_id"] == "u_sd_3"

    validate_error(
        client.adjudicate(citation_id, f.adjudicate_payload("UPHELD"), DIRECTOR_3),
        ApiErrorId.SOD_VIOLATION_ADJUDICATION,
        403,
    )
    rows, _ = validate_paginated(
        client.list_rule_violations(env["basalt_contract"]["id"],
                                    fx.DIRECTOR_HEADERS)
    )
    assert rows[0]["status"] == ViolationStatus.OPEN

    upheld = validate_success(
        client.adjudicate(citation_id, f.adjudicate_payload("UPHELD"), DIRECTOR)
    )
    assert upheld["status"] == ViolationStatus.UPHELD
    assert upheld["penalty_points"] == 5
    assert fx.read_exhibitor(client, env["basalt"]["id"])["penalty_points"] == 5


def test_a_deep_discount_needs_a_director_who_did_not_make_the_last_offer(
    client: ApiClient,
):
    """
    Twenty-five percent is refused twice — once for the role, once for the operator
    — and granted only by a director who was not the last to offer.

    "A discount above 10 percent may only be approved by a `ShowDirector`; a
    `SalesRep` attempting it is refused with `ERR_DISCOUNT_APPROVAL_REQUIRED`."
    "Third, an operator may not self-approve a deep discount on the offer that
    follows its own: when a re-offer carries an `approved_discount_pct` greater than
    10, the approving `X-User-ID` must differ from the contract's
    `last_offer_by_user_id`, and a match is `ERR_SOD_DISCOUNT_APPROVAL` (HTTP 403)."
    "It writes `approved_discount_pct` — the discount the producer is actually
    granting — and records the acting operator in `last_offer_by_user_id`."

    Design: Corner/rbac/segregation_of_duties_refuses_every_self_approval_on_all_three_legs
    """
    env = _self_approval_env(client)
    contract_id = env["contract"]["id"]
    assert env["contract"]["last_offer_by_user_id"] == "u_sr_1"
    assert env["contract"]["negotiation_round"] == 2
    assert fx.read_show(client, env["show_id"])["floor_posture"] == FloorPosture.OPEN

    validate_error(
        client.negotiate(contract_id, f.reoffer_payload(25), REP_2),
        ApiErrorId.DISCOUNT_APPROVAL_REQUIRED,
        403,
    )
    validate_error(
        client.negotiate(contract_id, f.reoffer_payload(25),
                         make_director_headers("u_sr_1")),
        ApiErrorId.SOD_DISCOUNT_APPROVAL,
        403,
    )

    midway = fx.read_contract(client, contract_id)
    assert midway["status"] == SpaceContractStatus.COUNTERED
    assert midway["approved_discount_pct"] == 8
    assert midway["negotiation_round"] == 2

    reoffered = validate_success(
        client.negotiate(contract_id, f.reoffer_payload(25), DIRECTOR)
    )
    assert reoffered["status"] == SpaceContractStatus.OFFERED
    assert reoffered["approved_discount_pct"] == 25
    assert reoffered["last_offer_by_user_id"] == "u_sd_1"
    assert reoffered["space_fee_cents"] == 1167210
    assert reoffered["min_deposit_cents"] == 291803


# ── Peer roles on the endpoints they genuinely share ────────────────────────
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
F200 = f.inline_booth_payload("F200", 10, 20)


def _peer_env(client: ApiClient) -> dict:
    """
    A signed hold on the 2027 edition, an empty 2028 edition still in `PLANNING`,
    and a separate sponsor's two-obligation deal.
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    next_year = fx.planning_show(client, venue_contract=env["venue_contract"],
                                 **SHOW_2028)
    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example",
                          consecutive_years=6, headers=fx.SALES_REP_HEADERS)
    sponsor = fx.exhibitor(client, "Lumen Media",
                           contact_email="sponsor@lumen.example",
                           consecutive_years=0, headers=fx.SALES_REP_HEADERS)
    offered = fx.offered_contract(
        client, show_id, nordic["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], headers=REP,
        premium_placement_requested=True,
    )
    contract = fx.sign_contract(client, offered, 389070)
    package = fx.sponsorship_package(
        client, show_id, package_code="PLATINUM", list_price_cents=900000,
        price_floor_cents=700000, inventory_total=1,
        obligation_codes=["LOGO_PLACEMENT", "PROGRAM_AD"], priority_point_value=6,
    )
    deal = fx.signed_deal(client, package["id"], sponsor["id"], 800000,
                          proposer_headers=REP, signer_headers=DIRECTOR)
    obligations = fx.read_obligations(client, deal["id"])
    assert len(obligations) == 2
    env.update({"show_id": show_id, "next_show_id": next_year["show"]["id"],
                "nordic": nordic, "nordic_headers": make_exhibitor_headers(nordic["id"]),
                "sponsor": sponsor, "contract": contract, "package": package,
                "deal": deal, "obligations": obligations})
    return env


def test_the_floor_manager_and_the_director_both_lay_out_the_next_floor_plan(
    client: ApiClient,
):
    """
    Two booths added to the same `PLANNING` edition by the two roles the endpoint
    names, and the floor totals both of them.

    "A `FloorManager` runs the physical floor: adding and combining booths, taking
    service orders, writing citations, recording lead scans and marking sponsorship
    deliverables delivered."  "adding a booth rewrites the owning show's
    `sellable_booth_sqft`, `available_net_sqft`, `committed_ratio_pct` and
    `floor_posture` and bumps the show's `version`"

    Design: Corner/rbac/peer_roles_share_the_endpoints_they_are_both_listed_on
    """
    env = _peer_env(client)
    next_show_id = env["next_show_id"]

    by_floor_manager = validate_success(
        client.create_booth(next_show_id, F100, FLOOR), 201
    )
    by_director = validate_success(
        client.create_booth(next_show_id, F200, DIRECTOR), 201
    )
    assert by_floor_manager["show_id"] == next_show_id
    assert by_director["show_id"] == next_show_id

    assert fx.read_show(client, next_show_id)["sellable_booth_sqft"] == 600


def test_the_exhibitor_and_the_floor_manager_both_order_services_at_advance_rates(
    client: ApiClient,
):
    """
    One order from the buyer's side of the desk and one from the producer's, both
    dated inside the advance window.

    "Exhibitor services are ordered against a `SIGNED` space contract by the
    `Exhibitor` itself or by a `FloorManager` acting at the service desk, on a show
    that is `SPACE_SELECTION`, `SELLING` or `ON_SITE`."  "Under `ADVANCE`,
    `line_total_cents` is the product of `billable_quantity`, `unit_rate_cents` and
    the quantity (one hundred minus the venue agreement's
    `advance_order_discount_pct`) divided by one hundred, rounded half up to whole
    cents; no expedite fee applies."

    Design: Corner/rbac/peer_roles_share_the_endpoints_they_are_both_listed_on
    """
    env = _peer_env(client)
    contract_id = env["contract"]["id"]

    labor = validate_success(
        client.create_service_order(
            contract_id, f.service_order_payload("LABOR", 8, "2027-02-01T00:00:00Z"),
            env["nordic_headers"],
        ),
        201,
    )
    electrical = validate_success(
        client.create_service_order(
            contract_id,
            f.service_order_payload("ELECTRICAL", 20, "2027-02-01T00:00:00Z"),
            FLOOR,
        ),
        201,
    )
    assert labor["rate_variant"] == RateVariant.ADVANCE
    assert labor["line_total_cents"] == 60800
    assert electrical["rate_variant"] == RateVariant.ADVANCE
    assert electrical["line_total_cents"] == 67200

    _, meta = validate_paginated(
        client.list_service_orders(contract_id, fx.DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 2


def test_both_the_floor_manager_and_the_director_may_write_a_citation(
    client: ApiClient,
):
    """
    Two citations on the same signed hold from the two roles the endpoint names, and
    neither costs the exhibitor anything before a ruling.

    "Rebooking, lead scanning and floor-rule citation are legal only while the
    edition is `ON_SITE`."  "A `FloorManager` or a `ShowDirector` writes a citation
    against a `SIGNED` contract naming a `violation_type` of `BOOTH_HEIGHT`, `NOISE`,
    `AISLE_ENCROACHMENT` or `SALES_CONDUCT`"  "The new citation opens with `status`
    `OPEN` and `penalty_points` of zero, records the reporting operator's identity in
    `reported_by_user_id`, and leaves `adjudicated_by_user_id` and `waiver_reason`
    null."

    Design: Corner/rbac/peer_roles_share_the_endpoints_they_are_both_listed_on
    """
    env = _peer_env(client)
    contract_id = env["contract"]["id"]
    fx.transition(client, env["show_id"], ShowStatus.SELLING)
    fx.transition(client, env["show_id"], ShowStatus.ON_SITE)

    by_floor_manager = validate_success(
        client.create_rule_violation(
            contract_id,
            f.rule_violation_payload(
                "NOISE", notes="Speaker volume above the posted limit"),
            FLOOR,
        ),
        201,
    )
    by_director = validate_success(
        client.create_rule_violation(
            contract_id,
            f.rule_violation_payload(
                "AISLE_ENCROACHMENT",
                notes="Crate stacked 18 inches into the cross aisle"),
            DIRECTOR,
        ),
        201,
    )
    assert by_floor_manager["status"] == ViolationStatus.OPEN
    assert by_director["status"] == ViolationStatus.OPEN
    assert by_floor_manager["penalty_points"] == 0
    assert by_director["penalty_points"] == 0
    assert fx.read_exhibitor(client, env["nordic"]["id"])["penalty_points"] == 0


def test_the_floor_manager_delivers_but_only_the_director_may_waive(
    client: ApiClient,
):
    """
    The same endpoint, the same caller, two dispositions: one accepted and one
    refused on the payload alone, then completed by the director.

    "That same code also covers one role-shaped restriction inside an
    otherwise-permitted endpoint: a `FloorManager` may resolve a sponsorship
    obligation as delivered but may never waive one, so a waive disposition arriving
    from a `FloorManager` is answered with `ERR_ROLE_NOT_PERMITTED`."  "Both
    dispositions then bubble upward identically, because a waived obligation counts
    as resolved"

    Design: Corner/rbac/peer_roles_share_the_endpoints_they_are_both_listed_on
    """
    env = _peer_env(client)
    deal_id = env["deal"]["id"]
    first, second = env["obligations"][0], env["obligations"][1]

    delivered = validate_success(
        client.resolve_obligation(
            deal_id, first["id"],
            f.resolve_obligation_payload(
                "DELIVERED", note="Logo printed on the hall banner"),
            FLOOR,
        )
    )
    assert delivered["status"] == ObligationStatus.DELIVERED
    partial = fx.read_deal(client, deal_id)
    assert partial["resolved_obligation_count"] == 1
    assert partial["fulfillment_status"] == FulfillmentStatus.PARTIAL

    waiver = f.resolve_obligation_payload(
        "WAIVED", note="Program went to print before the artwork arrived")
    validate_error(
        client.resolve_obligation(deal_id, second["id"], waiver, FLOOR),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    still_pending = {row["id"]: row for row in fx.read_obligations(client, deal_id)}
    assert still_pending[second["id"]]["status"] == ObligationStatus.PENDING

    waived = validate_success(
        client.resolve_obligation(deal_id, second["id"], waiver, DIRECTOR)
    )
    assert waived["status"] == ObligationStatus.WAIVED
    assert fx.read_deal(client, deal_id)["fulfillment_status"] == FulfillmentStatus.COMPLETE
    assert (
        fx.read_exhibitor(client, env["sponsor"]["id"])["sponsorship_fulfillment_points"]
        == 6
    )
