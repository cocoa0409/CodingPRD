"""Composite setup builders.

The pytest fixtures themselves live in the suite's conftest; everything here is a
plain builder function, because most tests need several instances of the same
shape carrying different data.  Every builder validates its own response, so a
test that reaches its trigger knows its setup landed.

The recurring shape is the resolution arc itself: register an institution, load
its depositors and accounts, file and standardize a readiness package whose
`reported_deposit_total_cents` equals the booked total so the variance reads 0,
close the charter, then open, prepare, review and certify a determination.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from . import constants as C
from . import factories as F
from .test_users import (
    CLAIMS_AGENT,
    CLAIMS_CERTIFIER,
    CLOSING_MANAGER,
    RECEIVERSHIP_TRUSTEE,
    RESOLUTION_ANALYST,
    make_bidder_headers,
    make_claims_agent_headers,
    make_claims_certifier_headers,
    make_depositor_headers,
)


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------
def setup_data(response):
    """The `data` of a setup call, accepting any 2xx the operation may answer with."""
    return get_success_data(response)


def advance_clock(client, to_iso8601, headers=CLOSING_MANAGER):
    """Advance the logical clock and return the reported `current_utc`."""
    return validate_success(client.set_clock(to_iso8601, headers), 200)


def open_at_setup_clock(client):
    """Move the clock to the instant the suite builds its resolutions at."""
    return advance_clock(client, C.SETUP_CLOCK)


# ---------------------------------------------------------------------------
# Plain reads
# ---------------------------------------------------------------------------
def get_institution(client, institution_id, headers=CLOSING_MANAGER):
    return validate_success(client.get_institution(institution_id, headers), 200)


def insurance_summary(client, institution_id, headers=CLOSING_MANAGER):
    return validate_success(client.get_insurance_summary(institution_id, headers), 200)


def get_depositor(client, depositor_record_id, headers=CLAIMS_AGENT):
    return validate_success(
        client.get_depositor_record(depositor_record_id, headers), 200
    )


def get_account(client, account_id, headers=CLAIMS_AGENT):
    return validate_success(client.get_deposit_account(account_id, headers), 200)


def get_determination(client, determination_id, headers=CLAIMS_AGENT):
    return validate_success(client.get_determination(determination_id, headers), 200)


def get_certificate(client, certificate_id, headers=CLAIMS_CERTIFIER):
    return validate_success(client.get_certificate(certificate_id, headers), 200)


def get_bid(client, bid_id, headers=RESOLUTION_ANALYST):
    return validate_success(client.get_bid(bid_id, headers), 200)


def get_bidder(client, bidder_id, headers=RESOLUTION_ANALYST):
    return validate_success(client.get_bidder(bidder_id, headers), 200)


def get_branch_reopening(client, branch_reopening_id, headers=CLOSING_MANAGER):
    return validate_success(
        client.get_branch_reopening(branch_reopening_id, headers), 200
    )


def get_dividend(client, distribution_id, headers=RECEIVERSHIP_TRUSTEE):
    return validate_success(client.get_dividend(distribution_id, headers), 200)


def institution_version(client, institution_id, headers=RECEIVERSHIP_TRUSTEE):
    """The institution's current `version`, as PRD 2.9 requires a declarer to observe."""
    return get_institution(client, institution_id, headers)["version"]


def depositor_version(client, depositor_record_id, headers=CLAIMS_AGENT):
    """The depositor record's current `version`, required on a determination create."""
    return get_depositor(client, depositor_record_id, headers)["version"]


# ---------------------------------------------------------------------------
# Single records
# ---------------------------------------------------------------------------
def new_institution(client, headers=CLOSING_MANAGER, **kwargs):
    return validate_success(
        client.create_institution(F.institution_payload(**kwargs), headers), 201
    )


def new_depositor(client, institution_id, headers=CLAIMS_AGENT, **kwargs):
    return validate_success(
        client.create_depositor_record(
            institution_id, F.depositor_record_payload(**kwargs), headers
        ),
        201,
    )


def new_account(client, institution_id, depositor_id, headers=CLAIMS_AGENT, **kwargs):
    return validate_success(
        client.create_deposit_account(
            F.deposit_account_payload(institution_id, depositor_id, **kwargs), headers
        ),
        201,
    )


def new_interest(
    client,
    account_id,
    depositor_record_id,
    interest_role,
    designated_share_bps,
    headers=CLAIMS_AGENT,
):
    return validate_success(
        client.create_ownership_interest(
            account_id,
            F.ownership_interest_payload(
                depositor_record_id, interest_role, designated_share_bps
            ),
            headers,
        ),
        201,
    )


def file_readiness(client, institution_id, headers=CLOSING_MANAGER, **kwargs):
    return validate_success(
        client.create_readiness_submission(
            institution_id, F.readiness_submission_payload(**kwargs), headers
        ),
        201,
    )


def standardize(client, submission_id, headers=CLOSING_MANAGER):
    return validate_success(client.standardize_submission(submission_id, headers), 200)


def close_charter(client, institution_id, headers=CLOSING_MANAGER):
    return validate_success(client.close_institution(institution_id, headers), 200)


def new_branch_reopening(client, institution_id, headers=CLOSING_MANAGER, **kwargs):
    return validate_success(
        client.create_branch_reopening(
            institution_id, F.branch_reopening_payload(**kwargs), headers
        ),
        201,
    )


def new_bidder(client, headers=RESOLUTION_ANALYST, **kwargs):
    return validate_success(
        client.create_bidder(F.bidder_payload(**kwargs), headers), 201
    )


def qualify_bidder(client, bidder_id, headers=RESOLUTION_ANALYST, **kwargs):
    return validate_success(
        client.decide_qualification(
            bidder_id, F.qualification_payload(**kwargs), headers
        ),
        200,
    )


def new_qualified_bidder(client, **kwargs):
    """A bidder registered above both eligibility floors and then qualified."""
    bidder = new_bidder(client, **kwargs)
    qualify_bidder(client, bidder["id"])
    return get_bidder(client, bidder["id"])


def open_marketing(client, institution_id, bid_deadline_at="2026-09-30T00:00:00Z"):
    return validate_success(
        client.franchise_marketing(
            institution_id,
            F.marketing_payload("OPEN", bid_deadline_at=bid_deadline_at),
            RESOLUTION_ANALYST,
        ),
        200,
    )


def close_marketing(client, institution_id):
    return validate_success(
        client.franchise_marketing(
            institution_id, F.marketing_payload("CLOSE", bid_deadline_at=None), RESOLUTION_ANALYST
        ),
        200,
    )


def new_bid(client, institution_id, bidder_id, **kwargs):
    return validate_success(
        client.create_bid(
            F.bid_payload(institution_id, bidder_id, **kwargs),
            make_bidder_headers(bidder_id),
        ),
        201,
    )


def withdraw_bid(client, bid_id, bidder_id):
    return validate_success(
        client.withdraw_bid(bid_id, make_bidder_headers(bidder_id)), 200
    )


def evaluate_least_cost(client, institution_id, test_variant="EXPECTED_LOSS_SHARE"):
    return validate_success(
        client.evaluate_least_cost_test(
            institution_id, F.evaluate_payload(test_variant), RESOLUTION_ANALYST
        ),
        200,
    )


def award_least_cost(client, institution_id):
    return validate_success(
        client.award_least_cost_test(institution_id, RESOLUTION_ANALYST), 200
    )


def post_proceeds(client, institution_id, **kwargs):
    return validate_success(
        client.post_receivership_proceeds(
            institution_id, F.proceeds_payload(**kwargs), RECEIVERSHIP_TRUSTEE
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Determination lifecycle
# ---------------------------------------------------------------------------
def open_determination(client, depositor_record_id, headers=CLAIMS_AGENT, **kwargs):
    """Open a determination against the depositor's currently observed `version`."""
    version = depositor_version(client, depositor_record_id, headers)
    return validate_success(
        client.create_determination(
            F.determination_payload(depositor_record_id, version, **kwargs), headers
        ),
        201,
    )


def prepare(client, determination_id, method_variant="AGGREGATE_BY_CATEGORY", user_id=None):
    headers = make_claims_agent_headers(user_id) if user_id else CLAIMS_AGENT
    return validate_success(
        client.prepare_determination(
            determination_id, F.prepare_payload(method_variant), headers
        ),
        200,
    )


def submit_review(client, determination_id, user_id=None):
    headers = make_claims_agent_headers(user_id) if user_id else CLAIMS_AGENT
    return validate_success(
        client.submit_determination_review(determination_id, headers), 200
    )


def certify(client, determination_id, user_id=None):
    headers = make_claims_certifier_headers(user_id) if user_id else CLAIMS_CERTIFIER
    return validate_success(client.certify_determination(determination_id, headers), 200)


def request_revision(client, determination_id, revision_reason=None, user_id=None):
    headers = make_claims_certifier_headers(user_id) if user_id else CLAIMS_CERTIFIER
    payload = (
        F.request_revision_payload(revision_reason)
        if revision_reason is not None
        else F.request_revision_payload()
    )
    return validate_success(
        client.request_determination_revision(determination_id, payload, headers), 200
    )


def determination_under_review(client, depositor_record_id, method_variant="AGGREGATE_BY_CATEGORY"):
    """A determination opened, prepared and handed to a certifier."""
    determination = open_determination(client, depositor_record_id)
    prepare(client, determination["id"], method_variant)
    return submit_review(client, determination["id"])


def certified_determination(
    client, depositor_record_id, method_variant="AGGREGATE_BY_CATEGORY"
):
    """A determination taken all the way to `CERTIFIED` under segregation of duties."""
    determination_under_review(client, depositor_record_id, method_variant)
    determinations = validate_success(
        client.list_determinations(
            CLAIMS_AGENT, params={"depositor_record_id": depositor_record_id}
        ),
        200,
    )
    live = [d for d in determinations if d["status"] == "UNDER_REVIEW"]
    assert len(live) == 1, f"expected one determination under review, got {len(live)}"
    return certify(client, live[0]["id"])


def certificate_for(client, determination_id, headers=CLAIMS_CERTIFIER):
    """The single receivership certificate a certified determination issued."""
    rows = validate_success(
        client.list_certificates(
            headers, params={"insurance_determination_id": determination_id}
        ),
        200,
    )
    assert len(rows) == 1, f"expected exactly one certificate, got {len(rows)}"
    return rows[0]


def certificates_of(client, institution_id, headers=RECEIVERSHIP_TRUSTEE):
    """Every certificate filed against the estate, in `created_at` ascending order."""
    return validate_success(
        client.list_certificates(headers, params={"institution_id": institution_id}),
        200,
    )


def acknowledge_notice(client, depositor_record_id):
    return validate_success(
        client.acknowledge_notice(
            depositor_record_id, make_depositor_headers(depositor_record_id)
        ),
        200,
    )


def release_hold(client, account_id):
    return validate_success(client.release_hold(account_id, CLAIMS_CERTIFIER), 200)


# ---------------------------------------------------------------------------
# Dividend rounds
# ---------------------------------------------------------------------------
def declare_dividend(client, institution_id, priority_class, declared_rate_bps):
    """Declare a round against the institution's currently observed `version`."""
    version = institution_version(client, institution_id)
    return validate_success(
        client.declare_dividend(
            institution_id,
            F.dividend_payload(priority_class, declared_rate_bps, version),
            RECEIVERSHIP_TRUSTEE,
        ),
        201,
    )


def settle_dividend(client, distribution_id):
    return validate_success(
        client.settle_dividend(distribution_id, RECEIVERSHIP_TRUSTEE), 200
    )


def void_dividend(client, distribution_id):
    return validate_success(
        client.void_dividend(distribution_id, RECEIVERSHIP_TRUSTEE), 200
    )


def settled_round(client, institution_id, priority_class, declared_rate_bps):
    """A declared round taken through settlement."""
    declared = declare_dividend(client, institution_id, priority_class, declared_rate_bps)
    return settle_dividend(client, declared["id"])


# ---------------------------------------------------------------------------
# State progression: institution readiness and closure
# ---------------------------------------------------------------------------
def institution_in_readiness_collection(client, **kwargs):
    """An institution whose first package moved it out of pre-failure monitoring."""
    institution = new_institution(client, **kwargs)
    file_readiness(client, institution["id"], reported_deposit_total_cents=0)
    return get_institution(client, institution["id"])


def make_resolution_ready(client, institution_id, booked_total_cents):
    """File a clean package reconciling to the booked total, then standardize it.

    The default package scores exactly 9800 bps, and stating the booked total as
    the reported total puts `deposit_total_variance_bps` at 0, so both gates clear.
    """
    submission = file_readiness(
        client, institution_id, reported_deposit_total_cents=booked_total_cents
    )
    return standardize(client, submission["id"])


def closed_institution(client, booked_total_cents=0, **kwargs):
    """A registered institution standardized and then closed into receivership."""
    institution = new_institution(client, **kwargs)
    make_resolution_ready(client, institution["id"], booked_total_cents)
    close_charter(client, institution["id"])
    return get_institution(client, institution["id"])


def deposit_free_closed_institution(client, **kwargs):
    """A closed institution with no accounts at all, so its booked total is 0."""
    return closed_institution(client, booked_total_cents=0, **kwargs)


def marketed_institution(client, bid_deadline_at="2026-09-30T00:00:00Z", **kwargs):
    """A deposit-free closed institution whose franchise marketing is open."""
    institution = deposit_free_closed_institution(client, **kwargs)
    open_marketing(client, institution["id"], bid_deadline_at)
    return get_institution(client, institution["id"])


def _maybe_clock(client, clock):
    if clock is not None:
        advance_clock(client, clock)


# ---------------------------------------------------------------------------
# Entity hierarchy: a closed estate with one depositor and its accounts
# ---------------------------------------------------------------------------
def single_account_estate(
    client,
    balance_cents,
    ownership_category="SINGLE",
    account_number="S-0001",
    accrued_interest_cents=0,
    clock=C.SETUP_CLOCK,
    depositor_name=None,
    account_kwargs=None,
    **institution_kwargs,
):
    """A closed institution holding one depositor with one account."""
    _maybe_clock(client, clock)
    institution = new_institution(client, **institution_kwargs)
    depositor = new_depositor(client, institution["id"], legal_name=depositor_name)
    account = new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number=account_number,
        ownership_category=ownership_category,
        balance_cents=balance_cents,
        accrued_interest_cents=accrued_interest_cents,
        **(account_kwargs or {}),
    )
    booked = balance_cents + accrued_interest_cents
    make_resolution_ready(client, institution["id"], booked)
    close_charter(client, institution["id"])
    return {
        "institution": get_institution(client, institution["id"]),
        "depositor": get_depositor(client, depositor["id"]),
        "account": get_account(client, account["id"]),
    }


def pooled_estate(client, clock=C.SETUP_CLOCK, depositor_name="Alice Nakamura", **institution_kwargs):
    """The PRD's worked two-account single-ownership depositor, closed and frozen.

    Accounts of 20000000 and 9000001 cents pool to 29000001 against one standard
    maximum, so the aggregated determination will read 25000000 insured and
    4000001 uninsured.
    """
    _maybe_clock(client, clock)
    institution = new_institution(client, **institution_kwargs)
    depositor = new_depositor(client, institution["id"], legal_name=depositor_name)
    account_a = new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="S-0001",
        ownership_category="SINGLE",
        balance_cents=C.ACCOUNT_A_BALANCE_CENTS,
        opened_at="2024-03-01T00:00:00Z",
    )
    account_b = new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="S-0002",
        ownership_category="SINGLE",
        balance_cents=C.ACCOUNT_B_BALANCE_CENTS,
        opened_at="2024-06-15T00:00:00Z",
    )
    make_resolution_ready(client, institution["id"], C.POOLED_ATTRIBUTED_CENTS)
    close_charter(client, institution["id"])
    return {
        "institution": get_institution(client, institution["id"]),
        "depositor": get_depositor(client, depositor["id"]),
        "account_a": get_account(client, account_a["id"]),
        "account_b": get_account(client, account_b["id"]),
    }


def certified_pooled_estate(client, **kwargs):
    """The pooled estate carried through certification.

    Certification leaves the determination `CERTIFIED`, both accounts `DETERMINED`
    and `HELD` for 2758622 and 1241379 cents, one certificate of face 4000001
    `ISSUED`, and the depositor's notice `SENT` under `PARTIALLY_UNINSURED`.
    """
    estate = pooled_estate(client, **kwargs)
    determination = certified_determination(client, estate["depositor"]["id"])
    estate["determination"] = determination
    estate["certificate"] = certificate_for(client, determination["id"])
    estate["depositor"] = get_depositor(client, estate["depositor"]["id"])
    estate["account_a"] = get_account(client, estate["account_a"]["id"])
    estate["account_b"] = get_account(client, estate["account_b"]["id"])
    estate["institution"] = get_institution(client, estate["institution"]["id"])
    return estate


def two_certificate_estate(client, clock=C.SETUP_CLOCK, **institution_kwargs):
    """Two certified depositors leaving certificates of face 4000001 and 2000001.

    Alice pools 20000000 + 9000001 for an uninsured 4000001; Bob holds a single
    27000001 account for an uninsured 2000001.  Alice is certified first, so her
    certificate is the earlier row in `created_at` ascending order.
    """
    _maybe_clock(client, clock)
    institution = new_institution(client, **institution_kwargs)
    alice = new_depositor(client, institution["id"], legal_name="Alice Nakamura")
    bob = new_depositor(client, institution["id"], legal_name="Bob Serrano")
    alice_a = new_account(
        client,
        institution["id"],
        alice["id"],
        account_number="AA-1",
        balance_cents=C.ACCOUNT_A_BALANCE_CENTS,
        opened_at="2024-03-01T00:00:00Z",
    )
    alice_b = new_account(
        client,
        institution["id"],
        alice["id"],
        account_number="AA-2",
        balance_cents=C.ACCOUNT_B_BALANCE_CENTS,
        opened_at="2024-06-15T00:00:00Z",
    )
    bob_a = new_account(
        client,
        institution["id"],
        bob["id"],
        account_number="BB-1",
        balance_cents=27000001,
        opened_at="2024-05-01T00:00:00Z",
    )
    booked = C.POOLED_ATTRIBUTED_CENTS + 27000001
    submission = file_readiness(
        client,
        institution["id"],
        record_count=300,
        malformed_record_count=6,
        reported_deposit_total_cents=booked,
    )
    standardize(client, submission["id"])
    close_charter(client, institution["id"])
    alice_determination = certified_determination(client, alice["id"])
    bob_determination = certified_determination(client, bob["id"])
    return {
        "institution": get_institution(client, institution["id"]),
        "alice": get_depositor(client, alice["id"]),
        "bob": get_depositor(client, bob["id"]),
        "alice_accounts": [
            get_account(client, alice_a["id"]),
            get_account(client, alice_b["id"]),
        ],
        "bob_account": get_account(client, bob_a["id"]),
        "alice_determination": alice_determination,
        "bob_determination": bob_determination,
        "alice_certificate": certificate_for(client, alice_determination["id"]),
        "bob_certificate": certificate_for(client, bob_determination["id"]),
    }


def estate_with_settled_general_unsecured_round(
    client,
    declared_rate_bps=C.DIVIDEND_RATE_BPS,
    gross_proceeds_cents=5000000,
    disposition_expense_cents=1000000,
    **kwargs,
):
    """The two-certificate estate with one settled `GENERAL_UNSECURED` round.

    Proceeds of 5000000 against expenses of 1000000 leave 4000000 cents of
    receivership cash; a round at 3333 bps pays 1333200 + 666600 = 1999800.
    """
    estate = two_certificate_estate(client, **kwargs)
    post_proceeds(
        client,
        estate["institution"]["id"],
        gross_proceeds_cents=gross_proceeds_cents,
        disposition_expense_cents=disposition_expense_cents,
    )
    estate["round"] = settled_round(
        client, estate["institution"]["id"], "GENERAL_UNSECURED", declared_rate_bps
    )
    estate["institution"] = get_institution(client, estate["institution"]["id"])
    estate["alice_certificate"] = get_certificate(
        client, estate["alice_certificate"]["id"]
    )
    estate["bob_certificate"] = get_certificate(client, estate["bob_certificate"]["id"])
    return estate


# ---------------------------------------------------------------------------
# Terminal states: a resolution taken through the least-cost test
# ---------------------------------------------------------------------------
def evaluated_estate(
    client,
    test_variant="EXPECTED_LOSS_SHARE",
    bid_kwargs=None,
    clock=C.SETUP_CLOCK,
    **institution_kwargs,
):
    """A closed, marketed estate with one qualified bidder's bid already evaluated."""
    _maybe_clock(client, clock)
    institution = deposit_free_closed_institution(client, **institution_kwargs)
    open_marketing(client, institution["id"])
    bidder = new_qualified_bidder(client)
    bid = new_bid(client, institution["id"], bidder["id"], **(bid_kwargs or {}))
    evaluate_least_cost(client, institution["id"], test_variant)
    return {
        "institution": get_institution(client, institution["id"]),
        "bidder": bidder,
        "bid": get_bid(client, bid["id"]),
    }
