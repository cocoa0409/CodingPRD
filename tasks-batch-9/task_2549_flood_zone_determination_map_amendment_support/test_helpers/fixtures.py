"""Composite setup helpers.

Every pytest test runs against a freshly relaunched server with an empty
database, so nothing here may assume pre-existing rows: each helper builds the
state it needs from scratch using only endpoints the PRD declares.

The default literals mirror the canonical FL chain used by the design indices
(community 125129 / FL, panel 12086C0312K sequence 1 EFFECTIVE with BFE 7.75,
a ROOFTOP property with confidence 0.95, a SINGLE_FAMILY structure at
sfha_offset_ft -12.0 and a folio with principal 28,000,000 cents, escrow
500,000 cents and policy anniversary 2027-03-15), so the pre-computed figures
in the design indices hold exactly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    create_community_payload,
    create_compliance_notice_payload,
    create_determination_payload,
    create_elevation_certificate_payload,
    create_geocode_correction_payload,
    create_lender_payload,
    create_loan_folio_payload,
    create_map_amendment_request_payload,
    create_map_panel_payload,
    create_property_payload,
    create_structure_payload,
)
from .test_users import (
    AGENCY_USER_ID,
    ANALYST_USER_ID,
    REVIEWER_USER_ID,
    make_agency_headers,
    make_analyst_headers,
    make_borrower_headers,
    make_lender_headers,
    make_reviewer_headers,
)

# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(current_utc=DEFAULT_CLOCK_UTC, headers=None):
    """Pin the server's logical clock (PRD 2.4 test-driving capability)."""
    response = api_client.set_clock(
        current_utc, headers=headers or make_analyst_headers()
    )
    get_success_data(response)
    return current_utc


# ---------------------------------------------------------------------------
# Single-entity primitives
# ---------------------------------------------------------------------------


def create_community(**overrides):
    """Register one NFIP community as a ProviderAnalyst."""
    response = api_client.create_community(
        create_community_payload(**overrides), headers=make_analyst_headers()
    )
    return get_success_data(response)


def change_participation(community_id, participation_status, **overrides):
    payload = {"participation_status": participation_status}
    payload.update(overrides)
    response = api_client.change_participation(
        community_id, payload, headers=make_analyst_headers()
    )
    return get_success_data(response)


def create_lender(**overrides):
    """Register one lender / servicer as a ProviderAnalyst."""
    response = api_client.create_lender(
        create_lender_payload(**overrides), headers=make_analyst_headers()
    )
    return get_success_data(response)


def publish_panel(community_id, **overrides):
    """Publish a FIRM panel as an AgencyOfficer.

    A ``revision_sequence`` of 1 is created directly EFFECTIVE (PRD 3.2).
    """
    response = api_client.create_map_panel(
        create_map_panel_payload(community_id, **overrides),
        headers=make_agency_headers(),
    )
    return get_success_data(response)


def create_property(community_id, **overrides):
    response = api_client.create_property(
        create_property_payload(community_id, **overrides),
        headers=make_analyst_headers(),
    )
    return get_success_data(response)


def correct_geocode(property_id, **overrides):
    response = api_client.correct_geocode(
        property_id, create_geocode_correction_payload(**overrides),
        headers=make_analyst_headers(),
    )
    return get_success_data(response)


def create_structure(property_id, **overrides):
    response = api_client.create_structure(
        create_structure_payload(property_id, **overrides),
        headers=make_analyst_headers(),
    )
    return get_success_data(response)


def open_folio(lender_id, property_id, **overrides):
    """Open a life-of-loan folio; the acting Lender must be its own ``lender_id``."""
    response = api_client.create_loan_folio(
        create_loan_folio_payload(lender_id, property_id, **overrides),
        headers=make_lender_headers(lender_id),
    )
    return get_success_data(response)


def read_folio(loan_folio_id, headers=None):
    response = api_client.get_loan_folio(
        loan_folio_id, headers=headers or make_analyst_headers()
    )
    return get_success_data(response)


def folio_version(loan_folio_id):
    """Current ``version`` of the folio, for the PRD 2.6 concurrency guard."""
    return read_folio(loan_folio_id)["version"]


def issue_determination(loan_folio_id, structure_id,
                        determination_type="ORIGINATION",
                        user_id=ANALYST_USER_ID, expected_version=None,
                        **overrides):
    """Issue a determination, reading the folio's live ``version`` first.

    PRD 2.6 makes ``expected_loan_folio_version`` mandatory, and PRD 3.5
    increments the folio's version on every determination write, so the guard
    must be re-read rather than remembered.
    """
    if expected_version is None:
        expected_version = folio_version(loan_folio_id)
    response = api_client.create_determination(
        create_determination_payload(
            loan_folio_id, structure_id, expected_version,
            determination_type=determination_type, **overrides,
        ),
        headers=make_analyst_headers(user_id),
    )
    return get_success_data(response)


def report_insurance(loan_folio_id, lender_id, reported_coverage_cents):
    response = api_client.report_insurance(
        loan_folio_id, {"reported_coverage_cents": reported_coverage_cents},
        headers=make_lender_headers(lender_id),
    )
    return get_success_data(response)


def force_place(loan_folio_id, lender_id):
    response = api_client.force_place(
        loan_folio_id, {}, headers=make_lender_headers(lender_id)
    )
    return get_success_data(response)


def send_notice(loan_folio_id, determination_id, lender_id,
                notice_type="MANDATORY_PURCHASE", **overrides):
    response = api_client.create_compliance_notice(
        create_compliance_notice_payload(
            loan_folio_id, determination_id, notice_type=notice_type, **overrides
        ),
        headers=make_lender_headers(lender_id),
    )
    return get_success_data(response)


def acknowledge_notice(compliance_notice_id, headers):
    response = api_client.acknowledge_compliance_notice(
        compliance_notice_id, {}, headers=headers
    )
    return get_success_data(response)


def run_monitoring(payload=None, headers=None):
    response = api_client.run_monitoring(
        payload if payload is not None else {},
        headers=headers or make_analyst_headers(),
    )
    return get_success_data(response)


def file_certificate(structure_id, headers=None, **overrides):
    """File an elevation certificate; defaults to the analyst-1 filer."""
    response = api_client.create_elevation_certificate(
        create_elevation_certificate_payload(structure_id, **overrides),
        headers=headers or make_analyst_headers(),
    )
    return get_success_data(response)


def review_certificate(elevation_certificate_id, decision="VALIDATED",
                       reviewer_user_id=REVIEWER_USER_ID, **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    response = api_client.review_elevation_certificate(
        elevation_certificate_id, payload,
        headers=make_reviewer_headers(reviewer_user_id),
    )
    return get_success_data(response)


def prepare_amendment(determination_id, elevation_certificate_id,
                      request_type="LOMA", user_id=ANALYST_USER_ID, **overrides):
    response = api_client.create_map_amendment_request(
        create_map_amendment_request_payload(
            determination_id, elevation_certificate_id,
            request_type=request_type, **overrides,
        ),
        headers=make_analyst_headers(user_id),
    )
    return get_success_data(response)


def submit_amendment(map_amendment_request_id, user_id=ANALYST_USER_ID):
    response = api_client.submit_map_amendment_request(
        map_amendment_request_id, {}, headers=make_analyst_headers(user_id)
    )
    return get_success_data(response)


def decide_amendment(map_amendment_request_id, decision, **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    response = api_client.decide_map_amendment_request(
        map_amendment_request_id, payload, headers=make_agency_headers()
    )
    return get_success_data(response)


def file_dispute(determination_id, borrower_user_id, **overrides):
    from .factories import create_dispute_payload

    response = api_client.create_dispute(
        create_dispute_payload(determination_id, **overrides),
        headers=make_borrower_headers(borrower_user_id),
    )
    return get_success_data(response)


def provider_review_dispute(dispute_id, provider_recommendation,
                            reviewer_user_id=REVIEWER_USER_ID):
    response = api_client.provider_review_dispute(
        dispute_id, {"provider_recommendation": provider_recommendation},
        headers=make_reviewer_headers(reviewer_user_id),
    )
    return get_success_data(response)


def agency_review_dispute(dispute_id, agency_concurrence,
                          agency_user_id=AGENCY_USER_ID):
    response = api_client.agency_review_dispute(
        dispute_id, {"agency_concurrence": agency_concurrence},
        headers=make_agency_headers(agency_user_id),
    )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Composite chains
# ---------------------------------------------------------------------------


def setup_base_chain(clock=DEFAULT_CLOCK_UTC, community_overrides=None,
                     lender_overrides=None, panel_overrides=None,
                     property_overrides=None, structure_overrides=None,
                     folio_overrides=None, determination_type="ORIGINATION",
                     analyst_user_id=ANALYST_USER_ID, with_determination=True):
    """Community -> lender -> effective panel -> property -> structure -> folio
    -> determination, all through PRD-declared endpoints.

    Returns a dict keyed ``community``, ``lender``, ``panel``, ``property``,
    ``structure``, ``folio`` and ``determination`` (the last is ``None`` when
    ``with_determination`` is false), plus ready-made ``lender_headers`` and
    ``borrower_headers`` for the folio's own identities.
    """
    set_clock(clock)
    community = create_community(**(community_overrides or {}))
    lender = create_lender(**(lender_overrides or {}))
    panel = publish_panel(community["id"], **(panel_overrides or {}))
    prop = create_property(community["id"], **(property_overrides or {}))
    structure = create_structure(prop["id"], **(structure_overrides or {}))
    folio = open_folio(lender["id"], prop["id"], **(folio_overrides or {}))
    determination = None
    if with_determination:
        determination = issue_determination(
            folio["id"], structure["id"],
            determination_type=determination_type, user_id=analyst_user_id,
            expected_version=folio["version"],
        )
        folio = read_folio(folio["id"])
    return {
        "community": community,
        "lender": lender,
        "panel": panel,
        "property": prop,
        "structure": structure,
        "folio": folio,
        "determination": determination,
        "lender_headers": make_lender_headers(lender["id"]),
        "borrower_headers": make_borrower_headers(folio["borrower_user_id"]),
    }


def setup_folio_with_mandatory_notice(clock=DEFAULT_CLOCK_UTC,
                                      notice_type="MANDATORY_PURCHASE",
                                      notice_overrides=None, **chain_kwargs):
    """Base chain plus one SENT compliance notice citing the current determination."""
    chain = setup_base_chain(clock=clock, **chain_kwargs)
    chain["notice"] = send_notice(
        chain["folio"]["id"], chain["determination"]["id"], chain["lender"]["id"],
        notice_type=notice_type, **(notice_overrides or {}),
    )
    chain["folio"] = read_folio(chain["folio"]["id"])
    return chain


def setup_force_placed_folio(notice_clock=DEFAULT_CLOCK_UTC,
                             placement_clock="2026-09-16T00:00:00Z",
                             **chain_kwargs):
    """Drive a folio all the way to ``insurance_status`` FORCE_PLACED.

    The notice is sent at ``notice_clock`` and the clock is then advanced to
    ``placement_clock``, which must be strictly past the notice's 45-day
    response deadline so the posture reads FORCE_PLACE_ELIGIBLE.
    """
    chain = setup_folio_with_mandatory_notice(clock=notice_clock, **chain_kwargs)
    set_clock(placement_clock)
    chain["folio"] = force_place(chain["folio"]["id"], chain["lender"]["id"])
    return chain


def setup_validated_certificate(clock=DEFAULT_CLOCK_UTC,
                                certificate_overrides=None,
                                filer_headers=None,
                                reviewer_user_id=REVIEWER_USER_ID,
                                **chain_kwargs):
    """Base chain plus an elevation certificate moved SUBMITTED -> VALIDATED."""
    chain = setup_base_chain(clock=clock, **chain_kwargs)
    chain["certificate"] = file_certificate(
        chain["structure"]["id"], headers=filer_headers,
        **(certificate_overrides or {}),
    )
    chain["certificate"] = review_certificate(
        chain["certificate"]["id"], decision="VALIDATED",
        reviewer_user_id=reviewer_user_id,
    )
    chain["structure"] = get_success_data(
        api_client.get_structure(
            chain["structure"]["id"], headers=make_analyst_headers()
        )
    )
    return chain


def setup_amendment_draft(request_type="LOMA", structure_overrides=None,
                          amendment_overrides=None, **chain_kwargs):
    """Validated certificate plus a DRAFT amendment package over it.

    ``fill_placed_flag`` is set to match ``request_type`` so the PRD 3.8 type
    check cannot be what fails.
    """
    overrides = dict(structure_overrides or {})
    overrides.setdefault("fill_placed_flag", request_type == "LOMR_F")
    chain = setup_validated_certificate(
        structure_overrides=overrides, **chain_kwargs
    )
    chain["amendment"] = prepare_amendment(
        chain["determination"]["id"], chain["certificate"]["id"],
        request_type=request_type, **(amendment_overrides or {}),
    )
    return chain


def setup_amendment_submitted(request_type="LOMA", **kwargs):
    """A DRAFT package moved DRAFT -> SUBMITTED_TO_AGENCY."""
    chain = setup_amendment_draft(request_type=request_type, **kwargs)
    chain["amendment"] = submit_amendment(chain["amendment"]["id"])
    return chain


def setup_amendment_additional_data_requested(request_type="LOMA", **kwargs):
    """A submitted package returned to ADDITIONAL_DATA_REQUESTED by the agency."""
    chain = setup_amendment_submitted(request_type=request_type, **kwargs)
    chain["amendment"] = decide_amendment(
        chain["amendment"]["id"], "ADDITIONAL_DATA_REQUESTED",
        additional_data_note="Provide the signed FEMA form section C.",
    )
    return chain


def setup_dispute_submitted(dispute_overrides=None, **chain_kwargs):
    """Base chain plus a dispute in its initial state SUBMITTED."""
    chain = setup_base_chain(**chain_kwargs)
    chain["dispute"] = file_dispute(
        chain["determination"]["id"], chain["folio"]["borrower_user_id"],
        **(dispute_overrides or {}),
    )
    return chain


def setup_dispute_in_joint_review(provider_recommendation="REVISE",
                                  reviewer_user_id=REVIEWER_USER_ID, **kwargs):
    """A dispute moved SUBMITTED -> JOINT_AGENCY_REVIEW."""
    chain = setup_dispute_submitted(**kwargs)
    chain["dispute"] = provider_review_dispute(
        chain["dispute"]["id"], provider_recommendation,
        reviewer_user_id=reviewer_user_id,
    )
    return chain


def walk_panel_to_lfd_issued(map_panel_id,
                             appeal_period_end_date="2026-10-30T00:00:00Z",
                             decision_clock="2026-10-30T00:00:00Z"):
    """Walk a PRELIMINARY panel PRELIMINARY -> APPEAL_OPEN -> LFD_ISSUED.

    The appeal decision is only available once the posted window has closed, so
    the clock is moved to ``decision_clock`` first (PRD 3.2).
    """
    get_success_data(api_client.open_appeal_period(
        map_panel_id, {"appeal_period_end_date": appeal_period_end_date},
        headers=make_agency_headers(),
    ))
    set_clock(decision_clock, headers=make_agency_headers())
    return get_success_data(api_client.record_appeal_decision(
        map_panel_id, {"outcome": "LFD_ISSUED"}, headers=make_agency_headers()
    ))


def publish_successor_panel(community_id, predecessor,
                            effective_date="2027-04-28T00:00:00Z", **overrides):
    """Publish the sequence-2 successor of ``predecessor`` and walk it to LFD_ISSUED."""
    payload = {
        "revision_sequence": predecessor["revision_sequence"] + 1,
        "supersedes_panel_id": predecessor["id"],
        "effective_date": effective_date,
        "map_panel_number": predecessor["map_panel_number"],
        "zone_code": "VE",
        "base_flood_elevation_ft": 12.50,
        "study_case_number": "26-04-1234P",
    }
    payload.update(overrides)
    return publish_panel(community_id, **payload)


def setup_successor_panel_ready_for_effective(
        effective_date="2027-04-28T00:00:00Z",
        successor_overrides=None,
        appeal_period_end_date="2026-10-30T00:00:00Z",
        decision_clock="2026-10-30T00:00:00Z",
        effective_clock="2027-05-01T00:00:00Z",
        **chain_kwargs):
    """Base chain plus a sequence-2 successor panel sitting in LFD_ISSUED with
    both the appeal window and the 180-day LFD wait already elapsed."""
    chain = setup_base_chain(**chain_kwargs)
    chain["successor"] = publish_successor_panel(
        chain["community"]["id"], chain["panel"],
        effective_date=effective_date, **(successor_overrides or {}),
    )
    chain["successor"] = walk_panel_to_lfd_issued(
        chain["successor"]["id"],
        appeal_period_end_date=appeal_period_end_date,
        decision_clock=decision_clock,
    )
    set_clock(effective_clock, headers=make_agency_headers())
    return chain
