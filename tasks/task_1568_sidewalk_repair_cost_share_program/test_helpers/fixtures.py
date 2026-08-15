"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: PropertyOwner and Contractor calls are entity-backed, so
every ownership-gated call uses headers built from the real entity id via
make_owner_headers / make_contractor_headers. The five city-staff roles are
opaque and use the shared constants (coord-1, insp-1, insp-2, fin-1, for-1,
hear-1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_adjustment_payload,
    create_appeal_decision_payload,
    create_appeal_payload,
    create_application_payload,
    create_batch_payload,
    create_bid_payload,
    create_contractor_payload,
    create_cycle_payload,
    create_defect_payload,
    create_forestry_decision_payload,
    create_inspection_payload,
    create_lien_payload,
    create_notice_payload,
    create_owner_payload,
    create_parcel_payload,
    create_payment_payload,
    create_segment_payload,
    create_work_item_payload,
)
from .test_users import TEST_USERS, make_contractor_headers, make_owner_headers

COORD = TEST_USERS["coordinator_headers"]
COORD2 = TEST_USERS["coordinator2_headers"]
INSP1 = TEST_USERS["inspector_headers"]
INSP2 = TEST_USERS["inspector2_headers"]
FORESTRY = TEST_USERS["forestry_headers"]
FINANCE = TEST_USERS["finance_headers"]
HEARING = TEST_USERS["hearing_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Drive the logical clock. Returns the server's current_utc."""
    return get_success_data(api_client.set_clock(to_iso8601, COORD))


def make_cycle(appropriation_cents=10_000_000, cycle_year=2026,
               window_start_date="2026-01-01", window_end_date="2026-12-31"):
    return get_success_data(api_client.create_program_cycle(
        create_cycle_payload(cycle_year, window_start_date, window_end_date,
                             appropriation_cents), COORD))


def make_owner(full_name="Test Owner", mailing_address="1 Main St",
               hardship_tier=None):
    return get_success_data(api_client.create_property_owner(
        create_owner_payload(full_name, mailing_address, hardship_tier), COORD))


def make_parcel(owner_id, parcel_number="P-100", street_address="1 Main St",
                street_class="LOCAL", is_corner_lot=None, is_city_owned=None):
    return get_success_data(api_client.create_parcel(
        create_parcel_payload(owner_id, parcel_number, street_address,
                              street_class, is_corner_lot, is_city_owned),
        COORD))


def make_segment(parcel_id, segment_code="S-100-1", length_ft=20, width_ft=5,
                 is_corner_segment=None, has_existing_curb_ramp=None,
                 headers=None):
    return get_success_data(api_client.create_segment(
        create_segment_payload(parcel_id, segment_code, length_ft, width_ft,
                               is_corner_segment, has_existing_curb_ramp),
        headers or INSP1))


def make_defect(segment_id, defect_type="SPALLING", area_sqft=20,
                measured_offset_inches=None, city_tree_involved=None,
                headers=None):
    return get_success_data(api_client.create_defect(
        create_defect_payload(segment_id, defect_type, area_sqft,
                              measured_offset_inches, city_tree_involved),
        headers or INSP1))


def make_contractor(company_name="Acme Paving", license_number="L-001",
                    insurance_valid_until="2026-12-31"):
    return get_success_data(api_client.create_contractor(
        create_contractor_payload(company_name, license_number,
                                  insurance_valid_until), COORD))


def make_draft_notice(parcel_id, defect_ids, base_deadline_days=None,
                      prior_notice_id=None):
    return get_success_data(api_client.create_repair_notice(
        create_notice_payload(parcel_id, defect_ids, base_deadline_days,
                              prior_notice_id), COORD))


def issue_notice(notice_id):
    return get_success_data(api_client.issue_repair_notice(notice_id, COORD))


def make_batch(neighborhood_code="NB-1", work_window_start="2026-09-25",
               work_window_end="2026-10-15",
               bid_deadline="2026-09-22T00:00:00Z"):
    return get_success_data(api_client.create_bid_batch(
        create_batch_payload(neighborhood_code, work_window_start,
                             work_window_end, bid_deadline), COORD))


def make_work_item(batch_id, notice_id, scope_sqft=50,
                   engineer_unit_rate_cents=1300):
    return get_success_data(api_client.create_work_item(
        create_work_item_payload(batch_id, notice_id, scope_sqft,
                                 engineer_unit_rate_cents), COORD))


def make_bid(batch_id, contractor_id, expected_batch_version,
             unit_rate_cents=1000, ramp_flat_fee_cents=0):
    return get_success_data(api_client.create_bid(
        create_bid_payload(batch_id, expected_batch_version, unit_rate_cents,
                           ramp_flat_fee_cents),
        make_contractor_headers(contractor_id)))


def get_batch_version(batch_id):
    return get_success_data(api_client.get_bid_batch(batch_id, COORD))["version"]


def get_forestry_review_id(defect_id):
    rows = get_success_data(
        api_client.list_defect_forestry_reviews(defect_id, FORESTRY))
    assert isinstance(rows, list) and len(rows) == 1, \
        "expected exactly one auto-created forestry review"
    return rows[0]["id"]


# ---------------------------------------------------------------------------
# Tier 2: inventory + notice chains
# ---------------------------------------------------------------------------

def setup_inventory(parcel_number="P-100", segment_code="S-100-1",
                    street_class="LOCAL", hardship_tier=None,
                    defect_type="SPALLING", area_sqft=20,
                    measured_offset_inches=None, city_tree_involved=None,
                    is_corner_lot=None, is_city_owned=None,
                    is_corner_segment=None, has_existing_curb_ramp=None,
                    owner_name="Test Owner", street_address="1 Main St"):
    """Owner + parcel + segment + defect. Returns the bundle."""
    owner = make_owner(owner_name, street_address, hardship_tier)
    parcel = make_parcel(owner["id"], parcel_number, street_address,
                         street_class, is_corner_lot, is_city_owned)
    segment = make_segment(parcel["id"], segment_code,
                           is_corner_segment=is_corner_segment,
                           has_existing_curb_ramp=has_existing_curb_ramp)
    defect = make_defect(segment["id"], defect_type, area_sqft,
                         measured_offset_inches, city_tree_involved)
    return {"owner": owner, "parcel": parcel, "segment": segment,
            "defect": defect}


def setup_issued_notice(base_deadline_days=None, prior_notice_id=None,
                        **inventory_kwargs):
    """Inventory + DRAFT notice + issue. Bundle gains 'notice' (ISSUED)."""
    bundle = setup_inventory(**inventory_kwargs)
    notice = make_draft_notice(
        bundle["parcel"]["id"], [bundle["defect"]["id"]],
        base_deadline_days=base_deadline_days,
        prior_notice_id=prior_notice_id)
    bundle["notice"] = issue_notice(notice["id"])
    return bundle


def setup_two_defect_issued_notice(parcel_number="P-200",
                                   segment_code="S-200-1",
                                   defect_specs=None):
    """One segment with two defects, both covered by one ISSUED notice."""
    if defect_specs is None:
        defect_specs = [
            {"defect_type": "SPALLING", "area_sqft": 20},
            {"defect_type": "SETTLEMENT", "area_sqft": 12},
        ]
    owner = make_owner("Two Defect Owner", "2 Two St")
    parcel = make_parcel(owner["id"], parcel_number, "2 Two St", "LOCAL")
    segment = make_segment(parcel["id"], segment_code)
    defects = [make_defect(segment["id"], **spec) for spec in defect_specs]
    notice = make_draft_notice(parcel["id"], [d["id"] for d in defects])
    notice = issue_notice(notice["id"])
    return {"owner": owner, "parcel": parcel, "segment": segment,
            "defects": defects, "notice": notice}


# ---------------------------------------------------------------------------
# Tier 3: cost-share application lifecycle
# ---------------------------------------------------------------------------

def setup_application(appropriation_cents=10_000_000, estimated_qty_sqft=100,
                      cycle_kwargs=None, **inventory_kwargs):
    """OPEN cycle + ISSUED notice + SUBMITTED application by the owner."""
    bundle = setup_issued_notice(**inventory_kwargs)
    cycle = make_cycle(**(cycle_kwargs or {"appropriation_cents": appropriation_cents}))
    app = get_success_data(api_client.create_application(
        create_application_payload(bundle["notice"]["id"],
                                   bundle["parcel"]["id"], cycle["id"],
                                   estimated_qty_sqft),
        make_owner_headers(bundle["owner"]["id"])))
    bundle.update({"cycle": cycle, "application": app})
    return bundle


def approve_application(bundle):
    return get_success_data(api_client.decide_application(
        bundle["application"]["id"], {"outcome": "APPROVE"}, COORD))


def setup_approved_application(**kwargs):
    bundle = setup_application(**kwargs)
    bundle["application"] = approve_application(bundle)
    return bundle


def setup_obligated_application(**kwargs):
    bundle = setup_approved_application(**kwargs)
    bundle["application"] = get_success_data(api_client.obligate_application(
        bundle["application"]["id"], FINANCE))
    return bundle


def setup_compliant_notice(bundle, inspector_headers=None):
    """PASS-inspect the bundle's notice by a non-recorder inspector."""
    record = get_success_data(api_client.create_inspection(
        bundle["notice"]["id"], create_inspection_payload("PASS"),
        inspector_headers or INSP2))
    bundle["notice"] = get_success_data(
        api_client.get_repair_notice(bundle["notice"]["id"], COORD))
    bundle["inspection_record"] = record
    return bundle


# ---------------------------------------------------------------------------
# Tier 4: delinquency and city-repair (bid batch) chains
# ---------------------------------------------------------------------------

def setup_delinquent_notice(sweep_clock="2026-09-20T00:00:00Z",
                            issue_clock="2026-08-01T00:00:00Z",
                            **inventory_kwargs):
    """ISSUED notice swept to DELINQUENT after the clock passes its deadline.

    The clock is pinned to the PRD startup default before issuance so the
    compliance deadline lands at issue+base_deadline_days regardless of any
    clock a previous setup step left behind; without this, composing two
    delinquent notices in one test would issue the second at the first
    sweep's clock and leave it unswept."""
    set_clock(issue_clock)
    bundle = setup_issued_notice(**inventory_kwargs)
    set_clock(sweep_clock)
    bundle["sweep"] = get_success_data(api_client.run_delinquency_sweep(COORD))
    bundle["notice"] = get_success_data(
        api_client.get_repair_notice(bundle["notice"]["id"], COORD))
    return bundle


def setup_sealed_batch(bundle, neighborhood_code="NB-1",
                       work_window_start="2026-09-25",
                       work_window_end="2026-10-15",
                       bid_deadline="2026-09-22T00:00:00Z",
                       scope_sqft=50, engineer_unit_rate_cents=1300):
    """Pool the bundle's DELINQUENT notice into a batch and seal it.

    Bundle gains 'batch', 'item', and 'batch_version' (captured after seal).
    """
    batch = make_batch(neighborhood_code, work_window_start, work_window_end,
                       bid_deadline)
    item = make_work_item(batch["id"], bundle["notice"]["id"], scope_sqft,
                          engineer_unit_rate_cents)
    sealed = get_success_data(api_client.seal_bid_batch(batch["id"], COORD))
    bundle.update({"batch": sealed, "item": item,
                   "batch_version": sealed["version"]})
    return bundle


def setup_bid(bundle, company_name="Acme Paving", license_number="L-001",
              insurance_valid_until="2026-12-31", unit_rate_cents=1100,
              ramp_flat_fee_cents=0):
    """Register a contractor and bid on the bundle's sealed batch."""
    contractor = make_contractor(company_name, license_number,
                                 insurance_valid_until)
    bid = make_bid(bundle["batch"]["id"], contractor["id"],
                   bundle["batch_version"], unit_rate_cents, ramp_flat_fee_cents)
    bundle.update({"contractor": contractor, "bid": bid,
                   "batch_version": get_batch_version(bundle["batch"]["id"])})
    return bundle


def award_batch(bundle, award_clock="2026-09-23T00:00:00Z"):
    set_clock(award_clock)
    bundle["batch"] = get_success_data(
        api_client.award_bid_batch(bundle["batch"]["id"], COORD))
    return bundle


def setup_awarded_batch(award_clock="2026-09-23T00:00:00Z", **kwargs):
    """Delinquent notice -> sealed batch -> one contractor bid -> AWARDED."""
    bundle = setup_delinquent_notice(**kwargs.pop("inventory_kwargs", {}))
    setup_sealed_batch(bundle, **kwargs)
    setup_bid(bundle)
    award_batch(bundle, award_clock)
    return bundle


def setup_city_repair_completed(award_clock="2026-09-22T00:00:00Z",
                                work_window_start="2026-09-21",
                                work_window_end="2026-10-05",
                                bid_deadline="2026-09-21T00:00:00Z",
                                bid_unit_rate_cents=1100,
                                verify_headers=None, **inventory_kwargs):
    """Full city-repair chain through item verification.

    Ends with: batch COMPLETED, item VERIFIED, notice CITY_REPAIR_COMPLETED,
    covered defects VERIFIED. Default clock path sweeps at 2026-09-20.
    """
    bundle = setup_delinquent_notice(**inventory_kwargs)
    setup_sealed_batch(bundle, "NB-CR", work_window_start, work_window_end,
                       bid_deadline)
    setup_bid(bundle, unit_rate_cents=bid_unit_rate_cents)
    award_batch(bundle, award_clock)
    get_success_data(api_client.start_batch_work(bundle["batch"]["id"], COORD))
    get_success_data(api_client.complete_work_item(
        bundle["item"]["id"], make_contractor_headers(bundle["contractor"]["id"])))
    bundle["item"] = get_success_data(api_client.verify_work_item(
        bundle["item"]["id"], verify_headers or INSP2))
    bundle["batch"] = get_success_data(
        api_client.get_bid_batch(bundle["batch"]["id"], COORD))
    bundle["notice"] = get_success_data(
        api_client.get_repair_notice(bundle["notice"]["id"], COORD))
    return bundle


# ---------------------------------------------------------------------------
# Tier 5: lien chain
# ---------------------------------------------------------------------------

def setup_lien(actual_repair_cost_cents=500000, record=False, **kwargs):
    """City-repair chain + lien creation. Bundle gains 'lien' (ASSESSED)."""
    bundle = setup_city_repair_completed(**kwargs)
    lien = get_success_data(api_client.create_lien_case(
        create_lien_payload(bundle["notice"]["id"], actual_repair_cost_cents),
        FINANCE))
    bundle["lien"] = lien
    bundle["notice"] = get_success_data(
        api_client.get_repair_notice(bundle["notice"]["id"], COORD))
    if record:
        bundle["lien"] = get_success_data(
            api_client.record_lien_case(lien["id"], FINANCE))
    return bundle


def setup_recorded_lien(actual_repair_cost_cents=500000, **kwargs):
    """Lien chain through RECORDED (payable)."""
    return setup_lien(actual_repair_cost_cents, record=True, **kwargs)


# ---------------------------------------------------------------------------
# Convenience: owner payment on a lien
# ---------------------------------------------------------------------------

def post_payment(lien_id, owner_id, amount_cents):
    return api_client.post_lien_payment(
        lien_id, create_payment_payload(amount_cents),
        make_owner_headers(owner_id))


def adjust_appropriation(cycle_id, delta_cents, expected_version):
    return api_client.adjust_appropriation(
        cycle_id, create_adjustment_payload(delta_cents, expected_version),
        FINANCE)


def appeal(notice_id, owner_id, grounds="dispute"):
    return api_client.appeal_repair_notice(
        notice_id, create_appeal_payload(grounds), make_owner_headers(owner_id))


def decide_appeal(notice_id, decision, headers=None):
    return api_client.decide_appeal(
        notice_id, create_appeal_decision_payload(decision),
        headers or HEARING)


def decide_forestry(review_id, decision):
    return api_client.decide_forestry_review(
        review_id, create_forestry_decision_payload(decision), FORESTRY)
