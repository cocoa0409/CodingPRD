"""Corner tests — cross_cutting_complexity, consistency_model, and the
remaining errors-section instances.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    create_accepted_assessment,
    create_and_activate_event,
    create_confirm_outage_payload,
    create_crew,
    create_etr_revision_payload,
    create_feeder_record,
    create_fema_claim,
    create_fema_claim_payload,
    create_outage_payload,
    create_priority_customer_payload,
    create_ready_work_order,
    create_submitted_assessment,
    create_work_order_payload,
    get_success_data,
    make_claims_officer_headers,
    make_field_crew_lead_headers,
    set_clock,
    setup_event_with_feeder,
    setup_outage_with_accepted_assessment,
    validate_error,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CO1 = TEST_USERS["claims_officer_headers"]


def test_occ_stale_version_on_etr_revision(api):
    """PRD §2.8: "If the value does not equal the outage's current `version`
    — because another writer has advanced the outage since the client last
    read it — the request is rejected with `ERR_STALE_OUTAGE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity/occ_stale_version_on_etr_revision
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    confirmed = get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(
                customers_affected=100, cause_code="TREE"
            ),
            DISP,
        )
    )
    set_clock("2026-08-10T01:00:00Z")
    # First revision with the observed version succeeds (v 2 -> 3).
    rev1 = get_success_data(
        api.publish_etr_revision(
            ot["id"],
            create_etr_revision_payload(
                published_etr="2026-08-10T09:00:00Z",
                revision_reason="WEATHER_DELAY",
                expected_outage_version=confirmed["version"],
            ),
            DISP,
        )
    )
    assert rev1["revision_seq"] == 2
    # Second revision carrying the now-stale version is rejected.
    resp = api.publish_etr_revision(
        ot["id"],
        create_etr_revision_payload(
            published_etr="2026-08-10T10:00:00Z",
            revision_reason="CREW_DELAYED",
            expected_outage_version=confirmed["version"],
        ),
        DISP,
    )
    err = validate_error(resp, ApiErrorId.ERR_STALE_OUTAGE_VERSION)
    assert err["error_id"] == "ERR_STALE_OUTAGE_VERSION"
    outage = get_success_data(api.get_outage(ot["id"], DISP))
    assert_instant_equals(outage["current_etr"], "2026-08-10T09:00:00Z")


def test_occ_stale_version_on_assessment_accept(api):
    """PRD §2.8: "If the value does not equal the outage's current `version`
    — because another writer has advanced the outage since the client last
    read it — the request is rejected with `ERR_STALE_OUTAGE_VERSION` (HTTP
    412)." Applied to `POST /om/damage-assessments/{id}/accept`.

    Design: Corner/cross_cutting_complexity/occ_stale_version_on_assessment_accept
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    confirmed = get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(customers_affected=5, cause_code="EQUIPMENT"),
            DISP,
        )
    )
    cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
    da = create_submitted_assessment(
        ot["id"], cr_a["id"], damage_class="MINOR", estimated_repair_minutes=10
    )
    # Stale (one behind) is rejected.
    resp = api.accept_damage_assessment(
        da["id"],
        {"expected_outage_version": confirmed["version"] - 1},
        DISP,
    )
    err = validate_error(resp, ApiErrorId.ERR_STALE_OUTAGE_VERSION)
    assert err["error_id"] == "ERR_STALE_OUTAGE_VERSION"
    # The exact current version succeeds — the check is value-exact.
    accepted = get_success_data(
        api.accept_damage_assessment(
            da["id"], {"expected_outage_version": confirmed["version"]}, DISP
        )
    )
    assert accepted["assessment_status"] == "ACCEPTED"


def test_clock_sweep_recomputes_outage_priority_score(api):
    """PRD §2.4: "Advancing the clock performs a certification sweep: every
    priority customer whose `certification_status` is `CERTIFIED` and whose
    `certified_through` lies strictly before the new logical now transitions
    to `SUSPENDED`, and the sweep recomputes the affected feeder's
    `certified_priority_count` as well as `has_priority_customers` and
    `priority_score` on every non-terminal outage served by that feeder."

    Design: Corner/cross_cutting_complexity/clock_sweep_recomputes_outage_priority_score
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    pc = get_success_data(
        api.create_priority_customer(create_priority_customer_payload(fd["id"]), DISP)
    )
    get_success_data(
        api.certify_priority_customer(
            pc["id"], {"certified_through": "2026-08-12T00:00:00Z"}, DISP
        )
    )
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(
                customers_affected=10, cause_code="EQUIPMENT"
            ),
            DISP,
        )
    )
    # Read at 00:05Z: 5 minutes elapsed -> floor(5min / 1h) = 0 age points.
    set_clock("2026-08-10T00:05:00Z")
    pre = get_success_data(api.get_outage(ot["id"], DISP))
    # 10000 LIFE_SUPPORT + 0 + 10 customers + 0 age + 0 missed.
    assert pre["priority_score"] == 10010

    # Sweep past certified_through; the outage also missed its ETR.
    set_clock("2026-08-12T00:00:01Z")
    post = get_success_data(api.get_outage(ot["id"], DISP))
    assert post["etr_missed"] is True
    # 0 + 0 + 10 + 48h*50 = 2400 + 2000 missed = 4410.
    assert post["priority_score"] == 4410


def test_immediate_read_after_write_consistency(api):
    """PRD §2.6: "State changes propagate across entity boundaries as a
    single atomic unit of work: every side effect of an operation commits
    within the triggering request".

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
    cr_l = create_crew(crew_type="LINE")
    wo = create_ready_work_order(ot["id"])
    assigned = get_success_data(
        api.assign_work_order(wo["id"], {"crew_id": cr_l["id"]}, DISP)
    )
    # The assign response itself carries the new state.
    assert assigned["execution_status"] == "DISPATCHED"
    assert assigned["assigned_crew_id"] == cr_l["id"]
    # A directly-following read of the related crew shows the cascade.
    crew = get_success_data(api.get_crew(cr_l["id"], DISP))
    assert crew["crew_status"] == "EN_ROUTE"


def test_fema_submit_before_demobilization_returns_error(api):
    """PRD §3.9: "Submission moves `DRAFT` to `SUBMITTED` and is gated by
    posture and money: the event must be in `DEMOBILIZING` or `CLOSED`
    (`ERR_EVENT_NOT_DEMOBILIZING`)".

    Design: Corner/errors/fema_submit_before_demobilization_returns_error
    """
    set_clock("2026-08-10T00:00:00Z")
    ev = create_and_activate_event(event_name="Storm X15", event_type="HURRICANE")
    claim = create_fema_claim(ev["id"], county_code="C1", threshold_cents=0)
    resp = api.submit_fema_claim(claim["id"], CO1)
    err = validate_error(resp, ApiErrorId.ERR_EVENT_NOT_DEMOBILIZING)
    assert err["error_id"] == "ERR_EVENT_NOT_DEMOBILIZING"
    read = get_success_data(api.get_fema_claim(claim["id"], CO1))
    assert read["claim_status"] == "DRAFT"
    assert read["eligible_snapshot_cents"] is None


def test_mutation_after_event_close_rejected(api):
    """PRD §3.9: "Once an event is `CLOSED`, every mutation scoped to that
    event is rejected with `ERR_EVENT_CLOSED`."

    Design: Corner/errors/mutation_after_event_close_rejected
    """
    set_clock("2026-08-10T00:00:00Z")
    ev = create_and_activate_event(event_name="Storm X16", event_type="HURRICANE")
    get_success_data(api.begin_demobilization(ev["id"], ED))
    get_success_data(api.close_storm_event(ev["id"], ED))
    fd = create_feeder_record(county_code="C1", customer_count=1000)
    resp = api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
    err = validate_error(resp, ApiErrorId.ERR_EVENT_CLOSED)
    assert err["error_id"] == "ERR_EVENT_CLOSED"


def test_start_without_on_site_crew_rejected(api):
    """PRD §3.5: "Starting requires the assigned internal crew to be
    `ON_SITE` (`ERR_CREW_NOT_ON_SITE`); mutual-aid assignments skip the
    on-site check."

    Design: Corner/errors/start_without_on_site_crew_rejected
    """
    _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
    cr_l = create_crew(crew_type="LINE")
    wo = create_ready_work_order(ot["id"])
    get_success_data(api.assign_work_order(wo["id"], {"crew_id": cr_l["id"]}, DISP))
    # Crew is EN_ROUTE (arrive never called).
    resp = api.start_work_order(wo["id"], make_field_crew_lead_headers(cr_l["id"]))
    err = validate_error(resp, ApiErrorId.ERR_CREW_NOT_ON_SITE)
    assert err["error_id"] == "ERR_CREW_NOT_ON_SITE"
    read = get_success_data(api.get_work_order(wo["id"], DISP))
    assert read["execution_status"] == "DISPATCHED"


def test_ready_without_accepted_assessment_rejected(api):
    """PRD §3.5: "for any `work_type` other than `ASSESSMENT`, at least one
    damage assessment on the linked outage must be `ACCEPTED` — readiness
    without field truth is rejected with `ERR_ASSESSMENT_REQUIRED`."

    Design: Corner/errors/ready_without_accepted_assessment_rejected
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(customers_affected=5, cause_code="EQUIPMENT"),
            DISP,
        )
    )
    wo_fix = get_success_data(
        api.create_work_order(
            create_work_order_payload(
                ot["id"], work_type="REPAIR", required_crew_type="LINE"
            ),
            DISP,
        )
    )
    wo_check = get_success_data(
        api.create_work_order(
            create_work_order_payload(
                ot["id"], work_type="ASSESSMENT", required_crew_type="DAMAGE_ASSESSOR"
            ),
            DISP,
        )
    )
    resp = api.ready_work_order(wo_fix["id"], DISP)
    err = validate_error(resp, ApiErrorId.ERR_ASSESSMENT_REQUIRED)
    assert err["error_id"] == "ERR_ASSESSMENT_REQUIRED"
    # ASSESSMENT work orders are exempt from the rule.
    ready = get_success_data(api.ready_work_order(wo_check["id"], DISP))
    assert ready["execution_status"] == "READY"
