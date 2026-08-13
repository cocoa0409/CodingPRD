"""Special stain ordering: state gates, cold-ischemia gate, reflex rule
firing, dedupe and chain-depth guards, and the reflex-to-deadline cascade."""
from test_helpers import (
    ADMIN_HEADERS,
    HISTOTECH_HEADERS,
    ApiErrorId,
    accession_specimen,
    assert_instant_equal,
    assign_case,
    create_block,
    create_case,
    create_patient,
    create_pathologist,
    create_reflex_rule,
    create_slide,
    create_stain_order,
    embed_block,
    get_case,
    get_reflex_rule,
    get_stain_order,
    gross_specimen,
    make_pathologist_headers,
    result_stain_order,
    setup_pending_signout_case,
    setup_qc_passed_case,
    setup_workup_case,
    sign_out_case,
    start_stain_order,
    submit_for_signout,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_stain_result_before_start_rejected(api):
    """PRD §3.4: "Any start, result, or cancel attempted from a disallowed
    state is rejected with `ERR_STAIN_WRONG_STATE` (HTTP 409)."
    PRD §3.4: "result entry moves `IN_PROGRESS → RESULTED`, recording the
    supplied `result_value` (`POSITIVE`, `NEGATIVE`, or `EQUIVOCAL`) and
    stamping `resulted_at`."

    Design: Corner/errors/stain_result_before_start_rejected
    """
    ctx = setup_workup_case(mrn="MRN-R4", specimen_type="RESECTION", num_blocks=1)
    pathologist = create_pathologist(full_name="Dr S")
    order = create_stain_order(
        ctx["case"]["id"], ctx["blocks"][0]["id"], "MUCIN", pathologist["id"]
    )
    resp = api.result_stain_order(
        order["id"], {"result_value": "POSITIVE"}, HISTOTECH_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_STAIN_WRONG_STATE)
    after = get_stain_order(order["id"])
    assert after["status"] == "ORDERED"
    assert after["result_value"] is None


def test_stain_order_on_final_case_rejected(api):
    """PRD §3.4: "Ordering requires the case to be in `WORKUP`,
    `PENDING_SIGNOUT`, or `AMENDING` (otherwise `ERR_CASE_NOT_ORDERABLE`,
    HTTP 409)"

    Design: Corner/errors/stain_order_on_final_case_rejected
    """
    ctx = setup_qc_passed_case(mrn="MRN-RB", specimen_type="RESECTION")
    case_id = ctx["case"]["id"]
    assign_case(case_id, ctx["pathologist"]["id"])
    submit_for_signout(case_id, ctx["pathologist"]["id"])
    sign_out_case(case_id, ctx["pathologist"]["id"])

    resp = api.create_stain_order(
        case_id,
        {"block_id": ctx["block"]["id"], "stain_type": "MUCIN"},
        make_pathologist_headers(ctx["pathologist"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_ORDERABLE)


def test_stain_order_block_from_other_case_rejected(api):
    """PRD §3.4: "the referenced block must belong to a specimen of the same
    case (otherwise `ERR_BLOCK_NOT_IN_CASE`, HTTP 422)."

    Design: Corner/validations/stain_order_block_from_other_case_rejected
    """
    pathologist = create_pathologist(full_name="Dr X")
    ctx_a = setup_workup_case(mrn="MRN-VC", specimen_type="RESECTION", num_blocks=1)
    # Second case for the same patient, worked up to WORKUP with no blocks.
    patient = ctx_a["patient"]
    case_b = create_case(patient["id"], subspecialty="GI")
    sp_b = accession_specimen(
        case_b["id"], patient_mrn="MRN-VC", specimen_type="RESECTION",
        anatomical_site="Ileum",
    )
    # Gross the second specimen so case B is in WORKUP (an orderable state).
    gross_specimen(sp_b["id"])

    resp = api.create_stain_order(
        case_b["id"],
        {"block_id": ctx_a["blocks"][0]["id"], "stain_type": "MUCIN"},
        make_pathologist_headers(pathologist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BLOCK_NOT_IN_CASE)
    _orders, meta = validate_paginated(
        api.list_stain_orders(ADMIN_HEADERS, params={"case_id": case_b["id"]})
    )
    assert meta["total_count"] == 0, "no StainOrder row may be created"


def test_stain_order_create_pulls_back_pending_signout(api):
    """PRD §3.4: "Ordering a stain while the case is `PENDING_SIGNOUT` pulls
    the case back to `WORKUP`, mirroring the QC-failure pull-back"
    PRD §3.4: "The server stamps `ordered_by_pathologist_id` from the
    authenticated caller and leaves `reflex_rule_id` and
    `parent_stain_order_id` null on a manual order."

    Design: Corner/state_machines/stain_order_create_pulls_back_pending_signout
    """
    ctx = setup_pending_signout_case(mrn="MRN-S4", specimen_type="RESECTION")
    case_id = ctx["case"]["id"]
    assert get_case(case_id)["status"] == "PENDING_SIGNOUT"

    resp = api.create_stain_order(
        case_id,
        {"block_id": ctx["block"]["id"], "stain_type": "MUCIN"},
        make_pathologist_headers(ctx["pathologist"]["id"]),
    )
    order = validate_success(resp, expected_status=201)
    assert order["status"] == "ORDERED"
    assert order["ordered_by_pathologist_id"] == ctx["pathologist"]["id"]
    assert order["reflex_rule_id"] is None
    assert order["parent_stain_order_id"] is None
    assert get_case(case_id)["status"] == "WORKUP", (
        "the new order pulled the case back to WORKUP"
    )


def test_cold_ischemia_truncates_seconds_and_limits_at_60(api):
    """PRD §3.2: "computes `cold_ischemia_minutes` as the whole minutes from
    collection to receipt truncated toward zero — a value that later gates
    cold-sensitive stains"
    PRD §3.4: "Two cold-sensitive stains carry an ischemia gate: `HER2_IHC`
    requires the target block's specimen to have `cold_ischemia_minutes` of at
    most 60 minutes, and `PD_L1` requires at most 90 minutes, with violations
    rejected as `ERR_COLD_ISCHEMIA_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/cold_ischemia_truncates_seconds_and_limits_at_60
    """
    pathologist = create_pathologist(full_name="Dr Cold")
    patient = create_patient(mrn="MRN-V3", full_name="Val Three")
    case = create_case(patient["id"], subspecialty="GI")
    # Specimen at exactly 60 computed minutes (60m59s truncates to 60).
    sp60 = accession_specimen(
        case["id"],
        patient_mrn="MRN-V3",
        specimen_type="RESECTION",
        anatomical_site="Breast",
        collection_datetime="2026-08-03T09:00:30Z",
        received_datetime="2026-08-03T10:01:29Z",
    )
    assert sp60["cold_ischemia_minutes"] == 60, "seconds truncate toward zero"
    gross_specimen(sp60["id"], gross_description="lumpectomy")
    b60 = embed_block(create_block(sp60["id"], block_label="B1")["id"])
    # Specimen at 61 computed minutes.
    sp61 = accession_specimen(
        case["id"],
        patient_mrn="MRN-V3",
        specimen_type="RESECTION",
        anatomical_site="Breast",
        collection_datetime="2026-08-03T09:00:00Z",
        received_datetime="2026-08-03T10:01:00Z",
    )
    assert sp61["cold_ischemia_minutes"] == 61
    gross_specimen(sp61["id"], gross_description="lumpectomy 2")
    b61 = embed_block(create_block(sp61["id"], block_label="B1")["id"])

    ok = create_stain_order(case["id"], b60["id"], "HER2_IHC", pathologist["id"])
    assert ok["status"] == "ORDERED", "60 minutes is at most the 60-minute limit"

    resp = api.create_stain_order(
        case["id"],
        {"block_id": b61["id"], "stain_type": "HER2_IHC"},
        make_pathologist_headers(pathologist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COLD_ISCHEMIA_EXCEEDED)


def test_duplicate_labels_and_active_reflex_uniqueness(api):
    """PRD §3.3: "Each block carries a `block_label` unique within its
    specimen, with duplicates rejected by `ERR_DUPLICATE_BLOCK_LABEL`
    (HTTP 409)."
    PRD §3.3: "Slides are ordered by a `Histotech` against an `EMBEDDED` block,
    each with a `slide_label` unique within the block
    (`ERR_DUPLICATE_SLIDE_LABEL`, HTTP 409, on collision)"
    PRD §3.4: "Among rules with `active` true, the triple of trigger stain,
    trigger result, and follow-up stain must be unique; a colliding create or
    update is rejected with `ERR_DUPLICATE_REFLEX_RULE` (HTTP 409)."
    PRD §3.4: "Deactivation is a separate action that sets `active` to false;
    a deactivated rule never fires."

    Design: Corner/validations/duplicate_labels_and_active_reflex_uniqueness
    """
    ctx = setup_workup_case(mrn="MRN-VB", num_blocks=1)
    block = ctx["blocks"][0]
    create_slide(block["id"], slide_label="S-1")

    resp = api.create_block(ctx["specimen"]["id"], {"block_label": "A1"}, HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BLOCK_LABEL)

    resp = api.create_slide(block["id"], {"slide_label": "S-1"}, HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SLIDE_LABEL)

    rule = create_reflex_rule(name="orig")
    resp = api.create_reflex_rule(
        {
            "name": "dupe",
            "trigger_stain_type": "HER2_IHC",
            "trigger_result": "POSITIVE",
            "followup_stain_type": "KI67",
            "priority": 2,
        },
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REFLEX_RULE)

    # The triple is unique only among ACTIVE rules: after deactivation the same
    # triple is accepted again.
    resp = api.deactivate_reflex_rule(rule["id"], ADMIN_HEADERS)
    validate_success(resp, expected_status=200)
    reborn = create_reflex_rule(name="reborn", priority=2)
    assert reborn["active"] is True
    assert get_reflex_rule(rule["id"])["active"] is False


def test_reflex_rule_fires_once_per_case(api):
    """PRD §3.4: "Each rule fires at most once per case: if any stain order of
    the case already carries that rule in its `reflex_rule_id`, the rule is
    skipped."

    Design: Corner/calculations/reflex_rule_fires_once_per_case
    """
    pathologist = create_pathologist(full_name="Dr Reflex")
    ctx = setup_workup_case(mrn="MRN-C3", specimen_type="RESECTION", num_blocks=1)
    case_id = ctx["case"]["id"]
    block_id = ctx["blocks"][0]["id"]
    rule = create_reflex_rule(name="HER2->KI67")
    so1 = create_stain_order(case_id, block_id, "HER2_IHC", pathologist["id"])
    so2 = create_stain_order(case_id, block_id, "HER2_IHC", pathologist["id"])
    start_stain_order(so1["id"])
    start_stain_order(so2["id"])

    result_stain_order(so1["id"], "POSITIVE")
    result_stain_order(so2["id"], "POSITIVE")

    assert get_stain_order(so1["id"])["status"] == "RESULTED"
    assert get_stain_order(so2["id"])["status"] == "RESULTED"

    children, meta = validate_paginated(
        api.list_stain_orders(
            ADMIN_HEADERS, params={"case_id": case_id, "reflex_rule_id": rule["id"]}
        )
    )
    assert meta["total_count"] == 1, "the rule fires at most once per case"
    assert children[0]["parent_stain_order_id"] == so1["id"]


def test_reflex_chain_depth_guard_stops_at_depth_3(api):
    """PRD §3.4: "Firing is also depth-guarded along the
    `parent_stain_order_id` ancestry chain: a manual order sits at depth 0, its
    reflex children at depths 1 through 3, and an order already at depth 3
    spawns nothing."

    Design: Corner/calculations/reflex_chain_depth_guard_stops_at_depth_3
    """
    pathologist = create_pathologist(full_name="Dr Chain")
    ctx = setup_workup_case(mrn="MRN-C4", specimen_type="RESECTION", num_blocks=1)
    case_id = ctx["case"]["id"]
    block_id = ctx["blocks"][0]["id"]
    create_reflex_rule(name="R1", trigger_stain_type="HER2_IHC", followup_stain_type="KI67")
    create_reflex_rule(name="R2", trigger_stain_type="KI67", followup_stain_type="PAX5")
    create_reflex_rule(name="R3", trigger_stain_type="PAX5", followup_stain_type="CD20")
    create_reflex_rule(name="R4", trigger_stain_type="CD20", followup_stain_type="MUCIN")
    root = create_stain_order(case_id, block_id, "HER2_IHC", pathologist["id"])
    start_stain_order(root["id"])

    def _only_child_of(parent_id):
        data, meta = validate_paginated(
            api.list_stain_orders(
                ADMIN_HEADERS, params={"parent_stain_order_id": parent_id}
            )
        )
        assert meta["total_count"] == 1, f"expected one child of {parent_id}"
        return data[0]

    result_stain_order(root["id"], "POSITIVE")
    depth1 = _only_child_of(root["id"])
    assert depth1["stain_type"] == "KI67"
    start_stain_order(depth1["id"])
    result_stain_order(depth1["id"], "POSITIVE")
    depth2 = _only_child_of(depth1["id"])
    assert depth2["stain_type"] == "PAX5"
    start_stain_order(depth2["id"])
    result_stain_order(depth2["id"], "POSITIVE")
    depth3 = _only_child_of(depth2["id"])
    assert depth3["stain_type"] == "CD20"
    start_stain_order(depth3["id"])
    result_stain_order(depth3["id"], "POSITIVE")

    # The depth-3 CD20 order spawns nothing even though rule R4 matches.
    data, meta = validate_paginated(
        api.list_stain_orders(ADMIN_HEADERS, params={"parent_stain_order_id": depth3["id"]})
    )
    assert meta["total_count"] == 0, "an order at depth 3 spawns nothing"
    all_orders, all_meta = validate_paginated(
        api.list_stain_orders(ADMIN_HEADERS, params={"case_id": case_id, "limit": 100})
    )
    assert all_meta["total_count"] == 4, "manual root plus three reflex levels"
    assert all(o["stain_type"] != "MUCIN" for o in all_orders)


def test_stain_result_reflex_complexity_cascade_child_order(api):
    """PRD §3.4: "The candidates are all `active` `ReflexRule` rows whose
    `trigger_stain_type` equals the resulted order's stain type and whose
    `trigger_result` equals the entered `result_value`."
    PRD §3.4: "A rule that fires creates a child order in `ORDERED` status with
    the rule's `followup_stain_type`, the same `block_id` as the resulted
    order, `reflex_rule_id` and `parent_stain_order_id` set to the rule and the
    triggering order respectively, and `ordered_by_pathologist_id` null to mark
    its system origin."

    Design: Difficulty/transitive_cascade/stain_result_reflex_complexity_cascade
    """
    pathologist = create_pathologist(full_name="Dr Cascade")
    ctx = setup_workup_case(
        mrn="MRN-500",
        tat_mode="CALENDAR",
        specimen_type="RESECTION",
        anatomical_site="Right colon",
        container_count=2,
        num_blocks=2,
    )
    case_id = ctx["case"]["id"]
    b1, b2 = ctx["blocks"]
    create_slide(b1["id"], slide_label="A1-1")
    create_slide(b1["id"], slide_label="A1-2")
    create_slide(b2["id"], slide_label="A2-1")
    rule = create_reflex_rule(name="HER2 pos reflex KI67")
    order = create_stain_order(case_id, b1["id"], "HER2_IHC", pathologist["id"])
    start_stain_order(order["id"])
    resulted = result_stain_order(order["id"], "POSITIVE")
    assert resulted["status"] == "RESULTED"
    assert resulted["result_value"] == "POSITIVE"
    assert resulted["resulted_at"] is not None

    children, meta = validate_paginated(
        api.list_stain_orders(
            ADMIN_HEADERS, params={"parent_stain_order_id": order["id"]}
        )
    )
    assert meta["total_count"] == 1, "exactly one reflex child order"
    child = children[0]
    assert child["stain_type"] == "KI67"
    assert child["status"] == "ORDERED"
    assert child["reflex_rule_id"] == rule["id"]
    assert child["parent_stain_order_id"] == order["id"]
    assert child["block_id"] == b1["id"]
    assert child["ordered_by_pathologist_id"] is None


def test_stain_result_reflex_complexity_cascade_case_upgrade(api):
    """PRD §3.4: "Each created child then drives the case complexity cascade
    exactly as a manual order would."
    PRD §3.3: "plus 2.0 for every stain order of the case in `ORDERED`,
    `IN_PROGRESS`, or `RESULTED`."
    PRD §3.3: "on any change of `complexity_class` the `turnaround_deadline` is
    recomputed and `tat_breached` re-evaluated, since the deadline allowance
    depends on the class."

    Design: Difficulty/transitive_cascade/stain_result_reflex_complexity_cascade
    """
    pathologist = create_pathologist(full_name="Dr Cascade")
    ctx = setup_workup_case(
        mrn="MRN-500",
        tat_mode="CALENDAR",
        specimen_type="RESECTION",
        anatomical_site="Right colon",
        container_count=2,
        num_blocks=2,
    )
    case_id = ctx["case"]["id"]
    b1, b2 = ctx["blocks"]
    create_slide(b1["id"], slide_label="A1-1")
    create_slide(b1["id"], slide_label="A1-2")
    create_slide(b2["id"], slide_label="A2-1")
    create_reflex_rule(name="HER2 pos reflex KI67")
    order = create_stain_order(case_id, b1["id"], "HER2_IHC", pathologist["id"])
    start_stain_order(order["id"])
    # Pre-result: 3 + 2*1.0 + 3*0.5 + 1*2.0 = 8.5 -> MODERATE.
    pre = get_case(case_id)
    assert pre["complexity_score"] == 8.5
    assert pre["complexity_class"] == "MODERATE"

    result_stain_order(order["id"], "POSITIVE")

    post = get_case(case_id)
    # The reflex child lifts the stain term: 8.5 + 2.0 = 10.5 -> COMPLEX.
    assert post["complexity_score"] == 10.5
    assert post["complexity_class"] == "COMPLEX"
    # COMPLEX allowance 120h from tat_base 2026-08-03T10:00:00Z.
    assert_instant_equal(
        post["turnaround_deadline"], "2026-08-08T10:00:00Z", "recomputed deadline"
    )


def test_occ_stale_reflex_rule_update_returns_412(api):
    """PRD §2.8: "The reflex-rule update endpoint (`PUT
    /pathology/reflex-rules/{id}`) requires the request to carry
    `expected_reflex_rule_version`, holding the rule's `version` as last read.
    A mismatch with the rule's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing the client from clobbering a
    rule definition it never observed."

    Design: Corner/complexity_layers/occ_stale_reflex_rule_update_returns_412
    """
    rule = create_reflex_rule(name="R")
    observed_version = rule["version"]

    resp = api.update_reflex_rule(
        rule["id"],
        {"expected_reflex_rule_version": observed_version, "priority": 5},
        ADMIN_HEADERS,
    )
    updated = validate_success(resp, expected_status=200)
    assert updated["priority"] == 5

    resp = api.update_reflex_rule(
        rule["id"],
        {"expected_reflex_rule_version": observed_version, "priority": 9},
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = get_reflex_rule(rule["id"])
    assert after["priority"] == 5, "the stale PUT changed nothing"
    assert after["version"] == updated["version"], (
        "version advanced exactly once, by the successful PUT"
    )


def test_reflex_rule_create_forbidden_for_histotech(api, histotech_headers):
    """PRD §2.1: "A request whose role is not on the endpoint's authorized list
    — or that fails an entity-backed ownership check — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.4: "Reflex rules themselves are `LabAdmin` configuration."

    Design: Corner/rbac/reflex_rule_create_forbidden_for_histotech
    """
    resp = api.create_reflex_rule(
        {
            "name": "x",
            "trigger_stain_type": "HER2_IHC",
            "trigger_result": "POSITIVE",
            "followup_stain_type": "KI67",
            "priority": 1,
        },
        histotech_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
