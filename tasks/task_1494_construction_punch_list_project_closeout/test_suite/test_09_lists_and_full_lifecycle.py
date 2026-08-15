"""List/pagination behavior, reverse-FK filters, and the full-lifecycle drive that
captures every resource's initial state."""
from test_helpers import (
    TEST_USERS,
    api_client,
    approve_doc,
    approve_release,
    begin_punch,
    complete_walk,
    conduct_training,
    create_item,
    create_release,
    create_warranty_case_payload,
    decide_waiver,
    drive_to_closeout,
    drive_to_substantially_complete,
    get_project,
    make_gc_inspector_headers,
    mark_ready,
    new_project,
    new_trade,
    schedule_training,
    schedule_walk,
    set_clock,
    submit_doc,
    submit_waiver,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["gc_pm_headers"]
INSP = TEST_USERS["gc_inspector_headers"]
OWNER = TEST_USERS["owner_rep_headers"]


class TestPagination:

    def test_pagination_on_punch_items_list(self):
        """PRD §2.3: "`limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` states how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/pagination_on_punch_items_list
        """
        project = new_project(name="Proj")
        trade = new_trade(project["id"])
        begin_punch(project["id"])
        for idx in range(1, 13):
            create_item(project["id"], trade["id"], title=f"I{idx:02d}",
                        location_area=f"R{idx:02d}", photo_ref=f"i{idx:02d}")

        page1, meta1 = validate_paginated(
            api_client.list_punch_items(INSP, params={"project_id": project["id"]})
        )
        assert len(page1) == 10
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api_client.list_punch_items(
                INSP, params={"project_id": project["id"], "limit": 10, "offset": 10}
            )
        )
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestReverseFkFilters:

    def test_filtered_lists_reverse_fk_lookup(self):
        """PRD §2.3: "List endpoints additionally accept resource-appropriate equality filters — depending on the resource, some combination of `project_id`, `trade_package_id`, `lead_inspector_id`, `status`, `severity`, `punch_walk_id`, `doc_type`, and `kind` — each narrowing the result set before pagination is applied."

        Design: Corner/endpoints/filtered_lists_reverse_fk_lookup
        """
        project = new_project(name="Proj")
        trade_a = new_trade(project["id"], trade_name="ELECTRICAL", subcontractor_org="SparkyCo")
        trade_b = new_trade(project["id"], trade_name="PLUMBING", subcontractor_org="PipeCo")
        begin_punch(project["id"])
        create_item(project["id"], trade_a["id"], title="A1", severity="MINOR",
                    location_area="R1", photo_ref="a1")
        create_item(project["id"], trade_a["id"], title="A2", severity="MAJOR",
                    location_area="R2", photo_ref="a2")
        create_item(project["id"], trade_b["id"], title="B1", severity="MINOR",
                    location_area="R3", photo_ref="b1")

        _, meta_a = validate_paginated(
            api_client.list_punch_items(PM, params={"trade_package_id": trade_a["id"]})
        )
        assert meta_a["total_count"] == 2

        _, meta_b = validate_paginated(
            api_client.list_punch_items(
                PM, params={"trade_package_id": trade_b["id"], "severity": "MINOR"}
            )
        )
        assert meta_b["total_count"] == 1

        trades, meta_t = validate_paginated(
            api_client.list_trade_packages(PM, params={"project_id": project["id"]})
        )
        assert meta_t["total_count"] == 2
        assert {t["id"] for t in trades} == {trade_a["id"], trade_b["id"]}


class TestFullLifecycleInitialStates:

    def test_new_entities_start_in_initial_states(self):
        """PRD §3.1: "A new project begins in `MOBILIZED`."
        PRD §3.1: "A fresh package starts with `lien_waiver_status` at `NONE`, `open_item_count` at zero, and every derived flag — `has_completed_walk`, `om_doc_approved`, `warranty_doc_approved`, `asbuilt_doc_approved`, `has_conducted_training`, and `closeout_ready` — false."
        PRD §3.2: "A newly scheduled walk sits in `SCHEDULED`."
        PRD §3.2: "A new item starts `OPEN` and immediately blocks: the project's counter for that severity (`open_life_safety_count`, `open_major_count`, or `open_minor_count`) and the responsible trade's `open_item_count` each increase by one, and the eligibility flags of §2.8 are recomputed."
        PRD §3.5: "Approval moves the document from `SUBMITTED` to `APPROVED`, flips the trade's corresponding flag — `om_doc_approved`, `warranty_doc_approved`, or `asbuilt_doc_approved` according to `doc_type` — and recomputes `closeout_ready`."
        PRD §3.5: "Each accepted submission is numbered by the server: its `revision` is the count of prior documents for the same trade and document type, plus one."
        PRD §3.5: "The count is stored, the session moves from `SCHEDULED` to `CONDUCTED`, the trade's `has_conducted_training` flips to true, and `closeout_ready` is recomputed."
        PRD §3.6: "A created release starts in `REQUESTED`, and its creation increments the project's `version`."
        PRD §3.7: "The case starts in `REPORTED`, stamps `reported_at` with the logical clock, and leaves `sla_due_at` null until triage."

        Design: Corner/state_machines/new_entities_start_in_initial_states
        """
        project = new_project(name="Proj")
        assert project["status"] == "MOBILIZED"

        trade = new_trade(project["id"])
        assert trade["lien_waiver_status"] == "NONE"
        assert trade["open_item_count"] == 0
        assert trade["closeout_ready"] is False

        begin_punch(project["id"])
        walk = schedule_walk(project["id"], trade["id"], "insp-lead-1",
                             "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
        assert walk["status"] == "SCHEDULED"

        set_clock("2026-08-03T10:00:00Z")
        complete_walk(walk["id"])

        item = create_item(project["id"], trade["id"], title="Paint", photo_ref="i1")
        assert item["status"] == "OPEN"

        doc = submit_doc(project["id"], trade["id"], "OM_MANUAL", "om-ref")
        assert doc["status"] == "SUBMITTED"
        assert doc["revision"] == 1

        mark_ready(item["id"], trade["id"])
        validate_success(api_client.verify_punch_item(
            item["id"], make_gc_inspector_headers("insp-9")
        ), 200)

        ctx = {"project": get_project(project["id"]), "trade": trade}
        drive_to_substantially_complete(ctx, sc_clock="2026-08-03T10:00:00Z")

        session = schedule_training(project["id"], trade["id"], location_room="TR-1",
                                    scheduled_start="2026-08-10T09:00:00Z",
                                    scheduled_end="2026-08-10T10:00:00Z")
        assert session["status"] == "SCHEDULED"

        reduction = create_release(project["id"], "REDUCTION")
        assert reduction["status"] == "REQUESTED"

        drive_to_closeout(ctx)
        doc2 = submit_doc(project["id"], trade["id"], "WARRANTY_DOC", "wd-ref")
        doc3 = submit_doc(project["id"], trade["id"], "AS_BUILT", "ab-ref")
        approve_doc(doc["id"])
        approve_doc(doc2["id"])
        approve_doc(doc3["id"])
        submit_waiver(trade["id"])
        decide_waiver(trade["id"], "ACCEPT")
        set_clock("2026-08-10T09:00:00Z")
        conducted = conduct_training(session["id"], attendee_count=2)
        assert conducted["status"] == "CONDUCTED"

        final = create_release(project["id"], "FINAL")
        assert final["status"] == "REQUESTED"
        approve_release(final["id"])
        closed = validate_success(api_client.close_project(project["id"], PM), 200)
        assert closed["status"] == "CLOSED"

        case = validate_success(api_client.create_warranty_case(
            create_warranty_case_payload(project["id"], title="Drip", description="sink"),
            OWNER,
        ), 201)
        assert case["status"] == "REPORTED"
