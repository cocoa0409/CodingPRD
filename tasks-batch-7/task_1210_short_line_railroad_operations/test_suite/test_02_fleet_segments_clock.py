"""Fleet registration, track-segment computed speed, the fixed-epoch logical
clock, and the siding expiry sweep (PRD §2.4, §2.5, §3.1, §3.3, §3.6)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    assert_railcar,
    create_customer,
    create_railcar,
    create_railcar_payload,
    create_segment,
    create_siding,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_success,
)

FIXED_EPOCH = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestRailcarRegistration:
    def test_railcar_invalid_car_type_enum_rejected(self, api, system_admin_headers):
        """PRD §3.1: "With master data in place, a `CustomerRep` places a
        **CarOrder** by naming the `customer_id`, the delivery `siding_id` — which
        must belong to that customer — the requested `car_type` (one of `BOX`,
        `HOPPER`, `TANK`, `FLAT`, or `GONDOLA`), a `quantity` of at least one car,
        and a `needed_by_date`."
        PRD §2.9: "Immediately after the headers, and still ahead of any business
        rule, syntactic body validation rejects malformed payloads, missing
        required fields, invalid enum values, and invalid types with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/railcar_invalid_car_type_enum_rejected
        """
        resp = api.create_railcar(
            create_railcar_payload(reporting_mark="GNWR 1", car_type="COIL"),
            system_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_railcar_duplicate_reporting_mark_rejected(self, api, system_admin_headers):
        """PRD §3.3: "The **Railcar** roster is maintained by a `SystemAdmin`, who
        registers each car with its unique AAR `reporting_mark` — a duplicate mark
        anywhere on the roster is refused with `ERR_DUPLICATE_REPORTING_MARK` — a
        `car_type` from the same five-value fleet enum used by orders, an
        `ownership` of `HOME` for railroad-owned cars or `FOREIGN` for cars owned
        by a connecting road, and, for foreign cars, the `home_road_mark` plus the
        car-hire rates `hire_rate_per_hour_cents` and `hire_rate_per_mile_cents`,
        both integer cents payable to the owner."

        Design: Corner/entities/railcar_duplicate_reporting_mark_rejected
        """
        create_railcar(reporting_mark="GNWR 5001", car_type="BOX")
        resp = api.create_railcar(
            create_railcar_payload(
                reporting_mark="GNWR 5001", car_type="HOPPER", ownership="FOREIGN",
                home_road_mark="NS", hire_rate_per_hour_cents=100, hire_rate_per_mile_cents=80,
            ),
            system_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORTING_MARK)

    def test_railcar_system_fields_server_minted(self, api, system_admin_headers):
        """PRD §2.5: "The `id` is a server-minted UUID with no type prefix.
        `created_at` is an ISO 8601 UTC timestamp with three fractional digits
        recording when the resource was created."
        PRD §2.4: "At server startup the clock reads exactly
        `2026-05-01T00:00:00Z`, and it advances only when a `SystemAdmin` sets it
        to a supplied `to_iso8601` instant through the clock-advance capability."

        Design: Corner/entities/railcar_system_fields_server_minted
        """
        car = create_railcar(reporting_mark="GNWR 7001", car_type="FLAT")
        assert_railcar(car)
        assert is_valid_uuid(car["id"]), f"id must be a prefix-free UUID, got {car['id']!r}"
        assert _parse_iso(car["created_at"]) == FIXED_EPOCH, (
            f"created_at must equal the fixed startup clock 2026-05-01T00:00:00Z, "
            f"got {car['created_at']!r}"
        )


class TestTrackSegmentSpeed:
    def test_segment_computed_speed_input_ignored(self, api, system_admin_headers):
        """PRD §3.6: "Each segment carries a computed `effective_speed_mph`: the
        base speed for its class — 10 mph for `EXCEPTED`, 10 for `CLASS_1`, 25 for
        `CLASS_2`, 40 for `CLASS_3`, 60 for `CLASS_4`, and 80 for `CLASS_5` — and,
        while a defect is open on the segment, the lesser of that base and the
        defect cap, which is 25 mph for a `MONITOR` defect and 10 mph for a
        `CRITICAL` one."

        Design: Corner/entities/segment_computed_speed_input_ignored
        """
        resp = api.create_track_segment(
            {
                "name": "Spur 1", "milepost_start": 0, "milepost_end": 2,
                "fra_class": "CLASS_2", "effective_speed_mph": 99,
            },
            system_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["effective_speed_mph"] == 25, (
            f"effective_speed_mph is server-computed from the class: CLASS_2 must yield 25, "
            f"got {data['effective_speed_mph']} (client-supplied 99 must not win)"
        )


class TestLogicalClock:
    def test_clock_default_is_fixed_epoch(self, api, system_admin_headers):
        """PRD §2.4: "At server startup the clock reads exactly
        `2026-05-01T00:00:00Z`, and it advances only when a `SystemAdmin` sets it
        to a supplied `to_iso8601` instant through the clock-advance capability."
        PRD §3.6: "A new segment is `IN_SERVICE` with `defect_open` false,
        `open_defect_severity` unset, `is_overdue` false, and `last_inspection_at`
        stamped with the creation clock; segments can be listed filtered by
        `fra_class` or `status`."

        Design: Corner/cross_cutting_layers/clock_default_is_fixed_epoch
        """
        seg = create_segment(name="Epoch Seg", milepost_start=0, milepost_end=1, fra_class="CLASS_5")
        assert _parse_iso(seg["last_inspection_at"]) == FIXED_EPOCH, (
            f"last_inspection_at must be stamped from the fixed startup clock, "
            f"got {seg['last_inspection_at']!r}"
        )
        assert seg["is_overdue"] is False, (
            "a segment created at the startup epoch is not past its own inspection deadline"
        )


class TestSidingAgreementSweep:
    def test_siding_expiry_sweep_and_renewal(self, api, system_admin_headers):
        """PRD §3.1: "An administrator may suspend an active agreement, moving it
        to `SUSPENDED`, and may renew an `EXPIRED` or `SUSPENDED` agreement by
        supplying a `new_expires_on` strictly later than the current clock;
        renewal copies `new_expires_on` into `agreement_expires_on` and returns
        the siding to `ACTIVE`. When the logical clock reaches or passes
        `agreement_expires_on`, the siding expiry sweep moves an `ACTIVE`
        agreement to `EXPIRED` on its own."

        Design: Corner/state_machines/siding_expiry_sweep_and_renewal
        """
        customer = create_customer(name="Expiry Co", billing_email="e@x.example")
        segment = create_segment(name="Main MP 17-18", milepost_start=17, milepost_end=18)
        siding = create_siding(
            customer["id"], segment["id"], name="Expiry Siding", capacity_cars=4,
            agreement_expires_on="2026-05-10T00:00:00Z",
        )

        set_clock("2026-05-09T23:59:59Z")
        before = validate_success(api.get_siding(siding["id"], system_admin_headers))
        assert before["maintenance_agreement_status"] == "ACTIVE", (
            f"one second before expiry the agreement must still be ACTIVE, "
            f"got {before['maintenance_agreement_status']}"
        )

        set_clock("2026-05-10T00:00:00Z")
        expired = validate_success(api.get_siding(siding["id"], system_admin_headers))
        assert expired["maintenance_agreement_status"] == "EXPIRED", (
            f"at exactly agreement_expires_on the sweep must move the agreement to EXPIRED "
            f"(reaches-or-passes semantics), got {expired['maintenance_agreement_status']}"
        )

        renewed = validate_success(
            api.renew_siding_agreement(siding["id"], {"new_expires_on": "2027-06-01T00:00:00Z"}, system_admin_headers)
        )
        assert renewed["maintenance_agreement_status"] == "ACTIVE", (
            f"renew-agreement must return an EXPIRED siding to ACTIVE, "
            f"got {renewed['maintenance_agreement_status']}"
        )
        assert renewed["agreement_expires_on"].startswith("2027-06-01T00:00:00"), (
            f"renewal must copy new_expires_on into agreement_expires_on, "
            f"got {renewed['agreement_expires_on']!r}"
        )
