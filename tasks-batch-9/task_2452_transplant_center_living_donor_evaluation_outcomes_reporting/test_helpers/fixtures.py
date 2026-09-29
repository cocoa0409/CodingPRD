"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses the lenient validator so a broken preamble reports as a
setup failure rather than as a confusing assertion failure.

Identity threading: the four entity-backed roles always act through
`make_<role>_headers(<StaffMember id>)`, never through a shared constant.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH, follow_up_fields
from .factories import (
    create_chain_segment_payload,
    create_donor_candidate_payload,
    create_donor_cost_claim_payload,
    create_exchange_chain_payload,
    create_improvement_plan_payload,
    create_medical_evaluation_payload,
    create_offer_payload,
    create_operating_room_payload,
    create_outcome_review_payload,
    create_procedure_booking_payload,
    create_program_payload,
    create_psychosocial_evaluation_payload,
    create_recipient_candidate_payload,
    create_staff_member_payload,
    create_status_update_payload,
)
from .test_users import (
    make_advocate_headers,
    make_coordinator_headers,
    make_finance_admin_headers,
    make_program_admin_headers,
    make_quality_officer_headers,
    make_reviewer_headers,
)

# ----------------------------------------------------------------------------
# Instant arithmetic helpers
# ----------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def fmt_instant(moment: datetime) -> str:
    """Render an instant in the ISO 8601 UTC form the API accepts."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_instant(value, days=0, hours=0, minutes=0, seconds=0) -> str:
    base = parse_instant(value) if isinstance(value, str) else value
    return fmt_instant(
        base + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    )


def date_plus_days(date_text: str, days: int) -> str:
    """Add whole days to a YYYY-MM-DD date."""
    return (datetime.strptime(date_text[:10], "%Y-%m-%d") + timedelta(days=days)).strftime(
        "%Y-%m-%d"
    )


# ----------------------------------------------------------------------------
# Tier 1 — clock, program, people, theatres
# ----------------------------------------------------------------------------


def set_clock(instant: str, headers=None) -> None:
    """Advance the logical clock. The clock reads CLOCK_EPOCH before any call."""
    get_success_data(
        api_client.set_clock(
            {"current_utc": instant}, headers or make_program_admin_headers()
        )
    )


def create_program(**overrides) -> dict:
    admin_headers = make_program_admin_headers()
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), admin_headers)
    )


def add_staff_member(program_id, staff_role, npi, full_name, **overrides) -> dict:
    return get_success_data(
        api_client.create_staff_member(
            create_staff_member_payload(
                program_id, staff_role, npi, full_name=full_name, **overrides
            ),
            make_program_admin_headers(),
        )
    )


def setup_program_with_staff(**program_overrides) -> dict:
    """Register a program plus the standing cast of credentialed people.

    Returns an environment dict carrying the program, every staff member and the
    correctly threaded headers for each role.
    """
    set_clock(CLOCK_EPOCH)
    program = create_program(**program_overrides)
    program_id = program["id"]
    coordinator = add_staff_member(
        program_id, "TRANSPLANT_COORDINATOR", "1000000001", "Coordinator One"
    )
    advocate = add_staff_member(
        program_id, "LIVING_DONOR_ADVOCATE", "1000000002", "Advocate One"
    )
    reviewer_med = add_staff_member(
        program_id, "EVALUATION_REVIEWER", "1000000003", "Reviewer Med"
    )
    reviewer_psy = add_staff_member(
        program_id, "EVALUATION_REVIEWER", "1000000004", "Reviewer Psy"
    )
    quality_officer = add_staff_member(
        program_id, "QUALITY_OFFICER", "1000000005", "Quality Officer One"
    )
    surgeon = add_staff_member(program_id, "SURGEON", "1000000006", "Surgeon One")
    env = {
        "clock": CLOCK_EPOCH,
        "program": program,
        "program_id": program_id,
        "coordinator": coordinator,
        "advocate": advocate,
        "reviewer_med": reviewer_med,
        "reviewer_psy": reviewer_psy,
        "quality_officer": quality_officer,
        "surgeon": surgeon,
        "admin_headers": make_program_admin_headers(),
        "finance_headers": make_finance_admin_headers(),
        "coordinator_headers": make_coordinator_headers(coordinator["id"]),
        "advocate_headers": make_advocate_headers(advocate["id"]),
        "reviewer_med_headers": make_reviewer_headers(reviewer_med["id"]),
        "reviewer_psy_headers": make_reviewer_headers(reviewer_psy["id"]),
        "quality_headers": make_quality_officer_headers(quality_officer["id"]),
    }
    return env


def add_surgeon(env, npi="1000000007", full_name="Surgeon Two") -> dict:
    return add_staff_member(env["program_id"], "SURGEON", npi, full_name)


def add_operating_room(env, room_code="OR-1", turnover_buffer_minutes=45) -> dict:
    return get_success_data(
        api_client.create_operating_room(
            create_operating_room_payload(
                env["program_id"],
                room_code=room_code,
                turnover_buffer_minutes=turnover_buffer_minutes,
            ),
            env["admin_headers"],
        )
    )


def advance_clock(env, instant: str) -> None:
    set_clock(instant, env["admin_headers"])
    env["clock"] = instant


def refresh_program(env) -> dict:
    program = get_success_data(
        api_client.get_program(env["program_id"], env["admin_headers"])
    )
    env["program"] = program
    return program


# ----------------------------------------------------------------------------
# Tier 2 — recipient candidacy
# ----------------------------------------------------------------------------


def create_recipient(env, **overrides) -> dict:
    """Open a recipient workup. Lands on listing_status WORKUP."""
    return get_success_data(
        api_client.create_recipient_candidate(
            create_recipient_candidate_payload(env["program_id"], **overrides),
            env["coordinator_headers"],
        )
    )


def update_recipient_status(env, recipient_id, to_status, reason_code, effective_at=None):
    return get_success_data(
        api_client.create_recipient_status_update(
            recipient_id,
            create_status_update_payload(
                to_status, reason_code, effective_at or env["clock"]
            ),
            env["coordinator_headers"],
        )
    )


def activate_recipient(env, recipient, effective_at=None) -> dict:
    """Walk WORKUP -> APPROVED_NOT_LISTED -> ACTIVE."""
    moment = effective_at or env["clock"]
    update_recipient_status(
        env, recipient["id"], "APPROVED_NOT_LISTED", "WORKUP_COMPLETE", moment
    )
    return update_recipient_status(env, recipient["id"], "ACTIVE", "LISTED", moment)


def create_active_recipient(env, effective_at=None, **overrides) -> dict:
    recipient = create_recipient(env, **overrides)
    return activate_recipient(env, recipient, effective_at)


def get_recipient(env, recipient_id) -> dict:
    return get_success_data(
        api_client.get_recipient_candidate(recipient_id, env["coordinator_headers"])
    )


# ----------------------------------------------------------------------------
# Tier 2 — donor referral, evaluation, advocacy
# ----------------------------------------------------------------------------


def create_donor(env, intended_recipient_id=None, assign_advocate=True, **overrides) -> dict:
    """Refer a donor. Supplying intended_recipient_id makes the donation directed."""
    payload = create_donor_candidate_payload(env["program_id"], **overrides)
    if intended_recipient_id is not None:
        payload["intended_recipient_id"] = intended_recipient_id
    donor = get_success_data(
        api_client.create_donor_candidate(payload, env["coordinator_headers"])
    )
    if assign_advocate:
        donor = get_success_data(
            api_client.assign_advocate(
                donor["id"],
                {"advocate_staff_id": env["advocate"]["id"]},
                env["admin_headers"],
            )
        )
    return donor


def get_donor(env, donor_id) -> dict:
    return get_success_data(
        api_client.get_donor_candidate(donor_id, env["coordinator_headers"])
    )


def submit_medical_evaluation(env, donor_id, reviewer_headers=None, **findings) -> dict:
    return get_success_data(
        api_client.create_donor_evaluation(
            create_medical_evaluation_payload(donor_id, **findings),
            reviewer_headers or env["reviewer_med_headers"],
        )
    )


def submit_psychosocial_evaluation(env, donor_id, reviewer_headers=None, **findings) -> dict:
    return get_success_data(
        api_client.create_donor_evaluation(
            create_psychosocial_evaluation_payload(donor_id, **findings),
            reviewer_headers or env["reviewer_psy_headers"],
        )
    )


def determine_evaluation(env, evaluation_id, outcome, reviewer_headers) -> dict:
    return get_success_data(
        api_client.record_evaluation_determination(
            evaluation_id, {"outcome": outcome}, reviewer_headers
        )
    )


def clear_both_domains(env, donor_id, medical=None, psychosocial=None) -> tuple:
    """Submit and clear both clinical domains, honouring the reviewer separation."""
    medical_eval = submit_medical_evaluation(env, donor_id, **(medical or {}))
    determine_evaluation(env, medical_eval["id"], "CLEARED", env["reviewer_med_headers"])
    psychosocial_eval = submit_psychosocial_evaluation(
        env, donor_id, **(psychosocial or {})
    )
    determine_evaluation(
        env, psychosocial_eval["id"], "CLEARED", env["reviewer_psy_headers"]
    )
    return medical_eval, psychosocial_eval


def record_disclosure(env, donor_id) -> dict:
    return get_success_data(
        api_client.record_consent_disclosure(donor_id, env["advocate_headers"])
    )


def advance_to_cooling_off_end(env, donor_id) -> dict:
    """Move the logical clock to exactly the donor's cooling_off_ends_at."""
    donor = get_donor(env, donor_id)
    advance_clock(env, fmt_instant(parse_instant(donor["cooling_off_ends_at"])))
    return donor


def attest_donor(env, donor_id) -> dict:
    """Disclose, wait out the cooling-off window and attest."""
    record_disclosure(env, donor_id)
    advance_to_cooling_off_end(env, donor_id)
    return get_success_data(
        api_client.record_advocacy_determination(
            donor_id, {"outcome": "ATTESTED"}, env["advocate_headers"]
        )
    )


def create_approved_donor(
    env, intended_recipient_id=None, medical=None, psychosocial=None, **overrides
) -> dict:
    """Referral -> advocate -> both domains CLEARED -> disclosure -> attestation."""
    donor = create_donor(env, intended_recipient_id=intended_recipient_id, **overrides)
    clear_both_domains(env, donor["id"], medical=medical, psychosocial=psychosocial)
    return attest_donor(env, donor["id"])


# ----------------------------------------------------------------------------
# Tier 3 — chains and segments
# ----------------------------------------------------------------------------


def create_chain(env, chain_type="PAIRED_LOOP", **overrides) -> dict:
    return get_success_data(
        api_client.create_exchange_chain(
            create_exchange_chain_payload(env["program_id"], chain_type, **overrides),
            env["coordinator_headers"],
        )
    )


def get_chain(env, chain_id) -> dict:
    return get_success_data(
        api_client.get_exchange_chain(chain_id, env["coordinator_headers"])
    )


def add_segment(
    env, chain_id, position, donor_id, recipient_id, predecessor_segment_id=None, **overrides
) -> dict:
    """Insert a segment, reading the chain's current version for the OCC field."""
    chain = get_chain(env, chain_id)
    payload = create_chain_segment_payload(
        chain["version"],
        position,
        donor_id,
        recipient_id,
        predecessor_segment_id=predecessor_segment_id,
        **overrides,
    )
    return get_success_data(
        api_client.create_chain_segment(chain_id, payload, env["coordinator_headers"])
    )


def get_segment(env, segment_id) -> dict:
    return get_success_data(
        api_client.get_chain_segment(segment_id, env["coordinator_headers"])
    )


def validate_chain(env, chain_id) -> dict:
    return get_success_data(
        api_client.validate_chain(chain_id, env["coordinator_headers"])
    )


def commit_chain(env, chain_id) -> dict:
    return get_success_data(api_client.commit_chain(chain_id, env["coordinator_headers"]))


def setup_paired_loop_participants(env=None, **program_overrides) -> dict:
    """Two ACTIVE recipients and two APPROVED directed donors that close a loop.

    Donor D-001 came in for recipient R-001 and gives to R-002; donor D-002 came
    in for R-002 and gives back to R-001, so the loop closes.
    """
    env = env or setup_program_with_staff(**program_overrides)
    recipient_one = create_active_recipient(
        env,
        mrn="R-001",
        abo_blood_type="A",
        age_years=44,
        cpra=0.85,
        dialysis_years=3.0,
        medical_urgency_points=7,
    )
    recipient_two = create_active_recipient(
        env,
        mrn="R-002",
        abo_blood_type="B",
        age_years=51,
        cpra=0.1,
        dialysis_years=1.0,
        medical_urgency_points=4,
    )
    donor_one = create_donor(
        env, intended_recipient_id=recipient_one["id"], mrn="D-001", age_years=41
    )
    donor_two = create_donor(
        env, intended_recipient_id=recipient_two["id"], mrn="D-002", age_years=38
    )
    clear_both_domains(env, donor_one["id"])
    clear_both_domains(env, donor_two["id"])
    record_disclosure(env, donor_one["id"])
    record_disclosure(env, donor_two["id"])
    advance_to_cooling_off_end(env, donor_one["id"])
    donor_one = get_success_data(
        api_client.record_advocacy_determination(
            donor_one["id"], {"outcome": "ATTESTED"}, env["advocate_headers"]
        )
    )
    donor_two = get_success_data(
        api_client.record_advocacy_determination(
            donor_two["id"], {"outcome": "ATTESTED"}, env["advocate_headers"]
        )
    )
    env.update(
        {
            "recipient_one": recipient_one,
            "recipient_two": recipient_two,
            "donor_one": donor_one,
            "donor_two": donor_two,
        }
    )
    return env


def build_paired_loop_chain(env) -> dict:
    """Open a PAIRED_LOOP chain over the two prepared pairs. Chain stays DRAFT."""
    chain = create_chain(env, "PAIRED_LOOP")
    segment_one = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    segment_two = add_segment(
        env,
        chain["id"],
        2,
        env["donor_two"]["id"],
        env["recipient_one"]["id"],
        predecessor_segment_id=segment_one["id"],
    )
    env.update(
        {"chain": chain, "segment_one": segment_one, "segment_two": segment_two}
    )
    return env


def setup_validated_paired_loop(env=None, **program_overrides) -> dict:
    env = env or setup_paired_loop_participants(**program_overrides)
    if "chain" not in env:
        build_paired_loop_chain(env)
    env["chain"] = validate_chain(env, env["chain"]["id"])
    return env


def setup_committed_paired_loop(env=None, **program_overrides) -> dict:
    """A two-segment closed loop in COMMITTED with both donors CHAIN_COMMITTED."""
    env = env or setup_validated_paired_loop(**program_overrides)
    if env["chain"]["status"] == "DRAFT":
        env["chain"] = validate_chain(env, env["chain"]["id"])
    env["chain"] = commit_chain(env, env["chain"]["id"])
    return env


# ----------------------------------------------------------------------------
# Tier 3 — theatre, offers, completion
# ----------------------------------------------------------------------------


def book_theatre(
    env, room_id, segment_id, booking_role, start_at, end_at, surgeon_id=None
) -> dict:
    return get_success_data(
        api_client.create_procedure_booking(
            create_procedure_booking_payload(
                room_id,
                segment_id,
                surgeon_id or env["surgeon"]["id"],
                booking_role,
                start_at,
                end_at,
            ),
            env["coordinator_headers"],
        )
    )


def get_room_listing(env, params=None) -> list:
    response = api_client.list_program_operating_rooms(
        env["program_id"], env["admin_headers"], params=params
    )
    return get_success_data(response)


def setup_segment_bookings(
    env,
    segment_id,
    day="2026-08-09",
    recovery_window=("06:00:00", "10:00:00"),
    implant_window=("12:00:00", "15:00:00"),
) -> dict:
    """Reserve a DONOR_RECOVERY and a RECIPIENT_IMPLANT booking for one segment."""
    room_one = env.get("room_one") or add_operating_room(env, "OR-1")
    room_two = env.get("room_two") or add_operating_room(env, "OR-2")
    env["room_one"], env["room_two"] = room_one, room_two
    recovery = book_theatre(
        env,
        room_one["id"],
        segment_id,
        "DONOR_RECOVERY",
        f"{day}T{recovery_window[0]}Z",
        f"{day}T{recovery_window[1]}Z",
    )
    implant = book_theatre(
        env,
        room_two["id"],
        segment_id,
        "RECIPIENT_IMPLANT",
        f"{day}T{implant_window[0]}Z",
        f"{day}T{implant_window[1]}Z",
    )
    return {"donor_recovery": recovery, "recipient_implant": implant}


def send_offer(
    env,
    segment_id,
    planned_cross_clamp_at,
    planned_reperfusion_at,
    planned_transport_minutes=90,
) -> dict:
    return get_success_data(
        api_client.send_segment_offer(
            segment_id,
            create_offer_payload(
                planned_cross_clamp_at, planned_reperfusion_at, planned_transport_minutes
            ),
            env["coordinator_headers"],
        )
    )


def accept_offer(env, segment_id) -> dict:
    return get_success_data(
        api_client.record_offer_response(
            segment_id, {"response": "ACCEPT"}, env["coordinator_headers"]
        )
    )


def complete_transplant(env, segment_id, actual_cross_clamp_at, actual_reperfusion_at) -> dict:
    return get_success_data(
        api_client.record_transplant_completion(
            segment_id,
            {
                "actual_cross_clamp_at": actual_cross_clamp_at,
                "actual_reperfusion_at": actual_reperfusion_at,
            },
            env["coordinator_headers"],
        )
    )


def setup_offered_segment(env=None, **program_overrides) -> dict:
    """A committed loop whose first segment carries a live offer.

    Bookings are 06:00-10:00 (recovery) and 12:00-15:00 (implant) on 9 August;
    the plan clamps at 07:00 and reperfuses at 13:00.
    """
    env = env or setup_committed_paired_loop(**program_overrides)
    if env["segment_one"]["status"] == "OFFER_SENT":
        return env
    env["segment_one_bookings"] = env.get("segment_one_bookings") or setup_segment_bookings(
        env, env["segment_one"]["id"]
    )
    advance_clock(env, "2026-08-09T06:00:00Z")
    env["segment_one"] = send_offer(
        env, env["segment_one"]["id"], "2026-08-09T07:00:00Z", "2026-08-09T13:00:00Z"
    )
    return env


def setup_accepted_segment(env=None, **program_overrides) -> dict:
    env = env or setup_offered_segment(**program_overrides)
    if env["segment_one"]["status"] == "ACCEPTED":
        return env
    if env["segment_one"]["status"] != "OFFER_SENT":
        setup_offered_segment(env)
    env["segment_one"] = accept_offer(env, env["segment_one"]["id"])
    return env


def setup_donated_donor(env=None, **program_overrides) -> dict:
    """Carry the first segment all the way through transplant completion.

    Leaves donor_one DONATED with its three follow-up rows DUE, recipient_two
    TRANSPLANTED and the chain EXECUTING.
    """
    env = env or setup_accepted_segment(**program_overrides)
    if env["segment_one"]["status"] != "TRANSPLANTED":
        if env["segment_one"]["status"] != "ACCEPTED":
            setup_accepted_segment(env)
        env["segment_one"] = complete_transplant(
            env, env["segment_one"]["id"], "2026-08-09T07:05:00Z", "2026-08-09T13:00:00Z"
        )
    env["donor_one"] = get_donor(env, env["donor_one"]["id"])
    env["chain"] = get_chain(env, env["chain"]["id"])
    return env


def list_donor_follow_ups(env, donor_id, params=None) -> list:
    return get_success_data(
        api_client.list_donor_follow_ups(donor_id, env["coordinator_headers"], params=params)
    )


def follow_up_by_interval(env, donor_id, interval_code) -> dict:
    rows = list_donor_follow_ups(env, donor_id, params={"interval_code": interval_code})
    assert rows, f"expected a {interval_code} follow-up row for donor {donor_id}"
    return rows[0]


def submit_follow_up(env, follow_up_id, field_count=None, submitted_fields=None) -> dict:
    fields = submitted_fields if submitted_fields is not None else follow_up_fields(
        field_count or 0
    )
    return get_success_data(
        api_client.submit_follow_up(
            follow_up_id, {"submitted_fields": fields}, env["coordinator_headers"]
        )
    )


def waive_follow_up(env, follow_up_id, waiver_reason_code="DONOR_UNREACHABLE") -> dict:
    return get_success_data(
        api_client.waive_follow_up(
            follow_up_id, {"waiver_reason_code": waiver_reason_code}, env["admin_headers"]
        )
    )


def run_compliance_sweep(env) -> dict:
    return get_success_data(
        api_client.run_compliance_sweep(env["program_id"], env["quality_headers"])
    )


# ----------------------------------------------------------------------------
# Tier 4 — outcome reviews, plans and the posture gate
# ----------------------------------------------------------------------------


def create_outcome_review(env, **overrides) -> dict:
    return get_success_data(
        api_client.create_outcome_review(
            create_outcome_review_payload(env["program_id"], **overrides),
            env["quality_headers"],
        )
    )


def finalize_review(env, review_id) -> dict:
    return get_success_data(
        api_client.finalize_outcome_review(review_id, env["quality_headers"])
    )


def create_finalized_flagged_review(env, **overrides) -> dict:
    """A FINALIZED review whose flag_level is FLAGGED, which freezes the program.

    With an expected rate of 0.8, a cohort of 10 expects 8.00 survivors; 6
    observed survivors give an oe_ratio of 0.7500, strictly below 0.85.
    """
    defaults = {"cohort_size": 10, "observed_survivor_count": 6}
    defaults.update(overrides)
    review = create_outcome_review(env, **defaults)
    return finalize_review(env, review["id"])


def create_finalized_watch_review(env, **overrides) -> dict:
    """A FINALIZED review whose flag_level is WATCH, which restricts the program.

    With an expected rate of 0.8, a cohort of 10 expects 8.00 survivors; 7
    observed survivors give an oe_ratio of 0.8750 — at or above 0.85 and below
    0.95.
    """
    defaults = {"cohort_size": 10, "observed_survivor_count": 7}
    defaults.update(overrides)
    review = create_outcome_review(env, **defaults)
    return finalize_review(env, review["id"])


def file_improvement_plan(env, review_id, expected_review_version=None, **overrides) -> dict:
    if expected_review_version is None:
        expected_review_version = get_success_data(
            api_client.get_outcome_review(review_id, env["quality_headers"])
        )["version"]
    return get_success_data(
        api_client.create_improvement_plan(
            create_improvement_plan_payload(
                review_id, expected_review_version, **overrides
            ),
            env["quality_headers"],
        )
    )


def transition_improvement_plan(env, plan_id, action, decision_reason_code=None) -> dict:
    payload = {"action": action}
    if decision_reason_code is not None:
        payload["decision_reason_code"] = decision_reason_code
    return get_success_data(
        api_client.transition_improvement_plan(plan_id, payload, env["admin_headers"])
    )


def setup_frozen_program(env=None, **program_overrides) -> dict:
    """Drive the program's posture to FROZEN through an unanswered flagged review."""
    env = env or setup_program_with_staff(**program_overrides)
    env["review"] = create_finalized_flagged_review(env)
    refresh_program(env)
    return env


def setup_restricted_program(env=None, **program_overrides) -> dict:
    """Drive the program's posture to RESTRICTED through an open watch review."""
    env = env or setup_program_with_staff(**program_overrides)
    env["review"] = create_finalized_watch_review(env)
    refresh_program(env)
    return env


# ----------------------------------------------------------------------------
# Tier 5 — donor cost claims
# ----------------------------------------------------------------------------


def file_claim(env, donor_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_donor_cost_claim(
            create_donor_cost_claim_payload(donor_id, **overrides),
            env["coordinator_headers"],
        )
    )


def adjudicate_claim(env, claim_id, decision="APPROVE", decision_reason_code=None) -> dict:
    payload = {"decision": decision}
    if decision_reason_code is not None:
        payload["decision_reason_code"] = decision_reason_code
    return get_success_data(
        api_client.adjudicate_claim(claim_id, payload, env["finance_headers"])
    )


def reverse_claim(env, claim_id, reversal_reason_code="FILED_IN_ERROR") -> dict:
    return get_success_data(
        api_client.reverse_claim(
            claim_id, {"reversal_reason_code": reversal_reason_code}, env["finance_headers"]
        )
    )


def file_and_approve_claim(env, donor_id, **overrides) -> dict:
    claim = file_claim(env, donor_id, **overrides)
    return adjudicate_claim(env, claim["id"])


def setup_donor_with_exhausted_lifetime_headroom(env=None, **program_overrides) -> dict:
    """A DONATED donor with 1,350,000 cents already adjudicated.

    A 1,000,000-cent medical claim against recipient insurance plus a
    350,000-cent travel claim against the NLDAC grant leave only 150,000 cents of
    the 1,500,000-cent lifetime cap.
    """
    env = env or setup_donated_donor(**program_overrides)
    donor_id = env["donor_one"]["id"]
    env["claim_medical"] = file_and_approve_claim(
        env,
        donor_id,
        claim_type="MEDICAL",
        coverage_source="RECIPIENT_INSURANCE",
        submitted_amount_cents=1000000,
    )
    env["claim_travel"] = file_and_approve_claim(
        env,
        donor_id,
        claim_type="TRAVEL",
        coverage_source="NLDAC_GRANT",
        submitted_amount_cents=400000,
        service_to_on="2026-08-10",
    )
    refresh_program(env)
    return env
