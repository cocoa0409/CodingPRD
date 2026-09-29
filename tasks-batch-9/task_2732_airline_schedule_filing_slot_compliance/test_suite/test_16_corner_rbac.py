"""Access-control breadth: role admission, identity and duty separation.

An allocation endpoint closed to everyone but the coordinator, an identity check
that must fire before any role verdict, a read open to all six roles with no
projection narrowing, and a transmit gate that compares people rather than
roles.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_slot_holding,
    assert_timestamp_equals,
    assign_aircraft,
    create_flight_leg,
    create_slot_holding,
    create_slot_holding_payload,
    make_filing_agent_headers,
    make_headers,
    make_network_planner_headers,
    make_partner_carrier_headers,
    queue_submission,
    read_holding,
    read_leg,
    read_submission,
    read_version,
    setup_domestic_rotation_base,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
    validate_version,
    COMPLIANCE_OFFICER_USER_ID,
    DEFAULT_CLOCK_UTC,
    FILING_AGENT_USER_ID,
    TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
COORDINATOR = TEST_USERS["slot_coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
AGENT = TEST_USERS["filing_agent_headers"]


# ─── RBAC 1: allocation belongs to the coordinator alone ──────────────────

def _coordinated_hub_awaiting_its_first_series():
    """A carrier that wants an `FRA` Monday series but may not mint it."""
    ref = setup_reference_data(("FRA",))
    ref["series_payload"] = create_slot_holding_payload(
        ref["stations"]["FRA"]["id"],
        ref["season"]["id"],
        ref["carrier"]["id"],
        movement_type="DEPARTURE",
        slot_time_utc="2026-11-02T08:00:00.000Z",
        days_of_week="1",
        series_weeks=5,
    )
    return ref


class TestAllocatingASlotSeriesIsForbiddenToEveryRoleButTheCoordinator:
    """The same allocation body sent by three different roles."""

    def test_the_carrier_naming_itself_is_still_refused_on_role(self):
        """The body names the planner's own carrier, so there is no ownership
        question left - the refusal has to be the role one, and the failed call
        must not leave a series behind.

        PRD §2.1: "If both headers are present but `X-User-Role` is not one of
        the six declared role names, or is a declared role that the target
        endpoint does not admit, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        PRD §4: "Record a slot series held at a fully coordinated airport as a
        movement type, slot time, day mask and week count."

        Design: Corner/rbac/allocating_a_slot_series_is_forbidden_to_every_role_but_the_coordinator
        """
        world = _coordinated_hub_awaiting_its_first_series()

        validate_error(
            api_client.create_slot_holding(world["series_payload"], world["planner"]),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            expected_status=403,
        )

        _, meta = validate_paginated(
            api_client.list_slot_holdings(
                COORDINATOR, params={"station_id": world["stations"]["FRA"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_the_reference_data_administrator_cannot_allocate_either(self):
        """`SystemAdmin` owns stations and seasons but not slots, and its
        refusal leaves the station just as empty.

        PRD §2.1: "A `SystemAdmin` administers reference data and the logical
        clock: carriers, stations, seasons and traffic rights, season
        transitions, carrier and authority suspensions, and clock advancement.
        It holds no planning, slot, compliance or filing power whatsoever."

        Design: Corner/rbac/allocating_a_slot_series_is_forbidden_to_every_role_but_the_coordinator
        """
        world = _coordinated_hub_awaiting_its_first_series()

        validate_error(
            api_client.create_slot_holding(world["series_payload"], ADMIN),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            expected_status=403,
        )

        _, meta = validate_paginated(
            api_client.list_slot_holdings(
                COORDINATOR, params={"station_id": world["stations"]["FRA"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_the_coordinator_sending_the_identical_body_is_accepted(self):
        """Only the acting role differs, and the same series is minted for the
        same carrier.

        PRD §2.1: "A `SlotCoordinator` is the independent airport slot
        coordinator. It allocates slot series, approves or denies exchanges and
        transfers, and runs the season's use-it-or-lose-it audit."

        PRD §3.5: "A new series is created in `holding_status` `HELD` with
        `planned_operations` equal to `series_weeks` multiplied by the number of
        digits in `days_of_week`"

        Design: Corner/rbac/allocating_a_slot_series_is_forbidden_to_every_role_but_the_coordinator
        """
        world = _coordinated_hub_awaiting_its_first_series()

        created = validate_success(
            api_client.create_slot_holding(world["series_payload"], COORDINATOR),
            expected_status=201,
        )
        assert_slot_holding(created)
        assert created["holding_status"] == "HELD"
        assert created["carrier_id"] == world["carrier"]["id"]
        assert created["planned_operations"] == 5


# ─── RBAC 2: identity is checked before the role verdict ──────────────────

def _one_held_series_to_probe():
    """A `HELD` `FRA` Monday series owned by the home carrier."""
    ref = setup_reference_data(("FRA",))
    ref["holding"] = create_slot_holding(
        ref["stations"]["FRA"]["id"],
        ref["season"]["id"],
        ref["carrier"]["id"],
        movement_type="DEPARTURE",
        slot_time_utc="2026-11-02T08:00:00.000Z",
        days_of_week="1",
        series_weeks=5,
    )
    return ref


def _assert_series_untouched(world):
    holding = read_holding(world["holding"]["id"], COORDINATOR)
    assert holding["holding_status"] == "HELD"
    assert holding["returned_reason"] is None
    assert holding["version"] == world["holding"]["version"]


class TestABlankIdentityHeaderIsUnauthenticatedBeforeAnyRoleCheck:
    """Three blank-header probes, two of them on a role-restricted write."""

    def test_a_blank_user_identifier_is_rejected_as_unauthenticated(self):
        """The role is the right one for the endpoint, so only the empty
        identity can explain a 401 - and nothing is returned.

        PRD §2.1: "If either header is absent, empty, or blank, the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else
        about the request is inspected."

        Design: Corner/rbac/a_blank_identity_header_is_unauthenticated_before_any_role_check_runs
        """
        world = _one_held_series_to_probe()

        validate_error(
            api_client.return_slot_holding(
                world["holding"]["id"],
                {"reason": "NOT_NEEDED"},
                make_headers("", "NetworkPlanner"),
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            expected_status=401,
        )
        _assert_series_untouched(world)

    def test_a_blank_role_never_leaks_the_role_verdict(self):
        """A blank role would also fail role admission, but authentication is
        the first band, so the answer is 401 and never 403.

        PRD §2.9: "Every request is evaluated against the rule bands below **in
        the order listed**, and the first band that produces an objection
        determines the response; no later band can mask an earlier one."

        PRD §2.9: "1. **Authentication.** Both headers present and non-blank,
        else `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/a_blank_identity_header_is_unauthenticated_before_any_role_check_runs
        """
        world = _one_held_series_to_probe()

        validate_error(
            api_client.return_slot_holding(
                world["holding"]["id"],
                {"reason": "NOT_NEEDED"},
                make_headers(world["carrier"]["id"], ""),
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            expected_status=401,
        )
        _assert_series_untouched(world)

    def test_the_check_fires_on_reads_as_well_as_on_writes(self):
        """Reads are not exempt, and the refused read returns an error envelope
        rather than any of the series' fields.

        PRD §2.1: "Every request to every endpoint - reads included - must carry
        two headers: `X-User-ID`, identifying the acting principal, and
        `X-User-Role`, naming the capacity in which it acts."

        Design: Corner/rbac/a_blank_identity_header_is_unauthenticated_before_any_role_check_runs
        """
        world = _one_held_series_to_probe()

        response = api_client.get_slot_holding(
            world["holding"]["id"], make_headers("", "")
        )
        validate_error(
            response, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401
        )
        assert set(response.json()["data"].keys()) == {"error_id", "message"}
        _assert_series_untouched(world)


# ─── RBAC 3: a read every role may make, identically ──────────────────────

def _one_grandfathered_series_and_six_readers():
    """A historic `HX` series plus the header set of all six roles."""
    ref = setup_reference_data(("FRA",), with_partner=True)
    ref["holding"] = create_slot_holding(
        ref["stations"]["FRA"]["id"],
        ref["season"]["id"],
        ref["carrier"]["id"],
        movement_type="DEPARTURE",
        slot_time_utc="2026-11-02T08:00:00.000Z",
        days_of_week="1",
        series_weeks=5,
        historic_precedence=True,
    )
    ref["readers"] = {
        "NetworkPlanner": make_network_planner_headers(ref["carrier"]["id"]),
        "PartnerCarrier": make_partner_carrier_headers(ref["partner"]["id"]),
        "SlotCoordinator": COORDINATOR,
        "ComplianceOfficer": OFFICER,
        "FilingAgent": AGENT,
        "SystemAdmin": ADMIN,
    }
    return ref


class TestReferenceReadsAreOpenToAllSixRolesWithAnIdenticalBody:
    """One `HX`-owned series read by six different roles in turn."""

    def test_no_role_receives_a_narrowed_or_refused_projection(self):
        """Ownership gates writes, not this read, so the counterparty airline
        and the filing agent get the same body the holder gets.

        PRD §4: "Read one slot series with both utilization variants and its
        at-risk flag."

        PRD §2.1: "Any mismatch in either case is `ERR_OWNERSHIP_MISMATCH` (HTTP
        403), and it applies to every write against a schedule version, a flight
        leg, a slot holding, or a slot transaction."

        Design: Corner/rbac/reference_reads_are_open_to_all_six_roles_with_an_identical_body
        """
        world = _one_grandfathered_series_and_six_readers()

        bodies = {}
        for role, headers in world["readers"].items():
            response = api_client.get_slot_holding(world["holding"]["id"], headers)
            data = validate_success(response)
            assert response.json()["response_type"] == "object", role
            bodies[role] = data

        reference = bodies["NetworkPlanner"]
        for role, data in bodies.items():
            assert data == reference, role

    def test_the_shared_body_is_the_holders_own_unmodified_row(self):
        """Six reads move nothing: the grandfather flag, both utilisation
        variants and the row's `version` are exactly as allocated.

        PRD §3.5: "A new series is created in `holding_status` `HELD` with
        `planned_operations` equal to `series_weeks` multiplied by the number of
        digits in `days_of_week`, `attached_operations` at 0,
        `credited_operations` at 0, both `utilization_pct` and
        `utilization_pct_as_filed` at 0.00, `at_risk_of_loss` false"

        Design: Corner/rbac/reference_reads_are_open_to_all_six_roles_with_an_identical_body
        """
        world = _one_grandfathered_series_and_six_readers()

        for headers in world["readers"].values():
            validate_success(
                api_client.get_slot_holding(world["holding"]["id"], headers)
            )

        holding = read_holding(world["holding"]["id"], AGENT)
        assert holding["id"] == world["holding"]["id"]
        assert holding["carrier_id"] == world["carrier"]["id"]
        assert holding["historic_precedence"] is True
        assert holding["holding_status"] == "HELD"
        assert holding["planned_operations"] == 5
        assert holding["attached_operations"] == 0
        assert holding["credited_operations"] == 0
        assert holding["utilization_pct"] == 0.00
        assert holding["utilization_pct_as_filed"] == 0.00
        assert holding["at_risk_of_loss"] is False
        assert holding["version"] == 1


# ─── RBAC 4: the transmit gate compares people, not roles ─────────────────

def _validated_plan_with_one_queued_filing():
    """Two slot-free legs validated by `usr-comp-1` and queued by `usr-file-1`."""
    ref = setup_domestic_rotation_base(version_label="W26-S1")
    muc, txl = ref["stations"]["MUC"]["id"], ref["stations"]["TXL"]["id"]

    legs = []
    for flight_number, origin, dest, dep, arr in (
        ("HX320", muc, txl, "08:00", "09:00"),
        ("HX321", txl, muc, "10:00", "11:00"),
    ):
        leg = create_flight_leg(
            ref["carrier"]["id"],
            ref["version"]["id"],
            origin,
            dest,
            f"2026-11-03T{dep}:00.000Z",
            f"2026-11-03T{arr}:00.000Z",
            flight_number=flight_number,
        )
        legs.append(
            assign_aircraft(ref["carrier"]["id"], leg["id"], ref["aircraft"]["id"])
        )

    ref["legs"] = legs
    ref["version"] = validate_version(ref["version"]["id"], OFFICER)
    ref["submission"] = queue_submission(
        ref["version"]["id"],
        change_window="STANDARD",
        distribution_system="OAG",
        headers=AGENT,
    )
    return ref


class TestTheOfficerWhoValidatedASchedulePlanCannotTransmitIt:
    """One queued filing offered to two different `FilingAgent` identities."""

    def test_validation_stamps_the_person_the_transmit_gate_will_compare(self):
        """Before any transmit: the officer's identity is on the version, the
        filing is priced and waiting, and nothing has been charged.

        PRD §2.1: "When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an
        opaque operator identifier; the server records it as
        `validated_by_user_id` on the schedule version it validates, and that
        stored value is what later locks the same person out of transmitting."

        PRD §3.8: "Second, a raw amount equal to that count multiplied by 4225
        cents per leg. Third, a volume surcharge chosen by the count: at 5 legs
        or fewer the surcharge is 0.00 percent"

        Design: Corner/rbac/the_officer_who_validated_a_schedule_cannot_be_the_person_who_transmits_it
        """
        world = _validated_plan_with_one_queued_filing()

        version = read_version(world["version"]["id"], OFFICER)
        assert version["filing_status"] == "VALIDATED"
        assert version["validated_by_user_id"] == COMPLIANCE_OFFICER_USER_ID
        assert version["filing_charge_accrued_cents"] == 0

        submission = read_submission(world["submission"]["id"], AGENT)
        assert submission["status"] == "QUEUED"
        assert submission["changed_leg_count"] == 2
        assert submission["base_charge_subtotal_cents"] == 8450
        assert submission["expedite_fee_cents"] == 0
        assert submission["total_charge_cents"] == 8450

    def test_the_validating_person_is_refused_even_wearing_the_filing_role(self):
        """The acting role is the permitted `FilingAgent`, so only the identity
        can explain the refusal - and the refusal costs nothing.

        PRD §2.8: "Transmitting a filing submission is refused when the acting
        `X-User-ID` equals the `validated_by_user_id` stored on the submission's
        schedule version at validation time."

        PRD §3.8: "The acting `X-User-ID` must differ from the version's
        `validated_by_user_id`, or it fails with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/the_officer_who_validated_a_schedule_cannot_be_the_person_who_transmits_it
        """
        world = _validated_plan_with_one_queued_filing()

        validate_error(
            api_client.transmit_filing_submission(
                world["submission"]["id"],
                make_filing_agent_headers(COMPLIANCE_OFFICER_USER_ID),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )

        submission = read_submission(world["submission"]["id"], AGENT)
        assert submission["status"] == "QUEUED"
        assert submission["transmitted_by_user_id"] is None
        assert submission["transmitted_at_utc"] is None

        version = read_version(world["version"]["id"], OFFICER)
        assert version["filing_status"] == "VALIDATED"
        assert version["filing_charge_accrued_cents"] == 0

    def test_a_different_agent_sends_the_identical_request_successfully(self):
        """A second holder of the same role clears the gate, and the whole
        transmission cascade lands: the charge accrues and the legs are filed.

        PRD §2.8: "Both are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403),
        and in both cases a second user holding the same role but a different
        `X-User-ID` succeeds on the byte-identical request."

        PRD §3.8: "A successful transmission moves the submission `QUEUED →
        TRANSMITTED`, stamps `transmitted_by_user_id` with the acting user and
        `transmitted_at_utc` with the logical clock, adds `total_charge_cents` to
        the version's `filing_charge_accrued_cents`, moves the version
        `VALIDATED → FILED`, and moves every one of that version's `SLOT_BACKED`
        legs to `FILED`."

        Design: Corner/rbac/the_officer_who_validated_a_schedule_cannot_be_the_person_who_transmits_it
        """
        world = _validated_plan_with_one_queued_filing()
        validate_error(
            api_client.transmit_filing_submission(
                world["submission"]["id"],
                make_filing_agent_headers(COMPLIANCE_OFFICER_USER_ID),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        transmitted = validate_success(
            api_client.transmit_filing_submission(world["submission"]["id"], AGENT)
        )
        assert transmitted["status"] == "TRANSMITTED"
        assert transmitted["transmitted_by_user_id"] == FILING_AGENT_USER_ID
        assert_timestamp_equals(
            transmitted["transmitted_at_utc"],
            DEFAULT_CLOCK_UTC,
            "transmitted_at_utc",
        )

        version = read_version(world["version"]["id"], OFFICER)
        assert version["filing_status"] == "FILED"
        assert version["filing_charge_accrued_cents"] == 8450

        for leg in world["legs"]:
            assert read_leg(leg["id"], OFFICER)["status"] == "FILED"
