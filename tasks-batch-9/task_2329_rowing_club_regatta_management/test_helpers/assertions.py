"""Domain assertion helpers: entity shape checks and cross-field invariants.

Every persisted resource carries `id` and `created_at`. All of them except a
river-condition reading additionally carry `updated_at` and `version`; a reading
is an immutable observation, so it carries neither (PRD §2.4).
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_identity(entity, label):
    assert "id" in entity, f"{label} is missing 'id'"
    assert is_valid_uuid(entity["id"]), f"{label} id is not a UUID: {entity['id']!r}"
    assert "created_at" in entity, f"{label} is missing 'created_at'"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"{label} created_at is not ISO-8601: {entity['created_at']!r}"
    )


def _assert_mutable_common_fields(entity, label):
    """id, created_at, updated_at and version — the common set for every
    resource other than a river-condition reading."""
    _assert_identity(entity, label)
    assert "updated_at" in entity, f"{label} is missing 'updated_at'"
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"{label} updated_at is not ISO-8601: {entity['updated_at']!r}"
    )
    assert "version" in entity, f"{label} is missing 'version'"
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        f"{label} version must be a positive integer, got {entity['version']!r}"
    )


def _assert_fields_present(entity, fields, label):
    missing = [field for field in fields if field not in entity]
    assert not missing, f"{label} is missing fields {missing}"


def assert_member(member):
    _assert_mutable_common_fields(member, "Member")
    _assert_fields_present(
        member,
        [
            "full_name",
            "tier",
            "body_weight_kg",
            "club_roles",
            "swim_test_passed_on",
            "coxswain_cert_expires_at",
            "coach_cert_expires_at",
            "safety_launch_cert_expires_at",
            "launch_supervision_limit",
            "membership_status",
            "dues_balance_cents",
            "logged_session_count",
            "boathouse_access_level",
        ],
        "Member",
    )
    assert member["tier"] in ("COMPETITIVE", "RECREATIONAL", "LEARN_TO_ROW"), (
        f"Member tier out of range: {member['tier']!r}"
    )
    assert member["membership_status"] in (
        "ACTIVE",
        "DUES_HOLD",
        "SUSPENDED",
        "WITHDRAWN",
    ), f"Member membership_status out of range: {member['membership_status']!r}"
    assert member["boathouse_access_level"] in ("FULL", "SUPERVISED", "NONE"), (
        f"Member boathouse_access_level out of range: {member['boathouse_access_level']!r}"
    )
    assert isinstance(member["club_roles"], list), "Member club_roles must be a list"
    return member


def assert_dues_invoice(invoice):
    _assert_mutable_common_fields(invoice, "DuesInvoice")
    _assert_fields_present(
        invoice,
        [
            "member_id",
            "season_year",
            "billable_months",
            "locker_requested",
            "due_at",
            "status",
            "variant_basis",
            "assessed_cents",
            "paid_cents",
            "trueup_cents",
        ],
        "DuesInvoice",
    )
    assert invoice["status"] in (
        "ISSUED",
        "PARTIALLY_PAID",
        "DELINQUENT",
        "PAID",
        "VOIDED",
    ), f"DuesInvoice status out of range: {invoice['status']!r}"
    assert invoice["variant_basis"] in ("PROVISIONAL", "TRUEUP"), (
        f"DuesInvoice variant_basis out of range: {invoice['variant_basis']!r}"
    )
    return invoice


def assert_shell(shell):
    _assert_mutable_common_fields(shell, "Shell")
    _assert_fields_present(
        shell,
        [
            "hull_name",
            "boat_class",
            "hull_weight_kg",
            "home_bay",
            "tier_restriction",
            "last_serviced_at",
            "status",
            "slot_units",
            "condition_index_conservative",
            "condition_index_optimistic",
        ],
        "Shell",
    )
    assert shell["status"] in (
        "AVAILABLE",
        "ASSIGNED",
        "DAMAGED",
        "IN_REPAIR",
        "RETIRED",
    ), f"Shell status out of range: {shell['status']!r}"
    assert shell["boat_class"] in ("1X", "2X", "4+", "8+"), (
        f"Shell boat_class out of range: {shell['boat_class']!r}"
    )
    return shell


def assert_damage_report(report):
    _assert_mutable_common_fields(report, "DamageReport")
    _assert_fields_present(
        report,
        [
            "shell_id",
            "reported_by_member_id",
            "severity",
            "narrative",
            "reported_at",
            "status",
            "triaged_by_user_id",
            "verified_by_user_id",
            "assigned_repair_bay",
            "repair_window_start_at",
            "repair_window_end_at",
            "severity_points",
        ],
        "DamageReport",
    )
    assert report["severity"] in ("COSMETIC", "MINOR", "MAJOR", "STRUCTURAL"), (
        f"DamageReport severity out of range: {report['severity']!r}"
    )
    assert report["status"] in (
        "REPORTED",
        "TRIAGED",
        "REPAIR_SCHEDULED",
        "VERIFIED",
        "CONDEMNED",
        "CLOSED_NO_ACTION",
    ), f"DamageReport status out of range: {report['status']!r}"
    return report


def assert_water_condition_reading(reading):
    """A reading carries only id and created_at from the common set — it has
    neither updated_at nor version (PRD §2.4)."""
    _assert_identity(reading, "WaterConditionReading")
    _assert_fields_present(
        reading,
        [
            "observed_at",
            "air_temp_c",
            "water_temp_c",
            "wind_speed_kt",
            "visibility_m",
            "traffic_pattern",
            "cold_water_flag",
            "posture",
        ],
        "WaterConditionReading",
    )
    assert "updated_at" not in reading, (
        "WaterConditionReading must not carry updated_at — a reading is an "
        "immutable observation"
    )
    assert "version" not in reading, (
        "WaterConditionReading must not carry version — a reading is an "
        "immutable observation"
    )
    assert reading["posture"] in ("OPEN", "RESTRICTED", "CLOSED"), (
        f"WaterConditionReading posture out of range: {reading['posture']!r}"
    )
    assert isinstance(reading["cold_water_flag"], bool), (
        "WaterConditionReading cold_water_flag must be a boolean"
    )
    return reading


def assert_water_session(session):
    _assert_mutable_common_fields(session, "WaterSession")
    _assert_fields_present(
        session,
        [
            "shell_id",
            "session_kind",
            "planned_start_at",
            "planned_end_at",
            "coach_member_id",
            "coxswain_member_id",
            "primary_launch_driver_member_id",
            "secondary_launch_driver_member_id",
            "athlete_member_ids",
            "status",
            "reading_id",
            "required_launch_count",
            "assigned_launch_count",
            "actual_return_at",
        ],
        "WaterSession",
    )
    assert session["status"] in (
        "PLANNED",
        "CLEARED",
        "LAUNCHED",
        "RETURNED",
        "CANCELLED",
    ), f"WaterSession status out of range: {session['status']!r}"
    assert session["planned_start_at"] < session["planned_end_at"], (
        "WaterSession planned window must be non-degenerate: "
        f"{session['planned_start_at']} .. {session['planned_end_at']}"
    )
    return session


def assert_regatta(regatta):
    _assert_mutable_common_fields(regatta, "Regatta")
    _assert_fields_present(
        regatta,
        [
            "name",
            "host_club",
            "venue_kind",
            "race_date_at",
            "entry_deadline_at",
            "scratch_deadline_at",
            "weigh_in_opens_at",
            "weigh_in_closes_at",
            "late_entry_allowed",
            "status",
            "net_fee_cents",
            "deposit_held_cents",
        ],
        "Regatta",
    )
    assert regatta["venue_kind"] in ("HOME", "AWAY"), (
        f"Regatta venue_kind out of range: {regatta['venue_kind']!r}"
    )
    assert regatta["status"] in (
        "OPEN_FOR_ENTRY",
        "ENTRIES_CLOSED",
        "RACING",
        "COMPLETE",
        "CANCELLED",
    ), f"Regatta status out of range: {regatta['status']!r}"
    return regatta


def assert_regatta_entry(entry):
    _assert_mutable_common_fields(entry, "RegattaEntry")
    _assert_fields_present(
        entry,
        [
            "regatta_id",
            "shell_id",
            "event_code",
            "boat_class",
            "seed_time_seconds",
            "status",
            "base_fee_cents",
            "transport_levy_cents",
            "late_fee_cents",
            "total_fee_cents",
            "refund_cents",
            "submitted_at",
            "trailer_load_id",
            "rack_tier",
            "rack_position",
        ],
        "RegattaEntry",
    )
    assert entry["status"] in (
        "DRAFT",
        "LINEUP_DECLARED",
        "SUBMITTED",
        "CONFIRMED",
        "RACED",
        "SCRATCHED",
    ), f"RegattaEntry status out of range: {entry['status']!r}"
    return entry


def assert_entry_fee_components_sum(entry):
    """The three fee components must add up to the stored total."""
    expected = (
        entry["base_fee_cents"] + entry["transport_levy_cents"] + entry["late_fee_cents"]
    )
    assert entry["total_fee_cents"] == expected, (
        "RegattaEntry total_fee_cents must equal base + transport levy + late fee: "
        f"{entry['base_fee_cents']} + {entry['transport_levy_cents']} + "
        f"{entry['late_fee_cents']} = {expected}, got {entry['total_fee_cents']}"
    )
    return entry


def assert_lineup_seat(seat):
    _assert_mutable_common_fields(seat, "LineupSeat")
    _assert_fields_present(
        seat,
        [
            "regatta_entry_id",
            "member_id",
            "seat_number",
            "seat_role",
            "weighed_kg",
            "weighed_by_user_id",
            "deadweight_kg",
            "weigh_in_status",
            "eligibility_status",
        ],
        "LineupSeat",
    )
    assert seat["seat_role"] in ("ROWER", "COXSWAIN"), (
        f"LineupSeat seat_role out of range: {seat['seat_role']!r}"
    )
    assert seat["weigh_in_status"] in ("NOT_REQUIRED", "PENDING", "PASSED", "FAILED"), (
        f"LineupSeat weigh_in_status out of range: {seat['weigh_in_status']!r}"
    )
    assert seat["eligibility_status"] in (
        "ELIGIBLE",
        "BLOCKED_SAFETY",
        "BLOCKED_CERT",
        "BLOCKED_DUES",
    ), f"LineupSeat eligibility_status out of range: {seat['eligibility_status']!r}"
    return seat


def assert_heat(heat):
    _assert_mutable_common_fields(heat, "Heat")
    _assert_fields_present(
        heat,
        [
            "regatta_id",
            "event_code",
            "round_kind",
            "scheduled_start_at",
            "lane_count",
            "advance_count",
            "advances_to_heat_id",
            "status",
            "occupied_lane_count",
            "free_lane_count",
            "protest_window_closes_at",
        ],
        "Heat",
    )
    assert heat["status"] in (
        "SCHEDULED",
        "LANES_ASSIGNED",
        "RESULTS_PROVISIONAL",
        "RESULTS_OFFICIAL",
    ), f"Heat status out of range: {heat['status']!r}"
    assert heat["round_kind"] in ("HEAT", "SEMI", "FINAL"), (
        f"Heat round_kind out of range: {heat['round_kind']!r}"
    )
    return heat


def assert_heat_lane_counts_conserved(heat):
    """Occupied plus free lanes must always account for the whole heat."""
    total = heat["occupied_lane_count"] + heat["free_lane_count"]
    assert total == heat["lane_count"], (
        "Heat occupied_lane_count + free_lane_count must equal lane_count: "
        f"{heat['occupied_lane_count']} + {heat['free_lane_count']} = {total}, "
        f"lane_count is {heat['lane_count']}"
    )
    return heat


def assert_race_lane(lane):
    _assert_mutable_common_fields(lane, "RaceLane")
    _assert_fields_present(
        lane,
        [
            "heat_id",
            "regatta_entry_id",
            "lane_number",
            "lane_status",
            "elapsed_seconds",
            "place",
            "advanced",
        ],
        "RaceLane",
    )
    assert lane["lane_status"] in (
        "PENDING",
        "PROVISIONAL",
        "OFFICIAL",
        "DISQUALIFIED",
        "VOIDED",
    ), f"RaceLane lane_status out of range: {lane['lane_status']!r}"
    return lane


def assert_protest(protest):
    _assert_mutable_common_fields(protest, "Protest")
    _assert_fields_present(
        protest,
        [
            "heat_id",
            "filed_by_member_id",
            "against_race_lane_id",
            "ground_code",
            "narrative",
            "filed_at",
            "status",
            "deposit_cents",
            "deposit_refunded",
            "review_round",
            "jury_user_id",
        ],
        "Protest",
    )
    assert protest["status"] in (
        "FILED",
        "UNDER_JURY_REVIEW",
        "REMANDED",
        "UPHELD",
        "DENIED",
        "WITHDRAWN",
    ), f"Protest status out of range: {protest['status']!r}"
    assert protest["ground_code"] in (
        "INTERFERENCE",
        "LANE_VIOLATION",
        "EQUIPMENT",
        "FALSE_START",
    ), f"Protest ground_code out of range: {protest['ground_code']!r}"
    return protest


def assert_trailer_load(trailer):
    _assert_mutable_common_fields(trailer, "TrailerLoad")
    _assert_fields_present(
        trailer,
        [
            "regatta_id",
            "driver_member_id",
            "tow_vehicle_code",
            "depart_at",
            "return_at",
            "rack_tier_count",
            "rack_units_per_tier",
            "rack_unit_capacity",
            "status",
            "rack_units_used",
            "rack_units_free",
        ],
        "TrailerLoad",
    )
    assert trailer["status"] in ("OPEN", "SEALED", "DEPARTED", "ARRIVED", "RETURNED"), (
        f"TrailerLoad status out of range: {trailer['status']!r}"
    )
    return trailer


def assert_rack_units_conserved(trailer):
    """Used plus free rack units must always add back to the stated capacity."""
    total = trailer["rack_units_used"] + trailer["rack_units_free"]
    assert total == trailer["rack_unit_capacity"], (
        "TrailerLoad rack_units_used + rack_units_free must equal "
        f"rack_unit_capacity: {trailer['rack_units_used']} + "
        f"{trailer['rack_units_free']} = {total}, capacity is "
        f"{trailer['rack_unit_capacity']}"
    )
    return trailer


def assert_rack_capacity_derived(trailer):
    """Capacity is the tier count multiplied by the units available per tier."""
    expected = trailer["rack_tier_count"] * trailer["rack_units_per_tier"]
    assert trailer["rack_unit_capacity"] == expected, (
        "TrailerLoad rack_unit_capacity must equal rack_tier_count * "
        f"rack_units_per_tier: {trailer['rack_tier_count']} * "
        f"{trailer['rack_units_per_tier']} = {expected}, got "
        f"{trailer['rack_unit_capacity']}"
    )
    return trailer
