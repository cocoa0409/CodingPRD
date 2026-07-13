"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty DB) before every individual test.

All helpers use get_success_data() (lenient) so a broken setup step raises a clear
"Setup failed" style error rather than a confusing downstream assertion failure.

Identity threading: Contributor is entity_backed, so every ownership-gated contributor
call uses make_contributor_headers(<contributor id>), never the shared fallback header.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_contributor_headers
from . import factories as f

FINANCE = TEST_USERS["finance_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #
def set_clock(api, iso: str):
    """Advance/set the logical clock (FinanceAdmin only)."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, FINANCE))


def register_contributor(api, **overrides) -> dict:
    """Self-register a contributor (created PENDING, no auth headers)."""
    return get_success_data(api.create_contributor(f.create_contributor_payload(**overrides)))


def get_contributor(api, contributor_id: str) -> dict:
    return get_success_data(api.get_contributor(contributor_id, FINANCE))


def get_contributor_version(api, contributor_id: str) -> int:
    return get_contributor(api, contributor_id)["version"]


def create_license_tier(api, code="STANDARD", base_price_cents=1000) -> dict:
    return get_success_data(
        api.create_license_tier(
            f.create_license_tier_payload(code=code, base_price_cents=base_price_cents), FINANCE
        )
    )


def submit_and_verify_tax_form(api, contributor_id, form_type="W9", tax_id="TAX-1",
                               treaty_rate_pct=None) -> dict:
    """Submit a tax form and VERIFY it — activates a PENDING contributor. Returns the tax form."""
    payload = {"form_type": form_type, "tax_id": tax_id}
    if treaty_rate_pct is not None:
        payload["treaty_rate_pct"] = treaty_rate_pct
    ch = make_contributor_headers(contributor_id)
    tf = get_success_data(api.create_tax_form(contributor_id, payload, ch))
    get_success_data(api.decide_tax_form(tf["id"], {"decision": "VERIFY"}, COMPLIANCE))
    return tf


def onboard_active_contributor(api, country_code="US", form_type="W9", tax_id="TAX-1",
                               treaty_rate_pct=None, **overrides) -> dict:
    """Register + submit tax form + verify → returns the re-fetched ACTIVE contributor."""
    c = register_contributor(api, country_code=country_code, **overrides)
    submit_and_verify_tax_form(api, c["id"], form_type=form_type, tax_id=tax_id,
                               treaty_rate_pct=treaty_rate_pct)
    return get_contributor(api, c["id"])


def add_exclusivity_window(api, contributor_id, start_at="2026-03-01T00:00:00Z",
                           end_at="2027-03-01T00:00:00Z") -> dict:
    ch = make_contributor_headers(contributor_id)
    return get_success_data(
        api.create_exclusivity_window(
            contributor_id, {"start_at": start_at, "end_at": end_at}, ch
        )
    )


def add_earning_adjustment(api, contributor_id, amount_cents, reason="adj") -> dict:
    return get_success_data(
        api.create_earning_adjustment(
            contributor_id, {"amount_cents": amount_cents, "reason": reason}, FINANCE
        )
    )


def create_model_release(api, contributor_id, release_type="MODEL", releaser_name="Jane Doe",
                         verify=False) -> dict:
    ch = make_contributor_headers(contributor_id)
    rel = get_success_data(
        api.create_model_release(
            contributor_id, {"release_type": release_type, "releaser_name": releaser_name}, ch
        )
    )
    if verify:
        get_success_data(api.decide_model_release(rel["id"], {"decision": "VERIFY"}, COMPLIANCE))
    return rel


# --------------------------------------------------------------------------- #
# Asset lifecycle
# --------------------------------------------------------------------------- #
def create_draft_asset(api, contributor_id, **overrides) -> dict:
    ch = make_contributor_headers(contributor_id)
    return get_success_data(
        api.create_asset(f.create_asset_payload(contributor_id, **overrides), ch)
    )


def create_submitted_asset(api, contributor_id, **overrides) -> dict:
    a = create_draft_asset(api, contributor_id, **overrides)
    ch = make_contributor_headers(contributor_id)
    return get_success_data(api.submit_asset(a["id"], ch))


def create_in_review_asset(api, contributor_id, **overrides) -> dict:
    a = create_submitted_asset(api, contributor_id, **overrides)
    return get_success_data(api.claim_asset(a["id"], REVIEWER))


def create_accepted_asset(api, contributor_id, **overrides) -> dict:
    """Create → submit → claim → ACCEPT. Contributor must already be ACTIVE."""
    a = create_in_review_asset(api, contributor_id, **overrides)
    get_success_data(api.create_review(a["id"], {"decision": "ACCEPT"}, REVIEWER))
    return get_success_data(api.get_asset(a["id"], REVIEWER))


# --------------------------------------------------------------------------- #
# Downloads / earnings
# --------------------------------------------------------------------------- #
def create_download(api, asset_id, license_tier_code="STANDARD", buyer_reference="buy-1") -> dict:
    return get_success_data(
        api.create_download(
            {"asset_id": asset_id, "license_tier_code": license_tier_code,
             "buyer_reference": buyer_reference}, FINANCE
        )
    )


def settle_download(api, download_id) -> dict:
    return get_success_data(api.settle_download(download_id, FINANCE))


def create_settled_download(api, asset_id, license_tier_code="STANDARD", buyer_reference="buy-1",
                            settle_clock="2026-04-01T00:00:00Z") -> dict:
    """Create a download at the default clock, advance past clearing, and settle it."""
    dl = create_download(api, asset_id, license_tier_code, buyer_reference)
    set_clock(api, settle_clock)
    return settle_download(api, dl["id"])


# --------------------------------------------------------------------------- #
# Higher-level composite scenarios
# --------------------------------------------------------------------------- #
def setup_exclusive_bronze_with_accepted_asset(api, country_code="US", form_type="W9",
                                               tax_id="TAX-1", content_category="COMMERCIAL",
                                               tier_code="ENHANCED", base_price_cents=1500):
    """ACTIVE, EXCLUSIVE (window covers default clock), BRONZE contributor with one ACCEPTED
    asset and a license tier. Returns (contributor_id, asset, tier)."""
    tier = create_license_tier(api, code=tier_code, base_price_cents=base_price_cents)
    c = onboard_active_contributor(api, country_code=country_code, form_type=form_type, tax_id=tax_id)
    add_exclusivity_window(api, c["id"])
    asset = create_accepted_asset(api, c["id"], content_category=content_category)
    return c["id"], asset, tier


def setup_payout_ready_foreign(api, treaty_rate_pct=None, tier_base=1500, num_downloads=2,
                               adjustment_cents=10000):
    """Foreign (CA/W8BEN) ACTIVE EXCLUSIVE+BRONZE contributor; num_downloads ENHANCED downloads
    settled to AVAILABLE; then an earning adjustment. Returns (contributor_id, version)."""
    tier = create_license_tier(api, code="ENHANCED", base_price_cents=tier_base)
    c = onboard_active_contributor(api, country_code="CA", form_type="W8BEN", tax_id="CA-1",
                                   treaty_rate_pct=treaty_rate_pct)
    add_exclusivity_window(api, c["id"])
    asset = create_accepted_asset(api, c["id"])
    dl_ids = []
    for i in range(num_downloads):
        dl = create_download(api, asset["id"], "ENHANCED", buyer_reference=f"buy-{i}")
        dl_ids.append(dl["id"])
    set_clock(api, "2026-04-01T00:00:00Z")
    for dl_id in dl_ids:
        settle_download(api, dl_id)
    if adjustment_cents:
        add_earning_adjustment(api, c["id"], adjustment_cents, reason="referral bonus")
    return c["id"], get_contributor_version(api, c["id"])


def setup_active_contributor_with_available_balance(api, adjustment_cents=10000, form_type="W9",
                                                    country_code="US"):
    """ACTIVE US/W9 contributor whose available balance comes solely from an adjustment.
    Returns (contributor_id, version)."""
    c = onboard_active_contributor(api, country_code=country_code, form_type=form_type, tax_id="TAX-A")
    add_earning_adjustment(api, c["id"], adjustment_cents, reason="seed")
    return c["id"], get_contributor_version(api, c["id"])


def setup_accepted_asset_with_settled_download(api, tier_base=1000):
    """ACTIVE US/W9 non-exclusive BRONZE contributor with one ACCEPTED asset and one settled
    AVAILABLE download (STANDARD, royalty 150). Returns (contributor_id, asset, download_id)."""
    create_license_tier(api, code="STANDARD", base_price_cents=tier_base)
    c = onboard_active_contributor(api, tax_id="TAX-S")
    asset = create_accepted_asset(api, c["id"])
    dl = create_download(api, asset["id"], "STANDARD")
    set_clock(api, "2026-04-01T00:00:00Z")
    settle_download(api, dl["id"])
    return c["id"], asset, dl["id"]


def setup_accepted_asset_with_open_takedown(api, settle=True, tier_base=1000):
    """ACTIVE non-exclusive BRONZE contributor with one ACCEPTED asset, one download
    (settled AVAILABLE when settle=True, else left PENDING), and one OPEN takedown.
    Returns (contributor_id, asset, download_id, takedown_id)."""
    create_license_tier(api, code="STANDARD", base_price_cents=tier_base)
    c = onboard_active_contributor(api, tax_id="TAX-T")
    asset = create_accepted_asset(api, c["id"])
    dl = create_download(api, asset["id"], "STANDARD")
    if settle:
        set_clock(api, "2026-04-01T00:00:00Z")
        settle_download(api, dl["id"])
    td = get_success_data(
        api.create_takedown(asset["id"], f.create_takedown_payload(), COMPLIANCE)
    )
    return c["id"], asset, dl["id"], td["id"]


def setup_suspended_contributor(api):
    """ACTIVE contributor driven to SUSPENDED via three ACCEPTED assets each UPHELD (strike 3),
    available balance 0. Returns (contributor_id, version)."""
    c = onboard_active_contributor(api, tax_id="TAX-SUS")
    cid = c["id"]
    for i, phash in enumerate(("aaaa", "bbbb", "cccc")):
        asset = create_accepted_asset(api, cid, perceptual_hash=phash, title=f"A{i}")
        td = get_success_data(
            api.create_takedown(
                asset["id"], {"claim_type": "COPYRIGHT", "claimant_name": f"L{i}"}, COMPLIANCE
            )
        )
        get_success_data(api.decide_takedown(td["id"], {"decision": "UPHOLD"}, COMPLIANCE))
    return cid, get_contributor_version(api, cid)
