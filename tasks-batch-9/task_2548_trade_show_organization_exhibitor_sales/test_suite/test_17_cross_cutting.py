"""
Version pinning across the six inventory-consuming writes: which parent row each
one pins, and what a stale pin leaves behind.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    AppointmentState,
    BoothStatus,
    CancellationReason,
    FloorPosture,
    ShowStatus,
    SpaceContractStatus,
    VenueContractStatus,
    factories as f,
    fixtures as fx,
    make_exhibitor_headers,
    make_sales_rep_headers,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"
DESK_CLOCK = "2027-03-01T09:30:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)
D010 = f.inline_booth_payload("D010", 10, 10)
F100 = f.booth_payload("F100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)

REP = make_sales_rep_headers("u_sr_1")


# ── One OCC field, three endpoints, one parent ───────────────────────────────
def _desk_open_env(client: ApiClient) -> dict:
    """
    Round one is open with Harbor's slot `ACTIVE`, and Alder is free to buy
    off-appointment on the same floor.
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050, D010])
    show_id = env["show"]["id"]
    alder = fx.exhibitor(client, "Alder Textiles",
                         contact_email="space@alder.example",
                         consecutive_years=1, headers=fx.SALES_REP_HEADERS)
    harbor = fx.exhibitor(client, "Harbor Ceramics",
                          contact_email="space@harbor.example",
                          consecutive_years=2, headers=fx.SALES_REP_HEADERS)
    appointment = fx.scheduled_appointment(
        client, show_id, harbor["id"], 1,
        "2027-03-01T09:00:00Z", "2027-03-01T11:00:00Z", headers=REP,
    )
    fx.set_clock(client, DESK_CLOCK)
    validate_success(client.advance_selection_round(show_id, fx.DIRECTOR_HEADERS))
    activated = validate_success(
        client.get_selection_appointment(appointment["id"], fx.DIRECTOR_HEADERS)
    )
    assert activated["state"] == AppointmentState.ACTIVE
    env.update({"show_id": show_id, "alder": alder, "harbor": harbor,
                "alder_headers": make_exhibitor_headers(alder["id"]),
                "harbor_headers": make_exhibitor_headers(harbor["id"]),
                "appointment": appointment})
    return env


def test_one_pinned_version_goes_stale_across_create_sign_and_exercise(
    client: ApiClient,
):
    """
    Three writes on the same floor, each composed against the version the caller
    read one write too early, then each re-issued against the current one.

    "Four of them pin the show whose floor is being consumed and require
    `expected_show_version` to equal that show's current `version`"  "If the
    supplied `expected_show_version` does not equal the show's current `version`,
    the request is rejected with `ERR_STALE_SHOW_VERSION` (HTTP 412) and nothing is
    written."

    Design: Corner/cross_cutting_complexity_layers/stale_show_version_is_refused_on_contract_create_sign_and_appointment_exercise
    """
    env = _desk_open_env(client)
    show_id = env["show_id"]
    booth_c = env["booth_by_number"]["C050"]["id"]
    booth_d = env["booth_by_number"]["D010"]["id"]
    version_1 = fx.show_version(client, show_id)

    stale_create = f.space_contract_payload(show_id, env["alder"]["id"],
                                           version_1 - 1, 200,
                                           booth_ids=[booth_c])
    validate_error(
        client.create_space_contract(stale_create, REP),
        ApiErrorId.STALE_SHOW_VERSION,
        412,
    )
    assert fx.read_booth(client, booth_c)["status"] == BoothStatus.AVAILABLE
    assert fx.show_version(client, show_id) == version_1

    contract = validate_success(
        client.create_space_contract(
            f.space_contract_payload(show_id, env["alder"]["id"], version_1, 200,
                                     booth_ids=[booth_c]),
            REP,
        ),
        201,
    )
    version_2 = fx.show_version(client, show_id)
    assert version_2 == version_1 + 1

    validate_error(
        client.sign_space_contract(contract["id"], f.sign_payload(version_1, 163750),
                                   env["alder_headers"]),
        ApiErrorId.STALE_SHOW_VERSION,
        412,
    )
    assert (
        fx.read_contract(client, contract["id"])["status"]
        == SpaceContractStatus.OFFERED
    )

    signed = validate_success(
        client.sign_space_contract(contract["id"], f.sign_payload(version_2, 163750),
                                   env["alder_headers"])
    )
    assert signed["status"] == SpaceContractStatus.SIGNED
    assert signed["deposit_paid_cents"] == 163750
    assert fx.read_booth(client, booth_c)["status"] == BoothStatus.ASSIGNED

    version_3 = fx.show_version(client, show_id)
    assert version_3 == version_2 + 1

    appointment_id = env["appointment"]["id"]
    validate_error(
        client.exercise_appointment(
            appointment_id,
            f.exercise_payload(version_2, 100, booth_ids=[booth_d]),
            env["harbor_headers"],
        ),
        ApiErrorId.STALE_SHOW_VERSION,
        412,
    )
    held_back = validate_success(
        client.get_selection_appointment(appointment_id, fx.DIRECTOR_HEADERS)
    )
    assert held_back["state"] == AppointmentState.ACTIVE
    assert fx.read_booth(client, booth_d)["status"] == BoothStatus.AVAILABLE
    assert fx.show_version(client, show_id) == version_3

    exercised_contract = validate_success(
        client.exercise_appointment(
            appointment_id,
            f.exercise_payload(version_3, 100, booth_ids=[booth_d]),
            env["harbor_headers"],
        ),
        201,
    )
    assert exercised_contract["exhibitor_id"] == env["harbor"]["id"]
    assert exercised_contract["status"] == SpaceContractStatus.OFFERED
    assert fx.read_booth(client, booth_d)["status"] == BoothStatus.HELD
    assert (
        validate_success(
            client.get_selection_appointment(appointment_id, fx.DIRECTOR_HEADERS)
        )["state"]
        == AppointmentState.EXERCISED
    )
    assert fx.show_version(client, show_id) == version_3 + 1


# ── The combine pins the booth set, not a hold ───────────────────────────────
def test_a_stale_combine_leaves_the_floor_plan_exactly_as_it_was(client: ApiClient):
    """
    The merge body is identical both times; only the pinned version differs, and
    the refused attempt moves neither booth nor ledger.

    "`POST /booths/{id}/combine` — a combine rewrites the show's sellable
    inventory, and must not silently absorb a booth another writer has already
    held."  "On success each child moves `AVAILABLE → MERGED` with its
    `combined_parent_booth_id` pointing at the survivor, and each child's
    `area_sqft` is added to the survivor's `area_sqft`."  "As §2.9 states, a combine
    leaves `sellable_booth_sqft` unchanged — area is conserved, never created."

    Design: Corner/cross_cutting_complexity_layers/a_stale_combine_leaves_the_floor_plan_exactly_as_it_was
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050, D010])
    show_id = env["show"]["id"]
    booth_a = env["booth_by_number"]["A100"]["id"]
    booth_c = env["booth_by_number"]["C050"]["id"]
    booth_d = env["booth_by_number"]["D010"]["id"]
    alder = fx.exhibitor(client, "Alder Textiles",
                         contact_email="space@alder.example",
                         consecutive_years=1, headers=fx.SALES_REP_HEADERS)
    offered = fx.offered_contract(client, show_id, alder["id"], 400, [booth_a],
                                 headers=REP, premium_placement_requested=True)
    fx.sign_contract(client, offered, 389070)

    before = fx.read_show(client, show_id)
    assert before["sellable_booth_sqft"] == 700
    assert before["assigned_net_sqft"] == 400
    assert before["committed_ratio_pct"] == 57
    pinned = before["version"]

    validate_error(
        client.combine_booths(booth_c, f.combine_payload(pinned - 1, [booth_d]),
                              fx.FLOOR_MANAGER_HEADERS),
        ApiErrorId.STALE_SHOW_VERSION,
        412,
    )
    assert fx.read_booth(client, booth_c)["area_sqft"] == 200
    child_before = fx.read_booth(client, booth_d)
    assert child_before["status"] == BoothStatus.AVAILABLE
    assert child_before["combined_parent_booth_id"] is None
    assert fx.show_version(client, show_id) == pinned

    survivor = validate_success(
        client.combine_booths(booth_c, f.combine_payload(pinned, [booth_d]),
                              fx.FLOOR_MANAGER_HEADERS)
    )
    assert survivor["area_sqft"] == 300
    child_after = fx.read_booth(client, booth_d)
    assert child_after["status"] == BoothStatus.MERGED
    assert child_after["combined_parent_booth_id"] == booth_c

    after = fx.read_show(client, show_id)
    assert after["sellable_booth_sqft"] == 700
    assert after["assigned_net_sqft"] == 400
    assert after["committed_ratio_pct"] == 57
    assert after["floor_posture"] == FloorPosture.OPEN
    assert after["version"] == pinned + 1


# ── The one rule whose field names the target ────────────────────────────────
SHOW_2028 = {
    "edition_year": 2028,
    "move_in_start": "2028-03-01",
    "event_start": "2028-03-05",
    "event_end": "2028-03-07",
    "move_out_end": "2028-03-09",
    "base_rate_cents_per_sqft": 3400,
}
POST_SHOW_CLOCK = "2027-03-10T00:00:00Z"


def test_the_rebook_pins_the_target_edition_and_never_the_source(client: ApiClient):
    """
    The 2027 edition has not moved at all, yet the rebook is refused — and the
    version it was refused for belongs to the 2028 floor.

    "A rebook creates a contract on the *target* edition and holds booths there, so
    the field pins the target show's `version`, never the version of the show being
    rebooked from. A mismatch is again `ERR_STALE_SHOW_VERSION` (HTTP 412)."  "A
    successful rebook creates a fresh space contract in `OFFERED` on the target
    edition with `rebooked_from_space_contract_id` set to the source contract"  "the
    exhibitor's `consecutive_years` is incremented by one, which is what keeps a
    long-running exhibitor's streak intact across editions."

    Design: Corner/cross_cutting_complexity_layers/the_rebook_occ_field_pins_the_target_edition_not_the_source
    """
    fx.set_clock(client, CLOCK)
    this_year = fx.published_show(client, [A100])
    next_year = fx.published_show(client, [F100],
                                 venue_contract=this_year["venue_contract"],
                                 **SHOW_2028)
    source_show_id = this_year["show"]["id"]
    target_show_id = next_year["show"]["id"]
    target_booth = next_year["booth_by_number"]["F100"]["id"]
    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example",
                          consecutive_years=6, headers=fx.SALES_REP_HEADERS)
    offered = fx.offered_contract(client, source_show_id, nordic["id"], 400,
                                 [this_year["booth_by_number"]["A100"]["id"]],
                                 headers=REP, premium_placement_requested=True)
    source = fx.sign_contract(client, offered, 389070)
    fx.transition(client, source_show_id, ShowStatus.SELLING)
    fx.transition(client, source_show_id, ShowStatus.ON_SITE)
    fx.transition(client, source_show_id, ShowStatus.CLOSED)
    fx.set_clock(client, POST_SHOW_CLOCK)
    assert (
        fx.read_contract(client, source["id"])["status"]
        == SpaceContractStatus.CLOSED_OUT
    )
    source_version = fx.show_version(client, source_show_id)
    target_version = fx.show_version(client, target_show_id)

    body = f.rebook_payload(target_show_id, target_version - 1, 400,
                            premium_placement_requested=True,
                            booth_ids=[target_booth])
    validate_error(
        client.rebook(source["id"], body, REP),
        ApiErrorId.STALE_SHOW_VERSION,
        412,
    )
    assert fx.read_booth(client, target_booth)["status"] == BoothStatus.AVAILABLE
    refused = fx.read_show(client, target_show_id)
    assert refused["held_net_sqft"] == 0
    assert refused["version"] == target_version
    assert fx.read_exhibitor(client, nordic["id"])["consecutive_years"] == 6

    rebooked = validate_success(
        client.rebook(
            source["id"],
            f.rebook_payload(target_show_id, target_version, 400,
                             premium_placement_requested=True,
                             booth_ids=[target_booth]),
            REP,
        ),
        201,
    )
    assert rebooked["show_id"] == target_show_id
    assert rebooked["rebooked_from_space_contract_id"] == source["id"]
    assert rebooked["status"] == SpaceContractStatus.OFFERED

    assert fx.show_version(client, target_show_id) == target_version + 1
    assert fx.show_version(client, source_show_id) == source_version
    assert fx.read_exhibitor(client, nordic["id"])["consecutive_years"] == 7


# ── The one rule whose parent is not a show ──────────────────────────────────
def test_terminating_the_agreement_is_pinned_to_the_agreements_own_version(
    client: ApiClient,
):
    """
    A different field, a different error id and a different parent row — and past
    the pin, the cascade that empties the hall.

    "The sixth rule pins a venue contract. `POST /venue-contracts/{id}/terminate`
    requires `expected_venue_contract_version` to equal the venue contract's current
    `version`."  "a terminate authorised against an older version was authorised
    against a smaller blast radius than the one it would actually execute, and is
    rejected with `ERR_STALE_VENUE_CONTRACT_VERSION` (HTTP 412)."  "every show whose
    `venue_contract_id` is this agreement and whose status is `PLANNING`,
    `SPACE_SELECTION`, `SELLING` or `ON_SITE` is transitioned to `CANCELLED` with its
    `cancellation_reason` set to the literal `VENUE_CONTRACT_TERMINATED`"

    Design: Corner/cross_cutting_complexity_layers/terminating_a_venue_contract_is_guarded_by_the_contracts_own_version
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100])
    show_id = env["show"]["id"]
    booth_id = env["booth_by_number"]["A100"]["id"]
    agreement_id = env["venue_contract"]["id"]
    alder = fx.exhibitor(client, "Alder Textiles",
                         contact_email="space@alder.example",
                         consecutive_years=1, headers=fx.SALES_REP_HEADERS)
    contract = fx.offered_contract(client, show_id, alder["id"], 400, [booth_id],
                                  headers=REP, premium_placement_requested=True)
    agreement = validate_success(
        client.get_venue_contract(agreement_id, fx.DIRECTOR_HEADERS)
    )
    pinned = agreement["version"]

    validate_error(
        client.terminate_venue_contract(
            agreement_id,
            f.terminate_payload(pinned - 1, "2026-09-01",
                                reason="Hall roof replacement"),
            fx.DIRECTOR_HEADERS,
        ),
        ApiErrorId.STALE_VENUE_CONTRACT_VERSION,
        412,
    )
    refused = validate_success(
        client.get_venue_contract(agreement_id, fx.DIRECTOR_HEADERS)
    )
    assert refused["status"] == VenueContractStatus.EXECUTED
    assert refused["version"] == pinned
    assert fx.read_show(client, show_id)["status"] == ShowStatus.SPACE_SELECTION

    terminated = validate_success(
        client.terminate_venue_contract(
            agreement_id,
            f.terminate_payload(pinned, "2026-09-01",
                                reason="Hall roof replacement"),
            fx.DIRECTOR_HEADERS,
        )
    )
    assert terminated["status"] == VenueContractStatus.TERMINATED
    assert terminated["terminated_effective_date"] == "2026-09-01"
    assert terminated["version"] == pinned + 1

    cancelled_show = fx.read_show(client, show_id)
    assert cancelled_show["status"] == ShowStatus.CANCELLED
    assert (
        cancelled_show["cancellation_reason"]
        == CancellationReason.VENUE_CONTRACT_TERMINATED
    )

    cancelled_contract = fx.read_contract(client, contract["id"])
    assert cancelled_contract["status"] == SpaceContractStatus.CANCELLED
    assert cancelled_contract["cancellation_fee_cents"] == 0

    released = fx.read_booth(client, booth_id)
    assert released["status"] == BoothStatus.AVAILABLE
    assert released["space_contract_id"] is None
