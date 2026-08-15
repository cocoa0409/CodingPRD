"""Committees, appointments, activation gates, dormancy and dissolution."""
import test_helpers as th
from test_helpers import fixtures as fx

ADMIN = th.TEST_USERS["governance_admin_headers"]


def _org_with_cleared_board(api, ein, members_spec=("CHAIR", "D1")):
    """Org + adopted bylaws + ACTIVE members with CLEARED FY2026 disclosures."""
    officers = tuple("CHAIR" if s == "CHAIR" else None for s in members_spec)
    sc = fx.setup_org_with_board(num_directors=sum(1 for s in members_spec if s != "CHAIR"),
                                 officers=tuple(o for o in officers if o), ein=ein,
                                 receipts=1_000_000)
    fx.clear_coi_for_all(sc["nonprofit"]["id"], sc["members"], fiscal_year=2026)
    return sc


class TestCommitteeDefaults:
    def test_audit_committee_independence_forced_default(self, api):
        """PRD §3.3: "Committees are chartered by a `GovernanceAdmin` or
        `BoardChair` with a `name` unique within the nonprofit among committees that
        are not `DISSOLVED` (`ERR_DUPLICATE_COMMITTEE_NAME`), a `type` of `AUDIT`,
        `FINANCE`, `GOVERNANCE`, `NOMINATING`, `EXECUTIVE`, `COMPENSATION`, or
        `OTHER`, a `min_members` of at least 1, an `authorized_size` no smaller than
        `min_members`, and a `requires_all_independent` flag defaulting to false —
        but forced to true whenever the type is `AUDIT`, since audit committees must
        be composed entirely of independent directors."

        Design: Corner/entities/audit_committee_independence_forced_default
        """
        org = fx.create_nonprofit(name="O", ein="EIN-AC-1", receipts=1_000_000)
        audit = fx.create_committee(org["id"], name="Audit", type="AUDIT",
                                    min_members=3, authorized_size=5)
        assert audit["requires_all_independent"] is True, (
            "type AUDIT must force requires_all_independent true")
        finance = fx.create_committee(org["id"], name="Fin", type="FINANCE",
                                      min_members=2, authorized_size=4)
        assert finance["requires_all_independent"] is False, (
            "non-AUDIT committee keeps the default false")


class TestAppointmentGates:
    def test_committee_chair_uniqueness_rejected(self, api):
        """PRD §3.3: "Two uniqueness rules complete the gate: a member may not hold
        two active appointments on the same committee (`ERR_DUPLICATE_APPOINTMENT`),
        and each appointment carries a `committee_role` of `CHAIR` or `MEMBER`
        (default `MEMBER`) with at most one active `CHAIR` appointment per committee
        (`ERR_DUPLICATE_COMMITTEE_CHAIR`)."

        Design: Corner/errors/committee_chair_uniqueness_rejected
        """
        sc = _org_with_cleared_board(api, "EIN-CC-1", ("CHAIR", "D1"))
        np_id = sc["nonprofit"]["id"]
        chair, d1 = sc["chair"], sc["members"][1]
        committee = fx.create_committee(np_id, name="Gov", type="GOVERNANCE",
                                        min_members=1, authorized_size=3)
        fx.appoint(np_id, committee["id"], chair, chair, committee_role="CHAIR")

        resp_dup = api.create_appointment(
            th.create_appointment_payload(np_id, committee["id"], d1["id"],
                                          committee_role="CHAIR"),
            th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp_dup, th.ApiErrorId.ERR_DUPLICATE_COMMITTEE_CHAIR)

        ok = th.validate_success(api.create_appointment(
            th.create_appointment_payload(np_id, committee["id"], d1["id"],
                                          committee_role="MEMBER"),
            th.make_board_chair_headers(chair["id"])), 201)
        assert ok["status"] == "ACTIVE"

    def test_committee_full_and_duplicate_appointment_rejected(self, api):
        """PRD §3.3: "Appointment gates, all evaluated before the seat is granted:
        the appointee must be an `ACTIVE` member (`ERR_MEMBER_NOT_ELIGIBLE`); the
        committee must not be `DISSOLVED` (a dissolved committee rejects the
        appointment with `ERR_INVALID_STATE`); the committee's
        `active_member_count` must be below its `authorized_size`
        (`ERR_COMMITTEE_FULL`); a `requires_all_independent` committee accepts only
        appointees whose `is_independent` is true (`ERR_COMMITTEE_NOT_INDEPENDENT`)"
        PRD §3.3: "Two uniqueness rules complete the gate: a member may not hold two
        active appointments on the same committee (`ERR_DUPLICATE_APPOINTMENT`), and
        each appointment carries a `committee_role` of `CHAIR` or `MEMBER` (default
        `MEMBER`) with at most one active `CHAIR` appointment per committee
        (`ERR_DUPLICATE_COMMITTEE_CHAIR`)."

        Design: Corner/errors/committee_full_and_duplicate_appointment_rejected
        """
        sc = _org_with_cleared_board(api, "EIN-CF2-1", ("CHAIR", "D1"))
        np_id = sc["nonprofit"]["id"]
        chair, d1 = sc["chair"], sc["members"][1]
        committee = fx.create_committee(np_id, name="Gov", type="GOVERNANCE",
                                        min_members=1, authorized_size=1)
        fx.appoint(np_id, committee["id"], chair, chair)

        resp_dup = api.create_appointment(
            th.create_appointment_payload(np_id, committee["id"], chair["id"]),
            th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp_dup, th.ApiErrorId.ERR_DUPLICATE_APPOINTMENT)

        resp_full = api.create_appointment(
            th.create_appointment_payload(np_id, committee["id"], d1["id"]),
            th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp_full, th.ApiErrorId.ERR_COMMITTEE_FULL)

    def test_committee_activation_min_and_independence_gates(self, api):
        """PRD §3.3: "Activation is a separate, deliberate step: the `BoardChair`
        activates a `CHARTERED` committee only when its `active_member_count` is at
        least `min_members` (`ERR_COMMITTEE_BELOW_MIN`), when every active appointee
        is independent if the committee requires it (`ERR_COMMITTEE_NOT_INDEPENDENT`),
        and when every active appointee holds a current-fiscal-year disclosure in
        `CLEARED` or `RESTRICTIONS_IMPOSED` (`ERR_COI_REVIEW_REQUIRED`)."
        PRD §3.3: "a `requires_all_independent` committee accepts only appointees
        whose `is_independent` is true (`ERR_COMMITTEE_NOT_INDEPENDENT`)"

        Design: Corner/errors/committee_activation_min_and_independence_gates
        """
        org = fx.create_nonprofit(name="O", ein="EIN-CAG-1", receipts=1_000_000)
        fx.create_adopted_bylaws(org["id"])
        chair = fx.create_board_member(org["id"], "C", "c@x.org",
                                       skills=["GOVERNANCE"], officer_role="CHAIR")
        d1 = fx.create_board_member(org["id"], "D1", "d1@x.org", skills=["FINANCE"])
        d2 = fx.create_board_member(org["id"], "D2", "d2@x.org", skills=["LEGAL"],
                                    is_independent=False)
        for m in (chair, d1, d2):
            fx.elect_member(org["id"], m["id"], start_date="2026-01-01T00:00:00Z")
        members = [th.validate_success(api.get_board_member(m["id"], ADMIN))
                   for m in (chair, d1, d2)]
        chair, d1, d2 = members
        fx.clear_coi_for_all(org["id"], members, fiscal_year=2026)
        chair_headers = th.make_board_chair_headers(chair["id"])

        gov = fx.create_committee(org["id"], name="Gov", type="GOVERNANCE",
                                  min_members=2, authorized_size=3)
        audit = fx.create_committee(org["id"], name="Audit", type="AUDIT",
                                    min_members=1, authorized_size=3)
        fx.appoint(org["id"], gov["id"], chair, chair)

        resp_ind = api.create_appointment(
            th.create_appointment_payload(org["id"], audit["id"], d2["id"]),
            chair_headers)
        th.validate_error(resp_ind, th.ApiErrorId.ERR_COMMITTEE_NOT_INDEPENDENT)

        # GOV has 1 active appointee < min_members 2
        th.validate_error(api.activate_committee(gov["id"], chair_headers),
                          th.ApiErrorId.ERR_COMMITTEE_BELOW_MIN)
        # AUDIT has 0 active appointees < min_members 1
        th.validate_error(api.activate_committee(audit["id"], chair_headers),
                          th.ApiErrorId.ERR_COMMITTEE_BELOW_MIN)


class TestDissolveAndDormancy:
    def test_committee_dissolve_cascades_and_locks(self, api):
        """PRD §3.3: "Dissolution is available from `CHARTERED`, `ACTIVE`, or
        `DORMANT`: from `CHARTERED` or `ACTIVE` it ends every active appointment
        with `ended_reason` `COMMITTEE_DISSOLVED` and cancels the committee's
        scheduled meetings, while from `DORMANT` only the meeting cancellation
        remains, its appointments having already ended. `DISSOLVED` is terminal."

        Design: Corner/state_machines/committee_dissolve_cascades_and_locks
        """
        sc = _org_with_cleared_board(api, "EIN-CD-1", ("CHAIR", "D1"))
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        committee, appointments = fx.setup_active_committee(
            np_id, chair, [chair], name="Gov", type="GOVERNANCE",
            min_members=1, authorized_size=3)
        cmtg = fx.create_meeting(np_id, start="2026-08-10T10:00:00Z",
                                 committee_id=committee["id"])

        dissolved = th.validate_success(api.dissolve_committee(
            committee["id"], th.make_board_chair_headers(chair["id"])))
        assert dissolved["status"] == "DISSOLVED"

        appt = th.validate_success(api.get_appointment(appointments[0]["id"], ADMIN))
        assert appt["status"] == "ENDED"
        assert appt["ended_reason"] == "COMMITTEE_DISSOLVED"

        meeting = th.validate_success(api.get_meeting(cmtg["id"], ADMIN))
        assert meeting["status"] == "CANCELLED", (
            "dissolution cancels the committee's scheduled meetings")

        th.validate_error(api.activate_committee(
            committee["id"], th.make_board_chair_headers(chair["id"])),
            th.ApiErrorId.ERR_INVALID_STATE)

    def test_dormant_committee_blocks_call_to_order(self, api):
        """PRD §3.3: "The committee lifecycle is `CHARTERED` to `ACTIVE`, with
        demotion to `DORMANT` whenever an appointment ends and the count of an
        `ACTIVE` committee falls below `min_members` — a demotion that also cancels
        the committee's `SCHEDULED` meetings — and recovery from `DORMANT` to
        `ACTIVE` as described above."
        PRD §2.7: "7. **State-machine from-state.** The target resource must be in a
        state from which the requested transition is allowed, else
        `ERR_INVALID_STATE` (409); this also covers transitions attempted on
        terminal resources and non-idempotent re-fires."

        Design: Corner/state_machines/dormant_committee_blocks_call_to_order
        """
        sc = _org_with_cleared_board(api, "EIN-DO-1", ("CHAIR", "D1"))
        np_id = sc["nonprofit"]["id"]
        chair, d1 = sc["chair"], sc["members"][1]
        committee, appointments = fx.setup_active_committee(
            np_id, chair, [chair, d1], name="Gov", type="GOVERNANCE",
            min_members=2, authorized_size=3)
        cmtg = fx.create_meeting(np_id, start="2026-08-01T00:00:00Z",
                                 committee_id=committee["id"])

        appt_d1 = next(a for a in appointments if a["board_member_id"] == d1["id"])
        th.validate_success(api.end_appointment(
            appt_d1["id"], th.make_board_chair_headers(chair["id"])))

        committee_after = th.validate_success(api.get_committee(committee["id"], ADMIN))
        assert committee_after["status"] == "DORMANT", (
            f"1 active appointee < min_members 2 must demote to DORMANT, got {committee_after['status']}")
        meeting_after = th.validate_success(api.get_meeting(cmtg["id"], ADMIN))
        assert meeting_after["status"] == "CANCELLED", (
            "the demotion cascade cancels the committee's scheduled meetings")

        resp = api.call_to_order(cmtg["id"], {"attendance": [chair["id"]]},
                                 th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_INVALID_STATE)


class TestAppointmentCoiGate:
    """Difficulty: cross_entity_state_dependency / committee_appointment_gated_by_coi_review."""

    def _setup(self, api):
        sc = fx.setup_org_with_board(num_directors=1, officers=("CHAIR",),
                                     ein="EIN-GATE-2")
        committee = fx.create_committee(sc["nonprofit"]["id"], name="Gov Cttee",
                                        type="GOVERNANCE", min_members=1,
                                        authorized_size=3,
                                        via=th.make_board_chair_headers(sc["chair"]["id"]))
        return sc, committee

    def test_appointment_blocked_without_reviewed_disclosure(self, api):
        """PRD §3.3: "the appointee must hold a reviewed current-fiscal-year
        disclosure — one in `CLEARED` or `RESTRICTIONS_IMPOSED` — and, when that
        disclosure is `RESTRICTIONS_IMPOSED`, its `restriction_categories` must not
        map onto the committee's type, else `ERR_COI_REVIEW_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/committee_appointment_gated_by_coi_review
        """
        sc, committee = self._setup(api)
        np_id = sc["nonprofit"]["id"]
        chair, member = sc["chair"], sc["members"][1]
        resp = api.create_appointment(
            th.create_appointment_payload(np_id, committee["id"], member["id"]),
            th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_COI_REVIEW_REQUIRED)

    def test_appointment_succeeds_after_disclosure_cleared(self, api):
        """PRD §3.3: "the appointee must hold a reviewed current-fiscal-year
        disclosure — one in `CLEARED` or `RESTRICTIONS_IMPOSED` — and, when that
        disclosure is `RESTRICTIONS_IMPOSED`, its `restriction_categories` must not
        map onto the committee's type, else `ERR_COI_REVIEW_REQUIRED`."
        PRD §3.3: "A successful appointment is `ACTIVE` and increments the
        committee's `active_member_count` by 1"

        Design: Difficulty/cross_entity_state_dependency/committee_appointment_gated_by_coi_review
        """
        sc, committee = self._setup(api)
        np_id = sc["nonprofit"]["id"]
        chair, member = sc["chair"], sc["members"][1]
        # member files FY2026; chair (own FY2026 filed) reviews and clears it
        disclosure = fx.file_coi(np_id, member, fiscal_year=2026)
        fx.file_coi(np_id, chair, fiscal_year=2026)
        fx.review_disclosure(disclosure["id"], chair)

        appt = th.validate_success(api.create_appointment(
            th.create_appointment_payload(np_id, committee["id"], member["id"]),
            th.make_board_chair_headers(chair["id"])), 201)
        th.assert_appointment(appt)
        assert appt["status"] == "ACTIVE"
        committee_after = th.validate_success(api.get_committee(committee["id"], ADMIN))
        assert committee_after["active_member_count"] == 1
