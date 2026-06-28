"""Validation precedence between competing guards, technician half-open
double-booking, quarantine closed-interval occupancy, the strict bioload
overstock boundary, and the quarantine-abort livestock-count invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_field_tech_headers,
    create_active_contract_with_system,
    setup_active_system_with_tech,
    create_active_quarantine,
    setup_home_and_qt_with_livestock,
    TEST_USERS,
)
from test_helpers.fixtures import create_technician
from test_helpers import factories as f

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_double_book_error_beats_stale_version_error(api):
    """PRD §3.12: "the technician double-booking guard on booking a visit and
    dispatching an emergency (ERR_TECH_DOUBLE_BOOKED), ... the
    optimistic-concurrency check on booking visits and opening quarantines
    (ERR_STALE_VERSION), and finally generic request validation".

    A single booking that both overlaps an existing visit window for the tech AND
    carries a stale expected_system_version returns the earlier-listed
    ERR_TECH_DOUBLE_BOOKED, not ERR_STALE_VERSION.

    Design: Difficulty/priority_pair_validation_conflict/visit_book_double_book_beats_stale_version
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    system_id = base["system"]["id"]
    tech_id = base["technician"]["id"]
    stale_v = base["system"]["version"]

    # First booking [09:00,10:00) consumes the version (system.version advances).
    validate_success(api.create_visit(
        f.create_visit_payload(system_id, tech_id, stale_v,
                               scheduled_start="2026-02-08T09:00:00Z",
                               scheduled_end="2026-02-08T10:00:00Z"),
        DISP), expected_status=201)

    # Second booking overlaps [09:30,10:30) AND reuses the now-stale version.
    resp = api.create_visit(
        f.create_visit_payload(system_id, tech_id, stale_v,
                               scheduled_start="2026-02-08T09:30:00Z",
                               scheduled_end="2026-02-08T10:30:00Z"),
        DISP)
    validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_BOOKED)


def test_stale_version_alone_surfaces_when_no_overlap(api):
    """PRD §2.7: "If that value does not equal the system's current version ...
    the create is rejected with ERR_STALE_VERSION and HTTP status 412".

    Control for the precedence pair: a stale booking that does NOT collide with
    any existing visit window surfaces ERR_STALE_VERSION on its own — proving the
    OCC guard is real and only suppressed by the higher-priority overlap check
    when both conditions hold.

    Design: Difficulty/priority_pair_validation_conflict/visit_book_double_book_beats_stale_version
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    system_id = base["system"]["id"]
    tech_id = base["technician"]["id"]
    stale_v = base["system"]["version"]

    # First booking advances the system version, making stale_v one behind.
    validate_success(api.create_visit(
        f.create_visit_payload(system_id, tech_id, stale_v,
                               scheduled_start="2026-02-08T13:00:00Z",
                               scheduled_end="2026-02-08T14:00:00Z"),
        DISP), expected_status=201)
    # Non-overlapping window [15:00,16:00) but still carrying the stale version.
    resp = api.create_visit(
        f.create_visit_payload(system_id, tech_id, stale_v,
                               scheduled_start="2026-02-08T15:00:00Z",
                               scheduled_end="2026-02-08T16:00:00Z"),
        DISP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_tech_mismatch_error_beats_reef_cert_error(api):
    """PRD §3.12: "the tech-identity match on visit start and rework
    (ERR_TECH_MISMATCH), the reef-certification gate on visit start and emergency
    dispatch (ERR_TECH_NOT_CERTIFIED)".

    On a REEF system, a tech who is neither the assigned tech nor reef-certified
    is rejected with the earlier-listed ERR_TECH_MISMATCH.

    Design: Difficulty/priority_pair_validation_conflict/visit_start_tech_mismatch_beats_reef_cert
    """
    # tech-1 is assigned + reef-certified; tech-2 is neither assigned nor certified.
    tech1 = create_technician(tech_user_id="tech-1", full_name="Tia", certified_for_reef=True)
    create_technician(tech_user_id="tech-2", full_name="Tom", certified_for_reef=False)
    base = create_active_contract_with_system(service_tier="PREMIUM",
                                              customer_user_id="owner-1",
                                              system_kind="REEF", nominal_volume_l=300)
    system_id = base["system"]["id"]

    visit = validate_success(api.create_visit(
        f.create_visit_payload(system_id, tech1["id"], base["system"]["version"],
                               scheduled_start="2026-02-09T09:00:00Z",
                               scheduled_end="2026-02-09T10:00:00Z"),
        DISP), expected_status=201)

    # tech-2 (wrong tech, not reef-certified) tries to start -> mismatch wins.
    resp = api.start_visit(visit["id"], make_field_tech_headers("tech-2"))
    validate_error(resp, ApiErrorId.ERR_TECH_MISMATCH)


def test_reef_cert_alone_surfaces_when_tech_is_assigned(api):
    """PRD §3.3: "When the target system's system_kind is REEF, the assigned
    Technician must have certified_for_reef set to true; an uncertified tech is
    rejected with ERR_TECH_NOT_CERTIFIED."

    Control for the precedence pair: when the acting tech IS the assigned tech
    (so no mismatch) but is NOT reef-certified, the reef-cert guard fires on its
    own with ERR_TECH_NOT_CERTIFIED — proving it is only suppressed by the
    higher-priority mismatch when both conditions hold.

    Design: Difficulty/priority_pair_validation_conflict/visit_start_tech_mismatch_beats_reef_cert
    """
    tech = create_technician(tech_user_id="tech-1", full_name="Tia", certified_for_reef=False)
    base = create_active_contract_with_system(service_tier="PREMIUM",
                                              customer_user_id="owner-1",
                                              system_kind="REEF", nominal_volume_l=300)
    system_id = base["system"]["id"]
    visit = validate_success(api.create_visit(
        f.create_visit_payload(system_id, tech["id"], base["system"]["version"],
                               scheduled_start="2026-02-09T11:00:00Z",
                               scheduled_end="2026-02-09T12:00:00Z"),
        DISP), expected_status=201)
    # Assigned tech-1 starts (no mismatch) but is uncertified for REEF.
    resp = api.start_visit(visit["id"], make_field_tech_headers("tech-1"))
    validate_error(resp, ApiErrorId.ERR_TECH_NOT_CERTIFIED)


def test_visit_tech_double_book_half_open_adjacency_allowed(api):
    """PRD §3.3: "Because the intervals are half-open, two visits that merely
    touch at an endpoint (one ending exactly when the next begins) do not
    conflict; a genuine overlap is rejected with ERR_TECH_DOUBLE_BOOKED."

    Booking [10:00,11:00) right after [09:00,10:00) is allowed (touching);
    booking [09:30,10:30) overlapping the interior is rejected.

    Design: Difficulty/resource_temporal_overlap/visit_tech_double_book_half_open_no_adjacency
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    system_id = base["system"]["id"]
    tech_id = base["technician"]["id"]

    v1 = validate_success(api.get_system(system_id, AM))
    validate_success(api.create_visit(
        f.create_visit_payload(system_id, tech_id, v1["version"],
                               scheduled_start="2026-02-13T09:00:00Z",
                               scheduled_end="2026-02-13T10:00:00Z"),
        DISP), expected_status=201)

    v2 = validate_success(api.get_system(system_id, AM))
    # Adjacent [10:00,11:00) — half-open touch is NOT a conflict, must create.
    validate_success(api.create_visit(
        f.create_visit_payload(system_id, tech_id, v2["version"],
                               scheduled_start="2026-02-13T10:00:00Z",
                               scheduled_end="2026-02-13T11:00:00Z"),
        DISP), expected_status=201)

    v3 = validate_success(api.get_system(system_id, AM))
    # Overlapping interior [09:30,10:30) — rejected.
    resp = api.create_visit(
        f.create_visit_payload(system_id, tech_id, v3["version"],
                               scheduled_start="2026-02-13T09:30:00Z",
                               scheduled_end="2026-02-13T10:30:00Z"),
        DISP)
    validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_BOOKED)


def test_visit_tech_overlap_rejected_when_new_window_contains_existing(api):
    """PRD §3.3: "the half-open window must not overlap any other non-terminal
    visit — one that is SCHEDULED or IN_PROGRESS — already held by the same
    technician. Because the intervals are half-open ... a genuine overlap is
    rejected with ERR_TECH_DOUBLE_BOOKED."

    A new window [08:30,10:30) that fully contains an existing [09:00,10:00)
    genuinely overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/visit_tech_double_book_half_open_no_adjacency
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    system_id = base["system"]["id"]
    tech_id = base["technician"]["id"]

    v1 = validate_success(api.get_system(system_id, AM))
    validate_success(api.create_visit(
        f.create_visit_payload(system_id, tech_id, v1["version"],
                               scheduled_start="2026-02-14T09:00:00Z",
                               scheduled_end="2026-02-14T10:00:00Z"),
        DISP), expected_status=201)
    v2 = validate_success(api.get_system(system_id, AM))
    resp = api.create_visit(
        f.create_visit_payload(system_id, tech_id, v2["version"],
                               scheduled_start="2026-02-14T08:30:00Z",
                               scheduled_end="2026-02-14T10:30:00Z"),
        DISP)
    validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_BOOKED)


def test_quarantine_tank_shared_endpoint_is_a_conflict(api):
    """PRD §3.6: "since the intervals are closed, sharing a single endpoint — one
    window ending exactly when another begins — counts as a conflict; a collision
    is rejected with ERR_QT_TANK_OCCUPIED."

    An ACTIVE quarantine on [03-01,03-03] then a second on [03-03,03-05] shares
    the 03-03 endpoint and is rejected.

    Design: Difficulty/resource_temporal_overlap/quarantine_tank_closed_interval_adjacency_conflicts
    """
    base = setup_home_and_qt_with_livestock(customer_user_id="owner-1",
                                            tech_user_id="tech-1",
                                            home_volume_l=300, qt_volume_l=80,
                                            num_fish=2, species_class="COMMUNITY",
                                            adult_length_cm=3)
    tech_headers = make_field_tech_headers("tech-1")
    qt_id = base["qt"]["id"]
    qt_v = base["qt"]["version"]

    validate_success(api.create_quarantine(
        f.create_quarantine_payload(base["livestock"][0]["id"], qt_id, qt_v,
                                    window_start="2026-03-01T00:00:00Z",
                                    window_end="2026-03-03T00:00:00Z"),
        tech_headers), expected_status=201)

    qt_after = validate_success(api.get_system(qt_id, tech_headers))
    resp = api.create_quarantine(
        f.create_quarantine_payload(base["livestock"][1]["id"], qt_id, qt_after["version"],
                                    window_start="2026-03-03T00:00:00Z",
                                    window_end="2026-03-05T00:00:00Z"),
        tech_headers)
    validate_error(resp, ApiErrorId.ERR_QT_TANK_OCCUPIED)


def test_quarantine_tank_interior_overlap_is_a_conflict(api):
    """PRD §3.6: "two ACTIVE quarantines on the same quarantine_tank_id may not
    overlap, and since the intervals are closed, sharing a single endpoint ...
    counts as a conflict; a collision is rejected with ERR_QT_TANK_OCCUPIED."

    A second quarantine [03-02,03-04] overlapping the interior of an existing
    [03-01,03-03] is rejected.

    Design: Difficulty/resource_temporal_overlap/quarantine_tank_closed_interval_adjacency_conflicts
    """
    base = setup_home_and_qt_with_livestock(customer_user_id="owner-1",
                                            tech_user_id="tech-1",
                                            home_volume_l=300, qt_volume_l=80,
                                            num_fish=2, species_class="COMMUNITY",
                                            adult_length_cm=3)
    tech_headers = make_field_tech_headers("tech-1")
    qt_id = base["qt"]["id"]

    validate_success(api.create_quarantine(
        f.create_quarantine_payload(base["livestock"][0]["id"], qt_id, base["qt"]["version"],
                                    window_start="2026-03-01T00:00:00Z",
                                    window_end="2026-03-03T00:00:00Z"),
        tech_headers), expected_status=201)
    qt_after = validate_success(api.get_system(qt_id, tech_headers))
    resp = api.create_quarantine(
        f.create_quarantine_payload(base["livestock"][1]["id"], qt_id, qt_after["version"],
                                    window_start="2026-03-02T00:00:00Z",
                                    window_end="2026-03-04T00:00:00Z"),
        tech_headers)
    validate_error(resp, ApiErrorId.ERR_QT_TANK_OCCUPIED)


def test_bioload_exactly_100_normal_then_overstock_rejected(api):
    """PRD §2.9: "The stocking_posture is OVERSTOCKED when bioload_index is
    strictly greater than 100.0 and NORMAL otherwise; a value of exactly 100.0 is
    NORMAL."
    PRD §3.2: "if the resulting bioload_index would land strictly above 100.0 —
    making the system OVERSTOCKED — the addition is rejected with ERR_OVERSTOCKED
    and HTTP status 422."

    100 L / 0 displacement, two PREDATOR (30cm + 10cm) -> (75+25)/100*100 = 100.0
    NORMAL; a third PREDATOR 4cm would push to 110.0 -> rejected.

    Design: Difficulty/boundary_precision_check/bioload_overstock_strict_greater_than_100
    """
    base = create_active_contract_with_system(service_tier="BASIC",
                                              customer_user_id="owner-1",
                                              nominal_volume_l=100,
                                              substrate_displacement_pct=0.0)
    system_id = base["system"]["id"]

    validate_success(api.create_livestock(
        f.create_livestock_payload(system_id, common_name="Oscar",
                                   species_class="PREDATOR", adult_length_cm=30),
        AM), expected_status=201)
    validate_success(api.create_livestock(
        f.create_livestock_payload(system_id, common_name="Jack",
                                   species_class="PREDATOR", adult_length_cm=10),
        AM), expected_status=201)

    system = validate_success(api.get_system(system_id, AM))
    assert system["bioload_index"] == 100.0, (
        f"Expected bioload exactly 100.0, got {system['bioload_index']}")
    assert system["stocking_posture"] == "NORMAL", (
        f"Expected NORMAL at 100.0, got {system['stocking_posture']}")

    resp = api.create_livestock(
        f.create_livestock_payload(system_id, common_name="Fry",
                                   species_class="PREDATOR", adult_length_cm=4),
        AM)
    validate_error(resp, ApiErrorId.ERR_OVERSTOCKED)


def test_bioload_addition_landing_exactly_at_100_is_accepted(api):
    """PRD §2.9: "The stocking_posture is OVERSTOCKED when bioload_index is
    strictly greater than 100.0 and NORMAL otherwise; a value of exactly 100.0 is
    NORMAL."

    The X boundary (X = 100.0): the addition that lands the system at exactly
    100.0 succeeds and the system reports NORMAL — the strict threshold admits
    the endpoint.

    Design: Difficulty/boundary_precision_check/bioload_overstock_strict_greater_than_100
    """
    base = create_active_contract_with_system(service_tier="BASIC",
                                              customer_user_id="owner-1",
                                              nominal_volume_l=100,
                                              substrate_displacement_pct=0.0)
    system_id = base["system"]["id"]

    validate_success(api.create_livestock(
        f.create_livestock_payload(system_id, common_name="Oscar",
                                   species_class="PREDATOR", adult_length_cm=30),
        AM), expected_status=201)
    # Second PREDATOR 10cm lands the system at exactly (75+25)/100*100 = 100.0.
    second = validate_success(api.create_livestock(
        f.create_livestock_payload(system_id, common_name="Jack",
                                   species_class="PREDATOR", adult_length_cm=10),
        AM), expected_status=201)
    assert second["status"] == "ALIVE"
    system = validate_success(api.get_system(system_id, AM))
    assert system["bioload_index"] == 100.0, (
        f"Expected exactly 100.0, got {system['bioload_index']}")
    assert system["stocking_posture"] == "NORMAL", (
        f"Expected NORMAL at exactly 100.0, got {system['stocking_posture']}")


def test_quarantine_abort_preserves_alive_livestock_count(api):
    """PRD §3.6: "Opening a quarantine moves the linked Livestock to QUARANTINED,
    which recomputes the home system's bioload and the contract's
    alive_livestock_count."
    PRD §3.6: "A FieldTech may instead abort a quarantine, moving it
    ACTIVE → ABORTED, which sets the linked Livestock to DECEASED; the contract's
    alive_livestock_count is unchanged here, because a QUARANTINED animal was
    already excluded from the count."

    Two ALIVE fish -> count 2; quarantining one drops it to 1; aborting that
    quarantine leaves the count at 1 (no double-decrement).

    Design: Difficulty/compensating_invariant/quarantine_abort_preserves_alive_livestock_count
    """
    base = create_active_quarantine(customer_user_id="owner-1", tech_user_id="tech-1")
    contract_id = base["contract"]["id"]
    tech_headers = make_field_tech_headers("tech-1")

    during = validate_success(api.get_contract(contract_id, AM))
    assert during["alive_livestock_count"] == 1, (
        f"Expected count 1 while one is quarantined, got {during['alive_livestock_count']}")

    validate_success(api.abort_quarantine(base["quarantine"]["id"], tech_headers))

    after = validate_success(api.get_contract(contract_id, AM))
    assert after["alive_livestock_count"] == 1, (
        f"Expected count unchanged at 1 after abort, got {after['alive_livestock_count']}")

    animal = validate_success(api.get_livestock(base["livestock"][0]["id"], tech_headers))
    assert animal["status"] == "DECEASED", (
        f"Expected aborted animal DECEASED, got {animal['status']}")


def test_quarantine_abort_sets_animal_deceased(api):
    """PRD §3.6: "A FieldTech may instead abort a quarantine, moving it
    ACTIVE → ABORTED, which sets the linked Livestock to DECEASED".

    The abort's direct cross-entity effect: the quarantine becomes ABORTED and
    the linked animal becomes DECEASED.

    Design: Difficulty/compensating_invariant/quarantine_abort_preserves_alive_livestock_count
    """
    base = create_active_quarantine(customer_user_id="owner-1", tech_user_id="tech-1")
    tech_headers = make_field_tech_headers("tech-1")

    aborted = validate_success(api.abort_quarantine(base["quarantine"]["id"], tech_headers))
    assert aborted["status"] == "ABORTED", (
        f"Expected quarantine ABORTED, got {aborted['status']}")
    animal = validate_success(api.get_livestock(base["livestock"][0]["id"], tech_headers))
    assert animal["status"] == "DECEASED", (
        f"Expected linked animal DECEASED, got {animal['status']}")
