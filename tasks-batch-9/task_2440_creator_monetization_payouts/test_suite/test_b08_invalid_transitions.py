"""Calls made from the wrong state change nothing at all."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_instant
from test_helpers.constants import (
    RATING_RED,
    RATING_SOURCE_AUTOMATED,
    RATING_SOURCE_MANUAL,
    TAX_DRAFT,
    TAX_SUBMITTED,
    TAX_VERIFIED,
)
from test_helpers.fixtures import content_item, new_creator, subs_product
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER, REVIEWER_ALT, make_creator_headers


def _draft_profile(api, tin_provided=True):
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    profile = get_success_data(
        api.create_tax_profile(
            fac.tax_profile_payload(
                creator["id"], creator["version"], country_code="US",
                tin_provided=tin_provided,
            ),
            make_creator_headers(creator["id"]),
        )
    )
    return creator, profile


def test_a_verified_document_cannot_be_submitted_again(api):
    """Submission is only ever a draft's move.

    Design: Corner/state_machines/submit_verified_tax_profile_rejected_as_not_draft
    """
    creator, profile = _draft_profile(api)
    get_success_data(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"]))
    )
    get_success_data(api.verify_tax_profile(profile["id"], fac.verify_payload(), FINANCE))

    validate_error(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"])),
        err.ERR_TAX_PROFILE_NOT_DRAFT,
        409,
    )
    reloaded = validate_success(api.get_tax_profile(profile["id"], FINANCE))
    assert reloaded["status"] == TAX_VERIFIED
    assert_instant(reloaded["verified_at"], "2026-08-01T00:00:00Z")


def test_a_draft_document_cannot_receive_a_verification_decision(api):
    """A decision requires a submission first.

    Design: Corner/state_machines/verify_draft_tax_profile_rejected_as_not_submitted
    """
    _creator, profile = _draft_profile(api)

    validate_error(
        api.verify_tax_profile(profile["id"], fac.verify_payload(), FINANCE),
        err.ERR_TAX_PROFILE_NOT_SUBMITTED,
        409,
    )
    reloaded = validate_success(api.get_tax_profile(profile["id"], FINANCE))
    assert reloaded["status"] == TAX_DRAFT
    assert reloaded["verified_at"] is None


def test_a_submitted_document_cannot_be_revised(api):
    """Revision is reserved for a document that was actually rejected.

    Design: Corner/state_machines/revise_submitted_tax_profile_rejected_as_not_rejected
    """
    creator, profile = _draft_profile(api, tin_provided=False)
    get_success_data(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"]))
    )

    validate_error(
        api.revise_tax_profile(
            profile["id"],
            fac.revise_payload(tin_provided=True),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_TAX_PROFILE_NOT_REJECTED,
        409,
    )
    reloaded = validate_success(api.get_tax_profile(profile["id"], FINANCE))
    assert reloaded["status"] == TAX_SUBMITTED
    assert reloaded["tin_provided"] is False


def test_retiring_a_retired_surface_does_not_re_stamp_it(api):
    """The second retirement is refused even a day later.

    Design: Corner/state_machines/retire_already_retired_product_rejected
    """
    product = subs_product(api, name="Memberships")
    get_success_data(api.retire_product(product["id"], ADMIN))
    get_success_data(api.set_clock(fac.clock_payload("2026-08-02T00:00:00Z"), ADMIN))

    validate_error(
        api.retire_product(product["id"], ADMIN),
        err.ERR_PRODUCT_ALREADY_RETIRED,
        409,
    )
    rows = get_success_data(api.list_products(ADMIN))
    assert_instant(rows[0]["retired_at"], "2026-08-01T00:00:00Z")


def test_a_retired_surface_has_frozen_terms(api):
    """Amendment is refused with the same error as a second retirement.

    Design: Corner/state_machines/patch_retired_product_rejected_as_already_retired
    """
    product = subs_product(api, name="Memberships")
    get_success_data(api.retire_product(product["id"], ADMIN))

    validate_error(
        api.patch_product(product["id"], {"creator_share_bps": 8000}, ADMIN),
        err.ERR_PRODUCT_ALREADY_RETIRED,
        409,
    )
    rows = get_success_data(api.list_products(ADMIN))
    assert rows[0]["creator_share_bps"] == 7000


def test_re_rating_a_clip_to_the_rating_it_already_has_is_refused(api):
    """A rating change must actually change something.

    The refused call does not overwrite the provenance or the rater recorded by
    the rating that did take effect.

    Design: Corner/state_machines/rate_content_item_with_unchanged_rating_rejected
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )
    get_success_data(
        api.rate_content_item(item["id"], fac.rate_payload(RATING_RED), REVIEWER)
    )

    validate_error(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_RED, rating_source=RATING_SOURCE_AUTOMATED),
            REVIEWER_ALT,
        ),
        err.ERR_RATING_UNCHANGED,
        409,
    )
    reloaded = validate_success(api.get_content_item(item["id"], REVIEWER))
    assert reloaded["rating_source"] == RATING_SOURCE_MANUAL
    assert reloaded["last_rated_by_user_id"] == "reviewer-r1"
