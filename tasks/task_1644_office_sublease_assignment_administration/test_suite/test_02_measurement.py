"""Space measurement: standards, provisional-vs-certified, revision chains (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    B1,
    add_certified_measurement,
    assert_demised_area,
    build_granted_transfer,
    certify_measurement,
    create_draft_transfer,
    create_measurement,
    document_transfer,
    standard_portfolio,
    validate_error,
    validate_paginated,
    validate_success,
)

EXPECTED_RSF_METHOD_A = 8960      # 8000 * (10000 + 1200) / 10000
EXPECTED_PRORATA_A = 448          # round_half_up(8960 * 10000 / 200000)
EXPECTED_RSF_METHOD_B = 8680      # 8000 * (10000 + 600 + 250) / 10000
EXPECTED_PRORATA_B = 434          # round_half_up(8680 * 10000 / 200000)
EXPECTED_RSF_REVISION = 8710      # 7777 * 11200 / 10000 = 8710.24 -> 8710


def test_demised_area_defaults_and_computed_fields(api):
    """PRD §3.3: "A new record starts in `DRAFT`, and while it remains there its derived values are provisional: each read recomputes them against the building's current loss factor, so a draft measurement silently tracks building changes."
    PRD §3.3: "First `rentable_sf`: under `METHOD_A`, the `usable_sf` multiplied by ten thousand plus the building's `loss_factor_bps`, the product divided by ten thousand, and the quotient rounded half-up to a whole square foot"

    Design: Corner/entities/demised_area_defaults_and_computed_fields
    """
    ctx = standard_portfolio()
    transfer = create_draft_transfer(ctx)

    area = validate_success(api.create_demised_area(
        transfer["id"],
        {"measurement_standard": "METHOD_A", "usable_sf": 8000},
        B1,
    ), 201)
    assert_demised_area(area)
    assert area["status"] == "DRAFT"
    assert area["rentable_sf"] == EXPECTED_RSF_METHOD_A, "provisional value computed by the server"
    assert area["prorata_share_bps"] == EXPECTED_PRORATA_A
    assert area["is_partial_floor"] is True  # 8960 < leased_rsf 10000
    assert area.get("superseded_by_id") is None
    assert area["lease_id"] == ctx["lease"]["id"], "lease association derived from the parent transfer"


def test_method_a_certified_values(api):
    """PRD §3.3: "under `METHOD_A`, the `usable_sf` multiplied by ten thousand plus the building's `loss_factor_bps`, the product divided by ten thousand, and the quotient rounded half-up to a whole square foot"
    PRD §3.3: "Second, `prorata_share_bps`: the frozen `rentable_sf` multiplied by ten thousand and divided by the building's `total_rentable_sf`, rounded half-up to an integer basis-point value."

    Design: Difficulty/dual_variant_calc/measurement_standard_a_vs_b_divergent_rsf
    """
    ctx = standard_portfolio()
    transfer = create_draft_transfer(ctx)
    area = add_certified_measurement(transfer["id"], measurement_standard="METHOD_A",
                                     usable_sf=8000)

    fetched = validate_success(api.get_demised_area(area["id"], B1), 200)
    assert fetched["status"] == "CERTIFIED"
    assert fetched["rentable_sf"] == EXPECTED_RSF_METHOD_A
    assert fetched["prorata_share_bps"] == EXPECTED_PRORATA_A
    assert fetched["is_partial_floor"] is True


def test_method_b_certified_values_diverge(api):
    """PRD §3.3: "under `METHOD_B`, the same shape but with the loss factor integer-halved — the basis-point value divided by two with any remainder discarded — and a fixed common-area add-on of 250 basis points (two and a half percent) included alongside the halved factor."
    PRD §3.3: "Second, `prorata_share_bps`: the frozen `rentable_sf` multiplied by ten thousand and divided by the building's `total_rentable_sf`, rounded half-up to an integer basis-point value."

    Design: Difficulty/dual_variant_calc/measurement_standard_a_vs_b_divergent_rsf
    """
    ctx = standard_portfolio()
    transfer = create_draft_transfer(ctx)
    area_a = add_certified_measurement(transfer["id"], measurement_standard="METHOD_A",
                                       usable_sf=8000)

    # A second lease + transfer hosts the METHOD_B twin (one open transfer per lease).
    ctx2 = standard_portfolio()
    transfer_b = create_draft_transfer(ctx2)
    area_b = add_certified_measurement(transfer_b["id"], measurement_standard="METHOD_B",
                                       usable_sf=8000)

    fetched_b = validate_success(api.get_demised_area(area_b["id"], B1), 200)
    assert fetched_b["rentable_sf"] == EXPECTED_RSF_METHOD_B
    assert fetched_b["prorata_share_bps"] == EXPECTED_PRORATA_B

    fetched_a = validate_success(api.get_demised_area(area_a["id"], B1), 200)
    assert fetched_a["rentable_sf"] != fetched_b["rentable_sf"], (
        "identical usable_sf diverges under the two measurement standards"
    )


def test_provisional_draft_then_certified_freeze(api):
    """PRD §3.3: "A new record starts in `DRAFT`, and while it remains there its derived values are provisional: each read recomputes them against the building's current loss factor, so a draft measurement silently tracks building changes."
    PRD §3.3: "Once certified, the record's values are frozen; a later change to the building's loss factor does not alter them."

    Design: Corner/calculations/provisional_draft_measurement_recomputed_against_loss_factor_change
    """
    ctx = standard_portfolio()
    transfer = create_draft_transfer(ctx)
    area = create_measurement(transfer["id"], measurement_standard="METHOD_A",
                              usable_sf=8000)

    draft_read = validate_success(api.get_demised_area(area["id"], B1), 200)
    assert draft_read["status"] == "DRAFT"
    assert draft_read["rentable_sf"] == EXPECTED_RSF_METHOD_A, (
        "provisional variant computes on read"
    )

    certified = certify_measurement(area["id"])
    assert certified["status"] == "CERTIFIED"
    frozen_read = validate_success(api.get_demised_area(area["id"], B1), 200)
    assert frozen_read["rentable_sf"] == EXPECTED_RSF_METHOD_A, (
        "certified variant freezes the same inputs"
    )
    assert frozen_read["prorata_share_bps"] == EXPECTED_PRORATA_A


def test_revision_certify_supersedes_prior(api):
    """PRD §3.3: "When a revision certifies, the record it references flips from `CERTIFIED` to `SUPERSEDED` and its `superseded_by_id` is set to the new record's `id`; a superseded record is thereafter read-only for settlement math."

    Design: Difficulty/transitive_cascade/measurement_revision_two_hop_supersession_cascade
    """
    ctx = standard_portfolio()
    transfer = create_draft_transfer(ctx)
    m1 = add_certified_measurement(transfer["id"], measurement_standard="METHOD_A",
                                   usable_sf=8000)
    m2 = create_measurement(transfer["id"], measurement_standard="METHOD_A",
                            usable_sf=7777, supersedes_id=m1["id"])
    assert m2["status"] == "DRAFT"

    certified_m2 = certify_measurement(m2["id"])
    assert certified_m2["status"] == "CERTIFIED"
    assert certified_m2["rentable_sf"] == EXPECTED_RSF_REVISION

    m1_after = validate_success(api.get_demised_area(m1["id"], B1), 200)
    assert m1_after["status"] == "SUPERSEDED", "hop 2: prior certified record flips"
    assert m1_after["superseded_by_id"] == m2["id"]


def test_revision_chain_visible_via_filters(api):
    """PRD §3.3: "The measurements collection lists with `lease_id`, `transfer_request_id`, `supersedes_id`, `superseded_by_id`, and `status` filters, which also exposes the chain in both directions: the revisions of a record and the records a record has superseded."

    Design: Difficulty/transitive_cascade/measurement_revision_two_hop_supersession_cascade
    """
    ctx = standard_portfolio()
    transfer = create_draft_transfer(ctx)
    m1 = add_certified_measurement(transfer["id"], measurement_standard="METHOD_A",
                                   usable_sf=8000)
    m2 = create_measurement(transfer["id"], measurement_standard="METHOD_A",
                            usable_sf=7777, supersedes_id=m1["id"])
    certify_measurement(m2["id"])

    revisions, _ = validate_paginated(
        api.list_demised_areas(B1, params={"supersedes_id": m1["id"]})
    )
    assert [r["id"] for r in revisions] == [m2["id"]], (
        "supersedes_id filter exposes the revisions of a record"
    )

    superseded, _ = validate_paginated(
        api.list_demised_areas(B1, params={"superseded_by_id": m2["id"]})
    )
    assert [r["id"] for r in superseded] == [m1["id"]], (
        "superseded_by_id filter exposes the records a record has superseded"
    )


def test_revision_chain_off_non_tip_rejected(api):
    """PRD §3.3: "A revision must chain off the current certified tip: creating one whose `supersedes_id` references a record that is still `DRAFT` or already `SUPERSEDED` is rejected with `ERR_MEASUREMENT_SUPERSEDED` (HTTP 409), and attempting to certify a record that is itself `SUPERSEDED` draws the same rejection."

    Design: Corner/state_machines/supersession_chain_off_non_tip_rejected
    """
    ctx = standard_portfolio()
    transfer = create_draft_transfer(ctx)
    m1 = add_certified_measurement(transfer["id"], measurement_standard="METHOD_A",
                                   usable_sf=8000)
    m2 = create_measurement(transfer["id"], measurement_standard="METHOD_A",
                            usable_sf=7777, supersedes_id=m1["id"])
    certify_measurement(m2["id"])  # m1 is now SUPERSEDED, m2 is the tip

    resp = api.create_demised_area(
        transfer["id"],
        {"measurement_standard": "METHOD_B", "usable_sf": 9000,
         "supersedes_id": m1["id"]},
        B1,
    )
    validate_error(resp, ApiErrorId.ERR_MEASUREMENT_SUPERSEDED, 409)

    resp2 = api.certify_demised_area(m1["id"], B1)
    validate_error(resp2, ApiErrorId.ERR_MEASUREMENT_SUPERSEDED, 409)

    m2_after = validate_success(api.get_demised_area(m2["id"], B1), 200)
    assert m2_after["status"] == "CERTIFIED", "m2 remains the certified tip"
    m1_after = validate_success(api.get_demised_area(m1["id"], B1), 200)
    assert m1_after["superseded_by_id"] == m2["id"]


def test_certify_after_grant_rejected_document_pins_prior(api):
    """PRD §3.3: "When the broker certifies a record — permitted only while the parent transfer sits in `DRAFT`, `SUBMITTED`, or `CONSENT_PENDING`, with attempts in any other transfer state rejected as `ERR_INVALID_STATE`"
    PRD §3.7: "For a `SUBLEASE`, an instrument is minted in `EXECUTED` status, stamped with `executed_at` and pinned to the certified measurement through its `demised_area_id` — version-pinning on approval, so the closing paper always names the exact measurement it relies on"

    Design: Corner/state_machines/certify_revision_rejected_after_grant_document_pins_m1
    """
    ctx = build_granted_transfer()
    m1 = validate_paginated(api.list_transfer_demised_areas(ctx["transfer"]["id"], B1))[0][0]
    assert m1["status"] == "CERTIFIED"

    # Revision created after consent; its certification is now locked.
    m2 = create_measurement(ctx["transfer"]["id"], measurement_standard="METHOD_A",
                            usable_sf=7777, supersedes_id=m1["id"])
    resp = api.certify_demised_area(m2["id"], B1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    m2_after = validate_success(api.get_demised_area(m2["id"], B1), 200)
    assert m2_after["status"] == "DRAFT"
    m1_after = validate_success(api.get_demised_area(m1["id"], B1), 200)
    assert m1_after["status"] == "CERTIFIED"
    assert m1_after.get("superseded_by_id") is None

    receipt = document_transfer(ctx["transfer"]["id"])
    instrument = validate_success(
        api.get_sublease_agreement(receipt["sublease_agreement_id"], B1), 200,
    )
    assert instrument["demised_area_id"] == m1["id"], (
        "documentation pins the pre-grant certified measurement"
    )
