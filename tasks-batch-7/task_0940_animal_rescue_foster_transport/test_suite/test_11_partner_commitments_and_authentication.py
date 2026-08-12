"""The partner transfer-slot ledger and the authentication rung."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_leg,
    assert_partner_slots_conserved,
    build_user_headers,
    manifest_animal,
    new_animal,
    new_driver,
    new_organization,
    new_partner_commitment,
    new_partner_organization,
    new_run,
    set_clock,
    take_into_custody,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCH = TEST_USERS["transport_dispatcher_headers"]


def test_the_expire_sweep_forfeits_only_the_undrawn_slots(api):
    """PRD 3.7: "The sweep visits every commitment whose `expires_at` the clock has
    strictly passed and whose `status` is `OPEN` or `PARTIALLY_DRAWN`, moves each to
    `EXPIRED`, shifts its remaining `slots_open` into `slots_released` and sets
    `slots_open` to zero, and recomputes each affected organization's
    `open_commitment_slots_total`."
    PRD 3.7: "The sweep answers with an `expired_count`, the list of
    `expired_commitment_ids`, and the total `slots_forfeited` across them. `EXPIRED` is
    terminal."
    PRD 3.7: "That organization-level roll-up is the sum of `slots_open` across the
    organization's commitments whose `status` is `OPEN` or `PARTIALLY_DRAWN`, and it is
    recomputed after every draw, return and expiry."

    Design: Corner/state_machines/partner_commitment_expire_sweep_forfeits_unused_slots
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    partner = new_partner_organization(api)
    commitment = new_partner_commitment(
        api, partner["id"], species="DOG", slots_total=4, expires_at="2026-06-01T00:00:00Z"
    )

    set_clock(api, "2026-06-02T00:00:00Z")
    swept = validate_success(api.expire_sweep_partner_commitments(DISPATCH))
    assert swept["expired_count"] == 1
    assert swept["slots_forfeited"] == 4
    assert commitment["id"] in swept["expired_commitment_ids"]

    after = validate_success(api.get_partner_commitment(commitment["id"], DISPATCH))
    assert after["status"] == "EXPIRED"
    assert after["slots_open"] == 0
    assert after["slots_released"] == 4
    assert after["slots_total"] == 4
    assert_partner_slots_conserved(after)

    org = validate_success(api.get_organization(partner["id"], ADMIN))
    assert org["open_commitment_slots_total"] == 0


def test_species_mismatch_and_expiry_each_block_a_transfer_out_run_start(api):
    """PRD 3.7: "Every one of those distinct animals must be of the commitment's
    `species`, failing which the start is refused with `ERR_PARTNER_SPECIES_MISMATCH`."
    PRD 3.7: "The commitment must not have expired — the clock must be at or before
    `expires_at` and the `status` must not be `EXPIRED` — failing which the answer is
    `ERR_PARTNER_COMMITMENT_UNAVAILABLE`."

    Each run violates exactly one of the two conditions: the first carries a dog
    against a CAT commitment that is still in date, and the second is species-matched
    against a commitment whose `expires_at` the clock has passed.

    Design: Corner/validations/partner_commitment_expired_and_species_mismatch_block_run_start
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    partner = new_partner_organization(api)
    cat_commitment = new_partner_commitment(
        api, partner["id"], species="CAT", slots_total=2, expires_at="2026-07-01T00:00:00Z"
    )
    expired_commitment = new_partner_commitment(
        api, partner["id"], species="DOG", slots_total=2, expires_at="2026-05-04T00:00:00Z"
    )
    driver_one = new_driver(api, "Milo Frey", "milo@example.test", "CDL-8891")
    driver_two = new_driver(api, "Nora Vale", "nora@example.test", "CDL-2210")

    dogs = []
    for name in ("Dog1", "Dog2"):
        dog = new_animal(api, org["id"], name=name, size_class="SMALL", weight_lb=20.0,
                         date_of_birth="2022-01-01T00:00:00Z")
        take_into_custody(api, dog["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
        dogs.append(dog)

    run_one = new_run(api, org["id"], purpose="TRANSFER_OUT",
                      partner_commitment_id=cat_commitment["id"])
    leg_one = add_leg(api, run_one["id"], driver_one["id"],
                      scheduled_depart_at="2026-05-06T08:00:00Z",
                      scheduled_arrive_at="2026-05-06T12:00:00Z",
                      crate_capacity_units=10, weight_capacity_lb=400.0,
                      species_policy="DOGS_ONLY")
    manifest_animal(api, leg_one["id"], dogs[0]["id"])

    run_two = new_run(api, org["id"], purpose="TRANSFER_OUT",
                      partner_commitment_id=expired_commitment["id"])
    leg_two = add_leg(api, run_two["id"], driver_two["id"],
                      scheduled_depart_at="2026-05-06T08:00:00Z",
                      scheduled_arrive_at="2026-05-06T12:00:00Z",
                      crate_capacity_units=10, weight_capacity_lb=400.0,
                      species_policy="DOGS_ONLY")
    manifest_animal(api, leg_two["id"], dogs[1]["id"])

    set_clock(api, "2026-05-05T00:00:00Z")

    validate_error(
        api.start_transport_run(run_one["id"], DISPATCH),
        ApiErrorId.ERR_PARTNER_SPECIES_MISMATCH.value,
        422,
    )
    validate_error(
        api.start_transport_run(run_two["id"], DISPATCH),
        ApiErrorId.ERR_PARTNER_COMMITMENT_UNAVAILABLE.value,
        409,
    )

    assert validate_success(api.get_transport_run(run_one["id"], DISPATCH))[
        "status"
    ] == "PLANNED"
    assert validate_success(api.get_transport_run(run_two["id"], DISPATCH))[
        "status"
    ] == "PLANNED"
    assert validate_success(api.get_partner_commitment(cat_commitment["id"], DISPATCH))[
        "slots_open"
    ] == 2
    assert validate_success(api.get_partner_commitment(expired_commitment["id"], DISPATCH))[
        "slots_open"
    ] == 2


def test_an_unrecognised_role_is_an_authentication_failure(api):
    """PRD 2.1: "Every request to every endpoint — reads included — must carry two
    headers: `X-User-ID`, identifying the actor, and `X-User-Role`, naming the role the
    actor is acting in."
    PRD 2.1: "If `X-User-Role` carries a string that is not one of the eleven role names
    below, the request is likewise rejected with `ERR_UNAUTHENTICATED` — an
    unrecognised role is treated as a failure to authenticate, not as a permission
    problem."

    Design: Corner/rbac/request_without_role_header_is_unauthenticated
    """
    set_clock(api, "2026-05-01T00:00:00Z")

    validate_error(
        api.list_animals(build_user_headers("someone", "NotARole")),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    rows, meta = validate_paginated(api.list_animals(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0
