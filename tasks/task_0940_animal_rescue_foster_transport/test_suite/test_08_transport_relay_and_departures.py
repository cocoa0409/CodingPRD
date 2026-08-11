"""Relay departures: the certificate gate, rabies eligibility and the abort cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_partner_slots_conserved,
    assert_same_instant,
    add_leg,
    arrive_leg,
    depart_leg,
    issue_certificate,
    make_driver_headers,
    manifest_animal,
    new_animal,
    new_driver,
    new_organization,
    new_partner_commitment,
    new_partner_organization,
    new_run,
    set_clock,
    setup_relay_run,
    setup_run_with_leg,
    start_run,
    take_into_custody,
    vaccinate_rabies,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCH = TEST_USERS["transport_dispatcher_headers"]


# --------------------------------------------------------------------------
# Aborting a departed leg: the six-hop cascade
# --------------------------------------------------------------------------
def _departed_transfer_out_relay(api):
    """A fully drawn TRANSFER_OUT relay whose second leg has departed with both dogs
    aboard, with the clock standing at 2026-05-05T14:30:00Z."""
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    partner = new_partner_organization(api)
    commitment = new_partner_commitment(
        api, partner["id"], species="DOG", slots_total=2, expires_at="2026-07-01T00:00:00Z"
    )
    driver = new_driver(api)
    dog1 = new_animal(api, org["id"], name="Dog1", weight_lb=45.0,
                      date_of_birth="2022-01-01T00:00:00Z")
    dog2 = new_animal(api, org["id"], name="Dog2", weight_lb=46.0,
                      date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, dog1["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    take_into_custody(api, dog2["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    relay = setup_relay_run(
        api, org["id"], driver=driver,
        run_overrides={"purpose": "TRANSFER_OUT", "partner_commitment_id": commitment["id"]},
        leg1_overrides={"crate_capacity_units": 10, "weight_capacity_lb": 500.0,
                        "species_policy": "DOGS_ONLY"},
        leg2_overrides={"crate_capacity_units": 10, "weight_capacity_lb": 500.0,
                        "species_policy": "DOGS_ONLY"},
    )
    manifest_animal(api, relay["leg1"]["id"], dog1["id"])
    manifest_animal(api, relay["leg1"]["id"], dog2["id"])
    entry_dog1 = manifest_animal(api, relay["leg2"]["id"], dog1["id"])
    entry_dog2 = manifest_animal(api, relay["leg2"]["id"], dog2["id"])

    started = start_run(api, relay["run"]["id"])

    set_clock(api, "2026-05-05T08:00:00Z")
    depart_leg(api, relay["leg1"]["id"])
    set_clock(api, "2026-05-05T12:00:00Z")
    arrive_leg(api, relay["leg1"]["id"])
    set_clock(api, "2026-05-05T14:00:00Z")
    depart_leg(api, relay["leg2"]["id"])
    set_clock(api, "2026-05-05T14:30:00Z")

    return {
        "org": org, "partner": partner, "commitment": commitment,
        "dog1": dog1, "dog2": dog2, "run": relay["run"],
        "leg1": relay["leg1"], "leg2": relay["leg2"],
        "entry_dog1": entry_dog1, "entry_dog2": entry_dog2,
        "slots_drawn_at_start": started["slots_drawn"],
    }


def test_aborting_a_departed_leg_strands_its_entries_and_its_animals(api):
    """PRD 3.6: "Hop two moves every `LOADED` entry on that leg to `STRANDED`, stamping
    each with a `stranded_at_hub_code` equal to the aborted leg's `origin_hub_code`."
    PRD 3.6: "Hop three moves each of those animals `IN_TRANSIT → STRANDED` and sets
    each animal's `current_hub_code` to that same hub, incrementing each animal's
    `version`."
    PRD 3.6: "Hop one is the leg itself moving `DEPARTED → ABORTED` and incrementing
    its `version`."

    Design: Difficulty/transitive_cascade/leg_abort_strands_animal_and_returns_partner_slots
    """
    scenario = _departed_transfer_out_relay(api)

    aborted = validate_success(
        api.abort_transport_leg(
            scenario["leg2"]["id"], DISPATCH, {"reason": "vehicle breakdown at HUB-B"}
        )
    )
    assert aborted["status"] == "ABORTED"

    for key in ("entry_dog1", "entry_dog2"):
        entry = validate_success(api.get_manifest_entry(scenario[key]["id"], DISPATCH))
        assert entry["status"] == "STRANDED"
        assert entry["stranded_at_hub_code"] == "HUB-B"

    for key in ("dog1", "dog2"):
        animal = validate_success(api.get_animal(scenario[key]["id"], ADMIN))
        assert animal["lifecycle_status"] == "STRANDED"
        assert animal["current_hub_code"] == "HUB-B"


def test_the_leg_abort_cascade_reaches_the_run_and_the_partner_ledger(api):
    """PRD 3.7: "Slots are drawn at the moment a **transfer-out run starts**, not when
    its legs are manifested and not when they depart. The number needed is the count of
    **distinct** animals across all of the run's legs whose manifest entries stand at
    `ASSIGNED` or `LOADED` — an animal manifested onto two legs of a relay counts
    once."
    PRD 3.6: "Hop four moves the parent run `IN_PROGRESS → ABORTED`, stamping
    `aborted_at` and invalidating the run's remaining scheduled legs. Hop five, on a
    transfer-out run, returns the drawn slots to the partner commitment. Hop six
    recomputes the partner organization's `open_commitment_slots_total`."
    PRD 3.7: "When a drawing run aborts — whether by an explicit run abort or through
    hop five of the leg-abort cascade — its `slots_drawn` are returned: the
    commitment's `slots_drawn` falls and its `slots_open` rises by the same amount, and
    the status moves `EXHAUSTED → PARTIALLY_DRAWN` when some draws remain from other
    runs, or `PARTIALLY_DRAWN → OPEN` when nothing is drawn any longer."

    Two distinct animals ride both legs, so the start draws exactly 2 slots; the abort
    returns both, and with no other run drawing on the commitment nothing is drawn any
    longer.

    Design: Difficulty/transitive_cascade/leg_abort_strands_animal_and_returns_partner_slots
    """
    scenario = _departed_transfer_out_relay(api)
    assert scenario["slots_drawn_at_start"] == 2

    validate_success(
        api.abort_transport_leg(
            scenario["leg2"]["id"], DISPATCH, {"reason": "vehicle breakdown at HUB-B"}
        )
    )

    run = validate_success(api.get_transport_run(scenario["run"]["id"], DISPATCH))
    assert run["status"] == "ABORTED"
    assert run["aborted_at"] is not None

    commitment = validate_success(
        api.get_partner_commitment(scenario["commitment"]["id"], DISPATCH)
    )
    assert commitment["slots_drawn"] == 0
    assert commitment["slots_open"] == 2
    assert commitment["status"] == "OPEN"
    assert_partner_slots_conserved(commitment)

    partner = validate_success(api.get_organization(scenario["partner"]["id"], ADMIN))
    assert partner["open_commitment_slots_total"] == 2

    assert validate_success(api.get_transport_leg(scenario["leg1"]["id"], DISPATCH))[
        "status"
    ] == "ARRIVED"


# --------------------------------------------------------------------------
# A departure that depends on another entity's certificate state
# --------------------------------------------------------------------------
def _relay_waiting_on_certificates(api):
    """A cat and a dog certified for WA on 2026-05-01; the relay's second leg crosses
    into WA on 2026-05-20T08:00:00Z, by which time the cat's 15-day certificate has
    passed its expiry while the dog's 30-day one has not."""
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    cat = new_animal(api, org["id"], name="Pixel", species="CAT", size_class="SMALL",
                     weight_lb=9.0, date_of_birth="2024-01-01T00:00:00Z")
    dog = new_animal(api, org["id"], name="Rex", weight_lb=45.0,
                     date_of_birth="2024-01-01T00:00:00Z")
    take_into_custody(api, cat["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    take_into_custody(api, dog["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    vaccinate_rabies(api, cat["id"], "2026-05-01T00:00:00Z")
    vaccinate_rabies(api, dog["id"], "2026-05-01T00:00:00Z")
    cat_cvi = issue_certificate(api, cat["id"], "2026-05-01T00:00:00Z", "WA")
    dog_cvi = issue_certificate(api, dog["id"], "2026-05-01T00:00:00Z", "WA")

    relay = setup_relay_run(
        api, org["id"], driver=driver,
        leg1_overrides={"scheduled_depart_at": "2026-05-02T08:00:00Z",
                        "scheduled_arrive_at": "2026-05-02T12:00:00Z",
                        "crate_capacity_units": 10, "weight_capacity_lb": 500.0,
                        "species_policy": "MIXED_SEGREGATED"},
        leg2_overrides={"scheduled_depart_at": "2026-05-20T08:00:00Z",
                        "scheduled_arrive_at": "2026-05-20T18:00:00Z",
                        "crate_capacity_units": 10, "weight_capacity_lb": 500.0,
                        "crosses_state_line": True, "destination_state_code": "WA",
                        "species_policy": "MIXED_SEGREGATED"},
    )
    manifest_animal(api, relay["leg1"]["id"], cat["id"])
    manifest_animal(api, relay["leg1"]["id"], dog["id"])
    manifest_animal(api, relay["leg2"]["id"], cat["id"])
    manifest_animal(api, relay["leg2"]["id"], dog["id"])

    start_run(api, relay["run"]["id"])
    set_clock(api, "2026-05-02T08:00:00Z")
    depart_leg(api, relay["leg1"]["id"], make_driver_headers(driver["id"]))
    set_clock(api, "2026-05-02T12:00:00Z")
    arrive_leg(api, relay["leg1"]["id"], make_driver_headers(driver["id"]))
    set_clock(api, "2026-05-20T08:00:00Z")

    return {
        "org": org, "driver": driver, "cat": cat, "dog": dog,
        "cat_cvi": cat_cvi, "dog_cvi": dog_cvi,
        "run": relay["run"], "leg1": relay["leg1"], "leg2": relay["leg2"],
    }


def test_one_expired_certificate_blocks_the_whole_interstate_departure(api):
    """PRD 3.5: "The validity window is selected by the animal's species and nothing
    else: a `DOG` gets 30 days, a `CAT` gets 15, and an `OTHER` gets 10. The selected
    figure is stored as `window_days` and `expires_at` is `issued_at` advanced by that
    many 24-hour periods. A certificate starts in `status` `VALID`."
    PRD 3.6: "**Certificate validity** then requires that animal's governing
    certificate — greatest `issued_at`, tie-broken by greatest `created_at`, among
    those matching the destination state — to have an `expires_at` at or after the
    leg's `scheduled_depart_at`. The comparison is against the leg's *scheduled*
    departure instant, not against the clock at the moment of the call. A failure is
    `ERR_CVI_EXPIRED`."
    PRD 3.5: "Expiry is evaluated with a strict comparison — the certificate is still
    valid at an instant exactly equal to `expires_at` — and the transition `VALID →
    EXPIRED` is one-way."

    The cat's 15-day certificate expires 2026-05-16, before the leg's scheduled
    departure of 2026-05-20; the dog's 30-day certificate runs to 2026-05-31.

    Design: Difficulty/cross_entity_state_dependency/leg_departure_depends_on_health_certificate_state
    """
    scenario = _relay_waiting_on_certificates(api)
    assert scenario["cat_cvi"]["window_days"] == 15
    assert scenario["dog_cvi"]["window_days"] == 30
    assert_same_instant(
        scenario["cat_cvi"]["expires_at"], "2026-05-16T00:00:00Z", "expires_at"
    )

    validate_error(
        api.depart_transport_leg(
            scenario["leg2"]["id"], make_driver_headers(scenario["driver"]["id"])
        ),
        ApiErrorId.ERR_CVI_EXPIRED.value,
        409,
    )

    # The departure check has observed the cat's certificate past its expiry instant.
    assert validate_success(api.get_health_certificate(scenario["cat_cvi"]["id"], ADMIN))[
        "status"
    ] == "EXPIRED"
    assert validate_success(api.get_health_certificate(scenario["dog_cvi"]["id"], ADMIN))[
        "status"
    ] == "VALID"
    assert validate_success(api.get_transport_leg(scenario["leg1"]["id"], DISPATCH))[
        "status"
    ] == "ARRIVED"
    assert validate_success(api.get_transport_leg(scenario["leg2"]["id"], DISPATCH))[
        "status"
    ] == "SCHEDULED"


def test_a_freshly_issued_certificate_governs_and_unblocks_the_departure(api):
    """PRD 3.5: "Where an animal holds several certificates for the same destination
    state, exactly one **governs**: the row with the greatest `issued_at`, tie-broken
    by the greatest `created_at`. An older, already-expired certificate for the same
    animal and state does not block a departure once a newer one governs."
    PRD 3.5: "An expired certificate can no longer authorise an interstate departure,
    and the remedy is to issue a fresh one rather than to amend the old."
    PRD 3.6: "**Departing** a leg moves it `SCHEDULED → DEPARTED` and is the single
    most heavily guarded action in the system."

    A replacement CAT certificate issued 2026-05-20 carries the same 15-day window and
    therefore expires 2026-06-04, comfortably after the leg's scheduled departure.

    Design: Difficulty/cross_entity_state_dependency/leg_departure_depends_on_health_certificate_state
    """
    scenario = _relay_waiting_on_certificates(api)

    validate_error(
        api.depart_transport_leg(
            scenario["leg2"]["id"], make_driver_headers(scenario["driver"]["id"])
        ),
        ApiErrorId.ERR_CVI_EXPIRED.value,
        409,
    )

    replacement = issue_certificate(api, scenario["cat"]["id"], "2026-05-20T00:00:00Z", "WA")
    assert replacement["window_days"] == 15
    assert_same_instant(replacement["expires_at"], "2026-06-04T00:00:00Z", "expires_at")

    departed = validate_success(
        api.depart_transport_leg(
            scenario["leg2"]["id"], make_driver_headers(scenario["driver"]["id"])
        )
    )
    assert departed["status"] == "DEPARTED"
    assert_same_instant(departed["departed_at"], "2026-05-20T08:00:00Z", "departed_at")


# --------------------------------------------------------------------------
# Corner coverage on interstate departures and driver ownership
# --------------------------------------------------------------------------
def test_rabies_age_is_checked_above_certificate_presence(api):
    """PRD 3.6: "**Rabies eligibility**, tested only when `crosses_state_line` is true,
    requires the animal's `rabies_vaccinated_at` to be non-null and requires the animal
    to have been at least 12 weeks old at the moment of that vaccination."
    PRD 3.6: "A failure on either count — never vaccinated, or vaccinated too young —
    is `ERR_RABIES_AGE_NOT_MET`. Note that this check sits **above** both certificate
    checks on the ladder, so an animal that is both unvaccinated and uncertified
    reports the rabies failure."
    PRD 3.6: "**Certificate presence** then requires each manifested animal to hold at
    least one health certificate whose `destination_state` equals the leg's
    `destination_state_code`; if none exists the answer is `ERR_CVI_REQUIRED`."

    A puppy born 2026-04-01 and vaccinated 2026-05-01 was 30 // 7 == 4 weeks old at
    vaccination, below the inclusive 12-week boundary, even though it holds a valid WA
    certificate; the adult dog clears rabies but holds no certificate at all.

    Design: Corner/validations/interstate_departure_requires_rabies_age_and_certificate
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver_one = new_driver(api, "Milo Frey", "milo@example.test", "CDL-8891")
    driver_two = new_driver(api, "Nora Vale", "nora@example.test", "CDL-2210")
    puppy = new_animal(api, org["id"], name="Puppy", size_class="SMALL", weight_lb=8.0,
                       date_of_birth="2026-04-01T00:00:00Z")
    adult = new_animal(api, org["id"], name="Adult", weight_lb=40.0,
                       date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, puppy["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    take_into_custody(api, adult["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    vaccinate_rabies(api, puppy["id"], "2026-05-01T00:00:00Z")
    vaccinate_rabies(api, adult["id"], "2026-05-01T00:00:00Z")
    puppy_cvi = issue_certificate(api, puppy["id"], "2026-05-01T00:00:00Z", "WA")

    interstate_leg = {
        "crate_capacity_units": 10, "weight_capacity_lb": 400.0,
        "crosses_state_line": True, "destination_state_code": "WA",
        "species_policy": "DOGS_ONLY",
    }
    puppy_run = setup_run_with_leg(
        api, org["id"], driver=driver_one, leg_overrides=dict(interstate_leg)
    )
    manifest_animal(api, puppy_run["leg"]["id"], puppy["id"])
    start_run(api, puppy_run["run"]["id"])

    adult_run = setup_run_with_leg(
        api, org["id"], driver=driver_two, leg_overrides=dict(interstate_leg)
    )
    manifest_animal(api, adult_run["leg"]["id"], adult["id"])
    start_run(api, adult_run["run"]["id"])

    set_clock(api, "2026-05-05T08:00:00Z")
    validate_error(
        api.depart_transport_leg(
            puppy_run["leg"]["id"], make_driver_headers(driver_one["id"])
        ),
        ApiErrorId.ERR_RABIES_AGE_NOT_MET.value,
        422,
    )
    validate_error(
        api.depart_transport_leg(
            adult_run["leg"]["id"], make_driver_headers(driver_two["id"])
        ),
        ApiErrorId.ERR_CVI_REQUIRED.value,
        422,
    )

    assert validate_success(api.get_transport_leg(puppy_run["leg"]["id"], DISPATCH))[
        "status"
    ] == "SCHEDULED"
    assert validate_success(api.get_transport_leg(adult_run["leg"]["id"], DISPATCH))[
        "status"
    ] == "SCHEDULED"
    assert validate_success(api.get_health_certificate(puppy_cvi["id"], ADMIN))[
        "status"
    ] == "VALID"


def test_a_driver_may_only_act_on_their_own_leg(api):
    """PRD 2.1: "Ownership is then enforced by comparing `X-User-ID` to the foreign key
    on the resource being touched: a `Driver` may act only on a `TransportLeg` whose
    `driver_person_id` equals `X-User-ID`; a `FosterParent` may act only on a
    `FosterApplication` whose `person_id` equals `X-User-ID` and on a `FosterHome`
    whose `person_id` equals `X-User-ID`, together with the placements belonging to
    that home; an `Adopter` may act only on an `AdoptionApplication` whose
    `applicant_person_id` equals `X-User-ID` and on an `Adoption` whose
    `adopter_person_id` equals `X-User-ID`; and a `PartnerRescue` may read only a
    `PartnerCommitment` whose `organization_id` equals `X-User-ID`, together with the
    runs drawing on it and its own organization record. An entity-backed actor reaching
    for someone else's record is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 3.6: "On success, departure stamps `departed_at` with the current clock
    instant, moves every `ASSIGNED` entry on the leg to `LOADED`, and moves each
    carried animal to `IN_TRANSIT` — from `IN_CUSTODY` on a first departure, or from
    `STRANDED` when this is a replacement leg picking up an animal left behind."

    Design: Corner/rbac/driver_cannot_depart_another_drivers_leg
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver_a = new_driver(api, "Driver A", "da@example.test", "CDL-1")
    driver_b = new_driver(api, "Driver B", "db@example.test", "CDL-2")
    run = new_run(api, org["id"])
    leg = add_leg(api, run["id"], driver_a["id"], crate_capacity_units=6,
                  weight_capacity_lb=400.0)
    start_run(api, run["id"])
    set_clock(api, "2026-05-05T08:00:00Z")

    validate_error(
        api.depart_transport_leg(leg["id"], make_driver_headers(driver_b["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    departed = validate_success(
        api.depart_transport_leg(leg["id"], make_driver_headers(driver_a["id"]))
    )
    assert departed["status"] == "DEPARTED"
    assert_same_instant(departed["departed_at"], "2026-05-05T08:00:00Z", "departed_at")
