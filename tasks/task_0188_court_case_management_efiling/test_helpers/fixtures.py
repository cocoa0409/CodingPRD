"""Composite setup helpers.

Each helper builds the multi-step preconditions a family of tests shares, using
only PRD-declared endpoints, against an empty database (the runner restarts the
server before every test). Setup calls use get_success_data (lenient) so setup
failures surface as clear "Setup failed" errors rather than confusing assertion
failures.

Identity threading: an Attorney's identity is the attorney_user_id string on the
party they represent (PRD 2.1). Ownership-gated attorney calls always use
make_attorney_headers(<attorney_user_id>) with that string — never the shared
constant when ownership matters.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_attorney_headers
from .factories import (
    create_court_payload, create_case_payload, create_party_payload,
    create_filing_payload, create_judgment_payload, create_appeal_payload,
    create_motion_payload, rule_motion_payload, create_hearing_payload,
    create_fee_waiver_payload, create_deadline_payload,
    create_service_of_process_payload,
)

ADMIN = TEST_USERS["system_admin_headers"]
CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]

# Default attorney identities used by parties created in fixtures.
ATT_PL = "att_1"   # represents the PLAINTIFF party
ATT_DF = "att_2"   # represents the DEFENDANT party


# --- low-level helpers -------------------------------------------------------
def set_clock(iso: str):
    return get_success_data(api_client.set_clock(iso, ADMIN))


def create_court(**overrides):
    return get_success_data(api_client.create_court(create_court_payload(**overrides), ADMIN))


def create_case(court_id, **overrides):
    return get_success_data(
        api_client.create_case(create_case_payload(court_id, **overrides), CLERK)
    )


def add_party(case_id, role="PLAINTIFF", display_name=None, attorney_user_id=None):
    if attorney_user_id is None:
        attorney_user_id = ATT_PL if role == "PLAINTIFF" else ATT_DF
    if display_name is None:
        display_name = "Acme" if role == "PLAINTIFF" else "Beta"
    payload = create_party_payload(
        case_id, role=role, display_name=display_name, attorney_user_id=attorney_user_id
    )
    return get_success_data(api_client.create_party(payload, CLERK))


def efile(case_id, party_id, attorney_user_id, document_type="COMPLAINT",
          title="Filing", **overrides):
    payload = create_filing_payload(
        case_id, party_id, document_type=document_type, title=title, **overrides
    )
    return get_success_data(
        api_client.create_filing(payload, make_attorney_headers(attorney_user_id))
    )


def pay_review_accept(filing_id):
    """For a COMPLAINT with a positive fee: pay then review then accept."""
    get_success_data(api_client.pay_fee(filing_id, CLERK))
    get_success_data(api_client.claim_review_filing(filing_id, CLERK))
    return get_success_data(api_client.accept_filing(filing_id, CLERK))


def review_accept(filing_id):
    """For a zero-fee filing (no payment needed): review then accept."""
    get_success_data(api_client.claim_review_filing(filing_id, CLERK))
    return get_success_data(api_client.accept_filing(filing_id, CLERK))


# --- Tier 1/2: case in OPEN with both parties + accepted complaint -----------
def setup_open_case(clock="2026-03-01T00:00:00.000Z", court_overrides=None,
                    with_defendant=True):
    """Create court + DRAFT case + plaintiff (+defendant) + accepted+paid
    COMPLAINT, then open the case.

    Returns dict with: court, case (post-open), plaintiff, defendant (or None),
    complaint, case_version (post-open Case.version).
    """
    court_overrides = court_overrides or {}
    set_clock(clock)
    court = create_court(**court_overrides)
    case = create_case(court["id"])
    plaintiff = add_party(case["id"], role="PLAINTIFF", attorney_user_id=ATT_PL)
    defendant = (
        add_party(case["id"], role="DEFENDANT", attorney_user_id=ATT_DF)
        if with_defendant else None
    )
    complaint = efile(case["id"], plaintiff["id"], ATT_PL,
                      document_type="COMPLAINT", title="Complaint")
    pay_review_accept(complaint["id"])
    opened = get_success_data(api_client.open_case(case["id"], CLERK))
    return {
        "court": court,
        "case": opened,
        "plaintiff": plaintiff,
        "defendant": defendant,
        "complaint": complaint,
        "case_version": opened["version"],
    }


def setup_draft_case(clock="2026-03-01T00:00:00.000Z", court_overrides=None):
    """Create court + DRAFT case only. Returns dict with court, case."""
    court_overrides = court_overrides or {}
    set_clock(clock)
    court = create_court(**court_overrides)
    case = create_case(court["id"])
    return {"court": court, "case": case}


# --- Tier 3: accepted MOTION filing + Motion in a target state ---------------
def add_accepted_motion_filing(case_id, plaintiff_id, attorney_user_id=ATT_PL,
                               title="Mtn"):
    """e-File a MOTION-type filing (fee 0) and accept it. Returns the filing."""
    mfiling = efile(case_id, plaintiff_id, attorney_user_id,
                    document_type="MOTION", title=title)
    review_accept(mfiling["id"])
    return mfiling


def file_motion(case_id, filing_id, moving_party_id, attorney_user_id=ATT_PL,
                **overrides):
    payload = create_motion_payload(case_id, filing_id, moving_party_id, **overrides)
    return get_success_data(
        api_client.create_motion(payload, make_attorney_headers(attorney_user_id))
    )


def setup_motion_filed(clock="2026-03-01T00:00:00.000Z", motion_overrides=None):
    """OPEN case with a Motion in FILED state.

    Returns dict extending setup_open_case with: motion_filing, motion.
    """
    base = setup_open_case(clock=clock)
    motion_overrides = motion_overrides or {}
    mfiling = add_accepted_motion_filing(base["case"]["id"], base["plaintiff"]["id"])
    motion = file_motion(base["case"]["id"], mfiling["id"], base["plaintiff"]["id"],
                         **motion_overrides)
    base["motion_filing"] = mfiling
    base["motion"] = motion
    return base


def setup_motion_under_submission(clock="2026-03-01T00:00:00.000Z", motion_overrides=None):
    """OPEN case with a Motion in UNDER_SUBMISSION state (submitted by a judge)."""
    base = setup_motion_filed(clock=clock, motion_overrides=motion_overrides)
    get_success_data(api_client.submit_motion(base["motion"]["id"], JUDGE))
    base["motion"] = get_success_data(api_client.get_motion(base["motion"]["id"], JUDGE))
    return base


# --- Tier 5: judgment entered / on appeal ------------------------------------
def setup_judgment_entered(clock="2026-04-01T00:00:00.000Z", judgment_overrides=None):
    """Case driven to JUDGMENT_ENTERED with an ENTERED judgment.

    Returns dict extending setup_open_case with: judgment, case (post-judgment),
    case_version (current Case.version after judgment entry).
    """
    base = setup_open_case(clock=clock)
    judgment_overrides = judgment_overrides or {}
    payload = create_judgment_payload(
        base["case"]["id"], base["case_version"],
        prevailing_party_id=base["plaintiff"]["id"], **judgment_overrides
    )
    judgment = get_success_data(api_client.create_judgment(payload, JUDGE))
    case_after = get_success_data(api_client.get_case(base["case"]["id"], CLERK))
    base["judgment"] = judgment
    base["case"] = case_after
    base["case_version"] = case_after["version"]
    return base


def setup_notice_filed_appeal(clock="2026-04-01T00:00:00.000Z",
                              filed_on="2026-04-10T00:00:00.000Z",
                              judgment_overrides=None):
    """Case driven to ON_APPEAL with a NOTICE_FILED appeal.

    Returns dict extending setup_judgment_entered with: appeal, case (ON_APPEAL).
    """
    base = setup_judgment_entered(clock=clock, judgment_overrides=judgment_overrides)
    payload = create_appeal_payload(
        base["case"]["id"], base["judgment"]["id"], base["defendant"]["id"],
        filed_on, base["case_version"],
    )
    appeal = get_success_data(
        api_client.create_appeal(payload, make_attorney_headers(ATT_DF))
    )
    case_after = get_success_data(api_client.get_case(base["case"]["id"], CLERK))
    base["appeal"] = appeal
    base["case"] = case_after
    base["case_version"] = case_after["version"]
    return base


# --- Service-of-process helpers ------------------------------------------
def add_attempted_service(case_id, filing_id, served_party_id,
                          service_date="2026-03-02T00:00:00.000Z", method="PERSONAL"):
    payload = create_service_of_process_payload(
        case_id, filing_id, served_party_id, method=method, service_date=service_date
    )
    return get_success_data(api_client.create_service_of_process(payload, CLERK))


# --- Fee-waiver helpers --------------------------------------------------
def add_fee_waiver(case_id, filing_id, requesting_party_id, attorney_user_id=ATT_PL,
                   **overrides):
    payload = create_fee_waiver_payload(case_id, filing_id, requesting_party_id, **overrides)
    return get_success_data(
        api_client.create_fee_waiver(payload, make_attorney_headers(attorney_user_id))
    )


# --- Hearing helpers -----------------------------------------------------
def schedule_hearing(case_id, **overrides):
    payload = create_hearing_payload(case_id, **overrides)
    return get_success_data(api_client.create_hearing(payload, JUDGE))


# --- Deadline helpers ----------------------------------------------------
def add_deadline(case_id, **overrides):
    payload = create_deadline_payload(case_id, **overrides)
    return get_success_data(api_client.create_deadline(payload, CLERK))


def setup_restricted_case(clock="2026-03-01T00:00:00.000Z"):
    """OPEN case pushed to RESTRICTED posture by reaching 5 PENDING deadlines.

    The STATUTE_OF_LIMITATIONS deadline created on open counts as 1; four manual
    deadlines bring open_deadline_count to 5 (>= POSTURE_DEADLINE_LIMIT).
    Returns dict extending setup_open_case (with both parties).
    """
    base = setup_open_case(clock=clock)
    for extra in range(4):
        add_deadline(base["case"]["id"], interval_days=10 + extra)
    base["case"] = get_success_data(api_client.get_case(base["case"]["id"], CLERK))
    return base


def setup_stayed_case(clock="2026-03-01T00:00:00.000Z"):
    """OPEN case driven to STAYED (FROZEN posture) via a granted motion with
    stays_case=true.

    Returns dict extending setup_open_case with: motion, order_id, case (STAYED).
    """
    base = setup_motion_under_submission(clock=clock, motion_overrides={"opposed": True})
    ruled = get_success_data(
        api_client.rule_motion(
            base["motion"]["id"],
            rule_motion_payload(ruling="GRANT", order_text="Granted; stay", stays_case=True),
            JUDGE,
        )
    )
    base["motion"] = ruled
    base["order_id"] = ruled.get("order_id")
    base["case"] = get_success_data(api_client.get_case(base["case"]["id"], CLERK))
    return base
