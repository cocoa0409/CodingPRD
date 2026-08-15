"""Consent record cyclic lifecycle, dual expiry horizons, and counter ledger."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_property, create_active_policy, create_adult_visitor,
    create_consent_record_payload,
    make_visitor_headers,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
ANY = TEST_USERS["any_headers"]

GDPR = dict(
    jurisdiction_code="EU-GDPR", banner_regime="OPT_IN_REQUIRED",
    min_consent_age=16, retention_days=30, gpc_honored=False,
    effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
)


def _cycle_site(api):
    prop = create_property(name="Cycle Site", sale_share_designation="NO_SALE_NO_SHARE")
    pol = create_active_policy(prop["id"], **GDPR)
    vis = create_adult_visitor(
        prop["id"], birthdate="1995-03-03T00:00:00Z",
        external_ref="cyc@x.com", jurisdiction_code="EU-GDPR",
    )
    get_success_data(api.set_clock({"to_iso8601": "2026-05-10T00:00:00Z"}, ADMIN))
    return prop, pol, vis


def test_grant_withdraw_regrant_cycle(api):
    """PRD section 3.5: "Its lifecycle is deliberately cyclic: `GRANTED →
    WITHDRAWN → GRANTED` and around again. Withdrawal requires `GRANTED` and
    works even while the property is frozen; re-grant requires `WITHDRAWN` and
    re-applies the grant-time gates (posture, age, child, policy, window),
    refreshing the policy snapshot, the banner binding, and the timestamps."

    Design: Difficulty/non_linear_state_machine/consent_record_grant_withdraw_cycle
    """
    prop, pol, vis = _cycle_site(api)
    vh = make_visitor_headers(vis["id"])
    rec = get_success_data(
        api.create_consent_record(vis["id"], create_consent_record_payload("ANALYTICS"), vh)
    )
    w1 = validate_success(api.withdraw_consent_record(rec["id"], vh), 200)
    assert w1["status"] == "WITHDRAWN"
    r1 = validate_success(api.regrant_consent_record(rec["id"], vh), 200)
    assert r1["status"] == "GRANTED", "loop back to GRANTED on regrant"
    assert r1["policy_snapshot_retention_days"] == 30, "regrant refreshed the policy snapshot"
    w2 = validate_success(api.withdraw_consent_record(rec["id"], vh), 200)
    assert w2["status"] == "WITHDRAWN", "loop completed a second lap"
    assert w2["source_of_decision"] == "EXPLICIT_WITHDRAW"


def test_cycle_tracks_property_counter_each_lap(api):
    """PRD section 3.5: "Grants and re-grants increment it; withdrawals and
    expiries decrement it; a grant-then-withdraw pair nets to zero; and every
    such adjustment also increments the property's `version`."

    Design: Difficulty/non_linear_state_machine/consent_record_grant_withdraw_cycle
    """
    prop, pol, vis = _cycle_site(api)
    vh = make_visitor_headers(vis["id"])
    rec = get_success_data(
        api.create_consent_record(vis["id"], create_consent_record_payload("ANALYTICS"), vh)
    )
    assert get_success_data(api.get_property(prop["id"], ANY))["granted_purpose_count"] == 1
    get_success_data(api.withdraw_consent_record(rec["id"], vh))
    assert get_success_data(api.get_property(prop["id"], ANY))["granted_purpose_count"] == 0
    get_success_data(api.regrant_consent_record(rec["id"], vh))
    assert get_success_data(api.get_property(prop["id"], ANY))["granted_purpose_count"] == 1
    get_success_data(api.withdraw_consent_record(rec["id"], vh))
    final = get_success_data(api.get_property(prop["id"], ANY))
    assert final["granted_purpose_count"] == 0, "1 grant, +1 regrant, -2 withdraws nets to 0"


def test_retention_pinned_vs_rolling_expiry_diverge(api):
    """PRD section 2.10: "When the privacy team amends a policy's retention
    horizon, existing records keep their pinned horizon while their rolling
    horizon moves — the two values intentionally diverge, and the record's
    lifecycle follows the pinned one."

    Design: Difficulty/dual_variant_calc/retention_pinned_vs_rolling_expiry
    """
    prop = create_property(name="Retention Site", sale_share_designation="SELLS_AND_SHARES")
    pol = create_active_policy(
        prop["id"], jurisdiction_code="EU-GDPR", banner_regime="OPT_IN_REQUIRED",
        min_consent_age=16, retention_days=30, gpc_honored=True,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    vis = create_adult_visitor(
        prop["id"], birthdate="2000-01-01T00:00:00Z",
        external_ref="rv1@x.com", jurisdiction_code="EU-GDPR",
    )
    get_success_data(api.set_clock({"to_iso8601": "2026-05-10T00:00:00Z"}, ADMIN))
    rec = get_success_data(
        api.create_consent_record(
            vis["id"], create_consent_record_payload("ANALYTICS"),
            make_visitor_headers(vis["id"]),
        )
    )
    # Amend retention horizon 30 -> 10 while the policy is ACTIVE.
    get_success_data(api.update_jurisdiction_policy(pol["id"], {"retention_days": 10}, ADMIN))

    after = get_success_data(api.get_consent_record(rec["id"], ANY))
    assert after["expires_at_pinned"] == "2026-06-09T00:00:00.000Z", (
        "last_changed 2026-05-10 + 30d snapshot"
    )
    assert after["expires_at_rolling"] == "2026-05-20T00:00:00.000Z", (
        "last_changed + live 10d"
    )
    assert after["expires_at_pinned"] != after["expires_at_rolling"]
    assert after["policy_snapshot_retention_days"] == 30


def test_retention_pinned_is_authoritative_after_rolling_passes(api):
    """PRD section 2.10: "two expiry horizons are then maintained:
    `expires_at_pinned` (computed from the snapshot; authoritative — it alone
    drives the `EXPIRED` transition) and `expires_at_rolling` (recomputed on
    read from the live policy's current `retention_days`, for audit
    comparison)."

    Design: Difficulty/dual_variant_calc/retention_pinned_vs_rolling_expiry
    """
    prop = create_property(name="Retention Site", sale_share_designation="SELLS_AND_SHARES")
    pol = create_active_policy(
        prop["id"], jurisdiction_code="EU-GDPR", banner_regime="OPT_IN_REQUIRED",
        min_consent_age=16, retention_days=30, gpc_honored=True,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    vis = create_adult_visitor(
        prop["id"], birthdate="2000-01-01T00:00:00Z",
        external_ref="rv1@x.com", jurisdiction_code="EU-GDPR",
    )
    get_success_data(api.set_clock({"to_iso8601": "2026-05-10T00:00:00Z"}, ADMIN))
    rec = get_success_data(
        api.create_consent_record(
            vis["id"], create_consent_record_payload("ANALYTICS"),
            make_visitor_headers(vis["id"]),
        )
    )
    get_success_data(api.update_jurisdiction_policy(pol["id"], {"retention_days": 10}, ADMIN))
    # Clock past the rolling horizon (2026-05-20) but before the pinned (2026-06-09).
    get_success_data(api.set_clock({"to_iso8601": "2026-05-21T00:00:00Z"}, ADMIN))

    after = get_success_data(api.get_consent_record(rec["id"], ANY))
    assert after["status"] == "GRANTED", (
        "rolling horizon passed but pinned is authoritative"
    )


def test_retention_expiry_alive_one_second_before(api):
    """PRD section 3.5: "the retention rule of §2.10 moves any record — granted
    or withdrawn — to terminal `EXPIRED` once the logical clock reaches
    `expires_at_pinned`; the expiry instant itself counts (a record is alive one
    second before its horizon and `EXPIRED` exactly at it)".

    Design: Difficulty/boundary_precision_check/retention_expiry_exact_instant
    """
    prop = create_property(name="Expiry Site", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(prop["id"], **GDPR)
    vis = create_adult_visitor(
        prop["id"], birthdate="1990-01-01T00:00:00Z",
        external_ref="exp@x.com", jurisdiction_code="EU-GDPR",
    )
    get_success_data(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    rec = get_success_data(
        api.create_consent_record(
            vis["id"], create_consent_record_payload("ANALYTICS"),
            make_visitor_headers(vis["id"]),
        )
    )
    get_success_data(api.set_clock({"to_iso8601": "2026-05-30T23:59:59Z"}, ADMIN))
    before = get_success_data(api.get_consent_record(rec["id"], ANY))
    assert before["expires_at_pinned"] == "2026-05-31T00:00:00.000Z"
    assert before["status"] == "GRANTED", "one second before the pinned horizon"


def test_retention_expiry_fires_at_exact_instant(api):
    """PRD section 3.5: "the expiry instant itself counts (a record is alive one
    second before its horizon and `EXPIRED` exactly at it), and expiry flips
    `source_of_decision` to `EXPIRY`."

    Design: Difficulty/boundary_precision_check/retention_expiry_exact_instant
    """
    prop = create_property(name="Expiry Site", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(prop["id"], **GDPR)
    vis = create_adult_visitor(
        prop["id"], birthdate="1990-01-01T00:00:00Z",
        external_ref="exp@x.com", jurisdiction_code="EU-GDPR",
    )
    get_success_data(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    rec = get_success_data(
        api.create_consent_record(
            vis["id"], create_consent_record_payload("ANALYTICS"),
            make_visitor_headers(vis["id"]),
        )
    )
    get_success_data(api.set_clock({"to_iso8601": "2026-05-31T00:00:00Z"}, ADMIN))
    at = get_success_data(api.get_consent_record(rec["id"], ANY))
    assert at["status"] == "EXPIRED", "EXPIRED at exactly the expiry instant (>= semantics)"
    assert at["source_of_decision"] == "EXPIRY"


def test_grant_withdraw_regrant_counter_conservation(api):
    """PRD section 3.5: "The property's `granted_purpose_count` is a living
    ledger: it always equals the number of consent records in `GRANTED` status
    across all of the property's visitors. Grants and re-grants increment it;
    withdrawals and expiries decrement it; a grant-then-withdraw pair nets to
    zero".

    Design: Difficulty/compensating_invariant/grant_withdraw_regrant_counter_conservation
    """
    prop = create_property(name="Invariant Site", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(prop["id"], **GDPR)
    vis = create_adult_visitor(
        prop["id"], birthdate="1985-09-09T00:00:00Z",
        external_ref="inv@x.com", jurisdiction_code="EU-GDPR",
    )
    vh = make_visitor_headers(vis["id"])
    r1 = get_success_data(api.create_consent_record(vis["id"], create_consent_record_payload("ANALYTICS"), vh))
    r2 = get_success_data(api.create_consent_record(vis["id"], create_consent_record_payload("ADVERTISING"), vh))

    get_success_data(api.withdraw_consent_record(r1["id"], vh))
    get_success_data(api.regrant_consent_record(r1["id"], vh))
    get_success_data(api.withdraw_consent_record(r1["id"], vh))
    get_success_data(api.withdraw_consent_record(r2["id"], vh))

    prop_after = get_success_data(api.get_property(prop["id"], ANY))
    assert prop_after["granted_purpose_count"] == 0, (
        "two grants and two compensating withdraws net to zero"
    )
    rec1_after = get_success_data(api.get_consent_record(r1["id"], ANY))
    rec2_after = get_success_data(api.get_consent_record(r2["id"], ANY))
    assert rec1_after["status"] == "WITHDRAWN"
    assert rec2_after["status"] == "WITHDRAWN"


def test_counter_matches_filtered_recount(api):
    """PRD section 3.5: "An auditor can always reconcile the stored counter
    against a filtered listing of the property's consent records."

    Design: Difficulty/compensating_invariant/grant_withdraw_regrant_counter_conservation
    """
    prop = create_property(name="Invariant Site", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(prop["id"], **GDPR)
    vis = create_adult_visitor(
        prop["id"], birthdate="1985-09-09T00:00:00Z",
        external_ref="inv@x.com", jurisdiction_code="EU-GDPR",
    )
    vh = make_visitor_headers(vis["id"])
    r1 = get_success_data(api.create_consent_record(vis["id"], create_consent_record_payload("ANALYTICS"), vh))
    r2 = get_success_data(api.create_consent_record(vis["id"], create_consent_record_payload("ADVERTISING"), vh))
    get_success_data(api.withdraw_consent_record(r1["id"], vh))

    prop_after = get_success_data(api.get_property(prop["id"], ANY))
    granted_list, meta = validate_paginated(
        api.list_visitor_consent_records(vis["id"], ANY, params={"status": "GRANTED"})
    )
    assert meta["total_count"] == 1
    assert prop_after["granted_purpose_count"] == meta["total_count"], (
        "stored counter equals the independent filtered recount of GRANTED records"
    )
    assert granted_list[0]["id"] == r2["id"]
