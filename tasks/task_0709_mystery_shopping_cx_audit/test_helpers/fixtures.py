"""Composite setup helpers.

Each individual pytest test runs against a freshly-launched, empty database, so
every fixture builds its preconditions from scratch using only PRD-declared
endpoints. Fixtures use get_success_data() (lenient) internally so a setup failure
surfaces clearly as a "Setup failed" rather than a confusing assertion error.

Identity threading: after creating an entity_backed entity (ClientAccount,
Shopper), ownership-gated calls use make_<role>_headers(entity_id) with the real
id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_platform_admin_headers,
    make_qa_validator_headers,
    make_finance_officer_headers,
    make_anonymous_headers,
    make_client_manager_headers,
    make_shopper_headers,
)
from . import factories
from . import assertions


# Standard clock anchor used across time-sensitive setups (within the default
# June 2026 wave window). Tests that need a different instant pass clock_iso.
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
DEFAULT_WINDOW_START = "2026-06-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-06-30T00:00:00Z"


# --- Low-level primitives --------------------------------------------------
def set_clock(to_iso8601):
    """Set the logical clock as PlatformAdmin."""
    return get_success_data(
        api_client.set_clock(to_iso8601, make_platform_admin_headers())
    )


def register_client(fee_per_completed_shop_cents=15000, **overrides):
    """Public self-registration of an ACTIVE ClientAccount. Returns the client dict."""
    payload = factories.create_client_payload(
        fee_per_completed_shop_cents=fee_per_completed_shop_cents, **overrides
    )
    return get_success_data(api_client.create_client(payload, make_anonymous_headers()))


def register_shopper(tax_id_on_file=None, home_lat=40.0, home_lng=-74.0, **overrides):
    """Public self-registration of a REGISTERED Shopper. Returns the shopper dict."""
    payload = factories.create_shopper_payload(home_lat=home_lat, home_lng=home_lng, **overrides)
    if tax_id_on_file is not None:
        payload["tax_id_on_file"] = tax_id_on_file
    return get_success_data(api_client.create_shopper(payload, make_anonymous_headers()))


def certify_shopper(shopper_id, raw_score=90, scenario_family="RETAIL", qa_user_id=None):
    """Record a PASSED certification attempt, certifying the shopper in a family."""
    headers = make_qa_validator_headers(qa_user_id) if qa_user_id else make_qa_validator_headers()
    payload = factories.create_certification_payload(
        raw_score=raw_score, scenario_family=scenario_family
    )
    return get_success_data(
        api_client.create_certification_attempt(shopper_id, payload, headers)
    )


def create_location(client_id, scenario_family="RETAIL", lat=40.5, lng=-74.5, label="Store"):
    cm = make_client_manager_headers(client_id)
    payload = factories.create_location_payload(
        label=label, lat=lat, lng=lng, scenario_family=scenario_family
    )
    return get_success_data(api_client.create_location(client_id, payload, cm))


def create_and_publish_script(client_id, scenario_family="RETAIL",
                              weights_json=None, required_photo_count=1,
                              receipt_required=False, reimburse_cap_cents=5000,
                              base_fee_cents=2000, passing_score=70):
    """Create a DRAFT script and publish it. Returns the published script dict."""
    cm = make_client_manager_headers(client_id)
    if weights_json is None:
        weights_json = {"greeting": 1.0}
    payload = factories.create_script_payload(
        scenario_family=scenario_family,
        weights_json=weights_json,
        required_photo_count=required_photo_count,
        receipt_required=receipt_required,
        reimburse_cap_cents=reimburse_cap_cents,
        base_fee_cents=base_fee_cents,
        passing_score=passing_score,
    )
    script = get_success_data(api_client.create_script(client_id, payload, cm))
    get_success_data(api_client.publish_script(script["id"], cm))
    return script


def create_and_publish_wave(client_id, window_start=DEFAULT_WINDOW_START,
                            window_end=DEFAULT_WINDOW_END, rotation_cooldown_days=30,
                            name="Wave"):
    """Create a DRAFT wave and publish it. Returns the published wave dict."""
    cm = make_client_manager_headers(client_id)
    payload = factories.create_wave_payload(
        name=name, field_window_start=window_start, field_window_end=window_end,
        rotation_cooldown_days=rotation_cooldown_days,
    )
    wave = get_success_data(api_client.create_wave(client_id, payload, cm))
    get_success_data(api_client.publish_wave(wave["id"], cm))
    return wave


# --- Tier 2: catalog scaffolding ------------------------------------------
def setup_catalog(scenario_family="RETAIL", fee_per_completed_shop_cents=15000,
                  loc_lat=40.5, loc_lng=-74.5, weights_json=None,
                  required_photo_count=1, receipt_required=False,
                  reimburse_cap_cents=5000, base_fee_cents=2000,
                  rotation_cooldown_days=30, window_start=DEFAULT_WINDOW_START,
                  window_end=DEFAULT_WINDOW_END, passing_score=70,
                  clock_iso=DEFAULT_CLOCK):
    """Full client catalog: clock set, ACTIVE client, ACTIVE location, PUBLISHED
    script and PUBLISHED wave. Returns a dict with client, location, script, wave.
    """
    if clock_iso is not None:
        set_clock(clock_iso)
    client = register_client(fee_per_completed_shop_cents=fee_per_completed_shop_cents)
    cid = client["id"]
    location = create_location(cid, scenario_family=scenario_family, lat=loc_lat, lng=loc_lng)
    script = create_and_publish_script(
        cid, scenario_family=scenario_family, weights_json=weights_json,
        required_photo_count=required_photo_count, receipt_required=receipt_required,
        reimburse_cap_cents=reimburse_cap_cents, base_fee_cents=base_fee_cents,
        passing_score=passing_score,
    )
    wave = create_and_publish_wave(
        cid, window_start=window_start, window_end=window_end,
        rotation_cooldown_days=rotation_cooldown_days,
    )
    return {"client": client, "location": location, "script": script, "wave": wave}


def setup_catalog_with_shopper(home_lat=40.0, home_lng=-74.0, tax_id_on_file=True,
                               qa_user_id=None, **catalog_kwargs):
    """setup_catalog + a CERTIFIED shopper (certified in the catalog's family).
    Returns a dict with client, location, script, wave, shopper.
    """
    family = catalog_kwargs.get("scenario_family", "RETAIL")
    cat = setup_catalog(**catalog_kwargs)
    shopper = register_shopper(
        tax_id_on_file=tax_id_on_file, home_lat=home_lat, home_lng=home_lng
    )
    certify_shopper(shopper["id"], scenario_family=family, qa_user_id=qa_user_id)
    cat["shopper"] = shopper
    return cat


# --- Tier 3: assignment lifecycle shortcuts -------------------------------
def create_assignment(client_id, wave_id, shopper_id, location_id, script_id, due_at):
    cm = make_client_manager_headers(client_id)
    payload = factories.create_assignment_payload(
        wave_id, shopper_id, location_id, script_id, due_at
    )
    return get_success_data(api_client.create_assignment(payload, cm))


def add_approved_photo(assignment_id, shopper_id, object_uri="s3://e/p.jpg",
                       section_key=None, qa_user_id=None):
    """Upload a PHOTO and approve it. Returns the evidence id."""
    sh = make_shopper_headers(shopper_id)
    qa = make_qa_validator_headers(qa_user_id) if qa_user_id else make_qa_validator_headers()
    ev_payload = factories.create_evidence_payload("PHOTO", object_uri)
    if section_key is not None:
        ev_payload["section_key"] = section_key
    ev = get_success_data(api_client.upload_evidence(assignment_id, ev_payload, sh))
    get_success_data(api_client.review_evidence(ev["id"], {"decision": "APPROVE"}, qa))
    return ev["id"]


def add_reviewed_evidence(assignment_id, shopper_id, kind, decision,
                          object_uri="s3://e/x.jpg", receipt_amount_cents=None,
                          section_key=None, qa_user_id=None):
    """Upload an evidence item of `kind` and apply `decision` (APPROVE/FLAG).
    Returns the evidence id."""
    sh = make_shopper_headers(shopper_id)
    qa = make_qa_validator_headers(qa_user_id) if qa_user_id else make_qa_validator_headers()
    ev_payload = factories.create_evidence_payload(kind, object_uri)
    if receipt_amount_cents is not None:
        ev_payload["receipt_amount_cents"] = receipt_amount_cents
    if section_key is not None:
        ev_payload["section_key"] = section_key
    ev = get_success_data(api_client.upload_evidence(assignment_id, ev_payload, sh))
    get_success_data(api_client.review_evidence(ev["id"], {"decision": decision}, qa))
    return ev["id"]


def create_scorecard(assignment_id, shopper_id, section_scores_json):
    sh = make_shopper_headers(shopper_id)
    payload = factories.create_scorecard_payload(section_scores_json)
    return get_success_data(api_client.create_scorecard(assignment_id, payload, sh))


def create_in_field_assignment(client_id, wave_id, shopper_id, location_id,
                               script_id, due_at):
    """Create an assignment and accept it (ASSIGNED -> IN_FIELD). Returns assignment dict."""
    asg = create_assignment(client_id, wave_id, shopper_id, location_id, script_id, due_at)
    sh = make_shopper_headers(shopper_id)
    return get_success_data(api_client.accept_assignment(asg["id"], sh))


def setup_submitted_assignment(due_at="2026-06-20T00:00:00Z",
                               section_scores_json=None,
                               required_photo_count=1, receipt_required=False,
                               weights_json=None, base_fee_cents=2000,
                               reimburse_cap_cents=5000, fee_per_completed_shop_cents=15000,
                               qa_user_id=None, **catalog_overrides):
    """Build a full catalog + certified shopper + one assignment driven to SUBMITTED
    with one APPROVED photo and a scorecard. Returns a dict with client, location,
    script, wave, shopper, assignment.

    section_scores_json defaults to {greeting: 88}; weights default to {greeting: 1.0}.
    """
    if weights_json is None:
        weights_json = {"greeting": 1.0}
    if section_scores_json is None:
        section_scores_json = {"greeting": 88}
    cat = setup_catalog_with_shopper(
        weights_json=weights_json, required_photo_count=required_photo_count,
        receipt_required=receipt_required, base_fee_cents=base_fee_cents,
        reimburse_cap_cents=reimburse_cap_cents,
        fee_per_completed_shop_cents=fee_per_completed_shop_cents,
        qa_user_id=qa_user_id, **catalog_overrides,
    )
    shopper_id = cat["shopper"]["id"]
    asg = create_in_field_assignment(
        cat["client"]["id"], cat["wave"]["id"], shopper_id,
        cat["location"]["id"], cat["script"]["id"], due_at,
    )
    if required_photo_count >= 1:
        add_approved_photo(asg["id"], shopper_id, qa_user_id=qa_user_id)
    create_scorecard(asg["id"], shopper_id, section_scores_json)
    sh = make_shopper_headers(shopper_id)
    submitted = get_success_data(api_client.submit_assignment(asg["id"], sh))
    cat["assignment"] = submitted
    return cat


def setup_validated_assignment(due_at="2026-06-20T00:00:00Z", qa_user_id=None,
                               **kwargs):
    """setup_submitted_assignment driven one step further to VALIDATED. Returns the
    same dict with assignment in VALIDATED state."""
    cat = setup_submitted_assignment(due_at=due_at, qa_user_id=qa_user_id, **kwargs)
    qa = make_qa_validator_headers(qa_user_id) if qa_user_id else make_qa_validator_headers()
    validated = get_success_data(api_client.validate_assignment(cat["assignment"]["id"], qa))
    cat["assignment"] = validated
    return cat


def get_assignment_reimbursement(assignment_id):
    """Return the (single) reimbursement dict for an assignment, or None."""
    data = get_success_data(
        api_client.get_assignment_reimbursement(assignment_id, make_finance_officer_headers())
    )
    if isinstance(data, list):
        return data[0] if data else None
    return data


def setup_batched_reimbursement(due_at="2026-06-10T00:00:00Z", finance_user_id=None,
                                **kwargs):
    """Validated assignment -> ACCRUED reimbursement collected into an OPEN batch.
    Returns dict with all catalog entities plus reimbursement and batch.
    """
    cat = setup_validated_assignment(due_at=due_at, **kwargs)
    reimb = get_assignment_reimbursement(cat["assignment"]["id"])
    fo = make_finance_officer_headers(finance_user_id) if finance_user_id else make_finance_officer_headers()
    batch = get_success_data(api_client.create_payout_batch(
        {"shopper_id": cat["shopper"]["id"], "reimbursement_ids": [reimb["id"]]}, fo
    ))
    cat["reimbursement"] = reimb
    cat["batch"] = batch
    return cat
