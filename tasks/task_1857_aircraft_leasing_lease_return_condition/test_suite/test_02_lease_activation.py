"""Lease activation gates: records safety gate, overlap, aircraft
availability, invalid transitions, and the pipeline's gate ordering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_aircraft,
    create_aircraft_with_birth_record,
    create_lease_payload,
    create_lessee,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["lessor_admin_headers"]


def _mk_lease(api, aircraft_id, lessee_id, start, end, **overrides):
    payload = create_lease_payload(
        aircraft_id=aircraft_id, lessee_id=lessee_id,
        start_date=start, end_date=end, **overrides)
    return validate_success(api.create_lease(payload, ADMIN), expected_status=201)


class TestActivateInvalidState:
    def test_activate_already_active_lease_returns_invalid_state(self, api):
        """PRD §3.2: "A lease not in `DRAFT` cannot be activated at all
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/activate_already_active_lease_returns_invalid_state
        """
        aircraft, _doc = create_aircraft_with_birth_record(
            msn="MSN-SM-1", model="A320-200", manufacture_date="2012-01-01")
        lessee = create_lessee(legal_name="SM1 Air")
        lease = _mk_lease(api, aircraft["id"], lessee["id"], "2026-08-01", "2027-08-01")
        validate_success(api.activate_lease(lease["id"], ADMIN))

        resp = api.activate_lease(lease["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestRecordsGateAtActivation:
    def test_activation_requires_verified_birth_record(self, api):
        """PRD §3.2: "the aircraft holds at least one `VERIFIED` document of
        `doc_type` `BIRTH_RECORD` — the back-to-birth anchor, without which
        the attempt fails with `ERR_RECORDS_INCOMPLETE`"

        Design: Difficulty/priority_pair_validation_conflict/activate_records_missing_and_overlap_safety_wins
        """
        # Aircraft with a BIRTH_RECORD that stays SUBMITTED (never verified).
        aircraft = create_aircraft(msn="MSN-L2", model="E195-E2",
                                   manufacture_date="2021-05-05")
        doc = validate_success(
            api.create_document(aircraft["id"],
                                {"doc_type": "BIRTH_RECORD", "doc_reference": "BR-L2"},
                                ADMIN),
            expected_status=201)
        assert doc["status"] == "SUBMITTED"
        lessee_x = create_lessee(legal_name="Lima Air")
        lessee_y = create_lessee(legal_name="Lima2 Air")
        _mk_lease(api, aircraft["id"], lessee_x["id"], "2026-08-01", "2027-08-01",
                  monthly_rent_cents=900000)
        lease_y = _mk_lease(api, aircraft["id"], lessee_y["id"], "2027-01-01", "2028-01-01",
                            monthly_rent_cents=950000)

        resp = api.activate_lease(lease_y["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RECORDS_INCOMPLETE, expected_status=409)

    def test_activation_records_gate_fires_before_overlap_rule(self, api):
        """PRD §2.8: "activation evaluates the records gate before the overlap
        rule, and the overlap rule before the aircraft-availability and
        lessee-standing checks"

        Design: Difficulty/priority_pair_validation_conflict/activate_records_missing_and_overlap_safety_wins
        """
        # Lease Y both lacks the records gate (no verified BIRTH_RECORD) and
        # overlaps DRAFT lease X; the records gate must win.
        aircraft = create_aircraft(msn="MSN-L2B", model="E195-E2",
                                   manufacture_date="2021-05-05")
        validate_success(
            api.create_document(aircraft["id"],
                                {"doc_type": "BIRTH_RECORD", "doc_reference": "BR-L2B"},
                                ADMIN),
            expected_status=201)
        lessee_x = create_lessee(legal_name="Lima Air B1")
        lessee_y = create_lessee(legal_name="Lima Air B2")
        _mk_lease(api, aircraft["id"], lessee_x["id"], "2026-08-01", "2027-08-01")
        lease_y = _mk_lease(api, aircraft["id"], lessee_y["id"], "2027-01-01", "2028-01-01")

        resp = api.activate_lease(lease_y["id"], ADMIN)
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_RECORDS_INCOMPLETE", (
            f"records gate (priority 6) must fire before overlap (priority 7); "
            f"got {body['data']['error_id']!r}")


class TestOverlap:
    def test_adjacent_lease_activation_succeeds(self, api):
        """PRD §3.2: "no other lease on the same aircraft in `DRAFT`,
        `ACTIVE`, `RETURN_INITIATED`, or `DEFAULTED` has a half-open interval
        intersecting this lease's interval — adjacency, where one lease's
        `start_date` equals the other's `end_date`, is explicitly permitted,
        and a true intersection fails with `ERR_LEASE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/lease_overlap_half_open_adjacency
        """
        aircraft, _doc = create_aircraft_with_birth_record(
            msn="MSN-R7", model="A330-900", manufacture_date="2022-03-10")
        lessee = create_lessee(legal_name="Romeo Air")
        lease_a = _mk_lease(api, aircraft["id"], lessee["id"], "2026-08-01", "2027-08-01")
        lease_b = _mk_lease(api, aircraft["id"], lessee["id"], "2027-08-01", "2028-08-01")

        # Adjacent to A (B.start == A.end): not an overlap under half-open
        # semantics. A is the only other lease at this point, so nothing else
        # can block B's activation.
        activated_b = validate_success(api.activate_lease(lease_b["id"], ADMIN))
        assert activated_b["status"] == "ACTIVE"

        # Interior intersection with the now-ACTIVE lease B: rejected. (C is
        # drafted only after B is ACTIVE — a DRAFT C would also block B's own
        # activation, since DRAFT leases count toward the overlap rule.)
        lease_c = _mk_lease(api, aircraft["id"], lessee["id"], "2027-06-01", "2028-06-01")
        resp = api.activate_lease(lease_c["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_LEASE_PERIOD_OVERLAP, expected_status=409)

    def test_overlapping_lease_activation_rejected(self, api):
        """PRD §3.2: "no other lease on the same aircraft in `DRAFT`,
        `ACTIVE`, `RETURN_INITIATED`, or `DEFAULTED` has a half-open interval
        intersecting this lease's interval — adjacency, where one lease's
        `start_date` equals the other's `end_date`, is explicitly permitted,
        and a true intersection fails with `ERR_LEASE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/lease_overlap_half_open_adjacency
        """
        aircraft, _doc = create_aircraft_with_birth_record(
            msn="MSN-R7B", model="A330-900", manufacture_date="2022-03-10")
        lessee = create_lessee(legal_name="Romeo Air B")
        # No overlap checking happens at creation time per PRD §3.2: "No
        # overlap checking happens at creation time — two drafts may coexist;
        # the conflict is enforced at activation." A activates cleanly while
        # it is the only lease on the aircraft.
        lease_a = _mk_lease(api, aircraft["id"], lessee["id"], "2026-08-01", "2027-08-01")
        validate_success(api.activate_lease(lease_a["id"], ADMIN))
        # The overlapping draft is creatable (creation never checks overlap),
        # but its activation conflicts with the ACTIVE lease A.
        lease_b = _mk_lease(api, aircraft["id"], lessee["id"], "2027-01-01", "2028-01-01")

        resp = api.activate_lease(lease_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_LEASE_PERIOD_OVERLAP, expected_status=409)


class TestAircraftAvailability:
    def test_activation_rejected_when_aircraft_on_lease(self, api):
        """PRD §3.2: "the aircraft's `status` is `AVAILABLE`, else
        `ERR_AIRCRAFT_NOT_AVAILABLE`"

        Design: Difficulty/cross_entity_state_dependency/lease_activation_requires_aircraft_available
        """
        aircraft, _doc = create_aircraft_with_birth_record(
            msn="MSN-P5", model="A321neo", manufacture_date="2020-06-15")
        lessee_1 = create_lessee(legal_name="Papa Air")
        lessee_2 = create_lessee(legal_name="Papa2 Air")
        lease_1 = _mk_lease(api, aircraft["id"], lessee_1["id"], "2026-08-01", "2027-08-01")
        validate_success(api.activate_lease(lease_1["id"], ADMIN))
        # Dates disjoint from lease 1: the temporal overlap rule passes, so
        # only the availability gate can fire.
        lease_2 = _mk_lease(api, aircraft["id"], lessee_2["id"], "2027-09-01", "2028-09-01")

        resp = api.activate_lease(lease_2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_AVAILABLE, expected_status=409)

    def test_activation_flips_aircraft_on_lease(self, api):
        """PRD §3.2: "On success the cascade flips the aircraft from
        `AVAILABLE` to `ON_LEASE`, refreshing the aircraft's `updated_at` and
        incrementing its `version`, and increments the lease's own
        `version`."

        Design: Difficulty/cross_entity_state_dependency/lease_activation_requires_aircraft_available
        """
        aircraft, _doc = create_aircraft_with_birth_record(
            msn="MSN-P5B", model="A321neo", manufacture_date="2020-06-15")
        lessee = create_lessee(legal_name="Papa Air B")
        lease = _mk_lease(api, aircraft["id"], lessee["id"], "2026-08-01", "2027-08-01")
        assert aircraft["status"] == "AVAILABLE"
        aircraft_version = aircraft["version"]

        activated = validate_success(api.activate_lease(lease["id"], ADMIN))
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == lease["version"] + 1

        aircraft_now = validate_success(api.get_aircraft(aircraft["id"], ADMIN))
        assert aircraft_now["status"] == "ON_LEASE", (
            "activation cascades the aircraft AVAILABLE -> ON_LEASE")
        assert aircraft_now["version"] == aircraft_version + 1
