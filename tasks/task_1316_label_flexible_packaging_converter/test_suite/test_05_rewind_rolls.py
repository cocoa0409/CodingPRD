"""Rewind rolls: recording gates, capacity ceiling, splice tolerance, roll
judgment, and the automatic PRINTED -> REWOUND advance."""
from test_helpers import (
    PRESS_OP,
    QM,
    accept_roll,
    api_client,
    current_job_version,
    get_job,
    job_chain,
    record_roll,
    ship_job,
    validate_error,
    validate_paginated,
)


class TestRewindRollRecording:

    def test_rewind_roll_while_on_press_rejected(self):
        """PRD §3.7: "Off the rewinder, finished rolls are recorded by the
        `PressOperator` one at a time, each with its `roll_seq` (the 1-based
        sequence number of the roll within the job), the `label_count` of good
        labels wound on, and its `splice_count`. The parent job must be
        `PRINTED` (`ERR_JOB_NOT_PRINTED`), and the job's roll count may never
        exceed its `rewind_max_rolls` — recording one roll too many is rejected
        with `ERR_ROLL_LIMIT_EXCEEDED`."

        Design: Corner/state_machines/rewind_roll_while_on_press_rejected
        """
        chain = job_chain(stop_at="ON_PRESS", account_name="Early Roll Co",
                          artwork_code="AW-ER", substrate_code="ER-1",
                          recipe_code="INK-ER", die_code="D-ER",
                          press_code="P-ER", quantity_ordered=2000)
        resp = api_client.record_rewind_roll(
            chain["job"]["id"],
            {"roll_seq": 1, "label_count": 500, "splice_count": 0}, PRESS_OP)
        validate_error(resp, "ERR_JOB_NOT_PRINTED", expected_status=409)

    def test_rolls_up_to_rewind_max_rolls_admitted(self):
        """PRD §3.7: "The parent job must be `PRINTED` (`ERR_JOB_NOT_PRINTED`),
        and the job's roll count may never exceed its `rewind_max_rolls` —
        recording one roll too many is rejected with
        `ERR_ROLL_LIMIT_EXCEEDED`. Each roll starts `WOUND` and carries the
        system-recorded `job_id`."

        Design: Difficulty/resource_temporal_overlap/rewind_roll_count_capacity_exceeded
        """
        chain = job_chain(stop_at="PRINTED", account_name="Overlap B At",
                          artwork_code="AW-16A", substrate_code="BOPP-40A",
                          recipe_code="INK-16A", die_code="D-16A",
                          press_code="P-16A", quantity_ordered=3000,
                          good_quantity_produced=3000, rewind_max_rolls=2)
        job_id = chain["job"]["id"]
        r1 = record_roll(job_id, 1, 1500, 0)
        r2 = record_roll(job_id, 2, 1500, 0)
        assert r1["status"] == "WOUND"
        assert r2["status"] == "WOUND", \
            "the roll at exactly rewind_max_rolls must still be admitted"

    def test_roll_beyond_rewind_max_rolls_rejected(self):
        """PRD §3.7: "The parent job must be `PRINTED` (`ERR_JOB_NOT_PRINTED`),
        and the job's roll count may never exceed its `rewind_max_rolls` —
        recording one roll too many is rejected with
        `ERR_ROLL_LIMIT_EXCEEDED`. Each roll starts `WOUND` and carries the
        system-recorded `job_id`."

        Design: Difficulty/resource_temporal_overlap/rewind_roll_count_capacity_exceeded
        """
        chain = job_chain(stop_at="PRINTED", account_name="Overlap B",
                          artwork_code="AW-16", substrate_code="BOPP-40",
                          recipe_code="INK-16", die_code="D-16",
                          press_code="P-16", quantity_ordered=3000,
                          good_quantity_produced=3000, rewind_max_rolls=2)
        job_id = chain["job"]["id"]
        record_roll(job_id, 1, 1500, 0)
        record_roll(job_id, 2, 1500, 0)

        resp = api_client.record_rewind_roll(
            job_id, {"roll_seq": 3, "label_count": 500, "splice_count": 0},
            PRESS_OP)
        validate_error(resp, "ERR_ROLL_LIMIT_EXCEEDED", expected_status=422)

        data, meta = validate_paginated(
            api_client.list_rewind_rolls(job_id, PRESS_OP))
        assert meta["total_count"] == 2, \
            "rejected roll must not join the job's roll list"


class TestRewindRollJudgment:

    def test_splice_limit_accept_rejected(self):
        """PRD §3.7: "Roll judgment belongs to the `QualityManager`, and both
        verdicts require the roll to still be `WOUND`
        (`ERR_ROLL_ALREADY_JUDGED`) and the parent job to be `PRINTED`
        (`ERR_JOB_NOT_PRINTED`). Acceptance additionally enforces the
        customer's splice tolerance: a roll whose `splice_count` exceeds the
        job's `max_splices_per_roll` cannot be accepted
        (`ERR_SPLICE_LIMIT_EXCEEDED`)."

        Design: Corner/validations/splice_limit_accept_rejected
        """
        chain = job_chain(stop_at="PRINTED", account_name="Splice Co",
                          artwork_code="AW-SP", substrate_code="SP-1",
                          recipe_code="INK-SP", die_code="D-SP",
                          press_code="P-SP", quantity_ordered=1000,
                          good_quantity_produced=1000, rewind_max_rolls=2,
                          max_splices_per_roll=1)
        job_id = chain["job"]["id"]
        roll = record_roll(job_id, 1, 1000, 2)

        resp = api_client.accept_rewind_roll(job_id, roll["id"], QM)
        validate_error(resp, "ERR_SPLICE_LIMIT_EXCEEDED", expected_status=422)

        data, _ = validate_paginated(api_client.list_rewind_rolls(job_id, QM))
        row = next(r for r in data if r["id"] == roll["id"])
        assert row["status"] == "WOUND", \
            "splice-limited roll stays WOUND after the rejected acceptance"

    def test_roll_double_judge_rejected(self):
        """PRD §3.7: "Roll judgment belongs to the `QualityManager`, and both
        verdicts require the roll to still be `WOUND`
        (`ERR_ROLL_ALREADY_JUDGED`) and the parent job to be `PRINTED`
        (`ERR_JOB_NOT_PRINTED`)."
        PRD §3.7: "Either way the roll's `version` increments, and after each
        judgment the server re-checks the job: when every recorded roll has
        been judged — `ACCEPTED` or `REJECTED` — and at least one is
        `ACCEPTED`, the job advances automatically from `PRINTED` to
        `REWOUND`."

        Design: Corner/state_machines/roll_double_judge_rejected
        """
        # Two rolls so the job stays PRINTED after the first judgment (the
        # auto-advance requires every recorded roll to be judged): the second
        # accept attempt then isolates the roll-state violation.
        chain = job_chain(stop_at="PRINTED", account_name="Roll Co",
                          artwork_code="AW-R2", substrate_code="R-1",
                          recipe_code="INK-R", die_code="D-R",
                          press_code="P-R", quantity_ordered=1000,
                          good_quantity_produced=1000, rewind_max_rolls=2)
        job_id = chain["job"]["id"]
        r1 = record_roll(job_id, 1, 500, 0)
        record_roll(job_id, 2, 500, 0)
        accepted = accept_roll(job_id, r1["id"])
        assert accepted["status"] == "ACCEPTED"
        assert get_job(job_id)["status"] == "PRINTED", \
            "one WOUND roll outstanding keeps the job PRINTED"

        resp = api_client.accept_rewind_roll(job_id, r1["id"], QM)
        validate_error(resp, "ERR_ROLL_ALREADY_JUDGED", expected_status=409)

        data, _ = validate_paginated(api_client.list_rewind_rolls(job_id, QM))
        row = next(r for r in data if r["id"] == r1["id"])
        assert row["status"] == "ACCEPTED"


class TestRewindBubbleToRewound:

    def test_partial_roll_judgment_keeps_job_printed(self):
        """PRD §3.7: "Either way the roll's `version` increments, and after
        each judgment the server re-checks the job: when every recorded roll
        has been judged — `ACCEPTED` or `REJECTED` — and at least one is
        `ACCEPTED`, the job advances automatically from `PRINTED` to
        `REWOUND`."

        Design: Difficulty/transitive_cascade/roll_accept_bubbles_job_rewound_enables_ship_invoice
        """
        chain = job_chain(stop_at="PRINTED", account_name="Bubble BV",
                          artwork_code="AW-8", substrate_code="BOPP-34",
                          recipe_code="INK-8", die_code="D-8",
                          press_code="P-8", quantity_ordered=1000,
                          good_quantity_produced=1000, rewind_max_rolls=3,
                          max_splices_per_roll=1)
        job_id = chain["job"]["id"]
        r1 = record_roll(job_id, 1, 400, 0)
        record_roll(job_id, 2, 600, 1)

        accept_roll(job_id, r1["id"])
        assert get_job(job_id)["status"] == "PRINTED", (
            "the second roll is still WOUND, so the auto-advance must not "
            "fire yet")

    def test_full_roll_judgment_bubbles_and_enables_ship(self):
        """PRD §3.7: "Either way the roll's `version` increments, and after
        each judgment the server re-checks the job: when every recorded roll
        has been judged — `ACCEPTED` or `REJECTED` — and at least one is
        `ACCEPTED`, the job advances automatically from `PRINTED` to
        `REWOUND`."
        PRD §3.7: "Shipment is the final act, performed by a `QualityManager`.
        The job must be `REWOUND` (`ERR_JOB_NOT_REWOUND`); a job flagged
        `requires_food_contact_letter` cannot ship until its `FOOD_CONTACT`
        letter exists (`ERR_COMPLIANCE_LETTER_MISSING`); and the request must
        carry `expected_job_version` matching the job's current `version`,
        rejected as `ERR_STALE_VERSION` on mismatch per §2.8."

        Design: Difficulty/transitive_cascade/roll_accept_bubbles_job_rewound_enables_ship_invoice
        """
        chain = job_chain(stop_at="PRINTED", account_name="Bubble BV 2",
                          artwork_code="AW-8B", substrate_code="BOPP-34B",
                          recipe_code="INK-8B", die_code="D-8B",
                          press_code="P-8B", quantity_ordered=1000,
                          good_quantity_produced=1000, rewind_max_rolls=3,
                          max_splices_per_roll=1)
        job_id = chain["job"]["id"]
        r1 = record_roll(job_id, 1, 400, 0)
        r2 = record_roll(job_id, 2, 600, 1)

        accept_roll(job_id, r1["id"])
        assert get_job(job_id)["status"] == "PRINTED"
        accept_roll(job_id, r2["id"])
        rewound = get_job(job_id)
        assert rewound["status"] == "REWOUND", \
            "judging the last roll bubbles the job PRINTED -> REWOUND"

        shipped = ship_job(job_id, current_job_version(job_id))
        assert shipped["status"] == "SHIPPED"
        # invoice on good 1000: base 4500 + material ceil(265.9843*40)=10640
        # + ink ceil(0.2252*300)=68 + plates 120000 + die 0
        assert shipped["invoiced_price_cents"] == 135208


class TestShipGate:

    def test_ship_while_printed_rejected(self):
        """PRD §3.7: "Shipment is the final act, performed by a
        `QualityManager`. The job must be `REWOUND` (`ERR_JOB_NOT_REWOUND`); a
        job flagged `requires_food_contact_letter` cannot ship until its
        `FOOD_CONTACT` letter exists (`ERR_COMPLIANCE_LETTER_MISSING`); and the
        request must carry `expected_job_version` matching the job's current
        `version`, rejected as `ERR_STALE_VERSION` on mismatch per §2.8."

        Design: Corner/state_machines/ship_while_printed_rejected
        """
        chain = job_chain(stop_at="PRINTED", account_name="Early Ship Co",
                          artwork_code="AW-ES", substrate_code="ES-1",
                          recipe_code="INK-ES", die_code="D-ES",
                          press_code="P-ES", quantity_ordered=1000,
                          good_quantity_produced=1000)
        job_id = chain["job"]["id"]
        resp = api_client.ship_job(
            job_id, {"expected_job_version": current_job_version(job_id)}, QM)
        validate_error(resp, "ERR_JOB_NOT_REWOUND", expected_status=409)

    def test_ship_from_rewound_succeeds(self):
        """PRD §3.7: "Shipment is the final act, performed by a
        `QualityManager`. The job must be `REWOUND` (`ERR_JOB_NOT_REWOUND`); a
        job flagged `requires_food_contact_letter` cannot ship until its
        `FOOD_CONTACT` letter exists (`ERR_COMPLIANCE_LETTER_MISSING`); and the
        request must carry `expected_job_version` matching the job's current
        `version`, rejected as `ERR_STALE_VERSION` on mismatch per §2.8."
        PRD §3.7: "The final `invoiced_price_cents` is the sum of the base
        charge, the material charge, the ink charge, the artwork's
        `plate_set_cost_cents`, and any `die_charge_applied_cents` billed at
        release; it replaces the provisional quote, and the difference between
        the two figures is the invoice variance. The job moves `REWOUND` →
        `SHIPPED`, a terminal state."

        Design: Difficulty/transitive_cascade/roll_accept_bubbles_job_rewound_enables_ship_invoice
        """
        chain = job_chain(stop_at="SHIPPED", account_name="Bubble BV 3",
                          artwork_code="AW-8C", substrate_code="BOPP-34C",
                          recipe_code="INK-8C", die_code="D-8C",
                          press_code="P-8C", quantity_ordered=1000,
                          good_quantity_produced=1000, rewind_max_rolls=3,
                          max_splices_per_roll=1,
                          rolls=[{"label_count": 400, "splice_count": 0},
                                 {"label_count": 600, "splice_count": 1}])
        job = chain["job"]
        assert job["status"] == "SHIPPED"
        assert job["invoiced_price_cents"] == 135208
