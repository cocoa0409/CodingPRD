"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly started server with an empty
database). Setup calls use get_success_data() so a setup failure surfaces a
clear "Setup step failed" error instead of a confusing assertion failure.

Identity threading: Claimant is entity-backed, so claim operations use
make_claimant_headers(claimant["id"]). Operator roles are opaque; callers pass
explicit user ids wherever segregation-of-duties rules compare them.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AFTER_EVENT_END,
    EVENT_ENDS_AT,
    EVENT_STARTS_AT,
    FOUND_AT,
    OPERATOR_IDS,
)
from .factories import (
    create_auction_event_payload,
    create_auction_lot_payload,
    create_claim_payload,
    create_claimant_payload,
    create_inquiry_payload,
    create_item_payload,
    create_program_payload,
    create_referral_payload,
    create_release_payload,
    create_resubmit_payload,
    create_retention_policy_payload,
    create_storage_location_payload,
    create_venue_payload,
)
from .test_users import (
    TEST_USERS,
    make_claimant_headers,
    make_claims_examiner_headers,
    make_intake_officer_headers,
    make_police_liaison_headers,
    make_property_custodian_headers,
    make_release_officer_headers,
    make_auction_coordinator_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD_1 = OPERATOR_IDS["coordinator"]
COORD_2 = OPERATOR_IDS["coordinator_other"]
INTAKE_1 = OPERATOR_IDS["intake_officer"]
CUSTODIAN_1 = OPERATOR_IDS["custodian"]
EXAMINER_1 = OPERATOR_IDS["examiner"]
RELEASE_1 = OPERATOR_IDS["release_officer"]
LIAISON_1 = OPERATOR_IDS["liaison"]


# ─── Clock and sweep ─────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_retention_sweep():
    return get_success_data(api_client.run_retention_sweep(ADMIN))


def advance_clock_and_sweep(to_iso8601: str):
    set_clock(to_iso8601)
    return run_retention_sweep()


# ─── Programs / policies / storage / venues ──────────────────────────────────

def create_program(program_type: str = "TRANSIT", name: str | None = None):
    payload = create_program_payload(
        program_type=program_type,
        name=name or f"{program_type.title()} L&F",
        contact_email=f"{program_type.lower()}@city.gov",
    )
    return get_success_data(api_client.create_program(payload, ADMIN))


def get_program(program_id: str):
    return get_success_data(api_client.get_program(program_id, ADMIN))


def create_policy(program_id: str, *, item_category="ELECTRONICS",
                  value_tier="LOW", retention_days=10, disposal_method="AUCTION",
                  expected_version=None):
    """Create a retention policy. When expected_version is None the program's
    current version is read first (policy creation bumps the program version)."""
    if expected_version is None:
        expected_version = get_program(program_id)["version"]
    payload = create_retention_policy_payload(
        program_id, expected_version,
        item_category=item_category, value_tier=value_tier,
        retention_days=retention_days, disposal_method=disposal_method,
    )
    return get_success_data(api_client.create_retention_policy(payload, ADMIN))


def create_location(program_id: str, *, name="Cage T", capacity_slots=10,
                    supports_high_value=True):
    payload = create_storage_location_payload(
        program_id, name=name, capacity_slots=capacity_slots,
        supports_high_value=supports_high_value)
    return get_success_data(api_client.create_storage_location(payload, ADMIN))


def get_location(location_id: str):
    return get_success_data(api_client.get_storage_location(location_id, ADMIN))


def create_venue(program_id: str, *, name="Depot Hall", address="1 Depot St",
                 insurance_cap_cents=100000000):
    payload = create_venue_payload(
        program_id, name=name, address=address,
        insurance_cap_cents=insurance_cap_cents)
    return get_success_data(api_client.create_venue(payload, ADMIN))


def setup_program_policy_location(*, program_type="TRANSIT",
                                  item_category="ELECTRONICS", value_tier="LOW",
                                  retention_days=10, disposal_method="AUCTION",
                                  location_name="Cage T", capacity_slots=10,
                                  supports_high_value=True):
    """Program + one active retention policy + one storage location."""
    program = create_program(program_type)
    policy = create_policy(
        program["id"], item_category=item_category, value_tier=value_tier,
        retention_days=retention_days, disposal_method=disposal_method)
    location = create_location(
        program["id"], name=location_name, capacity_slots=capacity_slots,
        supports_high_value=supports_high_value)
    return SimpleNamespace(program=program, policy=policy, location=location)


# ─── Items ───────────────────────────────────────────────────────────────────

def create_item(program_id: str, location_id: str, *, category="ELECTRONICS",
                declared_value_cents=5000, description="earbuds",
                found_at=FOUND_AT, found_location="Bus 12",
                intake_officer_id=INTAKE_1, extra=None):
    payload = create_item_payload(
        program_id, location_id, category=category,
        declared_value_cents=declared_value_cents, description=description,
        found_at=found_at, found_location=found_location)
    if extra:
        payload.update(extra)
    return get_success_data(api_client.create_item(
        payload, make_intake_officer_headers(intake_officer_id)))


def get_item(item_id: str):
    return get_success_data(api_client.get_item(item_id, ADMIN))


def publish_item(item_id: str, officer_id=INTAKE_1):
    return get_success_data(api_client.publish_item(
        item_id, make_intake_officer_headers(officer_id)))


def setup_stored_item(*, program_type="TRANSIT", item_category="ELECTRONICS",
                      value_tier="LOW", retention_days=10,
                      disposal_method="AUCTION", declared_value_cents=5000,
                      capacity_slots=10, supports_high_value=True,
                      intake_officer_id=INTAKE_1, found_at=FOUND_AT,
                      description="earbuds"):
    """Program + policy + location + one item in STORED status."""
    base = setup_program_policy_location(
        program_type=program_type, item_category=item_category,
        value_tier=value_tier, retention_days=retention_days,
        disposal_method=disposal_method, capacity_slots=capacity_slots,
        supports_high_value=supports_high_value)
    item = create_item(
        base.program["id"], base.location["id"], category=item_category,
        declared_value_cents=declared_value_cents, description=description,
        intake_officer_id=intake_officer_id, found_at=found_at)
    return SimpleNamespace(**vars(base), item=item)


def make_item_auction_eligible(item_id: str, sweep_clock="2026-08-11T09:00:00Z"):
    """Advance the logical clock to sweep_clock and run the retention sweep;
    returns the refreshed item (AUCTION_ELIGIBLE for AUCTION policies)."""
    advance_clock_and_sweep(sweep_clock)
    return get_item(item_id)


def setup_auction_eligible_item(*, declared_value_cents=5005, value_tier="LOW",
                                retention_days=10, disposal_method="AUCTION",
                                program_type="TRANSIT",
                                sweep_clock="2026-08-11T09:00:00Z",
                                found_at=FOUND_AT, description="earbuds"):
    """Full chain to one AUCTION_ELIGIBLE item under a fresh program."""
    ctx = setup_stored_item(
        program_type=program_type, value_tier=value_tier,
        retention_days=retention_days, disposal_method=disposal_method,
        declared_value_cents=declared_value_cents, found_at=found_at,
        description=description)
    item = make_item_auction_eligible(ctx.item["id"], sweep_clock)
    return SimpleNamespace(**{**vars(ctx), "item": item})


# ─── Claimants and claims ────────────────────────────────────────────────────

def create_claimant(full_name="Pat Owner", email="pat@x.com", **extra):
    return get_success_data(api_client.create_claimant(
        create_claimant_payload(full_name=full_name, email=email, **extra),
        TEST_USERS["public_user_headers"]))


def get_claim(claim_id: str):
    return get_success_data(api_client.get_claim(claim_id, TEST_USERS["claims_examiner_headers"]))


def create_claim(item_id: str, claimant_id: str, *, proof_serial=True,
                 proof_photo=False, proof_receipt=False,
                 proof_description_detail="BRIEF", expected_item_version=None):
    """File a claim. When expected_item_version is None the item's current
    version is read first (fresh OCC version)."""
    if expected_item_version is None:
        expected_item_version = get_item(item_id)["version"]
    payload = create_claim_payload(
        item_id, claimant_id, expected_item_version,
        proof_serial=proof_serial, proof_photo=proof_photo,
        proof_receipt=proof_receipt,
        proof_description_detail=proof_description_detail)
    return get_success_data(api_client.create_claim(
        payload, make_claimant_headers(claimant_id)))


def start_review(claim_id: str, examiner_id=EXAMINER_1):
    return get_success_data(api_client.start_claim_review(
        claim_id, make_claims_examiner_headers(examiner_id)))


def request_info(claim_id: str, text="need receipt", examiner_id=EXAMINER_1):
    return get_success_data(api_client.request_claim_info(
        claim_id, text, make_claims_examiner_headers(examiner_id)))


def resubmit_claim(claim_id: str, claimant_id: str, **proof_overrides):
    payload = create_resubmit_payload(**proof_overrides)
    return get_success_data(api_client.resubmit_claim(
        claim_id, payload, make_claimant_headers(claimant_id)))


def approve_claim(claim_id: str, examiner_id=EXAMINER_1):
    return get_success_data(api_client.approve_claim(
        claim_id, make_claims_examiner_headers(examiner_id)))


def setup_claim_under_review(*, declared_value_cents=5000, value_tier="LOW",
                             retention_days=10, disposal_method="AUCTION",
                             proof_serial=True, proof_photo=False,
                             proof_receipt=False, proof_description_detail="BRIEF",
                             examiner_id=EXAMINER_1, intake_officer_id=INTAKE_1):
    """Item STORED + claimant + claim moved to UNDER_REVIEW by examiner_id."""
    ctx = setup_stored_item(
        value_tier=value_tier, retention_days=retention_days,
        disposal_method=disposal_method, declared_value_cents=declared_value_cents,
        intake_officer_id=intake_officer_id)
    claimant = create_claimant()
    claim = create_claim(
        ctx.item["id"], claimant["id"],
        proof_serial=proof_serial, proof_photo=proof_photo,
        proof_receipt=proof_receipt,
        proof_description_detail=proof_description_detail)
    claim = start_review(claim["id"], examiner_id)
    return SimpleNamespace(**vars(ctx), claimant=claimant, claim=claim,
                           examiner_id=examiner_id,
                           intake_officer_id=intake_officer_id)


def setup_approved_claim(*, declared_value_cents=5000, value_tier="LOW",
                         proof_serial=True, proof_photo=True,
                         proof_receipt=False, proof_description_detail="BRIEF",
                         examiner_id=EXAMINER_1, intake_officer_id=INTAKE_1):
    """Claim APPROVED and item cascaded to RELEASE_PENDING."""
    ctx = setup_claim_under_review(
        declared_value_cents=declared_value_cents, value_tier=value_tier,
        proof_serial=proof_serial, proof_photo=proof_photo,
        proof_receipt=proof_receipt,
        proof_description_detail=proof_description_detail,
        examiner_id=examiner_id, intake_officer_id=intake_officer_id)
    claim = approve_claim(ctx.claim["id"], examiner_id)
    return SimpleNamespace(**{**vars(ctx), "claim": claim})


# ─── Inquiries ───────────────────────────────────────────────────────────────

def create_inquiry(**overrides):
    return get_success_data(api_client.create_inquiry(
        create_inquiry_payload(**overrides), TEST_USERS["public_user_headers"]))


# ─── Law-enforcement referrals ───────────────────────────────────────────────

def refer_item(item_id: str, *, agency_name="CPD", case_number="C-100",
               liaison_id=LIAISON_1):
    return get_success_data(api_client.refer_item_to_law_enforcement(
        item_id, create_referral_payload(agency_name=agency_name,
                                         case_number=case_number),
        make_police_liaison_headers(liaison_id)))


def confirm_pickup(referral_id: str, liaison_id=LIAISON_1):
    return get_success_data(api_client.confirm_pickup(
        referral_id, make_police_liaison_headers(liaison_id)))


def return_to_custody(referral_id: str, liaison_id=LIAISON_1):
    return get_success_data(api_client.return_to_custody(
        referral_id, make_police_liaison_headers(liaison_id)))


def convert_to_evidence(referral_id: str, liaison_id=LIAISON_1):
    return get_success_data(api_client.convert_to_evidence(
        referral_id, make_police_liaison_headers(liaison_id)))


def setup_item_in_le_custody(**item_kwargs):
    """Item referred and picked up: referral IN_CUSTODY, item IN_LE_CUSTODY."""
    ctx = setup_stored_item(**item_kwargs)
    referral = refer_item(ctx.item["id"])
    referral = confirm_pickup(referral["id"])
    item = get_item(ctx.item["id"])
    return SimpleNamespace(**{**vars(ctx), "referral": referral, "item": item})


# ─── Auction events and lots ─────────────────────────────────────────────────

def create_event(program_id: str, venue_id: str, *, name="Aug Sale",
                 starts_at=EVENT_STARTS_AT, ends_at=EVENT_ENDS_AT,
                 coordinator_id=COORD_1):
    payload = create_auction_event_payload(
        venue_id, program_id, name=name, starts_at=starts_at, ends_at=ends_at)
    return get_success_data(api_client.create_auction_event(
        payload, make_auction_coordinator_headers(coordinator_id)))


def get_event(event_id: str):
    return get_success_data(api_client.get_auction_event(event_id, ADMIN))


def create_lot(event_id: str, *, title="Lot A", coordinator_id=COORD_1):
    return get_success_data(api_client.create_auction_lot(
        create_auction_lot_payload(event_id, title=title),
        make_auction_coordinator_headers(coordinator_id)))


def get_lot(lot_id: str):
    return get_success_data(api_client.get_auction_lot(
        lot_id, make_auction_coordinator_headers(COORD_1)))


def add_lot_item(lot_id: str, item_id: str, *, coordinator_id=COORD_1,
                 expected_lot_version=None):
    """Add an item to a DRAFT lot. When expected_lot_version is None the lot's
    current version is read first (fresh OCC version)."""
    if expected_lot_version is None:
        expected_lot_version = get_lot(lot_id)["version"]
    return get_success_data(api_client.add_lot_item(
        lot_id, item_id, expected_lot_version,
        make_auction_coordinator_headers(coordinator_id)))


def publish_lot(lot_id: str, coordinator_id=COORD_1):
    return get_success_data(api_client.publish_lot(
        lot_id, make_auction_coordinator_headers(coordinator_id)))


def setup_event_with_lot(program_id: str, *, coordinator_id=COORD_1,
                         venue_cap=100000000, starts_at=EVENT_STARTS_AT,
                         ends_at=EVENT_ENDS_AT, lot_title="Lot A"):
    """Venue + SCHEDULED event + one empty DRAFT lot."""
    venue = create_venue(program_id, insurance_cap_cents=venue_cap)
    event = create_event(program_id, venue["id"], starts_at=starts_at,
                         ends_at=ends_at, coordinator_id=coordinator_id)
    lot = create_lot(event["id"], title=lot_title, coordinator_id=coordinator_id)
    return SimpleNamespace(venue=venue, event=event, lot=lot)


def setup_lot_with_eligible_item(*, declared_value_cents=5005,
                                 value_tier="LOW", retention_days=10,
                                 coordinator_id=COORD_1, venue_cap=100000000,
                                 sweep_clock="2026-08-11T09:00:00Z"):
    """AUCTION_ELIGIBLE item + venue/event + DRAFT lot + item added (LOTTED)."""
    ctx = setup_auction_eligible_item(
        declared_value_cents=declared_value_cents, value_tier=value_tier,
        retention_days=retention_days, sweep_clock=sweep_clock)
    auction = setup_event_with_lot(
        ctx.program["id"], coordinator_id=coordinator_id, venue_cap=venue_cap)
    lot_item = add_lot_item(auction.lot["id"], ctx.item["id"],
                            coordinator_id=coordinator_id)
    item = get_item(ctx.item["id"])
    return SimpleNamespace(**{**vars(ctx), **vars(auction),
                              "lot_item": lot_item, "item": item})


def setup_published_lot_with_item(**kwargs):
    """DRAFT lot with one lotted item, then published (PUBLISHED)."""
    ctx = setup_lot_with_eligible_item(**kwargs)
    lot = publish_lot(ctx.lot["id"], kwargs.get("coordinator_id", COORD_1))
    return SimpleNamespace(**{**vars(ctx), "lot": lot})


def finalize_lot(lot_id: str, hammer_price_cents: int, coordinator_id=COORD_2):
    return get_success_data(api_client.finalize_lot_sale(
        lot_id, hammer_price_cents,
        make_auction_coordinator_headers(coordinator_id)))


def settle_event(event_id: str, coordinator_id=COORD_1):
    return get_success_data(api_client.settle_auction_event(
        event_id, make_auction_coordinator_headers(coordinator_id)))


def release_item(item_id: str, *, handover_method="IN_PERSON",
                 id_document_ref="DL-999", release_officer_id=RELEASE_1):
    return get_success_data(api_client.release_item(
        item_id,
        create_release_payload(handover_method=handover_method,
                               id_document_ref=id_document_ref),
        make_release_officer_headers(release_officer_id)))
