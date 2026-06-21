"""Admission gates, occupancy/capacity, OCC, exit & ejection cascades.

Difficulty (A): boundary_precision (capacity), resource_temporal_overlap (re-entry),
priority_pair (id-check beats capacity), transitive_cascade (ejection depth-3).
Corner (B): cross-entity validation, OCC happy/sad, exit-reverts-posture, redeem link,
immediate consistency.
"""
from test_helpers import validate_success, validate_error
from test_helpers import fixtures as fx

ADMIN = fx.ADMIN
DOOR = fx.DOOR
SECURITY = fx.SECURITY


# ── Capacity boundary (cap, cap+1) ───────────────────────────────────────────

def test_admit_at_exact_capacity_blocks_next(api):
    """PRD §3.4: "The capacity gate refuses admission when the room is full: if
    `occupancy_count` already equals `fire_code_capacity` at admit time, admitting
    would push the count past the legal limit and the request is rejected with
    `ERR_AT_CAPACITY`."
    PRD §2.6: "The room moves to `AT_CAPACITY` when, immediately after an admission,
    the count of patrons inside has reached the fire-code limit ...."

    Design: Difficulty/boundary_precision_check/occupancy_at_exact_capacity_blocks_next_admit
    """
    venue = fx.create_venue(name="V", fire_code_capacity=2)
    version = venue["version"]
    _, version = fx.admit_patron(venue["id"], version, patron_name="A")
    _, version = fx.admit_patron(venue["id"], version, patron_name="B")
    idc_c = fx.create_pass_id_check(venue["id"], patron_name="C")
    res = api.create_entry(
        {"venue_id": venue["id"], "id_check_id": idc_c["id"],
         "expected_venue_version": version},
        DOOR,
    )
    validate_error(res, "ERR_AT_CAPACITY", expected_status=409)
    venue_after = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_after["occupancy_count"] == 2
    assert venue_after["posture"] == "AT_CAPACITY"


def test_admit_below_capacity_succeeds_and_flips_posture(api):
    """PRD §2.6: "The room moves to `AT_CAPACITY` when, immediately after an
    admission, the count of patrons inside has reached the fire-code limit and the
    clock has not yet entered the last-call window ...."

    Design: Difficulty/boundary_precision_check/occupancy_at_exact_capacity_blocks_next_admit
    """
    venue = fx.create_venue(name="V", fire_code_capacity=2)
    version = venue["version"]
    _, version = fx.admit_patron(venue["id"], version, patron_name="A")
    venue_mid = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_mid["occupancy_count"] == 1
    assert venue_mid["posture"] == "OPEN"
    _, version = fx.admit_patron(venue["id"], version, patron_name="B")
    venue_full = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_full["occupancy_count"] == 2
    assert venue_full["posture"] == "AT_CAPACITY"


# ── Patron re-entry: unbounded live interval ─────────────────────────────────

def test_patron_reentry_while_inside_rejected(api):
    """PRD §3.4: "the ID check named by `id_check_id` must not already back another
    entry whose status is `INSIDE` — a patron currently on the floor has an open,
    unexited occupancy interval and cannot be admitted a second time, so the
    attempt is rejected with `ERR_PATRON_ALREADY_INSIDE`."

    Design: Difficulty/resource_temporal_overlap/patron_reentry_unbounded_active_interval_rejected
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10)
    idc = fx.create_pass_id_check(venue["id"], patron_name="A")
    e1 = validate_success(
        api.create_entry({"venue_id": venue["id"], "id_check_id": idc["id"],
                          "expected_venue_version": venue["version"]}, DOOR),
        201,
    )
    assert e1["status"] == "INSIDE"
    venue_after = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    res = api.create_entry(
        {"venue_id": venue["id"], "id_check_id": idc["id"],
         "expected_venue_version": venue_after["version"]},
        DOOR,
    )
    validate_error(res, "ERR_PATRON_ALREADY_INSIDE", expected_status=409)


def test_patron_reentry_allowed_after_exit(api):
    """PRD §3.4: "a patron currently on the floor has an open, unexited occupancy
    interval and cannot be admitted a second time, so the attempt is rejected with
    `ERR_PATRON_ALREADY_INSIDE`."
    PRD §3.5: "On exit the entry's `status` becomes `EXITED` ...."

    Design: Difficulty/resource_temporal_overlap/patron_reentry_unbounded_active_interval_rejected
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10)
    idc = fx.create_pass_id_check(venue["id"], patron_name="A")
    e1 = validate_success(
        api.create_entry({"venue_id": venue["id"], "id_check_id": idc["id"],
                          "expected_venue_version": venue["version"]}, DOOR),
        201,
    )
    validate_success(api.exit_entry(e1["id"], DOOR), 200)
    venue_after = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    e2 = validate_success(
        api.create_entry({"venue_id": venue["id"], "id_check_id": idc["id"],
                          "expected_venue_version": venue_after["version"]}, DOOR),
        201,
    )
    assert e2["status"] == "INSIDE"


# ── Priority conflict: id-check safety beats capacity ────────────────────────

def test_id_check_gate_beats_capacity_gate(api):
    """PRD §3.10: "the ID-check gate (`ERR_ID_CHECK_NOT_PASSED`), the last-call
    alcohol gate (`ERR_LAST_CALL_NO_ALCOHOL`), the over-service gate
    (`ERR_OVER_SERVICE_REFUSED`), the reservation-window gate
    (`ERR_RESERVATION_WINDOW`), the table double-book gate
    (`ERR_TABLE_DOUBLE_BOOKED`), the re-entry gate (`ERR_PATRON_ALREADY_INSIDE`),
    the capacity gate (`ERR_AT_CAPACITY`), the comp-budget gate
    (`ERR_COMP_BUDGET_EXCEEDED`), and the pre-authorization gate
    (`ERR_PREAUTH_INSUFFICIENT`) each fire in the context of the operation they
    guard ...."

    Design: Difficulty/priority_pair_validation_conflict/id_check_safety_beats_capacity_constraint
    """
    fx.set_clock("2026-03-15T20:00:00Z")
    venue = fx.create_venue(name="V", fire_code_capacity=1)
    version = venue["version"]
    # Fill the venue (occupancy == capacity).
    _, version = fx.admit_patron(venue["id"], version, patron_name="A")
    # A second patron whose id-check is REFUSED_UNDERAGE (dob 2005-03-16 -> age 20).
    idc_b = fx.create_id_check(venue["id"], patron_name="B",
                               date_of_birth="2005-03-16", id_expiry="2030-01-01")
    assert idc_b["outcome"] == "REFUSED_UNDERAGE"
    venue_now = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    res = api.create_entry(
        {"venue_id": venue["id"], "id_check_id": idc_b["id"],
         "expected_venue_version": venue_now["version"]},
        DOOR,
    )
    validate_error(res, "ERR_ID_CHECK_NOT_PASSED", expected_status=422)


def test_id_check_gate_returns_422_not_capacity_409(api):
    """PRD §3.10: "Finally the business-safety, temporal, capacity, and fiscal rules
    apply: the ID-check gate (`ERR_ID_CHECK_NOT_PASSED`) ..., the capacity gate
    (`ERR_AT_CAPACITY`) ... each fire in the context of the operation they guard
    ...."
    PRD §3.4: "The verification gate requires that the `id_check_id` reference an ID
    check whose `outcome` is `PASS`; an admission citing a refused or missing check
    is rejected with `ERR_ID_CHECK_NOT_PASSED`."

    Design: Difficulty/priority_pair_validation_conflict/id_check_safety_beats_capacity_constraint
    """
    fx.set_clock("2026-03-15T20:00:00Z")
    venue = fx.create_venue(name="V", fire_code_capacity=1)
    version = venue["version"]
    _, version = fx.admit_patron(venue["id"], version, patron_name="A")
    # Expired ID of an of-age patron -> outcome REFUSED_EXPIRED_ID (also non-PASS).
    idc_b = fx.create_id_check(venue["id"], patron_name="B",
                               date_of_birth="1990-01-01", id_expiry="2026-03-14")
    venue_now = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    res = api.create_entry(
        {"venue_id": venue["id"], "id_check_id": idc_b["id"],
         "expected_venue_version": venue_now["version"]},
        DOOR,
    )
    # Full venue (would be ERR_AT_CAPACITY 409) but the id-check gate (422) is reported.
    validate_error(res, "ERR_ID_CHECK_NOT_PASSED", expected_status=422)


# ── Cross-entity validation: admit with non-PASS id-check ────────────────────

def test_admit_with_non_pass_idcheck_rejected(api):
    """PRD §3.4: "The verification gate requires that the `id_check_id` reference an
    ID check whose `outcome` is `PASS`; an admission citing a refused or missing
    check is rejected with `ERR_ID_CHECK_NOT_PASSED`."

    Design: Corner/validations/admit_with_non_pass_idcheck_returns_id_check_not_passed
    """
    fx.set_clock("2026-03-15T20:00:00Z")
    venue = fx.create_venue(name="V", fire_code_capacity=10)
    idc = fx.create_id_check(venue["id"], patron_name="Young",
                             date_of_birth="2005-03-16", id_expiry="2030-01-01")
    res = api.create_entry(
        {"venue_id": venue["id"], "id_check_id": idc["id"],
         "expected_venue_version": venue["version"]},
        DOOR,
    )
    validate_error(res, "ERR_ID_CHECK_NOT_PASSED", expected_status=422)


# ── OCC: admit happy path bumps version; reused stale version rejected ────────

def test_occ_admit_correct_version_succeeds_stale_rejected(api):
    """PRD §2.9: "When a patron is admitted, the request body's
    `expected_venue_version` is compared against the venue's current `version`. ...
    if another admission, an exit, or a posture recomputation has advanced the
    venue's `version` since the client last read it ... the admission is rejected
    with `ERR_STALE_VENUE_VERSION` (HTTP 412) ...."
    PRD §3.4: "The admission then re-derives posture ... and increments the venue's
    `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_admit_correct_version_succeeds_and_bumps
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10)
    idc_a = fx.create_pass_id_check(venue["id"], patron_name="A")
    idc_b = fx.create_pass_id_check(venue["id"], patron_name="B")
    validate_success(
        api.create_entry({"venue_id": venue["id"], "id_check_id": idc_a["id"],
                          "expected_venue_version": venue["version"]}, DOOR),
        201,
    )
    venue_after = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_after["version"] == 2
    res = api.create_entry(
        {"venue_id": venue["id"], "id_check_id": idc_b["id"],
         "expected_venue_version": venue["version"]},  # stale (1)
        DOOR,
    )
    validate_error(res, "ERR_STALE_VENUE_VERSION", expected_status=412)


# ── Exit reverts AT_CAPACITY -> OPEN ─────────────────────────────────────────

def test_exit_reverts_at_capacity_to_open(api):
    """PRD §3.5: "the venue's `occupancy_count` is decremented, and posture is
    re-derived — reverting `AT_CAPACITY → OPEN` when the count falls below
    `fire_code_capacity` (provided the clock has not entered the last-call
    window)."

    Design: Corner/endpoints/occupancy_exit_reverts_at_capacity_to_open
    """
    venue = fx.create_venue(name="V", fire_code_capacity=1)
    entry, _ = fx.admit_patron(venue["id"], venue["version"], patron_name="A")
    venue_full = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_full["posture"] == "AT_CAPACITY"
    validate_success(api.exit_entry(entry["id"], DOOR), 200)
    venue_after = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_after["occupancy_count"] == 0
    assert venue_after["posture"] == "OPEN"


# ── Guest-list redeem on admission sets the link ─────────────────────────────

def test_guest_list_redeemed_on_admission_sets_link(api):
    """PRD §3.4: "When the admission redeems a guest-list entry, that entry's
    `status` moves to `REDEEMED` and its `redeemed_entry_id` is set to the new
    entry's identifier."

    Design: Corner/endpoints/guest_list_redeemed_on_admission_sets_link
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10)
    gle = fx.create_guest_list_entry(venue["id"], guest_name="G", party_size=1)
    idc = fx.create_pass_id_check(venue["id"], patron_name="G")
    entry = validate_success(
        api.create_entry({"venue_id": venue["id"], "id_check_id": idc["id"],
                          "guest_list_entry_id": gle["id"],
                          "expected_venue_version": venue["version"]}, DOOR),
        201,
    )
    gle_after = validate_success(api.get_guest_list_entry(gle["id"], DOOR), 200)
    assert gle_after["status"] == "REDEEMED"
    assert gle_after["redeemed_entry_id"] == entry["id"]


# ── Immediate consistency ────────────────────────────────────────────────────

def test_immediate_admit_reflects_occupancy(api):
    """PRD §3.4: "sets the entry's `status` to `INSIDE`, stamps `admitted_at_utc`
    from the logical clock, and increments the venue's `occupancy_count`."
    PRD §3.1: "The `occupancy_count` is recomputed as the number of that venue's
    entries whose status is `INSIDE` on every admit and every exit ...."

    Design: Corner/consistency_model/immediate_admit_reflects_occupancy_in_same_response
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10)
    idc = fx.create_pass_id_check(venue["id"], patron_name="A")
    validate_success(
        api.create_entry({"venue_id": venue["id"], "id_check_id": idc["id"],
                          "expected_venue_version": venue["version"]}, DOOR),
        201,
    )
    venue_after = validate_success(api.get_venue(venue["id"], DOOR), 200)
    assert venue_after["occupancy_count"] == 1


# ── Ejection cascade: incident -> EJECTED -> occupancy -> posture (depth 3) ──

def test_ejection_cascade_depth3(api):
    """PRD §3.5: "When a `SecurityOfficer` files an incident whose `action` is
    `EJECTION` naming a subject entry that is currently `INSIDE`, the system
    cascades that entry from `INSIDE → EJECTED`: it stamps `exited_at_utc`,
    decrements the venue's `occupancy_count`, and re-derives posture exactly as a
    normal exit would ...."

    Design: Difficulty/transitive_cascade/ejection_cascade_entry_occupancy_posture_depth3
    """
    venue = fx.create_venue(name="V", fire_code_capacity=1)
    entry, _ = fx.admit_patron(venue["id"], venue["version"], patron_name="A")
    venue_full = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_full["posture"] == "AT_CAPACITY"
    validate_success(
        api.create_incident(
            {"venue_id": venue["id"], "severity": "SERIOUS", "action": "EJECTION",
             "narrative": "fight", "subject_entry_id": entry["id"]},
            SECURITY),
        201,
    )
    entry_after = validate_success(api.get_entry(entry["id"], SECURITY), 200)
    assert entry_after["status"] == "EJECTED"
    venue_after = validate_success(api.get_venue(venue["id"], SECURITY), 200)
    assert venue_after["occupancy_count"] == 0
    assert venue_after["posture"] == "OPEN"


def test_ejection_stamps_exit_and_decrements_occupancy(api):
    """PRD §3.5: "the system cascades that entry from `INSIDE → EJECTED`: it stamps
    `exited_at_utc`, decrements the venue's `occupancy_count`, and re-derives
    posture exactly as a normal exit would ...."

    Design: Difficulty/transitive_cascade/ejection_cascade_entry_occupancy_posture_depth3
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10)
    entry, _ = fx.admit_patron(venue["id"], venue["version"], patron_name="A")
    assert entry["exited_at_utc"] is None
    validate_success(
        api.create_incident(
            {"venue_id": venue["id"], "severity": "CRITICAL", "action": "EJECTION",
             "narrative": "ejected", "subject_entry_id": entry["id"]},
            SECURITY),
        201,
    )
    entry_after = validate_success(api.get_entry(entry["id"], SECURITY), 200)
    assert entry_after["status"] == "EJECTED"
    assert entry_after["exited_at_utc"] is not None
    venue_after = validate_success(api.get_venue(venue["id"], SECURITY), 200)
    assert venue_after["occupancy_count"] == 0
