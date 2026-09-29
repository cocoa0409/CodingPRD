"""Who may act, who may not, and where the boundary between hands is drawn.

Each scenario probes an authority rule from the role standing closest to it —
the hand that built the row, priced it, or owns the neighbouring lifecycle step
— so that an implementation granting a verb to "anyone in the area" is caught.
Refusals are always shown to have left the row untouched, and the same body is
then replayed from the hand that does hold the authority.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    CLIENT_SERVICE_AGENT,
    COMMERCIAL_DIRECTOR,
    COMMERCIAL_DIRECTOR_AS_PRICER,
    COMMERCIAL_MANAGER,
    ERR_CLIENT_SCOPE_VIOLATION,
    ERR_INVALID_BUILD_STATE,
    ERR_INVALID_DEAL_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
    FINANCE_CONTROLLER,
    OPERATIONS_MANAGER,
    RIGHTS_MANAGER,
    USER_COMMERCIAL_DIRECTOR,
    USER_COMMERCIAL_MANAGER,
    USER_FINANCE_CONTROLLER,
    ApiClient,
    add_component,
    allocate_booking,
    approve_build,
    get_success_data,
    host_assignment_payload,
    installments_of,
    make_block,
    make_booking,
    make_bronze_package,
    make_build,
    make_client,
    make_client_portal_user_headers,
    make_committed_deal,
    make_event,
    make_host,
    make_published_bronze_package,
    on_site_host_payload,
    pay_payload,
    price_package,
    publish_payload,
    read_host,
    release_deal,
    reset_clock,
    validate_error,
)


# --------------------------------------------------------------------------
# Publication belongs to the commercial director alone
# --------------------------------------------------------------------------


def _priced_bronze_package(api: ApiClient) -> Dict[str, Any]:
    """A one-line BRONZE package priced by the commercial manager.

    The fixture carries a committed TICKET deal, so the only thing standing
    between this package and sale is the approval itself.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    package = make_bronze_package(api, event["id"])
    add_component(api, package["id"])
    priced = price_package(api, package["id"])
    assert priced["package_status"] == "PRICED"
    return {"event": event, "deal": deal, "package": priced}


@pytest.mark.parametrize("refused_headers", [COMMERCIAL_MANAGER, FINANCE_CONTROLLER],
                         ids=["CommercialManager", "FinanceController"])
def test_the_roles_closest_to_the_price_still_may_not_approve_it(
    api: ApiClient, refused_headers: Dict[str, str],
) -> None:
    """The hand that built the package and the hand that owns money are both out.

    The commercial manager created this package, gave it its component line and
    computed its price; the finance controller owns spend and reads the fixture's
    margin. Neither may release the package for sale, and the refusal lands before
    any state change: the package is still priced-not-published, its version is
    where pricing left it, and no approver is recorded.

    PRD §3.4: "Publication belongs to the `CommercialDirector` alone and is the
    compliance spine of the commercial process."

    PRD §2.1: "When both headers are well formed but the declared role is not
    authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED`
    (HTTP 403). Authorisation per endpoint is tabulated in §4."

    PRD §4: "| POST | `/package-products/{id}/publish` | Publishes a priced
    package for sale. | CommercialDirector |"

    Design: Corner/rbac/only_the_commercial_director_may_publish_a_price
    """
    scenario = _priced_bronze_package(api)
    package_id = scenario["package"]["id"]
    priced_version = scenario["package"]["version"]

    response = api.publish_package_product(
        package_id, publish_payload(priced_version), refused_headers
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)
    untouched = get_success_data(
        api.get_package_product(package_id, COMMERCIAL_MANAGER)
    )
    assert untouched["package_status"] == "PRICED"
    assert untouched["version"] == priced_version
    assert untouched["published_by_user_id"] is None
    assert untouched["published_at"] is None


def test_the_byte_identical_body_lands_for_the_commercial_director(
    api: ApiClient,
) -> None:
    """Only the acting role changes between the two refusals and the approval.

    The version pin, the path and the body are exactly what the refused calls
    sent, so nothing but the authority of the caller can explain the difference in
    outcome. The approval stamps the director as the approver.

    PRD §2.1: "A `CommercialDirector` approves the reviewed margin and releases a
    package for sale. Publication is exclusive to this role, and is additionally
    blocked when the acting user is the same user who priced the package."

    PRD §3.4: "When all of that holds, `package_status` becomes `PUBLISHED`,
    `published_by_user_id` is stamped with the acting user, `published_at` is
    stamped with the logical clock, and the package's `version` increases by one
    again."

    Design: Corner/rbac/only_the_commercial_director_may_publish_a_price
    """
    scenario = _priced_bronze_package(api)
    package_id = scenario["package"]["id"]
    body = publish_payload(scenario["package"]["version"])

    validate_error(api.publish_package_product(package_id, body, COMMERCIAL_MANAGER),
                   ERR_UNAUTHORIZED, 403)
    validate_error(api.publish_package_product(package_id, body, FINANCE_CONTROLLER),
                   ERR_UNAUTHORIZED, 403)

    published = get_success_data(
        api.publish_package_product(package_id, body, COMMERCIAL_DIRECTOR)
    )

    assert published["package_status"] == "PUBLISHED"
    assert published["published_by_user_id"] == USER_COMMERCIAL_DIRECTOR
    assert published["version"] == scenario["package"]["version"] + 1


# --------------------------------------------------------------------------
# Only the finance controller commits the organisation to money
# --------------------------------------------------------------------------


def _planned_build_and_a_fully_released_deal(api: ApiClient) -> Dict[str, Any]:
    """A PLANNED ZONE_A build and a 20-unit deal that has released all of it.

    Neither money-committing verb has been used yet, so both are available to
    probe, and the deal holds no allocation blocks at all.
    """
    reset_clock(api)
    event = make_event(api)
    build = make_build(api, event["id"], space_units=30, catering_covers=20,
                       staff_count=5)
    deal = make_committed_deal(api, event["id"], contracted_units=20,
                               guaranteed_minimum_units=0)
    release_deal(api, deal["id"], 20)
    released = get_success_data(api.get_rights_deal(deal["id"], RIGHTS_MANAGER))
    assert build["build_state"] == "PLANNED"
    assert released["deal_status"] == "FULLY_RELEASED"
    return {"event": event, "build": build, "deal": released}


def test_the_hand_that_planned_the_build_may_not_approve_its_own_spend(
    api: ApiClient,
) -> None:
    """PLANNED is exactly the state approval wants, and the planner is still out.

    The operations manager created this build and is the only role that can take
    it further once approved, but committing its cost to the fixture's margin is
    not its call. That the refusal is about the actor rather than the state is
    shown immediately afterwards: the operations manager's own exclusive verb on
    the very same row answers on business grounds instead.

    PRD §2.1: "A `FinanceController` controls money and cost recognition: it
    approves build, catering and staffing spend, settles rights deals against the
    holder, records installment payments, and reads the event margin."

    PRD §3.7: "Declaring the build-out dressed, catered and staffed is the
    `OperationsManager`'s call and requires the build to be `APPROVED`, otherwise
    `ERR_INVALID_BUILD_STATE`; it also requires the build to be genuinely
    resourced, meaning `staff_count` of at least 1 and `catering_covers` of at
    least 1, and a build that is neither staffed nor catered cannot be declared
    ready."

    PRD §5: "| `ERR_INVALID_BUILD_STATE` | 409 |"

    Design: Corner/rbac/only_the_finance_controller_may_commit_the_organisation_to_spend_or_settlement
    """
    scenario = _planned_build_and_a_fully_released_deal(api)
    build_id = scenario["build"]["id"]

    refused = api.approve_hospitality_build(build_id, OPERATIONS_MANAGER)
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    on_business_grounds = api.ready_hospitality_build(build_id, OPERATIONS_MANAGER)
    validate_error(on_business_grounds, ERR_INVALID_BUILD_STATE, 409)

    untouched = get_success_data(api.get_hospitality_build(build_id, OPERATIONS_MANAGER))
    assert untouched["build_state"] == "PLANNED"
    assert untouched["approved_by_user_id"] is None


def test_the_rights_manager_who_owns_the_deal_may_not_settle_it(
    api: ApiClient,
) -> None:
    """Owning the deal and having confirmed its releases is not authority to pay.

    The rights manager registered this deal, committed it and confirmed the
    tranche that released it, and the deal would in any case earn a state refusal
    because its fixture has not been played out. The authority refusal is what
    comes back, and the state complaint never surfaces.

    PRD §3.1: "A `FinanceController`, not the rights manager, closes the deal out
    against the holder."

    PRD §3.1: "Settlement is permitted only when `deal_status` is
    `PARTIALLY_RELEASED`, `FULLY_RELEASED` or `SHORTFALL_DECLARED`, the fixture has
    reached `COMPLETED` or `CANCELLED`, and no tranche of the deal is still
    `PENDING`; any of those failing gives `ERR_INVALID_DEAL_STATE`."

    PRD §2.7: "**Authorisation.** The role appears in the called endpoint's
    authorised list — `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/only_the_finance_controller_may_commit_the_organisation_to_spend_or_settlement
    """
    scenario = _planned_build_and_a_fully_released_deal(api)
    deal_id = scenario["deal"]["id"]
    assert scenario["event"]["status"] == "SCHEDULED"

    response = api.settle_rights_deal(deal_id, RIGHTS_MANAGER)

    body = validate_error(response, ERR_UNAUTHORIZED, 403)
    assert body["error_id"] != ERR_INVALID_DEAL_STATE

    untouched = get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER))
    assert untouched["deal_status"] == "FULLY_RELEASED"
    assert untouched["settled_at"] is None


def test_the_two_hands_interleave_on_one_build_row(api: ApiClient) -> None:
    """Approval and readiness are different hands walking the same record.

    The finance controller's approval stamps it as the approver, and only then may
    the operations manager declare the build-out dressed. Each verb is refused to
    the other hand, yet the row moves through both.

    PRD §3.7: "Approval moves `PLANNED → APPROVED`, stamps `approved_by_user_id`
    with the acting `X-User-ID`, and from that moment the build's
    `total_cost_cents` counts against the fixture's margin."

    PRD §4: "| POST | `/hospitality-builds/{id}/ready` | Declares an approved
    build-out dressed, catered and staffed, enabling credential issuance on the
    fixture. | OperationsManager |"

    Design: Corner/rbac/only_the_finance_controller_may_commit_the_organisation_to_spend_or_settlement
    """
    scenario = _planned_build_and_a_fully_released_deal(api)
    build_id = scenario["build"]["id"]
    validate_error(api.approve_hospitality_build(build_id, OPERATIONS_MANAGER),
                   ERR_UNAUTHORIZED, 403)

    approved = get_success_data(
        api.approve_hospitality_build(build_id, FINANCE_CONTROLLER)
    )
    assert approved["build_state"] == "APPROVED"
    assert approved["approved_by_user_id"] == USER_FINANCE_CONTROLLER

    readied = get_success_data(api.ready_hospitality_build(build_id, OPERATIONS_MANAGER))
    assert readied["build_state"] == "READY"


# --------------------------------------------------------------------------
# Rostering and reading are shared; registering a host is not
# --------------------------------------------------------------------------


def _one_host_and_two_allocated_bookings(api: ApiClient) -> Dict[str, Any]:
    """A host with capacity for two bookings, and two bookings holding inventory.

    Both bookings sit on the same fixture and the same approved build-out, so the
    only difference between the two roster lines below is the hand that files
    them.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=40,
                               guaranteed_minimum_units=0)
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=40)
    release_deal(api, deal["id"], 40)
    build = approve_build(api, make_build(api, event["id"], space_units=30,
                                         catering_covers=20, staff_count=5)["id"])
    host = make_host(api, max_concurrent_bookings=2)
    package = make_published_bronze_package(api, event["id"])
    first_client = make_client(api)
    second_client = make_client(api, name="Vantage Partners",
                                client_type="TRAVEL_PARTNER")
    bookings = []
    for client in (first_client, second_client):
        booking = make_booking(api, client["id"], package["id"], units=5)
        bookings.append(allocate_booking(api, booking["id"], block["id"]))
    return {
        "event": event,
        "build": build,
        "host": host,
        "package": package,
        "clients": [first_client, second_client],
        "bookings": bookings,
    }


def test_the_same_rostering_endpoint_accepts_either_hand(api: ApiClient) -> None:
    """Two roster lines, two different callers, one host counter.

    The selling agent files the first shift and the operations manager files the
    second, with the same shape of body against the same host and the same
    build-out. Both open in the same state, they are distinct records, and the
    host's counter aggregates them without caring who filed them.

    PRD §3.7: "Rostering a host is shared between the `ClientServiceAgent` and the
    `OperationsManager`."

    PRD §3.7: "A new host opens with `active_assignment_count` at 0; that counter
    is always the number of that host's assignments whose `assignment_state` is
    `ASSIGNED`."

    Design: Corner/rbac/rostering_and_reading_are_shared_across_hands_while_registration_stays_exclusive
    """
    scenario = _one_host_and_two_allocated_bookings(api)
    host_id = scenario["host"]["id"]
    build_id = scenario["build"]["id"]

    by_agent = get_success_data(
        api.create_host_assignment(
            host_assignment_payload(host_id, scenario["bookings"][0]["id"], build_id),
            CLIENT_SERVICE_AGENT,
        ),
        201,
    )
    by_operations = get_success_data(
        api.create_host_assignment(
            host_assignment_payload(host_id, scenario["bookings"][1]["id"], build_id),
            OPERATIONS_MANAGER,
        ),
        201,
    )

    assert by_agent["assignment_state"] == "ASSIGNED"
    assert by_operations["assignment_state"] == "ASSIGNED"
    assert by_agent["id"] != by_operations["id"]
    assert read_host(api, host_id)["active_assignment_count"] == 2


def test_releasing_a_roster_line_is_shared_crosswise_between_the_hands(
    api: ApiClient,
) -> None:
    """Each hand releases the shift the other one filed.

    Sharing is symmetric rather than a matter of who created the row: the
    operations manager releases the agent's roster line and the agent releases the
    operations manager's, and both land in the released state with the host's
    capacity handed back.

    PRD §3.7: "Released deliberately — by an `OperationsManager` or a
    `ClientServiceAgent`, and also automatically for every still-`ASSIGNED` roster
    when the fixture is completed — it moves `ASSIGNED → RELEASED` with
    `released_at` stamped at the logical clock, and the host's
    `active_assignment_count` and the booking's itinerary host list are
    recomputed."

    PRD §4: "| POST | `/host-assignments/{id}/release` | Releases an active host
    assignment, freeing the host's capacity and refreshing the booking's itinerary
    host list. | OperationsManager, ClientServiceAgent |"

    Design: Corner/rbac/rostering_and_reading_are_shared_across_hands_while_registration_stays_exclusive
    """
    scenario = _one_host_and_two_allocated_bookings(api)
    host_id = scenario["host"]["id"]
    build_id = scenario["build"]["id"]
    by_agent = get_success_data(
        api.create_host_assignment(
            host_assignment_payload(host_id, scenario["bookings"][0]["id"], build_id),
            CLIENT_SERVICE_AGENT,
        ),
        201,
    )
    by_operations = get_success_data(
        api.create_host_assignment(
            host_assignment_payload(host_id, scenario["bookings"][1]["id"], build_id),
            OPERATIONS_MANAGER,
        ),
        201,
    )

    released_by_operations = get_success_data(
        api.release_host_assignment(by_agent["id"], OPERATIONS_MANAGER)
    )
    released_by_agent = get_success_data(
        api.release_host_assignment(by_operations["id"], CLIENT_SERVICE_AGENT)
    )

    assert released_by_operations["assignment_state"] == "RELEASED"
    assert released_by_agent["assignment_state"] == "RELEASED"
    assert read_host(api, host_id)["active_assignment_count"] == 0


def test_registering_a_host_is_not_shared_with_the_selling_agent(
    api: ApiClient,
) -> None:
    """The agent that may roster a host may not put one on the books.

    Rostering and registration sit on adjacent endpoints of the same entity
    family, and the agent holds the first but not the second — so a role list
    copied from the roster endpoint onto the registration endpoint is wrong.

    PRD §2.1: "An `OperationsManager` runs the venue and the clock: it plans
    hospitality build-outs, declares them dressed and staffed, registers hosts,
    and drives the daily rollover sweep."

    PRD §4: "| POST | `/on-site-hosts` | Registers an on-site host with the
    languages they service and their concurrent-assignment capacity. |
    OperationsManager |"

    PRD §5: "| `ERR_UNAUTHORIZED` | 403 |"

    Design: Corner/rbac/rostering_and_reading_are_shared_across_hands_while_registration_stays_exclusive
    """
    _one_host_and_two_allocated_bookings(api)

    response = api.create_on_site_host(
        on_site_host_payload(full_name="Marc Delacroix", languages=["FR"]),
        CLIENT_SERVICE_AGENT,
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)


def test_the_fixture_read_is_open_to_every_hand_including_the_portal_client(
    api: ApiClient,
) -> None:
    """The widest sharing in the matrix: the fixture reads for staff and buyer.

    The rights manager who registered it, the director who approves prices on it
    and the buying client acting for itself all retrieve the same fixture record.
    The portal identity is the interesting one, because its `X-User-ID` is a client
    id rather than an operator handle.

    PRD §4: "| GET | `/events/{id}` | Retrieves a fixture with its postponement
    history, fulfillment risk score and risk posture. | RightsManager,
    CommercialManager, CommercialDirector, ClientServiceAgent, FinanceController,
    OperationsManager, ClientPortalUser |"

    PRD §2.1: "When `X-User-Role` is `ClientPortalUser`, by contrast, `X-User-ID`
    is the `id` of the acting `Client`."

    Design: Corner/rbac/rostering_and_reading_are_shared_across_hands_while_registration_stays_exclusive
    """
    scenario = _one_host_and_two_allocated_bookings(api)
    event_id = scenario["event"]["id"]
    portal = make_client_portal_user_headers(scenario["clients"][0]["id"])

    for headers in (portal, RIGHTS_MANAGER, COMMERCIAL_DIRECTOR):
        assert get_success_data(api.get_event(event_id, headers))["id"] == event_id


# --------------------------------------------------------------------------
# The hand that set the price can never be the hand that approves it
# --------------------------------------------------------------------------


def _unpriced_bronze_package(api: ApiClient) -> Dict[str, Any]:
    """A one-line BRONZE package that nobody has priced yet.

    Because pricing is shared between the manager and the director, which hand
    performs it decides which hand is afterwards disqualified from approving it.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    package = make_bronze_package(api, event["id"])
    add_component(api, package["id"])
    return {"event": event, "deal": deal, "package": package}


def test_the_wrong_role_is_answered_before_the_conflicted_identity(
    api: ApiClient,
) -> None:
    """The pricer publishing under its own role breaks two rules and hears one.

    Pricing stamps the acting user on the package. That same user then attempts to
    publish while still declaring the commercial manager role, which is both an
    unauthorised role and a conflicted identity — and authority is answered first,
    so the segregation complaint is not what comes back.

    PRD §3.4: "Finally the pass sets `package_status` to `PRICED`, stamps
    `priced_by_user_id` with the acting `X-User-ID` and `priced_at` with the
    logical clock, clears both `published_by_user_id` and `published_at` back to
    null, and increases the package's `version` by one."

    PRD §2.7: "**Authorisation.** The role appears in the called endpoint's
    authorised list — `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/the_hand_that_set_the_price_can_never_be_the_hand_that_approves_it
    """
    scenario = _unpriced_bronze_package(api)
    priced = price_package(api, scenario["package"]["id"])
    assert priced["priced_by_user_id"] == USER_COMMERCIAL_MANAGER

    response = api.publish_package_product(
        priced["id"], publish_payload(priced["version"]), COMMERCIAL_MANAGER
    )

    body = validate_error(response, ERR_UNAUTHORIZED, 403)
    assert body["error_id"] != ERR_SEGREGATION_OF_DUTIES


def test_the_same_hand_wearing_the_director_role_lands_on_segregation_of_duties(
    api: ApiClient,
) -> None:
    """Clearing the authority rule exposes the identity rule underneath it.

    The acting user is unchanged from the one that priced the package; only the
    declared role changes to the one publication requires. That removes the
    authority objection and leaves the conflict of interest, which is refused with
    its own code at the same status.

    PRD §3.4: "The acting `X-User-ID` must differ from the package's
    `priced_by_user_id`: the operator who set a price may never be the operator who
    approves it, and an attempt to do both is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD §5: "| `ERR_SEGREGATION_OF_DUTIES` | 403 |"

    Design: Corner/rbac/the_hand_that_set_the_price_can_never_be_the_hand_that_approves_it
    """
    scenario = _unpriced_bronze_package(api)
    priced = price_package(api, scenario["package"]["id"])
    body = publish_payload(priced["version"])

    validate_error(api.publish_package_product(priced["id"], body, COMMERCIAL_MANAGER),
                   ERR_UNAUTHORIZED, 403)

    response = api.publish_package_product(priced["id"], body,
                                           COMMERCIAL_DIRECTOR_AS_PRICER)

    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)
    untouched = get_success_data(api.get_package_product(priced["id"], COMMERCIAL_DIRECTOR))
    assert untouched["package_status"] == "PRICED"
    assert untouched["version"] == priced["version"]


def test_a_second_hand_in_the_director_role_publishes_the_reviewed_version(
    api: ApiClient,
) -> None:
    """A different operator in the approving role is what the rule wants.

    Same role, same version pin, same body as the refused attempt — a different
    acting user. The approval lands and the version moves on by one from the one
    that was reviewed.

    PRD §2.1: "A `CommercialDirector` approves the reviewed margin and releases a
    package for sale. Publication is exclusive to this role, and is additionally
    blocked when the acting user is the same user who priced the package."

    PRD §3.4: "When all of that holds, `package_status` becomes `PUBLISHED`,
    `published_by_user_id` is stamped with the acting user, `published_at` is
    stamped with the logical clock, and the package's `version` increases by one
    again."

    Design: Corner/rbac/the_hand_that_set_the_price_can_never_be_the_hand_that_approves_it
    """
    scenario = _unpriced_bronze_package(api)
    priced = price_package(api, scenario["package"]["id"])
    body = publish_payload(priced["version"])
    validate_error(api.publish_package_product(priced["id"], body,
                                               COMMERCIAL_DIRECTOR_AS_PRICER),
                   ERR_SEGREGATION_OF_DUTIES, 403)

    published = get_success_data(
        api.publish_package_product(priced["id"], body, COMMERCIAL_DIRECTOR)
    )

    assert published["package_status"] == "PUBLISHED"
    assert published["published_by_user_id"] == USER_COMMERCIAL_DIRECTOR
    assert published["version"] == priced["version"] + 1


def test_re_pricing_moves_the_disqualification_along_with_the_stamp(
    api: ApiClient,
) -> None:
    """The bar follows the pricing stamp, and it swaps the two hands over.

    The manager prices the package first, so at that point the manager is the
    barred hand. The director then re-prices it through the legal PRICED
    self-loop, which re-stamps the pricer onto him and bumps the version. He is
    now barred from his own exclusive verb, while the manager who was the barred
    hand a moment ago may publish it wearing the director role — the
    disqualification is about the hand, not about the person's rank.

    PRD §3.4: "Pricing is available from `DRAFT` and, as a self-loop, from
    `PRICED`, and may be performed by a `CommercialManager` or a
    `CommercialDirector`."

    PRD §3.4: "The acting `X-User-ID` must differ from the package's
    `priced_by_user_id`: the operator who set a price may never be the operator who
    approves it, and an attempt to do both is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/the_hand_that_set_the_price_can_never_be_the_hand_that_approves_it
    """
    scenario = _unpriced_bronze_package(api)
    package_id = scenario["package"]["id"]
    first_price = price_package(api, package_id)
    assert first_price["priced_by_user_id"] == USER_COMMERCIAL_MANAGER

    re_priced = get_success_data(
        api.price_package_product(package_id, COMMERCIAL_DIRECTOR)
    )
    assert re_priced["package_status"] == "PRICED"
    assert re_priced["priced_by_user_id"] == USER_COMMERCIAL_DIRECTOR
    assert re_priced["published_by_user_id"] is None
    assert re_priced["version"] == first_price["version"] + 1

    body = publish_payload(re_priced["version"])
    validate_error(api.publish_package_product(package_id, body, COMMERCIAL_DIRECTOR),
                   ERR_SEGREGATION_OF_DUTIES, 403)

    republished = get_success_data(
        api.publish_package_product(package_id, body, COMMERCIAL_DIRECTOR_AS_PRICER)
    )
    assert republished["package_status"] == "PUBLISHED"
    assert republished["published_by_user_id"] == USER_COMMERCIAL_MANAGER


# --------------------------------------------------------------------------
# The portal identity is confined to the rows that trace back to it
# --------------------------------------------------------------------------


def _two_clients_with_one_booking_each(api: ApiClient) -> Dict[str, Any]:
    """Two clients holding indistinguishable 5-unit bookings on one package.

    Because the two bookings differ in nothing but their buyer, the scope of the
    acting portal identity is the only thing that can decide which one it may
    touch.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    package = make_published_bronze_package(api, event["id"])
    own_client = make_client(api)
    other_client = make_client(api, name="Vantage Partners")
    own_booking = make_booking(api, own_client["id"], package["id"], units=5)
    other_booking = make_booking(api, other_client["id"], package["id"], units=5)
    other_lines = installments_of(api, other_booking["id"])
    return {
        "event": event,
        "deal": deal,
        "package": package,
        "own_client": own_client,
        "other_client": other_client,
        "own_booking": own_booking,
        "other_booking": other_booking,
        "other_first_line": other_lines[0],
        "portal": make_client_portal_user_headers(own_client["id"]),
    }


def test_the_portal_client_reads_the_rows_that_trace_back_to_it(
    api: ApiClient,
) -> None:
    """Its own client record and its own booking are both readable.

    The acting header value is the client's own id, so the ownership comparison
    succeeds on both rows, and the booking it reads back is linked to exactly that
    client.

    PRD §2.1: "Ownership checks therefore compare the resource's client linkage to
    `X-User-ID` directly: the header value must match an existing `Client` record,
    and it must equal the `client_id` of every `Booking`, `PaymentInstallment`
    (reached through the installment's owning booking) or `Client` resource the
    request touches."

    PRD §2.1: "A `ClientPortalUser` is the buying client acting for itself through
    the self-service portal."

    Design: Corner/rbac/the_portal_identity_is_confined_to_the_rows_that_trace_back_to_it
    """
    scenario = _two_clients_with_one_booking_each(api)
    portal = scenario["portal"]
    client_id = scenario["own_client"]["id"]

    own_client = get_success_data(api.get_client(client_id, portal))
    own_booking = get_success_data(api.get_booking(scenario["own_booking"]["id"], portal))

    assert own_client["id"] == client_id
    assert own_booking["id"] == scenario["own_booking"]["id"]
    assert own_booking["client_id"] == client_id


@pytest.mark.parametrize("probe", ["read_client", "read_booking", "read_installment",
                                   "pay_installment", "cancel_booking"])
def test_every_row_of_another_client_is_refused_on_scope(
    api: ApiClient, probe: str,
) -> None:
    """Reads and writes alike are refused on the other client's rows.

    The portal identity can name every one of these rows, and the payment probe
    even offers the exactly correct amount while the cancellation probe names a
    perfectly cancellable booking — yet the scope check runs ahead of every
    business rule, so the amount and the state never get a say.

    PRD §2.1: "A violation is rejected with `ERR_CLIENT_SCOPE_VIOLATION` (HTTP
    403)."

    PRD §2.1: "This scope check guards reading a client record, reading a booking,
    reading an installment, paying an installment and cancelling a booking."

    PRD §2.7: "**Client scope.** For a `ClientPortalUser`, every touched client,
    booking or installment traces back to `X-User-ID` — `ERR_CLIENT_SCOPE_VIOLATION`."

    Design: Corner/rbac/the_portal_identity_is_confined_to_the_rows_that_trace_back_to_it
    """
    scenario = _two_clients_with_one_booking_each(api)
    portal = scenario["portal"]
    other_booking_id = scenario["other_booking"]["id"]
    other_line = scenario["other_first_line"]

    if probe == "read_client":
        response = api.get_client(scenario["other_client"]["id"], portal)
    elif probe == "read_booking":
        response = api.get_booking(other_booking_id, portal)
    elif probe == "read_installment":
        response = api.get_payment_installment(other_line["id"], portal)
    elif probe == "pay_installment":
        response = api.pay_installment(other_line["id"],
                                       pay_payload(other_line["amount_cents"]), portal)
    else:
        response = api.cancel_booking(other_booking_id, portal)

    validate_error(response, ERR_CLIENT_SCOPE_VIOLATION, 403)


def test_the_staff_only_collection_is_a_different_refusal_altogether(
    api: ApiClient,
) -> None:
    """Outside the matrix row is an authority refusal, not a scope refusal.

    The booking list is not an endpoint the portal identity appears on at all, so
    the refusal is the authorisation one and never reaches the scope check. The
    same rows the portal user was refused are perfectly readable by staff, which
    shows the refusals were about the caller rather than the data.

    PRD §4: "| GET | `/bookings` | Lists bookings, filterable by client, package,
    allocation block, fulfillment status and payment status. | ClientServiceAgent,
    FinanceController |"

    PRD §2.7: "Checks are evaluated in the fixed sequence below and the first
    failing check produces the response."

    Design: Corner/rbac/the_portal_identity_is_confined_to_the_rows_that_trace_back_to_it
    """
    scenario = _two_clients_with_one_booking_each(api)

    refused = api.list_bookings(scenario["portal"], {"limit": 10, "offset": 0})
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    for_staff = get_success_data(
        api.get_booking(scenario["other_booking"]["id"], CLIENT_SERVICE_AGENT)
    )
    assert for_staff["id"] == scenario["other_booking"]["id"]
