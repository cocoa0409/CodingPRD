"""Installation: crew booking order (safety -> fabrication -> certification -> overlap),
the half-open crew double-booking rule, and certification enforcement."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, create_install_appointment_payload,
)
from test_helpers import fixtures as fx


STOREFRONT_ANNEALED_SAFETY = {
    "product_type": "STOREFRONT", "glass_type": "ANNEALED", "thickness_mm": 10,
    "width_in": 30, "height_in": 72, "quantity": 1, "requires_safety_glazing": True,
}
STOREFRONT_TEMPERED = {
    "product_type": "STOREFRONT", "glass_type": "TEMPERED", "thickness_mm": 10,
    "width_in": 30, "height_in": 72, "quantity": 1,
}


# ==========================================================================
# priority_pair_validation_conflict / install_safety_beats_crew_temporal
# ==========================================================================
def test_install_safety_glazing_beats_crew_overlap(api):
    """PRD §3.6: "Safety glazing is enforced first: any line item with
    `requires_safety_glazing` set to true must have a `glass_type` of `TEMPERED` or
    `LAMINATED` before install can be scheduled, else `ERR_SAFETY_GLAZING_REQUIRED` (HTTP
    422)."
    PRD §3.6: "Finally, the appointment window must not overlap another `SCHEDULED`
    appointment on the same crew, evaluated as half-open intervals, else
    `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/install_safety_beats_crew_temporal
    """
    job1 = fx.setup_fabricated_job(api, tier="SILVER", lines=[dict(STOREFRONT_ANNEALED_SAFETY)])
    job2 = fx.setup_fabricated_job(api, tier="SILVER", lines=[dict(STOREFRONT_TEMPERED)])
    crew = fx.create_crew(api, certified_products=["STOREFRONT"])
    fx.create_appointment(api, job2["job_id"], crew["id"],
                          start="2026-06-15T09:00:00Z", end="2026-06-15T12:00:00Z")
    # job1's window (11:00-13:00) overlaps job2's appointment, but its ANNEALED safety line
    # fails the safety check first.
    resp = api.create_install_appointment(
        create_install_appointment_payload(job1["job_id"], crew["id"],
                                            "2026-06-15T11:00:00Z", "2026-06-15T13:00:00Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(resp, ApiErrorId.ERR_SAFETY_GLAZING_REQUIRED)


def test_install_safety_glazing_fails_in_isolation(api):
    """PRD §3.6: "Safety glazing is enforced first: any line item with
    `requires_safety_glazing` set to true must have a `glass_type` of `TEMPERED` or
    `LAMINATED` before install can be scheduled, else `ERR_SAFETY_GLAZING_REQUIRED` (HTTP
    422)."

    Design: Difficulty/priority_pair_validation_conflict/install_safety_beats_crew_temporal
    """
    job = fx.setup_fabricated_job(api, tier="SILVER", lines=[dict(STOREFRONT_ANNEALED_SAFETY)])
    crew = fx.create_crew(api, certified_products=["STOREFRONT"])
    resp = api.create_install_appointment(
        create_install_appointment_payload(job["job_id"], crew["id"],
                                            "2026-06-15T09:00:00Z", "2026-06-15T12:00:00Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(resp, ApiErrorId.ERR_SAFETY_GLAZING_REQUIRED)


# ==========================================================================
# cross_entity_state_dependency / install_requires_fabrication_complete
# ==========================================================================
def test_install_before_fabrication_complete_pending_rejected(api):
    """PRD §3.6: "Next, the job's `fabrication_status` must be `COMPLETE`, else
    `ERR_FABRICATION_INCOMPLETE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/install_requires_fabrication_complete
    """
    ctx = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    crew = fx.create_crew(api, certified_products=["SHOWER_ENCLOSURE"])
    resp = api.create_install_appointment(
        create_install_appointment_payload(ctx["job_id"], crew["id"],
                                            "2026-06-15T09:00:00Z", "2026-06-15T12:00:00Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(resp, ApiErrorId.ERR_FABRICATION_INCOMPLETE)


def test_install_while_fabrication_in_progress_rejected(api):
    """PRD §3.6: "Next, the job's `fabrication_status` must be `COMPLETE`, else
    `ERR_FABRICATION_INCOMPLETE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/install_requires_fabrication_complete
    """
    ctx = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    furnace = fx.create_furnace(api, max_batch_sqft=500)
    fx.create_batch(api, ctx["job_id"], furnace["id"])  # scheduled, not completed -> IN_FABRICATION
    crew = fx.create_crew(api, certified_products=["SHOWER_ENCLOSURE"])
    resp = api.create_install_appointment(
        create_install_appointment_payload(ctx["job_id"], crew["id"],
                                            "2026-06-15T09:00:00Z", "2026-06-15T12:00:00Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(resp, ApiErrorId.ERR_FABRICATION_INCOMPLETE)


# ==========================================================================
# resource_temporal_overlap / crew_appointment_halfopen_overlap
# ==========================================================================
def test_crew_overlapping_appointment_rejected(api):
    """PRD §3.6: "Finally, the appointment window must not overlap another `SCHEDULED`
    appointment on the same crew, evaluated as half-open intervals, else
    `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/crew_appointment_halfopen_overlap
    """
    job1 = fx.setup_fabricated_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    job2 = fx.setup_fabricated_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    crew = fx.create_crew(api, certified_products=["SHOWER_ENCLOSURE"])
    fx.create_appointment(api, job1["job_id"], crew["id"],
                          start="2026-06-15T09:00:00Z", end="2026-06-15T12:00:00Z")
    resp = api.create_install_appointment(
        create_install_appointment_payload(job2["job_id"], crew["id"],
                                            "2026-06-15T11:00:00Z", "2026-06-15T13:00:00Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED)


def test_crew_touching_appointment_allowed(api):
    """PRD §3.6: "Finally, the appointment window must not overlap another `SCHEDULED`
    appointment on the same crew, evaluated as half-open intervals, else
    `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/crew_appointment_halfopen_overlap
    """
    job1 = fx.setup_fabricated_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    job2 = fx.setup_fabricated_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    crew = fx.create_crew(api, certified_products=["SHOWER_ENCLOSURE"])
    fx.create_appointment(api, job1["job_id"], crew["id"],
                          start="2026-06-15T09:00:00Z", end="2026-06-15T12:00:00Z")
    # 12:00 start touches the prior 12:00 end — half-open intervals do not overlap.
    appt2 = validate_success(api.create_install_appointment(
        create_install_appointment_payload(job2["job_id"], crew["id"],
                                            "2026-06-15T12:00:00Z", "2026-06-15T13:00:00Z"),
        TEST_USERS["scheduler_headers"]), 201)
    assert appt2["status"] == "SCHEDULED", appt2["status"]


# ==========================================================================
# validations / install_crew_not_certified_returns_error
# ==========================================================================
def test_install_crew_not_certified_rejected(api):
    """PRD §3.6: "Then the crew must be certified for every product type present in the job —
    every distinct `product_type` among the job's lines must appear in the crew's
    `certified_products` — else `ERR_CREW_NOT_CERTIFIED` (HTTP 409)."

    Design: Corner/validations/install_crew_not_certified_returns_error
    """
    ctx = fx.setup_fabricated_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    crew = fx.create_crew(api, certified_products=["STOREFRONT"])  # not certified for SHOWER_ENCLOSURE
    resp = api.create_install_appointment(
        create_install_appointment_payload(ctx["job_id"], crew["id"],
                                            "2026-06-15T09:00:00Z", "2026-06-15T12:00:00Z"),
        TEST_USERS["scheduler_headers"])
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_CERTIFIED)
