"""Cross-cutting breadth probes: version tokens, cascades, and frozen checkpoints.

The three layers exercised here all span more than one entity: optimistic
concurrency, where a write on a parent invalidates a token a client already
holds; multi-hop cascades, where one accepted call must reach every dependent row
and no further; and the ops-run checkpoint, whose counters describe the instant
they were computed rather than the live state of the association.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_instant_equals,
    assert_allocation_sums_to,
    fetch_ledger_entries,
    find_entry,
    read_billing_run,
    read_budget,
    read_certificate,
    read_claim,
    read_contract,
    read_unit,
    snapshot_row,
)
from test_helpers.factories import (
    billing_run_payload,
    budget_payload,
    charge_payload,
    installment_payload,
    payment_payload,
    resale_certificate_payload,
    work_order_payload,
)
from test_helpers.fixtures import (
    add_contract,
    add_element,
    add_owner,
    add_unit,
    adjust_claim,
    adopt_budget,
    approve_special_assessment,
    award_and_activate_contract,
    convene,
    create_association,
    issue_certificate,
    notice_meeting,
    patch_association,
    report_claim,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import (
    ATTORNEY_HEADERS,
    MANAGER_HEADERS,
    TITLE_AGENT_HEADERS,
)

HARBOR_POINT = "Harbor Point Condominium Association"


def _seat_director(ctx, label="d1", full_name="Dana Reed", email="dana@example.test"):
    add_owner(
        ctx,
        label,
        full_name=full_name,
        email=email,
        board_role="DIRECTOR",
        is_seated=True,
    )


def _seat_treasurer(ctx):
    add_owner(
        ctx,
        "tr",
        full_name="Tina Cole",
        email="tina@example.test",
        board_role="TREASURER",
        is_seated=True,
    )


def _three_unit_association(api):
    """Three units at 3334/3333/3333 basis points, summing to exactly 10000."""
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    _seat_director(ctx)
    add_unit(ctx, "101", "o1", 3_334, heated_sqft=1_000)
    add_unit(ctx, "102", "o1", 3_333, heated_sqft=1_000)
    add_unit(ctx, "103", "o1", 3_333, heated_sqft=1_000)
    return ctx


# ======================================================================
# Optimistic concurrency
# ======================================================================
def test_a_reserve_only_patch_invalidates_the_budget_creation_token(api):
    """The token is a version, not a timestamp, and any write moves it.

    The `PATCH` touches nothing a budget depends on -- only
    `reserve_balance_cents` -- yet it advances `Association.version` by exactly 1
    and therefore poisons the token the client captured before it. Re-reading and
    resending the identical body succeeds, which proves the refusal was about the
    token and not about the payload.

    PRD 2.6: "Creating a budget for a fiscal year requires
    `expected_association_version` in the request body, carrying the client's last
    observed `version` of the target `Association`."
    PRD 2.6: "If that value does not equal the association's current `version`,
    the create is rejected with `ERR_STALE_ASSOCIATION_VERSION` (HTTP 412)."
    PRD 2.10: "Any such revision increments `Association.version` by 1, which
    invalidates any `expected_association_version` a client captured earlier."
    PRD 3.2: "Budget `status` takes one of six values -- `DRAFT`, `PROPOSED`,
    `NOTICED`, `ADOPTED`, `REJECTED`, and `SUPERSEDED` -- with `DRAFT` as the
    initial state and `ADOPTED` and `SUPERSEDED` as terminal."

    Design: Corner/cross_cutting_complexity_layers/occ_budget_create_rejects_the_stale_association_and_the_refreshed_retry_succeeds
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_unit(ctx, "101", "o1", 10_000, heated_sqft=1_000)
    stale_version = ctx.association_version()
    patched = patch_association(ctx, reserve_balance_cents=3_500_000)
    assert patched["version"] == stale_version + 1
    assert patched["reserve_balance_cents"] == 3_500_000

    body = budget_payload(
        stale_version,
        fiscal_year=2026,
        operating_total_cents=12_000_000,
        reserve_contribution_cents=1_200_000,
    )
    validate_error(
        api.create_budget(ctx.association_id, body, MANAGER_HEADERS),
        "ERR_STALE_ASSOCIATION_VERSION",
        412,
    )
    _budgets, meta = validate_paginated(
        api.list_budgets(MANAGER_HEADERS, params={"association_id": ctx.association_id})
    )
    assert meta["total_count"] == 0

    body["expected_association_version"] = patched["version"]
    drafted = validate_success(
        api.create_budget(ctx.association_id, body, MANAGER_HEADERS), 201
    )
    assert drafted["status"] == "DRAFT"
    assert drafted["fiscal_year"] == 2026


def test_a_rival_certificate_request_voids_the_first_and_moves_the_unit_token(api):
    """The void is what invalidates the token; no money needs to move.

    Agent B's request supersedes agent A's `REQUESTED` certificate and advances
    `Unit.version`, so agent A's follow-on request -- carrying the version read
    before B filed -- is refused. Nothing has been issued, so the ledger is still
    empty; the refusal is purely about a superseded reader.

    PRD 3.9: "Requesting a certificate supersedes any other certificate for that
    unit whose `status` is `REQUESTED`, which becomes `VOIDED` with
    `requires_reissue` false, and advances `Unit.version` by 1."
    PRD 2.6: "A mismatch against the unit's current `version` is rejected with
    `ERR_STALE_UNIT_VERSION` (HTTP 412)."
    PRD 2.6: "A new request legitimately voids any other `REQUESTED` certificate
    for the same unit and quotes payoff figures off that unit's ledger, so a stale
    reader would both supersede an unseen request and publish figures from a
    ledger state that has already advanced."
    PRD 3.9: "`status` runs over `REQUESTED`, `ISSUED`, `VOIDED`, and `EXPIRED`,
    of which `VOIDED` and `EXPIRED` are terminal."

    Design: Corner/cross_cutting_complexity_layers/occ_unit_version_advances_when_a_rival_certificate_request_supersedes_the_first
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    unit_id = add_unit(ctx, "101", "o1", 10_000, heated_sqft=1_000)

    version_a = ctx.unit_version("101")
    cert_a = get_success_data(
        api.request_resale_certificate(
            unit_id,
            resale_certificate_payload(
                "TA-0001", version_a, closing_date="2026-10-05T00:00:00Z"
            ),
            TITLE_AGENT_HEADERS,
        )
    )
    version_b = ctx.unit_version("101")
    assert version_b == version_a + 1
    cert_b = get_success_data(
        api.request_resale_certificate(
            unit_id,
            resale_certificate_payload(
                "TA-0002", version_b, closing_date="2026-10-12T00:00:00Z"
            ),
            TITLE_AGENT_HEADERS,
        )
    )

    validate_error(
        api.request_resale_certificate(
            unit_id,
            resale_certificate_payload(
                "TA-0001", version_b, closing_date="2026-10-19T00:00:00Z"
            ),
            TITLE_AGENT_HEADERS,
        ),
        "ERR_STALE_UNIT_VERSION",
        412,
    )

    _certs, meta = validate_paginated(
        api.list_resale_certificates(MANAGER_HEADERS, params={"unit_id": unit_id})
    )
    assert meta["total_count"] == 2
    voided = read_certificate(api, cert_a["id"], MANAGER_HEADERS)
    assert voided["status"] == "VOIDED"
    assert voided["requires_reissue"] is False
    assert voided["cert_fee_entry_id"] is None
    assert read_certificate(api, cert_b["id"], MANAGER_HEADERS)["status"] == "REQUESTED"
    _rows, ledger_meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"unit_id": unit_id})
    )
    assert ledger_meta["total_count"] == 0

    third = validate_success(
        api.request_resale_certificate(
            unit_id,
            resale_certificate_payload(
                "TA-0001",
                ctx.unit_version("101"),
                closing_date="2026-10-19T00:00:00Z",
            ),
            TITLE_AGENT_HEADERS,
        ),
        201,
    )
    assert third["status"] == "REQUESTED"
    assert read_certificate(api, cert_b["id"], MANAGER_HEADERS)["status"] == "VOIDED"


def test_the_first_encumbrance_moves_the_contract_token_the_second_order_holds(api):
    """Encumbrance and concurrency are coupled through one version number.

    The second order would fit inside the cap -- 600000 plus 300000 is under the
    1000000 authorization -- so a cap error would be the wrong answer; what is
    stale is the client's view of `committed_cents`, and the version guard says so
    before any business check runs. The retry from the refreshed version lands at
    900000 committed.

    PRD 2.6: "Creating a maintenance work order requires
    `expected_contract_version` in the request body, carrying the client's last
    observed `version` of the target `VendorContract`."
    PRD 2.6: "A mismatch against the contract's current `version` is rejected with
    `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."
    PRD 2.6: "Each new order encumbers part of `contract_cap_cents`, so a writer
    working from a stale contract version would be computing remaining
    authorization from a `committed_cents` figure that an earlier encumbrance has
    already changed."
    PRD 3.6: "On success `encumbered_cents` is set to `estimated_cost_cents`, the
    contract's `committed_cents` rises by the same amount, and
    `VendorContract.version` advances by 1."
    PRD 3.6: "A new order is admitted only when `estimated_cost_cents` plus the
    contract's current `committed_cents` plus its `invoiced_cents` is less than or
    equal to `contract_cap_cents`."

    Design: Corner/cross_cutting_complexity_layers/occ_work_order_create_reads_committed_cents_through_the_contract_version
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    _seat_director(ctx)
    element_id = add_element(
        ctx,
        "el1",
        name="Main Roof",
        element_class="ROOF",
        replacement_cost_cents=12_000_000,
        useful_life_years=40,
        effective_age_years=5,
    )
    contract_id = add_contract(
        ctx,
        "ct1",
        "el1",
        vendor_name="Ridgeline Roofing",
        contract_cap_cents=1_000_000,
        # The certificate must sit at or after effective_to so it covers the
        # whole term, or submission is refused with ERR_CONTRACT_TERM_INVALID.
        insurance_cert_expires_at="2027-08-31T00:00:00Z",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2027-08-31T00:00:00Z",
    )
    schedule_meeting(
        ctx, "mtg1", ["CONTRACT_AWARD"], "2026-09-01T10:00:00Z", "2026-09-01T12:00:00Z"
    )
    notice_meeting(ctx, "mtg1")
    set_clock(api, "2026-09-01T10:00:00Z")
    convene(ctx, "mtg1", attending=("d1",))
    activated = award_and_activate_contract(
        ctx, "ct1", "mtg1", voters=(("d1", "101"),)
    )
    assert activated["status"] == "ACTIVE"

    stale_version = ctx.contract_version("ct1")
    first = get_success_data(
        api.create_work_order(
            work_order_payload(
                contract_id,
                element_id,
                stale_version,
                scope="Replace flashing",
                estimated_cost_cents=600_000,
                window_start="2026-09-10T08:00:00Z",
                window_end="2026-09-10T16:00:00Z",
            ),
            MANAGER_HEADERS,
        )
    )
    assert first["encumbered_cents"] == 600_000

    second_body = work_order_payload(
        contract_id,
        element_id,
        stale_version,
        scope="Replace membrane",
        estimated_cost_cents=300_000,
        window_start="2026-09-20T08:00:00Z",
        window_end="2026-09-20T16:00:00Z",
    )
    validate_error(
        api.create_work_order(second_body, MANAGER_HEADERS),
        "ERR_STALE_CONTRACT_VERSION",
        412,
    )

    _orders, meta = validate_paginated(
        api.list_work_orders(MANAGER_HEADERS, params={"contract_id": contract_id})
    )
    assert meta["total_count"] == 1
    encumbered = read_contract(api, contract_id, MANAGER_HEADERS)
    assert encumbered["committed_cents"] == 600_000
    assert encumbered["version"] == stale_version + 1

    second_body["expected_contract_version"] = encumbered["version"]
    second = validate_success(api.create_work_order(second_body, MANAGER_HEADERS), 201)
    assert second["status"] == "SCHEDULED"
    assert (
        read_contract(api, contract_id, MANAGER_HEADERS)["committed_cents"] == 900_000
    )


# ======================================================================
# Multi-hop cascades
# ======================================================================
def test_one_ratify_call_allocates_every_unit_and_unblocks_the_billing_run(api):
    """Four hops out of one call, and a late-arriving unit that the cascade skips.

    The 13200000-cent budget yields a 1100000-cent monthly pool that divides
    without drift over 3334/3333/3333 basis points, so every share is its
    per-line rounded value and no remainder cent is awarded. A unit created after
    adoption is not retro-allocated, and the billing run -- which had no adopted
    budget to draw on before this call -- now posts from the frozen snapshot
    rather than from live membership.

    PRD 3.2: "On `NOTICED → ADOPTED`, the server writes `no_weight_bp` and stamps
    `adopted_at` with the logical clock, then runs a five-hop cascade."
    PRD 3.2: "First, the pool is fixed in integer cents *before* any per-unit
    arithmetic: for a budget adoption the pool is `assessment_total_cents` divided
    by 12 and rounded half up."
    PRD 3.2: "Each unit's `monthly_assessment_cents` receives its final share, and
    the budget's `allocation_snapshot` freezes one object per participant carrying
    `unit_id`, `interest_bp`, `monthly_cents` holding the final share, and
    `remainder_cent_awarded`, a boolean that is true exactly when the final share
    differs from the per-line rounded value computed in the third step."
    PRD 3.2: "Units created after adoption are not retro-allocated and keep
    `monthly_assessment_cents` at 0 until the next adoption."
    PRD 3.5: "First, one `ASSESSMENT` row per unit is posted from the budget's
    `allocation_snapshot`, each carrying that unit's `monthly_cents` as its
    positive `amount_cents`, the run's `due_on` as its `due_on`, the run's
    `period` as its `effective_period`, and the run's identifier as its
    `billing_run_id`; the run reports `assessment_charged_cents` as the sum of
    those amounts, `charged_unit_count` as the number of units that received at
    least one charge in this run, and `remainder_cents_allocated` as the absolute
    rounding drift the allocator reconciled."

    Design: Corner/cross_cutting_complexity_layers/ratification_cascade_reaches_association_units_and_the_first_billing_run
    """
    ctx = _three_unit_association(api)
    adopted = adopt_budget(
        ctx,
        meeting_start="2026-09-01T10:00:00Z",
        meeting_end="2026-09-01T12:00:00Z",
        attending=("d1",),
    )
    assert adopted["status"] == "ADOPTED"
    assert adopted["assessment_total_cents"] == 13_200_000
    assert adopted["monthly_assessable_cents"] == 1_100_000
    assert_instant_equals(adopted["adopted_at"], "2026-09-01T10:00:00Z")

    snapshot = adopted["allocation_snapshot"]
    assert len(snapshot) == 3
    assert_allocation_sums_to(snapshot, "monthly_cents", 1_100_000)
    top = snapshot_row(snapshot, ctx.units["101"])
    assert top["interest_bp"] == 3_334
    assert top["monthly_cents"] == 366_740
    assert top["remainder_cent_awarded"] is False
    for label in ("102", "103"):
        row = snapshot_row(snapshot, ctx.units[label])
        assert row["monthly_cents"] == 366_630
        assert row["remainder_cent_awarded"] is False
    assert (
        read_unit(api, ctx.units["101"], MANAGER_HEADERS)["monthly_assessment_cents"]
        == 366_740
    )
    for label in ("102", "103"):
        assert (
            read_unit(api, ctx.units[label], MANAGER_HEADERS)[
                "monthly_assessment_cents"
            ]
            == 366_630
        )

    latecomer_id = add_unit(ctx, "104", "o1", 1, heated_sqft=1_000)
    assert (
        read_unit(api, latecomer_id, MANAGER_HEADERS)["monthly_assessment_cents"] == 0
    )
    reread = read_budget(api, adopted["id"], MANAGER_HEADERS)
    assert [row["unit_id"] for row in reread["allocation_snapshot"]].count(
        latecomer_id
    ) == 0

    run = validate_success(
        api.create_billing_run(
            ctx.association_id,
            billing_run_payload(
                adopted["id"], period="2026-09", due_on="2026-09-10T00:00:00Z"
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert run["assessment_charged_cents"] == 1_100_000
    assert run["charged_unit_count"] == 3
    assert run["remainder_cents_allocated"] == 0


def test_the_tender_voids_only_the_certificates_of_the_named_units(api):
    """The fan-out follows `affected_unit_ids`, and the third unit is spared.

    Tendering the defect matter voids the certificates of the two named units and
    reverses each 35000-cent fee, returning both ledgers to zero, while the
    unnamed third unit keeps its `ISSUED` certificate, its fee and its unblocked
    transfer. A blanket void across the association is the failure mode this
    guards. The follow-on `IN_LITIGATION` call is refused because no approved
    assessment funds the suit, which shows the litigation dimension advances one
    rung at a time.

    PRD 3.7: "It sets `disclosure_required` to true and then cascades: every
    resale certificate whose `status` is `ISSUED` and whose `unit_id` appears in
    `affected_unit_ids` becomes `VOIDED` with `requires_reissue` set to true,
    because an already-issued certificate cannot disclose a matter tendered after
    it was printed; each such certificate's `cert_fee_entry_id` is answered with a
    `REVERSAL` row, and the affected unit's `balance_due_cents` and
    `delinquency_stage` are recomputed with `Unit.version` advancing by 1."
    PRD 3.7: "Moving `TENDERED → IN_LITIGATION` requires `litigation_status` to be
    `TENDERED` and requires that some special assessment exist whose
    `funding_claim_id` is this claim and whose `approval_status` is `APPROVED` --
    suit may not be filed until the owners have funded it -- failing which the
    response is `ERR_LITIGATION_FUNDING_MISSING`; the only effect is that
    `InsuranceClaim.version` advances by 1."
    PRD 3.1: "`balance_due_cents` is the signed sum of `amount_cents` over
    *every* ledger row of the unit, regardless of `status` -- a reversed pair nets
    to zero, so nothing is double counted."
    PRD 3.9: "Finally `issued_at` is stamped from the logical clock, `expires_at`
    is set to `issued_at` advanced by `certificate_validity_days`, the unit's
    `transfer_blocked` is set to false, and `ResaleCertificate.version` advances
    by 1."

    Design: Corner/cross_cutting_complexity_layers/tender_cascade_fans_out_over_affected_units_and_spares_the_unaffected_one
    """
    ctx = _three_unit_association(api)
    add_element(
        ctx,
        "el1",
        name="Podium Slab",
        element_class="FACADE",
        replacement_cost_cents=30_000_000,
        useful_life_years=50,
        effective_age_years=25,
    )
    adopt_budget(
        ctx,
        meeting_start="2026-09-01T10:00:00Z",
        meeting_end="2026-09-01T12:00:00Z",
        attending=("d1",),
    )
    certificates = {
        label: issue_certificate(ctx, label, closing_date="2026-10-05T00:00:00Z")
        for label in ("101", "102", "103")
    }
    for certificate in certificates.values():
        assert certificate["status"] == "ISSUED"
    claim = report_claim(
        ctx,
        "101",
        "el1",
        loss_type="CONSTRUCTION_DEFECT",
        loss_at="2026-06-01T00:00:00Z",
        gross_damage_cents=30_000_000,
        within_unit_boundary_cents=0,
        affected_unit_ids=[ctx.units["101"], ctx.units["102"]],
    )
    adjust_claim(ctx, claim["id"], responsibility="DENY")

    tendered = validate_success(
        api.set_litigation_stage(claim["id"], {"stage": "TENDERED"}, ATTORNEY_HEADERS),
        200,
    )
    assert tendered["litigation_status"] == "TENDERED"
    assert tendered["disclosure_required"] is True
    assert tendered["adjustment_status"] == "DENIED"

    for label in ("101", "102"):
        voided = read_certificate(api, certificates[label]["id"], MANAGER_HEADERS)
        assert voided["status"] == "VOIDED"
        assert voided["requires_reissue"] is True
        rows = fetch_ledger_entries(api, MANAGER_HEADERS, unit_id=ctx.units[label])
        fee_row = find_entry(rows, id=certificates[label]["cert_fee_entry_id"])
        assert fee_row["status"] == "REVERSED"
        reversal = find_entry(rows, entry_type="REVERSAL")
        assert reversal["amount_cents"] == -35_000
        assert read_unit(api, ctx.units[label], MANAGER_HEADERS)["balance_due_cents"] == 0

    spared = read_certificate(api, certificates["103"]["id"], MANAGER_HEADERS)
    assert spared["status"] == "ISSUED"
    assert spared["requires_reissue"] is False
    untouched = read_unit(api, ctx.units["103"], MANAGER_HEADERS)
    assert untouched["balance_due_cents"] == 35_000
    assert untouched["transfer_blocked"] is False

    validate_error(
        api.set_litigation_stage(
            claim["id"], {"stage": "IN_LITIGATION"}, ATTORNEY_HEADERS
        ),
        "ERR_LITIGATION_FUNDING_MISSING",
        409,
    )
    assert read_claim(api, claim["id"], MANAGER_HEADERS)["litigation_status"] == "TENDERED"


# ======================================================================
# Shared allocator, two pools
# ======================================================================
def test_the_installment_pool_allocates_independently_of_the_monthly_pool(api):
    """One allocator, two pools, and no shared rounding state.

    The monthly variant divides 13200000 by twelve into a 1100000-cent pool while
    the installment variant divides 4000000 into four 1000000-cent rounds; over
    the same 3334/3333/3333 participants the two produce different share vectors,
    and the installment posting must leave every unit's monthly figure alone.

    PRD 3.4: "Each round reuses the same allocator as budget adoption, with one
    difference: the pool for rounds one through `installment_count` minus one is
    `total_amount_cents` divided by `installment_count` and rounded half up,
    while the **final** round instead uses `total_amount_cents` minus the sum of
    the pools already posted, so that the posted installments sum to
    `total_amount_cents` exactly with no drift."
    PRD 3.2: "Third, each participant's share is computed as the pool multiplied
    by that unit's `interest_bp`, divided by 10000, and rounded half up; this
    per-line rounding is mandatory and summing before rounding is wrong."
    PRD 3.4: "One `SPECIAL_ASSESSMENT_INSTALLMENT` row per unit is posted with
    that unit's share, `installments_posted` rises by 1, `charged_cents` is
    recomputed, every affected unit's `balance_due_cents` is recomputed and its
    `delinquency_stage` re-derived with `Unit.version` advancing by 1, and
    `SpecialAssessment.version` advances by 1."
    PRD 3.4: "`eligible_weight_bp` is the sum of `interest_bp` over every unit of
    the association whose `voting_eligible` is true, so a unit that never cast a
    ballot still sits in the denominator."

    Design: Corner/cross_cutting_complexity_layers/allocator_variants_diverge_on_the_same_participants_monthly_versus_installment
    """
    ctx = _three_unit_association(api)
    _seat_treasurer(ctx)
    adopted = adopt_budget(
        ctx,
        meeting_start="2026-09-01T10:00:00Z",
        meeting_end="2026-09-01T12:00:00Z",
        attending=("d1",),
    )
    monthly = {
        label: snapshot_row(adopted["allocation_snapshot"], ctx.units[label])[
            "monthly_cents"
        ]
        for label in ("101", "102", "103")
    }
    assert monthly == {"101": 366_740, "102": 366_630, "103": 366_630}

    assessment = approve_special_assessment(
        ctx,
        total_amount_cents=4_000_000,
        installment_count=4,
        purpose="Podium slab repair",
        ballots=(
            ("o1", "101", "YES"),
            ("o1", "102", "YES"),
            ("o1", "103", "YES"),
        ),
    )
    assert assessment["approval_status"] == "APPROVED"
    assert assessment["yes_weight_bp"] == 10_000
    assert assessment["eligible_weight_bp"] == 10_000

    posted = validate_success(
        api.post_installment(
            assessment["id"],
            installment_payload(
                due_on="2026-10-01T00:00:00Z", effective_period="2026-10"
            ),
            ctx.treasurer(),
        ),
        200,
    )
    assert posted["installments_posted"] == 1
    assert posted["charged_cents"] == 1_000_000

    rows = fetch_ledger_entries(
        api, MANAGER_HEADERS, special_assessment_id=assessment["id"]
    )
    assert len(rows) == 3
    shares = {
        label: find_entry(rows, unit_id=ctx.units[label])["amount_cents"]
        for label in ("101", "102", "103")
    }
    assert shares == {"101": 333_400, "102": 333_300, "103": 333_300}
    assert sum(shares.values()) == 1_000_000

    unchanged = read_unit(api, ctx.units["101"], MANAGER_HEADERS)
    assert unchanged["monthly_assessment_cents"] == 366_740
    assert unchanged["balance_due_cents"] == 333_400


# ======================================================================
# Ops-run checkpoint
# ======================================================================
def test_the_run_counters_stay_frozen_after_the_unit_pays_its_way_back(api):
    """A billing run is a historical checkpoint, not a live view of the ledger.

    The run posts both assessments, charges a capped late fee on the one aged
    assessment, and escalates that unit into `LIEN_FILED`. A later full payment
    de-escalates the unit to `CURRENT` with a zero balance, yet the run's
    `escalated_unit_count` and `late_fees_charged_cents` must still describe the
    instant they were computed; recomputing them from live unit state is the
    failure mode. Re-billing the same period is refused outright.

    PRD 3.5: "Otherwise the percentage limb is the delinquent principal
    multiplied by `late_fee_percent_bp`, divided by 10000, and rounded half up --
    one tenth of the delinquent principal at the default of 1000 basis points --
    and the fee is then that percentage limb raised to at least
    `late_fee_min_cents` and afterwards lowered to at most `late_fee_cap_cents`,
    applying the floor before the cap in that order."
    PRD 3.5: "Special-assessment, fine, collection-cost, and interest balances
    never enter the late-fee base."
    PRD 3.5: "Third, every unit's `balance_due_cents`, `credit_balance_cents`, and
    `oldest_unpaid_age_days` are recomputed and `delinquency_stage` is re-derived
    through the ladder of §3.1, with `escalated_unit_count` counting the units
    whose posture advanced during this run."
    PRD 3.1: "Rule 3: if `oldest_unpaid_age_days` is at least 90 and
    `balance_due_cents` is at least `lien_threshold_cents`, the posture is
    `LIEN_FILED`."
    PRD 3.5: "A run for a period this association has already billed is refused
    with `ERR_PERIOD_ALREADY_BILLED`, and a `source_budget_id` that is not
    `ADOPTED`, or whose `fiscal_year` does not cover the `period`, is refused with
    `ERR_BUDGET_NOT_ADOPTED`."

    Design: Corner/cross_cutting_complexity_layers/billing_run_counters_are_a_frozen_checkpoint_not_a_live_view
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_owner(ctx, "o2", full_name="Nora Bell", email="nora@example.test")
    _seat_director(ctx)
    add_unit(ctx, "101", "o1", 5_000, heated_sqft=1_000)
    add_unit(ctx, "102", "o2", 5_000, heated_sqft=1_000)
    budget = adopt_budget(
        ctx,
        meeting_start="2026-09-01T10:00:00Z",
        meeting_end="2026-09-01T12:00:00Z",
        attending=("d1",),
    )
    get_success_data(
        api.create_charge(
            ctx.units["101"],
            charge_payload(
                entry_type="ASSESSMENT",
                amount_cents=170_000,
                due_on="2026-05-05T00:00:00Z",
                effective_period="2026-05",
                memo="corrective spring assessment",
            ),
            MANAGER_HEADERS,
        )
    )
    aged = read_unit(api, ctx.units["101"], MANAGER_HEADERS)
    assert aged["delinquency_stage"] == "LATE_NOTICE"
    assert aged["voting_eligible"] is True
    set_clock(api, "2026-09-20T00:00:00Z")

    run = validate_success(
        api.create_billing_run(
            ctx.association_id,
            billing_run_payload(
                budget["id"], period="2026-09", due_on="2026-10-01T00:00:00Z"
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert_instant_equals(run["executed_at"], "2026-09-20T00:00:00Z")
    assert run["assessment_charged_cents"] == 1_100_000
    assert run["charged_unit_count"] == 2
    assert run["remainder_cents_allocated"] == 0
    assert run["late_fees_charged_cents"] == 10_000
    assert run["escalated_unit_count"] == 1
    assert run["fines_finalized_count"] == 0

    lienned = read_unit(api, ctx.units["101"], MANAGER_HEADERS)
    assert lienned["delinquency_stage"] == "LIEN_FILED"
    assert lienned["voting_eligible"] is False
    assert_instant_equals(lienned["lien_recorded_at"], "2026-09-20T00:00:00Z")
    assert lienned["balance_due_cents"] == 730_000
    current = read_unit(api, ctx.units["102"], MANAGER_HEADERS)
    assert current["delinquency_stage"] == "CURRENT"
    assert current["balance_due_cents"] == 550_000

    get_success_data(
        api.create_payment(
            ctx.units["101"],
            payment_payload(730_000, effective_period="2026-09", memo="payoff in full"),
            MANAGER_HEADERS,
        )
    )
    settled = read_unit(api, ctx.units["101"], MANAGER_HEADERS)
    assert settled["balance_due_cents"] == 0
    assert settled["delinquency_stage"] == "CURRENT"

    frozen = read_billing_run(api, run["id"], MANAGER_HEADERS)
    assert frozen["escalated_unit_count"] == 1
    assert frozen["late_fees_charged_cents"] == 10_000
    assert frozen["assessment_charged_cents"] == 1_100_000

    validate_error(
        api.create_billing_run(
            ctx.association_id,
            billing_run_payload(
                budget["id"], period="2026-09", due_on="2026-10-01T00:00:00Z"
            ),
            MANAGER_HEADERS,
        ),
        "ERR_PERIOD_ALREADY_BILLED",
        409,
    )
    _runs, meta = validate_paginated(
        api.list_billing_runs(
            MANAGER_HEADERS, params={"association_id": ctx.association_id}
        )
    )
    assert meta["total_count"] == 1
