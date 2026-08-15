"""Endpoint-level behaviors: wall-gate pass cases, letter ISSUE idempotence
guard, hit listing filters, empty deposit view, and client ownership reads."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_roster_party,
    api_client,
    create_attorney,
    create_matter,
    create_party,
    get_success_data,
    issue_letter,
    list_hits_for_check,
    make_client_headers,
    make_responsible_attorney_headers,
    run_conflict_check,
    setup_basic_matter,
    setup_matter_with_wall,
    setup_matter_with_issued_letter,
    transition_letter_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

INTAKE = TEST_USERS["intake_specialist_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestWallGateAllowsNonExcludedAndOpaque:
    def test_responsible_attorney_not_excluded_reads_matter(self):
        """PRD §2.9: "When the caller belongs to an entity-backed attorney role
        — `ResponsibleAttorney` or `ConflictsPartner` — and their `X-User-ID`
        appears in the `excluded_attorney_ids` of any `ACTIVE` EthicalWall on
        the requested matter, the read is denied with `ERR_WALL_EXCLUDED`
        (HTTP 403). Callers in opaque roles and the matter's own client are
        never wall-blocked."

        Design: Corner/endpoints/c_wall_gate_allows_non_excluded_and_opaque
        """
        party, atty_r, atty_x, partner, matter, wall = setup_matter_with_wall(
            "Gate Client Inc", reason="CONFLICT_CONFIRMED"
        )
        # The wall excludes atty_x, NOT the responsible attorney.
        assert wall["excluded_attorney_ids"] == [atty_x["id"]]

        resp = api_client.get_matter(
            matter["id"], make_responsible_attorney_headers(atty_r["id"])
        )
        data = validate_success(resp, 200)
        assert data["id"] == matter["id"]

    def test_opaque_role_is_never_wall_blocked(self):
        """PRD §2.9: "Callers in opaque roles and the matter's own client are
        never wall-blocked."

        Design: Corner/endpoints/c_wall_gate_allows_non_excluded_and_opaque
        """
        party, atty_r, atty_x, partner, matter, wall = setup_matter_with_wall(
            "Gate Client Inc", reason="CONFLICT_CONFIRMED"
        )
        resp = api_client.get_matter(matter["id"], INTAKE)
        data = validate_success(resp, 200)
        assert data["id"] == matter["id"]


class TestLetterIssueTwiceInvalidState:
    def test_second_issue_on_same_letter_fails(self):
        """PRD §3.7: "Issuing is the responsible attorney's act: an `ISSUE`
        action requires the letter to be `DRAFT` (otherwise
        `ERR_LETTER_INVALID_STATE`), the matter still `INTAKE` (otherwise
        `ERR_MATTER_NOT_INTAKE`), and a `ResponsibleAttorney` caller to be the
        matter's `responsible_attorney_id` (otherwise
        `ERR_NOT_RESPONSIBLE_ATTORNEY`)."

        Design: Corner/endpoints/c_letter_issue_twice_invalid_state
        """
        party, atty, matter = setup_basic_matter("Issue Client Inc")
        from test_helpers import create_letter

        letter = create_letter(matter, atty)
        ra = make_responsible_attorney_headers(atty["id"])
        first = validate_success(
            api_client.transition_engagement_letter(
                letter["id"], transition_letter_payload("ISSUE"), ra
            ),
            200,
        )
        assert first["status"] == "ISSUED"

        resp = api_client.transition_engagement_letter(
            letter["id"], transition_letter_payload("ISSUE"), ra
        )
        validate_error(resp, ApiErrorId.ERR_LETTER_INVALID_STATE)


class TestFilteredHitsByMatter:
    def test_hits_filtered_by_matched_matter_id(self):
        """PRD §3.4: "The listing endpoint accepts the filters `check_id`,
        `matched_party_id`, `matched_matter_id`, and `review_status`, which
        also serve as the reverse reach from a check, party, or matter to its
        hits."

        Design: Corner/endpoints/c_filtered_hits_by_matter
        """
        p_a = create_party("Shared Name One Inc")
        p_b = create_party("Shared Name Two Inc")
        p_c = create_party("Third Client Corp")
        atty = create_attorney()
        ma = create_matter(p_a["id"], atty["id"], practice_group="LITIGATION",
                           matter_title="MA")
        create_matter(p_b["id"], atty["id"], practice_group="CORPORATE",
                      matter_title="MB")
        mc = create_matter(p_c["id"], atty["id"], practice_group="IP",
                           matter_title="MC")
        add_roster_party(mc["id"], p_a["id"], "ADVERSE")
        add_roster_party(mc["id"], p_b["id"], "ADVERSE")
        check = run_conflict_check(mc["id"], "STRICT")
        assert check["hit_count"] == 2, (
            "one hit against MA's client, one against MB's"
        )

        hits, meta = validate_paginated(
            api_client.list_conflict_hits(
                INTAKE, params={"matched_matter_id": ma["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert hits[0]["matched_matter_id"] == ma["id"]
        assert hits[0]["matched_party_id"] == p_a["id"]


class TestRetainerDepositEmptyBeforeIssue:
    def test_deposit_list_is_empty_array_before_any_issue(self):
        """PRD §3.8: "The deposit view returns an array of zero or one element
        for the matter, created only at first issuance, and an owning `Client`
        may read it for its own matters."

        Design: Corner/endpoints/c_retainer_deposit_empty_before_issue
        """
        _, _, matter = setup_basic_matter("Empty Dep Client Inc")
        resp = api_client.list_matter_retainer_deposits(matter["id"], BILLING)
        data = validate_success(resp, 200)
        assert data == [], "no letter ISSUE yet -> deposit list is empty"


class TestClientReadOtherMatterForbidden:
    def test_client_reading_another_partys_matter_forbidden(self):
        """PRD §3.3: "Reading a single matter is subject to the wall gate of
        §2.9, and a `Client` caller may read only matters where its `X-User-ID`
        equals the matter's `client_party_id` — any other matter read by a
        client fails with `ERR_FORBIDDEN`."

        Design: Corner/endpoints/c_client_read_other_matter_forbidden
        """
        p1 = create_party("Owner Client Inc")
        p2 = create_party("Stranger Party Corp")
        atty = create_attorney()
        matter = create_matter(p1["id"], atty["id"], matter_title="M")

        resp = api_client.get_matter(matter["id"], make_client_headers(p2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
