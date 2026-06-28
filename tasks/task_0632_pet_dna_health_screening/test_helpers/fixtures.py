"""Composite setup helpers for the Pet DNA & Health Screening API.

These encapsulate the multi-step sequences tests need to reach a given state.
All setup calls use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors. Every fixture builds its preconditions from
scratch — the test harness restarts the server with an empty database before
each test.

Identity threading: the Account role is entity_backed, so every ownership-gated
call uses make_account_headers(account_id) with the real account id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_account_headers,
)
from .factories import (
    create_account_payload,
    create_pet_payload,
    create_kit_payload,
    activate_kit_payload,
    create_sample_payload,
    pass_run_payload,
    finalize_report_payload,
    create_share_link_payload,
    create_relative_match_payload,
    create_subscription_payload,
    create_data_request_payload,
    create_marker_catalog_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LAB = TEST_USERS["lab_technician_headers"]


# --------------------------------------------------------------------------
# Clock control
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Set the logical clock to a given instant."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# --------------------------------------------------------------------------
# Tier 1: base entity creation
# --------------------------------------------------------------------------

def create_account(**overrides):
    """Register an account (PlatformAdmin). Returns the account dict."""
    return get_success_data(
        api_client.create_account(create_account_payload(**overrides), ADMIN)
    )


def create_pet(account_id, **overrides):
    """Register a pet under an account. Returns the pet dict."""
    return get_success_data(
        api_client.create_pet(
            create_pet_payload(account_id, **overrides),
            make_account_headers(account_id),
        )
    )


def create_kit(account_id, product_tier="BREED", **overrides):
    """Order a kit for an account. Returns the kit dict."""
    return get_success_data(
        api_client.create_kit(
            create_kit_payload(account_id, product_tier=product_tier, **overrides),
            make_account_headers(account_id),
        )
    )


def create_marker_catalog_entry(**overrides):
    """Register a marker-catalog entry (PlatformAdmin)."""
    return get_success_data(
        api_client.create_marker_catalog_entry(
            create_marker_catalog_payload(**overrides), ADMIN
        )
    )


# --------------------------------------------------------------------------
# Tier 2: kit lifecycle to ACTIVATED / sample RECEIVED
# --------------------------------------------------------------------------

def create_activated_kit(account_id, pet_id, product_tier="BREED"):
    """Order a kit and activate it against pet_id. Returns the kit dict (ACTIVATED)."""
    kit = create_kit(account_id, product_tier=product_tier)
    get_success_data(
        api_client.activate_kit(
            kit["id"], activate_kit_payload(pet_id), make_account_headers(account_id)
        )
    )
    return get_success_data(api_client.get_kit(kit["id"], make_account_headers(account_id)))


def setup_received_sample(product_tier="BREED", account_overrides=None,
                          pet_overrides=None):
    """Account + pet + activated kit + received sample.

    Returns dict with keys: account, pet, kit, sample.
    """
    account = create_account(**(account_overrides or {}))
    pet = create_pet(account["id"], **(pet_overrides or {}))
    kit = create_activated_kit(account["id"], pet["id"], product_tier=product_tier)
    sample = get_success_data(
        api_client.create_sample(create_sample_payload(kit["id"]), LAB)
    )
    return {"account": account, "pet": pet, "kit": kit, "sample": sample}


# --------------------------------------------------------------------------
# Tier 3: genotyping to PASS / report (PRELIMINARY) / FINALIZED
# --------------------------------------------------------------------------

def setup_preliminary_report(product_tier="BREED", breed_segments=None,
                             account_overrides=None, pet_overrides=None):
    """Account + pet + activated kit + sample + PASS run -> PRELIMINARY report.

    Returns dict with keys: account, pet, kit, sample, report.
    """
    base = setup_received_sample(
        product_tier=product_tier,
        account_overrides=account_overrides,
        pet_overrides=pet_overrides,
    )
    get_success_data(
        api_client.create_genotyping_run(
            base["sample"]["id"], pass_run_payload(breed_segments=breed_segments), LAB
        )
    )
    reports = get_success_data(
        api_client.list_reports(LAB, params={"sample_id": base["sample"]["id"]})
    )
    report = reports[0]
    base["report"] = report
    return base


def setup_finalized_report(product_tier="BREED", breed_segments=None,
                           account_overrides=None, pet_overrides=None):
    """Drive a sample through PASS, then finalize its report.

    Returns dict with keys: account, pet, kit, sample, report (FINALIZED).
    """
    base = setup_preliminary_report(
        product_tier=product_tier,
        breed_segments=breed_segments,
        account_overrides=account_overrides,
        pet_overrides=pet_overrides,
    )
    rep = base["report"]
    finalized = get_success_data(
        api_client.finalize_report(
            rep["id"], finalize_report_payload(rep["version"]), LAB
        )
    )
    base["report"] = finalized
    return base


# --------------------------------------------------------------------------
# Tier 4: relative-finder setups
# --------------------------------------------------------------------------

def setup_two_pets_both_finalized(shared_cm=600):
    """Account opted-in, two opted-in pets each with a FINALIZED report,
    and an ESTIMATED RelativeMatch between them.

    Returns dict: account, pet1, pet2, report1, report2, match.
    """
    account = create_account(relative_finder_opt_in=True)

    pet1 = create_pet(account["id"], name="P1", relative_finder_opt_in=True)
    pet2 = create_pet(account["id"], name="P2", relative_finder_opt_in=True)

    rep1 = _finalize_pet_report(account["id"], pet1["id"], breed="LABRADOR")
    rep2 = _finalize_pet_report(account["id"], pet2["id"], breed="POODLE")

    match = get_success_data(
        api_client.create_relative_match(
            create_relative_match_payload(pet1["id"], pet2["id"], shared_cm=shared_cm), LAB
        )
    )
    return {
        "account": account, "pet1": pet1, "pet2": pet2,
        "report1": rep1, "report2": rep2, "match": match,
    }


def _finalize_pet_report(account_id, pet_id, breed="LABRADOR"):
    """Activate a kit for an existing pet, drive to PASS, finalize. Returns report."""
    kit = create_activated_kit(account_id, pet_id, product_tier="BREED")
    sample = get_success_data(
        api_client.create_sample(create_sample_payload(kit["id"]), LAB)
    )
    get_success_data(
        api_client.create_genotyping_run(
            sample["id"],
            pass_run_payload(breed_segments=[{"breed": breed, "match_cm": 1000}]),
            LAB,
        )
    )
    reports = get_success_data(
        api_client.list_reports(LAB, params={"sample_id": sample["id"]})
    )
    rep = reports[0]
    return get_success_data(
        api_client.finalize_report(rep["id"], finalize_report_payload(rep["version"]), LAB)
    )


def setup_estimated_match_two_pets(shared_cm=625):
    """Two opted-in pets (no reports) with an ESTIMATED match between them.

    Returns dict: account, pet1, pet2, match.
    """
    account = create_account(relative_finder_opt_in=True)
    pet1 = create_pet(account["id"], name="P1", relative_finder_opt_in=True)
    pet2 = create_pet(account["id"], name="P2", relative_finder_opt_in=True)
    match = get_success_data(
        api_client.create_relative_match(
            create_relative_match_payload(pet1["id"], pet2["id"], shared_cm=shared_cm), LAB
        )
    )
    return {"account": account, "pet1": pet1, "pet2": pet2, "match": match}


# --------------------------------------------------------------------------
# Tier 5: share links
# --------------------------------------------------------------------------

def setup_finalized_report_with_share_link(vet_email="vet@example.com"):
    """A FINALIZED report with one ACTIVE share link.

    Returns dict: account, pet, kit, sample, report, share_link.
    """
    base = setup_finalized_report(product_tier="BREED")
    share = get_success_data(
        api_client.create_share_link(
            create_share_link_payload(base["report"]["id"], vet_email=vet_email),
            make_account_headers(base["account"]["id"]),
        )
    )
    base["share_link"] = share
    return base


# --------------------------------------------------------------------------
# Tier 6: subscriptions
# --------------------------------------------------------------------------

def setup_active_basic_subscription(annual_fee_cents=9900, clock="2026-01-01T00:00:00Z"):
    """Clock set, account, one ACTIVE BASIC subscription.

    Returns dict: account, subscription.
    """
    set_clock(clock)
    account = create_account()
    acct_h = make_account_headers(account["id"])
    sub = get_success_data(
        api_client.create_subscription(
            create_subscription_payload(account["id"], tier="BASIC",
                                        annual_fee_cents=annual_fee_cents),
            acct_h,
        )
    )
    return {"account": account, "subscription": sub}


def setup_active_premium_subscription(annual_fee_cents=19900, clock="2026-01-01T00:00:00Z"):
    """Clock set, account, one ACTIVE PREMIUM subscription.

    Returns dict: account, subscription.
    """
    set_clock(clock)
    account = create_account()
    acct_h = make_account_headers(account["id"])
    sub = get_success_data(
        api_client.create_subscription(
            create_subscription_payload(account["id"], tier="PREMIUM",
                                        annual_fee_cents=annual_fee_cents),
            acct_h,
        )
    )
    return {"account": account, "subscription": sub}


# --------------------------------------------------------------------------
# Tier 7: data requests
# --------------------------------------------------------------------------

def setup_delete_request_in_grace(clock="2026-05-01T00:00:00Z", num_pets=0):
    """Clock set, account with num_pets pets, and a DELETE DataRequest in GRACE.

    Returns dict: account, pets (list), data_request.
    """
    set_clock(clock)
    account = create_account()
    pets = [create_pet(account["id"], name=f"P{i}") for i in range(num_pets)]
    dr = get_success_data(
        api_client.create_data_request(
            create_data_request_payload(account["id"], kind="DELETE"),
            make_account_headers(account["id"]),
        )
    )
    return {"account": account, "pets": pets, "data_request": dr}
