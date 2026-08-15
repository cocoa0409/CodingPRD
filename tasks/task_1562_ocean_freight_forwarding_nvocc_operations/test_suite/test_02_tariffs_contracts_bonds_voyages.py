"""Tariff publication, carrier contract windows, surety bonds, voyage gates."""
from test_helpers import (
    ApiErrorId,
    create_active_contract,
    create_carrier_contract_payload,
    create_open_voyage,
    create_published_tariff,
    create_shipper,
    create_surety_bond_payload,
    create_tariff_payload,
    create_voyage_payload,
    setup_lcl_lane,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CO_1, CO_2, OPS
from test_helpers.test_users import make_shipper_headers


class TestTariffLifecycle:
    def test_tariff_create_starts_in_draft(self, api):
        """PRD §3.2: "New tariffs start in `DRAFT`."

        Design: Corner/state_machines/tariff_create_starts_in_draft
        """
        tariff = validate_success(
            api.create_tariff(create_tariff_payload(tariff_code="T-INIT"), CO_1),
            201)
        assert tariff["status"] == "DRAFT"

    def test_sod_tariff_creator_cannot_publish_own_draft(self, api):
        """PRD §3.2: "Publishing a tariff — a `ComplianceOfficer` action —
        transitions it to `PUBLISHED`, but three preconditions must hold: the
        tariff must currently be `DRAFT` (otherwise `ERR_TARIFF_INVALID_STATE`);
        the publisher must differ from the creator (`published_by_user_id` must
        differ from `created_by_user_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES`); and no other `PUBLISHED` tariff may
        already exist with the identical key tuple — `origin_port`,
        `destination_port`, `commodity_type`, `mode`, `container_type` — whose
        half-open window intersects this tariff's window."

        Design: Corner/validations/sod_tariff_creator_cannot_publish_own_draft
        """
        tariff = validate_success(
            api.create_tariff(create_tariff_payload(tariff_code="T-SOD"), CO_1),
            201)
        res = api.publish_tariff(tariff["id"], CO_1)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)

        published = validate_success(api.publish_tariff(tariff["id"], CO_2), 200)
        assert published["status"] == "PUBLISHED"
        assert published["published_by_user_id"] == "co_2"


class TestTariffWindowOverlap:
    """Half-open tariff windows: adjacency allowed, straddle rejected."""

    def _setup_three_tariffs(self, api):
        t_a = validate_success(
            api.create_tariff(
                create_tariff_payload(tariff_code="T-A",
                                      effective_from="2026-08-01T00:00:00Z",
                                      effective_to="2026-11-01T00:00:00Z"),
                CO_1),
            201)
        validate_success(api.publish_tariff(t_a["id"], CO_2), 200)
        t_b = validate_success(
            api.create_tariff(
                create_tariff_payload(tariff_code="T-B",
                                      rate_per_unit_cents=9900,
                                      effective_from="2026-11-01T00:00:00Z",
                                      effective_to="2027-02-01T00:00:00Z"),
                CO_1),
            201)
        t_c = validate_success(
            api.create_tariff(
                create_tariff_payload(tariff_code="T-C",
                                      rate_per_unit_cents=9200,
                                      effective_from="2026-10-15T00:00:00Z",
                                      effective_to="2026-12-15T00:00:00Z"),
                CO_1),
            201)
        return t_a, t_b, t_c

    def test_adjacent_tariff_window_publish_allowed(self, api):
        """PRD §3.2: "**Adjacency is not an intersection** for tariffs: if one
        window ends exactly when another begins, they do not overlap."

        Design: Difficulty/resource_temporal_overlap/tariff_halfopen_window_adjacency_allowed_overlap_rejected
        """
        _t_a, t_b, _t_c = self._setup_three_tariffs(api)
        published = validate_success(api.publish_tariff(t_b["id"], CO_2), 200)
        assert published["status"] == "PUBLISHED", (
            "T-B starting exactly at T-A's effective_to is adjacent, not overlapping"
        )

    def test_straddling_tariff_window_publish_rejected(self, api):
        """PRD §3.2: "no other `PUBLISHED` tariff may already exist with the
        identical key tuple — `origin_port`, `destination_port`,
        `commodity_type`, `mode`, `container_type` — whose half-open window
        intersects this tariff's window."
        PRD §3.2: "A window-intersection violation is rejected with
        `ERR_TARIFF_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/tariff_halfopen_window_adjacency_allowed_overlap_rejected
        """
        _t_a, t_b, t_c = self._setup_three_tariffs(api)
        validate_success(api.publish_tariff(t_b["id"], CO_2), 200)

        res = api.publish_tariff(t_c["id"], CO_2)
        validate_error(res, ApiErrorId.ERR_TARIFF_WINDOW_OVERLAP,
                       expected_status=409)
        after = validate_success(api.get_tariff(t_c["id"], CO_1), 200)
        assert after["status"] == "DRAFT"


class TestContractWindowOverlap:
    """Closed contract windows: adjacency IS a conflict on the same lane."""

    def _setup_three_contracts(self, api):
        c_a = validate_success(
            api.create_carrier_contract(
                create_carrier_contract_payload(
                    contract_number="OOCL-A",
                    service_start="2026-01-01T00:00:00Z",
                    service_end="2026-06-30T00:00:00Z"),
                OPS),
            201)
        validate_success(api.activate_carrier_contract(c_a["id"], OPS), 200)
        c_b = validate_success(
            api.create_carrier_contract(
                create_carrier_contract_payload(
                    contract_number="OOCL-B",
                    service_start="2026-06-30T00:00:00Z",
                    service_end="2026-12-31T00:00:00Z"),
                OPS),
            201)
        c_c = validate_success(
            api.create_carrier_contract(
                create_carrier_contract_payload(
                    contract_number="OOCL-C",
                    service_start="2026-07-01T00:00:00Z",
                    service_end="2026-12-31T00:00:00Z"),
                OPS),
            201)
        return c_a, c_b, c_c

    def test_adjacent_contract_window_activate_rejected(self, api):
        """PRD §3.3: "**Adjacency is an intersection** for contracts (unlike
        tariffs): a contract whose `service_start` equals an existing
        contract's `service_end` conflicts with it. An overlap is rejected
        with `ERR_CONTRACT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contract_closed_window_adjacency_conflicts
        """
        _c_a, c_b, _c_c = self._setup_three_contracts(api)
        res = api.activate_carrier_contract(c_b["id"], OPS)
        validate_error(res, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP,
                       expected_status=409)
        after = validate_success(api.get_carrier_contract(c_b["id"], OPS), 200)
        assert after["status"] == "NEGOTIATION"

    def test_strictly_later_contract_window_activate_allowed(self, api):
        """PRD §3.3: "Activating a contract — an `OperationsManager` action —
        requires the contract to be `NEGOTIATION` (otherwise
        `ERR_CONTRACT_INVALID_STATE`) and transitions it to `ACTIVE` only when
        no other contract with the identical (`carrier_name`, `service_lane`)
        pair in `ACTIVE` or `SUSPENDED` status has a closed window that
        intersects this contract's closed window."

        Design: Difficulty/resource_temporal_overlap/contract_closed_window_adjacency_conflicts
        """
        _c_a, c_b, c_c = self._setup_three_contracts(api)
        validate_error(api.activate_carrier_contract(c_b["id"], OPS),
                       ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)

        activated = validate_success(
            api.activate_carrier_contract(c_c["id"], OPS), 200)
        assert activated["status"] == "ACTIVE", (
            "C-C starts strictly after C-A's inclusive service_end — no intersection"
        )


class TestContractSuspendResume:
    def test_contract_suspend_resume_cycle_blocks_voyage_creation(self, api):
        """PRD §3.3: "An `ACTIVE` contract may be suspended (transitioning
        `ACTIVE` to `SUSPENDED`; any other state rejects with
        `ERR_CONTRACT_INVALID_STATE`), which blocks new voyage creation against
        it with `ERR_CONTRACT_NOT_ACTIVE` while leaving existing voyages
        untouched; a `SUSPENDED` contract may be resumed (again
        `ERR_CONTRACT_INVALID_STATE` on any other state), which re-runs the
        window-overlap check against currently `ACTIVE` contracts on the same
        carrier and lane."

        Design: Corner/state_machines/contract_suspend_resume_cycle_blocks_voyage_creation
        """
        contract = create_active_contract(contract_number="CARR-S")

        suspended = validate_success(
            api.suspend_carrier_contract(contract["id"], OPS), 200)
        assert suspended["status"] == "SUSPENDED"

        payload = create_voyage_payload(
            contract["id"], vessel_name="STAR", voyage_number="ST1",
            etd="2026-10-01T00:00:00Z", eta="2026-10-30T00:00:00Z")
        res = api.create_voyage(payload, OPS)
        validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
                       expected_status=409)

        resumed = validate_success(
            api.resume_carrier_contract(contract["id"], OPS), 200)
        assert resumed["status"] == "ACTIVE"
        voyage = validate_success(api.create_voyage(payload, OPS), 201)
        assert voyage["status"] == "SCHEDULED"


class TestBondActivationWindow:
    def test_bond_activate_outside_window_rejected(self, api):
        """PRD §3.4: "Activation — a `ComplianceOfficer` action — requires the
        bond to be `INACTIVE` (otherwise `ERR_BOND_INVALID_STATE`) and the
        logical clock to satisfy the window condition: `effective_from` must be
        less than or equal to the logical clock, and the logical clock must be
        strictly less than `effective_to` (otherwise
        `ERR_BOND_NOT_IN_WINDOW`)."

        Design: Corner/validations/bond_activate_outside_window_rejected
        """
        bond = validate_success(
            api.create_surety_bond(
                create_surety_bond_payload(
                    bond_number="BOND-FUT",
                    effective_from="2027-01-01T00:00:00Z",
                    effective_to="2028-01-01T00:00:00Z"),
                CO_1),
            201)
        res = api.activate_surety_bond(bond["id"], CO_1)
        validate_error(res, ApiErrorId.ERR_BOND_NOT_IN_WINDOW,
                       expected_status=409)

        validate_success(api.set_clock("2027-01-01T00:00:00Z", OPS), 200)
        activated = validate_success(api.activate_surety_bond(bond["id"], CO_1), 200)
        assert activated["status"] == "ACTIVE", (
            "clock == effective_from satisfies the inclusive lower bound"
        )


class TestVoyageTemporalGates:
    def test_voyage_etd_outside_contract_window_rejected(self, api):
        """PRD §3.5: "Two temporal invariants hold: `eta` must be strictly
        later than `etd`, and the `etd` must lie inside the contract's
        **closed** service window — that is, on or after `service_start` and
        on or before `service_end`. A voyage whose `etd` falls outside the
        contract window is rejected with
        `ERR_VOYAGE_OUTSIDE_CONTRACT_WINDOW`."

        Design: Corner/validations/voyage_etd_outside_contract_window_rejected
        """
        contract = create_active_contract(contract_number="CARR-W")

        ok = validate_success(
            api.create_voyage(
                create_voyage_payload(contract["id"], vessel_name="STAR",
                                      voyage_number="ST-EDGE",
                                      etd="2026-12-31T00:00:00Z",
                                      eta="2027-01-20T00:00:00Z"),
                OPS),
            201)
        assert ok["status"] == "SCHEDULED", (
            "etd == service_end is inside the closed window (inclusive bound)"
        )

        res = api.create_voyage(
            create_voyage_payload(contract["id"], vessel_name="STAR",
                                  voyage_number="ST-OUT",
                                  etd="2027-01-01T00:00:00Z",
                                  eta="2027-01-30T00:00:00Z"),
            OPS)
        validate_error(res, ApiErrorId.ERR_VOYAGE_OUTSIDE_CONTRACT_WINDOW,
                       expected_status=422)

    def test_voyage_depart_before_etd_rejected(self, api):
        """PRD §3.5: "From `BOOKING_OPEN` the voyage may depart: departure
        requires the logical clock to be greater than or equal to `etd`
        (otherwise `ERR_VOYAGE_NOT_DEPARTABLE`) and transitions the voyage to
        `DEPARTED`."
        PRD §2.5: "Before any operator has advanced it, the logical clock
        reads exactly `2026-08-01T00:00:00Z` and must not fall back to
        wall-clock time."

        Design: Corner/validations/voyage_depart_before_etd_rejected
        """
        contract = create_active_contract(contract_number="CARR-D")
        voyage = create_open_voyage(contract["id"], voyage_number="ST1")

        res = api.depart_voyage(voyage["id"], OPS)
        validate_error(res, ApiErrorId.ERR_VOYAGE_NOT_DEPARTABLE,
                       expected_status=409)

        validate_success(api.set_clock("2026-09-01T00:00:00Z", OPS), 200)
        departed = validate_success(api.depart_voyage(voyage["id"], OPS), 200)
        assert departed["status"] == "DEPARTED", "clock == etd satisfies >="


class TestBookingTariffReferentialGates:
    def test_booking_rejected_when_tariff_window_misses_voyage_etd(self, api):
        """PRD §3.6: "The tariff must be `PUBLISHED` and its half-open window
        must cover the voyage's `etd` (otherwise `ERR_TARIFF_NOT_EFFECTIVE`)."
        PRD §3.2: "The tariff window is **half-open** — the window includes
        `effective_from` and excludes `effective_to`, so a voyage departing
        exactly at `effective_to` is not covered."

        Design: Corner/validations/booking_rejected_when_tariff_window_misses_voyage_etd
        """
        shipper = create_shipper(legal_name="ACME TNE")
        tariff = create_published_tariff(tariff_code="T-EXP",
                                         effective_to="2026-08-31T00:00:00Z")
        contract = create_active_contract()
        voyage = create_open_voyage(contract["id"])

        res = api.create_booking(
            {
                "voyage_id": voyage["id"],
                "tariff_id": tariff["id"],
                "rate_source": "CONTRACT",
                "mode": "LCL",
                "commodity_type": "GENERAL",
                "gross_weight_kg": 4000,
                "volume_cbm": 6.0,
                "terms": "PREPAID",
            },
            make_shipper_headers(shipper["id"]))
        validate_error(res, ApiErrorId.ERR_TARIFF_NOT_EFFECTIVE,
                       expected_status=422)

    def test_booking_tariff_commodity_mismatch_rejected(self, api):
        """PRD §3.6: "The tariff's `origin_port` and `destination_port` must
        match the voyage's ports, its `commodity_type` and `mode` must match
        the booking's, and for `FCL` the booking's `container_type` must equal
        the tariff's `container_type` — any mismatch is rejected with
        `ERR_TARIFF_MISMATCH`."

        Design: Corner/validations/booking_tariff_commodity_mismatch_rejected
        """
        ctx = setup_lcl_lane()
        res = api.create_booking(
            {
                "voyage_id": ctx["voyage"]["id"],
                "tariff_id": ctx["tariff"]["id"],
                "rate_source": "CONTRACT",
                "mode": "LCL",
                "commodity_type": "HAZMAT",
                "gross_weight_kg": 4000,
                "volume_cbm": 6.0,
                "terms": "PREPAID",
            },
            make_shipper_headers(ctx["shipper"]["id"]))
        validate_error(res, ApiErrorId.ERR_TARIFF_MISMATCH, expected_status=422)
