"""Job lifecycle branching, the pro's parallel vetting axes, and state legality guards."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_customer_headers, make_pro_headers, TEST_USERS,
    create_category, create_customer, create_pro, create_cleared_pro,
    create_job, estimate_requested_job, accepted_instant_job, instant_quoted_job,
    in_progress_job,
    create_background_check_payload, decide_background_check_payload,
    submit_quote_payload, accept_quote_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# =====================================================================
# Difficulty: non_linear_state_machine / job_branches_instant_vs_estimate_from_requested
# =====================================================================

class TestJobBranchesFromRequested:
    """REQUESTED forks into INSTANT_QUOTED (with a Quote) or ESTIMATE_REQUESTED (no Quote)."""

    def _setup(self):
        cat = create_category(code="GEN_FIX", name="General Fix", pricing_model="HOURLY",
                              hourly_rate_cents=9000, instant_quote_eligible=True,
                              instant_quote_flat_cents=15000)
        cust = create_customer(email="c5@x.com", full_name="C Five", zip_code="30301")
        return cat, cust

    def test_instant_branch_sets_status_and_quote_path(self, api):
        """PRD §3.3: "the customer may take the instant quote, advancing the job
        `REQUESTED → INSTANT_QUOTED`. This produces a `Quote` whose `quote_type` is `INSTANT` ...
        and it sets the job's `quote_path` to `INSTANT`."

        Design: Difficulty/non_linear_state_machine/job_branches_instant_vs_estimate_from_requested
        """
        cat, cust = self._setup()
        job = create_job(cust["id"], cat["id"], "30301")
        api.instant_quote(job["id"], make_customer_headers(cust["id"]))
        refreshed = validate_success(api.get_job(job["id"], make_customer_headers(cust["id"])), 200)
        assert refreshed["status"] == "INSTANT_QUOTED"
        assert refreshed["quote_path"] == "INSTANT"

    def test_estimate_branch_sets_status_and_quote_path(self, api):
        """PRD §3.3: "Alternatively the customer requests an in-home estimate, advancing the job
        `REQUESTED → ESTIMATE_REQUESTED` and setting `quote_path` to `IN_HOME`."

        Design: Difficulty/non_linear_state_machine/job_branches_instant_vs_estimate_from_requested
        """
        cat, cust = self._setup()
        job = create_job(cust["id"], cat["id"], "30301")
        api.request_estimate(job["id"], make_customer_headers(cust["id"]))
        refreshed = validate_success(api.get_job(job["id"], make_customer_headers(cust["id"])), 200)
        assert refreshed["status"] == "ESTIMATE_REQUESTED"
        assert refreshed["quote_path"] == "IN_HOME"


# =====================================================================
# Difficulty: non_linear_state_machine / pro_parallel_background_and_license_dimensions
# =====================================================================

class TestProParallelVettingAxes:
    """background_check_status and license_status evolve on orthogonal axes."""

    def test_clearing_criminal_identity_leaves_license_none(self, api):
        """PRD §3.2: "A professional moves from `PENDING` to `CLEARED` exactly when every
        background check of theirs whose `check_type` is `CRIMINAL` or `IDENTITY` has a `decision`
        of `PASS`." PRD §3.2: "On registration a professional's `background_check_status` is
        `PENDING` and their `license_status` is `NONE`, with `license_expires_on` null".

        Design: Difficulty/non_linear_state_machine/pro_parallel_background_and_license_dimensions
        """
        pro = create_pro(email="p6@x.com", full_name="P Six", home_zip_code="30301", skill_tags=["hvac"])
        bc1 = get_success_data(api.create_background_check(
            pro["id"], create_background_check_payload(check_type="CRIMINAL"), ADMIN))
        bc2 = get_success_data(api.create_background_check(
            pro["id"], create_background_check_payload(check_type="IDENTITY"), ADMIN))
        # also submit a LICENSE check but do NOT decide it
        get_success_data(api.create_background_check(
            pro["id"], create_background_check_payload(
                check_type="LICENSE", license_expires_on="2030-01-01T00:00:00.000Z"), ADMIN))
        api.decide_background_check(bc1["id"], decide_background_check_payload(decision="PASS"), ADMIN)
        api.decide_background_check(bc2["id"], decide_background_check_payload(decision="PASS"), ADMIN)
        refreshed = validate_success(api.get_pro(pro["id"], ADMIN), 200)
        assert refreshed["background_check_status"] == "CLEARED"
        assert refreshed["license_status"] == "NONE"
        assert refreshed["license_expires_on"] is None

    def test_license_axis_independent_verified_without_full_clearance(self, api):
        """PRD §3.2: "a `LICENSE` check that passes sets `license_status` to `VERIFIED` and copies
        its `license_expires_on` onto the professional — unless that expiry date is already in the
        past at decision time, in which case `license_status` becomes `EXPIRED`."

        Design: Difficulty/non_linear_state_machine/pro_parallel_background_and_license_dimensions
        """
        pro = create_pro(email="p6b@x.com", full_name="P Six B", home_zip_code="30301", skill_tags=["hvac"])
        # Decide ONLY a LICENSE check PASS; criminal/identity remain undecided -> still PENDING.
        bc = get_success_data(api.create_background_check(
            pro["id"], create_background_check_payload(
                check_type="LICENSE", license_expires_on="2030-01-01T00:00:00.000Z"), ADMIN))
        api.decide_background_check(bc["id"], decide_background_check_payload(decision="PASS"), ADMIN)
        refreshed = validate_success(api.get_pro(pro["id"], ADMIN), 200)
        assert refreshed["license_status"] == "VERIFIED"
        assert refreshed["background_check_status"] == "PENDING"


# =====================================================================
# Difficulty: cross_entity_state_dependency / job_complete_requires_invoice_issued_job_to_invoice
# =====================================================================

class TestCompleteRequiresIssuedInvoice:
    """IN_PROGRESS -> COMPLETED requires an Invoice in ISSUED status."""

    def _in_progress_with_draft_invoice(self):
        cat = create_category(code="XENT_B", name="Xent B", pricing_model="FLAT",
                              flat_task_fee_cents=12000, instant_quote_eligible=True,
                              instant_quote_flat_cents=15000, skill_tags=["plumb"])
        cust = create_customer(email="c14@x.com", full_name="C Fourteen", zip_code="30301")
        pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="30301",
                                 email="p14@x.com", full_name="P Fourteen")
        job, window = in_progress_job(cust["id"], cat["id"], pro,
                                      "2026-06-09T10:00:00.000Z", "2026-06-09T12:00:00.000Z",
                                      "2026-06-09T10:30:00.000Z")
        pro_h = make_pro_headers(pro["id"])
        inv = get_success_data(api_client.create_invoice(job["id"], pro_h))  # DRAFT
        return job, pro, inv

    def test_complete_with_only_draft_invoice_rejected(self, api):
        """PRD §3.8: "A `Pro` marks an in-progress job complete, advancing it
        `IN_PROGRESS → COMPLETED`, but only once an invoice for the job exists in `ISSUED` status
        and the acting professional is the job's professional."

        Design: Difficulty/cross_entity_state_dependency/job_complete_requires_invoice_issued_job_to_invoice
        """
        job, pro, inv = self._in_progress_with_draft_invoice()
        res = api.complete_job(job["id"], make_pro_headers(pro["id"]))
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_complete_succeeds_once_invoice_issued(self, api):
        """PRD §3.8: "A `Pro` marks an in-progress job complete, advancing it
        `IN_PROGRESS → COMPLETED`, but only once an invoice for the job exists in `ISSUED` status
        and the acting professional is the job's professional."

        Design: Difficulty/cross_entity_state_dependency/job_complete_requires_invoice_issued_job_to_invoice
        """
        job, pro, inv = self._in_progress_with_draft_invoice()
        pro_h = make_pro_headers(pro["id"])
        api.issue_invoice(inv["id"], pro_h)
        completed = validate_success(api.complete_job(job["id"], pro_h), 200)
        assert completed["status"] == "COMPLETED"


# =====================================================================
# Corner: state_machines
# =====================================================================

def test_new_job_starts_in_requested_initial_state(api):
    """PRD §3.3: "A fresh job is born in `REQUESTED` status with `quote_path`, `pro_id`,
    `agreed_price_cents`, and `parent_job_id` all unset, and `is_warranty_callback` false."

    Design: Corner/state_machines/new_job_starts_in_requested_initial_state
    """
    cat = create_category(code="SM_INIT", name="SM Init", pricing_model="HOURLY", hourly_rate_cents=9000)
    cust = create_customer(email="csm2@x.com", full_name="C SM2", zip_code="30301")
    res = api.create_job(
        {"customer_id": cust["id"], "category_id": cat["id"], "address_zip_code": "30301"},
        make_customer_headers(cust["id"]))
    job = validate_success(res, 201)
    assert job["status"] == "REQUESTED"
    assert job["pro_id"] is None
    assert job["quote_path"] is None


def test_cancel_already_cancelled_job_returns_invalid_state(api):
    """PRD §3.9: "A request to cancel from a state with no defined cancel transition is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_already_cancelled_job_returns_invalid_state
    """
    cat = create_category(code="SM_CANC", name="SM Cancel", pricing_model="HOURLY", hourly_rate_cents=9000)
    cust = create_customer(email="csm1@x.com", full_name="C SM1", zip_code="30301")
    cust_h = make_customer_headers(cust["id"])
    job = create_job(cust["id"], cat["id"], "30301")
    validate_success(api.cancel_job(job["id"], cust_h), 200)
    res = api.cancel_job(job["id"], cust_h)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    refreshed = validate_success(api.get_job(job["id"], cust_h), 200)
    assert refreshed["status"] == "CANCELLED"


# Corner instance state_machines/instant_quote_supersedes_then_estimate_quote_marks_old_superseded
# is SKIPPED. PRD §3.3 states that submitting a new estimate marks a prior not-yet-accepted quote
# superseded, but it does NOT state from which job state a SECOND POST /jobs/{id}/quotes is
# permitted. The scaffold only defines that transition from ESTIMATE_REQUESTED; once the first
# quote moves the job to ESTIMATED, whether a re-submission is allowed (re-quoting from ESTIMATED)
# or rejected (requiring a return to ESTIMATE_REQUESTED) is left open by PRD prose. The supersede
# outcome is therefore not uniquely derivable -> gap left as a gap.


# =====================================================================
# Corner: endpoints / accept_quote_computed_read_pins_agreed_price
# =====================================================================

def test_accept_quote_pins_agreed_price(api):
    """PRD §3.3: "Acceptance sets the chosen quote's `accepted` to true and pins the job's
    `agreed_price_cents` to that quote's `priced_amount_cents`."

    Design: Corner/endpoints/accept_quote_computed_read_pins_agreed_price
    """
    cat = create_category(code="EP_ACC", name="EP Accept", pricing_model="HOURLY",
                          hourly_rate_cents=9000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000)
    cust = create_customer(email="cep2@x.com", full_name="C EP2", zip_code="30301")
    cust_h = make_customer_headers(cust["id"])
    job = create_job(cust["id"], cat["id"], "30301")
    quote = get_success_data(api.instant_quote(job["id"], cust_h))
    res = api.accept_quote(job["id"], accept_quote_payload(quote["id"]), cust_h)
    updated = validate_success(res, 200)
    assert updated["agreed_price_cents"] == 15000
