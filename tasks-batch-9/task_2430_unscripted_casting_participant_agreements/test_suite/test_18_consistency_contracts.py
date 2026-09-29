"""Consistency is immediate: one execute call, and every figure it touches is
already settled when the very next read arrives — the agreement's final total and
audit stamp, the production's rollup and posture, the applicant's cast status, and
the whole set of auto-created obligations with their derived dates and fees. No
sweep, no clock movement and no second write sits in between.
"""

from test_helpers import (
    DEFAULT_LOGICAL_CLOCK,
    TEST_USERS,
    assert_money,
    create_agreement_payload,
    get_applicant,
    get_applicant_version,
    get_production,
    record_screening_items,
    setup_applicant,
    setup_docusoap_production,
    setup_published_casting_call,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["production_admin_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
BA1 = TEST_USERS["business_affairs_headers"]
BA2 = TEST_USERS["business_affairs_2_headers"]

THREE_ADULT_INSTRUMENTS = (
    ("INTERVIEW", "PASS", 0, CO1),
    ("BACKGROUND_CHECK", "PASS", 0, CO1),
    ("MEDICAL_EXAM", "PASS", 0, CO1),
)


class TestExecuteIsImmediatelyConsistent:
    """The execute response and the reads that follow it agree with each other on
    every derived figure."""

    def test_one_execute_settles_the_total_the_rollups_and_all_three_obligations(
        self, api
    ):
        """PRD §3.6: "First, the final stipend variant is written to
        `total_stipend_commitment_cents`, the status becomes `EXECUTED`,
        `executed_by_user_id` is stamped with the caller's `X-User-ID`,
        `executed_at` is stamped with the logical clock, and the applicant's
        `screening_status` moves to `CAST`."
        PRD §3.6: "Second, because the final commitment was written, the
        production's `stipend_committed_cents` is recomputed by full re-summation
        over executed agreements and its `minor_participant_count` is recomputed as
        the count of executed agreements whose applicant is a minor."
        PRD §3.9: "For each ordinal from 1 up to `press_appearance_obligation_count`,
        a press obligation is created with `kind` `PRESS_JUNKET`, its
        `sequence_ordinal` set to that ordinal, its `fee_cents` set to the press
        appearance rate of 25,000 cents, and its `due_utc` set to the production's
        `photography_end_utc` advanced by 30 days multiplied by the ordinal — so
        the first junket falls 30 days after wrap, the second 60 days after, the
        third 90 days after, and so on."
        PRD §3.9: "Then, and only when `reunion_obligation` is true, a single
        reunion obligation is created with `kind` `REUNION_TAPING`,
        `sequence_ordinal` 1, `fee_cents` of 150,000 cents, and `due_utc` set to
        `photography_end_utc` advanced by 180 days."
        PRD §3.9: "Every obligation records the `agreement_id` that owes the
        appearance and opens at `status` `SCHEDULED` with `fulfilled_at` absent."

        Design: Corner/consistency_model/execute_response_reflects_every_rollup_in_the_same_request
        """
        production = setup_docusoap_production(title="Harbour Nights S1")
        call = setup_published_casting_call(
            production["id"],
            channel="REFERRAL",
            min_age=18,
            max_age=60,
            exclusivity_window_days=0,
        )
        ada = setup_applicant(
            call["id"],
            legal_name="Ada Reyes",
            date_of_birth="1994-04-02",
            residency_state_code="GA",
        )
        record_screening_items(ada["id"], THREE_ADULT_INSTRUMENTS)

        agreement = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    ada["id"],
                    production["id"],
                    get_applicant_version(ada["id"]),
                    exclusivity_window_days=0,
                    confidentiality_tier="STANDARD",
                    depiction_rights_scope="FULL",
                    stipend_structure="PER_EPISODE",
                    base_stipend_cents=100_000,
                    episodes_committed=2,
                    press_appearance_obligation_count=2,
                    reunion_obligation=True,
                ),
                BA1,
            ),
            201,
        )
        sent = validate_success(api.send_agreement(agreement["id"], BA1))
        # The worst case assumes the full nine-episode season at the 1.30 tier and
        # charges four junkets and a reunion.
        assert_money(
            sent["provisional_stipend_cents"], 1_420_000, "provisional stipend"
        )

        executed = validate_success(api.execute_agreement(agreement["id"], BA2))
        assert executed["status"] == "EXECUTED"
        # The agreed terms are two episodes at the 1.00 tier, two junkets and the
        # reunion actually owed.
        assert_money(
            executed["total_stipend_commitment_cents"], 400_000, "final stipend"
        )
        assert executed["executed_at"].startswith(DEFAULT_LOGICAL_CLOCK[:19])

        # The very next reads already see the recomputed figures.
        rolled_up = get_production(production["id"])
        assert_money(
            rolled_up["stipend_committed_cents"], 400_000, "committed stipend"
        )
        assert rolled_up["casting_posture"] == "OPEN"
        assert rolled_up["minor_participant_count"] == 0
        assert get_applicant(ada["id"])["screening_status"] == "CAST"

        rows, meta = validate_paginated(
            api.list_post_obligations(
                agreement["id"], BA2, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 3
        by_key = {(row["kind"], row["sequence_ordinal"]): row for row in rows}
        assert set(by_key) == {
            ("PRESS_JUNKET", 1),
            ("PRESS_JUNKET", 2),
            ("REUNION_TAPING", 1),
        }
        for row in rows:
            assert row["agreement_id"] == agreement["id"]
            assert row["status"] == "SCHEDULED"
            assert row.get("fulfilled_at") is None

        # Thirty, sixty and one hundred and eighty days past the 2026-12-15 wrap.
        first_junket = by_key[("PRESS_JUNKET", 1)]
        assert first_junket["due_utc"].startswith("2027-01-14")
        assert_money(first_junket["fee_cents"], 25_000, "first junket fee")

        second_junket = by_key[("PRESS_JUNKET", 2)]
        assert second_junket["due_utc"].startswith("2027-02-13")
        assert_money(second_junket["fee_cents"], 25_000, "second junket fee")

        reunion = by_key[("REUNION_TAPING", 1)]
        assert reunion["due_utc"].startswith("2027-06-13")
        assert_money(reunion["fee_cents"], 150_000, "reunion fee")
