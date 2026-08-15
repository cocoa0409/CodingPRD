"""Petition circulation, signature verification, and support thresholds
(PRD §3.2, §2.10, §2.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_petition,
    create_district,
    create_owner,
    create_parcel,
    create_signature_payload,
    drive_to_scoping,
    get_district,
    get_petition,
    make_property_owner_headers,
    open_petition,
    sign_and_verify,
    sign_petition,
    api_client,
    validate_error,
    validate_success,
    verify_signature,
)

CLERK = TEST_USERS["clerk_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


def _five_parcel_district(name, prefix):
    district = create_district(name=name)
    pairs = []
    for i in range(1, 6):
        owner = create_owner(full_name=f"Owner {prefix}{i}", email=f"{prefix}-o{i}@x.test",
                             mailing_address=f"{i} Main St")
        parcel = create_parcel(district["id"], owner["id"],
                               parcel_number=f"P-{i:03d}", frontage_ft=40.0)
        pairs.append((owner, parcel))
    return district, pairs


class TestPetitionCountThreshold:
    def test_exactly_sixty_percent_count_passes(self, api):
        """PRD §3.2: "Passage requires both — a count percentage of at least
        60.00 and a frontage percentage of at least 50.00". PRD §3.2: "A
        petition that meets both thresholds closes `CLOSED_VERIFIED` and moves
        the district `PETITIONING` → `SCOPING`".

        Design: Difficulty/boundary_precision_check/petition_count_threshold_exactly_sixty_percent
        """
        district, pairs = _five_parcel_district("B1-A", "b1a")
        petition = open_petition(district["id"])
        for owner, parcel in pairs[:3]:
            sign_and_verify(petition["id"], parcel["id"], owner["id"])
        petition = close_petition(petition["id"])
        assert petition["status"] == "CLOSED_VERIFIED"
        assert petition["support_count_pct"] == pytest.approx(60.00), (
            "3 of 5 parcels is exactly 60.00% and must pass (>= semantics)"
        )
        assert petition["support_frontage_pct"] == pytest.approx(60.00)
        assert get_district(district["id"])["status"] == "SCOPING"

    def test_below_sixty_percent_count_fails_and_recirculates(self, api):
        """PRD §3.2: "Passage requires both — a count percentage of at least
        60.00 and a frontage percentage of at least 50.00". PRD §3.2: "one that
        misses either threshold closes `CLOSED_INSUFFICIENT` and returns the
        district to `DRAFT`, where a fresh petition may be opened for a new
        cycle."

        Design: Difficulty/boundary_precision_check/petition_count_threshold_exactly_sixty_percent
        """
        district, pairs = _five_parcel_district("B1-B", "b1b")
        petition = open_petition(district["id"])
        for owner, parcel in pairs[:2]:
            sign_and_verify(petition["id"], parcel["id"], owner["id"])
        petition = close_petition(petition["id"])
        assert petition["status"] == "CLOSED_INSUFFICIENT"
        assert petition["support_count_pct"] == pytest.approx(40.00)
        assert get_district(district["id"])["status"] == "DRAFT", (
            "a failed petition must return the district to DRAFT"
        )


class TestSignatureTallyConservation:
    def test_verify_increments_petition_tallies(self, api):
        """PRD §3.2: "A verified signature moves to `VERIFIED`, stamps
        `verified_at`, records the clerk in `verified_by`, and adds one to the
        petition's `verified_signature_count` and the parcel's `frontage_ft` to
        `verified_frontage_ft`."

        Design: Difficulty/compensating_invariant/signature_tally_verify_withdraw_conservation
        """
        district = create_district(name="CI2")
        o1 = create_owner(full_name="Owner ci21", email="ci2-o1@x.test")
        o2 = create_owner(full_name="Owner ci22", email="ci2-o2@x.test")
        p1 = create_parcel(district["id"], o1["id"], parcel_number="P-001", frontage_ft=60.0)
        p2 = create_parcel(district["id"], o2["id"], parcel_number="P-002", frontage_ft=40.0)
        petition = open_petition(district["id"])
        sign_and_verify(petition["id"], p1["id"], o1["id"])
        sign_and_verify(petition["id"], p2["id"], o2["id"])

        petition = get_petition(petition["id"])
        assert petition["verified_signature_count"] == 2
        assert petition["verified_frontage_ft"] == pytest.approx(100.00)

    def test_withdraw_of_verified_signature_decrements_tallies(self, api):
        """PRD §3.2: "withdrawing a `VERIFIED` signature additionally
        decrements `verified_signature_count` by one and subtracts the parcel's
        `frontage_ft` from `verified_frontage_ft`, keeping the petition's
        tallies conserved against the set of signatures currently `VERIFIED`."

        Design: Difficulty/compensating_invariant/signature_tally_verify_withdraw_conservation
        """
        district = create_district(name="CI2")
        o1 = create_owner(full_name="Owner ci21", email="ci2-o1@x.test")
        o2 = create_owner(full_name="Owner ci22", email="ci2-o2@x.test")
        p1 = create_parcel(district["id"], o1["id"], parcel_number="P-001", frontage_ft=60.0)
        p2 = create_parcel(district["id"], o2["id"], parcel_number="P-002", frontage_ft=40.0)
        petition = open_petition(district["id"])
        s1 = sign_and_verify(petition["id"], p1["id"], o1["id"])
        sign_and_verify(petition["id"], p2["id"], o2["id"])

        withdrawn = validate_success(
            api_client.withdraw_signature(s1["id"], make_property_owner_headers(o1["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        petition = get_petition(petition["id"])
        assert petition["verified_signature_count"] == 1
        assert petition["verified_frontage_ft"] == pytest.approx(40.00), (
            "net of the verify/withdraw pair equals the single remaining "
            "VERIFIED signature"
        )


class TestPetitionStateMachine:
    def test_petition_double_close_rejected(self, api):
        """PRD §3.2: "Closing circulation is the clerk's final act on a
        petition, and only a `CIRCULATING` petition can be closed
        (`ERR_PETITION_NOT_CIRCULATING`)."

        Design: Corner/state_machines/sm_petition_double_close_rejected
        """
        ctx = drive_to_scoping("SDC", prefix="sdc")
        validate_error(
            api_client.close_petition(ctx["petition"]["id"], CLERK),
            ApiErrorId.ERR_PETITION_NOT_CIRCULATING,
        )

    def test_signature_verify_twice_rejected(self, api):
        """PRD §3.2: "Verifying requires the signature still be `SUBMITTED`
        (`ERR_SIGNATURE_NOT_VERIFIABLE`)". PRD §3.2: "a second submission while
        a `SUBMITTED` or `VERIFIED` signature exists for the same parcel on the
        same petition is refused with `ERR_DUPLICATE_SIGNATURE`, which is also
        why a parcel can never contribute more than one verified signature to
        the tallies."

        Design: Corner/state_machines/sm_signature_verify_twice_rejected
        """
        district = create_district(name="SVT")
        owner = create_owner(full_name="Owner svt1", email="svt-o1@x.test")
        parcel = create_parcel(district["id"], owner["id"])
        petition = open_petition(district["id"])
        sig = sign_petition(petition["id"], parcel["id"], owner["id"])
        verify_signature(sig["id"])

        validate_error(
            api_client.verify_signature(sig["id"], CLERK),
            ApiErrorId.ERR_SIGNATURE_NOT_VERIFIABLE,
        )
        assert get_petition(petition["id"])["verified_signature_count"] == 1, (
            "tallies must not double-count a re-verification attempt"
        )

    def test_signature_withdraw_after_close_rejected(self, api):
        """PRD §3.2: "Withdrawal is available to the signature's owner
        (`ERR_NOT_RESOURCE_OWNER`) from either `SUBMITTED` or `VERIFIED`, but
        only while the petition still circulates — once circulation has closed,
        withdrawal fails with `ERR_SIGNATURE_NOT_WITHDRAWABLE`."

        Design: Corner/state_machines/sm_signature_withdraw_after_close_rejected
        """
        district = create_district(name="SWC")
        owner = create_owner(full_name="Owner swc1", email="swc-o1@x.test")
        parcel = create_parcel(district["id"], owner["id"])
        petition = open_petition(district["id"])
        sig = sign_and_verify(petition["id"], parcel["id"], owner["id"])
        close_petition(petition["id"])

        validate_error(
            api_client.withdraw_signature(sig["id"], make_property_owner_headers(owner["id"])),
            ApiErrorId.ERR_SIGNATURE_NOT_WITHDRAWABLE,
        )

    def test_failed_petition_recirculation_cycle(self, api):
        """PRD §3.2: "one that misses either threshold closes
        `CLOSED_INSUFFICIENT` and returns the district to `DRAFT`, where a
        fresh petition may be opened for a new cycle." PRD §3.1: "two
        sanctioned loops — re-circulation from `PETITIONING` back to `DRAFT`".

        Design: Corner/state_machines/sm_failed_petition_recirculation_cycle
        """
        district = create_district(name="SRC")
        o1 = create_owner(full_name="Owner src1", email="src-o1@x.test")
        o2 = create_owner(full_name="Owner src2", email="src-o2@x.test")
        p1 = create_parcel(district["id"], o1["id"], parcel_number="P-001", frontage_ft=50.0)
        p2 = create_parcel(district["id"], o2["id"], parcel_number="P-002", frontage_ft=50.0)

        pet1 = open_petition(district["id"])
        sign_and_verify(pet1["id"], p1["id"], o1["id"])
        pet1 = close_petition(pet1["id"])
        assert pet1["status"] == "CLOSED_INSUFFICIENT", "1 of 2 = 50.00% < 60.00%"
        assert get_district(district["id"])["status"] == "DRAFT"

        pet2 = open_petition(district["id"])
        sign_and_verify(pet2["id"], p1["id"], o1["id"])
        sign_and_verify(pet2["id"], p2["id"], o2["id"])
        pet2 = close_petition(pet2["id"])
        assert pet2["status"] == "CLOSED_VERIFIED"
        assert get_district(district["id"])["status"] == "SCOPING"


class TestAbandonmentCascade:
    def test_abandoned_district_lockdown(self, api):
        """PRD §3.9: "Abandonment is the clerk's escape hatch, and it is only
        open early: from `DRAFT`, `PETITIONING`, `SCOPING`,
        `HEARING_SCHEDULED`, or `OBJECTION_WINDOW`. From any later status the
        district cannot be abandoned and the attempt fails with
        `ERR_DISTRICT_NOT_ABANDONABLE`." PRD §3.2: "attempting it in any other
        district state fails with `ERR_DISTRICT_NOT_DRAFT`."

        Design: Corner/state_machines/sm_abandoned_district_lockdown
        """
        district = create_district(name="SAL")
        abandoned = validate_success(
            api_client.abandon_district(district["id"], CLERK)
        )
        assert abandoned["status"] == "ABANDONED"
        validate_error(
            api_client.create_petition({"district_id": district["id"]}, CLERK),
            ApiErrorId.ERR_DISTRICT_NOT_DRAFT,
        )
        validate_error(
            api_client.abandon_district(district["id"], CLERK),
            ApiErrorId.ERR_DISTRICT_NOT_ABANDONABLE,
        )

    def test_abandon_petitioning_cascades_to_children(self, api):
        """PRD §3.9: "From `PETITIONING`, the `CIRCULATING` petition is
        `VOIDED` and its `SUBMITTED` and `VERIFIED` signatures are `VOIDED`
        with it."

        Design: Corner/state_machines/sm_abandon_cascades_to_children
        """
        district = create_district(name="SAB")
        owner = create_owner(full_name="Owner sab1", email="sab-o1@x.test")
        parcel = create_parcel(district["id"], owner["id"])
        petition = open_petition(district["id"])
        sig = sign_and_verify(petition["id"], parcel["id"], owner["id"])

        abandoned = validate_success(
            api_client.abandon_district(district["id"], CLERK)
        )
        assert abandoned["status"] == "ABANDONED"
        assert get_petition(petition["id"])["status"] == "VOIDED"
        sig_after = validate_success(
            api_client.get_signature(sig["id"], CLERK)
        )
        assert sig_after["status"] == "VOIDED"


class TestSignatureEligibilityAndOwnership:
    def test_duplicate_signature_rejected(self, api):
        """PRD §3.2: "A parcel holds at most one live signature per petition:
        a second submission while a `SUBMITTED` or `VERIFIED` signature exists
        for the same parcel on the same petition is refused with
        `ERR_DUPLICATE_SIGNATURE`".

        Design: Corner/validations/v_duplicate_signature_rejected
        """
        district = create_district(name="VDS")
        owner = create_owner(full_name="Owner vds1", email="vds-o1@x.test")
        parcel = create_parcel(district["id"], owner["id"])
        petition = open_petition(district["id"])
        payload = create_signature_payload(petition_id=petition["id"],
                                           parcel_id=parcel["id"])
        validate_success(
            api_client.create_signature(payload, make_property_owner_headers(owner["id"])),
            expected_status=201,
        )
        validate_error(
            api_client.create_signature(payload, make_property_owner_headers(owner["id"])),
            ApiErrorId.ERR_DUPLICATE_SIGNATURE,
        )

    def test_sign_other_owners_parcel_forbidden(self, api):
        """PRD §3.2: "a `PropertyOwner` signs it for their own parcel by
        submitting `petition_id` and `parcel_id`. The caller must be the
        parcel's owner of record (`ERR_NOT_RESOURCE_OWNER`)". PRD §2.1:
        "ownership checks on any resource that references a property owner — a
        signature's parcel, an objection's parcel, an assessment's parcel —
        compare the resource's owner-of-record field to `X-User-ID`, and a
        mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/validations/v_sign_other_owners_parcel_forbidden
        """
        district = create_district(name="VSO")
        o1 = create_owner(full_name="Owner vso1", email="vso-o1@x.test")
        o2 = create_owner(full_name="Owner vso2", email="vso-o2@x.test")
        p1 = create_parcel(district["id"], o1["id"], parcel_number="P-001", frontage_ft=50.0)
        create_parcel(district["id"], o2["id"], parcel_number="P-002", frontage_ft=50.0)
        petition = open_petition(district["id"])

        payload = create_signature_payload(petition_id=petition["id"], parcel_id=p1["id"])
        validate_error(
            api_client.create_signature(payload, make_property_owner_headers(o2["id"])),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        )

    def test_owner_cannot_close_petition_forbidden(self, api):
        """PRD §2.1: "When the supplied role is not among the roles an endpoint
        admits, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)." PRD §4: "POST `/petitions/{id}/close` | Close circulation
        and compute support | CityClerk".

        Design: Corner/validations/v_owner_cannot_close_petition_forbidden
        """
        district = create_district(name="VUC")
        owner = create_owner(full_name="Owner vuc1", email="vuc-o1@x.test")
        parcel = create_parcel(district["id"], owner["id"])
        petition = open_petition(district["id"])
        sign_petition(petition["id"], parcel["id"], owner["id"])

        validate_error(
            api_client.close_petition(
                petition["id"], make_property_owner_headers(owner["id"])
            ),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )

    def test_engineer_cannot_verify_signature(self, api):
        """PRD §2.1: "When the supplied role is not among the roles an endpoint
        admits, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)." PRD §4: "POST `/signatures/{id}/verify` | Clerk verifies a
        submitted signature | CityClerk".

        Design: Corner/rbac/r_engineer_cannot_verify_signature
        """
        district = create_district(name="REV")
        owner = create_owner(full_name="Owner rev1", email="rev-o1@x.test")
        parcel = create_parcel(district["id"], owner["id"])
        petition = open_petition(district["id"])
        sig = sign_petition(petition["id"], parcel["id"], owner["id"])

        validate_error(
            api_client.verify_signature(sig["id"], ENGINEER),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )

    def test_exempt_parcel_excluded_and_cannot_sign(self, api):
        """PRD §2.10: "A parcel marked `exempt` — and any parcel whose `status`
        has become `REMOVED` — cannot sign petitions, is excluded from every
        eligibility denominator, receives no assessment, and cannot be the
        target of a new objection; attempting to sign or object for such a
        parcel is rejected with `ERR_INELIGIBLE_PARCEL` (HTTP 409)."

        Design: Corner/validations/v_exempt_parcel_excluded_and_cannot_sign
        """
        district = create_district(name="VEX")
        o1 = create_owner(full_name="Owner vex1", email="vex-o1@x.test")
        o2 = create_owner(full_name="Owner vex2", email="vex-o2@x.test")
        p1 = create_parcel(district["id"], o1["id"], parcel_number="P-001", frontage_ft=100.0)
        p2 = create_parcel(district["id"], o2["id"], parcel_number="P-002",
                           frontage_ft=50.0, exempt=True)
        petition = open_petition(district["id"])

        district_view = get_district(district["id"])
        assert district_view["total_frontage_ft"] == pytest.approx(100.00)
        assert district_view["eligible_parcel_count"] == 1, (
            "the exempt parcel is excluded from the eligibility denominator"
        )

        payload = create_signature_payload(petition_id=petition["id"], parcel_id=p2["id"])
        validate_error(
            api_client.create_signature(payload, make_property_owner_headers(o2["id"])),
            ApiErrorId.ERR_INELIGIBLE_PARCEL,
        )

        sign_and_verify(petition["id"], p1["id"], o1["id"])
        petition = close_petition(petition["id"])
        assert petition["status"] == "CLOSED_VERIFIED"
        assert petition["support_count_pct"] == pytest.approx(100.00), (
            "1 of 1 eligible parcels signed -> 100.00%"
        )


class TestFrontageThresholdDualCriterion:
    def test_frontage_exactly_fifty_percent_passes(self, api):
        """PRD §3.2: "Passage requires both — a count percentage of at least
        60.00 and a frontage percentage of at least 50.00 — so a district can
        pass on parcels yet fail on frontage, or the reverse, on an identical
        signature set." PRD §2.6: "Percentages — petition support figures and
        the protest weight — are computed to exactly two decimal places with
        round-half-up, and threshold comparisons consume the rounded value."

        Design: Corner/calculations/c_petition_frontage_exactly_fifty_and_dual_criterion
        """
        district = create_district(name="FB1")
        frontages = [50.0, 30.0, 20.0, 100.0]
        pairs = []
        for i, frontage in enumerate(frontages, start=1):
            owner = create_owner(full_name=f"Owner fb1{i}", email=f"fb1-o{i}@x.test",
                                 mailing_address=f"{i} Main St")
            pairs.append((owner, create_parcel(district["id"], owner["id"],
                                               parcel_number=f"P-{i:03d}",
                                               frontage_ft=frontage)))
        petition = open_petition(district["id"])
        for owner, parcel in pairs[:3]:
            sign_and_verify(petition["id"], parcel["id"], owner["id"])
        petition = close_petition(petition["id"])

        assert petition["support_frontage_pct"] == pytest.approx(50.00), (
            "signed frontage 100.00 of 200.00 is exactly 50.00% (boundary inclusive)"
        )
        assert petition["support_count_pct"] == pytest.approx(75.00)
        assert petition["status"] == "CLOSED_VERIFIED"

    def test_frontage_below_fifty_fails_despite_count_passing(self, api):
        """PRD §3.2: "Passage requires both — a count percentage of at least
        60.00 and a frontage percentage of at least 50.00 — so a district can
        pass on parcels yet fail on frontage, or the reverse, on an identical
        signature set." PRD §3.2: "one that misses either threshold closes
        `CLOSED_INSUFFICIENT` and returns the district to `DRAFT`".

        Design: Corner/calculations/c_petition_frontage_exactly_fifty_and_dual_criterion
        """
        district = create_district(name="FB2")
        frontages = [49.98, 30.0, 20.0, 100.02]
        pairs = []
        for i, frontage in enumerate(frontages, start=1):
            owner = create_owner(full_name=f"Owner fb2{i}", email=f"fb2-o{i}@x.test",
                                 mailing_address=f"{i} Main St")
            pairs.append((owner, create_parcel(district["id"], owner["id"],
                                               parcel_number=f"P-{i:03d}",
                                               frontage_ft=frontage)))
        petition = open_petition(district["id"])
        for owner, parcel in pairs[:3]:
            sign_and_verify(petition["id"], parcel["id"], owner["id"])
        petition = close_petition(petition["id"])

        assert petition["support_frontage_pct"] == pytest.approx(49.99), (
            "signed frontage 99.98 of 200.00 rounds to 49.99% and must fail"
        )
        assert petition["support_count_pct"] == pytest.approx(75.00)
        assert petition["status"] == "CLOSED_INSUFFICIENT"
        assert get_district(district["id"])["status"] == "DRAFT"
