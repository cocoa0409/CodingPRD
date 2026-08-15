"""Assignments: initial state, word-count floor, kill-fee tiers, lateness
halving, per-word final-count basis, listing filters, and the logical clock."""
from test_helpers import (
    ApiErrorId,
    accept_for_publication,
    adjudicate_report,
    assert_assignment,
    bootstrap_desk,
    clear_all_reports,
    create_assignment,
    create_contributor,
    get_assignment,
    get_success_data,
    kill_assignment,
    list_reports,
    make_contributor_headers,
    record_result,
    set_clock,
    setup_assignment_in_state,
    setup_contributor_with_agreement,
    setup_under_verification_cleared,
    submit_assignment,
    validate_error,
    validate_paginated,
    validate_success,
    walk_assignment,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["desk_admin_headers"]
EDITOR = TEST_USERS["editor_headers"]


def test_new_assignment_starts_in_draft_uninvoiced(api):
    """PRD section 3.3: "The new record starts in `DRAFT` editorial status
    with `payment_status` `UNINVOICED`."
    PRD section 3.3: "Its `final_word_count` is null until acceptance,
    `kill_fee_tier` is null until a kill, `agreed_fee_cents` is zero until
    offer, `final_fee_cents` is null until a terminal editorial state,
    `verification_cleared` is false, and `late_flag` is false."

    Design: Corner/state_machines/assignment_initial_state_draft
    """
    bootstrap_desk()
    contributor = create_contributor(legal_name="Init Ivy",
                                     email="ivy@x.com")
    resp = api.create_assignment(
        {"contributor_id": contributor["id"], "title": "IS", "brief": "b",
         "commissioned_word_count": 500,
         "deadline_utc": "2026-08-10T00:00:00Z"},
        EDITOR)
    data = validate_success(resp, 201)
    assert_assignment(data)
    assert data["editorial_status"] == "DRAFT"
    assert data["payment_status"] == "UNINVOICED"
    assert data["agreed_fee_cents"] == 0
    assert data["final_fee_cents"] is None
    assert data["final_word_count"] is None
    assert data["kill_fee_tier"] is None
    assert data["verification_cleared"] is False
    assert data["late_flag"] is False


def test_assignment_below_minimum_word_count_rejected(api):
    """PRD section 3.3: "An `Editor` drafts an assignment with the
    commissioned `contributor_id`, a working `title`, the `brief` body, a
    `commissioned_word_count` of at least 100 words, and a `deadline_utc`
    filing deadline."
    PRD section 3.11: "Then the constraint family: the receipt gate
    (`ERR_RECEIPT_REQUIRED`) on expense submission, amount sanity
    (`ERR_INVALID_AMOUNT`) on expense creation and submission, email
    uniqueness (`ERR_DUPLICATE_EMAIL`) on contributor creation, generic
    field-shape (`ERR_INVALID_REQUEST`) across the surface, the
    rate-agreement window (`ERR_INVALID_WINDOW`) on agreement creation,
    rights reusability (`ERR_RIGHTS_NOT_REUSABLE`) on record-reuse, batch
    openness (`ERR_BATCH_NOT_OPEN`) on add-invoice and lock."

    Design: Corner/entities/assignment_min_word_count
    """
    bootstrap_desk()
    contributor = create_contributor(legal_name="Word Wendy",
                                     email="wendy@x.com")
    resp = api.create_assignment(
        {"contributor_id": contributor["id"], "title": "t", "brief": "b",
         "commissioned_word_count": 99,
         "deadline_utc": "2026-08-10T00:00:00Z"},
        EDITOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_kill_from_rejected_after_flag_terminal_fails(api):
    """PRD section 3.4: "An `Editor` may kill an assignment from `OFFERED`,
    `ACCEPTED`, or `IN_PROGRESS`" and "Killing from `UNDER_VERIFICATION` is a
    post-delivery kill" — no kill transition exists from
    `REJECTED_AFTER_FLAG`.
    PRD section 3.11: "Authentication comes first (missing or malformed
    headers yield `ERR_UNAUTHENTICATED`), then role authorization
    (`ERR_FORBIDDEN_ROLE`), then path existence left-to-right
    (`ERR_NOT_FOUND`), then state-machine legality including terminal-state
    lockdown (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/kill_from_terminal_rejected_after_flag_fails
    """
    contributor, _agr, assignment = setup_assignment_in_state(
        "UNDER_VERIFICATION", legal_name="Term Ted", email="ted@x.com")
    reports = list_reports(assignment["id"])
    ai_report = reports[1]
    record_result(ai_report["id"], 0, 9000, user_id="ve-rec")
    adjudicate_report(ai_report["id"], "CONFIRMED_VIOLATION",
                      note="confirmed", user_id="ve-adj")
    assert (get_assignment(assignment["id"])["editorial_status"]
            == "REJECTED_AFTER_FLAG")

    resp = api.kill_assignment(assignment["id"], EDITOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_default_clock_submission_is_not_late(api):
    """PRD section 2.5: "At server startup the clock reads exactly
    2026-08-01T00:00:00Z; it never falls back to wall-clock time."
    PRD section 3.3: "Submission moves the assignment to `SUBMITTED`, sets
    `late_flag` to true exactly when the submission time is later than
    `deadline_utc`, and then immediately auto-advances to
    `UNDER_VERIFICATION`."

    Design: Corner/cross_cutting_layers/clock_default_startup_time
    """
    contributor, _agr, assignment = setup_assignment_in_state(
        "IN_PROGRESS", legal_name="Clock Cleo", email="cleo@x.com",
        deadline_utc="2026-08-10T00:00:00Z")
    submitted = validate_success(
        api.submit_assignment(
            assignment["id"],
            make_contributor_headers(contributor["id"])))
    assert submitted["late_flag"] is False, (
        "logical clock at startup default 2026-08-01T00:00:00Z, before the "
        "2026-08-10 deadline")
    assert submitted["editorial_status"] == "UNDER_VERIFICATION"


class TestKillFeeTierDivergence:
    """Identical agreed fees diverge purely by the editorial state the kill
    fires from."""

    def test_pre_delivery_kill_pays_25_percent(self, api):
        """PRD section 3.4: "An `Editor` may kill an assignment from
        `OFFERED`, `ACCEPTED`, or `IN_PROGRESS`: the kill is a pre-delivery
        kill, so `kill_fee_tier` becomes `PRE_DELIVERY` and `final_fee_cents`
        is the kill-variant result."
        PRD section 3.4: "The tier percentage is 25 when `kill_fee_tier` is
        `PRE_DELIVERY`, or the desk's `kill_fee_post_delivery_pct_num`
        (default 50) when `POST_DELIVERY`. The fee is the agreed fee
        multiplied by the tier percentage and divided by 100, using floor
        division."

        Design: Difficulty/dual_variant_calc/kill_fee_tier_divergence_on_assignment
        """
        contributor, _agr, assignment = setup_assignment_in_state(
            "IN_PROGRESS", legal_name="Alice Pre", email="alice@x.com",
            pricing_mode="PER_WORD", per_word_rate_cents=75,
            commissioned_word_count=1200)
        assert assignment["agreed_fee_cents"] == 90000

        killed = validate_success(api.kill_assignment(assignment["id"],
                                                      EDITOR))
        assert killed["editorial_status"] == "KILLED"
        assert killed["kill_fee_tier"] == "PRE_DELIVERY"
        assert killed["final_fee_cents"] == 22500, "floor(90000 * 25 / 100)"
        assert killed["payment_status"] == "UNINVOICED"

    def test_post_delivery_kill_pays_50_percent(self, api):
        """PRD section 3.4: "Killing from `UNDER_VERIFICATION` is a
        post-delivery kill: `kill_fee_tier` becomes `POST_DELIVERY`,
        `final_fee_cents` follows the kill variant with the halving rule when
        the submission was late, and `verification_cleared` remains false
        unless every report is already `CLEARED` or `DISMISSED`."
        PRD section 3.4: "The tier percentage is 25 when `kill_fee_tier` is
        `PRE_DELIVERY`, or the desk's `kill_fee_post_delivery_pct_num`
        (default 50) when `POST_DELIVERY`. The fee is the agreed fee
        multiplied by the tier percentage and divided by 100, using floor
        division."

        Design: Difficulty/dual_variant_calc/kill_fee_tier_divergence_on_assignment
        """
        contributor, _agr, assignment, _reports = (
            setup_under_verification_cleared(
                legal_name="Bob Post", email="bob@x.com",
                pricing_mode="PER_WORD", per_word_rate_cents=75,
                commissioned_word_count=1200))
        assert assignment["agreed_fee_cents"] == 90000

        killed = validate_success(api.kill_assignment(assignment["id"],
                                                      EDITOR))
        assert killed["kill_fee_tier"] == "POST_DELIVERY"
        assert killed["final_fee_cents"] == 45000, "floor(90000 * 50 / 100)"
        # The dual-variant divergence: identical agreed fee, different tier.
        assert killed["final_fee_cents"] != 22500


class TestLateKillHalving:

    def test_late_post_delivery_kill_halved(self, api):
        """PRD section 3.4: "When `late_flag` is true and the tier is
        `POST_DELIVERY`, the result is halved again — floor-divided by 2 — as
        the late-delivery kill penalty."
        PRD section 3.3: "Submission moves the assignment to `SUBMITTED`, sets
        `late_flag` to true exactly when the submission time is later than
        `deadline_utc`, and then immediately auto-advances to
        `UNDER_VERIFICATION`."

        Design: Difficulty/combinatorial_formula/kill_fee_late_halving_mode_a
        """
        contributor, _agr, assignment = setup_assignment_in_state(
            "IN_PROGRESS", legal_name="Late Larry", email="larry@x.com",
            pricing_mode="PER_WORD", per_word_rate_cents=100,
            commissioned_word_count=1400, deadline_utc="2026-08-05T00:00:00Z")
        set_clock("2026-08-06T00:00:00Z")  # one day past deadline
        submitted = submit_assignment(assignment["id"], contributor["id"])
        assert submitted["late_flag"] is True
        clear_all_reports(assignment["id"])

        killed = validate_success(api.kill_assignment(assignment["id"],
                                                      EDITOR))
        assert killed["kill_fee_tier"] == "POST_DELIVERY"
        # floor(floor(140000 * 50 / 100) / 2) == 35000
        assert killed["final_fee_cents"] == 35000

    def test_on_time_post_delivery_kill_not_halved(self, api):
        """PRD section 3.4: "When `late_flag` is true and the tier is
        `POST_DELIVERY`, the result is halved again — floor-divided by 2 — as
        the late-delivery kill penalty." (the on-time branch skips the
        halving)
        PRD section 3.4: "The tier percentage is 25 when `kill_fee_tier` is
        `PRE_DELIVERY`, or the desk's `kill_fee_post_delivery_pct_num`
        (default 50) when `POST_DELIVERY`."

        Design: Difficulty/combinatorial_formula/kill_fee_late_halving_mode_a
        """
        contributor, _agr, assignment = setup_assignment_in_state(
            "IN_PROGRESS", legal_name="OnTime Owen", email="owen@x.com",
            pricing_mode="PER_WORD", per_word_rate_cents=100,
            commissioned_word_count=1400, deadline_utc="2026-08-05T00:00:00Z")
        # default clock 2026-08-01 is ahead of nothing; submit well before
        # the 2026-08-05 deadline (clock still at startup default).
        submitted = submit_assignment(assignment["id"], contributor["id"])
        assert submitted["late_flag"] is False
        clear_all_reports(assignment["id"])

        killed = validate_success(api.kill_assignment(assignment["id"],
                                                      EDITOR))
        assert killed["late_flag"] is False
        assert killed["kill_fee_tier"] == "POST_DELIVERY"
        assert killed["final_fee_cents"] == 70000, (
            "floor(140000 * 50 / 100), no halving when on time")


def test_per_word_acceptance_bills_final_word_count(api):
    """PRD section 3.4: "The base is the agreed fee for `FLAT` agreements,
    but for `PER_WORD` agreements it is the editor-verified
    `final_word_count` multiplied by the pinned agreement's
    `per_word_rate_cents` — diverging from the commissioned basis locked in
    `agreed_fee_cents` whenever the final count differs from the commissioned
    count."

    Design: Corner/calculations/per_word_accepted_final_count_basis
    """
    contributor, _agr, assignment, _reports = (
        setup_under_verification_cleared(
            legal_name="Final Fay", email="fay@x.com",
            pricing_mode="PER_WORD", per_word_rate_cents=75,
            commissioned_word_count=1200))
    assert assignment["agreed_fee_cents"] == 90000, "commissioned basis"

    accepted = accept_for_publication(assignment["id"], 1400)
    assert accepted["editorial_status"] == "ACCEPTED_FOR_PUBLICATION"
    assert accepted["final_word_count"] == 1400
    assert accepted["agreed_fee_cents"] == 90000, "locked at offer, unchanged"
    assert accepted["final_fee_cents"] == 105000, "1400 words at 75 c/word"


def test_list_assignments_filters_by_editorial_status(api):
    """PRD section 4: "List assignments (filters: `contributor_id`,
    `rate_agreement_id`, `editorial_status`, `payment_status`)".
    PRD section 3.4: "An `Editor` may kill an assignment from `OFFERED`,
    `ACCEPTED`, or `IN_PROGRESS`: the kill is a pre-delivery kill, so
    `kill_fee_tier` becomes `PRE_DELIVERY` and `final_fee_cents` is the
    kill-variant result."

    Design: Corner/endpoints/list_filter_by_editorial_status
    """
    contributor, _agr = setup_contributor_with_agreement(
        legal_name="Filter Flo", email="flo@x.com", pricing_mode="FLAT",
        flat_fee_cents=50000)
    asg_killed = create_assignment(contributor["id"], title="K1")
    asg_draft = create_assignment(contributor["id"], title="D1")
    walk_assignment(asg_killed["id"], contributor["id"], "OFFERED")
    kill_assignment(asg_killed["id"])

    resp = api.list_assignments(
        EDITOR, params={"editorial_status": "KILLED",
                        "contributor_id": contributor["id"]})
    rows, meta = validate_paginated(resp)
    assert len(rows) == 1, "only the killed assignment matches"
    assert rows[0]["id"] == asg_killed["id"]
    assert rows[0]["editorial_status"] == "KILLED"
    assert rows[0]["kill_fee_tier"] == "PRE_DELIVERY"
    assert rows[0]["final_fee_cents"] == 12500, "floor(50000 * 25 / 100)"
    assert rows[0]["id"] != asg_draft["id"]
