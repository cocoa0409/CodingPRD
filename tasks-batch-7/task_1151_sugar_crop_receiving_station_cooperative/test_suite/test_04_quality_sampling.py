"""Quality sampling: sample type constraints, the SAMPLED cascade, segregation
of duties on verify, result invalidation, and lab role exclusivity."""
import pytest

from test_helpers import (
    ApiErrorId,
    QT_ALICE,
    QT_BOB,
    SLOT_AM_END,
    SLOT_AM_START,
    WEIGH_CLOCK_AM,
    add_recorded_sample,
    collect_sample,
    create_confirmed_booking,
    create_weighed_ticket,
    make_quality_tech_headers,
    record_sample,
    setup_world,
    validate_error,
    validate_success,
)


def _weighed_world(api):
    world = setup_world(with_pile=False)
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 20)
    ticket = create_weighed_ticket(booking["id"], 60000, 32000, WEIGH_CLOCK_AM)
    world["booking"] = booking
    world["ticket"] = ticket
    return world


def test_sample_create_invalid_enum_returns_invalid_request(api, quality_tech_headers):
    """PRD §3.4: "A `QUALITY_TECH` collects a **quality sample** against a ticket
    by supplying `ticket_id` and a `sample_type` of either `STATION_QUICK` (the
    station's rapid assay) or `LAB_VERIFY` (the laboratory verification that
    governs final payment)."
    PRD §2.7: "State-machine and request-shape checks run fifth
    (`ERR_INVALID_STATE`, `ERR_INVALID_REQUEST`, `ERR_TICKET_NOT_CREDITABLE`,
    `ERR_BOOKING_NOT_CONFIRMED`, `ERR_CAMPAIGN_NOT_OPEN`,
    `ERR_POOL_NOT_ACCRUING`, `ERR_PILE_NOT_FILLING`, `ERR_LAB_SAMPLE_REQUIRED`)".

    Design: Corner/entities/sample_create_invalid_enum_returns_invalid_request
    """
    world = _weighed_world(api)
    res = api.create_sample(
        {"ticket_id": world["ticket"]["id"], "sample_type": "HPLC"},
        quality_tech_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_sample_verify_of_quick_sample_returns_invalid_state(api):
    """PRD §3.4: "Only a `LAB_VERIFY` sample may be verified — attempting to
    verify a `STATION_QUICK` sample is rejected with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/sample_verify_of_quick_sample_returns_invalid_state
    """
    world = _weighed_world(api)
    sample = add_recorded_sample(world["ticket"]["id"], "STATION_QUICK",
                                 16.50, 4.00, recorder=QT_ALICE)
    res = api.verify_sample(sample["id"], make_quality_tech_headers(QT_BOB))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_sod_same_user_cannot_verify_own_recorded_sample(api):
    """PRD §2.1: "when a `QUALITY_TECH` attempts to verify a recorded sample, the
    verifier's `X-User-ID` must differ from the `recorded_by_user_id` captured
    when the result was recorded; a match is rejected with `ERR_SOD_VIOLATION`
    (403)."
    PRD §3.4: "A successful verify moves the sample from `RESULT_RECORDED` to its
    terminal `VERIFIED` state and increments its `version`."

    Design: Corner/rbac/sod_same_user_cannot_verify_own_recorded_sample
    """
    world = _weighed_world(api)
    sample = add_recorded_sample(world["ticket"]["id"], "LAB_VERIFY",
                                 16.10, 4.40, recorder=QT_ALICE)
    assert sample["recorded_by_user_id"] == QT_ALICE
    res = api.verify_sample(sample["id"], make_quality_tech_headers(QT_ALICE))
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION.value)
    verified = validate_success(
        api.verify_sample(sample["id"], make_quality_tech_headers(QT_BOB)), 200)
    assert verified["status"] == "VERIFIED"


def test_scheduler_cannot_record_sample(api, scheduler_headers):
    """PRD §2.1: "A request whose role is syntactically valid but not on the
    endpoint's authorized-role list is rejected with `ERR_FORBIDDEN` (403)."
    PRD §4: POST /api/samples/{sample_id}/record-result is authorized for
    QUALITY_TECH only.

    Design: Corner/rbac/scheduler_cannot_record_sample
    """
    world = _weighed_world(api)
    sample = collect_sample(world["ticket"]["id"], "STATION_QUICK")
    res = api.record_sample_result(sample["id"], {"sugar_pct": 16.50, "trash_pct": 4.00},
                                   scheduler_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_ticket_auto_sampled_on_first_result(api, pool_accountant_headers):
    """PRD §3.4: "If the ticket was `WEIGHED` at that moment, this first recorded
    sample triggers a cascade: the ticket moves to `SAMPLED`, its
    `provisional_trash_pct` and `provisional_sugar_pct` are copied from that
    triggering sample, and the system computes its `provisional_factor`,
    `provisional_adjusted_net_tons`, and `provisional_value_cents` per the
    calculation rules in §3.5."

    Design: Corner/state_machines/ticket_auto_sampled_on_first_result
    """
    world = _weighed_world(api)
    sample = collect_sample(world["ticket"]["id"], "STATION_QUICK")
    record_sample(sample["id"], 16.50, 4.00, recorder=QT_ALICE)
    ticket = validate_success(api.get_ticket(world["ticket"]["id"],
                                             pool_accountant_headers), 200)
    assert ticket["status"] == "SAMPLED"
    # net 28000 lbs = 14.0 t; trash 4.00 -> deducted 1.00%; 14.0 x 0.99 = 13.8600
    assert ticket["provisional_adjusted_net_tons"] == pytest.approx(13.86, abs=1e-9)
    # factor = 1.00 + (16.50 - 16.00) x 0.04 = 1.0200
    assert ticket["provisional_factor"] == pytest.approx(1.02, abs=1e-9)
    assert ticket["provisional_trash_pct"] == pytest.approx(4.00, abs=1e-9)
    assert ticket["provisional_sugar_pct"] == pytest.approx(16.50, abs=1e-9)


def test_sample_invalidate_reverts_ticket_to_weighed(api, pool_accountant_headers):
    """PRD §3.4: "Invalidating a sample returns it from `RESULT_RECORDED` to
    `COLLECTED` and clears `sugar_pct`, `trash_pct`, and `recorded_by_user_id` to
    null. If the invalidated sample was the one that triggered its ticket's
    `SAMPLED` transition and no other sample of that ticket remains in
    `RESULT_RECORDED` or `VERIFIED`, the ticket reverts from `SAMPLED` to
    `WEIGHED` and all of its `provisional_*` fields are cleared to null".

    Design: Corner/state_machines/sample_invalidate_reverts_ticket_to_weighed
    """
    world = _weighed_world(api)
    sample = add_recorded_sample(world["ticket"]["id"], "STATION_QUICK",
                                 16.50, 4.00, recorder=QT_ALICE)
    invalidated = validate_success(api.invalidate_sample(
        sample["id"], make_quality_tech_headers(QT_ALICE)), 200)
    assert invalidated["status"] == "COLLECTED"
    assert invalidated["sugar_pct"] is None
    assert invalidated["trash_pct"] is None
    assert invalidated["recorded_by_user_id"] is None
    ticket = validate_success(api.get_ticket(world["ticket"]["id"],
                                             pool_accountant_headers), 200)
    assert ticket["status"] == "WEIGHED"
    assert ticket["provisional_factor"] is None
    assert ticket["provisional_adjusted_net_tons"] is None
    assert ticket["provisional_value_cents"] is None
