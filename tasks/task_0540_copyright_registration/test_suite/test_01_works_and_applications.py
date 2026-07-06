"""Work registration, application filing, fee computation, and the registration
decision cascade.

Covers Difficulty queue instances: application_fee_multifactor,
registration_issue_depth2, effective_date_receipt_vs_decision,
application_fee_refund_conserves_net; and the entities/calculations/validations
corner instances that exercise the create-and-submit surface.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    NON_EXISTENT_UUID,
    assert_work, assert_application, assert_certificate, assert_same_calendar_date,
)
from test_helpers import factories as fac
from test_helpers import fixtures as fx


# ==========================================================================
# Corner — entities
# ==========================================================================
def test_create_work_returns_initial_state(api, rightsholder_headers):
    """PRD §3.1: "At creation the server records the acting user as owner_user_id,
    sets the work's registration_status to UNREGISTERED, and initializes the
    computed current_owner_name to the author_name."
    PRD §2.4: "The version is an integer that begins at 1 when a resource is created."

    Design: Corner/entities/work_create_success_returns_201
    """
    payload = fac.create_work_payload(author_name="Ann", owner_shares=[{"name": "Ann", "share_bps": 10000}])
    data = validate_success(api.create_work(payload, rightsholder_headers), 201)
    assert_work(data)
    assert data["version"] == 1
    assert data["registration_status"] == "UNREGISTERED"
    assert data["current_owner_name"] == "Ann"


def test_create_work_missing_title_rejected(api, rightsholder_headers):
    """PRD §2.6: "For write endpoints, the body must be well-formed: all required
    fields present, enumerated values valid, integer amounts non-negative, an
    owner_shares list whose share_bps values sum to exactly 10000, and a
    publication_date present whenever the work is published. A violation yields
    ERR_VALIDATION."

    Design: Corner/entities/create_work_missing_title_returns_validation
    """
    payload = fac.create_work_payload()
    payload.pop("title")
    validate_error(api.create_work(payload, rightsholder_headers), ApiErrorId.ERR_VALIDATION)


def test_create_work_owner_shares_bad_sum_rejected(api, rightsholder_headers):
    """PRD §2.6: "an owner_shares list whose share_bps values sum to exactly 10000
    ... A violation yields ERR_VALIDATION."

    Design: Corner/entities/create_work_owner_shares_bad_sum_returns_validation
    """
    payload = fac.create_work_payload(owner_shares=[{"name": "Ann", "share_bps": 9000}])
    validate_error(api.create_work(payload, rightsholder_headers), ApiErrorId.ERR_VALIDATION)


def test_get_nonexistent_work_returns_not_found(api, rightsholder_headers):
    """PRD §2.4: "retrieval of a resource by its path identifier fails with
    ERR_NOT_FOUND when no resource with that id exists."

    Design: Corner/entities/get_work_nonexistent_returns_not_found
    """
    validate_error(api.get_work(NON_EXISTENT_UUID, rightsholder_headers), ApiErrorId.ERR_NOT_FOUND)


def test_application_defaults_applied(api, rightsholder_headers):
    """PRD §3.1: "A newly filed application is created in DRAFT" and "may declare a
    claimant_count (defaulting to 1, and never less than 1) and an is_expedited
    flag (defaulting to false)."

    Design: Corner/entities/application_defaults_applied
    """
    work = fx.create_work()
    data = validate_success(
        api.create_application(fac.create_application_payload(work["id"]), rightsholder_headers), 201
    )
    assert_application(data)
    assert data["claimant_count"] == 1
    assert data["is_expedited"] is False
    assert data["status"] == "DRAFT"


def test_application_unknown_work_fk_returns_not_found(api, rightsholder_headers):
    """PRD §2.4: "any create or action request that names a foreign resource which
    does not exist likewise fails with ERR_NOT_FOUND."

    Design: Corner/entities/application_work_id_fk_nonexistent_returns_not_found
    """
    payload = fac.create_application_payload(NON_EXISTENT_UUID)
    validate_error(api.create_application(payload, rightsholder_headers), ApiErrorId.ERR_NOT_FOUND)


# ==========================================================================
# Corner — consistency
# ==========================================================================
def test_created_work_is_immediately_readable(api, rightsholder_headers):
    """PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."
    PRD §2.4: retrieval of a resource by its path identifier returns it.

    Design: Corner/consistency_model/immediate_visibility_on_create
    """
    created = validate_success(
        api.create_work(fac.create_work_payload(title="Echo"), rightsholder_headers), 201
    )
    fetched = validate_success(api.get_work(created["id"], rightsholder_headers), 200)
    assert fetched["id"] == created["id"]
    assert fetched["title"] == "Echo"


# ==========================================================================
# Difficulty — application_fee_multifactor
# ==========================================================================
def test_standard_expedited_multiclaimant_fee(api, rightsholder_headers):
    """PRD §3.2: "the base is the standard base of 6,500 cents ($65.00), to which
    an additional-claimant surcharge is added: for each claimant beyond the first
    ... an extra 1,500 cents ($15.00) is added ... Finally, if is_expedited is
    true, an expedite surcharge of 80,000 cents ($800.00) is added on top."

    Design: Difficulty/combinatorial_formula/application_fee_multifactor
    """
    work = fx.create_work(is_published=True, publication_date="2025-01-01T00:00:00Z")
    app = fx.create_application(work["id"], filing_basis="STANDARD", claimant_count=3, is_expedited=True)
    data = validate_success(api.submit_application(app["id"], rightsholder_headers), 200)
    assert data["fee_due_cents"] == 89500, f"6500 + 2*1500 + 80000 = 89500, got {data['fee_due_cents']}"


def test_standard_expedited_single_claimant_fee(api, rightsholder_headers):
    """PRD §3.2: "the base is the standard base of 6,500 cents ($65.00) ... for each
    claimant beyond the first — that is, the claimant_count minus one, or zero if
    there is only one claimant ... Finally, if is_expedited is true, an expedite
    surcharge of 80,000 cents ($800.00) is added on top."

    Design: Difficulty/combinatorial_formula/application_fee_multifactor
    """
    work = fx.create_work()
    app = fx.create_application(work["id"], filing_basis="STANDARD", claimant_count=1, is_expedited=True)
    data = validate_success(api.submit_application(app["id"], rightsholder_headers), 200)
    assert data["fee_due_cents"] == 86500, f"6500 + 0 + 80000 = 86500, got {data['fee_due_cents']}"


# ==========================================================================
# Corner — calculations (application fee single basis)
# ==========================================================================
def test_single_basis_unpublished_fee(api, rightsholder_headers):
    """PRD §3.2: "When the basis is SINGLE_AUTHOR_SINGLE_WORK, the claimant_count is
    1, and the work is not published, the base fee is the single-work base of 4,500
    cents ($45.00)."

    Design: Corner/calculations/application_fee_single_basis_unpublished
    """
    work = fx.create_work(is_published=False)
    app = fx.create_application(work["id"], filing_basis="SINGLE_AUTHOR_SINGLE_WORK", claimant_count=1)
    data = validate_success(api.submit_application(app["id"], rightsholder_headers), 200)
    assert data["fee_due_cents"] == 4500


# ==========================================================================
# Corner — validations on submit / file
# ==========================================================================
def test_single_basis_multi_claimant_rejected(api, rightsholder_headers):
    """PRD §3.2: "If the declared basis is SINGLE_AUTHOR_SINGLE_WORK, that basis is
    only valid when claimant_count equals 1 and the work is not published; a
    SINGLE_AUTHOR_SINGLE_WORK filing that names more than one claimant or a
    published work is rejected with ERR_FILING_BASIS_INVALID."

    Design: Corner/validations/filing_basis_single_multi_claimant_returns_error
    """
    work = fx.create_work()
    app = fx.create_application(work["id"], filing_basis="SINGLE_AUTHOR_SINGLE_WORK", claimant_count=2)
    validate_error(api.submit_application(app["id"], rightsholder_headers), ApiErrorId.ERR_FILING_BASIS_INVALID)


def test_duplicate_active_application_rejected(api, rightsholder_headers):
    """PRD §3.1: "an attempt to file a second application for a work that already
    has one in any other state is rejected with ERR_DUPLICATE_ACTIVE_APPLICATION."

    Design: Corner/validations/duplicate_active_application_returns_error
    """
    work = fx.create_work()
    fx.create_application(work["id"])
    dup = api.create_application(fac.create_application_payload(work["id"]), rightsholder_headers)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_ACTIVE_APPLICATION)


def test_fee_amount_mismatch_rejected(api, rightsholder_headers):
    """PRD §3.2: "When a RightsHolder pays the fee, the request supplies amount_cents,
    which must equal fee_due_cents exactly; any other amount is rejected with
    ERR_FEE_AMOUNT_MISMATCH."

    Design: Corner/validations/fee_amount_mismatch_returns_error
    """
    _work, app = fx.setup_application_submitted()
    resp = api.pay_fee(app["id"], fac.pay_fee_payload(5000), rightsholder_headers)
    validate_error(resp, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH)


# ==========================================================================
# Corner — state machine (register from wrong state)
# ==========================================================================
def test_register_from_submitted_rejected(api, examiner_headers):
    """PRD §3.3: "This transition is only valid from UNDER_EXAMINATION; in
    particular, it is invalid while a correspondence round is open ... and such an
    attempt is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/register_from_submitted_returns_invalid_state
    """
    _work, app = fx.setup_application_submitted()
    resp = api.register_application(app["id"], examiner_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# Corner — cross-entity validations on begin-examination
# ==========================================================================
def test_begin_examination_without_accepted_deposit_rejected(api, rightsholder_headers, examiner_headers):
    """PRD §3.3: "an ACCEPTED deposit must exist for the application (otherwise
    ERR_DEPOSIT_NOT_ACCEPTED)."

    Design: Corner/validations/begin_examination_without_accepted_deposit_returns_error
    """
    _work, app = fx.setup_application_submitted()
    fx.get_success_data(api.pay_fee(app["id"], fac.pay_fee_payload(app["fee_due_cents"]), rightsholder_headers))
    fx.get_success_data(api.create_deposit(fac.create_deposit_payload(app["id"]), rightsholder_headers))
    resp = api.begin_examination(app["id"], examiner_headers)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_ACCEPTED)


def test_begin_examination_without_full_fee_rejected(api, rightsholder_headers, examiner_headers):
    """PRD §3.3: "the amount paid must cover the amount due, meaning fee_paid_cents
    is at least fee_due_cents (otherwise ERR_FEE_NOT_PAID)."

    Design: Corner/validations/begin_examination_without_fee_returns_error
    """
    _work, app = fx.setup_application_submitted()
    dep = fx.get_success_data(api.create_deposit(fac.create_deposit_payload(app["id"]), rightsholder_headers))
    fx.get_success_data(api.accept_deposit(dep["id"], examiner_headers))
    resp = api.begin_examination(app["id"], examiner_headers)
    validate_error(resp, ApiErrorId.ERR_FEE_NOT_PAID)


# ==========================================================================
# Difficulty — registration_issue_depth2
# ==========================================================================
def test_register_mints_issued_certificate(api, examiner_headers):
    """PRD §3.3: "Granting registration mints a new certificate" and "The certificate
    is created with status ISSUED."

    Design: Difficulty/transitive_cascade/registration_issue_depth2
    """
    _work, app = fx.setup_application_under_examination()
    validate_success(api.register_application(app["id"], examiner_headers), 200)
    cert = fx.get_certificate_for_application(app["id"])
    assert_certificate(cert)
    assert cert["status"] == "ISSUED"
    assert cert["application_id"] == app["id"]


def test_register_sets_work_and_application_registered(api, examiner_headers):
    """PRD §3.3: "Granting registration ... moves the work's registration_status to
    REGISTERED, incrementing the work's version."
    PRD §3.1: registration_status "becomes ... REGISTERED when the application is
    registered."

    Design: Difficulty/transitive_cascade/registration_issue_depth2
    """
    work, app = fx.setup_application_under_examination()
    registered_app = validate_success(api.register_application(app["id"], examiner_headers), 200)
    assert registered_app["status"] == "REGISTERED"
    refreshed = fx.get_work(work["id"])
    assert refreshed["registration_status"] == "REGISTERED"


# ==========================================================================
# Difficulty — effective_date_receipt_vs_decision
# ==========================================================================
def _register_with_receipt_dates(api, rh, ex):
    """Pipeline where submit / fee / deposit-accept / register land on distinct
    clock days: submitted 05-02, fee-paid 05-03, deposit-accepted 05-05,
    registered 05-10. Returns the minted certificate."""
    fx.set_clock("2026-05-02T00:00:00Z")
    work = fx.create_work()
    app = fx.create_application(work["id"])
    submitted = fx.get_success_data(api.submit_application(app["id"], rh))
    dep = fx.get_success_data(api.create_deposit(fac.create_deposit_payload(app["id"]), rh))
    fx.set_clock("2026-05-03T00:00:00Z")
    fx.get_success_data(api.pay_fee(app["id"], fac.pay_fee_payload(submitted["fee_due_cents"]), rh))
    fx.set_clock("2026-05-05T00:00:00Z")
    fx.get_success_data(api.accept_deposit(dep["id"], ex))
    fx.get_success_data(api.begin_examination(app["id"], ex))
    fx.set_clock("2026-05-10T00:00:00Z")
    fx.get_success_data(api.register_application(app["id"], ex))
    return fx.get_certificate_for_application(app["id"])


def test_effective_date_is_receipt_completion_max(api, rightsholder_headers, examiner_headers):
    """PRD §3.3: "the effective_date is the latest of three calendar dates: the date
    of submitted_at, the date the accepted deposit's accepted_at was stamped, and
    the date of fee_paid_at — all compared at calendar-day granularity."

    Design: Difficulty/dual_variant_calc/effective_date_receipt_vs_decision
    """
    cert = _register_with_receipt_dates(api, rightsholder_headers, examiner_headers)
    # max(05-02 submitted, 05-03 fee-paid, 05-05 deposit-accepted) == 05-05
    assert_same_calendar_date(cert["effective_date"], "2026-05-05T00:00:00Z", "effective_date")


def test_decision_date_is_registration_instant(api, rightsholder_headers, examiner_headers):
    """PRD §3.3: "The decision_date records the later registration-decision date
    separately and is not itself the effective date." and "sets decision_date to
    the registration decision instant (the same clock value as registered_at)."

    Design: Difficulty/dual_variant_calc/effective_date_receipt_vs_decision
    """
    cert = _register_with_receipt_dates(api, rightsholder_headers, examiner_headers)
    assert_same_calendar_date(cert["decision_date"], "2026-05-10T00:00:00Z", "decision_date")
    # The two dates genuinely diverge (receipt-completion vs decision date).
    assert_same_calendar_date(cert["effective_date"], "2026-05-05T00:00:00Z", "effective_date")


# ==========================================================================
# Difficulty — application_fee_refund_conserves_net
# ==========================================================================
def test_refuse_refunds_full_fee_net_zero(api, rightsholder_headers, examiner_headers):
    """PRD §3.3: "Refusal refunds the full paid fee: fee_refunded_cents increases by
    fee_paid_cents, so that net_fee_cents returns to zero."

    Design: Difficulty/compensating_invariant/application_fee_refund_conserves_net
    """
    _work, app = fx.setup_application_under_examination()  # STANDARD -> fee_due 6500, paid
    refused = validate_success(api.refuse_application(app["id"], examiner_headers), 200)
    assert refused["status"] == "REFUSED"
    assert refused["fee_refunded_cents"] == 6500
    assert refused["net_fee_cents"] == 0


def test_refuse_preserves_paid_amount_record(api, examiner_headers):
    """PRD §2.9: "For each application, net_fee_cents always equals fee_paid_cents
    minus fee_refunded_cents; when an application is refused or withdrawn, the full
    paid fee is refunded and this net returns to zero."

    Design: Difficulty/compensating_invariant/application_fee_refund_conserves_net
    """
    _work, app = fx.setup_application_under_examination()
    refused = validate_success(api.refuse_application(app["id"], examiner_headers), 200)
    assert refused["fee_paid_cents"] == 6500
    assert refused["net_fee_cents"] == refused["fee_paid_cents"] - refused["fee_refunded_cents"]
