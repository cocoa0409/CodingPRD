"""Priority-pair conflicts: when two validation tiers both fail on one request,
the lower-numbered tier's error must win (PRD section 2.11)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_roster_party,
    api_client,
    create_attorney,
    create_letter,
    create_matter,
    create_party,
    get_deposit,
    get_success_data,
    issue_letter,
    list_hits_for_check,
    make_client_headers,
    make_responsible_attorney_headers,
    record_credit_assessment,
    run_conflict_check,
    setup_matter_with_confirmed_hit,
    transition_letter_payload,
    validate_error,
    validate_success,
)

INTAKE = TEST_USERS["intake_specialist_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def _issue_letter_for_blocked_matter(m1: dict, atty: dict) -> dict:
    """Record PRIME credit, create + ISSUE a letter, and leave the deposit
    unfunded. Returns the issued letter."""
    record_credit_assessment(m1["id"], 800)
    letter = create_letter(m1, atty)
    issue_letter(letter["id"], atty)
    return letter


class TestClearanceSafetyBeatsRetainerFiscal:
    def test_countersign_blocked_and_unfunded_reports_clearance_error(self):
        """PRD §2.11: "Beyond resolution, every request passes through twelve
        ordered validation tiers, and the first failure wins. The tiers are:
        (1) header authentication, failing as `ERR_UNAUTHENTICATED`; (2) role
        authorization for the endpoint and action, failing as `ERR_FORBIDDEN`;
        (3) existence of path and body references, failing as `ERR_NOT_FOUND`;
        (4) the ethical-wall read gate of §2.9, failing as `ERR_WALL_EXCLUDED`;
        (5) ownership — attorney-scoped operations failing as
        `ERR_NOT_RESPONSIBLE_ATTORNEY` and client-scoped ownership mismatches
        failing as `ERR_FORBIDDEN`; (6) state and concurrency gates, failing as
        `ERR_MATTER_NOT_INTAKE`, `ERR_MATTER_NOT_OPEN`, `ERR_MATTER_TERMINAL`,
        `ERR_HIT_NOT_PENDING`, `ERR_WAIVER_INVALID_STATE`,
        `ERR_LETTER_INVALID_STATE`, `ERR_WALL_INVALID_STATE`, or
        `ERR_STALE_VERSION`; (7) business safety, failing as
        `ERR_MATTER_CLEARANCE_BLOCKED`, `ERR_SOD_SELF_APPROVAL`,
        `ERR_ATTORNEY_ADVERSE_OVERLAP`, or `ERR_ATTORNEY_NOT_ACTIVE`; (8)
        business temporal rules, failing as `ERR_LETTER_STALE`; (9) business
        referential rules, failing as `ERR_CHECK_SUPERSEDED` or
        `ERR_HIT_NOT_CONFIRMED`; (10) business constraints, failing as
        `ERR_WAIVER_ACTIVE_EXISTS`, `ERR_WALL_INVALID_STATE`,
        `ERR_ATTORNEY_ALREADY_EXCLUDED`, `ERR_ATTORNEY_NOT_EXCLUDED`, or
        `ERR_PARTY_ALREADY_ON_MATTER`; (11) business fiscal rules, failing as
        `ERR_CREDIT_MISSING`, `ERR_CREDIT_STALE`, `ERR_RETAINER_UNFUNDED`, or
        `ERR_REFUND_EXCEEDS_BALANCE`; and (12) request shape, failing as
        `ERR_INVALID_REQUEST`."

        Design: Difficulty/priority_pair_validation_conflict/clearance_safety_beats_retainer_fiscal
        """
        p_x, p_y, atty, m1 = setup_matter_with_confirmed_hit(
            "Mike November Inc", "Oscar Pine Corp"
        )
        m1_fresh = get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)
        assert m1_fresh["clearance_status"] == "BLOCKED"

        letter = _issue_letter_for_blocked_matter(m1, atty)
        deposit = get_deposit(m1["id"])
        assert deposit["status"] == "PENDING"
        assert deposit["required_cents"] == 2000000, (
            "PRIME band multiplies the 2,000,000-cent fee by 1 (floor 50,000 "
            "not binding)"
        )

        resp = api_client.transition_engagement_letter(
            letter["id"],
            transition_letter_payload("COUNTERSIGN"),
            make_client_headers(p_y["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MATTER_CLEARANCE_BLOCKED)

    def test_both_gates_fail_so_the_error_is_priority_derived(self):
        """PRD §3.7: "The matter's `clearance_status` must be `CLEARED` or
        `WAIVED`, else `ERR_MATTER_CLEARANCE_BLOCKED`."
        PRD §3.7: "And the retainer deposit must stand `FUNDED`, else
        `ERR_RETAINER_UNFUNDED`."
        PRD §2.11: "Beyond resolution, every request passes through twelve
        ordered validation tiers, and the first failure wins."

        Design: Difficulty/priority_pair_validation_conflict/clearance_safety_beats_retainer_fiscal
        """
        p_x, p_y, atty, m1 = setup_matter_with_confirmed_hit(
            "Dual Fail X Inc", "Dual Fail Y Corp"
        )
        letter = _issue_letter_for_blocked_matter(m1, atty)
        deposit = get_deposit(m1["id"])
        # Precondition: BOTH the clearance gate and the retainer gate fail.
        m1_now = get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)
        assert m1_now["clearance_status"] == "BLOCKED"
        assert deposit["status"] != "FUNDED"

        resp = api_client.transition_engagement_letter(
            letter["id"],
            transition_letter_payload("COUNTERSIGN"),
            make_client_headers(p_y["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_MATTER_CLEARANCE_BLOCKED)
        assert error["error_id"] != "ERR_RETAINER_UNFUNDED"


class TestSupersededCheckReferentialBeatsActiveWaiverConstraint:
    def _setup_hit_with_active_waiver_then_supersede(self):
        """Matter M1: CONFIRMED hit H + active DRAFT waiver W1; a roster add
        then supersedes the producing check (only PENDING hits go STALE, so H
        stays CONFIRMED)."""
        p_x = create_party("Quebec Romeo Inc")
        p_y = create_party("Sierra Tango Corp")
        p_z = create_party("Unrelated Extra LLC")
        atty = create_attorney()
        create_matter(p_x["id"], atty["id"], matter_title="M0")
        m1 = create_matter(p_y["id"], atty["id"], matter_title="M1")
        add_roster_party(m1["id"], p_x["id"], "ADVERSE")
        chk = run_conflict_check(m1["id"], "STRICT")
        hits = list_hits_for_check(chk["id"])
        hit = hits[0]
        ra = make_responsible_attorney_headers(atty["id"])
        get_success_data(
            api_client.review_conflict_hit(
                hit["id"], {"decision": "CONFIRMED"}, ra
            ),
            200,
        )
        resp = api_client.create_waiver_request(
            m1["id"],
            {"conflict_hit_id": hit["id"], "proposed_terms": "w1 terms"},
            ra,
        )
        get_success_data(resp, 201)
        # Roster add supersedes the COMPLETED INTAKE check.
        add_roster_party(m1["id"], p_z["id"], "WITNESS")
        return atty, m1, hit

    def test_waiver_create_on_superseded_check_with_active_waiver_reports_superseded(self):
        """PRD §2.11: "Beyond resolution, every request passes through twelve
        ordered validation tiers, and the first failure wins."
        PRD §2.11 (tier list): "(9) business referential rules, failing as
        `ERR_CHECK_SUPERSEDED` or `ERR_HIT_NOT_CONFIRMED`; (10) business
        constraints, failing as `ERR_WAIVER_ACTIVE_EXISTS`, ...".

        Design: Difficulty/priority_pair_validation_conflict/superseded_check_referential_beats_active_waiver_constraint
        """
        atty, m1, hit = (
            self._setup_hit_with_active_waiver_then_supersede()
        )
        resp = api_client.create_waiver_request(
            m1["id"],
            {"conflict_hit_id": hit["id"], "proposed_terms": "w2 terms"},
            make_responsible_attorney_headers(atty["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHECK_SUPERSEDED)

    def test_superseded_check_error_wins_over_active_waiver_error(self):
        """PRD §3.6: "The referenced hit must be `CONFIRMED` — anything else
        fails with `ERR_HIT_NOT_CONFIRMED` — and the check that produced it
        must not be `SUPERSEDED`, or the draft fails with
        `ERR_CHECK_SUPERSEDED`".
        PRD §3.6: "At most one waiver per hit may be active at a time, where
        active means `DRAFT`, `SENT`, `CONSENTED`, or `APPROVED`; a second
        attempt against the same hit fails with `ERR_WAIVER_ACTIVE_EXISTS`."
        PRD §2.11: "Beyond resolution, every request passes through twelve
        ordered validation tiers, and the first failure wins."

        Design: Difficulty/priority_pair_validation_conflict/superseded_check_referential_beats_active_waiver_constraint
        """
        atty, m1, hit = (
            self._setup_hit_with_active_waiver_then_supersede()
        )
        # Confirm both failure conditions hold: the check is SUPERSEDED ...
        checks = get_success_data(
            api_client.list_matter_conflict_checks(m1["id"], INTAKE), 200
        )
        assert all(c["status"] == "SUPERSEDED" for c in checks)
        # ... and an active DRAFT waiver already exists for the hit.
        waivers = get_success_data(
            api_client.list_hit_waiver_requests(
                hit["id"], make_responsible_attorney_headers(atty["id"])
            ),
            200,
        )
        assert any(w["status"] == "DRAFT" for w in waivers)

        resp = api_client.create_waiver_request(
            m1["id"],
            {"conflict_hit_id": hit["id"], "proposed_terms": "w2 terms"},
            make_responsible_attorney_headers(atty["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_CHECK_SUPERSEDED)
        assert error["error_id"] != "ERR_WAIVER_ACTIVE_EXISTS"
