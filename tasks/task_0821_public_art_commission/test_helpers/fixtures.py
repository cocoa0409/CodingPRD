"""Composite setup helpers.

Every helper builds its preconditions from scratch (the server restarts with an
empty database before each test) using only PRD-declared endpoints, and uses the
lenient get_success_data() validator so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_artist_headers, make_panelist_headers
from .factories import (
    make_project_payload, make_certify_payload, make_commission_payload,
    make_call_payload, make_panelist_payload, make_artist_payload,
    make_submission_payload, make_score_payload, make_contract_payload,
    make_milestone_schedule_payload, make_site_payload, make_artwork_payload,
    make_install_payload, make_loan_payload,
)

DEADLINE = "2026-06-01T00:00:00Z"


def _admin():
    return TEST_USERS["program_admin_headers"]


def _registrar():
    return TEST_USERS["registrar_headers"]


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------
def create_project(api, construction_budget_cents=200000000, percent_rate=0.01, name="Project"):
    return get_success_data(api.create_project(
        make_project_payload(name=name, construction_budget_cents=construction_budget_cents,
                             percent_rate=percent_rate),
        _admin()))


def create_certified_project(api, construction_budget_cents=200000000,
                             certified_construction_budget_cents=200000000,
                             percent_rate=0.01, name="Project"):
    proj = create_project(api, construction_budget_cents, percent_rate, name)
    return get_success_data(api.certify_project(
        proj["id"], make_certify_payload(certified_construction_budget_cents), _admin()))


def _project_version(api, project_id):
    return get_success_data(api.get_project(project_id, _admin()))["version"]


def create_commission(api, project_id, allocation_cents=900000, title="Commission",
                      expected_version=None):
    if expected_version is None:
        expected_version = _project_version(api, project_id)
    return get_success_data(api.create_commission(
        project_id, make_commission_payload(allocation_cents, expected_version, title=title),
        _admin()))


def create_call(api, commission_id, call_type="RFP", submission_deadline=DEADLINE, quorum_min=1):
    return get_success_data(api.create_call(
        commission_id,
        make_call_payload(call_type=call_type, submission_deadline=submission_deadline,
                          quorum_min=quorum_min),
        _admin()))


def create_artist(api, display_name="Artist", email="artist@example.com"):
    return get_success_data(api.create_artist(
        make_artist_payload(display_name=display_name, email=email), _admin()))


def add_panelist(api, call_id, evaluator_name="Panelist", has_conflict=False):
    return get_success_data(api.add_panelist(
        call_id, make_panelist_payload(evaluator_name=evaluator_name, has_conflict=has_conflict),
        _admin()))


def create_submission(api, call_id, artist_id, proposed_budget_cents=800000):
    return get_success_data(api.create_submission(
        call_id, make_submission_payload(artist_id, proposed_budget_cents=proposed_budget_cents),
        make_artist_headers(artist_id)))


def add_score(api, submission_id, panelist_id, artistic_merit, feasibility,
              community_impact, durability):
    return get_success_data(api.create_score(
        submission_id,
        make_score_payload(panelist_id, artistic_merit, feasibility, community_impact, durability),
        make_panelist_headers(panelist_id)))


def set_clock(api, to_iso8601):
    return api.set_clock({"to_iso8601": to_iso8601}, _admin())


# --------------------------------------------------------------------------
# Selection / scoring composites
# --------------------------------------------------------------------------
def setup_open_call_with_submission(api, quorum_min=1, call_type="RFP",
                                    allocation_cents=900000, proposed_budget_cents=800000,
                                    num_panelists=0, panelist_conflicts=None,
                                    construction_budget_cents=200000000,
                                    certified_construction_budget_cents=200000000):
    """Certified project + commission + OPEN call + artist + one SUBMITTED submission.

    Optionally adds `num_panelists` panelists; panelist_conflicts is an optional
    list of bools (one per panelist) marking recusal. Returns a dict of entities.
    """
    project = create_certified_project(
        api, construction_budget_cents=construction_budget_cents,
        certified_construction_budget_cents=certified_construction_budget_cents)
    commission = create_commission(api, project["id"], allocation_cents=allocation_cents)
    call = create_call(api, commission["id"], call_type=call_type, quorum_min=quorum_min)
    artist = create_artist(api)
    panelists = []
    conflicts = panelist_conflicts or [False] * num_panelists
    for i in range(num_panelists):
        panelists.append(add_panelist(api, call["id"], evaluator_name=f"P{i + 1}",
                                      has_conflict=conflicts[i]))
    submission = create_submission(api, call["id"], artist["id"],
                                   proposed_budget_cents=proposed_budget_cents)
    return {
        "project": project, "commission": commission, "call": call,
        "artist": artist, "panelists": panelists, "submission": submission,
    }


def setup_scored_submission(api, score_specs, quorum_min=1, allocation_cents=900000,
                            proposed_budget_cents=800000, call_type="RFP",
                            construction_budget_cents=200000000,
                            certified_construction_budget_cents=200000000):
    """Certified project through a CLOSED call with one submission scored by every
    (non-recused) panelist. `score_specs` is a list of 4-tuples
    (artistic_merit, feasibility, community_impact, durability); one panelist per
    tuple scores the submission. The call is CLOSED but NOT tabulated. Returns a
    dict with project/commission/call/artist/submission/panelists/scores.
    """
    ctx = setup_open_call_with_submission(
        api, quorum_min=quorum_min, call_type=call_type, allocation_cents=allocation_cents,
        proposed_budget_cents=proposed_budget_cents, num_panelists=len(score_specs),
        construction_budget_cents=construction_budget_cents,
        certified_construction_budget_cents=certified_construction_budget_cents)
    scores = []
    for panelist, spec in zip(ctx["panelists"], score_specs):
        scores.append(add_score(api, ctx["submission"]["id"], panelist["id"], *spec))
    get_success_data(api.close_call(ctx["call"]["id"], _admin()))
    ctx["scores"] = scores
    return ctx


def setup_awarded_commission(api, allocation_cents=1000000, contract_amount_cents=None,
                             proposed_budget_cents=None, score=(80, 80, 80, 80),
                             call_type="RFQ", construction_budget_cents=400000000,
                             certified_construction_budget_cents=400000000):
    """Full chain to an AWARDED commission with a SCORED, then AWARDED submission.
    Returns dict incl project/commission/call/artist/panelist/submission.
    """
    if proposed_budget_cents is None:
        proposed_budget_cents = allocation_cents
    ctx = setup_scored_submission(
        api, [score], quorum_min=1, allocation_cents=allocation_cents,
        proposed_budget_cents=proposed_budget_cents, call_type=call_type,
        construction_budget_cents=construction_budget_cents,
        certified_construction_budget_cents=certified_construction_budget_cents)
    get_success_data(api.tabulate_call(ctx["call"]["id"], _admin()))
    get_success_data(api.award_commission(
        ctx["commission"]["id"], {"submission_id": ctx["submission"]["id"]}, _admin()))
    ctx["panelist"] = ctx["panelists"][0]
    return ctx


def setup_contracted_commission(api, allocation_cents=1000000, contract_amount_cents=1000000,
                                **kwargs):
    """AWARDED commission advanced to CONTRACTED with a DRAFT contract. Returns the
    awarded-commission dict plus `contract`.
    """
    ctx = setup_awarded_commission(api, allocation_cents=allocation_cents, **kwargs)
    contract = get_success_data(api.create_contract(
        ctx["commission"]["id"],
        make_contract_payload(ctx["submission"]["id"], contract_amount_cents), _admin()))
    ctx["contract"] = contract
    return ctx


def schedule_milestones(api, contract_id, milestones, expected_version=None):
    if expected_version is None:
        expected_version = get_success_data(api.get_contract(contract_id, _admin()))["version"]
    return get_success_data(api.schedule_milestones(
        contract_id, make_milestone_schedule_payload(milestones, expected_version), _admin()))


def setup_active_contract_with_artwork(api, contract_amount_cents=1000000,
                                       milestones=None, allocation_cents=1000000, **kwargs):
    """CONTRACTED commission whose contract has a scheduled milestone set and has
    been ACTIVATED (synthesizing the COMMISSION artwork in FABRICATION). Returns
    the contracted dict plus `milestones` (list) and `artwork`.
    """
    if milestones is None:
        milestones = [{"sequence": 1, "title": "Full", "pct": 1.0}]
    ctx = setup_contracted_commission(
        api, allocation_cents=allocation_cents, contract_amount_cents=contract_amount_cents,
        **kwargs)
    ms = schedule_milestones(api, ctx["contract"]["id"], milestones)
    get_success_data(api.activate_contract(ctx["contract"]["id"], _admin()))
    artworks = get_success_data(api.list_artworks(
        _admin(), params={"contract_id": ctx["contract"]["id"]}))
    ctx["milestones"] = ms
    ctx["artwork"] = artworks[0]
    return ctx


# --------------------------------------------------------------------------
# Physical registry composites
# --------------------------------------------------------------------------
def create_site(api, name="Site", address="1 Civic Plaza"):
    return get_success_data(api.create_site(make_site_payload(name=name, address=address),
                                            _registrar()))


def create_donation_artwork(api, title="Donated Piece", appraised_value_cents=500000):
    return get_success_data(api.create_artwork(
        make_artwork_payload(title=title, acquisition_type="DONATION",
                             appraised_value_cents=appraised_value_cents),
        _registrar()))


def install_donation_artwork(api, site_name="Site", install_date="2026-04-01T00:00:00Z",
                             appraised_value_cents=500000):
    """AVAILABLE site with a DONATION artwork installed on it (site OCCUPIED).
    Returns dict with `site` and `artwork` (post-install fetch)."""
    site = create_site(api, name=site_name)
    artwork = create_donation_artwork(api, appraised_value_cents=appraised_value_cents)
    get_success_data(api.install_artwork(
        artwork["id"], make_install_payload(site["id"], install_date), _registrar()))
    site = get_success_data(api.get_site(site["id"], _registrar()))
    artwork = get_success_data(api.get_artwork(artwork["id"], _registrar()))
    return {"site": site, "artwork": artwork}


def create_loan(api, artwork_id, borrower_name, loan_start, loan_end):
    return get_success_data(api.create_loan(
        artwork_id, make_loan_payload(borrower_name, loan_start, loan_end), _registrar()))
