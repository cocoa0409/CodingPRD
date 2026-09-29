"""The three body-less advertising actions, and the one envelope every failure comes back in."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.assertions import assert_advertised_item, assert_error_envelope_shape
from test_helpers.test_users import make_chain_admin_headers, make_merchandising_lead_headers

COOL_STATEMENT = "Atlantic Cod | WILD CAUGHT | Wild caught in US (WILD_LONGLINE) | FRESH - NEVER FROZEN"


def _labelled_lot_ready_to_advertise(api) -> dict:
    """A cod lot in slot 1 whose case label is PUBLISHED, so advertisements may go live."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    label = fixtures.publish_case_label(api, counter_id, lot["id"])
    env.update({"lot": lot, "label": label})
    return env


def test_01_publishing_makes_the_window_live_and_closing_retires_it_at_its_end(api):
    """PRD §3.6: "Closing retires a live window normally, moving `status` from `PUBLISHED` to
    `CLOSED`, and is legal only once the logical clock has reached or passed the advertisement's
    `ad_end_at`."

    Design: Corner/endpoints/ad_lifecycle_action_endpoints_publish_close_and_retract
    """
    env = _labelled_lot_ready_to_advertise(api)
    counter_id = env["counter"]["id"]
    item = fixtures.approved_ad_item(
        api,
        counter_id,
        env["lot"]["id"],
        headline="Fresh Atlantic Cod at the Counter",
        ad_start_at="2026-08-01T09:00:00Z",
        ad_end_at="2026-08-01T10:00:00Z",
    )
    assert item["status"] == "APPROVED"

    published = fixtures.publish_ad_item(api, item["id"])
    assert_advertised_item(published)
    assert published["status"] == "PUBLISHED"
    assert published["cool_statement"] == COOL_STATEMENT

    fixtures.set_clock(api, "2026-08-01T11:00:00Z")
    closed = validate_success(
        api.close_ad_item(item["id"], {}, make_merchandising_lead_headers()), expected_status=200
    )

    assert closed["status"] == "CLOSED"
    assert closed["retract_reason"] is None
    assert fixtures.read_case_label(api, counter_id, env["label"]["id"])["status"] == "PUBLISHED"
    assert fixtures.read_counter(api, counter_id)["violation_points"] == 0


def test_02_retracting_pulls_a_live_window_early_and_records_manual(api):
    """PRD §3.6: "Retracting pulls a live window early, moving `status` from `PUBLISHED` to
    `RETRACTED`; the request carries a `reason`, and for an operator-initiated retraction —
    available to both the `MerchandisingLead` and a `ComplianceOfficer` — the recorded
    `retract_reason` is `MANUAL`."

    Design: Corner/endpoints/ad_lifecycle_action_endpoints_publish_close_and_retract
    """
    env = _labelled_lot_ready_to_advertise(api)
    counter_id = env["counter"]["id"]
    item = fixtures.published_ad_item(
        api,
        counter_id,
        env["lot"]["id"],
        headline="Cod Special Continues",
        ad_start_at="2026-08-01T12:00:00Z",
        ad_end_at="2026-08-01T16:00:00Z",
    )
    assert item["status"] == "PUBLISHED"

    response = api.retract_ad_item(
        item["id"], {"reason": "MANUAL"}, make_merchandising_lead_headers()
    )
    retracted = validate_success(response, expected_status=200)

    assert retracted["status"] == "RETRACTED"
    assert retracted["retract_reason"] == "MANUAL"
    assert fixtures.read_case_label(api, counter_id, env["label"]["id"])["status"] == "PUBLISHED"
    assert fixtures.read_counter(api, counter_id)["violation_points"] == 0


def test_03_referential_authorization_and_shape_failures_share_one_envelope(api):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/errors/error_envelope_shape_is_identical_on_every_failure
    """
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    receipt = factories.lot_payload(
        counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )

    missing = api.get_lot(NON_EXISTENT_UUID, make_chain_admin_headers())
    validate_error(missing, ApiErrorId.ERR_LOT_NOT_FOUND.value, expected_status=404)

    wrong_role = api.create_lot(receipt, make_merchandising_lead_headers())
    validate_error(wrong_role, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    wrong_shape = api.create_counter(
        factories.counter_payload(case_slot_count="six"), make_chain_admin_headers()
    )
    validate_error(wrong_shape, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    for response in (missing, wrong_role, wrong_shape):
        body = response.json()
        assert_error_envelope_shape(body)
        assert body["data"]["message"].strip() != ""
