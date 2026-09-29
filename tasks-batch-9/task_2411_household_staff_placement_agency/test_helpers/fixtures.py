"""Composite setup helpers.

Every helper here drives the real API through PRD-declared endpoints only, and
uses ``get_success_data`` so that a broken precondition reports as a setup
failure rather than as a confusing assertion failure inside a test.

The central helper is :func:`setup_scenario`, which walks the full household →
requisition → candidate → trial → negotiation → offer → active placement
pipeline and stops at whichever ``stage`` the caller asks for. Every stage name
is a real state of the system, so a test that needs a requisition in
``SOURCING`` asks for ``stage="sourcing"`` and nothing more runs.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_SCENARIO, DEFAULT_CLOCK_UTC, SENIOR_SCENARIO
from .factories import (
    adjudicate_background_payload,
    attest_handoff_payload,
    cancel_trial_payload,
    confirm_start_payload,
    countersign_agreement_payload,
    create_accommodation_term_payload,
    create_background_verification_payload,
    create_candidate_payload,
    create_client_payload,
    create_fee_schedule_payload,
    create_non_solicitation_case_payload,
    create_payroll_handoff_payload,
    create_placement_payload,
    create_reference_check_payload,
    create_replacement_claim_payload,
    create_requisition_payload,
    create_trial_engagement_payload,
    finalize_scope_payload,
    invoice_milestone_payload,
    investigate_case_payload,
    ledger_adjustment_payload,
    record_background_result_payload,
    record_payment_payload,
    record_trial_outcome_payload,
    resolve_case_payload,
    respond_accommodation_term_payload,
    review_claim_payload,
    scope_requisition_payload,
    settle_case_payload,
    sign_agreement_payload,
    start_trial_payload,
    terminate_placement_payload,
    update_ein_payload,
    verify_reference_payload,
)
from .test_users import (
    TEST_USERS,
    make_candidate_headers,
    make_client_headers,
    make_compliance_officer_headers,
    make_vetting_specialist_headers,
    COMPLIANCE_OPENER_USER_ID,
    COMPLIANCE_RESOLVER_USER_ID,
    VETTING_RECORDER_USER_ID,
    VETTING_VERIFIER_USER_ID,
)

PRINCIPAL = TEST_USERS["agency_principal_headers"]
CONSULTANT = TEST_USERS["placement_consultant_headers"]
BILLING = TEST_USERS["billing_administrator_headers"]
RECORDER = make_vetting_specialist_headers(VETTING_RECORDER_USER_ID)
VERIFIER = make_vetting_specialist_headers(VETTING_VERIFIER_USER_ID)
CASE_OPENER = make_compliance_officer_headers(COMPLIANCE_OPENER_USER_ID)
CASE_RESOLVER = make_compliance_officer_headers(COMPLIANCE_RESOLVER_USER_ID)

# The ordered pipeline. ``setup_scenario`` runs every stage up to and including
# the requested one.
STAGES = (
    "clock",
    "household",
    "onboarded",
    "fee_schedule",
    "requisition",
    "scoping",
    "sourcing",
    "candidate",
    "references_recorded",
    "references_verified",
    "background_ordered",
    "background_recorded",
    "trial_booked",
    "trial_started",
    "trial_passed",
    "term_proposed",
    "term_accepted",
    "placement_pending",
    "placement_active",
)

# The two adjacent twelve-month references that make up the default chain: a
# 2022 year followed by the 2023 year that abuts it, giving 24 contiguous months.
DEFAULT_REFERENCES = (
    {
        "principal_employer_name": "Whitfield Residence",
        "relationship_type": "PRINCIPAL_EMPLOYER",
        "employment_start_month": "2022-01",
        "employment_end_month": "2022-12",
        "contact_email": "whitfield@mail.example",
    },
    {
        "principal_employer_name": "Marlow Estate",
        "relationship_type": "PRINCIPAL_EMPLOYER",
        "employment_start_month": "2023-01",
        "employment_end_month": "2023-12",
        "contact_email": "marlow@mail.example",
        "chain_to_previous": True,
    },
)


# --- Primitive steps ---------------------------------------------------------


def set_clock(current_utc: str) -> dict:
    """Move the logical clock and run the ops sweep (PRD §2.6)."""
    return get_success_data(api_client.set_clock(current_utc))


def advance_clock(current_utc: str) -> dict:
    return set_clock(current_utc)


def read_clock() -> dict:
    return get_success_data(api_client.get_clock())


def create_household(**overrides) -> dict:
    """Intake a prospective household. Returns the Client row in PROSPECT."""
    return get_success_data(
        api_client.create_client(create_client_payload(**overrides), PRINCIPAL)
    )


def onboard_household(client: dict, signatory_name=None) -> dict:
    """Sign as the household then countersign as the agency, taking the Client
    PROSPECT → ONBOARDED. The signature is ownership-gated, so it is made with
    the household's own identity."""
    headers = make_client_headers(client["id"])
    sign = sign_agreement_payload()
    if signatory_name is not None:
        sign["signatory_name"] = signatory_name
    get_success_data(
        api_client.confidentiality_agreement(client["id"], sign, headers)
    )
    return get_success_data(
        api_client.confidentiality_agreement(
            client["id"], countersign_agreement_payload(), PRINCIPAL
        )
    )


def create_onboarded_household(**overrides) -> dict:
    """Household whose confidentiality agreement is COUNTERSIGNED."""
    client = create_household(**overrides)
    return onboard_household(client)


def publish_fee_schedule(**overrides) -> dict:
    return get_success_data(
        api_client.create_fee_schedule(create_fee_schedule_payload(**overrides), PRINCIPAL)
    )


def retire_fee_schedule(fee_schedule: dict) -> dict:
    return get_success_data(
        api_client.retire_fee_schedule(fee_schedule["id"], None, PRINCIPAL)
    )


def open_requisition(client: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_requisition(
            create_requisition_payload(client["id"], **overrides), CONSULTANT
        )
    )


def run_scoping_round(requisition: dict, **overrides) -> dict:
    return get_success_data(
        api_client.scope_requisition(
            requisition["id"], scope_requisition_payload(**overrides), CONSULTANT
        )
    )


def finalize_scope(requisition: dict, **overrides) -> dict:
    return get_success_data(
        api_client.finalize_scope(
            requisition["id"], finalize_scope_payload(**overrides), CONSULTANT
        )
    )


def register_candidate(**overrides) -> dict:
    return get_success_data(
        api_client.create_candidate(create_candidate_payload(**overrides), RECORDER)
    )


def record_reference(candidate: dict, prior_reference_id=None, **overrides) -> dict:
    payload = create_reference_check_payload(**overrides)
    if prior_reference_id is not None:
        payload["prior_reference_id"] = prior_reference_id
    return get_success_data(
        api_client.create_reference_check(candidate["id"], payload, RECORDER)
    )


def verify_reference(reference: dict, outcome="VERIFIED", **overrides) -> dict:
    """Verified by u_vet_2, who is never the recorder (PRD §2.10)."""
    return get_success_data(
        api_client.verify_reference_check(
            reference["id"], verify_reference_payload(outcome, **overrides), VERIFIER
        )
    )


def order_background_verification(candidate: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_background_verification(
            candidate["id"],
            create_background_verification_payload(**overrides),
            VERIFIER,
        )
    )


def record_background_result(verification: dict, result="CLEARED", **overrides) -> dict:
    return get_success_data(
        api_client.record_background_result(
            verification["id"],
            record_background_result_payload(result, **overrides),
            VERIFIER,
        )
    )


def adjudicate_background(verification: dict, disposition, candidate_version) -> dict:
    return get_success_data(
        api_client.adjudicate_background_verification(
            verification["id"],
            adjudicate_background_payload(disposition, candidate_version),
            PRINCIPAL,
        )
    )


def book_trial(requisition: dict, candidate: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_trial_engagement(
            requisition["id"],
            create_trial_engagement_payload(candidate["id"], **overrides),
            CONSULTANT,
        )
    )


def start_trial(trial: dict) -> dict:
    return get_success_data(
        api_client.start_trial(trial["id"], start_trial_payload(), CONSULTANT)
    )


def record_trial_outcome(trial: dict, outcome="PASSED") -> dict:
    return get_success_data(
        api_client.record_trial_outcome(
            trial["id"], record_trial_outcome_payload(outcome), CONSULTANT
        )
    )


def cancel_trial(trial: dict, cancel_reason="CLIENT_REQUEST") -> dict:
    return get_success_data(
        api_client.cancel_trial(
            trial["id"], cancel_trial_payload(cancel_reason), CONSULTANT
        )
    )


def propose_accommodation_term(requisition: dict, candidate: dict, **overrides) -> dict:
    """Open a negotiation. The write is version-gated, so the requisition's
    current version is read immediately beforehand (PRD §2.8)."""
    current = read_requisition(requisition)
    return get_success_data(
        api_client.create_accommodation_term(
            requisition["id"],
            create_accommodation_term_payload(
                candidate["id"], current["version"], **overrides
            ),
            CONSULTANT,
        )
    )


def respond_to_term(term: dict, headers, response="ACCEPT", **overrides) -> dict:
    return get_success_data(
        api_client.respond_accommodation_term(
            term["id"], respond_accommodation_term_payload(response, **overrides), headers
        )
    )


def extend_offer(requisition: dict, candidate: dict, **overrides) -> dict:
    """Create a placement. Version-gated on the requisition (PRD §2.8)."""
    current = read_requisition(requisition)
    return get_success_data(
        api_client.create_placement(
            create_placement_payload(
                requisition["id"], candidate["id"], current["version"], **overrides
            ),
            CONSULTANT,
        )
    )


def confirm_start(placement: dict) -> dict:
    return get_success_data(
        api_client.confirm_placement_start(
            placement["id"], confirm_start_payload(), PRINCIPAL
        )
    )


# --- Re-reads ----------------------------------------------------------------


def read_client(client) -> dict:
    client_id = client["id"] if isinstance(client, dict) else client
    return get_success_data(api_client.get_client(client_id, PRINCIPAL))


def read_requisition(requisition) -> dict:
    requisition_id = requisition["id"] if isinstance(requisition, dict) else requisition
    return get_success_data(api_client.get_requisition(requisition_id, CONSULTANT))


def read_candidate(candidate) -> dict:
    candidate_id = candidate["id"] if isinstance(candidate, dict) else candidate
    return get_success_data(api_client.get_candidate(candidate_id, CONSULTANT))


def read_reference(reference) -> dict:
    reference_id = reference["id"] if isinstance(reference, dict) else reference
    return get_success_data(api_client.get_reference_check(reference_id, CONSULTANT))


def read_background_verification(verification) -> dict:
    verification_id = (
        verification["id"] if isinstance(verification, dict) else verification
    )
    return get_success_data(
        api_client.get_background_verification(verification_id, CONSULTANT)
    )


def read_trial(trial) -> dict:
    trial_id = trial["id"] if isinstance(trial, dict) else trial
    return get_success_data(api_client.get_trial_engagement(trial_id, CONSULTANT))


def read_term(term) -> dict:
    term_id = term["id"] if isinstance(term, dict) else term
    return get_success_data(api_client.get_accommodation_term(term_id, CONSULTANT))


def read_placement(placement) -> dict:
    placement_id = placement["id"] if isinstance(placement, dict) else placement
    return get_success_data(api_client.get_placement(placement_id, PRINCIPAL))


def read_milestone(milestone) -> dict:
    milestone_id = milestone["id"] if isinstance(milestone, dict) else milestone
    return get_success_data(api_client.get_fee_milestone(milestone_id, BILLING))


def read_claim(claim) -> dict:
    claim_id = claim["id"] if isinstance(claim, dict) else claim
    return get_success_data(api_client.get_replacement_claim(claim_id, PRINCIPAL))


def read_handoff(handoff) -> dict:
    handoff_id = handoff["id"] if isinstance(handoff, dict) else handoff
    return get_success_data(api_client.get_payroll_handoff(handoff_id, PRINCIPAL))


def read_case(case) -> dict:
    case_id = case["id"] if isinstance(case, dict) else case
    return get_success_data(api_client.get_non_solicitation_case(case_id, PRINCIPAL))


def read_milestones(placement) -> list:
    """The placement's three billing rows, in ascending sequence_no order."""
    placement_id = placement["id"] if isinstance(placement, dict) else placement
    body = get_success_data(api_client.list_fee_milestones(placement_id, BILLING))
    rows = body if isinstance(body, list) else body.get("items", body)
    return sorted(rows, key=lambda row: row["sequence_no"])


def read_ledger(client) -> list:
    """The household's append-only ledger, in ascending sequence_no order."""
    client_id = client["id"] if isinstance(client, dict) else client
    body = get_success_data(api_client.list_ledger_entries(client_id, BILLING))
    rows = body if isinstance(body, list) else body.get("items", body)
    return sorted(rows, key=lambda row: row["sequence_no"])


# --- The pipeline ------------------------------------------------------------


def setup_scenario(stage="placement_active", **options) -> dict:
    """Walk the placement pipeline and stop at ``stage``.

    Recognised options, all optional:

    ``clock``                initial logical clock (default 2026-08-01T00:00:00Z)
    ``client``               overrides for the household payload
    ``signatory_name``       name used when the household signs
    ``fee_schedules``        list of fee-band override dicts (default one band)
    ``requisition``          overrides for the requisition payload
    ``scope``                overrides for the scoping round payload
    ``candidate``            overrides for the candidate payload
    ``references``           list of reference override dicts; a member carrying
                             ``chain_to_previous`` is linked to the row before it
    ``verify_outcomes``      per-reference verification outcomes
    ``background``           overrides for the background order payload
    ``background_result``    CLEARED, FLAGGED or INCONCLUSIVE
    ``trial``                overrides for the trial booking payload
    ``trial_end_clock``      clock instant used to start and close the trial
    ``trial_outcome``        PASSED or FAILED
    ``term``                 overrides for the accommodation term payload
    ``term_response``        COUNTER, ACCEPT or REJECT
    ``term_responder``       ``"CLIENT"`` or ``"CANDIDATE"``
    ``placement``            overrides for the offer payload
    ``start_date_clock``     clock instant used before confirming the start

    Returns a bundle whose keys are filled in as the pipeline progresses.
    """
    assert stage in STAGES, f"unknown stage {stage!r}"
    reached = STAGES.index(stage)

    def wanted(name):
        return reached >= STAGES.index(name)

    bundle = {
        "client": None,
        "client_headers": None,
        "fee_schedules": [],
        "fee_schedule": None,
        "requisition": None,
        "candidate": None,
        "candidate_headers": None,
        "references": [],
        "background": None,
        "trial": None,
        "term": None,
        "placement": None,
        "milestones": [],
    }

    bundle["clock"] = set_clock(options.get("clock", DEFAULT_CLOCK_UTC))
    if not wanted("household"):
        return bundle

    bundle["client"] = create_household(**options.get("client", {}))
    bundle["client_headers"] = make_client_headers(bundle["client"]["id"])
    if not wanted("onboarded"):
        return bundle

    bundle["client"] = onboard_household(
        bundle["client"], options.get("signatory_name")
    )
    if not wanted("fee_schedule"):
        return bundle

    for band in options.get("fee_schedules", [{}]):
        bundle["fee_schedules"].append(publish_fee_schedule(**band))
    if bundle["fee_schedules"]:
        bundle["fee_schedule"] = bundle["fee_schedules"][0]
    if not wanted("requisition"):
        return bundle

    bundle["requisition"] = open_requisition(
        bundle["client"], **options.get("requisition", {})
    )
    if not wanted("scoping"):
        return bundle

    bundle["requisition"] = run_scoping_round(
        bundle["requisition"], **options.get("scope", {})
    )
    if not wanted("sourcing"):
        return bundle

    bundle["requisition"] = finalize_scope(bundle["requisition"])
    if not wanted("candidate"):
        return bundle

    bundle["candidate"] = register_candidate(**options.get("candidate", {}))
    bundle["candidate_headers"] = make_candidate_headers(bundle["candidate"]["id"])
    if not wanted("references_recorded"):
        return bundle

    previous_id = None
    for spec in options.get("references", DEFAULT_REFERENCES):
        spec = dict(spec)
        chain = spec.pop("chain_to_previous", False)
        reference = record_reference(
            bundle["candidate"],
            prior_reference_id=previous_id if chain else None,
            **spec,
        )
        bundle["references"].append(reference)
        previous_id = reference["id"]
    if not wanted("references_verified"):
        return bundle

    outcomes = options.get("verify_outcomes") or ["VERIFIED"] * len(
        bundle["references"]
    )
    bundle["references"] = [
        verify_reference(reference, outcome)
        for reference, outcome in zip(bundle["references"], outcomes)
    ]
    bundle["candidate"] = read_candidate(bundle["candidate"])
    if not wanted("background_ordered"):
        return bundle

    bundle["background"] = order_background_verification(
        bundle["candidate"], **options.get("background", {})
    )
    if not wanted("background_recorded"):
        return bundle

    bundle["background"] = record_background_result(
        bundle["background"], options.get("background_result", "CLEARED")
    )
    bundle["candidate"] = read_candidate(bundle["candidate"])
    if not wanted("trial_booked"):
        return bundle

    bundle["trial"] = book_trial(
        bundle["requisition"], bundle["candidate"], **options.get("trial", {})
    )
    bundle["requisition"] = read_requisition(bundle["requisition"])
    bundle["candidate"] = read_candidate(bundle["candidate"])
    if not wanted("trial_started"):
        return bundle

    bundle["clock"] = set_clock(
        options.get("trial_end_clock", "2026-08-10T17:00:00Z")
    )
    bundle["trial"] = start_trial(bundle["trial"])
    if not wanted("trial_passed"):
        return bundle

    bundle["trial"] = record_trial_outcome(
        bundle["trial"], options.get("trial_outcome", "PASSED")
    )
    bundle["requisition"] = read_requisition(bundle["requisition"])
    bundle["candidate"] = read_candidate(bundle["candidate"])
    if not wanted("term_proposed"):
        return bundle

    bundle["term"] = propose_accommodation_term(
        bundle["requisition"], bundle["candidate"], **options.get("term", {})
    )
    bundle["requisition"] = read_requisition(bundle["requisition"])
    if not wanted("term_accepted"):
        return bundle

    responder = options.get("term_responder", "CLIENT")
    headers = (
        bundle["client_headers"] if responder == "CLIENT" else bundle["candidate_headers"]
    )
    bundle["term"] = respond_to_term(
        bundle["term"], headers, options.get("term_response", "ACCEPT")
    )
    bundle["requisition"] = read_requisition(bundle["requisition"])
    if not wanted("placement_pending"):
        return bundle

    bundle["placement"] = extend_offer(
        bundle["requisition"], bundle["candidate"], **options.get("placement", {})
    )
    bundle["requisition"] = read_requisition(bundle["requisition"])
    bundle["candidate"] = read_candidate(bundle["candidate"])
    bundle["milestones"] = read_milestones(bundle["placement"])
    if not wanted("placement_active"):
        return bundle

    start_clock = options.get("start_date_clock")
    if start_clock is None:
        start_clock = f"{bundle['placement']['start_date']}T00:00:00Z"
    bundle["clock"] = set_clock(start_clock)
    bundle["placement"] = confirm_start(bundle["placement"])
    bundle["candidate"] = read_candidate(bundle["candidate"])
    bundle["client"] = read_client(bundle["client"])
    bundle["milestones"] = read_milestones(bundle["placement"])
    return bundle


# --- Named shortcuts over the pipeline ---------------------------------------


def setup_onboarded_household(**options) -> dict:
    """Household in ONBOARDED with one published fee band."""
    return setup_scenario(stage="fee_schedule", **options)


def setup_sourcing_requisition(**options) -> dict:
    """Requisition in SOURCING with its fee band resolved and stamped."""
    return setup_scenario(stage="sourcing", **options)


def setup_vetted_candidate(**options) -> dict:
    """Candidate whose two adjacent references are VERIFIED and whose background
    screen has been recorded, alongside a SOURCING requisition."""
    return setup_scenario(stage="background_recorded", **options)


def setup_booked_trial(**options) -> dict:
    """Trial in SCHEDULED, requisition in TRIALING, candidate ON_TRIAL."""
    return setup_scenario(stage="trial_booked", **options)


def setup_passed_trial(**options) -> dict:
    """Trial in PASSED, ready for a negotiation to open."""
    return setup_scenario(stage="trial_passed", **options)


def setup_accepted_term(**options) -> dict:
    """Accommodation term in ACCEPTED, ready for an offer."""
    return setup_scenario(stage="term_accepted", **options)


def setup_pending_offer(**options) -> dict:
    """Placement in PENDING_ACCEPTANCE priced with the PROVISIONAL fee, with its
    three milestone rows already allocated."""
    return setup_scenario(stage="placement_pending", **options)


def setup_active_placement(**options) -> dict:
    """Placement in ACTIVE, re-priced with the FINAL fee on confirm-start."""
    return setup_scenario(stage="placement_active", **options)


# --- The senior family: two fee bands and a package on the upper floor ------

SENIOR_FEE_BANDS = (
    {
        "role_type": SENIOR_SCENARIO["ROLE_TYPE"],
        "comp_band_floor_cents": SENIOR_SCENARIO["LOWER_BAND_FLOOR_CENTS"],
        "comp_band_ceiling_cents": SENIOR_SCENARIO["LOWER_BAND_CEILING_CENTS"],
        "fee_percent_bps": SENIOR_SCENARIO["LOWER_BAND_FEE_BPS"],
        "guarantee_window_days": SENIOR_SCENARIO["GUARANTEE_WINDOW_DAYS"],
        "effective_from": SENIOR_SCENARIO["EFFECTIVE_FROM"],
    },
    {
        "role_type": SENIOR_SCENARIO["ROLE_TYPE"],
        "comp_band_floor_cents": SENIOR_SCENARIO["UPPER_BAND_FLOOR_CENTS"],
        "comp_band_ceiling_cents": SENIOR_SCENARIO["UPPER_BAND_CEILING_CENTS"],
        "fee_percent_bps": SENIOR_SCENARIO["UPPER_BAND_FEE_BPS"],
        "guarantee_window_days": SENIOR_SCENARIO["GUARANTEE_WINDOW_DAYS"],
        "effective_from": SENIOR_SCENARIO["EFFECTIVE_FROM"],
    },
)

SENIOR_REFERENCES = (
    {
        "principal_employer_name": "Grantham Estate",
        "relationship_type": "PRINCIPAL_EMPLOYER",
        "employment_start_month": "2022-01",
        "employment_end_month": "2022-12",
        "contact_email": "grantham@mail.example",
    },
    {
        "principal_employer_name": "Ravensworth Hall",
        "relationship_type": "PRINCIPAL_EMPLOYER",
        "employment_start_month": "2023-01",
        "employment_end_month": "2023-12",
        "contact_email": "ravensworth@mail.example",
        "chain_to_previous": True,
    },
)


def senior_options(**options) -> dict:
    """Option bundle for the ESTATE_MANAGER family: two touching fee bands, a
    compensation of exactly 15,000,000 cents sitting on the upper band's
    inclusive floor, and a four-component package that sums to it."""
    merged = {
        "client": {
            "household_name": SENIOR_SCENARIO["HOUSEHOLD_NAME"],
            "primary_contact_email": SENIOR_SCENARIO["CONTACT_EMAIL"],
            "region_code": SENIOR_SCENARIO["REGION_CODE"],
        },
        "signatory_name": SENIOR_SCENARIO["SIGNATORY_NAME"],
        "fee_schedules": [dict(band) for band in SENIOR_FEE_BANDS],
        "requisition": {
            "role_type": SENIOR_SCENARIO["ROLE_TYPE"],
            "first_year_compensation_cents": SENIOR_SCENARIO["COMPENSATION_CENTS"],
            "schedule_pattern": SENIOR_SCENARIO["SCHEDULE_PATTERN"],
            "live_in_required": True,
        },
        "term": {
            "live_in": True,
            "weekly_hours": 45,
            "days_off_per_week": 2,
            "private_quarters": True,
            "imputed_accommodation_cents": SENIOR_SCENARIO[
                "ACCOMMODATION_IMPUTED_CENTS"
            ],
        },
        "candidate": {
            "full_name": SENIOR_SCENARIO["CANDIDATE_NAME"],
            "contact_email": SENIOR_SCENARIO["CANDIDATE_EMAIL"],
            "primary_role_type": SENIOR_SCENARIO["ROLE_TYPE"],
            "years_experience": SENIOR_SCENARIO["YEARS_EXPERIENCE"],
            "live_in_willing": True,
        },
        "references": [dict(reference) for reference in SENIOR_REFERENCES],
        "trial": {"day_rate_cents": SENIOR_SCENARIO["TRIAL_DAY_RATE_CENTS"]},
        "placement": {
            "start_date": SENIOR_SCENARIO["START_DATE"],
            "base_salary_cents": SENIOR_SCENARIO["BASE_SALARY_CENTS"],
            "guaranteed_bonus_cents": SENIOR_SCENARIO["GUARANTEED_BONUS_CENTS"],
            "accommodation_imputed_cents": SENIOR_SCENARIO[
                "ACCOMMODATION_IMPUTED_CENTS"
            ],
            "overtime_allowance_cents": SENIOR_SCENARIO["OVERTIME_ALLOWANCE_CENTS"],
        },
    }
    for key, value in options.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def setup_senior_scenario(stage="placement_active", **options) -> dict:
    return setup_scenario(stage=stage, **senior_options(**options))


# --- Payroll handoff ---------------------------------------------------------


def prepare_payroll_handoff(placement, **overrides) -> dict:
    placement_id = placement["id"] if isinstance(placement, dict) else placement
    return get_success_data(
        api_client.create_payroll_handoff(
            placement_id, create_payroll_handoff_payload(**overrides), CASE_OPENER
        )
    )


def update_handoff_ein(handoff: dict, ein_status="ISSUED") -> dict:
    return get_success_data(
        api_client.update_payroll_handoff_ein(
            handoff["id"], update_ein_payload(ein_status), CASE_OPENER
        )
    )


def attest_handoff(handoff: dict, client_headers, **overrides) -> dict:
    return get_success_data(
        api_client.attest_payroll_handoff(
            handoff["id"], attest_handoff_payload(**overrides), client_headers
        )
    )


def setup_attested_handoff(scenario: dict) -> dict:
    """Prepare a handoff, take its EIN to ISSUED and have the household attest
    it, which is what unblocks the START_DATE milestone (PRD §3.7)."""
    handoff = prepare_payroll_handoff(scenario["placement"])
    handoff = update_handoff_ein(handoff, "ISSUED")
    handoff = attest_handoff(handoff, scenario["client_headers"])
    scenario["handoff"] = handoff
    return handoff


# --- Billing -----------------------------------------------------------------


def invoice_milestone(milestone) -> dict:
    milestone_id = milestone["id"] if isinstance(milestone, dict) else milestone
    return get_success_data(
        api_client.invoice_fee_milestone(
            milestone_id, invoice_milestone_payload(), BILLING
        )
    )


def pay_milestone(milestone: dict, paid_amount_cents=None) -> dict:
    amount = (
        milestone["amount_cents"] if paid_amount_cents is None else paid_amount_cents
    )
    return get_success_data(
        api_client.record_milestone_payment(
            milestone["id"], record_payment_payload(amount), BILLING
        )
    )


def reverse_milestone(milestone) -> dict:
    milestone_id = milestone["id"] if isinstance(milestone, dict) else milestone
    return get_success_data(
        api_client.reverse_fee_milestone(milestone_id, None, BILLING)
    )


def invoice_and_pay(milestone: dict) -> dict:
    invoiced = invoice_milestone(milestone)
    return pay_milestone(invoiced)


def setup_placement_with_engagement_invoiced(**options) -> dict:
    """ACTIVE placement whose ENGAGEMENT milestone is INVOICED, so the household
    carries exactly that receivable."""
    scenario = setup_active_placement(**options)
    scenario["milestones"][0] = invoice_milestone(scenario["milestones"][0])
    scenario["client"] = read_client(scenario["client"])
    return scenario


def setup_placement_with_first_two_paid(**options) -> dict:
    """ACTIVE placement whose ENGAGEMENT and TRIAL_CLEARED milestones are PAID,
    leaving the START_DATE row PENDING behind the handoff gate."""
    scenario = setup_active_placement(**options)
    scenario["milestones"][0] = invoice_and_pay(scenario["milestones"][0])
    scenario["milestones"][1] = invoice_and_pay(scenario["milestones"][1])
    scenario["client"] = read_client(scenario["client"])
    scenario["placement"] = read_placement(scenario["placement"])
    return scenario


def setup_fully_billed_placement(**options) -> dict:
    """ACTIVE placement with all three milestones PAID; requires the payroll
    handoff to be ATTESTED before the START_DATE row can be invoiced."""
    scenario = setup_active_placement(**options)
    setup_attested_handoff(scenario)
    scenario["milestones"] = [
        invoice_and_pay(milestone) for milestone in scenario["milestones"]
    ]
    scenario["client"] = read_client(scenario["client"])
    scenario["placement"] = read_placement(scenario["placement"])
    return scenario


def append_ledger_adjustment(client, signed_amount_cents, **overrides) -> dict:
    client_id = client["id"] if isinstance(client, dict) else client
    return get_success_data(
        api_client.create_ledger_adjustment(
            client_id,
            ledger_adjustment_payload(signed_amount_cents, **overrides),
            BILLING,
        )
    )


# --- Termination, claims and remedies ---------------------------------------


def terminate_placement(placement, separation_date) -> dict:
    placement_id = placement["id"] if isinstance(placement, dict) else placement
    return get_success_data(
        api_client.terminate_placement(
            placement_id, terminate_placement_payload(separation_date), CONSULTANT
        )
    )


def file_claim(placement, client_headers, requested_remedy, separation_date) -> dict:
    """File a claim as the household. Version-gated on the placement (PRD §2.8)."""
    current = read_placement(placement)
    return get_success_data(
        api_client.create_replacement_claim(
            current["id"],
            create_replacement_claim_payload(
                requested_remedy, separation_date, current["version"]
            ),
            client_headers,
        )
    )


def review_claim(claim, action) -> dict:
    claim_id = claim["id"] if isinstance(claim, dict) else claim
    return get_success_data(
        api_client.review_replacement_claim(
            claim_id, review_claim_payload(action), PRINCIPAL
        )
    )


def setup_terminated_placement(separation_date="2026-10-16", **options) -> dict:
    """ACTIVE placement whose first milestone is PAID and which has then been
    terminated inside the guarantee window."""
    scenario = setup_active_placement(**options)
    scenario["milestones"][0] = invoice_and_pay(scenario["milestones"][0])
    scenario["clock"] = set_clock(f"{separation_date}T00:00:00Z")
    scenario["placement"] = terminate_placement(scenario["placement"], separation_date)
    scenario["client"] = read_client(scenario["client"])
    scenario["separation_date"] = separation_date
    return scenario


def setup_claim_under_review(
    requested_remedy="REFUND", separation_date="2026-10-16", **options
) -> dict:
    """Claim filed inside the guarantee window and moved to UNDER_REVIEW, which
    is the only state from which it may be decided."""
    scenario = setup_terminated_placement(separation_date, **options)
    claim = file_claim(
        scenario["placement"],
        scenario["client_headers"],
        requested_remedy,
        separation_date,
    )
    scenario["claim"] = review_claim(claim, "OPEN_REVIEW")
    return scenario


def setup_refunded_placement(separation_date="2026-10-16", **options) -> dict:
    """Claim approved for a refund, so the proration figures are stamped and the
    refund has been posted to the ledger."""
    scenario = setup_claim_under_review("REFUND", separation_date, **options)
    scenario["claim"] = review_claim(scenario["claim"], "APPROVE_REFUND")
    scenario["placement"] = read_placement(scenario["placement"])
    scenario["client"] = read_client(scenario["client"])
    scenario["milestones"] = read_milestones(scenario["placement"])
    return scenario


# --- Non-solicitation enforcement -------------------------------------------


def file_enforcement_case(
    client, candidate, discovered_on, source_placement=None, **overrides
) -> dict:
    client_id = client["id"] if isinstance(client, dict) else client
    candidate_id = candidate["id"] if isinstance(candidate, dict) else candidate
    payload = create_non_solicitation_case_payload(
        client_id, candidate_id, discovered_on, **overrides
    )
    if source_placement is not None:
        payload["source_placement_id"] = (
            source_placement["id"]
            if isinstance(source_placement, dict)
            else source_placement
        )
    return get_success_data(
        api_client.create_non_solicitation_case(payload, CASE_OPENER)
    )


def investigate_case(case) -> dict:
    case_id = case["id"] if isinstance(case, dict) else case
    return get_success_data(
        api_client.investigate_non_solicitation_case(
            case_id, investigate_case_payload(), CASE_OPENER
        )
    )


def resolve_case(case, disposition) -> dict:
    """Resolved by u_comp_2, who is never the opener (PRD §2.10)."""
    case_id = case["id"] if isinstance(case, dict) else case
    return get_success_data(
        api_client.resolve_non_solicitation_case(
            case_id, resolve_case_payload(disposition), CASE_RESOLVER
        )
    )


def settle_case(case, settlement_amount_cents) -> dict:
    case_id = case["id"] if isinstance(case, dict) else case
    return get_success_data(
        api_client.settle_non_solicitation_case(
            case_id, settle_case_payload(settlement_amount_cents), BILLING
        )
    )


def setup_investigating_case(discovered_on="2026-10-01", **options) -> dict:
    """Enforcement case in INVESTIGATING against a household that has an ACTIVE
    placement, so the case has a source placement whose fee sets the penalty."""
    scenario = setup_active_placement(**options)
    scenario["clock"] = set_clock(f"{discovered_on}T00:00:00Z")
    case = file_enforcement_case(
        scenario["client"],
        scenario["candidate"],
        discovered_on,
        source_placement=scenario["placement"],
    )
    scenario["case"] = investigate_case(case)
    return scenario


def setup_substantiated_case(discovered_on="2026-10-01", **options) -> dict:
    """Enforcement case in SUBSTANTIATED: the penalty is assessed, the household
    is SUSPENDED and the assessment has been posted to the ledger."""
    scenario = setup_investigating_case(discovered_on, **options)
    scenario["case"] = resolve_case(scenario["case"], "SUBSTANTIATE")
    scenario["client"] = read_client(scenario["client"])
    scenario["requisition"] = read_requisition(scenario["requisition"])
    return scenario


# --- Extra actors ------------------------------------------------------------


def add_vetted_candidate(
    full_name="T. Mercer",
    contact_email="tmercer@mail.example",
    reference_prefix="Selwyn",
    **overrides
) -> dict:
    """A second candidate carried through to a recorded, cleared background
    screen, for tests that need two candidates on one household."""
    candidate = register_candidate(
        full_name=full_name, contact_email=contact_email, **overrides
    )
    first = record_reference(
        candidate,
        principal_employer_name=f"{reference_prefix} Court",
        employment_start_month="2022-01",
        employment_end_month="2022-12",
        contact_email=f"{reference_prefix.lower()}@mail.example",
    )
    second = record_reference(
        candidate,
        prior_reference_id=first["id"],
        principal_employer_name=f"{reference_prefix} Lodge",
        employment_start_month="2023-01",
        employment_end_month="2023-12",
        contact_email=f"{reference_prefix.lower()}2@mail.example",
    )
    verify_reference(first)
    verify_reference(second)
    verification = order_background_verification(
        candidate, provider_reference=f"BV-2411-{reference_prefix[:2].upper()}"
    )
    record_background_result(verification, "CLEARED")
    return read_candidate(candidate)


def add_onboarded_household(
    household_name="Brackenridge Court",
    primary_contact_email="ops@brackenridge.example",
    **overrides
) -> dict:
    """A second household, already COUNTERSIGNED."""
    return create_onboarded_household(
        household_name=household_name,
        primary_contact_email=primary_contact_email,
        **overrides,
    )
