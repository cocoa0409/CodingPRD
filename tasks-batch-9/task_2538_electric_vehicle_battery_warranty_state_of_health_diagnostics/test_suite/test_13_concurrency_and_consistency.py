"""The three version tokens, and the immediacy of every derivation behind them.

Each guard is staled by a *different* writer — a gateway ingest, an
adjudication, an owner's refusal — and each refusal must leave the world
exactly where it found it, so that the byte-identical retry carrying the fresh
token succeeds. The last test reads the whole derived closure out of a single
create response.
"""

import pytest

from test_helpers import (
    ADJUDICATOR_1_ID,
    ApiErrorId,
    TEST_USERS,
    add_assessment,
    add_sibling_vehicle,
    adjudicate_payload,
    assert_same_instant,
    consent_payload,
    create_campaign,
    decide_consent,
    dispute_payload,
    list_assessments,
    list_campaign_consents,
    list_claim_disputes,
    list_modules,
    make_adjudicator_headers,
    make_gateway_headers,
    read_assessment,
    read_campaign,
    read_claim,
    read_consent,
    read_pack,
    read_vehicle,
    read_vehicle_version,
    release_campaign,
    setup_base_world,
    setup_submitted_claim_world,
    snapshot_payload,
    telematics_assessment_payload,
    validate_error,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["program_admin_headers"]

# Three fresh, identical, wholly plausible rows: 56.000 kWh against a nominal
# 80.000, so every window drawn from them retains exactly 70.00 %.
WINDOW_ROWS = [
    ("2026-07-20T00:00:00Z", 71000, 56.000),
    ("2026-07-22T00:00:00Z", 71200, 56.000),
    ("2026-07-24T00:00:00Z", 71400, 56.000),
]


class TestVehicleVersionStaledByAnIngest:
    """The invisible writer is the gateway, and the fourth row joins the window."""

    def test_the_stale_assessment_is_refused_and_writes_no_module_status(self, api):
        """412 before the module write, and the retry sees a four-row window.

        PRD 2.6: "Creating a state-of-health assessment requires
        `expected_vehicle_version` carrying the client's last observed `version` of the
        target `Vehicle`. If it does not equal that vehicle's current `version`, the
        create is rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412)." / "including
        one produced after a telematics ingest moved the vehicle's `odometer_miles`."

        PRD 2.1: "`version`, an integer that starts at 1 and increments by one on every
        mutation of that record. Recomputing a derived field counts as a mutation".

        PRD 3.2: "Only a `VALID` snapshot moves anything else. When one is accepted, the
        vehicle's `odometer_miles` is raised to whichever is greater, its existing value
        or the new row's `odometer_miles`; it is never lowered."

        PRD 2.7: "8. `expected_vehicle_version` on assessment creation —
        `ERR_STALE_VEHICLE_VERSION`."

        PRD 3.3: "both are written through to the pack's modules — setting those
        children to `FAULTED` and `DEGRADED` respectively — *before* any retention
        arithmetic runs."

        PRD 3.3: "When the window is smaller than that — three or four rows — no
        trimming happens and all of the values are averaged."

        Design: Corner/cross_cutting_complexity_layers/assessment_create_rejects_a_vehicle_version_stale_by_one_snapshot
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000601"},
            pack_overrides={"serial_number": "PK-C401"},
            snapshots=WINDOW_ROWS,
        )
        vehicle_id, pack_id = world["vehicle_id"], world["pack_id"]
        technician_id = world["technician_id"]
        stale_version = read_vehicle_version(api, vehicle_id, technician_id)

        # A writer the technician never sees: one more accepted row, one more mutation.
        fourth = validate_success(
            api.ingest_snapshot(
                vehicle_id,
                snapshot_payload("2026-07-26T00:00:00Z", 71600, 56.000),
                make_gateway_headers(),
            ),
            expected_status=201,
        )
        assert fourth["validity_flag"] == "VALID"
        fresh_version = read_vehicle_version(api, vehicle_id, technician_id)
        assert fresh_version == stale_version + 1

        stale_request = telematics_assessment_payload(
            vehicle_id,
            pack_id,
            technician_id,
            stale_version,
            module_fault_positions=[3, 7],
        )
        validate_error(
            api.create_assessment(stale_request, world["tech_headers"]),
            ApiErrorId.ERR_STALE_VEHICLE_VERSION.value,
            expected_status=412,
        )

        # The guard sits ahead of the module write, so the roster is untouched.
        modules, _ = list_modules(api, pack_id, limit=100)
        assert [row["status"] for row in modules] == ["HEALTHY"] * 16
        assert read_pack(api, pack_id)["faulted_module_count"] == 0

        # The same request, differing only in the token it carries.
        accepted = validate_success(
            api.create_assessment(
                telematics_assessment_payload(
                    vehicle_id,
                    pack_id,
                    technician_id,
                    fresh_version,
                    module_fault_positions=[3, 7],
                ),
                world["tech_headers"],
            ),
            expected_status=201,
        )
        assert accepted["diagnostic_validity"] == "VALID"
        # The row that staled the token is itself the newest member of the window.
        assert accepted["window_snapshot_count"] == 4
        assert accepted["assessed_odometer_miles"] == 71600
        assert accepted["estimated_capacity_kwh"] == pytest.approx(56.000, abs=0.001)
        assert accepted["retention_pct"] == pytest.approx(70.00, abs=0.01)

        _, meta = list_assessments(api, vehicle_id=vehicle_id)
        assert meta["total_count"] == 1


class TestClaimVersionStaledByTheAdjudication:
    """The very act that made the claim disputable is the act that staled the read."""

    def test_the_pre_adjudication_view_is_a_412_and_never_a_disputability_409(self, api):
        """Rung 9 answers first, then the refreshed filing freezes the OEM basis.

        PRD 2.6: "Filing a capacity dispute requires `expected_claim_version` carrying
        the client's last observed `version` of the target `WarrantyClaim`. A mismatch
        with the claim's current `version` is rejected with `ERR_STALE_CLAIM_VERSION`
        (HTTP 412)."

        PRD 2.7: "9. `expected_claim_version` on dispute filing —
        `ERR_STALE_CLAIM_VERSION`." / "21. Claim status among `APPROVED_MODULE`,
        `APPROVED_PACK`, `APPROVED_SOFTWARE`, `DENIED` and `FULFILLED` for a dispute
        filing — `ERR_CLAIM_NOT_DISPUTABLE`."

        PRD 3.9: "a claim whose `version` has moved on since the owner read it — because
        an earlier dispute filing bumped it, for instance — must be re-read before the
        filing can succeed."

        PRD 3.9: "An accepted filing creates the dispute in `LAB_ASSIGNED` with
        `retest_count` 0, and snapshots two numbers from the claim's backing assessment:
        `nominal_basis_kwh`, which becomes the denominator for every later lab
        computation, and `retention_pct`, stored as `oem_retention_pct`, which is the
        figure the lab's result will be measured against." / "`lab_measured_capacity_kwh`,
        `lab_retention_pct`, `deviation_pct`, `resolution_note` and `resolved_by_user_id`
        all start null." / "The filing also raises the claim's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/dispute_create_rejects_a_claim_version_staled_by_the_adjudication
        """
        world = setup_submitted_claim_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000611"},
            pack_overrides={"serial_number": "PK-C411"},
            snapshots=WINDOW_ROWS,
        )
        claim_id = world["claim_id"]
        assert world["claim"]["adjudication_status"] == "SUBMITTED"

        # The owner reads while the claim is still under adjudication.
        stale_claim_version = read_claim(api, claim_id, world["owner_headers"])["version"]

        adjudicated = validate_success(
            api.adjudicate_claim(
                claim_id,
                adjudicate_payload("MODULE_REPLACEMENT"),
                make_adjudicator_headers(ADJUDICATOR_1_ID),
            )
        )
        assert adjudicated["adjudication_status"] == "APPROVED_MODULE"
        fresh_claim_version = adjudicated["version"]
        assert fresh_claim_version == stale_claim_version + 1

        # A SUBMITTED claim would have been an ERR_CLAIM_NOT_DISPUTABLE at rung 21, but
        # the claim is APPROVED_MODULE now: only the stale token can refuse this.
        validate_error(
            api.create_dispute(
                dispute_payload(
                    claim_id,
                    stale_claim_version,
                    lab_name="Statewide Cell Lab",
                    owner_statement="stale read",
                ),
                world["owner_headers"],
            ),
            ApiErrorId.ERR_STALE_CLAIM_VERSION.value,
            expected_status=412,
        )
        assert read_claim(api, claim_id)["version"] == fresh_claim_version

        filed = validate_success(
            api.create_dispute(
                dispute_payload(
                    claim_id,
                    fresh_claim_version,
                    lab_name="Statewide Cell Lab",
                    owner_statement="fresh read",
                ),
                world["owner_headers"],
            ),
            expected_status=201,
        )
        assert filed["dispute_status"] == "LAB_ASSIGNED"
        assert filed["nominal_basis_kwh"] == pytest.approx(80.000, abs=0.001)
        assert filed["oem_retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert filed["retest_count"] == 0
        assert filed["lab_measured_capacity_kwh"] is None
        assert filed["lab_retention_pct"] is None
        assert filed["deviation_pct"] is None
        assert filed["resolution_note"] is None
        assert filed["resolved_by_user_id"] is None

        _, meta = list_claim_disputes(api, claim_id)
        assert meta["total_count"] == 1
        # The accepted filing is itself a mutation of the claim.
        assert read_claim(api, claim_id)["version"] == fresh_claim_version + 1


class TestCampaignVersionStaledByAnOwnersRefusal:
    """Two eligible vehicles, so the refusal shrinks the open set without closing it."""

    def test_the_resolicitation_needs_the_version_the_decline_left_behind(self, api):
        """412 ahead of both the release check and the duplicate check, then round two.

        PRD 2.6: "Creating a remediation consent requires `expected_campaign_version`
        carrying the client's last observed `version` of the target
        `RemediationCampaign`. A mismatch with the campaign's current `version` is
        rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)."

        PRD 2.7: "10. `expected_campaign_version` on consent creation —
        `ERR_STALE_CAMPAIGN_VERSION`." / "26. Campaign status `LIMITED_RELEASE` or
        `FIELD_RELEASE` for consent solicitation — `ERR_CAMPAIGN_NOT_RELEASED`." / "64. No
        duplicate active consent for the campaign-and-vehicle pair, and a well-formed
        supersession reference — `ERR_DUPLICATE_ACTIVE_CONSENT`."

        PRD 3.8: "both create one `PENDING` consent per eligible vehicle in ascending
        vehicle `created_at` order, then set both `solicited_consent_count` and
        `open_consent_count` to the number of consents created."

        PRD 3.8: "A `DECLINE` moves `consent_status` to `DECLINED`, which is terminal,
        and lowers the campaign's `open_consent_count` by one."

        PRD 3.8: "A campaign in `LIMITED_RELEASE` or `FIELD_RELEASE` auto-transitions to
        `CLOSED`, freezing `applied_count`, when and only when `solicited_consent_count`
        is at least one and `open_consent_count` is zero".

        PRD 3.8: "An accepted solicitation creates the consent in `PENDING`, sets
        `expires_at` to its own `created_at` plus fourteen days, and sets
        `solicitation_round` to the superseded consent's `solicitation_round` plus one
        when one was named and to 1 otherwise. It raises the campaign's
        `solicited_consent_count` and `open_consent_count` each by one, and raises the
        campaign's `version` by one."

        PRD 3.8: "`solicited_consent_count` is a lifetime total that never falls."

        Design: Corner/cross_cutting_complexity_layers/consent_resolicitation_rejects_a_stale_campaign_version
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000621"},
            pack_overrides={"serial_number": "PK-C421"},
            snapshots=None,
        )
        sibling = add_sibling_vehicle(
            api, world, vin="5YJ3E1EA7KF000622", serial_number="PK-C422"
        )
        first_vehicle_id = world["vehicle_id"]

        campaign = create_campaign(
            api,
            campaign_code="CMP-OCC-01",
            target_defect="CHARGING",
            software_version="bms-4.2.1",
            applies_to_pack_type="ANY",
            applies_to_model_code="MX-90",
        )
        campaign_id = campaign["id"]
        released = release_campaign(api, campaign_id, "FIELD")
        assert released["status"] == "FIELD_RELEASE"
        assert released["solicited_consent_count"] == 2
        assert released["open_consent_count"] == 2

        rows, _ = list_campaign_consents(api, campaign_id, vehicle_id=first_vehicle_id)
        first_consent = rows[0]
        assert first_consent["consent_status"] == "PENDING"
        assert first_consent["solicitation_round"] == 1

        stale_campaign_version = read_campaign(api, campaign_id)["version"]

        declined = decide_consent(api, first_consent["id"], first_vehicle_id, "DECLINE")
        assert declined["consent_status"] == "DECLINED"

        after_decline = read_campaign(api, campaign_id)
        assert after_decline["open_consent_count"] == 1
        assert after_decline["solicited_consent_count"] == 2
        # The sibling's PENDING consent is what keeps the open set non-empty.
        assert after_decline["status"] == "FIELD_RELEASE"
        assert sibling["vehicle_id"] != first_vehicle_id

        # The predecessor is DECLINED, so the supersession reference is well formed and
        # the pair holds nothing active: only the token is wrong.
        validate_error(
            api.create_consent(
                consent_payload(
                    campaign_id,
                    first_vehicle_id,
                    stale_campaign_version,
                    superseded_consent_id=first_consent["id"],
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_STALE_CAMPAIGN_VERSION.value,
            expected_status=412,
        )

        fresh_campaign_version = read_campaign(api, campaign_id)["version"]
        assert fresh_campaign_version != stale_campaign_version

        resolicited = validate_success(
            api.create_consent(
                consent_payload(
                    campaign_id,
                    first_vehicle_id,
                    fresh_campaign_version,
                    superseded_consent_id=first_consent["id"],
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert resolicited["consent_status"] == "PENDING"
        assert resolicited["solicitation_round"] == 2
        assert resolicited["superseded_consent_id"] == first_consent["id"]
        assert resolicited["decision_at"] is None
        assert resolicited["applied_at"] is None
        assert_same_instant(
            resolicited["expires_at"], "2026-08-15T00:00:00Z", "consent.expires_at"
        )

        reopened = read_campaign(api, campaign_id)
        assert reopened["solicited_consent_count"] == 3
        assert reopened["open_consent_count"] == 2
        assert reopened["applied_count"] == 0
        assert read_consent(api, first_consent["id"])["consent_status"] == "DECLINED"


class TestAssessmentCreateIsAlreadyFullyDerived:
    """One create response, and then three reads that need no settling step."""

    def test_the_201_body_carries_the_whole_closure_and_the_siblings_are_visible(
        self, api
    ):
        """Nine derived fields in the body; supersession, roster and version next door.

        PRD 3.3: "The window's size is recorded as `window_snapshot_count`, and the
        newest row in it supplies both `assessed_odometer_miles` and the assessment's own
        `max_cell_delta_mv`".

        PRD 3.3: "For `TELEMATICS_FLEET`, the denominator `nominal_basis_kwh` is the
        pack's full beginning-of-life `nominal_capacity_kwh`; faulted modules are *not*
        excluded from it." / "When the window is smaller than that — three or four rows —
        no trimming happens and all of the values are averaged."

        PRD 3.3: "`retention_pct` is `estimated_capacity_kwh` divided by
        `nominal_basis_kwh`, multiplied by one hundred, rounded half up to two decimals."

        PRD 3.3: "`elapsed_months` is the whole number of months from the vehicle's
        `in_service_date` to the current logical clock, floored on the day of month" /
        "When a row is selected, `coverage_position` reads `IN_COVERAGE` and
        `applicable_min_retention_pct` takes that row's `min_retention_pct`."

        PRD 3.3: "`qualifies_for_claim` is true when `diagnostic_validity` is `VALID`,
        `coverage_position` is either `IN_COVERAGE` or `GOODWILL_BAND`, and
        `retention_pct` is at or below `applicable_min_retention_pct` — retention exactly
        at the threshold qualifies."

        PRD 3.3: "every prior assessment on the same `vehicle_id` has `superseded` set to
        true ... The vehicle's `version` increments by one as part of the same operation".

        PRD 3.1: "A module's `status` later reads `DEGRADED` when an assessment names its
        position among the degraded ones, `FAULTED` when an assessment names it among the
        faulted ones ... `faulted_module_count` is the count of its children in
        `FAULTED`."

        Design: Corner/consistency_model/assessment_response_already_carries_every_derived_field
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000631"},
            pack_overrides={"serial_number": "PK-C431"},
            snapshots=WINDOW_ROWS,
        )
        vehicle_id, pack_id = world["vehicle_id"], world["pack_id"]
        first = add_assessment(api, world)
        assert first["superseded"] is False

        second_version = read_vehicle_version(api, vehicle_id, world["technician_id"])

        created = validate_success(
            api.create_assessment(
                telematics_assessment_payload(
                    vehicle_id,
                    pack_id,
                    world["technician_id"],
                    second_version,
                    module_fault_positions=[3, 7],
                    module_degraded_positions=[4],
                ),
                world["tech_headers"],
            ),
            expected_status=201,
        )

        # Everything below is read out of the create response itself: no second call,
        # no 202, no job identifier, no retry.
        assert created["diagnostic_validity"] == "VALID"
        assert created["window_snapshot_count"] == 3
        assert created["assessed_odometer_miles"] == 71400
        assert created["max_cell_delta_mv"] == 40
        assert created["nominal_basis_kwh"] == pytest.approx(80.000, abs=0.001)
        assert created["estimated_capacity_kwh"] == pytest.approx(56.000, abs=0.001)
        assert created["retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert created["elapsed_months"] == 76
        assert created["coverage_position"] == "IN_COVERAGE"
        assert created["applicable_min_retention_pct"] == pytest.approx(70.0, abs=0.01)
        assert created["qualifies_for_claim"] is True
        assert created["superseded"] is False

        # The immediately following read of the older diagnostic already reads superseded.
        assert read_assessment(api, first["id"])["superseded"] is True

        pack = read_pack(api, pack_id)
        assert pack["faulted_module_count"] == 2
        modules, _ = list_modules(api, pack_id, limit=100)
        by_position = {row["position_index"]: row for row in modules}
        assert by_position[3]["status"] == "FAULTED"
        assert by_position[7]["status"] == "FAULTED"
        # A degraded module is a status, not a fault: it is deliberately uncounted.
        assert by_position[4]["status"] == "DEGRADED"

        vehicle = read_vehicle(api, vehicle_id)
        assert vehicle["version"] == second_version + 1
        assert vehicle["odometer_miles"] == 71400
