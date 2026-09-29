"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: the harness restarts the server before each test, so each
test starts against an empty database and a logical clock reading
2026-08-01T00:00:00Z.

Setup calls use the lenient `get_success_data` validator so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion inside the test body.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import BASE_CLOCK, TEST_DEFAULTS, THRESHOLDS
from . import factories as f
from .test_users import (
    ADMIN,
    make_expert_headers,
    make_research_partner_headers,
    make_volunteer_headers,
)

# Stage markers for build_world().
STAGE_CLOCK = 1
STAGE_PROTOCOL = 2
STAGE_ACTORS = 3
STAGE_ENROLLED = 4
STAGE_TRAINED = 5
STAGE_CERTIFIED = 6
STAGE_CAMPAIGN = 7
STAGE_SITE = 8
STAGE_OPEN = 9

_asset_seq = itertools.count(1)
_photo_seq = itertools.count(1)


# --------------------------------------------------------------------------
# Tier 1: primitive single-call setup helpers
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock and return the reported body."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_protocol(**overrides) -> dict:
    return get_success_data(api.create_protocol(f.create_protocol_payload(**overrides), ADMIN))


def create_active_protocol(**overrides) -> dict:
    protocol = create_protocol(**overrides)
    return get_success_data(api.activate_protocol(protocol["id"], ADMIN))


def create_volunteer(**overrides) -> dict:
    return get_success_data(api.create_volunteer(f.create_volunteer_payload(**overrides), ADMIN))


def create_expert(**overrides) -> dict:
    return get_success_data(api.create_expert(f.create_expert_payload(**overrides), ADMIN))


def create_campaign(protocol_id, **overrides) -> dict:
    return get_success_data(
        api.create_campaign(f.create_campaign_payload(protocol_id, **overrides), ADMIN))


def create_site(campaign_id, **overrides) -> dict:
    return get_success_data(
        api.create_site(campaign_id, f.create_site_payload(**overrides), ADMIN))


def open_campaign(campaign_id) -> dict:
    return get_success_data(api.open_campaign(campaign_id, ADMIN))


def close_campaign(campaign_id) -> dict:
    return get_success_data(api.close_campaign(campaign_id, ADMIN))


def read_campaign(campaign_id) -> dict:
    return get_success_data(api.get_campaign(campaign_id, ADMIN))


def read_observation(observation_id) -> dict:
    return get_success_data(api.get_observation(observation_id, ADMIN))


def read_volunteer(volunteer_id) -> dict:
    return get_success_data(api.get_volunteer(volunteer_id, ADMIN))


def read_expert(expert_id) -> dict:
    return get_success_data(api.get_expert(expert_id, ADMIN))


def read_certification(certification_id) -> dict:
    return get_success_data(api.get_certification(certification_id, ADMIN))


def read_equipment(equipment_id) -> dict:
    return get_success_data(api.get_equipment(equipment_id, ADMIN))


def read_loan(loan_id) -> dict:
    return get_success_data(api.get_loan(loan_id, ADMIN))


def read_publication(publication_id) -> dict:
    return get_success_data(api.get_publication(publication_id, ADMIN))


def read_partner(partner_id) -> dict:
    return get_success_data(api.get_partner(partner_id, ADMIN))


def read_grant(grant_id) -> dict:
    return get_success_data(api.get_access_grant(grant_id, ADMIN))


def read_site(campaign_id, site_id) -> dict:
    rows, _meta = _paginate(lambda params: api.list_sites(campaign_id, ADMIN, params))
    for row in rows:
        if row["id"] == site_id:
            return row
    raise AssertionError(f"Setup failed: site {site_id} not found under campaign {campaign_id}")


def _paginate(call, page=100):
    body = get_success_data_list(call({"limit": page, "offset": 0}))
    rows, meta = body
    offset = page
    while meta.get("has_more"):
        more_rows, meta = get_success_data_list(call({"limit": page, "offset": offset}))
        rows = rows + more_rows
        offset += page
    return rows, meta


def get_success_data_list(response):
    body = response.json()
    assert 200 <= response.status_code < 300, (
        f"Setup failed: {response.status_code} {response.text}")
    return body["data"], body["meta"]


def list_awards(**params) -> list:
    query = dict(params)
    rows, _meta = _paginate(lambda p: api.list_awards(ADMIN, {**query, **p}))
    return rows


def list_votes(observation_id, **params) -> list:
    query = dict(params)
    rows, _meta = _paginate(lambda p: api.list_votes(observation_id, ADMIN, {**query, **p}))
    return rows


# --------------------------------------------------------------------------
# Tier 2: the standard program world
# --------------------------------------------------------------------------

def enroll_certification(volunteer_id, protocol_id, trainer_expert_id, level="ADVANCED") -> dict:
    return get_success_data(api.create_certification(
        f.create_certification_payload(volunteer_id, protocol_id, trainer_expert_id, level),
        ADMIN))


def complete_training(certification_id, trainer_expert_id,
                      exam_score=TEST_DEFAULTS["EXAM_SCORE"]) -> dict:
    return get_success_data(api.complete_training(
        certification_id, f.complete_training_payload(exam_score),
        make_expert_headers(trainer_expert_id)))


def grant_certification(certification_id) -> dict:
    return get_success_data(api.grant_certification(certification_id, ADMIN))


def certify(volunteer_id, protocol_id, trainer_expert_id, level="ADVANCED",
            exam_score=TEST_DEFAULTS["EXAM_SCORE"]) -> dict:
    """Enrol -> complete training -> grant. Returns the CERTIFIED certification."""
    cert = enroll_certification(volunteer_id, protocol_id, trainer_expert_id, level)
    complete_training(cert["id"], trainer_expert_id, exam_score)
    return grant_certification(cert["id"])


def build_world(stage=STAGE_OPEN, clock=BASE_CLOCK, cert_level="ADVANCED",
                protocol_overrides=None, campaign_overrides=None,
                site_overrides=None):
    """Build the standard program world up to `stage` and return its handles.

    Stage ladder:
      1 clock -> 2 active protocol -> 3 volunteer + three experts
      -> 4 certification ENROLLED -> 5 TRAINED -> 6 CERTIFIED
      -> 7 campaign PLANNED -> 8 one survey site -> 9 campaign OPEN

    Returned keys: clock, protocol/p1, volunteer/v1/vol_headers,
    trainer/et/trainer_headers, expert1/e1/e1_headers,
    expert2/e2/e2_headers, certification/c1, campaign/cam1, site/s_hi.
    """
    world = {}
    if stage < STAGE_CLOCK:
        return world

    set_clock(clock)
    world["clock"] = clock
    if stage < STAGE_PROTOCOL:
        return world

    protocol = create_active_protocol(**(protocol_overrides or {}))
    world["protocol"] = protocol
    world["p1"] = protocol["id"]
    if stage < STAGE_ACTORS:
        return world

    volunteer = create_volunteer()
    trainer = create_expert(full_name="Tess Trainer",
                            verification_weight=TEST_DEFAULTS["TRAINER_WEIGHT"])
    expert1 = create_expert(full_name="Ada Verifier",
                            verification_weight=TEST_DEFAULTS["VERIFIER_WEIGHT"])
    expert2 = create_expert(full_name="Bo Verifier",
                            verification_weight=TEST_DEFAULTS["VERIFIER_WEIGHT"])
    world.update({
        "volunteer": volunteer, "v1": volunteer["id"],
        "vol_headers": make_volunteer_headers(volunteer["id"]),
        "trainer": trainer, "et": trainer["id"],
        "trainer_headers": make_expert_headers(trainer["id"]),
        "expert1": expert1, "e1": expert1["id"],
        "e1_headers": make_expert_headers(expert1["id"]),
        "expert2": expert2, "e2": expert2["id"],
        "e2_headers": make_expert_headers(expert2["id"]),
    })
    if stage < STAGE_ENROLLED:
        return world

    cert = enroll_certification(volunteer["id"], protocol["id"], trainer["id"], cert_level)
    world["certification"] = cert
    world["c1"] = cert["id"]
    if stage >= STAGE_TRAINED:
        world["certification"] = complete_training(cert["id"], trainer["id"])
    if stage >= STAGE_CERTIFIED:
        world["certification"] = grant_certification(cert["id"])
        world["volunteer"] = read_volunteer(volunteer["id"])
    if stage < STAGE_CAMPAIGN:
        return world

    campaign = create_campaign(protocol["id"], **(campaign_overrides or {}))
    world["campaign"] = campaign
    world["cam1"] = campaign["id"]
    if stage < STAGE_SITE:
        return world

    site = create_site(campaign["id"], **(site_overrides or {}))
    world["site"] = site
    world["s_hi"] = site["id"]
    if stage < STAGE_OPEN:
        return world

    world["campaign"] = open_campaign(campaign["id"])
    return world


# --------------------------------------------------------------------------
# Tier 3: observation lifecycle shortcuts
# --------------------------------------------------------------------------

def submit_observation(world, site_id=None, **overrides) -> dict:
    payload = f.create_observation_payload(
        world["cam1"], site_id or world["s_hi"], world["v1"], **overrides)
    return get_success_data(api.create_observation(payload, world["vol_headers"]))


def attach_photo(world, observation_id, **overrides) -> dict:
    overrides.setdefault("file_hash", f"ph-{next(_photo_seq):04d}")
    return get_success_data(api.attach_photo(
        observation_id, f.create_photo_payload(**overrides), world["vol_headers"]))


def start_review(observation_id, expert_headers) -> dict:
    return get_success_data(api.start_review(observation_id, expert_headers))


def cast_vote(observation_id, expert_headers, decision, confidence=5, comment=None) -> dict:
    """Re-read the observation's current version, then cast the vote."""
    current = read_observation(observation_id)
    payload = f.cast_vote_payload(decision, confidence, current["version"])
    if comment is not None:
        payload["comment"] = comment
    return get_success_data(api.cast_vote(observation_id, payload, expert_headers))


def submit_with_photo(world, site_id=None, photo_overrides=None, **overrides) -> dict:
    """Create an observation and attach one photo that screens ACCEPTED."""
    obs = submit_observation(world, site_id=site_id, **overrides)
    photo_kwargs = dict(photo_overrides or {})
    photo_kwargs.setdefault("captured_at", obs["observed_at"])
    photo_kwargs.setdefault("exif_latitude", obs["latitude"])
    photo_kwargs.setdefault("exif_longitude", obs["longitude"])
    attach_photo(world, obs["id"], **photo_kwargs)
    return read_observation(obs["id"])


def drive_to_under_review(world, site_id=None, photo_overrides=None, **overrides) -> dict:
    obs = submit_with_photo(world, site_id=site_id, photo_overrides=photo_overrides, **overrides)
    return start_review(obs["id"], world["e1_headers"])


def resolve_by_two_votes(world, observation_id, decision, confidence=5, comment=None) -> dict:
    """Cast the two verifier votes that carry the resolution ladder."""
    cast_vote(observation_id, world["e1_headers"], decision, confidence, comment)
    cast_vote(observation_id, world["e2_headers"], decision, confidence, comment)
    return read_observation(observation_id)


def create_accepted_observation(world, site_id=None, confidence=5,
                                photo_overrides=None, **overrides) -> dict:
    """Submit -> photograph -> review -> two CONFIRM votes. Returns ACCEPTED row."""
    obs = drive_to_under_review(world, site_id=site_id,
                                photo_overrides=photo_overrides, **overrides)
    return resolve_by_two_votes(world, obs["id"], "CONFIRM", confidence)


def create_rejected_observation(world, site_id=None, confidence=5,
                                photo_overrides=None, **overrides) -> dict:
    obs = drive_to_under_review(world, site_id=site_id,
                                photo_overrides=photo_overrides, **overrides)
    return resolve_by_two_votes(world, obs["id"], "REJECT", confidence)


def create_revision_requested_observation(world, site_id=None, confidence=2,
                                          comment=None, **overrides) -> dict:
    obs = drive_to_under_review(world, site_id=site_id, **overrides)
    return resolve_by_two_votes(world, obs["id"], "REQUEST_REVISION", confidence, comment)


def push_revision_round(world, observation_id, confidence=2) -> dict:
    """From SUBMITTED: start review, two REQUEST_REVISION votes -> NEEDS_REVISION."""
    start_review(observation_id, world["e1_headers"])
    cast_vote(observation_id, world["e1_headers"], "REQUEST_REVISION", confidence)
    cast_vote(observation_id, world["e2_headers"], "REQUEST_REVISION", confidence)
    return read_observation(observation_id)


def resubmit(world, observation_id, **payload) -> dict:
    return get_success_data(
        api.resubmit_observation(observation_id, dict(payload), world["vol_headers"]))


def retract(observation_id, reason="administrative retraction") -> dict:
    return get_success_data(
        api.retract_observation(observation_id, f.reason_payload(reason), ADMIN))


# --------------------------------------------------------------------------
# Tier 4: equipment custody shortcuts
# --------------------------------------------------------------------------

def register_equipment(**overrides) -> dict:
    overrides.setdefault("asset_tag", f"EQ-{next(_asset_seq):03d}")
    return get_success_data(api.create_equipment(f.create_equipment_payload(**overrides), ADMIN))


def request_loan(equipment_id, volunteer_id, start_at="2026-08-05T12:00:00Z",
                 due_at="2026-08-20T00:00:00Z", headers=None) -> dict:
    """Re-read the instrument's current version, then book the window."""
    equipment = read_equipment(equipment_id)
    payload = f.create_loan_payload(equipment_id, volunteer_id, equipment["version"],
                                    start_at=start_at, due_at=due_at)
    return get_success_data(api.create_loan(payload, headers or ADMIN))


def issue_loan(loan_id) -> dict:
    return get_success_data(api.issue_loan(loan_id, ADMIN))


def return_loan(loan_id, condition_on_return="GOOD") -> dict:
    return get_success_data(
        api.return_loan(loan_id, f.return_loan_payload(condition_on_return), ADMIN))


def setup_issued_loan(world, equipment_overrides=None,
                      start_at="2026-08-05T12:00:00Z",
                      due_at="2026-08-20T00:00:00Z"):
    """Register an instrument, book it for the volunteer and hand it over."""
    equipment = register_equipment(**(equipment_overrides or {}))
    loan = request_loan(equipment["id"], world["v1"], start_at=start_at, due_at=due_at)
    loan = issue_loan(loan["id"])
    return read_equipment(equipment["id"]), loan


def setup_quarantined_equipment(world, return_clock, condition_on_return="GOOD",
                                equipment_overrides=None,
                                start_at="2026-08-05T12:00:00Z",
                                due_at="2026-08-20T00:00:00Z"):
    """Issue an instrument then take it back, leaving it in QUARANTINE."""
    equipment, loan = setup_issued_loan(world, equipment_overrides, start_at, due_at)
    set_clock(return_clock)
    loan = return_loan(loan["id"], condition_on_return)
    return read_equipment(equipment["id"]), loan


def run_maintenance() -> dict:
    return get_success_data(api.run_maintenance(ADMIN))


# --------------------------------------------------------------------------
# Tier 5: publication and partner access shortcuts
# --------------------------------------------------------------------------

def create_publication(campaign_id, doi="10.5555/cs-2026-01", embargo_until=None) -> dict:
    """Re-read the campaign's current version, then assemble the publication."""
    campaign = read_campaign(campaign_id)
    payload = f.create_publication_payload(campaign_id, campaign["version"], doi=doi)
    if embargo_until is not None:
        payload["embargo_until"] = embargo_until
    return get_success_data(api.create_publication(payload, ADMIN))


def setup_publishable_campaign(world, accepted_count=2, site_id=None, confidence=5):
    """Accept `accepted_count` observations then close the campaign."""
    observations = []
    for index in range(accepted_count):
        observations.append(create_accepted_observation(
            world, site_id=site_id, confidence=confidence, count_value=index + 1))
    close_campaign(world["cam1"])
    return observations


def setup_released_publication(world, doi="10.5555/cs-2026-01", accepted_count=2,
                               embargo_until=None):
    """Full path to a released (or embargoed) publication on the standard world."""
    observations = setup_publishable_campaign(world, accepted_count=accepted_count)
    publication = create_publication(world["cam1"], doi=doi, embargo_until=embargo_until)
    publication = get_success_data(api.release_publication(publication["id"], ADMIN))
    return publication, observations


def register_partner(approved=True, **overrides) -> dict:
    partner = get_success_data(api.create_partner(f.create_partner_payload(**overrides), ADMIN))
    if approved:
        partner = get_success_data(api.approve_partner(partner["id"], ADMIN))
    return partner


def request_grant(publication_id, partner_id, scope="AGGREGATE",
                  expires_at="2027-01-01T00:00:00Z", headers=None) -> dict:
    payload = f.create_access_grant_payload(publication_id, partner_id, scope, expires_at)
    return get_success_data(api.create_access_grant(payload, headers or ADMIN))


def approve_grant(grant_id) -> dict:
    return get_success_data(api.approve_access_grant(grant_id, ADMIN))


def setup_partner_with_approved_grant(world, scope="FULL", doi="10.5555/cs-2026-02",
                                      trust_tier="STANDARD",
                                      data_use_agreement_signed_at="2026-07-01T00:00:00Z",
                                      org_name="Boreal Institute"):
    """Released publication + approved partner + one APPROVED access grant."""
    publication, observations = setup_released_publication(world, doi=doi)
    partner = register_partner(
        approved=True, org_name=org_name, trust_tier=trust_tier,
        data_use_agreement_signed_at=data_use_agreement_signed_at)
    grant = approve_grant(request_grant(publication["id"], partner["id"], scope)["id"])
    return publication, partner, grant, observations


def read_protocol(protocol_id) -> dict:
    return get_success_data(api.get_protocol(protocol_id, ADMIN))


def read_photo(observation_id, photo_id) -> dict:
    rows = list_photos(observation_id)
    for row in rows:
        if row["id"] == photo_id:
            return row
    raise AssertionError(
        f"Setup failed: photo {photo_id} not found on observation {observation_id}")


def list_photos(observation_id, **params) -> list:
    query = dict(params)
    rows, _meta = _paginate(lambda p: api.list_photos(observation_id, ADMIN, {**query, **p}))
    return rows


def list_observations(**params) -> list:
    query = dict(params)
    rows, _meta = _paginate(lambda p: api.list_observations(ADMIN, {**query, **p}))
    return rows


def list_loans(**params) -> list:
    query = dict(params)
    rows, _meta = _paginate(lambda p: api.list_loans(ADMIN, {**query, **p}))
    return rows


def list_publications(**params) -> list:
    query = dict(params)
    rows, _meta = _paginate(lambda p: api.list_publications(ADMIN, {**query, **p}))
    return rows


def list_access_grants(**params) -> list:
    query = dict(params)
    rows, _meta = _paginate(lambda p: api.list_access_grants(ADMIN, {**query, **p}))
    return rows
