"""Who may act, and who may not, at a permitted treatment facility.

Three kinds of boundary meet here. Identity itself comes first: a caller with no
headers is nobody. Then the seven declared capacities partition the work of the
dock, the laboratory, the treatment floor and the compliance office. Finally two
duties are split on the acting person rather than on the capacity, so the chemist
who ran the laboratory sample and the operator who burned the batch must both
hand the signature to somebody else.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    api_client,
    assert_assurance,
    assert_cents,
    assert_unit_state,
    factories,
    fixtures,
    make_generator_headers,
    make_headers,
)
from test_helpers.test_users import (
    CHEMIST_2_USER_ID,
    COMPLIANCE_MANAGER_USER_ID,
    OPERATOR_USER_ID,
)


def _two_generators_and_a_shipment_offered_by_the_first() -> fixtures.Scenario:
    """One facility, two registered generators, and a manifest offered by the first.

    The second generator has nothing of its own on the dock, which is what makes
    the row-level boundary visible.
    """
    fixtures.set_clock()
    facility = fixtures.create_facility()
    generator_a = fixtures.create_generator()
    generator_b = fixtures.create_generator(
        epa_id="TXR000777888", name="Delta Plating"
    )
    profile = fixtures.create_approved_profile(generator_a["id"], facility["id"])
    manifest = fixtures.create_manifest(
        generator_a["id"],
        facility["id"],
        lines=[factories.manifest_line_payload(profile["id"], 1000.0, 4, False)],
    )
    return fixtures.Scenario(
        facility=facility,
        generator_a=generator_a,
        generator_b=generator_b,
        profile=profile,
        manifest=manifest,
    )


def _profile_awaiting_a_decision_after_a_run_by_the_first_chemist() -> fixtures.Scenario:
    """A profile in SAMPLE_PASSED whose only laboratory run was recorded by the
    first chemist, so that chemist is now the disqualified signer."""
    fixtures.set_clock()
    facility = fixtures.create_facility()
    generator = fixtures.create_generator()
    profile = fixtures.create_draft_profile(generator["id"], facility["id"])
    submitted = fixtures.submit_profile(profile["id"], generator["id"])
    sample = fixtures.record_sample(profile["id"], submitted["version"])
    return fixtures.Scenario(
        facility=facility,
        generator=generator,
        profile=fixtures.read_profile(profile["id"]),
        sample=sample,
    )


class TestIdentityAndRolePartitioning:
    def test_facility_registration_without_identity_headers_is_unauthenticated(self):
        """Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts.
        A request that omits either header, or that supplies a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).
        1. **Authentication.** `X-User-ID` and `X-User-Role` are present and well formed — `ERR_UNAUTHENTICATED` (401). Applies to every endpoint except the clock-control capability.
        All validations are evaluated in ascending priority order and **the first violated rule wins**; no later rule may mask an earlier one, and no earlier rule may be skipped because a later one would also fail.

        Design: Corner/rbac/request_missing_x_user_headers_unauthenticated
        """
        fixtures.set_clock()

        anonymous = api_client.create_facility(
            factories.facility_payload(), NO_AUTH_HEADERS
        )

        validate_error(anonymous, "ERR_UNAUTHENTICATED")
        _, meta = validate_paginated(api_client.list_facilities(TEST_USERS["admin"]))
        assert meta["total_count"] == 0, "an unauthenticated call must write nothing"

    def test_treatment_operator_may_not_register_a_facility(self):
        """A value of `X-User-Role` that is not one of these seven, or that is one of the seven but is not authorised for the endpoint being called, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).
        `PlatformAdmin` is the registry operator. It registers facilities, generators and permitted storage units, reads everything, and signs nothing.

        Design: Corner/rbac/treatment_operator_creating_a_facility_unauthorized
        """
        fixtures.set_clock()

        refused = api_client.create_facility(
            factories.facility_payload(), TEST_USERS["operator"]
        )

        validate_error(refused, "ERR_ROLE_NOT_PERMITTED")
        _, meta = validate_paginated(api_client.list_facilities(TEST_USERS["admin"]))
        assert meta["total_count"] == 0

        validate_success(
            api_client.create_facility(
                factories.facility_payload(), TEST_USERS["admin"]
            ),
            expected_status=201,
        )

    def test_generator_may_not_read_another_generators_manifest(self):
        """The seventh role is entity-backed.
        A `Generator` caller may therefore address only waste profiles and manifests whose `generator_id` equals its own `X-User-ID`, together with the sub-resources reachable from them (a profile's samples, a profile's manifest lines, and a manifest's lines) and its own generator record and reliability score.
        Any attempt by a `Generator` caller to address a row belonging to another generator is rejected with `ERR_GENERATOR_SCOPE_VIOLATION` (HTTP 403).
        3. **Generator scope.** A caller acting as `Generator` addresses only rows whose `generator_id` equals `X-User-ID`, including waste profiles, manifests and their sub-resources — `ERR_GENERATOR_SCOPE_VIOLATION` (403). Applies to every endpoint a `Generator` can reach.

        Design: Corner/rbac/generator_reading_another_generators_manifest_forbidden
        """
        scenario = _two_generators_and_a_shipment_offered_by_the_first()

        intruder = api_client.get_manifest(
            scenario.manifest["id"], make_generator_headers(scenario.generator_b["id"])
        )

        validate_error(intruder, "ERR_GENERATOR_SCOPE_VIOLATION")

        owner_view = validate_success(
            api_client.get_manifest(
                scenario.manifest["id"],
                make_generator_headers(scenario.generator_a["id"]),
            )
        )
        assert owner_view["id"] == scenario.manifest["id"]
        assert owner_view["generator_id"] == scenario.generator_a["id"]

        _, meta = validate_paginated(
            api_client.list_manifests(
                make_generator_headers(scenario.generator_b["id"])
            )
        )
        assert meta["total_count"] == 0

    def test_receiving_clerk_may_not_schedule_the_treatment_of_the_drum_it_sealed(self):
        """`TreatmentOperator` works the treatment floor: it schedules and runs batches, empties treated containers, and performs repair attempts.
        `ReceivingClerk` works the receiving dock: manifest receipt, manifest certification, container creation, and container custody moves.
        A value of `X-User-Role` that is not one of these seven, or that is one of the seven but is not authorised for the endpoint being called, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).
        Staging is not a caller-driven custody request at all: it happens as a side effect of batch scheduling, advancing each listed container from `SEALED` to `STAGED`, setting its `treatment_batch_id` to the new batch, and requiring the container to be `COMPLIANT` — a container in any other condition makes the batch creation an invalid state.

        Design: Corner/rbac/receiving_clerk_scheduling_a_treatment_batch_unauthorized
        """
        scenario = fixtures.setup_sealed_container(net_weight_kg=200.0)
        schedule = factories.treatment_batch_payload(
            scenario.facility["id"],
            scenario.unit["id"],
            [scenario.container["id"]],
            treatment_method="INCINERATION",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-01T12:00:00Z",
        )

        refused = api_client.create_treatment_batch(schedule, TEST_USERS["clerk"])

        validate_error(refused, "ERR_ROLE_NOT_PERMITTED")
        assert fixtures.read_container(scenario.container["id"])["custody_state"] == "SEALED"
        assert_unit_state(fixtures.read_unit(scenario.unit["id"]), reserved_kg=0.0)
        _, meta = validate_paginated(
            api_client.list_treatment_batches(
                TEST_USERS["operator"], params={"facility_id": scenario.facility["id"]}
            )
        )
        assert meta["total_count"] == 0

        scheduled = validate_success(
            api_client.create_treatment_batch(schedule, TEST_USERS["operator"]),
            expected_status=201,
        )
        staged = fixtures.read_container(scenario.container["id"])
        assert staged["custody_state"] == "STAGED"
        assert staged["treatment_batch_id"] == scheduled["id"]


class TestSeparationOfDutiesOnTheActingUser:
    def test_the_chemist_who_ran_the_sample_cannot_sign_the_same_approval(self):
        """Two duties are additionally segregated **on the user identifier, not on the role**.
        The `X-User-ID` that recorded a profile's most recent verification sample may not sign that profile's approval decision, even though both actions are performed by a `WasteApprovalChemist`.
        Approval is defined only from `SAMPLE_PASSED` and carries three preconditions, all of which must hold: the acting `X-User-ID` must differ from the `recorded_by_user_id` of the profile's most recent sample — that is, the last sample when the profile's samples are ordered by `created_at` ascending — failing which the request is refused with `ERR_SEGREGATION_OF_DUTIES`; the owning generator must be `ACTIVE`, failing which `ERR_GENERATOR_SUSPENDED` is returned; and the method being approved must appear in the `permitted_methods` of the facility named by the profile's `facility_id`, failing which `ERR_METHOD_NOT_PERMITTED` is returned.
        On approval the profile moves to `APPROVED`, `approved_at` is stamped from the clock, `approved_by_user_id` records the signing chemist, `approved_treatment_method` is locked in from the body, and `recertification_due_at` is set to `approved_at` advanced by `recertification_months` calendar months.

        Design: Corner/rbac/sample_recorder_cannot_sign_the_same_profiles_decision_forbidden
        """
        scenario = _profile_awaiting_a_decision_after_a_run_by_the_first_chemist()
        assert scenario.profile["status"] == "SAMPLE_PASSED"
        decision = factories.profile_decision_payload("APPROVE", "INCINERATION")

        self_signed = api_client.decide_waste_profile(
            scenario.profile["id"], decision, TEST_USERS["chemist"]
        )

        validate_error(self_signed, "ERR_SEGREGATION_OF_DUTIES")
        untouched = fixtures.read_profile(scenario.profile["id"])
        assert untouched["status"] == "SAMPLE_PASSED"
        assert untouched["approved_at"] is None

        approved = validate_success(
            api_client.decide_waste_profile(
                scenario.profile["id"], decision, TEST_USERS["chemist_2"]
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == CHEMIST_2_USER_ID
        assert approved["approved_treatment_method"] == "INCINERATION"
        assert approved["recertification_due_at"].startswith("2027-08-01"), (
            "twelve calendar months after an approval stamped 2026-08-01"
        )

    def test_the_operator_who_completed_the_batch_cannot_sign_its_own_verification(self):
        """Likewise, the `X-User-ID` that completed a treatment batch (acting as `TreatmentOperator`) may not sign that batch's land-disposal-restriction verification (acting as `ComplianceManager`).
        Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
        Its one precondition is segregation of duties: the acting `X-User-ID` must differ from `completed_by_user_id`, failing which `ERR_SEGREGATION_OF_DUTIES` is returned.
        When that family is `NONE`, `ldr_standard_ppm` stays null and the result is a pass.
        A pass sets `ldr_result` to `PASS`, records `verified_by_user_id`, and advances the batch from `TREATED` to the terminal `VERIFIED`; the batch leaves the unit's `reserved_kg` and the facility's `active_treatment_liability_cents`.

        Design: Corner/rbac/batch_completer_cannot_sign_its_own_ldr_verification_forbidden
        """
        scenario = fixtures.setup_treated_batch(
            net_weight_kg=200.0, residue_mass_kg=150.0, residue_constituent_ppm=400.0
        )
        assert scenario.batch["completed_by_user_id"] == OPERATOR_USER_ID
        verification = factories.ldr_verification_payload(400.0)

        dual_hatted = api_client.verify_batch_ldr(
            scenario.batch["id"],
            verification,
            make_headers(OPERATOR_USER_ID, "ComplianceManager"),
        )

        validate_error(dual_hatted, "ERR_SEGREGATION_OF_DUTIES")
        held_back = fixtures.read_batch(scenario.batch["id"])
        assert held_back["status"] == "TREATED"
        assert held_back["ldr_result"] == "PENDING"

        verified = validate_success(
            api_client.verify_batch_ldr(
                scenario.batch["id"], verification, TEST_USERS["compliance_manager"]
            )
        )
        assert verified["status"] == "VERIFIED"
        assert verified["ldr_result"] == "PASS"
        assert verified["ldr_standard_ppm"] is None
        assert verified["verified_by_user_id"] == COMPLIANCE_MANAGER_USER_ID
        assert_unit_state(fixtures.read_unit(scenario.unit["id"]), reserved_kg=0.0)
        assert_cents(
            fixtures.read_facility(scenario.facility["id"])[
                "active_treatment_liability_cents"
            ],
            0,
            "active_treatment_liability_cents",
        )


class TestComplianceManagerExclusiveAuthority:
    def test_the_compliance_officer_posts_assurance_and_pulls_a_profile_in_and_out(self):
        """`ComplianceManager` is the facility's compliance officer: it posts and cancels financial assurance instruments, changes generator standing, suspends and reinstates waste profiles, moves storage units towards closure, resolves manifest discrepancies, changes container condition, records inspections, drives repair orders, signs land-disposal-restriction verifications, and files permit renewal applications.
        The new instrument opens `ACTIVE`.
        `posted_assurance_cents` is the sum of `face_amount_cents` over the facility's instruments whose `status` is `ACTIVE`, and `assurance_shortfall_cents` is the amount by which the required total exceeds the posted total, or zero when the posted total is at least the required total.
        An approved profile can be pulled out of service and put back.
        Naming a `to_status` of `APPROVED` reverses the chain exactly: every container under that profile that is `DEFICIENT` with `last_finding_code` equal to `PROFILE_SUSPENDED` returns to `COMPLIANT`; the affected units recompute posture and return from `RESTRICTED` to `OPEN` when no other restriction holds; and every batch on those units that is `HELD` with `held_reason_code` of `PROFILE_SUSPENDED` returns to `PLANNED`, re-entering reserved mass and active treatment liability.

        Design: Corner/rbac/compliance_manager_performs_its_exclusive_fiscal_and_standing_operations
        """
        fixtures.set_clock()
        facility = fixtures.create_facility()
        generator = fixtures.create_generator()
        profile = fixtures.create_approved_profile(generator["id"], facility["id"])

        instrument = validate_success(
            api_client.create_instrument(
                factories.instrument_payload(
                    facility["id"],
                    facility["version"],
                    face_amount_cents=90_000_000,
                    instrument_type="LETTER_OF_CREDIT",
                ),
                TEST_USERS["compliance_manager"],
            ),
            expected_status=201,
        )
        assert instrument["status"] == "ACTIVE"
        assert_assurance(
            fixtures.read_facility(facility["id"]),
            posted_cents=90_000_000,
            shortfall_cents=0,
        )

        suspended = validate_success(
            api_client.set_waste_profile_status(
                profile["id"],
                factories.profile_status_payload("SUSPENDED", "CONSTITUENT_DRIFT"),
                TEST_USERS["compliance_manager"],
            )
        )
        assert suspended["status"] == "SUSPENDED"

        reinstated = validate_success(
            api_client.set_waste_profile_status(
                profile["id"],
                factories.profile_status_payload("APPROVED", "RESAMPLED_OK"),
                TEST_USERS["compliance_manager"],
            )
        )
        assert reinstated["status"] == "APPROVED"
        assert reinstated["approved_treatment_method"] == "INCINERATION"
