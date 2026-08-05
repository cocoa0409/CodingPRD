"""The two intake completeness variants and the independent patient axes."""

from test_helpers import (
    ApiErrorId,
    add_protocol_item,
    book_encounter,
    complete_encounter,
    create_product,
    draft_protocol,
    make_director_headers,
    make_nd_headers,
    read_patient,
    register_director,
    register_nd,
    register_patient,
    setup_booking_ready_patient,
    setup_patient_at_booking_score,
    submit_and_attest,
    submit_section,
    validate_error,
    validate_success,
)


def _mixed_chart(api):
    """Three attested sections (75) plus two merely submitted ones (7 + 5)."""
    nd = register_nd(api, licensed_state_codes=["OR", "WA"])
    patient = register_patient(api, nd["id"], telehealth_consent=True)
    for section_type in (
        "CHIEF_COMPLAINT_TIMELINE",
        "SYSTEMS_REVIEW",
        "MEDICATIONS_SUPPLEMENTS",
    ):
        submit_and_attest(api, patient["id"], section_type)
    for section_type in ("DIET_LIFESTYLE", "FAMILY_HISTORY"):
        submit_section(api, patient["id"], section_type)
    return nd, read_patient(api, patient["id"])


def test_partially_signed_chart_scores_eighty_seven_and_books_a_visit(api):
    """PRD §3.1: "In the **booking variant**, an `ATTESTED` section contributes
    its full weight, a merely `SUBMITTED` section contributes half its weight
    with the fraction discarded — 25 becomes 12, 15 becomes 7, 10 becomes 5 —
    and an `EXPIRED` or entirely absent section contributes nothing."
    PRD §3.1: "In the **protocol variant** there is no partial credit
    whatsoever: only `ATTESTED` sections contribute, at full weight, and
    everything else including `SUBMITTED` contributes nothing."

    Design: Difficulty/dual_variant_calc/intake_gate_booking_variant_passes_while_protocol_variant_fails
    """
    nd, patient = _mixed_chart(api)

    assert patient["intake_booking_score"] == 87
    assert patient["intake_protocol_score"] == 75

    response = api.create_encounter(
        {
            "patient_id": patient["id"],
            "practitioner_id": nd["id"],
            "modality": "IN_PERSON",
            "scheduled_start": "2026-06-01T15:00:00Z",
            "scheduled_end": "2026-06-01T16:00:00Z",
        },
        make_nd_headers(nd["id"]),
    )
    encounter = validate_success(response, 201)
    assert encounter["scheduling_status"] == "SCHEDULED"


def test_same_chart_is_refused_a_protocol_issue_on_the_attested_only_variant(api):
    """PRD §3.1: "Booking an encounter requires `intake_booking_score` to be at
    least 60, and issuing a protocol requires `intake_protocol_score` to be at
    least 85; both boundaries are inclusive, so a chart sitting exactly on the
    number passes. A chart that falls short is refused with
    `ERR_INTAKE_INCOMPLETE`."
    PRD §3.6: "A protocol moves `DRAFT → ISSUED` only when the patient's gate is
    `OPEN`, the patient's `intake_protocol_score` is at least 85 — failing which
    the request is refused with `ERR_INTAKE_INCOMPLETE` — and the protocol has
    at least one line."

    Design: Difficulty/dual_variant_calc/intake_gate_booking_variant_passes_while_protocol_variant_fails
    """
    nd, patient = _mixed_chart(api)
    assert patient["intake_protocol_score"] == 75

    product = create_product(api)
    protocol = draft_protocol(api, nd["id"], patient["id"])
    add_protocol_item(api, nd["id"], protocol["id"], product["id"])

    response = api.issue_protocol(protocol["id"], make_nd_headers(nd["id"]))
    validate_error(response, ApiErrorId.ERR_INTAKE_INCOMPLETE.value, 422)

    unchanged = validate_success(
        api.get_protocol(protocol["id"], make_nd_headers(nd["id"]))
    )
    assert unchanged["status"] == "DRAFT"


def test_booking_gate_admits_a_chart_sitting_exactly_on_sixty(api):
    """PRD §3.1: "Booking an encounter requires `intake_booking_score` to be at
    least 60, and issuing a protocol requires `intake_protocol_score` to be at
    least 85; both boundaries are inclusive, so a chart sitting exactly on the
    number passes."
    PRD §3.3: "First the patient's `intake_booking_score` must be at least 60,
    or the booking is refused with `ERR_INTAKE_INCOMPLETE`."

    Design: Difficulty/boundary_precision_check/booking_gate_admits_exactly_sixty_and_refuses_fifty_five
    """
    nd = register_nd(api)
    patient = setup_patient_at_booking_score(
        api,
        nd,
        attested=("CHIEF_COMPLAINT_TIMELINE", "SYSTEMS_REVIEW", "FAMILY_HISTORY"),
    )
    assert patient["intake_booking_score"] == 60

    response = api.create_encounter(
        {
            "patient_id": patient["id"],
            "practitioner_id": nd["id"],
            "modality": "IN_PERSON",
            "scheduled_start": "2026-06-01T09:00:00Z",
            "scheduled_end": "2026-06-01T10:00:00Z",
        },
        make_nd_headers(nd["id"]),
    )
    encounter = validate_success(response, 201)
    assert encounter["scheduling_status"] == "SCHEDULED"


def test_booking_gate_refuses_a_chart_one_partial_section_short_at_fifty_five(api):
    """PRD §3.1: "A chart that falls short is refused with
    `ERR_INTAKE_INCOMPLETE`."
    PRD §3.1: "In the **booking variant**, an `ATTESTED` section contributes its
    full weight, a merely `SUBMITTED` section contributes half its weight with
    the fraction discarded — 25 becomes 12, 15 becomes 7, 10 becomes 5 — and an
    `EXPIRED` or entirely absent section contributes nothing."

    Design: Difficulty/boundary_precision_check/booking_gate_admits_exactly_sixty_and_refuses_fifty_five
    """
    nd = register_nd(api)
    patient = setup_patient_at_booking_score(
        api,
        nd,
        attested=("CHIEF_COMPLAINT_TIMELINE", "SYSTEMS_REVIEW"),
        submitted_only=("FAMILY_HISTORY",),
    )
    assert patient["intake_booking_score"] == 55

    response = api.create_encounter(
        {
            "patient_id": patient["id"],
            "practitioner_id": nd["id"],
            "modality": "IN_PERSON",
            "scheduled_start": "2026-06-01T11:00:00Z",
            "scheduled_end": "2026-06-01T12:00:00Z",
        },
        make_nd_headers(nd["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INTAKE_INCOMPLETE.value, 422)


def test_first_completed_visit_advances_only_the_care_relationship_axis(api):
    """PRD §3.1: "A patient's `clinical_status` starts at `INTAKE` and moves
    `INTAKE → ESTABLISHED` automatically the first time one of that patient's
    encounters is completed, incrementing the patient's `version` by 1."
    PRD §3.1: "**Scope-of-practice review is an entirely independent axis**, and
    a patient can be `ESTABLISHED` and `UNDER_REVIEW` at the same time."

    Design: Difficulty/non_linear_state_machine/patient_care_axis_and_scope_review_axis_hold_different_values
    """
    ready = setup_booking_ready_patient(api)
    nd, patient = ready["nd"], ready["patient"]

    encounter = book_encounter(api, nd["id"], patient["id"])
    settled = complete_encounter(
        api, nd["id"], encounter["id"], duration_minutes=40, service_code="99214"
    )
    assert settled["scheduling_status"] == "COMPLETED"

    refreshed = read_patient(api, patient["id"])
    assert refreshed["clinical_status"] == "ESTABLISHED"
    assert refreshed["scope_review_status"] == "NONE"
    assert refreshed["clinical_write_gate"] == "OPEN"


def test_opening_a_scope_review_leaves_the_care_relationship_axis_established(api):
    """PRD §3.1: "Only a `ClinicalDirector` may open one, supplying a `reason`.
    The review can be opened from `NONE`, from `CLEARED`, or from `RESTRICTED` —
    all three lead to `UNDER_REVIEW` — so a cleared patient can be re-reviewed
    later without any special-casing."
    PRD §2.5: "The gate leaves `OPEN` for `FROZEN_SCOPE_REVIEW` when a
    `ClinicalDirector` opens a scope-of-practice review, and for
    `FROZEN_RED_FLAG` when a critical analyte result raises an automatic
    red-flag referral that nobody has acknowledged yet."

    Design: Difficulty/non_linear_state_machine/patient_care_axis_and_scope_review_axis_hold_different_values
    """
    ready = setup_booking_ready_patient(api)
    nd, patient = ready["nd"], ready["patient"]
    director = register_director(api)

    encounter = book_encounter(api, nd["id"], patient["id"])
    complete_encounter(
        api, nd["id"], encounter["id"], duration_minutes=40, service_code="99214"
    )

    reviewed = validate_success(
        api.open_scope_review(
            patient["id"],
            {"reason": "scope question on injectable recommendation"},
            make_director_headers(director["id"]),
        )
    )

    assert reviewed["clinical_status"] == "ESTABLISHED"
    assert reviewed["scope_review_status"] == "UNDER_REVIEW"
    assert reviewed["clinical_write_gate"] == "FROZEN_SCOPE_REVIEW"

    encounter_now = validate_success(
        api.get_encounter(encounter["id"], make_nd_headers(nd["id"]))
    )
    assert encounter_now["scheduling_status"] == "COMPLETED"
