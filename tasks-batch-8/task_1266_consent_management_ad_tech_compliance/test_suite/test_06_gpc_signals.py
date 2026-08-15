"""Global Privacy Control signal events and the honoring cascade."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_gpc_signal_event,
    create_property, create_active_policy, create_adult_visitor,
    create_visitor_payload, gpc_signal_payload, create_consent_record_payload,
    make_visitor_headers,
    TEST_USERS, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
ANY = TEST_USERS["any_headers"]


def test_gpc_signal_event_immutable_no_version(api):
    """PRD section 2.5: "a `GpcSignalEvent` is an append-only record carrying
    only `id`, `created_at`, `visitor_id`, and `signal`; it has neither
    `updated_at` nor `version`, and no endpoint modifies or deletes it."

    Design: Corner/entities/gpc_signal_event_immutable_no_version
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    vis = get_success_data(
        api.create_visitor(
            create_visitor_payload(prop["id"], external_ref="e@x.com", jurisdiction_code="US-CA"),
            ANON,
        )
    )
    ev = validate_success(
        api.create_gpc_signal(vis["id"], gpc_signal_payload("ON"), make_visitor_headers(vis["id"])),
        201,
    )
    assert_gpc_signal_event(ev)
    assert ev["visitor_id"] == vis["id"]
    events, _meta = validate_paginated(api.list_gpc_signals(vis["id"], ANY))
    assert events[0]["signal"] == "ON"
    assert "version" not in events[0] and "updated_at" not in events[0]


def _setup_gpc_site(api):
    prop = create_property(name="GPC Site", sale_share_designation="SELLS_AND_SHARES")
    create_active_policy(
        prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_OUT_ALLOWED",
        min_consent_age=16, retention_days=30, gpc_honored=True,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    vis = create_adult_visitor(
        prop["id"], birthdate="1988-07-07T00:00:00Z",
        external_ref="g@x.com", jurisdiction_code="US-CA",
    )
    return prop, vis


def test_gpc_on_cascades_sale_share_withdrawals(api):
    """PRD section 3.4: "the flag flip itself drives every `GRANTED` consent
    record the visitor holds for `SALE_SHARE` into `WITHDRAWN` with
    `source_of_decision` `AUTO_GPC_WITHDRAW` (records for other purposes are
    untouched)".

    Design: Difficulty/transitive_cascade/gpc_signal_cascade_depth3
    """
    prop, vis = _setup_gpc_site(api)
    vh = make_visitor_headers(vis["id"])
    rec_sale = get_success_data(api.create_consent_record(vis["id"], create_consent_record_payload("SALE_SHARE"), vh))
    rec_adv = get_success_data(api.create_consent_record(vis["id"], create_consent_record_payload("ADVERTISING"), vh))

    validate_success(api.create_gpc_signal(vis["id"], gpc_signal_payload("ON"), vh), 201)

    visitor_after = get_success_data(api.get_visitor(vis["id"], ANY))
    assert visitor_after["sale_share_opted_out"] is True
    assert visitor_after["gpc_effective"] == "ON"

    sale_after = get_success_data(api.get_consent_record(rec_sale["id"], ANY))
    assert sale_after["status"] == "WITHDRAWN"
    assert sale_after["source_of_decision"] == "AUTO_GPC_WITHDRAW"

    adv_after = get_success_data(api.get_consent_record(rec_adv["id"], ANY))
    assert adv_after["status"] == "GRANTED", "cascade is scoped to SALE_SHARE only"


def test_gpc_cascade_syncs_granted_purpose_count(api):
    """PRD section 3.4: "each such withdrawal decrements the property's
    `granted_purpose_count` and refreshes its `version`."
    PRD section 3.5: "The property's `granted_purpose_count` is a living ledger:
    it always equals the number of consent records in `GRANTED` status across
    all of the property's visitors."

    Design: Difficulty/transitive_cascade/gpc_signal_cascade_depth3
    """
    prop, vis = _setup_gpc_site(api)
    vh = make_visitor_headers(vis["id"])
    get_success_data(api.create_consent_record(vis["id"], create_consent_record_payload("SALE_SHARE"), vh))
    get_success_data(api.create_consent_record(vis["id"], create_consent_record_payload("ADVERTISING"), vh))
    before = get_success_data(api.get_property(prop["id"], ANY))
    assert before["granted_purpose_count"] == 2

    validate_success(api.create_gpc_signal(vis["id"], gpc_signal_payload("ON"), vh), 201)

    after = get_success_data(api.get_property(prop["id"], ANY))
    assert after["granted_purpose_count"] == 1, "2 grants - 1 cascaded withdrawal"
    assert after["version"] > before["version"], "each cascaded withdrawal refreshes version"


def test_gpc_off_does_not_regrant(api):
    """PRD section 3.4: "Setting the signal `OFF` clears `sale_share_opted_out`
    but never resurrects cascaded withdrawals — a withdrawn record stays
    `WITHDRAWN` until the visitor deliberately re-grants it."
    PRD section 3.5: "Fourth, an existing `GRANTED` record yields
    `EXPLICIT_GRANT` and a `WITHDRAWN` one `EXPLICIT_WITHDRAWN`; an `EXPIRED`
    record is treated as absent."

    Design: Corner/cross_cutting_layers/gpc_off_does_not_regrant
    """
    prop, vis = _setup_gpc_site(api)
    vh = make_visitor_headers(vis["id"])
    rec = get_success_data(api.create_consent_record(vis["id"], create_consent_record_payload("SALE_SHARE"), vh))
    get_success_data(api.set_clock({"to_iso8601": "2026-05-10T00:00:00Z"}, ADMIN))
    validate_success(api.create_gpc_signal(vis["id"], gpc_signal_payload("ON"), vh), 201)

    validate_success(api.create_gpc_signal(vis["id"], gpc_signal_payload("OFF"), vh), 201)

    visitor_after = get_success_data(api.get_visitor(vis["id"], ANY))
    assert visitor_after["gpc_effective"] == "OFF"
    assert visitor_after["sale_share_opted_out"] is False

    rec_after = get_success_data(api.get_consent_record(rec["id"], ANY))
    assert rec_after["status"] == "WITHDRAWN", "no automatic re-grant on GPC OFF"

    preview = get_success_data(
        api.get_consent_preview(vis["id"], ANY, params={"purpose_category": "SALE_SHARE"})
    )
    assert preview["decision"] == "EXPLICIT_WITHDRAWN", (
        "latest record governs once GPC is OFF"
    )
