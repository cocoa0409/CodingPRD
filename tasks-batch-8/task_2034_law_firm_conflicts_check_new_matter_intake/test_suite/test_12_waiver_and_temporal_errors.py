"""Waiver error paths and countersign temporal boundaries."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_roster_party,
    api_client,
    create_attorney,
    create_letter,
    create_matter,
    create_party,
    fund_deposit,
    get_deposit,
    get_success_data,
    issue_letter,
    list_hits_for_check,
    make_client_headers,
    make_conflicts_partner_headers,
    make_responsible_attorney_headers,
    record_credit_assessment,
    run_conflict_check,
    send_waiver,
    set_clock,
    setup_countersign_ready,
    setup_matter_with_waiver,
    transition_letter_payload,
    transition_waiver_payload,
    validate_error,
    validate_success,
)

INTAKE = TEST_USERS["intake_specialist_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestWaiverCreateOnDismissedHit:
    def test_waiver_for_dismissed_hit_fails_not_confirmed(self):
        """PRD §3.6: "The referenced hit must be `CONFIRMED` — anything else
        fails with `ERR_HIT_NOT_CONFIRMED` — and the check that produced it
        must not be `SUPERSEDED`, or the draft fails with
        `ERR_CHECK_SUPERSEDED`".

        Design: Corner/errors/c_waiver_create_on_dismissed_hit
        """
        p_x = create_party("Dismissed X Inc")
        p_y = create_party("Dismissed Y Corp")
        atty = create_attorney()
        create_matter(p_x["id"], atty["id"], matter_title="M0")
        m1 = create_matter(p_y["id"], atty["id"], matter_title="M1")
        add_roster_party(m1["id"], p_x["id"], "ADVERSE")
        chk = run_conflict_check(m1["id"], "STRICT")
        hit = list_hits_for_check(chk["id"])[0]
        ra = make_responsible_attorney_headers(atty["id"])
        get_success_data(
            api_client.review_conflict_hit(
                hit["id"], {"decision": "DISMISSED"}, ra
            ),
            200,
        )

        resp = api_client.create_waiver_request(
            m1["id"], {"conflict_hit_id": hit["id"], "proposed_terms": "t"}, ra
        )
        validate_error(resp, ApiErrorId.ERR_HIT_NOT_CONFIRMED)


class TestConsentOnDraftWaiverInvalid:
    def test_record_consent_on_draft_waiver_fails(self):
        """PRD §3.6: "From `SENT`, the ball is with the client. The caller's
        `X-User-ID` must equal the matter's `client_party_id`, or the attempt
        fails with `ERR_FORBIDDEN`. Recording consent — a `RECORD_CONSENT`
        action — requires a `consent_document_ref` (its absence fails with
        `ERR_INVALID_REQUEST`), stores the reference, and moves the waiver to
        `CONSENTED`."
        PRD §3.6: "A `SEND` action requires the waiver to be in `DRAFT`
        (otherwise `ERR_WAIVER_INVALID_STATE`)".

        Design: Corner/errors/c_consent_on_draft_waiver_invalid
        """
        p_x, p_y, atty, m1, hit, waiver = setup_matter_with_waiver(
            "Consent X Inc", "Consent Y Corp"
        )
        assert waiver["status"] == "DRAFT"
        resp = api_client.transition_waiver_request(
            waiver["id"],
            transition_waiver_payload(
                "RECORD_CONSENT", consent_document_ref="doc-1"
            ),
            make_client_headers(p_y["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_INVALID_STATE)


class TestWaiverExpiryInclusiveBoundary:
    def _two_sent_waivers(self):
        """Two matters each with a CONFIRMED hit and a SENT waiver."""
        set_clock("2026-08-01T00:00:00Z")
        p_x = create_party("Expiry X Inc")
        p_y = create_party("Expiry Y Corp")
        p_z = create_party("Expiry Z LLC")
        atty = create_attorney()
        create_matter(p_x["id"], atty["id"], matter_title="M0")

        m1 = create_matter(p_y["id"], atty["id"], matter_title="M1")
        add_roster_party(m1["id"], p_x["id"], "ADVERSE")
        chk1 = run_conflict_check(m1["id"], "STRICT")
        h1 = list_hits_for_check(chk1["id"])[0]
        ra = make_responsible_attorney_headers(atty["id"])
        get_success_data(
            api_client.review_conflict_hit(h1["id"], {"decision": "CONFIRMED"}, ra),
            200,
        )
        w1 = get_success_data(
            api_client.create_waiver_request(
                m1["id"], {"conflict_hit_id": h1["id"], "proposed_terms": "t"}, ra
            ),
            201,
        )
        w1_sent = send_waiver(w1["id"], atty)

        m2 = create_matter(p_z["id"], atty["id"], matter_title="M2")
        add_roster_party(m2["id"], p_x["id"], "ADVERSE")
        chk2 = run_conflict_check(m2["id"], "STRICT")
        h2 = list_hits_for_check(chk2["id"])[0]
        get_success_data(
            api_client.review_conflict_hit(h2["id"], {"decision": "CONFIRMED"}, ra),
            200,
        )
        w2 = get_success_data(
            api_client.create_waiver_request(
                m2["id"], {"conflict_hit_id": h2["id"], "proposed_terms": "t"}, ra
            ),
            201,
        )
        send_waiver(w2["id"], atty)
        return p_y, p_z, atty, m1, w1, w1_sent, w2

    def test_consent_one_day_before_expiry_succeeds(self):
        """PRD §3.6: "Meanwhile the clock watches the deadline: a waiver still
        `SENT` when the logical clock reaches or passes `expires_at` is swept
        to `EXPIRED` by the next clock-set, the boundary inclusive, and the
        sweep never alters clearance because a `SENT` waiver has waived nothing
        yet."

        Design: Corner/errors/c_waiver_expiry_inclusive_boundary
        """
        p_y, p_z, atty, m1, w1, w1_sent, w2 = self._two_sent_waivers()
        assert w1_sent["expires_at"] == "2026-08-31T00:00:00.000Z", (
            "sent 2026-08-01 + 30 days"
        )

        set_clock("2026-08-30T00:00:00Z")
        consented = validate_success(
            api_client.transition_waiver_request(
                w2["id"],
                transition_waiver_payload(
                    "RECORD_CONSENT", consent_document_ref="doc-w2"
                ),
                make_client_headers(p_z["id"]),
            ),
            200,
        )
        assert consented["status"] == "CONSENTED", (
            "one day before expiry the waiver is still SENT and consent succeeds"
        )

    def test_consent_at_exact_expiry_fails_after_inclusive_sweep(self):
        """PRD §2.5: "Setting the clock performs a waiver-expiry sweep: every
        waiver still `SENT` whose `expires_at` is less than or equal to the new
        current time transitions to `EXPIRED` — the boundary is inclusive, so a
        waiver expiring exactly at the new time is swept."
        PRD §3.6: "A consent attempt arriving after the sweep fails with
        `ERR_WAIVER_INVALID_STATE`, since the waiver is no longer `SENT`."

        Design: Corner/errors/c_waiver_expiry_inclusive_boundary
        """
        p_y, p_z, atty, m1, w1, w1_sent, w2 = self._two_sent_waivers()
        set_clock("2026-08-31T00:00:00Z")

        resp = api_client.transition_waiver_request(
            w1["id"],
            transition_waiver_payload(
                "RECORD_CONSENT", consent_document_ref="doc-w1"
            ),
            make_client_headers(p_y["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_INVALID_STATE)

        waivers = get_success_data(
            api_client.list_matter_waiver_requests(
                m1["id"], make_conflicts_partner_headers(atty["id"])
            ),
            200,
        )
        assert waivers[0]["status"] == "EXPIRED", (
            "at exactly expires_at the inclusive sweep fires"
        )


class TestTemporalBoundariesLetter30Credit90:
    def _setup_three_matters_with_staggered_issue(self):
        """MA issued at day 60 (2026-09-30), MB at day 60, MC at day 61
        (2026-10-01); all with credit assessed at day 0 (2026-08-01), all
        deposits FUNDED 2,000,000.

        Each matter gets its OWN client party: under PRD section 3.4 the
        candidate pool is every party appearing on any OTHER INTAKE/OPEN
        matter, so a shared client would direct-match (score 100) across the
        sibling matters and leave them HITS_PENDING instead of CLEARED. The
        three names share only the token "temporal" (overlap 1/2 = 50 < 80),
        so each STRICT check is a zero-hit clearing check."""
        set_clock("2026-08-01T00:00:00Z")
        atty = create_attorney()
        parties = {}
        matters = {}
        letters = {}
        for key, group, cname in (
                ("ma", "LITIGATION", "Temporal Alpha Corp"),
                ("mb", "CORPORATE", "Temporal Beta LLC"),
                ("mc", "TAX", "Temporal Gamma Inc")):
            p = create_party(cname)
            m = create_matter(p["id"], atty["id"], practice_group=group,
                              matter_title=key.upper())
            run_conflict_check(m["id"], "STRICT")
            record_credit_assessment(m["id"], 800)
            parties[key] = p
            matters[key] = m

        set_clock("2026-09-30T00:00:00Z")
        for key in ("ma", "mb"):
            letter = create_letter(matters[key], atty)
            issue_letter(letter["id"], atty)
            fund_deposit(get_deposit(matters[key]["id"])["id"], 2000000)
            letters[key] = letter

        set_clock("2026-10-01T00:00:00Z")
        letter = create_letter(matters["mc"], atty)
        issue_letter(letter["id"], atty)
        fund_deposit(get_deposit(matters["mc"]["id"])["id"], 2000000)
        letters["mc"] = letter
        return parties, atty, matters, letters

    def test_letter_exactly_30_days_and_credit_exactly_90_days_countersigns(self):
        """PRD §3.7: "The letter must not be stale: the current logical time
        must be at most thirty days after `issued_at` — exactly thirty days is
        still countersignable, anything later fails with `ERR_LETTER_STALE`."
        PRD §3.8: "An assessment remains valid for ninety days: it is stale
        only when the current logical time is strictly later than `assessed_at`
        plus ninety days, so an assessment exactly ninety days old is still
        valid."

        Design: Corner/errors/c_temporal_boundaries_letter30_credit90
        """
        parties, atty, matters, letters = (
            self._setup_three_matters_with_staggered_issue()
        )
        set_clock("2026-10-30T00:00:00Z")
        signed = validate_success(
            api_client.transition_engagement_letter(
                letters["ma"]["id"],
                transition_letter_payload("COUNTERSIGN"),
                make_client_headers(parties["ma"]["id"]),
            ),
            200,
        )
        assert signed["status"] == "COUNTERSIGNED", (
            "letter exactly 30 days old and credit exactly 90 days old are "
            "both still valid — strict staleness"
        )

    def test_letter_31_days_old_fails_letter_stale(self):
        """PRD §3.7: "The letter must not be stale: the current logical time
        must be at most thirty days after `issued_at` — exactly thirty days is
        still countersignable, anything later fails with `ERR_LETTER_STALE`."
        PRD §2.11: "Beyond resolution, every request passes through twelve
        ordered validation tiers, and the first failure wins."

        Design: Corner/errors/c_temporal_boundaries_letter30_credit90
        """
        parties, atty, matters, letters = (
            self._setup_three_matters_with_staggered_issue()
        )
        set_clock("2026-10-31T00:00:00Z")
        resp = api_client.transition_engagement_letter(
            letters["mb"]["id"],
            transition_letter_payload("COUNTERSIGN"),
            make_client_headers(parties["mb"]["id"]),
        )
        # MB's letter was issued 2026-09-30 (31 days before), and its credit
        # (2026-08-01) is 91 days stale too — temporal tier 8 beats fiscal 11.
        validate_error(resp, ApiErrorId.ERR_LETTER_STALE)

    def test_letter_30_days_old_with_credit_91_days_fails_credit_stale(self):
        """PRD §3.7: "The latest assessment must still be valid under the
        ninety-day rule of §3.8, else `ERR_CREDIT_STALE`."
        PRD §3.8: "An assessment remains valid for ninety days: it is stale
        only when the current logical time is strictly later than `assessed_at`
        plus ninety days, so an assessment exactly ninety days old is still
        valid."

        Design: Corner/errors/c_temporal_boundaries_letter30_credit90
        """
        parties, atty, matters, letters = (
            self._setup_three_matters_with_staggered_issue()
        )
        set_clock("2026-10-31T00:00:00Z")
        resp = api_client.transition_engagement_letter(
            letters["mc"]["id"],
            transition_letter_payload("COUNTERSIGN"),
            make_client_headers(parties["mc"]["id"]),
        )
        # MC's letter is exactly 30 days old (fine); its credit is 91 days old.
        validate_error(resp, ApiErrorId.ERR_CREDIT_STALE)


class TestCreditMissingBlocksCountersign:
    def test_countersign_without_any_assessment_fails_credit_missing(self):
        """PRD §3.7: "At least one credit assessment must exist for the matter,
        else `ERR_CREDIT_MISSING`."
        PRD §3.8: "The governing band is the band of the valid assessment with
        the latest `assessed_at`, with a tie on `assessed_at` broken in favor
        of the later `created_at`; when no valid assessment exists, the band
        defaults conservatively to `SUBPRIME`."

        Design: Corner/errors/c_credit_missing_blocks_countersign
        """
        # No assessment: required = 2,000,000 x 3 = 6,000,000 (SUBPRIME).
        party, atty, matter, letter, deposit = setup_countersign_ready(
            "No Credit Client Inc", score=None, fund_amount=6000000
        )
        assert deposit["required_cents"] == 6000000
        assert deposit["status"] == "FUNDED", "fiscal retainer gate passes"

        resp = api_client.transition_engagement_letter(
            letter["id"],
            transition_letter_payload("COUNTERSIGN"),
            make_client_headers(party["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_MISSING)


class TestRetainerUnfundedBlocksCountersign:
    def test_partially_funded_deposit_blocks_countersign(self):
        """PRD §3.7: "And the retainer deposit must stand `FUNDED`, else
        `ERR_RETAINER_UNFUNDED`."

        Design: Corner/errors/c_retainer_unfunded_blocks_countersign
        """
        party, atty, matter, letter, deposit = setup_countersign_ready(
            "Unfunded Client Inc", score=800, fund_amount=1000000
        )
        assert deposit["status"] == "PARTIALLY_FUNDED"

        resp = api_client.transition_engagement_letter(
            letter["id"],
            transition_letter_payload("COUNTERSIGN"),
            make_client_headers(party["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RETAINER_UNFUNDED)
