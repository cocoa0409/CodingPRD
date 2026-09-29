"""Composite setup helpers.

Every helper builds its preconditions from scratch through the endpoints §4
declares, and uses the lenient success validator so that a broken precondition
surfaces as a setup failure rather than as a confusing assertion.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DISCIPLINE_ROLE
from .factories import (
    all_elements_passing,
    brief_decision_payload,
    cancel_plate_order_payload,
    clearance_payload,
    clock_payload,
    color_decision_payload,
    create_artwork_asset_payload,
    create_artwork_version_payload,
    create_brief_payload,
    create_error_escape_payload,
    create_inventory_runout_payload,
    create_marketing_claim_payload,
    create_plate_order_payload,
    create_printer_payload,
    create_printer_proof_payload,
    depletion_records_payload,
    disposition_payload,
    disposition_reversal_payload,
    dispute_payload,
    press_check_payload,
    recovery_claim_payload,
    release_payload,
    revise_payload,
    root_cause_payload,
    settle_payload,
    submit_payload,
    substrate_decision_payload,
    task_decision_payload,
    verify_elements_payload,
    waiver_payload,
)
from .test_users import TEST_USERS, make_printer_rep_headers

# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------


def coord():
    return TEST_USERS["coordinator_headers"]


def brand():
    return TEST_USERS["brand_reviewer_headers"]


def legal():
    return TEST_USERS["legal_reviewer_headers"]


def regulatory():
    return TEST_USERS["regulatory_reviewer_headers"]


def quality():
    return TEST_USERS["quality_reviewer_headers"]


def admin():
    return TEST_USERS["platform_admin_headers"]


def printer_as(printer):
    """PrinterRep is entity-backed: ownership-gated calls carry the printer id."""
    return make_printer_rep_headers(
        printer["id"] if isinstance(printer, dict) else printer
    )


def reviewer_for(discipline):
    role = DISCIPLINE_ROLE[discipline]
    return {
        "BrandReviewer": brand(),
        "LegalReviewer": legal(),
        "RegulatoryReviewer": regulatory(),
        "QualityReviewer": quality(),
    }[role]


def _id(row):
    return row["id"] if isinstance(row, dict) else row


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock(to_iso8601) -> dict:
    """Move the logical clock. Setting it mutates no domain entity."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), admin()))


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------


def new_brief(**overrides) -> dict:
    return get_success_data(
        api_client.create_brief(create_brief_payload(**overrides), coord())
    )


def read_brief(brief_id) -> dict:
    return get_success_data(api_client.get_brief(_id(brief_id), coord()))


def patch_brief(brief_id, payload) -> dict:
    return get_success_data(api_client.patch_brief(_id(brief_id), payload, coord()))


def decide_brief(brief_id, decision="APPROVED", **overrides) -> dict:
    return get_success_data(
        api_client.decide_brief(
            _id(brief_id), brief_decision_payload(decision, **overrides), regulatory()
        )
    )


def new_approved_brief(**overrides) -> dict:
    """A brief in APPROVED — the state every artwork submission is gated on."""
    brief = new_brief(**overrides)
    return decide_brief(brief["id"], "APPROVED")


# ---------------------------------------------------------------------------
# Marketing claims
# ---------------------------------------------------------------------------


def new_claim(**overrides) -> dict:
    return get_success_data(
        api_client.create_marketing_claim(
            create_marketing_claim_payload(**overrides), coord()
        )
    )


def read_claim(claim_id) -> dict:
    return get_success_data(api_client.get_marketing_claim(_id(claim_id), coord()))


def clear_claim(
    claim_id,
    cleared_from_utc="2026-07-01T00:00:00Z",
    cleared_until_utc="2027-07-01T00:00:00Z",
    **overrides,
) -> dict:
    return get_success_data(
        api_client.decide_claim_clearance(
            _id(claim_id),
            clearance_payload(
                "CLEARED",
                cleared_from_utc=cleared_from_utc,
                cleared_until_utc=cleared_until_utc,
                **overrides,
            ),
            legal(),
        )
    )


def reject_claim(claim_id, **overrides) -> dict:
    return get_success_data(
        api_client.decide_claim_clearance(
            _id(claim_id), clearance_payload("REJECTED", **overrides), legal()
        )
    )


def new_cleared_claim(
    cleared_from_utc="2026-07-01T00:00:00Z",
    cleared_until_utc="2027-07-01T00:00:00Z",
    **overrides,
) -> dict:
    """A CLEARED claim whose window comfortably contains the clock epoch."""
    claim = new_claim(**overrides)
    return clear_claim(
        claim["id"],
        cleared_from_utc=cleared_from_utc,
        cleared_until_utc=cleared_until_utc,
    )


# ---------------------------------------------------------------------------
# Artwork assets and versions
# ---------------------------------------------------------------------------


def new_asset(brief_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_artwork_asset(
            create_artwork_asset_payload(_id(brief_id), **overrides), coord()
        )
    )


def read_asset(asset_id) -> dict:
    return get_success_data(api_client.get_artwork_asset(_id(asset_id), coord()))


def new_version(asset, **overrides) -> dict:
    """Create the next version of an asset, pinning the asset's current version."""
    asset_row = asset if isinstance(asset, dict) else read_asset(asset)
    payload = create_artwork_version_payload(asset_row["version"], **overrides)
    return get_success_data(
        api_client.create_artwork_version(asset_row["id"], payload, coord())
    )


def read_version(version_id) -> dict:
    return get_success_data(api_client.get_artwork_version(_id(version_id), coord()))


def patch_version(version_id, payload) -> dict:
    return get_success_data(
        api_client.patch_artwork_version(_id(version_id), payload, coord())
    )


def set_version_elements(version_id, **element_overrides) -> dict:
    """Rewrite the version's mandatory element payload without rescoring it."""
    return patch_version(
        version_id, {"mandatory_elements": all_elements_passing(**element_overrides)}
    )


def verify(version_id, **overrides) -> dict:
    return get_success_data(
        api_client.verify_elements(
            _id(version_id), verify_elements_payload(**overrides), coord()
        )
    )


def revise(version_id, **overrides) -> dict:
    return get_success_data(
        api_client.revise_artwork_version(
            _id(version_id), revise_payload(**overrides), coord()
        )
    )


def submit(version_id, **overrides) -> dict:
    return get_success_data(
        api_client.submit_artwork_version(
            _id(version_id), submit_payload(**overrides), coord()
        )
    )


def release(version_id, **overrides) -> dict:
    return get_success_data(
        api_client.release_to_print(
            _id(version_id), release_payload(**overrides), coord()
        )
    )


# ---------------------------------------------------------------------------
# Element checks
# ---------------------------------------------------------------------------


def element_checks_for(version_id) -> list:
    """Every verdict row of a version, in the fixed element order."""
    return get_success_data(
        api_client.list_element_checks(
            coord(), params={"artwork_version_id": _id(version_id), "limit": 100}
        )
    )


def element_check_by_code(version_id, element_code) -> dict:
    rows = element_checks_for(version_id)
    matches = [row for row in rows if row["element_code"] == element_code]
    assert matches, f"no {element_code} verdict row for version {_id(version_id)}"
    return matches[-1]


def read_element_check(check_id) -> dict:
    return get_success_data(api_client.get_element_check(_id(check_id), coord()))


def waive_check(check_id, **overrides) -> dict:
    return get_success_data(
        api_client.waive_element_check(
            _id(check_id), waiver_payload(**overrides), regulatory()
        )
    )


# ---------------------------------------------------------------------------
# Review routes and tasks
# ---------------------------------------------------------------------------


def routes_for(version_id) -> list:
    return get_success_data(
        api_client.list_review_routes(
            coord(), params={"artwork_version_id": _id(version_id), "limit": 100}
        )
    )


def current_route(version_id) -> dict:
    """The newest routing pass of a version — routes are listed route_no ASC."""
    routes = routes_for(version_id)
    assert routes, f"no routing pass exists for version {_id(version_id)}"
    return routes[-1]


def read_route(route_id) -> dict:
    return get_success_data(api_client.get_review_route(_id(route_id), coord()))


def tasks_for_route(route_id) -> list:
    return get_success_data(
        api_client.list_review_tasks(
            coord(), params={"review_route_id": _id(route_id), "limit": 100}
        )
    )


def tasks_by_discipline(route_id) -> dict:
    """The four tasks of a pass, keyed by discipline.

    §4 makes the review-task list the only discovery channel for the tasks the
    submit cascade created.
    """
    return {task["discipline"]: task for task in tasks_for_route(route_id)}


def read_task(task_id) -> dict:
    return get_success_data(api_client.get_review_task(_id(task_id), coord()))


def decide_task(task, decision="APPROVED", headers=None, **overrides) -> dict:
    """Record a verdict, defaulting to the reviewer bound to the discipline."""
    task_row = task if isinstance(task, dict) else read_task(task)
    return get_success_data(
        api_client.decide_review_task(
            task_row["id"],
            task_decision_payload(decision, **overrides),
            headers or reviewer_for(task_row["discipline"]),
        )
    )


def decide_discipline(version_id, discipline, decision="APPROVED", **kwargs) -> dict:
    """Decide the named discipline's task on the version's current pass."""
    route = current_route(version_id)
    tasks = tasks_by_discipline(route["id"])
    assert discipline in tasks, f"pass has no {discipline} task"
    return decide_task(tasks[discipline], decision, **kwargs)


def approve_all_stages(version_id) -> dict:
    """Walk the frozen three-stage plan with four approving verdicts.

    Returns the route row as it stands after the final approval, i.e. after the
    approval cascade has run.
    """
    route = current_route(version_id)
    tasks = tasks_by_discipline(route["id"])
    decide_task(tasks["BRAND"], "APPROVED")
    decide_task(tasks["REGULATORY"], "APPROVED")
    decide_task(tasks["LEGAL"], "APPROVED")
    return decide_task(tasks["QUALITY"], "APPROVED")


# ---------------------------------------------------------------------------
# Composite: a version carried to APPROVED
# ---------------------------------------------------------------------------


def verified_version(brief_overrides=None, asset_overrides=None, **version_overrides):
    """An APPROVED brief, an asset under it and an ELEMENTS_VERIFIED version.

    Returns (brief, asset, version).
    """
    brief = new_approved_brief(**(brief_overrides or {}))
    asset = new_asset(brief["id"], **(asset_overrides or {}))
    version = new_version(asset, **version_overrides)
    version = verify(version["id"])
    return brief, asset, version


def approved_version(brief_overrides=None, asset_overrides=None, **version_overrides):
    """A version carried all the way to APPROVED through a full routing pass.

    Returns (brief, asset, version) with the version re-read after the cascade.
    """
    brief, asset, version = verified_version(
        brief_overrides, asset_overrides, **version_overrides
    )
    submit(version["id"])
    approve_all_stages(version["id"])
    return read_brief(brief["id"]), read_asset(asset["id"]), read_version(version["id"])


def in_review_version(brief_overrides=None, asset_overrides=None, **version_overrides):
    """A version sitting IN_REVIEW on an open pass. Returns (brief, asset, version)."""
    brief, asset, version = verified_version(
        brief_overrides, asset_overrides, **version_overrides
    )
    version = submit(version["id"])
    return brief, asset, version


def superseding_version(asset, predecessor, **overrides) -> dict:
    """A second version that supersedes its predecessor and is carried to APPROVED.

    On approval the cascade repoints the asset, moves it to SUPERSEDE_PENDING and
    drops the predecessor to OBSOLETE_PENDING.
    """
    successor = new_version(
        read_asset(_id(asset)),
        supersedes_version_id=_id(predecessor),
        reason_for_change_code="ERROR_CORRECTION",
        change_description="Second production revision superseding the first.",
        **overrides,
    )
    verify(successor["id"])
    submit(successor["id"])
    approve_all_stages(successor["id"])
    return read_version(successor["id"])


def asset_with_obsolete_predecessor(
    brief_overrides=None, asset_overrides=None, **version_overrides
):
    """v1 APPROVED then superseded by v2, so v1 is OBSOLETE_PENDING.

    Returns (brief, asset, v1, v2) with every row re-read after the cascade.
    """
    brief, asset, v1 = approved_version(
        brief_overrides, asset_overrides, **version_overrides
    )
    v2 = superseding_version(asset, v1)
    return (
        read_brief(brief["id"]),
        read_asset(asset["id"]),
        read_version(v1["id"]),
        v2,
    )


# ---------------------------------------------------------------------------
# Printers
# ---------------------------------------------------------------------------


def new_printer(**overrides) -> dict:
    return get_success_data(
        api_client.create_printer(create_printer_payload(**overrides), admin())
    )


def read_printer(printer_id) -> dict:
    return get_success_data(api_client.get_printer(_id(printer_id), coord()))


# ---------------------------------------------------------------------------
# Printer proofs
# ---------------------------------------------------------------------------


def new_proof(version_id, printer, **overrides) -> dict:
    """The vendor submits a proof, acting as its own Printer row."""
    return get_success_data(
        api_client.create_printer_proof(
            create_printer_proof_payload(_id(version_id), _id(printer), **overrides),
            printer_as(printer),
        )
    )


def read_proof(proof_id) -> dict:
    return get_success_data(api_client.get_printer_proof(_id(proof_id), coord()))


def proofs_for_version(version_id) -> list:
    return get_success_data(
        api_client.list_printer_proofs(
            coord(), params={"artwork_version_id": _id(version_id), "limit": 100}
        )
    )


def decide_color(proof_id, measured_delta_e_max=1.2, **overrides) -> dict:
    return get_success_data(
        api_client.decide_proof_color(
            _id(proof_id),
            color_decision_payload(measured_delta_e_max, **overrides),
            quality(),
        )
    )


def decide_substrate(proof_id, decision="SUBSTRATE_APPROVED", **overrides) -> dict:
    return get_success_data(
        api_client.decide_proof_substrate(
            _id(proof_id), substrate_decision_payload(decision, **overrides), quality()
        )
    )


def book_press_check(proof_id, **overrides) -> dict:
    return get_success_data(
        api_client.book_press_check(
            _id(proof_id), press_check_payload(**overrides), quality()
        )
    )


def press_check_window_for(proof) -> dict:
    """A press-check window unique to the proof's ordinal.

    Windows one calendar day apart never collide once each is widened by the
    120-minute buffer on both sides.
    """
    day = 9 + proof["proof_no"]
    return {
        "press_check_start_utc": f"2026-09-{day:02d}T08:00:00Z",
        "press_check_end_utc": f"2026-09-{day:02d}T12:00:00Z",
    }


def approved_proof(version_id, printer, **overrides) -> dict:
    """A proof driven to PROOF_APPROVED on all three dimensions.

    The press-check track is only touched when the proof actually requires one.
    """
    proof = new_proof(version_id, printer, **overrides)
    if proof["press_check_required"]:
        book_press_check(proof["id"], **press_check_window_for(proof))
    decide_substrate(proof["id"], "SUBSTRATE_APPROVED")
    tolerance = proof["effective_tolerance"]
    decide_color(proof["id"], min(1.2, tolerance))
    return read_proof(proof["id"])


def released_version(brief_overrides=None, asset_overrides=None, **version_overrides):
    """A version carried to RELEASED_TO_PRINT behind an approved proof.

    Returns (brief, asset, version, printer, proof).
    """
    brief, asset, version = approved_version(
        brief_overrides, asset_overrides, **version_overrides
    )
    printer = new_printer()
    proof = approved_proof(version["id"], printer)
    version = release(version["id"])
    return brief, read_asset(asset["id"]), version, read_printer(printer["id"]), proof


# ---------------------------------------------------------------------------
# Plate orders
# ---------------------------------------------------------------------------


def new_plate_order(version_id, printer, proof, plate_set_count=6, **overrides) -> dict:
    return get_success_data(
        api_client.create_plate_order(
            create_plate_order_payload(
                _id(version_id),
                _id(printer),
                _id(proof),
                plate_set_count=plate_set_count,
                **overrides,
            ),
            coord(),
        )
    )


def read_plate_order(order_id) -> dict:
    return get_success_data(api_client.get_plate_order(_id(order_id), coord()))


def plate_orders_for_version(version_id) -> list:
    return get_success_data(
        api_client.list_plate_orders(
            coord(), params={"artwork_version_id": _id(version_id), "limit": 100}
        )
    )


def cancel_plate_order(order_id, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_plate_order(
            _id(order_id), cancel_plate_order_payload(**overrides), coord()
        )
    )


# ---------------------------------------------------------------------------
# Inventory runouts
# ---------------------------------------------------------------------------


def new_runout(asset, obsolete_version, on_hand_qty=5000, weekly_usage_qty=1200,
               **overrides) -> dict:
    return get_success_data(
        api_client.create_inventory_runout(
            create_inventory_runout_payload(
                _id(asset),
                _id(obsolete_version),
                on_hand_qty=on_hand_qty,
                weekly_usage_qty=weekly_usage_qty,
                **overrides,
            ),
            coord(),
        )
    )


def read_runout(runout_id) -> dict:
    return get_success_data(api_client.get_inventory_runout(_id(runout_id), coord()))


def depletion(week_start_utc, units_consumed) -> dict:
    return {"week_start_utc": week_start_utc, "units_consumed": units_consumed}


def append_depletion(runout_id, records) -> dict:
    """Append weekly actuals. `records` is a list of depletion() objects."""
    return get_success_data(
        api_client.append_depletion_records(
            _id(runout_id), depletion_records_payload(records), coord()
        )
    )


def disposition_runout(runout_id, disposition="RUNOUT", **overrides) -> dict:
    return get_success_data(
        api_client.disposition_runout(
            _id(runout_id), disposition_payload(disposition, **overrides), coord()
        )
    )


def reverse_disposition(runout_id, **overrides) -> dict:
    return get_success_data(
        api_client.reverse_runout_disposition(
            _id(runout_id), disposition_reversal_payload(**overrides), admin()
        )
    )


def scrapped_runout(on_hand_qty=20000, weekly_usage_qty=3000, consumed=(3333, 3333),
                    units_scrapped=10000, units_reworked=3334, **asset_overrides):
    """A SCRAP-dispositioned runout on an obsolete predecessor version.

    Returns (brief, asset, v1, v2, runout) with every row re-read afterwards.
    """
    brief, asset, v1, v2 = asset_with_obsolete_predecessor(
        asset_overrides=asset_overrides or None
    )
    runout = new_runout(
        asset, v1, on_hand_qty=on_hand_qty, weekly_usage_qty=weekly_usage_qty
    )
    weeks = ["2026-08-03T00:00:00Z", "2026-08-10T00:00:00Z", "2026-08-17T00:00:00Z"]
    append_depletion(
        runout["id"],
        [depletion(weeks[i], qty) for i, qty in enumerate(consumed)],
    )
    runout = disposition_runout(
        runout["id"],
        "SCRAP",
        units_scrapped=units_scrapped,
        units_reworked=units_reworked,
    )
    return (
        read_brief(brief["id"]),
        read_asset(asset["id"]),
        read_version(v1["id"]),
        read_version(v2["id"]),
        runout,
    )


# ---------------------------------------------------------------------------
# Error escapes
# ---------------------------------------------------------------------------


def new_escape(version_id, printer, discovered_stage="MARKET", units_affected=12500,
               **overrides) -> dict:
    return get_success_data(
        api_client.create_error_escape(
            create_error_escape_payload(
                _id(version_id),
                _id(printer),
                discovered_stage=discovered_stage,
                units_affected=units_affected,
                **overrides,
            ),
            quality(),
        )
    )


def read_escape(escape_id) -> dict:
    return get_success_data(api_client.get_error_escape(_id(escape_id), coord()))


def assign_root_cause(escape_id, root_cause_party="SHARED", printer_share_pct=0.65,
                      **overrides) -> dict:
    return get_success_data(
        api_client.assign_root_cause(
            _id(escape_id),
            root_cause_payload(root_cause_party, printer_share_pct, **overrides),
            quality(),
        )
    )


def raise_recovery_claim(escape, **overrides) -> dict:
    """Raise the provisional claim, pinning the escape's currently observed version."""
    escape_row = escape if isinstance(escape, dict) else read_escape(escape)
    return get_success_data(
        api_client.raise_recovery_claim(
            escape_row["id"],
            recovery_claim_payload(escape_row["version"], **overrides),
            quality(),
        )
    )


def dispute_escape(escape_id, printer, **overrides) -> dict:
    """Only the printer named on the escape may dispute the claim."""
    return get_success_data(
        api_client.dispute_escape(
            _id(escape_id), dispute_payload(**overrides), printer_as(printer)
        )
    )


def settle_escape(escape_id, resolution="SETTLED", **overrides) -> dict:
    return get_success_data(
        api_client.settle_escape(
            _id(escape_id), settle_payload(resolution, **overrides), admin()
        )
    )


def root_caused_escape(
    discovered_stage="MARKET",
    units_affected=12500,
    root_cause_party="SHARED",
    printer_share_pct=0.65,
    **version_kwargs,
):
    """An escape on a RELEASED_TO_PRINT version, sitting in ROOT_CAUSE_ASSIGNED.

    Returns (asset, version, printer, escape).
    """
    _brief, asset, version, printer, _proof = released_version(**version_kwargs)
    escape = new_escape(
        version["id"],
        printer,
        discovered_stage=discovered_stage,
        units_affected=units_affected,
    )
    escape = assign_root_cause(
        escape["id"], root_cause_party, printer_share_pct
    )
    return read_asset(asset["id"]), version, read_printer(printer["id"]), escape


def claimed_escape(
    discovered_stage="MARKET",
    units_affected=12500,
    root_cause_party="SHARED",
    printer_share_pct=0.65,
    **version_kwargs,
):
    """An escape whose provisional claim has been raised — state RECOVERY_CLAIMED.

    Returns (asset, version, printer, escape).
    """
    asset, version, printer, escape = root_caused_escape(
        discovered_stage=discovered_stage,
        units_affected=units_affected,
        root_cause_party=root_cause_party,
        printer_share_pct=printer_share_pct,
        **version_kwargs,
    )
    escape = raise_recovery_claim(escape)
    return asset, version, read_printer(printer["id"]), escape
