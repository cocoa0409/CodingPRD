"""Composite setup helpers.

These encapsulate the multi-step API sequences needed to put the system in
interesting states, so tests focus on assertions. All setup calls use the
lenient get_success_data() validator so failures surface as clear
"Setup failed" errors.

The server is restarted (empty DB) before every test, so every fixture
builds its preconditions from scratch via PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_grant_payload,
    create_host_agreement_payload,
    create_material_payload,
    create_partner_payload,
    create_program_payload,
    create_route_payload,
    create_site_payload,
    create_stop_payload,
    register_participant_payload,
    create_drop_payload,
)
from .test_users import (
    TEST_USERS,
    make_participant_headers,
    make_processing_partner_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
HOST = TEST_USERS["site_host_headers"]
OPERATOR = TEST_USERS["route_operator_headers"]
AUDITOR = TEST_USERS["municipal_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1/2: program + site + agreement + material + activation
# ---------------------------------------------------------------------------

def setup_program_with_operational_site(program_overrides=None,
                                        site_overrides=None,
                                        material_overrides=None,
                                        agreement_overrides=None,
                                        activate_program=True):
    """Program + site + ACTIVE host agreement + material + commissioned site.

    Order per PRD §3.1/§3.2: commission requires an ACTIVE agreement; the
    program itself is activated after the site is OPERATIONAL.

    Returns dict with prog_id, site_id, agr_id, mat_id.
    """
    prog = get_success_data(api_client.create_program(
        create_program_payload(**(program_overrides or {})), ADMIN))
    prog_id = prog["id"]

    site = get_success_data(api_client.create_site(
        prog_id, create_site_payload(**(site_overrides or {})), ADMIN))
    site_id = site["id"]

    agr = get_success_data(api_client.create_host_agreement(
        prog_id,
        create_host_agreement_payload(site_id, **(agreement_overrides or {})),
        ADMIN))
    agr_id = agr["id"]
    get_success_data(api_client.activate_host_agreement(prog_id, agr_id, ADMIN))

    mat = get_success_data(api_client.create_material(
        prog_id, create_material_payload(**(material_overrides or {})), ADMIN))
    mat_id = mat["id"]

    get_success_data(api_client.commission_site(prog_id, site_id, ADMIN))

    if activate_program:
        get_success_data(api_client.activate_program(prog_id, ADMIN))

    return {"prog_id": prog_id, "site_id": site_id, "agr_id": agr_id,
            "mat_id": mat_id}


def add_operational_site_to_program(prog_id, site_overrides=None,
                                    agreement_overrides=None):
    """Add a second OPERATIONAL site (with its own ACTIVE agreement) to an
    existing program. Useful when a batch-close reconciliation must not touch
    drops at another site. Returns dict with site_id, agr_id."""
    site = get_success_data(api_client.create_site(
        prog_id, create_site_payload(**(site_overrides or {})), ADMIN))
    site_id = site["id"]
    agr = get_success_data(api_client.create_host_agreement(
        prog_id,
        create_host_agreement_payload(site_id, **(agreement_overrides or {})),
        ADMIN))
    agr_id = agr["id"]
    get_success_data(api_client.activate_host_agreement(prog_id, agr_id, ADMIN))
    get_success_data(api_client.commission_site(prog_id, site_id, ADMIN))
    return {"site_id": site_id, "agr_id": agr_id}


# ---------------------------------------------------------------------------
# Tier 2: participant + access grant
# ---------------------------------------------------------------------------

def setup_verified_participant_with_grant(prog_id, site_id,
                                          email="p@x.com",
                                          household_size=1,
                                          grant_overrides=None):
    """Register + verify a participant and issue an ACTIVE grant at site_id.

    Returns dict with part_id, grant_id, part_headers (ownership-threaded).
    """
    reg = get_success_data(api_client.register_participant(
        prog_id,
        register_participant_payload(email=email, household_size=household_size),
        ANON))
    part_id = reg["id"]
    token = reg["verification_token"]
    get_success_data(api_client.verify_participant(
        prog_id, part_id, {"verification_token": token}, ANON))

    grant = get_success_data(api_client.create_grant(
        prog_id, part_id,
        create_grant_payload(site_id, **(grant_overrides or {})), ADMIN))
    grant_id = grant["id"]

    return {"part_id": part_id, "grant_id": grant_id,
            "part_headers": make_participant_headers(part_id)}


# ---------------------------------------------------------------------------
# Tier 3: drop helpers (OCC-threaded)
# ---------------------------------------------------------------------------

def get_site_version(prog_id, site_id):
    site = get_success_data(api_client.get_site(prog_id, site_id, ADMIN))
    return site["version"]


def create_drop_at_site(prog_id, site_id, part_id, grant_id, mat_id,
                        **drop_overrides):
    """Create a drop with the site's current version (OCC per PRD §2.5).

    Returns the DropEvent data dict.
    """
    sv = get_site_version(prog_id, site_id)
    payload = create_drop_payload(
        part_id, grant_id, mat_id, sv, **drop_overrides)
    return get_success_data(api_client.create_drop(
        prog_id, site_id, payload, make_participant_headers(part_id)))


def create_and_accept_drop(prog_id, site_id, part_id, grant_id, mat_id,
                           **drop_overrides):
    """Create a drop and have the SiteHost accept it. Returns drop dict."""
    drop = create_drop_at_site(prog_id, site_id, part_id, grant_id, mat_id,
                               **drop_overrides)
    return get_success_data(api_client.accept_drop(
        prog_id, site_id, drop["id"], HOST))


# ---------------------------------------------------------------------------
# Tier 3/5: route -> stop -> dispatch -> collect -> complete -> batch -> close
# ---------------------------------------------------------------------------

def setup_closed_accepted_batch(prog_id, site_id,
                                planned_pickup_kg,
                                actual_pickup_kg,
                                measured_contamination_kg=0.00,
                                yield_ratio=0.5,
                                reject_threshold_pct=25.0):
    """Partner + route + stop -> dispatch -> collect -> complete -> close batch.

    Returns dict with partner_id, route_id, stop_id, batch (closed data).
    """
    partner = get_success_data(api_client.create_partner(
        prog_id, create_partner_payload(yield_ratio=yield_ratio,
                                        contamination_reject_threshold_pct=reject_threshold_pct),
        ADMIN))
    partner_id = partner["id"]

    route = get_success_data(api_client.create_route(
        prog_id, create_route_payload(partner_id), OPERATOR))
    route_id = route["id"]

    stop = get_success_data(api_client.create_stop(
        prog_id, route_id,
        create_stop_payload(site_id, route["version"],
                            planned_pickup_kg=planned_pickup_kg),
        OPERATOR))
    stop_id = stop["id"]

    get_success_data(api_client.dispatch_route(prog_id, route_id, OPERATOR))
    get_success_data(api_client.collect_stop(
        prog_id, route_id, stop_id, {"actual_pickup_kg": actual_pickup_kg},
        OPERATOR))
    get_success_data(api_client.complete_route(prog_id, route_id, OPERATOR))

    batches, _meta = _list_batch_data(prog_id, partner_id)
    batch_id = batches[0]["id"]
    batch = get_success_data(api_client.close_batch(
        prog_id, partner_id, batch_id,
        {"measured_contamination_kg": measured_contamination_kg},
        make_processing_partner_headers(partner_id)))

    return {"partner_id": partner_id, "route_id": route_id,
            "stop_id": stop_id, "batch": batch, "batch_id": batch_id}


def _list_batch_data(prog_id, partner_id):
    """Lenient list of batches; returns (data_list, meta)."""
    resp = api_client.list_batches(prog_id, partner_id, ADMIN)
    body = get_success_data(resp)
    if isinstance(body, list):
        return body, resp.json().get("meta", {})
    return body.get("data", body), resp.json().get("meta", {})


def setup_open_distribution(prog_id, site_id, part_id, grant_id, mat_id,
                            drop_gross_kg=10.00, drop_contamination_kg=0.00,
                            yield_ratio=1.0, measured_contamination_kg=0.00):
    """Full chain: accepted drop -> collected route -> CLOSED_ACCEPTED batch
    -> OPEN distribution. Returns dict with ids and the distribution."""
    create_and_accept_drop(prog_id, site_id, part_id, grant_id, mat_id,
                           gross_weight_kg=drop_gross_kg,
                           contamination_kg=drop_contamination_kg)
    chain = setup_closed_accepted_batch(
        prog_id, site_id,
        planned_pickup_kg=int(drop_gross_kg),
        actual_pickup_kg=drop_gross_kg,
        measured_contamination_kg=measured_contamination_kg,
        yield_ratio=yield_ratio)
    dist = get_success_data(api_client.create_distribution(
        prog_id, {"batch_id": chain["batch_id"]}, ADMIN))
    return {**chain, "dist": dist, "dist_id": dist["id"],
            "dist_version": dist["version"]}
