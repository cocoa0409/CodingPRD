"""Recall notice publication, the hazard-class branch and per-unit disposition."""

from test_helpers import (
    ApiErrorId,
    assert_recall_match,
    assert_recall_notice,
    disposition_recall_match,
    first_recall_match_id,
    publish_recall_notice,
    read_device,
    read_facility,
    read_loaner_assignment,
    read_recall_match,
    read_recall_notice,
    read_work_order,
    setup_class_i_cascade_scene,
    setup_lot_scoped_recall,
    setup_published_class_ii_recall,
    setup_published_class_iii_recall_with_pending_match,
    setup_two_model_recall_branches,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_publishing_a_notice_twice_is_rejected(api, ce_manager_headers):
    """PRD §3.7: "Publishing runs the inventory scan and is accepted only from `DRAFT`; a
    notice already past that point reports `ERR_INVALID_RECALL_STATE`."
    PRD §3.7: "The notice's `matched_device_count` and `pending_match_count` are both set to
    the number of matches, and `published_at` is stamped from the logical clock."

    Design: Corner/state_machines/recall_publish_twice_returns_invalid_recall_state
    """
    scene = setup_published_class_ii_recall()
    notice_id = scene["notice"]["id"]
    assert scene["notice"]["status"] == "MONITORING"

    response = api.publish_recall_notice(notice_id, ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_RECALL_STATE.value, 409)

    after = read_recall_notice(notice_id)
    assert after["status"] == "MONITORING"
    assert after["matched_device_count"] == 1, "A rejected republish must not rescan inventory"

    matches, meta = validate_paginated(
        api.list_recall_matches(ce_manager_headers, params={"recall_notice_id": notice_id})
    )
    assert len(matches) == 1
    assert meta["total_count"] == 1


def test_close_is_refused_while_a_match_is_still_pending(api, ce_manager_headers):
    """PRD §3.7: "A `CEManager` closes it from either `MANDATORY_REMOVAL` or `MONITORING`, and
    the close is refused with `ERR_RECALL_MATCHES_PENDING` while `pending_match_count` is
    greater than zero."
    PRD §3.7: "A `REMEDIATED` or `EXEMPTED` disposition instead clears the unit's `recall_hold`
    — but only when this was its last `PENDING` match, since a unit may be matched by more
    than one notice — and then returns it from `DOWN` to `IN_SERVICE` subject to the three
    conditional-restoration preconditions of §2.10."

    Design: Corner/state_machines/recall_close_with_pending_matches_returns_error
    """
    scene = setup_published_class_ii_recall()
    notice_id = scene["notice"]["id"]
    match_id = first_recall_match_id(notice_id)

    blocked = api.close_recall_notice(notice_id, ce_manager_headers)
    validate_error(blocked, ApiErrorId.ERR_RECALL_MATCHES_PENDING.value, 409)
    assert read_recall_notice(notice_id)["status"] == "MONITORING"

    disposition_recall_match(match_id, "EXEMPTED",
                             note="Serial outside affected build range")
    assert read_recall_match(match_id)["disposition"] == "EXEMPTED"
    assert read_recall_notice(notice_id)["pending_match_count"] == 0
    assert read_device(scene["device"]["id"])["recall_hold"] is False

    data = validate_success(api.close_recall_notice(notice_id, ce_manager_headers), 200)
    assert_recall_notice(data)
    assert data["status"] == "CLOSED"


def test_a_removed_disposition_retires_the_unit(api, biomed_tech_headers):
    """PRD §3.7: "A `REMOVED` disposition retires the unit: its `operational_state` becomes
    `RETIRED` from wherever it stood, and a retired unit is excluded from every future recall
    scan, from every loaner candidate set and from every replacement plan."
    PRD §3.7: "In every case `disposed_at` is stamped from the logical clock,
    `disposed_by_user_id` records the caller's opaque `X-User-ID`, and the notice's
    `pending_match_count` decreases by 1."

    Design: Corner/state_machines/recall_match_removed_retires_the_device
    """
    scene = setup_published_class_iii_recall_with_pending_match()

    data = validate_success(
        api.disposition_recall_match(scene["match_id"],
                                     {"disposition": "REMOVED",
                                      "note": "Removed from service and scrapped"},
                                     biomed_tech_headers),
        200,
    )
    assert_recall_match(data)
    assert data["disposition"] == "REMOVED"
    assert data["match_basis"] == "MODEL_ONLY"

    assert read_device(scene["device"]["id"])["operational_state"] == "RETIRED"
    notice = read_recall_notice(scene["notice"]["id"])
    assert notice["pending_match_count"] == 0
    assert notice["matched_device_count"] == 1


def test_a_second_disposition_on_the_same_match_is_rejected(api, ce_manager_headers):
    """PRD §3.7: "Only a match still at `PENDING` may be dispositioned; one that already
    carries a terminal disposition reports `ERR_INVALID_RECALL_MATCH_STATE`."

    Design: Corner/errors/second_disposition_returns_invalid_recall_match_state
    """
    scene = setup_published_class_ii_recall()
    match_id = first_recall_match_id(scene["notice"]["id"])
    disposition_recall_match(match_id, "EXEMPTED")

    response = api.disposition_recall_match(match_id, {"disposition": "REMOVED"},
                                            ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_RECALL_MATCH_STATE.value, 409)

    assert read_recall_match(match_id)["disposition"] == "EXEMPTED"
    assert read_device(scene["device"]["id"])["operational_state"] == "IN_SERVICE"
    assert read_recall_notice(scene["notice"]["id"])["pending_match_count"] == 0


def test_a_lot_scoped_notice_matches_only_the_named_lots(api, ce_manager_headers):
    """PRD §3.7: "When the array is non-empty, only candidates whose `lot_number` appears in it
    match, and each match records a `match_basis` of `MODEL_AND_LOT`."
    PRD §3.7: "Every matched device has `recall_hold` set to `true`, and that is all: no
    matched device's `operational_state` changes, no loaner assignment is cancelled, no PM task
    is deferred, `open_class_i_recall_count` is not changed, and `ce_posture` is not changed."

    Design: Corner/calculations/recall_lot_filter_matches_only_named_lots
    """
    scene = setup_lot_scoped_recall()

    data = validate_success(
        api.publish_recall_notice(scene["notice"]["id"], ce_manager_headers), 200
    )
    assert data["matched_device_count"] == 1

    matches, meta = validate_paginated(
        api.list_recall_matches(ce_manager_headers,
                                params={"recall_notice_id": scene["notice"]["id"]})
    )
    assert len(matches) == 1, f"Only the LOT-C1 unit may match, got {len(matches)}"
    assert meta["total_count"] == 1
    assert matches[0]["device_id"] == scene["device"]["id"]
    assert matches[0]["match_basis"] == "MODEL_AND_LOT"

    assert read_device(scene["device"]["id"])["recall_hold"] is True
    assert read_device(scene["miss_device"]["id"])["recall_hold"] is False


def test_class_i_publication_downs_the_unit_and_escalates_the_campus(api, ce_manager_headers):
    """PRD §3.7: "Every matched device has `recall_hold` set to `true`. Every matched device
    whose `operational_state` is `IN_SERVICE` or `ON_LOAN` is taken to `DOWN`, with its
    `version` incremented."
    PRD §3.7: "The campus `open_class_i_recall_count` increases by 1, and `ce_posture` moves
    `NORMAL` → `HEIGHTENED`."

    Design: Difficulty/non_linear_state_machine/recall_publish_branches_on_hazard_class_with_disjoint_side_effects
    """
    scene = setup_two_model_recall_branches()

    data = validate_success(
        api.publish_recall_notice(scene["class_i_notice"]["id"], ce_manager_headers), 200
    )
    assert data["status"] == "MANDATORY_REMOVAL"
    assert data["matched_device_count"] == 1
    assert data["pending_match_count"] == 1

    pump = read_device(scene["device"]["id"])
    assert pump["operational_state"] == "DOWN"
    assert pump["recall_hold"] is True

    facility = read_facility(scene["facility"]["id"])
    assert facility["open_class_i_recall_count"] == 1
    assert facility["ce_posture"] == "HEIGHTENED"


def test_class_iii_publication_only_sets_the_recall_hold(api, ce_manager_headers):
    """PRD §3.7: "A `CLASS_II` or `CLASS_III` notice takes the `PUBLISHED` → `MONITORING`
    branch instead, and its side-effect set is deliberately disjoint. Every matched device has
    `recall_hold` set to `true`, and that is all: no matched device's `operational_state`
    changes, no loaner assignment is cancelled, no PM task is deferred,
    `open_class_i_recall_count` is not changed, and `ce_posture` is not changed."

    Design: Difficulty/non_linear_state_machine/recall_publish_branches_on_hazard_class_with_disjoint_side_effects
    """
    scene = setup_two_model_recall_branches()
    publish_recall_notice(scene["class_i_notice"]["id"])

    data = validate_success(
        api.publish_recall_notice(scene["class_iii_notice"]["id"], ce_manager_headers), 200
    )
    assert data["status"] == "MONITORING"
    assert data["matched_device_count"] == 1

    monitor = read_device(scene["monitor_device"]["id"])
    assert monitor["operational_state"] == "IN_SERVICE", (
        "The MONITORING branch must not change availability"
    )
    assert monitor["recall_hold"] is True

    facility = read_facility(scene["facility"]["id"])
    assert facility["open_class_i_recall_count"] == 1, (
        "A CLASS_III publication must not touch the Class I counter"
    )


def test_class_i_publication_creates_one_match_per_unit_in_scan_order(api, ce_manager_headers):
    """PRD §3.7: "The scan considers every device at the notice's campus that is on the
    notice's exact model and whose `operational_state` is not `RETIRED`."
    PRD §3.7: "Matches can be read individually and listed with filters on `recall_notice_id`,
    `device_id` and `disposition`; that listing is the only discovery channel for the matches a
    publish creates."

    Design: Difficulty/non_linear_state_machine/recall_publish_branches_on_hazard_class_with_disjoint_side_effects
    """
    scene = setup_two_model_recall_branches()
    publish_recall_notice(scene["class_i_notice"]["id"])

    matches, meta = validate_paginated(
        api.list_recall_matches(ce_manager_headers,
                                params={"recall_notice_id": scene["class_i_notice"]["id"]})
    )
    assert len(matches) == 1, f"Only the pump-model unit may match, got {len(matches)}"
    assert meta["total_count"] == 1
    assert matches[0]["device_id"] == scene["device"]["id"]
    assert matches[0]["disposition"] == "PENDING"
    assert matches[0]["match_basis"] == "MODEL_ONLY"


def test_class_i_publish_matches_every_non_retired_unit_on_the_model(api, ce_manager_headers):
    """PRD §3.7: "When `affected_lot_numbers` is empty, **all** of those candidates match — an
    empty array means a whole-model recall, not a match-nothing recall — and each resulting
    match records a `match_basis` of `MODEL_ONLY`."
    PRD §3.7: "The notice's `matched_device_count` and `pending_match_count` are both set to
    the number of matches, and `published_at` is stamped from the logical clock."

    Design: Difficulty/transitive_cascade/class_i_recall_cascade_reaches_work_order_priority_four_hops
    """
    scene = setup_class_i_cascade_scene()

    data = validate_success(
        api.publish_recall_notice(scene["notice"]["id"], ce_manager_headers), 200
    )
    assert data["status"] == "MANDATORY_REMOVAL"
    assert data["matched_device_count"] == 2, (
        f"Both the downed unit and the pool unit are on the recalled model, "
        f"got {data['matched_device_count']}"
    )
    assert data["published_at"] is not None


def test_class_i_publish_downs_the_lent_out_pool_unit(api, ce_manager_headers):
    """PRD §3.7: "Every matched device has `recall_hold` set to `true`. Every matched device
    whose `operational_state` is `IN_SERVICE` or `ON_LOAN` is taken to `DOWN`, with its
    `version` incremented."

    Design: Difficulty/transitive_cascade/class_i_recall_cascade_reaches_work_order_priority_four_hops
    """
    scene = setup_class_i_cascade_scene()
    assert read_device(scene["pool_device"]["id"])["operational_state"] == "ON_LOAN"

    publish_recall_notice(scene["notice"]["id"])

    pool = read_device(scene["pool_device"]["id"])
    assert pool["operational_state"] == "DOWN"
    assert pool["recall_hold"] is True


def test_class_i_publish_cancels_the_loaner_without_billing_it(api, ce_manager_headers):
    """PRD §3.7: "Every `DEPLOYED` loaner assignment whose `loaner_device_id` is one of those
    newly downed units moves to `CANCELLED` with `billable_days` 0 and `rental_cost_cents` 0,
    and each such cancellation sets its own work order's `loaner_status` to `UNCOVERED` and
    escalates a still-open order to `P1` with `sla_hours` 4, exactly as described in §3.6."

    Design: Difficulty/transitive_cascade/class_i_recall_cascade_reaches_work_order_priority_four_hops
    """
    scene = setup_class_i_cascade_scene()
    publish_recall_notice(scene["notice"]["id"])

    loaner = read_loaner_assignment(scene["loaner"]["id"])
    assert loaner["status"] == "CANCELLED"
    assert loaner["billable_days"] == 0
    assert loaner["rental_cost_cents"] == 0


def test_class_i_cascade_escalates_the_uncovered_order_to_p1(api, ce_manager_headers):
    """PRD §3.6: "Crucially, the covered order's `loaner_status` becomes `UNCOVERED`, and when
    that order's `status` is still `INTAKE`, `IN_REPAIR` or `AWAITING_PARTS`, its `priority` is
    forced to `P1` and its `sla_hours` to 4 regardless of what the derivation in §3.4
    originally produced — a department left with no substitute machine is now the most urgent
    repair in the shop."
    PRD §3.4: "Placing an order on hold moves it `IN_REPAIR` → `AWAITING_PARTS`, optionally
    recording a `note`; the open active-repair segment is closed and its elapsed seconds are
    added to `active_repair_seconds`."

    Design: Difficulty/transitive_cascade/class_i_recall_cascade_reaches_work_order_priority_four_hops
    """
    from test_helpers import read_department

    scene = setup_class_i_cascade_scene()
    assert scene["work_order"]["priority"] == "P3"
    assert scene["work_order"]["sla_hours"] == 72

    publish_recall_notice(scene["notice"]["id"])

    order = read_work_order(scene["work_order"]["id"])
    assert order["loaner_status"] == "UNCOVERED"
    assert order["priority"] == "P1"
    assert order["sla_hours"] == 4
    assert order["status"] == "AWAITING_PARTS", "The cascade must not advance the repair itself"
    assert read_facility(scene["facility"]["id"])["ce_posture"] == "HEIGHTENED"
    assert read_department(scene["department"]["id"])["downtime_spend_cents"] == 0
