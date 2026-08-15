"""Guest registration defaults and the walk-in intake capacity gates
(PRD §2.6, §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_guest,
    assert_guest_stay,
    assert_site_activation,
    get_site_activation,
    open_activation,
    register_guest,
    setup_active_episode_with_opening_site,
    setup_open_site_with_guests,
    validate_error,
    validate_paginated,
    validate_success,
    walk_in_stay,
    EOC_HEADERS,
    INTAKE_HEADERS,
)


class TestGuestRegistration:
    def test_guest_registration_minimal_barrier_defaults(
            self, api, intake_staff_headers):
        """PRD §3.4: "an `IntakeStaff` registers a guest with an `alias` and
        nothing more is ever required — no legal name, no identification.
        Optional profile fields default sensibly: `has_pets` false,
        `pet_count` zero (non-negative, and it must be zero whenever
        `has_pets` is false), `bag_count` zero (non-negative), and
        `medical_flag` false for a self-declared vulnerability. A guest's
        `medical_hold_active` starts false and is thereafter computed from the
        incident workflow (§3.7)."

        Design: Corner/entities/guest_registration_minimal_barrier_defaults
        """
        resp = api.create_guest({"alias": "Jane Doe of 5th St"},
                                intake_staff_headers)
        data = validate_success(resp, 201)
        assert_guest(data)
        assert data["alias"] == "Jane Doe of 5th St"
        assert data["has_pets"] is False
        assert data["pet_count"] == 0
        assert data["bag_count"] == 0
        assert data["medical_flag"] is False
        assert data["medical_hold_active"] is False

    def test_guest_missing_alias_returns_validation(self, api,
                                                    intake_staff_headers):
        """PRD §2.9: "a malformed payload — a missing required field, an
        unknown enum value, a type mismatch — also fails with
        `ERR_VALIDATION` (HTTP 400)."
        PRD §3.4: "an `IntakeStaff` registers a guest with an `alias` and
        nothing more is ever required — no legal name, no identification."

        Design: Corner/entities/guest_missing_alias_returns_validation
        """
        resp = api.create_guest({}, intake_staff_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


class TestBedBoundary:
    def test_intake_with_one_bed_free_succeeds(self, api):
        """PRD §3.4: "Capacity is then checked in a pinned order — beds, then
        pets, then lockers: at least one free bed, else
        `ERR_NO_BED_AVAILABLE`; ..."
        PRD §2.7: "Wherever this document says "at least" or "at most", the
        boundary value satisfies the condition."

        Design: Difficulty/boundary_precision_check/intake_at_zero_beds_free_rejected_one_bed_allowed
        """
        ws = setup_open_site_with_guests(
            [{"alias": "first"}, {"alias": "second"}], bed_capacity=1)
        sa_id = ws["site_activation"]["id"]
        resp = api.create_stay(sa_id, {"guest_id": ws["guests"][0]["id"]},
                               INTAKE_HEADERS)
        data = validate_success(resp, 201)
        assert_guest_stay(data)
        assert data["status"] == "CHECKED_IN"

    def test_intake_with_zero_beds_free_rejected(self, api):
        """PRD §3.4: "Capacity is then checked in a pinned order — beds, then
        pets, then lockers: at least one free bed, else
        `ERR_NO_BED_AVAILABLE`; ..."

        Design: Difficulty/boundary_precision_check/intake_at_zero_beds_free_rejected_one_bed_allowed
        """
        ws = setup_open_site_with_guests(
            [{"alias": "first"}, {"alias": "second"}], bed_capacity=1)
        sa_id = ws["site_activation"]["id"]
        walk_in_stay(sa_id, ws["guests"][0]["id"])  # consumes the only bed

        resp = api.create_stay(sa_id, {"guest_id": ws["guests"][1]["id"]},
                               INTAKE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NO_BED_AVAILABLE, expected_status=409)

        after = get_site_activation(sa_id)
        assert after["occupied_beds"] == 1
        assert after["beds_free"] == 0


class TestSiteOpenGate:
    def test_intake_on_opening_site_rejected(self, api):
        """PRD §3.4: "Walk-in intake creates a stay directly in `CHECKED_IN`.
        The activation must be `OPEN`, else `ERR_SITE_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/intake_requires_site_activation_open
        """
        # Episode ACTIVE, activation never opened (still OPENING).
        ws = setup_active_episode_with_opening_site()
        guest = register_guest("walker")
        resp = api.create_stay(ws["site_activation"]["id"],
                               {"guest_id": guest["id"]}, INTAKE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_OPEN, expected_status=409)

    def test_intake_after_open_succeeds(self, api):
        """PRD §3.4: "Walk-in intake creates a stay directly in `CHECKED_IN`.
        The activation must be `OPEN`, else `ERR_SITE_NOT_OPEN`." — once the
        same activation is OPEN, the identical request succeeds.

        Design: Difficulty/cross_entity_state_dependency/intake_requires_site_activation_open
        """
        ws = setup_active_episode_with_opening_site()
        guest = register_guest("walker")
        open_activation(ws["site_activation"]["id"], ws["lead1"]["id"])
        resp = api.create_stay(ws["site_activation"]["id"],
                               {"guest_id": guest["id"]}, INTAKE_HEADERS)
        data = validate_success(resp, 201)
        assert data["status"] == "CHECKED_IN"


class TestUniquenessAndPools:
    def test_second_active_stay_same_episode_rejected(self, api):
        """PRD §3.4: "The guest must not already hold a stay in the same
        episode in `RESERVED` or `CHECKED_IN`, else
        `ERR_GUEST_ALREADY_HAS_ACTIVE_STAY`."

        Design: Corner/validations/second_active_stay_same_episode_rejected
        """
        ws = setup_open_site_with_guests([{"alias": "walker"}])
        sa_id = ws["site_activation"]["id"]
        guest_id = ws["guests"][0]["id"]
        walk_in_stay(sa_id, guest_id)

        resp = api.create_stay(sa_id, {"guest_id": guest_id}, INTAKE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_GUEST_ALREADY_HAS_ACTIVE_STAY,
                       expected_status=409)

        stays, meta = validate_paginated(
            api.list_stays(EOC_HEADERS, params={"guest_id": guest_id}))
        assert meta["total_count"] == 1
        assert stays[0]["status"] == "CHECKED_IN"

    def test_intake_pet_and_locker_overflow_rejected(self, api):
        """PRD §3.4: "the guest's `pet_count` within `pet_slots_free`, else
        `ERR_PET_CAPACITY_EXCEEDED`; and the guest's locker demand —
        `bag_count` divided by two and rounded up — within `lockers_free`,
        else `ERR_LOCKER_CAPACITY_EXCEEDED`."

        Design: Corner/validations/intake_pet_and_locker_overflow_rejected
        """
        ws = setup_open_site_with_guests(
            [{"alias": "pet-owner", "has_pets": True, "pet_count": 2},
             {"alias": "bag-carrier", "bag_count": 4}],
            bed_capacity=4, pet_capacity=1, locker_capacity=1)
        sa_id = ws["site_activation"]["id"]

        resp_pet = api.create_stay(sa_id, {"guest_id": ws["guests"][0]["id"]},
                                   INTAKE_HEADERS)
        validate_error(resp_pet, ApiErrorId.ERR_PET_CAPACITY_EXCEEDED,
                       expected_status=409)

        resp_bags = api.create_stay(sa_id, {"guest_id": ws["guests"][1]["id"]},
                                    INTAKE_HEADERS)
        validate_error(resp_bags, ApiErrorId.ERR_LOCKER_CAPACITY_EXCEEDED,
                       expected_status=409)

        _, meta = validate_paginated(
            api.list_stays(EOC_HEADERS, params={"site_activation_id": sa_id}))
        assert meta["total_count"] == 0

    def test_lockers_used_rounds_up_bag_pairs(self, api):
        """PRD §2.6: "`pet_slots_used` is the guest's `pet_count` at the
        intake moment, and `lockers_used` is the guest's `bag_count` divided
        by two and rounded up — one locker shelters two bags, and an odd bag
        still claims a whole locker."

        Design: Corner/calculations/lockers_used_rounds_up_bag_pairs
        """
        ws = setup_open_site_with_guests([{"alias": "bags", "bag_count": 3}],
                                         locker_capacity=10)
        sa_id = ws["site_activation"]["id"]
        resp = api.create_stay(sa_id, {"guest_id": ws["guests"][0]["id"]},
                               INTAKE_HEADERS)
        stay = validate_success(resp, 201)
        assert stay["lockers_used"] == 2  # ceil(3 / 2)

        after = get_site_activation(sa_id)
        assert_site_activation(after)
        assert after["lockers_free"] == 8

    def test_immediate_consistency_read_your_writes(self, api):
        """PRD §2.6: "Consistency is immediate: every computed field described
        in this document recomputes within the same request that mutates any
        of its inputs, so a read issued after a mutation never observes a
        stale pool, coverage figure or stock level."

        Design: Corner/consistency_model/immediate_consistency_read_your_writes
        """
        ws = setup_open_site_with_guests([{"alias": "walker"}])
        sa_id = ws["site_activation"]["id"]
        resp = api.create_stay(sa_id, {"guest_id": ws["guests"][0]["id"]},
                               INTAKE_HEADERS)
        assert validate_success(resp, 201)["status"] == "CHECKED_IN"

        after = get_site_activation(sa_id)
        assert after["occupied_beds"] == 1
        assert after["beds_free"] == 3
