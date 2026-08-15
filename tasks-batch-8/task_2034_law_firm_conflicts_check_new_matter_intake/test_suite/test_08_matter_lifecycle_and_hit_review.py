"""Matter lifecycle guards, terminal lockdown, hit-review finality, countersign
side effects, and lateral zero-hit activation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_attorney,
    create_conflicts_partner,
    create_matter,
    create_party,
    get_success_data,
    list_hits_for_check,
    make_client_headers,
    make_conflicts_partner_headers,
    make_responsible_attorney_headers,
    run_conflict_check,
    setup_countersign_ready,
    setup_open_matter,
    setup_basic_matter,
    transition_letter_payload,
    validate_error,
    validate_paginated,
    validate_success,
    add_roster_party,
)

INTAKE = TEST_USERS["intake_specialist_headers"]
FIRM_ADMIN = TEST_USERS["firm_admin_headers"]


class TestMatterInitialStates:
    def test_new_matter_starts_intake_unchecked_with_null_number(self):
        """PRD §3.3: "A new matter starts with `lifecycle_status` `INTAKE` and
        `clearance_status` `UNCHECKED`; `matter_number` stays null until
        countersignature, `opened_at` stays null until the same event,
        `closed_at` stays null unless the matter is later closed, and
        `decline_reason` starts empty."

        Design: Corner/state_machines/c_matter_initial_states
        """
        party = create_party("Init Client Inc")
        atty = create_attorney()
        matter = create_matter(party["id"], atty["id"], matter_title="M")
        assert matter["lifecycle_status"] == "INTAKE"
        assert matter["clearance_status"] == "UNCHECKED"
        assert matter["matter_number"] is None
        assert matter["opened_at"] is None
        assert matter["version"] == 1


class TestDeclineOrCloseWrongStateRejected:
    def test_decline_from_open_fails_not_intake(self):
        """PRD §3.3: "Declining and closing drive the lifecycle dimension. A
        `ConflictsPartner` declines a matter by posting an `action` of
        `DECLINE` with an optional `reason`, which is stored as
        `decline_reason`; declining from any state other than `INTAKE` fails
        with `ERR_MATTER_NOT_INTAKE`."

        Design: Corner/state_machines/c_decline_or_close_wrong_state_rejected
        """
        party, atty, matter, letter, deposit = setup_open_matter(
            "State Client Inc"
        )
        partner = create_conflicts_partner()
        resp = api_client.transition_matter(
            matter["id"],
            {"action": "DECLINE", "reason": "too late"},
            make_conflicts_partner_headers(partner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MATTER_NOT_INTAKE)

    def test_close_from_intake_fails_not_open(self):
        """PRD §3.3: "Closing takes an `action` of `CLOSE`, requires the matter
        to be `OPEN` (else `ERR_MATTER_NOT_OPEN`), and may be performed by a
        `ConflictsPartner` or by the matter's responsible attorney".

        Design: Corner/state_machines/c_decline_or_close_wrong_state_rejected
        """
        party, atty, matter_b = setup_basic_matter(
            "State Client Two Inc", practice_group="TAX", matter_title="MB"
        )
        partner = create_conflicts_partner()
        resp = api_client.transition_matter(
            matter_b["id"],
            {"action": "CLOSE"},
            make_conflicts_partner_headers(partner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MATTER_NOT_OPEN)


class TestTerminalLockdownCheckOnClosedMatter:
    def test_conflict_check_on_closed_matter_rejected(self):
        """PRD §3.4: "Running a conflict check is available to an
        `IntakeSpecialist` or a `ResponsibleAttorney` while the matter is
        `INTAKE` or `OPEN`; on a terminal matter the attempt fails with
        `ERR_MATTER_TERMINAL`."

        Design: Corner/state_machines/c_terminal_lockdown_check_on_closed_matter
        """
        party, atty, matter, letter, deposit = setup_open_matter(
            "Lock Client Inc"
        )
        partner = create_conflicts_partner()
        closed = validate_success(
            api_client.transition_matter(
                matter["id"],
                {"action": "CLOSE"},
                make_conflicts_partner_headers(partner["id"]),
            ),
            200,
        )
        assert closed["lifecycle_status"] == "CLOSED"

        resp = api_client.create_conflict_check(
            matter["id"], {"search_variant": "PHONETIC"}, INTAKE
        )
        validate_error(resp, ApiErrorId.ERR_MATTER_TERMINAL)


class TestHitReviewNotPendingRejected:
    def test_second_review_of_dismissed_hit_fails(self):
        """PRD §3.4: "The hit must still be `PENDING` — reviewing a hit already
        `CONFIRMED`, `DISMISSED`, `WAIVED`, or `STALE` fails with
        `ERR_HIT_NOT_PENDING`".

        Design: Corner/state_machines/c_hit_review_not_pending_rejected
        """
        p_x = create_party("Review Target Inc")
        p_y = create_party("Review Client Corp")
        atty = create_attorney()
        create_matter(p_x["id"], atty["id"], matter_title="M0")
        m1 = create_matter(p_y["id"], atty["id"], matter_title="M1")
        add_roster_party(m1["id"], p_x["id"], "ADVERSE")
        chk = run_conflict_check(m1["id"], "STRICT")
        hit = list_hits_for_check(chk["id"])[0]
        ra = make_responsible_attorney_headers(atty["id"])

        first = validate_success(
            api_client.review_conflict_hit(
                hit["id"], {"decision": "DISMISSED"}, ra
            ),
            200,
        )
        assert first["review_status"] == "DISMISSED"

        resp = api_client.review_conflict_hit(
            hit["id"], {"decision": "CONFIRMED"}, ra
        )
        validate_error(resp, ApiErrorId.ERR_HIT_NOT_PENDING)


class TestCountersignAssignsMatterNumberAndOpens:
    def test_first_countersign_assigns_m000001_and_stamps_default_clock(self):
        """PRD §3.7: "On a successful countersign, the letter becomes
        `COUNTERSIGNED` with `countersigned_at` stamped, and the matter flips
        `INTAKE` → `OPEN` in the same transaction: its `matter_number` is
        assigned exactly once — the letter "M" followed by a zero-padded
        six-digit counter handed out in countersign completion order across the
        whole system — and `opened_at` records the logical time."
        PRD §2.5: "Before any clock-setting call has been made, the clock reads
        exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock
        time."

        Design: Corner/state_machines/c_countersign_assigns_matter_number_and_opens
        """
        party, atty, matter, letter, deposit = setup_countersign_ready(
            "Numbered Client Inc"
        )
        signed = validate_success(
            api_client.transition_engagement_letter(
                letter["id"],
                transition_letter_payload("COUNTERSIGN"),
                make_client_headers(party["id"]),
            ),
            200,
        )
        assert signed["status"] == "COUNTERSIGNED"
        assert signed["countersigned_at"] == "2026-08-01T00:00:00.000Z", (
            "default logical clock, no clock-set call made"
        )

        fresh = get_success_data(api_client.get_matter(matter["id"], INTAKE), 200)
        assert fresh["lifecycle_status"] == "OPEN"
        assert fresh["matter_number"] == "M000001", (
            "first countersign in an empty database assigns M000001"
        )
        assert fresh["opened_at"] == "2026-08-01T00:00:00.000Z"

    def test_countersign_immediately_visible_on_reread(self):
        """PRD §2.4: "Consistency is immediate: every mutation and all of its
        cascaded effects are visible in the same request's response and in any
        re-read that follows it."
        PRD §3.7: "On a successful countersign, the letter becomes
        `COUNTERSIGNED` with `countersigned_at` stamped, and the matter flips
        `INTAKE` → `OPEN` in the same transaction".

        Design: Corner/state_machines/c_countersign_assigns_matter_number_and_opens
        """
        party, atty, matter, letter, deposit = setup_countersign_ready(
            "Numbered Client Inc"
        )
        signed = validate_success(
            api_client.transition_engagement_letter(
                letter["id"],
                transition_letter_payload("COUNTERSIGN"),
                make_client_headers(party["id"]),
            ),
            200,
        )
        reread = get_success_data(api_client.get_matter(matter["id"], INTAKE), 200)
        assert reread["lifecycle_status"] == "OPEN", (
            "the GET immediately after countersign reflects the transition "
            "(no eventual-consistency lag)"
        )
        assert reread["matter_number"] == "M000001"
        assert signed["status"] == "COUNTERSIGNED"


class TestLateralZeroHitsActivatesImmediately:
    def test_lateral_with_no_sweep_hits_starts_active(self):
        """PRD §3.2: "The new attorney starts `LATERAL_PENDING` if the sweep
        created at least one hit, and `ACTIVE` otherwise; `INTERNAL` hires
        always start `ACTIVE`."

        Design: Corner/state_machines/c_lateral_zero_hits_activates_immediately
        """
        party = create_party("Unique Existing Corp")
        atty = create_attorney()
        m0 = create_matter(party["id"], atty["id"], matter_title="M0")

        lateral = create_attorney(
            full_name="Lena Lateral",
            bar_number="BAR010",
            hire_type="LATERAL",
            lateral_employed_from="2024-01-01",
            lateral_employed_to="2025-06-30",
            prior_client_names=["No Such Name Holdings"],
        )
        assert lateral["status"] == "ACTIVE", (
            "zero sweep hits -> immediate activation"
        )
        hits, meta = validate_paginated(
            api_client.list_conflict_hits(
                INTAKE, params={"matched_matter_id": m0["id"]}
            )
        )
        assert meta["total_count"] == 0, "no sweep hits exist for M0"
