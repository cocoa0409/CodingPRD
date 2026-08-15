"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use the lenient get_success_data
validator so a setup failure surfaces as a clear "Setup failed" error.

Segregation-of-duties defaults: membership applications are filed by
officer-1 and decided by officer-2; eligibility reviews are flagged by co-1
and decided by co-2. Tests that need other combinations pass explicit headers.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import STANDARD_SEGMENT_DOCS, clock_iso
from .factories import (
    add_segment_amendment_payload,
    create_amendment_payload,
    create_ballot_payload,
    create_charter_payload,
    create_declaration_payload,
    create_enrollment_payload,
    create_meeting_payload,
    create_membership_application_payload,
    create_review_payload,
    create_share_account_payload,
    create_transaction_payload,
    cure_review_payload,
    reconvene_payload,
    segment_spec,
)
from .test_users import TEST_USERS, make_member_headers

BOARD = TEST_USERS["board_director_headers"]
FILER = TEST_USERS["membership_officer_headers"]          # officer-1
DECIDER = TEST_USERS["membership_officer_2_headers"]      # officer-2
FLAGGER = TEST_USERS["compliance_officer_headers"]        # co-1
REVIEW_DECIDER = TEST_USERS["compliance_officer_2_headers"]  # co-2
REGULATOR = TEST_USERS["regulator_headers"]
OPS = TEST_USERS["operations_officer_headers"]
SYSADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(date_or_iso):
    """Set the logical clock. Accepts 'YYYY-MM-DD' or a full ISO instant."""
    iso = date_or_iso if "T" in date_or_iso else clock_iso(date_or_iso)
    get_success_data(api_client.set_clock(iso, SYSADMIN))


# ---------------------------------------------------------------------------
# Charter
# ---------------------------------------------------------------------------

def create_charter(par_value_cents=500, bond_type="MULTIPLE_COMMON_BOND",
                   segments=None):
    """Create the singleton charter. Returns the charter dict."""
    return get_success_data(api_client.create_charter(
        create_charter_payload(bond_type=bond_type,
                               par_value_cents=par_value_cents,
                               segments=segments), BOARD))


def list_segment_ids(charter_id):
    """Segment ids of a charter in list order (creation order)."""
    data, _meta = validate_paginated(
        api_client.list_charter_segments(charter_id, BOARD))
    return [row["id"] for row in data]


def setup_charter(par_value_cents=500, bond_type="MULTIPLE_COMMON_BOND",
                  segments=None):
    """Charter plus its segment ids. Returns (charter, segment_ids)."""
    charter = create_charter(par_value_cents=par_value_cents,
                             bond_type=bond_type, segments=segments)
    return charter, list_segment_ids(charter["id"])


def two_occupational_segments():
    """Two OCCUPATIONAL segments (ACME, BETA) for retirement-cascade setups."""
    return [
        segment_spec("OCCUPATIONAL", "ACME Corp employees"),
        segment_spec("OCCUPATIONAL", "BETA LLC employees"),
    ]


# ---------------------------------------------------------------------------
# Membership applications and members
# ---------------------------------------------------------------------------

def file_application(segment_id=None, name="Test Applicant",
                     date_of_birth="1990-01-01", basis="SEGMENT_MATCH",
                     sponsor_member_id=None, relationship_to_sponsor=None,
                     documents_provided=None, headers=None):
    """File a membership application (filer officer-1 by default)."""
    if documents_provided is None and basis == "SEGMENT_MATCH":
        documents_provided = list(STANDARD_SEGMENT_DOCS)
    payload = create_membership_application_payload(
        applicant_full_name=name, date_of_birth=date_of_birth, basis=basis,
        segment_id=segment_id, sponsor_member_id=sponsor_member_id,
        relationship_to_sponsor=relationship_to_sponsor,
        documents_provided=documents_provided)
    return get_success_data(api_client.create_membership_application(
        payload, headers or FILER))


def approve_application(application_id, headers=None):
    """Approve an application (decider officer-2 by default). Returns the
    resulting member id."""
    data = get_success_data(api_client.approve_membership_application(
        application_id, headers or DECIDER))
    return data["resulting_member_id"]


def create_member(segment_id=None, name="Test Applicant",
                  date_of_birth="1990-01-01", basis="SEGMENT_MATCH",
                  sponsor_member_id=None, relationship_to_sponsor=None,
                  documents_provided=None):
    """File + approve a membership application. Returns the member id."""
    app = file_application(
        segment_id=segment_id, name=name, date_of_birth=date_of_birth,
        basis=basis,
        sponsor_member_id=sponsor_member_id,
        relationship_to_sponsor=relationship_to_sponsor,
        documents_provided=documents_provided)
    return approve_application(app["id"])


def get_member(member_id, headers=None):
    return get_success_data(api_client.get_member(member_id,
                                                  headers or FILER))


# ---------------------------------------------------------------------------
# Share accounts and transactions
# ---------------------------------------------------------------------------

def open_account(member_id, account_type="PRIMARY", initial_deposit_cents=100_000):
    return get_success_data(api_client.create_share_account(
        create_share_account_payload(
            member_id, account_type=account_type,
            initial_deposit_cents=initial_deposit_cents), FILER))


def get_account(account_id, headers=None):
    return get_success_data(api_client.get_share_account(account_id,
                                                         headers or FILER))


def list_account_transactions(account_id, headers=None):
    data, _meta = validate_paginated(
        api_client.list_share_transactions(account_id, headers or OPS))
    return data


def post_transaction(account_id, kind, amount_cents, posted_date):
    return get_success_data(api_client.post_share_transaction(
        account_id,
        create_transaction_payload(kind=kind, amount_cents=amount_cents,
                                   posted_date=posted_date),
        OPS))


def setup_member_with_primary(deposit=100_000, name="Member One",
                              segment_id=None, account_type="PRIMARY",
                              par_value_cents=500):
    """Approved member with one share account. When segment_id is None a fresh
    charter (with one OCCUPATIONAL segment) is created first; otherwise the
    caller's existing segment is used. Returns a context dict."""
    ctx = {}
    if segment_id is None:
        charter, seg_ids = setup_charter(par_value_cents=par_value_cents)
        ctx["charter"] = charter
        ctx["segment_id"] = seg_ids[0]
    else:
        ctx["segment_id"] = segment_id
    ctx["member_id"] = create_member(segment_id=ctx["segment_id"], name=name)
    ctx["account"] = open_account(ctx["member_id"], account_type=account_type,
                                  initial_deposit_cents=deposit)
    return ctx


# ---------------------------------------------------------------------------
# Eligibility reviews and member posture
# ---------------------------------------------------------------------------

def flag_review(member_id, headers=None):
    """Open a MANUAL_FLAG review (flagger co-1 by default)."""
    return get_success_data(api_client.create_eligibility_review(
        member_id, create_review_payload(), headers or FLAGGER))


def confirm_review(review_id, headers=None):
    """Confirm an OPEN review ineligible (decider co-2 by default)."""
    return get_success_data(api_client.confirm_ineligible(
        review_id, headers or REVIEW_DECIDER))


def cure_review(review_id, resolution_note=None, headers=None):
    """Cure an OPEN review (decider co-2 by default)."""
    return get_success_data(api_client.cure_eligibility_review(
        review_id, cure_review_payload(resolution_note),
        headers or REVIEW_DECIDER))


def setup_member_in_grace(name="Grace Member"):
    """Charter + approved member + review confirmed ineligible -> the member is
    in GRACE_PERIOD. Returns a context dict with the member and review ids."""
    charter, seg_ids = setup_charter()
    member_id = create_member(segment_id=seg_ids[0], name=name)
    review = flag_review(member_id)
    confirm_review(review["id"])
    return {"charter": charter, "segment_id": seg_ids[0],
            "member_id": member_id, "review_id": review["id"]}


# ---------------------------------------------------------------------------
# Product enrollments
# ---------------------------------------------------------------------------

def enroll(member_id, funding_share_account_id, product_code="MONEY_MARKET"):
    return get_success_data(api_client.create_product_enrollment(
        create_enrollment_payload(member_id, funding_share_account_id,
                                  product_code=product_code), FILER))


# ---------------------------------------------------------------------------
# Dividend declarations
# ---------------------------------------------------------------------------

def declare_dividend(period_start="2026-07-01", period_end="2026-07-31",
                     rate_bps=600, method="AVERAGE_DAILY_BALANCE",
                     payable_date="2026-08-10"):
    return get_success_data(api_client.create_dividend_declaration(
        create_declaration_payload(
            period_start=period_start, period_end=period_end,
            rate_bps=rate_bps, method=method, payable_date=payable_date),
        BOARD))


def list_declaration_payments(declaration_id, headers=None):
    data, _meta = validate_paginated(
        api_client.list_declaration_payments(declaration_id,
                                             headers or BOARD))
    return data


# ---------------------------------------------------------------------------
# Charter amendments
# ---------------------------------------------------------------------------

def file_add_segment_amendment(charter_id, expected_charter_version,
                               effective_date="2026-09-01",
                               proposed_segment_type="COMMUNITY",
                               proposed_segment_descriptor="Riverside County residents",
                               headers=None):
    return get_success_data(api_client.create_amendment_application(
        add_segment_amendment_payload(
            charter_id, expected_charter_version,
            effective_date=effective_date,
            proposed_segment_type=proposed_segment_type,
            proposed_segment_descriptor=proposed_segment_descriptor),
        headers or FLAGGER))


def file_retire_segment_amendment(charter_id, retire_segment_ids,
                                  expected_charter_version,
                                  effective_date="2026-09-01", headers=None):
    return get_success_data(api_client.create_amendment_application(
        create_amendment_payload(
            charter_id, "RETIRE_SEGMENT", effective_date,
            expected_charter_version, retire_segment_ids=retire_segment_ids),
        headers or FLAGGER))


def approve_amendment(application_id, headers=None):
    return get_success_data(api_client.approve_amendment_application(
        application_id, headers or REGULATOR))


# ---------------------------------------------------------------------------
# Annual meetings and ballots
# ---------------------------------------------------------------------------

def create_meeting(meeting_date="2026-07-20", record_date="2026-07-05",
                   voting_open_date="2026-07-10", quorum_threshold=1):
    return get_success_data(api_client.create_annual_meeting(
        create_meeting_payload(meeting_date=meeting_date,
                               record_date=record_date,
                               voting_open_date=voting_open_date,
                               quorum_threshold=quorum_threshold), BOARD))


def cast_ballot(meeting_id, member_id, choice="FOR_SLATE_A"):
    """Cast a ballot as the member (identity-threaded headers)."""
    return get_success_data(api_client.cast_ballot(
        create_ballot_payload(meeting_id, choice=choice),
        make_member_headers(member_id)))


def close_and_tally(meeting_id):
    return get_success_data(api_client.close_and_tally(meeting_id, BOARD))


def reconvene(meeting_id, meeting_date="2026-07-25",
              voting_open_date="2026-07-16"):
    return get_success_data(api_client.reconvene_meeting(
        meeting_id,
        reconvene_payload(meeting_date=meeting_date,
                          voting_open_date=voting_open_date),
        BOARD))


def setup_voters(count, names=None, approved_name_prefix="Voter"):
    """Charter + `count` approved members at the current clock date.
    Returns (charter, segment_id, [member_ids])."""
    charter, seg_ids = setup_charter()
    member_ids = []
    for i in range(count):
        name = (names[i] if names else f"{approved_name_prefix} {i + 1}")
        member_ids.append(create_member(segment_id=seg_ids[0], name=name,
                                        date_of_birth=f"1990-0{(i % 8) + 1}-0{i % 9 + 1}"))
    return charter, seg_ids[0], member_ids
