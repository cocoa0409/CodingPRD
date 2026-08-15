"""Staffing posture thresholds, scheduling overlap, charge-slot and skill-mix
gates, and the safety validations on assignment creation."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    complete_assignment,
    confirm_assignment,
    create_float_nurse,
    create_full_matrix,
    create_nurse,
    create_shift,
    create_unit,
    get_shift,
    make_charge_nurse_headers,
    propose_assignment,
    setup_staffed_shift,
    setup_unit_with_shift,
    submit_snapshot,
    validate_error,
    validate_success,
    walk_to_accepted,
    walk_to_confirmed,
)


class TestPostureThresholdWalk:
    """Corner instance: posture_threshold_walk."""

    def test_posture_walks_critical_understaffed_adequate(self):
        """PRD section 3.3: "The posture evaluation, re-run after every
        mutation of those inputs, is: `ADEQUATE` when effective assignments are
        at least `required_nurses` and, additionally, either `required_nurses`
        is less than two or charge coverage exists; otherwise `UNDERSTAFFED`
        when effective assignments are at least `required_nurses` minus one;
        and `CRITICAL` when effective assignments are less than or equal to
        `required_nurses` minus two."
        PRD section 2.7: "While unlocked, the shift's `status` is `STAFFED`
        exactly when the posture is `ADEQUATE`, and `OPEN` otherwise".

        Design: Corner/cross_cutting_layers/posture_threshold_walk
        """
        sc = setup_unit_with_shift(name="ICU X2", census=(4, 0, 0, 0))
        shift_id = sc["shift"]["id"]
        # required_nurses == 2 (ceil(4/4)=1 raised to the floor of 2)
        assert sc["shift"]["required_nurses"] == 2
        assert sc["shift"]["staffing_posture"] == "CRITICAL", \
            f"0 effective <= 2-2 must be CRITICAL, got {sc['shift']['staffing_posture']}"

        n1 = create_nurse(full_name="Walk One", employment_type="CORE",
                          competencies=["ICU"], base_hourly_rate_cents=5000,
                          home_unit_id=sc["unit"]["id"], charge_qualified=True)
        n2 = create_nurse(full_name="Walk Two", employment_type="CORE",
                          competencies=["ICU"], base_hourly_rate_cents=5000,
                          home_unit_id=sc["unit"]["id"])
        walk_to_accepted(shift_id, n1, sc["charge_headers"], is_charge=True)
        mid = get_shift(shift_id)
        assert mid["staffing_posture"] == "UNDERSTAFFED", \
            f"1 effective == 2-1 must be UNDERSTAFFED, got {mid['staffing_posture']}"
        assert mid["status"] == "OPEN"

        walk_to_accepted(shift_id, n2, sc["charge_headers"])
        final = get_shift(shift_id)
        assert final["staffing_posture"] == "ADEQUATE", \
            f"2 effective >= 2 with charge covered must be ADEQUATE, got {final['staffing_posture']}"
        assert final["status"] == "STAFFED", \
            f"STAFFED exactly when posture is ADEQUATE, got {final['status']}"


class TestHalfOpenOverlap:
    """Difficulty instance: nurse_half_open_overlap_adjacency."""

    def _setup_two_units(self):
        """Unit A (ICU) DAY shift; unit B (MED_SURG) DAY + NIGHT shifts, all
        on 2026-08-10; one nurse competent in both, proposed onto A's DAY."""
        ua = create_unit(name="ICU M", unit_type="ICU")
        create_full_matrix("ICU")
        ub = create_unit(name="MS M", unit_type="MED_SURG", bed_count=30)
        create_full_matrix("MED_SURG")
        cn = create_nurse(full_name="M Charge", employment_type="CORE",
                          competencies=["ICU", "MED_SURG"],
                          base_hourly_rate_cents=7000,
                          home_unit_id=ua["id"], charge_qualified=True)
        ch = make_charge_nurse_headers(cn["id"])
        submit_snapshot(ua["id"], "2026-08-10", "DAY", (4, 0, 0, 0),
                        as_headers=ch)
        sha = create_shift(ua["id"], "2026-08-10", "DAY")
        submit_snapshot(ub["id"], "2026-08-10", "DAY", (5, 0, 0, 0),
                        as_headers=ch)
        submit_snapshot(ub["id"], "2026-08-10", "NIGHT", (5, 0, 0, 0),
                        as_headers=ch)
        shb = create_shift(ub["id"], "2026-08-10", "DAY")
        shc = create_shift(ub["id"], "2026-08-10", "NIGHT")
        nurse = create_nurse(full_name="Olive Overlap", employment_type="CORE",
                             competencies=["ICU", "MED_SURG"],
                             base_hourly_rate_cents=5000,
                             home_unit_id=ua["id"])
        a1 = propose_assignment(sha["id"], nurse["id"], ch)
        return {"ua": ua, "ub": ub, "sha": sha, "shb": shb, "shc": shc,
                "nurse": nurse, "a1": a1, "charge_headers": ch}

    def test_same_interval_overlap_rejected(self):
        """PRD section 2.11: "A nurse may never hold two overlapping live
        commitments, where "live" means an assignment in `PROPOSED`,
        `ACCEPTED`, or `CONFIRMED` status."
        PRD section 3.4: "the new commitment must not overlap any of the
        nurse's live commitments under the half-open rule of §2.11, else
        `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/nurse_half_open_overlap_adjacency
        """
        sc = self._setup_two_units()
        # Unit B DAY shift runs the identical 07:00-19:00Z interval.
        resp = api_client.create_assignment(
            sc["shb"]["id"],
            {"nurse_id": sc["nurse"]["id"],
             "expected_shift_version": sc["shb"]["version"]},
            sc["charge_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)

    def test_back_to_back_adjacency_allowed(self):
        """PRD section 2.11: "Because the intervals are half-open, back-to-back
        shifts — where the new commitment starts exactly when the existing one
        ends — do **not** overlap and are allowed."

        Design: Difficulty/resource_temporal_overlap/nurse_half_open_overlap_adjacency
        """
        sc = self._setup_two_units()
        # Unit B NIGHT shift starts 19:00Z, exactly when A's DAY shift ends.
        resp = api_client.create_assignment(
            sc["shc"]["id"],
            {"nurse_id": sc["nurse"]["id"],
             "expected_shift_version": sc["shc"]["version"]},
            sc["charge_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PROPOSED"
        a1 = validate_success(
            api_client.get_assignment(sc["a1"]["id"], ADMIN),
            expected_status=200)
        assert a1["status"] == "PROPOSED", "the existing assignment is untouched"


class TestChargeSlotCapacity:
    """Difficulty instance: charge_slot_capacity_one."""

    def _setup_two_charge_candidates(self):
        sc = setup_unit_with_shift(name="ICU N", census=(4, 0, 0, 0))
        q1 = create_nurse(full_name="Q One", employment_type="CORE",
                          competencies=["ICU"], base_hourly_rate_cents=5000,
                          home_unit_id=sc["unit"]["id"], charge_qualified=True)
        q2 = create_nurse(full_name="Q Two", employment_type="CORE",
                          competencies=["ICU"], base_hourly_rate_cents=5000,
                          home_unit_id=sc["unit"]["id"], charge_qualified=True)
        # Confirm a1's charge designation BEFORE a2 becomes an ACCEPTED
        # charge candidate: the PRD gate blocks confirming an is_charge
        # assignment when *another* ACCEPTED/CONFIRMED charge assignment
        # already exists, so a1 must be confirmed while it is still the
        # only ACCEPTED charge assignment on the shift.
        a1 = walk_to_accepted(sc["shift"]["id"], q1, sc["charge_headers"],
                              is_charge=True)
        confirm_assignment(a1["id"], sc["charge_headers"])
        a2 = walk_to_accepted(sc["shift"]["id"], q2, sc["charge_headers"],
                              is_charge=True)
        sc.update({"q1": q1, "q2": q2, "a1": a1, "a2": a2})
        return sc

    def test_second_charge_confirm_rejected(self):
        """PRD section 3.4: "The charge-slot gate: if the assignment carries
        `is_charge`, no other `ACCEPTED` or `CONFIRMED` assignment on the same
        shift may already hold the charge designation, else
        `ERR_CHARGE_SLOT_TAKEN`."

        Design: Difficulty/resource_temporal_overlap/charge_slot_capacity_one
        """
        sc = self._setup_two_charge_candidates()
        resp = api_client.confirm_assignment(sc["a2"]["id"],
                                             sc["charge_headers"])
        validate_error(resp, ApiErrorId.ERR_CHARGE_SLOT_TAKEN)

    def test_rejected_charge_confirm_leaves_state_untouched(self):
        """PRD section 3.3: "`charge_covered` is true exactly when an
        `ACCEPTED` or `CONFIRMED` assignment with `is_charge` set exists."

        Design: Difficulty/resource_temporal_overlap/charge_slot_capacity_one
        """
        sc = self._setup_two_charge_candidates()
        resp = api_client.confirm_assignment(sc["a2"]["id"],
                                             sc["charge_headers"])
        validate_error(resp, ApiErrorId.ERR_CHARGE_SLOT_TAKEN)
        a2 = validate_success(
            api_client.get_assignment(sc["a2"]["id"], ADMIN),
            expected_status=200)
        assert a2["status"] == "ACCEPTED", \
            f"failed confirm must leave the assignment ACCEPTED, got {a2['status']}"
        shift = get_shift(sc["shift"]["id"])
        assert shift["charge_covered"] is True
        assert shift["counted_assignments"] == 2


class TestSkillMixFloatCap:

    def test_skill_mix_float_cap_at_floor_boundary(self):
        """PRD section 3.4: "The skill-mix gate: after this confirmation, the
        number of the shift's counted assignments held by `FLOAT_POOL` nurses
        must not exceed half of the shift's counted assignments rounded down to
        a whole number, else `ERR_SKILL_MIX_VIOLATION`."

        Design: Corner/calculations/skill_mix_float_cap_at_floor_boundary
        """
        sc = setup_unit_with_shift(name="ICU C6", census=(2, 3, 2, 1))
        assert sc["shift"]["required_nurses"] == 4
        ch = sc["charge_headers"]
        shift_id = sc["shift"]["id"]

        cores = [create_nurse(full_name=f"Core {i}", employment_type="CORE",
                              competencies=["ICU"], base_hourly_rate_cents=5000,
                              home_unit_id=sc["unit"]["id"])
                 for i in (1, 2)]
        floats = [create_float_nurse(full_name=f"Float G{i}",
                                     competencies=["ICU"])
                  for i in (1, 2, 3)]

        # counted 1: 0 floats <= floor(1/2)=0 OK; counted 2: 0 <= 1 OK
        for n in cores:
            walk_to_confirmed(shift_id, n, ch)
        # counted 3: 1 float <= floor(3/2)=1 OK; counted 4: 2 <= 2 OK
        for n in floats[:2]:
            walk_to_confirmed(shift_id, n, ch)
        # third float: accept (counted 5) then confirm -> 3 > floor(5/2)=2
        g3 = walk_to_accepted(shift_id, floats[2], ch)

        resp = api_client.confirm_assignment(g3["id"], ch)
        validate_error(resp, ApiErrorId.ERR_SKILL_MIX_VIOLATION)

        after = validate_success(api_client.get_assignment(g3["id"], ADMIN),
                                 expected_status=200)
        assert after["status"] == "ACCEPTED", \
            f"failed confirm must leave state untouched, got {after['status']}"


class TestCreationSafetyRules:

    def test_competency_missing_on_create_rejected(self):
        """PRD section 3.4: "the nurse's `competencies` must include the
        shift's unit type, else `ERR_COMPETENCY_NOT_HELD`".

        Design: Corner/validations/competency_missing_on_create_rejected
        """
        sc = setup_unit_with_shift(name="ICU V2", census=(4, 0, 0, 0))
        nurse = create_nurse(full_name="Wrong Wing", employment_type="CORE",
                             competencies=["MED_SURG"],
                             base_hourly_rate_cents=4500,
                             home_unit_id=sc["unit"]["id"])
        resp = api_client.create_assignment(
            sc["shift"]["id"],
            {"nurse_id": nurse["id"],
             "expected_shift_version": sc["shift"]["version"]},
            sc["charge_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_COMPETENCY_NOT_HELD)

    def test_not_charge_qualified_rejected(self):
        """PRD section 3.4: "a request to set `is_charge` on a nurse whose
        `charge_qualified` is false fails with `ERR_NOT_CHARGE_QUALIFIED`".

        Design: Corner/validations/not_charge_qualified_rejected
        """
        sc = setup_unit_with_shift(name="ICU V3", census=(4, 0, 0, 0))
        nurse = create_nurse(full_name="Not Qualified", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=5000,
                             home_unit_id=sc["unit"]["id"],
                             charge_qualified=False)
        resp = api_client.create_assignment(
            sc["shift"]["id"],
            {"nurse_id": nurse["id"], "is_charge": True,
             "expected_shift_version": sc["shift"]["version"]},
            sc["charge_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_CHARGE_QUALIFIED)
