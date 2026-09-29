"""Refusals that guard the back of the fastener process.

This module exercises the paperwork and dispatch end of the plant: a certificate may
not cite a rejected destructive test nor a test belonging to a sibling lot, a pack may
not be shipped while it is still open, behind a certificate that was never issued, or
with an incomplete label; each certificate verb accepts only its own source status; a
closed secondary operation may not be closed twice; and a lot opened against wire it
cannot cover is refused without a gram being reserved or a press window booked. Every
expectation below is taken from the narratives of PRD §2.10, §3.3, §3.4, §3.5, §3.7,
§3.8 and §3.9.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_lot_piece_ledger,
    assert_wire_mass_ledger,
    factories,
    fixtures,
    make_clerk_headers,
    make_engineer_headers,
    make_inspector_headers,
    make_manager_headers,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

# The unplated reference part: plating_spec NONE, so the lot is testable straight from
# HEAT_TREATED and the relief-bake terms drop out of the risk score entirely.
UNPLATED_SPEC = {"max_decarb_depth_mm": 0.100, "pieces_per_kg": 62.5}

ENGINEER_1 = make_engineer_headers("eng-1")
INSPECTOR_1 = make_inspector_headers("insp-1")
INSPECTOR_2 = make_inspector_headers("insp-2")
MANAGER_1 = make_manager_headers("qm-1")
CLERK_1 = make_clerk_headers("ship-1")


# ---------------------------------------------------------------------------
# Local builders
# ---------------------------------------------------------------------------
def _heat_treated_unplated_lot():
    """An unplated lot at HEAT_TREATED with available_count 4850, ready for testing."""
    return fixtures.setup_heat_treated_lot(unplated=True, spec_overrides=UNPLATED_SPEC)


def _tested_unplated_lot():
    """The same route carried through one accepted destructive test: lot at TESTED."""
    return fixtures.setup_tested_lot(
        unplated=True,
        spec_overrides=UNPLATED_SPEC,
        min_measured_core_hardness_hv=322.0,
    )


def _certified_unplated_lot():
    """A lot at CERTIFIED behind one ISSUED certificate signed by qm-1."""
    return fixtures.setup_certified_lot(
        unplated=True,
        spec_overrides=UNPLATED_SPEC,
        min_measured_core_hardness_hv=322.0,
    )


def _open_lot_test(production_lot_id, headers):
    return validate_success(
        api_client.create_lot_test(
            factories.create_lot_test_payload(production_lot_id), headers
        ),
        201,
    )


def _record_lot_test(lot_test_id, headers, **overrides):
    return validate_success(
        api_client.record_lot_test_results(
            lot_test_id, factories.lot_test_results_payload(**overrides), headers
        )
    )


def _draft_response(production_lot_id, lot_test_id, cert_serial, headers):
    """POST a certificate draft with the lot's live version, returning the response."""
    payload = factories.create_certification_document_payload(
        production_lot_id,
        lot_test_id,
        fixtures.lot_version(production_lot_id),
        cert_serial=cert_serial,
    )
    return api_client.create_certification_document(payload, headers)


def _two_sibling_lots_at_tested():
    """Two lots drawn off one wire lot, one die and one furnace, both at TESTED.

    L-A is tested by insp-1 and L-B by insp-2, so each lot owns an ACCEPTed test of
    its own that the other lot could try to borrow.
    """
    env = fixtures.setup_master_data(unplated=True, spec_overrides=UNPLATED_SPEC)
    spec_id = env["spec"]["id"]
    wire_id = env["wire"]["id"]
    tool_id = env["tool"]["id"]
    furnace_id = env["furnace"]["id"]

    lot_a = fixtures.open_production_lot(
        spec_id,
        wire_id,
        tool_id,
        lot_code="L-A",
        press_code="PRESS-3",
        press_window_start_at="2026-09-01T06:00:00Z",
        press_window_end_at="2026-09-01T08:00:00Z",
        planned_pieces=1000,
    )
    fixtures.report_heading(lot_a["id"], 980, 20)
    lot_b = fixtures.open_production_lot(
        spec_id,
        wire_id,
        tool_id,
        lot_code="L-B",
        press_code="PRESS-3",
        press_window_start_at="2026-09-01T08:00:00Z",
        press_window_end_at="2026-09-01T10:00:00Z",
        planned_pieces=1000,
    )
    fixtures.report_heading(lot_b["id"], 980, 20)

    fixtures.run_secondary_op(lot_a["id"], "THREAD_ROLL", 1, 975)
    fixtures.run_secondary_op(lot_b["id"], "THREAD_ROLL", 1, 975)

    fixtures.run_heat_treat(
        lot_a["id"],
        furnace_id,
        start_at="2026-09-01T18:30:00Z",
        results_at="2026-09-01T19:30:00Z",
        window_start_at="2026-09-01T18:00:00Z",
        window_end_at="2026-09-01T20:00:00Z",
    )
    fixtures.run_heat_treat(
        lot_b["id"],
        furnace_id,
        start_at="2026-09-01T21:30:00Z",
        results_at="2026-09-01T22:30:00Z",
        window_start_at="2026-09-01T21:00:00Z",
        window_end_at="2026-09-01T23:00:00Z",
    )

    # Keep the *recorded* rows, not the PENDING open responses, so callers see the
    # ACCEPT verdict each lot's own test earned.
    test_a = _record_lot_test(
        _open_lot_test(lot_a["id"], INSPECTOR_1)["id"],
        INSPECTOR_1,
        min_measured_core_hardness_hv=322.0,
    )
    test_b = _record_lot_test(
        _open_lot_test(lot_b["id"], INSPECTOR_2)["id"],
        INSPECTOR_2,
        min_measured_core_hardness_hv=322.0,
    )

    env["lot_a"] = fixtures.read_lot(lot_a["id"])
    env["lot_b"] = fixtures.read_lot(lot_b["id"])
    env["test_a"] = test_a
    env["test_b"] = test_b
    return env


# ---------------------------------------------------------------------------
# A retested lot keeps its rejected first test, and cannot certify against it
# ---------------------------------------------------------------------------
def test_draft_citing_the_rejected_first_test_is_refused_while_the_retest_certifies():
    """After a retest accepts, the surviving rejected first test is still not citable.

    PRD: "The cited test must belong to the same lot as the certificate, or the draft is refused with `ERR_TEST_LOT_MISMATCH`; only then is the test's `result` examined, and a test that is not `ACCEPT` is refused with `ERR_TEST_NOT_ACCEPTED`."

    PRD: "On `REJECT` the test moves `PENDING → REJECT`, `risk_score_final` is still computed, the lot's `disposition` moves to `HOLD` with `hold_source` of `TEST_REJECT`, and the lot's `process_state` stays at `TESTING` — which is exactly why a certificate drafted after a retest can still be pointing at the first, rejected test."

    PRD: "The lot must be admissible: normally its `process_state` must be `BAKED`, but a part whose `plating_spec` is `NONE` may be tested straight from `HEAT_TREATED` or from `SECONDARY_DONE` — the latter covering parts whose thread rolling ran after heat treatment — and a lot already in `TESTING` may be tested again only when every existing test of that lot came back with `result` `REJECT`."

    PRD: "On `ACCEPT` the test moves `PENDING → ACCEPT`, the lot's `achieved_strength_class` is derived, `risk_score_final` is computed, and the lot moves `TESTING → TESTED`."

    PRD: "A fresh draft starts in `status` `DRAFT` with `revision` of 1 and `signed_by_user_id`, `issued_at` and `revoked_reason` all empty."

    PRD: "It copies `pinned_part_spec_version` from the lot's own `pinned_part_spec_version`, and sets `certified_strength_class` from the lot's `achieved_strength_class` as it stands at draft time."

    PRD: "The lot's own specified class gets first refusal: if the measured hardness falls inside the band of the part's `strength_class`, then `achieved_strength_class` is that class."

    Design: Corner/errors/retested_lot_cannot_cite_its_rejected_first_test
    """
    env = _heat_treated_unplated_lot()
    lot_id = env["lot"]["id"]

    first = _open_lot_test(lot_id, INSPECTOR_1)
    first = _record_lot_test(
        first["id"],
        INSPECTOR_1,
        proof_load_failures=1,
        tensile_failures=1,
        min_measured_core_hardness_hv=322.0,
    )
    assert first["result"] == "REJECT", f"Expected REJECT, got {first['result']}"

    held = fixtures.read_lot(lot_id)
    assert held["disposition"] == "HOLD", (
        f"Expected disposition HOLD after a rejected test, got {held['disposition']}"
    )
    assert held["hold_source"] == "TEST_REJECT", (
        f"Expected hold_source TEST_REJECT, got {held['hold_source']}"
    )
    assert held["process_state"] == "TESTING", (
        f"Expected process_state to stay TESTING, got {held['process_state']}"
    )

    fixtures.release_hold(lot_id, note="RETEST_AUTHORISED")
    second = _open_lot_test(lot_id, INSPECTOR_1)
    second = _record_lot_test(
        second["id"], INSPECTOR_1, min_measured_core_hardness_hv=322.0
    )
    assert second["result"] == "ACCEPT", f"Expected ACCEPT, got {second['result']}"

    tested = fixtures.read_lot(lot_id)
    assert tested["process_state"] == "TESTED", (
        f"Expected process_state TESTED after the accepted retest, got "
        f"{tested['process_state']}"
    )

    # The draft that cites the rejected first test is refused ...
    refused = _draft_response(lot_id, first["id"], "CERT-2641-A", INSPECTOR_1)
    validate_error(refused, ApiErrorId.ERR_TEST_NOT_ACCEPTED.value)

    items, pagination = validate_paginated(
        api_client.list_certification_documents(
            INSPECTOR_1, {"production_lot_id": lot_id}
        )
    )
    assert pagination["total_count"] == 0, (
        f"A refused draft must create no certificate row, got {pagination['total_count']}"
    )
    assert items == [], f"Expected no certificates for the lot, got {items}"

    # ... while the identical draft against the accepted retest, reusing the very same
    # plant-unique serial, succeeds — proving the refusal left nothing behind.
    accepted = _draft_response(lot_id, second["id"], "CERT-2641-A", INSPECTOR_1)
    cert = validate_success(accepted, 201)
    assert cert["status"] == "DRAFT", f"Expected DRAFT, got {cert['status']}"
    assert cert["revision"] == 1, f"Expected revision 1, got {cert['revision']}"
    assert cert["lot_test_id"] == second["id"], (
        "The certificate must cite the retest it was drafted against"
    )
    assert cert["certified_strength_class"] == "CLASS_10_9", (
        f"Expected certified_strength_class CLASS_10_9, got "
        f"{cert['certified_strength_class']}"
    )


def test_retest_of_a_rejected_lot_samples_under_tightened_inspection():
    """The retest is planned tightened, taking 104 pieces where the first took 70.

    PRD: "Severity is `TIGHTENED` when either of two things is true: the lot's `risk_score_pre_test` is at least 40.0, or a rejected test already exists anywhere in the plant on a production lot sharing both the same `part_spec_id` and the same `traceability_heat_id` as this lot."

    PRD: "Under **normal inspection**, `sample_size` is the greater of 8 and the square root of the lot's `available_count` raised upward to the next whole piece, and `acceptance_number` is 1 when that `sample_size` is at least 20 and 0 otherwise — so a single failure is tolerated on any lot holding 400 or more available pieces, and a lot holding fewer than 8 available pieces cannot be sampled at all."

    PRD: "Under **tightened inspection**, `sample_size` is the greater of 13 and 1.5 multiplied by the square root of `available_count`, raised upward to the next whole piece, and `acceptance_number` is 0 unconditionally — the very same measured failure count that accepts a lot under normal inspection rejects it under tightened inspection, and the sampling floor of 13 pieces is itself out of reach for a nearly exhausted lot."

    PRD: "The test's `destructive` flag defaults to true and the create payload offers no way to change it, so the sample is consumed: when `destructive` is true, the lot's `destructive_test_count` grows by `sample_size` and its `available_count` shrinks by the same amount, keeping the piece ledger balanced."

    PRD: "The chosen severity is copied onto the test as `severity` and simultaneously frozen onto the lot as `inspection_severity`; later movement in the lot's risk score never re-derives it, and it is always the pass-one score that feeds the decision."

    PRD: "The **heat term** is 0 when the lot's traceability heat has `cert_status` of `VERIFIED` and 25 otherwise."

    PRD: "The **tool term** is the lot's snapshotted `tool_utilization_pct`, capped at 100."

    PRD: "The **decarburization term** is 100 multiplied by the governing run's `total_decarb_depth_mm`, divided by the part's `max_decarb_depth_mm`, rounded half up to two decimal places and then capped at 100."

    PRD: "The score is 0.30 multiplied by the heat term, plus 0.20 multiplied by the tool term, plus 0.25 multiplied by the bake term, plus 0.25 multiplied by the decarburization term, with the sum rounded half up to two decimal places exactly once at the end — the individual weighted terms are never rounded on their own."

    PRD: "For a part whose `plating_spec` is `NONE` there is no plating run at all, so the lot never reaches `BAKED` and the pre-test score is instead computed when the lot test is opened, with the bake term taken as zero."

    PRD: "Once computed, `risk_score_pre_test` is frozen: the second scoring pass described in §3.7 never recomputes it."

    PRD: "`risk_score_final` adds test evidence to the frozen pre-test value: it is `risk_score_pre_test` plus 12.5 points for each failure counted in `total_failures`, capped at 100, and rounded half up to two decimal places."

    Design: Corner/errors/retested_lot_cannot_cite_its_rejected_first_test
    """
    env = _heat_treated_unplated_lot()
    lot_id = env["lot"]["id"]
    assert env["lot"]["available_count"] == 4850, (
        f"Expected 4850 available pieces before testing, got "
        f"{env['lot']['available_count']}"
    )

    first = _open_lot_test(lot_id, INSPECTOR_1)
    assert first["severity"] == "NORMAL", (
        f"Expected NORMAL severity on the first test, got {first['severity']}"
    )
    assert first["sample_size"] == 70, (
        f"Expected sample_size 70 for 4850 available pieces, got {first['sample_size']}"
    )
    assert first["acceptance_number"] == 1, (
        f"Expected acceptance_number 1 for a 70-piece normal sample, got "
        f"{first['acceptance_number']}"
    )

    after_first_open = fixtures.read_lot(lot_id)
    assert after_first_open["risk_score_pre_test"] == pytest.approx(5.83, abs=0.001), (
        f"Expected risk_score_pre_test 5.83, got "
        f"{after_first_open['risk_score_pre_test']}"
    )
    assert after_first_open["available_count"] == 4780, (
        f"Expected 4780 available after a 70-piece sample, got "
        f"{after_first_open['available_count']}"
    )
    assert after_first_open["inspection_severity"] == "NORMAL", (
        f"Expected the lot's inspection_severity frozen at NORMAL, got "
        f"{after_first_open['inspection_severity']}"
    )

    rejected = _record_lot_test(
        first["id"],
        INSPECTOR_1,
        proof_load_failures=1,
        tensile_failures=1,
        min_measured_core_hardness_hv=322.0,
    )
    assert rejected["total_failures"] == 2, (
        f"Expected total_failures 2, got {rejected['total_failures']}"
    )
    after_reject = fixtures.read_lot(lot_id)
    assert after_reject["risk_score_final"] == pytest.approx(30.83, abs=0.001), (
        f"Expected risk_score_final 30.83 (5.83 + 12.5 * 2), got "
        f"{after_reject['risk_score_final']}"
    )
    assert after_reject["risk_score_pre_test"] == pytest.approx(5.83, abs=0.001), (
        "risk_score_pre_test is frozen and must not be recomputed by the test result"
    )

    fixtures.release_hold(lot_id, note="RETEST_AUTHORISED")
    second = _open_lot_test(lot_id, INSPECTOR_1)
    assert second["severity"] == "TIGHTENED", (
        f"Expected TIGHTENED severity on the retest, got {second['severity']}"
    )
    assert second["sample_size"] == 104, (
        f"Expected sample_size 104 for 4780 available pieces under tightened "
        f"inspection, got {second['sample_size']}"
    )
    assert second["acceptance_number"] == 0, (
        f"Expected acceptance_number 0 under tightened inspection, got "
        f"{second['acceptance_number']}"
    )

    _record_lot_test(second["id"], INSPECTOR_1, min_measured_core_hardness_hv=322.0)
    final = fixtures.read_lot(lot_id)
    assert final["available_count"] == 4676, (
        f"Expected 4676 available after 70 + 104 destroyed pieces, got "
        f"{final['available_count']}"
    )
    assert final["destructive_test_count"] == 174, (
        f"Expected destructive_test_count 174, got {final['destructive_test_count']}"
    )
    assert final["risk_score_final"] == pytest.approx(5.83, abs=0.001), (
        f"Expected risk_score_final back to 5.83 with no failures, got "
        f"{final['risk_score_final']}"
    )
    assert_lot_piece_ledger(final)


# ---------------------------------------------------------------------------
# Sibling lots cannot borrow each other's paperwork
# ---------------------------------------------------------------------------
def test_certificate_cannot_cite_a_sibling_lots_accepted_test():
    """Lot B's certificate may not rest on lot A's test, accepted though that test is.

    PRD: "The cited test must belong to the same lot as the certificate, or the draft is refused with `ERR_TEST_LOT_MISMATCH`; only then is the test's `result` examined, and a test that is not `ACCEPT` is refused with `ERR_TEST_NOT_ACCEPTED`."

    PRD: "On certificate drafting, the cited test must belong to the same production lot as the certificate (`ERR_TEST_LOT_MISMATCH`, 409) and must have result `ACCEPT` (`ERR_TEST_NOT_ACCEPTED`, 409) — and the mismatch rule is evaluated *before* the not-accepted rule, so citing a foreign test reports the mismatch and only a same-lot, non-accepted test can reach the second rule."

    PRD: "Under **normal inspection**, `sample_size` is the greater of 8 and the square root of the lot's `available_count` raised upward to the next whole piece, and `acceptance_number` is 1 when that `sample_size` is at least 20 and 0 otherwise — so a single failure is tolerated on any lot holding 400 or more available pieces, and a lot holding fewer than 8 available pieces cannot be sampled at all."

    Design: Corner/errors/foreign_test_and_foreign_certificate_are_rejected
    """
    env = _two_sibling_lots_at_tested()
    lot_b_id = env["lot_b"]["id"]

    assert env["test_a"]["result"] == "ACCEPT", (
        "Lot A's test must be ACCEPTed so the refusal cannot be blamed on its verdict"
    )
    assert env["test_a"]["sample_size"] == 32, (
        f"Expected sample_size 32 for 975 available pieces, got "
        f"{env['test_a']['sample_size']}"
    )

    refused = _draft_response(lot_b_id, env["test_a"]["id"], "CERT-B", INSPECTOR_1)
    validate_error(refused, ApiErrorId.ERR_TEST_LOT_MISMATCH.value)

    _, pagination = validate_paginated(
        api_client.list_certification_documents(
            INSPECTOR_1, {"production_lot_id": lot_b_id}
        )
    )
    assert pagination["total_count"] == 0, (
        f"A refused draft must create no certificate row, got {pagination['total_count']}"
    )

    # Citing its own test, under the same serial the refusal never consumed, works.
    cert_b = validate_success(
        _draft_response(lot_b_id, env["test_b"]["id"], "CERT-B", INSPECTOR_1), 201
    )
    assert cert_b["production_lot_id"] == lot_b_id, (
        "The accepted draft must belong to lot B"
    )
    assert cert_b["lot_test_id"] == env["test_b"]["id"], (
        "The accepted draft must cite lot B's own test"
    )


def test_pack_unit_cannot_be_opened_under_a_sibling_lots_certificate():
    """Lot A's box may not be printed with the certificate that belongs to lot B.

    PRD: "The named certificate must belong to the same production lot as the pack, or the request is refused with `ERR_CERT_LOT_MISMATCH`."

    PRD: "The pack's `pack_mode` is copied from the part specification's `packaging_mode` and is therefore either `BY_COUNT` or `BY_WEIGHT`, and which one it is decides which measurement the payload must carry: a `BY_COUNT` pack supplies `actual_count`, the pieces physically counted into the box, which may not be negative and leaves `net_weight_kg` empty; a `BY_WEIGHT` pack supplies `net_weight_kg`, the weighed net mass, which must be strictly positive and leaves `actual_count` empty."

    PRD: "`count_tolerance_pieces` is the part's `nominal_pack_count` multiplied by its `count_tolerance_pct`, truncated downward to a whole number of pieces — so a nominal pack of 500 at a `count_tolerance_pct` of 0.02 tolerates 10 pieces of deviation, and a nominal pack of 40 at the same tolerance tolerates none at all, because 0.8 of a piece truncates downward to 0."

    PRD: "`packaging_mode` is either `BY_COUNT` or `BY_WEIGHT`; `nominal_pack_count` is the target number of pieces per pack and must be at least 1; `pieces_per_kg` is the nominal piece count per kilogram used to derive a declared count from a weighed pack and must be strictly positive; and `count_tolerance_pct` is the fraction of the nominal pack count tolerated as deviation, defaulting to 0.02 when omitted."

    Design: Corner/errors/foreign_test_and_foreign_certificate_are_rejected
    """
    env = _two_sibling_lots_at_tested()
    lot_a_id = env["lot_a"]["id"]
    lot_b_id = env["lot_b"]["id"]

    cert_a = validate_success(
        _draft_response(lot_a_id, env["test_a"]["id"], "CERT-A", INSPECTOR_2), 201
    )
    fixtures.issue_certificate(cert_a["id"], manager_user_id="qm-1")
    cert_b = validate_success(
        _draft_response(lot_b_id, env["test_b"]["id"], "CERT-B", INSPECTOR_1), 201
    )
    fixtures.issue_certificate(cert_b["id"], manager_user_id="qm-1")

    refused = api_client.create_pack_unit(
        factories.create_pack_unit_payload(
            lot_a_id, cert_b["id"], label_serial="PK-X1", actual_count=100
        ),
        CLERK_1,
    )
    validate_error(refused, ApiErrorId.ERR_CERT_LOT_MISMATCH.value)

    _, pagination = validate_paginated(
        api_client.list_pack_units(CLERK_1, {"production_lot_id": lot_a_id})
    )
    assert pagination["total_count"] == 0, (
        f"A refused pack-unit opening must create no pack row, got "
        f"{pagination['total_count']}"
    )

    # The same label serial opens cleanly under lot A's own certificate.
    pack = validate_success(
        api_client.create_pack_unit(
            factories.create_pack_unit_payload(
                lot_a_id, cert_a["id"], label_serial="PK-X1", actual_count=100
            ),
            CLERK_1,
        ),
        201,
    )
    assert pack["pack_mode"] == "BY_COUNT", (
        f"Expected pack_mode BY_COUNT copied from the part, got {pack['pack_mode']}"
    )
    assert pack["declared_count"] == 100, (
        f"Expected declared_count 100 taken verbatim from actual_count, got "
        f"{pack['declared_count']}"
    )
    assert pack["count_tolerance_pieces"] == 2, (
        f"Expected count_tolerance_pieces 2 (floor of 100 * 0.02), got "
        f"{pack['count_tolerance_pieces']}"
    )


# ---------------------------------------------------------------------------
# The three gates on shipment, in the order the ladder fixes
# ---------------------------------------------------------------------------
def test_shipping_an_open_pack_is_refused_on_its_own_state():
    """A box that was never sealed cannot leave the dock.

    PRD: "A pack unit must be `OPEN` to seal and `SEALED` to reopen or ship, with `RECALLED` terminal — otherwise `ERR_INVALID_PACK_UNIT_STATE` (409)."

    PRD: "A new pack starts in `status` `OPEN` with `sealed_at`, `shipped_at` and `recall_reason` all empty."

    Design: Corner/errors/ship_rejects_an_open_pack_an_unissued_certificate_and_an_incomplete_label
    """
    env = fixtures.setup_open_pack(
        unplated=True,
        spec_overrides=UNPLATED_SPEC,
        min_measured_core_hardness_hv=322.0,
    )
    pack_id = env["pack"]["id"]
    assert env["pack"]["status"] == "OPEN", (
        f"Expected a fresh pack in OPEN, got {env['pack']['status']}"
    )

    validate_error(
        api_client.ship_pack_unit(pack_id, CLERK_1),
        ApiErrorId.ERR_INVALID_PACK_UNIT_STATE.value,
    )

    unchanged = fixtures.read_pack_unit(pack_id)
    assert unchanged["status"] == "OPEN", (
        f"Expected the pack to stay OPEN after the refusal, got {unchanged['status']}"
    )
    assert not unchanged["shipped_at"], (
        f"A refused shipment must not stamp shipped_at, got {unchanged['shipped_at']}"
    )
    assert unchanged["version"] == env["pack"]["version"], (
        f"A refused shipment must not bump the pack version, got "
        f"{unchanged['version']}"
    )

    lot = fixtures.read_lot(env["lot"]["id"])
    assert lot["process_state"] == "CERTIFIED", (
        f"Expected the lot to stay CERTIFIED, got {lot['process_state']}"
    )
    assert lot["packed_count"] == 0, (
        f"Expected packed_count 0 while nothing is sealed, got {lot['packed_count']}"
    )


def test_a_shipped_pack_cannot_be_shipped_a_second_time():
    """SHIPPED is not a shipping source state, so the second dispatch is refused.

    PRD: "On success the pack moves `SEALED → SHIPPED` and `shipped_at` is stamped from the logical clock; the lot moves `PACKED → SHIPPED` only once every pack unit of the lot is in `status` `SHIPPED` and at least one such pack exists."

    PRD: "A pack unit must be `OPEN` to seal and `SEALED` to reopen or ship, with `RECALLED` terminal — otherwise `ERR_INVALID_PACK_UNIT_STATE` (409)."

    Design: Corner/errors/ship_rejects_an_open_pack_an_unissued_certificate_and_an_incomplete_label
    """
    env = fixtures.setup_sealed_pack(
        unplated=True,
        spec_overrides=UNPLATED_SPEC,
        min_measured_core_hardness_hv=322.0,
    )
    pack_id = env["pack"]["id"]

    shipped = validate_success(api_client.ship_pack_unit(pack_id, CLERK_1))
    assert shipped["status"] == "SHIPPED", (
        f"Expected status SHIPPED, got {shipped['status']}"
    )
    assert shipped["shipped_at"], "shipped_at must be stamped from the logical clock"

    lot = fixtures.read_lot(env["lot"]["id"])
    assert lot["process_state"] == "SHIPPED", (
        f"With the lot's only pack shipped the lot must reach SHIPPED, got "
        f"{lot['process_state']}"
    )

    validate_error(
        api_client.ship_pack_unit(pack_id, CLERK_1),
        ApiErrorId.ERR_INVALID_PACK_UNIT_STATE.value,
    )
    again = fixtures.read_pack_unit(pack_id)
    assert again["status"] == "SHIPPED", (
        f"Expected the pack to stay SHIPPED, got {again['status']}"
    )
    assert again["version"] == shipped["version"], (
        f"A refused re-shipment must not bump the pack version, got {again['version']}"
    )


def test_shipment_reports_the_unissued_certificate_before_the_incomplete_label():
    """A sealed pack behind a DRAFT certificate reports the paperwork, not the label.

    PRD: "The pack's certificate must be in `status` `ISSUED`, or the shipment is refused with `ERR_CERT_NOT_ISSUED`."

    PRD: "At shipment the certificate must be `ISSUED` (`ERR_CERT_NOT_ISSUED`, 409)."

    PRD: "This ordering is normative — it is what makes an error response predictable when a request breaks several rules at once."

    PRD: "On success the pack moves `OPEN → SEALED`, `sealed_at` is stamped from the logical clock, the lot's `packed_count` grows by `declared_count` while its `available_count` shrinks by the same amount, the lot moves `CERTIFIED → PACKED`, and the pack's `version` and the lot's `version` each increment by 1."

    Design: Corner/errors/ship_rejects_an_open_pack_an_unissued_certificate_and_an_incomplete_label
    """
    env = _tested_unplated_lot()
    lot_id = env["lot"]["id"]
    test_id = env["lot_test"]["id"]

    cert_a = validate_success(_draft_response(lot_id, test_id, "CERT-A", INSPECTOR_1), 201)
    cert_b = validate_success(_draft_response(lot_id, test_id, "CERT-B", INSPECTOR_1), 201)
    fixtures.issue_certificate(cert_a["id"], manager_user_id="qm-1")
    assert fixtures.read_certificate(cert_b["id"])["status"] == "DRAFT", (
        "CERT-B must stay DRAFT so the shipment has an unissued certificate to hit"
    )

    # This pack breaks two rules at once: its certificate is unissued *and* its label
    # is incomplete. The lower-numbered rule decides.
    pack = fixtures.open_pack(
        lot_id, cert_b["id"], label_serial="PK-2", label_fields_complete=False
    )
    fixtures.seal_pack(pack["id"])

    validate_error(
        api_client.ship_pack_unit(pack["id"], CLERK_1),
        ApiErrorId.ERR_CERT_NOT_ISSUED.value,
    )

    still_sealed = fixtures.read_pack_unit(pack["id"])
    assert still_sealed["status"] == "SEALED", (
        f"Expected the pack to stay SEALED after the refusal, got "
        f"{still_sealed['status']}"
    )
    assert not still_sealed["shipped_at"], (
        "A refused shipment must not stamp shipped_at"
    )
    lot = fixtures.read_lot(lot_id)
    assert lot["process_state"] == "PACKED", (
        f"Expected the lot to stay PACKED with nothing shipped, got "
        f"{lot['process_state']}"
    )


def test_shipment_of_an_incompletely_labelled_pack_is_refused():
    """With the certificate issued, the omitted label confirmation is what blocks it.

    PRD: "The payload may also carry `label_fields_complete`, the operator's confirmation that the printed label actually carries the certificate serial, the lot code and the declared count; it defaults to false, and a pack opened without that confirmation can never ship."

    PRD: "`label_fields_complete` must be true, or the shipment is refused with `ERR_PACK_LABEL_INCOMPLETE`."

    PRD: "On success the pack moves `OPEN → SEALED`, `sealed_at` is stamped from the logical clock, the lot's `packed_count` grows by `declared_count` while its `available_count` shrinks by the same amount, the lot moves `CERTIFIED → PACKED`, and the pack's `version` and the lot's `version` each increment by 1."

    Design: Corner/errors/ship_rejects_an_open_pack_an_unissued_certificate_and_an_incomplete_label
    """
    env = _certified_unplated_lot()
    lot_id = env["lot"]["id"]

    payload = factories.create_pack_unit_payload(
        lot_id, env["certificate"]["id"], label_serial="PK-3", actual_count=100
    )
    payload.pop("label_fields_complete")
    pack = validate_success(api_client.create_pack_unit(payload, CLERK_1), 201)
    assert pack["label_fields_complete"] is False, (
        "label_fields_complete must default to false when the field is omitted, got "
        f"{pack['label_fields_complete']}"
    )

    fixtures.seal_pack(pack["id"])
    assert fixtures.read_certificate(env["certificate"]["id"])["status"] == "ISSUED", (
        "The certificate must be ISSUED so the label rule is the one that is reached"
    )

    validate_error(
        api_client.ship_pack_unit(pack["id"], CLERK_1),
        ApiErrorId.ERR_PACK_LABEL_INCOMPLETE.value,
    )

    still_sealed = fixtures.read_pack_unit(pack["id"])
    assert still_sealed["status"] == "SEALED", (
        f"Expected the pack to stay SEALED, got {still_sealed['status']}"
    )
    lot = fixtures.read_lot(lot_id)
    assert lot["process_state"] == "PACKED", (
        f"Expected the lot to stay PACKED, got {lot['process_state']}"
    )
    assert lot["packed_count"] == 100, (
        f"Expected packed_count 100 from the seal, got {lot['packed_count']}"
    )
    assert_lot_piece_ledger(lot)


# ---------------------------------------------------------------------------
# Each certificate verb accepts only its own source status
# ---------------------------------------------------------------------------
def test_issued_certificate_refuses_a_second_issue_and_an_early_reissue():
    """ISSUED is neither an issue source nor a reissue source.

    PRD: "A certificate must be `DRAFT` or `REISSUE_PENDING` to be issued, `DRAFT`, `ISSUED` or `REISSUE_PENDING` to be revoked, and `REVOKED` to be reissued — otherwise `ERR_INVALID_CERT_STATE` (409)."

    PRD: "Signing a certificate in `status` `DRAFT` requires the lot to be in `process_state` `TESTED` with `disposition` `IN_PROCESS`; the certificate moves `DRAFT → ISSUED`, `issued_at` is stamped from the logical clock, `signed_by_user_id` takes the acting `X-User-ID`, the lot moves `TESTED → CERTIFIED`, and the certificate's `version` and the lot's `version` each increment by 1."

    Design: Corner/errors/certificate_status_gates_issue_revoke_and_reissue
    """
    env = _certified_unplated_lot()
    cert_id = env["certificate"]["id"]
    before = fixtures.read_certificate(cert_id)
    assert before["status"] == "ISSUED", (
        f"Expected an ISSUED certificate to start from, got {before['status']}"
    )
    assert before["signed_by_user_id"] == "qm-1", (
        f"Expected signed_by_user_id qm-1, got {before['signed_by_user_id']}"
    )

    validate_error(
        api_client.issue_certification_document(cert_id, MANAGER_1),
        ApiErrorId.ERR_INVALID_CERT_STATE.value,
    )
    validate_error(
        api_client.reissue_certification_document(
            cert_id, {"cert_serial": "CERT-0001-R2"}, MANAGER_1
        ),
        ApiErrorId.ERR_INVALID_CERT_STATE.value,
    )

    after = fixtures.read_certificate(cert_id)
    assert after["status"] == "ISSUED", (
        f"Expected the certificate to stay ISSUED, got {after['status']}"
    )
    assert after["signed_by_user_id"] == "qm-1", (
        f"Expected signed_by_user_id still qm-1, got {after['signed_by_user_id']}"
    )
    assert after["cert_serial"] == before["cert_serial"], (
        f"Expected cert_serial still {before['cert_serial']}, got {after['cert_serial']}"
    )
    assert after["revision"] == 1, f"Expected revision still 1, got {after['revision']}"
    assert after["version"] == before["version"], (
        f"Two refusals must not bump the version, got {after['version']}"
    )


def test_revoked_certificate_refuses_a_second_revocation():
    """A withdrawn certificate cannot be withdrawn twice.

    PRD: "Revoking a certificate in `status` `DRAFT`, `ISSUED` or `REISSUE_PENDING` with a supplied `reason` moves it to `REVOKED` and records that reason as `revoked_reason`."

    PRD: "When the revocation came from the operator endpoint and the lot's `disposition` was `IN_PROCESS`, the lot additionally moves to `disposition` `HOLD` with `hold_source` of `QUALITY`."

    PRD: "A certificate must be `DRAFT` or `REISSUE_PENDING` to be issued, `DRAFT`, `ISSUED` or `REISSUE_PENDING` to be revoked, and `REVOKED` to be reissued — otherwise `ERR_INVALID_CERT_STATE` (409)."

    Design: Corner/errors/certificate_status_gates_issue_revoke_and_reissue
    """
    env = _certified_unplated_lot()
    cert_id = env["certificate"]["id"]
    lot_id = env["lot"]["id"]

    revoked = validate_success(
        api_client.revoke_certification_document(
            cert_id, {"reason": "CUSTOMER_COMPLAINT"}, MANAGER_1
        )
    )
    assert revoked["status"] == "REVOKED", (
        f"Expected status REVOKED, got {revoked['status']}"
    )
    assert revoked["revoked_reason"] == "CUSTOMER_COMPLAINT", (
        f"Expected revoked_reason CUSTOMER_COMPLAINT, got {revoked['revoked_reason']}"
    )

    held = fixtures.read_lot(lot_id)
    assert held["disposition"] == "HOLD", (
        f"Expected the lot on HOLD after the revocation, got {held['disposition']}"
    )
    assert held["hold_source"] == "QUALITY", (
        f"Expected hold_source QUALITY, got {held['hold_source']}"
    )

    validate_error(
        api_client.revoke_certification_document(
            cert_id, {"reason": "DUPLICATE_ENTRY"}, MANAGER_1
        ),
        ApiErrorId.ERR_INVALID_CERT_STATE.value,
    )
    after = fixtures.read_certificate(cert_id)
    assert after["revoked_reason"] == "CUSTOMER_COMPLAINT", (
        f"The refused revocation must not overwrite revoked_reason, got "
        f"{after['revoked_reason']}"
    )
    assert after["version"] == revoked["version"], (
        f"A refused revocation must not bump the version, got {after['version']}"
    )


def test_reissue_runs_once_out_of_revoked_and_then_refuses_reissue_pending():
    """REVOKED is the only reissue source, and only once the quality hold is lifted.

    PRD: "A `QualityManager` reissues it by supplying a new, plant-unique `cert_serial`; the certificate must be in `status` `REVOKED` and the lot's `disposition` must be `IN_PROCESS`, so a lot still on hold reports `ERR_LOT_ON_HOLD` and a quarantined lot reports `ERR_LOT_QUARANTINED`."

    PRD: "On success the new serial replaces the old one, `revision` increments by 1, the `status` moves `REVOKED → REISSUE_PENDING`, `signed_by_user_id` is cleared, the `traceability_chain` is re-projected from the lot's current provenance, and the certificate's `version` increments by 1 — closing the cycle `ISSUED → REVOKED → REISSUE_PENDING → ISSUED`."

    PRD: "A certificate must be `DRAFT` or `REISSUE_PENDING` to be issued, `DRAFT`, `ISSUED` or `REISSUE_PENDING` to be revoked, and `REVOKED` to be reissued — otherwise `ERR_INVALID_CERT_STATE` (409)."

    Design: Corner/errors/certificate_status_gates_issue_revoke_and_reissue
    """
    env = _certified_unplated_lot()
    cert_id = env["certificate"]["id"]
    lot_id = env["lot"]["id"]

    fixtures.revoke_certificate(cert_id, reason="CUSTOMER_COMPLAINT")

    # The revocation left the lot on a quality hold, which outranks the certificate's
    # own state check.
    validate_error(
        api_client.reissue_certification_document(
            cert_id, {"cert_serial": "CERT-0001-R2"}, MANAGER_1
        ),
        ApiErrorId.ERR_LOT_ON_HOLD.value,
    )

    fixtures.release_hold(lot_id, note="REISSUE_AUTHORISED")
    reissued = validate_success(
        api_client.reissue_certification_document(
            cert_id, {"cert_serial": "CERT-0001-R2"}, MANAGER_1
        )
    )
    assert reissued["status"] == "REISSUE_PENDING", (
        f"Expected status REISSUE_PENDING, got {reissued['status']}"
    )
    assert reissued["revision"] == 2, (
        f"Expected revision 2, got {reissued['revision']}"
    )
    assert reissued["cert_serial"] == "CERT-0001-R2", (
        f"Expected the new serial CERT-0001-R2, got {reissued['cert_serial']}"
    )
    assert not reissued["signed_by_user_id"], (
        f"signed_by_user_id must be cleared on reissue, got "
        f"{reissued['signed_by_user_id']}"
    )

    validate_error(
        api_client.reissue_certification_document(
            cert_id, {"cert_serial": "CERT-0001-R3"}, MANAGER_1
        ),
        ApiErrorId.ERR_INVALID_CERT_STATE.value,
    )
    after = fixtures.read_certificate(cert_id)
    assert after["cert_serial"] == "CERT-0001-R2", (
        f"The refused reissue must not replace the serial, got {after['cert_serial']}"
    )
    assert after["revision"] == 2, (
        f"The refused reissue must not advance the revision, got {after['revision']}"
    )


# ---------------------------------------------------------------------------
# A closed secondary operation stays closed
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("repeat_pieces_out", [975, 900])
def test_completing_a_done_secondary_operation_again_is_refused(repeat_pieces_out):
    """A DONE operation refuses a second closure and does not move pieces twice.

    PRD: "A secondary operation must still be `PENDING` to be completed — otherwise `ERR_INVALID_SECONDARY_OP_STATE` (409)."

    PRD: "On success the operation moves `PENDING → DONE` (a terminal status), `pieces_out` is recorded, and `scrap_pieces` is set to `pieces_in` minus `pieces_out`."

    PRD: "The lot absorbs the yield: its `available_count` is replaced by `pieces_out` and its `scrap_count` grows by `scrap_pieces`, keeping the piece ledger of §2.8 balanced."

    PRD: "When the lot has no operation left in `status` `PENDING` *and* the operations due at this stage are all `DONE`, the lot moves `SECONDARY_IN_PROGRESS → SECONDARY_DONE`."

    PRD: "For a part with `thread_timing` of `BEFORE_HEAT_TREAT`, every `op_type` listed in `required_secondary_ops` must have a `DONE` operation."

    Design: Corner/errors/secondary_operation_completion_cannot_be_repeated
    """
    env = fixtures.setup_headed_lot(
        planned_pieces=1000,
        headed_count=980,
        heading_scrap_count=20,
        unplated=True,
        spec_overrides=dict(
            UNPLATED_SPEC,
            part_number="NP-M8-DT",
            required_secondary_ops=["DRILL", "THREAD_ROLL"],
        ),
        lot_overrides={
            "lot_code": "L-2649",
            "press_window_end_at": "2026-09-01T08:00:00Z",
        },
    )
    lot_id = env["lot"]["id"]

    op = fixtures.queue_op(lot_id, op_type="DRILL", sequence_no=1, machine_code="DR-1")
    assert op["pieces_in"] == 980, (
        f"Expected pieces_in 980 from the lot's available_count, got {op['pieces_in']}"
    )
    done = fixtures.complete_op(op["id"], 975)
    assert done["status"] == "DONE", f"Expected status DONE, got {done['status']}"
    assert done["scrap_pieces"] == 5, (
        f"Expected scrap_pieces 5 (980 - 975), got {done['scrap_pieces']}"
    )

    validate_error(
        api_client.complete_secondary_operation(
            op["id"], {"pieces_out": repeat_pieces_out}, ENGINEER_1
        ),
        ApiErrorId.ERR_INVALID_SECONDARY_OP_STATE.value,
    )

    rows, _ = validate_paginated(
        api_client.list_secondary_operations(lot_id, ENGINEER_1)
    )
    row = next(r for r in rows if r["id"] == op["id"])
    assert row["status"] == "DONE", f"Expected status still DONE, got {row['status']}"
    assert row["pieces_out"] == 975, (
        f"Expected pieces_out still 975, got {row['pieces_out']}"
    )
    assert row["scrap_pieces"] == 5, (
        f"Expected scrap_pieces still 5, got {row['scrap_pieces']}"
    )
    assert row["version"] == 2, (
        f"Expected the operation's version still 2 after the refusal, got "
        f"{row['version']}"
    )

    lot = fixtures.read_lot(lot_id)
    assert lot["available_count"] == 975, (
        f"Expected available_count still 975 with no double deduction, got "
        f"{lot['available_count']}"
    )
    assert lot["scrap_count"] == 25, (
        f"Expected scrap_count still 25 (20 heading + 5 drilling), got "
        f"{lot['scrap_count']}"
    )
    assert lot["process_state"] == "SECONDARY_IN_PROGRESS", (
        f"Expected SECONDARY_IN_PROGRESS while the required THREAD_ROLL is outstanding, "
        f"got {lot['process_state']}"
    )
    assert_lot_piece_ledger(lot)


# ---------------------------------------------------------------------------
# The two material-sufficiency refusals at lot opening
# ---------------------------------------------------------------------------
def _shortfall_environment():
    """A verified heat with a 100 kg and a 500 kg released wire lot, and two dies."""
    env = fixtures.setup_master_data(
        unplated=True,
        spec_overrides=UNPLATED_SPEC,
        heat_overrides={"gross_mass_kg": 600.0},
        wire_overrides={"gross_mass_kg": 100.0},
        tool_overrides={"tool_code": "DIE-TINY", "rated_life_pieces": 1000},
        press_code="PRESS-7",
    )
    env["wire_small"] = env["wire"]
    env["wire_big"] = fixtures.create_released_wire_lot(
        env["heat"]["id"], gross_mass_kg=500.0
    )
    env["tool_tiny"] = env["tool"]
    env["tool_big"] = fixtures.create_mounted_tool(
        press_code="PRESS-3", tool_code="DIE-BIG", rated_life_pieces=120000
    )
    return env


def _open_lot_response(env, wire, tool, headers, **overrides):
    payload = factories.create_production_lot_payload(
        env["spec"]["id"],
        wire["id"],
        tool["id"],
        fixtures.wire_lot_version(wire["id"]),
        press_window_start_at="2026-09-01T06:00:00Z",
        press_window_end_at="2026-09-01T10:00:00Z",
        **overrides,
    )
    return api_client.create_production_lot(payload, headers)


def test_lot_short_of_both_wire_and_die_life_is_refused_by_one_of_the_two_rules(
    engineer_headers,
):
    """A lot short of wire *and* short of die life is refused without any side effect.

    PRD: "The wire lot's `available_mass_kg` must be at least that amount, or the request is refused with `ERR_WIRE_MASS_INSUFFICIENT`."

    PRD: "If the demand exceeds the remaining life, the request is refused with `ERR_TOOL_LIFE_EXHAUSTED`."

    PRD: "On success, that amount is subtracted from `available_mass_kg`, added to `reserved_mass_kg`, and stored on the lot as `wire_reserved_kg`; the wire lot's `version` increments by 1."

    PRD: "Wire mass sufficiency (`ERR_WIRE_MASS_INSUFFICIENT`, 422) and remaining die life (`ERR_TOOL_LIFE_EXHAUSTED`, 422) on lot opening; and furnace charge capacity (`ERR_FURNACE_CAPACITY_EXCEEDED`, 422) on run booking."

    Design: Corner/errors/wire_mass_shortfall_outranks_the_tool_life_shortfall
    """
    env = _shortfall_environment()
    small_before = fixtures.read_wire_lot(env["wire_small"]["id"])

    # Required mass is 105.000 kg against 100.000 available, and the demand of 5250
    # pieces is far beyond the 1000-piece die. Both priority-17 rules are broken.
    resp = _open_lot_response(
        env,
        env["wire_small"],
        env["tool_tiny"],
        engineer_headers,
        lot_code="L-BOTH",
        press_code="PRESS-7",
        planned_pieces=5000,
    )
    matched = validate_error_is_one_of(
        resp,
        [
            ApiErrorId.ERR_WIRE_MASS_INSUFFICIENT.value,
            ApiErrorId.ERR_TOOL_LIFE_EXHAUSTED.value,
        ],
    )
    assert resp.status_code == 422, (
        f"Both material-sufficiency refusals carry 422, got {resp.status_code} "
        f"for {matched}"
    )

    small_after = fixtures.read_wire_lot(env["wire_small"]["id"])
    assert small_after["available_mass_kg"] == pytest.approx(100.000, abs=0.001), (
        f"Expected available_mass_kg untouched at 100.000, got "
        f"{small_after['available_mass_kg']}"
    )
    assert small_after["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001), (
        f"A refused opening must reserve nothing, got {small_after['reserved_mass_kg']}"
    )
    assert small_after["version"] == small_before["version"], (
        f"A refused opening must not bump the wire lot version, got "
        f"{small_after['version']}"
    )
    assert_wire_mass_ledger(small_after)

    _, pagination = validate_paginated(
        api_client.list_production_lots(engineer_headers)
    )
    assert pagination["total_count"] == 0, (
        f"No production lot may survive the refusal, got {pagination['total_count']}"
    )


def test_ample_wire_exposes_the_die_life_shortfall_and_a_smaller_lot_opens(
    engineer_headers,
):
    """With wire to spare the same call reports the die, and a 900-piece lot fits.

    PRD: "The demand is the planned output inflated by the scrap allowance — `planned_pieces` multiplied by one plus the part's `scrap_allowance_pct`, raised upward to the next whole piece."

    PRD: "If the demand exceeds the remaining life, the request is refused with `ERR_TOOL_LIFE_EXHAUSTED`."

    PRD: "The required mass is `planned_pieces` multiplied by the part's `blank_mass_g`, multiplied by one plus `scrap_allowance_pct`, divided by 1000 to convert grams to kilograms, and rounded half up to three decimal places."

    PRD: "On success, that amount is subtracted from `available_mass_kg`, added to `reserved_mass_kg`, and stored on the lot as `wire_reserved_kg`; the wire lot's `version` increments by 1."

    Design: Corner/errors/wire_mass_shortfall_outranks_the_tool_life_shortfall
    """
    env = _shortfall_environment()
    big_before = fixtures.read_wire_lot(env["wire_big"]["id"])

    refused = _open_lot_response(
        env,
        env["wire_big"],
        env["tool_tiny"],
        engineer_headers,
        lot_code="L-TOOL",
        press_code="PRESS-7",
        planned_pieces=5000,
    )
    validate_error(refused, ApiErrorId.ERR_TOOL_LIFE_EXHAUSTED.value)

    untouched = fixtures.read_wire_lot(env["wire_big"]["id"])
    assert untouched["available_mass_kg"] == pytest.approx(500.000, abs=0.001), (
        f"Expected available_mass_kg untouched at 500.000, got "
        f"{untouched['available_mass_kg']}"
    )
    assert untouched["version"] == big_before["version"], (
        f"A refused opening must not bump the wire lot version, got "
        f"{untouched['version']}"
    )

    # 900 planned pieces demand ceil(945) == 945 pieces of die life and 18.900 kg.
    created = validate_success(
        _open_lot_response(
            env,
            env["wire_big"],
            env["tool_tiny"],
            engineer_headers,
            lot_code="L-OK",
            press_code="PRESS-7",
            planned_pieces=900,
        ),
        201,
    )
    assert created["wire_reserved_kg"] == pytest.approx(18.900, abs=0.001), (
        f"Expected wire_reserved_kg 18.900 (900 * 20.0 * 1.05 / 1000), got "
        f"{created['wire_reserved_kg']}"
    )

    after = fixtures.read_wire_lot(env["wire_big"]["id"])
    assert after["available_mass_kg"] == pytest.approx(481.100, abs=0.001), (
        f"Expected available_mass_kg 481.100 after the reservation, got "
        f"{after['available_mass_kg']}"
    )
    assert after["reserved_mass_kg"] == pytest.approx(18.900, abs=0.001), (
        f"Expected reserved_mass_kg 18.900, got {after['reserved_mass_kg']}"
    )
    assert after["version"] == big_before["version"] + 1, (
        f"Expected the wire lot version to advance by exactly 1, got {after['version']}"
    )
    assert_wire_mass_ledger(after)


def test_ample_die_life_exposes_the_wire_mass_shortfall(engineer_headers):
    """With die life to spare the 100 kg coil is what refuses the 5000-piece lot.

    PRD: "The required mass is `planned_pieces` multiplied by the part's `blank_mass_g`, multiplied by one plus `scrap_allowance_pct`, divided by 1000 to convert grams to kilograms, and rounded half up to three decimal places."

    PRD: "The wire lot's `available_mass_kg` must be at least that amount, or the request is refused with `ERR_WIRE_MASS_INSUFFICIENT`."

    Design: Corner/errors/wire_mass_shortfall_outranks_the_tool_life_shortfall
    """
    env = _shortfall_environment()
    small_before = fixtures.read_wire_lot(env["wire_small"]["id"])

    resp = _open_lot_response(
        env,
        env["wire_small"],
        env["tool_big"],
        engineer_headers,
        lot_code="L-WIRE",
        press_code="PRESS-3",
        planned_pieces=5000,
    )
    validate_error(resp, ApiErrorId.ERR_WIRE_MASS_INSUFFICIENT.value)

    after = fixtures.read_wire_lot(env["wire_small"]["id"])
    assert after["available_mass_kg"] == pytest.approx(100.000, abs=0.001), (
        f"Expected available_mass_kg untouched at 100.000, got "
        f"{after['available_mass_kg']}"
    )
    assert after["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001), (
        f"A refused opening must reserve nothing, got {after['reserved_mass_kg']}"
    )
    assert after["version"] == small_before["version"], (
        f"A refused opening must not bump the wire lot version, got {after['version']}"
    )
    assert_wire_mass_ledger(after)


# ---------------------------------------------------------------------------
# Mount needs AVAILABLE, condemn needs MOUNTED, regrind needs WORN
# ---------------------------------------------------------------------------
def _register_die(engineer_headers):
    return validate_success(
        api_client.create_heading_tool(
            factories.create_heading_tool_payload(
                tool_code="DIE-4S-002", rated_life_pieces=120000
            ),
            engineer_headers,
        ),
        201,
    )


@pytest.mark.parametrize("verb", ["regrind", "condemn"])
def test_available_die_refuses_regrind_and_condemn(verb, engineer_headers):
    """A die still on the shelf can be mounted and nothing else.

    PRD: "A heading tool must be `AVAILABLE` to mount, `MOUNTED` to condemn, and `WORN` to regrind — otherwise `ERR_INVALID_TOOL_STATE` (409)."

    Design: Corner/errors/tool_transition_guards_reject_every_out_of_order_verb
    """
    tool = _register_die(engineer_headers)
    assert tool["status"] == "AVAILABLE", (
        f"Expected a fresh die in AVAILABLE, got {tool['status']}"
    )

    if verb == "regrind":
        resp = api_client.regrind_heading_tool(tool["id"], engineer_headers)
    else:
        resp = api_client.condemn_heading_tool(
            tool["id"], {"reason": "CHIPPED_STATION_2"}, INSPECTOR_1
        )
    validate_error(resp, ApiErrorId.ERR_INVALID_TOOL_STATE.value)

    after = fixtures.read_tool(tool["id"])
    assert after["status"] == "AVAILABLE", (
        f"Expected the die to stay AVAILABLE, got {after['status']}"
    )
    assert after["version"] == 1, (
        f"A refused {verb} must leave the version at 1, got {after['version']}"
    )
    assert after["cycle_pieces_history"] == [], (
        f"A refused {verb} must not close a cycle, got {after['cycle_pieces_history']}"
    )


def test_mounted_die_refuses_a_second_mount_and_a_regrind(engineer_headers):
    """A die already on a press cannot be re-mounted or reground.

    PRD: "A `ProcessEngineer` mounts an `AVAILABLE` set on a press by supplying the `press_code`, taking it `AVAILABLE → MOUNTED`, recording the press in `mounted_press_code`, clearing any previous `condemn_reason`, and incrementing the set's `version` by 1."

    PRD: "A heading tool must be `AVAILABLE` to mount, `MOUNTED` to condemn, and `WORN` to regrind — otherwise `ERR_INVALID_TOOL_STATE` (409)."

    Design: Corner/errors/tool_transition_guards_reject_every_out_of_order_verb
    """
    tool = _register_die(engineer_headers)
    mounted = validate_success(
        api_client.mount_heading_tool(
            tool["id"], {"press_code": "PRESS-5"}, engineer_headers
        )
    )
    assert mounted["status"] == "MOUNTED", (
        f"Expected status MOUNTED, got {mounted['status']}"
    )
    assert mounted["mounted_press_code"] == "PRESS-5", (
        f"Expected mounted_press_code PRESS-5, got {mounted['mounted_press_code']}"
    )
    assert mounted["version"] == 2, (
        f"Expected version 2 after mounting, got {mounted['version']}"
    )

    validate_error(
        api_client.mount_heading_tool(
            tool["id"], {"press_code": "PRESS-6"}, engineer_headers
        ),
        ApiErrorId.ERR_INVALID_TOOL_STATE.value,
    )
    validate_error(
        api_client.regrind_heading_tool(tool["id"], engineer_headers),
        ApiErrorId.ERR_INVALID_TOOL_STATE.value,
    )

    after = fixtures.read_tool(tool["id"])
    assert after["status"] == "MOUNTED", (
        f"Expected the die to stay MOUNTED, got {after['status']}"
    )
    assert after["mounted_press_code"] == "PRESS-5", (
        f"Expected mounted_press_code still PRESS-5, got {after['mounted_press_code']}"
    )
    assert after["version"] == 2, (
        f"Two refusals must leave the version at 2, got {after['version']}"
    )


def test_worn_die_refuses_a_second_condemn_and_a_remount(engineer_headers):
    """A worn die can only be reground; condemning or mounting it again is refused.

    PRD: "The operator route is a `ProcessEngineer` or `QualityInspector` condemning a chipped or cracked die with a supplied `reason`: `status` becomes `WORN`, that `reason` is recorded as `condemn_reason`, `mounted_press_code` is cleared, and every production lot on that set in `process_state` `SETUP` moves, in ascending `created_at` order, to `disposition` `HOLD` with `hold_source` `TOOL_WEAR`."

    PRD: "A heading tool must be `AVAILABLE` to mount, `MOUNTED` to condemn, and `WORN` to regrind — otherwise `ERR_INVALID_TOOL_STATE` (409)."

    Design: Corner/errors/tool_transition_guards_reject_every_out_of_order_verb
    """
    tool = _register_die(engineer_headers)
    fixtures.mount_tool(tool["id"], press_code="PRESS-5")
    worn = validate_success(
        api_client.condemn_heading_tool(
            tool["id"], {"reason": "CHIPPED_STATION_2"}, INSPECTOR_1
        )
    )
    assert worn["status"] == "WORN", f"Expected status WORN, got {worn['status']}"
    assert worn["condemn_reason"] == "CHIPPED_STATION_2", (
        f"Expected condemn_reason CHIPPED_STATION_2, got {worn['condemn_reason']}"
    )
    assert not worn["mounted_press_code"], (
        f"mounted_press_code must be cleared on condemnation, got "
        f"{worn['mounted_press_code']}"
    )

    validate_error(
        api_client.condemn_heading_tool(
            tool["id"], {"reason": "CRACKED_STATION_3"}, INSPECTOR_1
        ),
        ApiErrorId.ERR_INVALID_TOOL_STATE.value,
    )
    validate_error(
        api_client.mount_heading_tool(
            tool["id"], {"press_code": "PRESS-5"}, engineer_headers
        ),
        ApiErrorId.ERR_INVALID_TOOL_STATE.value,
    )

    after = fixtures.read_tool(tool["id"])
    assert after["status"] == "WORN", (
        f"Expected the die to stay WORN, got {after['status']}"
    )
    assert after["condemn_reason"] == "CHIPPED_STATION_2", (
        f"The refused condemnation must not overwrite condemn_reason, got "
        f"{after['condemn_reason']}"
    )
    assert after["version"] == worn["version"], (
        f"Two refusals must not bump the version, got {after['version']}"
    )


def test_regrind_of_a_zero_piece_cycle_recomputes_the_budgets_then_refuses_a_repeat(
    engineer_headers,
):
    """The one legal regrind closes an empty cycle and leaves no conservative life.

    PRD: "When `regrind_count` is still below `max_regrinds`, the set goes `WORN → AVAILABLE`: the open cycle's `cumulative_pieces_current_cycle` is appended to `cycle_pieces_history`, `completed_cycle_count` and `regrind_count` each increment by 1, `cumulative_pieces_current_cycle` resets to zero, `observed_avg_cycle_pieces`, `rated_derated_life_pieces` and `conservative_life_pieces` are all recomputed, `condemn_reason` is cleared, and the set's `version` increments by 1 — closing the cycle `AVAILABLE → MOUNTED → WORN → AVAILABLE`."

    PRD: "`rated_derated_life_pieces` is the nameplate `rated_life_pieces` multiplied by one minus 0.15 for each completed regrind — that is, by one minus the product of `regrind_count` and 0.15 — with the result truncated downward to a whole number of pieces."

    PRD: "Once at least one cycle has closed, `observed_avg_cycle_pieces` is the sum of every entry in `cycle_pieces_history` divided by `completed_cycle_count`, rounded half up to two decimal places, and `conservative_life_pieces` is the smaller of `rated_derated_life_pieces` and 0.90 multiplied by `observed_avg_cycle_pieces`, truncated downward to a whole number of pieces."

    PRD: "A heading tool must be `AVAILABLE` to mount, `MOUNTED` to condemn, and `WORN` to regrind — otherwise `ERR_INVALID_TOOL_STATE` (409)."

    Design: Corner/errors/tool_transition_guards_reject_every_out_of_order_verb
    """
    tool = _register_die(engineer_headers)
    fixtures.mount_tool(tool["id"], press_code="PRESS-5")
    fixtures.condemn_tool(tool["id"], reason="CHIPPED_STATION_2")

    reground = validate_success(
        api_client.regrind_heading_tool(tool["id"], engineer_headers)
    )
    assert reground["status"] == "AVAILABLE", (
        f"Expected status AVAILABLE after the regrind, got {reground['status']}"
    )
    assert reground["regrind_count"] == 1, (
        f"Expected regrind_count 1, got {reground['regrind_count']}"
    )
    assert reground["cycle_pieces_history"] == [0], (
        f"Expected the empty cycle appended as [0], got "
        f"{reground['cycle_pieces_history']}"
    )
    assert reground["completed_cycle_count"] == 1, (
        f"Expected completed_cycle_count 1, got {reground['completed_cycle_count']}"
    )
    assert reground["cumulative_pieces_current_cycle"] == 0, (
        f"Expected the open cycle reset to zero, got "
        f"{reground['cumulative_pieces_current_cycle']}"
    )
    assert reground["rated_derated_life_pieces"] == 102000, (
        f"Expected rated_derated_life_pieces 102000 (120000 * 0.85), got "
        f"{reground['rated_derated_life_pieces']}"
    )
    assert reground["observed_avg_cycle_pieces"] == pytest.approx(0.0, abs=0.001), (
        f"Expected observed_avg_cycle_pieces 0.00, got "
        f"{reground['observed_avg_cycle_pieces']}"
    )
    assert reground["conservative_life_pieces"] == 0, (
        f"Expected conservative_life_pieces 0 from a zero-piece average, got "
        f"{reground['conservative_life_pieces']}"
    )
    assert not reground["condemn_reason"], (
        f"condemn_reason must be cleared by the regrind, got "
        f"{reground['condemn_reason']}"
    )

    # The die is AVAILABLE again, not WORN, so the immediate second regrind is refused.
    validate_error(
        api_client.regrind_heading_tool(tool["id"], engineer_headers),
        ApiErrorId.ERR_INVALID_TOOL_STATE.value,
    )
    after = fixtures.read_tool(tool["id"])
    assert after["regrind_count"] == 1, (
        f"The refused regrind must not advance regrind_count, got "
        f"{after['regrind_count']}"
    )
    assert after["cycle_pieces_history"] == [0], (
        f"The refused regrind must not append another cycle, got "
        f"{after['cycle_pieces_history']}"
    )
    assert after["version"] == reground["version"], (
        f"The refused regrind must not bump the version, got {after['version']}"
    )
