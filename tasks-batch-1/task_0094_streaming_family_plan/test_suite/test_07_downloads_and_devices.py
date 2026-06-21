"""Offline downloads and devices: the download-size computation, the HD and
downloadable gates, the per-profile quota (zero edge, slot conservation),
device deregistration cascades and its active-session block, the device cap,
and the license-expiry sweep.

Translates Difficulty/transitive_cascade (deregister frees quota),
Difficulty/boundary_precision_check (zero quota edge),
Difficulty/cross_entity_state_dependency (deregister blocked),
Difficulty/compensating_invariant (quota slot conservation), and
Corner/calculations + Corner/validations + Corner/cross_cutting instances.
"""
from test_helpers import (
    make_owner_headers,
    make_profile_headers,
    validate_success,
    validate_error,
    ApiErrorId,
)
import test_helpers as h


def test_download_size_hd_doubles_sd(api):
    """PRD §3.7: a download's "size_mb is computed from the title's
    license_size_mb: passed through unchanged at SD, and doubled at HD."

    700MB title at HD => 1400.

    Design: Corner/calculations/download_size_hd_doubles_sd
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Big", maturity_rating="PG", runtime_minutes=120, license_size_mb=700)
    account = h.create_account(plan["id"], owner_email="dl@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)

    resp = api.create_download(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"], "quality": "HD"},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(resp, 201)["size_mb"] == 1400


def test_hd_download_on_non_hd_plan_rejected(api):
    """PRD §3.7: "Requesting HD quality requires both that the current plan's
    hd_offline_allowed flag is true and that the device's supports_hd flag is
    true; an HD request that fails either condition is rejected with
    ERR_HD_NOT_ALLOWED."

    Design: Corner/validations/hd_not_allowed_on_sd_plan
    """
    plan = h.create_ad_free_plan()  # hd_offline_allowed == false
    title = h.create_title(name="T", maturity_rating="G", runtime_minutes=45, license_size_mb=300)
    account = h.create_account(plan["id"], owner_email="hd@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)

    resp = api.create_download(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"], "quality": "HD"},
        make_profile_headers(profile["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HD_NOT_ALLOWED.value, 409)


def test_download_of_non_downloadable_title_rejected(api):
    """PRD §3.7: a download may be requested "only for a title whose downloadable
    flag is true (otherwise ERR_TITLE_NOT_DOWNLOADABLE)".

    Design: Corner/validations/title_not_downloadable_rejected
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="NoDl", maturity_rating="G", runtime_minutes=45,
                           downloadable=False, license_size_mb=300)
    account = h.create_account(plan["id"], owner_email="nodl@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="Tab", platform="TABLET", supports_hd=False)

    resp = api.create_download(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"], "quality": "SD"},
        make_profile_headers(profile["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TITLE_NOT_DOWNLOADABLE.value, 409)


def test_zero_download_quota_rejects_first_download(api):
    """PRD §3.7: "the profile's combined count of DOWNLOADING and READY downloads
    must be below the plan's download_quota_per_profile, and a profile already at
    its quota is rejected with ERR_DOWNLOAD_QUOTA_REACHED."

    download_quota_per_profile=0 => the very first download (0 < 0 is false) is
    rejected.

    Design: Difficulty/boundary_precision_check/download_quota_zero_empty_edge
    """
    plan = h.create_ad_supported_plan(download_quota_per_profile=0)
    title = h.create_title(name="DlTitle", maturity_rating="G", runtime_minutes=45, license_size_mb=300)
    account = h.create_account(plan["id"], owner_email="owner12@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="Tab", platform="TABLET", supports_hd=False)

    resp = api.create_download(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"], "quality": "SD"},
        make_profile_headers(profile["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DOWNLOAD_QUOTA_REACHED.value, 409)


def test_deregister_cascade_frees_quota_slot(api):
    """PRD §3.5: a successful deregistration "cascades a deletion of every
    DOWNLOADING or READY Download licensed to that device, each deletion freeing
    one slot of the owning profile's download quota."

    quota=1, one READY download on dev1 (full). Deregistering dev1 deletes that
    download and frees the slot, so a fresh download on dev2 then succeeds.

    Design: Difficulty/transitive_cascade/deregister_depth2_cascade_frees_quota
    """
    plan = h.create_ad_free_plan(download_quota_per_profile=1)
    title = h.create_title(name="Doc", maturity_rating="G", runtime_minutes=45, license_size_mb=300)
    account = h.create_account(plan["id"], owner_email="owner8@x.com")
    profile = h.create_profile(account["id"], display_name="Kid", kind="KID")
    dev1 = h.create_device(account["id"], device_label="Tab", platform="TABLET", supports_hd=False)
    dev2 = h.create_device(account["id"], device_label="Phone", platform="MOBILE", supports_hd=False)
    download = h.create_ready_download(profile["id"], dev1["id"], title["id"], quality="SD")

    h.api_client.deregister_device(dev1["id"], make_owner_headers(account["id"]))

    dl_after = h.fetch_download(account["id"], download["id"])
    assert dl_after["status"] == "DELETED"

    resp = api.create_download(
        {"profile_id": profile["id"], "device_id": dev2["id"], "title_id": title["id"], "quality": "SD"},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(resp, 201)["status"] == "DOWNLOADING"


def test_deregister_blocked_by_active_session_on_device(api):
    """PRD §3.5: "Deregistering a device drives it from REGISTERED to DEREGISTERED
    and is permitted only while it is REGISTERED and only when no ACTIVE
    StreamSession references it."

    Design: Difficulty/cross_entity_state_dependency/deregister_blocked_by_active_session_on_device
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Show", maturity_rating="PG", runtime_minutes=50, license_size_mb=300)
    h.set_clock("2026-06-21T12:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="owner14@x.com", billing_anchor_day=21)
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    h.start_stream(profile["id"], device["id"], title["id"])

    resp = api.deregister_device(device["id"], make_owner_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_download_delete_conserves_profile_quota_slots(api):
    """PRD §3.7: "Deleting a download is permitted from either DOWNLOADING or
    READY, drives it to DELETED, and frees one slot of the profile's download
    quota."

    quota=2: two downloads (full), delete one (frees a slot), then a third create
    succeeds — the freed slot restored the used-count to its pre-create value.

    Design: Difficulty/compensating_invariant/download_delete_conserves_profile_quota_slots
    """
    plan = h.create_ad_free_plan(download_quota_per_profile=2)
    ta = h.create_title(name="A", maturity_rating="G", runtime_minutes=40, license_size_mb=250)
    tb = h.create_title(name="B", maturity_rating="G", runtime_minutes=40, license_size_mb=250)
    tc = h.create_title(name="C", maturity_rating="G", runtime_minutes=40, license_size_mb=250)
    account = h.create_account(plan["id"], owner_email="owner18@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="Tab", platform="TABLET", supports_hd=False)
    dl_a = h.create_download(profile["id"], device["id"], ta["id"], quality="SD")
    h.create_download(profile["id"], device["id"], tb["id"], quality="SD")

    delete = api.delete_download(dl_a["id"], make_profile_headers(profile["id"]))
    assert validate_success(delete, 200)["status"] == "DELETED"

    resp = api.create_download(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": tc["id"], "quality": "SD"},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(resp, 201)["status"] == "DOWNLOADING"


def test_device_cap_reached_on_register(api):
    """PRD §3.5: registration "is permitted only while the account is ACTIVE and
    only while registered_device_count remains below the plan's
    max_registered_devices; exceeding the ceiling is rejected with
    ERR_DEVICE_CAP_REACHED."

    Design: Corner/validations/device_cap_reached_on_register
    """
    plan = h.create_ad_supported_plan(max_profiles=2, max_registered_devices=1,
                                      concurrent_stream_cap=1, download_quota_per_profile=1,
                                      monthly_fee_cents=300)
    account = h.create_account(plan["id"], owner_email="devcap@x.com")
    h.create_device(account["id"], device_label="D1", platform="TV", supports_hd=True)

    resp = api.create_device(
        {"account_id": account["id"], "device_label": "D2", "platform": "MOBILE", "supports_hd": False},
        make_owner_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEVICE_CAP_REACHED.value, 409)


def test_download_license_expiry_sweep_marks_expired(api):
    """PRD §2.9: "every READY Download whose license_expires_at the clock has now
    reached or passed transitions to EXPIRED and frees one of its profile's
    download slots". PRD §3.7: "A READY download whose license window the clock
    has crossed is swept to EXPIRED during a clock advance with sweeps enabled".

    Design: Corner/cross_cutting_complexity_layers/download_license_expiry_sweep_on_clock_advance
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="D", maturity_rating="G", runtime_minutes=40, license_size_mb=250)
    h.set_clock("2026-06-29T00:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="exp2@x.com", billing_anchor_day=28)
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="Tab", platform="TABLET", supports_hd=False)
    download = h.create_ready_download(profile["id"], device["id"], title["id"], quality="SD")

    # Advance far past the license window with sweeps enabled.
    h.set_clock("2026-08-01T00:00:00Z", run_sweeps=True)
    dl_after = h.fetch_download(account["id"], download["id"])
    assert dl_after["status"] == "EXPIRED"
