"""The tax document walks draft, submitted, decided, revised, superseded."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_instant
from test_helpers.constants import (
    BACKUP_WITHHOLDING_BPS,
    FORM_W9,
    PERIOD_CLOSED,
    TAX_DRAFT,
    TAX_EXPIRED,
    TAX_REJECTED,
    TAX_SUBMITTED,
    TAX_SUPERSEDED,
    TAX_VERIFIED,
)
from test_helpers.fixtures import august_period, new_creator, refresh_creator
from test_helpers.test_users import ADMIN, FINANCE, make_creator_headers


def _draft_profile(api, tin_provided=True):
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    profile = get_success_data(
        api.create_tax_profile(
            fac.tax_profile_payload(
                creator["id"],
                creator["version"],
                form_type=FORM_W9,
                country_code="US",
                tin_provided=tin_provided,
            ),
            make_creator_headers(creator["id"]),
        )
    )
    return creator, profile


def test_submitting_a_draft_stamps_the_submission_instant(api):
    """Submission moves the document on but does not lower its rate.

    Design: Corner/state_machines/tax_profile_draft_to_submitted_records_submitted_at
    """
    creator, profile = _draft_profile(api)

    submitted = validate_success(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"])), 200
    )
    assert submitted["status"] == TAX_SUBMITTED
    assert_instant(submitted["submitted_at"], "2026-08-01T00:00:00Z")
    assert submitted["withholding_rate_bps"] == BACKUP_WITHHOLDING_BPS


def test_verification_dates_the_document_three_years_out(api):
    """Verifying zeroes the rate and stamps both the decision and the expiry.

    Design: Corner/state_machines/tax_profile_verify_sets_expires_at_from_validity_days_constant
    """
    creator, profile = _draft_profile(api)
    get_success_data(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"]))
    )

    verified = validate_success(
        api.verify_tax_profile(profile["id"], fac.verify_payload(), FINANCE)
    )
    assert verified["status"] == TAX_VERIFIED
    assert_instant(verified["verified_at"], "2026-08-01T00:00:00Z")
    assert_instant(verified["expires_at"], "2029-07-31T00:00:00Z")
    assert verified["withholding_rate_bps"] == 0
    assert verified["rejection_reason"] is None


def test_a_rejected_document_can_be_revised_back_to_a_draft(api):
    """Rejection records its reason and revision clears it again.

    The rejected document withholds at the backup rate, and revising restores a
    draft with the corrected taxpayer number and the reason cleared.

    Design: Corner/state_machines/tax_profile_rejected_then_revise_returns_to_draft
    """
    creator, profile = _draft_profile(api, tin_provided=False)
    get_success_data(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"]))
    )

    rejected = validate_success(
        api.verify_tax_profile(
            profile["id"],
            fac.reject_payload(rejection_reason="TIN missing from the submitted form."),
            FINANCE,
        )
    )
    assert rejected["status"] == TAX_REJECTED
    assert rejected["rejection_reason"] == "TIN missing from the submitted form."
    assert rejected["withholding_rate_bps"] == BACKUP_WITHHOLDING_BPS

    revised = validate_success(
        api.revise_tax_profile(
            profile["id"],
            fac.revise_payload(tin_provided=True),
            make_creator_headers(creator["id"]),
        )
    )
    assert revised["status"] == TAX_DRAFT
    assert revised["rejection_reason"] is None
    assert revised["tin_provided"] is True
    assert revised["withholding_rate_bps"] == BACKUP_WITHHOLDING_BPS


def test_a_newer_document_supersedes_the_old_one_for_good(api):
    """The superseded document is terminal and cannot be resubmitted.

    The replacement is a draft back at the backup rate, and the retired document
    refuses a fresh submission because it is no longer a draft.

    Design: Corner/state_machines/newer_tax_profile_supersedes_prior_profile_terminally
    """
    creator, first = _draft_profile(api)
    get_success_data(
        api.submit_tax_profile(first["id"], make_creator_headers(creator["id"]))
    )
    get_success_data(api.verify_tax_profile(first["id"], fac.verify_payload(), FINANCE))
    current = refresh_creator(api, creator["id"])

    second = get_success_data(
        api.create_tax_profile(
            fac.tax_profile_payload(
                creator["id"],
                current["version"],
                form_type=FORM_W9,
                country_code="US",
                tin_provided=False,
            ),
            make_creator_headers(creator["id"]),
        )
    )
    assert validate_success(api.get_tax_profile(first["id"], FINANCE))["status"] == (
        TAX_SUPERSEDED
    )
    assert second["status"] == TAX_DRAFT
    assert second["withholding_rate_bps"] == BACKUP_WITHHOLDING_BPS

    validate_error(
        api.submit_tax_profile(first["id"], make_creator_headers(creator["id"])),
        err.ERR_TAX_PROFILE_NOT_DRAFT,
        409,
    )


def test_a_stale_document_is_only_expired_by_the_next_close(api):
    """Passing the expiry instant does not itself rewrite the document.

    Three years on the document still reads verified, and the first period close
    after that instant is what marks it expired while keeping its expiry stamp.

    Design: Corner/state_machines/verified_tax_profile_expires_during_period_close_step_one
    """
    creator, profile = _draft_profile(api)
    get_success_data(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"]))
    )
    get_success_data(api.verify_tax_profile(profile["id"], fac.verify_payload(), FINANCE))
    period = august_period(api)
    get_success_data(api.set_clock(fac.clock_payload("2029-08-01T00:00:00Z"), ADMIN))

    before = validate_success(api.get_tax_profile(profile["id"], FINANCE))
    assert before["status"] == TAX_VERIFIED

    closed = validate_success(api.close_period(period["id"], FINANCE))
    assert closed["status"] == PERIOD_CLOSED

    after = validate_success(api.get_tax_profile(profile["id"], FINANCE))
    assert after["status"] == TAX_EXPIRED
    assert_instant(after["expires_at"], "2029-07-31T00:00:00Z")
