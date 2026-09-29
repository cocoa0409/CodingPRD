"""Who may act: league-office exclusives, club and agent ownership, and the two
independent identity controls the league runs on top of ordinary permissions.

Covers the role-authorization gate that keeps league-office operations out of
club and agent hands, the ownership gate that isolates one club or one prospect
from another, the four-eyes rule on eligibility waivers, and the confidentiality
tier that reserves restricted medical files for club medical staff.
"""

from test_helpers import (
    ADMIN,
    CLUB_SEEDS,
    COMMITTEE_REVIEWER_USER_ID,
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    build_declaration_open,
    build_draft_live_on_clock,
    build_medical_evaluation,
    build_order_pending,
    build_waiver_under_review,
    club_payload,
    declaration_payload,
    file_waiver,
    find_by_id,
    grant_consent,
    lottery_payload,
    make_club_medical_director_headers,
    make_club_gm_headers,
    make_committee_headers,
    make_prospect_agent_headers,
    medical_record_share_payload,
    read_club,
    read_cycle,
    read_evaluation,
    read_pick,
    read_prospect,
    register_prospect,
    selection_payload,
    validate_error,
    validate_paginated,
    validate_success,
    waiver_review_payload,
)


def _read_waiver(api, prospect_id: str, waiver_id: str) -> dict:
    """Fetch one waiver back through the prospect's waiver collection."""
    rows, _meta = validate_paginated(
        api.list_eligibility_waivers(prospect_id, ADMIN, {"limit": 100})
    )
    return find_by_id(rows, waiver_id)


class TestLeagueOfficeExclusiveOperations:
    """Operations the endpoint table reserves for the league office."""

    def test_prospect_agent_cannot_register_a_club(self, api):
        """A well-formed club registration from an agent is refused on the role gate.

        The same payload the league office uses is rejected before any body
        validation runs, and the cycle's club roster is untouched.

        "If the headers are well formed but the declared role is not among the roles authorized for the target operation, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/prospect_agent_cannot_register_a_club_role_not_permitted
        """
        state = build_declaration_open(api)
        cycle = state["cycle"]
        prospect = register_prospect(api, cycle["id"])

        response = api.create_club(
            club_payload(cycle["id"], "BRN", **CLUB_SEEDS["BRN"]),
            make_prospect_agent_headers(prospect["id"]),
        )

        validate_error(response, ERR_ROLE_NOT_PERMITTED, expected_status=403)
        assert read_cycle(api, cycle["id"])["club_count"] == 2

    def test_club_gm_cannot_run_the_lottery(self, api):
        """A club that is a party to the draw still may not run the lottery itself.

        The refusal lands on the role gate, so the drawn sequence is never
        consumed: the cycle stays at ORDER_PENDING with the lottery undrawn and
        the club's draft order index still unassigned.

        "Role authorization — the acting role appears in the target endpoint's authorized list, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

        Design: Corner/rbac/club_gm_cannot_run_the_lottery_role_not_permitted
        """
        state = build_order_pending(api)
        cycle = state["cycle"]
        harbor = state["clubs"]["HAR"]

        response = api.run_lottery(
            cycle["id"],
            lottery_payload([200, 50]),
            make_club_gm_headers(harbor["id"]),
        )

        validate_error(response, ERR_ROLE_NOT_PERMITTED, expected_status=403)
        after = read_cycle(api, cycle["id"])
        assert after["lottery_completed"] is False
        assert after["status"] == "ORDER_PENDING"
        assert read_club(api, harbor["id"])["draft_order_index"] == 0


class TestEntityBackedOwnershipIsolation:
    """A club acts only for itself, and an agent only for its own prospect."""

    def test_gm_of_another_club_cannot_select_with_this_clubs_pick(self, api):
        """The general manager of a peer club cannot spend the pick on the clock.

        The ownership comparison rejects the peer club, and the pick keeps
        running for its real owner: still ON_CLOCK, still unspent, and the
        prospect still undrafted.

        "For the three entity-backed roles, acting on a resource that belongs to a different `Club` or a different `Prospect` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/gm_of_another_club_cannot_use_this_clubs_pick
        """
        state = build_draft_live_on_clock(api)
        elm = state["clubs"]["ELM"]
        harbor = state["clubs"]["HAR"]
        prospect = state["prospect"]
        on_clock = state["pick"]["r1p1"]

        response = api.create_selection(
            on_clock["id"],
            selection_payload(prospect["id"]),
            make_club_gm_headers(harbor["id"]),
        )

        validate_error(response, ERR_NOT_RESOURCE_OWNER, expected_status=403)
        after = read_pick(api, on_clock["id"])
        assert after["status"] == "ON_CLOCK"
        assert after["owning_club_id"] == elm["id"]
        assert after["selected_prospect_id"] is None
        assert read_prospect(api, prospect["id"])["drafted_pick_overall_number"] == 0

    def test_agent_cannot_declare_for_a_prospect_it_does_not_represent(self, api):
        """An agent whose identity is one prospect cannot declare a different one.

        Neither prospect moves: the targeted player stays UNDECLARED with no
        declaration instant, and the agent's own player is untouched.

        "Everything downstream depends on the declaration dimension, and only a `ProspectAgent` may move it, by submitting an `action` of `DECLARE` or `WITHDRAW` against the prospect it represents."

        Design: Corner/rbac/agent_cannot_declare_for_a_prospect_they_do_not_represent
        """
        state = build_declaration_open(api)
        cycle = state["cycle"]
        avery = register_prospect(api, cycle["id"])
        brooks = register_prospect(
            api,
            cycle["id"],
            full_name="Brooks Hale",
            position_group="WR",
            school_code="STH",
            scouting_grade=88.00,
            position_group_scarcity_rank=3,
        )

        response = api.declare_prospect(
            avery["id"],
            declaration_payload("DECLARE"),
            make_prospect_agent_headers(brooks["id"]),
        )

        validate_error(response, ERR_NOT_RESOURCE_OWNER, expected_status=403)
        targeted = read_prospect(api, avery["id"])
        assert targeted["declaration_status"] == "UNDECLARED"
        assert targeted["declared_at"] is None
        assert read_prospect(api, brooks["id"])["declaration_status"] == "UNDECLARED"


class TestWaiverSeparationOfDuties:
    """Three different people must carry a waiver from filing to decision."""

    def test_submitter_cannot_open_review_of_its_own_waiver(self, api):
        """The identity that filed the waiver cannot also open its review.

        The filer's identifier is recorded on the waiver, so the same identifier
        acting in the committee capacity is refused and the waiver stays
        SUBMITTED with no reviewer recorded.

        "It requires the acting committee member's identifier to differ from `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`, and it records the acting identifier as `opened_by_user_id`."

        Design: Corner/rbac/waiver_submitter_cannot_open_its_own_review
        """
        state = build_declaration_open(api)
        prospect = register_prospect(api, state["cycle"]["id"])
        filed = file_waiver(api, prospect, "EARLY_ENTRY")

        response = api.review_eligibility_waiver(
            filed["id"],
            waiver_review_payload("OPEN_REVIEW"),
            make_committee_headers(prospect["id"]),
        )

        validate_error(response, ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        after = _read_waiver(api, prospect["id"], filed["id"])
        assert after["status"] == "SUBMITTED"
        assert after["opened_by_user_id"] is None
        assert after["submitted_by_user_id"] == prospect["id"]

    def test_reviewer_who_opened_the_waiver_cannot_grant_it(self, api):
        """The committee member that opened the review may not also decide it.

        The four-eyes rule spans two steps of the same review, so the opener's
        grant is refused: the waiver stays UNDER_REVIEW with no decider and the
        relief the grant would have carried is never applied.

        "It requires the acting identifier to differ from `opened_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`, and it requires `decision_note` to be present."

        Design: Corner/rbac/reviewer_who_opened_the_waiver_cannot_also_decide_it
        """
        state = build_waiver_under_review(api, waiver_type="EARLY_ENTRY")
        prospect = state["prospect"]
        waiver = state["waiver"]

        response = api.review_eligibility_waiver(
            waiver["id"],
            waiver_review_payload(
                "GRANT", decision_note="Hardship documentation verified"
            ),
            state["reviewer_headers"],
        )

        validate_error(response, ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        after = _read_waiver(api, prospect["id"], waiver["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["opened_by_user_id"] == COMMITTEE_REVIEWER_USER_ID
        assert after["decided_by_user_id"] is None
        assert read_prospect(api, prospect["id"])["early_entry_waived"] is False


class TestRestrictedEvaluationAccess:
    """The restricted confidentiality tier is club medical staff's alone."""

    def test_club_medical_director_may_request_a_restricted_evaluation(self, api):
        """Club medical staff legitimately reach a restricted evaluation.

        The request the club general manager is barred from succeeds for the
        medical director: the share is created in REQUESTED with the director's
        capacity recorded, and it waits there for the league decision without
        touching the evaluation's share ledger.

        "An evaluation whose `confidentiality_tier` is `RESTRICTED` is readable only by club medical staff: only a `ClubMedicalDirector` may request a share against it, and a share against it may only be granted while the recorded `requested_by_role` is `ClubMedicalDirector`."

        Design: Corner/rbac/club_medical_director_may_request_a_restricted_evaluation
        """
        state = build_medical_evaluation(
            api, findings_code="ORTHO-REDFLAG-09", medical_grade="RED_FLAG"
        )
        elm = state["clubs"]["ELM"]
        grant_consent(api, state["prospect"])
        evaluation = read_evaluation(api, state["evaluation"]["id"])
        assert evaluation["confidentiality_tier"] == "RESTRICTED"

        response = api.create_medical_record_share(
            medical_record_share_payload(
                evaluation["id"], elm["id"], evaluation["version"], scope="FULL"
            ),
            make_club_medical_director_headers(elm["id"]),
        )

        share = validate_success(response, expected_status=201)
        assert share["status"] == "REQUESTED"
        assert share["requested_by_role"] == "ClubMedicalDirector"
        assert share["scope"] == "FULL"
        assert share["club_id"] == elm["id"]
        assert share["granted_at"] is None
        after = read_evaluation(api, evaluation["id"])
        assert after["confidentiality_tier"] == "RESTRICTED"
        assert after["active_share_count"] == 0
