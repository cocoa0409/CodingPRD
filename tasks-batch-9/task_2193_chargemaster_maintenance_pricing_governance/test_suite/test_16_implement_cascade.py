"""The four-hop cascade riding on a change-request implementation."""
from test_helpers import (
    api_client, validate_success,
    setup_northgate_published_scenario,
    create_change_request, decide_change_request, read_change_request,
    read_item, read_facility, read_department, read_file, implement_change_request,
    ANALYST, APPROVER,
)


def _two_approved_requests(s):
    """CR-A (PRICE_CHANGE to 70000) and CR-B (DEACTIVATION), both APPROVED on the same item."""
    item_id = s["item"]["id"]
    cr_a = create_change_request(
        s, item_id, "PRICE_CHANGE",
        justification="Reagent vendor cost increase for the FY2027 contract year",
        proposed_cost_basis_cents=70000,
    )
    cr_b = create_change_request(
        s, item_id, "DEACTIVATION",
        justification="Assay retired by the reference laboratory effective Q1 2027",
    )
    decide_change_request(cr_a["id"], "REVIEW", ANALYST,
                         decision_note="price change review opened")
    decide_change_request(cr_b["id"], "REVIEW", ANALYST,
                         decision_note="deactivation review opened")
    v_for_a = read_item(item_id)["version"]
    cr_a = validate_success(
        api_client.approve_change_request(
            cr_a["id"],
            {"expected_charge_item_version": v_for_a,
             "decision_note": "price change approved"},
            APPROVER,
        ),
        200,
    )
    v_for_b = read_item(item_id)["version"]
    cr_b = validate_success(
        api_client.approve_change_request(
            cr_b["id"],
            {"expected_charge_item_version": v_for_b,
             "decision_note": "deactivation approved"},
            APPROVER,
        ),
        200,
    )
    return cr_a, cr_b, v_for_a, v_for_b


def test_implementation_mutates_the_item_then_supersedes_the_published_file():
    """PRD §3.10: "Supersession also arrives from outside: a `PUBLISHED` file transitions to
    `SUPERSEDED` whenever any `ACTIVE` charge item of its facility is mutated by a reprice, a
    change-request implementation, a code-cycle activation or rollback, or a lifecycle change,
    and in that case `superseded_by_file_id` stays null while the facility's
    `published_transparency_file_id` is cleared and `transparency_status` drops to
    `NEEDS_REFRESH`."
    PRD §3.5: "Four further cascade links fire on every successful implementation regardless
    of branch. The charge item has been mutated and its `version` has advanced. Every
    `TransparencyFile` of the facility whose `status` is `PUBLISHED` transitions to
    `SUPERSEDED`. The facility's `published_transparency_file_id` is cleared to null, its
    `transparency_status` set to `NEEDS_REFRESH`, its aggregates and `chargemaster_posture`
    recomputed, and `Facility.version` advanced by 1."

    Design: Difficulty/transitive_cascade/transitive_cascade__implement_item_supersedes_file_clears_facility_voids_sibling_request
    """
    s = setup_northgate_published_scenario()
    assert s["transparency_file"]["payer_column_count"] == 1
    assert s["transparency_file"]["included_item_count"] == 1
    assert s["facility"]["transparency_status"] == "CURRENT"
    facility_version_before = s["facility"]["version"]

    cr_a, _cr_b, v_for_a, _v_for_b = _two_approved_requests(s)
    assert cr_a["projected_gross_charge_cents"] == 168000
    assert cr_a["projected_markup_ratio_bp"] == 24000
    assert cr_a["pinned_charge_item_version"] == v_for_a + 1

    implemented = implement_change_request(
        cr_a["id"], implementation_note="applied the approved cost basis of 70000 cents"
    )
    assert implemented["status"] == "IMPLEMENTED"
    assert read_change_request(cr_a["id"])["status"] == "IMPLEMENTED"

    item = read_item(s["item"]["id"])
    assert item["cost_basis_cents"] == 70000
    assert item["gross_charge_cents"] == 168000
    assert item["prior_gross_charge_cents"] == 144000
    assert item["price_status"] == "PRICED_CURRENT"
    assert item["lifecycle_status"] == "ACTIVE"

    tfile = read_file(s["transparency_file"]["id"])
    assert tfile["status"] == "SUPERSEDED"
    assert tfile["superseded_by_file_id"] is None, (
        "an outside-driven supersession leaves superseded_by_file_id null"
    )

    facility = read_facility(s["facility"]["id"])
    assert facility["published_transparency_file_id"] is None
    assert facility["transparency_status"] == "NEEDS_REFRESH"
    assert facility["active_item_count"] == 1
    assert facility["aggregate_gross_charge_cents"] == 168000
    assert facility["aggregate_cost_basis_cents"] == 70000
    assert facility["aggregate_markup_ratio_bp"] == 24000
    assert facility["stale_price_item_count"] == 0
    assert facility["chargemaster_posture"] == "OPEN"
    assert facility["version"] > facility_version_before


def test_implementation_voids_the_sibling_approved_request_and_recounts_the_department():
    """PRD §3.5: "And every *other* change request with `status` `APPROVED` that targets the
    same `charge_item_id` and whose `pinned_charge_item_version` no longer equals the item's
    new version transitions `APPROVED → VOIDED_STALE`, advancing its own `version` by 1 and
    prompting a recomputation of the department's `open_request_count`."
    PRD §3.5: "`IMPLEMENTED`, `REJECTED`, `WITHDRAWN` and `VOIDED_STALE` are the four terminal
    states of a change request."
    PRD §2.11: "`open_request_count` (the number of its change requests whose `status` is one
    of `SUBMITTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED` or `APPROVED`)"

    Design: Difficulty/transitive_cascade/transitive_cascade__implement_item_supersedes_file_clears_facility_voids_sibling_request
    """
    s = setup_northgate_published_scenario()
    cr_a, cr_b, v_for_a, v_for_b = _two_approved_requests(s)
    assert v_for_b == v_for_a + 1, (
        "only the PRICE_CHANGE approval touches the item's pricing dimension"
    )
    assert cr_b["pinned_charge_item_version"] == v_for_b, (
        "a DEACTIVATION approval does not bump the item, so its pin equals the live version"
    )
    assert cr_b["pinned_charge_item_version"] == cr_a["pinned_charge_item_version"], (
        "both approvals pinned the same item version, which is what makes one of them stale"
    )
    assert read_department(s["department"]["id"])["open_request_count"] == 2

    implement_change_request(cr_a["id"], implementation_note="applied")

    voided = read_change_request(cr_b["id"])
    assert voided["status"] == "VOIDED_STALE"
    assert voided["pinned_charge_item_version"] == v_for_b, (
        "the pin is a historical record and is not rewritten by the voiding"
    )
    assert read_item(s["item"]["id"])["version"] == v_for_b + 1

    department = read_department(s["department"]["id"])
    assert department["open_request_count"] == 0, (
        "IMPLEMENTED and VOIDED_STALE are both terminal, so nothing is open"
    )
