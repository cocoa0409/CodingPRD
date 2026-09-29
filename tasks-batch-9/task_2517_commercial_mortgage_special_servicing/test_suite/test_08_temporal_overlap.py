"""Two temporal reservations with opposite interval conventions: the appraisal
coverage window is half-open, the approved lease term is closed.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ASSET_MANAGER,
    ASSET_MANAGER_2,
    COMMITTEE_OFFICER,
    MASTER_SERVICER,
)


# ==========================================================================
# The half-open appraisal coverage window, and its release on rejection
# ==========================================================================
def _loan_with_one_covered_window(api):
    """A loan whose only live coverage window is [2026-08-01, 2027-08-01)."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-W1"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-W01", "maturity_date": "2029-06-01T00:00:00Z"},
        event_factory=fx.record_bankruptcy_event,
    )
    incumbent = fx.accepted_appraisal(
        api, built["loan_id"], value_usd=9000000, as_of_date="2026-08-01T00:00:00Z"
    )
    return built["loan_id"], incumbent


def _rejected_appraisal_covering_the_later_year(api, loan_id):
    """An appraisal whose window would be [2027-09-01, 2028-09-01) but for the
    rejection that releases it."""
    appraisal = fx.order_appraisal(
        api, loan_id, ordered_on="2026-08-01T00:00:00Z", appraiser_firm="Beta Valuation"
    )
    fx.receive_appraisal(api, appraisal["id"], 8800000, "2027-09-01T00:00:00Z")
    return validate_success(
        api.set_appraisal_status(
            appraisal["id"],
            f.status_payload(
                "REJECTED",
                rejection_reason="comparable set rejected by the special servicer",
            ),
            ASSET_MANAGER_2,
        )
    )


def test_a_window_ending_the_day_the_new_one_starts_does_not_overlap(api):
    """The incumbent window's exclusive end is available to the successor.

    The PRD: "Because the interval is half-open, a new window beginning exactly on
    an existing window's `coverage_end_date` is adjacent rather than overlapping
    and is accepted, whereas beginning one day earlier is refused."

    Design: Difficulty/resource_temporal_overlap/appraisal_coverage_window_half_open_adjacency_and_release_on_rejection
    """
    loan_id, incumbent = _loan_with_one_covered_window(api)
    assert incumbent["coverage_start_date"].startswith("2026-08-01")
    assert incumbent["coverage_end_date"].startswith("2027-08-01")

    fx.set_clock(api, "2027-08-01T00:00:00Z")
    successor = fx.order_appraisal(
        api, loan_id, ordered_on="2027-06-01T00:00:00Z", appraiser_firm="Gamma Valuation"
    )
    received = validate_success(
        api.set_appraisal_status(
            successor["id"],
            f.appraisal_received_payload(8500000, "2027-08-01T00:00:00Z"),
            ASSET_MANAGER,
        )
    )
    a.assert_status(received, "RECEIVED")
    assert received["coverage_start_date"].startswith("2027-08-01")
    assert received["coverage_end_date"].startswith("2028-08-01")
    assert received["received_on"].startswith("2027-08-01")


def test_a_window_starting_one_day_earlier_overlaps_and_is_refused(api):
    """One day inside the incumbent's half-open window is contention.

    The PRD: "Before storing anything, the service checks every other appraisal on
    the same `loan_id` whose status is `RECEIVED` or `ACCEPTED` and refuses the
    transition with `ERR_APPRAISAL_WINDOW_OVERLAP` if any of their windows overlaps
    the new one."

    Design: Difficulty/resource_temporal_overlap/appraisal_coverage_window_half_open_adjacency_and_release_on_rejection
    """
    loan_id, _ = _loan_with_one_covered_window(api)
    fx.set_clock(api, "2027-08-01T00:00:00Z")
    successor = fx.order_appraisal(
        api, loan_id, ordered_on="2027-06-01T00:00:00Z", appraiser_firm="Gamma Valuation"
    )

    response = api.set_appraisal_status(
        successor["id"],
        f.appraisal_received_payload(8500000, "2027-07-31T00:00:00Z"),
        ASSET_MANAGER,
    )
    validate_error(response, e.ERR_APPRAISAL_WINDOW_OVERLAP, 409)

    untouched = validate_success(api.get_appraisal(successor["id"], ASSET_MANAGER))
    a.assert_status(untouched, "ORDERED")
    a.assert_fields_null(
        untouched, "value_usd", "as_of_date", "coverage_start_date", "coverage_end_date"
    )
    a.assert_version_is(untouched, successor["version"], "appraisal")


def test_a_rejected_appraisal_releases_the_window_it_was_holding(api):
    """The rejected report's window is not contended by anyone.

    The PRD: "Appraisals in `REJECTED`, `SUPERSEDED` or `CANCELLED` release their
    windows entirely, so a later appraisal may occupy the same span."

    Design: Difficulty/resource_temporal_overlap/appraisal_coverage_window_half_open_adjacency_and_release_on_rejection
    """
    loan_id, _ = _loan_with_one_covered_window(api)
    rejected = _rejected_appraisal_covering_the_later_year(api, loan_id)
    a.assert_status(rejected, "REJECTED")

    fx.set_clock(api, "2027-08-01T00:00:00Z")
    successor = fx.order_appraisal(
        api, loan_id, ordered_on="2027-06-01T00:00:00Z", appraiser_firm="Gamma Valuation"
    )
    received = validate_success(
        api.set_appraisal_status(
            successor["id"],
            f.appraisal_received_payload(8500000, "2027-08-01T00:00:00Z"),
            ASSET_MANAGER,
        )
    )
    assert received["coverage_start_date"].startswith("2027-08-01")
    assert received["coverage_end_date"].startswith("2028-08-01")


def test_neither_reception_probe_creates_an_appraisal_reduction(api):
    """Reduction creation hangs off acceptance, not reception.

    The PRD: "Its consequences are the ones acceptance does *not* have: the
    coverage window is released so that a later appraisal may occupy the same span
    without triggering `ERR_APPRAISAL_WINDOW_OVERLAP`, no appraisal reduction is
    created, and the loan's `appraisal_required` flag is **not** cleared — the asset
    still needs a valuation."

    Design: Difficulty/resource_temporal_overlap/appraisal_coverage_window_half_open_adjacency_and_release_on_rejection
    """
    loan_id, _ = _loan_with_one_covered_window(api)
    reductions_after_acceptance = len(fx.reductions_for_loan(api, loan_id))

    _rejected_appraisal_covering_the_later_year(api, loan_id)
    fx.set_clock(api, "2027-08-01T00:00:00Z")
    successor = fx.order_appraisal(
        api, loan_id, ordered_on="2027-06-01T00:00:00Z", appraiser_firm="Gamma Valuation"
    )
    validate_error(
        api.set_appraisal_status(
            successor["id"],
            f.appraisal_received_payload(8500000, "2027-07-31T00:00:00Z"),
            ASSET_MANAGER,
        ),
        e.ERR_APPRAISAL_WINDOW_OVERLAP,
    )
    validate_success(
        api.set_appraisal_status(
            successor["id"],
            f.appraisal_received_payload(8500000, "2027-08-01T00:00:00Z"),
            ASSET_MANAGER,
        )
    )

    assert len(fx.reductions_for_loan(api, loan_id)) == reductions_after_acceptance, (
        "a rejection and two reception probes create no appraisal reduction"
    )


# ==========================================================================
# The closed lease term, reserved on the pair (loan, suite)
# ==========================================================================
def _loan_with_an_approved_anchor_lease(api):
    """Suite S-300 is let on the closed term [2027-01-01, 2031-12-31]."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-L1"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-L01", "maturity_date": "2029-06-01T00:00:00Z"},
        event_factory=lambda client, loan_id: fx.record_transfer_event(
            client,
            loan_id,
            event_code="IMMINENT_DEFAULT",
            occurred_on="2026-07-15T00:00:00Z",
            evidence_note="borrower notified imminent monetary default",
            days_delinquent_at_event=None,
            imminent_default_certified=True,
        ),
    )
    loan_id = built["loan_id"]
    fx.accepted_appraisal(api, loan_id, value_usd=9000000)

    incumbent = _lease_awaiting_approval(
        api,
        built["trust_id"],
        loan_id,
        suite_code="S-300",
        lease_commencement_date="2027-01-01T00:00:00Z",
        lease_expiration_date="2031-12-31T00:00:00Z",
    )
    approved = fx.approve_request(api, incumbent["request_id"])
    return built["trust_id"], loan_id, approved


def _lease_awaiting_approval(api, trust_id, loan_id, **lease_terms):
    """A LEASE_APPROVAL request in CONSULTATION_PENDING with a CONSENTED reply."""
    return fx.consultation_pending_request(
        api,
        trust_id,
        loan_id,
        submitter=fx.submit_lease_request,
        analysis=f.lease_analysis_payload(),
        **lease_terms,
    )


def test_the_approved_incumbent_term_is_recorded_with_its_margin(api):
    """The first lease approval succeeds and stamps the deciding officer.

    The PRD: "On approval the service stamps `decided_on` with the current logical
    clock and records the deciding officer in `decided_by_user_id`, and for a
    `MODIFICATION` it sets the loan's `is_modified` flag to true."

    Design: Difficulty/resource_temporal_overlap/lease_term_closed_interval_adjacency_rejected_and_scoped_by_suite
    """
    _, loan_id, approved = _loan_with_an_approved_anchor_lease(api)
    a.assert_status(approved, "APPROVED")
    a.assert_money(
        approved["servicing_standard_margin_usd"], 100000.00, "servicing_standard_margin_usd"
    )
    a.assert_status(
        approved, "SERVICING_STANDARD_MET", "servicing_standard_conclusion"
    )
    assert approved["decided_on"].startswith("2026-08-01")
    assert approved["decided_by_user_id"] == "cmte-001"

    loan = fx.read_loan(api, loan_id, MASTER_SERVICER)
    assert loan["is_modified"] is False, (
        "the is_modified side effect fires only for a MODIFICATION request"
    )


def test_a_term_starting_on_the_incumbents_expiry_day_overlaps(api):
    """The shared closed endpoint 2031-12-31 is contention.

    The PRD: "A new term starting on the very day an existing term expires
    therefore does overlap and is refused with `ERR_LEASE_TERM_OVERLAP`; starting
    the following day is accepted."

    Design: Difficulty/resource_temporal_overlap/lease_term_closed_interval_adjacency_rejected_and_scoped_by_suite
    """
    trust_id, loan_id, _ = _loan_with_an_approved_anchor_lease(api)
    contender = _lease_awaiting_approval(
        api,
        trust_id,
        loan_id,
        suite_code="S-300",
        lease_commencement_date="2031-12-31T00:00:00Z",
        lease_expiration_date="2036-12-31T00:00:00Z",
        lease_base_rent_annual_usd=510000,
        requested_terms_note="replacement tenant commencing on the incumbent expiration date",
    )

    response = api.set_borrower_request_status(
        contender["request_id"], f.status_payload("APPROVED"), COMMITTEE_OFFICER
    )
    validate_error(response, e.ERR_LEASE_TERM_OVERLAP, 409)

    unchanged = validate_success(
        api.get_borrower_request(contender["request_id"], COMMITTEE_OFFICER)
    )
    a.assert_status(unchanged, "CONSULTATION_PENDING")
    a.assert_fields_null(unchanged, "decided_on", "decided_by_user_id")


def test_a_term_starting_the_following_day_is_accepted(api):
    """Commencing 2032-01-01 shares no day with the incumbent.

    The PRD: "For a `LEASE_APPROVAL`, approval carries one further test: no other
    request on the same loan and the same `suite_code` that is already `APPROVED`
    may have a lease term overlapping this one, where both terms are treated as
    **closed** intervals running from `lease_commencement_date` through
    `lease_expiration_date` inclusive."

    Design: Difficulty/resource_temporal_overlap/lease_term_closed_interval_adjacency_rejected_and_scoped_by_suite
    """
    trust_id, loan_id, _ = _loan_with_an_approved_anchor_lease(api)
    successor = _lease_awaiting_approval(
        api,
        trust_id,
        loan_id,
        suite_code="S-300",
        lease_commencement_date="2032-01-01T00:00:00Z",
        lease_expiration_date="2036-12-31T00:00:00Z",
        lease_base_rent_annual_usd=510000,
        requested_terms_note="replacement tenant commencing the day after expiration",
    )

    approved = validate_success(
        api.set_borrower_request_status(
            successor["request_id"], f.status_payload("APPROVED"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(approved, "APPROVED")
    assert approved["decided_on"].startswith("2026-08-01")


def test_the_same_shared_day_on_a_different_suite_is_accepted(api):
    """The reservation is keyed on the pair, not on the loan.

    The PRD: "The pairing of a loan with a `suite_code` is the occupancy resource
    the overlap rule guards."

    Design: Difficulty/resource_temporal_overlap/lease_term_closed_interval_adjacency_rejected_and_scoped_by_suite
    """
    trust_id, loan_id, _ = _loan_with_an_approved_anchor_lease(api)
    other_suite = _lease_awaiting_approval(
        api,
        trust_id,
        loan_id,
        suite_code="S-400",
        lease_commencement_date="2031-12-31T00:00:00Z",
        lease_expiration_date="2036-12-31T00:00:00Z",
        lease_base_rent_annual_usd=260000,
        requested_terms_note="different suite, same commencement date as the refused request",
    )

    approved = validate_success(
        api.set_borrower_request_status(
            other_suite["request_id"], f.status_payload("APPROVED"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(approved, "APPROVED")
    assert approved["suite_code"] == "S-400"


def test_a_request_refused_for_overlap_reserves_nothing_itself(api):
    """Contention is evaluated only against rows that are already APPROVED.

    The PRD: "no other request on the same loan and the same `suite_code` that is
    already `APPROVED` may have a lease term overlapping this one"

    Design: Difficulty/resource_temporal_overlap/lease_term_closed_interval_adjacency_rejected_and_scoped_by_suite
    """
    trust_id, loan_id, _ = _loan_with_an_approved_anchor_lease(api)
    refused = _lease_awaiting_approval(
        api,
        trust_id,
        loan_id,
        suite_code="S-300",
        lease_commencement_date="2031-12-31T00:00:00Z",
        lease_expiration_date="2036-12-31T00:00:00Z",
        lease_base_rent_annual_usd=510000,
        requested_terms_note="replacement tenant commencing on the incumbent expiration date",
    )
    validate_error(
        api.set_borrower_request_status(
            refused["request_id"], f.status_payload("APPROVED"), COMMITTEE_OFFICER
        ),
        e.ERR_LEASE_TERM_OVERLAP,
    )

    successor = _lease_awaiting_approval(
        api,
        trust_id,
        loan_id,
        suite_code="S-300",
        lease_commencement_date="2032-01-01T00:00:00Z",
        lease_expiration_date="2036-12-31T00:00:00Z",
        lease_base_rent_annual_usd=510000,
        requested_terms_note="replacement tenant commencing the day after expiration",
    )
    approved = validate_success(
        api.set_borrower_request_status(
            successor["request_id"], f.status_payload("APPROVED"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(approved, "APPROVED")

    validate_error(
        api.set_borrower_request_status(
            refused["request_id"], f.status_payload("APPROVED"), COMMITTEE_OFFICER
        ),
        e.ERR_LEASE_TERM_OVERLAP,
    )
