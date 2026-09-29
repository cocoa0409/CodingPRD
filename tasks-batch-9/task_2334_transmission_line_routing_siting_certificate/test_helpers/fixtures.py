"""Composite setup helpers.

The API harness restarts the server before every individual test, so each test
starts against an empty database.  Every precondition therefore has to be built
from scratch through the PRD-declared endpoints, and these helpers encapsulate
the long canonical chains so the tests themselves stay readable.

All helpers take the :class:`~test_helpers.api_client.ApiClient` as their first
argument and thread a mutable ``ctx`` dictionary of captured identifiers.  They
use :func:`get_success_data` so a broken setup step fails loudly with the
server's own error identifier.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    COMMISSION_STAFF_HEADERS,
    COMPLIANCE_MONITOR_HEADERS,
    DEVELOPER_CERTIFIER_HEADERS,
    DEVELOPER_FILER_HEADERS,
    DEVELOPER_HEADERS,
    FEDERAL_PERMIT_OFFICER_HEADERS,
    HEARING_EXAMINER_HEADERS,
    ROUTE_ANALYST_HEADERS,
    make_landowner_headers,
)

# ===========================================================================
# Tier 1 — primitives
# ===========================================================================


def set_clock(api, instant, headers=None):
    """Drive the logical clock. Available to all roles; returns 200 and no payload."""
    response = api.set_clock(instant, headers or DEVELOPER_HEADERS)
    assert response.status_code == 200, (
        f"Setting the logical clock to {instant} should return 200, "
        f"got {response.status_code}: {response.text}"
    )
    return response


def reset_clock(api):
    """Put the logical clock back to the reading it has before anyone sets it."""
    set_clock(api, DEFAULT_CLOCK_UTC)
    return DEFAULT_CLOCK_UTC


def create_project(api, ctx=None, key="proj", **overrides):
    """Create a project (default: the KV_345 Harlan-Boone rebuild)."""
    data = get_success_data(api.create_project(f.project_payload(**overrides), DEVELOPER_HEADERS))
    if ctx is not None:
        ctx[key] = data["id"]
    return data


def create_landowner(api, ctx=None, key="lo1", **overrides):
    data = get_success_data(
        api.create_landowner(f.landowner_payload(**overrides), DEVELOPER_HEADERS)
    )
    if ctx is not None:
        ctx[key] = data["id"]
    return data


def fund_escrow(api, ctx, amount_cents=600_000_000, reference="ESCROW-1"):
    return get_success_data(
        api.create_escrow_deposit(
            ctx["proj"],
            f.escrow_deposit_payload(amount_cents=amount_cents, reference=reference),
            DEVELOPER_HEADERS,
        )
    )


def read_project(api, ctx, key="proj", headers=None):
    return get_success_data(api.get_project(ctx[key], headers or DEVELOPER_HEADERS))


def read_route(api, route_id, headers=None):
    return get_success_data(api.get_route(route_id, headers or ROUTE_ANALYST_HEADERS))


def read_segment(api, segment_id, headers=None):
    return get_success_data(api.get_route_segment(segment_id, headers or ROUTE_ANALYST_HEADERS))


def read_application(api, application_id, headers=None):
    return get_success_data(api.get_application(application_id, headers or COMMISSION_STAFF_HEADERS))


def read_certificate(api, certificate_id, headers=None):
    return get_success_data(api.get_certificate(certificate_id, headers or COMMISSION_STAFF_HEADERS))


def read_condition(api, condition_id, headers=None):
    return get_success_data(
        api.get_certificate_condition(condition_id, headers or COMMISSION_STAFF_HEADERS)
    )


def read_tract(api, tract_id, headers=None):
    return get_success_data(api.get_easement_tract(tract_id, headers or DEVELOPER_HEADERS))


def read_activity(api, activity_id, headers=None):
    return get_success_data(
        api.get_construction_activity(activity_id, headers or DEVELOPER_HEADERS)
    )


def read_finding(api, finding_id, headers=None):
    return get_success_data(
        api.get_nonconformance(finding_id, headers or COMPLIANCE_MONITOR_HEADERS)
    )


def read_study(api, study_id, headers=None):
    return get_success_data(api.get_planning_study(study_id, headers or DEVELOPER_HEADERS))


def read_alternative(api, alternative_id, headers=None):
    return get_success_data(api.get_alternative(alternative_id, headers or DEVELOPER_HEADERS))


def read_intervention(api, intervention_id, headers=None):
    return get_success_data(
        api.get_intervention(intervention_id, headers or COMMISSION_STAFF_HEADERS)
    )


def read_session(api, session_id, headers=None):
    return get_success_data(
        api.get_hearing_session(session_id, headers or HEARING_EXAMINER_HEADERS)
    )


# ===========================================================================
# Tier 2 — the need case
# ===========================================================================


def build_need_case(api, ctx=None):
    """Project + DRAFT study + one TRANSMISSION and one NON_TRANSMISSION alternative.

    The non-wires portfolio levelizes to 230000000.00 cents/MW against the
    transmission solution's 200000000.00, which is exactly the 1.1500 need
    margin the PRD sets as its certification threshold.
    """
    ctx = {} if ctx is None else ctx
    create_project(api, ctx)
    study = get_success_data(
        api.create_planning_study(f.planning_study_payload(ctx["proj"]), DEVELOPER_HEADERS)
    )
    ctx["study"] = study["id"]
    alt1 = get_success_data(
        api.create_alternative(
            f.alternative_payload(
                ctx["study"],
                kind="TRANSMISSION",
                description="New 345kV single-circuit line",
                capex_cents=80_000_000_000,
                deliverable_mw=400,
            ),
            ROUTE_ANALYST_HEADERS,
        )
    )
    ctx["alt1"] = alt1["id"]
    alt2 = get_success_data(
        api.create_alternative(
            f.alternative_payload(
                ctx["study"],
                kind="NON_TRANSMISSION",
                description="Battery storage plus demand response portfolio",
                capex_cents=46_000_000_000,
                deliverable_mw=200,
            ),
            ROUTE_ANALYST_HEADERS,
        )
    )
    ctx["alt2"] = alt2["id"]
    return ctx


def screen_in_both_alternatives(api, ctx):
    get_success_data(
        api.screen_alternative(
            ctx["alt1"],
            f.screening_payload(screen_reason="Meets deficit in full"),
            ROUTE_ANALYST_HEADERS,
        )
    )
    get_success_data(
        api.screen_alternative(
            ctx["alt2"],
            f.screening_payload(screen_reason="Credible non-wires portfolio"),
            ROUTE_ANALYST_HEADERS,
        )
    )
    return ctx


def certify_study(api, ctx, headers=None):
    """Sufficiency certification by a developer other than the study's author."""
    return get_success_data(
        api.certify_study_sufficiency(
            ctx["study"],
            f.sufficiency_certification_payload(),
            headers or DEVELOPER_CERTIFIER_HEADERS,
        )
    )


def build_certified_study(api, ctx=None):
    """Need case screened and certified: the study reaches CERTIFIED_SUFFICIENT."""
    ctx = build_need_case(api, ctx)
    screen_in_both_alternatives(api, ctx)
    certify_study(api, ctx)
    return ctx


# ===========================================================================
# Tier 2 — corridors
# ===========================================================================

#: Route A's three segments. Segment 1 crosses sensitive habitat, segment 2
#: crosses navigable water and therefore needs a federal permit, segment 3 is
#: only a desk study.
ROUTE_A_SEGMENTS = (
    dict(
        sequence_index=1,
        miles=10.0,
        land_use_rating=3,
        environmental_rating=4,
        cultural_rating=2,
        engineering_rating=3,
        county="Harlan",
        crew_capacity=12,
        survey_status="FIELD_VERIFIED",
        habitat_blackout=True,
        federal_crossing_kind="NONE",
    ),
    dict(
        sequence_index=2,
        miles=6.0,
        land_use_rating=2,
        environmental_rating=2,
        cultural_rating=1,
        engineering_rating=4,
        county="Boone",
        crew_capacity=12,
        survey_status="FIELD_VERIFIED",
        habitat_blackout=False,
        federal_crossing_kind="NAVIGABLE_WATERWAY",
    ),
    dict(
        sequence_index=3,
        miles=4.0,
        land_use_rating=4,
        environmental_rating=5,
        cultural_rating=3,
        engineering_rating=2,
        county="Clay",
        crew_capacity=12,
        survey_status="DESKTOP",
        habitat_blackout=False,
        federal_crossing_kind="NONE",
    ),
)

ROUTE_B_SEGMENTS = (
    dict(
        sequence_index=1,
        miles=8.0,
        land_use_rating=2,
        environmental_rating=1,
        cultural_rating=1,
        engineering_rating=2,
        county="Boone",
        crew_capacity=12,
        survey_status="FIELD_VERIFIED",
        habitat_blackout=False,
        federal_crossing_kind="NONE",
    ),
    dict(
        sequence_index=2,
        miles=4.0,
        land_use_rating=1,
        environmental_rating=1,
        cultural_rating=1,
        engineering_rating=1,
        county="Clay",
        crew_capacity=12,
        survey_status="FIELD_VERIFIED",
        habitat_blackout=False,
        federal_crossing_kind="NONE",
    ),
)


def create_route(api, ctx, key="routeA", label="Route A - river crossing", kind="PROPOSED",
                 project_key="proj"):
    data = get_success_data(
        api.create_route(
            f.route_payload(ctx[project_key], label=label, kind=kind), ROUTE_ANALYST_HEADERS
        )
    )
    ctx[key] = data["id"]
    return data


def add_segment(api, ctx, route_key, seg_key, **spec):
    data = get_success_data(
        api.create_route_segment(
            f.route_segment_payload(ctx[route_key], **spec), ROUTE_ANALYST_HEADERS
        )
    )
    ctx[seg_key] = data["id"]
    return data


def run_mapping(api, ctx, route_key="routeA", note="Desk study plus one field-verified segment"):
    return get_success_data(
        api.run_constraint_mapping(
            ctx[route_key], f.constraint_mapping_payload(mapping_note=note), ROUTE_ANALYST_HEADERS
        )
    )


def build_route_a(api, ctx, seg1_survey="FIELD_VERIFIED", map_it=True):
    """Route A with its three segments, optionally constraint-mapped.

    With segment 1 field-verified the certified score is 69.58 and the density
    3.48; with segment 1 left at DESKTOP the certified score is 82.23 and the
    density 4.11, which is above the 4.00 nomination gate.
    """
    create_route(api, ctx, "routeA", "Route A - river crossing", "PROPOSED")
    for index, spec in enumerate(ROUTE_A_SEGMENTS, start=1):
        spec = dict(spec)
        if index == 1:
            spec["survey_status"] = seg1_survey
        add_segment(api, ctx, "routeA", f"seg{index}", **spec)
    if map_it:
        run_mapping(api, ctx, "routeA")
    return ctx


def build_route_b(api, ctx, nominate=True):
    """Alternate Route B, fully field-verified, mapped and nominated."""
    create_route(api, ctx, "routeB", "Route B - ridge line", "ALTERNATE")
    for index, spec in enumerate(ROUTE_B_SEGMENTS, start=1):
        add_segment(api, ctx, "routeB", f"segB{index}", **dict(spec))
    run_mapping(api, ctx, "routeB", note="Alternate fully field verified")
    if nominate:
        get_success_data(
            api.nominate_route(
                ctx["routeB"],
                f.nomination_payload(nomination_note="Alternate route for the filing"),
                DEVELOPER_HEADERS,
            )
        )
    return ctx


def publish_route_a(api, ctx, comment_window_days=30):
    return get_success_data(
        api.publish_route(
            ctx["routeA"],
            f.publication_payload(comment_window_days=comment_window_days),
            DEVELOPER_HEADERS,
        )
    )


def record_two_open_houses(api, ctx, route_key="routeA"):
    get_success_data(
        api.record_open_house(
            ctx[route_key], f.open_house_payload(county="Harlan", attendee_count=40),
            DEVELOPER_HEADERS,
        )
    )
    get_success_data(
        api.record_open_house(
            ctx[route_key], f.open_house_payload(county="Boone", attendee_count=25),
            DEVELOPER_HEADERS,
        )
    )


def nominate_route(api, ctx, route_key="routeA", note=None):
    return get_success_data(
        api.nominate_route(
            ctx[route_key],
            f.nomination_payload(
                nomination_note=note or "Comment window closed with no open material comments"
            ),
            DEVELOPER_HEADERS,
        )
    )


def setup_mapped_routes(api, ctx=None, seg1_survey="FIELD_VERIFIED"):
    """Certified study, mapped Route A and a nominated alternate Route B."""
    ctx = build_certified_study(api, ctx)
    build_route_a(api, ctx, seg1_survey=seg1_survey)
    build_route_b(api, ctx)
    return ctx


def setup_published_route(api, ctx=None, seg1_survey="FIELD_VERIFIED",
                          comment_window_days=30, open_houses=True):
    """Route A published for comment with two open houses in two counties."""
    ctx = setup_mapped_routes(api, ctx, seg1_survey=seg1_survey)
    publish_route_a(api, ctx, comment_window_days=comment_window_days)
    if open_houses:
        record_two_open_houses(api, ctx)
    return ctx


def setup_nominated_routes(api, ctx=None, seg1_survey="FIELD_VERIFIED"):
    """Both corridors NOMINATED, with the comment window closed at 2026-08-31."""
    ctx = setup_published_route(api, ctx, seg1_survey=seg1_survey)
    set_clock(api, "2026-08-31T00:00:00Z")
    nominate_route(api, ctx, "routeA")
    return ctx


# ===========================================================================
# Tier 3 — the docket
# ===========================================================================


def file_application(api, ctx, docket_number="EL-2026-0334", filing_fee_cents=2_500_000):
    """File the siting application as a developer who did not author the study."""
    data = get_success_data(
        api.create_application(
            f.application_payload(
                ctx["proj"],
                ctx["study"],
                ctx["routeA"],
                docket_number=docket_number,
                filing_fee_cents=filing_fee_cents,
            ),
            DEVELOPER_FILER_HEADERS,
        )
    )
    ctx["app"] = data["id"]
    ctx["app_version"] = data["version"]
    return data


def review_application(api, ctx, outcome="ACCEPT", deficiency_note=None):
    payload = f.sufficiency_review_payload(outcome=outcome)
    if deficiency_note is not None:
        payload["deficiency_note"] = deficiency_note
    data = get_success_data(
        api.review_application_sufficiency(ctx["app"], payload, COMMISSION_STAFF_HEADERS)
    )
    ctx["app_version"] = data["version"]
    return data


def amend_application(api, ctx, summary="Alternate route impact assessment added"):
    data = get_success_data(
        api.amend_application(
            ctx["app"],
            f.amendment_payload(ctx["app_version"], amendment_summary=summary),
            DEVELOPER_FILER_HEADERS,
        )
    )
    ctx["app_version"] = data["version"]
    return data


def schedule_session(api, ctx, key="sess1", kind="EVIDENTIARY",
                     window_start_at="2026-10-05T09:00:00Z",
                     window_end_at="2026-10-05T12:00:00Z", headers=None):
    data = get_success_data(
        api.create_hearing_session(
            f.hearing_session_payload(
                ctx["app"], kind=kind, window_start_at=window_start_at,
                window_end_at=window_end_at,
            ),
            headers or HEARING_EXAMINER_HEADERS,
        )
    )
    ctx[key] = data["id"]
    return data


def hold_session(api, ctx, key="sess1", exhibits_admitted_count=12, headers=None):
    return get_success_data(
        api.hold_hearing_session(
            ctx[key],
            f.holding_payload(exhibits_admitted_count=exhibits_admitted_count),
            headers or HEARING_EXAMINER_HEADERS,
        )
    )


def close_record(api, ctx, headers=None):
    data = get_success_data(
        api.close_record(ctx["app"], f.record_closure_payload(), headers or HEARING_EXAMINER_HEADERS)
    )
    ctx["app_version"] = data["version"]
    return data


def petition_to_intervene(api, ctx, key, landowner_key="lo1", grounds=None):
    """A landowner petition, filed by the landowner it names."""
    data = get_success_data(
        api.create_intervention(
            f.intervention_payload(
                ctx["app"],
                petitioner_kind="LANDOWNER",
                grounds=grounds or "Crossing severs the home pasture",
                landowner_id=ctx[landowner_key],
            ),
            make_landowner_headers(ctx[landowner_key]),
        )
    )
    ctx[key] = data["id"]
    return data


def rule_on_petition(api, ctx, key, ruling="GRANT", reason="Direct property interest shown"):
    return get_success_data(
        api.rule_on_intervention(
            ctx[key],
            f.intervention_ruling_payload(ruling=ruling, ruling_reason=reason),
            COMMISSION_STAFF_HEADERS,
        )
    )


def setup_filed_application(api, ctx=None, seg1_survey="FIELD_VERIFIED",
                            docket_number="EL-2026-0334", filing_fee_cents=2_500_000):
    """Application FILED at 2026-08-31, so its decision deadline is 2027-08-31."""
    ctx = setup_nominated_routes(api, ctx, seg1_survey=seg1_survey)
    file_application(api, ctx, docket_number=docket_number, filing_fee_cents=filing_fee_cents)
    return ctx


def setup_accepted_application(api, ctx=None, seg1_survey="FIELD_VERIFIED"):
    """Application ACCEPTED with its record dimension at SCHEDULING."""
    ctx = setup_filed_application(api, ctx, seg1_survey=seg1_survey)
    review_application(api, ctx, outcome="ACCEPT")
    return ctx


def setup_closed_record(api, ctx=None, seg1_survey="FIELD_VERIFIED"):
    """Application ACCEPTED and the evidentiary record RECORD_CLOSED.

    Leaves the logical clock at 2026-10-05T09:00:00Z, the instant the
    evidentiary session opened.
    """
    ctx = setup_accepted_application(api, ctx, seg1_survey=seg1_survey)
    schedule_session(api, ctx)
    set_clock(api, "2026-10-05T09:00:00Z", HEARING_EXAMINER_HEADERS)
    hold_session(api, ctx)
    close_record(api, ctx)
    return ctx


# ===========================================================================
# Tier 3 — the order and the certificate
# ===========================================================================


def record_decision(api, ctx, **overrides):
    overrides.setdefault("certified_route_id", ctx["routeA"])
    return get_success_data(
        api.record_decision(ctx["app"], f.decision_payload(**overrides), COMMISSION_STAFF_HEADERS)
    )


def capture_certificate(api, ctx, cert_key="cert", condition_prefix="cond",
                        application_key="app"):
    """Read back the minted certificate and its conditions in the order imposed."""
    certificates, _ = _paginated(
        api.list_certificates(
            COMMISSION_STAFF_HEADERS, {"application_id": ctx[application_key]}
        )
    )
    assert certificates, "The granting order must mint a certificate"
    ctx[cert_key] = certificates[0]["id"]
    conditions, _ = _paginated(
        api.list_certificate_conditions_of_certificate(ctx[cert_key], COMMISSION_STAFF_HEADERS)
    )
    for index, condition in enumerate(conditions, start=1):
        ctx[f"{condition_prefix}{index}"] = condition["id"]
    return ctx[cert_key]


def _paginated(response):
    body = get_success_data(response)
    meta = response.json()["meta"]
    return body, meta


def setup_issued_certificate(api, ctx=None, seg1_survey="FIELD_VERIFIED", **decision_overrides):
    """The full arc to an ISSUED/ACTIVE certificate with three conditions.

    The order carries mitigation_base_cents 480000000 — TIER_1 — and conditions
    of severity_weight 4, 2 and 4, so escrow_required_cents is 533000000.  The
    logical clock is left at 2026-10-05T09:00:00Z.
    """
    ctx = setup_closed_record(api, ctx, seg1_survey=seg1_survey)
    record_decision(api, ctx, **decision_overrides)
    capture_certificate(api, ctx)
    return ctx


# ===========================================================================
# Tier 4 — easement acquisition
# ===========================================================================


def create_tract(api, ctx, key="tract1", segment_key="seg1", landowner_key="lo1", **overrides):
    data = get_success_data(
        api.create_easement_tract(
            f.easement_tract_payload(
                ctx["proj"], ctx[segment_key], ctx[landowner_key], **overrides
            ),
            DEVELOPER_HEADERS,
        )
    )
    ctx[key] = data["id"]
    ctx[f"{key}_version"] = data["version"]
    return data


def extend_offer(api, ctx, key="tract1", note="Initial appraisal-based offer"):
    """Extend an offer at the tract's current version, then record the new version."""
    data = get_success_data(
        api.create_offer(
            ctx[key],
            f.offer_payload(ctx[f"{key}_version"], offer_note=note),
            DEVELOPER_HEADERS,
        )
    )
    ctx[f"{key}_version"] = data["version"]
    return data


def respond_to_offer(api, ctx, key="tract1", response="ACCEPT", note="Terms accepted",
                     landowner_key="lo1"):
    """The tract's own landowner answers — the ownership check demands it."""
    data = get_success_data(
        api.respond_to_offer(
            ctx[key],
            f.offer_response_payload(response=response, response_note=note),
            make_landowner_headers(ctx[landowner_key]),
        )
    )
    ctx[f"{key}_version"] = data["version"]
    return data


def setup_agreed_tract(api, ctx, key="tract1", landowner_key="lo1", segment_key="seg1",
                       **tract_overrides):
    """One tract on segment 1, offered once and accepted, so it sits at AGREED.

    On the canonical tract — 12.35 acres at 487500 cents an acre, easement
    factor 0.65 plus 250000 cents of structure damages — the first offer is
    4163406 cents.
    """
    if landowner_key not in ctx:
        create_landowner(api, ctx, landowner_key)
    create_tract(api, ctx, key=key, segment_key=segment_key, landowner_key=landowner_key,
                 **tract_overrides)
    extend_offer(api, ctx, key)
    respond_to_offer(api, ctx, key, response="ACCEPT", landowner_key=landowner_key)
    return ctx


def setup_rejected_tract(api, ctx, key="tract1", landowner_key="lo1", rounds=1,
                         **tract_overrides):
    """A tract whose offers have all been rejected, leaving it at REJECTED."""
    if landowner_key not in ctx:
        create_landowner(api, ctx, landowner_key)
    create_tract(api, ctx, key=key, landowner_key=landowner_key, **tract_overrides)
    for round_number in range(rounds):
        extend_offer(
            api, ctx, key,
            note="Initial appraisal-based offer" if round_number == 0 else "Sweetened offer",
        )
        respond_to_offer(
            api, ctx, key, response="REJECT", note="Below market", landowner_key=landowner_key
        )
    return ctx


def file_condemnation(api, ctx, key="tract1", court_docket_number="CC-2027-77",
                      deposit_cents=5_000_000):
    data = get_success_data(
        api.file_condemnation(
            ctx[key],
            f.condemnation_payload(
                court_docket_number=court_docket_number, deposit_cents=deposit_cents
            ),
            DEVELOPER_HEADERS,
        )
    )
    ctx[f"{key}_version"] = data["version"]
    return data


def record_award(api, ctx, key="tract1"):
    data = get_success_data(
        api.record_award(ctx[key], f.award_payload(), COMMISSION_STAFF_HEADERS)
    )
    ctx[f"{key}_version"] = data["version"]
    return data


def pay_tract(api, ctx, key="tract1", payment_reference="WIRE-1"):
    data = get_success_data(
        api.create_payment(
            ctx[key], f.payment_payload(payment_reference=payment_reference), DEVELOPER_HEADERS
        )
    )
    ctx[f"{key}_version"] = data["version"]
    return data


def rescind_payment(api, ctx, key="tract1"):
    data = get_success_data(
        api.rescind_payment(ctx[key], f.rescission_payload(), COMMISSION_STAFF_HEADERS)
    )
    ctx[f"{key}_version"] = data["version"]
    return data


def setup_paid_tract(api, ctx, escrow_cents=600_000_000):
    """Escrow funded, the canonical tract AGREED at 4163406 cents and PAID."""
    setup_agreed_tract(api, ctx)
    fund_escrow(api, ctx, amount_cents=escrow_cents)
    pay_tract(api, ctx)
    return ctx


# ===========================================================================
# Tier 4 — construction
# ===========================================================================


def schedule_activity(api, ctx, key="act1", segment_key="seg1", **overrides):
    data = get_success_data(
        api.create_construction_activity(
            f.construction_activity_payload(ctx["cert"], ctx[segment_key], **overrides),
            DEVELOPER_HEADERS,
        )
    )
    ctx[key] = data["id"]
    return data


def start_activity(api, ctx, key="act1", note="Crew mobilized"):
    return get_success_data(
        api.start_activity(ctx[key], f.activity_start_payload(start_note=note), DEVELOPER_HEADERS)
    )


def complete_activity(api, ctx, key="act1"):
    return get_success_data(
        api.complete_activity(ctx[key], f.activity_completion_payload(), DEVELOPER_HEADERS)
    )


def cancel_activity(api, ctx, key="act1"):
    return get_success_data(
        api.cancel_activity(ctx[key], f.activity_cancellation_payload(), DEVELOPER_HEADERS)
    )


def setup_started_activity(api, ctx, key="act1", crew_count=6, activity_kind="CLEARING",
                           window_start_at="2027-08-02T00:00:00Z",
                           window_end_at="2027-08-12T00:00:00Z"):
    """A CLEARING activity on segment 1, started, so the segment is ACTIVE.

    Requires an AGREED tract on the segment and escrow funded at or above the
    certificate's requirement; :func:`setup_construction_ready` arranges both.
    """
    schedule_activity(
        api, ctx, key=key, crew_count=crew_count, activity_kind=activity_kind,
        window_start_at=window_start_at, window_end_at=window_end_at,
    )
    set_clock(api, window_start_at)
    start_activity(api, ctx, key)
    return ctx


def setup_construction_ready(api, ctx=None, escrow_cents=600_000_000):
    """Certificate ISSUED/ACTIVE, tract 1 AGREED on segment 1 and escrow funded.

    Everything a start on segment 1 needs: segment 1's crossing kind is NONE so
    its federal permit status is NOT_REQUIRED, its only tract is AGREED, and
    escrow_funded_cents 600000000 clears the certificate's 533000000
    requirement.
    """
    ctx = setup_issued_certificate(api, ctx)
    setup_agreed_tract(api, ctx)
    fund_escrow(api, ctx, amount_cents=escrow_cents)
    return ctx


def file_finding(api, ctx, key="ncr1", condition_key="cond1", severity="SEVERE",
                 observation="Clearing inside the seasonal habitat blackout", **overrides):
    payload = f.nonconformance_payload(
        ctx["cert"], ctx[condition_key], severity=severity, observation=observation, **overrides
    )
    data = get_success_data(api.create_nonconformance(payload, COMPLIANCE_MONITOR_HEADERS))
    ctx[key] = data["id"]
    return data


def correct_finding(api, ctx, key="ncr1", note="Restoration complete"):
    return get_success_data(
        api.correct_nonconformance(
            ctx[key], f.correction_payload(corrective_action=note), COMPLIANCE_MONITOR_HEADERS
        )
    )


def void_finding(api, ctx, key="ncr1"):
    return get_success_data(
        api.correct_nonconformance(ctx[key], f.void_payload(), COMMISSION_STAFF_HEADERS)
    )


def setup_stop_work_certificate(api, ctx=None):
    """One SEVERE finding on the weight-4 blackout condition drives STOP_WORK.

    The finding deducts 48.00 points, so both indices fall to 52.00 — below the
    60.00 rolling floor but above the 25.00 cumulative floor.
    """
    ctx = setup_issued_certificate(api, ctx) if ctx is None or "cert" not in ctx else ctx
    file_finding(api, ctx, key="ncr_sev", condition_key="cond1", severity="SEVERE")
    return ctx


def setup_revoked_certificate(api, ctx=None):
    """Two SEVERE findings on weight-4 conditions drive the cumulative index to 4.00."""
    ctx = setup_issued_certificate(api, ctx) if ctx is None or "cert" not in ctx else ctx
    file_finding(api, ctx, key="ncr_sev1", condition_key="cond1", severity="SEVERE")
    file_finding(
        api, ctx, key="ncr_sev2", condition_key="cond3", severity="SEVERE",
        observation="Crew count far above the certificate crew limit",
    )
    return ctx


# ===========================================================================
# Tier 5 — multi-docket and cross-project scenarios
# ===========================================================================


def build_unrelated_project(api, ctx, key="proj_other"):
    """A second, unrelated project used for cross-family belonging checks."""
    return create_project(
        api, ctx, key=key,
        name="Wolfe County 138kV Loop",
        voltage_class="KV_138",
        jurisdiction_state="KY",
        target_energization_at="2029-04-01T00:00:00Z",
    )


#: Two field-verified segments rated 1/1/1/1 — a corridor whose density is 1.00
#: on any voltage class, so it always clears the 4.00 nomination gate.
PLAIN_SEGMENTS = (
    dict(
        sequence_index=1, miles=6.0, land_use_rating=1, environmental_rating=1,
        cultural_rating=1, engineering_rating=1, county="Boone", crew_capacity=12,
        survey_status="FIELD_VERIFIED", habitat_blackout=False, federal_crossing_kind="NONE",
    ),
    dict(
        sequence_index=2, miles=4.0, land_use_rating=1, environmental_rating=1,
        cultural_rating=1, engineering_rating=1, county="Clay", crew_capacity=12,
        survey_status="FIELD_VERIFIED", habitat_blackout=False, federal_crossing_kind="NONE",
    ),
)


def build_plain_route(api, ctx, project_key, route_key, label, kind="PROPOSED",
                      seg_prefix=None, segments=PLAIN_SEGMENTS):
    """A mapped two-segment corridor whose certified density is 1.00."""
    create_route(api, ctx, key=route_key, label=label, kind=kind, project_key=project_key)
    prefix = seg_prefix or f"{route_key}_seg"
    for index, spec in enumerate(segments, start=1):
        add_segment(api, ctx, route_key, f"{prefix}{index}", **dict(spec))
    run_mapping(api, ctx, route_key, note="Fully field verified corridor")
    return ctx


def nominate_plain_proposed_route(api, ctx, route_key, publish_at, window_days=30,
                                   close_at=None, counties=("Boone", "Clay")):
    """Publish, hold two open houses, close the window and nominate a corridor."""
    set_clock(api, publish_at)
    get_success_data(
        api.publish_route(
            ctx[route_key], f.publication_payload(comment_window_days=window_days),
            DEVELOPER_HEADERS,
        )
    )
    for county, attendees in zip(counties, (30, 20)):
        get_success_data(
            api.record_open_house(
                ctx[route_key], f.open_house_payload(county=county, attendee_count=attendees),
                DEVELOPER_HEADERS,
            )
        )
    assert close_at is not None, "The caller must supply the window close instant"
    set_clock(api, close_at)
    nominate_route(api, ctx, route_key, note="Second docket corridor nominated")
    return ctx


def setup_second_project_nominated_route(api, ctx):
    """A second project carrying its own NOMINATED proposed corridor.

    The second project has no certified study of its own, so it stays in
    ``PLANNING`` while its corridor is drawn, mapped and nominated.  That makes
    it the right vehicle for an application that names this project but a study
    belonging to the first one.
    """
    build_unrelated_project(api, ctx, key="proj_other")
    build_plain_route(api, ctx, "proj_other", "routeO", "Route O - Wolfe loop", "PROPOSED")
    nominate_plain_proposed_route(
        api, ctx, "routeO", publish_at="2026-08-31T00:00:00Z", window_days=30,
        close_at="2026-09-30T00:00:00Z",
    )
    return ctx


def setup_second_certificate(api, ctx):
    """A whole second docket, ending in its own ISSUED certificate.

    Built on a KV_138 project with its own certified study, its own proposed and
    alternate corridors, its own hearing session and its own order carrying a
    single weight-2 monitoring condition.  Used where a rule has to be shown to
    be scoped to one certificate rather than to the database.
    """
    build_unrelated_project(api, ctx, key="proj2")
    study2 = get_success_data(
        api.create_planning_study(
            f.planning_study_payload(
                ctx["proj2"], horizon_year=2033, reliability_deficit_mw=200,
                transmission_capex_cents=40_000_000_000, benefit_pv_cents=40_000_000_000,
            ),
            DEVELOPER_HEADERS,
        )
    )
    ctx["study2"] = study2["id"]
    alt_t2 = get_success_data(
        api.create_alternative(
            f.alternative_payload(
                ctx["study2"], kind="TRANSMISSION", description="New 138kV loop",
                capex_cents=40_000_000_000, deliverable_mw=200,
            ),
            ROUTE_ANALYST_HEADERS,
        )
    )
    alt_n2 = get_success_data(
        api.create_alternative(
            f.alternative_payload(
                ctx["study2"], kind="NON_TRANSMISSION", description="Local storage portfolio",
                capex_cents=23_000_000_000, deliverable_mw=100,
            ),
            ROUTE_ANALYST_HEADERS,
        )
    )
    ctx["alt_t2"], ctx["alt_n2"] = alt_t2["id"], alt_n2["id"]
    for alternative_id in (ctx["alt_t2"], ctx["alt_n2"]):
        get_success_data(
            api.screen_alternative(
                alternative_id, f.screening_payload(screen_reason="Carried into the analysis"),
                ROUTE_ANALYST_HEADERS,
            )
        )
    get_success_data(
        api.certify_study_sufficiency(
            ctx["study2"], f.sufficiency_certification_payload(),
            DEVELOPER_CERTIFIER_HEADERS,
        )
    )

    build_plain_route(api, ctx, "proj2", "route2a", "Route A2 - Wolfe loop", "PROPOSED")
    build_plain_route(
        api, ctx, "proj2", "route2b", "Route B2 - Wolfe alternate", "ALTERNATE",
        segments=(
            dict(
                sequence_index=1, miles=5.0, land_use_rating=1, environmental_rating=1,
                cultural_rating=1, engineering_rating=1, county="Boone", crew_capacity=12,
                survey_status="FIELD_VERIFIED", habitat_blackout=False,
                federal_crossing_kind="NONE",
            ),
            dict(
                sequence_index=2, miles=3.0, land_use_rating=1, environmental_rating=1,
                cultural_rating=1, engineering_rating=1, county="Clay", crew_capacity=12,
                survey_status="FIELD_VERIFIED", habitat_blackout=False,
                federal_crossing_kind="NONE",
            ),
        ),
    )
    nominate_route(api, ctx, "route2b", note="Second docket alternate nominated")
    nominate_plain_proposed_route(
        api, ctx, "route2a", publish_at="2026-10-05T09:00:00Z", window_days=30,
        close_at="2026-11-04T09:00:00Z",
    )

    app2 = get_success_data(
        api.create_application(
            f.application_payload(
                ctx["proj2"], ctx["study2"], ctx["route2a"],
                docket_number="EL-2026-0999", filing_fee_cents=2_500_000,
            ),
            DEVELOPER_FILER_HEADERS,
        )
    )
    ctx["app2"] = app2["id"]
    get_success_data(
        api.review_application_sufficiency(
            ctx["app2"], f.sufficiency_review_payload(outcome="ACCEPT"),
            COMMISSION_STAFF_HEADERS,
        )
    )
    sess2 = get_success_data(
        api.create_hearing_session(
            f.hearing_session_payload(
                ctx["app2"], kind="EVIDENTIARY",
                window_start_at="2026-11-10T09:00:00Z",
                window_end_at="2026-11-10T12:00:00Z",
            ),
            HEARING_EXAMINER_HEADERS,
        )
    )
    ctx["sess2a"] = sess2["id"]
    set_clock(api, "2026-11-10T09:00:00Z", HEARING_EXAMINER_HEADERS)
    get_success_data(
        api.hold_hearing_session(
            ctx["sess2a"], f.holding_payload(exhibits_admitted_count=4), HEARING_EXAMINER_HEADERS
        )
    )
    get_success_data(
        api.close_record(ctx["app2"], f.record_closure_payload(), HEARING_EXAMINER_HEADERS)
    )
    get_success_data(
        api.record_decision(
            ctx["app2"],
            f.decision_payload(
                outcome="GRANT",
                certified_route_id=ctx["route2a"],
                eminent_domain_authorized=False,
                mitigation_base_cents=100_000_000,
                conditions=[
                    {
                        "code": "CUL-MON-2",
                        "category": "CULTURAL",
                        "constraint_kind": "MONITORING",
                        "severity_weight": 2,
                    }
                ],
            ),
            COMMISSION_STAFF_HEADERS,
        )
    )
    capture_certificate(api, ctx, cert_key="cert2", condition_prefix="cond2_",
                        application_key="app2")
    return ctx


def apply_for_federal_permit(api, ctx, segment_key="seg2", agency="USACE"):
    """Move segment 2's waterway crossing REQUIRED -> APPLIED."""
    return get_success_data(
        api.record_federal_permit_action(
            ctx[segment_key],
            f.federal_permit_action_payload(action="APPLY", agency=agency),
            FEDERAL_PERMIT_OFFICER_HEADERS,
        )
    )


def deny_federal_permit(api, ctx, segment_key="seg2"):
    return get_success_data(
        api.record_federal_permit_action(
            ctx[segment_key],
            f.federal_permit_action_payload(
                action="DENY", agency=None,
                determination_note="Crossing refused after consultation",
            ),
            FEDERAL_PERMIT_OFFICER_HEADERS,
        )
    )


def file_material_comment(api, ctx, key="comment1", segment_key="seg3", route_key="routeA"):
    """A MATERIAL comment naming a segment — the nomination blocker."""
    data = get_success_data(
        api.create_public_comment(
            f.public_comment_payload(
                ctx[route_key],
                commenter_kind="PUBLIC",
                commenter_name="Clay County Historical Society",
                body="The corridor clips the ridge-top burial ground on this segment.",
                materiality="MATERIAL",
                segment_id=ctx[segment_key],
            ),
            ROUTE_ANALYST_HEADERS,
        )
    )
    ctx[key] = data["id"]
    return data


def setup_two_granted_interventions(api, ctx):
    """Two granted landowner petitions, which lengthen the statutory clock.

    The second grant carries the record to EVIDENTIARY_REQUIRED, sets
    suspension_days to 90 and pushes decision_deadline_at from 2027-08-31 to
    2027-11-29.
    """
    create_landowner(api, ctx, "lo1")
    create_landowner(
        api, ctx, "lo2", name="Boyd Teague", email="boyd@example.com",
        mailing_address="44 Creek Ln, Boone KY",
    )
    petition_to_intervene(api, ctx, "int1", landowner_key="lo1")
    petition_to_intervene(
        api, ctx, "int2", landowner_key="lo2",
        grounds="Alternate ridge route was never studied at my parcel",
    )
    rule_on_petition(api, ctx, "int1", ruling="GRANT")
    rule_on_petition(
        api, ctx, "int2", ruling="GRANT", reason="Alternatives showing is contested"
    )
    return ctx
