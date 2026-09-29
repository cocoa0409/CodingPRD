"""Negotiating the sampling plan, tiling the scope and pulling the first invoices."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    agree_agreement,
    api_client,
    counter_agreement,
    create_sample_unit_payload,
    create_sampling_agreement_payload,
    get_success_data,
    read_agreement,
    read_audit,
    revise_agreement,
    revise_agreement_payload,
    setup_proposed_methodology,
    setup_scoped_audit,
    stratum,
    validate_error,
    validate_success,
)

AUDITOR = TEST_USERS["field_auditor_headers"]

SCOPE_START = "2026-01-01"
SCOPE_END = "2026-06-30"
DAY_AFTER_SCOPE = "2026-07-01"
MID_QUARTER = "2026-03-01"
QUARTER_BREAK = "2026-04-01"


def _negotiation_at_the_round_cap():
    """Counter and revise twice, then counter again: round_number stands at 3."""
    ctx = setup_proposed_methodology(confidence_level_bp=9_000, minimum_sample_size=1)
    agreement_id = ctx["agreement"]["id"]
    taxpayer_id = ctx["taxpayer"]["id"]
    counter_agreement(
        agreement_id,
        taxpayer_id,
        counter_note="Sample too small for a quarterly filer",
        requested_minimum_sample_size=4,
    )
    revise_agreement(agreement_id, minimum_sample_size=2)
    counter_agreement(
        agreement_id, taxpayer_id, counter_note="Still short of the requested four units"
    )
    revise_agreement(agreement_id, minimum_sample_size=3)
    counter_agreement(
        agreement_id, taxpayer_id, counter_note="Final objection to the methodology"
    )
    return ctx


def test_each_legal_round_of_the_negotiation_advances_the_round_number():
    """Countering and revising walks the same pair of states, counting rounds.

    PRD 3.3: "Revision is the auditor's reply, available only while the agreement
    is `COUNTERED`. It moves the agreement `COUNTERED → PROPOSED` and increments
    `round_number` by one."
    PRD 3.3: "The requested size is advisory only: it changes nothing about the
    sampling plan until an auditor revision adopts it into `minimum_sample_size`."

    Design: Difficulty/non_linear_state_machine/sampling_agreement_negotiation_cycle_hits_round_cap
    """
    ctx = setup_proposed_methodology(confidence_level_bp=9_000, minimum_sample_size=1)
    agreement_id = ctx["agreement"]["id"]
    assert ctx["agreement"]["round_number"] == 1
    assert ctx["agreement"]["status"] == "PROPOSED"

    countered = counter_agreement(
        agreement_id,
        ctx["taxpayer"]["id"],
        counter_note="Sample too small for a quarterly filer",
        requested_minimum_sample_size=4,
    )
    assert countered["status"] == "COUNTERED"
    assert countered["round_number"] == 1
    assert countered["requested_minimum_sample_size"] == 4
    assert countered["minimum_sample_size"] == 1

    revised = revise_agreement(agreement_id, minimum_sample_size=2)
    assert revised["status"] == "PROPOSED"
    assert revised["round_number"] == 2
    assert revised["minimum_sample_size"] == 2


def test_the_third_round_closes_the_negotiation_to_further_revision():
    """A fourth reply is refused, and the plan stays exactly where round three left it.

    PRD 3.3: "The negotiation cycle `PROPOSED → COUNTERED → PROPOSED` is bounded at
    three rounds: a revision attempted while `round_number` already stands at 3 is
    refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/sampling_agreement_negotiation_cycle_hits_round_cap
    """
    ctx = _negotiation_at_the_round_cap()
    agreement_id = ctx["agreement"]["id"]
    assert read_agreement(agreement_id)["round_number"] == 3

    response = api_client.revise_sampling_agreement(
        agreement_id, revise_agreement_payload(minimum_sample_size=4), AUDITOR
    )
    validate_error(response, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value, 422)

    agreement = read_agreement(agreement_id)
    assert agreement["round_number"] == 3
    assert agreement["status"] == "COUNTERED"
    assert agreement["minimum_sample_size"] == 3
    assert read_audit(ctx["audit"]["id"])["status"] == "SCOPED"


def _two_strata(first_end, second_start):
    return [
        stratum(SCOPE_START, first_end, 4_000_000, 40),
        stratum(second_start, DAY_AFTER_SCOPE, 6_000_000, 60),
    ]


def _propose(audit, strata):
    return api_client.create_sampling_agreement(
        create_sampling_agreement_payload(
            audit["id"],
            audit["version"],
            strata,
            methodology="MEAN_PER_UNIT",
            confidence_level_bp=9_000,
            minimum_sample_size=1,
        ),
        AUDITOR,
    )


def _agreements_of(audit_id):
    return get_success_data(
        api_client.list_sampling_agreements(AUDITOR, params={"audit_id": audit_id})
    )


def test_a_hole_between_two_strata_leaves_the_scope_untiled():
    """A missing month is a gap, and the rejected proposal writes nothing.

    PRD 3.3: "a hole between adjacent strata, a first start later than the scope
    start, or a last end earlier than the day after the scope end are all rejected
    with `ERR_STRATUM_GAP`."

    Design: Difficulty/resource_temporal_overlap/strata_must_tile_the_scope_with_half_open_adjacency
    """
    ctx = setup_scoped_audit(scope_period_start=SCOPE_START, scope_period_end=SCOPE_END)
    audit = ctx["audit"]

    response = _propose(audit, _two_strata(MID_QUARTER, QUARTER_BREAK))
    validate_error(response, ApiErrorId.ERR_STRATUM_GAP.value, 422)

    assert read_audit(audit["id"])["version"] == audit["version"]
    assert _agreements_of(audit["id"]) == []


def test_two_strata_covering_a_common_month_are_an_overlap():
    """A shared month is an overlap, told apart from a gap by its own error.

    PRD 3.3: "Two strata covering a common day are rejected with
    `ERR_STRATUM_OVERLAP`; a hole between adjacent strata, a first start later than
    the scope start, or a last end earlier than the day after the scope end are all
    rejected with `ERR_STRATUM_GAP`."

    Design: Difficulty/resource_temporal_overlap/strata_must_tile_the_scope_with_half_open_adjacency
    """
    ctx = setup_scoped_audit(scope_period_start=SCOPE_START, scope_period_end=SCOPE_END)
    audit = ctx["audit"]

    response = _propose(audit, _two_strata(QUARTER_BREAK, MID_QUARTER))
    validate_error(response, ApiErrorId.ERR_STRATUM_OVERLAP.value, 422)

    assert read_audit(audit["id"])["version"] == audit["version"]
    assert _agreements_of(audit["id"]) == []


def test_adjacent_half_open_strata_tile_the_scope_and_sum_the_population():
    """Adjacency is required, and the accepted plan sums its strata.

    PRD 3.3: "Sorted by start date, each stratum's `period_start` must equal the
    previous stratum's `period_end` — adjacency is required, not merely permitted —
    the first `period_start` must equal the audit's `scope_period_start`, and the
    last `period_end` must equal the audit's `scope_period_end` advanced by one
    day, so that the final scope day is covered by the half-open convention."
    PRD 3.3: "The agreement's `population_base_amount_cents` is the sum of the
    strata's `population_base_amount_cents` and is the denominator population for
    ratio estimation; its `population_unit_count` is the sum of the strata's
    `population_unit_count` and is the multiplier for mean-per-unit projection."

    Design: Difficulty/resource_temporal_overlap/strata_must_tile_the_scope_with_half_open_adjacency
    """
    ctx = setup_scoped_audit(scope_period_start=SCOPE_START, scope_period_end=SCOPE_END)
    audit = ctx["audit"]

    response = _propose(audit, _two_strata(QUARTER_BREAK, QUARTER_BREAK))
    agreement = validate_success(response, 201)

    assert agreement["status"] == "PROPOSED"
    assert agreement["round_number"] == 1
    assert agreement["population_base_amount_cents"] == 10_000_000
    assert agreement["population_unit_count"] == 100
    assert read_audit(audit["id"])["version"] == audit["version"] + 1


SAMPLED_INVOICE_DATE = "2026-03-02"
SAMPLED_INVOICE_CENTS = 100_000


def _unit_body(agreement_id):
    """One undisputed invoice, identical in both attempts."""
    return create_sample_unit_payload(
        agreement_id,
        0,
        SAMPLED_INVOICE_DATE,
        SAMPLED_INVOICE_CENTS,
        invoice_reference="X1-1",
        error_class="NO_ERROR",
    )


def _units_of(agreement_id):
    return get_success_data(
        api_client.list_agreement_sample_units(agreement_id, AUDITOR)
    )


def test_no_invoice_may_be_pulled_before_the_taxpayer_accepts_the_plan():
    """While the plan is only proposed the invoice is refused and nothing is stored.

    PRD 3.4: "Each **sample unit** names the `sampling_agreement_id` it was drawn
    under, which must be the audit's `agreed_agreement_id`; a unit offered against
    any other agreement — a superseded round, or an audit with no accepted
    methodology at all — is refused with `ERR_AGREEMENT_NOT_AGREED`."

    Design: Difficulty/cross_entity_state_dependency/sample_unit_requires_an_agreed_methodology
    """
    ctx = setup_proposed_methodology(
        methodology="MEAN_PER_UNIT", confidence_level_bp=9_000, minimum_sample_size=1
    )
    agreement_id = ctx["agreement"]["id"]
    assert read_agreement(agreement_id)["status"] == "PROPOSED"
    assert read_audit(ctx["audit"]["id"])["status"] == "SCOPED"

    response = api_client.create_sample_unit(_unit_body(agreement_id), AUDITOR)
    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_AGREED.value, 409)

    assert _units_of(agreement_id) == []


def test_the_same_invoice_is_accepted_the_moment_the_plan_is_accepted():
    """Acceptance opens fieldwork, and the unchanged request body now succeeds.

    PRD 3.3: "Acceptance moves the agreement `PROPOSED → AGREED` and cascades: the
    audit's `agreed_agreement_id` is set to that agreement, the audit moves
    `SCOPED → FIELDWORK`, and every other sampling agreement of the same audit
    still in `PROPOSED` or `COUNTERED` moves to `SUPERSEDED`."
    PRD 3.4: "Every new unit sets the audit's `projection_status` to `STALE`, which
    in turn moves any assessment of that audit still in `DRAFT` to `DRAFT_STALE`."

    Design: Difficulty/cross_entity_state_dependency/sample_unit_requires_an_agreed_methodology
    """
    ctx = setup_proposed_methodology(
        methodology="MEAN_PER_UNIT", confidence_level_bp=9_000, minimum_sample_size=1
    )
    agreement_id = ctx["agreement"]["id"]

    agreed = agree_agreement(agreement_id, ctx["taxpayer"]["id"])
    assert agreed["status"] == "AGREED"
    assert read_audit(ctx["audit"]["id"])["status"] == "FIELDWORK"

    unit = validate_success(
        api_client.create_sample_unit(_unit_body(agreement_id), AUDITOR), 201
    )
    assert unit["error_class"] == "NO_ERROR"
    assert unit["error_amount_cents"] == 0
    assert read_audit(ctx["audit"]["id"])["projection_status"] == "STALE"


BOUNDARY_INVOICE_DATE = "2026-04-01"
BOUNDARY_INVOICE_CENTS = 250_000
BOUNDARY_ERROR_CENTS = 15_625


def _two_stratum_fieldwork_audit():
    """Fieldwork audit tiled [01-01,04-01) then [04-01,07-01)."""
    ctx = setup_proposed_methodology(
        methodology="MEAN_PER_UNIT",
        confidence_level_bp=9_000,
        minimum_sample_size=1,
        strata=_two_strata(QUARTER_BREAK, QUARTER_BREAK),
        scope_period_start=SCOPE_START,
        scope_period_end=SCOPE_END,
    )
    ctx["agreement"] = agree_agreement(ctx["agreement"]["id"], ctx["taxpayer"]["id"])
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    return ctx


def _boundary_unit_body(agreement_id, stratum_index):
    return create_sample_unit_payload(
        agreement_id,
        stratum_index,
        BOUNDARY_INVOICE_DATE,
        BOUNDARY_INVOICE_CENTS,
        invoice_reference="O3-BOUNDARY",
        error_class="UNREPORTED_TAXABLE_SALE",
        declared_error_amount_cents=BOUNDARY_ERROR_CENTS,
    )


def test_an_invoice_dated_on_a_boundary_does_not_belong_to_the_earlier_stratum():
    """The earlier stratum ends before its own end date, so the boundary invoice is out.

    PRD 3.4: "It carries the auditor's `invoice_reference` for the document, the
    `invoice_date`, which must fall inside the half-open interval of the declared
    stratum — on or after that stratum's `period_start` and strictly before its
    `period_end`, or the unit is refused with `ERR_INVOICE_DATE_OUT_OF_STRATUM` —
    and the `invoice_amount_cents`, which must be greater than zero and is the
    per-unit base for ratio estimation."

    Design: Difficulty/resource_temporal_overlap/invoice_date_falls_in_exactly_one_half_open_stratum
    """
    ctx = _two_stratum_fieldwork_audit()
    agreement_id = ctx["agreement"]["id"]

    response = api_client.create_sample_unit(
        _boundary_unit_body(agreement_id, 0), AUDITOR
    )
    validate_error(response, ApiErrorId.ERR_INVOICE_DATE_OUT_OF_STRATUM.value, 422)

    assert _units_of(agreement_id) == []


def test_the_boundary_invoice_belongs_to_the_stratum_that_opens_on_that_day():
    """Declared against the later stratum the same invoice is accepted.

    PRD 3.3: "Stratum intervals are half-open: a stratum covers days from its
    `period_start` inclusive to its `period_end` exclusive."
    PRD 3.4: "From these the system computes `error_amount_cents`, which is 0 for
    both `NO_ERROR` and `PENDING`, equals `declared_error_amount_cents` for
    `UNREPORTED_TAXABLE_SALE` and `RATE_ERROR`, and for `CERTIFICATE_DEFECT` is
    `exempt_sale_amount_cents` multiplied by 625 basis points, divided by 10,000
    and rounded half up — the tax on the sale the defective certificate purported
    to exempt."

    Design: Difficulty/resource_temporal_overlap/invoice_date_falls_in_exactly_one_half_open_stratum
    """
    ctx = _two_stratum_fieldwork_audit()
    agreement_id = ctx["agreement"]["id"]

    unit = validate_success(
        api_client.create_sample_unit(_boundary_unit_body(agreement_id, 1), AUDITOR), 201
    )

    assert unit["stratum_index"] == 1
    assert unit["error_amount_cents"] == BOUNDARY_ERROR_CENTS
    assert read_audit(ctx["audit"]["id"])["projection_status"] == "STALE"
