"""Ownership claims and the return pipeline: claim guards, the approval cascade,
sibling-match expiry (PRD §3.5, §3.6)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    register_owner,
    register_bicycle,
    owner_headers,
    file_theft_report,
    flag_report,
    create_active_partner_org,
    partner_headers,
    create_intake,
    scan_intake,
    get_matches_for_intake,
    get_notifications_for_owner,
    setup_notified_match,
    create_claim_for_match,
    create_claim_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def _two_match_scenario(api):
    """Two owners with similar-but-not-duplicate bicycles (confidence 7500, no
    auto-flag), both reports FLAGGED; one intake matching both — matches m1
    (screening 10000) and m2 (screening 9167), both NOTIFIED."""
    set_clock("2026-05-01T00:00:00Z")
    owner1 = register_owner("o1@x.com", "O One")
    owner2 = register_owner("o2@x.com", "O Two")
    bicycle1 = register_bicycle(
        owner1, serial_number="MCH100", manufacturer="Trek", model="FX",
        primary_color="Red", declared_value_cents=60000, photo_url="https://x/1.jpg",
    )
    bicycle2 = register_bicycle(
        owner2, serial_number="MCH200", manufacturer="Trek", model="Escape",
        primary_color="Red", declared_value_cents=55000, photo_url="https://x/2.jpg",
    )
    report1 = file_theft_report(owner1, bicycle1, occurred_at="2026-05-10T00:00:00Z")
    report2 = file_theft_report(owner2, bicycle2, occurred_at="2026-05-10T00:00:00Z")
    flag_report(report1["id"])
    flag_report(report2["id"])
    org = create_active_partner_org()
    intake = create_intake(
        org, serial_number_raw="MCH100", primary_color="Red",
        found_at="2026-05-12T00:00:00Z", appraised_value_cents=40000,
        manufacturer="Trek",
    )
    scan_intake(intake["id"], partner_headers(org))
    matches = get_matches_for_intake(intake["id"])
    assert len(matches) == 2, f"expected 2 matches, got {len(matches)}"
    by_report = {m["theft_report_id"]: m for m in matches}
    match1 = by_report[report1["id"]]
    match2 = by_report[report2["id"]]
    assert match1["status"] == "NOTIFIED" and match2["status"] == "NOTIFIED"
    claim1 = validate_success(
        api.create_claim(
            create_claim_payload(intake["id"], match1["id"], proof_text="receipt o1"),
            owner_headers(owner1),
        ),
        expected_status=201,
    )
    claim2 = validate_success(
        api.create_claim(
            create_claim_payload(intake["id"], match2["id"], proof_text="receipt o2"),
            owner_headers(owner2),
        ),
        expected_status=201,
    )
    return {
        "owner1": owner1, "owner2": owner2,
        "bicycle1": bicycle1, "bicycle2": bicycle2,
        "report1": report1, "report2": report2,
        "org": org, "intake": intake,
        "match1": match1, "match2": match2,
        "claim1": claim1, "claim2": claim2,
    }


class TestClaimApprovalCascade:
    def test_claim_approval_cascade_match_intake_bicycle_report(self, api):
        """PRD §3.6: "On approval the chain fires in order: the match moves from
        `NOTIFIED` to `CONFIRMED`; the intake moves from `INTAKE` to
        `CLAIM_PENDING`; the bicycle's `registry_status` moves from `STOLEN` to
        `RECOVERED`; the theft report moves from `FLAGGED` to `CLOSED_RECOVERED`;
        every other match candidate on the same intake still in `PROPOSED` or
        `NOTIFIED` moves to `EXPIRED`; a `CLAIM_APPROVED` notification is created
        for the claiming owner;"

        Design: Difficulty/transitive_cascade/claim_approval_cascade_match_intake_bicycle_report
        """
        scenario = setup_notified_match(serial="CSC200", photo_hash="1111222233334444")
        claim = create_claim_for_match(scenario)
        approved = validate_success(api.approve_claim(claim["id"], REGISTRAR))
        assert approved["status"] == "APPROVED"
        match = validate_success(api.get_match(scenario["match"]["id"], REGISTRAR))
        assert match["status"] == "CONFIRMED", "link 1: match must be CONFIRMED"
        intake = validate_success(api.get_recovery_intake(scenario["intake"]["id"], REGISTRAR))
        assert intake["status"] == "CLAIM_PENDING", (
            "link 2: intake must flip to CLAIM_PENDING"
        )
        bicycle = validate_success(api.get_bicycle(scenario["bicycle"]["id"], REGISTRAR))
        assert bicycle["registry_status"] == "RECOVERED", (
            "link 3: bicycle must flip STOLEN -> RECOVERED"
        )
        report = validate_success(api.get_theft_report(scenario["report"]["id"], REGISTRAR))
        assert report["status"] == "CLOSED_RECOVERED", (
            "link 3 sibling: report must flip FLAGGED -> CLOSED_RECOVERED"
        )

    def test_claim_approval_expires_sibling_matches_and_notifies(self, api):
        """PRD §3.6: "every other match candidate on the same intake still in
        `PROPOSED` or `NOTIFIED` moves to `EXPIRED`; a `CLAIM_APPROVED` notification
        is created for the claiming owner; and every row in the chain — claim,
        match, intake, bicycle, report, sibling matches — has its own `version`
        incremented."

        Design: Difficulty/transitive_cascade/claim_approval_cascade_match_intake_bicycle_report
        """
        s = _two_match_scenario(api)
        validate_success(api.approve_claim(s["claim1"]["id"], REGISTRAR))
        sibling = validate_success(api.get_match(s["match2"]["id"], REGISTRAR))
        assert sibling["status"] == "EXPIRED", (
            f"sibling match must move to EXPIRED, got {sibling['status']}"
        )
        assert sibling["version"] == s["match2"]["version"] + 1, (
            "the sibling match's own version must increment"
        )
        notifications = get_notifications_for_owner(s["owner1"]["id"])
        kinds = [n["kind"] for n in notifications]
        assert "CLAIM_APPROVED" in kinds, (
            f"claiming owner must receive CLAIM_APPROVED, got {kinds}"
        )


class TestClaimGuards:
    def test_claim_create_on_dismissed_match_rejected(self, api):
        """PRD §3.6: "The referenced match must be in `NOTIFIED` status (otherwise
        `ERR_MATCH_NOT_OPEN`),"

        Design: Corner/errors/claim_create_on_dismissed_match_rejected
        """
        scenario = setup_notified_match(serial="DMS100")
        validate_success(api.dismiss_match(scenario["match"]["id"], REGISTRAR))
        resp = api.create_claim(
            create_claim_payload(
                scenario["intake"]["id"], scenario["match"]["id"], proof_text="receipt"
            ),
            owner_headers(scenario["owner"]),
        )
        validate_error(resp, ApiErrorId.ERR_MATCH_NOT_OPEN, expected_status=409)

    def test_second_under_review_claim_same_match_rejected(self, api):
        """PRD §3.6: "At most one `UNDER_REVIEW` claim may exist per match; a
        duplicate filing fails with `ERR_CLAIM_ALREADY_EXISTS`."

        Design: Corner/errors/second_under_review_claim_same_match_rejected
        """
        scenario = setup_notified_match(serial="CLX100")
        create_claim_for_match(scenario, proof_text="receipt")
        resp = api.create_claim(
            create_claim_payload(
                scenario["intake"]["id"], scenario["match"]["id"], proof_text="more proof"
            ),
            owner_headers(scenario["owner"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_EXISTS, expected_status=409)

    def test_second_claim_approval_blocked_by_intake_state(self, api):
        """PRD §3.6: "the intake is still `INTAKE` — the first approved claim wins,
        and a second approval attempt against an intake that has moved on fails
        with `ERR_RECOVERY_NOT_ACTIONABLE`;"

        Design: Corner/errors/second_claim_approval_blocked_by_intake_state
        """
        s = _two_match_scenario(api)
        validate_success(api.approve_claim(s["claim1"]["id"], REGISTRAR))
        resp = api.approve_claim(s["claim2"]["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_RECOVERY_NOT_ACTIONABLE, expected_status=409)

    def test_approve_terminal_claim_rejected(self, api):
        """PRD §3.6: "a `Registrar` performs it only when four conditions hold,
        each with its own rejection: the claim is `UNDER_REVIEW` (otherwise
        `ERR_CLAIM_NOT_REVIEWABLE`);"

        Design: Corner/errors/approve_terminal_claim_rejected
        """
        scenario = setup_notified_match(serial="CTR100")
        claim = create_claim_for_match(scenario, proof_text="receipt")
        rejected = validate_success(
            api.reject_claim(claim["id"], {"reason_text": "insufficient proof"}, REGISTRAR)
        )
        assert rejected["status"] == "REJECTED"
        resp = api.approve_claim(claim["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE, expected_status=409)

    def test_partner_cannot_approve_claim(self, api):
        """PRD §4: POST /registry/claims/{id}/approve is authorized for Registrar
        only.
        PRD §2.1: "A request whose role is well-formed but not permitted for the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/partner_cannot_approve_claim
        """
        scenario = setup_notified_match(serial="RBC200")
        claim = create_claim_for_match(scenario, proof_text="receipt")
        resp = api.approve_claim(claim["id"], partner_headers(scenario["org"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
