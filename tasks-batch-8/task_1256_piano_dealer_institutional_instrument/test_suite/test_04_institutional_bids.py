"""Institutional bid pricing pipeline, compliance cycle, and revision OCC (PRD §2.7, §3.3)."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_customer, create_instrument, bid_line, create_bid_package_payload,
    bid_revision_payload,
    create_bid, submit_bid, create_submitted_bid,
    make_bid_officer_headers, make_compliance_officer_headers,
    assert_bid_package,
)


def _edu_instruments(api, count, prefix, list_price=500_000, floor=300_000):
    instruments = []
    for i in range(count):
        instruments.append(create_instrument(
            serial_number=f"{prefix}-{i}", category="UPRIGHT", manufacturer="Yamaha",
            model="U1", year_built=2024, condition_grade="EXCELLENT",
            acquisition_type="NEW", list_price_cents=list_price, floor_price_cents=floor))
    return instruments


def test_bid_tier_and_institution_multiplier_applied(api, bid_officer_headers):
    """PRD §3.3: "A `tier_discount_pct` of 15 percent applies at eleven or more lines, 12
    percent at six through ten lines, 8 percent at three through five lines, and no discount
    below three; the discounted amount is rounded half-up to whole cents."
    PRD §3.3: "Second, an institution multiplier — 0.95 for `EDUCATION`, 0.93 for
    `GOVERNMENT`, 0.97 for `NONPROFIT`, and 1.00 for `CORPORATE` — is applied to the tiered
    amount and rounded half-up again; this multiplier is visible on the package as
    `institution_multiplier`."
    (4 lines of 500000: quantity 4 -> tier 0.08; 2000000 * 0.92 = 1840000 tiered.)

    Design: Difficulty/combinatorial_formula/institutional_bid_tier_multiplier_ceiling
    """
    customer = create_customer(full_name="State University", email="purchasing@su.edu",
                               customer_type="INSTITUTIONAL", institution_type="EDUCATION",
                               tax_exempt=True, state_contract_ceiling_cents=1_700_000,
                               credit_limit_cents=0)
    instruments = _edu_instruments(api, 4, "SN-B")
    bid = validate_success(api.create_bid_package(
        create_bid_package_payload(customer["id"],
                                   [bid_line(i["id"], 500_000) for i in instruments]),
        bid_officer_headers), 201)
    assert_bid_package(bid)
    assert bid["quantity"] == 4
    assert bid["subtotal_cents"] == 2_000_000
    assert bid["tier_discount_pct"] == 0.08, "4 lines hits the 3-5 line tier"
    assert bid["institution_multiplier"] == 0.95, "EDUCATION multiplier"


def test_bid_ceiling_caps_multiplied_total(api, bid_officer_headers):
    """PRD §3.3: "Third, a state-contract ceiling: when the customer carries a non-null
    `state_contract_ceiling_cents`, the final `total_cents` is the lesser of the multiplied
    amount and that ceiling, and the ceiling in force at pricing time is snapshotted onto
    the package as `ceiling_cents`; when the customer has no ceiling, the multiplied amount
    stands."
    (2000000 * 0.92 = 1840000 tiered; 1840000 * 0.95 = 1748000 multiplied; ceiling 1700000
    caps the total.)

    Design: Difficulty/combinatorial_formula/institutional_bid_tier_multiplier_ceiling
    """
    customer = create_customer(full_name="State University", email="purchasing@su.edu",
                               customer_type="INSTITUTIONAL", institution_type="EDUCATION",
                               tax_exempt=True, state_contract_ceiling_cents=1_700_000,
                               credit_limit_cents=0)
    instruments = _edu_instruments(api, 4, "SN-B")
    bid = validate_success(api.create_bid_package(
        create_bid_package_payload(customer["id"],
                                   [bid_line(i["id"], 500_000) for i in instruments]),
        bid_officer_headers), 201)
    assert bid["total_cents"] == 1_700_000, (
        f"ceiling must cap the 1748000 multiplied price, got {bid['total_cents']}")
    assert bid["ceiling_cents"] == 1_700_000, "ceiling snapshot at pricing time"


def test_bid_tier_boundary_qty2_vs_qty3(api, bid_officer_headers):
    """PRD §3.3: "A `tier_discount_pct` of 15 percent applies at eleven or more lines, 12
    percent at six through ten lines, 8 percent at three through five lines, and no discount
    below three; the discounted amount is rounded half-up to whole cents."
    (CORPORATE multiplier 1.00: qty 2 -> total 1000000; qty 3 -> 1500000 * 0.92 = 1380000.)

    Design: Corner/calculations/bid_tier_boundary_qty2_vs_qty3
    """
    customer = create_customer(full_name="Corp Buyer LLC", email="it@corp.com",
                               customer_type="INSTITUTIONAL", institution_type="CORPORATE")
    instruments = _edu_instruments(api, 3, "SN-TB")
    bid2 = validate_success(api.create_bid_package(
        create_bid_package_payload(customer["id"],
                                   [bid_line(instruments[0]["id"], 500_000),
                                    bid_line(instruments[1]["id"], 500_000)]),
        bid_officer_headers), 201)
    bid3 = validate_success(api.create_bid_package(
        create_bid_package_payload(customer["id"],
                                   [bid_line(i["id"], 500_000) for i in instruments]),
        bid_officer_headers), 201)
    assert bid2["tier_discount_pct"] == 0.0 and bid2["total_cents"] == 1_000_000
    assert bid3["tier_discount_pct"] == 0.08 and bid3["total_cents"] == 1_380_000


def test_bid_return_for_revision_cycle(api):
    """PRD §3.3: "A `ComplianceOfficer` may approve it (`SUBMITTED` → `APPROVED`) or return
    it for revision (`SUBMITTED` → `DRAFT`), each permitted only from `SUBMITTED`, else
    `ERR_BID_NOT_ACTIONABLE`."
    PRD §3.3: "From `DRAFT`, the officer submits the package — permitted only from `DRAFT`,
    else `ERR_BID_NOT_ACTIONABLE`"

    Design: Corner/state_machines/bid_return_for_revision_cycle
    """
    customer = create_customer(full_name="City Schools", email="bids@city.gov",
                               customer_type="INSTITUTIONAL", institution_type="GOVERNMENT",
                               state_contract_ceiling_cents=900_000)
    instrument = create_instrument(serial_number="SN-REV-1")
    bid = create_submitted_bid(customer["id"], [bid_line(instrument["id"], 500_000)],
                               officer_user_id="ibo-cycle")

    returned = validate_success(api.return_bid_for_revision(
        bid["id"], make_compliance_officer_headers("co-cycle")), 200)
    assert returned["status"] == "DRAFT", "return-for-revision moves SUBMITTED back to DRAFT"

    resubmitted = validate_success(api.submit_bid_package(
        bid["id"], make_bid_officer_headers("ibo-cycle")), 200)
    assert resubmitted["status"] == "SUBMITTED", "cycle completes: DRAFT -> SUBMITTED again"


def test_bid_submit_below_floor_rejected(api):
    """PRD §3.3: "the `total_cents` must be at least the sum of the `floor_price_cents` of
    every instrument named in the lines, else the submission is rejected with
    `ERR_BID_BELOW_FLOOR` (HTTP 422)."
    (Line 100000 against floor 300000: 100000 * 0.95 = 95000 < 300000.)

    Design: Corner/validations/bid_submit_below_floor_rejected
    """
    customer = create_customer(full_name="Lowball Uni", email="purch@low.edu",
                               customer_type="INSTITUTIONAL", institution_type="EDUCATION")
    instrument = create_instrument(serial_number="SN-LB-1")
    bid = create_bid(customer["id"], [bid_line(instrument["id"], 100_000)],
                     officer_user_id="ibo-lb")
    res = api.submit_bid_package(bid["id"], make_bid_officer_headers("ibo-lb"))
    validate_error(res, "ERR_BID_BELOW_FLOOR")
    after = validate_success(api.get_bid_package(
        bid["id"], make_bid_officer_headers("ibo-lb")), 200)
    assert after["status"] == "DRAFT", "rejected submit must leave the bid in DRAFT"


def test_bid_revision_stale_version_rejected(api):
    """PRD §2.7: "creating a new revision of a bid package requires the request to carry
    `expected_bid_version` holding the `version` of the `BidPackage` the client last read.
    If the package's current `version` has advanced beyond that value — because another
    writer revised or otherwise mutated the package in the meantime — the revision is
    rejected with `ERR_STALE_VERSION` (HTTP 412), since a new revision legitimately
    supersedes the prior one and a writer holding a stale view must be refused."

    Design: Corner/endpoints/bid_revision_occ_stale_version_rejected
    """
    customer = create_customer(full_name="OCC State College", email="it@occ.edu",
                               customer_type="INSTITUTIONAL", institution_type="EDUCATION")
    instrument = create_instrument(serial_number="SN-OCC-1")
    bid = create_submitted_bid(customer["id"], [bid_line(instrument["id"], 500_000)],
                               officer_user_id="ibo-occ")
    observed_version = bid["version"]
    officer = make_bid_officer_headers("ibo-occ")

    first = validate_success(api.create_bid_revision(
        bid["id"], bid_revision_payload(observed_version,
                                        [bid_line(instrument["id"], 480_000)]),
        officer), 200)
    assert first["version"] == observed_version + 1, "successful revision bumps version by one"

    res = api.create_bid_revision(
        bid["id"], bid_revision_payload(observed_version,
                                        [bid_line(instrument["id"], 470_000)]),
        officer)
    validate_error(res, "ERR_STALE_VERSION")


def test_bid_revision_recomputes_pricing_and_revision_number(api):
    """PRD §3.3: "The revision is created-with-supersede — it becomes the package's
    authoritative content — with pricing fully recomputed per the pipeline above, the
    `revision_number` advancing by one, and the package's `version` incrementing by one."
    (Revised line 480000, EDUCATION 0.95: 480000 * 0.95 = 456000.)

    Design: Corner/endpoints/bid_revision_occ_stale_version_rejected
    """
    customer = create_customer(full_name="OCC State College", email="it@occ.edu",
                               customer_type="INSTITUTIONAL", institution_type="EDUCATION")
    instrument = create_instrument(serial_number="SN-OCC-1")
    bid = create_submitted_bid(customer["id"], [bid_line(instrument["id"], 500_000)],
                               officer_user_id="ibo-occ")
    assert bid["revision_number"] == 1
    officer = make_bid_officer_headers("ibo-occ")

    revised = validate_success(api.create_bid_revision(
        bid["id"], bid_revision_payload(bid["version"],
                                        [bid_line(instrument["id"], 480_000)]),
        officer), 200)
    assert revised["revision_number"] == 2, "revision_number advances by one"
    assert revised["total_cents"] == 456_000, (
        f"repriced total 456000 expected, got {revised['total_cents']}")
    assert revised["version"] == bid["version"] + 1
