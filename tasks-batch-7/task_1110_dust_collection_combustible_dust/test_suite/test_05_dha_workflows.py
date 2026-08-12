"""DHA lifecycle: submission, the reject/revise cycle, segregation of duties
at approval, and the optimistic-concurrency check on the parent Site."""
from test_helpers import (
    ApiErrorId,
    assert_dha,
    create_dha,
    create_dha_with_linked_sample,
    create_submitted_dha,
    get_site_version,
    setup_site_with_dust,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.test_users import (
    make_compliance_engineer_headers,
    make_compliance_manager_headers,
)

ENGINEER = TEST_USERS["compliance_engineer_headers"]
MANAGER = TEST_USERS["compliance_manager_headers"]


def test_submit_dha_transitions_to_submitted(api):
    """PRD §3.4: "When the author is satisfied with the draft, they submit it;
    submission moves the DHA from `DRAFT` to `SUBMITTED`."

    Design: Corner/endpoints/action_endpoint_submit_dha_transitions_state
    """
    site, _sample = setup_site_with_dust(insurer_id="FM-1")
    dha = create_dha(site["id"], author_id="eng-1")

    res = api.submit_dha(site["id"], dha["id"],
                         make_compliance_engineer_headers("eng-1"))
    submitted = validate_success(res, 200)
    assert_dha(submitted)
    assert submitted["status"] == "SUBMITTED"


def test_dha_author_cannot_approve_own(api):
    """PRD §3.4: "the approver must not be the DHA's author (a
    `ComplianceManager` whose `X-User-ID` equals `author_id` is rejected with
    `ERR_SOD_VIOLATION`, HTTP 422)".

    Design: Corner/validations/sod_dha_author_cannot_approve_own
    """
    site, sample = setup_site_with_dust(insurer_id="FM-1")
    dha = create_submitted_dha(site["id"], sample["id"], author_id="mgr-1")
    assert dha["status"] == "SUBMITTED"

    site_version = get_site_version(site["id"])
    res = api.approve_dha(site["id"], dha["id"], site_version,
                          make_compliance_manager_headers("mgr-1"))
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION)

    after = validate_success(api.get_dha(site["id"], dha["id"], MANAGER), 200)
    assert after["status"] == "SUBMITTED"


def test_dha_approve_stale_site_version_rejected(api):
    """PRD §2.8: "**Approving a DHA** requires the request body to carry
    `expected_site_version`, which must equal the parent Site's current
    `version`."
    PRD §2.8: "The rejection carries `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.1: "such updates increment `Site.version` by 1".

    Design: Corner/validations/occ_stale_version_rejected
    """
    site, sample = setup_site_with_dust(insurer_id="FM-1")
    dha = create_submitted_dha(site["id"], sample["id"], author_id="eng-1")

    stale_version = get_site_version(site["id"])
    # Any site profile update bumps Site.version, making the captured view stale.
    validate_success(api.update_site(site["id"], {"address": "new address"},
                                     MANAGER), 200)

    res = api.approve_dha(site["id"], dha["id"], stale_version,
                          make_compliance_manager_headers("mgr-1"))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert res.status_code == 412

    after = validate_success(api.get_dha(site["id"], dha["id"], MANAGER), 200)
    assert after["status"] == "SUBMITTED"


def test_dha_revision_cycle_reaches_approved(api):
    """PRD §3.4: "Rejection is also a `ComplianceManager` action and moves the
    DHA from `SUBMITTED` to `REJECTED`. The author can then revise it back to
    `DRAFT` — the revision transition requires the acting `X-User-ID` to equal
    the DHA's `author_id` — and iterate again through submit and approve."
    PRD §3.4: "A successful approval writes `approver_id` to the acting
    `X-User-ID`".

    Full cycle: DRAFT → SUBMITTED → REJECTED → DRAFT → SUBMITTED → APPROVED.

    Design: Difficulty/non_linear_state_machine/dha_revision_cycle_draft_to_rejected_and_back
    """
    site, sample = setup_site_with_dust()
    author = make_compliance_engineer_headers("eng-1")
    dha = create_dha_with_linked_sample(site["id"], sample["id"],
                                        author_id="eng-1")

    validate_success(api.submit_dha(site["id"], dha["id"], author), 200)
    rejected = validate_success(api.reject_dha(site["id"], dha["id"], MANAGER),
                                200)
    assert rejected["status"] == "REJECTED"

    revised = validate_success(api.revise_dha(site["id"], dha["id"], author),
                               200)
    assert revised["status"] == "DRAFT"

    validate_success(api.submit_dha(site["id"], dha["id"], author), 200)
    site_version = get_site_version(site["id"])
    approved = validate_success(
        api.approve_dha(site["id"], dha["id"], site_version,
                        make_compliance_manager_headers("mgr-1")), 200)
    assert approved["status"] == "APPROVED"
    assert approved["approver_id"] == "mgr-1"


def test_dha_revise_returns_to_draft_and_resubmits(api):
    """PRD §3.4: "Rejection is also a `ComplianceManager` action and moves the
    DHA from `SUBMITTED` to `REJECTED`. The author can then revise it back to
    `DRAFT` — the revision transition requires the acting `X-User-ID` to equal
    the DHA's `author_id` — and iterate again through submit and approve."
    PRD §3.4: "submission moves the DHA from `DRAFT` to `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/dha_revision_cycle_draft_to_rejected_and_back
    """
    site, sample = setup_site_with_dust()
    author = make_compliance_engineer_headers("eng-1")
    dha = create_dha_with_linked_sample(site["id"], sample["id"],
                                        author_id="eng-1")

    validate_success(api.submit_dha(site["id"], dha["id"], author), 200)
    validate_success(api.reject_dha(site["id"], dha["id"], MANAGER), 200)

    revised = validate_success(api.revise_dha(site["id"], dha["id"], author),
                               200)
    assert revised["status"] == "DRAFT"

    resubmitted = validate_success(
        api.submit_dha(site["id"], dha["id"], author), 200)
    assert resubmitted["status"] == "SUBMITTED"
