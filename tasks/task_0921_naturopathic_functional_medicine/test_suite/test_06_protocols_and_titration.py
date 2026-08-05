"""Protocol authoring, revision chains, titration anchors and adverse reactions."""

from test_helpers import (
    UNKNOWN_UUID_ALT,
    ApiErrorId,
    add_protocol_item,
    assert_protocol,
    assert_protocol_item,
    assert_same_instant,
    create_product,
    draft_protocol,
    make_nd_headers,
    make_patient_headers,
    read_patient,
    report_adverse_reaction,
    setup_dispensed_line,
    setup_protocol_ready_patient,
    setup_titrating_line,
    set_clock,
    take_titration_decision,
    validate_error,
    validate_paginated,
    validate_success,
    setup_active_protocol,
)


def test_activating_a_revision_supersedes_its_predecessor_and_stops_its_lines(api):
    """PRD §3.6: "When the newly activated protocol names a
    `supersedes_protocol_id` and that predecessor is currently `ACTIVE`,
    activation runs a three-link cascade: the predecessor moves
    `ACTIVE → SUPERSEDED`; because it was superseded, every line beneath it in
    status `ACTIVE` or `HELD` moves to `DISCONTINUED` with `discontinue_reason`
    recorded as `SUPERSEDED_BY_REVISION`; and because those lines stopped, their
    `next_review_due_at` is cleared to null and their `titration_locked` is set
    false."
    PRD §3.6: "Its `version_no` is 1 for an original protocol, or one more than
    the named predecessor's `version_no` when `supersedes_protocol_id` is
    supplied, so a revision chain numbers itself."

    Design: Corner/state_machines/protocol_activation_supersedes_predecessor_and_stops_its_lines
    """
    ctx = setup_active_protocol(api, with_tech=False, with_lot=False)
    nd, patient, product = ctx["nd"], ctx["patient"], ctx["product"]
    first, first_item = ctx["protocol"], ctx["item"]

    second = draft_protocol(
        api,
        nd["id"],
        patient["id"],
        title="Repletion v2",
        symptom_score_baseline=26,
        supersedes_protocol_id=first["id"],
    )
    second_item = add_protocol_item(
        api, nd["id"], second["id"], product["id"], dose_amount_mg=300
    )
    validate_success(api.issue_protocol(second["id"], make_nd_headers(nd["id"])))
    activated = validate_success(
        api.activate_protocol(second["id"], make_nd_headers(nd["id"]))
    )

    assert_protocol(activated)
    assert activated["status"] == "ACTIVE"
    assert activated["version_no"] == 2

    predecessor = validate_success(
        api.get_protocol(first["id"], make_nd_headers(nd["id"]))
    )
    assert predecessor["status"] == "SUPERSEDED"

    stopped = validate_success(
        api.get_protocol_item(first_item["id"], make_nd_headers(nd["id"]))
    )
    assert stopped["status"] == "DISCONTINUED"
    assert stopped["discontinue_reason"] == "SUPERSEDED_BY_REVISION"
    assert stopped["next_review_due_at"] is None
    assert stopped["titration_locked"] is False

    survivor = validate_success(
        api.get_protocol_item(second_item["id"], make_nd_headers(nd["id"]))
    )
    assert survivor["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_protocols(
            make_nd_headers(nd["id"]), params={"supersedes_protocol_id": first["id"]}
        )
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == second["id"]


def test_severe_interaction_blocks_the_issue_while_moderate_only_flags_it(api):
    """PRD §3.6: "The contraindication check then runs against the patient's
    reported `medication_classes`: no line's product may carry
    `interaction_severity` of `SEVERE` with a medication class that the patient
    actually reports, and a hit is refused with `ERR_CONTRAINDICATION_SEVERE`."
    PRD §3.6: "A `MODERATE` hit does not block; instead, one entry per offending
    line is recorded in the protocol's `interaction_flags` at issue time so that
    the interaction is documented rather than hidden."

    Design: Corner/validations/severe_interaction_blocks_issue_while_moderate_only_flags_it
    """
    ready = setup_protocol_ready_patient(api, medication_classes=["SSRI"])
    nd, patient = ready["nd"], ready["patient"]

    severe_product = create_product(
        api,
        sku="SJW-300",
        name="St Johns Wort",
        supplement_class="BOTANICAL",
        retail_price_cents=3200,
        practitioner_cost_cents=1900,
        interacts_with_med_classes=["SSRI"],
        interaction_severity="SEVERE",
    )
    moderate_product = create_product(
        api,
        interacts_with_med_classes=["SSRI"],
        interaction_severity="MODERATE",
    )

    severe_protocol = draft_protocol(
        api, nd["id"], patient["id"], title="Mood support", symptom_score_baseline=30
    )
    add_protocol_item(
        api, nd["id"], severe_protocol["id"], severe_product["id"], dose_amount_mg=300,
        frequency_per_day=2,
    )
    moderate_protocol = draft_protocol(
        api, nd["id"], patient["id"], title="Mineral support", symptom_score_baseline=30
    )
    add_protocol_item(api, nd["id"], moderate_protocol["id"], moderate_product["id"])

    refused = api.issue_protocol(severe_protocol["id"], make_nd_headers(nd["id"]))
    validate_error(refused, ApiErrorId.ERR_CONTRAINDICATION_SEVERE.value, 422)
    still_draft = validate_success(
        api.get_protocol(severe_protocol["id"], make_nd_headers(nd["id"]))
    )
    assert still_draft["status"] == "DRAFT"

    issued = validate_success(
        api.issue_protocol(moderate_protocol["id"], make_nd_headers(nd["id"]))
    )
    assert issued["status"] == "ISSUED"
    assert len(issued["interaction_flags"]) == 1


def test_advance_reanchors_on_the_decision_while_a_late_hold_keeps_the_anchor(api):
    """PRD §3.7: "For `ADVANCE` and `REDUCE` the schedule is re-anchored on the
    decision itself: `next_review_due_at` becomes `last_decision_at` plus
    `titration_interval_days` days."
    PRD §3.7: "For `HOLD` the original anchor is preserved: `next_review_due_at`
    becomes the **previous** `next_review_due_at` plus `titration_interval_days`
    days, so drift caused by a late review is never absorbed and the line stays
    on its original rhythm."
    PRD §3.7: "`HOLD` and `DISCONTINUE` leave the dose exactly as it stands."

    Design: Corner/calculations/titration_advance_reanchors_while_a_late_hold_preserves_the_original_anchor
    """
    ctx = setup_titrating_line(api, baseline=28, dose_amount_mg=500, titration_interval_days=14)
    nd, item = ctx["nd"], ctx["item"]

    set_clock(api, "2026-05-20T10:00:00Z")
    advanced = take_titration_decision(api, nd["id"], item["id"], 19)
    assert advanced["last_decision"] == "ADVANCE"
    assert advanced["dose_amount_mg"] == 625
    assert_same_instant(
        advanced["next_review_due_at"], "2026-06-03T10:00:00Z", "next_review_due_at"
    )

    set_clock(api, "2026-06-05T09:00:00Z")
    held = take_titration_decision(api, nd["id"], item["id"], 24)

    assert_protocol_item(held)
    assert held["last_decision"] == "HOLD"
    assert held["status"] == "HELD"
    assert held["dose_amount_mg"] == 625
    assert held["titration_step_no"] == 2
    assert_same_instant(
        held["next_review_due_at"], "2026-06-17T10:00:00Z", "next_review_due_at"
    )


def test_a_protocol_line_naming_an_unknown_product_is_a_body_reference_failure(api):
    """PRD §2.6: "Every foreign key that is *present* in the request body
    resolves to a live row, checked in the order the fields are declared in that
    endpoint's input list."
    PRD §2.6: "A body `patient_id` that does not resolve yields
    `ERR_PATIENT_NOT_FOUND`, a `practitioner_id` yields
    `ERR_PRACTITIONER_NOT_FOUND`, an `encounter_id` yields
    `ERR_ENCOUNTER_NOT_FOUND`, and a `supersedes_protocol_id` yields
    `ERR_PROTOCOL_NOT_FOUND`; `product_id`, `product_lot_id` and
    `protocol_item_id` have no entity-specific code and yield
    `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/errors/unknown_product_id_on_a_protocol_item_returns_reference_not_found
    """
    ready = setup_protocol_ready_patient(api)
    nd, patient = ready["nd"], ready["patient"]
    protocol = draft_protocol(api, nd["id"], patient["id"], title="Repletion")

    response = api.create_protocol_item(
        protocol["id"],
        {
            "product_id": UNKNOWN_UUID_ALT,
            "dose_amount_mg": 400,
            "frequency_per_day": 1,
            "duration_days": 60,
            "titration_interval_days": 14,
        },
        make_nd_headers(nd["id"]),
    )
    validate_error(response, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, 404)

    rows, meta = validate_paginated(
        api.list_protocol_items(
            make_nd_headers(nd["id"]), params={"protocol_id": protocol["id"]}
        )
    )
    assert meta["total_count"] == 0 and rows == []


def _severe_reaction_context(api):
    return setup_dispensed_line(
        api,
        quantity=2,
        product_overrides={
            "sku": "ASH-KSM-600",
            "name": "Ashwagandha KSM-66",
            "supplement_class": "ADAPTOGEN",
            "retail_price_cents": 4995,
            "practitioner_cost_cents": 3000,
        },
        item_overrides={"dose_amount_mg": 600, "frequency_per_day": 2, "duration_days": 90},
        protocol_overrides={"title": "Adrenal support", "symptom_score_baseline": 30},
    )


def test_a_severe_adverse_reaction_stops_the_line_and_its_owning_protocol(api):
    """PRD §3.7: "A `SEVERE` report stops the line immediately: it moves to
    `DISCONTINUED` with `discontinue_reason` recorded as `ADVERSE_REACTION`, and
    it runs exactly the same cascade a `DISCONTINUE` decision runs — the owning
    protocol moves `ACTIVE → DISCONTINUED` when every line is now stopped,
    dispenses within the same fourteen-day window are reversed, lots are
    restocked and the patient's refunded total grows."
    PRD §3.7: "The line moves to `DISCONTINUED`, its `next_review_due_at` is
    cleared to null and its `discontinue_reason` is recorded."

    Design: Difficulty/transitive_cascade/severe_adverse_reaction_stops_line_protocol_dispense_and_lot
    """
    ctx = _severe_reaction_context(api)
    nd, patient, item, protocol = ctx["nd"], ctx["patient"], ctx["item"], ctx["protocol"]

    stopped = report_adverse_reaction(
        api,
        make_patient_headers(patient["id"]),
        item["id"],
        "SEVERE",
        description="palpitations and rash within 48 hours",
    )

    assert_protocol_item(stopped)
    assert stopped["status"] == "DISCONTINUED"
    assert stopped["discontinue_reason"] == "ADVERSE_REACTION"
    assert stopped["next_review_due_at"] is None

    owning = validate_success(api.get_protocol(protocol["id"], make_nd_headers(nd["id"])))
    assert owning["status"] == "DISCONTINUED"


def test_the_severe_reaction_cascade_reverses_the_dispense_and_restocks_the_lot(api):
    """PRD §3.7: "And because those dispenses reversed, each returns its
    `quantity` to its source lot's `quantity_on_hand` and adds its
    `total_price_cents` to the patient's `cash_refunded_total_cents`."
    PRD §2.8: "Reversals never decrease the charged counter; they increase the
    refunded counter instead, so both counters are monotonic and the patient's
    net cash position at any instant is the difference between them."

    Design: Difficulty/transitive_cascade/severe_adverse_reaction_stops_line_protocol_dispense_and_lot
    """
    ctx = _severe_reaction_context(api)
    nd, patient, item = ctx["nd"], ctx["patient"], ctx["item"]
    dispense, lot = ctx["dispense"], ctx["lot"]
    assert dispense["total_price_cents"] == 9990

    report_adverse_reaction(
        api,
        make_patient_headers(patient["id"]),
        item["id"],
        "SEVERE",
        description="palpitations and rash within 48 hours",
    )

    reversed_dispense = validate_success(
        api.get_dispense(dispense["id"], make_nd_headers(nd["id"]))
    )
    assert reversed_dispense["status"] == "REVERSED"
    assert reversed_dispense["total_price_cents"] == 9990

    restocked = validate_success(api.get_product_lot(lot["id"], make_nd_headers(nd["id"])))
    assert restocked["quantity_on_hand"] == 20

    refreshed = read_patient(api, patient["id"])
    assert refreshed["cash_charged_total_cents"] == 9990
    assert refreshed["cash_refunded_total_cents"] == 9990
