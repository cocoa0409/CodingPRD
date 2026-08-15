"""Conflict-of-interest disclosures, peer review, restriction cascades."""
import test_helpers as th
from test_helpers import fixtures as fx

ADMIN = th.TEST_USERS["governance_admin_headers"]


class TestDisclosureFiling:
    def test_coi_disclosure_has_conflict_computed_from_answers(self, api):
        """PRD §3.6: "The filing is `FILED` upon receipt, its `filed_at` stamped
        from the clock, and its `has_conflict` flag is true when any answer is
        answered true."
        PRD §3.6: "Each director files one disclosure per fiscal year, as themself
        per §2.1, supplying `nonprofit_id`, their own `board_member_id`, the
        `fiscal_year` covered, and an `answers` list of question entries — each with
        a `question_key`, a boolean `answer`, and an optional free-text `detail`."

        Design: Corner/entities/coi_disclosure_has_conflict_computed_input_ignored
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-HC-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]

        clean = th.validate_success(api.file_disclosure(
            th.create_disclosure_payload(np_id, chair["id"], 2026,
                                         answers=[{"question_key": "q1",
                                                   "answer": False}]),
            th.headers_for_member(chair)), 201)
        assert clean["has_conflict"] is False, (
            "all-false answers must compute has_conflict false")

        member2 = fx.create_board_member(np_id, "D1", "d1@x.org", skills=["LEGAL"])
        fx.elect_member(np_id, member2["id"], start_date="2026-01-01T00:00:00Z")
        conflicted = th.validate_success(api.file_disclosure(
            th.create_disclosure_payload(np_id, member2["id"], 2026,
                                         answers=[{"question_key": "q1",
                                                   "answer": False},
                                                  {"question_key": "q2",
                                                   "answer": True,
                                                   "detail": "vendor"}]),
            th.headers_for_member(member2)), 201)
        assert conflicted["has_conflict"] is True, (
            "any true answer must compute has_conflict true")

    def test_coi_duplicate_year_rejected(self, api):
        """PRD §3.6: "A second filing for the same member and fiscal year is
        rejected with `ERR_DUPLICATE_DISCLOSURE`, and an empty `answers` list with
        `ERR_INVALID_REQUEST`."

        Design: Corner/errors/coi_duplicate_year_rejected
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-CDX-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        fx.file_coi(np_id, chair, fiscal_year=2026)

        resp = api.file_disclosure(
            th.create_disclosure_payload(np_id, chair["id"], 2026,
                                         answers=[{"question_key": "q1",
                                                   "answer": True}]),
            th.headers_for_member(chair))
        th.validate_error(resp, th.ApiErrorId.ERR_DUPLICATE_DISCLOSURE)


class TestReviewSegregation:
    def test_coi_self_review_rejected(self, api):
        """PRD §3.6: "The reviewer may not be the filer
        (`ERR_SEGREGATION_OF_DUTIES`), must be an `ACTIVE` member of the same
        nonprofit (`ERR_REVIEWER_NOT_QUALIFIED`), and must have filed their own
        disclosure for the same fiscal year in any of `FILED`, `UNDER_REVIEW`,
        `CLEARED`, or `RESTRICTIONS_IMPOSED` (`ERR_REVIEWER_NOT_COMPLIANT`)."

        Design: Corner/errors/coi_self_review_rejected
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-CSR-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        disclosure = fx.file_coi(np_id, chair, fiscal_year=2026)

        resp = api.start_review(disclosure["id"], th.headers_for_member(chair))
        th.validate_error(resp, th.ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = th.validate_success(api.get_disclosure(disclosure["id"], ADMIN))
        assert after["status"] == "FILED"

    def test_coi_clear_by_non_reviewer_rejected(self, api):
        """PRD §3.6: "Only the assigned reviewer may then decide the review:
        clearing moves the disclosure to `CLEARED`, while imposing restrictions
        requires a non-empty `restriction_categories` list (`ERR_INVALID_REQUEST`)
        and moves it to `RESTRICTIONS_IMPOSED`; either act attempted by anyone other
        than the recorded `reviewer_member_id` is rejected with
        `ERR_REVIEWER_MISMATCH`."

        Design: Corner/errors/coi_clear_by_non_reviewer_rejected
        """
        sc = fx.setup_org_with_board(num_directors=2, officers=("CHAIR",),
                                     ein="EIN-CNR-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, reviewer, d1 = sc["chair"], sc["members"][1], sc["members"][2]
        disclosure = fx.file_coi(np_id, chair, fiscal_year=2026)
        fx.file_coi(np_id, reviewer, fiscal_year=2026)
        th.validate_success(api.start_review(disclosure["id"],
                                             th.headers_for_member(reviewer)))

        resp = api.clear_disclosure(disclosure["id"], th.headers_for_member(d1))
        th.validate_error(resp, th.ApiErrorId.ERR_REVIEWER_MISMATCH)

    def test_reviewer_without_own_filing_rejected(self, api):
        """PRD §3.6: "The reviewer may not be the filer
        (`ERR_SEGREGATION_OF_DUTIES`), must be an `ACTIVE` member of the same
        nonprofit (`ERR_REVIEWER_NOT_QUALIFIED`), and must have filed their own
        disclosure for the same fiscal year in any of `FILED`, `UNDER_REVIEW`,
        `CLEARED`, or `RESTRICTIONS_IMPOSED` (`ERR_REVIEWER_NOT_COMPLIANT`)."

        Design: Corner/errors/reviewer_without_own_filing_rejected
        """
        sc = fx.setup_org_with_board(num_directors=1, officers=("CHAIR",),
                                     ein="EIN-RNC-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, reviewer = sc["chair"], sc["members"][1]
        disclosure = fx.file_coi(np_id, chair, fiscal_year=2026)
        # reviewer has NOT filed a FY2026 disclosure of their own

        resp = api.start_review(disclosure["id"], th.headers_for_member(reviewer))
        th.validate_error(resp, th.ApiErrorId.ERR_REVIEWER_NOT_COMPLIANT)

    def test_reviewer_must_be_active_member(self, api):
        """PRD §2.1: "Three roles are entity-backed by the board roster. When
        `X-User-Role` is `BoardChair`, `X-User-ID` must be the `id` of an `ACTIVE`
        `BoardMember` whose `officer_role` is `CHAIR`; when `X-User-Role` is
        `Treasurer`, `X-User-ID` must be the `id` of an `ACTIVE` `BoardMember` whose
        `officer_role` is `TREASURER`; when `X-User-Role` is `BoardDirector`,
        `X-User-ID` must be the `id` of any `ACTIVE` `BoardMember`. In all three
        cases the member must belong to the nonprofit being acted on, and ownership
        checks on any resource that references a `BoardMember` compare the
        resource's foreign-key field to `X-User-ID`. A caller who fails this
        qualification is rejected with `ERR_IDENTITY_NOT_QUALIFIED` (HTTP 403)."

        Design: Corner/errors/reviewer_must_be_active_member
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-RNQ-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        nominee = fx.create_board_member(np_id, "P", "p@x.org",
                                         skills=["LEGAL"])  # stays PROPOSED
        disclosure = fx.file_coi(np_id, chair, fiscal_year=2026)

        resp = api.start_review(disclosure["id"],
                                th.make_board_director_headers(nominee["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_IDENTITY_NOT_QUALIFIED, 403)


class TestResignationCascade:
    def test_member_resignation_full_cascade(self, api):
        """PRD §2.10: "**Departure chain (resignation or removal).** The member's
        scheduled or active term is vacated (link 1a); the member's active committee
        appointments end with the corresponding reason (link 1b); each affected
        committee recomputes its active membership and an `ACTIVE` committee that
        falls below its minimum goes `DORMANT` (link 2); and a committee going
        dormant has its scheduled meetings cancelled (link 3). The freed seat
        returns to the organization's open-seat pool."
        PRD §3.2: "Resignation — recorded by a `GovernanceAdmin` or `BoardChair` for
        anyone, or by the director themself under the self-service rule of §2.1 —
        moves an `ACTIVE` member to `RESIGNED` and fires the departure chain of
        §2.10"

        Design: Corner/state_machines/member_resignation_full_cascade
        """
        sc = fx.setup_org_with_board(num_directors=1, officers=("CHAIR",),
                                     ein="EIN-RC-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, member = sc["chair"], sc["members"][1]
        fx.clear_coi_for_all(np_id, [chair, member], fiscal_year=2026)
        committee, appointments = fx.setup_active_committee(
            np_id, chair, [chair, member], name="Gov", type="GOVERNANCE",
            min_members=2, authorized_size=3)
        member_appt = next(a for a in appointments
                           if a["board_member_id"] == member["id"])
        member_term = th.validate_paginated(api.list_board_terms(
            ADMIN, params={"board_member_id": member["id"]}))[0][0]
        cmtg = fx.create_meeting(np_id, start="2026-08-10T10:00:00Z",
                                 committee_id=committee["id"])

        resigned = th.validate_success(api.resign_member(member["id"], ADMIN))
        assert resigned["status"] == "RESIGNED"

        term_after = th.validate_success(api.get_board_term(member_term["id"], ADMIN))
        assert term_after["status"] == "VACATED", "link 1a: the active term is vacated"

        appt_after = th.validate_success(api.get_appointment(member_appt["id"], ADMIN))
        assert appt_after["status"] == "ENDED"
        assert appt_after["ended_reason"] == "RESIGNED", "link 1b"

        committee_after = th.validate_success(api.get_committee(committee["id"], ADMIN))
        assert committee_after["active_member_count"] == 1
        assert committee_after["status"] == "DORMANT", (
            "link 2: below min_members 2 the committee goes DORMANT")

        meeting_after = th.validate_success(api.get_meeting(cmtg["id"], ADMIN))
        assert meeting_after["status"] == "CANCELLED", (
            "link 3: the dormant committee's scheduled meeting is cancelled")


class TestCoiRestrictionCascade:
    """Difficulty: transitive_cascade / coi_restriction_cascade_dormants_committee_and_cancels_meeting."""

    def _setup(self, api):
        """FY2025-cleared board with an ACTIVE FINANCE committee, then FY2026 restrictions.

        Clock starts at 2025-06-01 (FY2025 under a December year-end) so the
        appointment/activation COI gates read FY2025 disclosures; the clock then
        advances to 2026-02-01 (FY2026) where the target files a conflicting
        disclosure and the reviewer imposes FINANCE restrictions.
        """
        fx.set_clock("2025-06-01T00:00:00Z")
        org = fx.create_nonprofit(name="COI Org", ein="EIN-COI-1")
        fx.create_adopted_bylaws(org["id"])
        np_id = org["id"]
        specs = [("Chair", "CHAIR", ["GOVERNANCE"]), ("Rev", None, ["LEGAL"]),
                 ("Tgt", None, ["FINANCE"]), ("A1", None, ["PROGRAM"])]
        members = []
        for name, officer, skills in specs:
            m = fx.create_board_member(np_id, name, f"{name.lower()}@x.org",
                                       skills=skills, officer_role=officer)
            fx.elect_member(np_id, m["id"], start_date="2025-01-01T00:00:00Z")
            members.append(th.validate_success(api.get_board_member(m["id"], ADMIN)))
        chair, reviewer, target, a1 = members
        fx.clear_coi_for_all(np_id, members, fiscal_year=2025)
        committee, appointments = fx.setup_active_committee(
            np_id, chair, [target, a1], name="Finance Cttee", type="FINANCE",
            min_members=2, authorized_size=3)
        target_appt = next(a for a in appointments
                           if a["board_member_id"] == target["id"])
        cmtg = fx.create_meeting(np_id, start="2026-03-01T10:00:00Z",
                                 committee_id=committee["id"])

        fx.set_clock("2026-02-01T00:00:00Z")
        target_fy26 = fx.file_coi(
            np_id, target, fiscal_year=2026,
            answers=[{"question_key": "q_fin", "answer": True,
                      "detail": "vendor relationship"}])
        fx.file_coi(np_id, reviewer, fiscal_year=2026)
        th.validate_success(api.start_review(target_fy26["id"],
                                             th.headers_for_member(reviewer)))
        return {
            "np_id": np_id, "chair": chair, "reviewer": reviewer,
            "target": target, "committee": committee,
            "target_appt": target_appt, "cmtg": cmtg, "target_fy26": target_fy26,
        }

    def test_impose_restrictions_flags_member_and_ends_appointment(self, api):
        """PRD §3.6: "Imposing restrictions fires the restriction chain of §2.10.
        The member's `has_active_restrictions` becomes true (link 1); the member's
        active appointments on committees whose type maps to a restricted category
        end with `ended_reason` `COI_RESTRICTION` — a `FINANCE` restriction maps to
        `FINANCE`, `AUDIT`, and `COMPENSATION` committees, a `PERSONNEL` restriction
        to `COMPENSATION` and `EXECUTIVE` committees, and a `GOVERNANCE` restriction
        to `GOVERNANCE` and `NOMINATING` committees (link 2); and each affected
        committee recomputes its count, demoting to `DORMANT` with its scheduled
        meetings cancelled where the minimum is breached (link 3)."

        Design: Difficulty/transitive_cascade/coi_restriction_cascade_dormants_committee_and_cancels_meeting
        """
        ctx = self._setup(api)
        imposed = th.validate_success(api.impose_restrictions(
            ctx["target_fy26"]["id"], {"restriction_categories": ["FINANCE"]},
            th.headers_for_member(ctx["reviewer"])))
        assert imposed["status"] == "RESTRICTIONS_IMPOSED"

        member_after = th.validate_success(
            api.get_board_member(ctx["target"]["id"], ADMIN))
        assert member_after["has_active_restrictions"] is True, "link 1"

        appt_after = th.validate_success(
            api.get_appointment(ctx["target_appt"]["id"], ADMIN))
        assert appt_after["status"] == "ENDED"
        assert appt_after["ended_reason"] == "COI_RESTRICTION", (
            "link 2: FINANCE restriction ends the FINANCE-committee appointment")

    def test_impose_restrictions_dormants_committee_and_cancels_meeting(self, api):
        """PRD §3.6: "Imposing restrictions fires the restriction chain of §2.10.
        The member's `has_active_restrictions` becomes true (link 1); the member's
        active appointments on committees whose type maps to a restricted category
        end with `ended_reason` `COI_RESTRICTION` — a `FINANCE` restriction maps to
        `FINANCE`, `AUDIT`, and `COMPENSATION` committees, a `PERSONNEL` restriction
        to `COMPENSATION` and `EXECUTIVE` committees, and a `GOVERNANCE` restriction
        to `GOVERNANCE` and `NOMINATING` committees (link 2); and each affected
        committee recomputes its count, demoting to `DORMANT` with its scheduled
        meetings cancelled where the minimum is breached (link 3)."

        Design: Difficulty/transitive_cascade/coi_restriction_cascade_dormants_committee_and_cancels_meeting
        """
        ctx = self._setup(api)
        th.validate_success(api.impose_restrictions(
            ctx["target_fy26"]["id"], {"restriction_categories": ["FINANCE"]},
            th.headers_for_member(ctx["reviewer"])))

        committee_after = th.validate_success(
            api.get_committee(ctx["committee"]["id"], ADMIN))
        assert committee_after["active_member_count"] == 1
        assert committee_after["status"] == "DORMANT", (
            "link 3: 1 active member < min_members 2 demotes the committee")

        meeting_after = th.validate_success(api.get_meeting(ctx["cmtg"]["id"], ADMIN))
        assert meeting_after["status"] == "CANCELLED", (
            "link 4: the dormant committee's scheduled meeting is cancelled")
