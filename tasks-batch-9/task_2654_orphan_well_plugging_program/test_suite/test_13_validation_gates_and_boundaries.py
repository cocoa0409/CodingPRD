"""Specific validation gates: which rule speaks first, and where its edge falls."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_null_fields,
    assert_page,
    assert_score,
)

SOLVENT_WELL = dict(spud_year=1961, total_depth_ft=2500, casing_strings=1)
LATE_BID_RATES = {
    "cement_per_sack_cents": 4100,
    "rig_day_rate_cents": 810000,
    "casing_per_ft_cents": 1250,
    "mobilization_fee_cents": 2450000,
}


def test_forfeiting_a_solvent_operators_bond_reports_the_standing_error(api):
    """The forfeiture carve-out speaks before the generic edge check does.

    The operator is ACTIVE, so FORFEIT_BOND is not a declared edge out of its state at
    all; the generic rule would therefore answer first and the specific error would be
    unreachable. It is the specific error that comes back, the operator is left entirely
    untouched, and once insolvency is declared the identical action runs its four hops.

    PRD: "A forfeiture attempt against an operator that is not `INSOLVENT` fails with
    `ERR_OPERATOR_STILL_SOLVENT`. This carve-out deliberately sits ahead of the generic
    state check in step 10"

    Design: Corner/validations/forfeiting_a_solvent_operators_bond_is_rejected_before_the_generic_edge_check
    """
    operator = fx.make_operator(
        api,
        name="Wind River Petroleum",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=250000,
    )
    well = fx.make_well(api, operator["id"], **SOLVENT_WELL)
    first_version = fx.read_operator(api, operator["id"])["version"]
    assert_fields(fx.read_operator(api, operator["id"]), status="ACTIVE")

    refused = api.operator_enforcement(
        operator["id"],
        f.enforcement_payload(
            "FORFEIT_BOND", first_version, "premature forfeiture attempt"
        ),
        users.ADMIN,
    )
    validate_error(refused, e.ERR_OPERATOR_STILL_SOLVENT, 422)

    untouched = fx.read_operator(api, operator["id"])
    assert_fields(untouched, status="ACTIVE")
    assert_cents(untouched["bond_amount_cents"], 250000, "bond_amount_cents")
    assert_null_fields(untouched, "bond_forfeited_at")
    assert_page(api.list_funding_sources(users.FUNDING), 0, expected_total=0)

    insolvent = fx.enforce(
        api, operator["id"], "DECLARE_INSOLVENT", "receivership filed"
    )
    assert_fields(
        insolvent, status="INSOLVENT", insolvency_declared_at="2026-08-01T00:00:00Z"
    )

    revoked = fx.enforce(api, operator["id"], "FORFEIT_BOND", "bond called")
    assert_fields(
        revoked, status="REVOKED", bond_forfeited_at="2026-08-01T00:00:00Z"
    )
    assert_cents(revoked["bond_amount_cents"], 0, "bond_amount_cents after forfeiture")

    sources = assert_page(api.list_funding_sources(users.FUNDING), 1, expected_total=1)
    source = sources[0]
    assert_fields(
        source,
        kind="FORFEITED_BOND",
        name="FORFEITED BOND Wind River Petroleum",
        bond_operator_id=operator["id"],
        expires_at="2036-07-29T00:00:00Z",
        status="ACTIVE",
    )
    assert_cents(source["authorized_cents"], 250000, "authorized_cents")
    assert source["allowable_cost_categories"] == ["PLUGGING", "RECLAMATION"], (
        "the forfeited bond must be spendable on plugging and reclamation, got %r"
        % (source["allowable_cost_categories"],)
    )

    assert_fields(fx.read_well(api, well["id"]), status="ORPHAN_CANDIDATE")
    assert_fields(
        fx.read_operator(api, operator["id"]), orphan_candidate_count=1
    )


def test_a_bid_is_refused_before_opening_and_after_closing(api):
    """The bid window is open at exactly one point in the procurement lifecycle.

    A DRAFT solicitation and an EVALUATING one both refuse the same well-formed bid with
    the same error, and neither refusal leaves a row behind; between them the identical
    payload is accepted and priced against the standard basket.

    PRD: "A bid may only be submitted into a solicitation whose `status` is `OPEN`; any
    other procurement state is rejected with `ERR_SOLICITATION_NOT_OPEN` (HTTP 409)."

    Design: Corner/validations/bidding_is_rejected_before_open_and_after_close_but_accepted_while_open
    """
    first = fx.make_contractor(
        api,
        name="Bighorn Plugging",
        license_number="P-60001",
        bond_amount_cents=2500000,
        performance_score=89,
    )
    second = fx.make_contractor(
        api,
        name="Teton Cementing",
        license_number="P-60002",
        bond_amount_cents=2500000,
        performance_score=91,
    )
    solicitation = fx.make_solicitation(
        api, scope_description="district 5 orphan well plugging"
    )
    solicitation_id = solicitation["id"]
    open_window_rates = {
        "cement_per_sack_cents": 4000,
        "rig_day_rate_cents": 800000,
        "casing_per_ft_cents": 1200,
        "mobilization_fee_cents": 2400000,
    }
    payload = f.bid_payload(first["id"], rates=open_window_rates, technical_score=80)

    too_early = api.create_bid(solicitation_id, payload, users.PROCUREMENT)
    validate_error(too_early, e.ERR_SOLICITATION_NOT_OPEN, 409)
    assert_fields(fx.read_solicitation(api, solicitation_id), status="DRAFT")
    assert_page(
        api.list_bids(users.PROCUREMENT, {"solicitation_id": solicitation_id}),
        0,
        expected_total=0,
    )

    fx.advance_solicitation(api, solicitation_id, "OPEN")
    accepted = validate_success(
        api.create_bid(solicitation_id, payload, users.PROCUREMENT), 201
    )
    assert_fields(accepted, status="SUBMITTED")
    assert_cents(
        accepted["evaluated_unit_cost_cents"], 7040000, "evaluated_unit_cost_cents"
    )

    fx.advance_solicitation(api, solicitation_id, "CLOSE")
    too_late = api.create_bid(
        solicitation_id,
        f.bid_payload(second["id"], rates=LATE_BID_RATES, technical_score=85),
        users.PROCUREMENT,
    )
    validate_error(too_late, e.ERR_SOLICITATION_NOT_OPEN, 409)
    assert_fields(fx.read_solicitation(api, solicitation_id), status="EVALUATING")

    assert_page(
        api.list_bids(users.PROCUREMENT, {"solicitation_id": solicitation_id}),
        1,
        expected_total=1,
    )
    assert_page(
        api.list_bids(users.PROCUREMENT, {"contractor_id": second["id"]}),
        0,
        expected_total=0,
    )


def test_a_grant_expiring_at_the_clock_instant_cannot_be_reported_on(api):
    """Reportability is judged against `expires_at`, not against the stored status.

    Both grants are still ACTIVE, so only the instant decides: the one whose authority
    lapses exactly now is refused, while the one that survives one more day generates a
    period with all three computed figures at their empty values.

    PRD: "A source that is `EXPIRED`, or whose `expires_at` is at or before the logical
    clock, is rejected with `ERR_FUNDING_SOURCE_EXPIRED`."

    Design: Corner/validations/grant_report_on_a_source_expiring_at_the_clock_instant_is_rejected
    """
    closing_today = fx.make_funding_source(
        api,
        kind="FEDERAL_GRANT",
        name="FY25 orphan well grant closing today",
        authorized_cents=5000000,
        expires_at="2026-08-01T00:00:00Z",
        federal_match_required_pct=40,
    )
    closing_tomorrow = fx.make_funding_source(
        api,
        kind="FEDERAL_GRANT",
        name="FY26 orphan well grant closing tomorrow",
        authorized_cents=5000000,
        expires_at="2026-08-02T00:00:00Z",
        federal_match_required_pct=40,
    )
    assert_fields(closing_today, status="ACTIVE", reporting_required=True)
    assert_fields(closing_tomorrow, status="ACTIVE", reporting_required=True)

    refused = api.create_grant_report(
        closing_today["id"],
        f.grant_report_payload("2026-07-01", "2026-07-31"),
        users.FUNDING,
    )
    validate_error(refused, e.ERR_FUNDING_SOURCE_EXPIRED, 409)
    assert_fields(fx.read_source(api, closing_today["id"]), status="ACTIVE")
    assert_page(
        api.list_grant_reports(closing_today["id"], users.FUNDING), 0, expected_total=0
    )

    report = fx.make_grant_report(
        api, closing_tomorrow["id"], "2026-07-01", "2026-07-31"
    )
    assert_fields(
        report,
        status="DUE",
        source_id=closing_tomorrow["id"],
        period_start="2026-07-01",
        period_end="2026-07-31",
        wells_plugged_count=0,
    )
    assert_cents(report["reported_cost_cents"], 0, "reported_cost_cents")
    assert_score(report["federal_share_pct"], 0.00, "federal_share_pct")


def test_entry_is_refused_one_day_before_the_supplied_notice_window_closes(api):
    """The notice window is measured from the supplied waiting period, not the default.

    The request carries 45 days rather than the statutory-entry default of 30, so the
    window closes on 2026-09-15; the day before is still inside it and is refused, and
    the closing instant itself is enough.

    PRD: "If the logical clock is strictly before the row's `window_end_at` - that is,
    strictly before `notice_sent_at` plus `waiting_period_days` days - the order is
    rejected with `ERR_STATUTORY_NOTICE_PERIOD_ACTIVE` (HTTP 422)."

    Design: Corner/validations/entry_cannot_be_ordered_one_day_before_the_supplied_notice_window_ends
    """
    operator = fx.make_operator(
        api,
        name="Wind River Petroleum",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=250000,
    )
    well = fx.make_well(api, operator["id"], **SOLVENT_WELL)
    access = fx.open_site_access(
        api, well["id"], mode="STATUTORY_ENTRY", waiting_period_days=45
    )
    assert_fields(
        access,
        notice_sent_at="2026-08-01T00:00:00Z",
        waiting_period_days=45,
        window_end_at="2026-09-15T00:00:00Z",
    )
    assert access["window_end_at"][:10] != "2026-08-31", (
        "the 30 day statutory default must not override the supplied 45 days: %r"
        % (access["window_end_at"],)
    )

    fx.set_clock(api, "2026-09-14T00:00:00Z")
    refused = api.resolve_site_access(
        access["id"],
        f.site_access_resolution_payload("ORDER_ENTRY", "W.S. 30-5-104(d)(vi)"),
        users.ADMIN,
    )
    validate_error(refused, e.ERR_STATUTORY_NOTICE_PERIOD_ACTIVE, 422)
    still_pending = fx.read_site_access(api, access["id"])
    assert_fields(still_pending, status="REQUESTED")
    assert_null_fields(still_pending, "legal_authority_citation", "resolved_at")
    assert_fields(fx.read_well(api, well["id"]), access_status="ACCESS_PENDING")

    fx.set_clock(api, "2026-09-15T00:00:00Z")
    ordered = fx.resolve_site_access(
        api, access["id"], "ORDER_ENTRY", "W.S. 30-5-104(d)(vi)"
    )
    assert_fields(
        ordered,
        status="ENTRY_ORDERED",
        resolved_at="2026-09-15T00:00:00Z",
        legal_authority_citation="W.S. 30-5-104(d)(vi)",
    )
    assert_cents(ordered["compensation_cents"], 0, "compensation_cents")
    assert_fields(fx.read_well(api, well["id"]), access_status="ENTRY_ORDERED")


def test_revegetation_cannot_start_without_a_pit_closure_or_before_day_ninety(api):
    """Both limbs of the revegetation wait are refused with the same error.

    With no pit closure at all there is no timestamp to measure from, so the start is
    refused outright rather than measured against an assumed epoch; once the pit closes on
    2026-08-01 the 90th day is 2026-10-30, so 2026-10-29 is still one day short.

    PRD: "If the pit closure task is not complete - it has no `completed_at` yet - or
    fewer than 90 days have passed since it completed, the start is rejected with
    `ERR_REVEGETATION_WAITING_PERIOD` (HTTP 422)."

    Design: Corner/validations/revegetation_cannot_start_before_pit_closure_or_before_ninety_days
    """
    bundle = fx.make_plugged_job(api)
    job_id = bundle["job"]["id"]
    equipment = fx.task_by_type(bundle["tasks"], "EQUIPMENT_REMOVAL")
    pit = fx.task_by_type(bundle["tasks"], "PIT_CLOSURE")
    revegetation = fx.task_by_type(bundle["tasks"], "REVEGETATION")
    start = f.task_progress_payload("START", "seeding crew on site")

    assert_null_fields(fx.read_task(api, pit["id"]), "completed_at")
    no_pit_closure = api.progress_reclamation_task(
        revegetation["id"], start, users.INSPECTOR
    )
    validate_error(no_pit_closure, e.ERR_REVEGETATION_WAITING_PERIOD, 422)
    refused = fx.read_task(api, revegetation["id"])
    assert_fields(refused, status="PENDING")
    assert_null_fields(refused, "inspected_by_user_id", "notes", "completed_at")

    fx.complete_task(api, pit["id"], "reserve pit backfilled")
    assert_fields(
        fx.read_task(api, pit["id"]),
        status="COMPLETE",
        completed_at="2026-08-01T00:00:00Z",
    )

    fx.set_clock(api, "2026-10-29T00:00:00Z")
    day_eighty_nine = api.progress_reclamation_task(
        revegetation["id"], start, users.INSPECTOR
    )
    validate_error(day_eighty_nine, e.ERR_REVEGETATION_WAITING_PERIOD, 422)
    assert_fields(fx.read_task(api, revegetation["id"]), status="PENDING")

    fx.set_clock(api, "2026-10-30T00:00:00Z")
    started = validate_success(
        api.progress_reclamation_task(revegetation["id"], start, users.INSPECTOR), 200
    )
    assert_fields(started, status="IN_PROGRESS")

    job = fx.read_job(api, job_id)
    assert_fields(job, status="PLUGGED")
    assert_null_fields(job, "reclaimed_at")
    assert_fields(fx.read_task(api, equipment["id"]), status="PENDING")


def test_revegetation_cannot_be_passed_while_a_sibling_task_is_outstanding(api):
    """The final sign-off reads its two siblings, not the row being advanced.

    The revegetation task is perfectly IN_PROGRESS and well past its 90 day wait, yet the
    pass is refused while equipment removal is still PENDING; clearing the sibling makes
    the identical call carry the job and the well all the way to reclamation.

    PRD: "if either the `EQUIPMENT_REMOVAL` or the `PIT_CLOSURE` task of that job is not
    `COMPLETE`, the pass is rejected with `ERR_RECLAMATION_INCOMPLETE` (HTTP 422)."

    Design: Corner/validations/revegetation_pass_is_rejected_while_a_sibling_task_is_outstanding
    """
    bundle = fx.make_plugged_job(api)
    job_id = bundle["job"]["id"]
    well_id = bundle["well"]["id"]
    equipment = fx.task_by_type(bundle["tasks"], "EQUIPMENT_REMOVAL")
    pit = fx.task_by_type(bundle["tasks"], "PIT_CLOSURE")
    revegetation = fx.task_by_type(bundle["tasks"], "REVEGETATION")

    fx.complete_task(api, pit["id"], "reserve pit backfilled")
    fx.set_clock(api, "2026-10-30T00:00:00Z")
    fx.progress_task(api, revegetation["id"], "START", "native seed mix drilled")
    assert_fields(fx.read_task(api, equipment["id"]), status="PENDING")

    pass_payload = f.task_progress_payload("PASS", "70 percent cover established")
    too_early = api.progress_reclamation_task(
        revegetation["id"], pass_payload, users.INSPECTOR
    )
    validate_error(too_early, e.ERR_RECLAMATION_INCOMPLETE, 422)
    held = fx.read_task(api, revegetation["id"])
    assert_fields(held, status="IN_PROGRESS")
    assert_null_fields(held, "completed_at")
    job = fx.read_job(api, job_id)
    assert_fields(job, status="PLUGGED")
    assert_null_fields(job, "reclaimed_at")
    assert_fields(fx.read_well(api, well_id), status="PLUGGED")

    fx.progress_task(api, equipment["id"], "START")
    cleared = fx.progress_task(
        api, equipment["id"], "PASS", "pumping unit and tank battery removed"
    )
    assert_fields(
        cleared, status="COMPLETE", completed_at="2026-10-30T00:00:00Z"
    )

    signed_off = validate_success(
        api.progress_reclamation_task(
            revegetation["id"], pass_payload, users.INSPECTOR
        ),
        200,
    )
    assert_fields(
        signed_off, status="COMPLETE", completed_at="2026-10-30T00:00:00Z"
    )
    assert_fields(
        fx.read_job(api, job_id),
        status="RECLAIMED",
        reclaimed_at="2026-10-30T00:00:00Z",
    )
    assert_fields(fx.read_well(api, well_id), status="RECLAIMED")
    assert_cents(
        fx.read_operator(api, bundle["operator"]["id"])["required_bond_cents"],
        0,
        "required_bond_cents",
    )


def test_a_job_cannot_be_ordered_under_a_suspended_contract(api):
    """Ordering work reads a state two entities away from the request.

    The contract was disabled indirectly, through its contractor's licence, and the well is
    already ORPHAN_CONFIRMED so the well gate cannot mask this one; reinstating the licence
    makes the identical payload succeed and obligates the estimate.

    PRD: "And the contract must be usable - a contract whose `status` is `SUSPENDED` or
    `CLOSED` is rejected with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 422)."

    Design: Corner/validations/scheduling_against_a_suspended_contract_is_rejected_then_accepted_after_reinstatement
    """
    orphan = fx.make_confirmed_orphan_well(api)
    procurement = fx.make_active_contract(api)
    well_id = orphan["well"]["id"]
    contract_id = procurement["contract"]["id"]

    fx.set_license_status(
        api, procurement["contractor"]["id"], "SUSPEND_LICENSE", "expired bonding rider"
    )
    assert_fields(fx.read_contract(api, contract_id), status="SUSPENDED")

    payload = f.plugging_job_payload(
        well_id, contract_id, scheduled_start="2026-08-05T00:00:00Z"
    )
    refused = api.create_plugging_job(payload, users.ADMIN)
    validate_error(refused, e.ERR_CONTRACT_NOT_ACTIVE, 422)

    assert_fields(fx.read_well(api, well_id), status="ORPHAN_CONFIRMED")
    assert_cents(
        fx.read_contract(api, contract_id)["obligated_cents"], 0, "obligated_cents"
    )
    assert_page(
        api.list_plugging_jobs(users.ADMIN, {"well_id": well_id}), 0, expected_total=0
    )

    fx.set_license_status(
        api, procurement["contractor"]["id"], "REINSTATE", "bonding rider refiled"
    )
    job = validate_success(api.create_plugging_job(payload, users.ADMIN), 201)
    assert_fields(
        job, status="SCHEDULED", crew_window_end_at="2026-08-10T00:00:00Z"
    )
    assert_cents(
        job["plugging_cost_estimate_cents"], 6070196, "plugging_cost_estimate_cents"
    )

    contract = fx.read_contract(api, contract_id)
    assert_fields(contract, status="ACTIVE")
    assert_cents(contract["obligated_cents"], 6070196, "obligated_cents after ordering")
    assert_fields(fx.read_well(api, well_id), status="PLUGGING_SCHEDULED")


def test_a_transfer_into_a_delinquent_operator_holding_an_orphan_is_refused(api):
    """The second limb of the transferee gate turns on a computed count.

    An INSOLVENT transferee is refused on its state alone; the DELINQUENT one is refused
    only because it is already accumulating orphan candidates, which a state-list-only
    reading would let through. The ACTIVE transferee with adequate assurance is accepted.

    PRD: "when the receiving operator's `status` is `INSOLVENT` or `REVOKED`, or when it is
    `DELINQUENT` and its `orphan_candidate_count` is greater than zero, the request is
    rejected with `ERR_TRANSFER_TO_INSOLVENT_OPERATOR` (HTTP 422)."

    Design: Corner/validations/transfers_to_insolvent_and_to_delinquent_with_orphans_are_both_rejected
    """
    releasing = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=250000,
    )
    well = fx.make_well(api, releasing["id"])

    insolvent = fx.make_operator(
        api,
        name="Absaroka Minerals Inc",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=250000,
    )
    fx.enforce(api, insolvent["id"], "DECLARE_INSOLVENT", "chapter 7 filing")

    delinquent = fx.make_operator(
        api,
        name="Shoshone Shell Co",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=1,
    )
    delinquent_well = fx.make_well(api, delinquent["id"], spud_year=1968)
    determination = fx.open_determination(
        api, delinquent_well["id"], inspector_notes="abandoned wellhead"
    )
    fx.submit_determination(api, determination["id"])

    healthy = fx.make_operator(
        api,
        name="Teton Basin Resources",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=250000,
    )

    assert_fields(fx.read_operator(api, insolvent["id"]), status="INSOLVENT")
    assert_fields(
        fx.read_operator(api, delinquent["id"]),
        status="DELINQUENT",
        orphan_candidate_count=1,
    )

    into_insolvent = api.create_well_transfer(
        well["id"], f.transfer_payload(insolvent["id"]), users.ADMIN
    )
    validate_error(into_insolvent, e.ERR_TRANSFER_TO_INSOLVENT_OPERATOR, 422)

    into_delinquent = api.create_well_transfer(
        well["id"], f.transfer_payload(delinquent["id"]), users.ADMIN
    )
    validate_error(into_delinquent, e.ERR_TRANSFER_TO_INSOLVENT_OPERATOR, 422)

    accepted = validate_success(
        api.create_well_transfer(
            well["id"], f.transfer_payload(healthy["id"]), users.ADMIN
        ),
        201,
    )
    assert_fields(
        accepted,
        status="PENDING",
        from_operator_id=releasing["id"],
        to_operator_id=healthy["id"],
    )
    assert_cents(
        accepted["transferee_required_bond_cents"],
        250000,
        "transferee_required_bond_cents",
    )
    assert_null_fields(accepted, "approved_at")

    assert_page(
        api.list_well_transfers(users.ADMIN, {"well_id": well["id"]}),
        1,
        expected_total=1,
    )
    assert_fields(fx.read_well(api, well["id"]), operator_id=releasing["id"])


def test_an_override_naming_another_operators_forfeited_bond_is_refused(api):
    """Seized assurance is ring-fenced to the operator it was seized from.

    Two forfeited bonds are large enough to fund the job outright and differ only in whose
    assurance they hold; the foreign one is refused without touching a single figure, and
    the well owner's own bond then funds the whole estimate at rank 1.

    PRD: "A named `FORFEITED_BOND` source whose `bond_operator_id` differs from the
    `operator_id` of the job's well is rejected with `ERR_FORFEITED_BOND_OPERATOR_MISMATCH`
    (HTTP 422) - one operator's seized assurance may not subsidize another operator's well."

    Design: Corner/validations/override_source_naming_another_operators_forfeited_bond_is_rejected
    """
    owner = fx.make_unbonded_operator(api, name="Cottonwood Energy LLC")
    stranger = fx.make_operator(
        api, name="Absaroka Minerals Inc", bond_amount_cents=5000000
    )
    orphan = fx.make_confirmed_orphan_well(api, operator=owner)
    procurement = fx.make_active_contract(api)
    job = fx.make_plugging_job(
        api,
        orphan["well"]["id"],
        procurement["contract"]["id"],
        scheduled_start="2026-08-05T00:00:00Z",
    )
    assert_cents(
        job["plugging_cost_estimate_cents"], 6070196, "plugging_cost_estimate_cents"
    )

    foreign = fx.make_funding_source(
        api,
        kind="FORFEITED_BOND",
        name="Absaroka Minerals forfeited bond",
        authorized_cents=6070196,
        expires_at="2027-12-31T00:00:00Z",
        bond_operator_id=stranger["id"],
    )
    own = fx.make_funding_source(
        api,
        kind="FORFEITED_BOND",
        name="Cottonwood Energy forfeited bond",
        authorized_cents=6070196,
        expires_at="2027-12-31T00:00:00Z",
        bond_operator_id=owner["id"],
    )

    refused = api.create_funding_commitments(
        job["id"], users.FUNDING, {"override_source_id": foreign["id"]}
    )
    validate_error(refused, e.ERR_FORFEITED_BOND_OPERATOR_MISMATCH, 422)
    assert_cents(
        fx.read_source(api, foreign["id"])["committed_cents"],
        0,
        "foreign committed_cents",
    )
    assert_cents(fx.read_job(api, job["id"])["funded_cents"], 0, "funded_cents")
    assert_page(
        api.list_funding_allocations(users.FUNDING, {"job_id": job["id"]}),
        0,
        expected_total=0,
    )

    allocations = fx.commit_funding(api, job["id"], override_source_id=own["id"])
    assert len(allocations) == 1, "expected exactly one allocation, got %r" % (
        allocations,
    )
    assert_fields(allocations[0], source_id=own["id"], waterfall_rank=1)
    assert_cents(allocations[0]["allocated_cents"], 6070196, "allocated_cents")

    funded_source = fx.read_source(api, own["id"])
    assert_fields(funded_source, status="EXHAUSTED")
    assert_cents(funded_source["committed_cents"], 6070196, "own committed_cents")
    untouched = fx.read_source(api, foreign["id"])
    assert_fields(untouched, status="ACTIVE")
    assert_cents(untouched["committed_cents"], 0, "foreign committed_cents at the end")
    assert_cents(
        fx.read_job(api, job["id"])["funded_cents"], 6070196, "funded_cents at the end"
    )
