"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. They use the lenient get_success_data validator
so a setup failure surfaces as a clear setup error rather than an assertion
failure deep inside a test.

All six roles are opaque identities (PRD section 2.1); the shared role header
constants are canonical. Only payout propose/approve needs distinct operator
ids (segregation of duties), supplied via make_incentive_manager_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_care_gap_payload,
    create_complaint_case_payload,
    create_cutpoint_set_payload,
    create_incentive_payout_payload,
    create_measure_payload,
    create_measure_performance_payload,
    create_member_payload,
    create_provider_group_payload,
    create_rating_cycle_payload,
    create_rating_forecast_payload,
    create_survey_vendor_payload,
    create_survey_wave_payload,
    cutpoint_row,
)
from .test_users import TEST_USERS, make_incentive_manager_headers

ADMIN = TEST_USERS["stars_admin_headers"]
ANALYST = TEST_USERS["stars_analyst_headers"]
OPS = TEST_USERS["quality_ops_headers"]
SURVEY = TEST_USERS["survey_coordinator_headers"]
INCENTIVE = TEST_USERS["incentive_manager_headers"]
AUDITOR = TEST_USERS["complaints_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and state progression
# ---------------------------------------------------------------------------

def create_cycle(measurement_year=2026, rating_year=2028, benchmark_pmpm=950.0):
    """Create a rating cycle (born SETUP). Returns the cycle."""
    return get_success_data(api_client.create_rating_cycle(
        create_rating_cycle_payload(measurement_year, rating_year, benchmark_pmpm),
        ADMIN))


def transition_cycle(cycle_id, to_state):
    """Drive the cycle lifecycle. Returns the updated cycle."""
    return get_success_data(api_client.transition_rating_cycle(cycle_id, to_state, ADMIN))


def get_cycle(cycle_id):
    return get_success_data(api_client.get_rating_cycle(cycle_id, ADMIN))


def create_measure(cycle_id, code="BCS", measure_type="PROCESS",
                   direction="HIGHER_BETTER", data_source="HEDIS",
                   domain="STAYING_HEALTHY", improvement_eligible=False,
                   prior_cycle_star=None, title=None):
    """Register a measure (born DRAFT). Returns the measure."""
    return get_success_data(api_client.create_measure(
        create_measure_payload(
            cycle_id, code=code, title=title, domain=domain,
            measure_type=measure_type, direction=direction, data_source=data_source,
            improvement_eligible=improvement_eligible,
            prior_cycle_star=prior_cycle_star),
        ANALYST))


def transition_measure(measure_id, to_state):
    return get_success_data(api_client.transition_measure(measure_id, to_state, ANALYST))


def create_active_measure(cycle_id, **kwargs):
    """Create a measure and activate it (cycle must be SETUP or DATA_COLLECTION)."""
    measure = create_measure(cycle_id, **kwargs)
    transition_measure(measure["id"], "ACTIVE")
    return get_success_data(api_client.get_measure(measure["id"], ANALYST))


def create_draft_set(cycle_id, rows, label="draft-2028"):
    """Create a DRAFT cut point set with the given rows. Returns the set."""
    return get_success_data(api_client.create_cutpoint_set(
        create_cutpoint_set_payload(cycle_id, label=label, rows=rows), ANALYST))


def get_cutpoint_set(set_id):
    return get_success_data(api_client.get_cutpoint_set(set_id, ANALYST))


def replace_rows(set_id, rows, expected_cutpoint_set_version):
    return get_success_data(api_client.replace_cutpoint_rows(
        set_id, {"rows": rows,
                 "expected_cutpoint_set_version": expected_cutpoint_set_version},
        ANALYST))


def publish_set(cycle_id, set_id):
    """Publish a DRAFT set, re-reading the cycle version for the OCC field."""
    cycle = get_cycle(cycle_id)
    return get_success_data(api_client.publish_cutpoint_set(
        set_id, cycle["version"], ADMIN))


def report_performance(cycle_id, measure_id, numerator, denominator,
                       exclusion_count=None, reporter_headers=None):
    """Report a measure performance (born REPORTED). Returns the performance."""
    return get_success_data(api_client.create_measure_performance(
        create_measure_performance_payload(cycle_id, measure_id, numerator,
                                           denominator, exclusion_count),
        reporter_headers or OPS))


def transition_performance(perf_id, to_state):
    return get_success_data(api_client.transition_measure_performance(
        perf_id, to_state, ANALYST))


def validate_performance(perf_id):
    return transition_performance(perf_id, "VALIDATED")


def lock_performance(perf_id):
    """Walk a performance REPORTED -> VALIDATED -> LOCKED. Returns the perf."""
    perf = get_success_data(api_client.get_measure_performance(perf_id, ANALYST))
    if perf["status"] == "REPORTED":
        transition_performance(perf_id, "VALIDATED")
    return transition_performance(perf_id, "LOCKED")


def get_performance(perf_id):
    return get_success_data(api_client.get_measure_performance(perf_id, ANALYST))


def create_member(member_ref, enrolled_months=12, plan_contract="H1234"):
    """Enroll a member (born ENROLLED). Returns the member."""
    return get_success_data(api_client.create_member(
        create_member_payload(member_ref, plan_contract, enrolled_months), OPS))


def transition_member(member_id, to_state):
    return get_success_data(api_client.transition_member(member_id, to_state, OPS))


def disenroll_member(member_id):
    return transition_member(member_id, "DISENROLLED")


def open_gap(member_id, measure_id, gap_type="SCREENING"):
    """Open a care gap (born OPEN). Returns the gap."""
    return get_success_data(api_client.create_care_gap(
        create_care_gap_payload(member_id, measure_id, gap_type), OPS))


def transition_gap(gap_id, to_state):
    return get_success_data(api_client.transition_care_gap(gap_id, to_state, OPS))


def close_gap(gap_id):
    return transition_gap(gap_id, "CLOSED")


def reopen_gap(gap_id):
    return transition_gap(gap_id, "REOPENED")


def intervene(gap_id, channel):
    return get_success_data(api_client.intervene_care_gap(gap_id, channel, OPS))


def get_gap(gap_id):
    return get_success_data(api_client.get_care_gap(gap_id, OPS))


def create_vendor(name="Vendor V", max_concurrent_waves=5):
    return get_success_data(api_client.create_survey_vendor(
        create_survey_vendor_payload(name, max_concurrent_waves), SURVEY))


def plan_wave(cycle_id, vendor_id, survey_type, window_start, window_end,
             sample_size=100):
    """Plan a survey wave (born PLANNED). Returns the wave."""
    return get_success_data(api_client.create_survey_wave(
        create_survey_wave_payload(cycle_id, survey_type, vendor_id,
                                  window_start, window_end, sample_size),
        SURVEY))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_group(name, program_type, linked_measure_id, target_star=5,
                 unit_reward_per_gap=250.0, max_pool_amount=10000.0):
    """Create a provider group (born ACTIVE). Returns the group."""
    return get_success_data(api_client.create_provider_group(
        create_provider_group_payload(name, program_type, linked_measure_id,
                                      target_star, unit_reward_per_gap,
                                      max_pool_amount),
        INCENTIVE))


def get_group(group_id):
    return get_success_data(api_client.get_provider_group(group_id, INCENTIVE))


def close_group(group_id):
    return get_success_data(api_client.transition_provider_group(
        group_id, "CLOSED", INCENTIVE))


def propose_payout(group_id, proposer_user_id="im-1"):
    """Propose a payout as the given IncentiveManager operator (born PENDING)."""
    return get_success_data(api_client.create_incentive_payout(
        create_incentive_payout_payload(group_id),
        make_incentive_manager_headers(proposer_user_id)))


def transition_payout(payout_id, to_state, user_id="im-2"):
    return get_success_data(api_client.transition_incentive_payout(
        payout_id, to_state, make_incentive_manager_headers(user_id)))


def approve_payout(payout_id, user_id="im-2"):
    return transition_payout(payout_id, "APPROVED", user_id)


def pay_payout(payout_id, user_id="im-2"):
    return transition_payout(payout_id, "PAID", user_id)


def deny_payout(payout_id, user_id="im-2"):
    return transition_payout(payout_id, "DENIED", user_id)


def get_payout(payout_id):
    return get_success_data(api_client.get_incentive_payout(payout_id, INCENTIVE))


def file_complaint(cycle_id, member_id, category="BILLING",
                   filed_at="2026-08-01T00:00:00Z"):
    """File a complaint case (born FILED). Returns the case."""
    return get_success_data(api_client.create_complaint_case(
        create_complaint_case_payload(cycle_id, member_id, category, filed_at),
        AUDITOR))


def resolve_complaint(case_id, to_state):
    return get_success_data(api_client.transition_complaint_case(
        case_id, to_state, AUDITOR))


def run_forecast(cycle_id, basis="DRAFT_CUTPOINTS"):
    """Run and persist a rating forecast. Returns the forecast snapshot."""
    return get_success_data(api_client.create_rating_forecast(
        create_rating_forecast_payload(cycle_id, basis), ANALYST))


# ---------------------------------------------------------------------------
# Tier 2: measure + performance scenarios inside a collecting cycle
# ---------------------------------------------------------------------------

def setup_collecting_measure(numerator=10, denominator=20,
                             measure_kwargs=None, floors=None,
                             set_label="draft-2028", performance=True):
    """Cycle in DATA_COLLECTION with one ACTIVE measure, optionally a DRAFT cut
    point set with one row, and optionally a REPORTED performance.

    Returns a dict: cycle, measure, cutpoint_set (or None), performance (or None).
    """
    measure_kwargs = dict(measure_kwargs or {})
    cycle = create_cycle()
    measure = create_active_measure(cycle["id"], **measure_kwargs)
    cutpoint_set = None
    if floors is not None:
        cutpoint_set = create_draft_set(
            cycle["id"], [cutpoint_row(measure["id"], *floors)], label=set_label)
    transition_cycle(cycle["id"], "DATA_COLLECTION")
    perf = None
    if performance:
        perf = report_performance(cycle["id"], measure["id"], numerator, denominator)
    return {
        "cycle": get_cycle(cycle["id"]),
        "measure": measure,
        "cutpoint_set": cutpoint_set,
        "performance": perf,
    }


def setup_gap_scenario(numerator=10, denominator=20, gap_type="SCREENING",
                       measure_kwargs=None, floors=None, member_ref="MBR-1"):
    """Collecting cycle + ACTIVE measure + REPORTED performance + ENROLLED
    member + one OPEN gap (opening already credited the denominator +1).

    Returns a dict: cycle, measure, cutpoint_set, performance, member, gap.
    """
    sc = setup_collecting_measure(numerator, denominator,
                                  measure_kwargs=measure_kwargs, floors=floors)
    member = create_member(member_ref)
    gap = open_gap(member["id"], sc["measure"]["id"], gap_type)
    sc["member"] = member
    sc["gap"] = gap
    sc["performance"] = get_performance(sc["performance"]["id"])
    return sc


# ---------------------------------------------------------------------------
# Tier 3: locked-performance / cutpoint-review scenarios
# ---------------------------------------------------------------------------

def setup_locked_performance_scenario(numerator=5, denominator=10,
                                      measure_kwargs=None, floors=None,
                                      with_open_gap=False):
    """Cycle in DATA_COLLECTION with an ACTIVE measure whose performance is
    LOCKED. Optionally adds one ENROLLED member with an OPEN gap (gap opened
    while the performance was still REPORTED).

    Returns a dict with cycle, measure, cutpoint_set, performance, and
    optionally member and gap.
    """
    sc = setup_collecting_measure(numerator, denominator,
                                  measure_kwargs=measure_kwargs, floors=floors)
    if with_open_gap:
        member = create_member("MBR-1")
        gap = open_gap(member["id"], sc["measure"]["id"], "SCREENING")
        sc["member"] = member
        sc["gap"] = gap
    lock_performance(sc["performance"]["id"])
    sc["performance"] = get_performance(sc["performance"]["id"])
    sc["cycle"] = get_cycle(sc["cycle"]["id"])
    return sc


def setup_cycle_in_cutpoint_review(numerator=5, denominator=10,
                                   measure_kwargs=None, floors=None):
    """Cycle advanced DATA_COLLECTION -> CUTPOINT_REVIEW with one LOCKED
    performance. Returns the scenario dict."""
    sc = setup_locked_performance_scenario(numerator, denominator,
                                           measure_kwargs=measure_kwargs,
                                           floors=floors)
    transition_cycle(sc["cycle"]["id"], "CUTPOINT_REVIEW")
    sc["cycle"] = get_cycle(sc["cycle"]["id"])
    return sc


# ---------------------------------------------------------------------------
# Tier 4: the four-measure review fixture (weighted stars + improvement)
# ---------------------------------------------------------------------------

# Measure codes / shapes for the shared four-measure fixture:
#   BCS  PROCESS            w1  improvement_eligible, prior 3
#   SPD  OUTCOME            w3  improvement_eligible, prior 4
#   CNC  PATIENT_EXPERIENCE w4  not eligible
#   CMP  OUTCOME LOWER      w3  not eligible
FOUR_MEASURE_SPEC = [
    {"key": "m1", "code": "BCS", "title": "Breast Cancer Screening",
     "domain": "STAYING_HEALTHY", "measure_type": "PROCESS",
     "direction": "HIGHER_BETTER", "data_source": "HEDIS",
     "improvement_eligible": True, "prior_cycle_star": 3,
     "numerator": 17, "denominator": 20},
    {"key": "m2", "code": "SPD", "title": "Statin Adherence",
     "domain": "DRUG_SAFETY", "measure_type": "OUTCOME",
     "direction": "HIGHER_BETTER", "data_source": "PHARMACY_PDE",
     "improvement_eligible": True, "prior_cycle_star": 4,
     "numerator": 2123, "denominator": 2500},
    {"key": "m3", "code": "CNC", "title": "Getting Needed Care",
     "domain": "MEMBER_EXPERIENCE", "measure_type": "PATIENT_EXPERIENCE",
     "direction": "HIGHER_BETTER", "data_source": "CAHPS",
     "improvement_eligible": False,
     "numerator": 33, "denominator": 50},
    {"key": "m4", "code": "CMP", "title": "Complaints Rate",
     "domain": "MEMBER_COMPLAINTS", "measure_type": "OUTCOME",
     "direction": "LOWER_BETTER", "data_source": "COMPLAINTS",
     "improvement_eligible": False,
     "numerator": 9, "denominator": 20},
]

# Published-basis floors band the four performances to 3/3/3/3.
FOUR_MEASURE_PUBLISHED_FLOORS = {
    "m1": (0.62, 0.75, 0.90, 0.95),
    "m2": (0.72, 0.80, 0.88, 0.93),
    "m3": (0.55, 0.65, 0.78, 0.90),
    "m4": (1.20, 0.80, 0.40, 0.15),  # LOWER_BETTER: b2 > b3 > b4 > b5
}

# Draft-basis floors band the four performances to 4/4/3/4.
FOUR_MEASURE_DRAFT_FLOORS = {
    "m1": (0.60, 0.72, 0.85, 0.94),
    "m2": (0.70, 0.78, 0.85, 0.92),
    "m3": (0.55, 0.65, 0.75, 0.88),
    "m4": (1.50, 0.90, 0.50, 0.20),  # LOWER_BETTER: b2 > b3 > b4 > b5
}


def setup_four_measure_review_cycle(with_draft_set=True, publish=True,
                                    member_refs=()):
    """Four-measure cycle driven all the way to CUTPOINT_REVIEW with every
    performance LOCKED and (optionally) the published-basis set PUBLISHED.

    Returns a dict: cycle, measures {key: measure}, performances {key: perf},
    published_set, draft_set (or None), members [member, ...].
    """
    cycle = create_cycle()
    measures = {}
    for spec in FOUR_MEASURE_SPEC:
        measures[spec["key"]] = create_active_measure(
            cycle["id"], code=spec["code"], title=spec["title"],
            domain=spec["domain"], measure_type=spec["measure_type"],
            direction=spec["direction"], data_source=spec["data_source"],
            improvement_eligible=spec["improvement_eligible"],
            prior_cycle_star=spec.get("prior_cycle_star"))

    published_set = create_draft_set(
        cycle["id"],
        [cutpoint_row(measures[k]["id"], *FOUR_MEASURE_PUBLISHED_FLOORS[k])
         for k in ("m1", "m2", "m3", "m4")],
        label="official-2028")
    draft_set = None
    if with_draft_set:
        draft_set = create_draft_set(
            cycle["id"],
            [cutpoint_row(measures[k]["id"], *FOUR_MEASURE_DRAFT_FLOORS[k])
             for k in ("m1", "m2", "m3", "m4")],
            label="draft-2028")

    transition_cycle(cycle["id"], "DATA_COLLECTION")

    performances = {}
    for spec in FOUR_MEASURE_SPEC:
        perf = report_performance(cycle["id"], measures[spec["key"]]["id"],
                                  spec["numerator"], spec["denominator"])
        lock_performance(perf["id"])
        performances[spec["key"]] = get_performance(perf["id"])

    transition_cycle(cycle["id"], "CUTPOINT_REVIEW")

    if publish:
        publish_set(cycle["id"], published_set["id"])
        published_set = get_cutpoint_set(published_set["id"])

    members = [create_member(ref) for ref in member_refs]

    return {
        "cycle": get_cycle(cycle["id"]),
        "measures": measures,
        "performances": performances,
        "published_set": published_set,
        "draft_set": draft_set,
        "members": members,
    }


# ---------------------------------------------------------------------------
# Tier 4: incentive program scenarios
# ---------------------------------------------------------------------------

def setup_gap_closure_group(num_closed_gaps=1, unit_reward_per_gap=250.0,
                            max_pool_amount=10000.0, target_star=5,
                            group_name="Group G"):
    """Collecting cycle + ACTIVE PHARMACY_PDE measure + REPORTED 0/0
    performance + num_closed_gaps members each with a CLOSED
    PHARMACY_ADHERENCE gap + an ACTIVE GAP_CLOSURE provider group.

    Returns a dict: cycle, measure, performance, members, gaps, group.
    """
    sc = setup_collecting_measure(
        0, 0,
        measure_kwargs={"code": "SPD", "title": "Statin Adherence",
                        "domain": "DRUG_SAFETY", "measure_type": "OUTCOME",
                        "data_source": "PHARMACY_PDE"})
    members = []
    gaps = []
    for i in range(num_closed_gaps):
        member = create_member(f"MBR-{i + 1}")
        gap = open_gap(member["id"], sc["measure"]["id"], "PHARMACY_ADHERENCE")
        close_gap(gap["id"])
        members.append(member)
        gaps.append(get_gap(gap["id"]))
    group = create_group(group_name, "GAP_CLOSURE", sc["measure"]["id"],
                         target_star=target_star,
                         unit_reward_per_gap=unit_reward_per_gap,
                         max_pool_amount=max_pool_amount)
    sc.update({"members": members, "gaps": gaps, "group": group})
    return sc


def setup_paid_out_group(unit_reward_per_gap=250.0, max_pool_amount=100.0):
    """A GAP_CLOSURE group whose entire pool has been paid out and which is
    then CLOSED (no open payouts). Returns the scenario dict."""
    sc = setup_gap_closure_group(num_closed_gaps=1,
                                 unit_reward_per_gap=unit_reward_per_gap,
                                 max_pool_amount=max_pool_amount)
    payout = propose_payout(sc["group"]["id"], "im-1")
    approve_payout(payout["id"], "im-2")
    pay_payout(payout["id"], "im-2")
    close_group(sc["group"]["id"])
    sc["group"] = get_group(sc["group"]["id"])
    sc["payout"] = get_payout(payout["id"])
    return sc


# ---------------------------------------------------------------------------
# Tier 4: survey lane scenarios
# ---------------------------------------------------------------------------

def setup_survey_lane(max_concurrent_waves=5,
                      first_window=("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"),
                      survey_type="CAHPS", sample_size=100):
    """Cycle + vendor + one PLANNED wave on the given window.

    Returns a dict: cycle, vendor, wave.
    """
    cycle = create_cycle()
    vendor = create_vendor(max_concurrent_waves=max_concurrent_waves)
    wave = plan_wave(cycle["id"], vendor["id"], survey_type,
                    first_window[0], first_window[1], sample_size)
    return {"cycle": cycle, "vendor": vendor, "wave": wave}


# ---------------------------------------------------------------------------
# Tier 4: complaints scenarios
# ---------------------------------------------------------------------------

def setup_complaints_measure_scenario(numerator=9, denominator=20,
                                      complaints=()):
    """Collecting cycle + ACTIVE LOWER_BETTER COMPLAINTS measure + REPORTED
    performance + one ENROLLED member + zero or more FILED complaints.

    complaints: list of (category, filed_at) tuples.
    Returns a dict: cycle, measure, performance, member, cases.
    """
    sc = setup_collecting_measure(
        numerator, denominator,
        measure_kwargs={"code": "CMP", "title": "Complaints Rate",
                        "domain": "MEMBER_COMPLAINTS", "measure_type": "OUTCOME",
                        "direction": "LOWER_BETTER", "data_source": "COMPLAINTS"})
    member = create_member("MBR-1")
    cases = [file_complaint(sc["cycle"]["id"], member["id"], category, filed_at)
             for category, filed_at in complaints]
    sc.update({"member": member, "cases": cases})
    return sc


# ---------------------------------------------------------------------------
# Tier 5: terminal-state scenarios
# ---------------------------------------------------------------------------

def setup_officially_published_cycle():
    """Four-measure fixture driven through publish-official-rating:
    cycle OFFICIAL_PUBLISHED with official stars / improvement star / rebate
    computed on the published basis. Returns the scenario dict."""
    sc = setup_four_measure_review_cycle(with_draft_set=True, publish=True)
    transition_cycle(sc["cycle"]["id"], "OFFICIAL_PUBLISHED")
    sc["cycle"] = get_cycle(sc["cycle"]["id"])
    return sc
