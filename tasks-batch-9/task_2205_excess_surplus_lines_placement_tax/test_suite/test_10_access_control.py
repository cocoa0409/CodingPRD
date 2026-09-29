"""Authentication, role permission and resource ownership: the first three
rungs of the ladder and the one that follows field shape.
"""

from test_helpers import (
    ERR_NOT_RESOURCE_OWNER,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN,
    STATE_REGULATOR_TX,
    TAX_FILER_NINA,
    broker_payload,
    carrier_eligibility_payload,
    carrier_payload,
    make_headers,
    make_placement_broker_headers,
    validate_error,
    validate_success,
)

NO_IDENTITY = {"Content-Type": "application/json"}


def test_unauthenticated_request_missing_x_user_headers_or_carrying_an_unknown_role(
    configured_world,
):
    """Identity is established before the path is even resolved.

    PRD 2.11: "**Identity headers present.** Both `X-User-ID` and `X-User-Role`
    are non-empty strings. Applies to every endpoint. Violation:
    `ERR_UNAUTHENTICATED` (401). Checked before the path is inspected."

    PRD 2.11: "**Role recognised.** `X-User-Role` is one of the five declared
    roles. Applies to every endpoint. Violation: `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/unauthenticated_request_missing_x_user_headers_or_carrying_an_unknown_role
    """
    world = configured_world
    broker_id = world.broker["id"]

    validate_error(world.api.get_broker(broker_id, NO_IDENTITY), ERR_UNAUTHENTICATED, 401)
    validate_error(
        world.api.get_broker(broker_id, make_headers("pa-root", "")),
        ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        world.api.get_broker(broker_id, make_headers("", "PlatformAdmin")),
        ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        world.api.get_broker(broker_id, make_headers("auditor-1", "Auditor")),
        ERR_UNAUTHENTICATED,
        401,
    )

    # Identity is checked before the templated segment is resolved, so an unknown
    # id with no identity is still a 401 rather than a 404.
    validate_error(
        world.api.get_broker(NON_EXISTENT_UUID, NO_IDENTITY), ERR_UNAUTHENTICATED, 401
    )

    assert validate_success(world.api.get_broker(broker_id, PLATFORM_ADMIN), 200)[
        "id"
    ] == broker_id


def test_each_roles_exclusive_operations_are_closed_to_the_other_four_roles(
    policy_world,
):
    """Every write endpoint answers only to its declared role.

    PRD 2.11: "**Role permitted.** The endpoint's authorised-role list contains
    the acting role, or the endpoint is open to any role. Applies to every
    endpoint. Violation: `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/each_roles_exclusive_operations_are_closed_to_the_other_four_roles
    """
    world = policy_world

    # Calculating tax belongs to the TaxFiler, not the administrator.
    validate_error(
        world.api.calculate_tax(world.policy["id"], PLATFORM_ADMIN),
        ERR_UNAUTHORIZED,
        403,
    )
    # Registering an insurer belongs to the administrator, not a filer.
    validate_error(
        world.api.create_carrier(
            carrier_payload(
                naic_number="99999", legal_name="Filer Owned Insurance Company"
            ),
            TAX_FILER_NINA,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    # White-listing belongs to the state regulator, not the broker.
    validate_error(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(world.carrier["id"], world.program_id("NV")),
            world.broker_headers,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    # Opening a security review belongs to the compliance officer.
    validate_error(
        world.api.create_security_review(world.carrier["id"], STATE_REGULATOR_TX),
        ERR_UNAUTHORIZED,
        403,
    )
    # The role rung precedes path resolution, so an unknown carrier still reports
    # 403 rather than 404.
    validate_error(
        world.api.create_security_review(NON_EXISTENT_UUID, STATE_REGULATOR_TX),
        ERR_UNAUTHORIZED,
        403,
    )

    # The authorised role is unaffected.
    calculated = validate_success(
        world.api.calculate_tax(world.policy["id"], TAX_FILER_NINA), 200
    )
    assert calculated["tax_status"] == "CALCULATED"


def test_a_broker_cannot_act_on_another_brokerages_placement(placement_world):
    """Ownership is enforced on the twelve broker-owned write operations.

    PRD 2.11: "**Resource ownership.** When the acting role is `PlacementBroker`,
    the resource being written belongs to that brokerage — the relevant `broker_id`
    equals `X-User-ID`. Violation: `ERR_NOT_RESOURCE_OWNER` (403). Because
    ownership is checked *after* shape, a malformed payload aimed at someone else's
    placement reports 400. This rung guards exactly twelve operations: beginning a
    search, completing a search, recording a declination, issuing a policy, affixing
    notices, creating an endorsement, requesting a cancellation, drafting an
    affidavit, issuing an endorsement, voiding an endorsement, processing a
    cancellation, and signing an affidavit."

    Design: Corner/rbac/a_broker_cannot_act_on_another_brokerages_placement
    """
    world = placement_world
    placement = world.placement
    interloper = validate_success(
        world.api.create_broker(
            broker_payload(firm_name="Interloper Surplus Partners"), PLATFORM_ADMIN
        ),
        201,
    )
    assert interloper["id"] != world.broker["id"]
    intruder_headers = make_placement_broker_headers(interloper["id"])

    validate_error(
        world.api.begin_search(placement["id"], intruder_headers),
        ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        world.api.complete_search(placement["id"], intruder_headers),
        ERR_NOT_RESOURCE_OWNER,
        403,
    )

    after = world.get_placement(placement["id"])
    assert after["status"] == "DRAFT"
    assert after["version"] == placement["version"]

    # The owning brokerage is unaffected.
    assert placement["broker_id"] == world.broker["id"]
    opened = validate_success(
        world.api.begin_search(placement["id"], world.broker_headers), 200
    )
    assert opened["status"] == "SEARCH_IN_PROGRESS"
