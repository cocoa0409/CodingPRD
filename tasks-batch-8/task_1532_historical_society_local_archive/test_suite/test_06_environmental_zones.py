"""Environmental telemetry: replay-driven posture, breach/clean thresholds,
operator asymmetry, the zone -> item -> appointment cascade, and recovery."""
from test_helpers import (
    ApiErrorId,
    api_client,
    catalog_item,
    create_accessioned,
    create_collection,
    create_item,
    create_published_finding_aid,
    create_zone,
    get_appointment,
    get_item,
    get_zone,
    make_item_available,
    post_breach_run,
    post_clean_run,
    post_reading,
    setup_confirmed_appointment,
    validate_error,
    validate_success,
)

ARCH = {"X-User-ID": "arch-1", "X-User-Role": "Archivist", "Content-Type": "application/json"}


class TestThresholdOperatorPrecision:

    def test_temperature_bound_is_strict(self):
        """PRD §2.6: "A reading is a breach when its temperature is strictly
        greater than `temp_high_c`, strictly less than `temp_low_c`, its
        humidity is greater than or equal to `humidity_high_pct`, or its
        humidity is less than or equal to `humidity_low_pct`; note the
        deliberate asymmetry — the temperature bounds are strict comparisons
        while the humidity bounds are inclusive."
        PRD §2.9: "Environmental thresholds are compared at the exact decimal
        precision posted, with the strict-versus-inclusive asymmetry of §2.6
        preserved."

        Design: Difficulty/boundary_precision_check/environmental_threshold_operator_precision
        """
        zone = create_zone()  # default thresholds: temp_high 24.0
        # Exactly 24.0 is NOT a breach (strict >).
        after = post_reading(zone["id"], "2026-08-01T01:00:00Z", 24.0)
        assert after["breach_streak"] == 0, (
            f"temp == temp_high_c must not breach; streak "
            f"{after['breach_streak']}")
        assert after["posture"] == "OPEN"
        # 24.1 > 24.0 IS a breach.
        after2 = post_reading(zone["id"], "2026-08-01T02:00:00Z", 24.1)
        assert after2["breach_streak"] == 1

    def test_humidity_bound_is_inclusive_and_hysteresis(self):
        """PRD §2.6: "A reading is a breach when its temperature is strictly
        greater than `temp_high_c`, strictly less than `temp_low_c`, its
        humidity is greater than or equal to `humidity_high_pct`, or its
        humidity is less than or equal to `humidity_low_pct`; note the
        deliberate asymmetry — the temperature bounds are strict comparisons
        while the humidity bounds are inclusive."
        PRD §2.6: "when the breach run reaches six the posture becomes
        `CLOSED`, and when the breach run reaches three while the replayed
        posture is still `OPEN` it becomes `RESTRICTED` — one or two consecutive
        breaches change nothing, a deliberate hysteresis."

        Design: Difficulty/boundary_precision_check/environmental_threshold_operator_precision
        """
        zone = create_zone()  # defaults: temp_high 24.0, humidity_high 60.0
        post_reading(zone["id"], "2026-08-01T02:00:00Z", 24.1)
        # Humidity exactly 60.0 (>= humidity_high_pct) breaches even with the
        # temperature in range.
        after = post_reading(zone["id"], "2026-08-01T03:00:00Z", 20.0,
                             humidity_pct=60.0)
        assert after["breach_streak"] == 2
        assert after["posture"] == "OPEN", (
            "two consecutive breaches sit inside the hysteresis band (< 3)")


class TestEnvironmentalBreachCascade:

    def _setup_zone_with_booked_item(self):
        ctx_zone = create_zone()
        collection = create_collection(ctx_zone["id"])
        accession, _deed = create_accessioned()
        create_published_finding_aid(collection["id"])
        item = create_item(accession["id"], collection["id"], title="Ledger")
        catalog_item(item["id"], appraised_value_cents=15000,
                     format="BOUND_VOLUME")
        make_item_available(item["id"])
        _researcher, _request, appointment = setup_confirmed_appointment(
            item["id"], scheduled_date="2026-08-10", start_time="10:00",
            end_time="12:00", seats=1)
        return ctx_zone, item, appointment

    def test_third_breach_restricts_zone_and_cascades(self):
        """PRD §2.6: "when the breach run reaches six the posture becomes
        `CLOSED`, and when the breach run reaches three while the replayed
        posture is still `OPEN` it becomes `RESTRICTED` — one or two consecutive
        breaches change nothing, a deliberate hysteresis."
        PRD §2.6: "When a zone leaves `OPEN` for `RESTRICTED`, or is driven from
        `OPEN` straight to `CLOSED` by a severe latest reading, every item whose
        collection sits in that zone and whose status is `AVAILABLE` moves to
        `ZONE_HOLD`, and every reading-room appointment in `CONFIRMED` status
        whose `scheduled_date` falls on or after the current logical date and
        whose underlying research request references a just-held item moves to
        `NEEDS_RESCHEDULE`."

        Design: Difficulty/transitive_cascade/environmental_breach_cascade
        """
        zone, item, appointment = self._setup_zone_with_booked_item()
        # Two breaches: hysteresis keeps the zone OPEN, nothing cascades.
        after_two = post_breach_run(zone["id"], 2, start_hour=1)
        assert after_two["posture"] == "OPEN"
        assert get_item(item["id"])["status"] == "AVAILABLE"

        # The third consecutive breach flips posture and fires both links.
        after_three = post_reading(zone["id"], "2026-08-01T03:00:00Z", 26.0)
        assert after_three["posture"] == "RESTRICTED"
        assert after_three["breach_streak"] == 3

        assert get_item(item["id"])["status"] == "ZONE_HOLD", (
            "link 2: AVAILABLE items in the zone move to ZONE_HOLD")
        assert get_appointment(appointment["id"])["status"] == "NEEDS_RESCHEDULE", (
            "link 3: future CONFIRMED appointments over held items move to "
            "NEEDS_RESCHEDULE")

    def test_breach_cascade_increments_versions(self):
        """PRD §2.4: "`version` (integer): starts at 1 at creation and
        increments by exactly 1 on every mutation of the resource, including
        mutations caused by cascades originating elsewhere."
        PRD §2.10: "Whenever a cascade mutates a resource, that resource's
        `updated_at` refreshes and its `version` increments like any other
        mutation."

        Design: Difficulty/transitive_cascade/environmental_breach_cascade
        """
        zone, item, appointment = self._setup_zone_with_booked_item()
        item_before = get_item(item["id"])["version"]
        appt_before = get_appointment(appointment["id"])["version"]

        post_breach_run(zone["id"], 3)

        item_after = get_item(item["id"])
        appt_after = get_appointment(appointment["id"])
        assert item_after["version"] == item_before + 1, (
            "cascade mutation increments the item's version")
        assert appt_after["version"] == appt_before + 1, (
            "cascade mutation increments the appointment's version")


class TestHysteresisRecovery:

    def test_zone_hysteresis_recovery_and_asymmetric_restore(self):
        """PRD §2.6: "An in-range reading extends the in-range run and resets
        the breach run to zero; when the in-range run reaches three, the posture
        steps one level toward `OPEN` (`CLOSED` to `RESTRICTED`, `RESTRICTED` to
        `OPEN`, `OPEN` remaining `OPEN`). A zone therefore never recovers from
        `CLOSED` directly to `OPEN` in a single step; recovery proceeds one
        level at a time."
        PRD §2.6: "A zone moving from `RESTRICTED` to `CLOSED` on a six-breach
        run causes no further item transitions; already-held items remain
        `ZONE_HOLD`. When a zone returns to `OPEN`, the zone's `ZONE_HOLD` items
        become `AVAILABLE` again — but appointments in `NEEDS_RESCHEDULE` are
        deliberately **not** auto-restored; the researcher must explicitly
        reschedule or cancel them. This asymmetry is pinned product behavior."

        Design: Corner/calculations/zone_hysteresis_recovery_and_asymmetric_restore
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        accession, _deed = create_accessioned()
        create_published_finding_aid(collection["id"])
        item = create_item(accession["id"], collection["id"], title="I1")
        catalog_item(item["id"])
        make_item_available(item["id"])
        _researcher, _request, appointment = setup_confirmed_appointment(
            item["id"], scheduled_date="2026-08-10", start_time="10:00",
            end_time="12:00", seats=1)

        # Six consecutive breaches: RESTRICTED at 3, CLOSED at 6.
        after_three = post_breach_run(zone["id"], 3, start_hour=1)
        assert after_three["posture"] == "RESTRICTED"
        after_six = post_breach_run(zone["id"], 3, start_hour=4)
        assert after_six["posture"] == "CLOSED"
        assert after_six["breach_streak"] == 6
        assert get_item(item["id"])["status"] == "ZONE_HOLD"

        # First clean run of three: CLOSED steps only one level.
        after_clean1 = post_clean_run(zone["id"], 3, start_hour=7)
        assert after_clean1["posture"] == "RESTRICTED", (
            "CLOSED recovers one level at a time, never directly to OPEN")
        assert get_item(item["id"])["status"] == "ZONE_HOLD"

        # Second clean run of three: reaches OPEN and frees the items.
        after_clean2 = post_clean_run(zone["id"], 3, start_hour=10)
        assert after_clean2["posture"] == "OPEN"
        assert get_item(item["id"])["status"] == "AVAILABLE"

        # The appointment is deliberately NOT auto-restored.
        assert get_appointment(appointment["id"])["status"] == "NEEDS_RESCHEDULE"


class TestZoneGateOnMakeAvailable:

    def test_zone_restricted_blocks_make_available(self):
        """PRD §3.2: "Making an item available moves it `CATALOGED → AVAILABLE`
        only when three further conditions hold beyond the item's own state: the
        collection has a published finding aid (`ERR_FINDING_AID_NOT_PUBLISHED`),
        the item's accession is `ACCESSIONED` (`ERR_ACCESSION_NOT_ACCESSIONED`),
        and the collection's zone posture is `OPEN` (`ERR_ZONE_RESTRICTED`)."

        Design: Corner/validations/zone_restricted_blocks_make_available
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        accession, _deed = create_accessioned()
        create_published_finding_aid(collection["id"])
        item = create_item(accession["id"], collection["id"], title="I1")
        catalog_item(item["id"])

        after_three = post_breach_run(zone["id"], 3)
        assert after_three["posture"] == "RESTRICTED"

        resp = api_client.make_item_available(item["id"], ARCH)
        validate_error(resp, ApiErrorId.ERR_ZONE_RESTRICTED)
        assert get_item(item["id"])["status"] == "CATALOGED"
