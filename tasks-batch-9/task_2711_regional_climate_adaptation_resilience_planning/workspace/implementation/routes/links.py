"""PRD 3.6 -- attributing avoided annual loss to protected lifeline assets."""

from flask import Blueprint

import envelope
import lookup
import serialize
import store
import validate
from auth import ROLE_PROJECT_SPONSOR, guard, require_owned_jurisdiction
from errors import fail

bp = Blueprint("links", __name__)


@bp.post("/resilience/projects/<project_id>/asset-links")
@guard(ROLE_PROJECT_SPONSOR)
def create_link(project_id):
    project = lookup.need("project", project_id)
    body = validate.json_body()
    asset = lookup.need_ref("asset", body, "asset_id")
    if asset is None:
        validate.bad("asset_id", "is required.")
    require_owned_jurisdiction(project["jurisdiction_id"], roles=(ROLE_PROJECT_SPONSOR,))

    avoided = validate.int_field(
        body, "avoided_loss_annual_cents", required=True, minimum=0
    )
    reaches = validate.bool_field(body, "benefit_reaches_disadvantaged")

    if project["screening_status"] != "SCREENED_IN":
        fail("ERR_PROJECT_NOT_SCREENED_IN", "The project is not SCREENED_IN.")
    existing = lookup.links_of(project["id"])
    for row in existing:
        if row["asset_id"] == asset["id"]:
            fail("ERR_DUPLICATE_ASSET_LINK", "This asset is already linked to the project.")

    if reaches is None:
        owner = store.jurisdictions.get(asset["jurisdiction_id"])
        reaches = bool(owner["disadvantaged_flag"]) if owner else False

    record = store.insert(
        store.links,
        {
            "project_id": project["id"],
            "asset_id": asset["id"],
            "avoided_loss_annual_cents": avoided,
            "benefit_reaches_disadvantaged": reaches,
            "link_sequence": len(existing) + 1,
        },
        common_fields=False,
    )

    # a new link changes the benefit input set of an already-certified analysis
    certified = lookup.certified_analysis(project["id"])
    if certified is not None:
        certified["status"] = "STALE"
        certified["stale_reason"] = "LINK_ADDED"
        store.touch(certified)
        if project["analysis_status"] == "BCA_CERTIFIED":
            project["analysis_status"] = "BCA_STALE"
            store.touch(project)

    return envelope.created(serialize.link(record))


@bp.get("/resilience/asset-links")
@guard()
def list_links():
    rows = envelope.match(
        store.ordered(store.links),
        project_id=envelope.str_filter("project_id"),
        asset_id=envelope.str_filter("asset_id"),
        benefit_reaches_disadvantaged=envelope.bool_filter("benefit_reaches_disadvantaged"),
    )
    return envelope.listing(rows, serialize.link)


@bp.get("/resilience/asset-links/<link_id>")
@guard()
def get_link(link_id):
    row = lookup.need("link", link_id)
    return envelope.ok(serialize.link(row))
